"""ConfigLoader — 从 YAML/dict 加载注册配置

纯 IO + 解析，不关心注册逻辑。
AgentRegistry 消费 ConfigLoader 输出的 RegistryConfig。

Usage:
    # 从 YAML 文件加载
    config = ConfigLoader.from_yaml("config/registry. ")

    # 从 dict 加载（测试 / DB 场景）
    config = ConfigLoader.from_dict({"tools": [...], "middlewares": [...]})

    # 传给 AgentRegistry
    registry = AgentRegistry(transport)
    registry.load(config, scan_tools_dir="app/tools")
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════
# 配置数据结构
# ═══════════════════════════════════════════════════════════

@dataclass
class ToolConfig:
    """Tool 配置项"""
    api_key: str
    name: str = ""
    description: str = ""
    domain: str = ""
    type: str = "remote"
    service: str = ""
    input_schema: dict[str, Any] = field(default_factory=dict)
    timeout_ms: int = 5000
    read_only_flg: bool = True
    category: str = ""
    tags: list[str] = field(default_factory=list)


@dataclass
class MiddlewareConfig:
    """Middleware 配置项"""
    api_key: str
    name: str = ""
    description: str = ""
    service: str = ""
    hooks: list[str] = field(default_factory=list)
    sort_num: int = 0
    required_features: list[str] = field(default_factory=list)


@dataclass
class ScanConfig:
    """Builtin 扫描配置"""
    tools_dir: str = "app/tools"
    middlewares_dir: str = "app/middlewares"


@dataclass
class RegistryConfig:
    """注册配置全量数据"""
    scan: ScanConfig = field(default_factory=ScanConfig)
    tools: list[ToolConfig] = field(default_factory=list)
    middlewares: list[MiddlewareConfig] = field(default_factory=list)


# ═══════════════════════════════════════════════════════════
# ConfigLoader
# ═══════════════════════════════════════════════════════════

class ConfigLoader:
    """配置加载器 — 从 YAML/dict 解析 RegistryConfig"""

    @staticmethod
    def from_yaml(config_path: str) -> RegistryConfig:
        """从 YAML 文件加载

        Args:
            config_path: YAML 文件路径。

        Returns:
            RegistryConfig 实例。

        Raises:
            FileNotFoundError: 文件不存在时抛出。
        """
        path = Path(config_path)
        if not path.exists():
            raise FileNotFoundError(f"注册配置文件不存在: {path}")

        with open(path, encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}

        return ConfigLoader.from_dict(raw)

    @staticmethod
    def from_dict(raw: dict[str, Any]) -> RegistryConfig:
        """从 dict 加载（测试 / DB 场景）

        Args:
            raw: 配置字典。

        Returns:
            RegistryConfig 实例。
        """
        # 解析 scan
        scan_raw = raw.get("scan", {})
        scan = ScanConfig(
            tools_dir=scan_raw.get("tools_dir", "app/tools"),
            middlewares_dir=scan_raw.get("middlewares_dir", "app/middlewares"),
        )

        # 解析 tools
        tools = []
        for item in raw.get("tools", []):
            tools.append(ToolConfig(
                api_key=item["api_key"],
                name=item.get("name", ""),
                description=item.get("description", ""),
                domain=item.get("domain", ""),
                type=item.get("type", "remote"),
                service=item.get("service", ""),
                input_schema=item.get("input_schema", {}),
                timeout_ms=item.get("timeout_ms", 5000),
                read_only_flg=item.get("read_only_flg", True),
                category=item.get("category", ""),
                tags=item.get("tags", []),
            ))

        # 解析 middlewares
        middlewares = []
        for item in raw.get("middlewares", []):
            middlewares.append(MiddlewareConfig(
                api_key=item["api_key"],
                name=item.get("name", ""),
                description=item.get("description", ""),
                service=item.get("service", ""),
                hooks=item.get("hooks", []),
                sort_num=item.get("sort_num", 0),
                required_features=item.get("required_features", []),
            ))

        logger.info("配置加载完成: scan=%s, %d tools, %d middlewares", scan, len(tools), len(middlewares))
        return RegistryConfig(scan=scan, tools=tools, middlewares=middlewares)
