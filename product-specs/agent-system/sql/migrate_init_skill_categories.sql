-- 迁移脚本：初始化 Skill 分类表数据 + 为已有技能设置 category
-- 执行前提：ai_skill_category 表已创建（见 init_tables.sql 9b 节）
--           ai_skill_definition 表已有 category 列（ALTER TABLE 已执行）
-- 幂等：使用 ON CONFLICT DO NOTHING，可重复执行

SET search_path TO paas_ai;

-- ═══════════════════════════════════════════════════════════
-- 1. 创建分类表（如果尚未创建）
-- ═══════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS ai_skill_category (
    id              BIGINT PRIMARY KEY,
    api_key         VARCHAR(50) NOT NULL,
    tenant_id       BIGINT NOT NULL DEFAULT 0,
    name            VARCHAR(100) NOT NULL DEFAULT '',
    name_key        VARCHAR(100) NOT NULL DEFAULT '',
    description     VARCHAR(500) DEFAULT '',
    icon            VARCHAR(100) DEFAULT '',
    color           VARCHAR(20) DEFAULT '',
    sort_num        INT NOT NULL DEFAULT 0,
    enabled_flg     SMALLINT NOT NULL DEFAULT 1,
    system_flg      SMALLINT NOT NULL DEFAULT 0,
    delete_flg      SMALLINT NOT NULL DEFAULT 0,
    created_at      BIGINT NOT NULL,
    created_by      BIGINT NOT NULL DEFAULT 0,
    updated_at      BIGINT NOT NULL,
    updated_by      BIGINT NOT NULL DEFAULT 0
);

CREATE UNIQUE INDEX IF NOT EXISTS uk_skill_category_key
    ON ai_skill_category(tenant_id, api_key) WHERE delete_flg = 0;
CREATE INDEX IF NOT EXISTS idx_skill_category_sort
    ON ai_skill_category(tenant_id, enabled_flg, sort_num) WHERE delete_flg = 0;

-- ═══════════════════════════════════════════════════════════
-- 2. 为 ai_skill_definition 添加扩展列（如果尚未添加）
-- ═══════════════════════════════════════════════════════════

ALTER TABLE ai_skill_definition ADD COLUMN IF NOT EXISTS category VARCHAR(50) DEFAULT '';
ALTER TABLE ai_skill_definition ADD COLUMN IF NOT EXISTS enabled_flg SMALLINT NOT NULL DEFAULT 1;
ALTER TABLE ai_skill_definition ADD COLUMN IF NOT EXISTS tags TEXT DEFAULT '[]';
ALTER TABLE ai_skill_definition ADD COLUMN IF NOT EXISTS icon VARCHAR(100) DEFAULT '';
ALTER TABLE ai_skill_definition ADD COLUMN IF NOT EXISTS sort_num INT DEFAULT 0;

-- ═══════════════════════════════════════════════════════════
-- 3. 插入预置分类数据（5 个系统级分类）
-- ═══════════════════════════════════════════════════════════

INSERT INTO ai_skill_category (
    id, api_key, tenant_id, name, name_key, description, icon, color,
    sort_num, enabled_flg, system_flg,
    delete_flg, created_at, created_by, updated_at, updated_by
) VALUES
(2000000000000001, 'crm', 0,
 'CRM 业务', 'skill.category.crm',
 'CRM 业务相关技能，如客户分析、商机管理、联系人洞察',
 '📊', '#1890ff', 10, 1, 1, 0, 1746489600000, 0, 1746489600000, 0),

(2000000000000002, 'metarepo', 0,
 '元数据管理', 'skill.category.metarepo',
 '元模型检查、配置校验、列映射反查、元数据实例审计',
 '🗂️', '#52c41a', 20, 1, 1, 0, 1746489600000, 0, 1746489600000, 0),

(2000000000000003, 'analysis', 0,
 '数据分析', 'skill.category.analysis',
 '多维数据分析、统计报表、趋势洞察、异常检测',
 '📈', '#faad14', 30, 1, 1, 0, 1746489600000, 0, 1746489600000, 0),

(2000000000000004, 'automation', 0,
 '自动化操作', 'skill.category.automation',
 '批量处理、定时任务、数据清理等自动化技能',
 '⚙️', '#f5222d', 40, 1, 1, 0, 1746489600000, 0, 1746489600000, 0),

(2000000000000005, 'custom', 0,
 '自定义', 'skill.category.custom',
 '租户自行创建的技能分类',
 '🔧', '#722ed1', 100, 1, 1, 0, 1746489600000, 0, 1746489600000, 0)

ON CONFLICT (tenant_id, api_key) WHERE delete_flg = 0 DO NOTHING;

-- ═══════════════════════════════════════════════════════════
-- 4. 为已有预置技能设置 category（关联分类 api_key）
-- ═══════════════════════════════════════════════════════════

UPDATE ai_skill_definition SET category = 'crm'        WHERE api_key = 'accountInsight'          AND tenant_id = 0 AND delete_flg = 0 AND (category IS NULL OR category = '');
UPDATE ai_skill_definition SET category = 'crm'        WHERE api_key = 'verify_config'           AND tenant_id = 0 AND delete_flg = 0 AND (category IS NULL OR category = '');
UPDATE ai_skill_definition SET category = 'crm'        WHERE api_key = 'diagnose'                AND tenant_id = 0 AND delete_flg = 0 AND (category IS NULL OR category = '');
UPDATE ai_skill_definition SET category = 'crm'        WHERE api_key = 'customer_360'            AND tenant_id = 0 AND delete_flg = 0 AND (category IS NULL OR category = '');
UPDATE ai_skill_definition SET category = 'crm'        WHERE api_key = 'pipeline_analysis'       AND tenant_id = 0 AND delete_flg = 0 AND (category IS NULL OR category = '');
UPDATE ai_skill_definition SET category = 'analysis'   WHERE api_key = 'data_analysis'           AND tenant_id = 0 AND delete_flg = 0 AND (category IS NULL OR category = '');
UPDATE ai_skill_definition SET category = 'automation' WHERE api_key = 'batch_cleanup'           AND tenant_id = 0 AND delete_flg = 0 AND (category IS NULL OR category = '');
UPDATE ai_skill_definition SET category = 'metarepo'   WHERE api_key = 'inspect_metamodel'       AND tenant_id = 0 AND delete_flg = 0 AND (category IS NULL OR category = '');
UPDATE ai_skill_definition SET category = 'metarepo'   WHERE api_key = 'trace_db_column'         AND tenant_id = 0 AND delete_flg = 0 AND (category IS NULL OR category = '');
UPDATE ai_skill_definition SET category = 'metarepo'   WHERE api_key = 'inspect_entity_metadata' AND tenant_id = 0 AND delete_flg = 0 AND (category IS NULL OR category = '');

-- ═══════════════════════════════════════════════════════════
-- 验证
-- ═══════════════════════════════════════════════════════════

-- 查看分类数据
-- SELECT api_key, name, icon, sort_num, enabled_flg, system_flg FROM ai_skill_category WHERE delete_flg = 0 ORDER BY sort_num;

-- 查看技能的分类关联
-- SELECT api_key, name, category FROM ai_skill_definition WHERE delete_flg = 0 AND tenant_id = 0 ORDER BY category, api_key;
