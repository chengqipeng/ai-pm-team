# department（部门）— 元数据体系归属分析

## 一、结论

**部门（department）已纳入元数据体系。** 详见 [role-department-metadata.md](role-department-metadata.md)。

| 维度 | 现状 | 状态 |
|:---|:---|:---|
| 元模型注册（p_meta_model） | ✅ 注册为独立元模型 api_key='department' | 已完成 |
| 字段定义（p_meta_item） | ✅ 10 个业务字段 | 已完成 |
| 数据存储 | ✅ `paas_metarepo.p_tenant_department`（10 条，2 租户） | 已迁移 |
| 关联关系（entityLink） | ✅ 2 条（自关联 + 部门用户） | 已完成（已软删除老注册） |
| 老表 `paas_auth.p_department` | ✅ 已删除 | 已清理 |
| 老 entity 注册（p_common_metadata） | ✅ 已软删除 | 已清理 |
| Java 代码 | ✅ DepartmentServiceImpl 查 p_tenant_department | 已完成 |
| 前端管理 | 待改为元数据驱动 | 待实施 |

## 二、现状分析

### 2.1 当前存储：独立表 p_department

部门数据存储在 `paas_metarepo.p_department`（或 `base_user` 库），不在元数据体系内：

```
p_department
├── id              BIGINT       — 部门ID
├── tenant_id       BIGINT       — 租户ID
├── name            VARCHAR(100) — 部门名称
├── parent_id       BIGINT       — 上级部门ID（自关联，树形结构）
├── dept_level      INT          — 层级深度（0=根节点）
├── sort_order      INT          — 同级排序
├── created_at      BIGINT       — 创建时间
└── updated_at      BIGINT       — 更新时间
```

### 2.2 当前 API

| 接口 | 方法 | 说明 | 状态 |
|:---|:---|:---|:---|
| `/auth/departments` | GET | 查询部门树 | ✅ 可用 |
| `/auth/department/create` | POST | 创建部门 | ❌ 不存在 |
| `/auth/department/update` | PUT | 更新部门 | ❌ 不存在 |
| `/auth/department/delete` | DELETE | 删除部门 | ❌ 不存在 |

### 2.3 被引用情况

department 是 **★必要** 的系统级实体，被所有核心业务实体引用：

| 引用方 | 关联字段 | 用途 |
|:---|:---|:---|
| account | dimDepart, outterDepartId | 客户所属部门、外部部门 |
| contact | dimDepart | 联系人所属部门 |
| opportunity | dimDepart | 商机所属部门 |
| lead | dimDepart | 线索所属部门 |
| user | departId | 用户所属部门 |
| 数据权限 | depart_id | 部门级数据可见性过滤 |

**结论：department 是数据权限的基础维度，所有业务数据的部门归属都依赖它。**

### 2.4 元数据体系中的位置

在 `account-centric-analysis.md` 中，department 被明确标注为：

> | department | 6 | 所有实体的 departId 引用 | **★必要** | 组织架构，数据权限基础 |

但在已注册的元模型中，department 已作为**独立元模型**注册到 `p_meta_model`（api_key='department'），数据存储在 `paas_metarepo.p_tenant_department`。

## 三、与 user 实体的对比

user 实体已经完成了元数据化改造（见 `user-entity.md`）：

| 对比项 | user | department |
|:---|:---|:---|
| entity 注册 | ✅ 已在 p_common_metadata | ❌ 未注册 |
| item 定义 | ✅ 25 系统 + 5 自定义 | ❌ 无 |
| 数据存储 | p_user → 迁移中 | p_department（独立表） |
| 前端管理 | 元数据驱动（动态列/表单） | 硬编码（固定字段） |
| 自定义字段 | ✅ 支持 | ❌ 不支持 |

## 四、迁移方案

### 4.1 目标表结构映射

| p_department 列 | 目标 dbc 列 | item apiKey | item label | itemType |
|:---|:---|:---|:---|:---|
| name | name（固定列） | name | 部门名称 | 1(文本) |
| parent_id | dbc_bigint1 | parentId | 上级部门 | 10(关联) |
| dept_level | dbc_int1 | deptLevel | 层级深度 | 5(整数) |
| sort_order | dbc_int2 | sortOrder | 排序号 | 5(整数) |
| — | dbc_varchar1 | deptCode | 部门编码 | 1(文本) |
| — | dbc_varchar2 | description | 部门描述 | 4(文本域) |
| — | dbc_smallint1 | status | 状态 | 2(单选) |

### 4.2 元数据注册 SQL

```sql
-- 1. entity 注册（如果 Common 中不存在）
INSERT INTO p_common_metadata (
    id, metamodel_api_key, api_key, label, label_key, namespace,
    description, custom_flg, enable_flg, delete_flg,
    dbc_int1, dbc_varchar2,
    created_at, updated_at
) VALUES (
    {snowflake_id}, 'entity', 'department', '部门',
    'XdMDObj.department', 'system',
    '组织架构部门，树形结构，数据权限基础维度',
    0, 1, 0,
    2, 'p_tenant_data_0',
    {now}, {now}
);

-- 2. item 注册
INSERT INTO p_common_metadata (id, metamodel_api_key, entity_api_key, api_key, label, namespace, ...) VALUES
({id}, 'item', 'department', 'parentId', '上级部门', 'system', ...),
({id}, 'item', 'department', 'deptLevel', '层级深度', 'system', ...),
({id}, 'item', 'department', 'sortOrder', '排序号', 'system', ...),
({id}, 'item', 'department', 'deptCode', '部门编码', 'system', ...),
({id}, 'item', 'department', 'description', '部门描述', 'system', ...),
({id}, 'item', 'department', 'status', '状态', 'system', ...);

-- 3. entity_link 注册（自关联）
INSERT INTO p_common_metadata (id, metamodel_api_key, api_key, label, namespace, ...) VALUES
({id}, 'entityLink', 'department_to_department_parent', '上级部门', 'system', ...);
```

### 4.3 特殊考虑：树形结构

department 的核心特征是 **树形自关联**（parentId → department.id）。迁移到大宽表后需要：

1. **parentId 关联方式**：从 ID 关联改为 apiKey 关联（如果部门有 apiKey），或保持 ID 关联（部门是系统实体，ID 在租户内稳定）
2. **树形查询性能**：大宽表中的递归查询需要优化（物化路径或闭包表）
3. **数据权限依赖**：权限系统通过 `depart_id IN (#{deptIds})` 过滤数据，迁移后需要确保查询路径不变

## 五、建议

### 短期（当前阶段）

1. **保持 p_department 独立表不动**，不急于迁移到大宽表
2. **在 p_common_metadata 中注册 department 的 entity 和 item 定义**，让元数据浏览器能看到它
3. **前端部门管理页面保持现有 API**（`/auth/departments`），不改为元数据驱动

### 中期（V2 阶段）

1. 将 department 数据迁移到 `p_tenant_data` 大宽表
2. 前端部门管理改为元数据驱动（支持自定义字段）
3. 数据权限查询适配新的存储路径

### 原因

- department 是树形结构，大宽表的递归查询性能需要专门优化
- department 是数据权限的基础维度，迁移风险高，需要充分测试
- 当前 `/auth/departments` API 工作正常，没有紧迫的迁移需求
- user 实体的迁移经验可以为 department 迁移提供参考
