-- ═══════════════════════════════════════════════════════════
-- 新增 post_output_behavior 字段
-- Fork skill 输出后主 Agent 行为控制：silent | summarize | continue | passthrough
-- ═══════════════════════════════════════════════════════════

ALTER TABLE ai_skill_definition
ADD COLUMN IF NOT EXISTS post_output_behavior VARCHAR(20) NOT NULL DEFAULT 'silent';

COMMENT ON COLUMN ai_skill_definition.post_output_behavior IS
  'Fork skill 输出后主 Agent 行为: silent(沉默) | summarize(简短总结) | continue(继续决策) | passthrough(不直出,回传LLM)';

-- ═══════════════════════════════════════════════════════════
-- 为现有 Skill 设置 post_output_behavior
-- ═══════════════════════════════════════════════════════════

-- 客户洞察：完整报告自包含，主 Agent 沉默
UPDATE ai_skill_definition SET post_output_behavior = 'silent'
WHERE api_key IN ('accountInsight', 'account-insight', 'account_insight')
  AND delete_flg = 0;

-- 知识检索：检索结果直出后，主 Agent 追加简短引导
UPDATE ai_skill_definition SET post_output_behavior = 'summarize'
WHERE api_key = 'knowledge_doc_search'
  AND delete_flg = 0;

-- 数据分析：表格结果自包含
UPDATE ai_skill_definition SET post_output_behavior = 'silent'
WHERE api_key IN ('data_analysis', 'pipeline_analysis')
  AND delete_flg = 0;

-- 诊断/校验（inline 模式，此字段不生效，设默认值）
UPDATE ai_skill_definition SET post_output_behavior = 'silent'
WHERE api_key IN ('verify_config', 'diagnose', 'inspect_metamodel', 'trace_db_column')
  AND delete_flg = 0;

-- 批量操作：结果直出后可能需要继续
UPDATE ai_skill_definition SET post_output_behavior = 'continue'
WHERE api_key = 'batch_cleanup'
  AND delete_flg = 0;
