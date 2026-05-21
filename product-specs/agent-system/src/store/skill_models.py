"""Skill 数据模型 — 三表结构

ai_skill            Skill 主记录（版本无关，每个 Skill 一行）
ai_skill_definition 版本内容（每个版本一行，含 prompt/参数/工具配置）
ai_skill_resource   资源文件（每个版本独立一套）

字段风格：雪花 BIGINT 主键、毫秒时间戳、JSON 字段存 TEXT
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field

from .snowflake import next_id


# ═══════════════════════════════════════════════════════════
# SkillRow — ai_skill（主记录）
# ═══════════════════════════════════════════════════════════

@dataclass
class SkillRow:
    """Skill 主记录 — 版本无关的元信息"""
    id: int = 0
    api_key: str = ""                   # Skill 唯一标识
    tenant_id: int = 0                  # 0 = 平台级
    name: str = ""                      # 显示名称
    description: str = ""               # 一句话描述
    owner: str = ""                     # 负责人
    category: str = ""                  # 分类
    tags: str = "[]"                    # JSON 标签数组
    icon: str = ""                      # 图标
    sort_num: int = 0                   # 排序权重
    current_version: str = "1.0.0"      # 当前生效版本号
    enabled_flg: int = 1                # 1=启用, 0=禁用
    system_flg: int = 0                 # 1=系统预置, 0=用户创建
    exec_count: int = 0                 # 累计执行次数
    success_count: int = 0              # 累计成功次数
    avg_duration_ms: int = 0            # 平均执行时长
    ext_info: str = "{}"                # 扩展 JSON
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


# ═══════════════════════════════════════════════════════════
# SkillDefinitionRow — ai_skill_definition（版本内容）
# ═══════════════════════════════════════════════════════════

@dataclass
class SkillDefinitionRow:
    """Skill 版本内容 — 每个版本一行"""
    id: int = 0
    skill_api_key: str = ""             # 关联 ai_skill.api_key
    tenant_id: int = 0
    version: str = "1.0.0"              # 版本号
    name: str = ""                      # 版本对应的名称（与 ai_skill.name 同步）
    description: str = ""               # 版本对应的描述（与 ai_skill.description 同步）
    changelog: str = ""                 # 变更说明
    # ── 技能配置 ──
    when_to_use: str = ""               # 触发关键词
    category: str = ""                  # 分类
    context: str = "inline"             # inline | fork
    agent: str = ""                     # fork 模式子 Agent
    model: str = ""                     # 指定模型
    allowed_tools: str = "[]"           # JSON 数组
    arguments: str = "[]"               # JSON 数组
    prompt: str = ""                    # Markdown prompt
    risk_level: str = "read_only"       # read_only | mutating | destructive
    requires_confirmation: int = 0
    max_tool_calls: int = 20
    timeout_ms: int = 60000
    output_mode: str = "text"           # text | card | component | table
    component_apikey: str = ""
    post_output_behavior: str = "silent"
    # ── 状态 ──
    published_by: int = 0               # 创建人
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


# ═══════════════════════════════════════════════════════════
# SkillVersionRow — 兼容别名（指向 SkillDefinitionRow）
# ═══════════════════════════════════════════════════════════

# 保留 SkillVersionRow 作为别名，兼容已有引用
SkillVersionRow = SkillDefinitionRow
