"""Skill 数据模型 — 对应 paas_ai.ai_skill_* 表

对应 init_tables.sql 中的 4 张表：
  - ai_skill_definition  当前生效版本（主表）
  - ai_skill_version     版本历史快照
  - ai_skill_policy      发布策略
  - ai_skill_exec_log    执行审计日志

字段风格对齐 models.py / knowledge_models.py：
  - 雪花 BIGINT 主键
  - 毫秒时间戳
  - JSON 字段存 TEXT（默认 '[]' / '{}'）
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field

from .snowflake import next_id


# ═══════════════════════════════════════════════════════════
# SkillDefinitionRow — ai_skill_definition
# ═══════════════════════════════════════════════════════════

@dataclass
class SkillDefinitionRow:
    id: int = 0
    api_key: str = ""                   # Skill 唯一标识（租户内唯一）
    tenant_id: int = 0                  # 0 = 平台级，所有租户可用
    name: str = ""
    description: str = ""
    when_to_use: str = ""               # 触发关键词（|分隔）
    owner: str = ""
    context: str = "inline"             # inline | fork
    agent: str = ""                     # fork 模式下的子 Agent 名（空串表示通用）
    model: str = ""                     # 指定模型（空串 = 继承主模型）
    allowed_tools: str = "[]"           # JSON 数组
    arguments: str = "[]"               # JSON 数组（参数名列表）
    prompt: str = ""                    # 当前版本的 Markdown prompt
    risk_level: str = "read_only"       # read_only | mutating | destructive
    requires_confirmation: int = 0      # 0/1
    max_tool_calls: int = 20
    timeout_ms: int = 60000
    idempotent_flg: int = 1
    version: str = "1.0.0"
    status: str = "published"           # 兼容旧字段
    published_at: int = 0
    exec_count: int = 0
    success_count: int = 0
    avg_duration_ms: int = 0
    ext_info: str = "{}"
    delete_flg: int = 0
    created_at: int = 0
    created_by: int = 0
    updated_at: int = 0
    updated_by: int = 0
    # 新增字段
    enabled_flg: int = 1                # 1=启用, 0=禁用
    category: str = ""                  # 分类
    tags: str = "[]"                    # JSON 标签数组
    icon: str = ""                      # 图标
    sort_num: int = 0                   # 排序权重
    system_flg: int = 0                 # 1=系统预置（不可编辑/删除）, 0=用户创建

    def __post_init__(self):
        if not self.id:
            self.id = next_id()
        now = int(time.time() * 1000)
        if not self.created_at:
            self.created_at = now
        if not self.updated_at:
            self.updated_at = now


# ═══════════════════════════════════════════════════════════
# SkillVersionRow — ai_skill_version
# ═══════════════════════════════════════════════════════════

@dataclass
class SkillVersionRow:
    id: int = 0
    tenant_id: int = 0
    skill_api_key: str = ""
    version: str = "1.0.0"
    description: str = ""
    when_to_use: str = ""
    context: str = "inline"
    agent: str = ""
    model: str = ""
    allowed_tools: str = "[]"
    arguments: str = "[]"
    prompt: str = ""
    risk_level: str = "read_only"
    requires_confirmation: int = 0
    max_tool_calls: int = 20
    timeout_ms: int = 60000
    changelog: str = ""
    published_by: int = 0
    delete_flg: int = 0
    created_at: int = 0
    created_by: int = 0
    updated_at: int = 0
    updated_by: int = 0

    def __post_init__(self):
        if not self.id:
            self.id = next_id()
        now = int(time.time() * 1000)
        if not self.created_at:
            self.created_at = now
        if not self.updated_at:
            self.updated_at = now
