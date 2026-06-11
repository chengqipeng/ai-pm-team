"""上下文压缩存档数据模型 — 对应 paas_ai.ai_context_archive 表"""
from __future__ import annotations

import time
from dataclasses import dataclass, field

from .snowflake import next_id


@dataclass
class ContextArchiveRow:
    """被压缩轮次的持久化记录

    表: ai_context_archive
    生命周期: 随会话存在，会话删除时级联清理
    用途: 供 recall_context 工具跨会话检索被压缩的历史对话原文
    """
    id: int = 0
    tenant_id: int = 0
    thread_id: str = ""           # 会话 thread_id（关联 ai_conversation）
    turn_id: int = 0              # 轮次编号（会话内递增，与摘要中 [📦 turn:N] 对应）
    user_query: str = ""          # 用户原始问题（完整保留，最大 2000 字符）
    answer_preview: str = ""      # Agent 回复前 500 字
    entities: str = "[]"          # JSON: 实体名列表
    keywords: str = "[]"          # JSON: 分词关键词列表
    tool_names: str = "[]"        # JSON: 使用的工具名列表
    skill_names: str = "[]"       # JSON: 执行的 Skill 名列表
    tool_summaries: str = "[]"    # JSON: 每个 ToolMessage 的一行摘要
    key_data: str = "{}"          # JSON: 正则提取的精确数字 {金额:[], 日期:[], 比例:[]}
    message_count: int = 0        # 该轮次消息条数
    message_range_start: int = 0  # 原文在完整 messages 中的起始索引
    message_range_end: int = 0    # 原文在完整 messages 中的结束索引
    original_messages: str = ""   # JSON: 原始消息序列化（完整原文持久化，不再依赖 Checkpointer TTL）
    data_timestamp: int = 0       # 数据采集时间（毫秒时间戳，用于时效性判断）
    archived_at: int = 0          # 存档时间（毫秒时间戳）
    delete_flg: int = 0
    created_at: int = 0

    def __post_init__(self):
        if not self.id:
            self.id = next_id()
        now = int(time.time() * 1000)
        if not self.created_at:
            self.created_at = now
        if not self.archived_at:
            self.archived_at = now
        if not self.data_timestamp:
            self.data_timestamp = now
