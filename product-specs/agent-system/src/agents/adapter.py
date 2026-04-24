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
        """创建 Agent — 使用 build_middleware 动态组装中间件"""
        from src.agents.langchain_agent import create_deep_agent, LangChainAgentConfig
        from src.tools.base import ToolRegistry
        from src.tools.crm_backend import CrmSimulatedBackend
        from src.tools.crm_tools import register_crm_tools
        from src.skills.base import SkillRegistry
        from src.skills.crm_skills import register_crm_skills
        from src.core.prompt_builder import build_system_prompt
        from src.core.checkpointer import create_async_redis_checkpointer
        from src.middleware.builder import build_middleware
        from src.memory.fts_engine import FTSMemoryEngine
        from src.skills.tracker import SkillTracker
        from src.skills.optimizer import SkillOptimizer
        import os

        backend = CrmSimulatedBackend()
        reg = ToolRegistry()
        register_crm_tools(reg, backend)

        skill_reg = SkillRegistry()
        register_crm_skills(skill_reg)

        checkpointer = await create_async_redis_checkpointer()

        # 初始化 LLM（记忆提取 + 技能优化共用）
        from langchain_openai import ChatOpenAI
        aux_llm = ChatOpenAI(
            model="doubao-1-5-pro-32k-250115",
            api_key=os.environ.get("DOUBAO_API_KEY", "651621e7-e495-4728-93ef-ed380e9ddcd1"),
            base_url="https://ark.cn-beijing.volces.com/api/v3/",
            max_tokens=2048,
        )

        # 初始化长期记忆引擎
        memory_engine = FTSMemoryEngine(
            storage_dir="./data/memory",
            llm=aux_llm,
            debounce_seconds=5.0,
        )

        # 初始化自改进学习循环
        tracker = SkillTracker(db_path="./data/skill_metrics.db")
        optimizer = SkillOptimizer(
            llm=aux_llm,
            tracker=tracker,
            skills_dir="./skills/auto-generated",
            skill_registry=skill_reg,
            optimize_threshold=5,
        )

        system_prompt = build_system_prompt(agent_name="CRM-Agent", skills=skill_reg.list_all())

        # 动态组装中间件
        middlewares = build_middleware(
            system_prompt=system_prompt,
            agent_name="CRM-Agent",
            memory_engine=memory_engine,
        )

        config = LangChainAgentConfig(
            model="doubao-1-5-pro-32k-250115",
            api_key=os.environ.get("DOUBAO_API_KEY", "651621e7-e495-4728-93ef-ed380e9ddcd1"),
            api_base="https://ark.cn-beijing.volces.com/api/v3/",
            tool_registry=reg,
            skill_registry=skill_reg,
            system_prompt=system_prompt,
            checkpointer=checkpointer,
            middlewares=middlewares,
        )
        return create_deep_agent(config)

    async def execute(
        self,
        thread_id: str,
        user_input: str,
        history: list[dict[str, Any]] | None = None,
        files: list | None = None,
        extend_params: dict[str, Any] | None = None,
    ) -> AsyncGenerator[dict[str, Any], None]:
        """执行 Agent，流式输出 SSE 事件"""
        from src.core.streaming import stream_agent_response

        agent = await self._ensure_agent()
        messages = _build_messages(user_input, history)
        config = {
            "configurable": {
                "thread_id": thread_id,
                "files": files or [],
                "extend_params": extend_params or {},
                "parsed_files": [],
            },
            "recursion_limit": 100,
        }

        async for sse_event in stream_agent_response(agent, {"messages": messages}, config):
            yield sse_event.to_dict()

    async def execute_agui(
        self,
        thread_id: str,
        user_input: str,
        run_id: str | None = None,
        history: list[dict[str, Any]] | None = None,
    ) -> AsyncGenerator[Any, None]:
        """AG-UI 模式执行：输出标准 AG-UI 事件流

        使用 AGUIConverter + ProgressiveRenderer 管道，
        将 LangGraph astream_events 转换为 AG-UI 协议事件。
        """
        import uuid as _uuid
        from src.agui import create_agui_pipeline

        agent = await self._ensure_agent()
        _run_id = run_id or _uuid.uuid4().hex

        converter, renderer = create_agui_pipeline(
            run_id=_run_id, thread_id=thread_id,
            history_messages=history,
        )

        messages = _build_messages(user_input, history)
        input_data = {"messages": messages}
        config = {"configurable": {"thread_id": thread_id}}

        astream = agent.astream_events(input_data, config=config, version="v2")
        async for event in renderer.process(converter.convert(astream)):
            yield event


def _build_messages(user_input: str, history: list[dict] | None = None) -> list:
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


neo_agent_v2_adapter = NeoAgentV2Adapter()
