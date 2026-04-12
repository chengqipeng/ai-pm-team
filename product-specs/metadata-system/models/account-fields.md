# account（客户）字段元数据定义

基于 CRM 客户管理业务语义，对 account 实体的字段进行标准化定义。
已移除布局行（itemType=8）和维度（itemType=99）等非业务字段。

## 字段类型编码说明

| 编码 | 类型 | 存储 | 说明 |
|---|---|---|---|
| 1 | 文本 | VARCHAR | 短文本输入 |
| 2 | 单选 | VARCHAR | 下拉单选（存 apiKey） |
| 3 | 日期 | BIGINT | 日期/日期时间（毫秒时间戳） |
| 4 | 文本域 | TEXT | 长文本/多行文本 |
| 5 | 整数/引用 | BIGINT | 整数值或关联引用 ID |
| 6 | 实数 | DECIMAL | 货币/金额/小数 |
| 9 | 布尔 | VARCHAR | 是/否开关 |
| 10 | 关联 | BIGINT | 查找关联（Lookup） |
| 11 | 整数 | BIGINT | 老系统整数编码 |
| 13 | 电话 | VARCHAR | 电话号码 |
| 15 | 日期时间 | BIGINT | 老系统日期时间编码 |
| 16 | 多选标签 | VARCHAR | 多选标签 |
| 27 | 计算 | - | 公式计算字段 |
| 31 | 布尔 | SMALLINT | 布尔开关 0/1 |
| 33 | 百分比 | DECIMAL | 百分比值 |
| 38 | 时间 | BIGINT | 精确时间戳 |

## 一、系统公用字段（19 个）

所有 entity 共享的固定列字段，由 `CommonFieldProvider` 注入。

| # | apiKey | 标签 | 类型 | 存储 | 数据库列 | 说明 |
|---|--------|------|------|------|---------|------|
| 1 | id | 记录ID | 整数(5) | BIGINT | id | 雪花算法主键 |
| 2 | name | 名称 | 文本(1) | VARCHAR | name | 记录名称 |
| 3 | ownerId | 所有人 | 整数(5) | BIGINT | owner_id | 数据所有人 |
| 4 | departId | 所属部门 | 整数(5) | BIGINT | depart_id | 所属部门 |
| 5 | busitypeApiKey | 业务类型 | 单选(2) | VARCHAR | busitype_api_key | 记录类型 |
| 6 | applicantId | 审批提交人 | 整数(5) | BIGINT | applicant_id | 审批流提交人 |
| 7 | approvalStatus | 审批状态 | 单选(2) | INT | approval_status | 审批流状态 |
| 8 | lockStatus | 锁定状态 | 单选(2) | INT | lock_status | 记录锁定状态 |
| 9 | createdAt | 创建时间 | 日期(3) | BIGINT | created_at | 创建时间戳 |
| 10 | createdBy | 创建人 | 整数(5) | BIGINT | created_by | 创建人 ID |
| 11 | updatedAt | 修改时间 | 日期(3) | BIGINT | updated_at | 最后修改时间戳 |
| 12 | updatedBy | 修改人 | 整数(5) | BIGINT | updated_by | 最后修改人 ID |
| 13 | deleteFlg | 删除标记 | 布尔(31) | SMALLINT | delete_flg | 软删除 0/1 |
| 14 | entityApiKey | 对象类型 | 文本(1) | VARCHAR | entity_api_key | 所属对象标识 |
| 15 | tenantId | 租户ID | 整数(5) | BIGINT | tenant_id | 租户隔离 |
| 16 | workflowStage | 工作流阶段 | 文本(1) | VARCHAR | workflow_stage | 当前工作流阶段 |
| 17 | currencyUnit | 币种 | 单选(2) | INT | currency_unit | 币种编码 |
| 18 | currencyRate | 汇率 | 实数(6) | DECIMAL | currency_rate | 汇率 |
| 19 | territoryId | 区域 | 整数(5) | BIGINT | territory_id | 所属销售区域 |

## 二、基本信息

| # | apiKey | 标签 | 类型 | 存储 | 数据库列 | 业务说明 |
|---|--------|------|------|------|---------|---------|
| 20 | entityType | 客户类型 | 整数(5) | BIGINT | dbc_bigint5 | 客户分类：个人/企业/渠道等 |
| 21 | accountName | 客户名称 | 文本(1) | VARCHAR | name | 客户全称（映射到固定列 name） |
| 22 | level | 客户级别 | 文本域(4) | TEXT | dbc_varchar3 | 客户等级：A/B/C/D |
| 23 | parentAccountId | 上级客户 | 整数(5) | BIGINT | dbc_bigint3 | 上级客户关联 ID |
| 24 | industryId | 行业 | 文本域(4) | TEXT | dbc_varchar15 | 所属行业 |

## 三、联系信息

| # | apiKey | 标签 | 类型 | 存储 | 数据库列 | 业务说明 |
|---|--------|------|------|------|---------|---------|
| 25 | fState | 省份 | 文本域(4) | TEXT | dbc_varchar16 | 省份（级联地址） |
| 26 | fCity | 市 | 文本域(4) | TEXT | dbc_varchar17 | 城市（级联地址） |
| 27 | fDistrict | 区 | 文本域(4) | TEXT | dbc_varchar18 | 区县（级联地址） |
| 28 | longitude | 经度 | 关联(10) | BIGINT | dbc_bigint7 | GPS 经度 |
| 29 | latitude | 纬度 | 关联(10) | BIGINT | dbc_bigint9 | GPS 纬度 |
| 30 | address | 详细地址 | 文本(1) | VARCHAR | dbc_varchar4 | 详细街道地址 |
| 31 | zipCode | 邮政编码 | 文本(1) | VARCHAR | dbc_varchar5 | 邮编 |
| 32 | phone | 电话 | 电话(13) | VARCHAR | dbc_varchar6 | 公司电话 |
| 33 | fax | 传真 | 文本(1) | VARCHAR | dbc_varchar8 | 传真号码 |
| 34 | url | 公司网址 | 文本(1) | VARCHAR | dbc_varchar7 | 公司官网 URL |
| 35 | weibo | 微博 | 文本(1) | VARCHAR | dbc_varchar9 | 微博账号 |

## 四、业务信息

| # | apiKey | 标签 | 类型 | 存储 | 数据库列 | 业务说明 |
|---|--------|------|------|------|---------|---------|
| 36 | employeeNumber | 总人数 | 单选(2) | VARCHAR | dbc_bigint4 | 公司员工规模 |
| 37 | annualRevenue | 销售额 | 关联(10) | BIGINT | dbc_decimal3 | 年销售额 |
| 38 | accountChannel | 来源方式 | 单选(2) | VARCHAR | dbc_varchar20 | 客户获取渠道 |
| 39 | recentActivityRecordTime | 最新活动记录时间 | 日期(3) | VARCHAR | dbc_varchar11 | 最近一次活动时间 |
| 40 | recentActivityCreatedBy | 最新跟进人 | 整数(5) | BIGINT | dbc_bigint6 | 最近跟进人 ID |
| 41 | loss | 是否为流失好友 | 单选(2) | VARCHAR | dbc_varchar19 | 客户流失标记 |
| 42 | srcFlg | 工商注册 | 文本域(4) | TEXT | dbc_varchar10 | 工商注册信息来源 |
| 43 | score | 客户分值 | 单选(2) | VARCHAR | dbc_bigint19 | 客户评分等级 |
| 44 | releaseDescription | 退回公海描述 | 文本(1) | VARCHAR | dbc_varchar13 | 退回公海的原因描述 |
| 45 | vipFlag | VIP标识 | 单选(2) | VARCHAR | dbc_varchar14 | VIP 客户标记 |
| 46 | doNotDisturb | 免打扰 | 布尔(9) | VARCHAR | dbc_varchar22 | 免打扰开关 |
| 47 | duplicateFlg | 疑似查重 | 布尔(31) | SMALLINT | dbc_smallint3 | 查重标记 |
| 48 | newOppFlg | 是否存在销售机会 | 布尔(9) | VARCHAR | dbc_smallint1 | 是否有关联商机 |
| 49 | dimDepart | 所属部门 | 整数(5) | BIGINT | dbc_bigint10 | 数据权限-部门维度 |
| 50 | outterDepartId | 外部部门 | 关联(10) | BIGINT | dbc_bigint18 | 外部组织部门 |

## 五、公海信息

| # | apiKey | 标签 | 类型 | 存储 | 数据库列 | 业务说明 |
|---|--------|------|------|------|---------|---------|
| 51 | highSeaId | 所属公海 | 整数(5) | BIGINT | dbc_bigint8 | 公海池 ID |
| 52 | highSeaAccountSource | 客户来源 | 日期(3) | VARCHAR | dbc_varchar12 | 公海客户来源渠道 |
| 53 | highSeaStatus | 状态 | 文本域(4) | TEXT | dbc_varchar21 | 公海状态 |
| 54 | claimTime | 认领日期 | 日期(3) | VARCHAR | dbc_bigint11 | 从公海认领的时间 |
| 55 | expireTime | 到期时间 | 日期(3) | VARCHAR | dbc_bigint13 | 公海到期时间 |
| 56 | territoryHighSeaId | 所属区域公海 | 关联(10) | BIGINT | dbc_bigint27 | 区域公海池 ID |

## 六、计算/汇总字段

由公式或汇总规则自动计算，不可手动编辑。

| # | apiKey | 标签 | 类型 | 存储 | 数据库列 | 业务说明 |
|---|--------|------|------|------|---------|---------|
| 57 | accountScore | 客户得分 | 实数(6) | DECIMAL | dbc_decimal22 | 综合评分（公式计算） |
| 58 | totalWonOpportunities | 结单商机数 | 实数(6) | DECIMAL | dbc_decimal2 | 已赢单商机数量 |
| 59 | totalWonOpportunityAmount | 结单商机总金额 | 实数(6) | DECIMAL | dbc_decimal16 | 已赢单商机总金额 |
| 60 | totalActiveOrders | 生效订单数 | 实数(6) | DECIMAL | dbc_decimal17 | 有效订单数量 |
| 61 | totalOrderAmount | 订单总金额 | 实数(6) | DECIMAL | dbc_decimal19 | 订单总金额 |
| 62 | totalContract | 合同数 | 实数(6) | DECIMAL | dbc_decimal18 | 合同数量 |
| 63 | actualInvoicedAmount | 实际应收账金额 | 实数(6) | DECIMAL | dbc_decimal15 | 已开票金额 |
| 64 | paidAmount | 实际收款金额 | 实数(6) | DECIMAL | dbc_decimal12 | 已收款金额 |
| 65 | unpaidAmount | 未收款金额 | 实数(6) | DECIMAL | dbc_decimal13 | 未收款金额 |
| 66 | amountUnbilled | 未出应收账金额 | 实数(6) | DECIMAL | dbc_decimal14 | 未开票金额 |
| 67 | invoiceBalance | 应收余额（欠款） | 实数(6) | DECIMAL | dbc_decimal11 | 应收账款余额 |
| 68 | isCustomer | 是否为结单客户 | 实数(6) | DECIMAL | dbc_decimal10 | 是否有成交记录 |
| 69 | paymentRate | 账户支付比例 | 百分比(33) | DECIMAL | dbc_decimal4 | 回款率 |
| 70 | visitInplanCount | 计划内拜访数 | 实数(6) | DECIMAL | dbc_decimal20 | 计划拜访次数 |
| 71 | visitTotalCount | 拜访总数 | 实数(6) | DECIMAL | dbc_decimal21 | 实际拜访总次数 |
| 72 | visitLatestTime | 最近拜访时间 | 日期时间(15) | BIGINT | dbc_bigint21 | 最近一次拜访时间 |
| 73 | visitUnvisitDay | 未拜访天数 | 单选(2) | VARCHAR | dbc_bigint22 | 距上次拜访天数 |
| 74 | activeDays | 活跃天数 | 实数(6) | DECIMAL | dbc_bigint35 | 客户活跃天数 |

## 七、AI/数据分析字段

系统自动生成的分析标签，用于客户画像和智能推荐。

| # | apiKey | 标签 | 类型 | 存储 | 数据库列 | 业务说明 |
|---|--------|------|------|------|---------|---------|
| 75 | gradeLabel | 客户等级标签 | 实数(6) | DECIMAL | dbc_varchar23 | AI 生成的等级标签 |
| 76 | nameInitial | 名称首字母 | 实数(6) | DECIMAL | dbc_varchar24 | 名称首字母索引 |
| 77 | valueScore | 客户价值评分 | 实数(6) | DECIMAL | dbc_decimal7 | AI 价值评分 |
| 78 | paymentHealthPct | 应收健康度 | 实数(6) | DECIMAL | dbc_decimal8 | 应收账款健康度 |
| 79 | avgOrderAmount | 订单均价 | 实数(6) | DECIMAL | dbc_decimal9 | 平均订单金额 |
| 80 | nameLenCategory | 名称长度分类 | 实数(6) | DECIMAL | dbc_varchar25 | 名称长度分类标签 |
| 81 | wonRatioText | 赢单占比文本 | 实数(6) | DECIMAL | dbc_varchar26 | 赢单率文本描述 |
| 82 | compositeGrade | 综合评级 | 实数(6) | DECIMAL | dbc_varchar27 | 综合评级标签 |
| 83 | processedName | 处理后名称 | 实数(6) | DECIMAL | dbc_varchar28 | 清洗后的标准化名称 |

## 八、自定义字段

租户自定义的扩展字段。

| # | apiKey | 标签 | 类型 | 存储 | 数据库列 | 业务说明 |
|---|--------|------|------|------|---------|---------|
| 84 | customItem153__c | bool | 布尔(9) | VARCHAR | dbc_smallint1 | 自定义布尔字段 |
| 85 | customItem147__c | 百分比 | 整数(11) | BIGINT | dbc_decimal1 | 自定义百分比字段 |
| 86 | customItem148__c | 电话11 | 电话(13) | VARCHAR | dbc_varchar1 | 自定义电话字段 |
| 87 | customItem150__c | 时间 | 日期(3) | VARCHAR | dbc_bigint1 | 自定义时间字段 |
| 88 | customItem151__c | 33 | 文本(1) | VARCHAR | dbc_varchar1 | 自定义文本字段 |
| 89 | customItem154__c | 客户来源 | 多选标签(16) | VARCHAR | dbc_varchar29 | 客户来源多选标签 |
| 90 | ecouponsAccountLabel | 促销场景标签 | 多选标签(16) | VARCHAR | dbc_varchar30 | 促销场景多选标签 |
| 91 | customItem172__c | 用户 | 整数(5) | BIGINT | dbc_bigint1 | 自定义用户关联 |
| 92 | customItem32__c | 用户32 | 整数(5) | BIGINT | dbc_bigint2 | 自定义用户关联 |
| 93 | customItem181__c | 关联的拜访记录 | 整数(5) | BIGINT | dbc_bigint3 | 关联拜访记录 ID |
| 94 | registrationUtmId | 关联UTM | 整数(5) | BIGINT | dbc_bigint30 | UTM 来源追踪 |
| 95 | leadId | 销售线索 | 整数(5) | BIGINT | dbc_bigint12 | 关联的销售线索 |
| 96 | cleanLatestTime | 最近清洗时间 | 时间(38) | BIGINT | dbc_bigint25 | 数据清洗时间 |
| 97 | recentBackfillTime | 最近回填时间 | 时间(38) | BIGINT | dbc_bigint26 | 数据回填时间 |

---

## 统计

| 分类 | 数量 |
|---|---|
| 系统公用字段 | 19 |
| 基本信息 | 5 |
| 联系信息 | 11 |
| 业务信息 | 15 |
| 公海信息 | 6 |
| 计算/汇总字段 | 18 |
| AI/数据分析字段 | 9 |
| 自定义字段 | 14 |
| **合计** | **97** |

> 已移除：3 条 old_old_old_ 废弃字段 + 6 条布局行(type=8) + 4 条维度(type=99) = 共删除 13 条，从 110 条精简为 97 条。
