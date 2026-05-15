"""<long_text> 标签解析状态机 — 对齐 apps-agent V2AGUIConverter

当 LLM 输出中包含 <long_text type="report" title="标题">内容</long_text> 时，
自动将内容折叠为卡片（ACTIVITY_SNAPSHOT），而非直接输出为 TEXT_MESSAGE。

流程：
  1. 检测到 <long_text type="xxx" title="yyy"> 开始标签
  2. 关闭当前文本流（TEXT_MESSAGE_END）
  3. 发送 ACTIVITY_SNAPSHOT（status=pending，卡片加载态）
  4. 标签内的内容累积（不发 TEXT_MESSAGE）
  5. 检测到 </long_text> 结束标签
  6. 发送 ACTIVITY_SNAPSHOT（status=complete，卡片完成态，含完整内容）

对齐：apps-agent service/agent_agui/agent_v2/converter.py 的 _handle_long_text_chunk
"""
from __future__ import annotations

import logging
import re
import uuid
from typing import AsyncGenerator

from . import models as m

logger = logging.getLogger(__name__)


class LongTextParser:
    """<long_text> 标签解析状态机"""

    def __init__(self, run_id: str):
        self._run_id = run_id
        self.active = False
        self._pending = ""
        self._type = ""
        self._title = ""
        self._content = ""
        self._index = 0
        self._message_id = ""
        self._surface_id = ""

    def could_be_prefix(self, text: str) -> bool:
        """判断 text 是否可能是 <long_text 的不完整前缀"""
        target = "<long_text"
        min_len = min(len(text), len(target))
        return text[:min_len] == target[:min_len]

    async def feed(self, content: str) -> AsyncGenerator[m.AGUIEvent, None]:
        """喂入一个 chunk，产出事件（可能为空）"""

        # 已在 long_text 模式中
        if self.active:
            async for ev in self._handle_active(content):
                yield ev
            return

        # 有 pending 缓冲
        if self._pending:
            self._pending += content
            if "<long_text" in self._pending:
                async for ev in self._parse_open_tag():
                    yield ev
                return
            if self.could_be_prefix(self._pending):
                return  # 继续等待
            # 确认不是 long_text，返回 pending 作为普通文本
            text = self._pending
            self._pending = ""
            yield m.AGUIEvent(type="__plain_text__", data={"text": text})
            return

        # 检查当前 content
        if "<long_text" in content:
            self._pending = content
            async for ev in self._parse_open_tag():
                yield ev
            return

        # 检查末尾是否有不完整前缀
        lt_idx = content.rfind("<")
        if lt_idx >= 0:
            tail = content[lt_idx:]
            if self.could_be_prefix(tail):
                before = content[:lt_idx]
                if before:
                    yield m.AGUIEvent(type="__plain_text__", data={"text": before})
                self._pending = tail
                return

        # 普通文本
        yield m.AGUIEvent(type="__plain_text__", data={"text": content})

    async def _parse_open_tag(self) -> AsyncGenerator[m.AGUIEvent, None]:
        """解析开始标签"""
        match = re.search(r'<long_text\s+([^>]*)>', self._pending)
        if not match:
            return  # 标签不完整，继续等待

        # 解析属性
        tag_str = match.group(1)
        attrs = dict(re.findall(r'(\w+)="([^"]*)"', tag_str))
        self._type = attrs.get("type", "report")
        self._title = attrs.get("title", "")

        # 标签之前的文本
        before = self._pending[:match.start()]
        if before.strip():
            yield m.AGUIEvent(type="__plain_text__", data={"text": before})

        # 关闭文本流信号
        yield m.AGUIEvent(type="__close_text__", data={})

        # 激活状态
        self.active = True
        self._content = ""
        self._index += 1
        self._pending = self._pending[match.end():]

        # 发送 pending 卡片
        self._surface_id = f"longtext-{self._run_id[:8]}-{self._index}"
        self._message_id = f"a2ui-longtext-{self._run_id[:8]}-{self._index}"

        yield self._build_activity_snapshot("pending")

        # 处理标签后的剩余内容
        if self._pending:
            remaining = self._pending
            self._pending = ""
            async for ev in self._handle_active(remaining):
                yield ev

    async def _handle_active(self, content: str) -> AsyncGenerator[m.AGUIEvent, None]:
        """标签激活后处理内容"""
        self._pending += content

        close_idx = self._pending.find("</long_text>")
        if close_idx >= 0:
            # 结束标签之前的内容
            inner = self._pending[:close_idx]
            if inner:
                self._content += inner

            # 发送 complete 卡片
            yield self._build_activity_snapshot("complete")

            # 重置状态
            after = self._pending[close_idx + len("</long_text>"):]
            self.active = False
            self._pending = ""

            # 结束标签后的内容作为普通文本
            if after.strip():
                yield m.AGUIEvent(type="__plain_text__", data={"text": after})
        else:
            # 没有结束标签，安全输出部分内容（保留末尾 12 字符缓冲）
            close_tag_len = len("</long_text>")
            if len(self._pending) > close_tag_len:
                safe = self._pending[:-close_tag_len]
                self._content += safe
                self._pending = self._pending[-close_tag_len:]

    def _build_activity_snapshot(self, status: str) -> m.AGUIEvent:
        """构建卡片的 ACTIVITY_SNAPSHOT 事件"""
        components = [{
            "id": f"micro-report-card-{self._run_id[:8]}-{self._index}",
            "component": {
                "MicroReportCard": {
                    "status": status,
                    "title": self._title,
                    "content": self._content if status == "complete" else "",
                    "startTime": "",
                }
            }
        }]

        root_id = f"micro-report-card-{self._run_id[:8]}-{self._index}"

        operations = [
            {"surfaceUpdate": {"surfaceId": self._surface_id, "components": components}},
            {"beginRendering": {"surfaceId": self._surface_id, "root": root_id}},
        ]

        return m.activity_snapshot(
            message_id=self._message_id,
            activity_type="a2ui-surface",
            content={"operations": operations},
            replace=True,
        )
