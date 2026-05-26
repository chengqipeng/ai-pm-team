"""AG-UI Converter — LangGraph astream_events → AG-UI 标准事件流

职责（对齐 apps-agent v2 + AG-UI 官方 SDK）：
- 订阅 LangGraph astream_events(v2)
- 维护三类流状态机（文本 / 推理 / 工具调用）互斥切换
- 过滤子 Agent 事件（parent_ids[0] != root_run_id；on_custom_event 例外）
- 识别 Skill chain（skill_ 前缀）→ 发 STEP + 伴随 CUSTOM("step_metadata")
- 工具调用：拆 TOOL_CALL_START / ARGS / END / RESULT 四段
- 推理：REASONING_START/END 包围 REASONING_MESSAGE_START/CONTENT/END
- on_custom_event 适配层：agent_text / agent_data / a2ui.* / state.patch / skill.output
- 断线重连：emit_reconnect_snapshot 按固定顺序下发首包
"""
from __future__ import annotations

import logging
import uuid
from typing import Any, AsyncGenerator

from . import models as m

logger = logging.getLogger(__name__)

SKILL_CHAIN_PREFIX = "skill_"


def _record_model_phase_middlewares(phase: str, thread_id: str) -> None:
    """记录 before_model/after_model 阶段的中间件 span

    LangGraph create_react_agent 不自动调用 middleware 的 before_model/after_model，
    这里在 on_chat_model_start/end 事件时手动记录已知的中间件。
    与 server.py SSE 模式的 _record_model_phase_middlewares 保持一致。

    注意：如果 MiddlewareTracingWrapper 已经记录了该阶段的 span（LangGraph 自动调用的情况），
    此函数会做去重检查以避免重复。
    """
    from src.middleware.tracing import tracing_middleware
    MW_BY_PHASE = {
        "before_model": ["SummarizationMiddleware"],
        "after_model": ["SubagentLimitMiddleware", "LoopDetectionMiddleware", "OutputValidationMiddleware"],
    }
    mw_list = MW_BY_PHASE.get(phase, [])

    # 去重检查：检查最近 N 个 span 中是否已有同阶段同名中间件（避免 MiddlewareTracingWrapper 重复）
    existing_spans = tracing_middleware.get_spans(thread_id)
    recent_mw_names = set()
    for s in existing_spans[-20:]:  # 只检查最近 20 个 span
        if s.get("type") == "middleware":
            s_meta = s.get("metadata", {})
            s_input = s.get("input_data", {})
            s_phase = s_input.get("phase", "") or s_meta.get("phase", "")
            s_name = s_meta.get("middleware_name", "")
            if s_phase == phase and s_name:
                recent_mw_names.add(s_name)

    for mw_name in mw_list:
        if mw_name in recent_mw_names:
            continue  # 已被 MiddlewareTracingWrapper 记录，跳过
        tracing_middleware._add_to_thread(
            thread_id, "middleware", f"mw:{mw_name}", 0,
            metadata={
                "middleware_name": mw_name,
                "phase": phase,
                "has_effect": False,
            },
            input_data={
                "middleware": mw_name,
                "phase": phase,
            },
            output_data={
                "has_effect": False,
                "duration_ms": 0,
            },
            detail=f"{mw_name}.{phase} → 无变更",
        )


# ModelName → 事件分流（对齐 apps-agent ModelNameType）
CUSTOM_MODEL_NAMES = frozenset({
    "component", "relevantData", "searchResults", "link",
})
TEXT_MODEL_NAMES = frozenset({
    "textResult", "explanation", "longText",
})


class AGUIConverter:
    """将 LangGraph astream_events 映射为 AG-UI 协议事件"""

    def __init__(
        self,
        run_id: str,
        thread_id: str,
        history_messages: list[dict] | None = None,
        *,
        parent_run_id: str | None = None,
        emit_legacy_reasoning: bool = True,
        skill_registry: Any | None = None,
        conversation_type: int | None = None,
    ) -> None:
        self.run_id = run_id
        self.thread_id = thread_id
        self._parent_run_id = parent_run_id
        self._emit_legacy_reasoning = emit_legacy_reasoning
        self._skill_registry = skill_registry
        self._conversation_type = conversation_type  # 1,2=chat; 3=定时器; 4=调试; 5=临时; 6=嵌入页面

        # long_text 标签解析器（对齐 apps-agent）
        from .long_text import LongTextParser
        self._long_text_parser = LongTextParser(run_id=run_id)  # SkillRegistry，用于查询 skill context 模式

        # 步骤计数
        self._step_index = 0
        # 文本流
        self._text_active = False
        self._text_message_id = ""
        # 推理流
        self._reasoning_active = False
        self._reasoning_msg_active = False
        self._reasoning_id = ""      # REASONING_START/END 的 message_id
        self._reasoning_msg_id = ""  # REASONING_MESSAGE_* 的 message_id
        # 工具调用流
        self._tool_started: set[str] = set()
        # 根 run_id（用于子 Agent 事件过滤）
        self._root_run_id: str | None = None
        # 消息缓冲
        self._messages: list[dict] = list(history_messages or [])
        # ── Fork Skill 输出控制 ──
        # 标记是否抑制后续 LLM 文本输出（silent 模式）
        self._suppress_next_text: bool = False
        # silent 模式：硬抑制 — 完全屏蔽 LLM 文本，直到下一次 tool call 或 run 结束
        self._hard_suppress_text: bool = False
        # doc_stream 模式：硬抑制对话区文本，但通过 doc_stream 事件流式推送到右侧面板
        self._doc_stream_mode: bool = False
        # 抑制计数器（累计被抑制的字符数，超过阈值时解除）
        self._suppress_char_count: int = 0
        # 抑制阈值（仅 summarize/continue 的软抑制下生效）
        self._suppress_max_chars: int = 200
        # 最近一次 skill_result 直出的内容 hash（用于去重）
        self._last_skill_output_hash: int = 0
        # 最近一次 skill_result 直出的内容前缀（用于 LLM stream 去重）
        self._last_skill_output_prefix: str = ""
        # LLM stream 累计文本缓冲区（用于检测与 skill_result 重复）
        self._llm_text_buffer: str = ""
        # LLM stream 去重：是否正在检测重复
        self._dedup_checking: bool = False
        # ── REF 标记缓冲区（处理流式 chunk 中跨 chunk 的 <!-- REF: ... --> 标记）──
        self._ref_buffer: str = ""
        self._ref_buffering: bool = False
        # ── LLM 输入消息缓存（on_chat_model_start 时捕获，on_chat_model_end 时写入 span）──
        self._llm_input_preview: list[dict] = []

    # ═══════════════════════════════════════════════════════════
    # 主入口
    # ═══════════════════════════════════════════════════════════

    async def convert(
        self, astream_events: AsyncGenerator[dict[str, Any], None]
    ) -> AsyncGenerator[m.AGUIEvent, None]:
        """主方法：遍历 LangGraph 事件并映射为 AG-UI 事件"""
        yield m.run_started(self.run_id, self.thread_id,
                            parent_run_id=self._parent_run_id)

        # 会话初始化发射历史消息快照
        if self._messages:
            yield m.messages_snapshot(list(self._messages))

        try:
            async for event in astream_events:
                if self._root_run_id is None:
                    self._root_run_id = event.get("run_id")
                async for agui_event in self._map_event(event):
                    yield agui_event
        except Exception as exc:
            logger.exception("AGUIConverter.convert: unhandled error")
            async for e in self._close_active_streams():
                yield e
            yield m.run_error("INTERNAL_ERROR", code=type(exc).__name__)
            return

        async for e in self._close_active_streams():
            yield e
        yield m.run_finished(self.run_id, self.thread_id)

    # ═══════════════════════════════════════════════════════════
    # 分发
    # ═══════════════════════════════════════════════════════════

    async def _map_event(self, event: dict) -> AsyncGenerator[m.AGUIEvent, None]:
        kind = event.get("event", "")
        data = event.get("data", {})
        name = event.get("name", "")

        # on_custom_event 不走子 Agent 过滤（允许穿透）
        if kind == "on_custom_event":
            async for e in self._handle_custom_event(name, data):
                yield e
            return

        # 过滤子 Agent 的事件（全部过滤，子 Agent 的执行细节由 mw_span 展示）
        parent_ids = event.get("parent_ids", [])
        is_sub_agent = self._root_run_id and parent_ids and parent_ids[0] != self._root_run_id
        if is_sub_agent:
            return

        if kind == "on_chat_model_stream":
            async for e in self._handle_chat_stream(event, data):
                yield e
        elif kind == "on_chat_model_start":
            # 记录 LLM 推理开始 — 缓存完整输入上下文，span 在 on_chat_model_end 时统一写入
            if not is_sub_agent and len(parent_ids) <= 2:
                self._step_index += 1
                # 提取 LLM 完整输入上下文（所有消息）
                try:
                    raw_input = data.get("input", {}) or {}
                    msgs = raw_input.get("messages") or []
                    if msgs and isinstance(msgs[0], list):
                        msgs = msgs[0]
                    preview = []
                    for m in msgs:
                        m_type = getattr(m, "type", None) or (m.get("type") if isinstance(m, dict) else "unknown")
                        m_content = getattr(m, "content", None)
                        if m_content is None and isinstance(m, dict):
                            m_content = m.get("content", "")
                        if isinstance(m_content, list):
                            m_content = "".join(c.get("text", "") if isinstance(c, dict) else str(c) for c in m_content)
                        m_content = str(m_content or "")
                        # system prompt 保留更多（2000字符），其他消息 1000 字符
                        max_len = 2000 if m_type == "system" else 1000
                        if len(m_content) > max_len:
                            m_content = m_content[:max_len] + f"... (截断，原始{len(m_content)}字符)"
                        # tool message 额外提取 tool name
                        m_name = getattr(m, "name", None) or (m.get("name") if isinstance(m, dict) else "")
                        entry = {"role": m_type, "content": m_content}
                        if m_name:
                            entry["name"] = m_name
                        preview.append(entry)
                    self._llm_input_preview = preview
                except Exception:
                    self._llm_input_preview = []
        elif kind == "on_chat_model_end":
            # 记录完整的 llm_call span（含推理结果：tool_calls / is_final / knowledge_refs / 输入输出）
            if not is_sub_agent and len(parent_ids) <= 2:
                output = data.get("output", None)
                tool_calls = []
                is_final = True
                knowledge_refs = []
                output_preview = ""
                token_info = {}

                if output and hasattr(output, "tool_calls") and output.tool_calls:
                    tool_calls = [tc.get("name", "") for tc in output.tool_calls if isinstance(tc, dict)]
                    is_final = False

                # 提取输出内容预览
                if output and hasattr(output, "content"):
                    content_text = output.content if isinstance(output.content, str) else str(output.content)
                    knowledge_refs = self._parse_knowledge_refs(content_text)
                    output_preview = content_text[:800]

                # 提取 token 用量
                if output and hasattr(output, "usage_metadata") and output.usage_metadata:
                    um = output.usage_metadata
                    token_info = {
                        "input_tokens": um.get("input_tokens", 0),
                        "output_tokens": um.get("output_tokens", 0),
                    }

                try:
                    from src.middleware.tracing import tracing_middleware
                    is_parallel = len(tool_calls) > 1
                    desc = f"第{self._step_index}轮: {'生成最终回复 ✅' if is_final else ('并行调用 ' if is_parallel else '调用 ') + ', '.join(tool_calls)}"
                    if knowledge_refs:
                        desc += f" | 引用: {', '.join(knowledge_refs)}"
                    tracing_middleware._add_to_thread(
                        self.thread_id, "llm_call", desc, 0,
                        {
                            "iteration": self._step_index,
                            "tool_calls": tool_calls,
                            "is_final": is_final,
                            "is_parallel": is_parallel,
                            "tool_call_count": len(tool_calls),
                            "knowledge_refs": knowledge_refs,
                            "output_preview": output_preview[:300],
                            **token_info,
                        },
                        input_data={
                            "iteration": self._step_index,
                            "messages_preview": getattr(self, '_llm_input_preview', []),
                            "message_count": len(getattr(self, '_llm_input_preview', [])),
                        },
                        output_data={
                            "tool_calls": tool_calls,
                            "is_final": is_final,
                            "is_parallel": is_parallel,
                            "knowledge_refs": knowledge_refs,
                            "output": output_preview[:500],
                            "tokens": token_info if token_info else {},
                        },
                        detail=desc,
                    )
                except Exception:
                    logger.exception("converter.py L301 异常")
            # after_model 中间件（OutputValidation/LoopDetection/SubagentLimit）
            # 已由 MiddlewareTracingWrapper 在 LangGraph 内部自动记录，无需手动补充
        elif kind == "on_chain_start" and name.startswith(SKILL_CHAIN_PREFIX):
            async for e in self._handle_skill_start(name):
                yield e
        elif kind == "on_chain_end" and name.startswith(SKILL_CHAIN_PREFIX):
            async for e in self._handle_skill_end(name, data):
                yield e
        elif kind == "on_tool_start":
            async for e in self._handle_tool_start(event, data, name):
                yield e
        elif kind == "on_tool_end":
            async for e in self._handle_tool_end(event, data, name):
                yield e

    # ═══════════════════════════════════════════════════════════
    # Chat model stream → 文本 / 推理 / 工具调用
    # ═══════════════════════════════════════════════════════════

    async def _handle_chat_stream(self, event: dict, data: dict) -> AsyncGenerator[m.AGUIEvent, None]:
        chunk = data.get("chunk")
        if chunk is None:
            return

        # 1. 工具调用 chunks（如果模型返回 tool_call_chunks）
        tool_chunks = getattr(chunk, "tool_call_chunks", None) or []
        for tc in tool_chunks:
            async for e in self._handle_tool_chunk(tc):
                yield e

        content = getattr(chunk, "content", "")

        # 2. thinking-model: content 是 list（ anthropic / qwen3 等）
        if isinstance(content, list):
            for block in content:
                if isinstance(block, dict):
                    btype = block.get("type")
                    if btype == "thinking":
                        text = block.get("thinking", "") or block.get("text", "")
                        if text:
                            async for e in self._emit_reasoning(text):
                                yield e
                    elif btype == "text":
                        async for e in self._emit_text(block.get("text", "")):
                            yield e
            return

        # 3. 普通文本 chunk
        if content:
            async for e in self._emit_text(content):
                yield e

    async def _handle_tool_chunk(self, tc: dict) -> AsyncGenerator[m.AGUIEvent, None]:
        """处理 chunk.tool_call_chunks 里的单个 tool call 分片。

        LangChain 的 tool_call_chunks 结构：
          {"name": str | None, "args": str | None, "id": str | None, "index": int}
        """
        if not isinstance(tc, dict):
            return
        tool_call_id = tc.get("id") or ""
        if not tool_call_id:
            return

        # 第一次见到此 tool_call_id → 发 TOOL_CALL_START
        if tool_call_id not in self._tool_started:
            self._tool_started.add(tool_call_id)
            # 切换流：关闭文本/推理
            async for e in self._close_text_stream():
                yield e
            async for e in self._close_reasoning_stream():
                yield e
            # 新 tool call 开始 → 解除文本抑制（LLM 决策了新动作）
            # 注意：只有当 tool_call 有明确的 name 时才解除硬抑制，
            # 避免 LLM streaming 中的虚假 tool_call_chunk 误解除 skill 直出后的抑制
            tool_name = tc.get("name") or ""
            if tool_name:
                # skills_tool 特殊处理：主动激活硬抑制
                # 子 Agent 的 LLM stream 会泄漏到主事件流，需要在 tool 开始时就抑制
                # 等到 on_tool_end 时通过 component_complete 或解除抑制来输出
                if tool_name == "skills_tool":
                    self._hard_suppress_text = True
                    # 判断 skill context 模式：仅 fork 模式才启用 doc_stream
                    # inline 模式只是返回 prompt 文本，不需要流式推送到右侧面板
                    _skill_name_for_mode = ""
                    try:
                        args_str = tc.get("args") or ""
                        if args_str and "skill_name" in args_str:
                            import json as _json
                            _parsed = _json.loads(args_str) if isinstance(args_str, str) else args_str
                            _skill_name_for_mode = _parsed.get("skill_name", "") if isinstance(_parsed, dict) else ""
                    except Exception:
                        pass
                    _is_fork = False
                    if _skill_name_for_mode and self._skill_registry:
                        _sk = self._skill_registry.get(_skill_name_for_mode)
                        if _sk is None:
                            alt = _skill_name_for_mode.replace('-', '_') if '-' in _skill_name_for_mode else _skill_name_for_mode.replace('_', '-')
                            _sk = self._skill_registry.get(alt)
                        if _sk and _sk.context == "fork":
                            _is_fork = True
                    self._doc_stream_mode = _is_fork  # 仅 fork 模式流式推送到右侧面板
                elif not self._hard_suppress_text:
                    # 只有当前没有硬抑制时才重置（避免子 Agent 工具调用解除 skills_tool 的抑制）
                    self._suppress_next_text = False
                    self._suppress_char_count = 0
                    self._dedup_checking = False
                    self._llm_text_buffer = ""
            yield m.tool_call_start(tool_call_id, tool_call_name=tool_name)

        # args delta
        args_delta = tc.get("args")
        if args_delta:
            yield m.tool_call_args(tool_call_id, args_delta)

    async def _emit_text(self, content: str) -> AsyncGenerator[m.AGUIEvent, None]:
        if not content:
            return

        # ── 剥离知识引用标记（处理流式 chunk 跨越 [KB_REF: ...] 的情况）──
        content = self._strip_ref_markers(content)
        if not content:
            return

        # ── Fork Skill 后续文本抑制 ──
        # silent 模式：硬抑制 — 完全屏蔽，直到下一次 tool call 或 run 结束
        if self._hard_suppress_text:
            # doc_stream 模式：不在对话区显示，但流式推送到右侧面板
            if self._doc_stream_mode:
                yield m.custom_event("doc_stream", {"delta": content})
            else:
                logger.debug("[AGUIConverter] _emit_text SUPPRESSED (hard): %s", content[:80])
            return

        # ── LLM stream 与 skill_result 直出内容去重 ──
        # 如果 skill_result 已输出了报告，检测 LLM stream 是否在重复相同内容
        if self._dedup_checking and self._last_skill_output_prefix:
            self._llm_text_buffer += content
            # 累计足够长度后做比较
            if len(self._llm_text_buffer) >= 60:
                buffer_stripped = self._llm_text_buffer.strip().lstrip("#").strip()
                prefix_stripped = self._last_skill_output_prefix.strip().lstrip("#").strip()
                # 如果 LLM 输出的前缀与 skill_result 内容前缀高度匹配，判定为重复
                match_len = min(len(buffer_stripped), len(prefix_stripped), 60)
                if match_len > 20 and buffer_stripped[:match_len] == prefix_stripped[:match_len]:
                    # LLM 在重复 skill_result 已输出的内容 → 启动硬抑制
                    logger.info(
                        "[AGUIConverter] _emit_text DEDUP: LLM stream repeating skill_result content, "
                        "activating hard suppress. buffer[:60]=%s",
                        buffer_stripped[:60],
                    )
                    self._hard_suppress_text = True
                    self._dedup_checking = False
                    self._llm_text_buffer = ""
                    return
                else:
                    # 不是重复内容，停止检测，正常输出（补发 buffer 中暂存的内容）
                    self._dedup_checking = False
                    # 用 buffer 内容替代当前 content 输出（因为之前的 chunks 被暂存了）
                    content = self._llm_text_buffer
                    self._llm_text_buffer = ""
            else:
                # buffer 不够长，暂存不输出，等待更多 chunks
                return

        # summarize/continue 模式：软抑制 — 噪音过滤
        if self._suppress_next_text:
            if self._is_post_skill_noise(content):
                return
            # LLM 产出了实质性内容（非噪音），解除抑制并正常输出
            self._suppress_next_text = False

        # 切换：关闭推理流
        async for e in self._close_reasoning_stream():
            yield e

        # <long_text> 标签检测（对齐 apps-agent）
        if self._long_text_parser.active or "<long_text" in content or self._long_text_parser._pending:
            async for ev in self._long_text_parser.feed(content):
                t = ev.type if isinstance(ev.type, str) else ev.type.value
                if t == "__plain_text__":
                    # 普通文本正常输出
                    text = ev.data.get("text", "")
                    if text:
                        if not self._text_active:
                            self._text_active = True
                            self._text_message_id = uuid.uuid4().hex[:12]
                            yield m.text_message_start(self._text_message_id)
                        yield m.text_message_content(self._text_message_id, text)
                elif t == "__close_text__":
                    # 关闭文本流
                    async for e in self._close_text_stream():
                        yield e
                else:
                    # ACTIVITY_SNAPSHOT 等事件直接透传
                    yield ev
            return

        # 正常文本输出（无 long_text 标签）
        if not self._text_active:
            self._text_active = True
            self._text_message_id = uuid.uuid4().hex[:12]
            yield m.text_message_start(self._text_message_id)

        yield m.text_message_content(self._text_message_id, content)

    async def _emit_reasoning(self, text: str) -> AsyncGenerator[m.AGUIEvent, None]:
        if not text:
            return
        # 切换：关闭文本流
        async for e in self._close_text_stream():
            yield e
        if not self._reasoning_active:
            self._reasoning_active = True
            self._reasoning_id = uuid.uuid4().hex[:12]
            yield m.reasoning_start(self._reasoning_id)
            # 旧事件兼容
            if self._emit_legacy_reasoning:
                yield m.AGUIEvent(type=m.AGUIEventType.REASONING_STARTED)
        if not self._reasoning_msg_active:
            self._reasoning_msg_active = True
            self._reasoning_msg_id = uuid.uuid4().hex[:12]
            yield m.reasoning_message_start(self._reasoning_msg_id)
        yield m.reasoning_message_content(self._reasoning_msg_id, text)
        if self._emit_legacy_reasoning:
            yield m.AGUIEvent(type=m.AGUIEventType.REASONING_CONTENT, data={"delta": text})

    # ═══════════════════════════════════════════════════════════
    # Tool 事件（on_tool_start / on_tool_end 作为兜底）
    # ═══════════════════════════════════════════════════════════

    async def _handle_tool_start(self, event: dict, data: dict, tool_name: str) -> AsyncGenerator[m.AGUIEvent, None]:
        """LangChain on_tool_start — 若 chat_model_stream 已发过 TOOL_CALL_START 则跳过。"""
        tool_call_id = event.get("run_id", "")
        if tool_call_id in self._tool_started:
            return
        self._tool_started.add(tool_call_id)
        async for e in self._close_text_stream():
            yield e
        async for e in self._close_reasoning_stream():
            yield e
        # 新 tool call 开始 → 解除文本抑制（on_tool_start 表示 tool 确实被调用了）
        if tool_name:
            # skills_tool 特殊处理：主动激活硬抑制（子 Agent LLM stream 泄漏防护）
            if tool_name == "skills_tool":
                self._hard_suppress_text = True
                # 判断 skill context 模式：仅 fork 模式才启用 doc_stream
                _skill_name_for_mode = ""
                try:
                    raw_input = data.get("input", {})
                    if isinstance(raw_input, dict):
                        _skill_name_for_mode = raw_input.get("skill_name", "")
                    elif isinstance(raw_input, str):
                        import json as _json
                        _parsed = _json.loads(raw_input)
                        _skill_name_for_mode = _parsed.get("skill_name", "") if isinstance(_parsed, dict) else ""
                except Exception:
                    pass
                _is_fork = False
                if _skill_name_for_mode and self._skill_registry:
                    _sk = self._skill_registry.get(_skill_name_for_mode)
                    if _sk is None:
                        alt = _skill_name_for_mode.replace('-', '_') if '-' in _skill_name_for_mode else _skill_name_for_mode.replace('_', '-')
                        _sk = self._skill_registry.get(alt)
                    if _sk and _sk.context == "fork":
                        _is_fork = True
                self._doc_stream_mode = _is_fork
            elif not self._hard_suppress_text:
                # 只有当前没有硬抑制时才重置（避免子 Agent 工具调用解除 skills_tool 的抑制）
                self._suppress_next_text = False
                self._suppress_char_count = 0
                self._dedup_checking = False
                self._llm_text_buffer = ""
        yield m.tool_call_start(tool_call_id, tool_call_name=tool_name)

    async def _handle_tool_end(self, event: dict, data: dict, tool_name: str) -> AsyncGenerator[m.AGUIEvent, None]:
        tool_call_id = event.get("run_id", "")
        output = data.get("output", "")
        # 提取 ToolMessage 的 content（避免序列化问题）
        if hasattr(output, "content"):
            output = output.content if isinstance(output.content, str) else str(output.content)
        elif not isinstance(output, str):
            output = str(output)

        # ── Fork Skill 输出控制：检测 [SKILL_DONE:*] 标记 ──
        if "[SKILL_DONE:" in output:
            if "[SKILL_DONE:silent]" in output:
                self._hard_suppress_text = True
                # 如果 doc_stream 模式仍活跃，发送结束信号
                if self._doc_stream_mode:
                    self._doc_stream_mode = False
                    yield m.custom_event("doc_stream_end", {"status": "complete"})
                self._suppress_next_text = False
                logger.info("[AGUIConverter] tool_end detected SKILL_DONE:silent, hard suppress ON")
            elif "[SKILL_DONE:summarize]" in output:
                self._hard_suppress_text = False
                if self._doc_stream_mode:
                    self._doc_stream_mode = False
                    yield m.custom_event("doc_stream_end", {"status": "complete"})
                self._suppress_next_text = True
                self._suppress_char_count = 0
            elif "[SKILL_DONE:passthrough]" in output:
                # passthrough 模式：skill_result dispatch 失败，完整结果在 tool output 中
                # 检查该 skill 的 output_mode，如果不是 text 则直接渲染并抑制 LLM
                skill_content = output.split("\n\n", 1)[1] if "\n\n" in output else output
                # 剥离知识引用标记
                skill_content = self._strip_ref_markers_full(skill_content)
                # 从 output 中提取 skill_apikey
                import re as _re
                _skill_match = _re.search(r"\[SKILL_DONE:passthrough\]\s*(\S+)", output)
                _skill_apikey = _skill_match.group(1) if _skill_match else ""
                _output_mode = self._resolve_output_mode(_skill_apikey) if _skill_apikey else "text"

                if _output_mode == "card" and skill_content:
                    # 直接渲染为 doc_card，抑制 LLM 后续输出
                    title = skill_content.split("\n")[0][:60].lstrip("# ").strip()
                    yield m.custom_event("component_complete", {
                        "apikey": "doc_card",
                        "state": "complete",
                        "data": {"title": title, "content": skill_content, "skill_apikey": _skill_apikey},
                    })
                    self._hard_suppress_text = True
                    self._last_skill_output_hash = hash(skill_content)
                    self._doc_stream_mode = False  # skill 完成
                    logger.info("[AGUIConverter] tool_end SKILL_DONE:passthrough → card mode, emitted component_complete, hard suppress ON")
                elif _output_mode in ("component", "table") and skill_content:
                    # 非 text 模式：抑制 LLM 输出（组件渲染由前端处理）
                    self._hard_suppress_text = True
                    self._last_skill_output_hash = hash(skill_content)
                    self._doc_stream_mode = False
                    logger.info("[AGUIConverter] tool_end SKILL_DONE:passthrough → %s mode, hard suppress ON", _output_mode)
                else:
                    # text 模式或无法识别：解除硬抑制，让 LLM 正常输出
                    self._hard_suppress_text = False
                    self._doc_stream_mode = False
                    self._dedup_checking = True
                    self._llm_text_buffer = ""
        elif tool_name == "skills_tool":
            # ── Inline Skill：skills_tool 返回 prompt 文本（无 SKILL_DONE 标记）──
            # inline 模式下 LLM 会继续执行工具调用并最终生成文本回复，
            # 不应该走 doc_stream 模式，解除硬抑制让后续文本正常输出
            self._hard_suppress_text = False
            self._doc_stream_mode = False
            self._suppress_next_text = False
            self._dedup_checking = False
            self._llm_text_buffer = ""
            logger.info("[AGUIConverter] tool_end skills_tool (inline mode): suppress released")

        # RESULT + END
        yield m.tool_call_result(tool_call_id, content=output, role="tool")
        yield m.tool_call_end(tool_call_id)
        self._tool_started.discard(tool_call_id)

    # ═══════════════════════════════════════════════════════════
    # Skill chain → STEP 事件
    # ═══════════════════════════════════════════════════════════

    async def _handle_skill_start(self, name: str) -> AsyncGenerator[m.AGUIEvent, None]:
        async for e in self._close_all_streams():
            yield e
        skill_apikey = name[len(SKILL_CHAIN_PREFIX):]
        step_name = skill_apikey
        # 查询 skill 的 context 模式（inline/fork）
        skill_context = self._resolve_skill_context(skill_apikey)

        # 如果 skill 的 output_mode 不是 text/streaming，抑制子 Agent 的 LLM stream
        # （子 Agent 的最终输出将通过 _handle_skill_end 以正确的模式渲染）
        output_mode = self._resolve_output_mode(skill_apikey)
        if output_mode in ("card", "component", "table"):
            self._hard_suppress_text = True
            logger.info("[AGUIConverter] skill_start %s: output_mode=%s, suppressing text stream",
                        skill_apikey, output_mode)

        yield m.step_started(step_name)
        yield m.step_metadata(step_name, skill_apikey=skill_apikey,
                              step_index=self._step_index, phase="started",
                              skill_context=skill_context)

    async def _handle_skill_end(self, name: str, data: dict) -> AsyncGenerator[m.AGUIEvent, None]:
        skill_apikey = name[len(SKILL_CHAIN_PREFIX):]
        step_name = skill_apikey
        output = data.get("output", {})
        status = "failed" if isinstance(output, dict) and output.get("error") else "completed"
        skill_context = self._resolve_skill_context(skill_apikey)

        # 根据 output_mode 决定事件通道
        output_mode = self._resolve_output_mode(skill_apikey)

        if status == "completed" and output:
            output_text = str(output) if not isinstance(output, str) else output

            # ── 剥离知识引用标记 ──
            output_text = self._strip_ref_markers_full(output_text)

            # 去重：如果此内容已通过 skill_result 直出，跳过渲染（避免双重输出）
            content_hash = hash(output_text)
            if content_hash == self._last_skill_output_hash and self._last_skill_output_hash != 0:
                logger.info("[AGUIConverter] _handle_skill_end DEDUP: content already output via skill_result, skipping")
            elif output_mode == "text" or output_mode == "streaming":
                # 走 TEXT_MESSAGE 通道 → 前端渲染为 Markdown 文本气泡
                async for e in self._emit_text(output_text):
                    yield e
            elif output_mode == "card":
                # 走 CUSTOM(component_complete) + 内置 doc_card
                title = output_text.split("\n")[0][:60].lstrip("# ").strip()
                yield m.custom_event("component_complete", {
                    "apikey": "doc_card",
                    "state": "complete",
                    "data": {"title": title, "content": output_text, "skill_apikey": skill_apikey},
                })
                # 记录 hash 防止 skill_result 重复输出 + 激活硬抑制防止 LLM 重复
                self._last_skill_output_hash = hash(output_text)
                self._last_skill_output_prefix = output_text[:200].strip()
                self._hard_suppress_text = True
                self._dedup_checking = True
            elif output_mode == "component":
                # 走 CUSTOM(skill_output) → Renderer 匹配组件
                comp_apikey = self._resolve_component_apikey(skill_apikey)
                yield m.custom_event("skill_output",
                                     {"skill_apikey": skill_apikey, "data": output})
            elif output_mode == "table":
                # 走 CUSTOM(component_data)
                yield m.custom_event("component_data", {
                    "model_name": "searchResults",
                    "skill_apikey": skill_apikey,
                    "data": output if isinstance(output, (dict, list)) else {"value": output},
                })
            else:
                # auto / 兜底：走原有 skill_output 路径
                yield m.custom_event("skill_output",
                                     {"skill_apikey": skill_apikey, "data": output})

        yield m.step_metadata(step_name, skill_apikey=skill_apikey,
                              step_index=self._step_index, status=status,
                              phase="finished", skill_context=skill_context)
        yield m.step_finished(step_name)
        self._step_index += 1
        yield m.messages_snapshot(list(self._messages))

    def _resolve_output_mode(self, skill_apikey: str) -> str:
        """从 SkillRegistry 获取 Skill 的 output_mode。"""
        if self._skill_registry is None:
            return "text"
        try:
            skill = self._skill_registry.get(skill_apikey)
            if skill:
                return getattr(skill, "output_mode", "text") or "text"
        except Exception:
            logger.exception("_resolve_output_mode 异常")
        return "text"

    def _resolve_component_apikey(self, skill_apikey: str) -> str:
        """从 SkillRegistry 获取 Skill 的 component_apikey。"""
        if self._skill_registry is None:
            return ""
        try:
            skill = self._skill_registry.get(skill_apikey)
            if skill:
                return getattr(skill, "component_apikey", "") or ""
        except Exception:
            logger.exception("_resolve_component_apikey 异常")
        return ""

    def _resolve_skill_context(self, skill_apikey: str) -> str | None:
        """从 SkillRegistry 查询 skill 的 context 模式（inline/fork）。"""
        if self._skill_registry is None:
            return None
        try:
            skill = self._skill_registry.get(skill_apikey)
            if skill:
                return getattr(skill, 'context', None) or 'inline'
        except Exception:
            logger.exception("_resolve_skill_context 异常")
        return None

    @staticmethod
    def _parse_knowledge_refs(content: str) -> list[str]:
        """从 LLM 输出中解析知识文件引用标记。

        支持两种格式：
        - 新格式: [KB_REF: file1.md, file2.md]
        - 旧格式: <!-- REF: file1.md, file2.md -->
        返回: ["file1.md", "file2.md"]
        """
        import re
        refs = []
        # 新格式
        for match in re.findall(r'\[KB_REF:\s*(.+?)\]', content):
            for ref in match.split(","):
                ref = ref.strip()
                if ref and ref not in refs:
                    refs.append(ref)
        # 旧格式（兼容）
        if not refs:
            for match in re.findall(r'<!--\s*REF:\s*(.+?)\s*-->', content):
                for ref in match.split(","):
                    ref = ref.strip()
                    if ref and ref not in refs:
                        refs.append(ref)
        return refs

    def _strip_ref_markers(self, content: str) -> str:
        """从流式 chunk 中剥离 [KB_REF: ...] 标记。

        [KB_REF: ...] 格式的优势：
        - 不会被浏览器当作 HTML 注释解析
        - 不会被 Markdown 渲染器处理
        - 单行格式，流式场景下容易处理（按行缓冲即可）
        """
        import re

        # 如果正在缓冲（上一个 chunk 留下了不完整的 [KB_REF 前缀）
        if self._ref_buffering:
            self._ref_buffer += content
            # 检查缓冲区是否包含完整的 ] 结束标记
            if ']' in self._ref_buffer:
                # 完整标记已到达，剥离
                result = re.sub(r'\[KB_REF:.*?\]\s*', '', self._ref_buffer)
                self._ref_buffer = ""
                self._ref_buffering = False
                return result
            # 缓冲区过长（>300 字符）说明不是 KB_REF 标记，释放
            if len(self._ref_buffer) > 300:
                result = self._ref_buffer
                self._ref_buffer = ""
                self._ref_buffering = False
                return result
            # 继续缓冲，不输出
            return ""

        # 正常模式：检查是否包含完整标记
        full_pattern = r'\[KB_REF:.*?\]\s*'
        if re.search(full_pattern, content):
            return re.sub(full_pattern, '', content)

        # 检查是否包含不完整的 [KB_REF 开头但没有 ]（标记跨 chunk）
        if '[KB_REF:' in content and ']' not in content[content.index('[KB_REF:'):]:
            idx = content.index('[KB_REF:')
            safe_part = content[:idx]
            self._ref_buffer = content[idx:]
            self._ref_buffering = True
            return safe_part

        return content

    @staticmethod
    def _strip_ref_markers_full(content: str) -> str:
        """从完整文本中剥离 [KB_REF: ...] 标记（非流式场景）。

        用于 skill_result / skill_end 等一次性获得完整内容的场景。
        同时兼容旧格式 <!-- REF: ... --> 以防残留。
        """
        import re
        content = re.sub(r'\[KB_REF:.*?\]\s*', '', content)
        content = re.sub(r'<!--\s*REF:.*?-->\s*', '', content)
        return content

    # ═══════════════════════════════════════════════════════════
    # on_custom_event 适配层（Skill / Tool / Middleware 自定义事件）
    # ═══════════════════════════════════════════════════════════

    async def _handle_custom_event(self, name: str, data: dict) -> AsyncGenerator[m.AGUIEvent, None]:
        """按命名空间约定分发自定义事件。

        - agent_text       — 文本增量 → 走 TEXT_MESSAGE 三段式
        - agent_data       — 结构化数据 → 先关文本流，再发 CUSTOM(component_data)
        - a2ui.*           — A2UI 操作消息 → 透传 CUSTOM(a2ui.*)
        - state.patch      — 业务状态 JSON Patch → STATE_DELTA
        - skill.output     — 含 model_name 的 Skill 产出 → 按 ModelName 分流
        - 其他             — 原样 CUSTOM 透传
        """
        if not isinstance(data, dict):
            data = {"value": data}

        if name == "agent_text":
            content = data.get("content", "") if isinstance(data, dict) else ""
            if content:
                # 去重：如果此内容已通过 skill_result 输出过，跳过
                content_hash = hash(content)
                if content_hash == self._last_skill_output_hash and self._last_skill_output_hash != 0:
                    logger.info("[AGUIConverter] agent_text DEDUP: same as skill_result, skipping")
                    return
                # 如果硬抑制生效，跳过
                if self._hard_suppress_text:
                    logger.debug("[AGUIConverter] agent_text SUPPRESSED (hard)")
                    return
                async for e in self._emit_text(content):
                    yield e
            return

        if name == "agent_data":
            async for e in self._close_text_stream():
                yield e
            data_key = data.get("data_key", "")
            payload = data.get("payload", {}) if isinstance(data, dict) else {}
            if data_key:
                yield m.custom_event(
                    name="component_data",
                    value={
                        "data_key": data_key,
                        "data": payload.get("data") if isinstance(payload, dict) else payload,
                        "schema": payload.get("schema") if isinstance(payload, dict) else None,
                    },
                )
            return

        # A2UI 消息直通
        if name.startswith("a2ui."):
            async for e in self._close_text_stream():
                yield e
            yield m.custom_event(name=name, value=data)
            return

        if name == "state.patch":
            patch = data.get("patch", [])
            if patch:
                yield m.state_delta(patch)
            return

        if name == "skill.output":
            model_name = data.get("model_name")
            skill_apikey = data.get("skill_apikey", "")
            payload = data.get("data")
            async for e in self._convert_by_model_name(model_name, payload, skill_apikey):
                yield e
            return

        if name == "skill_result":
            async for e in self._handle_skill_result(data):
                yield e
            return

        # Fallback：其他 CUSTOM 原样透传
        yield m.custom_event(name=name, value=data)

    # ═══════════════════════════════════════════════════════════
    # ModelName 事件分流
    # ═══════════════════════════════════════════════════════════

    async def _convert_by_model_name(
        self,
        model_name: str | None,
        data: Any,
        skill_apikey: str,
    ) -> AsyncGenerator[m.AGUIEvent, None]:
        """根据 ModelName 决定走 CUSTOM 还是 TEXT_MESSAGE 通道。"""
        if model_name is None:
            # 未声明类型 → 交给 Renderer 通过 skill_output 路径处理
            yield m.custom_event("skill_output",
                                 {"skill_apikey": skill_apikey, "data": data})
            return

        if model_name in CUSTOM_MODEL_NAMES:
            if model_name == "component":
                apikey = data.get("actionApikey", "") if isinstance(data, dict) else ""
                yield m.custom_event("component_complete", {
                    "apikey": apikey,
                    "state": "complete",
                    "data": data,
                })
            else:
                yield m.custom_event("component_data", {
                    "model_name": model_name,
                    "skill_apikey": skill_apikey,
                    "data": data,
                })
            return

        if model_name in TEXT_MODEL_NAMES:
            if isinstance(data, dict):
                text = data.get("value") or data.get("text") or ""
            else:
                text = str(data or "")
            if text:
                async for e in self._emit_text(text):
                    yield e
            return

        # 未知类型 → 降级到 skill_output
        logger.warning("Unknown ModelName %r from skill %r; degrade to skill_output",
                       model_name, skill_apikey)
        yield m.custom_event("skill_output",
                             {"skill_apikey": skill_apikey, "data": data})

    # ═══════════════════════════════════════════════════════════
    # Fork Skill 直出结果处理
    # ═══════════════════════════════════════════════════════════

    async def _handle_skill_result(self, data: dict) -> AsyncGenerator[m.AGUIEvent, None]:
        """处理 skill_result 自定义事件 — 子 Agent 结果直出 + 主 Agent 行为控制。

        事件数据结构：
            skill_apikey: str — Skill 标识
            behavior: str — silent | summarize | continue | passthrough
            content: str — 子 Agent 完整输出
            summary: str — 摘要（供调试/日志）
            output_mode: str — text | card | component | table
        """
        skill_apikey = data.get("skill_apikey", "")
        behavior = data.get("behavior", "silent")
        content = data.get("content", "")
        output_mode = data.get("output_mode", "text")

        logger.info(
            "[AGUIConverter] skill_result received: skill=%s, behavior=%s, output_mode=%s, content_len=%d",
            skill_apikey, behavior, output_mode, len(content),
        )

        if not content:
            return

        # ── 剥离知识引用标记（完整内容，非流式）──
        content = self._strip_ref_markers_full(content)

        # 去重：如果相同内容已经通过 skill_result 输出过，跳过
        content_hash = hash(content)
        if content_hash == self._last_skill_output_hash and self._last_skill_output_hash != 0:
            logger.info("[AGUIConverter] skill_result DEDUP: same content already output, skipping")
            return
        self._last_skill_output_hash = content_hash
        # 记录前缀用于 LLM stream 去重（取前 200 字符，去除 Markdown 标记后比对）
        self._last_skill_output_prefix = content[:200].strip()
        # 激活 LLM stream 去重检测
        self._dedup_checking = True
        self._llm_text_buffer = ""

        # ── doc_stream 模式结束：skill_result 到达意味着子 Agent 已完成 ──
        # 如果之前通过 doc_stream 推送了流式内容，现在需要发送结束信号
        was_doc_stream = self._doc_stream_mode
        if self._doc_stream_mode:
            self._doc_stream_mode = False
            # 如果 output_mode 不是 card（card 模式会通过 component_complete(doc_card) 结束），
            # 需要显式发送 doc_stream_end 让前端完成文档渲染
            if output_mode != "card":
                yield m.custom_event("doc_stream_end", {"status": "complete", "skill_apikey": skill_apikey})

        # 1. 关闭当前活跃流（三流互斥）
        async for e in self._close_all_streams():
            yield e

        # 2. 按 output_mode 输出子 Agent 结果
        # 注意：即使之前通过 doc_stream 推送了内容，仍需通过正式通道输出最终结果。
        # 因为 doc_stream 推送的是子 Agent LLM 的流式中间输出，可能不完整或为空
        # （例如子 Agent 直接调用工具返回结果，没有 LLM 文本产出）。
        # 前端通过 textMsgFinalized 标志防止重复渲染。
        async for e in self._emit_skill_direct_output(skill_apikey, content, output_mode):
            yield e

        # 3. 根据 behavior 设置后续主 Agent 文本输出控制
        if behavior == "silent":
            # 硬抑制：完全屏蔽 LLM 后续文本，直到下次 tool call 或 run 结束
            self._hard_suppress_text = True
            self._suppress_next_text = False
            self._suppress_char_count = 0
        elif behavior == "summarize":
            # 软抑制：允许 LLM 产出简短总结，过滤噪音
            self._hard_suppress_text = False
            self._suppress_next_text = True
            self._suppress_char_count = 0
        elif behavior == "continue":
            # 不抑制：允许 LLM 继续决策（包括调下一个 tool）
            self._hard_suppress_text = False
            self._suppress_next_text = False
        else:
            self._hard_suppress_text = False
            self._suppress_next_text = False

    async def _emit_skill_direct_output(
        self,
        skill_apikey: str,
        content: str,
        output_mode: str,
    ) -> AsyncGenerator[m.AGUIEvent, None]:
        """子 Agent 结果直出 — 根据 output_mode 选择事件通道。

        与主 Agent 的 LLM 文本流独立，形成完整闭环。
        注意：直出内容必须绕过 _hard_suppress_text（因为直出是正当输出，不应被抑制）。
        """
        if output_mode == "text" or output_mode == "streaming":
            # 走 TEXT_MESSAGE 三段式，然后立即关闭（形成独立消息闭环）
            # 临时解除硬抑制以确保直出内容不被吞掉（skill_result 可能在 on_tool_end 之后到达）
            saved_hard_suppress = self._hard_suppress_text
            saved_dedup_checking = self._dedup_checking
            self._hard_suppress_text = False
            self._dedup_checking = False  # 直出内容本身不参与去重检测
            async for e in self._emit_text(content):
                yield e
            async for e in self._close_text_stream():
                yield e
            # 恢复硬抑制（后续 LLM 文本仍应被抑制）
            self._hard_suppress_text = saved_hard_suppress
            self._dedup_checking = saved_dedup_checking

        elif output_mode == "card":
            # 走 CUSTOM(component_complete) + 内置 doc_card
            title = content.split("\n")[0][:60].lstrip("# ").strip() if content else ""
            yield m.custom_event("component_complete", {
                "apikey": "doc_card",
                "state": "complete",
                "data": {
                    "title": title,
                    "content": content,
                    "skill_apikey": skill_apikey,
                },
            })

        elif output_mode == "component":
            # 走 CUSTOM(skill_output) → ProgressiveRenderer 匹配组件
            yield m.custom_event("skill_output",
                                 {"skill_apikey": skill_apikey, "data": content})

        elif output_mode == "table":
            # 走 CUSTOM(component_data) + searchResults 类型
            yield m.custom_event("component_data", {
                "model_name": "searchResults",
                "skill_apikey": skill_apikey,
                "data": content if isinstance(content, (dict, list)) else {"value": content},
            })

        else:
            # auto / 兜底：走文本通道
            async for e in self._emit_text(content):
                yield e
            async for e in self._close_text_stream():
                yield e

    # ═══════════════════════════════════════════════════════════
    # 流关闭（三流互斥）
    # ═══════════════════════════════════════════════════════════

    async def _close_text_stream(self) -> AsyncGenerator[m.AGUIEvent, None]:
        if self._text_active:
            self._text_active = False
            yield m.text_message_end(self._text_message_id)

    async def _close_reasoning_stream(self) -> AsyncGenerator[m.AGUIEvent, None]:
        if self._reasoning_msg_active:
            self._reasoning_msg_active = False
            yield m.reasoning_message_end(self._reasoning_msg_id)
        if self._reasoning_active:
            self._reasoning_active = False
            yield m.reasoning_end(self._reasoning_id)
            if self._emit_legacy_reasoning:
                yield m.AGUIEvent(type=m.AGUIEventType.REASONING_FINISHED)

    async def _close_all_streams(self) -> AsyncGenerator[m.AGUIEvent, None]:
        async for e in self._close_text_stream():
            yield e
        async for e in self._close_reasoning_stream():
            yield e
        # ── doc_stream 兜底：如果 doc_stream 模式仍活跃，发送结束信号让前端完成文档渲染 ──
        if self._doc_stream_mode:
            self._doc_stream_mode = False
            yield m.custom_event("doc_stream_end", {"status": "complete"})

    # 兼容老方法名
    _close_active_streams = _close_all_streams

    # ═══════════════════════════════════════════════════════════
    # Fork Skill 文本抑制辅助
    # ═══════════════════════════════════════════════════════════

    def _is_post_skill_noise(self, content: str) -> bool:
        """判断是否是 fork skill 执行后 LLM 的无用确认性回复。

        当 _suppress_next_text=True 时调用：
        - 累计字符数 < 阈值 且内容匹配噪音模式 → 返回 True（丢弃）
        - 累计字符数 >= 阈值 → 返回 False（可能是实质性内容，解除抑制）
        """
        self._suppress_char_count += len(content)

        # 超过阈值 → 解除抑制（LLM 可能在产出实质性内容）
        if self._suppress_char_count > self._suppress_max_chars:
            return False

        # 常见噪音模式检测
        trimmed = content.strip()
        if not trimmed:
            return True

        noise_patterns = (
            "好的", "以上是", "报告已", "分析完成", "执行完毕",
            "如上所示", "以上就是", "如有疑问", "希望对您有帮助",
            "如果您", "请问还有", "还有什么", "需要我",
            "已经为您", "上述", "综上",
        )
        # 短内容且匹配噪音模式 → 丢弃
        if len(trimmed) < 100 and any(p in trimmed for p in noise_patterns):
            return True

        # 极短内容（< 20字）大概率是确认性回复
        if len(trimmed) < 20:
            return True

        return False

    # ═══════════════════════════════════════════════════════════
    # 断线重连 / 初始化快照
    # ═══════════════════════════════════════════════════════════

    async def emit_reconnect_snapshot(
        self,
        messages: list[dict] | None = None,
        state_snapshot: dict | None = None,
        activities: list[dict] | None = None,
        parent_run_id: str | None = None,
    ) -> AsyncGenerator[m.AGUIEvent, None]:
        """断线重连首包（固定顺序，对齐设计 §2.7）：

        1. RUN_STARTED(parent_run_id)
        2. MESSAGES_SNAPSHOT
        3. STATE_SNAPSHOT
        4. ACTIVITY_SNAPSHOT × N（每个活跃 surface 一次）
        """
        yield m.run_started(self.run_id, self.thread_id,
                            parent_run_id=parent_run_id or self._parent_run_id)
        if messages:
            yield m.messages_snapshot(messages)
        if state_snapshot:
            yield m.state_snapshot(state_snapshot)
        for activity in (activities or []):
            yield m.activity_snapshot(
                message_id=activity.get("message_id", f"a2ui-{self.run_id[:8]}"),
                activity_type=activity.get("activity_type", "a2ui-surface"),
                content=activity.get("content", {}),
                replace=activity.get("replace", True),
            )

    def append_message(self, message: dict) -> None:
        """外部追加消息（用于 MESSAGES_SNAPSHOT 缓冲）"""
        self._messages.append(message)
