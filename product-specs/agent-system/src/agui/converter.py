"""AG-UI Converter — LangGraph astream_events → AG-UI 标准事件流

对齐 v2 的 V2AGUIConverter：
- 三段式文本状态机（start → content → end）
- 推理内容（thinking model）支持
- 工具调用事件
- Skill 步骤事件
- 消息快照
- 子 Agent 事件过滤
"""
from __future__ import annotations

import logging
import uuid
from typing import Any, AsyncGenerator

from . import models as m

logger = logging.getLogger(__name__)

SKILL_CHAIN_PREFIX = "skill_"


class AGUIConverter:
    """将 LangGraph astream_events 映射为 AG-UI 协议事件"""

    def __init__(self, run_id: str, thread_id: str,
                 history_messages: list[dict] | None = None) -> None:
        self.run_id = run_id
        self.thread_id = thread_id
        self._step_index = 0
        self._text_active = False
        self._text_message_id = ""
        self._reasoning_active = False
        self._root_run_id: str | None = None
        self._messages: list[dict] = list(history_messages or [])

    async def convert(
        self, astream_events: AsyncGenerator[dict[str, Any], None]
    ) -> AsyncGenerator[m.AGUIEvent, None]:
        """主方法：遍历 LangGraph 事件并映射为 AG-UI 事件"""
        yield m.run_started(self.run_id, self.thread_id)

        # 会话初始化时发射历史消息快照
        if self._messages:
            yield m.messages_snapshot(list(self._messages))

        try:
            async for event in astream_events:
                if self._root_run_id is None:
                    self._root_run_id = event.get("run_id")
                async for agui_event in self._map_event(event):
                    yield agui_event
        except Exception as exc:
            async for e in self._close_active_streams():
                yield e
            yield m.run_error("INTERNAL_ERROR", str(exc))
            return

        async for e in self._close_active_streams():
            yield e
        yield m.run_finished(self.run_id, self.thread_id)

    async def _map_event(self, event: dict) -> AsyncGenerator[m.AGUIEvent, None]:
        kind = event.get("event", "")
        data = event.get("data", {})
        name = event.get("name", "")

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
            yield m.tool_call_start(event.get("run_id", uuid.uuid4().hex[:12]), name)
        elif kind == "on_tool_end":
            run_id = event.get("run_id", "")
            output = data.get("output", "")
            yield m.tool_call_result(run_id, output)
            yield m.tool_call_end(run_id)

    async def _handle_chat_stream(self, event: dict, data: dict) -> AsyncGenerator[m.AGUIEvent, None]:
        # 过滤子 Agent 的 LLM 事件
        parent_ids = event.get("parent_ids", [])
        if self._root_run_id and parent_ids and parent_ids[0] != self._root_run_id:
            return

        chunk = data.get("chunk")
        if chunk is None:
            return

        content = getattr(chunk, "content", "")

        # thinking model: content 是 list
        if isinstance(content, list):
            for block in content:
                if isinstance(block, dict):
                    if block.get("type") == "thinking":
                        text = block.get("thinking", "") or block.get("text", "")
                        if text:
                            if not self._reasoning_active:
                                self._reasoning_active = True
                                yield m.reasoning_started()
                            yield m.reasoning_content(text)
                    elif block.get("type") == "text":
                        async for e in self._emit_text(block.get("text", "")):
                            yield e
            return

        if content:
            async for e in self._emit_text(content):
                yield e

    async def _emit_text(self, content: str) -> AsyncGenerator[m.AGUIEvent, None]:
        if not content:
            return
        # 关闭推理流
        if self._reasoning_active:
            self._reasoning_active = False
            yield m.reasoning_finished()
        # 开启文本流
        if not self._text_active:
            self._text_active = True
            self._text_message_id = uuid.uuid4().hex[:12]
            yield m.text_message_start(self._text_message_id)
        yield m.text_message_content(self._text_message_id, content)

    async def _handle_skill_start(self, name: str) -> AsyncGenerator[m.AGUIEvent, None]:
        async for e in self._close_text_stream():
            yield e
        skill_apikey = name[len(SKILL_CHAIN_PREFIX):]
        step_id = f"step-{self._step_index}"
        yield m.step_started(step_id, skill_apikey, self._step_index)

    async def _handle_skill_end(self, name: str, data: dict) -> AsyncGenerator[m.AGUIEvent, None]:
        skill_apikey = name[len(SKILL_CHAIN_PREFIX):]
        step_id = f"step-{self._step_index}"
        output = data.get("output", {})
        status = "failed" if isinstance(output, dict) and output.get("error") else "completed"
        yield m.step_finished(step_id, skill_apikey, self._step_index, status)
        self._step_index += 1
        yield m.messages_snapshot(list(self._messages))

    async def _close_text_stream(self) -> AsyncGenerator[m.AGUIEvent, None]:
        if self._text_active:
            self._text_active = False
            yield m.text_message_end(self._text_message_id)

    async def _close_active_streams(self) -> AsyncGenerator[m.AGUIEvent, None]:
        if self._reasoning_active:
            self._reasoning_active = False
            yield m.reasoning_finished()
        async for e in self._close_text_stream():
            yield e
