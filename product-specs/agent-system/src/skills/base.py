"""
Skills 体系 — SkillDefinition + SkillRegistry + SkillExecutor + SkillsTool

对应 design.md §6: Skills 系统
- SkillDefinition: 技能数据结构（name/prompt/context/allowed_tools/agent）
- SkillRegistry: 注册/查找/按 context 筛选
- SkillExecutor: 路由 inline / fork(通用) / fork(指定agent)
- SkillsTool: 注册到 ToolRegistry，LLM 通过 function calling 调用
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Awaitable

from src.core.dtypes import ToolResult, Message, MessageRole
from src.core.exceptions import SkillExecutionError
from src.tools.base import Tool

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════
# SkillDefinition
# ═══════════════════════════════════════════════════════════

@dataclass
class SkillDefinition:
    """
    技能定义 — 对应 design.md §6.1 Skill 数据模型

    context="inline": prompt 作为工具返回值注入当前对话，LLM 按 SOP 继续执行
    context="fork":   创建独立子 Agent 执行，返回结果
    """
    name: str                                    # 技能唯一标识
    description: str                             # 一句话描述（必填，用于 LLM 判断何时调用）
    prompt: str = ""                             # 技能提示词（Markdown body）
    when_to_use: str = ""                        # 何时使用（注入 system prompt）
    arguments: list[str] = field(default_factory=list)       # 命名参数列表
    allowed_tools: list[str] = field(default_factory=list)   # 额外允许的工具
    model: str = ""                              # 指定模型（空=继承主模型）
    context: str = "inline"                      # inline | fork
    agent: str = ""                              # fork 模式下指定的子 Agent 名称
    # 扩展字段（DB 版本引入；内存构造也可以保持默认）
    version: str = "1.0.0"
    requires_confirmation: bool = False
    max_tool_calls: int = 20
    timeout_ms: int = 60000
    owner: str = ""
    output_mode: str = "text"
    component_apikey: str = ""
    post_output_behavior: str = "silent"         # silent | summarize | continue | passthrough
    tenant_id: int = 0                           # 0 = 平台级

    # 系统变量名（通过 ${VAR} 语法注入，不属于用户参数）
    _SYSTEM_VAR_NAMES = frozenset({"SKILL_DIR", "SKILL_NAME", "SKILL_TMP_DIR", "SKILL_OUTPUT_DIR"})

    def format_prompt(self, arguments: dict[str, str], system_vars: dict[str, str] | None = None) -> str:
        """替换 prompt 中的占位符

        支持两类变量：
        - {arg_name} — 用户传入的命名参数
        - ${SYSTEM_VAR} — 系统变量（如 SKILL_DIR、SKILL_NAME）

        校验规则：
        - 传入的参数在 prompt 中没有对应占位符时，打告警日志并跳过（不阻断执行）
        - prompt 中残留未替换的 {占位符} 打告警日志（不阻断执行）
        """
        import re

        result = self.prompt

        # 1. 替换系统变量 ${VAR_NAME}
        if system_vars:
            for key, value in system_vars.items():
                result = result.replace(f"${{{key}}}", str(value))

        # 2. 替换用户参数 {arg_name}，找不到占位符时仅告警
        for key, value in arguments.items():
            if key in self._SYSTEM_VAR_NAMES:
                continue
            if f"{{{key}}}" not in result:
                logger.warning("参数 '%s' 在 prompt 中未找到 {%s} 占位符，已跳过", key, key)
                continue
            result = result.replace(f"{{{key}}}", str(value))

        # 3. 检查 prompt 中是否残留未替换的 {占位符}（仅告警）
        remaining = re.findall(r'(?<!\$)\{([a-zA-Z_][a-zA-Z0-9_]*)\}', result)
        if remaining:
            missing = [r for r in remaining if r not in self._SYSTEM_VAR_NAMES]
            if missing:
                logger.warning("prompt 中存在未提供值的占位符: %s", ", ".join("{" + m + "}" for m in missing))

        return result

    @classmethod
    def from_db_row(cls, row: "Any") -> "SkillDefinition":
        """从 ai_skill_definition 行（SkillDefinitionRow）构建运行时对象"""
        import json
        try:
            allowed_tools = json.loads(row.allowed_tools or "[]")
            if not isinstance(allowed_tools, list):
                allowed_tools = []
        except (json.JSONDecodeError, TypeError):
            allowed_tools = []
        try:
            arguments = json.loads(row.arguments or "[]")
            if not isinstance(arguments, list):
                arguments = []
        except (json.JSONDecodeError, TypeError):
            arguments = []
        skill = cls(
            name=getattr(row, 'api_key', None) or getattr(row, 'skill_api_key', ''),
            description=row.description or row.name,
            prompt=row.prompt or "",
            when_to_use=row.when_to_use or "",
            arguments=[str(a) for a in arguments],
            allowed_tools=[str(t) for t in allowed_tools],
            model=row.model or "",
            context=row.context or "inline",
            agent=row.agent or "",
            version=row.version or "1.0.0",
            requires_confirmation=bool(row.requires_confirmation),
            max_tool_calls=row.max_tool_calls or 20,
            timeout_ms=row.timeout_ms or 60000,
            owner=getattr(row, "owner", "") or "",
            output_mode=getattr(row, "output_mode", "text") or "text",
            component_apikey=getattr(row, "component_apikey", "") or "",
            post_output_behavior=getattr(row, "post_output_behavior", "silent") or "silent",
            tenant_id=row.tenant_id or 0,
        )
        # 保留 ext_info 供 ResourcePreloader 使用（不作为 dataclass 字段，避免序列化问题）
        # ext_info 来自 ai_skill 主表（通过 list_active JOIN 获取），含 preload_resources 等配置
        raw_ext = getattr(row, "ext_info", None)
        skill._ext_info = raw_ext if raw_ext and raw_ext != "{}" else None
        return skill


# ═══════════════════════════════════════════════════════════
# SkillRegistry
# ═══════════════════════════════════════════════════════════

class SkillRegistry:
    """技能注册表 — 对应 design.md §6.3"""

    def __init__(self):
        self._skills: dict[str, SkillDefinition] = {}

    def register(self, skill: SkillDefinition) -> None:
        if skill.name in self._skills:
            logger.warning(f"Skill '{skill.name}' already registered, overwriting")
        self._skills[skill.name] = skill

    def get(self, name: str) -> SkillDefinition | None:
        return self._skills.get(name)

    def list_all(self) -> list[SkillDefinition]:
        return list(self._skills.values())

    def list_by_context(self, context: str) -> list[SkillDefinition]:
        return [s for s in self._skills.values() if s.context == context]

    def unregister(self, name: str) -> None:
        self._skills.pop(name, None)

    # ── DB 集成：运行时单一数据源 ──

    def load_from_db(self, tenant_id: int = 0, *, clear: bool = True,
                      include_platform: bool = True) -> int:
        """从 ai_skill_definition 表加载 enabled_flg=1 的技能

        Args:
            tenant_id: 目标租户；0 表示仅加载平台级
            clear: 是否清空现有内存注册（默认 True，保证加载后是 DB 的全量快照）
            include_platform: 是否把 tenant_id=0 的平台级技能并入结果
        Returns:
            加载到的技能数量
        """
        from src.store.skill_dao import SkillDefinitionDAO

        if clear:
            self._skills.clear()

        rows = SkillDefinitionDAO.list_active(
            tenant_id=tenant_id, include_platform=include_platform,
        )
        loaded = 0
        for row in rows:
            # 只加载启用的技能（兼容：enabled_flg 字段可能不存在时 fallback 到 status）
            enabled = getattr(row, "enabled_flg", None)
            if enabled is not None and enabled != 1:
                continue
            try:
                skill = SkillDefinition.from_db_row(row)
                self._skills[skill.name] = skill
                loaded += 1
            except Exception as exc:
                logger.warning("加载 Skill 失败 api_key=%s: %s",
                               getattr(row, 'api_key', None) or getattr(row, 'skill_api_key', '?'), exc)
        logger.info("SkillRegistry 从 DB 加载完成: tenant=%d, count=%d",
                    tenant_id, loaded)
        return loaded

    def upsert_to_db(self, skill: SkillDefinition, *, tenant_id: int | None = None,
                      status: str = "published", changelog: str = "",
                      published_by: int = 0) -> None:
        """把 SkillDefinition 持久化到 ai_skill_definition + ai_skill_version

        供 SkillInstaller / SkillOptimizer / SkillGenerator 使用。
        不会自动注册到内存，调用方决定是否 self.register(skill)。
        """
        import json
        import time

        from src.store.skill_dao import SkillDefinitionDAO, SkillVersionDAO
        from src.store.skill_models import SkillDefinitionRow, SkillVersionRow

        tid = tenant_id if tenant_id is not None else getattr(skill, "tenant_id", 0)
        now = int(time.time() * 1000)
        row = SkillDefinitionRow(
            api_key=skill.name,
            tenant_id=tid,
            name=skill.name,
            description=skill.description,
            when_to_use=skill.when_to_use,
            owner=getattr(skill, "owner", ""),
            context=skill.context,
            agent=skill.agent,
            model=skill.model,
            allowed_tools=json.dumps(skill.allowed_tools, ensure_ascii=False),
            arguments=json.dumps(skill.arguments, ensure_ascii=False),
            prompt=skill.prompt,
            requires_confirmation=1 if getattr(skill, "requires_confirmation", False) else 0,
            max_tool_calls=getattr(skill, "max_tool_calls", 20),
            timeout_ms=getattr(skill, "timeout_ms", 60000),
            version=getattr(skill, "version", "1.0.0"),
            status=status,
            published_at=now if status == "published" else 0,
            output_mode=getattr(skill, "output_mode", "text") or "text",
            component_apikey=getattr(skill, "component_apikey", "") or "",
            post_output_behavior=getattr(skill, "post_output_behavior", "silent") or "silent",
        )
        SkillDefinitionDAO.upsert(row)

        version_row = SkillVersionRow(
            tenant_id=tid,
            skill_api_key=skill.name,
            version=row.version,
            description=row.description,
            when_to_use=row.when_to_use,
            context=row.context,
            agent=row.agent,
            model=row.model,
            allowed_tools=row.allowed_tools,
            arguments=row.arguments,
            prompt=row.prompt,
            requires_confirmation=row.requires_confirmation,
            max_tool_calls=row.max_tool_calls,
            timeout_ms=row.timeout_ms,
            changelog=changelog,
            published_by=published_by,
        )
        SkillVersionDAO.insert(version_row)

    def match_by_intent(self, intent: str, tracker: Any = None) -> SkillDefinition | None:
        """按意图匹配技能 — 关键词粗筛 + 度量加权精排

        支持两种 when_to_use 格式：
        - 旧格式（竖线分隔关键词）: "创建技能|新建技能|保存为技能" → 子串匹配
        - 新格式（自然语言描述）: "当用户需要撰写商务邮件时使用" → 跳过规则匹配，由 LLM 自行判断

        Args:
            intent: 用户意图文本
            tracker: SkillTracker 实例（可选），用于度量加权
        """
        # 关键词粗筛
        candidates = []
        for skill in self._skills.values():
            if skill.when_to_use:
                # 判断格式：包含 | 且不是自然语言句子 → 旧格式关键词匹配
                if "|" in skill.when_to_use:
                    keywords = skill.when_to_use.split("|")
                    if any(kw.strip() in intent for kw in keywords if kw.strip()):
                        candidates.append(skill)
                # 新格式（自然语言）：不做规则匹配，由 LLM 在 system prompt 中自行决定
                # 此处不参与 match_by_intent 的规则筛选

        if not candidates:
            return None
        if len(candidates) == 1:
            return candidates[0]

        # 多个候选 → 度量加权精排
        if tracker is not None:
            def _score(skill: SkillDefinition) -> float:
                metrics = tracker.get_metrics(skill.name)
                if metrics is None:
                    return 0.5  # 新技能给中等分
                return metrics.success_rate
            candidates.sort(key=_score, reverse=True)

        return candidates[0]

    def build_skills_prompt_section(self) -> str:
        """生成注入 system prompt 的 <skills> 标签内容"""
        if not self._skills:
            return ""
        lines = ["\n## 可用技能（通过 skills_tool 调用）"]
        for s in self._skills.values():
            args_str = ", ".join(s.arguments) if s.arguments else "无"
            lines.append(f"- **{s.name}**: {s.description}")
            if s.when_to_use:
                lines.append(f"  使用时机: {s.when_to_use}")
            lines.append(f"  参数: {args_str} | 模式: {s.context}")
        lines.append("")
        lines.append("调用方式: skills_tool(skill_name=\"技能名\", arguments={\"参数名\": \"值\"})")
        return "\n".join(lines)


# ═══════════════════════════════════════════════════════════
# SkillLoader — 从 SKILL.md 文件加载技能
# ═══════════════════════════════════════════════════════════

class SkillValidationError(Exception):
    def __init__(self, message: str, errors: list[str] | None = None):
        super().__init__(message)
        self.errors = errors or []


class SkillLoader:
    """
    技能文件加载器 — 对应 design.md §6.3

    从 SKILL.md 文件加载技能定义:
    - discover(skills_dir): 扫描目录下所有 SKILL.md
    - load(skill_path): 加载单个 SKILL.md
    - parse(content): 解析 frontmatter + body
    - validate(skill): 校验必填字段和格式
    """

    @staticmethod
    def discover(skills_dir: str) -> list[SkillDefinition]:
        """扫描目录下所有子目录的 SKILL.md 文件"""
        from pathlib import Path
        skills = []
        base = Path(skills_dir)
        if not base.is_dir():
            return skills

        for skill_md in base.rglob("SKILL.md"):
            try:
                skill = SkillLoader.load(str(skill_md))
                skills.append(skill)
            except (SkillValidationError, Exception) as e:
                logger.warning(f"Failed to load {skill_md}: {e}")
        return skills

    @staticmethod
    def load(skill_path: str) -> SkillDefinition:
        """加载单个 SKILL.md 文件"""
        from pathlib import Path
        path = Path(skill_path)
        if not path.exists():
            raise SkillValidationError(f"File not found: {skill_path}")

        content = path.read_text(encoding="utf-8")
        skill = SkillLoader.parse(content)

        # name 未指定时取目录名
        if not skill.name:
            skill.name = path.parent.name

        SkillLoader.validate(skill)
        return skill

    @staticmethod
    def parse(content: str) -> SkillDefinition:
        """解析 SKILL.md: YAML frontmatter + Markdown body"""
        import yaml

        content = content.strip()
        if not content.startswith("---"):
            raise SkillValidationError("SKILL.md must start with ---")

        # 分离 frontmatter 和 body
        parts = content.split("---", 2)
        if len(parts) < 3:
            raise SkillValidationError("SKILL.md frontmatter not closed (missing second ---)")

        fm_text = parts[1].strip()
        body = parts[2].strip()

        try:
            fm = yaml.safe_load(fm_text) or {}
        except yaml.YAMLError as e:
            raise SkillValidationError(f"YAML parse error: {e}")

        return SkillDefinition(
            name=fm.get("name", ""),
            description=fm.get("description", ""),
            prompt=body,
            when_to_use=fm.get("when_to_use", ""),
            arguments=fm.get("arguments", []),
            allowed_tools=fm.get("allowed-tools", fm.get("allowed_tools", [])),
            model=fm.get("model", ""),
            context=fm.get("context", "inline"),
            agent=fm.get("agent", ""),
        )

    @staticmethod
    def validate(skill: SkillDefinition) -> None:
        """校验技能定义"""
        errors = []
        if not skill.description:
            errors.append("description is required")
        if skill.context not in ("inline", "fork"):
            errors.append(f"context must be 'inline' or 'fork', got '{skill.context}'")
        if not isinstance(skill.arguments, list):
            errors.append("arguments must be a list")
        if not isinstance(skill.allowed_tools, list):
            errors.append("allowed-tools must be a list")
        if errors:
            raise SkillValidationError(f"Validation failed for '{skill.name}'", errors)


# ═══════════════════════════════════════════════════════════
# SkillExecutor — 路由 inline / fork
# ═══════════════════════════════════════════════════════════

class SkillExecutor:
    """
    技能执行调度器 — 对应 design.md §6.4

    inline: 返回 formatted_prompt，LLM 继续推理
    fork(通用): 创建子 Agent，用 skill.prompt 作为 system_prompt
    fork(指定agent): 加载 SubagentConfig 构建专属子 Agent
    """

    def __init__(self, registry: SkillRegistry, context: Any = None, subagent_registry: Any = None):
        self._registry = registry
        self._context = context  # PluginContext
        self._subagent_registry = subagent_registry  # SubagentRegistry
        self._agent_factory = None  # AgentFactory，由外部注入
        self._current_depth = 0     # 当前嵌套深度，由外部注入
        self._tracker = None        # SkillTracker，由外部注入
        self._optimizer = None      # SkillOptimizer，由外部注入
        self._last_fork_children: list[dict] = []  # fork 子 Agent 的 tool_call spans

    async def execute(
        self,
        skill_name: str,
        arguments: dict[str, str],
        parent_thread_id: str = "",
    ) -> str:
        """执行技能，返回结果文本 — 自动追踪 + 触发优化"""
        import time as _time

        skill = self._registry.get(skill_name)
        if not skill:
            raise SkillExecutionError(f"技能 '{skill_name}' 未注册")

        # 先同步脚本到沙盒，获取 SKILL_DIR 路径
        skill_dir = await self._sync_scripts_to_sandbox(skill)

        # 构建系统变量
        system_vars = {}
        if skill_dir:
            system_vars["SKILL_DIR"] = skill_dir
            system_vars["SKILL_NAME"] = skill.name
            system_vars["SKILL_TMP_DIR"] = f"{skill_dir}/tmp"
            system_vars["SKILL_OUTPUT_DIR"] = f"{skill_dir}/output"

        formatted_prompt = skill.format_prompt(arguments, system_vars=system_vars)
        logger.info(f"SkillExecutor: {skill_name} (context={skill.context})")

        start_ms = _time.monotonic() * 1000

        if skill.context == "inline":
            result = await self._execute_inline(skill, formatted_prompt)
        elif skill.context == "fork":
            result = await self._execute_fork(skill, formatted_prompt, arguments)
        else:
            raise SkillExecutionError(f"未知的 context 模式: {skill.context}")

        duration_ms = _time.monotonic() * 1000 - start_ms

        # 收集子 Agent 执行的 tool_call 详情（fork 模式）
        children = getattr(self, '_last_fork_children', []) if skill.context == "fork" else []
        self._last_fork_children = []  # 清除

        # 记录 skill 执行 tracing span
        self._record_skill_span(
            skill_name=skill_name,
            context_mode=skill.context,
            arguments=arguments,
            duration_ms=duration_ms,
            output_preview=result[:300] if result else "",
            parent_thread_id=parent_thread_id,
            children=children,
        )

        # 自动追踪执行轨迹
        if self._tracker is not None:
            try:
                from .tracker import SkillExecution
                self._tracker.record(SkillExecution(
                    skill_name=skill_name,
                    arguments=arguments,
                    tool_calls=[],
                    total_tokens=len(result) // 2,
                    duration_ms=duration_ms,
                    output=result[:500],
                    user_feedback="unknown",
                ))
            except Exception as e:
                logger.warning("SkillTracker record failed: %s", e)

        # 异步触发优化（不阻塞主流程）
        if self._optimizer is not None:
            try:
                import asyncio
                should = await self._optimizer.should_optimize(skill_name)
                if should:
                    asyncio.create_task(self._async_optimize(skill_name))
            except Exception as e:
                logger.warning("SkillOptimizer check failed: %s", e)

        return result

    @staticmethod
    def _record_skill_span(
        skill_name: str, context_mode: str, arguments: dict,
        duration_ms: float, output_preview: str, parent_thread_id: str,
        children: list | None = None,
    ) -> None:
        """记录 skill 执行 span 到 TracingMiddleware"""
        try:
            from src.middleware.tracing import tracing_middleware
            tracing_middleware._add("skill_execution", f"skill:{skill_name}", duration_ms,
                metadata={
                    "skill_name": skill_name,
                    "context_mode": context_mode,
                    "arguments": {k: v[:100] if isinstance(v, str) else v for k, v in arguments.items()},
                    "parent_thread_id": parent_thread_id,
                },
                input_data={
                    "skill_name": skill_name,
                    "context_mode": context_mode,
                    "arguments": arguments,
                },
                output_data={
                    "output_preview": output_preview[:200],
                    "duration_ms": round(duration_ms, 1),
                    "context_mode": context_mode,
                },
                detail=f"技能 {skill_name} ({context_mode}) · {round(duration_ms)}ms",
                children=children or [],
            )
        except Exception as e:
            logger.debug("Skill span record failed: %s", e)

    @staticmethod
    def _collect_sub_agent_spans(sub_thread_id: str) -> list[dict]:
        """从 TracingMiddleware 中收集子 Agent 的完整执行链路 spans

        fork 模式的子 Agent 运行在独立 thread 中，其 spans 被写入了子 thread_id。
        提取完整的执行步骤链路：context_build、middleware、llm_call、tool_call 等，
        按原始顺序保留，供前端展示子 Agent 的完整执行过程。
        """
        try:
            from src.middleware.tracing import tracing_middleware
            sub_spans = tracing_middleware.get_spans(sub_thread_id)
            logger.info("[skill] Collecting sub-agent spans: thread=%s, total=%d, types=%s",
                        sub_thread_id, len(sub_spans),
                        [s.get("type", "") for s in sub_spans[:20]])
            children = []
            for s in sub_spans:
                s_type = s.get("type", "")
                s_meta = s.get("metadata", {})
                # 跳过纯日志类中间件（AgentLogging / Tracing 自身）
                if s_type == "middleware":
                    mw_name = s_meta.get("middleware_name", "")
                    if mw_name in ("AgentLoggingMiddleware", "TracingMiddleware"):
                        continue
                # 跳过前端隐藏的类型（与主 Agent HIDDEN_SPAN_TYPES 一致）
                if s_type in ("llm_input", "intent_analysis", "request", "clarification", "memory_extract"):
                    continue
                child = {
                    "type": s_type,
                    "name": s.get("name", ""),
                    "duration_ms": s.get("duration_ms", 0),
                    "detail": s.get("detail", ""),
                    "input_data": s.get("input_data", {}),
                    "output_data": s.get("output_data", {}),
                    "metadata": {
                        "tool_name": s_meta.get("tool_name", ""),
                        "status": s_meta.get("status", s.get("status", "success")),
                        "middleware_name": s_meta.get("middleware_name", ""),
                        "phase": s_meta.get("phase", ""),
                        "has_effect": s_meta.get("has_effect", False),
                    },
                }
                children.append(child)
            # 清理子 Agent 的 spans（已合并到父级 children 中）
            tracing_middleware.clear(sub_thread_id)
            logger.info("[skill] Collected %d children from sub-agent %s", len(children), sub_thread_id)
            return children
        except Exception as e:
            logger.warning("[skill] _collect_sub_agent_spans failed: %s", e)
            return []

    async def _async_optimize(self, skill_name: str) -> None:
        """异步优化技能（不阻塞主流程）"""
        try:
            optimized = await self._optimizer.optimize(skill_name)
            if optimized:
                logger.info("技能 '%s' 已异步优化", skill_name)
        except Exception as e:
            logger.warning("异步优化失败: %s — %s", skill_name, e)

    async def _execute_inline(self, skill: SkillDefinition, prompt: str) -> str:
        """
        inline 模式 — 返回 prompt 文本，由 LLM 继续推理

        对应 design.md §6.4 inline 模式:
        prompt 作为工具返回值注入对话，LLM 根据 prompt 中的 SOP 继续调用 Tool
        """
        logger.info(f"Skill inline: {skill.name} ({len(prompt)} chars)")
        return prompt

    async def _execute_fork(
        self, skill: SkillDefinition, prompt: str, arguments: dict
    ) -> str:
        """fork 模式 — 通过 AgentFactory 构建子 Agent 并执行

        对齐 v2 SkillExecutor._execute_fork：
        - 与 AgentTool 共用同一套 AgentFactory.build() 逻辑
        - skill.agent 为空时用 "default"
        - skill.prompt 作为 HumanMessage（任务指令），不是 system_prompt
        - 支持资源预加载：根据 ext_info.preload_resources 配置，在子 Agent 启动前
          批量加载基础知识文件，减少子 Agent 的推理轮次
        """
        if self._agent_factory is None:
            raise SkillExecutionError(
                skill_name=skill.name if hasattr(skill, 'name') else "",
                detail="AgentFactory 未配置，无法执行 fork 模式技能",
            )

        # 防递归保护：如果当前深度已达上限，降级为 inline 执行
        if self._current_depth >= (getattr(self._agent_factory, '_max_depth', 5)):
            logger.warning(
                "[skill] Fork 降级为 inline: name=%s, depth=%d >= max_depth=%d",
                skill.name, self._current_depth, getattr(self._agent_factory, '_max_depth', 5),
            )
            return await self._execute_inline(skill, prompt)

        from langchain_core.messages import AIMessage, HumanMessage
        from uuid import uuid4

        agent_name = skill.agent if skill.agent else "default"

        logger.info("[skill] Fork 执行: name=%s, agent=%s, depth=%d",
                     skill.name, agent_name, self._current_depth)

        # 通过 AgentFactory 获取或构建 Agent（和 AgentTool 同一套逻辑）
        agent = await self._agent_factory.build(agent_name, self._current_depth)

        # 构建任务指令（skill.prompt 作为 HumanMessage，不是 system_prompt）
        task_instruction = self._build_task_instruction(skill, arguments, formatted_prompt=prompt)

        sub_thread_id = f"skill-{skill.name}-{uuid4().hex[:8]}"

        # ── 资源预加载：在子 Agent 启动前批量注入基础知识文件 ──
        preload_context = await self._preload_resources(skill, arguments, sub_thread_id)
        if preload_context:
            task_instruction += preload_context

        messages = [HumanMessage(content=task_instruction)]

        # 注册子 thread 供主 Agent 实时 polling 子 Agent 链路
        try:
            from src.middleware.tracing import tracing_middleware
            from langgraph.config import get_config
            parent_tid = get_config().get("configurable", {}).get("thread_id", "")
            if parent_tid:
                tracing_middleware.register_sub_thread(parent_tid, sub_thread_id)
        except Exception:
            parent_tid = ""

        try:
            from src.skills.context import set_skill_context, clear_skill_context
            _scope_token = set_skill_context(skill.name, skill.allowed_tools, "fork")
        except Exception:
            _scope_token = None

        try:
            result = await agent.ainvoke(
                {"messages": messages},
                config={"configurable": {
                    "thread_id": sub_thread_id,
                    "skip_memory_extract": True,   # 子 Agent 不提取记忆，由父 Agent 统一处理
                    "skip_memory_retrieve": True,  # 子 Agent 不检索记忆，父 Agent 已注入上下文
                }},
            )
        except RuntimeError as rte:
            if "Event loop is closed" in str(rte) or "closed" in str(rte).lower():
                logger.warning("[skill] Fork RuntimeError (event loop), invalidate cache and retry: %s", rte)
                self._agent_factory.invalidate(agent_name)
                agent = await self._agent_factory.build(agent_name, self._current_depth)
                try:
                    result = await agent.ainvoke(
                        {"messages": messages},
                        config={"configurable": {
                            "thread_id": sub_thread_id,
                            "skip_memory_extract": True,
                        }},
                    )
                except Exception as exc2:
                    raise SkillExecutionError(
                        skill_name=skill.name,
                        detail=str(exc2),
                    ) from exc2
            else:
                raise SkillExecutionError(
                    skill_name=skill.name,
                    detail=str(rte),
                ) from rte
        except Exception as exc:
            # 检查 cause chain 中是否有 Event loop is closed（可能被包装）
            exc_str = str(exc) + str(exc.__cause__ or '')
            if "Event loop is closed" in exc_str or "loop is closed" in exc_str.lower():
                logger.warning("[skill] Fork Exception (event loop wrapped), invalidate cache and retry: %s", exc)
                self._agent_factory.invalidate(agent_name)
                agent = await self._agent_factory.build(agent_name, self._current_depth)
                try:
                    result = await agent.ainvoke(
                        {"messages": messages},
                        config={"configurable": {
                            "thread_id": sub_thread_id,
                            "skip_memory_extract": True,
                        }},
                    )
                except Exception as exc2:
                    raise SkillExecutionError(
                        skill_name=skill.name,
                        detail=str(exc2),
                    ) from exc2
            else:
                raise SkillExecutionError(
                    skill_name=skill.name,
                    detail=str(exc),
                ) from exc
        finally:
            # 清除 fork 模式的 Skill 执行上下文
            if _scope_token is not None:
                try:
                    clear_skill_context(_scope_token)
                except Exception:
                    logger.exception("base.py L706 异常")

        output = self._extract_output(result)
        logger.info("[skill] Fork 完成: name=%s, agent=%s, thread=%s, output_len=%d",
                     skill.name, agent_name, sub_thread_id, len(output))

        # 取消注册子 thread（fork 完成，不再需要实时 polling）
        if parent_tid:
            try:
                tracing_middleware.unregister_sub_thread(parent_tid, sub_thread_id)
            except Exception:
                logger.exception("base.py L717 异常")

        # 收集子 Agent 的 tool_call spans 作为 skill_execution 的 children
        self._last_fork_children = self._collect_sub_agent_spans(sub_thread_id)

        return output

    async def _sync_scripts_to_sandbox(self, skill: SkillDefinition) -> str:
        """同步 Skill 的 scripts/ 目录到沙盒，返回沙盒中的 skill 目录路径

        如果 skill 的 ext_info 中配置了 script_execution，则触发 ScriptSyncer
        将 DB 中的脚本文件增量同步到远程沙盒。

        Returns:
            沙盒中的 skill 目录路径（如 /sandbox/.skills/sales-data-analyzer），
            如果无需同步或同步失败则返回空字符串。
        """
        # 检查 skill 是否有 script_execution 配置
        ext_info = getattr(skill, '_ext_info', None)
        if not ext_info:
            return ""

        import json as _json
        if isinstance(ext_info, str):
            try:
                ext_info = _json.loads(ext_info)
            except (ValueError, TypeError):
                return ""

        script_cfg = ext_info.get("script_execution") if isinstance(ext_info, dict) else None
        if not script_cfg:
            return ""

        # 获取沙盒 backend（从 ToolRegistry 中找到 TerminalTool 的 backend）
        try:
            from src.tools.sandbox.script_syncer import ScriptSyncer, SKILL_BASE_DIR

            sandbox_backend = None
            if self._context and hasattr(self._context, 'tool_registry'):
                tool_reg = self._context.tool_registry
                if tool_reg:
                    terminal_tool = tool_reg.find_by_name("terminal")
                    if terminal_tool and hasattr(terminal_tool, '_backend'):
                        sandbox_backend = terminal_tool._backend

            if sandbox_backend is None:
                # 尝试从环境变量创建
                from src.tools.sandbox.ssh_backend import create_ssh_backend_from_env
                sandbox_backend = create_ssh_backend_from_env()

            if sandbox_backend is None:
                logger.warning("[skill] 无法获取沙盒 backend，跳过脚本同步: %s", skill.name)
                return ""

            # 执行同步
            syncer = ScriptSyncer(backend=sandbox_backend, tenant_id=skill.tenant_id)
            version = getattr(skill, 'version', '1.0.0')
            result = await syncer.sync(skill.name, version=version)

            if result.errors:
                logger.warning("[skill] 脚本同步有错误: %s — %s", skill.name, result.errors)

            skill_dir = f"{SKILL_BASE_DIR}/{skill.name}"
            logger.info(
                "[skill] 脚本同步完成: %s → %s (synced=%d, skipped=%d, %.0fms)",
                skill.name, skill_dir, result.synced, result.skipped, result.duration_ms,
            )
            return skill_dir

        except Exception as e:
            logger.warning("[skill] 脚本同步失败: %s — %s", skill.name, e)
            return ""

    @staticmethod
    def _build_task_instruction(skill: SkillDefinition, arguments: dict[str, str],
                                formatted_prompt: str = "") -> str:
        """构建传递给子 Agent 的任务指令"""
        # 使用已格式化的 prompt（包含 ${SKILL_DIR} 替换），如果没有则 fallback
        prompt_text = formatted_prompt or skill.format_prompt(arguments)
        parts = [f"请执行技能 '{skill.name}': {skill.description}"]
        if arguments:
            args_str = ", ".join(f"{k}={v}" for k, v in arguments.items())
            parts.append(f"参数: {args_str}")
        if prompt_text:
            parts.append(f"\n{prompt_text}")
        return "\n".join(parts)

    async def _preload_resources(
        self, skill: SkillDefinition, arguments: dict[str, str],
        sub_thread_id: str = "",
    ) -> str:
        """预加载 Skill 关联的基础知识文件

        根据 skill 的 ext_info.preload_resources 配置，在子 Agent 启动前
        批量加载知识文件并格式化为注入文本。

        降级策略：
        - 有 preload_resources 配置 → 按配置加载
        - 无配置但 allowed_tools 包含 read_skill_resource → 自动加载索引文件
        - 都不满足 → 跳过

        Args:
            skill: 技能定义
            arguments: 用户传入的参数（用于场景匹配）
            sub_thread_id: 子 Agent 的 thread_id（用于写入 tracing span）

        Returns:
            格式化的预加载知识文本（空字符串表示无需预加载）
        """
        # 前置检查：只有 fork 模式且 allowed_tools 包含 read_skill_resource 才有意义
        if "read_skill_resource" not in skill.allowed_tools:
            return ""

        try:
            from src.skills.resource_preloader import ResourcePreloader, PreloadConfig

            preloader = ResourcePreloader(tenant_id=skill.tenant_id)

            # 从 SkillDefinition 获取 ext_info（可能是 DB 加载时存入的）
            ext_info = getattr(skill, "_ext_info", None)
            if ext_info is None:
                # 尝试从 DB 重新获取 ext_info（ai_skill 主表）
                logger.info("[skill] _ext_info 未随 SkillDefinition 加载，尝试从 ai_skill 表获取: skill=%s",
                            skill.name)
                ext_info = self._load_skill_ext_info(skill.name, skill.tenant_id)

            config = preloader.parse_config(ext_info)

            # 降级：无显式配置时，自动发现并加载索引文件
            if config is None:
                logger.warning("[skill] preload_resources 配置缺失，走自动发现降级: skill=%s, ext_info=%s",
                               skill.name, (ext_info or "")[:100])
                config = await self._auto_discover_preload(preloader, skill.name)
                if config is None:
                    return ""

            # 根据 arguments 匹配场景，确定需要加载的文件
            resource_paths = preloader.match_scene(config, arguments)
            if not resource_paths:
                return ""

            # 批量加载
            result = await preloader.preload(skill.name, resource_paths)
            if not result.files:
                return ""

            # 记录预加载 tracing span（写入子 Agent 的 thread，作为执行链路第一步）
            self._record_preload_span(
                skill_name=skill.name,
                requested=len(resource_paths),
                loaded=len(result.files),
                duration_ms=result.duration_ms,
                requested_paths=resource_paths,
                loaded_paths=[f["path"] for f in result.files],
                thread_id=sub_thread_id,
            )

            # 格式化为注入文本
            return ResourcePreloader.format_preloaded_context(result)

        except Exception as e:
            logger.warning("[skill] 资源预加载失败（降级为运行时加载）: skill=%s, err=%s",
                           skill.name, e)
            return ""

    @staticmethod
    async def _auto_discover_preload(preloader, skill_name: str):
        """自动发现 Skill 的索引文件作为最小预加载配置

        当 ext_info 中没有 preload_resources 配置时，
        尝试查找 knowledge/industries/_index.md 或 knowledge/_index.md 作为基础加载。
        """
        from src.skills.resource_preloader import PreloadConfig

        # 尝试列出该 skill 下的可用文件
        try:
            from src.store.pg_pool import get_conn

            names = preloader._build_name_variants(skill_name)
            with get_conn() as conn:
                cur = conn.cursor()
                name_placeholders = ",".join(["%s"] * len(names))
                cur.execute(f"""
                    SELECT path FROM ai_skill_resource
                    WHERE skill_api_key IN ({name_placeholders})
                      AND node_type = 'file'
                      AND tenant_id = %s
                      AND delete_flg = 0 AND enabled_flg = 1
                      AND path LIKE '%%/_index.md'
                    ORDER BY depth, sort_num
                    LIMIT 3
                """, (*names, preloader._tenant_id))
                index_files = [r[0] for r in cur.fetchall()]

            if not index_files:
                return None

            return PreloadConfig(
                always=index_files[:2],  # 最多自动加载 2 个索引文件
                scene_map={},
                max_preload=2,
            )
        except Exception:
            return None

    @staticmethod
    def _load_skill_ext_info(skill_name: str, tenant_id: int) -> str:
        """从 DB 加载 Skill 的 ext_info 字段

        注意：ext_info 存储在 ai_skill 主记录表（版本无关元信息），
        不在 ai_skill_definition 版本内容表中。
        """
        try:
            from src.store.pg_pool import get_conn
            import re

            # 构建名称变体
            names = [skill_name]
            if "-" in skill_name:
                names.append(skill_name.replace("-", "_"))
            elif "_" in skill_name:
                names.append(skill_name.replace("_", "-"))
            if any(c.isupper() for c in skill_name):
                kebab = re.sub(r'([a-z])([A-Z])', r'\1-\2', skill_name).lower()
                if kebab not in names:
                    names.append(kebab)

            with get_conn() as conn:
                cur = conn.cursor()
                placeholders = ",".join(["%s"] * len(names))
                cur.execute(f"""
                    SELECT ext_info FROM ai_skill
                    WHERE api_key IN ({placeholders})
                      AND tenant_id = %s AND delete_flg = 0 AND enabled_flg = 1
                    LIMIT 1
                """, (*names, tenant_id))
                row = cur.fetchone()
                return row[0] if row else "{}"
        except Exception as e:
            logger.warning("[skill] _load_skill_ext_info 查询失败: skill=%s, err=%s", skill_name, e)
            return "{}"

    @staticmethod
    def _record_preload_span(
        skill_name: str, requested: int, loaded: int,
        duration_ms: float,
        requested_paths: list[str],
        loaded_paths: list[str],
        thread_id: str = "",
    ) -> None:
        """记录资源预加载 tracing span（写入子 Agent 的 thread）

        预加载是子 Agent 执行链路的第一步（context 阶段），
        写入 sub_thread_id 后会被 _collect_sub_agent_spans 收集为 skill_execution 的 children。
        """
        try:
            from src.middleware.tracing import tracing_middleware
            if thread_id:
                tracing_middleware._add_to_thread(
                    thread_id,
                    "resource_preload", f"resource_preload:{skill_name}", duration_ms,
                    metadata={
                        "skill_name": skill_name,
                        "preload_requested": requested,
                        "preload_loaded": loaded,
                    },
                    input_data={
                        "skill_name": skill_name,
                        "requested_paths": requested_paths,
                    },
                    output_data={
                        "loaded_count": loaded,
                        "loaded_paths": loaded_paths,
                        "duration_ms": round(duration_ms, 1),
                    },
                    detail=f"预加载 {loaded}/{requested} 个知识文件 · {round(duration_ms)}ms",
                )
            else:
                tracing_middleware._add(
                    "resource_preload", f"resource_preload:{skill_name}", duration_ms,
                    metadata={
                        "skill_name": skill_name,
                        "preload_requested": requested,
                        "preload_loaded": loaded,
                    },
                    input_data={
                        "skill_name": skill_name,
                        "requested_paths": requested_paths,
                    },
                    output_data={
                        "loaded_count": loaded,
                        "loaded_paths": loaded_paths,
                        "duration_ms": round(duration_ms, 1),
                    },
                    detail=f"预加载 {loaded}/{requested} 个知识文件 · {round(duration_ms)}ms",
                )
        except Exception:
            logger.exception("base.py L946 异常")

    @staticmethod
    def _extract_output(result: dict[str, Any]) -> str:
        """从 Agent 执行结果中提取最后一条 AIMessage 的内容"""
        from langchain_core.messages import AIMessage
        messages = result.get("messages", [])
        for msg in reversed(messages):
            if isinstance(msg, AIMessage):
                content = msg.content
                if isinstance(content, list):
                    return "".join(
                        c.get("text", "") if isinstance(c, dict) else str(c)
                        for c in content
                    )
                return str(content)
        return ""


# ═══════════════════════════════════════════════════════════
# SkillsTool — LLM 调用技能的统一入口
# ═══════════════════════════════════════════════════════════

class SkillsTool(Tool):
    """
    技能调用工具 — 对应 design.md §6.5

    注册到 ToolRegistry，LLM 通过 function calling 调用:
    skills_tool(skill_name="verify_config", arguments={"entity": "opportunity"})
    """

    def __init__(self, executor: SkillExecutor):
        self._executor = executor

    @property
    def name(self) -> str:
        return "skills_tool"

    def input_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "skill_name": {
                    "type": "string",
                    "description": "要调用的技能名称",
                },
                "arguments": {
                    "type": "object",
                    "description": "传递给技能的命名参数（键值对）",
                    "additionalProperties": {"type": "string"},
                },
            },
            "required": ["skill_name"],
        }

    async def call(self, input_data: dict, context: Any, on_progress=None) -> ToolResult:
        skill_name = input_data.get("skill_name", "")
        arguments = input_data.get("arguments", {})

        try:
            result = await self._executor.execute(skill_name, arguments)
            return ToolResult(content=result)
        except SkillExecutionError as e:
            return ToolResult(content=f"技能执行失败: {e}", is_error=True)
        except Exception as e:
            logger.error(f"SkillsTool error: {e}")
            return ToolResult(content=f"技能执行异常: {e}", is_error=True)

    def prompt(self) -> str:
        return (
            "调用已注册的技能。传入 skill_name（技能名称）和 arguments（参数字典）。"
            "技能会返回执行指引或分析结果。"
        )
