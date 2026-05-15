# AG-UI × A2UI 详细设计（基于代码实现）

> 基于 `src/agui/` 和 `src/a2ui/` 的实际代码，详细描述从 Agent 执行到前端渲染的完整数据流。

---

## 一、系统总览

### 1.1 两层协议定位

| 协议 | 代码位置 | 职责 | 传输方式 |
|------|----------|------|----------|
| AG-UI | `src/agui/` | Agent 运行时事件流 — "Agent 在做什么" | SSE (text/event-stream) |
| A2UI | `src/a2ui/` | 声明式 UI 定义 — "Agent 想让用户看到什么" | 嵌入 AG-UI ACTIVITY 事件 (Mode B) 或独立 NDJSON 流 (Mode A) |

### 1.2 代码模块地图

```
src/agui/                          src/a2ui/
├── models.py     事件类型+工厂     ├── models.py      数据模型(BoundValue/Component/Message)
├── converter.py  LangGraph→AG-UI   ├── builder.py     流畅API构建surface
├── renderer.py   渐进式组件渲染    ├── aggregator.py  业务状态聚合+STATE事件
├── pipeline.py   管道工厂          ├── emitter.py     Mode A/B 事件包装
└── __init__.py                     ├── catalog.py     组件目录+协商+5层匹配
                                    ├── inbound.py     客户端入站(userAction/error)
                                    ├── projector.py   AG-UI→A2UI投影
                                    ├── stream.py      JSONL/SSE流输出
                                    ├── render_helper.py 一站式渲染辅助
                                    ├── thread_store.py  重连态持有
                                    └── __init__.py

src/agents/adapter.py              src/api/a2ui_routes.py
└── NeoAgentV2Adapter              └── FastAPI路由(5个端点)
    ├── execute_agui()                 ├── /.well-known/agent-card
    ├── execute_a2ui()                 ├── /agent/a2ui/event
    └── inject_message()               ├── /agent/a2ui/stream
                                       ├── /agent/chat/reconnect
                                       └── /api/chat/agui
```


---

## 二、AG-UI 事件层详细设计

### 2.1 事件类型完整清单（models.py）

```python
class AGUIEventType(str, Enum):
    # 运行生命周期
    RUN_STARTED   = "RUN_STARTED"      # {thread_id, run_id, parent_run_id?}
    RUN_FINISHED  = "RUN_FINISHED"     # {thread_id, run_id, result?}
    RUN_ERROR     = "RUN_ERROR"        # {message, code?}

    # 步骤（Skill 执行单元）
    STEP_STARTED  = "STEP_STARTED"     # {step_name}
    STEP_FINISHED = "STEP_FINISHED"    # {step_name}

    # 文本消息（对话气泡）
    TEXT_MESSAGE_START   = "TEXT_MESSAGE_START"    # {message_id, role}
    TEXT_MESSAGE_CONTENT = "TEXT_MESSAGE_CONTENT"  # {message_id, delta}
    TEXT_MESSAGE_END     = "TEXT_MESSAGE_END"      # {message_id}

    # 工具调用
    TOOL_CALL_START  = "TOOL_CALL_START"   # {tool_call_id, tool_call_name}
    TOOL_CALL_ARGS   = "TOOL_CALL_ARGS"    # {tool_call_id, delta}
    TOOL_CALL_END    = "TOOL_CALL_END"     # {tool_call_id}
    TOOL_CALL_RESULT = "TOOL_CALL_RESULT"  # {message_id, tool_call_id, content}

    # 推理过程（新分层）
    REASONING_START           = "REASONING_START"
    REASONING_MESSAGE_START   = "REASONING_MESSAGE_START"
    REASONING_MESSAGE_CONTENT = "REASONING_MESSAGE_CONTENT"
    REASONING_MESSAGE_END     = "REASONING_MESSAGE_END"
    REASONING_END             = "REASONING_END"

    # 状态快照
    STATE_SNAPSHOT    = "STATE_SNAPSHOT"     # {snapshot: {...}}
    STATE_DELTA       = "STATE_DELTA"        # {delta: [JsonPatch]}
    MESSAGES_SNAPSHOT = "MESSAGES_SNAPSHOT"  # {messages: [...]}

    # A2UI 承载通道
    ACTIVITY_SNAPSHOT = "ACTIVITY_SNAPSHOT"  # {message_id, activity_type, content}
    ACTIVITY_DELTA    = "ACTIVITY_DELTA"     # {message_id, activity_type, patch}

    # 扩展
    CUSTOM = "CUSTOM"    # {name, value}
    RAW    = "RAW"       # {event, source?}
```

### 2.2 AGUIConverter 核心逻辑（converter.py）

AGUIConverter 订阅 LangGraph `astream_events(v2)`，将内部事件映射为标准 AG-UI 事件。

#### 三流互斥状态机

```
┌──────────┐     ┌──────────┐     ┌──────────┐
│ 文本流    │ ←→ │ 推理流    │ ←→ │ 工具调用流 │
│ _text_   │     │ _reason_ │     │ _tool_   │
│ active   │     │ active   │     │ started  │
└──────────┘     └──────────┘     └──────────┘
     任何一个开启前，先关闭其他两个（发 END 事件）
```

#### 事件映射规则

| LangGraph 事件 | 条件 | 产出的 AG-UI 事件 |
|---------------|------|------------------|
| `on_chat_model_stream` 文本 chunk | 首 chunk | TEXT_MESSAGE_START + TEXT_MESSAGE_CONTENT |
| `on_chat_model_stream` 文本 chunk | 后续 chunk | TEXT_MESSAGE_CONTENT |
| `on_chat_model_stream` thinking block | 首块 | REASONING_START + REASONING_MESSAGE_START + CONTENT |
| `on_chat_model_stream` tool_call_chunks | 首 chunk | TOOL_CALL_START |
| `on_chat_model_stream` tool_call_chunks | argsDelta | TOOL_CALL_ARGS |
| `on_tool_end` | — | TOOL_CALL_RESULT + TOOL_CALL_END |
| `on_chain_start` name=skill_xxx | — | STEP_STARTED + CUSTOM(step_metadata) |
| `on_chain_end` name=skill_xxx | — | CUSTOM(skill_output) + STEP_FINISHED |
| `on_custom_event` name=agent_text | — | TEXT_MESSAGE_* 三段式 |
| `on_custom_event` name=agent_data | — | CUSTOM(component_data) |
| `on_custom_event` name=a2ui.* | — | CUSTOM(a2ui.*) 透传 |
| `on_custom_event` name=state.patch | — | STATE_DELTA |
| `on_custom_event` name=skill.output | 有 model_name | _convert_by_model_name 分流 |

#### ModelName 分流逻辑

```python
CUSTOM_MODEL_NAMES = {"component", "relevantData", "searchResults", "link"}
TEXT_MODEL_NAMES = {"textResult", "explanation", "longText"}

async def _convert_by_model_name(self, model_name, data, skill_apikey):
    if model_name in CUSTOM_MODEL_NAMES:
        # → CUSTOM("component_complete"/"component_data")
        yield custom_event(...)
    elif model_name in TEXT_MODEL_NAMES:
        # → TEXT_MESSAGE_* 三段式
        yield from self._emit_text(text)
    else:
        # → CUSTOM("skill_output") 兜底
        yield custom_event("skill_output", {...})
```

#### 子 Agent 事件过滤

```python
# 过滤规则：parent_ids[0] != root_run_id 的事件丢弃
# 例外：on_custom_event 不过滤（允许穿透）
parent_ids = event.get("parent_ids", [])
if self._root_run_id and parent_ids and parent_ids[0] != self._root_run_id:
    return  # 丢弃子 Agent 事件
```

### 2.3 ProgressiveRenderer 渲染器（renderer.py）

在 STEP 边界自动注入组件生命周期事件。

#### 事件改写规则

```
输入事件流                          输出事件流
─────────────                      ─────────────
STEP_STARTED                  →    STEP_STARTED（透传）
                                   + CUSTOM("component_loading", {apikey, state:"loading"})

CUSTOM("skill_output",{...})  →    [拦截吸收，不透传]
                                   缓存到 _pending_skill_output[skill_apikey]

CUSTOM("step_metadata",{...}) →    [透传] + 记录 status/skill_apikey

STEP_FINISHED                 →    CUSTOM("component_complete", {apikey, state:"complete", data})
                                   + STATE_DELTA([{op:"replace", path:"/panels/<apikey>/state"...}])
                                   + STEP_FINISHED（最后透传）
```

#### ComponentMatcher 5 层匹配

```python
def resolve(self, skill_apikey, output_schema=None, output_model_names=None):
    # Layer 1: bind — 组件 JSON 中 skill_bindings.bind 声明
    # Layer 2: prefer — 组件 JSON 中 skill_bindings.prefer 声明
    # Layer 3: ModelName — 组件 supported_model_names 匹配
    # Layer 4: Schema 字段重叠 ≥ 0.6
    # Layer 5: LLM fallback（多候选时让小模型选）
    # 无匹配 → 返回 None（Renderer 不发 component_* 事件）
```

### 2.4 Pipeline 管道工厂（pipeline.py）

```python
def create_agui_pipeline(run_id, thread_id, history_messages=None):
    converter = AGUIConverter(run_id, thread_id, history_messages)
    renderer = ProgressiveRenderer(matcher=ComponentMatcherV2(...))
    return converter, renderer

# 使用方式（adapter.py）：
converter, renderer = create_agui_pipeline(run_id, thread_id)
astream = agent.astream_events(input_data, config, version="v2")
async for event in renderer.process(converter.convert(astream)):
    yield event  # → SSE
```


---

## 三、A2UI 声明式 UI 层详细设计

### 3.1 数据模型（models.py）

#### BoundValue — 可绑定属性值

```python
@dataclass
class BoundValue:
    path: str | None = None              # 数据路径绑定（如 /data/customers/0/name）
    literal_string: str | None = None    # 字面量字符串
    literal_number: float | None = None  # 字面量数字
    literal_boolean: bool | None = None  # 字面量布尔
    literal_array: list | None = None    # 字面量数组

# 工厂函数
BoundValue.literal("Hello")              # → {literalString: "Hello"}
BoundValue.path_bind("/data/user/name")  # → {path: "/data/user/name"}
```

#### Component — 组件实例（邻接表）

```python
@dataclass
class Component:
    id: str       # 全局唯一 ID
    type: str     # 组件类型（来自 Catalog，如 "Text"/"Column"/"CrmRecordCard"）
    props: dict   # 属性字典（值为 BoundValue 或嵌套结构）
```

#### 四种服务端消息

| 消息类型 | 字段 | 用途 |
|----------|------|------|
| SurfaceUpdate | surface_id, components[] | 定义/更新一个面板的组件列表 |
| DataModelUpdate | surface_id, contents[], path? | 更新面板数据模型（仅局部 UI 状态） |
| BeginRendering | surface_id, root, catalog_id? | 触发首次渲染 |
| DeleteSurface | surface_id | 移除面板 |

#### 客户端入站消息

| 消息类型 | 字段 | 用途 |
|----------|------|------|
| UserAction | name, surface_id, source_component_id, timestamp, context | 用户交互事件 |
| ClientError | message, component_id?, surface_id? | 渲染/绑定错误 |

### 3.2 Builder — 流畅 API 构建 surface（builder.py）

```python
ui = A2UIBuilder(surface_id="panel-1", catalog_id="viking.crm-v1")

# 容器组件
ui.column("root", children=["title", "list"])
ui.row("header", children=["logo", "nav"])
ui.card("card1", children=["card_body"])

# 叶子组件
ui.text("title", literal="Q3 客户 Top10", usage_hint="h2")
ui.image("logo", src="/assets/logo.png")
ui.button("btn", label="查看详情", action="view_detail", context={...})
ui.text_field("input", placeholder="输入搜索词", binding="/data/search_query")

# 动态列表（模板）
ui.list_template("customers_list",
    data_binding="/data/customers_top",    # 绑定到 Shared State 数组
    template_id="customer_row_tpl")        # 每项用此模板渲染

# 业务组件
ui.crm_record_card("card", record_type="customer", record_id_path="./id")
ui.pipeline_table("table", stages_path="/data/pipeline/stages")

# 数据模型（仅 surface 局部 UI 状态）
ui.data("form_state", {"draft": "", "collapsed": False})

# 生成消息
messages = ui.messages()  # → [SurfaceUpdate, BeginRendering]
```

#### Root 选择策略

```
1. 显式调用 ui.set_root("root_id") → 使用指定 ID
2. 第一个 is_container=True 的组件（Column/Row/Card）
3. 第一个添加的组件
```

### 3.3 Aggregator — 业务状态聚合（aggregator.py）

Aggregator 是 Shared State 的唯一写入者，管理业务数据和 surface 分配。

#### Shared State 结构

```json
{
  "phase": "executing",
  "panelLayoutOrder": ["customers_top", "pipeline"],
  "panelAppearanceOrder": ["customers_top", "pipeline"],
  "panelSurfaceMap": {"customers_top": "panel-slot-1", "pipeline": "panel-slot-2"},
  "notifications": [{"type": "info", "message": "客户列表已加载"}],
  "data": {
    "customers_top": [{"id": "C1", "name": "工商银行", "amount": 58.0}],
    "pipeline": {"stages": [...], "total_amount": 3440}
  }
}
```

#### 核心方法

```python
class SnapshotAggregator:
    def add(self, render_type, data, notification_message=None):
        """追加业务数据 → 产出 STATE_SNAPSHOT/DELTA 事件"""
        # 1. 首次：分配 surface slot（panel-slot-N）
        # 2. 写入 self._state["data"][render_type] = data
        # 3. 追加 panelLayoutOrder / panelAppearanceOrder
        # 4. 可选：追加 notification
        # 5. Delta 决策：diff < snap × 0.5 → STATE_DELTA，否则 STATE_SNAPSHOT
        return events

    def emit_ui(self, render_type, messages):
        """下发 A2UI 消息到指定面板 → 产出 ACTIVITY_SNAPSHOT"""
        surface_id = self.ensure_surface(render_type)
        return [activity_snapshot(surface_id, messages)]

    def bind_a2ui_data(self, render_type):
        """返回数据路径前缀，供 Builder 绑定"""
        return f"/data/{render_type}"

    def force_snapshot(self):
        """强制全量快照（首包/重连）"""
        return [state_snapshot(self._state)]

    def active_activities(self):
        """返回所有活跃 surface 的 operations（重连用）"""
        return [...]
```

#### Delta 决策算法

```python
def _should_use_delta(self, old_state, new_state):
    import jsonpatch
    patch = jsonpatch.make_patch(old_state, new_state)
    diff_size = len(json.dumps(patch.patch))
    snap_size = len(json.dumps(new_state))
    return diff_size < snap_size * 0.5
```

### 3.4 Emitter — 事件包装（emitter.py）

将 A2UI 消息包装为 AG-UI 事件的两种模式：

```python
class A2UIEmitter:
    def emit_activity(self, messages, surface_id, replace=True):
        """Mode B：嵌入 ACTIVITY_SNAPSHOT"""
        operations = [msg.to_dict() for msg in messages]
        return activity_snapshot(
            message_id=f"a2ui-{self._run_id}",
            activity_type="a2ui-surface",
            content={"operations": operations, "render_type": self._render_type},
            replace=replace
        )

    def emit_custom(self, messages):
        """旁通道：每条消息独立 CUSTOM 事件"""
        return [custom_event(f"a2ui.{msg.type}", msg.to_dict()) for msg in messages]
```

### 3.5 Catalog — 组件目录与协商（catalog.py）

#### 组件元数据（JSON 定义）

```json
// resources/a2ui/components/crm_record_card.json
{
  "type": "CrmRecordCard",
  "description": "CRM 业务记录卡片",
  "input_schema": {
    "recordType": {"type": "string", "enum": ["customer","contact","opportunity"]},
    "recordId": {"type": "string"}
  },
  "skill_bindings": {
    "bind": ["customer_360_analysis"],
    "prefer": ["customer_list", "account_detail"]
  },
  "supported_model_names": ["component", "relevantData"]
}
```

#### CatalogRegistry

```python
class CatalogRegistry:
    def register_standard(self):
        """注册 A2UI v0.8 标准 catalog（Text/Row/Column/Card/Button/...）"""

    def load_from_dir(self, dir_path, catalog_id):
        """从 JSON 文件加载业务组件到指定 catalog"""

    def negotiate(self, client_supported, client_inline, accepts_inline):
        """Catalog 协商：选出双方都支持的 catalog_id"""
        # 优先业务 catalog → 次选标准 catalog

    def advertise(self, accepts_inline=False):
        """生成 Agent Card 的 extensions 声明"""
```

#### ComponentMatcherV2（5 层匹配）

```python
class ComponentMatcherV2(ComponentMatcher):
    def warmup(self, catalog_registry):
        """启动时预计算 4 张缓存"""
        # _bind_map: skill_apikey → component_type（一对一）
        # _prefer_map: skill_apikey → [component_types]（首选列表）
        # _model_name_map: model_name → [component_types]
        # _schema_cache: skill_apikey → [component_types]（字段重叠）

    def resolve(self, skill_apikey, output_schema=None, output_model_names=None):
        """5 层匹配，返回最佳组件 type 或 None"""
```

### 3.6 RenderHelper — 一站式渲染辅助（render_helper.py）

简化 Skill 开发者的使用：一个方法完成数据+结构+下发。

```python
class A2UIRenderHelper:
    def __init__(self, run_id, thread_id, catalog_registry):
        self._aggregator = SnapshotAggregator(run_id, thread_id)
        self._emitter = A2UIEmitter(run_id)
        self._catalog = catalog_registry

    def render(self, render_type, data, surface_fn, notification_message=None):
        """一步完成：
        1. aggregator.add(render_type, data) → STATE 事件
        2. Builder 构建 surface（调用 surface_fn）
        3. aggregator.emit_ui(render_type, messages) → ACTIVITY 事件
        4. 返回所有事件
        """
        events = []
        # 数据
        events += self._aggregator.add(render_type, data, notification_message)
        # 结构
        data_path = self._aggregator.bind_a2ui_data(render_type)
        surface_id = self._aggregator.ensure_surface(render_type)
        ui = A2UIBuilder(surface_id=surface_id, catalog_id=self._catalog.default_id)
        surface_fn(ui, data_path)  # 用户定义的构建函数
        messages = ui.messages()
        # 下发
        events += self._aggregator.emit_ui(render_type, messages)
        return events

    def update_data(self, render_type, new_data):
        """只更新数据（不重建 surface）"""
        return self._aggregator.add(render_type, new_data)
```

### 3.7 ThreadStore — 重连态持有（thread_store.py）

```python
class ThreadState:
    aggregator: SnapshotAggregator    # Shared State
    last_run_id: str                  # 最近一次 run
    surface_operations: dict          # render_type → operations（最近一次 render）
    messages: list[dict]              # 消息缓冲

    def snapshot_state(self):
        """重连用：返回 STATE_SNAPSHOT 数据"""
        return self.aggregator.get_snapshot()

    def active_activities(self):
        """重连用：返回所有活跃 surface 的 ACTIVITY_SNAPSHOT"""
        return [...]

class ThreadStore:
    """进程级单例，管理所有 thread 的会话态"""
    def get(self, thread_id) -> ThreadState | None
    def ensure(self, thread_id) -> ThreadState
    def bind_aggregator(self, thread_id, aggregator)
    def set_last_run(self, thread_id, run_id)
    def record_activity(self, thread_id, render_type, operations)
    def append_message(self, thread_id, message)
```


---

## 四、适配器与路由层

### 4.1 NeoAgentV2Adapter（adapter.py）

单例懒加载，提供三种执行模式：

```python
class NeoAgentV2Adapter:
    async def execute_agui(self, thread_id, user_input, run_id=None, history=None):
        """AG-UI 模式：输出标准 AG-UI 事件流（主通道）"""
        # 1. 毒性检测 → 拦截则直接返回 TEXT_MESSAGE
        # 2. 查询改写（记忆增强）
        # 3. 注入 pending A2UI userAction
        # 4. 创建 AGUI Pipeline（Converter + Renderer）
        # 5. agent.astream_events → converter.convert → renderer.process
        # 6. yield 每个 AG-UI 事件

    async def execute_a2ui(self, thread_id, user_input, run_id=None):
        """Mode A：纯 A2UI JSONL 流"""
        # 内部调用 execute_agui，通过 A2UIProjector 投影出 A2UI 消息

    def inject_message(self, thread_id, message, source="a2ui"):
        """外部消息注入（A2UI userAction 回传）"""
        # 存入 _pending_messages[thread_id]，下次 execute 时注入
```

### 4.2 FastAPI 路由（a2ui_routes.py）

| 端点 | 方法 | 用途 | 响应格式 |
|------|------|------|----------|
| `/.well-known/agent-card` | GET | A2A Agent Card（Catalog 声明） | JSON |
| `/agent/a2ui/event` | POST | 客户端入站（userAction/error） | 202 JSON |
| `/agent/a2ui/stream` | POST | Mode A 纯 A2UI 流 | NDJSON 或 SSE |
| `/agent/chat/reconnect` | POST | 断线重连首包 | SSE |
| `/api/chat/agui` | POST | 统一 AG-UI 事件流对话 | SSE |

#### /api/chat/agui 核心流程

```python
@router.post("/api/chat/agui")
async def chat_agui(req):
    # 1. Catalog 协商
    catalog_id = registry.negotiate(client_supported, ...)

    # 2. Trace start
    trace = tracer.start_trace(thread_id, user_input)

    # 3. 记录消息到 ThreadStore
    thread_store.append_message(thread_id, {"role": "user", "content": message})

    # 4. 调用 Adapter
    async def generator():
        async for event in adapter.execute_agui(thread_id, message, run_id, history):
            # 记录 ACTIVITY_SNAPSHOT 到 ThreadStore（供重连）
            if event.type == "ACTIVITY_SNAPSHOT" and activity_type == "a2ui-surface":
                thread_store.record_activity(thread_id, render_type, operations)
            yield event.to_sse()

    return StreamingResponse(generator(), media_type="text/event-stream")
```

#### /agent/chat/reconnect 首包顺序

```python
async def chat_reconnect(req):
    state = thread_store.get(thread_id)
    # 固定顺序：
    yield run_started(run_id, thread_id, parent_run_id)     # 1
    yield messages_snapshot(state.messages)                   # 2
    yield state_snapshot(state.snapshot_state())              # 3
    for activity in state.active_activities():                # 4
        yield activity_snapshot(...)
    # 5. 恢复增量推送
```

---

## 五、端到端数据流

### 5.1 场景 A：纯文本回答（output_mode=text）

```
用户: "大管径管道流量测量哪些产品适合"
    │
    ▼
┌─ adapter.execute_agui() ─────────────────────────────────────────┐
│                                                                    │
│  LangGraph Agent Loop                                              │
│  ├─ LLM 决定调用 skills_tool(knowledge_doc_search)                 │
│  ├─ SkillExecutor._execute_fork() → 子 Agent 执行检索              │
│  └─ 子 Agent 返回结果文本                                          │
│                                                                    │
│  LangGraph 产出事件：                                               │
│  ├─ on_chain_start(name="skill_knowledge_doc_search")              │
│  ├─ [子 Agent 内部事件被过滤]                                       │
│  ├─ on_chain_end(name="skill_knowledge_doc_search", output=文本)   │
│  └─ on_chat_model_stream(最终回答文本 chunks)                       │
└────────────────────────────────────────────────────────────────────┘
    │
    ▼
┌─ AGUIConverter.convert() ────────────────────────────────────────┐
│                                                                    │
│  on_chain_start(skill_*) → STEP_STARTED + step_metadata           │
│  on_chain_end(skill_*)   → CUSTOM(skill_output) + STEP_FINISHED   │
│  on_chat_model_stream    → TEXT_MESSAGE_START/CONTENT/END          │
└────────────────────────────────────────────────────────────────────┘
    │
    ▼
┌─ ProgressiveRenderer.process() ──────────────────────────────────┐
│                                                                    │
│  STEP_STARTED → 透传 + component_loading（如有匹配组件）           │
│  CUSTOM(skill_output) → 拦截缓存                                   │
│  STEP_FINISHED → component_complete + STATE_DELTA + 透传           │
│  TEXT_MESSAGE_* → 直接透传                                         │
└────────────────────────────────────────────────────────────────────┘
    │
    ▼
┌─ SSE 输出到前端 ─────────────────────────────────────────────────┐
│                                                                    │
│  event: RUN_STARTED                                                │
│  event: STEP_STARTED {step_name: "knowledge_doc_search"}           │
│  event: CUSTOM {name: "step_metadata", value: {...}}               │
│  event: STEP_FINISHED {step_name: "knowledge_doc_search"}          │
│  event: TEXT_MESSAGE_START {message_id: "m1", role: "assistant"}    │
│  event: TEXT_MESSAGE_CONTENT {message_id: "m1", delta: "## 📚..."}│
│  event: TEXT_MESSAGE_CONTENT {message_id: "m1", delta: "..."}      │
│  event: TEXT_MESSAGE_END {message_id: "m1"}                        │
│  event: RUN_FINISHED                                               │
└────────────────────────────────────────────────────────────────────┘
    │
    ▼
┌─ 前端渲染 ───────────────────────────────────────────────────────┐
│                                                                    │
│  TEXT_MESSAGE_* → ChatBubble → MarkdownRenderer                    │
│  渲染为：Markdown 文本气泡（含表格、列表、来源标注）                │
└────────────────────────────────────────────────────────────────────┘
```

### 5.2 场景 B：A2UI 组件渲染（output_mode=component）

```
用户: "分析客户 C1 的全景"
    │
    ▼
┌─ Agent 执行 accountInsight Skill ────────────────────────────────┐
│                                                                    │
│  子 Agent 调用 query_data/analyze_data 获取结构化数据               │
│  Skill 内部通过 on_custom_event("agent_data") 推送数据              │
│  或通过 on_custom_event("skill.output", model_name="component")    │
└────────────────────────────────────────────────────────────────────┘
    │
    ▼
┌─ AGUIConverter ──────────────────────────────────────────────────┐
│                                                                    │
│  skill_output(model_name="component") →                            │
│    CUSTOM("component_complete", {apikey:"crm_record_card", data})  │
│                                                                    │
│  或 agent_data →                                                   │
│    CUSTOM("component_data", {model_name:"relevantData", data})     │
└────────────────────────────────────────────────────────────────────┘
    │
    ▼
┌─ ProgressiveRenderer ────────────────────────────────────────────┐
│                                                                    │
│  STEP_STARTED → component_loading(crm_record_card)                 │
│  skill_output → 缓存                                               │
│  STEP_FINISHED →                                                   │
│    component_complete(crm_record_card, data) +                     │
│    STATE_DELTA(/panels/crm_record_card/state = "complete") +       │
│    STATE_DELTA(/panels/crm_record_card/data = {...})                │
└────────────────────────────────────────────────────────────────────┘
    │
    ▼
┌─ 前端渲染 ───────────────────────────────────────────────────────┐
│                                                                    │
│  component_loading → 显示 Skeleton 加载态                           │
│  component_complete → CrmRecordCard 组件渲染完整数据                │
│  STATE_DELTA → SharedState 更新（组件通过 BoundValue.path 读取）    │
└────────────────────────────────────────────────────────────────────┘
```

### 5.3 场景 C：A2UI Surface 完整渲染（RenderHelper）

```
用户: "查看 Q3 新签 Top10 客户"
    │
    ▼
┌─ Skill 内部使用 A2UIRenderHelper ────────────────────────────────┐
│                                                                    │
│  helper = A2UIRenderHelper(run_id, thread_id, catalog_registry)    │
│                                                                    │
│  events = helper.render(                                           │
│      render_type="customers_top",                                  │
│      data=[{id:"C1",name:"工行"}, ...],                            │
│      surface_fn=build_customers_surface,                           │
│      notification_message="✅ 客户列表已加载"                       │
│  )                                                                 │
│                                                                    │
│  产出事件：                                                         │
│  1. STATE_SNAPSHOT (data.customers_top = [...])                     │
│  2. ACTIVITY_SNAPSHOT (surfaceUpdate + beginRendering)              │
└────────────────────────────────────────────────────────────────────┘
    │
    ▼
┌─ SSE 输出 ───────────────────────────────────────────────────────┐
│                                                                    │
│  event: STATE_SNAPSHOT                                             │
│    data: {snapshot: {                                              │
│      phase: "executing",                                           │
│      data: {customers_top: [{id:"C1",name:"工行",amount:58}, ...]},│
│      panelSurfaceMap: {customers_top: "panel-slot-1"},             │
│      notifications: [{type:"info", message:"✅ 客户列表已加载"}]    │
│    }}                                                              │
│                                                                    │
│  event: ACTIVITY_SNAPSHOT                                          │
│    data: {                                                         │
│      message_id: "a2ui-xxx",                                       │
│      activity_type: "a2ui-surface",                                │
│      replace: true,                                                │
│      content: {                                                    │
│        render_type: "customers_top",                               │
│        operations: [                                               │
│          {surfaceUpdate: {surfaceId:"panel-slot-1", components:[   │
│            {id:"root", component:{Column:{children:{explicitList:  │
│              ["title","customers_list"]}}}},                        │
│            {id:"title", component:{Text:{text:{literalString:      │
│              "Q3 新签 Top10"}, usageHint:"h2"}}},                  │
│            {id:"customers_list", component:{List:{children:        │
│              {template:{dataBinding:"/data/customers_top",          │
│               componentId:"customer_row"}}}}},                     │
│            {id:"customer_row", component:{CrmRecordCard:{          │
│              recordType:{literalString:"customer"},                 │
│              recordId:{path:"./id"}}}}                              │
│          ]}},                                                      │
│          {beginRendering: {surfaceId:"panel-slot-1", root:"root",  │
│            catalogId:"viking.crm-v1"}}                             │
│        ]                                                           │
│      }                                                             │
│    }                                                               │
└────────────────────────────────────────────────────────────────────┘
    │
    ▼
┌─ 前端渲染 ───────────────────────────────────────────────────────┐
│                                                                    │
│  STATE_SNAPSHOT → SharedState 初始化                                │
│    sharedState.data.customers_top = [{id:"C1",...}, ...]           │
│                                                                    │
│  ACTIVITY_SNAPSHOT → A2UIBridge.dispatch(operations)                │
│    1. surfaceUpdate → 注册组件树到 SurfaceStore                     │
│    2. beginRendering → 触发 root 组件渲染                           │
│       └─ Column → Text("Q3 新签 Top10")                            │
│                 → List(template)                                    │
│                     └─ 遍历 sharedState.data.customers_top          │
│                        └─ CrmRecordCard(recordId=item.id)          │
└────────────────────────────────────────────────────────────────────┘
```

---

## 六、前端接入规范

### 6.1 SSE 事件订阅

```typescript
// 连接 AG-UI SSE
const eventSource = new EventSource("/api/chat/agui", {method: "POST", body: {...}});

eventSource.addEventListener("RUN_STARTED", (e) => { /* 开始 */ });
eventSource.addEventListener("RUN_FINISHED", (e) => { /* 结束 */ });
eventSource.addEventListener("RUN_ERROR", (e) => { /* 错误 */ });

// 文本消息 → ChatBubble
eventSource.addEventListener("TEXT_MESSAGE_START", (e) => { chatRenderer.start(data) });
eventSource.addEventListener("TEXT_MESSAGE_CONTENT", (e) => { chatRenderer.append(data) });
eventSource.addEventListener("TEXT_MESSAGE_END", (e) => { chatRenderer.end(data) });

// 工具调用 → 推理链路展示
eventSource.addEventListener("TOOL_CALL_START", (e) => { toolRenderer.start(data) });
eventSource.addEventListener("TOOL_CALL_ARGS", (e) => { toolRenderer.appendArgs(data) });
eventSource.addEventListener("TOOL_CALL_RESULT", (e) => { toolRenderer.showResult(data) });

// 推理过程 → 折叠展示
eventSource.addEventListener("REASONING_MESSAGE_CONTENT", (e) => { reasoningRenderer.append(data) });

// 步骤 → 进度指示
eventSource.addEventListener("STEP_STARTED", (e) => { stepIndicator.start(data) });
eventSource.addEventListener("STEP_FINISHED", (e) => { stepIndicator.finish(data) });

// 状态 → SharedState
eventSource.addEventListener("STATE_SNAPSHOT", (e) => { sharedState.replace(data.snapshot) });
eventSource.addEventListener("STATE_DELTA", (e) => { sharedState.applyPatch(data.delta) });

// A2UI → SurfaceRenderer
eventSource.addEventListener("ACTIVITY_SNAPSHOT", (e) => {
    if (data.activity_type === "a2ui-surface") {
        a2uiBridge.dispatch(data.content.operations);
    }
});

// CUSTOM → 组件状态
eventSource.addEventListener("CUSTOM", (e) => {
    switch (data.name) {
        case "component_loading": componentRenderer.showLoading(data.value.apikey); break;
        case "component_complete": componentRenderer.renderComplete(data.value); break;
        case "component_data": dataRenderer.render(data.value); break;
        case "component_error": componentRenderer.showError(data.value); break;
        case "step_metadata": debugPanel.update(data.value); break;
    }
});
```

### 6.2 Shared State 数据绑定

```typescript
// A2UI 组件通过 BoundValue.path 读取 SharedState
class SharedStateStore {
    private state: Record<string, any> = {};

    replace(snapshot: any) { this.state = snapshot; }
    applyPatch(delta: JsonPatch[]) { this.state = applyPatch(this.state, delta); }

    // 组件读取数据
    resolve(path: string): any {
        // "/data/customers_top/0/name" → state.data.customers_top[0].name
        return getByPath(this.state, path);
    }

    // 模板列表中的相对路径
    resolveRelative(basePath: string, relativePath: string, index: number): any {
        // basePath="/data/customers_top", relativePath="./name", index=0
        // → state.data.customers_top[0].name
        return getByPath(this.state, `${basePath}/${index}/${relativePath.slice(2)}`);
    }
}
```

### 6.3 A2UI Surface 渲染

```typescript
class A2UIBridge {
    dispatch(operations: A2UIOperation[]) {
        for (const op of operations) {
            if ("surfaceUpdate" in op) {
                this.surfaceStore.update(op.surfaceUpdate.surfaceId, op.surfaceUpdate.components);
            } else if ("beginRendering" in op) {
                this.surfaceStore.startRender(op.beginRendering.surfaceId, op.beginRendering.root);
            } else if ("dataModelUpdate" in op) {
                this.surfaceStore.updateLocalData(op.dataModelUpdate);
            } else if ("deleteSurface" in op) {
                this.surfaceStore.remove(op.deleteSurface.surfaceId);
            }
        }
    }
}

class SurfaceStore {
    // 邻接表展开为组件树
    update(surfaceId: string, components: Component[]) {
        const componentMap = new Map(components.map(c => [c.id, c]));
        this.surfaces.set(surfaceId, componentMap);
    }

    startRender(surfaceId: string, rootId: string) {
        const componentMap = this.surfaces.get(surfaceId);
        const root = componentMap.get(rootId);
        // 递归渲染组件树
        this.renderComponent(root, componentMap);
    }
}
```

### 6.4 用户交互回传

```typescript
// 用户点击按钮 → 回传 userAction
async function handleButtonClick(surfaceId: string, componentId: string, context: any) {
    await fetch("/agent/a2ui/event", {
        method: "POST",
        body: JSON.stringify({
            threadId: currentThreadId,
            userAction: {
                name: "button_click",
                surfaceId: surfaceId,
                sourceComponentId: componentId,
                timestamp: new Date().toISOString(),
                context: context
            }
        })
    });
    // 后端会在原 SSE 连接上推送新事件
}
```

### 6.5 断线重连

```typescript
async function reconnect(threadId: string, lastRunId: string) {
    const response = await fetch("/agent/chat/reconnect", {
        method: "POST",
        body: JSON.stringify({ threadId, lastRunId })
    });

    // 按固定顺序接收：
    // 1. RUN_STARTED → 标记重连中
    // 2. MESSAGES_SNAPSHOT → 恢复消息历史
    // 3. STATE_SNAPSHOT → 恢复 SharedState
    // 4. ACTIVITY_SNAPSHOT × N → 恢复所有 surface
    // 5. 后续增量事件 → 正常处理
}
```

---

## 七、组件 Catalog 体系

### 7.1 标准 Catalog（A2UI v0.8）

| 组件类型 | 用途 | 关键属性 |
|----------|------|----------|
| Text | 文本展示 | text(BoundValue), usageHint(h1/h2/body/caption) |
| Image | 图片 | src(BoundValue), alt, width, height |
| Button | 按钮 | child(组件id), action(ActionDef) |
| TextField | 输入框 | placeholder, binding(path) |
| Row | 横向布局 | children(explicitList/template) |
| Column | 纵向布局 | children(explicitList/template) |
| Card | 卡片容器 | children, title?, subtitle? |
| List | 动态列表 | children.template(dataBinding + componentId) |

### 7.2 业务 Catalog（Viking CRM v1）

| 组件类型 | 用途 | 关键属性 | Skill 绑定 |
|----------|------|----------|-----------|
| CrmRecordCard | CRM 记录卡片 | recordType, recordId | customer_360_analysis(bind) |
| PipelineTable | Pipeline 看板 | stages(数组) | pipeline_analysis(bind) |
| BantMatrix | BANT 矩阵 | budget/authority/need/timeline | — |
| OpportunityTimeline | 商机时间线 | events(数组) | — |
| SearchResultsList | 搜索结果列表 | items(数组) | — |
| LinkCard | 链接卡片 | title, url, description | — |

### 7.3 Catalog 协商流程

```
1. 前端请求带 a2uiClientCapabilities:
   {supportedCatalogIds: ["standard_v0.8", "viking.crm-v1"]}

2. 后端 CatalogRegistry.negotiate():
   - 双方都支持 viking.crm-v1 → 选定
   - 否则降级到 standard_v0.8

3. 后端 beginRendering 带 catalogId:
   {beginRendering: {catalogId: "viking.crm-v1", ...}}

4. 前端按 catalogId 查找组件实现并渲染
```

---

## 八、关键设计约束

| 约束 | 说明 | 代码位置 |
|------|------|----------|
| 三流互斥 | 文本/推理/工具调用同时只能有一个活跃 | converter.py |
| 子 Agent 事件过滤 | parent_ids[0] != root_run_id 的丢弃 | converter.py |
| skill_output 不透传 | 被 Renderer 拦截，不到达前端 | renderer.py |
| STEP_FINISHED 延迟透传 | 等 component_complete + STATE_DELTA 之后 | renderer.py |
| Shared State 唯一源 | 业务数据只走 STATE_SNAPSHOT/DELTA | aggregator.py |
| dataModelUpdate 仅局部 | 只用于 surface 内部 UI 状态 | builder.py |
| 组件 id 全局唯一 | 重复 id 会 raise | builder.py |
| Delta 决策 | diff < snap × 0.5 用 DELTA，否则 SNAPSHOT | aggregator.py |
| 断线重连固定顺序 | RUN→MESSAGES→STATE→ACTIVITY | a2ui_routes.py |
| CUSTOM 命名空间 | 禁止裸 CUSTOM 透传前端 | converter.py |
