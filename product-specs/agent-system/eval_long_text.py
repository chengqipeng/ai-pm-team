"""
LightKompress 长文本低信息密度评测
==================================
测试场景：1000-3000字符文本，仅30%句子含关键数据，70%为填充描述
50个测试用例覆盖5大场景

评测指标：
  - must_keep recall >= 98.5%
  - compression savings >= 15%
"""

from __future__ import annotations
import re
import time
from dataclasses import dataclass
from demo_light_kompress import LightKompress, CompressResult


# must_keep 正则（与 LightKompress.MUST_KEEP_PATTERNS 一致）
MUST_KEEP_PATTERNS = [
    re.compile(r'\d[\d,.]*\s*%'),
    re.compile(r'[\$¥￥]\s*[\d,.]+[KMB万亿]?'),
    re.compile(r'\d{4}[-/]\d{1,2}[-/]\d{1,2}'),
    re.compile(r'\d+[.:]\d+(?:[.:]\d+)?'),
    re.compile(r'\d[\d,.]+[KMBGTkmbgt]?\w*'),
    re.compile(r'[A-Z][a-z]+(?:[A-Z][a-z]+)+'),
    re.compile(r'[A-Z][A-Z0-9_]{2,}'),
    re.compile(r'https?://\S+'),
    re.compile(r'/[a-z0-9][\w/.-]+'),
    re.compile(r'[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.'),
    re.compile(r'[a-z_]+=[a-zA-Z0-9_.]+'),
    re.compile(r'[a-z_]+:[a-z_]+\([a-z_]+\)'),
    re.compile(r'[A-Z][\w-]*\.\w+[:]\d+'),
]


def extract_must_keep(text: str) -> set[str]:
    """提取文本中所有 must_keep 实体"""
    entities = set()
    for pattern in MUST_KEEP_PATTERNS:
        entities.update(pattern.findall(text))
    return entities


def calc_recall(original_text: str, compressed_text: str) -> float:
    """计算 must_keep 实体的召回率"""
    original_entities = extract_must_keep(original_text)
    if not original_entities:
        return 1.0
    recalled = sum(1 for e in original_entities if e in compressed_text)
    return recalled / len(original_entities)


# ═══════════════════════════════════════════════════════════
# 测试用例定义
# ═══════════════════════════════════════════════════════════

TEST_CASES: list[dict] = []


# ─── K01-K10: 中文 CRM/销售报告 ──────────────────────────

TEST_CASES.append({
    "id": "K01",
    "name": "季度销售总结-华东区",
    "context": "华东区销售业绩",
    "text": (
        "经过详细的分析和研究，我们对华东区本季度的销售情况进行了全面的回顾和总结。"
        "从整体上来看，目前的情况是市场竞争依然激烈，各个团队都在积极努力地推进业务发展。"
        "值得一提的是，在这个过程中我们遇到了不少挑战，但团队展现了很强的韧性和执行力。"
        "需要说明的是，关于这个问题我们已经进行了多次内部讨论和评估。"
        "总的来说，我们在这方面做了大量工作，包括市场调研、客户拜访和方案优化等。"
        "在日常运营层面，团队保持了良好的工作节奏，各项流程运转正常。"
        "另外从行业趋势来看，数字化转型的需求依然旺盛，这为我们提供了广阔的市场空间。"
        "我们注意到客户对于产品的期望在不断提高，这也驱动我们持续进行产品迭代。"
        "在团队建设方面，本季度新增了3名销售顾问，目前团队规模达到了合理水平。"
        "关于竞争对手方面，我们也进行了系统性的分析和对标研究。"
        "本季度华东区实际完成销售额¥3,850万，达成率112%，同比增长28.5%。"
        "其中大客户贡献¥2,100万，占比54.5%，新签客户47家，续约率达到91.3%。"
        "本季度签约的最大单笔合同金额为¥680万，来自金融行业的某头部券商。"
        "平均客单价从上季度的¥32万提升至¥38万，增幅为18.7%。"
        "Q4目标为¥4,200万，需在2024-12-31前完成全年KPI的冲刺。"
        "从管理层面来说，我们还需要进一步优化内部协作机制和信息共享流程。"
        "在客户关系维护方面，我们坚持定期回访的原则，确保客户满意度维持在较高水平。"
        "综合以上各方面的情况来看，本季度整体表现符合预期，部分指标超出了年初设定的目标。"
    ),
    "must_keep": ["¥3,850万", "112%", "28.5%", "¥2,100万", "54.5%", "91.3%", "¥680万", "18.7%", "¥4,200万", "2024-12-31"],
})

TEST_CASES.append({
    "id": "K02",
    "name": "客户流失分析报告",
    "context": "客户流失原因",
    "text": (
        "关于客户流失这个话题，我们团队一直以来都非常重视，并且投入了大量精力去分析和研究。"
        "从宏观角度来看，客户流失是任何SaaS企业都不可避免需要面对的问题。"
        "在过去的几个月里，我们的客户成功团队进行了大量的沟通和回访工作。"
        "值得一提的是，我们在分析方法论上也进行了升级，引入了更多维度的数据分析框架。"
        "从行业最佳实践来看，客户流失的原因通常是多方面的，很难归结为单一因素。"
        "我们认为，建立完善的预警机制是减少流失的关键手段之一。"
        "在日常工作中，客户成功经理会定期与客户进行沟通，了解他们的使用情况和满意度。"
        "同时我们也在不断优化产品功能，以期更好地满足客户的实际需求。"
        "经过详细的数据分析和客户访谈，我们对流失情况有了比较清晰的认识。"
        "本季度客户流失率为4.8%，较上季度6.2%下降了1.4个百分点。"
        "流失客户共计156家，其中合同金额低于¥5万的小微客户占比72.4%。"
        "流失原因TOP3：价格因素占38%，功能不满足占27%，竞品替代占19%。"
        "高价值客户（年合同>¥50万）流失仅3家，流失率0.8%，远低于整体水平。"
        "流失预警模型准确率已达到85.6%，可提前14天识别高风险客户。"
        "总的来说，这些数据给我们提供了很好的参考依据，让我们能够更精准地制定留存策略。"
        "在接下来的工作中，我们将继续深化对客户需求的理解，不断提升服务质量。"
        "另外我们还计划引入更智能的客户健康度评分体系来辅助决策。"
        "从长远来看，降低流失率需要产品、服务和运营多方面的协同努力。"
    ),
    "must_keep": ["4.8%", "6.2%", "1.4", "156", "¥5万", "72.4%", "38%", "27%", "19%", "¥50万", "0.8%", "85.6%"],
})

TEST_CASES.append({
    "id": "K03",
    "name": "销售漏斗转化分析",
    "context": "各阶段转化率",
    "text": (
        "在销售管理的日常实践中，漏斗分析是我们非常重视的一个环节。"
        "从整体方法论来看，销售漏斗的管理需要结合定量数据和定性判断来进行综合评估。"
        "值得一提的是，我们在过去几个季度里持续优化了漏斗管理的流程和工具。"
        "经过团队的讨论，我们一致认为漏斗健康度直接影响到未来的业绩预测准确性。"
        "需要说明的是，不同行业和客户规模的漏斗转化周期存在较大差异。"
        "从销售方法论的角度来看，MEDDIC框架在大客户销售中被证明是非常有效的。"
        "我们的销售代表在日常工作中也在不断积累经验，提升各环节的转化能力。"
        "关于市场环境的变化，我们注意到客户的决策周期在整体上有所延长。"
        "在数字化工具方面，CRM系统的使用率和数据质量也在持续提升。"
        "从我们的观察来看，线索质量的高低对后续转化有着决定性的影响。"
        "本季度漏斗数据如下：线索到MQL转化率为23.5%，MQL到SQL为34.8%。"
        "SQL到商机转化率为45.2%，商机到签约的win rate为28.6%。"
        "整体从线索到签约的端到端转化率为1.06%，平均成交周期为67天。"
        "本季度新增线索12,450条，最终签约132笔，平均合同金额¥29.2万。"
        "与上季度对比，MQL到SQL阶段提升了5.3个百分点，是改善最明显的环节。"
        "在漏斗管理的实际操作中，我们还在不断完善数据采集和分析的精细度。"
        "另外我们计划在下季度引入AI辅助的线索评分机制来提升线索质量。"
        "总的来说，漏斗管理是一项需要持续投入和优化的系统工程。"
        "展望未来，我们相信通过不断的改进和创新，转化效率还有很大的提升空间。"
    ),
    "must_keep": ["23.5%", "34.8%", "45.2%", "28.6%", "1.06%", "12,450", "132", "¥29.2万", "5.3"],
})

TEST_CASES.append({
    "id": "K04",
    "name": "大客户经营季报",
    "context": "大客户收入情况",
    "text": (
        "大客户经营一直是我们公司战略的核心组成部分，我们在这方面投入了大量的资源和精力。"
        "从行业的普遍经验来看，二八定律在大客户管理中体现得非常明显。"
        "在日常的客户维护工作中，我们的Key Account Manager团队保持了高频的客户接触。"
        "值得一提的是，我们在本季度还举办了多场行业沙龙活动来增进客户关系。"
        "需要说明的是，大客户的需求往往更加复杂和多样化，需要我们提供定制化的解决方案。"
        "从市场反馈来看，客户对我们产品的整体评价是正面的，但仍有改进空间。"
        "在竞争格局方面，我们面临着来自多个维度的挑战，需要不断强化自身优势。"
        "我们的服务理念是以客户为中心，深入理解客户的业务场景和痛点。"
        "关于团队能力建设，我们也在持续开展各类培训和学习交流活动。"
        "从长远发展来看，建立深度的客户信任是大客户经营成功的基础。"
        "另外，我们注意到跨部门协作在大客户服务中扮演着越来越重要的角色。"
        "本季度大客户（年合同>¥100万）共68家，贡献收入¥8,920万，占总营收63.5%。"
        "TOP10客户贡献¥4,150万，客户集中度为29.5%，较上季度略有下降。"
        "新增大客户8家，流失2家，净增6家，增长率为9.7%。"
        "大客户平均ARR为¥131.2万，NRR（净收入留存率）为118.5%。"
        "交叉销售渗透率从32%提升至38%，追加销售转化率为22.8%。"
        "接下来我们将继续深耕大客户市场，围绕客户的核心需求提供更多增值服务。"
        "总之，大客户经营需要耐心和长期主义的心态，不能急功近利。"
    ),
    "must_keep": ["¥100万", "¥8,920万", "63.5%", "¥4,150万", "29.5%", "9.7%", "¥131.2万", "118.5%", "32%", "38%", "22.8%"],
})

TEST_CASES.append({
    "id": "K05",
    "name": "市场活动ROI报告",
    "context": "市场活动效果",
    "text": (
        "在过去的一个季度里，市场团队组织了多场活动，整体工作节奏比较紧凑。"
        "从市场营销的大环境来看，获客成本在持续上升，这要求我们更加注重活动效率。"
        "值得一提的是，我们在内容营销方面做了很多新的尝试和探索。"
        "需要说明的是，线上和线下活动的投入产出比存在较大差异，需要区别对待。"
        "经过团队的反复讨论和优化，我们逐步形成了一套相对成熟的活动运营方法论。"
        "从品牌建设的角度看，持续的市场活动对于提升品牌知名度有着重要作用。"
        "我们注意到，目标客户群体的信息获取方式在不断变化，这要求我们适时调整策略。"
        "在社交媒体运营方面，团队保持了稳定的内容输出频率和质量。"
        "关于竞品的市场动作，我们也在密切关注并进行对标分析。"
        "总的来说，市场工作是一项需要长期坚持才能看到效果的投入。"
        "另外团队在协作效率和流程标准化方面也取得了一定的进步。"
        "本季度市场总投入¥285万，产生有效线索3,280条，获客单价CAC为¥868。"
        "线下活动投入¥120万，获客652条，CPL为¥1,840；线上活动投入¥165万，获客2,628条，CPL为¥628。"
        "活动带来的签约金额为¥1,520万，整体ROI为5.33倍。"
        "其中年度大会ROI最高达8.2倍，行业沙龙为4.5倍，线上研讨会为3.8倍。"
        "内容下载转化率为12.8%，注册到参会的转化率为45.6%。"
        "在后续的工作规划中，我们将加大线上活动的投入比例，进一步降低获客成本。"
        "最终我们希望能够建立起一套可复制、可规模化的市场获客引擎。"
    ),
    "must_keep": ["¥285万", "3,280", "¥868", "¥120万", "652", "¥1,840", "¥165万", "2,628", "¥628", "¥1,520万", "5.33", "8.2", "4.5", "3.8", "12.8%", "45.6%"],
})


TEST_CASES.append({
    "id": "K06",
    "name": "渠道合作伙伴季度回顾",
    "context": "渠道销售贡献",
    "text": (
        "渠道生态建设是公司发展战略中的重要一环，我们一直在积极推进这方面的工作。"
        "从行业的角度来看，建立健康的渠道体系需要长时间的培育和投入。"
        "值得一提的是，我们在合作伙伴赋能方面做了大量的基础性工作，包括培训体系搭建和技术支持。"
        "需要说明的是，不同类型的合作伙伴在能力模型和合作模式上存在较大差异。"
        "经过持续的探索和优化，我们逐步明确了适合自身业务特点的渠道策略。"
        "在日常的合作伙伴管理中，我们注重沟通的频率和质量，确保信息的及时传递。"
        "从整体市场环境来看，间接销售模式正在被越来越多的SaaS企业所采用。"
        "我们认为，与合作伙伴的关系应该是互利共赢的，而非简单的交易关系。"
        "关于渠道冲突管理，我们也制定了相应的规则和处理流程来保障各方利益。"
        "另外在合作伙伴激励方面，我们设计了分层级的返利和奖励机制。"
        "总的来说，渠道建设是一项需要耐心和恒心的长期投资。"
        "本季度渠道合作伙伴总计186家，活跃伙伴128家，活跃率68.8%。"
        "渠道带来签约收入¥2,450万，占总营收17.4%，同比增长42.3%。"
        "新发展合作伙伴23家，认证合作伙伴从45家增长至58家，增幅28.9%。"
        "合作伙伴平均产出从上季度¥16.8万提升至¥19.1万，提升13.7%。"
        "渠道返利支出¥367万，渠道净利润率为21.5%。"
        "在下一阶段，我们将继续完善渠道体系，扩大合作伙伴覆盖范围。"
        "我们期待通过渠道的力量，进一步提升市场覆盖率和业务规模。"
    ),
    "must_keep": ["186", "128", "68.8%", "¥2,450万", "17.4%", "42.3%", "28.9%", "¥16.8万", "¥19.1万", "13.7%", "¥367万", "21.5%"],
})

TEST_CASES.append({
    "id": "K07",
    "name": "售前方案团队效率",
    "context": "方案响应效率",
    "text": (
        "售前团队作为连接销售和产品的桥梁，在整个业务链条中发挥着关键作用。"
        "从售前工作的本质来看，它既需要深厚的技术功底，也需要出色的客户沟通能力。"
        "值得一提的是，随着业务规模的扩大，售前团队面临的工作量也在持续增长。"
        "需要说明的是，不同类型的项目对售前支持的需求存在很大差异。"
        "在日常工作中，售前团队需要处理大量的方案编写、技术交流和POC支持等任务。"
        "从团队管理的角度来看，如何合理分配资源是一个持续需要优化的课题。"
        "经过这段时间的运营实践，我们积累了一些有价值的经验和教训。"
        "关于人才培养方面，我们建立了系统性的培训机制和知识库。"
        "我们注意到，好的售前支持能够显著提升项目的win rate。"
        "从客户反馈来看，专业的技术方案展示对建立客户信任有很大帮助。"
        "另外在工具建设方面，我们也在不断完善方案模板库和自动化支撑工具。"
        "总的来说，售前能力是公司核心竞争力的重要组成部分。"
        "本季度售前团队共支持项目287个，方案输出平均响应时间从5.2天缩短至3.8天。"
        "售前支持的项目win rate为35.2%，高于无售前支持项目的18.6%。"
        "POC项目共执行42个，成功率为78.6%，平均POC周期为12.5天。"
        "方案复用率从上季度的45%提升至62%，团队人效提升37.8%。"
        "售前人均支持项目数为14.35个/季度，人均贡献签约金额¥298万。"
        "我们将继续提升售前团队的专业能力和工作效率，为业务增长提供有力支撑。"
    ),
    "must_keep": ["287", "5.2", "3.8", "35.2%", "18.6%", "78.6%", "12.5", "45%", "62%", "37.8%", "14.35", "¥298万"],
})

TEST_CASES.append({
    "id": "K08",
    "name": "客户成功季度复盘",
    "context": "客户健康度评估",
    "text": (
        "客户成功是SaaS业务可持续发展的基石，这一点已经成为行业共识。"
        "从方法论层面来看，客户成功管理需要将主动服务和被动响应有机结合起来。"
        "值得一提的是，我们在客户成功体系建设方面一直在进行探索和优化。"
        "需要说明的是，不同阶段的客户需要差异化的服务策略和资源配置。"
        "在实际运营中，客户成功经理需要密切关注客户的产品使用数据和业务动态。"
        "从长远来看，帮助客户实现业务目标才是客户成功的真正内涵。"
        "经过这段时间的积累，团队在客户运营方面形成了一套比较完善的方法和工具。"
        "关于客户分层管理，我们采用了基于价值和潜力的二维分类模型。"
        "我们注意到，早期干预对于防止客户流失有着显著的效果。"
        "从数据驱动的角度来看，健康度评分模型的准确性直接影响到工作效率。"
        "另外在客户社区建设方面，我们也取得了一些阶段性的进展。"
        "总的来说，客户成功是一项需要持续投入和精细化运营的工作。"
        "本季度客户健康度评估结果：绿色（健康）客户占比67.8%，黄色（需关注）22.4%，红色（高风险）9.8%。"
        "客户活跃度指标：月均登录DAU为12,450，WAU为28,600，MAU为45,200。"
        "功能采纳率TOP3：报表功能82.3%，工作流67.5%，API集成45.8%。"
        "客户续约提前率：提前90天续约占比35.6%，提前60天占比28.2%，临期续约占比36.2%。"
        "NPS季度均值为52分，较上季度提升4分，CSAT为4.3分（5分制）。"
        "我们将在下季度重点关注红色客户的挽留和黄色客户的转绿工作。"
    ),
    "must_keep": ["67.8%", "22.4%", "9.8%", "12,450", "28,600", "45,200", "82.3%", "67.5%", "45.8%", "35.6%", "28.2%", "36.2%", "4.3"],
})

TEST_CASES.append({
    "id": "K09",
    "name": "新产品上线销售反馈",
    "context": "新产品市场反应",
    "text": (
        "新产品的推出是公司产品矩阵拓展的重要里程碑，整个团队为此付出了很多努力。"
        "从产品策划到最终上线，经历了多轮的需求讨论、方案评审和市场验证。"
        "值得一提的是，在产品设计阶段我们充分参考了客户的反馈意见和竞品分析结果。"
        "需要说明的是，新产品的市场培育需要一个过程，不能期望一蹴而就。"
        "从用户体验的角度来看，我们在产品的易用性方面做了很多优化工作。"
        "在产品推广方面，市场和销售团队进行了密切配合，共同制定了Go-to-Market策略。"
        "经过前期的种子客户验证，产品的核心价值得到了初步的市场认可。"
        "关于定价策略，我们在充分调研市场后确定了目前的价格体系。"
        "我们注意到，客户在评估新产品时更加关注实际的业务价值而非技术特性。"
        "从销售团队的反馈来看，客户对新产品的接受度整体上是积极的。"
        "另外在培训赋能方面，我们为销售团队提供了系统的产品知识培训。"
        "总的来说，新产品的上线为我们打开了新的市场空间和增长机会。"
        "新产品上线45天数据：试用注册1,680家，付费转化率8.5%，付费客户143家。"
        "首月营收¥425万，平均客单价¥2.97万，用户7日留存率62.3%。"
        "NPS首测评分38分，主要扣分项为文档不完善和学习曲线陡峭。"
        "竞品替换率为23.4%，其中从A产品迁移占45%，从B产品迁移占31%。"
        "功能使用TOP3：智能推荐89.2%，数据看板76.8%，自动化工作流53.4%。"
        "我们对新产品的未来发展充满信心，将持续根据市场反馈进行迭代优化。"
    ),
    "must_keep": ["1,680", "8.5%", "143", "¥425万", "¥2.97万", "62.3%", "23.4%", "45%", "31%", "89.2%", "76.8%", "53.4%"],
})

TEST_CASES.append({
    "id": "K10",
    "name": "年度销售预测调整",
    "context": "收入预测修正",
    "text": (
        "销售预测是企业经营管理中非常重要的环节，它直接影响到资源配置和战略决策。"
        "从方法论角度来看，准确的销售预测需要结合历史数据、管线分析和市场趋势等多个因素。"
        "值得一提的是，我们在预测模型方面持续进行优化，引入了更多的数据源和算法。"
        "需要说明的是，宏观经济环境的不确定性给预测带来了额外的难度。"
        "在实际操作中，我们采用了Bottom-up和Top-down相结合的预测方法。"
        "从历史规律来看，Q4通常是全年业绩冲刺的关键时期，会有集中签约的特点。"
        "经过管理层的讨论和评估，我们认为有必要对年度预测进行一次修正。"
        "关于风险因素方面，我们也进行了充分的情景分析和压力测试。"
        "我们注意到，部分大型项目的决策周期有所延长，这对短期预测造成了一定影响。"
        "从pipeline覆盖率来看，目前的管线还需要进一步充实才能支撑全年目标。"
        "另外在预测准确度方面，上两个季度的预测偏差分别为8%和5%。"
        "总的来说，我们对全年完成目标保持审慎乐观的态度。"
        "年度修正预测：原年度目标¥5.2亿，上调至¥5.68亿，上调幅度9.2%。"
        "Q4预测收入¥1.85亿，其中确定性收入¥1.12亿（已签约+高概率），预期收入¥7,300万。"
        "当前pipeline总额¥4.8亿，覆盖率为2.59倍（目标3.0倍）。"
        "加权pipeline金额为¥1.92亿，Win Rate假设为28.5%。"
        "年度实际完成进度：前三季度累计¥3.83亿，完成率73.6%，需Q4完成¥1.85亿。"
        "预测置信度评估：乐观情景¥6.1亿，基准情景¥5.68亿，悲观情景¥5.2亿。"
        "我们将密切跟踪pipeline的动态变化，确保预测的及时更新和调整。"
    ),
    "must_keep": ["¥5.2亿", "¥5.68亿", "9.2%", "¥1.85亿", "¥1.12亿", "¥7,300万", "¥4.8亿", "2.59", "¥1.92亿", "28.5%", "¥3.83亿", "73.6%", "¥6.1亿"],
})


# ─── K11-K20: 英文技术文档 ──────────────────────────────

TEST_CASES.append({
    "id": "K11",
    "name": "Database Connection Pool Config",
    "context": "connection pool tuning",
    "text": (
        "In this section, we will discuss the general approach to configuring database connection pools in our platform. "
        "It is worth noting that connection pooling is a well-established pattern in enterprise applications and has been widely adopted across the industry. "
        "As mentioned earlier, the choice of pooling strategy depends on various factors including workload characteristics and infrastructure constraints. "
        "From our perspective, getting the connection pool configuration right is crucial for application performance and reliability. "
        "The team has spent considerable time analyzing different approaches and evaluating trade-offs between throughput and resource utilization. "
        "Generally speaking, the default settings work well for most use cases, but high-traffic applications may need custom tuning. "
        "We have observed that many performance issues in production environments can be traced back to suboptimal connection pool settings. "
        "It should be mentioned that our recommendations are based on extensive benchmarking and production experience. "
        "In the broader context of system design, connection pooling sits at the intersection of application logic and infrastructure management. "
        "The following section provides detailed guidance on how to approach connection pool configuration for different scenarios. "
        "Furthermore, we want to emphasize that monitoring is essential for validating configuration changes in production. "
        "The recommended configuration for production deployments is: max_pool_size=50, min_idle=10, max_idle_time=300s, connection_timeout=5000ms. "
        "For read-heavy workloads, set read_pool_size=80 and write_pool_size=20 with statement_cache_size=250. "
        "Health check interval should be set to health_check_interval=30s with validation_query=SELECT 1 and max_lifetime=1800s. "
        "Connection leak detection threshold is leak_detection_threshold=60s, and abandoned connection timeout is abandon_timeout=120s. "
        "Performance benchmarks show: at max_pool_size=50, throughput reaches 12,500 QPS with P99 latency of 45ms. "
        "At max_pool_size=100, throughput reaches 15,200 QPS but P99 degrades to 120ms due to lock contention. "
        "The optimal configuration for our standard 8C32G instances is max_pool_size=50 with connection_timeout=3000ms. "
        "Additional monitoring metrics to watch: pool.active_connections, pool.pending_requests, pool.timeout_total should all be exported to /metrics/pool endpoint. "
    ),
    "must_keep": ["max_pool_size=50", "min_idle=10", "300s", "5000ms", "read_pool_size=80", "write_pool_size=20", "statement_cache_size=250", "health_check_interval=30s", "1800s", "leak_detection_threshold=60s", "abandon_timeout=120s", "12,500", "15,200", "120ms", "8C32G", "connection_timeout=3000ms"],
})

TEST_CASES.append({
    "id": "K12",
    "name": "API Rate Limiting Documentation",
    "context": "rate limit configuration",
    "text": (
        "This document provides an overview of the rate limiting mechanisms implemented in our API gateway. "
        "It is important to understand that rate limiting serves multiple purposes in a distributed system architecture. "
        "From a high-level perspective, our approach to rate limiting has evolved significantly over the past several releases. "
        "As mentioned in previous discussions, the design philosophy prioritizes fairness while maintaining system stability. "
        "In practice, rate limiting configurations need to balance user experience with infrastructure protection. "
        "The engineering team has conducted extensive research on different algorithms and their trade-offs. "
        "It is worth noting that our implementation draws on industry best practices from companies operating at scale. "
        "Generally speaking, most API consumers will never encounter rate limits during normal usage patterns. "
        "From our experience, clear communication of limits through response headers helps developers build more resilient clients. "
        "In the broader ecosystem, rate limiting is just one component of a comprehensive API management strategy. "
        "We believe that transparent and well-documented limits contribute to a better developer experience. "
        "Furthermore, the monitoring and alerting around rate limiting helps us identify abuse patterns early. "
        "Rate limit tiers are configured as follows: Free tier at 100 requests/minute, Pro tier at 1,000 requests/minute, Enterprise at 10,000 requests/minute. "
        "Burst allowance is set to burst_multiplier=2.5x for short spikes lasting up to burst_window=10s. "
        "Token bucket parameters: bucket_size=500, refill_rate=100/s for Pro, bucket_size=5000, refill_rate=1000/s for Enterprise. "
        "Rate limit headers returned: X-RateLimit-Limit, X-RateLimit-Remaining, X-RateLimit-Reset with Unix timestamp. "
        "When limits are exceeded, the API returns HTTP 429 with retry_after header value between 1-60 seconds. "
        "Sliding window implementation uses Redis ZRANGEBYSCORE with TTL=3600s and precision of 1ms granularity. "
        "IP-based limiting applies at 50,000 requests/hour regardless of authentication status. "
    ),
    "must_keep": ["100", "1,000", "10,000", "burst_multiplier=2.5x", "burst_window=10s", "bucket_size=500", "refill_rate=100/s", "bucket_size=5000", "refill_rate=1000/s", "429", "1-60", "TTL=3600s", "50,000"],
})

TEST_CASES.append({
    "id": "K13",
    "name": "Kubernetes Deployment Specs",
    "context": "pod resource configuration",
    "text": (
        "This section covers the deployment specifications for our microservices running on Kubernetes. "
        "It is worth noting that container orchestration has become the standard approach for deploying modern applications. "
        "From an operational standpoint, getting resource requests and limits right is critical for cluster efficiency. "
        "As mentioned in our architecture decision records, we adopted Kubernetes to improve deployment reliability and scalability. "
        "The platform engineering team has established a set of best practices based on production experience. "
        "In general, we recommend starting with conservative resource allocations and adjusting based on actual usage patterns. "
        "It should be noted that over-provisioning wastes cluster resources while under-provisioning leads to OOM kills and throttling. "
        "From our monitoring data, we have observed that most services exhibit predictable resource patterns after initial warmup. "
        "The team continues to refine our approach to capacity planning as workload characteristics evolve. "
        "In the context of our multi-tenant architecture, proper resource isolation between services is particularly important. "
        "We believe that automated right-sizing recommendations will further improve our resource efficiency over time. "
        "Furthermore, the observability stack provides granular visibility into resource consumption at the pod level. "
        "Standard pod spec for API services: requests.cpu=500m, requests.memory=512Mi, limits.cpu=2000m, limits.memory=2Gi. "
        "Worker pods configuration: requests.cpu=1000m, requests.memory=1Gi, limits.cpu=4000m, limits.memory=4Gi. "
        "HPA settings: minReplicas=3, maxReplicas=20, targetCPUUtilization=70%, scaleUpPeriod=60s, scaleDownPeriod=300s. "
        "PDB configuration: minAvailable=2 for all critical services, maxUnavailable=1 for batch processors. "
        "Liveness probe: httpGet /health/live, initialDelaySeconds=30, periodSeconds=10, failureThreshold=3. "
        "Readiness probe: httpGet /health/ready, initialDelaySeconds=15, periodSeconds=5, successThreshold=2. "
        "Resource quotas per namespace: max CPU 64 cores, max memory 128Gi, max pods 200, max PVCs 50. "
    ),
    "must_keep": ["requests.cpu=500m", "requests.memory=512Mi", "limits.cpu=2000m", "limits.memory=2Gi", "requests.cpu=1000m", "requests.memory=1Gi", "limits.cpu=4000m", "limits.memory=4Gi", "minReplicas=3", "maxReplicas=20", "70%", "60s", "300s", "minAvailable=2", "maxUnavailable=1"],
})

TEST_CASES.append({
    "id": "K14",
    "name": "Caching Strategy Documentation",
    "context": "cache TTL and eviction",
    "text": (
        "In this document, we describe the caching strategy employed across our platform services. "
        "It is important to recognize that caching is a fundamental technique for improving application performance and reducing backend load. "
        "From a theoretical standpoint, caching introduces complexity around data consistency and cache invalidation. "
        "As the famous saying goes, cache invalidation is one of the hardest problems in computer science. "
        "Our team has iterated on the caching approach multiple times to find the right balance for our use cases. "
        "In practice, we have found that a multi-layer caching strategy provides the best combination of performance and consistency. "
        "It is worth noting that our approach differs slightly from textbook recommendations due to our specific workload patterns. "
        "Generally speaking, the read-heavy nature of our application makes it particularly well-suited for aggressive caching. "
        "From a cost perspective, effective caching also reduces our infrastructure expenses by lowering database and compute requirements. "
        "The following guidelines have been developed based on production performance data and incident post-mortems. "
        "We acknowledge that caching adds operational complexity, but the performance benefits outweigh the costs for our scale. "
        "Furthermore, our cache monitoring dashboards provide real-time visibility into hit rates and memory utilization. "
        "L1 cache (in-process): max_entries=10000, TTL=60s, eviction=LRU, memory_limit=256MB per instance. "
        "L2 cache (Redis cluster): TTL ranges from 300s to 3600s depending on entity type, max_memory=32GB, eviction_policy=allkeys-lfu. "
        "Hot data prefetch: warmup_interval=120s, prefetch_threshold=100 hits/min, max_prefetch_batch=500. "
        "Cache-aside pattern with write-through for user sessions: session_TTL=7200s, max_session_size=64KB. "
        "CDN cache for static assets: max_age=86400s, s-maxage=604800s, stale-while-revalidate=3600s. "
        "Cache hit rates targets: L1 >= 85%, L2 >= 92%, CDN >= 97%, overall >= 94%. "
        "Invalidation strategy: event-driven via message queue with max_propagation_delay=500ms, fallback TTL expiry. "
    ),
    "must_keep": ["max_entries=10000", "TTL=60s", "256MB", "300s", "3600s", "max_memory=32GB", "eviction_policy=allkeys-lfu", "warmup_interval=120s", "prefetch_threshold=100", "max_prefetch_batch=500", "session_TTL=7200s", "64KB", "max_age=86400s", "s-maxage=604800s", "85%", "92%", "97%", "94%", "max_propagation_delay=500ms"],
})

TEST_CASES.append({
    "id": "K15",
    "name": "Message Queue Configuration",
    "context": "Kafka consumer settings",
    "text": (
        "This section documents the message queue configuration for our event-driven architecture. "
        "It is worth noting that event-driven systems have become increasingly popular for building scalable and decoupled architectures. "
        "From a design perspective, our message queue setup reflects the specific requirements of our business domain. "
        "As mentioned in our architecture documentation, we selected Apache Kafka as our primary message broker. "
        "The choice was made after careful evaluation of multiple options including RabbitMQ and Amazon SQS. "
        "In practice, operating Kafka at scale requires attention to many configuration parameters and operational procedures. "
        "It should be noted that our configuration has been refined through several iterations based on production behavior. "
        "From our experience, consumer group management is one of the most common sources of operational issues. "
        "Generally speaking, the default Kafka settings are not suitable for production workloads without customization. "
        "In the broader context, proper message queue configuration is essential for maintaining data consistency and processing guarantees. "
        "We believe that documented configuration standards help new team members quickly understand our infrastructure decisions. "
        "Furthermore, the alerting rules around consumer lag help us detect processing bottlenecks before they impact end users. "
        "Kafka broker config: num.partitions=12, replication.factor=3, min.insync.replicas=2, log.retention.hours=168. "
        "Producer settings: batch.size=65536, linger.ms=10, buffer.memory=33554432, max.request.size=10485760, acks=all. "
        "Consumer settings: max.poll.records=500, max.poll.interval.ms=300000, session.timeout.ms=30000, heartbeat.interval.ms=10000. "
        "Topic-specific config for order-events: partitions=24, retention.ms=604800000, max.message.bytes=5242880. "
        "Consumer lag alerting: warning at lag > 10000, critical at lag > 50000, measured per partition. "
        "Dead letter queue: max_retries=5, retry_backoff=exponential starting at 1000ms, DLQ retention=30 days. "
        "Throughput benchmarks: sustained 85,000 messages/sec write, 120,000 messages/sec read on 6-broker cluster. "
    ),
    "must_keep": ["num.partitions=12", "replication.factor=3", "min.insync.replicas=2", "log.retention.hours=168", "batch.size=65536", "linger.ms=10", "max.poll.records=500", "max.poll.interval.ms=300000", "session.timeout.ms=30000", "heartbeat.interval.ms=10000", "partitions=24", "max_retries=5", "1000ms", "85,000", "120,000"],
})


TEST_CASES.append({
    "id": "K16",
    "name": "Logging and Observability Setup",
    "context": "log retention and alerting",
    "text": (
        "This document outlines our observability stack configuration and logging best practices. "
        "It is important to understand that observability encompasses logging, metrics, and tracing as complementary signals. "
        "From a philosophical standpoint, good observability enables teams to ask arbitrary questions about system behavior. "
        "As mentioned in our platform guidelines, structured logging is mandatory for all production services. "
        "The observability team has invested significant effort in building a unified platform that serves all engineering teams. "
        "In practice, the challenge lies in balancing comprehensive data collection with storage costs and query performance. "
        "It is worth noting that our logging volume has grown substantially as the platform scales. "
        "From our operational experience, most production incidents can be diagnosed faster with proper observability in place. "
        "Generally speaking, the three pillars of observability work best when they are correlated through trace IDs. "
        "In the broader industry context, observability has evolved from simple log aggregation to sophisticated data platforms. "
        "We recognize that alert fatigue is a real problem and strive to maintain high signal-to-noise ratio in our alerting. "
        "Furthermore, the cost optimization of our observability infrastructure is an ongoing concern given data volumes. "
        "Log levels and retention: DEBUG retained for 24h, INFO for 7 days, WARN for 30 days, ERROR for 90 days. "
        "Storage allocation: hot tier max_size=2TB with SSD, warm tier max_size=10TB with HDD, cold tier on S3 unlimited retention. "
        "Ingestion rate limit: max 50,000 events/sec per service, global cap at 2,000,000 events/sec. "
        "Alert thresholds: error_rate > 1% triggers P2, error_rate > 5% triggers P1, latency_p99 > 2000ms triggers P2. "
        "Trace sampling: 100% for errors, 10% for successful requests, adaptive_sampling_target=1000 traces/min. "
        "Metric scrape interval: 15s for critical services, 60s for batch jobs, cardinality_limit=10000 per metric. "
        "Dashboard SLO: data freshness < 30s for real-time views, < 5min for aggregate dashboards. "
        "Cost allocation: logging $0.50/GB ingested, metrics $0.10/1000 series/month, traces $2.00/million spans. "
    ),
    "must_keep": ["24h", "7 days", "30 days", "90 days", "max_size=2TB", "max_size=10TB", "50,000", "2,000,000", "1%", "5%", "2000ms", "100%", "10%", "adaptive_sampling_target=1000", "15s", "60s", "cardinality_limit=10000", "$0.50", "$0.10", "$2.00"],
})

TEST_CASES.append({
    "id": "K17",
    "name": "CI/CD Pipeline Configuration",
    "context": "build and deploy settings",
    "text": (
        "This document describes the CI/CD pipeline configuration used for our application deployments. "
        "It is worth noting that continuous integration and deployment practices are fundamental to modern software development. "
        "From our team's perspective, a well-configured pipeline significantly reduces deployment risk and developer friction. "
        "As mentioned in our engineering principles, we believe in shipping small increments frequently. "
        "The platform team has built and refined this pipeline over the course of multiple quarters. "
        "In practice, the pipeline handles everything from code validation through to production rollout. "
        "It should be noted that our approach emphasizes safety through progressive deployment strategies. "
        "From our incident history, most deployment-related outages were preventable with better validation stages. "
        "Generally speaking, the pipeline configuration aims to catch issues as early as possible in the delivery process. "
        "In the broader context of DevOps maturity, automated pipelines are a prerequisite for sustainable high-velocity delivery. "
        "We acknowledge that pipeline maintenance itself requires ongoing investment and is never truly complete. "
        "Furthermore, developer experience in interacting with the pipeline is something we continuously try to improve. "
        "Build stage: timeout=15min, parallel_jobs=4, cache_key=dependencies-v2, artifact_retention=7days. "
        "Test stage: unit_test_timeout=10min, integration_test_timeout=20min, coverage_threshold=80%, flaky_test_retries=2. "
        "Security scan: SAST timeout=8min, dependency_check with CVE severity >= HIGH blocks merge, container_scan on every build. "
        "Deployment strategy: canary with initial_weight=5%, promotion_interval=10min, full_rollout after 3 successful intervals. "
        "Rollback trigger: error_rate > 2% OR latency_p95 > 1500ms OR crash_rate > 0.1% within observation_window=5min. "
        "Environment promotion: staging auto-deploy on merge, production requires approval + min_staging_soak=2h. "
        "Pipeline metrics: median_build_time=8.2min, deployment_frequency=12/day, MTTR=23min, change_failure_rate=4.2%. "
    ),
    "must_keep": ["timeout=15min", "parallel_jobs=4", "artifact_retention=7days", "unit_test_timeout=10min", "integration_test_timeout=20min", "coverage_threshold=80%", "flaky_test_retries=2", "timeout=8min", "initial_weight=5%", "promotion_interval=10min", "2%", "1500ms", "0.1%", "observation_window=5min", "min_staging_soak=2h", "8.2min", "23min", "4.2%"],
})

TEST_CASES.append({
    "id": "K18",
    "name": "Authentication Token Management",
    "context": "JWT token lifecycle",
    "text": (
        "This document covers the token management approach used in our authentication and authorization system. "
        "It is important to understand that token-based authentication has become the dominant pattern for modern APIs. "
        "From a security standpoint, proper token lifecycle management is critical to preventing unauthorized access. "
        "As mentioned in our security architecture review, we follow OAuth 2.0 and OpenID Connect standards. "
        "The security engineering team has designed the token system to balance security requirements with user experience. "
        "In practice, token management involves careful consideration of validity periods, rotation policies, and storage mechanisms. "
        "It is worth noting that our approach has been validated through multiple security audits and penetration tests. "
        "From our operational data, token-related issues account for a significant portion of support tickets. "
        "Generally speaking, shorter token lifetimes improve security but increase the frequency of refresh operations. "
        "In the broader context of zero-trust architecture, token validation at every service boundary is essential. "
        "We believe that transparent token handling in our SDKs reduces the burden on application developers. "
        "Furthermore, the token revocation mechanism ensures compromised tokens can be invalidated immediately. "
        "Access token: algorithm=RS256, expiry=900s (15min), issuer=https://auth.platform.io, max_payload_size=4KB. "
        "Refresh token: expiry=604800s (7days), rotation=true, reuse_detection=true, max_refresh_count=168. "
        "ID token: expiry=3600s (1h), claims=[sub, email, name, org_id, roles], nonce_required=true. "
        "Token storage: access_token in memory only, refresh_token in HttpOnly cookie with SameSite=Strict, Secure=true. "
        "Key rotation: RSA-2048 keys rotated every 90 days, JWKS endpoint cache TTL=3600s, max_active_keys=3. "
        "Rate limiting on token endpoint: max 30 requests/minute per client_id, lockout after 10 failed attempts for 30min. "
        "Token introspection: cache_ttl=60s, max_batch_size=100, fallback to direct validation on cache miss. "
    ),
    "must_keep": ["RS256", "expiry=900s", "https://auth.platform.io", "4KB", "expiry=604800s", "max_refresh_count=168", "expiry=3600s", "SameSite=Strict", "RSA-2048", "90 days", "TTL=3600s", "max_active_keys=3", "30", "cache_ttl=60s", "max_batch_size=100"],
})

TEST_CASES.append({
    "id": "K19",
    "name": "Data Backup and Recovery",
    "context": "backup schedule and RPO",
    "text": (
        "This section documents our data backup and recovery procedures for production databases. "
        "It is worth noting that data protection is one of the most critical aspects of operating production systems. "
        "From a business continuity perspective, our backup strategy is designed to meet stringent recovery objectives. "
        "As mentioned in our compliance documentation, certain data retention requirements are mandated by regulatory frameworks. "
        "The infrastructure team has established comprehensive backup procedures that cover all production data stores. "
        "In practice, backup operations must be performed without impacting production performance. "
        "It should be noted that we regularly test our recovery procedures to ensure they work as expected. "
        "From our experience with past incidents, having reliable backups has been crucial for service restoration. "
        "Generally speaking, the cost of backup storage is a small fraction of the cost of data loss. "
        "In the broader context of disaster recovery, backups are just one component of a comprehensive resilience strategy. "
        "We recognize that backup verification is as important as the backup itself. "
        "Furthermore, encryption of backup data at rest and in transit is non-negotiable for security compliance. "
        "Primary database backup: full_backup every 24h at 02:00 UTC, incremental every 1h, WAL archiving continuous. "
        "RPO target: <= 5min for tier-1 services, <= 1h for tier-2, <= 24h for tier-3 (non-critical analytics). "
        "RTO target: <= 15min for tier-1, <= 1h for tier-2, <= 4h for tier-3. "
        "Backup retention: daily snapshots retained 30 days, weekly snapshots 90 days, monthly snapshots 365 days. "
        "Cross-region replication: async replication with max_lag=30s to DR region, failover_time < 60s. "
        "Backup encryption: AES-256-GCM at rest, TLS 1.3 in transit, key rotation every 180 days. "
        "Recovery testing: full DR drill quarterly, automated restore test weekly with validation_timeout=30min. "
        "Storage costs: primary backups $0.023/GB/month, cross-region $0.035/GB/month, archive tier $0.004/GB/month. "
    ),
    "must_keep": ["24h", "02:00", "5min", "15min", "30 days", "90 days", "365 days", "max_lag=30s", "60s", "AES-256-GCM", "180 days", "validation_timeout=30min", "$0.023", "$0.035", "$0.004"],
})

TEST_CASES.append({
    "id": "K20",
    "name": "Search Engine Index Configuration",
    "context": "Elasticsearch index settings",
    "text": (
        "This document details the search engine configuration for our product search and full-text search capabilities. "
        "It is important to recognize that search quality directly impacts user experience and business conversion metrics. "
        "From a technical standpoint, our search infrastructure is built on Elasticsearch with custom analyzers and scoring. "
        "As mentioned in our product requirements, sub-second search latency is a hard requirement for user-facing queries. "
        "The search team has invested considerable effort in tuning relevance and performance over multiple iterations. "
        "In practice, search configuration involves balancing relevance, performance, and index size trade-offs. "
        "It is worth noting that our index design has evolved significantly as the data volume has grown. "
        "From our A/B testing results, improved search relevance directly correlates with higher conversion rates. "
        "Generally speaking, the standard Elasticsearch defaults are rarely optimal for domain-specific search use cases. "
        "In the broader context of information retrieval, our approach combines traditional BM25 with vector similarity. "
        "We believe that continuous relevance tuning based on user behavior signals is essential for search quality. "
        "Furthermore, the monitoring of search metrics helps us detect quality regressions quickly after index changes. "
        "Index settings: number_of_shards=6, number_of_replicas=2, refresh_interval=5s, max_result_window=10000. "
        "Analysis: custom analyzer with icu_tokenizer, synonym_filter with 2,500 entries, edge_ngram min=2 max=15. "
        "Mapping: nested fields limit=50, total_fields_limit=2000, depth_limit=20, dynamic=strict. "
        "Query config: BM25 with k1=1.2, b=0.75, combined with vector search using cosine similarity, vector_dims=768. "
        "Performance targets: p50 < 50ms, p95 < 200ms, p99 < 500ms, max_concurrent_searches=200. "
        "Index lifecycle: hot phase 7 days, warm phase 30 days (force_merge to 1 segment), cold after 90 days, delete after 365 days. "
        "Bulk indexing: batch_size=5000, max_retries=3, backoff=exponential starting at 100ms, thread_pool_size=8. "
    ),
    "must_keep": ["number_of_shards=6", "number_of_replicas=2", "refresh_interval=5s", "max_result_window=10000", "2,500", "min=2", "max=15", "total_fields_limit=2000", "k1=1.2", "b=0.75", "vector_dims=768", "50ms", "200ms", "500ms", "max_concurrent_searches=200", "batch_size=5000", "100ms", "thread_pool_size=8"],
})


# ─── K21-K30: 中英混合 Agent 推理过程 ──────────────────────

TEST_CASES.append({
    "id": "K21",
    "name": "Agent数据查询推理链",
    "context": "查询超时原因分析",
    "text": (
        "让我来分析一下这个查询请求为什么会失败。首先从用户的问题入手，他想要获取上个月的销售数据汇总。"
        "从整体的分析框架来看，查询失败可能的原因有很多，需要逐一排查。"
        "我先检查了用户的权限配置，确认其具有read:analytics(org_level)权限，所以权限方面不存在问题。"
        "值得注意的是，在排查过程中我考虑了多种可能性，包括网络问题、配置错误和资源限制等。"
        "从经验来看，类似的问题在之前也出现过，通常与系统负载有关。"
        "接下来我需要分析具体的错误上下文，看看是哪个环节出了问题。"
        "经过仔细的思考和推导，我认为问题很可能出在数据库查询层面。"
        "在进一步调查之前，让我先整理一下已知的信息和线索。"
        "从逻辑推理的角度来看，如果权限没有问题，那问题一定在查询执行阶段。"
        "我注意到系统日志中有一些相关的信息，需要结合起来分析。"
        "综合各方面的情况来看，我的初步判断是与数据库性能有关。"
        "查询执行路径：API Gateway -> QueryService -> PostgreSQL，在第三步返回了error_code=QUERY_TIMEOUT。"
        "具体错误：SQL查询sales_summary表，WHERE条件month='2024-03' AND org_id='ORG_8842'，执行时间超过30s timeout。"
        "根因定位：sales_summary表记录数达到1,850万行，month字段缺少索引，导致full table scan。"
        "建议方案：1) 立即添加索引CREATE INDEX idx_month ON sales_summary(month, org_id)，预计将查询降至200ms以内。"
        "2) 长期方案：引入物化视图materialized_view刷新周期为每日02:00，查询延迟可降至50ms。"
        "当前已通过添加LIMIT 10000临时修复，返回了部分数据：总销售额$2.84M，订单数12,456笔，平均客单价$228。"
        "总的来说，这个问题的根因比较明确，解决方案也相对straightforward。"
    ),
    "must_keep": ["read:analytics(org_level)", "error_code=QUERY_TIMEOUT", "2024-03", "ORG_8842", "30s", "1,850万", "200ms", "02:00", "50ms", "10000", "$2.84M", "12,456", "$228"],
})

TEST_CASES.append({
    "id": "K22",
    "name": "Agent权限校验推理",
    "context": "RBAC权限判断过程",
    "text": (
        "现在需要判断用户是否有权限执行这个操作。让我按照系统的权限模型逐步分析。"
        "从安全设计的角度来看，权限校验是系统中最关键的环节之一，不容有丝毫的疏忽。"
        "在开始具体分析之前，让我先回顾一下我们平台的权限架构设计理念。"
        "值得一提的是，RBAC模型在企业级应用中被广泛采用，是业界公认的最佳实践。"
        "从用户体验的角度来看，权限设计需要在安全性和易用性之间找到平衡。"
        "我注意到这个请求涉及到跨部门的数据访问，这增加了校验的复杂度。"
        "经过仔细的思考，我决定从用户角色开始逐层分析权限继承关系。"
        "在权限体系中，每个角色都有明确定义的权限边界，这是系统设计的基础原则。"
        "从系统架构的层面来看，权限校验需要在多个层级进行，包括API网关和服务层。"
        "另外还需要考虑数据权限的范围，即用户能看到哪些组织单元的数据。"
        "总的来说，权限判断是一个需要严谨逻辑推理的过程。"
        "用户身份：user_id=U_29384，角色为DepartmentAdmin，所属部门dept_id=D_005。"
        "请求操作：尝试调用DELETE /api/v2/users/U_10042，目标用户属于dept_id=D_007。"
        "权限规则链：DepartmentAdmin拥有manage:users(department)权限，scope限制为本部门。"
        "判断结果：DENIED。原因：操作目标U_10042属于D_007，而请求者管辖范围仅限D_005。"
        "如需跨部门操作，需要OrgAdmin角色或显式授权cross_dept_access=true（当前为false）。"
        "审计记录：access_denied event已写入audit_log，trace_id=TR_84729fba，时间戳2024-03-15T14:23:07Z。"
        "建议反馈给用户：权限不足，请联系OrgAdmin或在IAM控制台申请临时提权grant_type=temporary,duration=24h。"
    ),
    "must_keep": ["U_29384", "DepartmentAdmin", "D_005", "DELETE", "/api/v2/users/U_10042", "D_007", "manage:users(department)", "cross_dept_access=true", "TR_84729fba", "2024-03-15T14:23:07Z", "grant_type=temporary", "duration=24h"],
})

TEST_CASES.append({
    "id": "K23",
    "name": "Agent工具选择推理",
    "context": "选择合适的工具执行任务",
    "text": (
        "用户提出了一个需求，我需要判断应该使用哪个工具来完成这个任务。"
        "从方法论的角度来看，工具选择是Agent推理过程中非常关键的一步。"
        "在做出决策之前，让我先仔细理解用户的意图和预期结果。"
        "值得一提的是，我们的工具集覆盖了多种场景，每个工具都有其适用的上下文。"
        "从过去的经验来看，选择正确的工具能够极大地提升任务完成的效率和质量。"
        "我需要综合考虑多个因素，包括数据来源、操作类型和输出格式等。"
        "经过初步分析，这个请求涉及到数据检索和格式化两个步骤。"
        "在我的工具集中，有几个候选工具可能适合这个场景，需要进一步评估。"
        "从效率的角度来看，我应该选择能够一步完成任务的工具，避免不必要的中间步骤。"
        "另外还需要考虑工具的调用限制和资源消耗，选择最经济的方案。"
        "总的来说，工具选择需要在功能匹配度和执行效率之间做出权衡。"
        "让我回顾一下这个任务的核心需求：从knowledge_base中检索相关文档并生成摘要。"
        "可用工具评估：search_knowledge(relevance_score >= 0.85) -> summarize_text(max_tokens=500) 组合最优。"
        "备选方案：直接使用RAG_query工具，但其max_context_window=4096 tokens可能不够覆盖所有相关文档。"
        "决策：选择search_knowledge + summarize_text组合，预计耗时2.3s，token消耗约1,200 tokens。"
        "执行参数：search_knowledge(query=用户问题, top_k=5, threshold=0.85, collection_id=KB_2024_03)。"
        "summarize_text(input=检索结果, style=concise, max_length=500, language=zh-CN)。"
        "风险评估：如果search返回结果< 3条，需要降低threshold到0.70并扩大top_k到10。"
    ),
    "must_keep": ["relevance_score >= 0.85", "max_tokens=500", "max_context_window=4096", "2.3s", "1,200", "top_k=5", "threshold=0.85", "KB_2024_03", "max_length=500", "0.70", "top_k到10"],
})

TEST_CASES.append({
    "id": "K24",
    "name": "Agent多步骤任务规划",
    "context": "复杂任务拆解",
    "text": (
        "用户请求创建一份包含数据分析的月度报告，这是一个多步骤的复合任务。"
        "从任务管理的角度来看，复杂任务需要被合理地拆解为可执行的子步骤。"
        "在规划执行路径之前，让我先评估整体的工作量和可能遇到的依赖关系。"
        "值得一提的是，良好的任务规划能够避免重复工作和资源浪费。"
        "从系统设计的角度来看，任务之间的依赖关系决定了执行的先后顺序。"
        "我需要考虑每个步骤的输入输出，确保数据在步骤之间正确传递。"
        "经过初步评估，这个任务大约需要4-5个步骤才能完成。"
        "在实际执行中，可能会遇到一些异常情况需要错误处理和重试。"
        "从整体效率来看，并行化一些独立步骤可以减少总执行时间。"
        "另外还需要考虑中间结果的缓存策略，避免重复计算。"
        "总的来说，一个好的执行计划应该是清晰、可靠和高效的。"
        "让我来制定详细的执行计划和资源估算。"
        "任务拆解完成，共5步：Step1 数据获取(est. 3.5s) -> Step2 数据清洗(est. 1.2s) -> Step3 统计分析(est. 2.8s) -> Step4 图表生成(est. 4.1s) -> Step5 报告组装(est. 1.5s)。"
        "总预估时间：13.1s，token预算：input 8,500 tokens + output 3,200 tokens = 11,700 tokens total。"
        "并行优化：Step2和Step4的图表模板加载可并行，优化后总时间降至9.8s。"
        "资源依赖：data_source=CRM_DB(conn_pool=primary), chart_engine=v2.3, template_id=TPL_MONTHLY_001。"
        "错误策略：每步最多retry=3次，exponential_backoff起始interval=500ms，全链路timeout=60s。"
        "输出规格：PDF格式，max_pages=15，含6张图表，数据截止日期为2024-03-31。"
    ),
    "must_keep": ["3.5s", "1.2s", "2.8s", "4.1s", "1.5s", "13.1s", "8,500", "3,200", "11,700", "9.8s", "v2.3", "TPL_MONTHLY_001", "retry=3", "interval=500ms", "timeout=60s", "max_pages=15", "2024-03-31"],
})

TEST_CASES.append({
    "id": "K25",
    "name": "Agent上下文压缩决策",
    "context": "context window管理",
    "text": (
        "当前对话的上下文已经接近token限制，我需要决定如何进行压缩。"
        "从LLM应用的角度来看，上下文窗口管理是影响对话质量的关键因素。"
        "在做出压缩决策之前，让我先评估现有上下文中各部分的重要性。"
        "值得一提的是，过度压缩可能导致重要信息丢失，从而影响后续回答的质量。"
        "从信息论的角度来看，不同类型的信息具有不同的保留价值和冗余度。"
        "我需要仔细权衡哪些内容是后续对话中必须保留的，哪些可以安全地压缩或丢弃。"
        "经过分析，当前上下文中包含了大量的历史对话记录和中间推理过程。"
        "在实际操作中，通常可以保留结论而压缩推理过程来节省token。"
        "从用户体验的角度来看，压缩不应该影响对话的连贯性和上下文理解。"
        "另外还需要考虑不同类型信息的时效性，较早的信息可能已经不再相关。"
        "总的来说，上下文压缩是一个需要精细化管理的优化问题。"
        "让我评估当前的具体状况，并制定压缩方案。"
        "当前状态：total_tokens=14,850/16,384(使用率90.6%)，需要释放至少4,000 tokens的空间。"
        "上下文分布：system_prompt占2,048 tokens，对话历史占9,200 tokens，工具结果占3,602 tokens。"
        "压缩策略：对话历史中turn_1到turn_5(共5,400 tokens)可压缩为摘要，预计压缩后为1,200 tokens。"
        "保留规则：最近3轮对话(turn_6-turn_8)完整保留，所有包含数据结果的工具输出完整保留。"
        "压缩后预计：total_tokens=10,650/16,384(使用率65.0%)，释放空间5,734 tokens。"
        "压缩质量保障：保留所有entity(数字/日期/配置)，recall_target=99%，仅压缩过渡性描述文本。"
        "执行方式：调用LightKompress(target_ratio=0.22, bias=1.2)处理turn_1到turn_5的内容。"
    ),
    "must_keep": ["14,850", "16,384", "90.6%", "4,000", "2,048", "9,200", "3,602", "5,400", "1,200", "10,650", "65.0%", "5,734", "99%", "target_ratio=0.22", "bias=1.2"],
})


TEST_CASES.append({
    "id": "K26",
    "name": "Agent错误恢复推理",
    "context": "API调用失败后的恢复",
    "text": (
        "在执行任务的过程中遇到了一个API调用失败，我需要分析原因并决定恢复策略。"
        "从系统可靠性的角度来看，错误处理是Agent健壮性的重要体现。"
        "在实际运行中，各种临时性错误是不可避免的，关键在于如何优雅地处理它们。"
        "值得一提的是，不同类型的错误需要不同的恢复策略。"
        "从最佳实践来看，重试机制是处理临时错误的标准方案。"
        "我需要判断这次失败是暂时性的还是永久性的，这决定了下一步的行动。"
        "经过分析错误响应的内容，我可以大致判断出问题的性质。"
        "在制定恢复方案时，我还需要考虑幂等性和副作用的问题。"
        "从用户体验的角度来看，透明的错误处理和清晰的反馈非常重要。"
        "另外还需要注意重试风暴的问题，避免对下游服务造成额外压力。"
        "总的来说，一个好的错误恢复机制应该是自动化的、有边界的和可观测的。"
        "让我具体分析这次失败并制定恢复计划。"
        "失败详情：POST https://api.service.io/v3/analytics/query 返回HTTP 503 Service Unavailable。"
        "响应头显示：Retry-After: 30, X-RateLimit-Remaining: 0, X-Request-ID: req_7f3a9b2c。"
        "错误分析：503+Retry-After表明是服务端限流，非永久性错误，30秒后可重试。"
        "恢复策略：等待30s后重试，采用exponential_backoff(base=30s, factor=2, max_retries=3, jitter=5s)。"
        "第1次重试：T+30s，如果仍然503则第2次重试：T+65s，第3次：T+135s，超过则降级。"
        "降级方案：使用cached_result(cache_key=analytics_2024_03, age=2h, freshness=stale)作为兜底。"
        "最终结果：第1次重试成功，在T+32s时获取到响应，latency=1.2s，data_points=8,450条。"
    ),
    "must_keep": ["https://api.service.io/v3/analytics/query", "503", "Retry-After: 30", "X-RateLimit-Remaining: 0", "req_7f3a9b2c", "base=30s", "factor=2", "max_retries=3", "jitter=5s", "T+30s", "T+65s", "T+135s", "cache_key=analytics_2024_03", "age=2h", "1.2s", "8,450"],
})

TEST_CASES.append({
    "id": "K27",
    "name": "Agent知识检索评估",
    "context": "RAG检索结果质量判断",
    "text": (
        "用户问了一个关于产品功能的问题，我从知识库中检索到了多条结果需要评估其相关性。"
        "从信息检索的理论来看，检索结果的质量直接影响最终回答的准确性。"
        "在评估检索结果之前，让我先明确用户问题的核心意图。"
        "值得一提的是，向量检索虽然能找到语义相似的内容，但不一定能精准匹配用户意图。"
        "从RAG系统的设计来看，检索和生成两个阶段都需要质量保障。"
        "我需要逐条评估检索到的文档，判断哪些是真正相关的，哪些是干扰项。"
        "经过初步浏览，部分结果看起来相关度不高，可能是向量空间中的近邻噪声。"
        "在实际应用中，设置合理的相关性阈值能够有效过滤低质量的检索结果。"
        "从答案生成的角度来看，传入过多不相关的上下文反而会降低回答质量。"
        "另外还需要考虑文档的时效性，过期的文档可能包含已废弃的信息。"
        "总的来说，检索结果的质量评估是保证RAG系统输出可靠的关键环节。"
        "让我对这次检索的具体结果进行评估和筛选。"
        "检索结果共8条，相关性评分分布：doc_001=0.94, doc_002=0.91, doc_003=0.88, doc_004=0.82, doc_005=0.76, doc_006=0.71, doc_007=0.65, doc_008=0.58。"
        "筛选阈值设定为threshold=0.80，保留TOP4文档，过滤掉doc_005到doc_008。"
        "保留文档总token数：doc_001(1,240 tokens) + doc_002(890 tokens) + doc_003(2,100 tokens) + doc_004(560 tokens) = 4,790 tokens。"
        "上下文窗口预算：max_context=6,000 tokens，当前使用率79.8%，在安全范围内。"
        "文档时效性检查：doc_001更新于2024-03-10，doc_003更新于2023-11-20(标记为potentially_stale)。"
        "最终决策：使用doc_001+doc_002+doc_004作为主要参考(freshness优先)，doc_003作为supplementary(降权0.7x)。"
        "预期回答质量评估：confidence=0.87，coverage=high，factual_risk=low。"
    ),
    "must_keep": ["doc_001=0.94", "doc_002=0.91", "doc_003=0.88", "doc_004=0.82", "doc_005=0.76", "doc_006=0.71", "doc_007=0.65", "doc_008=0.58", "threshold=0.80", "1,240", "890", "2,100", "560", "4,790", "max_context=6,000", "79.8%", "2024-03-10", "2023-11-20", "0.7x", "confidence=0.87"],
})

TEST_CASES.append({
    "id": "K28",
    "name": "Agent并行任务调度",
    "context": "多任务并行执行策略",
    "text": (
        "当前有多个子任务需要执行，我需要分析它们之间的依赖关系并决定调度策略。"
        "从并发编程的角度来看，合理的任务调度能够显著提升系统的整体吞吐量。"
        "在制定调度方案之前，让我先梳理各任务之间的数据依赖和资源竞争关系。"
        "值得一提的是，并行化不是万能的，任务间的依赖关系限制了可并行的程度。"
        "从Amdahl定律的角度来看，系统的加速比受限于不可并行化的部分。"
        "我需要识别关键路径上的任务，这些任务决定了整体执行时间的下限。"
        "经过分析，当前的任务集存在一些可以并行执行的独立子任务。"
        "在资源分配方面，需要考虑并发执行时的资源竞争和限流问题。"
        "从可靠性的角度来看，并行执行时的错误处理比串行执行更加复杂。"
        "另外还需要设计合并策略，将并行任务的结果正确地汇聚到一起。"
        "总的来说，并行调度需要在加速收益和复杂度成本之间找到平衡。"
        "让我具体分析这批任务的调度方案。"
        "任务集：TaskA(数据拉取,est=4.2s), TaskB(模型推理,est=6.8s), TaskC(格式转换,est=1.5s), TaskD(结果验证,est=2.1s), TaskE(通知发送,est=0.8s)。"
        "依赖图：TaskA -> TaskB -> TaskD -> TaskE, TaskA -> TaskC -> TaskD(TaskC可与TaskB并行)。"
        "关键路径：A->B->D->E, 总时间=4.2+6.8+2.1+0.8=13.9s(串行执行15.4s，并行优化节省1.5s=9.7%)。"
        "资源约束：concurrent_api_calls_max=5, memory_budget=2048MB, cpu_threads=4。"
        "调度方案：T0启动TaskA, T4.2s并行启动TaskB和TaskC, T11.0s启动TaskD, T13.1s启动TaskE。"
        "超时策略：per_task_timeout=30s, total_pipeline_timeout=60s, task_retry_budget=2 per task。"
        "监控指标：emit task_duration, task_status, pipeline_latency, concurrency_level到metrics endpoint /pipeline/stats。"
    ),
    "must_keep": ["4.2s", "6.8s", "1.5s", "2.1s", "0.8s", "13.9s", "15.4s", "9.7%", "concurrent_api_calls_max=5", "memory_budget=2048MB", "cpu_threads=4", "T4.2s", "T11.0s", "T13.1s", "per_task_timeout=30s", "total_pipeline_timeout=60s", "task_retry_budget=2", "/pipeline/stats"],
})

TEST_CASES.append({
    "id": "K29",
    "name": "Agent意图消歧推理",
    "context": "用户意图识别",
    "text": (
        "用户的输入比较模糊，我需要通过上下文线索来判断其真实意图。"
        "从自然语言理解的角度来看，用户表达往往是不完整的，需要结合上下文进行推断。"
        "在做出判断之前，让我先回顾对话历史中的相关线索。"
        "值得一提的是，意图消歧是对话系统中最具挑战性的问题之一。"
        "从认知科学的角度来看，人类在交流中大量依赖共同背景知识和语境。"
        "我需要综合考虑用户的角色、历史行为和当前对话上下文来判断意图。"
        "经过初步分析，这个请求可能对应多个不同的操作意图。"
        "在不确定的情况下，选择最高概率的意图并提供确认机制是比较安全的做法。"
        "从用户体验的角度来看，频繁地追问意图会降低交互效率。"
        "另外还需要考虑错误判断的成本，有些操作是不可逆的，需要更高的确认阈值。"
        "总的来说，意图消歧需要在效率和准确性之间做出权衡。"
        "让我分析这次具体的意图判断过程。"
        "用户输入：\"把上个月的数据导出来\"，对话历史显示前3轮都在讨论sales_report模块。"
        "候选意图评分：intent_export_sales=0.82, intent_export_analytics=0.64, intent_export_raw_data=0.41。"
        "消歧线索：(1)对话context关联sales_report, (2)用户角色=SalesManager, (3)上次导出也是sales数据。"
        "最终判断：选择intent_export_sales(confidence=0.82)，参数推断month=2024-02, format=xlsx, scope=department。"
        "确认策略：confidence > 0.80时直接执行，0.60-0.80时简短确认，< 0.60时展示选项。"
        "当前confidence=0.82 > threshold=0.80，执行导出操作，预计文件大小约2.4MB，耗时约5.2s。"
        "兜底机制：如果用户否定，回退到intent_export_analytics(confidence=0.64)，需要追问具体指标。"
    ),
    "must_keep": ["intent_export_sales=0.82", "intent_export_analytics=0.64", "intent_export_raw_data=0.41", "SalesManager", "confidence=0.82", "month=2024-02", "format=xlsx", "scope=department", "0.80", "0.60", "threshold=0.80", "2.4MB", "5.2s", "confidence=0.64"],
})

TEST_CASES.append({
    "id": "K30",
    "name": "Agent响应质量自评",
    "context": "回答质量评估",
    "text": (
        "在生成最终回答之前，我需要对回答的质量进行自我评估。"
        "从AI安全的角度来看，自评机制是确保输出可靠性的重要防线。"
        "在评估过程中，我会从多个维度来衡量回答的质量。"
        "值得一提的是，自评并不能完全替代人工审核，但可以过滤掉明显的问题。"
        "从产品设计的角度来看，输出质量直接影响用户对系统的信任度。"
        "我需要检查回答是否准确、完整、相关，并且没有包含有害内容。"
        "经过初步的质量检查，回答在大部分维度上表现良好。"
        "在实际运营中，我们会收集用户反馈来不断优化质量评估标准。"
        "从可解释性的角度来看，展示评估过程有助于建立用户信任。"
        "另外还需要关注回答的表达是否清晰易懂，避免过度使用专业术语。"
        "总的来说，质量自评是负责任AI系统的标配功能。"
        "让我对这次回答进行具体的评分和分析。"
        "质量评估维度(满分10分)：factual_accuracy=9.2, completeness=8.5, relevance=9.0, clarity=8.8, safety=10.0。"
        "综合得分：weighted_score=9.08(权重：accuracy=0.3, completeness=0.25, relevance=0.25, clarity=0.1, safety=0.1)。"
        "风险检查：hallucination_risk=0.05(低), bias_score=0.02(极低), toxicity=0.00。"
        "来源可追溯性：引用了3篇知识库文档，coverage_ratio=87.5%，未覆盖部分为基于推理的补充说明。"
        "置信度评估：high_confidence区间占比78.4%，medium_confidence占18.2%，low_confidence占3.4%。"
        "输出决策：综合得分9.08 > release_threshold=7.5，质量达标，允许输出。如得分在6.0-7.5区间需人工审核。"
        "改进建议：completeness可通过引入更多上下文文档提升，建议增加top_k从5到8。"
    ),
    "must_keep": ["factual_accuracy=9.2", "completeness=8.5", "relevance=9.0", "clarity=8.8", "safety=10.0", "weighted_score=9.08", "accuracy=0.3", "completeness=0.25", "relevance=0.25", "hallucination_risk=0.05", "bias_score=0.02", "toxicity=0.00", "coverage_ratio=87.5%", "78.4%", "18.2%", "3.4%", "release_threshold=7.5"],
})


# ─── K31-K40: 知识库/产品文档 ──────────────────────────────

TEST_CASES.append({
    "id": "K31",
    "name": "平台权限配置指南",
    "context": "如何配置角色权限",
    "text": (
        "本文档介绍平台权限管理系统的配置方法和最佳实践。"
        "权限管理是企业级应用中非常重要的一个功能模块，它关系到系统的安全性和数据的保密性。"
        "从设计理念来看，我们的权限系统采用了业界成熟的RBAC模型，并在此基础上进行了扩展。"
        "值得一提的是，合理的权限设计能够在保障安全的同时提供良好的用户体验。"
        "在实际使用过程中，管理员需要根据组织结构和业务需求来配置权限。"
        "需要说明的是，权限配置变更会立即生效，无需重启服务。"
        "从管理效率的角度来看，建议使用角色继承来减少重复配置的工作量。"
        "另外我们还提供了权限审计功能，帮助管理员追踪权限变更历史。"
        "在多租户环境下，不同租户的权限配置是完全隔离的，互不影响。"
        "从安全合规的角度来看，定期审查权限配置是一项推荐的最佳实践。"
        "总的来说，权限配置应该遵循最小权限原则，只授予必要的权限。"
        "配置步骤：1) 进入管理后台 /admin/rbac/roles，创建自定义角色。"
        "2) 角色模板可选：ViewOnly(4项权限)、Editor(12项权限)、Admin(28项权限)、SuperAdmin(全部52项权限)。"
        "3) 权限粒度：模块级(module:read)、对象级(object:crm:lead:edit)、字段级(field:salary:mask)。"
        "4) 数据范围：scope=self(仅自己)、scope=department(本部门)、scope=org(全组织)。"
        "5) API配置：POST /api/v1/roles/{role_id}/permissions, Content-Type: application/json。"
        "6) 生效策略：cache_ttl=300s, 权限变更后最长300秒全局生效，紧急模式可调用/admin/cache/flush即时生效。"
        "注意事项：单用户最多绑定max_roles=10个角色，单角色最多包含max_permissions=200项权限。"
        "审计日志保留audit_retention=180天，支持导出为CSV格式，最大单次导出max_export=50000条记录。"
    ),
    "must_keep": ["/admin/rbac/roles", "ViewOnly", "Editor", "Admin", "SuperAdmin", "module:read", "object:crm:lead:edit", "field:salary:mask", "scope=self", "scope=department", "scope=org", "/api/v1/roles/{role_id}/permissions", "cache_ttl=300s", "max_roles=10", "max_permissions=200", "audit_retention=180天", "max_export=50000"],
})

TEST_CASES.append({
    "id": "K32",
    "name": "数据集成API文档",
    "context": "对接外部系统",
    "text": (
        "本文档说明如何通过API将外部系统的数据集成到我们的平台中。"
        "数据集成是企业数字化建设中的核心诉求之一，不同系统之间的数据互通至关重要。"
        "从架构设计的角度来看，我们提供了多种集成方式以适应不同的技术场景。"
        "值得一提的是，我们的API设计遵循RESTful规范，对开发者比较友好。"
        "在集成过程中，数据的一致性和完整性是需要重点保障的方面。"
        "需要说明的是，所有API调用都需要通过身份认证才能执行。"
        "从性能优化的角度来看，批量操作比逐条操作要高效得多。"
        "另外我们还提供了Webhook机制，支持事件驱动的实时数据同步。"
        "在实际对接中，可能会遇到数据格式不一致的问题，需要做好映射和转换。"
        "从运维监控的角度来看，建议对集成任务配置告警以便及时发现异常。"
        "总的来说，良好的集成方案应该是可靠的、高效的和易于维护的。"
        "API基础信息：base_url=https://api.platform.io/v2, 认证方式Bearer Token, token有效期expiry=3600s。"
        "批量导入接口：POST /data/import/batch, 单次最大max_records=5000条，payload上限max_size=10MB。"
        "支持格式：JSON(推荐)、CSV、XML，字符编码UTF-8，日期格式ISO 8601。"
        "限流规则：rate_limit=1000 requests/min(标准版), 5000 requests/min(企业版), burst=2x。"
        "Webhook配置：POST /webhooks/subscribe, 支持事件类型：record.created, record.updated, record.deleted。"
        "重试机制：webhook_retry_count=5, retry_interval=exponential(30s,60s,120s,300s,600s), timeout=10s per delivery。"
        "数据映射：通过/mappings/create定义字段映射规则, 支持transform_functions: uppercase, trim, date_format, lookup。"
        "监控端点：GET /integration/health 返回 status, last_sync_time, pending_records, error_count。"
    ),
    "must_keep": ["https://api.platform.io/v2", "expiry=3600s", "/data/import/batch", "max_records=5000", "max_size=10MB", "rate_limit=1000", "5000", "burst=2x", "/webhooks/subscribe", "webhook_retry_count=5", "30s,60s,120s,300s,600s", "timeout=10s", "/mappings/create", "/integration/health"],
})

TEST_CASES.append({
    "id": "K33",
    "name": "工作流自动化配置",
    "context": "自动化规则设置",
    "text": (
        "本文档介绍如何配置平台的工作流自动化引擎来实现业务流程的自动执行。"
        "工作流自动化是提升企业运营效率的重要手段，能够减少人工操作和人为错误。"
        "从产品设计的角度来看，我们的工作流引擎支持可视化配置，降低了使用门槛。"
        "值得一提的是，复杂的业务逻辑可以通过组合简单的规则来实现。"
        "在实际应用中，工作流可以覆盖从简单的字段更新到复杂的多步骤审批流程。"
        "需要说明的是，工作流的执行是异步的，不会阻塞用户的操作。"
        "从可靠性的角度来看，工作流引擎提供了完善的错误处理和重试机制。"
        "另外我们还支持工作流的版本管理，方便进行变更追踪和回滚操作。"
        "在性能方面，工作流引擎经过优化能够处理大量并发触发。"
        "从安全角度来看，工作流的执行权限受到严格控制，遵循最小权限原则。"
        "总的来说，工作流自动化能够帮助企业实现流程标准化和效率提升。"
        "让我们来看具体的配置方法和参数。"
        "触发器类型：on_create, on_update, on_delete, on_schedule(cron), on_webhook, 共5种。"
        "配置入口：/admin/workflows/builder, 最大支持max_steps=50步/工作流, max_conditions=20/步骤。"
        "定时触发配置：cron表达式，最小粒度min_interval=5min, 时区支持timezone=UTC/Asia_Shanghai。"
        "条件节点：支持AND/OR/NOT逻辑组合，字段比较operators: eq, ne, gt, lt, gte, lte, contains, regex。"
        "动作类型：update_field, send_email, call_webhook, create_record, assign_user, send_notification共6种。"
        "执行限制：max_executions=10000/天/工作流, max_duration=300s/次, concurrent_limit=100。"
        "错误处理：on_error策略可选：retry(max=3,interval=60s), skip, abort, notify_admin。"
        "监控面板：/admin/workflows/monitor 展示 execution_count, success_rate, avg_duration, error_log。"
    ),
    "must_keep": ["on_create", "on_update", "on_delete", "on_schedule", "on_webhook", "/admin/workflows/builder", "max_steps=50", "max_conditions=20", "min_interval=5min", "timezone=UTC", "max_executions=10000", "max_duration=300s", "concurrent_limit=100", "max=3", "interval=60s", "/admin/workflows/monitor"],
})

TEST_CASES.append({
    "id": "K34",
    "name": "报表配置与导出",
    "context": "自定义报表",
    "text": (
        "本文档说明如何在平台中创建和配置自定义报表以满足不同的数据分析需求。"
        "报表功能是企业级应用中使用频率最高的功能之一，帮助用户快速获取业务洞察。"
        "从产品理念来看，我们希望让非技术用户也能轻松创建所需的报表。"
        "值得一提的是，我们的报表引擎支持丰富的图表类型和数据处理能力。"
        "在使用过程中，用户可以通过拖拽方式来构建报表，无需编写代码。"
        "需要说明的是，报表的性能与数据量和查询复杂度密切相关。"
        "从数据安全的角度来看，报表内容受数据权限控制，不同用户看到的数据范围不同。"
        "另外我们还支持报表的定时自动推送，减少人工操作的频率。"
        "在可视化方面，我们提供了多种主题和配色方案供用户选择。"
        "从协作的角度来看，报表可以被分享给团队成员并支持评论和标注。"
        "总的来说，一个好的报表工具应该既灵活又易用。"
        "报表创建入口：/analytics/reports/new, 支持图表类型：bar, line, pie, scatter, table, heatmap, funnel共7种。"
        "数据源配置：最多关联max_datasources=5个数据对象, 支持JOIN/UNION操作, 最大行数limit=100000。"
        "计算字段：支持公式types: SUM, AVG, COUNT, MAX, MIN, DISTINCT_COUNT, PERCENTILE, RUNNING_TOTAL共8种。"
        "过滤器：最多max_filters=15个条件, 支持动态参数${current_user}, ${today}, ${this_month}。"
        "导出格式：PDF(max_pages=100), Excel(max_rows=500000, max_cols=256), CSV(无限制), PNG(resolution=2x)。"
        "定时推送：schedule_types=daily/weekly/monthly, 收件人max_recipients=50, 格式支持email附件或链接。"
        "性能参数：查询超时query_timeout=120s, 缓存cache_ttl=600s, 刷新间隔min_refresh=60s。"
        "API接口：GET /api/v1/reports/{id}/data?page=1&size=100, 分页默认每页100条，最大1000条。"
    ),
    "must_keep": ["/analytics/reports/new", "max_datasources=5", "limit=100000", "max_filters=15", "${current_user}", "${today}", "${this_month}", "max_pages=100", "max_rows=500000", "max_cols=256", "resolution=2x", "max_recipients=50", "query_timeout=120s", "cache_ttl=600s", "min_refresh=60s", "/api/v1/reports/{id}/data"],
})

TEST_CASES.append({
    "id": "K35",
    "name": "字段配置与校验规则",
    "context": "自定义字段类型",
    "text": (
        "本文档介绍平台中自定义字段的配置方法和数据校验规则的设置。"
        "字段是数据模型的基本构成单元，合理的字段设计对系统的可扩展性至关重要。"
        "从元数据驱动的设计理念来看，字段的灵活配置是平台核心能力之一。"
        "值得一提的是，我们支持丰富的字段类型以满足不同业务场景的需求。"
        "在配置字段时，需要考虑数据类型、校验规则、显示格式和权限控制等多个方面。"
        "需要说明的是，字段配置变更对已有数据的影响需要谨慎评估。"
        "从性能优化的角度来看，合理的索引策略能够显著提升查询效率。"
        "另外我们还支持字段的条件显隐，可以根据其他字段的值来控制显示逻辑。"
        "在国际化方面，字段标签和提示信息支持多语言配置。"
        "从数据质量管理的角度来看，完善的校验规则是保障数据准确性的第一道防线。"
        "总的来说，字段配置需要在灵活性和规范性之间找到平衡。"
        "支持的字段类型(共15种)：text(max_length=4000), number(precision=10,scale=4), date, datetime, boolean, email, phone, url, select, multiselect, lookup, formula, attachment, rich_text, auto_number。"
        "校验规则配置API：POST /api/v1/fields/{field_id}/validations, 规则类型：required, unique, regex, range, custom_function。"
        "文本校验：min_length=0, max_length=4000, pattern支持正则, 内置模板：email, url, phone_cn, id_card。"
        "数字校验：min_value=-999999999, max_value=999999999, decimal_places=0-4, allow_negative=true/false。"
        "附件限制：max_file_size=50MB, max_files=10, allowed_types=[pdf,doc,docx,xls,xlsx,jpg,png], total_storage=5GB/org。"
        "自动编号：format支持prefix+date+sequence, 如PRJ-{YYYYMMDD}-{0001}, reset_cycle=yearly/monthly/never。"
        "索引策略：自动为unique字段和lookup字段创建索引, 自定义索引max_custom_indexes=20/对象。"
        "字段数量限制：每个对象max_fields=500, 其中formula字段max_formula=50, lookup字段max_lookup=30。"
    ),
    "must_keep": ["max_length=4000", "precision=10", "scale=4", "/api/v1/fields/{field_id}/validations", "min_length=0", "max_value=999999999", "decimal_places=0-4", "max_file_size=50MB", "max_files=10", "total_storage=5GB", "PRJ-{YYYYMMDD}-{0001}", "reset_cycle=yearly", "max_custom_indexes=20", "max_fields=500", "max_formula=50", "max_lookup=30"],
})

TEST_CASES.append({
    "id": "K36",
    "name": "消息通知配置文档",
    "context": "通知渠道设置",
    "text": (
        "本文档介绍平台消息通知系统的配置方法，包括多渠道通知和模板管理。"
        "消息通知是保持用户活跃度和信息传递效率的重要工具。"
        "从用户体验的角度来看，通知既不能太多打扰用户，也不能让用户错过重要信息。"
        "值得一提的是，我们的通知系统支持多种渠道，用户可以根据偏好进行配置。"
        "在设计通知策略时，需要考虑通知的紧急程度和用户的接收习惯。"
        "需要说明的是，不同渠道的通知在到达率和时效性上存在差异。"
        "从技术实现的角度来看，通知系统需要具备高可用性和良好的扩展性。"
        "另外我们还提供了通知的聚合和静默功能，避免短时间内大量通知轰炸用户。"
        "在模板管理方面，支持变量插入和条件逻辑来实现个性化通知内容。"
        "从合规角度来看，某些类型的通知需要获得用户明确同意才能发送。"
        "总的来说，好的通知设计应该在信息传递和用户体验之间找到平衡。"
        "通知渠道(共5种)：in_app(实时), email(延迟<30s), sms(延迟<10s), webhook(延迟<5s), push(延迟<3s)。"
        "配置接口：POST /api/v1/notifications/channels/{channel}/config, 每个渠道独立配置。"
        "频率限制：per_user_max=100条/天, per_channel_max=50条/天, quiet_hours=22:00-08:00可配置。"
        "模板管理：POST /api/v1/notifications/templates, 支持变量{{user_name}}, {{record_name}}, {{action}}。"
        "聚合规则：相同事件aggregate_window=5min内合并, 最多aggregate_max=20条合并为摘要。"
        "优先级：P1(立即推送所有渠道), P2(仅in_app+email), P3(仅in_app), 自定义routing_rules最多10条。"
        "送达追踪：delivery_status=sent/delivered/read/failed, 重试retry_policy=3次间隔60s。"
        "存储与清理：通知记录保留retention=90天, 已读通知30天后自动归档, 归档数据保留365天。"
    ),
    "must_keep": ["in_app", "email", "sms", "webhook", "push", "<30s", "<10s", "<5s", "<3s", "/api/v1/notifications/channels/{channel}/config", "per_user_max=100", "per_channel_max=50", "quiet_hours=22:00-08:00", "/api/v1/notifications/templates", "aggregate_window=5min", "aggregate_max=20", "routing_rules", "retry_policy=3", "retention=90天", "365天"],
})


TEST_CASES.append({
    "id": "K37",
    "name": "数据同步任务配置",
    "context": "ETL任务管理",
    "text": (
        "本文档说明如何配置数据同步任务以实现不同数据源之间的定期数据传输。"
        "数据同步是数据治理的重要组成部分，确保各系统间的数据保持一致。"
        "从数据工程的角度来看，可靠的数据同步机制是数据平台的基础设施。"
        "值得一提的是，我们的同步引擎支持增量同步和全量同步两种模式。"
        "在设计同步策略时，需要权衡实时性要求、系统负载和网络成本。"
        "需要说明的是，大规模数据同步可能对源端系统产生性能影响。"
        "从容错设计的角度来看，同步任务需要具备断点续传和自动恢复的能力。"
        "另外我们还支持数据转换和清洗操作，可以在同步过程中完成数据质量提升。"
        "在并行处理方面，大表可以按分区进行并行同步以提高吞吐量。"
        "从监控角度来看，同步任务的执行状态和数据质量指标需要实时可观测。"
        "总的来说，数据同步是一项需要精细化管理的日常运维工作。"
        "同步模式配置：full_sync(全量,适合<100万行表), incremental(增量,基于timestamp/CDC), streaming(实时,延迟<1s)。"
        "任务配置API：POST /api/v1/sync/tasks, 参数：source, target, mode, schedule, transform_rules。"
        "调度规则：cron格式, 最小间隔min_interval=1min(streaming除外), 并发任务max_concurrent=20。"
        "性能参数：batch_size=10000行/批, write_buffer=64MB, parallel_threads=8, network_timeout=120s。"
        "增量策略：基于updated_at字段, watermark_delay=5min(处理乱序数据), 或基于binlog position。"
        "容错配置：checkpoint_interval=30s, max_retries=5, retry_backoff=exponential(10s,20s,40s,80s,160s)。"
        "数据质量：校验规则null_check, type_check, range_check, 异常数据写入quarantine_table, 阈值error_threshold=1%。"
        "监控告警：GET /api/v1/sync/tasks/{id}/metrics, 指标包括rows_synced, lag_seconds, error_rate, throughput_rps。"
    ),
    "must_keep": ["full_sync", "incremental", "streaming", "<1s", "/api/v1/sync/tasks", "min_interval=1min", "max_concurrent=20", "batch_size=10000", "write_buffer=64MB", "parallel_threads=8", "network_timeout=120s", "watermark_delay=5min", "checkpoint_interval=30s", "max_retries=5", "10s,20s,40s,80s,160s", "error_threshold=1%"],
})

TEST_CASES.append({
    "id": "K38",
    "name": "审计日志查询指南",
    "context": "审计追踪配置",
    "text": (
        "本文档介绍平台审计日志系统的使用方法和查询技巧。"
        "审计日志是企业合规管理的核心工具，记录了系统中所有重要操作的详细信息。"
        "从安全管理的角度来看，完整的审计追踪是发现和调查安全事件的基础。"
        "值得一提的是，我们的审计日志系统经过了专业的安全审计，符合行业标准。"
        "在使用过程中，用户可以通过多种维度来检索和分析审计记录。"
        "需要说明的是，审计日志一经写入即不可修改，保证了数据的完整性和真实性。"
        "从性能角度来看，审计日志的写入采用异步方式，不影响业务操作的响应时间。"
        "另外我们还提供了审计报告的自动生成功能，支持定期合规审查。"
        "在数据量增长方面，系统会自动进行日志的归档和生命周期管理。"
        "从隐私保护的角度来看，敏感字段在审计日志中会进行脱敏处理。"
        "总的来说，审计日志是保障系统可信的重要基础设施。"
        "日志类型(共6种)：login_audit, data_change, permission_change, config_change, api_access, system_event。"
        "查询接口：GET /api/v1/audit/logs?actor=&action=&target=&from=&to=, 分页默认page_size=50, 最大1000。"
        "记录字段：timestamp(精确到ms), actor_id, actor_ip, action, target_type, target_id, changes(JSON diff), trace_id。"
        "存储策略：热数据retention_hot=90天(SSD), 温数据retention_warm=365天(HDD), 冷数据retention_cold=2555天(7年,S3归档)。"
        "查询性能：热数据查询<500ms(P95), 温数据<3s(P95), 冷数据需要restore, 耗时约5-12小时。"
        "告警规则：suspicious_login(异地登录)延迟<10s通知, bulk_delete(批量删除>100条)立即告警, privilege_escalation实时阻断。"
        "导出功能：POST /api/v1/audit/export, 格式支持JSON/CSV, 单次最大max_records=1000000, 异步生成download_link有效期24h。"
        "合规报告：GET /api/v1/audit/reports/compliance, 支持SOC2, ISO27001, GDPR模板, 生成周期monthly/quarterly。"
    ),
    "must_keep": ["login_audit", "data_change", "permission_change", "config_change", "api_access", "system_event", "/api/v1/audit/logs", "page_size=50", "retention_hot=90天", "retention_warm=365天", "retention_cold=2555天", "<500ms", "<3s", "5-12小时", "<10s", "/api/v1/audit/export", "max_records=1000000", "24h", "SOC2", "ISO27001", "GDPR"],
})

TEST_CASES.append({
    "id": "K39",
    "name": "多租户隔离配置",
    "context": "租户资源隔离",
    "text": (
        "本文档介绍平台的多租户架构设计和租户间资源隔离的配置方法。"
        "多租户是SaaS平台的核心架构特征，它允许多个租户共享同一套基础设施。"
        "从架构设计的角度来看，租户隔离需要在安全性和资源效率之间取得平衡。"
        "值得一提的是，我们的多租户实现已经在大规模生产环境中得到了充分验证。"
        "在实际运营中，不同规模的租户对隔离级别的需求可能不同。"
        "需要说明的是，更高级别的隔离通常意味着更高的基础设施成本。"
        "从安全合规的角度来看，数据隔离是最基本的要求，任何情况下都不能妥协。"
        "另外我们还支持自定义域名和品牌定制，提升租户的独立性体验。"
        "在性能隔离方面，我们通过资源配额和限流来防止个别租户影响整体服务质量。"
        "从运维角度来看，多租户环境下的问题排查需要更精细的可观测性支持。"
        "总的来说，多租户架构的设计需要考虑安全、性能、成本和可维护性多个维度。"
        "隔离级别(3种)：shared(共享表,tenant_id列隔离), dedicated_schema(独立schema), dedicated_db(独立数据库实例)。"
        "默认配额：max_users=500/租户, max_storage=100GB, max_api_calls=100000/天, max_objects=200。"
        "企业版配额：max_users=unlimited, max_storage=10TB, max_api_calls=5000000/天, max_objects=1000。"
        "资源限流：cpu_quota=4cores, memory_quota=16GB, network_bandwidth=1Gbps(shared)/10Gbps(dedicated)。"
        "数据加密：at_rest=AES-256, in_transit=TLS1.3, 企业版支持BYOK(Bring Your Own Key), key_rotation=90天。"
        "自定义域名：CNAME配置, SSL证书自动签发via Let's Encrypt, propagation_time<10min。"
        "租户创建API：POST /api/v1/tenants, 初始化耗时init_time<30s(shared), <5min(dedicated_schema), <15min(dedicated_db)。"
        "监控隔离：per_tenant_metrics=true, 独立Grafana dashboard, alert_routing按tenant_id分组。"
    ),
    "must_keep": ["shared", "dedicated_schema", "dedicated_db", "max_users=500", "max_storage=100GB", "max_api_calls=100000", "max_objects=200", "max_users=unlimited", "max_storage=10TB", "max_api_calls=5000000", "max_objects=1000", "cpu_quota=4cores", "memory_quota=16GB", "1Gbps", "10Gbps", "AES-256", "TLS1.3", "key_rotation=90天", "<10min", "/api/v1/tenants", "<30s", "<5min", "<15min"],
})

TEST_CASES.append({
    "id": "K40",
    "name": "API版本管理策略",
    "context": "API向后兼容",
    "text": (
        "本文档说明平台API的版本管理策略和向后兼容性保障措施。"
        "API版本管理是平台生态健康发展的重要保障，直接影响开发者体验。"
        "从长期维护的角度来看，清晰的版本策略能够减少breaking change对用户的影响。"
        "值得一提的是，我们参考了业界领先平台的版本管理实践来制定我们的策略。"
        "在API演进过程中，需要在引入新特性和保持向后兼容之间做出平衡。"
        "需要说明的是，我们对deprecated API提供充足的迁移窗口和工具支持。"
        "从开发者关系的角度来看，突然的breaking change是对信任的严重伤害。"
        "另外我们还提供了API变更的订阅通知，让开发者能够及时了解变更计划。"
        "在测试方面，我们为每个API版本维护完整的测试套件以确保质量。"
        "从文档管理的角度来看，每个版本都有独立的API文档和变更日志。"
        "总的来说，负责任的API版本管理是平台可信赖性的重要体现。"
        "版本格式：URL路径方式 /api/v{major}/, 当前最新版v3, 最旧支持版本v1(deprecated)。"
        "版本生命周期：active(全功能支持) -> deprecated(仅安全修复, 持续12个月) -> sunset(停服, 提前6个月通知)。"
        "兼容性规则：minor version不允许breaking change, 新增字段默认optional, 删除字段先deprecated=6个月。"
        "版本头部：Accept: application/vnd.platform.v3+json, 或URL参数?api_version=2024-03-01(日期版本)。"
        "Breaking change定义：删除端点, 删除必填字段, 修改字段类型, 修改错误码语义, 修改认证方式。"
        "迁移工具：GET /api/migration/guide?from=v1&to=v3 返回逐步迁移指南, 自动检查工具cli: platform-migrate check。"
        "废弃通知：deprecated端点返回header Sunset: Sat, 01 Mar 2025 00:00:00 GMT, Deprecation: true。"
        "监控指标：per_version_usage统计, v1占比15.3%, v2占比42.8%, v3占比41.9%, deprecated调用告警threshold=1000/天。"
    ),
    "must_keep": ["/api/v{major}/", "v3", "v1", "12个月", "6个月", "deprecated=6个月", "application/vnd.platform.v3+json", "api_version=2024-03-01", "/api/migration/guide", "platform-migrate", "2025", "15.3%", "42.8%", "41.9%", "threshold=1000"],
})


# ─── K41-K50: 错误诊断/运维报告 ──────────────────────────

TEST_CASES.append({
    "id": "K41",
    "name": "数据库连接池耗尽事故",
    "context": "连接池故障排查",
    "text": (
        "以下是一次数据库连接池耗尽导致服务不可用的事故报告。"
        "在我们的日常运维工作中，数据库相关的问题是最常见的故障类型之一。"
        "从系统可靠性的角度来看，连接池管理是数据库访问层最关键的配置。"
        "值得一提的是，这类问题往往在流量突增时才会暴露出来。"
        "在事故发生之前，系统的各项监控指标都处于正常范围内。"
        "需要说明的是，我们的监控覆盖了多个维度，但此次问题暴露了监控的盲点。"
        "从事后分析来看，问题的根因是一个特定场景下的连接泄漏bug。"
        "另外这次事故也暴露了我们在容量规划方面的不足，需要加强。"
        "在应急响应过程中，团队的协作和沟通还是比较高效的。"
        "从经验教训的角度来看，这次事故给我们提供了很多改进的方向。"
        "总的来说，通过这次事故我们对系统的薄弱环节有了更清晰的认识。"
        "事故时间线：2024-03-12T09:15:23Z 开始出现connection_timeout错误。"
        "09:18:45Z 错误率从0.1%飙升至23.5%，触发P1告警，影响用户数约8,200。"
        "09:22:00Z oncall工程师介入，确认PostgreSQL连接池active=200/max=200，wait_queue=1,247。"
        "09:28:33Z 定位根因：BatchExportService.java:142处存在连接泄漏，未调用connection.close()。"
        "09:35:00Z 临时修复：将max_pool_size从200提升至500，并重启受影响的3个pod。"
        "09:38:15Z 服务恢复正常，error_rate降至0.05%，总故障时间MTTR=22分52秒。"
        "影响范围：API成功率从99.95%降至76.5%，受影响请求数约42,300个。"
        "根因修复：PR #4892已合并，添加try-finally确保连接释放，增加leak_detection_threshold=30s。"
    ),
    "must_keep": ["2024-03-12T09:15:23Z", "0.1%", "23.5%", "8,200", "09:22:00Z", "active=200", "max=200", "wait_queue=1,247", "BatchExportService.java:142", "max_pool_size", "500", "09:38:15Z", "0.05%", "22分52秒", "99.95%", "76.5%", "42,300", "PR #4892", "leak_detection_threshold=30s"],
})

TEST_CASES.append({
    "id": "K42",
    "name": "缓存雪崩事故复盘",
    "context": "Redis故障分析",
    "text": (
        "以下是一次Redis缓存集群故障导致的缓存雪崩事故复盘报告。"
        "缓存系统在我们的架构中扮演着非常关键的角色，承担了大量的读请求。"
        "从系统设计的角度来看，缓存失效后的降级方案是必须提前规划的。"
        "值得一提的是，类似的问题在业界并不少见，很多大型系统都曾遭遇过缓存雪崩。"
        "在平时的运维中，我们对Redis集群的监控是比较全面的。"
        "需要说明的是，这次问题的触发条件比较特殊，是多个因素叠加的结果。"
        "从容灾设计的角度来看，单一故障不应该导致全局性的服务降级。"
        "另外这次事故也让我们重新审视了缓存架构的设计合理性。"
        "在恢复过程中，团队快速启动了预案并按流程执行。"
        "从长远来看，我们需要建立更完善的混沌工程实践来提前发现类似风险。"
        "总的来说，这是一次代价较高但收获很大的故障事件。"
        "事故时间线：2024-03-18T14:02:10Z Redis Cluster primary节点node-3(192.168.1.43:6379)发生OOM。"
        "14:02:15Z 自动failover启动，sentinel选举新primary耗时4.2s，期间丢失写入约2,100条。"
        "14:02:20Z 大量缓存key同时过期(TTL集中在14:00-14:05之间)，触发cache stampede。"
        "14:03:00Z 数据库QPS从正常的3,500骤增至28,000，超过连接池容量，开始拒绝连接。"
        "14:05:30Z 启动限流策略：API层面限制到5,000 QPS，返回HTTP 503并设置Retry-After: 10。"
        "14:08:45Z 手动执行cache warmup脚本，加载TOP 10000 hot keys，耗时3分15秒。"
        "14:12:00Z 系统恢复正常水位，数据库QPS降回3,800，缓存命中率从0%恢复至87.5%。"
        "影响统计：总故障时间9分50秒，SLA violation 0.018%，影响请求约156,000个，客户投诉12起。"
        "改进措施：1) TTL添加random jitter±300s 2) 热点key设置never_expire+后台刷新 3) 本地L1缓存兜底max_size=5000。"
    ),
    "must_keep": ["2024-03-18T14:02:10Z", "192.168.1.43:6379", "4.2s", "2,100", "14:02:20Z", "3,500", "28,000", "5,000", "503", "Retry-After: 10", "10000", "3分15秒", "3,800", "87.5%", "9分50秒", "0.018%", "156,000", "±300s", "max_size=5000"],
})

TEST_CASES.append({
    "id": "K43",
    "name": "API网关延迟飙升",
    "context": "网关性能问题",
    "text": (
        "以下是一次API网关延迟异常飙升的事故分析报告。"
        "API网关作为所有流量的入口，它的性能直接影响全局的用户体验。"
        "从微服务架构的角度来看，网关是整个系统的咽喉，任何问题都会被放大。"
        "值得一提的是，网关层面的性能优化一直是我们运维工作的重点。"
        "在日常监控中，我们对网关的各项指标设置了多级告警阈值。"
        "需要说明的是，延迟问题的排查通常需要结合链路追踪来定位具体环节。"
        "从流量分析的角度来看，某些特殊的请求模式可能会对网关产生不成比例的影响。"
        "另外网关的配置变更也是一个常见的故障引入点，需要严格的变更管理。"
        "在事故响应过程中，快速定位问题根因是缩短恢复时间的关键。"
        "从预防的角度来看，压力测试和容量规划能够帮助提前发现潜在问题。"
        "总的来说，网关的稳定性直接关系到整个平台的可用性。"
        "事故时间线：2024-03-20T11:30:15Z API网关P99延迟从正常的85ms飙升至2,340ms。"
        "11:30:45Z 告警触发，影响范围：全部API endpoint，错误率从0.02%上升到3.8%。"
        "11:32:00Z 排查发现：网关CPU使用率达到92%，正常水位为35-45%，GC频率从2次/min增至45次/min。"
        "11:34:20Z 定位原因：11:28:00Z部署的WAF规则更新引入了复杂正则(回溯深度>10000)，导致ReDoS。"
        "11:36:00Z 回滚WAF规则至上一版本(rule_version=v2.8.3 -> v2.8.2)，CPU立即降至38%。"
        "11:37:30Z P99延迟恢复至正常水位92ms，全链路恢复，总故障时间MTTR=7分15秒。"
        "影响量化：受影响请求约89,500个，其中timeout(>5s)请求12,300个，用户可感知率约15.2%。"
        "正则分析：问题规则pattern为(?:[a-z]+\\.)+[a-z]{2,}在特定输入下回溯次数达O(2^n)，n=input_length。"
        "修复方案：1) WAF规则灰度发布(先5%流量验证) 2) 添加regex_timeout=100ms限制 3) 禁止使用嵌套量词。"
    ),
    "must_keep": ["2024-03-20T11:30:15Z", "85ms", "2,340ms", "0.02%", "3.8%", "92%", "35-45%", "45次/min", "11:28:00Z", "10000", "v2.8.3", "v2.8.2", "38%", "92ms", "7分15秒", "89,500", "12,300", "15.2%", "regex_timeout=100ms"],
})

TEST_CASES.append({
    "id": "K44",
    "name": "磁盘空间告警处理",
    "context": "存储容量管理",
    "text": (
        "以下是一次磁盘空间不足告警的处理过程记录。"
        "存储容量管理是运维工作中需要持续关注的基础性工作。"
        "从系统可靠性的角度来看，磁盘空间耗尽会导致服务完全不可用。"
        "值得一提的是，我们的监控系统在磁盘使用率达到阈值时会自动触发告警。"
        "在日常运维中，定期的存储审计和清理是必不可少的。"
        "需要说明的是，不同服务对存储的需求和增长模式各有不同。"
        "从成本优化的角度来看，及时清理无用数据能够有效控制存储成本。"
        "另外自动化的存储生命周期管理可以减少人工干预的频率。"
        "在紧急情况下，需要快速识别和清理占用空间最大的文件或目录。"
        "从容量规划的角度来看，基于历史增长趋势的预测能够帮助提前扩容。"
        "总的来说，良好的存储管理需要监控、预警和自动化三管齐下。"
        "告警信息：2024-03-22T03:45:00Z prod-db-01(10.0.1.25) /data分区使用率达到92.3%，剩余空间48.2GB/620GB。"
        "空间分析：PostgreSQL data目录占用435GB，WAL日志占用89GB，临时文件占用38GB。"
        "WAL堆积原因：replica-02(10.0.1.27)网络中断导致WAL无法发送，堆积时间约18小时。"
        "即时操作：1) 手动清理>7天的临时文件，释放空间28.5GB 2) 压缩归档旧WAL释放34GB。"
        "03:52:00Z 操作完成，磁盘使用率降至82.1%，剩余空间110.7GB，告警自动解除。"
        "replica恢复：修复网络后replica追赶lag=18h的数据，预计耗时约45分钟，追赶速度约24GB/min。"
        "根因修复：1) 增加WAL清理策略wal_keep_size=32GB 2) replica断连超过2h自动告警 3) /data分区扩容至1TB。"
        "容量预测：按当前增长速度3.2GB/天，扩容后可支撑约300天，下次扩容预计在2025-01-15前后。"
    ),
    "must_keep": ["2024-03-22T03:45:00Z", "10.0.1.25", "92.3%", "48.2GB", "620GB", "435GB", "89GB", "38GB", "10.0.1.27", "18小时", "28.5GB", "34GB", "82.1%", "110.7GB", "45分钟", "24GB/min", "wal_keep_size=32GB", "1TB", "3.2GB/天", "300天", "2025-01-15"],
})

TEST_CASES.append({
    "id": "K45",
    "name": "证书过期导致服务中断",
    "context": "TLS证书管理",
    "text": (
        "以下是一次TLS证书过期导致服务中断的事故报告。"
        "证书管理是保障HTTPS安全通信的基础工作，虽然看似简单但容易被忽视。"
        "从安全运维的角度来看，证书过期是完全可以预防的事故类型。"
        "值得一提的是，行业中因证书过期导致的大规模故障并不罕见。"
        "在我们的基础设施中，证书的管理涉及多个层级和多个团队。"
        "需要说明的是，自动化证书续签机制的重要性在这次事故中得到了充分验证。"
        "从流程管理的角度来看，证书的续签应该有明确的责任人和时间表。"
        "另外证书即将过期的监控告警也需要覆盖所有使用证书的节点。"
        "在事故发生时，由于是凌晨时段，oncall的响应时间受到了一定影响。"
        "从用户视角来看，证书过期会导致浏览器显示安全警告，严重影响用户信任。"
        "总的来说，这次事故的教训是自动化和冗余是防止此类问题的最佳手段。"
        "事故时间线：2024-03-25T02:00:00Z api.platform.io的TLS证书(*.platform.io通配符证书)到期失效。"
        "02:00:01Z 所有HTTPS请求开始返回ERR_CERT_DATE_INVALID，影响全部API流量。"
        "02:03:22Z 自动监控检测到SSL错误率100%，触发P0告警，通知oncall和安全团队。"
        "02:15:00Z oncall响应，确认证书过期，原始过期时间为2024-03-25T01:59:59Z(UTC)。"
        "02:22:00Z 从Let's Encrypt申请新证书，域名验证(DNS-01 challenge)耗时3分28秒。"
        "02:26:30Z 新证书(有效期至2024-06-23T01:59:59Z)部署到全部12个edge节点。"
        "02:28:00Z 服务恢复正常，总故障时间MTTR=28分钟，影响请求约34,500个。"
        "根因：cert-manager配置错误，renew_before=720h(30天)的自动续签因DNS provider API鉴权失败而静默失败。"
        "改进措施：1) 修复DNS API凭证 2) 证书过期前30/14/7/3/1天逐级告警 3) 备用证书auto_fallback=true。"
    ),
    "must_keep": ["2024-03-25T02:00:00Z", "api.platform.io", "ERR_CERT_DATE_INVALID", "100%", "02:03:22Z", "2024-03-25T01:59:59Z", "02:22:00Z", "3分28秒", "2024-06-23T01:59:59Z", "02:28:00Z", "28分钟", "34,500", "renew_before=720h", "30/14/7/3/1天", "auto_fallback=true"],
})


TEST_CASES.append({
    "id": "K46",
    "name": "内存泄漏排查报告",
    "context": "JVM内存问题",
    "text": (
        "以下是一次Java服务内存泄漏的排查和修复过程记录。"
        "内存管理是Java应用运维中经常遇到的挑战性问题之一。"
        "从JVM调优的角度来看，合理的堆内存配置和GC策略选择非常重要。"
        "值得一提的是，内存泄漏问题往往是渐进式的，不容易在短时间内被发现。"
        "在日常监控中，我们对JVM的各项内存指标保持了持续的观察。"
        "需要说明的是，某些类型的内存泄漏只在特定的使用模式下才会触发。"
        "从代码质量的角度来看，资源的正确释放是每个开发者需要注意的基本功。"
        "另外静态分析工具也能够帮助在编码阶段发现潜在的泄漏风险。"
        "在问题定位过程中，heap dump分析是最直接有效的手段。"
        "从系统稳定性的角度来看，及时发现和修复内存泄漏对长期运行很重要。"
        "总的来说，内存问题的排查需要耐心和系统性的方法。"
        "现象描述：order-service(3个pod)在连续运行约72小时后内存使用持续增长。"
        "监控数据：JVM heap从启动时的1.2GB缓慢增长至3.6GB(max_heap=4GB)，Old Gen占用达92%。"
        "GC状况：Full GC频率从正常的1次/2h增至15次/h，每次耗时约800ms，STW影响明显。"
        "Heap Dump分析(文件大小3.8GB)：Top1占用类 com.cache.SessionCache 实例数1,247,000个，占堆42.3%。"
        "根因定位：SessionCache使用ConcurrentHashMap存储用户会话，过期session未被清除(TTL逻辑bug)。"
        "修复方案：使用Caffeine替代原生Map，配置expireAfterAccess=30min, maximumSize=100000。"
        "修复后验证：连续运行168h(7天)，heap稳定在1.4-1.8GB区间，Full GC降至1次/4h。"
        "容量优化：修复后单pod可支撑max_concurrent_sessions=50000，较之前提升4倍。"
    ),
    "must_keep": ["72小时", "1.2GB", "3.6GB", "max_heap=4GB", "92%", "1次/2h", "15次/h", "800ms", "3.8GB", "1,247,000", "42.3%", "SessionCache", "ConcurrentHashMap", "expireAfterAccess=30min", "maximumSize=100000", "168h", "1.4-1.8GB", "1次/4h", "max_concurrent_sessions=50000"],
})

TEST_CASES.append({
    "id": "K47",
    "name": "网络分区故障处理",
    "context": "集群脑裂处理",
    "text": (
        "以下是一次网络分区导致集群脑裂的故障处理报告。"
        "分布式系统中的网络分区是CAP理论中必须面对的现实挑战。"
        "从分布式系统设计的角度来看，网络分区的处理策略需要提前规划。"
        "值得一提的是，网络分区在实际生产环境中比理论上出现得更加频繁。"
        "在我们的集群架构中，节点之间通过心跳机制来检测连通性。"
        "需要说明的是，脑裂问题如果处理不当可能导致数据不一致。"
        "从数据一致性的角度来看，在网络分区期间的写入需要特殊处理。"
        "另外仲裁机制的设计对于正确处理脑裂至关重要。"
        "在故障恢复后，数据的合并和冲突解决也是一个技术难点。"
        "从运维角度来看，网络分区的检测和自动处理能力是评估系统成熟度的重要指标。"
        "总的来说，处理网络分区需要在可用性和一致性之间做出明确的取舍。"
        "事故时间线：2024-03-28T16:45:12Z 机房交换机故障，rack-A(node-1,2,3)与rack-B(node-4,5)网络隔离。"
        "16:45:18Z 心跳超时(threshold=6s)，两个分区各自开始leader选举。"
        "16:45:25Z 脑裂发生：rack-A选举node-1为leader(3/5=60%票数), rack-B拒绝选举(2/5<quorum)。"
        "16:45:30Z rack-B的2个节点自动降级为read-only模式，拒绝所有写请求(返回HTTP 503)。"
        "16:48:00Z 网络恢复，rack-B节点重新加入集群，开始数据同步(增量delta=12,450条记录)。"
        "16:49:30Z 数据同步完成，集群状态恢复一致(checksum验证通过)，总分区时间3分18秒。"
        "影响评估：rack-B写入被拒绝period=3m18s，影响约5,680个写请求，无数据丢失(设计如预期)。"
        "配置参数：heartbeat_interval=2s, election_timeout=6s, quorum_size=3/5, split_brain_strategy=minority_readonly。"
        "改进建议：1) 部署第3个rack以提供仲裁 2) 交换机链路冗余bond模式 3) 增加witness节点。"
    ),
    "must_keep": ["2024-03-28T16:45:12Z", "rack-A", "node-1,2,3", "rack-B", "node-4,5", "threshold=6s", "3/5", "60%", "2/5", "read-only", "503", "12,450", "3分18秒", "5,680", "heartbeat_interval=2s", "election_timeout=6s", "quorum_size=3/5", "split_brain_strategy=minority_readonly"],
})

TEST_CASES.append({
    "id": "K48",
    "name": "消息队列消费延迟",
    "context": "Kafka消费积压",
    "text": (
        "以下是一次Kafka消费者组严重积压的故障分析和处理报告。"
        "消息队列的消费延迟是分布式系统中比较常见的问题之一。"
        "从系统设计的角度来看，消费能力需要与生产速率相匹配。"
        "值得一提的是，消费积压如果不及时处理，可能会导致数据丢失或业务异常。"
        "在我们的事件驱动架构中，消息的及时处理对业务连续性至关重要。"
        "需要说明的是，不同topic的消费优先级应该根据业务重要性来区分。"
        "从容量规划的角度来看，需要为流量高峰预留足够的消费冗余。"
        "另外消费者的并发度和批量处理参数也会影响整体的消费吞吐。"
        "在问题发生时，快速扩容消费者实例是最直接的应对手段。"
        "从架构演进的角度来看，引入背压机制能够从根本上防止积压。"
        "总的来说，消息积压的处理需要短期的应急措施和长期的架构优化相结合。"
        "告警触发：2024-03-30T08:12:00Z consumer-group=order-processor, topic=order-events, 消费lag突破阈值。"
        "积压数据：总lag=2,340,000条消息，各分区最大lag：partition-5=312,000, partition-8=298,000。"
        "正常消费速率：约8,500 msgs/s，当前生产速率：约12,800 msgs/s，差距4,300 msgs/s持续积压。"
        "原因分析：08:00部署的新版本引入了外部API调用(avg_latency=45ms)，使单条处理时间从5ms增至52ms。"
        "即时措施：1) 消费者实例从6扩至18个(3x) 2) max.poll.records从500降至200 3) 关闭非核心逻辑bypass=true。"
        "08:25:00Z 消费速率提升至25,600 msgs/s，开始消化积压，预计清空时间约92秒。"
        "08:27:32Z 积压清零，回到实时消费状态(lag < 100)，总处理时间15分32秒。"
        "后续优化：外部API调用改为异步(使用CompletableFuture)，处理时间从52ms降至8ms，吞吐提升6.5倍。"
    ),
    "must_keep": ["2024-03-30T08:12:00Z", "order-processor", "order-events", "2,340,000", "partition-5=312,000", "partition-8=298,000", "8,500", "12,800", "4,300", "45ms", "5ms", "52ms", "18个", "max.poll.records", "200", "bypass=true", "25,600", "92秒", "15分32秒", "8ms", "6.5倍"],
})

TEST_CASES.append({
    "id": "K49",
    "name": "部署回滚操作记录",
    "context": "版本回滚过程",
    "text": (
        "以下是一次生产环境部署失败后执行回滚操作的详细记录。"
        "部署回滚是保障生产环境稳定性的最后一道防线。"
        "从DevOps实践的角度来看，快速可靠的回滚能力是成熟交付流程的标志。"
        "值得一提的是，每次部署之前都应该确认回滚方案可行且经过验证。"
        "在我们的CI/CD流程中，回滚操作已经实现了高度自动化。"
        "需要说明的是，有些部署涉及数据库变更，回滚时需要特别注意兼容性。"
        "从风险管理的角度来看，灰度发布能够在问题扩大之前及时发现。"
        "另外回滚决策的时机也很关键，过早回滚可能误判，过晚则影响面扩大。"
        "在执行回滚的过程中，需要同步通知相关团队和利益相关者。"
        "从事后复盘的角度来看，每次回滚都应该分析部署失败的根因。"
        "总的来说，回滚能力是系统韧性的重要组成部分。"
        "触发事件：2024-04-01T10:30:00Z 版本v3.12.0部署到production，canary阶段(5%流量)。"
        "10:35:00Z canary指标异常：error_rate=4.8%(baseline=0.1%), P99_latency=1,850ms(baseline=120ms)。"
        "10:36:30Z 自动回滚触发条件满足(error_rate > 2% for 3min)，开始执行回滚到v3.11.2。"
        "回滚步骤：1) 停止canary traffic routing(耗时2s) 2) 拉取v3.11.2镜像(已缓存,耗时0s)。"
        "3) Rolling update 12个pod(strategy=RollingUpdate, maxSurge=3, maxUnavailable=1)耗时45s。"
        "4) 健康检查全部通过(12/12 healthy)，耗时30s，流量全部切回stable版本。"
        "10:37:47Z 回滚完成，总耗时77秒，error_rate恢复至0.08%，P99恢复至115ms。"
        "影响范围：canary期间(5%流量×7分钟)，受影响请求约3,250个，其中失败约156个。"
        "根因分析：v3.12.0中引入的数据库连接参数变更(pool_timeout从5s改为500ms)导致大量timeout。"
        "改进措施：1) 配置变更需独立review 2) canary观察期从5min延长至15min 3) 添加配置diff检查gate。"
    ),
    "must_keep": ["2024-04-01T10:30:00Z", "v3.12.0", "5%", "4.8%", "0.1%", "1,850ms", "120ms", "v3.11.2", "12个pod", "maxSurge=3", "maxUnavailable=1", "45s", "10:37:47Z", "77秒", "0.08%", "115ms", "3,250", "156", "pool_timeout", "5s", "500ms", "15min"],
})

TEST_CASES.append({
    "id": "K50",
    "name": "定时任务执行失败告警",
    "context": "批处理任务监控",
    "text": (
        "以下是一次关键定时任务连续执行失败的告警处理和根因分析报告。"
        "定时任务是许多业务流程自动化的基础，它的可靠执行直接影响业务数据的准确性。"
        "从运维管理的角度来看，定时任务的监控需要覆盖执行状态、耗时和结果三个维度。"
        "值得一提的是，定时任务的失败有时不会立即产生可见的业务影响，容易被忽视。"
        "在我们的任务调度系统中，所有定时任务都有完善的日志记录和告警配置。"
        "需要说明的是，定时任务之间的依赖关系也需要在调度时妥善管理。"
        "从数据一致性的角度来看，幂等性设计是定时任务的基本要求。"
        "另外任务的超时控制和重试策略也需要根据具体业务来配置。"
        "在生产环境中，定时任务的并发控制避免了资源竞争和数据冲突。"
        "从系统负载的角度来看，大批量任务应该错峰执行以避免对在线服务的影响。"
        "总的来说，定时任务虽然在后台运行不被用户直接感知，但其重要性不可忽视。"
        "告警信息：2024-04-03T06:05:00Z job=daily_data_sync 连续3次执行失败(最近成功执行: 2024-03-31T06:00:00Z)。"
        "任务配置：cron=0 6 * * *(每日06:00), timeout=3600s, retry_count=3, retry_interval=300s。"
        "失败日志：第1次(04-01 06:00): OOM killed, memory_usage=7.8GB/max=8GB, 处理到记录第2,450,000/3,800,000。"
        "第2次(04-02 06:00): 同样OOM, memory=7.9GB/8GB, 处理到第2,520,000条。"
        "第3次(04-03 06:00): OOM, memory=8.0GB/8GB, 处理到第2,380,000条。"
        "根因分析：3月底大促活动新增数据800,000条(增幅26.7%)，超出任务内存预算。"
        "临时修复：提升内存限制memory_limit=12GB，并增加分批处理batch_size=500000/batch。"
        "修复后验证：04-03T10:00手动触发，耗时2,847秒(约47min)，峰值内存6.2GB，成功同步3,800,000条记录。"
        "长期方案：1) 改为streaming模式(每批100000条) 2) 内存监控阈值调整alert_threshold=70% 3) 自动扩容trigger=memory>80%。"
    ),
    "must_keep": ["2024-04-03T06:05:00Z", "daily_data_sync", "2024-03-31T06:00:00Z", "cron=0 6 * * *", "timeout=3600s", "retry_count=3", "retry_interval=300s", "7.8GB", "8GB", "2,450,000", "3,800,000", "2,520,000", "2,380,000", "800,000", "26.7%", "memory_limit=12GB", "batch_size=500000", "2,847秒", "6.2GB", "alert_threshold=70%"],
})


# ═══════════════════════════════════════════════════════════
# 评测运行器
# ═══════════════════════════════════════════════════════════


def run_eval():
    """运行全部50个测试用例并输出评测结果"""
    kompressor = LightKompress()

    print("=" * 80)
    print("LightKompress 长文本低密度评测 (50 Cases)")
    print("条件：1000-3000字符 | 30%信息密度 | must_keep recall>=98.5% | savings>=15%")
    print("=" * 80)

    results = []
    pass_count = 0
    fail_count = 0

    for case in TEST_CASES:
        text = case["text"]
        context = case.get("context", "")
        must_keep_items = case.get("must_keep", [])

        # 运行压缩
        result = kompressor.compress(
            text=text,
            context=context,
            bias=1.0,
            target_ratio=0.5,
        )

        # 计算 must_keep recall
        if must_keep_items:
            recalled = sum(1 for item in must_keep_items if item in result.compressed)
            recall = recalled / len(must_keep_items)
            missed = [item for item in must_keep_items if item not in result.compressed]
        else:
            recall = 1.0
            missed = []

        # 计算 savings
        savings = (1 - result.ratio) * 100

        # 判断 pass/fail
        passed = recall >= 0.985 and savings >= 15.0

        if passed:
            pass_count += 1
            status = "PASS"
        else:
            fail_count += 1
            status = "FAIL"

        results.append({
            "id": case["id"],
            "name": case["name"],
            "original_chars": result.original_chars,
            "compressed_chars": result.compressed_chars,
            "ratio": result.ratio,
            "savings": savings,
            "recall": recall,
            "missed": missed,
            "passed": passed,
            "status": status,
            "duration_ms": result.duration_ms,
        })

        # 打印单条结果
        recall_str = f"{recall*100:.1f}%"
        savings_str = f"{savings:.1f}%"
        fail_reason = ""
        if not passed:
            reasons = []
            if recall < 0.985:
                reasons.append(f"recall={recall_str}<98.5%")
            if savings < 15.0:
                reasons.append(f"savings={savings_str}<15%")
            fail_reason = f" ({', '.join(reasons)})"

        print(f"  [{status}] {case['id']} {case['name']:<28} | "
              f"orig={result.original_chars:>5} comp={result.compressed_chars:>5} "
              f"savings={savings_str:>6} recall={recall_str:>6} "
              f"time={result.duration_ms:.1f}ms{fail_reason}")

        if missed and not passed:
            print(f"         missed: {missed[:5]}{'...' if len(missed)>5 else ''}")

    # ─── Summary ───
    print("\n" + "=" * 80)
    print("Summary")
    print("=" * 80)

    avg_savings = sum(r["savings"] for r in results) / len(results)
    avg_recall = sum(r["recall"] for r in results) / len(results)
    min_recall = min(r["recall"] for r in results)
    max_savings = max(r["savings"] for r in results)
    min_savings = min(r["savings"] for r in results)
    avg_duration = sum(r["duration_ms"] for r in results) / len(results)

    print(f"  Total cases:       {len(results)}")
    print(f"  Passed:            {pass_count}/{len(results)} ({pass_count/len(results)*100:.1f}%)")
    print(f"  Failed:            {fail_count}/{len(results)}")
    print(f"  Avg savings:       {avg_savings:.1f}%")
    print(f"  Savings range:     {min_savings:.1f}% ~ {max_savings:.1f}%")
    print(f"  Avg must_keep recall: {avg_recall*100:.2f}%")
    print(f"  Min must_keep recall: {min_recall*100:.2f}%")
    print(f"  Avg duration:      {avg_duration:.2f}ms")
    print("=" * 80)

    # 打印失败用例详情
    if fail_count > 0:
        print(f"\nFailed cases detail ({fail_count}):")
        print("-" * 80)
        for r in results:
            if not r["passed"]:
                print(f"  {r['id']} {r['name']}")
                print(f"    savings={r['savings']:.1f}%, recall={r['recall']*100:.1f}%")
                if r["missed"]:
                    print(f"    missed items: {r['missed']}")
                print()

    return results


if __name__ == "__main__":
    run_eval()
