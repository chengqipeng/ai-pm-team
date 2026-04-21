"""
AgentFactory — 8-Phase 初始化，对应产品设计 §3.7 + Agent-Core 〇.一节
创建和配置 Agent 实例的唯一入口
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from .state import GraphState, AgentLimits, AgentCallbacks, TaskPlan
from .engine import GraphEngine, CheckpointStore
from .router import Router
from ..middleware.base import PluginContext
from ..middleware.tenant import TenantMiddleware
from ..middleware.audit import AuditMiddleware
from ..middleware.context import ContextMiddleware
from ..middleware.memory import MemoryMiddleware
from ..middleware.skill import SkillMiddleware
from ..middleware.hitl import HITLMiddleware, HITLRule
from ..nodes.planning import PlanningNode
from ..nodes.execution import ExecutionNode
from ..nodes.reflection import ReflectionNode

logger = logging.getLogger(__name__)

DEFAULT_SYSTEM_PROMPT = """你是一个智能业务助手，运行在 aPaaS 元数据驱动平台上。
你可以查询和操作业务数据、分析数据、搜索网络信息、查询企业工商信息等。
请用简洁专业的语言回答用户问题，必要时使用工具获取信息。
"""


@dataclass
class AgentConfig:
    """Agent 配置 — 创建 Agent 所需的全部参数"""
    tenant_id: str = ""
    user_id: str = ""

    # LLM
    llm_client: Any = None                    # LLMClient 实例
    llm_model: str = "deepseek-chat"

    # 工具
    tool_registry: Any = None                 # ToolRegistry 实例
    enabled_tools: list[str] | None = None
    disabled_tools: list[str] | None = None

    # 技能
    skill_registry: Any = None                # SkillRegistry 实例

    # Plugin
    memory_plugin: Any = None
    search_plugin: Any = None
    company_plugin: Any = None
    financial_plugin: Any = None
    notification_plugin: Any = None

    # 中间件
    enable_hitl: bool = True
    enable_audit: bool = True
    hitl_rules: list[HITLRule] = field(default_factory=list)

    # 限制
    max_total_llm_calls: int = 200
    max_step_llm_calls: int = 20

    # 回调
    callbacks: AgentCallbacks | None = None

    # System prompt
    system_prompt: str = ""
    system_prompt_append: str = ""

    # 检查点
    checkpoint_dir: str = ".checkpoints"


class AgentFactory:

    @staticmethod
    def create(config: AgentConfig) -> tuple[GraphEngine, str]:
        """
        创建 Agent 实例。返回 (engine, system_prompt)。
        同步方法 — 初始化不需要 async。
        """
        # Phase 1: 校验
        if not config.llm_client:
            raise ValueError("llm_client is required")

        # Phase 2: 构建 limits
        limits = AgentLimits(
            MAX_TOTAL_LLM_CALLS=config.max_total_llm_calls,
            MAX_STEP_LLM_CALLS=config.max_step_llm_calls,
        )

        # Phase 3: 构建中间件栈
        middlewares = []
        if config.tenant_id:
            middlewares.append(TenantMiddleware(config.tenant_id))
        if config.enable_audit:
            middlewares.append(AuditMiddleware())
        middlewares.append(ContextMiddleware())
        if config.memory_plugin:
            middlewares.append(MemoryMiddleware(config.memory_plugin))
        if config.skill_registry:
            middlewares.append(SkillMiddleware(config.skill_registry))
        if config.enable_hitl:
            middlewares.append(HITLMiddleware(config.hitl_rules))

        # Phase 4: 构建 PluginContext
        context = PluginContext(
            llm=config.llm_client,
            tool_registry=config.tool_registry,
            limits=limits,
            tenant_id=config.tenant_id,
            user_id=config.user_id,
            memory=config.memory_plugin,
            search=config.search_plugin,
            company=config.company_plugin,
            financial=config.financial_plugin,
            notification=config.notification_plugin,
            middlewares=middlewares,
            callbacks=config.callbacks,
        )

        # Phase 5: 构建 Nodes
        nodes = {
            "planning": PlanningNode(),
            "execution": ExecutionNode(),
            "reflection": ReflectionNode(),
        }

        # Phase 6: 构建 CheckpointStore
        checkpoint = CheckpointStore(config.checkpoint_dir)

        # Phase 7: 构建 GraphEngine
        engine = GraphEngine(
            nodes=nodes,
            middleware_stack=middlewares,
            context=context,
            limits=limits,
            checkpoint_store=checkpoint,
        )

        # Phase 8: 组装 system prompt
        system_prompt = config.system_prompt or DEFAULT_SYSTEM_PROMPT
        if config.system_prompt_append:
            system_prompt += "\n\n" + config.system_prompt_append

        # 注入工具提示
        if config.tool_registry:
            tool_hints = []
            for t in config.tool_registry.all_tools:
                p = t.prompt() if hasattr(t, "prompt") else ""
                if p:
                    tool_hints.append(f"- {t.name}: {p[:100]}")
            if tool_hints:
                system_prompt += "\n\n## 可用工具\n" + "\n".join(tool_hints)

        return engine, system_prompt
