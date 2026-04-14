# 部门管理 CRUD 与数据权限刷新详细设计

---

## 一、现状分析

### 1.1 已有能力

| 组件 | 状态 | 说明 |
|:---|:---:|:---|
| `Department` 实体 | ✅ | `p_department` 表，字段：id, tenantId, name, parentId, deptLevel, sortOrder |
| `DepartmentServiceImpl` | ✅ | 仅有 `listByTenant()` 查询方法 |
| `AuthApiService.listDepartments` | ✅ | `GET /auth/departments` 查询接口 |
| `DeptManagementView` 前端 | ✅ | 部门树展示 + 详情查看，"新建部门"按钮无功能 |
| `DeptTree` 组件 | ✅ | 左侧部门树选择器，多个页面复用 |
| `useDeptTree` Hook | ✅ | 加载部门树 + 扁平化列表 |

### 1.2 缺失能力

| 能力 | 状态 | 影响 |
|:---|:---:|:---|
| 新增部门 API + UI | ❌ | 无法创建子部门 |
| 修改部门 API + UI | ❌ | 无法改名、调整上级、调整排序 |
| 删除部门 API + UI | ❌ | 无法删除空部门 |
| 部门变更 → 权限刷新 | ❌ | 部门调整后用户数据可见范围不更新 |
| 部门删除 → share 清理 | ❌ | 删除部门后残留 share 记录 |
| 部门变更 → 共享规则重算 | ❌ | 基于部门的共享规则不重新执行 |

---

## 二、数据模型

### 2.1 p_department 表（已有）

```
p_department
├── id              BIGINT PK（雪花算法）
├── tenant_id       BIGINT NOT NULL
├── name            VARCHAR(100) NOT NULL
├── parent_id       BIGINT（根部门为 NULL）
├── dept_level      INT（0=根, 1=一级, 2=二级...）
├── sort_order      INT（同级排序）
├── delete_flg      SMALLINT DEFAULT 0
├── created_at      BIGINT
├── created_by      BIGINT
├── updated_at      BIGINT
└── updated_by      BIGINT
```

### 2.2 关联表

| 表 | 关联字段 | 说明 |
|:---|:---|:---|
| `p_user` (PlatformUser) | `depart_id` → `p_department.id` | 用户所属部门 |
| `p_data_share` | `subject_api_key` = 部门ID字符串, `subject_type=1` | 部门级 share 记录 |
| `p_common_metadata` (sharingRule) | `from_subject_api_key` / `to_subject_api_key` | 共享规则引用部门 |

---

## 三、后端 API 设计

### 3.1 新增部门

```
POST /auth/department/create
Request:  { name, parent_id, sort_order? }
Response: { code: 200, data: { id, name, parent_id, dept_level, sort_order } }
```

业务规则：
- `name` 必填，同一 `parent_id` 下不允许重名
- `dept_level` = 父部门 `dept_level + 1`，根部门 `dept_level = 0`
- `sort_order` 默认取同级最大值 + 1
- `parent_id` 为 null 时创建根部门（每个租户只允许一个根部门）

### 3.2 修改部门

```
PUT /auth/department/update
Request:  { id, name?, parent_id?, sort_order? }
Response: { code: 200 }
```

业务规则：
- 修改 `name`：同级不允许重名
- 修改 `parent_id`（调整上级）：
  - 不允许将部门移到自己的子部门下（防止循环）
  - 自动重算 `dept_level`（递归更新所有子部门）
  - **触发权限刷新**（见 §五）
- 修改 `sort_order`：仅影响显示顺序，不触发权限刷新

### 3.3 删除部门

```
DELETE /auth/department/delete?id={deptId}
Response: { code: 200 }
```

业务规则：
- 有子部门时不允许删除（返回 400 "请先删除子部门"）
- 有成员时不允许删除（返回 400 "请先转移部门成员"）
- 软删除（`delete_flg = 1`）
- **触发权限清理**（见 §五）

---

## 四、前端设计

### 4.1 前端 API 层（auth.ts 新增）

```typescript
/** 新增部门 */
export async function createDepartment(dept: {
  name: string; parentId: number | null; sortOrder?: number;
}): Promise<DepartmentNode> { ... }

/** 修改部门 */
export async function updateDepartment(dept: {
  id: number; name?: string; parentId?: number | null; sortOrder?: number;
}): Promise<void> { ... }

/** 删除部门 */
export async function deleteDepartment(id: number): Promise<void> { ... }
```

### 4.2 DeptManagementView 交互设计

| 操作 | 入口 | 交互 |
|:---|:---|:---|
| 新增子部门 | 选中部门后，右侧详情区"新增子部门"按钮 | 弹窗输入名称 → 调用 API → 刷新树 |
| 新增根部门 | 顶部"新建部门"按钮（无根部门时） | 弹窗输入名称 → 调用 API → 刷新树 |
| 修改部门 | 右侧详情区"编辑"按钮 | 弹窗编辑名称/上级/排序 → 调用 API → 刷新树 |
| 删除部门 | 右侧详情区"删除"按钮 | 确认弹窗（显示子部门数和成员数）→ 调用 API → 刷新树 |

### 4.3 删除保护

删除前检查：
- 子部门数 > 0 → 按钮禁用，tooltip "请先删除子部门"
- 成员数 > 0 → 按钮禁用，tooltip "请先转移部门成员"
- 两者都为 0 → 允许删除，二次确认

---

## 五、部门变更 → 数据权限刷新

### 5.1 影响分析矩阵

| 部门操作 | 影响的权限组件 | 刷新动作 | 同步/异步 |
|:---|:---|:---|:---:|
| 新增部门 | 无 | 不需要刷新 | — |
| 修改部门名称 | 无 | 不需要刷新（权限按 ID 关联，不按名称） | — |
| 修改部门上级 | UserSubject 缓存 | 清除该部门所有成员的 `user_subjects` 缓存 | 同步 |
| 修改部门上级 | 共享规则 | 重算引用该部门的"基于负责人"共享规则 | 异步 |
| 删除部门 | share 表 | 软删除 `subject_type=1, subject_api_key=deptId` 的 share 记录 | 同步 |
| 删除部门 | UserSubject 缓存 | 清除该部门所有成员的 `user_subjects` 缓存 | 同步 |
| 删除部门 | 共享规则 | 检查是否有规则引用该部门，有则告警 | 同步 |

### 5.2 修改部门上级 → 权限刷新流程

```
PUT /auth/department/update { id: 1002, parent_id: 1003 }
  │
  ├─ 1. 更新 p_department 表
  │     UPDATE p_department SET parent_id=1003, dept_level=? WHERE id=1002
  │     递归更新子部门的 dept_level
  │
  ├─ 2. 查询该部门的所有成员
  │     SELECT user_id FROM p_user WHERE depart_id=1002 AND tenant_id=?
  │
  ├─ 3. 清除每个成员的权限主体缓存
  │     for userId in memberIds:
  │       UserSubjectService.evictCache(tenantId, userId)
  │     → 下次查询时自动重新展开权限主体（包含新的部门层级）
  │
  ├─ 4. 检查共享规则引用
  │     查询 sharingRule 中 fromSubjectType=2(部门) AND fromSubjectApiKey=1002
  │     或 toSubjectType=2(部门) AND toSubjectApiKey=1002
  │     如果有匹配规则 → 记录日志，后续可触发规则重算
  │
  └─ 5. 返回成功
```

### 5.3 删除部门 → 权限清理流程

```
DELETE /auth/department/delete?id=1002
  │
  ├─ 1. 前置校验
  │     子部门数 > 0 → 拒绝
  │     成员数 > 0 → 拒绝
  │
  ├─ 2. 软删除 p_department
  │     UPDATE p_department SET delete_flg=1 WHERE id=1002
  │
  ├─ 3. 清理 share 表中该部门的记录
  │     遍历所有 entity 的 share 路由表：
  │     UPDATE p_data_share_{N} SET delete_flg=1
  │       WHERE tenant_id=? AND subject_type=1 AND subject_api_key='1002'
  │     （通过 DataShareWriteService 新增 cleanByDepartment 方法）
  │
  ├─ 4. 检查共享规则引用
  │     查询引用该部门的 sharingRule
  │     如果有 → 返回告警信息（不阻塞删除，但提示管理员修改规则）
  │
  └─ 5. 返回成功 + 告警信息（如有）
```

### 5.4 用户调部门 → 权限刷新流程

当用户的 `depart_id` 变更时（在用户管理中修改），也需要触发权限刷新：

```
PUT /auth/user/update { id: userId, depart_id: newDeptId }
  │
  ├─ 1. 更新 p_user.depart_id
  │
  ├─ 2. 更新 share 表中该用户数据的部门 share
  │     遍历该用户负责的所有数据：
  │     UPDATE p_data_share SET subject_api_key='newDeptId'
  │       WHERE subject_type=1 AND share_cause=2
  │       AND data_id IN (SELECT id FROM p_tenant_data WHERE owner_id=userId)
  │     （简化方案：清除旧部门 share + 重新初始化新部门 share）
  │
  ├─ 3. 清除用户权限主体缓存
  │     UserSubjectService.evictCache(tenantId, userId)
  │
  └─ 4. 重算该用户数据的共享规则
        SharingRuleEngine.matchAndApply(...)
```

---

## 六、后端服务层设计

### 6.1 DepartmentServiceImpl 新增方法

```java
/** 创建部门 */
public Department create(long tenantId, String name, Long parentId,
                          Integer sortOrder, Long operatorId)

/** 更新部门 */
public void update(long tenantId, long deptId, String name,
                    Long parentId, Integer sortOrder, Long operatorId)

/** 删除部门（含前置校验） */
public DeptDeleteResult delete(long tenantId, long deptId, Long operatorId)

/** 查询部门的所有成员 ID */
public List<Long> getMemberUserIds(long tenantId, long deptId)

/** 查询部门的所有子部门 ID（递归） */
public List<Long> getDescendantIds(long tenantId, long deptId)

/** 递归更新子部门的 dept_level */
private void recalcLevels(long tenantId, long deptId, int newLevel)

/** 检测循环引用 */
private boolean wouldCreateCycle(long tenantId, long deptId, long newParentId)
```

### 6.2 DataShareWriteService 新增方法

```java
/** 清理某个部门的所有 share 记录（部门删除时调用） */
public void cleanByDepartment(long tenantId, String deptApiKey)
```

### 6.3 DeptPermissionRefreshService（新增）

```java
/**
 * 部门变更权限刷新服务。
 * 协调部门 CRUD 与数据权限系统的联动。
 */
@Service
public class DeptPermissionRefreshService {

    /** 部门上级变更时刷新权限 */
    public void onDeptParentChanged(long tenantId, long deptId,
                                     Long oldParentId, Long newParentId)

    /** 部门删除时清理权限 */
    public DeptDeleteWarning onDeptDeleted(long tenantId, long deptId)

    /** 用户调部门时刷新权限 */
    public void onUserDeptChanged(long tenantId, Long userId,
                                   Long oldDeptId, Long newDeptId)
}
```

---

## 七、实施步骤

| 阶段 | 内容 | 依赖 |
|:---:|:---|:---|
| 1 | 后端：`DepartmentServiceImpl` 新增 create/update/delete 方法 | 无 |
| 2 | 后端：`AuthApiService` 新增 3 个部门 CRUD 接口 | 阶段 1 |
| 3 | 后端：`DataShareWriteService.cleanByDepartment()` | 无 |
| 4 | 后端：`DeptPermissionRefreshService` 权限刷新服务 | 阶段 1, 3 |
| 5 | 后端：部门 CRUD 接口中集成权限刷新调用 | 阶段 2, 4 |
| 6 | 前端：`auth.ts` 新增 3 个部门 API 函数 | 阶段 2 |
| 7 | 前端：`DeptManagementView` 新增弹窗和操作按钮 | 阶段 6 |
| 8 | 前端：`useDeptTree` Hook 新增 refresh 能力 | 无 |

---

## 八、风险与降级

| 风险 | 影响 | 降级方案 |
|:---|:---|:---|
| 部门删除时 share 清理遗漏 | 已删除部门的 share 记录残留，不影响查询（subject 不匹配） | 定期清理脚本 |
| 部门上级变更时缓存清除不完整 | 用户短时间内看到旧的数据范围 | 缓存 TTL 5 分钟自动过期 |
| 共享规则引用已删除部门 | 规则匹配失败，不产生 share | 删除时告警，管理员手动修改规则 |
| 大部门（1000+ 成员）变更时批量清缓存 | 短时间 Redis 压力 | 分批清除，每批 100 个 |
