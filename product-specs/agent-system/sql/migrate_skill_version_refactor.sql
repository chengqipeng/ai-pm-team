-- ═══════════════════════════════════════════════════════════
-- Skill 三表结构重构
--
-- ai_skill              主记录（版本无关，每个 Skill 一行）
-- ai_skill_definition   版本内容（每个版本一行）
-- ai_skill_resource     资源文件（每个版本独立一套）
--
-- 关联：ai_skill.api_key → ai_skill_definition.skill_api_key
--       ai_skill.api_key → ai_skill_resource.skill_api_key
--       ai_skill.current_version → 指向当前生效的 definition.version
-- ═══════════════════════════════════════════════════════════

SET search_path TO paas_ai;

-- ═══════════════════════════════════════════════════════════
-- 1. ai_skill — 主记录
-- ═══════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS ai_skill (
    id                BIGINT        PRIMARY KEY,
    api_key           VARCHAR(100)  NOT NULL,
    tenant_id         BIGINT        NOT NULL DEFAULT 0,
    name              VARCHAR(200)  NOT NULL DEFAULT '',
    description       VARCHAR(1000) NOT NULL DEFAULT '',
    owner             VARCHAR(100)  DEFAULT '',
    category          VARCHAR(50)   DEFAULT '',
    tags              TEXT          NOT NULL DEFAULT '[]',
    icon              VARCHAR(100)  DEFAULT '',
    sort_num          INT           NOT NULL DEFAULT 0,
    current_version   VARCHAR(20)   NOT NULL DEFAULT '1.0.0',
    enabled_flg       SMALLINT      NOT NULL DEFAULT 1,
    system_flg        SMALLINT      NOT NULL DEFAULT 0,
    exec_count        INT           NOT NULL DEFAULT 0,
    success_count     INT           NOT NULL DEFAULT 0,
    avg_duration_ms   INT           NOT NULL DEFAULT 0,
    ext_info          TEXT          DEFAULT '{}',
    delete_flg        SMALLINT      NOT NULL DEFAULT 0,
    created_at        BIGINT        NOT NULL,
    created_by        BIGINT        NOT NULL DEFAULT 0,
    updated_at        BIGINT        NOT NULL,
    updated_by        BIGINT        NOT NULL DEFAULT 0
);

CREATE UNIQUE INDEX IF NOT EXISTS uk_skill_apikey
    ON ai_skill(tenant_id, api_key) WHERE delete_flg = 0;
CREATE INDEX IF NOT EXISTS idx_skill_category
    ON ai_skill(tenant_id, category) WHERE delete_flg = 0;
CREATE INDEX IF NOT EXISTS idx_skill_enabled
    ON ai_skill(tenant_id, enabled_flg) WHERE delete_flg = 0;

-- ═══════════════════════════════════════════════════════════
-- 2. ai_skill_definition — 版本内容（重建）
-- ═══════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS ai_skill_definition (
    id                BIGINT        PRIMARY KEY,
    skill_api_key     VARCHAR(100)  NOT NULL,
    tenant_id         BIGINT        NOT NULL DEFAULT 0,
    version           VARCHAR(20)   NOT NULL DEFAULT '1.0.0',
    changelog         TEXT          DEFAULT '',
    -- 技能配置
    when_to_use       VARCHAR(500)  DEFAULT '',
    context           VARCHAR(20)   NOT NULL DEFAULT 'inline',
    agent             VARCHAR(100)  DEFAULT '',
    model             VARCHAR(100)  DEFAULT '',
    allowed_tools     TEXT          NOT NULL DEFAULT '[]',
    arguments         TEXT          NOT NULL DEFAULT '[]',
    prompt            TEXT          NOT NULL DEFAULT '',
    risk_level        VARCHAR(20)   NOT NULL DEFAULT 'read_only',
    requires_confirmation SMALLINT  NOT NULL DEFAULT 0,
    max_tool_calls    INT           NOT NULL DEFAULT 20,
    timeout_ms        INT           NOT NULL DEFAULT 60000,
    output_mode       VARCHAR(20)   NOT NULL DEFAULT 'text',
    component_apikey  VARCHAR(100)  DEFAULT '',
    post_output_behavior VARCHAR(20) NOT NULL DEFAULT 'silent',
    -- 状态
    published_by      BIGINT        NOT NULL DEFAULT 0,
    delete_flg        SMALLINT      NOT NULL DEFAULT 0,
    created_at        BIGINT        NOT NULL,
    created_by        BIGINT        NOT NULL DEFAULT 0,
    updated_at        BIGINT        NOT NULL,
    updated_by        BIGINT        NOT NULL DEFAULT 0
);

CREATE UNIQUE INDEX IF NOT EXISTS uk_skill_def_version
    ON ai_skill_definition(tenant_id, skill_api_key, version) WHERE delete_flg = 0;
CREATE INDEX IF NOT EXISTS idx_skill_def_skill
    ON ai_skill_definition(tenant_id, skill_api_key) WHERE delete_flg = 0;

-- ═══════════════════════════════════════════════════════════
-- 3. ai_skill_resource — 资源文件（增加 version 字段）
-- ═══════════════════════════════════════════════════════════

ALTER TABLE ai_skill_resource ADD COLUMN IF NOT EXISTS version VARCHAR(20) NOT NULL DEFAULT '1.0.0';

DROP INDEX IF EXISTS uk_skill_resource_path;
CREATE UNIQUE INDEX IF NOT EXISTS uk_skill_resource_path
    ON ai_skill_resource(tenant_id, skill_api_key, version, path) WHERE delete_flg = 0;
CREATE INDEX IF NOT EXISTS idx_skill_resource_version
    ON ai_skill_resource(tenant_id, skill_api_key, version) WHERE delete_flg = 0;

-- ═══════════════════════════════════════════════════════════
-- 4. 旧表保留（ai_skill_version 可后续清理）
-- ═══════════════════════════════════════════════════════════

COMMENT ON TABLE ai_skill IS 'Skill 主记录 — 版本无关元信息';
COMMENT ON TABLE ai_skill_definition IS 'Skill 版本内容 — 每个版本一行';
COMMENT ON COLUMN ai_skill.current_version IS '当前生效版本号，指向 ai_skill_definition.version';
COMMENT ON COLUMN ai_skill_resource.version IS '关联版本号';
