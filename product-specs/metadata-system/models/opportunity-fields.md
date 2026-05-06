# opportunity（商机）字段元数据定义

基于 CRM 销售管理业务语义，对 opportunity 实体的字段进行标准化定义。

## 统计

| 分类 | 数量 |
|---|---|
| 标准字段 | 48 |
| 产品字段 | 11 |
| 自定义字段 | 7 |
| **合计** | **66** |

## 标准字段（48 个）

### 系统公用字段（19 个）

| # | apiKey | 标签 | 类型 | 存储 | 数据库列 |
|---|--------|------|------|------|---------|
| 1 | id | 记录ID | 整数(5) | BIGINT | id |
| 2 | name | 名称 | 文本(1) | VARCHAR | name |
| 3 | ownerId | 所有人 | 整数(5) | BIGINT | owner_id |
| 4 | departId | 所属部门 | 整数(5) | BIGINT | depart_id |
| 5 | busitypeApiKey | 业务类型 | 单选(2) | VARCHAR | busitype_api_key |
| 6 | applicantId | 审批提交人 | 整数(5) | BIGINT | applicant_id |
| 7 | approvalStatus | 审批状态 | 单选(2) | DECIMAL | approval_status |
| 8 | lockStatus | 锁定状态 | 单选(2) | DECIMAL | lock_status |
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

### 商机核心字段（29 个）

| # | apiKey | 标签 | 类型 | 存储 | 数据库列 | 业务说明 |
|---|--------|------|------|------|---------|---------|
| 20 | opportunityName | 机会名称 | 文本(1) | VARCHAR | name | 商机名称（映射到固定列 name） |
| 21 | opportunityType | 机会类型 | 单选(2) | VARCHAR | dbc_varchar9 | 新建/续约/增购等 | <!-- 修正：文本域→单选, dbc_int1→dbc_varchar9 2026-04-28 -->
| 22 | money | 销售金额 | 实数(6) | DECIMAL | dbc_decimal1 | 预计成交金额 | <!-- 修正：关联→实数 2026-04-28 -->
| 23 | saleStageId | 销售阶段 | 整数(5) | BIGINT | dbc_bigint6 | 当前销售阶段 |
| 24 | lostStageId | 输单阶段 | 整数(5) | BIGINT | dbc_bigint5 | 输单时所在阶段 |
| 25 | winRate | 赢率 | 单选(2) | VARCHAR | dbc_varchar6 | 预计赢单概率 | <!-- 修正：dbc_bigint7→dbc_varchar6 2026-04-28 -->
| 26 | reason | 输单原因 | 单选(2) | VARCHAR | dbc_varchar1 | 输单原因分类 | <!-- 修正：文本域→单选 2026-04-28 -->
| 27 | winReason | 赢单原因 | 单选(2) | VARCHAR | dbc_varchar10 | 赢单原因分类 | <!-- 修正：文本域→单选, dbc_int8→dbc_varchar10 2026-04-28 -->
| 28 | closeDate | 结单日期 | 日期(7) | BIGINT | dbc_bigint8 | 预计/实际结单日期 | <!-- 修正：dataType VARCHAR→BIGINT 2026-04-28 -->
| 29 | commitmentFlg | 承诺 | 布尔(31) | SMALLINT | dbc_smallint2 | 是否承诺成交 | <!-- 修正：文本域→布尔, dbc_int3→dbc_smallint2 2026-04-28 -->
| 30 | status | 状态 | 单选(2) | VARCHAR | dbc_varchar3 | 商机状态 | <!-- 修正：文本域→单选 2026-04-28 -->
| 31 | forecastCategory | 阶段分类 | 单选(2) | VARCHAR | dbc_varchar11 | 预测分类 | <!-- 修正：文本域→单选, dbc_int7→dbc_varchar11 2026-04-28 -->
| 32 | stageUpdatedAt | 阶段更新时间 | 时间(38) | BIGINT | dbc_bigint11 | 最近阶段变更时间 | <!-- 修正：dataType VARCHAR→BIGINT 2026-04-28 -->
| 33 | priceId | 价格表名称 | 整数(5) | BIGINT | dbc_bigint3 | 关联价格表 |
| 34 | projectBudget | 项目预算 | 实数(6) | DECIMAL | dbc_decimal2 | 客户项目预算 | <!-- 修正：关联→实数 2026-04-28 -->
| 35 | actualCost | 实际花费 | 实数(6) | DECIMAL | dbc_decimal3 | 实际销售成本 | <!-- 修正：关联→实数 2026-04-28 -->
| 36 | discount | 折扣 | 百分比(33) | DECIMAL | dbc_decimal4 | 折扣率 | <!-- 修正：关联→百分比 2026-04-28 -->
| 37 | campaignContactId | 联系人 | 整数(5) | BIGINT | dbc_bigint18 | 关联联系人 |
| 38 | campaignId | 市场活动 | 整数(5) | BIGINT | dbc_bigint19 | 关联市场活动 |
| 39 | workflowStageName | 工作流阶段名称 | 文本(1) | VARCHAR | dbc_varchar2 | 工作流阶段显示名 |
| 40 | opportunityCode | 机会编号 | 文本(1) | VARCHAR | dbc_varchar5 | 自动编号 |
| 41 | repeatFlg | 重复标志 | 布尔(31) | SMALLINT | dbc_smallint1 | 是否重复商机 | <!-- 修正：单选→布尔, dbc_bigint20→dbc_smallint1 2026-04-28 -->
| 42 | standardPeriod | 标准周期 | 整数(5) | BIGINT | dbc_bigint21 | 标准销售周期 | <!-- 修正：单选→整数 2026-04-28 -->
| 43 | actualPeriod | 实际周期 | 整数(5) | BIGINT | dbc_bigint24 | 实际销售周期 | <!-- 修正：单选→整数 2026-04-28 -->
| 44 | invoiceDate | 开票日期 | 日期(7) | BIGINT | dbc_bigint22 | 开票日期 | <!-- 修正：dataType VARCHAR→BIGINT 2026-04-28 -->
| 45 | paymentDate | 付款日期 | 日期(7) | BIGINT | dbc_bigint23 | 付款日期 | <!-- 修正：dataType VARCHAR→BIGINT 2026-04-28 -->
| 46 | opportunityScore | 商机得分 | 实数(6) | DECIMAL | dbc_decimal6 | 商机评分 |
| 47 | fcastMoney | 预测金额 | 实数(6) | DECIMAL | dbc_decimal7 | 预测成交金额 |
| 48 | roiCiCount | ROI影响力计数 | 实数(6) | DECIMAL | dbc_decimal8 | ROI 影响力指标 |

## 产品字段（11 个）

| # | apiKey | 标签 | 类型 | 存储 | 数据库列 | 业务说明 |
|---|--------|------|------|------|---------|---------|
| 1 | reasonDesc | 输单描述 | 文本域(4) | TEXT | dbc_textarea1 | 输单详细描述 |
| 2 | winReasonDesc | 赢单描述 | 文本域(4) | TEXT | dbc_textarea3 | 赢单详细描述 |
| 3 | sourceId | 机会来源 | 整数(5) | BIGINT | dbc_bigint9 | 商机来源渠道 |
| 4 | oppHealthAssessmentScore | 商机评分 | 实数(6) | DECIMAL | dbc_decimal5 | AI 商机健康度评分 |
| 5 | oppHealthAssessmentLevel | 商机健康度等级 | 单选(2) | VARCHAR | dbc_varchar12 | 健康度等级 | <!-- 修正：dbc_int9→dbc_varchar12 2026-04-28 -->
| 6 | oppHealthAssessmentShow | 商机健康度展示 | 文本(1) | VARCHAR | dbc_varchar8 | 健康度展示文本 |
| 7 | intelligentDuplicateCheckResult | 智能查重结果 | 文本(1) | VARCHAR | dbc_varchar7 | 查重结果 |
| 8 | duplicateCheckExplanation | 查重结果说明 | 文本域(4) | TEXT | dbc_textarea4 | 查重说明 |
| 9 | suspectedOpportunityAnalysis | 疑似商机分析 | 文本域(4) | TEXT | dbc_textarea5 | 疑似重复分析 |
| 10 | duplicateCheckResultTime | 智能查重时间 | 时间(38) | BIGINT | dbc_bigint32 | 查重执行时间 |
| 11 | seemDuplicateRuleId | 疑似查重规则id | 整数(5) | BIGINT | dbc_bigint33 | 匹配的查重规则 |

## 自定义字段（7 个）

| # | apiKey | 标签 | 类型 | 存储 | 数据库列 | 业务说明 |
|---|--------|------|------|------|---------|---------|
| 1 | customItem58__c | 计算-文本58 | 实数(6) | DECIMAL | dbc_decimal9 | 自定义计算字段 |
| 2 | customItem10__c | 计算-文本10 | 实数(6) | DECIMAL | dbc_decimal10 | 自定义计算字段 |
| 3 | customItem17__c | 计算-文本17 | 实数(6) | DECIMAL | dbc_decimal11 | 自定义计算字段 |
| 4 | customItem166__c | 客户 | 整数(5) | BIGINT | dbc_bigint1 | 自定义客户关联 |
| 5 | customItem167__c | ws-日期+时间 | 日期(3) | VARCHAR | dbc_bigint1 | 自定义日期时间 |
| 6 | customItem170__c | 测试123 | 文本(1) | VARCHAR | dbc_varchar4 | 自定义文本 |
| 7 | customItem171__c | 测试444 | 文本(1) | VARCHAR | dbc_varchar5 | 自定义文本 |
