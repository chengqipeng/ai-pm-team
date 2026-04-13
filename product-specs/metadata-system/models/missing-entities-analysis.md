# 老系统缺失实体 CRM 场景必要性分析

老系统 873 个实体，新系统已有 21 个，缺失 852 个。
按 CRM 核心场景逐一分析，筛选出必不可少的实体。

## 筛选标准

- ★必要：CRM 基础业务流程无法运转缺少此实体
- ◎重要：主流 CRM 场景需要，但可延后
- ○可选：特定行业/模块才需要
- ✗不需要：测试/废弃/行业定制/内部实现

## 一、★必要实体（CRM 基础流程必须）

| 实体 | 标签 | 老系统字段 | 被引用 | 场景 |
|---|---|---|---|---|
| payment | 回款记录 | 0(system) | 2 | 合同回款闭环：合同→回款→核销，account 的 paidAmount/unpaidAmount 汇总依赖此实体 |
| invoice | 应收单 | 6 | 12 | 开票管理：合同→应收单→发票，account 的 actualInvoicedAmount/invoiceBalance 汇总依赖 |
| invoiceItem | 应收单明细 | 0 | 6 | 应收单行项目 |
| opportunityProduct | 商机明细 | 8(system) | 0 | 商机关联产品：商机→商机明细→产品，报价/订单的产品来源 |
| visitRecord | 拜访记录 | 28 | 10 | 拜访管理：account 的 visitLatestTime/visitTotalCount 汇总依赖，销售过程管理核心 |
| contactRole | 联系人角色 | 9(system) | 0 | 商机中联系人的角色（决策者/影响者/使用者），大客户销售必须 |

理由：
- payment/invoice：account 的 15 个计算字段中有 6 个（paidAmount/unpaidAmount/actualInvoicedAmount/amountUnbilled/invoiceBalance/paymentRate）直接依赖回款和应收数据
- opportunityProduct：商机→报价→订单的产品链路中间环节
- visitRecord：account 的 visitLatestTime/visitTotalCount 字段依赖，且拜访是 CRM 最高频操作
- contactRole：多联系人商机中区分决策链角色

## 二、◎重要实体（主流 CRM 场景需要）

| 实体 | 标签 | 老系统字段 | 被引用 | 场景 |
|---|---|---|---|---|
| paymentApplicationPlan | 收款计划 | 8 | 9 | 合同分期收款计划 |
| paymentApplication | 收款单 | 2 | 4 | 收款单据 |
| receipt | 发票 | 1 | 4 | 发票管理 |
| quoteLine | 报价单明细 | 11 | 7 | 报价单行项目（quote 的子实体） |
| asset | 资产 | 19 | 16 | 客户资产管理（已购产品追踪） |
| serviceCase | 服务工单 | 23 | 10 | 售后服务工单 |
| serviceContract | 服务合同 | 11 | 3 | 服务合同（质保/维保） |
| announcement | 公告 | 25 | 3 | 系统公告 |
| teamMember | 团队成员 | 6 | 0 | 客户团队协作（account.teamFlg=1 时需要） |
| formInstance | 表单 | 17 | 4 | 自定义表单（审批/调查） |
| formColumn | 表单元素 | 18 | 4 | 表单字段定义 |
| territoryModel | 区域模型 | 7 | 15 | 区域管理模型定义 |

## 三、○可选实体（特定模块/行业）

### 3.1 营销自动化模块
| 实体 | 标签 | 说明 |
|---|---|---|
| mcEmail | 邮件 | 邮件营销 |
| mcTask | 营销任务 | 营销自动化任务 |
| marketSOP | 客户旅程 | 客户旅程编排 |
| marketSOPNode | 客户旅程节点 | 旅程节点 |
| segmentRule | 细分群组 | 客户分群 |
| smsTemplatePlus | 短信模板 | 短信营销 |

### 3.2 企业微信集成
| 实体 | 标签 | 说明 |
|---|---|---|
| qwContact | 企微联系人 | 企微好友 |
| qwGroup | 企微客户群 | 企微群 |
| qwSidebar | 企微好友关系 | 侧边栏 |

### 3.3 现场服务
| 实体 | 标签 | 说明 |
|---|---|---|
| fieldJob | 派工单 | 现场派工 |
| serviceTask | 服务任务 | 服务任务 |
| serviceVisitor | 访客 | 访客管理 |

### 3.4 仓储物流
| 实体 | 标签 | 说明 |
|---|---|---|
| warehouse | 仓库 | 仓库管理 |
| stockIn/stockOut | 出入库 | 出入库单 |
| dispatchNote | 发运单 | 发运管理 |

### 3.5 汽车行业定制（auto* 系列，约 80 个）
全部为汽车行业垂直定制，通用 CRM 不需要。

### 3.6 医药行业定制（med* 系列，约 20 个）
全部为医药行业垂直定制，通用 CRM 不需要。

## 四、✗不需要的实体

| 类别 | 数量 | 说明 |
|---|---|---|
| auto* 汽车行业 | ~80 | 汽车行业垂直定制 |
| med* 医药行业 | ~20 | 医药行业垂直定制 |
| qw* 企微相关 | ~30 | 企业微信深度集成 |
| bpm* 流程引擎 | ~10 | BPM 流程引擎内部实体 |
| territory* 区域详细 | ~15 | 区域管理细节实体 |
| 0 字段 system 实体 | ~40 | 老系统预留但未实现的空壳实体 |
| 测试/废弃 | ~10 | testzly__c 等 |
| AI/大模型 | ~10 | AI 相关实验性实体 |
| 内部实现 | ~100+ | 日志/统计/配置等内部实现实体 |

## 五、建议新增清单

### 第一优先级（★必要，立即新增）

| # | 实体 | 标签 | 预估字段 | 依赖 |
|---|---|---|---|---|
| 1 | payment | 回款记录 | 12 | contract, account |
| 2 | invoice | 应收单 | 10 | contract, account |
| 3 | invoiceItem | 应收单明细 | 8 | invoice, orderProduct |
| 4 | opportunityProduct | 商机明细 | 12 | opportunity, product, priceBookEntry |
| 5 | visitRecord | 拜访记录 | 15 | account, contact, opportunity |
| 6 | contactRole | 联系人角色 | 6 | contact, opportunity |

新增后系统将有 27 个实体，覆盖完整的 CRM 核心业务闭环。

### 第二优先级（◎重要，下一阶段）

| # | 实体 | 标签 | 预估字段 |
|---|---|---|---|
| 7 | quoteLine | 报价单明细 | 12 |
| 8 | paymentPlan | 收款计划 | 8 |
| 9 | asset | 资产 | 15 |
| 10 | serviceCase | 服务工单 | 18 |
