"""Tracing 中间件 — 记录完整执行链路的每个步骤

对齐 index.html 的 Trace 详情格式，完整链路：
1. context_build       — before_agent 阶段，消息预处理
2. memory_retrieval    — before_agent 阶段，记忆检索注入
3. intent_analysis     — before_model 首次调用前，意图分析
4. llm_call            — 首次 LLM 调用（规划）
5. hierarchical_search — 检索阶段（skill / resource / memory），含 vector_search + rerank 子步骤
6. llm_call Iter N     — 迭代 LLM 调用，标注 tool_call 或 final
7. tool:xxx            — 工具执行
8. memory_extract      — after_agent 阶段，记忆提取
"""
from __future__ import annotations

import logging
import time
from typing import Any

from langchain_core.messages import AIMessage, ToolMessage
from langchain.agents.middleware.types import AgentMiddleware, AgentState
from langgraph.config import get_config
from langgraph.prebuilt.tool_node import ToolCallRequest
from langgraph.runtime import Runtime
from langgraph.types import Command

logger = logging.getLogger(__name__)


class TracingMiddleware(AgentMiddleware):
    """完整执行链路追踪 — 对齐 index.html 的 Trace 详情格式

    链路节点与 index.html 一一对应：
    - context_build: 上下文构建（消息数、token 估算）
    - memory_retrieval: 记忆检索（维度、命中数、耗时）
    - intent_analysis: 意图分析（任务类型、匹配技能）
    - llm_call: LLM 调用（含 token 消耗、是否 final）
    - hierarchical_search: 分层检索（skill/resource/memory），含 vector_search + rerank 子步骤
    - tool:xxx: 工具执行（输入、输出、耗时）
    - memory_extract: 记忆提取（提取维度、条目数）
    """

    def __init__(self) -> None:
        super().__init__()
        self._iter_count: dict[str, int] = {}
        self._iter_start: dict[str, float] = {}
        self._spans: dict[str, list[dict]] = {}  # thread_id → spans
        self._memory_result: dict[str, Any] = {}  # thread_id → memory retrieval result
        self._intent_result: dict[str, dict] = {}  # thread_id → intent analysis result

    def _tid(self) -> str:
        try:
            return get_config().get("configurable", {}).get("thread_id", "default")
        except Exception:
            return "default"

    def _add(self, span_type: str, name: str, duration_ms: float = 0,
             metadata: dict | None = None, children: list | None = None) -> None:
        tid = self._tid()
        self._spans.setdefault(tid, []).append({
            "type": span_type,
            "name": name,
            "timestamp": time.time(),
            "duration_ms": round(duration_ms, 1),
            "metadata": metadata or {},
            "children": children or [],
        })

    def get_spans(self, thread_id: str) -> list[dict]:
        return self._spans.get(thread_id, [])

    def clear(self, thread_id: str) -> None:
        self._spans.pop(thread_id, None)
        self._iter_count.pop(thread_id, None)
        self._memory_result.pop(thread_id, None)
        self._intent_result.pop(thread_id, None)

    # ── 外部注入接口（供 MemoryMiddleware / SkillExecutor 等调用） ──

    def record_memory_retrieval(
        self, duration_ms: float, query_used: str = "",
        dimensions: list[str] | None = None, hit_count: int = 0,
        items: list[dict] | None = None,
    ) -> None:
        """记录 memory_retrieval span — 由 MemoryMiddleware 调用"""
        self._add("memory_retrieval", "memory_retrieval", duration_ms, {
            "query_used": query_used[:200],
            "dimensions": dimensions or [],
            "hit_count": hit_count,
            "items_preview": [
                {"dimension": it.get("dimension", ""), "content": it.get("content", "")[:100]}
                for it in (items or [])[:5]
            ],
        })

    def record_intent_analysis(
        self, duration_ms: float, task_type: str = "",
        matched_skills: list[str] | None = None,
        confidence: float = 0.0, raw_intent: str = "",
    ) -> None:
        """记录 intent_analysis span — 由意图分析逻辑调用"""
        self._add("intent_analysis", "intent_analysis", duration_ms, {
            "task_type": task_type,
            "matched_skills": matched_skills or [],
            "confidence": round(confidence, 3),
            "raw_intent": raw_intent[:200],
        })

    def record_hierarchical_search(
        self, search_type: str, duration_ms: float,
        hit_count: int = 0, children: list[dict] | None = None,
    ) -> None:
        """记录 hierarchical_search span — 由检索逻辑调用

        search_type: "skill" / "resource" / "memory"
        children: vector_search / rerank 子步骤列表
        """
        child_spans = []
        for child in (children or []):
            child_spans.append({
                "type": child.get("type", "vector_search"),
                "name": child.get("name", "vector_search"),
                "duration_ms": round(child.get("duration_ms", 0), 1),
                "metadata": child.get("metadata", {}),
            })
        self._add(
            "hierarchical_search",
            f"hierarchical_search {search_type}",
            duration_ms,
            {"search_type": search_type, "hit_count": hit_count},
            children=child_spans,
        )

    def record_memory_extract(
        self, duration_ms: float = 0,
        extracted_count: int = 0, dimensions: list[str] | None = None,
    ) -> None:
        """记录 memory_extract span — 由 MemoryMiddleware.aafter_agent 调用"""
        self._add("memory_extract", "memory_extract", duration_ms, {
            "extracted_count": extracted_count,
            "dimensions": dimensions or [],
        })

    # ── before_agent: context_build ──

    def before_agent(self, state: AgentState, runtime: Runtime) -> dict[str, Any] | None:
        tid = self._tid()
        self._iter_count[tid] = 0
        start = time.monotonic()

        messages = state.get("messages", [])
        msg_count = len(messages)
        token_est = sum(len(str(getattr(m, "content", ""))) // 2 for m in messages)

        dur = (time.monotonic() - start) * 1000
        self._add("context_build", "context_build", dur, {
            "message_count": msg_count,
            "estimated_tokens": token_est,
        })
        return None

    # ── before_model: iter 计数 + 首次触发 intent_analysis ──

    def before_model(self, state: AgentState, runtime: Runtime) -> dict[str, Any] | None:
        tid = self._tid()
        self._iter_count[tid] = self._iter_count.get(tid, 0) + 1
        self._iter_start[tid] = time.monotonic()

        iter_num = self._iter_count[tid]

        # 首次 before_model 时，如果还没有 intent_analysis span，
        # 生成一个基于规则的 intent_analysis（LLM 驱动的由外部注入）
        if iter_num == 1 and tid not in self._intent_result:
            self._rule_based_intent_analysis(state)

        return None

    def _rule_based_intent_analysis(self, state: AgentState) -> None:
        """基于规则的意图分析 — 作为 LLM 意图分析的 fallback"""
        tid = self._tid()
        start = time.monotonic()

        messages = state.get("messages", [])
        current_query = ""
        for msg in reversed(messages):
            if getattr(msg, "type", "") == "human":
                content = getattr(msg, "content", "")
                if isinstance(content, str):
                    current_query = content
                    break

        # 简单规则分类
        task_type = "对话型"
        if any(kw in current_query for kw in ["帮我", "创建", "生成", "写", "部署", "执行", "迁移", "优化"]):
            task_type = "操作型"
        elif any(kw in current_query for kw in ["查", "分析", "看看", "是什么", "怎么", "多少"]):
            task_type = "信息型"

        dur = (time.monotonic() - start) * 1000
        self._intent_result[tid] = {"task_type": task_type}
        self._add("intent_analysis", "intent_analysis", dur, {
            "task_type": task_type,
            "matched_skills": [],
            "confidence": 0.6,
            "raw_intent": current_query[:200],
            "source": "rule_based",
        })

    # ── after_model: 不再记录 llm_call span（由 server.py on_chat_model_start/end 统一记录） ──

    def after_model(self, state: AgentState, runtime: Runtime) -> dict[str, Any] | None:
        return None

    # ── wrap_tool_call: tool 执行 ──

    def wrap_tool_call(self, request: ToolCallRequest, handler) -> ToolMessage | Command:
        name = request.tool_call.get("name", "unknown")
        args = str(request.tool_call.get("args", {}))[:200]
        start = time.monotonic()
        try:
            result = handler(request)
            dur = (time.monotonic() - start) * 1000
            output = str(getattr(result, "content", ""))[:200]
            status = getattr(result, "status", "success")
            self._add("tool_call", f"tool:{name}", dur, {
                "input": args, "output": output, "status": status,
            })
            return result
        except Exception as exc:
            dur = (time.monotonic() - start) * 1000
            self._add("tool_call", f"tool:{name}", dur, {
                "input": args, "error": str(exc)[:200], "status": "error",
            })
            raise

    async def awrap_tool_call(self, request: ToolCallRequest, handler) -> ToolMessage | Command:
        name = request.tool_call.get("name", "unknown")
        args = str(request.tool_call.get("args", {}))[:200]
        start = time.monotonic()
        try:
            result = await handler(request)
            dur = (time.monotonic() - start) * 1000
            output = str(getattr(result, "content", ""))[:200]
            status = getattr(result, "status", "success")
            self._add("tool_call", f"tool:{name}", dur, {
                "input": args, "output": output, "status": status,
            })
            return result
        except Exception as exc:
            dur = (time.monotonic() - start) * 1000
            self._add("tool_call", f"tool:{name}", dur, {
                "input": args, "error": str(exc)[:200], "status": "error",
            })
            raise

    # ── after_agent: 不再直接记录 memory_extract，由 MemoryMiddleware 通过 record_memory_extract 注入 ──

    def after_agent(self, state: AgentState, runtime: Runtime) -> dict[str, Any] | None:
        # memory_extract 由 MemoryMiddleware 通过 record_memory_extract() 主动调用
        # 这里作为 fallback，如果没有外部注入则补一个空 span
        tid = self._tid()
        spans = self._spans.get(tid, [])
        has_memory_extract = any(s["type"] == "memory_extract" for s in spans)
        if not has_memory_extract:
            self._add("memory_extract", "memory_extract", 0, {})
        return None


# 全局单例
tracing_middleware = TracingMiddleware()
