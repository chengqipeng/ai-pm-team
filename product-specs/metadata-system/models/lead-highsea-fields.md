# leadHighSea（线索公海）字段元数据定义

> 日期：2026-04-28
> 参考：highSea（客户公海）实体结构，针对线索场景调整

## 一、entity 注册

| 属性 | 值 | 说明 |
|---|---|---|
| metamodel_api_key | entity | 元模型标识 |
| api_key | leadHighSea | 实体标识 |
| label | 线索公海 | 显示名称 |
| namespace | system | 系统级实体 |
| entityType (dbc_int1) | 0 | 标准对象 |
| enableFlg (dbc_smallint3) | 1 | 启用 |
| busiTypeFlg (dbc_smallint1) | 1 | 启用业务类型 |
| checkRuleFlg (dbc_smallint2) | 0 | 不启用校验规则 |
| customFlg | 0 | 非自定义 |

## 二、系统公用字段（19 个，CommonFieldProvider 注入）

所有 entity 共享，不在 item 元数据中定义。

| # | apiKey | 数据库列 | 类型 | 说明 |
|---|--------|---------|------|------|
| 1 | id | id | BIGINT | 雪花 ID |
| 2 | name | name | VARCHAR | 记录名称（= leadHighSeaName） |
| 3 | ownerId | owner_id | BIGINT | 所有人 |
| 4 | departApiKey | depart_api_key | VARCHAR | 所属部门 |
| 5 | busitypeApiKey | busitype_api_key | VARCHAR | 业务类型 |
| 6 | applicantId | applicant_id | BIGINT | 审批提交人 |
| 7 | approvalStatus | approval_status | INT | 审批状态 |
| 8 | lockStatus | lock_status | INT | 锁定状态 |
| 9 | createdAt | created_at | BIGINT | 创建时间 |
| 10 | createdBy | created_by | BIGINT | 创建人 |
| 11 | updatedAt | updated_at | BIGINT | 修改时间 |
| 12 | updatedBy | updated_by | BIGINT | 修改人 |
| 13 | deleteFlg | delete_flg | SMALLINT | 软删除 |
| 14 | entityApiKey | entity_api_key | VARCHAR | = 'leadHighSea' |
| 15 | tenantId | tenant_id | BIGINT | 租户 ID |
| 16 | workflowStage | workflow_stage | VARCHAR | 工作流阶段 |
| 17 | currencyUnit | currency_unit | INT | 币种 |
| 18 | currencyRate | currency_rate | DECIMAL | 汇率 |
| 19 | territoryId | territory_id | BIGINT | 区域 |

## 三、业务字段（12 个，item 元数据定义）

存储在 `p_common_metadata`（metamodel_api_key='item', entity_api_key='leadHighSea'）。

| # | apiKey | label | itemType | dataType | dbColumn | 说明 |
|---|--------|-------|----------|----------|----------|------|
| 1 | leadHighSeaName | 公海池名称 | 1(TEXT) | 1(VARCHAR) | name | 主属性，映射到固定列 |
| 2 | assignRule | 领取规则 | 2(SELECT) | 1(VARCHAR) | dbc_smallint1 | 0=自行领取 1=手动分配 |
| 3 | recycleRule | 回收规则 | 2(SELECT) | 1(VARCHAR) | dbc_smallint2 | 0=自动回收 1=手动回收 |
| 4 | transferRule | 转移规则 | 2(SELECT) | 1(VARCHAR) | dbc_smallint3 | 0=仅管理员 1=成员可转移 |
| 5 | noActivitiesDay | 无跟进回收天数 | 5(NUMBER) | 3(BIGINT) | dbc_bigint1 | 天数，0=不启用 |
| 6 | noContactDay | 无联系回收天数 | 5(NUMBER) | 3(BIGINT) | dbc_bigint2 | 无电话/邮件联系天数 |
| 7 | remindDay | 提前提醒天数 | 5(NUMBER) | 3(BIGINT) | dbc_bigint3 | 回收前提醒 |
| 8 | claimLimitDay | 回收后禁领天数 | 5(NUMBER) | 3(BIGINT) | dbc_bigint4 | 回收后多少天不可再领 |
| 9 | releaseLimit | 退回次数限制 | 5(NUMBER) | 3(BIGINT) | dbc_bigint5 | 0=不限制 |
| 10 | claimMaxCount | 每人最大持有数 | 5(NUMBER) | 3(BIGINT) | dbc_bigint6 | 0=不限制 |
| 11 | enableFlg | 是否启用 | 31(BOOLEAN) | 6(SMALLINT) | dbc_smallint4 | 1=启用 0=停用 |
| 12 | description | 描述 | 4(TEXTAREA) | 5(TEXT) | dbc_textarea1 | |

### dbc 列分配

| 前缀 | 已用 | 列号 |
|---|---|---|
| dbc_bigint | 6 | 1~6 |
| dbc_smallint | 4 | 1~4 |
| dbc_textarea | 1 | 1 |
| dbc_varchar | 0 | — |
| dbc_decimal | 0 | — |

## 四、pickOption 定义

### assignRule 选项

| apiKey | label | 值 |
|---|---|---|
| opt_self_claim | 自行领取 | 0 |
| opt_manual_assign | 手动分配 | 1 |

### recycleRule 选项

| apiKey | label | 值 |
|---|---|---|
| opt_auto_recycle | 自动回收 | 0 |
| opt_manual_recycle | 手动回收 | 1 |

### transferRule 选项

| apiKey | label | 值 |
|---|---|---|
| opt_admin_only | 仅管理员 | 0 |
| opt_member_can | 成员可转移 | 1 |

## 五、busiType 定义

| apiKey | label | defaultFlg |
|---|---|---|
| defaultBusiType | 默认业务类型 | 1 |

## 六、entityLink 定义

| apiKey | label | parent | child | referItemApiKey | cascadeDelete |
|---|---|---|---|---|---|
| leadHighSea_to_lead | 公海线索 | leadHighSea | lead | leadHighSeaId | 0(不级联) |

## 七、与 highSea（客户公海）的对比

| 维度 | highSea | leadHighSea |
|---|---|---|
| 管理对象 | account | lead |
| 回收条件 | 无跟进 + 无商机 + 无成交 | 无跟进 + 无联系 |
| 特有字段 | noNewOpportunityDay, noTransferDay | noContactDay, claimMaxCount |
| 转化出口 | 无 | L2O 转化 |
| 字段数 | 12 | 12 |
| 结构 | 一致 | 一致 |

---

