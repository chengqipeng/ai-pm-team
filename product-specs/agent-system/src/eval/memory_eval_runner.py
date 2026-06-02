"""长期记忆召回率评测引擎

五层评测体系：
  Layer 1: 写入正确性（Extract Accuracy）
  Layer 2: 检索召回率（Retrieval Recall）
  Layer 3: 时间衰减（Temporal Dynamics）
  Layer 4: 上下文匹配度（Context Relevance）
  Layer 5: 端到端效果（E2E Impact）

设计原则：
  - 分层解耦：每层独立评测，快速定位问题
  - 隔离执行：使用独立 Memory 实例，不污染生产数据
  - 与现有 200 场景用例对齐
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════
# 数据模型
# ═══════════════════════════════════════════════════════════

class EvalLayer(str, Enum):
    EXTRACT = "extract"          # Layer 1: 写入正确性
    RETRIEVAL = "retrieval"      # Layer 2: 检索召回率
    TEMPORAL = "temporal"        # Layer 3: 时间衰减
    CONTEXT = "context"          # Layer 4: 上下文匹配度
    E2E = "e2e"                  # Layer 5: 端到端效果


class QueryType(str, Enum):
    EXACT_ENTITY = "exact_entity"        # 精确实体召回
    FUZZY_SEMANTIC = "fuzzy_semantic"     # 模糊语义召回
    TIME_RELATED = "time_related"        # 时间相关召回
    CROSS_CATEGORY = "cross_category"    # 跨类别召回
    UPDATE_OVERRIDE = "update_override"  # 更新覆盖验证
    CONFLICT_RESOLVE = "conflict_resolve"  # 冲突消解验证
    LONG_TAIL_DECAY = "long_tail_decay"  # 长尾衰减验证
    NEGATIVE = "negative"                # 负例验证
    MULTI_DIMENSION = "multi_dimension"  # 多维度综合


@dataclass
class MemoryEvalCase:
    """记忆评测用例"""
    id: str
    layer: EvalLayer
    query_type: QueryType
    query: str                          # 检索查询
    description: str = ""
    expected_memories: list[str] = field(default_factory=list)  # 期望命中的记忆 merge_key 或关键词
    expected_category: str = ""         # 期望类别
    expected_parent_entity: str = ""    # 期望父实体
    top_k: int = 5                      # 评测时取 Top-K
    assertion_mode: str = "any"         # any=任一命中即可, all=全部命中, ordered=按顺序
    negative: bool = False              # 负例（不应召回）
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class MemoryEvalResult:
    """单条用例的评测结果"""
    case_id: str
    query_type: str
    layer: str
    passed: bool
    query: str = ""
    description: str = ""
    expected: list[str] = field(default_factory=list)
    actual: list[dict] = field(default_factory=list)  # 实际召回结果
    recall_at_k: float = 0.0
    precision_at_k: float = 0.0
    mrr: float = 0.0
    top1_hit: bool = False
    duration_ms: float = 0.0
    error: str = ""

    def to_dict(self) -> dict:
        return {
            "case_id": self.case_id,
            "query_type": self.query_type,
            "layer": self.layer,
            "passed": self.passed,
            "query": self.query,
            "description": self.description,
            "expected": self.expected,
            "actual": self.actual[:5],  # 只返回 Top-5
            "recall_at_k": round(self.recall_at_k, 4),
            "precision_at_k": round(self.precision_at_k, 4),
            "mrr": round(self.mrr, 4),
            "top1_hit": self.top1_hit,
            "duration_ms": round(self.duration_ms, 1),
            "error": self.error,
        }


@dataclass
class MemoryEvalReport:
    """评测报告"""
    total: int = 0
    passed: int = 0
    failed: int = 0
    results: list[MemoryEvalResult] = field(default_factory=list)
    total_duration_ms: float = 0.0

    # 按层统计
    by_layer: dict[str, dict] = field(default_factory=dict)
    # 按查询类型统计
    by_query_type: dict[str, dict] = field(default_factory=dict)
    # 聚合指标
    avg_recall_at_3: float = 0.0
    avg_recall_at_5: float = 0.0
    avg_precision_at_5: float = 0.0
    avg_mrr: float = 0.0
    top1_hit_rate: float = 0.0

    @property
    def pass_rate(self) -> float:
        return self.passed / max(self.total, 1)

    def to_dict(self) -> dict:
        return {
            "total": self.total,
            "passed": self.passed,
            "failed": self.failed,
            "pass_rate": round(self.pass_rate, 4),
            "total_duration_ms": round(self.total_duration_ms, 1),
            "by_layer": self.by_layer,
            "by_query_type": self.by_query_type,
            "avg_recall_at_3": round(self.avg_recall_at_3, 4),
            "avg_recall_at_5": round(self.avg_recall_at_5, 4),
            "avg_precision_at_5": round(self.avg_precision_at_5, 4),
            "avg_mrr": round(self.avg_mrr, 4),
            "top1_hit_rate": round(self.top1_hit_rate, 4),
            "results": [r.to_dict() for r in self.results],
        }


# ═══════════════════════════════════════════════════════════
# 种子数据：模拟的记忆数据集
# ═══════════════════════════════════════════════════════════

SEED_MEMORIES = [
    # ── 华为客户 ──
    {"merge_key": "华为_张伟_风格", "category": "entities", "parent_entity": "华为",
     "abstract": "华为/张伟: 说话直接，汇报用PPT，决策果断",
     "content": "华为科技的张伟是IT部门负责人，说话非常直接，开会时喜欢看PPT而不是demo，决策果断但要求数据支撑。"},
    {"merge_key": "华为_李娜_风格", "category": "entities", "parent_entity": "华为",
     "abstract": "华为/李娜: 采购经理，做事谨慎，注重合规流程",
     "content": "华为的李娜是采购经理，做事非常谨慎，每个决策都要反复确认，特别注重合规流程和供应商资质。"},
    {"merge_key": "华为_ERP项目", "category": "events", "parent_entity": "华为",
     "abstract": "华为/ERP项目: 张伟支持但李娜担心预算，存在内部分歧",
     "content": "华为科技ERP项目中张伟和李娜意见不太一致，张伟想上ERP，但李娜觉得预算不够，建议分别沟通。"},
    {"merge_key": "华为_采购流程", "category": "patterns", "parent_entity": "华为",
     "abstract": "华为/采购流程: 需过IT部门评估+采购委员会审批，周期3-4周",
     "content": "华为的采购流程需要先过IT部门技术评估，再经过采购委员会审批，整个周期大约3-4周。"},
    {"merge_key": "华为_报价策略", "category": "patterns", "parent_entity": "华为",
     "abstract": "华为/报价: 先报标准价预留谈判空间，张伟喜欢直接了当",
     "content": "给华为报价要注意先报标准价格预留谈判空间，张伟喜欢直接了当，不要绕弯子。"},
    {"merge_key": "华为_预算收紧", "category": "events", "parent_entity": "华为",
     "abstract": "华为/预算: 今年预算收紧，需强调ROI才能推动",
     "content": "华为今年整体预算收紧，任何采购都需要明确的ROI分析，建议准备详细的投入产出测算。"},
    {"merge_key": "华为_安全审计", "category": "events", "parent_entity": "华为",
     "abstract": "华为/安全审计项目: 即将closing，本周可能签约",
     "content": "华为安全审计项目已经走完所有流程，即将closing，预计本周就能签约。"},
    {"merge_key": "华为_CRM部署", "category": "events", "parent_entity": "华为",
     "abstract": "华为/CRM部署: 李娜负责，需满足数据安全合规要求",
     "content": "华为CRM部署项目由李娜负责跟进，她特别强调要满足数据安全和合规要求。"},

    # ── 腾讯客户 ──
    {"merge_key": "腾讯_王强_风格", "category": "entities", "parent_entity": "腾讯",
     "abstract": "腾讯/王强: CTO，技术导向，偏好live demo而非PPT",
     "content": "腾讯的王强是CTO，技术导向明显，开会时更喜欢看live demo而不是PPT，决策快。"},
    {"merge_key": "腾讯_数据中台", "category": "events", "parent_entity": "腾讯",
     "abstract": "腾讯/数据中台: 在评估我们和用友，POC效果好（3倍快）",
     "content": "腾讯数据中台项目正在评估我们和用友两家，我们的POC执行效率是用友的3倍，王强表示满意。"},
    {"merge_key": "腾讯_POC结果", "category": "events", "parent_entity": "腾讯",
     "abstract": "腾讯/POC: 性能是用友的3倍，王强表扬了团队效率",
     "content": "腾讯POC测试结果很好，我们的性能是用友的3倍，王强在会上表扬了我们团队的效率。"},
    {"merge_key": "腾讯_时间窗口", "category": "events", "parent_entity": "腾讯",
     "abstract": "腾讯/时间窗口: 下月组织架构调整，王强本月没时间跟进",
     "content": "腾讯下个月有组织架构调整，王强表示本月没时间跟进我们的项目，建议下月再联系。"},
    {"merge_key": "腾讯_报价策略", "category": "patterns", "parent_entity": "腾讯",
     "abstract": "腾讯/报价: 对价格敏感，需突出性价比，VP审批",
     "content": "腾讯对价格比较敏感，报价时需要突出性价比，最终需要VP审批。"},
    {"merge_key": "腾讯_赵经理", "category": "entities", "parent_entity": "腾讯",
     "abstract": "腾讯/赵经理: 采购部门，执行层面对接人",
     "content": "腾讯的赵经理在采购部门，是执行层面的对接人，负责合同流程和付款安排。"},
    {"merge_key": "腾讯_AI平台", "category": "events", "parent_entity": "腾讯",
     "abstract": "腾讯/AI平台项目: 预算1200万，王强直接负责",
     "content": "腾讯AI平台项目预算1200万，由王强直接负责推动，技术评审已通过。"},

    # ── 招行客户 ──
    {"merge_key": "招行_陈刚_风格", "category": "entities", "parent_entity": "招行",
     "abstract": "招行/陈刚: 信息安全部总监，最关注安全合规",
     "content": "招行的陈刚是信息安全部总监，最关注的是安全合规问题，任何方案必须满足等保三级和SOC2。"},
    {"merge_key": "招行_风控平台", "category": "events", "parent_entity": "招行",
     "abstract": "招行/风控平台: 方案已确认，预计两周内启动正式流程",
     "content": "招行风控平台项目方案已经确认，预计两周内启动正式采购流程。"},
    {"merge_key": "招行_合规要求", "category": "patterns", "parent_entity": "招行",
     "abstract": "招行/合规: 需等保三级+SOC2认证，数据不出境",
     "content": "招行的合规要求包括：等保三级认证、SOC2 Type II报告、数据不出境、定期安全审计。"},
    {"merge_key": "招行_刘总", "category": "entities", "parent_entity": "招行",
     "abstract": "招行/刘总: VP级，负责最终审批，看重长期战略价值",
     "content": "招行的刘总是VP级别，负责大额采购的最终审批，看重供应商的长期战略价值而非短期价格。"},
    {"merge_key": "招行_数据迁移", "category": "events", "parent_entity": "招行",
     "abstract": "招行/数据迁移: 历史数据量大，需专项迁移方案",
     "content": "招行有大量历史数据需要迁移，历史数据格式不统一，需要制定专项数据迁移方案。"},
    {"merge_key": "招行_培训要求", "category": "patterns", "parent_entity": "招行",
     "abstract": "招行/培训: 要求3轮培训（管理层+技术+业务），每轮20人",
     "content": "招行要求上线前做3轮培训，分别面向管理层、技术人员和业务人员，每轮约20人参加。"},

    # ── 比亚迪客户 ──
    {"merge_key": "比亚迪_赵敏_偏好", "category": "entities", "parent_entity": "比亚迪",
     "abstract": "比亚迪/赵敏: 喜欢非正式场合沟通，爱打羽毛球",
     "content": "比亚迪的赵敏喜欢在非正式场合沟通，爱好打羽毛球，约饭或运动时谈事效果更好。"},
    {"merge_key": "比亚迪_MES预算", "category": "events", "parent_entity": "比亚迪",
     "abstract": "比亚迪/MES项目: 预算被砍20%，需重新论证ROI",
     "content": "比亚迪MES项目预算被砍了20%，赵敏说需要重新论证ROI才能继续推进。"},
    {"merge_key": "比亚迪_决策链", "category": "patterns", "parent_entity": "比亚迪",
     "abstract": "比亚迪/决策: 技术线和采购线并行，最终赵敏拍板",
     "content": "比亚迪的决策链比较长，技术线评估和采购线流程并行进行，最终由赵敏统一拍板。"},
    {"merge_key": "比亚迪_工厂部署", "category": "events", "parent_entity": "比亚迪",
     "abstract": "比亚迪/部署: 需深圳和长沙两地部署，网络条件差异大",
     "content": "比亚迪要求在深圳总部和长沙工厂两地部署，两地网络条件差异较大，需要考虑离线能力。"},
    {"merge_key": "比亚迪_竞品SAP", "category": "events", "parent_entity": "比亚迪",
     "abstract": "比亚迪/竞品: 之前用过SAP体验不好，偏好国产化方案",
     "content": "比亚迪之前用过SAP，体验不太好，现在明确偏好国产化方案，这是我们的优势。"},
    {"merge_key": "比亚迪_时间表", "category": "events", "parent_entity": "比亚迪",
     "abstract": "比亚迪/时间: 希望Q3完成选型，Q4启动实施",
     "content": "比亚迪希望在Q3完成供应商选型，Q4正式启动实施，时间比较紧张。"},

    # ── 小米客户 ──
    {"merge_key": "小米_林总_风格", "category": "entities", "parent_entity": "小米",
     "abstract": "小米/林总: 互联网思维，追求快速迭代，不喜欢传统方案",
     "content": "小米的林总有典型的互联网思维，追求快速迭代和敏捷开发，不喜欢传统的瀑布式项目方案。"},
    {"merge_key": "小米_IoT平台", "category": "events", "parent_entity": "小米",
     "abstract": "小米/IoT平台: 正在方案设计阶段，林总亲自关注",
     "content": "小米IoT平台项目正在方案设计阶段，林总亲自关注，要求两周内出概念设计。"},
    {"merge_key": "小米_技术栈", "category": "patterns", "parent_entity": "小米",
     "abstract": "小米/技术: 偏好微服务架构+API优先，要求开放性强",
     "content": "小米技术团队偏好微服务架构和API优先的设计理念，要求系统开放性强，能灵活对接内部系统。"},
    {"merge_key": "小米_预算充足", "category": "events", "parent_entity": "小米",
     "abstract": "小米/预算: 预算充足，关键是快速响应和技术能力",
     "content": "小米预算比较充足，不是主要卡点，关键是能否快速响应需求和展现技术能力。"},
    {"merge_key": "小米_智能工厂", "category": "events", "parent_entity": "小米",
     "abstract": "小米/智能工厂: 林总直接推动，年度重点项目",
     "content": "小米智能工厂是林总直接推动的年度重点项目，预算优先级最高。"},

    # ── 字节客户 ──
    {"merge_key": "字节_孙丽_风格", "category": "entities", "parent_entity": "字节",
     "abstract": "字节/孙丽: 雷厉风行，邮件必须当天回复，决策极快",
     "content": "字节的孙丽做事雷厉风行，发的邮件必须当天回复，她的决策速度非常快，但也要求供应商同样高效。"},
    {"merge_key": "字节_广告平台", "category": "events", "parent_entity": "字节",
     "abstract": "字节/广告平台: 竞争对手是Salesforce，金额3000万",
     "content": "字节广告平台项目我们和Salesforce竞争，项目金额约3000万，孙丽在评估中。"},
    {"merge_key": "字节_技术要求", "category": "patterns", "parent_entity": "字节",
     "abstract": "字节/技术: 要求支持10万级并发，低延迟响应",
     "content": "字节对技术要求很高，系统必须支持10万级并发访问，接口响应延迟要在100ms以内。"},
    {"merge_key": "字节_合同法务", "category": "patterns", "parent_entity": "字节",
     "abstract": "字节/合同: 法务审核严格，合同条款细致",
     "content": "字节的法务审核非常严格，合同条款要求细致，建议提前准备好各类合规材料。"},
    {"merge_key": "字节_试用要求", "category": "events", "parent_entity": "字节",
     "abstract": "字节/试用: 要求先免费试用1个月再签合同",
     "content": "字节要求先免费试用1个月，观察实际效果后再决定是否签正式合同。"},

    # ── 通用经验 ──
    {"merge_key": "通用_金融方案", "category": "patterns", "parent_entity": "",
     "abstract": "金融行业方案: 重点安全合规+数据不出境+资质认证",
     "content": "做金融客户方案要重点突出安全合规能力、数据不出境保证、以及各类安全资质认证。"},
    {"merge_key": "通用_互联网方案", "category": "patterns", "parent_entity": "",
     "abstract": "互联网行业方案: 重点性能+可扩展性+快速迭代能力",
     "content": "互联网客户最关注系统性能、可扩展性和快速迭代能力，方案中要突出这些优势。"},
    {"merge_key": "通用_制造业方案", "category": "patterns", "parent_entity": "",
     "abstract": "制造业方案: 重点工厂部署+离线能力+多地协同",
     "content": "制造业客户关注工厂环境部署、离线运行能力和多地协同，要考虑网络条件差的场景。"},
    {"merge_key": "通用_报价策略", "category": "patterns", "parent_entity": "",
     "abstract": "报价通用策略: 先了解预算范围，阶梯报价，预留谈判空间",
     "content": "报价通用策略：先了解客户预算范围，采用阶梯式报价方案，预留适当谈判空间。"},
    {"merge_key": "通用_竞品应对", "category": "patterns", "parent_entity": "",
     "abstract": "竞品应对策略: 差异化定位，不贬低对手，突出自身优势",
     "content": "遇到竞品时坚持差异化定位策略，不要贬低对手，而是突出自身独特优势和客户成功案例。"},
    {"merge_key": "通用_大客户跟进", "category": "patterns", "parent_entity": "",
     "abstract": "大客户跟进节奏: 每周至少一次有效触达，节假日前重点关注",
     "content": "大客户跟进保持每周至少一次有效触达，节假日前要重点关注进展，避免被遗忘。"},
    {"merge_key": "通用_POC流程", "category": "patterns", "parent_entity": "",
     "abstract": "POC标准流程: 需求确认→环境准备→数据导入→演示评估",
     "content": "POC标准流程包括：需求确认、环境准备、样本数据导入、功能演示和效果评估。"},
    {"merge_key": "通用_合同谈判", "category": "patterns", "parent_entity": "",
     "abstract": "合同谈判要点: 关注付款条件、SLA条款、违约责任",
     "content": "合同谈判重点关注付款条件（分期比例）、SLA服务等级条款和违约责任界定。"},

    # ── 用户画像 ──
    {"merge_key": "profile", "category": "profile", "parent_entity": "",
     "abstract": "用户画像: 大客户销售经理，擅长ToB销售，负责华为/腾讯等KA客户",
     "content": "用户是大客户销售经理，擅长ToB企业级销售，主要负责华为、腾讯、招行等KA客户的跟进和维护。"},
]


# ═══════════════════════════════════════════════════════════
# 内存记忆引擎（评测用，不依赖外部服务）
# ═══════════════════════════════════════════════════════════

class InMemoryEvalEngine:
    """纯内存记忆引擎 — 用于评测，基于关键词+简单相似度匹配

    不依赖 VDB/PG，支持快速隔离评测。
    模拟真实 VikingMemoryEngine 的 retrieve 行为。
    """

    def __init__(self):
        self._memories: list[dict] = []
        self._write_log: list[dict] = []

    def seed(self, memories: list[dict]):
        """批量写入种子数据"""
        self._memories = [m.copy() for m in memories]

    def add_memory(self, memory: dict):
        """写入单条记忆"""
        # 检查 merge_key 是否已存在（模拟 upsert）
        for i, m in enumerate(self._memories):
            if m.get("merge_key") == memory.get("merge_key"):
                self._memories[i] = memory.copy()
                self._write_log.append({"action": "update", "memory": memory})
                return
        self._memories.append(memory.copy())
        self._write_log.append({"action": "insert", "memory": memory})

    def retrieve(self, query: str, top_k: int = 5,
                 category: str = None, parent_entity: str = None) -> list[dict]:
        """基于关键词匹配的简单检索（模拟向量检索行为）

        评分策略：
          1. abstract 中包含查询关键词 → +1 分/词
          2. parent_entity 精确匹配 → +3 分
          3. category 匹配 → +1 分
          4. content 中包含关键词 → +0.5 分/词
        """
        query_lower = query.lower()
        # 提取查询中的关键词（中文按字符切分 + 保留完整词）
        keywords = self._extract_keywords(query)

        scored = []
        for mem in self._memories:
            score = 0.0
            abstract = (mem.get("abstract") or "").lower()
            content = (mem.get("content") or "").lower()
            mem_parent = mem.get("parent_entity", "")

            # 关键词匹配
            for kw in keywords:
                if kw in abstract:
                    score += 2.0
                if kw in content:
                    score += 0.5

            # 父实体匹配
            if parent_entity and mem_parent == parent_entity:
                score += 3.0
            elif mem_parent and mem_parent in query:
                score += 3.0

            # 类别筛选
            if category and mem.get("category") != category:
                continue

            if score > 0:
                scored.append((score, mem))

        # 按分数降序排列
        scored.sort(key=lambda x: -x[0])
        return [item[1] for item in scored[:top_k]]

    def _extract_keywords(self, text: str) -> list[str]:
        """简单分词 — 提取有检索价值的关键词"""
        import re
        # 中文词（2字以上）
        cn_words = re.findall(r'[\u4e00-\u9fff]{2,}', text)
        # 英文词
        en_words = re.findall(r'[a-zA-Z]+', text)
        # 数字
        numbers = re.findall(r'\d+', text)

        all_words = cn_words + en_words + numbers
        # 过滤停用词
        stopwords = {"什么", "怎么", "哪个", "哪些", "有没有", "是否", "需要",
                     "帮我", "请问", "一下", "可以", "能否", "还是", "以及"}
        return [w.lower() for w in all_words if w not in stopwords and len(w) >= 2]

    def clear(self):
        self._memories = []
        self._write_log = []

    @property
    def memory_count(self) -> int:
        return len(self._memories)


# ═══════════════════════════════════════════════════════════
# 评测执行器
# ═══════════════════════════════════════════════════════════

class MemoryEvalRunner:
    """记忆召回率评测执行器"""

    def __init__(self, engine: InMemoryEvalEngine | None = None):
        self._engine = engine or InMemoryEvalEngine()

    def setup(self, seed_data: list[dict] | None = None):
        """初始化评测环境"""
        data = seed_data or SEED_MEMORIES
        self._engine.seed(data)
        logger.info("Memory eval engine seeded with %d memories", self._engine.memory_count)

    async def run_cases(self, cases: list[MemoryEvalCase],
                        layers: list[EvalLayer] | None = None,
                        query_types: list[QueryType] | None = None) -> MemoryEvalReport:
        """执行评测用例集"""
        # 筛选
        filtered = cases
        if layers:
            filtered = [c for c in filtered if c.layer in layers]
        if query_types:
            filtered = [c for c in filtered if c.query_type in query_types]

        report = MemoryEvalReport()
        report.total = len(filtered)

        all_recall_3 = []
        all_recall_5 = []
        all_precision_5 = []
        all_mrr = []
        top1_hits = 0

        start_time = time.time()

        for case in filtered:
            result = await self._run_single(case)
            report.results.append(result)

            if result.passed:
                report.passed += 1
            else:
                report.failed += 1

            # 聚合指标
            all_recall_5.append(result.recall_at_k)
            all_mrr.append(result.mrr)
            if result.top1_hit:
                top1_hits += 1

            # 按层统计
            layer_key = result.layer
            if layer_key not in report.by_layer:
                report.by_layer[layer_key] = {"total": 0, "passed": 0, "failed": 0}
            report.by_layer[layer_key]["total"] += 1
            if result.passed:
                report.by_layer[layer_key]["passed"] += 1
            else:
                report.by_layer[layer_key]["failed"] += 1

            # 按类型统计
            qt_key = result.query_type
            if qt_key not in report.by_query_type:
                report.by_query_type[qt_key] = {"total": 0, "passed": 0, "failed": 0}
            report.by_query_type[qt_key]["total"] += 1
            if result.passed:
                report.by_query_type[qt_key]["passed"] += 1
            else:
                report.by_query_type[qt_key]["failed"] += 1

        report.total_duration_ms = (time.time() - start_time) * 1000

        # 计算聚合指标
        n = max(len(filtered), 1)
        report.avg_recall_at_5 = sum(all_recall_5) / n
        report.avg_mrr = sum(all_mrr) / n
        report.top1_hit_rate = top1_hits / n

        return report

    async def _run_single(self, case: MemoryEvalCase) -> MemoryEvalResult:
        """执行单条用例"""
        start = time.time()
        try:
            # 执行检索
            results = self._engine.retrieve(
                query=case.query,
                top_k=case.top_k,
                category=case.expected_category or None,
                parent_entity=None,  # 不传 parent_entity，让引擎自己判断
            )

            duration = (time.time() - start) * 1000

            # 提取实际结果摘要
            actual = []
            for r in results:
                actual.append({
                    "merge_key": r.get("merge_key", ""),
                    "abstract": r.get("abstract", ""),
                    "category": r.get("category", ""),
                    "parent_entity": r.get("parent_entity", ""),
                })

            # 计算指标
            recall_at_k, precision_at_k, mrr, top1_hit, passed = self._evaluate(
                case, results
            )

            return MemoryEvalResult(
                case_id=case.id,
                query_type=case.query_type.value,
                layer=case.layer.value,
                passed=passed,
                query=case.query,
                description=case.description,
                expected=case.expected_memories,
                actual=actual,
                recall_at_k=recall_at_k,
                precision_at_k=precision_at_k,
                mrr=mrr,
                top1_hit=top1_hit,
                duration_ms=duration,
            )
        except Exception as e:
            duration = (time.time() - start) * 1000
            return MemoryEvalResult(
                case_id=case.id,
                query_type=case.query_type.value,
                layer=case.layer.value,
                passed=False,
                query=case.query,
                description=case.description,
                expected=case.expected_memories,
                duration_ms=duration,
                error=str(e),
            )

    def _evaluate(self, case: MemoryEvalCase, results: list[dict]) -> tuple:
        """评估检索结果

        Returns: (recall_at_k, precision_at_k, mrr, top1_hit, passed)
        """
        if case.negative:
            # 负例：不应召回任何期望的记忆
            for r in results:
                for expected_kw in case.expected_memories:
                    abstract = r.get("abstract", "") + r.get("merge_key", "")
                    if expected_kw.lower() in abstract.lower():
                        return 0.0, 0.0, 0.0, False, False
            return 1.0, 1.0, 1.0, True, True

        if not case.expected_memories:
            # 没有期望记忆定义 → 只要有结果就算通过
            return 1.0, 1.0, 1.0, len(results) > 0, len(results) > 0

        # 正向评测
        hit_count = 0
        first_hit_rank = 0
        expected_set = set(kw.lower() for kw in case.expected_memories)

        for i, r in enumerate(results):
            # 检查是否命中期望记忆（关键词匹配）
            searchable = (
                r.get("merge_key", "") + " " +
                r.get("abstract", "") + " " +
                r.get("parent_entity", "")
            ).lower()

            for kw in expected_set:
                if kw in searchable:
                    hit_count += 1
                    if first_hit_rank == 0:
                        first_hit_rank = i + 1
                    break

        total_expected = len(case.expected_memories)
        recall_at_k = hit_count / max(total_expected, 1)
        precision_at_k = hit_count / max(len(results), 1)
        mrr = (1.0 / first_hit_rank) if first_hit_rank > 0 else 0.0
        top1_hit = first_hit_rank == 1

        # 通过判定
        if case.assertion_mode == "any":
            passed = hit_count > 0
        elif case.assertion_mode == "all":
            passed = hit_count >= total_expected
        else:
            passed = hit_count > 0

        return recall_at_k, precision_at_k, mrr, top1_hit, passed


# ═══════════════════════════════════════════════════════════
# Console 输出
# ═══════════════════════════════════════════════════════════

def print_memory_eval_report(report: MemoryEvalReport):
    """控制台输出评测报告"""
    print("\n")
    print("═" * 60)
    print("  长期记忆召回率评测报告")
    print(f"  用例: {report.total} 条  |  耗时: {report.total_duration_ms:.1f}ms")
    print("═" * 60)

    # 按层输出
    print("\n── 按评测层 ──────────────────────────────────────────")
    layer_names = {
        "retrieval": "检索召回率",
        "temporal": "时间衰减",
        "context": "上下文匹配",
        "extract": "写入正确性",
        "e2e": "端到端效果",
    }
    for layer, stats in report.by_layer.items():
        name = layer_names.get(layer, layer)
        total = stats["total"]
        passed = stats["passed"]
        rate = passed / max(total, 1) * 100
        icon = "✅" if rate >= 85 else ("⚠️" if rate >= 70 else "❌")
        print(f"  {icon} {name:<12} {passed}/{total}  ({rate:.1f}%)")

    # 按查询类型输出
    print("\n── 按查询类型 ────────────────────────────────────────")
    type_names = {
        "exact_entity": "精确实体",
        "fuzzy_semantic": "模糊语义",
        "time_related": "时间相关",
        "cross_category": "跨类别",
        "update_override": "更新覆盖",
        "conflict_resolve": "冲突消解",
        "long_tail_decay": "长尾衰减",
        "negative": "负例过滤",
        "multi_dimension": "多维度",
    }
    for qt, stats in report.by_query_type.items():
        name = type_names.get(qt, qt)
        total = stats["total"]
        passed = stats["passed"]
        rate = passed / max(total, 1) * 100
        icon = "✅" if rate >= 85 else ("⚠️" if rate >= 70 else "❌")
        print(f"  {icon} {name:<12} {passed}/{total}  ({rate:.1f}%)")

    # 聚合指标
    print("\n── 聚合指标 ──────────────────────────────────────────")
    print(f"  Recall@5        {report.avg_recall_at_5 * 100:.1f}%")
    print(f"  MRR             {report.avg_mrr:.3f}")
    print(f"  Top-1 命中率    {report.top1_hit_rate * 100:.1f}%")

    # 汇总
    print("\n── 汇总 ──────────────────────────────────────────────")
    print(f"┌──────────────┬───────────┬────────┬────────────┐")
    print(f"│ 指标         │ 数值      │ 目标   │ 状态       │")
    print(f"├──────────────┼───────────┼────────┼────────────┤")
    pr = report.pass_rate * 100
    print(f"│ 通过率       │ {pr:>6.1f}%   │ ≥85%   │ {'✅ PASS' if pr >= 85 else '⚠️ WARN' if pr >= 70 else '❌ FAIL'}   │")
    r5 = report.avg_recall_at_5 * 100
    print(f"│ Recall@5     │ {r5:>6.1f}%   │ ≥80%   │ {'✅ PASS' if r5 >= 80 else '⚠️ WARN' if r5 >= 60 else '❌ FAIL'}   │")
    t1 = report.top1_hit_rate * 100
    print(f"│ Top-1 命中   │ {t1:>6.1f}%   │ ≥75%   │ {'✅ PASS' if t1 >= 75 else '⚠️ WARN' if t1 >= 60 else '❌ FAIL'}   │")
    print(f"└──────────────┴───────────┴────────┴────────────┘")

    # 失败用例
    failures = [r for r in report.results if not r.passed]
    if failures:
        print(f"\n── 失败用例 ({len(failures)} 条) ──────────────────────────")
        for f in failures[:10]:
            print(f"  ❌ [{f.query_type}] {f.query[:40]}")
            print(f"     期望: {f.expected[:3]}")
            if f.actual:
                print(f"     实际Top-1: {f.actual[0].get('abstract', '')[:50]}")
            if f.error:
                print(f"     错误: {f.error[:80]}")

    print("\n")
