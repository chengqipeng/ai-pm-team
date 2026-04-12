# 商品/订单/合同 元数据字段设计

CRM 商业交易链路的核心实体元数据定义。

## 实体总览

| 实体 | apiKey | 标签 | 字段数 | 说明 |
|---|---|---|---|---|
| product | product | 产品 | 57 | 产品目录（SPU），含规格、价格、组合配置 |
| goods | goods | 商品 | 27 | 商品（SKU），关联产品，含规格值、价格 |
| order | order | 订单 | 61 | 销售订单，含金额、状态、支付、促销 |
| orderProduct | orderProduct | 订单明细 | 67 | 订单行项目，含单价、数量、折扣、发货 |
| contract | contract | 合同 | 46 | 销售合同，含签约、回款、开票 |
| quote | quote | 报价单 | 35 | 报价单，含报价阶段、金额、有效期 |

## 业务流程

```
产品(product) → 商品(goods)
       ↓
报价单(quote) → 订单(order) → 订单明细(orderProduct)
                    ↓
               合同(contract) → 应收单(invoice) → 收款(payment)
```

---

详细字段定义见各实体独立文档：
- [product-fields.md](product-fields.md)（待生成）
- [order-fields.md](order-fields.md)（待生成）

以下为各实体业务字段摘要（不含 19 个系统公用字段）。

## product（产品）— 38 个业务字段

核心产品目录管理，支持组合产品、多规格、多单位。

| 分类 | 字段 | 说明 |
|---|---|---|
| 基本信息 | productName, parentId, priceUnit, fscProductModel, fscProductSpec | 名称、目录、标准价、型号、规格 |
| 产品配置 | configurable, configurationType, configurationEvent, configLevel | 组合产品配置 |
| SKU/规格 | goods, skuType, skuId, skuNo, specificationValue1~5 | 商品关联、规格值 |
| 单位管理 | baseUnitId, packUnit, goodsUnit, multiUnit | 基础单位、包装单位、多单位 |
| 销售属性 | independentProduct, marketable, enableSN, enableBatchNumber | 独立销售、营销、序列号、批次 |
| 价格/促销 | pricingCycle, orderFixedIncrement, salesPromotionLabel | 计费周期、固定增购、促销标记 |
| 库存 | soldNum, stockNum | 销量、库存 |
| 图片 | fileImage1, explodedView | 产品图片、爆炸图 |

## goods（商品）— 8 个业务字段

商品 SKU 管理，关联产品，支持多规格。

| 字段 | 标签 | 类型 | 说明 |
|---|---|---|---|
| baseUnit | 基础单位 | 关联 | 基础计量单位 |
| multiSpecification | 开启多规格 | 布尔 | 是否多规格商品 |
| origin | 划线价格 | 实数 | 原价/划线价 |
| itemNo | 三方商品编码 | 文本 | 第三方平台编码 |
| subTitle | 分享描述 | 文本 | 分享时的描述文案 |
| pageUrl | 小程序访问地址 | 文本 | 小程序商品页 URL |
| detailUrl | H5访问地址 | 文本 | H5 商品详情页 URL |
| itemType | 商品类型 | 单选 | 实物/虚拟/服务 |

## order（订单）— 42 个业务字段

销售订单管理，支持变更单、退货单、多种支付方式。

| 分类 | 字段 | 说明 |
|---|---|---|
| 订单核心 | po, poStatus, initAmount, productsAmount, effectiveDate, deliveryDate | 编号、状态、金额、生效/交货日期 |
| 退货 | ro, roStatus | 退货单编号、退货状态 |
| 变更 | co, originalOrderVersion, lineItemCount | 变更单号、原订单版本、明细条数 |
| 收款 | payments, paymentBalance, cashPayment, nonCashPayment, surplusPayable | 回款、现金/非现金支付、剩余应付 |
| 促销/返利 | generationRebate, generationPoints, generationCoupon, usableRebate, usablePoints, usableCoupon, exchangeRebate, exchangePoints, exchangeCoupon | 返利、积分、电子券 |
| 收货信息 | contactTel, contactAddress, receiverName, receiverTel | 联系电话、收货地址 |
| 关联 | contractId, orderRelQuotationEntity, rebateCustomerAccount | 合同、报价单、返利账户 |
| 第三方 | thirdOrderStatus, buyerThirdId, postFee, statusOfPayment, shipmentStatus | 三方状态、运费、支付/发货状态 |
| 计算字段 | paymentBalance, invoiceReceiptBlance | 未收款金额、应开票金额 |

## orderProduct（订单明细）— 48 个业务字段

订单行项目，支持折扣体系、变更追踪、发货管理。

| 分类 | 字段 | 说明 |
|---|---|---|
| 价格/数量 | unitPrice, quantity, bundledQuantity, listTotal | 单价、数量、选项数量、原价 |
| 折扣体系 | totalDiscountAmount, totalSystemDiscountAmount, totalAdditionalDiscountAmount, systemPercentageAfterDiscount, systemDiscount, additionalPercentageAfterDiscount, additionalDiscount | 系统折扣、额外折扣 |
| 兑换 | exchangePrice, exchangeAmount | 兑换单价、兑换总额 |
| 变更追踪 | deltaQuantity, deltaAmount, changeType, orderVersion, changeOrderVersion, delChangeOrderVersion | 变更数量/金额、变更类型、版本号 |
| 发货管理 | quantityUndelivered, quantityUnshipped, quantityShipped | 未收货、未发货、已发货数量 |
| 关联 | orderId, orderProductId, parentLine, originalOrderId, originalOrderProductId, priceBookEntryId, salesUnitId | 订单、上级明细、原订单、价格表 |
| 计算字段 | amountInvoiced, totalInvoiceAdjustmentAmount, totalPaymentAmount, totalRefundAmount | 应收、已变更应收、已收款、已退款 |

## contract（合同）— 27 个业务字段

销售合同管理，支持回款追踪、开票管理。

| 分类 | 字段 | 说明 |
|---|---|---|
| 合同核心 | title, contractType, contractCode, contractContent, signDate | 主题、类型、编号、正文、签约日期 |
| 签约方 | customerSigner, signerId | 客户方签约人、我方签约人 |
| 回款 | payMode, payBack, notPayment, paymentStatus, paymentPercent, overdueStatus | 付款方式、回款/未回款金额、回款状态/进度、逾期状态 |
| 开票 | invoiceAmount, receiptAmount, receiptBalance | 开票金额、已开票、未开票 |
| 计算字段 | orderAmount, invoicedAmount, paymentAmount, invoicedPercentage 等 | 订单总额、应收、收款、应收比例（共 11 个计算字段） |

## quote（报价单）— 16 个业务字段

报价单管理，关联客户、商机、联系人。

| 字段 | 标签 | 类型 | 说明 |
|---|---|---|---|
| quotationTitle | 报价单名称 | 文本 | 报价单标题 |
| quotationEntityRelAccount | 客户名称 | 关联 | 关联客户 |
| quotationEntityRelOpportunity | 销售机会名称 | 关联 | 关联商机 |
| quoteRelContact | 联系人名称 | 关联 | 关联联系人 |
| contactEmail | 联系人邮箱 | 邮箱 | 联系人邮箱 |
| quotationStage | 阶段 | 单选 | 报价阶段 |
| validDate | 有效日期 | 日期 | 报价有效期 |
| quoteTime | 报价时间 | 时间 | 报价创建时间 |
| synchronizedDate | 最近同步时间 | 时间 | 最近同步时间 |
| quotationAmount | 总金额 | 实数 | 报价总金额 |
| quotationQuantity | 总数量 | 实数 | 报价总数量 |
| priceListId | 价格表名称 | 关联 | 关联价格表 |
| mainQuote | 主报价单 | 布尔 | 是否主报价单 |
| template | 模板 | 关联 | 报价单模板 |
| isTemplate | 报价单模板 | 单选 | 是否为模板 |
| quotationRemarks | 备注 | 文本域 | 报价备注 |
