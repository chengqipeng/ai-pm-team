# entitySvg — 实体图标元模型

> 老系统常量：`MetaConstants.METAMODEL_ID_CUSTOM_SVG`
> 老系统 PO：`CustomSvg`（`p_custom_svg` 表）
> 新系统 api_key：`entitySvg`
> 父元模型：无（独立顶层，entity 通过 svgApiKey 引用）
> 支持 Common + Tenant 双层

## 概述

实体 SVG 图标是实体图标的基础资源元模型。每个 entity 通过 `svgApiKey` 字段引用一个 entitySvg 记录。Common 级存储系统预置图标，Tenant 级支持租户自定义图标。

## 新系统字段设计（16 字段）

| api_key | db_column | label | 类型 | 说明 |
|:---|:---|:---|:---|:---|
| namespace | namespace | 命名空间 | String | 固定列 |
| apiKey | api_key | 图标apiKey | String | 固定列（= svgClass） |
| label | label | 图标名称 | String | 固定列 |
| labelKey | label_key | 多语言Key | String | 固定列 |
| description | description | 描述 | String | 固定列 |
| customFlg | custom_flg | 自定义标记 | Integer(0/1) | 固定列（基类） |
| deleteFlg | delete_flg | 删除标记 | Integer(0/1) | 固定列（基类） |
| svgClass | dbc_varchar1 | CSS类名 | String | 如 icon-account |
| defaultColor | dbc_varchar2 | 默认颜色 | String | 如 #1890ff |
| viewBox | dbc_varchar3 | viewBox | String | 如 0 0 24 24 |
| svgCode | dbc_textarea1 | SVG代码（填充版） | String | 完整 SVG path |
| lineSvgCode | dbc_textarea2 | SVG代码（线条版） | String | 线条风格 SVG path |
| createdBy | created_by | 创建人 | Long | 固定列 |
| createdAt | created_at | 创建时间 | Long | 固定列 |
| updatedBy | updated_by | 修改人 | Long | 固定列 |
| updatedAt | updated_at | 修改时间 | Long | 固定列 |

## p_meta_model 注册

| api_key | label | enable_common | enable_tenant | entity_dependency | db_table |
|:---|:---|:---|:---|:---|:---|
| entitySvg | 实体图标 | 1 | 1 | 0 | p_tenant_entity_svg |

## 业务规则

- entitySvg 是独立顶层元模型，`entity_dependency = 0`
- entity.svgApiKey 引用 entitySvg.apiKey（= svgClass）
- Common 级存储系统预置图标，Tenant 级存储租户自定义图标
- 合并读取时 Tenant 覆盖 Common（同 apiKey）
