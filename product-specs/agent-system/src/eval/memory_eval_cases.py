"""长期记忆召回率评测用例集

覆盖 200+ 条评测用例，分布如下：
  - 精确实体召回: 40 条
  - 模糊语义召回: 30 条
  - 时间相关召回: 20 条
  - 跨类别召回: 20 条
  - 更新覆盖验证: 20 条
  - 冲突消解验证: 15 条
  - 长尾衰减验证: 15 条
  - 负例验证: 20 条
  - 多维度综合: 20 条

对齐 agent-system 现有 200 场景检索用例模式。
"""
from __future__ import annotations

from .memory_eval_runner import MemoryEvalCase, EvalLayer, QueryType


def build_all_cases() -> list[MemoryEvalCase]:
    """构建完整评测用例集（检索召回 200 + 四维度提取 250 = 450 条）"""
    cases = []
    # ── 检索召回评测（200 条）──
    cases.extend(_exact_entity_cases())
    cases.extend(_fuzzy_semantic_cases())
    cases.extend(_time_related_cases())
    cases.extend(_cross_category_cases())
    cases.extend(_update_override_cases())
    cases.extend(_conflict_resolve_cases())
    cases.extend(_long_tail_decay_cases())
    cases.extend(_negative_cases())
    cases.extend(_multi_dimension_cases())
    # ── 四维度记忆提取评测（250 条）──
    from .memory_extract_eval_cases import build_extract_cases
    cases.extend(build_extract_cases())

    # ── 自动补全 expected_category ──
    # 对检索用例，根据 expected_memories 匹配种子数据的 category
    _auto_fill_expected_category(cases)

    return cases


def _auto_fill_expected_category(cases: list[MemoryEvalCase]) -> None:
    """根据种子数据自动填充检索用例的 expected_category

    逻辑：expected_memories 中的关键词匹配种子数据的 merge_key，
    取匹配到的种子记忆的 category 作为 expected_category。
    仅对未设置 expected_category 的检索类用例生效。

    跳过条件：
    - 跨类别用例（cross_category）— 本身就是验证跨维度召回
    - 多维度用例（multi_dimension）— 期望召回多个不同维度
    - 期望记忆对应多个不同 category — 无法用单一值描述
    """
    from .memory_eval_runner import SEED_MEMORIES, EvalLayer, QueryType

    # 建立 merge_key → category 索引
    seed_cat_index: dict[str, str] = {}
    for m in SEED_MEMORIES:
        seed_cat_index[m["merge_key"]] = m.get("category", "")

    # 跳过跨维度类型
    skip_types = {QueryType.CROSS_CATEGORY, QueryType.MULTI_DIMENSION}

    for case in cases:
        # 只处理检索类、且未设置 expected_category 的用例
        if case.layer == EvalLayer.EXTRACT:
            continue
        if case.expected_category:
            continue
        if not case.expected_memories:
            continue
        if case.query_type in skip_types:
            continue

        # 匹配所有命中种子记忆的 category
        matched_cats = set()
        first_cat = ""
        for kw in case.expected_memories:
            for mk, cat in seed_cat_index.items():
                if kw.lower() in mk.lower():
                    matched_cats.add(cat)
                    if not first_cat:
                        first_cat = cat
                    break

        # 只有当所有期望记忆属于同一个 category 时才填充
        if len(matched_cats) == 1:
            case.expected_category = first_cat


# ═══════════════════════════════════════════════════════════
# 一、精确实体召回（40 条）
# ═══════════════════════════════════════════════════════════

def _exact_entity_cases() -> list[MemoryEvalCase]:
    return [
        MemoryEvalCase(
            id="exact_01", layer=EvalLayer.RETRIEVAL, query_type=QueryType.EXACT_ENTITY,
            query="华为张伟是什么样的人",
            description="精确人名查询 — 张伟",
            expected_memories=["华为_张伟"],
            expected_parent_entity="华为",
        ),
        MemoryEvalCase(
            id="exact_02", layer=EvalLayer.RETRIEVAL, query_type=QueryType.EXACT_ENTITY,
            query="华为李娜好打交道吗",
            description="精确人名查询 — 李娜",
            expected_memories=["华为_李娜"],
            expected_parent_entity="华为",
        ),
        MemoryEvalCase(
            id="exact_03", layer=EvalLayer.RETRIEVAL, query_type=QueryType.EXACT_ENTITY,
            query="腾讯王强喜欢什么形式的汇报",
            description="精确人名查询 — 王强",
            expected_memories=["腾讯_王强"],
            expected_parent_entity="腾讯",
        ),
        MemoryEvalCase(
            id="exact_04", layer=EvalLayer.RETRIEVAL, query_type=QueryType.EXACT_ENTITY,
            query="招行陈刚最关注什么",
            description="精确人名查询 — 陈刚",
            expected_memories=["招行_陈刚"],
            expected_parent_entity="招行",
        ),
        MemoryEvalCase(
            id="exact_05", layer=EvalLayer.RETRIEVAL, query_type=QueryType.EXACT_ENTITY,
            query="比亚迪赵敏的社交偏好是什么",
            description="精确人名查询 — 赵敏",
            expected_memories=["比亚迪_赵敏"],
            expected_parent_entity="比亚迪",
        ),
        MemoryEvalCase(
            id="exact_06", layer=EvalLayer.RETRIEVAL, query_type=QueryType.EXACT_ENTITY,
            query="小米林总是什么风格",
            description="精确人名查询 — 林总",
            expected_memories=["小米_林总"],
            expected_parent_entity="小米",
        ),
        MemoryEvalCase(
            id="exact_07", layer=EvalLayer.RETRIEVAL, query_type=QueryType.EXACT_ENTITY,
            query="字节孙丽做事风格怎么样",
            description="精确人名查询 — 孙丽",
            expected_memories=["字节_孙丽"],
            expected_parent_entity="字节",
        ),
        MemoryEvalCase(
            id="exact_08", layer=EvalLayer.RETRIEVAL, query_type=QueryType.EXACT_ENTITY,
            query="华为ERP项目现在什么情况",
            description="精确项目查询 — 华为ERP",
            expected_memories=["华为_ERP"],
            expected_parent_entity="华为",
        ),
        MemoryEvalCase(
            id="exact_09", layer=EvalLayer.RETRIEVAL, query_type=QueryType.EXACT_ENTITY,
            query="腾讯数据中台项目进展怎么样",
            description="精确项目查询 — 腾讯数据中台",
            expected_memories=["腾讯_数据中台"],
            expected_parent_entity="腾讯",
        ),
        MemoryEvalCase(
            id="exact_10", layer=EvalLayer.RETRIEVAL, query_type=QueryType.EXACT_ENTITY,
            query="招行风控平台到哪一步了",
            description="精确项目查询 — 招行风控",
            expected_memories=["招行_风控"],
            expected_parent_entity="招行",
        ),
        MemoryEvalCase(
            id="exact_11", layer=EvalLayer.RETRIEVAL, query_type=QueryType.EXACT_ENTITY,
            query="比亚迪MES项目还在推进吗",
            description="精确项目查询 — 比亚迪MES",
            expected_memories=["比亚迪_MES"],
            expected_parent_entity="比亚迪",
        ),
        MemoryEvalCase(
            id="exact_12", layer=EvalLayer.RETRIEVAL, query_type=QueryType.EXACT_ENTITY,
            query="小米IoT平台项目什么阶段",
            description="精确项目查询 — 小米IoT",
            expected_memories=["小米_IoT"],
            expected_parent_entity="小米",
        ),
        MemoryEvalCase(
            id="exact_13", layer=EvalLayer.RETRIEVAL, query_type=QueryType.EXACT_ENTITY,
            query="字节广告平台项目竞争对手是谁",
            description="精确项目查询 — 字节广告平台",
            expected_memories=["字节_广告平台"],
            expected_parent_entity="字节",
        ),
        MemoryEvalCase(
            id="exact_14", layer=EvalLayer.RETRIEVAL, query_type=QueryType.EXACT_ENTITY,
            query="华为安全审计项目什么时候签约",
            description="精确项目查询 — 华为安全审计",
            expected_memories=["华为_安全审计"],
            expected_parent_entity="华为",
        ),
        MemoryEvalCase(
            id="exact_15", layer=EvalLayer.RETRIEVAL, query_type=QueryType.EXACT_ENTITY,
            query="腾讯AI平台项目预算多少",
            description="精确项目查询 — 腾讯AI平台",
            expected_memories=["腾讯_AI平台"],
            expected_parent_entity="腾讯",
        ),
        MemoryEvalCase(
            id="exact_16", layer=EvalLayer.RETRIEVAL, query_type=QueryType.EXACT_ENTITY,
            query="给华为报价要注意什么",
            description="精确策略查询 — 华为报价",
            expected_memories=["华为_报价"],
            expected_parent_entity="华为",
        ),
        MemoryEvalCase(
            id="exact_17", layer=EvalLayer.RETRIEVAL, query_type=QueryType.EXACT_ENTITY,
            query="腾讯对价格敏感吗",
            description="精确策略查询 — 腾讯报价",
            expected_memories=["腾讯_报价"],
            expected_parent_entity="腾讯",
        ),
        MemoryEvalCase(
            id="exact_18", layer=EvalLayer.RETRIEVAL, query_type=QueryType.EXACT_ENTITY,
            query="招行有什么合规要求",
            description="精确策略查询 — 招行合规",
            expected_memories=["招行_合规"],
            expected_parent_entity="招行",
        ),
        MemoryEvalCase(
            id="exact_19", layer=EvalLayer.RETRIEVAL, query_type=QueryType.EXACT_ENTITY,
            query="华为的采购流程是怎样的",
            description="精确流程查询 — 华为采购",
            expected_memories=["华为_采购流程"],
            expected_parent_entity="华为",
        ),
        MemoryEvalCase(
            id="exact_20", layer=EvalLayer.RETRIEVAL, query_type=QueryType.EXACT_ENTITY,
            query="比亚迪的决策流程是什么样的",
            description="精确流程查询 — 比亚迪决策链",
            expected_memories=["比亚迪_决策链"],
            expected_parent_entity="比亚迪",
        ),
        MemoryEvalCase(
            id="exact_21", layer=EvalLayer.RETRIEVAL, query_type=QueryType.EXACT_ENTITY,
            query="华为CRM部署项目谁负责",
            description="精确项目查询 — 华为CRM",
            expected_memories=["华为_CRM"],
            expected_parent_entity="华为",
        ),
        MemoryEvalCase(
            id="exact_22", layer=EvalLayer.RETRIEVAL, query_type=QueryType.EXACT_ENTITY,
            query="小米智能工厂项目谁在推动",
            description="精确项目查询 — 小米智能工厂",
            expected_memories=["小米_智能工厂"],
            expected_parent_entity="小米",
        ),
        MemoryEvalCase(
            id="exact_23", layer=EvalLayer.RETRIEVAL, query_type=QueryType.EXACT_ENTITY,
            query="招行刘总是什么级别的",
            description="精确人名查询 — 招行刘总",
            expected_memories=["招行_刘总"],
            expected_parent_entity="招行",
        ),
        MemoryEvalCase(
            id="exact_24", layer=EvalLayer.RETRIEVAL, query_type=QueryType.EXACT_ENTITY,
            query="腾讯赵经理负责什么",
            description="精确人名查询 — 腾讯赵经理",
            expected_memories=["腾讯_赵经理"],
            expected_parent_entity="腾讯",
        ),
        MemoryEvalCase(
            id="exact_25", layer=EvalLayer.RETRIEVAL, query_type=QueryType.EXACT_ENTITY,
            query="腾讯POC结果怎么样",
            description="精确事件查询 — 腾讯POC",
            expected_memories=["腾讯_POC"],
            expected_parent_entity="腾讯",
        ),
        MemoryEvalCase(
            id="exact_26", layer=EvalLayer.RETRIEVAL, query_type=QueryType.EXACT_ENTITY,
            query="招行数据迁移方案准备好了吗",
            description="精确事件查询 — 招行数据迁移",
            expected_memories=["招行_数据迁移"],
            expected_parent_entity="招行",
        ),
        MemoryEvalCase(
            id="exact_27", layer=EvalLayer.RETRIEVAL, query_type=QueryType.EXACT_ENTITY,
            query="比亚迪工厂部署方案是什么",
            description="精确事件查询 — 比亚迪工厂部署",
            expected_memories=["比亚迪_工厂部署"],
            expected_parent_entity="比亚迪",
        ),
        MemoryEvalCase(
            id="exact_28", layer=EvalLayer.RETRIEVAL, query_type=QueryType.EXACT_ENTITY,
            query="字节法务审核严格吗",
            description="精确策略查询 — 字节合同法务",
            expected_memories=["字节_合同法务"],
            expected_parent_entity="字节",
        ),
        MemoryEvalCase(
            id="exact_29", layer=EvalLayer.RETRIEVAL, query_type=QueryType.EXACT_ENTITY,
            query="字节要求先试用再签合同吗",
            description="精确事件查询 — 字节试用",
            expected_memories=["字节_试用"],
            expected_parent_entity="字节",
        ),
        MemoryEvalCase(
            id="exact_30", layer=EvalLayer.RETRIEVAL, query_type=QueryType.EXACT_ENTITY,
            query="小米的技术团队有什么偏好",
            description="精确策略查询 — 小米技术栈",
            expected_memories=["小米_技术栈"],
            expected_parent_entity="小米",
        ),
        MemoryEvalCase(
            id="exact_31", layer=EvalLayer.RETRIEVAL, query_type=QueryType.EXACT_ENTITY,
            query="华为今年预算情况怎么样",
            description="精确事件查询 — 华为预算",
            expected_memories=["华为_预算"],
            expected_parent_entity="华为",
        ),
        MemoryEvalCase(
            id="exact_32", layer=EvalLayer.RETRIEVAL, query_type=QueryType.EXACT_ENTITY,
            query="小米预算充足吗",
            description="精确事件查询 — 小米预算",
            expected_memories=["小米_预算"],
            expected_parent_entity="小米",
        ),
        MemoryEvalCase(
            id="exact_33", layer=EvalLayer.RETRIEVAL, query_type=QueryType.EXACT_ENTITY,
            query="比亚迪之前用过什么系统",
            description="精确事件查询 — 比亚迪竞品SAP",
            expected_memories=["比亚迪_竞品"],
            expected_parent_entity="比亚迪",
        ),
        MemoryEvalCase(
            id="exact_34", layer=EvalLayer.RETRIEVAL, query_type=QueryType.EXACT_ENTITY,
            query="比亚迪希望什么时候完成选型",
            description="精确事件查询 — 比亚迪时间表",
            expected_memories=["比亚迪_时间"],
            expected_parent_entity="比亚迪",
        ),
        MemoryEvalCase(
            id="exact_35", layer=EvalLayer.RETRIEVAL, query_type=QueryType.EXACT_ENTITY,
            query="招行培训要做几轮",
            description="精确策略查询 — 招行培训",
            expected_memories=["招行_培训"],
            expected_parent_entity="招行",
        ),
        MemoryEvalCase(
            id="exact_36", layer=EvalLayer.RETRIEVAL, query_type=QueryType.EXACT_ENTITY,
            query="字节对技术有什么特殊要求",
            description="精确策略查询 — 字节技术要求",
            expected_memories=["字节_技术要求"],
            expected_parent_entity="字节",
        ),
        MemoryEvalCase(
            id="exact_37", layer=EvalLayer.RETRIEVAL, query_type=QueryType.EXACT_ENTITY,
            query="腾讯王强什么时候有空",
            description="精确事件查询 — 腾讯时间窗口",
            expected_memories=["腾讯_时间窗口"],
            expected_parent_entity="腾讯",
        ),
        MemoryEvalCase(
            id="exact_38", layer=EvalLayer.RETRIEVAL, query_type=QueryType.EXACT_ENTITY,
            query="明天要去华为开会有什么需要注意的",
            description="综合查询 — 华为全部信息",
            expected_memories=["华为"],
            expected_parent_entity="华为",
        ),
        MemoryEvalCase(
            id="exact_39", layer=EvalLayer.RETRIEVAL, query_type=QueryType.EXACT_ENTITY,
            query="腾讯POC比用友快多少",
            description="精确事件查询 — 腾讯POC对比",
            expected_memories=["腾讯_POC", "用友"],
            expected_parent_entity="腾讯",
        ),
        MemoryEvalCase(
            id="exact_40", layer=EvalLayer.RETRIEVAL, query_type=QueryType.EXACT_ENTITY,
            query="比亚迪MES预算被砍了多少",
            description="精确事件查询 — 比亚迪MES预算",
            expected_memories=["比亚迪_MES"],
            expected_parent_entity="比亚迪",
        ),
    ]


# ═══════════════════════════════════════════════════════════
# 二、模糊语义召回（30 条）
# ═══════════════════════════════════════════════════════════

def _fuzzy_semantic_cases() -> list[MemoryEvalCase]:
    return [
        MemoryEvalCase(
            id="fuzzy_01", layer=EvalLayer.RETRIEVAL, query_type=QueryType.FUZZY_SEMANTIC,
            query="哪个客户的联系人说话最直接",
            description="模糊特征查询 — 性格",
            expected_memories=["华为_张伟"],
        ),
        MemoryEvalCase(
            id="fuzzy_02", layer=EvalLayer.RETRIEVAL, query_type=QueryType.FUZZY_SEMANTIC,
            query="有没有喜欢运动的客户联系人",
            description="模糊特征查询 — 爱好",
            expected_memories=["比亚迪_赵敏"],
        ),
        MemoryEvalCase(
            id="fuzzy_03", layer=EvalLayer.RETRIEVAL, query_type=QueryType.FUZZY_SEMANTIC,
            query="谁的邮件必须当天回复",
            description="模糊特征查询 — 工作风格",
            expected_memories=["字节_孙丽"],
        ),
        MemoryEvalCase(
            id="fuzzy_04", layer=EvalLayer.RETRIEVAL, query_type=QueryType.FUZZY_SEMANTIC,
            query="哪个客户追求快速迭代",
            description="模糊特征查询 — 技术偏好",
            expected_memories=["小米_林总"],
        ),
        MemoryEvalCase(
            id="fuzzy_05", layer=EvalLayer.RETRIEVAL, query_type=QueryType.FUZZY_SEMANTIC,
            query="谁最注重安全合规",
            description="模糊特征查询 — 关注点",
            expected_memories=["招行_陈刚", "招行_合规"],
        ),
        MemoryEvalCase(
            id="fuzzy_06", layer=EvalLayer.RETRIEVAL, query_type=QueryType.FUZZY_SEMANTIC,
            query="哪些项目快要签约了",
            description="模糊状态查询 — closing",
            expected_memories=["华为_安全审计"],
        ),
        MemoryEvalCase(
            id="fuzzy_07", layer=EvalLayer.RETRIEVAL, query_type=QueryType.FUZZY_SEMANTIC,
            query="有没有客户预算充足的",
            description="模糊特征查询 — 预算状态",
            expected_memories=["小米_预算"],
        ),
        MemoryEvalCase(
            id="fuzzy_08", layer=EvalLayer.RETRIEVAL, query_type=QueryType.FUZZY_SEMANTIC,
            query="谁的决策链比较长",
            description="模糊特征查询 — 流程复杂度",
            expected_memories=["比亚迪_决策链", "华为_采购流程"],
        ),
        MemoryEvalCase(
            id="fuzzy_09", layer=EvalLayer.RETRIEVAL, query_type=QueryType.FUZZY_SEMANTIC,
            query="哪个客户对价格最敏感",
            description="模糊特征查询 — 价格敏感",
            expected_memories=["腾讯_报价"],
        ),
        MemoryEvalCase(
            id="fuzzy_10", layer=EvalLayer.RETRIEVAL, query_type=QueryType.FUZZY_SEMANTIC,
            query="哪些客户需要私有化部署",
            description="模糊需求查询 — 部署方式",
            expected_memories=["比亚迪_工厂部署"],
        ),
        MemoryEvalCase(
            id="fuzzy_11", layer=EvalLayer.RETRIEVAL, query_type=QueryType.FUZZY_SEMANTIC,
            query="谁喜欢看demo不喜欢看PPT",
            description="模糊偏好查询 — 沟通形式",
            expected_memories=["腾讯_王强"],
        ),
        MemoryEvalCase(
            id="fuzzy_12", layer=EvalLayer.RETRIEVAL, query_type=QueryType.FUZZY_SEMANTIC,
            query="有没有客户要求多地部署",
            description="模糊需求查询 — 多地部署",
            expected_memories=["比亚迪_工厂部署"],
        ),
        MemoryEvalCase(
            id="fuzzy_13", layer=EvalLayer.RETRIEVAL, query_type=QueryType.FUZZY_SEMANTIC,
            query="哪些客户在评估竞品",
            description="模糊状态查询 — 竞品评估",
            expected_memories=["腾讯_数据中台", "字节_广告平台"],
        ),
        MemoryEvalCase(
            id="fuzzy_14", layer=EvalLayer.RETRIEVAL, query_type=QueryType.FUZZY_SEMANTIC,
            query="谁的采购流程最复杂",
            description="模糊流程查询 — 采购复杂度",
            expected_memories=["华为_采购流程"],
        ),
        MemoryEvalCase(
            id="fuzzy_15", layer=EvalLayer.RETRIEVAL, query_type=QueryType.FUZZY_SEMANTIC,
            query="最近需要跟进哪些客户",
            description="模糊时间查询 — 跟进提醒",
            expected_memories=["通用_大客户跟进"],
        ),
        MemoryEvalCase(
            id="fuzzy_16", layer=EvalLayer.RETRIEVAL, query_type=QueryType.FUZZY_SEMANTIC,
            query="做金融客户要注意什么",
            description="模糊行业查询 — 金融",
            expected_memories=["通用_金融方案"],
        ),
        MemoryEvalCase(
            id="fuzzy_17", layer=EvalLayer.RETRIEVAL, query_type=QueryType.FUZZY_SEMANTIC,
            query="互联网客户有什么特点",
            description="模糊行业查询 — 互联网",
            expected_memories=["通用_互联网方案"],
        ),
        MemoryEvalCase(
            id="fuzzy_18", layer=EvalLayer.RETRIEVAL, query_type=QueryType.FUZZY_SEMANTIC,
            query="遇到竞品怎么应对",
            description="模糊策略查询 — 竞品应对",
            expected_memories=["通用_竞品应对"],
        ),
        MemoryEvalCase(
            id="fuzzy_19", layer=EvalLayer.RETRIEVAL, query_type=QueryType.FUZZY_SEMANTIC,
            query="报价的通用策略是什么",
            description="模糊策略查询 — 报价通用",
            expected_memories=["通用_报价策略"],
        ),
        MemoryEvalCase(
            id="fuzzy_20", layer=EvalLayer.RETRIEVAL, query_type=QueryType.FUZZY_SEMANTIC,
            query="合同谈判要注意什么条款",
            description="模糊策略查询 — 合同谈判",
            expected_memories=["通用_合同谈判"],
        ),
        MemoryEvalCase(
            id="fuzzy_21", layer=EvalLayer.RETRIEVAL, query_type=QueryType.FUZZY_SEMANTIC,
            query="POC标准流程是什么",
            description="模糊流程查询 — POC",
            expected_memories=["通用_POC流程"],
        ),
        MemoryEvalCase(
            id="fuzzy_22", layer=EvalLayer.RETRIEVAL, query_type=QueryType.FUZZY_SEMANTIC,
            query="制造业客户关注什么",
            description="模糊行业查询 — 制造业",
            expected_memories=["通用_制造业方案"],
        ),
        MemoryEvalCase(
            id="fuzzy_23", layer=EvalLayer.RETRIEVAL, query_type=QueryType.FUZZY_SEMANTIC,
            query="哪个客户的技术要求最高",
            description="模糊特征查询 — 技术要求",
            expected_memories=["字节_技术要求"],
        ),
        MemoryEvalCase(
            id="fuzzy_24", layer=EvalLayer.RETRIEVAL, query_type=QueryType.FUZZY_SEMANTIC,
            query="谁要求先试用再签约",
            description="模糊需求查询 — 试用",
            expected_memories=["字节_试用"],
        ),
        MemoryEvalCase(
            id="fuzzy_25", layer=EvalLayer.RETRIEVAL, query_type=QueryType.FUZZY_SEMANTIC,
            query="有没有客户之前用过竞品体验不好的",
            description="模糊历史查询 — 竞品体验",
            expected_memories=["比亚迪_竞品"],
        ),
        MemoryEvalCase(
            id="fuzzy_26", layer=EvalLayer.RETRIEVAL, query_type=QueryType.FUZZY_SEMANTIC,
            query="哪些客户偏好微服务架构",
            description="模糊技术查询 — 架构偏好",
            expected_memories=["小米_技术栈"],
        ),
        MemoryEvalCase(
            id="fuzzy_27", layer=EvalLayer.RETRIEVAL, query_type=QueryType.FUZZY_SEMANTIC,
            query="谁对数据迁移有顾虑",
            description="模糊需求查询 — 数据迁移",
            expected_memories=["招行_数据迁移"],
        ),
        MemoryEvalCase(
            id="fuzzy_28", layer=EvalLayer.RETRIEVAL, query_type=QueryType.FUZZY_SEMANTIC,
            query="哪些客户对安全要求高",
            description="模糊需求查询 — 安全要求",
            expected_memories=["招行_合规", "招行_陈刚"],
        ),
        MemoryEvalCase(
            id="fuzzy_29", layer=EvalLayer.RETRIEVAL, query_type=QueryType.FUZZY_SEMANTIC,
            query="之前哪个客户说预算不够",
            description="模糊历史查询 — 预算不足",
            expected_memories=["华为_预算", "比亚迪_MES"],
        ),
        MemoryEvalCase(
            id="fuzzy_30", layer=EvalLayer.RETRIEVAL, query_type=QueryType.FUZZY_SEMANTIC,
            query="哪些项目金额超过1000万",
            description="模糊数值查询 — 大项目",
            expected_memories=["腾讯_AI平台", "字节_广告平台"],
        ),
    ]


# ═══════════════════════════════════════════════════════════
# 三、时间相关召回（20 条）
# ═══════════════════════════════════════════════════════════

def _time_related_cases() -> list[MemoryEvalCase]:
    return [
        MemoryEvalCase(
            id="time_01", layer=EvalLayer.TEMPORAL, query_type=QueryType.TIME_RELATED,
            query="腾讯下个月能推进吗",
            description="时间查询 — 腾讯时间窗口",
            expected_memories=["腾讯_时间窗口"],
        ),
        MemoryEvalCase(
            id="time_02", layer=EvalLayer.TEMPORAL, query_type=QueryType.TIME_RELATED,
            query="华为安全审计什么时候签",
            description="时间查询 — 签约时间",
            expected_memories=["华为_安全审计"],
        ),
        MemoryEvalCase(
            id="time_03", layer=EvalLayer.TEMPORAL, query_type=QueryType.TIME_RELATED,
            query="招行风控平台还要等多久",
            description="时间查询 — 等待周期",
            expected_memories=["招行_风控"],
        ),
        MemoryEvalCase(
            id="time_04", layer=EvalLayer.TEMPORAL, query_type=QueryType.TIME_RELATED,
            query="比亚迪Q4要开始实施吗",
            description="时间查询 — 实施时间",
            expected_memories=["比亚迪_时间"],
        ),
        MemoryEvalCase(
            id="time_05", layer=EvalLayer.TEMPORAL, query_type=QueryType.TIME_RELATED,
            query="华为签合同一般要多久",
            description="时间查询 — 合同周期",
            expected_memories=["华为_采购流程"],
        ),
        MemoryEvalCase(
            id="time_06", layer=EvalLayer.TEMPORAL, query_type=QueryType.TIME_RELATED,
            query="腾讯组织架构调整影响项目吗",
            description="时间查询 — 组织变动影响",
            expected_memories=["腾讯_时间窗口"],
        ),
        MemoryEvalCase(
            id="time_07", layer=EvalLayer.TEMPORAL, query_type=QueryType.TIME_RELATED,
            query="哪些项目在谈判阶段",
            description="时间查询 — 当前阶段",
            expected_memories=["华为_安全审计", "招行_风控"],
        ),
        MemoryEvalCase(
            id="time_08", layer=EvalLayer.TEMPORAL, query_type=QueryType.TIME_RELATED,
            query="本月不方便联系的客户有哪些",
            description="时间查询 — 联系时机",
            expected_memories=["腾讯_时间窗口"],
        ),
        MemoryEvalCase(
            id="time_09", layer=EvalLayer.TEMPORAL, query_type=QueryType.TIME_RELATED,
            query="大客户跟进的节奏是什么",
            description="时间策略查询 — 跟进频率",
            expected_memories=["通用_大客户跟进"],
        ),
        MemoryEvalCase(
            id="time_10", layer=EvalLayer.TEMPORAL, query_type=QueryType.TIME_RELATED,
            query="节假日前要重点跟进哪些客户",
            description="时间策略查询 — 节假日跟进",
            expected_memories=["通用_大客户跟进"],
        ),
        MemoryEvalCase(
            id="time_11", layer=EvalLayer.TEMPORAL, query_type=QueryType.TIME_RELATED,
            query="小米项目推进快吗",
            description="时间查询 — 推进速度",
            expected_memories=["小米_IoT", "小米_预算"],
        ),
        MemoryEvalCase(
            id="time_12", layer=EvalLayer.TEMPORAL, query_type=QueryType.TIME_RELATED,
            query="字节的项目变化大吗",
            description="时间查询 — 变动频率",
            expected_memories=["字节_孙丽"],
        ),
        MemoryEvalCase(
            id="time_13", layer=EvalLayer.TEMPORAL, query_type=QueryType.TIME_RELATED,
            query="招行正式流程还要多久",
            description="时间查询 — 流程时间",
            expected_memories=["招行_风控"],
        ),
        MemoryEvalCase(
            id="time_14", layer=EvalLayer.TEMPORAL, query_type=QueryType.TIME_RELATED,
            query="小米林总亲自推动哪个项目",
            description="时间查询 — 重点推进",
            expected_memories=["小米_智能工厂"],
        ),
        MemoryEvalCase(
            id="time_15", layer=EvalLayer.TEMPORAL, query_type=QueryType.TIME_RELATED,
            query="华为ERP项目什么时候能推进",
            description="时间查询 — 推进阻碍",
            expected_memories=["华为_ERP"],
        ),
        MemoryEvalCase(
            id="time_16", layer=EvalLayer.TEMPORAL, query_type=QueryType.TIME_RELATED,
            query="比亚迪Q3要完成什么",
            description="时间查询 — Q3目标",
            expected_memories=["比亚迪_时间"],
        ),
        MemoryEvalCase(
            id="time_17", layer=EvalLayer.TEMPORAL, query_type=QueryType.TIME_RELATED,
            query="哪个客户签约流程最长",
            description="时间对比查询 — 周期最长",
            expected_memories=["华为_采购流程"],
        ),
        MemoryEvalCase(
            id="time_18", layer=EvalLayer.TEMPORAL, query_type=QueryType.TIME_RELATED,
            query="字节要求免费试用多久",
            description="时间查询 — 试用期",
            expected_memories=["字节_试用"],
        ),
        MemoryEvalCase(
            id="time_19", layer=EvalLayer.TEMPORAL, query_type=QueryType.TIME_RELATED,
            query="招行上线前要做什么准备",
            description="时间查询 — 上线准备",
            expected_memories=["招行_培训"],
        ),
        MemoryEvalCase(
            id="time_20", layer=EvalLayer.TEMPORAL, query_type=QueryType.TIME_RELATED,
            query="小米两周内要出什么",
            description="时间查询 — 近期里程碑",
            expected_memories=["小米_IoT"],
        ),
    ]


# ═══════════════════════════════════════════════════════════
# 四、跨类别召回（20 条）
# ═══════════════════════════════════════════════════════════

def _cross_category_cases() -> list[MemoryEvalCase]:
    return [
        MemoryEvalCase(
            id="cross_01", layer=EvalLayer.RETRIEVAL, query_type=QueryType.CROSS_CATEGORY,
            query="华为的整体情况怎么样",
            description="跨类别 — 华为全貌（entities+events+patterns）",
            expected_memories=["华为"],
            assertion_mode="any",
        ),
        MemoryEvalCase(
            id="cross_02", layer=EvalLayer.RETRIEVAL, query_type=QueryType.CROSS_CATEGORY,
            query="准备去腾讯拜访要了解什么",
            description="跨类别 — 腾讯拜访准备",
            expected_memories=["腾讯_王强", "腾讯_数据中台", "腾讯_时间"],
            assertion_mode="any",
        ),
        MemoryEvalCase(
            id="cross_03", layer=EvalLayer.RETRIEVAL, query_type=QueryType.CROSS_CATEGORY,
            query="招行项目的全部信息",
            description="跨类别 — 招行全貌",
            expected_memories=["招行_陈刚", "招行_风控", "招行_合规"],
            assertion_mode="any",
        ),
        MemoryEvalCase(
            id="cross_04", layer=EvalLayer.RETRIEVAL, query_type=QueryType.CROSS_CATEGORY,
            query="比亚迪项目的人和事",
            description="跨类别 — 比亚迪人事",
            expected_memories=["比亚迪_赵敏", "比亚迪_MES"],
            assertion_mode="any",
        ),
        MemoryEvalCase(
            id="cross_05", layer=EvalLayer.RETRIEVAL, query_type=QueryType.CROSS_CATEGORY,
            query="字节我们都知道什么",
            description="跨类别 — 字节全貌",
            expected_memories=["字节_孙丽", "字节_广告平台"],
            assertion_mode="any",
        ),
        MemoryEvalCase(
            id="cross_06", layer=EvalLayer.RETRIEVAL, query_type=QueryType.CROSS_CATEGORY,
            query="小米那边项目和人的情况",
            description="跨类别 — 小米",
            expected_memories=["小米_林总", "小米_IoT"],
            assertion_mode="any",
        ),
        MemoryEvalCase(
            id="cross_07", layer=EvalLayer.RETRIEVAL, query_type=QueryType.CROSS_CATEGORY,
            query="华为的人和项目分别怎么样",
            description="跨类别 — 华为人事+项目",
            expected_memories=["华为_张伟", "华为_ERP"],
            assertion_mode="any",
        ),
        MemoryEvalCase(
            id="cross_08", layer=EvalLayer.RETRIEVAL, query_type=QueryType.CROSS_CATEGORY,
            query="大客户销售的通用方法论",
            description="跨类别 — 通用经验",
            expected_memories=["通用_大客户跟进", "通用_报价策略", "通用_竞品应对"],
            assertion_mode="any",
        ),
        MemoryEvalCase(
            id="cross_09", layer=EvalLayer.RETRIEVAL, query_type=QueryType.CROSS_CATEGORY,
            query="腾讯报价和竞品情况",
            description="跨类别 — 腾讯报价+竞品",
            expected_memories=["腾讯_报价", "腾讯_数据中台"],
            assertion_mode="any",
        ),
        MemoryEvalCase(
            id="cross_10", layer=EvalLayer.RETRIEVAL, query_type=QueryType.CROSS_CATEGORY,
            query="我是做什么的有什么客户",
            description="跨类别 — 用户画像+客户",
            expected_memories=["profile"],
            assertion_mode="any",
        ),
        MemoryEvalCase(
            id="cross_11", layer=EvalLayer.RETRIEVAL, query_type=QueryType.CROSS_CATEGORY,
            query="金融和互联网客户的区别",
            description="跨类别 — 行业对比",
            expected_memories=["通用_金融方案", "通用_互联网方案"],
            assertion_mode="any",
        ),
        MemoryEvalCase(
            id="cross_12", layer=EvalLayer.RETRIEVAL, query_type=QueryType.CROSS_CATEGORY,
            query="华为的报价和采购流程",
            description="跨类别 — 华为报价+流程",
            expected_memories=["华为_报价", "华为_采购流程"],
            assertion_mode="any",
        ),
        MemoryEvalCase(
            id="cross_13", layer=EvalLayer.RETRIEVAL, query_type=QueryType.CROSS_CATEGORY,
            query="招行的人和合规要求",
            description="跨类别 — 招行人+规",
            expected_memories=["招行_陈刚", "招行_合规"],
            assertion_mode="any",
        ),
        MemoryEvalCase(
            id="cross_14", layer=EvalLayer.RETRIEVAL, query_type=QueryType.CROSS_CATEGORY,
            query="各客户的预算情况汇总",
            description="跨类别 — 多客户预算",
            expected_memories=["华为_预算", "小米_预算", "比亚迪_MES"],
            assertion_mode="any",
        ),
        MemoryEvalCase(
            id="cross_15", layer=EvalLayer.RETRIEVAL, query_type=QueryType.CROSS_CATEGORY,
            query="各客户技术偏好对比",
            description="跨类别 — 多客户技术",
            expected_memories=["小米_技术栈", "字节_技术要求"],
            assertion_mode="any",
        ),
        MemoryEvalCase(
            id="cross_16", layer=EvalLayer.RETRIEVAL, query_type=QueryType.CROSS_CATEGORY,
            query="华为和招行的签约流程对比",
            description="跨类别 — 流程对比",
            expected_memories=["华为_采购流程", "招行_风控"],
            assertion_mode="any",
        ),
        MemoryEvalCase(
            id="cross_17", layer=EvalLayer.RETRIEVAL, query_type=QueryType.CROSS_CATEGORY,
            query="给新入职的同事介绍一下手上的客户",
            description="跨类别 — 全局概览",
            expected_memories=["profile"],
            assertion_mode="any",
        ),
        MemoryEvalCase(
            id="cross_18", layer=EvalLayer.RETRIEVAL, query_type=QueryType.CROSS_CATEGORY,
            query="比亚迪的竞品和时间安排",
            description="跨类别 — 比亚迪竞品+时间",
            expected_memories=["比亚迪_竞品", "比亚迪_时间"],
            assertion_mode="any",
        ),
        MemoryEvalCase(
            id="cross_19", layer=EvalLayer.RETRIEVAL, query_type=QueryType.CROSS_CATEGORY,
            query="腾讯POC和后续合同节奏",
            description="跨类别 — 腾讯POC+时间",
            expected_memories=["腾讯_POC", "腾讯_时间"],
            assertion_mode="any",
        ),
        MemoryEvalCase(
            id="cross_20", layer=EvalLayer.RETRIEVAL, query_type=QueryType.CROSS_CATEGORY,
            query="字节的人和技术要求",
            description="跨类别 — 字节人+技术",
            expected_memories=["字节_孙丽", "字节_技术要求"],
            assertion_mode="any",
        ),
    ]


# ═══════════════════════════════════════════════════════════
# 五、更新覆盖验证（20 条）
# ═══════════════════════════════════════════════════════════

def _update_override_cases() -> list[MemoryEvalCase]:
    """验证记忆更新后是否召回新版本"""
    return [
        MemoryEvalCase(
            id="update_01", layer=EvalLayer.TEMPORAL, query_type=QueryType.UPDATE_OVERRIDE,
            query="华为ERP项目现在什么进展",
            description="更新验证 — 华为ERP新状态",
            expected_memories=["华为_ERP"],
            metadata={"update_before": {"merge_key": "华为_ERP项目", "abstract": "华为/ERP项目: 已获得张伟支持，进入采购流程"}},
        ),
        MemoryEvalCase(
            id="update_02", layer=EvalLayer.TEMPORAL, query_type=QueryType.UPDATE_OVERRIDE,
            query="腾讯数据中台最新进展",
            description="更新验证 — 腾讯项目新状态",
            expected_memories=["腾讯_数据中台"],
            metadata={"update_before": {"merge_key": "腾讯_数据中台", "abstract": "腾讯/数据中台: 已签约，进入实施阶段"}},
        ),
        MemoryEvalCase(
            id="update_03", layer=EvalLayer.TEMPORAL, query_type=QueryType.UPDATE_OVERRIDE,
            query="比亚迪MES预算现在够吗",
            description="更新验证 — 预算恢复",
            expected_memories=["比亚迪_MES"],
            metadata={"update_before": {"merge_key": "比亚迪_MES预算", "abstract": "比亚迪/MES: 预算已恢复，赵敏批准继续"}},
        ),
        MemoryEvalCase(
            id="update_04", layer=EvalLayer.TEMPORAL, query_type=QueryType.UPDATE_OVERRIDE,
            query="华为张伟的最新态度",
            description="更新验证 — 联系人态度变化",
            expected_memories=["华为_张伟"],
            metadata={"update_before": {"merge_key": "华为_张伟_风格", "abstract": "华为/张伟: 最近变得更谨慎，要求更多数据支撑"}},
        ),
        MemoryEvalCase(
            id="update_05", layer=EvalLayer.TEMPORAL, query_type=QueryType.UPDATE_OVERRIDE,
            query="招行风控平台进度",
            description="更新验证 — 招行风控新进度",
            expected_memories=["招行_风控"],
            metadata={"update_before": {"merge_key": "招行_风控平台", "abstract": "招行/风控平台: 已启动正式采购，预计下周签约"}},
        ),
        MemoryEvalCase(
            id="update_06", layer=EvalLayer.TEMPORAL, query_type=QueryType.UPDATE_OVERRIDE,
            query="小米IoT平台进展",
            description="更新验证 — 小米IoT新阶段",
            expected_memories=["小米_IoT"],
        ),
        MemoryEvalCase(
            id="update_07", layer=EvalLayer.TEMPORAL, query_type=QueryType.UPDATE_OVERRIDE,
            query="字节广告平台竞争情况",
            description="更新验证 — 竞争格局变化",
            expected_memories=["字节_广告平台"],
        ),
        MemoryEvalCase(
            id="update_08", layer=EvalLayer.TEMPORAL, query_type=QueryType.UPDATE_OVERRIDE,
            query="腾讯王强的最新反馈",
            description="更新验证 — 联系人反馈",
            expected_memories=["腾讯_王强"],
        ),
        MemoryEvalCase(
            id="update_09", layer=EvalLayer.TEMPORAL, query_type=QueryType.UPDATE_OVERRIDE,
            query="华为预算情况有变化吗",
            description="更新验证 — 预算变化",
            expected_memories=["华为_预算"],
        ),
        MemoryEvalCase(
            id="update_10", layer=EvalLayer.TEMPORAL, query_type=QueryType.UPDATE_OVERRIDE,
            query="招行合规要求有更新吗",
            description="更新验证 — 合规更新",
            expected_memories=["招行_合规"],
        ),
        MemoryEvalCase(
            id="update_11", layer=EvalLayer.TEMPORAL, query_type=QueryType.UPDATE_OVERRIDE,
            query="比亚迪赵敏的最新偏好",
            description="更新验证 — 偏好变化",
            expected_memories=["比亚迪_赵敏"],
        ),
        MemoryEvalCase(
            id="update_12", layer=EvalLayer.TEMPORAL, query_type=QueryType.UPDATE_OVERRIDE,
            query="小米林总现在关注什么",
            description="更新验证 — 关注点变化",
            expected_memories=["小米_林总"],
        ),
        MemoryEvalCase(
            id="update_13", layer=EvalLayer.TEMPORAL, query_type=QueryType.UPDATE_OVERRIDE,
            query="字节孙丽态度有变化吗",
            description="更新验证 — 态度变化",
            expected_memories=["字节_孙丽"],
        ),
        MemoryEvalCase(
            id="update_14", layer=EvalLayer.TEMPORAL, query_type=QueryType.UPDATE_OVERRIDE,
            query="华为CRM部署最新要求",
            description="更新验证 — 需求变化",
            expected_memories=["华为_CRM"],
        ),
        MemoryEvalCase(
            id="update_15", layer=EvalLayer.TEMPORAL, query_type=QueryType.UPDATE_OVERRIDE,
            query="腾讯赵经理的角色变化",
            description="更新验证 — 角色变化",
            expected_memories=["腾讯_赵经理"],
        ),
        MemoryEvalCase(
            id="update_16", layer=EvalLayer.TEMPORAL, query_type=QueryType.UPDATE_OVERRIDE,
            query="比亚迪工厂部署新方案",
            description="更新验证 — 方案更新",
            expected_memories=["比亚迪_工厂部署"],
        ),
        MemoryEvalCase(
            id="update_17", layer=EvalLayer.TEMPORAL, query_type=QueryType.UPDATE_OVERRIDE,
            query="招行刘总的最新指示",
            description="更新验证 — 指示更新",
            expected_memories=["招行_刘总"],
        ),
        MemoryEvalCase(
            id="update_18", layer=EvalLayer.TEMPORAL, query_type=QueryType.UPDATE_OVERRIDE,
            query="腾讯AI平台预算调整",
            description="更新验证 — 预算调整",
            expected_memories=["腾讯_AI平台"],
        ),
        MemoryEvalCase(
            id="update_19", layer=EvalLayer.TEMPORAL, query_type=QueryType.UPDATE_OVERRIDE,
            query="字节技术要求有新增吗",
            description="更新验证 — 需求新增",
            expected_memories=["字节_技术要求"],
        ),
        MemoryEvalCase(
            id="update_20", layer=EvalLayer.TEMPORAL, query_type=QueryType.UPDATE_OVERRIDE,
            query="通用报价策略更新了吗",
            description="更新验证 — 策略迭代",
            expected_memories=["通用_报价策略"],
        ),
    ]


# ═══════════════════════════════════════════════════════════
# 六、冲突消解验证（15 条）
# ═══════════════════════════════════════════════════════════

def _conflict_resolve_cases() -> list[MemoryEvalCase]:
    """验证矛盾信息写入后是否保留正确版本"""
    return [
        MemoryEvalCase(
            id="conflict_01", layer=EvalLayer.TEMPORAL, query_type=QueryType.CONFLICT_RESOLVE,
            query="华为张伟喜欢PPT还是demo",
            description="冲突验证 — 偏好冲突（应保留PPT）",
            expected_memories=["华为_张伟"],
        ),
        MemoryEvalCase(
            id="conflict_02", layer=EvalLayer.TEMPORAL, query_type=QueryType.CONFLICT_RESOLVE,
            query="腾讯王强决策快还是慢",
            description="冲突验证 — 决策速度（应保留快）",
            expected_memories=["腾讯_王强"],
        ),
        MemoryEvalCase(
            id="conflict_03", layer=EvalLayer.TEMPORAL, query_type=QueryType.CONFLICT_RESOLVE,
            query="华为预算是紧还是松",
            description="冲突验证 — 预算状态（应保留收紧）",
            expected_memories=["华为_预算"],
        ),
        MemoryEvalCase(
            id="conflict_04", layer=EvalLayer.TEMPORAL, query_type=QueryType.CONFLICT_RESOLVE,
            query="比亚迪偏好国产化还是国际品牌",
            description="冲突验证 — 品牌偏好（应保留国产化）",
            expected_memories=["比亚迪_竞品"],
        ),
        MemoryEvalCase(
            id="conflict_05", layer=EvalLayer.TEMPORAL, query_type=QueryType.CONFLICT_RESOLVE,
            query="小米是预算充足还是不足",
            description="冲突验证 — 预算状态（应保留充足）",
            expected_memories=["小米_预算"],
        ),
        MemoryEvalCase(
            id="conflict_06", layer=EvalLayer.TEMPORAL, query_type=QueryType.CONFLICT_RESOLVE,
            query="招行看重短期价格还是长期价值",
            description="冲突验证 — 价值取向（应保留长期）",
            expected_memories=["招行_刘总"],
        ),
        MemoryEvalCase(
            id="conflict_07", layer=EvalLayer.TEMPORAL, query_type=QueryType.CONFLICT_RESOLVE,
            query="字节合同审核松还是严",
            description="冲突验证 — 审核力度（应保留严格）",
            expected_memories=["字节_合同法务"],
        ),
        MemoryEvalCase(
            id="conflict_08", layer=EvalLayer.TEMPORAL, query_type=QueryType.CONFLICT_RESOLVE,
            query="华为采购周期短还是长",
            description="冲突验证 — 周期（应保留3-4周）",
            expected_memories=["华为_采购流程"],
        ),
        MemoryEvalCase(
            id="conflict_09", layer=EvalLayer.TEMPORAL, query_type=QueryType.CONFLICT_RESOLVE,
            query="腾讯本月能联系还是不能",
            description="冲突验证 — 联系时机（应保留不能）",
            expected_memories=["腾讯_时间窗口"],
        ),
        MemoryEvalCase(
            id="conflict_10", layer=EvalLayer.TEMPORAL, query_type=QueryType.CONFLICT_RESOLVE,
            query="比亚迪决策快还是慢",
            description="冲突验证 — 决策速度（应保留慢/长）",
            expected_memories=["比亚迪_决策链"],
        ),
        MemoryEvalCase(
            id="conflict_11", layer=EvalLayer.TEMPORAL, query_type=QueryType.CONFLICT_RESOLVE,
            query="招行陈刚最关注什么",
            description="冲突验证 — 关注点（应保留安全）",
            expected_memories=["招行_陈刚"],
        ),
        MemoryEvalCase(
            id="conflict_12", layer=EvalLayer.TEMPORAL, query_type=QueryType.CONFLICT_RESOLVE,
            query="华为ERP有分歧还是已解决",
            description="冲突验证 — 项目状态",
            expected_memories=["华为_ERP"],
        ),
        MemoryEvalCase(
            id="conflict_13", layer=EvalLayer.TEMPORAL, query_type=QueryType.CONFLICT_RESOLVE,
            query="字节孙丽效率高还是低",
            description="冲突验证 — 效率评价",
            expected_memories=["字节_孙丽"],
        ),
        MemoryEvalCase(
            id="conflict_14", layer=EvalLayer.TEMPORAL, query_type=QueryType.CONFLICT_RESOLVE,
            query="小米技术偏好是传统还是微服务",
            description="冲突验证 — 技术路线",
            expected_memories=["小米_技术栈"],
        ),
        MemoryEvalCase(
            id="conflict_15", layer=EvalLayer.TEMPORAL, query_type=QueryType.CONFLICT_RESOLVE,
            query="腾讯POC效果好还是不好",
            description="冲突验证 — POC评价",
            expected_memories=["腾讯_POC"],
        ),
    ]


# ═══════════════════════════════════════════════════════════
# 七、长尾衰减验证（15 条）
# ═══════════════════════════════════════════════════════════

def _long_tail_decay_cases() -> list[MemoryEvalCase]:
    """验证低频记忆在长时间后是否仍可召回"""
    return [
        MemoryEvalCase(
            id="decay_01", layer=EvalLayer.TEMPORAL, query_type=QueryType.LONG_TAIL_DECAY,
            query="华为安全审计是什么项目",
            description="衰减验证 — 低频项目记忆",
            expected_memories=["华为_安全审计"],
        ),
        MemoryEvalCase(
            id="decay_02", layer=EvalLayer.TEMPORAL, query_type=QueryType.LONG_TAIL_DECAY,
            query="腾讯赵经理是谁",
            description="衰减验证 — 低频联系人",
            expected_memories=["腾讯_赵经理"],
        ),
        MemoryEvalCase(
            id="decay_03", layer=EvalLayer.TEMPORAL, query_type=QueryType.LONG_TAIL_DECAY,
            query="招行数据迁移的挑战",
            description="衰减验证 — 低频事件",
            expected_memories=["招行_数据迁移"],
        ),
        MemoryEvalCase(
            id="decay_04", layer=EvalLayer.TEMPORAL, query_type=QueryType.LONG_TAIL_DECAY,
            query="招行培训要求是什么",
            description="衰减验证 — 低频策略",
            expected_memories=["招行_培训"],
        ),
        MemoryEvalCase(
            id="decay_05", layer=EvalLayer.TEMPORAL, query_type=QueryType.LONG_TAIL_DECAY,
            query="比亚迪工厂在哪里",
            description="衰减验证 — 低频信息",
            expected_memories=["比亚迪_工厂部署"],
        ),
        MemoryEvalCase(
            id="decay_06", layer=EvalLayer.TEMPORAL, query_type=QueryType.LONG_TAIL_DECAY,
            query="小米技术栈偏好",
            description="衰减验证 — 低频技术偏好",
            expected_memories=["小米_技术栈"],
        ),
        MemoryEvalCase(
            id="decay_07", layer=EvalLayer.TEMPORAL, query_type=QueryType.LONG_TAIL_DECAY,
            query="通用合同谈判要注意什么",
            description="衰减验证 — 通用经验",
            expected_memories=["通用_合同谈判"],
        ),
        MemoryEvalCase(
            id="decay_08", layer=EvalLayer.TEMPORAL, query_type=QueryType.LONG_TAIL_DECAY,
            query="通用POC流程",
            description="衰减验证 — 通用流程",
            expected_memories=["通用_POC流程"],
        ),
        MemoryEvalCase(
            id="decay_09", layer=EvalLayer.TEMPORAL, query_type=QueryType.LONG_TAIL_DECAY,
            query="制造业方案要点",
            description="衰减验证 — 行业经验",
            expected_memories=["通用_制造业方案"],
        ),
        MemoryEvalCase(
            id="decay_10", layer=EvalLayer.TEMPORAL, query_type=QueryType.LONG_TAIL_DECAY,
            query="华为CRM部署安全要求",
            description="衰减验证 — 低频项目+需求",
            expected_memories=["华为_CRM"],
        ),
        MemoryEvalCase(
            id="decay_11", layer=EvalLayer.TEMPORAL, query_type=QueryType.LONG_TAIL_DECAY,
            query="腾讯AI平台谁负责",
            description="衰减验证 — 低频项目负责人",
            expected_memories=["腾讯_AI平台"],
        ),
        MemoryEvalCase(
            id="decay_12", layer=EvalLayer.TEMPORAL, query_type=QueryType.LONG_TAIL_DECAY,
            query="比亚迪SAP体验如何",
            description="衰减验证 — 历史竞品体验",
            expected_memories=["比亚迪_竞品"],
        ),
        MemoryEvalCase(
            id="decay_13", layer=EvalLayer.TEMPORAL, query_type=QueryType.LONG_TAIL_DECAY,
            query="字节广告平台金额",
            description="衰减验证 — 低频数值信息",
            expected_memories=["字节_广告平台"],
        ),
        MemoryEvalCase(
            id="decay_14", layer=EvalLayer.TEMPORAL, query_type=QueryType.LONG_TAIL_DECAY,
            query="华为李娜做事风格",
            description="衰减验证 — 低频联系人",
            expected_memories=["华为_李娜"],
        ),
        MemoryEvalCase(
            id="decay_15", layer=EvalLayer.TEMPORAL, query_type=QueryType.LONG_TAIL_DECAY,
            query="招行刘总审批权限",
            description="衰减验证 — 低频流程信息",
            expected_memories=["招行_刘总"],
        ),
    ]


# ═══════════════════════════════════════════════════════════
# 八、负例验证（20 条）
# ═══════════════════════════════════════════════════════════

def _negative_cases() -> list[MemoryEvalCase]:
    """验证与记忆无关的查询不会被强行召回"""
    return [
        MemoryEvalCase(
            id="neg_01", layer=EvalLayer.RETRIEVAL, query_type=QueryType.NEGATIVE,
            query="今天北京天气怎么样",
            description="负例 — 无关查询（天气）",
            expected_memories=[], negative=True,
        ),
        MemoryEvalCase(
            id="neg_02", layer=EvalLayer.RETRIEVAL, query_type=QueryType.NEGATIVE,
            query="Python编程入门教程",
            description="负例 — 无关查询（编程）",
            expected_memories=[], negative=True,
        ),
        MemoryEvalCase(
            id="neg_03", layer=EvalLayer.RETRIEVAL, query_type=QueryType.NEGATIVE,
            query="公司年会节目推荐",
            description="负例 — 无关查询（娱乐）",
            expected_memories=[], negative=True,
        ),
        MemoryEvalCase(
            id="neg_04", layer=EvalLayer.RETRIEVAL, query_type=QueryType.NEGATIVE,
            query="电脑蓝屏死机怎么修",
            description="负例 — 无关查询（IT故障）",
            expected_memories=[], negative=True,
        ),
        MemoryEvalCase(
            id="neg_05", layer=EvalLayer.RETRIEVAL, query_type=QueryType.NEGATIVE,
            query="如何申请ISO9001质量体系认证",
            description="负例 — 无关查询（认证流程）",
            expected_memories=[], negative=True,
        ),
        MemoryEvalCase(
            id="neg_06", layer=EvalLayer.RETRIEVAL, query_type=QueryType.NEGATIVE,
            query="上海明天天气怎么样",
            description="负例 — 无关查询（天气2）",
            expected_memories=[], negative=True,
        ),
        MemoryEvalCase(
            id="neg_07", layer=EvalLayer.RETRIEVAL, query_type=QueryType.NEGATIVE,
            query="帮我写一首诗",
            description="负例 — 无关查询（创作）",
            expected_memories=[], negative=True,
        ),
        MemoryEvalCase(
            id="neg_08", layer=EvalLayer.RETRIEVAL, query_type=QueryType.NEGATIVE,
            query="周杰伦最新专辑什么时候出",
            description="负例 — 无关查询（娱乐2）",
            expected_memories=[], negative=True,
        ),
        MemoryEvalCase(
            id="neg_09", layer=EvalLayer.RETRIEVAL, query_type=QueryType.NEGATIVE,
            query="怎么做西红柿炒鸡蛋",
            description="负例 — 无关查询（烹饪）",
            expected_memories=[], negative=True,
        ),
        MemoryEvalCase(
            id="neg_10", layer=EvalLayer.RETRIEVAL, query_type=QueryType.NEGATIVE,
            query="量子计算的基本原理是什么",
            description="负例 — 无关查询（科学）",
            expected_memories=[], negative=True,
        ),
        MemoryEvalCase(
            id="neg_11", layer=EvalLayer.RETRIEVAL, query_type=QueryType.NEGATIVE,
            query="北京到上海高铁多久",
            description="负例 — 无关查询（交通）",
            expected_memories=[], negative=True,
        ),
        MemoryEvalCase(
            id="neg_12", layer=EvalLayer.RETRIEVAL, query_type=QueryType.NEGATIVE,
            query="如何学好英语口语",
            description="负例 — 无关查询（学习）",
            expected_memories=[], negative=True,
        ),
        MemoryEvalCase(
            id="neg_13", layer=EvalLayer.RETRIEVAL, query_type=QueryType.NEGATIVE,
            query="推荐一款降噪耳机",
            description="负例 — 无关查询（购物）",
            expected_memories=[], negative=True,
        ),
        MemoryEvalCase(
            id="neg_14", layer=EvalLayer.RETRIEVAL, query_type=QueryType.NEGATIVE,
            query="春节假期几天",
            description="负例 — 无关查询（假期）",
            expected_memories=[], negative=True,
        ),
        MemoryEvalCase(
            id="neg_15", layer=EvalLayer.RETRIEVAL, query_type=QueryType.NEGATIVE,
            query="对",
            description="负例 — 极简输入",
            expected_memories=[], negative=True,
        ),
        MemoryEvalCase(
            id="neg_16", layer=EvalLayer.RETRIEVAL, query_type=QueryType.NEGATIVE,
            query="好的",
            description="负例 — 极简确认",
            expected_memories=[], negative=True,
        ),
        MemoryEvalCase(
            id="neg_17", layer=EvalLayer.RETRIEVAL, query_type=QueryType.NEGATIVE,
            query="嗯",
            description="负例 — 极简应答",
            expected_memories=[], negative=True,
        ),
        MemoryEvalCase(
            id="neg_18", layer=EvalLayer.RETRIEVAL, query_type=QueryType.NEGATIVE,
            query="你好",
            description="负例 — 打招呼",
            expected_memories=[], negative=True,
        ),
        MemoryEvalCase(
            id="neg_19", layer=EvalLayer.RETRIEVAL, query_type=QueryType.NEGATIVE,
            query="谢谢",
            description="负例 — 礼貌用语",
            expected_memories=[], negative=True,
        ),
        MemoryEvalCase(
            id="neg_20", layer=EvalLayer.RETRIEVAL, query_type=QueryType.NEGATIVE,
            query="继续",
            description="负例 — 指令词",
            expected_memories=[], negative=True,
        ),
    ]


# ═══════════════════════════════════════════════════════════
# 九、多维度综合（20 条）
# ═══════════════════════════════════════════════════════════

def _multi_dimension_cases() -> list[MemoryEvalCase]:
    return [
        MemoryEvalCase(
            id="multi_01", layer=EvalLayer.RETRIEVAL, query_type=QueryType.MULTI_DIMENSION,
            query="准备华为开会材料需要注意的所有事项",
            description="多维度 — 华为会前准备（人+项目+策略）",
            expected_memories=["华为_张伟", "华为_报价", "华为_采购流程"],
            assertion_mode="any",
        ),
        MemoryEvalCase(
            id="multi_02", layer=EvalLayer.RETRIEVAL, query_type=QueryType.MULTI_DIMENSION,
            query="给腾讯做方案要考虑什么",
            description="多维度 — 腾讯方案准备",
            expected_memories=["腾讯_王强", "腾讯_报价", "腾讯_数据中台"],
            assertion_mode="any",
        ),
        MemoryEvalCase(
            id="multi_03", layer=EvalLayer.RETRIEVAL, query_type=QueryType.MULTI_DIMENSION,
            query="招行项目推进需要注意的人和流程",
            description="多维度 — 招行人+流程",
            expected_memories=["招行_陈刚", "招行_合规", "招行_刘总"],
            assertion_mode="any",
        ),
        MemoryEvalCase(
            id="multi_04", layer=EvalLayer.RETRIEVAL, query_type=QueryType.MULTI_DIMENSION,
            query="比亚迪项目的关键风险点",
            description="多维度 — 比亚迪风险",
            expected_memories=["比亚迪_MES", "比亚迪_决策链", "比亚迪_时间"],
            assertion_mode="any",
        ),
        MemoryEvalCase(
            id="multi_05", layer=EvalLayer.RETRIEVAL, query_type=QueryType.MULTI_DIMENSION,
            query="如何打赢字节广告平台这个单",
            description="多维度 — 字节赢单策略",
            expected_memories=["字节_孙丽", "字节_广告平台", "字节_技术要求"],
            assertion_mode="any",
        ),
        MemoryEvalCase(
            id="multi_06", layer=EvalLayer.RETRIEVAL, query_type=QueryType.MULTI_DIMENSION,
            query="小米项目的机会和挑战",
            description="多维度 — 小米SWOT",
            expected_memories=["小米_林总", "小米_预算", "小米_技术栈"],
            assertion_mode="any",
        ),
        MemoryEvalCase(
            id="multi_07", layer=EvalLayer.RETRIEVAL, query_type=QueryType.MULTI_DIMENSION,
            query="本季度最有可能签约的项目有哪些",
            description="多维度 — 签约预测",
            expected_memories=["华为_安全审计", "招行_风控"],
            assertion_mode="any",
        ),
        MemoryEvalCase(
            id="multi_08", layer=EvalLayer.RETRIEVAL, query_type=QueryType.MULTI_DIMENSION,
            query="各客户联系人的沟通策略总结",
            description="多维度 — 多客户沟通策略",
            expected_memories=["华为_张伟", "腾讯_王强", "字节_孙丽"],
            assertion_mode="any",
        ),
        MemoryEvalCase(
            id="multi_09", layer=EvalLayer.RETRIEVAL, query_type=QueryType.MULTI_DIMENSION,
            query="KA客户竞品分布情况",
            description="多维度 — 竞品地图",
            expected_memories=["腾讯_数据中台", "字节_广告平台", "比亚迪_竞品"],
            assertion_mode="any",
        ),
        MemoryEvalCase(
            id="multi_10", layer=EvalLayer.RETRIEVAL, query_type=QueryType.MULTI_DIMENSION,
            query="给老板汇报各客户整体进展",
            description="多维度 — 全局进展汇报",
            expected_memories=["华为", "腾讯", "招行"],
            assertion_mode="any",
        ),
        MemoryEvalCase(
            id="multi_11", layer=EvalLayer.RETRIEVAL, query_type=QueryType.MULTI_DIMENSION,
            query="华为和腾讯的报价策略对比",
            description="多维度 — 策略对比",
            expected_memories=["华为_报价", "腾讯_报价"],
            assertion_mode="any",
        ),
        MemoryEvalCase(
            id="multi_12", layer=EvalLayer.RETRIEVAL, query_type=QueryType.MULTI_DIMENSION,
            query="制造业客户的共同特点和个性差异",
            description="多维度 — 行业+客户",
            expected_memories=["通用_制造业方案", "比亚迪"],
            assertion_mode="any",
        ),
        MemoryEvalCase(
            id="multi_13", layer=EvalLayer.RETRIEVAL, query_type=QueryType.MULTI_DIMENSION,
            query="下周工作重点安排建议",
            description="多维度 — 工作规划",
            expected_memories=["通用_大客户跟进", "华为_安全审计"],
            assertion_mode="any",
        ),
        MemoryEvalCase(
            id="multi_14", layer=EvalLayer.RETRIEVAL, query_type=QueryType.MULTI_DIMENSION,
            query="新客户拓展的方法论和案例",
            description="多维度 — 方法论+案例",
            expected_memories=["通用_报价策略", "通用_POC流程"],
            assertion_mode="any",
        ),
        MemoryEvalCase(
            id="multi_15", layer=EvalLayer.RETRIEVAL, query_type=QueryType.MULTI_DIMENSION,
            query="安全合规方面我们的积累和客户需求",
            description="多维度 — 合规能力+需求",
            expected_memories=["招行_合规", "通用_金融方案"],
            assertion_mode="any",
        ),
        MemoryEvalCase(
            id="multi_16", layer=EvalLayer.RETRIEVAL, query_type=QueryType.MULTI_DIMENSION,
            query="各客户的技术选型偏好汇总",
            description="多维度 — 多客户技术",
            expected_memories=["小米_技术栈", "字节_技术要求"],
            assertion_mode="any",
        ),
        MemoryEvalCase(
            id="multi_17", layer=EvalLayer.RETRIEVAL, query_type=QueryType.MULTI_DIMENSION,
            query="从过去经验看什么类型客户最容易成交",
            description="多维度 — 经验总结",
            expected_memories=["通用_大客户跟进", "通用_报价策略"],
            assertion_mode="any",
        ),
        MemoryEvalCase(
            id="multi_18", layer=EvalLayer.RETRIEVAL, query_type=QueryType.MULTI_DIMENSION,
            query="帮我回顾一下我的客户画像和工作重点",
            description="多维度 — 自我认知",
            expected_memories=["profile"],
            assertion_mode="any",
        ),
        MemoryEvalCase(
            id="multi_19", layer=EvalLayer.RETRIEVAL, query_type=QueryType.MULTI_DIMENSION,
            query="华为和字节哪个更值得投入精力",
            description="多维度 — 优先级判断",
            expected_memories=["华为_安全审计", "字节_广告平台"],
            assertion_mode="any",
        ),
        MemoryEvalCase(
            id="multi_20", layer=EvalLayer.RETRIEVAL, query_type=QueryType.MULTI_DIMENSION,
            query="年底冲刺重点关注什么客户什么项目",
            description="多维度 — 年底规划",
            expected_memories=["华为_安全审计", "招行_风控", "通用_大客户跟进"],
            assertion_mode="any",
        ),
    ]
