"""ToolState — Tool/Middleware 执行时的状态传递

分为两部分：
1. ToolState（只读）：Agent 传入的上下文数据，Provider 只能读不能改
2. set_state / get_state（线程隔离）：Provider 回写数据的接口，基于 contextvars 隔离

使用方式：

    # Provider handler 中
    from neo_ai_registry.state import get_state, set_state

    async def query_customer(input_data: dict, state: ToolState) -> dict:
        # 读取 Agent 传入的 state（只读）
        tenant_id = state.get("tenant_id")
        user_input = state.get("user_input")

        # 通过 set_state 回写（线程隔离，自动返回给 Runtime）
        set_state("last_query_entity", "account")
        set_state("query_count", get_state("query_count", 0) + 1)

        return {"status": "success"}

    # Agent Runtime 侧（SDK 自动处理）
    result = client.execute_tool("query_customer", input_data, state=state)
    # result["state_patch"] = {"last_query_entity": "account", "query_count": 1}
    # SDK 自动 merge 到 Agent state
"""
from __future__ import annotations

from contextvars import ContextVar
from typing import Any


# ═══════════════════════════════════════════════════════════
# 线程隔离的 state patch 存储（基于 contextvars）
# ═══════════════════════════════════════════════════════════

# 每个请求/协程独立的 patch 存储，避免跨线程污染
_state_patch: ContextVar[dict[str, Any]] = ContextVar("_state_patch", default=None)
_state_data: ContextVar[dict[str, Any]] = ContextVar("_state_data", default=None)


def _init_state_context(data: dict[str, Any]) -> None:
    """初始化当前请求的 state 上下文（由 SDK 路由层调用，每个请求调用一次）

    Args:
        data: Agent 传入的 state 字典。
    """
    _state_data.set(dict(data))
    _state_patch.set({})


def _collect_state_patch() -> dict[str, Any]:
    """收集当前请求中 set_state 写入的所有数据（由 SDK 路由层在返回时调用）

    Returns:
        Provider 通过 set_state 写入的增量字典。
    """
    patch = _state_patch.get()
    return dict(patch) if patch else {}


# ═══════════════════════════════════════════════════════════
# Provider 侧公开 API（handler 中使用）
# ═══════════════════════════════════════════════════════════

def set_state(key: str, value: Any) -> None:
    """写入状态（Provider handler 中调用）

    写入的数据会在请求返回时自动回传给 Agent Runtime，
    Runtime 侧通过 SDK 自动 merge 到 Agent state。

    线程安全：基于 contextvars 隔离，不同请求互不干扰。

    Args:
        key: 状态字段名（自定义业务字段，如 "last_query_entity"）。
        value: 状态值。
    """
    patch = _state_patch.get()
    if patch is None:
        patch = {}
        _state_patch.set(patch)
    patch[key] = value


def get_state(key: str, default: Any = None) -> Any:
    """读取状态（Provider handler 中调用）

    优先读取当前请求中 set_state 写入的值，其次读取 Agent 传入的原始值。

    Args:
        key: 状态字段名。
        default: 不存在时的默认值。
    """
    # 优先读 patch（当前请求已写入的）
    patch = _state_patch.get()
    if patch and key in patch:
        return patch[key]
    # 其次读 Agent 传入的原始数据
    data = _state_data.get()
    if data and key in data:
        return data[key]
    return default


# ═══════════════════════════════════════════════════════════
# ToolState（只读视图 — Agent 传入的状态数据）
# ═══════════════════════════════════════════════════════════

class ToolState:
    """Tool 执行状态 — 只读视图

    Provider handler 通过此对象读取 Agent 传入的状态数据。
    写入请使用 set_state() 函数（线程隔离）。

    Attributes:
        _data: Agent 传入的原始状态字典（只读）。
    """

    def __init__(self, **kwargs: Any):
        """初始化 ToolState

        Args:
            **kwargs: Agent state 字段（tenant_id/user_id/thread_id/... + 任意业务字段）。
        """
        self._data: dict[str, Any] = dict(kwargs)
        self._original: dict[str, Any] = dict(kwargs)  # 保留初始快照，用于 write_back 对比

    def get(self, key: str, default: Any = None) -> Any:
        """读取 Agent 传入的状态值（只读）

        Args:
            key: 状态字段名。
            default: 不存在时的默认值。
        """
        return self._data.get(key, default)

    def to_dict(self) -> dict[str, Any]:
        """序列化为传输格式"""
        return dict(self._data)

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "ToolState":
        """从传输格式反序列化"""
        if not data:
            return cls()
        return cls(**data)

    @classmethod
    def from_agent_state(cls, agent_state: dict[str, Any]) -> "ToolState":
        """从 LangGraph AgentState（dict）转换为 ToolState（调用前）

        排除不可序列化和体积过大的字段（messages/interrupt_event 等）。

        Args:
            agent_state: LangGraph AgentState dict。

        Usage:
            tool_state = ToolState.from_agent_state(state)
            result = client.execute_tool("query_customer", input_data, state=tool_state)
            tool_state.write_back(state)
        """
        if not agent_state:
            return cls()
        excluded = {"messages", "interrupt_event", "_limits", "_hitl_approved_once"}
        filtered = {k: v for k, v in agent_state.items() if k not in excluded}
        return cls(**filtered)

    def write_back(self, agent_state: dict[str, Any]) -> dict[str, Any]:
        """将 Provider set_state 的 patch 写回 LangGraph AgentState（调用后）

        FeignClient 调用完成后自动将 state_patch merge 到了 self._data。
        本方法对比原始数据和当前数据的差异，将变化的字段写入 agent_state。

        Args:
            agent_state: LangGraph AgentState dict（可变引用，直接修改）。

        Returns:
            实际写入的 patch dict（供日志/调试用）。

        Usage:
            tool_state = ToolState.from_agent_state(state)
            result = client.execute_tool("query_customer", input_data, state=tool_state)
            patch = tool_state.write_back(state)  # Provider 写入的数据回到 AgentState
        """
        # FeignClient 已将 response["state_patch"] merge 到 self._data
        # 与 _original 对比找出变化的 key
        changed = {}
        for key, value in self._data.items():
            if key not in self._original or self._original[key] != value:
                changed[key] = value
        if changed:
            agent_state.update(changed)
        return changed

    def merge_patch(self, patch: dict[str, Any]) -> None:
        """合并 Provider 回传的 patch（Agent Runtime 侧调用）

        Args:
            patch: Provider 回传的增量字典。
        """
        self._data.update(patch)

    def __repr__(self) -> str:
        return f"ToolState({list(self._data.keys())})"
