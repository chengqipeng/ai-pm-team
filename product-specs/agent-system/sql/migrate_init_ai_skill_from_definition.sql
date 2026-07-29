-- ═══════════════════════════════════════════════════════════
-- 数据迁移：从旧 ai_skill_definition 初始化 ai_skill 主记录
--
-- 前提：
--   1. ai_skill 表已创建（migrate_skill_version_refactor.sql）
--   2. 旧 ai_skill_definition 表中有存量数据
--
-- 逻辑：
--   将旧 ai_skill_definition 中每个 (tenant_id, api_key) 的数据
--   拆分为 ai_skill（主记录）+ 新 ai_skill_definition（版本内容）
--
-- 执行方式：手动执行一次，幂等（ON CONFLICT DO NOTHING）
-- ═══════════════════════════════════════════════════════════

SET search_path TO paas_ai;

-- ═══════════════════════════════════════════════════════════
-- 1. 从旧 ai_skill_definition 初始化 ai_skill 主记录
-- ═══════════════════════════════════════════════════════════

INSERT INTO ai_skill (
    id, api_key, tenant_id, name, description, owner,
    category, tags, icon, sort_num, current_version,
    enabled_flg, system_flg, exec_count, success_count, avg_duration_ms,
    ext_info, delete_flg, created_at, created_by, updated_at, updated_by
)
SELECT
    id,                                     -- 复用原 ID
    api_key,
    tenant_id,
    name,
    description,
    COALESCE(owner, ''),
    COALESCE(category, ''),
    COALESCE(tags, '[]'),
    COALESCE(icon, ''),
    COALESCE(sort_num, 0),
    COALESCE(version, '1.0.0'),             -- current_version = 旧表的 version 字段
    COALESCE(enabled_flg, 1),
    COALESCE(system_flg, 0),
    COALESCE(exec_count, 0),
    COALESCE(success_count, 0),
    COALESCE(avg_duration_ms, 0),
    COALESCE(ext_info, '{}'),
    delete_flg,
    created_at,
    created_by,
    updated_at,
    updated_by
FROM ai_skill_definition
WHERE delete_flg = 0
ON CONFLICT (tenant_id, api_key) WHERE delete_flg = 0
DO NOTHING;

-- ═══════════════════════════════════════════════════════════
-- 2. 将旧 ai_skill_definition 数据写入新结构的 ai_skill_definition
--    （如果新表是独立创建的，需要从旧表迁移内容字段）
--
--    如果新旧表是同一张表（ALTER 方式改造），则只需确保：
--    - skill_api_key 字段有值（= api_key）
--    - version 字段有值
--    此步骤通过 UPDATE 补齐即可
-- ═══════════════════════════════════════════════════════════

-- 情况 A：新 ai_skill_definition 是独立新建的表
-- 从旧表迁移版本内容数据

INSERT INTO ai_skill_definition (
    id, skill_api_key, tenant_id, version, changelog,
    when_to_use, context, agent, model, allowed_tools, arguments, prompt,
    risk_level, requires_confirmation, max_tool_calls, timeout_ms,
    output_mode, component_apikey, post_output_behavior,
    published_by, delete_flg, created_at, created_by, updated_at, updated_by
)
SELECT
    id + 100000000000000,                   -- 新 ID（避免冲突）
    api_key,                                -- skill_api_key
    tenant_id,
    COALESCE(version, '1.0.0'),
    '',                                     -- changelog（初始版本无变更说明）
    COALESCE(when_to_use, ''),
    COALESCE(context, 'inline'),
    COALESCE(agent, ''),
    COALESCE(model, ''),
    COALESCE(allowed_tools, '[]'),
    COALESCE(arguments, '[]'),
    COALESCE(prompt, ''),
    COALESCE(risk_level, 'read_only'),
    COALESCE(requires_confirmation, 0),
    COALESCE(max_tool_calls, 20),
    COALESCE(timeout_ms, 60000),
    COALESCE(output_mode, 'text'),
    COALESCE(component_apikey, ''),
    COALESCE(post_output_behavior, 'silent'),
    COALESCE(created_by, 0),
    delete_flg,
    created_at,
    created_by,
    updated_at,
    updated_by
FROM ai_skill_definition_old                -- 旧表（需先 RENAME）
WHERE delete_flg = 0
ON CONFLICT (tenant_id, skill_api_key, version) WHERE delete_flg = 0
DO NOTHING;

-- ═══════════════════════════════════════════════════════════
-- 3. ai_skill_resource 补齐 version 字段
--    将已有资源文件关联到对应 Skill 的 current_version
-- ═══════════════════════════════════════════════════════════

UPDATE ai_skill_resource r
SET version = COALESCE(
    (SELECT current_version FROM ai_skill s
     WHERE s.api_key = r.skill_api_key AND s.tenant_id = r.tenant_id AND s.delete_flg = 0),
    '1.0.0'
)
WHERE r.version = '1.0.0' AND r.delete_flg = 0;

-- ═══════════════════════════════════════════════════════════
-- 完成提示
-- ═══════════════════════════════════════════════════════════
-- 迁移完成后：
--   1. 验证 ai_skill 行数 = 旧 ai_skill_definition 的 distinct (tenant_id, api_key) 数
--   2. 验证 ai_skill_definition (新) 行数正确
--   3. 验证 ai_skill_resource.version 已更新
--   4. 旧表可 RENAME 为 ai_skill_definition_old 保留备份
