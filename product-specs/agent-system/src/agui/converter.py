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
    ) -> None:
        self.run_id = run_id
        self.thread_id = thread_id
        self._parent_run_id = parent_run_id
        self._emit_legacy_reasoning = emit_legacy_reasoning
        self._skill_registry = skill_registry  # SkillRegistry，用于查询 skill context 模式

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

        # 过滤子 Agent 的事件
        parent_ids = event.get("parent_ids", [])
        if self._root_run_id and parent_ids and parent_ids[0] != self._root_run_id:
            return

        if kind == "on_chat_model_stream":
            async for e in self._handle_chat_stream(event, data):
                yield e
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
            tool_name = tc.get("name") or ""
            yield m.tool_call_start(tool_call_id, tool_call_name=tool_name)

        # args delta
        args_delta = tc.get("args")
        if args_delta:
            yield m.tool_call_args(tool_call_id, args_delta)

    async def _emit_text(self, content: str) -> AsyncGenerator[m.AGUIEvent, None]:
        if not content:
            return
        # 切换：关闭推理流
        async for e in self._close_reasoning_stream():
            yield e
        # 开启文本流
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
        yield m.tool_call_start(tool_call_id, tool_call_name=tool_name)

    async def _handle_tool_end(self, event: dict, data: dict, tool_name: str) -> AsyncGenerator[m.AGUIEvent, None]:
        tool_call_id = event.get("run_id", "")
        output = data.get("output", "")
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

            if output_mode == "text" or output_mode == "streaming":
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
            return "auto"
        try:
            skill = self._skill_registry.get(skill_apikey)
            if skill:
                return getattr(skill, "output_mode", "auto") or "auto"
        except Exception:
            pass
        return "auto"

    def _resolve_component_apikey(self, skill_apikey: str) -> str:
        """从 SkillRegistry 获取 Skill 的 component_apikey。"""
        if self._skill_registry is None:
            return ""
        try:
            skill = self._skill_registry.get(skill_apikey)
            if skill:
                return getattr(skill, "component_apikey", "") or ""
        except Exception:
            pass
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
            pass
        return None

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

    # 兼容老方法名
    _close_active_streams = _close_all_streams

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
