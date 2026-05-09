"""skills — Skill 定义、注册、执行、加载、生成、安装、追踪、优化

Skill 的权威数据源是数据库（ai_skill_definition / ai_skill_version）。
项目代码中 **禁止** 定义 `SkillDefinition` 常量并硬编码注册。

运行时统一使用：
    skill_reg = SkillRegistry()
    skill_reg.load_from_db(tenant_id=<tenant>)
"""
from .base import (SkillDefinition, SkillRegistry, SkillExecutor, SkillsTool,
                    SkillLoader, SkillValidationError, SkillExecutionError)
from .generator import SkillGenerator
from .installer import SkillInstaller
from .tracker import SkillTracker, SkillExecution, SkillMetrics
from .optimizer import SkillOptimizer
