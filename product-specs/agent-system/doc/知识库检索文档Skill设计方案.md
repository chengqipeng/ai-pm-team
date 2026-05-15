# 知识库检索文档 Skill 设计方案

> 基于现有知识库检索引擎（KnowledgeRetriever）+ Skill 管理体系，设计一个面向终端用户的「知识库文档检索」Skill。
> 与 `knowledge_search` Tool 的关系：Tool 是原子能力，Skill 是编排策略。

---

## 一、设计背景

### 1.1 现状分析

当前系统中，Agent 通过 `knowledge_search` Tool 调用知识库检索能力。这个 Tool 提供了：
- 自然语言查询 → Self-Querying 自动提取过滤条件
- 多路并行召回（切片 hybrid + 文档元数据 hybrid）
- 三维度归一化加权排序（α 相关性 + β 元数据 + γ 文档属性）
- Parent-Child 上下文扩展

**问题**：Tool 只是原子能力，Agent 在使用时缺乏明确的检索策略指导：
1. 首次检索无结果时，Agent 不知道如何降级/重试
2. 多文档结果时，Agent 不知道如何综合分析和对比
3. 输出格式不统一，有时只是简单罗列，缺乏结构化呈现
4. 缺少引用溯源，用户无法追踪信息来源

### 1.2 Skill 的价值

Skill 在 Tool 之上提供**编排策略**：

```
用户查询
    │
    ▼
┌─────────────────────────────────────────────┐
│ knowledge-doc-search Skill                   │
│                                              │
│  ┌─────────────┐    ┌─────────────────────┐ │
│  │ 意图分析     │───→│ 策略选择             │ │
│  │ (查询理解)   │    │ (精准/渐进/对比)     │ │
│  └─────────────┘    └──────────┬──────────┘ │
│                                 │            │
│  ┌──────────────────────────────▼──────────┐ │
│  │ 工具调用编排                              │ │
│  │ ├─ knowledge_search (1~3 次)             │ │
│  │ └─ list_knowledge_bases (按需)           │ │
│  └──────────────────────────────┬──────────┘ │
│                                 │            │
│  ┌──────────────────────────────▼──────────┐ │
│  │ 结果综合分析 + 结构化输出                  │ │
│  │ ├─ 核心发现摘要                           │ │
│  │ ├─ 详细内容 + 引用溯源                    │ │
│  │ └─ 建议 + 追问方向                        │ │
│  └─────────────────────────────────────────┘ │
└─────────────────────────────────────────────┘
    │
    ▼
结构化回答（带来源标注）
```

### 1.3 与现有组件的关系

| 组件 | 层级 | 职责 | 本 Skill 的关系 |
|------|------|------|----------------|
| KnowledgeRetriever | 引擎层 | 多路召回 + 加权排序 | 底层能力，不直接调用 |
| KnowledgeSearchTool | Tool 层 | 封装 Provider.search 为 LangChain Tool | Skill 通过此 Tool 调用检索 |
| knowledge-doc-search Skill | Skill 层 | 编排策略 + 结果分析 + 输出格式化 | **本方案** |
| Agent | 应用层 | 意图路由 + Skill 调度 | 根据 when_to_use 触发本 Skill |

---

## 二、Skill 定义

### 2.1 元数据

| 字段 | 值 | 说明 |
|------|-----|------|
| api_key | `knowledge-doc-search` | 唯一标识 |
| name | 知识库文档检索 | 展示名 |
| category | crm | 分类（知识库服务于 CRM 业务） |
| context | inline | 内联执行，共享主 Agent 上下文 |
| risk_level | read_only | 只读操作，无副作用 |
| max_tool_calls | 8 | 最多 8 次工具调用（覆盖渐进式检索场景） |
| timeout_ms | 30000 | 30 秒超时 |
| allowed_tools | knowledge_search, list_knowledge_bases | 允许的工具 |
| arguments | query, knowledge_base_id | 输入参数 |

### 2.2 触发条件（when_to_use）

```
知识检索|文档查找|知识库搜索|查资料|找文档|产品手册|技术文档|解决方案|
成功案例|FAQ|操作指南|培训材料|白皮书|竞品分析|帮我找|有没有关于|查一下
```

覆盖场景：
- 显式检索意图：「帮我找一下关于 XX 的文档」「查一下 XX 的资料」
- 文档类型触发：「有没有 XX 的产品手册」「XX 的成功案例」
- 隐式知识需求：「XX 怎么安装」「XX 的技术参数是什么」（Agent 判断需要查知识库时触发）

### 2.3 参数设计

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| query | string | 是 | 用户的检索问题（自然语言） |
| knowledge_base_id | int | 否 | 指定知识库 ID，不指定则全库检索 |

**为什么不暴露更多参数？**

`knowledge_search` Tool 本身支持 `doc_category`、`industry`、`business_stage`、`target_audience` 等过滤参数，但 Skill 层不直接暴露这些参数给用户，原因：
1. Self-Querying 已经能从自然语言中自动提取过滤条件
2. 用户不需要知道底层的 Schema 字段名
3. Skill 的 prompt 会指导 LLM 在调用 Tool 时自动填充这些参数

---

## 三、执行策略详解

### 3.1 策略选择逻辑

```
用户查询
    │
    ├─ 意图明确 + 关键词清晰？
    │   └─ 是 → 策略 1: 单次精准检索
    │
    ├─ 包含对比/比较关键词？（"区别"、"对比"、"哪个好"、"优缺点"）
    │   └─ 是 → 策略 3: 多角度对比检索
    │
    └─ 其他 → 策略 1 → 结果不足时自动升级为策略 2
```

### 3.2 策略 1: 单次精准检索

**适用场景**：
- 「3051 压力变送器的安装步骤」
- 「CRM 系统的审批流配置方法」
- 「制造业的成功案例」

**执行流程**：
```
1. 分析查询 → 提取意图
2. knowledge_search(query="{query}", top_k=5)
3. 结果 ≥ 2 条且 top_score ≥ 0.5 → 直接输出
4. 结果 < 2 条或 top_score < 0.5 → 升级为策略 2
```

**工具调用次数**：1 次

### 3.3 策略 2: 渐进式检索

**适用场景**：
- 首次检索结果不理想
- 查询比较模糊或口语化
- 专业术语可能有多种表述

**执行流程**：
```
1. 首次检索（原始查询）
2. 结果不足 → 选择补充策略：
   a. 去掉隐含的过滤条件，扩大范围
      knowledge_search(query="{query}", top_k=8)  // 不带 category 等
   b. 同义词替换
      knowledge_search(query="{同义词改写}", top_k=5)
   c. 拆解子问题
      knowledge_search(query="{子问题1}", top_k=3)
      knowledge_search(query="{子问题2}", top_k=3)
3. 合并所有结果，按 score 去重排序
4. 输出综合分析
```

**工具调用次数**：2~4 次

### 3.4 策略 3: 多角度对比检索

**适用场景**：
- 「A 产品和 B 产品的区别」
- 「各解决方案的优缺点对比」
- 「不同行业的实施案例对比」

**执行流程**：
```
1. 拆解对比维度
   - "A 和 B 的区别" → 查询 A、查询 B
   - "各方案优缺点" → 查询方案1、查询方案2、查询方案3
2. 分别检索
   knowledge_search(query="A 的特点和优势", top_k=3)
   knowledge_search(query="B 的特点和优势", top_k=3)
3. 对比分析，输出表格
```

**工具调用次数**：2~6 次

---

## 四、与知识库检索引擎的协作

### 4.1 检索链路全景

```
Skill 层                          Tool 层                         引擎层
┌──────────────┐                ┌──────────────┐              ┌──────────────────────┐
│ Skill Prompt │                │ knowledge_   │              │ KnowledgeRetriever   │
│ 指导 LLM     │──调用──→      │ search Tool  │──委托──→     │                      │
│ 选择策略     │                │              │              │ Step 1: 查询改写      │
│ 编排调用     │                │ 参数校验     │              │ Step 2: Self-Querying │
│ 分析结果     │                │ Provider注入 │              │ Step 3: 多路召回      │
│ 格式化输出   │                │ 结果格式化   │              │ Step 4: Hydrate+扩展  │
└──────────────┘                └──────────────┘              │ Step 5: 三维度加权    │
                                                              │ Step 6: 过滤+排序     │
                                                              │ Step 7: 审计日志      │
                                                              └──────────────────────┘
```

### 4.2 Skill 层 vs Tool 层的职责边界

| 职责 | Skill 层 | Tool 层 |
|------|----------|---------|
| 查询理解 | 分析用户意图，决定检索策略 | — |
| 查询改写 | — | 引擎内部自动完成（多轮指代消解） |
| Self-Querying | — | 引擎内部自动完成（LLM 提取 filter） |
| 过滤条件 | 根据策略决定是否传入显式 filter | 接收 filter 参数传给引擎 |
| 多次检索 | 编排多次 Tool 调用 | 每次调用独立执行 |
| 结果分析 | 综合多次结果，提炼核心信息 | 单次结果格式化为 Markdown |
| 输出格式 | 结构化报告（摘要+详情+建议） | 原始检索结果列表 |
| 引用溯源 | 标注来源文档和章节 | 返回 document_title + section_title |

### 4.3 检索参数优化

Skill 在调用 `knowledge_search` 时的参数选择策略：

| 场景 | top_k | 过滤参数 | 说明 |
|------|-------|----------|------|
| 精准检索 | 5 | 不传（让 Self-Querying 自动识别） | 默认策略 |
| 扩大范围 | 8~10 | 不传 | 首次结果不足时 |
| 指定类别 | 5 | doc_category | 用户明确说了文档类型 |
| 指定行业 | 5 | industry | 用户明确说了行业 |
| 对比检索 | 3 | 按角度不同 | 每个角度少量但精准 |

### 4.4 与 Schema 动态注入的配合

`KnowledgeSearchTool.get_dynamic_description()` 会根据租户 Schema 生成带受控词表的描述。Skill 执行时，LLM 能看到这些受控词，从而在调用 Tool 时使用正确的枚举值。

示例：如果租户 Schema 定义了 `docCategory` 枚举值包含「产品手册」「成功案例」「技术白皮书」，LLM 在 Skill 执行过程中会自动使用这些标准值作为过滤条件。

---

## 五、输出质量保障

### 5.1 信息准确性

Skill prompt 中明确要求：
- **只基于检索到的文档内容回答**，不编造信息
- 如果检索结果无法回答用户问题，明确告知而非猜测
- 区分「文档中明确提到」和「基于文档推断」

### 5.2 引用溯源机制

每个信息点标注来源：
```
📄 来源：{document_title} | 章节：{section_title} | 相关度：{score}
```

这些信息来自 `KnowledgeChunk` 的字段：
- `document_title`：文档标题
- `section_title`：章节标题（来自 Segment 切分时的标题提取）
- `section_path`：章节路径（如 "第二章 技术参数 / 2.1 量程范围"）
- `score`：三维度加权后的最终相关度分数

### 5.3 结果质量判断

Skill 内部的质量判断逻辑：

| 指标 | 阈值 | 处理 |
|------|------|------|
| 结果数量 | < 2 | 触发渐进式检索 |
| 最高分数 | < 0.5 | 提示用户结果可能不够精准 |
| 最高分数 | < 0.35 | 视为无有效结果 |
| 结果间分数差 | top1 - top2 > 0.3 | 重点展示 top1，其余简略 |

---

## 六、与 Skill 管理体系的集成

### 6.1 注册方式

通过 `init.sql` 写入 `ai_skill_definition` 表，系统启动时 `SkillRegistry.load_from_db()` 自动加载。

### 6.2 运行时行为

```
Agent Loop
    │
    ├─ 用户消息匹配 when_to_use 关键词
    │   └─ SkillRouter 选中 knowledge-doc-search
    │
    ├─ SkillExecutor 执行
    │   ├─ context=inline → 在主 Agent 上下文中执行
    │   ├─ 注入 Skill prompt 到 system message
    │   ├─ allowed_tools 限制为 [knowledge_search, list_knowledge_bases]
    │   └─ max_tool_calls=8 限制调用次数
    │
    └─ 执行完成 → 写 ai_skill_exec_log
```

### 6.3 监控指标

| 指标 | 来源 | 用途 |
|------|------|------|
| 执行次数 | ai_skill_exec_log | 使用频率 |
| 平均耗时 | ai_skill_exec_log.duration_ms | 性能监控 |
| 成功率 | success_count / exec_count | 质量监控 |
| 工具调用次数 | exec_log.tool_call_count | 成本控制 |
| 检索命中率 | ai_knowledge_search_log | 检索效果 |

---

## 七、未来演进

### 7.1 短期优化（1-2 迭代）

1. **检索反馈闭环**：用户对结果点赞/踩 → 写入 `ai_knowledge_search_log.feedback` → 优化排序权重
2. **热门查询缓存**：高频查询结果缓存 5 分钟，减少重复检索
3. **多知识库路由**：根据查询内容自动选择最相关的知识库

### 7.2 中期增强（3-4 迭代）

1. **Agentic RAG 深度集成**：
   - 检索结果不足时，自动触发「追问式检索」（生成追问 → 再检索 → 合并）
   - 支持多跳推理（A 文档提到 B → 自动检索 B 的详情）
2. **文档级摘要生成**：
   - 对整篇文档生成结构化摘要（而非只返回切片）
   - 支持「帮我总结这篇文档」的场景
3. **检索+生成混合**：
   - 检索到相关切片后，基于切片内容生成完整回答
   - 类似 RAG 的 Generate 阶段，但由 Skill 编排

### 7.3 长期方向

1. **个性化检索**：基于用户历史查询和角色，调整检索权重
2. **知识图谱增强**：文档间关系图谱，支持关联推荐
3. **多模态检索**：支持图片、表格的语义检索

---

## 八、输出深度优化设计（v4.0）

> 本节描述 v4.0 新增的输出形式智能选择 + 引用溯源链接化设计。

### 8.1 设计目标

1. **输出形式与用户语义匹配**：不同查询意图产出不同格式（对比表格 / 参数列表 / 概述段落 / 步骤指引 / 诊断方案）
2. **信息来源强制引用**：每个关键信息点标注来源编号，末尾统一输出可点击的引用链接
3. **引用链接可跳转**：前端渲染为超链接，点击可跳转到原文档对应章节

### 8.2 语义类型判定

Skill prompt 中定义了 5 种语义类型，由 LLM 在执行时自动判定：

| 语义类型 | 触发关键词 | 输出形式 | 示例查询 |
|----------|-----------|----------|----------|
| 对比型 | 对比、区别、哪个好、vs、优缺点、选型 | 多列对比表格 | "3051 和 3095 的区别" |
| 参数查询型 | 参数、规格、量程、精度、尺寸 | 参数表格 | "3051 的技术参数" |
| 概述型 | 介绍、是什么、概述、了解 | 结构化段落 | "阿牛巴流量计是什么" |
| 操作指引型 | 怎么、如何、步骤、安装、配置 | 编号步骤列表 | "3051 怎么安装" |
| 问题诊断型 | 故障、报错、不工作、异常 | 原因+方案 | "3051 显示异常怎么办" |

### 8.3 对比型输出的深度逻辑

**触发条件**（满足任一）：
- 用户提到 2 个及以上产品/型号/方案名称
- 使用了对比类关键词
- 问"有哪些产品适合 XX 场景"（隐含多产品对比）

**检索策略**：
```
1. 拆解对比对象（A、B、...）
2. 分别检索：
   knowledge_search(query="A 特点 参数 优势", top_k=3)
   knowledge_search(query="B 特点 参数 优势", top_k=3)
3. 合并结果，按对比维度组织
```

**输出结构**：
```markdown
[一句话核心结论]

| 对比维度 | 产品A | 产品B |
|----------|-------|-------|
| 适用场景 | ...[^1] | ...[^2] |
| 核心参数 | ...[^1] | ...[^2] |
| 优势     | ...[^1] | ...[^2] |
| 局限     | ...[^1] | ...[^2] |

**选型建议**：[明确推荐]

---
📚 **信息来源**

[^1]: [产品A手册](/knowledge/doc/{doc_id}#section=技术规格) — 第3章 技术规格
[^2]: [产品B手册](/knowledge/doc/{doc_id}#section=产品概述) — 第1章 产品概述
```

### 8.4 引用溯源链接化设计

#### 8.4.1 数据流

```
KnowledgeChunk
  ├── document_id      → 构建链接路径 /knowledge/doc/{doc_id}
  ├── document_title   → 链接显示文本
  ├── section_title    → 锚点 #section={section_title}
  └── section_path     → 补充描述（如 "第2章 / 2.1 安装要求"）

Tool._format_results()
  └── 输出 <!-- ref: doc_id=xxx title=xxx section=xxx --> 注释标记
  └── 输出 ### 📚 引用索引 结构化列表

Skill Prompt
  └── 指导 LLM 使用 [^N] 行内标注 + 末尾引用列表
  └── 引用格式：[^N]: [文档标题](/knowledge/doc/{doc_id}#section={section}) — 章节路径
```

#### 8.4.2 前端渲染

引用链接在前端 Markdown 渲染器中被解析为：
- `[^N]` → 上标数字，hover 显示来源摘要
- `/knowledge/doc/{doc_id}#section={section}` → 点击跳转到文档详情页对应章节

#### 8.4.3 引用规则

| 规则 | 说明 |
|------|------|
| 强制标注 | 每个关键数据/结论必须标注来源编号 |
| 末尾汇总 | 所有引用源在回答最末尾统一列出 |
| 可点击 | 每条引用是 Markdown 链接格式 |
| 去重复用 | 同一文档同一章节只分配一个编号 |
| 不确定标注 | 推断性内容标注"（基于文档推断）" |

### 8.5 与 output_mode 的关系

knowledge-doc-search Skill 的 `output_mode` 固定为 `text`，所有输出通过 TEXT_MESSAGE 三段式推送到前端 ChatBubble 的 Markdown 渲染器。

Markdown 渲染器需要支持：
- 标准表格渲染（对比表格、参数表格）
- 脚注语法 `[^N]` 渲染为上标链接
- 内部链接 `/knowledge/doc/...` 渲染为可点击跳转

### 8.6 变更清单

| 文件 | 变更 | 说明 |
|------|------|------|
| `skills/definitions/knowledge-doc-search/SKILL.md` | 重写 | v4.0 prompt：语义类型判定 + 输出形式规则 + 引用规范 |
| `src/tools/builtins/knowledge_tool.py` | `_format_results` 增强 | 输出引用元数据注释 + 结构化引用索引 |
| 前端 MarkdownRenderer | 待开发 | 支持脚注语法 + 内部链接跳转 |

---

## 九、文件清单

| 文件 | 路径 | 说明 |
|------|------|------|
| SQL 迁移（v4.0） | `sql/migrate_knowledge_skill_v4_output_optimization.sql` | 直接更新 DB 中的 prompt/配置 |
| SQL 初始化 | `sql/migrate_add_knowledge_doc_search_skill.sql` | 首次安装（v1.0） |
| 设计文档 | `doc/知识库检索文档Skill设计方案.md` | 本文档 |
| 依赖 Tool | `src/tools/builtins/knowledge_tool.py` | knowledge_search Tool |
| 文档详情 Tool | `src/tools/builtins/knowledge_doc_detail_tool.py` | knowledge_doc_detail Tool |
| 检索引擎 | `src/knowledge/retriever.py` | KnowledgeRetriever |
| Provider | `src/knowledge/standalone_provider.py` | StandaloneKnowledgeProvider |

> ⚠️ 注意：Skill 定义的唯一数据源是 `ai_skill_definition` 数据库表。
> 所有变更通过 SQL 迁移脚本直接更新 DB，不再维护本地 SKILL.md 文件。
> 运行时通过 `SkillRegistry.load_from_db()` 加载。
