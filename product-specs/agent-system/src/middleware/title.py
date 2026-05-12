"""会话标题生成中间件 — 异步生成，不阻塞主流程

仅在首次对话（thread 第一条消息）时触发：
1. after_agent 阶段检测是否需要生成标题
2. 如果需要，启动异步任务在后台生成（LLM 优先，规则 fallback）
3. 生成完成后持久化到 ai_conversation 表
4. 前端通过 SSE 事件 `title_update` 接收新标题替换"新对话"

不阻塞 Agent 响应流，标题生成耗时不计入用户等待时间。
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from langchain_core.messages import HumanMessage, AIMessage
from langchain.agents.middleware.types import AgentMiddleware, AgentState
from langgraph.config import get_config
from langgraph.runtime import Runtime

logger = logging.getLogger(__name__)


class TitleMiddleware(AgentMiddleware):
    """异步生成会话标题 — 仅首次对话触发，后台执行不阻塞"""

    def __init__(self, llm: Any = None) -> None:
        super().__init__()
        self._llm = llm
        self._generated: set[str] = set()  # 已生成标题的 thread_id

    def after_agent(self, state: AgentState, runtime: Runtime) -> dict[str, Any] | None:
        """同步版本 — 不执行任何操作，所有逻辑在 aafter_agent 中"""
        return None

    async def aafter_agent(self, state: AgentState, runtime: Runtime) -> dict[str, Any] | None:
        """检测是否需要生成标题，如果需要则启动异步任务"""
        try:
            configurable = get_config().get("configurable", {})
            thread_id = configurable.get("thread_id", "")
            tenant_id = configurable.get("tenant_id", "")
            user_id = configurable.get("user_id", "")
        except Exception:
            return None

        # 每个 thread 只生成一次标题
        if thread_id in self._generated:
            return None

        messages = state.get("messages", [])
        # 只有首次对话（只有一条 user 消息）才生成标题
        user_messages = [m for m in messages if isinstance(m, HumanMessage)]
        if len(user_messages) != 1:
            # 非首次对话，标记为已处理避免后续重复检查
            if thread_id:
                self._generated.add(thread_id)
            return None

        first_human = user_messages[0]
        content = first_human.content if isinstance(first_human.content, str) else str(first_human.content)
        if not content.strip():
            return None

        # 获取 Agent 回复
        last_ai = ""
        for m in reversed(messages):
            if isinstance(m, AIMessage) and not getattr(m, "tool_calls", None):
                last_ai = m.content if isinstance(m.content, str) else str(m.content)
                break

        # 标记为已处理
        self._generated.add(thread_id)

        # 启动异步任务生成标题（不阻塞 Agent 响应）
        asyncio.ensure_future(
            self._async_generate_and_persist(
                thread_id, tenant_id, user_id, content, last_ai
            )
        )

        return None

    async def _async_generate_and_persist(
        self, thread_id: str, tenant_id: str, user_id: str,
        user_input: str, agent_output: str,
    ) -> None:
        """异步生成标题并持久化"""
        start = time.monotonic()
        try:
            title = await self._generate_title(user_input, agent_output)
            duration_ms = (time.monotonic() - start) * 1000
            logger.info("Title generated for thread %s: '%s' (%.0fms)",
                        thread_id, title, duration_ms)

            if title:
                self._persist_title(thread_id, tenant_id, user_id, title)
                # 记录 tracing span
                self._record_span(thread_id, title, duration_ms)

        except Exception as e:
            logger.warning("Async title generation failed (non-fatal): %s", e)

    async def _generate_title(self, user_input: str, agent_output: str) -> str:
        """生成标题 — LLM 优先，规则 fallback"""
        if self._llm is not None:
            try:
                title = await self._llm_generate(user_input, agent_output)
                if title and len(title) <= 30:
                    return title
            except asyncio.TimeoutError:
                logger.warning("LLM title generation timed out, fallback to rules")
            except Exception as e:
                logger.warning("LLM title generation failed: %s, fallback to rules", e)

        return self._rule_generate(user_input)

    async def _llm_generate(self, user_input: str, agent_output: str) -> str:
        """用 LLM 生成简短标题"""
        prompt = (
            "请为以下对话生成一个简短的中文标题（10-20个字，不要标点符号）。\n\n"
            f"用户: {user_input[:200]}\n"
            f"助手: {agent_output[:300]}\n\n"
            "标题:"
        )
        result = await asyncio.wait_for(
            self._llm.ainvoke(prompt, config={"callbacks": [], "tags": ["__title_internal__"]}),
            timeout=8,
        )
        title = getattr(result, "content", None) or str(result)
        title = title.strip().strip('"').strip("'").strip("《》")
        for prefix in ("标题：", "标题:", "Title:", "title:"):
            if title.startswith(prefix):
                title = title[len(prefix):].strip()
        return title[:30] if title else ""

    @staticmethod
    def _rule_generate(user_input: str) -> str:
        """规则生成：截取用户输入的核心内容"""
        text = user_input.strip()
        for prefix in ("帮我", "请帮我", "请", "帮忙", "麻烦"):
            if text.startswith(prefix):
                text = text[len(prefix):]
                break
        text = text.strip()
        if len(text) > 25:
            return text[:25] + "..."
        return text or "新对话"

    def _persist_title(self, thread_id: str, tenant_id: str, user_id: str, title: str) -> None:
        """将标题持久化到 ai_conversation 表"""
        try:
            from src.store.pg_pool import get_conn

            now = int(time.time() * 1000)
            tid = int(tenant_id) if str(tenant_id).isdigit() else 0

            with get_conn() as conn:
                cur = conn.cursor()
                cur.execute(
                    "SELECT id, title FROM ai_conversation "
                    "WHERE tenant_id=%s AND thread_id=%s AND delete_flg=0",
                    (tid, thread_id))
                row = cur.fetchone()

                if row:
                    conv_id, existing_title = row
                    if not existing_title or existing_title in ('', '新对话', '对话'):
                        cur.execute(
                            "UPDATE ai_conversation SET title=%s, updated_at=%s WHERE id=%s",
                            (title, now, conv_id))
                        logger.debug("Title persisted: conv=%s title='%s'", conv_id, title)
                else:
                    logger.debug("Conversation not yet created for thread %s, title will be set by TraceWriter", thread_id)

        except Exception as e:
            logger.warning("Title persist failed (non-fatal): %s", e)

    @staticmethod
    def _record_span(thread_id: str, title: str, duration_ms: float) -> None:
        """记录 tracing span"""
        try:
            from src.middleware.tracing import tracing_middleware
            tracing_middleware._add_to_thread(
                thread_id, "middleware", "TitleMiddleware", duration_ms,
                {"title": title, "method": "llm" if duration_ms > 100 else "rule"},
                input_data={"trigger": "首次对话"},
                output_data={"title": title},
                detail=f"生成标题: {title}",
            )
        except Exception:
            pass
