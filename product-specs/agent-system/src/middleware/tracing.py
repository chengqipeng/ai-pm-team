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
        except Exception as e:
            logger.debug("TracingMiddleware get_config failed: %s", e)
            return "default"

    # ── 步骤定义：对齐检索链路详情的 PipelineNode 格式 ──
    # 每个步骤有固定编号、中文名、英文名
    STEP_DEFINITIONS: dict[str, dict] = {
        "content_review":       {"step": 1, "name": "内容审查",       "name_en": "content_review_input"},
        "query_rewrite":        {"step": 2, "name": "查询改写",       "name_en": "query_rewrite"},
        "user_input":           {"step": 3, "name": "用户输入",       "name_en": "user_input"},
        "context_build":        {"step": 4, "name": "上下文构建",     "name_en": "context_build"},
        "memory_retrieval":     {"step": 5, "name": "记忆检索",       "name_en": "memory_retrieval"},
        "intent_analysis":      {"step": 6, "name": "意图分析",       "name_en": "intent_analysis"},
        "llm_input":            {"step": 7, "name": "LLM 输入准备",   "name_en": "llm_input"},
        "llm_call":             {"step": 8, "name": "模型推理",       "name_en": "llm_call"},
        "tool_call":            {"step": 9, "name": "工具调用",       "name_en": "tool_call"},
        "hierarchical_search":  {"step": 10, "name": "分层检索",      "name_en": "hierarchical_search"},
        "memory_extract":       {"step": 11, "name": "记忆提取",      "name_en": "memory_extract"},
    }

    def _add(self, span_type: str, name: str, duration_ms: float = 0,
             metadata: dict | None = None, children: list | None = None,
             input_data: dict | None = None, output_data: dict | None = None,
             detail: str = "") -> None:
        tid = self._tid()
        step_def = self.STEP_DEFINITIONS.get(span_type, {})
        self._spans.setdefault(tid, []).append({
            "type": span_type,
            "name": name,
            "step": step_def.get("step", 0),
            "step_name": step_def.get("name", name),
            "step_name_en": step_def.get("name_en", span_type),
            "timestamp": time.time(),
            "duration_ms": round(duration_ms, 1),
            "status": "success",
            "input_data": input_data or {},
            "output_data": output_data or {},
            "detail": detail,
            "metadata": metadata or {},
            "children": children or [],
        })

    def _add_to_thread(
        self, thread_id: str, span_type: str, name: str,
        duration_ms: float = 0, metadata: dict | None = None,
        children: list | None = None,
        input_data: dict | None = None, output_data: dict | None = None,
        detail: str = "",
    ) -> None:
        """显式指定 thread_id 写入 span

        用于入口层（如 QueryRewriter）调用，此时没有 LangGraph runtime context。
        """
        step_def = self.STEP_DEFINITIONS.get(span_type, {})
        self._spans.setdefault(thread_id, []).append({
            "type": span_type,
            "name": name,
            "step": step_def.get("step", 0),
            "step_name": step_def.get("name", name),
            "step_name_en": step_def.get("name_en", span_type),
            "timestamp": time.time(),
            "duration_ms": round(duration_ms, 1),
            "status": "success",
            "input_data": input_data or {},
            "output_data": output_data or {},
            "detail": detail,
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

    # ── 外部注入接口（供 QueryRewriter / MemoryMiddleware / SkillExecutor 等调用） ──

    def record_query_rewrite(
        self, original_query: str = "", rewritten_query: str = "",
        changed: bool = False, duration_ms: float = 0,
        source: str = "entry",
    ) -> None:
        """记录 query_rewrite span — 由入口层 QueryRewriter 主动调用

        注意：这里只记录 span 结果（input/output/duration），不会捕获 LLM 调用的
        astream_events 事件。QueryRewriter 的 LLM 调用用 callbacks=[] 隔离。

        Args:
            original_query: 用户原始输入
            rewritten_query: 改写后的查询
            changed: 是否发生改写（单轮或无变化时为 False）
            duration_ms: 改写耗时
            source: 调用方标识（entry=入口层，fallback=中间件兜底）
        """
        self._add("query_rewrite", "query_rewrite", duration_ms,
            metadata={
                "original_query": original_query[:500],
                "rewritten_query": rewritten_query[:500],
                "changed": changed,
                "source": source,
            },
            input_data={
                "original_query": original_query[:500],
                "source": source,
            },
            output_data={
                "rewritten_query": rewritten_query[:500],
                "changed": changed,
            },
            detail=(
                f"{'改写生效' if changed else '无需改写'}: "
                f"「{original_query[:60]}」→「{rewritten_query[:60]}」"
            ) if changed else f"单轮对话，无需改写: 「{original_query[:80]}」",
        )

    def record_content_review(
        self, direction: str, passed: bool,
        blocked_keywords: list[str] | None = None,
        blocked_reason: str = "", duration_ms: float = 0,
    ) -> None:
        """记录 content_review span — 由入口层毒性检测调用

        Args:
            direction: "input" / "output"
            passed: 是否通过审查
            blocked_keywords: 命中的关键词
            blocked_reason: 拦截原因
            duration_ms: 审查耗时
        """
        self._add("content_review", f"content_review_{direction}", duration_ms,
            metadata={
                "direction": direction,
                "passed": passed,
                "blocked_keywords": blocked_keywords or [],
                "blocked_reason": blocked_reason[:200],
            },
            input_data={
                "direction": direction,
                "review_type": "toxicity + keyword",
            },
            output_data={
                "passed": passed,
                "blocked_keywords": blocked_keywords or [],
                "blocked_reason": blocked_reason[:200] if not passed else "",
            },
            detail=(
                f"{'输入' if direction == 'input' else '输出'}审查 → "
                f"{'✅ 通过' if passed else '❌ 拦截: ' + (blocked_reason[:80] or '命中关键词')}"
            ),
        )

    def record_memory_retrieval(
        self, duration_ms: float, query_used: str = "",
        dimensions: list[str] | None = None, hit_count: int = 0,
        items: list[dict] | None = None,
    ) -> None:
        """记录 memory_retrieval span — 由 MemoryMiddleware 调用"""
        items_preview = [
            {"dimension": it.get("dimension", ""), "content": it.get("content", "")[:200]}
            for it in (items or [])[:10]
        ]
        self._add("memory_retrieval", "memory_retrieval", duration_ms,
            metadata={
                "query_used": query_used[:500],
                "dimensions": dimensions or [],
                "hit_count": hit_count,
                "items_preview": items_preview,
            },
            input_data={
                "query": query_used[:500],
                "dimensions": dimensions or [],
            },
            output_data={
                "hit_count": hit_count,
                "items_preview": items_preview,
            },
            detail=(
                f"查询: 「{query_used[:60]}」| "
                f"维度: {', '.join(dimensions or ['all'])} | "
                f"命中 {hit_count} 条结果"
            ),
        )

    def record_intent_analysis(
        self, duration_ms: float, task_type: str = "",
        matched_skills: list[str] | None = None,
        confidence: float = 0.0, raw_intent: str = "",
    ) -> None:
        """记录 intent_analysis span — 由意图分析逻辑调用"""
        self._add("intent_analysis", "intent_analysis", duration_ms,
            metadata={
                "task_type": task_type,
                "matched_skills": matched_skills or [],
                "confidence": round(confidence, 3),
                "raw_intent": raw_intent[:200],
            },
            input_data={
                "raw_intent": raw_intent[:500],
            },
            output_data={
                "task_type": task_type,
                "matched_skills": matched_skills or [],
                "confidence": round(confidence, 3),
            },
            detail=(
                f"任务类型: {task_type} | "
                f"匹配技能: {', '.join(matched_skills or []) or '无'} | "
                f"置信度: {confidence:.1%}"
            ),
        )

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
            metadata={"search_type": search_type, "hit_count": hit_count},
            children=child_spans,
            input_data={
                "search_type": search_type,
                "sub_steps": [c.get("name", "vector_search") for c in child_spans],
            },
            output_data={
                "hit_count": hit_count,
                "children_count": len(child_spans),
            },
            detail=(
                f"分层检索({search_type}): "
                f"命中 {hit_count} 条 | "
                f"子步骤: {', '.join(c.get('name', '') for c in child_spans) or '无'}"
            ),
        )

    def record_memory_extract(
        self, duration_ms: float = 0,
        extracted_count: int = 0, dimensions: list[str] | None = None,
    ) -> None:
        """记录 memory_extract span — 由 MemoryMiddleware.aafter_agent 调用"""
        self._add("memory_extract", "memory_extract", duration_ms,
            metadata={
                "extracted_count": extracted_count,
                "dimensions": dimensions or [],
            },
            input_data={
                "agent_output": "(from agent response)",
            },
            output_data={
                "extracted_count": extracted_count,
                "dimensions": dimensions or [],
            },
            detail=(
                f"从 Agent 回复中提取记忆: "
                f"{extracted_count} 条 | "
                f"维度: {', '.join(dimensions or []) or '无'}"
            ),
        )

    # ── before_agent: context_build ──

    def before_agent(self, state: AgentState, runtime: Runtime) -> dict[str, Any] | None:
        tid = self._tid()
        self._iter_count[tid] = 0
        start = time.monotonic()

        messages = state.get("messages", [])
        msg_count = len(messages)
        token_est = sum(len(str(getattr(m, "content", ""))) // 2 for m in messages)

        # 记录详细的消息列表摘要（用于排查）
        msg_summary = []
        for i, m in enumerate(messages[-10:]):  # 最近 10 条
            m_type = getattr(m, "type", "unknown")
            m_content = getattr(m, "content", "")
            if isinstance(m_content, str):
                preview = m_content[:150]
            else:
                preview = str(m_content)[:150]
            msg_summary.append({"index": len(messages) - 10 + i, "type": m_type, "preview": preview})

        dur = (time.monotonic() - start) * 1000
        self._add("context_build", "context_build", dur,
            metadata={
                "message_count": msg_count,
                "estimated_tokens": token_est,
                "recent_messages": msg_summary,
            },
            input_data={
                "message_count": msg_count,
                "history_window": min(10, msg_count),
            },
            output_data={
                "estimated_tokens": token_est,
                "message_types": list({getattr(m, "type", "unknown") for m in messages}),
            },
            detail=(
                f"构建 LLM 上下文: {msg_count} 条消息, "
                f"预估 {token_est} tokens"
            ),
        )
        return None

    # ── before_model: iter 计数 + 首次触发 intent_analysis + 记录 LLM 输入 ──

    def before_model(self, state: AgentState, runtime: Runtime) -> dict[str, Any] | None:
        tid = self._tid()
        self._iter_count[tid] = self._iter_count.get(tid, 0) + 1
        self._iter_start[tid] = time.monotonic()

        iter_num = self._iter_count[tid]

        # 记录每轮 LLM 调用的输入消息摘要（关键排查信息）
        messages = state.get("messages", [])
        llm_input_summary = []
        for m in messages[-15:]:  # 最近 15 条（含 system/tool messages）
            m_type = getattr(m, "type", "unknown")
            m_content = getattr(m, "content", "")
            if isinstance(m_content, str):
                preview = m_content[:300]
            else:
                preview = str(m_content)[:300]
            tool_calls = getattr(m, "tool_calls", None)
            entry = {"type": m_type, "content_preview": preview}
            if tool_calls:
                entry["tool_calls"] = [tc.get("name", "") for tc in tool_calls[:5]]
            llm_input_summary.append(entry)

        self._add("llm_input", f"llm_input_iter_{iter_num}", 0,
            metadata={
                "iteration": iter_num,
                "total_messages": len(messages),
                "messages_to_llm": llm_input_summary,
            },
            input_data={
                "iteration": iter_num,
                "total_messages": len(messages),
            },
            output_data={
                "messages_to_llm_count": len(llm_input_summary),
                "last_message_type": llm_input_summary[-1]["type"] if llm_input_summary else "",
            },
            detail=(
                f"第 {iter_num} 轮 LLM 调用准备: "
                f"共 {len(messages)} 条消息送入模型"
            ),
        )

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
        self._add("intent_analysis", "intent_analysis", dur,
            metadata={
                "task_type": task_type,
                "matched_skills": [],
                "confidence": 0.6,
                "raw_intent": current_query[:200],
                "source": "rule_based",
            },
            input_data={
                "raw_intent": current_query[:500],
                "source": "rule_based",
            },
            output_data={
                "task_type": task_type,
                "matched_skills": [],
                "confidence": 0.6,
            },
            detail=(
                f"规则意图分析: 任务类型={task_type} | "
                f"输入: 「{current_query[:60]}」"
            ),
        )

    # ── after_model: 不再记录 llm_call span（由 server.py on_chat_model_start/end 统一记录） ──

    def after_model(self, state: AgentState, runtime: Runtime) -> dict[str, Any] | None:
        return None

    # ── wrap_tool_call: tool 执行 ──

    def wrap_tool_call(self, request: ToolCallRequest, handler) -> ToolMessage | Command:
        name = request.tool_call.get("name", "unknown")
        args = str(request.tool_call.get("args", {}))[:500]
        start = time.monotonic()
        try:
            result = handler(request)
            dur = (time.monotonic() - start) * 1000
            output = str(getattr(result, "content", ""))[:500]
            status = getattr(result, "status", "success")
            self._add("tool_call", f"tool:{name}", dur,
                metadata={
                    "tool_name": name,
                    "input": args,
                    "output": output,
                    "status": status,
                },
                input_data={
                    "tool_name": name,
                    "arguments": args,
                },
                output_data={
                    "result": output,
                    "status": status,
                },
                detail=f"调用工具 {name}: {status}",
            )
            return result
        except Exception as exc:
            dur = (time.monotonic() - start) * 1000
            self._add("tool_call", f"tool:{name}", dur,
                metadata={
                    "tool_name": name,
                    "input": args,
                    "error": str(exc)[:500],
                    "status": "error",
                },
                input_data={
                    "tool_name": name,
                    "arguments": args,
                },
                output_data={
                    "error": str(exc)[:500],
                    "status": "error",
                },
                detail=f"工具 {name} 执行失败: {str(exc)[:100]}",
            )
            raise

    async def awrap_tool_call(self, request: ToolCallRequest, handler) -> ToolMessage | Command:
        name = request.tool_call.get("name", "unknown")
        args = str(request.tool_call.get("args", {}))[:500]
        start = time.monotonic()
        try:
            result = await handler(request)
            dur = (time.monotonic() - start) * 1000
            output = str(getattr(result, "content", ""))[:500]
            status = getattr(result, "status", "success")
            self._add("tool_call", f"tool:{name}", dur,
                metadata={
                    "tool_name": name,
                    "input": args,
                    "output": output,
                    "status": status,
                },
                input_data={
                    "tool_name": name,
                    "arguments": args,
                },
                output_data={
                    "result": output,
                    "status": status,
                },
                detail=f"调用工具 {name}: {status}",
            )
            return result
        except Exception as exc:
            dur = (time.monotonic() - start) * 1000
            self._add("tool_call", f"tool:{name}", dur,
                metadata={
                    "tool_name": name,
                    "input": args,
                    "error": str(exc)[:500],
                    "status": "error",
                },
                input_data={
                    "tool_name": name,
                    "arguments": args,
                },
                output_data={
                    "error": str(exc)[:500],
                    "status": "error",
                },
                detail=f"工具 {name} 执行失败: {str(exc)[:100]}",
            )
            raise

    # ── after_agent: 不再直接记录 memory_extract，由 MemoryMiddleware 通过 record_memory_extract 注入 ──

    def after_agent(self, state: AgentState, runtime: Runtime) -> dict[str, Any] | None:
        # memory_extract 由 MemoryMiddleware 通过 record_memory_extract() 主动调用
        # 这里作为 fallback，如果没有外部注入则补一个空 span
        tid = self._tid()
        spans = self._spans.get(tid, [])
        has_memory_extract = any(s["type"] == "memory_extract" for s in spans)
        if not has_memory_extract:
            self._add("memory_extract", "memory_extract", 0,
                metadata={},
                input_data={"agent_output": "(skipped)"},
                output_data={"extracted_count": 0},
                detail="记忆提取: 跳过（无需提取）",
            )
        return None


# 全局单例
tracing_middleware = TracingMiddleware()
