-- 修复 tenant_id 不一致问题
-- 历史数据中 tenant_id=1 的记录应该属于 tenant_id=292193
-- 执行前请确认当前环境的正确 tenant_id

SET search_path TO paas_ai;

-- 检查受影响的数据量
-- SELECT 'ai_conversation' AS tbl, COUNT(*) FROM ai_conversation WHERE tenant_id = 1
-- UNION ALL
-- SELECT 'ai_trace', COUNT(*) FROM ai_trace WHERE tenant_id = 1
-- UNION ALL
-- SELECT 'ai_trace_span', COUNT(*) FROM ai_trace_span WHERE tenant_id = 1
-- UNION ALL
-- SELECT 'ai_message', COUNT(*) FROM ai_message WHERE tenant_id = 1;

-- 1. 修复 ai_conversation 表
UPDATE ai_conversation SET tenant_id = 292193 WHERE tenant_id = 1;

-- 2. 修复 ai_trace 表
UPDATE ai_trace SET tenant_id = 292193 WHERE tenant_id = 1;

-- 3. 修复 ai_trace_span 表
UPDATE ai_trace_span SET tenant_id = 292193 WHERE tenant_id = 1;

-- 4. 修复 ai_message 表
UPDATE ai_message SET tenant_id = 292193 WHERE tenant_id = 1;

-- 5. 修复 ai_message_ext 表
UPDATE ai_message_ext SET tenant_id = 292193 WHERE tenant_id = 1;

-- 6. 修复 ai_conversation 中 user_id=0 的记录（设为默认用户）
UPDATE ai_conversation
SET user_id = 100000000000000006,
    created_by = 100000000000000006,
    updated_by = 100000000000000006
WHERE tenant_id = 292193 AND user_id = 0;

-- 验证修复结果
-- SELECT 'ai_conversation' AS tbl, COUNT(*) FROM ai_conversation WHERE tenant_id = 292193
-- UNION ALL
-- SELECT 'ai_trace', COUNT(*) FROM ai_trace WHERE tenant_id = 292193
-- UNION ALL
-- SELECT 'ai_conversation (user_id=0)', COUNT(*) FROM ai_conversation WHERE tenant_id = 292193 AND user_id = 0;
