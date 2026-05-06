-- ============================================================================
-- menu 元模型注册 + 字段定义 + Common 级种子数据
-- ============================================================================

-- 1. 注册元模型
-- INSERT INTO p_meta_model (api_key, label, namespace, enable_common, enable_tenant,
--   enable_tenant_intercept, db_table, delete_flg)
-- VALUES ('menu', '菜单', 'system', 1, 1, 1, 'p_tenant_menu', 0);

-- 2. 注册 p_meta_item 扩展字段（11 个）
-- 固定列（namespace, apiKey, label, labelKey, description, customFlg, deleteFlg,
--   createdBy, createdAt, updatedBy, updatedAt）由 CommonMetadataConverter 自动映射，无需注册。

-- | api_key            | db_column      | label        | item_type |
-- |--------------------|----------------|--------------|-----------|
-- | menuIcon           | dbc_varchar1   | 图标          | 1 (TEXT)  |
-- | menuGroup          | dbc_varchar2   | 分组标题       | 1 (TEXT)  |
-- | menuGroupKey       | dbc_varchar3   | 分组多语言Key  | 1 (TEXT)  |
-- | pageApiKey         | dbc_varchar4   | 关联页面       | 1 (TEXT)  |
-- | parentMenuApiKey   | dbc_varchar5   | 上级菜单       | 1 (TEXT)  |
-- | permissionApiKey   | dbc_varchar6   | 权限标识       | 1 (TEXT)  |
-- | menuOrder          | dbc_int1       | 菜单排序       | 5 (NUMBER)|
-- | groupOrder         | dbc_int2       | 分组排序       | 5 (NUMBER)|
-- | menuType           | dbc_smallint1  | 菜单类型       | 4 (SELECT)|
-- | visibleFlg         | dbc_smallint2  | 是否可见       | 31(BOOL)  |
-- | enableFlg          | dbc_smallint3  | 是否启用       | 31(BOOL)  |


-- 3. Common 级种子数据（11 个菜单项）
-- 以下为 PostgreSQL 语法，实际执行由 init_local_dev.py 处理

-- ┌─────────────────────────────────────────────────────────────┐
-- │ 组织与权限 (groupOrder=1)                                    │
-- ├─────────────────────────────────────────────────────────────┤
-- │ menuUsers       │ 用户管理     │ Users       │ pageUserList │
-- │ menuDepartments │ 部门树管理   │ Network     │ pageDeptTree │
-- │ menuRoles       │ 角色与授权   │ ShieldCheck │ pageRoleList │
-- │ menuRoleAuth    │ 角色权限配置 │ Lock        │ pageRoleAuth │
-- ├─────────────────────────────────────────────────────────────┤
-- │ 数据安全 (groupOrder=2)                                      │
-- ├─────────────────────────────────────────────────────────────┤
-- │ menuSharing     │ 共享规则     │ Share2      │ pageSharingRules │
-- │ menuPublicGroups│ 共享组管理   │ UsersRound  │ pagePublicGroups │
-- │ menuTerritory   │ 区域数据权限 │ Map         │ pageTerritory    │
-- ├─────────────────────────────────────────────────────────────┤
-- │ 业务实体 (groupOrder=3)                                      │
-- ├─────────────────────────────────────────────────────────────┤
-- │ menuEntities    │ 实体管理     │ Database    │ pageEntityList   │
-- ├─────────────────────────────────────────────────────────────┤
-- │ 元模型管理 (groupOrder=4)                                    │
-- ├─────────────────────────────────────────────────────────────┤
-- │ menuMetamodel   │ 元模型定义   │ Boxes       │ pageMetamodel    │
-- ├─────────────────────────────────────────────────────────────┤
-- │ 系统设置 (groupOrder=5)                                      │
-- ├─────────────────────────────────────────────────────────────┤
-- │ menuSettingsLang│ 语言管理     │ Globe       │ pageSettingsLang │
-- │ menuSettingsTz  │ 时区管理     │ Clock       │ pageSettingsTz   │
-- └─────────────────────────────────────────────────────────────┘
