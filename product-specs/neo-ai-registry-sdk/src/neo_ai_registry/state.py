"""ToolState — Tool/Middleware 执行时的 state 传递（可读写）

分为两个独立参数（分开传递）：
1. state: ToolState — 图 state 业务字段（可读写，Provider 通过 set_state 回写）
2. configurable: dict — 请求上下文（只读，Provider 只能读取）

MCP 场景不需要 state 和 configurable（MCP handler 只接收 input_data）。

Provider handler 签名：
    # Tool
    async def handler(input_data: dict, state: ToolState, configurable: dict) -> dict

    # Middleware
    async def handler(hook: str, payload: dict, state: ToolState, configurable: dict) -> dict

    # MCP Tool（无 state/configurable）
    async def handler(input_data: dict) -> dict
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
    """
    patch = _state_patch.get()
    if patch is None:
        patch = {}
        _state_patch.set(patch)
    patch[key] = value


def get_state(key: str, default: Any = None) -> Any:
    """读取状态（Provider handler 中调用）

    优先读取 set_state 写入的值，其次读取 Agent 传入的原始 state 值。
    """
    patch = _state_patch.get()
    if patch and key in patch:
        return patch[key]
    data = _state_data.get()
    if data and key in data:
        return data[key]
    return default


# ═══════════════════════════════════════════════════════════
# ToolState — 图 state 可读写视图
# ═══════════════════════════════════════════════════════════

class ToolState:
    """Tool 执行时的图 state（可读写）

    Provider handler 通过此对象读取图 state 中的业务字段。
    写入使用 set_state() 函数（线程隔离）。
    configurable 作为独立参数传递，不在 ToolState 中。
    """

    def __init__(self, data: dict[str, Any] | None = None):
        self._data: dict[str, Any] = dict(data or {})
        self._original: dict[str, Any] = dict(data or {})

    def get(self, key: str, default: Any = None) -> Any:
        """读取 state 字段"""
        return self._data.get(key, default)

    def to_dict(self) -> dict[str, Any]:
        """序列化为 dict"""
        return dict(self._data)

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "ToolState":
        """从 dict 反序列化"""
        return cls(data=data)

    @classmethod
    def from_agent_state(cls, agent_state: dict[str, Any]) -> "ToolState":
        """从 LangGraph 图 state 构建（排除不可序列化字段）

        Args:
            agent_state: LangGraph 图 state dict。
        """
        if not agent_state:
            return cls()
        excluded = {"messages", "interrupt_event", "_limits", "_hitl_approved_once"}
        filtered = {k: v for k, v in agent_state.items() if k not in excluded}
        return cls(data=filtered)

    def write_back(self, agent_state: dict[str, Any]) -> dict[str, Any]:
        """将 state_patch 写回图 state（调用后）

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
        """合并 Provider 回传的 state_patch"""
        self._data.update(patch)

    def __repr__(self) -> str:
        return f"ToolState({list(self._data.keys())})"
