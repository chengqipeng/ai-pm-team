"""上下文存档检索评测用例集 — 255 条

覆盖场景:
  A. 代词消解 (30) — 验证 query rewrite 的代词替换
  B. 意图关键词 (35) — 验证意图识别 + 关键词扩展
  C. 实体精确召回 (30) — 按客户名/ID 精确检索
  D. 工具结果检索 (25) — 按工具名/类型检索
  E. 变更追踪 (25) — 金额/日期/状态变更链
  F. 模糊语义 (25) — 同义改写/口语化查询
  G. 负例验证 (20) — 不应命中的查询（完全不相关）
  H. 跨任务 (20) — 跨客户/跨场景关联
  I. 多工具区分 (20) — 同工具多次调用的精确定位
  J. 时序过滤 (10) — 第一次/最后/最近等时间条件
  K. 边界负例 (10) — 相似但不存在的查询（客户存在但业务不存在）

对齐系统中所有 Tool 特性:
  - query_data: 客户/商机/合同/联系人/活动/需求查询
  - analyze_data: BANT/pipeline/报价/续约/竞品分析
  - web_search: 竞品定价/行业调研
  - execute_task: 报价更新/合同创建/签约/POC规划
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ArchiveRecallEvalCase:
    """存档检索评测用例"""
    id: str
    category: str                         # 场景分类
    query: str                            # 用户查询
    active_entities: list[str]            # 当前活跃实体（rewriter 上下文）
    # 改写验证
    expect_rewritten_contains: str = ""   # 改写后应包含的关键词/实体
    expect_intent: str = ""               # 期望意图类型
    expect_keyword_in_result: str = ""    # 关键词提取应包含
    # 检索验证
    expect_hit_turns: list[int] = field(default_factory=list)  # 期望命中的轮次
    expect_entity: str = ""               # 结果应包含的实体
    expect_no_hit: bool = False           # 负例
    # 工具验证
    expect_tool: str = ""                 # 应推断的工具名
    description: str = ""                 # 用例描述


def build_archive_recall_cases() -> list[ArchiveRecallEvalCase]:
    """构建 255 条存档检索评测用例"""
    cases = []
    cases.extend(_pronoun_resolution_cases())
    cases.extend(_intent_keyword_cases())
    cases.extend(_entity_recall_cases())
    cases.extend(_tool_result_cases())
    cases.extend(_change_tracking_cases())
    cases.extend(_fuzzy_semantic_cases())
    cases.extend(_negative_cases())
    cases.extend(_cross_task_cases())
    # 新增分类
    cases.extend(_multi_tool_distinction_cases())
    cases.extend(_temporal_filter_cases())
    cases.extend(_boundary_negative_cases())
    return cases


# ═══════════════════════════════════════════════════════════
# 活跃实体定义（模拟不同对话上下文）
# ═══════════════════════════════════════════════════════════

_ENT_PT = ["PT Sentosa", "opp_001"]
_ENT_HW = ["华为科技", "张总"]
_ENT_TC = ["腾讯云", "Q-TC-001"]
_ENT_BYD = ["比亚迪", "opp_BYD_001"]
_ENT_XM = ["小米", "林总"]


# ═══════════════════════════════════════════════════════════
# A. 代词消解 (30)
# ═══════════════════════════════════════════════════════════

def _pronoun_resolution_cases() -> list[ArchiveRecallEvalCase]:
    return [
        ArchiveRecallEvalCase("PR01", "代词消解", "他们的报价是多少", _ENT_PT, expect_rewritten_contains="PT Sentosa", description="他们→PT Sentosa"),
        ArchiveRecallEvalCase("PR02", "代词消解", "他们商机什么阶段", _ENT_PT, expect_rewritten_contains="PT Sentosa", description="他们→PT Sentosa 商机"),
        ArchiveRecallEvalCase("PR03", "代词消解", "那个客户年营收", _ENT_HW, expect_rewritten_contains="华为科技", description="那个客户→华为科技"),
        ArchiveRecallEvalCase("PR04", "代词消解", "这个客户联系人", _ENT_HW, expect_rewritten_contains="华为科技", description="这个客户→华为科技"),
        ArchiveRecallEvalCase("PR05", "代词消解", "对方接受了吗", _ENT_PT, expect_rewritten_contains="PT Sentosa", description="对方→PT Sentosa"),
        ArchiveRecallEvalCase("PR06", "代词消解", "那边什么反馈", _ENT_TC, expect_rewritten_contains="腾讯云", description="那边→腾讯云"),
        ArchiveRecallEvalCase("PR07", "代词消解", "她们的技术需求", _ENT_TC, expect_rewritten_contains="腾讯云", description="她们→腾讯云"),
        ArchiveRecallEvalCase("PR08", "代词消解", "它的到期时间", _ENT_PT, expect_rewritten_contains="PT Sentosa", description="它→PT Sentosa"),
        ArchiveRecallEvalCase("PR09", "代词消解", "该客户POC结果", _ENT_HW, expect_rewritten_contains="华为科技", description="该客户→华为科技"),
        ArchiveRecallEvalCase("PR10", "代词消解", "那家公司规模", _ENT_HW, expect_rewritten_contains="华为科技", description="那家公司→华为科技"),
        ArchiveRecallEvalCase("PR11", "代词消解", "他们砍了多少", _ENT_PT, expect_rewritten_contains="PT Sentosa", description="他们砍价→PT Sentosa"),
        ArchiveRecallEvalCase("PR12", "代词消解", "对方签约了没", _ENT_BYD, expect_rewritten_contains="比亚迪", description="对方→比亚迪"),
        ArchiveRecallEvalCase("PR13", "代词消解", "这家公司什么行业", _ENT_BYD, expect_rewritten_contains="比亚迪", description="这家公司→比亚迪"),
        ArchiveRecallEvalCase("PR14", "代词消解", "他们的合同状态", _ENT_TC, expect_rewritten_contains="腾讯云", description="他们合同→腾讯云"),
        ArchiveRecallEvalCase("PR15", "代词消解", "它还在谈判阶段吗", _ENT_BYD, expect_rewritten_contains="比亚迪", description="它→比亚迪"),
        ArchiveRecallEvalCase("PR16", "代词消解", "那个客户的BANT分析", _ENT_HW, expect_rewritten_contains="华为科技", description="那个客户BANT→华为"),
        ArchiveRecallEvalCase("PR17", "代词消解", "他们最终报价", _ENT_HW, expect_rewritten_contains="华为科技", description="他们最终→华为"),
        ArchiveRecallEvalCase("PR18", "代词消解", "该客户付款条件", _ENT_PT, expect_rewritten_contains="PT Sentosa", description="该客户付款→PT"),
        ArchiveRecallEvalCase("PR19", "代词消解", "对方CTO是谁", _ENT_HW, expect_rewritten_contains="华为科技", description="对方CTO→华为"),
        ArchiveRecallEvalCase("PR20", "代词消解", "那边的需求清单", _ENT_TC, expect_rewritten_contains="腾讯云", description="那边需求→腾讯"),
        ArchiveRecallEvalCase("PR21", "代词消解", "他们预算多少", _ENT_XM, expect_rewritten_contains="小米", description="他们预算→小米"),
        ArchiveRecallEvalCase("PR22", "代词消解", "该客户风险评估", _ENT_PT, expect_rewritten_contains="PT Sentosa", description="该客户风险→PT"),
        ArchiveRecallEvalCase("PR23", "代词消解", "那个客户实施周期", _ENT_HW, expect_rewritten_contains="华为科技", description="那个客户实施→华为"),
        ArchiveRecallEvalCase("PR24", "代词消解", "对方的决策链", _ENT_BYD, expect_rewritten_contains="比亚迪", description="对方决策→比亚迪"),
        ArchiveRecallEvalCase("PR25", "代词消解", "他们用什么竞品", _ENT_BYD, expect_rewritten_contains="比亚迪", description="他们竞品→比亚迪"),
        ArchiveRecallEvalCase("PR26", "代词消解", "它的技术栈要求", _ENT_XM, expect_rewritten_contains="小米", description="它技术栈→小米"),
        ArchiveRecallEvalCase("PR27", "代词消解", "那家公司签约时间", _ENT_BYD, expect_rewritten_contains="比亚迪", description="那家签约→比亚迪"),
        ArchiveRecallEvalCase("PR28", "代词消解", "他们的POC通过了吗", _ENT_HW, expect_rewritten_contains="华为科技", description="他们POC→华为"),
        ArchiveRecallEvalCase("PR29", "代词消解", "该客户方案确认了没", _ENT_TC, expect_rewritten_contains="腾讯云", description="该客户方案→腾讯"),
        ArchiveRecallEvalCase("PR30", "代词消解", "那边的项目进展", _ENT_XM, expect_rewritten_contains="小米", description="那边项目→小米"),
    ]


# ═══════════════════════════════════════════════════════════
# B. 意图关键词 (30)
# ═══════════════════════════════════════════════════════════

def _intent_keyword_cases() -> list[ArchiveRecallEvalCase]:
    return [
        # 变更追踪意图
        ArchiveRecallEvalCase("IK01", "意图关键词", "报价怎么变的", _ENT_PT, expect_intent="change_tracking"),
        ArchiveRecallEvalCase("IK02", "意图关键词", "金额调整了几次", _ENT_PT, expect_intent="change_tracking"),
        ArchiveRecallEvalCase("IK03", "意图关键词", "从$45K改到多少了", _ENT_PT, expect_intent="change_tracking"),
        ArchiveRecallEvalCase("IK04", "意图关键词", "之前是多少钱", _ENT_PT, expect_intent="change_tracking"),
        ArchiveRecallEvalCase("IK05", "意图关键词", "价格演变历史", _ENT_PT, expect_intent="change_tracking"),
        ArchiveRecallEvalCase("IK06", "意图关键词", "实施周期缩短了吗", _ENT_HW, expect_intent="change_tracking"),
        # 决策原因意图
        ArchiveRecallEvalCase("IK07", "意图关键词", "为什么降价了", _ENT_PT, expect_intent="decision_reason"),
        ArchiveRecallEvalCase("IK08", "意图关键词", "谁同意的这个价格", _ENT_PT, expect_intent="decision_reason"),
        ArchiveRecallEvalCase("IK09", "意图关键词", "降价的理由", _ENT_PT, expect_intent="decision_reason"),
        ArchiveRecallEvalCase("IK10", "意图关键词", "怎么定的这个方案", _ENT_HW, expect_intent="decision_reason"),
        ArchiveRecallEvalCase("IK11", "意图关键词", "谁批准去掉实时告警", _ENT_TC, expect_intent="decision_reason"),
        ArchiveRecallEvalCase("IK12", "意图关键词", "砍价的依据是什么", _ENT_TC, expect_intent="decision_reason"),
        # 最新状态意图
        ArchiveRecallEvalCase("IK13", "意图关键词", "最新报价是多少", _ENT_PT, expect_intent="latest_state"),
        ArchiveRecallEvalCase("IK14", "意图关键词", "当前合同状态", _ENT_TC, expect_intent="latest_state"),
        ArchiveRecallEvalCase("IK15", "意图关键词", "现在什么阶段", _ENT_BYD, expect_intent="latest_state"),
        ArchiveRecallEvalCase("IK16", "意图关键词", "最终确认了吗", _ENT_HW, expect_intent="latest_state"),
        ArchiveRecallEvalCase("IK17", "意图关键词", "签了吗", _ENT_BYD, expect_intent="latest_state"),
        ArchiveRecallEvalCase("IK18", "意图关键词", "目前进展如何", _ENT_XM, expect_intent="latest_state"),
        # 对比意图
        ArchiveRecallEvalCase("IK19", "意图关键词", "和SAP比怎么样", _ENT_HW, expect_intent="comparison"),
        ArchiveRecallEvalCase("IK20", "意图关键词", "Odoo跟我们差多少", _ENT_PT, expect_intent="comparison"),
        ArchiveRecallEvalCase("IK21", "意图关键词", "竞品哪个更贵", _ENT_PT, expect_intent="comparison"),
        # 时间线意图
        ArchiveRecallEvalCase("IK22", "意图关键词", "从开始到现在全过程", _ENT_PT, expect_intent="timeline"),
        ArchiveRecallEvalCase("IK23", "意图关键词", "第一次接触是什么时候", _ENT_HW, expect_intent="timeline"),
        ArchiveRecallEvalCase("IK24", "意图关键词", "后来发生了什么", _ENT_PT, expect_intent="timeline"),
        ArchiveRecallEvalCase("IK25", "意图关键词", "时间线梳理一下", _ENT_TC, expect_intent="timeline"),
        # 具体数据意图
        ArchiveRecallEvalCase("IK26", "意图关键词", "报价金额具体多少", _ENT_PT, expect_intent="specific_data"),
        ArchiveRecallEvalCase("IK27", "意图关键词", "合同到期日是哪天", _ENT_TC, expect_intent="specific_data"),
        ArchiveRecallEvalCase("IK28", "意图关键词", "折扣比例多少", _ENT_PT, expect_intent="specific_data"),
        ArchiveRecallEvalCase("IK29", "意图关键词", "付款条件怎么分的", _ENT_PT, expect_intent="specific_data"),
        ArchiveRecallEvalCase("IK30", "意图关键词", "实施费用多少钱", _ENT_HW, expect_intent="specific_data"),
        # 否定回忆意图（新增）
        ArchiveRecallEvalCase("IK31", "意图关键词", "之前否了什么方案", _ENT_TC, expect_intent="change_tracking"),
        ArchiveRecallEvalCase("IK32", "意图关键词", "哪些需求被砍了", _ENT_TC, expect_intent="change_tracking"),
        # 汇总/计数意图（新增）
        ArchiveRecallEvalCase("IK33", "意图关键词", "一共花了多少时间", _ENT_HW, expect_intent="specific_data"),
        ArchiveRecallEvalCase("IK34", "意图关键词", "总共跟进了几次", _ENT_HW, expect_intent="timeline"),
        ArchiveRecallEvalCase("IK35", "意图关键词", "这轮谈判谁赢了", _ENT_PT, expect_intent="decision_reason"),
    ]


# ═══════════════════════════════════════════════════════════
# C. 实体精确召回 (30)
# ═══════════════════════════════════════════════════════════

def _entity_recall_cases() -> list[ArchiveRecallEvalCase]:
    return [
        ArchiveRecallEvalCase("ER01", "实体精确", "PT Sentosa 客户信息", _ENT_PT, expect_entity="PT Sentosa", expect_hit_turns=[1]),
        ArchiveRecallEvalCase("ER02", "实体精确", "PT Sentosa 商机", _ENT_PT, expect_entity="PT Sentosa", expect_hit_turns=[2]),
        ArchiveRecallEvalCase("ER03", "实体精确", "PT Sentosa 报价", _ENT_PT, expect_entity="PT Sentosa", expect_hit_turns=[3, 5, 6]),
        ArchiveRecallEvalCase("ER04", "实体精确", "华为科技 客户画像", _ENT_HW, expect_entity="华为科技", expect_hit_turns=[11]),
        ArchiveRecallEvalCase("ER05", "实体精确", "华为科技 BANT", _ENT_HW, expect_entity="华为科技", expect_hit_turns=[12]),
        ArchiveRecallEvalCase("ER06", "实体精确", "华为科技 联系人", _ENT_HW, expect_entity="华为科技", expect_hit_turns=[14]),
        ArchiveRecallEvalCase("ER07", "实体精确", "华为科技 POC", _ENT_HW, expect_entity="华为科技", expect_hit_turns=[15, 16]),
        ArchiveRecallEvalCase("ER08", "实体精确", "华为科技 报价", _ENT_HW, expect_entity="华为科技", expect_hit_turns=[27, 28, 29]),
        ArchiveRecallEvalCase("ER09", "实体精确", "腾讯云 需求", _ENT_TC, expect_entity="腾讯云", expect_hit_turns=[17]),
        ArchiveRecallEvalCase("ER10", "实体精确", "腾讯云 技术方案", _ENT_TC, expect_entity="腾讯云", expect_hit_turns=[18]),
        ArchiveRecallEvalCase("ER11", "实体精确", "腾讯云 报价", _ENT_TC, expect_entity="腾讯云", expect_hit_turns=[19, 20, 21]),
        ArchiveRecallEvalCase("ER12", "实体精确", "比亚迪 客户信息", _ENT_BYD, expect_entity="比亚迪", expect_hit_turns=[22]),
        ArchiveRecallEvalCase("ER13", "实体精确", "比亚迪 商机", _ENT_BYD, expect_entity="比亚迪", expect_hit_turns=[23]),
        ArchiveRecallEvalCase("ER14", "实体精确", "比亚迪 签约", _ENT_BYD, expect_entity="比亚迪", expect_hit_turns=[24]),
        ArchiveRecallEvalCase("ER15", "实体精确", "opp_001 详情", _ENT_PT, expect_hit_turns=[2]),
        ArchiveRecallEvalCase("ER16", "实体精确", "con_005 合同", _ENT_TC, expect_hit_turns=[7, 10]),
        ArchiveRecallEvalCase("ER17", "实体精确", "Q-001 报价单", _ENT_PT, expect_hit_turns=[3, 6]),
        ArchiveRecallEvalCase("ER18", "实体精确", "Q-TC-001 报价", _ENT_TC, expect_hit_turns=[19, 21]),
        ArchiveRecallEvalCase("ER19", "实体精确", "Q-HW-001 报价", _ENT_HW, expect_hit_turns=[29]),
        ArchiveRecallEvalCase("ER20", "实体精确", "POC-HW-001", _ENT_HW, expect_hit_turns=[15, 16]),
        ArchiveRecallEvalCase("ER21", "实体精确", "CON-BYD-001", _ENT_BYD, expect_hit_turns=[24]),
        ArchiveRecallEvalCase("ER22", "实体精确", "opp_BYD_001", _ENT_BYD, expect_hit_turns=[23, 24]),
        ArchiveRecallEvalCase("ER23", "实体精确", "CV XYZ 合同", _ENT_TC, expect_entity="CV XYZ", expect_hit_turns=[7]),
        ArchiveRecallEvalCase("ER24", "实体精确", "CV XYZ 续约", _ENT_TC, expect_entity="CV XYZ", expect_hit_turns=[8, 9, 10]),
        ArchiveRecallEvalCase("ER25", "实体精确", "张总 华为", _ENT_HW, expect_entity="华为科技", expect_hit_turns=[12, 14, 16]),
        ArchiveRecallEvalCase("ER26", "实体精确", "Andi PT Sentosa", _ENT_PT, expect_hit_turns=[2]),
        ArchiveRecallEvalCase("ER27", "实体精确", "pipeline 总览", _ENT_PT, expect_hit_turns=[25]),
        ArchiveRecallEvalCase("ER28", "实体精确", "风险商机列表", _ENT_PT, expect_hit_turns=[26]),
        ArchiveRecallEvalCase("ER29", "实体精确", "REQ-TC-001 API对接", _ENT_TC, expect_hit_turns=[17]),
        ArchiveRecallEvalCase("ER30", "实体精确", "TP-TC-001 技术方案", _ENT_TC, expect_hit_turns=[18]),
    ]


# ═══════════════════════════════════════════════════════════
# D. 工具结果检索 (25)
# ═══════════════════════════════════════════════════════════

def _tool_result_cases() -> list[ArchiveRecallEvalCase]:
    return [
        ArchiveRecallEvalCase("TR01", "工具检索", "上次搜了什么竞品", _ENT_PT, expect_tool="web_search", expect_hit_turns=[4, 13]),
        ArchiveRecallEvalCase("TR02", "工具检索", "网上查的Odoo定价", _ENT_PT, expect_tool="web_search", expect_hit_turns=[4]),
        ArchiveRecallEvalCase("TR03", "工具检索", "SAP搜索结果", _ENT_HW, expect_tool="web_search", expect_hit_turns=[13]),
        ArchiveRecallEvalCase("TR04", "工具检索", "查询客户信息的结果", _ENT_PT, expect_tool="query_data", expect_hit_turns=[1, 11, 22]),
        ArchiveRecallEvalCase("TR05", "工具检索", "商机查询结果", _ENT_PT, expect_tool="query_data", expect_hit_turns=[2, 23]),
        ArchiveRecallEvalCase("TR06", "工具检索", "联系人查到了什么", _ENT_HW, expect_tool="query_data", expect_hit_turns=[14]),
        ArchiveRecallEvalCase("TR07", "工具检索", "合同查询结果", _ENT_TC, expect_tool="query_data", expect_hit_turns=[7]),
        ArchiveRecallEvalCase("TR08", "工具检索", "需求查询返回了什么", _ENT_TC, expect_tool="query_data", expect_hit_turns=[17]),
        ArchiveRecallEvalCase("TR09", "工具检索", "活动记录查询", _ENT_HW, expect_tool="query_data", expect_hit_turns=[27]),
        ArchiveRecallEvalCase("TR10", "工具检索", "BANT分析结果", _ENT_HW, expect_tool="analyze_data", expect_hit_turns=[12]),
        ArchiveRecallEvalCase("TR11", "工具检索", "pipeline分析结论", _ENT_PT, expect_tool="analyze_data", expect_hit_turns=[25]),
        ArchiveRecallEvalCase("TR12", "工具检索", "风险分析结果", _ENT_PT, expect_tool="analyze_data", expect_hit_turns=[26]),
        ArchiveRecallEvalCase("TR13", "工具检索", "续约方案分析", _ENT_TC, expect_tool="analyze_data", expect_hit_turns=[8]),
        ArchiveRecallEvalCase("TR14", "工具检索", "技术方案生成结果", _ENT_TC, expect_tool="analyze_data", expect_hit_turns=[18]),
        ArchiveRecallEvalCase("TR15", "工具检索", "报价生成操作", _ENT_PT, expect_tool="execute_task", expect_hit_turns=[3]),
        ArchiveRecallEvalCase("TR16", "工具检索", "报价更新记录", _ENT_PT, expect_tool="execute_task", expect_hit_turns=[6, 21, 29]),
        ArchiveRecallEvalCase("TR17", "工具检索", "合同更新操作", _ENT_TC, expect_tool="execute_task", expect_hit_turns=[10]),
        ArchiveRecallEvalCase("TR18", "工具检索", "POC规划创建", _ENT_HW, expect_tool="execute_task", expect_hit_turns=[15]),
        ArchiveRecallEvalCase("TR19", "工具检索", "签约成交操作", _ENT_BYD, expect_tool="execute_task", expect_hit_turns=[24]),
        ArchiveRecallEvalCase("TR20", "工具检索", "腾讯报价创建", _ENT_TC, expect_tool="execute_task", expect_hit_turns=[19]),
        ArchiveRecallEvalCase("TR21", "工具检索", "华为报价更新操作", _ENT_HW, expect_tool="execute_task", expect_hit_turns=[29]),
        ArchiveRecallEvalCase("TR22", "工具检索", "所有execute_task执行", _ENT_PT, expect_tool="execute_task"),
        ArchiveRecallEvalCase("TR23", "工具检索", "所有web_search调用", _ENT_PT, expect_tool="web_search"),
        ArchiveRecallEvalCase("TR24", "工具检索", "POC结果查询", _ENT_HW, expect_tool="query_data", expect_hit_turns=[16]),
        ArchiveRecallEvalCase("TR25", "工具检索", "报价单生成analyze_data", _ENT_PT, expect_tool="analyze_data", expect_hit_turns=[3]),
    ]


# ═══════════════════════════════════════════════════════════
# E. 变更追踪 (25)
# ═══════════════════════════════════════════════════════════

def _change_tracking_cases() -> list[ArchiveRecallEvalCase]:
    return [
        ArchiveRecallEvalCase("CT01", "变更追踪", "PT Sentosa报价金额变化", _ENT_PT, expect_hit_turns=[3, 5, 6], expect_intent="change_tracking"),
        ArchiveRecallEvalCase("CT02", "变更追踪", "CV XYZ合同期限变更", _ENT_TC, expect_hit_turns=[7, 10], expect_intent="change_tracking"),
        ArchiveRecallEvalCase("CT03", "变更追踪", "腾讯云报价调整历史", _ENT_TC, expect_hit_turns=[19, 20, 21], expect_intent="change_tracking"),
        ArchiveRecallEvalCase("CT04", "变更追踪", "华为报价从多少降到多少", _ENT_HW, expect_hit_turns=[27, 28, 29], expect_intent="change_tracking"),
        ArchiveRecallEvalCase("CT05", "变更追踪", "$45K后来改成多少", _ENT_PT, expect_hit_turns=[3, 5, 6], expect_keyword_in_result="$45K"),
        ArchiveRecallEvalCase("CT06", "变更追踪", "¥80万最后谈到多少", _ENT_TC, expect_hit_turns=[19, 20, 21], expect_keyword_in_result="80万"),
        ArchiveRecallEvalCase("CT07", "变更追踪", "¥480万为什么降到¥450万", _ENT_HW, expect_hit_turns=[27, 28, 29], expect_intent="decision_reason"),
        ArchiveRecallEvalCase("CT08", "变更追踪", "合同期限怎么变的", _ENT_TC, expect_hit_turns=[7, 10], expect_intent="change_tracking"),
        ArchiveRecallEvalCase("CT09", "变更追踪", "实施周期从12周改到8周", _ENT_HW, expect_hit_turns=[28, 29], expect_intent="change_tracking"),
        ArchiveRecallEvalCase("CT10", "变更追踪", "腾讯方案砍了哪些功能", _ENT_TC, expect_hit_turns=[20, 21]),
        ArchiveRecallEvalCase("CT11", "变更追踪", "¥450万是怎么定下来的", _ENT_HW, expect_hit_turns=[28, 29], expect_intent="decision_reason"),
        ArchiveRecallEvalCase("CT12", "变更追踪", "$40K谁同意的", _ENT_PT, expect_hit_turns=[5, 6], expect_intent="decision_reason"),
        ArchiveRecallEvalCase("CT13", "变更追踪", "CV XYZ最终选了哪个方案", _ENT_TC, expect_hit_turns=[9, 10]),
        ArchiveRecallEvalCase("CT14", "变更追踪", "GraphQL保留了吗", _ENT_TC, expect_hit_turns=[21]),
        ArchiveRecallEvalCase("CT15", "变更追踪", "日志审计最后怎么处理", _ENT_TC, expect_hit_turns=[21]),
        ArchiveRecallEvalCase("CT16", "变更追踪", "比亚迪成交价和最初一样吗", _ENT_BYD, expect_hit_turns=[23, 24]),
        ArchiveRecallEvalCase("CT17", "变更追踪", "PT Sentosa付款条件改没", _ENT_PT, expect_hit_turns=[3, 6]),
        ArchiveRecallEvalCase("CT18", "变更追踪", "华为POC范围有调整吗", _ENT_HW, expect_hit_turns=[15, 16]),
        ArchiveRecallEvalCase("CT19", "变更追踪", "Q-001金额变更记录", _ENT_PT, expect_hit_turns=[3, 6], expect_keyword_in_result="Q-001"),
        ArchiveRecallEvalCase("CT20", "变更追踪", "con_005到期日变了吗", _ENT_TC, expect_hit_turns=[7, 10], expect_keyword_in_result="con_005"),
        ArchiveRecallEvalCase("CT21", "变更追踪", "续约不涨价的原因", _ENT_TC, expect_hit_turns=[8, 9, 10], expect_intent="decision_reason"),
        ArchiveRecallEvalCase("CT22", "变更追踪", "SLA升级为什么被砍", _ENT_TC, expect_hit_turns=[8, 9]),
        ArchiveRecallEvalCase("CT23", "变更追踪", "¥60万方案缺什么功能", _ENT_TC, expect_hit_turns=[20]),
        ArchiveRecallEvalCase("CT24", "变更追踪", "为什么选里程碑付款", _ENT_TC, expect_hit_turns=[19], expect_intent="decision_reason"),
        ArchiveRecallEvalCase("CT25", "变更追踪", "比亚迪全款付的原因", _ENT_BYD, expect_hit_turns=[24], expect_intent="decision_reason"),
    ]


# ═══════════════════════════════════════════════════════════
# F. 模糊语义 (25)
# ═══════════════════════════════════════════════════════════

def _fuzzy_semantic_cases() -> list[ArchiveRecallEvalCase]:
    return [
        ArchiveRecallEvalCase("FS01", "模糊语义", "制造业客户有哪些", _ENT_PT, expect_hit_turns=[1, 22]),
        ArchiveRecallEvalCase("FS02", "模糊语义", "年费二十万的合同", _ENT_TC, expect_hit_turns=[7, 8, 9, 10]),
        ArchiveRecallEvalCase("FS03", "模糊语义", "已签约的商机", _ENT_BYD, expect_hit_turns=[24]),
        ArchiveRecallEvalCase("FS04", "模糊语义", "本月成交了多少", _ENT_BYD, expect_hit_turns=[24, 25]),
        ArchiveRecallEvalCase("FS05", "模糊语义", "涨价方案", _ENT_TC, expect_hit_turns=[8]),
        ArchiveRecallEvalCase("FS06", "模糊语义", "API接口需求", _ENT_TC, expect_hit_turns=[17]),
        ArchiveRecallEvalCase("FS07", "模糊语义", "多租户架构", _ENT_TC, expect_hit_turns=[17, 18]),
        ArchiveRecallEvalCase("FS08", "模糊语义", "ERP替换项目", _ENT_HW, expect_hit_turns=[12]),
        ArchiveRecallEvalCase("FS09", "模糊语义", "供应链管理模块", _ENT_BYD, expect_hit_turns=[23]),
        ArchiveRecallEvalCase("FS10", "模糊语义", "折扣优惠", _ENT_PT, expect_hit_turns=[3, 6]),
        ArchiveRecallEvalCase("FS11", "模糊语义", "付款条件", _ENT_PT, expect_hit_turns=[3, 6, 19]),
        ArchiveRecallEvalCase("FS12", "模糊语义", "里程碑付款", _ENT_TC, expect_hit_turns=[19]),
        ArchiveRecallEvalCase("FS13", "模糊语义", "实施周期", _ENT_HW, expect_hit_turns=[3, 15, 29]),
        ArchiveRecallEvalCase("FS14", "模糊语义", "免费技术支持", _ENT_PT, expect_hit_turns=[3]),
        ArchiveRecallEvalCase("FS15", "模糊语义", "竞品对比", _ENT_PT, expect_hit_turns=[4, 13]),
        ArchiveRecallEvalCase("FS16", "模糊语义", "SAP报价多少", _ENT_HW, expect_hit_turns=[13]),
        ArchiveRecallEvalCase("FS17", "模糊语义", "Odoo多少钱", _ENT_PT, expect_hit_turns=[4]),
        ArchiveRecallEvalCase("FS18", "模糊语义", "哪些客户砍过价", _ENT_PT, expect_hit_turns=[5, 9, 20, 28]),
        ArchiveRecallEvalCase("FS19", "模糊语义", "审批流相关", _ENT_HW, expect_hit_turns=[15]),
        ArchiveRecallEvalCase("FS20", "模糊语义", "S级大客户", _ENT_HW, expect_hit_turns=[11]),
        ArchiveRecallEvalCase("FS21", "模糊语义", "做POC的客户", _ENT_HW, expect_hit_turns=[15, 16]),
        ArchiveRecallEvalCase("FS22", "模糊语义", "还在谈判的", _ENT_BYD, expect_hit_turns=[23]),
        ArchiveRecallEvalCase("FS23", "模糊语义", "Salesforce竞争", _ENT_TC, expect_hit_turns=[8]),
        ArchiveRecallEvalCase("FS24", "模糊语义", "VP级决策者", _ENT_HW, expect_hit_turns=[12, 14]),
        ArchiveRecallEvalCase("FS25", "模糊语义", "本周客户互动", _ENT_HW, expect_hit_turns=[27]),
    ]


# ═══════════════════════════════════════════════════════════
# G. 负例验证 (20)
# ═══════════════════════════════════════════════════════════

def _negative_cases() -> list[ArchiveRecallEvalCase]:
    return [
        ArchiveRecallEvalCase("NE01", "负例", "Amazon的客户信息", _ENT_PT, expect_no_hit=True),
        ArchiveRecallEvalCase("NE02", "负例", "Microsoft Teams集成", _ENT_PT, expect_no_hit=True),
        ArchiveRecallEvalCase("NE03", "负例", "阿里巴巴的商机", _ENT_PT, expect_no_hit=True),
        ArchiveRecallEvalCase("NE04", "负例", "Slack渠道配置", _ENT_PT, expect_no_hit=True),
        ArchiveRecallEvalCase("NE05", "负例", "京东物流合同", _ENT_PT, expect_no_hit=True),
        ArchiveRecallEvalCase("NE06", "负例", "Kubernetes部署方案", _ENT_PT, expect_no_hit=True),
        ArchiveRecallEvalCase("NE07", "负例", "AWS Lambda费用", _ENT_PT, expect_no_hit=True),
        ArchiveRecallEvalCase("NE08", "负例", "字节跳动广告", _ENT_PT, expect_no_hit=True),
        ArchiveRecallEvalCase("NE09", "负例", "opp_999不存在的商机", _ENT_PT, expect_no_hit=True),
        ArchiveRecallEvalCase("NE10", "负例", "CON-FAKE-001假合同", _ENT_PT, expect_no_hit=True),
        ArchiveRecallEvalCase("NE11", "负例", "2024年Q1数据", _ENT_PT, expect_no_hit=True),
        ArchiveRecallEvalCase("NE12", "负例", "招聘Java工程师", _ENT_PT, expect_no_hit=True),
        ArchiveRecallEvalCase("NE13", "负例", "公司年会策划", _ENT_PT, expect_no_hit=True),
        ArchiveRecallEvalCase("NE14", "负例", "小红书营销", _ENT_PT, expect_no_hit=True),
        ArchiveRecallEvalCase("NE15", "负例", "特斯拉自动驾驶", _ENT_PT, expect_no_hit=True),
        ArchiveRecallEvalCase("NE16", "负例", "GPT-5发布时间", _ENT_PT, expect_no_hit=True),
        ArchiveRecallEvalCase("NE17", "负例", "NBA季后赛", _ENT_PT, expect_no_hit=True),
        ArchiveRecallEvalCase("NE18", "负例", "iPhone16价格", _ENT_PT, expect_no_hit=True),
        ArchiveRecallEvalCase("NE19", "负例", "Python3.13新特性", _ENT_PT, expect_no_hit=True),
        ArchiveRecallEvalCase("NE20", "负例", "Docker Compose配置", _ENT_PT, expect_no_hit=True),
    ]


# ═══════════════════════════════════════════════════════════
# H. 跨任务 (15)
# ═══════════════════════════════════════════════════════════

def _cross_task_cases() -> list[ArchiveRecallEvalCase]:
    return [
        ArchiveRecallEvalCase("XT01", "跨任务", "所有报价超过¥100万的客户", _ENT_PT, expect_hit_turns=[23, 27, 28, 29]),
        ArchiveRecallEvalCase("XT02", "跨任务", "所有使用web_search的场景", _ENT_PT, expect_tool="web_search", expect_hit_turns=[4, 13]),
        ArchiveRecallEvalCase("XT03", "跨任务", "更新过报价的客户", _ENT_PT, expect_tool="execute_task", expect_hit_turns=[6, 21, 29]),
        ArchiveRecallEvalCase("XT04", "跨任务", "成交金额最大的", _ENT_BYD, expect_hit_turns=[24]),
        ArchiveRecallEvalCase("XT05", "跨任务", "有竞品威胁的客户", _ENT_PT, expect_hit_turns=[4, 8, 13, 26]),
        ArchiveRecallEvalCase("XT06", "跨任务", "所有P0需求", _ENT_TC, expect_hit_turns=[17]),
        ArchiveRecallEvalCase("XT07", "跨任务", "所有已确认报价", _ENT_PT, expect_hit_turns=[6, 21, 29]),
        ArchiveRecallEvalCase("XT08", "跨任务", "涉及砍价的轮次", _ENT_PT, expect_hit_turns=[5, 9, 20, 28]),
        ArchiveRecallEvalCase("XT09", "跨任务", "所有合同相关操作", _ENT_TC, expect_hit_turns=[7, 8, 9, 10, 24]),
        ArchiveRecallEvalCase("XT10", "跨任务", "本月forecast", _ENT_PT, expect_hit_turns=[25]),
        ArchiveRecallEvalCase("XT11", "跨任务", "涉及技术评估的客户", _ENT_HW, expect_hit_turns=[14, 16, 17, 18]),
        ArchiveRecallEvalCase("XT12", "跨任务", "所有周报总结", _ENT_PT, expect_hit_turns=[25, 30]),
        ArchiveRecallEvalCase("XT13", "跨任务", "negotiation阶段商机", _ENT_BYD, expect_hit_turns=[23]),
        ArchiveRecallEvalCase("XT14", "跨任务", "3年长期合同", _ENT_TC, expect_hit_turns=[10]),
        ArchiveRecallEvalCase("XT15", "跨任务", "自动续约相关", _ENT_TC, expect_hit_turns=[7]),
        # 新增: 时间窗口过滤跨任务
        ArchiveRecallEvalCase("XT16", "跨任务", "本周华为所有操作", _ENT_HW, expect_hit_turns=[27, 28, 29]),
        ArchiveRecallEvalCase("XT17", "跨任务", "最近3轮做了什么", _ENT_PT, expect_hit_turns=[28, 29, 30]),
        ArchiveRecallEvalCase("XT18", "跨任务", "上周所有砍价谈判", _ENT_PT, expect_hit_turns=[5, 9, 20, 28]),
        ArchiveRecallEvalCase("XT19", "跨任务", "涉及¥100万以上的所有客户", _ENT_PT, expect_hit_turns=[23, 24, 27, 28, 29]),
        ArchiveRecallEvalCase("XT20", "跨任务", "还没签约的客户进展", _ENT_PT, expect_hit_turns=[2, 23, 25, 26]),
    ]


# ═══════════════════════════════════════════════════════════
# I. 多轮同工具重复调用区分 (20)
# ═══════════════════════════════════════════════════════════

def _multi_tool_distinction_cases() -> list[ArchiveRecallEvalCase]:
    """I. 多轮同工具重复调用区分 (20)

    核心场景: 同一工具在对话中被调用多次，验证能按实体/业务对象/时间精确定位目标轮次。
    种子数据中:
      - query_data 出现 10 次 (turn 1,2,7,11,14,16,17,22,23,27)
      - execute_task 出现 7 次 (turn 6,10,15,19,21,24,29)
      - analyze_data 出现 5 次 (turn 3,8,12,18,25)
      - web_search 出现 2 次 (turn 4,13)
    """
    return [
        # === query_data 按客户名区分 (3条) ===
        ArchiveRecallEvalCase(
            "MT01", "多工具区分", "查PT Sentosa时返回了什么", _ENT_PT,
            expect_tool="query_data", expect_hit_turns=[1, 2],
            description="query_data×10, 按客户名→PT的2次"),
        ArchiveRecallEvalCase(
            "MT02", "多工具区分", "查华为时得到了什么信息", _ENT_HW,
            expect_tool="query_data", expect_hit_turns=[11, 14, 16, 27],
            description="query_data×10, 按客户名→华为的4次"),
        ArchiveRecallEvalCase(
            "MT03", "多工具区分", "腾讯云的查询结果", _ENT_TC,
            expect_tool="query_data", expect_hit_turns=[7, 17],
            description="query_data×10, 按客户名→腾讯的2次"),

        # === query_data 按业务对象区分 (5条) ===
        ArchiveRecallEvalCase(
            "MT04", "多工具区分", "商机查询结果是什么", _ENT_PT,
            expect_tool="query_data", expect_hit_turns=[2, 23],
            description="query_data×10, 按业务对象'商机'→2条"),
        ArchiveRecallEvalCase(
            "MT05", "多工具区分", "联系人的查询结果", _ENT_HW,
            expect_tool="query_data", expect_hit_turns=[14],
            description="query_data×10, 按业务对象'联系人'→仅1次"),
        ArchiveRecallEvalCase(
            "MT06", "多工具区分", "合同查询返回了什么", _ENT_TC,
            expect_tool="query_data", expect_hit_turns=[7],
            description="query_data×10, 按业务对象'合同'→CV XYZ"),
        ArchiveRecallEvalCase(
            "MT07", "多工具区分", "需求查到了什么", _ENT_TC,
            expect_tool="query_data", expect_hit_turns=[17],
            description="query_data×10, 按业务对象'需求'→腾讯需求"),
        ArchiveRecallEvalCase(
            "MT08", "多工具区分", "活动记录查了什么", _ENT_HW,
            expect_tool="query_data", expect_hit_turns=[27],
            description="query_data×10, 按业务对象'活动'→华为互动"),

        # === query_data 按时间区分 (2条) ===
        ArchiveRecallEvalCase(
            "MT09", "多工具区分", "最近一次查数据是什么", _ENT_HW,
            expect_tool="query_data", expect_hit_turns=[27],
            description="query_data×10, 按时间'最近'→最后1次(turn27)"),
        ArchiveRecallEvalCase(
            "MT10", "多工具区分", "第一次查客户信息得到什么", _ENT_PT,
            expect_tool="query_data", expect_hit_turns=[1],
            description="query_data×10, 按时间'第一次'→最早(turn1)"),

        # === execute_task 按动作类型区分 (4条) ===
        ArchiveRecallEvalCase(
            "MT11", "多工具区分", "报价创建操作", _ENT_TC,
            expect_tool="execute_task", expect_hit_turns=[19],
            description="execute_task×7, 按'创建'→首次报价生成"),
        ArchiveRecallEvalCase(
            "MT12", "多工具区分", "报价更新了几次", _ENT_PT,
            expect_tool="execute_task", expect_hit_turns=[6, 21, 29],
            description="execute_task×7, 按'更新'→所有更新轮次"),
        ArchiveRecallEvalCase(
            "MT13", "多工具区分", "签约成交那次操作", _ENT_BYD,
            expect_tool="execute_task", expect_hit_turns=[24],
            description="execute_task×7, 按'签约'→仅比亚迪"),
        ArchiveRecallEvalCase(
            "MT14", "多工具区分", "最后一次execute_task做了什么", _ENT_HW,
            expect_tool="execute_task", expect_hit_turns=[29],
            description="execute_task×7, 按时间'最后'→turn29"),

        # === execute_task 按客户区分 (2条) ===
        ArchiveRecallEvalCase(
            "MT15", "多工具区分", "腾讯的执行操作有几次", _ENT_TC,
            expect_tool="execute_task", expect_hit_turns=[10, 19, 21],
            description="execute_task×7, 按客户→腾讯3次"),
        ArchiveRecallEvalCase(
            "MT16", "多工具区分", "华为做了什么执行操作", _ENT_HW,
            expect_tool="execute_task", expect_hit_turns=[15, 29],
            description="execute_task×7, 按客户→华为2次(POC规划+报价更新)"),

        # === analyze_data 区分 (2条) ===
        ArchiveRecallEvalCase(
            "MT17", "多工具区分", "BANT分析是什么时候做的", _ENT_HW,
            expect_tool="analyze_data", expect_hit_turns=[12],
            description="analyze_data×5, 按分析类型'BANT'→1次"),
        ArchiveRecallEvalCase(
            "MT18", "多工具区分", "续约方案的分析结果", _ENT_TC,
            expect_tool="analyze_data", expect_hit_turns=[8],
            description="analyze_data×5, 按业务场景'续约'→1次"),

        # === web_search 区分 (2条) ===
        ArchiveRecallEvalCase(
            "MT19", "多工具区分", "搜Odoo那次结果", _ENT_PT,
            expect_tool="web_search", expect_hit_turns=[4],
            description="web_search×2, 按竞品名'Odoo'→turn4"),
        ArchiveRecallEvalCase(
            "MT20", "多工具区分", "搜SAP定价那次", _ENT_HW,
            expect_tool="web_search", expect_hit_turns=[13],
            description="web_search×2, 按竞品名'SAP'→turn13"),
    ]


# ═══════════════════════════════════════════════════════════
# J. 时序条件过滤 (10)
# ═══════════════════════════════════════════════════════════

def _temporal_filter_cases() -> list[ArchiveRecallEvalCase]:
    """J. 时序条件过滤 (10)

    验证"第一次/最后一次/最近/上次"等时序修饰对检索结果排序的影响。
    注意: 纯 VDB hybrid_search 不直接支持时序过滤，
    需要配合 ContextArchiveService 的时间线排序实现。
    """
    return [
        # 最近/最后
        ArchiveRecallEvalCase(
            "TF01", "时序过滤", "最近一次和华为的互动", _ENT_HW,
            expect_hit_turns=[27, 28, 29], expect_intent="latest_state",
            description="取华为最近的轮次"),
        ArchiveRecallEvalCase(
            "TF02", "时序过滤", "上次跟腾讯云谈的什么", _ENT_TC,
            expect_hit_turns=[20, 21], expect_intent="latest_state",
            description="取腾讯最后的交互"),
        ArchiveRecallEvalCase(
            "TF03", "时序过滤", "最后确认的报价是什么", _ENT_PT,
            expect_hit_turns=[6, 21, 29], expect_intent="latest_state",
            description="取所有确认报价中最新的"),
        # 第一次/最早
        ArchiveRecallEvalCase(
            "TF04", "时序过滤", "第一次接触PT Sentosa是什么时候", _ENT_PT,
            expect_hit_turns=[1], expect_intent="timeline",
            description="第一次接触→最早的轮次"),
        ArchiveRecallEvalCase(
            "TF05", "时序过滤", "最早提出报价是哪次", _ENT_PT,
            expect_hit_turns=[3], expect_intent="timeline",
            description="最早报价→turn3"),
        # 区间
        ArchiveRecallEvalCase(
            "TF06", "时序过滤", "华为POC前后发生了什么", _ENT_HW,
            expect_hit_turns=[14, 15, 16], expect_intent="timeline",
            description="POC前后→turn14-16"),
        ArchiveRecallEvalCase(
            "TF07", "时序过滤", "腾讯砍价之后做了什么", _ENT_TC,
            expect_hit_turns=[20, 21],
            description="砍价之后→turn20后的轮次"),
        # 次数/频率
        ArchiveRecallEvalCase(
            "TF08", "时序过滤", "跟PT Sentosa总共互动了几轮", _ENT_PT,
            expect_hit_turns=[1, 2, 3, 4, 5, 6], expect_intent="timeline",
            description="总共互动→PT相关的所有轮次"),
        ArchiveRecallEvalCase(
            "TF09", "时序过滤", "比亚迪从接触到签约用了几轮", _ENT_BYD,
            expect_hit_turns=[22, 23, 24], expect_intent="timeline",
            description="接触到签约→turn22-24"),
        ArchiveRecallEvalCase(
            "TF10", "时序过滤", "华为报价谈判持续了多久", _ENT_HW,
            expect_hit_turns=[27, 28, 29], expect_intent="timeline",
            description="报价谈判→turn27-29"),
    ]


# ═══════════════════════════════════════════════════════════
# K. 边界负例验证 (10)
# ═══════════════════════════════════════════════════════════

def _boundary_negative_cases() -> list[ArchiveRecallEvalCase]:
    """K. 边界负例 (10)

    相似但不存在的查询 — 考验 embedding 和 BM25 的边界区分能力。
    与 G 类"完全不相关负例"的区别:
      - G 类: Amazon/Kubernetes（完全无关实体）
      - K 类: 客户存在但业务/事件/ID不存在（容易误判的边界 case）
    """
    return [
        # 客户存在但业务对象不存在
        ArchiveRecallEvalCase(
            "BN01", "边界负例", "华为科技的HR系统项目", _ENT_HW,
            expect_no_hit=True,
            description="华为存在但HR系统不存在"),
        ArchiveRecallEvalCase(
            "BN02", "边界负例", "腾讯云的自动驾驶项目", _ENT_TC,
            expect_no_hit=True,
            description="腾讯存在但自动驾驶不存在"),
        ArchiveRecallEvalCase(
            "BN03", "边界负例", "比亚迪的AI芯片报价", _ENT_BYD,
            expect_no_hit=True,
            description="比亚迪存在但AI芯片不存在"),
        ArchiveRecallEvalCase(
            "BN04", "边界负例", "PT Sentosa员工培训计划", _ENT_PT,
            expect_no_hit=True,
            description="PT存在但培训计划不存在"),
        # 联系人存在但信息不存在
        ArchiveRecallEvalCase(
            "BN05", "边界负例", "华为张总的生日是哪天", _ENT_HW,
            expect_no_hit=True,
            description="张总存在但生日信息不存在"),
        ArchiveRecallEvalCase(
            "BN06", "边界负例", "PT Sentosa Andi的学历", _ENT_PT,
            expect_no_hit=True,
            description="Andi存在但学历不存在"),
        # 相似ID但不存在
        ArchiveRecallEvalCase(
            "BN07", "边界负例", "Q-002报价单详情", _ENT_PT,
            expect_no_hit=True,
            description="Q-001存在但Q-002不存在"),
        ArchiveRecallEvalCase(
            "BN08", "边界负例", "opp_002商机进展", _ENT_PT,
            expect_no_hit=True,
            description="opp_001存在但opp_002不存在"),
        # 时间段不存在
        ArchiveRecallEvalCase(
            "BN09", "边界负例", "腾讯云去年的合同情况", _ENT_TC,
            expect_no_hit=True,
            description="合同存在但'去年'时段不存在"),
        # 事件不存在
        ArchiveRecallEvalCase(
            "BN10", "边界负例", "比亚迪第二次POC结果", _ENT_BYD,
            expect_no_hit=True,
            description="比亚迪存在但没做过POC"),
    ]
