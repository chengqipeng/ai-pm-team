# user — 用户实体元模型

> 元模型 api_key：`user`
> 存储：迁移至 `paas_entity_data.p_tenant_data_{N}` 大宽表
> 原始表：`paas_metarepo.p_user`（待废弃）
> 命名空间：system
> 状态：📋 迁移中

## 概述

用户（User）是 aPaaS 平台的核心系统实体，存储租户下的所有用户信息。迁移到元数据驱动架构后，用户实体与其他业务实体（account、contact 等）共享统一的元数据管理能力，支持自定义字段扩展、布局配置、校验规则等。

## 迁移方案

### 源表结构（p_user）

| 列名 | 类型 | 说明 |
|:---|:---|:---|
| id | BIGINT | 雪花ID |
| tenant_id | BIGINT | 租户ID |
| name | VARCHAR(100) | 姓名 |
| phone | VARCHAR(20) | 手机号（登录凭证） |
| email | VARCHAR(100) | 邮箱 |
| status | SMALLINT | 1=启用 2=停用 |
| user_type | SMALLINT | 0=普通用户 1=管理员 |
| depart_id | BIGINT | 所属部门ID |
| manager_id | BIGINT | 上级主管ID |
| lock_auth_status | SMALLINT | 0=正常 1=锁定 |
| avatar_url | VARCHAR(500) | 头像URL |
| passport_id | BIGINT | 通行证ID |
| created_at | BIGINT | 创建时间(ms) |
| created_by | BIGINT | 创建人 |
| updated_at | BIGINT | 更新时间(ms) |
| updated_by | BIGINT | 更新人 |

### 目标：p_tenant_data 大宽表映射

| 源列 | 目标 dbc 列 | item apiKey | item label | itemType |
|:---|:---|:---|:---|:---|
| name | name（固定列） | name | 姓名 | 1(文本) |
| phone | dbc_varchar1 | phone | 手机号 | 13(电话) |
| email | dbc_varchar2 | email | 邮箱 | 23(邮箱) |
| avatar_url | dbc_varchar3 | avatarUrl | 头像 | 24(网址) |
| status | dbc_smallint1 | status | 状态 | 2(单选) |
| user_type | dbc_smallint2 | userType | 用户类型 | 2(单选) |
| lock_auth_status | dbc_smallint3 | lockAuthStatus | 锁定状态 | 2(单选) |
| depart_id | dbc_bigint1 | departId | 所属部门 | 10(关联) |
| manager_id | dbc_bigint2 | managerId | 上级主管 | 10(关联) |
| passport_id | dbc_bigint3 | passportId | 通行证ID | 5(整数) |

### 元数据注册

entity 注册到 p_common_metadata（metamodel_api_key='entity'）：
- api_key: user
- label: 用户
- namespace: system
- entity_type: 2（系统对象）
- enable_flg: 1
- db_table: p_tenant_data_0（与其他系统实体共享）

item 注册到 p_common_metadata（metamodel_api_key='item'）：
- 10 个业务字段 + 系统固定字段（id, ownerId, createdAt 等）

pick_option 注册：
- status: 1=启用, 2=停用
- userType: 0=普通用户, 1=管理员
- lockAuthStatus: 0=正常, 1=锁定
