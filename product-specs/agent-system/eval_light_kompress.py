"""
LightKompress 准确率评估框架

评估维度：
  1. 关键信息保留率 (must-keep recall) — 压缩后是否保留了所有关键事实
  2. 场景覆盖率 — 覆盖所有实际业务场景
  3. 压缩率 — 在保证准确率前提下的压缩效果
  4. 上下文相关性 — 结合用户问题时是否保留了相关信息

目标：所有场景 98.5%+ 的关键信息保留率

场景分类（对应 Kompress 处理的纯文本类型）：
  A. 中文业务报告 / 分析结论
  B. 英文技术文档 / API 说明
  C. 中英混合 Agent 推理过程
  D. RAG 召回的知识库文档
  E. 用户上传文档（合同/方案）
  F. 多轮对话历史压缩
  G. 数据分析结论文本
  H. 错误诊断/故障报告
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from typing import Any

from demo_light_kompress import LightKompress, CompressResult


# ═══════════════════════════════════════════════════════════
# 评估数据类型
# ═══════════════════════════════════════════════════════════


@dataclass
class EvalCase:
    """单条评估用例"""
    id: str
    scenario: str               # 场景分类 A-H
    name: str                   # 用例名称
    text: str                   # 待压缩文本
    context: str                # 用户问题/上下文
    must_keep: list[str]        # 必须保留的关键信息（精确匹配或正则）
    must_keep_semantic: list[str] = field(default_factory=list)  # 语义级必须保留
    bias: float = 1.0
    target_ratio: float = 0.5


@dataclass
class EvalResult:
    """单条评估结果"""
    case_id: str
    scenario: str
    name: str
    passed: bool
    must_keep_total: int
    must_keep_found: int
    must_keep_recall: float     # 关键信息保留率
    missing_items: list[str]    # 未保留的关键信息
    compression_ratio: float
    duration_ms: float


@dataclass
class ScenarioReport:
    """场景级汇总"""
    scenario: str
    total_cases: int
    passed_cases: int
    avg_recall: float
    avg_compression: float
    min_recall: float
    failed_cases: list[str]


# ═══════════════════════════════════════════════════════════
# 评估用例集（覆盖所有场景）
# ═══════════════════════════════════════════════════════════

EVAL_CASES: list[EvalCase] = [
    # ── 场景 A: 中文业务报告 ──
    EvalCase(
        id="A01",
        scenario="A-中文业务报告",
        name="CRM季度运营报告",
        context="本季度业务增长数据",
        text=("2024年第三季度CRM系统运营报告。本季度新增客户1,234家，"
              "大客户52家占比4.2%。华东地区贡献45%新增客户，华南28%，"
              "其余地区27%。总合同金额¥5,680万，同比增长23%，环比增长8%。"
              "客户流失率3.2%，较上季度4.1%显著改善。NPS评分48分，"
              "较上季度42分提升6分。技术支持响应时间从4.2小时缩短至2.8小时。"
              "建议Q4重点关注金融行业深度拓展和小微客户留存策略。"),
        must_keep=["1,234", "52", "45%", "5,680", "23%", "3.2%", "48"],
    ),

    EvalCase(
        id="A02",
        scenario="A-中文业务报告",
        name="销售漏斗分析",
        context="各阶段转化率",
        text=("销售漏斗各阶段数据如下。线索阶段：本月新增线索3,456条，"
              "其中市场活动带来1,200条，官网注册890条，转介绍366条，其他1,000条。"
              "商机阶段：线索转商机率为28.5%，共985个有效商机。"
              "方案阶段：商机转方案率为45%，共443个进入方案阶段。"
              "谈判阶段：方案转谈判率62%，共275个进入谈判。"
              "成交阶段：谈判转成交率为41%，最终成交113单，"
              "平均客单价¥18.7万。整体线索到成交的端到端转化率为3.3%。"
              "同比去年同期的2.8%有明显提升，主要得益于商机阶段的AI评分筛选。"),
        must_keep=["3,456", "28.5%", "985", "45%", "443", "62%", "275", "41%", "113", "18.7", "3.3%"],
    ),

    EvalCase(
        id="A03",
        scenario="A-中文业务报告",
        name="客户满意度报告",
        context="客户反馈和满意度",
        text=("2024年Q3客户满意度调研报告。本次调研覆盖856家活跃客户，"
              "回收有效问卷623份，回收率72.8%。整体满意度评分4.2分（5分制），"
              "较Q2的3.9分有所提升。分维度来看：产品功能4.5分，"
              "系统稳定性4.1分，客服响应3.8分，文档完善度3.5分。"
              "不满意的TOP3原因：报表导出速度慢占32%，移动端体验差占28%，"
              "API文档更新不及时占18%。VIP客户满意度4.6分明显高于普通客户的3.9分。"
              "建议重点改进报表引擎性能和移动端适配。"),
        must_keep=["856", "623", "72.8%", "4.2", "4.5", "4.1", "3.8", "3.5", "32%", "28%", "18%"],
    ),

    # ── 场景 B: 英文技术文档 ──
    EvalCase(
        id="B01",
        scenario="B-英文技术文档",
        name="OAuth认证流程",
        context="How does authentication work",
        text=("The authentication system uses OAuth 2.0 with PKCE flow. "
              "When a user logs in, the system validates client_id against registered apps. "
              "Three auth methods are supported: password login with bcrypt cost factor 12, "
              "social login via Google/GitHub, and enterprise SSO using SAML 2.0. "
              "After auth, a JWT access token (15-min expiry) and refresh token (7-day validity) are issued. "
              "Rate limiting: 5 failed attempts per 10-min window triggers 30-min lockout. "
              "MFA supports TOTP (RFC 6238) and WebAuthn/FIDO2. "
              "Current MFA enrollment rate is 78%, target is 95% by Q4."),
        must_keep=["OAuth 2.0", "PKCE", "bcrypt", "SAML 2.0", "JWT", "15-min", "7-day",
                   "5 failed", "30-min", "TOTP", "78%", "95%"],
    ),

    EvalCase(
        id="B02",
        scenario="B-英文技术文档",
        name="API限流策略",
        context="What are the rate limits",
        text=("API Rate Limiting Policy v2.3. All endpoints enforce rate limits based on "
              "the subscription tier. Free tier: 100 requests/minute, 1000 requests/hour. "
              "Pro tier: 500 requests/minute, 10000 requests/hour. Enterprise: 5000 requests/minute, "
              "unlimited hourly. Burst allowance: 2x the per-minute limit for 10 seconds. "
              "When limits are exceeded, the API returns HTTP 429 with a Retry-After header. "
              "Rate limit headers included in every response: X-RateLimit-Remaining, "
              "X-RateLimit-Reset (Unix timestamp). WebSocket connections: max 50 concurrent per account "
              "for Pro, 500 for Enterprise. GraphQL queries are metered at 1 point per node resolved, "
              "with a complexity budget of 10000 points per query."),
        must_keep=["100 requests/minute", "500 requests/minute", "5000 requests/minute",
                   "HTTP 429", "Retry-After", "50 concurrent", "500 for Enterprise", "10000 points"],
    ),

    EvalCase(
        id="B03",
        scenario="B-英文技术文档",
        name="数据库迁移文档",
        context="database migration steps",
        text=("Database Migration Guide: PostgreSQL 14 to 16. "
              "Step 1: Backup current database using pg_dump with --format=custom flag. "
              "Estimated backup size: 450GB for production, ETA 2-3 hours. "
              "Step 2: Install PostgreSQL 16 on target server. Minimum requirements: "
              "32GB RAM, 8 CPU cores, 1TB SSD storage. "
              "Step 3: Run pg_upgrade with --link flag for zero-copy migration. "
              "Expected downtime: 15-30 minutes for databases under 500GB. "
              "Step 4: Update connection strings in all services. "
              "Critical: Set max_connections=500, shared_buffers=8GB, work_mem=256MB. "
              "Step 5: Run ANALYZE on all tables. Full vacuum recommended within 24 hours. "
              "Rollback plan: Keep old cluster for 72 hours post-migration."),
        must_keep=["PostgreSQL 14", "16", "pg_dump", "450GB", "32GB RAM", "8 CPU",
                   "pg_upgrade", "15-30 minutes", "max_connections=500", "shared_buffers=8GB",
                   "72 hours"],
    ),

    # ── 场景 C: 中英混合 Agent 推理 ──
    EvalCase(
        id="C01",
        scenario="C-中英混合Agent推理",
        name="查询超时诊断",
        context="为什么查询超时了",
        text=("在执行query_data工具时遇到了HTTP 504 Gateway Timeout错误。"
              "查询目标是CRM.Opportunity对象，过滤条件stage='Closed Won' AND close_date>='2024-01-01'。"
              "根本原因是Opportunity表有280万条记录，close_date字段缺少索引导致全表扫描。"
              "同时有定时任务占用了数据库连接池。"
              "临时方案：添加分页limit=1000，创建B-tree索引。"
              "长期建议：引入读写分离，分析查询路由到只读副本。"
              "当前已获取823条记录，总金额$12.4M。"),
        must_keep=["504", "Opportunity", "Closed Won", "280万", "close_date",
                   "limit=1000", "B-tree", "823", "$12.4M"],
    ),

    EvalCase(
        id="C02",
        scenario="C-中英混合Agent推理",
        name="字段映射推理过程",
        context="如何映射客户字段",
        text=("分析源系统和目标系统的字段映射关系。源系统（SAP CRM）中的字段："
              "BP_NUMBER → 目标系统Customer.external_id，"
              "NAME1 + NAME2 → Customer.full_name（需要拼接），"
              "SMTP_ADDR → Customer.email，"
              "TEL_NUMBER → Customer.phone（需格式化为+86前缀），"
              "CITY1 → Customer.city，REGION → Customer.province。"
              "数据量方面，SAP侧有42,567条有效客户记录，"
              "其中15,230条有完整联系方式，其余缺少email或phone。"
              "建议分两批导入：第一批完整数据15,230条，"
              "第二批缺失数据27,337条标记为待补充。"
              "关键约束：external_id必须唯一，email格式需校验，phone需统一为E.164格式。"),
        must_keep=["BP_NUMBER", "external_id", "NAME1", "NAME2", "full_name",
                   "SMTP_ADDR", "TEL_NUMBER", "42,567", "15,230", "27,337",
                   "E.164"],
    ),

    EvalCase(
        id="C03",
        scenario="C-中英混合Agent推理",
        name="权限问题诊断",
        context="用户看不到数据",
        text=("用户反馈无法看到销售报表数据。经过排查，问题出在RBAC权限配置。"
              "该用户角色为Sales_Rep，对应的权限集合是：read:opportunity(own), "
              "read:contact(own), write:activity(own)。但销售报表需要的权限是"
              "read:opportunity(all)和read:report(team)。当前系统中共有5个角色层级："
              "Admin > Sales_Director > Sales_Manager > Sales_Rep > Viewer。"
              "Sales_Rep只能看到自己名下的数据，看不到团队汇总报表。"
              "解决方案：新建一个Report_Viewer角色，赋予read:report(team)权限，"
              "然后将该角色附加给需要看报表的Sales_Rep用户。"
              "影响范围：当前有128个Sales_Rep用户需要调整。"),
        must_keep=["RBAC", "Sales_Rep", "read:opportunity(own)",
                   "read:opportunity(all)", "read:report(team)",
                   "Report_Viewer", "128"],
    ),

    # ── 场景 D: RAG 召回知识库文档 ──
    EvalCase(
        id="D01",
        scenario="D-RAG知识库文档",
        name="产品功能说明",
        context="如何配置审批流程",
        text=("审批流程配置指南。系统支持多级审批、会签、或签三种模式。"
              "多级审批：按层级逐级审批，任一环节驳回则流程终止。"
              "会签：所有审批人必须全部通过，适用于金额超过50万的合同。"
              "或签：任一审批人通过即可，适用于日常报销等低风险场景。"
              "配置路径：系统设置 > 流程管理 > 审批流程 > 新建规则。"
              "审批条件支持按金额、部门、客户等级等字段设置分支。"
              "超时处理：默认48小时未处理自动转交上级，可自定义为24/72/168小时。"
              "审批记录保留365天，支持导出为Excel。"
              "注意：修改审批流程需要Admin或FlowAdmin角色权限。"),
        must_keep=["多级审批", "会签", "或签", "50万", "系统设置", "流程管理",
                   "48小时", "365天", "Admin", "FlowAdmin"],
    ),

    EvalCase(
        id="D02",
        scenario="D-RAG知识库文档",
        name="数据备份策略",
        context="备份和恢复",
        text=("数据备份与恢复策略文档 v3.1。备份策略采用3-2-1原则："
              "3份副本、2种介质、1份异地。全量备份每周日凌晨2:00执行，"
              "增量备份每天凌晨3:00执行。备份保留策略：日备份保留7天，"
              "周备份保留4周，月备份保留12个月。核心数据库RPO≤15分钟，"
              "通过binlog实时同步实现。RTO目标：核心系统4小时内恢复，"
              "非核心系统24小时内恢复。恢复测试：每季度进行一次全量恢复演练，"
              "记录恢复时间和数据完整性验证结果。"
              "存储成本：当前月度备份存储费用约¥2.3万，主要为OSS费用。"),
        must_keep=["3-2-1", "周日凌晨2:00", "凌晨3:00", "7天", "4周", "12个月",
                   "RPO", "15分钟", "RTO", "4小时", "24小时", "2.3万"],
    ),

    # ── 场景 E: 用户上传文档（合同/方案）──
    EvalCase(
        id="E01",
        scenario="E-用户上传文档",
        name="SaaS服务合同摘要",
        context="合同核心条款",
        text=("SaaS服务合同关键条款摘要。甲方：某科技有限公司，"
              "乙方：我方平台。合同编号：CT-2024-0892。合同期限：2024年7月1日至2027年6月30日，"
              "共36个月。合同总金额：¥186万（不含税），分三年支付，每年¥62万，"
              "于每年1月15日前支付当年费用。SLA条款：系统可用性≥99.9%，"
              "月度不可用时间超过43分钟则赔偿当月费用的10%。"
              "数据安全：乙方承诺数据不出境，通过等保三级认证。"
              "知识产权：定制开发部分归甲方所有，平台通用功能归乙方。"
              "终止条款：任一方可提前90天书面通知终止，提前终止需支付剩余合同额的30%作为违约金。"
              "争议解决：北京仲裁委员会仲裁。"),
        must_keep=["CT-2024-0892", "2024年7月1日", "2027年6月30日", "36个月",
                   "186万", "62万", "1月15日", "99.9%", "43分钟", "10%",
                   "等保三级", "90天", "30%", "北京仲裁"],
    ),

    EvalCase(
        id="E02",
        scenario="E-用户上传文档",
        name="技术方案书要点",
        context="系统架构方案",
        text=("技术方案概述。本方案采用微服务架构，基于Kubernetes集群部署。"
              "核心服务拆分为12个微服务：用户服务、权限服务、数据服务、"
              "流程引擎、消息服务、文件服务、搜索服务、报表服务、"
              "集成网关、监控服务、日志服务、配置中心。"
              "技术栈：后端Java 17 + Spring Boot 3.2，前端React 18 + TypeScript。"
              "数据库：PostgreSQL 16主库 + Redis 7缓存 + Elasticsearch 8全文搜索。"
              "预计QPS：峰值5000，日均2000。响应时间P99≤200ms。"
              "部署规格：3个master节点(8C32G) + 6个worker节点(16C64G)。"
              "总预算：硬件¥85万/年，软件授权¥12万/年，人力¥240万/年。"),
        must_keep=["Kubernetes", "12个微服务", "Java 17", "Spring Boot 3.2",
                   "React 18", "PostgreSQL 16", "Redis 7", "Elasticsearch 8",
                   "5000", "200ms", "8C32G", "16C64G", "85万", "12万", "240万"],
    ),

    # ── 场景 F: 多轮对话历史 ──
    EvalCase(
        id="F01",
        scenario="F-对话历史压缩",
        name="多轮需求澄清",
        context="用户最终需要什么报表",
        text=("对话历史摘要。用户第一轮说：我想看销售报表。"
              "Agent 追问了报表的时间范围和维度。"
              "用户第二轮回答：看最近三个月的，按区域分。"
              "Agent 确认了是按大区还是省份。"
              "用户第三轮明确：按大区，华东华南华北华中四个大区。"
              "Agent 又问了指标维度。"
              "用户第四轮说：看成交金额和成交笔数，另外加一个同比增长率。"
              "Agent 最终确认需求：时间=最近3个月，维度=4个大区，"
              "指标=成交金额+成交笔数+同比增长率，格式=表格+柱状图。"
              "用户确认：是的，就这样。"),
        must_keep=["三个月", "大区", "华东", "华南", "华北", "华中",
                   "成交金额", "成交笔数", "同比增长率"],
    ),

    EvalCase(
        id="F02",
        scenario="F-对话历史压缩",
        name="问题排查对话",
        context="系统报错问题",
        text=("对话回顾。用户报告登录后看到空白页面。"
              "Agent 请求了浏览器控制台截图。"
              "用户提供截图显示Console有错误：TypeError: Cannot read property 'map' of undefined at Dashboard.jsx:47。"
              "Agent 分析是前端数据为null时未做空值保护。"
              "进一步排查发现后端API /api/v2/dashboard/stats 返回了HTTP 500。"
              "查看后端日志发现是Redis连接超时：RedisConnectionException timeout after 3000ms。"
              "根因是Redis节点在10:23发生了主从切换，客户端缓存了旧的master地址。"
              "修复方案：1.前端加空值保护避免白屏 2.配置Redis Sentinel自动发现 3.重启应用刷新连接池。"
              "用户确认修复后功能恢复正常。"),
        must_keep=["TypeError", "Dashboard.jsx:47", "/api/v2/dashboard/stats",
                   "HTTP 500", "RedisConnectionException", "3000ms",
                   "10:23", "主从切换", "Redis Sentinel"],
    ),

    # ── 场景 G: 数据分析结论 ──
    EvalCase(
        id="G01",
        scenario="G-数据分析结论",
        name="用户行为分析",
        context="用户活跃度分析",
        text=("用户行为分析报告。月活用户(MAU)达到23,456人，较上月增长12%。"
              "日活用户(DAU)平均8,901人，DAU/MAU比值38%表明用户粘性一般。"
              "功能使用TOP5：数据查询(89%)、报表导出(67%)、审批处理(54%)、"
              "客户管理(48%)、流程配置(23%)。平均会话时长18.5分钟，"
              "较上月的15.2分钟增长21.7%。跳出率从35%降至28%。"
              "移动端占比从上月的22%提升至31%，增长显著。"
              "留存率方面：次日留存62%，7日留存45%，30日留存28%。"
              "付费转化率从免费试用到付费为8.5%，平均转化周期14天。"),
        must_keep=["23,456", "12%", "8,901", "38%", "89%", "67%", "54%",
                   "18.5分钟", "28%", "31%", "62%", "45%", "8.5%", "14天"],
    ),

    EvalCase(
        id="G02",
        scenario="G-数据分析结论",
        name="营收分析",
        context="营收趋势",
        text=("营收分析结论。本月总营收¥892万，同比+34%，环比+5%。"
              "其中SaaS订阅收入¥645万占比72.3%，实施服务收入¥158万占比17.7%，"
              "定制开发收入¥89万占比10%。ARR（年度经常性收入）达到¥7,740万，"
              "较年初的¥5,800万增长33.4%。ARPU（每用户平均收入）¥3.8万/年，"
              "较去年的¥3.2万增长18.75%。客户LTV（生命周期价值）预估¥15.2万，"
              "LTV/CAC比值为4.2。净收入留存率(NRR)为118%，表明存量客户持续增购。"
              "最大的增购品类是BI分析模块，贡献了¥120万增量收入。"),
        must_keep=["892万", "34%", "72.3%", "645万", "158万", "89万",
                   "7,740万", "33.4%", "3.8万", "15.2万", "4.2", "118%", "120万"],
    ),

    # ── 场景 H: 错误诊断/故障报告 ──
    EvalCase(
        id="H01",
        scenario="H-错误诊断报告",
        name="生产环境故障",
        context="线上故障原因",
        text=("故障报告 INC-2024-0156。故障发生时间：2024-09-15 14:23 UTC。"
              "影响范围：全部华东区域用户，约3,200家客户受影响。"
              "故障现象：API响应时间从正常的50ms飙升至15秒，大量请求超时。"
              "根因分析：数据库主节点的磁盘IOPS达到上限(16,000 IOPS)，"
              "触发原因是一个未经审批的批量更新SQL修改了150万行记录，"
              "导致大量WAL写入和索引重建。该SQL由运维人员在未走变更流程的情况下直接执行。"
              "修复措施：14:45 kill掉问题SQL，14:52 数据库恢复正常。"
              "总故障时长29分钟。事后改进：1.数据库增加大事务自动kill机制(阈值100万行) "
              "2.生产环境SQL执行必须通过审批平台 3.增加IOPS监控告警(阈值80%)。"),
        must_keep=["INC-2024-0156", "2024-09-15", "14:23", "3,200",
                   "50ms", "15秒", "16,000 IOPS", "150万行",
                   "14:45", "14:52", "29分钟", "100万行", "80%"],
    ),

    EvalCase(
        id="H02",
        scenario="H-错误诊断报告",
        name="内存泄漏分析",
        context="服务内存持续增长",
        text=("内存泄漏分析报告。data-service服务在过去72小时内内存从2.1GB "
              "持续增长至7.8GB，增长率约80MB/小时。通过heap dump分析发现"
              "主要泄漏点在QueryCache类，缓存的PreparedStatement对象未被正确释放。"
              "具体路径：DataService.query() → QueryCache.getOrCreate() → "
              "PreparedStatementPool.borrow()。每次查询分配约1.2KB内存，"
              "但pool.return()在异常路径下被跳过。日均查询量约120万次，"
              "其中约2%走异常路径，即每天泄漏约24,000个Statement对象(约28MB)。"
              "修复：在finally块中确保归还Statement。灰度验证后内存稳定在2.3GB。"
              "建议：增加JVM参数-XX:MaxMetaspaceSize=512m，配置OOM时自动dump。"),
        must_keep=["data-service", "2.1GB", "7.8GB", "80MB/小时",
                   "QueryCache", "PreparedStatement", "1.2KB",
                   "120万次", "2%", "24,000", "28MB", "2.3GB", "512m"],
    ),
]


# ═══════════════════════════════════════════════════════════
# 评估引擎
# ═══════════════════════════════════════════════════════════


class EvalEngine:
    """LightKompress 准确率评估引擎"""

    def __init__(self):
        self.kompressor = LightKompress()

    def evaluate_case(self, case: EvalCase) -> EvalResult:
        """评估单条用例"""
        result = self.kompressor.compress(
            text=case.text,
            context=case.context,
            bias=case.bias,
            target_ratio=case.target_ratio,
        )

        # 检查每个 must_keep 项是否在压缩结果中
        found = 0
        missing = []
        for item in case.must_keep:
            # 支持正则匹配
            if item.startswith("re:"):
                pattern = item[3:]
                if re.search(pattern, result.compressed):
                    found += 1
                else:
                    missing.append(item)
            else:
                # 精确子串匹配
                if item in result.compressed:
                    found += 1
                else:
                    missing.append(item)

        total = len(case.must_keep)
        recall = found / total if total > 0 else 1.0

        return EvalResult(
            case_id=case.id,
            scenario=case.scenario,
            name=case.name,
            passed=recall >= 0.985,  # 98.5% 阈值
            must_keep_total=total,
            must_keep_found=found,
            must_keep_recall=recall,
            missing_items=missing,
            compression_ratio=result.ratio,
            duration_ms=result.duration_ms,
        )

    def run_all(self) -> list[EvalResult]:
        """运行所有评估用例"""
        results = []
        for case in EVAL_CASES:
            result = self.evaluate_case(case)
            results.append(result)
        return results

    def generate_report(self, results: list[EvalResult]) -> dict[str, Any]:
        """生成评估报告"""
        # 总体统计
        total = len(results)
        passed = sum(1 for r in results if r.passed)
        all_recalls = [r.must_keep_recall for r in results]
        avg_recall = sum(all_recalls) / len(all_recalls)
        min_recall = min(all_recalls)
        avg_compression = sum(r.compression_ratio for r in results) / total
        avg_duration = sum(r.duration_ms for r in results) / total

        # 按场景分组
        scenarios: dict[str, list[EvalResult]] = {}
        for r in results:
            scenarios.setdefault(r.scenario, []).append(r)

        scenario_reports = []
        for scenario, s_results in sorted(scenarios.items()):
            s_recalls = [r.must_keep_recall for r in s_results]
            scenario_reports.append(ScenarioReport(
                scenario=scenario,
                total_cases=len(s_results),
                passed_cases=sum(1 for r in s_results if r.passed),
                avg_recall=sum(s_recalls) / len(s_recalls),
                avg_compression=sum(r.compression_ratio for r in s_results) / len(s_results),
                min_recall=min(s_recalls),
                failed_cases=[r.case_id for r in s_results if not r.passed],
            ))

        return {
            "summary": {
                "total_cases": total,
                "passed_cases": passed,
                "pass_rate": passed / total,
                "avg_must_keep_recall": avg_recall,
                "min_must_keep_recall": min_recall,
                "avg_compression_ratio": avg_compression,
                "avg_savings_pct": (1 - avg_compression) * 100,
                "avg_duration_ms": avg_duration,
                "target_recall": 0.985,
                "target_met": avg_recall >= 0.985,
            },
            "scenarios": scenario_reports,
            "failed_details": [r for r in results if not r.passed],
        }


# ═══════════════════════════════════════════════════════════
# 主入口
# ═══════════════════════════════════════════════════════════


def main():
    """运行完整评估"""
    print("=" * 70)
    print("LightKompress 准确率评估")
    print("目标：所有场景 98.5% must-keep recall")
    print("=" * 70)

    engine = EvalEngine()
    results = engine.run_all()
    report = engine.generate_report(results)
    summary = report["summary"]

    # ── 总体结果 ──
    print(f"\n{'━' * 70}")
    print("📊 总体评估结果")
    print(f"{'━' * 70}")
    target_met = "✅ 达标" if summary["target_met"] else "❌ 未达标"
    print(f"  目标 recall ≥ 98.5%:  {target_met}")
    print(f"  总用例数:              {summary['total_cases']}")
    print(f"  通过用例:              {summary['passed_cases']}/{summary['total_cases']}")
    print(f"  通过率:                {summary['pass_rate']*100:.1f}%")
    print(f"  平均 must-keep recall: {summary['avg_must_keep_recall']*100:.2f}%")
    print(f"  最低 must-keep recall: {summary['min_must_keep_recall']*100:.2f}%")
    print(f"  平均压缩节省:          {summary['avg_savings_pct']:.1f}%")
    print(f"  平均耗时:              {summary['avg_duration_ms']:.2f}ms")

    # ── 分场景结果 ──
    print(f"\n{'━' * 70}")
    print("📋 分场景结果")
    print(f"{'━' * 70}")
    print(f"  {'场景':<22} {'用例':<6} {'通过':<6} {'avg recall':<12} {'min recall':<12} {'压缩':<8}")
    print(f"  {'─'*68}")

    for sr in report["scenarios"]:
        status = "✅" if sr.passed_cases == sr.total_cases else "⚠️"
        print(f"  {status} {sr.scenario:<20} {sr.total_cases:<6} "
              f"{sr.passed_cases:<6} {sr.avg_recall*100:.1f}%{'':<7} "
              f"{sr.min_recall*100:.1f}%{'':<7} {(1-sr.avg_compression)*100:.0f}%")

    # ── 失败详情 ──
    failed = report["failed_details"]
    if failed:
        print(f"\n{'━' * 70}")
        print(f"❌ 失败用例详情 ({len(failed)} 个)")
        print(f"{'━' * 70}")
        for r in failed:
            print(f"\n  [{r.case_id}] {r.name}")
            print(f"    recall: {r.must_keep_recall*100:.1f}% "
                  f"({r.must_keep_found}/{r.must_keep_total})")
            print(f"    缺失项: {r.missing_items}")
    else:
        print(f"\n  🎉 所有用例全部通过！")

    # ── 逐用例详细结果 ──
    print(f"\n{'━' * 70}")
    print("📝 逐用例详细结果")
    print(f"{'━' * 70}")
    print(f"  {'ID':<5} {'名称':<20} {'recall':<10} {'保留':<12} {'压缩':<8} {'耗时':<8} {'状态'}")
    print(f"  {'─'*75}")
    for r in results:
        status = "✅" if r.passed else "❌"
        print(f"  {r.case_id:<5} {r.name:<20} "
              f"{r.must_keep_recall*100:.1f}%{'':<5} "
              f"{r.must_keep_found}/{r.must_keep_total}{'':<8} "
              f"{(1-r.compression_ratio)*100:.0f}%{'':<5} "
              f"{r.duration_ms:.1f}ms{'':<3} {status}")

    # ── 结论 ──
    print(f"\n{'═' * 70}")
    if summary["target_met"]:
        print("✅ 结论：LightKompress 达到 98.5% must-keep recall 目标")
        print(f"   可替代 BERT Kompress 用于生产环境")
    else:
        gap = 0.985 - summary["avg_must_keep_recall"]
        print(f"⚠️  结论：当前 recall {summary['avg_must_keep_recall']*100:.2f}%，"
              f"距离目标还差 {gap*100:.2f}%")
        print("   需要优化评分策略或调整 target_ratio/bias 参数")
    print(f"{'═' * 70}")

    return report


if __name__ == "__main__":
    main()
