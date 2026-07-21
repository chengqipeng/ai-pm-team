"""ToolState — Tool/Middleware 执行时的状态传递

拆分为两部分，对齐 LangGraph 架构：
1. state（可读写）— 图 state 中的业务字段，Provider 可通过 set_state 回写
2. configurable（只读）— 请求级上下文（tenant_id/user_id/thread_id），Provider 只能读取

使用方式：

    # Provider handler 中
    from neo_ai_registry.state import get_state, set_state

    async def query_customer(input_data: dict, state: ToolState) -> dict:
        # 读取 configurable（只读 — tenant_id/user_id 等请求上下文）
        tenant_id = state.configurable.get("tenant_id")
        user_id = state.configurable.get("user_id")

        # 读取 state（可读写 — 图 state 业务字段）
        thread_data = state.get("thread_data")

        # 通过 set_state 回写到 state（不影响 configurable）
        set_state("last_query_entity", "account")
        set_state("query_count", get_state("query_count", 0) + 1)

        return {"status": "success"}

    # Agent Runtime 侧（SDK 自动处理）
    tool_state = ToolState.from_agent_state(graph_state, configurable=configurable)
    result = client.execute_tool("query_customer", input_data, state=tool_state)
    tool_state.write_back(graph_state)  # 只有 state_patch 回写，configurable 不变
"""
from __future__ import annotations

from contextvars import ContextVar
from typing import Any


# ═══════════════════════════════════════════════════════════
# 线程隔离的 state patch 存储（基于 contextvars）
# ═══════════════════════════════════════════════════════════

_state_patch: ContextVar[dict[str, Any]] = ContextVar("_state_patch", default=None)
_state_data: ContextVar[dict[str, Any]] = ContextVar("_state_data", default=None)


def _init_state_context(data: dict[str, Any]) -> None:
    """初始化当前请求的 state 上下文（SDK 路由层调用）"""
    _state_data.set(dict(data))
    _state_patch.set({})


def _collect_state_patch() -> dict[str, Any]:
    """收集当前请求中 set_state 写入的数据（SDK 路由层返回时调用）"""
    patch = _state_patch.get()
    return dict(patch) if patch else {}


# ═══════════════════════════════════════════════════════════
# Provider 侧公开 API（handler 中使用）
# ═══════════════════════════════════════════════════════════

def set_state(key: str, value: Any) -> None:
    """写入状态到 state（Provider handler 中调用）

    写入的数据会回传给 Agent Runtime，merge 到图 state。
    注意：不能修改 configurable 中的数据。

    Args:
        key: 状态字段名。
        value: 状态值。
    """
    patch = _state_patch.get()
    if patch is None:
        patch = {}
        _state_patch.set(patch)
    patch[key] = value


def get_state(key: str, default: Any = None) -> Any:
    """读取状态（Provider handler 中调用）

    优先读取 set_state 写入的值，其次读取 Agent 传入的原始 state 值。

    Args:
        key: 状态字段名。
        default: 不存在时的默认值。
    """
    patch = _state_patch.get()
    if patch and key in patch:
        return patch[key]
    data = _state_data.get()
    if data and key in data:
        return data[key]
    return default


# ═══════════════════════════════════════════════════════════
# ToolState — 可读写 state + 只读 configurable
# ═══════════════════════════════════════════════════════════

class ToolState:
    """Tool 执行状态 — state（可读写）+ configurable（只读）

    Provider handler 通过此对象：
    - state.get(key) → 读取图 state 字段
    - state.configurable.get(key) → 读取请求上下文（只读）
    - set_state(key, value) → 回写数据到图 state（线程隔离）

    Attributes:
        _data: 图 state 业务字段（可读写）。
        _configurable: 请求上下文（只读，Provider 不可修改）。
    """

    def __init__(self, data: dict[str, Any] | None = None, configurable: dict[str, Any] | None = None):
        """初始化 ToolState

        Args:
            data: 图 state 业务字段（可读写部分）。
            configurable: 请求上下文（只读部分：tenant_id/user_id/thread_id 等）。
        """
        self._data: dict[str, Any] = dict(data or {})
        self._original: dict[str, Any] = dict(data or {})
        self._configurable: dict[str, Any] = dict(configurable or {})

    @property
    def configurable(self) -> dict[str, Any]:
        """请求上下文（只读）— tenant_id/user_id/thread_id/language_code 等"""
        return self._configurable

    def get(self, key: str, default: Any = None) -> Any:
        """读取 state 字段"""
        return self._data.get(key, default)

    def to_dict(self) -> dict[str, Any]:
        """序列化 state 部分"""
        return dict(self._data)

    def to_transport(self) -> dict[str, Any]:
        """序列化为传输格式（state + configurable 分开传递）"""
        return {
            "state": dict(self._data),
            "configurable": dict(self._configurable),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None, configurable: dict[str, Any] | None = None) -> "ToolState":
        """从传输格式反序列化"""
        return cls(data=data, configurable=configurable)

    @classmethod
    def from_agent_state(
        cls,
        agent_state: dict[str, Any],
        configurable: dict[str, Any] | None = None,
    ) -> "ToolState":
        """从 LangGraph 图 state + configurable 构建 ToolState（调用前）

        Args:
            agent_state: LangGraph 图 state dict（messages/artifacts/title/thread_data/sandbox 等）。
            configurable: 请求上下文 dict（tenant_id/user_id/thread_id/language_code 等）。

        Usage:
            tool_state = ToolState.from_agent_state(graph_state, configurable=configurable)
            result = client.execute_tool("query_customer", input_data, state=tool_state)
            tool_state.write_back(graph_state)
        """
        # state: 排除不可序列化字段
        excluded = {"interrupt_event", "_limits", "_hitl_approved_once"}
        state_data = {k: v for k, v in agent_state.items() if k not in excluded} if agent_state else {}

        return cls(data=state_data, configurable=configurable)

    def write_back(self, agent_state: dict[str, Any]) -> dict[str, Any]:
        """将 Provider set_state 的 patch 写回图 state（调用后）

        只写回 state 的变化，不修改 configurable。

        Args:
            agent_state: LangGraph 图 state dict（可变引用，直接修改）。

        Returns:
            实际写入的 patch dict。
        """
        changed = {}
        for key, value in self._data.items():
            if key not in self._original or self._original[key] != value:
                changed[key] = value
        if changed:
            agent_state.update(changed)
        return changed

    def merge_patch(self, patch: dict[str, Any]) -> None:
        """合并 Provider 回传的 state_patch（Agent Runtime 侧）"""
        self._data.update(patch)

    def __repr__(self) -> str:
        return f"ToolState(state={list(self._data.keys())}, configurable={list(self._configurable.keys())})"
