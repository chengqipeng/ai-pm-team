-- ================================================================
-- 2026-04-28 全量迁移脚本（已执行，记录备查）
-- ================================================================

-- ============================================================
-- 第一部分：元数据字段类型修正
-- 详见 字段类型修正-执行SQL.md（动作一~五共 52 个字段）
-- 已于 2026-04-28 通过 execute_fix.py 执行并 COMMIT
-- ============================================================

-- ============================================================
-- 第二部分：depart_api_key 回填 + depart_id 删除
-- ============================================================

-- 2a. 回填 depart_api_key（12 张有数据的分片表，共 119 条）
-- 无法映射到部门表的 depart_id 设为 'root'
-- 以下 12 张表有需要回填的数据（其余 1988 张表无数据或已有值）
-- p_tenant_data_0(3), p_tenant_data_3(8), p_tenant_data_19(15),
-- p_tenant_data_51(15), p_tenant_data_53(9), p_tenant_data_83(24),
-- p_tenant_data_88(6), p_tenant_data_90(1), p_tenant_data_95(18),
-- p_tenant_data_96(4), p_tenant_data_126(6), p_tenant_data_132(10)

-- 回填 SQL 模板（对每张表执行）：
-- UPDATE paas_entity_data.p_tenant_data_{N} t
-- SET depart_api_key = COALESCE(
--     (SELECT d.api_key FROM paas_metarepo.p_tenant_department d
--      WHERE d.id = t.depart_id AND d.delete_flg = 0 LIMIT 1),
--     'root'
-- )
-- WHERE t.depart_id IS NOT NULL
--   AND (t.depart_api_key IS NULL OR t.depart_api_key = '')
--   AND t.delete_flg = 0;

-- 2b. 删除 depart_id 列（2000 张分片表）
-- 通过 Python 脚本分批执行，每批 100 张表
-- DO $$ BEGIN
--     FOR i IN 0..1999 LOOP
--         EXECUTE format('ALTER TABLE paas_entity_data.p_tenant_data_%s DROP COLUMN IF EXISTS depart_id', i);
--     END LOOP;
-- END $$;

-- ============================================================
-- 第三部分：部门数据同步（Common → Tenant）
-- ============================================================

-- 28 个 Common 级部门同步到 p_tenant_department（tenant_id=292193）
-- 已有 7 个基础部门（root, sales, cs, rd, rd_frontend, rd_backend, rd_qa）
-- 新增 28 个（含重复的 7 个会跳过，实际插入 21 个）

INSERT INTO paas_metarepo.p_tenant_department
    (id, tenant_id, api_key, label, namespace, delete_flg,
     created_at, created_by, updated_at, updated_by,
     metamodel_api_key, dbc_varchar1, dbc_varchar5, dbc_smallint1)
SELECT
    2100 + ROW_NUMBER() OVER (ORDER BY api_key),
    292193, cm.api_key, cm.dbc_varchar1, 'system', 0,
    EXTRACT(EPOCH FROM NOW())::BIGINT * 1000, 1,
    EXTRACT(EPOCH FROM NOW())::BIGINT * 1000, 1,
    'department', cm.dbc_varchar1, cm.dbc_varchar5, 1
FROM paas_metarepo_common.p_common_metadata cm
WHERE cm.metamodel_api_key = 'department' AND cm.delete_flg = 0
  AND cm.api_key NOT IN (
    SELECT api_key FROM paas_metarepo.p_tenant_department
    WHERE delete_flg = 0 AND tenant_id = 292193
  );

-- ============================================================
-- 第四部分：验证查询
-- ============================================================

-- 验证 1：depart_id 列已删除
SELECT column_name FROM information_schema.columns
WHERE table_schema = 'paas_entity_data' AND table_name = 'p_tenant_data_0'
  AND column_name = 'depart_id';
-- 期望：0 行

-- 验证 2：所有活跃数据的 depart_api_key 非空
-- SELECT COUNT(*) FROM paas_entity_data.p_tenant_data_{N}
-- WHERE delete_flg = 0 AND (depart_api_key IS NULL OR depart_api_key = '');
-- 期望：0

-- 验证 3：部门数据完整
SELECT COUNT(*) FROM paas_metarepo.p_tenant_department
WHERE delete_flg = 0 AND tenant_id = 292193;
-- 期望：35（7 基础 + 28 Common 级）

-- 验证 4：元数据字段类型无不匹配
-- 详见 字段类型修正-执行SQL.md 的验证查询
