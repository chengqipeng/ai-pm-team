# busiTypePickOption — 业务类型选项值元模型

> 老系统常量：`MetaConstants.METAMODEL_ID_BUSITYPE_PICKOPTION`
> 老系统 DTO：`XBusiTypePickOption` | 老系统 PO：`BusiTypePickoption`
> 老系统存储：`p_custom_busitype_pickoption`
> 父元模型：busiType（通过 busiTypeApiKey 关联）
> 子元模型：无
> 状态：❌ 未迁移

## 概述

业务类型选项值定义不同业务类型下 PICKLIST 字段的可选选项子集和默认值。当 entity 启用了多业务类型时，同一个 PICKLIST 字段在不同业务类型下可以显示不同的选项范围，并设置不同的默认选项。

典型场景：
- 客户对象有"标准客户"和"PRM客户"两种业务类型
- "行业"字段在"标准客户"下显示全部选项，在"PRM客户"下只显示 IT/金融/制造业
- 不同业务类型下"行业"字段的默认值不同

## 老系统字段

| 老字段名 | Java 类型 | 说明 | 新 api_key |
|:---|:---|:---|:---|
| id | Long | 主键 | — |
| objectId | Long | 所属对象 ID | entityApiKey |
| busiTypeId | Long | 所属业务类型 ID | busiTypeApiKey |
| itemId | Long | 关联字段 ID | itemApiKey |
| optionCodes | String | 可选选项编码列表（逗号分隔） | optionCodes |
| defaultOptionCodes | String | 默认选项编码列表（逗号分隔） | defaultOptionCodes |
| namespace | String | 命名空间 | namespace |
| deleteFlg | Integer | 软删除 | deleteFlg |

## 新系统字段设计

| api_key | db_column | label | 类型 | 说明 |
|:---|:---|:---|:---|:---|
| namespace | namespace | 命名空间 | String | 固定列 |
| entityApiKey | entity_api_key | 所属对象 | String | 固定列 |
| apiKey | api_key | apiKey | String | 固定列 |
| label | label | 标签 | String | 固定列 |
| labelKey | label_key | 多语言Key | String | 固定列 |
| description | description | 描述 | String | 固定列 |
| customFlg | custom_flg | 自定义标记 | Integer(0/1) | 固定列（基类） |
| deleteFlg | delete_flg | 删除标记 | Integer(0/1) | 固定列（基类） |
| busiTypeApiKey | dbc_varchar1 | 业务类型apiKey | String | 关联 busiType |
| itemApiKey | dbc_varchar2 | 字段apiKey | String | 关联 item |
| optionCodes | dbc_varchar3 | 可选选项编码 | String | 逗号分隔 |
| defaultOptionCodes | dbc_varchar4 | 默认选项编码 | String | 逗号分隔 |
| createdBy | created_by | 创建人 | Long | 固定列 |
| createdAt | created_at | 创建时间 | Long | 固定列 |
| updatedBy | updated_by | 修改人 | Long | 固定列 |
| updatedAt | updated_at | 修改时间 | Long | 固定列 |

## p_meta_model 注册

| api_key | label | db_table | entity_dependency |
|:---|:---|:---|:---|
| busiTypePickOption | 业务类型选项值 | p_tenant_busi_type_pick_option | 1 |

## p_meta_link

| api_key | 父元模型 | 子元模型 | 关联字段 | 级联删除 |
|:---|:---|:---|:---|:---|
| busiType_to_pickOption | busiType | busiTypePickOption | busiTypeApiKey | 是 |

## 业务规则

- 同一 busiType + item 组合唯一（一个业务类型下一个字段只有一条配置）
- optionCodes 是该业务类型下该字段可选的 pickOption 编码子集
- defaultOptionCodes 必须是 optionCodes 的子集
- 仅 PICKLIST(4) 和 MULTIPICKLIST(16) 类型的字段可配置
- 删除 busiType 时级联删除其下所有 busiTypePickOption
