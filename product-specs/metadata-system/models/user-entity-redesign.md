# p_user 元数据字段精简方案

## 设计原则

1. 与 p_user 固定列重复的 dbc 字段全部移除（passport_id、manager_id、avatar_url 等已有固定列）
2. 老系统遗留的无用字段移除（QQ/MSN、手机定位、技能值等）
3. 纯分隔线字段（xxxInfoLine）移除，前端用布局组件替代
4. 每种 dbc 类型至少保留 1 个预留位，支持租户自定义扩展
5. dbc 列编号从 1 开始连续分配，避免空洞

## 精简后的自定义字段（17 个）

### varchar 类型（8 个使用 + 2 个预留）

| # | apiKey | label | db_column | 说明 |
|---|--------|-------|-----------|------|
| 1 | alias | 别名 | dbc_varchar1 | 用户别名 |
| 2 | employeeCode | 员工编号 | dbc_varchar2 | 工号 |
| 3 | unionId | 唯一标识 | dbc_varchar3 | 第三方集成 ID |
| 4 | enterpriseWechatAccount | 企业微信账号 | dbc_varchar4 | 企微绑定 |
| 5 | positionName | 职位 | dbc_varchar5 | 职位名称 |
| 6 | nickName | 昵称 | dbc_varchar6 | 显示昵称 |
| 7 | languageCode | 语言编码 | dbc_varchar7 | 如 zh_CN / en_US |
| 8 | timezone | 时区 | dbc_varchar8 | 如 Asia/Shanghai |
| 9 | telephone | 办公电话 | dbc_varchar9 | 座机号 |
| 10 | — | 预留 | dbc_varchar10 | 租户自定义 |

### bigint 类型（7 个使用 + 1 个预留）

| # | apiKey | label | db_column | 说明 |
|---|--------|-------|-----------|------|
| 1 | joinAt | 入职日期 | dbc_bigint1 | 毫秒时间戳 |
| 2 | birthday | 出生日期 | dbc_bigint2 | 毫秒时间戳 |
| 3 | rankId | 职级 | dbc_bigint3 | 关联职级表 |
| 4 | dimArea | 所属区域 | dbc_bigint4 | 维度表 ID |
| 5 | dimBusiness | 所属业务 | dbc_bigint5 | 维度表 ID |
| 6 | dimProduct | 所属产品线 | dbc_bigint6 | 维度表 ID |
| 7 | dimIndustry | 所属行业 | dbc_bigint7 | 维度表 ID |
| 8 | lastestLoginAt | 最近登录时间 | dbc_bigint8 | 毫秒时间戳 |
| 9 | — | 预留 | dbc_bigint9 | 租户自定义 |
| 10 | — | 预留 | dbc_bigint10 | 租户自定义 |

### smallint 类型（1 个使用 + 1 个预留）

| # | apiKey | label | db_column | 说明 |
|---|--------|-------|-----------|------|
| 1 | isVirtual | 是否虚拟用户 | dbc_smallint1 | 0=否 1=是 |
| 2 | — | 预留 | dbc_smallint2 | 租户自定义 |

### textarea 类型（1 个使用 + 1 个预留）

| # | apiKey | label | db_column | 说明 |
|---|--------|-------|-----------|------|
| 1 | selfIntro | 自我介绍 | dbc_textarea1 | 长文本 |
| 2 | — | 预留 | dbc_textarea2 | 租户自定义 |

### decimal / array 类型（仅预留）

| # | db_column | 说明 |
|---|-----------|------|
| 1 | dbc_decimal1 | 预留 |
| 2 | dbc_array1 | 预留（VARCHAR(300)[]） |

## 移除的字段（共 35 个）

### 与固定列重复（6 个）
- passwordRuleId → pwd_rule_id
- managerId(dbc) → manager_id
- passportId(dbc) → passport_id
- icon → avatar_url
- superflag → user_type
- currency → currency_unit

### 老系统遗留无用（18 个）
- im (QQ/MSN)、hometown、extNo、areaCode、postCode、location
- mobileLocationJson、mobileLocationStatus
- spaceId、maxAccept、skillValue
- hiddenYearFlg、initiativeFlag、freshGuideStatus
- colleagueRelationDepart
- relatedArea、relatedBusiness、relatedProduct、relatedIndustry（与 dim* 重复）
- personalEmail（与 email 固定列重复）

### 分隔线字段（5 个）
- baseInfoLine、langAndTimeZoneInfoLine、dimInfoLine、businessInfoLine、otherInfoLine

### 其他（2 个）
- expertise（业务专长，低频）
- hobby（兴趣爱好，低频）

## 精简后的 p_user 建表 DDL

```sql
-- p_user 精简版（19 公共字段 + 18 用户固定列 + 精简 dbc 扩展列）
CREATE TABLE IF NOT EXISTS p_user (
    -- 19 个公共字段（与 p_tenant_data 同构）
    id                  BIGINT          NOT NULL,
    tenant_id           BIGINT          NOT NULL,
    entity_api_key      VARCHAR(100)    NOT NULL DEFAULT 'user',
    name                VARCHAR(300),
    owner_id            BIGINT,
    depart_api_key      VARCHAR(255),
    busitype_api_key    VARCHAR(100),
    applicant_id        BIGINT,
    delete_flg          SMALLINT        DEFAULT 0,
    created_at          BIGINT,
    created_by          BIGINT,
    updated_at          BIGINT,
    updated_by          BIGINT,
    lock_status         INTEGER         DEFAULT 1,
    approval_status     INTEGER,
    workflow_stage      VARCHAR(255),
    currency_unit       INTEGER,
    currency_rate       DECIMAL(20,4),
    territory_id        BIGINT,

    -- 用户业务固定列（18 个）
    phone               VARCHAR(50)     NOT NULL,
    email               VARCHAR(255),
    passport_id         BIGINT,
    status              SMALLINT        DEFAULT 1,
    user_type           SMALLINT        DEFAULT 0,
    avatar_url          VARCHAR(500),
    manager_id          BIGINT,
    position            VARCHAR(255),
    lock_auth_status    SMALLINT        DEFAULT 0,
    pwd_rule_id         BIGINT,
    pwd_expire_at       BIGINT,
    pwd_updated_at      BIGINT,
    login_try_times     SMALLINT        DEFAULT 0,
    login_lock_time     BIGINT,
    reset_pwd_flg       SMALLINT        DEFAULT 0,
    api_access_token    VARCHAR(255),
    security_token      VARCHAR(255),
    open_id             VARCHAR(255),

    -- dbc 扩展列（精简版：varchar×10 + bigint×10 + smallint×2 + decimal×1 + textarea×2 + array×1 = 26 列）
    dbc_varchar1  VARCHAR(300),  -- alias 别名
    dbc_varchar2  VARCHAR(300),  -- employeeCode 员工编号
    dbc_varchar3  VARCHAR(300),  -- unionId 唯一标识
    dbc_varchar4  VARCHAR(300),  -- enterpriseWechatAccount 企业微信账号
    dbc_varchar5  VARCHAR(300),  -- positionName 职位
    dbc_varchar6  VARCHAR(300),  -- nickName 昵称
    dbc_varchar7  VARCHAR(300),  -- languageCode 语言编码
    dbc_varchar8  VARCHAR(300),  -- timezone 时区
    dbc_varchar9  VARCHAR(300),  -- telephone 办公电话
    dbc_varchar10 VARCHAR(300),  -- 预留
    dbc_bigint1   BIGINT,        -- joinAt 入职日期
    dbc_bigint2   BIGINT,        -- birthday 出生日期
    dbc_bigint3   BIGINT,        -- rankId 职级
    dbc_bigint4   BIGINT,        -- dimArea 所属区域
    dbc_bigint5   BIGINT,        -- dimBusiness 所属业务
    dbc_bigint6   BIGINT,        -- dimProduct 所属产品线
    dbc_bigint7   BIGINT,        -- dimIndustry 所属行业
    dbc_bigint8   BIGINT,        -- lastestLoginAt 最近登录时间
    dbc_bigint9   BIGINT,        -- 预留
    dbc_bigint10  BIGINT,        -- 预留
    dbc_smallint1 SMALLINT,      -- isVirtual 是否虚拟用户
    dbc_smallint2 SMALLINT,      -- 预留
    dbc_decimal1  DECIMAL(20,4), -- 预留
    dbc_textarea1 TEXT,           -- selfIntro 自我介绍
    dbc_textarea2 TEXT,           -- 预留
    dbc_array1    VARCHAR(300)[],   -- 预留

    PRIMARY KEY (id)
);

-- 索引（与原表一致）
CREATE INDEX IF NOT EXISTS idx_puser_tid ON p_user (tenant_id);
CREATE INDEX IF NOT EXISTS idx_puser_tid_status ON p_user (tenant_id, status);
CREATE INDEX IF NOT EXISTS idx_puser_passport ON p_user (passport_id);
CREATE INDEX IF NOT EXISTS idx_puser_tid_dept ON p_user (tenant_id, depart_api_key);
CREATE INDEX IF NOT EXISTS idx_puser_tid_mgr ON p_user (tenant_id, manager_id);
CREATE INDEX IF NOT EXISTS idx_puser_owner ON p_user (owner_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_puser_tid_phone ON p_user (tenant_id, phone);
CREATE INDEX IF NOT EXISTS idx_puser_tid_email ON p_user (tenant_id, email);
CREATE INDEX IF NOT EXISTS idx_puser_tid_openid ON p_user (tenant_id, open_id);
CREATE INDEX IF NOT EXISTS idx_puser_tid_updated ON p_user (tenant_id, updated_at);
```

## 列数对比

| 类别 | 原表 | 精简后 | 减少 |
|------|------|--------|------|
| varchar | 50 | 10 | -40 |
| bigint | 30 | 10 | -20 |
| decimal | 10 | 1 | -9 |
| smallint | 10 | 2 | -8 |
| textarea | 5 | 2 | -3 |
| array(VARCHAR(300)[]) | 5 | 1 | -4 |
| **dbc 总计** | **110** | **26** | **-84** |

## 数据迁移 SQL（列号重映射）

```sql
-- 在新表结构上执行数据迁移（假设已 ALTER TABLE 或重建表）
-- 旧列 → 新列的映射关系：
UPDATE p_user SET
    dbc_varchar1  = old.dbc_varchar3,   -- alias
    dbc_varchar2  = old.dbc_varchar5,   -- employeeCode
    dbc_varchar3  = old.dbc_varchar6,   -- unionId
    dbc_varchar4  = old.dbc_varchar8,   -- enterpriseWechatAccount
    dbc_varchar5  = old.dbc_varchar10,  -- positionName
    dbc_varchar6  = old.dbc_varchar22,  -- nickName
    dbc_varchar7  = old.dbc_varchar12,  -- languageCode
    dbc_varchar8  = old.dbc_varchar13,  -- timezone
    dbc_varchar9  = old.dbc_varchar26,  -- telephone
    dbc_bigint1   = old.dbc_bigint4,    -- joinAt
    dbc_bigint2   = old.dbc_bigint5,    -- birthday
    dbc_bigint3   = old.dbc_bigint6,    -- rankId
    dbc_bigint4   = old.dbc_bigint8,    -- dimArea
    dbc_bigint5   = old.dbc_bigint9,    -- dimBusiness
    dbc_bigint6   = old.dbc_bigint10,   -- dimProduct
    dbc_bigint7   = old.dbc_bigint11,   -- dimIndustry
    dbc_bigint8   = old.dbc_bigint16,   -- lastestLoginAt
    dbc_smallint1 = old.dbc_smallint4,  -- isVirtual
    dbc_textarea1 = old.dbc_textarea6;  -- selfIntro
-- 注意：需要同步更新 p_meta_item / p_custom_item 中的 db_column 映射
```
