"""FeignClient 实现 — 基于可插拔 Transport 的远程调用

传输层抽象：
    - 生产环境: NeoApiTransport（基于 NeoApiClient，自动传递上下文+trace）
    - 开发环境: HttpxTransport（基于 httpx，直连无依赖）

路由规范：
    - Tool:       POST /v2/tools/{api_key}/execute  → execute_tool
    - Middleware:  POST /v2/middlewares/{api_key}/execute → execute_middleware
"""
from __future__ import annotations

import logging
from typing import Any, Callable

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════
# ServiceResolver（保留，供 HttpxTransport 使用）
# ═══════════════════════════════════════════════════════════

class ServiceResolver:
    """服务名解析器 — 将 app_name 解析为实际服务地址

    支持多种解析策略：
    - 静态配置（开发/测试环境）
    - K8s DNS
    - 自定义解析函数
    """

    def __init__(
        self,
        static_map: dict[str, str] | None = None,
        k8s_namespace: str = "",
        k8s_port: int = 8080,
        custom_resolver: Callable[[str], str] | None = None,
    ):
        """初始化服务解析器

        Args:
            static_map: 静态服务名→地址映射（优先级最高）。
            k8s_namespace: K8s 命名空间，非空时启用 K8s DNS 解析。
            k8s_port: K8s Service 默认端口。
            custom_resolver: 自定义解析函数。
        """
        self._static_map = static_map or {}
        self._k8s_namespace = k8s_namespace
        self._k8s_port = k8s_port
        self._custom_resolver = custom_resolver

    def resolve(self, app_name: str) -> str:
        """将服务名解析为 HTTP 基础地址

        Args:
            app_name: 服务名（如 "neo-ai-salescloud-service"）。

        Returns:
            服务基础地址（如 "http://neo-ai-salescloud-service:8080"）。
        """
        if app_name in self._static_map:
            return self._static_map[app_name]
        if self._custom_resolver:
            return self._custom_resolver(app_name)
        if self._k8s_namespace:
            return f"http://{app_name}.{self._k8s_namespace}.svc.cluster.local:{self._k8s_port}"
        return f"http://{app_name}:{self._k8s_port}"


# ═══════════════════════════════════════════════════════════
# ToolFeignClient
# ═══════════════════════════════════════════════════════════

class ToolFeignClient:
    """Tool Provider 的 FeignClient 实现

    底层通过 Transport 发起调用：
    - 生产环境传入 NeoApiTransport → 自动带上下文+trace
    - 开发环境传入 HttpxTransport → 直连无依赖

    Usage:
        # 生产环境
        from neo_ai_registry.feign.transport import NeoApiTransport
        client = ToolFeignClient(app_name="neo-ai-salescloud-service", transport=NeoApiTransport())

        # 开发环境
        from neo_ai_registry.feign.transport import HttpxTransport
        resolver = ServiceResolver(static_map={"neo-ai-provider-demo": "http://localhost:8002"})
        client = ToolFeignClient(app_name="neo-ai-provider-demo", transport=HttpxTransport(resolver=resolver))

        result = client.execute_tool("query_customer", {"customer_name": "仁科"})
    """

    def __init__(
        self,
        app_name: str = "",
        transport: Any = None,
        resolver: ServiceResolver | None = None,
    ):
        """初始化 ToolFeignClient

        Args:
            app_name: 目标业务域服务名（如 "neo-ai-salescloud-service"）。
            transport: 传输层实例（Transport 子类）。
                       传 None 时自动创建 HttpxTransport（开发模式）。
            resolver: 服务名解析器（仅在 transport=None 时用于创建默认 HttpxTransport）。
        """
        self._app_name = app_name
        if transport:
            self._transport = transport
        else:
            from neo_ai_registry.feign.transport import HttpxTransport
            self._transport = HttpxTransport(resolver=resolver)

    def execute_tool(
        self,
        api_key: str,
        input_data: dict[str, Any],
        state: Any = None,
        stream: bool = False,
    ) -> dict[str, Any] | Any:
        """远程执行 Tool（支持 state 双向传递 + SSE 流式）

        Args:
            api_key: Tool 唯一标识。
            input_data: Tool 入参字典。
            state: ToolState 实例或 dict。
            stream: 是否请求 SSE 流式响应。为 True 时返回 generator。

        Returns:
            stream=False: {"result": ..., "state_patch": ...}
            stream=True: generator，逐 chunk yield dict
        """
        from neo_ai_registry.state import ToolState

        # 序列化 state
        if isinstance(state, ToolState):
            state_dict = state.to_dict()
        elif isinstance(state, dict):
            state_dict = state
        else:
            state_dict = {}

        payload: dict[str, Any] = {"input": input_data}
        if state_dict:
            payload["state"] = state_dict

        if stream:
            return self._stream_invoke(api_key, payload, state)

        response = self._transport.invoke(
            app_name=self._app_name,
            service=f"/v2/tools/{api_key}/execute",
            method="POST",
            data=payload,
        )

        # 如果 Agent 传入了 ToolState 实例，自动 merge 回写
        if isinstance(state, ToolState) and isinstance(response, dict):
            patch = response.get("state_patch", {})
            if patch:
                state.merge_patch(patch)

        return response

    def _stream_invoke(self, api_key: str, payload: dict, state: Any):
        """SSE 流式调用 — 返回 generator"""
        import httpx
        from neo_ai_registry.state import ToolState

        # 需要直接用 httpx 发 SSE 请求（Transport 不支持流式）
        from neo_ai_registry.feign.client import ServiceResolver
        if hasattr(self._transport, '_resolver'):
            base_url = self._transport._resolver.resolve(self._app_name)
        else:
            base_url = f"http://{self._app_name}:8080"

        url = f"{base_url}/v2/tools/{api_key}/execute"

        def stream_generator():
            import json
            with httpx.stream("POST", url, json=payload, headers={"Content-Type": "application/json"}, timeout=60) as resp:
                for line in resp.iter_lines():
                    if not line:
                        continue
                    if line.startswith("event: state_patch"):
                        # 下一行是 state_patch data
                        continue
                    if line.startswith("event: done"):
                        break
                    if line.startswith("data: "):
                        data_str = line[6:]
                        try:
                            chunk = json.loads(data_str)
                            # 检查是否是 state_patch
                            if isinstance(chunk, dict) and "last_query_entity" in chunk:
                                # state_patch event
                                if isinstance(state, ToolState):
                                    state.merge_patch(chunk)
                            else:
                                yield chunk
                        except json.JSONDecodeError:
                            pass

        return stream_generator()


# ═══════════════════════════════════════════════════════════
# MiddlewareFeignClient
# ═══════════════════════════════════════════════════════════

class MiddlewareFeignClient:
    """Middleware Provider 的 FeignClient 实现

    底层通过 Transport 发起调用，与 ToolFeignClient 一致。
    """

    def __init__(
        self,
        app_name: str = "",
        transport: Any = None,
        resolver: ServiceResolver | None = None,
    ):
        """初始化 MiddlewareFeignClient

        Args:
            app_name: 目标业务域服务名。
            transport: 传输层实例。传 None 时创建 HttpxTransport。
            resolver: 服务名解析器（transport=None 时使用）。
        """
        self._app_name = app_name
        if transport:
            self._transport = transport
        else:
            from neo_ai_registry.feign.transport import HttpxTransport
            self._transport = HttpxTransport(resolver=resolver)

    def execute_middleware(
        self,
        api_key: str,
        hook: str,
        payload: dict[str, Any],
        state: Any = None,
    ) -> dict[str, Any]:
        """远程执行 Middleware 钩子（支持 state 双向传递）

        Args:
            api_key: Middleware 唯一标识。
            hook: 生命周期钩子名称。
            payload: 钩子入参字典。
            state: ToolState 实例或 dict。

        Returns:
            {"result": Middleware执行结果, "state_patch": Provider回写的状态增量}
        """
        from neo_ai_registry.state import ToolState

        if isinstance(state, ToolState):
            state_dict = state.to_dict()
        elif isinstance(state, dict):
            state_dict = state
        else:
            state_dict = {}

        request_data: dict[str, Any] = {
            "hook": hook,
            "payload": payload,
        }
        if state_dict:
            request_data["state"] = state_dict

        response = self._transport.invoke(
            app_name=self._app_name,
            service=f"/v2/middlewares/{api_key}/execute",
            method="POST",
            data=request_data,
        )

        if isinstance(state, ToolState) and isinstance(response, dict):
            patch = response.get("state_patch", {})
            if patch:
                state.merge_patch(patch)

        return response
