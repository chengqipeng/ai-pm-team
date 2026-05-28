"""COS 文件上传工具 — 将本地文件上传到腾讯云 COS 并返回可访问链接

使用场景：
    - Agent 生成了 HTML/PDF/Markdown 等文件后，上传到 COS 获取公开链接
    - 用户需要将本地文件分享给他人时，上传后返回预签名 URL

配置：
    COS 凭证通过环境变量注入：
        COS_SECRET_ID / COS_SECRET_KEY / COS_BUCKET / COS_REGION / COS_KEY_PREFIX
    或在 KnowledgeSettings 中配置。
"""
from __future__ import annotations

import logging
import os
import time
import uuid
from pathlib import Path
from typing import Any, Callable

from src.core.dtypes import ToolResult
from src.tools.base import Tool

logger = logging.getLogger(__name__)


class CosUploadTool(Tool):
    """将本地文件上传到腾讯云 COS，返回可访问的 URL"""

    def __init__(self, cos_client=None):
        """
        Args:
            cos_client: TencentCOSClient 实例。为 None 时在首次调用时从环境变量懒加载。
        """
        self._cos_client = cos_client

    @classmethod
    def create(cls, tenant_id: int = 0, db_row=None) -> "CosUploadTool":
        """自包含初始化 — COS 凭证从环境变量懒加载

        Raises:
            ToolCreateSkipped: COS 凭证未配置时跳过注册
        """
        from src.tools.factory import ToolCreateSkipped

        secret_id = os.environ.get("COS_SECRET_ID", "")
        secret_key = os.environ.get("COS_SECRET_KEY", "")
        if not secret_id or not secret_key:
            raise ToolCreateSkipped("COS 凭证未配置（COS_SECRET_ID / COS_SECRET_KEY）")
        # 凭证存在，实例化（实际 client 仍然懒加载）
        return cls()

    def _ensure_client(self):
        """懒加载 COS 客户端"""
        if self._cos_client is not None:
            return self._cos_client

        from src.knowledge.cos_client import TencentCOSClient

        secret_id = os.environ.get("COS_SECRET_ID", "")
        secret_key = os.environ.get("COS_SECRET_KEY", "")
        bucket = os.environ.get("COS_BUCKET", "domainverify-1253467224")
        region = os.environ.get("COS_REGION", "ap-beijing")
        key_prefix = os.environ.get("COS_KEY_PREFIX", "agent-files/")

        if not secret_id or not secret_key:
            raise RuntimeError(
                "COS 凭证未配置。请设置环境变量 COS_SECRET_ID 和 COS_SECRET_KEY"
            )

        self._cos_client = TencentCOSClient(
            secret_id=secret_id,
            secret_key=secret_key,
            bucket=bucket,
            region=region,
            key_prefix=key_prefix,
        )
        return self._cos_client

    @property
    def name(self) -> str:
        return "cos_upload"

    def prompt(self) -> str:
        return (
            "将文件上传到腾讯云 COS 对象存储，返回可通过浏览器直接访问的 URL。\n"
            "支持两种模式：\n"
            "1. 传入 file_path：上传已有的本地文件（推荐，如已用 write_file 写入沙盒则直接传路径即可，无需再 read_file）\n"
            "2. 传入 content + file_name：直接将内容生成文件并上传（适合动态生成 HTML/Markdown/文本，无需先 write_file 再上传）\n"
            "上传后返回预签名 URL（有效期 7 天），用户可直接在浏览器中打开。\n"
            "注意：如果你已经用 write_file 生成了文件，直接传 file_path 即可，不要再 read_file 读取内容。"
        )

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": (
                        "要上传的本地文件路径（绝对路径或相对路径）。"
                        "如果已用 write_file 写入了文件，直接传该路径即可（如 /sandbox/report.html），无需先 read_file。"
                        "与 content 二选一。"
                    ),
                },
                "content": {
                    "type": "string",
                    "description": (
                        "文件内容（与 file_path 二选一）。直接传入 HTML/Markdown/文本内容，"
                        "工具会自动生成文件并上传。适用于 Agent 动态生成内容的场景。"
                    ),
                },
                "file_name": {
                    "type": "string",
                    "description": (
                        "文件名（当使用 content 参数时必填）。"
                        "示例: 'beijing-travel.html'、'report.md'、'data.csv'"
                    ),
                },
                "object_key": {
                    "type": "string",
                    "description": (
                        "COS 对象 key（可选）。不指定时自动生成唯一文件名。"
                        "示例: 'reports/2024/analysis.html'"
                    ),
                },
                "expires": {
                    "type": "integer",
                    "description": "预签名 URL 有效期（秒），默认 604800（7天）",
                    "default": 604800,
                },
            },
            "required": [],
        }

    async def call(
        self,
        input_data: dict,
        context: Any,
        on_progress: Callable[[Any], None] | None = None,
    ) -> ToolResult:
        file_path = input_data.get("file_path", "")
        content = input_data.get("content", "")
        file_name = input_data.get("file_name", "")
        object_key = input_data.get("object_key")
        expires = input_data.get("expires", 604800)  # 默认 7 天

        # 参数校验：file_path 和 content 二选一
        if not file_path and not content:
            return ToolResult(
                content="错误：必须指定 file_path（上传已有文件）或 content（生成新文件）之一",
                is_error=True,
            )

        temp_file_created = False
        path: Path | None = None

        try:
            if content:
                # 模式 B：从 content 生成文件
                if not file_name:
                    # 根据内容推断文件名
                    if content.strip().startswith("<!") or content.strip().startswith("<html"):
                        file_name = f"generated_{uuid.uuid4().hex[:6]}.html"
                    elif content.strip().startswith("#") or content.strip().startswith("---"):
                        file_name = f"generated_{uuid.uuid4().hex[:6]}.md"
                    else:
                        file_name = f"generated_{uuid.uuid4().hex[:6]}.txt"

                # 写入临时文件
                import tempfile
                tmp_dir = Path(tempfile.gettempdir()) / "cos_upload"
                tmp_dir.mkdir(parents=True, exist_ok=True)
                path = tmp_dir / file_name
                path.write_text(content, encoding="utf-8")
                temp_file_created = True
            else:
                # 模式 A：上传已有文件
                path = Path(file_path)
                if not path.is_absolute():
                    project_root = Path(__file__).parent.parent.parent
                    path = project_root / file_path

                if not path.exists():
                    return ToolResult(
                        content=f"错误：文件不存在: {path}",
                        is_error=True,
                    )

                if not path.is_file():
                    return ToolResult(
                        content=f"错误：路径不是文件: {path}",
                        is_error=True,
                    )

            # 文件大小检查（限制 100MB）
            file_size = path.stat().st_size
            if file_size > 100 * 1024 * 1024:
                return ToolResult(
                    content=f"错误：文件过大（{file_size / 1024 / 1024:.1f}MB），最大支持 100MB",
                    is_error=True,
                )

            # 生成 object_key
            if not object_key:
                date_str = time.strftime("%Y%m%d")
                short_id = uuid.uuid4().hex[:8]
                object_key = f"{date_str}/{short_id}_{path.name}"

            try:
                client = self._ensure_client()
            except Exception as exc:
                return ToolResult(
                    content=f"COS 客户端初始化失败: {exc}",
                    is_error=True,
                )

            # 上传
            try:
                raw_url = client.upload_file(
                    local_path=str(path),
                    object_key=object_key,
                )
            except Exception as exc:
                logger.exception("COS upload failed: file=%s key=%s", path, object_key)
                return ToolResult(
                    content=f"上传失败: {type(exc).__name__}: {exc}",
                    is_error=True,
                )

            # 生成预签名 URL
            try:
                presigned_url = client.generate_presigned_url(
                    object_key=object_key,
                    expires=expires,
                )
            except Exception as exc:
                logger.warning("生成预签名 URL 失败（返回原始 URL）: %s", exc)
                presigned_url = raw_url

            # 格式化有效期描述
            if expires >= 86400:
                expires_desc = f"{expires // 86400} 天"
            elif expires >= 3600:
                expires_desc = f"{expires // 3600} 小时"
            else:
                expires_desc = f"{expires // 60} 分钟"

            result = (
                f"文件上传成功！\n\n"
                f"📄 文件: {path.name} ({file_size / 1024:.1f} KB)\n"
                f"🔗 访问链接（有效期 {expires_desc}）:\n"
                f"[{path.stem}]({presigned_url})\n\n"
                f"【重要】回复用户时，必须将上面的 Markdown 链接原样包含在回复中。"
                f"即 [{path.stem}](完整URL) 格式，不要省略 URL 部分，不要只写文件名。"
            )

            return ToolResult(
                content=result,
                metadata={
                    "raw_url": raw_url,
                    "presigned_url": presigned_url,
                    "object_key": object_key,
                    "file_name": path.name,
                    "file_size": file_size,
                    "expires": expires,
                },
            )
        finally:
            # 清理临时文件
            if temp_file_created and path and path.exists():
                try:
                    path.unlink()
                except Exception:
                    pass

    def is_read_only(self, input_data: dict) -> bool:
        return False

    @property
    def tags(self) -> list[str]:
        return ["file", "upload", "cos", "share"]
