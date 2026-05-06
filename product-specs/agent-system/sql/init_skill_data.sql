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
