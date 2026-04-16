# depart_id 迁移为 depart_api_key 方案

## 一、变更范围

将所有表的 `depart_id BIGINT`（引用部门 ID）改为 `depart_api_key VARCHAR(255)`（引用部门 api_key）。

### 1.1 数据库表

| 表 | 库 | 当前列 | 目标列 | 数据量 |
|:---|:---|:---|:---|:---|
| p_user | paas_auth | depart_id BIGINT | depart_api_key VARCHAR(255) | 小 |
| p_tenant_data_0 ~ p_tenant_data_1999 | paas_entity_data | depart_id BIGINT | depart_api_key VARCHAR(255) | 2000 张分片表 |

### 1.2 Java 实体类

| 类 | 当前字段 | 目标字段 |
|:---|:---|:---|
| PlatformUser | `private Long departId` | `private String departApiKey` |
| TenantData | `private Long departId` | `private String departApiKey` |
| BaseTenantDataEntity（如有） | `departId` | `departApiKey` |

### 1.3 Java 服务层

| 文件 | 改动 | 状态 |
|:---|:---|:---:|
| AuthApiService | departId → departApiKey | ✅ |
| EntityDataApiService | departId 过滤 → departApiKey | ✅ |
| EntityDataService | departId → departApiKey | ✅ |
| EntityDataBatchService | departId → departApiKey | ✅ |
| DataPermissionFilter | `depart_id IN (...)` → `depart_api_key IN (...)` | ✅ |
| DeptPermissionRefreshService | departId → departApiKey | ✅ |
| PermissionTraceService | departId → departApiKey | ✅ |
| DataShareWriteService | departId → departApiKey | ✅ |
| SharingRuleEngine | departId → departApiKey | ✅ |
| DepartmentServiceImpl | 移除 getById/getDescendantIds 兼容方法 | ✅ |
| PlatformUserServiceImpl | getUserDepartId → getUserDepartApiKey | ✅ |

### 1.4 前端

| 文件 | 改动 | 状态 |
|:---|:---|:---:|
| auth.ts PlatformUserRow | departId → departApiKey | ✅ |
| auth.ts LoginUser | departId → departApiKey | ✅ |
| auth.ts listUsers | departId 参数 → departApiKey | ✅ |
| types/auth.ts LoginUser | departId → departApiKey | ✅ |
| types/admin.ts UserRow | departApiKey: number → string | ✅ |
| api/entityData.ts BizDataRecord | departId → departApiKey | ✅ |
| ShellApp.tsx | departId → departApiKey | ✅ |
| UserManagementView | selectedDeptId → 直接用 apiKey | ✅ |
| DeptManagementView | 用户过滤 → departApiKey | ✅ |
| UserDetailModal | departId → departApiKey | ✅ |

## 二、DDL 迁移脚本

```sql
-- Step 1: p_user 表（paas_auth 库）
ALTER TABLE paas_auth.p_user ADD COLUMN depart_api_key VARCHAR(255);
-- 数据迁移：从 p_tenant_department 查 api_key 回填
UPDATE paas_auth.p_user u
SET depart_api_key = (
    SELECT d.api_key FROM paas_metarepo.p_tenant_department d
    WHERE d.id = u.depart_id AND d.delete_flg = 0
    LIMIT 1
)
WHERE u.depart_id IS NOT NULL;
-- 验证后删除老列
-- ALTER TABLE paas_auth.p_user DROP COLUMN depart_id;

-- Step 2: p_tenant_data 分片表（paas_entity_data 库，批量执行）
-- 生成 2000 条 ALTER TABLE 语句
DO $$
BEGIN
    FOR i IN 0..1999 LOOP
        EXECUTE format('ALTER TABLE paas_entity_data.p_tenant_data_%s ADD COLUMN depart_api_key VARCHAR(255)', i);
    END LOOP;
END $$;

-- 数据迁移（按实体分批执行，避免锁表）
-- UPDATE paas_entity_data.p_tenant_data_0 t
-- SET depart_api_key = (SELECT d.api_key FROM paas_metarepo.p_tenant_department d WHERE d.id = t.depart_id LIMIT 1)
-- WHERE t.depart_id IS NOT NULL;
```

## 三、实施步骤

1. ✅ 先执行 DDL 添加新列（不删除老列）— DDL 建表脚本已更新
2. ✅ 部署新代码（读写新列 depart_api_key）— PlatformUser.departApiKey 已为 String 类型
3. 执行数据迁移脚本（回填 depart_api_key）
4. 验证数据一致性
5. 确认无误后删除老列 depart_id
