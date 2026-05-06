"""记忆中间件 — before_agent 检索注入，after_agent 异步提取更新"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage, AIMessage
from langchain.agents.middleware.types import AgentMiddleware, AgentState
from langgraph.config import get_config
from langgraph.runtime import Runtime

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════
# 反思触发的信号检测 + 冷却
# ═══════════════════════════════════════════════════════════

# 失败信号：AI 回复中的错误关键词
_AI_ERROR_PATTERNS = (
    "查询失败", "调用失败", "执行失败", "报错",
    "未找到", "查不到", "没有找到", "返回为空", "空结果",
    "无法", "error", "failed", "not found", "exception",
)

# 用户纠正强信号：消息前 30 字包含这些关键词
_STRONG_CORRECTION_KEYWORDS = (
    "不对", "错了", "搞错了", "说错了",
    "改一下", "更正", "修正一下",
    "你错了", "你记错了", "不是这样",
)

# 用户纠正中信号：正则模式
_NEGATION_PATTERNS = (
    r"不是.{1,20}[,，]\s*是",
    r"不应该.{1,20}[,，]\s*应该",
)

# 冷却
_REFLECT_COOLDOWN = {
    "failure": 60.0,      # 失败反思冷却 60s
    "correction": 30.0,   # 纠正反思冷却 30s
}
_last_reflect_at: dict[str, float] = {}


def _can_trigger_reflect(reflect_type: str, thread_id: str) -> bool:
    """冷却检查"""
    key = f"{reflect_type}:{thread_id}"
    now = time.time()
    last = _last_reflect_at.get(key, 0.0)
    cooldown = _REFLECT_COOLDOWN.get(reflect_type, 60.0)
    if now - last < cooldown:
        return False
    _last_reflect_at[key] = now
    return True


def _detect_ai_failure(ai_content: str) -> bool:
    """检测 AI 回复是否包含错误信号"""
    if not ai_content or not isinstance(ai_content, str):
        return False
    if len(ai_content) > 500:
        return False  # 长回复通常不是报错
    lower = ai_content.lower()
    return any(kw in lower for kw in _AI_ERROR_PATTERNS)


def _detect_tool_failure(messages: list) -> tuple[bool, str]:
    """检测最近是否有 Tool 调用失败"""
    for msg in messages[-10:]:
        if getattr(msg, "type", "") == "tool":
            if getattr(msg, "status", "") == "error":
                content = getattr(msg, "content", "")
                return True, str(content)[:200]
    return False, ""


def _detect_correction_signal(text: str) -> tuple[str, str]:
    """检测用户纠正信号，返回 (level, matched_text)"""
    if not text or not isinstance(text, str):
        return "", ""
    head = text[:30]
    # 强信号
    for kw in _STRONG_CORRECTION_KEYWORDS:
        if kw in head:
            return "strong", text[:300]
    # 中信号
    for pattern in _NEGATION_PATTERNS:
        if re.search(pattern, text[:100]):
            return "medium", text[:300]
    return "", ""


class MemoryDimension(str, Enum):
    USER_PROFILE = "user_profile"
    CUSTOMER_CONTEXT = "customer_context"
    TASK_HISTORY = "task_history"
    DOMAIN_KNOWLEDGE = "domain_knowledge"


@dataclass
class MemoryItem:
    dimension: MemoryDimension
    content: str
    confidence: float = 1.0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class MemoryRetrievalResult:
    items: list[MemoryItem] = field(default_factory=list)
    query_used: str = ""


@dataclass
class MemoryExtractionResult:
    items: list[MemoryItem] = field(default_factory=list)
    source_thread_id: str = ""


class MemoryEngine(ABC):
    """记忆引擎抽象接口

    所有方法均需 tenant_id 参数实现多租户隔离。
    tenant_id 为空时使用 "default" 作为默认租户。
    """
    @abstractmethod
    async def rewrite_query(self, messages: list, current_query: str,
                            tenant_id: str | None = None) -> str: ...
    @abstractmethod
    async def retrieve(self, query: str, dimensions: list[MemoryDimension] | None = None,
                       tenant_id: str | None = None, user_id: str | None = None,
                       top_k: int = 5) -> MemoryRetrievalResult: ...
    @abstractmethod
    async def extract_and_update(self, messages: list, thread_id: str,
                                 tenant_id: str | None = None,
                                 user_id: str | None = None) -> MemoryExtractionResult: ...


class NoopMemoryEngine(MemoryEngine):
    """空实现占位"""
    async def rewrite_query(self, messages, current_query, tenant_id=None): return current_query
    async def retrieve(self, query, dimensions=None, tenant_id=None, user_id=None, top_k=5):
        return MemoryRetrievalResult(query_used=query)
    async def extract_and_update(self, messages, thread_id, tenant_id=None, user_id=None):
        return MemoryExtractionResult(source_thread_id=thread_id)


class MemoryMiddleware(AgentMiddleware):
    """记忆中间件"""

    def __init__(self, engine: MemoryEngine | None = None,
                 dimensions: list[MemoryDimension] | None = None, enabled: bool = True):
        super().__init__()
        self._engine = engine or NoopMemoryEngine()
        self._dimensions = dimensions or list(MemoryDimension)
        self._enabled = enabled

    @property
    def engine(self) -> MemoryEngine:
        return self._engine

    @engine.setter
    def engine(self, value: MemoryEngine) -> None:
        self._engine = value

    async def abefore_agent(self, state: AgentState, runtime: Runtime) -> dict[str, Any] | None:
        """记忆检索注入 — 同时向 TracingMiddleware 记录 memory_retrieval span"""
        if not self._enabled:
            return None
        messages = state.get("messages", [])
        if not messages:
            return None

        current_query = self._get_current_query(messages)
        if not current_query:
            return None

        configurable = get_config().get("configurable", {})
        tenant_id = configurable.get("tenant_id", "default")
        user_id = configurable.get("user_id")

        import time as _time
        start = _time.monotonic()

        try:
            query = (await self._engine.rewrite_query(messages, current_query, tenant_id)
                     if self._has_context(messages) else current_query)
            result = await self._engine.retrieve(query, self._dimensions, tenant_id, user_id)

            dur = (_time.monotonic() - start) * 1000

            # 向 TracingMiddleware 记录 memory_retrieval span
            self._record_retrieval_span(dur, query, result)

            text = self._format_memory(result)

            # Agent Rules 注入 — 让 Agent 从第一轮就知道行为准则
            rules_text = ""
            if hasattr(self._engine, "get_agent_rules_text") and user_id:
                try:
                    rules_text = self._engine.get_agent_rules_text(user_id)
                except Exception:
                    pass

            inject_messages = []
            if rules_text:
                inject_messages.append(SystemMessage(content=rules_text))
            if text:
                inject_messages.append(SystemMessage(content=text))

            if inject_messages:
                return {"messages": inject_messages}
        except Exception as e:
            dur = (_time.monotonic() - start) * 1000
            self._record_retrieval_span(dur, current_query, None, error=str(e))
            logger.error("Memory retrieval failed: %s", e)
        return None

    def _record_retrieval_span(
        self, duration_ms: float, query_used: str,
        result: MemoryRetrievalResult | None, error: str = "",
    ) -> None:
        """向 TracingMiddleware 注入 memory_retrieval span"""
        try:
            from src.middleware.tracing import tracing_middleware
            if error:
                tracing_middleware.record_memory_retrieval(
                    duration_ms=duration_ms, query_used=query_used,
                    dimensions=[d.value for d in self._dimensions],
                    hit_count=0,
                )
            else:
                items = []
                if result and result.items:
                    items = [{"dimension": it.dimension.value, "content": it.content}
                             for it in result.items]
                tracing_middleware.record_memory_retrieval(
                    duration_ms=duration_ms, query_used=query_used,
                    dimensions=[d.value for d in self._dimensions],
                    hit_count=len(result.items) if result else 0,
                    items=items,
                )
        except Exception as e:
            logger.debug("Failed to record memory_retrieval span: %s", e)

    async def aafter_agent(self, state: AgentState, runtime: Runtime) -> dict[str, Any] | None:
        """记忆提取 — 同时向 TracingMiddleware 记录 memory_extract span + 失败/纠正反思触发"""
        if not self._enabled:
            return None
        messages = state.get("messages", [])
        if len(messages) < 2:
            return None
        configurable = get_config().get("configurable", {})
        thread_id = configurable.get("thread_id", "unknown")
        tenant_id = configurable.get("tenant_id", "default")
        user_id = configurable.get("user_id")

        # 1. 异步提取记忆 — 只传最近的用户原始消息（排除 middleware 注入的指令）
        #    取最后 N 条 HumanMessage 作为提取输入
        recent_user_messages = [m for m in messages if isinstance(m, HumanMessage)][-3:]
        if recent_user_messages:
            asyncio.create_task(self._async_extract(recent_user_messages, thread_id, tenant_id, user_id))

        # 2. 按优先级触发"实时"反思（P0 用户纠正 > P1 失败驱动）
        if user_id and hasattr(self._engine, "reflect_on_correction"):
            self._trigger_realtime_reflections(messages, thread_id, user_id)

        return None

    def _trigger_realtime_reflections(self, messages: list, thread_id: str, user_id: str) -> None:
        """按优先级触发用户纠正反思和失败驱动反思（最多触发一种）"""
        # ── P0: 用户纠正反思（强信号优先） ──
        last_user_msg = next(
            (m for m in reversed(messages) if isinstance(m, HumanMessage)), None
        )
        if last_user_msg:
            user_text = last_user_msg.content if isinstance(last_user_msg.content, str) else ""
            level, matched = _detect_correction_signal(user_text)
            if level == "strong" and _can_trigger_reflect("correction", thread_id):
                logger.info("Triggering correction reflection: %s", matched[:80])
                asyncio.create_task(
                    self._safe_reflect_on_correction(matched, user_id)
                )
                return  # 触发了就不再触发失败反思

        # ── P1: 失败驱动反思 ──
        if not hasattr(self._engine, "reflect_on_failure"):
            return

        # 信号 1: AI 回复报错
        failure_desc = ""
        last_ai_msg = next(
            (m for m in reversed(messages) if isinstance(m, AIMessage)), None
        )
        if last_ai_msg:
            ai_content = last_ai_msg.content if isinstance(last_ai_msg.content, str) else ""
            if _detect_ai_failure(ai_content):
                failure_desc = f"ai_error: {ai_content[:200]}"

        # 信号 2: Tool 调用失败
        if not failure_desc:
            tool_failed, tool_err = _detect_tool_failure(messages)
            if tool_failed:
                failure_desc = f"tool_error: {tool_err}"

        if failure_desc and _can_trigger_reflect("failure", thread_id):
            logger.info("Triggering failure reflection: %s", failure_desc[:80])
            asyncio.create_task(
                self._safe_reflect_on_failure(messages, failure_desc, user_id)
            )

    async def _safe_reflect_on_correction(self, text: str, user_id: str):
        """安全包装 reflect_on_correction"""
        try:
            await self._engine.reflect_on_correction(text, user_id)
        except Exception as e:
            logger.warning("Correction reflection failed: %s", e)

    async def _safe_reflect_on_failure(self, messages: list, error: str, user_id: str):
        """安全包装 reflect_on_failure"""
        try:
            await self._engine.reflect_on_failure(messages, error, user_id)
        except Exception as e:
            logger.warning("Failure reflection failed: %s", e)

    def _has_context(self, messages): return sum(1 for m in messages if isinstance(m, HumanMessage)) > 1
    def _get_current_query(self, messages):
        for msg in reversed(messages):
            if isinstance(msg, HumanMessage):
                return msg.content if isinstance(msg.content, str) else str(msg.content)
        return ""

    def _format_memory(self, result: MemoryRetrievalResult) -> str | None:
        """格式化记忆检索结果 — 区分目录节点（L0）和叶子节点（L0）

        目录节点：可通过 memory_read(id, level="L1") 获取结构化概览
        叶子节点：可通过 memory_read(id, level="L2") 获取完整内容
        """
        if not result.items:
            return None
        lines = []
        for item in result.items:
            mem_id = item.metadata.get("id", "")
            category = item.metadata.get("category", "")
            node_type = item.metadata.get("type", "leaf")

            if node_type == "directory":
                # 目录节点：标记 [DIR]，可加载 L1
                lines.append(f"  - [DIR:{mem_id}] [{category}] {item.content}")
            else:
                # 叶子节点：标记 [ID]，可加载 L2（完整内容）
                lines.append(f"  - [ID:{mem_id}] [{category}] {item.content}")

        return (
            "<memory_context>\n"
            "以下是与当前问题相关的记忆摘要（L0）。\n"
            "- [DIR:xxx] 是目录摘要，调用 memory_read(memory_id=xxx, level='L1') 获取结构化概览\n"
            "- [ID:xxx] 是记忆摘要，调用 memory_read(memory_id=xxx, level='L2') 获取完整内容\n\n"
            + "\n".join(lines)
            + "\n</memory_context>"
        )

    async def _async_extract(self, messages, thread_id, tenant_id, user_id):
        import time as _time
        start = _time.monotonic()
        try:
            result = await self._engine.extract_and_update(messages, thread_id, tenant_id, user_id)
            dur = (_time.monotonic() - start) * 1000
            if result.items:
                logger.info("Extracted %d memory items", len(result.items))
            # 向 TracingMiddleware 记录 memory_extract span
            try:
                from src.middleware.tracing import tracing_middleware
                tracing_middleware.record_memory_extract(
                    duration_ms=dur,
                    extracted_count=len(result.items) if result else 0,
                    dimensions=[it.dimension.value for it in result.items] if result else [],
                )
            except Exception:
                pass
        except Exception as e:
            dur = (_time.monotonic() - start) * 1000
            logger.error("Memory extraction failed: %s", e)
            try:
                from src.middleware.tracing import tracing_middleware
                tracing_middleware.record_memory_extract(duration_ms=dur)
            except Exception:
                pass
