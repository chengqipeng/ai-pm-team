"""AgentState 模拟 — 对应 LangGraph 中 Agent 的运行时状态

模拟 neo-apps-ai-agent-service 中的 AgentState（TypedDict/dict），
演示 ToolState 与 AgentState 之间的转换和跨服务参数传递。
"""
from __future__ import annotations

from typing import Any


def create_agent_state(
    tenant_id: int = 292193,
    user_id: str = "100000000000000006",
    thread_id: str = "th_demo_001",
    user_input: str = "",
) -> dict[str, Any]:
    """创建模拟的 LangGraph AgentState

    对应 LangGraph 中 MessagesState + 自定义扩展字段。
    """
    return {
        # LangGraph 核心字段
        "messages": [
            {"role": "system", "content": "你是 CRM 智能助手"},
            {"role": "user", "content": user_input},
        ],

        # 身份与会话（来自 RequestContext）
        "tenant_id": tenant_id,
        "user_id": user_id,
        "thread_id": thread_id,
        "agent_name": "query-crm-data",

        # 用户输入
        "user_input": user_input,
        "language_name": "zh-CN",
        "language_code": "zh",

        # 记忆上下文
        "memory_context": {
            "user_profile": "张伟，华东区销售经理，负责仁科等大客户",
            "agent_rules": "回答简洁，数据使用表格展示",
        },

        # 文件列表（前序 Tool 结果）
        "file_list": [],

        # 任务结果
        "task_results": [],

        # 执行追踪
        "total_llm_calls": 0,
        "total_tool_calls": 0,
        "query_count": 0,

        # 当前话题
        "current_topic": "crm_query",

        # 扩展参数
        "extend_params": {"source": "workbuddy", "platform": "web"},

        # 不可序列化字段（ToolState.from_agent_state 会排除）
        "interrupt_event": None,
    }
