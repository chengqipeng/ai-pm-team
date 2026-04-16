# user — 用户实体架构

> 状态：✅ 已实施（2026-04-15 重构）

## 架构

```
p_user（paas_auth schema）
├── 19 个公共固定列（与 p_tenant_data 一致）
│   └── id, tenant_id, entity_api_key, name, owner_id, depart_id,
│       busitype_api_key, approval_status, applicant_id, lock_status,
│       workflow_stage, currency_unit, currency_rate, territory_id,
│       delete_flg, created_at, created_by, updated_at, updated_by
├── 用户认证固定列（p_user 独有，p_tenant_data 没有）
│   └── phone, email, passport_id, status, user_type, avatar_url,
│       manager_id, position, lock_auth_status, pwd_rule_id,
│       pwd_expire_at, pwd_updated_at, login_try_times,
│       login_lock_time, reset_pwd_flg, api_access_token,
│       security_token, open_id
└── dbc 扩展列（与 p_tenant_data 同类型，数量较少）
    ├── dbc_varchar1~50   VARCHAR(300)
    ├── dbc_bigint1~30    BIGINT
    ├── dbc_decimal1~10   DECIMAL(20,4)
    ├── dbc_smallint1~10  SMALLINT
    ├── dbc_textarea1~5   TEXT
    └── dbc_multi1~5      JSONB
```

### p_user 与 p_tenant_data 的差异

| 对比项 | p_tenant_data_* | p_user |
|:---|:---|:---|
| 19 个公共固定列 | ✅ | ✅ 一致 |
| 认证固定列（phone, status 等） | ❌ 没有 | ✅ 有 |
| dbc_varchar | 1~250 | 1~50 |
| dbc_bigint | 1~195 | 1~30 |
| dbc_decimal | 1~140 | 1~10 |
| dbc_smallint | 1~35 | 1~10 |
| dbc_textarea | 1~20 | 1~5 |
| dbc_multi | 1~30 | 1~5 |
| dbc_int / dbc_text | ❌ 不存在 | ❌ 不存在 |

> ⚠️ 大宽表只有 6 种 dbc 列类型：varchar、bigint、decimal、smallint、textarea、multi。
> 元数据中 db_column 引用了 dbc_int1 或 dbc_text1 属于配置错误，
> `EntityColumnResolver.isValidDbcColumn()` 会自动过滤并打印警告日志。

## 元数据存储

user 实体的字段定义遵循标准 Common/Tenant 双层架构：

| 层级 | 存储表 | 内容 | namespace |
|:---|:---|:---|:---|
| Common（出厂） | p_common_metadata | 系统预置字段（userName, realName, avatar, status, departId, roleId, lastLoginAt） | system |
| Tenant（个性化） | p_tenant_item | 租户自定义字段（jobTitle, workLocation, entryDate 等） | custom |

通过 `IMetadataMergeReadService.listMergedByEntityApiKey("item", "user")` 合并读取，
与 Account、Contact 等业务实体完全一致。

## 数据读写流程

```
用户业务数据 CRUD → /entity/data/user（通用 EntityDataApiService）
                    ↓
              TableRouteService.resolveTableName("user")
                → FIXED_TABLE_MAP 命中 → "p_user"（不走分表路由）
                    ↓
              EntityColumnResolver.resolveColumns("user")
                → FIXED_COLUMNS（19 列）
                + EXTRA_FIXED_COLUMNS["user"]（phone, email, status 等 9 列）
                + 元数据 dbc 列（isValidDbcColumn 校验后）
                    ↓
              TenantDataServiceImpl.pageMaps() → SELECT 指定列 FROM paas_auth.p_user

认证操作 → /auth/*（AuthApiService，只操作 p_user 固定列）
           ├── POST /auth/login          → 登录认证
           ├── POST /auth/user/create    → 创建认证记录 + 角色分配
           ├── PUT  /auth/user/update    → 更新固定列（name, phone, email, status）
           ├── POST /auth/user/toggle    → 启用/禁用
           └── DELETE /auth/user/delete  → 软删除

角色管理 → /auth/*（AuthApiService）
           ├── GET  /auth/user/roles     → 查询用户角色
           ├── POST /auth/roles/assign   → 分配角色
           └── POST /auth/roles/unassign → 移除角色
```

## 关键设计决策

### 为什么 p_user 不走分表路由？

`TableRouteService.FIXED_TABLE_MAP` 将 `entityApiKey="user"` 固定路由到 `p_user`：
- p_user 在 paas_auth schema，有独立的认证安全列
- 登录流程需要直接查 p_user（phone + passport_id）
- 用户数据量有限（单租户 < 10000），不需要分表

### PlatformUser 实体类

`PlatformUser extends BaseTenantDataEntity`，只声明固定列和认证安全列，
**不声明 dbc 扩展列**（与 `TenantData` 保持一致）。

dbc 列通过 `EntityDataService.pageMaps()` 返回 `Map<String, Object>`，
由 `EntityColumnResolver` 根据元数据动态解析需要 SELECT 的列。

### EntityColumnResolver 对 user 的特殊处理

1. `EXTRA_FIXED_COLUMNS["user"]`：追加 phone, email, status, user_type 等 p_user 独有固定列
2. `isValidDbcColumn()`：校验 dbc 列名前缀，过滤 dbc_int1、dbc_text1 等不存在的列类型
3. Redis 缓存校验：读取缓存时检查 dbc 列合法性 + 额外固定列完整性，不合格则清除重建

### 前端 dbc 列名 → apiKey 映射

`/entity/data/user` 返回 snake_case 列名（如 `dbc_varchar4`），
前端需要转换为元数据 apiKey（如 `jobTitle`）。

`UserManagementView` 中 `enrichedUsers` 通过 `allItems` 的 `dbColumn → apiKey` 映射，
将 dbc 列值复制到 apiKey 上，让列表渲染和编辑弹窗都能用 apiKey 访问数据。

编辑弹窗 `UserFormModal` 初始化时，按优先级取值：
1. `user[item.apiKey]` — 直接匹配
2. `user[aliasMap[item.apiKey]]` — 别名映射（realName→name, userName→phone）
3. `user[item.dbColumn]` — dbc 列名 fallback

## 当前字段映射

### 系统字段（p_common_metadata, namespace=system）

| apiKey | db_column | label |
|:---|:---|:---|
| userName | dbc_varchar1 | 用户名 |
| realName | dbc_varchar2 | 姓名 |
| avatar | dbc_varchar5 | 头像 |
| status | dbc_varchar6 | 状态 |
| departId | dbc_bigint1 | 所属部门 |
| roleId | dbc_bigint2 | 角色 |
| lastLoginAt | dbc_bigint3 | 最后登录 |

### 自定义字段（p_tenant_item, namespace=custom）

| apiKey | db_column | label | 备注 |
|:---|:---|:---|:---|
| jobTitle | dbc_varchar4 | 职位 | |
| workLocation | dbc_varchar10 | 工作地点 | 从 dbc_varchar5 迁移，修复与 avatar 的列冲突 |
| employeeNo | dbc_varchar11 | 工号 | 从 dbc_varchar6 迁移，修复与 status 的列冲突 |
| emergencyContact | dbc_varchar7 | 紧急联系人 | |
| wechatId | dbc_varchar9 | 微信号 | |
| entryDate | dbc_bigint4 | 入职日期 | |
| contractEndDate | dbc_bigint8 | 合同到期日 | |
| skillLevel | dbc_smallint6 | 技能等级 | |
| annualLeave | dbc_smallint7 | 年假天数 | 从 dbc_int1 迁移，p_user 无 dbc_int 类型 |
| personalBio | dbc_textarea1 | 个人简介 | 从 dbc_text1 迁移，p_user 无 dbc_text 类型 |

### name 与 realName 的关系

| 字段 | 存储位置 | 说明 |
|:---|:---|:---|
| name | p_user.name（固定列） | 列表展示用，不在元数据 items 中 |
| realName | p_user.dbc_varchar2（元数据字段） | 编辑弹框通过此字段渲染姓名输入 |

前端 aliasMap：`realName → name`（读取回显），保存时 `realName → name`（同步写入）。

## 前端 API 调用

| 操作 | 接口 | 说明 |
|:---|:---|:---|
| 用户列表 | GET /entity/data/user | 通用实体数据接口，分页 + 元数据驱动列 |
| 用户详情 | GET /entity/data/user/{id} | 通用实体数据接口 |
| 创建用户 | POST /auth/user/create | 认证记录 + 角色 |
| 更新认证 | PUT /auth/user/update | 固定列（name, phone, email, status） |
| 更新业务 | PUT /entity/data/user/{id} | 自定义字段（dbc 列） |
| 启用/禁用 | POST /auth/user/toggle | 认证操作 |
| 删除 | DELETE /auth/user/delete | 软删除 |
| 查询角色 | GET /auth/user/roles | 查询用户已分配的角色 |
| 分配角色 | POST /auth/roles/assign | 分配角色给用户 |
| 移除角色 | POST /auth/roles/unassign | 从用户移除角色 |
| 角色列表 | GET /auth/roles | 查询所有角色 |

## 已删除的代码

| 文件 | 原用途 | 删除原因 |
|:---|:---|:---|
| UserFieldResolver.java | 硬编码 apiKey↔dbc 列映射 | 改用元数据驱动 + EntityColumnResolver |
| user-routes.cjs | BFF 用户路由（含本地 JSON 存储） | 违反架构约束（BFF 禁止存储数据） |
| user-ext-data.json | BFF 本地自定义字段数据 | 同上 |
| AuthApiService.listUsers | 硬编码用户列表查询 | 改用 /entity/data/user 通用接口 |
| AuthApiService.getUser | 硬编码用户详情查询 | 改用 /entity/data/user/{id} 通用接口 |

## 待执行 SQL

depart_id → depart_api_key 迁移脚本（详见 `depart_id迁移为depart_api_key方案.md`）：
```sql
-- 已在 DDL 建表脚本中更新为 depart_api_key VARCHAR(255)
-- 存量数据库需执行以下迁移：
ALTER TABLE paas_auth.p_user ADD COLUMN IF NOT EXISTS depart_api_key VARCHAR(255);
UPDATE paas_auth.p_user u
SET depart_api_key = (
    SELECT d.api_key FROM paas_metarepo.p_tenant_department d
    WHERE d.id = u.depart_id AND d.delete_flg = 0
    LIMIT 1
)
WHERE u.depart_id IS NOT NULL AND u.depart_api_key IS NULL;
-- 验证后删除老列：ALTER TABLE paas_auth.p_user DROP COLUMN depart_id;
```

## paas_auth 表清单

| 表名 | Java 实体 | 说明 |
|:---|:---|:---|
| p_user | PlatformUser | 用户表（大宽表，含认证列 + dbc 扩展列） |
| p_passport | Passport | 全局身份凭证 |
| p_passport_log | PassportLog | 登录日志 |
| p_user_role | UserRole | 用户-角色关联 |
| p_tenant_auth_provider | AuthProvider | 认证提供商 |
| p_tenant_ip_whitelist | IpWhitelist | IP 白名单 |
| p_tenant_login_policy | LoginPolicy | 登录策略 |
| p_tenant_oauth_client | OauthClient | OAuth 客户端 |
| p_tenant_password_policy | PasswordPolicy | 密码策略 |
| p_tenant_third_binding | ThirdBinding | 第三方绑定 |
| p_totp_secret | TotpSecret | TOTP 密钥 |

> 注意：`p_role` 和 `p_department` 已从 paas_auth 移除，迁移到元数据体系。
> 详见 [role-department-metadata.md](role-department-metadata.md)。
