# lead（线索）字段元数据设计 V2

> 日期：2026-04-28
> 基于 lead-fields.md（V1）修正，严格遵循 ItemTypeEnum 规范
> 修正内容：dbc_int 列迁移到合法列、新增公海关联字段、类型规范化

## 设计原则

1. itemType/dataType 严格使用 `ItemTypeEnum` 编码
2. dbColumn 只使用合法前缀：dbc_varchar / dbc_bigint / dbc_decimal / dbc_smallint / dbc_textarea / dbc_array
3. 禁止使用 dbc_int（大宽表无此列类型）
4. 新增线索公海关联字段

## 一、entity 注册

| 属性 | 值 | 说明 |
|---|---|---|
| metamodel_api_key | entity | 元模型标识 |
| api_key | lead | 实体标识 |
| label | 线索 | 显示名称 |
| namespace | system | 系统级实体 |
| entityType (dbc_int1) | 0 | 标准对象 |
| enableFlg (dbc_smallint3) | 1 | 启用 |
| busiTypeFlg (dbc_smallint1) | 1 | 启用业务类型 |
| checkRuleFlg (dbc_smallint2) | 1 | 启用校验规则 |
| duplicateRuleFlg (dbc_int4) | 1 | 启用查重规则 |

## 二、系统公用字段（19 个，CommonFieldProvider 注入）

与 leadHighSea 一致，不再重复。

## 三、业务字段（33 个，item 元数据定义）

存储在 `p_common_metadata`（metamodel_api_key='item', entity_api_key='lead'）。

### 3.1 基本信息（9 个）

| # | apiKey | label | itemType | dataType | dbColumn | 说明 |
|---|--------|-------|----------|----------|----------|------|
| 1 | leadName | 线索名称 | 1(TEXT) | 1(VARCHAR) | name | 主属性 |
| 2 | companyName | 公司名称 | 1(TEXT) | 1(VARCHAR) | dbc_varchar2 | 线索关联的公司 |
| 3 | leadChannel | 来源方式 | 2(SELECT) | 1(VARCHAR) | dbc_varchar1 | 网站/电话/活动等 |
| 4 | leadQuality | 线索质量 | 2(SELECT) | 1(VARCHAR) | dbc_varchar3 | 高/中/低 |
| 5 | bdType | 大数据类型 | 2(SELECT) | 1(VARCHAR) | dbc_varchar4 | 大数据来源分类 |
| 6 | countryId | 省份 | 2(SELECT) | 1(VARCHAR) | dbc_varchar5 | 级联地址-省 |
| 7 | phone | 电话 | 22(PHONE) | 1(VARCHAR) | dbc_varchar6 | 联系电话 |
| 8 | email | 邮箱 | 23(EMAIL) | 1(VARCHAR) | dbc_varchar7 | 联系邮箱 |
| 9 | releaseDefinition | 退回原因说明 | 1(TEXT) | 1(VARCHAR) | dbc_varchar8 | 退回公海的原因 |

### 3.2 关联字段（5 个）

| # | apiKey | label | itemType | dataType | dbColumn | referEntityApiKey | 说明 |
|---|--------|-------|----------|----------|----------|-------------------|------|
| 10 | leadSourceId | 线索来源 | 10(REFER) | 3(BIGINT) | dbc_bigint1 | — | 来源渠道 |
| 11 | opportunityId | 转化商机 | 10(REFER) | 3(BIGINT) | dbc_bigint2 | opportunity | 转化后的商机 |
| 12 | contactId | 联系人 | 10(REFER) | 3(BIGINT) | dbc_bigint3 | contact | 关联联系人 |
| 13 | lastOwnerId | 最后所有人 | 10(REFER) | 3(BIGINT) | dbc_bigint4 | user | 退回前的所有人 |
| 14 | leadHighSeaId | 所属线索公海 | 10(REFER) | 3(BIGINT) | dbc_bigint5 | leadHighSea | 关联线索公海池 |

### 3.3 公海状态字段（5 个）

| # | apiKey | label | itemType | dataType | dbColumn | 说明 |
|---|--------|-------|----------|----------|----------|------|
| 15 | leadHighSeaStatus | 公海状态 | 2(SELECT) | 1(VARCHAR) | dbc_varchar9 | active/inHighSea/claimed/converted/invalid |
| 16 | claimTime | 认领日期 | 7(DATE) | 3(BIGINT) | dbc_bigint6 | 从公海认领的时间 |
| 17 | expireTime | 到期时间 | 7(DATE) | 3(BIGINT) | dbc_bigint7 | 公海到期时间 |
| 18 | releaseTime | 退回时间 | 7(DATE) | 3(BIGINT) | dbc_bigint8 | 退回公海时间 |
| 19 | thawTime | 解冻时间 | 7(DATE) | 3(BIGINT) | dbc_bigint9 | 公海解冻时间 |

### 3.4 数值字段（5 个）

| # | apiKey | label | itemType | dataType | dbColumn | 说明 |
|---|--------|-------|----------|----------|----------|------|
| 20 | leadScore | 线索得分 | 5(NUMBER) | 3(BIGINT) | dbc_bigint10 | 线索评分 |
| 21 | releaseNum | 退回次数 | 5(NUMBER) | 3(BIGINT) | dbc_bigint11 | 累计退回次数 |
| 22 | returnTimes | 总退回次数 | 5(NUMBER) | 3(BIGINT) | dbc_bigint12 | 总退回次数 |
| 23 | statusUpdatedAt | 状态更新时间 | 38(DATETIME) | 3(BIGINT) | dbc_bigint13 | 最近状态变更时间 |
| 24 | applyDelayTime | 延期时间 | 7(DATE) | 3(BIGINT) | dbc_bigint14 | 申请延期的时间 |

### 3.5 广告投放字段（7 个）

| # | apiKey | label | itemType | dataType | dbColumn | 说明 |
|---|--------|-------|----------|----------|----------|------|
| 25 | adPlanName | 广告计划名称 | 1(TEXT) | 1(VARCHAR) | dbc_varchar10 | 广告投放计划 |
| 26 | adPlatform | 广告投放平台 | 1(TEXT) | 1(VARCHAR) | dbc_varchar11 | 百度/头条等 |
| 27 | adSource | 广告投放来源 | 1(TEXT) | 1(VARCHAR) | dbc_varchar12 | 广告来源标识 |
| 28 | adDmpLeadId | 广告线索ID | 1(TEXT) | 1(VARCHAR) | dbc_varchar13 | DMP 平台线索 ID |
| 29 | adProjectName | 项目名称 | 1(TEXT) | 1(VARCHAR) | dbc_varchar14 | 广告项目名称 |
| 30 | adRetentionTime | 广告留资时间 | 38(DATETIME) | 3(BIGINT) | dbc_bigint15 | 用户留资时间 |
| 31 | phoneLocation | 手机号归属地 | 1(TEXT) | 1(VARCHAR) | dbc_varchar15 | 手机号归属地 |

### 3.6 扩展字段（2 个）

| # | apiKey | label | itemType | dataType | dbColumn | 说明 |
|---|--------|-------|----------|----------|----------|------|
| 32 | scoreDetail | 线索得分分析 | 4(TEXTAREA) | 5(TEXT) | dbc_textarea1 | 评分明细 JSON |
| 33 | releaseReason | 退回原因 | 2(SELECT) | 1(VARCHAR) | dbc_varchar16 | 退回原因编码 |

## 四、dbc 列分配汇总

| 前缀 | 已用 | 列号 |
|---|---|---|
| dbc_varchar | 16 | 1~16（跳过 name 固定列） |
| dbc_bigint | 15 | 1~15 |
| dbc_smallint | 0 | — |
| dbc_decimal | 0 | — |
| dbc_textarea | 1 | 1 |
| dbc_array | 0 | — |

## 五、pickOption 定义

### leadChannel 选项

| apiKey | label |
|---|---|
| opt_website | 网站注册 |
| opt_phone | 电话咨询 |
| opt_campaign | 市场活动 |
| opt_referral | 转介绍 |
| opt_ad | 广告投放 |
| opt_social | 社交媒体 |
| opt_other | 其他 |

### leadQuality 选项

| apiKey | label |
|---|---|
| opt_high | 高 |
| opt_medium | 中 |
| opt_low | 低 |

### leadHighSeaStatus 选项

| apiKey | label | 说明 |
|---|---|---|
| active | 活跃 | 新建/已分配，正常跟进中 |
| inHighSea | 公海中 | 在公海池等待领取 |
| claimed | 已领取 | 从公海领取，跟进中 |
| converted | 已转化 | L2O 转化为客户+商机 |
| invalid | 无效 | 标记为无效线索 |

### releaseReason 选项

| apiKey | label |
|---|---|
| opt_no_response | 无回应 |
| opt_no_demand | 无需求 |
| opt_wrong_contact | 联系方式错误 |
| opt_duplicate | 重复线索 |
| opt_other_reason | 其他原因 |

## 六、entityLink 定义

| apiKey | label | parent | child | referItemApiKey | cascadeDelete |
|---|---|---|---|---|---|
| leadHighSea_to_lead | 公海线索 | leadHighSea | lead | leadHighSeaId | 0(不级联) |
| lead_to_opportunity | 转化商机 | lead | opportunity | opportunityId | 0(不级联) |
| lead_to_contact | 转化联系人 | lead | contact | contactId | 0(不级联) |

## 七、V1 → V2 变更记录

| 字段 | V1 | V2 | 变更 |
|---|---|---|---|
| leadChannel | dbc_int7 | dbc_varchar1 | dbc_int 不存在，迁移到 varchar |
| leadQuality | dbc_int10 | dbc_varchar3 | 同上 |
| bdType | dbc_int11 | dbc_varchar4 | 同上 |
| leadSourceId | dbc_bigint4 | dbc_bigint1 | 列号重新分配 |
| opportunityId | dbc_bigint22 | dbc_bigint2 | 列号重新分配 |
| contactId | dbc_bigint27 | dbc_bigint3 | 列号重新分配 |
| leadHighSeaId | — | dbc_bigint5 | 新增 |
| leadHighSeaStatus | — | dbc_varchar9 | 新增 |
| claimTime | — | dbc_bigint6 | 新增 |
| expireTime | — | dbc_bigint7 | 新增 |
| releaseTime | — | dbc_bigint8 | 新增 |
| thawTime | — | dbc_bigint9 | 新增 |
| phone | — | dbc_varchar6 | 新增 |
| email | — | dbc_varchar7 | 新增 |
| releaseReason | dbc_bigint31 | dbc_varchar16 | 类型修正：整数→单选 |

## 八、统计

| 分类 | 数量 |
|---|---|
| 系统公用字段 | 19 |
| 基本信息 | 9 |
| 关联字段 | 5 |
| 公海状态字段 | 5 |
| 数值字段 | 5 |
| 广告投放字段 | 7 |
| 扩展字段 | 2 |
| **合计** | **52**（19 公用 + 33 业务） |
