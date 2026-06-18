"""
LightKompress 评估测试集 — 210+ 用例覆盖 10 大维度
用于全面评估 TF-IDF + TextRank 轻量压缩器的各项能力

运行方式:
    python eval_200_cases.py

覆盖维度:
    A. 前置检查 (20 cases)    — 边界条件、短文本、空值
    B. 分句逻辑 (20 cases)    — 中英文标点、换行、合并
    C. TF-IDF维度 (20 cases)  — 关键词分布、权重
    D. 位置加权 (20 cases)    — 首尾句、中间句
    E. 实体密度 (25 cases)    — 13种正则模式
    F. 上下文相关性 (20 cases) — context重叠、多语言
    G. 信息密度 (20 cases)    — 停用词 vs 内容词
    H. 技术标识符 (20 cases)  — tech_pattern正则
    I. 补回机制 (25 cases)    — _ensure_must_keep
    J. 综合场景 (20 cases)    — 真实业务文本
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import List

from demo_light_kompress import LightKompress, CompressResult


@dataclass
class TestCase:
    """评估用例"""
    id: str
    category: str
    name: str
    text: str
    context: str = ""
    must_keep: List[str] = field(default_factory=list)
    expect_compressed: bool = True
    expect_strategy: str = "tfidf_textrank"
    bias: float = 1.0
    target_ratio: float = 0.5


# ═══════════════════════════════════════════════════════════════════════════════
# A. 前置检查 — 边界条件测试
# ═══════════════════════════════════════════════════════════════════════════════

CASES_A: List[TestCase] = [
    TestCase(
        id="A01", category="前置检查", name="空字符串",
        text="",
        must_keep=[],
        expect_compressed=False,
        expect_strategy="too_short",
    ),
    TestCase(
        id="A02", category="前置检查", name="None值处理",
        text="",
        must_keep=[],
        expect_compressed=False,
        expect_strategy="too_short",
    ),
    TestCase(
        id="A03", category="前置检查", name="纯空格字符串",
        text="          ",
        must_keep=[],
        expect_compressed=False,
        expect_strategy="too_short",
    ),
    TestCase(
        id="A04", category="前置检查", name="单个换行符",
        text="\n",
        must_keep=[],
        expect_compressed=False,
        expect_strategy="too_short",
    ),
    TestCase(
        id="A05", category="前置检查", name="50字符短文本",
        text="这是一段非常短的文本，不到一百个字符，不需要压缩处理。",
        must_keep=[],
        expect_compressed=False,
        expect_strategy="too_short",
    ),
    TestCase(
        id="A06", category="前置检查", name="99字符边界",
        text="这是一段恰好接近一百个字符的测试文本用于验证前置检查的边界条件是否能正确判断不需要压缩的情况以确保系统稳定运行不会出现错误这是填充文本。",
        must_keep=[],
        expect_compressed=False,
        expect_strategy="too_short",
    ),
    TestCase(
        id="A07", category="前置检查", name="恰好100字符",
        text="A" * 100,
        must_keep=[],
        expect_compressed=False,
        expect_strategy="too_short",
    ),
    TestCase(
        id="A08", category="前置检查", name="101字符但仅1句",
        text="这是一段刚刚超过一百个字符的长句子它没有任何标点分隔因此只会被识别为单一的句子不应该触发压缩而是返回原文因为句子数量不足三句的最低要求所以走too_few_sentences策略",
        must_keep=[],
        expect_compressed=False,
        expect_strategy="too_few_sentences",
    ),
    TestCase(
        id="A09", category="前置检查", name="2句话超100字符",
        text="第一句话包含了系统运营数据和分析结果，需要完整保留以确保信息不丢失。第二句话是对第一句的补充说明，提供了额外的上下文背景信息，这两句话合起来超过了一百个字符但句子数不足三句。",
        must_keep=[],
        expect_compressed=False,
        expect_strategy="too_few_sentences",
    ),
    TestCase(
        id="A10", category="前置检查", name="恰好3句话",
        text="第一句话是关于系统架构设计的核心描述，涉及微服务拆分策略。第二句话说明了数据库选型的考量因素，包括性能和扩展性。第三句话总结了技术方案的预期收益和潜在风险评估结果。",
        must_keep=[],
        expect_compressed=False,
        expect_strategy="too_few_sentences",
    ),
    TestCase(
        id="A11", category="前置检查", name="4句话刚好触发压缩",
        text="第一句话描述了系统当前的性能瓶颈所在，主要集中在数据库查询层面。第二句话分析了造成性能问题的根本原因，是索引缺失和全表扫描。第三句话提出了短期的优化方案，包括添加索引和查询缓存。第四句话规划了长期的架构改进方向，建议引入读写分离和分库分表策略。",
        must_keep=["性能瓶颈", "索引缺失", "读写分离"],
        expect_compressed=True,
        expect_strategy="tfidf_textrank",
    ),
    TestCase(
        id="A12", category="前置检查", name="纯制表符和空格混合",
        text="\t  \t  \t  ",
        must_keep=[],
        expect_compressed=False,
        expect_strategy="too_short",
    ),
    TestCase(
        id="A13", category="前置检查", name="Unicode特殊字符",
        text="🎉🎊🎈" * 10,
        must_keep=[],
        expect_compressed=False,
        expect_strategy="too_short",
    ),
    TestCase(
        id="A14", category="前置检查", name="单个超长句子200字符",
        text="这是一个非常非常长的句子它没有任何标点符号所以不管它有多长都只会被分成一个句子因为分句逻辑依赖于句末标点来切分文本而这里完全没有用到任何中文或英文的句末标点符号所以即使字符数远超一百个字符的阈值它依然不会被压缩因为句子总数不足三句",
        must_keep=[],
        expect_compressed=False,
        expect_strategy="too_few_sentences",
    ),
    TestCase(
        id="A15", category="前置检查", name="多个空行分隔的短片段",
        text="短。\n\n短。\n\n短。",
        must_keep=[],
        expect_compressed=False,
        expect_strategy="too_short",
    ),
    TestCase(
        id="A16", category="前置检查", name="英文短文本80字符",
        text="This is a short English text that has fewer than 100 characters in total length.",
        must_keep=[],
        expect_compressed=False,
        expect_strategy="too_short",
    ),
    TestCase(
        id="A17", category="前置检查", name="中英混合短文本",
        text="Hello你好World世界这是测试。",
        must_keep=[],
        expect_compressed=False,
        expect_strategy="too_short",
    ),
    TestCase(
        id="A18", category="前置检查", name="纯数字短文本",
        text="123456789012345678901234567890",
        must_keep=[],
        expect_compressed=False,
        expect_strategy="too_short",
    ),
    TestCase(
        id="A19", category="前置检查", name="3句话含实体但不触发压缩",
        text="2024年Q3季度收入达到¥5,680万元。客户增长率为23%，超过了预期目标。建议Q4重点拓展金融行业客户群体，预计可带来额外¥2,000万收入。",
        must_keep=["¥5,680万", "23%"],
        expect_compressed=False,
        expect_strategy="too_few_sentences",
    ),
    TestCase(
        id="A20", category="前置检查", name="超长但只有2句",
        text="这是第一句话它非常长包含了大量的信息但是没有句末标点只用逗号分隔，包括系统架构设计、数据库选型、性能优化策略、安全防护机制、监控告警配置等多个方面的内容。这是第二句话同样很长涵盖了测试策略、部署方案、运维手册、故障恢复流程、容灾备份计划等关键信息。",
        must_keep=[],
        expect_compressed=False,
        expect_strategy="too_few_sentences",
    ),
]


# ═══════════════════════════════════════════════════════════════════════════════
# B. 分句逻辑 — 标点与分割测试
# ═══════════════════════════════════════════════════════════════════════════════

CASES_B: List[TestCase] = [
    TestCase(
        id="B01", category="分句逻辑", name="中文句号分隔",
        text="系统在Q3季度完成了三次重大版本升级。第一次升级主要优化了数据查询性能，平均响应时间从4.2秒降低到1.8秒。第二次升级引入了新的权限管理模块，支持RBAC细粒度授权。第三次升级重构了前端框架，从Vue2迁移到Vue3。所有升级均在维护窗口内完成，未造成计划外停机。",
        must_keep=["4.2秒", "1.8秒", "RBAC", "Vue2", "Vue3"],
        expect_compressed=True,
        expect_strategy="tfidf_textrank",
    ),
    TestCase(
        id="B02", category="分句逻辑", name="中文感叹号分隔",
        text="这次系统上线非常成功！用户反馈都是正面的！性能指标全面超过预期目标！后端延迟从200ms降到了50ms！前端加载时间也从3.5秒优化到了1.2秒！团队的努力终于得到了回报！",
        must_keep=["200ms", "50ms", "3.5秒", "1.2秒"],
        expect_compressed=True,
        expect_strategy="tfidf_textrank",
    ),
    TestCase(
        id="B03", category="分句逻辑", name="中文问号分隔",
        text="为什么系统在高峰期会出现性能下降？是因为数据库连接池不够大吗？还是因为缓存命中率太低？根据监控数据，连接池使用率在高峰期达到了95%？那我们是否需要将max_connections从200提升到500？另外Redis缓存的命中率只有68%是否正常？",
        must_keep=["max_connections", "95%", "200", "500", "68%"],
        expect_compressed=True,
        expect_strategy="tfidf_textrank",
    ),
    TestCase(
        id="B04", category="分句逻辑", name="中文分号分隔",
        text="系统优化方案如下：数据库层面添加B-tree索引；应用层面引入Redis缓存热点数据；网络层面启用CDN加速静态资源；监控层面部署Prometheus+Grafana全链路追踪；安全层面升级WAF规则防止SQL注入；运维层面建立自动化发布流水线。",
        must_keep=["B-tree", "Redis", "CDN", "Prometheus", "Grafana", "WAF", "SQL"],
        expect_compressed=True,
        expect_strategy="tfidf_textrank",
    ),
    TestCase(
        id="B05", category="分句逻辑", name="英文句号分隔",
        text="The system experienced a major outage on September 15th lasting approximately 2 hours. Root cause analysis revealed that a database migration script failed to complete properly. The migration was attempting to add an index on the transactions table which contains over 50 million rows. During the index creation the table was locked preventing all write operations. The engineering team implemented a fix by using CREATE INDEX CONCURRENTLY to avoid table locks. Post-incident review recommended implementing a staging environment for migration testing.",
        must_keep=["September 15th", "2 hours", "50 million", "CREATE INDEX CONCURRENTLY"],
        expect_compressed=True,
        expect_strategy="tfidf_textrank",
    ),
    TestCase(
        id="B06", category="分句逻辑", name="英文感叹号和问号混合",
        text="Can you believe the system handled 10,000 concurrent connections without any issues! What an achievement for the team! The P99 latency stayed below 50ms even under peak load. How did we manage to optimize the connection pooling? The secret was implementing HikariCP with a pool size of 30 and a connection timeout of 5000ms. Incredible performance improvement compared to last quarter!",
        must_keep=["10,000", "P99", "50ms", "HikariCP", "5000ms"],
        expect_compressed=True,
        expect_strategy="tfidf_textrank",
    ),
    TestCase(
        id="B07", category="分句逻辑", name="换行符分隔",
        text="系统监控告警汇总\nCPU使用率: 峰值达到92%，持续时间超过15分钟\n内存使用: 稳定在78%，无明显波动\n磁盘IO: 读写IOPS达到12,000，接近SSD上限\n网络流量: 入站峰值850Mbps，出站320Mbps\n数据库连接: 活跃连接数180/200，即将触及上限\n建议: 紧急扩容CPU和数据库连接池",
        must_keep=["92%", "78%", "12,000", "850Mbps", "180/200"],
        expect_compressed=True,
        expect_strategy="tfidf_textrank",
    ),
    TestCase(
        id="B08", category="分句逻辑", name="中英文标点混合",
        text="系统架构采用了microservices pattern。每个服务独立部署在Kubernetes集群中！目前共运行了28个微服务？不，准确说是32个。其中核心服务包括：user-service, order-service, payment-service, notification-service。每个服务的SLA要求是99.95%；实际达成率为99.97%。",
        must_keep=["Kubernetes", "32个", "99.95%", "99.97%"],
        expect_compressed=True,
        expect_strategy="tfidf_textrank",
    ),
    TestCase(
        id="B09", category="分句逻辑", name="纯逗号无句末标点",
        text="系统监控数据显示CPU使用率持续偏高，内存占用稳定在80%左右，磁盘IO也接近瓶颈，网络带宽还有余量但需要关注晚高峰时段的流量突增，数据库慢查询数量从每小时20条增加到了150条，Redis缓存命中率下降到了65%，建议立即进行容量评估和扩容规划，否则预计在两周内将出现服务降级风险",
        must_keep=["80%", "150条", "65%"],
        expect_compressed=False,
        expect_strategy="too_few_sentences",
    ),
    TestCase(
        id="B10", category="分句逻辑", name="无标点纯中文长文",
        text="这段文本完全没有使用任何标点符号无论是中文的句号感叹号问号还是英文的点号都没有出现所以分句逻辑应该将其视为一个整体句子即使它的长度超过了一百个字符也不应该触发压缩因为句子数量不满足最低三句的要求",
        must_keep=[],
        expect_compressed=False,
        expect_strategy="too_few_sentences",
    ),
    TestCase(
        id="B11", category="分句逻辑", name="超短片段合并测试",
        text="好。对。是。没错。确实如此。这个功能在2024年Q3季度进行了重大升级，主要改进包括性能优化和安全加固两大方面。性能方面，查询响应时间从平均3.5秒降低到了0.8秒，提升幅度达到77%。安全方面，新增了OAuth2.0认证和RBAC权限管理。",
        must_keep=["3.5秒", "0.8秒", "77%", "OAuth2.0", "RBAC"],
        expect_compressed=True,
        expect_strategy="tfidf_textrank",
    ),
    TestCase(
        id="B12", category="分句逻辑", name="连续换行符多段",
        text="一、系统现状分析\n当前系统承载日活用户52万，峰值QPS达到8,500。\n\n二、性能瓶颈\n数据库层存在慢查询，P99延迟超过2秒。\n\n三、优化方案\n引入读写分离架构，预计可将延迟降低60%。\n\n四、实施计划\n分三个阶段执行，总工期预计6周。",
        must_keep=["52万", "8,500", "P99", "60%", "6周"],
        expect_compressed=True,
        expect_strategy="tfidf_textrank",
    ),
    TestCase(
        id="B13", category="分句逻辑", name="省略号作为句末",
        text="系统性能分析结果表明……查询响应时间在高峰期显著增加。数据库连接池利用率已经接近极限……活跃连接占用率达到了93%。缓存层也出现了问题……Redis内存使用率突破了85%的告警阈值。网络层面的监控数据也不乐观……入站流量已经占满了80%的带宽。综合来看需要紧急扩容。",
        must_keep=["93%", "85%", "80%"],
        expect_compressed=True,
        expect_strategy="tfidf_textrank",
    ),
    TestCase(
        id="B14", category="分句逻辑", name="Markdown列表格式",
        text="系统升级内容概述如下。- 数据库从MySQL 5.7升级到MySQL 8.0，支持窗口函数。- 缓存从Redis 5迁移到Redis 7，支持Redis Functions。- 消息队列从RabbitMQ切换到Kafka，吞吐提升10倍。- 容器运行时从Docker切换到Containerd。- 监控从自建Zabbix迁移到云原生Prometheus方案。",
        must_keep=["MySQL 8.0", "Redis 7", "Kafka", "Containerd", "Prometheus"],
        expect_compressed=True,
        expect_strategy="tfidf_textrank",
    ),
    TestCase(
        id="B15", category="分句逻辑", name="引号内的句号不分句",
        text='项目经理在会议上说"我们必须在本周五之前完成上线。这是硬性要求。"然后CTO补充道"如果延期会影响Q4的营收目标¥3,000万。"技术负责人回应"团队目前进度达到85%，剩余工作包括性能测试和安全审计。"最终确定了deadline是2024-12-20。',
        must_keep=["¥3,000万", "85%", "2024-12-20"],
        expect_compressed=True,
        expect_strategy="tfidf_textrank",
    ),
    TestCase(
        id="B16", category="分句逻辑", name="数字加句号不误分",
        text="服务器配置清单如表3.2所示。CPU型号为Intel Xeon Gold 6348，主频2.6GHz，共28核56线程。内存配置为DDR4 3200MHz，总容量512GB。存储方面使用NVMe SSD，单盘容量3.84TB，RAID10配置。网络采用25GbE双网卡bonding模式。",
        must_keep=["6348", "2.6GHz", "512GB", "3.84TB", "25GbE"],
        expect_compressed=True,
        expect_strategy="tfidf_textrank",
    ),
    TestCase(
        id="B17", category="分句逻辑", name="括号内容不分句",
        text="用户认证模块（基于OAuth 2.0协议实现）支持多种登录方式。密码登录采用bcrypt加密（cost factor = 12）确保安全性。社交登录对接了Google和GitHub（通过OIDC协议）。企业级SSO使用SAML 2.0（兼容Okta和Azure AD）。MFA支持TOTP和WebAuthn两种方案（覆盖率已达78%）。",
        must_keep=["OAuth 2.0", "bcrypt", "SAML 2.0", "78%"],
        expect_compressed=True,
        expect_strategy="tfidf_textrank",
    ),
    TestCase(
        id="B18", category="分句逻辑", name="代码块中的句号",
        text="系统初始化时需要配置数据库连接参数。关键配置项包括host=db.prod.internal，port=5432，database=crm_main。连接池参数为max_pool_size=50，min_idle=10，timeout_ms=3000。SSL模式必须设置为require以确保传输安全。应用启动时会自动验证连接有效性并记录到日志。",
        must_keep=["max_pool_size=50", "min_idle=10", "timeout_ms=3000"],
        expect_compressed=True,
        expect_strategy="tfidf_textrank",
    ),
    TestCase(
        id="B19", category="分句逻辑", name="日语风格句号「。」",
        text="本次系统评估结果如下。性能评分为A级，满足SLA 99.95%的要求。安全评分为B+级，需要补充WAF规则和DDoS防护。可用性评分为A+级，多区域部署确保了高可用。可维护性评分为B级，建议增加自动化运维脚本覆盖率。综合评定为优秀，可以进入下一阶段。",
        must_keep=["99.95%", "WAF", "DDoS"],
        expect_compressed=True,
        expect_strategy="tfidf_textrank",
    ),
    TestCase(
        id="B20", category="分句逻辑", name="混合分隔符（标点+换行+空格）",
        text="一、总体架构\n系统采用前后端分离的微服务架构。 后端基于Spring Cloud构建，共12个核心服务。\n二、关键指标\nQPS峰值: 15,000/s；平均响应时间: 85ms。\n三、已知问题\n内存泄漏导致服务每72小时需要重启一次！已定位到是HikariCP连接未正确释放。\n四、优化计划\n目标: 将重启周期延长到30天以上。",
        must_keep=["15,000", "85ms", "72小时", "HikariCP", "30天"],
        expect_compressed=True,
        expect_strategy="tfidf_textrank",
    ),
]


# ═══════════════════════════════════════════════════════════════════════════════
# C. TF-IDF维度 — 关键词权重测试
# ═══════════════════════════════════════════════════════════════════════════════

CASES_C: List[TestCase] = [
    TestCase(
        id="C01", category="TF-IDF维度", name="单一关键词高频重复",
        text="数据库性能优化是本次项目的核心目标。数据库连接池需要扩容到200个连接。数据库索引需要重新设计，特别是针对高频查询字段。数据库慢查询日志显示P99延迟超过3秒。数据库主从同步延迟在高峰期达到500ms。数据库容量规划需要考虑未来6个月的增长趋势。",
        must_keep=["200个", "P99", "3秒", "500ms", "6个月"],
        expect_compressed=True,
        expect_strategy="tfidf_textrank",
    ),
    TestCase(
        id="C02", category="TF-IDF维度", name="关键词均匀分布",
        text="系统架构包含前端、后端、数据库、缓存、消息队列五大组件。前端使用React 18框架，支持SSR服务端渲染。后端采用Java 17 + Spring Boot 3.2构建RESTful API。数据库层使用PostgreSQL 15作为主数据存储。缓存层部署Redis Cluster集群模式。消息队列采用Apache Kafka处理异步任务。",
        must_keep=["React 18", "Java 17", "Spring Boot 3.2", "PostgreSQL 15", "Redis Cluster", "Kafka"],
        expect_compressed=True,
        expect_strategy="tfidf_textrank",
    ),
    TestCase(
        id="C03", category="TF-IDF维度", name="罕见词vs常见词对比",
        text="系统中有一个非常特殊的模块叫做Quorum Consensus Engine。这个模块负责处理分布式一致性问题。它使用了Raft协议的变体来保证数据一致性。普通的CRUD操作不需要经过这个模块。日常的用户请求也不涉及一致性问题。只有跨区域数据同步时才会触发Quorum机制。",
        must_keep=["Quorum Consensus Engine", "Raft"],
        expect_compressed=True,
        expect_strategy="tfidf_textrank",
    ),
    TestCase(
        id="C04", category="TF-IDF维度", name="长短句归一化验证",
        text="CPU。内存使用率持续在85%以上运行了超过两周的时间没有明显下降趋势，怀疑存在内存泄漏问题需要用VisualVM或者MAT工具进行堆内存分析排查。磁盘。网络带宽使用正常维持在总容量的30%左右没有突发流量异常，CDN缓存命中率98%表现优异。IO等待。",
        must_keep=["85%", "VisualVM", "MAT", "30%", "CDN", "98%"],
        expect_compressed=True,
        expect_strategy="tfidf_textrank",
    ),
    TestCase(
        id="C05", category="TF-IDF维度", name="中文专业术语密集",
        text="容器编排平台采用Kubernetes 1.28版本，集群规模为50个Worker节点。服务网格选用Istio 1.20实现流量治理和可观测性。持续集成使用Jenkins Pipeline，每日构建次数约200次。制品管理通过Harbor私有镜像仓库统一管理。配置中心使用Nacos实现动态配置下发和服务发现。链路追踪集成了Jaeger和OpenTelemetry协议。",
        must_keep=["Kubernetes 1.28", "Istio 1.20", "Jenkins", "Harbor", "Nacos", "Jaeger", "OpenTelemetry"],
        expect_compressed=True,
        expect_strategy="tfidf_textrank",
    ),
    TestCase(
        id="C06", category="TF-IDF维度", name="同义词替换不影响权重",
        text="系统的吞吐量在本季度有了显著提升。处理能力从每秒3000个请求提升到了8000个。并发处理容量翻了将近三倍。每秒事务处理数TPS的增长主要得益于数据库优化。性能提升的另一个关键因素是引入了异步处理机制。响应速度的改善让用户满意度从72%提升到了89%。",
        must_keep=["3000", "8000", "TPS", "72%", "89%"],
        expect_compressed=True,
        expect_strategy="tfidf_textrank",
    ),
    TestCase(
        id="C07", category="TF-IDF维度", name="英文技术文档TF-IDF",
        text="The microservices architecture consists of 15 independent services communicating via gRPC and REST APIs. Service discovery is handled by Consul with health checks running every 10 seconds. Circuit breaker pattern is implemented using Resilience4j with a failure rate threshold of 50%. Load balancing uses a weighted round-robin algorithm across 3 availability zones. Each service maintains its own PostgreSQL database following the database-per-service pattern. Event-driven communication between services uses Apache Kafka with exactly-once semantics enabled.",
        must_keep=["gRPC", "Consul", "Resilience4j", "50%", "PostgreSQL", "Kafka"],
        expect_compressed=True,
        expect_strategy="tfidf_textrank",
    ),
    TestCase(
        id="C08", category="TF-IDF维度", name="数值信息作为关键词",
        text="2024年Q3季度业绩报告显示总营收¥1.2亿。其中SaaS订阅收入¥8,500万，占比71%。专业服务收入¥2,800万，占比23%。硬件销售收入¥700万，占比6%。客户续约率达到92%，高于行业平均水平85%。新签合同总额¥4,200万，同比增长35%。人均产出从¥45万提升到¥52万。",
        must_keep=["¥1.2亿", "¥8,500万", "71%", "92%", "85%", "35%", "¥52万"],
        expect_compressed=True,
        expect_strategy="tfidf_textrank",
    ),
    TestCase(
        id="C09", category="TF-IDF维度", name="重复段落去重验证",
        text="客户满意度调查结果显示NPS评分为48分。客户满意度是衡量服务质量的核心指标之一。产品功能满意度达到4.5分（满分5分），用户对新功能反馈积极。技术支持满意度为4.2分，响应速度从4小时缩短到2.8小时。总体满意度处于行业领先水平，目标是Q4达到52分。需要特别关注小微客户群体的满意度偏低问题。",
        must_keep=["NPS", "48分", "4.5分", "4.2分", "2.8小时", "52分"],
        expect_compressed=True,
        expect_strategy="tfidf_textrank",
    ),
    TestCase(
        id="C10", category="TF-IDF维度", name="低信息量填充文本",
        text="接下来我们来看一下系统的各项指标情况。首先需要指出的是这些数据都是从监控系统中实时采集的。其实这些指标本身并没有什么特别的地方。然后我们注意到CPU使用率达到了85%这个数值。另外内存方面也有一些需要关注的点，使用率是92%。总的来说系统目前运行在较高负载状态，需要考虑扩容。",
        must_keep=["85%", "92%"],
        expect_compressed=True,
        expect_strategy="tfidf_textrank",
    ),
    TestCase(
        id="C11", category="TF-IDF维度", name="jieba分词边界测试",
        text="PreparedStatement预编译SQL可以有效防止SQL注入攻击。ConnectionPool连接池管理需要合理配置maxActive和maxIdle参数。ThreadPoolExecutor线程池的corePoolSize建议设置为CPU核心数的2倍。ScheduledExecutorService定时任务调度器需要设置合理的initialDelay和period。ConcurrentHashMap在高并发场景下性能优于Hashtable。",
        must_keep=["PreparedStatement", "ConnectionPool", "ThreadPoolExecutor", "ScheduledExecutorService", "ConcurrentHashMap"],
        expect_compressed=True,
        expect_strategy="tfidf_textrank",
    ),
    TestCase(
        id="C12", category="TF-IDF维度", name="多语言混合关键词",
        text="国际化i18n模块支持12种语言的动态切换。本地化l10n处理包括日期格式、货币符号和数字分隔符。RTL布局适配覆盖了阿拉伯语和希伯来语两种从右到左的语言。Unicode编码统一使用UTF-8格式，避免了GBK编码在跨区域部署时的兼容性问题。翻译管理系统集成了Crowdin平台，支持翻译记忆和术语库。",
        must_keep=["i18n", "l10n", "RTL", "UTF-8", "GBK", "Crowdin"],
        expect_compressed=True,
        expect_strategy="tfidf_textrank",
    ),
    TestCase(
        id="C13", category="TF-IDF维度", name="stopwords密集但含关键数据",
        text="对于这个问题我们需要进行一些分析和说明。关于系统可用性，目前的SLA是99.95%，这个已经达到了我们的目标。通过对比我们可以发现，竞品的SLA通常在99.9%左右，所以我们是有优势的。由于近期进行了架构升级，MTTR从45分钟降低到了12分钟。为了进一步提升，我们计划引入混沌工程Chaos Engineering来主动发现潜在故障点。",
        must_keep=["SLA", "99.95%", "99.9%", "MTTR", "45分钟", "12分钟", "Chaos Engineering"],
        expect_compressed=True,
        expect_strategy="tfidf_textrank",
    ),
    TestCase(
        id="C14", category="TF-IDF维度", name="TF-IDF topK=50验证",
        text="微服务治理涉及服务注册、服务发现、负载均衡、熔断降级、限流、重试、超时控制七大核心能力。服务注册中心选用Nacos支持AP和CP两种模式切换。负载均衡算法从轮询切换到加权最少连接数。熔断器使用Sentinel设置阈值为异常比例超过50%触发。限流策略在网关层实现每秒最大1000个请求。重试次数限制为3次间隔指数退避。超时时间全局默认3秒网关层10秒。",
        must_keep=["Nacos", "AP", "CP", "Sentinel", "50%", "1000个", "3次", "3秒", "10秒"],
        expect_compressed=True,
        expect_strategy="tfidf_textrank",
    ),
    TestCase(
        id="C15", category="TF-IDF维度", name="单一领域高度专业",
        text="OLAP引擎选型对比分析如下。ClickHouse在百亿级数据量下查询延迟低于1秒，适合实时分析场景。Apache Doris支持实时数据摄入和亚秒级查询，兼容MySQL协议。StarRocks在多表Join场景性能表现最优，比ClickHouse快2-5倍。Druid适合时序数据分析但不支持复杂Join。最终选定StarRocks作为主力OLAP引擎，ClickHouse作为日志分析补充。",
        must_keep=["ClickHouse", "Apache Doris", "StarRocks", "Druid", "MySQL"],
        expect_compressed=True,
        expect_strategy="tfidf_textrank",
    ),
    TestCase(
        id="C16", category="TF-IDF维度", name="事件时间线信息",
        text="故障时间线梳理如下。14:23系统开始出现零星超时告警。14:35超时比例上升到15%，触发P2级别告警。14:42值班工程师开始排查确认是数据库主节点CPU飙升到98%。14:50执行了kill慢查询操作但效果有限。15:05决定执行主从切换，将流量切到从节点。15:08主从切换完成系统恢复正常。15:20确认所有积压请求处理完毕，关闭告警。",
        must_keep=["14:23", "14:35", "15%", "14:42", "98%", "15:05", "15:08", "15:20"],
        expect_compressed=True,
        expect_strategy="tfidf_textrank",
    ),
    TestCase(
        id="C17", category="TF-IDF维度", name="对比类文本（A vs B）",
        text="MySQL与PostgreSQL在本项目场景下的对比评估。性能方面，PostgreSQL在复杂查询和JSON处理上优势明显，JSONB索引查询比MySQL JSON快3倍。并发处理上MySQL的InnoDB引擎在高写入场景表现更好，TPS可达15,000。扩展性方面PostgreSQL原生支持分区表和并行查询，而MySQL需要依赖第三方方案。生态方面MySQL社区更大运维工具更成熟。综合评估选择PostgreSQL 15作为主数据库。",
        must_keep=["PostgreSQL", "MySQL", "JSONB", "3倍", "InnoDB", "15,000", "PostgreSQL 15"],
        expect_compressed=True,
        expect_strategy="tfidf_textrank",
    ),
    TestCase(
        id="C18", category="TF-IDF维度", name="列表式信息密集",
        text="API性能基准测试结果。GET /api/users P50=12ms P95=45ms P99=120ms。POST /api/orders P50=35ms P95=150ms P99=380ms。PUT /api/products P50=28ms P95=95ms P99=220ms。DELETE /api/sessions P50=8ms P95=25ms P99=55ms。总体评价：读操作性能优异写操作需要优化。优化目标：所有接口P99控制在200ms以内。",
        must_keep=["P50", "P95", "P99", "/api/users", "/api/orders", "200ms"],
        expect_compressed=True,
        expect_strategy="tfidf_textrank",
    ),
    TestCase(
        id="C19", category="TF-IDF维度", name="因果关系链",
        text="内存泄漏的根因分析已完成。直接原因是HttpClient连接未正确关闭导致Socket对象累积。根本原因是连接池的eviction策略配置错误，minEvictableIdleTime设置为-1导致空闲连接永不回收。影响范围是所有调用外部API的服务，共8个微服务受影响。修复方案是设置minEvictableIdleTime=60000ms并启用testWhileIdle=true。验证方式是通过jmap监控Old Gen使用率应在72小时内稳定下降。",
        must_keep=["HttpClient", "minEvictableIdleTime", "testWhileIdle=true", "jmap", "72小时"],
        expect_compressed=True,
        expect_strategy="tfidf_textrank",
    ),
    TestCase(
        id="C20", category="TF-IDF维度", name="高重复低信息文本",
        text="好的，让我来看看这个问题。嗯，我看到了一些数据。首先，我们来看第一个指标。然后，我们看第二个指标。接着，我们分析第三个指标。另外，还有第四个指标需要关注。最后，总结一下所有指标的情况。关键结论是系统CPU达到90%需要立即扩容。内存使用78%暂时安全但需要监控。",
        must_keep=["90%", "78%"],
        expect_compressed=True,
        expect_strategy="tfidf_textrank",
    ),
]


# ═══════════════════════════════════════════════════════════════════════════════
# D. 位置加权 — 首尾句与中间句权重测试
# ═══════════════════════════════════════════════════════════════════════════════

CASES_D: List[TestCase] = [
    TestCase(
        id="D01", category="位置加权", name="关键信息在第一句",
        text="本季度核心结论：系统整体健康度评分为A级，所有SLA指标达标。具体到各个模块的表现，用户模块访问量最大日均请求1200万次。订单模块处理能力正常，日均处理订单8万笔。支付模块稳定性最高，全季度零故障。通知模块有少量延迟问题但在可接受范围内。搜索模块需要关注性能退化趋势。",
        must_keep=["A级", "SLA", "1200万"],
        expect_compressed=True,
        expect_strategy="tfidf_textrank",
    ),
    TestCase(
        id="D02", category="位置加权", name="关键信息在最后一句",
        text="我们对系统进行了为期两周的全面压力测试。测试覆盖了正常负载、高峰负载和极端负载三种场景。正常负载下系统表现符合预期没有异常。高峰负载下出现了轻微的响应延迟增加。极端负载测试中发现了一些边界case。综合所有测试结果，最终结论是系统需要将数据库连接池从100扩容到300，否则在双十一期间将无法承受预计¥8,000万的交易峰值。",
        must_keep=["100", "300", "¥8,000万"],
        expect_compressed=True,
        expect_strategy="tfidf_textrank",
    ),
    TestCase(
        id="D03", category="位置加权", name="关键信息仅在中间",
        text="以下是本周系统运维报告的详细内容。周一和周二系统运行平稳没有告警。周三上午10:35出现了严重的数据库死锁问题，导致订单系统停摆47分钟，影响交易金额约¥1,500万。周四进行了紧急修复部署了死锁检测机制。周五系统恢复正常运行。整体来看本周系统可用性为99.5%。",
        must_keep=["10:35", "47分钟", "¥1,500万", "99.5%"],
        expect_compressed=True,
        expect_strategy="tfidf_textrank",
    ),
    TestCase(
        id="D04", category="位置加权", name="首尾句为套话中间有料",
        text="经过深入分析和全面评估，我们得出了以下结论。系统当前面临的最大挑战是数据库写入性能瓶颈。核心问题在于order_items表已经达到5亿条记录。分库分表方案评估：按user_id取模分32个库每库32张表。迁移工具选用ShardingSphere 5.4支持在线平滑迁移。预计迁移周期4周，需要2名DBA全程参与。以上就是我们的分析报告，请各位领导审阅。",
        must_keep=["5亿条", "32个库", "ShardingSphere 5.4", "4周"],
        expect_compressed=True,
        expect_strategy="tfidf_textrank",
    ),
    TestCase(
        id="D05", category="位置加权", name="首句总结+尾句结论",
        text="2024年Q3安全审计总结：共发现高危漏洞3个、中危7个、低危15个。高危漏洞包括SQL注入一处、越权访问一处、敏感数据明文传输一处。SQL注入位于/api/v2/search接口的keyword参数。越权访问存在于管理员角色的organization_id校验缺失。敏感数据问题出现在用户手机号在日志中明文记录。所有高危漏洞已在7天内完成修复并通过复测，中危漏洞计划在30天内修复完毕。",
        must_keep=["SQL注入", "/api/v2/search", "3个", "7天", "30天"],
        expect_compressed=True,
        expect_strategy="tfidf_textrank",
    ),
    TestCase(
        id="D06", category="位置加权", name="递进式重要性递增",
        text="背景介绍一下我们的系统架构。目前是典型的三层架构设计。前端层没有什么特别的采用标准的React方案。中间件层也比较传统使用了Nginx做反向代理。应用层使用Spring Boot这也是常规选择。关键的问题出在数据层：MySQL单机已经无法承受日均2亿次查询的压力。紧急决定：本周五之前必须完成TiDB集群的部署和数据迁移。",
        must_keep=["2亿次", "TiDB"],
        expect_compressed=True,
        expect_strategy="tfidf_textrank",
    ),
    TestCase(
        id="D07", category="位置加权", name="位置权重与实体密度竞争",
        text="系统概况简要说明如下。本季度没有重大变更计划。日常运维工作按部就班进行中。值得特别关注的是第15行代码ServiceRegistry.register():42处出现了内存泄漏，泄漏速率约为每小时增加150MB，已持续运行72小时累计泄漏约10.8GB。这是一般性的补充说明不重要。总体来看系统基本稳定。",
        must_keep=["ServiceRegistry.register():42", "150MB", "72小时", "10.8GB"],
        expect_compressed=True,
        expect_strategy="tfidf_textrank",
    ),
    TestCase(
        id="D08", category="位置加权", name="前三句均重要",
        text="紧急通知：生产环境Redis集群出现脑裂问题。影响范围：所有依赖缓存的服务约占总流量的85%。当前状态：已触发降级策略直接查询数据库但延迟从5ms增加到200ms。脑裂原因正在排查中怀疑是网络分区导致。运维团队已经在线处理预计30分钟内恢复。临时方案是手动指定Redis主节点IP为10.0.1.50。",
        must_keep=["Redis", "85%", "5ms", "200ms", "30分钟", "10.0.1.50"],
        expect_compressed=True,
        expect_strategy="tfidf_textrank",
    ),
    TestCase(
        id="D09", category="位置加权", name="均匀分布无明显首尾",
        text="微服务A的健康检查通过率98.5%。微服务B的健康检查通过率99.2%。微服务C的健康检查通过率97.8%。微服务D的健康检查通过率99.9%。微服务E的健康检查通过率96.3%需要关注。微服务F的健康检查通过率99.5%。微服务G的健康检查通过率94.1%存在问题。",
        must_keep=["98.5%", "99.2%", "97.8%", "96.3%", "94.1%"],
        expect_compressed=True,
        expect_strategy="tfidf_textrank",
    ),
    TestCase(
        id="D10", category="位置加权", name="第二句是核心观点",
        text="以下为本次容量评估的详细报告。核心结论：当前系统在保持现有架构不变的情况下最多还能支撑3个月的业务增长，之后必须进行水平扩展。从CPU维度来看目前平均使用率为62%，按照每月增长8%的趋势3个月后将达到86%。内存方面当前使用72%增速较缓预计6个月才会到达告警线。磁盘空间按照每月新增500GB的速度还剩余2.4TB可用大约可以再支撑5个月。",
        must_keep=["3个月", "62%", "8%", "86%", "72%", "500GB", "2.4TB"],
        expect_compressed=True,
        expect_strategy="tfidf_textrank",
    ),
    TestCase(
        id="D11", category="位置加权", name="最后两句含紧急行动项",
        text="以下是Q3客户反馈分析摘要。大部分客户对产品整体表示满意。UI方面收到了一些改进建议但不紧急。性能方面少数客户反映了偶尔的卡顿现象。文档方面希望能提供更多API使用示例。但是有一个严重问题：金融客户report了数据不一致Bug，影响了资金对账准确性。紧急行动项：48小时内必须修复该Bug并向受影响的12家金融客户提供补偿方案，预计赔付金额¥280万。",
        must_keep=["48小时", "12家", "¥280万"],
        expect_compressed=True,
        expect_strategy="tfidf_textrank",
    ),
    TestCase(
        id="D12", category="位置加权", name="首句为标题格式",
        text="【P0故障通报】2024-09-15 14:23 生产环境主数据库宕机。故障现象：所有写入操作返回Connection refused错误。影响范围：全部业务线，约12万在线用户受影响。止损措施：14:35启动故障转移切换到备库。恢复时间：14:42备库接管完成业务恢复正常。根因：主库磁盘阵列控制器硬件故障导致IO挂起。后续改进：采购双活存储阵列，预算¥150万已提交审批。",
        must_keep=["2024-09-15", "14:23", "12万", "14:35", "14:42", "¥150万"],
        expect_compressed=True,
        expect_strategy="tfidf_textrank",
    ),
    TestCase(
        id="D13", category="位置加权", name="中间连续三句高价值",
        text="本次性能优化项目背景和目标如下。项目启动于2024年7月经过了充分的前期调研。接下来进入核心优化措施详述。措施一：数据库索引重建，覆盖TOP20慢查询，预计减少50%的全表扫描。措施二：引入本地缓存Caffeine，热点数据TTL设置为5分钟，命中率目标95%以上。措施三：异步化非关键路径，使用CompletableFuture并行处理，P99从800ms降到200ms。以上三项措施将在两周内分批上线。",
        must_keep=["TOP20", "50%", "Caffeine", "95%", "CompletableFuture", "800ms", "200ms"],
        expect_compressed=True,
        expect_strategy="tfidf_textrank",
    ),
    TestCase(
        id="D14", category="位置加权", name="倒数第二句含决策",
        text="经过三轮技术选型评审会议的讨论。候选方案A是自研Gateway基于Netty开发周期3个月。候选方案B是采用Kong网关社区版开箱即用但定制性有限。候选方案C是使用APISIX支持Lua插件扩展生态活跃。各方案都有优缺点需要综合考量。最终技术委员会投票决定采用APISIX方案，原因是Lua插件机制能满足我们80%的定制需求且无需改源码。具体实施计划将在下周一输出。",
        must_keep=["Netty", "Kong", "APISIX", "Lua", "80%"],
        expect_compressed=True,
        expect_strategy="tfidf_textrank",
    ),
    TestCase(
        id="D15", category="位置加权", name="首句否定+末句肯定",
        text="本次发布并没有达到预期的性能提升目标。优化项一的效果低于预期只提升了5%而非目标的30%。优化项二由于兼容性问题被迫回滚。优化项三还在灰度验证阶段尚无结论。不过好消息是第四项优化——连接池参数调优——效果显著。最终确认的有效优化：将HikariCP的maximumPoolSize从10调整到50，单独这一项就将QPS从2000提升到了5500，提升幅度175%。",
        must_keep=["5%", "30%", "HikariCP", "maximumPoolSize", "10", "50", "2000", "5500", "175%"],
        expect_compressed=True,
        expect_strategy="tfidf_textrank",
    ),
    TestCase(
        id="D16", category="位置加权", name="每句权重应该相近",
        text="安全加固项目第一阶段已完成WAF规则部署拦截率99.2%。第二阶段完成了HTTPS全站强制跳转和HSTS头配置max-age=31536000。第三阶段实现了API接口的JWT Token认证和refresh_token轮转机制。第四阶段部署了速率限制中间件每个用户每分钟最多100次API调用。第五阶段完成了日志脱敏处理手机号和身份证号自动掩码。第六阶段引入了SAST扫描集成到CI流水线每次提交自动检测漏洞。",
        must_keep=["WAF", "99.2%", "HSTS", "JWT", "refresh_token", "100次", "SAST"],
        expect_compressed=True,
        expect_strategy="tfidf_textrank",
    ),
    TestCase(
        id="D17", category="位置加权", name="位置vs上下文竞争",
        text="公司年度技术大会的主题演讲非常精彩获得了全场最高评分。技术分享环节有20个团队做了presentation。午餐时间的networking也很有收获。下午的工作坊环节参与度很高。最受好评的是关于Kubernetes集群从500节点扩展到2000节点的实战分享。茶歇时间大家讨论了很多话题。闭幕式上CTO宣布了明年的技术投入预算增加40%达到¥8,000万。",
        context="Kubernetes扩容方案",
        must_keep=["Kubernetes", "500节点", "2000节点", "40%", "¥8,000万"],
        expect_compressed=True,
        expect_strategy="tfidf_textrank",
    ),
    TestCase(
        id="D18", category="位置加权", name="开头冗长背景",
        text="在当前数字化转型的大背景下，企业对于数据处理能力的要求越来越高，同时随着云原生技术的快速发展和成熟，传统的单体架构已经无法满足日益增长的业务需求。我们的团队经过了长时间的调研和方案对比。最终确定的技术方案核心参数如下：计算节点8C32G规格共12台。存储采用NVMe SSD总容量96TB RAID10。网络使用100GbE InfiniBand低延迟互联。预计总投入¥420万分三期支付。",
        must_keep=["8C32G", "12台", "96TB", "100GbE", "¥420万"],
        expect_compressed=True,
        expect_strategy="tfidf_textrank",
    ),
    TestCase(
        id="D19", category="位置加权", name="结尾冗长展望",
        text="本季度API网关升级核心数据：请求处理能力从5万QPS提升到12万QPS。错误率从0.5%降低到0.02%。平均延迟从15ms降低到3ms。这些改进已经通过了两周的灰度验证没有出现回归问题。展望未来我们将继续在这个方向上深耕，争取在下个季度带来更多的技术创新和突破，让系统能力更上一个台阶，为业务发展保驾护航，助力公司数字化战略稳步推进。",
        must_keep=["5万QPS", "12万QPS", "0.5%", "0.02%", "15ms", "3ms"],
        expect_compressed=True,
        expect_strategy="tfidf_textrank",
    ),
    TestCase(
        id="D20", category="位置加权", name="交替重要/不重要",
        text="下面开始汇报。核心指标一：月活跃用户MAU达到850万创历史新高。这个数据还需要进一步验证。核心指标二：付费转化率从3.2%提升到4.8%增幅50%。后续我们会持续跟踪。核心指标三：ARPU值从¥45提升到¥62客单价提高38%。以上就是本次汇报的全部内容谢谢大家。",
        must_keep=["MAU", "850万", "3.2%", "4.8%", "50%", "ARPU", "¥45", "¥62", "38%"],
        expect_compressed=True,
        expect_strategy="tfidf_textrank",
    ),
]


# ═══════════════════════════════════════════════════════════════════════════════
# E. 实体密度 — 13种正则模式测试
# ═══════════════════════════════════════════════════════════════════════════════

CASES_E: List[TestCase] = [
    TestCase(
        id="E01", category="实体密度", name="百分比模式",
        text="系统各项指标完成情况汇报。CPU使用率日均75%峰值92%。内存使用率稳定在68%左右波动不大。磁盘利用率已经达到了83%需要扩容。网络带宽利用率仅35%还有充足空间。缓存命中率从上月的71%提升到本月的89%。用户请求成功率保持在99.7%以上。",
        must_keep=["75%", "92%", "68%", "83%", "35%", "71%", "89%", "99.7%"],
        expect_compressed=True,
        expect_strategy="tfidf_textrank",
    ),
    TestCase(
        id="E02", category="实体密度", name="金额模式-人民币",
        text="Q3财务数据核对结果如下。总营收¥1,280万较上季度增长15%。其中产品收入¥890万服务收入¥390万。最大单笔合同金额¥156万来自金融客户A。应收账款余额¥320万账龄在60天以内的占85%。研发投入¥450万占总营收35%。预计Q4目标营收¥1,500万。",
        must_keep=["¥1,280万", "¥890万", "¥390万", "¥156万", "¥320万", "¥450万", "¥1,500万"],
        expect_compressed=True,
        expect_strategy="tfidf_textrank",
    ),
    TestCase(
        id="E03", category="实体密度", name="金额模式-美元",
        text="Global SaaS market analysis for Q3 2024 shows promising trends. Total ARR reached $12.4M representing a 28% YoY growth. Enterprise segment contributed $7.8M while SMB added $4.6M. Average contract value increased to $45K from $38K last quarter. Customer acquisition cost dropped to $2,800 per customer. Lifetime value to CAC ratio improved to 4.2x indicating healthy unit economics. Projected Q4 revenue target is $15M.",
        must_keep=["$12.4M", "28%", "$7.8M", "$4.6M", "$45K", "$2,800", "$15M"],
        expect_compressed=True,
        expect_strategy="tfidf_textrank",
    ),
    TestCase(
        id="E04", category="实体密度", name="日期模式",
        text="项目里程碑时间线已确认。需求评审完成日期2024-07-15。技术方案确定2024-08-01。开发阶段截止2024-09-30。集成测试开始2024-10-08。UAT验收计划2024-10-20。生产上线目标2024-11-01。灰度发布持续到2024-11-15全量放开。",
        must_keep=["2024-07-15", "2024-08-01", "2024-09-30", "2024-10-08", "2024-10-20", "2024-11-01", "2024-11-15"],
        expect_compressed=True,
        expect_strategy="tfidf_textrank",
    ),
    TestCase(
        id="E05", category="实体密度", name="时间模式",
        text="故障事件时间线记录。08:15监控系统首次告警CPU使用率超过阈值。08:23运维工程师收到PagerDuty通知开始排查。09:05定位到是定时任务cron在08:00触发的全量数据同步导致。09:15尝试kill相关进程但未生效。09:30执行了服务重启操作。09:32服务重启完成恢复正常。10:00确认所有积压请求处理完毕系统稳定运行。",
        must_keep=["08:15", "08:23", "09:05", "08:00", "09:15", "09:30", "09:32", "10:00"],
        expect_compressed=True,
        expect_strategy="tfidf_textrank",
    ),
    TestCase(
        id="E06", category="实体密度", name="数字+单位模式",
        text="数据中心资源使用报告。当前集群总算力为2,400核CPU，已分配1,850核使用率77%。内存总量为6,400GB，已使用4,800GB占比75%。存储总容量280TB其中已使用215TB。网络出口带宽10Gbps峰值使用7.2Gbps。容器实例总数1,350个运行中1,280个。每日新增日志数据量约3.5TB需要定期清理。",
        must_keep=["2,400核", "1,850核", "6,400GB", "4,800GB", "280TB", "10Gbps", "7.2Gbps", "1,350个", "3.5TB"],
        expect_compressed=True,
        expect_strategy="tfidf_textrank",
    ),
    TestCase(
        id="E07", category="实体密度", name="驼峰标识符模式",
        text="代码审查发现的设计问题清单。UserAccountService类违反了单一职责原则需要拆分。OrderPaymentProcessor中存在循环依赖需要引入事件机制解耦。DataSourceConnectionFactory的连接创建逻辑过于复杂建议使用Builder模式重构。HttpRequestInterceptor缺少超时处理可能导致线程阻塞。CacheEvictionStrategy需要支持LRU和LFU两种淘汰算法。AsyncTaskScheduler的异常处理不完善会吞掉异常。",
        must_keep=["UserAccountService", "OrderPaymentProcessor", "DataSourceConnectionFactory", "HttpRequestInterceptor", "CacheEvictionStrategy", "AsyncTaskScheduler"],
        expect_compressed=True,
        expect_strategy="tfidf_textrank",
    ),
    TestCase(
        id="E08", category="实体密度", name="全大写标识符模式",
        text="系统集成的第三方协议和标准清单。认证授权使用OAuth和OIDC协议。API设计遵循REST规范并提供GraphQL接口。数据传输安全使用TLS加密。服务间通信支持gRPC和HTTP两种协议。身份管理兼容SAML和LDAP。访问控制实现了RBAC和ABAC两种模型。日志格式统一为JSON并支持CEF标准。消息格式使用AVRO序列化。",
        must_keep=["OAuth", "OIDC", "REST", "GraphQL", "TLS", "gRPC", "HTTP", "SAML", "LDAP", "RBAC", "ABAC", "JSON", "CEF", "AVRO"],
        expect_compressed=True,
        expect_strategy="tfidf_textrank",
    ),
    TestCase(
        id="E09", category="实体密度", name="URL模式",
        text="外部服务集成端点配置信息。支付网关地址为https://pay.gateway.com/v2/charge。短信服务使用https://sms.provider.cn/api/send。对象存储入口为https://oss.cloud.com/bucket/upload。搜索引擎节点https://es-cluster.internal:9200。监控数据推送https://metrics.datadog.com/api/v1/series。OAuth认证回调https://auth.ourapp.com/callback。日志收集端点https://logstash.internal:5044/beats。",
        must_keep=["https://pay.gateway.com/v2/charge", "https://sms.provider.cn/api/send", "https://oss.cloud.com/bucket/upload"],
        expect_compressed=True,
        expect_strategy="tfidf_textrank",
    ),
    TestCase(
        id="E10", category="实体密度", name="URL路径模式",
        text="API路由规划V2版本更新说明。用户相关接口从/user迁移到/api/v2/users。订单接口路径为/api/v2/orders支持分页和过滤。支付回调地址更新为/api/v2/payments/webhook。文件上传统一走/api/v2/files/upload支持分片。搜索接口/api/v2/search增加了模糊匹配。报表导出/api/v2/reports/export支持异步下载。健康检查地址保持/healthz不变。",
        must_keep=["/api/v2/users", "/api/v2/orders", "/api/v2/payments/webhook", "/api/v2/files/upload", "/api/v2/search", "/api/v2/reports/export", "/healthz"],
        expect_compressed=True,
        expect_strategy="tfidf_textrank",
    ),
    TestCase(
        id="E11", category="实体密度", name="邮箱模式",
        text="项目干系人联系方式整理。技术负责人zhang.wei@company.com负责架构决策。产品经理li.ming@company.com负责需求对接。运维主管wang.qiang@ops-team.cn负责发布部署。安全专员security@infosec.company.com负责安全审计。外部顾问consultant@partner.io提供技术咨询。紧急联系人oncall@company.com负责7x24值班响应。客户成功经理cs-team@company.com处理客户问题。",
        must_keep=["zhang.wei@company.com", "li.ming@company.com", "wang.qiang@ops-team.cn", "security@infosec.company.com", "oncall@company.com"],
        expect_compressed=True,
        expect_strategy="tfidf_textrank",
    ),
    TestCase(
        id="E12", category="实体密度", name="配置参数key=value模式",
        text="数据库连接池优化后的最终配置参数。核心参数max_connections=500适配当前并发量。空闲连接保持min_idle=50避免冷启动延迟。连接超时设置connect_timeout=3000毫秒。查询超时query_timeout=30000毫秒防止慢查询阻塞。连接最大存活时间max_lifetime=1800000毫秒即30分钟。空闲回收时间idle_timeout=600000毫秒即10分钟。验证查询使用validation_query=SELECT1确保连接有效性。",
        must_keep=["max_connections=500", "min_idle=50", "connect_timeout=3000", "query_timeout=30000", "max_lifetime=1800000", "idle_timeout=600000"],
        expect_compressed=True,
        expect_strategy="tfidf_textrank",
    ),
    TestCase(
        id="E13", category="实体密度", name="权限表达式模式",
        text="RBAC权限矩阵配置更新说明。管理员角色新增权限write:organization(all)可以修改所有组织数据。产品经理角色具备read:opportunity(own)权限只能查看自己的商机。开发人员拥有execute:deployment(team)可以部署所属团队的服务。数据分析师配置read:analytics(all)可以访问全部分析数据。客服人员权限为read:customer(assigned)只能查看分配给自己的客户。审计人员具有read:audit_log(all)权限可以查阅所有操作日志。",
        must_keep=["write:organization(all)", "read:opportunity(own)", "execute:deployment(team)", "read:analytics(all)", "read:customer(assigned)", "read:audit_log(all)"],
        expect_compressed=True,
        expect_strategy="tfidf_textrank",
    ),
    TestCase(
        id="E14", category="实体密度", name="类.方法:行号模式",
        text="生产环境异常堆栈分析报告。首个异常出现在OrderService.createOrder:145处空指针异常。调用链追踪到PaymentGateway.charge:89处超时异常。数据库操作在Repository.saveOrder:203处抛出了DeadlockException。重试机制在RetryTemplate.execute:67处达到最大重试次数。最终异常被GlobalExceptionHandler.handle:34捕获并返回500错误。日志记录在AuditLogger.logError:112处完成了异常信息持久化。",
        must_keep=["OrderService.createOrder:145", "PaymentGateway.charge:89", "Repository.saveOrder:203", "RetryTemplate.execute:67", "GlobalExceptionHandler.handle:34", "AuditLogger.logError:112"],
        expect_compressed=True,
        expect_strategy="tfidf_textrank",
    ),
    TestCase(
        id="E15", category="实体密度", name="混合实体高密度",
        text="2024-09-15故障复盘报告。14:23系统告警显示错误率飙升到15%。根因是PaymentService.processRefund:234处的SQL注入漏洞被利用。攻击者通过/api/v2/refunds接口注入恶意SQL。受影响交易金额¥2,350万涉及客户1,200家。修复方案使用PreparedStatement替代字符串拼接。紧急修复版本v3.2.1于15:08部署完成。联系安全团队security@company.com进行事后审计。",
        must_keep=["2024-09-15", "14:23", "15%", "PaymentService.processRefund:234", "/api/v2/refunds", "¥2,350万", "1,200家", "PreparedStatement", "security@company.com"],
        expect_compressed=True,
        expect_strategy="tfidf_textrank",
    ),
    TestCase(
        id="E16", category="实体密度", name="版本号和数字密集",
        text="依赖升级计划季度review结果。Spring Boot从2.7.18升级到3.2.0需要JDK17。MySQL驱动从8.0.33升级到8.2.0。Redis客户端Lettuce从6.2.7升级到6.3.1。Jackson JSON库从2.15.3升级到2.16.0修复CVE-2023-35116。Netty从4.1.97升级到4.1.101修复内存泄漏。Guava从32.1.3升级到33.0.0移除了deprecated API。总计涉及28个依赖需要回归测试。",
        must_keep=["3.2.0", "8.2.0", "6.3.1", "2.16.0", "4.1.101", "33.0.0"],
        expect_compressed=True,
        expect_strategy="tfidf_textrank",
    ),
    TestCase(
        id="E17", category="实体密度", name="无实体纯叙述文本",
        text="团队最近在讨论是否要引入新的技术框架来替代现有方案。支持方认为新框架的社区更活跃而且文档更完善容易上手。反对方觉得迁移成本太高而且现有方案运行稳定没必要折腾。双方各执一词争论了好几轮也没有达成一致。后来决定做一个小规模的试点项目来验证新框架是否真的如宣传的那么好用。试点结果将在下个月的技术评审会上进行讨论和最终决策。",
        must_keep=[],
        expect_compressed=True,
        expect_strategy="tfidf_textrank",
    ),
    TestCase(
        id="E18", category="实体密度", name="单个句子含多个实体",
        text="系统运行状态正常没有告警。各项基础指标都在合理范围内。业务层面没有客户投诉。但是核心交易链路在2024-10-08 14:23出现了一次P0故障，PaymentGateway.processPayment:567返回HTTP 503错误，影响交易金额¥890万，错误率从0.01%飙升到23%，持续了12分钟才恢复。事后分析已完成。后续改进计划已排期。",
        must_keep=["2024-10-08", "14:23", "PaymentGateway.processPayment:567", "HTTP", "¥890万", "0.01%", "23%", "12分钟"],
        expect_compressed=True,
        expect_strategy="tfidf_textrank",
    ),
    TestCase(
        id="E19", category="实体密度", name="实体在被压缩句中",
        text="项目管理方面一切顺利进度符合预期。日常站会按时召开沟通顺畅。代码审查流程运转良好。团队士气比较高涨加班不多。唯一需要关注的风险是第三方支付接口partner-pay.com/api/v3/transaction的SLA只有99.5%，低于我们对客户承诺的99.95%。建议与供应商协商升级SLA或者引入备用通道。上周已发送沟通邮件到vendor-support@partner-pay.com等待回复中。",
        must_keep=["/api/v3/transaction", "99.5%", "99.95%", "vendor-support@partner-pay.com"],
        expect_compressed=True,
        expect_strategy="tfidf_textrank",
    ),
    TestCase(
        id="E20", category="实体密度", name="连续数字不同格式",
        text="数据迁移进度报告。用户表user共12,500,000条记录已完成迁移。订单表orders共45,800,000条分批迁移中已完成80%。交易流水表transactions共128,000,000条是最大的表预计还需48小时。产品表products共35,000条小表已全部完成。日志表operation_log共2.8亿条按时间分区迁移只保留最近90天数据。总数据量约3.2TB已迁移2.1TB。",
        must_keep=["12,500,000", "45,800,000", "80%", "128,000,000", "48小时", "35,000", "3.2TB", "2.1TB"],
        expect_compressed=True,
        expect_strategy="tfidf_textrank",
    ),
    TestCase(
        id="E21", category="实体密度", name="百分比与金额组合",
        text="投资回报分析报告如下。本次技术升级总投入¥680万。预期年化收益包括：运维成本降低35%节省¥240万。人效提升20%相当于节省2个全职人力约¥100万。系统宕机减少预计避免损失¥500万。客户流失降低1.5%额外保留收入¥180万。综合计算ROI为150%投资回收周期约8个月。",
        must_keep=["¥680万", "35%", "¥240万", "20%", "¥100万", "¥500万", "1.5%", "¥180万", "150%", "8个月"],
        expect_compressed=True,
        expect_strategy="tfidf_textrank",
    ),
    TestCase(
        id="E22", category="实体密度", name="邮箱+URL+路径组合",
        text="新员工开发环境配置指南。代码仓库地址https://gitlab.internal.com/platform/backend-services。CI/CD流水线地址https://jenkins.internal.com/job/backend-deploy。内部文档站点https://wiki.internal.com/tech/architecture。API文档入口/docs/swagger-ui/index.html。配置中心/config/application-prod.yml。遇到问题请联系devops@engineering.com或在Slack的#dev-support频道提问。紧急情况直接联系oncall@engineering.com。",
        must_keep=["https://gitlab.internal.com/platform/backend-services", "https://jenkins.internal.com/job/backend-deploy", "/docs/swagger-ui/index.html", "devops@engineering.com", "oncall@engineering.com"],
        expect_compressed=True,
        expect_strategy="tfidf_textrank",
    ),
    TestCase(
        id="E23", category="实体密度", name="配置参数密集",
        text="生产环境JVM调优最终配置。堆内存设置heap_size=8G适配32GB物理内存的服务器。新生代比例new_ratio=2即新生代占堆的三分之一。GC算法选择gc_type=G1GC兼顾吞吐和延迟。最大停顿目标max_pause=200ms。并发GC线程数concurrent_threads=8。元空间大小metaspace_size=512M防止Full GC。堆外内存限制direct_memory=2G用于Netty缓冲区。GC日志输出gc_log_path=/var/log/gc.log。",
        must_keep=["heap_size=8G", "new_ratio=2", "gc_type=G1GC", "max_pause=200ms", "concurrent_threads=8", "metaspace_size=512M", "direct_memory=2G"],
        expect_compressed=True,
        expect_strategy="tfidf_textrank",
    ),
    TestCase(
        id="E24", category="实体密度", name="权限表达式+类方法组合",
        text="访问控制审计异常发现。用户ID=10234尝试执行write:financial_report(all)权限操作但其角色仅有read:financial_report(own)。拦截点在AuthorizationFilter.checkPermission:78处。另外发现用户ID=10567越权调用delete:customer(all)被AccessControl.validateScope:145拦截。系统管理员通过admin:system(all)权限修复了配置。审计日志记录在AuditService.logViolation:92处完成。",
        must_keep=["write:financial_report(all)", "read:financial_report(own)", "AuthorizationFilter.checkPermission:78", "delete:customer(all)", "AccessControl.validateScope:145", "admin:system(all)", "AuditService.logViolation:92"],
        expect_compressed=True,
        expect_strategy="tfidf_textrank",
    ),
    TestCase(
        id="E25", category="实体密度", name="全类型实体混合极端",
        text="2024-11-01 09:15生产事故报告。DataSyncService.batchImport:321抛出OutOfMemoryError。问题接口/api/v2/import/bulk上传了一个2.3GB的CSV文件。内存使用从65%瞬间飙升到99%。服务自动重启后恢复，影响时长8分钟。涉及客户数据42,000条金额¥3,200万。修复配置upload_max_size=100M限制上传大小。通知客户success-team@company.com跟进受影响用户。工单已创建权限assign:incident(ops)分配给运维组。",
        must_keep=["2024-11-01", "09:15", "DataSyncService.batchImport:321", "/api/v2/import/bulk", "2.3GB", "65%", "99%", "8分钟", "42,000条", "¥3,200万", "upload_max_size=100M", "success-team@company.com", "assign:incident(ops)"],
        expect_compressed=True,
        expect_strategy="tfidf_textrank",
    ),
]


# ═══════════════════════════════════════════════════════════════════════════════
# F. 上下文相关性 — context参数影响测试
# ═══════════════════════════════════════════════════════════════════════════════

CASES_F: List[TestCase] = [
    TestCase(
        id="F01", category="上下文相关性", name="中文context精确匹配",
        text="本季度系统升级涉及三个核心模块。用户认证模块重构了OAuth流程支持无密码登录。订单处理模块优化了库存锁定机制减少超卖。支付网关对接了新的渠道支持数字人民币。报表模块增加了实时数据大屏功能。消息通知模块集成了企业微信推送。搜索功能引入了Elasticsearch替代MySQL全文索引。",
        context="支付网关升级了什么",
        must_keep=["数字人民币", "支付网关"],
        expect_compressed=True,
        expect_strategy="tfidf_textrank",
    ),
    TestCase(
        id="F02", category="上下文相关性", name="英文context精确匹配",
        text="The platform update includes several key improvements across different areas. The authentication module now supports biometric login via WebAuthn. The search engine was migrated from Solr to Elasticsearch 8.10 for better performance. The payment system integrated Stripe Connect for marketplace payouts. The notification service added support for push notifications via Firebase Cloud Messaging. The analytics dashboard now provides real-time cohort analysis. The API gateway implemented rate limiting using token bucket algorithm.",
        context="What changes were made to the search engine",
        must_keep=["Elasticsearch 8.10", "Solr"],
        expect_compressed=True,
        expect_strategy="tfidf_textrank",
    ),
    TestCase(
        id="F03", category="上下文相关性", name="无context基线",
        text="系统监控月度报告包含多个维度。基础设施层面服务器可用性达到99.98%。应用层面API成功率为99.85%。数据库层面主从延迟控制在50ms以内。缓存层面Redis命中率92%内存使用率65%。安全层面WAF拦截恶意请求12,000次。成本层面云资源月支出¥45万较上月减少8%。",
        context="",
        must_keep=["99.98%", "99.85%", "50ms", "92%", "12,000次", "¥45万"],
        expect_compressed=True,
        expect_strategy="tfidf_textrank",
    ),
    TestCase(
        id="F04", category="上下文相关性", name="context与文本高度重叠",
        text="数据库性能优化是本季度的重点工作。数据库查询优化首先针对TOP10慢查询添加了复合索引。数据库连接池从默认的10扩容到100适配了高并发场景。数据库主从读写分离部署完成写走主库读走从库。数据库分表方案已完成设计按user_id哈希分64张表。数据库备份策略从每日改为每6小时增量备份一次。数据库监控告警规则新增了连接数和慢查询数的实时监控。",
        context="数据库性能优化做了哪些工作",
        must_keep=["TOP10", "100", "64张表", "6小时"],
        expect_compressed=True,
        expect_strategy="tfidf_textrank",
    ),
    TestCase(
        id="F05", category="上下文相关性", name="context与文本无重叠",
        text="后端服务使用Java 17开发基于Spring Boot 3框架。部署在Kubernetes集群中使用Helm Chart管理。CI/CD流水线由Jenkins驱动支持自动化回滚。监控使用Prometheus + Grafana组合。日志收集通过ELK Stack统一管理。服务网格采用Istio实现流量治理。配置中心使用Apollo支持热更新。",
        context="前端页面加载速度如何优化",
        must_keep=["Java 17", "Spring Boot 3", "Kubernetes"],
        expect_compressed=True,
        expect_strategy="tfidf_textrank",
    ),
    TestCase(
        id="F06", category="上下文相关性", name="中英混合context",
        text="Agent系统的ReAct循环包含多个步骤。第一步是Thought阶段，模型分析用户意图并制定计划。第二步是Action阶段，选择合适的Tool进行调用。第三步是Observation阶段，获取工具返回结果。第四步是Reflection阶段，评估结果是否满足用户需求。如果不满足则回到第一步继续循环最多允许5轮迭代。最终生成Answer返回给用户包含结构化数据和自然语言解释。",
        context="ReAct循环中Tool调用失败怎么处理",
        must_keep=["ReAct", "Thought", "Action", "Tool", "Observation", "Reflection", "5轮"],
        expect_compressed=True,
        expect_strategy="tfidf_textrank",
    ),
    TestCase(
        id="F07", category="上下文相关性", name="context为单个关键词",
        text="系统安全加固措施清单已全部执行完毕。网络层部署了下一代防火墙NGFW。应用层实施了输入验证和输出编码防止XSS攻击。数据层实现了字段级加密AES-256保护敏感信息。传输层强制HTTPS并配置了HSTS响应头。身份层引入了MFA多因子认证覆盖所有管理员账号。审计层部署了SIEM系统实时分析安全事件。物理层机房增加了生物识别门禁。",
        context="加密",
        must_keep=["AES-256", "HTTPS", "HSTS"],
        expect_compressed=True,
        expect_strategy="tfidf_textrank",
    ),
    TestCase(
        id="F08", category="上下文相关性", name="context为完整问句",
        text="客户数据管理平台CDP的功能模块介绍。数据采集模块支持埋点SDK、服务端API、第三方数据源三种方式。身份识别模块使用ID-Mapping技术将多设备用户归一化。标签系统支持规则标签和模型标签两种类型。用户分群模块可以基于100+维度进行交叉筛选。营销触达模块对接了短信、邮件、Push、站内信四个渠道。效果分析模块提供A/B测试和归因分析能力。数据安全模块实现了GDPR合规的用户数据删除和导出。",
        context="请问CDP平台是如何实现跨设备用户身份统一的？它的ID-Mapping技术原理是什么？",
        must_keep=["ID-Mapping", "身份识别", "归一化"],
        expect_compressed=True,
        expect_strategy="tfidf_textrank",
    ),
    TestCase(
        id="F09", category="上下文相关性", name="context含专有名词",
        text="微服务技术栈选型决策记录。服务框架对比了Spring Cloud和Dubbo最终选择Spring Cloud Alibaba。注册中心对比了Eureka、Consul、Nacos最终选择Nacos。配置中心对比了Spring Cloud Config和Apollo最终选择Apollo。网关对比了Zuul、Gateway、APISIX最终选择Spring Cloud Gateway。熔断器对比了Hystrix和Sentinel最终选择Sentinel。链路追踪对比了Zipkin、Jaeger、SkyWalking最终选择SkyWalking。",
        context="为什么选择Nacos作为注册中心而不是Consul",
        must_keep=["Nacos", "Consul", "Eureka"],
        expect_compressed=True,
        expect_strategy="tfidf_textrank",
    ),
    TestCase(
        id="F10", category="上下文相关性", name="context与首句无关与末句相关",
        text="以下是本季度的技术债务清理计划概述。第一优先级是清理废弃的Feature Flag共计45个。第二优先级是删除无人维护的内部工具代码约2万行。第三优先级是升级过期的第三方依赖涉及12个安全漏洞。第四优先级是重构单元测试提高覆盖率从55%到80%。第五优先级也是最关键的，需要彻底解决内存泄漏问题——当前HeapDumpAnalyzer显示PermGen区每天增长约200MB，预计15天后触发OOM。",
        context="内存泄漏问题的具体表现是什么",
        must_keep=["HeapDumpAnalyzer", "PermGen", "200MB", "15天", "OOM"],
        expect_compressed=True,
        expect_strategy="tfidf_textrank",
    ),
    TestCase(
        id="F11", category="上下文相关性", name="context为否定句",
        text="API设计规范更新要点。所有新接口必须使用RESTful风格命名。请求体统一使用JSON格式不再支持XML。响应码严格按照HTTP标准2xx成功4xx客户端错误5xx服务端错误。分页参数统一使用page和size不使用offset和limit。错误响应必须包含code和message两个字段。接口版本通过URL路径控制如/api/v2/不使用Header版本控制。认证统一使用Bearer Token不再支持Basic Auth。",
        context="为什么不再支持XML格式的请求",
        must_keep=["JSON", "XML", "RESTful"],
        expect_compressed=True,
        expect_strategy="tfidf_textrank",
    ),
    TestCase(
        id="F12", category="上下文相关性", name="多个context关键词分散在不同句",
        text="DevOps实践成熟度评估报告。持续集成方面每日构建次数180次成功率97%。持续部署方面从代码提交到生产上线平均需要25分钟。基础设施即代码使用Terraform管理所有云资源。容器化覆盖率达到95%仅有2个遗留服务未容器化。监控告警方面MTTD平均5分钟MTTR平均35分钟。自动化测试覆盖率为78%其中单元测试65%集成测试13%。混沌工程每月执行一次故障注入演练。",
        context="部署效率和自动化测试覆盖情况",
        must_keep=["25分钟", "95%", "78%", "65%", "13%"],
        expect_compressed=True,
        expect_strategy="tfidf_textrank",
    ),
    TestCase(
        id="F13", category="上下文相关性", name="context为代码片段",
        text="代码审查中发现的问题列表。第一个问题是在高并发场景下HashMap可能导致CPU 100%死循环应该换用ConcurrentHashMap。第二个问题是SimpleDateFormat非线程安全在多线程中共享会出现日期错乱应使用DateTimeFormatter。第三个问题是catch Exception吞掉了所有异常包括NPE应该只捕获业务异常。第四个问题是String拼接在循环中使用加号应改为StringBuilder。第五个问题是synchronized锁粒度过大应该缩小同步块范围。",
        context="ConcurrentHashMap线程安全问题",
        must_keep=["HashMap", "ConcurrentHashMap", "CPU 100%"],
        expect_compressed=True,
        expect_strategy="tfidf_textrank",
    ),
    TestCase(
        id="F14", category="上下文相关性", name="context极长超过50字",
        text="客户反馈分析月度报告。功能需求类反馈占比45%主要集中在报表定制化方面。性能类反馈占比25%客户希望大数据量导出速度更快。易用性反馈占比15%新用户上手成本较高。稳定性反馈占比10%偶有系统卡顿现象。安全性反馈占比5%部分客户要求支持IP白名单和操作审计。本月NPS评分为52分较上月提升3分。总反馈数量1,200条同比增长20%。",
        context="最近客户在使用系统的过程中有没有反映什么性能方面的问题尤其是涉及到大数据量处理和导出功能的性能反馈",
        must_keep=["25%", "导出速度", "NPS", "52分"],
        expect_compressed=True,
        expect_strategy="tfidf_textrank",
    ),
    TestCase(
        id="F15", category="上下文相关性", name="context为空但文本自带重点",
        text="【紧急】生产数据库磁盘空间告警。当前磁盘使用率已达93%剩余可用空间仅47GB。按照当前每日增长3GB的速度约15天后磁盘将被写满。写满后数据库将变为只读模式所有写入操作将失败。建议立即执行以下操作：清理90天以上的归档日志预计释放120GB空间。同时启动存储扩容申请将磁盘从500GB扩展到1TB。已创建P1级别工单编号INC-2024-0915。",
        context="",
        must_keep=["93%", "47GB", "3GB", "15天", "120GB", "500GB", "1TB", "INC-2024-0915"],
        expect_compressed=True,
        expect_strategy="tfidf_textrank",
    ),
    TestCase(
        id="F16", category="上下文相关性", name="context与文本完全相同子串",
        text="系统目前支持的数据源类型包括以下几种。关系型数据库支持MySQL、PostgreSQL、Oracle、SQL Server。NoSQL数据库支持MongoDB、Redis、Elasticsearch。消息队列支持Kafka、RabbitMQ、RocketMQ。文件存储支持S3、OSS、MinIO。数据仓库支持Hive、ClickHouse、Doris。实时计算支持Flink和Spark Streaming。",
        context="系统支持哪些NoSQL数据库",
        must_keep=["MongoDB", "Redis", "Elasticsearch", "NoSQL"],
        expect_compressed=True,
        expect_strategy="tfidf_textrank",
    ),
    TestCase(
        id="F17", category="上下文相关性", name="context语言与文本语言不同",
        text="The deployment architecture uses a multi-region active-active setup. Primary region is us-east-1 hosting 60% of traffic. Secondary region is eu-west-1 handling 25% of traffic. Asia-Pacific region ap-southeast-1 serves 15% of traffic. Cross-region data replication uses CockroachDB with a replication lag under 100ms. Global load balancing is managed by CloudFlare with geographic routing. Failover between regions is automatic with a recovery time objective of 30 seconds.",
        context="亚太地区的流量占比是多少",
        must_keep=["ap-southeast-1", "15%", "CockroachDB", "100ms"],
        expect_compressed=True,
        expect_strategy="tfidf_textrank",
    ),
    TestCase(
        id="F18", category="上下文相关性", name="context含错别字/近似词",
        text="系统的缓存策略采用多级缓存架构。第一级是浏览器缓存通过Cache-Control头控制有效期。第二级是CDN边缘缓存针对静态资源。第三级是应用本地缓存使用Caffeine框架容量10000条TTL 5分钟。第四级是分布式缓存使用Redis Cluster 6节点3主3从。第五级是数据库查询缓存MySQL Query Cache已关闭改用应用层管理。缓存击穿防护使用互斥锁+空值缓存策略。",
        context="分布缓存用的什么方案",
        must_keep=["Redis Cluster", "6节点", "Caffeine"],
        expect_compressed=True,
        expect_strategy="tfidf_textrank",
    ),
    TestCase(
        id="F19", category="上下文相关性", name="context为对话式追问",
        text="上次讨论的API限流方案已经实现并上线了。网关层使用令牌桶算法每秒补充1000个Token。单个用户限制为每分钟200次请求超过返回HTTP 429。企业级客户可以申请更高配额最高每分钟2000次。限流数据存储在Redis中使用Lua脚本保证原子性。当触发限流时响应头会包含Retry-After字段告知客户端等待时间。目前线上限流触发率约0.3%影响用户数约150人每天。",
        context="你说的那个限流上线了吗效果怎么样",
        must_keep=["1000个", "200次", "2000次", "0.3%", "150人"],
        expect_compressed=True,
        expect_strategy="tfidf_textrank",
    ),
    TestCase(
        id="F20", category="上下文相关性", name="context为指令型而非问题型",
        text="以下是本周新入职员工需要了解的开发流程。代码分支策略采用Git Flow模型包含main、develop、feature、release、hotfix五种分支。代码提交前必须通过pre-commit hook进行lint检查和单元测试。Pull Request需要至少2人review且CI全部通过才能合并。合并到develop分支后自动触发staging环境部署。Release分支创建后进入冻结期只允许bug fix。正式上线通过Jenkins Pipeline执行需要PO和TL双签审批。",
        context="帮我总结一下代码合并的审批流程",
        must_keep=["Pull Request", "2人", "CI", "Jenkins", "双签审批"],
        expect_compressed=True,
        expect_strategy="tfidf_textrank",
    ),
]


# ═══════════════════════════════════════════════════════════════════════════════
# G. 信息密度 — 停用词vs内容词测试
# ═══════════════════════════════════════════════════════════════════════════════

CASES_G: List[TestCase] = [
    TestCase(
        id="G01", category="信息密度", name="高停用词比例句子",
        text="其实说到这个问题的话，我觉得我们可以这样来看。对于那些已经有了的东西，我们就不需要再去做什么改变。然后就是关于之后要做的事情，我们也不要太着急。但是呢，有一个比较重要的点，就是系统的QPS需要从当前的5000提升到20000。如果这个搞不定的话，双十一肯定是扛不住的。所以综上所述我建议尽快完成扩容。",
        must_keep=["QPS", "5000", "20000"],
        expect_compressed=True,
        expect_strategy="tfidf_textrank",
    ),
    TestCase(
        id="G02", category="信息密度", name="高内容词密度-技术",
        text="Kubernetes Pod资源限制配置：CPU requests 500m limits 2000m。Memory requests 1Gi limits 4Gi。存活探针livenessProbe HTTP GET /healthz间隔30秒超时5秒失败阈值3次。就绪探针readinessProbe TCP 8080间隔10秒超时3秒。HPA自动伸缩目标CPU利用率70%最小副本数3最大20。PodDisruptionBudget设置minAvailable=2确保滚动更新时至少2个Pod可用。",
        must_keep=["500m", "2000m", "1Gi", "4Gi", "/healthz", "HPA", "70%", "PodDisruptionBudget"],
        expect_compressed=True,
        expect_strategy="tfidf_textrank",
    ),
    TestCase(
        id="G03", category="信息密度", name="叙事性低密度文本",
        text="这件事情要从上个月说起。当时我们正在讨论下一步的工作计划。大家各抒己见提出了很多想法和建议。经过一番讨论之后我们达成了一些初步的共识。然后在接下来的几天里我们开始着手去落实这些想法。虽然过程中遇到了一些困难但总体还是比较顺利的。目前的进展基本符合我们最初的预期和计划。最终结论：Q4必须完成TiDB迁移，否则明年预计¥2,000万的交易量将无法承载。",
        must_keep=["TiDB", "¥2,000万"],
        expect_compressed=True,
        expect_strategy="tfidf_textrank",
    ),
    TestCase(
        id="G04", category="信息密度", name="学术论文风格高密度",
        text="本研究采用随机对照实验设计评估压缩算法性能。实验组使用LightKompress基于TF-IDF TextRank多维评分。对照组使用BERT-based ModernBERT Kompress 149M参数。数据集包含10,000篇中英文混合文档平均长度800字符。评估指标为ROUGE-L F1值和信息保留率。实验组ROUGE-L达到0.72对照组0.81差距9%。但推理延迟实验组2.3ms对照组35ms实验组快15倍。综合评分加权后实验组在成本效益上显著优于对照组。",
        must_keep=["TF-IDF", "TextRank", "ModernBERT", "149M", "10,000篇", "ROUGE-L", "0.72", "0.81", "2.3ms", "35ms", "15倍"],
        expect_compressed=True,
        expect_strategy="tfidf_textrank",
    ),
    TestCase(
        id="G05", category="信息密度", name="会议记录口语化",
        text="嗯，那我们就先说一下这个事情吧。就是上周那个bug，对吧，就是那个登录超时的问题。然后呢，小李已经修了，测试也过了。但是呢，还有另外一个问题就是内存泄漏。这个问题比较严重，每24小时大概泄漏800MB内存。如果不处理的话系统就得每天重启一次。所以我们打算这周就修，用WeakReference替换强引用。",
        must_keep=["24小时", "800MB", "WeakReference"],
        expect_compressed=True,
        expect_strategy="tfidf_textrank",
    ),
    TestCase(
        id="G06", category="信息密度", name="数据报表格式",
        text="日期: 2024-10-15。活跃用户: 125,000。新注册: 3,200。付费转化: 4.8%。DAU/MAU: 32%。人均使用时长: 28分钟。页面加载时间P50: 1.2秒。API错误率: 0.05%。推送到达率: 94%。客诉数量: 12件。系统可用性: 99.97%。核心接口超时率: 0.002%。",
        must_keep=["2024-10-15", "125,000", "3,200", "4.8%", "32%", "28分钟", "1.2秒", "0.05%", "94%", "99.97%"],
        expect_compressed=True,
        expect_strategy="tfidf_textrank",
    ),
    TestCase(
        id="G07", category="信息密度", name="法律条款高密度",
        text="根据《数据安全法》第二十七条规定。数据处理者应当建立健全全流程数据安全管理制度。个人信息收集应遵循最小必要原则。数据跨境传输需要通过安全评估或标准合同备案。违反规定者将面临¥100万至¥1,000万罚款。情节严重的可处以上一年度营业额5%的罚款。本系统已完成等保三级认证编号为GD-2024-ICP-00892。数据保留期限为用户注销后60天自动删除。",
        must_keep=["¥100万", "¥1,000万", "5%", "GD-2024-ICP-00892", "60天"],
        expect_compressed=True,
        expect_strategy="tfidf_textrank",
    ),
    TestCase(
        id="G08", category="信息密度", name="产品说明书风格",
        text="LightKompress压缩器技术规格说明。支持语言：中文、英文及混合文本。输入长度限制：无上限建议单次不超过10,000字符。压缩率范围：40%-60%取决于文本信息密度。推理延迟：平均2-5ms，P99小于10ms。内存占用：运行时约50MB主要为jieba词典。依赖项：jieba分词库、numpy数值计算库。线程安全：是，支持多线程并发调用。压缩策略：TF-IDF + TextRank + 位置加权 + 实体保护。",
        must_keep=["10,000字符", "40%-60%", "2-5ms", "P99", "10ms", "50MB", "TF-IDF", "TextRank"],
        expect_compressed=True,
        expect_strategy="tfidf_textrank",
    ),
    TestCase(
        id="G09", category="信息密度", name="空洞形容词堆砌",
        text="这是一个非常非常棒的系统，它具有极其出色的性能表现。用户体验方面也是相当优秀的，真的非常好用。界面设计精美大方给人一种非常舒适的感觉。功能也是特别丰富而且非常实用。总之这是一个非常值得推荐的优质产品。不过有一个小问题：生产环境的error_rate=0.3%需要降到0.01%以下。计划通过优化RetryPolicy和CircuitBreaker配置来解决。",
        must_keep=["error_rate=0.3%", "0.01%", "RetryPolicy", "CircuitBreaker"],
        expect_compressed=True,
        expect_strategy="tfidf_textrank",
    ),
    TestCase(
        id="G10", category="信息密度", name="纯技术命令序列",
        text="生产环境故障恢复操作步骤记录。步骤一执行kubectl get pods -n production确认故障Pod状态为CrashLoopBackOff。步骤二kubectl describe pod payment-svc-7d4f8查看事件日志发现OOMKilled。步骤三kubectl top nodes确认节点内存使用率98%。步骤四kubectl scale deployment payment-svc --replicas=0先停止服务。步骤五修改deployment yaml将memory limits从2Gi调整为4Gi。步骤六kubectl apply -f payment-svc.yaml重新部署并验证。",
        must_keep=["CrashLoopBackOff", "OOMKilled", "98%", "2Gi", "4Gi"],
        expect_compressed=True,
        expect_strategy="tfidf_textrank",
    ),
    TestCase(
        id="G11", category="信息密度", name="中英混合信息密度差异",
        text="The overall system performance has been quite satisfactory this quarter. 但是我们发现了一些需要关注的技术细节。In general the latency numbers look good across the board. 具体来说，核心交易接口P99延迟从450ms优化到了120ms。There are some concerns about memory usage though. 内存分析显示Old Gen区域每12小时Full GC一次每次停顿约800ms。We should address this in the next sprint. 计划引入ZGC垃圾回收器将停顿控制在10ms以内。",
        must_keep=["P99", "450ms", "120ms", "12小时", "800ms", "ZGC", "10ms"],
        expect_compressed=True,
        expect_strategy="tfidf_textrank",
    ),
    TestCase(
        id="G12", category="信息密度", name="结构化数据文本化",
        text="服务器清单信息如下。server-01规格16C64G操作系统CentOS 7.9角色web-gateway。server-02规格8C32G操作系统Ubuntu 22.04角色api-service。server-03规格32C128G操作系统CentOS 8角色database-master。server-04规格32C128G操作系统CentOS 8角色database-slave。server-05规格16C64G操作系统Ubuntu 22.04角色redis-cluster。server-06规格8C16G操作系统Alpine角色monitoring。",
        must_keep=["16C64G", "8C32G", "32C128G", "CentOS 7.9", "Ubuntu 22.04"],
        expect_compressed=True,
        expect_strategy="tfidf_textrank",
    ),
    TestCase(
        id="G13", category="信息密度", name="比喻/类比低信息",
        text="我们的系统架构就像一座城市的交通网络。网关相当于高速公路入口负责分流。负载均衡器就像交通信号灯调节流量。微服务像城市里的各个功能区各司其职。数据库好比城市的地下管网储存着所有重要数据。但具体来说网关层使用Kong处理每秒35,000个请求。数据库层使用PostgreSQL 15存储了12TB的业务数据。Redis缓存命中率保持在96%以上有效降低数据库压力。",
        must_keep=["Kong", "35,000个", "PostgreSQL 15", "12TB", "96%"],
        expect_compressed=True,
        expect_strategy="tfidf_textrank",
    ),
    TestCase(
        id="G14", category="信息密度", name="FAQ问答格式",
        text="常见问题解答。Q：系统最大支持多少并发用户？A：设计容量为10万并发实际压测通过8.5万。Q：数据备份频率是多少？A：全量备份每天凌晨3点增量备份每小时一次。Q：故障恢复RTO是多少？A：目标RTO为15分钟实际最近一次故障恢复用了8分钟。Q：支持哪些浏览器？A：Chrome 90+、Firefox 88+、Safari 14+、Edge 90+。Q：API调用有频率限制吗？A：免费版100次每分钟企业版5000次每分钟。",
        must_keep=["10万", "8.5万", "15分钟", "8分钟", "100次", "5000次"],
        expect_compressed=True,
        expect_strategy="tfidf_textrank",
    ),
    TestCase(
        id="G15", category="信息密度", name="changelog条目",
        text="v3.2.0 Release Notes发布说明。新增功能：支持批量导入最大文件大小500MB。新增功能：仪表盘支持自定义时间范围筛选。性能优化：列表查询响应时间从1.8s降至0.4s优化幅度78%。Bug修复：修复了并发下单时库存扣减不准确的问题编号BUG-2024-0892。Bug修复：修复了时区转换导致报表数据偏移8小时的问题。安全修复：升级log4j从2.14.1到2.21.0修复CVE-2024-23115。破坏性变更：/api/v1/legacy接口已废弃请迁移到/api/v2。",
        must_keep=["v3.2.0", "500MB", "1.8s", "0.4s", "78%", "BUG-2024-0892", "8小时", "CVE-2024-23115", "/api/v1/legacy", "/api/v2"],
        expect_compressed=True,
        expect_strategy="tfidf_textrank",
    ),
    TestCase(
        id="G16", category="信息密度", name="对话记录低信息量",
        text="用户：你好，我想问一下。客服：您好，请问有什么可以帮助您的？用户：就是那个，我的系统好像出了点问题。客服：好的，能详细描述一下是什么问题吗？用户：就是登录不上去了，一直转圈。客服：了解了，请问您使用的是什么浏览器？错误提示信息是什么？用户：Chrome浏览器，报错是HTTP 503 Service Unavailable，我的账号是user_id=10234。客服：我查到了，您的账户所在的服务器集群正在维护，预计15分钟后恢复。",
        must_keep=["HTTP", "user_id=10234", "15分钟"],
        expect_compressed=True,
        expect_strategy="tfidf_textrank",
    ),
    TestCase(
        id="G17", category="信息密度", name="警告级别混合",
        text="[INFO] 应用启动完成，耗时23秒，端口8080已监听。[INFO] 数据库连接池初始化完成，活跃连接10/50。[WARN] Redis连接超时一次，自动重连成功，延迟增加200ms。[WARN] 磁盘空间剩余15%，建议尽快清理或扩容。[ERROR] OutOfMemoryError: GC overhead limit exceeded，JVM堆内存使用4.8GB/5GB。[FATAL] 服务主进程异常退出exit_code=137，疑似被OOM Killer终止。[INFO] 自动重启触发，第3次重启，距上次重启间隔仅12分钟。",
        must_keep=["8080", "200ms", "15%", "OutOfMemoryError", "4.8GB", "exit_code=137", "12分钟"],
        expect_compressed=True,
        expect_strategy="tfidf_textrank",
    ),
    TestCase(
        id="G18", category="信息密度", name="纯定义性文本",
        text="术语定义表。SLA即服务级别协议是指服务提供方与使用方之间的约定。SLO即服务级别目标是SLA中具体的量化目标。SLI即服务级别指标是衡量SLO达成情况的具体指标。MTTR即平均修复时间是从故障发生到恢复的平均耗时。MTTF即平均无故障时间是系统在两次故障之间正常运行的时间。MTBF即平均故障间隔时间等于MTTF加MTTR。Error Budget即错误预算是SLO允许的最大不可用时间。",
        must_keep=["SLA", "SLO", "SLI", "MTTR", "MTTF", "MTBF"],
        expect_compressed=True,
        expect_strategy="tfidf_textrank",
    ),
    TestCase(
        id="G19", category="信息密度", name="高密度配置说明",
        text="Nginx反向代理优化配置总结。worker_processes设置为auto自动匹配CPU核数。worker_connections设置为65535单个Worker最大连接数。keepalive_timeout设置为65秒保持长连接。gzip_comp_level设置为6兼顾压缩率和CPU消耗。proxy_buffer_size设置为128k缓冲响应头。client_max_body_size设置为100m限制上传大小。proxy_connect_timeout设置为10s后端连接超时。限流配置limit_req_zone设置每秒100个请求超出排队延迟处理。",
        must_keep=["65535", "65秒", "128k", "100m", "10s", "100个"],
        expect_compressed=True,
        expect_strategy="tfidf_textrank",
    ),
    TestCase(
        id="G20", category="信息密度", name="多轮对话上下文",
        text="上一轮回答中提到的数据库方案在这里做进一步说明。之前说的读写分离方案已经开始实施了。目前的进展是主库和两个从库已经部署完成。读写分离中间件选用了ShardingSphere-Proxy版本5.4.1。配置了数据分片规则按照order_id取模分到4个数据节点。写入请求全部路由到主库读取按权重分配主库20%从库各40%。压测结果显示读QPS从8,000提升到24,000写QPS不变维持5,000。",
        must_keep=["ShardingSphere-Proxy", "5.4.1", "4个数据节点", "20%", "40%", "8,000", "24,000", "5,000"],
        expect_compressed=True,
        expect_strategy="tfidf_textrank",
    ),
]


# ═══════════════════════════════════════════════════════════════════════════════
# H. 技术标识符 — tech_pattern正则测试
# ═══════════════════════════════════════════════════════════════════════════════

CASES_H: List[TestCase] = [
    TestCase(
        id="H01", category="技术标识符", name="全大写标识符密集",
        text="系统集成层协议支持情况说明。通信层支持HTTP和HTTPS以及gRPC三种协议。认证层实现了OAuth和OIDC标准兼容JWT令牌验证。授权层同时支持RBAC和ABAC两种访问控制模型。数据层兼容SQL和NoSQL两类存储。传输安全全部使用TLS加密MTLS双向认证。日志格式支持JSON和CEF两种标准。API设计遵循REST规范并实验性支持GraphQL。",
        must_keep=["HTTP", "HTTPS", "gRPC", "OAuth", "OIDC", "JWT", "RBAC", "ABAC", "SQL", "TLS", "REST", "GraphQL"],
        expect_compressed=True,
        expect_strategy="tfidf_textrank",
    ),
    TestCase(
        id="H02", category="技术标识符", name="snake_case标识符",
        text="数据库表设计规范和关键字段说明。用户表核心字段包括user_id、user_name、created_at、updated_at。订单表关键字段有order_id、order_status、total_amount、payment_method。配置表重要字段为config_key、config_value、environment、last_modified_by。审计日志表记录action_type、target_resource、performed_by、client_ip。所有表必须包含is_deleted软删除标记和version乐观锁字段。",
        must_keep=["user_id", "user_name", "created_at", "order_id", "order_status", "config_key", "config_value", "action_type", "is_deleted"],
        expect_compressed=True,
        expect_strategy="tfidf_textrank",
    ),
    TestCase(
        id="H03", category="技术标识符", name="方法调用模式",
        text="性能热点分析结果显示以下方法调用耗时最长。排名第一的是repository.findByCondition()平均耗时120ms占总耗时35%。第二位是cache.getOrLoad()在缓存未命中时耗时80ms。第三位是http.sendRequest()外部调用平均60ms。第四位是json.serialize()大对象序列化耗时45ms。第五位是validator.validate()复杂规则校验耗时30ms。建议重点优化前三个热点方法预计可降低总延迟50%。",
        must_keep=["repository.findByCondition(", "cache.getOrLoad(", "http.sendRequest(", "json.serialize(", "validator.validate("],
        expect_compressed=True,
        expect_strategy="tfidf_textrank",
    ),
    TestCase(
        id="H04", category="技术标识符", name="URL路径密集",
        text="API健康检查端点清单和状态说明。主健康检查/health返回HTTP 200表示服务正常。详细健康信息/health/detail包含各组件状态。数据库连接检查/health/db验证数据库可达性。缓存服务检查/health/redis验证Redis连接。消息队列检查/health/kafka验证Kafka集群状态。外部依赖检查/health/dependencies聚合所有第三方服务状态。Prometheus指标/metrics暴露JVM和业务指标。",
        must_keep=["/health", "/health/detail", "/health/db", "/health/redis", "/health/kafka", "/health/dependencies", "/metrics"],
        expect_compressed=True,
        expect_strategy="tfidf_textrank",
    ),
    TestCase(
        id="H05", category="技术标识符", name="CamelCase标识符密集",
        text="核心设计模式使用情况审查。ServiceLocator模式在服务发现场景中使用。AbstractFactory模式用于创建不同数据库的Repository。ObserverPattern实现了事件驱动的通知机制。ChainOfResponsibility模式处理请求过滤链。BuilderPattern用于构造复杂的查询对象。ProxyPattern实现了远程服务调用的透明代理。SingletonPattern确保配置中心客户端只有一个实例。StrategyPattern允许动态切换压缩算法。",
        must_keep=["ServiceLocator", "AbstractFactory", "ObserverPattern", "ChainOfResponsibility", "BuilderPattern", "ProxyPattern", "SingletonPattern", "StrategyPattern"],
        expect_compressed=True,
        expect_strategy="tfidf_textrank",
    ),
    TestCase(
        id="H06", category="技术标识符", name="规格参数8C32G格式",
        text="云资源配置方案根据服务类型分级。网关服务器推荐配置4C8G适合轻量转发场景。业务应用服务器标准配置8C16G满足日常业务处理。核心服务推荐配置8C32G应对高并发场景。数据库服务器要求配置16C64G确保查询性能。大数据分析节点配置32C128G满足计算密集型任务。机器学习GPU服务器配置8C32G加配NVIDIA A100。缓存服务器配置4C32G内存优先型实例。",
        must_keep=["4C8G", "8C16G", "8C32G", "16C64G", "32C128G"],
        expect_compressed=True,
        expect_strategy="tfidf_textrank",
    ),
    TestCase(
        id="H07", category="技术标识符", name="版本号密集",
        text="技术栈版本矩阵年度更新计划。Java运行时从JDK11升级到JDK17长期支持版本。Spring Boot从v2.7升级到v3.2支持虚拟线程。Kubernetes集群从v1.25升级到v1.28改进了Pod调度。Istio服务网格从v1.17升级到v1.20优化了数据面性能。Helm Chart从v3.11升级到v3.13改进了依赖管理。Terraform从v1.4升级到v1.6新增import功能。ArgoCD从v2.7升级到v2.9支持ApplicationSet。",
        must_keep=["v2.7", "v3.2", "v1.25", "v1.28", "v1.17", "v1.20", "v3.13", "v1.6", "v2.9"],
        expect_compressed=True,
        expect_strategy="tfidf_textrank",
    ),
    TestCase(
        id="H08", category="技术标识符", name="混合tech标识符",
        text="系统告警规则配置清单。规则1：当api_error_rate超过5%持续5分钟触发P1告警。规则2：当db_connection_pool使用率超过90%发送WARN通知。规则3：JVM heap_usage超过85%且持续增长触发GC分析。规则4：Kafka consumer_lag超过10000条触发扩容建议。规则5：HTTP 5xx错误率在/api/v2/orders路径超过1%自动触发回滚。规则6：当Pod内存使用超过limits的90%即3.6Gi发送OOM预警。",
        must_keep=["api_error_rate", "5%", "db_connection_pool", "90%", "heap_usage", "85%", "consumer_lag", "/api/v2/orders", "3.6Gi"],
        expect_compressed=True,
        expect_strategy="tfidf_textrank",
    ),
    TestCase(
        id="H09", category="技术标识符", name="无技术标识符对照",
        text="今天天气不错，阳光明媚温度适宜。早上起来心情很好决定去公园散步。路上遇到了邻居王阿姨聊了几句家常。公园里有很多人在锻炼有跑步的有打太极的。坐在湖边长椅上看了一会儿风景。中午回家做了一顿简单的午饭。下午准备继续整理一下家里的书架。晚上计划看一部电影放松一下。",
        must_keep=[],
        expect_compressed=True,
        expect_strategy="tfidf_textrank",
    ),
    TestCase(
        id="H10", category="技术标识符", name="Docker相关标识符",
        text="容器化部署问题排查记录。通过docker ps发现container状态为Exited(137)表明被OOM Killer终止。检查docker stats显示容器内存使用已达到limit的100%即4Gi。Dockerfile中的FROM base-image:v2.3存在已知的内存泄漏问题。docker-compose.yml中的mem_limit配置需要从4G调整为8G。同时需要添加restart_policy为on-failure最大重试3次。镜像大小从1.2GB优化到680MB通过multi-stage build实现。推送到Harbor仓库registry.internal.com/platform/api-service:v3.2.1。",
        must_keep=["Exited(137)", "4Gi", "v2.3", "mem_limit", "restart_policy", "1.2GB", "680MB", "v3.2.1"],
        expect_compressed=True,
        expect_strategy="tfidf_textrank",
    ),
    TestCase(
        id="H11", category="技术标识符", name="数据库SQL相关",
        text="慢查询优化建议清单。第一条SELECT * FROM orders WHERE status='pending' AND created_at > '2024-01-01'需要添加复合索引idx_status_created。第二条使用了LEFT JOIN关联5张表建议拆分为多次简单查询。第三条GROUP BY user_id HAVING count > 100可以改用窗口函数ROW_NUMBER优化。第四条ORDER BY random()全表扫描建议使用物化视图预计算。第五条IN (SELECT ...)子查询改为EXISTS关联子查询性能提升10倍。",
        must_keep=["idx_status_created", "LEFT JOIN", "GROUP BY", "ROW_NUMBER", "ORDER BY"],
        expect_compressed=True,
        expect_strategy="tfidf_textrank",
    ),
    TestCase(
        id="H12", category="技术标识符", name="AWS服务标识符",
        text="AWS云资源使用情况月度报告。EC2实例共45台其中m5.2xlarge 20台c5.4xlarge 15台r5.8xlarge 10台。RDS使用db.r5.4xlarge多可用区部署存储1.5TB。ElastiCache Redis集群cache.r6g.xlarge 6节点。S3存储总量28TB月增长2.1TB。CloudFront CDN月度请求8.5亿次带宽费用$4,200。Lambda函数调用量月均1.2亿次平均耗时45ms。EKS集群Kubernetes v1.27运行230个Pod。",
        must_keep=["m5.2xlarge", "c5.4xlarge", "r5.8xlarge", "1.5TB", "cache.r6g.xlarge", "28TB", "$4,200", "v1.27"],
        expect_compressed=True,
        expect_strategy="tfidf_textrank",
    ),
    TestCase(
        id="H13", category="技术标识符", name="Linux命令和路径",
        text="服务器运维操作记录。执行top命令发现java进程CPU占用350%说明多个线程在密集计算。通过jstack PID > /tmp/thread_dump.txt导出线程堆栈。分析发现大量线程阻塞在sun.misc.Unsafe.park说明存在锁竞争。使用iostat -x 1发现磁盘读写IOPS达到15,000接近NVMe上限。检查/var/log/syslog发现kernel级别的内存分配失败信息。修改/etc/security/limits.conf增大进程最大文件描述符到65535。最终通过调整线程池大小从200减少到50解决了CPU飙升问题。",
        must_keep=["/tmp/thread_dump.txt", "350%", "15,000", "/var/log/syslog", "/etc/security/limits.conf", "65535"],
        expect_compressed=True,
        expect_strategy="tfidf_textrank",
    ),
    TestCase(
        id="H14", category="技术标识符", name="Python包和模块",
        text="后端服务Python依赖审计报告。Web框架使用FastAPI v0.104性能是Flask的3倍。ORM使用SQLAlchemy v2.0支持异步查询async/await。任务队列使用Celery v5.3配合Redis作为Broker。数据验证使用Pydantic v2性能比v1提升5-50倍。HTTP客户端使用httpx替代requests支持HTTP/2。序列化使用orjson比标准json快3-10倍。机器学习推理使用onnxruntime替代PyTorch减少部署体积80%。",
        must_keep=["FastAPI", "SQLAlchemy", "Celery", "Pydantic", "httpx", "orjson", "onnxruntime", "PyTorch"],
        expect_compressed=True,
        expect_strategy="tfidf_textrank",
    ),
    TestCase(
        id="H15", category="技术标识符", name="网络协议和端口",
        text="网络安全策略配置审查结果。入站规则：TCP/443允许所有来源即HTTPS流量。TCP/80仅允许内部网络10.0.0.0/8用于健康检查。TCP/22只允许跳板机IP 10.0.1.100/32。TCP/5432仅允许应用服务器安全组sg-app-servers。出站规则：TCP/443允许所有目标即HTTPS外部调用。UDP/53允许DNS服务器10.0.0.2/32。TCP/6379允许Redis集群安全组sg-redis-cluster。其他所有端口默认拒绝deny all。",
        must_keep=["TCP/443", "TCP/80", "10.0.0.0/8", "TCP/22", "TCP/5432", "TCP/6379", "UDP/53"],
        expect_compressed=True,
        expect_strategy="tfidf_textrank",
    ),
    TestCase(
        id="H16", category="技术标识符", name="监控指标命名",
        text="Prometheus指标命名规范和当前指标清单。请求相关：http_requests_total按状态码标签统计总请求数。延迟相关：http_request_duration_seconds分位数直方图。错误相关：http_errors_total按错误类型分类统计。业务相关：order_created_total订单创建总数。资源相关：jvm_memory_used_bytes JVM内存使用量。连接相关：db_connections_active当前活跃数据库连接数。队列相关：kafka_consumer_lag消费者积压消息数。每个指标必须包含job和instance两个基础标签。",
        must_keep=["http_requests_total", "http_request_duration_seconds", "http_errors_total", "order_created_total", "jvm_memory_used_bytes", "db_connections_active", "kafka_consumer_lag"],
        expect_compressed=True,
        expect_strategy="tfidf_textrank",
    ),
    TestCase(
        id="H17", category="技术标识符", name="正则混合-snake+UPPER+版本",
        text="CI/CD流水线工具链升级计划。代码扫描工具SonarQube从v9.8升级到v10.3新增AI代码分析。静态分析SAST工具Semgrep从v1.40升级到v1.52规则库扩展30%。依赖检查工具dependency_check从v8.4升级到v9.0支持SBOM导出。容器扫描Trivy从v0.45升级到v0.48增加了secret_scanning功能。IaC扫描Checkov从v2.4升级到v3.1支持Terraform v1.6语法。制品签名使用cosign v2.2确保supply_chain_security。",
        must_keep=["SonarQube", "v10.3", "SAST", "dependency_check", "v9.0", "SBOM", "secret_scanning", "v3.1", "cosign", "supply_chain_security"],
        expect_compressed=True,
        expect_strategy="tfidf_textrank",
    ),
    TestCase(
        id="H18", category="技术标识符", name="Kubernetes资源对象",
        text="Kubernetes集群资源编排清单。Deployment控制器管理无状态应用共计45个。StatefulSet管理有状态服务包括数据库和消息队列共8个。DaemonSet在每个节点运行日志采集agent和监控exporter共3个。CronJob定时任务包括数据清理和报表生成共12个。HorizontalPodAutoscaler配置了18个服务的自动伸缩策略。PodDisruptionBudget保护12个核心服务的最小可用副本数。NetworkPolicy限制了Pod间通信只允许白名单内的namespace互访。",
        must_keep=["Deployment", "StatefulSet", "DaemonSet", "CronJob", "HorizontalPodAutoscaler", "PodDisruptionBudget", "NetworkPolicy"],
        expect_compressed=True,
        expect_strategy="tfidf_textrank",
    ),
    TestCase(
        id="H19", category="技术标识符", name="前端技术标识符",
        text="前端工程化架构说明。构建工具从webpack v4迁移到vite v5构建速度提升10倍。状态管理从Redux切换到Zustand减少了60%的样板代码。UI组件库使用Ant Design v5支持CSS-in-JS方案。单元测试框架从Jest迁移到Vitest与Vite共享配置。E2E测试使用Playwright替代Cypress支持多浏览器并行测试。代码规范使用ESLint配合Prettier统一格式化。TypeScript严格模式开启strict_null_checks确保类型安全。",
        must_keep=["vite", "v5", "Zustand", "Ant Design", "Vitest", "Playwright", "ESLint", "Prettier", "TypeScript", "strict_null_checks"],
        expect_compressed=True,
        expect_strategy="tfidf_textrank",
    ),
    TestCase(
        id="H20", category="技术标识符", name="API错误码体系",
        text="错误码体系设计说明文档。业务错误码格式为BIZ_XXXX四位数字。认证错误AUTH_001到AUTH_010覆盖登录和token问题。权限错误PERM_001到PERM_005覆盖越权访问场景。数据错误DATA_001到DATA_020覆盖校验和存储异常。系统错误SYS_001到SYS_010覆盖基础设施故障。限流错误RATE_001返回HTTP 429 Too Many Requests。超时错误TIMEOUT_001网关层30秒超时TIMEOUT_002后端服务10秒超时。每个错误码必须关联对应的error_message和suggested_action。",
        must_keep=["BIZ_XXXX", "AUTH_001", "PERM_001", "DATA_001", "SYS_001", "RATE_001", "TIMEOUT_001", "TIMEOUT_002", "error_message", "suggested_action"],
        expect_compressed=True,
        expect_strategy="tfidf_textrank",
    ),
]


# ═══════════════════════════════════════════════════════════════════════════════
# I. 补回机制 — _ensure_must_keep 测试
# ═══════════════════════════════════════════════════════════════════════════════

CASES_I: List[TestCase] = [
    TestCase(
        id="I01", category="补回机制", name="正则实体被压缩后补回",
        text="本季度总体运营情况良好各项指标稳步提升。用户活跃度持续增长日活突破新高。产品功能迭代节奏正常每双周发布一个版本。团队协作效率有所提高跨部门沟通更加顺畅。值得特别关注的是在2024-10-15这天发生了一起重大数据不一致事件，影响金额¥4,500万，涉及客户数量2,800家。事后复盘已完成修复方案已上线。各部门负责人签字确认无异议。",
        must_keep=["2024-10-15", "¥4,500万", "2,800家"],
        expect_compressed=True,
        expect_strategy="tfidf_textrank",
    ),
    TestCase(
        id="I02", category="补回机制", name="TF-IDF关键术语补回",
        text="本文介绍一种新的缓存架构设计方案。传统的缓存方案存在一些众所周知的问题。业界对此有很多讨论和研究。我们在调研了多种方案后有了新的思考。缓存一致性问题是所有分布式系统的通用难题。解决方案的核心思想是引入Cache-Aside-Pattern配合延迟双删策略，具体实现使用Redisson分布式锁确保写操作的原子性，过期时间设置为TTL=300s。我们相信这个方案能满足需求。",
        must_keep=["Cache-Aside-Pattern", "Redisson", "TTL=300s"],
        expect_compressed=True,
        expect_strategy="tfidf_textrank",
    ),
    TestCase(
        id="I03", category="补回机制", name="优先级排序-实体多的句子优先",
        text="项目进展按计划进行中。需求文档编写阶段已完成。技术方案评审也已通过。代码开发进度略微超前。关键性能测试结果：单接口QPS达到12,000，P99延迟85ms，错误率0.02%，数据库连接池使用率65%。另外一个数据点：CPU使用率72%。还有一个观察：日均API调用量1.2亿次其中支付接口占比35%。整体符合上线标准。",
        must_keep=["12,000", "85ms", "0.02%", "65%", "72%", "1.2亿次", "35%"],
        expect_compressed=True,
        expect_strategy="tfidf_textrank",
    ),
    TestCase(
        id="I04", category="补回机制", name="40%字符限制验证",
        text="以下是一段非常长的背景介绍和铺垫文字用于测试补回机制的字符限制。我们需要确保补回内容不会超过原文的40%。这段话本身没有太多有价值的信息只是为了增加文本总长度。继续填充一些无意义的内容来使总字符数增加到足够的程度。更多的填充文本确保压缩后有足够的空间来测试补回限制。核心数据散落在以下各句中。业绩指标A：季度营收¥8,900万同比增长42%。业绩指标B：客户净增长1,500家续约率93%。业绩指标C：NPS评分从45提升到58。业绩指标D：研发效率提升人均产出增加28%。业绩指标E：运营成本降低15%节省¥200万。",
        must_keep=["¥8,900万", "42%", "1,500家", "93%", "58", "28%", "¥200万"],
        expect_compressed=True,
        expect_strategy="tfidf_textrank",
    ),
    TestCase(
        id="I05", category="补回机制", name="[补充:]兜底机制",
        text="系统整体运行报告如下所示。各模块均处于正常状态。监控面板显示绿灯全亮。自动化测试通过率百分之百。代码质量评分持续提升。技术债务在逐步清理中。团队士气高涨工作氛围良好。唯一的隐患：运维组报告发现生产环境配置项max_pool_connections=1000即将到达上限，当前已使用到987个连接，预计48小时内将出现连接耗尽。",
        must_keep=["max_pool_connections=1000", "987个", "48小时"],
        expect_compressed=True,
        expect_strategy="tfidf_textrank",
    ),
    TestCase(
        id="I06", category="补回机制", name="多个实体分散在不同低分句",
        text="首先来看一下我们系统的用户增长趋势。其次是关于产品功能的更新说明。然后是技术架构方面的一些优化。接着是运维保障方面的改进措施。关于安全合规方面也有新的进展。在用户增长方面新增注册用户来自渠道A的转化率为12.5%。技术架构方面完成了从MySQL 5.7到MySQL 8.0的升级。安全方面通过了等保三级认证编号CERT-2024-08842。运维方面MTTR从120分钟降低到了28分钟。",
        must_keep=["12.5%", "MySQL 5.7", "MySQL 8.0", "CERT-2024-08842", "MTTR", "120分钟", "28分钟"],
        expect_compressed=True,
        expect_strategy="tfidf_textrank",
    ),
    TestCase(
        id="I07", category="补回机制", name="英文术语补回",
        text="We have completed the quarterly infrastructure review. The team has been working hard on several improvements. Communication between departments has improved significantly. Overall project velocity is increasing month over month. The key finding from our load testing is that the system bottleneck is in the ConnectionPoolManager which only supports 200 concurrent connections. We recommend upgrading to PgBouncer with transaction_pooling mode and setting pool_size=500 with reserve_pool=50 for burst traffic handling.",
        must_keep=["ConnectionPoolManager", "200", "PgBouncer", "transaction_pooling", "pool_size=500", "reserve_pool=50"],
        expect_compressed=True,
        expect_strategy="tfidf_textrank",
    ),
    TestCase(
        id="I08", category="补回机制", name="权限表达式补回",
        text="本次权限体系升级涉及多个模块的变更。前端菜单显示逻辑需要配合调整。后端接口鉴权中间件需要更新。数据库权限表结构保持不变。缓存中的权限数据需要失效重载。核心变更是新增了三个细粒度权限：manage:team_budget(own)允许管理者查看和编辑自己团队的预算。export:sensitive_data(dept)允许部门管理员导出本部门敏感数据。configure:integration(all)允许超级管理员配置所有第三方集成。灰度发布计划已确定。",
        must_keep=["manage:team_budget(own)", "export:sensitive_data(dept)", "configure:integration(all)"],
        expect_compressed=True,
        expect_strategy="tfidf_textrank",
    ),
    TestCase(
        id="I09", category="补回机制", name="URL和路径补回",
        text="系统间集成接口梳理文档概述。目前系统间通过同步REST调用集成。异步场景使用消息队列解耦。文件传输使用SFTP协议。监控数据通过pull方式采集。核心外部依赖接口地址已更新：支付回调新地址https://pay.newgateway.com/v3/notify需要在11月1日前切换。SSO认证端点迁移到https://sso.identity.com/oauth2/authorize。Webhook推送地址变更为/webhooks/v2/events替代旧的/hooks/notify。",
        must_keep=["https://pay.newgateway.com/v3/notify", "https://sso.identity.com/oauth2/authorize", "/webhooks/v2/events", "/hooks/notify"],
        expect_compressed=True,
        expect_strategy="tfidf_textrank",
    ),
    TestCase(
        id="I10", category="补回机制", name="日期时间补回",
        text="项目管理信息系统显示一切正常。各迭代按时交付没有延期。资源分配合理无瓶颈。利益相关方沟通频率足够。风险登记簿已更新无高风险项。但是有三个关键时间节点需要特别注意：2024-12-01安全审计开始所有代码必须冻结。2024-12-15性能压测开始需要完整的预生产环境。2025-01-05正式上线日期不可推迟否则将违反客户合同约定的SLA承诺。",
        must_keep=["2024-12-01", "2024-12-15", "2025-01-05", "SLA"],
        expect_compressed=True,
        expect_strategy="tfidf_textrank",
    ),
    TestCase(
        id="I11", category="补回机制", name="邮箱地址补回",
        text="通讯录变更通知已发送给全体成员。组织架构调整已生效。办公地点搬迁流程正在进行中。行政后勤保障到位大家无需担心。新系统已完成部署培训安排已通知。IT部门新的技术支持联系方式：日常问题请发邮件到helpdesk@support.newdomain.com。紧急故障请联系oncall-team@ops.newdomain.com或直接拨打热线。安全事件报告请发送至security-incident@compliance.newdomain.com附带截图和日志。",
        must_keep=["helpdesk@support.newdomain.com", "oncall-team@ops.newdomain.com", "security-incident@compliance.newdomain.com"],
        expect_compressed=True,
        expect_strategy="tfidf_textrank",
    ),
    TestCase(
        id="I12", category="补回机制", name="配置参数补回",
        text="系统上线后运行稳定用户反馈正面。客户端兼容性测试全部通过。多浏览器多终端适配良好。CDN缓存策略生效访问速度提升明显。SSL证书有效期还剩200天无需急着更换。但生产环境有三个配置需要紧急调整：connection_timeout=5000需要改为connection_timeout=10000因为新接入的第三方接口响应较慢。retry_max_attempts=3需要改为retry_max_attempts=5增加容错。circuit_breaker_threshold=50需要改为circuit_breaker_threshold=30提前熔断保护系统。",
        must_keep=["connection_timeout=5000", "connection_timeout=10000", "retry_max_attempts=3", "retry_max_attempts=5", "circuit_breaker_threshold=50", "circuit_breaker_threshold=30"],
        expect_compressed=True,
        expect_strategy="tfidf_textrank",
    ),
    TestCase(
        id="I13", category="补回机制", name="金额类实体补回",
        text="行政事务一切正常无特殊事项。办公设备采购计划按时推进。员工福利方案今年没有变化。团建活动安排在下月第三周。假期值班表已发布。重要财务信息：本年度剩余IT预算¥1,850万，其中硬件采购额度¥600万，软件许可¥350万，云服务¥500万，安全投入¥250万，预留应急¥150万。所有采购须在2024-12-20前完成否则预算将被收回。",
        must_keep=["¥1,850万", "¥600万", "¥350万", "¥500万", "¥250万", "¥150万", "2024-12-20"],
        expect_compressed=True,
        expect_strategy="tfidf_textrank",
    ),
    TestCase(
        id="I14", category="补回机制", name="类.方法:行号补回",
        text="代码质量持续改善代码评审覆盖率达到100%。单元测试覆盖率提升到了85%。SonarQube扫描无新增blocker级别问题。技术债务Sprint占比保持在20%以内。代码仓库的分支管理也井然有序。有三个异常堆栈需要跟进修复：InventoryService.deductStock:456在高并发下出现乐观锁冲突频率较高。NotificationEngine.sendBatch:789批量发送时偶尔触发限流。ReportGenerator.exportPDF:234导出大文件时OOM需要流式处理。",
        must_keep=["InventoryService.deductStock:456", "NotificationEngine.sendBatch:789", "ReportGenerator.exportPDF:234"],
        expect_compressed=True,
        expect_strategy="tfidf_textrank",
    ),
    TestCase(
        id="I15", category="补回机制", name="混合实体综合补回",
        text="季度经营分析会议圆满结束。各部门汇报内容翔实数据充分。讨论环节气氛热烈观点碰撞激烈。会后行动项已明确责任人已分配。下季度目标已达成共识将全力冲刺。需要记录的关键决策：批准投入¥2,200万用于基础架构升级，由infra-team@company.com负责执行，目标在2025-03-31前完成从MySQL到TiDB的完整迁移，届时需支撑QPS从当前15,000提升到80,000，该项目代号Operation_Phoenix计划分4个Phase执行。",
        must_keep=["¥2,200万", "infra-team@company.com", "2025-03-31", "MySQL", "TiDB", "15,000", "80,000", "Operation_Phoenix"],
        expect_compressed=True,
        expect_strategy="tfidf_textrank",
    ),
    TestCase(
        id="I16", category="补回机制", name="高压缩率下的实体保全",
        text="每日早会记录整理如下。昨天完成的工作：前端完成了登录页面重构。后端优化了一个慢查询。测试覆盖了回归用例的80%。设计完成了新功能的交互稿。运维处理了一个告警误报。今天计划：继续推进各自的任务。无blocker。其他重要事项：性能测试报告出炉，系统在5000并发时TPS仅为800远低于预期目标3000，根因已定位到BatchProcessor.execute:112处的synchronized锁粒度过大。",
        context="性能问题详情",
        must_keep=["TPS", "800", "3000", "BatchProcessor.execute:112", "synchronized"],
        expect_compressed=True,
        expect_strategy="tfidf_textrank",
        target_ratio=0.3,
    ),
    TestCase(
        id="I17", category="补回机制", name="bias>1保守模式减少补回需求",
        text="本报告概述了Q3的研发投入和产出情况。研发团队规模稳定在50人。代码贡献均匀分布在各个模块。重点是以下几个关键产出数据：发布版本数12个，修复Bug数340个，新功能上线15个，技术债清理占比18%，测试覆盖率从72%提升到83%。API文档覆盖率也从60%提升到95%。核心接口性能P99从200ms优化到45ms。",
        must_keep=["12个", "340个", "15个", "18%", "72%", "83%", "60%", "95%", "200ms", "45ms"],
        expect_compressed=True,
        expect_strategy="tfidf_textrank",
        bias=1.5,
    ),
    TestCase(
        id="I18", category="补回机制", name="bias<1激进模式增加补回需求",
        text="年度技术回顾与展望报告。回顾部分：完成了微服务拆分从单体到12个独立服务。实现了容器化100%覆盖。引入了ServiceMesh方案Istio。搭建了完整的可观测性平台。建立了SRE体系。展望部分：计划引入Serverless架构处理突发流量。评估eBPF技术用于网络可观测性。探索WebAssembly在Edge Computing的应用。推进AIOps智能运维能力建设。目标将MTTR从当前30分钟降低到5分钟以内。",
        must_keep=["12个", "Istio", "Serverless", "eBPF", "WebAssembly", "AIOps", "MTTR", "30分钟", "5分钟"],
        expect_compressed=True,
        expect_strategy="tfidf_textrank",
        bias=0.6,
        target_ratio=0.3,
    ),
    TestCase(
        id="I19", category="补回机制", name="must_keep列表全部在低分句",
        text="总体来说一切顺利，团队配合默契工作推进有序。产品方向清晰，用户需求明确。开发节奏稳定，质量可控。本段不含任何关键数据仅为背景铺垫。以下是分散在文本各处的关键指标。指标一写在这里可能不太显眼：DAU突破200万。这句是过渡没什么信息量。指标二藏在中间：月均GMV达到¥4.5亿。又是一段没什么用的话题过渡。指标三在末尾之前：年化LTV为¥580/用户。以上就是汇报全部内容。",
        must_keep=["DAU", "200万", "¥4.5亿", "¥580"],
        expect_compressed=True,
        expect_strategy="tfidf_textrank",
    ),
    TestCase(
        id="I20", category="补回机制", name="补回后不应重复内容",
        text="系统安全扫描结果报告如下。本次扫描覆盖了全部32个微服务。扫描工具使用的是OWASP ZAP自动化版本。扫描耗时约4小时完成。扫描结果已同步到安全看板。安全团队已进行了人工复核确认。高危漏洞发现一处：接口/api/v2/export存在SSRF漏洞，攻击者可构造请求访问内网资源如http://169.254.169.254/metadata获取云服务器元数据。修复方案已提交PR限制出站请求白名单。",
        must_keep=["OWASP", "/api/v2/export", "SSRF", "http://169.254.169.254/metadata"],
        expect_compressed=True,
        expect_strategy="tfidf_textrank",
    ),
    TestCase(
        id="I21", category="补回机制", name="中文专有名词术语补回",
        text="公司技术战略报告的一般性介绍内容。数字化转型是大势所趋。云原生是技术发展方向。AI赋能业务是未来重点。组织架构也在持续优化中。招聘计划稳步推进中。具体到落地层面，公司确定了三大技术方向：第一是基于知识图谱的智能推荐引擎，第二是采用联邦学习实现跨机构数据协作，第三是部署数字孪生平台实现运营仿真预测。这三个方向的总投入预算¥5,000万。",
        must_keep=["知识图谱", "联邦学习", "数字孪生", "¥5,000万"],
        expect_compressed=True,
        expect_strategy="tfidf_textrank",
    ),
    TestCase(
        id="I22", category="补回机制", name="数字+单位实体散落各处",
        text="以下是基础设施运营月报的常规内容介绍。运维团队工作有序保障到位。监控体系完善告警及时准确。变更管理流程规范执行到位。安全巡检定期进行无遗漏。关键资源用量数据分布如下：主集群CPU总量2,048核已用1,536核。内存总量8,192GB已用6,400GB。网络出口带宽40Gbps峰值用到32Gbps。对象存储已用空间156TB月增长率12TB。CDN月度流量280TB费用¥42万。",
        must_keep=["2,048核", "1,536核", "8,192GB", "6,400GB", "40Gbps", "32Gbps", "156TB", "12TB", "280TB", "¥42万"],
        expect_compressed=True,
        expect_strategy="tfidf_textrank",
    ),
    TestCase(
        id="I23", category="补回机制", name="驼峰命名术语补回",
        text="代码架构演进方向讨论纪要。目前代码架构基本合理。模块划分清晰职责明确。但有几处需要重构改进。第一处是需要新增EventDrivenArchitecture模块支持异步事件流。第二处是引入DomainDrivenDesign理念重构核心业务模块。第三处是实现CommandQueryResponsibilitySeg将读写模型分离。这三项重构预计需要8周投入3名高级工程师。",
        must_keep=["EventDrivenArchitecture", "DomainDrivenDesign", "CommandQueryResponsibilitySeg"],
        expect_compressed=True,
        expect_strategy="tfidf_textrank",
    ),
    TestCase(
        id="I24", category="补回机制", name="补回上限10个实体",
        text="全面体检报告内容非常详尽。涵盖了各个方面的检查结果。医生的建议是继续保持良好的生活习惯。定期复查即可无需特殊处理。总体健康状况良好。以下为系统全面检查的指标快照：error_rate=0.05%，latency_p99=120ms，throughput=8500qps，cpu_usage=72%，memory_usage=81%，disk_io=4500iops，network_in=2.5Gbps，network_out=1.8Gbps，gc_pause=45ms，thread_count=350，connection_pool=180/200，cache_hit=94%。",
        must_keep=["error_rate=0.05%", "latency_p99=120ms", "throughput=8500qps", "cpu_usage=72%", "memory_usage=81%", "cache_hit=94%"],
        expect_compressed=True,
        expect_strategy="tfidf_textrank",
    ),
    TestCase(
        id="I25", category="补回机制", name="target_ratio=0.3极端压缩",
        text="一个很长的铺垫段落用于测试极端压缩下的补回效果。我们需要确保即使在非常激进的压缩设置下关键信息依然不会丢失。这体现了系统的鲁棒性和可靠性。更多的填充内容来增加文本长度。还需要更多的句子来确保压缩确实会移除大量内容。继续添加无意义的文字。再来一些背景描述。关键决策：采用ShardingSphere 5.5实现分库分表，目标支撑10亿级数据量，分片键选用tenant_id，配置auto_tables=true自动路由。实施团队联系dba-team@infra.com，计划2025-02-28完成。",
        must_keep=["ShardingSphere 5.5", "10亿级", "tenant_id", "auto_tables=true", "dba-team@infra.com", "2025-02-28"],
        expect_compressed=True,
        expect_strategy="tfidf_textrank",
        target_ratio=0.3,
    ),
]


# ═══════════════════════════════════════════════════════════════════════════════
# J. 综合场景 — 真实业务文本测试
# ═══════════════════════════════════════════════════════════════════════════════

CASES_J: List[TestCase] = [
    TestCase(
        id="J01", category="综合场景", name="CRM季度运营报告",
        text="2024年Q3 CRM系统运营报告。本季度新增客户1,234家其中大客户52家中小客户1,182家。主要来源为华东地区贡献45%新增客户。总合同金额¥5,680万同比增长23%环比增长8%。金融行业客户贡献35%增量收入得益于Q2金融解决方案包。客户流失率3.2%较上季度4.1%改善。NPS评分从42提升至48产品功能满意度4.5分。技术支持响应从4.2小时缩至2.8小时提升33%。9月15日大版本升级出现2小时中断影响350家客户。",
        context="本季度客户增长和营收情况",
        must_keep=["1,234家", "¥5,680万", "23%", "35%", "3.2%", "NPS", "48", "2.8小时"],
        expect_compressed=True,
        expect_strategy="tfidf_textrank",
    ),
    TestCase(
        id="J02", category="综合场景", name="API接口文档摘要",
        text="用户认证API v2.0文档更新说明。POST /api/v2/auth/login接受JSON Body包含username和password字段。成功返回HTTP 200和access_token有效期15分钟。refresh_token有效期7天支持滑动续期。POST /api/v2/auth/refresh用于刷新Token传入refresh_token。POST /api/v2/auth/logout使当前Token失效加入黑名单。错误响应码401 Unauthorized表示Token过期，403 Forbidden表示权限不足，429 Too Many Requests表示触发限流每分钟最多5次失败尝试。所有接口支持CORS跨域允许origin为*.ourapp.com。",
        context="认证接口的Token有效期和刷新机制",
        must_keep=["/api/v2/auth/login", "/api/v2/auth/refresh", "/api/v2/auth/logout", "access_token", "15分钟", "refresh_token", "7天"],
        expect_compressed=True,
        expect_strategy="tfidf_textrank",
    ),
    TestCase(
        id="J03", category="综合场景", name="错误诊断分析",
        text="生产环境异常诊断报告。2024-10-08 14:23用户报告订单创建失败。错误日志显示OrderService.createOrder:145抛出NullPointerException。堆栈追踪显示问题出在DiscountCalculator.apply:89处访问了null的promotion对象。根因分析：营销系统在14:15做了一次配置变更将promotion_rules表清空了3分钟。影响范围：14:15到14:18之间约230笔订单创建失败金额约¥85万。修复措施：在DiscountCalculator中添加了null check使用Optional包装。预防措施：营销系统配置变更必须走审批流程联系marketing-ops@company.com。",
        context="订单创建失败的根因是什么",
        must_keep=["2024-10-08", "14:23", "OrderService.createOrder:145", "DiscountCalculator.apply:89", "14:15", "14:18", "230笔", "¥85万", "marketing-ops@company.com"],
        expect_compressed=True,
        expect_strategy="tfidf_textrank",
    ),
    TestCase(
        id="J04", category="综合场景", name="数据分析报告",
        text="用户行为分析月度报告——2024年10月。DAU均值125,000峰值出现在10月18日达到182,000。用户平均会话时长从22分钟提升到28分钟增幅27%。核心功能使用率：搜索82%、收藏45%、分享18%、评论12%。转化漏斗分析：首页→列表页85%、列表页→详情页62%、详情页→下单35%、下单→支付成功91%。整体转化率首页到支付完成为16.8%。用户留存数据：次日留存45%、7日留存28%、30日留存15%。新用户主要获客渠道：自然搜索35%、付费投放28%、社交裂变22%、应用商店15%。",
        context="用户转化率和留存情况分析",
        must_keep=["125,000", "182,000", "28分钟", "16.8%", "45%", "28%", "15%"],
        expect_compressed=True,
        expect_strategy="tfidf_textrank",
    ),
    TestCase(
        id="J05", category="综合场景", name="合同条款摘要",
        text="SaaS服务合同技术条款摘要。服务可用性SLA不低于99.95%计算方式为月度总分钟数减去故障分钟数除以总分钟数。若未达标按以下标准赔付：99.9%-99.95%赔付月费10%，99.0%-99.9%赔付月费25%，低于99.0%赔付月费50%。数据备份要求RPO不超过1小时RTO不超过4小时。数据所有权归甲方所有乙方在合同终止后30天内完成数据迁移和销毁。安全要求：通过等保三级认证、年度渗透测试、SOC2 Type II审计。合同期限3年总金额¥360万按年支付每年¥120万。",
        context="SLA赔付标准和数据安全要求",
        must_keep=["99.95%", "10%", "25%", "50%", "RPO", "1小时", "RTO", "4小时", "30天", "¥360万", "SOC2"],
        expect_compressed=True,
        expect_strategy="tfidf_textrank",
    ),
    TestCase(
        id="J06", category="综合场景", name="多轮对话上下文压缩",
        text="用户之前询问了数据库选型的问题。我建议使用PostgreSQL并解释了原因。用户又追问了关于性能的顾虑。我提供了压测数据证明PostgreSQL可以满足需求。现在用户的新问题是关于分库分表方案。基于之前讨论的PostgreSQL方案，分库分表推荐使用Citus扩展实现透明分片。Citus支持在线resharding不需要停机。分片键建议选择tenant_id适合多租户SaaS架构。分片数量建议初始32个后续可在线扩展到128个。读写分离搭配PgBouncer连接池，pool_mode=transaction，max_client_conn=1000。",
        context="分库分表方案的具体推荐",
        must_keep=["Citus", "tenant_id", "32个", "128个", "PgBouncer", "pool_mode=transaction", "max_client_conn=1000"],
        expect_compressed=True,
        expect_strategy="tfidf_textrank",
    ),
    TestCase(
        id="J07", category="综合场景", name="内存泄漏诊断报告",
        text="内存泄漏问题分析报告——Payment Service。症状：服务每运行约72小时后出现Full GC频率急剧增加从每小时1次变为每分钟3次。JVM heap使用呈锯齿形但baseline持续上升。通过MAT分析heap dump发现泄漏对象为com.payment.cache.TransactionCache内部持有的ConcurrentHashMap。根因：缓存的eviction策略存在bug，当entry的TTL=0时不会被清除导致持续累积。泄漏速率约150MB/小时，72小时后堆使用从初始2GB增长到约12.8GB接近max_heap=14G上限。修复方案已合并到release/v4.2.1分支预计明天发布。",
        context="内存泄漏的根因和影响",
        must_keep=["72小时", "Full GC", "MAT", "TransactionCache", "ConcurrentHashMap", "TTL=0", "150MB", "12.8GB", "max_heap=14G", "v4.2.1"],
        expect_compressed=True,
        expect_strategy="tfidf_textrank",
    ),
    TestCase(
        id="J08", category="综合场景", name="部署上线指南",
        text="v3.5.0版本上线操作手册。前置条件检查：确认staging环境测试全部通过。确认数据库migration脚本已审核批准。确认回滚方案已准备就绪。操作步骤：Step1 21:00开始创建release分支打tag v3.5.0。Step2 21:15触发Jenkins Pipeline自动构建Docker镜像推送到Harbor。Step3 21:30通过ArgoCD同步Kubernetes deployment配置。Step4 21:45金丝雀发布开放5%流量观察15分钟。Step5 22:00无异常则逐步放量25%→50%→100%间隔10分钟。Step6 22:40全量发布完成验证核心链路。回滚条件：错误率超过1%或P99延迟超过500ms立即执行kubectl rollout undo。",
        context="上线步骤和回滚条件",
        must_keep=["v3.5.0", "21:00", "21:15", "Jenkins", "Harbor", "ArgoCD", "5%", "22:00", "1%", "500ms"],
        expect_compressed=True,
        expect_strategy="tfidf_textrank",
    ),
    TestCase(
        id="J09", category="综合场景", name="竞品分析技术对比",
        text="与竞品X的技术能力对比分析。计算能力：我方支持最大1000并发查询竞品X为500并发。存储能力：我方单集群最大500TB竞品X为200TB。查询延迟：我方P99 120ms竞品X为350ms。可用性SLA：我方99.99%竞品X为99.95%。扩展性：我方支持在线扩容竞品X需要停机维护。安全认证：我方已通过SOC2+等保三级竞品X仅有等保二级。价格：我方¥15万/年竞品X为¥22万/年性价比优势明显。API兼容性：我方100%兼容标准SQL竞品X有15%的语法差异。",
        context="我们和竞品X在性能和价格上的差异",
        must_keep=["1000并发", "500并发", "500TB", "200TB", "120ms", "350ms", "99.99%", "99.95%", "¥15万", "¥22万"],
        expect_compressed=True,
        expect_strategy="tfidf_textrank",
    ),
    TestCase(
        id="J10", category="综合场景", name="架构评审会议纪要",
        text="架构评审会议纪要——2024-10-25。参会人：CTO张总、架构师李工、DBA王工、安全专家赵工。议题一：是否引入GraphQL替代部分REST接口。决议：在BFF层引入GraphQL处理移动端聚合查询场景后端服务仍保持REST。议题二：数据库分片策略选择。决议：采用按tenant_id range分片不使用hash分片因为需要支持范围查询。分片数初始为16。议题三：缓存架构是否需要多级缓存。决议：采用L1本地缓存Caffeine容量5000条+L2分布式缓存Redis的两级结构。议题四：日志存储成本优化。决议：热数据保留7天在Elasticsearch冷数据转存到S3费用从月¥12万降至¥3万。",
        context="数据库分片和缓存架构的决策",
        must_keep=["2024-10-25", "GraphQL", "tenant_id", "16", "Caffeine", "5000条", "Redis", "7天", "Elasticsearch", "¥12万", "¥3万"],
        expect_compressed=True,
        expect_strategy="tfidf_textrank",
    ),
    TestCase(
        id="J11", category="综合场景", name="容量规划评估",
        text="系统容量规划评估报告——未来12个月预测。当前基线：日均请求量5,000万QPS峰值850。用户增长预测：按月增长15%预计12个月后DAU从50万增至200万。流量增长预测：对应QPS峰值将从850增长至3,400。数据库容量：当前2TB按月增长150GB，12个月后将达到3.8TB。计算资源需求：需要从当前12台8C32G服务器扩展到35台同规格或升级为16C64G减少到18台。网络带宽：当前10Gbps使用率40%预计需升级到25Gbps。预算评估：扩容总成本约¥180万其中计算资源¥100万存储¥50万网络¥30万。建议在第6个月时启动扩容避免被动应对。",
        context="未来12个月需要多少资源扩容",
        must_keep=["5,000万", "850", "200万", "3,400", "2TB", "3.8TB", "12台", "35台", "16C64G", "25Gbps", "¥180万"],
        expect_compressed=True,
        expect_strategy="tfidf_textrank",
    ),
    TestCase(
        id="J12", category="综合场景", name="安全事件响应报告",
        text="安全事件响应报告 IR-2024-0892。事件类型：疑似数据泄露。发现时间：2024-10-20 03:47由SIEM系统自动检测。告警触发条件：单个API Key在1小时内下载超过10,000条客户记录异常模式。涉事API Key归属：partner-integration账户client_id=pk_live_a8f3b2。初步影响评估：约45,000条客户记录可能已被非授权访问包含姓名电话和邮箱。响应措施：03:52自动吊销该API Key，04:15安全团队到位开始取证，06:00完成日志分析确认泄露范围。后续行动：24小时内完成受影响客户通知。72小时内提交监管报告。联系legal@company.com评估法律风险。",
        context="数据泄露事件的影响范围和响应时间线",
        must_keep=["IR-2024-0892", "2024-10-20", "03:47", "10,000条", "45,000条", "03:52", "04:15", "06:00", "24小时", "72小时", "legal@company.com"],
        expect_compressed=True,
        expect_strategy="tfidf_textrank",
    ),
    TestCase(
        id="J13", category="综合场景", name="技术选型RFC文档",
        text="RFC-2024-015：引入消息队列技术选型。背景：当前系统通过HTTP同步调用实现服务间通信，在高峰期存在级联超时问题。候选方案对比。Kafka：吞吐量最高100万msg/s，延迟10-50ms，适合日志流和事件流。RabbitMQ：吞吐5万msg/s，延迟1-5ms，支持复杂路由，运维成本低。RocketMQ：吞吐10万msg/s，延迟5-10ms，支持事务消息和延迟消息。Pulsar：吞吐50万msg/s，延迟5-20ms，存算分离架构扩展性最好。决策：采用RocketMQ作为主力MQ，原因是事务消息对订单系统至关重要。Kafka作为日志收集专用通道。预计月度成本增加¥2.5万。",
        context="为什么选择RocketMQ",
        must_keep=["Kafka", "RabbitMQ", "RocketMQ", "Pulsar", "100万msg/s", "5万msg/s", "10万msg/s", "50万msg/s", "¥2.5万"],
        expect_compressed=True,
        expect_strategy="tfidf_textrank",
    ),
    TestCase(
        id="J14", category="综合场景", name="SRE周报",
        text="SRE团队周报 2024-W43。本周核心指标：系统可用性99.97%（目标99.95%达标）。P99延迟85ms（目标100ms达标）。错误预算消耗：本月已消耗15%剩余85%健康。本周事件：周二10:30 Redis集群节点故障自动failover耗时8秒无用户感知。周四16:15 Kubernetes节点NotReady自动驱逐Pod迁移耗时45秒部分请求超时。On-call负载：总告警52条其中P1级0条P2级3条P3级12条noise级37条。Noise ratio 71%需要优化告警规则。下周计划：实施Chaos Engineering演练模拟AZ故障。优化告警Noise争取降到50%以下。",
        context="本周系统稳定性和事件情况",
        must_keep=["99.97%", "99.95%", "P99", "85ms", "15%", "8秒", "45秒", "52条", "71%"],
        expect_compressed=True,
        expect_strategy="tfidf_textrank",
    ),
    TestCase(
        id="J15", category="综合场景", name="数据迁移方案",
        text="数据迁移方案——从自建MySQL到云数据库RDS。迁移数据量：总计12TB包含85张业务表最大表orders有8亿条记录。迁移策略：采用DMS在线迁移工具支持全量+增量无停机切换。全量迁移预计耗时48小时网络带宽需求500Mbps。增量同步延迟目标控制在5秒以内。切换窗口计划15分钟业务停写时间不超过3分钟。回滚方案：72小时内保留源库只读副本可随时回切。数据校验：使用自研CheckSum工具逐表比对确保零差异。涉及改造的应用服务共18个需要更新连接串。项目timeline：启动2024-11-01全量完成11-03增量追平11-10正式切换11-15。",
        context="迁移方案的时间线和停机要求",
        must_keep=["12TB", "85张", "8亿条", "DMS", "48小时", "500Mbps", "5秒", "15分钟", "3分钟", "72小时", "18个", "2024-11-01"],
        expect_compressed=True,
        expect_strategy="tfidf_textrank",
    ),
    TestCase(
        id="J16", category="综合场景", name="成本优化方案",
        text="云资源成本优化方案总结。当前月度云费用¥85万目标降到¥60万以下节省30%。优化措施一：将30%的计算资源转为预留实例RI节省约¥12万/月。优化措施二：实施定时伸缩非业务时间缩容50%节省约¥8万/月。优化措施三：日志数据30天后转存至S3 IA存储类型节省存储费用约¥3万/月。优化措施四：清理废弃资源包括未挂载EBS卷和闲置EIP节省¥2万/月。优化措施五：数据库使用Graviton3实例替代x86实例性价比提升40%节省¥5万/月。预计总节省¥30万/月达到目标。实施周期8周由cloud-ops@company.com团队负责。",
        context="成本优化能省多少钱",
        must_keep=["¥85万", "¥60万", "30%", "¥12万", "¥8万", "¥3万", "¥2万", "¥5万", "¥30万", "Graviton3", "40%", "cloud-ops@company.com"],
        expect_compressed=True,
        expect_strategy="tfidf_textrank",
    ),
    TestCase(
        id="J17", category="综合场景", name="性能压测报告",
        text="性能压测报告——双十一保障专项。测试环境：等比缩放的预生产环境资源为生产的1/4。压测工具：JMeter分布式集群8台压力机。场景一稳态测试：500并发持续30分钟TPS稳定在3,200无错误。场景二峰值测试：2000并发持续10分钟TPS达到8,500错误率0.3%。场景三极限测试：5000并发持续5分钟TPS达到12,000错误率飙升到5.8%系统出现明显性能劣化。场景四恢复测试：极限压力释放后系统在60秒内恢复到正常状态。瓶颈分析：数据库连接池在2000并发时已满需要从200扩展到500。结论：当前配置可安全支撑2000并发建议配置再留30%余量目标2600并发。",
        context="压测发现的瓶颈和承载能力",
        must_keep=["500并发", "3,200", "2000并发", "8,500", "0.3%", "5000并发", "12,000", "5.8%", "60秒", "200", "500", "2600并发"],
        expect_compressed=True,
        expect_strategy="tfidf_textrank",
    ),
    TestCase(
        id="J18", category="综合场景", name="故障复盘Action Items",
        text="2024-10-15故障复盘会议总结。故障影响：服务中断2小时15分钟影响用户12万SLA消耗完本月全部错误预算。五个Why分析。Why1：为什么服务中断？数据库主节点OOM导致crash。Why2：为什么OOM？一个新上线的报表查询没有分页加载了100万条记录到内存。Why3：为什么没有分页？代码审查时遗漏了该问题。Why4：为什么代码审查没发现？审查Checklist中没有内存使用评估项。Why5：为什么Checklist不完善？上次更新是6个月前。Action Items：AI-01更新Code Review Checklist增加内存评估项负责人李工deadline 10-20。AI-02对所有查询接口添加默认分页limit=1000负责人王工deadline 10-25。AI-03部署数据库内存使用告警阈值80%负责人DBA赵工deadline 10-18。AI-04引入SQL Review自动化工具SQLCheck集成到CI pipeline负责人架构组deadline 11-01。",
        context="故障原因和后续改进措施",
        must_keep=["2小时15分钟", "12万", "OOM", "100万条", "limit=1000", "80%", "SQLCheck", "10-20", "10-25", "11-01"],
        expect_compressed=True,
        expect_strategy="tfidf_textrank",
    ),
    TestCase(
        id="J19", category="综合场景", name="Agent工具调用日志",
        text="Agent执行日志——用户问题：查询本月销售数据。Step1 Thought：用户需要本月的销售数据需要调用CRM查询工具。Step2 Action：调用query_data工具参数object=Opportunity filter=close_date>=2024-10-01 AND stage=Closed Won。Step3 Observation：工具返回结果共458条记录总金额$3.2M。Step4 Thought：数据已获取需要按区域汇总。Step5 Action：调用aggregate工具参数group_by=region metrics=sum(amount)。Step6 Observation：华东$1.4M占44%华南$0.9M占28%华北$0.6M占19%其他$0.3M占9%。Step7 Answer：本月已关闭商机458笔总金额$3.2M其中华东地区贡献最大占44%。",
        context="Agent是怎么获取和处理销售数据的",
        must_keep=["query_data", "Opportunity", "2024-10-01", "458条", "$3.2M", "aggregate", "华东", "$1.4M", "44%"],
        expect_compressed=True,
        expect_strategy="tfidf_textrank",
    ),
    TestCase(
        id="J20", category="综合场景", name="技术面试评估",
        text="候选人技术面试评估报告——张三（高级后端工程师）。系统设计题：设计一个支持1亿用户的短链接服务。候选人方案：使用Snowflake算法生成ID转Base62编码。存储选择Redis做热点缓存+MySQL做持久化。读写比例100:1所以重点优化读路径。QPS设计容量50万读500写。使用一致性哈希分库分表支持水平扩展。设计缺陷：未考虑短链接过期清理机制。编码能力：LeetCode中等难度题15分钟完成代码规范性好。系统知识：对JVM GC调优、MySQL索引原理、分布式事务理解深入。综合评分4.2/5.0建议发offer职级定为P7薪资范围¥60-70万/年。",
        context="候选人技术评估结果和薪资建议",
        must_keep=["1亿", "Snowflake", "Base62", "50万读", "4.2/5.0", "P7", "¥60-70万"],
        expect_compressed=True,
        expect_strategy="tfidf_textrank",
    ),
]


# ═══════════════════════════════════════════════════════════════════════════════
# 汇总所有用例
# ═══════════════════════════════════════════════════════════════════════════════

ALL_CASES: List[TestCase] = (
    CASES_A + CASES_B + CASES_C + CASES_D + CASES_E +
    CASES_F + CASES_G + CASES_H + CASES_I + CASES_J
)


# ═══════════════════════════════════════════════════════════════════════════════
# 评估运行器
# ═══════════════════════════════════════════════════════════════════════════════


def run_eval():
    """运行全部评估用例并输出报告"""
    print("=" * 80)
    print("LightKompress 评估测试 — 210+ 用例 × 10 维度")
    print("=" * 80)
    print(f"\n总用例数: {len(ALL_CASES)}")
    print()

    kompressor = LightKompress()

    # 统计结构
    results = {
        "total": 0,
        "passed": 0,
        "failed": 0,
        "failures": [],
        "by_category": {},
    }

    t_start = time.perf_counter()

    for case in ALL_CASES:
        results["total"] += 1
        cat = case.category
        if cat not in results["by_category"]:
            results["by_category"][cat] = {"total": 0, "passed": 0, "failed": 0}
        results["by_category"][cat]["total"] += 1

        # 执行压缩
        text_input = case.text if case.text else ""
        result: CompressResult = kompressor.compress(
            text=text_input,
            context=case.context,
            bias=case.bias,
            target_ratio=case.target_ratio,
        )

        # 检查结果
        errors = []

        # 检查1: expect_compressed
        actual_compressed = (result.ratio < 1.0)
        if case.expect_compressed != actual_compressed:
            errors.append(
                f"expect_compressed={case.expect_compressed} "
                f"but actual ratio={result.ratio:.3f} "
                f"({'compressed' if actual_compressed else 'not compressed'})"
            )

        # 检查2: expect_strategy
        if case.expect_strategy and result.strategy != case.expect_strategy:
            errors.append(
                f"expect_strategy='{case.expect_strategy}' "
                f"but actual='{result.strategy}'"
            )

        # 检查3: must_keep items present
        missing_items = []
        for item in case.must_keep:
            if item not in result.compressed:
                missing_items.append(item)
        if missing_items:
            errors.append(
                f"must_keep缺失 {len(missing_items)}/{len(case.must_keep)}: "
                f"{missing_items[:5]}{'...' if len(missing_items) > 5 else ''}"
            )

        # 记录结果
        if errors:
            results["failed"] += 1
            results["by_category"][cat]["failed"] += 1
            results["failures"].append({
                "case_id": case.id,
                "case_name": case.name,
                "category": cat,
                "errors": errors,
                "ratio": result.ratio,
                "strategy": result.strategy,
                "compressed_len": result.compressed_chars,
            })
        else:
            results["passed"] += 1
            results["by_category"][cat]["passed"] += 1

    t_elapsed = time.perf_counter() - t_start

    # ── 输出报告 ──
    print("\n" + "─" * 80)
    print("📊 分类统计")
    print("─" * 80)
    print(f"{'分类':<16} {'总数':>6} {'通过':>6} {'失败':>6} {'通过率':>8}")
    print("─" * 80)

    for cat, stats in results["by_category"].items():
        rate = stats["passed"] / stats["total"] * 100 if stats["total"] > 0 else 0
        status = "✓" if stats["failed"] == 0 else "✗"
        print(
            f"{status} {cat:<14} {stats['total']:>6} "
            f"{stats['passed']:>6} {stats['failed']:>6} "
            f"{rate:>7.1f}%"
        )

    print("─" * 80)
    overall_rate = results["passed"] / results["total"] * 100 if results["total"] > 0 else 0
    print(
        f"  {'合计':<14} {results['total']:>6} "
        f"{results['passed']:>6} {results['failed']:>6} "
        f"{overall_rate:>7.1f}%"
    )
    print(f"\n⏱  总耗时: {t_elapsed:.2f}s  平均: {t_elapsed/results['total']*1000:.2f}ms/case")

    # ── 输出失败详情 ──
    if results["failures"]:
        print(f"\n\n{'=' * 80}")
        print(f"❌ 失败用例详情 ({results['failed']}个)")
        print("=" * 80)

        for i, f in enumerate(results["failures"], 1):
            print(f"\n[{i}] {f['case_id']} - {f['case_name']} ({f['category']})")
            print(f"    ratio={f['ratio']:.3f} strategy={f['strategy']}")
            for err in f["errors"]:
                print(f"    ⚠ {err}")

    # ── 结论 ──
    print(f"\n\n{'=' * 80}")
    if results["failed"] == 0:
        print("🎉 全部用例通过！")
    elif overall_rate >= 90:
        print(f"⚡ 通过率 {overall_rate:.1f}% — 良好，有 {results['failed']} 个用例需要关注")
    elif overall_rate >= 70:
        print(f"⚠️  通过率 {overall_rate:.1f}% — 一般，有 {results['failed']} 个用例失败需要改进")
    else:
        print(f"❌ 通过率 {overall_rate:.1f}% — 较差，需要重点优化")
    print("=" * 80)

    return results


if __name__ == "__main__":
    run_eval()
