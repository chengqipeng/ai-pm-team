# item — 自定义字段元模型

> 元模型 api_key：`item`
> p_meta_model 注册：enable_common=1, enable_tenant=1, db_table=`p_tenant_item`
> 父元模型：entity（通过 entityApiKey 关联）
> 子元模型：pickOption（选项值）、referenceFilter（关联过滤）
> Java Entity：`EntityItem.java` | API 模型：`XEntityItem.java`

## 概述
定义 entity 上的字段（如 Name、Phone、Industry）。每个字段有类型（itemType）、存储列（dbColumn）、权限控制、关联配置等属性。item 是字段数最多的元模型（101 个），按功能域分组。

## 字段类型体系（ItemTypeEnum）

| 编码 | 名称 | dbColumnPrefix | 说明 |
|:---:|:---|:---|:---|
| 1 | TEXT | dbc_varchar | 文本 |
| 2 | NUMBER | dbc_bigint | 数字 |
| 3 | DATE | dbc_bigint | 日期 |
| 4 | PICKLIST | dbc_int | 单选 |
| 5 | LOOKUP | dbc_bigint | 查找关联 |
| 6 | FORMULA | null | 公式（不占物理列） |
| 7 | ROLLUP | null | 汇总（不占物理列） |
| 8 | TEXTAREA | dbc_textarea | 长文本 |
| 9 | BOOLEAN | dbc_smallint | 布尔 |
| 10 | CURRENCY | dbc_decimal | 货币 |
| 11 | PERCENT | dbc_decimal | 百分比 |
| 12 | EMAIL | dbc_varchar | 邮箱 |
| 13 | PHONE | dbc_varchar | 电话 |
| 14 | URL | dbc_varchar | URL |
| 15 | DATETIME | dbc_bigint | 日期时间 |
| 16 | MULTIPICKLIST | dbc_varchar | 多选 |
| 17 | MASTER_DETAIL | dbc_bigint | 主从关联 |
| 18 | GEOLOCATION | dbc_varchar | 地理位置 |
| 19 | IMAGE | dbc_varchar | 图片 |
| 20 | AUTONUMBER | dbc_varchar | 自动编号 |
| 21 | JOIN | null | 引用（不占物理列） |
| 22 | AUDIO | dbc_varchar | 语音 |
| 27 | COMPUTED | null | 计算字段（不占物理列） |

---

## 字段定义（按功能域分组）

### 基础信息（固定列映射）

| api_key | db_column | label | 类型 |
|:---|:---|:---|:---|
| namespace | namespace | 命名空间 | String |
| entityApiKey | entity_api_key | 所属对象apiKey | String |
| apiKey | api_key | 字段apiKey | String |
| label | label | 显示标签 | String |
| labelKey | label_key | 多语言Key | String |
| description | description | 描述 | String |
| customFlg | custom_flg | 是否定制 | Integer(0/1) |
| deleteFlg | delete_flg | 删除标识 | Integer(0/1) |

### 核心属性

| api_key | db_column | label | 类型 | 取值约束 |
|:---|:---|:---|:---|:---|
| itemType | dbc_int1 | 字段数据类型 | Integer | 见 ItemTypeEnum（23 种） |
| dataType | dbc_int2 | 底层数据类型 | Integer | — |
| itemOrder | dbc_int3 | 排序序号 | Integer | — |
| dbColumn | dbc_varchar3 | 数据库列名 | String | dbc_xxxN 格式 |
| helpText | dbc_varchar4 | 帮助文本 | String | — |
| helpTextKey | dbc_varchar5 | 帮助文本Key | String | 国际化 |
| descriptionKey | dbc_varchar6 | 描述Key | String | 国际化 |
| columnName | dbc_varchar7 | 列显示名 | String | — |
| defaultValue | dbc_textarea2 | 默认值 | String(长文本) | — |
| typeProperty | dbc_textarea1 | 类型扩展属性JSON | String(长文本) | — |

### 权限控制

| api_key | db_column | label | 类型 |
|:---|:---|:---|:---|
| requireFlg | dbc_smallint1 | 是否必填 | Integer(0/1) |
| enableFlg | dbc_smallint2 | 是否启用 | Integer(0/1) |
| hiddenFlg | dbc_smallint3 | 是否隐藏 | Integer(0/1) |
| uniqueKeyFlg | dbc_smallint4 | 是否唯一键 | Integer(0/1) |
| creatable | dbc_smallint5 | 新建时可赋值 | Integer(0/1) |
| updatable | dbc_smallint6 | 可更新 | Integer(0/1) |
| enableHistoryLog | dbc_smallint7 | 历史记录跟踪 | Integer(0/1) |
| enableDeactivate | dbc_smallint8 | 允许禁用 | Integer(0/1) |
| readonlyStatus | dbc_int4 | 只读状态 | Integer |
| visibleStatus | dbc_int5 | 可见状态 | Integer |
| enableSort | dbc_int6 | 允许排序 | Integer(0/1) |
| encryptFlg | dbc_smallint10 | 加密字段 | Integer(0/1) |
| markdownFlg | dbc_smallint11 | Markdown编辑器 | Integer(0/1) |
| enableReferItemFilter | dbc_smallint12 | 关联字段增强过滤 | Integer(0/1) |

### 关联/LOOKUP 相关

| api_key | db_column | label | 类型 |
|:---|:---|:---|:---|
| referEntityApiKey | dbc_varchar1 | 关联对象apiKey | String |
| referLinkApiKey | dbc_varchar2 | 关联Link apiKey | String |
| cascadeDelete | dbc_smallint22 | 级联删除规则 | Integer(0/1/2) |
| detailFlg | dbc_smallint23 | 是否明细实体 | Integer(0/1) |
| canBatchCreate | dbc_smallint24 | 允许批量新建 | Integer(0/1) |
| copyWithParentFlg | dbc_smallint25 | 随父复制 | Integer(0/1) |
| maskFlg | dbc_smallint26 | 是否掩码显示 | Integer(0/1) |
| enableMultiDetail | dbc_smallint27 | 启用多明细 | Integer(0/1) |
| batchCreateMode | dbc_int | 批量创建模式 | Integer |
| batchCreateLinkByBusinessType | dbc_smallint | 按业务类型批量创建 | Integer |
| joinItem | dbc_varchar12 | 引用字段 | String |
| joinObject | dbc_varchar13 | 引用实体 | String |
| joinLink | dbc_varchar14 | 引用Link | String |
| linkLabel | dbc_varchar15 | 关联标签 | String |
| referEntityApiKeys | dbc_varchar16 | 多态引用实体列表 | String(逗号分隔) |
| entityOrData | dbc_smallint | 多态属性标识 | Integer |
| groupKey | dbc_varchar17 | 多态分组Key | String |

### 选项集相关

| api_key | db_column | label | 类型 |
|:---|:---|:---|:---|
| referGlobal | dbc_smallint19 | 引用全局选项集 | Integer(0/1) |
| globalPickItem | dbc_varchar10 | 全局选项集apiKey | String |
| globalPickItemApiKey | dbc_varchar11 | 全局选项集apiKey | String |
| externalFlg | dbc_smallint20 | 外部选项源 | Integer(0/1) |

### 货币相关

| api_key | db_column | label | 类型 |
|:---|:---|:---|:---|
| currencyFlg | dbc_smallint13 | 是否货币 | Integer(0/1) |
| currencyPart | dbc_smallint14 | 货币组成 | Integer(1=本币, 2=原币) |
| multiCurrencyFlg | dbc_smallint15 | 多币种 | Integer(0/1) |
| computeMultiCurrencyUnit | dbc_varchar8 | 展示币种信息 | String |

### 公式/汇总相关

| api_key | db_column | label | 类型 |
|:---|:---|:---|:---|
| computeType | dbc_smallint17 | 计算结果子类型 | Integer |
| realTimeCompute | dbc_smallint18 | 实时计算 | Integer(0/1) |
| aggregateComputeType | dbc_varchar29 | 汇总计算结果类型 | String |

### 日期相关

| api_key | db_column | label | 类型 |
|:---|:---|:---|:---|
| dateMode | dbc_smallint21 | 日期模式 | Integer(1=仅日期, 2=日期+时间) |

### 自动编号相关

| api_key | db_column | label | 类型 |
|:---|:---|:---|:---|
| format | dbc_varchar9 | 编号格式 | String |
| startNumber | dbc_varchar23 | 起始值 | String |
| incrementStrategy | dbc_int12 | 递增策略 | Integer |
| dataFormat | dbc_varchar22 | 编号数据格式 | String |

### 文本/长度相关

| api_key | db_column | label | 类型 |
|:---|:---|:---|:---|
| maxLength | dbc_int13 | 最大长度 | Integer |
| minLength | dbc_int14 | 最小长度 | Integer |
| decimal | dbc_int15 | 小数位数 | Integer |
| multiLineText | dbc_smallint29 | 多行文本 | Integer(0/1) |
| scanCodeEntryFlg | dbc_smallint | 扫码录入 | Integer(0/1) |
| caseSensitive | dbc_smallint | 大小写敏感 | Integer(0/1) |
| showRows | dbc_smallint | 富文本显示行数 | Integer |

### 掩码相关

| api_key | db_column | label | 类型 |
|:---|:---|:---|:---|
| maskPrefix | dbc_int7 | 掩码前缀字符数 | Integer |
| maskSuffix | dbc_int8 | 掩码后缀字符数 | Integer |
| maskSymbolType | dbc_int11 | 掩码字符类型 | Integer |

### 图片水印相关

| api_key | db_column | label | 类型 |
|:---|:---|:---|:---|
| watermarkFlg | dbc_smallint30 | 水印开关 | Integer(0/1) |
| watermarkTimeFlg | dbc_smallint31 | 水印时间 | Integer(0/1) |
| watermarkLoginUserFlg | dbc_smallint32 | 水印登录用户 | Integer(0/1) |
| watermarkLocationFlg | dbc_smallint33 | 水印定位 | Integer(0/1) |
| watermarkJoinField | dbc_varchar19 | 水印引用字段apiKey | String |

### 复合字段相关

| api_key | db_column | label | 类型 |
|:---|:---|:---|:---|
| compoundFlg | dbc_smallint9 | 是否复合字段 | Integer(0/1) |
| compoundSubFlg | dbc_smallint28 | 复合子字段 | Integer(0/1) |
| compoundApiKey | dbc_varchar18 | 复合字段apiKey | String |

### 索引/配置

| api_key | db_column | label | 类型 |
|:---|:---|:---|:---|
| indexType | dbc_int10 | 索引类型 | Integer |
| indexOrder | dbc_int9 | 索引顺序 | Integer |
| customItemSeq | dbc_bigint1 | 字段排序号 | Long |
| enableConfig | dbc_bigint2 | 配置位掩码 | Long |
| enablePackage | dbc_bigint3 | 包配置位掩码 | Long |

---

## 唯一性
- item.apiKey 在同一 entity 内唯一
- 定位方式：entity_api_key + api_key

## 层级关系
```
item（字段）
  ├── pickOption（选项值）   ← itemApiKey 关联，级联删除
  └── referenceFilter（过滤）← itemApiKey 关联，级联删除
```

## 业务规则
- itemType 决定 dbColumnPrefix，进而决定存储在大宽表的哪类扩展列
- FORMULA(6)/ROLLUP(7)/JOIN(21)/COMPUTED(27) 不占物理列，dbColumn 为 NULL
- 同一 entity 内同前缀的 dbColumn 按 itemOrder 递增分配
- 删除 item 时级联删除其下所有 pickOption 和 referenceFilter
