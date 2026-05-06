# 操作日志 / Passport / UserRole 完整元模型化分析

> 日期：2026-04-16
> 状态：**已修正** — 经深度分析，这 5 张表是业务数据表，不应注册为元模型。
> 详见 [业务数据表元模型化与大宽表分析](业务数据表元模型化与大宽表分析.md)
>
> 本文档保留作为分析过程记录。最终结论：
> - metaOperateLog / entityOperateLog：保留元模型注册（已有），因为它们的 enable_tenant_intercept=0 需要配置载体
> - passport / passportLog / userRole：**不注册为元模型**，通过 @IgnoreTenantLine 注解声明
> 参考模式：[role-department-metadata.md](role-department-metadata.md)

## 一、分析目标

将以下 5 张表按照 role/department 的模式完整元模型化：

| 表 | 当前状态 | 目标 |
|:---|:---|:---|
| p_meta_operate_log | 独立表，固定列，Java Entity 直接映射 | 独立元模型，字段定义注册到 p_meta_item |
| p_entity_operate_log | 同上 | 同上（与 metaOperateLog 共享字段定义） |
| p_passport | 独立表，固定列 | 独立元模型 |
| p_passport_log | 独立表，固定列 | 独立元模型 |
| p_user_role | 独立表，固定列 | 独立元模型 |

## 二、元模型化的核心问题

### 2.1 这些表能否用大宽表？

**不能，也不需要。** 原因：

1. **p_meta_operate_log / p_entity_operate_log**：在 `paas_metarepo_common` 和 `paas_entity_data` 两个不同 schema 中，不能合并到一张大宽表
2. **p_passport**：全局表，无 tenant_id，不能放入 Tenant 级大宽表
3. **p_passport_log**：同上
4. **p_user_role**：关联表，字段极少（3 个业务字段），用大宽表浪费

这些表跟 role/department 一样，使用**独立表结构 + 元模型注册**的模式。

### 2.2 元模型化意味着什么？

完整元模型化 = 以下 4 层全部完成：

| 层级 | 内容 | 作用 |
|:---|:---|:---|
| p_meta_model | 元模型注册 | 声明"有这种类型的数据" |
| p_meta_item | 字段定义 | 声明"这种数据有哪些字段，每个字段的类型和存储列" |
| p_meta_link | 关联关系（可选） | 声明"这种数据与其他数据的父子/引用关系" |
| Java Entity + DAO | 代码实现 | 实际的 CRUD 逻辑 |

### 2.3 这些表的字段是固定列还是 dbc 列？

**全部是固定列。** 这些表不使用 dbc_xxxN 扩展列，因为：
- 字段语义固定，不需要租户自定义扩展
- 表结构已经确定，不会动态增减字段

在 p_meta_item 中注册时，`db_column` 直接填固定列名（如 `process_id`、`phone`），不填 `dbc_xxxN`。
这与 role/department 不同——role/department 使用 dbc 列是因为它们存储在大宽表结构的快捷表中。

---

## 三、逐表分析

### 3.1 metaOperateLog — 元数据操作日志

#### 业务分析

| 维度 | 说明 |
|:---|:---|
| 用途 | 元数据批量操作的回滚日志，记录每条操作的前置快照 |
| 生命周期 | 批量操作开始时写入，commit 时删除，异常时用于回滚 |
| 查询场景 | 启动恢复（跨租户扫描）、按 processId 查询、按 rollback_status 过滤 |
| 租户隔离 | 有 tenant_id 列，但启动恢复需跨租户查询 → enable_tenant_intercept=0 |
| 扩展需求 | ❌ 无。字段固定，不需要租户自定义 |

#### 元模型注册（p_meta_model）

| 属性 | 值 |
|:---|:---|
| api_key | metaOperateLog |
| label | 元数据操作日志 |
| namespace | system |
| enable_common | 0 |
| enable_tenant | 1 |
| enable_tenant_intercept | **0** |
| entity_dependency | 0 |
| db_table | p_meta_operate_log |
| visible | 0 |

#### 字段定义（p_meta_item）— 6 个业务字段

> BaseEntity 提供的 6 个基础字段（id, delete_flg, created_at, created_by, updated_at, updated_by）不在 item 中定义。
> tenant_id 作为系统字段也不在 item 中定义。

| api_key | db_column | label | itemType | dataType | 说明 |
|:---|:---|:---|:---|:---|:---|
| processId | process_id | 事务ID | 5(NUMBER) | 3(BIGINT) | 批量操作事务标识 |
| targetType | target_type | 业务类型 | 1(TEXT) | 1(VARCHAR) | metamodelApiKey |
| targetKey | target_key | 业务标识 | 1(TEXT) | 1(VARCHAR) | metadataApiKey |
| targetId | target_id | 数据ID | 5(NUMBER) | 3(BIGINT) | 元数据场景为 null |
| dmlType | dml_type | 操作类型 | 5(NUMBER) | 6(SMALLINT) | 1=create, 2=update, 3=delete |
| beforeValue | before_value | 操作前快照 | 2(TEXTAREA) | 2(TEXT) | JSON 格式 |
| rollbackStatus | rollback_status | 回滚状态 | 5(NUMBER) | 6(SMALLINT) | 0=pending, 1=done |

> 注意：p_meta_operate_log 当前 DDL 中列名是 `metamodel_api_key` / `metadata_api_key`，
> 操作日志下沉设计中已规划统一为 `target_type` / `target_key`。
> 元模型字段定义按统一后的列名注册。

### 3.2 entityOperateLog — 业务数据操作日志

#### 业务分析

与 metaOperateLog 完全相同的字段结构，区别仅在于：
- 存储在 `paas_entity_data` schema
- `targetType` 存储 entityApiKey（而非 metamodelApiKey）
- `targetId` 存储 dataId（而非 null）
- `targetKey` 为 null（业务数据用 id 标识，不用 apiKey）

#### 元模型注册（p_meta_model）

| 属性 | 值 |
|:---|:---|
| api_key | entityOperateLog |
| label | 业务数据操作日志 |
| namespace | system |
| enable_common | 0 |
| enable_tenant | 1 |
| enable_tenant_intercept | **0** |
| entity_dependency | 0 |
| db_table | p_entity_operate_log |
| visible | 0 |

#### 字段定义（p_meta_item）

与 metaOperateLog 完全相同的 7 个字段。`metamodel_api_key` 分别为 `metaOperateLog` 和 `entityOperateLog`。

### 3.3 passport — 全局身份凭证

#### 业务分析

| 维度 | 说明 |
|:---|:---|
| 用途 | 全局登录凭证，一个手机号对应一个 Passport，可关联多个租户的 User |
| 生命周期 | 首次注册时创建，密码修改时更新 |
| 查询场景 | 按手机号查询（登录）、按 id 查询 |
| 租户隔离 | ❌ 无 tenant_id 列，全局表 → enable_tenant=0, enable_tenant_intercept=0 |
| 扩展需求 | ❌ 无。认证凭证字段固定 |

#### 元模型注册（p_meta_model）

| 属性 | 值 |
|:---|:---|
| api_key | passport |
| label | 全局身份凭证 |
| namespace | system |
| enable_common | 0 |
| enable_tenant | 0 |
| enable_tenant_intercept | **0** |
| entity_dependency | 0 |
| db_table | p_passport |
| visible | 0 |

#### 字段定义（p_meta_item）— 4 个业务字段

| api_key | db_column | label | itemType | dataType | 说明 |
|:---|:---|:---|:---|:---|:---|
| phone | phone | 手机号 | 1(TEXT) | 1(VARCHAR) | 全局唯一登录凭证 |
| password | password | 密码 | 1(TEXT) | 1(VARCHAR) | BCrypt 加密 |
| passwordSalt | password_salt | 密码盐值 | 1(TEXT) | 1(VARCHAR) | 可选 |
| valid | valid | 有效状态 | 31(BOOLEAN) | 6(SMALLINT) | 0=无效, 1=有效 |
| pwdFlg | pwd_flg | 密码标记 | 31(BOOLEAN) | 6(SMALLINT) | 0=自定义, 1=系统生成 |

### 3.4 passportLog — 密码变更日志

#### 业务分析

| 维度 | 说明 |
|:---|:---|
| 用途 | 记录密码变更历史，用于"最近 N 次密码不能重复"策略 |
| 生命周期 | 每次密码变更时追加一条 |
| 查询场景 | 按 passportId 查询历史密码 |
| 租户隔离 | ❌ 无 tenant_id 列，跟随 Passport 全局 → enable_tenant=0, enable_tenant_intercept=0 |
| 扩展需求 | ❌ 无 |

#### 元模型注册（p_meta_model）

| 属性 | 值 |
|:---|:---|
| api_key | passportLog |
| label | 密码变更日志 |
| namespace | system |
| enable_common | 0 |
| enable_tenant | 0 |
| enable_tenant_intercept | **0** |
| entity_dependency | 0 |
| db_table | p_passport_log |
| visible | 0 |

#### 字段定义（p_meta_item）— 3 个业务字段

| api_key | db_column | label | itemType | dataType | 说明 |
|:---|:---|:---|:---|:---|:---|
| passportId | passport_id | 凭证ID | 10(RELATION_SHIP) | 3(BIGINT) | 引用 p_passport.id |
| password | password | 历史密码 | 1(TEXT) | 1(VARCHAR) | BCrypt 加密 |
| changeType | change_type | 变更类型 | 5(NUMBER) | 6(SMALLINT) | 0=修改, 1=重置, 2=管理员重置 |

#### 关联关系（p_meta_link）

| api_key | parent → child | cascadeDelete |
|:---|:---|:---|
| passport_passportLog | passport → passportLog | 1(级联删除) |

### 3.5 userRole — 用户角色关联

#### 业务分析

| 维度 | 说明 |
|:---|:---|
| 用途 | 用户与角色的多对多关联表 |
| 生命周期 | 分配角色时创建，移除角色时删除 |
| 查询场景 | 按 tenantId+userId 查用户角色、按 tenantId+roleApiKey 查角色用户 |
| 租户隔离 | ✅ 有 tenant_id 列，但业务代码手动控制 → enable_tenant_intercept=0 |
| 扩展需求 | ❌ 无。纯关联表，字段固定 |

#### 元模型注册（p_meta_model）

| 属性 | 值 |
|:---|:---|
| api_key | userRole |
| label | 用户角色关联 |
| namespace | system |
| enable_common | 0 |
| enable_tenant | 1 |
| enable_tenant_intercept | **0** |
| entity_dependency | 0 |
| db_table | p_user_role |
| visible | 0 |

#### 字段定义（p_meta_item）— 2 个业务字段

> tenant_id 作为系统字段不在 item 中定义。

| api_key | db_column | label | itemType | dataType | 说明 |
|:---|:---|:---|:---|:---|:---|
| userId | user_id | 用户ID | 10(RELATION_SHIP) | 3(BIGINT) | 引用 p_user.id |
| roleApiKey | role_api_key | 角色标识 | 10(RELATION_SHIP) | 1(VARCHAR) | 引用 p_tenant_role.api_key |

#### 关联关系（p_meta_link）

| api_key | parent → child | cascadeDelete |
|:---|:---|:---|
| user_userRole | user → userRole | 1(级联删除) |
| role_userRole | role → userRole | 0(不级联，删角色前需先移除用户) |

---

## 四、p_meta_item 注册 SQL

```sql
-- ==================== metaOperateLog（7 个字段） ====================
INSERT INTO paas_metarepo_common.p_meta_item (
    id, metamodel_api_key, api_key, label, label_key,
    item_type, data_type, db_column, require_flg, enable_flg,
    namespace, custom_flg, delete_flg, created_at, updated_at
) VALUES
(1800000000000000301, 'metaOperateLog', 'processId', '事务ID', 'operateLog.processId', 5, 3, 'process_id', 1, 1, 'system', 0, 0, {now}, {now}),
(1800000000000000302, 'metaOperateLog', 'targetType', '业务类型', 'operateLog.targetType', 1, 1, 'target_type', 1, 1, 'system', 0, 0, {now}, {now}),
(1800000000000000303, 'metaOperateLog', 'targetKey', '业务标识', 'operateLog.targetKey', 1, 1, 'target_key', 0, 1, 'system', 0, 0, {now}, {now}),
(1800000000000000304, 'metaOperateLog', 'targetId', '数据ID', 'operateLog.targetId', 5, 3, 'target_id', 0, 1, 'system', 0, 0, {now}, {now}),
(1800000000000000305, 'metaOperateLog', 'dmlType', '操作类型', 'operateLog.dmlType', 5, 6, 'dml_type', 1, 1, 'system', 0, 0, {now}, {now}),
(1800000000000000306, 'metaOperateLog', 'beforeValue', '操作前快照', 'operateLog.beforeValue', 2, 2, 'before_value', 0, 1, 'system', 0, 0, {now}, {now}),
(1800000000000000307, 'metaOperateLog', 'rollbackStatus', '回滚状态', 'operateLog.rollbackStatus', 5, 6, 'rollback_status', 1, 1, 'system', 0, 0, {now}, {now});

-- ==================== entityOperateLog（7 个字段，与 metaOperateLog 相同） ====================
INSERT INTO paas_metarepo_common.p_meta_item (
    id, metamodel_api_key, api_key, label, label_key,
    item_type, data_type, db_column, require_flg, enable_flg,
    namespace, custom_flg, delete_flg, created_at, updated_at
) VALUES
(1800000000000000311, 'entityOperateLog', 'processId', '事务ID', 'operateLog.processId', 5, 3, 'process_id', 1, 1, 'system', 0, 0, {now}, {now}),
(1800000000000000312, 'entityOperateLog', 'targetType', '业务类型', 'operateLog.targetType', 1, 1, 'target_type', 1, 1, 'system', 0, 0, {now}, {now}),
(1800000000000000313, 'entityOperateLog', 'targetKey', '业务标识', 'operateLog.targetKey', 1, 1, 'target_key', 0, 1, 'system', 0, 0, {now}, {now}),
(1800000000000000314, 'entityOperateLog', 'targetId', '数据ID', 'operateLog.targetId', 5, 3, 'target_id', 0, 1, 'system', 0, 0, {now}, {now}),
(1800000000000000315, 'entityOperateLog', 'dmlType', '操作类型', 'operateLog.dmlType', 5, 6, 'dml_type', 1, 1, 'system', 0, 0, {now}, {now}),
(1800000000000000316, 'entityOperateLog', 'beforeValue', '操作前快照', 'operateLog.beforeValue', 2, 2, 'before_value', 0, 1, 'system', 0, 0, {now}, {now}),
(1800000000000000317, 'entityOperateLog', 'rollbackStatus', '回滚状态', 'operateLog.rollbackStatus', 5, 6, 'rollback_status', 1, 1, 'system', 0, 0, {now}, {now});

-- ==================== passport（5 个字段） ====================
INSERT INTO paas_metarepo_common.p_meta_item (
    id, metamodel_api_key, api_key, label, label_key,
    item_type, data_type, db_column, require_flg, enable_flg,
    namespace, custom_flg, delete_flg, created_at, updated_at
) VALUES
(1800000000000000321, 'passport', 'phone', '手机号', 'passport.phone', 1, 1, 'phone', 1, 1, 'system', 0, 0, {now}, {now}),
(1800000000000000322, 'passport', 'password', '密码', 'passport.password', 1, 1, 'password', 1, 1, 'system', 0, 0, {now}, {now}),
(1800000000000000323, 'passport', 'passwordSalt', '密码盐值', 'passport.passwordSalt', 1, 1, 'password_salt', 0, 1, 'system', 0, 0, {now}, {now}),
(1800000000000000324, 'passport', 'valid', '有效状态', 'passport.valid', 31, 6, 'valid', 1, 1, 'system', 0, 0, {now}, {now}),
(1800000000000000325, 'passport', 'pwdFlg', '密码标记', 'passport.pwdFlg', 31, 6, 'pwd_flg', 0, 1, 'system', 0, 0, {now}, {now});

-- ==================== passportLog（3 个字段） ====================
INSERT INTO paas_metarepo_common.p_meta_item (
    id, metamodel_api_key, api_key, label, label_key,
    item_type, data_type, db_column, require_flg, enable_flg,
    namespace, custom_flg, delete_flg, created_at, updated_at
) VALUES
(1800000000000000331, 'passportLog', 'passportId', '凭证ID', 'passportLog.passportId', 10, 3, 'passport_id', 1, 1, 'system', 0, 0, {now}, {now}),
(1800000000000000332, 'passportLog', 'password', '历史密码', 'passportLog.password', 1, 1, 'password', 1, 1, 'system', 0, 0, {now}, {now}),
(1800000000000000333, 'passportLog', 'changeType', '变更类型', 'passportLog.changeType', 5, 6, 'change_type', 1, 1, 'system', 0, 0, {now}, {now});

-- ==================== userRole（2 个字段） ====================
INSERT INTO paas_metarepo_common.p_meta_item (
    id, metamodel_api_key, api_key, label, label_key,
    item_type, data_type, db_column, require_flg, enable_flg,
    namespace, custom_flg, delete_flg, created_at, updated_at
) VALUES
(1800000000000000341, 'userRole', 'userId', '用户ID', 'userRole.userId', 10, 3, 'user_id', 1, 1, 'system', 0, 0, {now}, {now}),
(1800000000000000342, 'userRole', 'roleApiKey', '角色标识', 'userRole.roleApiKey', 10, 1, 'role_api_key', 1, 1, 'system', 0, 0, {now}, {now});
```

## 五、p_meta_link 注册 SQL

```sql
INSERT INTO paas_metarepo_common.p_meta_link (
    id, api_key, label, namespace,
    link_type, parent_metamodel_api_key, child_metamodel_api_key,
    refer_item_api_key, cascade_delete,
    delete_flg, created_at, updated_at
) VALUES
-- passport → passportLog（级联删除）
(1700000000000000301, 'passport_passportLog', 'Passport密码日志', 'system',
 2, 'passport', 'passportLog', 'passportId', 1, 0, {now}, {now}),

-- user → userRole（级联删除：删用户时清理角色关联）
(1700000000000000302, 'user_userRole', '用户角色关联', 'system',
 2, 'user', 'userRole', 'userId', 1, 0, {now}, {now}),

-- role → userRole（不级联：删角色前需先移除用户）
(1700000000000000303, 'role_userRole', '角色用户关联', 'system',
 2, 'role', 'userRole', 'roleApiKey', 0, 0, {now}, {now});
```

## 六、元模型化可行性结论

| 表 | 能否元模型化 | 是否需要大宽表 | 字段数 | 关联关系 |
|:---|:---|:---|:---|:---|
| p_meta_operate_log | ✅ 可以 | ❌ 独立表 | 7 | 无 |
| p_entity_operate_log | ✅ 可以 | ❌ 独立表 | 7 | 无 |
| p_passport | ✅ 可以 | ❌ 独立表 | 5 | passport → passportLog |
| p_passport_log | ✅ 可以 | ❌ 独立表 | 3 | 子表（passport 的子） |
| p_user_role | ✅ 可以 | ❌ 独立表 | 2 | user → userRole, role → userRole |

所有 5 张表都可以完整元模型化。字段全部是固定列（非 dbc 列），不需要大宽表结构。
Java Entity 和 DAO 代码不需要改动——元模型化是元数据层面的注册，不影响运行时的 CRUD 逻辑。
