# CRM 核心元数据模型（客户/联系人/商机/线索）

## 一、实体总览

| 实体 | 标签 | 字段数(C+T) | 选项值 | 关联关系 | 业务类型 | 公式 | 汇总 | 查重 |
|---|---|---|---|---|---|---|---|---|
| account | 客户 | 54+53 | 40+7 | 13+72 | 3+2 | 13 | 12 | 1 |
| contact | 联系人 | 43+28 | 10 | 11+33 | - | 1 | - | 1 |
| opportunity | 商机 | 37+36 | 30+8 | 17+32 | 0+10 | 2 | 1 | - |
| lead | 线索 | 26+23 | 44 | 17+45 | - | - | - | 1 |

> C=Common, T=Tenant

## 二、跨实体关联关系图

```
                    ┌─────────────┐
                    │   campaign  │ 市场活动
                    └──────┬──────┘
                           │
    ┌──────────────────────┼──────────────────────┐
    │                      │                      │
    ▼                      ▼                      ▼
┌────────┐          ┌────────────┐          ┌──────────┐
│  lead  │ ──────→  │ opportunity│ ──────→  │ account  │
│ 销售线索 │          │   销售机会   │          │   客户    │
└────┬───┘          └─────┬──────┘          └────┬─────┘
     │                    │                      │
     │                    │                      │
     ▼                    ▼                      ▼
┌─────────┐         ┌──────────┐          ┌──────────┐
│ contact │         │  quote   │          │ contract │
│  联系人   │         │  报价单   │          │   合同    │
└─────────┘         └────┬─────┘          └────┬─────┘
                         │                     │
                         ▼                     ▼
                    ┌──────────┐          ┌──────────┐
                    │  order   │          │ invoice  │
                    │   订单    │          │  应收单   │
                    └────┬─────┘          └──────────┘
                         │
                         ▼
                    ┌──────────────┐
                    │ orderProduct │
                    │   订单明细    │
                    └──────────────┘
```

## 三、关联关系详情

### account（客户）关联 — 13 条

| 关联 apiKey | 标签 | 关联目标 | 说明 |
|---|---|---|---|
| account_account_parentAccountId | 客户 | account | 上级客户（自关联） |
| account_lead_leadId | 客户 | lead | 关联销售线索 |
| account_user_ownerId | 客户 | user | 客户所有人 |
| account_user_createdBy | 客户 | user | 创建人 |
| account_user_updatedBy | 客户 | user | 修改人 |
| account_user_applicantId | 客户 | user | 审批提交人 |
| account_user_recentActivityCreatedBy | 客户 | user | 最新跟进人 |
| account_department_dimDepart | 客户 | department | 所属部门 |
| account_department_outterDepartId | 客户 | department | 外部部门 |
| account_territory_territoryId | 客户 | territory | 所属区域 |
| account_territory_territoryHighSeaId | 客户 | territory | 所属区域公海 |
| account_entityBelongType_entityType | 客户 | entityBelongType | 业务类型关联 |
| account_qwContact_qwContactId | 企微好友 | qwContact | 企业微信好友 |

### contact（联系人）关联 — 11 条

| 关联 apiKey | 标签 | 关联目标 | 说明 |
|---|---|---|---|
| contact_account_accountId | 联系人 | account | 所属客户 |
| contact_user_ownerId | 联系人 | user | 联系人所有人 |
| contact_user_createdBy | 联系人 | user | 创建人 |
| contact_user_updatedBy | 联系人 | user | 修改人 |
| contact_user_applicantId | 联系人 | user | 审批提交人 |
| contact_department_dimDepart | 联系人 | department | 所属部门 |
| contact_territory_territoryId | 联系人 | territory | 所属区域 |
| contact_entityBelongType_entityType | 联系人 | entityBelongType | 业务类型关联 |
| contact_activityrecord_recentActivityRecordId | 联系人 | activityrecord | 最新活动记录 |
| contact_qwContact_qwContactId | 联系人 | qwContact | 企业微信好友 |
| contact_mcRegistrationUtm_registrationUtmId | 关联UTM | - | UTM 来源追踪 |

### opportunity（商机）关联 — 17 条

| 关联 apiKey | 标签 | 关联目标 | 说明 |
|---|---|---|---|
| opportunity_account_accountId | 商机 | account | 关联客户 |
| opportunity_contact_campaignContactId | 商机 | contact | 关联联系人 |
| opportunity_lead_leadId | 商机 | lead | 来源线索 |
| opportunity_campaign_campaignId | 商机 | campaign | 关联市场活动 |
| opportunity_priceBook_priceId | 商机 | priceBook | 关联价格表 |
| opportunity_stage_saleStageId | 商机 | - | 销售阶段 |
| opportunity_stage_lostStageId | 商机 | - | 输单阶段 |
| opportunity_user_ownerId | 商机 | user | 商机所有人 |
| opportunity_user_createdBy | 商机 | user | 创建人 |
| opportunity_user_updatedBy | 商机 | user | 修改人 |
| opportunity_user_applicantId | 商机 | user | 审批提交人 |
| opportunity_department_dimDepart | 商机 | department | 所属部门 |
| opportunity_territory_territoryId | 商机 | territory | 所属区域 |
| opportunity_entityBelongType_entityType | 商机 | entityBelongType | 业务类型关联 |
| opportunity_entityBelongType_recentActivityRecordType | 商机 | entityBelongType | 最新活动类型 |
| opportunity_activityrecord_recentActivityRecordId | 商机 | activityrecord | 最新活动记录 |
| opportunity_mcRegistrationUtm_registrationUtmId | 关联UTM | - | UTM 来源追踪 |

### lead（线索）关联 — 17 条

| 关联 apiKey | 标签 | 关联目标 | 说明 |
|---|---|---|---|
| lead_account_accountId | 线索 | account | 转化后的客户 |
| lead_contact_contactId | 线索 | contact | 转化后的联系人 |
| lead_opportunity_opportunityId | 线索 | opportunity | 转化后的商机 |
| lead_campaign_campaignId | 线索 | campaign | 来源市场活动 |
| lead_user_ownerId | 线索 | user | 线索所有人 |
| lead_user_createdBy | 线索 | user | 创建人 |
| lead_user_updatedBy | 线索 | user | 修改人 |
| lead_user_applicantId | 线索 | user | 审批提交人 |
| lead_user_lastOwnerId | 线索 | user | 退回前所有人 |
| lead_user_recentActivityCreatedBy | 线索 | user | 最新跟进人 |
| lead_department_dimDepart | 线索 | department | 所属部门 |
| lead_territory_territoryId | 线索 | territory | 所属区域 |
| lead_entityBelongType_entityType | 线索 | entityBelongType | 业务类型关联 |
| lead_entityBelongType_recentActivityRecordType | 线索 | entityBelongType | 最新活动类型 |
| lead_activityrecord_recentActivityRecordId | 线索 | activityrecord | 最新活动记录 |
| lead_qwContact_qwContactId | 企微好友 | qwContact | 企业微信好友 |
| lead_mcRegistrationUtm_registrationUtmId | 关联UTM | - | UTM 来源追踪 |

## 四、业务类型（Record Type）

### account 业务类型 — 3+2 条

| apiKey | 标签 | 来源 |
|---|---|---|
| defaultBusiType | 默认业务类型 | Common |
| defaultScrmBusiType | 企业客户 | Common |
| defaultVendorBusiType | 供应商 | Common |

### opportunity 业务类型 — 10 条（Tenant）

由租户自定义，Common 无预置。

## 五、计算字段

### account 公式计算 — 13 条

| apiKey | 标签 |
|---|---|
| gradeLabel_fc | 客户等级标签 |
| nameInitial_fc | 名称首字母 |
| valueScore_fc | 客户价值评分 |
| paymentHealthPct_fc | 应收健康度 |
| avgOrderAmount_fc | 订单均价 |
| nameLenCategory_fc | 名称长度分类 |
| wonRatioText_fc | 赢单占比文本 |
| activeDays_fc | 活跃天数 |
| compositeGrade_fc | 综合评级 |
| processedName_fc | 处理后名称 |

### account 汇总计算 — 12 条

汇总子实体（商机、订单、合同）的统计数据到客户。

### opportunity 公式计算 — 2 条 + 汇总 1 条

## 六、业务完整性检查

### ✓ 完整的业务链路

| 链路 | 关联字段 | 状态 |
|---|---|---|
| lead → account | lead_account_accountId | ✓ |
| lead → contact | lead_contact_contactId | ✓ |
| lead → opportunity | lead_opportunity_opportunityId | ✓ |
| opportunity → account | opportunity_account_accountId | ✓ |
| opportunity → contact | opportunity_contact_campaignContactId | ✓ |
| contact → account | contact_account_accountId | ✓ |
| account → account | account_account_parentAccountId | ✓ 自关联 |

### ⚠ 关联到未保留实体

以下关联指向已删除的实体，需要评估是否影响业务：

| 关联 | 目标实体 | 说明 |
|---|---|---|
| → campaign | 市场活动 | 商机/线索来源追踪 |
| → activityrecord | 活动记录 | 最新活动记录 |
| → territory | 区域 | 销售区域 |
| → department | 部门 | 组织架构 |
| → user | 用户 | 所有人/创建人等 |
| → entityBelongType | 业务类型 | 业务类型关联 |
| → qwContact | 企微好友 | 企业微信集成 |
| → priceBook | 价格表 | 商机关联价格表 |

> 这些是系统级实体（user/department）或扩展功能实体（campaign/territory），
> 虽然不在保留的 10 个核心实体中，但关联关系应保留，确保未来扩展时数据完整。
