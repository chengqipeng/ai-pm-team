-- Skill 表结构迁移：简化状态模型，新增分类字段
-- 执行前提：ai_skill_definition 表已存在

SET search_path TO paas_ai;

-- 新增 enabled_flg 字段（1=启用, 0=禁用）
ALTER TABLE ai_skill_definition ADD COLUMN IF NOT EXISTS enabled_flg SMALLINT NOT NULL DEFAULT 1;

-- 新增分类字段
ALTER TABLE ai_skill_definition ADD COLUMN IF NOT EXISTS category VARCHAR(50) DEFAULT '';

-- 新增标签字段
ALTER TABLE ai_skill_definition ADD COLUMN IF NOT EXISTS tags TEXT DEFAULT '[]';

-- 新增图标字段
ALTER TABLE ai_skill_definition ADD COLUMN IF NOT EXISTS icon VARCHAR(100) DEFAULT '';

-- 新增排序字段
ALTER TABLE ai_skill_definition ADD COLUMN IF NOT EXISTS sort_num INT DEFAULT 0;

-- 将已有 status='published' 的记录设为 enabled_flg=1
UPDATE ai_skill_definition SET enabled_flg = 1 WHERE status = 'published' AND delete_flg = 0;

-- 将已有 status='deprecated' 或 'draft' 的记录设为 enabled_flg=0
UPDATE ai_skill_definition SET enabled_flg = 0 WHERE status IN ('deprecated', 'draft') AND delete_flg = 0;

-- 新增索引
CREATE INDEX IF NOT EXISTS idx_skill_def_enabled
    ON ai_skill_definition(tenant_id, enabled_flg) WHERE delete_flg = 0;
CREATE INDEX IF NOT EXISTS idx_skill_def_category
    ON ai_skill_definition(tenant_id, category) WHERE delete_flg = 0;
