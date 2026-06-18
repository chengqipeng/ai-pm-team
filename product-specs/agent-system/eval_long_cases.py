"""
LightKompress 长文本/极致压缩评估测试集 — 50+ 用例覆盖 3 大维度
评估 Feature A (无标点分句) 和 Feature B (句内精简) 的压缩能力

运行方式:
    python eval_long_cases.py

覆盖维度:
    K. 极致压缩率 (20 cases)  — 长文本高冗余度，目标 20-40% 压缩
    L. 无标点文本 (15 cases)  — 无句末标点，验证降级分句
    M. 超长句内压缩 (15 cases) — 单句/少句极长文本
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import List

from demo_light_kompress import LightKompress, CompressResult
from eval_200_cases import TestCase


# ═══════════════════════════════════════════════════════════════════════════════
# K. 极致压缩率 — 高冗余长文本
# ═══════════════════════════════════════════════════════════════════════════════

CASES_K: List[TestCase] = [
    TestCase(
        id="K01", category="极致压缩率", name="中文业务报告-大量填充词",
        text=(
            "经过详细分析，2024年第一季度的销售数据显示出一些值得关注的趋势。"
            "总的来说，公司整体营收达到了¥8,500万，同比增长了18.5%。"
            "从目前的情况来看，华东区域依然是我们最强势的市场，贡献了整体收入的42%。"
            "需要说明的是，新产品线SuperApp在本季度首次突破了1000万用户。"
            "值得一提的是，客户获取成本从上季度的¥320降低到了¥285，降幅达11%。"
            "从这个角度来看，我们的获客策略正在持续优化。"
            "另外需要说明的是，本季度研发投入占比提升至15.2%，主要用于AI能力建设。"
            "总的来说，技术团队完成了3个核心项目的交付，包括推荐系统V2.0、智能客服升级和数据平台迁移。"
            "值得注意的是，推荐系统V2.0上线后，用户点击率提升了27%，转化率提升了15%。"
            "从目前的情况来看，竞争对手在Q1也有较大动作，某竞品发布了类似功能。"
            "需要指出的是，我们的技术壁垒在于自研的深度学习模型和数据积累。"
            "经过详细分析竞品数据，我们的模型准确率领先约8个百分点。"
            "总的来说，Q1整体表现符合预期，建议Q2继续加大在AI和数据方面的投入。"
            "值得一提的是，管理层已批准了¥2,000万的额外预算用于AI人才招聘。"
            "从长远来看，这些投入将在未来2-3个季度开始产生回报。"
        ),
        context="Q1销售和营收增长情况",
        must_keep=["¥8,500万", "18.5%", "42%", "1000万", "¥285", "27%", "15%", "V2.0"],
        expect_compressed=True,
        target_ratio=0.4,
    ),
    TestCase(
        id="K02", category="极致压缩率", name="中文项目汇报-冗余过渡",
        text=(
            "关于智能客服系统升级项目的进展汇报如下。从目前的情况来看，项目整体进度符合预期。"
            "需要说明的是，前端重构已完成85%，剩余部分预计本月底完成。"
            "值得注意的是，后端API已完成全部重写，新接口响应时间从平均450ms降低到120ms。"
            "总的来说，性能提升非常显著，QPS从原来的500提升到了2800。"
            "经过详细分析用户反馈数据，我们发现智能路由模块的准确率达到了92%。"
            "从这个角度来看，自动分配工单给最合适的客服代表的效果很好。"
            "另外需要说明的是，NLP引擎采用了BERT-base模型，意图识别准确率为94.5%。"
            "值得一提的是，我们还集成了知识库检索功能，命中率达到了78%。"
            "需要指出的是，目前尚未解决的问题包括：多轮对话中的上下文保持。"
            "从技术层面来看，这需要引入更复杂的状态管理机制。"
            "总的来说，预计需要额外2周的研发时间来解决这个问题。"
            "综上所述，项目整体进度良好，核心指标达标，建议按计划在下月15日发布V3.0版本。"
            "需要说明的是，发布前还需要完成压力测试和安全审计两项工作。"
            "从资源角度来看，当前团队规模8人足够支撑剩余工作量。"
        ),
        context="智能客服升级项目进度",
        must_keep=["85%", "120ms", "2800", "92%", "94.5%", "78%", "V3.0", "8人"],
        expect_compressed=True,
        target_ratio=0.4,
    ),
    TestCase(
        id="K03", category="极致压缩率", name="英文verbose技术报告",
        text=(
            "It is worth noting that the database migration project has reached a significant milestone. "
            "As a matter of fact, we have successfully migrated 85% of the production data from MySQL 5.7 to PostgreSQL 15. "
            "Broadly speaking, the migration process has been proceeding smoothly with minimal downtime. "
            "It should be mentioned that the total data volume processed is approximately 2.4TB across 156 tables. "
            "Needless to say, data integrity verification is of paramount importance in such operations. "
            "In other words, every record must be validated against the source. "
            "As we all know, schema differences between MySQL and PostgreSQL require careful handling. "
            "To put it simply, we developed custom ETL scripts for 23 complex table transformations. "
            "It goes without saying that performance benchmarks were conducted post-migration. "
            "As a matter of fact, query performance improved by an average of 34% due to PostgreSQL's superior query optimizer. "
            "It is worth noting that the connection pool was tuned to max_connections=200, pool_size=50. "
            "Broadly speaking, the remaining 15% of data involves legacy tables with deprecated column types. "
            "It should be mentioned that the final cutover is scheduled for 2024-03-15 during the maintenance window. "
            "In other words, the expected downtime during cutover will be approximately 45 minutes. "
            "Needless to say, a comprehensive rollback plan has been prepared in case of unexpected issues."
        ),
        context="database migration progress and performance",
        must_keep=["85%", "MySQL 5.7", "PostgreSQL 15", "2.4TB", "156 tables", "34%", "max_connections=200", "2024-03-15", "45 minutes"],
        expect_compressed=True,
        target_ratio=0.4,
    ),
    TestCase(
        id="K04", category="极致压缩率", name="中文运营数据-重复句式",
        text=(
            "2024年3月用户运营数据月报。总的来说，本月活跃用户数达到了580万。"
            "值得注意的是，日活跃用户(DAU)峰值出现在3月15日，达到了98万。"
            "从目前的情况来看，新增注册用户为23.5万，较上月增长了12%。"
            "需要说明的是，用户留存率方面，次日留存42%，7日留存18%，30日留存8.5%。"
            "经过详细分析用户行为数据，我们发现平均会话时长从5.2分钟增长到了6.8分钟。"
            "值得一提的是，每用户日均打开次数从3.1次提升到了4.2次。"
            "从这个角度来看，产品粘性在持续提升。"
            "总的来说，付费转化率为3.8%，ARPU值¥45.6。"
            "需要指出的是，VIP用户续费率维持在85%以上，这是一个健康的水平。"
            "另外需要说明的是，本月推送通知的点击率为6.2%，较上月提升了1.5个百分点。"
            "从渠道角度来看，应用商店自然流量占比55%，付费推广占比30%，社交分享占比15%。"
            "值得注意的是，社交分享的获客质量最高，其30日留存达到了12%。"
            "总的来说，建议Q2加大社交裂变功能的投入。"
            "综上所述，3月用户运营核心指标均呈现正向增长趋势。"
        ),
        context="3月用户活跃度和留存数据",
        must_keep=["580万", "98万", "23.5万", "12%", "42%", "18%", "8.5%", "6.8分钟", "¥45.6", "85%"],
        expect_compressed=True,
        target_ratio=0.4,
    ),
    TestCase(
        id="K05", category="极致压缩率", name="英文产品更新公告-冗余描述",
        text=(
            "We are extremely pleased to announce several exciting new features in our latest release v4.2.0. "
            "As many of you have been eagerly awaiting, we have finally introduced the long-requested dark mode feature. "
            "It is worth mentioning that this feature was the number one request from our community for over 18 months. "
            "Additionally, and this is something we are particularly proud of, we have completely redesigned the dashboard. "
            "The new dashboard provides real-time analytics with a refresh rate of 500ms and supports up to 50 concurrent widgets. "
            "Furthermore, it should be noted that we have improved the API rate limiting from 100 requests per minute to 500 requests per minute for Pro users. "
            "In terms of performance, which we know is critically important to our users, page load time has decreased from 3.2 seconds to 1.1 seconds. "
            "Another noteworthy improvement is the addition of SSO support for SAML 2.0 and OpenID Connect protocols. "
            "We are also happy to report that storage capacity has been doubled from 50GB to 100GB for Business plans. "
            "It goes without saying that security remains our top priority, and we have passed SOC 2 Type II certification. "
            "Last but certainly not least, we have reduced our pricing by 15% across all plans effective immediately. "
            "We truly believe that these improvements will significantly enhance your experience with our platform."
        ),
        context="v4.2.0 release key features and improvements",
        must_keep=["v4.2.0", "dark mode", "500ms", "50 concurrent widgets", "500 requests per minute", "1.1 seconds", "SAML 2.0", "100GB", "SOC 2 Type II", "15%"],
        expect_compressed=True,
        target_ratio=0.4,
    ),
    TestCase(
        id="K06", category="极致压缩率", name="中文市场分析-过度修饰",
        text=(
            "经过我们团队长时间的深入研究和全面调研，关于2024年SaaS市场的发展趋势分析如下。"
            "从宏观层面来看，全球SaaS市场规模预计将从2023年的¥1.2万亿增长到2024年的¥1.5万亿。"
            "值得特别关注的是，中国市场增速高于全球平均水平，预计增长率为28%。"
            "在细分领域中，从目前的数据来看，企业协同办公赛道增速最快，年增长率达到了35%。"
            "需要特别说明的是，AI+SaaS的融合趋势在2024年尤为明显。"
            "总的来说，约有67%的SaaS企业已经或正在将AI能力集成到产品中。"
            "从竞争格局来看，头部3家企业市占率合计为45%，集中度在持续提升。"
            "值得一提的是，我们的竞品A公司在Q4获得了$2亿的D轮融资。"
            "另外，据不完全统计，本年度SaaS领域共发生了156起融资事件，总金额超过$50亿。"
            "经过详细分析行业报告和专家访谈，我们认为2024年的核心机会在于垂直行业解决方案。"
            "从客户需求角度来看，定制化和行业化已经成为了不可逆转的趋势。"
            "需要指出的是，我们目前在制造业SaaS赛道的市占率为12%，排名第三。"
            "综上所述，建议公司在保持通用平台能力的基础上，重点深耕3-5个垂直行业。"
        ),
        context="2024年SaaS市场趋势和竞争分析",
        must_keep=["¥1.2万亿", "¥1.5万亿", "28%", "35%", "67%", "45%", "$2亿", "156起", "$50亿", "12%"],
        expect_compressed=True,
        target_ratio=0.4,
    ),
    TestCase(
        id="K07", category="极致压缩率", name="中文技术复盘-啰嗦叙述",
        text=(
            "关于本次P0级别线上事故的复盘报告如下。需要说明的是，事故发生在2024年2月28日凌晨2:35。"
            "从表象来看，用户反馈支付功能完全不可用，错误码为5001。"
            "经过深入排查，总的来说，根本原因是Redis集群的master节点发生了OOM。"
            "值得注意的是，当时Redis内存使用率已达到96%，触发了自动驱逐策略。"
            "从技术角度详细分析，被驱逐的key中包含了支付session的缓存数据。"
            "需要指出的是，session缓存的TTL设置为24小时，远超实际需要的15分钟。"
            "另外需要说明的是，Redis实例规格为16C64G，但承载了超过8000万个key。"
            "从监控数据来看，告警实际上在2:20就已触发，但值班人员未及时响应。"
            "总的来说，事故持续了约47分钟，影响了约15,000笔交易。"
            "值得一提的是，直接经济损失预估为¥230万，包括退款和补偿。"
            "经过详细分析，我们制定了以下改进措施：第一，将session TTL从24h调整为15min。"
            "第二，Redis扩容至32C128G，并开启cluster模式。第三，优化告警规则和值班响应流程。"
            "从长远来看，还需要引入Redis容量预测和自动扩缩容机制。"
            "综上所述，本次事故暴露了容量管理和告警响应两方面的不足。"
        ),
        context="P0事故原因和改进措施",
        must_keep=["2024年2月28日", "2:35", "5001", "OOM", "96%", "16C64G", "8000万", "47分钟", "15,000笔", "¥230万"],
        expect_compressed=True,
        target_ratio=0.4,
    ),
    TestCase(
        id="K08", category="极致压缩率", name="英文HR年度报告-冗余总结",
        text=(
            "It is with great pleasure that we present the annual Human Resources report for the fiscal year 2024. "
            "As everyone knows, our team has grown significantly over the past twelve months. "
            "To be specific, total headcount increased from 1,250 to 1,680 employees, representing a growth rate of 34.4%. "
            "It is worth noting that the engineering department experienced the highest growth, adding 215 new members. "
            "Broadly speaking, the average time-to-hire across all departments was 32 days, down from 45 days last year. "
            "It should be mentioned that our offer acceptance rate reached an impressive 89%, up from 76% in the previous year. "
            "In terms of retention, which is always a key focus area, annual turnover rate decreased to 12.3% from 18.1%. "
            "As a matter of fact, the most common reason for voluntary departure was compensation, cited by 35% of exiting employees. "
            "Needless to say, we have addressed this with a market adjustment budget of $4.5M allocated for Q1 2025. "
            "It goes without saying that employee satisfaction is crucial to our success. "
            "Our annual engagement survey showed an eNPS score of 52, up from 38 last year. "
            "Furthermore, it is noteworthy that 78% of employees reported being satisfied or very satisfied with their manager. "
            "In conclusion, the HR team recommends increasing the L&D budget by 20% to $2.8M for continued talent development. "
            "We truly believe that investing in our people is the foundation of our continued growth and success."
        ),
        context="headcount growth and retention metrics",
        must_keep=["1,250", "1,680", "34.4%", "215", "32 days", "89%", "12.3%", "35%", "$4.5M", "eNPS", "52"],
        expect_compressed=True,
        target_ratio=0.4,
    ),
    TestCase(
        id="K09", category="极致压缩率", name="中文产品需求文档-过度背景",
        text=(
            "关于智能推荐系统V3.0的产品需求文档如下。首先需要说明的是，当前系统V2.0已运行18个月。"
            "从数据表现来看，V2.0的推荐点击率为8.5%，转化率为2.1%。"
            "总的来说，这些指标在行业中处于中等偏上水平，但仍有较大提升空间。"
            "值得注意的是，竞品B公司近期公布的数据显示其点击率达到了12%。"
            "经过详细分析用户反馈和数据，我们确定了V3.0的核心目标：点击率提升至12%以上，转化率达到3.5%。"
            "从技术方案来看，需要引入实时特征计算引擎，支持毫秒级特征更新。"
            "需要说明的是，新架构将采用Flink作为流计算引擎，特征存储使用Redis Cluster。"
            "另外值得一提的是，模型层将从XGBoost升级为Deep-FM加Wide-and-Deep的混合架构。"
            "从用户体验角度来看，需要支持多样性控制，避免推荐结果过于单一。"
            "总的来说，多样性指标目标为ILS≥0.3。"
            "需要指出的是，冷启动问题也是V3.0必须解决的难题。"
            "从目前的情况来看，新用户首次推荐的点击率仅为3.2%，远低于平均水平。"
            "经过详细调研，我们计划引入基于用户画像的协同过滤来解决冷启动。"
            "综上所述，V3.0的开发周期预计为4个月，需要5名后端+3名算法工程师。"
        ),
        context="推荐系统V3.0核心指标和技术方案",
        must_keep=["V3.0", "8.5%", "2.1%", "12%", "3.5%", "Flink", "Redis Cluster", "Deep-FM", "ILS≥0.3", "3.2%"],
        expect_compressed=True,
        target_ratio=0.4,
    ),
    TestCase(
        id="K10", category="极致压缩率", name="英文季度财报摘要-冗余解释",
        text=(
            "We are delighted to share with all our valued stakeholders the financial results for Q3 2024. "
            "It is important to note that these results exceed our initial guidance by a significant margin. "
            "Total revenue for the quarter came in at $128.5M, representing a year-over-year increase of 22.3%. "
            "It is worth highlighting that recurring revenue, which is a key indicator of business health, reached $98.2M or 76.4% of total revenue. "
            "As many analysts have noted, our gross margin improved to 72.1%, up from 68.5% in the same quarter last year. "
            "It should be mentioned that this improvement is primarily attributable to infrastructure cost optimization. "
            "Operating expenses, which we continue to manage prudently, totaled $78.3M representing 60.9% of revenue. "
            "As a result of these improvements, adjusted EBITDA reached $24.7M with a margin of 19.2%. "
            "Needless to say, free cash flow generation remains strong at $18.5M for the quarter. "
            "It is also noteworthy that our net dollar retention rate stands at 118%, indicating healthy expansion within existing accounts. "
            "In terms of our balance sheet, we ended the quarter with $456M in cash and no debt. "
            "It goes without saying that this gives us significant flexibility for both organic growth and potential M&A opportunities. "
            "Looking ahead, which I know is what everyone is most interested in, we are raising our full-year guidance to $500-510M. "
            "In conclusion, we remain confident in our ability to deliver sustained profitable growth."
        ),
        context="Q3 revenue and profitability metrics",
        must_keep=["$128.5M", "22.3%", "$98.2M", "76.4%", "72.1%", "$78.3M", "$24.7M", "19.2%", "118%", "$456M", "$500-510M"],
        expect_compressed=True,
        target_ratio=0.4,
    ),
    TestCase(
        id="K11", category="极致压缩率", name="中文客服话术-大量礼貌用语",
        text=(
            "尊敬的客户，非常感谢您对我们产品的关注和支持。针对您提出的问题，我来为您详细解答。"
            "首先，关于您反馈的订单号ORD-2024031588延迟发货的问题，经过我们物流团队的仔细核查，"
            "发现是由于仓库在3月12日进行了年度盘点导致的发货延迟。"
            "非常抱歉给您带来了不便，我们深表歉意。"
            "目前您的订单已经安排发出，快递单号SF1234567890，预计3月16日前送达。"
            "另外，为了表达我们的歉意，我们已经为您的账户充值了50元优惠券，有效期90天。"
            "其次，关于您询问的会员升级问题，您当前的累计消费金额为¥12,680，距离金卡会员还差¥2,320。"
            "需要说明的是，金卡会员可享受全场9折优惠和免费极速配送服务。"
            "最后，非常感谢您的耐心等待和理解，如果您还有其他问题，随时可以联系我们。"
            "我们的客服热线400-888-9999全天候为您服务。祝您生活愉快！"
            "再次感谢您选择我们的产品和服务，我们会继续努力为您提供更好的购物体验。"
            "希望我的回答对您有所帮助，期待您的下次光临。"
        ),
        context="订单延迟原因和补偿方案",
        must_keep=["ORD-2024031588", "3月12日", "SF1234567890", "3月16日", "50元", "¥12,680", "¥2,320", "400-888-9999"],
        expect_compressed=True,
        target_ratio=0.4,
    ),
    TestCase(
        id="K12", category="极致压缩率", name="中文会议纪要-过渡冗余",
        text=(
            "以下是2024年3月18日产品评审会议的完整纪要。参会人员包括产品总监张伟、技术负责人李明、"
            "设计师王芳和QA负责人赵刚。总的来说，本次会议主要讨论了三个议题。"
            "首先，第一个议题是关于V2.5版本的发布计划。经过详细讨论，大家一致同意将发布日期定在4月1日。"
            "值得注意的是，当前还有12个P1级别bug需要修复，预计需要5个工作日。"
            "从测试角度来看，回归测试需要3天，因此总共需要8个工作日来确保版本质量。"
            "第二个议题是关于新功能数据导出模块的设计方案。需要说明的是，当前方案支持CSV和Excel两种格式。"
            "另外需要说明的是，单次导出数据量上限为100万行，超过部分需要分批处理。"
            "从性能角度来看，导出100万行数据预计耗时约45秒。"
            "第三个议题是关于Q2的OKR制定。总的来说，Q2核心目标是DAU突破200万。"
            "值得一提的是，为达成这个目标，需要完成用户增长体系和社交分享功能两大项目。"
            "综上所述，会议达成了明确的行动项和时间表。会议结束时间15:30。"
        ),
        context="评审会议核心决策和行动项",
        must_keep=["2024年3月18日", "4月1日", "12个", "P1", "5个工作日", "100万行", "45秒", "200万", "15:30"],
        expect_compressed=True,
        target_ratio=0.4,
    ),
    TestCase(
        id="K13", category="极致压缩率", name="英文市场营销邮件-大量套话",
        text=(
            "Dear valued partner, I hope this email finds you well and that you are having a wonderful start to the new quarter. "
            "I am writing to share some incredibly exciting updates about our partnership program that I believe will be of great interest to you. "
            "First and foremost, I am thrilled to announce that our joint revenue for Q1 reached $3.2M, exceeding target by 28%. "
            "As you are undoubtedly aware, this represents a significant achievement for both our organizations. "
            "Furthermore, I wanted to take this opportunity to inform you that we are expanding our partner discount from 20% to 25% effective April 1st. "
            "Additionally, and I think you will find this particularly exciting, we are introducing a new Partner Gold tier with a minimum threshold of $500K annual revenue. "
            "It would be wonderful if we could schedule a meeting to discuss how we can further strengthen our collaboration. "
            "I am confident that together we can achieve even greater things in the coming quarter. "
            "Please do not hesitate to reach out at your earliest convenience if you have any questions whatsoever. "
            "I look forward to hearing from you soon and continuing our incredibly productive partnership. "
            "With warmest regards and best wishes for continued success, the partnership team at TechCorp. "
            "P.S. Our annual partner summit is scheduled for June 15-17 in San Francisco, and we would love to have you there."
        ),
        context="partnership program updates and new discount",
        must_keep=["$3.2M", "28%", "20%", "25%", "April 1st", "$500K", "Partner Gold", "June 15-17", "San Francisco"],
        expect_compressed=True,
        target_ratio=0.4,
    ),
    TestCase(
        id="K14", category="极致压缩率", name="中文安全审计报告-重复结论",
        text=(
            "关于2024年Q1信息安全审计的综合报告如下。总的来说，本次审计覆盖了公司全部23个业务系统。"
            "需要说明的是，审计周期为2024年1月15日至3月15日，历时2个月。"
            "从整体安全态势来看，本季度共发现高危漏洞3个、中危漏洞15个、低危漏洞42个。"
            "值得注意的是，3个高危漏洞分别是：SQL注入(支付模块)、SSRF(文件服务)、权限绕过(管理后台)。"
            "经过详细分析，所有高危漏洞均已在发现后48小时内完成修复。"
            "从合规角度来看，系统整体合规率达到了94.5%，较上次审计提升了3个百分点。"
            "另外需要说明的是，WAF拦截了约120万次恶意请求，其中SQL注入攻击占比45%。"
            "值得一提的是，DDoS防护系统成功抵御了2次大规模攻击，峰值流量达到了85Gbps。"
            "总的来说，数据加密覆盖率从85%提升到了97%，基本实现了全面加密目标。"
            "需要指出的是，仍有3%的历史数据因技术限制未完成加密迁移。"
            "综上所述，Q1安全态势整体可控，建议Q2重点推进零信任架构改造。"
            "从预算角度来看，零信任改造预计需要投入¥500万，周期6个月。"
        ),
        context="Q1安全漏洞和合规情况",
        must_keep=["23个", "高危漏洞3个", "中危漏洞15个", "SQL注入", "SSRF", "48小时", "94.5%", "120万次", "85Gbps", "97%", "¥500万"],
        expect_compressed=True,
        target_ratio=0.4,
    ),
    TestCase(
        id="K15", category="极致压缩率", name="英文投资者简报-夸大修饰",
        text=(
            "We are absolutely thrilled to present to our distinguished investors the extraordinary progress we have made this quarter. "
            "It is truly remarkable and deeply gratifying to report that our Series C round closed at an incredible $85M valuation of $1.2B. "
            "As everyone in the industry will agree, this represents a phenomenal achievement for a company just 4 years old. "
            "Our remarkable growth trajectory shows ARR increasing from $42M to $67M, representing an astonishing 59.5% year-over-year growth. "
            "It is absolutely worth highlighting that our customer base has expanded magnificently to 2,800 enterprise accounts. "
            "The incredibly talented team has grown to 450 employees across 12 offices globally, which is simply outstanding. "
            "Our truly world-class NRR of 135% demonstrates the exceptional value our amazing product delivers to customers. "
            "We are extremely proud that CAC payback period has improved dramatically from 18 months to just 11 months. "
            "It is genuinely exciting to report that LTV/CAC ratio stands at an impressive 5.2x, well above the industry benchmark of 3x. "
            "Our incredibly efficient go-to-market engine achieved a remarkable magic number of 1.4 this quarter. "
            "Looking ahead with tremendous optimism, we are confidently targeting $100M ARR by end of fiscal year 2025. "
            "We are profoundly grateful for your continued trust and unwavering support of our extraordinary vision."
        ),
        context="Series C metrics and growth trajectory",
        must_keep=["$85M", "$1.2B", "4 years", "$42M", "$67M", "59.5%", "2,800", "450", "135%", "11 months", "5.2x", "$100M"],
        expect_compressed=True,
        target_ratio=0.4,
    ),
    TestCase(
        id="K16", category="极致压缩率", name="中文培训文档-冗余解释",
        text=(
            "欢迎参加本次新员工技术培训。首先需要说明的是，本培训为期3天，每天8小时。"
            "总的来说，培训内容涵盖了我们技术栈的所有核心组件。"
            "值得注意的是，我们的主要技术栈包括：前端React 18+TypeScript 5.0，后端Java 17+Spring Boot 3.1。"
            "从架构角度来看，系统采用了微服务架构，目前共有56个微服务。"
            "需要说明的是，服务间通信使用gRPC协议，消息队列使用Kafka 3.5。"
            "另外需要说明的是，数据库层采用MySQL 8.0作为主库，Redis 7.0作为缓存。"
            "从部署角度来看，所有服务部署在Kubernetes集群上，共有120个节点。"
            "值得一提的是，CI/CD流水线使用GitLab CI，从提交到部署平均需要12分钟。"
            "经过详细的历史数据统计，系统整体可用性达到了99.95%，SLA等级为L1。"
            "总的来说，监控体系使用Prometheus+Grafana，告警通过PagerDuty分发。"
            "需要指出的是，所有新员工需要在入职30天内完成技术认证考试，及格分数为80分。"
            "从学习资源来看，内部Wiki有超过2000篇技术文档可供参考。"
            "综上所述，希望大家认真学习，尽快融入技术团队。"
        ),
        context="技术栈和系统架构概览",
        must_keep=["React 18", "TypeScript 5.0", "Java 17", "Spring Boot 3.1", "56个微服务", "gRPC", "Kafka 3.5", "MySQL 8.0", "Redis 7.0", "120个节点", "99.95%"],
        expect_compressed=True,
        target_ratio=0.4,
    ),
    TestCase(
        id="K17", category="极致压缩率", name="英文SLA报告-冗余过渡句",
        text=(
            "This document serves as the comprehensive monthly Service Level Agreement report for March 2024. "
            "It is important to begin by stating that overall system availability remained exceptionally strong. "
            "Specifically, our primary production environment achieved 99.97% uptime, exceeding our SLA target of 99.9%. "
            "It should be noted that this translates to only 13 minutes of total downtime across the entire month. "
            "As our engineering team continues to work diligently, API latency at P99 measured 245ms, well within the 500ms threshold. "
            "It is worth mentioning that error rate averaged 0.03%, significantly below the 0.1% SLA commitment. "
            "Furthermore, and this deserves special attention, our CDN edge cache hit ratio reached 94.2% globally. "
            "It goes without saying that bandwidth consumption was 45TB, a 12% increase from February. "
            "As many stakeholders will appreciate, we processed 8.9 billion API requests during the month without major incidents. "
            "It is noteworthy that the database cluster maintained replication lag under 50ms at all times. "
            "In terms of support metrics, which are equally important, average ticket resolution time was 2.3 hours for P1 issues. "
            "Broadly speaking, customer-reported incidents decreased by 18% compared to the previous month. "
            "In conclusion, all 14 SLA metrics met or exceeded their defined thresholds for the reporting period."
        ),
        context="March uptime and performance SLA metrics",
        must_keep=["99.97%", "99.9%", "13 minutes", "245ms", "500ms", "0.03%", "94.2%", "45TB", "8.9 billion", "50ms", "2.3 hours", "18%"],
        expect_compressed=True,
        target_ratio=0.4,
    ),
    TestCase(
        id="K18", category="极致压缩率", name="中文数据分析报告-冗余连接",
        text=(
            "基于对过去12个月用户行为数据的深入挖掘和全面分析，我们得出了以下有价值的结论。"
            "从用户画像角度来看，核心付费用户群体集中在25-35岁年龄段，占比为58%。"
            "值得特别关注的是，女性用户付费率为男性的1.5倍，达到了5.2%。"
            "经过详细的数据建模分析，用户生命周期价值(LTV)平均为¥680，最高可达¥3,200。"
            "需要说明的是，LTV前20%的用户贡献了总收入的72%，呈现典型的二八定律。"
            "从行为路径来看，高价值用户平均每周使用产品4.5次，会话时长中位数为23分钟。"
            "总的来说，注册后第3天是用户流失的关键节点，此时流失率高达35%。"
            "另外需要说明的是，如果用户在注册后48小时内完成了首次核心功能使用，"
            "其30天留存率将提升至52%，远高于平均的18%。"
            "从渠道ROI来看，微信生态获客的LTV/CAC为3.8x，抖音为2.1x，百度SEM为1.5x。"
            "值得一提的是，自然搜索(SEO)渠道虽然量小但LTV/CAC高达6.2x。"
            "综上所述，建议重点优化注册后48小时的新用户引导流程，并加大SEO投入。"
            "需要指出的是，上述分析基于987,654名样本用户的行为数据。"
        ),
        context="用户画像和LTV分析结论",
        must_keep=["25-35岁", "58%", "5.2%", "¥680", "¥3,200", "72%", "4.5次", "23分钟", "35%", "52%", "18%", "3.8x", "6.2x"],
        expect_compressed=True,
        target_ratio=0.4,
    ),
    TestCase(
        id="K19", category="极致压缩率", name="英文架构决策记录-冗余推理",
        text=(
            "This Architecture Decision Record documents our team's careful deliberation regarding the message queue selection. "
            "After extensive research, thorough evaluation, and many thoughtful discussions among all team members, "
            "we have decided to adopt Apache Kafka 3.6 as our primary event streaming platform. "
            "It is important to provide context by noting that we evaluated 5 alternatives: RabbitMQ, AWS SQS, Apache Pulsar, NATS, and Redis Streams. "
            "As everyone on the team agreed, our requirements include throughput of 500K messages per second, at-least-once delivery, and 7-day retention. "
            "It should be mentioned that Kafka's benchmark results showed sustained throughput of 850K msg/s on our test cluster of 6 brokers. "
            "Broadly speaking, partition count will be set to 128 per topic with replication factor 3 for durability. "
            "It is also worth noting that storage requirements are estimated at 12TB per month based on average message size of 2.4KB. "
            "As a matter of fact, the operational team already has significant Kafka expertise from managing our legacy cluster. "
            "Needless to say, this expertise significantly reduces the learning curve and operational risk. "
            "It goes without saying that monitoring will use Confluent Control Center with alerts on consumer lag exceeding 10,000 offsets. "
            "In conclusion, after very careful consideration, Kafka 3.6 best satisfies our technical and operational requirements. "
            "The migration from legacy RabbitMQ is planned for completion by 2024-06-30 with zero message loss."
        ),
        context="message queue technology selection rationale",
        must_keep=["Apache Kafka 3.6", "500K messages per second", "850K msg/s", "6 brokers", "128", "replication factor 3", "12TB", "2.4KB", "10,000 offsets", "2024-06-30"],
        expect_compressed=True,
        target_ratio=0.4,
    ),
    TestCase(
        id="K20", category="极致压缩率", name="中文产品发布公告-重复强调",
        text=(
            "我们非常高兴地宣布，经过产品团队6个月的精心打磨，DataInsight Pro V5.0正式发布！"
            "总的来说，这是一次具有里程碑意义的重大版本更新，包含了50多项新功能和200多项优化改进。"
            "首先，值得特别关注的是，我们全新推出了AI驱动的智能分析引擎SmartAnalyzer。"
            "需要说明的是，SmartAnalyzer能够在30秒内自动完成数据探索，识别关键趋势和异常。"
            "从技术角度来看，该引擎基于GPT-4和自研算法的混合架构，准确率达到了92%。"
            "其次，值得一提的是，数据连接器数量从原来的45种扩展到了78种。"
            "另外需要说明的是，新增了对Snowflake、Databricks和BigQuery的原生支持。"
            "从性能角度来看，大数据集查询速度提升了3倍，支持实时处理10亿级数据。"
            "第三，关于协作功能，我们推出了实时多人协同编辑功能，支持最多20人同时编辑同一报表。"
            "值得注意的是，版本控制采用了Git-like的分支管理机制。"
            "总的来说，V5.0的定价调整为：标准版¥999/月/用户，企业版¥2,499/月/用户。"
            "需要指出的是，现有用户可享受6折升级优惠，有效期至2024年4月30日。"
            "综上所述，DataInsight Pro V5.0代表了数据分析领域的新标杆。"
        ),
        context="V5.0核心新功能和定价",
        must_keep=["V5.0", "50多项", "SmartAnalyzer", "30秒", "92%", "78种", "Snowflake", "10亿级", "20人", "¥999", "¥2,499", "6折", "2024年4月30日"],
        expect_compressed=True,
        target_ratio=0.4,
    ),
]


# ═══════════════════════════════════════════════════════════════════════════════
# L. 无标点文本 — 验证降级分句逻辑
# ═══════════════════════════════════════════════════════════════════════════════

CASES_L: List[TestCase] = [
    TestCase(
        id="L01", category="无标点文本", name="OCR扫描-中文无句号",
        text=(
            "本季度销售数据显示华东区域收入达到3200万元，同比增长15%，"
            "其中新签客户贡献了约40%的增量，大客户续约率维持在88%以上，"
            "中小客户流失率有所上升达到了7.2%，主要原因是竞品价格战的影响，"
            "华南区域收入2100万元，环比增长8%，新开拓了金融和医疗两个垂直行业，"
            "西北区域收入680万元，低于预期的800万目标，主要受区域经济下行影响，"
            "合计全国收入7580万元，完成全年目标的62%，整体进度基本符合预期，"
            "但需要关注西北区域的追赶计划以及中小客户的留存问题，"
            "建议Q3加大中小客户成功团队的投入并适当调整定价策略，"
            "同时加快华南区域金融行业的深度拓展以弥补西北缺口"
        ),
        context="各区域销售完成情况",
        must_keep=["3200万元", "15%", "40%", "88%", "7.2%", "2100万元", "680万元", "7580万元", "62%"],
        expect_compressed=True,
        target_ratio=0.5,
    ),
    TestCase(
        id="L02", category="无标点文本", name="API响应拼接-无断句",
        text=(
            "用户ID为U20240315001的账户在2024年3月15日14时23分发起了一笔金额为$2,500的跨境转账，"
            "收款方为香港恒生银行账户HK-8834567，交易状态为pending review，"
            "风控系统标记了3个异常指标分别是金额超过历史均值5倍和非常用收款方和深夜时段交易，"
            "系统自动触发了人工审核流程，当前排队位置为第7位，"
            "预计审核等待时间为45分钟，审核完成后将通过短信和邮件通知用户，"
            "如果审核通过则预计T+1日到账，如果被拒则资金将在2小时内退回原账户，"
            "用户历史交易记录显示过去90天内共有23笔境外交易平均金额$480，"
            "本次交易金额明显偏高触发了大额交易监控规则AML-R005，"
            "建议审核人员重点核实交易背景和资金来源合规性"
        ),
        context="跨境转账风控审核详情",
        must_keep=["U20240315001", "$2,500", "HK-8834567", "pending review", "第7位", "45分钟", "T+1", "23笔", "$480", "AML-R005"],
        expect_compressed=True,
        target_ratio=0.5,
    ),
    TestCase(
        id="L03", category="无标点文本", name="日志拼接-纯逗号分隔",
        text=(
            "服务启动时间2024-03-15T08:00:15Z，加载配置文件config_prod.yaml成功，"
            "数据库连接池初始化完成pool_size=50，Redis连接已建立cluster_nodes=6，"
            "Kafka消费者组启动consumer_group=payment-processor，分配到partition 0-7，"
            "开始消费消息offset=1284567，处理速率稳定在2500msg/s，"
            "08:15:22检测到消息积压lag=15000，自动触发扩容scale_up=3，"
            "08:18:45扩容完成new_instances=8，消息积压开始消化lag_decreasing，"
            "08:25:00积压清除lag=0，处理速率恢复到3200msg/s，"
            "内存使用率72%，CPU使用率45%，GC暂停时间P99=12ms，"
            "08:30:00健康检查通过health_check=ok，所有依赖服务状态正常，"
            "截至08:30已成功处理消息总量458,923条，错误率0.002%"
        ),
        context="服务启动和消息处理状态",
        must_keep=["2024-03-15T08:00:15Z", "pool_size=50", "cluster_nodes=6", "2500msg/s", "lag=15000", "scale_up=3", "3200msg/s", "P99=12ms", "458,923", "0.002%"],
        expect_compressed=True,
        target_ratio=0.5,
    ),
    TestCase(
        id="L04", category="无标点文本", name="OCR发票信息-无标点",
        text=(
            "增值税专用发票发票代码3100214130发票号码08567234开票日期2024年03月12日"
            "购买方名称上海智创科技有限公司纳税人识别号91310115MA1K4XWE8J"
            "地址电话上海市浦东新区张江高科技园区碧波路690号021-50556789"
            "开户行及账号中国工商银行上海张江支行1001256709024563215"
            "货物名称信息技术服务费规格型号SaaS年度订阅单位项数量1"
            "单价398000.00金额398000.00税率6%税额23880.00"
            "价税合计大写肆拾贰万壹仟捌佰捌拾元整小写421880.00"
            "销售方名称北京数据云科技股份有限公司纳税人识别号91110108MA01B48T3K"
            "备注合同编号HT-2024-0315服务期限2024年4月至2025年3月"
        ),
        context="发票关键信息提取",
        must_keep=["3100214130", "08567234", "2024年03月12日", "91310115MA1K4XWE8J", "398000.00", "6%", "23880.00", "421880.00", "HT-2024-0315"],
        expect_compressed=True,
        target_ratio=0.5,
    ),
    TestCase(
        id="L05", category="无标点文本", name="英文OCR-连续无标点",
        text=(
            "Server performance report for cluster prod-us-east-1 covering the period March 1 to March 31 2024 "
            "total requests processed 2.8 billion with average response time of 89ms at P50 and 312ms at P99 "
            "peak traffic observed on March 15 at 14:00 UTC reaching 125K requests per second "
            "CPU utilization averaged 62% across 48 nodes with max spike to 91% during peak "
            "memory consumption stable at 78% of allocated 384GB per node "
            "disk IO throughput measured at 2.4GB/s read and 800MB/s write on NVMe storage "
            "network bandwidth utilization 45% of available 100Gbps inter-node connectivity "
            "error rate maintained below 0.01% throughout the reporting period "
            "auto-scaling events triggered 7 times adding temporary capacity of 12 additional nodes "
            "estimated infrastructure cost for the month $485,000 representing 8% under budget"
        ),
        context="cluster performance and resource utilization",
        must_keep=["prod-us-east-1", "2.8 billion", "89ms", "312ms", "125K", "48 nodes", "91%", "384GB", "2.4GB/s", "100Gbps", "0.01%", "$485,000"],
        expect_compressed=True,
        target_ratio=0.5,
    ),
    TestCase(
        id="L06", category="无标点文本", name="中文聊天记录-无断句",
        text=(
            "客户说他们的系统从昨天晚上开始就一直报错，错误信息是Connection refused to host 10.0.5.23 port 5432，"
            "他们已经尝试了重启服务和检查网络配置但问题没有解决，"
            "我查了一下监控发现那台数据库服务器的磁盘使用率已经达到了98%，"
            "WAL日志积压了大约200GB没有被清理，原因是replica节点在3月14日就断开了连接，"
            "导致primary无法推进checkpoint，WAL持续增长直到磁盘满，"
            "紧急处理方案是先手动清理过期的WAL文件释放空间然后重建replica连接，"
            "长期方案需要配置WAL保留策略max_wal_size=64GB并添加磁盘空间告警阈值为85%，"
            "另外建议将数据盘从500GB扩容到1TB以应对业务增长，"
            "预计修复时间30分钟，需要客户配合重启应用以重新建立数据库连接"
        ),
        context="数据库连接失败故障排查",
        must_keep=["10.0.5.23", "5432", "98%", "200GB", "3月14日", "WAL", "max_wal_size=64GB", "85%", "500GB", "1TB", "30分钟"],
        expect_compressed=True,
        target_ratio=0.5,
    ),
    TestCase(
        id="L07", category="无标点文本", name="产品配置清单-无句末标点",
        text=(
            "基础套餐Standard配置如下，包含5个用户席位，存储空间50GB，API调用量10万次/月，"
            "支持数据源连接数最多10个，报表数量不限，仪表板最多20个，"
            "数据刷新频率为每小时一次，不含实时推送功能，"
            "专业套餐Pro配置包含20个用户席位，存储空间500GB，API调用量100万次/月，"
            "支持数据源连接数最多50个，报表和仪表板数量均不限，"
            "数据刷新频率为每15分钟一次，包含实时推送和告警功能，"
            "企业套餐Enterprise配置包含无限用户席位，存储空间5TB，API调用量不限，"
            "支持数据源连接数不限，所有功能全开放包括自定义开发和私有化部署，"
            "数据刷新频率为实时（延迟<1秒），包含7x24小时专属技术支持，"
            "定价方面Standard为¥299/月，Pro为¥999/月，Enterprise为¥4,999/月起"
        ),
        context="各套餐配置和定价对比",
        must_keep=["5个用户", "50GB", "10万次/月", "20个用户", "500GB", "100万次/月", "5TB", "<1秒", "¥299", "¥999", "¥4,999"],
        expect_compressed=True,
        target_ratio=0.5,
    ),
    TestCase(
        id="L08", category="无标点文本", name="英文技术规格-连续参数",
        text=(
            "Hardware specifications for the new ML training cluster deployment include "
            "8 nodes each equipped with 4x NVIDIA A100 80GB GPUs connected via NVLink 600GB/s "
            "host memory 1TB DDR5 per node with CPU being dual AMD EPYC 9654 96-core processors "
            "local storage 15.36TB NVMe SSD per node configured in RAID-10 for boot and scratch "
            "network interconnect 400Gbps InfiniBand HDR between all nodes in fat-tree topology "
            "shared storage NetApp AFF A900 providing 2PB usable capacity with 20GB/s throughput "
            "power consumption estimated at 42KW total requiring 3 phase 480V supply "
            "cooling requirements 150KW of cooling capacity with redundant CRAC units "
            "estimated total cost $4.2M including 3 year hardware warranty and support contract "
            "deployment timeline 6 weeks from order to production ready "
            "expected training throughput 2.5x improvement over current V100 cluster on LLM workloads"
        ),
        context="ML cluster hardware specifications",
        must_keep=["8 nodes", "A100 80GB", "NVLink 600GB/s", "1TB DDR5", "EPYC 9654", "15.36TB", "400Gbps", "2PB", "42KW", "$4.2M"],
        expect_compressed=True,
        target_ratio=0.5,
    ),
    TestCase(
        id="L09", category="无标点文本", name="中文问诊记录-口语无标点",
        text=(
            "患者主诉最近一周持续头痛，部位主要集中在右侧太阳穴附近，疼痛评分6/10，"
            "每天发作2-3次，每次持续约30分钟到1小时，服用布洛芬400mg后约20分钟缓解，"
            "伴随症状有轻度恶心但无呕吐，无视觉模糊或闪光感，无肢体麻木，"
            "既往史有偏头痛家族史（母亲），本人5年前曾有类似发作但频率较低每月1-2次，"
            "近期生活变化包括工作压力增大连续加班2周每天睡眠不足5小时，"
            "体检血压135/85mmHg偏高，心率78次/分，体温36.5度，BMI 26.8偏胖，"
            "初步诊断考虑紧张型头痛伴偏头痛特征，建议完善头颅MRI排除器质性病变，"
            "处方开具双氯芬酸钠75mg和盐酸氟桂利嗪5mg每晚一次，"
            "嘱患者调整作息保证7小时以上睡眠并减少屏幕使用时间，2周后复诊"
        ),
        context="头痛患者诊断和治疗方案",
        must_keep=["6/10", "2-3次", "30分钟", "布洛芬400mg", "135/85mmHg", "78次/分", "BMI 26.8", "MRI", "双氯芬酸钠75mg", "氟桂利嗪5mg"],
        expect_compressed=True,
        target_ratio=0.5,
    ),
    TestCase(
        id="L10", category="无标点文本", name="英文邮件正文-意识流写法",
        text=(
            "Hi team just wanted to give a quick update on where we stand with the Q2 OKR planning "
            "so basically after discussing with leadership we have been given a budget of $2.8M for the quarter "
            "which is actually 15% more than Q1 so that is good news "
            "the main priorities they want us to focus on are first expanding to the EU market targeting 500 new customers "
            "second improving platform reliability to 99.99% from current 99.95% "
            "and third launching the self-service onboarding flow to reduce time-to-value from 14 days to 3 days "
            "in terms of headcount we have approval to hire 8 engineers and 3 product managers "
            "the timeline for all of this is fairly aggressive with EU launch targeted for May 15 "
            "reliability improvements need to be done by end of April "
            "and self-service onboarding MVP should be ready for beta by June 1 "
            "I think we can make it work but it will require careful prioritization and probably some scope trade-offs "
            "lets sync on Thursday at 2pm PST to finalize the plan and assign DRIs for each objective"
        ),
        context="Q2 planning budget and priorities",
        must_keep=["$2.8M", "15%", "500 new customers", "99.99%", "99.95%", "14 days", "3 days", "8 engineers", "May 15", "June 1"],
        expect_compressed=True,
        target_ratio=0.5,
    ),
    TestCase(
        id="L11", category="无标点文本", name="中文产品评论-无标点口语",
        text=(
            "用了这个产品大概3个月了整体感觉还不错，主要是数据分析功能比较强大，"
            "之前用的某友的系统光是出一张报表就要等5分钟，现在只需要15秒就搞定了，"
            "而且支持自定义维度交叉分析这个功能非常实用，"
            "但是也有一些不太满意的地方，比如移动端的体验还是比较差，"
            "很多功能在手机上用不了只能用电脑，还有就是价格确实偏高，"
            "我们买的企业版一年要花¥128,000，对于50人的团队来说人均¥2,560/年，"
            "竞品大概只要¥1,800/年/人，不过考虑到效率提升和时间节省还是值得的，"
            "据我估算每个分析师每月能节省大约20小时的报表制作时间，"
            "按时薪¥150计算每人每月节省¥3,000，12个分析师一年节省¥432,000，"
            "ROI大概是3.4倍所以还是推荐购买的，希望后续能改善移动端体验和价格"
        ),
        context="产品使用体验和ROI分析",
        must_keep=["3个月", "5分钟", "15秒", "¥128,000", "50人", "¥2,560", "¥1,800", "20小时", "¥3,000", "¥432,000", "3.4倍"],
        expect_compressed=True,
        target_ratio=0.5,
    ),
    TestCase(
        id="L12", category="无标点文本", name="中文设备巡检-纯列举",
        text=(
            "机房A区巡检记录2024年3月15日09:00，UPS电源状态正常输入电压380V输出电压220V负载率62%，"
            "备用电池组剩余容量89%预计可支撑时间45分钟，"
            "精密空调1号机运行正常送风温度22.5度回风温度28.3度湿度45%RH，"
            "精密空调2号机运行正常送风温度22.8度回风温度27.9度湿度44%RH，"
            "机柜温度最高点为C排第8柜顶部达到34.2度已接近告警阈值35度需关注，"
            "网络核心交换机Nexus 9508运行时间456天端口利用率78%无告警，"
            "存储阵列NetApp FAS8700健康状态绿色磁盘使用率73%预计可用容量32TB，"
            "消防系统FM-200气体灭火系统压力正常14.5MPa烟感报警器自检通过，"
            "门禁系统正常本日共12人次进出最后出入记录08:55运维工程师张伟，"
            "总体评估A区设备运行正常需重点关注C8柜温度趋势"
        ),
        context="机房设备运行状态",
        must_keep=["380V", "220V", "62%", "89%", "45分钟", "22.5度", "34.2度", "35度", "Nexus 9508", "456天", "73%", "32TB", "14.5MPa"],
        expect_compressed=True,
        target_ratio=0.5,
    ),
    TestCase(
        id="L13", category="无标点文本", name="英文配置文件描述-连续参数",
        text=(
            "Production environment configuration for payment-service v3.2.1 deployed on 2024-03-10 "
            "database primary endpoint rds-prod-payment.cluster-abc123.us-east-1.rds.amazonaws.com port 5432 "
            "read replica endpoints rds-prod-payment-ro1 and rds-prod-payment-ro2 "
            "connection pool minimum 20 maximum 100 idle timeout 300s validation interval 30s "
            "Redis cluster endpoint redis-prod-payment.abc123.ng.0001.use1.cache.amazonaws.com port 6379 "
            "cache TTL for session 900s for rate-limit 60s for idempotency-key 86400s "
            "Kafka bootstrap servers kafka-prod-1.internal:9092 kafka-prod-2.internal:9092 kafka-prod-3.internal:9092 "
            "consumer group payment-processor-prod auto offset reset latest max poll records 500 "
            "circuit breaker failure threshold 5 timeout 30s half-open requests 3 reset interval 60s "
            "rate limiting 1000 requests per second per merchant with burst allowance of 1500 "
            "encryption at rest using AWS KMS key alias/payment-prod-key rotation every 90 days"
        ),
        context="payment service production configuration details",
        must_keep=["v3.2.1", "2024-03-10", "port 5432", "100", "300s", "port 6379", "900s", "86400s", "9092", "500", "1000 requests per second", "90 days"],
        expect_compressed=True,
        target_ratio=0.5,
    ),
    TestCase(
        id="L14", category="无标点文本", name="中文需求描述-口语连续",
        text=(
            "客户那边提了一个比较紧急的需求，大概是这样的，"
            "他们想要在现有的CRM系统里面增加一个批量导入客户数据的功能，"
            "数据格式支持CSV和Excel两种，单次导入上限10万条记录，"
            "导入过程中需要做数据校验包括手机号格式校验和邮箱去重和必填字段检查，"
            "校验不通过的记录要单独导出为错误报告方便客户修改后重新导入，"
            "另外他们还要求导入过程可以设置字段映射因为他们不同部门的Excel表头不一样，"
            "完成导入后需要自动触发客户分群规则把新导入的客户分配到对应的销售组，"
            "分配规则是按区域划分华东华南华北西部四个大区各对应一个销售团队，"
            "时间要求是2周内完成开发和测试因为他们4月1日有一波大批量客户数据需要导入，"
            "预计数据量大约8万条包含公司名称联系人手机号邮箱地址行业分类等15个字段"
        ),
        context="批量导入功能需求和时间要求",
        must_keep=["CSV", "Excel", "10万条", "手机号", "邮箱去重", "字段映射", "2周", "4月1日", "8万条", "15个字段"],
        expect_compressed=True,
        target_ratio=0.5,
    ),
    TestCase(
        id="L15", category="无标点文本", name="英文测试报告-结果拼接",
        text=(
            "Automated test execution summary for release candidate RC-4.1.0 build 2847 executed on 2024-03-14 "
            "total test cases 3,456 passed 3,389 failed 42 skipped 25 pass rate 98.1% "
            "unit tests 2,100 passed 2,098 failed 2 coverage 87.3% "
            "integration tests 890 passed 872 failed 18 average duration 4.2s "
            "end-to-end tests 466 passed 419 failed 22 skipped 25 average duration 45s "
            "critical path tests all 128 scenarios passed including payment flow and user registration "
            "performance regression tests 3 failures detected response time for /api/search increased from 120ms to 340ms "
            "memory leak suspected in WebSocket handler growing 50MB per hour under load test "
            "flaky test analysis 8 tests identified as flaky with failure rate between 5% and 15% "
            "recommended actions fix 2 P1 failures in payment refund flow before release "
            "investigate search API regression and WebSocket memory issue as P2 "
            "target release date 2024-03-18 pending P1 fix verification"
        ),
        context="RC build test results and blocking issues",
        must_keep=["RC-4.1.0", "3,456", "98.1%", "87.3%", "4.2s", "128 scenarios", "120ms", "340ms", "50MB", "2024-03-18"],
        expect_compressed=True,
        target_ratio=0.5,
    ),
]


# ═══════════════════════════════════════════════════════════════════════════════
# M. 超长句内压缩 — 极少句但极长文本
# ═══════════════════════════════════════════════════════════════════════════════

CASES_M: List[TestCase] = [
    TestCase(
        id="M01", category="超长句内压缩", name="英文复合长句-技术描述",
        text=(
            "The distributed event-driven architecture that we have implemented for the real-time analytics platform "
            "utilizes Apache Kafka as the central message broker with a throughput capacity of 2 million events per second, "
            "which feeds into a Flink streaming processing layer that performs window-based aggregations with tumbling windows "
            "of 5 seconds and sliding windows of 30 seconds, and the processed results are then stored in a time-series "
            "database InfluxDB with a retention policy of 90 days for raw data and 365 days for aggregated metrics, "
            "while simultaneously pushing real-time updates through WebSocket connections to the frontend dashboard "
            "that supports up to 10,000 concurrent users with a P99 latency of under 200 milliseconds from event ingestion "
            "to dashboard display, and the entire system is deployed across 3 availability zones with automatic failover "
            "configured with a recovery time objective of 30 seconds and recovery point objective of zero data loss "
            "through synchronous replication, which has been validated through monthly chaos engineering exercises "
            "that randomly terminate up to 33% of the processing nodes without any observable impact on end-user experience."
        ),
        context="real-time analytics architecture and performance",
        must_keep=["2 million events per second", "Kafka", "Flink", "5 seconds", "InfluxDB", "90 days", "10,000 concurrent", "200 milliseconds", "30 seconds", "33%"],
        expect_compressed=True,
        target_ratio=0.5,
    ),
    TestCase(
        id="M02", category="超长句内压缩", name="中文超长逗号句-数据库设计",
        text=(
            "在本次数据库架构重构方案中，我们决定将原有的单体MySQL实例拆分为按业务域划分的独立数据库集群，"
            "其中用户服务使用PostgreSQL 15作为主库配置为3节点的Patroni高可用集群，读写分离比例为1:4，"
            "订单服务继续使用MySQL 8.0但升级为InnoDB Cluster模式配置group_replication支持多主写入，"
            "分片策略采用按用户ID哈希取模分为256个逻辑分片映射到16个物理节点上，"
            "每个分片预计承载约200万条订单记录和50GB数据量，"
            "支付服务由于对一致性要求最高采用CockroachDB分布式数据库部署9节点集群跨3个机房，"
            "事务隔离级别设为Serializable保证强一致性牺牲部分性能延迟约增加15ms，"
            "搜索服务独立使用Elasticsearch 8.x集群配置15个数据节点3个master节点索引分片数为30，"
            "缓存层统一使用Redis 7.0 Cluster模式配置128个slot分布在8个节点上，"
            "数据同步通过Debezium CDC实现变更捕获延迟控制在500ms以内实现准实时数据一致性"
        ),
        context="数据库拆分方案和技术选型",
        must_keep=["PostgreSQL 15", "3节点", "1:4", "MySQL 8.0", "256个逻辑分片", "16个物理节点", "200万条", "CockroachDB", "15ms", "Elasticsearch 8.x", "128个slot", "500ms"],
        expect_compressed=True,
        target_ratio=0.5,
    ),
    TestCase(
        id="M03", category="超长句内压缩", name="英文单句-法律条款",
        text=(
            "Notwithstanding any other provision of this Agreement to the contrary, in the event that the Licensee's "
            "total annual revenue exceeds $50 million USD or the Licensee's total number of active end users exceeds "
            "500,000 in any rolling twelve-month period, the Licensee shall be required to upgrade to the Enterprise "
            "tier within 30 calendar days of exceeding either threshold, which shall result in an increase of the "
            "annual license fee from the current rate of $120,000 to $450,000, payable in quarterly installments "
            "of $112,500 each, with the first payment due within 15 business days of the tier upgrade notification, "
            "and failure to complete the upgrade within the specified timeframe shall constitute a material breach "
            "of this Agreement entitling the Licensor to terminate the license with 10 days written notice and seek "
            "damages equal to 150% of the difference between the actual fees paid and the Enterprise tier fees that "
            "should have been paid from the date the threshold was first exceeded, plus reasonable attorney fees "
            "and costs incurred in enforcing this provision, provided however that the Licensee shall have a one-time "
            "cure period of 45 days upon receiving the breach notice during which full compliance will waive any penalties."
        ),
        context="license tier upgrade triggers and penalties",
        must_keep=["$50 million", "500,000", "30 calendar days", "$120,000", "$450,000", "$112,500", "15 business days", "10 days", "150%", "45 days"],
        expect_compressed=True,
        target_ratio=0.5,
    ),
    TestCase(
        id="M04", category="超长句内压缩", name="中文跑题长句-产品规划",
        text=(
            "根据我们对市场趋势的深入分析以及与超过50家核心客户的深度访谈结果，"
            "我们认为2024年下半年的产品演进方向应该聚焦在三个核心领域，"
            "第一是AI原生能力的深度集成预计投入研发资源40人月总预算¥800万，"
            "包括但不限于自然语言查询功能让用户可以用自然语言代替SQL进行数据分析，"
            "智能异常检测功能基于时序预测算法自动发现业务指标的异常波动并推送告警，"
            "以及AI辅助报表生成功能根据用户描述自动生成可视化报表和分析结论，"
            "第二是协作和工作流能力的增强预计投入25人月预算¥500万，"
            "包括多人实时协同编辑功能支持最多30人同时操作同一份数据看板，"
            "基于角色的审批工作流让数据分析报告可以走正式的评审和发布流程，"
            "以及跨团队的数据资产共享市场让不同部门可以发布和订阅彼此的数据集和分析模板，"
            "第三是性能和规模的突破预计投入20人月预算¥400万，"
            "目标是支持单租户100亿级数据量的交互式分析查询响应时间控制在3秒以内"
        ),
        context="下半年产品规划核心方向和预算",
        must_keep=["50家", "40人月", "¥800万", "SQL", "25人月", "¥500万", "30人", "20人月", "¥400万", "100亿级", "3秒"],
        expect_compressed=True,
        target_ratio=0.5,
    ),
    TestCase(
        id="M05", category="超长句内压缩", name="英文超长技术规范-API设计",
        text=(
            "The RESTful API for the user management service shall expose the following endpoints with their respective "
            "rate limits and authentication requirements: POST /api/v2/users for creating new user accounts limited to "
            "100 requests per minute per API key requiring OAuth 2.0 bearer token with scope user:write, "
            "GET /api/v2/users/{id} for retrieving individual user profiles limited to 1000 requests per minute "
            "requiring scope user:read with optional fields parameter supporting partial responses to reduce payload size, "
            "PATCH /api/v2/users/{id} for updating user attributes limited to 200 requests per minute requiring scope "
            "user:write with optimistic concurrency control via ETag headers returning 409 Conflict on version mismatch, "
            "DELETE /api/v2/users/{id} for soft-deleting users limited to 50 requests per minute requiring scope "
            "user:admin with mandatory reason parameter and 30-day grace period before permanent deletion, "
            "and GET /api/v2/users with pagination support using cursor-based pagination with default page size of 50 "
            "and maximum of 200 records per page with total count header and next/prev link headers following RFC 8288 "
            "Web Linking standard, and all endpoints shall return responses in JSON:API format with proper HATEOAS links "
            "and support content negotiation via Accept header for JSON and Protocol Buffers serialization formats."
        ),
        context="user management API endpoints and rate limits",
        must_keep=["POST /api/v2/users", "100 requests per minute", "user:write", "GET /api/v2/users/{id}", "1000 requests per minute", "PATCH", "ETag", "409 Conflict", "DELETE", "50 requests per minute", "30-day", "RFC 8288"],
        expect_compressed=True,
        target_ratio=0.5,
    ),
    TestCase(
        id="M06", category="超长句内压缩", name="中文超长句-融资条款",
        text=(
            "本轮B+轮融资由红杉中国领投金额为$3,000万美元，跟投方包括经纬创投和高瓴资本，"
            "投后估值$4.5亿美元，本轮融资将主要用于三个方向，"
            "其中50%即$1,500万用于产品研发重点是AI能力和国际化版本的开发，"
            "30%即$900万用于市场拓展包括北美和东南亚两个目标市场的本地化运营团队搭建，"
            "20%即$600万用于人才引进计划在未来12个月内将技术团队从现有的120人扩充到200人，"
            "投资人要求的对赌条款包括2025年ARR需达到$8,000万且年增长率不低于80%，"
            "否则创始团队需额外让渡5%的股份作为业绩补偿，"
            "同时本轮投资人享有2倍优先清算权和反稀释保护条款采用加权平均法计算，"
            "创始团队锁定期延长至IPO后18个月，员工期权池从10%扩大到15%，"
            "新设立的ESOP池将在未来24个月内按季度分4批发放给核心员工"
        ),
        context="B+轮融资条款和资金用途",
        must_keep=["$3,000万", "红杉中国", "$4.5亿", "50%", "$1,500万", "30%", "$900万", "120人", "200人", "$8,000万", "80%", "5%", "2倍", "15%"],
        expect_compressed=True,
        target_ratio=0.5,
    ),
    TestCase(
        id="M07", category="超长句内压缩", name="英文超长句-安全合规",
        text=(
            "In accordance with the General Data Protection Regulation (GDPR) Article 32 and the California Consumer "
            "Privacy Act (CCPA) Section 1798.150, our organization has implemented comprehensive technical and "
            "organizational measures including but not limited to AES-256 encryption for all data at rest across "
            "all storage systems including databases, file systems, and backup media, TLS 1.3 with perfect forward "
            "secrecy for all data in transit between services and external endpoints, role-based access control (RBAC) "
            "with principle of least privilege enforced through automated policy engines that review and revoke unused "
            "permissions every 90 days, multi-factor authentication required for all employees and contractors with "
            "hardware security keys mandatory for anyone with access to production systems or customer data, "
            "data retention policies that automatically purge personal data after 730 days unless subject to legal hold, "
            "annual penetration testing by certified third-party auditors with findings remediated within 30 days for "
            "critical issues and 90 days for high-severity issues, and a dedicated Data Protection Officer reporting "
            "directly to the Chief Executive Officer with authority to halt any processing activity deemed non-compliant, "
            "with the overall compliance program audited annually against ISO 27001 and SOC 2 Type II standards."
        ),
        context="data protection compliance measures",
        must_keep=["GDPR", "CCPA", "AES-256", "TLS 1.3", "RBAC", "90 days", "730 days", "30 days", "ISO 27001", "SOC 2 Type II"],
        expect_compressed=True,
        target_ratio=0.5,
    ),
    TestCase(
        id="M08", category="超长句内压缩", name="中文超长句-项目规划",
        text=(
            "经过项目管理委员会的充分评估和讨论，我们决定将数据中台建设项目分为四个阶段执行，"
            "第一阶段为基础设施搭建阶段时间范围2024年4月到6月预算¥1,200万主要目标是完成"
            "Hadoop集群从CDH 6.x到CDP 7.1的升级以及配套的Hive 3.1和Spark 3.4环境部署，"
            "第二阶段为数据治理阶段时间范围2024年7月到9月预算¥800万重点完成数据资产目录建设"
            "覆盖全公司1,500+数据表的元数据采集和血缘关系梳理以及数据质量规则的制定和落地，"
            "第三阶段为服务化阶段时间范围2024年10月到12月预算¥600万核心任务是将数据能力封装为"
            "标准化的DataAPI对外提供统一的数据查询和分析服务目标是支持日均500万次API调用，"
            "第四阶段为智能化阶段时间范围2025年1月到3月预算¥400万重点是引入ML Pipeline"
            "支持自动化的特征工程和模型训练全流程管理目标覆盖20+业务场景的智能预测能力"
        ),
        context="数据中台建设分阶段计划",
        must_keep=["¥1,200万", "CDH 6.x", "CDP 7.1", "Hive 3.1", "Spark 3.4", "¥800万", "1,500+", "¥600万", "500万次", "¥400万", "20+"],
        expect_compressed=True,
        target_ratio=0.5,
    ),
    TestCase(
        id="M09", category="超长句内压缩", name="英文超长句-架构决策",
        text=(
            "After conducting a thorough evaluation of container orchestration platforms over a period of 6 weeks "
            "during which the infrastructure team tested Kubernetes, Docker Swarm, Apache Mesos, and HashiCorp Nomad "
            "against our specific requirements of supporting 500+ microservices with automatic scaling based on custom "
            "metrics including request queue depth and ML model inference latency, we have unanimously decided to "
            "standardize on Kubernetes 1.28 deployed through Amazon EKS with a control plane spanning 3 availability "
            "zones, worker node groups configured with mixed instance types ranging from m6i.2xlarge for general "
            "workloads to p4d.24xlarge for GPU-intensive ML inference services, cluster autoscaler set to maintain "
            "a 30% headroom buffer with scale-up time under 90 seconds using Karpenter for node provisioning, "
            "service mesh implemented via Istio 1.20 with mutual TLS enforced for all east-west traffic and "
            "Envoy sidecar proxies handling circuit breaking with a 5-second timeout and 3-retry policy, "
            "observability stack consisting of Prometheus for metrics with 15-second scrape interval, "
            "Grafana Loki for log aggregation with 30-day retention, and Jaeger for distributed tracing "
            "sampling at 1% for production traffic and 100% for error traces."
        ),
        context="container orchestration platform decision",
        must_keep=["Kubernetes 1.28", "500+", "Amazon EKS", "3 availability zones", "m6i.2xlarge", "p4d.24xlarge", "30%", "90 seconds", "Istio 1.20", "5-second", "15-second", "30-day", "1%"],
        expect_compressed=True,
        target_ratio=0.5,
    ),
    TestCase(
        id="M10", category="超长句内压缩", name="中文超长句-竞品分析",
        text=(
            "通过对主要竞品的全面对比分析，我们发现竞品A在产品功能层面覆盖了我们85%的核心场景但在"
            "实时分析能力上存在明显短板其查询延迟平均在8-15秒而我们的P95延迟仅为2.3秒，"
            "竞品B的定价策略极具侵略性其企业版价格仅为我们的60%即¥599/用户/月但其产品成熟度不足"
            "上线仅18个月且客户规模仅有800家企业客户远低于我们的3,500家，"
            "竞品C获得了最新一轮$1.2亿融资主要在AI能力方面投入较大"
            "已经推出了基于GPT-4的自然语言查询功能月活跃使用率达到了35%，"
            "而我们的类似功能还在研发中预计6月上线，"
            "综合来看我们的核心优势在于性能(比竞品快3-5倍)和客户规模(行业第一)，"
            "短板在于AI能力落后竞品C约6个月以及价格高于竞品B约40%"
        ),
        context="竞品对比分析核心结论",
        must_keep=["85%", "8-15秒", "2.3秒", "60%", "¥599", "18个月", "800家", "3,500家", "$1.2亿", "GPT-4", "35%", "3-5倍", "40%"],
        expect_compressed=True,
        target_ratio=0.5,
    ),
    TestCase(
        id="M11", category="超长句内压缩", name="英文超长句-机器学习pipeline",
        text=(
            "The end-to-end machine learning pipeline that powers our recommendation system processes approximately "
            "850 million user interaction events daily through a feature engineering stage that computes 2,400 features "
            "across 6 categories including user demographics, behavioral sequences, item attributes, contextual signals, "
            "cross-feature interactions, and temporal patterns, which are then fed into a two-tower neural network "
            "architecture with the user tower containing 4 transformer layers with 12 attention heads and embedding "
            "dimension of 256, and the item tower using a 3-layer MLP with dimensions 512-256-128, both towers "
            "producing 128-dimensional embeddings that are compared using cosine similarity during serving with "
            "approximate nearest neighbor search via FAISS index containing 15 million item vectors updated every "
            "6 hours, achieving a recall@100 of 78.5% and NDCG@10 of 0.342 on our offline evaluation dataset "
            "of 50 million labeled interactions, with the model retrained weekly on 4 A100 GPUs taking approximately "
            "8 hours per training run using a learning rate of 1e-4 with cosine annealing schedule."
        ),
        context="recommendation ML pipeline architecture",
        must_keep=["850 million", "2,400 features", "4 transformer layers", "12 attention heads", "256", "128-dimensional", "FAISS", "15 million", "6 hours", "78.5%", "0.342", "4 A100", "8 hours", "1e-4"],
        expect_compressed=True,
        target_ratio=0.5,
    ),
    TestCase(
        id="M12", category="超长句内压缩", name="中文超长逗号句-运维规范",
        text=(
            "生产环境变更管理规范要求所有变更必须经过以下完整流程，"
            "首先变更发起人需要在ITSM系统中提交变更申请单包含变更原因和影响范围评估和回滚方案，"
            "然后由变更经理在每周二和周四的CAB会议上进行评审会议参与者包括架构师和QA和DBA和SRE，"
            "评审通过后变更执行窗口仅限周一到周四的凌晨2:00-6:00时段，"
            "周五到周日以及法定节假日禁止执行任何非紧急变更，"
            "变更执行前必须确认已完成以下检查项：备份验证通过备份RPO<1小时和"
            "监控告警已静默相关规则和通知相关业务方和准备好回滚脚本经过测试环境验证，"
            "变更执行过程中需要保持WarRoom在线所有相关人员5分钟内响应，"
            "变更完成后需要持续观察30分钟确认核心指标无异常才能关闭变更窗口，"
            "紧急变更(P0/P1)可以跳过CAB评审但必须由2名L4及以上工程师联合审批"
            "且事后48小时内补充完整的变更复盘报告提交给技术VP"
        ),
        context="生产变更流程和规范要求",
        must_keep=["ITSM", "周二", "周四", "CAB", "2:00-6:00", "RPO<1小时", "5分钟", "30分钟", "P0/P1", "2名", "L4", "48小时"],
        expect_compressed=True,
        target_ratio=0.5,
    ),
    TestCase(
        id="M13", category="超长句内压缩", name="英文超长句-SaaS合同条款",
        text=(
            "This Enterprise Subscription Agreement provides Customer with access to the Platform for a term of "
            "36 months commencing on the Effective Date at an annual subscription fee of $480,000 payable in advance "
            "within 30 days of each annual anniversary, with automatic renewal for successive 12-month periods unless "
            "either party provides written notice of non-renewal at least 90 days prior to the then-current term expiration, "
            "and the subscription includes up to 500 named users with the ability to purchase additional user packs "
            "in increments of 50 at $800 per user per year, and the Platform shall maintain availability of no less "
            "than 99.95% measured monthly excluding scheduled maintenance windows of up to 4 hours per month "
            "communicated at least 72 hours in advance, and in the event availability falls below the SLA threshold "
            "Customer shall receive service credits equal to 10% of monthly fees for each 0.1% below target "
            "up to a maximum credit of 30% of monthly fees, and Customer data shall be stored exclusively within "
            "the designated geographic region selected at onboarding with no cross-border transfer except as required "
            "to fulfill the service and disclosed in the Data Processing Addendum."
        ),
        context="enterprise subscription pricing and SLA terms",
        must_keep=["36 months", "$480,000", "30 days", "12-month", "90 days", "500 named users", "50", "$800", "99.95%", "4 hours", "72 hours", "10%", "30%"],
        expect_compressed=True,
        target_ratio=0.5,
    ),
    TestCase(
        id="M14", category="超长句内压缩", name="中文超长句-技术债务清单",
        text=(
            "技术债务梳理结果如下按严重程度排序，S级债务3项分别是支付服务仍在使用已EOL的Spring Boot 2.3"
            "存在已知的RCE漏洞CVE-2023-34055需要在4月30日前完成升级至3.2版本预计工作量15人天，"
            "用户鉴权模块的JWT密钥轮换机制缺失自系统上线以来2年未更换过签名密钥"
            "一旦泄露将导致全量用户token被伪造影响320万用户需要在2周内实现自动轮换机制，"
            "以及订单数据库的分库分表策略已到达扩展瓶颈单表数据量突破5亿行查询P99从200ms劣化到1.8s"
            "需要在Q2完成重新分片预计需要30人天和3次停机迁移每次窗口2小时，"
            "A级债务5项包括前端还在使用React 16需升级到18和CI流水线缺少安全扫描环节"
            "和监控覆盖率仅72%低于90%标准和3个服务缺少优雅关闭逻辑和文档覆盖率仅45%"
        ),
        context="技术债务严重程度和修复计划",
        must_keep=["S级", "Spring Boot 2.3", "CVE-2023-34055", "4月30日", "15人天", "2年", "320万", "2周", "5亿行", "200ms", "1.8s", "30人天", "2小时", "React 16", "72%"],
        expect_compressed=True,
        target_ratio=0.5,
    ),
    TestCase(
        id="M15", category="超长句内压缩", name="英文超长句-incident报告",
        text=(
            "On March 12, 2024 at 14:23 UTC, our monitoring system detected an anomalous spike in error rates "
            "across the payment processing service which escalated from the baseline of 0.02% to 12.5% within "
            "a 3-minute window, triggering an automatic PagerDuty alert to the on-call engineer who acknowledged "
            "the incident at 14:26 UTC and immediately initiated the incident response protocol by creating "
            "a war room in Slack channel #inc-20240312-payment, and initial investigation revealed that the root "
            "cause was a cascading failure initiated by a configuration change deployed at 14:20 UTC that modified "
            "the connection timeout from 5000ms to 500ms which caused all connections to the downstream fraud "
            "detection service to time out because that service had a P99 latency of 480ms under normal load, "
            "and the cascading effect caused the circuit breaker to open after 50 consecutive failures which then "
            "caused all payment requests to fail with HTTP 503 status code, with total impact being 8,453 failed "
            "transactions representing approximately $2.1M in lost revenue over the 18-minute incident duration "
            "before the configuration was reverted at 14:41 UTC and services fully recovered by 14:44 UTC."
        ),
        context="payment service incident root cause and impact",
        must_keep=["March 12, 2024", "14:23 UTC", "0.02%", "12.5%", "14:20 UTC", "5000ms", "500ms", "480ms", "50 consecutive", "503", "8,453", "$2.1M", "18-minute", "14:41 UTC"],
        expect_compressed=True,
        target_ratio=0.5,
    ),
]


# ═══════════════════════════════════════════════════════════════════════════════
# 合并所有用例
# ═══════════════════════════════════════════════════════════════════════════════

LONG_CASES: List[TestCase] = CASES_K + CASES_L + CASES_M


# ═══════════════════════════════════════════════════════════════════════════════
# 评估运行器
# ═══════════════════════════════════════════════════════════════════════════════


def run_eval():
    """运行长文本评估测试集"""
    kompressor = LightKompress()

    print("=" * 70)
    print("LightKompress 长文本评估 — 极致压缩 / 无标点 / 句内精简")
    print(f"共 {len(LONG_CASES)} 个测试用例")
    print("=" * 70)

    # 统计结构
    results_by_category = {}
    total_pass = 0
    total_fail = 0
    total_cases = 0

    for case in LONG_CASES:
        total_cases += 1
        if case.category not in results_by_category:
            results_by_category[case.category] = {
                "total": 0,
                "pass": 0,
                "fail": 0,
                "must_keep_recall": [],
                "compression_ratios": [],
                "failures": [],
            }

        cat_stats = results_by_category[case.category]
        cat_stats["total"] += 1

        # 运行压缩
        result = kompressor.compress(
            text=case.text,
            context=case.context,
            bias=case.bias,
            target_ratio=case.target_ratio,
        )

        # 检查 1: must_keep 召回率
        must_keep_found = 0
        must_keep_missing = []
        for item in case.must_keep:
            if item in result.compressed:
                must_keep_found += 1
            else:
                must_keep_missing.append(item)

        recall = must_keep_found / len(case.must_keep) if case.must_keep else 1.0
        cat_stats["must_keep_recall"].append(recall)

        # 检查 2: 是否实际压缩了 (ratio < 0.95)
        actually_compressed = result.ratio < 0.95

        # 检查 3: 最低压缩目标 (至少 15% 节省)
        min_compression = 0.15
        met_minimum = (1 - result.ratio) >= min_compression

        # 判定通过/失败
        passed = True
        fail_reasons = []

        if case.expect_compressed and not actually_compressed:
            passed = False
            fail_reasons.append(f"未压缩(ratio={result.ratio:.3f})")

        if recall < 0.7:
            passed = False
            fail_reasons.append(f"召回不足({recall:.1%}, 缺失: {must_keep_missing[:3]})")

        if case.expect_compressed and not met_minimum:
            passed = False
            fail_reasons.append(f"压缩不足(节省{(1-result.ratio)*100:.1f}%<{min_compression*100:.0f}%)")

        if passed:
            total_pass += 1
            cat_stats["pass"] += 1
        else:
            total_fail += 1
            cat_stats["fail"] += 1
            cat_stats["failures"].append((case.id, fail_reasons))

        cat_stats["compression_ratios"].append(result.ratio)

        # 打印单个结果
        status = "✓" if passed else "✗"
        print(f"  {status} {case.id} {case.name:<30} "
              f"ratio={result.ratio:.3f} recall={recall:.1%} "
              f"({result.compressed_chars}/{result.original_chars}字符) "
              f"{result.duration_ms:.1f}ms")
        if not passed:
            print(f"    ↳ 失败: {'; '.join(fail_reasons)}")

    # 打印汇总
    print(f"\n{'═' * 70}")
    print("📊 分类汇总")
    print(f"{'═' * 70}")

    for cat_name, stats in results_by_category.items():
        avg_recall = sum(stats["must_keep_recall"]) / len(stats["must_keep_recall"]) if stats["must_keep_recall"] else 0
        avg_ratio = sum(stats["compression_ratios"]) / len(stats["compression_ratios"]) if stats["compression_ratios"] else 0
        avg_savings = (1 - avg_ratio) * 100

        print(f"\n  [{cat_name}]")
        print(f"    通过/总数: {stats['pass']}/{stats['total']} ({stats['pass']/stats['total']*100:.0f}%)")
        print(f"    平均 must_keep 召回: {avg_recall:.1%}")
        print(f"    平均压缩节省: {avg_savings:.1f}%")
        print(f"    平均保留比例: {avg_ratio:.3f}")

        if stats["failures"]:
            print(f"    失败用例:")
            for case_id, reasons in stats["failures"][:5]:
                print(f"      - {case_id}: {'; '.join(reasons)}")

    # 总汇总
    print(f"\n{'═' * 70}")
    print(f"🏁 总结: {total_pass}/{total_cases} 通过 ({total_pass/total_cases*100:.1f}%)")
    print(f"   通过: {total_pass}  失败: {total_fail}")
    print(f"{'═' * 70}")

    return total_pass, total_fail, total_cases


if __name__ == "__main__":
    run_eval()
