# DAO 层使用设计规范

本文档定义 aPaaS 平台数据访问层的使用规范。所有业务服务的数据库操作必须通过 framework-dao 框架完成，禁止直接使用 MyBatis-Plus 原生 API。

---

## 1. 核心原则

**统一通过 framework-dao 访问数据库，禁止绕过框架直接使用 MyBatis-Plus。**

framework-dao 在 MyBatis-Plus 之上封装了缓存、租户隔离、双阶段缓存失效、事务感知、元数据保护等核心能力。直接使用 MyBatis-Plus 会绕过这些保护机制，导致缓存不一致、租户数据泄漏等严重问题。

---

## 2. 禁止事项

### 2.1 禁止直接继承 MyBatis-Plus BaseMapper

```java
// ❌ 禁止：直接继承 BaseMapper
public interface FileMetaMapper extends BaseMapper<FileMeta> {}

// ✅ 正确：继承 framework-dao 的 SuperMapper
public interface FileMetaMapper extends SuperMapper<FileMeta> {}
```

### 2.2 禁止 Service 层直接注入和使用 Mapper

```java
// ❌ 禁止：Service 直接注入 Mapper 操作数据库
@Service
public class MyService {
    @Autowired
    private MyMapper myMapper;
    public MyEntity get(long id) {
        return myMapper.selectById(id);  // 绕过缓存和租户隔离
    }
}

// ✅ 正确：继承 DataBaseServiceImpl，通过框架方法操作
@Service
public class MyService extends DataBaseServiceImpl<MyEntity> {
    public MyEntity get(long id) {
        return getById(id);  // 自动走缓存 + 租户隔离
    }
}
```

### 2.3 禁止直接构造 MyBatis-Plus 查询对象并调用 Mapper

```java
// ❌ 禁止：直接 new LambdaQueryWrapper 并调用 mapper
LambdaQueryWrapper<ExcelTask> wrapper = new LambdaQueryWrapper<>();
return taskMapper.selectPage(new Page<>(page, pageSize), wrapper);

// ✅ 正确：使用 DataBaseServiceImpl 的 list(Wrapper) / getOne(Wrapper) 等已覆盖方法
return list(new QueryWrapper<ExcelTask>().eq("status", 1));
```

### 2.4 禁止直接使用 MyBatis-Plus 的 Page 作为返回值

```java
// ❌ 禁止
public Page<ExcelTask> getMyTasks(...) { ... }

// ✅ 正确
public PageResult<ExcelTask> getMyTasks(...) { ... }
```

### 2.5 禁止在业务代码中手动做 JSON 字段名转换

```java
// ❌ 禁止：手动构造 Map 做 camelCase → snake_case 转换
public static Map<String, Object> mapRoleRow(Role r) {
    Map<String, Object> row = new HashMap<>();
    row.put("api_key", r.getApiKey());
    row.put("name", r.getLabel());
    return row;
}

// ✅ 正确：直接返回 Entity 对象，Jackson 全局 SNAKE_CASE 策略自动转换
result.put("data", role);  // Jackson 自动: apiKey → api_key, roleLevel → role_level
```

### 2.6 禁止在业务代码中手动加 tenant_id 条件

```java
// ❌ 禁止：手动加 tenant_id（拦截器会自动追加，导致重复条件）
return list(new QueryWrapper<UserRole>()
        .eq("tenant_id", tenantId)  // ← 多余
        .eq("role_api_key", roleApiKey));

// ✅ 正确：拦截器自动追加 tenant_id
return list(new QueryWrapper<UserRole>()
        .eq("role_api_key", roleApiKey));

// ✅ 跨租户查询：使用 executeIgnoreTenant
public List<PlatformUser> listByPassportId(Long passportId) {
    return executeIgnoreTenant(() ->
            list(new QueryWrapper<PlatformUser>().eq("passport_id", passportId)));
}
```

### 2.7 禁止硬编码 dbc 列名

```java
// ❌ 禁止：硬编码 dbc 列名
Object v = r.get("dbc_varchar5");  // 谁知道 dbc_varchar5 是什么？

// ✅ 正确：使用元数据 Entity 的强类型字段
String parentApiKey = dept.getDeptParentApiKey();
```

已元模型化的数据（role、department 等）必须通过 `IMetadataMergeReadService` / `IMetadataMergeWriteService` 标准链路操作，字段映射由 `CommonMetadataConverter` 根据 `p_meta_item` 自动完成。

---

## 3. Service 层继承规范

### 3.1 业务数据 Service

普通业务数据（非元数据）的 Service 必须继承 `DataBaseServiceImpl<T>`：

```java
@Service
public class ExcelTaskServiceImpl extends DataBaseServiceImpl<ExcelTask> {
    // 自动获得：缓存、租户隔离、双阶段缓存失效、软删除等能力
}
```

#### 租户拦截机制

| 机制 | 适用场景 | 使用方式 |
|:---|:---|:---|
| 拦截器自动追加 | 默认行为，绝大多数查询 | 不需要任何代码，拦截器自动追加 `AND tenant_id = ?` |
| `@IgnoreTenantLine` | 无 tenant_id 列的表（Passport）或系统补偿表（OperateLog） | Entity 类加注解，框架自动跳过 |
| `executeIgnoreTenant()` | 有 tenant_id 但某些方法需跨租户（如登录查一人多租户） | Service 方法内调用 `executeIgnoreTenant(() -> ...)` |

> `@IgnoreTenantLine` 对应 `p_meta_model.enable_tenant_intercept=0`。详见 [租户拦截器元模型驱动设计](租户拦截器元模型驱动设计.md)。

#### lambdaQuery() 限制

`@IgnoreTenantLine` 的 Entity 禁止使用 `lambdaQuery()`，因为链式 API 内部直接调用 `baseMapper`，绕过了 `executeWithTenantControl`。必须使用以下已覆盖的方法：

| 方法 | 说明 |
|---|---|
| `getById(id)` | 按 ID 查询（缓存 + 租户控制） |
| `listByIds(ids)` | 批量查询 |
| `list()` | 全量查询（缓存） |
| `list(Wrapper)` | 条件查询 |
| `getOne(Wrapper)` | 条件查询单条 |
| `count(Wrapper)` | 条件计数 |
| `listMaps(Wrapper)` | 条件查询返回 Map |
| `getMap(Wrapper)` | 条件查询单条返回 Map |
| `save(entity)` | 新增 |
| `saveBatch(list)` | 批量新增 |
| `saveOrUpdate(entity)` | 新增或更新 |
| `updateById(entity)` | 按 ID 更新 |
| `update(entity, Wrapper)` | 条件更新 |
| `updateBatchById(list)` | 批量更新 |
| `removeById(id)` | 按 ID 删除 |
| `removeByIds(list)` | 批量删除 |
| `remove(Wrapper)` | 条件删除 |
| `page(PageQuery)` | 分页查询 |
| `getByIdAndTenant(id, tenantId)` | 租户隔离查询 |
| `softDelete(id, tenantId)` | 租户隔离软删除 |
| `getByIdBypassCache(id)` | 绕过缓存直查 |
| `executeIgnoreTenant(Supplier)` | 方法级跨租户查询 |

### 3.2 元数据 Service

已元模型化的数据（role、department、sharingRule 等）通过标准元数据链路操作：

```java
@Service
@RequiredArgsConstructor
public class RoleMetadataService {
    private final IMetadataMergeReadService mergeReadService;
    private final IMetadataMergeWriteService mergeWriteService;

    public List<Role> listAll() {
        return mergeReadService.listMerged(MetamodelApiKey.ROLE);
    }

    public Role create(String name, ...) {
        Role role = new Role();
        role.setApiKey(code);
        role.setLabel(name);
        return mergeWriteService.create(MetamodelApiKey.ROLE, role, operatorId);
    }
}
```

> tenantId 由 GlobalContext 提供，Service 方法签名不传 tenantId。
> 字段映射由 CommonMetadataConverter 根据 p_meta_item 自动完成，禁止硬编码 dbc 列名。

### 3.3 Common/Tenant 合并查询 Service

需要 Common + Tenant 双层合并的元数据 Service 继承 `CommonTenantServiceImpl<T>`。

---

## 4. JSON 序列化规范

### 4.1 全局 SNAKE_CASE 策略

`application.yml` 配置：

```yaml
spring:
  jackson:
    property-naming-strategy: SNAKE_CASE
```

所有 API 响应自动将 Java camelCase 字段转为 snake_case JSON：
- `roleParentApiKey` → `role_parent_api_key`
- `createdAt` → `created_at`
- `deleteFlg` → `delete_flg`

### 4.2 前端自动转换

前端 axios interceptor 全局处理：
- 请求：camelCase → snake_case（`convertKeys(data, toSnake)`）
- 响应：snake_case → camelCase（`convertKeys(data, toCamel)`）

业务代码（前后端）统一使用各自的命名风格，转换由框架/拦截器自动完成。

### 4.3 禁止手动转换

禁止在业务代码中手动构造 `Map<String, Object>` 做字段名转换（如 `mapRoleRow`、`mapDeptRow`）。直接返回 Entity 对象，Jackson 自动序列化。

---

## 5. Mapper 层规范

### 5.1 基本规则

- 所有 Mapper 必须继承 `SuperMapper<T>`（而非 `BaseMapper<T>`）
- 大多数场景不需要手动定义 Mapper，`AutoMapperRegistrar` 会自动注册
- 仅在聚合统计、高频局部更新、复杂条件查询等场景允许自定义 SQL

### 5.2 自定义 SQL 的注入方式

自定义 Mapper 中的方法仍然通过 Service 层调用：

```java
@Service
public class ExcelTaskServiceImpl extends DataBaseServiceImpl<ExcelTask> {
    @Autowired
    private ExcelTaskMapper excelTaskMapper;

    // 标准 CRUD → 使用继承的框架方法
    public ExcelTask getTask(long id) { return getById(id); }

    // 自定义 SQL → 通过注入的 Mapper 调用
    public int countActive(long tenantId) {
        return excelTaskMapper.countActiveByTenant(tenantId);
    }
}
```

---

## 6. Entity 层规范

### 6.1 基类继承

| 数据类型 | 基类 | 说明 |
|---|---|---|
| 普通业务数据 | `BaseEntity` | id, deleteFlg, createdAt/By, updatedAt/By |
| 带租户的业务数据 | `BaseTenantDataEntity` | BaseEntity + tenantId |
| Common 级元数据 | `BaseMetaCommonEntity` | BaseEntity + apiKey, namespace, label, customFlg |
| Tenant 级元数据 | `BaseMetaTenantEntity` | BaseMetaCommonEntity + tenantId |

### 6.2 框架注解

| 注解 | 位置 | 作用 |
|---|---|---|
| `@TableName("p_xxx")` | Entity 类 | MyBatis-Plus 表名映射 |
| `@DaoCacheConfig` | Entity 类 | 缓存策略配置 |
| `@IgnoreTenantLine` | Entity 类 | 跳过租户拦截（无 tenant_id 列或系统补偿表） |

---

## 7. 改造检查清单

| # | 检查项 | 违规标志 | 修复方式 |
|---|---|---|---|
| 1 | Mapper 继承 | `extends BaseMapper<T>` | 改为 `extends SuperMapper<T>` |
| 2 | Service 继承 | 未继承框架基类 | 继承 `DataBaseServiceImpl<T>` 或用 `IMetadataMergeReadService` |
| 3 | 直接注入 Mapper | `@Autowired Mapper` 做标准 CRUD | 改用继承的框架方法 |
| 4 | 手动 tenant_id | `eq("tenant_id", tenantId)` | 删除，拦截器自动追加 |
| 5 | 硬编码 dbc 列 | `r.get("dbc_varchar5")` | 改用元数据 Entity 强类型字段 |
| 6 | 手动 JSON 转换 | `mapRoleRow()`、`mapDeptRow()` | 删除，直接返回 Entity |
| 7 | 返回值类型 | 返回 `Page<T>` | 改为 `PageResult<T>` |
| 8 | 缓存绕过 | `mapper.selectById()` | 改用 `getById()` 或 `getByIdBypassCache()` |

---

## 8. 已完成改造记录

| 模块 | 文件 | 改造内容 | 日期 |
|---|---|---|---|
| dao | `DataBaseServiceImpl.java` | 新增 `@IgnoreTenantLine` 框架支持 + `executeIgnoreTenant()` + 覆盖 `list(Wrapper)`/`getOne`/`count`/`listMaps`/`getMap` | 2026-04-16 |
| dao | `IgnoreTenantLine.java` | 新增 Entity 级注解 | 2026-04-16 |
| dao | `TenantInterceptor.java` | 简化为只判断 `p_meta_*`/`p_common_*` 前缀 | 2026-04-16 |
| auth | `Role.java` / `Department.java` | 新增元数据 Entity 类，注册到 MetamodelApiKeyEnum | 2026-04-16 |
| auth | `RoleMetadataService.java` | 重写：DynamicTableNameHolder + 硬编码 dbc → 标准元数据链路 | 2026-04-16 |
| auth | `DepartmentServiceImpl.java` | 重写：同上，去掉 tenantId 参数 | 2026-04-16 |
| auth | `PlatformUserServiceImpl.java` | 去掉手动 `eq("tenant_id")`，跨租户用 `executeIgnoreTenant` | 2026-04-16 |
| auth | `UserRoleServiceImpl.java` | 去掉手动 `eq("tenant_id")` | 2026-04-16 |
| auth | `Passport.java` / `PassportLog.java` | 加 `@IgnoreTenantLine`（无 tenant_id 列） | 2026-04-16 |
| auth | `AuthApiService.java` | 去掉手动 tenant_id、删除 mapRoleRow/mapDeptRow、直接返回 Entity | 2026-04-16 |
| config | `MetaRepoDataConfig.java` | 删除 PLATFORM_TABLES + addIgnorePredicate | 2026-04-16 |
| config | `EntityDataConfig.java` | 删除 addIgnoreTable | 2026-04-16 |
| config | `application.yml` | 新增 `property-naming-strategy: SNAKE_CASE` | 2026-04-16 |
| operatelog | `OperateLog.java` | 从 framework-dao 移到业务层，加 `@IgnoreTenantLine` | 2026-04-16 |
| operatelog | `OperateLogBaseDao.java` | 删除（框架不再需要） | 2026-04-16 |
| operatelog | `MetaOperateLogDao.java` / `EntityOperateLogDao.java` | 直接继承 DataBaseServiceImpl | 2026-04-16 |
