# lead（销售线索）字段元数据定义

基于 CRM 线索管理业务语义，对 lead 实体的字段进行标准化定义。

> ⚠ 注意：Tenant 级数据中 `entity_api_key='lead'` 的记录实际混入了 product（产品）的字段，
> 属于老系统迁移数据质量问题。以下清单以 Common 级数据为准，Tenant 中的产品字段已排除。

## 统计

| 分类 | 数量 |
|---|---|
| 标准字段（含公用） | 19 |
| 线索业务字段 | 26 |
| **合计** | **45** |

## 系统公用字段（19 个）

| # | apiKey | 标签 | 类型 | 存储 | 数据库列 |
|---|--------|------|------|------|---------|
| 1 | id | 记录ID | 整数(5) | BIGINT | id |
| 2 | name | 名称 | 文本(1) | VARCHAR | name |
| 3 | ownerId | 所有人 | 整数(5) | BIGINT | owner_id |
| 4 | departId | 所属部门 | 整数(5) | BIGINT | depart_id |
| 5 | busitypeApiKey | 业务类型 | 单选(2) | VARCHAR | busitype_api_key |
| 6 | applicantId | 审批提交人 | 整数(5) | BIGINT | applicant_id |
| 7 | approvalStatus | 审批状态 | 单选(2) | INT | approval_status |
| 8 | lockStatus | 锁定状态 | 单选(2) | INT | lock_status |
| 9 | createdAt | 创建时间 | 日期(3) | BIGINT | created_at |
| 10 | createdBy | 创建人 | 整数(5) | BIGINT | created_by |
| 11 | updatedAt | 修改时间 | 日期(3) | BIGINT | updated_at |
| 12 | updatedBy | 修改人 | 整数(5) | BIGINT | updated_by |
| 13 | deleteFlg | 删除标记 | 布尔(31) | SMALLINT | delete_flg |
| 14 | entityApiKey | 对象类型 | 文本(1) | VARCHAR | entity_api_key |
| 15 | tenantId | 租户ID | 整数(5) | BIGINT | tenant_id |
| 16 | workflowStage | 工作流阶段 | 文本(1) | VARCHAR | workflow_stage |
| 17 | currencyUnit | 币种 | 单选(2) | INT | currency_unit |
| 18 | currencyRate | 汇率 | 实数(6) | DECIMAL | currency_rate |
| 19 | territoryId | 区域 | 整数(5) | BIGINT | territory_id |

## 线索业务字段（26 个）

| # | apiKey | 标签 | 类型 | 存储 | 数据库列 | 业务说明 |
|---|--------|------|------|------|---------|---------|
| 1 | companyName | 公司名称 | 文本(1) | VARCHAR | dbc_varchar2 | 线索关联的公司名称 |
| 2 | leadSourceId | 线索来源 | 整数(5) | BIGINT | dbc_bigint4 | 线索来源渠道 ID |
| 3 | leadChannel | 来源方式 | 单选(2) | VARCHAR | dbc_int7 | 获取方式（网站/电话/活动等） |
| 4 | leadQuality | 线索质量 | 单选(2) | VARCHAR | dbc_int10 | 质量评级（高/中/低） |
| 5 | leadScore | 线索得分 | 整数(5) | BIGINT | dbc_bigint18 | 线索评分 |
| 6 | bdType | 大数据类型 | 单选(2) | VARCHAR | dbc_int11 | 大数据来源分类 |
| 7 | countryId | 省份 | 文本(1) | VARCHAR | dbc_varchar13 | 线索所在省份 |
| 8 | opportunityId | 销售机会 | 关联(10) | BIGINT | dbc_bigint22 | 转化后的商机 ID |
| 9 | statusUpdatedAt | 状态更新时间 | 日期(7) | BIGINT | dbc_bigint23 | 最近状态变更时间 |
| 10 | releaseDefinition | 退回原因说明 | 文本(1) | VARCHAR | dbc_varchar15 | 退回公海的原因描述 |
| 11 | applyDelayTime | 延期时间 | 日期(7) | BIGINT | dbc_bigint26 | 申请延期的时间 |
| 12 | contactId | 联系人 | 关联(10) | BIGINT | dbc_bigint27 | 关联联系人 ID |
| 13 | releaseNum | 退回公海次数 | 整数(5) | BIGINT | dbc_bigint29 | 累计退回次数 |
| 14 | thawTime | 解冻时间 | 日期(7) | BIGINT | dbc_bigint30 | 公海解冻时间 |
| 15 | releaseReason | 退回原因 | 整数(5) | BIGINT | dbc_bigint31 | 退回原因编码 |
| 16 | releaseTime | 退回时间 | 日期(7) | BIGINT | dbc_bigint32 | 退回公海时间 |
| 17 | lastOwnerId | 最后所有人 | 关联(10) | BIGINT | dbc_bigint33 | 退回前的所有人 |
| 18 | returnTimes | 退回次数 | 整数(5) | BIGINT | dbc_bigint34 | 总退回次数 |
| 19 | scoreDetail | 线索得分分析 | 文本域(4) | TEXT | dbc_textarea2 | 评分明细（JSON） |
| 20 | adPlanName | 广告计划名称 | 文本(1) | VARCHAR | dbc_varchar18 | 广告投放计划 |
| 21 | adPlatform | 广告投放平台 | 文本(1) | VARCHAR | dbc_varchar19 | 投放平台（百度/头条等） |
| 22 | adSource | 广告投放来源 | 文本(1) | VARCHAR | dbc_varchar20 | 广告来源标识 |
| 23 | adDmpLeadId | 广告线索id | 文本(1) | VARCHAR | dbc_varchar17 | DMP 平台线索 ID |
| 24 | adRetentionTime | 广告留资时间 | 日期(7) | BIGINT | dbc_bigint35 | 用户留资时间 |
| 25 | adProjectName | 项目名称 | 文本(1) | VARCHAR | dbc_varchar21 | 广告项目名称 |
| 26 | phoneLocation | 手机号归属地 | 文本(1) | VARCHAR | dbc_varchar23 | 手机号归属地 |
