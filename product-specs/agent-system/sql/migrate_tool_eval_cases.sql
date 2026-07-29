-- ═══════════════════════════════════════════════════════════
-- Tool 评测用例持久化存储
-- 支持按工具分类、方法分类、参数组合维度管理用例
-- ═══════════════════════════════════════════════════════════

-- 评测套件表（顶层分组）
CREATE TABLE IF NOT EXISTS ai_eval_tool_suite (
    id              BIGSERIAL PRIMARY KEY,
    suite_key       VARCHAR(100) NOT NULL UNIQUE,      -- 如 'default', 'regression_v1'
    name            VARCHAR(200) NOT NULL,
    description     TEXT DEFAULT '',
    status          VARCHAR(20) DEFAULT 'active',      -- active / archived
    created_at      BIGINT NOT NULL,
    updated_at      BIGINT NOT NULL
);

-- 评测用例表（核心表）
CREATE TABLE IF NOT EXISTS ai_eval_tool_case (
    id              BIGSERIAL PRIMARY KEY,
    suite_id        BIGINT NOT NULL REFERENCES ai_eval_tool_suite(id),
    case_key        VARCHAR(100) NOT NULL,             -- 用例唯一标识如 qs_01
    tool_name       VARCHAR(100) NOT NULL,             -- 工具名: query_schema, query_data, modify_data...
    method_name     VARCHAR(100) NOT NULL DEFAULT '',  -- 方法名: list_entities, entity, query, get, create...
    description     VARCHAR(500) DEFAULT '',
    category        VARCHAR(50) DEFAULT 'normal',      -- normal / error / boundary / side_effect
    input_data      JSONB NOT NULL DEFAULT '{}',       -- 工具输入参数
    assertions      JSONB NOT NULL DEFAULT '[]',       -- 断言规则列表
    setup_steps     JSONB NOT NULL DEFAULT '[]',       -- 前置步骤
    tags            JSONB NOT NULL DEFAULT '[]',       -- 标签 ["positive","negative","edge"]
    priority        INT DEFAULT 0,                     -- 优先级（越高越优先执行）
    timeout_ms      INT DEFAULT 10000,
    enabled         BOOLEAN DEFAULT TRUE,
    generated_by    VARCHAR(50) DEFAULT 'manual',      -- manual / auto_combination / recording
    source_params   JSONB DEFAULT NULL,                -- 生成来源参数（自动组合时记录）
    status          VARCHAR(20) DEFAULT 'active',      -- active / disabled / deprecated
    created_at      BIGINT NOT NULL,
    updated_at      BIGINT NOT NULL,
    UNIQUE(suite_id, case_key)
);

-- 评测执行报告表
CREATE TABLE IF NOT EXISTS ai_eval_tool_report (
    id              BIGSERIAL PRIMARY KEY,
    report_key      VARCHAR(100) NOT NULL UNIQUE,
    suite_id        BIGINT NOT NULL REFERENCES ai_eval_tool_suite(id),
    trigger_type    VARCHAR(50) DEFAULT 'manual',      -- manual / scheduled / ci
    filter_tools    JSONB DEFAULT '[]',                -- 筛选条件：工具列表
    filter_methods  JSONB DEFAULT '[]',                -- 筛选条件：方法列表
    filter_categories JSONB DEFAULT '[]',              -- 筛选条件：分类列表
    total           INT DEFAULT 0,
    passed          INT DEFAULT 0,
    failed          INT DEFAULT 0,
    error_count     INT DEFAULT 0,
    pass_rate       NUMERIC(6,4) DEFAULT 0,
    total_duration_ms NUMERIC(10,1) DEFAULT 0,
    by_tool         JSONB DEFAULT '{}',
    by_method       JSONB DEFAULT '{}',
    by_category     JSONB DEFAULT '{}',
    failures        JSONB DEFAULT '[]',
    status          VARCHAR(20) DEFAULT 'running',     -- running / completed / failed
    created_at      BIGINT NOT NULL,
    completed_at    BIGINT DEFAULT NULL
);

-- 评测用例执行结果明细表
CREATE TABLE IF NOT EXISTS ai_eval_tool_case_result (
    id              BIGSERIAL PRIMARY KEY,
    report_id       BIGINT NOT NULL REFERENCES ai_eval_tool_report(id),
    case_id         BIGINT NOT NULL REFERENCES ai_eval_tool_case(id),
    case_key        VARCHAR(100) NOT NULL,
    tool_name       VARCHAR(100) NOT NULL,
    method_name     VARCHAR(100) DEFAULT '',
    category        VARCHAR(50) DEFAULT '',
    passed          BOOLEAN DEFAULT FALSE,
    duration_ms     NUMERIC(10,1) DEFAULT 0,
    tool_output     TEXT DEFAULT '',
    is_error        BOOLEAN DEFAULT FALSE,
    assertion_results JSONB DEFAULT '[]',
    error_message   TEXT DEFAULT '',
    created_at      BIGINT NOT NULL
);

-- 索引
CREATE INDEX IF NOT EXISTS idx_eval_case_tool ON ai_eval_tool_case(tool_name);
CREATE INDEX IF NOT EXISTS idx_eval_case_method ON ai_eval_tool_case(tool_name, method_name);
CREATE INDEX IF NOT EXISTS idx_eval_case_category ON ai_eval_tool_case(category);
CREATE INDEX IF NOT EXISTS idx_eval_case_suite ON ai_eval_tool_case(suite_id, enabled);
CREATE INDEX IF NOT EXISTS idx_eval_report_suite ON ai_eval_tool_report(suite_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_eval_case_result_report ON ai_eval_tool_case_result(report_id);

-- 初始化默认 Suite
INSERT INTO ai_eval_tool_suite (suite_key, name, description, created_at, updated_at)
VALUES ('default', 'Tool 评测 — 默认全量', '覆盖所有内置工具的正常/异常/边界/副作用场景', EXTRACT(EPOCH FROM NOW())::BIGINT * 1000, EXTRACT(EPOCH FROM NOW())::BIGINT * 1000)
ON CONFLICT (suite_key) DO NOTHING;
