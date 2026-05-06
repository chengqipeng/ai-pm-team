# enable_tenant_intercept — 元模型定义与元数据设计

> 日期：2026-04-16
> 前置：[租户拦截器元模型驱动设计](租户拦截器元模型驱动设计.md)、[全表纳入元模型体系规划](全表纳入元模型体系规划.md)

## 一、元模型定义层（p_meta_model 表结构变更）

### 1.1 新增列

`p_meta_model` 是独立物理表（非大宽表），`enable_*` 系列字段均为固定列名。

```sql
ALTER TABLE paas_metarepo_common.p_meta_model
    ADD COLUMN IF NOT EXISTS enable_tenant_intercept SMALLINT NOT NULL DEFAULT 1;
```

### 1.2 字段在 p_meta_model 中的位置

| 字段 | 类型 | 默认值 | 说明 |
|:---|:---|:---|:---|
| ... | | | |
| `enable_log` | SMALLINT | 0 | 写操作是否记录变更日志 |
| `enable_module_control` | SMALLINT | 0 | 是否启用模块级权限控制 |
| **`enable_tenant_intercept`** | **SMALLINT** | **1** | **是否启用租户拦截器自动追加 tenant_id** |
| `delta_scope` | SMALLINT | — | Delta 作用范围 |
| ... | | | |

### 1.3 字段语义矩阵

`enable_tenant_intercept` 与 `enable_tenant` 的组合语义：

| enable_tenant | enable_tenant_intercept | 表有 tenant_id 列 | 拦截器自动追加 | 典型场景 |
|:---:|:---:|:---:|:---:|:---|
| 0 | 0 | ❌ 无 | ❌ 不追加 | 全局表（p_passport） |
| 1 | 1 | ✅ 有 | ✅ 自动追加 | 绝大多数业务表（默认） |
| 1 | 0 | ✅ 有 | ❌ 不追加 | 业务代码手动控制（p_user、操作日志） |
| 0 | 1 | ❌ 无 | — | 无意义组合（enable_tenant=0 时拦截器不涉及） |

### 1.4 MetaModel Java Entity

```java
// 已在前序步骤完成，确认字段位置
public class MetaModel extends BaseMetaCommonEntity {
    // ...
    private Integer enableModuleControl;
    private Integer enableTenantIntercept;  // ← 新增
    private Integer enableCommon;
    private Integer enableTenant;
    // ...
}
```

### 1.5 p_meta_item 字段定义（metaModel 元模型的字段注册）

`enable_tenant_intercept` 作为 `p_meta_model` 的固定列，需要在 `p_meta_item` 中注册字段定义：

```sql
INSERT INTO paas_metarepo_common.p_meta_item (
    id, metamodel_api_key, api_key, label, label_key,
    item_type, data_type, db_column, require_flg, enable_flg,
    namespace, custom_flg, delete_flg, created_at, updated_at
) VALUES (
    1800000000000000200, 'metaModel', 'enableTenantIntercept', '租户拦截开关', 'meta.model.enableTenantIntercept',
    5, 5, 'enable_tenant_intercept', 0, 1,
    'system', 0, 0, {now}, {now}
);
```

> item_type=5（SMALLINT），data_type=5（SMALLINT），db_column='enable_tenant_intercept'（固定列名，非 dbc 列）

---

## 二、元数据层（p_meta_model 数据变更）

### 2.1 已有元模型补充 enable_tenant_intercept

所有已注册的元模型，`enable_tenant_intercept` 默认值为 1（ALTER TABLE DEFAULT），无需逐条 UPDATE。

仅需对特殊表执行 UPDATE：

```sql
-- 操作日志：启动恢复需跨租户扫描
UPDATE paas_metarepo_common.p_meta_model SET enable_tenant_intercept = 0
WHERE api_key IN ('metaOperateLog', 'entityOperateLog');

-- 用户表：业务代码手动控制 tenant_id
UPDATE paas_metarepo_common.p_meta_model SET enable_tenant_intercept = 0
WHERE api_key = 'user';
```

### 2.2 新增元模型注册

以下表当前未注册为元模型，需要新增 INSERT。按 schema 分组：

#### paas_auth schema — 认证与用户

```sql
-- 以下仅注册真正的元模型，passport/passportLog/userRole 是业务数据表不注册

-- totpSecret
 0, 1, 1, 'p_totp_secret', 0, 0, 0, 1, {now}, 1, {now}),

(1900000000000000024, 'passwordPolicy', '密码策略', 'system', 1,
 0, 1, 1, 'p_tenant_password_policy', 0, 0, 0, 1, {now}, 1, {now}),

(1900000000000000025, 'authProvider', '认证提供商', 'system', 1,
 0, 1, 1, 'p_tenant_auth_provider', 0, 0, 0, 1, {now}, 1, {now}),

(1900000000000000026, 'oauthClient', 'OAuth客户端', 'system', 1,
 0, 1, 1, 'p_tenant_oauth_client', 0, 0, 0, 1, {now}, 1, {now}),

(1900000000000000027, 'loginPolicy', '登录策略', 'system', 1,
 0, 1, 1, 'p_tenant_login_policy', 0, 0, 0, 1, {now}, 1, {now}),

(1900000000000000028, 'ipWhitelist', 'IP白名单', 'system', 1,
 0, 1, 1, 'p_tenant_ip_whitelist', 0, 0, 0, 1, {now}, 1, {now}),

(1900000000000000029, 'thirdBinding', '第三方绑定', 'system', 1,
 0, 1, 1, 'p_tenant_third_binding', 0, 0, 0, 1, {now}, 1, {now}),

(1900000000000000030, 'position', '岗位', 'system', 1,
 0, 1, 1, 'p_position', 0, 0, 0, 1, {now}, 1, {now}),

(1900000000000000031, 'positionUser', '岗位用户关联', 'system', 1,
 0, 1, 1, 'p_position_user', 0, 0, 0, 1, {now}, 1, {now}),

(1900000000000000032, 'assistantRelation', '助理关系', 'system', 1,
 0, 1, 1, 'p_assistant_relation', 0, 0, 0, 1, {now}, 1, {now});
```

#### paas_entity_data schema — 业务数据基础设施

```sql
INSERT INTO paas_metarepo_common.p_meta_model (
    id, api_key, label, namespace, metamodel_type,
    enable_common, enable_tenant, enable_tenant_intercept,
    db_table, entity_dependency, visible,
    delete_flg, created_by, created_at, updated_by, updated_at
) VALUES
(1900000000000000040, 'tenantDataRoute', '分表路由', 'system', 1,
 0, 1, 1, 'p_tenant_data_route', 0, 0, 0, 1, {now}, 1, {now}),

(1900000000000000041, 'tenantDataStats', '分表统计', 'system', 1,
 0, 1, 1, 'p_tenant_data_stats', 0, 0, 0, 1, {now}, 1, {now}),

(1900000000000000042, 'dataShare', '权限共享记录', 'system', 1,
 0, 1, 1, 'p_data_share', 0, 0, 0, 1, {now}, 1, {now}),

(1900000000000000043, 'dataShareRoute', 'Share分表路由', 'system', 1,
 0, 1, 1, 'p_data_share_route', 0, 0, 0, 1, {now}, 1, {now}),

(1900000000000000044, 'publicGroupMember', '公共组成员', 'system', 1,
 0, 1, 1, 'p_public_group_member', 0, 0, 0, 1, {now}, 1, {now}),

(1900000000000000045, 'teamMember', '团队成员', 'system', 1,
 0, 1, 1, 'p_team_member', 0, 0, 0, 1, {now}, 1, {now}),

(1900000000000000046, 'territory', '销售区域', 'system', 1,
 0, 1, 1, 'p_territory', 0, 0, 0, 1, {now}, 1, {now}),

(1900000000000000047, 'territoryMember', '区域成员', 'system', 1,
 0, 1, 1, 'p_territory_member', 0, 0, 0, 1, {now}, 1, {now});
```

#### paas_metarepo schema — 运行时数据

```sql
INSERT INTO paas_metarepo_common.p_meta_model (
    id, api_key, label, namespace, metamodel_type,
    enable_common, enable_tenant, enable_tenant_intercept,
    db_table, entity_dependency, visible,
    delete_flg, created_by, created_at, updated_by, updated_at
) VALUES
(1900000000000000050, 'metaLog', '元数据变更日志', 'system', 1,
 0, 1, 1, 'p_tenant_meta_log', 0, 0, 0, 1, {now}, 1, {now}),

(1900000000000000051, 'excelTask', '导入导出任务', 'system', 1,
 0, 1, 1, 'p_excel_task', 0, 0, 0, 1, {now}, 1, {now}),

(1900000000000000052, 'fileMeta', '文件元信息', 'system', 1,
 0, 1, 1, 'p_file_meta', 0, 0, 0, 1, {now}, 1, {now});
```

---

## 三、enable_tenant_intercept 的框架消费逻辑

### 3.1 消费链路

```
p_meta_model.enable_tenant_intercept = 0
        ↓ 设计约定
Entity 类标注 @IgnoreTenantLine
        ↓ 框架自动识别
DataBaseServiceImpl.isIgnoreTenantLine() = true
        ↓ 每次 CRUD 操作
DataBaseServiceImpl.executeWithTenantControl()
        ↓ 设置 ThreadLocal
InterceptorIgnoreHelper.handle(tenantLine=true)
        ↓ MyBatis-Plus 拦截器入口
TenantLineInnerInterceptor.beforeQuery()
        → willIgnoreTenantLine() = true → return（跳过 SQL 解析）
```

### 3.2 两层配置的对应关系

| 层级 | 配置位置 | 值 | 消费方 |
|:---|:---|:---|:---|
| 元模型配置 | `p_meta_model.enable_tenant_intercept` | 0 或 1 | 开发者查阅，决定 Entity 是否加注解 |
| Java 注解 | Entity 类 `@IgnoreTenantLine` | 有或无 | `DataBaseServiceImpl` 框架自动识别 |

两层配置的关系是**设计约定**：`enable_tenant_intercept=0` 的元模型，其对应的 Entity 类**必须**标注 `@IgnoreTenantLine`。这不是运行时自动联动，而是开发规范。

### 3.3 为什么不做运行时自动联动

即"为什么不让 `DataBaseServiceImpl` 在运行时查 `p_meta_model` 来决定是否跳过拦截"：

1. **启动时序**：`DataBaseServiceImpl.initMapper()` 在 `@PostConstruct` 阶段执行，此时查 `p_meta_model` 可能触发租户拦截（鸡生蛋问题）
2. **性能**：每个 Service Bean 初始化时都查一次 `p_meta_model`，增加启动时间
3. **表名映射**：`DataBaseServiceImpl` 知道的是 Entity 类和 `@TableName`，但 `p_meta_model.db_table` 的值可能经过 `DynamicTableNameHolder` 路由后才是最终表名，映射关系不直接
4. **简单可靠**：注解是编译期确定的，不依赖任何运行时状态

### 3.4 开发规范

新增需要跳过租户拦截的表时，完整步骤：

```
1. p_meta_model 注册（或 UPDATE）：设置 enable_tenant_intercept = 0
2. Entity 类加 @IgnoreTenantLine 注解
3. 业务代码中手动控制 tenant_id（在 QueryWrapper 中显式加条件）
```

---

## 四、变更后的完整元模型清单

注册完成后，`p_meta_model` 中共 **50 个**元模型（27 已有 + 23 新增）：

### enable_tenant_intercept = 0 的元模型（3 个）

| api_key | 表 | enable_tenant | 原因 | Entity 注解 |
|:---|:---|:---:|:---|:---|
| user | p_user | 1 | 业务手动控制 tenant_id | @IgnoreTenantLine |
| metaOperateLog | p_meta_operate_log | 1 | 启动恢复跨租户扫描 | @IgnoreTenantLine（继承自 OperateLog） |
| entityOperateLog | p_entity_operate_log | 1 | 启动恢复跨租户扫描 | @IgnoreTenantLine（继承自 OperateLog） |

> 注意：p_passport、p_passport_log、p_user_role 是业务数据表，不注册为元模型。
> 它们的租户拦截行为通过 Java Entity `@IgnoreTenantLine` 注解直接声明。
> 详见 [业务数据表元模型化与大宽表分析](models/业务数据表元模型化与大宽表分析.md)

### enable_tenant_intercept = 1 的元模型（44 个）

所有其他元模型，包括 27 个已有 + 17 个新增，均为默认值 1，正常走租户拦截。

---

## 五、执行 SQL 汇总

按执行顺序：

```sql
-- Step 1: DDL — 新增列
ALTER TABLE paas_metarepo_common.p_meta_model
    ADD COLUMN IF NOT EXISTS enable_tenant_intercept SMALLINT NOT NULL DEFAULT 1;

-- Step 2: p_meta_item — 注册字段定义
INSERT INTO paas_metarepo_common.p_meta_item (
    id, metamodel_api_key, api_key, label, label_key,
    item_type, data_type, db_column, require_flg, enable_flg,
    namespace, custom_flg, delete_flg, created_at, updated_at
) VALUES (
    1800000000000000200, 'metaModel', 'enableTenantIntercept', '租户拦截开关', 'meta.model.enableTenantIntercept',
    5, 5, 'enable_tenant_intercept', 0, 1,
    'system', 0, 0, {now}, {now}
);

-- Step 3: 已有元模型 — 特殊表设置 enable_tenant_intercept=0
UPDATE paas_metarepo_common.p_meta_model SET enable_tenant_intercept = 0
WHERE api_key IN ('metaOperateLog', 'entityOperateLog', 'user');

-- Step 4: 新增元模型 — paas_auth 表（不含 passport/passportLog/userRole，它们是业务数据表）
-- （见上方 §2.2 完整 SQL）

-- Step 5: 新增元模型 — paas_entity_data 表（8 个）
-- （见上方 §2.2 完整 SQL）

-- Step 6: 新增元模型 — paas_metarepo 表（3 个）
-- （见上方 §2.2 完整 SQL）
```

> 注意：Step 4-6 的 `{now}` 替换为实际毫秒时间戳，如 `1713264000000`。
