# account（客户）字段元数据设计 V2

基于老系统数据分析 + CRM 业务需求，重新设计的标准化字段清单。

## 设计原则

1. itemType/dataType 严格使用新系统 `ItemTypeEnum` 编码
2. itemSubType = itemType（非计算型），计算型由公式决定
3. dbColumn 按 itemType 对应的 dbc 前缀顺序分配
4. 删除废弃字段、测试字段、无业务价值的字段
5. 自定义字段只保留有明确业务含义的
6. 去除非 CRM 核心的 AI/数据分析字段、过时字段、内部运维字段

## 字段类型编码（新系统 ItemTypeEnum）

| code | 名称 | 存储(dataType) | dbc前缀 |
|---|---|---|---|
| 1 | 文本 | 1(VARCHAR) | dbc_varchar |
| 2 | 单选 | 1(VARCHAR) | dbc_varchar |
| 3 | 多选 | 1(VARCHAR) | dbc_varchar |
| 4 | 文本域 | 5(TEXT) | dbc_textarea |
| 5 | 整数 | 3(BIGINT) | dbc_bigint |
| 6 | 实数/货币 | 4(DECIMAL) | dbc_decimal |
| 7 | 日期 | 3(BIGINT) | dbc_bigint |
| 9 | 自动编号 | 1(VARCHAR) | dbc_varchar |
| 10 | 关联(Lookup) | 3(BIGINT) | dbc_bigint |
| 16 | 多选标签 | 1(VARCHAR) | dbc_varchar |
| 22 | 电话 | 1(VARCHAR) | dbc_varchar |
| 23 | 邮箱 | 1(VARCHAR) | dbc_varchar |
| 24 | 网址 | 1(VARCHAR) | dbc_varchar |
| 27 | 计算(公式) | - | - |
| 29 | 图片 | 1(VARCHAR) | dbc_varchar |
| 31 | 布尔 | 6(SMALLINT) | dbc_smallint |
| 33 | 百分比 | 4(DECIMAL) | dbc_decimal |
| 34 | 多态关联 | 3(BIGINT) | dbc_bigint |
| 38 | 时间 | 3(BIGINT) | dbc_bigint |
| 39 | 文件 | 1(VARCHAR) | dbc_varchar |
| 40 | 富文本 | 5(TEXT) | dbc_textarea |
| 41 | 多值关联 | 3(BIGINT) | dbc_bigint |

---

## 一、系统公用字段（19 个，CommonFieldProvider 注入）

不变，见 [业务数据大宽表设计.md](../业务数据大宽表设计.md) §3.2.1。

## 二、基本信息（8 个）

| # | apiKey | 标签 | itemType | dataType | dbColumn | 说明 |
|---|--------|------|----------|----------|----------|------|
| 1 | accountName | 客户名称 | 1(文本) | 1(VARCHAR) | name | 映射到固定列 |
| 2 | level | 客户级别 | 2(单选) | 1(VARCHAR) | dbc_varchar1 | A/B/C/D 等级 |
| 3 | industryId | 行业 | 2(单选) | 1(VARCHAR) | dbc_varchar2 | 所属行业 |
| 4 | parentAccountId | 上级客户 | 10(关联) | 3(BIGINT) | dbc_bigint1 | 上级客户 Lookup |
| 5 | fState | 省份 | 2(单选) | 1(VARCHAR) | dbc_varchar3 | 级联地址-省 |
| 6 | fCity | 市 | 2(单选) | 1(VARCHAR) | dbc_varchar4 | 级联地址-市 |
| 7 | fDistrict | 区 | 2(单选) | 1(VARCHAR) | dbc_varchar5 | 级联地址-区 |
| 8 | address | 详细地址 | 1(文本) | 1(VARCHAR) | dbc_varchar6 | 街道地址 |

## 三、联系方式（2 个）

| # | apiKey | 标签 | itemType | dataType | dbColumn | 说明 |
|---|--------|------|----------|----------|----------|------|
| 9 | phone | 电话 | 22(电话) | 1(VARCHAR) | dbc_varchar7 | 公司电话 |
| 10 | url | 公司网址 | 24(网址) | 1(VARCHAR) | dbc_varchar8 | 官网 URL |

## 四、业务属性（10 个）

| # | apiKey | 标签 | itemType | dataType | dbColumn | 说明 |
|---|--------|------|----------|----------|----------|------|
| 11 | employeeNumber | 员工规模 | 2(单选) | 1(VARCHAR) | dbc_varchar9 | 1-50/50-200/... |
| 12 | annualRevenue | 年销售额 | 6(实数) | 4(DECIMAL) | dbc_decimal1 | 年营收金额 |
| 13 | accountChannel | 来源方式 | 2(单选) | 1(VARCHAR) | dbc_varchar10 | 获客渠道 |
| 14 | customerSource | 客户来源 | 2(单选) | 1(VARCHAR) | dbc_varchar11 | 客户来源分类 |
| 15 | vipFlag | VIP标识 | 2(单选) | 1(VARCHAR) | dbc_varchar12 | VIP 等级 |
| 16 | doNotDisturb | 免打扰 | 31(布尔) | 6(SMALLINT) | dbc_smallint1 | 免打扰开关 |
| 17 | duplicateFlg | 疑似查重 | 31(布尔) | 6(SMALLINT) | dbc_smallint2 | 查重标记 |
| 18 | score | 客户分值 | 5(整数) | 3(BIGINT) | dbc_bigint2 | 客户评分 |
| 19 | longitude | 经度 | 6(实数) | 4(DECIMAL) | dbc_decimal2 | GPS 经度 |
| 20 | latitude | 纬度 | 6(实数) | 4(DECIMAL) | dbc_decimal3 | GPS 纬度 |

## 五、关联字段（4 个）

| # | apiKey | 标签 | itemType | dataType | dbColumn | 说明 |
|---|--------|------|----------|----------|----------|------|
| 21 | leadId | 销售线索 | 10(关联) | 3(BIGINT) | dbc_bigint3 | 来源线索 |
| 22 | dimDepart | 数据权限部门 | 10(关联) | 3(BIGINT) | dbc_bigint4 | 数据权限维度 |
| 23 | recentActivityCreatedBy | 最新跟进人 | 10(关联) | 3(BIGINT) | dbc_bigint5 | 最近跟进人 |
| 24 | territoryHighSeaId | 所属区域公海 | 10(关联) | 3(BIGINT) | dbc_bigint6 | 区域公海 |

## 六、公海信息（5 个）

| # | apiKey | 标签 | itemType | dataType | dbColumn | 说明 |
|---|--------|------|----------|----------|----------|------|
| 25 | highSeaId | 所属公海 | 10(关联) | 3(BIGINT) | dbc_bigint7 | 公海池 ID |
| 26 | highSeaAccountSource | 公海来源 | 2(单选) | 1(VARCHAR) | dbc_varchar13 | 公海来源渠道 |
| 27 | highSeaStatus | 公海状态 | 2(单选) | 1(VARCHAR) | dbc_varchar14 | 公海状态 |
| 28 | claimTime | 认领日期 | 7(日期) | 3(BIGINT) | dbc_bigint8 | 从公海认领时间 |
| 29 | expireTime | 到期时间 | 7(日期) | 3(BIGINT) | dbc_bigint9 | 公海到期时间 |

## 七、时间字段（2 个）

| # | apiKey | 标签 | itemType | dataType | dbColumn | 说明 |
|---|--------|------|----------|----------|----------|------|
| 30 | recentActivityRecordTime | 最新活动时间 | 38(时间) | 3(BIGINT) | dbc_bigint10 | 最近活动时间 |
| 31 | visitLatestTime | 最近拜访时间 | 38(时间) | 3(BIGINT) | dbc_bigint11 | 最近拜访时间 |

## 八、描述/备注（1 个）

| # | apiKey | 标签 | itemType | dataType | dbColumn | 说明 |
|---|--------|------|----------|----------|----------|------|
| 32 | releaseDescription | 退回公海描述 | 1(文本) | 1(VARCHAR) | dbc_varchar15 | 退回原因描述 |

## 九、计算/汇总字段（15 个）

这些字段由公式或汇总规则自动计算，itemType=27(计算)。

| # | apiKey | 标签 | itemType | dataType | dbColumn | 说明 |
|---|--------|------|----------|----------|----------|------|
| 33 | accountScore | 客户得分 | 27(计算) | 4(DECIMAL) | dbc_decimal4 | 综合评分公式 |
| 34 | totalWonOpportunities | 结单商机数 | 27(计算) | 4(DECIMAL) | dbc_decimal5 | 汇总 |
| 35 | totalWonOpportunityAmount | 结单商机总金额 | 27(计算) | 4(DECIMAL) | dbc_decimal6 | 汇总 |
| 36 | totalActiveOrders | 生效订单数 | 27(计算) | 4(DECIMAL) | dbc_decimal7 | 汇总 |
| 37 | totalOrderAmount | 订单总金额 | 27(计算) | 4(DECIMAL) | dbc_decimal8 | 汇总 |
| 38 | totalContract | 合同数 | 27(计算) | 4(DECIMAL) | dbc_decimal9 | 汇总 |
| 39 | actualInvoicedAmount | 实际应收金额 | 27(计算) | 4(DECIMAL) | dbc_decimal10 | 汇总 |
| 40 | paidAmount | 实际收款金额 | 27(计算) | 4(DECIMAL) | dbc_decimal11 | 汇总 |
| 41 | unpaidAmount | 未收款金额 | 27(计算) | 4(DECIMAL) | dbc_decimal12 | 汇总 |
| 42 | amountUnbilled | 未开票金额 | 27(计算) | 4(DECIMAL) | dbc_decimal13 | 汇总 |
| 43 | invoiceBalance | 应收余额 | 27(计算) | 4(DECIMAL) | dbc_decimal14 | 汇总 |
| 44 | isCustomer | 是否结单客户 | 27(计算) | 4(DECIMAL) | dbc_decimal15 | 公式 |
| 45 | paymentRate | 回款率 | 27(计算) | 4(DECIMAL) | dbc_decimal16 | 公式 |
| 46 | visitTotalCount | 拜访总数 | 27(计算) | 4(DECIMAL) | dbc_decimal17 | 汇总 |
| 47 | visitUnvisitDay | 未拜访天数 | 27(计算) | 3(BIGINT) | dbc_bigint12 | 公式 |

## 十、AI/数据分析字段（2 个）

仅保留有直接业务价值的分析字段。

| # | apiKey | 标签 | itemType | dataType | dbColumn | 说明 |
|---|--------|------|----------|----------|----------|------|
| 48 | valueScore | 客户价值评分 | 27(计算) | 4(DECIMAL) | dbc_decimal18 | AI 价值评分 |
| 49 | paymentHealthPct | 应收健康度 | 27(计算) | 4(DECIMAL) | dbc_decimal19 | 应收健康度 |

---

## 统计

| 分类 | 数量 |
|---|---|
| 系统公用字段 | 19 |
| 基本信息 | 8 |
| 联系方式 | 2 |
| 业务属性 | 10 |
| 关联字段 | 4 |
| 公海信息 | 5 |
| 时间字段 | 2 |
| 描述/备注 | 1 |
| 计算/汇总 | 15 |
| AI/数据分析 | 2 |
| **合计** | **68** |

## 本次删除的字段（相比 V2 初版）

| 字段 | 原因 |
|---|---|
| fax | 传真已过时，现代 CRM 不需要 |
| weibo | 微博账号非 CRM 核心 |
| srcFlg | 工商注册标记，非核心业务 |
| outterDepartId | 外部部门，极少使用 |
| registrationUtmId | UTM 追踪属于营销系统，非核心 CRM |
| cleanLatestTime | 数据清洗时间，内部运维字段 |
| recentBackfillTime | 数据回填时间，内部运维字段 |
| gradeLabel | AI 等级标签，可由前端实时计算 |
| nameInitial | 名称首字母索引，可由前端/搜索引擎处理 |
| nameLenCategory | 名称长度分类，无直接业务价值 |
| wonRatioText | 赢单占比文本，可由前端格式化 |
| compositeGrade | 综合评级标签，可由前端实时计算 |
| processedName | 处理后名称，内部数据清洗用 |
| ecouponsAccountLabel | 促销场景标签，属于促销系统 |
| visitInplanCount | 计划拜访数，可通过活动记录汇总 |
| activeDays | 活跃天数，可由前端实时计算 |
| newOppFlg | 是否有商机，可由 totalWonOpportunities>0 判断 |
| avgOrderAmount | 订单均价，可由 totalOrderAmount/totalActiveOrders 计算 |

## 历史删除的字段（相比老系统）

| 字段 | 原因 |
|---|---|
| entityType | 与 busitypeApiKey 重复，已统一 |
| old_old_old_* | 废弃地址字段 |
| 布局行(type=8) | 非业务字段 |
| 维度(type=99) | 非业务字段 |
| customItem147__c(百分比) | 无明确业务含义 |
| customItem151__c(33) | 测试字段 |
| customItem172__c(用户) | 含义不明 |
| customItem32__c(用户32) | 含义不明 |
| customItem181__c(关联拜访记录) | 可通过活动记录关联实现 |

## 保留的自定义字段

| 字段 | 标签 | 说明 |
|---|---|---|
| customerSource | 客户来源 | 原 customItem154__c，重命名为标准字段 |

## dbc 列分配汇总

| 前缀 | 已用 | 范围 |
|---|---|---|
| dbc_varchar | 15 | 1~15 |
| dbc_bigint | 12 | 1~12 |
| dbc_decimal | 19 | 1~19 |
| dbc_smallint | 2 | 1~2 |
| dbc_textarea | 0 | - |
