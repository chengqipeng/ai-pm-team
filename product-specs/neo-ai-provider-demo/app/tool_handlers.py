"""Tool 执行处理器 — 业务域具体实现

统一 handler 签名：
    async def handler(input_data: dict, state: ToolState) -> dict

state 操作：
    - state.get("key")     → 读取 AgentState 传入的数据
    - set_state("key", v)  → 回写数据到 Agent 运行时（线程隔离，自动传递）
    - get_state("key")     → 读取当前请求中已 set 的数据
"""
from __future__ import annotations

from typing import Any, TYPE_CHECKING

from neo_ai_registry.state import set_state, get_state
from app.data_store import data_store

if TYPE_CHECKING:
    from neo_ai_registry.state import ToolState


async def query_customer(input_data: dict[str, Any], state: "ToolState") -> dict[str, Any]:
    """查询客户"""
    customer_name = input_data.get("customer_name", "")

    # 从 mock_data.yaml 查询
    conditions = {"name": customer_name} if customer_name else {}
    records = data_store.query("crm", "accounts", conditions, limit=10)

    # 回写 state（自动传递回 Agent Runtime）
    set_state("last_query_entity", "account")
    set_state("last_query_keyword", customer_name)
    set_state("query_count", get_state("query_count", 0) + 1)

    return {
        "status": "success",
        "records": records,
        "total": len(records),
    }


async def update_opportunity(input_data: dict[str, Any], state: "ToolState") -> dict[str, Any]:
    """更新商机"""
    opp_id = input_data.get("opportunity_id", "")
    stage = input_data.get("stage", "")

    set_state("last_modified_entity", "opportunity")
    set_state("last_modified_id", opp_id)

    return {
        "status": "success",
        "message": f"商机 {opp_id} 已更新为 {stage}",
    }


async def analyze_pipeline(input_data: dict[str, Any], state: "ToolState") -> dict[str, Any]:
    """分析销售管道"""
    group_by = input_data.get("group_by", "stage")

    set_state("last_analysis_group_by", group_by)

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


async def query_customer_stream(input_data: dict[str, Any], state: "ToolState") -> Any:
    """查询客户（SSE 流式返回） — 逐条返回记录

    返回 AsyncGenerator，SDK 自动转为 SSE 流式响应。
    """
    import asyncio
    customer_name = input_data.get("customer_name", "")

    # 从 mock_data.yaml 查询
    conditions = {"name": customer_name} if customer_name else {}
    records = data_store.query("crm", "accounts", conditions, limit=10)

    set_state("last_query_entity", "account")
    set_state("last_query_keyword", customer_name)
    set_state("query_count", get_state("query_count", 0) + 1)

    async def stream():
        # 先发 meta
        yield {"type": "meta", "total": len(records)}
        # 逐条发送记录
        for record in records:
            await asyncio.sleep(0.3)  # 模拟延迟
            yield {"type": "record", "data": record}
        # 最后发 summary
        yield {"type": "summary", "text": f"共找到 {len(records)} 条 {customer_name} 相关客户"}

    return stream()
