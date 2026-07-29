-- 迁移：为评测用例添加 cleanup_steps 字段
-- 用途：用例执行完成后自动清理初始化数据，保证沙箱环境干净

ALTER TABLE ai_eval_tool_case
ADD COLUMN IF NOT EXISTS cleanup_steps JSONB NOT NULL DEFAULT '[]';

COMMENT ON COLUMN ai_eval_tool_case.cleanup_steps IS '后置清理步骤 — 用例执行后清理初始化数据';
