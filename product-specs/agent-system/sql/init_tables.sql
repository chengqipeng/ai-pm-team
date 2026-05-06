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

-- 8. 记忆反思日志
CREATE TABLE IF NOT EXISTS ai_memory_reflection_log (
    id              BIGSERIAL PRIMARY KEY,
    tenant_id       BIGINT NOT NULL DEFAULT 1,
    user_id         VARCHAR(64) NOT NULL,
    reflection_type VARCHAR(32) NOT NULL,   -- session/failure/correction/global
    trigger_source  TEXT,                    -- 触发原因（error msg / correction text）
    old_memory_id   VARCHAR(64) DEFAULT '',  -- 旧记忆 ID
    new_memory_id   VARCHAR(64) DEFAULT '',  -- 新记忆 ID（可选）
    relation        VARCHAR(32) DEFAULT '',  -- identical/contradiction/evolution/unrelated
    action          VARCHAR(32) DEFAULT '',  -- discard_new/archive_old/update_old/keep_both
    llm_reason      TEXT,                    -- LLM 判断理由
    created_at      BIGINT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_reflection_user
    ON ai_memory_reflection_log(user_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_reflection_old_memory
    ON ai_memory_reflection_log(old_memory_id);

CREATE INDEX IF NOT EXISTS idx_reflection_type_time
    ON ai_memory_reflection_log(reflection_type, created_at DESC);

COMMENT ON TABLE ai_memory_reflection_log IS '记忆反思日志 — 记录所有反思决策供追溯';

-- ═══════════════════════════════════════════════════════════
-- 长期记忆主表（对应 doc/长期记忆数据库表设计.md）
-- 替代已废弃的 agent_memory 表
-- ═══════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS ai_agent_memory (
    id              BIGSERIAL    PRIMARY KEY,
    memory_id       VARCHAR(64)  NOT NULL,
    tenant_id       BIGINT       NOT NULL DEFAULT 0,
    user_id         VARCHAR(64)  NOT NULL,
    category        VARCHAR(32)  NOT NULL,
    source_type     VARCHAR(32)  NOT NULL DEFAULT 'insight',
    abstract        TEXT         NOT NULL DEFAULT '',
    overview        TEXT         NOT NULL DEFAULT '',
    content         TEXT         NOT NULL DEFAULT '',
    merge_key       VARCHAR(512) NOT NULL DEFAULT '',
    parent_entity   VARCHAR(256) NOT NULL DEFAULT '',
    biz_id          VARCHAR(128) NOT NULL DEFAULT '',
    biz_parent_id   VARCHAR(128) NOT NULL DEFAULT '',
    biz_type        VARCHAR(64)  NOT NULL DEFAULT '',
    thread_id       VARCHAR(64)  NOT NULL DEFAULT '',
    message_id      BIGINT       NOT NULL DEFAULT 0,
    status          VARCHAR(20)  NOT NULL DEFAULT 'active',
    active_count    INT          NOT NULL DEFAULT 0,
    confidence      DECIMAL(5,4) NOT NULL DEFAULT 1.0,
    vector_synced   SMALLINT     NOT NULL DEFAULT 0,
    vector_id       VARCHAR(64)  NOT NULL DEFAULT '',
    delete_flg      SMALLINT     NOT NULL DEFAULT 0,
    created_at      BIGINT       NOT NULL DEFAULT 0,
    created_by      BIGINT       NOT NULL DEFAULT 0,
    updated_at      BIGINT       NOT NULL DEFAULT 0,
    updated_by      BIGINT       NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_memory_user_cat
    ON ai_agent_memory (tenant_id, user_id, category, delete_flg);
CREATE UNIQUE INDEX IF NOT EXISTS uk_memory_merge
    ON ai_agent_memory (tenant_id, user_id, category, merge_key)
    WHERE merge_key != '' AND delete_flg = 0;
CREATE INDEX IF NOT EXISTS idx_memory_parent
    ON ai_agent_memory (tenant_id, user_id, parent_entity)
    WHERE parent_entity != '' AND delete_flg = 0;
CREATE INDEX IF NOT EXISTS idx_memory_biz_id
    ON ai_agent_memory (biz_id) WHERE biz_id != '';
CREATE INDEX IF NOT EXISTS idx_memory_biz_parent
    ON ai_agent_memory (biz_parent_id) WHERE biz_parent_id != '';
CREATE INDEX IF NOT EXISTS idx_memory_status_time
    ON ai_agent_memory (tenant_id, category, status, updated_at) WHERE delete_flg = 0;
CREATE INDEX IF NOT EXISTS idx_memory_vector_sync
    ON ai_agent_memory (vector_synced, updated_at) WHERE vector_synced = 0 AND delete_flg = 0;
CREATE INDEX IF NOT EXISTS idx_memory_thread
    ON ai_agent_memory (tenant_id, thread_id) WHERE thread_id != '';

-- ═══════════════════════════════════════════════════════════
-- Skill 存储表（对应 doc/Skill存储表设计.md）
-- ═══════════════════════════════════════════════════════════

-- 9. Skill 定义主表
CREATE TABLE IF NOT EXISTS ai_skill_definition (
    id              BIGINT PRIMARY KEY,
    api_key         VARCHAR(100) NOT NULL,
    tenant_id       BIGINT NOT NULL DEFAULT 0,
    name            VARCHAR(200) NOT NULL DEFAULT '',
    description     VARCHAR(1000) NOT NULL DEFAULT '',
    when_to_use     VARCHAR(500) DEFAULT '',
    owner           VARCHAR(100) DEFAULT '',
    context         VARCHAR(20) NOT NULL DEFAULT 'inline',
    agent           VARCHAR(100) DEFAULT '',
    model           VARCHAR(100) DEFAULT '',
    allowed_tools   TEXT NOT NULL DEFAULT '[]',
    arguments       TEXT NOT NULL DEFAULT '[]',
    prompt          TEXT NOT NULL DEFAULT '',
    risk_level      VARCHAR(20) NOT NULL DEFAULT 'read_only',
    requires_confirmation SMALLINT NOT NULL DEFAULT 0,
    max_tool_calls  INT NOT NULL DEFAULT 20,
    timeout_ms      INT NOT NULL DEFAULT 60000,
    idempotent_flg  SMALLINT NOT NULL DEFAULT 1,
    version         VARCHAR(20) NOT NULL DEFAULT '1.0.0',
    status          VARCHAR(20) NOT NULL DEFAULT 'draft',
    published_at    BIGINT DEFAULT 0,
    exec_count      INT NOT NULL DEFAULT 0,
    success_count   INT NOT NULL DEFAULT 0,
    avg_duration_ms INT NOT NULL DEFAULT 0,
    ext_info        TEXT DEFAULT '{}',
    delete_flg      SMALLINT NOT NULL DEFAULT 0,
    created_at      BIGINT NOT NULL,
    created_by      BIGINT NOT NULL DEFAULT 0,
    updated_at      BIGINT NOT NULL,
    updated_by      BIGINT NOT NULL DEFAULT 0
);

CREATE UNIQUE INDEX IF NOT EXISTS uk_skill_def_apikey
    ON ai_skill_definition(tenant_id, api_key) WHERE delete_flg = 0;
CREATE INDEX IF NOT EXISTS idx_skill_def_status
    ON ai_skill_definition(tenant_id, status) WHERE delete_flg = 0;
CREATE INDEX IF NOT EXISTS idx_skill_def_risk
    ON ai_skill_definition(risk_level, status) WHERE delete_flg = 0;
CREATE INDEX IF NOT EXISTS idx_skill_def_owner
    ON ai_skill_definition(owner) WHERE delete_flg = 0;

-- 10. Skill 版本历史
CREATE TABLE IF NOT EXISTS ai_skill_version (
    id              BIGINT PRIMARY KEY,
    tenant_id       BIGINT NOT NULL DEFAULT 0,
    skill_api_key   VARCHAR(100) NOT NULL,
    version         VARCHAR(20) NOT NULL,
    description     VARCHAR(1000) DEFAULT '',
    when_to_use     VARCHAR(500) DEFAULT '',
    context         VARCHAR(20) NOT NULL DEFAULT 'inline',
    agent           VARCHAR(100) DEFAULT '',
    model           VARCHAR(100) DEFAULT '',
    allowed_tools   TEXT NOT NULL DEFAULT '[]',
    arguments       TEXT NOT NULL DEFAULT '[]',
    prompt          TEXT NOT NULL DEFAULT '',
    risk_level      VARCHAR(20) NOT NULL DEFAULT 'read_only',
    requires_confirmation SMALLINT NOT NULL DEFAULT 0,
    max_tool_calls  INT NOT NULL DEFAULT 20,
    timeout_ms      INT NOT NULL DEFAULT 60000,
    changelog       TEXT DEFAULT '',
    published_by    BIGINT NOT NULL DEFAULT 0,
    delete_flg      SMALLINT NOT NULL DEFAULT 0,
    created_at      BIGINT NOT NULL,
    created_by      BIGINT NOT NULL DEFAULT 0,
    updated_at      BIGINT NOT NULL,
    updated_by      BIGINT NOT NULL DEFAULT 0
);

CREATE UNIQUE INDEX IF NOT EXISTS uk_skill_version
    ON ai_skill_version(tenant_id, skill_api_key, version) WHERE delete_flg = 0;
CREATE INDEX IF NOT EXISTS idx_skill_version_list
    ON ai_skill_version(tenant_id, skill_api_key, created_at DESC) WHERE delete_flg = 0;

-- 11. Skill 发布策略
CREATE TABLE IF NOT EXISTS ai_skill_policy (
    id              BIGINT PRIMARY KEY,
    tenant_id       BIGINT NOT NULL,
    skill_api_key   VARCHAR(100) NOT NULL,
    enabled_flg     SMALLINT NOT NULL DEFAULT 1,
    role_whitelist  TEXT DEFAULT '[]',
    role_blacklist  TEXT DEFAULT '[]',
    user_whitelist  TEXT DEFAULT '[]',
    percentage      INT NOT NULL DEFAULT 100,
    override_allowed_tools TEXT DEFAULT '',
    override_risk_level    VARCHAR(20) DEFAULT '',
    block_destructive_flg  SMALLINT NOT NULL DEFAULT 0,
    max_qps         INT NOT NULL DEFAULT 10,
    max_daily_exec  INT NOT NULL DEFAULT 1000,
    max_concurrent  INT NOT NULL DEFAULT 5,
    delete_flg      SMALLINT NOT NULL DEFAULT 0,
    created_at      BIGINT NOT NULL,
    created_by      BIGINT NOT NULL DEFAULT 0,
    updated_at      BIGINT NOT NULL,
    updated_by      BIGINT NOT NULL DEFAULT 0
);

CREATE UNIQUE INDEX IF NOT EXISTS uk_skill_policy
    ON ai_skill_policy(tenant_id, skill_api_key) WHERE delete_flg = 0;
CREATE INDEX IF NOT EXISTS idx_skill_policy_skill
    ON ai_skill_policy(skill_api_key) WHERE delete_flg = 0;

-- 12. Skill 执行审计日志
CREATE TABLE IF NOT EXISTS ai_skill_exec_log (
    id              BIGINT PRIMARY KEY,
    tenant_id       BIGINT NOT NULL,
    user_id         BIGINT NOT NULL,
    skill_api_key   VARCHAR(100) NOT NULL,
    skill_version   VARCHAR(20) NOT NULL DEFAULT '',
    thread_id       VARCHAR(64) DEFAULT '',
    trace_id        VARCHAR(64) DEFAULT '',
    parent_span_id  VARCHAR(64) DEFAULT '',
    idempotency_key VARCHAR(128) DEFAULT '',
    exec_mode       VARCHAR(20) NOT NULL DEFAULT 'inline',
    run_mode        VARCHAR(20) NOT NULL DEFAULT 'execute',
    arguments       TEXT DEFAULT '{}',
    formatted_prompt_hash VARCHAR(64) DEFAULT '',
    status          VARCHAR(20) NOT NULL DEFAULT 'running',
    output_summary  TEXT DEFAULT '',
    error_code      VARCHAR(50) DEFAULT '',
    error_message   TEXT DEFAULT '',
    tool_calls      TEXT DEFAULT '[]',
    tool_call_count INT NOT NULL DEFAULT 0,
    llm_call_count  INT NOT NULL DEFAULT 0,
    input_tokens    INT NOT NULL DEFAULT 0,
    output_tokens   INT NOT NULL DEFAULT 0,
    total_tokens    INT NOT NULL DEFAULT 0,
    duration_ms     INT NOT NULL DEFAULT 0,
    start_time      BIGINT NOT NULL,
    end_time        BIGINT DEFAULT 0,
    user_feedback   VARCHAR(20) DEFAULT '',
    feedback_comment TEXT DEFAULT '',
    delete_flg      SMALLINT NOT NULL DEFAULT 0,
    created_at      BIGINT NOT NULL,
    created_by      BIGINT NOT NULL DEFAULT 0,
    updated_at      BIGINT NOT NULL,
    updated_by      BIGINT NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_skill_exec_tenant_skill
    ON ai_skill_exec_log(tenant_id, skill_api_key, start_time DESC);
CREATE INDEX IF NOT EXISTS idx_skill_exec_user
    ON ai_skill_exec_log(tenant_id, user_id, start_time DESC);
CREATE INDEX IF NOT EXISTS idx_skill_exec_trace
    ON ai_skill_exec_log(trace_id) WHERE trace_id != '';
CREATE INDEX IF NOT EXISTS idx_skill_exec_status
    ON ai_skill_exec_log(tenant_id, status, start_time DESC);
CREATE INDEX IF NOT EXISTS idx_skill_exec_idempotency
    ON ai_skill_exec_log(tenant_id, idempotency_key)
    WHERE idempotency_key != '' AND status = 'success';
CREATE INDEX IF NOT EXISTS idx_skill_exec_time
    ON ai_skill_exec_log(tenant_id, start_time DESC);
