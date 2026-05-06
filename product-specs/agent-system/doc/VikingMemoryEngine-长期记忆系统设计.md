# VikingMemoryEngine — 长期记忆系统设计文档

> 基于 OpenViking 范式设计，直连腾讯向量库（tcvectordb SDK），不依赖 mem0。
> 对齐 apps-agent（OpenViking）的核心能力，针对 CRM toB 场景做领域适配。

---

## 一、设计背景与技术选型

### 1.1 为什么不用 mem0

经过源码级分析和生产验证，mem0 在我们的架构中已被架空：

| 能力 | mem0 提供的 | 我们实际用的 |
|:---|:---|:---|
| LLM 提取 | ADDITIVE_EXTRACTION_PROMPT | 我们的 CRM 结构化提取指令（覆盖了 mem0 的 prompt） |
| 向量检索 | LangChain 桥接 | `_native_search`（绕过 LangChain，直连 tcvectordb） |
| 去重 | MD5 hash 精确去重 | 我们的语义去重 + LLM 精判 |
| Filter | 不支持（LangChain TencentVectorDB 的 lark parser 不兼容） | 直连 tcvectordb 原生 filter |
| Score | 不返回（LangChain 的 similarity_search_by_vector 无 score） | 直连 tcvectordb 原生 score |
| BM25 混合检索 | 不支持 | 直连 tcvectordb hybrid_search |

mem0 唯一还在用的是 `add()` 的 LangChain 桥接写入，而这个也有 filter/score/sparse_vector 兼容性问题。

### 1.2 为什么不直接用 OpenViking SDK

OpenViking 的文件系统范式（VikingFS）和目录递归检索是架构级能力，需要完整的虚拟文件系统。但对于 CRM 场景（单用户记忆量 < 500 条），文件系统范式的 token 效率优势不明显。我们取 OpenViking 的核心机制（9 类分类、L0/L1/L2 三层、语义去重、合并策略），用 tcvectordb 的 metadata 字段模拟目录结构。

### 1.3 最终选型

```
提取层: 自研（LLM 提取 + 规则预过滤）
存储层: 腾讯向量库（tcvectordb SDK 直连，支持 filter index + BM25 稀疏向量）+ PG（profile/agent_rules）
检索层: 自研（BM25 混合检索 + 递归目录检索 + 分层加载）
```

---

## 二、记忆分类体系

### 2.1 9 类分类（对齐 OpenViking + apps-agent wiki 设计 + SOUL 扩展）

| 类别 | 归属 | 说明 | 合并策略 | CRM 场景示例 |
|:---|:---|:---|:---|:---|
| soul | 用户 | 用户对 Agent 的角色定义和行为准则 | LLM 合并（矛盾时以新为准） | "你是我的数据分析助理，回复不超过100字" |
| profile | 用户 | 身份、角色、能力水平 | 始终合并（新值追加到旧值） | "华东区销售总监，管理15人团队" |
| preferences | 用户 | 偏好（按 aspect 独立） | 同 aspect 替换，不同 aspect 独立（向量库语义检索） | "数据展示偏好: 表格格式" |
| entities | 用户 | 客户/联系人/商机/合同 | 同 merge_key 替换 | "华为科技/ERP项目: 金额800万，谈判阶段" |
| events | 用户 | 决策、里程碑、计划 | 不合并，语义去重 | "2026-04-28 丁总同意报价方案" |
| cases | Agent | 问题 + 解决方案 | 不合并，语义去重 | "查询报错 → 字段名拼写错误" |
| patterns | Agent | 可重复的工作流程 | 同 merge_key 合并 | "客户360分析: 基本信息→商机→联系人→活动" |
| tools | Agent | 工具使用统计和经验 | 同工具名合并（Python 统计累加） | "query_data: 调用42次，成功率95%" |
| skills | Agent | 技能执行策略 | 同技能名合并 | "Pipeline报告: 阶段统计→负责人统计→环比" |

### 2.2 分类决策逻辑

```
选择类别时的核心问题:

  Agent 应该怎么做？   → soul
  用户是谁？         → profile
  用户偏好什么？     → preferences
  这是什么实体？     → entities
  发生了什么事？     → events
  问题怎么解决的？   → cases
  流程是什么？       → patterns
  工具怎么用最好？   → tools
  技能怎么执行最优？ → skills
```

### 2.3 9 类 → 4 维度映射（兼容 MemoryMiddleware）

```python
_CATEGORY_TO_DIMENSION = {
    "soul":        MemoryDimension.USER_PROFILE,
    "profile":     MemoryDimension.USER_PROFILE,
    "preferences": MemoryDimension.USER_PROFILE,
    "entities":    MemoryDimension.CUSTOMER_CONTEXT,
    "events":      MemoryDimension.CUSTOMER_CONTEXT,
    "cases":       MemoryDimension.DOMAIN_KNOWLEDGE,
    "patterns":    MemoryDimension.DOMAIN_KNOWLEDGE,
    "tools":       MemoryDimension.TASK_HISTORY,
    "skills":      MemoryDimension.TASK_HISTORY,
}
```


### 2.4 各类别存储形式详解

每个类别的 abstract（L0）、overview（L1）、content（L2）、merge_key、parent_entity 的格式和含义不同：

#### profile — 用户身份

```
存储形式:
  abstract:      "用户为华东区销售总监，管理15人团队，负责互联网行业大客户"
  overview:      "## 身份\n- 角色: 销售总监\n- 区域: 华东区\n## 团队\n- 规模: 15人\n- 行业: 互联网"
  content:       "用户是华东区的销售总监，管着15个人的团队，主要负责互联网行业大客户。"（增量合并，多次写入的内容追加）
  merge_key:     "profile"（固定值，全局唯一，始终合并到同一条）
  parent_entity: ""（无父实体）

特殊行为:
  - 每个用户只有 1 条 profile 记忆
  - 新信息追加到 content 末尾（不替换）
  - "销售经理" → "销售总监" 两次写入后 content = "销售经理...\n销售总监..."
```

#### preferences — 用户偏好

```
存储形式:
  abstract:      "数据展示偏好: 表格格式，简洁风格"
  overview:      "## 偏好领域\n- 领域: 数据展示\n## 具体偏好\n- 使用表格格式\n- 简洁风格"
  content:       "用户偏好使用表格展示数据，要求简洁不要长篇分析。"
  merge_key:     "数据展示偏好"（按 aspect 分，每个 aspect 一条）
  parent_entity: ""（无父实体）

特殊行为:
  - 每个 aspect 独立一条记忆
  - "数据展示偏好" 和 "回复风格偏好" 是两条不同的记忆
  - 同 aspect 新值替换旧值（"表格" → "图表" 时，旧的被删除）
  - 不同 aspect 互不影响

aspect 示例:
  "数据展示偏好"    — 表格/图表/列表
  "回复风格偏好"    — 简洁/详细/中英混合
  "金额格式偏好"    — 万为单位/不要小数
  "数据范围偏好"    — 默认只看自己的/看全部
  "Pipeline查看偏好" — 按阶段/按负责人/按时间
```

#### entities — 实体信息

```
存储形式（客户汇总）:
  abstract:      "华为科技: 通信行业龙头，3个商机总金额780万"
  overview:      "## 基本信息\n- 行业: 通信\n- 商机数: 3\n## 金额\n- 总金额: 780万"
  content:       "华为科技是通信行业龙头企业，当前有3个活跃商机，总金额780万。"
  merge_key:     "华为科技"（客户名）
  parent_entity: ""（顶层实体，无父）

存储形式（商机）:
  abstract:      "华为科技/ERP升级: 金额500万，谈判阶段"
  overview:      "## 基本信息\n- 客户: 华为科技\n- 金额: 500万\n## 状态\n- 阶段: 谈判"
  content:       "华为科技的ERP升级项目，金额500万，处于谈判阶段，预计下月签约。"
  merge_key:     "华为科技/ERP升级"（客户名/商机名）
  parent_entity: "华为科技"（属于华为科技）

存储形式（联系人）:
  abstract:      "华为科技/张总: 职位CTO，电话139-0001-0001"
  overview:      "## 基本信息\n- 客户: 华为科技\n- 姓名: 张总\n## 联系方式\n- 职位: CTO\n- 电话: 139-0001-0001"
  content:       "华为科技联系人张总，职位CTO，电话139-0001-0001，负责技术决策。"
  merge_key:     "华为科技/张总"（客户名/联系人名）
  parent_entity: "华为科技"（属于华为科技）

层级关系:
  parent_entity="" 的是顶层客户汇总（用于两级下钻的第一级）
  parent_entity="华为科技" 的是该客户下的子条目（商机、联系人、合同等）
```

#### events — 事件记录

```
存储形式:
  abstract:      "2026-04-28 华为ERP项目评审通过，丁总同意报价方案"
  overview:      "## 决策内容\n丁总同意报价方案\n## 原因\n项目评审通过\n## 结果\n预计下周签约"
  content:       "2026-04-28与华为张总开会，ERP项目评审通过，丁总同意580万报价方案，预计下周三签约。"
  merge_key:     ""（空，events 不合并）
  parent_entity: "华为科技"（关联客户）

特殊行为:
  - 不合并，每个事件独立存储
  - 语义去重：相似度 > 0.9 时 LLM 判断是否重复
  - 90 天后过期（可被遗忘策略清理）
```

#### cases — 案例

```
存储形式:
  abstract:      "查询商机报错 → 字段名 stage 写成 status，修正后解决"
  overview:      "## 问题\n查询商机时报错\n## 解决方案\n字段名 stage 写成了 status，修正后正常"
  content:       "查询 opportunity 时报错，原因是字段名写错，stage 写成了 status。修正后查询正常。建议先用 query_schema 确认字段名。"
  merge_key:     ""（空，cases 不合并）
  parent_entity: ""（通常无关联客户）

特殊行为:
  - 不合并，每个案例独立存储
  - 包含"问题→解决方案"结构
  - Agent 遇到类似错误时自动检索
```

#### patterns — 模式

```
存储形式:
  abstract:      "客户360分析流程: 基本信息→商机→联系人→活动→汇总"
  overview:      "## 触发条件\n用户请求客户全景分析\n## 流程\n1. 查基本信息\n2. 查商机\n3. 查联系人\n4. 查活动\n5. 汇总分析"
  content:       "当用户请求客户全景分析时，按以下顺序执行：先查基本信息，再查商机列表，然后查联系人，接着查活动记录，最后汇总分析。"
  merge_key:     "客户360分析流程"（流程名）
  parent_entity: ""（通用流程，无关联客户）

特殊行为:
  - 同 merge_key 合并（流程优化时替换旧版本）
  - Agent 执行多步骤任务时自动检索匹配的 pattern
```

#### tools — 工具使用记忆

```
存储形式:
  abstract:      "query_data: 本轮调用3次，成功率100%"
  overview:      "## 工具统计\n- 工具: query_data\n- 调用: 3次\n- 成功: 3次\n- 失败: 0次"
  content:       "工具 query_data 在本轮对话中调用3次，成功3次，失败0次，成功率100%。"
  merge_key:     "query_data"（工具名）
  parent_entity: ""（无关联客户）

特殊行为:
  - 纯 Python 统计提取（不调 LLM）
  - 同工具名合并（统计累加）
  - 包含成功率、调用次数等量化指标
```

#### skills — 技能执行记忆

```
存储形式:
  abstract:      "Pipeline报告: 按 阶段统计→负责人统计→环比→建议 顺序执行"
  overview:      "## 技能信息\n- 名称: Pipeline报告\n## 推荐流程\n1. 按阶段统计\n2. 按负责人统计\n3. 环比对比\n4. 生成建议"
  content:       "执行Pipeline报告技能时，最佳顺序是：先按阶段统计金额和数量，再按负责人分组，然后与上月环比，最后生成跟进建议。"
  merge_key:     "Pipeline报告"（技能名）
  parent_entity: ""（无关联客户）

特殊行为:
  - 同技能名合并（策略优化时替换旧版本）
  - Agent 执行技能前自动检索匹配的 skill 记忆
```

### 2.5 各类别存储形式汇总

| 类别 | merge_key 含义 | parent_entity 含义 | 合并行为 | 记忆数量 |
|:---|:---|:---|:---|:---|
| profile | 固定 "profile" | 空 | 始终追加合并，全局 1 条 | 每用户 1 条 |
| preferences | aspect 名（如"数据展示偏好"） | 空 | 同 aspect 替换（向量库语义检索） | 每用户 5-15 条 |
| entities | 实体路径（如"华为科技/ERP升级"） | 父实体名（如"华为科技"） | 同路径替换 | 每客户 3-10 条 |
| events | 空 | 关联客户名 | 不合并，语义去重 | 持续增长，90天过期 |
| cases | 空 | 空 | 不合并，语义去重 | 持续增长，180天过期 |
| patterns | 流程名 | 空 | 同名替换 | 每用户 3-10 条 |
| tools | 工具名 | 空 | 同名替换（统计累加） | 每工具 1 条 |
| skills | 技能名 | 空 | 同名替换 | 每技能 1 条 |


---

## 三、L0/L1/L2 三层信息模型

> 对齐 apps-agent（OpenViking）：L0/L1 属于目录，L2 属于叶子。

### 3.1 三层定义（对齐 apps-agent）

| 层级 | 归属 | 生成方式 | Token 量 | 用途 |
|:---|:---|:---|:---|:---|
| L0 | 目录节点 | 系统 LLM 聚合（从所有叶子 content 压缩为一句话） | ~30-100 | 向量检索匹配 + 注入 Agent 上下文 |
| L1 | 目录节点 | 系统 LLM 聚合（从所有叶子 content 生成结构化 Markdown） | ~200-500 | Agent 按需加载（了解目录结构） |
| L2 | 叶子节点 | LLM 提取时直接输出 | 无限制 | Agent 按需加载（获取完整记忆内容） |

### 3.2 目录节点 vs 叶子节点

```
向量库中的文档分两种：

1. 目录节点（is_leaf=false）
   abstract:  L0 聚合摘要（系统 LLM 生成）
   overview:  L1 结构化导航（系统 LLM 生成）
   content:   空
   vector:    embed(L0)
   示例:
     abstract = "华为科技: 张伟说话直接喜欢PPT，ERP项目内部有分歧需分别沟通，审批流程复杂至少3-4周"
     overview = "## 联系人洞察\n- 张伟: 说话直接，汇报用PPT\n## 商机洞察\n- ERP项目: 内部有分歧\n## 内部流程\n- 审批: 至少3-4周"

2. 叶子节点（is_leaf=true）
   abstract:  叶子的一句话摘要（LLM 提取时输出）
   overview:  空（不需要，由目录 L1 替代）
   content:   完整记忆内容（LLM 提取时输出）
   vector:    embed(abstract)
   示例:
     abstract = "华为科技/张伟: 说话直接，汇报用PPT，开会控制30分钟"
     content  = "张伟说话直接不绕弯子，汇报用PPT带数据，开会控制30分钟。建议和他沟通时直接说重点。"
```

### 3.3 目录 L0/L1 的生成逻辑

**触发时机**：每次叶子节点写入或更新后，异步触发该叶子所属目录的重新聚合。

```
LLM 提取叶子 → 写入向量库 → 看到 parent_entity="华为科技"
  → asyncio.create_task(_ensure_directory_node("entities", "华为科技", user_id))
  → 收集华为科技下所有叶子的 content
  → LLM 生成 L1（结构化 Markdown）
  → LLM 从 L1 压缩生成 L0（一句话摘要）
  → 写入/更新目录节点（abstract=L0, overview=L1）
```

**LLM 不提取目录**。目录的存在完全由叶子的 `parent_entity` 字段驱动。

**L0 生成 prompt**：
```
将以下结构化目录压缩为一句话摘要（不超过100字）。
目录路径: entities/华为科技
目录内容: {L1 内容}
直接输出一句话摘要。
```

**L1 生成 prompt**：
```
将以下多条记忆聚合为一个结构化 Markdown 目录。
目录路径: entities/华为科技
记忆条目:
- 张伟说话直接不绕弯子，汇报用PPT带数据，开会控制30分钟
- ERP项目张伟和李娜意见有分歧，建议分别沟通
- 华为内部审批流程复杂，IT部门后还需采购委员会，至少3-4周
用 ## 标题分组，- 列表列出具体信息。
```

### 3.4 检索时的分层加载

```
检索流程:
  1. 用户查询 → embedding → hybrid_search（匹配目录 L0 向量 + 叶子 abstract 向量）
  2. 返回 Top-K 结果，区分目录节点和叶子节点
  3. 注入 Agent 上下文:
     - 目录节点 → 注入 L0 摘要，标记 [DIR:xxx]
     - 叶子节点 → 注入 abstract（L0 摘要），标记 [ID:xxx]
  4. Agent 按需加载:
     - 需要目录结构 → memory_read(id=目录ID, level="L1") → 返回 overview
     - 需要叶子详情 → memory_read(id=叶子ID, level="L2") → 返回 content

注入格式:
  <memory_context>
  - [DIR:dir_001] [entities] 华为科技: 张伟直接，审批3周，ERP有分歧
  - [ID:mem_001] [entities] 华为/张伟: 说话直接，汇报用PPT，开会控制30分钟
  - [ID:mem_002] [entities] 华为/ERP项目: 张伟和李娜有分歧，建议分别沟通
  </memory_context>
```

### 3.5 与 apps-agent 的对齐状态

| 维度 | apps-agent | 我们 | 状态 |
|:---|:---|:---|:---|
| L0/L1 属于目录 | ✅ | ✅ | 已对齐 |
| L2 属于叶子 | ✅ | ✅ | 已对齐 |
| 目录 L0 由 LLM 聚合 | ✅ | ✅ | 已对齐 |
| 目录 L1 由 LLM 聚合 | ✅ | ✅ | 已对齐 |
| 叶子变更后自动重新聚合 | ✅ | ✅ | 已对齐 |
| 检索返回 L0 + 按需加载 | ✅ | ✅ | 已对齐 |
| LLM 提取只输出叶子内容 | ✅（只输出 content） | ⚠️（仍输出 abstract + content） | 待优化 |

---

## 四、记忆写入流水线

### 4.1 存储路由

```
LLM 提取出一条记忆
  │
  ├── category = profile / agent_rules
  │   → PG 存储（_merge_single_record）
  │   → 每用户各一条，LLM 合并
  │   → 不写入向量库（不需要语义检索）
  │
  └── category = preferences / entities
      → 向量库存储（_merge_by_key 或 _dedup_create）
      → 同时异步写 PG（_sync_to_pg，前端展示 + 生命周期管理）
      → 写入后异步触发目录聚合（_ensure_directory_node）
```

### 4.2 完整流程

```
对话消息
  │
  ▼
第一层: 预过滤 _should_extract()（代码规则，0 LLM 成本）
  ├── 跳过: 寒暄/确认/感谢
  ├── 跳过: AI 回复太短
  ├── 跳过: 工具全部失败
  └── 通过: 有实质内容的对话
  │
  ▼
第二层: LLM 结构化提取（注入已有 soul/profile/preferences 状态避免重复）
  ├── 输入: EXTRACTION_PROMPT + 已有状态上下文 + 对话文本
  ├── 输出: JSON {"memories": [{category, abstract, content, merge_key, parent_entity}]}
  ├── 注意: LLM 只输出 abstract + content，不输出 overview（由目录聚合生成）
  └── profile/agent_rules 的 merge_key 固定为 "profile"/"agent_rules"
  │
  ▼
第三层: 语义去重 + 分类合并 _dedup_and_store()
  │
  ├── profile / agent_rules → _merge_single_record()
  │     读 PG 已有 → LLM 合并 → 写回 PG 一条
  │     超长自动精炼（profile≤200字，agent_rules≤300字）
  │
  ├── preferences / entities → _merge_by_key()
  │     向量搜索同 merge_key → 同 key 且相似度>0.8 → LLM 合并覆盖
  │     不同 key → 独立存储
  │
  └── 无 merge_key 的 entities → _dedup_create()
        向量预筛（相似度>0.9）→ LLM 精判（skip/create/merge/delete）
  │
  ▼
第四层: 写入向量库（叶子节点）
  │
  ▼
第五层: 异步触发目录聚合 _ensure_directory_node()
  ├── 条件: parent_entity 非空
  ├── 收集该目录下所有叶子的 content
  ├── LLM 生成 L1（结构化 Markdown 导航）
  ├── LLM 从 L1 压缩生成 L0（一句话摘要）
  └── 写入/更新目录节点（abstract=L0, overview=L1, is_leaf=false）
  │
  ▼
第六层: 异步同步 PG（ai_agent_memory 表，前端展示 + 生命周期管理）
  │
  ▼
第七层: 异步触发会话反思（只对 entities 类别）
```

### 4.3 向量库存储内容

**叶子节点**（is_leaf=true）：

| 字段 | 来源 | 示例 |
|------|------|------|
| id | UUID | "mem_a1b2c3" |
| vector | embed(abstract) | 2560 维向量 |
| sparse_vector | BM25(abstract) | 稀疏向量 |
| abstract | LLM 提取时输出 | "华为科技/张伟: 说话直接，汇报用PPT" |
| content | LLM 提取时输出 | "张伟说话直接不绕弯子，汇报用PPT带数据..." |
| overview | 空（由目录 L1 替代） | "" |
| category | LLM 提取时输出 | "entities" |
| merge_key | LLM 提取时输出 | "华为科技/张伟" |
| parent_entity | LLM 提取时输出 | "华为科技" |
| is_leaf | 固定 | "true" |
| status | 固定 | "active" |

**目录节点**（is_leaf=false）：

| 字段 | 来源 | 示例 |
|------|------|------|
| id | 确定性 hash | "dir_abc123" |
| vector | embed(L0) | 2560 维向量 |
| abstract | 系统 LLM 聚合生成（L0） | "华为科技: 张伟直接喜欢PPT，ERP有分歧，审批3周" |
| overview | 系统 LLM 聚合生成（L1） | "## 联系人\n- 张伟: 直接\n## 商机\n- ERP: 有分歧" |
| content | 空 | "" |
| merge_key | 目录名 | "华为科技" |
| parent_entity | 空 | "" |
| is_leaf | 固定 | "false" |

### 4.4 PG 存储内容

**agent_memory 表**（profile / agent_rules 权威存储）：

| 字段 | 说明 | 示例 |
|------|------|------|
| user_id | 用户隔离 | "user_001" |
| category | "profile" 或 "agent_rules" | "profile" |
| merge_key | 固定值 | "profile" |
| content | LLM 合并后的完整内容 | "用户是华东区销售总监，管理15人团队..." |

**ai_agent_memory 表**（全量记忆，前端展示 + 生命周期管理）：

| 字段 | 说明 |
|------|------|
| memory_id | 和向量库 id 一致 |
| category | 所有类别都写入 |
| status | active/stale/archived/deleted |
| last_accessed_at | 最后被检索命中的时间（驱动遗忘） |
| active_count | 累计命中次数 |
| user_query / agent_reply | 产生这条记忆的原始对话 |

---

## 五、记忆检索流水线

### 5.1 完整流程

```
用户查询
  │
  ▼
Step 0: 查询改写（多轮对话时 LLM 解析代词）
  "那个项目怎么样" → "华为ERP项目的状态"
  │
  ▼
Step 1: hybrid_search（BM25 0.7 + 向量 0.3）
  filter: user_id + status != "archived"
  向量库中目录节点和叶子节点都参与检索
  │
  ▼
Step 2: 分离目录节点和叶子节点
  目录节点（is_leaf=false）→ 入优先队列
  叶子节点（is_leaf=true）→ 直接收集
  │
  ▼
Step 3: 递归展开目录（优先队列）
  搜索 parent_uri=目录URI 的子节点
  分数传播: child_score = 0.5×自身 + 0.5×父目录
  收敛检测: Top-K 连续 3 轮不变则停止
  │
  ▼
Step 4: 构建返回结果（返回 L0 摘要）
  目录节点 → 返回 abstract（L0 聚合摘要），标记 [DIR:xxx]
  叶子节点 → 返回 abstract（L0 摘要），标记 [ID:xxx]
  stale 记忆 → 分数 ×0.5，标注 [可能过时]
  │
  ▼
Step 5: 注入 Agent 上下文
  <memory_context>
  - [DIR:dir_001] [entities] 华为科技: 张伟直接，审批3周，ERP有分歧
  - [ID:mem_001] [entities] 华为/张伟: 说话直接，汇报用PPT
  - [ID:mem_002] [entities] 华为/ERP项目: 张伟和李娜有分歧
  </memory_context>
  │
  ▼
Step 6: Agent 按需加载（memory_read 工具）
  memory_read(id=目录ID, level="L1") → 返回目录 overview（结构化导航）
  memory_read(id=叶子ID, level="L2") → 返回叶子 content（完整记忆）
  │
  ▼
Step 7: 异步更新 PG（不阻塞检索）
  UPDATE ai_agent_memory SET last_accessed_at=now, active_count+=1
  stale/archived 被命中 → 复活为 active
```

### 5.2 BM25 混合检索

#### 5.2.1 双路检索原理

```
用户查询: "华为科技的商机情况"
  │
  ├── 稠密向量路（语义匹配）
  │   embed("华为科技的商机情况") → 2560 维向量
  │   → cosine similarity 计算
  │   → 语义相近的记忆得分高（如"华为ERP项目有分歧"虽然没有"商机"这个词但语义相关）
  │
  └── 稀疏向量路（关键词匹配）
      BM25Encoder.encode_queries("华为科技的商机情况") → 稀疏向量
      → 精确匹配"华为科技"、"商机"等关键词
      → 包含这些关键词的记忆得分高（如 abstract 中有"华为科技/ERP项目"）
```

#### 5.2.2 融合取值逻辑

```
两路检索各自返回 Top-K 结果后，通过 WeightedRerank 融合：

  final_score = sparse_weight × BM25_score + dense_weight × vector_score
              = 0.7 × BM25_score + 0.3 × vector_score

权重设计原因：
  BM25 权重 0.7（高）：CRM 场景中客户名、联系人名是精确匹配需求
    "华为科技" 必须精确命中包含"华为科技"的记忆，不能被语义相近的"中兴通讯"替代
  向量权重 0.3（低）：语义补充，捕获同义词和隐含关系
    "商机情况" 可以匹配到"ERP项目有分歧"（语义相关但无关键词重叠）
```

#### 5.2.3 BM25 稀疏向量的生成

```python
# 写入时：为每条记忆的 abstract 生成 BM25 稀疏向量
from tcvdb_text.encoder import BM25Encoder
bm25 = BM25Encoder.default()

# 叶子节点写入
abstract = "华为科技/张伟: 说话直接，汇报用PPT，开会控制30分钟"
sparse_vec = bm25.encode_texts([abstract])[0]  # 稀疏向量（关键词→权重）

# 目录节点写入
l0 = "华为科技: 张伟直接喜欢PPT，ERP有分歧，审批3周"
sparse_vec = bm25.encode_texts([l0])[0]

# 检索时：为查询生成 BM25 稀疏向量
query = "华为科技的商机情况"
query_sparse = bm25.encode_queries([query])[0]
```

#### 5.2.4 hybrid_search API 调用

```python
from tcvectordb.model.document import AnnSearch, KeywordSearch, WeightedRerank, Filter

# 稠密向量检索
ann = AnnSearch(field_name="vector", data=query_vec)

# 稀疏向量检索（BM25 关键词匹配）
kw = KeywordSearch(field_name="sparse_vector", data=query_sparse)

# 加权融合
rerank = WeightedRerank(
    field_list=["vector", "sparse_vector"],
    weight=[0.3, 0.7],  # 向量 0.3 + BM25 0.7
)

# 执行混合检索
results = collection.hybrid_search(
    ann=[ann],
    match=[kw],
    rerank=rerank,
    filter=Filter('user_id = "user_001" and status != "archived"'),
    limit=10,
)
```

#### 5.2.5 融合后的排序示例

```
查询: "华为科技的商机情况"

候选记忆                              BM25_score  vector_score  final_score
─────────────────────────────────────────────────────────────────────────
[DIR] 华为科技: 张伟直接，ERP有分歧     0.95        0.88         0.7×0.95 + 0.3×0.88 = 0.929
[ID]  华为科技/ERP项目: 有分歧          0.90        0.82         0.7×0.90 + 0.3×0.82 = 0.876
[ID]  华为科技/张伟: 说话直接            0.85        0.75         0.7×0.85 + 0.3×0.75 = 0.820
[ID]  腾讯/云项目: 方案阶段             0.20        0.70         0.7×0.20 + 0.3×0.70 = 0.350
─────────────────────────────────────────────────────────────────────────

结果：华为相关记忆排在前面（BM25 精确匹配"华为科技"），腾讯被压到最后（BM25 不匹配）。
即使腾讯的 vector_score 较高（语义上"商机"相关），BM25 的高权重确保了客户名精确匹配优先。
```

#### 5.2.6 检索匹配字段 vs 存储字段

向量库中每个文档有多个字段，但**只有 abstract 的向量化结果参与检索匹配**，其他字段只是存储：

```
向量库中有 3 个文档：

1. 目录节点（华为科技/）
   vector = embed("华为科技: 张伟直接，ERP有分歧，审批3周")  ← 参与检索（cosine）
   sparse_vector = BM25("华为科技: 张伟直接，ERP有分歧...")  ← 参与检索（关键词）
   abstract = "华为科技: 张伟直接，ERP有分歧，审批3周"       ← 向量化的源文本
   overview = "## 联系人\n- 张伟...\n## 商机\n- ERP..."     ← 不参与检索（按需加载）
   content = ""                                             ← 目录没有 content

2. 叶子节点（华为科技/ERP项目）
   vector = embed("华为科技/ERP项目: 张伟和李娜有分歧")      ← 参与检索
   sparse_vector = BM25("华为科技/ERP项目: 张伟和李娜...")   ← 参与检索
   abstract = "华为科技/ERP项目: 张伟和李娜有分歧"           ← 向量化的源文本
   content = "ERP项目张伟和李娜意见有分歧，建议分别沟通..."   ← 不参与检索（按需加载）

3. 叶子节点（华为科技/张伟）
   vector = embed("华为科技/张伟: 说话直接，汇报用PPT")      ← 参与检索
   sparse_vector = BM25("华为科技/张伟: 说话直接...")        ← 参与检索
   abstract = "华为科技/张伟: 说话直接，汇报用PPT"           ← 向量化的源文本
   content = "张伟说话直接不绕弯子，汇报用PPT带数据..."       ← 不参与检索（按需加载）
```

**总结**：

| 字段 | 是否参与检索匹配 | 用途 |
|------|:--------------:|------|
| vector（embed(abstract)） | ✅ | cosine similarity 语义匹配 |
| sparse_vector（BM25(abstract)） | ✅ | 关键词精确匹配 |
| abstract | ❌（是向量化的源文本） | 检索返回给 Agent 的 L0 摘要 |
| overview（L1） | ❌ | Agent 调用 memory_read(level="L1") 时返回 |
| content（L2） | ❌ | Agent 调用 memory_read(level="L2") 时返回 |

### 5.3 分层加载（对齐 apps-agent）

```
检索默认返回 L0 摘要（~30 tokens/条），Agent 按需加载 L1/L2：

  L0 够用 → Agent 直接回答（不调用 memory_read）
  需要目录结构 → memory_read(id=DIR_ID, level="L1") → 返回结构化 Markdown
  需要叶子详情 → memory_read(id=LEAF_ID, level="L2") → 返回完整记忆内容

Token 开销对比：
  5 条 L0 注入: 5 × 30 = 150 tokens
  按需加载 2 条 L2: 2 × 200 = 400 tokens
  总计: 550 tokens（vs 直接返回 5 条 L2 = 1000 tokens）
```

---

## 六、记忆合并策略

### 6.1 按类别差异化

| 类别 | 合并方式 | 触发条件 | 实现方法 |
|:---|:---|:---|:---|
| profile | 始终合并（追加） | 每次 profile 记忆写入 | `_merge_profile()`: 搜索已有 → 内容追加 → 删旧写新 |
| preferences | 同 aspect 替换 | merge_key 相同且相似度 > 0.8 | `_merge_by_key()`: 按 merge_key 搜索 → 替换（向量库） |
| entities | 同实体替换 | merge_key 相同且相似度 > 0.8 | `_merge_by_key()`: 按 merge_key 搜索 → 替换 |
| events | 不合并 | 相似度 > 0.9 时 LLM 判断 | `_dedup_create()`: 向量预筛 + LLM 精判 |
| cases | 不合并 | 相似度 > 0.9 时 LLM 判断 | `_dedup_create()`: 向量预筛 + LLM 精判 |
| patterns | 同流程合并 | merge_key 相同 | `_merge_by_key()` |
| tools | 同工具合并 | merge_key = 工具名 | `_merge_by_key()` |
| skills | 同技能合并 | merge_key = 技能名 | `_merge_by_key()` |

### 6.2 语义去重流程（events/cases）

```
候选记忆
  │
  ▼
向量预筛: 搜索已有同类别记忆，取 Top-3
  │
  ├── 最高相似度 < 0.9 → 直接 create（新信息）
  │
  └── 最高相似度 >= 0.9 → 调 LLM 精判
        │
        ├── skip: 重复/改写，不存储
        ├── create: 虽然相似但是新信息，独立存储
        ├── merge: 与目标记忆合并 → delete 旧 + create 新
        └── delete: 使目标记忆完全失效 → delete 旧 + create 新
```

---

## 七、SOUL — 用户对 Agent 的角色定义

### 7.1 什么是 SOUL

SOUL 是**用户通过对话定义的 Agent 角色和行为准则**。用户告诉 Agent "你是什么、你要怎么做"，Agent 提取并持久化为 SOUL，在每次会话开始时注入 system prompt。

```
用户对话中的 SOUL 定义示例:
  "你是我的数据分析助理，帮我整理专业的数据分析总结"
  "回复要简洁，不超过100字"
  "你不要主动推荐产品，只回答我问的问题"
  "遇到不确定的先确认，不要猜测"

提取后的 SOUL:
  "你是用户的数据分析助理，帮助整理专业的数据分析总结。
   回复简洁不超过100字，不主动推荐产品，只回答用户提问。
   遇到不确定的先确认，不要猜测。"
```

### 7.2 SOUL 与 profile / preferences 的区别

```
SOUL:        用户定义 Agent 的角色（"你是..."、"你要..."）
profile:     用户描述自己的身份（"我是..."）
preferences: 用户表达自己的偏好（"我喜欢..."）

示例:
  "你是我的销售助理"        → soul（定义 Agent）
  "我是销售总监"            → profile（描述用户）
  "我喜欢表格展示"          → preferences（用户偏好）
  "你回复要简洁不超过100字"  → soul（约束 Agent）
  "你不要主动推荐产品"       → soul（约束 Agent）
```

### 7.3 触发和更新

```
触发条件: 对话中提取到 category="soul" 的记忆时立即触发
更新方式: LLM 合并已有 SOUL + 新增定义（矛盾时以新增为准）
存储: PG（merge_key="soul"，每用户一条）+ 内存缓存
```

### 7.4 注入位置

```
system prompt 结构:

┌─────────────────────────────────┐
│ CRM_SYSTEM_PROMPT（通用规范）     │  ← 工具使用、安全边界、输出格式
├─────────────────────────────────┤
│ <user_soul>                      │  ← SOUL 注入（用户定义的 Agent 角色）
│   你是用户的数据分析助理...        │
│ </user_soul>                     │
├─────────────────────────────────┤
│ <memory_context>                 │  ← 记忆检索注入（本轮相关记忆）
│   [entities] 华为/ERP: 张伟和李娜有分歧
│ </memory_context>                │
└─────────────────────────────────┘
```

### 7.1 什么是 SOUL（原始设计，仅供参考）

SOUL 不是一条记忆，是从所有零散记忆中**持续蒸馏**出来的结构化用户模型。它回答一个核心问题：**Agent 在新会话开始时，不看任何历史消息，仅凭 SOUL 就能知道"我在跟谁说话、他关心什么、他习惯什么"。**

与零散记忆的区别：

```
零散记忆（可能有 50-200 条）:
  [preferences] 数据展示偏好: 表格格式
  [preferences] 回复风格偏好: 简洁，给结论
  [entities] 华为科技: 3个商机780万
  [entities] 华为科技/张总: CTO
  [entities] 华为科技/ERP升级: 500万，谈判
  [events] 2026-04-28 华为ERP评审通过
  [patterns] 每周一查Pipeline
  ...

SOUL（蒸馏后，~500 tokens）:
  一份结构化 JSON，注入 system prompt
  Agent 从第一轮就"认识"用户
```

### 7.2 SOUL 数据结构

```json
{
  "identity": {
    "role": "华东区销售总监",
    "team": "15人团队",
    "region": "华东区",
    "expertise": "互联网行业大客户",
    "tech_level": "熟悉CRM基本操作，不熟悉数据分析函数"
  },
  "preferences": {
    "display": "表格展示",
    "language": "中文",
    "style": "简洁，给结论不要长篇分析",
    "amount_format": "万为单位，不要小数",
    "default_scope": "默认只看自己负责的数据"
  },
  "key_accounts": [
    {"name": "华为科技", "summary": "3商机780万，关键联系人张总(CTO)，ERP项目下周评审"},
    {"name": "网易", "summary": "2商机800万，丁总同意报价，下周签约"},
    {"name": "小米集团", "summary": "2商机2450万，IoT平台和智能工厂"}
  ],
  "active_tasks": [
    "华为ERP项目下周三评审",
    "网易合同下周签约",
    "小米IoT项目等待报价确认"
  ],
  "work_patterns": [
    "每周一查看Pipeline",
    "先查schema再查数据",
    "习惯按阶段统计商机"
  ]
}
```

### 7.3 SOUL 的 5 个字段来源

| SOUL 字段 | 来源记忆类别 | 蒸馏逻辑 |
|:---|:---|:---|
| identity | profile | 直接取 profile 记忆的最新内容 |
| preferences | preferences | 聚合所有 aspect 的偏好，每个 aspect 取最新值 |
| key_accounts | entities（parent_entity="" 的顶层客户） | 取 Top-5 高频客户，每个客户汇总商机数、金额、关键联系人 |
| active_tasks | events（最近 30 天） | 提取未完成的计划/待办，按时间排序取最近 3 个 |
| work_patterns | patterns + tools + skills | 提炼 3-5 条行为模式 |

### 7.4 触发条件

```
触发条件 1: 首次生成
  → 用户的记忆总数首次达到 5 条时，生成第一版 SOUL

触发条件 2: 增量更新
  → 自上次 SOUL 更新后，新增记忆数 >= soul_threshold（默认 5）

触发条件 3: 强制更新
  → profile 或 preferences 类记忆有新增（身份/偏好变更直接影响画像）

不触发:
  → 只有 tools 类记忆新增（工具统计不影响画像）
  → 记忆总数 < 5 条（数据不足，画像质量低）
```

### 7.5 生成流程

```
Step 1: 收集原料
  ├── 从向量库检索该用户所有记忆的 L0 摘要
  ├── 按 8 类分组:
  │     profile: ["用户为华东区销售总监..."]
  │     preferences: ["数据展示偏好: 表格", "回复风格偏好: 简洁"]
  │     entities: ["华为科技: 3商机780万", "腾讯: 2商机2000万", ...]
  │     events: ["2026-04-28 华为ERP评审通过", ...]
  │     patterns: ["每周一查Pipeline", ...]
  │     tools: ["query_data: 调用42次，成功率95%", ...]
  │     skills: ["Pipeline报告: 阶段统计→负责人统计→环比", ...]
  └── 如果已有旧版 SOUL，一并作为输入

Step 2: LLM 蒸馏（单次调用，用 flash 模型降低成本）
  ├── 系统提示词: SOUL_PROMPT
  ├── 输入: 分类后的记忆列表 + 旧版 SOUL（如有）
  ├── 输出: 结构化 JSON（~500 tokens）
  └── 模型: doubao-seed-1-6-flash（最快最便宜，~$0.0003/次）

Step 3: 存储
  ├── 存入本地内存缓存: self._soul_cache[user_id] = soul_json
  └── 缓存命中率高（同一用户的多次会话复用同一份 SOUL）

Step 4: 注入
  └── 下次会话开始时，MemoryMiddleware.abefore_agent() 调用 engine.get_soul(user_id)
      → 返回 "<user_soul>\n{soul_json}\n</user_soul>"
      → 注入 system prompt
```

### 7.6 SOUL 与零散记忆的协作

```
SOUL 和 memory_context 不是替代关系，而是互补:

SOUL（~500 tokens，会话开始时一次性注入）:
  → 回答"用户是谁" — 身份、偏好、重点客户、行为模式
  → 让 Agent 从第一轮就个性化
  → 相对稳定，不随每轮对话变化

memory_context（~300-500 tokens，每轮检索注入）:
  → 回答"与当前问题相关的历史" — 具体的商机数据、联系人电话、上次讨论的结论
  → 随用户问题动态变化
  → 来自向量库的语义检索

两者配合的效果:
  用户: "查一下华为的情况"

  Agent 看到的上下文:
    SOUL → 用户是华东区销售总监，偏好表格展示，华为是重点客户(3商机780万)
    memory_context → [entities] 华为/ERP升级: 500万谈判, [entities] 华为/张总: CTO

  Agent 的回复:
    → 知道用户是销售总监（来自 SOUL.identity）→ 侧重管理视角
    → 用表格展示（来自 SOUL.preferences）
    → 直接展示 3 个商机详情（来自 memory_context）
    → 提醒"ERP项目下周评审"（来自 SOUL.active_tasks）
```

### 7.7 SOUL 注入位置

```
system prompt 结构:

┌─────────────────────────────────┐
│ CRM_SYSTEM_PROMPT（角色定义）     │  ← 固定，~2000 tokens
├─────────────────────────────────┤
│ <user_soul>                      │  ← SOUL 注入，~500 tokens
│   {                              │
│     "identity": {...},           │
│     "preferences": {...},        │
│     "key_accounts": [...],       │
│     "active_tasks": [...],       │
│     "work_patterns": [...]       │
│   }                              │
│ </user_soul>                     │
├─────────────────────────────────┤
│ <skills>（技能段落）              │  ← 动态，按需注入
├─────────────────────────────────┤
│ <memory_context>                 │  ← 本轮检索记忆，~300-500 tokens
│   [entities] 华为/ERP: 500万谈判  │
│   [entities] 华为/张总: CTO       │
│ </memory_context>                │
└─────────────────────────────────┘

总 system prompt: ~3000-3500 tokens（对 32K 窗口的模型，占比 ~10%）
```

### 7.8 SOUL 存储形式

```
SOUL 本身也是一条记忆，存储在向量库中:

  category:      "soul"（特殊类别）
  abstract:      "用户画像: 华东区销售总监，偏好表格展示，重点客户华为/网易/小米"
  overview:       ""（SOUL 不需要 L1）
  content:       完整的 SOUL JSON 字符串
  merge_key:     "soul"（固定，每用户 1 条）
  parent_entity: ""
  user_id:       用户 ID

但生产中优先从内存缓存读取（self._soul_cache），
只有缓存未命中时才从向量库检索 category="soul" 的记忆。
```

### 7.9 SOUL 成本

```
单次 SOUL 生成:
  输入: ~2000 tokens（50-100 条记忆的 L0 摘要）
  输出: ~500 tokens（SOUL JSON）
  模型: doubao-seed-1-6-flash
  成本: ~$0.0003/次
  耗时: ~1-2s

触发频率: 每 5 条新记忆触发一次，约每 2-3 个会话一次

月均成本（100 个用户）:
  100 × 30 次/月 × $0.0003 = $0.9/月（可忽略）
```

---

## 八、记忆遗忘策略

### 8.1 各类别保留天数

| 类别 | 保留天数 | 说明 |
|:---|:---|:---|
| profile | 永不遗忘 | 用户身份是核心画像 |
| preferences | 永不遗忘 | 偏好需要长期保持 |
| entities | 180 天 | 客户/商机信息半年后可能过时 |
| events | 90 天 | 事件 3 个月后时效性降低 |
| cases | 180 天 | 案例经验半年内有参考价值 |
| patterns | 365 天 | 工作模式相对稳定 |
| tools | 365 天 | 工具经验长期有效 |
| skills | 365 天 | 技能策略长期有效 |

### 8.2 遗忘条件

```
过期 AND 低热度:
  age_days > retention_days AND active_count < 3
  → 删除

过期 BUT 高热度:
  age_days > retention_days AND active_count >= 3
  → 保留（经常被检索到的记忆即使过期也有价值）
```

---

## 九、反思修正机制

### 9.1 失败驱动反思 `reflect_on_failure()`

```
触发: Agent 任务失败后
流程:
  1. 检索本轮对话中被使用的记忆
  2. LLM 分析失败原因是否与某条记忆有关
  3. 如果有 → 删除错误记忆
```

### 9.2 用户反馈反思 `reflect_on_correction()`

```
触发: 用户说"不对"/"错了"/"改一下"
流程:
  1. 检索与纠正内容相关的记忆
  2. LLM 判断哪些记忆需要修正或删除
  3. 执行修正
```

### 9.3 会话结束反思 `reflect_on_session()`

参考 OpenViking 的 `post_session_reflection` 设计。在每次 `extract_and_update` 完成后异步调用。

```
触发: extract_and_update 完成后（异步，不阻塞主流程）
输入: 本次提取的新记忆列表 + user_id

流程:
  1. 对每条新记忆，检索已有的相似记忆（排除本次写入的）
  2. 过滤高相似度候选（score > 0.7）
  3. LLM 判断关系类型:
     - no_conflict: 无矛盾，信息互补 → 不处理
     - contradiction: 直接矛盾（偏好改变、事实更正）→ 需要解决
     - evolution: 信息演进（旧信息过时但不矛盾）→ 需要解决
     - duplicate: 重复信息 → 需要解决
  4. 对每个冲突，LLM 决定解决方案:
     - update_old: 用合并内容更新旧记忆
     - archive_old: 归档旧记忆，保留新记忆
     - keep_both: 两者都保留
     - discard_new: 丢弃新记忆

返回: {"checked": N, "conflicts": N, "resolved": N, "actions": [...]}

示例:
  新记忆: "华为ERP项目金额800万，谈判阶段"
  已有记忆: "华为ERP项目金额500万，谈判阶段"
  → 关系: evolution（金额从500万调整为800万）
  → 解决: update_old（用800万更新旧记忆）
```

### 9.4 定期全局反思 `reflect_global()`

参考 OpenViking 的 `weekly_global_reflection` 设计。建议每天或每周执行一次。

```
触发: 定时任务（每天/每周）或手动调用

Step 1: 碎片化检测与合并
  ├── 遍历向量库中所有类别（entities/events/cases/patterns）
  ├── 按 merge_key 分组
  ├── 同 merge_key 超过 1 条 → LLM 合并为 1 条
  └── 删除旧碎片，写入合并后的新条目

Step 2: 一致性检查（profile vs preferences）
  ├── 从 PG 获取 profile 和 preferences
  ├── LLM 检查两者是否矛盾
  └── 记录不一致项（不自动修复，留给人工确认）

Step 3: 过时检测
  └── 调用 cleanup_expired() 清理过期 + 低热度记忆

返回: {"merged": N, "inconsistencies": N, "stale_marked": N}
```

---

## 九-B、VikingFS 虚拟文件系统

### 9B.1 设计目标

参考 OpenViking 的文件系统范式，用 PG + 向量库模拟目录树结构。不是真正的文件系统，而是基于 URI 路径的记忆组织层，提供统一的记忆浏览和导航能力。

### 9B.2 URI 格式

```
viking://{space}/memories/{category}/{parent}/{name}

  space:    "user"（profile/preferences/entities/events）
            "agent"（cases/patterns/tools/skills）
  category: 8 类之一
  parent:   父实体（可选，如 "华为科技"）
  name:     记忆名（可选，如 "ERP升级项目"）
```

### 9B.3 目录结构示例

```
viking://user/memories/
├── profile: 华东区销售总监，管理15人团队
├── preferences/
│   ├── 数据展示偏好: 表格格式
│   └── 回复风格偏好: 简洁，给结论
├── entities/
│   ├── 华为科技/ (5 条)
│   │   ├── ERP升级项目: 金额500万，谈判阶段
│   │   ├── 云迁移项目: 金额200万，方案阶段
│   │   └── 张总: CTO，139-xxxx
│   └── 腾讯/ (3 条)
└── events/
    └── 2026-04-28_华为ERP评审通过

viking://agent/memories/
├── cases/
│   └── 查询报错_字段名拼写
├── patterns/
│   └── 客户360分析流程
├── tools/
│   └── query_data: 调用42次，成功率95%
└── skills/
    └── Pipeline报告
```

### 9B.4 操作接口

| 操作 | 方法 | 说明 |
|:---|:---|:---|
| ls | `VikingFS.ls(uri)` | 列出目录下的直接子条目 |
| tree | `VikingFS.tree(uri, max_depth)` | 递归展示目录树（文本格式） |
| read | `VikingFS.read(uri, level)` | 读取指定 URI 的记忆（L0/L1/L2） |
| find | `VikingFS.find(pattern)` | 按关键词搜索所有记忆 |
| rm | `VikingFS.rm(uri)` | 删除指定 URI 的记忆 |

### 9B.5 存储路由

```
VikingFS 在 PG 和向量库之上提供统一视图:

  PG 类别（精确查询）:
    profile / soul / tools / skills
    → MemoryDAO.get_by_user_category() 查询

  向量库类别（语义检索）:
    entities / events / cases / patterns / preferences
    → VectorStore.query_by_filter() 查询
```

### 9B.6 与 VikingMemoryEngine 的集成

```python
# 获取 FS 实例
fs = engine.get_fs(user_id="u1")

# 展示目录树
print(engine.tree(user_id="u1"))

# 通过 URI 读取记忆
node = engine.read_uri("u1", "viking://user/memories/entities/华为科技/ERP升级项目")

# 关键词搜索
results = engine.find_by_keyword("u1", "华为")
```

---

## 九-C、记忆与系统数据一致性

### 9C.1 问题分析

当前 entities 类记忆用**客户名称**做 merge_key 和 parent_entity，存在两个根本性问题：

**问题 1：系统数据变更 → 记忆过时**

```
时间线:
  T1: 对话中提取记忆 → "华为科技/ERP升级: 金额500万，谈判阶段"
  T2: 销售在 CRM 系统中修改了商机金额 → 800万
  T3: 用户问 "华为ERP项目多少钱" → Agent 检索到记忆 → 回答 "500万"（错误！）

根因: 记忆存的是对话时刻的数据快照，不是系统数据的引用
```

**问题 2：实体重命名 → 记忆孤儿**

```
时间线:
  T1: 记忆中有 5 条 parent_entity="华为科技" 的记忆
  T2: 管理员在 CRM 中把客户名改为 "深圳华为科技"
  T3: 用户问 "深圳华为科技的商机" → 向量库 filter parent_entity="深圳华为科技" → 0 条命中
      用户问 "华为科技的商机" → 命中 5 条，但客户名已经不对了

根因: merge_key 和 parent_entity 用的是名称字符串，不是系统 ID
```

### 9C.2 记忆应该记什么 vs 不应该记什么

这是核心设计决策。entities 类记忆不应该做系统数据的镜像，而应该记录**对话中产生的增量认知**：

```
❌ 不应该记的（系统已有的结构化数据）:
  "华为科技/ERP升级: 金额500万，谈判阶段"
  → 这些数据在 CRM 系统中已经存在，Agent 可以实时查询
  → 存成记忆 = 存了一份会过时的快照

✅ 应该记的（对话中产生的、系统中没有的增量认知）:
  "华为科技/ERP升级: 张总倾向选方案B，对价格敏感，建议不要主动提折扣"
  "华为科技/张总: 喜欢先看数据再讨论，不喜欢PPT，每次会议控制在30分钟内"
  "华为科技: 内部审批流程复杂，至少需要3周，建议提前准备材料"
  → 这些是销售在对话中透露的主观判断、沟通技巧、隐性知识
  → CRM 系统中没有这些字段，只有记忆系统能存
```

### 9C.3 解决方案：双锚点 + 分层存储

```
方案核心:
  1. entities 记忆绑定系统 record_id（不依赖名称字符串）
  2. 区分"系统数据摘要"和"增量认知"两种记忆类型
  3. 系统数据变更时通过 Webhook 级联更新记忆
```

#### 方案 A：record_id 锚定（推荐）

在 entities 记忆中增加 `biz_id` 字段，绑定 CRM 系统的 record_id：

```
当前存储:
  merge_key:     "华为科技/ERP升级"      ← 名称字符串，会过时
  parent_entity: "华为科技"              ← 名称字符串，会过时

改进后存储:
  merge_key:     "华为科技/ERP升级"      ← 仍然保留（用于人类可读的目录展示）
  parent_entity: "华为科技"              ← 仍然保留（用于目录展示）
  biz_id:        "opp_12345"            ← 新增：CRM 系统的 record_id（不变的锚点）
  biz_parent_id: "acc_67890"            ← 新增：父实体的 record_id
  biz_type:      "opportunity"          ← 新增：业务实体类型

检索时:
  优先用 biz_id filter（精确匹配，不受改名影响）
  fallback 到 merge_key / parent_entity（兼容无 biz_id 的旧记忆）
```

#### 方案 B：增量认知 vs 数据摘要分离

```
entities 记忆拆成两个子类型:

  entities_summary（数据摘要）:
    来源: 工具返回的结构化数据
    特点: 会过时，需要定期刷新或标记 TTL
    示例: "华为科技/ERP升级: 金额500万，谈判阶段"
    TTL:  24小时（过期后下次检索时实时查询系统数据替代）

  entities_insight（增量认知）:
    来源: 对话中的主观判断、隐性知识
    特点: 不会因系统数据变更而失效
    示例: "华为科技/ERP升级: 张总倾向方案B，对价格敏感"
    TTL:  180天（正常遗忘策略）

检索时:
  entities_summary → 检查 TTL，过期则标记为 stale，提示 Agent 实时查询
  entities_insight → 正常返回，不受系统数据变更影响
```

#### 方案 C：实体重命名级联更新

```
CRM 系统 Webhook → 记忆系统:

  事件: 客户名称变更（华为科技 → 深圳华为科技）
  │
  ▼
  记忆系统收到 rename 事件:
    1. 查询所有 biz_parent_id = "acc_67890" 的记忆
    2. 批量更新:
       parent_entity: "华为科技" → "深圳华为科技"
       merge_key: "华为科技/ERP升级" → "深圳华为科技/ERP升级"
       abstract: 替换文本中的 "华为科技" → "深圳华为科技"
       重新 embed(abstract) → 更新 vector
    3. 记录一条 events 记忆:
       "2026-04-28 客户华为科技更名为深圳华为科技"
```

### 9C.4 推荐实施路径

```
Phase 1（短期，改提取逻辑）:
  ├── 修改 EXTRACTION_PROMPT，要求 LLM 区分"数据摘要"和"增量认知"
  ├── 数据摘要类记忆标记 source_type="system_data"，设置短 TTL
  ├── 增量认知类记忆标记 source_type="insight"，正常 TTL
  └── 检索时对 stale 的数据摘要标记 [可能已过时]

Phase 2（中期，加 biz_id 锚定）:
  ├── 提取时从 ToolMessage 中解析 record_id
  │   （工具返回的数据通常包含 id 字段）
  ├── 存储时写入 biz_id / biz_parent_id / biz_type
  ├── 检索时优先用 biz_id filter
  └── 向量库 collection 增加 biz_id filter index

Phase 3（长期，Webhook 级联）:
  ├── CRM 系统数据变更时发送 Webhook
  ├── 记忆系统接收 Webhook，级联更新相关记忆
  ├── 实体重命名时批量更新 merge_key / parent_entity / abstract
  └── 重新 embed 更新后的 abstract
```

### 9C.5 提取提示词改进

```
当前 EXTRACTION_PROMPT 的问题:
  LLM 会把工具返回的结构化数据（金额、阶段、电话）原样提取为记忆
  这些数据在 CRM 系统中已经存在，存成记忆是冗余且会过时的

改进方向:
  1. 明确告诉 LLM: 不要提取系统中已有的结构化字段值
  2. 重点提取: 用户的主观判断、沟通策略、隐性知识、关系洞察
  3. 对于必须提取的数据摘要，标记 source_type

改进后的提取规则（增加到 EXTRACTION_PROMPT）:

  ## 提取优先级
  - 高优先级（必须提取）:
    用户的主观判断: "张总对价格很敏感"
    沟通策略: "建议先展示ROI再谈价格"
    关系洞察: "张总和李经理有分歧，需要分别沟通"
    隐性知识: "华为内部审批至少3周"
    用户偏好: "喜欢表格展示"

  - 低优先级（可选提取，标记 source_type="system_data"）:
    实体属性快照: "ERP项目金额500万"
    联系人信息: "张总电话139-xxxx"
    → 这些数据系统中已有，提取时标记为数据摘要

  - 不提取:
    工具返回的原始数据（"查到5条记录..."）
    操作描述（"用户请求查询..."）
    通用知识
```

### 9C.6 各场景处理方式

| 场景 | 当前行为 | 改进后行为 |
|:---|:---|:---|
| 商机金额变更 | 记忆过时，Agent 回答旧数据 | 数据摘要 TTL 过期 → Agent 实时查询系统 |
| 客户名称变更 | 记忆孤儿，检索不到 | biz_id 锚定 → 不受改名影响；Webhook 级联更新名称 |
| 联系人离职 | 记忆中仍有旧联系人 | 数据摘要 TTL 过期 → 不再返回；insight 类记忆保留（"张总喜欢先看数据"仍有参考价值） |
| 商机关闭 | 记忆中仍显示"谈判阶段" | 数据摘要 TTL 过期；events 记忆记录"商机已关闭" |
| 新增商机 | 需要对话才能产生记忆 | 数据摘要可选同步；insight 仍需对话产生 |

---

## 十、存储架构

### 10.1 向量库 Collection Schema

```
Collection: agent_memories
  Fields:
    id:             String (PRIMARY_KEY)
    vector:         Vector (2560维, HNSW, COSINE)
    sparse_vector:  SparseVector (BM25, SPARSE_INVERTED, IP)
    abstract:       String          ← 叶子: LLM 提取的 L0 摘要 / 目录: 系统聚合的 L0
    overview:       String          ← 叶子: 空 / 目录: 系统聚合的 L1 结构化导航
    content:        String          ← 叶子: 完整记忆内容 / 目录: 空
    category:       String (FILTER) ← entities / preferences
    merge_key:      String          ← 合并键
    parent_entity:  String (FILTER) ← 父实体（叶子有，目录为空）
    parent_uri:     String (FILTER) ← 父目录 URI
    uri:            String          ← 自身 URI
    is_leaf:        String (FILTER) ← "true" / "false"
    status:         String (FILTER) ← active / stale / archived
    user_id:        String (FILTER) ← 用户隔离
    source_type:    String          ← insight / system_data
    thread_id:      String          ← 来源会话
    created_at:     String          ← 创建时间
    updated_at:     String          ← 更新时间
```

### 10.2 PG 存储

**agent_memory 表**（profile / agent_rules 权威存储，每用户各一条）：

```
表: agent_memory
  user_id         VARCHAR(64)
  category        VARCHAR(32)   ← "profile" / "agent_rules"
  merge_key       VARCHAR(256)  ← 固定 "profile" / "agent_rules"
  abstract        TEXT          ← 自动生成的摘要
  content         TEXT          ← LLM 合并后的完整内容
  唯一约束: (user_id, category, merge_key)
```

**ai_agent_memory 表**（全量记忆，前端展示 + 生命周期管理）：

```
表: ai_agent_memory
  memory_id       VARCHAR(64)   ← 和向量库 id 一致
  tenant_id       BIGINT
  user_id         VARCHAR(64)
  category        VARCHAR(32)   ← 所有类别都写入
  abstract        TEXT          ← L0 摘要
  content         TEXT          ← 完整内容
  merge_key       VARCHAR(512)
  parent_entity   VARCHAR(256)
  status          VARCHAR(20)   ← active / stale / archived / deleted
  last_accessed_at BIGINT       ← 最后被检索命中的时间（驱动遗忘）
  active_count    INT           ← 累计命中次数
  user_query      TEXT          ← 产生这条记忆的用户问题
  agent_reply     TEXT          ← 产生这条记忆的 AI 回复
  vector_id       VARCHAR(64)   ← 向量库中的文档 ID
```

### 10.3 数据流全景

```
┌─────────────────────────────────────────────────────────────┐
│                        对话层                                 │
│  用户输入 → Agent 回复 → middleware aafter_agent              │
└────────────────────────────┬────────────────────────────────┘
                             │
                    ┌────────▼────────┐
                    │   LLM 提取       │
                    │ (abstract+content│
                    │  +merge_key      │
                    │  +parent_entity) │
                    └────────┬────────┘
                             │
              ┌──────────────┼──────────────┐
              │              │              │
     ┌────────▼───┐  ┌──────▼──────┐  ┌───▼────────────┐
     │ PG 存储     │  │ 向量库存储   │  │ 目录聚合        │
     │ (profile/   │  │ (叶子节点)   │  │ (_ensure_dir)  │
     │  agent_rules│  │ abstract    │  │ 收集叶子content │
     │  单条合并)   │  │ content     │  │ → LLM 生成 L0  │
     └─────────────┘  │ vector      │  │ → LLM 生成 L1  │
                      │ merge_key   │  │ → 写入目录节点  │
                      └──────┬──────┘  └────────────────┘
                             │
                    ┌────────▼────────┐
                    │ ai_agent_memory  │
                    │ (全量同步，      │
                    │  前端展示+       │
                    │  生命周期管理)    │
                    └─────────────────┘


┌─────────────────────────────────────────────────────────────┐
│                        检索层                                 │
│  用户查询 → hybrid_search → 命中目录+叶子 → 返回 L0 摘要      │
│  → Agent 按需 memory_read(L1/L2) → 返回详情                  │
│  → 异步更新 PG（last_accessed_at + active_count）            │
└─────────────────────────────────────────────────────────────┘
```

---

## 十一、与 apps-agent（OpenViking）的对比

### 11.1 已对齐的能力

| 能力 | apps-agent | VikingMemoryEngine | 状态 |
|:---|:---|:---|:---|
| 9 类分类 | ✅ (8类) | ✅ (9类，新增 soul) | 已对齐 + 扩展 |
| L0/L1/L2 三层 | ✅ | ✅ | 已对齐（L1 由 LLM 生成） |
| 语义去重 + LLM 合并 | ✅ | ✅ | 已对齐 |
| profile 增量合并 | ✅ | ✅ | 已对齐 |
| preferences 按 aspect 合并 | ✅ | ✅ | 已对齐 |
| tools/skills 统计 | ✅ | ✅ | 已对齐（Python 统计） |
| filter index | ✅ | ✅ | 已对齐（user_id + category + parent_entity） |
| BM25 混合检索 | ✅ | ✅ | 已对齐（tcvectordb hybrid_search） |
| 记忆遗忘 | ✅ | ✅ | 已对齐（TTL + 热度） |
| 反思修正 | ✅ | ✅ | 已对齐（失败驱动 + 用户反馈 + 会话结束 + 全局） |
| 虚拟文件系统 | ✅ VikingFS | ✅ VikingFS | 已对齐（viking:// URI + ls/tree/read/find/rm） |
| 会话结束反思 | ✅ post_session_reflection | ✅ reflect_on_session | 已对齐 |
| 定期全局反思 | ✅ weekly_global_reflection | ✅ reflect_global | 已对齐 |

### 11.2 我们独有的能力

| 能力 | 说明 |
|:---|:---|
| 预过滤 | 寒暄/确认/工具失败跳过，节省 ~30% LLM 调用 |
| SOUL 蒸馏 | 从所有记忆中定期生成结构化用户画像 |
| CRM 领域适配 | 提取指令针对客户/商机/联系人/合同做了专门优化 |
| BM25 混合检索 | 关键词 0.7 + 向量 0.3，CRM 场景客户名精确匹配 |
| 分层加载 | 检索返回 L0 摘要，Agent 按需加载 L1/L2 |

### 11.3 未实现的能力

| 能力 | apps-agent | 原因 | 影响 |
|:---|:---|:---|:---|
| active_count 持久化 | 向量库 filter index | tcvectordb Int64 字段兼容性问题 | 热度统计暂存内存，重启丢失 |
| entities 合并用 LLM 生成 | LLM 生成合并内容 | 当前是直接替换 | 合并质量可进一步提升 |
| tools 统计含耗时和 token | 包含 latency 和 token 消耗 | 当前只统计调用次数和成功率 | 可后续补充 |

---

## 十二、成本估算

```
单次对话的记忆成本:

  预过滤: 0（纯代码规则）
  LLM 提取: ~800 tokens input + ~300 tokens output = ~$0.0002
  工具统计: 0（纯 Python）
  语义去重: ~500 tokens（仅 events/cases 触发）= ~$0.0001
  Embedding: ~100 tokens × 3 条 = ~$0.00003
  向量库写入: 免费（腾讯向量库按存储计费）

  单次对话总成本: ~$0.0003

月均成本（100 个销售用户，每人每天 30 次对话）:
  100 × 30 × 30 × $0.0003 = $27/月

SOUL 蒸馏（额外）:
  100 × 30 × $0.0003 = $0.9/月

总计: ~$28/月（可忽略）
```

---

## 十三、实现文件清单

```
src/memory/
  ├── viking_engine.py      ← 主引擎（~1500行）
  │     ├── MemoryCategory      9 类分类枚举（含 soul）
  │     ├── MemoryRecord        记忆数据结构
  │     ├── EXTRACTION_PROMPT   提取提示词
  │     ├── DEDUP_PROMPT        去重提示词
  │     ├── INTENT_PROMPT       意图分析提示词
  │     ├── SOUL_PROMPT         SOUL 蒸馏提示词
  │     ├── VectorStore         腾讯向量库操作封装
  │     └── VikingMemoryEngine  主引擎类
  │           ├── extract_and_update()      写入（预过滤 + LLM 提取 + 去重合并 + 会话反思）
  │           ├── retrieve()                检索（意图分析 + BM25 混合 + 热度更新）
  │           ├── rewrite_query()           查询改写
  │           ├── get_soul()                获取 SOUL 画像
  │           ├── cleanup_expired()         记忆遗忘
  │           ├── reflect_on_failure()      失败驱动反思
  │           ├── reflect_on_correction()   用户反馈反思
  │           ├── reflect_on_session()      会话结束反思（冲突检测 + 解决）
  │           ├── reflect_global()          定期全局反思（碎片合并 + 一致性 + 过时）
  │           ├── get_fs()                  获取 VikingFS 实例
  │           ├── tree()                    展示记忆目录树
  │           ├── read_uri()               通过 URI 读取记忆
  │           └── find_by_keyword()         关键词搜索
  │
  ├── viking_fs.py          ← 虚拟文件系统（~400行）
  │     ├── VikingURI           URI 解析结果
  │     ├── parse_uri()         解析 viking:// URI
  │     ├── build_uri()         从记忆字段构建 URI
  │     ├── FSNode              文件系统节点
  │     └── VikingFS            虚拟文件系统操作
  │           ├── ls()          列出目录下的直接子条目
  │           ├── tree()        递归展示目录树
  │           ├── read()        读取指定路径的记忆
  │           ├── find()        路径前缀搜索
  │           └── rm()          删除
  │
  ├── fts_engine.py         ← 降级引擎（已有，~600行）
  ├── mem0_engine.py        ← Mem0 适配器（已有，可逐步废弃）
  ├── storage.py            ← SQLite FTS5 存储（已有）
  └── __init__.py           ← 导出 VikingMemoryEngine

src/store/
  ├── memory_dao.py         ← PG 记忆存储（profile/soul/tools/skills）
  │     ├── MemoryRow           PG 记忆行数据模型
  │     └── MemoryDAO           CRUD 操作
  │           ├── upsert()              写入/更新（profile 追加合并，其他按 merge_key 替换）
  │           ├── get_by_user_category() 按用户+类别查询
  │           ├── get_profile()          获取用户 profile
  │           ├── get_soul()             获取用户 SOUL
  │           ├── get_all_for_soul()     获取所有 PG 记忆（SOUL 蒸馏用）
  │           └── count_by_user()        按类别统计
  └── pg_pool.py            ← PG 连接池

tests/
  ├── test_viking_full.py           ← 完整测试（14 功能点 × 5+ 用例）
  └── test_viking_directory_search.py ← 目录递归检索 Demo
```

---

> 参考来源:
> - Wiki: [会话管理&记忆管理](https://wiki.ingageapp.com/pages/viewpage.action?pageId=152089637)（apps-agent OpenViking 设计）
> - Wiki: [Agent记忆应用设计](https://wiki.ingageapp.com/pages/viewpage.action?pageId=152099787)
> - 项目: `src/memory/viking_engine.py`（实现代码）
> - 项目: `product-specs/long-term-memory/长期记忆技术实现方案.md`（早期设计）
> - 项目: `product-specs/long-term-memory/Mem0-OpenViking-FTSMemoryEngine-源码级深度对比.md`（框架对比）
