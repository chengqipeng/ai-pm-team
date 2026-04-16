# 以客户（account）为核心的元模型关联分析

## 一、全局关联拓扑

```
                                ┌─────────────┐
                                │  campaign   │ 市场活动
                                │  (9 字段)    │
                                └──────┬──────┘
                                       │ campaignId
          ┌────────────────────────────┼────────────────────────────┐
          │                            │                            │
          ▼                            ▼                            ▼
    ┌──────────┐              ┌──────────────┐              ┌────────────┐
    │   lead   │─────────────→│ opportunity  │─────────────→│  account   │ ★核心
    │ 销售线索   │ opportunityId│   销售机会     │  accountId   │   客户      │
    │ (26 字段) │              │  (44 字段)    │              │ (49 字段)   │
    └────┬─────┘              └──────┬───────┘              └─────┬──────┘
         │ contactId                 │ campaignContactId          │ parentAccountId
         ▼                           ▼                            │ (自关联)
    ┌──────────┐              ┌──────────┐                        │
    │ contact  │◄─────────────│  quote   │                        │
    │  联系人   │  accountId   │  报价单   │                        │
    │ (26 字段) │──────────→   │ (16 字段) │                        │
    └──────────┘  account     └────┬─────┘                        │
                                   │ orderRelQuotationEntity      │
                                   ▼                              │
                              ┌──────────┐    contractId    ┌──────────┐
                              │  order   │─────────────────→│ contract │
                              │   订单    │                  │   合同    │
                              │ (42 字段) │                  │ (27 字段) │
                              └────┬─────┘                  └──────────┘
                                   │ orderId
                                   ▼
                              ┌──────────────┐
                              │ orderProduct │
                              │   订单明细    │
                              │  (48 字段)   │
                              └──────┬───────┘
                                     │ priceBookEntryId
                                     ▼
    ┌──────────────┐          ┌──────────────┐          ┌──────────┐
    │productCategory│◄────────│   product    │─────────→│  goods   │
    │   产品目录     │ parentId │    产品      │  goods    │   商品    │
    │   (2 字段)    │          │  (38 字段)   │          │ (8 字段)  │
    └──────────────┘          └──────┬───────┘          └──────────┘
                                     │ baseUnitId/packUnit
                                     ▼
                              ┌──────────┐
                              │   unit   │
                              │  计量单位  │
                              │ (5 字段)  │
                              └──────────┘

    ═══════════════════════════════════════════════════════════════
    系统级实体（所有业务实体共享）
    ═══════════════════════════════════════════════════════════════

    ┌────────┐  ┌────────────┐  ┌───────────┐  ┌────────────────┐
    │  user  │  │ department │  │ territory │  │ activityrecord │
    │  用户   │  │    部门     │  │   区域     │  │    活动记录     │
    │(7 字段) │  │ (10 字段)   │  │  (5 字段)  │  │   (9 字段)     │
    └────────┘  └────────────┘  └───────────┘  └────────────────┘
       ↑ ownerId    ↑ departId     ↑ territoryId    ↑ recentActivityRecordId
       │            │              │                 │
       └────────────┴──────────────┴─────────────────┘
                    所有核心实体共享引用

    ═══════════════════════════════════════════════════════════════
    公海池 + 权限（元模型级，非业务数据实体）
    ═══════════════════════════════════════════════════════════════

    ┌──────────┐  ┌──────────────┐
    │ highSea  │  │ highSeaRule  │
    │  公海池   │  │   公海规则    │
    │(10 字段)  │  │  (9 字段)    │
    └──────────┘  └──────────────┘
       ↑ highSeaId (account.highSeaId)

    ┌────────────────┐  ┌──────────────┐  ┌────────────────────────┐
    │ dataPermission │  │ sharingRule  │  │ sharingRuleCondition   │
    │  数据权限配置    │  │   共享规则    │  │     共享规则条件         │
    │  (8 字段)       │  │  (14 字段)   │  │     (7 字段)           │
    └────────────────┘  └──────────────┘  └────────────────────────┘
       ↑ 每个 entity 一条      ↑ 每个 entity 多条      ↑ 每条规则多条
```

## 二、account 直接关联分析

### 2.1 account 主动引用的实体（正向 Lookup）

| 字段 | 目标实体 | 关联类型 | 必要性 | 说明 |
|---|---|---|---|---|
| parentAccountId | account | Lookup | ★必要 | 上级客户自关联，支持客户层级 |
| leadId | lead | Lookup | ★必要 | 来源线索，追踪转化路径 |
| dimDepart | department | Lookup | ★必要 | 数据权限维度，控制可见性 |
| recentActivityCreatedBy | user | Lookup | ★必要 | 最新跟进人，销售管理核心 |
| territoryHighSeaId | territory | Lookup | ○可选 | 区域公海，仅启用区域管理时需要 |
| highSeaId | (highSea) | Lookup | ★必要 | 所属公海池，公海机制核心 |

### 2.2 引用 account 的实体（反向关联）

| 来源实体 | 关联字段 | 业务含义 | 必要性 |
|---|---|---|---|
| contact | accountId | 联系人所属客户 | ★必要 — 联系人必须挂在客户下 |
| opportunity | accountId/customItem166__c | 商机关联客户 | ★必要 — 商机必须关联客户 |
| lead | accountId | 线索转化后的客户 | ★必要 — 线索转化链路 |
| order | accountId | 订单关联客户 | ★必要 — 订单归属 |
| contract | accountId | 合同关联客户 | ★必要 — 合同归属 |
| quote | quotationEntityRelAccount | 报价单关联客户 | ★必要 — 报价归属 |

### 2.3 account 的元模型级关联

| 元模型 | 关联方式 | 说明 |
|---|---|---|
| item | entity_api_key='account' | 49 个业务字段定义 |
| pickOption | entity_api_key='account' | 54 个选项值（8 个单选字段） |
| entityLink | entity_api_key='account' | 11 条关联关系 |
| busiType | entity_api_key='account' | 3 种业务类型（默认/企业客户/供应商） |
| dataPermission | entity_api_key='account' | 1 条权限配置（私有+层级只读+负责人读写） |
| sharingRule | entity_api_key='account' | 共享规则（待配置） |
| formulaCompute | entity_api_key='account' | 公式计算定义 |
| aggregationCompute | entity_api_key='account' | 汇总计算定义 |
| duplicateRule | entity_api_key='account' | 查重规则 |
| fieldSet | entity_api_key='account' | 字段集 |


## 三、各实体字段必要性深度分析

### 3.1 account（客户）— 49 字段

| 分类 | 字段 | 类型 | 必要性 | 理由 |
|---|---|---|---|---|
| 基本信息 | accountName | 文本 | ★必要 | 客户名称，核心标识 |
| 基本信息 | level | 单选 | ★必要 | 客户等级(A/B/C/D)，分层管理基础 |
| 基本信息 | industryId | 单选 | ★必要 | 行业分类，市场分析维度 |
| 基本信息 | parentAccountId | 关联 | ★必要 | 上级客户，集团化管理 |
| 基本信息 | fState/fCity/fDistrict | 单选 | ★必要 | 省市区，地域分析+拜访路线 |
| 基本信息 | address | 文本 | ◎重要 | 详细地址，拜访场景需要 |
| 联系方式 | phone | 电话 | ★必要 | 公司电话，基础联系方式 |
| 联系方式 | url | 网址 | ○可选 | 官网，非必须 |
| 业务属性 | employeeNumber | 单选 | ◎重要 | 员工规模，客户画像维度 |
| 业务属性 | annualRevenue | 实数 | ◎重要 | 年销售额，客户价值评估 |
| 业务属性 | accountChannel | 单选 | ★必要 | 获客渠道，ROI 分析基础 |
| 业务属性 | customerSource | 单选 | ★必要 | 客户来源，营销归因 |
| 业务属性 | vipFlag | 单选 | ◎重要 | VIP 标识，差异化服务 |
| 业务属性 | doNotDisturb | 布尔 | ○可选 | 免打扰，合规需要 |
| 业务属性 | duplicateFlg | 布尔 | ○可选 | 查重标记，数据质量 |
| 业务属性 | score | 整数 | ◎重要 | 客户评分，优先级排序 |
| 业务属性 | longitude/latitude | 实数 | ○可选 | GPS 坐标，地图拜访场景 |
| 关联 | leadId | 关联 | ★必要 | 来源线索，转化追踪 |
| 关联 | dimDepart | 关联 | ★必要 | 数据权限部门 |
| 关联 | recentActivityCreatedBy | 关联 | ★必要 | 最新跟进人 |
| 关联 | territoryHighSeaId | 关联 | ○可选 | 区域公海 |
| 公海 | highSeaId | 关联 | ★必要 | 所属公海池 |
| 公海 | highSeaAccountSource | 单选 | ★必要 | 公海来源 |
| 公海 | highSeaStatus | 单选 | ★必要 | 公海状态 |
| 公海 | claimTime/expireTime | 日期 | ★必要 | 认领/到期时间 |
| 时间 | recentActivityRecordTime | 时间 | ◎重要 | 最新活动时间 |
| 时间 | visitLatestTime | 时间 | ◎重要 | 最近拜访时间 |
| 描述 | releaseDescription | 文本 | ○可选 | 退回公海描述 |
| 计算(15个) | accountScore~paymentHealthPct | 计算 | ◎重要 | 汇总统计，客户360视图 |

结论：49 字段中 ★必要 20 个、◎重要 22 个、○可选 7 个，无需再精简。

### 3.2 contact（联系人）— 26 字段

| 字段 | 类型 | 必要性 | 理由 |
|---|---|---|---|
| contactName | 文本 | ★必要 | 联系人姓名 |
| accountId | 关联→account | ★必要 | 所属客户，核心关联 |
| depart | 文本 | ◎重要 | 联系人部门 |
| post | 文本 | ◎重要 | 联系人职务 |
| phone | 电话 | ★必要 | 电话 |
| mobile | 电话 | ★必要 | 手机 |
| email | 邮箱 | ★必要 | 邮箱 |
| state | 单选 | ○可选 | 省份 |
| address | 文本 | ○可选 | 地址 |
| zipCode | 文本 | ○可选 | 邮编 |
| gender | 单选 | ○可选 | 性别 |
| contactBirthday | 日期 | ○可选 | 生日 |
| contactChannel | 单选 | ◎重要 | 来源方式 |
| comment | 文本域 | ○可选 | 备注 |
| leadId | 关联→lead | ◎重要 | 来源线索 |
| countryId | 单选 | ○可选 | 城市 |
| sExternalUserId | 文本 | ○可选 | 外部联系人ID |
| recentActivityRecordId | 关联→activityrecord | ◎重要 | 最新活动记录 |
| recentActivityRecordType | 单选 | ○可选 | 最新活动类型 |
| doNotDisturb | 布尔 | ○可选 | 免打扰 |
| contactRole | 单选 | ◎重要 | 联系人角色（决策者/影响者/使用者） |
| duplicateFlg | 布尔 | ○可选 | 查重标记 |
| contactScore | 计算 | ◎重要 | 联系人评分 |
| **customItem158__c** | 文本 | **⚠存疑** | **"身份ID"含义不明，建议确认或删除** |

⚠ 建议删除：customItem158__c（身份ID）— 含义不明，无标准业务场景。

### 3.3 opportunity（商机）— 44 字段

| 分类 | 字段 | 必要性 | 理由 |
|---|---|---|---|
| 核心 | opportunityName, money, saleStageId, closeDate, status | ★必要 | 商机五要素 |
| 核心 | winRate, forecastCategory | ★必要 | 预测分析 |
| 关联 | priceId→priceBook, campaignContactId→contact, campaignId→campaign | ★必要 | 业务关联 |
| 关联 | sourceId | ◎重要 | 商机来源 |
| 金额 | projectBudget, actualCost, discount, fcastMoney | ◎重要 | 财务分析 |
| 阶段 | lostStageId, stageUpdatedAt, standardPeriod, actualPeriod | ◎重要 | 销售过程管理 |
| 输赢 | reason, reasonDesc, winReason, winReasonDesc | ◎重要 | 输赢分析 |
| 编号 | opportunityCode, workflowStageName | ○可选 | 辅助信息 |
| 标记 | commitmentFlg, repeatFlg | ○可选 | 辅助标记 |
| 日期 | invoiceDate, paymentDate | ○可选 | 开票/付款日期 |
| 评分 | opportunityScore, roiCiCount | ◎重要 | 商机评分 |
| AI | oppHealthAssessment* (3个) | ○可选 | AI 健康度评估 |
| 查重 | intelligentDuplicate* (5个) | ○可选 | 智能查重 |
| **自定义** | **customItem58/10/17__c** | **⚠存疑** | **"计算-文本N"含义不明** |
| **自定义** | **customItem166__c** | **⚠存疑** | **"客户"关联→account，与标准 accountId 重复** |

⚠ 建议删除 4 个存疑字段：
- customItem58__c / customItem10__c / customItem17__c — 标签为"计算-文本N"，无明确业务含义
- customItem166__c — "客户"关联，与公用字段 ownerId 或标准 accountId 关联重复

### 3.4 lead（线索）— 26 字段 ✓ 已清洗

已在 V2 清洗中删除了 23 个混入的 product 字段，剩余 26 个全部必要。

核心链路：lead → (转化) → account + contact + opportunity

### 3.5 product（产品）— 38 字段

| 分类 | 字段数 | 必要性 |
|---|---|---|
| 基本信息（名称/目录/价格/型号/规格） | 6 | ★必要 |
| 组合产品配置 | 4 | ◎重要 |
| SKU/规格值（5个 specificationValue） | 7 | ◎重要 |
| 单位管理（base/pack/goods/multi） | 4 | ◎重要 |
| 销售属性（独立销售/营销/序列号/批次） | 4 | ○可选 |
| 价格/促销 | 3 | ◎重要 |
| 库存（soldNum/stockNum） | 2 | ◎重要 |
| 图片 | 2 | ○可选 |
| 其他 | 6 | ○可选 |

product 引用了 5 个 specificationValue（规格值），但 specificationValue 实体未定义。
建议：如果不启用多规格 SKU，specificationValue1~5 可标记为可选。

### 3.6 goods（商品）— 8 字段 ✓ 精简

最小化的 SKU 实体，全部必要。

### 3.7 order（订单）— 42 字段

| 分类 | 字段数 | 必要性 |
|---|---|---|
| 订单核心（编号/状态/金额/日期） | 8 | ★必要 |
| 退货/变更 | 4 | ◎重要 |
| 收款 | 5 | ★必要 |
| 促销/返利（9个 generation/usable/exchange） | 9 | ○可选 — 仅促销场景 |
| 收货信息 | 4 | ◎重要 |
| 关联（合同/报价单/返利账户） | 3 | ◎重要 |
| 第三方（5个 third*） | 5 | ○可选 — 仅电商对接 |
| 计算 | 2 | ◎重要 |

⚠ 促销返利 9 个字段（generationRebate~exchangeCoupon）和第三方 5 个字段仅在特定场景使用，
如果不启用促销/电商模块，可以考虑标记为 enableFlg=0。

### 3.8 orderProduct（订单明细）— 48 字段

字段最多的实体，但大部分是订单行项目的标准属性：
- 价格/数量/折扣体系（20 个）— ★必要
- 变更追踪（6 个）— ◎重要
- 发货管理（3 个）— ◎重要
- 关联（7 个）— ★必要
- 计算（5 个）— ◎重要
- 其他（7 个）— ○可选

### 3.9 contract（合同）— 27 字段

| 分类 | 字段数 | 必要性 |
|---|---|---|
| 合同核心（主题/类型/编号/正文/签约日期） | 5 | ★必要 |
| 签约方 | 2 | ★必要 |
| 回款（付款方式/回款金额/未回款/状态/进度/逾期） | 6 | ★必要 |
| 开票 | 2 | ◎重要 |
| 计算字段（11 个） | 11 | ◎重要 |

合同实体设计合理，无需精简。

### 3.10 quote（报价单）— 16 字段 ✓ 精简

最小化的报价单实体，全部必要。

## 四、扩展实体必要性评估

| 实体 | 字段数 | 与 account 关系 | 必要性 | 说明 |
|---|---|---|---|---|
| user | 7 | 所有实体的 ownerId/createdBy 引用 | ★必要 | 系统基础，不可缺少 |
| department | 10 | 所有实体的 departId 引用 | ★必要 | 组织架构，数据权限基础（独立元模型，存储在 p_tenant_department） |
| territory | 5 | account/contact 的 territoryId 引用 | ◎重要 | 区域管理，可选模块 |
| campaign | 9 | opportunity/lead 的 campaignId 引用 | ◎重要 | 市场活动，营销归因 |
| activityrecord | 9 | contact/lead/opportunity 引用 | ◎重要 | 活动记录，跟进管理 |
| highSea | 10 | account.highSeaId 引用 | ★必要 | 公海池，客户流转核心 |
| highSeaRule | 9 | highSea 的子规则 | ◎重要 | 公海自动回收规则 |
| priceBook | 3 | opportunity/order/quote 引用 | ◎重要 | 价格表，报价/订单基础 |
| priceBookEntry | 6 | orderProduct 引用 | ◎重要 | 价格表明细 |
| productCategory | 2 | product.parentId 引用 | ○可选 | 产品目录分类 |
| unit | 5 | product/goods/orderProduct 引用 | ◎重要 | 计量单位 |

### 权限元模型

| 元模型 | 与 account 关系 | 必要性 | 说明 |
|---|---|---|---|
| dataPermission | 每个 entity 一条配置 | ★必要 | 控制数据默认可见性 |
| sharingRule | 每个 entity 多条规则 | ★必要 | 自动共享策略 |
| sharingRuleCondition | 每条规则多条条件 | ★必要 | 共享规则的过滤条件 |

## 五、存疑字段清理建议

| 实体 | 字段 | 标签 | 建议 | 理由 |
|---|---|---|---|---|
| contact | customItem158__c | 身份ID | 删除 | 含义不明，无标准 CRM 场景 |
| opportunity | customItem58__c | 计算-文本58 | 删除 | 标签为自动生成，无业务含义 |
| opportunity | customItem10__c | 计算-文本10 | 删除 | 同上 |
| opportunity | customItem17__c | 计算-文本17 | 删除 | 同上 |
| opportunity | customItem166__c | 客户 | 删除 | 与标准 accountId 关联重复 |

共 5 个存疑字段建议删除。

## 六、缺失实体分析

以下实体被核心实体引用但尚未定义：

| 实体 | 被引用方 | 必要性 | 建议 |
|---|---|---|---|
| entityBelongType | 所有实体的业务类型关联 | ○可选 | 系统内部实体，busiType 已覆盖此功能 |
| specificationValue | product 的规格值1~5 | ○可选 | 仅多规格 SKU 场景需要 |
| servicePlan | product.fscServicePlan | ○可选 | 服务计划，仅服务型产品需要 |
| goodsUnit | product.goodsUnit | ○可选 | 商品单位，unit 已覆盖 |
| customerAccount | order.rebateCustomerAccount | ○可选 | 返利账户，仅促销场景 |
| shop | goods/order/orderProduct/product | ○可选 | 店铺，仅电商场景 |
| qwContact | contact/lead/order | ○可选 | 企业微信好友，仅企微集成 |

建议：这些实体属于特定业务模块的扩展，当前阶段不需要创建，保留 entityLink 引用即可，
待对应模块启用时再补充。

## 七、总结

### 当前系统完整度

| 维度 | 数量 | 状态 |
|---|---|---|
| 核心业务实体 | 10 | ✓ 完整 |
| 系统基础实体 | 5 | ✓ 完整 |
| 公海池实体 | 2 | ✓ 完整 |
| 商业扩展实体 | 4 | ✓ 完整 |
| 权限元模型 | 3 | ✓ 完整 |
| 总字段数 | 787 | ✓ 全部有类型和列名 |
| 存疑字段 | 5 | ⚠ 建议删除 |
| 缺失实体 | 7 | ○ 可选，按需补充 |

### 以 account 为核心的业务完整性

```
线索获取 → 线索培育 → 客户转化 → 商机跟进 → 报价 → 订单 → 合同 → 回款
  lead      lead     account   opportunity  quote  order  contract  contract
                     contact                              (计算字段)
```

每个环节的实体和关联关系都已完整定义，支撑完整的 CRM 业务闭环。
