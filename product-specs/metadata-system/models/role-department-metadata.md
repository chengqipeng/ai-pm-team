# role（角色）与 department（部门）— 元模型定义与数据迁移方案

> 状态：✅ 全部完成
> 关联文档：[department-entity-analysis.md](department-entity-analysis.md)、[user-entity.md](user-entity.md)

## 一、背景与目标

角色（role）和部门（department）是系统级基础元数据，被所有核心业务实体引用：
- department：数据权限基础维度，所有实体的 `departId` 引用
- role：权限控制基础，用户通过角色获得对象级 CRUD 权限和 `viewAll/modifyAll` 标记

目标：将两者作为独立元模型注册到 `p_meta_model`，数据存储在 `paas_metarepo` 的 Tenant 级快捷表中。

## 二、当前存储架构

### 2.1 数据存储

| 数据 | 存储位置 | 说明 |
|:---|:---|:---|
| role 元模型注册 | `paas_metarepo_common.p_meta_model`（api_key='role'） | db_table=p_tenant_role |
| role 字段定义 | `paas_metarepo_common.p_meta_item`（metamodel_api_key='role'） | 6 个字段 |
| role 元数据 | `paas_metarepo.p_tenant_role` | 7 条（2 租户） |
| department 元模型注册 | `paas_metarepo_common.p_meta_model`（api_key='department'） | enable_common=1, db_table=p_tenant_department |
| department 字段定义 | `paas_metarepo_common.p_meta_item`（metamodel_api_key='department'） | 10 个字段 |
| department Common 数据 | `paas_metarepo_common.p_common_metadata`（metamodel_api_key='department'） | 1 条：companyRoot（全公司根部门） |
| department Tenant 数据 | `paas_metarepo.p_tenant_department` | 10 条（2 租户） |
| 用户-角色关联 | `paas_auth.p_user_role` | 业务数据表，保留不动 |

### 2.2 已清理的老存储

| 老存储 | 状态 | 说明 |
|:---|:---|:---|
| `paas_auth.p_role` | ✅ 已删除 | 最早的老表 |
| `paas_auth.p_department` | ✅ 已删除 | 最早的老表 |
| `p_common_metadata`（entity 注册） | ✅ 已软删除 | 曾错误注册为 entity 类型 |
| `p_common_metadata`（item 定义） | ✅ 已软删除 | 44 条老 item 定义 |
| `paas_entity_data.p_tenant_data_1`（role） | ✅ 数据已迁移 | 迁移到 p_tenant_role |
| `paas_entity_data.p_tenant_data_132`（department） | ✅ 数据已迁移 | 迁移到 p_tenant_department |
| `Role.java` / `RoleServiceImpl.java` / `Department.java` | ✅ 已删除 | 指向老表的废弃代码 |
| `paas_auth.p_user_role` | 🔒 保留 | 用户-角色多对多关联，业务数据表 |

### 2.3 p_user_role 表结构

```sql
CREATE TABLE paas_auth.p_user_role (
    id              BIGINT       PRIMARY KEY,
    tenant_id       BIGINT       NOT NULL,
    user_id         BIGINT       NOT NULL,   -- 引用 p_user.id (paas_auth)
    role_api_key    VARCHAR(255) NOT NULL,   -- 引用 p_tenant_role.api_key (paas_metarepo)
    delete_flg      SMALLINT     NOT NULL DEFAULT 0,
    created_at      BIGINT,
    created_by      BIGINT,
    updated_at      BIGINT,
    updated_by      BIGINT
);
-- 索引
CREATE INDEX idx_p_user_role_tid ON paas_auth.p_user_role (tenant_id);
CREATE INDEX idx_p_user_role_uid ON paas_auth.p_user_role (tenant_id, user_id);
CREATE INDEX idx_p_user_role_rak ON paas_auth.p_user_role (tenant_id, role_api_key);
```

### 2.4 被引用情况

| 引用方 | 引用 role 的字段 | 引用 department 的字段 | 用途 |
|:---|:---|:---|:---|
| user | p_user_role.role_id | departId (dbc_bigint1) | 用户所属角色/部门 |
| account | — | dimDepart | 客户所属部门 |
| contact | — | dimDepart | 联系人所属部门 |
| opportunity | — | dimDepart | 商机所属部门 |
| lead | — | dimDepart | 线索所属部门 |
| 数据权限 | viewAll/modifyAll | depart_id IN (...) | 权限过滤 |

## 三、元模型定义

### 3.1 role — 独立元模型注册

> ⚠️ 以下为当前生效的独立元模型注册。老的 entity 注册（metamodel_api_key='entity', dbTable=p_tenant_data_1）已于 2026-04-16 软删除。

| 属性 | 值 | 说明 |
|:---|:---|:---|
| api_key | role | 全局唯一标识 |
| label | 角色 | 中文显示名 |
| label_key | XdMDObj.role | 国际化 Key |
| namespace | system | 系统级元模型 |
| enable_common | 0 | 无 Common 级数据 |
| enable_tenant | 1 | 仅 Tenant 级 |
| entity_dependency | 0 | 不依赖 entity，顶级独立元模型 |
| db_table | p_tenant_role | Tenant 级快捷表 |

### 3.2 role — item 定义（6 个业务字段）

> item apiKey 在系统中全局唯一（跨 entity），使用 `role` 前缀避免冲突。
> name 字段由 `p_tenant_data` 固定列提供，不在 item 中定义。
>
> **关联字段存储 api_key 说明**：`roleParentApiKey` 的 `itemType=10(RELATION_SHIP)` 表示这是关联字段（前端渲染为关联选择器），
> 但 `dataType` 覆盖为 `1(VARCHAR)`、`db_column` 使用 `dbc_varchar5`，因为存储的是目标记录的 `api_key`（字符串）而非 `id`（BIGINT）。
> 这符合平台"禁止 ID 关联，统一用 api_key"的规范。`itemType` 决定 UI 语义，`dataType` 决定存储类型，两者可以独立配置。
>
> **编码体系说明**：下表 itemType 列使用 **ItemTypeEnum 新编码**（元数据实例层）。
> 在 `p_meta_item.item_type` 中注册时需转换为**老编码**（如 RELATION_SHIP: 新编码 10 → 老编码 5）。
> 详见 [元模型与元数据-ItemType设计差异分析](元模型与元数据-ItemType设计差异分析.md)。

| api_key | db_column | label | itemType | dataType | 说明 |
|:---|:---|:---|:---|:---|:---|
| roleCode | dbc_varchar1 | 角色编码 | 1(TEXT) | 1(VARCHAR) | 唯一标识，如 systemAdmin |
| roleParentApiKey | dbc_varchar5 | 上级角色 | 10(RELATION_SHIP) | 1(VARCHAR) | 自关联 api_key，覆盖默认 BIGINT |
| roleLevel | dbc_bigint2 | 层级深度 | 5(NUMBER) | 3(BIGINT) | 0=根节点 |
| roleSortOrder | dbc_bigint3 | 排序号 | 5(NUMBER) | 3(BIGINT) | 同级排序 |
| roleStatus | dbc_smallint1 | 状态 | 31(BOOLEAN) | 6(SMALLINT) | 0=禁用, 1=启用 |
| roleDescriptionKey | dbc_varchar2 | 描述Key | 1(TEXT) | 1(VARCHAR) | 国际化 |

### 3.3 role — entityLink 定义（2 条）

| api_key | label | parent → child | cascadeDelete |
|:---|:---|:---|:---|
| role_role_parentId | 上级角色 | role → role | 2(阻止删除) |
| role_user_roleId | 用户角色 | role → user | 0(不级联) |

### 3.4 department — 独立元模型注册

> ⚠️ 以下为当前生效的独立元模型注册。老的 entity 注册（metamodel_api_key='entity', dbTable=p_tenant_data_132）已于 2026-04-16 软删除。

| 属性 | 值 | 说明 |
|:---|:---|:---|
| api_key | department | 全局唯一标识 |
| label | 部门 | 中文显示名 |
| namespace | system | 系统级元模型 |
| enable_common | 0 | 无 Common 级数据 |
| enable_tenant | 1 | 仅 Tenant 级 |
| entity_dependency | 0 | 不依赖 entity，顶级独立元模型 |
| db_table | p_tenant_department | Tenant 级快捷表 |

### 3.5 department — item 定义（10 个业务字段）

> 原有 6 个 + 补充 4 个 = 10 个。
> `deptParentApiKey` 同 role 的 `roleParentApiKey`，`itemType=10(RELATION_SHIP)` + `dataType=1(VARCHAR)`。

| api_key | db_column | label | itemType | dataType | 来源 |
|:---|:---|:---|:---|:---|:---|
| departName | dbc_varchar1 | 部门名称 | 1(TEXT) | 1(VARCHAR) | 原有 |
| departLevel | dbc_bigint2 | 部门层级 | 5(NUMBER) | 3(BIGINT) | 原有 |
| departPath | dbc_varchar2 | 部门路径 | 1(TEXT) | 1(VARCHAR) | 原有 |
| managerApiKey | dbc_varchar6 | 部门负责人 | 10(RELATION_SHIP) | 1(VARCHAR) | 原有（改造：id→apiKey） |
| sortOrder | dbc_bigint4 | 排序 | 5(NUMBER) | 3(BIGINT) | 原有 |
| enableFlg | dbc_smallint1 | 启用状态 | 31(BOOLEAN) | 6(SMALLINT) | 原有 |
| deptCode | dbc_varchar3 | 部门编码 | 1(TEXT) | 1(VARCHAR) | 补充 |
| deptParentApiKey | dbc_varchar5 | 上级部门 | 10(RELATION_SHIP) | 1(VARCHAR) | 补充（api_key 关联，覆盖默认 BIGINT） |
| deptStatus | dbc_smallint2 | 状态 | 31(BOOLEAN) | 6(SMALLINT) | 补充 |
| deptDescriptionKey | dbc_varchar4 | 描述Key | 1(TEXT) | 1(VARCHAR) | 补充 |

### 3.6 department — entityLink 定义（2 条）

| api_key | label | parent → child | cascadeDelete |
|:---|:---|:---|:---|
| department_department_parentId | 上级部门 | department → department | 2(阻止删除) |
| department_user_departId | 部门用户 | department → user | 0(不级联) |

## 四、业务数据分布

### 4.1 role 业务数据（p_tenant_role）

"系统管理员"作为内置角色在每个租户中自动创建（roleCode=systemAdmin），其他角色为租户自定义。

| tenant_id | name | roleCode | roleStatus | 类型 |
|:---|:---|:---|:---|:---|
| 292193 | 系统管理员 | systemAdmin | 1 | 内置 |
| 292193 | 销售专员 | sales_rep | 1 | 租户自定义 |
| 292193 | 客服专员 | cs_rep | 1 | 租户自定义 |
| 292193 | 只读用户 | readonly | 1 | 租户自定义 |
| 292194 | 系统管理员 | systemAdmin | 1 | 内置 |
| 292194 | 教师 | teacher | 1 | 租户自定义 |
| 292194 | 运营人员 | operator | 1 | 租户自定义 |

### 4.2 department 业务数据（p_tenant_department）

| tenant_id | name | parentId | level | sort |
|:---|:---|:---|:---|:---|
| 292193 | 鸿阳科技 | NULL | 0 | 0 |
| 292193 | 销售部 | 1000 | 1 | 1 |
| 292193 | 客服部 | 1000 | 1 | 2 |
| 292193 | 研发部 | 1000 | 1 | 3 |
| 292193 | 前端组 | 1003 | 2 | 1 |
| 292193 | 后端组 | 1003 | 2 | 2 |
| 292193 | 测试组 | 1003 | 2 | 3 |
| 292194 | 星辰教育 | NULL | 0 | 0 |
| 292194 | 教学部 | 2000 | 1 | 1 |
| 292194 | 运营部 | 2000 | 1 | 2 |

### 4.3 大宽表字段映射（p_tenant_role / p_tenant_department）

| 固定列/dbc列 | role 含义 | department 含义 |
|:---|:---|:---|
| name | 角色名称 | 部门名称 |
| owner_id | 创建人 | 创建人 |
| depart_id | NULL | 部门自身 ID |
| dbc_varchar1 | roleCode（角色编码） | departName（部门名称） |
| dbc_varchar2 | roleDescriptionKey | departPath（部门路径） |
| dbc_varchar3 | — | deptCode（部门编码） |
| dbc_varchar4 | — | deptDescriptionKey |
| dbc_varchar5 | roleParentApiKey（上级角色 api_key） | deptParentApiKey（上级部门 api_key） |
| dbc_bigint2 | roleLevel（层级深度） | departLevel（部门层级） |
| dbc_bigint3 | roleSortOrder（排序号） | —（已迁移到 dbc_varchar6） |
| dbc_bigint4 | — | sortOrder（排序） |
| dbc_smallint1 | roleStatus（状态） | enableFlg（启用状态） |
| dbc_smallint2 | — | deptStatus（状态） |
| dbc_varchar6 | — | managerApiKey（部门负责人 api_key） |

## 五、特殊考虑

### 5.1 ID 一致性

迁移时保持原始 ID 不变：
- `p_user_role.role_api_key` 引用 `p_tenant_role.api_key`（使用 api_key 关联，符合平台规范）
- user 实体的 `departId`（dbc_bigint1）引用 `p_tenant_department.id`
- 数据权限过滤中的 `depart_id` 值不变

### 5.2 树形结构查询

role 和 department 都是树形自关联。当前使用递归 CTE 查询（层级通常 ≤ 10），中期可增加物化路径字段优化。

### 5.3 角色权限矩阵

角色关联的对象级权限矩阵（viewAll/modifyAll 等）存储在独立的权限配置表中，不在元数据体系内，迁移不影响。

## 六、与 user 实体的对比

| 对比项 | user | role | department |
|:---|:---|:---|:---|
| 注册方式 | entity 注册 | 独立元模型（api_key='role'） | 独立元模型（api_key='department'） |
| item 定义 | 25 系统 + 5 自定义 | 6 业务 | 10 业务（6 原有 + 4 补充） |
| 数据存储 | p_user（paas_auth） | p_tenant_role（paas_metarepo） | p_tenant_department（paas_metarepo） |
| 树形结构 | 无 | 有（角色层级） | 有（部门树） |
| 自定义字段 | ✅ 支持 | ✅ 支持 | ✅ 支持 |

## 七、实施记录

### 阶段一：元模型注册（✅ 已完成）

- [x] 在 `p_meta_model` 中注册 `role`（db_table=p_tenant_role）和 `department`（db_table=p_tenant_department）
- [x] 在 `p_meta_item` 中注册 role 6 个字段、department 10 个字段
- [x] 在 `paas_metarepo` 中创建 `p_tenant_role` 和 `p_tenant_department` 快捷表

### 阶段二：数据迁移（✅ 已完成）

- [x] role：7 条数据从 `p_tenant_data_1` 迁移到 `p_tenant_role`
- [x] department：10 条数据从 `p_tenant_data_132` 迁移到 `p_tenant_department`
- [x] 保持原始 ID 不变，确保引用一致
- [x] 软删除 `p_common_metadata` 中的老 entity 注册（3 条）、item 定义（44 条）、entityLink（21 条）、dataPermission（2 条）

### 阶段三：代码切换（✅ 已完成）

- [x] `DepartmentServiceImpl` 改为 `DynamicTableNameHolder.executeWith("p_tenant_department", ...)` 查元数据快捷表
- [x] 新增 `RoleMetadataService`，通过 `DynamicTableNameHolder.executeWith("p_tenant_role", ...)` 查元数据快捷表
- [x] `AuthApiService` 角色查询从 `entityDataService.listAll(tenantId, "role")` 改为 `roleMetadataService.listAll(tenantId)`
- [x] 删除废弃的 `Role.java`、`RoleServiceImpl.java`、`Department.java`
- [ ] 前端管理页面改为元数据驱动（支持自定义字段扩展）
