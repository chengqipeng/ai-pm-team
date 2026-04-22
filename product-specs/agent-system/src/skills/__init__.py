"""skills — Skill 定义、注册、执行、加载、生成"""
from .base import (SkillDefinition, SkillRegistry, SkillExecutor, SkillsTool,
                    SkillLoader, SkillValidationError, SkillExecutionError)
from .generator import SkillGenerator
from .crm_skills import register_crm_skills
