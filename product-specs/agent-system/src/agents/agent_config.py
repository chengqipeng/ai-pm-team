"""AgentConfig + AgentLoader + AgentRegistry — YAML 定义自动发现

AgentConfig: 统一 Agent 配置数据模型
AgentLoader: 从 definitions/ 目录发现和加载 agent.yaml
AgentRegistry: 全局 Agent 配置注册表
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Any

import yaml

logger = logging.getLogger(__name__)


@dataclass
class Features:
    """Agent 特性开关"""
    memory_enabled: bool = True
    subagent_enabled: bool = True
    guardrail_enabled: bool = True
    mcp_enabled: bool = False
    skill_autogen_enabled: bool = False

    @classmethod
    def from_config(cls, config: dict[str, Any]) -> Features:
        known = {f.name for f in cls.__dataclass_fields__.values()}
        filtered = {k: bool(v) for k, v in config.items() if k in known}
        return cls(**filtered)


@dataclass
class AgentConfig:
    """Agent 配置 — 描述一个完整的 Agent 实例"""
    name: str
    description: str = ""
    system_prompt: str = ""
    model: str = ""
    middleware_names: list[str] = field(default_factory=list)
    middleware_config: dict[str, Any] = field(default_factory=dict)
    inherit_middleware: bool = True
    tool_names: list[str] = field(default_factory=list)
    skill_names: list[str] = field(default_factory=list)
    features: Features = field(default_factory=Features)
    base_dir: str = ""


class AgentRegistry:
    """全局 Agent 配置注册表"""

    def __init__(self) -> None:
        self._configs: dict[str, AgentConfig] = {}

    def register(self, config: AgentConfig) -> None:
        if not config.name:
            raise ValueError("Agent 名称不能为空")
        if config.name in self._configs:
            logger.warning("覆盖已注册的 Agent: %s", config.name)
        self._configs[config.name] = config
        logger.info("已注册 Agent: %s", config.name)

    def get(self, name: str) -> AgentConfig | None:
        return self._configs.get(name)

    def list_all(self) -> list[str]:
        return list(self._configs.keys())

    def __len__(self) -> int:
        return len(self._configs)

    def __contains__(self, name: str) -> bool:
        return name in self._configs


class AgentLoader:
    """从 definitions/ 目录发现和加载所有 Agent 配置"""

    def __init__(self, definitions_dir: str = "") -> None:
        self._definitions_dir = definitions_dir

    def discover(self) -> list[AgentConfig]:
        """扫描 definitions/ 下所有子目录，解析 agent.yaml"""
        if not self._definitions_dir or not os.path.isdir(self._definitions_dir):
            logger.warning("Agent definitions 目录不存在: %s", self._definitions_dir)
            return []

        configs: list[AgentConfig] = []
        for entry in sorted(os.listdir(self._definitions_dir)):
            agent_dir = os.path.join(self._definitions_dir, entry)
            if not os.path.isdir(agent_dir):
                continue
            yaml_path = os.path.join(agent_dir, "agent.yaml")
            if not os.path.isfile(yaml_path):
                continue
            try:
                config = self._load_yaml(yaml_path, agent_dir)
                configs.append(config)
            except Exception:
                logger.warning("Agent 配置加载失败: %s", yaml_path, exc_info=True)

        logger.info("发现 %d 个 Agent 定义: %s", len(configs), [c.name for c in configs])
        return configs

    def load(self, agent_name: str) -> AgentConfig:
        """按名称加载指定 Agent 配置"""
        agent_dir = os.path.join(self._definitions_dir, agent_name)
        yaml_path = os.path.join(agent_dir, "agent.yaml")
        if not os.path.isfile(yaml_path):
            raise FileNotFoundError(f"Agent '{agent_name}' 配置不存在: {yaml_path}")
        return self._load_yaml(yaml_path, agent_dir)

    def _load_yaml(self, yaml_path: str, agent_dir: str) -> AgentConfig:
        with open(yaml_path, encoding="utf-8") as f:
            raw: dict[str, Any] = yaml.safe_load(f) or {}

        name = raw.get("name", os.path.basename(agent_dir))
        mw = raw.get("middleware", {})
        features_raw = raw.get("features", {})
        features = Features.from_config(features_raw) if features_raw else Features()

        return AgentConfig(
            name=name,
            description=raw.get("description", ""),
            system_prompt=raw.get("system_prompt", ""),
            model=raw.get("model", ""),
            middleware_names=mw.get("names", []) or [],
            middleware_config=mw.get("config", {}) or {},
            inherit_middleware=mw.get("inherit", True),
            tool_names=raw.get("tools", []) or [],
            skill_names=raw.get("skills", []) or [],
            features=features,
            base_dir=agent_dir,
        )
