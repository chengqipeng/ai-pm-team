"""子 Agent 数据模型 + 注册表 — 对齐 v2 subagents/config.py + registry.py

SubagentDefinition: 轻量描述（name/description/task_type）
SubagentConfig: 完整配置（system_prompt/middleware/tools/skills）
SubagentTask: 一次委派请求
SubagentResult: 执行结果
SubagentRegistry: 双方法注册表（register + register_config）
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Iterator
from uuid import uuid4

logger = logging.getLogger(__name__)


class TaskType(str, Enum):
    IO = "io"
    CPU = "cpu"


@dataclass
class SubagentDefinition:
    """子 Agent 轻量定义"""
    name: str
    description: str
    task_type: TaskType = TaskType.IO
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class SubagentTask:
    """子 Agent 任务"""
    task_id: str
    agent_name: str
    instruction: str
    parent_thread_id: str
    context: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @staticmethod
    def create(agent_name: str, instruction: str, parent_thread_id: str,
               context: dict[str, Any] | None = None) -> SubagentTask:
        return SubagentTask(
            task_id=uuid4().hex, agent_name=agent_name,
            instruction=instruction, parent_thread_id=parent_thread_id,
            context=context or {},
        )


@dataclass
class SubagentResult:
    """子 Agent 执行结果"""
    task_id: str
    success: bool
    output: str
    error: str | None = None


@dataclass
class SubagentConfig:
    """子 Agent 完整配置"""
    name: str
    description: str = ""
    system_prompt: str = ""
    model: str = ""
    middleware_names: list[str] = field(default_factory=list)
    middleware_config: dict[str, Any] = field(default_factory=dict)
    inherit_middleware: bool = True
    tool_names: list[str] = field(default_factory=list)
    skill_names: list[str] = field(default_factory=list)
    features: dict[str, bool] = field(default_factory=dict)
    max_llm_calls: int = 20
    max_step_llm_calls: int = 10
    metadata: dict[str, Any] = field(default_factory=dict)


class SubagentRegistry:
    """子 Agent 注册表 — 双方法：Definition（轻量）+ Config（完整）"""

    def __init__(self) -> None:
        self._agents: dict[str, SubagentDefinition] = {}
        self._configs: dict[str, SubagentConfig] = {}

    # ── Definition 方法 ──

    def register(self, name_or_config: str | SubagentConfig | SubagentDefinition,
                 agent_def: SubagentDefinition | None = None) -> None:
        """注册子 Agent（兼容旧接口）"""
        if isinstance(name_or_config, SubagentConfig):
            # 旧接口：register(SubagentConfig)
            self._configs[name_or_config.name] = name_or_config
            return
        if isinstance(name_or_config, SubagentDefinition):
            self._agents[name_or_config.name] = name_or_config
            return
        if isinstance(name_or_config, str) and agent_def is not None:
            self._agents[name_or_config] = agent_def
            return
        raise ValueError(f"无效的注册参数: {type(name_or_config)}")

    def get(self, name: str) -> SubagentDefinition | SubagentConfig | None:
        """查找（优先 Config，其次 Definition）"""
        return self._configs.get(name) or self._agents.get(name)

    # ── Config 方法 ──

    def register_config(self, name: str, config: SubagentConfig) -> None:
        if not name:
            raise ValueError("子 Agent 配置名称不能为空")
        if name in self._configs:
            logger.warning("覆盖已注册的子 Agent 配置: %s", name)
        self._configs[name] = config
        logger.info("已注册子 Agent 配置: %s", name)

    def get_config(self, name: str) -> SubagentConfig | None:
        return self._configs.get(name)

    def get_definition(self, name: str) -> SubagentDefinition | None:
        return self._agents.get(name)

    # ── 通用方法 ──

    def list_all(self) -> list[SubagentConfig]:
        return list(self._configs.values())

    def list_agents(self) -> list[str]:
        return list(set(list(self._agents.keys()) + list(self._configs.keys())))

    def unregister(self, name: str) -> None:
        self._configs.pop(name, None)
        self._agents.pop(name, None)

    def __len__(self) -> int:
        return len(set(list(self._agents.keys()) + list(self._configs.keys())))

    def __contains__(self, name: str) -> bool:
        return name in self._agents or name in self._configs
