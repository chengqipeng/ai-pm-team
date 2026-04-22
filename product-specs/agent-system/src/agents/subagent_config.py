"""
SubagentConfig — 子 Agent 配置体系

对应 design.md §7.3: 子 Agent 配置体系
支持 fork 模式 Skill 指定独立的子 Agent 配置（system_prompt / middleware / tools / skills）
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class SubagentConfig:
    """
    子 Agent 完整配置 — 描述一个可被 fork 技能驱动的专属子 Agent。

    对应 design.md §7.3.1
    """
    name: str                                    # 子 Agent 唯一标识
    description: str = ""                        # 描述
    system_prompt: str = ""                      # 专属系统提示词
    model: str = ""                              # 指定 LLM 模型（空=继承主模型）

    # 中间件配置
    middleware_names: list[str] = field(default_factory=list)
    middleware_config: dict[str, dict[str, Any]] = field(default_factory=dict)
    inherit_middleware: bool = True               # 未指定 middleware_names 时是否继承主 Agent

    # 工具配置
    tool_names: list[str] = field(default_factory=list)

    # 技能配置（仅 inline 模式，防止递归 fork）
    skill_names: list[str] = field(default_factory=list)

    # 特性开关
    features: dict[str, bool] = field(default_factory=dict)

    # 执行限制
    max_llm_calls: int = 20
    max_step_llm_calls: int = 10

    # 扩展
    metadata: dict[str, Any] = field(default_factory=dict)


class SubagentRegistry:
    """
    子 Agent 配置注册表 — 对应 design.md §7.3.2

    SkillExecutor 在 fork 模式下通过 skill.agent 字段查找对应的 SubagentConfig。
    """

    def __init__(self):
        self._configs: dict[str, SubagentConfig] = {}

    def register(self, config: SubagentConfig) -> None:
        self._configs[config.name] = config

    def get(self, name: str) -> SubagentConfig | None:
        return self._configs.get(name)

    def list_all(self) -> list[SubagentConfig]:
        return list(self._configs.values())

    def unregister(self, name: str) -> None:
        self._configs.pop(name, None)
