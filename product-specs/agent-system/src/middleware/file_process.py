"""文件预处理中间件 — 解析上传文件，写入 parsed_files 供后续工具消费

数据流：
1. 用户上传文件 → configurable["files"] 传入
2. FileProcessMiddleware.before_agent 解析文件 → state["thread_data"]["parsed_files"]
3. load_file_content 工具读取 parsed_files → 返回文件内容给 LLM
4. MultimodalInjectMiddleware.before_model 将图片/文档 URL 注入 HumanMessage
"""
from __future__ import annotations

import logging
import mimetypes
from typing import Any

from langchain.agents.middleware.types import AgentMiddleware, AgentState
from langgraph.config import get_config
from langgraph.runtime import Runtime

logger = logging.getLogger(__name__)

# 支持的文件类型
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".svg"}
DOCUMENT_EXTENSIONS = {".pdf", ".docx", ".doc", ".xlsx", ".xls", ".pptx", ".ppt", ".csv", ".txt", ".md"}


class FileProcessMiddleware(AgentMiddleware):
    """文件预处理中间件：解析上传文件，写入 parsed_files"""

    def __init__(self, upload_dir: str = "./data/uploads") -> None:
        super().__init__()
        self._upload_dir = upload_dir

    def before_agent(self, state: AgentState, runtime: Runtime) -> dict[str, Any] | None:
        configurable = get_config().get("configurable", {})
        files = configurable.get("files")
        if not files:
            return None

        parsed_files = self._parse_files(files, configurable)
        if not parsed_files:
            return None

        # 写入 thread_data 供工具消费
        thread_data = dict(state.get("thread_data", {}) or {})
        thread_data["parsed_files"] = parsed_files
        logger.info("文件预处理完成: %d 个文件", len(parsed_files))
        return {"thread_data": thread_data}

    def _parse_files(self, files: list, configurable: dict) -> list[dict[str, Any]]:
        """解析文件列表，返回标准化的文件元信息"""
        parsed = []
        for f in files:
            file_info = self._parse_single_file(f, configurable)
            if file_info:
                parsed.append(file_info)
        return parsed

    def _parse_single_file(self, f: Any, configurable: dict) -> dict[str, Any] | None:
        """解析单个文件"""
        # 支持 dict 格式和对象格式
        if isinstance(f, dict):
            filename = f.get("filename", f.get("fileName", ""))
            file_type = f.get("file_type", f.get("fileType", ""))
            content = f.get("content", "")
            url = f.get("url", f.get("pdfFileUrl", ""))
            media_id = f.get("media_id", f.get("mediaId", ""))
        else:
            filename = getattr(f, "filename", getattr(f, "fileName", ""))
            file_type = getattr(f, "file_type", getattr(f, "fileType", ""))
            content = getattr(f, "content", getattr(f, "fileToText", ""))
            url = getattr(f, "url", getattr(f, "pdfFileUrl", ""))
            media_id = getattr(f, "media_id", getattr(f, "mediaId", ""))

        if not filename and not content:
            return None

        # 推断文件类型
        if not file_type and filename:
            ext = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
            mime = mimetypes.guess_type(filename)[0] or ""
            if ext in IMAGE_EXTENSIONS:
                file_type = "image"
            elif ext in DOCUMENT_EXTENSIONS:
                file_type = "document"
            else:
                file_type = "unknown"

        return {
            "fileName": filename,
            "fileType": file_type,
            "content": content,
            "url": url,
            "mediaId": media_id,
        }
