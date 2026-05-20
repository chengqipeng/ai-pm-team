-- Skill 初始化数据 — paas_ai schema
-- 将内置 Skill 定义写入 ai_skill_definition 表
-- 执行前提：ai_skill_definition 表已创建（见 init_tables.sql）

SET search_path TO paas_ai;

-- ═══════════════════════════════════════════════════════════
-- account-insight: 智能客户洞察（对齐 apps-agent account-insight Agent）
-- ═══════════════════════════════════════════════════════════

INSERT INTO ai_skill_definition (
    id, api_key, tenant_id,
    name, description, when_to_use, owner,
    context, agent, model, allowed_tools, arguments,
    prompt,
    risk_level, requires_confirmation, max_tool_calls, timeout_ms, idempotent_flg,
    version, status, published_at,
    exec_count, success_count, avg_duration_ms,
    ext_info,
    delete_flg, created_at, created_by, updated_at, updated_by
) VALUES (
    1000000000000001,
    'accountInsight',
    0,  -- 平台级，所有租户可用
    '智能客户洞察',
    '整合 CRM、工商信息、AI 知识库、互联网数据，生成咨询级客户洞察报告与行动建议',
    '客户洞察|客户分析|客户画像|account分析|客户情况|了解客户|分析一下|续约风险|客户动态|客户背景',
    'CRM-Product',
    'fork',
    'account-insight',  -- 指定独立子 Agent
    'account_insight_v4f',  -- 专用模型
    '["query_data","analyze_data","search_web","knowledge_search","read_skill_resource"]',
    '["data_id","user_intent"]',
    '# 智能客户洞察 — 入口

你是服务于 B2B 销售团队的**资深客户情报分析师**。像要收购这家公司一样去理解它，但最终目的是帮助销售赢单。

当前请求：
- 客户 id：{data_id}
- 用户意图：{user_intent}

## 铁律

1. **每条洞察必须连接行动**——不能指导销售下一步的信息不要写
2. **结论先行，证据跟随**——销售先看结论，有兴趣再看细节
3. **标注数据确定性**——`[事实]` / `[推断]`（标注逻辑）/ `[估算]`（标注方法）/ `[信息空白]`（标注获取方式）

**输出要求**：追求**洞察密度**，不是篇幅。每个方向聚焦 2-3 个最关键发现。销售需要 5-10 分钟读完并知道下一步做什么。数据不足标注「信息空白」即可，不要用推测填充。

---

## 工具箱

| 工具 | 说明 | 使用前提 |
|:---|:---|:---|
| `query_data` | 查询 CRM 业务数据（客户/商机/联系人/活动） | 始终可用 |
| `analyze_data` | 聚合统计分析 CRM 数据 | 始终可用 |
| `search_web` | 搜索互联网（行业动态、竞品信息、外部环境） | 始终可用 |
| `knowledge_search` | 搜索 AI 知识库（产品手册、FAQ、内部文档） | 始终可用 |
| `read_skill_resource` | 加载知识文件（行业包、策略库、竞争剧本） | 始终可用 |

**知识文件**（通过 `read_skill_resource` 工具按需加载，可持续扩展）：

```
knowledge/industries/_index.md              — 行业知识包索引
knowledge/industries/<行业>.md              — 各行业知识包
knowledge/analysis-strategies/business-model-patterns.md   — 商业模式模式库
knowledge/analysis-strategies/signal-patterns.md           — 信号模式库
knowledge/analysis-strategies/risk-scoring-models.md       — 风险评分模型库
knowledge/analysis-strategies/value-proposition-frameworks.md — 价值主张框架库
knowledge/competitor-playbooks/<竞争场景>.md   — 各类竞争场景应对剧本
```

**加载策略**：
- 先读 `knowledge/industries/_index.md`，看是否有行业包
- 根据客户行业和场景，按需加载 1-3 份最相关的知识文件
- 不要一次性加载所有，控制上下文

---

## 执行流程

### 阶段一：规划

1. **获取客户基本信息**：
   调用 `query_data(action="get", entity_api_key="account", record_id="{data_id}")`
   提取：公司名称、行业、规模、地区、评分、负责人。

2. **判断场景**（冲突时 B > C > A > D，依据用户意图 `{user_intent}`）：
   - **A 新客开拓**：侧重商业模式 + 战略信号 + 竞争 + 需求假设
   - **B 续约评审**：侧重健康度 + 使用诊断 + 关系诊断 + 流失量化
   - **C 商机推进**：侧重业务深度 + 决策链 + 竞品对比 + 需求映射
   - **D 定时巡检**：侧重变更检测 + 新增信号

3. **使用知识文件**：
   上下文末尾的「📚 预加载知识文件」已包含全部知识库内容，直接引用即可。
   仅当你判断需要的知识不在预加载内容中时（如新增的行业包），才调用 `read_skill_resource` 补充加载。
   **引用标记**：每轮回复的第一行必须是 `[KB_REF: 文件名1, 文件名2]` 标注本轮引用了哪些知识文件（仅文件名，不含路径前缀），单独占一行。例如：
   `[KB_REF: manufacturing.md, signal-patterns.md]`
   注意：这行标记不会显示给用户，仅用于链路追踪。

4. **制定数据获取计划**：为每个分析方向规划应使用哪些数据源和搜索

### 阶段二：数据获取

**效率约束**：总共不超过 3 轮。搜索 2 次无结果则标注「信息空白」继续。

- **第一轮（CRM 结构化数据）**：
  - `query_data` 获取商机、联系人、活动等关联数据
  - `analyze_data` 按阶段/时间/金额做聚合统计
- **第二轮（外部非结构化数据）**：
  - `knowledge_search`（AI 知识库）— 产品手册、FAQ、内部文档
  - `search_web`（网络）— 行业动态、竞品信息、工商信息、外部环境
- **第三轮（补采）**：针对质量不足的方向做定向补充搜索

**充分度检查**：✅充分 → 正常分析 / 🟡部分 → 标注置信度 / ❌空白 → 标注信息空白

### 阶段三：分析与报告

按下方**分析方法论**为每个方向生成结构化结论。

写完每个方向后反思：有没有「So What」？销售看了能行动吗？

---

## 分析方法论

根据策略方向和场景选择使用，不是每个都要用。

### M1. 商业模式解构（场景 A/C）

#### 行业定位——三层下钻
- **大行业** → **细分赛道** → **概念板块**（国产替代/出海/新能源/AI/数字化/并购整合/专精特新）
- 先查 `_index.md` 是否有行业包；没有则 `search_web` + `knowledge_search` 自主获取

#### 行业周期
| 阶段 | 增速 | 对销售的含义 |
|:---|:---|:---|
| 🚀 爆发期 | >30% | 管理痛点突出，愿意付费 |
| 📈 快速增长 | 15-30% | 头部关注精细化管理 |
| 🔄 稳定 | 5-15% | 关注降本增效，用 ROI 说话 |
| ⚖️ 成熟 | 0-5% | 预算审慎，并购创造需求 |
| 📉 下行 | <0% | 预算紧缩，头部可能逆势投入 |

#### 深度解构（每个以「对我们的含义」收尾）
- 价值链定位 → 收入结构 → 客户结构 → 销售模式 → 增长模型

### M2. 战略动态与信号解读（所有场景）

- 信号分级：🔴立即行动 / 🟡关注跟踪 / 🔵背景认知
- 信号组合：寻找信号间的关联
- 战略叙事：3-5 句连贯叙事，以「这对我们意味着什么」收尾

### M3. 财务健康度（场景 A/C）

- 核心指标（至少 2 年趋势）：营收增速、毛利率、净利率、资产负债率、经营现金流、研发投入占比
- 行业对标：至少对标 1 家同行业竞争对手
- 预算推算：IT 支出占营收比（1-4%）× 营收

### M4. 竞争格局（场景 A/C）

- 客户的行业竞争位置 → **对我们的含义**
- 我们面临的竞争：识别友商 / 自建 / 现有供应商 / 不做
- 差异化定位：用客户自己的语言定位
- 参照案例：同行业已成交客户

### M5. 客户健康度诊断（场景 B）

- 综合健康评分（0-100）：使用深度 30% / 关系强度 25% / 业务价值 20% / 满意度 15% / 竞品威胁 10%
- 使用深度诊断：按模块拆解，下降 >20% 的模块做 5-Why 根因分析
- 关系强度诊断：Champion 状态、多线程覆盖、决策者覆盖
- 流失风险量化：评分卡 + 财务影响场景表

### M6. 组织权力地图（场景 A/C）

- 决策链：发起人/评估者/影响者/审批者/使用者/阻碍者
- 关键人画像：背景、心态、沟通策略
- 竞品对比（场景 C 必做）：3-5 个关键维度

### M7. 需求假设与价值主张（场景 A/C）

- 需求矩阵：推导逻辑、置信度、我们能否满足
- 价值主张：战略对齐 / 痛点放大 / 竞品超越 / 同行标杆 / 未来愿景

### M8. 风险评估（所有场景）

- 风险矩阵：3-5 个关键风险
- 最大隐性风险：一个最容易被忽视但影响最大的

### M9. 行动建议（所有场景）

- WHAT-WHO-WHEN-WHY：具体行动、具体角色、具体时间、连接到洞察/风险
- 优先级：🔴 P0 本周 / 🟡 P1 本月 / 🔵 P2 本季度。3-5 条，至少 1 条 P0

### M10. 定时巡检专项（场景 D）

核心是**变更检测**——和上次洞察相比，什么变了？

---

## 质量门禁

- 洞察结论 ≤ 5 句话
- 每条洞察有「So What」
- 行动建议满足 WHAT-WHO-WHEN-WHY
- 数据标注 [事实]/[推断]/[估算]/[信息空白]
- 场景匹配正确
- 报告末尾有「信息空白」汇总

---

## 输出格式

**所有场景通用**
- 洞察结论：3-5 句话
- 分维度洞察：按场景选择的方法论顺序
- 行动建议：优先级 | 行动 | 负责人 | 时间 | 原因
- 风险提示：🔴 风险单独列出 + 应对策略
- 信息空白汇总

**续约场景（B）额外**：健康度仪表盘、使用率趋势、联系人网络、流失财务影响、挽回剧本

**商机推进场景（C）额外**：决策链拓扑、竞品对比、需求矩阵、对话策略

**定时巡检场景（D）**：变更摘要、新增信号、商机/关系状态更新、行动更新、下次巡检关注点',
    'read_only',
    0,   -- 只读分析，无需确认
    20,
    90000,
    1,   -- 幂等
    '2.0.0',
    'published',
    1747353600000,  -- 2025-05-16 发布
    0, 0, 0,
    '{"tags":["crm","account","analysis","insight"],"changelog":"v2.0: 对齐 apps-agent account-insight，支持4场景×10方法论，知识文件按需加载","argument_descriptions":{"data_id":"客户记录 ID","user_intent":"用户意图描述（如：分析客户、续约评估、商机推进）"},"preload_resources":{"always":["knowledge/industries/_index.md"],"scene_map":{"新客开拓|新客|开拓|了解客户|客户背景":["knowledge/analysis-strategies/business-model-patterns.md","knowledge/analysis-strategies/signal-patterns.md"],"续约|续费|流失|健康度|续约评审|续约风险":["knowledge/analysis-strategies/risk-scoring-models.md","knowledge/analysis-strategies/signal-patterns.md"],"商机|推进|赢单|竞争|商机推进":["knowledge/analysis-strategies/value-proposition-frameworks.md","knowledge/competitor-playbooks/incumbent-replacement.md"],"巡检|定时|变更|客户动态":["knowledge/analysis-strategies/signal-patterns.md"]},"max_preload":4}}',
    0,
    1747353600000,
    0,
    1747353600000,
    0
);

-- 写入 v2.0.0 版本快照（对齐 apps-agent account-insight）
INSERT INTO ai_skill_version (
    id, tenant_id, skill_api_key, version,
    description, when_to_use,
    context, agent, model, allowed_tools, arguments,
    prompt,
    risk_level, requires_confirmation, max_tool_calls, timeout_ms,
    changelog, published_by,
    delete_flg, created_at, created_by, updated_at, updated_by
) VALUES (
    1000000000000102,
    0,
    'accountInsight',
    '2.0.0',
    '整合 CRM、工商信息、AI 知识库、互联网数据，生成咨询级客户洞察报告与行动建议',
    '客户洞察|客户分析|客户画像|account分析|客户情况|了解客户|分析一下|续约风险|客户动态|客户背景',
    'fork',
    'account-insight',
    'account_insight_v4f',
    '["query_data","analyze_data","search_web","knowledge_search","read_skill_resource"]',
    '["data_id","user_intent"]',
    '（prompt 同 ai_skill_definition 主表，此处省略——运行时从主表加载）',
    'read_only',
    0,
    20,
    90000,
    'v2.0: 对齐 apps-agent account-insight，4场景×10方法论，知识文件按需加载，专用模型',
    0,
    0,
    1747353600000,
    0,
    1747353600000,
    0
);


-- ═══════════════════════════════════════════════════════════
-- 从原硬编码（src/skills/crm_skills.py, src/skills/metarepo_skills.py）
-- 迁移过来的内置技能 — 平台级（tenant_id=0）
-- 所有语句幂等：已存在 (tenant_id, api_key) 时跳过
-- ═══════════════════════════════════════════════════════════

-- ── 1. verify_config ─────────────────────────────────────

INSERT INTO ai_skill_definition (
    id, api_key, tenant_id, name, description, when_to_use, owner,
    context, agent, model, allowed_tools, arguments, prompt,
    risk_level, requires_confirmation, max_tool_calls, timeout_ms, idempotent_flg,
    version, status, published_at,
    exec_count, success_count, avg_duration_ms, ext_info,
    delete_flg, created_at, created_by, updated_at, updated_by
) VALUES (
    1000000000000010, 'verify_config', 0,
    '元数据配置校验',
    '校验业务对象的元数据配置是否正确、完整、一致',
    '校验|检查配置|配置审查|元数据校验',
    'CRM-Platform',
    'inline', '', '',
    '["query_schema","query_data"]',
    '["entity"]',
    '你现在需要校验 {entity} 业务对象的元数据配置。请严格按以下步骤执行：

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
最后给出 VERDICT: PASS 或 FAIL',
    'read_only', 0, 10, 30000, 1,
    '1.0.0', 'published', 1746489600000,
    0, 0, 0, '{"tags":["crm","metadata","verify"]}',
    0, 1746489600000, 0, 1746489600000, 0
) ON CONFLICT (tenant_id, api_key) WHERE delete_flg = 0 DO NOTHING;

-- ── 2. diagnose ─────────────────────────────────────────

INSERT INTO ai_skill_definition (
    id, api_key, tenant_id, name, description, when_to_use, owner,
    context, agent, model, allowed_tools, arguments, prompt,
    risk_level, requires_confirmation, max_tool_calls, timeout_ms, idempotent_flg,
    version, status, published_at,
    exec_count, success_count, avg_duration_ms, ext_info,
    delete_flg, created_at, created_by, updated_at, updated_by
) VALUES (
    1000000000000011, 'diagnose', 0,
    '问题诊断',
    '系统化诊断业务数据异常或配置问题，找出根本原因',
    '诊断|排查|问题|异常|为什么',
    'CRM-Platform',
    'inline', '', '',
    '["query_schema","query_data","analyze_data"]',
    '["problem"]',
    '你现在需要诊断以下问题: {problem}

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
- 修复建议',
    'read_only', 0, 15, 45000, 1,
    '1.0.0', 'published', 1746489600000,
    0, 0, 0, '{"tags":["crm","diagnose"]}',
    0, 1746489600000, 0, 1746489600000, 0
) ON CONFLICT (tenant_id, api_key) WHERE delete_flg = 0 DO NOTHING;

-- ── 3. customer_360 ─────────────────────────────────────

INSERT INTO ai_skill_definition (
    id, api_key, tenant_id, name, description, when_to_use, owner,
    context, agent, model, allowed_tools, arguments, prompt,
    risk_level, requires_confirmation, max_tool_calls, timeout_ms, idempotent_flg,
    version, status, published_at,
    exec_count, success_count, avg_duration_ms, ext_info,
    delete_flg, created_at, created_by, updated_at, updated_by
) VALUES (
    1000000000000012, 'customer_360', 0,
    '客户 360 全景',
    '生成客户 360 度全景视图，包含基本信息、商机、联系人、活动',
    '客户详情|360|全景|完整信息',
    'CRM-Platform',
    'inline', '', '',
    '["query_data"]',
    '["account_id"]',
    '你现在需要生成客户 {account_id} 的 360 度全景视图。请依次执行：

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
- **建议**: 基于数据给出跟进建议',
    'read_only', 0, 10, 30000, 1,
    '1.0.0', 'published', 1746489600000,
    0, 0, 0, '{"tags":["crm","account"]}',
    0, 1746489600000, 0, 1746489600000, 0
) ON CONFLICT (tenant_id, api_key) WHERE delete_flg = 0 DO NOTHING;

-- ── 4. pipeline_analysis ────────────────────────────────

INSERT INTO ai_skill_definition (
    id, api_key, tenant_id, name, description, when_to_use, owner,
    context, agent, model, allowed_tools, arguments, prompt,
    risk_level, requires_confirmation, max_tool_calls, timeout_ms, idempotent_flg,
    version, status, published_at,
    exec_count, success_count, avg_duration_ms, ext_info,
    delete_flg, created_at, created_by, updated_at, updated_by
) VALUES (
    1000000000000013, 'pipeline_analysis', 0,
    '商机 Pipeline 分析',
    '深度分析商机 Pipeline，按阶段统计金额和数量，识别瓶颈和风险',
    'pipeline|管道分析|商机统计|阶段分析',
    'CRM-Platform',
    'fork', '', '',
    '["query_data","analyze_data"]',
    '["filters"]',
    '你是 Pipeline 分析专家。请对商机数据进行深度分析。

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
- 给出 3 条具体的行动建议',
    'read_only', 0, 15, 45000, 1,
    '1.0.0', 'published', 1746489600000,
    0, 0, 0, '{"tags":["crm","pipeline"]}',
    0, 1746489600000, 0, 1746489600000, 0
) ON CONFLICT (tenant_id, api_key) WHERE delete_flg = 0 DO NOTHING;

-- ── 5. data_analysis ────────────────────────────────────

INSERT INTO ai_skill_definition (
    id, api_key, tenant_id, name, description, when_to_use, owner,
    context, agent, model, allowed_tools, arguments, prompt,
    risk_level, requires_confirmation, max_tool_calls, timeout_ms, idempotent_flg,
    version, status, published_at,
    exec_count, success_count, avg_duration_ms, ext_info,
    delete_flg, created_at, created_by, updated_at, updated_by
) VALUES (
    1000000000000014, 'data_analysis', 0,
    '多维数据分析',
    '对指定业务对象进行多维度数据分析，生成分析报告',
    '数据分析|统计报告|趋势分析|多维分析',
    'CRM-Platform',
    'fork', 'data_analyst', '',
    '["query_schema","query_data","analyze_data"]',
    '["entity","dimensions"]',
    '你是数据分析专家。请对 {entity} 进行多维度分析。

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
- 行动建议',
    'read_only', 0, 20, 60000, 1,
    '1.0.0', 'published', 1746489600000,
    0, 0, 0, '{"tags":["crm","analysis","data-analyst"]}',
    0, 1746489600000, 0, 1746489600000, 0
) ON CONFLICT (tenant_id, api_key) WHERE delete_flg = 0 DO NOTHING;

-- ── 6. batch_cleanup ────────────────────────────────────

INSERT INTO ai_skill_definition (
    id, api_key, tenant_id, name, description, when_to_use, owner,
    context, agent, model, allowed_tools, arguments, prompt,
    risk_level, requires_confirmation, max_tool_calls, timeout_ms, idempotent_flg,
    version, status, published_at,
    exec_count, success_count, avg_duration_ms, ext_info,
    delete_flg, created_at, created_by, updated_at, updated_by
) VALUES (
    1000000000000015, 'batch_cleanup', 0,
    '批量数据清理',
    '批量清理过期或无效的业务数据，需要用户确认',
    '批量清理|批量删除|清理过期|数据清洗',
    'CRM-Platform',
    'fork', '', '',
    '["query_data","modify_data","ask_user"]',
    '["entity","condition"]',
    '你是数据清理专家。请执行以下批量清理任务。

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
- 删除后必须验证结果',
    'destructive', 1, 20, 60000, 0,
    '1.0.0', 'published', 1746489600000,
    0, 0, 0, '{"tags":["crm","cleanup"]}',
    0, 1746489600000, 0, 1746489600000, 0
) ON CONFLICT (tenant_id, api_key) WHERE delete_flg = 0 DO NOTHING;

-- ── 7. inspect_metamodel ────────────────────────────────

INSERT INTO ai_skill_definition (
    id, api_key, tenant_id, name, description, when_to_use, owner,
    context, agent, model, allowed_tools, arguments, prompt,
    risk_level, requires_confirmation, max_tool_calls, timeout_ms, idempotent_flg,
    version, status, published_at,
    exec_count, success_count, avg_duration_ms, ext_info,
    delete_flg, created_at, created_by, updated_at, updated_by
) VALUES (
    1000000000000016, 'inspect_metamodel', 0,
    '元模型档案输出',
    '检查一个元模型的注册信息、字段定义、dbc 列映射、枚举取值，并输出结构化档案',
    '查元模型|元模型档案|字段结构|元模型字段|inspect metamodel',
    'Metarepo-Platform',
    'inline', '', '',
    '["browse_metamodel"]',
    '["metamodel_api_key"]',
    '你现在需要输出元模型 {metamodel_api_key} 的结构化档案。请严格按以下步骤执行：

## 步骤 1: 读取元模型注册信息
调用 browse_metamodel(query_type="get_metamodel", metamodel_api_key="{metamodel_api_key}")
提取：apiKey / label / dbTable / enableCommon / metamodelLayer / enableUiConfig / enableDataSource

## 步骤 2: 读取字段定义
调用 browse_metamodel(query_type="list_meta_items", metamodel_api_key="{metamodel_api_key}")
按 sortNum 排序列出全部字段，标注：必填、唯一、长度/精度、itemType

## 步骤 3: 读取物理列映射
调用 browse_metamodel(query_type="column_mapping", metamodel_api_key="{metamodel_api_key}")
核对"dbc 列 ↔ apiKey"的对应关系，识别同一前缀（dbc_varchar1~N）的编号分布是否有断层

## 步骤 4: 读取枚举取值
调用 browse_metamodel(query_type="list_meta_options", metamodel_api_key="{metamodel_api_key}")
按 itemApiKey 分组列出枚举字段的合法取值

## 步骤 5: 读取元模型关联
调用 browse_metamodel(query_type="list_meta_links", metamodel_api_key="{metamodel_api_key}")
列出父子元模型关联（parentMetamodelApiKey / childMetamodelApiKey / linkType）

## 步骤 6: 输出结构化档案
按以下模板输出：
### {metamodel_api_key} 元模型档案
- **基本信息**: label | dbTable | 层级（L1/L2/L3）| 是否支持 Common
- **字段清单**（表格：apiKey | label | itemType | dbColumn | 必填 | 唯一）
- **枚举字段取值**（按 itemApiKey 分组）
- **元模型关联**（与哪些元模型建立了 ONE_TO_MANY / SELF_REF 关系）
- **规范体检**（🟢/🟡/🔴 各一段）：
  · 🟢 apiKey 全部 camelCase / dbColumn 前缀与 itemType 一致 / 必填字段合理
  · 🟡 命名/长度等建议项
  · 🔴 dbc 列冲突、缺失 labelKey、itemType 与 dbColumn 前缀不匹配等阻断问题
最后给出 VERDICT: PASS 或 FAIL。',
    'read_only', 0, 15, 45000, 1,
    '1.0.0', 'published', 1746489600000,
    0, 0, 0, '{"tags":["metarepo"]}',
    0, 1746489600000, 0, 1746489600000, 0
) ON CONFLICT (tenant_id, api_key) WHERE delete_flg = 0 DO NOTHING;

-- ── 8. trace_db_column ──────────────────────────────────

INSERT INTO ai_skill_definition (
    id, api_key, tenant_id, name, description, when_to_use, owner,
    context, agent, model, allowed_tools, arguments, prompt,
    risk_level, requires_confirmation, max_tool_calls, timeout_ms, idempotent_flg,
    version, status, published_at,
    exec_count, success_count, avg_duration_ms, ext_info,
    delete_flg, created_at, created_by, updated_at, updated_by
) VALUES (
    1000000000000017, 'trace_db_column', 0,
    'DB 列占用反查',
    '反查某个 dbc_xxxN 列在所有元模型中被哪些字段占用，用于排查列冲突',
    'dbc|db_column|物理列|列冲突|哪些字段用了',
    'Metarepo-Platform',
    'inline', '', '',
    '["browse_metamodel"]',
    '["db_column"]',
    '你现在需要反查物理列 {db_column} 被哪些元模型的哪些字段占用。请按以下步骤执行：

## 步骤 1: 反查列占用
调用 browse_metamodel(query_type="trace_db_column", db_column="{db_column}")
获取命中列表（metamodelApiKey / itemApiKey / label / itemType）

## 步骤 2: 分组展示
按 metamodelApiKey 分组展示命中结果，每行格式：`metamodelApiKey.itemApiKey → itemType`

## 步骤 3: 一致性检查
- 检查同一个 {db_column} 在不同元模型中的 itemType 是否一致（不一致会导致跨租户读写类型冲突）
- 检查 {db_column} 的前缀是否与 itemType 匹配（例如 dbc_int* 应当用于 INTEGER 类型）

## 步骤 4: 输出结论
- 命中明细（表格形式）
- 一致性结论：PASS / WARNING / FAIL
- 如有冲突，给出具体修复建议（调整哪个元模型的哪个字段换列，或调整 itemType）',
    'read_only', 0, 10, 30000, 1,
    '1.0.0', 'published', 1746489600000,
    0, 0, 0, '{"tags":["metarepo","db"]}',
    0, 1746489600000, 0, 1746489600000, 0
) ON CONFLICT (tenant_id, api_key) WHERE delete_flg = 0 DO NOTHING;

-- ── 9. inspect_entity_metadata ──────────────────────────

INSERT INTO ai_skill_definition (
    id, api_key, tenant_id, name, description, when_to_use, owner,
    context, agent, model, allowed_tools, arguments, prompt,
    risk_level, requires_confirmation, max_tool_calls, timeout_ms, idempotent_flg,
    version, status, published_at,
    exec_count, success_count, avg_duration_ms, ext_info,
    delete_flg, created_at, created_by, updated_at, updated_by
) VALUES (
    1000000000000018, 'inspect_entity_metadata', 0,
    '业务对象元数据检查',
    '检查某个业务对象（entity）的元数据实例完整性：字段、选项、关联、校验、业务类型',
    '业务对象|entity 元数据|实体配置|检查实体|inspect entity',
    'Metarepo-Platform',
    'inline', '', '',
    '["browse_metamodel","query_metadata"]',
    '["entity_api_key"]',
    '你现在需要输出业务对象 {entity_api_key} 的元数据实例完整性报告。请严格按以下步骤执行：

## 步骤 1: 读取业务对象自身
调用 query_metadata(metamodel_api_key="entity", api_key="{entity_api_key}")
确认 entity 存在且 enableFlg=1；记录 namespace（system/product/custom）、customFlg、sortNum

## 步骤 2: 读取字段清单
调用 query_metadata(metamodel_api_key="item", entity_api_key="{entity_api_key}")
按 sortNum 排序。对每个字段：
- 列出 apiKey / label / itemType / dbColumn / 必填 / 唯一
- PICK_LIST 字段记录 apiKey，后续查选项

## 步骤 3: 读取选项值
对步骤 2 中每个 PICK_LIST 字段，调用：
query_metadata(metamodel_api_key="pickOption", entity_api_key="{entity_api_key}", item_api_key="<字段 apiKey>")
列出选项 apiKey / label / optionOrder / defaultFlg

## 步骤 4: 读取关联关系
调用 query_metadata(metamodel_api_key="entityLink", entity_api_key="{entity_api_key}")
列出以 {entity_api_key} 为父对象的 ONE_TO_MANY / ONE_TO_ONE 关系

## 步骤 5: 读取校验规则与业务类型
- query_metadata(metamodel_api_key="checkRule", entity_api_key="{entity_api_key}")
- query_metadata(metamodel_api_key="busiType", entity_api_key="{entity_api_key}")

## 步骤 6: 输出报告
### {entity_api_key} 元数据实例报告
- **基本信息**（label / namespace / customFlg / enableFlg）
- **字段清单**（Markdown 表格）
- **选项值**（按 itemApiKey 分组）
- **关联关系**（指向哪些子对象）
- **校验规则 & 业务类型**（各一段列表）
- **体检**：
  · 🟢 通过项
  · 🟡 建议项（缺默认 busiType / PICK_LIST 缺默认选项 / labelKey 缺失）
  · 🔴 阻断项（PICK_LIST 无选项值、必填字段无 label、关联对象不存在 等）
最后给出 VERDICT: PASS / WARN / FAIL。',
    'read_only', 0, 20, 60000, 1,
    '1.0.0', 'published', 1746489600000,
    0, 0, 0, '{"tags":["metarepo","entity"]}',
    0, 1746489600000, 0, 1746489600000, 0
) ON CONFLICT (tenant_id, api_key) WHERE delete_flg = 0 DO NOTHING;


-- ── 10. knowledge_doc_search ─────────────────────────────

INSERT INTO ai_skill_definition (
    id, api_key, tenant_id, name, description, when_to_use, owner,
    context, agent, model, allowed_tools, arguments, prompt,
    risk_level, requires_confirmation, max_tool_calls, timeout_ms, idempotent_flg,
    version, status, published_at,
    exec_count, success_count, avg_duration_ms, ext_info,
    delete_flg, created_at, created_by, updated_at, updated_by
) VALUES (
    1000000000000019, 'knowledge_doc_search', 0,
    '知识库文档检索',
    '深度检索知识库文档，支持多维度过滤、多轮追问、结果摘要与引用溯源，帮助用户快速定位和理解知识库中的专业文档内容',
    '知识检索|文档查找|知识库搜索|查资料|找文档|产品手册|技术文档|解决方案|成功案例|FAQ|操作指南|培训材料|白皮书|竞品分析|帮我找|有没有关于|查一下',
    'AI-Platform',
    'inline', '', '',
    '["knowledge_search","list_knowledge_bases","knowledge_doc_detail"]',
    '["query","knowledge_base_id"]',
    '你是一位专业的知识库检索助手。你的任务是帮助用户从知识库中精准定位相关文档，并以结构化、易理解的方式呈现检索结果。

## 核心能力

1. **智能查询理解**：分析用户意图，必要时拆解为多个子查询以提升召回率
2. **多维度过滤**：根据用户描述自动识别文档类别、行业、业务阶段等过滤条件
3. **结果综合分析**：不只是罗列检索结果，而是提炼核心信息、对比异同、给出结论
4. **引用溯源**：每个结论都标注来源文档和章节，方便用户深入阅读原文

## 执行策略

### 策略 1: 单次精准检索（默认）

当用户查询意图明确、关键词清晰时使用。

**步骤**：
1. 分析用户查询，提取核心意图和可能的过滤条件
2. 调用 knowledge_search(query="{query}", top_k=5)
3. 如果用户指定了知识库，加上 knowledge_base_id={knowledge_base_id} 参数
4. 综合分析结果，输出结构化回答

### 策略 2: 渐进式检索

当首次检索结果不理想（结果少于 2 条或相关度低于 0.5）时使用。

**步骤**：
1. 首次检索：使用用户原始查询
2. 如果结果不足，尝试以下补充策略（按需选择 1-2 个）：
   - 去掉过滤条件，扩大搜索范围：knowledge_search(query="{query}", top_k=8)
   - 用同义词/相关术语重新查询
   - 拆解为更具体的子问题分别检索
3. 合并多次检索结果，去重后综合分析

### 策略 3: 多角度对比检索

当用户需要对比分析（如"A 和 B 的区别"、"各方案优缺点"）时使用。

**步骤**：
1. 拆解为多个独立查询（每个角度一次检索）
2. 分别调用 knowledge_search
3. 对比分析各查询结果，输出对比表格

## 特殊场景处理

### 用户未指定知识库
- 先调用 list_knowledge_bases 查看可用知识库
- 如果只有 1 个知识库，直接在该库中检索
- 如果有多个知识库，根据查询内容推断最可能的知识库，或在全部库中检索

### 检索结果质量低
- 相关度分数普遍低于 0.5 时，主动告知用户结果可能不够精准
- 建议用户调整查询方式或确认知识库中是否有相关文档

## 输出格式

### 检索成功时

## 📚 检索结果：{用户问题的简短描述}

### 核心发现
{用 2-3 句话概括最重要的发现，直接回答用户问题}

### 详细内容
#### 1. {文档标题} — {章节名}
> {最相关的内容摘要，150-300 字}

**关键信息**：
- 要点 1
- 要点 2
- 要点 3

📄 来源：{文档标题} | 章节：{section_title} | 相关度：{score}

---

#### 2. {文档标题} — {章节名}
> {内容摘要}

📄 来源：...

### 💡 建议
{基于检索结果给出的建议或下一步行动指引}
- 如果需要更详细的信息，可以追问具体方面
- 相关主题推荐：{列出 2-3 个相关的可追问方向}

### 检索无结果时

未找到直接相关的文档。可能的原因：
1. 知识库中尚未收录该主题的文档
2. 查询关键词与文档用词不匹配

建议：
- 尝试换个说法：{给出 2-3 个替代查询建议}
- 如果是特定产品/型号，请提供完整名称
- 可以尝试更宽泛的查询范围

## 质量要求

1. **准确性**：只基于检索到的文档内容回答，不编造信息
2. **完整性**：如果多个文档涉及同一主题，综合多个来源给出完整答案
3. **可追溯**：每个关键信息点都标注来源文档
4. **简洁性**：优先呈现最相关的内容，避免大段复制粘贴
5. **实用性**：结尾给出可操作的建议或追问方向',
    'read_only', 0, 12, 30000, 1,
    '1.0.0', 'published', 1747267200000,  -- 2025-05-15 发布
    0, 0, 0, '{"tags":["knowledge","retrieval","document","search","rag"],"changelog":"初始版本：多策略检索 + 结果综合分析 + 引用溯源","argument_descriptions":{"query":"检索问题，用自然语言描述你要查找的知识","knowledge_base_id":"知识库"},"argument_config":{"query":{"type":"text","required":true,"placeholder":"输入你要检索的问题","label":"检索问题"},"knowledge_base_id":{"type":"select","required":false,"label":"知识库","placeholder":"选择知识库（不选则检索全部）","data_source":"knowledge_bases","data_source_api":"/api/knowledge/bases","option_label_field":"name","option_value_field":"id","allow_empty":true,"empty_label":"全部知识库"}}}',
    0, 1747267200000, 0, 1747267200000, 0
) ON CONFLICT (tenant_id, api_key) WHERE delete_flg = 0 DO NOTHING;


-- ═══════════════════════════════════════════════════════════
-- Skill 分类预置数据
-- 平台级（tenant_id=0），system_flg=1 不可删除
-- ═══════════════════════════════════════════════════════════

INSERT INTO ai_skill_category (
    id, api_key, tenant_id, name, name_key, description, icon, color,
    sort_num, enabled_flg, system_flg,
    delete_flg, created_at, created_by, updated_at, updated_by
) VALUES
(2000000000000001, 'crm', 0, 'CRM 业务', 'skill.category.crm', 'CRM 业务相关技能，如客户分析、商机管理', '📊', '#1890ff', 10, 1, 1, 0, 1746489600000, 0, 1746489600000, 0),
(2000000000000002, 'metarepo', 0, '元数据管理', 'skill.category.metarepo', '元模型检查、配置校验、列映射反查等', '🗂️', '#52c41a', 20, 1, 1, 0, 1746489600000, 0, 1746489600000, 0),
(2000000000000003, 'analysis', 0, '数据分析', 'skill.category.analysis', '多维数据分析、统计报表、趋势洞察', '📈', '#faad14', 30, 1, 1, 0, 1746489600000, 0, 1746489600000, 0),
(2000000000000004, 'automation', 0, '自动化操作', 'skill.category.automation', '批量处理、定时任务、数据清理等自动化技能', '⚙️', '#f5222d', 40, 1, 1, 0, 1746489600000, 0, 1746489600000, 0),
(2000000000000005, 'custom', 0, '自定义', 'skill.category.custom', '租户自行创建的技能分类', '🔧', '#722ed1', 100, 1, 1, 0, 1746489600000, 0, 1746489600000, 0),
(2000000000000006, 'knowledge', 0, '知识库', 'skill.category.knowledge', '知识库检索、文档查找、RAG 相关技能', '📚', '#13c2c2', 25, 1, 1, 0, 1747267200000, 0, 1747267200000, 0)
ON CONFLICT (tenant_id, api_key) WHERE delete_flg = 0 DO NOTHING;

-- ═══════════════════════════════════════════════════════════
-- 为预置技能设置 category 字段（关联 ai_skill_category.api_key）
-- 需要 category 列已通过 ALTER TABLE 添加
-- ═══════════════════════════════════════════════════════════

UPDATE ai_skill_definition SET category = 'crm'        WHERE api_key = 'accountInsight'          AND tenant_id = 0 AND delete_flg = 0;
UPDATE ai_skill_definition SET category = 'crm'        WHERE api_key = 'verify_config'           AND tenant_id = 0 AND delete_flg = 0;
UPDATE ai_skill_definition SET category = 'crm'        WHERE api_key = 'diagnose'                AND tenant_id = 0 AND delete_flg = 0;
UPDATE ai_skill_definition SET category = 'crm'        WHERE api_key = 'customer_360'            AND tenant_id = 0 AND delete_flg = 0;
UPDATE ai_skill_definition SET category = 'crm'        WHERE api_key = 'pipeline_analysis'       AND tenant_id = 0 AND delete_flg = 0;
UPDATE ai_skill_definition SET category = 'analysis'   WHERE api_key = 'data_analysis'           AND tenant_id = 0 AND delete_flg = 0;
UPDATE ai_skill_definition SET category = 'automation' WHERE api_key = 'batch_cleanup'           AND tenant_id = 0 AND delete_flg = 0;
UPDATE ai_skill_definition SET category = 'metarepo'   WHERE api_key = 'inspect_metamodel'       AND tenant_id = 0 AND delete_flg = 0;
UPDATE ai_skill_definition SET category = 'metarepo'   WHERE api_key = 'trace_db_column'         AND tenant_id = 0 AND delete_flg = 0;
UPDATE ai_skill_definition SET category = 'metarepo'   WHERE api_key = 'inspect_entity_metadata' AND tenant_id = 0 AND delete_flg = 0;
UPDATE ai_skill_definition SET category = 'knowledge'  WHERE api_key = 'knowledge_doc_search'    AND tenant_id = 0 AND delete_flg = 0;
