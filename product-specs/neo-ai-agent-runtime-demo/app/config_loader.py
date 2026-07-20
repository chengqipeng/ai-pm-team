"""配置加载器 — 从 YAML 文件加载注册数据（模拟数据库）

实际生产环境从数据库读取 Tool/Middleware 注册信息，
此处通过配置文件 config/registry.yaml 初始化，便于开发和测试。
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

_DEFAULT_CONFIG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(__file__)),
    "config", "registry.yaml",
)


@dataclass
class ToolConfig:
    """Tool 配置项（从 YAML 解析）"""
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
    """Middleware 配置项（从 YAML 解析）"""
    api_key: str
    name: str = ""
    description: str = ""
    service: str = ""
    hooks: list[str] = field(default_factory=list)
    sort_num: int = 0
    required_features: list[str] = field(default_factory=list)


@dataclass
class RegistryConfig:
    """注册配置全量数据"""
    services: dict[str, str] = field(default_factory=dict)
    tools: list[ToolConfig] = field(default_factory=list)
    middlewares: list[MiddlewareConfig] = field(default_factory=list)


def load_registry_config(config_path: str = "") -> RegistryConfig:
    """从 YAML 配置文件加载注册数据

    Args:
        config_path: 配置文件路径。为空时使用默认路径 config/registry.yaml。

    Returns:
        RegistryConfig 实例，包含 services/tools/middlewares 全量配置。

    Raises:
        FileNotFoundError: 配置文件不存在时抛出。
    """
    path = Path(config_path or _DEFAULT_CONFIG_PATH)
    if not path.exists():
        raise FileNotFoundError(f"注册配置文件不存在: {path}")

    with open(path, encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}

    # 解析 services
    services = raw.get("services", {})

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

    logger.info(
        "注册配置加载完成: %d services, %d tools, %d middlewares",
        len(services), len(tools), len(middlewares),
    )
    return RegistryConfig(services=services, tools=tools, middlewares=middlewares)
