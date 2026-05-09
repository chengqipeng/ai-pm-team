"""会话标题生成中间件 — LLM 摘要 + 规则 fallback

在 after_agent 阶段，根据用户第一条消息和 Agent 回复生成简短的会话标题。
- LLM 可用时：调用 LLM 生成 10-20 字的中文摘要标题
- LLM 不可用时：截取用户第一条消息的前 30 个字符

标题生成后直接持久化到 ai_conversation 表，不依赖 TraceWriter 的规则截取。
"""
from __future__ import annotations

import logging
from typing import Any

from langchain_core.messages import HumanMessage, AIMessage
from langchain.agents.middleware.types import AgentMiddleware, AgentState
from langgraph.config import get_config
from langgraph.runtime import Runtime

logger = logging.getLogger(__name__)


class TitleMiddleware(AgentMiddleware):
    """生成会话标题 — LLM 优先，规则 fallback，生成后直接持久化"""

    def __init__(self, llm: Any = None) -> None:
        super().__init__()
        self._llm = llm
        self._generated: set[str] = set()  # 已生成标题的 thread_id

    def after_agent(self, state: AgentState, runtime: Runtime) -> dict[str, Any] | None:
        # 已有标题则跳过
        if state.get("title"):
            return None

        try:
            configurable = get_config().get("configurable", {})
            thread_id = configurable.get("thread_id", "")
            tenant_id = configurable.get("tenant_id", "")
            user_id = configurable.get("user_id", "")
        except Exception as e:
            logger.error("TitleMiddleware get_config failed: %s", e, exc_info=True)
            thread_id = ""
            tenant_id = ""
            user_id = ""

        # 每个 thread 只生成一次标题
        if thread_id in self._generated:
            return None

        messages = state.get("messages", [])
        first_human = next((m for m in messages if isinstance(m, HumanMessage)), None)
        if not first_human:
            return None

        content = first_human.content if isinstance(first_human.content, str) else str(first_human.content)
        if not content.strip():
            return None

        # 获取 Agent 回复（用于 LLM 生成更准确的标题）
        last_ai = ""
        for m in reversed(messages):
            if isinstance(m, AIMessage) and not getattr(m, "tool_calls", None):
                last_ai = m.content if isinstance(m.content, str) else str(m.content)
                break

        title = self._generate_title(content, last_ai)
        self._generated.add(thread_id)
        logger.info("Generated title for thread %s: %s", thread_id, title)

        # 持久化标题到数据库
        if thread_id and title:
            self._persist_title(thread_id, tenant_id, user_id, title)

        return {"title": title}

    def _persist_title(self, thread_id: str, tenant_id: str, user_id: str, title: str) -> None:
        """将标题持久化到 ai_conversation 表"""
        try:
            import time
            from src.store.pg_pool import get_conn

            now = int(time.time() * 1000)
            tid = int(tenant_id) if str(tenant_id).isdigit() else 0

            with get_conn() as conn:
                cur = conn.cursor()
                # 查找对应的 conversation 记录
                cur.execute(
                    "SELECT id, title FROM ai_conversation "
                    "WHERE tenant_id=%s AND thread_id=%s AND delete_flg=0",
                    (tid, thread_id))
                row = cur.fetchone()

                if row:
                    conv_id, existing_title = row
                    # 只在标题为空或为默认值时更新（避免覆盖用户手动设置的标题）
                    if not existing_title or existing_title in ('', '新对话', '对话') or existing_title == title:
                        cur.execute(
                            "UPDATE ai_conversation SET title=%s, updated_at=%s WHERE id=%s",
                            (title, now, conv_id))
                        logger.debug("Title persisted for conversation %s: %s", conv_id, title)
                else:
                    # conversation 记录尚未创建（TraceWriter 还没执行），
                    # 标题会通过 state["title"] 传递给 TraceWriter 使用
                    logger.debug("Conversation not found for thread %s, title will be set by TraceWriter", thread_id)

        except Exception as e:
            # 持久化失败不影响主流程
            logger.warning("Title persist failed (non-fatal): %s", e)

    def _generate_title(self, user_input: str, agent_output: str) -> str:
        """生成标题 — LLM 优先，规则 fallback"""
        if self._llm is not None:
            try:
                import asyncio
                loop = asyncio.get_running_loop()
                # 在已有事件循环中：提交协程到当前 loop，在新线程中等待结果
                import concurrent.futures
                future = asyncio.run_coroutine_threadsafe(
                    self._llm_generate(user_input, agent_output), loop
                )
                title = future.result(timeout=8)
                if title and len(title) <= 30:
                    return title
            except (asyncio.TimeoutError, concurrent.futures.TimeoutError):
                logger.warning("LLM title generation timed out, fallback to rules")
            except RuntimeError:
                # 没有 running loop（不太可能在 LangGraph 里发生）
                try:
                    import asyncio
                    title = asyncio.run(self._llm_generate(user_input, agent_output))
                    if title and len(title) <= 30:
                        return title
                except Exception:
                    pass
            except Exception as e:
                logger.warning("LLM title generation failed, fallback to rules: %s", e)

        # 规则 fallback
        return self._rule_generate(user_input)

    async def _llm_generate(self, user_input: str, agent_output: str) -> str:
        """用 LLM 生成简短标题"""
        prompt = (
            "请为以下对话生成一个简短的中文标题（10-20个字，不要标点符号）。\n\n"
            f"用户: {user_input[:200]}\n"
            f"助手: {agent_output[:300]}\n\n"
            "标题:"
        )
        result = await self._llm.ainvoke(prompt)
        title = getattr(result, "content", None) or str(result)
        title = title.strip().strip('"').strip("'").strip("《》")
        # 清理：去掉"标题："前缀
        for prefix in ("标题：", "标题:", "Title:", "title:"):
            if title.startswith(prefix):
                title = title[len(prefix):].strip()
        return title[:30] if title else ""

    @staticmethod
    def _rule_generate(user_input: str) -> str:
        """规则生成：截取用户输入的核心内容"""
        text = user_input.strip()
        # 去掉常见前缀
        for prefix in ("帮我", "请帮我", "请", "帮忙", "麻烦"):
            if text.startswith(prefix):
                text = text[len(prefix):]
                break
        text = text.strip()
        if len(text) > 25:
            return text[:25] + "..."
        return text or "新对话"
