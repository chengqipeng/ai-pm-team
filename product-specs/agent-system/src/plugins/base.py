"""
Plugin 体系 — 可插拔基础设施模块

对应产品设计 §3.10:
Plugin 是系统的器官 — 有生命周期、有配置、有状态、可替换。
Tool 通过 PluginContext 调用 Plugin 的接口，Plugin 不直接注册 Tool。

Plugin 分层:
  platform: 平台级（llm / memory / search / notification）
  industry: 行业级（crm / hr / finance）
  tenant:   租户级（自定义）
"""
from __future__ import annotations

import logging
from typing import Any, Protocol, runtime_checkable
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@runtime_checkable
class Plugin(Protocol):
    """Plugin 接口 — 所有 Plugin 必须实现"""
    name: str

    async def initialize(self) -> None:
        """初始化 Plugin（连接数据库、加载配置等）"""
        ...

    async def shutdown(self) -> None:
        """关闭 Plugin（释放连接、清理资源）"""
        ...

    async def health_check(self) -> bool:
        """健康检查"""
        return True


@dataclass
class PluginManifest:
    """Plugin 清单"""
    name: str
    version: str = "1.0.0"
    description: str = ""
    plugin_type: str = "platform"  # platform / industry / tenant
    required: bool = False
    default_enabled: bool = True
    config: dict[str, Any] = field(default_factory=dict)


class PluginRegistry:
    """
    Plugin 注册表 — 管理 Plugin 的注册、初始化、关闭

    生命周期:
    register → initialize_all → (运行期间) → shutdown_all
    """

    def __init__(self):
        self._plugins: dict[str, Plugin] = {}
        self._manifests: dict[str, PluginManifest] = {}
        self._initialized: set[str] = set()

    def register(self, plugin: Plugin, manifest: PluginManifest | None = None) -> None:
        """注册 Plugin"""
        name = plugin.name
        self._plugins[name] = plugin
        if manifest:
            self._manifests[name] = manifest
        logger.info(f"Plugin registered: {name}")

    def get(self, name: str) -> Plugin | None:
        """获取 Plugin 实例"""
        return self._plugins.get(name)

    def get_manifest(self, name: str) -> PluginManifest | None:
        return self._manifests.get(name)

    async def initialize_all(self) -> None:
        """初始化所有已注册的 Plugin"""
        for name, plugin in self._plugins.items():
            if name in self._initialized:
                continue
            try:
                await plugin.initialize()
                self._initialized.add(name)
                logger.info(f"Plugin initialized: {name}")
            except Exception as e:
                logger.error(f"Plugin init failed: {name}: {e}")
                manifest = self._manifests.get(name)
                if manifest and manifest.required:
                    raise  # 必选 Plugin 初始化失败 → 抛出

    async def shutdown_all(self) -> None:
        """关闭所有已初始化的 Plugin"""
        for name in list(self._initialized):
            try:
                await self._plugins[name].shutdown()
                self._initialized.discard(name)
                logger.info(f"Plugin shutdown: {name}")
            except Exception as e:
                logger.warning(f"Plugin shutdown error: {name}: {e}")

    async def health_check_all(self) -> dict[str, bool]:
        """检查所有 Plugin 的健康状态"""
        results = {}
        for name, plugin in self._plugins.items():
            try:
                results[name] = await plugin.health_check()
            except Exception:
                results[name] = False
        return results

    @property
    def all_plugins(self) -> list[Plugin]:
        return list(self._plugins.values())

    @property
    def initialized_plugins(self) -> list[str]:
        return list(self._initialized)


# ═══════════════════════════════════════════════════════════
# 内置 Plugin 实现
# ═══════════════════════════════════════════════════════════

class MemoryPlugin:
    """
    记忆 Plugin — 对应产品设计 §4.7.2

    提供 recall / commit 接口，后端可替换（filesystem / pgvector / elasticsearch）
    """
    name = "memory"

    def __init__(self, backend: str = "memory", config: dict | None = None):
        self._backend = backend
        self._config = config or {}
        self._store: list[dict] = []

    async def initialize(self) -> None:
        logger.info(f"MemoryPlugin initialized (backend={self._backend})")

    async def shutdown(self) -> None:
        pass

    async def health_check(self) -> bool:
        return True

    async def recall(self, query: str, categories: list[str] | None = None, max_results: int = 5) -> list[dict]:
        results = []
        for entry in self._store:
            if categories and entry.get("category") not in categories:
                continue
            # 简单关键词匹配
            content = entry.get("content", "").lower()
            if any(query[i:i+2] in content for i in range(len(query)-1) if len(query) > 1):
                results.append(entry)
            elif categories:  # category 过滤时直接返回
                results.append(entry)
            if len(results) >= max_results:
                break
        return results

    async def commit(self, entry: dict) -> None:
        self._store.append(entry)

    def seed(self, entries: list[dict]) -> None:
        """预置记忆数据"""
        self._store.extend(entries)


class NotificationPlugin:
    """通知 Plugin — 对应产品设计 §4.7.3"""
    name = "notification"

    def __init__(self, channels: list[str] | None = None):
        self._channels = channels or ["in_app"]
        self._sent: list[dict] = []

    async def initialize(self) -> None:
        logger.info(f"NotificationPlugin initialized (channels={self._channels})")

    async def shutdown(self) -> None:
        pass

    async def health_check(self) -> bool:
        return True

    async def send(self, message: str, channel: str = "in_app", **kwargs) -> bool:
        self._sent.append({"message": message, "channel": channel, **kwargs})
        logger.info(f"Notification sent ({channel}): {message[:50]}")
        return True

    @property
    def sent_messages(self) -> list[dict]:
        return self._sent
