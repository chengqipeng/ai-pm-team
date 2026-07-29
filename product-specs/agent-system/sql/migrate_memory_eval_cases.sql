-- ═══════════════════════════════════════════════════════════
-- Memory 评测用例 + 报告持久化存储
-- 对齐 Tool 评测三表结构：Suite → Case → Report + CaseResult
-- ═══════════════════════════════════════════════════════════

-- 评测套件表（Memory 评测顶层分组）
CREATE TABLE IF NOT EXISTS ai_eval_memory_suite (
    id              BIGSERIAL PRIMARY KEY,
    suite_key       VARCHAR(100) NOT NULL UNIQUE,      -- 如 'default', 'recall_v2'
    name            VARCHAR(200) NOT NULL,
    description     TEXT DEFAULT '',
    status          VARCHAR(20) DEFAULT 'active',      -- active / archived
    created_at      BIGINT NOT NULL,
    updated_at      BIGINT NOT NULL
);

-- 记忆评测用例表
CREATE TABLE IF NOT EXISTS ai_eval_memory_case (
    id              BIGSERIAL PRIMARY KEY,
    suite_id        BIGINT NOT NULL REFERENCES ai_eval_memory_suite(id),
    case_key        VARCHAR(100) NOT NULL,             -- 用例唯一标识如 exact_01, ext_profile_01
    layer           VARCHAR(50) NOT NULL,              -- extract / retrieval / temporal / context / e2e
    query_type      VARCHAR(100) NOT NULL,             -- exact_entity / fuzzy_semantic / extract_profile ...
    query           TEXT NOT NULL DEFAULT '',          -- 检索查询 / 用户发言
    description     VARCHAR(500) DEFAULT '',
    expected_memories   JSONB NOT NULL DEFAULT '[]',   -- 期望命中的 merge_key 或关键词
    expected_category   VARCHAR(100) DEFAULT '',
    expected_parent_entity VARCHAR(100) DEFAULT '',
    expected_dimensions JSONB NOT NULL DEFAULT '[]',   -- 期望提取维度: ["profile","preferences"]
    expected_action VARCHAR(50) DEFAULT '',            -- 反思期望动作: update_old/archive_old/keep_both
    conflict_type   VARCHAR(50) DEFAULT '',            -- 冲突类型: contradiction/evolution
    test_focus      VARCHAR(500) DEFAULT '',           -- 测试重点描述
    top_k           INT DEFAULT 5,
    assertion_mode  VARCHAR(20) DEFAULT 'any',         -- any / all / ordered
    negative        BOOLEAN DEFAULT FALSE,             -- 负例标记
    existing_memory JSONB DEFAULT '{}',                -- 反思用例已有记忆
    metadata        JSONB DEFAULT '{}',                -- 扩展元数据
    priority        INT DEFAULT 0,
    enabled         BOOLEAN DEFAULT TRUE,
    generated_by    VARCHAR(50) DEFAULT 'preset',      -- preset / manual / recording
    status          VARCHAR(20) DEFAULT 'active',
    created_at      BIGINT NOT NULL,
    updated_at      BIGINT NOT NULL,
    UNIQUE(suite_id, case_key)
);

-- 记忆评测执行报告表
CREATE TABLE IF NOT EXISTS ai_eval_memory_report (
    id              BIGSERIAL PRIMARY KEY,
    report_key      VARCHAR(100) NOT NULL UNIQUE,
    suite_id        BIGINT NOT NULL REFERENCES ai_eval_memory_suite(id),
    trigger_type    VARCHAR(50) DEFAULT 'manual',      -- manual / scheduled / ci
    filter_layers   JSONB DEFAULT '[]',                -- 筛选条件：层列表
    filter_query_types JSONB DEFAULT '[]',             -- 筛选条件：查询类型列表
    use_llm         BOOLEAN DEFAULT FALSE,             -- 是否使用真实 LLM 提取
    total           INT DEFAULT 0,
    passed          INT DEFAULT 0,
    failed          INT DEFAULT 0,
    pass_rate       NUMERIC(6,4) DEFAULT 0,
    avg_recall_at_5 NUMERIC(6,4) DEFAULT 0,
    avg_mrr         NUMERIC(6,4) DEFAULT 0,
    top1_hit_rate   NUMERIC(6,4) DEFAULT 0,
    total_duration_ms NUMERIC(12,1) DEFAULT 0,
    by_layer        JSONB DEFAULT '{}',
    by_query_type   JSONB DEFAULT '{}',
    failures        JSONB DEFAULT '[]',
    status          VARCHAR(20) DEFAULT 'running',     -- running / completed / failed
    created_at      BIGINT NOT NULL,
    completed_at    BIGINT DEFAULT NULL
);

-- 记忆评测用例执行结果明细表
CREATE TABLE IF NOT EXISTS ai_eval_memory_case_result (
    id              BIGSERIAL PRIMARY KEY,
    report_id       BIGINT NOT NULL REFERENCES ai_eval_memory_report(id),
    case_id         BIGINT NOT NULL REFERENCES ai_eval_memory_case(id),
    case_key        VARCHAR(100) NOT NULL,
    layer           VARCHAR(50) NOT NULL,
    query_type      VARCHAR(100) NOT NULL,
    query           TEXT DEFAULT '',
    description     VARCHAR(500) DEFAULT '',
    passed          BOOLEAN DEFAULT FALSE,
    recall_at_k     NUMERIC(6,4) DEFAULT 0,
    precision_at_k  NUMERIC(6,4) DEFAULT 0,
    mrr             NUMERIC(6,4) DEFAULT 0,
    top1_hit        BOOLEAN DEFAULT FALSE,
    duration_ms     NUMERIC(10,1) DEFAULT 0,
    expected        JSONB DEFAULT '[]',                -- 期望的记忆/维度
    actual          JSONB DEFAULT '[]',                -- 实际召回结果 Top-K
    memory_snapshot_count INT DEFAULT 0,               -- 执行时记忆库条数
    memory_snapshot JSONB DEFAULT '[]',                -- 执行时记忆库全量快照（用于人工分析）
    memory_changes  JSONB DEFAULT '[]',                -- 记忆变更日志
    extracted_dimensions JSONB DEFAULT '[]',           -- 提取的维度
    output_detail   JSONB DEFAULT '{}',                -- 完整输出详情
    error_message   TEXT DEFAULT '',
    created_at      BIGINT NOT NULL
);

-- 索引
CREATE INDEX IF NOT EXISTS idx_mem_eval_case_layer ON ai_eval_memory_case(layer);
CREATE INDEX IF NOT EXISTS idx_mem_eval_case_qt ON ai_eval_memory_case(query_type);
CREATE INDEX IF NOT EXISTS idx_mem_eval_case_suite ON ai_eval_memory_case(suite_id, enabled);
CREATE INDEX IF NOT EXISTS idx_mem_eval_report_suite ON ai_eval_memory_report(suite_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_mem_eval_result_report ON ai_eval_memory_case_result(report_id);
CREATE INDEX IF NOT EXISTS idx_mem_eval_result_case ON ai_eval_memory_case_result(case_id);

-- 初始化默认 Suite
INSERT INTO ai_eval_memory_suite (suite_key, name, description, created_at, updated_at)
VALUES ('default', 'Memory 评测 — 默认全量', '长期记忆召回率 + 四维度提取评测，450+ 用例', EXTRACT(EPOCH FROM NOW())::BIGINT * 1000, EXTRACT(EPOCH FROM NOW())::BIGINT * 1000)
ON CONFLICT (suite_key) DO NOTHING;
