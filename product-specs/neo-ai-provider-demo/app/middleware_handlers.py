"""Middleware 处理器 — 业务域自定义中间件

统一 handler 签名：
    async def handler(hook: str, payload: dict, state: ToolState) -> dict

使用 MiddlewareHook 枚举判断钩子类型（避免硬编码字符串）。
"""
from __future__ import annotations

from typing import Any, TYPE_CHECKING

from neo_ai_registry.models import MiddlewareHook
from neo_ai_registry.state import set_state, get_state

if TYPE_CHECKING:
    from neo_ai_registry.state import ToolState


async def crm_query_state_handler(hook: str, payload: dict[str, Any], state: "ToolState") -> dict[str, Any]:
    """CRM 查询状态管理"""
    if hook == MiddlewareHook.BEFORE_AGENT:
        set_state("crm_query_initialized", True)
        return {
            "action": "modify",
            "patch": {
                "crm_query_state": {
                    "entities_identified": [],
                    "xoql_generated": False,
                    "retry_count": 0,
                }
            },
        }
    elif hook == MiddlewareHook.AFTER_MODEL:
        tool_calls = payload.get("model_output", {}).get("tool_calls", [])
        if any(tc.get("name") == "extract_entity" for tc in tool_calls):
            return {
                "action": "modify",
                "patch": {"crm_query_state": {"entities_identified": ["account"]}},
            }
    return {"action": "continue"}


async def sales_context_inject_handler(hook: str, payload: dict[str, Any], state: "ToolState") -> dict[str, Any]:
    """销售上下文注入"""
    if hook == MiddlewareHook.BEFORE_MODEL:
        set_state("context_injected", True)
        return {
            "action": "modify",
            "patch": {
                "inject_system_message": "[销售上下文] 当前用户负责 12 个活跃客户，本月新增商机 3 个，总管道金额 ¥850 万。",
            },
        }
    return {"action": "continue"}
