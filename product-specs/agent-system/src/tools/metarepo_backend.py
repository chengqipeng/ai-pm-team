"""
Metarepo 模拟后端 — 对齐 paas-platform-service / paas-metarepo-service 三层数据模型

镜像 MetamodelBrowseApiService 的数据语义：
  第一层 p_meta_model    ——  元模型注册
  第二层 p_meta_item     ——  元模型字段定义（含 dbc_xxxN 列映射）
        p_meta_link     ——  元模型间关联
        p_meta_option   ——  枚举字段合法取值
  第三层 p_common_metadata + p_tenant_metadata 合并后的元数据实例
        （本模块内直接以 merged 形式提供，不再区分 Common / Tenant）

对外暴露的方法与 MetamodelBrowseApiService 的 @GetMapping 基本一一对应。
"""
from __future__ import annotations

import copy
from typing import Any, Optional


# ═══════════════════════════════════════════════════════════
# ItemTypeEnum —— 对齐 com.hongyang.framework.common.enums.paas.ItemTypeEnum
# ═══════════════════════════════════════════════════════════

ITEM_TYPE_MAPPING: list[dict[str, Any]] = [
    {"code": "VARCHAR",      "name": "VARCHAR",      "description": "短文本",       "dbColumnPrefix": "dbc_varchar",  "isCompute": False, "isVirtual": False, "dataTypeCode": "STRING",   "dataTypeLabel": "字符串", "javaType": "String"},
    {"code": "TEXT",         "name": "TEXT",         "description": "长文本",       "dbColumnPrefix": "dbc_text",     "isCompute": False, "isVirtual": False, "dataTypeCode": "STRING",   "dataTypeLabel": "字符串", "javaType": "String"},
    {"code": "INTEGER",      "name": "INTEGER",      "description": "整数",         "dbColumnPrefix": "dbc_int",      "isCompute": False, "isVirtual": False, "dataTypeCode": "INT",      "dataTypeLabel": "整数",   "javaType": "Integer"},
    {"code": "LONG",         "name": "LONG",         "description": "长整数",       "dbColumnPrefix": "dbc_bigint",   "isCompute": False, "isVirtual": False, "dataTypeCode": "LONG",     "dataTypeLabel": "长整数", "javaType": "Long"},
    {"code": "DECIMAL",      "name": "DECIMAL",      "description": "金额/小数",    "dbColumnPrefix": "dbc_decimal",  "isCompute": False, "isVirtual": False, "dataTypeCode": "DECIMAL",  "dataTypeLabel": "小数",   "javaType": "BigDecimal"},
    {"code": "DATE",         "name": "DATE",         "description": "日期",         "dbColumnPrefix": "dbc_date",     "isCompute": False, "isVirtual": False, "dataTypeCode": "DATE",     "dataTypeLabel": "日期",   "javaType": "LocalDate"},
    {"code": "DATETIME",     "name": "DATETIME",     "description": "日期时间",     "dbColumnPrefix": "dbc_datetime", "isCompute": False, "isVirtual": False, "dataTypeCode": "DATETIME", "dataTypeLabel": "日期时间", "javaType": "LocalDateTime"},
    {"code": "BOOLEAN_FLG",  "name": "BOOLEAN_FLG",  "description": "布尔标记",     "dbColumnPrefix": "dbc_smallint", "isCompute": False, "isVirtual": False, "dataTypeCode": "INT",      "dataTypeLabel": "整数",   "javaType": "Integer"},
    {"code": "PICK_LIST",    "name": "PICK_LIST",    "description": "选项集",       "dbColumnPrefix": "dbc_varchar",  "isCompute": False, "isVirtual": False, "dataTypeCode": "STRING",   "dataTypeLabel": "字符串", "javaType": "String"},
    {"code": "RELATIONSHIP", "name": "RELATIONSHIP", "description": "关联字段",     "dbColumnPrefix": "dbc_varchar",  "isCompute": False, "isVirtual": False, "dataTypeCode": "STRING",   "dataTypeLabel": "字符串", "javaType": "String"},
    {"code": "FORMULA",      "name": "FORMULA",      "description": "公式计算字段", "dbColumnPrefix": "",             "isCompute": True,  "isVirtual": True,  "dataTypeCode": "DECIMAL",  "dataTypeLabel": "小数",   "javaType": "BigDecimal"},
    {"code": "AGGREGATION",  "name": "AGGREGATION",  "description": "汇总累计",     "dbColumnPrefix": "",             "isCompute": True,  "isVirtual": True,  "dataTypeCode": "DECIMAL",  "dataTypeLabel": "小数",   "javaType": "BigDecimal"},
]


# ═══════════════════════════════════════════════════════════
# p_meta_model —— 元模型注册
# ═══════════════════════════════════════════════════════════

META_MODELS: list[dict[str, Any]] = [
    {"apiKey": "entity",           "label": "业务对象",       "dbTable": "p_tenant_entity",           "enableCommon": 1, "enableUiConfig": 1, "metamodelLayer": "L1", "enableDataSource": 1, "sortNum": 10},
    {"apiKey": "item",             "label": "业务对象字段",   "dbTable": "p_tenant_item",             "enableCommon": 1, "enableUiConfig": 1, "metamodelLayer": "L2", "enableDataSource": 1, "sortNum": 20},
    {"apiKey": "entityLink",       "label": "业务对象关联",   "dbTable": "p_tenant_entity_link",      "enableCommon": 1, "enableUiConfig": 1, "metamodelLayer": "L2", "enableDataSource": 0, "sortNum": 30},
    {"apiKey": "pickOption",       "label": "选项值",         "dbTable": "p_tenant_pick_option",      "enableCommon": 1, "enableUiConfig": 1, "metamodelLayer": "L3", "enableDataSource": 0, "sortNum": 40},
    {"apiKey": "globalPickOption", "label": "全局选项集",     "dbTable": "p_tenant_global_pick_option","enableCommon": 1, "enableUiConfig": 1, "metamodelLayer": "L1", "enableDataSource": 0, "sortNum": 50},
    {"apiKey": "checkRule",        "label": "校验规则",       "dbTable": "p_tenant_check_rule",       "enableCommon": 1, "enableUiConfig": 1, "metamodelLayer": "L2", "enableDataSource": 0, "sortNum": 60},
    {"apiKey": "busiType",         "label": "业务类型",       "dbTable": "p_tenant_busi_type",        "enableCommon": 1, "enableUiConfig": 1, "metamodelLayer": "L2", "enableDataSource": 0, "sortNum": 70},
    {"apiKey": "role",             "label": "角色",           "dbTable": "p_tenant_role",             "enableCommon": 0, "enableUiConfig": 1, "metamodelLayer": "L1", "enableDataSource": 1, "sortNum": 80},
    {"apiKey": "department",       "label": "部门",           "dbTable": "p_tenant_department",       "enableCommon": 0, "enableUiConfig": 1, "metamodelLayer": "L1", "enableDataSource": 1, "sortNum": 90},
    {"apiKey": "sharingRule",      "label": "共享规则",       "dbTable": "p_tenant_sharing_rule",     "enableCommon": 0, "enableUiConfig": 1, "metamodelLayer": "L2", "enableDataSource": 0, "sortNum": 100},
    {"apiKey": "dataPermission",   "label": "数据权限配置",   "dbTable": "p_tenant_data_permission",  "enableCommon": 0, "enableUiConfig": 1, "metamodelLayer": "L2", "enableDataSource": 0, "sortNum": 110},
]


# ═══════════════════════════════════════════════════════════
# p_meta_item —— 元模型字段定义（含 dbc 列映射）
# 按 metamodelApiKey 分桶
# ═══════════════════════════════════════════════════════════

META_ITEMS: dict[str, list[dict[str, Any]]] = {
    "entity": [
        {"apiKey": "apiKey",      "label": "apiKey",     "labelKey": "meta.entity.apiKey",      "itemType": "VARCHAR",     "dbColumn": "dbc_varchar1",  "requireFlg": 1, "uniqueFlg": 1, "maxLength": 64,   "sortNum": 1},
        {"apiKey": "label",       "label": "名称",       "labelKey": "meta.entity.label",       "itemType": "VARCHAR",     "dbColumn": "dbc_varchar2",  "requireFlg": 1, "uniqueFlg": 0, "maxLength": 128,  "sortNum": 2},
        {"apiKey": "labelKey",    "label": "国际化 key", "labelKey": "meta.entity.labelKey",    "itemType": "VARCHAR",     "dbColumn": "dbc_varchar3",  "requireFlg": 0, "uniqueFlg": 0, "maxLength": 128,  "sortNum": 3},
        {"apiKey": "description", "label": "描述",       "labelKey": "meta.entity.description", "itemType": "TEXT",        "dbColumn": "dbc_text1",     "requireFlg": 0, "uniqueFlg": 0, "maxLength": 2000, "sortNum": 4},
        {"apiKey": "iconName",    "label": "图标",       "labelKey": "meta.entity.iconName",    "itemType": "VARCHAR",     "dbColumn": "dbc_varchar4",  "requireFlg": 0, "uniqueFlg": 0, "maxLength": 64,   "sortNum": 5},
        {"apiKey": "sortNum",     "label": "排序",       "labelKey": "meta.entity.sortNum",     "itemType": "INTEGER",     "dbColumn": "dbc_int1",      "requireFlg": 0, "uniqueFlg": 0, "sortNum": 6},
        {"apiKey": "enableFlg",   "label": "启用标记",   "labelKey": "meta.entity.enableFlg",   "itemType": "BOOLEAN_FLG", "dbColumn": "dbc_smallint1", "requireFlg": 1, "uniqueFlg": 0, "sortNum": 7},
        {"apiKey": "customFlg",   "label": "自定义标记", "labelKey": "meta.entity.customFlg",   "itemType": "BOOLEAN_FLG", "dbColumn": "dbc_smallint2", "requireFlg": 0, "uniqueFlg": 0, "sortNum": 8},
        {"apiKey": "namespace",   "label": "命名空间",   "labelKey": "meta.entity.namespace",   "itemType": "PICK_LIST",   "dbColumn": "dbc_varchar5",  "requireFlg": 1, "uniqueFlg": 0, "sortNum": 9},
    ],
    "item": [
        {"apiKey": "entityApiKey", "label": "业务对象",     "itemType": "RELATIONSHIP", "dbColumn": "dbc_varchar1",  "requireFlg": 1, "uniqueFlg": 0, "maxLength": 64,  "sortNum": 1},
        {"apiKey": "apiKey",       "label": "字段 apiKey",  "itemType": "VARCHAR",      "dbColumn": "dbc_varchar2",  "requireFlg": 1, "uniqueFlg": 0, "maxLength": 64,  "sortNum": 2},
        {"apiKey": "label",        "label": "字段名称",     "itemType": "VARCHAR",      "dbColumn": "dbc_varchar3",  "requireFlg": 1, "uniqueFlg": 0, "maxLength": 128, "sortNum": 3},
        {"apiKey": "itemType",     "label": "字段类型",     "itemType": "PICK_LIST",    "dbColumn": "dbc_varchar4",  "requireFlg": 1, "uniqueFlg": 0, "sortNum": 4},
        {"apiKey": "dbColumn",     "label": "物理列名",     "itemType": "VARCHAR",      "dbColumn": "dbc_varchar5",  "requireFlg": 0, "uniqueFlg": 0, "maxLength": 64,  "sortNum": 5},
        {"apiKey": "requireFlg",   "label": "必填标记",     "itemType": "BOOLEAN_FLG",  "dbColumn": "dbc_smallint1", "requireFlg": 0, "uniqueFlg": 0, "sortNum": 6},
        {"apiKey": "uniqueFlg",    "label": "唯一标记",     "itemType": "BOOLEAN_FLG",  "dbColumn": "dbc_smallint2", "requireFlg": 0, "uniqueFlg": 0, "sortNum": 7},
        {"apiKey": "maxLength",    "label": "最大长度",     "itemType": "INTEGER",      "dbColumn": "dbc_int1",      "requireFlg": 0, "uniqueFlg": 0, "sortNum": 8},
        {"apiKey": "decimalPlaces","label": "小数位",       "itemType": "INTEGER",      "dbColumn": "dbc_int2",      "requireFlg": 0, "uniqueFlg": 0, "sortNum": 9},
        {"apiKey": "defaultValue", "label": "默认值",       "itemType": "VARCHAR",      "dbColumn": "dbc_varchar6",  "requireFlg": 0, "uniqueFlg": 0, "sortNum": 10},
    ],
    "pickOption": [
        {"apiKey": "entityApiKey", "label": "业务对象",   "itemType": "RELATIONSHIP", "dbColumn": "dbc_varchar1", "requireFlg": 1, "uniqueFlg": 0, "sortNum": 1},
        {"apiKey": "itemApiKey",   "label": "字段",       "itemType": "RELATIONSHIP", "dbColumn": "dbc_varchar2", "requireFlg": 1, "uniqueFlg": 0, "sortNum": 2},
        {"apiKey": "apiKey",       "label": "选项 apiKey","itemType": "VARCHAR",      "dbColumn": "dbc_varchar3", "requireFlg": 1, "uniqueFlg": 0, "sortNum": 3},
        {"apiKey": "label",        "label": "选项名",     "itemType": "VARCHAR",      "dbColumn": "dbc_varchar4", "requireFlg": 1, "uniqueFlg": 0, "sortNum": 4},
        {"apiKey": "optionOrder",  "label": "排序",       "itemType": "INTEGER",      "dbColumn": "dbc_int1",     "requireFlg": 0, "uniqueFlg": 0, "sortNum": 5},
        {"apiKey": "defaultFlg",   "label": "默认选项",   "itemType": "BOOLEAN_FLG",  "dbColumn": "dbc_smallint1","requireFlg": 0, "uniqueFlg": 0, "sortNum": 6},
    ],
    "entityLink": [
        {"apiKey": "apiKey",             "label": "关联 apiKey", "itemType": "VARCHAR",      "dbColumn": "dbc_varchar1", "requireFlg": 1, "uniqueFlg": 1, "sortNum": 1},
        {"apiKey": "parentEntityApiKey", "label": "父对象",     "itemType": "RELATIONSHIP", "dbColumn": "dbc_varchar2", "requireFlg": 1, "uniqueFlg": 0, "sortNum": 2},
        {"apiKey": "childEntityApiKey",  "label": "子对象",     "itemType": "RELATIONSHIP", "dbColumn": "dbc_varchar3", "requireFlg": 1, "uniqueFlg": 0, "sortNum": 3},
        {"apiKey": "linkType",           "label": "关联类型",   "itemType": "PICK_LIST",    "dbColumn": "dbc_varchar4", "requireFlg": 1, "uniqueFlg": 0, "sortNum": 4},
        {"apiKey": "cascadeDelete",      "label": "级联删除",   "itemType": "BOOLEAN_FLG",  "dbColumn": "dbc_smallint1","requireFlg": 0, "uniqueFlg": 0, "sortNum": 5},
    ],
    "checkRule": [
        {"apiKey": "entityApiKey", "label": "业务对象", "itemType": "RELATIONSHIP","dbColumn": "dbc_varchar1","requireFlg": 1, "sortNum": 1},
        {"apiKey": "apiKey",       "label": "规则 apiKey","itemType": "VARCHAR",   "dbColumn": "dbc_varchar2","requireFlg": 1, "sortNum": 2},
        {"apiKey": "label",        "label": "规则名",   "itemType": "VARCHAR",     "dbColumn": "dbc_varchar3","requireFlg": 1, "sortNum": 3},
        {"apiKey": "expression",   "label": "规则表达式","itemType": "TEXT",       "dbColumn": "dbc_text1",   "requireFlg": 1, "sortNum": 4},
        {"apiKey": "errorMessage", "label": "错误提示", "itemType": "VARCHAR",     "dbColumn": "dbc_varchar4","requireFlg": 1, "sortNum": 5},
    ],
    "busiType": [
        {"apiKey": "entityApiKey", "label": "业务对象", "itemType": "RELATIONSHIP","dbColumn": "dbc_varchar1","requireFlg": 1, "sortNum": 1},
        {"apiKey": "apiKey",       "label": "apiKey",   "itemType": "VARCHAR",     "dbColumn": "dbc_varchar2","requireFlg": 1, "sortNum": 2},
        {"apiKey": "label",        "label": "业务类型名","itemType": "VARCHAR",    "dbColumn": "dbc_varchar3","requireFlg": 1, "sortNum": 3},
        {"apiKey": "defaultFlg",   "label": "默认类型", "itemType": "BOOLEAN_FLG", "dbColumn": "dbc_smallint1","requireFlg": 0, "sortNum": 4},
    ],
    "role": [
        {"apiKey": "apiKey",      "label": "角色 apiKey","itemType": "VARCHAR",    "dbColumn": "dbc_varchar1","requireFlg": 1, "uniqueFlg": 1, "sortNum": 1},
        {"apiKey": "label",       "label": "角色名",    "itemType": "VARCHAR",    "dbColumn": "dbc_varchar2","requireFlg": 1, "sortNum": 2},
        {"apiKey": "parentApiKey","label": "父角色",    "itemType": "RELATIONSHIP","dbColumn": "dbc_varchar3","requireFlg": 0, "sortNum": 3},
        {"apiKey": "description", "label": "描述",      "itemType": "TEXT",       "dbColumn": "dbc_text1",   "requireFlg": 0, "sortNum": 4},
    ],
    "department": [
        {"apiKey": "apiKey",      "label": "部门 apiKey","itemType": "VARCHAR",    "dbColumn": "dbc_varchar1","requireFlg": 1, "uniqueFlg": 1, "sortNum": 1},
        {"apiKey": "label",       "label": "部门名",    "itemType": "VARCHAR",    "dbColumn": "dbc_varchar2","requireFlg": 1, "sortNum": 2},
        {"apiKey": "parentApiKey","label": "上级部门",  "itemType": "RELATIONSHIP","dbColumn": "dbc_varchar3","requireFlg": 0, "sortNum": 3},
        {"apiKey": "leaderUserId","label": "负责人",    "itemType": "LONG",       "dbColumn": "dbc_bigint1", "requireFlg": 0, "sortNum": 4},
    ],
}


# ═══════════════════════════════════════════════════════════
# p_meta_link —— 元模型间关联
# ═══════════════════════════════════════════════════════════

META_LINKS: list[dict[str, Any]] = [
    {"apiKey": "entity_to_item",        "parentMetamodelApiKey": "entity", "childMetamodelApiKey": "item",        "linkType": "ONE_TO_MANY", "cascadeDelete": 1},
    {"apiKey": "entity_to_entityLink",  "parentMetamodelApiKey": "entity", "childMetamodelApiKey": "entityLink",  "linkType": "ONE_TO_MANY", "cascadeDelete": 1},
    {"apiKey": "entity_to_checkRule",   "parentMetamodelApiKey": "entity", "childMetamodelApiKey": "checkRule",   "linkType": "ONE_TO_MANY", "cascadeDelete": 1},
    {"apiKey": "entity_to_busiType",    "parentMetamodelApiKey": "entity", "childMetamodelApiKey": "busiType",    "linkType": "ONE_TO_MANY", "cascadeDelete": 1},
    {"apiKey": "item_to_pickOption",    "parentMetamodelApiKey": "item",   "childMetamodelApiKey": "pickOption",  "linkType": "ONE_TO_MANY", "cascadeDelete": 1},
    {"apiKey": "role_hierarchy",        "parentMetamodelApiKey": "role",   "childMetamodelApiKey": "role",        "linkType": "SELF_REF",    "cascadeDelete": 0},
    {"apiKey": "department_hierarchy",  "parentMetamodelApiKey": "department","childMetamodelApiKey": "department","linkType": "SELF_REF", "cascadeDelete": 0},
]


# ═══════════════════════════════════════════════════════════
# p_meta_option —— 元模型枚举字段合法取值
# ═══════════════════════════════════════════════════════════

META_OPTIONS: list[dict[str, Any]] = [
    # entity.namespace
    {"metamodelApiKey": "entity", "itemApiKey": "namespace", "optionCode": "system",  "label": "系统出厂", "optionOrder": 1},
    {"metamodelApiKey": "entity", "itemApiKey": "namespace", "optionCode": "product", "label": "业务产品", "optionOrder": 2},
    {"metamodelApiKey": "entity", "itemApiKey": "namespace", "optionCode": "custom",  "label": "租户自定义","optionOrder": 3},
    # item.itemType（列出常用的 5 个即可，完整列表见 ITEM_TYPE_MAPPING）
    {"metamodelApiKey": "item", "itemApiKey": "itemType", "optionCode": "VARCHAR",      "label": "短文本",   "optionOrder": 1},
    {"metamodelApiKey": "item", "itemApiKey": "itemType", "optionCode": "INTEGER",      "label": "整数",     "optionOrder": 2},
    {"metamodelApiKey": "item", "itemApiKey": "itemType", "optionCode": "DECIMAL",      "label": "小数",     "optionOrder": 3},
    {"metamodelApiKey": "item", "itemApiKey": "itemType", "optionCode": "PICK_LIST",    "label": "选项集",   "optionOrder": 4},
    {"metamodelApiKey": "item", "itemApiKey": "itemType", "optionCode": "RELATIONSHIP", "label": "关联字段", "optionOrder": 5},
    # entityLink.linkType
    {"metamodelApiKey": "entityLink", "itemApiKey": "linkType", "optionCode": "ONE_TO_ONE",  "label": "一对一", "optionOrder": 1},
    {"metamodelApiKey": "entityLink", "itemApiKey": "linkType", "optionCode": "ONE_TO_MANY", "label": "一对多", "optionOrder": 2},
    {"metamodelApiKey": "entityLink", "itemApiKey": "linkType", "optionCode": "MANY_TO_MANY","label": "多对多", "optionOrder": 3},
    {"metamodelApiKey": "entityLink", "itemApiKey": "linkType", "optionCode": "SELF_REF",    "label": "自关联", "optionOrder": 4},
]


# ═══════════════════════════════════════════════════════════
# 元数据实例（Common + Tenant 合并后的结果）
# ═══════════════════════════════════════════════════════════

METADATA_INSTANCES: dict[str, list[dict[str, Any]]] = {
    "entity": [
        {"apiKey": "account",     "label": "客户",     "iconName": "customer",    "sortNum": 10, "enableFlg": 1, "customFlg": 0, "namespace": "product"},
        {"apiKey": "contact",     "label": "联系人",   "iconName": "contact",     "sortNum": 20, "enableFlg": 1, "customFlg": 0, "namespace": "product"},
        {"apiKey": "opportunity", "label": "商机",     "iconName": "opportunity", "sortNum": 30, "enableFlg": 1, "customFlg": 0, "namespace": "product"},
        {"apiKey": "activity",    "label": "活动",     "iconName": "activity",    "sortNum": 40, "enableFlg": 1, "customFlg": 0, "namespace": "product"},
        {"apiKey": "lead",        "label": "线索",     "iconName": "lead",        "sortNum": 50, "enableFlg": 1, "customFlg": 0, "namespace": "product"},
        {"apiKey": "customOrder", "label": "定制订单", "iconName": "custom",      "sortNum": 60, "enableFlg": 1, "customFlg": 1, "namespace": "custom"},
    ],
    "item": [
        # account 的字段
        {"apiKey": "name",          "entityApiKey": "account", "label": "公司名称", "itemType": "VARCHAR",     "dbColumn": "dbc_varchar1", "requireFlg": 1, "uniqueFlg": 0, "maxLength": 200},
        {"apiKey": "industry",      "entityApiKey": "account", "label": "行业",     "itemType": "PICK_LIST",   "dbColumn": "dbc_varchar2", "requireFlg": 0, "uniqueFlg": 0},
        {"apiKey": "employeeCount", "entityApiKey": "account", "label": "员工数",   "itemType": "INTEGER",     "dbColumn": "dbc_int1",     "requireFlg": 0, "uniqueFlg": 0},
        {"apiKey": "annualRevenue", "entityApiKey": "account", "label": "年营收",   "itemType": "DECIMAL",     "dbColumn": "dbc_decimal1", "requireFlg": 0, "uniqueFlg": 0},
        {"apiKey": "activeFlg",     "entityApiKey": "account", "label": "是否活跃", "itemType": "BOOLEAN_FLG", "dbColumn": "dbc_smallint1","requireFlg": 0, "uniqueFlg": 0},
        # opportunity 的字段
        {"apiKey": "name",       "entityApiKey": "opportunity", "label": "商机名称", "itemType": "VARCHAR",   "dbColumn": "dbc_varchar1", "requireFlg": 1, "uniqueFlg": 0, "maxLength": 200},
        {"apiKey": "accountId",  "entityApiKey": "opportunity", "label": "所属客户", "itemType": "RELATIONSHIP","dbColumn": "dbc_varchar2", "requireFlg": 1, "uniqueFlg": 0},
        {"apiKey": "amount",     "entityApiKey": "opportunity", "label": "金额",     "itemType": "DECIMAL",   "dbColumn": "dbc_decimal1", "requireFlg": 0, "uniqueFlg": 0},
        {"apiKey": "stage",      "entityApiKey": "opportunity", "label": "阶段",     "itemType": "PICK_LIST", "dbColumn": "dbc_varchar3", "requireFlg": 1, "uniqueFlg": 0},
        {"apiKey": "closeDate",  "entityApiKey": "opportunity", "label": "预计关闭日期", "itemType": "DATE",  "dbColumn": "dbc_date1",    "requireFlg": 0, "uniqueFlg": 0},
        # contact 的字段
        {"apiKey": "name",       "entityApiKey": "contact", "label": "姓名",     "itemType": "VARCHAR",     "dbColumn": "dbc_varchar1", "requireFlg": 1, "uniqueFlg": 0, "maxLength": 64},
        {"apiKey": "accountId",  "entityApiKey": "contact", "label": "所属客户", "itemType": "RELATIONSHIP","dbColumn": "dbc_varchar2", "requireFlg": 1, "uniqueFlg": 0},
        {"apiKey": "phone",      "entityApiKey": "contact", "label": "电话",     "itemType": "VARCHAR",     "dbColumn": "dbc_varchar3", "requireFlg": 0, "uniqueFlg": 0, "maxLength": 32},
    ],
    "entityLink": [
        {"apiKey": "account_to_contact",     "parentEntityApiKey": "account",     "childEntityApiKey": "contact",     "linkType": "ONE_TO_MANY", "cascadeDelete": 0},
        {"apiKey": "account_to_opportunity", "parentEntityApiKey": "account",     "childEntityApiKey": "opportunity", "linkType": "ONE_TO_MANY", "cascadeDelete": 0},
        {"apiKey": "opportunity_to_activity","parentEntityApiKey": "opportunity", "childEntityApiKey": "activity",    "linkType": "ONE_TO_MANY", "cascadeDelete": 0},
    ],
    "pickOption": [
        {"apiKey": "industry_telecom",  "entityApiKey": "account",     "itemApiKey": "industry", "label": "通信设备", "optionOrder": 1, "defaultFlg": 0},
        {"apiKey": "industry_internet", "entityApiKey": "account",     "itemApiKey": "industry", "label": "互联网",   "optionOrder": 2, "defaultFlg": 0},
        {"apiKey": "industry_finance",  "entityApiKey": "account",     "itemApiKey": "industry", "label": "金融",     "optionOrder": 3, "defaultFlg": 0},
        {"apiKey": "stage_prospecting", "entityApiKey": "opportunity", "itemApiKey": "stage",    "label": "勘察",     "optionOrder": 1, "defaultFlg": 1},
        {"apiKey": "stage_proposal",    "entityApiKey": "opportunity", "itemApiKey": "stage",    "label": "方案",     "optionOrder": 2, "defaultFlg": 0},
        {"apiKey": "stage_negotiation", "entityApiKey": "opportunity", "itemApiKey": "stage",    "label": "谈判",     "optionOrder": 3, "defaultFlg": 0},
        {"apiKey": "stage_won",         "entityApiKey": "opportunity", "itemApiKey": "stage",    "label": "赢单",     "optionOrder": 4, "defaultFlg": 0},
        {"apiKey": "stage_lost",        "entityApiKey": "opportunity", "itemApiKey": "stage",    "label": "丢单",     "optionOrder": 5, "defaultFlg": 0},
    ],
    "checkRule": [
        {"apiKey": "account_name_required", "entityApiKey": "account",     "label": "客户名必填", "expression": "name != null && name != ''", "errorMessage": "客户名称不能为空"},
        {"apiKey": "opp_amount_positive",   "entityApiKey": "opportunity", "label": "商机金额为正","expression": "amount > 0",                 "errorMessage": "商机金额必须大于 0"},
    ],
    "busiType": [
        {"apiKey": "account_standard",   "entityApiKey": "account",     "label": "标准客户", "defaultFlg": 1},
        {"apiKey": "account_strategic",  "entityApiKey": "account",     "label": "战略客户", "defaultFlg": 0},
        {"apiKey": "opp_new_business",   "entityApiKey": "opportunity", "label": "新业务",   "defaultFlg": 1},
        {"apiKey": "opp_renewal",        "entityApiKey": "opportunity", "label": "续签",     "defaultFlg": 0},
    ],
    "role": [
        {"apiKey": "admin",         "label": "系统管理员", "parentApiKey": None,          "description": "全部权限"},
        {"apiKey": "salesManager",  "label": "销售经理",   "parentApiKey": "admin",       "description": "管理本部门销售人员"},
        {"apiKey": "salesRep",      "label": "销售代表",   "parentApiKey": "salesManager","description": "管理自己的客户"},
    ],
    "department": [
        {"apiKey": "headquarters",  "label": "总部",       "parentApiKey": None,           "leaderUserId": 1001},
        {"apiKey": "salesNorth",    "label": "华北销售部", "parentApiKey": "headquarters", "leaderUserId": 1002},
        {"apiKey": "salesSouth",    "label": "华南销售部", "parentApiKey": "headquarters", "leaderUserId": 1003},
    ],
}


# ═══════════════════════════════════════════════════════════
# MetarepoSimulatedBackend
# ═══════════════════════════════════════════════════════════

class MetarepoSimulatedBackend:
    """
    模拟 paas-metarepo-service，提供元模型与元数据的只读查询能力。

    对应 MetamodelBrowseApiService 的接口：
      - list_metamodels     ↔ GET /meta/metamodels
      - list_meta_items     ↔ GET /meta/meta-items
      - column_mapping      ↔ GET /meta/column-mapping
      - list_meta_links     ↔ GET /meta/meta-links
      - list_meta_options   ↔ GET /meta/meta-options
      - item_type_mapping   ↔ GET /meta/item-type-mapping
      - list_metadata       ↔ GET /meta/metadata
      - get_metamodel       ↔ (by apiKey) 补充查询
    """

    def __init__(self):
        self._meta_models = copy.deepcopy(META_MODELS)
        self._meta_items = copy.deepcopy(META_ITEMS)
        self._meta_links = copy.deepcopy(META_LINKS)
        self._meta_options = copy.deepcopy(META_OPTIONS)
        self._metadata = copy.deepcopy(METADATA_INSTANCES)

    # ─── 元模型层 ───

    def list_metamodels(self) -> list[dict[str, Any]]:
        return [copy.deepcopy(m) for m in sorted(self._meta_models, key=lambda x: x.get("sortNum", 0))]

    def get_metamodel(self, metamodel_api_key: str) -> Optional[dict[str, Any]]:
        for m in self._meta_models:
            if m["apiKey"] == metamodel_api_key:
                return copy.deepcopy(m)
        return None

    def list_meta_items(self, metamodel_api_key: str) -> list[dict[str, Any]]:
        items = self._meta_items.get(metamodel_api_key, [])
        return [copy.deepcopy(i) for i in sorted(items, key=lambda x: x.get("sortNum", 0))]

    def get_column_mapping(self, metamodel_api_key: str) -> dict[str, str]:
        mapping: dict[str, str] = {}
        for item in self._meta_items.get(metamodel_api_key, []):
            db_col = item.get("dbColumn")
            api_key = item.get("apiKey")
            if db_col and api_key:
                mapping[db_col] = api_key
        return mapping

    def list_meta_links(self, metamodel_api_key: Optional[str] = None) -> list[dict[str, Any]]:
        links = self._meta_links
        if metamodel_api_key:
            links = [
                l for l in links
                if l.get("parentMetamodelApiKey") == metamodel_api_key
                or l.get("childMetamodelApiKey") == metamodel_api_key
            ]
        return [copy.deepcopy(l) for l in links]

    def list_meta_options(
        self,
        metamodel_api_key: str,
        item_api_key: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        opts = [
            o for o in self._meta_options
            if o.get("metamodelApiKey") == metamodel_api_key
            and (item_api_key is None or o.get("itemApiKey") == item_api_key)
        ]
        return [copy.deepcopy(o) for o in sorted(opts, key=lambda x: x.get("optionOrder", 0))]

    def get_item_type_mapping(self) -> list[dict[str, Any]]:
        return [copy.deepcopy(t) for t in ITEM_TYPE_MAPPING]

    # ─── 元数据实例层（Common + Tenant 合并后） ───

    def list_metadata(
        self,
        metamodel_api_key: str,
        entity_api_key: Optional[str] = None,
        item_api_key: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        records = self._metadata.get(metamodel_api_key, [])
        if entity_api_key:
            records = [
                r for r in records
                if r.get("entityApiKey") == entity_api_key
                or r.get("parentEntityApiKey") == entity_api_key
            ]
        if item_api_key:
            records = [r for r in records if r.get("itemApiKey") == item_api_key]
        # sort by sortNum/optionOrder when present
        records = sorted(
            records,
            key=lambda r: (
                r.get("sortNum") if r.get("sortNum") is not None else
                r.get("optionOrder") if r.get("optionOrder") is not None else 0
            ),
        )
        return [copy.deepcopy(r) for r in records]

    def get_metadata(
        self,
        metamodel_api_key: str,
        api_key: str,
        entity_api_key: Optional[str] = None,
    ) -> Optional[dict[str, Any]]:
        for r in self._metadata.get(metamodel_api_key, []):
            if r.get("apiKey") != api_key:
                continue
            if entity_api_key and r.get("entityApiKey") != entity_api_key:
                continue
            return copy.deepcopy(r)
        return None

    # ─── 便捷封装 —— 对齐 MetamodelBrowseApiService 的 @GetMapping 命名 ───

    def list_metadata_entities(self) -> list[dict[str, Any]]:
        return self.list_metadata("entity")

    def list_metadata_items(self, entity_api_key: str) -> list[dict[str, Any]]:
        return self.list_metadata("item", entity_api_key=entity_api_key)

    def list_metadata_entity_links(self, entity_api_key: str) -> list[dict[str, Any]]:
        return self.list_metadata("entityLink", entity_api_key=entity_api_key)

    def list_metadata_check_rules(self, entity_api_key: str) -> list[dict[str, Any]]:
        return self.list_metadata("checkRule", entity_api_key=entity_api_key)

    def list_metadata_busi_types(self, entity_api_key: str) -> list[dict[str, Any]]:
        return self.list_metadata("busiType", entity_api_key=entity_api_key)

    def list_metadata_pick_options(self, item_api_key: str) -> list[dict[str, Any]]:
        return self.list_metadata("pickOption", item_api_key=item_api_key)

    # ─── 诊断辅助 ───

    def trace_db_column(self, db_column: str) -> list[dict[str, Any]]:
        """根据 dbc_xxxN 列名反查"哪些元模型的哪些字段"使用了该列。"""
        hits: list[dict[str, Any]] = []
        for mm_key, items in self._meta_items.items():
            for item in items:
                if item.get("dbColumn") == db_column:
                    hits.append({
                        "metamodelApiKey": mm_key,
                        "itemApiKey": item.get("apiKey"),
                        "label": item.get("label"),
                        "itemType": item.get("itemType"),
                    })
        return hits

    def get_stats(self) -> dict[str, int]:
        return {
            "meta_models": len(self._meta_models),
            "meta_items_total": sum(len(v) for v in self._meta_items.values()),
            "meta_links": len(self._meta_links),
            "meta_options": len(self._meta_options),
            "metadata_instances_total": sum(len(v) for v in self._metadata.values()),
        }
