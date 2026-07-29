-- 为 ai_eval_memory_case_result 添加 memory_snapshot 列
-- 用于保存每条用例执行时记忆库的全量快照，支持人工分析数据提取是否准确

ALTER TABLE ai_eval_memory_case_result
ADD COLUMN IF NOT EXISTS memory_snapshot JSONB DEFAULT '[]';

COMMENT ON COLUMN ai_eval_memory_case_result.memory_snapshot IS '执行时记忆库全量快照 — 用于人工分析提取/检索是否准确';
