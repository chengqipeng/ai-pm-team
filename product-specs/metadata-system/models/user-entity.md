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
