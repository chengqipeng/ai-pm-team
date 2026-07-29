-- Skill 输出模式迁移：新增 output_mode + component_apikey + system_flg 字段
-- 执行前提：ai_skill_definition 表已存在，migrate_skill_enabled.sql 已执行
--
-- output_mode 决定 Skill 输出在前端的渲染方式：
--   text      — 对话气泡（Markdown 文本，嵌入对话流）
--   card      — 文档面板（右侧独立面板，适合长报告）
--   component — 业务组件（A2UI 卡片渲染）
--   table     — 数据表格（结构化列表展示）
--   auto      — 系统自动判断（默认值，不推荐）

SET search_path TO paas_ai;

-- 新增 output_mode 字段
ALTER TABLE ai_skill_definition
ADD COLUMN IF NOT EXISTS output_mode VARCHAR(20) NOT NULL DEFAULT 'text';

-- 新增 component_apikey 字段（output_mode=component 时指定渲染组件）
ALTER TABLE ai_skill_definition
ADD COLUMN IF NOT EXISTS component_apikey VARCHAR(100) NOT NULL DEFAULT '';

-- 新增 system_flg 字段（1=系统预置不可删除, 0=用户创建）
ALTER TABLE ai_skill_definition
ADD COLUMN IF NOT EXISTS system_flg SMALLINT NOT NULL DEFAULT 0;

COMMENT ON COLUMN ai_skill_definition.output_mode IS
  '输出渲染模式: text(对话气泡) | card(文档面板) | component(业务组件) | table(数据表格)';
COMMENT ON COLUMN ai_skill_definition.component_apikey IS
  '当 output_mode=component 时，指定渲染的 A2UI 组件 apikey';

-- ═══════════════════════════════════════════════════════════
-- 为现有 Skill 设置正确的 output_mode
-- ═══════════════════════════════════════════════════════════

-- 客户洞察：对话气泡（直接在对话中显示分析报告）
UPDATE ai_skill_definition SET output_mode = 'text'
WHERE api_key = 'accountInsight' AND delete_flg = 0;

-- 知识检索：对话气泡
UPDATE ai_skill_definition SET output_mode = 'text'
WHERE api_key = 'knowledge_doc_search' AND delete_flg = 0;

-- 其他分析类 Skill：对话气泡
UPDATE ai_skill_definition SET output_mode = 'text'
WHERE api_key IN ('verify_config', 'diagnose', 'inspect_metamodel',
                  'trace_db_column', 'inspect_entity_metadata', 'batch_cleanup',
                  'create_skill')
  AND delete_flg = 0;

-- 数据分析类：表格展示
UPDATE ai_skill_definition SET output_mode = 'table'
WHERE api_key IN ('data_analysis', 'pipeline_analysis')
  AND delete_flg = 0;
