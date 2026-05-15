"""
CRM 模拟后端 — 完整的内存数据库 + CRUD + 聚合 + 元数据 + 权限
替代 MockServiceBackend，提供真实的业务逻辑。
"""
from __future__ import annotations

import uuid
import time
import copy
import re
from typing import Any
from dataclasses import dataclass, field


def _id() -> str:
    return uuid.uuid4().hex[:12]


def _now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


# ═══════════════════════════════════════════════════════════
# 元数据定义（Schema）
# ═══════════════════════════════════════════════════════════

ENTITY_SCHEMAS: dict[str, dict] = {
    "account": {
        "label": "客户",
        "api_key": "account",
        "items": [
            {"api_key": "accountChannel", "label": "来源方式", "item_type": "PICK_LIST", "paas_item_type": 2, "paas_data_type": 2, "db_column": "dbc_varchar20"},
            {"api_key": "accountName", "label": "客户名称", "item_type": "VARCHAR", "paas_item_type": 1, "paas_data_type": 1, "db_column": "name"},
            {"api_key": "accountScore", "label": "客户得分", "item_type": "DECIMAL", "paas_item_type": 27, "paas_data_type": 6, "db_column": "dbc_decimal6"},
            {"api_key": "actualInvoicedAmount", "label": "实际应收账金额", "item_type": "DECIMAL", "paas_item_type": 27, "paas_data_type": 5, "db_column": "dbc_bigint24"},
            {"api_key": "amountUnbilled", "label": "未出应收账金额", "item_type": "DECIMAL", "paas_item_type": 27, "paas_data_type": 5, "db_column": "dbc_bigint28"},
            {"api_key": "annualRevenue", "label": "销售额", "item_type": "DECIMAL", "paas_item_type": 6, "paas_data_type": 6, "db_column": "dbc_decimal3"},
            {"api_key": "claimTime", "label": "认领日期", "item_type": "DATE", "paas_item_type": 7, "paas_data_type": 7, "db_column": "dbc_bigint11"},
            {"api_key": "duplicateFlg", "label": "疑似查重", "item_type": "BOOLEAN", "paas_item_type": 31, "paas_data_type": 31, "db_column": "dbc_smallint3"},
            {"api_key": "employeeNumber", "label": "总人数", "item_type": "INTEGER", "paas_item_type": 5, "paas_data_type": 5, "db_column": "dbc_bigint4"},
            {"api_key": "expireTime", "label": "到期时间", "item_type": "DATE", "paas_item_type": 7, "paas_data_type": 7, "db_column": "dbc_bigint13"},
            {"api_key": "fCity", "label": "市", "item_type": "PICK_LIST", "paas_item_type": 2, "paas_data_type": 2, "db_column": "dbc_varchar17"},
            {"api_key": "fDistrict", "label": "区", "item_type": "PICK_LIST", "paas_item_type": 2, "paas_data_type": 2, "db_column": "dbc_varchar18"},
            {"api_key": "fState", "label": "省份", "item_type": "PICK_LIST", "paas_item_type": 2, "paas_data_type": 2, "db_column": "dbc_varchar16"},
            {"api_key": "highSeaAccountSource", "label": "客户来源", "item_type": "PICK_LIST", "paas_item_type": 3, "paas_data_type": 3, "db_column": "dbc_varchar12"},
            {"api_key": "highSeaId", "label": "所属公海", "item_type": "RELATIONSHIP", "paas_item_type": 10, "paas_data_type": 5, "db_column": "dbc_bigint8", "refer_entity": "highSea"},
            {"api_key": "highSeaStatus", "label": "状态", "item_type": "PICK_LIST", "paas_item_type": 2, "paas_data_type": 2, "db_column": "dbc_varchar21"},
            {"api_key": "industryId", "label": "行业", "item_type": "PICK_LIST", "paas_item_type": 2, "paas_data_type": 2, "db_column": "dbc_varchar15"},
            {"api_key": "invoiceBalance", "label": "应收余额（欠款）", "item_type": "DECIMAL", "paas_item_type": 27, "paas_data_type": 5, "db_column": "dbc_bigint29"},
            {"api_key": "isCustomer", "label": "是否为结单客户", "item_type": "DECIMAL", "paas_item_type": 27, "paas_data_type": 1, "db_column": "dbc_varchar2"},
            {"api_key": "paidAmount", "label": "实际收款金额", "item_type": "DECIMAL", "paas_item_type": 27, "paas_data_type": 5, "db_column": "dbc_bigint30"},
            {"api_key": "parentAccountId", "label": "上级客户", "item_type": "RELATIONSHIP", "paas_item_type": 10, "paas_data_type": 10, "db_column": "dbc_bigint3", "refer_entity": "account"},
            {"api_key": "paymentHealthPct", "label": "应收健康度", "item_type": "DECIMAL", "paas_item_type": 6, "paas_data_type": 0, "db_column": "dbc_decimal8"},
            {"api_key": "paymentRate", "label": "账户支付比例", "item_type": "DECIMAL", "paas_item_type": 33, "paas_data_type": 33, "db_column": "dbc_decimal4"},
            {"api_key": "recentActivityCreatedBy", "label": "最新跟进人", "item_type": "RELATIONSHIP", "paas_item_type": 10, "paas_data_type": 10, "db_column": "dbc_bigint6", "refer_entity": "user"},
            {"api_key": "releaseDescription", "label": "退回公海描述", "item_type": "VARCHAR", "paas_item_type": 1, "paas_data_type": 1, "db_column": "dbc_varchar13"},
            {"api_key": "score", "label": "客户分值", "item_type": "INTEGER", "paas_item_type": 5, "paas_data_type": 5, "db_column": "dbc_bigint19"},
            {"api_key": "territoryHighSeaId", "label": "所属区域公海", "item_type": "RELATIONSHIP", "paas_item_type": 10, "paas_data_type": 10, "db_column": "dbc_bigint27", "refer_entity": "territory"},
            {"api_key": "totalActiveOrders", "label": "生效订单数", "item_type": "DECIMAL", "paas_item_type": 27, "paas_data_type": 5, "db_column": "dbc_bigint32"},
            {"api_key": "totalContract", "label": "合同数", "item_type": "DECIMAL", "paas_item_type": 27, "paas_data_type": 5, "db_column": "dbc_bigint34"},
            {"api_key": "totalOrderAmount", "label": "订单总金额", "item_type": "DECIMAL", "paas_item_type": 27, "paas_data_type": 5, "db_column": "dbc_bigint33"},
            {"api_key": "totalWonOpportunities", "label": "结单商机数", "item_type": "DECIMAL", "paas_item_type": 27, "paas_data_type": 5, "db_column": "dbc_bigint23"},
            {"api_key": "totalWonOpportunityAmount", "label": "结单商机总金额", "item_type": "DECIMAL", "paas_item_type": 27, "paas_data_type": 5, "db_column": "dbc_bigint31"},
            {"api_key": "unpaidAmount", "label": "未收款金额", "item_type": "DECIMAL", "paas_item_type": 27, "paas_data_type": 6, "db_column": "dbc_decimal5"},
            {"api_key": "valueScore", "label": "客户价值评分", "item_type": "DECIMAL", "paas_item_type": 6, "paas_data_type": 0, "db_column": "dbc_decimal7"},
            {"api_key": "vipFlag", "label": "VIP标识", "item_type": "PICK_LIST", "paas_item_type": 2, "paas_data_type": 2, "db_column": "dbc_varchar14"},
            {"api_key": "visitLatestTime", "label": "最近拜访时间", "item_type": "DATETIME", "paas_item_type": 38, "paas_data_type": 38, "db_column": "dbc_bigint21"},
            {"api_key": "visitTotalCount", "label": "拜访总数", "item_type": "DECIMAL", "paas_item_type": 27, "paas_data_type": 5, "db_column": "dbc_bigint36"},
            {"api_key": "visitUnvisitDay", "label": "未拜访天数", "item_type": "INTEGER", "paas_item_type": 5, "paas_data_type": 5, "db_column": "dbc_bigint22"},
        ],
        "links": [
        ],
    },
    "contact": {
        "label": "联系人",
        "api_key": "contact",
        "items": [
            {"api_key": "address", "label": "地址", "item_type": "VARCHAR", "paas_item_type": 1, "paas_data_type": 1, "db_column": "dbc_varchar8"},
            {"api_key": "comment", "label": "备注", "item_type": "TEXT", "paas_item_type": 4, "paas_data_type": 4, "db_column": "dbc_textarea1"},
            {"api_key": "contactBirthday", "label": "出生日期", "item_type": "DATE", "paas_item_type": 7, "paas_data_type": 7, "db_column": "dbc_bigint4"},
            {"api_key": "contactChannel", "label": "来源方式", "item_type": "PICK_LIST", "paas_item_type": 2, "paas_data_type": 2, "db_column": "dbc_int3"},
            {"api_key": "contactName", "label": "姓名", "item_type": "VARCHAR", "paas_item_type": 1, "paas_data_type": 1, "db_column": "name"},
            {"api_key": "contactRole", "label": "联系人角色", "item_type": "PICK_LIST", "paas_item_type": 2, "paas_data_type": 2, "db_column": "dbc_int6"},
            {"api_key": "contactScore", "label": "联系人得分", "item_type": "DECIMAL", "paas_item_type": 27, "paas_data_type": 6},
            {"api_key": "countryId", "label": "城市", "item_type": "INTEGER", "paas_item_type": 5, "paas_data_type": 5, "db_column": "dbc_bigint17"},
            {"api_key": "depart", "label": "部门", "item_type": "VARCHAR", "paas_item_type": 1, "paas_data_type": 1, "db_column": "dbc_varchar2"},
            {"api_key": "doNotDisturb", "label": "免打扰", "item_type": "BOOLEAN", "paas_item_type": 31, "paas_data_type": 31, "db_column": "dbc_smallint1"},
            {"api_key": "email", "label": "电子邮件", "item_type": "VARCHAR", "paas_item_type": 23, "paas_data_type": 23, "db_column": "email"},
            {"api_key": "externalUserId", "label": "扩展用户", "item_type": "INTEGER", "paas_item_type": 5, "paas_data_type": 5, "db_column": "dbc_bigint19"},
            {"api_key": "gender", "label": "性别", "item_type": "PICK_LIST", "paas_item_type": 2, "paas_data_type": 2, "db_column": "dbc_int1"},
            {"api_key": "leadId", "label": "线索", "item_type": "INTEGER", "paas_item_type": 5, "paas_data_type": 5, "db_column": "dbc_bigint13"},
            {"api_key": "mobile", "label": "手机", "item_type": "VARCHAR", "paas_item_type": 22, "paas_data_type": 22, "db_column": "dbc_varchar5"},
            {"api_key": "phone", "label": "电话", "item_type": "VARCHAR", "paas_item_type": 22, "paas_data_type": 22, "db_column": "dbc_varchar4"},
            {"api_key": "pinyin", "label": "拼音", "item_type": "VARCHAR", "paas_item_type": 1, "paas_data_type": 1, "db_column": "dbc_varchar11"},
            {"api_key": "post", "label": "职务", "item_type": "VARCHAR", "paas_item_type": 1, "paas_data_type": 1, "db_column": "dbc_varchar3"},
            {"api_key": "recentActivityRecordId", "label": "最新活动记录", "item_type": "RELATIONSHIP", "paas_item_type": 10, "paas_data_type": 10, "db_column": "dbc_bigint20", "refer_entity": "activityrecord"},
            {"api_key": "recentActivityRecordTime", "label": "最新活动记录时间", "item_type": "DATE", "paas_item_type": 7, "paas_data_type": 7, "db_column": "dbc_bigint5"},
            {"api_key": "recentActivityRecordType", "label": "最新活动记录类型", "item_type": "INTEGER", "paas_item_type": 5, "paas_data_type": 5, "db_column": "dbc_bigint21"},
            {"api_key": "registrationUtmId", "label": "关联UTM", "item_type": "RELATIONSHIP", "paas_item_type": 10, "paas_data_type": 10, "db_column": "dbc_bigint29", "refer_entity": "592"},
            {"api_key": "state", "label": "省份", "item_type": "VARCHAR", "paas_item_type": 1, "paas_data_type": 1, "db_column": "dbc_varchar7"},
            {"api_key": "territoryId", "label": "区域", "item_type": "RELATIONSHIP", "paas_item_type": 10, "paas_data_type": 10, "db_column": "territory_id", "refer_entity": "territory"},
            {"api_key": "zipCode", "label": "邮政编码", "item_type": "VARCHAR", "paas_item_type": 1, "paas_data_type": 1, "db_column": "dbc_varchar9"},
        ],
        "links": [
        ],
    },
    "opportunity": {
        "label": "商机",
        "api_key": "opportunity",
        "items": [
            {"api_key": "actualCost", "label": "实际花费", "item_type": "DECIMAL", "paas_item_type": 6, "paas_data_type": 6, "db_column": "dbc_decimal3"},
            {"api_key": "actualPeriod", "label": "实际周期", "item_type": "INTEGER", "paas_item_type": 5, "paas_data_type": 5, "db_column": "dbc_bigint24"},
            {"api_key": "campaignContactId", "label": "联系人", "item_type": "RELATIONSHIP", "paas_item_type": 10, "paas_data_type": 10, "db_column": "dbc_bigint18", "refer_entity": "contact"},
            {"api_key": "campaignId", "label": "市场活动", "item_type": "RELATIONSHIP", "paas_item_type": 10, "paas_data_type": 10, "db_column": "dbc_bigint19", "refer_entity": "campaign"},
            {"api_key": "closeDate", "label": "结单日期", "item_type": "DATE", "paas_item_type": 7, "paas_data_type": 7, "db_column": "dbc_bigint8"},
            {"api_key": "commitmentFlg", "label": "承诺", "item_type": "PICK_LIST", "paas_item_type": 2, "paas_data_type": 2, "db_column": "dbc_int3"},
            {"api_key": "discount", "label": "折扣", "item_type": "DECIMAL", "paas_item_type": 6, "paas_data_type": 6, "db_column": "dbc_decimal4"},
            {"api_key": "duplicateCheckExplanation", "label": "查重结果说明", "item_type": "TEXT", "paas_item_type": 4, "paas_data_type": 4, "db_column": "dbc_textarea4"},
            {"api_key": "duplicateCheckResultTime", "label": "智能查重时间", "item_type": "DATETIME", "paas_item_type": 38, "paas_data_type": 38, "db_column": "dbc_bigint32"},
            {"api_key": "fcastMoney", "label": "预测金额", "item_type": "DECIMAL", "paas_item_type": 27, "paas_data_type": 6},
            {"api_key": "forecastCategory", "label": "阶段分类", "item_type": "PICK_LIST", "paas_item_type": 2, "paas_data_type": 2, "db_column": "dbc_int7"},
            {"api_key": "intelligentDuplicateCheckResult", "label": "智能查重结果", "item_type": "VARCHAR", "paas_item_type": 1, "paas_data_type": 1, "db_column": "dbc_varchar7"},
            {"api_key": "invoiceDate", "label": "开票日期", "item_type": "DATE", "paas_item_type": 7, "paas_data_type": 7, "db_column": "dbc_bigint22"},
            {"api_key": "lostStageId", "label": "输单阶段", "item_type": "RELATIONSHIP", "paas_item_type": 10, "paas_data_type": 10, "db_column": "dbc_bigint5"},
            {"api_key": "money", "label": "销售金额", "item_type": "DECIMAL", "paas_item_type": 6, "paas_data_type": 6, "db_column": "dbc_decimal1"},
            {"api_key": "oppHealthAssessmentLevel", "label": "商机健康度等级", "item_type": "PICK_LIST", "paas_item_type": 2, "paas_data_type": 2, "db_column": "dbc_int9"},
            {"api_key": "oppHealthAssessmentScore", "label": "商机评分", "item_type": "DECIMAL", "paas_item_type": 6, "paas_data_type": 6, "db_column": "dbc_decimal5"},
            {"api_key": "oppHealthAssessmentShow", "label": "商机健康度等级展示", "item_type": "VARCHAR", "paas_item_type": 1, "paas_data_type": 1, "db_column": "dbc_varchar8"},
            {"api_key": "opportunityCode", "label": "机会编号", "item_type": "VARCHAR", "paas_item_type": 1, "paas_data_type": 1, "db_column": "dbc_varchar5"},
            {"api_key": "opportunityName", "label": "机会名称", "item_type": "VARCHAR", "paas_item_type": 1, "paas_data_type": 1, "db_column": "name"},
            {"api_key": "opportunityScore", "label": "商机得分", "item_type": "DECIMAL", "paas_item_type": 27, "paas_data_type": 6},
            {"api_key": "opportunityType", "label": "机会类型", "item_type": "PICK_LIST", "paas_item_type": 2, "paas_data_type": 2, "db_column": "dbc_int1"},
            {"api_key": "paymentDate", "label": "付款日期", "item_type": "DATE", "paas_item_type": 7, "paas_data_type": 7, "db_column": "dbc_bigint23"},
            {"api_key": "priceId", "label": "价格表名称", "item_type": "RELATIONSHIP", "paas_item_type": 10, "paas_data_type": 10, "db_column": "dbc_bigint3", "refer_entity": "priceBook"},
            {"api_key": "projectBudget", "label": "项目预算", "item_type": "DECIMAL", "paas_item_type": 6, "paas_data_type": 6, "db_column": "dbc_decimal2"},
            {"api_key": "reasonDesc", "label": "输单描述", "item_type": "TEXT", "paas_item_type": 4, "paas_data_type": 4, "db_column": "dbc_textarea1"},
            {"api_key": "repeatFlg", "label": "重复标志", "item_type": "INTEGER", "paas_item_type": 5, "paas_data_type": 5, "db_column": "dbc_bigint20"},
            {"api_key": "roiCiCount", "label": "ROI影响力计数", "item_type": "DECIMAL", "paas_item_type": 27, "paas_data_type": 5},
            {"api_key": "saleStageId", "label": "销售阶段", "item_type": "RELATIONSHIP", "paas_item_type": 10, "paas_data_type": 10, "db_column": "dbc_bigint6"},
            {"api_key": "seemDuplicateRuleId", "label": "疑似查重规则id", "item_type": "INTEGER", "paas_item_type": 5, "paas_data_type": 5, "db_column": "dbc_bigint33"},
            {"api_key": "sourceId", "label": "机会来源", "item_type": "INTEGER", "paas_item_type": 5, "paas_data_type": 5, "db_column": "dbc_bigint9"},
            {"api_key": "stageUpdatedAt", "label": "阶段更新时间", "item_type": "DATE", "paas_item_type": 7, "paas_data_type": 7, "db_column": "dbc_bigint11"},
            {"api_key": "standardPeriod", "label": "标准周期", "item_type": "INTEGER", "paas_item_type": 5, "paas_data_type": 5, "db_column": "dbc_bigint21"},
            {"api_key": "suspectedOpportunityAnalysis", "label": "疑似商机分析", "item_type": "TEXT", "paas_item_type": 4, "paas_data_type": 4, "db_column": "dbc_textarea5"},
            {"api_key": "winRate", "label": "赢率", "item_type": "INTEGER", "paas_item_type": 5, "paas_data_type": 5, "db_column": "dbc_bigint7"},
            {"api_key": "winReason", "label": "赢单原因", "item_type": "PICK_LIST", "paas_item_type": 2, "paas_data_type": 2, "db_column": "dbc_int8"},
            {"api_key": "winReasonDesc", "label": "赢单描述", "item_type": "TEXT", "paas_item_type": 4, "paas_data_type": 4, "db_column": "dbc_textarea3"},
        ],
        "links": [
        ],
    },
    "lead": {
        "label": "线索",
        "api_key": "lead",
        "items": [
            {"api_key": "adDmpLeadId", "label": "广告线索id", "item_type": "VARCHAR", "paas_item_type": 1, "paas_data_type": 1, "db_column": "dbc_varchar17"},
            {"api_key": "adPlanName", "label": "广告计划名称", "item_type": "VARCHAR", "paas_item_type": 1, "paas_data_type": 1, "db_column": "dbc_varchar18"},
            {"api_key": "adPlatform", "label": "广告投放平台", "item_type": "VARCHAR", "paas_item_type": 1, "paas_data_type": 1, "db_column": "dbc_varchar19"},
            {"api_key": "adProjectName", "label": "项目名称", "item_type": "VARCHAR", "paas_item_type": 1, "paas_data_type": 1, "db_column": "dbc_varchar21"},
            {"api_key": "adRetentionTime", "label": "广告留资时间", "item_type": "DATE", "paas_item_type": 7, "paas_data_type": 7, "db_column": "dbc_bigint35"},
            {"api_key": "adSource", "label": "广告投放来源", "item_type": "VARCHAR", "paas_item_type": 1, "paas_data_type": 1, "db_column": "dbc_varchar20"},
            {"api_key": "applyDelayTime", "label": "延期时间", "item_type": "DATE", "paas_item_type": 7, "paas_data_type": 7, "db_column": "dbc_bigint26"},
            {"api_key": "bdType", "label": "大数据类型", "item_type": "PICK_LIST", "paas_item_type": 2, "paas_data_type": 2, "db_column": "dbc_int11"},
            {"api_key": "claimTime", "label": "认领日期", "item_type": "DATE", "paas_item_type": 7, "paas_data_type": 3, "db_column": "dbc_bigint6"},
            {"api_key": "companyName", "label": "公司名称", "item_type": "VARCHAR", "paas_item_type": 1, "paas_data_type": 1, "db_column": "dbc_varchar2"},
            {"api_key": "contactId", "label": "联系人", "item_type": "RELATIONSHIP", "paas_item_type": 10, "paas_data_type": 10, "db_column": "dbc_bigint27", "refer_entity": "contact"},
            {"api_key": "countryId", "label": "省份", "item_type": "VARCHAR", "paas_item_type": 1, "paas_data_type": 1, "db_column": "dbc_varchar13"},
            {"api_key": "expireTime", "label": "到期时间", "item_type": "DATE", "paas_item_type": 7, "paas_data_type": 3, "db_column": "dbc_bigint7"},
            {"api_key": "lastOwnerId", "label": "最后所有人", "item_type": "RELATIONSHIP", "paas_item_type": 10, "paas_data_type": 10, "db_column": "dbc_bigint33", "refer_entity": "user"},
            {"api_key": "leadChannel", "label": "来源方式", "item_type": "PICK_LIST", "paas_item_type": 2, "paas_data_type": 2, "db_column": "dbc_int7"},
            {"api_key": "leadHighSeaId", "label": "所属线索公海", "item_type": "RELATIONSHIP", "paas_item_type": 10, "paas_data_type": 3, "db_column": "dbc_bigint5", "refer_entity": "leadHighSea"},
            {"api_key": "leadHighSeaStatus", "label": "公海状态", "item_type": "PICK_LIST", "paas_item_type": 2, "paas_data_type": 1, "db_column": "dbc_varchar9"},
            {"api_key": "leadQuality", "label": "线索质量", "item_type": "PICK_LIST", "paas_item_type": 2, "paas_data_type": 2, "db_column": "dbc_int10"},
            {"api_key": "leadScore", "label": "线索得分", "item_type": "INTEGER", "paas_item_type": 5, "paas_data_type": 5, "db_column": "dbc_bigint18"},
            {"api_key": "leadSourceId", "label": "线索来源", "item_type": "INTEGER", "paas_item_type": 5, "paas_data_type": 5, "db_column": "dbc_bigint4"},
            {"api_key": "opportunityId", "label": "销售机会", "item_type": "RELATIONSHIP", "paas_item_type": 10, "paas_data_type": 10, "db_column": "dbc_bigint22", "refer_entity": "opportunity"},
            {"api_key": "phoneLocation", "label": "手机号归属地", "item_type": "VARCHAR", "paas_item_type": 1, "paas_data_type": 1, "db_column": "dbc_varchar23"},
            {"api_key": "releaseDefinition", "label": "退回原因说明", "item_type": "VARCHAR", "paas_item_type": 1, "paas_data_type": 1, "db_column": "dbc_varchar15"},
            {"api_key": "releaseNum", "label": "退回公海次数", "item_type": "INTEGER", "paas_item_type": 5, "paas_data_type": 5, "db_column": "dbc_bigint29"},
            {"api_key": "releaseReason", "label": "退回原因", "item_type": "INTEGER", "paas_item_type": 5, "paas_data_type": 5, "db_column": "dbc_bigint31"},
            {"api_key": "releaseTime", "label": "退回时间", "item_type": "DATE", "paas_item_type": 7, "paas_data_type": 7, "db_column": "dbc_bigint32"},
            {"api_key": "returnTimes", "label": "退回次数", "item_type": "INTEGER", "paas_item_type": 5, "paas_data_type": 5, "db_column": "dbc_bigint34"},
            {"api_key": "scoreDetail", "label": "线索得分分析", "item_type": "TEXT", "paas_item_type": 4, "paas_data_type": 4, "db_column": "dbc_textarea2"},
            {"api_key": "statusUpdatedAt", "label": "状态更新时间", "item_type": "DATE", "paas_item_type": 7, "paas_data_type": 7, "db_column": "dbc_bigint23"},
            {"api_key": "territoryLeadHighSeaId", "label": "所属区域线索公海", "item_type": "RELATIONSHIP", "paas_item_type": 10, "paas_data_type": 3, "db_column": "dbc_bigint16", "refer_entity": "territory"},
            {"api_key": "thawTime", "label": "解冻时间", "item_type": "DATE", "paas_item_type": 7, "paas_data_type": 7, "db_column": "dbc_bigint30"},
        ],
        "links": [
            {"target": "leadHighSea", "type": "MANY_TO_ONE", "label": "公海线索"},
            {"target": "territory", "type": "MANY_TO_ONE", "label": "区域线索公海"},
        ],
    },
    "activity": {
        "label": "活动",
        "api_key": "activity",
        "items": [
            {"api_key": "activityType", "label": "活动类型", "item_type": "PICK_LIST", "paas_item_type": 2, "paas_data_type": 2, "db_column": "dbc_int1"},
            {"api_key": "subject", "label": "主题", "item_type": "VARCHAR", "paas_item_type": 1, "paas_data_type": 1, "db_column": "name"},
            {"api_key": "description", "label": "描述", "item_type": "TEXT", "paas_item_type": 4, "paas_data_type": 4, "db_column": "dbc_textarea1"},
            {"api_key": "accountId", "label": "关联客户", "item_type": "RELATIONSHIP", "paas_item_type": 10, "paas_data_type": 10, "db_column": "dbc_bigint1", "refer_entity": "account"},
            {"api_key": "opportunityId", "label": "关联商机", "item_type": "RELATIONSHIP", "paas_item_type": 10, "paas_data_type": 10, "db_column": "dbc_bigint2", "refer_entity": "opportunity"},
            {"api_key": "contactId", "label": "关联联系人", "item_type": "RELATIONSHIP", "paas_item_type": 10, "paas_data_type": 10, "db_column": "dbc_bigint3", "refer_entity": "contact"},
            {"api_key": "dueDate", "label": "截止日期", "item_type": "DATE", "paas_item_type": 7, "paas_data_type": 7, "db_column": "dbc_bigint4"},
            {"api_key": "status", "label": "状态", "item_type": "PICK_LIST", "paas_item_type": 2, "paas_data_type": 2, "db_column": "dbc_int2"},
            {"api_key": "createdAt", "label": "创建时间", "item_type": "DATETIME", "paas_item_type": 38, "paas_data_type": 38, "db_column": "created_at"},
        ],
        "links": [
            {"target": "account", "type": "MANY_TO_ONE", "label": "关联客户"},
            {"target": "opportunity", "type": "MANY_TO_ONE", "label": "关联商机"},
            {"target": "contact", "type": "MANY_TO_ONE", "label": "关联联系人"},
        ],
    },
}


# ═══════════════════════════════════════════════════════════
# 种子数据
# ═══════════════════════════════════════════════════════════

def build_seed_data() -> dict[str, list[dict]]:
    """构建完整的 CRM 种子数据 — 从 crm_seed_data 模块加载"""
    from src.tools.crm_seed_data import build_seed_data as _build
    return _build()


# ═══════════════════════════════════════════════════════════
# CRM 模拟后端 — 完整 CRUD + 聚合 + 元数据
# ═══════════════════════════════════════════════════════════

class CrmSimulatedBackend:
    """
    内存 CRM 数据库，实现完整的 ServiceBackend 接口。
    支持: 查询/创建/更新/删除/计数/聚合/元数据查询/权限查询。
    """

    def __init__(self):
        self._data = build_seed_data()
        self._schemas = ENTITY_SCHEMAS
        self._audit_log: list[dict] = []

    # ── 元数据查询 ──

    async def query_metadata(self, query_type: str, **params) -> dict:
        entity_key = params.get("entity_api_key", "")
        item_key = params.get("item_api_key", "")

        if query_type == "list_entities":
            entities = [{"api_key": k, "label": v["label"]} for k, v in self._schemas.items()]
            return {"data": entities}

        if query_type == "entity" and entity_key in self._schemas:
            schema = self._schemas[entity_key]
            return {"data": schema}

        if query_type == "entity_items" and entity_key in self._schemas:
            return {"data": self._schemas[entity_key].get("items", [])}

        if query_type == "entity_links" and entity_key in self._schemas:
            return {"data": self._schemas[entity_key].get("links", [])}

        if query_type == "entity_pick_options":
            if not item_key:
                return {"data": {}, "error": "entity_pick_options 需要 item_api_key"}
            # 在所有 entity schema 中查找该字段的 options
            for schema in self._schemas.values():
                for item in schema.get("items", []):
                    if item.get("api_key") == item_key and "options" in item:
                        return {"data": item["options"]}
            return {"data": [], "error": f"字段 {item_key} 不存在或没有选项值"}

        return {"data": {}, "error": f"未知查询: {query_type} {entity_key}"}

    # ── 数据 CRUD ──

    async def query_data(self, entity: str, filters: dict, **kw) -> dict:
        if entity not in self._data:
            return {"data": {"records": [], "total": 0}, "error": f"实体 {entity} 不存在"}

        records = self._data[entity]

        # 过滤
        if filters:
            records = [r for r in records if self._match_filters(r, filters)]

        total = len(records)

        # 排序
        order_by = kw.get("order_by")
        if order_by:
            desc = order_by.startswith("-")
            field_name = order_by.lstrip("-")
            records = sorted(records, key=lambda r: r.get(field_name, ""), reverse=desc)

        # 分页
        page = kw.get("page") or 1
        page_size = kw.get("page_size") or 20
        start = (page - 1) * page_size
        records = records[start:start + page_size]

        # 字段过滤
        fields = kw.get("fields")
        if fields:
            records = [{k: r.get(k) for k in ["id"] + fields if k in r} for r in records]

        return {"data": {"records": copy.deepcopy(records), "total": total}}

    async def mutate_data(self, entity: str, action: str, data: dict, **kw) -> dict:
        if entity not in self._data:
            return {"error": f"实体 {entity} 不存在"}

        if action == "create":
            record = {"id": f"{entity[:3]}_{_id()}", "createdAt": _now(), "updatedAt": _now()}
            record.update(data)
            # 必填校验
            schema = self._schemas.get(entity, {})
            for item in schema.get("items", []):
                if item.get("required") and item["api_key"] not in data:
                    return {"error": f"必填字段 {item['api_key']}({item['label']}) 缺失"}
            self._data[entity].append(record)
            self._log("create", entity, record["id"], data)
            return {"data": {"id": record["id"], "success": True, "record": copy.deepcopy(record)}}

        if action == "update":
            record_id = kw.get("record_id") or data.get("id")
            if not record_id:
                return {"error": "update 需要 record_id"}
            for r in self._data[entity]:
                if r["id"] == record_id:
                    old = copy.deepcopy(r)
                    r.update({k: v for k, v in data.items() if k != "id"})
                    r["updatedAt"] = _now()
                    self._log("update", entity, record_id, data, old=old)
                    return {"data": {"id": record_id, "success": True, "record": copy.deepcopy(r)}}
            return {"error": f"记录 {record_id} 不存在"}

        if action == "delete":
            record_id = kw.get("record_id") or data.get("id")
            if not record_id:
                # 批量删除（按 filters）
                filters = data.get("filters", {})
                if not filters:
                    return {"error": "delete 需要 record_id 或 filters"}
                before = len(self._data[entity])
                self._data[entity] = [r for r in self._data[entity] if not self._match_filters(r, filters)]
                deleted = before - len(self._data[entity])
                self._log("batch_delete", entity, f"filters={filters}", {"deleted_count": deleted})
                return {"data": {"success": True, "deleted_count": deleted}}
            # 单条删除
            before = len(self._data[entity])
            self._data[entity] = [r for r in self._data[entity] if r["id"] != record_id]
            if len(self._data[entity]) < before:
                self._log("delete", entity, record_id, {})
                return {"data": {"id": record_id, "success": True}}
            return {"error": f"记录 {record_id} 不存在"}

        return {"error": f"未知操作: {action}"}

    # ── 聚合查询 ──

    async def aggregate_data(self, entity: str, metrics: list, **kw) -> dict:
        if entity not in self._data:
            return {"data": {"results": []}, "error": f"实体 {entity} 不存在"}

        records = self._data[entity]
        filters = kw.get("filters", {})
        if filters:
            records = [r for r in records if self._match_filters(r, filters)]

        group_by = kw.get("group_by")
        results = []

        if group_by:
            # 分组聚合
            groups: dict[str, list] = {}
            for r in records:
                key = str(r.get(group_by, "未知"))
                groups.setdefault(key, []).append(r)

            for group_key, group_records in groups.items():
                row = {group_by: group_key}
                for m in metrics:
                    field_name = m.get("field", "")
                    func = m.get("function", "count")
                    row[f"{func}_{field_name}"] = self._calc_metric(group_records, field_name, func)
                results.append(row)
        else:
            # 全局聚合
            row = {}
            for m in metrics:
                field_name = m.get("field", "")
                func = m.get("function", "count")
                row[f"{func}_{field_name}"] = self._calc_metric(records, field_name, func)
            results.append(row)

        return {"data": {"results": results, "total_records": len(records)}}

    # ── 权限查询 ──

    async def query_permission(self, query_type: str, **kw) -> dict:
        # 模拟权限数据
        if query_type == "roles":
            return {"data": [
                {"api_key": "admin", "label": "管理员", "permissions": "全部"},
                {"api_key": "sales_manager", "label": "销售经理", "permissions": "本部门及下级"},
                {"api_key": "sales_rep", "label": "销售代表", "permissions": "本人"},
            ]}
        if query_type == "user_permissions":
            return {"data": {"role": "sales_manager", "data_scope": "本部门及下级",
                             "entities": ["account", "contact", "opportunity", "activity", "lead"]}}
        return {"data": {}}

    # ── 内部方法 ──

    def _match_filters(self, record: dict, filters: dict) -> bool:
        for key, value in filters.items():
            # 支持操作符后缀：field__contains, field__startswith, field__in
            if "__contains" in key:
                field = key.replace("__contains", "")
                rec_val = str(record.get(field, ""))
                if str(value).lower() not in rec_val.lower():
                    return False
                continue
            if "__startswith" in key:
                field = key.replace("__startswith", "")
                rec_val = str(record.get(field, ""))
                if not rec_val.lower().startswith(str(value).lower()):
                    return False
                continue
            if "__in" in key:
                field = key.replace("__in", "")
                rec_val = record.get(field)
                if not isinstance(value, list) or rec_val not in value:
                    return False
                continue
            if "__gte" in key:
                field = key.replace("__gte", "")
                try:
                    if float(record.get(field, 0)) < float(value):
                        return False
                except (ValueError, TypeError):
                    return False
                continue
            if "__lte" in key:
                field = key.replace("__lte", "")
                try:
                    if float(record.get(field, 0)) > float(value):
                        return False
                except (ValueError, TypeError):
                    return False
                continue

            # 原有逻辑：精确匹配 / 大于小于 / 列表包含
            rec_val = record.get(key)
            if isinstance(value, str) and value.startswith(">"):
                try:
                    if not (float(rec_val or 0) > float(value[1:])):
                        return False
                except (ValueError, TypeError):
                    return False
                continue
            if isinstance(value, str) and value.startswith("<"):
                try:
                    if not (float(rec_val or 0) < float(value[1:])):
                        return False
                except (ValueError, TypeError):
                    return False
                continue
            if isinstance(value, list):
                if rec_val not in value:
                    return False
            elif rec_val != value:
                return False
        return True

    def _calc_metric(self, records: list, field_name: str, func: str) -> Any:
        if func == "count":
            return len(records)
        values = [r.get(field_name) for r in records if r.get(field_name) is not None]
        numeric = []
        for v in values:
            try:
                numeric.append(float(v))
            except (ValueError, TypeError):
                pass
        if not numeric:
            return 0
        if func == "sum":
            return round(sum(numeric), 2)
        if func == "avg":
            return round(sum(numeric) / len(numeric), 2)
        if func == "min":
            return min(numeric)
        if func == "max":
            return max(numeric)
        return len(records)

    def _log(self, action: str, entity: str, record_id: str, data: dict, **extra):
        self._audit_log.append({
            "action": action, "entity": entity, "record_id": record_id,
            "data": data, "timestamp": _now(), **extra,
        })

    @property
    def audit_log(self) -> list[dict]:
        return self._audit_log

    def get_stats(self) -> dict:
        """返回数据库统计"""
        return {entity: len(records) for entity, records in self._data.items()}
