-- ═══════════════════════════════════════════════════════════
-- 知识库存储表 — paas_ai schema
-- 对应 doc/知识库体系设计方案.md §四·补
--
-- 9 张表:
--   1. ai_knowledge_base          ── 知识库定义
--   2. ai_knowledge_dataset       ── 数据集（文档分组）
--   3. ai_knowledge_schema        ── 元数据 Schema
--   4. ai_knowledge_document      ── 文档主表
--   5. ai_knowledge_segment       ── 章节级聚合
--   6. ai_knowledge_chunk         ── 切片主表
--   7. ai_knowledge_ingest_queue  ── 入库任务队列（SKIP LOCKED）
--   8. ai_knowledge_ingest_log    ── 入库任务日志
--   9. ai_knowledge_search_log    ── 检索审计日志
-- ═══════════════════════════════════════════════════════════

SET search_path TO paas_ai;

-- ═══════════════════════════════════════════════════════════
-- 1. ai_knowledge_base — 知识库定义
-- ═══════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS ai_knowledge_base (
    id              BIGINT        PRIMARY KEY,
    tenant_id       BIGINT        NOT NULL,
    api_key         VARCHAR(100)  NOT NULL,
    name            VARCHAR(200)  NOT NULL,
    description     VARCHAR(1000) NOT NULL DEFAULT '',
    owner           VARCHAR(100)  NOT NULL DEFAULT '',

    -- 检索配置
    default_top_k         INT           NOT NULL DEFAULT 5,
    min_score             DECIMAL(5,4)  NOT NULL DEFAULT 0.0,
    enable_rerank         SMALLINT      NOT NULL DEFAULT 1,
    enable_self_query     SMALLINT      NOT NULL DEFAULT 1,
    enable_query_rewrite  SMALLINT      NOT NULL DEFAULT 0,

    -- 向量库绑定
    vdb_database    VARCHAR(100)  NOT NULL DEFAULT 'knowledge',
    vdb_collection  VARCHAR(100)  NOT NULL DEFAULT 'kb_chunks',

    -- 元数据 Schema 绑定
    schema_id       BIGINT        NOT NULL DEFAULT 0,

    -- 统计（冗余字段）
    document_count  INT           NOT NULL DEFAULT 0,
    chunk_count     INT           NOT NULL DEFAULT 0,
    total_tokens    BIGINT        NOT NULL DEFAULT 0,

    status          VARCHAR(20)   NOT NULL DEFAULT 'active',
    ext_info        TEXT          NOT NULL DEFAULT '{}',
    delete_flg      SMALLINT      NOT NULL DEFAULT 0,
    created_at      BIGINT        NOT NULL,
    created_by      BIGINT        NOT NULL DEFAULT 0,
    updated_at      BIGINT        NOT NULL,
    updated_by      BIGINT        NOT NULL DEFAULT 0
);

CREATE UNIQUE INDEX IF NOT EXISTS uk_kb_apikey
    ON ai_knowledge_base(tenant_id, api_key) WHERE delete_flg = 0;
CREATE INDEX IF NOT EXISTS idx_kb_tenant
    ON ai_knowledge_base(tenant_id, status) WHERE delete_flg = 0;

COMMENT ON TABLE ai_knowledge_base IS '知识库定义 — 租户维度';


-- ═══════════════════════════════════════════════════════════
-- 2. ai_knowledge_dataset — 数据集（文档分组）
-- ═══════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS ai_knowledge_dataset (
    id                BIGINT        PRIMARY KEY,
    tenant_id         BIGINT        NOT NULL,
    knowledge_base_id BIGINT        NOT NULL,
    name              VARCHAR(200)  NOT NULL,
    description       VARCHAR(1000) NOT NULL DEFAULT '',

    -- 入库默认配置
    default_metadata  TEXT          NOT NULL DEFAULT '{}',
    chunk_strategy    VARCHAR(32)   NOT NULL DEFAULT 'lkeap',
    chunk_size        INT           NOT NULL DEFAULT 800,
    chunk_overlap     INT           NOT NULL DEFAULT 200,

    -- 统计
    document_count    INT           NOT NULL DEFAULT 0,
    chunk_count       INT           NOT NULL DEFAULT 0,

    status            VARCHAR(20)   NOT NULL DEFAULT 'active',
    ext_info          TEXT          NOT NULL DEFAULT '{}',
    delete_flg        SMALLINT      NOT NULL DEFAULT 0,
    created_at        BIGINT        NOT NULL,
    created_by        BIGINT        NOT NULL DEFAULT 0,
    updated_at        BIGINT        NOT NULL,
    updated_by        BIGINT        NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_dataset_kb
    ON ai_knowledge_dataset(tenant_id, knowledge_base_id, delete_flg);

COMMENT ON TABLE ai_knowledge_dataset IS '知识库数据集 — 文档分组';


-- ═══════════════════════════════════════════════════════════
-- 3. ai_knowledge_schema — 元数据 Schema
-- ═══════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS ai_knowledge_schema (
    id                BIGINT        PRIMARY KEY,
    tenant_id         BIGINT        NOT NULL,
    name              VARCHAR(100)  NOT NULL,
    knowledge_base_id BIGINT        NOT NULL DEFAULT 0,

    -- Schema 字段定义 JSON
    fields            TEXT          NOT NULL DEFAULT '[]',

    version           INT           NOT NULL DEFAULT 1,
    status            VARCHAR(20)   NOT NULL DEFAULT 'active',
    delete_flg        SMALLINT      NOT NULL DEFAULT 0,
    created_at        BIGINT        NOT NULL,
    created_by        BIGINT        NOT NULL DEFAULT 0,
    updated_at        BIGINT        NOT NULL,
    updated_by        BIGINT        NOT NULL DEFAULT 0
);

CREATE UNIQUE INDEX IF NOT EXISTS uk_schema_name
    ON ai_knowledge_schema(tenant_id, name, knowledge_base_id) WHERE delete_flg = 0;

COMMENT ON TABLE ai_knowledge_schema IS '元数据 Schema — 驱动 LLM 打标 + Self-Querying';


-- ═══════════════════════════════════════════════════════════
-- 4. ai_knowledge_document — 文档主表
-- ═══════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS ai_knowledge_document (
    id                BIGINT        PRIMARY KEY,
    doc_id            VARCHAR(64)   NOT NULL,
    tenant_id         BIGINT        NOT NULL,
    knowledge_base_id BIGINT        NOT NULL,
    dataset_id        BIGINT        NOT NULL DEFAULT 0,

    -- 文件信息
    title             VARCHAR(500)  NOT NULL DEFAULT '',
    file_name         VARCHAR(500)  NOT NULL DEFAULT '',
    file_type         VARCHAR(20)   NOT NULL DEFAULT '',
    file_size         BIGINT        NOT NULL DEFAULT 0,
    file_hash         VARCHAR(64)   NOT NULL DEFAULT '',
    raw_url           VARCHAR(1000) NOT NULL DEFAULT '',
    parsed_md_url     VARCHAR(1000) NOT NULL DEFAULT '',
    parsed_json_url   VARCHAR(1000) NOT NULL DEFAULT '',
    page_count        INT           NOT NULL DEFAULT 0,
    total_chars       INT           NOT NULL DEFAULT 0,

    -- 解析状态
    parse_status      VARCHAR(20)   NOT NULL DEFAULT 'pending',
    parse_task_id     VARCHAR(64)   NOT NULL DEFAULT '',
    parse_engine      VARCHAR(32)   NOT NULL DEFAULT 'lkeap',
    parse_error       TEXT          NOT NULL DEFAULT '',
    failed_pages      TEXT          NOT NULL DEFAULT '[]',

    -- 清洗状态
    clean_status      VARCHAR(20)   NOT NULL DEFAULT 'pending',
    clean_error       TEXT          NOT NULL DEFAULT '',

    -- 切分 / 索引状态
    chunk_status      VARCHAR(20)   NOT NULL DEFAULT 'pending',
    chunk_count       INT           NOT NULL DEFAULT 0,
    segment_count     INT           NOT NULL DEFAULT 0,

    -- LLM 自动打标结果
    summary           TEXT          NOT NULL DEFAULT '',
    keywords          TEXT          NOT NULL DEFAULT '[]',
    metadata          TEXT          NOT NULL DEFAULT '{}',
    metadata_tagged   SMALLINT      NOT NULL DEFAULT 0,

    -- 质量评分
    quality_score     DECIMAL(5,4)  NOT NULL DEFAULT 0.0,
    quality_signals   TEXT          NOT NULL DEFAULT '{}',

    -- 生效时间
    date_published    BIGINT        NOT NULL DEFAULT 0,

    -- 访问统计
    search_hit_count  INT           NOT NULL DEFAULT 0,

    status            VARCHAR(20)   NOT NULL DEFAULT 'active',
    ext_info          TEXT          NOT NULL DEFAULT '{}',
    delete_flg        SMALLINT      NOT NULL DEFAULT 0,
    created_at        BIGINT        NOT NULL,
    created_by        BIGINT        NOT NULL DEFAULT 0,
    updated_at        BIGINT        NOT NULL,
    updated_by        BIGINT        NOT NULL DEFAULT 0
);

CREATE UNIQUE INDEX IF NOT EXISTS uk_doc_docid
    ON ai_knowledge_document(doc_id);
CREATE INDEX IF NOT EXISTS idx_doc_kb
    ON ai_knowledge_document(tenant_id, knowledge_base_id, delete_flg);
CREATE INDEX IF NOT EXISTS idx_doc_dataset
    ON ai_knowledge_document(dataset_id, delete_flg);
-- 去重约束：同租户同知识库下，file_hash 唯一
CREATE UNIQUE INDEX IF NOT EXISTS uk_doc_hash
    ON ai_knowledge_document(tenant_id, knowledge_base_id, file_hash)
    WHERE file_hash != '' AND delete_flg = 0;
CREATE INDEX IF NOT EXISTS idx_doc_parse_status
    ON ai_knowledge_document(parse_status, created_at) WHERE delete_flg = 0;
CREATE INDEX IF NOT EXISTS idx_doc_chunk_status
    ON ai_knowledge_document(chunk_status, updated_at) WHERE delete_flg = 0;
CREATE INDEX IF NOT EXISTS idx_doc_quality
    ON ai_knowledge_document(tenant_id, knowledge_base_id, quality_score)
    WHERE delete_flg = 0 AND status = 'active';

COMMENT ON TABLE ai_knowledge_document IS '文档主表 — 存元数据/解析状态/质量分，不存切片内容';


-- ═══════════════════════════════════════════════════════════
-- 5. ai_knowledge_segment — 章节级聚合
-- ═══════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS ai_knowledge_segment (
    id                BIGSERIAL     PRIMARY KEY,
    segment_id        VARCHAR(64)   NOT NULL,
    tenant_id         BIGINT        NOT NULL,
    knowledge_base_id BIGINT        NOT NULL,
    doc_id            VARCHAR(64)   NOT NULL,

    -- Segment 内容
    title             VARCHAR(500)  NOT NULL DEFAULT '',
    section_path      VARCHAR(1000) NOT NULL DEFAULT '',
    content           TEXT          NOT NULL,
    content_tokens    INT           NOT NULL DEFAULT 0,

    -- 结构信息
    segment_index     INT           NOT NULL DEFAULT 0,
    heading_level     INT           NOT NULL DEFAULT 0,
    page_start        INT           NOT NULL DEFAULT 0,
    page_end          INT           NOT NULL DEFAULT 0,
    start_offset      INT           NOT NULL DEFAULT 0,
    end_offset        INT           NOT NULL DEFAULT 0,
    chunk_count       INT           NOT NULL DEFAULT 0,

    delete_flg        SMALLINT      NOT NULL DEFAULT 0,
    created_at        BIGINT        NOT NULL,
    updated_at        BIGINT        NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS uk_segment_segid
    ON ai_knowledge_segment(segment_id);
CREATE INDEX IF NOT EXISTS idx_segment_doc
    ON ai_knowledge_segment(doc_id, segment_index) WHERE delete_flg = 0;

COMMENT ON TABLE ai_knowledge_segment IS '章节级聚合 — Parent-Child 扩展的父节点（2000~8000 字符）';


-- ═══════════════════════════════════════════════════════════
-- 6. ai_knowledge_chunk — 切片主表
-- ═══════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS ai_knowledge_chunk (
    id                BIGSERIAL     PRIMARY KEY,
    chunk_id          VARCHAR(64)   NOT NULL,
    tenant_id         BIGINT        NOT NULL,
    knowledge_base_id BIGINT        NOT NULL,
    dataset_id        BIGINT        NOT NULL DEFAULT 0,
    doc_id            VARCHAR(64)   NOT NULL,

    -- 切片内容
    content           TEXT          NOT NULL,
    display_content   TEXT          NOT NULL DEFAULT '',
    content_hash      VARCHAR(64)   NOT NULL DEFAULT '',
    content_tokens    INT           NOT NULL DEFAULT 0,

    -- 切片定位
    chunk_index       INT           NOT NULL DEFAULT 0,
    chunk_type        VARCHAR(32)   NOT NULL DEFAULT 'Text',
    section_title     VARCHAR(500)  NOT NULL DEFAULT '',
    section_path      VARCHAR(1000) NOT NULL DEFAULT '',
    page_number       INT           NOT NULL DEFAULT 0,
    start_offset      INT           NOT NULL DEFAULT 0,
    end_offset        INT           NOT NULL DEFAULT 0,

    -- 冗余检索字段（从 document.metadata 下放）
    doc_category      VARCHAR(100)  NOT NULL DEFAULT '',
    industry          VARCHAR(100)  NOT NULL DEFAULT '',
    business_stage    VARCHAR(100)  NOT NULL DEFAULT '',
    target_audience   VARCHAR(100)  NOT NULL DEFAULT '',
    product_service   VARCHAR(500)  NOT NULL DEFAULT '',
    date_published    BIGINT        NOT NULL DEFAULT 0,

    -- Parent-Child 关系
    parent_chunk_id   VARCHAR(64)   NOT NULL DEFAULT '',
    parent_segment_id VARCHAR(64)   NOT NULL DEFAULT '',
    is_summary        SMALLINT      NOT NULL DEFAULT 0,

    -- 向量库同步
    vector_synced     SMALLINT      NOT NULL DEFAULT 0,
    vector_error      VARCHAR(500)  NOT NULL DEFAULT '',
    vector_retry_count INT          NOT NULL DEFAULT 0,
    embedding_model   VARCHAR(100)  NOT NULL DEFAULT '',
    embedding_dim     INT           NOT NULL DEFAULT 0,

    -- 检索统计
    hit_count         INT           NOT NULL DEFAULT 0,
    last_hit_at       BIGINT        NOT NULL DEFAULT 0,

    metadata          TEXT          NOT NULL DEFAULT '{}',
    status            VARCHAR(20)   NOT NULL DEFAULT 'active',
    delete_flg        SMALLINT      NOT NULL DEFAULT 0,
    created_at        BIGINT        NOT NULL,
    updated_at        BIGINT        NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS uk_chunk_chunkid
    ON ai_knowledge_chunk(chunk_id);
CREATE INDEX IF NOT EXISTS idx_chunk_doc
    ON ai_knowledge_chunk(doc_id, chunk_index) WHERE delete_flg = 0;
CREATE INDEX IF NOT EXISTS idx_chunk_segment
    ON ai_knowledge_chunk(parent_segment_id)
    WHERE parent_segment_id != '' AND delete_flg = 0;
CREATE INDEX IF NOT EXISTS idx_chunk_kb
    ON ai_knowledge_chunk(tenant_id, knowledge_base_id, delete_flg);
CREATE INDEX IF NOT EXISTS idx_chunk_vector_sync
    ON ai_knowledge_chunk(vector_synced, updated_at)
    WHERE vector_synced IN (0, 2) AND delete_flg = 0;
CREATE INDEX IF NOT EXISTS idx_chunk_category
    ON ai_knowledge_chunk(tenant_id, knowledge_base_id, doc_category)
    WHERE delete_flg = 0;

-- BM25 FTS 倒排索引（PG GIN，中文建议配合 zhparser 扩展；'simple' 作为保底）
CREATE INDEX IF NOT EXISTS idx_chunk_fts
    ON ai_knowledge_chunk USING GIN (to_tsvector('simple', content))
    WHERE delete_flg = 0;

COMMENT ON TABLE ai_knowledge_chunk IS '切片主表 — 权威数据源；向量库只存 chunk_id+向量+过滤字段';


-- ═══════════════════════════════════════════════════════════
-- 7. ai_knowledge_ingest_queue — 入库任务队列
-- 基于 FOR UPDATE SKIP LOCKED 实现，无 MQ/Redis 依赖
-- ═══════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS ai_knowledge_ingest_queue (
    id                    BIGSERIAL    PRIMARY KEY,
    task_id               VARCHAR(64)  NOT NULL,
    tenant_id             BIGINT       NOT NULL,
    knowledge_base_id     BIGINT       NOT NULL,
    dataset_id            BIGINT       NOT NULL DEFAULT 0,

    -- 负载 JSON: {file_path, file_name, file_hash, user_metadata, ...}
    payload               TEXT         NOT NULL,

    -- 调度状态: pending / running / success / failed / dead
    status                VARCHAR(20)  NOT NULL DEFAULT 'pending',
    priority              SMALLINT     NOT NULL DEFAULT 0,
    available_at          BIGINT       NOT NULL,
    picked_at             BIGINT       NOT NULL DEFAULT 0,
    picked_by             VARCHAR(100) NOT NULL DEFAULT '',
    completed_at          BIGINT       NOT NULL DEFAULT 0,

    -- 重试控制
    retry_count           INT          NOT NULL DEFAULT 0,
    max_retry             INT          NOT NULL DEFAULT 3,
    last_error            TEXT         NOT NULL DEFAULT '',

    -- 可见性超时（防 Worker 崩溃死锁）
    visibility_timeout_ms INT          NOT NULL DEFAULT 600000,

    created_at            BIGINT       NOT NULL,
    updated_at            BIGINT       NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS uk_queue_task
    ON ai_knowledge_ingest_queue(task_id);
CREATE INDEX IF NOT EXISTS idx_queue_pick
    ON ai_knowledge_ingest_queue(status, available_at, priority DESC)
    WHERE status IN ('pending', 'running');
CREATE INDEX IF NOT EXISTS idx_queue_tenant
    ON ai_knowledge_ingest_queue(tenant_id, knowledge_base_id, status, created_at DESC);

COMMENT ON TABLE ai_knowledge_ingest_queue IS '入库任务队列 — FOR UPDATE SKIP LOCKED 替代 MQ';


-- ═══════════════════════════════════════════════════════════
-- 8. ai_knowledge_ingest_log — 入库任务日志
-- ═══════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS ai_knowledge_ingest_log (
    id                    BIGINT        PRIMARY KEY,
    tenant_id             BIGINT        NOT NULL,
    knowledge_base_id     BIGINT        NOT NULL,
    dataset_id            BIGINT        NOT NULL DEFAULT 0,
    doc_id                VARCHAR(64)   NOT NULL DEFAULT '',

    task_id               VARCHAR(64)   NOT NULL,
    file_name             VARCHAR(500)  NOT NULL DEFAULT '',
    file_size             BIGINT        NOT NULL DEFAULT 0,
    file_type             VARCHAR(20)   NOT NULL DEFAULT '',

    -- 阶段: upload / parsing / cleaning / tagging / splitting / indexing / done / failed
    phase                 VARCHAR(32)   NOT NULL DEFAULT 'upload',
    status                VARCHAR(20)   NOT NULL DEFAULT 'running',
    progress              INT           NOT NULL DEFAULT 0,

    -- 耗时统计
    parse_duration_ms     INT           NOT NULL DEFAULT 0,
    clean_duration_ms     INT           NOT NULL DEFAULT 0,
    tagging_duration_ms   INT           NOT NULL DEFAULT 0,
    split_duration_ms     INT           NOT NULL DEFAULT 0,
    index_duration_ms     INT           NOT NULL DEFAULT 0,
    total_duration_ms     INT           NOT NULL DEFAULT 0,

    -- 输出统计
    total_chars           INT           NOT NULL DEFAULT 0,
    segment_count         INT           NOT NULL DEFAULT 0,
    chunk_count           INT           NOT NULL DEFAULT 0,
    vector_count          INT           NOT NULL DEFAULT 0,
    quality_score         DECIMAL(5,4)  NOT NULL DEFAULT 0.0,

    error_message         TEXT          NOT NULL DEFAULT '',
    retry_count           INT           NOT NULL DEFAULT 0,

    start_time            BIGINT        NOT NULL,
    end_time              BIGINT        NOT NULL DEFAULT 0,
    delete_flg            SMALLINT      NOT NULL DEFAULT 0,
    created_at            BIGINT        NOT NULL,
    created_by            BIGINT        NOT NULL DEFAULT 0
);

CREATE UNIQUE INDEX IF NOT EXISTS uk_ingest_task
    ON ai_knowledge_ingest_log(task_id);
CREATE INDEX IF NOT EXISTS idx_ingest_kb
    ON ai_knowledge_ingest_log(tenant_id, knowledge_base_id, start_time DESC);
CREATE INDEX IF NOT EXISTS idx_ingest_status
    ON ai_knowledge_ingest_log(status, phase, start_time DESC);

COMMENT ON TABLE ai_knowledge_ingest_log IS '入库任务日志 — 审计 + 进度追踪';


-- ═══════════════════════════════════════════════════════════
-- 9. ai_knowledge_search_log — 检索审计日志
-- ═══════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS ai_knowledge_search_log (
    id                    BIGINT        PRIMARY KEY,
    tenant_id             BIGINT        NOT NULL,
    knowledge_base_id     BIGINT        NOT NULL,
    user_id               VARCHAR(64)   NOT NULL DEFAULT '',
    thread_id             VARCHAR(64)   NOT NULL DEFAULT '',
    trace_id              VARCHAR(64)   NOT NULL DEFAULT '',

    -- 查询
    raw_query             TEXT          NOT NULL DEFAULT '',
    rewritten_query       TEXT          NOT NULL DEFAULT '',
    semantic_query        TEXT          NOT NULL DEFAULT '',
    filters               TEXT          NOT NULL DEFAULT '{}',

    -- 结果
    hit_chunk_ids         TEXT          NOT NULL DEFAULT '[]',
    hit_count             INT           NOT NULL DEFAULT 0,
    top_score             DECIMAL(10,6) NOT NULL DEFAULT 0,
    vector_hit_count      INT           NOT NULL DEFAULT 0,
    bm25_hit_count        INT           NOT NULL DEFAULT 0,

    -- 耗时
    rewrite_ms            INT           NOT NULL DEFAULT 0,
    self_query_ms         INT           NOT NULL DEFAULT 0,
    vector_search_ms      INT           NOT NULL DEFAULT 0,
    bm25_search_ms        INT           NOT NULL DEFAULT 0,
    rerank_ms             INT           NOT NULL DEFAULT 0,
    total_ms              INT           NOT NULL DEFAULT 0,

    -- 反馈
    user_feedback         VARCHAR(20)   NOT NULL DEFAULT '',
    feedback_comment      TEXT          NOT NULL DEFAULT '',

    delete_flg            SMALLINT      NOT NULL DEFAULT 0,
    created_at            BIGINT        NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_search_log_kb
    ON ai_knowledge_search_log(tenant_id, knowledge_base_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_search_log_trace
    ON ai_knowledge_search_log(trace_id) WHERE trace_id != '';
CREATE INDEX IF NOT EXISTS idx_search_log_feedback
    ON ai_knowledge_search_log(tenant_id, user_feedback, created_at DESC)
    WHERE user_feedback != '';

COMMENT ON TABLE ai_knowledge_search_log IS '检索审计日志 — 效果分析 + 坏例挖掘';
