"""
Mock 数据查看 API — 提供 CRM 模拟数据和元数据 Schema 的浏览接口

路由前缀: /api/mock-data
用途: 开发/调试阶段查看 Agent 使用的 Mock 数据和对应的元数据描述

字段结构对齐 paas-platform-service 标准：
  - Entity（对象）→ XEntity 字段结构
  - Item（字段）→ XEntityItem 字段结构（itemType 使用数字编码）
  - Link（关联）→ entityLink 字段结构（parentEntityApiKey/childEntityApiKey/linkType）
  - PickOption（选项值）→ pickOption 字段结构

接口清单:
  GET  /api/mock-data/entities           — 列出所有业务对象（XEntity 格式）
  GET  /api/mock-data/schema/{entity}    — 查看某个业务对象的元数据 Schema（XMetaModel 格式）
  GET  /api/mock-data/records/{entity}   — 查看某个业务对象的 Mock 数据记录
  GET  /api/mock-data/stats              — 数据总览统计
  GET  /api/mock-data/full               — 完整导出（所有 Schema + 所有数据）
"""
from __future__ import annotations

import logging
import time
from typing import Any, Optional

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/mock-data", tags=["Mock 数据查看"])


# ═══════════════════════════════════════════════════════════
# paas-platform-service 标准字段类型映射
# 参照 p_meta_item.item_type 编码：
#   1=文本(VARCHAR), 2=长文本(TEXT), 3=选择(SELECT/PICK_LIST),
#   4=布尔(BOOLEAN), 5=数字(INTEGER/DECIMAL), 6=日期(DATE/DATETIME),
#   8=JSON, 10=关联(LOOKUP/RELATIONSHIP), 31=开关(FLAG)
# ═══════════════════════════════════════════════════════════

ITEM_TYPE_MAP = {
    "VARCHAR": 1,
    "TEXT": 2,
    "PICK_LIST": 3,
    "MULTI_PICK_LIST": 3,
    "BOOLEAN": 4,
    "INTEGER": 5,
    "DECIMAL": 5,
    "DATE": 6,
    "DATETIME": 6,
    "JSON": 8,
    "RELATIONSHIP": 10,
    "LOOKUP": 10,
    "FLAG": 31,
}

# dataType 映射（底层存储类型）
DATA_TYPE_MAP = {
    "VARCHAR": 1,    # 字符串
    "TEXT": 1,       # 字符串（长文本）
    "PICK_LIST": 1,  # 字符串（选项值存 apiKey）
    "MULTI_PICK_LIST": 1,
    "BOOLEAN": 6,    # smallint
    "INTEGER": 3,    # 整数
    "DECIMAL": 4,    # 小数
    "DATE": 3,       # bigint（时间戳）
    "DATETIME": 3,
    "JSON": 5,       # text
    "RELATIONSHIP": 3,  # bigint（关联 ID）
    "LOOKUP": 3,
    "FLAG": 6,       # smallint
}

# linkType 映射
LINK_TYPE_MAP = {
    "ONE_TO_MANY": 1,
    "MANY_TO_ONE": 2,
    "MANY_TO_MANY": 3,
    "ONE_TO_ONE": 4,
}

# dbColumn 自动分配前缀
DB_COLUMN_PREFIX = {
    1: "dbc_varchar",    # 文本
    2: "dbc_textarea",   # 长文本
    3: "dbc_int",        # 选择
    5: "dbc_int",        # 数字（整数）
    6: "dbc_bigint",     # 日期
    10: "dbc_varchar",   # 关联
    31: "dbc_smallint",  # 开关
}


def _get_schemas() -> dict[str, dict]:
    """获取 ENTITY_SCHEMAS 定义"""
    from src.tools.crm_backend import ENTITY_SCHEMAS
    return ENTITY_SCHEMAS


def _get_seed_data() -> dict[str, list[dict]]:
    """获取当前 CRM 后端的实时数据（与 Agent 共享同一实例）"""
    try:
        from server import get_crm_backend
        backend = get_crm_backend()
        return backend._data
    except Exception:
        # fallback: 直接构建种子数据
        from src.tools.crm_seed_data import build_seed_data
        return build_seed_data()


# 通用字段中文标签（seed data 中常见的字段名 → 中文）
_COMMON_FIELD_LABELS: dict[str, str] = {
    "id": "ID",
    "name": "名称",
    "label": "标签",
    "apiKey": "API Key",
    "createdAt": "创建时间",
    "updatedAt": "更新时间",
    "createdBy": "创建人",
    "updatedBy": "更新人",
    "ownerName": "负责人",
    "ownerId": "负责人ID",
    "activeFlg": "是否活跃",
    "enableFlg": "是否启用",
    "deleteFlg": "删除标记",
    "industry": "行业",
    "city": "城市",
    "employeeCount": "员工数",
    "annualRevenue": "年营收(万元)",
    "website": "网站",
    "rating": "评分",
    "title": "职位",
    "phone": "电话",
    "email": "邮箱",
    "accountId": "所属客户",
    "isPrimary": "主要联系人",
    "amount": "金额(万元)",
    "stage": "阶段",
    "probability": "赢单概率(%)",
    "closeDate": "预计关闭日期",
    "source": "来源",
    "lastActivityDate": "最后活动日期",
    "type": "类型",
    "subject": "主题",
    "description": "描述",
    "opportunityId": "关联商机",
    "contactId": "关联联系人",
    "dueDate": "截止日期",
    "status": "状态",
    "company": "公司",
    "score": "评分",
}

# 字段业务描述（apiKey → 业务含义说明）
_FIELD_DESCRIPTIONS: dict[str, dict[str, str]] = {
    "account": {
        "accountChannel": "客户获取渠道，记录客户最初通过何种方式进入系统（如官网注册、销售拓展、合作伙伴推荐等）",
        "accountName": "客户的正式注册公司名称，作为客户唯一标识的主要展示字段",
        "accountScore": "系统根据客户活跃度、成交历史、互动频率等维度自动计算的综合评分（0-100）",
        "actualInvoicedAmount": "已开具发票的累计金额，反映客户的实际应收账款总额",
        "amountUnbilled": "已确认收入但尚未开具发票的金额，用于财务对账和催收管理",
        "annualRevenue": "客户企业的年度营业收入（万元），用于评估客户规模和购买力",
        "claimTime": "销售人员从公海池中认领该客户的时间，用于计算跟进时效",
        "duplicateFlg": "系统查重标记，标识该客户是否与其他客户记录存在疑似重复",
        "employeeNumber": "客户企业的员工总数，用于判断企业规模等级",
        "expireTime": "客户保护期到期时间，到期后未成交将自动退回公海池",
        "fCity": "客户所在城市，用于区域销售管理和地域分析",
        "fDistrict": "客户所在区/县，精确定位客户地理位置",
        "fState": "客户所在省份，用于大区划分和区域业绩统计",
        "highSeaAccountSource": "客户进入公海池的来源（如超期未跟进回收、销售主动释放、系统自动回收等）",
        "highSeaId": "客户当前所属的公海池ID，关联公海池规则配置",
        "highSeaStatus": "客户在公海池中的状态（活跃/冻结/已领取等）",
        "industryId": "客户所属行业分类，用于行业维度的销售分析和策略制定",
        "invoiceBalance": "应收账款余额（欠款），即已开票未收款的金额",
        "isCustomer": "标识该账户是否已有成交订单，区分潜在客户和正式客户",
        "paidAmount": "客户累计已付款金额，用于计算回款率和信用评估",
        "parentAccountId": "上级客户/母公司ID，用于构建集团客户层级关系",
        "paymentHealthPct": "应收健康度百分比，反映客户付款及时性（越高越健康）",
        "paymentRate": "客户历史付款比例，已付金额/应付总额，用于信用风险评估",
        "recentActivityCreatedBy": "最近一次跟进活动的创建人，用于判断当前跟进责任人",
        "releaseDescription": "客户被退回公海时填写的原因说明",
        "score": "客户价值分值，基于成交金额、活跃度等因素的综合打分",
        "territoryHighSeaId": "客户所属的区域公海池ID，用于区域化的客户分配管理",
        "totalActiveOrders": "该客户当前生效中的订单数量",
        "totalContract": "该客户关联的合同总数",
        "totalOrderAmount": "该客户所有订单的累计金额",
        "totalWonOpportunities": "该客户已赢单的商机总数，反映客户的成交活跃度",
        "totalWonOpportunityAmount": "该客户已赢单商机的累计金额",
        "unpaidAmount": "未收款金额，用于应收账款管理和催收优先级排序",
        "valueScore": "客户价值评分，综合考虑营收贡献、增长潜力、战略价值等维度",
        "vipFlag": "VIP客户标识，标记为VIP的客户享有优先服务和专属资源",
        "visitLatestTime": "最近一次拜访该客户的时间戳",
        "visitTotalCount": "累计拜访该客户的总次数",
        "visitUnvisitDay": "距离上次拜访已过去的天数，用于提醒销售及时跟进",
    },
    "contact": {
        "address": "联系人的通讯地址，用于邮寄合同、发票等纸质文件",
        "comment": "联系人备注信息，记录特殊偏好、注意事项等",
        "contactBirthday": "联系人生日，用于客户关怀和节日问候",
        "contactChannel": "联系人获取渠道（如名片交换、官网注册、活动认识等）",
        "contactName": "联系人姓名，作为沟通时的称呼依据",
        "contactRole": "联系人在客户组织中的角色（如决策者、影响者、使用者、把关者）",
        "contactScore": "联系人活跃度评分，基于互动频率和响应质量计算",
        "countryId": "联系人所在城市ID，用于地域化沟通策略",
        "depart": "联系人所在部门，帮助理解其在组织中的职能定位",
        "doNotDisturb": "免打扰标记，标记后系统不会向该联系人发送营销信息",
        "email": "联系人电子邮箱，用于邮件沟通和系统通知",
        "externalUserId": "外部系统用户ID，用于与第三方系统（如企业微信）的身份关联",
        "gender": "联系人性别，用于称呼和个性化沟通",
        "leadId": "该联系人转化自哪条线索，记录线索→联系人的转化链路",
        "mobile": "联系人手机号码，用于电话沟通和短信通知",
        "phone": "联系人座机号码",
        "pinyin": "联系人姓名拼音，用于拼音排序和模糊搜索",
        "post": "联系人职务/头衔，帮助判断其决策权限",
        "recentActivityRecordId": "最近一次与该联系人相关的活动记录ID",
        "recentActivityRecordTime": "最近一次活动记录的时间，用于判断跟进时效",
        "recentActivityRecordType": "最近活动的类型（电话/邮件/拜访等）",
        "registrationUtmId": "联系人注册时的UTM追踪ID，用于营销归因分析",
        "state": "联系人所在省份",
        "territoryId": "联系人所属销售区域，用于区域化管理",
        "zipCode": "联系人邮政编码",
    },
    "opportunity": {
        "actualCost": "商机实际花费的销售成本（差旅、招待、样品等）",
        "actualPeriod": "商机从创建到关闭的实际天数",
        "campaignContactId": "通过市场活动关联的联系人，记录营销触达路径",
        "campaignId": "商机来源的市场活动，用于营销ROI归因",
        "closeDate": "预计或实际结单日期，用于销售预测和Pipeline管理",
        "commitmentFlg": "销售承诺标记，标识该商机是否已向管理层做出成交承诺",
        "discount": "给予客户的折扣比例，用于利润分析",
        "duplicateCheckExplanation": "智能查重的结果说明，描述与哪些商机疑似重复",
        "duplicateCheckResultTime": "最近一次执行智能查重的时间",
        "fcastMoney": "预测金额 = 销售金额 × 赢单概率，用于收入预测",
        "forecastCategory": "预测分类（如Pipeline/Best Case/Commit/Closed），用于销售预测报表",
        "intelligentDuplicateCheckResult": "AI智能查重的结论（重复/疑似/无重复）",
        "invoiceDate": "开票日期，记录该商机对应的发票开具时间",
        "lostStageId": "输单时所处的销售阶段，用于分析在哪个阶段容易丢单",
        "money": "商机的销售金额（万元），即预期成交总价",
        "oppHealthAssessmentLevel": "AI评估的商机健康度等级（优/良/中/差）",
        "oppHealthAssessmentScore": "AI评估的商机健康度分数（0-100）",
        "oppHealthAssessmentShow": "商机健康度的前端展示文本",
        "opportunityCode": "商机编号，系统自动生成的唯一业务编码",
        "opportunityName": "商机名称，通常包含客户名+产品/项目关键词",
        "opportunityScore": "商机综合得分，基于金额、阶段、活跃度等因素计算",
        "opportunityType": "商机类型（新签/续约/增购/升级等）",
        "paymentDate": "预计或实际付款日期",
        "priceId": "关联的价格表，决定该商机适用的产品定价策略",
        "projectBudget": "客户的项目预算金额，用于判断报价空间",
        "reasonDesc": "输单原因的详细描述，用于复盘和改进",
        "repeatFlg": "重复商机标记，标识是否与已有商机存在重复",
        "roiCiCount": "ROI影响力计数，记录影响该商机的营销触点数量",
        "saleStageId": "当前销售阶段（如初步接洽/需求确认/方案报价/商务谈判/合同签署）",
        "seemDuplicateRuleId": "触发疑似查重的规则ID",
        "sourceId": "商机来源渠道（如官网/转介绍/市场活动/合作伙伴等）",
        "stageUpdatedAt": "销售阶段最近一次变更的时间，用于计算阶段停留时长",
        "standardPeriod": "该类型商机的标准成交周期（天），用于对比实际周期是否超期",
        "suspectedOpportunityAnalysis": "AI对疑似重复商机的分析说明",
        "winRate": "赢单概率百分比，随阶段推进自动更新或手动调整",
        "winReason": "赢单原因分类（如价格优势/产品匹配/关系优势/服务优势等）",
        "winReasonDesc": "赢单原因的详细描述",
    },
    "lead": {
        "adDmpLeadId": "广告DMP平台的线索唯一标识，用于广告投放效果追踪",
        "adPlanName": "产生该线索的广告计划名称，用于营销归因",
        "adPlatform": "广告投放平台（如百度/头条/腾讯/LinkedIn等）",
        "adProjectName": "广告投放项目名称",
        "adRetentionTime": "用户在广告落地页的留资时间",
        "adSource": "广告投放的具体来源（如搜索广告/信息流/开屏等）",
        "applyDelayTime": "申请延期保护的时间，延长线索跟进保护期",
        "bdType": "大数据线索类型分类",
        "claimTime": "销售从线索公海中认领该线索的时间",
        "companyName": "线索关联的公司名称",
        "contactId": "线索转化后关联的联系人ID",
        "countryId": "线索所在省份/地区",
        "expireTime": "线索保护期到期时间，到期未转化将退回公海",
        "lastOwnerId": "线索上一任负责人ID，用于追溯跟进历史",
        "leadChannel": "线索获取渠道（如官网表单/400电话/线下活动/合作伙伴等）",
        "leadHighSeaId": "线索所属的线索公海池ID",
        "leadHighSeaStatus": "线索在公海中的状态（活跃/已认领/已转化/无效等）",
        "leadQuality": "线索质量等级（高/中/低），基于企业规模、需求匹配度等评估",
        "leadScore": "线索评分，基于行为数据和属性数据的综合打分",
        "leadSourceId": "线索来源的详细分类ID",
        "opportunityId": "线索转化后生成的商机ID，记录线索→商机的转化链路",
        "phoneLocation": "线索手机号的归属地信息，用于区域分配",
        "releaseDefinition": "线索被退回公海时的原因说明",
        "releaseNum": "该线索被退回公海的累计次数",
        "releaseReason": "退回原因分类（如无法联系/非目标客户/需求不匹配等）",
        "releaseTime": "最近一次退回公海的时间",
        "returnTimes": "线索被退回的总次数，多次退回可能标记为低质量线索",
        "scoreDetail": "线索评分的详细分析说明（各维度得分明细）",
        "statusUpdatedAt": "线索状态最近一次变更的时间",
        "territoryLeadHighSeaId": "线索所属的区域线索公海池ID",
        "thawTime": "线索解冻时间（被冻结后重新可被认领的时间）",
    },
    "activity": {
        "activityType": "活动类型（电话/邮件/拜访/会议/任务/备注），决定活动的记录模板",
        "subject": "活动主题，简要描述本次活动的目的或内容",
        "description": "活动详细描述，记录沟通内容、客户反馈、下一步计划等",
        "accountId": "活动关联的客户，用于客户维度的活动统计",
        "opportunityId": "活动关联的商机，用于商机推进过程的活动追踪",
        "contactId": "活动关联的联系人，记录本次沟通的对象",
        "dueDate": "活动的计划完成日期/截止日期",
        "status": "活动状态（待处理/已完成/已取消），用于任务管理",
        "createdAt": "活动记录的创建时间",
    },
}

# seed data 字段名 → schema 字段名的映射
# seed data 使用简化字段名，schema 使用 paas-platform-service 中的真实字段名
_SEED_TO_SCHEMA_FIELD_MAP: dict[str, dict[str, str]] = {
    "account": {
        "name": "accountName",
        "industry": "industryId",
        "city": "fCity",
        "employeeCount": "employeeNumber",
        "rating": "score",
        "activeFlg": "highSeaStatus",
        "ownerName": "ownerName",
    },
    "contact": {
        "name": "contactName",
        "title": "post",
        "phone": "phone",
        "email": "email",
        "accountId": "accountId",
        "isPrimary": "contactRole",
    },
    "opportunity": {
        "name": "opportunityName",
        "amount": "money",
        "stage": "saleStageId",
        "probability": "winRate",
        "closeDate": "closeDate",
        "source": "sourceId",
        "lastActivityDate": "stageUpdatedAt",
    },
    "lead": {
        "name": "companyName",
        "company": "companyName",
        "phone": "phone",
        "email": "email",
        "source": "leadChannel",
        "status": "leadHighSeaStatus",
        "score": "leadScore",
    },
    "activity": {
        "type": "activityType",
    },
}


def _generate_default_value(item: dict, entity_api_key: str, row_idx: int) -> Any:
    """为 Schema 中定义但 seed data 中缺失的字段生成合理的业务数据"""
    import random
    random.seed(hash(f"{entity_api_key}_{item['api_key']}_{row_idx}") % (2**31))

    api_key = item["api_key"]

    # ── 客户（account）字段补全 ──
    if entity_api_key == "account":
        return _gen_account_field(api_key, row_idx, item)
    # ── 联系人（contact）字段补全 ──
    elif entity_api_key == "contact":
        return _gen_contact_field(api_key, row_idx, item)
    # ── 通用默认值 ──
    else:
        return _gen_generic_field(item, row_idx)


# 省市区数据
_PROVINCES = ["广东省", "浙江省", "北京市", "上海市", "江苏省", "福建省", "四川省", "湖北省", "山东省", "湖南省"]
_CITIES_BY_PROVINCE = {
    "广东省": ["深圳市", "广州市", "东莞市", "佛山市", "珠海市"],
    "浙江省": ["杭州市", "宁波市", "温州市", "嘉兴市"],
    "北京市": ["北京市"],
    "上海市": ["上海市"],
    "江苏省": ["南京市", "苏州市", "无锡市", "常州市"],
    "福建省": ["福州市", "厦门市", "泉州市", "宁德市"],
    "四川省": ["成都市", "绵阳市"],
    "湖北省": ["武汉市", "宜昌市"],
    "山东省": ["济南市", "青岛市", "烟台市"],
    "湖南省": ["长沙市", "株洲市"],
}
_DISTRICTS_BY_CITY = {
    "深圳市": ["南山区", "福田区", "宝安区", "龙岗区", "龙华区"],
    "广州市": ["天河区", "海珠区", "越秀区", "白云区"],
    "杭州市": ["西湖区", "滨江区", "余杭区", "萧山区"],
    "北京市": ["朝阳区", "海淀区", "西城区", "东城区", "丰台区"],
    "上海市": ["浦东新区", "徐汇区", "静安区", "黄浦区", "长宁区"],
    "南京市": ["鼓楼区", "建邺区", "玄武区"],
    "苏州市": ["工业园区", "姑苏区", "吴中区"],
    "成都市": ["高新区", "武侯区", "锦江区"],
    "武汉市": ["武昌区", "洪山区", "江汉区"],
}

# 客户来源渠道
_ACCOUNT_CHANNELS = ["官网注册", "销售拓展", "合作伙伴推荐", "市场活动", "老客户转介绍", "行业展会", "电话营销"]
_HIGHSEA_SOURCES = ["超期未跟进回收", "销售主动释放", "系统自动回收", "离职回收", "区域调整回收"]
_VIP_FLAGS = ["VIP", "SVIP", "普通", "普通", "普通", "普通", "VIP", "普通"]

# 联系人相关
_GENDERS = ["男", "女"]
_CONTACT_CHANNELS = ["名片交换", "官网注册", "活动认识", "转介绍", "电话沟通", "邮件往来"]
_DEPARTMENTS = ["技术部", "销售部", "市场部", "财务部", "采购部", "总经理办公室", "产品部", "运营部"]
_ADDRESSES = [
    "科技园南区A栋18楼", "创业大厦12层1205室", "金融中心B座3301",
    "高新技术产业园区6号楼", "商务中心大厦22层", "科创园区C栋5楼",
    "互联网产业园3期8号楼", "总部基地2号楼16层", "创新大厦A座901",
    "数字经济产业园15栋",
]
_ZIP_CODES = ["518000", "310000", "100000", "200000", "210000", "350000", "610000", "430000", "250000", "410000"]


def _gen_account_field(api_key: str, row_idx: int, item: dict) -> Any:
    """为 account 实体生成字段值"""
    import random
    random.seed(hash(f"account_{api_key}_{row_idx}") % (2**31))

    # 省市区 — 根据 row_idx 分配不同地区
    province = _PROVINCES[row_idx % len(_PROVINCES)]
    cities = _CITIES_BY_PROVINCE.get(province, ["未知市"])
    city = cities[row_idx % len(cities)]
    districts = _DISTRICTS_BY_CITY.get(city, ["未知区"])
    district = districts[row_idx % len(districts)]

    field_values = {
        "accountChannel": _ACCOUNT_CHANNELS[row_idx % len(_ACCOUNT_CHANNELS)],
        "fState": province,
        "fDistrict": district,
        "highSeaAccountSource": _HIGHSEA_SOURCES[row_idx % len(_HIGHSEA_SOURCES)] if row_idx % 3 == 0 else None,
        "highSeaId": None,  # 大部分客户不在公海
        "highSeaStatus": "活跃",
        "parentAccountId": None,  # 大部分无上级客户
        "recentActivityCreatedBy": f"user_{['zhang','li','wang'][row_idx % 3]}",
        "releaseDescription": None,  # 未退回公海的客户无描述
        "territoryHighSeaId": None,
        "vipFlag": _VIP_FLAGS[row_idx % len(_VIP_FLAGS)],
    }

    if api_key in field_values:
        return field_values[api_key]

    # 未明确指定的字段，走通用生成
    return _gen_generic_field(item, row_idx)


def _gen_contact_field(api_key: str, row_idx: int, item: dict) -> Any:
    """为 contact 实体生成字段值"""
    import random
    random.seed(hash(f"contact_{api_key}_{row_idx}") % (2**31))

    # 省市区
    province = _PROVINCES[row_idx % len(_PROVINCES)]
    cities = _CITIES_BY_PROVINCE.get(province, ["未知市"])
    city = cities[row_idx % len(cities)]

    # 姓名拼音
    _PINYINS = ["zhangwei", "liwang", "wangfang", "liuyang", "chenming",
                "zhaojun", "huangli", "zhouxin", "wuqiang", "sunhao",
                "zhengkai", "maxiao", "linjie", "heping", "guohua",
                "heyun", "luobin", "xieting", "dengchao", "fenglei",
                "jiangnan", "caixin", "panyu", "dongmei", "tangwei"]

    _MOBILES = [f"138{random.randint(10000000, 99999999)}" for _ in range(25)]

    field_values = {
        "address": _ADDRESSES[row_idx % len(_ADDRESSES)],
        "comment": None,  # 备注通常为空
        "contactChannel": _CONTACT_CHANNELS[row_idx % len(_CONTACT_CHANNELS)],
        "depart": _DEPARTMENTS[row_idx % len(_DEPARTMENTS)],
        "gender": _GENDERS[row_idx % 2],
        "mobile": f"138{10000000 + row_idx * 1111:08d}",
        "pinyin": _PINYINS[row_idx % len(_PINYINS)],
        "recentActivityRecordId": None,
        "registrationUtmId": None,
        "state": province,
        "territoryId": None,
        "zipCode": _ZIP_CODES[row_idx % len(_ZIP_CODES)],
    }

    if api_key in field_values:
        return field_values[api_key]

    # 未明确指定的字段，走通用生成
    return _gen_generic_field(item, row_idx)


def _gen_generic_field(item: dict, row_idx: int) -> Any:
    """通用默认值生成"""
    import random
    random.seed(hash(f"generic_{item['api_key']}_{row_idx}") % (2**31))

    raw_type = item.get("item_type", "VARCHAR")
    api_key = item["api_key"]

    if raw_type == "RELATIONSHIP":
        return None
    elif raw_type == "BOOLEAN":
        return random.choice([0, 1])
    elif raw_type == "INTEGER":
        if "count" in api_key.lower() or "total" in api_key.lower():
            return random.randint(0, 50)
        elif "day" in api_key.lower():
            return random.randint(0, 90)
        else:
            return random.randint(0, 100)
    elif raw_type == "DECIMAL":
        if "amount" in api_key.lower() or "money" in api_key.lower():
            return round(random.uniform(10000, 500000), 2)
        elif "rate" in api_key.lower() or "pct" in api_key.lower():
            return round(random.uniform(0.1, 0.99), 2)
        elif "score" in api_key.lower():
            return round(random.uniform(30, 95), 1)
        else:
            return round(random.uniform(0, 10000), 2)
    elif raw_type in ("DATE", "DATETIME"):
        return 1710000000000 + random.randint(0, 30000000000)
    elif raw_type == "PICK_LIST":
        return None
    elif raw_type == "TEXT":
        return None
    elif raw_type == "VARCHAR":
        return None
    else:
        return None


def _transform_entity(api_key: str, schema: dict, record_count: int) -> dict:
    """将内部 schema 转换为 paas XEntity 标准格式"""
    items = schema.get("items", [])
    links = schema.get("links", [])
    return {
        "apiKey": api_key,
        "label": schema.get("label", ""),
        "labelKey": f"entity.{api_key}",
        "namespace": "system",
        "entityType": 1,  # 1=标准对象
        "dbTable": f"t_{api_key}",
        "customFlg": 0,
        "enableFlg": 1,
        "deleteFlg": 0,
        "description": f"{schema.get('label', '')}业务对象",
        "descriptionKey": f"entity.{api_key}.desc",
        "hiddenFlg": 0,
        "searchableFlg": 1,
        "sharingFlg": 1,
        "activityFlg": 1 if api_key in ("account", "opportunity", "lead") else 0,
        "historyLogFlg": 1,
        "reportFlg": 1,
        "ownerFlg": 1,
        "teamFlg": 0,
        "detailFlg": 0,
        # 统计信息（非标准字段，前端展示用）
        "recordCount": record_count,
        "fieldCount": len(items),
        "linkCount": len(links),
    }


def _transform_item(item: dict, entity_api_key: str, order: int) -> dict:
    """将内部 item 转换为 paas XEntityItem 标准格式"""
    raw_type = item.get("item_type", "VARCHAR")
    item_type = ITEM_TYPE_MAP.get(raw_type, 1)
    data_type = DATA_TYPE_MAP.get(raw_type, 1)

    # 使用 schema 中的 db_column（如果有），否则自动分配
    db_column = item.get("db_column", "")
    if not db_column:
        prefix = DB_COLUMN_PREFIX.get(item_type, "dbc_varchar")
        db_column = f"{prefix}_{order}"

    # 使用 schema 中的 paas_item_type/paas_data_type（如果有）
    if "paas_item_type" in item:
        item_type = item["paas_item_type"]
    if "paas_data_type" in item:
        data_type = item["paas_data_type"]

    # 获取业务描述
    entity_descs = _FIELD_DESCRIPTIONS.get(entity_api_key, {})
    description = entity_descs.get(item["api_key"], "")

    result = {
        "entityApiKey": entity_api_key,
        "apiKey": item["api_key"],
        "label": item.get("label", ""),
        "labelKey": f"item.{entity_api_key}.{item['api_key']}",
        "description": description,
        "namespace": "system",
        "itemType": item_type,
        "dataType": data_type,
        "dbColumn": db_column,
        "itemOrder": order,
        "requireFlg": 1 if item.get("required") else 0,
        "enableFlg": 1,
        "deleteFlg": 0,
        "customFlg": 0,
        "hiddenFlg": 0,
        "creatable": 1,
        "updatable": 1,
        "uniqueKeyFlg": 1 if item["api_key"] == "name" else 0,
        "historyLogFlg": 1,
        "sortFlg": 1 if item_type in (1, 5, 6) else 0,
        "encryptFlg": 0,
        "readonlyStatus": 0,
        "visibleStatus": 1,
        # 关联字段
        "referEntityApiKey": item.get("refer_entity", ""),
        "referLinkApiKey": "",
        # 选项集
        "referGlobalFlg": 0,
        "globalPickItem": "",
        # 原始类型（调试用）
        "_rawItemType": raw_type,
    }

    # 关联字段补充
    if raw_type in ("RELATIONSHIP", "LOOKUP") and not result["referEntityApiKey"]:
        refer_entity = item["api_key"].replace("Id", "")
        result["referEntityApiKey"] = refer_entity
        result["referLinkApiKey"] = f"{entity_api_key}_{refer_entity}_link"

    # 选项字段补充
    if "options" in item:
        result["referGlobalFlg"] = 0  # 本地选项集
        result["_options"] = item["options"]  # 前端展示用

    return result


def _transform_link(link: dict, entity_api_key: str, order: int) -> dict:
    """将内部 link 转换为 paas entityLink 标准格式"""
    link_type_str = link.get("type", "ONE_TO_MANY")
    link_type = LINK_TYPE_MAP.get(link_type_str, 1)

    # 根据 linkType 确定 parent/child
    if link_type == 1:  # ONE_TO_MANY: 当前实体是 parent
        parent = entity_api_key
        child = link.get("target", "")
    elif link_type == 2:  # MANY_TO_ONE: 当前实体是 child
        parent = link.get("target", "")
        child = entity_api_key
    else:
        parent = entity_api_key
        child = link.get("target", "")

    return {
        "apiKey": f"{parent}_{child}_link_{order}",
        "label": link.get("label", ""),
        "labelKey": f"link.{parent}.{child}",
        "namespace": "system",
        "parentEntityApiKey": parent,
        "childEntityApiKey": child,
        "linkType": link_type,
        "detailLinkFlg": 0,
        "cascadeDelete": 0,
        "accessControl": 0,
        "enableFlg": 1,
        "deleteFlg": 0,
        "customFlg": 0,
        # 原始类型（调试用）
        "_rawLinkType": link_type_str,
    }


def _transform_pick_options(options: list, item_api_key: str, entity_api_key: str) -> list[dict]:
    """将选项列表转换为 paas pickOption 标准格式"""
    result = []
    for i, opt in enumerate(options):
        # 选项值可能是字符串或 dict
        if isinstance(opt, str):
            opt_api_key = opt.replace(" ", "_").lower()
            opt_label = opt
        else:
            opt_api_key = opt.get("api_key", str(i))
            opt_label = opt.get("label", str(opt))

        result.append({
            "apiKey": opt_api_key,
            "label": opt_label,
            "labelKey": f"pick.{entity_api_key}.{item_api_key}.{opt_api_key}",
            "entityApiKey": entity_api_key,
            "itemApiKey": item_api_key,
            "namespace": "system",
            "optionOrder": i + 1,
            "defaultFlg": 1 if i == 0 else 0,
            "enableFlg": 1,
            "deleteFlg": 0,
            "customFlg": 0,
        })
    return result


# ═══════════════════════════════════════════════════════════
# 接口实现
# ═══════════════════════════════════════════════════════════


@router.get("/entities", summary="列出所有业务对象（XEntity 格式）")
async def list_entities():
    """列出所有业务对象，返回 paas XEntity 标准字段结构。"""
    schemas = _get_schemas()
    seed_data = _get_seed_data()

    entities = []
    for api_key, schema in schemas.items():
        record_count = len(seed_data.get(api_key, []))
        entities.append(_transform_entity(api_key, schema, record_count))

    return JSONResponse(content={
        "entities": entities,
        "total_entities": len(entities),
        "total_records": sum(len(v) for v in seed_data.values()),
    })


@router.get("/schema/{entity_api_key}", summary="查看业务对象的元数据 Schema（XMetaModel 格式）")
async def get_entity_schema(
    entity_api_key: str,
    include_options: bool = Query(True, description="是否包含选项字段的取值列表"),
):
    """查看某个业务对象的完整元数据 Schema，返回 paas XMetaModel 标准格式。

    包含:
    - entity: XEntity 基本信息
    - items: XEntityItem[] 字段列表（itemType 为数字编码）
    - links: entityLink[] 关联关系
    - pickOptionsMap: { itemApiKey: pickOption[] } 选项值映射
    """
    schemas = _get_schemas()
    seed_data = _get_seed_data()
    schema = schemas.get(entity_api_key)

    if schema is None:
        return JSONResponse(
            status_code=404,
            content={"error": f"业务对象 '{entity_api_key}' 不存在", "available": list(schemas.keys())},
        )

    record_count = len(seed_data.get(entity_api_key, []))

    # 转换 items
    items = []
    pick_options_map: dict[str, list] = {}
    for i, item in enumerate(schema.get("items", []), start=1):
        transformed = _transform_item(item, entity_api_key, i)
        items.append(transformed)
        # 收集选项值
        if include_options and "options" in item:
            pick_options_map[item["api_key"]] = _transform_pick_options(
                item["options"], item["api_key"], entity_api_key
            )

    # 转换 links
    links = []
    for i, link in enumerate(schema.get("links", []), start=1):
        links.append(_transform_link(link, entity_api_key, i))

    # 构建数据字段的中文标签映射（seed data 中实际使用的字段名 → 中文）
    # Schema items 中的 api_key 可能与 seed data 字段名不同，需要额外映射
    data_field_labels: dict[str, str] = {}
    # 从 schema items 中提取
    for item in schema.get("items", []):
        data_field_labels[item["api_key"]] = item.get("label", item["api_key"])
    # 补充 seed data 中实际存在但 schema 中可能用不同名称的字段
    records = seed_data.get(entity_api_key, [])
    if records:
        for key in records[0].keys():
            if key not in data_field_labels:
                # 直接使用通用中文映射
                data_field_labels[key] = _COMMON_FIELD_LABELS.get(key, key)

    result = {
        "entity": _transform_entity(entity_api_key, schema, record_count),
        "items": items,
        "links": links,
        "pickOptionsMap": pick_options_map,
        "dataFieldLabels": data_field_labels,
    }

    return JSONResponse(content=result)


@router.get("/records/{entity_api_key}", summary="查看业务对象的 Mock 数据记录")
async def get_entity_records(
    entity_api_key: str,
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=100, description="每页条数"),
    fields: Optional[str] = Query(None, description="返回字段（逗号分隔），不传返回全部"),
):
    """查看某个业务对象的 Mock 数据记录（分页）。

    返回格式对齐 paas entity-data 标准：
    - 字段名映射为 Schema 中的 apiKey
    - Schema 中定义但 seed data 中缺失的字段自动补全默认值
    """
    schemas = _get_schemas()
    seed_data = _get_seed_data()

    if entity_api_key not in schemas:
        return JSONResponse(
            status_code=404,
            content={"error": f"业务对象 '{entity_api_key}' 不存在", "available": list(schemas.keys())},
        )

    records = seed_data.get(entity_api_key, [])
    total = len(records)

    # 获取字段名映射（seed data field → schema field）
    field_map = _SEED_TO_SCHEMA_FIELD_MAP.get(entity_api_key, {})

    # 获取 schema 所有字段及其类型（用于补全默认值）
    schema_items = schemas[entity_api_key].get("items", [])
    schema_field_set = {item["api_key"] for item in schema_items}

    # 分页
    start = (page - 1) * page_size
    page_records = records[start:start + page_size]

    # 映射字段名 + 补全 schema 中定义但数据中缺失的字段
    mapped_records = []
    for idx, r in enumerate(page_records):
        mapped = {"id": r.get("id", f"{entity_api_key}_{idx+1}")}
        # 先映射已有字段（只保留 schema 中存在的）
        for k, v in r.items():
            if k == "id":
                continue
            mapped_key = field_map.get(k, k)
            if mapped_key in schema_field_set:
                mapped[mapped_key] = v
        # 补全 schema 中有但数据中没有的字段
        for item in schema_items:
            ak = item["api_key"]
            if ak not in mapped:
                mapped[ak] = _generate_default_value(item, entity_api_key, idx)
        mapped_records.append(mapped)

    # 字段过滤
    if fields:
        field_list = [f.strip() for f in fields.split(",")]
        mapped_records = [
            {k: r.get(k) for k in ["id"] + field_list if k in r}
            for r in mapped_records
        ]

    return JSONResponse(content={
        "entityApiKey": entity_api_key,
        "entityLabel": schemas[entity_api_key].get("label", ""),
        "records": mapped_records,
        "total": total,
        "page": page,
        "pageSize": page_size,
    })


# ═══════════════════════════════════════════════════════════
# 数据写入接口（create / update / delete）
# ═══════════════════════════════════════════════════════════

class MutateRequest(BaseModel):
    action: str  # create / update / delete
    entity_api_key: str
    record_id: Optional[str] = None
    data: Optional[dict] = None


@router.post("/mutate", summary="修改 Mock 数据（创建/更新/删除）")
async def mutate_record(req: MutateRequest):
    """对 Mock 数据执行增删改操作，与 Agent 的 modify_data 工具共享同一数据源。

    - action=create: 创建新记录，需传 data
    - action=update: 更新记录，需传 record_id + data
    - action=delete: 删除记录，需传 record_id
    """
    try:
        from server import get_crm_backend
        backend = get_crm_backend()
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": f"后端未就绪: {e}"})

    result = await backend.mutate_data(
        req.entity_api_key,
        req.action,
        req.data or {},
        record_id=req.record_id,
    )

    if "error" in result:
        return JSONResponse(status_code=400, content={"error": result["error"]})

    return JSONResponse(content={"success": True, "data": result.get("data", {})})


@router.get("/stats", summary="数据总览统计")
async def get_stats():
    """返回 Mock 数据的总览统计信息（对齐 paas 元数据统计格式）。"""
    schemas = _get_schemas()
    seed_data = _get_seed_data()

    entity_stats = []
    total_fields = 0
    total_links = 0
    total_options = 0

    for api_key, schema in schemas.items():
        items = schema.get("items", [])
        links = schema.get("links", [])
        options_count = sum(1 for item in items if "options" in item)

        total_fields += len(items)
        total_links += len(links)
        total_options += options_count

        entity_stats.append({
            "apiKey": api_key,
            "label": schema.get("label", ""),
            "entityType": 1,
            "recordCount": len(seed_data.get(api_key, [])),
            "fieldCount": len(items),
            "linkCount": len(links),
            "pickListCount": options_count,
            "enableFlg": 1,
        })

    return JSONResponse(content={
        "summary": {
            "totalEntities": len(schemas),
            "totalRecords": sum(len(v) for v in seed_data.values()),
            "totalFields": total_fields,
            "totalLinks": total_links,
            "totalPickListFields": total_options,
        },
        "entities": entity_stats,
        "owners": [
            {"id": "user_zhang", "name": "张明", "role": "华东区销售总监", "scope": "通信+互联网"},
            {"id": "user_li", "name": "李强", "role": "华南区销售经理", "scope": "制造+金融"},
            {"id": "user_wang", "name": "王芳", "role": "华北区销售经理", "scope": "零售+医疗"},
        ],
    })


@router.get("/full", summary="完整导出（Schema + 数据，paas 标准格式）")
async def get_full_export():
    """完整导出所有 Mock 数据和 Schema 定义（paas-platform-service 标准格式）。"""
    schemas = _get_schemas()
    seed_data = _get_seed_data()

    # 转换所有 schema 为 paas 格式
    paas_schemas = {}
    for api_key, schema in schemas.items():
        record_count = len(seed_data.get(api_key, []))
        items = []
        pick_options_map: dict[str, list] = {}
        for i, item in enumerate(schema.get("items", []), start=1):
            items.append(_transform_item(item, api_key, i))
            if "options" in item:
                pick_options_map[item["api_key"]] = _transform_pick_options(
                    item["options"], item["api_key"], api_key
                )
        links = [_transform_link(lk, api_key, j) for j, lk in enumerate(schema.get("links", []), start=1)]

        paas_schemas[api_key] = {
            "entity": _transform_entity(api_key, schema, record_count),
            "items": items,
            "links": links,
            "pickOptionsMap": pick_options_map,
        }

    return JSONResponse(content={
        "schemas": paas_schemas,
        "data": seed_data,
        "metadata": {
            "exportedAt": time.strftime("%Y-%m-%d %H:%M:%S"),
            "version": "2.0",
            "format": "paas-platform-service-compatible",
            "description": "CRM Agent Mock 数据完整导出（对齐 paas-platform-service 元数据标准）",
            "fieldMapping": {
                "itemType": "数字编码: 1=文本, 2=长文本, 3=选择, 4=布尔, 5=数字, 6=日期, 8=JSON, 10=关联, 31=开关",
                "dataType": "底层存储: 1=VARCHAR, 3=INTEGER/BIGINT, 4=DECIMAL, 5=TEXT, 6=SMALLINT",
                "linkType": "关联类型: 1=ONE_TO_MANY, 2=MANY_TO_ONE, 3=MANY_TO_MANY, 4=ONE_TO_ONE",
            },
        },
    })


@router.get("/schema/{entity_api_key}/field/{field_api_key}", summary="查看单个字段的详细定义")
async def get_field_detail(entity_api_key: str, field_api_key: str):
    """查看某个字段的详细元数据定义（XEntityItem 完整字段 + 数据分布统计）。"""
    schemas = _get_schemas()
    seed_data = _get_seed_data()

    schema = schemas.get(entity_api_key)
    if schema is None:
        return JSONResponse(
            status_code=404,
            content={"error": f"业务对象 '{entity_api_key}' 不存在"},
        )

    # 查找字段定义
    field_def = None
    field_order = 0
    for i, item in enumerate(schema.get("items", []), start=1):
        if item["api_key"] == field_api_key:
            field_def = item
            field_order = i
            break

    if field_def is None:
        available_fields = [item["api_key"] for item in schema.get("items", [])]
        return JSONResponse(
            status_code=404,
            content={"error": f"字段 '{field_api_key}' 不存在于 {entity_api_key}", "availableFields": available_fields},
        )

    # 转换为 paas 格式
    transformed = _transform_item(field_def, entity_api_key, field_order)

    # 统计该字段在 Mock 数据中的值分布
    records = seed_data.get(entity_api_key, [])
    values = [r.get(field_api_key) for r in records if r.get(field_api_key) is not None]
    value_distribution: dict[str, int] = {}
    for v in values:
        key = str(v)
        value_distribution[key] = value_distribution.get(key, 0) + 1

    # 选项值
    pick_options = []
    if "options" in field_def:
        pick_options = _transform_pick_options(field_def["options"], field_api_key, entity_api_key)

    result: dict[str, Any] = {
        "entityApiKey": entity_api_key,
        "entityLabel": schema.get("label", ""),
        "field": transformed,
        "pickOptions": pick_options,
        "dataStats": {
            "totalRecords": len(records),
            "nonNullCount": len(values),
            "nullCount": len(records) - len(values),
            "distinctCount": len(set(str(v) for v in values)),
        },
    }

    # 值分布（最多显示 20 个）
    sorted_dist = sorted(value_distribution.items(), key=lambda x: -x[1])
    result["valueDistribution"] = dict(sorted_dist[:20])

    return JSONResponse(content=result)
