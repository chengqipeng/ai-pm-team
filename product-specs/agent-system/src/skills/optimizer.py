"""技能优化器 — LLM 驱动的技能自改进

SkillOptimizer: 分析执行轨迹，用 LLM 改写 SKILL.md
- 评估执行质量（SOP 覆盖率、工具调用合理性、输出完整性）
- 生成改进版 SKILL.md
- 版本管理（保留历史版本）
"""
from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any

from .tracker import SkillTracker, SkillExecution, SkillMetrics

logger = logging.getLogger(__name__)

_EVALUATE_PROMPT = """你是一个技能优化专家。请评估以下技能的执行质量，并输出改进后的 SKILL.md。

## 当前技能定义
```
{skill_content}
```

## 最近 {n} 次执行轨迹
{executions}

## 度量数据
- 总执行次数: {total_executions}
- 成功率: {success_rate:.0%}
- 平均 token 消耗: {avg_tokens:.0f}
- 平均耗时: {avg_duration_ms:.0f}ms

## 评估要求
1. SOP 步骤是否都被执行了？遗漏的步骤应该删除还是强调？
2. 工具调用顺序是否合理？有没有多余或缺失的调用？
3. 参数是否有硬编码应该参数化的值？
4. description 和 when_to_use 是否准确反映了实际使用场景？
5. 输出格式是否需要调整？

## 输出要求
如果需要改进，输出完整的 SKILL.md 内容（包含 --- frontmatter ---）。
如果不需要改进，只输出 "NO_CHANGE"。"""

_GENERATE_PROMPT = """分析以下对话，提取可复用的任务模式，生成 SKILL.md。

要求：
1. name: 用 kebab-case 命名，反映任务本质
2. description: 一句话描述，让 LLM 能判断何时调用
3. when_to_use: 触发关键词（|分隔），覆盖用户可能的表述方式
4. arguments: 参数化可变部分（如实体名、筛选条件、时间范围）
5. allowed-tools: 只列实际使用的工具
6. context: inline（主 Agent 内执行）或 fork（独立子 Agent）
7. prompt: 写成 SOP 步骤，每步说明：
   - 调哪个工具
   - 传什么参数（用 {{arg}} 占位符）
   - 期望什么结果
   - 异常时如何处理

对话内容：
{conversation}

输出完整的 SKILL.md 内容（包含 --- frontmatter ---）："""


class SkillOptimizer:
    """技能优化器 — LLM 驱动的自改进

    Args:
        llm: LLM 实例（需实现 ainvoke）
        tracker: SkillTracker 实例
        skills_dir: 技能文件目录
        skill_registry: 可选的 SkillRegistry
        optimize_threshold: 执行 N 次后触发优化
    """

    def __init__(
        self,
        llm: Any,
        tracker: SkillTracker,
        skill_registry: Any = None,
        optimize_threshold: int = 5,
        skills_dir: str | None = None,  # 兼容参数，已废弃
    ) -> None:
        self._llm = llm
        self._tracker = tracker
        self._skill_registry = skill_registry
        self._optimize_threshold = optimize_threshold
        # skills_dir 保留用于兼容旧调用方，不再使用
        self._skills_dir = Path(skills_dir) if skills_dir else None

    async def generate_from_conversation(self, messages: list, min_tool_calls: int = 5,
                                            tenant_id: int = 0) -> str | None:
        """LLM 驱动的技能生成，直接落库到 ai_skill_definition

        Returns:
            生成的 Skill api_key，失败返回 None
        """
        from langchain_core.messages import ToolMessage

        tool_count = sum(1 for m in messages if isinstance(m, ToolMessage))
        if tool_count < min_tool_calls:
            return None

        conversation = self._format_messages(messages)
        prompt = _GENERATE_PROMPT.format(conversation=conversation)

        try:
            result = await self._llm.ainvoke(prompt)
            content = getattr(result, "content", None) or str(result)
            content = content.strip()

            if not content.startswith("---"):
                logger.warning("LLM 生成的内容不是有效的 SKILL.md 格式")
                return None

            # 解析并验证
            from src.skills.base import SkillLoader
            skill = SkillLoader.parse(content)
            if not skill.name:
                skill.name = f"auto-{int(time.time())}"
            SkillLoader.validate(skill)
            skill.owner = skill.owner or "auto-generated"
            skill.tenant_id = tenant_id

            # 落库（发布状态）+ 注册到内存
            if self._skill_registry is not None:
                self._skill_registry.upsert_to_db(
                    skill, tenant_id=tenant_id, status="published",
                    changelog="auto-generated from conversation",
                )
                self._skill_registry.register(skill)
            else:
                # 降级：直接调 DAO
                from src.skills.base import SkillRegistry
                tmp = SkillRegistry()
                tmp.upsert_to_db(skill, tenant_id=tenant_id, status="published",
                                  changelog="auto-generated from conversation")

            logger.info("LLM 生成技能: api_key=%s (tenant=%d) → ai_skill_definition",
                        skill.name, tenant_id)
            return skill.name

        except Exception as e:
            logger.error("LLM 技能生成失败: %s", e)
            return None

    async def should_optimize(self, skill_name: str) -> bool:
        """判断是否应该触发优化"""
        metrics = self._tracker.get_metrics(skill_name)
        if metrics is None:
            return False
        # 执行次数达到阈值的整数倍时触发
        return (metrics.total_executions > 0 and
                metrics.total_executions % self._optimize_threshold == 0)

    async def optimize(self, skill_name: str, tenant_id: int = 0) -> bool:
        """优化技能 — 分析执行轨迹，用 LLM 改写 Skill，结果直接落库

        Returns:
            是否成功优化（True=已改写并发布新版，False=无需改进或失败）
        """
        metrics = self._tracker.get_metrics(skill_name)
        if metrics is None:
            return False

        # 读取当前 Skill（从内存或 DB）
        from src.skills.base import SkillLoader, SkillDefinition
        from src.store.skill_dao import SkillDefinitionDAO

        skill_content = ""
        current_version = getattr(metrics, "version", 1)
        current_row = SkillDefinitionDAO.get_by_api_key(tenant_id, skill_name)
        if current_row is not None:
            skill_content = _compose_skill_md(current_row)
            try:
                # 解析 "1.0.0" → 取 patch 号
                parts = (current_row.version or "1.0.0").split(".")
                current_version = int(parts[-1]) if parts[-1].isdigit() else current_version
            except Exception:
                logger.exception("optimize 异常")
        else:
            logger.warning("DB 中找不到 Skill '%s'，跳过优化", skill_name)
            return False

        # 获取最近执行轨迹
        executions = self._tracker.get_executions(skill_name, limit=5)
        exec_text = self._format_executions(executions)

        # 构建评估 prompt
        prompt = _EVALUATE_PROMPT.format(
            skill_content=skill_content,
            n=len(executions),
            executions=exec_text,
            total_executions=metrics.total_executions,
            success_rate=metrics.success_rate,
            avg_tokens=metrics.avg_tokens,
            avg_duration_ms=metrics.avg_duration_ms,
        )

        try:
            result = await self._llm.ainvoke(prompt)
            content = getattr(result, "content", None) or str(result)
            content = content.strip()

            if content == "NO_CHANGE" or not content.startswith("---"):
                logger.info("技能 '%s' 无需优化", skill_name)
                return False

            # 验证新版本
            new_skill = SkillLoader.parse(content)
            if not new_skill.name:
                new_skill.name = skill_name
            SkillLoader.validate(new_skill)

            # 递增版本号 — 保守策略：patch +1
            new_version = _bump_patch(current_row.version or "1.0.0")
            new_skill.version = new_version
            new_skill.tenant_id = tenant_id
            new_skill.owner = current_row.owner or new_skill.owner

            # 发布新版本到 DB
            if self._skill_registry is not None:
                self._skill_registry.upsert_to_db(
                    new_skill, tenant_id=tenant_id, status="published",
                    changelog=f"LLM 自动优化 v{current_row.version} → v{new_version}",
                )
                self._skill_registry.register(new_skill)

            logger.info("技能优化完成并落库: %s (v%s → v%s)",
                        skill_name, current_row.version, new_version)
            return True

        except Exception as e:
            logger.error("技能优化失败: %s — %s", skill_name, e)
            return False

    async def cleanup_retiring(self, tenant_id: int = 0) -> list[str]:
        """清理应该淘汰的技能 — DB 软删除 + 内存反注册"""
        from src.store.skill_dao import SkillDefinitionDAO

        retiring = self._tracker.get_retiring_skills()
        removed = []
        for name in retiring:
            try:
                SkillDefinitionDAO.soft_delete(tenant_id, name)
                removed.append(name)
                if self._skill_registry:
                    self._skill_registry.unregister(name)
                logger.info("淘汰技能: %s (tenant=%d)", name, tenant_id)
            except Exception as exc:
                logger.warning("淘汰技能失败 %s: %s", name, exc)
        return removed

    @staticmethod
    def _format_messages(messages: list) -> str:
        lines = []
        for msg in messages:
            role = getattr(msg, "type", "unknown")
            content = getattr(msg, "content", "")
            if isinstance(content, str) and content.strip():
                lines.append(f"[{role}]: {content[:300]}")
            tool_calls = getattr(msg, "tool_calls", None)
            if tool_calls:
                for tc in tool_calls:
                    lines.append(f"  → 调用工具: {tc.get('name', '')}({tc.get('args', {})})")
        return "\n".join(lines[-30:])  # 最多 30 行

    @staticmethod
    def _format_executions(executions: list[SkillExecution]) -> str:
        lines = []
        for i, ex in enumerate(executions, 1):
            lines.append(f"### 执行 #{i} (feedback={ex.user_feedback}, tokens={ex.total_tokens}, {ex.duration_ms:.0f}ms)")
            for tc in ex.tool_calls[:5]:
                status = "✅" if tc.get("success", True) else "❌"
                lines.append(f"  {status} {tc.get('name', '')} ({tc.get('duration_ms', 0):.0f}ms)")
            if ex.output:
                lines.append(f"  输出: {ex.output[:200]}")
        return "\n".join(lines)


# ═══════════════════════════════════════════════════════════
# 辅助函数 — 把 DB 行拼成 SKILL.md 供 LLM 阅读；版本号递增
# ═══════════════════════════════════════════════════════════

def _compose_skill_md(row) -> str:
    """SkillDefinitionRow → SKILL.md 文本（仅用于 LLM 评估，不落盘）"""
    import json as _json
    try:
        allowed_tools = _json.loads(row.allowed_tools or "[]")
    except Exception:
        allowed_tools = []
    try:
        arguments = _json.loads(row.arguments or "[]")
    except Exception:
        arguments = []
    fm_lines = [
        "---",
        f"name: {row.api_key}",
        f"description: {row.description}",
        f"when_to_use: {row.when_to_use or ''}",
        f"context: {row.context}",
    ]
    if row.agent:
        fm_lines.append(f"agent: {row.agent}")
    if arguments:
        fm_lines.append("arguments:")
        for a in arguments:
            fm_lines.append(f"  - {a}")
    else:
        fm_lines.append("arguments: []")
    if allowed_tools:
        fm_lines.append("allowed-tools:")
        for t in allowed_tools:
            fm_lines.append(f"  - {t}")
    else:
        fm_lines.append("allowed-tools: []")
    fm_lines.append(f"version: {row.version}")
    fm_lines.append("---")
    return "\n".join(fm_lines) + "\n\n" + (row.prompt or "")


def _bump_patch(version: str) -> str:
    """1.2.3 → 1.2.4，解析失败时退回 '{v}.1'"""
    parts = (version or "1.0.0").split(".")
    try:
        nums = [int(p) for p in parts]
        while len(nums) < 3:
            nums.append(0)
        nums[-1] += 1
        return ".".join(str(n) for n in nums[:3])
    except ValueError:
        return f"{version}.1"
