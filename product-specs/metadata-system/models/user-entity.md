# user — 用户实体最终架构

> 状态：✅ 已实施

## 架构

```
p_user（认证表，精简）           p_tenant_data WHERE entity_api_key='user'（业务主表）
├── id                           ├── id（同一个 ID）
├── tenant_id                    ├── tenant_id
├── phone ← 登录凭证             ├── name, depart_id, owner_id ← 固定列
└── password_hash ← 仅此表       ├── dbc_varchar1 (userName/phone) ← 冗余
                                 ├── dbc_varchar2 (realName)
                                 ├── dbc_varchar5 (avatar)
                                 ├── dbc_varchar6 (status)
                                 ├── dbc_bigint1 (departId)
                                 ├── dbc_bigint2 (roleId)
                                 ├── dbc_varchar4 (jobTitle) ← 自定义
                                 ├── dbc_varchar5 (workLocation) ← 自定义
                                 ├── dbc_bigint4 (entryDate) ← 自定义
                                 ├── dbc_varchar6 (employeeNo) ← 自定义
                                 └── dbc_varchar7 (emergencyContact) ← 自定义
```

## 字段映射与同步规则

### name 与 realName 的关系

| 字段 | 存储位置 | 来源 | 说明 |
|:---|:---|:---|:---|
| `name` | p_user.name / p_tenant_data.name | 固定列 | 所有实体都有的固定列，不在元数据 `p_common_metadata` 中定义，前端列表展示用此字段 |
| `realName` | p_tenant_data.dbc_varchar2 | 元数据字段 | user 实体的元数据字段（label="姓名"），编辑弹框通过此字段渲染姓名输入 |

两者表达同一含义（用户姓名），保留 `realName` 的原因：
- `name` 是固定列，不在 `/metadata/items` 返回结果中，元数据驱动的编辑弹框无法渲染它
- `realName` 在元数据表中有定义，编辑弹框通过它提供姓名编辑入口

**同步规则**：
- **读取（编辑回显）**：前端通过 `aliasMap` 将 `realName` 映射到 `p_user.name` 的值进行回显
- **写入（保存）**：前端保存时自动将 `realName` 的值同步写入 `name` 固定列，确保列表展示一致

```
编辑弹框回显: user.name → values['realName']  (aliasMap: realName → name)
保存时同步:   values['realName'] → payload['name']  (自动复制)
```

### userName 与 phone 的关系

| 字段 | 存储位置 | 来源 | 说明 |
|:---|:---|:---|:---|
| `phone` | p_user.phone | 认证表固定列 | 登录凭证，`/auth/users` 返回此字段 |
| `userName` | p_tenant_data.dbc_varchar1 | 元数据字段 | user 实体的元数据字段（label="用户名"），编辑弹框通过此字段渲染 |

**同步规则**：与 name/realName 相同，读取时 `aliasMap: userName → phone`，保存时应同步。

### 前端 aliasMap 完整定义

```typescript
// UserFormModal 初始化时的字段别名映射
// 元数据 apiKey → p_user 返回的字段名（BFF 未启动时 fallback 兼容）
const aliasMap: Record<string, string> = {
  userName: 'phone',    // 元数据"用户名" ← p_user.phone
  realName: 'name',     // 元数据"姓名"   ← p_user.name
};
```

## p_user 精简后保留字段

| 字段 | 用途 | 说明 |
|:---|:---|:---|
| id | 主键 | 与 p_tenant_data.id 一致 |
| tenant_id | 租户隔离 | |
| phone | 登录凭证 | 手机号登录 |
| password_hash | 密码 | 安全敏感，不进大宽表 |

## p_user 已删除字段（迁移到 p_tenant_data）

| 原字段 | 迁移目标 | 说明 |
|:---|:---|:---|
| name | p_tenant_data.name | 固定列 |
| email | dbc_varchar2 | 业务属性 |
| status | dbc_varchar6 | 业务属性 |
| user_type | dbc_smallint2 | 业务属性 |
| depart_id | p_tenant_data.depart_id | 固定列 |
| manager_id | dbc_bigint2 | 业务属性 |
| lock_auth_status | dbc_smallint3 | 业务属性 |
| avatar_url | dbc_varchar5 | 业务属性 |
| passport_id | dbc_bigint3 | 业务属性 |

## API 架构

```
前端 → Node BFF (/api/user/*) → Java 后端
                                  ├── /auth/users (读 p_user)
                                  └── /entity/data/user (读写 p_tenant_data)

合并逻辑全部在 Node BFF 完成，前端只做展示。
```

| 前端调用 | BFF 路由 | 后端操作 |
|:---|:---|:---|
| listUsers() | GET /api/user/list | 读 /auth/users + /entity/data/user → 合并返回 |
| createUser() | POST /api/user | 写 /auth/user/create + /entity/data/user |
| updateUser() | PUT /api/user | 写 /auth/user/update + /entity/data/user |
| toggleUser() | POST /api/user/toggle | 写两处 status |
| deleteUser() | DELETE /api/user/:id | 删两处 |

## paas_auth 建表规范

### BaseEntity 基础字段（必须）

paas_auth schema 下所有表的 Java 实体均继承 `com.hongyang.framework.dao.entity.BaseEntity`，框架层 MyBatis-Plus 会自动在 SELECT/INSERT/UPDATE 中引用以下 6 个字段。**新建表时必须包含全部 6 列，缺少任何一列会导致运行时 SQL 报错。**

| 列名 | 类型 | 说明 | 是否必须 |
|:---|:---|:---|:---:|
| `id` | BIGINT PRIMARY KEY | 主键，雪花算法生成 | ✅ |
| `delete_flg` | SMALLINT NOT NULL DEFAULT 0 | 软删除标记，0=正常 1=已删除 | ✅ |
| `created_at` | BIGINT | 创建时间（毫秒时间戳） | ✅ |
| `created_by` | BIGINT | 创建人 userId | ✅ |
| `updated_at` | BIGINT | 更新时间（毫秒时间戳） | ✅ |
| `updated_by` | BIGINT | 更新人 userId | ✅ |

### 建表模板

```sql
CREATE TABLE paas_auth.p_xxx (
    -- BaseEntity 基础字段（6 列，必须）
    id              BIGINT       PRIMARY KEY,
    delete_flg      SMALLINT     NOT NULL DEFAULT 0,
    created_at      BIGINT,
    created_by      BIGINT,
    updated_at      BIGINT,
    updated_by      BIGINT,
    -- 租户隔离（如需要）
    tenant_id       BIGINT       NOT NULL,
    -- 业务字段
    ...
);
CREATE INDEX idx_p_xxx_tid ON paas_auth.p_xxx (tenant_id);
```

### 当前 paas_auth 表清单

| 表名 | Java 实体 | 说明 | BaseEntity 6 列 |
|:---|:---|:---|:---:|
| p_user | PlatformUser (extends BaseTenantDataEntity) | 用户表 | ✅ |
| p_passport | Passport | 全局身份凭证 | ✅ |
| p_passport_log | PassportLog | 登录日志 | ✅ |
| p_department | Department | 部门表 | ✅ |
| p_role | Role | 角色表 | ✅ |
| p_user_role | UserRole | 用户-角色关联 | ✅ |
| p_tenant_auth_provider | AuthProvider | 认证提供商 | ✅ |
| p_tenant_ip_whitelist | IpWhitelist | IP 白名单 | ✅ |
| p_tenant_login_policy | LoginPolicy | 登录策略 | ✅ |
| p_tenant_oauth_client | OauthClient | OAuth 客户端 | ✅ |
| p_tenant_password_policy | PasswordPolicy | 密码策略 | ✅ |
| p_tenant_third_binding | ThirdBinding | 第三方绑定 | ✅ |
| p_totp_secret | TotpSecret | TOTP 密钥 | ✅ |

> 2026-04-14 验证：全部 13 张表均已包含 BaseEntity 6 个基础字段。
