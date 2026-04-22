"""NeoAgentV2 适配器 — 单例懒加载，对外暴露 execute()"""

from __future__ import annotations

import asyncio
import logging
from typing import AsyncGenerator, Any

from langchain_core.messages import HumanMessage
from langgraph.graph.state import CompiledStateGraph

logger = logging.getLogger(__name__)


class NeoAgentV2Adapter:
    """v2 Agent 适配器（单例），懒加载 + 流式输出"""

    def __init__(self):
        self._agent: CompiledStateGraph | None = None
        self._init_lock = asyncio.Lock()

    async def _ensure_agent(self) -> CompiledStateGraph:
        if self._agent is not None:
            return self._agent
        async with self._init_lock:
            if self._agent is not None:
                return self._agent
            self._agent = await self._create_agent()
            logger.info("NeoAgentV2 Agent 初始化完成")
            return self._agent

    async def _create_agent(self) -> CompiledStateGraph:
        """创建 Agent — 子类可覆盖此方法自定义创建逻辑"""
        from src.agents.langchain_agent import create_deep_agent, LangChainAgentConfig
        from src.tools.base import ToolRegistry
        from src.tools.crm_backend import CrmSimulatedBackend
        from src.tools.crm_tools import register_crm_tools
        from src.skills.base import SkillRegistry
        from src.skills.crm_skills import register_crm_skills
        from src.core.prompt_builder import build_system_prompt
        from src.middleware import (
            ToolErrorHandlingMiddleware,
            DanglingToolCallMiddleware,
            SummarizationMiddleware,
            LoopDetectionMiddleware,
            AgentLoggingMiddleware,
            MemoryMiddleware,
        )
        from src.core.checkpointer import create_async_redis_checkpointer
        from src.memory.fts_engine import FTSMemoryEngine
        import os

        backend = CrmSimulatedBackend()
        reg = ToolRegistry()
        register_crm_tools(reg, backend)

        skill_reg = SkillRegistry()
        register_crm_skills(skill_reg)

        # 生产环境使用 Redis checkpointer
        checkpointer = await create_async_redis_checkpointer()

        # 初始化长期记忆引擎（FTS5 + LLM 提取）
        from langchain_openai import ChatOpenAI
        memory_llm = ChatOpenAI(
            model="deepseek-chat",
            api_key=os.environ.get("DEEPSEEK_API_KEY", ""),
            base_url="https://api.deepseek.com",
            max_tokens=2048,
        )
        memory_engine = FTSMemoryEngine(
            storage_dir="./data/memory",
            llm=memory_llm,
            debounce_seconds=5.0,
        )

        config = LangChainAgentConfig(
            model="deepseek-chat",
            api_key=os.environ.get("DEEPSEEK_API_KEY", ""),
            api_base="https://api.deepseek.com",
            tool_registry=reg,
            skill_registry=skill_reg,
            system_prompt=build_system_prompt(agent_name="CRM-Agent", skills=skill_reg.list_all()),
            checkpointer=checkpointer,
            middlewares=[
                AgentLoggingMiddleware(
                    skill_names=[s.name for s in skill_reg.list_all()],
                    tool_names=[t.name for t in reg.all_tools],
                    agent_name="CRM-Agent",
                ),
                DanglingToolCallMiddleware(),
                SummarizationMiddleware(),
                MemoryMiddleware(engine=memory_engine),
                LoopDetectionMiddleware(),
                ToolErrorHandlingMiddleware(),
            ],
        )
        return create_deep_agent(config)

    async def execute(
        self,
        thread_id: str,
        user_input: str,
        history: list[dict[str, Any]] | None = None,
    ) -> AsyncGenerator[dict[str, Any], None]:
        """执行 Agent，流式输出 SSE 事件"""
        from src.core.streaming import stream_agent_response

        agent = await self._ensure_agent()
        messages = _build_messages(user_input, history)
        config = {"configurable": {"thread_id": thread_id}}

        async for sse_event in stream_agent_response(agent, {"messages": messages}, config):
            yield sse_event.to_dict()


def _build_messages(user_input: str, history: list[dict] | None = None) -> list:
    """将历史消息 + 用户输入转为 LangChain Message 列表"""
    from langchain_core.messages import HumanMessage, AIMessage, SystemMessage

    messages = []
    if history:
        for msg in history:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            if role == "user":
                messages.append(HumanMessage(content=content))
            elif role == "assistant":
                messages.append(AIMessage(content=content))
            elif role == "system":
                messages.append(SystemMessage(content=content))
    messages.append(HumanMessage(content=user_input))
    return messages


# 全局单例
neo_agent_v2_adapter = NeoAgentV2Adapter()
