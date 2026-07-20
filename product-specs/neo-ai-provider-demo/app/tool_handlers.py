"""Tool 执行处理器 — 业务域具体实现

每个 handler 签名：async def handler(input_data: dict, context: dict) -> dict
"""
from __future__ import annotations

from typing import Any


async def query_customer(input_data: dict[str, Any], state: Any) -> dict[str, Any]:
    """查询客户 — 模拟 CRM API 调用 + state 回写"""
    from neo_ai_registry.state import ToolState
    customer_name = input_data.get("customer_name", "")
    # 通过 state 回写跨服务参数
    if isinstance(state, ToolState):
        state.set("last_query_entity", "account")
        state.set("last_query_keyword", customer_name)
        prev_count = state.get("query_count", 0)
        state.set("query_count", prev_count + 1)
    return {
        "status": "success",
        "records": [
            {
                "id": "acc_001",
                "name": f"{customer_name}科技有限公司",
                "industry": "互联网",
                "owner": "张三",
                "revenue": 5000000,
            }
        ],
        "total": 1,
    }


async def update_opportunity(input_data: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """更新商机 — 模拟 CRM API 调用"""
    opp_id = input_data.get("opportunity_id", "")
    stage = input_data.get("stage", "")
    return {
        "status": "success",
        "message": f"商机 {opp_id} 已更新为 {stage}",
    }


async def analyze_pipeline(input_data: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """分析销售管道 — 模拟聚合计算"""
    group_by = input_data.get("group_by", "stage")
    return {
        "status": "success",
        "group_by": group_by,
        "data": [
            {"label": "线索确认", "count": 45, "amount": 12000000},
            {"label": "需求分析", "count": 32, "amount": 8500000},
            {"label": "方案报价", "count": 18, "amount": 6200000},
            {"label": "赢单", "count": 5, "amount": 2100000},
        ],
    }
