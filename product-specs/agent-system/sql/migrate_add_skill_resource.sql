-- ═══════════════════════════════════════════════════════════
-- Skill 资源表 — 虚拟目录模式
-- 对齐 apps-agent 的 knowledge/ 目录结构
--
-- 设计：目录和文件统一为"节点"，通过 parent_id 构建树
-- 支持无限层级、目录元数据、前端文件树渲染
-- ═══════════════════════════════════════════════════════════

SET search_path TO paas_ai;

-- ═══════════════════════════════════════════════════════════
-- 1. ai_skill_resource — 虚拟目录模式
-- ═══════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS ai_skill_resource (
    id                BIGINT        PRIMARY KEY,
    tenant_id         BIGINT        NOT NULL DEFAULT 0,
    skill_api_key     VARCHAR(100)  NOT NULL,

    -- 树形结构
    parent_id         BIGINT,                          -- 父节点 ID（根节点为 NULL）
    node_type         VARCHAR(10)   NOT NULL DEFAULT 'file',  -- dir=目录 / file=文件
    name              VARCHAR(200)  NOT NULL,           -- 节点名称
    path              VARCHAR(500)  NOT NULL,           -- 完整路径（冗余，加速查询）
    depth             SMALLINT      NOT NULL DEFAULT 0, -- 层级深度（根=0）

    -- 文件内容（dir 为 NULL）
    content           TEXT,
    content_type      VARCHAR(20)   NOT NULL DEFAULT 'md',
    content_size      INT           NOT NULL DEFAULT 0,

    -- 元数据
    description       VARCHAR(500)  NOT NULL DEFAULT '',
    icon              VARCHAR(50)   NOT NULL DEFAULT '',
    sort_num          INT           NOT NULL DEFAULT 0,

    -- 状态
    enabled_flg       SMALLINT      NOT NULL DEFAULT 1,
    delete_flg        SMALLINT      NOT NULL DEFAULT 0,
    created_at        BIGINT        NOT NULL,
    created_by        BIGINT        NOT NULL DEFAULT 0,
    updated_at        BIGINT        NOT NULL,
    updated_by        BIGINT        NOT NULL DEFAULT 0
);

CREATE UNIQUE INDEX IF NOT EXISTS uk_skill_resource_path
    ON ai_skill_resource(tenant_id, skill_api_key, path) WHERE delete_flg = 0;
CREATE INDEX IF NOT EXISTS idx_skill_resource_parent
    ON ai_skill_resource(tenant_id, skill_api_key, parent_id) WHERE delete_flg = 0;
CREATE INDEX IF NOT EXISTS idx_skill_resource_file_path
    ON ai_skill_resource(skill_api_key, path) WHERE delete_flg = 0 AND node_type = 'file';

COMMENT ON TABLE ai_skill_resource IS 'Skill 关联资源 — 虚拟目录模式（对齐 apps-agent knowledge/ 目录）';


-- ═══════════════════════════════════════════════════════════
-- 2. ai_skill_definition 新增字段
-- ═══════════════════════════════════════════════════════════

ALTER TABLE ai_skill_definition
ADD COLUMN IF NOT EXISTS output_model_names TEXT NOT NULL DEFAULT '[]';

ALTER TABLE ai_skill_definition
ADD COLUMN IF NOT EXISTS visible_flg SMALLINT NOT NULL DEFAULT 1;
