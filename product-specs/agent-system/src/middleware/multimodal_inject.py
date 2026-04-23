"""多模态注入中间件 — 将图片/文档 URL 注入 HumanMessage

在 before_model 时检查 ToolMessage 中的多模态附件标记，
将图片/文档 URL 以多模态格式注入到最后一条 HumanMessage 中。

标记格式：<!--MULTIMODAL_ATTACHMENTS:[{"type":"input_image","image_url":"..."}]-->
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

from langchain_core.messages import HumanMessage, ToolMessage
from langchain.agents.middleware.types import AgentMiddleware, AgentState
from langgraph.runtime import Runtime

logger = logging.getLogger(__name__)

ATTACHMENT_PATTERN = re.compile(r"<!--MULTIMODAL_ATTACHMENTS:(.*?)-->", re.DOTALL)


class MultimodalInjectMiddleware(AgentMiddleware):
    """多模态附件注入：在每轮模型调用前将图片/文档 URL 注入到 HumanMessage"""

    def before_model(self, state: AgentState, runtime: Runtime) -> dict[str, Any] | None:
        messages = state.get("messages", [])
        if not messages:
            return None

        # 从 ToolMessage 中提取附件
        attachments = self._extract_attachments(messages)

        # 从 thread_data.parsed_files 中提取图片附件
        thread_data = state.get("thread_data", {}) or {}
        parsed_files = thread_data.get("parsed_files", [])
        for pf in parsed_files:
            ft = pf.get("fileType", "")
            url = pf.get("url", "")
            if ft == "image" and url:
                attachments.append({
                    "type": "input_image",
                    "image_url": url,
                    "fileName": pf.get("fileName", ""),
                })
            elif ft == "document" and url:
                attachments.append({
                    "type": "input_file",
                    "file_url": url,
                    "fileName": pf.get("fileName", ""),
                })

        if not attachments:
            return None

        # 找最后一条 HumanMessage
        last_human_idx = None
        for i in range(len(messages) - 1, -1, -1):
            if isinstance(messages[i], HumanMessage):
                last_human_idx = i
                break

        if last_human_idx is None:
            return None

        last_human = messages[last_human_idx]
        original_content = last_human.content

        # 已经是多模态格式且包含附件 → 跳过
        if isinstance(original_content, list) and any(
            isinstance(item, dict) and item.get("type") in ("input_image", "input_file")
            for item in original_content
        ):
            return None

        # 构建多模态 content
        multimodal_content: list[dict[str, Any]] = []
        if isinstance(original_content, str):
            multimodal_content.append({"type": "input_text", "text": original_content})
        elif isinstance(original_content, list):
            multimodal_content.extend(original_content)

        for att in attachments:
            att_type = att.get("type")
            if att_type == "input_image":
                multimodal_content.append({"type": "input_image", "image_url": att["image_url"]})
            elif att_type == "input_file":
                multimodal_content.append({"type": "input_file", "file_url": att["file_url"]})

        # 替换 HumanMessage
        new_messages = list(messages)
        new_messages[last_human_idx] = HumanMessage(
            content=multimodal_content,
            id=last_human.id,
        )

        logger.info("多模态注入: %d 个附件注入到 HumanMessage", len(attachments))
        return {"messages": new_messages}

    @staticmethod
    def _extract_attachments(messages: list) -> list[dict[str, Any]]:
        """从 ToolMessage 中提取 <!--MULTIMODAL_ATTACHMENTS:...--> 标记"""
        attachments: list[dict[str, Any]] = []
        for msg in messages:
            if not isinstance(msg, ToolMessage):
                continue
            content = msg.content if isinstance(msg.content, str) else ""
            for match in ATTACHMENT_PATTERN.finditer(content):
                try:
                    items = json.loads(match.group(1))
                    if isinstance(items, list):
                        attachments.extend(items)
                except (json.JSONDecodeError, TypeError):
                    pass
        return attachments
