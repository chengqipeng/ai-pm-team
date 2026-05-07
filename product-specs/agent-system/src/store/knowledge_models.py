"""知识库数据模型 — 对应 paas_ai.ai_knowledge_* 表（10 张）

对齐 src/store/models.py 的风格：
- 雪花 BIGINT 主键（id）+ 业务 UUID（doc_id/chunk_id/segment_id/task_id）
- 毫秒时间戳（created_at / updated_at）
- BaseEntity 审计字段（delete_flg / created_by / updated_by）
- 所有 JSON 字段存为 TEXT，默认 '{}' 或 '[]'
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field

from .snowflake import next_id


# ═══════════════════════════════════════════════════════════
# 1. KnowledgeBaseRow — ai_knowledge_base
# ═══════════════════════════════════════════════════════════

@dataclass
class KnowledgeBaseRow:
    id: int = 0
    tenant_id: int = 0
    api_key: str = ""
    name: str = ""
    description: str = ""
    owner: str = ""

    # 检索配置
    default_top_k: int = 5
    min_score: float = 0.0
    enable_rerank: int = 1
    enable_self_query: int = 1
    enable_query_rewrite: int = 0

    # 向量库绑定
    vdb_database: str = "knowledge"
    vdb_collection: str = "kb_chunks"

    # 元数据 Schema
    schema_id: int = 0

    # 统计
    document_count: int = 0
    chunk_count: int = 0
    total_tokens: int = 0

    status: str = "active"
    ext_info: str = "{}"
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
# 2. KnowledgeBaseBindingRow — ai_knowledge_base_binding
# ═══════════════════════════════════════════════════════════

@dataclass
class KnowledgeBaseBindingRow:
    """知识库与 Agent 的授权绑定"""
    id: int = 0
    tenant_id: int = 0
    knowledge_base_id: int = 0
    agent_name: str = ""
    scope: str = "read"                 # read / write
    override_top_k: int = 0
    override_filters: str = "{}"
    status: str = "active"
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
# 3. KnowledgeDatasetRow — ai_knowledge_dataset
# ═══════════════════════════════════════════════════════════

@dataclass
class KnowledgeDatasetRow:
    id: int = 0
    tenant_id: int = 0
    knowledge_base_id: int = 0
    name: str = ""
    description: str = ""

    default_metadata: str = "{}"
    chunk_strategy: str = "lkeap"       # lkeap / local_header / sliding_window
    chunk_size: int = 800
    chunk_overlap: int = 200

    document_count: int = 0
    chunk_count: int = 0

    status: str = "active"
    ext_info: str = "{}"
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
# 4. KnowledgeSchemaRow — ai_knowledge_schema
# ═══════════════════════════════════════════════════════════

@dataclass
class KnowledgeSchemaRow:
    id: int = 0
    tenant_id: int = 0
    name: str = ""
    knowledge_base_id: int = 0
    fields: str = "[]"
    version: int = 1
    status: str = "active"
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
# 5. KnowledgeDocumentRow — ai_knowledge_document
# ═══════════════════════════════════════════════════════════

@dataclass
class KnowledgeDocumentRow:
    id: int = 0
    doc_id: str = ""
    tenant_id: int = 0
    knowledge_base_id: int = 0
    dataset_id: int = 0

    # 文件信息
    title: str = ""
    file_name: str = ""
    file_type: str = ""
    file_size: int = 0
    file_hash: str = ""
    raw_url: str = ""
    parsed_md_url: str = ""
    parsed_json_url: str = ""
    page_count: int = 0
    total_chars: int = 0

    # 解析状态
    parse_status: str = "pending"       # pending / parsing / parsed / failed
    parse_task_id: str = ""
    parse_engine: str = "lkeap"
    parse_error: str = ""
    failed_pages: str = "[]"

    # 清洗状态
    clean_status: str = "pending"       # pending / cleaning / cleaned / failed
    clean_error: str = ""

    # 切分 / 索引状态
    chunk_status: str = "pending"       # pending / splitting / indexed / failed
    chunk_count: int = 0
    segment_count: int = 0

    # LLM 打标
    summary: str = ""
    keywords: str = "[]"
    metadata: str = "{}"
    metadata_tagged: int = 0

    # 质量评分
    quality_score: float = 0.0
    quality_signals: str = "{}"

    # 其他
    date_published: int = 0
    search_hit_count: int = 0

    status: str = "active"
    ext_info: str = "{}"
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
# 6. KnowledgeSegmentRow — ai_knowledge_segment
# ═══════════════════════════════════════════════════════════

@dataclass
class KnowledgeSegmentRow:
    id: int = 0
    segment_id: str = ""
    tenant_id: int = 0
    knowledge_base_id: int = 0
    doc_id: str = ""

    title: str = ""
    section_path: str = ""
    content: str = ""
    content_tokens: int = 0

    segment_index: int = 0
    heading_level: int = 0
    page_start: int = 0
    page_end: int = 0
    start_offset: int = 0
    end_offset: int = 0
    chunk_count: int = 0

    delete_flg: int = 0
    created_at: int = 0
    updated_at: int = 0

    def __post_init__(self):
        now = int(time.time() * 1000)
        if not self.created_at:
            self.created_at = now
        if not self.updated_at:
            self.updated_at = now


# ═══════════════════════════════════════════════════════════
# 7. KnowledgeChunkRow — ai_knowledge_chunk
# ═══════════════════════════════════════════════════════════

@dataclass
class KnowledgeChunkRow:
    id: int = 0
    chunk_id: str = ""
    tenant_id: int = 0
    knowledge_base_id: int = 0
    dataset_id: int = 0
    doc_id: str = ""

    # 切片内容
    content: str = ""                   # 检索层纯文本
    display_content: str = ""           # 展示层（保留表格 HTML / 图片占位）
    content_hash: str = ""
    content_tokens: int = 0

    # 切片定位
    chunk_index: int = 0
    chunk_type: str = "Text"            # Text / Table / Image_Description / Title / Summary
    section_title: str = ""
    section_path: str = ""
    page_number: int = 0
    start_offset: int = 0
    end_offset: int = 0

    # 冗余检索字段
    doc_category: str = ""
    industry: str = ""
    business_stage: str = ""
    target_audience: str = ""
    product_service: str = ""
    date_published: int = 0

    # Parent-Child
    parent_chunk_id: str = ""
    parent_segment_id: str = ""
    is_summary: int = 0

    # 向量库同步
    vector_synced: int = 0              # 0=未同步, 1=已同步, 2=失败, 3=死信
    vector_error: str = ""
    vector_retry_count: int = 0
    embedding_model: str = ""
    embedding_dim: int = 0

    # 检索统计
    hit_count: int = 0
    last_hit_at: int = 0

    metadata: str = "{}"
    status: str = "active"
    delete_flg: int = 0
    created_at: int = 0
    updated_at: int = 0

    def __post_init__(self):
        now = int(time.time() * 1000)
        if not self.created_at:
            self.created_at = now
        if not self.updated_at:
            self.updated_at = now


# ═══════════════════════════════════════════════════════════
# 8. KnowledgeIngestQueueRow — ai_knowledge_ingest_queue
# ═══════════════════════════════════════════════════════════

@dataclass
class KnowledgeIngestQueueRow:
    """入库任务队列 — SKIP LOCKED 模式"""
    id: int = 0
    task_id: str = ""
    tenant_id: int = 0
    knowledge_base_id: int = 0
    dataset_id: int = 0

    payload: str = "{}"                 # JSON: {file_path, file_name, file_hash, ...}

    status: str = "pending"             # pending / running / success / failed / dead
    priority: int = 0
    available_at: int = 0
    picked_at: int = 0
    picked_by: str = ""
    completed_at: int = 0

    retry_count: int = 0
    max_retry: int = 3
    last_error: str = ""

    visibility_timeout_ms: int = 600_000  # 10 min

    created_at: int = 0
    updated_at: int = 0

    def __post_init__(self):
        now = int(time.time() * 1000)
        if not self.created_at:
            self.created_at = now
        if not self.updated_at:
            self.updated_at = now
        if not self.available_at:
            self.available_at = now


# ═══════════════════════════════════════════════════════════
# 9. KnowledgeIngestLogRow — ai_knowledge_ingest_log
# ═══════════════════════════════════════════════════════════

@dataclass
class KnowledgeIngestLogRow:
    id: int = 0
    tenant_id: int = 0
    knowledge_base_id: int = 0
    dataset_id: int = 0
    doc_id: str = ""

    task_id: str = ""
    file_name: str = ""
    file_size: int = 0
    file_type: str = ""

    # 阶段: upload / parsing / cleaning / tagging / splitting / indexing / done / failed
    phase: str = "upload"
    status: str = "running"             # running / success / failed
    progress: int = 0                   # 0 ~ 100

    # 耗时
    parse_duration_ms: int = 0
    clean_duration_ms: int = 0
    tagging_duration_ms: int = 0
    split_duration_ms: int = 0
    index_duration_ms: int = 0
    total_duration_ms: int = 0

    # 输出
    total_chars: int = 0
    segment_count: int = 0
    chunk_count: int = 0
    vector_count: int = 0
    quality_score: float = 0.0

    error_message: str = ""
    retry_count: int = 0

    start_time: int = 0
    end_time: int = 0
    delete_flg: int = 0
    created_at: int = 0
    created_by: int = 0

    def __post_init__(self):
        if not self.id:
            self.id = next_id()
        now = int(time.time() * 1000)
        if not self.created_at:
            self.created_at = now
        if not self.start_time:
            self.start_time = now


# ═══════════════════════════════════════════════════════════
# 10. KnowledgeSearchLogRow — ai_knowledge_search_log
# ═══════════════════════════════════════════════════════════

@dataclass
class KnowledgeSearchLogRow:
    id: int = 0
    tenant_id: int = 0
    knowledge_base_id: int = 0
    user_id: str = ""
    thread_id: str = ""
    trace_id: str = ""

    # 查询
    raw_query: str = ""
    rewritten_query: str = ""
    semantic_query: str = ""
    filters: str = "{}"

    # 结果
    hit_chunk_ids: str = "[]"
    hit_count: int = 0
    top_score: float = 0.0
    vector_hit_count: int = 0
    bm25_hit_count: int = 0

    # 耗时
    rewrite_ms: int = 0
    self_query_ms: int = 0
    vector_search_ms: int = 0
    bm25_search_ms: int = 0
    rerank_ms: int = 0
    total_ms: int = 0

    # 反馈
    user_feedback: str = ""             # good / bad / ''
    feedback_comment: str = ""

    delete_flg: int = 0
    created_at: int = 0

    def __post_init__(self):
        if not self.id:
            self.id = next_id()
        if not self.created_at:
            self.created_at = int(time.time() * 1000)
