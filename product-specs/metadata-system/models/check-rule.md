# checkRule — 校验规则元模型

> 元模型 api_key：`checkRule`
> p_meta_model 注册：enable_common=1, enable_tenant=1, db_table=`p_tenant_check_rule`
> 父元模型：entity（通过 entityApiKey 关联）
> 子元模型：无
> Java Entity：`CheckRule.java` | API 模型：`XCheckRule.java`

## 概述
定义 entity 上的数据校验规则。当用户创建或更新记录时，系统根据 checkFormula 执行校验，不通过则返回 checkErrorMsg。

## 字段定义（18 个）

### 基础信息（固定列映射）

| api_key | db_column | label | 类型 | 说明 |
|:---|:---|:---|:---|:---|
| namespace | namespace | 命名空间 | String | — |
| entityApiKey | entity_api_key | 所属对象apiKey | String | 关联到父 entity |
| apiKey | api_key | 规则apiKey | String | 同一 entity 内唯一 |
| label | label | 规则标签 | String | — |
| labelKey | label_key | 规则标签Key | String | 国际化 |
| description | description | 描述 | String | — |

### 扩展属性（固定列映射）

| api_key | db_column | label | 类型 | 取值约束 |
|:---|:---|:---|:---|:---|
| activeFlg | active_flg | 激活状态 | Integer | 0=未激活, 1=已激活 |
| checkFormula | check_formula | 校验公式 | String | 公式表达式 |
| checkErrorMsg | check_error_msg | 错误提示信息 | String | — |
| checkErrorMsgKey | check_error_msg_key | 错误提示Key | String | 国际化 |
| checkErrorLocation | check_error_location | 错误显示位置 | Integer | — |
| checkErrorWay | check_error_way | 弱校验错误类型 | Integer | — |
| checkErrorItemApiKey | check_error_item_api_key | 错误关联字段apiKey | String | 同对象内的字段 |
| checkAllItemsFlg | check_all_items_flg | 全量更新标识 | Integer | 0=增量更新, 1=全量更新 |

### 审计字段

| api_key | db_column | 类型 |
|:---|:---|:---|
| createdBy | created_by | Long |
| createdAt | created_at | Long(毫秒) |
| updatedBy | updated_by | Long |
| updatedAt | updated_at | Long(毫秒) |

## 业务规则
- checkRule.apiKey 在同一 entity 内唯一
- activeFlg=0 时规则不执行
- checkFormula 使用平台公式语法
- checkErrorItemApiKey 指向同 entity 下的 item，用于在 UI 上定位错误字段
- 删除 entity 时级联删除其下所有 checkRule
