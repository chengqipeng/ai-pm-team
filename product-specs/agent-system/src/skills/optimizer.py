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
        skills_dir: str = "./skills/auto-generated",
        skill_registry: Any = None,
        optimize_threshold: int = 5,
    ) -> None:
        self._llm = llm
        self._tracker = tracker
        self._skills_dir = Path(skills_dir)
        self._skill_registry = skill_registry
        self._optimize_threshold = optimize_threshold

    async def generate_from_conversation(self, messages: list, min_tool_calls: int = 5) -> str | None:
        """LLM 驱动的技能生成（替代规则提取）

        Returns:
            生成的 SKILL.md 文件路径，失败返回 None
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

            # 验证并保存
            from src.skills.base import SkillLoader
            skill = SkillLoader.parse(content)
            if not skill.name:
                skill.name = f"auto-{int(time.time())}"
            SkillLoader.validate(skill)

            skill_dir = self._skills_dir / skill.name
            skill_dir.mkdir(parents=True, exist_ok=True)
            skill_path = skill_dir / "SKILL.md"
            skill_path.write_text(content, encoding="utf-8")

            # 注册
            if self._skill_registry:
                skill_def = SkillLoader.load(str(skill_path))
                self._skill_registry.register(skill_def)

            logger.info("LLM 生成技能: %s → %s", skill.name, skill_path)
            return str(skill_path)

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

    async def optimize(self, skill_name: str) -> bool:
        """优化技能 — 分析执行轨迹，用 LLM 改写 SKILL.md

        Returns:
            是否成功优化（True=已改写，False=无需改进或失败）
        """
        metrics = self._tracker.get_metrics(skill_name)
        if metrics is None:
            return False

        # 读取当前 SKILL.md
        skill_path = self._skills_dir / skill_name / "SKILL.md"
        if not skill_path.exists():
            # 尝试从 skills/definitions 查找
            alt_path = Path("skills/definitions") / skill_name / "SKILL.md"
            if alt_path.exists():
                skill_path = alt_path
            else:
                logger.warning("技能文件不存在: %s", skill_path)
                return False

        skill_content = skill_path.read_text(encoding="utf-8")

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
            from src.skills.base import SkillLoader
            new_skill = SkillLoader.parse(content)
            SkillLoader.validate(new_skill)

            # 备份旧版本
            backup_path = skill_path.with_suffix(f".v{metrics.version}.md.bak")
            backup_path.write_text(skill_content, encoding="utf-8")

            # 写入新版本
            skill_path.write_text(content, encoding="utf-8")

            # 更新注册
            if self._skill_registry:
                new_skill_def = SkillLoader.load(str(skill_path))
                self._skill_registry.register(new_skill_def)

            logger.info("技能优化完成: %s (v%d → v%d)", skill_name,
                        metrics.version, metrics.version + 1)
            return True

        except Exception as e:
            logger.error("技能优化失败: %s — %s", skill_name, e)
            return False

    async def cleanup_retiring(self) -> list[str]:
        """清理应该淘汰的技能"""
        retiring = self._tracker.get_retiring_skills()
        removed = []
        for name in retiring:
            skill_dir = self._skills_dir / name
            if skill_dir.exists():
                import shutil
                shutil.rmtree(skill_dir)
                removed.append(name)
                if self._skill_registry:
                    self._skill_registry.unregister(name)
                logger.info("淘汰技能: %s", name)
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
