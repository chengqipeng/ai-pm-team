"""会话标题生成中间件 — 同步规则生成 + 异步 LLM 优化

仅在首次对话（thread 第一条消息）时触发：
1. aafter_agent 同步用规则生成标题（<1ms），立即记录完整 span
2. 同步持久化规则标题到 ai_conversation 表（保证即使 LLM 失败也有标题）
3. 启动后台任务调用 LLM 优化标题，成功后覆盖规则标题
4. 前端通过轮询 /api/conversations 获取最终标题（规则版立即可见，LLM 版几秒后更新）

设计权衡：
- 规则生成耗时可忽略，不阻塞主流程
- LLM 优化异步执行，即使失败也不影响基本功能
- Span 立即可见，链路完整
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
    """会话标题生成 — 首次对话规则同步 + LLM 异步优化"""

    def __init__(self, llm: Any = None) -> None:
        super().__init__()
        self._llm = llm
        self._generated: set[str] = set()  # 已生成标题的 thread_id

    def after_agent(self, state: AgentState, runtime: Runtime) -> dict[str, Any] | None:
        """同步版本 — fallback 用"""
        return self._trigger(state, runtime, is_async=False)

    async def aafter_agent(self, state: AgentState, runtime: Runtime) -> dict[str, Any] | None:
        """异步版本 — LangGraph 在 astream 模式下优先调用此方法"""
        return self._trigger(state, runtime, is_async=True)

    def _trigger(self, state: AgentState, runtime: Runtime, is_async: bool) -> dict[str, Any] | None:
        """检测首次对话，同步生成规则标题，异步启动 LLM 优化"""
        try:
            configurable = get_config().get("configurable", {})
            thread_id = configurable.get("thread_id", "")
            tenant_id = configurable.get("tenant_id", "")
            user_id = configurable.get("user_id", "")
        except Exception as e:
            logger.error("[TitleMiddleware] get_config failed: %s", e)
            return None

        # 每个 thread 只生成一次标题
        if thread_id in self._generated:
            return None

        messages = state.get("messages", [])
        user_messages = [m for m in messages if isinstance(m, HumanMessage)]

        # 首次对话判断：只有一条 user 消息
        if len(user_messages) != 1:
            if thread_id:
                self._generated.add(thread_id)
            return None

        first_human = user_messages[0]
        content = first_human.content if isinstance(first_human.content, str) else str(first_human.content)
        if not content.strip():
            return None

        # 获取 Agent 回复（用于 LLM 优化）
        last_ai = ""
        for m in reversed(messages):
            if isinstance(m, AIMessage) and not getattr(m, "tool_calls", None):
                last_ai = m.content if isinstance(m.content, str) else str(m.content)
                break

        # 标记为已处理
        self._generated.add(thread_id)

        # ── 同步：规则生成 + 立即记录 span + 立即持久化 ──
        start = time.monotonic()
        rule_title = self._rule_generate(content)
        rule_duration_ms = (time.monotonic() - start) * 1000

        # 立即持久化规则标题（即使后续 LLM 失败，也有标题）
        self._persist_title(thread_id, tenant_id, user_id, rule_title)

        # 立即记录完整 span
        self._record_span(thread_id, rule_title, rule_duration_ms, method="rule",
                          user_input=content, status="success")

        logger.info("[TitleMiddleware] rule title='%s' (%.1fms) thread=%s",
                    rule_title, rule_duration_ms, thread_id)

        # ── 异步：LLM 优化（后台执行，成功后覆盖规则标题）──
        if self._llm is not None and last_ai:
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(
                    self._async_llm_optimize(
                        thread_id, tenant_id, user_id, content, last_ai, rule_title,
                    )
                )
            except RuntimeError:
                logger.debug("[TitleMiddleware] no running loop, skip LLM optimization")

        return None

    async def _async_llm_optimize(
        self, thread_id: str, tenant_id: str, user_id: str,
        user_input: str, agent_output: str, fallback_title: str,
    ) -> None:
        """后台调用 LLM 优化标题，成功后覆盖规则标题"""
        start = time.monotonic()
        try:
            title = await asyncio.wait_for(
                self._llm_generate(user_input, agent_output),
                timeout=15,  # 给 LLM 足够时间（后台任务，用户已经看到规则标题）
            )
            if title and len(title) <= 30 and title != fallback_title:
                self._persist_title(thread_id, tenant_id, user_id, title)
                logger.info("[TitleMiddleware] LLM title='%s' overrode rule='%s' thread=%s",
                            title, fallback_title, thread_id)
            else:
                logger.debug("[TitleMiddleware] LLM title kept: '%s' thread=%s",
                             title, thread_id)
        except asyncio.TimeoutError:
            logger.warning("[TitleMiddleware] LLM timeout after %.1fs, keep rule title='%s'",
                           time.monotonic() - start, fallback_title)
        except Exception as e:
            logger.warning("[TitleMiddleware] LLM optimize failed: %s, keep rule title", e)

    async def _llm_generate(self, user_input: str, agent_output: str) -> str:
        """用 LLM 生成简短标题"""
        prompt = (
            "请为以下对话生成一个简短的中文标题（10-20个字，不要标点符号）。\n\n"
            f"用户: {user_input[:200]}\n"
            f"助手: {agent_output[:300]}\n\n"
            "标题:"
        )
        result = await self._llm.ainvoke(
            prompt,
            config={"callbacks": [], "tags": ["__title_internal__"]},
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

    @staticmethod
    def _record_span(
        thread_id: str, title: str, duration_ms: float,
        method: str = "rule", user_input: str = "", status: str = "success",
    ) -> None:
        """记录 title_generation span"""
        try:
            from src.middleware.tracing import tracing_middleware
            tracing_middleware._add_to_thread(
                thread_id, "title_generation", "title_generation", duration_ms,
                {"title": title, "method": method},
                input_data={
                    "trigger": "首次对话",
                    "user_input": user_input[:200],
                },
                output_data={
                    "title": title,
                    "method": method,
                    "optimized_by_llm": "后续异步优化中" if method == "rule" else "已优化",
                },
                detail=f"首轮对话生成标题「{title}」（{method}）",
                status=status,
            )
        except Exception as e:
            logger.debug("[TitleMiddleware] record span failed: %s", e)

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
                    # 允许覆盖：空、默认值、或规则标题（LLM 优化时会覆盖）
                    if not existing_title or existing_title in ('', '新对话', '对话') or existing_title.endswith('...'):
                        cur.execute(
                            "UPDATE ai_conversation SET title=%s, updated_at=%s WHERE id=%s",
                            (title, now, conv_id))
                        logger.info("[TitleMiddleware] persisted: conv=%s title='%s'", conv_id, title)
                # conversation 不存在时（TraceWriter 尚未创建），标题会通过后续 LLM 优化再次尝试持久化

        except Exception as e:
            logger.warning("[TitleMiddleware] persist failed: %s", e)
