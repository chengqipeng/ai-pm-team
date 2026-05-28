"""会话标题生成中间件 — 入口阶段异步生成，不阻塞主流程

仅在首次对话（thread 第一条消息）时触发：
1. server.py 入口层同步调用 _rule_generate 生成规则标题（<1ms）
2. 入口层调用 start_async_optimize 启动 LLM 异步优化
3. LLM 优化完成后通过事件通道通知 SSE 流推送 title_update 事件
4. 前端收到 title_update 事件后实时更新标题

设计要点：
- 入口层统一调度，中间件 before_agent 作为兜底
- 不阻塞 Agent 响应流（规则同步 + LLM 异步）
- LLM 标题通过 SSE 事件实时推送，无需前端轮询
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Dict, Optional

from langchain_core.messages import HumanMessage
from langchain.agents.middleware.types import AgentMiddleware, AgentState
from langgraph.config import get_config
from langgraph.runtime import Runtime

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════
# 标题更新事件通道 — 供 SSE 流监听 LLM 优化结果
# ═══════════════════════════════════════════════════════════
_title_events: Dict[str, asyncio.Event] = {}
_title_values: Dict[str, str] = {}


def register_title_listener(thread_id: str) -> asyncio.Event:
    """SSE 流注册标题更新监听器

    Returns:
        asyncio.Event: LLM 标题就绪时会被 set()
    """
    evt = asyncio.Event()
    _title_events[thread_id] = evt
    return evt


def get_updated_title(thread_id: str) -> Optional[str]:
    """获取 LLM 优化后的标题（取后即删）"""
    _title_events.pop(thread_id, None)
    return _title_values.pop(thread_id, None)


def _notify_title_update(thread_id: str, title: str) -> None:
    """LLM 标题就绪后通知监听方"""
    _title_values[thread_id] = title
    evt = _title_events.get(thread_id)
    if evt:
        evt.set()


class TitleMiddleware(AgentMiddleware):
    """会话标题生成 — 入口阶段异步触发，规则同步 + LLM 异步优化

    主流程由 server.py/adapter.py 入口层驱动：
    1. 入口层调用 _rule_generate() 同步生成规则标题
    2. 入口层调用 start_async_optimize() 启动 LLM 异步优化
    3. before_agent 作为兜底（入口层已标记 _generated_threads 则跳过）
    """

    # 模块级共享：所有实例共用，确保入口层标记后中间件链路中的实例也能感知
    _generated_threads: set[str] = set()

    def __init__(self, llm: Any = None) -> None:
        super().__init__()
        self._llm = llm

    def start_async_optimize(
        self, thread_id: str, tenant_id: str, user_id: str, user_input: str,
    ) -> None:
        """由入口层调用 — 标记已处理 + 启动 LLM 异步生成标题

        调用后 before_agent 不会重复触发。
        """
        TitleMiddleware._generated_threads.add(thread_id)
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(
                self._async_generate_title(
                    thread_id, tenant_id, user_id, user_input,
                )
            )
        except RuntimeError:
            logger.debug("[TitleMiddleware] no running loop, skip async title generation")

    def before_agent(self, state: AgentState, runtime: Runtime) -> dict[str, Any] | None:
        """同步版本 — fallback 用"""
        return self._trigger(state, runtime)

    async def abefore_agent(self, state: AgentState, runtime: Runtime) -> dict[str, Any] | None:
        """异步版本 — LangGraph 在 astream 模式下优先调用"""
        return self._trigger(state, runtime)

    def _trigger(self, state: AgentState, runtime: Runtime) -> dict[str, Any] | None:
        """检测首次对话，同步生成规则标题，异步启动 LLM 优化"""
        try:
            configurable = get_config().get("configurable", {})
            thread_id = configurable.get("thread_id", "")
            tenant_id = configurable.get("tenant_id", "")
            user_id = configurable.get("user_id", "")
        except Exception as e:
            logger.error("[TitleMiddleware] get_config failed: %s", e)
            return None

        # fallback tenant_id（AG-UI 模式下 configurable 中可能没有 tenant_id）
        if not tenant_id:
            try:
                from src.core.context import DEFAULT_TENANT_ID
                tenant_id = str(DEFAULT_TENANT_ID)
            except Exception:
                pass

        # 每个 thread 只生成一次标题
        if thread_id in TitleMiddleware._generated_threads:
            return None

        messages = state.get("messages", [])
        user_messages = [m for m in messages if isinstance(m, HumanMessage)]

        # 首次对话判断：只有一条 user 消息
        if len(user_messages) != 1:
            if thread_id:
                TitleMiddleware._generated_threads.add(thread_id)
            return None

        first_human = user_messages[0]
        content = first_human.content if isinstance(first_human.content, str) else str(first_human.content)
        if not content.strip():
            return None

        # 标记为已处理
        TitleMiddleware._generated_threads.add(thread_id)

        # span 已由入口层记录，这里不重复记录

        # ── 异步：LLM 生成标题 ──
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(
                self._async_generate_title(
                    thread_id, tenant_id, user_id, content,
                )
            )
        except RuntimeError:
            logger.debug("[TitleMiddleware] no running loop, skip async title generation")

        return None

    async def _async_generate_title(
        self, thread_id: str, tenant_id: str, user_id: str,
        user_input: str,
    ) -> None:
        """后台任务：LLM 生成标题 → 持久化 → 通知前端

        纯 LLM 模式，不使用规则标题。
        """
        if self._llm is None:
            logger.warning("[TitleMiddleware] no LLM configured, skip title generation for thread=%s", thread_id)
            return

        # 1. LLM 生成标题
        try:
            llm_title = await asyncio.wait_for(
                self._llm_generate_safe(user_input), timeout=15
            )
        except asyncio.TimeoutError:
            logger.warning("[TitleMiddleware] LLM timeout, thread=%s", thread_id)
            return

        if not llm_title:
            logger.warning("[TitleMiddleware] LLM returned empty title, thread=%s", thread_id)
            return

        logger.info("[TitleMiddleware] LLM title='%s' thread=%s", llm_title, thread_id)

        # 更新链路中的 title_generation span（回填 LLM 结果）
        try:
            from src.middleware.tracing import tracing_middleware
            tracing_middleware.update_span(thread_id, "title_generation", {
                "output_data": {"title": llm_title, "method": "llm"},
                "detail": f"标题生成「{llm_title}」（LLM）",
                "metadata": {"title": llm_title, "method": "llm", "phase": "entry"},
            })
        except Exception:
            pass

        # 更新已持久化到 DB 的 span 记录（刷新页面后仍能看到最终标题）
        try:
            from src.store.pg_pool import get_conn
            import json as _json
            with get_conn() as conn:
                cur = conn.cursor()
                cur.execute(
                    "UPDATE ai_trace_span SET output_data=%s, metadata=%s "
                    "WHERE trace_id IN (SELECT trace_id FROM ai_trace WHERE thread_id=%s ORDER BY created_at DESC LIMIT 1) "
                    "AND span_type='title_generation'",
                    (
                        _json.dumps({"title": llm_title, "method": "llm"}, ensure_ascii=False),
                        _json.dumps({"title": llm_title, "method": "llm", "phase": "entry", "detail": f"标题生成「{llm_title}」（LLM）"}, ensure_ascii=False),
                        thread_id,
                    ))
        except Exception as e:
            logger.debug("[TitleMiddleware] DB span update failed: %s", e)

        # 2. 持久化到 DB（重试等待 conversation 记录创建）
        for delay in (0, 1, 2, 3, 5, 10, 15):
            if delay:
                await asyncio.sleep(delay)
            if self._persist_title(thread_id, tenant_id, user_id, llm_title):
                logger.info("[TitleMiddleware] title persisted: thread=%s title='%s'", thread_id, llm_title)
                # 3. 通知前端更新标题
                _notify_title_update(thread_id, llm_title)
                return

        logger.warning("[TitleMiddleware] title persist failed after retries, thread=%s tenant=%s title='%s'",
                       thread_id, tenant_id, llm_title)
        # 即使持久化失败，也通知前端
        _notify_title_update(thread_id, llm_title)

    async def _llm_generate_safe(self, user_input: str) -> str:
        """安全的 LLM 调用（异常时返回空字符串）"""
        try:
            return await self._llm_generate(user_input)
        except Exception as e:
            logger.warning("[TitleMiddleware] LLM generate failed: %s", e)
            return ""

    async def _llm_generate(self, user_input: str) -> str:
        """基于用户输入生成简短标题"""
        prompt = (
            "你是 CRM 智能助手的标题生成器。请根据用户的首条消息，生成一个简洁的会话标题。\n\n"
            "要求：\n"
            "- 5-15个中文字\n"
            "- 提炼核心意图或主题，不要复述原文\n"
            "- 不要加标点符号、引号、书名号\n"
            "- 如果是自我介绍/身份说明，提取角色关键词\n"
            "- 如果是数据查询/分析，提取业务对象+动作\n\n"
            "示例：\n"
            "用户: 帮我查一下活跃客户 → 查询活跃客户\n"
            "用户: 我是华东区的销售总监，管理15个人的团队 → 华东区销售总监\n"
            "用户: 统计华东区团队本月的商机金额和数量 → 华东区商机月度统计\n"
            "用户: 帮忙看看系统有多少客户，按行业分类统计 → 客户行业分布统计\n"
            "用户: 分析商机 Pipeline → Pipeline分析\n"
            "用户: 你好 → 新会话\n\n"
            f"用户: {user_input[:300]}\n"
            "标题:"
        )
        result = await self._llm.ainvoke(
            prompt,
            config={"callbacks": [], "tags": ["__title_internal__"]},
        )
        title = getattr(result, "content", None) or str(result)
        title = title.strip().strip('"').strip("'").strip("《》").strip("「」")
        for prefix in ("标题：", "标题:", "Title:", "title:"):
            if title.startswith(prefix):
                title = title[len(prefix):].strip()
        # 去掉可能残留的标点
        title = title.rstrip("。，！？.!?,;；")
        return title[:20] if title else ""

    @staticmethod
    def _rule_generate(user_input: str) -> str:
        """规则生成：提取核心意图关键词

        策略：
        1. 去掉无意义前缀（重复字符、帮我、请、麻烦等）
        2. 去掉文件路径，保留动作+对象
        3. 去掉自我介绍的冗余部分，保留角色关键词
        4. 超长文本提取前半段核心内容
        """
        import re

        text = user_input.strip()
        if not text:
            return "新对话"

        # 去掉开头的无意义重复字符（如 "aaaaaaa "、"......"）
        text = re.sub(r'^[a-zA-Z]{4,}\s*', '', text)
        text = re.sub(r'^[.。…·~～!！?？]{3,}\s*', '', text)
        text = text.strip()
        if not text:
            return "新对话"

        # 去掉常见前缀
        for prefix in ("帮我", "请帮我", "请", "帮忙", "麻烦", "我想", "我要", "能不能帮我"):
            if text.startswith(prefix):
                text = text[len(prefix):]
                break
        text = text.strip()

        # 替换文件路径为文件名（/tmp/test_sales.csv → test_sales.csv）
        def _replace_path(m):
            path = m.group(0)
            # 提取文件名
            parts = path.rstrip('/').split('/')
            filename = parts[-1] if parts else path
            # 去掉扩展名
            name_no_ext = re.sub(r'\.[a-zA-Z0-9]{1,5}$', '', filename)
            return name_no_ext if name_no_ext else filename

        text = re.sub(r'[/\\][\w./\\-]+', _replace_path, text)
        text = text.strip()

        # 自我介绍场景：提取角色关键词
        if text.startswith("我是") or text.startswith("是"):
            intro = text[2:] if text.startswith("我是") else text[1:]
            for sep in ("，", ",", "。", "；"):
                if sep in intro:
                    intro = intro[:intro.index(sep)]
                    break
            intro = intro.replace("的", "")
            if len(intro) <= 20:
                return intro.strip() or text[:20]

        # 截断到合理长度
        if len(text) > 20:
            # 尝试在标点处截断
            for i in range(20, 10, -1):
                if text[i] in "，,。；、 ":
                    return text[:i]
            return text[:20] + "..."

        return text or "新对话"

    @staticmethod
    def _record_span(
        thread_id: str, title: str, duration_ms: float,
        method: str = "rule", user_input: str = "",
    ) -> None:
        """记录 title_generation span（入口阶段）"""
        try:
            from src.middleware.tracing import tracing_middleware
            tracing_middleware._add_to_thread(
                thread_id, "title_generation", "title_generation", duration_ms,
                {"title": title, "method": method, "phase": "entry"},
                input_data={
                    "trigger": "首次对话",
                    "user_input": user_input[:200],
                },
                output_data={
                    "title": title,
                    "method": method,
                    "async_llm_optimize": "后台执行中" if method == "rule" else "已完成",
                },
                detail=f"生成会话标题「{title}」（{method}）",
                status="success",
            )
        except Exception as e:
            logger.debug("[TitleMiddleware] record span failed: %s", e)

    def _persist_title(self, thread_id: str, tenant_id: str, user_id: str, title: str) -> bool:
        """将标题持久化到 ai_conversation 表

        Returns:
            True 如果成功更新或记录已存在，False 如果记录不存在（触发重试）
        """
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
                    # 允许覆盖：空、默认值、规则标题（以 ... 结尾或长度 ≤ 20）
                    # LLM 标题总是可以覆盖规则标题
                    if (not existing_title
                            or existing_title in ('', '新对话', '对话')
                            or existing_title.endswith('...')
                            or len(existing_title) <= 20):
                        cur.execute(
                            "UPDATE ai_conversation SET title=%s, updated_at=%s WHERE id=%s",
                            (title, now, conv_id))
                        logger.info("[TitleMiddleware] persisted: conv=%s title='%s'", conv_id, title)
                    return True
                else:
                    # conversation 不存在（TraceWriter 尚未创建），返回 False 触发重试
                    logger.debug("[TitleMiddleware] conv not found: tenant=%s thread=%s", tid, thread_id)
                    return False

        except Exception as e:
            logger.warning("[TitleMiddleware] persist failed: thread=%s tenant=%s error=%s", thread_id, tenant_id, e)
            return False
