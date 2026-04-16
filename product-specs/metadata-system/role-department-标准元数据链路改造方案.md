# Role / Department 标准元数据链路改造方案

> 日期：2026-04-16
> 目标：消除 DepartmentServiceImpl 和 RoleMetadataService 中的 dbc 列硬编码，改为走标准元数据链路

## 一、问题

当前 `DepartmentServiceImpl` 和 `RoleMetadataService` 虽然操作的是已元模型化的表（p_tenant_department / p_tenant_role），但代码中：

1. **硬编码 dbc 列名**：`r.get("dbc_varchar5")` 代替 `dept.getDeptParentApiKey()`
2. **硬编码 DynamicTableNameHolder**：`DynamicTableNameHolder.executeWith("p_tenant_role", ...)`
3. **直接操作 TenantData**：`dataDao.save(new TenantData())` + `dataDao.update(null, uw.set("dbc_varchar1", ...))`
4. **手动构造 UpdateWrapper 设置 dbc 列**：绕过了 CommonMetadataConverter 的 apiKey → dbColumn 映射

这违背了元数据驱动的核心理念。字段映射应该从 p_meta_item 动态获取。

## 二、目标架构

```
改造前：
  AuthApiService → RoleMetadataService → DynamicTableNameHolder + TenantData + 硬编码 dbc 列
  AuthApiService → DepartmentServiceImpl → DynamicTableNameHolder + TenantData + 硬编码 dbc 列

改造后：
  AuthApiService → RoleService → IMetadataMergeReadService / IMetadataMergeWriteService
  AuthApiService → DepartmentService → IMetadataMergeReadService / IMetadataMergeWriteService
```

## 三、改造步骤

### 3.1 新增 Entity 类

参考 `SharingRule extends BaseMetaTenantEntity` 的模式：

```java
// Role.java
package com.hongyang.platform.paas.service.entity.metadata;

import com.hongyang.framework.dao.entity.BaseMetaTenantEntity;
import lombok.Data;
import lombok.EqualsAndHashCode;

@Data
@EqualsAndHashCode(callSuper = true)
public class Role extends BaseMetaTenantEntity {
    private String entityApiKey;      // 固定列（独立元模型为 null）
    /** 角色编码（即 api_key） */
    private String roleCode;          // dbc_varchar1
    /** 描述国际化 Key */
    private String roleDescriptionKey; // dbc_varchar2
    /** 上级角色 api_key */
    private String roleParentApiKey;  // dbc_varchar5
    /** 层级深度 */
    private Long roleLevel;           // dbc_bigint2
    /** 排序号 */
    private Long roleSortOrder;       // dbc_bigint3
    /** 状态：0=禁用, 1=启用 */
    private Integer roleStatus;       // dbc_smallint1
}
```

```java
// Department.java
package com.hongyang.platform.paas.service.entity.metadata;

import com.hongyang.framework.dao.entity.BaseMetaTenantEntity;
import lombok.Data;
import lombok.EqualsAndHashCode;

@Data
@EqualsAndHashCode(callSuper = true)
public class Department extends BaseMetaTenantEntity {
    private String entityApiKey;
    /** 部门名称 */
    private String departName;         // dbc_varchar1
    /** 部门路径 */
    private String departPath;         // dbc_varchar2
    /** 部门编码 */
    private String deptCode;           // dbc_varchar3
    /** 描述国际化 Key */
    private String deptDescriptionKey; // dbc_varchar4
    /** 上级部门 api_key */
    private String deptParentApiKey;   // dbc_varchar5
    /** 部门层级 */
    private Long departLevel;          // dbc_bigint2
    /** 部门负责人 */
    private Long managerId;            // dbc_bigint3
    /** 排序 */
    private Long sortOrder;            // dbc_bigint4
    /** 启用状态 */
    private Integer enableFlg;         // dbc_smallint1
    /** 状态 */
    private Integer deptStatus;        // dbc_smallint2
}
```

> 字段名与 p_meta_item 中的 apiKey 一致，CommonMetadataConverter 自动完成 apiKey ↔ dbColumn 映射。

### 3.2 注册 MetamodelApiKeyEnum

```java
// MetamodelApiKeyEnum.java 新增两行
ROLE(MetamodelApiKey.ROLE, Role.class),
DEPARTMENT(MetamodelApiKey.DEPARTMENT, Department.class),
```

### 3.3 重写 RoleService（原 RoleMetadataService）

```java
@Slf4j
@Service
@RequiredArgsConstructor
public class RoleService {

    private final IMetadataMergeReadService mergeReadService;
    private final IMetadataMergeWriteService mergeWriteService;
    private final IdGenerator idGenerator;

    // ==================== 查询 ====================

    public List<Role> listAll() {
        return mergeReadService.listMerged(MetamodelApiKey.ROLE);
    }

    public Role getByApiKey(String apiKey) {
        return mergeReadService.getByApiKeyMerged(MetamodelApiKey.ROLE, apiKey);
    }

    public List<Role> listByApiKeys(List<String> apiKeys) {
        if (apiKeys == null || apiKeys.isEmpty()) return Collections.emptyList();
        List<Role> all = listAll();
        Set<String> keySet = new HashSet<>(apiKeys);
        return all.stream()
                .filter(r -> keySet.contains(r.getApiKey()))
                .collect(Collectors.toList());
    }

    // ==================== 写入 ====================

    public Role create(String name, String roleCode, String parentApiKey,
                       Integer sortOrder, Long operatorId) {
        List<Role> all = listAll();

        // 校验
        String effectiveCode = roleCode != null && !roleCode.isEmpty()
                ? roleCode : String.valueOf(idGenerator.nextId());
        if (all.stream().anyMatch(r -> effectiveCode.equals(r.getApiKey()))) {
            throw new IllegalArgumentException("角色编码已存在: " + effectiveCode);
        }
        if (all.stream().anyMatch(r ->
                Objects.equals(r.getRoleParentApiKey(), parentApiKey) && name.equals(r.getLabel()))) {
            throw new IllegalArgumentException("同级下已存在同名角色: " + name);
        }

        // 计算层级
        int level = 0;
        if (parentApiKey != null && !parentApiKey.isEmpty()) {
            Role parent = all.stream()
                    .filter(r -> parentApiKey.equals(r.getApiKey())).findFirst().orElse(null);
            if (parent == null) throw new IllegalArgumentException("父角色不存在: " + parentApiKey);
            level = (parent.getRoleLevel() != null ? parent.getRoleLevel().intValue() : 0) + 1;
        }
        if (sortOrder == null) {
            sortOrder = all.stream()
                    .filter(r -> Objects.equals(r.getRoleParentApiKey(), parentApiKey))
                    .map(r -> r.getRoleSortOrder() != null ? r.getRoleSortOrder().intValue() : 0)
                    .max(Integer::compareTo).orElse(0) + 1;
        }

        Role role = new Role();
        role.setApiKey(effectiveCode);
        role.setLabel(name);
        role.setRoleCode(effectiveCode);
        role.setRoleParentApiKey(parentApiKey);
        role.setRoleLevel((long) level);
        role.setRoleSortOrder((long) sortOrder);
        role.setRoleStatus(1);

        return mergeWriteService.create(MetamodelApiKey.ROLE, role, operatorId);
    }

    public void update(String roleApiKey, String newName,
                       Integer newStatus, Integer newSortOrder, Long operatorId) {
        Role role = getByApiKey(roleApiKey);
        if (role == null) throw new IllegalArgumentException("角色不存在: " + roleApiKey);

        if (newName != null) role.setLabel(newName);
        if (newStatus != null) role.setRoleStatus(newStatus);
        if (newSortOrder != null) role.setRoleSortOrder((long) newSortOrder);

        mergeWriteService.update(MetamodelApiKey.ROLE, role, operatorId);
    }

    public void delete(String roleApiKey) {
        if ("systemAdmin".equals(roleApiKey)) {
            throw new IllegalArgumentException("系统管理员角色不可删除");
        }
        mergeWriteService.delete(MetamodelApiKey.ROLE, roleApiKey, null);
    }
}
```

> 注意：不再传 tenantId 参数。`IMetadataMergeReadService` 内部从 GlobalContext 获取 tenantId。

### 3.4 重写 DepartmentService（原 DepartmentServiceImpl）

同样的模式，用 `mergeReadService.listMerged(MetamodelApiKey.DEPARTMENT)` 替代 `DynamicTableNameHolder + dataDao.listMaps`。

树形操作（`getDescendantApiKeys`、`recalcChildLevels`、`wouldCreateCycle`）保持业务逻辑不变，只是数据来源从 `Map<String, Object>` 改为 `Department` 强类型对象。

### 3.5 适配 AuthApiService

```java
// 改造前
List<Map<String, Object>> roles = roleMetadataService.listAll(tenantId);
Map<String, Object> row = RoleMetadataService.mapRoleRow(r);

// 改造后
List<Role> roles = roleService.listAll();
// 直接返回 Role 对象，前端适配层做 camelCase 转换
```

`mapRoleRow` / `mapDeptRow` 这些手动转换方法可以删除——`Role` / `Department` 对象本身就是 camelCase 字段，Spring MVC 的 Jackson 序列化自动处理。

### 3.6 适配权限模块

`DataPermissionFilter`、`PermissionTraceService`、`PermissionValidationService` 中调用的 `departmentService.getDescendantApiKeys(tenantId, deptApiKey)` 方法签名改为 `departmentService.getDescendantApiKeys(deptApiKey)`（tenantId 由 GlobalContext 提供）。

## 四、消除的硬编码

| 消除项 | 位置 | 替代 |
|:---|:---|:---|
| `r.get("dbc_varchar5")` | RoleMetadataService / DepartmentServiceImpl | `role.getRoleParentApiKey()` / `dept.getDeptParentApiKey()` |
| `r.get("dbc_bigint2")` | 同上 | `role.getRoleLevel()` / `dept.getDepartLevel()` |
| `r.get("dbc_bigint3")` | 同上 | `role.getRoleSortOrder()` / `dept.getSortOrder()` |
| `r.get("dbc_smallint1")` | 同上 | `role.getRoleStatus()` / `dept.getEnableFlg()` |
| `uw.set("dbc_varchar1", ...)` | create/update 方法 | `mergeWriteService.create/update` 自动映射 |
| `DynamicTableNameHolder.executeWith("p_tenant_role", ...)` | 所有方法 | `mergeReadService` 内部自动路由 |
| `dataDao.save(new TenantData())` + `dataDao.update(null, uw)` | create 方法 | `mergeWriteService.create(metamodelApiKey, entity, operatorId)` |
| `mapRoleRow` / `mapDeptRow` | AuthApiService | 直接返回 Entity 对象 |

## 五、文件变更清单

### 新增（2 个）

| 文件 | 说明 |
|:---|:---|
| `entity/metadata/Role.java` | Role Entity 类，继承 BaseMetaTenantEntity |
| `entity/metadata/Department.java` | Department Entity 类，继承 BaseMetaTenantEntity |

### 重写（2 个）

| 文件 | 改动 |
|:---|:---|
| `service/auth/RoleMetadataService.java` → `RoleService.java` | 全部重写，改用 mergeReadService / mergeWriteService |
| `service/auth/DepartmentServiceImpl.java` → `DepartmentService.java` | 全部重写，改用 mergeReadService / mergeWriteService |

### 修改（1 个）

| 文件 | 改动 |
|:---|:---|
| `common/constants/MetamodelApiKeyEnum.java` | 新增 ROLE / DEPARTMENT 枚举值 |

### 适配（5 个）

| 文件 | 改动 |
|:---|:---|
| `api/auth/AuthApiService.java` | `Map<String, Object>` → `Role` / `Department` 强类型，删除 `mapRoleRow` / `mapDeptRow` |
| `service/datapermission/DataPermissionFilter.java` | `departmentService.getDescendantApiKeys` 签名适配 |
| `service/datapermission/PermissionTraceService.java` | 同上 |
| `service/datapermission/PermissionValidationService.java` | 同上（如有引用） |
| `service/datapermission/UserSubjectService.java` | 同上（如有引用） |

### 不变

| 文件 | 原因 |
|:---|:---|
| `IMetadataMergeReadService.java` | 标准接口，不变 |
| `IMetadataMergeWriteService.java` | 标准接口，不变 |
| `MetadataMergeReadServiceImpl.java` | 标准实现，自动支持新注册的 ROLE / DEPARTMENT |
| `MetadataMergeWriteServiceImpl.java` | 同上 |
| `CommonMetadataConverter.java` | 自动根据 p_meta_item 做 apiKey ↔ dbColumn 映射 |
| 前端代码 | API 响应格式从 `Map` 变为 `Role`/`Department` 对象，但字段名不变（camelCase） |

## 六、风险与注意事项

1. **GlobalContext tenantId**：`IMetadataMergeReadService` 从 GlobalContext 获取 tenantId，调用方不再传 tenantId 参数。需确认所有调用路径中 GlobalContext 已设置。
2. **enable_common=0**：role 和 department 的 `enable_common=0`，`mergeReadService` 只查 Tenant 表，不查 Common 表。需确认 `MetadataMergeReadServiceImpl` 正确处理此场景。
3. **前端兼容**：AuthApiService 返回的 JSON 字段名从 `Map` 的 key（如 `apiKey`、`name`）变为 Entity 的 Jackson 序列化（如 `apiKey`、`label`）。需确认前端 `auth.ts` 中的字段名映射。
4. **树形操作性能**：`getDescendantApiKeys` 当前是全量查询后内存遍历。改用 `mergeReadService.listMerged` 后行为不变，但需确认缓存策略。
