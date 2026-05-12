"""NeoAgentV2 适配器 — 单例懒加载，对外暴露 execute()"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import AsyncGenerator, Any

from langchain_core.messages import HumanMessage
from langgraph.graph.state import CompiledStateGraph

logger = logging.getLogger(__name__)


def _build_metarepo_backend():
    """按环境变量选择 Sim 或 HTTP 后端（与 /api/meta/* 共享同一 AuthClient）"""
    from src.tools._http_auth import get_shared_auth_client
    client = get_shared_auth_client()
    if client is not None:
        from src.tools.metarepo_http_backend import MetarepoHttpBackend
        logger.info("Metarepo tool backend: HTTP → %s", client.base_url)
        return MetarepoHttpBackend(auth_client=client)
    from src.tools.metarepo_backend import MetarepoSimulatedBackend
    logger.info("Metarepo tool backend: Simulated")
    return MetarepoSimulatedBackend()


class NeoAgentV2Adapter:
    """v2 Agent 适配器（单例），懒加载 + 流式输出"""

    def __init__(self):
        self._agent: CompiledStateGraph | None = None
        self._init_lock = asyncio.Lock()
        # A2UI userAction / 外部消息注入队列：thread_id → [message, ...]
        self._pending_messages: dict[str, list[Any]] = {}

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
        from src.tools.metarepo_backend import MetarepoSimulatedBackend
        from src.tools.metarepo_tools import register_metarepo_tools
        from src.skills.base import SkillRegistry
        from src.core.prompt_builder import build_system_prompt
        from src.core.checkpointer import create_async_redis_checkpointer
        from src.middleware.builder import build_middleware
        from src.memory.viking_engine import VikingMemoryEngine
        from src.skills.tracker import SkillTracker
        from src.skills.optimizer import SkillOptimizer
        import os

        backend = CrmSimulatedBackend()
        metarepo_backend = _build_metarepo_backend()
        reg = ToolRegistry()

        skill_reg = SkillRegistry()
        # 权威数据源：ai_skill_definition 表（禁止硬编码）
        try:
            skill_reg.load_from_db(tenant_id=0)
        except Exception as exc:
            logger.warning("从 DB 加载 Skill 失败（Agent 将跳过技能）: %s", exc)

        checkpointer = await create_async_redis_checkpointer()

        # 初始化 LLM（记忆提取 + 技能优化共用）
        from langchain_openai import ChatOpenAI
        _model_name = os.environ.get("AGENT_MODEL", "doubao-seed-2-0-lite-260215")
        _api_key = os.environ.get("AGENT_API_KEY") or os.environ.get("DOUBAO_API_KEY", "651621e7-e495-4728-93ef-ed380e9ddcd1")
        _api_base = os.environ.get("AGENT_API_BASE", "https://ark.cn-beijing.volces.com/api/v3/")

        aux_llm = ChatOpenAI(
            model=_model_name,
            api_key=_api_key,
            base_url=_api_base,
            max_tokens=2048,
        )

        # 初始化长期记忆引擎 — VikingMemoryEngine（腾讯向量库 + PG）
        memory_engine = VikingMemoryEngine(
            vdb_url=os.environ.get("TENCENT_VDB_URL", "http://10.60.2.17"),
            vdb_key=os.environ.get("TENCENT_VDB_KEY", ""),
            vdb_username=os.environ.get("TENCENT_VDB_USERNAME", "root"),
            database_name=os.environ.get("TENCENT_VDB_DATABASE", "viking_memory"),
            collection_name=os.environ.get("TENCENT_VDB_COLLECTION", "memories"),
            llm=aux_llm,
            agent_rules_threshold=5,
        )

        register_crm_tools(reg, backend, memory_engine=memory_engine)
        register_metarepo_tools(reg, metarepo_backend)

        # 初始化自改进学习循环（SkillOptimizer 写入 DB，不再落盘）
        tracker = SkillTracker(db_path="./data/skill_metrics.db")
        optimizer = SkillOptimizer(
            llm=aux_llm,
            tracker=tracker,
            skill_registry=skill_reg,
            optimize_threshold=5,
        )

        system_prompt = build_system_prompt(agent_name="CRM-Agent", skills=skill_reg.list_all())

        # 动态组装中间件（传入 llm 供 QueryRewriteMiddleware + TitleMiddleware 使用）
        middlewares = build_middleware(
            system_prompt=system_prompt,
            agent_name="CRM-Agent",
            memory_engine=memory_engine,
            llm=aux_llm,
        )

        config = LangChainAgentConfig(
            model=_model_name,
            api_key=_api_key,
            api_base=_api_base,
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

        # ── 入口层预处理：毒性检测 → 查询改写 ──
        passed, blocked_reason = await _apply_content_review(user_input, thread_id)
        if not passed:
            # 拦截：直接返回拒绝响应
            yield {"event": "token", "data": {"content": blocked_reason}}
            yield {"event": "done", "data": {"blocked": True, "finished": True}}
            return

        effective_query = await _apply_query_rewrite(user_input, history, thread_id)
        messages = _build_messages(effective_query, history)

        config = {
            "configurable": {
                "thread_id": thread_id,
                "files": files or [],
                "extend_params": extend_params or {},
                "parsed_files": [],
            },
            "recursion_limit": 150,
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
        from src.agui import models as _m

        agent = await self._ensure_agent()
        _run_id = run_id or _uuid.uuid4().hex

        converter, renderer = create_agui_pipeline(
            run_id=_run_id, thread_id=thread_id,
            history_messages=history,
        )

        # ── 入口层预处理：毒性检测 → 查询改写 ──
        passed, blocked_reason = await _apply_content_review(user_input, thread_id)
        if not passed:
            # 拦截：直接作为单条文本消息返回
            msg_id = _uuid.uuid4().hex[:12]
            yield _m.run_started(_run_id, thread_id)
            yield _m.text_message_start(msg_id)
            yield _m.text_message_content(msg_id, blocked_reason)
            yield _m.text_message_end(msg_id)
            yield _m.run_finished(_run_id, thread_id)
            return

        effective_query = await _apply_query_rewrite(user_input, history, thread_id)

        # 将 pending A2UI userAction 注入本次对话
        messages = _build_messages(effective_query, history)
        pending = self._pending_messages.pop(thread_id, None)
        if pending:
            # 按注入顺序追加（用户原始输入仍在末尾，保证 Agent 先看到 UI action 再看到自由文本）
            messages = messages[:-1] + pending + messages[-1:]

        input_data = {"messages": messages}
        config = {"configurable": {"thread_id": thread_id}}

        astream = agent.astream_events(input_data, config=config, version="v2")
        async for event in renderer.process(converter.convert(astream)):
            yield event

    async def execute_a2ui(
        self,
        thread_id: str,
        user_input: str,
        run_id: str | None = None,
        history: list[dict[str, Any]] | None = None,
        *,
        include_state_as_data_model: bool = False,
    ) -> AsyncGenerator[Any, None]:
        """Mode A 执行：输出纯 A2UI 消息流

        复用 AGUI 管道产出事件，然后经 A2UIProjector 过滤成 A2UI 消息
        （SurfaceUpdate / DataModelUpdate / BeginRendering / DeleteSurface）。

        Args:
            include_state_as_data_model: 若开启，会把 STATE_SNAPSHOT 的 data 段转为
                dataModelUpdate（path=/data）送给客户端。
        """
        from src.a2ui import A2UIProjector

        projector = A2UIProjector(include_state_as_data_model=include_state_as_data_model)
        agui_stream = self.execute_agui(
            thread_id=thread_id, user_input=user_input,
            run_id=run_id, history=history,
        )
        async for msg in projector.project(agui_stream):
            yield msg

    # ═══════════════════════════════════════════════════════════
    # 外部消息注入（A2UI userAction / 其他系统触发）
    # ═══════════════════════════════════════════════════════════

    def inject_message(
        self,
        thread_id: str | None,
        message: Any,
        *,
        source: str = "external",
    ) -> None:
        """注入一条消息到指定 thread 的 pending 队列。

        在下一次 `execute` / `execute_agui` 被调用时，pending 消息会被追加到
        `input_data.messages`（位于 user_input 之前）。

        Args:
            thread_id: 目标会话 ID；None 视为默认 thread（不推荐）。
            message:   LangChain `BaseMessage` 或 dict（`{"role", "content"}`）。
            source:    日志标记（"a2ui" / "hook" / "webhook" ...）
        """
        key = thread_id or "__default__"
        bucket = self._pending_messages.setdefault(key, [])
        bucket.append(message)
        logger.info("[inject_message] thread=%s source=%s queue_size=%d",
                    key, source, len(bucket))


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


async def _apply_query_rewrite(user_input: str, history: list[dict] | None = None,
                                thread_id: str | None = None) -> str:
    """入口层查询改写 — 独立 LLM 调用，不进入主 Agent 推理链路

    Args:
        user_input: 用户当前输入
        history: 历史消息 dict 列表 [{"role": "user"/"assistant", "content": "..."}]
        thread_id: 会话 ID，用于 trace 记录

    Returns:
        改写后的查询（单轮对话或改写失败时返回原 query）
    """
    from src.core.query_rewriter import get_query_rewriter
    from langchain_core.messages import HumanMessage, AIMessage

    # 首次对话（无历史）直接跳过，不浪费 LLM 调用
    if not history:
        if thread_id:
            from src.middleware.tracing import tracing_middleware
            tracing_middleware._add_to_thread(
                thread_id, "query_rewrite", "query_rewrite", 0,
                {"original_query": user_input[:500], "rewritten_query": "", "changed": False, "source": "entry", "skipped": True},
                input_data={"original_query": user_input[:500], "source": "entry"},
                output_data={"rewritten_query": "", "changed": False, "skipped": True},
                status="skipped",
                detail="首轮对话，无需改写",
            )
        return user_input

    history_msgs = []
    for msg in history:
        role = msg.get("role", "user")
        content = msg.get("content", "")
        if role == "user":
            history_msgs.append(HumanMessage(content=content))
        elif role == "assistant":
            history_msgs.append(AIMessage(content=content))

    rewriter = get_query_rewriter()
    return await rewriter.rewrite(history_msgs, user_input, thread_id=thread_id)


async def _apply_content_review(user_input: str, thread_id: str | None = None):
    """入口层毒性检测 — 在任何 LLM 调用之前执行

    Returns:
        (passed, blocked_reason): passed=False 时调用方应返回拒绝响应
    """
    from src.core.content_reviewer import get_content_reviewer
    reviewer = get_content_reviewer()
    decision = await reviewer.review(user_input, thread_id=thread_id)
    return decision.passed, decision.blocked_reason


neo_agent_v2_adapter = NeoAgentV2Adapter()
