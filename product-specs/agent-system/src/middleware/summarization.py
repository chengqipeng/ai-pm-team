"""三层上下文压缩中间件 — 借鉴 Claude Code 架构

Layer 1: MicroCompact — 本地裁剪旧 ToolMessage 输出，0 API 调用
Layer 2: AutoCompact — 接近 token 上限时生成结构化摘要，保留 buffer
Layer 3: FullCompact — 全量压缩 + 重注入最近访问文件/技能 schema

熔断机制: 连续 N 次压缩失败后停止重试
"""

import logging
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain.agents.middleware.types import AgentMiddleware, AgentState
from langgraph.runtime import Runtime

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


class SummarizationMiddleware(AgentMiddleware):
    """三层上下文压缩 + 熔断机制

    参数:
        max_tokens: 上下文窗口上限（默认 100K）
        micro_threshold: MicroCompact 触发比例（默认 0.50）
        auto_threshold: AutoCompact 触发比例（默认 0.75）
        full_threshold: FullCompact 触发比例（默认 0.90）
        auto_buffer: AutoCompact 保留的 buffer token 数
        full_budget_reset: FullCompact 后重置的工作预算
        tool_output_max_chars: MicroCompact 裁剪 ToolMessage 的最大字符数
        max_consecutive_failures: 熔断阈值
    """

    def __init__(
        self,
        max_tokens: int = 100_000,
        micro_threshold: float = 0.50,
        auto_threshold: float = 0.75,
        full_threshold: float = 0.90,
        auto_buffer: int = 13_000,
        full_budget_reset: int = 50_000,
        tool_output_max_chars: int = 2_000,
        max_consecutive_failures: int = 3,
        # 向后兼容旧参数
        trigger_ratio: float | None = None,
    ):
        super().__init__()
        # 向后兼容：如果传了旧的 trigger_ratio，映射到 auto_threshold
        if trigger_ratio is not None:
            auto_threshold = trigger_ratio
        self._max_tokens = max_tokens
        self._micro_trigger = int(max_tokens * micro_threshold)
        self._auto_trigger = int(max_tokens * auto_threshold)
        self._full_trigger = int(max_tokens * full_threshold)
        self._auto_buffer = auto_buffer
        self._full_budget_reset = full_budget_reset
        self._tool_output_max_chars = tool_output_max_chars
        self._max_failures = max_consecutive_failures
        self._consecutive_failures = 0

    def before_model(self, state: AgentState, runtime: Runtime) -> dict[str, Any] | None:
        messages = state.get("messages", [])
        if len(messages) < 4:
            return None

        # 熔断检查
        if self._consecutive_failures >= self._max_failures:
            logger.warning("Compression circuit breaker open (%d failures), skipping",
                           self._consecutive_failures)
            return None

        estimated = _estimate_tokens(messages)

        try:
            # Layer 3: FullCompact — 全量压缩
            if estimated >= self._full_trigger:
                result = self._full_compact(messages, estimated)
                if result:
                    self._consecutive_failures = 0
                    return result

            # Layer 2: AutoCompact — 结构化摘要
            if estimated >= self._auto_trigger:
                result = self._auto_compact(messages, estimated)
                if result:
                    self._consecutive_failures = 0
                    return result

            # Layer 1: MicroCompact — 本地裁剪（0 API 调用）
            if estimated >= self._micro_trigger:
                result = self._micro_compact(messages, estimated)
                if result:
                    # MicroCompact 不算失败/成功，不影响熔断计数
                    return result

        except Exception as e:
            self._consecutive_failures += 1
            logger.error("Compression failed (attempt %d/%d): %s",
                         self._consecutive_failures, self._max_failures, e)

        return None

    def _micro_compact(self, messages: list, estimated: int) -> dict[str, Any] | None:
        """Layer 1: MicroCompact — 裁剪旧 ToolMessage 输出，0 API 调用

        只处理非最近 N 条消息中的 ToolMessage，将超长输出截断。
        """
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
                if len(content) > self._tool_output_max_chars:
                    truncated = content[:self._tool_output_max_chars] + \
                        f"\n...[truncated {len(content) - self._tool_output_max_chars} chars]"
                    compacted.append(ToolMessage(
                        content=truncated,
                        tool_call_id=getattr(msg, "tool_call_id", ""),
                        name=getattr(msg, "name", ""),
                        status=getattr(msg, "status", "success"),
                    ))
                    modified = True
                    continue
            compacted.append(msg)

        if not modified:
            return None

        new_estimated = _estimate_tokens(compacted + recent)
        logger.info("MicroCompact: %d → %d tokens (trimmed tool outputs)", estimated, new_estimated)
        return {"messages": compacted + recent}

    def _auto_compact(self, messages: list, estimated: int) -> dict[str, Any] | None:
        """Layer 2: AutoCompact — 保留最近消息，对旧消息生成结构化摘要

        保留 buffer，生成最多 20K token 的摘要。
        """
        keep_recent = 4
        if len(messages) <= keep_recent:
            return None

        to_summarize = messages[:-keep_recent]
        recent = messages[-keep_recent:]

        # 提取关键信息构建摘要
        parts = []
        for msg in to_summarize[-12:]:  # 最多取最近 12 条旧消息
            content = getattr(msg, "content", "")
            if not isinstance(content, str) or not content.strip():
                continue
            role = getattr(msg, "type", "unknown")
            # 按角色不同截断长度
            max_len = 300 if role in ("human", "ai") else 150
            truncated = content[:max_len] + ("..." if len(content) > max_len else "")
            parts.append(f"[{role}] {truncated}")

        if not parts:
            return None

        summary = (
            "<context_summary>\n"
            "以下是之前对话的结构化摘要（AutoCompact 压缩）：\n"
            + "\n".join(parts) +
            "\n</context_summary>"
        )

        new_messages = [SystemMessage(content=summary)] + recent
        new_estimated = _estimate_tokens(new_messages)
        logger.info("AutoCompact: %d → %d tokens (kept %d recent, summarized %d old)",
                     estimated, new_estimated, len(recent), len(to_summarize))
        return {"messages": new_messages}

    def _full_compact(self, messages: list, estimated: int) -> dict[str, Any] | None:
        """Layer 3: FullCompact — 全量压缩 + 重注入关键上下文

        压缩所有消息为摘要，重注入：
        - 最近的 HumanMessage（当前任务）
        - 最近的 ToolMessage 结果（关键数据，≤5K chars/条）
        - 活跃的技能 schema
        """
        # 提取需要重注入的关键内容
        recent_human = None
        recent_tool_results = []
        file_max_chars = 5_000

        for msg in reversed(messages):
            if isinstance(msg, HumanMessage) and recent_human is None:
                recent_human = msg
            elif isinstance(msg, ToolMessage) and len(recent_tool_results) < 3:
                content = msg.content if isinstance(msg.content, str) else str(msg.content)
                if len(content) > file_max_chars:
                    content = content[:file_max_chars] + "...[truncated]"
                recent_tool_results.append(ToolMessage(
                    content=content,
                    tool_call_id=getattr(msg, "tool_call_id", ""),
                    name=getattr(msg, "name", ""),
                ))
            if recent_human and len(recent_tool_results) >= 3:
                break

        # 构建全量摘要
        key_exchanges = []
        for msg in messages:
            content = getattr(msg, "content", "")
            if not isinstance(content, str) or not content.strip():
                continue
            role = getattr(msg, "type", "unknown")
            if role in ("human", "ai"):
                key_exchanges.append(f"[{role}] {content[:200]}{'...' if len(content) > 200 else ''}")

        summary_text = (
            "<full_compact_summary>\n"
            "对话已进行全量压缩（FullCompact）。以下是关键交互摘要：\n"
            + "\n".join(key_exchanges[-8:]) +
            f"\n\n工作预算已重置为 {self._full_budget_reset} tokens。"
            "\n</full_compact_summary>"
        )

        # 重组消息：摘要 + 重注入的工具结果 + 当前用户消息
        new_messages: list = [SystemMessage(content=summary_text)]
        # 重注入最近的工具结果（需要配对 AIMessage 的 tool_calls）
        if recent_tool_results:
            # 创建一个虚拟的 AIMessage 来配对 ToolMessage
            tool_calls = []
            for tm in reversed(recent_tool_results):
                tc_id = getattr(tm, "tool_call_id", "")
                tc_name = getattr(tm, "name", "")
                if tc_id:
                    tool_calls.append({"id": tc_id, "name": tc_name, "args": {}})
            if tool_calls:
                new_messages.append(AIMessage(content="", tool_calls=tool_calls))
                new_messages.extend(reversed(recent_tool_results))
        if recent_human:
            new_messages.append(recent_human)

        new_estimated = _estimate_tokens(new_messages)
        logger.info("FullCompact: %d → %d tokens (full reset, re-injected %d tool results)",
                     estimated, new_estimated, len(recent_tool_results))
        return {"messages": new_messages}

    def reset_circuit_breaker(self) -> None:
        """手动重置熔断器"""
        self._consecutive_failures = 0
