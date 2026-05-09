-- Skill 初始化数据 — paas_ai schema
-- 将内置 Skill 定义写入 ai_skill_definition 表
-- 执行前提：ai_skill_definition 表已创建（见 init_tables.sql）

SET search_path TO paas_ai;

-- ═══════════════════════════════════════════════════════════
-- account-insight: 客户深度洞察分析
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
    '客户深度洞察',
    '深度分析指定客户的业务全景，包括基本信息、商机分布、联系人网络、活动轨迹，并给出跟进建议',
    '客户洞察|客户分析|客户画像|account分析|客户情况|了解客户',
    'CRM-Product',
    'fork',
    '',  -- 不指定子 Agent，使用通用 SubagentExecutor
    '',  -- 继承主模型
    '["query_schema","query_data","analyze_data"]',
    '["account_id"]',
    '你是一位资深 CRM 客户分析专家。请对客户 {account_id} 进行深度洞察分析，生成结构化的客户画像报告。

## 分析步骤

### 步骤 1: 获取客户基本信息
调用 query_data(action="get", entity_api_key="account", record_id="{account_id}")
提取：公司名称、行业、规模、地区、评分、负责人、创建时间。

### 步骤 2: 分析商机全景
调用 analyze_data(entity_api_key="opportunity", metrics=[{"field":"amount","function":"sum"},{"field":"id","function":"count"}], group_by="stage", filters={"accountId":"{account_id}"})
了解各阶段商机数量和金额分布。

### 步骤 3: 获取商机明细
调用 query_data(action="query", entity_api_key="opportunity", filters={"accountId":"{account_id}"}, order_by="-amount", page_size=10)
获取金额最大的 10 个商机详情。

### 步骤 4: 获取联系人网络
调用 query_data(action="query", entity_api_key="contact", filters={"accountId":"{account_id}"}, page_size=20)
梳理关键决策人、影响者、使用者的角色分布。

### 步骤 5: 获取活动轨迹
调用 query_data(action="query", entity_api_key="activity", filters={"accountId":"{account_id}"}, order_by="-created_at", page_size=15)
分析最近的互动频率和类型分布。

### 步骤 6: 计算客户健康度
综合以下维度评估：
- 商机活跃度：是否有进行中的商机？最近是否有阶段推进？
- 互动频率：最近 30 天是否有活动记录？
- 联系人覆盖：是否覆盖了决策链上的关键角色？
- 金额贡献：历史成交金额和在谈金额

## 输出格式

请按以下结构输出分析报告：

### 📊 客户概览
| 维度 | 信息 |
|------|------|
| 公司名称 | ... |
| 行业/规模 | ... |
| 负责人 | ... |
| 客户评分 | ... |
| 合作时长 | ... |

### 💰 商机分析
- 在谈商机：X 个，总金额 ¥XXX 万
- 各阶段分布：（表格）
- 最大商机：名称 + 金额 + 阶段 + 预计关单日期
- 加权金额（金额×概率）：¥XXX 万

### 👥 联系人网络
- 总联系人数：X 人
- 关键决策人：姓名 + 职位
- 主要联系人：姓名 + 职位
- 覆盖度评估：是否缺少关键角色

### 📅 活动轨迹
- 最近活动：类型 + 主题 + 时间
- 30 天内活动数：X 次
- 活动类型分布：拜访/电话/邮件/会议

### 🏥 客户健康度
- 综合评分：🟢良好 / 🟡一般 / 🔴需关注
- 各维度评分明细

### 💡 跟进建议
基于以上分析，给出 3-5 条具体可执行的跟进建议，包括：
- 应该联系谁（具体联系人）
- 应该推进哪个商机
- 应该安排什么类型的活动
- 需要关注的风险点',
    'read_only',
    0,   -- 只读分析，无需确认
    15,
    45000,
    1,   -- 幂等
    '1.0.0',
    'published',
    1746489600000,  -- 2025-05-06 发布
    0, 0, 0,
    '{"tags":["crm","account","analysis"],"changelog":"初始版本：客户全景分析 + 健康度评估 + 跟进建议"}',
    0,
    1746489600000,
    0,
    1746489600000,
    0
);

-- 写入初始版本快照
INSERT INTO ai_skill_version (
    id, tenant_id, skill_api_key, version,
    description, when_to_use,
    context, agent, model, allowed_tools, arguments,
    prompt,
    risk_level, requires_confirmation, max_tool_calls, timeout_ms,
    changelog, published_by,
    delete_flg, created_at, created_by, updated_at, updated_by
) VALUES (
    1000000000000101,
    0,
    'accountInsight',
    '1.0.0',
    '深度分析指定客户的业务全景，包括基本信息、商机分布、联系人网络、活动轨迹，并给出跟进建议',
    '客户洞察|客户分析|客户画像|account分析|客户情况|了解客户',
    'fork',
    '',
    '',
    '["query_schema","query_data","analyze_data"]',
    '["account_id"]',
    '你是一位资深 CRM 客户分析专家。请对客户 {account_id} 进行深度洞察分析，生成结构化的客户画像报告。

## 分析步骤

### 步骤 1: 获取客户基本信息
调用 query_data(action="get", entity_api_key="account", record_id="{account_id}")
提取：公司名称、行业、规模、地区、评分、负责人、创建时间。

### 步骤 2: 分析商机全景
调用 analyze_data(entity_api_key="opportunity", metrics=[{"field":"amount","function":"sum"},{"field":"id","function":"count"}], group_by="stage", filters={"accountId":"{account_id}"})
了解各阶段商机数量和金额分布。

### 步骤 3: 获取商机明细
调用 query_data(action="query", entity_api_key="opportunity", filters={"accountId":"{account_id}"}, order_by="-amount", page_size=10)
获取金额最大的 10 个商机详情。

### 步骤 4: 获取联系人网络
调用 query_data(action="query", entity_api_key="contact", filters={"accountId":"{account_id}"}, page_size=20)
梳理关键决策人、影响者、使用者的角色分布。

### 步骤 5: 获取活动轨迹
调用 query_data(action="query", entity_api_key="activity", filters={"accountId":"{account_id}"}, order_by="-created_at", page_size=15)
分析最近的互动频率和类型分布。

### 步骤 6: 计算客户健康度
综合以下维度评估：
- 商机活跃度：是否有进行中的商机？最近是否有阶段推进？
- 互动频率：最近 30 天是否有活动记录？
- 联系人覆盖：是否覆盖了决策链上的关键角色？
- 金额贡献：历史成交金额和在谈金额

## 输出格式

请按以下结构输出分析报告：

### 📊 客户概览
| 维度 | 信息 |
|------|------|
| 公司名称 | ... |
| 行业/规模 | ... |
| 负责人 | ... |
| 客户评分 | ... |
| 合作时长 | ... |

### 💰 商机分析
- 在谈商机：X 个，总金额 ¥XXX 万
- 各阶段分布：（表格）
- 最大商机：名称 + 金额 + 阶段 + 预计关单日期
- 加权金额（金额×概率）：¥XXX 万

### 👥 联系人网络
- 总联系人数：X 人
- 关键决策人：姓名 + 职位
- 主要联系人：姓名 + 职位
- 覆盖度评估：是否缺少关键角色

### 📅 活动轨迹
- 最近活动：类型 + 主题 + 时间
- 30 天内活动数：X 次
- 活动类型分布：拜访/电话/邮件/会议

### 🏥 客户健康度
- 综合评分：🟢良好 / 🟡一般 / 🔴需关注
- 各维度评分明细

### 💡 跟进建议
基于以上分析，给出 3-5 条具体可执行的跟进建议，包括：
- 应该联系谁（具体联系人）
- 应该推进哪个商机
- 应该安排什么类型的活动
- 需要关注的风险点',
    'read_only',
    0,
    15,
    45000,
    '初始版本：客户全景分析 + 健康度评估 + 跟进建议',
    0,
    0,
    1746489600000,
    0,
    1746489600000,
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
