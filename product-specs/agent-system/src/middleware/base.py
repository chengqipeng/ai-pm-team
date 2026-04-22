"""
Middleware Protocol + PluginContext — 对应产品设计 §3.4
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from ..state import GraphState, AgentLimits, AgentCallbacks


class LLMInterface(Protocol):
    """LLM 调用接口 — 由 llm-plugin 实现"""
    async def call(
        self, system_prompt: str, messages: list[dict],
        tools: list[dict] | None = None, model: str = "", max_tokens: int = 0,
    ) -> dict: ...


class MemoryInterface(Protocol):
    """记忆接口 — 由 memory-plugin 实现"""
    async def recall(self, query: str, categories: list[str] | None = None, max_results: int = 5) -> list: ...
    async def commit(self, entry: dict) -> None: ...


@dataclass
class PluginContext:
    """贯穿整个执行链的上下文 — Node/Middleware/Tool 通过此对象访问所有能力"""
    llm: LLMInterface
    tool_registry: Any                          # ToolRegistry
    limits: AgentLimits = field(default_factory=AgentLimits)
    tenant_id: str = ""
    user_id: str = ""

    # 可选 Plugin（None 表示未启用）
    memory: MemoryInterface | None = None
    search: Any | None = None
    company: Any | None = None
    financial: Any | None = None
    notification: Any | None = None

    # 中间件列表（ExecutionNode 内部工具调用时使用）
    middlewares: list[Any] = field(default_factory=list)

    # 回调
    callbacks: AgentCallbacks | None = None

    # 权限
    permission_context: Any | None = None


@runtime_checkable
class Middleware(Protocol):
    """
    中间件接口 — 对应 design.md §5.1 的 6 个生命周期钩子

    执行时序:
    before_step → [before_model → LLM → after_model → wrap_tool_call]* → after_step
    """
    name: str

    # Node 级别（每个 GraphEngine 循环一次）
    async def before_step(self, state: GraphState, context: PluginContext) -> GraphState:
        return state

    async def after_step(self, state: GraphState, context: PluginContext) -> GraphState:
        return state

    # LLM 调用级别（ExecutionNode mini loop 中每次 LLM 调用）
    async def before_model(self, state: GraphState, context: PluginContext) -> GraphState:
        """每次 LLM 调用前 — 可修改 messages、注入上下文"""
        return state

    async def after_model(self, state: GraphState, response: dict, context: PluginContext) -> dict:
        """每次 LLM 调用后 — 可检查/修改 LLM 响应"""
        return response

    # 工具调用级别
    async def before_tool_call(
        self, tool_name: str, input_data: dict, state: GraphState, context: PluginContext
    ) -> dict | None:
        """返回 None 表示拒绝执行"""
        return input_data

    async def wrap_tool_call(
        self, tool_name: str, input_data: dict, state: GraphState, context: PluginContext
    ) -> Any | None:
        """
        包装工具调用 — 对应 design.md §5.1 wrap_tool_call

        返回 None: 继续执行原始工具
        返回 ToolResultBlock: 替代原始工具执行（拦截）
        可用于: 白名单检查、日志记录、参数修改
        """
        return None

    async def after_tool_call(
        self, tool_name: str, result: Any, state: GraphState, context: PluginContext
    ) -> Any:
        return result
