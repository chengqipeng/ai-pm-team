# Skill 输出 — 前后端 UI 显示规范

> 定义 Skill 执行结果从后端产出到前端渲染的完整链路规范。
> 所有业务 Skill 统一遵循本规范，确保输出形式可预期、可控制。
> 对齐 `AGUI-A2UI-协议层设计.md` §2.3 ModelName 分流 + §4.5 Renderer 五层匹配。

---

## 一、总体架构

```
┌─────────────────────────────────────────────────────────────────────────┐
│                          后端（Python）                                   │
│                                                                          │
│  Skill 执行完成                                                           │
│       │                                                                  │
│       ▼                                                                  │
│  ┌──────────────────────────────────────────────────────────────────┐   │
│  │ output_mode 路由器（AGUIConverter._handle_skill_end）              │   │
│  │                                                                    │   │
│  │  output_mode=text ──────→ TEXT_MESSAGE 三段式                      │   │
│  │  output_mode=streaming ─→ TEXT_MESSAGE 逐 chunk 流式              │   │
│  │  output_mode=card ──────→ CUSTOM(component_complete, doc_card)    │   │
│  │  output_mode=component ─→ CUSTOM(component_complete) + STATE_DELTA│   │
│  │  output_mode=table ─────→ CUSTOM(component_data, searchResults)   │   │
│  │  output_mode=auto ──────→ 按规则动态选择上述之一                   │   │
│  └──────────────────────────────────────────────────────────────────┘   │
│       │                                                                  │
│       ▼                                                                  │
│  SSE 事件流 → 前端                                                        │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                          前端（TypeScript/React）                          │
│                                                                          │
│  AG-UI EventDispatcher                                                   │
│       │                                                                  │
│       ├─ TEXT_MESSAGE_* ──────→ ChatBubble（Markdown 渲染器）             │
│       ├─ CUSTOM(component_complete) ──→ A2UI SurfaceRenderer             │
│       │     ├─ apikey=doc_card ──→ DocumentCard 组件                     │
│       │     └─ apikey=其他 ──────→ CatalogRegistry 查找 → 业务组件       │
│       ├─ CUSTOM(component_data) ──→ DataRenderer（表格/列表/链接卡片）    │
│       ├─ STATE_DELTA ─────────→ SharedState 更新（静默，不触发新 UI）     │
│       └─ ACTIVITY_SNAPSHOT ───→ A2UI Bridge → SurfaceStore              │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## 二、output_mode 与 AG-UI 事件的映射关系

### 2.1 完整映射表

| output_mode | 后端产出的 AG-UI 事件序列 | 前端渲染组件 | 用户体验 |
|-------------|--------------------------|-------------|----------|
| `text` | `TEXT_MESSAGE_START` → `TEXT_MESSAGE_CONTENT`×N → `TEXT_MESSAGE_END` | ChatBubble + MarkdownRenderer | 直接在对话气泡中看到格式化文本（表格/列表/代码块） |
| `streaming` | `TEXT_MESSAGE_START` → `TEXT_MESSAGE_CONTENT`×N（逐字）→ `TEXT_MESSAGE_END` | ChatBubble + StreamingText | 逐字出现的打字机效果，适合长回答 |
| `card` | `CUSTOM("component_complete", {apikey:"doc_card", data:{title,summary,content}})` | DocumentCard | 折叠卡片：标题+摘要+「点击查看全文」按钮 |
| `component` | `CUSTOM("component_loading")` → `CUSTOM("component_complete", {apikey, data})` + `STATE_DELTA` | 指定的 A2UI 业务组件 | 结构化业务卡片（如客户画像、Pipeline 看板） |
| `table` | `CUSTOM("component_data", {model_name:"searchResults", data:[...]})` | DataTable / SearchResultsList | 结构化数据表格或搜索结果列表 |
| `auto` | 动态选择上述之一 | 动态 | 系统自动判断 |

### 2.2 各模式的完整事件流

#### output_mode = text

```
event: STEP_STARTED        data: {step_name: "knowledge_doc_search"}
event: CUSTOM              data: {name: "step_metadata", value: {skill_apikey: "knowledge_doc_search", step_index: 0, phase: "started", skill_context: "fork"}}
event: TEXT_MESSAGE_START   data: {message_id: "msg_abc123", role: "assistant"}
event: TEXT_MESSAGE_CONTENT data: {message_id: "msg_abc123", delta: "## 📚 大管径管道流量测量产品推荐\n\n"}
event: TEXT_MESSAGE_CONTENT data: {message_id: "msg_abc123", delta: "### 核心发现\n\n对于大管径管道..."}
event: TEXT_MESSAGE_CONTENT data: {message_id: "msg_abc123", delta: "\n\n| 产品 | 适用管径 | 精度 |\n|------|..."}
event: TEXT_MESSAGE_END     data: {message_id: "msg_abc123"}
event: CUSTOM              data: {name: "step_metadata", value: {skill_apikey: "knowledge_doc_search", step_index: 0, status: "completed", phase: "finished"}}
event: STEP_FINISHED       data: {step_name: "knowledge_doc_search"}
```

**前端渲染效果**：
```
┌─────────────────────────────────────────────────┐
│ 🤖 Assistant                                     │
│                                                  │
│ ## 📚 大管径管道流量测量产品推荐                   │
│                                                  │
│ ### 核心发现                                      │
│ 对于大管径管道（6英寸/150mm以上），罗斯蒙特        │
│ 阿牛巴（Annubar）系列是最佳选择...               │
│                                                  │
│ | 产品 | 适用管径 | 精度 | 特点 |                │
│ |------|----------|------|------|                │
│ | 3051SFA | 2~36in | ±0.75% | 大管径首选 |      │
│ | 3051SFC | 小管径 | ±1.00% | 空间受限 |         │
│                                                  │
│ 📄 来源：产品样本：罗斯蒙特CF_SF系列...           │
└─────────────────────────────────────────────────┘
```

#### output_mode = card

```
event: STEP_STARTED        data: {step_name: "knowledge_doc_search"}
event: CUSTOM              data: {name: "step_metadata", value: {...}}
event: CUSTOM              data: {name: "component_complete", value: {
                                    apikey: "doc_card",
                                    state: "complete",
                                    data: {
                                      title: "大管径管道流量测量产品推荐",
                                      summary: "对于大管径管道，罗斯蒙特阿牛巴系列是最佳选择...",
                                      content: "## 📚 大管径管道流量测量产品推荐\n\n...(完整 Markdown)",
                                      page_count: 3,
                                      skill_apikey: "knowledge_doc_search",
                                      sources: ["产品样本：罗斯蒙特CF_SF系列差压流量计"]
                                    }
                                  }}
event: CUSTOM              data: {name: "step_metadata", value: {..., status: "completed"}}
event: STEP_FINISHED       data: {step_name: "knowledge_doc_search"}
```

**前端渲染效果**：
```
┌─────────────────────────────────────────────────┐
│ 🤖 Assistant                                     │
│                                                  │
│ ┌─────────────────────────────────────────────┐ │
│ │ 📄 大管径管道流量测量产品推荐                  │ │
│ │                                              │ │
│ │ 对于大管径管道，罗斯蒙特阿牛巴系列是最佳     │ │
│ │ 选择...                                      │ │
│ │                                              │ │
│ │ [点击查看全文 · 3页]              ↗          │ │
│ └─────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────┘
```

#### output_mode = component

```
event: STEP_STARTED        data: {step_name: "accountInsight"}
event: CUSTOM              data: {name: "step_metadata", value: {...}}
event: CUSTOM              data: {name: "component_loading", value: {apikey: "crm_record_card", state: "loading"}}

... (Skill 执行中，可能有 TOOL_CALL 事件) ...

event: STATE_DELTA         data: {delta: [
                                    {op: "replace", path: "/panels/crm_record_card/state", value: "complete"},
                                    {op: "replace", path: "/panels/crm_record_card/data", value: {
                                      accountName: "工商银行",
                                      industry: "金融",
                                      opportunities: [{name: "核心系统升级", amount: 580000}],
                                      healthScore: 85
                                    }}
                                  ]}
event: CUSTOM              data: {name: "component_complete", value: {
                                    apikey: "crm_record_card",
                                    state: "complete",
                                    data: {accountName: "工商银行", ...}
                                  }}
event: CUSTOM              data: {name: "step_metadata", value: {..., status: "completed"}}
event: STEP_FINISHED       data: {step_name: "accountInsight"}
```

**前端渲染效果**：
```
┌─────────────────────────────────────────────────┐
│ 🤖 Assistant                                     │
│                                                  │
│ ┌─────────────────────────────────────────────┐ │
│ │ 📊 工商银行                    健康度: 85 🟢 │ │
│ │ 金融 · 大型企业 · 北京                       │ │
│ │─────────────────────────────────────────────│ │
│ │ 💰 在谈商机 3 个  总金额 ¥580万              │ │
│ │ 👥 联系人 12 人   决策人 3 人                 │ │
│ │ 📅 最近活动 2天前  30天内 8 次               │ │
│ │─────────────────────────────────────────────│ │
│ │ 💡 建议：联系张总推进核心系统升级项目         │ │
│ └─────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────┘
```

#### output_mode = table

```
event: STEP_STARTED        data: {step_name: "pipeline_analysis"}
event: CUSTOM              data: {name: "step_metadata", value: {...}}
event: CUSTOM              data: {name: "component_data", value: {
                                    model_name: "searchResults",
                                    skill_apikey: "pipeline_analysis",
                                    data: {
                                      columns: [
                                        {key: "stage", label: "阶段"},
                                        {key: "count", label: "商机数"},
                                        {key: "amount", label: "金额(万)"},
                                        {key: "avg_days", label: "平均停留天数"}
                                      ],
                                      rows: [
                                        {stage: "线索", count: 45, amount: 1200, avg_days: 15},
                                        {stage: "需求确认", count: 28, amount: 890, avg_days: 22},
                                        {stage: "方案报价", count: 15, amount: 650, avg_days: 30},
                                        {stage: "谈判", count: 8, amount: 420, avg_days: 18},
                                        {stage: "赢单", count: 5, amount: 280, avg_days: 0}
                                      ],
                                      summary: "Q3 Pipeline 总金额 ¥3440万，转化率瓶颈在方案报价→谈判阶段"
                                    }
                                  }}
event: CUSTOM              data: {name: "step_metadata", value: {..., status: "completed"}}
event: STEP_FINISHED       data: {step_name: "pipeline_analysis"}
```

**前端渲染效果**：
```
┌─────────────────────────────────────────────────┐
│ 🤖 Assistant                                     │
│                                                  │
│ ┌─────────────────────────────────────────────┐ │
│ │ 📈 Pipeline 分析                              │ │
│ │                                              │ │
│ │ | 阶段     | 商机数 | 金额(万) | 停留天数 |  │ │
│ │ |----------|--------|----------|----------|  │ │
│ │ | 线索     | 45     | 1200     | 15       |  │ │
│ │ | 需求确认 | 28     | 890      | 22       |  │ │
│ │ | 方案报价 | 15     | 650      | 30 ⚠️    |  │ │
│ │ | 谈判     | 8      | 420      | 18       |  │ │
│ │ | 赢单     | 5      | 280      | -        |  │ │
│ │                                              │ │
│ │ 💡 瓶颈：方案报价→谈判 转化率仅 53%          │ │
│ └─────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────┘
```

---

## 三、后端实现规范

### 3.1 Skill 定义层

每个 Skill 在 `ai_skill_definition` 表中必须声明 `output_mode`：

```sql
-- 字段定义
output_mode      VARCHAR(20) NOT NULL DEFAULT 'auto'
component_apikey VARCHAR(100) NOT NULL DEFAULT ''
```

**业务开发者的选择指南**：

| 你的 Skill 输出是... | 选择 | 理由 |
|---------------------|------|------|
| 自然语言回答（≤2000字） | `text` | 直接展示，用户无需额外操作 |
| 自然语言回答（>2000字） | `streaming` | 流式展示，用户能看到逐步生成 |
| 长篇报告/文档（>5000字） | `card` | 折叠展示，避免对话流过长 |
| 结构化业务数据（有专属组件） | `component` | 用 A2UI 组件渲染，体验最佳 |
| 列表/表格型数据 | `table` | 结构化表格展示 |
| 不确定 | `auto` | 系统自动判断（不推荐，应尽量显式声明） |

### 3.2 AGUIConverter 层

`_handle_skill_end` 方法根据 `output_mode` 产出不同事件：

```python
# 伪代码 — 核心分流逻辑
match output_mode:
    case "text" | "streaming":
        yield text_message_start(msg_id)
        yield text_message_content(msg_id, output_text)
        yield text_message_end(msg_id)
    
    case "card":
        yield custom_event("component_complete", {
            "apikey": "doc_card",
            "state": "complete",
            "data": {"title": ..., "summary": ..., "content": output_text}
        })
    
    case "component":
        yield custom_event("component_complete", {
            "apikey": component_apikey,
            "state": "complete",
            "data": structured_data
        })
        yield state_delta([...])
    
    case "table":
        yield custom_event("component_data", {
            "model_name": "searchResults",
            "data": table_data
        })
```

### 3.3 ProgressiveRenderer 层

Renderer 的行为根据 output_mode 变化：

| output_mode | Renderer 行为 |
|-------------|--------------|
| text / streaming | **不介入**。TEXT_MESSAGE 事件直接透传，Renderer 不拦截 |
| card | **不介入**。component_complete(doc_card) 直接透传 |
| component | **介入**。STEP_STARTED 时发 component_loading，STEP_FINISHED 时发 component_complete + STATE_DELTA |
| table | **不介入**。component_data 直接透传 |
| auto | 按 auto 解析后的实际模式处理 |

**关键规则**：只有 `output_mode=component` 时 Renderer 才走完整的 loading → complete 生命周期。其他模式 Renderer 透传不干预。

---

## 四、前端实现规范

### 4.1 事件分发规则

前端 `AGUIEventDispatcher` 按事件类型分发到对应渲染器：

```typescript
class AGUIEventDispatcher {
  onEvent(event: AGUIEvent) {
    switch (event.type) {
      // ── 文本消息 → ChatBubble ──
      case "TEXT_MESSAGE_START":
        this.chatRenderer.startMessage(event.data.message_id, event.data.role);
        break;
      case "TEXT_MESSAGE_CONTENT":
        this.chatRenderer.appendContent(event.data.message_id, event.data.delta);
        break;
      case "TEXT_MESSAGE_END":
        this.chatRenderer.endMessage(event.data.message_id);
        break;

      // ── 组件事件 → ComponentRenderer ──
      case "CUSTOM":
        this.handleCustomEvent(event.data);
        break;

      // ── 状态更新 → SharedState ──
      case "STATE_DELTA":
        this.sharedState.applyPatch(event.data.delta);
        break;
      case "STATE_SNAPSHOT":
        this.sharedState.replace(event.data.snapshot);
        break;
    }
  }

  handleCustomEvent(data: {name: string, value: any}) {
    switch (data.name) {
      case "component_loading":
        this.componentRenderer.showLoading(data.value.apikey);
        break;
      case "component_complete":
        this.componentRenderer.renderComplete(data.value.apikey, data.value.data);
        break;
      case "component_data":
        this.dataRenderer.render(data.value.model_name, data.value.data);
        break;
      case "component_error":
        this.componentRenderer.showError(data.value.apikey, data.value.error);
        break;
    }
  }
}
```

### 4.2 各渲染器的职责

| 渲染器 | 输入 | 输出 UI | 支持的内容格式 |
|--------|------|---------|---------------|
| **ChatBubble** | TEXT_MESSAGE_* | 对话气泡 | Markdown（表格、代码块、列表、标题、粗体、链接） |
| **DocumentCard** | component_complete(doc_card) | 折叠卡片 | 标题 + 摘要 + 全文（点击展开） |
| **ComponentRenderer** | component_complete(业务组件) | A2UI 组件 | 按 Catalog 定义渲染 |
| **DataRenderer** | component_data | 数据表格/列表 | columns + rows 结构化数据 |

### 4.3 ChatBubble Markdown 渲染规范

ChatBubble 中的 Markdown 渲染器必须支持：

| Markdown 语法 | 渲染效果 | 示例 |
|--------------|----------|------|
| `# 标题` | 大标题 | `## 📚 检索结果` |
| `**粗体**` | 加粗文本 | `**关键信息**` |
| `- 列表项` | 无序列表 | `- 要点 1` |
| `1. 编号` | 有序列表 | `1. 第一步` |
| `\| 表格 \|` | 数据表格 | 参数对比表 |
| `` `代码` `` | 行内代码 | `knowledge_search` |
| `> 引用` | 引用块 | `> 文档摘要内容` |
| `---` | 分隔线 | 结果之间的分隔 |
| `📄 🔗 💡` | emoji | 来源标注、建议标记 |

**表格渲染要求**：
- 自动识别 Markdown 表格语法并渲染为 HTML table
- 支持列对齐（左对齐/居中/右对齐）
- 长表格自动横向滚动
- 单元格内支持粗体和链接

### 4.4 DocumentCard 组件规范

```typescript
interface DocumentCardProps {
  title: string;           // 卡片标题
  summary: string;         // 摘要（显示在卡片正文，≤200字）
  content: string;         // 完整内容（Markdown，点击展开后渲染）
  page_count?: number;     // 页数提示
  sources?: string[];      // 来源文档列表
  skill_apikey?: string;   // 产出该卡片的 Skill
}
```

**交互行为**：
- 默认折叠：显示 title + summary + 「点击查看全文 · N页」
- 点击展开：在侧边面板或弹窗中渲染完整 Markdown content
- 展开后支持：目录导航、搜索、复制

### 4.5 DataRenderer 组件规范

```typescript
interface DataTableProps {
  model_name: string;      // "searchResults" | "relevantData" | "link"
  columns: Array<{key: string, label: string, width?: number}>;
  rows: Array<Record<string, any>>;
  summary?: string;        // 数据摘要
  skill_apikey?: string;
}
```

**渲染规则**：
- `model_name = "searchResults"` → 带序号的搜索结果列表
- `model_name = "relevantData"` → 数据表格（支持排序）
- `model_name = "link"` → 链接卡片列表

---

## 五、禁止规则

### 5.1 后端禁止

| 禁止行为 | 原因 | 正确做法 |
|----------|------|----------|
| fork Skill 不声明 output_mode | 导致走 auto → 可能降级为卡片 | 显式声明 output_mode |
| output_mode=text 时产出 CUSTOM("skill_output") | Renderer 会拦截并尝试匹配组件 | 直接走 TEXT_MESSAGE 通道 |
| output_mode=component 时不指定 component_apikey | 前端不知道渲染哪个组件 | 必须指定 component_apikey |
| 在 TEXT_MESSAGE 流中间插入 CUSTOM 事件 | 破坏三流互斥 | 先 TEXT_MESSAGE_END 再发 CUSTOM |

### 5.2 前端禁止

| 禁止行为 | 原因 | 正确做法 |
|----------|------|----------|
| 对 STATE_DELTA 自动渲染新 UI | STATE_DELTA 是静默数据更新 | 只有 component_complete 才触发新 UI |
| 对长文本 TEXT_MESSAGE 自动折叠为卡片 | 后端已通过 output_mode 控制 | TEXT_MESSAGE 一律渲染为文本气泡 |
| 忽略 component_loading 事件 | 用户看不到加载状态 | 必须显示 loading skeleton |

---

## 六、output_mode = auto 的判定规则

```
输入：Skill 输出文本 + Skill 定义

判定流程：
  1. ComponentMatcher.resolve(skill_apikey) 有结果？
     → 是：output_mode = component
  
  2. 输出内容包含结构化数据（≥3行 Markdown 表格 或 JSON Array）？
     → 是：output_mode = table
  
  3. 输出内容长度判定：
     ≤ 2000 字符 → text
     2001~5000 字符 → streaming
     > 5000 字符 → card
```

**推荐**：新建 Skill 时不要依赖 auto，应显式声明 output_mode。auto 仅作为兜底。

---

## 七、与现有 Skill 的对应关系

| Skill | output_mode | context | 前端效果 |
|-------|-------------|---------|----------|
| knowledge_doc_search | **text** | fork | Markdown 文本气泡（含表格、来源标注） |
| accountInsight | component | fork | CRM 客户画像卡片 |
| customer_360 | component | inline | CRM 360 全景组件 |
| pipeline_analysis | table | fork | Pipeline 数据表格 |
| data_analysis | table | fork | 多维分析表格 |
| verify_config | text | inline | 校验报告文本 |
| diagnose | text | inline | 诊断结论文本 |
| inspect_metamodel | text | inline | 元模型档案文本 |
| batch_cleanup | text | fork | 操作结果文本 |
