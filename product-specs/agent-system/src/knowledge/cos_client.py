"""腾讯云 COS 对象存储客户端 — 知识库文件上传

职责：
    - 将本地文件上传到 COS
    - 返回可访问的 COS URL（供 LKEAP 文档解析使用）
    - 支持 COS 签名 V5（HMAC-SHA1）

使用方式：
    client = TencentCOSClient(
        secret_id=os.getenv("COS_SECRET_ID"),
        secret_key=os.getenv("COS_SECRET_KEY"),
        bucket="domainverify-1253467224",
        region="ap-beijing",
    )
    url = client.upload_file("/tmp/doc.pdf", "knowledge/tenant_1/abc.pdf")
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import mimetypes
import os
import time
from pathlib import Path

import requests

logger = logging.getLogger(__name__)

# 常见文件类型 → Content-Type 映射（补充 mimetypes 可能缺失的）
_EXTRA_MIME_TYPES = {
    ".pdf": "application/pdf",
    ".doc": "application/msword",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".ppt": "application/vnd.ms-powerpoint",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".xls": "application/vnd.ms-excel",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".md": "text/markdown",
    ".txt": "text/plain",
    ".csv": "text/csv",
    ".html": "text/html",
    ".epub": "application/epub+zip",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
}


def _guess_content_type(file_name: str) -> str:
    """根据文件名推断 Content-Type"""
    ext = os.path.splitext(file_name)[1].lower()
    if ext in _EXTRA_MIME_TYPES:
        return _EXTRA_MIME_TYPES[ext]
    mime, _ = mimetypes.guess_type(file_name)
    return mime or "application/octet-stream"


class TencentCOSClient:
    """腾讯云 COS 客户端（签名 V5，PUT Object）

    Args:
        secret_id: 腾讯云 SecretId
        secret_key: 腾讯云 SecretKey
        bucket: 存储桶名称（含 APPID 后缀）
        region: 地域，如 ap-beijing
        key_prefix: 对象 key 前缀，如 "knowledge/"
    """

    def __init__(
        self,
        secret_id: str,
        secret_key: str,
        bucket: str,
        region: str = "ap-beijing",
        key_prefix: str = "knowledge/",
    ) -> None:
        if not secret_id or not secret_key:
            raise ValueError(
                "COS 凭证未配置。请设置环境变量 COS_SECRET_ID / COS_SECRET_KEY"
            )
        self._secret_id = secret_id
        self._secret_key = secret_key
        self._bucket = bucket
        self._region = region
        self._key_prefix = key_prefix.rstrip("/") + "/" if key_prefix else ""
        self._host = f"{bucket}.cos.{region}.myqcloud.com"
        logger.info(
            "TencentCOSClient initialized: host=%s prefix=%s secret_id=%s secret_key_len=%d",
            self._host, self._key_prefix,
            self._secret_id[:10] + "...",
            len(self._secret_key),
        )

    @property
    def host(self) -> str:
        return self._host

    def _sign(self, method: str, key: str, headers: dict[str, str]) -> str:
        """生成 COS 签名 V5（q-sign-algorithm=sha1）

        参考：https://cloud.tencent.com/document/product/436/7778
        """
        now = int(time.time())
        sign_time = f"{now - 60};{now + 3600}"

        # 1. HttpString
        # 格式: HttpMethod\nUriPathname\nHttpParameters\nHttpHeaders\n
        lower_headers = {k.lower(): v for k, v in headers.items()}
        # 只签 host 头
        signed_header_list = "host"
        signed_headers_str = f"host={lower_headers.get('host', self._host)}"

        http_string = f"{method.lower()}\n/{key}\n\n{signed_headers_str}\n"

        # 2. StringToSign
        sha1_http = hashlib.sha1(http_string.encode()).hexdigest()
        string_to_sign = f"sha1\n{sign_time}\n{sha1_http}\n"

        # 3. SignKey
        sign_key = hmac.new(
            self._secret_key.encode(), sign_time.encode(), hashlib.sha1,
        ).hexdigest()

        # 4. Signature
        signature = hmac.new(
            sign_key.encode(), string_to_sign.encode(), hashlib.sha1,
        ).hexdigest()

        logger.debug(
            "COS sign debug: method=%s key=%s sign_time=%s "
            "format_string=%r string_to_sign=%r "
            "secret_id=%s secret_key_prefix=%s sign_key=%s signature=%s",
            method, key, sign_time,
            http_string, string_to_sign,
            self._secret_id[:8] + "...",
            self._secret_key[:4] + "***" + self._secret_key[-4:],
            sign_key, signature,
        )

        auth = (
            f"q-sign-algorithm=sha1"
            f"&q-ak={self._secret_id}"
            f"&q-sign-time={sign_time}"
            f"&q-key-time={sign_time}"
            f"&q-header-list={signed_header_list}"
            f"&q-url-param-list="
            f"&q-signature={signature}"
        )
        return auth

    def upload_file(
        self,
        local_path: str,
        object_key: str | None = None,
        content_type: str | None = None,
    ) -> str:
        """上传本地文件到 COS

        Args:
            local_path: 本地文件路径
            object_key: COS 对象 key（不含前缀）。为 None 时自动用文件名
            content_type: 文件 MIME 类型。为 None 时自动推断

        Returns:
            上传成功后的 COS URL（https://{bucket}.cos.{region}.myqcloud.com/{key}）

        Raises:
            FileNotFoundError: 本地文件不存在
            RuntimeError: 上传失败（HTTP 非 200）
        """
        path = Path(local_path)
        if not path.exists():
            raise FileNotFoundError(f"文件不存在: {local_path}")

        if object_key is None:
            object_key = path.name

        # 拼接完整 key（含前缀）
        full_key = f"{self._key_prefix}{object_key}"

        if content_type is None:
            content_type = _guess_content_type(path.name)

        url = f"https://{self._host}/{full_key}"

        headers = {
            "Host": self._host,
            "Content-Type": content_type,
        }

        # 生成签名
        auth = self._sign("put", full_key, headers)
        headers["Authorization"] = auth

        # 读取文件并上传
        file_size = path.stat().st_size
        logger.info(
            "COS uploading: key=%s size=%d content_type=%s",
            full_key, file_size, content_type,
        )

        with open(local_path, "rb") as f:
            data = f.read()

        resp = requests.put(url, data=data, headers=headers, timeout=300)

        if resp.status_code in (200, 204):
            logger.info("COS upload success: key=%s url=%s", full_key, url)
            return url
        else:
            error_msg = (
                f"COS upload failed: status={resp.status_code} "
                f"key={full_key} response={resp.text[:500]}"
            )
            logger.error(
                "COS upload_file failed: status=%d key=%s url=%s "
                "secret_id=%s host=%s content_type=%s file_size=%d "
                "response_body=%s",
                resp.status_code, full_key, url,
                self._secret_id[:10] + "...",
                self._host, content_type, file_size,
                resp.text[:800],
            )
            raise RuntimeError(error_msg)

    def upload_bytes(
        self,
        data: bytes,
        object_key: str,
        content_type: str = "application/octet-stream",
    ) -> str:
        """上传字节数据到 COS

        Args:
            data: 文件内容字节
            object_key: COS 对象 key（不含前缀）
            content_type: MIME 类型

        Returns:
            上传成功后的 COS URL
        """
        full_key = f"{self._key_prefix}{object_key}"
        url = f"https://{self._host}/{full_key}"

        headers = {
            "Host": self._host,
            "Content-Type": content_type,
        }

        auth = self._sign("put", full_key, headers)
        headers["Authorization"] = auth

        logger.info(
            "COS uploading bytes: key=%s size=%d content_type=%s",
            full_key, len(data), content_type,
        )

        resp = requests.put(url, data=data, headers=headers, timeout=300)

        if resp.status_code in (200, 204):
            logger.info("COS upload success: key=%s url=%s", full_key, url)
            return url
        else:
            error_msg = (
                f"COS upload failed: status={resp.status_code} "
                f"key={full_key} response={resp.text[:500]}"
            )
            logger.error(
                "COS upload_bytes failed: status=%d key=%s url=%s "
                "secret_id=%s host=%s content_type=%s data_size=%d "
                "response_body=%s",
                resp.status_code, full_key, url,
                self._secret_id[:10] + "...",
                self._host, content_type, len(data),
                resp.text[:800],
            )
            raise RuntimeError(error_msg)

    def generate_presigned_url(
        self,
        object_key: str,
        expires: int = 3600,
    ) -> str:
        """生成预签名下载 URL（GET 请求）

        Args:
            object_key: COS 对象 key（不含前缀，与 upload_file 时传入的一致）
            expires: 签名有效期（秒），默认 1 小时

        Returns:
            带签名参数的 HTTPS URL，可直接在浏览器中访问/预览
        """
        full_key = f"{self._key_prefix}{object_key}"
        now = int(time.time())
        sign_time = f"{now - 60};{now + expires}"

        # HttpString: method\nuri\nparams\nheaders\n
        http_string = f"get\n/{full_key}\n\nhost={self._host}\n"

        # StringToSign
        sha1_http = hashlib.sha1(http_string.encode()).hexdigest()
        string_to_sign = f"sha1\n{sign_time}\n{sha1_http}\n"

        # SignKey
        sign_key = hmac.new(
            self._secret_key.encode(), sign_time.encode(), hashlib.sha1,
        ).hexdigest()

        # Signature
        signature = hmac.new(
            sign_key.encode(), string_to_sign.encode(), hashlib.sha1,
        ).hexdigest()

        # 拼接带签名参数的 URL
        auth_params = (
            f"q-sign-algorithm=sha1"
            f"&q-ak={self._secret_id}"
            f"&q-sign-time={sign_time}"
            f"&q-key-time={sign_time}"
            f"&q-header-list=host"
            f"&q-url-param-list="
            f"&q-signature={signature}"
        )
        url = f"https://{self._host}/{full_key}?{auth_params}"
        logger.debug("COS presigned URL generated: key=%s expires=%ds", full_key, expires)
        return url

    def get_presigned_url_from_raw(
        self,
        raw_url: str,
        expires: int = 3600,
    ) -> str:
        """从已存储的 raw_url 反推 object_key 并生成预签名 URL

        Args:
            raw_url: 存储在 PG 中的 COS URL（如 https://bucket.cos.region.myqcloud.com/knowledge/...）
            expires: 签名有效期（秒）

        Returns:
            预签名下载 URL

        Raises:
            ValueError: raw_url 不是有效的 COS URL
        """
        prefix = f"https://{self._host}/"
        if not raw_url.startswith(prefix):
            raise ValueError(
                f"raw_url 不是当前 COS 存储桶的 URL: {raw_url[:100]}"
            )
        # 提取完整 key（含 key_prefix）
        full_key = raw_url[len(prefix):]

        now = int(time.time())
        sign_time = f"{now - 60};{now + expires}"

        http_string = f"get\n/{full_key}\n\nhost={self._host}\n"
        sha1_http = hashlib.sha1(http_string.encode()).hexdigest()
        string_to_sign = f"sha1\n{sign_time}\n{sha1_http}\n"

        sign_key = hmac.new(
            self._secret_key.encode(), sign_time.encode(), hashlib.sha1,
        ).hexdigest()

        signature = hmac.new(
            sign_key.encode(), string_to_sign.encode(), hashlib.sha1,
        ).hexdigest()

        auth_params = (
            f"q-sign-algorithm=sha1"
            f"&q-ak={self._secret_id}"
            f"&q-sign-time={sign_time}"
            f"&q-key-time={sign_time}"
            f"&q-header-list=host"
            f"&q-url-param-list="
            f"&q-signature={signature}"
        )
        url = f"https://{self._host}/{full_key}?{auth_params}"
        logger.debug("COS presigned URL from raw: raw=%s expires=%ds", raw_url[:60], expires)
        return url

    def build_object_key(
        self,
        tenant_id: int,
        knowledge_base_id: int,
        doc_id: str,
        file_name: str,
    ) -> str:
        """构建标准化的 COS 对象 key

        格式: {tenant_id}/{knowledge_base_id}/{doc_id}/{file_name}
        """
        # 清理文件名中的特殊字符
        safe_name = file_name.replace("/", "_").replace("\\", "_")
        return f"{tenant_id}/{knowledge_base_id}/{doc_id}/{safe_name}"
