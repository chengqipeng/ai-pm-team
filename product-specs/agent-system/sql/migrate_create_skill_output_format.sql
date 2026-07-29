-- ═══════════════════════════════════════════════════════════
-- 迁移脚本：create_skill 输出格式优化（v1.3.0）
-- 
-- 变更内容：
--   1. prompt 重写为结构化输出格式模板（Step 1/2/3&4 风格）
--   2. post_output_behavior 从 'silent' 改为 'continue'
--   3. version 升至 1.3.0
--
-- 修复的问题：
--   - create_skill 是 inline 模式，返回 prompt 给主 Agent 继续推理
--   - post_output_behavior='silent' 导致主 Agent 不输出设计过程
--   - ai_skill.current_version 必须与 ai_skill_definition.version 同步
--
-- 执行方式：psql -U postgres -d paas_db -f sql/migrate_create_skill_output_format.sql
-- ═══════════════════════════════════════════════════════════

-- 1. 同步 ai_skill 主表的 current_version
UPDATE ai_skill
SET current_version = '1.3.0',
    updated_at = EXTRACT(EPOCH FROM NOW())::BIGINT * 1000
WHERE api_key = 'create_skill'
  AND delete_flg = 0;

-- 2. 修改 post_output_behavior（inline 模式技能必须用 continue，不能 silent）
-- 3. 更新 prompt 和 version
UPDATE ai_skill_definition
SET
    post_output_behavior = 'continue',
    version = '1.3.0',
    updated_at = EXTRACT(EPOCH FROM NOW())::BIGINT * 1000
    -- prompt 通过 Python 脚本更新（内容过长不适合内联 SQL）
    -- 见 skills/definitions/create_skill/SKILL.md 中完整 prompt
WHERE skill_api_key = 'create_skill'
  AND delete_flg = 0;

-- 验证
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM ai_skill_definition d
        INNER JOIN ai_skill s
            ON s.api_key = d.skill_api_key
            AND s.tenant_id = d.tenant_id
            AND s.current_version = d.version
            AND s.delete_flg = 0
            AND s.enabled_flg = 1
        WHERE d.skill_api_key = 'create_skill'
          AND d.delete_flg = 0
          AND d.version = '1.3.0'
    ) THEN
        RAISE EXCEPTION 'create_skill v1.3.0 JOIN 验证失败！请检查 ai_skill.current_version';
    END IF;
END $$;
