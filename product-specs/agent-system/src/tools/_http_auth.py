"""
paas-platform-service HTTP 客户端共用基础设施 —— 自动登录 + 401 重登

AuthTokenInterceptor 不支持 dev 旁路，所有 /meta/* 和 /entity/data/* 调用都要求
Authorization: Bearer <JWT>。这里通过 /auth/login 自动换取 token，token 过期后
401 自动重登一次。

环境变量：
  METAREPO_API_BASE   paas-platform-service 基地址（必须）
  METAREPO_TOKEN      直接提供 JWT（若配置则跳过自动登录）
  METAREPO_PHONE      登录手机号（默认 13800000001，seed 数据里租户 292193 下的张伟）
  METAREPO_PASSWORD   登录密码（默认 123456，paas-platform-service dev 硬编码）
  METAREPO_TENANT_ID / DEFAULT_TENANT_ID  覆盖登录 tenantId（默认 292193）
"""
from __future__ import annotations

import asyncio
import logging
import os
from typing import Any, Optional

import httpx

logger = logging.getLogger(__name__)


class AuthClient:
    """懒登录 + 401 重登的共享 token 源。

    同一个 AuthClient 可以被多个 backend 共享（metarepo + entity-data），
    token 也共享一份。
    """

    def __init__(
        self,
        base_url: str,
        *,
        phone: Optional[str] = None,
        password: Optional[str] = None,
        tenant_id: Optional[str] = None,
        initial_token: Optional[str] = None,
        extra_headers: Optional[dict[str, str]] = None,
        timeout: float = 10.0,
    ):
        self._base = base_url.rstrip("/")
        self._phone = phone or os.getenv("METAREPO_PHONE", "13800000001")
        self._password = password or os.getenv("METAREPO_PASSWORD", "123456")
        self._tenant_id = str(tenant_id) if tenant_id is not None else None
        self._token = initial_token or os.getenv("METAREPO_TOKEN") or ""
        self._extra_headers = dict(extra_headers or {})
        self._timeout = timeout
        self._login_lock = asyncio.Lock()

    @property
    def base_url(self) -> str:
        return self._base

    async def _login(self) -> str:
        """调 /auth/login 拿 JWT，缓存并返回。"""
        body: dict[str, Any] = {"phone": self._phone, "password": self._password}
        if self._tenant_id:
            body["tenantId"] = int(self._tenant_id) if str(self._tenant_id).isdigit() else self._tenant_id

        async with httpx.AsyncClient(base_url=self._base, timeout=self._timeout) as cli:
            r = await cli.post("/auth/login", json=body, headers=self._extra_headers)
            r.raise_for_status()
            payload = r.json()

        if payload.get("code") != 200 or not payload.get("accessToken"):
            raise RuntimeError(f"paas-platform-service 登录失败: {payload}")
        token = payload["accessToken"]
        logger.info(
            "paas-platform-service 登录成功: tenant=%s user=%s",
            payload.get("user", {}).get("tenantId"),
            payload.get("user", {}).get("userId"),
        )
        self._token = token
        return token

    async def _ensure_token(self) -> str:
        if self._token:
            return self._token
        async with self._login_lock:
            if self._token:
                return self._token
            return await self._login()

    async def _refresh_token(self) -> str:
        async with self._login_lock:
            self._token = ""  # 强制下次 _login
            return await self._login()

    async def request(
        self,
        method: str,
        path: str,
        *,
        params: Optional[dict] = None,
        json: Any = None,
    ) -> Any:
        """发请求 + 401 自动重登一次。"""
        clean_params = None
        if params:
            clean_params = {k: v for k, v in params.items() if v is not None}

        headers = dict(self._extra_headers)
        headers.setdefault("Content-Type", "application/json")
        headers["Authorization"] = f"Bearer {await self._ensure_token()}"

        async with httpx.AsyncClient(
            base_url=self._base, timeout=self._timeout
        ) as cli:
            r = await cli.request(method, path, params=clean_params, json=json, headers=headers)
            if r.status_code == 401:
                logger.warning("paas-platform-service 401，尝试重新登录")
                headers["Authorization"] = f"Bearer {await self._refresh_token()}"
                r = await cli.request(method, path, params=clean_params, json=json, headers=headers)

            try:
                r.raise_for_status()
            except httpx.HTTPError as exc:
                logger.warning("HTTP %s %s failed: %s — %s", method, path, r.status_code, exc)
                raise

            if not r.content:
                return None
            payload = r.json()
            # 剥 {code, data} 响应壳
            if isinstance(payload, dict) and "code" in payload and "data" in payload:
                return payload["data"]
            return payload


# ─── 工厂：按环境变量构造一个 AuthClient ───

_shared_client: Optional[AuthClient] = None


def get_shared_auth_client() -> Optional[AuthClient]:
    """按环境变量构造一个全局共享的 AuthClient。

    未配置 METAREPO_API_BASE 时返回 None（调用方应回退到 sim backend）。
    """
    global _shared_client
    if _shared_client is not None:
        return _shared_client

    base = os.getenv("METAREPO_API_BASE", "").strip()
    if not base:
        return None

    from src.core.context import DEFAULT_TENANT_ID
    tenant_id = os.getenv("METAREPO_TENANT_ID") or str(DEFAULT_TENANT_ID)

    _shared_client = AuthClient(
        base_url=base,
        tenant_id=tenant_id,
        extra_headers={"X-Tenant-Id": tenant_id},
    )
    return _shared_client


def reset_shared_auth_client() -> None:
    """测试 / 重新加载环境变量时使用。"""
    global _shared_client
    _shared_client = None
