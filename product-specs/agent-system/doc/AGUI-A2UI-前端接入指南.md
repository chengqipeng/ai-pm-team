# AG-UI × A2UI 前端接入指南

面向：想把 DeepAgent 接入到自己前端（CopilotKit v2 / 纯 A2UI 客户端 / 自建 SSE 消费者）的开发者。

配套设计文档：[`AGUI-A2UI-协议层设计.md`](./AGUI-A2UI-协议层设计.md)
参考实现：`repos/apass_old_projects/ai-native-app`（React 18 + CopilotKit v2 + 自建 A2UI 渲染器）

---

## 1. 总览：2 条通道，3 类事件

```
┌─────────────────────────────────────────────────────────────┐
│  后端                                                        │
│                                                              │
│   /agent/chat/stream                 /agent/a2ui/stream      │
│   (AG-UI SSE，默认 Mode B)           (纯 A2UI NDJSON/SSE，Mode A) │
│        │                                    │                │
└────────┼────────────────────────────────────┼───────────────┘
         │ SSE / 事件流                        │ JSONL
         ▼                                    ▼
┌─────────────────────────────────────────────────────────────┐
│  前端                                                        │
│                                                              │
│  AG-UI 客户端订阅：                   A2UI 客户端直接渲染:     │
│    - RUN_STARTED/FINISHED/ERROR       - surfaceUpdate       │
│    - TEXT_MESSAGE_*                   - dataModelUpdate     │
│    - REASONING_*                      - beginRendering      │
│    - TOOL_CALL_*                      - deleteSurface       │
│    - MESSAGES_SNAPSHOT                                      │
│    - STATE_SNAPSHOT/DELTA                                   │
│    - ACTIVITY_SNAPSHOT   ──►  承载 A2UI operations          │
│    - CUSTOM              ──►  a2ui.* / ui.* / component_*   │
│                                                              │
│         ▲                                                    │
│         │ POST /agent/a2ui/event                             │
│         │ (userAction / error)                               │
└─────────────────────────────────────────────────────────────┘
```

**关键原则**
- 业务数据以 `STATE_SNAPSHOT` / `STATE_DELTA` 为**唯一来源**，存在一个全局 Shared State
- UI 结构以 `ACTIVITY_SNAPSHOT`（Mode B）或 JSONL（Mode A）发送，`surfaceUpdate` 里的 `path` 绑定 Shared State
- CUSTOM 事件带命名空间前缀，按前缀路由

---

## 2. 选择接入模式

| 场景 | 推荐 | 说明 |
|:---|:---|:---|
| 已有 CopilotKit v2 前端 | **Mode B**（默认） | 单 SSE 连接复用；A2UI 消息嵌入 `ACTIVITY_SNAPSHOT` |
| 新建纯 A2UI 前端（Flutter / 原生 Web） | **Mode A** | 官方 v0.8 JSONL 流，事件语义最小 |
| 想要 Chat + 动态 UI 双重能力 | **Mode B** | Chat 走 AG-UI 通道，组件走 CUSTOM `a2ui.*` 通道 |

---

## 3. 端点清单

| Method | Path | 用途 |
|:---|:---|:---|
| GET | `/.well-known/agent-card` | 查询 Agent 支持的 catalog |
| POST | `/agent/chat/stream` | AG-UI 主对话流（SSE） |
| POST | `/agent/a2ui/stream` | 纯 A2UI 流（Mode A） |
| POST | `/agent/a2ui/event` | 客户端回传 userAction / error |
| POST | `/agent/chat/reconnect` | 断线重连首包 + tail 订阅 |

---

## 4. 接入 Checklist（Mode B，CopilotKit v2 / 自建 SSE 都适用）

### 4.1 启动阶段 · Catalog 协商

```http
GET /.well-known/agent-card
```

返回示例：
```json
{
  "name": "DeepAgent CRM",
  "capabilities": {
    "streaming": true,
    "extensions": [{
      "uri": "https://a2ui.org/a2a-extension/a2ui/v0.8",
      "params": {
        "supportedCatalogIds": [
          "https://a2ui.org/specification/v0_8/standard_catalog_definition.json",
          "https://viking.tencent.com/a2ui/crm-v1.json"
        ],
        "acceptsInlineCatalogs": false
      }
    }]
  }
}
```

**你要做的：**
- [ ] 把前端能渲染的 catalog id 组织成 `a2uiClientCapabilities.supportedCatalogIds`
- [ ] 发对话请求时在 body 里附带（或 A2A metadata 里）这个对象
- [ ] 后端会选交集 catalog 并在 `beginRendering.catalogId` 里回传

### 4.2 运行阶段 · SSE 事件订阅

订阅以下事件（CopilotKit v2 的 `agent.subscribe({...})` 完整回调名参考 ai-native-app）：

```typescript
agent.subscribe({
  // ── 生命周期 ──
  onRunStartedEvent:   ({event}) => { /* event.parent_run_id 实现时间旅行 */ },
  onRunFinishedEvent:  ({event}) => {},
  onRunErrorEvent:     ({event}) => { /* event.message + event.code */ },

  // ── 文本流（消息气泡）──
  onTextMessageStartEvent:   ({event}) => startBubble(event.message_id),
  onTextMessageContentEvent: ({event}) => appendBubble(event.message_id, event.delta),
  onTextMessageEndEvent:     ({event}) => endBubble(event.message_id),

  // ── 工具调用（显示 [调用工具 X] 徽章）──
  onToolCallStartEvent:   ({event}) => {},
  onToolCallArgsEvent:    ({event}) => {},   // ← 拼 tool args JSON
  onToolCallEndEvent:     ({event}) => {},
  onToolCallResultEvent:  ({event}) => {},   // 必有 message_id + role="tool"

  // ── 推理（折叠面板）──
  onReasoningStartEvent:         ({event}) => {},
  onReasoningMessageStartEvent:  ({event}) => {},
  onReasoningMessageContentEvent:({event}) => {},
  onReasoningMessageEndEvent:    ({event}) => {},
  onReasoningEndEvent:           ({event}) => {},

  // ── 快照 ──
  onMessagesSnapshotEvent: ({event}) => rehydrate(event.messages),
  onStateSnapshotEvent:    ({event}) => setSharedState(event.snapshot),
  onStateDeltaEvent:       ({event}) => applyJsonPatch(event.delta),

  // ── A2UI 操作（Mode B 核心）──
  onActivitySnapshotEvent: ({event}) => {
    if (event.activity_type === "a2ui-surface") {
      // event.content.operations = [<surfaceUpdate>, <dataModelUpdate?>, <beginRendering>]
      a2uiRenderer.dispatch(event.message_id, event.content.operations);
    }
  },
  onActivityDeltaEvent: ({event}) => {
    if (event.activity_type === "a2ui-surface") {
      a2uiRenderer.applyPatch(event.message_id, event.patch);
    }
  },

  // ── 扩展（命名空间路由）──
  onCustomEvent: ({event}) => {
    if (event.name.startsWith("a2ui.")) a2uiBridge.dispatch(event.name, event.value);
    else if (event.name.startsWith("ui.")) eventBus.emit(event.name.slice(3), event.value);
    else if (event.name.startsWith("component_")) componentStateUpdater(event.name, event.value);
    else if (event.name === "step_metadata") traceSidebar.recordStep(event.value);
    else console.warn("Unknown CUSTOM namespace:", event.name);
  },
});
```

**你要做的：**
- [ ] 实现 Shared State 存储（对齐 ai-native-app 的 `useNeoState` 思路，全局唯一）
- [ ] 实现 `applyJsonPatch(state, patch)`（RFC 6902）
- [ ] 实现 A2UI Bridge：把 `{surfaceUpdate, dataModelUpdate, beginRendering, deleteSurface}` 落地到 SurfaceStore
- [ ] 实现 CUSTOM 命名空间路由（见上面代码）

### 4.3 A2UI Renderer 关键点

前端把 A2UI 操作解析到 SurfaceStore 时要注意：

- [ ] **组件 id 唯一**：同 id 的 `surfaceUpdate.components` 是覆盖语义
- [ ] **邻接表展开**：渲染时从 `beginRendering.root` 开始递归，通过 id 查表
- [ ] **BoundValue 解析**：
  - `{literalString: "hi"}` → 直接用
  - `{path: "/user/name"}` → 从 Shared State JSON Pointer 读取
  - `{path: "...", literalString: "default"}` → **先写入 Shared State**，再绑定
- [ ] **模板列表**：`children.template = {dataBinding, componentId}` 遍历数组，每项用模板组件渲染；相对路径 `./field` 解析为当前项字段
- [ ] **组件找不到时**：显示占位符，不要抛异常
- [ ] **LLM 幻觉防御**：对组件 props 做运行时 schema 校验（参考 ai-native-app `PropsValidator`）

### 4.4 用户交互回传

当用户点击 A2UI 组件触发 action：

```http
POST /agent/a2ui/event
Content-Type: application/json

{
  "threadId": "t-123",
  "userAction": {
    "name": "open_opportunity",
    "surfaceId": "panel-slot-1",
    "sourceComponentId": "detail_btn",
    "timestamp": "2026-05-07T10:05:00Z",
    "context": {
      "recordId": "C1"
    }
  }
}
```

**你要做的：**
- [ ] 按规范 `timestamp` 用 ISO 8601
- [ ] `context` 里的 `BoundValue` 已经由前端 **resolve 成实际值**（不是 `{path: ...}` 对象）
- [ ] 接收 `202 Accepted`，其中 `{status: "accepted" | "duplicate"}` 可用作本地日志
- [ ] **不要等同步响应** —— 后续 Agent 行为继续通过原 SSE 推送

返回错误：
```json
{"error": {"message": "render failed", "componentId": "title", "surfaceId": "panel-slot-1"}}
```

### 4.5 断线重连

当 SSE 连接断掉（刷新页面 / 网络抖动）：

```http
POST /agent/chat/reconnect
{
  "threadId": "t-123",
  "lastRunId": "r-old"    // 可选：上一次看到的 run_id，用于时间旅行/debug
}
```

服务端返回 SSE，**固定顺序**：

1. `RUN_STARTED`（`parent_run_id = lastRunId`）
2. `MESSAGES_SNAPSHOT`（完整历史消息）
3. `STATE_SNAPSHOT`（业务状态全量 = Shared State）
4. `ACTIVITY_SNAPSHOT × N`（每个活跃 surface 一次）
5. 恢复增量推送

**你要做的：**
- [ ] 收到 `RUN_STARTED.parent_run_id` 后清空本地临时消息气泡
- [ ] 应用 `MESSAGES_SNAPSHOT` / `STATE_SNAPSHOT` **覆盖**本地缓存（不要合并）
- [ ] 对每条 `ACTIVITY_SNAPSHOT(replace=true)` 重建 surface
- [ ] 之后继续监听 tail（可复用同一 SSE 通道）

---

## 5. 接入 Checklist（Mode A，纯 A2UI 客户端）

### 5.1 建立连接

```http
POST /agent/a2ui/stream
Accept: application/x-ndjson            # 或 text/event-stream
Content-Type: application/json

{
  "threadId": "t-456",
  "message": "查看 Q3 Top10 客户",
  "a2uiClientCapabilities": {
    "supportedCatalogIds": [
      "https://viking.tencent.com/a2ui/crm-v1.json"
    ]
  }
}
```

响应 header 里 `X-A2UI-Catalog` 回传 Agent 选用的 catalog id。

### 5.2 解析 NDJSON

每行一条 A2UI 消息：

```jsonl
{"surfaceUpdate": {"surfaceId":"s1","components":[...]}}
{"dataModelUpdate": {"surfaceId":"s1","contents":[{"key":"name","valueString":"Bob"}]}}
{"beginRendering": {"surfaceId":"s1","root":"root","catalogId":"..."}}
{"deleteSurface": {"surfaceId":"s2"}}
```

SSE 版本（Accept: text/event-stream）：
```
event: a2ui
data: {"surfaceUpdate": {...}}

event: a2ui
data: {"beginRendering": {...}}
```

### 5.3 用户交互

同 Mode B：走 `POST /agent/a2ui/event`。

### 5.4 客户端状态机

```
IDLE
  │  建立 /agent/a2ui/stream 连接
  ▼
BUFFERING  ← surfaceUpdate / dataModelUpdate 累积到内部 Buffer
  │  收到 beginRendering
  ▼
RENDERING  ← 从 root 递归展开邻接表
  │  surfaceUpdate（同 surfaceId 增量）继续消费
  ▼
ACTIVE     ← 用户交互 → /agent/a2ui/event → 服务端响应新的 surfaceUpdate
  │  deleteSurface 清空对应 surface
  ▼
CLOSED
```

---

## 6. 常见问题

### Q1: 为什么 Shared State 不分 surface？

A2UI v0.8 规范允许每个 surface 有自己的 data model，但我们参考 ai-native-app v0.6+ 的经验，把业务数据统一放 Shared State。好处：
- 多个 surface 可共享同一份数据
- 断线重连只需恢复一个对象
- `dataModelUpdate` 现在只用于**真正 surface 局部的 UI 状态**（表单草稿、折叠开关等）

### Q2: REASONING_* 事件怎么处理？

两层：
- `REASONING_START / REASONING_END` 是**包围事件**，前端用来显示"思考中…" 提示
- `REASONING_MESSAGE_START/CONTENT/END` 是**真正的消息事件**，需要拼接成一条 role="reasoning" 的消息

ai-native-app 的处理：用折叠面板展示，默认收起，用户可点开看推理过程。

### Q3: `CUSTOM("component_loading/complete/error")` 是干什么的？

Skill 执行时 Renderer 自动产出：
- `component_loading` → 组件骨架屏
- `component_delta` → 渐进式渲染（可选）
- `component_complete` → 数据到位，渲染完整内容
- `component_error` → Skill 失败，显示错误状态

前端把这些状态绑在 `/panels/<apikey>/state` 的 Shared State 路径上（Renderer 同时会发 `STATE_DELTA` 更新该路径）。

### Q4: userAction 必须同步回传吗？

不必。Fire-and-forget 即可：`POST /agent/a2ui/event` 返回 `202`，后续 Agent 行为通过原 SSE 推送。这是 v0.8 §5 的规范方式。

### Q5: 多个 surface 如何区分？

- 后端 `SnapshotAggregator` 按 `render_type` 自动分配 `panel-slot-N`
- 前端挂载 `<A2UISurface surfaceId="panel-slot-1" />` 声明式占位
- `snapshot.panelLayoutOrder` 告诉前端面板排列顺序
- `snapshot.panelSurfaceMap` 给前端查 `render_type → surface_id` 的反向映射

### Q6: 如果我的前端不支持 catalog 里的某个组件？

- 先在前端实现一个占位 UI（ai-native-app `UnregisteredComponentPlaceholder`）
- 未注册组件仍能正常解析邻接表，只是不渲染
- 生产环境建议 catalog 与前端组件库**版本号对齐**，这样能提前在 CI 里校验

---

## 7. 调试工具

| 工具 | 用途 |
|:---|:---|
| `python demo_a2ui_skill.py` | 后端侧产出的 AG-UI 事件完整示例 |
| 浏览器 EventSource 原生 API | 用 `new EventSource("/agent/chat/stream?...")` 快速看 SSE |
| `curl -N` | `curl -N -H "Accept: text/event-stream" -X POST ... /agent/chat/stream` 直接看流 |
| `/agent/chat/reconnect` 抓包 | 验证断线重连首包顺序 |
| `.kiro/steering/a2ui-debug-cheatsheet.md` | Kiro 一键命令调试 A2UI |

---

## 8. 参考资源

- AG-UI 官方 Events: <https://docs.ag-ui.com/sdk/python/core/events>
- A2UI v0.8 规范: <https://a2ui.org/specification/v0.8-a2ui/>
- 协议层设计文档: `doc/AGUI-A2UI-协议层设计.md`
- 参考实现（前端）: `repos/apass_old_projects/ai-native-app/apps/host-app/src/modules/ai-engine/`
- 参考实现（后端）: `repos/apass_old_projects/neo-apps-ai-agent-service/service/agent_agui/`

---

## 9. Checklist 汇总

**Mode B（推荐）最小可用接入：**
- [ ] 拉取 `/.well-known/agent-card` 获取支持的 catalog
- [ ] 发对话请求时带 `a2uiClientCapabilities`
- [ ] 订阅 AG-UI SSE 的 12+ 种事件（见 §4.2）
- [ ] 实现 Shared State + JSON Patch
- [ ] 实现 A2UI Bridge（surfaceUpdate / dataModelUpdate / beginRendering / deleteSurface）
- [ ] 实现 BoundValue 解析（path / literal* / 初始化简写）
- [ ] 实现 CUSTOM 命名空间路由
- [ ] 用户交互 POST `/agent/a2ui/event`
- [ ] 断线重连 POST `/agent/chat/reconnect`
- [ ] （可选）PropsValidator 防 LLM 幻觉
- [ ] （可选）未注册组件占位符

**Mode A（纯 A2UI 客户端）最小可用接入：**
- [ ] POST `/agent/a2ui/stream` 接 NDJSON / SSE
- [ ] 解析四种 A2UI 消息并构建邻接表
- [ ] 用户交互 POST `/agent/a2ui/event`
