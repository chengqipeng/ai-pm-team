"""上下文窗口管理中间件 — 统一的上下文压缩与控制

合并原 SummarizationMiddleware + ToolResultCompactMiddleware 的职责：

wrap_tool_call 阶段（源头控制）：
  - 工具执行后立即检查结果大小
  - 超过动态阈值 → 代码格式化提取（0 LLM 成本）或 LLM 摘要
  - 确保进入上下文的 ToolMessage 都是精简的

before_model 阶段（窗口管理）：
  - Pass 0: MD5 去重（相同内容只保留最新一份）
  - Pass 1: MicroCompact（CRM 专用摘要模板替换旧 ToolMessage）
  - Pass 2: AutoCompact（结构化摘要替换旧消息）
  - Pass 3: FullCompact（全量压缩 + 重注入关键信息）
  - 熔断机制：连续 N 次压缩失败后停止重试

参考：
  - apps-agent: process_sub_agent_result（源头摘要）
  - Hermes: _prune_old_tool_results（MD5 去重 + 信息摘要替换）
  - Claude Code: MicroCompact / AutoCompact / FullCompact（三层级联）
  - 设计文档: Layer 1 源头隔离 + Layer 2 当前轮次裁剪
"""
from __future__ import annotations

import hashlib
import json
import logging
import time
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain.agents.middleware.types import AgentMiddleware, AgentState
from langgraph.prebuilt.tool_node import ToolCallRequest
from langgraph.runtime import Runtime
from langgraph.types import Command

logger = logging.getLogger(__name__)


def _estimate_tokens(messages: list) -> int:
    """粗略估算 token 数（1 token ≈ 2 字符）"""
    total = 0
    for msg in messages:
        content = getattr(msg, "content", "")
        if isinstance(content, str):
            total += len(content) // 2
        elif isinstance(content, list):
            for block in content:
                if isinstance(block, str):
                    total += len(block) // 2
                elif isinstance(block, dict):
                    total += len(str(block.get("text", ""))) // 2
    return total


# ═══════════════════════════════════════════════════════════
# 源头压缩：动态阈值配置
# ═══════════════════════════════════════════════════════════

TOOL_THRESHOLDS: dict[str, dict] = {
    "query_data":          {"threshold": 300, "max_summary": 100},
    "query_schema":        {"threshold": 500, "max_summary": 150},
    "web_search":          {"threshold": 500, "max_summary": 150},
    "analyze_data":        {"threshold": 800, "max_summary": 200},
    "query_metadata":      {"threshold": 500, "max_summary": 150},
}
DEFAULT_TOOL_THRESHOLD = {"threshold": 500, "max_summary": 150}

# 不压缩的工具（skills_tool 由 SkillExecutor 自行处理；read_skill_resource 是知识文件，不能源头压缩）
SKIP_COMPACT_TOOLS = {"skills_tool", "agent_tool", "ask_user", "scratchpad", "read_skill_resource"}



class ContextWindowMiddleware(AgentMiddleware):
    """上下文窗口管理 — 源头压缩 + 窗口管理统一中间件

    wrap_tool_call: 源头压缩（动态阈值 + 代码提取 + LLM 摘要兜底）
    before_model:  窗口管理（MD5 去重 + MicroCompact + AutoCompact + FullCompact）
    """

    def __init__(
        self,
        max_tokens: int = 100_000,
        micro_threshold: float = 0.50,
        auto_threshold: float = 0.75,
        full_threshold: float = 0.90,
        tool_output_max_chars: int = 2_000,
        max_consecutive_failures: int = 3,
        llm: Any = None,
    ):
        super().__init__()
        self._max_tokens = max_tokens
        self._micro_trigger = int(max_tokens * micro_threshold)
        self._auto_trigger = int(max_tokens * auto_threshold)
        self._full_trigger = int(max_tokens * full_threshold)
        self._tool_output_max_chars = tool_output_max_chars
        self._max_failures = max_consecutive_failures
        self._consecutive_failures = 0
        self._llm = llm

    # ═══════════════════════════════════════════════════════════
    # wrap_tool_call: 源头压缩
    # ═══════════════════════════════════════════════════════════

    async def awrap_tool_call(self, request: ToolCallRequest, handler) -> ToolMessage | Command:
        tool_name = request.tool_call.get("name", "unknown")
        tool_call_id = request.tool_call.get("id", "")

        result = await handler(request)

        # 跳过不需要压缩的工具
        if tool_name in SKIP_COMPACT_TOOLS:
            return result

        content = getattr(result, "content", "")
        if not isinstance(content, str):
            content = str(content)

        # 查动态阈值
        config = TOOL_THRESHOLDS.get(tool_name, DEFAULT_TOOL_THRESHOLD)
        threshold = config["threshold"]

        if len(content) <= threshold:
            # 未超阈值，记录跳过 span
            self._record_compact_span(tool_name, len(content), len(content),
                                      skipped=True, tool_call_id=tool_call_id)
            return result

        original_len = len(content)

        # 代码格式化摘要（0 LLM 成本）
        summary = _try_code_extract(tool_name, content)

        # LLM 摘要兜底
        if not summary and self._llm:
            summary = await self._llm_summarize(content, tool_name, config["max_summary"])

        # 最终兜底：截断 + 标注
        if not summary:
            summary = _fallback_truncate(tool_name, content, config["max_summary"])

        result.content = summary

        logger.info("[ContextWindow] 源头压缩 %s: %d→%d chars (节省%.0f%%)",
                    tool_name, original_len, len(summary),
                    (1 - len(summary) / max(original_len, 1)) * 100)

        # Tracing（含原文和摘要内容）
        self._record_compact_span(tool_name, original_len, len(summary),
                                  original_content=content, summary_content=summary,
                                  tool_call_id=tool_call_id)
        return result

    async def _llm_summarize(self, content: str, tool_name: str, max_words: int) -> str | None:
        try:
            from langchain_core.messages import HumanMessage as HM
            prompt = (
                f"请将以下工具 `{tool_name}` 的返回结果压缩为不超过 {max_words} 字的摘要。\n"
                f"要求：保留关键数据（数字、名称、状态），去掉冗余描述。\n\n"
                f"原文：\n{content[:3000]}"
            )
            resp = await self._llm.ainvoke([HM(content=prompt)])
            return resp.content[:max_words * 3]
        except Exception as e:
            logger.warning("[ContextWindow] LLM summarize failed: %s", e)
            return None

    # ═══════════════════════════════════════════════════════════
    # before_model: 窗口管理
    # ═══════════════════════════════════════════════════════════

    def before_model(self, state: AgentState, runtime: Runtime) -> dict[str, Any] | None:
        messages = state.get("messages", [])

        # Pass 0: MD5 去重
        dedup_result = self._md5_dedup(messages)
        if dedup_result is not None:
            messages = dedup_result["messages"]

        if len(messages) < 4:
            self._record_window_span(
                len(messages), 0, "skip", "消息数不足",
                messages_before=messages)
            return dedup_result

        # 熔断检查
        if self._consecutive_failures >= self._max_failures:
            self._record_window_span(
                len(messages), 0, "circuit_break",
                f"熔断（连续{self._consecutive_failures}次失败）",
                messages_before=messages)
            return dedup_result

        estimated = _estimate_tokens(messages)

        try:
            # Pass 3: FullCompact
            if estimated >= self._full_trigger:
                result = self._full_compact(messages, estimated)
                if result:
                    self._consecutive_failures = 0
                    new_est = _estimate_tokens(result["messages"])
                    self._record_window_span(
                        len(messages), estimated, "full_compact",
                        f"超过90%阈值（{estimated}/{self._max_tokens}）",
                        new_est, len(result["messages"]), messages, result["messages"])
                    return result

            # Pass 2: AutoCompact
            if estimated >= self._auto_trigger:
                result = self._auto_compact(messages, estimated)
                if result:
                    self._consecutive_failures = 0
                    new_est = _estimate_tokens(result["messages"])
                    self._record_window_span(
                        len(messages), estimated, "auto_compact",
                        f"超过75%阈值（{estimated}/{self._max_tokens}）",
                        new_est, len(result["messages"]), messages, result["messages"])
                    return result

            # Pass 1: MicroCompact
            if estimated >= self._micro_trigger:
                result = self._micro_compact(messages, estimated)
                if result:
                    new_est = _estimate_tokens(result["messages"])
                    self._record_window_span(
                        len(messages), estimated, "micro_compact",
                        f"超过50%阈值（{estimated}/{self._max_tokens}）",
                        new_est, len(result["messages"]), messages, result["messages"])
                    return result

        except Exception as e:
            self._consecutive_failures += 1
            logger.error("Compression failed (%d/%d): %s",
                         self._consecutive_failures, self._max_failures, e)
            self._record_window_span(
                len(messages), estimated, "error",
                f"压缩失败: {str(e)[:100]}", messages_before=messages)

        # 无需压缩
        self._record_window_span(
            len(messages), estimated, "none", "未达到压缩阈值",
            messages_before=messages)
        return dedup_result

    # ═══════════════════════════════════════════════════════════
    # Pass 0: MD5 去重
    # ═══════════════════════════════════════════════════════════

    def _md5_dedup(self, messages: list) -> dict[str, Any] | None:
        """相同内容的 ToolMessage 只保留最新一份"""
        seen: dict[str, int] = {}
        modified = False
        result = list(messages)

        for i in range(len(result) - 1, -1, -1):
            if not isinstance(result[i], ToolMessage):
                continue
            content = result[i].content or ""
            if len(content) < 100:
                continue
            h = hashlib.md5(content.encode("utf-8")).hexdigest()[:12]
            if h in seen:
                result[i] = ToolMessage(
                    content="[重复结果 — 与最近一次相同查询结果一致]",
                    tool_call_id=getattr(result[i], "tool_call_id", ""),
                )
                modified = True
            else:
                seen[h] = i

        if modified:
            logger.info("[ContextWindow] MD5 去重: 移除重复 ToolMessage")
            return {"messages": result}
        return None

    # ═══════════════════════════════════════════════════════════
    # Pass 1: MicroCompact — CRM 专用摘要模板
    # ═══════════════════════════════════════════════════════════

    def _micro_compact(self, messages: list, estimated: int) -> dict[str, Any] | None:
        """裁剪旧 ToolMessage + tool_call 参数截断"""
        keep_recent = 6
        if len(messages) <= keep_recent:
            return None

        old_messages = messages[:-keep_recent]
        recent = messages[-keep_recent:]
        modified = False
        compacted = []

        for msg in old_messages:
            if isinstance(msg, ToolMessage):
                content = msg.content if isinstance(msg.content, str) else str(msg.content)
                if len(content) > 200:
                    # CRM 专用摘要模板
                    summary = _crm_tool_summary(msg)
                    compacted.append(ToolMessage(
                        content=summary,
                        tool_call_id=getattr(msg, "tool_call_id", ""),
                        name=getattr(msg, "name", ""),
                    ))
                    modified = True
                    continue
            # tool_call 参数截断
            elif isinstance(msg, AIMessage) and getattr(msg, "tool_calls", None):
                tc_modified = False
                new_tool_calls = []
                for tc in msg.tool_calls:
                    args_str = json.dumps(tc.get("args", {}), ensure_ascii=False)
                    if len(args_str) > 500:
                        tc = dict(tc)
                        tc["args"] = {"_truncated": args_str[:200] + "..."}
                        tc_modified = True
                    new_tool_calls.append(tc)
                if tc_modified:
                    compacted.append(AIMessage(
                        content=msg.content, tool_calls=new_tool_calls))
                    modified = True
                    continue
            compacted.append(msg)

        if not modified:
            return None

        new_estimated = _estimate_tokens(compacted + recent)
        logger.info("[ContextWindow] MicroCompact: %d → %d tokens", estimated, new_estimated)
        return {"messages": compacted + recent}

    # ═══════════════════════════════════════════════════════════
    # Pass 2: AutoCompact — 结构化摘要
    # ═══════════════════════════════════════════════════════════

    def _auto_compact(self, messages: list, estimated: int) -> dict[str, Any] | None:
        keep_recent = 4
        if len(messages) <= keep_recent:
            return None

        to_summarize = messages[:-keep_recent]
        recent = messages[-keep_recent:]

        parts = []
        for msg in to_summarize[-12:]:
            content = getattr(msg, "content", "")
            if not isinstance(content, str) or not content.strip():
                continue
            role = getattr(msg, "type", "unknown")
            max_len = 300 if role in ("human", "ai") else 150
            truncated = content[:max_len] + ("..." if len(content) > max_len else "")
            parts.append(f"[{role}] {truncated}")

        if not parts:
            return None

        summary_text = "[历史摘要]\n" + "\n".join(parts)
        new_messages = [SystemMessage(content=summary_text)] + recent
        new_estimated = _estimate_tokens(new_messages)
        logger.info("[ContextWindow] AutoCompact: %d → %d tokens", estimated, new_estimated)
        return {"messages": new_messages}

    # ═══════════════════════════════════════════════════════════
    # Pass 3: FullCompact — 全量压缩
    # ═══════════════════════════════════════════════════════════

    def _full_compact(self, messages: list, estimated: int) -> dict[str, Any] | None:
        new_messages = []
        recent_tool_results = []
        recent_human = None

        for msg in reversed(messages[-8:]):
            if isinstance(msg, ToolMessage) and len(recent_tool_results) < 3:
                recent_tool_results.append(msg)
            elif isinstance(msg, HumanMessage) and recent_human is None:
                recent_human = msg

        summary_parts = []
        for msg in messages:
            content = getattr(msg, "content", "")
            if not isinstance(content, str):
                continue
            role = getattr(msg, "type", "unknown")
            if role == "system":
                new_messages.append(msg)
            elif content.strip():
                summary_parts.append(f"[{role}] {content[:100]}")

        if summary_parts:
            compact_summary = "[全量压缩摘要]\n" + "\n".join(summary_parts[-20:])
            new_messages.append(SystemMessage(content=compact_summary))

        # 重注入最近的 tool_calls + results
        if recent_tool_results:
            tool_calls = []
            for tm in recent_tool_results:
                tc_id = getattr(tm, "tool_call_id", "")
                tc_name = getattr(tm, "name", "") or "tool"
                tool_calls.append({"id": tc_id, "name": tc_name, "args": {}})
            if tool_calls:
                new_messages.append(AIMessage(content="", tool_calls=tool_calls))
                new_messages.extend(reversed(recent_tool_results))
        if recent_human:
            new_messages.append(recent_human)

        new_estimated = _estimate_tokens(new_messages)
        logger.info("[ContextWindow] FullCompact: %d → %d tokens", estimated, new_estimated)
        return {"messages": new_messages}

    # ═══════════════════════════════════════════════════════════
    # Tracing
    # ═══════════════════════════════════════════════════════════

    def _record_compact_span(self, tool_name: str, original_len: int, summary_len: int,
                             skipped: bool = False,
                             original_content: str = "", summary_content: str = "",
                             tool_call_id: str = "") -> None:
        """记录源头压缩 span（含原文和压缩后内容）

        注意：此方法在 awrap_tool_call 中调用，即工具执行完成后立即记录。
        compact span 属于当前循环的工具执行阶段（不是下一个循环的 before_model）。
        通过 _iter_count 标记所属循环，供前端正确归组。
        """
        try:
            from src.middleware.tracing import tracing_middleware
            config = TOOL_THRESHOLDS.get(tool_name, DEFAULT_TOOL_THRESHOLD)
            # 获取当前循环编号（与 TracingMiddleware 的 _iter_count 一致）
            tid = tracing_middleware._tid()
            current_iteration = tracing_middleware._iter_count.get(tid, 0)

            if skipped:
                tracing_middleware._add("tool_result_compact", f"compact:{tool_name}", 0,
                    metadata={"tool_name": tool_name, "tool_call_id": tool_call_id,
                              "iteration": current_iteration},
                    input_data={"tool_name": tool_name, "content_length": original_len,
                                "threshold": config["threshold"],
                                "tool_call_id": tool_call_id,
                                "iteration": current_iteration},
                    output_data={"action": "skip", "reason": f"未超阈值({original_len}/{config['threshold']})"},
                    detail=f"上下文检查: {tool_name} {original_len}字符 ≤ 阈值{config['threshold']} → 保留原文",
                )
            else:
                ratio = round(1 - summary_len / max(original_len, 1), 2)
                tracing_middleware._add("tool_result_compact", f"compact:{tool_name}", 0,
                    metadata={"tool_name": tool_name, "tool_call_id": tool_call_id,
                              "iteration": current_iteration},
                    input_data={
                        "tool_name": tool_name,
                        "original_length": original_len,
                        "threshold": config["threshold"],
                        "original_content": original_content[:2000],
                        "tool_call_id": tool_call_id,
                        "iteration": current_iteration,
                    },
                    output_data={
                        "summary_length": summary_len,
                        "compression_ratio": f"{ratio:.0%}",
                        "action": "compressed",
                        "summary_content": summary_content[:500],
                    },
                    detail=f"源头压缩: {tool_name} {original_len}→{summary_len}字符 (节省{ratio:.0%})",
                )
        except Exception:
            logger.exception("context_window.py L461 异常")

    def _record_window_span(
        self, messages_count: int, estimated_tokens: int,
        action: str, reason: str,
        compressed_tokens: int = 0, messages_after: int = 0,
        messages_before: list | None = None, messages_result: list | None = None,
    ) -> None:
        """记录窗口管理 span（覆盖 MiddlewareTracingWrapper 的通用 span）"""
        try:
            from src.middleware.tracing import tracing_middleware
            has_effect = action not in ("none", "skip", "circuit_break")
            detail = f"{'✅ ' + action if has_effect else '⏭️ 无需压缩'}: {reason}"
            if has_effect:
                detail += f" → {estimated_tokens}→{compressed_tokens} tokens"

            # 构建上下文消息预览
            input_messages_preview = []
            if messages_before:
                for m in messages_before[-15:]:
                    m_type = getattr(m, "type", "unknown")
                    m_content = getattr(m, "content", "")
                    if not isinstance(m_content, str):
                        m_content = str(m_content)[:500]
                    input_messages_preview.append({"role": m_type, "content": m_content[:500]})

            output_messages_preview = []
            if has_effect and messages_result:
                for m in messages_result[-10:]:
                    m_type = getattr(m, "type", "unknown")
                    m_content = getattr(m, "content", "")
                    if not isinstance(m_content, str):
                        m_content = str(m_content)[:500]
                    output_messages_preview.append({"role": m_type, "content": m_content[:500]})

            tid = None
            try:
                from langgraph.config import get_config
                tid = get_config().get("configurable", {}).get("thread_id")
            except Exception:
                logger.exception("context_window.py L501 异常")

            if tid:
                tracing_middleware._spans.setdefault(tid, [])
                # 覆盖 MiddlewareTracingWrapper 记录的通用 span
                for i in range(len(tracing_middleware._spans[tid]) - 1, -1, -1):
                    s = tracing_middleware._spans[tid][i]
                    if (s.get("type") == "middleware"
                            and s.get("metadata", {}).get("middleware_name") == "ContextWindowMiddleware"
                            and s.get("metadata", {}).get("phase") == "before_model"):
                        s["input_data"] = {
                            "messages_count": messages_count,
                            "estimated_tokens": estimated_tokens,
                            "thresholds": {"micro": self._micro_trigger, "auto": self._auto_trigger, "full": self._full_trigger},
                            "context_messages": input_messages_preview,
                        }
                        s["output_data"] = {
                            "action": action, "has_effect": has_effect, "reason": reason,
                            "compressed_tokens": compressed_tokens, "messages_after": messages_after,
                            "compressed_messages": output_messages_preview if has_effect else [],
                        }
                        s["detail"] = detail
                        break
        except Exception:
            logger.exception("context_window.py L525 异常")

    def reset_circuit_breaker(self) -> None:
        self._consecutive_failures = 0


# ═══════════════════════════════════════════════════════════
# 源头压缩：代码格式化提取（零 LLM 成本）
# ═══════════════════════════════════════════════════════════

def _try_code_extract(tool_name: str, content: str) -> str | None:
    """尝试用代码规则提取摘要"""
    stripped = content.strip()
    if stripped.startswith("{") or stripped.startswith("["):
        try:
            data = json.loads(stripped)
            return _extract_from_json(tool_name, data)
        except json.JSONDecodeError:
            pass

    if tool_name == "web_search":
        lines = content.split("\n")
        meaningful = [l.strip() for l in lines if l.strip() and len(l.strip()) > 20][:3]
        if meaningful:
            return f"[web_search] ({len(content)}字符)\n" + "\n".join(meaningful)

    if len(content) > 500:
        return f"[{tool_name}] ({len(content)}字符, {content.count(chr(10))+1}行)\n{content[:200]}..."

    return None


def _extract_from_json(tool_name: str, data: Any) -> str | None:
    """从 JSON 数据提取摘要"""
    if isinstance(data, dict) and "records" in data:
        records = data["records"]
        if isinstance(records, list):
            count = len(records)
            names = [str(r.get("name", r.get("subject", r.get("id", ""))))
                     for r in records[:5]]
            names_str = ", ".join(n for n in names if n)
            extra = f"...等{count}条" if count > 5 else ""
            amounts = [r.get("amount", 0) for r in records if r.get("amount")]
            amount_str = f", 总金额{sum(float(a) for a in amounts):.0f}万" if amounts else ""
            return f"查询返回{count}条记录: {names_str}{extra}{amount_str}"

    if isinstance(data, dict) and "records" not in data:
        key_fields = ["name", "id", "industry", "city", "amount", "stage",
                      "status", "probability", "title", "type"]
        parts = [f"{k}={data[k]}" for k in key_fields if k in data and data[k]]
        if parts:
            return f"记录: {', '.join(str(p) for p in parts[:8])}"

    if isinstance(data, list):
        count = len(data)
        if count > 0 and isinstance(data[0], dict):
            names = [str(r.get("name", r.get("title", ""))) for r in data[:5]]
            return f"返回{count}条: {', '.join(n for n in names if n)}"
        return f"返回{count}项数据"

    return None


def _crm_tool_summary(msg: ToolMessage) -> str:
    """CRM 工具专用一行摘要（用于 MicroCompact 替换旧 ToolMessage）"""
    content = msg.content if isinstance(msg.content, str) else str(msg.content)
    tool_name = getattr(msg, "name", "") or ""

    # JSON 数据提取
    stripped = content.strip()
    if stripped.startswith("{") or stripped.startswith("["):
        try:
            data = json.loads(stripped)
            extracted = _extract_from_json(tool_name, data)
            if extracted:
                return extracted
        except json.JSONDecodeError:
            pass

    # 通用：保留前 100 字符
    preview = content[:100].replace("\n", " ")
    return f"[{tool_name or 'tool'}] {preview}... ({len(content)}字符)"


def _fallback_truncate(tool_name: str, content: str, max_chars: int) -> str:
    """兜底截断"""
    preview = content[:max_chars * 2]
    return f"[{tool_name}] {preview}...\n[已截断, 原文{len(content)}字符]"


# 向后兼容别名
SummarizationMiddleware = ContextWindowMiddleware
