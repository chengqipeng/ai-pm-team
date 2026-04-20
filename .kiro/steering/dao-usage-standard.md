---
inclusion: fileMatch
fileMatchPattern: "**/*.java"
---

# DAO 层使用规范（自动注入）

当编写或修改 Java 代码时，必须遵循以下 DAO 层规范：

## 硬约束

1. **Mapper 必须继承 `SuperMapper<T>`**（`com.hongyang.framework.dao.mapper.SuperMapper`），禁止直接继承 `BaseMapper<T>`
2. **Service 必须继承 framework-dao 基类**：
   - 普通业务数据 → `DataBaseServiceImpl<T>`
   - 元数据 → `MetaServiceImpl<T>`
   - Common/Tenant 合并 → `CommonTenantServiceImpl<T>`
   - 已元模型化的数据（role/department 等）→ 通过 `IMetadataMergeReadService` / `IMetadataMergeWriteService` 标准链路
3. **禁止 Service 直接注入 Mapper 做标准 CRUD**（getById/save/update/delete），必须使用继承的框架方法
4. **仅在聚合统计、高频局部更新、复杂条件查询等场景允许自定义 SQL**，且仍通过 Service 层调用
5. **分页返回值使用 `PageResult<T>`**，禁止直接返回 MyBatis-Plus 的 `Page<T>`
6. **禁止手动加 `eq("tenant_id", tenantId)`**，拦截器自动追加；跨租户查询用 `executeIgnoreTenant()`
7. **禁止硬编码 dbc 列名**（如 `r.get("dbc_varchar5")`），已元模型化的数据必须走标准元数据链路
8. **禁止手动构造 Map 做 JSON 字段名转换**，直接返回 Entity 对象，Jackson 全局 SNAKE_CASE 自动转换
9. **`@IgnoreTenantLine` 的 Entity 禁止使用 `lambdaQuery()`**，必须使用 `list(Wrapper)` / `getOne(Wrapper)` 等已覆盖方法
10. **禁止在 Controller 中通过 `@RequestHeader` 获取 tenantId / userId**，从 `GlobalContext` 获取（AuthTokenInterceptor 已从 JWT 注入）。例外：`/auth/login`

## 详细规范

完整规范文档：#[[file:product-specs/metadata-system/DAO层使用设计规范.md]]
