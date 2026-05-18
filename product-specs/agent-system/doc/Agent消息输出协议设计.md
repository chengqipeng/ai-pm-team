# Agent 消息输出协议设计

> 版本：v1.0
> 日期：2026-05-18
> 对齐：`AGUI-A2UI-协议层设计.md` §2.2 / `Skill输出渲染标准设计.md`
> 对应代码：`src/agui/converter.py`、`src/tools/skills_tool.py`

---

## 一、设计目标

解决 Agent 系统中"谁输出什么内容、通过什么通道、前端如何呈现"的体系化问题。

### 1.1 当前痛点

| 问题 | 根因 |
|------|------|
| fork skill 结果重复输出 | 子 Agent 直出 + 主 Agent LLM 重复，两条路径竞争 |
| 输出归属不清 | 没有明确定义"这段内容应该由谁负责输出" |
| LLM 不遵守指令 | 靠 prompt 让 LLM "不要重复"是不可靠的 |
| LangGraph 事件重复 | `astream_events(v2)` 对 custom event 在多层级产出 |

### 1.2 设计原则

| 原则 | 含义 |
|------|------|
| 生产者输出 | 谁生产内容谁负责输出，不经 LLM 中继转述 |
| 主 Agent 是协调者 | 主 Agent 决定"调谁"和"调完后做什么"，不负责重新加工子 Agent 产物 |
| 协议层去重 | 去重在 converter 代码层实现，不依赖 LLM 行为 |
| 事件幂等 | 同一业务输出无论收到几次事件，前端只收到一条消息 |

---

## 二、三类产出者与归属规则

### 2.1 产出者定义

| 产出者 | 执行环境 | 典型场景 |
|--------|----------|----------|
| **主 Agent LLM** | LangGraph react loop 中的 LLM 节点 | 直接回答、inline skill 推理后输出、协调性引导 |
| **子 Agent（fork skill）** | 独立子 Agent 通过 `agent.ainvoke()` 执行 | 客户洞察报告、数据分析、深度检索 |
| **Inline Skill** | 主 Agent LLM 收到 SOP prompt 后继续推理 | 配置校验、元数据查询、简单诊断 |

### 2.2 归属判定规则

**一句话判定**：

> 子 Agent 输出 = 内容本身就是交付物（报告/数据/分析结果）
>
> 主 Agent 输出 = 对交付物的协调性补充（引导/总结/追问/拒绝）

**详细判定表**：

| 场景 | 输出者 | 输出内容 | 理由 |
|------|--------|----------|------|
| 用户简单问候/闲聊 | 主 Agent | 直接回复 | 无需调 skill |
| 用户问题主 Agent 可直接回答 | 主 Agent | 推理结论 | 主 Agent 有足够能力 |
| 触发 inline skill | 主 Agent | 基于 SOP 推理后的最终回答 | inline 只注入指令，输出仍归主 Agent |
| 触发 fork skill（报告类） | 子 Agent | 完整报告 | 独立生产的专业交付物 |
| fork skill 完成后的引导语 | 主 Agent | "需要我深入分析吗？" | 协调性输出 |
| 多步任务（先检索再分析） | 子 Agent A + B | 各自结果 | 各 Agent 独立产出 |
| 多步任务完成后的汇总 | 主 Agent | 汇总总结 | 跨子 Agent 的综合判断 |
| 需要确认/追问 | 主 Agent | 确认问题 | 交互协调是主 Agent 职责 |

---

## 三、输出内容协议

### 3.1 协议结构

每次 fork skill 执行完成后，输出内容被拆分为两个明确部分：

```
┌────────────────────────────────────────────────────────┐
│  Part A: 子 Agent 产出（skill_output）                   │
│                                                        │
│  完整的、自包含的业务交付物                               │
│  特征：                                                 │
│  - 独立可读，无需附加说明                                │
│  - 格式化完整（有标题、有结构、有结论）                    │
│  - 内容由子 Agent 的专业能力决定                         │
│  - 不包含交互引导语（不说"还有什么需要帮助"）             │
│  - 不包含给主 Agent 的元指令                             │
│                                                        │
│  输出通道：on_custom_event("skill_result") → 直出       │
│  渲染形式：由 output_mode 决定                           │
└────────────────────────────────────────────────────────┘

┌────────────────────────────────────────────────────────┐
│  Part B: 主 Agent 补充（agent_followup）                 │
│                                                        │
│  协调性补充，取决于 post_output_behavior：               │
│                                                        │
│  silent    → 无输出（Part B 为空）                       │
│  summarize → 1-2 句引导                                 │
│  continue  → 决策下一步（可能调另一个 skill）             │
│                                                        │
│  特征：                                                 │
│  - 简短（< 100 字）                                     │
│  - 不包含子 Agent 已产出的内容                           │
│  - 是对用户的引导/过渡，不是内容本身                      │
│                                                        │
│  输出通道：on_chat_model_stream → TEXT_MESSAGE           │
│  渲染形式：始终为文本                                    │
└────────────────────────────────────────────────────────┘
```

### 3.2 前端消息呈现示例

**场景：客户洞察（silent 模式）**

```
┌─────────────────────────────────────────┐
│ 用户: 洞察华为科技                        │
├─────────────────────────────────────────┤
│ [子 Agent] TEXT_MESSAGE                  │
│                                         │
│ # 华为科技客户洞察报告                    │
│ ## 企业概况                              │
│ 华为技术有限公司...                       │
│ ## 行动建议                              │
│ 1. 跟进 ERP 项目                         │
│ 2. ...                                  │
│                                         │
│ （无主 Agent 补充 — silent 模式）         │
└─────────────────────────────────────────┘
```

**场景：知识检索（summarize 模式）**

```
┌─────────────────────────────────────────┐
│ 用户: 华为的 5G 产品线有哪些？            │
├─────────────────────────────────────────┤
│ [子 Agent] TEXT_MESSAGE                  │
│                                         │
│ ## 检索结果                              │
│ 找到 3 篇相关文档：                       │
│ 1. 华为 5G 产品白皮书 (相关度 0.92)       │
│ 2. ...                                  │
│                                         │
├─────────────────────────────────────────┤
│ [主 Agent] TEXT_MESSAGE                  │
│                                         │
│ 以上是检索到的相关文档，需要我深入         │
│ 分析某篇的具体内容吗？                    │
└─────────────────────────────────────────┘
```

**场景：多步任务（continue 模式）**

```
┌─────────────────────────────────────────┐
│ 用户: 先查华为资料再做 BANT 评估          │
├─────────────────────────────────────────┤
│ [子 Agent A] TEXT_MESSAGE                │
│ ## 检索结果 ...                          │
├─────────────────────────────────────────┤
│ [子 Agent B] TEXT_MESSAGE                │
│ ## BANT 评估 ...                         │
├─────────────────────────────────────────┤
│ [主 Agent] TEXT_MESSAGE                  │
│ 以上完成了资料检索和 BANT 评估两步。      │
└─────────────────────────────────────────┘
```

---

## 四、`post_output_behavior` 选择标准

### 4.1 决策树

```
子 Agent 产出内容
  │
  ├─ 内容是完整交付物，有结论/行动建议？
  │   ├─ YES → 用户看完不需要追问引导？
  │   │         ├─ YES → silent
  │   │         └─ NO  → summarize
  │   └─ NO  → 内容是中间结果，后续还要处理？
  │             ├─ YES → continue
  │             └─ NO  → passthrough
  │
  └─ 内容太短（< 500字）不适合独立展示？
      └─ YES → passthrough
```

### 4.2 各模式详解

#### `silent` — 子 Agent 输出即最终答案

- **判定**：产出是完整自包含交付物，有明确的结论/建议章节
- **场景**：客户洞察报告、Pipeline 分析、诊断报告
- **主 Agent 行为**：完全沉默，不产出任何文本
- **前端效果**：用户看到一条完整消息

#### `summarize` — 子 Agent 输出后需要引导

- **判定**：产出是信息列表/检索结果，用户后续操作有多种可能
- **场景**：知识库检索、相关客户推荐、竞品对比初筛
- **主 Agent 行为**：产出 1-2 句引导语
- **前端效果**：报告 + 一条简短引导

#### `continue` — 多步任务中的一步

- **判定**：当前结果不是最终交付物，是下一步的输入
- **场景**：先检索再分析、批量操作后验证
- **主 Agent 行为**：决策是否调用下一个 skill
- **前端效果**：可能紧跟下一个 skill 执行

#### `passthrough` — 不直出，回传主 Agent

- **判定**：产出太短/不适合独立展示/需要融入主 Agent 回答
- **场景**：字段校验结果、简单数据查询、参数提取
- **主 Agent 行为**：收到完整结果，自行组织语言输出
- **前端效果**：用户只看到主 Agent 的一条回复

### 4.3 Skill 配置参考

| Skill | context | output_mode | post_output_behavior |
|-------|---------|-------------|---------------------|
| accountInsight | fork | text | silent |
| knowledge_doc_search | fork | text | summarize |
| pipeline_analysis | fork | table | silent |
| data_analysis | fork | table | silent |
| batch_cleanup | fork | text | continue |
| verify_config | inline | text | — (不适用) |
| diagnose | inline | text | — (不适用) |
| inspect_metamodel | inline | text | — (不适用) |

---

## 五、输出边界契约

### 5.1 子 Agent 输出契约

子 Agent 的 prompt 中必须包含以下约束：

```
你的输出将直接展示给用户。请遵守以下规则：
1. 直接输出结构化内容，不要说"以下是报告"之类的前缀
2. 不要在末尾追问"还有什么需要帮助"
3. 确保输出格式完整（Markdown 标题闭合、表格完整）
4. 不要包含给系统的元指令
```

验证规则：

| 规则 | 说明 |
|------|------|
| self_contained | 独立可读，不依赖对话上下文 |
| has_structure | 有标题/章节/结论 |
| no_meta_instructions | 不包含给主 Agent 的指令 |
| no_user_interaction | 不包含交互引导语 |
| format_complete | Markdown 格式闭合完整 |

### 5.2 主 Agent 输出契约（post-skill）

| 规则 | silent | summarize | continue |
|------|--------|-----------|----------|
| 最大长度 | 0 字 | 100 字 | 200 字 |
| 可包含子 Agent 内容 | 否 | 否 | 否 |
| 可调用新 tool | 否 | 否 | 是 |
| 目的 | — | 引导追问 | 决策下一步 |

### 5.3 Inline Skill 输出契约

| 规则 | 说明 |
|------|------|
| output_owner = main_agent | 最终输出归属主 Agent |
| may_call_tools = true | LLM 可调用 allowed_tools |
| no_dispatch_event = true | 不使用 dispatch_custom_event 绕行 |
| 输出形式由 LLM 决定 | 根据 SOP prompt 自行组织 |

---

## 六、事件层协议

### 6.1 `skill_result` 事件结构

```json
{
  "name": "skill_result",
  "data": {
    "skill_apikey": "accountInsight",
    "behavior": "silent",
    "output_mode": "text",
    "content": "# 完整报告...",
    "summary": "华为科技洞察报告...（共2800字）",
    "metadata": {
      "execution_ms": 12500,
      "sub_agent": "account-insight",
      "tool_calls_count": 6
    }
  }
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| skill_apikey | string | 是 | Skill 唯一标识 |
| behavior | enum | 是 | silent / summarize / continue / passthrough |
| output_mode | enum | 是 | text / card / component / table |
| content | string | 是 | 子 Agent 完整产出 |
| summary | string | 否 | 摘要（供主 Agent 参考） |
| metadata | object | 否 | 执行元数据 |

### 6.2 Tool 返回值标记协议

```
格式：[SKILL_DONE:{behavior}] {skill_apikey} {description}
```

示例：
```
[SKILL_DONE:silent] accountInsight 已将完整结果（2797字）直接输出给用户。不要输出任何内容，直接结束本轮对话。
[SKILL_DONE:summarize] knowledge_doc_search 已将结果输出。摘要：找到3篇文档。请给出简短引导。
[SKILL_DONE:continue] data_analysis 已将结果输出。你可以继续调用其他工具。
```

此标记双重作用：
1. 给 **converter** 在 `_handle_tool_end` 中解析 → 设置行为状态
2. 给 **LLM** 看到后遵守行为指令（作为辅助，不是唯一依赖）

### 6.3 事件类型与归属映射

| 事件 | 产出者 | converter 处理 |
|------|--------|---------------|
| `on_custom_event("skill_result")` | 子 Agent（SkillsTool dispatch） | `_handle_skill_result` → 直出 + 设 flag |
| `on_chat_model_stream` | 主 Agent LLM | `_emit_text` → 受 flag 控制 |
| `on_custom_event("agent_text")` | 旧兼容路径 | 去重检查后透传或跳过 |
| `on_tool_end` 含 `[SKILL_DONE:*]` | SkillsTool 返回值 | 解析标记 → 确认/设置 flag |

---

## 七、Converter 状态机

### 7.1 状态定义

```
┌─────────────────┐
│    NORMAL       │ ← 初始状态 / 新 tool_call 时重置
│                 │
│ _emit_text: 正常│
└───┬────────┬────┘
    │        │
    │        │ on_tool_start (新 tool_call)
    │        └─────────────────────────────┐
    │                                      │
    │  skill_result(silent)                │
    │  或 tool_end 检测到 [SKILL_DONE:silent]
    ▼                                      │
┌─────────────────┐                        │
│ HARD_SUPPRESS   │                        │
│                 │                        │
│ _emit_text: 丢弃│                        │
│ agent_text: 丢弃│                        │
└───────┬─────────┘                        │
        │                                  │
        │ on_tool_start / run_end          │
        └──────────────────────────────────┘
                      │
                      ▼
              ┌─────────────────┐
              │    NORMAL       │
              └─────────────────┘
```

### 7.2 去重机制

```python
# 基于 content hash 的幂等性
self._last_skill_output_hash = hash(content)

# 触发去重的场景：
# 1. LangGraph 对同一 dispatch 在不同层级产出多次 on_custom_event
# 2. skill_result 和 agent_text 携带相同内容
# 3. LLM 在 on_chat_model_stream 中重复子 Agent 内容
```

### 7.3 状态重置条件

| 条件 | 动作 |
|------|------|
| 新 `on_tool_start` / `tool_call_chunks` 首次出现 | 重置为 NORMAL |
| `RUN_FINISHED` | 重置为 NORMAL |
| 超时（预留） | 重置为 NORMAL |

---

## 八、完整时序图

### 8.1 Silent 模式

```
User        主Agent LLM      SkillsTool      子Agent      Converter      前端
 │               │               │              │             │            │
 │ "洞察华为科技" │               │              │             │            │
 │──────────────>│               │              │             │            │
 │               │ tool_call     │              │             │            │
 │               │──────────────>│              │             │            │
 │               │               │ ainvoke()    │             │            │
 │               │               │─────────────>│             │            │
 │               │               │              │(执行,生成)   │            │
 │               │               │    result    │             │            │
 │               │               │<─────────────│             │            │
 │               │               │                            │            │
 │               │               │ dispatch("skill_result")   │            │
 │               │               │───────────────────────────>│            │
 │               │               │                            │ TEXT_MSG   │
 │               │               │                            │───────────>│
 │               │               │                            │ (报告)     │
 │               │               │                            │            │
 │               │               │                            │ 设置       │
 │               │               │                            │ HARD_SUP   │
 │               │               │                            │            │
 │               │ "[SKILL_DONE: │                            │            │
 │               │  silent]..."  │                            │            │
 │               │<──────────────│                            │            │
 │               │               │              on_tool_end   │            │
 │               │               │              ─────────────>│            │
 │               │               │              确认HARD_SUP  │            │
 │               │               │                            │            │
 │               │ "以上是..."   │                            │            │
 │               │ (LLM不遵守)  │                            │            │
 │               │──────────────────────────────────────────>│            │
 │               │               │                            │ SUPPRESSED │
 │               │               │                            │ (丢弃)     │
 │               │               │                            │            │
 │               │ end_turn      │                            │            │
 │               │──────────────────────────────────────────>│            │
 │               │               │                            │ RUN_FINISH │
 │               │               │                            │───────────>│
```

### 8.2 Summarize 模式

```
User        主Agent LLM      SkillsTool      子Agent      Converter      前端
 │               │               │              │             │            │
 │ "查华为5G资料" │               │              │             │            │
 │──────────────>│               │              │             │            │
 │               │ tool_call     │              │             │            │
 │               │──────────────>│              │             │            │
 │               │               │─────────────>│             │            │
 │               │               │    result    │             │            │
 │               │               │<─────────────│             │            │
 │               │               │                            │            │
 │               │               │ dispatch("skill_result",   │            │
 │               │               │  behavior="summarize")     │            │
 │               │               │───────────────────────────>│            │
 │               │               │                            │ TEXT_MSG_1 │
 │               │               │                            │───────────>│
 │               │               │                            │ (检索结果)  │
 │               │               │                            │            │
 │               │               │                            │ 设置       │
 │               │               │                            │ SOFT_SUP   │
 │               │               │                            │            │
 │               │ "[SKILL_DONE: │                            │            │
 │               │  summarize]"  │                            │            │
 │               │<──────────────│                            │            │
 │               │               │                            │            │
 │               │ "需要我深入   │                            │            │
 │               │  分析吗？"    │                            │            │
 │               │──────────────────────────────────────────>│            │
 │               │               │                            │ TEXT_MSG_2 │
 │               │               │                            │───────────>│
 │               │               │                            │ (引导语)   │
```

---

## 九、数据模型

### 9.1 SkillDefinition 新增字段

```python
@dataclass
class SkillDefinition:
    ...
    output_mode: str = "text"                    # text | card | component | table | streaming | auto
    component_apikey: str = ""                   # output_mode=component 时的目标组件
    post_output_behavior: str = "silent"         # silent | summarize | continue | passthrough
```

### 9.2 DDL

```sql
ALTER TABLE ai_skill_definition
ADD COLUMN IF NOT EXISTS post_output_behavior VARCHAR(20) NOT NULL DEFAULT 'silent';

COMMENT ON COLUMN ai_skill_definition.post_output_behavior IS
  'Fork skill 输出后主 Agent 行为: silent | summarize | continue | passthrough';
```

### 9.3 output_mode × post_output_behavior 组合矩阵

| output_mode | post_output_behavior | 子 Agent 渲染 | 主 Agent 行为 |
|-------------|---------------------|--------------|--------------|
| text + silent | Markdown 气泡 | 沉默 |
| text + summarize | Markdown 气泡 | 1-2 句引导 |
| text + continue | Markdown 气泡 | 继续决策 |
| card + silent | 折叠文档卡片 | 沉默 |
| component + silent | A2UI 组件 | 沉默 |
| table + silent | 数据表格 | 沉默 |
| table + summarize | 数据表格 | 简评 |
| * + passthrough | 不直出 | LLM 正常输出 |

---

## 十、各层职责边界

| 层 | 职责 | 不做什么 |
|----|------|---------|
| **SkillDefinition** | 声明 output_mode + post_output_behavior | 不负责具体输出逻辑 |
| **SkillsTool** | dispatch skill_result 事件，构造 [SKILL_DONE:*] 标记 | 不负责渲染/去重 |
| **SkillExecutor** | 路由 inline/fork 执行，返回结果 | 不关心输出形式 |
| **AGUIConverter** | 唯一输出决策点：去重 + 状态机 + 通道选择 | 不修改内容本身 |
| **ProgressiveRenderer** | 组件匹配 + 渲染状态管理 | 只处理 component 模式 |
| **前端** | 按事件类型渲染 | 不做去重/过滤/业务判断 |

---

## 十一、与旧 SSE 模式的差异

| 维度 | 旧 SSE 模式 (`/api/chat`) | AG-UI 模式 (`/api/chat/agui`) |
|------|--------------------------|------------------------------|
| 输出通道 | 单一 token 流 | 结构化事件流（多 message_id） |
| fork skill 输出 | server.py `on_tool_end` 手动分块推送 | converter `skill_result` 事件直出 |
| 去重 | 不需要（单通道） | 必须（content hash） |
| 行为控制 | 依赖 LLM prompt | converter 状态机确定性抑制 |
| 前端感知 | 混在同一流中 | 每条消息独立 message_id 和语义 |

---

## 十二、未来演进

| 方向 | 当前状态 | 后续规划 |
|------|----------|----------|
| Skill 中间进度 | 未实现 | 新增 `skill_progress` 事件（loading/percentage） |
| 多 Agent 并发 | 串行 | 并发时需要消息排序 + 合并展示 |
| 用户打断 | 未实现 | cancel 机制 + 清除 pending 输出 |
| 输出质量反馈 | 未实现 | 前端采集 👍👎 → 调整 behavior 配置 |
| A2UI 融合 | 独立通道 | skill_result 可携带 surfaceUpdate 操作 |
