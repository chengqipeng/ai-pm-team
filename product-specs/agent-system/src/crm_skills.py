"""
CRM 业务技能定义 — 完整的 Skill prompt

每个 Skill 对应一个业务 SOP，指导 LLM 如何编排多次 Tool 调用完成复杂任务。
inline 模式: prompt 注入当前对话，LLM 按 SOP 继续调用 Tool
fork 模式: 创建独立子 Agent 执行
"""
from __future__ import annotations

from .skills import SkillDefinition, SkillRegistry, SkillExecutor, SkillsTool
from .subagent_config import SubagentConfig, SubagentRegistry


# ═══════════════════════════════════════════════════════════
# inline 技能（注入当前对话，LLM 按 SOP 继续执行）
# ═══════════════════════════════════════════════════════════

VERIFY_CONFIG = SkillDefinition(
    name="verify_config",
    description="校验业务对象的元数据配置是否正确、完整、一致",
    when_to_use="校验|检查配置|配置审查|元数据校验",
    arguments=["entity"],
    allowed_tools=["query_schema", "query_data"],
    context="inline",
    prompt="""你现在需要校验 {entity} 业务对象的元数据配置。请严格按以下步骤执行：

## 步骤 1: 查询字段定义
调用 query_schema(query_type="entity_items", entity_api_key="{entity}") 获取全部字段列表。

## 步骤 2: 逐项校验
对每个字段检查：
- api_key 是否符合 camelCase 规范
- item_type 是否合理（VARCHAR/INTEGER/DECIMAL/DATE/RELATIONSHIP/PICK_LIST）
- 必填字段（required=True）是否合理
- PICK_LIST 类型是否有 options 定义

## 步骤 3: 查询关联关系
调用 query_schema(query_type="entity_links", entity_api_key="{entity}") 检查关联配置。

## 步骤 4: 输出校验报告
按以下格式输出：
- 🟢 PASS: 通过的检查项
- 🟡 WARNING: 建议改进的项
- 🔴 ERROR: 必须修复的问题
最后给出 VERDICT: PASS 或 FAIL""",
)

DIAGNOSE = SkillDefinition(
    name="diagnose",
    description="系统化诊断业务数据异常或配置问题，找出根本原因",
    when_to_use="诊断|排查|问题|异常|为什么",
    arguments=["problem"],
    allowed_tools=["query_schema", "query_data", "analyze_data"],
    context="inline",
    prompt="""你现在需要诊断以下问题: {problem}

请严格按以下诊断协议执行：

## 阶段 1: 定位问题
- 明确问题涉及哪个业务对象（account/opportunity/contact/activity/lead）
- 使用 query_schema 查询相关实体的元数据定义

## 阶段 2: 数据层排查
- 使用 query_data 查询相关业务数据
- 检查数据是否符合元数据定义的约束
- 检查关联数据的一致性

## 阶段 3: 统计分析
- 使用 analyze_data 进行聚合统计，发现异常模式
- 对比不同维度的数据分布

## 阶段 4: 给出诊断结论
- 根本原因（不是表面症状）
- 影响范围
- 修复建议""",
)

CUSTOMER_360 = SkillDefinition(
    name="customer_360",
    description="生成客户 360 度全景视图，包含基本信息、商机、联系人、活动",
    when_to_use="客户详情|360|全景|完整信息",
    arguments=["account_id"],
    allowed_tools=["query_data"],
    context="inline",
    prompt="""你现在需要生成客户 {account_id} 的 360 度全景视图。请依次执行：

## 步骤 1: 查询客户基本信息
调用 query_data(action="get", entity_api_key="account", record_id="{account_id}")

## 步骤 2: 查询关联商机
调用 query_data(action="query", entity_api_key="opportunity", filters={{"accountId": "{account_id}"}})

## 步骤 3: 查询关联联系人
调用 query_data(action="query", entity_api_key="contact", filters={{"accountId": "{account_id}"}})

## 步骤 4: 查询最近活动
调用 query_data(action="query", entity_api_key="activity", filters={{"accountId": "{account_id}"}})

## 步骤 5: 汇总输出
按以下结构输出 360 视图：
- **基本信息**: 公司名/行业/城市/规模/营收/评分
- **商机概览**: 数量/总金额/各阶段分布/最近活动
- **关键联系人**: 姓名/职位/是否主要联系人
- **最近活动**: 类型/主题/状态
- **建议**: 基于数据给出跟进建议""",
)


# ═══════════════════════════════════════════════════════════
# fork 技能（创建独立子 Agent 执行）
# ═══════════════════════════════════════════════════════════

PIPELINE_ANALYSIS = SkillDefinition(
    name="pipeline_analysis",
    description="深度分析商机 Pipeline，按阶段统计金额和数量，识别瓶颈和风险",
    when_to_use="pipeline|管道分析|商机统计|阶段分析",
    arguments=["filters"],
    allowed_tools=["query_data", "analyze_data"],
    context="fork",
    prompt="""你是 Pipeline 分析专家。请对商机数据进行深度分析。

## 分析任务
过滤条件: {filters}

## 执行步骤
1. 使用 analyze_data 按 stage 分组统计商机数量和金额总和
2. 使用 analyze_data 计算整体平均赢单概率
3. 使用 query_data 查询所有商机的详细信息（name, stage, amount, probability, closeDate）

## 输出要求
- 各阶段商机数量和金额
- 总金额和加权金额（金额×概率）
- 识别瓶颈阶段（转化率低的阶段）
- 识别风险商机（概率低但金额大的）
- 给出 3 条具体的行动建议""",
)

DATA_ANALYSIS = SkillDefinition(
    name="data_analysis",
    description="对指定业务对象进行多维度数据分析，生成分析报告",
    when_to_use="数据分析|统计报告|趋势分析|多维分析",
    arguments=["entity", "dimensions"],
    allowed_tools=["query_schema", "query_data", "analyze_data"],
    context="fork",
    agent="data_analyst",  # 指定子 Agent 配置
    prompt="""你是数据分析专家。请对 {entity} 进行多维度分析。

分析维度: {dimensions}

## 执行步骤
1. 使用 query_schema 了解 {entity} 的字段结构
2. 使用 analyze_data 按各维度进行聚合统计
3. 使用 query_data 获取明细数据验证统计结果

## 输出要求
- 各维度的统计数据（数量、金额、平均值）
- 数据分布特征
- 异常值识别
- 趋势判断
- 行动建议""",
)

BATCH_CLEANUP = SkillDefinition(
    name="batch_cleanup",
    description="批量清理过期或无效的业务数据，需要用户确认",
    when_to_use="批量清理|批量删除|清理过期|数据清洗",
    arguments=["entity", "condition"],
    allowed_tools=["query_data", "modify_data", "ask_user"],
    context="fork",
    prompt="""你是数据清理专家。请执行以下批量清理任务。

## 清理目标
实体: {entity}
条件: {condition}

## 执行步骤
1. 使用 query_data(action="count") 统计符合条件的记录数
2. 使用 query_data(action="query") 查看前 5 条样本数据
3. 使用 ask_user 向用户确认是否继续删除
4. 确认后使用 modify_data(action="delete") 执行删除
5. 再次使用 query_data(action="count") 验证删除结果

## 安全规则
- 删除前必须先统计和展示样本
- 必须获得用户确认才能执行删除
- 删除后必须验证结果""",
)


# ═══════════════════════════════════════════════════════════
# 子 Agent 配置（fork 模式指定 agent 时使用）
# ═══════════════════════════════════════════════════════════

DATA_ANALYST_CONFIG = SubagentConfig(
    name="data_analyst",
    description="数据分析专家子 Agent",
    system_prompt="""你是一位专业的 CRM 数据分析师。你的职责是：
1. 理解业务对象的数据结构
2. 使用聚合工具进行多维度统计分析
3. 从数据中发现规律和异常
4. 生成结构化的分析报告

工作规范：
- 必须使用工具获取真实数据，禁止编造
- 分析结果必须包含具体数字
- 用中文输出，保留原始数据精度""",
    tool_names=["query_schema", "query_data", "analyze_data"],
    max_llm_calls=15,
    max_step_llm_calls=8,
)


# ═══════════════════════════════════════════════════════════
# 注册函数
# ═══════════════════════════════════════════════════════════

def register_crm_skills(skill_registry: SkillRegistry) -> None:
    """注册全部 CRM 业务技能"""
    # inline 技能
    skill_registry.register(VERIFY_CONFIG)
    skill_registry.register(DIAGNOSE)
    skill_registry.register(CUSTOMER_360)
    # fork 技能
    skill_registry.register(PIPELINE_ANALYSIS)
    skill_registry.register(DATA_ANALYSIS)
    skill_registry.register(BATCH_CLEANUP)


def register_crm_subagents(subagent_registry: SubagentRegistry) -> None:
    """注册 CRM 子 Agent 配置"""
    subagent_registry.register(DATA_ANALYST_CONFIG)
