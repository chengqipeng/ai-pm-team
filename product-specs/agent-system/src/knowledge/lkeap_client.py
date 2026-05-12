"""腾讯云 LKEAP 文档解析客户端

封装知识引擎原子能力 API：
- CreateReconstructDocumentFlow / GetReconstructDocumentResult（异步文档解析）
- ReconstructDocumentSSE（实时文档解析）
- CreateSplitDocumentFlow / GetSplitDocumentResult（文档切分）
- GetEmbedding（文本向量化）
- RunRerank（重排序）

API 文档：https://cloud.tencent.com/document/product/1772/115345
"""
from __future__ import annotations

import asyncio
import base64
import io
import json
import logging
import time
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════
# 凭证处理：自动识别 base64 编码的 secret
# ═══════════════════════════════════════════════════════════

def _maybe_decode_base64(value: str) -> str:
    """自动识别并解码 base64 编码的凭证

    腾讯云 SecretId 格式：AKID + 32 个字符（总 36 字符，全 ASCII）
    腾讯云 SecretKey：32 个字符

    识别规则：
        - 为空 → 原样返回
        - 以 AKID 开头且长度合理 → 明文，原样返回
        - 长度是 4 的倍数、只含 base64 字符、解码后是合法 ASCII → 视为 base64，解码
        - 其他 → 原样返回
    """
    if not value:
        return value

    # 明文 SecretId 特征
    if value.startswith("AKID") and len(value) <= 50 and value.isalnum():
        return value

    # base64 特征：长度 4 的倍数、只含 base64 字符集
    stripped = value.strip()
    if len(stripped) % 4 != 0:
        return value

    try:
        decoded = base64.b64decode(stripped, validate=True).decode("ascii")
    except (ValueError, UnicodeDecodeError):
        return value

    # 解码后仍需符合腾讯云凭证长度（避免误判）
    if 20 <= len(decoded) <= 60 and decoded.isprintable():
        logger.debug("Decoded base64 credential: %s → %s***",
                     stripped[:6], decoded[:6])
        return decoded
    return value


# ── 数据模型 ──

@dataclass
class ParseResult:
    """文档解析结果"""
    status: str                                # SUCCESS / PROCESSING / FAILED
    task_id: str = ""
    markdown_content: str = ""                 # 解析后的 Markdown 文本
    result_url: str = ""                       # 结果 zip 下载地址
    failed_pages: list[int] = field(default_factory=list)
    success_page_num: int = 0
    fail_page_num: int = 0


@dataclass
class ChunkInfo:
    """切片信息"""
    content: str
    metadata: dict = field(default_factory=dict)
    chunk_type: str = "Text"                   # Text / Table / Image_Description / Title / Summary


@dataclass
class SplitResult:
    """文档切分结果"""
    status: str
    task_id: str = ""
    chunks: list[ChunkInfo] = field(default_factory=list)


@dataclass
class RerankItem:
    """重排序结果项"""
    index: int
    score: float


class TencentLKEAPClient:
    """腾讯云 LKEAP 文档解析客户端

    Args:
        secret_id: 腾讯云 SecretId
        secret_key: 腾讯云 SecretKey
        region: 地域，支持 ap-beijing / ap-guangzhou
    """

    # 支持的文件类型
    SUPPORTED_TYPES = {
        "pdf", "doc", "docx", "ppt", "pptx", "xls", "xlsx", "wps",
        "md", "txt", "csv", "html", "epub",
        "png", "jpg", "jpeg", "bmp", "gif", "webp", "heic",
        "eps", "icns", "im", "pcx", "ppm", "tiff", "xbm", "heif", "jp2",
    }

    def __init__(
        self,
        secret_id: str,
        secret_key: str,
        region: str = "ap-guangzhou",
    ) -> None:
        self._secret_id = secret_id
        self._secret_key = secret_key
        self._region = region
        self._client = None

    def _ensure_client(self):
        """延迟初始化腾讯云 SDK 客户端"""
        if self._client is not None:
            return self._client
        try:
            from tencentcloud.common import credential
            from tencentcloud.common.profile.client_profile import ClientProfile
            from tencentcloud.common.profile.http_profile import HttpProfile
            from tencentcloud.lkeap.v20240522 import lkeap_client
        except ImportError as exc:
            raise RuntimeError(
                "tencentcloud-sdk-python 未安装。请执行："
                "pip install 'tencentcloud-sdk-python>=3.1.86'。"
                f"原始错误: {exc}"
            ) from exc

        # 凭证自动 base64 解码（支持 plain 和 base64 两种传入方式）
        secret_id = _maybe_decode_base64(self._secret_id)
        secret_key = _maybe_decode_base64(self._secret_key)

        if not secret_id or not secret_key:
            raise RuntimeError(
                "LKEAP 凭证未配置：lkeap_secret_id / lkeap_secret_key 为空。"
                "请通过环境变量 LKEAP_SECRET_ID / LKEAP_SECRET_KEY 或 "
                "KnowledgeSettings 传入。"
            )

        cred = credential.Credential(secret_id, secret_key)
        http_profile = HttpProfile()
        http_profile.endpoint = "lkeap.tencentcloudapi.com"
        client_profile = ClientProfile()
        client_profile.httpProfile = http_profile
        self._client = lkeap_client.LkeapClient(cred, self._region, client_profile)
        logger.info(
            "LKEAP client initialized: region=%s secret_id=%s***",
            self._region, secret_id[:6],
        )
        return self._client

    # ── 异步文档解析 ──

    def create_parse_task(
        self,
        file_url: str | None = None,
        file_base64: str | None = None,
        file_type: str = "pdf",
        start_page: int | None = None,
        end_page: int | None = None,
    ) -> str:
        """创建异步文档解析任务，返回 task_id

        Args:
            file_url: 文件 URL（与 file_base64 二选一，优先 file_url）
            file_base64: 文件 Base64 编码（≤8M）
            file_type: 文件类型
            start_page: 起始页码（PDF/PPT/DOC 有效）
            end_page: 结束页码
        """
        client = self._ensure_client()
        from tencentcloud.lkeap.v20240522 import models

        req = models.CreateReconstructDocumentFlowRequest()
        params = {"FileType": file_type.upper()}
        if file_url:
            params["FileUrl"] = file_url
        elif file_base64:
            params["FileBase64"] = file_base64
        else:
            raise ValueError("file_url 或 file_base64 必须提供一个")
        if start_page is not None:
            params["FileStartPageNumber"] = start_page
        if end_page is not None:
            params["FileEndPageNumber"] = end_page
        req.from_json_string(json.dumps(params))

        resp = client.CreateReconstructDocumentFlow(req)
        task_id = resp.TaskId
        logger.info("LKEAP parse task created: task_id=%s, file_type=%s", task_id, file_type)
        return task_id

    def get_parse_result(self, task_id: str) -> ParseResult:
        """查询异步解析任务结果

        30 天内可查询。返回 ParseResult，status 为 SUCCESS 时包含结果 URL。
        """
        client = self._ensure_client()
        from tencentcloud.lkeap.v20240522 import models

        req = models.GetReconstructDocumentResultRequest()
        req.from_json_string(json.dumps({"TaskId": task_id}))
        resp = client.GetReconstructDocumentResult(req)

        return ParseResult(
            status=resp.Status or "PROCESSING",
            task_id=task_id,
            result_url=resp.DocumentRecognizeResultUrl or "",
            failed_pages=[p.PageNumber for p in (resp.FailedPages or [])] if hasattr(resp, 'FailedPages') and resp.FailedPages else [],
        )

    async def parse_document(
        self,
        file_url: str | None = None,
        file_base64: str | None = None,
        file_type: str = "pdf",
        start_page: int | None = None,
        end_page: int | None = None,
        poll_interval: float = 2.0,
        max_wait: float = 300.0,
    ) -> ParseResult:
        """异步文档解析（完整流程：创建任务 → 轮询 → 返回结果）

        Args:
            poll_interval: 轮询间隔（秒）
            max_wait: 最大等待时间（秒）
        """
        task_id = self.create_parse_task(
            file_url=file_url,
            file_base64=file_base64,
            file_type=file_type,
            start_page=start_page,
            end_page=end_page,
        )

        start_time = time.time()
        while True:
            elapsed = time.time() - start_time
            if elapsed > max_wait:
                return ParseResult(status="TIMEOUT", task_id=task_id)

            await asyncio.sleep(poll_interval)
            result = self.get_parse_result(task_id)
            logger.debug("LKEAP poll: task_id=%s, status=%s, elapsed=%.1fs", task_id, result.status, elapsed)

            if result.status in ("SUCCESS", "FAILED"):
                return result

    # ── 同步文档解析（SSE） ──

    def parse_document_sse(
        self,
        file_url: str | None = None,
        file_base64: str | None = None,
        file_type: str = "pdf",
        start_page: int | None = None,
        end_page: int | None = None,
        on_progress: Any = None,
    ) -> ParseResult:
        """实时文档解析（SSE 模式，适合小文件 ≤100M）

        SDK 返回 SSE generator，每个事件是 dict{"data": json_string}。
        消费所有事件，最后一个 TASK_RSP 事件包含结果下载 URL。

        Args:
            on_progress: 可选回调 (progress: int, message: str) -> None
        """
        client = self._ensure_client()
        from tencentcloud.lkeap.v20240522 import models

        req = models.ReconstructDocumentSSERequest()
        params = {"FileType": file_type.upper()}
        if file_url:
            params["FileUrl"] = file_url
        elif file_base64:
            params["FileBase64"] = file_base64
        else:
            raise ValueError("file_url 或 file_base64 必须提供一个")
        if start_page is not None:
            params["FileStartPageNumber"] = start_page
        if end_page is not None:
            params["FileEndPageNumber"] = end_page
        req.from_json_string(json.dumps(params))

        gen = client.ReconstructDocumentSSE(req)

        last_data: dict = {}
        for event in gen:
            # SSE 事件是 dict{"data": json_string}
            data_str = event.get("data", "") if isinstance(event, dict) else ""
            if not data_str:
                continue
            try:
                data = json.loads(data_str)
            except (json.JSONDecodeError, TypeError):
                continue
            last_data = data
            if on_progress and callable(on_progress):
                on_progress(int(data.get("Progress", 0)), data.get("ProgressMessage", ""))
            logger.debug(
                "LKEAP SSE: progress=%s type=%s msg=%s",
                data.get("Progress"), data.get("ResponseType"), data.get("ProgressMessage"),
            )

        if not last_data:
            return ParseResult(status="FAILED", task_id="")

        result_url = last_data.get("DocumentRecognizeResultUrl", "")
        return ParseResult(
            status="SUCCESS" if result_url else "FAILED",
            task_id=last_data.get("TaskId", ""),
            result_url=result_url,
            success_page_num=last_data.get("SuccessPageNum", 0) or 0,
            fail_page_num=last_data.get("FailPageNum", 0) or 0,
        )

    # ── 文档切分 ──

    def create_split_task(
        self,
        file_url: str | None = None,
        file_base64: str | None = None,
        file_type: str = "pdf",
    ) -> str:
        """创建文档切分任务"""
        client = self._ensure_client()
        from tencentcloud.lkeap.v20240522 import models

        req = models.CreateSplitDocumentFlowRequest()
        params = {"FileType": file_type.upper()}
        if file_url:
            params["FileUrl"] = file_url
        elif file_base64:
            params["FileBase64"] = file_base64
        req.from_json_string(json.dumps(params))

        resp = client.CreateSplitDocumentFlow(req)
        return resp.TaskId

    def get_split_result(self, task_id: str) -> SplitResult:
        """查询切分任务结果"""
        client = self._ensure_client()
        from tencentcloud.lkeap.v20240522 import models

        req = models.GetSplitDocumentResultRequest()
        req.from_json_string(json.dumps({"TaskId": task_id}))
        resp = client.GetSplitDocumentResult(req)

        chunks = []
        if hasattr(resp, 'SplitResult') and resp.SplitResult:
            for item in resp.SplitResult:
                chunks.append(ChunkInfo(
                    content=getattr(item, 'Content', '') or '',
                    metadata=json.loads(getattr(item, 'Metadata', '{}') or '{}') if isinstance(getattr(item, 'Metadata', None), str) else {},
                    chunk_type=getattr(item, 'ChunkType', 'Text') or 'Text',
                ))
        return SplitResult(
            status=resp.Status or "PROCESSING",
            task_id=task_id,
            chunks=chunks,
        )

    # ── Embedding ──

    def get_embedding(
        self, texts: list[str], model: str = "lke-text-embedding-v1"
    ) -> list[list[float]]:
        """文本向量化（逐条调用，腾讯云 LKEAP 单次只接受 1 个 input）

        Args:
            texts: 待向量化的文本列表
            model: 模型名称，默认 lke-text-embedding-v1（1024 维）
        """
        client = self._ensure_client()
        from tencentcloud.lkeap.v20240522 import models

        if not texts:
            return []

        vectors: list[list[float]] = []
        for i, text in enumerate(texts):
            if not text:
                # 空文本给一个 0 向量占位，保持顺序对齐
                logger.warning("get_embedding: empty text at index %d, skip", i)
                vectors.append([])
                continue
            req = models.GetEmbeddingRequest()
            # 注意：腾讯云 LKEAP GetEmbedding 限制单次 1 个 Input
            req.from_json_string(json.dumps({"Model": model, "Inputs": [text]}))
            try:
                resp = client.GetEmbedding(req)
            except Exception as exc:
                logger.exception(
                    "get_embedding failed at index %d/%d (text_len=%d): %s",
                    i, len(texts), len(text), exc,
                )
                raise
            vec = resp.Data[0].Embedding if resp.Data else []
            vectors.append(vec)
        return vectors

    # ── Rerank ──

    def rerank(self, query: str, documents: list[str], top_k: int = 5) -> list[RerankItem]:
        """重排序

        ScoreList 是 float 列表，索引对应 documents 的顺序。
        按 score 降序排列后返回 top_k 个结果。
        """
        client = self._ensure_client()
        from tencentcloud.lkeap.v20240522 import models

        req = models.RunRerankRequest()
        req.from_json_string(json.dumps({
            "Query": query,
            "Docs": documents,
        }))
        resp = client.RunRerank(req)
        items = []
        if resp.ScoreList:
            for i, score in enumerate(resp.ScoreList):
                items.append(RerankItem(index=i, score=float(score)))
        # 按 score 降序，取 top_k
        items.sort(key=lambda x: x.score, reverse=True)
        return items[:top_k]

    # ── 工具方法 ──

    @staticmethod
    def download_and_extract_markdown(result_url: str) -> str:
        """下载解析结果 zip 并提取 Markdown 内容

        LKEAP 返回的 zip 包含：.md 文件 + .json 结构化结果 + images/ 目录
        优先级：.md > .json > .txt > .html
        """
        import urllib.request
        logger.info("Downloading parse result: %s", result_url[:80] + "...")
        resp = urllib.request.urlopen(result_url, timeout=60)
        zip_bytes = resp.read()

        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            all_names = zf.namelist()
            # 记录 zip 内容概况，便于排查
            file_details = [
                (n, zf.getinfo(n).file_size) for n in all_names
                if not n.endswith("/")  # 排除目录条目
            ]
            logger.info(
                "Zip contents (%d entries, %d files): %s",
                len(all_names), len(file_details),
                [(n, sz) for n, sz in file_details[:20]],
            )

            # 查找 .md 文件（不区分大小写）
            md_files = [n for n in all_names if n.lower().endswith(".md")]
            if md_files:
                # 优先选最大的 .md 文件（避免选到空的 README 等）
                md_files.sort(key=lambda n: zf.getinfo(n).file_size, reverse=True)
                md_content = zf.read(md_files[0]).decode("utf-8")
                logger.info("Extracted markdown: %d chars from %s", len(md_content), md_files[0])
                if md_content.strip():
                    return md_content
                logger.warning("Found .md file but content is empty: %s", md_files[0])

            # 没有 .md，尝试 .json
            json_files = [n for n in all_names if n.lower().endswith(".json")]
            if json_files:
                json_files.sort(key=lambda n: zf.getinfo(n).file_size, reverse=True)
                json_content = zf.read(json_files[0]).decode("utf-8")
                logger.info("Extracted JSON: %d chars from %s", len(json_content), json_files[0])
                if json_content.strip():
                    return json_content
                logger.warning("Found .json file but content is empty: %s", json_files[0])

            # 降级：尝试 .txt
            txt_files = [n for n in all_names if n.lower().endswith(".txt")]
            if txt_files:
                txt_files.sort(key=lambda n: zf.getinfo(n).file_size, reverse=True)
                txt_content = zf.read(txt_files[0]).decode("utf-8")
                logger.info("Fallback extracted TXT: %d chars from %s", len(txt_content), txt_files[0])
                if txt_content.strip():
                    return txt_content

            # 降级：尝试 .html
            html_files = [n for n in all_names if n.lower().endswith((".html", ".htm"))]
            if html_files:
                html_files.sort(key=lambda n: zf.getinfo(n).file_size, reverse=True)
                html_content = zf.read(html_files[0]).decode("utf-8")
                logger.info("Fallback extracted HTML: %d chars from %s", len(html_content), html_files[0])
                if html_content.strip():
                    return html_content

            # 所有尝试均失败
            logger.error(
                "No usable content found in zip. All files: %s",
                file_details,
            )
            return ""

    @classmethod
    def is_supported(cls, file_type: str) -> bool:
        """检查文件类型是否支持"""
        return file_type.lower().lstrip(".") in cls.SUPPORTED_TYPES
