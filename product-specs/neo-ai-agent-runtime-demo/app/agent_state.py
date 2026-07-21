"""AgentState 模拟 — 对齐 neo-apps-ai-agent-service V2 架构

V2 架构中 Agent 运行时状态分为三层：
1. ThreadState（图 state）— LangGraph MessagesState 扩展，只存图级数据
2. configurable — 请求级上下文（tenant_id/user_id/thread_id 等），通过 get_config() 传递
3. AgentRuntimeContext — 运行时上下文（memory_context/skill_directive），存在 configurable 中

对齐 neo-apps-ai-agent-service/service/neo_agent_v2/agents/thread_state.py:
    class ThreadState(MessagesState):
        artifacts: Annotated[list[Artifact], artifacts_reducer]
        images: Annotated[list[ImageData], operator.add]
        title: str | None
        thread_data: dict[str, Any]
        sandbox: dict[str, Any]

Tool 通过 InjectedState 获取图 state，通过 get_config().configurable 获取请求上下文。
"""
from __future__ import annotations

from typing import Any


def create_thread_state(user_input: str = "") -> dict[str, Any]:
    """创建模拟的 ThreadState（图 state）

    对齐 V2 ThreadState 字段，只包含图级数据。
    """
    from langchain_core.messages import HumanMessage, SystemMessage

    return {
        # LangGraph MessagesState 核心字段
        "messages": [
            SystemMessage(content="你是 CRM 智能助手"),
            HumanMessage(content=user_input),
        ],

        # ThreadState 扩展字段
        "artifacts": [],
        "images": [],
        "title": None,
        "thread_data": {},
        "sandbox": {},
    }


def create_configurable(
    tenant_id: int = 292193,
    user_id: str = "100000000000000006",
    thread_id: str = "th_demo_001",
    language_code: str = "zh",
    language_name: str = "zh-CN",
) -> dict[str, Any]:
    """创建模拟的 configurable（请求级上下文）

    对齐 neo-apps-ai-agent-service 中通过 get_config().configurable 传递的数据。
    """
    return {
        "thread_id": thread_id,
        "tenant_id": tenant_id,
        "user_id": user_id,
        "language_code": language_code,
        "language_name": language_name,
        "conversation_id": f"conv_{thread_id}",
        "agent_name": "query-crm-data",
        "files": [],
        "extend_params": {"source": "workbuddy", "platform": "web"},
    }


def create_runtime_context() -> dict[str, Any]:
    """创建模拟的 AgentRuntimeContext

    对齐 neo-apps-ai-agent-service/service/neo_agent_v2/context.py:
        agent_local: 仅当前 Agent 可见（skill_directive/memory_context）
        agent_shared: 全链路透传的背景信息
    """
    return {
        "agent_local": {
            "memory_context": {
                "user_profile": "张伟，华东区销售经理，负责仁科等大客户",
                "agent_rules": "回答简洁，数据使用表格展示",
            },
        },
        "agent_shared": "",
    }


def create_agent_state(
    user_input: str = "",
    tenant_id: int = 292193,
    user_id: str = "100000000000000006",
    thread_id: str = "th_demo_001",
) -> dict[str, Any]:
    """创建完整的 Agent 运行时状态（供 Demo API 接口使用）

    合并 thread_state + configurable + runtime_context 为一个 dict，
    用于传给 ToolState.from_agent_state() 进行跨服务参数传递。

    注意：在真实 LangGraph 图中，这三层是分开传递的：
    - thread_state → 图节点的 state 参数
    - configurable → get_config().configurable
    - runtime_context → configurable["runtime_context"]

    Demo 中合并为一个 dict 是为了验证 ToolState 的 from_agent_state/write_back 链路。
    """
    thread_state = create_thread_state(user_input)
    configurable = create_configurable(tenant_id, user_id, thread_id)
    runtime_ctx = create_runtime_context()

    # 合并为 ToolState.from_agent_state 可消费的格式
    # from_agent_state 会排除 messages/interrupt_event/_limits
    return {
        # 图 state 字段（messages 会被 from_agent_state 排除）
        "messages": thread_state["messages"],
        "artifacts": thread_state["artifacts"],
        "title": thread_state["title"],
        "thread_data": thread_state["thread_data"],
        "sandbox": thread_state["sandbox"],

        # configurable 字段
        "tenant_id": configurable["tenant_id"],
        "user_id": configurable["user_id"],
        "thread_id": configurable["thread_id"],
        "agent_name": configurable["agent_name"],
        "language_code": configurable["language_code"],
        "language_name": configurable["language_name"],
        "extend_params": configurable["extend_params"],

        # runtime_context 字段
        "memory_context": runtime_ctx["agent_local"]["memory_context"],

        # 用户输入
        "user_input": user_input,
    }
