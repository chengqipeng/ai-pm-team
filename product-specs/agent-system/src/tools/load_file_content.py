"""load_file_content 工具 — 读取 parsed_files 中的文件内容

LLM 通过此工具获取用户上传文件的文本内容。
图片文件会生成多模态附件标记，由 MultimodalInjectMiddleware 注入。

数据来源：FileProcessMiddleware 写入的 state["thread_data"]["parsed_files"]
"""
from __future__ import annotations

import json
import logging
from typing import Any

from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

# 多模态附件标记（MultimodalInjectMiddleware 识别此格式）
ATTACHMENT_MARKER = "<!--MULTIMODAL_ATTACHMENTS:{attachments}-->"


class LoadFileContentInput(BaseModel):
    file_name: str = Field(default="", description="要加载的文件名，为空时加载所有文件")


class LoadFileContentTool(BaseTool):
    """加载用户上传文件的内容"""

    name: str = "load_file_content"
    description: str = (
        "加载用户上传的文件内容。传入 file_name 加载指定文件，"
        "为空时加载所有已上传文件。支持文档（PDF/Word/Excel）和图片。"
    )
    args_schema: type[BaseModel] = LoadFileContentInput

    model_config = {"arbitrary_types_allowed": True}

    def _run(self, file_name: str = "") -> str:
        return self._load(file_name, {})

    async def _arun(self, file_name: str = "") -> str:
        return self._load(file_name, {})

    def _load(self, file_name: str, runtime_config: dict) -> str:
        """从 thread_data.parsed_files 加载文件内容"""
        # 尝试从 langgraph config 获取 parsed_files
        parsed_files = []
        try:
            from langgraph.config import get_config
            configurable = get_config().get("configurable", {})
            parsed_files = configurable.get("parsed_files", [])
        except Exception:
            pass

        if not parsed_files:
            return "当前没有已上传的文件。请先上传文件。"

        # 过滤指定文件
        if file_name:
            targets = [f for f in parsed_files if file_name.lower() in f.get("fileName", "").lower()]
            if not targets:
                available = ", ".join(f.get("fileName", "?") for f in parsed_files)
                return f"未找到文件 '{file_name}'。可用文件: {available}"
        else:
            targets = parsed_files

        results = []
        multimodal_attachments = []

        for f in targets:
            fname = f.get("fileName", "unknown")
            ftype = f.get("fileType", "unknown")
            content = f.get("content", "")
            url = f.get("url", "")

            if ftype == "image" and url:
                # 图片：生成多模态附件标记
                multimodal_attachments.append({
                    "type": "input_image",
                    "image_url": url,
                    "fileName": fname,
                })
                results.append(f"📷 图片: {fname} (已注入多模态视觉)")
            elif content:
                # 文档：直接返回文本内容
                # 截断过长内容
                if len(content) > 10000:
                    content = content[:10000] + f"\n...[截断，原文 {len(content)} 字符]"
                results.append(f"📄 {fname}:\n{content}")
            elif url:
                # 有 URL 但无文本内容（PDF 等）
                multimodal_attachments.append({
                    "type": "input_file",
                    "file_url": url,
                    "fileName": fname,
                })
                results.append(f"📎 文档: {fname} (已注入多模态)")
            else:
                results.append(f"⚠️ {fname}: 无法读取内容")

        output = "\n\n".join(results)

        # 附加多模态标记（MultimodalInjectMiddleware 会解析）
        if multimodal_attachments:
            marker = ATTACHMENT_MARKER.format(
                attachments=json.dumps(multimodal_attachments, ensure_ascii=False)
            )
            output += "\n\n" + marker

        logger.info("load_file_content: 加载 %d 个文件", len(targets))
        return output
