-- ═══════════════════════════════════════════════════════════
-- 记忆数据清理
-- 1. 删除 _aggregate（旧目录聚合，已废弃）
-- 2. 删除已废弃分类
-- 3. 清理 agent_rules 重复（只保留最新一条）
-- ═══════════════════════════════════════════════════════════

-- 1. 删除 _aggregate 类别（旧目录聚合产物，不是真实记忆）
DELETE FROM ai_agent_memory WHERE category = '_aggregate';

-- 2. 删除已废弃分类
DELETE FROM ai_agent_memory WHERE category IN ('events', 'cases', 'patterns', 'tools', 'skills', 'soul');

-- 3. agent_rules 去重：每个 user_id 只保留最新一条
DELETE FROM ai_agent_memory
WHERE category = 'agent_rules'
  AND id NOT IN (
    SELECT DISTINCT ON (tenant_id, user_id) id
    FROM ai_agent_memory
    WHERE category = 'agent_rules' AND delete_flg = 0
    ORDER BY tenant_id, user_id, updated_at DESC
  );

-- 4. 验证
SELECT category, COUNT(*) as cnt
FROM ai_agent_memory
WHERE delete_flg = 0
GROUP BY category
ORDER BY cnt DESC;
-- 预期：profile / preferences / agent_rules / entities
