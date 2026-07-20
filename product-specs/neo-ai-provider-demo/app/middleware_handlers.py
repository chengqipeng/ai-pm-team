"""Middleware 执行处理器 — 业务域自定义中间件逻辑

每个 handler 签名：
    async def handler(hook: str, payload: dict, context: dict) -> dict

返回值约定：
    - {"action": "continue"} — 不修改，继续执行
    - {"action": "modify", "patch": {...}} — 修改 state
    - {"action": "abort", "message": "..."} — 中止流程
"""
from __future__ import annotations

from typing import Any


async def crm_query_state_handler(
    hook: str,
    payload: dict[str, Any],
    context: dict[str, Any],
) -> dict[str, Any]:
    """CRM 查询状态管理 — 跟踪实体识别和 XOQL 生成过程

    hook=before_agent: 初始化查询状态
    hook=after_model: 根据模型输出更新查询进度
    """
    if hook == "before_agent":
        # 初始化查询状态
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
    elif hook == "after_model":
        # 模拟：检查模型输出中是否包含实体识别结果
        model_output = payload.get("model_output", {})
        tool_calls = model_output.get("tool_calls", [])

        if any(tc.get("name") == "extract_entity" for tc in tool_calls):
            return {
                "action": "modify",
                "patch": {
                    "crm_query_state": {
                        "entities_identified": ["account"],
                        "xoql_generated": False,
                    }
                },
            }

    return {"action": "continue"}


async def sales_context_inject_handler(
    hook: str,
    payload: dict[str, Any],
    context: dict[str, Any],
) -> dict[str, Any]:
    """销售上下文注入 — 在 LLM 调用前注入用户的销售上下文

    hook=before_model: 注入当前用户负责的客户/商机摘要到 messages
    """
    if hook == "before_model":
        tenant_id = context.get("tenant_id", 0)
        user_id = context.get("user_id", 0)

        # 模拟：注入销售上下文（实际调用 CRM API 获取）
        sales_context = (
            f"[销售上下文] 当前用户负责 12 个活跃客户，"
            f"本月新增商机 3 个，总管道金额 ¥850 万。"
        )

        return {
            "action": "modify",
            "patch": {
                "inject_system_message": sales_context,
            },
        }

    return {"action": "continue"}
