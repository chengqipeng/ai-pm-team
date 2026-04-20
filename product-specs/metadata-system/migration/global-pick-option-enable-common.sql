-- globalPickOption 元模型修正：enable_common=0 → enable_common=1
-- 使 globalPickOption 走 Common/Tenant 合并读取标准链路

-- 1. 修正 p_meta_model 注册
UPDATE p_meta_model
SET enable_common = 1
WHERE api_key = 'globalPickOption';

-- 2. 补充 p_meta_item 字段定义（globalPickOption 扩展字段的 dbc 列映射）
-- 固定列（entityApiKey, namespace, apiKey, label, labelKey, description, descriptionKey, customFlg, deleteFlg, createdBy, createdAt, updatedBy, updatedAt）
-- 由 CommonMetadataConverter Step 1 自动映射，无需在 p_meta_item 中注册。
-- 以下仅注册需要 dbc 列映射的扩展字段。

INSERT INTO p_meta_item (api_key, metamodel_api_key, label, label_key, db_column, item_type, item_order, namespace, custom_flg, delete_flg, created_at, created_by, updated_at, updated_by)
VALUES
    ('optionOrder', 'globalPickOption', '排序序号', 'meta.globalPickOption.optionOrder', 'dbc_int1', 2, 1, 'system', 0, 0, UNIX_TIMESTAMP()*1000, 0, UNIX_TIMESTAMP()*1000, 0),
    ('defaultFlg', 'globalPickOption', '是否默认', 'meta.globalPickOption.defaultFlg', 'dbc_smallint1', 9, 2, 'system', 0, 0, UNIX_TIMESTAMP()*1000, 0, UNIX_TIMESTAMP()*1000, 0),
    ('enableFlg', 'globalPickOption', '是否启用', 'meta.globalPickOption.enableFlg', 'dbc_smallint2', 9, 3, 'system', 0, 0, UNIX_TIMESTAMP()*1000, 0, UNIX_TIMESTAMP()*1000, 0)
ON DUPLICATE KEY UPDATE
    db_column = VALUES(db_column),
    updated_at = VALUES(updated_at);

-- 3. 将 58 条系统出厂数据从 p_tenant_global_pick_option (tenant_id=-101 或种子数据)
--    迁移到 p_common_metadata（Common 级大宽表）
-- 注意：具体迁移脚本需根据实际数据情况编写，以下为模板
-- INSERT INTO p_common_metadata (metamodel_api_key, api_key, entity_api_key, label, label_key, namespace, ...)
-- SELECT 'globalPickOption', api_key, entity_api_key, label, label_key, namespace, ...
-- FROM p_tenant_global_pick_option
-- WHERE tenant_id = <seed_tenant_id> AND delete_flg = 0;
