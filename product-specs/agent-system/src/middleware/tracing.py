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
        self._active_sub_threads: dict[str, list[str]] = {}  # parent_thread → [sub_thread_ids]

    def register_sub_thread(self, parent_thread_id: str, sub_thread_id: str) -> None:
        """注册子 Agent 的 thread_id，供主 Agent polling 时实时获取子 Agent spans"""
        self._active_sub_threads.setdefault(parent_thread_id, []).append(sub_thread_id)

    def unregister_sub_thread(self, parent_thread_id: str, sub_thread_id: str) -> None:
        """取消注册子 thread"""
        subs = self._active_sub_threads.get(parent_thread_id, [])
        if sub_thread_id in subs:
            subs.remove(sub_thread_id)

    def get_spans_with_sub_threads(self, thread_id: str) -> list[dict]:
        """获取主 thread + 所有活跃子 thread 的 spans（供实时 polling）"""
        all_spans = list(self._spans.get(thread_id, []))
        for sub_tid in self._active_sub_threads.get(thread_id, []):
            sub_spans = self._spans.get(sub_tid, [])
            for sp in sub_spans:
                # 标记来源子 thread，前端可据此分组
                tagged = dict(sp)
                tagged["_sub_thread_id"] = sub_tid
                all_spans.append(tagged)
        return all_spans

    def _tid(self) -> str:
        try:
            return get_config().get("configurable", {}).get("thread_id", "default")
        except Exception as e:
            logger.debug("TracingMiddleware get_config failed: %s", e)
            return "default"

    def record_middleware_execution(
        self, middleware_name: str, phase: str, duration_ms: float,
        has_effect: bool = False, detail: str = "",
        tool_call_id: str = "",
    ) -> None:
        """记录单个中间件的执行 — 由 MiddlewareTracingWrapper 调用

        Args:
            middleware_name: 中间件类名（如 "MemoryMiddleware"）
            phase: 执行阶段 "before_agent" / "after_agent" / "before_model" / "after_model"
            duration_ms: 执行耗时
            has_effect: 是否产生了副作用（修改了 state）
            detail: 额外描述
            tool_call_id: 工具调用 ID（仅 wrap_tool_call 阶段有值，用于前端关联）
        """
        # 根据执行阶段映射到前端 phase 分组
        phase_mapping = {
            "before_agent": "context",    # Agent 开始前 → 上下文准备
            "after_agent": "post",        # Agent 结束后 → 后处理
            "before_model": "reasoning",  # LLM 调用前 → 模型推理（循环内）
            "after_model": "reasoning",   # LLM 返回后 → 模型推理（循环内）
            "wrap_tool_call": "reasoning", # 工具调用时 → 模型推理（循环内）
        }
        display_phase = phase_mapping.get(phase, "context")

        tid = self._tid()
        self._spans.setdefault(tid, []).append({
            "type": "middleware",
            "name": f"mw:{middleware_name}",
            "phase": display_phase,
            "step_name": middleware_name,
            "step_name_en": "middleware",
            "timestamp": time.time(),
            "duration_ms": round(duration_ms, 1),
            "status": "success",
            "input_data": {
                "middleware": middleware_name,
                "phase": phase,
            },
            "output_data": {
                "has_effect": has_effect,
                "duration_ms": round(duration_ms, 1),
            },
            "detail": detail or f"{middleware_name}.{phase} {'→ 已修改状态' if has_effect else '→ 无变更'}",
            "metadata": {
                "middleware_name": middleware_name,
                "phase": phase,
                "has_effect": has_effect,
                "tool_call_id": tool_call_id,
            },
            "children": [],
        })

    # ── 步骤定义：对齐检索链路详情的 PipelineNode 格式 ──
    # 每个步骤有阶段标识、中文名、英文名（编号由前端按到达顺序动态分配）
    STEP_DEFINITIONS: dict[str, dict] = {
        "content_review":       {"phase": "entry",     "name": "内容审查",       "name_en": "content_review"},
        "query_rewrite":        {"phase": "entry",     "name": "查询改写",       "name_en": "query_rewrite"},
        "user_input":           {"phase": "context",   "name": "用户输入",       "name_en": "user_input"},
        "context_build":        {"phase": "context",   "name": "上下文构建",     "name_en": "context_build"},
        "resource_preload":     {"phase": "context",   "name": "知识预加载",     "name_en": "resource_preload"},
        "middleware":           {"phase": "context",   "name": "中间件",         "name_en": "middleware"},
        "title_generation":     {"phase": "entry",     "name": "标题生成",       "name_en": "title_generation"},
        "memory_retrieval":     {"phase": "context",   "name": "记忆检索",       "name_en": "memory_retrieval"},
        "intent_analysis":      {"phase": "reasoning", "name": "意图分析",       "name_en": "intent_analysis"},
        "llm_input":            {"phase": "reasoning", "name": "LLM 输入准备",   "name_en": "llm_input"},
        "llm_call":             {"phase": "reasoning", "name": "模型推理",       "name_en": "llm_call"},
        "tool_call":            {"phase": "reasoning", "name": "工具调用",       "name_en": "tool_call"},
        "skill_execution":      {"phase": "reasoning", "name": "技能执行",       "name_en": "skill_execution"},
        "hierarchical_search":  {"phase": "reasoning", "name": "分层检索",      "name_en": "hierarchical_search"},
        "memory_extract":       {"phase": "post",      "name": "记忆提取",      "name_en": "memory_extract"},
    }

    def _add(self, span_type: str, name: str, duration_ms: float = 0,
             metadata: dict | None = None, children: list | None = None,
             input_data: dict | None = None, output_data: dict | None = None,
             detail: str = "", step_name_override: str = "") -> None:
        tid = self._tid()
        step_def = self.STEP_DEFINITIONS.get(span_type, {})
        self._spans.setdefault(tid, []).append({
            "type": span_type,
            "name": name,
            "phase": step_def.get("phase", ""),
            "step_name": step_name_override or step_def.get("name", name),
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
        detail: str = "", status: str = "success",
    ) -> None:
        """显式指定 thread_id 写入 span

        用于入口层（如 QueryRewriter）调用，此时没有 LangGraph runtime context。
        """
        step_def = self.STEP_DEFINITIONS.get(span_type, {})
        self._spans.setdefault(thread_id, []).append({
            "type": span_type,
            "name": name,
            "phase": step_def.get("phase", ""),
            "step_name": step_def.get("name", name),
            "step_name_en": step_def.get("name_en", span_type),
            "timestamp": time.time(),
            "duration_ms": round(duration_ms, 1),
            "status": status,
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
        source: str = "entry", skipped: bool = False,
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
            skipped: 是否跳过（首轮对话无历史时为 True）
        """
        tid = self._tid()
        step_def = self.STEP_DEFINITIONS.get("query_rewrite", {})
        status = "skipped" if skipped else "success"
        detail = "首轮对话，无需改写" if skipped else (
            f"{'改写生效' if changed else '无需改写'}: "
            f"「{original_query[:60]}」→「{rewritten_query[:60]}」"
        ) if changed else f"单轮对话，无需改写: 「{original_query[:80]}」"

        self._spans.setdefault(tid, []).append({
            "type": "query_rewrite",
            "name": "query_rewrite",
            "phase": step_def.get("phase", ""),
            "step_name": step_def.get("name", "查询改写"),
            "step_name_en": step_def.get("name_en", "query_rewrite"),
            "timestamp": time.time(),
            "duration_ms": round(duration_ms, 1),
            "status": status,
            "input_data": {
                "original_query": original_query[:500],
                "source": source,
            },
            "output_data": {
                "rewritten_query": rewritten_query[:500] if not skipped else "",
                "changed": changed,
                "skipped": skipped,
            },
            "detail": detail,
            "metadata": {
                "original_query": original_query[:500],
                "rewritten_query": rewritten_query[:500] if not skipped else "",
                "changed": changed,
                "source": source,
                "skipped": skipped,
            },
            "children": [],
        })

    def record_content_review(
        self, direction: str, passed: bool,
        blocked_keywords: list[str] | None = None,
        blocked_reason: str = "", duration_ms: float = 0,
        user_input: str = "",
    ) -> None:
        """记录 content_review span — 由入口层毒性检测调用

        Args:
            direction: "input" / "output"
            passed: 是否通过审查
            blocked_keywords: 命中的关键词
            blocked_reason: 拦截原因
            duration_ms: 审查耗时
            user_input: 被审查的文本内容
        """
        input_preview = (user_input[:200] + "...") if len(user_input) > 200 else user_input
        self._add("content_review", f"content_review_{direction}", duration_ms,
            metadata={
                "direction": direction,
                "passed": passed,
                "blocked_keywords": blocked_keywords or [],
                "blocked_reason": blocked_reason[:200],
            },
            input_data={
                "text": input_preview,
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

        # 提取用户当前输入（最后一条 HumanMessage）
        current_query = ""
        history_count = 0
        for m in reversed(messages):
            m_type = getattr(m, "type", "")
            if m_type == "human" and not current_query:
                current_query = getattr(m, "content", "")
                if not isinstance(current_query, str):
                    current_query = str(current_query)
                current_query = current_query[:200]
            elif m_type in ("human", "ai"):
                history_count += 1

        dur = (time.monotonic() - start) * 1000
        self._add("context_build", "context_build", dur,
            metadata={
                "message_count": msg_count,
                "estimated_tokens": token_est,
                "recent_messages": msg_summary,
            },
            input_data={
                "current_query": current_query,
                "history_turns": history_count,
                "total_messages": msg_count,
            },
            output_data={
                "estimated_tokens": token_est,
                "message_types": list({getattr(m, "type", "unknown") for m in messages}),
                "messages_preview": msg_summary[-5:],
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
        tool_call_id = request.tool_call.get("id", "")
        raw_args = request.tool_call.get("args", {})
        args = str(raw_args)[:500]
        start = time.monotonic()

        # 解析 skills_tool / agent_tool 的 skill_name
        skill_name = ""
        if name in ("skills_tool", "agent_tool") and isinstance(raw_args, dict):
            skill_name = str(raw_args.get("skill_name", ""))

        try:
            result = await handler(request)
            dur = (time.monotonic() - start) * 1000
            output = str(getattr(result, "content", ""))[:500]
            status = getattr(result, "status", "success")

            # skills_tool 正常完成：由 SkillExecutor._record_skill_span 记录 skill_execution span
            # 此处不重复记录，避免链路出现两个节点
            if not skill_name:
                self._add("tool_call", f"tool:{name}", dur,
                    metadata={
                        "tool_name": name,
                        "tool_call_id": tool_call_id,
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
            # skills_tool 异常：SkillExecutor 未能走到 _record_skill_span，
            # 此处兜底记录 skill_execution error span
            if skill_name:
                self._add("skill_execution", f"skill:{skill_name}", dur,
                    metadata={
                        "tool_name": name,
                        "skill_name": skill_name,
                        "context_mode": "unknown",
                        "input": args,
                        "error": str(exc)[:500],
                        "status": "error",
                    },
                    input_data={
                        "skill_name": skill_name,
                        "context_mode": "unknown",
                        "arguments": args,
                    },
                    output_data={
                        "error": str(exc)[:500],
                        "status": "error",
                    },
                    detail=f"技能执行失败 · {skill_name}: {str(exc)[:100]}",
                )
            else:
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


class MiddlewareTracingWrapper(AgentMiddleware):
    """中间件执行追踪包装器 — 记录被包装中间件的每次执行

    包装任意 AgentMiddleware，在其 before_agent / after_agent 执行前后
    记录耗时和效果到 TracingMiddleware。

    不包装 TracingMiddleware 自身（避免递归）。

    重要：只覆盖 inner middleware 实际实现的 hook 方法。
    create_agent 通过 `m.__class__.METHOD is not AgentMiddleware.METHOD` 检测
    中间件是否实现了某个 hook，如果 wrapper 无条件覆盖所有方法，会导致
    create_agent 为每个中间件注册所有阶段的图节点，极大增加每轮 ReAct 循环
    消耗的 recursion steps，最终触发 GraphRecursionError。
    """

    # 不需要追踪的中间件（TracingMiddleware 自身 + 纯日志类）
    _SKIP_NAMES = {"TracingMiddleware", "AgentLoggingMiddleware"}

    # 已自行记录详细 span 的中间件（避免重复记录粗粒度 middleware span）
    _SELF_TRACING_NAMES = {"MemoryMiddleware", "TitleMiddleware"}

    def __init__(self, inner: AgentMiddleware) -> None:
        super().__init__()
        self._inner = inner
        self._name = type(inner).__name__

    @property
    def name(self) -> str:
        """返回被包装中间件的名称，确保 langchain 去重检查不会误判"""
        return self._name

    @property
    def inner(self) -> AgentMiddleware:
        return self._inner

    # 中间件 → 设计归属阶段映射
    # 只有在设计归属阶段执行时才记录，避免所有中间件都出现在每个阶段
    _MW_DESIGN_PHASES: dict[str, set[str]] = {
        # before_agent 层
        'DanglingToolCallMiddleware': {'before_agent'},
        'FileProcessMiddleware': {'before_agent'},
        'InputTransformMiddleware': {'before_agent'},
        'MultimodalInjectMiddleware': {'before_agent'},
        'MemoryMiddleware': {'before_agent', 'after_agent'},
        # before_model 层
        'ContextWindowMiddleware': {'before_model'},
        # after_model 层
        'SubagentLimitMiddleware': {'after_model'},
        'LoopDetectionMiddleware': {'after_model'},
        'OutputValidationMiddleware': {'after_model'},
        # wrap_tool_call 层
        'GuardrailMiddleware': {'wrap_tool_call'},
        'ToolErrorHandlingMiddleware': {'wrap_tool_call'},
        'ClarificationMiddleware': {'wrap_tool_call'},
        'SkillToolScopeMiddleware': {'wrap_tool_call'},
        # after_agent 输出层
        'OutputRenderMiddleware': {'after_agent'},
        'StreamPIIRestorer': {'after_agent'},
    }

    def _should_trace(self, phase: str, has_effect: bool) -> bool:
        """判断是否需要追踪 — 只记录设计上属于该阶段的中间件

        每个中间件有明确的设计归属阶段（如 SummarizationMiddleware 归属 before_model）。
        LangGraph 会在所有阶段调用所有中间件，但大部分是空操作。
        只记录设计归属阶段的执行，避免 12 个中间件都出现在 before_model 组中。
        """
        if self._name in self._SELF_TRACING_NAMES:
            return False
        # 查找该中间件的设计归属阶段
        allowed_phases = self._MW_DESIGN_PHASES.get(self._name)
        if allowed_phases is not None:
            return phase in allowed_phases
        # 未在映射表中的中间件：所有阶段都记录
        return True

    def before_agent(self, state: AgentState, runtime: Runtime) -> dict[str, Any] | None:
        start = time.monotonic()
        result = self._inner.before_agent(state, runtime)
        dur = (time.monotonic() - start) * 1000
        if self._should_trace("before_agent", result is not None):
            tracing_middleware.record_middleware_execution(
                self._name, "before_agent", dur,
                has_effect=result is not None,
            )
        return result

    async def abefore_agent(self, state: AgentState, runtime: Runtime) -> dict[str, Any] | None:
        start = time.monotonic()
        inner_cls = type(self._inner)
        if hasattr(inner_cls, 'abefore_agent') and inner_cls.abefore_agent is not AgentMiddleware.abefore_agent:
            result = await self._inner.abefore_agent(state, runtime)
        else:
            result = self._inner.before_agent(state, runtime)
        dur = (time.monotonic() - start) * 1000
        if self._should_trace("before_agent", result is not None):
            tracing_middleware.record_middleware_execution(
                self._name, "before_agent", dur,
                has_effect=result is not None,
            )
        return result

    def after_agent(self, state: AgentState, runtime: Runtime) -> dict[str, Any] | None:
        start = time.monotonic()
        result = self._inner.after_agent(state, runtime)
        dur = (time.monotonic() - start) * 1000
        if self._should_trace("after_agent", result is not None):
            tracing_middleware.record_middleware_execution(
                self._name, "after_agent", dur,
                has_effect=result is not None,
            )
        return result

    async def aafter_agent(self, state: AgentState, runtime: Runtime) -> dict[str, Any] | None:
        start = time.monotonic()
        inner_cls = type(self._inner)
        if hasattr(inner_cls, 'aafter_agent') and inner_cls.aafter_agent is not AgentMiddleware.aafter_agent:
            result = await self._inner.aafter_agent(state, runtime)
        else:
            result = self._inner.after_agent(state, runtime)
        dur = (time.monotonic() - start) * 1000
        if self._should_trace("after_agent", result is not None):
            tracing_middleware.record_middleware_execution(
                self._name, "after_agent", dur,
                has_effect=result is not None,
            )
        return result

    def before_model(self, state: AgentState, runtime: Runtime) -> dict[str, Any] | None:
        start = time.monotonic()
        result = self._inner.before_model(state, runtime)
        dur = (time.monotonic() - start) * 1000
        if self._should_trace("before_model", result is not None):
            tracing_middleware.record_middleware_execution(
                self._name, "before_model", dur,
                has_effect=result is not None,
            )
        return result

    async def abefore_model(self, state: AgentState, runtime: Runtime) -> dict[str, Any] | None:
        start = time.monotonic()
        inner_cls = type(self._inner)
        if hasattr(inner_cls, 'abefore_model') and inner_cls.abefore_model is not AgentMiddleware.abefore_model:
            result = await self._inner.abefore_model(state, runtime)
        else:
            result = self._inner.before_model(state, runtime)
        dur = (time.monotonic() - start) * 1000
        if self._should_trace("before_model", result is not None):
            tracing_middleware.record_middleware_execution(
                self._name, "before_model", dur,
                has_effect=result is not None,
            )
        return result

    def after_model(self, state: AgentState, runtime: Runtime) -> dict[str, Any] | None:
        start = time.monotonic()
        result = self._inner.after_model(state, runtime)
        dur = (time.monotonic() - start) * 1000
        if self._should_trace("after_model", result is not None):
            tracing_middleware.record_middleware_execution(
                self._name, "after_model", dur,
                has_effect=result is not None,
            )
        return result

    async def aafter_model(self, state: AgentState, runtime: Runtime) -> dict[str, Any] | None:
        start = time.monotonic()
        inner_cls = type(self._inner)
        if hasattr(inner_cls, 'aafter_model') and inner_cls.aafter_model is not AgentMiddleware.aafter_model:
            result = await self._inner.aafter_model(state, runtime)
        else:
            result = self._inner.after_model(state, runtime)
        dur = (time.monotonic() - start) * 1000
        if self._should_trace("after_model", result is not None):
            tracing_middleware.record_middleware_execution(
                self._name, "after_model", dur,
                has_effect=result is not None,
            )
        return result

    def wrap_tool_call(self, request: ToolCallRequest, handler):
        inner_cls = type(self._inner)
        if hasattr(inner_cls, 'wrap_tool_call') and inner_cls.wrap_tool_call is not AgentMiddleware.wrap_tool_call:
            start = time.monotonic()
            result = self._inner.wrap_tool_call(request, handler)
            dur = (time.monotonic() - start) * 1000
            if self._should_trace("wrap_tool_call", True):
                tool_name = request.tool_call.get("name", "unknown")
                tool_call_id = request.tool_call.get("id", "")
                tracing_middleware.record_middleware_execution(
                    self._name, "wrap_tool_call", dur,
                    has_effect=True,
                    detail=f"{self._name}: {tool_name}",
                    tool_call_id=tool_call_id,
                )
            return result
        return handler(request)

    async def awrap_tool_call(self, request: ToolCallRequest, handler):
        inner_cls = type(self._inner)
        if hasattr(inner_cls, 'awrap_tool_call') and inner_cls.awrap_tool_call is not AgentMiddleware.awrap_tool_call:
            start = time.monotonic()
            result = await self._inner.awrap_tool_call(request, handler)
            dur = (time.monotonic() - start) * 1000
            if self._should_trace("wrap_tool_call", True):
                tool_name = request.tool_call.get("name", "unknown")
                tool_call_id = request.tool_call.get("id", "")
                tracing_middleware.record_middleware_execution(
                    self._name, "wrap_tool_call", dur,
                    has_effect=True,
                    detail=f"{self._name}: {tool_name}",
                    tool_call_id=tool_call_id,
                )
            return result
        return await handler(request)


def wrap_middlewares_with_tracing(middlewares: list[AgentMiddleware]) -> list[AgentMiddleware]:
    """为中间件列表添加执行追踪包装

    TracingMiddleware 自身不被包装（避免递归）。
    AgentLoggingMiddleware 不被包装（纯日志，无需追踪）。

    重要：使用动态类生成，只覆盖 inner middleware 实际实现的 hook 方法。
    这确保 create_agent 只为每个中间件注册其设计归属阶段的图节点，
    避免冗余节点导致 recursion steps 膨胀。
    """
    wrapped = []
    for mw in middlewares:
        name = type(mw).__name__
        if name in MiddlewareTracingWrapper._SKIP_NAMES:
            wrapped.append(mw)
        else:
            wrapped.append(_create_selective_tracing_wrapper(mw))
    return wrapped


def _create_selective_tracing_wrapper(inner: AgentMiddleware) -> AgentMiddleware:
    """为单个中间件创建选择性追踪包装器

    只覆盖 inner 实际实现的 hook 方法，避免 create_agent 注册冗余图节点。
    动态类直接继承 AgentMiddleware（不继承 MiddlewareTracingWrapper），
    确保未覆盖的方法保持基类默认行为。
    """
    inner_cls = type(inner)
    mw_name = inner_cls.__name__

    # 检测 inner 实际覆盖了哪些方法
    has_before_agent = (
        inner_cls.before_agent is not AgentMiddleware.before_agent
        or inner_cls.abefore_agent is not AgentMiddleware.abefore_agent
    )
    has_after_agent = (
        inner_cls.after_agent is not AgentMiddleware.after_agent
        or inner_cls.aafter_agent is not AgentMiddleware.aafter_agent
    )
    has_before_model = (
        inner_cls.before_model is not AgentMiddleware.before_model
        or inner_cls.abefore_model is not AgentMiddleware.abefore_model
    )
    has_after_model = (
        inner_cls.after_model is not AgentMiddleware.after_model
        or inner_cls.aafter_model is not AgentMiddleware.aafter_model
    )
    has_wrap_tool_call = (
        inner_cls.wrap_tool_call is not AgentMiddleware.wrap_tool_call
        or inner_cls.awrap_tool_call is not AgentMiddleware.awrap_tool_call
    )

    # 动态构建类属性字典，只包含 inner 实际实现的方法
    attrs: dict[str, Any] = {
        'name': property(lambda self: self._mw_name),
        'inner': property(lambda self: self._inner),
        '_should_trace': MiddlewareTracingWrapper._should_trace,
        '_MW_DESIGN_PHASES': MiddlewareTracingWrapper._MW_DESIGN_PHASES,
        '_SELF_TRACING_NAMES': MiddlewareTracingWrapper._SELF_TRACING_NAMES,
    }

    if has_before_agent:
        attrs['before_agent'] = _make_before_agent_sync()
        attrs['abefore_agent'] = _make_before_agent_async()

    if has_after_agent:
        attrs['after_agent'] = _make_after_agent_sync()
        attrs['aafter_agent'] = _make_after_agent_async()

    if has_before_model:
        attrs['before_model'] = _make_before_model_sync()
        attrs['abefore_model'] = _make_before_model_async()

    if has_after_model:
        attrs['after_model'] = _make_after_model_sync()
        attrs['aafter_model'] = _make_after_model_async()

    if has_wrap_tool_call:
        attrs['wrap_tool_call'] = _make_wrap_tool_call_sync()
        attrs['awrap_tool_call'] = _make_wrap_tool_call_async()

    # 动态创建类 — 直接继承 AgentMiddleware，不继承 MiddlewareTracingWrapper
    # 这样 create_agent 的检查 `m.__class__.METHOD is not AgentMiddleware.METHOD`
    # 只会对实际覆盖的方法返回 True
    wrapper_cls = type(f"TracedWrapper_{mw_name}", (AgentMiddleware,), attrs)
    instance = object.__new__(wrapper_cls)
    AgentMiddleware.__init__(instance)
    instance._inner = inner
    instance._name = mw_name
    instance._mw_name = mw_name
    return instance


# ── 工厂函数：生成各阶段的 tracing 方法 ──

def _make_before_agent_sync():
    def before_agent(self, state, runtime):
        start = time.monotonic()
        result = self._inner.before_agent(state, runtime)
        dur = (time.monotonic() - start) * 1000
        if self._should_trace("before_agent", result is not None):
            tracing_middleware.record_middleware_execution(
                self._mw_name, "before_agent", dur, has_effect=result is not None)
        return result
    return before_agent


def _make_before_agent_async():
    async def abefore_agent(self, state, runtime):
        start = time.monotonic()
        inner_cls = type(self._inner)
        if hasattr(inner_cls, 'abefore_agent') and inner_cls.abefore_agent is not AgentMiddleware.abefore_agent:
            result = await self._inner.abefore_agent(state, runtime)
        else:
            result = self._inner.before_agent(state, runtime)
        dur = (time.monotonic() - start) * 1000
        if self._should_trace("before_agent", result is not None):
            tracing_middleware.record_middleware_execution(
                self._mw_name, "before_agent", dur, has_effect=result is not None)
        return result
    return abefore_agent


def _make_after_agent_sync():
    def after_agent(self, state, runtime):
        start = time.monotonic()
        result = self._inner.after_agent(state, runtime)
        dur = (time.monotonic() - start) * 1000
        if self._should_trace("after_agent", result is not None):
            tracing_middleware.record_middleware_execution(
                self._mw_name, "after_agent", dur, has_effect=result is not None)
        return result
    return after_agent


def _make_after_agent_async():
    async def aafter_agent(self, state, runtime):
        start = time.monotonic()
        inner_cls = type(self._inner)
        if hasattr(inner_cls, 'aafter_agent') and inner_cls.aafter_agent is not AgentMiddleware.aafter_agent:
            result = await self._inner.aafter_agent(state, runtime)
        else:
            result = self._inner.after_agent(state, runtime)
        dur = (time.monotonic() - start) * 1000
        if self._should_trace("after_agent", result is not None):
            tracing_middleware.record_middleware_execution(
                self._mw_name, "after_agent", dur, has_effect=result is not None)
        return result
    return aafter_agent


def _make_before_model_sync():
    def before_model(self, state, runtime):
        start = time.monotonic()
        result = self._inner.before_model(state, runtime)
        dur = (time.monotonic() - start) * 1000
        if self._should_trace("before_model", result is not None):
            tracing_middleware.record_middleware_execution(
                self._mw_name, "before_model", dur, has_effect=result is not None)
        return result
    return before_model


def _make_before_model_async():
    async def abefore_model(self, state, runtime):
        start = time.monotonic()
        inner_cls = type(self._inner)
        if hasattr(inner_cls, 'abefore_model') and inner_cls.abefore_model is not AgentMiddleware.abefore_model:
            result = await self._inner.abefore_model(state, runtime)
        else:
            result = self._inner.before_model(state, runtime)
        dur = (time.monotonic() - start) * 1000
        if self._should_trace("before_model", result is not None):
            tracing_middleware.record_middleware_execution(
                self._mw_name, "before_model", dur, has_effect=result is not None)
        return result
    return abefore_model


def _make_after_model_sync():
    def after_model(self, state, runtime):
        start = time.monotonic()
        result = self._inner.after_model(state, runtime)
        dur = (time.monotonic() - start) * 1000
        if self._should_trace("after_model", result is not None):
            tracing_middleware.record_middleware_execution(
                self._mw_name, "after_model", dur, has_effect=result is not None)
        return result
    return after_model


def _make_after_model_async():
    async def aafter_model(self, state, runtime):
        start = time.monotonic()
        inner_cls = type(self._inner)
        if hasattr(inner_cls, 'aafter_model') and inner_cls.aafter_model is not AgentMiddleware.aafter_model:
            result = await self._inner.aafter_model(state, runtime)
        else:
            result = self._inner.after_model(state, runtime)
        dur = (time.monotonic() - start) * 1000
        if self._should_trace("after_model", result is not None):
            tracing_middleware.record_middleware_execution(
                self._mw_name, "after_model", dur, has_effect=result is not None)
        return result
    return aafter_model


def _make_wrap_tool_call_sync():
    def wrap_tool_call(self, request, handler):
        inner_cls = type(self._inner)
        if hasattr(inner_cls, 'wrap_tool_call') and inner_cls.wrap_tool_call is not AgentMiddleware.wrap_tool_call:
            start = time.monotonic()
            result = self._inner.wrap_tool_call(request, handler)
            dur = (time.monotonic() - start) * 1000
            if self._should_trace("wrap_tool_call", True):
                tool_name = request.tool_call.get("name", "unknown")
                tool_call_id = request.tool_call.get("id", "")
                tracing_middleware.record_middleware_execution(
                    self._mw_name, "wrap_tool_call", dur,
                    has_effect=True, detail=f"{self._mw_name}: {tool_name}",
                    tool_call_id=tool_call_id)
            return result
        return handler(request)
    return wrap_tool_call


def _make_wrap_tool_call_async():
    async def awrap_tool_call(self, request, handler):
        inner_cls = type(self._inner)
        if hasattr(inner_cls, 'awrap_tool_call') and inner_cls.awrap_tool_call is not AgentMiddleware.awrap_tool_call:
            start = time.monotonic()
            result = await self._inner.awrap_tool_call(request, handler)
            dur = (time.monotonic() - start) * 1000
            if self._should_trace("wrap_tool_call", True):
                tool_name = request.tool_call.get("name", "unknown")
                tool_call_id = request.tool_call.get("id", "")
                tracing_middleware.record_middleware_execution(
                    self._mw_name, "wrap_tool_call", dur,
                    has_effect=True, detail=f"{self._mw_name}: {tool_name}",
                    tool_call_id=tool_call_id)
            return result
        return await handler(request)
    return awrap_tool_call


# 全局单例
tracing_middleware = TracingMiddleware()
