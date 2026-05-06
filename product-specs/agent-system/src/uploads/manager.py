"""上传管理器 — 文件存储、元数据管理、文档格式转换"""
from __future__ import annotations

import logging
import mimetypes
import os
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol, runtime_checkable, Any

logger = logging.getLogger(__name__)

CONVERTIBLE_MIME_TYPES: dict[str, str] = {
    "application/pdf": "pdf",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": "pptx",
    "application/vnd.ms-powerpoint": "ppt",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "xlsx",
    "application/vnd.ms-excel": "xls",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
    "application/msword": "doc",
}


@dataclass
class FileMetadata:
    file_id: str
    filename: str
    size: int
    mime_type: str
    upload_time: datetime
    markdown_path: str | None = None
    text_content: str = ""


@runtime_checkable
class UploadFile(Protocol):
    filename: str | None
    content_type: str | None
    def read(self) -> bytes: ...


class UploadManager:
    """管理文件上传、存储和文档格式转换"""

    def __init__(self, base_dir: str = "./data/uploads") -> None:
        self._base_dir = Path(base_dir)
        self._metadata_store: dict[str, FileMetadata] = {}

    @property
    def base_dir(self) -> Path:
        return self._base_dir

    def save(self, thread_id: str, file: UploadFile) -> FileMetadata:
        """保存上传文件，返回元数据"""
        file_id = uuid.uuid4().hex
        filename = file.filename or f"unnamed_{file_id}"
        content = file.read()
        size = len(content)
        mime_type = file.content_type or mimetypes.guess_type(filename)[0] or "application/octet-stream"

        thread_dir = self._base_dir / thread_id
        thread_dir.mkdir(parents=True, exist_ok=True)

        dest_path = thread_dir / f"{file_id}_{filename}"
        dest_path.write_bytes(content)

        # 尝试提取文本内容
        text_content = ""
        markdown_path = None

        # 纯文本文件直接读取
        if mime_type.startswith("text/") or filename.endswith((".txt", ".md", ".csv")):
            try:
                text_content = content.decode("utf-8")
            except UnicodeDecodeError:
                text_content = content.decode("gbk", errors="replace")

        # 文档格式尝试转换
        elif mime_type in CONVERTIBLE_MIME_TYPES:
            try:
                md_content = self.convert_to_markdown(str(dest_path))
                md_dest = thread_dir / f"{file_id}.md"
                md_dest.write_text(md_content, encoding="utf-8")
                markdown_path = str(md_dest)
                text_content = md_content
            except (NotImplementedError, Exception) as exc:
                logger.warning("文档转换失败: %s — %s", filename, exc)

        metadata = FileMetadata(
            file_id=file_id, filename=filename, size=size,
            mime_type=mime_type, upload_time=datetime.now(timezone.utc),
            markdown_path=markdown_path, text_content=text_content,
        )
        self._metadata_store[file_id] = metadata
        return metadata

    def convert_to_markdown(self, file_path: str) -> str:
        """将文档转为 Markdown（预留接口，需集成 pypdf/python-docx 等）"""
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"文件不存在: {file_path}")

        suffix = path.suffix.lower()

        # 尝试 PDF
        if suffix == ".pdf":
            try:
                import pypdf
                reader = pypdf.PdfReader(str(path))
                pages = [page.extract_text() or "" for page in reader.pages]
                return "\n\n---\n\n".join(f"## 第 {i+1} 页\n{text}" for i, text in enumerate(pages) if text.strip())
            except ImportError:
                raise NotImplementedError("PDF 转换需要 pypdf: pip install pypdf")

        # 尝试 DOCX
        if suffix == ".docx":
            try:
                import docx
                doc = docx.Document(str(path))
                return "\n\n".join(p.text for p in doc.paragraphs if p.text.strip())
            except ImportError:
                raise NotImplementedError("DOCX 转换需要 python-docx: pip install python-docx")

        # 尝试 XLSX
        if suffix in (".xlsx", ".xls"):
            try:
                import openpyxl
                wb = openpyxl.load_workbook(str(path), read_only=True)
                sheets = []
                for ws in wb.worksheets:
                    rows = []
                    for row in ws.iter_rows(values_only=True):
                        rows.append(" | ".join(str(c) if c is not None else "" for c in row))
                    if rows:
                        sheets.append(f"### {ws.title}\n" + "\n".join(rows))
                return "\n\n".join(sheets)
            except ImportError:
                raise NotImplementedError("Excel 转换需要 openpyxl: pip install openpyxl")

        raise NotImplementedError(f"不支持的格式: {suffix}")

    def get_metadata(self, file_id: str) -> FileMetadata | None:
        return self._metadata_store.get(file_id)

    def list_files(self, thread_id: str | None = None) -> list[FileMetadata]:
        if thread_id is None:
            return list(self._metadata_store.values())
        thread_dir = str(self._base_dir / thread_id)
        return [m for m in self._metadata_store.values()
                if thread_dir in str(self._base_dir / m.file_id)]
