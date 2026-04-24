-- DeepAgent 对话存储表 — paas_ai schema
-- 兼容 PostgreSQL，遵循 BaseEntity 规范

SET search_path TO paas_ai;

-- 1. 对话会话
CREATE TABLE IF NOT EXISTS ai_conversation (
    id              BIGINT PRIMARY KEY,
    tenant_id       BIGINT NOT NULL,
    user_id         BIGINT NOT NULL,
    thread_id       VARCHAR(64) NOT NULL,
    agent_name      VARCHAR(100) NOT NULL DEFAULT 'CRM-Agent',
    title           VARCHAR(500) DEFAULT '',
    summary         TEXT DEFAULT '',
    model           VARCHAR(100) DEFAULT '',
    status          VARCHAR(20) NOT NULL DEFAULT 'active',
    message_count   INT NOT NULL DEFAULT 0,
    total_tokens    INT NOT NULL DEFAULT 0,
    total_cost      DECIMAL(10,4) NOT NULL DEFAULT 0,
    last_message_at BIGINT DEFAULT 0,
    ext_info        TEXT DEFAULT '{}',
    delete_flg      SMALLINT NOT NULL DEFAULT 0,
    created_at      BIGINT NOT NULL,
    created_by      BIGINT NOT NULL DEFAULT 0,
    updated_at      BIGINT NOT NULL,
    updated_by      BIGINT NOT NULL DEFAULT 0
);

CREATE UNIQUE INDEX IF NOT EXISTS uk_conversation_thread ON ai_conversation(tenant_id, thread_id);
CREATE INDEX IF NOT EXISTS idx_conversation_user ON ai_conversation(tenant_id, user_id, delete_flg);
CREATE INDEX IF NOT EXISTS idx_conversation_time ON ai_conversation(tenant_id, last_message_at DESC);

-- 2. 对话消息
CREATE TABLE IF NOT EXISTS ai_message (
    id              BIGINT PRIMARY KEY,
    tenant_id       BIGINT NOT NULL,
    conversation_id BIGINT NOT NULL,
    thread_id       VARCHAR(64) NOT NULL,
    sequence        INT NOT NULL DEFAULT 0,
    role            VARCHAR(20) NOT NULL,
    query           TEXT DEFAULT '',
    answer          TEXT DEFAULT '',
    masked_query    TEXT DEFAULT '',
    masked_answer   TEXT DEFAULT '',
    model           VARCHAR(100) DEFAULT '',
    input_tokens    INT NOT NULL DEFAULT 0,
    output_tokens   INT NOT NULL DEFAULT 0,
    total_tokens    INT NOT NULL DEFAULT 0,
    iteration_count INT NOT NULL DEFAULT 0,
    tool_count      INT NOT NULL DEFAULT 0,
    duration_ms     INT NOT NULL DEFAULT 0,
    trace_id        VARCHAR(64) DEFAULT '',
    status          VARCHAR(20) NOT NULL DEFAULT 'success',
    error_message   TEXT DEFAULT '',
    ext_info        TEXT DEFAULT '{}',
    delete_flg      SMALLINT NOT NULL DEFAULT 0,
    created_at      BIGINT NOT NULL,
    created_by      BIGINT NOT NULL DEFAULT 0,
    updated_at      BIGINT NOT NULL,
    updated_by      BIGINT NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_message_conversation ON ai_message(conversation_id, sequence);
CREATE INDEX IF NOT EXISTS idx_message_thread ON ai_message(tenant_id, thread_id, sequence);
CREATE INDEX IF NOT EXISTS idx_message_trace ON ai_message(trace_id);

-- 3. 消息扩展数据
CREATE TABLE IF NOT EXISTS ai_message_ext (
    id              BIGINT PRIMARY KEY,
    tenant_id       BIGINT NOT NULL,
    message_id      BIGINT NOT NULL,
    ext_type        VARCHAR(50) NOT NULL,
    ext_data        TEXT NOT NULL DEFAULT '{}',
    status          VARCHAR(20) DEFAULT 'active',
    delete_flg      SMALLINT NOT NULL DEFAULT 0,
    created_at      BIGINT NOT NULL,
    updated_at      BIGINT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_message_ext ON ai_message_ext(message_id, ext_type);

-- 4. 执行链路
CREATE TABLE IF NOT EXISTS ai_trace (
    id              BIGINT PRIMARY KEY,
    tenant_id       BIGINT NOT NULL,
    trace_id        VARCHAR(64) NOT NULL,
    thread_id       VARCHAR(64) NOT NULL,
    message_id      BIGINT DEFAULT 0,
    user_input      TEXT DEFAULT '',
    agent_output    TEXT DEFAULT '',
    model           VARCHAR(100) DEFAULT '',
    agent_name      VARCHAR(100) DEFAULT '',
    status          VARCHAR(20) NOT NULL DEFAULT 'running',
    total_tokens    INT NOT NULL DEFAULT 0,
    total_cost      DECIMAL(10,4) NOT NULL DEFAULT 0,
    iteration_count INT NOT NULL DEFAULT 0,
    tool_count      INT NOT NULL DEFAULT 0,
    span_count      INT NOT NULL DEFAULT 0,
    duration_ms     INT NOT NULL DEFAULT 0,
    start_time      BIGINT NOT NULL,
    end_time        BIGINT DEFAULT 0,
    ext_info        TEXT DEFAULT '{}',
    delete_flg      SMALLINT NOT NULL DEFAULT 0,
    created_at      BIGINT NOT NULL,
    updated_at      BIGINT NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS uk_trace_id ON ai_trace(trace_id);
CREATE INDEX IF NOT EXISTS idx_trace_thread ON ai_trace(tenant_id, thread_id, start_time DESC);
CREATE INDEX IF NOT EXISTS idx_trace_time ON ai_trace(tenant_id, start_time DESC);

-- 5. 链路步骤
CREATE TABLE IF NOT EXISTS ai_trace_span (
    id              BIGINT PRIMARY KEY,
    tenant_id       BIGINT NOT NULL,
    trace_id        VARCHAR(64) NOT NULL,
    span_id         VARCHAR(64) NOT NULL,
    parent_span_id  VARCHAR(64) DEFAULT '',
    span_type       VARCHAR(50) NOT NULL,
    span_name       VARCHAR(200) NOT NULL DEFAULT '',
    source          VARCHAR(20) NOT NULL DEFAULT 'agent',
    status          VARCHAR(20) NOT NULL DEFAULT 'running',
    duration_ms     INT NOT NULL DEFAULT 0,
    start_time      BIGINT NOT NULL,
    end_time        BIGINT DEFAULT 0,
    input_data      TEXT DEFAULT '{}',
    output_data     TEXT DEFAULT '{}',
    metadata        TEXT DEFAULT '{}',
    delete_flg      SMALLINT NOT NULL DEFAULT 0,
    created_at      BIGINT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_span_trace ON ai_trace_span(trace_id, start_time);
CREATE INDEX IF NOT EXISTS idx_span_type ON ai_trace_span(trace_id, span_type);
CREATE INDEX IF NOT EXISTS idx_span_source ON ai_trace_span(trace_id, source);

-- 6. 内容审查日志
CREATE TABLE IF NOT EXISTS ai_content_review_log (
    id              BIGINT PRIMARY KEY,
    tenant_id       BIGINT NOT NULL,
    thread_id       VARCHAR(64) NOT NULL,
    message_id      BIGINT DEFAULT 0,
    review_type     VARCHAR(20) NOT NULL,
    original_content TEXT NOT NULL,
    blocked_keywords TEXT DEFAULT '[]',
    blocked_reason  VARCHAR(500) DEFAULT '',
    rule_id         BIGINT DEFAULT 0,
    delete_flg      SMALLINT NOT NULL DEFAULT 0,
    created_at      BIGINT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_review_log_thread ON ai_content_review_log(tenant_id, thread_id);
CREATE INDEX IF NOT EXISTS idx_review_log_time ON ai_content_review_log(tenant_id, created_at DESC);

-- 7. Token 用量统计
CREATE TABLE IF NOT EXISTS ai_token_usage (
    id              BIGINT PRIMARY KEY,
    tenant_id       BIGINT NOT NULL,
    user_id         BIGINT NOT NULL,
    conversation_id BIGINT DEFAULT 0,
    thread_id       VARCHAR(64) DEFAULT '',
    trace_id        VARCHAR(64) DEFAULT '',
    model           VARCHAR(100) NOT NULL,
    input_tokens    INT NOT NULL DEFAULT 0,
    output_tokens   INT NOT NULL DEFAULT 0,
    total_tokens    INT NOT NULL DEFAULT 0,
    cost            DECIMAL(10,6) NOT NULL DEFAULT 0,
    created_at      BIGINT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_usage_user ON ai_token_usage(tenant_id, user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_usage_model ON ai_token_usage(tenant_id, model, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_usage_conversation ON ai_token_usage(conversation_id);
