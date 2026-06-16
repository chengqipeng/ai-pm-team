"""上下文存档数据模型 — 对应 ai_context_archive 表（Legacy PG 模型）

注意: 当前 ContextArchive 已迁移到纯 VDB 存储，本模型保留用于:
  1. 测试代码中的类型标注
  2. 兼容旧版 PG DAO 接口
  3. 未来可能的 PG 备份/审计需求
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field

from .snowflake import next_id


@dataclass
class ContextArchiveRow:
    """上下文存档行 — 对齐 ai_context_archive 表结构"""
    id: int = 0
    tenant_id: int = 0
    thread_id: str = ""
    turn_id: int = 0
    user_query: str = ""
    answer_preview: str = ""
    entities: str = ""              # JSON 或空格分隔的实体名
    keywords: str = ""              # JSON 或空格分隔的关键词
    tool_names: str = ""            # 空格分隔的工具名
    skill_names: str = ""           # 空格分隔的技能名
    tool_summaries: str = "[]"      # JSON 数组
    key_data: str = "{}"            # JSON 对象
    original_messages_json: str = ""  # 完整原始消息 JSON
    message_count: int = 0
    message_range_start: int = 0
    message_range_end: int = 0
    has_decision: int = 0           # 0/1
    decision_fields: str = "[]"     # JSON 数组
    task_id: str = ""
    data_timestamp: int = 0         # 毫秒时间戳
    delete_flg: int = 0
    created_at: int = 0
    updated_at: int = 0

    def __post_init__(self):
        if not self.id:
            self.id = next_id()
        now = int(time.time() * 1000)
        if not self.created_at:
            self.created_at = now
        if not self.updated_at:
            self.updated_at = now
