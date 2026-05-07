# AG-UI × A2UI 协议层设计（v3）

> **版本说明**
> - **v3（本版）**：基于 apps-agent（后端生产参考）× ai-native-app（前端生产参考）的深度对比重写；吸收两端最佳实践
> - v2：对齐 AG-UI SDK 官方 + A2UI v0.8 规范
> - v1：初版职责拆分
>
> **对齐对象**
> - **官方规范**
>   - AG-UI Python SDK Events: <https://docs.ag-ui.com/sdk/python/core/events>
>   - A2UI v0.8 Specification: <https://a2ui.org/specification/v0.8-a2ui/>
> - **生产参考**（附录 §13 详细对比）
>   - apps-agent: `repos/apass_old_projects/neo-apps-ai-agent-service/service/agent_agui/`（后端生成事件）
>   - ai-native-app: `repos/apass_old_projects/ai-native-app/apps/host-app/src/modules/ai-engine/a2ui/`（前端消费事件）
>
> **对应代码**：`src/agui/`（事件流协议）、`src/a2ui/`（声明式 UI 协议）

## 0. 本版关键决策摘要

| 来源 | 决策 | 章节 |
|:---|:---|:---|
| 官方 v0.8 | 事件层补齐：REASONING 分层 / TOOL_CALL_ARGS/CHUNK / RAW / TEXT_MESSAGE_CHUNK | §2.1 / §6.1 |
| 官方 v0.8 | Catalog 协商（Agent Card + beginRendering.catalogId） | §3.3 / §7 |
| 官方 v0.8 | 客户端入站 `userAction` / `error` 独立端点 | §3.4 / §7 |
| apps-agent | 三流互斥状态机 + `skill_` chain STEP 事件 | §2.2 / §4.1 |
| apps-agent | ModelName 7 种分流（CUSTOM 通道 vs TEXT_MESSAGE 通道） | §2.3 |
| apps-agent | ComponentMatcher 5 层匹配 + LLM fallback + 启动预热 | §4.5 |
| apps-agent | STATE_DELTA 阈值判断（diff < snap × 0.5） | §4.4 |
| apps-agent | Renderer 延迟 STEP_FINISHED 透传 + 拦截 skill_output | §4.5 |
| ai-native-app | **Shared State 唯一数据源**：业务数据走 STATE_SNAPSHOT/DELTA，Surface 只承载结构 | §3.6 / §4.4 |
| ai-native-app | CUSTOM 命名空间路由（`a2ui.*` / `ui.*` / `component_*` / `step_metadata`） | §2.4 |
| ai-native-app | A2UI 操作双格式兼容（键名 + type） | §1.3 |
| ai-native-app | 断线重连固定首包顺序（RUN → MESSAGES → STATE → ACTIVITY×N） | §2.7 / §7 |
| 规范对齐 | `DataEntry.valueList`（取代 `valueArray`） | §3.1 / §6.2 |

---

## 1. 目标与职责边界

Agent 与前端的交互通过两个**互补但独立**的开放协议解耦：

| 协议 | 定位 | 回答问题 | 传输形态 |
|:---|:---|:---|:---|
| **AG-UI** | Agent ↔ UI **事件流**协议 | "Agent 现在在做什么？" | SSE，事件-based |
| **A2UI** | Agent → UI **声明式界面**协议 | "Agent 想让用户看到什么？" | JSONL，消息-based |

两者**正交**：
- 只跑 AG-UI → 得到普通 Chat 流（文本 + 工具调用 + 状态）
- 只跑 A2UI → 得到一份可渲染的界面定义
- 组合 AG-UI + A2UI → Agent 一边流式输出推理/对话，一边动态构建业务界面（CRM 的客户画像卡、Pipeline 看板…）

### 1.1 分工原则（架构约束）

```
┌────────────────────────────────────────────────────────────────┐
│  AG-UI 事件流（传输层，SSE）                                     │
│  职责：Agent 运行时 → 前端的实时状态广播                          │
│   ● 运行生命周期    RUN_STARTED / RUN_FINISHED / RUN_ERROR       │
│   ● 步骤            STEP_STARTED / STEP_FINISHED                 │
│   ● 文本流          TEXT_MESSAGE_START/CONTENT/END/CHUNK         │
│   ● 工具调用        TOOL_CALL_START/ARGS/END/RESULT/CHUNK        │
│   ● 推理过程        REASONING_START/END + REASONING_MESSAGE_*    │
│   ● 业务状态        STATE_SNAPSHOT / STATE_DELTA                 │
│   ● 消息历史        MESSAGES_SNAPSHOT                            │
│   ● UI 活动         ACTIVITY_SNAPSHOT / ACTIVITY_DELTA ← A2UI 融合通道 │
│   ● 扩展            CUSTOM / RAW                                 │
└─────────────────────────┬──────────────────────────────────────┘
                          │
              （活动消息通道承载 A2UI 操作）
                          │
┌─────────────────────────▼──────────────────────────────────────┐
│  A2UI 协议（展示层，JSONL）                                      │
│  职责：Agent 产出的声明式 UI 定义                                │
│   ● surfaceUpdate   定义/更新一个 UI 面板的组件列表（邻接表）      │
│   ● dataModelUpdate 更新面板的数据模型（支持 /path 定位）         │
│   ● beginRendering  告知前端 root 组件 id 开始渲染               │
│   ● deleteSurface   移除一个面板                                 │
│                                                                │
│  客户端 → 服务端（通过 A2A 回传）:                                │
│   ● userAction      用户交互事件（按钮点击 / 表单提交）           │
│   ● error           客户端渲染/绑定错误                          │
└────────────────────────────────────────────────────────────────┘
```

### 1.2 两种融合模式（可共存）

A2UI 消息需要**送达前端**，有两种传输方式：

- **Mode A：独立 SSE 通道（纯 A2UI 客户端）**
  后端另开 `/a2ui/stream` 端点，直接 `text/event-stream` 流每条 JSONL 消息。前端用标准 A2UI 客户端解析。**符合 v0.8 规范的主传输方式**。

- **Mode B：嵌入 AG-UI `ACTIVITY_SNAPSHOT`（一体化客户端）**
  在已有的 AG-UI SSE 连接上，把 A2UI 消息打包进 `ACTIVITY_SNAPSHOT.content.operations[]`。前端用 AG-UI 客户端订阅 `onActivitySnapshotEvent`，把 `operations` 再交给 A2UI 渲染器处理。**减少连接数、保证事件顺序，是本项目默认方式**（对齐 apps-agent 现状，ai-native-app 已打通该通道）。

本设计两种模式同时支持，Skill 层代码无需感知差异。

### 1.3 双格式操作兼容

参考 ai-native-app 的 `A2UIBridge`，Emitter 产出的 A2UI 操作需要**同时兼容两种结构**以适配协议演进期的客户端：

```json
// 格式 A — 键名标识（A2UI 官方）默认
{"surfaceUpdate": {"surfaceId": "s1", "components": [...]}}

// 格式 B — type 标识（CopilotKit 早期 / 调试友好）
{"type": "surfaceUpdate", "surfaceId": "s1", "components": [...]}
```

**策略**：Emitter 默认产出格式 A（对齐官方），可通过 `A2UIEmitter(dual_format=True)` 同时产出 A+B（调试场景）；前端 Bridge 两种都能识别。

---

## 2. AG-UI 事件层设计（`src/agui/`）

### 2.1 事件类型完整清单（对齐官方 EventType）

```python
class AGUIEventType(str, Enum):
    # ── 运行生命周期 ──
    RUN_STARTED   = "RUN_STARTED"      # {thread_id, run_id, parent_run_id?, input?}
    RUN_FINISHED  = "RUN_FINISHED"     # {thread_id, run_id, result?}
    RUN_ERROR     = "RUN_ERROR"        # {message, code?}

    # ── 步骤 ──
    STEP_STARTED  = "STEP_STARTED"     # {step_name}  （仅 step_name 为规范字段，扩展字段放 CUSTOM）
    STEP_FINISHED = "STEP_FINISHED"    # {step_name}

    # ── 文本消息 ──
    TEXT_MESSAGE_START   = "TEXT_MESSAGE_START"    # {message_id, role="assistant"}
    TEXT_MESSAGE_CONTENT = "TEXT_MESSAGE_CONTENT"  # {message_id, delta}   delta 非空
    TEXT_MESSAGE_END     = "TEXT_MESSAGE_END"      # {message_id}
    TEXT_MESSAGE_CHUNK   = "TEXT_MESSAGE_CHUNK"    # 便捷：首 chunk 必带 message_id

    # ── 工具调用 ──
    TOOL_CALL_START  = "TOOL_CALL_START"   # {tool_call_id, tool_call_name, parent_message_id?}
    TOOL_CALL_ARGS   = "TOOL_CALL_ARGS"    # {tool_call_id, delta}
    TOOL_CALL_END    = "TOOL_CALL_END"     # {tool_call_id}
    TOOL_CALL_RESULT = "TOOL_CALL_RESULT"  # {message_id, tool_call_id, content, role="tool"?}
    TOOL_CALL_CHUNK  = "TOOL_CALL_CHUNK"   # 便捷：首 chunk 必带 id+name

    # ── 推理（含加密回传）──
    REASONING_START           = "REASONING_START"            # {message_id}
    REASONING_MESSAGE_START   = "REASONING_MESSAGE_START"    # {message_id, role="reasoning"}
    REASONING_MESSAGE_CONTENT = "REASONING_MESSAGE_CONTENT"  # {message_id, delta}
    REASONING_MESSAGE_END     = "REASONING_MESSAGE_END"      # {message_id}
    REASONING_MESSAGE_CHUNK   = "REASONING_MESSAGE_CHUNK"    # 便捷
    REASONING_END             = "REASONING_END"              # {message_id}
    REASONING_ENCRYPTED_VALUE = "REASONING_ENCRYPTED_VALUE"  # {subtype, entity_id, encrypted_value}

    # ── 状态/消息快照 ──
    STATE_SNAPSHOT     = "STATE_SNAPSHOT"      # {snapshot}
    STATE_DELTA        = "STATE_DELTA"         # {delta: [JsonPatch op]}
    MESSAGES_SNAPSHOT  = "MESSAGES_SNAPSHOT"   # {messages}

    # ── 活动（A2UI 承载通道）──
    ACTIVITY_SNAPSHOT  = "ACTIVITY_SNAPSHOT"   # {message_id, activity_type, content, replace=True}
    ACTIVITY_DELTA     = "ACTIVITY_DELTA"      # {message_id, activity_type, patch: [JsonPatch op]}

    # ── 扩展 ──
    RAW    = "RAW"       # {event, source?}  — 透传外部系统原始事件
    CUSTOM = "CUSTOM"    # {name, value}     — 应用自定义
```

### 2.2 事件产生规则

| 来源 | 规则 |
|:---|:---|
| `on_chat_model_stream` 文本 chunk | 首 chunk → `TEXT_MESSAGE_START`，每 chunk → `TEXT_MESSAGE_CONTENT`，切换/结束 → `TEXT_MESSAGE_END` |
| `on_chat_model_stream` thinking block | 首块 → `REASONING_START(message_id=r_id)` + `REASONING_MESSAGE_START(message_id=r_id_m)`，每块 → `REASONING_MESSAGE_CONTENT`，结束 → `REASONING_MESSAGE_END` + `REASONING_END` |
| `on_chat_model_stream` tool_call_chunks | 首 chunk → `TOOL_CALL_START`，argsDelta → `TOOL_CALL_ARGS`，结束 → `TOOL_CALL_END` |
| `on_tool_start`（LangChain） | → `TOOL_CALL_START`（兜底） |
| `on_tool_end` | → `TOOL_CALL_RESULT(message_id, role="tool")` + `TOOL_CALL_END` |
| Skill chain `on_chain_start/end`（name 以 `skill_` 前缀） | → `STEP_STARTED(step_name=skill_apikey)` + 伴随 `CUSTOM("step_metadata", {step_name, step_index, skill_apikey})` |
| Skill 输出 | 发 `CUSTOM("skill_output", {skill_apikey, data})` 供 Renderer 聚合（不透传前端） |
| `on_custom_event("agent_text")` | 走文本三段式 |
| `on_custom_event("agent_data")` / `a2ui.*` | 先关闭文本/推理流，再走 `ACTIVITY_SNAPSHOT`（Mode B）或 A2UI 原生通道（Mode A） |
| `on_custom_event("state.patch")` | → `STATE_DELTA`（透传 JSON Patch） |
| 子 Agent 事件（`parent_ids[0] != root_run_id`） | 默认丢弃；`on_custom_event` 例外（`agent_text/agent_data` 需要穿透） |

**三流互斥约束**（对齐 apps-agent converter）：文本 / 推理 / 工具调用三个流状态机**互斥**。任何一个开启前，先关闭其他两个（发相应的 END）。这确保前端组合式渲染器（如 CopilotKit）不会把 reasoning/tool_args 插进 assistant 消息气泡中。

### 2.3 ModelName 事件分流（Skill 产出分类）

> 参考 apps-agent `ModelNameType`。Skill / Tool 输出结构化结果时可声明 `model_name`（render_hint 的语义等价），由 Converter 决定走哪种事件：

| ModelName | 含义 | 事件分流 |
|:---|:---|:---|
| `component` | 声明了目标组件 apikey 的业务数据 | `CUSTOM("component_complete", {apikey, data})` |
| `relevantData` / `searchResults` / `link` | 数据明确但组件需要匹配 | `CUSTOM("component_data", {model_name, skill_apikey, data})` → Renderer 匹配 |
| `textResult` / `explanation` / `longText` | 纯文本结果 | `TEXT_MESSAGE_*` 三段式 |
| *（未声明）* | Skill 输出形态未知 | 保持 `CUSTOM("skill_output")` 内部事件 + `STATE_DELTA` 业务快照 |

Converter 提供 `_convert_by_model_name(model_name, data, skill_apikey)` 辅助方法。

### 2.4 CUSTOM 事件命名空间（对齐 ai-native-app CustomEventDispatcher）

所有 `CUSTOM` 事件使用**命名空间前缀**路由；前端 `CustomEventDispatcher` 按前缀分发：

| 命名空间 | 用途 | 前端路由 |
|:---|:---|:---|
| `a2ui.*` | A2UI 界面操作（`a2ui.render` / `a2ui.update` / `a2ui.clear`） | → `A2UIBridge` → SurfaceStore |
| `ui.*` | 通用 UI 事件（`ui.notify` / `ui.navigate` / `ui.toast`） | → 全局 EventBus |
| `component_*` | 渐进式组件状态（`component_loading/delta/complete/error/data`） | → 特定 Surface 渲染器 |
| `step_metadata` | STEP 事件的扩展字段（skill_apikey/step_index） | → 调试/Trace 侧边栏 |
| `skill_output` | **仅后端内部**，由 Renderer 消费后 **不透传**前端 | — |

**禁止规则**：
- 不允许"裸" CUSTOM（无命名空间）透传到前端
- 未知命名空间由前端记录 warning 并丢弃
- 业务 Skill 不直接发 `component_*` / `step_metadata` — 这些由 Converter/Renderer 自动产生

### 2.5 SSE 编码

```python
def to_sse(self) -> str:
    return f"event: {self.type}\ndata: {json.dumps(self.data, ensure_ascii=False)}\n\n"
```

`timestamp` / `raw_event` 按需附加；`BaseEvent` 字段支持透传。

### 2.6 字段对齐与扩展规范

**规范内字段**：按官方字段放在 event 顶层（序列化时 `type + data` → 官方 schema）。

**扩展字段策略**：规范未定义的字段（如 `skill_apikey`、`step_index`、`status`）统一放到伴随的 `CUSTOM("step_metadata", ...)` 事件里，**不污染规范事件**：

```python
# 发 Skill step 时成对发出：
yield AGUIEvent(type="STEP_STARTED", data={"step_name": skill_apikey})
yield AGUIEvent(type="CUSTOM", data={
    "name": "step_metadata",
    "value": {"step_name": skill_apikey, "step_index": i, "skill_apikey": skill_apikey},
})
```

### 2.7 断线重连 / 首包协议

前端重连时后端按以下**固定顺序**下发（对齐 ai-native-app 并比 apps-agent 更完整）：

1. `RUN_STARTED`（带 `parent_run_id` 指向上一个 run，实现 Time Travel）
2. `MESSAGES_SNAPSHOT`（完整历史消息）
3. `STATE_SNAPSHOT`（业务状态全量；分层后的 `{phase, data.*, panelLayoutOrder, panelSurfaceMap, notifications}`）
4. `ACTIVITY_SNAPSHOT`（每个活跃 surface 一次，`replace=True`，包装 `surfaceUpdate + beginRendering`，如有局部 UI 状态则附 `dataModelUpdate`）
5. 恢复增量推送（STATE_DELTA / ACTIVITY_DELTA / 文本/工具流）

AGUIConverter 暴露 `emit_reconnect_snapshot(messages, state_snapshot, activities, parent_run_id)` 辅助方法。

---

## 3. A2UI 消息层设计（`src/a2ui/`）

### 3.1 四种服务端消息（对齐 v0.8 §1.4）

```python
# ─ 1. surfaceUpdate — 定义/更新组件 ─
{
  "surfaceUpdate": {
    "surfaceId": "main_content_area",
    "components": [
      {"id": "root", "component": {"Column": {"children": {"explicitList": ["title", "btn"]}}}},
      {"id": "title", "component": {"Text": {"text": {"literalString": "Hello"}}}},
      {"id": "btn", "component": {"Button": {"child": "btn_label", "action": {...}}}},
      {"id": "btn_label", "component": {"Text": {"text": {"literalString": "Click"}}}}
    ]
  }
}

# ─ 2. dataModelUpdate — 更新数据模型（可选 path 定位）─
{
  "dataModelUpdate": {
    "surfaceId": "main_content_area",
    "path": "user",
    "contents": [
      {"key": "name",       "valueString":  "Bob"},
      {"key": "age",        "valueInt":     30},
      {"key": "isVerified", "valueBoolean": true},
      {"key": "tags",       "valueList":    ["vip", "gold"]},
      {"key": "address",    "valueMap": [
        {"key": "city", "valueString": "Beijing"}
      ]}
    ]
  }
}

# ─ 3. beginRendering — 触发首次渲染 ─
{
  "beginRendering": {
    "surfaceId": "main_content_area",
    "root": "root",
    "catalogId": "https://a2ui.org/specification/v0_8/standard_catalog_definition.json"
  }
}

# ─ 4. deleteSurface — 移除面板 ─
{"deleteSurface": {"surfaceId": "main_content_area"}}
```

### 3.2 邻接表模型与 BoundValue

**邻接表**：组件是**平坦列表**，通过 string id 相互引用。LLM 产出友好 + 消息可无序到达。

**BoundValue** 是可绑定属性的值载体：

```python
{"literalString": "Guest"}                 # 纯字面量
{"path": "/user/name"}                     # 纯路径绑定
{"path": "/user/name", "literalString": "Guest"}  # ① 写入 /user/name="Guest" ② 绑定到该路径
```

### 3.3 Catalog 协商（v0.8 §2.1）

- **Agent 能力声明**（Agent Card 里）：
  ```json
  {
    "extensions": [{
      "uri": "https://a2ui.org/a2a-extension/a2ui/v0.8",
      "params": {
        "supportedCatalogIds": [
          "https://a2ui.org/specification/v0_8/standard_catalog_definition.json",
          "https://viking.tencent.com/a2ui/crm-catalog-v1.json"
        ],
        "acceptsInlineCatalogs": true
      }
    }]
  }
  ```

- **客户端能力声明**（每条 A2A 消息的 metadata 里）：
  ```json
  {
    "a2uiClientCapabilities": {
      "supportedCatalogIds": [...],
      "inlineCatalogs": [<CatalogDef>]     // 仅当 Agent 允许
    }
  }
  ```

- **本项目 Catalog 体系**：
  - `standard` — 遵循 A2UI v0.8 标准（Row/Column/Card/Text/Image/Button/TextField/List 等基础控件）
  - `viking.crm-v1` — CRM 业务组件（`CrmRecordCard` / `PipelineTable` / `BantMatrix` / `OpportunityTimeline` …）
  - 运行时由客户端声明支持哪些，Agent 选择首个双方都支持的作为 `beginRendering.catalogId`

### 3.4 客户端 → 服务端事件（v0.8 §5）

前端交互回传两种消息：

```json
// userAction
{
  "userAction": {
    "name": "submit_form",
    "surfaceId": "main_content_area",
    "sourceComponentId": "submit_btn",
    "timestamp": "2025-09-19T17:05:00Z",
    "context": {"userInput": "hello", "formId": "f-123"}
  }
}

// error
{"error": {"message": "binding /user/xxx not found", "componentId": "title"}}
```

服务端接收后：
- `userAction` → 合成一条 HumanMessage 注入 Agent（或作为 tool call 回传）
- `error` → 记录 trace + 可选降级回复

### 3.5 动态列表（template）

```python
{"id": "list", "component": {"List": {
  "children": {"template": {
    "dataBinding": "/data/customers_top",  # 指向 Shared State 中的数组
    "componentId": "list_item_tpl"          # 每一项用这个模板渲染
  }}
}}}
```

模板组件访问当前项：`{"path": "./name"}`（相对路径）或 `{"path": "/data/customers_top/$/name"}`（绝对）。

### 3.6 数据归属原则（Shared State 唯一源）

> **对齐 ai-native-app v0.6+ 的 Shared State 统一设计**

业务数据的唯一来源是 AG-UI 的 `STATE_SNAPSHOT` / `STATE_DELTA`；`dataModelUpdate` 不再承担"主数据通道"角色。

```
┌───────────────── 业务数据流 ─────────────────┐      ┌─── UI 结构流 ───┐
│  Skill 产出数据                                │      │  Builder 产出    │
│       ↓                                        │      │  surfaceUpdate   │
│  Aggregator.add(render_type, data)             │      │       ↓          │
│       ↓                                        │      │  ACTIVITY_SNAP   │
│  STATE_SNAPSHOT { data: {render_type: ...} }   │      │  (结构 + 绑定)   │
└────────────────────────────────────────────────┘      └──────────────────┘
         │                                                        │
         ▼                                                        ▼
   前端 Shared State 更新  ←──── 通过 path 绑定 ────  组件渲染时读取 Shared State
```

**关键规则**：
- 每个 surface 的 `BoundValue.path` 全部指向 **同一个 Shared State 根**（如 `/data/customers_top/0/name`），不再用 surface 局部 dataModel
- `dataModelUpdate` 只在**首次初始化简写**（`path` + `literal*`）或**真正 surface 局部数据**（如组件内部 UI 状态）时才发
- Aggregator 的 `bind_a2ui_data(render_type, ...)` 方法产出绑定用的 `path`（指向 `/data/<render_type>/...`），供 Builder 直接引用

这样带来的好处：
- 前端实现简化：`A2UISurface` 不再需要维护局部 dataModels
- 多 surface 可共享同一份业务数据，无需重复推送
- 回放 / 时间旅行更容易：只需恢复 Shared State 一个对象

---

## 4. 代码结构与职责

```
src/
├── agui/                       # AG-UI 事件层
│   ├── models.py              # 事件类型 + dataclass + 工厂函数
│   ├── converter.py           # LangGraph astream_events → AG-UI 事件流
│   ├── renderer.py            # ProgressiveRenderer：在 STEP 边界注入组件事件
│   ├── pipeline.py            # 管道工厂 create_agui_pipeline
│   └── __init__.py
│
├── a2ui/                       # A2UI 声明式 UI 层
│   ├── models.py              # 四种消息 + BoundValue + DataEntry + Component
│   ├── builder.py             # A2UIBuilder：流式 API 构建 surface
│   ├── aggregator.py          # SnapshotAggregator：业务状态 → STATE/ACTIVITY 事件
│   ├── emitter.py             # A2UIEmitter：Mode A (JSONL) / Mode B (ACTIVITY_SNAPSHOT)
│   ├── catalog.py             # 【新增】Catalog 定义 + 协商辅助
│   ├── inbound.py             # 【新增】解析 userAction / error 客户端事件
│   ├── stream.py              # 【新增】Mode A 的 JSONL/SSE 流端点适配器
│   └── __init__.py
│
└── agents/adapter.py           # execute_agui() 编排两层
```

### 4.1 Converter（AG-UI）职责

- 订阅 LangGraph `astream_events(version="v2")`
- 维护**三类流状态机**（文本 / 推理 / 工具调用）**互斥切换** — 任何一类开启前先关闭其他两类
- 过滤子 Agent 事件（`parent_ids[0] != root_run_id` 的丢弃；`on_custom_event` 例外）
- 识别 Skill chain（`skill_` 前缀）→ 发 STEP + 伴随 `CUSTOM("step_metadata")`
- 识别工具调用：
  - `chunk.tool_call_chunks` → `TOOL_CALL_START`（首块） + `TOOL_CALL_ARGS`（每块 argsDelta）
  - `on_tool_end` → `TOOL_CALL_RESULT(message_id, role="tool")` + `TOOL_CALL_END`
- 拦截 `on_custom_event`：
  - `agent_text` → 文本三段式
  - `agent_data` / `a2ui.*` → 关闭文本/推理流后，经 Emitter 发出 ACTIVITY_SNAPSHOT
  - `state.patch` → `STATE_DELTA`
  - `skill.output(model_name, data, skill_apikey)` → 调用 `_convert_by_model_name` 分流到 CUSTOM 或 TEXT_MESSAGE
- 推理处理：
  - thinking block 首块 → `REASONING_START` + `REASONING_MESSAGE_START`
  - 每块 → `REASONING_MESSAGE_CONTENT`
  - 结束 → `REASONING_MESSAGE_END` + `REASONING_END`
- 断线重连：`emit_reconnect_snapshot(messages, state_snapshot, active_activities, parent_run_id)` 按 §2.7 顺序下发

### 4.2 Builder（A2UI）职责

```python
# 场景：Skill 已经通过 Aggregator 把数据写入 Shared State
#       aggregator.add("pipeline", {"stages": [...], "selected": None})
# Builder 只负责产出"结构 + 绑定"

ui = A2UIBuilder(
    surface_id=aggregator.ensure_surface("pipeline"),   # 由 Aggregator 分配
    catalog_id="viking.crm-v1",
)

data_path = aggregator.bind_a2ui_data("pipeline")       # → "/data/pipeline"

ui.column("root", children=[
    ui.text("title", literal="Q3 Pipeline 分析", usage_hint="h1"),
    ui.pipeline_table("table", stages_path=f"{data_path}/stages",
                      on_stage_click="drill_down"),
    ui.button("btn", label="查看详情", action="view_detail",
              context={"stage": {"path": f"{data_path}/selected"}}),
])

# 数据不再写入 dataModelUpdate —— 数据由 Aggregator 统一推 STATE_SNAPSHOT/DELTA
messages = ui.messages()   # → [SurfaceUpdate, BeginRendering]

# Aggregator 负责把 messages 打到对应 surface 槽位
events = aggregator.emit_ui("pipeline", messages)
for e in events: yield e
```

**关键规则**：
- 组件 id 全局唯一；重复 id raise
- root 选择：`set_root()` 显式 > 第一个 `is_container=True` 组件 > 第一个添加
- Builder 是 session 级；跨 run 不复用
- **`ui.data(...)` 仅保留给 surface 局部 UI 状态**（如表单草稿 / 折叠开关），业务数据一律走 `Aggregator.add()`

### 4.3 Emitter（融合层）

**Mode A（JSONL 原生流）**：
```python
async def a2ui_jsonl_stream(messages: Iterable[A2UIMessage]) -> AsyncIterator[str]:
    for m in messages:
        yield m.to_jsonl() + "\n"
```
可直接接 FastAPI `StreamingResponse(media_type="application/x-ndjson")`。

**Mode B（嵌入 AG-UI ACTIVITY）**：
```python
emitter.emit_activity(messages, activity_type="a2ui-surface", replace=True)
# → [ACTIVITY_SNAPSHOT(content={"operations": [<msg dict>, ...]})]
```

前端解析（Mode B）：
```typescript
onActivitySnapshotEvent: (event) => {
  if (event.activity_type === "a2ui-surface") {
    const { operations } = event.content;
    a2uiRenderer.dispatch(operations);   // 按 surfaceUpdate/dataModelUpdate/beginRendering 分发
  }
}
```

### 4.4 Aggregator（业务状态分层 + Shared State 统一源）

```
STATE_SNAPSHOT 结构（分层，对齐 ai-native-app）:
{
  "phase": "executing",               # 运行阶段元数据
  "panelLayoutOrder":   [...],        # render_type 顺序
  "panelAppearanceOrder":[...],       # 出现顺序
  "panelSurfaceMap":    {...},        # render_type → surfaceId
  "notifications":      [...],
  "data": {                           # ★ 业务数据命名空间（Shared State 实质内容）
    "customers_top": [...],
    "pipeline":      {...}
  }
}
```

**关键方法**（代码层契约，用法统一）：

| 方法 | 职责 |
|:---|:---|
| `add(render_type, data, notification_message=None, emit_activity=True)` | 追加一块业务数据，首次自动分配 surface-slot-N + 发通知；产出 `[ACTIVITY_SNAPSHOT?(首次通知) + STATE_SNAPSHOT/DELTA]` |
| `emit_ui(render_type, messages)` | 把一批 A2UI 消息打到 render_type 对应面板槽位上，产出 `ACTIVITY_SNAPSHOT` |
| `bind_a2ui_data(render_type)` | 返回 `path` 前缀（如 `/data/customers_top`），供 Builder 的 `path_bind` 直接使用 |
| `force_snapshot()` | 产出一次全量 `STATE_SNAPSHOT`（会话首包 / 重连） |
| `ensure_surface(render_type)` | 查询或分配 `surfaceId`（保证返回一个） |
| `surface_id_for(render_type)` | 查询 `surfaceId`，不存在时返回 None |
| `reset()` | 清空所有状态（跨 run 调用） |

**Delta 决策**（对齐 apps-agent）：每次 `add()` 计算 JSON Patch，若 `diff_size < snapshot_size * 0.5` 就发 `STATE_DELTA`，否则发 `STATE_SNAPSHOT`。首次或 `jsonpatch` 不可用时降级为全量。

### 4.5 Renderer（渐进式组件 + 5 层匹配）

`ProgressiveRenderer` 监听 AG-UI 事件，在 `STEP_STARTED/FINISHED` 上自动发：

```python
STEP_STARTED(skill_apikey)    →  CUSTOM("component_loading",  {apikey, state: "loading"})
CUSTOM("skill_output", data)  →  缓存到 _pending_skill_output（不透传前端）
STEP_FINISHED(ok)             →  CUSTOM("component_complete", {apikey, state: "complete", data})
                              +  STATE_DELTA 增量更新 /panels/<apikey>/state 和 /panels/<apikey>/data
STEP_FINISHED(failed)         →  CUSTOM("component_error",    {apikey, state: "error", error})
```

**事件顺序规则**（对齐 apps-agent v2 renderer）：
- `STEP_FINISHED` 原始事件**延迟**到 Renderer 插入完 `component_complete` 和 STATE_DELTA 之后再透传
- `skill_output` 内部事件被 Renderer 拦截吸收，**不透传到前端**
- `CUSTOM("component_delta", ...)` 供 Skill 中途推送增量（通过 `push_delta(skill_apikey, data)`）

#### ComponentMatcher 五层匹配（对齐 apps-agent）

```python
class ComponentMatcher:
    """按优先级返回组件 apikey，未匹配返回 None。"""

    def resolve(self, skill_apikey: str,
                output_schema: dict | None = None,
                output_model_names: list[str] | None = None) -> str | None:
        # Layer 1: 显式 bind（一对一）
        if skill_apikey in self._bind_map: return self._bind_map[skill_apikey]
        # Layer 2: prefer 首选（多对一）
        if skill_apikey in self._prefer_map: return self._prefer_map[skill_apikey][0]
        # Layer 3: ModelName 匹配（data 分类）
        for mn in (output_model_names or []):
            candidates = self._model_name_map.get(mn, [])
            if len(candidates) == 1: return candidates[0]
            if len(candidates) > 1:  return self._llm_fallback(skill_apikey, candidates)
        # Layer 4: schema 字段重叠（≥ 0.6 阈值）
        candidates = self._schema_cache.get(skill_apikey) or (
            self._match_schema_dynamic(output_schema) if output_schema else []
        )
        if len(candidates) == 1: return candidates[0]
        if len(candidates) > 1:  return self._llm_fallback(skill_apikey, candidates)
        # Layer 5: 无匹配返回 None
        return None

    def warmup(self, skills: list) -> None:
        """启动时预计算 bind/prefer/model_name/schema 缓存。"""

    def rewarmup(self, skills: list) -> None:
        """原子替换 4 张缓存（配置热更新用）。"""
```

**5 层来源**：
1. **bind / prefer** — 组件 JSON 的 `skill_bindings: {bind: [...], prefer: [...]}` 静态声明
2. **ModelName 匹配** — 组件 JSON 的 `supported_model_names: ["component","relevantData",...]`
3. **Schema 字段重叠** — `overlap / max(len(skill_fields), len(comp_fields)) ≥ 0.6`
4. **LLM fallback** — 多候选时让小模型选一个（失败兜底第一候选，可通过配置关闭）
5. **无匹配** — Renderer 不发 `component_*` 事件，Skill 输出仅走 STATE_DELTA

配置：组件元数据放 `resources/a2ui/components/*.json`，启动时由 `CatalogRegistry.load()` 注入到 Matcher。

---

## 5. 端到端事件流示例

### 5.1 场景：用户问"查看 Q3 新签 Top10 客户"

```
① 用户 POST /agent/chat
② 后端建立 SSE (AG-UI)

→ event: RUN_STARTED         data: {thread_id, run_id}
→ event: MESSAGES_SNAPSHOT   data: {messages: [...history]}

→ event: STEP_STARTED        data: {step_name: "new_customers_analysis"}
→ event: CUSTOM              data: {name: "step_metadata",
                                     value: {step_name: "new_customers_analysis",
                                             skill_apikey: "new_customers_analysis",
                                             step_index: 0}}
→ event: CUSTOM              data: {name: "component_loading",
                                     value: {apikey: "customer_top_list", state: "loading"}}

→ event: REASONING_START     data: {message_id: "r1"}
→ event: REASONING_MESSAGE_START   data: {message_id: "r1_m", role: "reasoning"}
→ event: REASONING_MESSAGE_CONTENT data: {message_id: "r1_m", delta: "我需要先调用客户查询接口..."}
→ event: REASONING_MESSAGE_END     data: {message_id: "r1_m"}
→ event: REASONING_END       data: {message_id: "r1"}

→ event: TOOL_CALL_START     data: {tool_call_id: "tc1", tool_call_name: "list_customers"}
→ event: TOOL_CALL_ARGS      data: {tool_call_id: "tc1", delta: "{\"quarter\":\"Q3\","}
→ event: TOOL_CALL_ARGS      data: {tool_call_id: "tc1", delta: "\"limit\":10}"}
→ event: TOOL_CALL_END       data: {tool_call_id: "tc1"}
→ event: TOOL_CALL_RESULT    data: {message_id: "m_tc1", tool_call_id: "tc1",
                                     content: "[{...},...]", role: "tool"}

→ event: STATE_SNAPSHOT      data: {snapshot: {
                                phase: "executing",
                                data: {customers_top: [{id:"C1",name:"工行"}, ...]},
                                panelSurfaceMap:    {customers_top: "panel-slot-1"},
                                panelLayoutOrder:   ["customers_top"],
                                panelAppearanceOrder:["customers_top"],
                                notifications: [{type: "info", message: "✅ 客户列表已加载"}]
                             }}

→ event: ACTIVITY_SNAPSHOT   data: {
     message_id: "a2ui-runXXXX",
     activity_type: "a2ui-surface",
     replace: true,
     content: {operations: [
       {"surfaceUpdate": {
           "surfaceId": "panel-slot-1",
           "components": [
             {"id": "root", "component": {"Column": {"children": {"explicitList": ["title","list"]}}}},
             {"id": "title", "component": {"Text": {"text": {"literalString": "Q3 新签 Top10"}, "usageHint": "h2"}}},
             {"id": "list", "component": {"List": {"children": {"template": {
               "dataBinding": "/data/customers_top",   // ★ 绑定到 Shared State
               "componentId": "customer_row"
             }}}}},
             {"id": "customer_row", "component": {"CrmRecordCard": {
               "recordType": {"literalString": "customer"},
               "recordId":   {"path": "./id"}           // ★ 相对路径（template 作用域内）
             }}}
           ]}},
       // ★ 不再发独立的 dataModelUpdate — 数据走 STATE_SNAPSHOT
       {"beginRendering": {"surfaceId": "panel-slot-1","root": "root",
                           "catalogId": "https://viking.tencent.com/a2ui/crm-v1.json"}}
     ]}
  }

→ event: STATE_DELTA         data: {delta: [
                                {op:"replace", path:"/panels/customer_top_list/state", value:"complete"},
                                {op:"replace", path:"/panels/customer_top_list/data",  value:{...}}
                             ]}
→ event: CUSTOM              data: {name: "component_complete",
                                     value: {apikey: "customer_top_list", state: "complete", data: {...}}}
→ event: STEP_FINISHED       data: {step_name: "new_customers_analysis"}

→ event: TEXT_MESSAGE_START   data: {message_id: "m1", role: "assistant"}
→ event: TEXT_MESSAGE_CONTENT data: {message_id: "m1", delta: "Q3 新签"}
→ event: TEXT_MESSAGE_CONTENT data: {message_id: "m1", delta: " Top10 客户..."}
→ event: TEXT_MESSAGE_END     data: {message_id: "m1"}

→ event: RUN_FINISHED        data: {thread_id, run_id, result: {...}}
```

### 5.2 用户交互闭环

```
前端：用户点击 "CrmRecordCard" 里的 "打开详情" 按钮
前端：POST /agent/a2ui/event
  {"userAction": {"name": "open_opportunity",
                  "surfaceId": "panel-slot-1",
                  "sourceComponentId": "detail_btn",
                  "timestamp": "2025-05-07T10:12:00Z",
                  "context": {"recordId": "C1"}}}

后端 A2UIInboundHandler.handle() →
  - 合成 HumanMessage("打开客户 C1 的详情")
  - 在同一 thread_id 上继续 Agent 执行
  - 新一轮事件流在原 SSE 继续输出
```

---

## 6. 数据模型（Python 类型）

### 6.1 AG-UI 事件（`src/agui/models.py`）

```python
@dataclass
class AGUIEvent:
    type: str
    data: dict[str, Any] = field(default_factory=dict)
    timestamp: int | None = None
    raw_event: Any | None = None

    def to_dict(self) -> dict: ...
    def to_sse(self) -> str: ...
```

工厂函数（与官方字段 1:1 对齐）：
```python
def run_started(run_id, thread_id, parent_run_id=None, input=None) -> AGUIEvent
def run_finished(run_id, thread_id, result=None) -> AGUIEvent
def run_error(message, code=None) -> AGUIEvent
def step_started(step_name) -> AGUIEvent
def step_finished(step_name) -> AGUIEvent

def text_message_start(message_id, role="assistant") -> AGUIEvent
def text_message_content(message_id, delta) -> AGUIEvent      # 校验 delta 非空
def text_message_end(message_id) -> AGUIEvent
def text_message_chunk(message_id, delta, role="assistant") -> AGUIEvent

def tool_call_start(tool_call_id, tool_call_name, parent_message_id=None) -> AGUIEvent
def tool_call_args(tool_call_id, delta) -> AGUIEvent
def tool_call_end(tool_call_id) -> AGUIEvent
def tool_call_result(message_id, tool_call_id, content, role="tool") -> AGUIEvent
def tool_call_chunk(tool_call_id, tool_call_name, delta, parent_message_id=None) -> AGUIEvent

def reasoning_start(message_id) -> AGUIEvent
def reasoning_message_start(message_id) -> AGUIEvent
def reasoning_message_content(message_id, delta) -> AGUIEvent
def reasoning_message_end(message_id) -> AGUIEvent
def reasoning_message_chunk(message_id, delta) -> AGUIEvent
def reasoning_end(message_id) -> AGUIEvent
def reasoning_encrypted_value(subtype, entity_id, encrypted_value) -> AGUIEvent

def state_snapshot(snapshot) -> AGUIEvent
def state_delta(delta) -> AGUIEvent
def messages_snapshot(messages) -> AGUIEvent
def activity_snapshot(message_id, activity_type, content, replace=True) -> AGUIEvent
def activity_delta(message_id, activity_type, patch) -> AGUIEvent

def raw(event, source=None) -> AGUIEvent
def custom(name, value) -> AGUIEvent
```

### 6.2 A2UI 模型（`src/a2ui/models.py`）

```python
@dataclass
class BoundValue:
    """对应 §4.2；同时提供 path + literal 表示"初始化简写"。"""
    path: str | None = None
    literal_string:  str  | None = None
    literal_number:  float | None = None
    literal_boolean: bool | None = None
    literal_array:   list | None = None

@dataclass
class DataEntry:
    """对应 §4.1；key 必填，value_* 互斥。"""
    key: str
    value_string:  str | None = None
    value_int:     int | None = None
    value_number:  float | None = None
    value_boolean: bool | None = None
    value_map:     list["DataEntry"] | None = None
    value_list:    list | None = None              # ← 规范建议字段名

@dataclass
class Component:
    id: str
    type: str          # 来自 Catalog 的组件名，如 "Text"/"Row"/"CrmRecordCard"
    props: dict

# 四种服务端消息
@dataclass class SurfaceUpdate:   surface_id, components: list[Component]
@dataclass class DataModelUpdate: surface_id, contents: list[DataEntry], path: str | None
@dataclass class BeginRendering:  surface_id, root: str, catalog_id: str | None
@dataclass class DeleteSurface:   surface_id

# 客户端入站（新增）
@dataclass class UserAction:      name, surface_id, source_component_id, timestamp, context: dict
@dataclass class ClientError:     message: str, component_id: str | None, surface_id: str | None
```

### 6.3 Catalog（新增 `src/a2ui/catalog.py`）

```python
@dataclass
class CatalogDefinition:
    catalog_id: str
    components: dict[str, dict]   # type_name → JSON Schema
    styles: dict[str, dict] = field(default_factory=dict)

class CatalogRegistry:
    """管理服务端已知的 catalog；支持 Agent Card 声明"""
    STANDARD_V08 = "https://a2ui.org/specification/v0_8/standard_catalog_definition.json"

    def register(self, cat: CatalogDefinition) -> None: ...
    def get(self, catalog_id: str) -> CatalogDefinition | None: ...
    def supported_ids(self) -> list[str]: ...
    def negotiate(self, client_supported: list[str],
                  client_inline: list[CatalogDefinition] | None = None,
                  accepts_inline: bool = False) -> str:
        """选出双方都支持的 catalog_id；优先用业务 catalog，次选标准 catalog"""
```

### 6.4 入站消息解析（新增 `src/a2ui/inbound.py`）

```python
def parse_client_event(payload: dict) -> UserAction | ClientError:
    if "userAction" in payload:
        ua = payload["userAction"]
        return UserAction(
            name=ua["name"], surface_id=ua["surfaceId"],
            source_component_id=ua["sourceComponentId"],
            timestamp=ua["timestamp"], context=ua.get("context", {}),
        )
    if "error" in payload:
        err = payload["error"]
        return ClientError(
            message=err.get("message", ""),
            component_id=err.get("componentId"),
            surface_id=err.get("surfaceId"),
        )
    raise ValueError("Unknown A2UI client event")


class A2UIInboundHandler:
    """把 userAction 转成 Agent 可消费的 HumanMessage / Tool Result"""
    def to_human_message(self, ua: UserAction) -> HumanMessage:
        return HumanMessage(content=f"[ui-action] {ua.name}: {json.dumps(ua.context)}")
```

---

## 7. FastAPI 端点设计

```python
# 主对话流（AG-UI Mode B：A2UI 嵌在 ACTIVITY 里）
POST /agent/chat/stream
  Accept: text/event-stream
  body:   {thread_id, message, files?,
           a2uiClientCapabilities?: {supportedCatalogIds, inlineCatalogs?}}
  → SSE of AGUIEvent

# 断线重连（返回首包 + tail 订阅）
POST /agent/chat/reconnect
  body:   {thread_id, last_run_id?}
  → SSE 按 §2.7 顺序：RUN_STARTED(parent_run_id) → MESSAGES_SNAPSHOT →
                        STATE_SNAPSHOT → ACTIVITY_SNAPSHOT×N → tail 增量

# A2UI 原生 JSONL 流（Mode A，可选）
POST /agent/a2ui/stream
  Accept: application/x-ndjson
  body:   {thread_id, message,
           a2uiClientCapabilities: {supportedCatalogIds: [...], inlineCatalogs?: [...]}}
  → JSONL of A2UI messages

# A2UI 客户端回传事件
POST /agent/a2ui/event
  body:   {userAction: {...}} 或 {error: {...}}
  → 202 Accepted（事件经 AgentManager 注入原 thread）
  幂等：以 `surfaceId + sourceComponentId + timestamp` 做请求去重
  速率：租户级 token bucket（默认 10 qps，可配）

# Agent Card（A2A 协议）
GET  /.well-known/agent-card
  → {
      name, description, url,
      capabilities: {
        extensions: [{
          uri: "https://a2ui.org/a2a-extension/a2ui/v0.8",
          params: {
            supportedCatalogIds: [
              "https://a2ui.org/specification/v0_8/standard_catalog_definition.json",
              "https://viking.tencent.com/a2ui/crm-v1.json"
            ],
            acceptsInlineCatalogs: false   // 生产关闭，开发可开
          }
        }]
      }
    }
```

---

## 8. 对现有代码的改造清单

> 仅改动点清单，不含完整实现。

### 8.1 AG-UI 层（`src/agui/`）

| 文件 | 改动 | 说明 |
|:---|:---|:---|
| `models.py` | **P0** 扩展 `AGUIEventType` | 增加 `TEXT_MESSAGE_CHUNK / TOOL_CALL_ARGS / TOOL_CALL_CHUNK / RAW / REASONING_START / REASONING_MESSAGE_START/CONTENT/END/CHUNK / REASONING_END / REASONING_ENCRYPTED_VALUE` |
| `models.py` | **P0** 工厂函数 | 把现有 `reasoning_started/content/finished` 改为对齐的 `reasoning_*` 系列（旧函数保留别名 + `DeprecationWarning` 一期） |
| `models.py` | **P0** `step_started/finished` | data 改为 `{"step_name"}`；扩展字段拆到伴随的 `CUSTOM("step_metadata")` |
| `models.py` | **P0** `tool_call_result` | 增加 `message_id` 必填参数、可选 `role="tool"` |
| `models.py` | **P1** `run_started/finished` | 支持 `parent_run_id` / `input` / `result` |
| `models.py` | P2 `BaseEvent` 字段 | 支持 `timestamp` / `raw_event`；SSE 序列化合并进 data |
| `converter.py` | **P0** 推理三段式升级 | 按 `REASONING_START → REASONING_MESSAGE_START/CONTENT/END → REASONING_END` 对齐官方分层 |
| `converter.py` | **P0** 工具事件拆 ARGS | 遍历 `chunk.tool_call_chunks` 拆 `TOOL_CALL_START / TOOL_CALL_ARGS / TOOL_CALL_END` |
| `converter.py` | **P0** STEP 语义对齐 | `step_name = skill_apikey`；扩展字段用伴随 `CUSTOM("step_metadata")` |
| `converter.py` | **P1** ModelName 分流 | 新增 `_convert_by_model_name(model_name, data, skill_apikey)`：CUSTOM_MODEL_NAMES → component_complete，TEXT_MODEL_NAMES → TEXT_MESSAGE 流 |
| `converter.py` | **P1** 子 Agent 过滤 | `parent_ids[0] != root_run_id` 时丢弃；`on_custom_event` 穿透 |
| `converter.py` | **P1** 重连快照方法 | `emit_reconnect_snapshot(messages, state_snapshot, activities, parent_run_id)` 按固定顺序下发 |
| `converter.py` | **P2** RAW 透传 | 提供 `emit_raw(event, source)` 接口 |
| `renderer.py` | **P0** STEP_FINISHED 延迟透传 | 在 `component_complete` + `STATE_DELTA` 之后再 yield 原 `STEP_FINISHED` |
| `renderer.py` | **P0** 拦截 skill_output | 收到 `CUSTOM("skill_output")` 不透传，缓存到 `_pending_skill_output` |
| `renderer.py` | **P1** 5 层匹配器 | `ComponentMatcher` 支持 bind/prefer/ModelName/schema/LLM fallback + warmup + 原子 rewarmup |
| `renderer.py` | **P1** STATE_DELTA 生成 | STEP_FINISHED 成功时产出 `/panels/<apikey>/state` + `/panels/<apikey>/data` 的 JsonPatch |

### 8.2 A2UI 层（`src/a2ui/`）

| 文件 | 改动 | 说明 |
|:---|:---|:---|
| `models.py` | **P0** `DataEntry.value_list` | 新增 `value_list` 作为规范字段名，`value_array` 标记 deprecated 但保留别名 |
| `models.py` | **P1** 客户端消息类 | 新增 `UserAction` / `ClientError` dataclass |
| `catalog.py` | **P0 新增** | `CatalogDefinition` / `CatalogRegistry` + 标准 catalog 常量 + CRM catalog + 组件元数据加载（`skill_bindings` / `supported_model_names` / `input_schema`） |
| `inbound.py` | **P0 新增** | `parse_client_event()` / `A2UIInboundHandler` |
| `stream.py` | **P1 新增** | `a2ui_jsonl_stream()` 工具，配合 FastAPI `StreamingResponse` |
| `builder.py` | **P1** `catalog_id` 默认 | 不指定时 fallback 到 `CatalogRegistry.STANDARD_V08` |
| `builder.py` | **P1** 双格式输出 | 默认产键名格式 `{"surfaceUpdate": {...}}`；可通过 `dual_format=True` 同时产出 `{"type": "surfaceUpdate", ...}` |
| `builder.py` | P2 路径规范化 | 支持 `template.dataBinding` 相对路径 `./field` / 绝对 `/data/<render_type>/$/field` |
| `aggregator.py` | **P0** 业务数据分层 | `_build_snapshot_dict` 产出 `{phase, panelLayoutOrder, panelAppearanceOrder, panelSurfaceMap, notifications, data: {<render_type>: ...}}` |
| `aggregator.py` | **P0** Shared State 绑定辅助 | 新增 `bind_a2ui_data(render_type)` 返回 `/data/<render_type>` 路径，供 Builder 直接 `path_bind()` |
| `aggregator.py` | **P1** `emit_ui` | Skill 产出 A2UI 消息后，打到对应 surface 槽位并封装成 `ACTIVITY_SNAPSHOT` |
| `emitter.py` | **P1** 双格式 | 配合 builder dual_format |
| `emitter.py` | P2 `replace=False` 语义 | 按规范：已存在同 message_id 的快照被忽略；添加语义单测 |

### 8.3 入口 & Adapter

| 文件 | 改动 |
|:---|:---|
| `src/agents/adapter.py` | **P1** `execute_agui()` 增加 `catalog_negotiation` 参数；前端能力从 API 层透传；支持 `parent_run_id` 续跑 |
| `server.py` | **P1** 新增 `/agent/a2ui/stream`（Mode A）和 `/agent/a2ui/event`（回传）路由 |
| `server.py` | **P1** `/.well-known/agent-card` 暴露 A2UI 扩展声明（supportedCatalogIds + acceptsInlineCatalogs） |
| `server.py` | **P1** `/agent/chat/reconnect` 返回断线重连首包（按 §2.7 顺序） |

### 8.4 组件元数据（`resources/a2ui/components/*.json`）

| 项 | 说明 |
|:---|:---|
| **P0 新增目录** | 参考 apps-agent `resources/agui/components/*.json` |
| **字段约定** | `type` / `description` / `input_schema` / `skill_bindings: {bind, prefer}` / `supported_model_names` |
| **加载器** | `CatalogRegistry.load()` 启动时扫描并注入到 `ComponentMatcher` |
| **Hot reload** | 新增文件触发 `rewarmup` 原子替换 4 张缓存 |

---

## 9. 测试策略

| 层 | 测试内容 | 文件 |
|:---|:---|:---|
| 单元 | 所有事件工厂函数字段正确；SSE 序列化；`timestamp/raw_event` 透传 | `tests/test_agui_models.py`（新增） |
| 单元 | 文本/推理/工具**三路互斥**状态机切换；REASONING 新旧事件双发 | `tests/test_agui_converter.py`（新增） |
| 单元 | `TOOL_CALL_ARGS` 从 `chunk.tool_call_chunks` 拆分；`TOOL_CALL_RESULT.message_id` 必填 | 同上 |
| 单元 | ModelName 分流：`component` → CUSTOM，`textResult` → TEXT_MESSAGE | 同上 |
| 单元 | `A2UIBuilder` 邻接表正确、duplicate id 报错、双格式输出 | `tests/test_a2ui_smoke.py`（扩展） |
| 单元 | `DataEntry.value_list` / BoundValue 初始化简写 | 同上 |
| 单元 | Catalog 协商：交集、inline、降级到标准 catalog | `tests/test_a2ui_catalog.py`（新增） |
| 单元 | `parse_client_event` userAction / error；未知类型 raise | `tests/test_a2ui_inbound.py`（新增） |
| 单元 | Aggregator：first / subsequent / delta 阈值 / reset；**分层快照断言** `snapshot["data"]["<render_type>"]` | 已有扩展 |
| 单元 | `bind_a2ui_data(render_type)` 返回 `/data/<render_type>` | 同上 |
| 单元 | ComponentMatcher 5 层：bind > prefer > ModelName > schema > LLM fallback；warmup + rewarmup 原子性 | `tests/test_a2ui_matcher.py`（新增） |
| 单元 | Renderer：STEP_FINISHED 延迟透传；skill_output 不穿透；STATE_DELTA 产出正确 path | `tests/test_agui_renderer.py`（新增） |
| 集成 | LangGraph → AG-UI 全事件流 Snapshot | `tests/test_agui_e2e.py`（新增） |
| 集成 | Skill 发 A2UI → Mode A JSONL 对比 snapshot | `tests/test_a2ui_jsonl_stream.py`（新增） |
| 集成 | 断线重连首包顺序断言（RUN → MESSAGES → STATE → ACTIVITY×N） | `tests/test_agui_reconnect.py`（新增） |
| 契约 | SSE 输出与官方 `ag_ui.core.Event` 反序列化兼容 | 可选 |
| 契约 | A2UI 消息与 v0.8 schema 对照（`server_to_client.json`） | 可选 |

---

## 10. 迁移与兼容性

### 10.1 向后兼容约定

- **现有 `on_custom_event` 约定保持不变**：`agent_text` / `agent_data` / `a2ui.*` / `state.patch` 等 Skill 侧已有约定由 Converter 统一翻译，无需 Skill 改动
- **`DataEntry.value_array` 保留别名**：Builder / Emitter 产出 `valueList`（规范名）时默认同时接受两者输入；一期后移除 `value_array`

### 10.2 事件名升级（双发过渡）

| 旧事件 | 新事件 | 过渡期 |
|:---|:---|:---|
| `REASONING_STARTED` | `REASONING_START` + `REASONING_MESSAGE_START` | 两周：旧+新同时发 |
| `REASONING_CONTENT` | `REASONING_MESSAGE_CONTENT` | 同上 |
| `REASONING_FINISHED` | `REASONING_MESSAGE_END` + `REASONING_END` | 同上 |

Converter 内部提供 `EMIT_LEGACY_REASONING = True` 开关，运营确认下游无人依赖旧事件后关闭。

### 10.3 字段升级

- **STEP_* 扩展字段迁移**：`skill_apikey` / `step_index` / `status` 先同时存在于 `STEP_*` data 和伴随的 `CUSTOM("step_metadata")`；两周后前端完成适配，从 `STEP_*.data` 中移除扩展字段
- **Surface 局部数据迁移**：现有 Skill 若用 `A2UIBuilder.data()` 推局部数据，改为 `aggregator.add(render_type, data)` 统一走 Shared State；`data()` API 仅保留给"真正的 surface 局部 UI 状态"场景（如表单草稿）

### 10.4 Mode A / Mode B 选择

- **默认 Mode B**（嵌入 ACTIVITY_SNAPSHOT）—— 对现有前端零改动，与 apps-agent 默认行为一致
- **Mode A**（独立 JSONL SSE）—— 引入纯 A2UI 客户端（非 CopilotKit 栈）时切换；通过 HTTP `Accept: application/x-ndjson` 协商

### 10.5 Catalog 协商渐进启用

- **Phase 1**：后端 Agent Card 声明 `supportedCatalogIds = [standard_v08, viking.crm-v1]`；前端暂不声明 capabilities，Agent 默认用 `viking.crm-v1`
- **Phase 2**：前端 A2A 消息带 `a2uiClientCapabilities`，Agent 按协商结果选择 catalog
- **Phase 3**：开放 `inlineCatalogs`（仅本地/测试环境，生产关闭）

---

## 11. 设计决策（留档）

| # | 决策 | 理由 |
|:---|:---|:---|
| D1 | AG-UI + A2UI 并存而不是二选一 | AG-UI 解决"事件流"，A2UI 解决"界面定义"，职责正交 |
| D2 | A2UI 默认走 ACTIVITY_SNAPSHOT（Mode B） | 减少 SSE 连接数，保证事件顺序一致（对齐 apps-agent 现状） |
| D3 | AG-UI 事件字段严格对齐官方 SDK | 可用官方 Python/TS 客户端直接解析，不锁定前端 |
| D4 | Skill 扩展字段拆到伴随 `CUSTOM("step_metadata")` | 规范事件保持纯净；扩展不破坏契约 |
| D5 | **业务数据 Shared State 单源**（STATE_SNAPSHOT/DELTA） | 对齐 ai-native-app v0.6+；Surface 只承载结构，避免双写冲突 |
| D6 | Catalog 协商前置到 A2A Agent Card | v0.8 §2.1 规范要求；方便多租户注册自定义组件 |
| D7 | 客户端入站事件复用 A2A 通道 | 不新增长连接，用普通 POST 即可 |
| D8 | `template` 模板语法支持相对路径 | 对齐 v0.8 动态列表；避免 LLM 生成绝对路径错位 |
| D9 | 重连首包顺序固定（RUN → MESSAGES → STATE → ACTIVITY per-surface） | 保证前端快照态可预测 |
| D10 | Aggregator 实例级隔离 | 跨 run 不共享状态；reset() 是唯一的跨 run 接口 |
| D11 | **CUSTOM 命名空间路由**（`a2ui.*` / `ui.*` / `component_*` / `step_metadata`） | 对齐 ai-native-app CustomEventDispatcher；禁止裸 CUSTOM |
| D12 | **STEP_FINISHED 延迟透传**（在 component_complete + STATE_DELTA 之后） | 前端拿到 STEP_FINISHED 时，组件数据已就位，避免闪烁 |
| D13 | **ComponentMatcher 5 层**（bind/prefer/ModelName/schema/LLM fallback） | 对齐 apps-agent 生产实践；LLM fallback 可配置关闭 |
| D14 | **ModelName 事件分流**（7 种类型） | component/relevantData/searchResults/link 走 CUSTOM；textResult/explanation/longText 走 TEXT_MESSAGE |
| D15 | **子 Agent 事件过滤**（parent_ids[0] != root） | 避免事件爆炸；`on_custom_event` 例外 |
| D16 | **双格式 A2UI 操作**（键名 + type 双产出） | 协议演进期兼容，默认键名格式 |
| D17 | **`valueList` 取代 `valueArray`** | 对齐 v0.8 规范字段名；`value_array` 保留别名一期 |
| D18 | **Skill chain `skill_` 前缀识别** | 不改动 Skill 注册层；Converter 只做转换 |
| D19 | **delta 阈值 0.5**（diff < snap * 0.5 → DELTA） | apps-agent 生产经验值；首次/无变化/异常降级为 SNAPSHOT |
| D20 | **Renderer 吸收 `skill_output`** | 内部缓存，不透传前端；前端只见 `component_complete/delta/error` |

---

## 12. 参考资料

- AG-UI Events (Python SDK): <https://docs.ag-ui.com/sdk/python/core/events>
- AG-UI Concepts - State Management: <https://docs.ag-ui.com/concepts/state>
- AG-UI AgentSubscriber: <https://docs.ag-ui.com/sdk/js/client/subscriber>
- A2UI v0.8 Protocol: <https://a2ui.org/specification/v0.8-a2ui/>
- A2UI 源 Markdown: <https://raw.githubusercontent.com/google/A2UI/main/specification/v0_8/docs/a2ui_protocol.md>

内容已根据各官方文档重新改写，确保符合许可使用约束。


---

## 13. 附录 — apps-agent × ai-native-app 双端实现对比

> 本节对照两个**已落地的生产参考实现**，归纳后端（apps-agent）与前端（ai-native-app）在 AG-UI / A2UI 协议栈上的职责划分、关键决策与设计矩阵，作为本项目设计的外部参照。
>
> - **apps-agent** = `repos/apass_old_projects/neo-apps-ai-agent-service`（Python FastAPI + LangGraph，后端生产 AG-UI / A2UI 事件）
> - **ai-native-app** = `repos/apass_old_projects/ai-native-app`（React 18 + Rspack + Module Federation + CopilotKit v2，前端消费 AG-UI / A2UI 事件）

### 13.1 角色与边界

```
┌────────────────────── apps-agent (后端 / 生产端) ──────────────────────┐
│ • LangGraph astream_events  →  AG-UI 事件流                           │
│ • Skill/Tool 产出结构化数据  →  A2UI surfaceUpdate + STATE_*           │
│ • 组件匹配、Surface 槽位分配、组件 apikey 注入                          │
│ • /rest/data/v2.0/ai/agui/copilotkit/* 系列 HTTP + SSE 端点             │
│ • 接收 /interaction（A2UI userAction）反向事件                          │
└────────────────────────────────────────────────────────────────────────┘
                             │  SSE / JSONL
                             ▼
┌───────────────────── ai-native-app (前端 / 消费端) ─────────────────────┐
│ • CopilotKit v2 (AbstractAgent + useAgent + useCoAgent)                │
│ • CustomEventDispatcher 订阅 CUSTOM → 按命名空间路由                     │
│ • A2UIBridge 把 surfaceUpdate/dataModelUpdate/beginRendering 落地到 Store │
│ • Shared State ← STATE_SNAPSHOT / STATE_DELTA 驱动（v0.6+ 统一）         │
│ • @neo-ai/ai-sdk 对外暴露 useNeoAgent / useNeoState / <A2UISurface>     │
│ • CopilotKit 防御性包装：AgentRunGuard / StateWriteGuard / MessageGuard   │
└────────────────────────────────────────────────────────────────────────┘
```

**关键分工**
- **apps-agent** 关心「如何从 Agent 运行时生成事件」：事件类型补全、转换器、渐进式渲染、快照聚合、组件 Skill 匹配
- **ai-native-app** 关心「如何把事件安全、高效地落地到 React UI」：Surface Store、Shared State 分层、渲染器、Provider 栈、LLM 幻觉防御

### 13.2 目录与模块映射

| 关注点 | apps-agent（后端） | ai-native-app（前端） | 本项目对应 |
|:---|:---|:---|:---|
| 事件模型 | `common/model/agui/` + `service/agent_agui/models.py` | `@neo-ai/ai-sdk` 类型 + `@copilotkit/react-core/v2` 事件 | `src/agui/models.py` |
| 事件转换 | `service/agent_agui/agent_v2/converter.py`（LangGraph → AG-UI） | CopilotKit Runtime 内部消费 | `src/agui/converter.py` |
| 渐进式渲染 | `service/agent_agui/agent_v2/renderer.py` | CustomEventDispatcher + A2UIBridge 被动接收 | `src/agui/renderer.py` |
| 快照聚合 | `service/agent_agui/agent_v2/snapshot.py`（V2SnapshotAggregator） | `A2UIGlobalProvider` 的 `surfacesRef` + Shared State | `src/a2ui/aggregator.py` |
| 组件匹配 | `service/agent_agui/components/matcher.py`（5 层匹配 + LLM fallback） | `ComponentRegistry.getEntry` + `PropsValidator` | `ComponentMatcher`（现状只做静态字典） |
| 布局元数据 | `resources/agui/components/*.json` + `layout_registry.py` + `data_schema_registry.py` | `ai-manifest.ts`（业务线声明） + `ComponentRegistry` | 对应 `Catalog` 概念，需要补齐 |
| Shared State | STATE_SNAPSHOT/STATE_DELTA + panelSurfaceMap | `A2UIGlobalProvider` + `useNeoState`（v0.6 之后 dataModels 废弃） | 对应 `Aggregator.data.*` 分层 |
| UserAction | `/rest/data/v2.0/ai/agui/interaction`（A2UI v0.8 `userAction`） | CopilotKit `agent.subscribe({ onCustomEvent })` 反向通过 A2A 回传 | 设计里的 `/agent/a2ui/event` + `inbound.py` |

### 13.3 事件类型 × 实际落地差异

| 规范事件 | apps-agent 现状 | ai-native-app 现状 | 本项目设计取舍 |
|:---|:---|:---|:---|
| `RUN_STARTED/FINISHED/ERROR` | ✅ 有，携带 `run_id/thread_id` | ✅ 订阅 | 字段扩展支持 `parent_run_id / input / result` |
| `STEP_STARTED/FINISHED` | ✅ 含 `skill_apikey / step_index / status` | ✅ 订阅 | 对齐官方只留 `step_name`，扩展字段走伴随 CUSTOM |
| `TEXT_MESSAGE_*` | ✅ 三段式 | ✅ 三段式 | 补齐 `TEXT_MESSAGE_CHUNK` |
| `TOOL_CALL_START/END/RESULT` | ✅ 三段（缺 ARGS） | ✅ 订阅 | 补齐 `TOOL_CALL_ARGS / CHUNK`，`TOOL_CALL_RESULT` 加 `message_id` |
| `REASONING_*` | 旧名：STARTED/CONTENT/FINISHED | ✅ 老事件，随 copilotkit 升级为 START/MESSAGE_*/END | 对齐官方最新分层（START/END + MESSAGE_START/CONTENT/END/CHUNK + ENCRYPTED_VALUE） |
| `STATE_SNAPSHOT / STATE_DELTA` | ✅ 每 Skill 完成后发；panelSurfaceMap + notifications 平铺 | ✅ 作为唯一 Shared State 驱动源（v0.6 统一） | **采用 ai-native-app 方案**：业务数据分层到 `data.*`，元数据放外层 |
| `MESSAGES_SNAPSHOT` | ✅ STEP_FINISHED 后发 + 会话初始化发 | ✅ 订阅同步 | 延续 apps-agent 策略 |
| `ACTIVITY_SNAPSHOT / ACTIVITY_DELTA` | ✅ 承载 A2UI surfaceUpdate（`activityType: "a2ui-surface"`） | ✅ A2UIBridge 消费 `content.operations` | 默认 Mode B（嵌入 ACTIVITY），Mode A（独立 JSONL）做可选 |
| `CUSTOM` | ✅ 组件渲染唯一通道（component_loading/complete/error/data） | ✅ CustomEventDispatcher 按 `a2ui.*` / `ui.*` 命名空间路由 | **采纳 ai-native-app 命名空间路由**：`a2ui.*` / `ui.*` / `component_*` 三组 |
| `RAW` | ❌ 未支持 | ❌ 未消费 | 设计里保留扩展点 |

### 13.4 A2UI 协议对照 v0.8

| v0.8 条目 | apps-agent 落地 | ai-native-app 落地 | 本项目采纳 |
|:---|:---|:---|:---|
| 四种服务端消息（surfaceUpdate / dataModelUpdate / beginRendering / deleteSurface） | ✅ 全支持，通过 `content.operations` 打包 | ✅ `A2UIBridge` 识别 `type` 或 键名两种格式 | ✅ models.py 已覆盖 |
| 邻接表模型（组件平坦列表） | ✅ | ✅ 递归渲染 | ✅ |
| BoundValue（`path` / `literal*` / 初始化简写） | ✅ 产出 `path` 引用 Shared State | ✅ `A2UITreeRenderer.getValue` 支持 path + literal\* + 向后兼容 jsonRef/stateRef | ✅ `BoundValue` + `literal() / path_bind()` 完整 |
| DataEntry 类型（valueString/valueInt/valueNumber/valueBoolean/valueMap/**valueList**） | ⚠️ 命名以 `valueArray`（非规范） | ✅ 前端接受 `valueList` | **统一用 valueList**（规范名），`value_array` 作为 deprecated 别名 |
| Catalog 协商（Agent Card + beginRendering.catalogId） | ❌ 未实现，靠 resources/agui/components/\*.json 固定 | ⚠️ `a2ui-catalog-bridge-design.md` 指出未打通，两套 registry 隔离 | **新增 `src/a2ui/catalog.py`**：服务端注册表 + 协商逻辑 |
| 动态列表 template（dataBinding + componentId） | ❌ 未用 | ⚠️ 前端可渲染，但 mock 中未普及 | 设计支持；作 P2 |
| 客户端入站事件（userAction / error） | ✅ 已实现 `/interaction` 端点对齐 v0.8 `userAction` | ✅ CopilotKit A2A 消息回传 | **新增 `src/a2ui/inbound.py`** + `/agent/a2ui/event` |

### 13.5 架构决策差异与取舍

| 决策点 | apps-agent | ai-native-app | 本项目取舍与理由 |
|:---|:---|:---|:---|
| **数据归属** | Surface 自带局部数据（`surfaceUpdate` 里绑 `dataModelUpdate`） | **Shared State 唯一**：`dataModelUpdate` 废弃，统一 `STATE_SNAPSHOT/DELTA` | 采纳 ai-native-app 方案；Builder 仍产 dataModelUpdate 但建议后端把数据汇入 Shared State，Surface 只做结构 |
| **Surface 槽位分配** | Aggregator 自动分配 `panel-slot-N`，维护 `panelSurfaceMap` | 前端根据 surfaceId 字面量挂载 `<A2UISurface>` | 后端分配 + 前端 declarative 挂载，两者结合 |
| **组件匹配 5 层** | `bind / prefer / ModelName / schema / LLM fallback` | 前端注册表是被动查找，没有 LLM 兜底 | 采纳后端 5 层；`LLM fallback` 可关（多租户隔离时） |
| **多 Surface 并发** | 按 `render_type → surface` 自动分配，ACTIVITY_SNAPSHOT 一次性下发 | `A2UIGlobalProvider` 维护 `Map<surfaceId, SurfaceData>` + Set 监听 | 后端专注内容产出，前端用 `useSyncExternalStore` 订阅 |
| **事件命名空间** | 以 `a2ui.*` / `skill_output` / `component_*` 自由使用 | CustomEventDispatcher 只认 `a2ui.*`（走 Bridge）+ `ui.*`（走 eventBus） | 规范 4 个命名空间：`a2ui.*` / `ui.*` / `component_*` / `step_*`（伴随 CUSTOM） |
| **防御机制** | 后端无前端防御需求 | `AgentRunGuard`（去重/节流/并发） + `StateWriteGuard`（类型+方向约束） + `MessageGuard`（角色校验） | 本项目是后端，不直接承担；但在 `/agent/a2ui/event` 做幂等 + 速率限制 |
| **Props 运行时校验** | 组件 JSON 里带 schema，供匹配用 | `PropsValidator` 编译 propsSchema → 渲染时校验 LLM 幻觉 | 后端只做 Schema 声明；前端消费方（ai-native-app）继续做 PropsValidator |
| **LLM 事件分流（ModelName）** | `ModelNameType` 7 种（component/relevantData/searchResults/link/textResult/explanation/longText），决定走 CUSTOM 还是 TEXT_MESSAGE | 前端无此概念 | 作为 `render_hint` 语义保留在 Tool/Skill 层，由 Converter 决定事件分流 |
| **断线重连** | `emit_reconnect_snapshot`：MESSAGES_SNAPSHOT + STATE_SNAPSHOT（历史重放 + tail） | CopilotKit `/connect` 拉取历史 + 订阅 tail | 本项目 `/agent/chat/reconnect` 下发：`RUN_STARTED(parent_run_id) → MESSAGES_SNAPSHOT → STATE_SNAPSHOT → ACTIVITY_SNAPSHOT(每个活跃 surface)` |
| **子 Agent 事件过滤** | `parent_ids[0] != _root_run_id` 时丢弃（on_custom_event 例外） | 不处理 | 沿用 apps-agent 策略 |
| **Skill chain 前缀识别** | `on_chain_start/end` + `skill_` 前缀 → STEP 事件 | 不感知 | 沿用 apps-agent |
| **Mock / 开发** | 无，直连 LangGraph | `scripts/mock-copilot-runtime.mjs`（SSE mock） | 本项目提供 `server.py --mock` 参数输出稳定事件 |
| **前端 Catalog 桥接** | N/A | CopilotKit 内置 A2UI 和自建 registry 是两套，需 `CatalogBridge` 适配 Props 契约 | 后端产出规范 catalogId；前端桥接由 ai-native-app 负责 |

### 13.6 融合传输策略（两端合谋）

apps-agent 当前**主通道 = ACTIVITY_SNAPSHOT + STATE_SNAPSHOT**（嵌入 AG-UI）：

```
apps-agent emit:                      ai-native-app consume:
  STATE_SNAPSHOT {data.*, meta}   →     useNeoState 响应
  ACTIVITY_SNAPSHOT {                  A2UIBridge.dispatch("a2ui.render") →
    activityType: "a2ui-surface",      [surfaceUpdate / dataModelUpdate / beginRendering]
    content.operations: [...]            → SurfaceStore.setSurface()
  }
  CUSTOM {name: "component_loading",  → CustomEventDispatcher → A2UIBridge
         value: {apikey, state}}
```

ai-native-app 中的 A2UIBridge 同时支持两种消息格式：
- `{type: "surfaceUpdate", components}`（类型标识）
- `{surfaceUpdate: {components}}`（键名标识，A2UI 官方）

**本项目做法**：后端 Emitter 两种格式都产出，默认用官方键名格式，保证双前端都能消费。

### 13.7 差距清单（现状 vs 生产参考）

| 缺口 | apps-agent 已有 | ai-native-app 已有 | 本项目需补（P0→P2） |
|:---|:---:|:---:|:---|
| REASONING 事件按新规范分层 | ❌（老名） | ✅（订阅新 SDK） | **P0** 按官方 START/MESSAGE_*/END 对齐（双发过渡） |
| TOOL_CALL_ARGS / CHUNK | ❌ | ✅ | **P0** converter 拆出 args chunk |
| TOOL_CALL_RESULT.message_id | ❌ | ✅ | **P0** 工厂函数加参数 |
| STEP_* 字段对齐 + 伴随 CUSTOM | ⚠️（扩展字段塞进 data） | ✅（订阅 step_name） | **P0** 规范 step_name + CUSTOM(step_metadata) |
| DataEntry.valueList | ❌（valueArray） | ✅ | **P0** 改名 + 兼容别名 |
| Catalog 协商端到端 | ❌ | ⚠️（两端 registry 隔离） | **P1** 新增 `catalog.py` + Agent Card 声明 + `beginRendering.catalogId` |
| 客户端 userAction/error 入站 | ✅（/interaction） | ✅（A2A 回传） | **P1** 新增 `inbound.py` + `/agent/a2ui/event` |
| 独立 A2UI JSONL 通道（Mode A） | ❌（只有 Mode B） | N/A | **P2** `stream.py` + `/agent/a2ui/stream` |
| Shared State 分层（data.* + meta） | ⚠️（业务数据与 meta 平铺） | ✅（Shared State 唯一源） | **P0** aggregator `_build_snapshot_dict` 重构 |
| ComponentMatcher 5 层 + LLM fallback | ✅ | N/A | **P1** 扩展 `ComponentMatcher`，bind > prefer > ModelName > schema > LLM |
| 断线重连首包顺序 | ⚠️（发消息快照） | ⚠️（CK /connect） | **P1** `emit_reconnect_snapshot` 按 RUN→MESSAGES→STATE→每 surface ACTIVITY 顺序 |
| RAW 事件 | ❌ | ❌ | **P2** 保留扩展点 |

### 13.8 小结 — 本项目应吸收的最佳实践

1. **后端事件生成**（从 apps-agent）：
   - V2AGUIConverter 的三流状态机（文本/推理/工具）
   - 5 层组件匹配 + LLM fallback + 启动预热 + 原子 rewarmup
   - `_handle_tool_end` 不阻塞 agent_text 流式，STEP_FINISHED 只做标记
   - 快照 delta 阈值判断（diff_size < snap_size * 0.5）

2. **前端契约约束**（从 ai-native-app）：
   - Shared State 为唯一业务数据源（从 STATE_SNAPSHOT/DELTA 驱动），Surface 只承载结构
   - BoundValue 解析支持 `path` 主路径 + `literal*` fallback + 向后兼容 `jsonRef/stateRef`
   - CustomEventDispatcher 命名空间路由策略
   - A2UIBridge 同时支持 `type` 和键名两种操作格式，解决协议演进期双版本共存

3. **协议实现一致性**（两端都要保持）：
   - `valueList` 规范字段名
   - catalogId 显式传递（Agent Card + beginRendering）
   - userAction 走独立端点（而非混进 SSE）
   - parent_run_id 支持时间旅行 / 断线重连
