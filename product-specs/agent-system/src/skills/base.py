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
    risk_level: str = "read_only"                # read_only | mutating | destructive
    requires_confirmation: bool = False
    max_tool_calls: int = 20
    timeout_ms: int = 60000
    owner: str = ""
    output_mode: str = "text"
    component_apikey: str = ""
    post_output_behavior: str = "silent"         # silent | summarize | continue | passthrough
    tenant_id: int = 0                           # 0 = 平台级

    def format_prompt(self, arguments: dict[str, str]) -> str:
        """替换 prompt 中的 {arg} 占位符"""
        result = self.prompt
        for key, value in arguments.items():
            result = result.replace(f"{{{key}}}", str(value))
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
        return cls(
            name=row.api_key,
            description=row.description or row.name,
            prompt=row.prompt or "",
            when_to_use=row.when_to_use or "",
            arguments=[str(a) for a in arguments],
            allowed_tools=[str(t) for t in allowed_tools],
            model=row.model or "",
            context=row.context or "inline",
            agent=row.agent or "",
            version=row.version or "1.0.0",
            risk_level=row.risk_level or "read_only",
            requires_confirmation=bool(row.requires_confirmation),
            max_tool_calls=row.max_tool_calls or 20,
            timeout_ms=row.timeout_ms or 60000,
            owner=row.owner or "",
            output_mode=getattr(row, "output_mode", "text") or "text",
            component_apikey=getattr(row, "component_apikey", "") or "",
            post_output_behavior=getattr(row, "post_output_behavior", "silent") or "silent",
            tenant_id=row.tenant_id or 0,
        )


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
                logger.warning("加载 Skill 失败 api_key=%s: %s", row.api_key, exc)
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
            risk_level=getattr(skill, "risk_level", "read_only"),
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
            risk_level=row.risk_level,
            requires_confirmation=row.requires_confirmation,
            max_tool_calls=row.max_tool_calls,
            timeout_ms=row.timeout_ms,
            changelog=changelog,
            published_by=published_by,
        )
        SkillVersionDAO.insert(version_row)

    def match_by_intent(self, intent: str, tracker: Any = None) -> SkillDefinition | None:
        """按意图匹配技能 — 关键词粗筛 + 度量加权精排

        Args:
            intent: 用户意图文本
            tracker: SkillTracker 实例（可选），用于度量加权
        """
        # 关键词粗筛
        candidates = []
        for skill in self._skills.values():
            if skill.when_to_use:
                keywords = skill.when_to_use.split("|")
                if any(kw.strip() in intent for kw in keywords):
                    candidates.append(skill)

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

        formatted_prompt = skill.format_prompt(arguments)
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
                if s_type in ("llm_input", "intent_analysis", "request", "clarification", "memory_extract", "tool_result_compact"):
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
        """
        if self._agent_factory is None:
            raise SkillExecutionError(
                skill_name=skill.name if hasattr(skill, 'name') else "",
                detail="AgentFactory 未配置，无法执行 fork 模式技能",
            )

        from langchain_core.messages import AIMessage, HumanMessage
        from uuid import uuid4

        agent_name = skill.agent if skill.agent else "default"

        logger.info("[skill] Fork 执行: name=%s, agent=%s, depth=%d",
                     skill.name, agent_name, self._current_depth)

        # 通过 AgentFactory 获取或构建 Agent（和 AgentTool 同一套逻辑）
        agent = await self._agent_factory.build(agent_name, self._current_depth)

        # 构建任务指令（skill.prompt 作为 HumanMessage，不是 system_prompt）
        task_instruction = self._build_task_instruction(skill, arguments)
        messages = [HumanMessage(content=task_instruction)]

        sub_thread_id = f"skill-{skill.name}-{uuid4().hex[:8]}"

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
            result = await agent.ainvoke(
                {"messages": messages},
                config={"configurable": {
                    "thread_id": sub_thread_id,
                    "skip_memory_extract": True,  # 子 Agent 不提取记忆，由父 Agent 统一处理
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

        output = self._extract_output(result)
        logger.info("[skill] Fork 完成: name=%s, agent=%s, thread=%s, output_len=%d",
                     skill.name, agent_name, sub_thread_id, len(output))

        # 取消注册子 thread（fork 完成，不再需要实时 polling）
        if parent_tid:
            try:
                tracing_middleware.unregister_sub_thread(parent_tid, sub_thread_id)
            except Exception:
                pass

        # 收集子 Agent 的 tool_call spans 作为 skill_execution 的 children
        self._last_fork_children = self._collect_sub_agent_spans(sub_thread_id)

        return output

    @staticmethod
    def _build_task_instruction(skill: SkillDefinition, arguments: dict[str, str]) -> str:
        """构建传递给子 Agent 的任务指令"""
        formatted_prompt = skill.format_prompt(arguments)
        parts = [f"请执行技能 '{skill.name}': {skill.description}"]
        if arguments:
            args_str = ", ".join(f"{k}={v}" for k, v in arguments.items())
            parts.append(f"参数: {args_str}")
        if formatted_prompt:
            parts.append(f"\n{formatted_prompt}")
        return "\n".join(parts)

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
