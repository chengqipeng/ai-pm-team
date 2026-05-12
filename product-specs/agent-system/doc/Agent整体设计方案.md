# NeoAgent2.0 整体设计方案

> 面向 2B CRM SaaS 的企业级 Agent 系统完整设计。
> 融合 Claude Code + NeoAgents + OpenViking/Hermes 四大体系精华。
> 本文档是系统全貌概览，各子系统详细设计见独立文档（记忆 / 上下文压缩 / 内容审查 / 协议 / 数据库表 等）。

---

## 一、系统定位与设计目标

### 1.1 产品定位

NeoAgent2.0 是面向 2B CRM SaaS 场景的智能 Agent 系统，在 aPaaS 元数据驱动平台上提供四大核心能力：

- **理解业务** — 基于元数据驱动的 aPaaS 平台，Agent 感知业务对象（客户 / 商机 / 联系人 / 合同 等）的完整 Schema、字段、关联关系与权限
- **多模态理解** — 原生支持图片、文档（PDF / Word / Excel / PPT）、语音转写、AI 生图等多模态输入与输出
- **记住用户** — 长期记忆系统按 **4 类**持续沉淀用户与业务洞察（均由 LLM 从用户对话中提取）：
  - `profile` — 用户身份、角色、背景
  - `preferences` — 用户偏好与习惯（按语义 slug 拆分）
  - `agent_rules` — 用户对 Agent 的角色定义与行为准则
  - `entities` — 客户 / 联系人 / 商机 / 合同等第三方实体的信息与洞察
- **执行任务** — 通过 Tool + Skill + Middleware 三层能力体系完成查询、分析、修改、配置、通知等任务
- **开放协议** — 通过 **AG-UI**（Agent ↔ UI 事件协议）和 **A2UI**（Agent-to-UI 动态组件协议）让前端实时感知 Agent 执行、按需渲染专用业务组件
- **持续进化** — 反思 + 遗忘机制保证记忆质量；工具与技能的执行统计沉淀在独立的指标存储中（非记忆体系），通过 SkillTracker / SkillOptimizer 驱动技能迭代

### 1.2 设计目标

| 目标维度 | 具体指标 |
|:---|:---|
| 多租户隔离 | 租户间数据、记忆、配置、工具开关完全隔离 |
| 多模态 | 原生支持图片 / 文档 / 语音，使用多模态 LLM 理解视觉信息 |
| 协议开放 | 基于 AG-UI 标准事件流 + A2UI 动态组件协议，第三方前端可零代码对接 |
| 上下文效率 | 单轮对话上下文占用 < 30% 窗口（64K–200K tokens） |
| 响应延迟 | 首 token P95 < 3s，完整回复 P95 < 15s |
| 记忆精度 | 记忆检索 Top-5 命中率 > 80% |
| 可扩展性 | 新增 Tool / Skill / Middleware 无需修改框架代码 |
| 容错恢复 | 支持检查点恢复，LLM/工具失败按级别分级处理（16 级错误体系） |
| 安全合规 | 输入输出内容审查 + 危险操作 HITL 审批 + 完整审计日志 |

### 1.3 技术栈

| 层级 | 选型 | 说明 |
|:---|:---|:---|
| 语言 | Python 3.11+ | Agent 运行时 |
| LLM（多厂商） | 豆包（Doubao）/ DeepSeek / OpenAI / Anthropic Claude / 通义千问（Qwen）/ 月之暗面（Kimi）/ 智谱（GLM）/ 文心一言 / Gemini 等 | 主模型 + 辅助模型路由（见下表） |
| 多模态模型 | 字节跳动豆包 / OpenAI / Anthropic / Google / 阿里 通义千问 / 智谱 等视觉模型 | 图片理解、视觉推理 |
| 模型接入协议 | OpenAI 兼容 API（首选）+ Anthropic 原生 API + 自定义 Adapter | 多厂商统一接入 |
| 向量库 | 腾讯云向量数据库（tcvectordb） | 记忆检索索引，原生 filter + BM25 混合检索 |
| 关系库 | PostgreSQL | 记忆权威数据源、审计日志、追踪、会话、配置 |
| 图片存储 | 对象存储（COS / OSS） | 图片、生成图、Artifact 二进制 |
| API 框架 | FastAPI + SSE | 流式对话接口（含多模态消息流） |
| 前端协议 | AG-UI（事件流）+ A2UI（动态组件） | Agent ↔ 前端标准交互协议 |
| 缓存 / 检查点 | Redis | 会话状态、检查点持久化、sessionSummary |

#### 1.3.1 LLM 多厂商支持

Agent 通过 `llm-middleware` 统一接入多家 LLM 厂商，租户可按需配置主模型与辅助模型：

| 厂商 | 接入方式 | 典型场景 |
|:---|:---|:---|
| 字节跳动 豆包 | OpenAI 兼容（Volces Ark） | **默认主模型**，覆盖主对话 / 辅助 / 多模态 / 代码 / 嵌入全档位 |
| DeepSeek | OpenAI 兼容 | 性价比主力、深度推理 |
| OpenAI | 原生 API | 旗舰主对话、多模态、深度推理 |
| Anthropic | 原生 API | 长上下文、代码生成、工具调用稳健 |
| 阿里 通义千问 | OpenAI 兼容（DashScope） | 中文场景、多模态 |
| 月之暗面 Kimi | OpenAI 兼容 | 超长上下文 |
| 智谱 | OpenAI 兼容 | 中文 + 多模态 |
| 百度 文心 | OpenAI 兼容（千帆） | 中文场景 |
| Google | 原生 API | 多模态、超长上下文 |
| 自部署（Llama / Qwen / DeepSeek 等） | OpenAI 兼容（vLLM / Ollama） | 私有化部署、数据合规 |

**多模型路由策略**（ModelRouter）：

| 任务类型 | 推荐档位 | 理由 |
|:---|:---|:---|
| 主对话（规划 / 执行 / 推理） | 旗舰级主模型 | 工具调用稳定、长上下文 |
| 辅助（记忆提取 / 摘要 / 分类 / 标题生成） | 低成本小模型 | 成本敏感，任务简单 |
| 深度推理（复杂分析 / 反思） | 推理专用模型 | 多步推理 |
| 多模态（看图 / 读扫描件） | 视觉多模态模型（VLM） | 视觉理解 |
| 代码生成 | 代码专长模型 | 代码质量 |
| 嵌入（Embedding） | 嵌入模型 | 向量检索 |

租户级配置：可在 `llm-middleware` 配置中为每种 TaskType 指定厂商 + 具体模型，支持按租户 / 按会话覆盖。具体模型 ID 随厂商迭代演进，不在架构文档中固定。

> 底层 Agent 编排基于开源 Agent 框架构建（通过 `create_agent` 接口与中间件栈集成），但本文档保持**框架无关的设计语言**，聚焦抽象层与业务约束。

---

## 二、系统整体架构

### 2.1 架构总览

```
┌────────────────────────────────────────────────────────────┐
│  入口层                                                     │
│  ─ REST API (FastAPI + SSE)   ─ AG-UI 事件流                │
│  ─ Python SDK                 ─ Chat UI / 工作台            │
└──────────────────────────┬─────────────────────────────────┘
                           │
┌──────────────────────────▼─────────────────────────────────┐
│  适配层                                                     │
│  ─ NeoAgentV2Adapter（懒加载 + 消息转换 + 租户上下文）      │
│  ─ AgentFactory（LRU 缓存 + 深度限制 + 唯一构建流程）       │
└──────────────────────────┬─────────────────────────────────┘
                           │
┌──────────────────────────▼─────────────────────────────────┐
│  编排层 — 状态机 Agent                                      │
│  ─ Lead Agent（主 Agent 循环）                              │
│  ─ Router（7 级路由决策）                                    │
│  ─ Checkpointer（Redis 持久化 / 断线恢复 / HITL 暂停恢复）   │
└──────────────────────────┬─────────────────────────────────┘
                           │
┌──────────────────────────▼─────────────────────────────────┐
│  中间件栈（洋葱模型，20 个中间件）                           │
│  Tracing │ AgentLogging │ DanglingToolCall │ FileProcess   │
│  InputTransform（含 ContentReview + PII + Multimodal）     │
│  Memory │ Summarization │ Todo │ SubagentLimit             │
│  Guardrail │ LoopDetection │ ToolErrorHandling             │
│  Clarification │ OutputValidation │ OutputRender │ Title   │
└──────────────────────────┬─────────────────────────────────┘
                           │
┌──────────────────────────▼─────────────────────────────────┐
│  能力层（三维度）                                            │
│  ┌─────────────┐  ┌─────────────┐  ┌───────────────────┐   │
│  │ ToolRegistry│  │SkillRegistry│  │  MiddlewareRegistry   │   │
│  │ 15 个 CRM   │  │ 12 个业务    │  │  9 个基础设施     │   │
│  │ 原子工具    │  │ 技能         │  │  可插拔能力       │   │
│  └─────────────┘  └─────────────┘  └───────────────────┘   │
└──────────────────────────┬─────────────────────────────────┘
                           │
┌──────────────────────────▼─────────────────────────────────┐
│  子 Agent 层                                                │
│  ─ SubagentRegistry（7 个业务域子 Agent 配置）               │
│  ─ SubagentExecutor（同步 delegate + 异步 start_async）      │
│  ─ SubagentCache（实例缓存 + 深度限制 ≤ 3）                  │
└──────────────────────────┬─────────────────────────────────┘
                           │
┌──────────────────────────▼─────────────────────────────────┐
│  记忆层                                                     │
│  记忆 — VikingMemoryEngine                                  │
│    提取（4 类：profile/preferences/agent_rules/entities）   │
│    → 存储（PG+向量库）→ 检索（BM25+向量）                    │
│    → 反思（冲突检测+修正）→ 遗忘（三阶段淡化）              │
└──────────────────────────┬─────────────────────────────────┘
                           │
┌──────────────────────────▼─────────────────────────────────┐
│  协议层 — 与前端的开放交互                                   │
│  AG-UI（事件流协议）                                         │
│    RUN_STARTED / TEXT_MESSAGE_* / TOOL_CALL_* /             │
│    STEP_* / REASONING_* / MESSAGES_SNAPSHOT / CUSTOM         │
│  A2UI（Agent-to-UI 组件协议）                                │
│    ComponentMatcher（skill_apikey → component_apikey）      │
│    ProgressiveRenderer（loading → delta → complete）        │
│    Tool.render_hint 驱动组件渲染                            │
└──────────────────────────┬─────────────────────────────────┘
                           │
┌──────────────────────────▼─────────────────────────────────┐
│  基础设施                                                   │
│  LLM Gateway │ 向量数据库 │ PostgreSQL │ Redis │ 对象存储    │
└────────────────────────────────────────────────────────────┘
```

### 2.2 Agent 与传统软件的三个关键差异

| 差异 | 带来的问题 | 对应特性 | 我们的实现 |
|:---|:---|:---|:---|
| 高延迟（LLM 秒级） | 用户等待体验差 | 流式输出 + 可中断 | AgentCallbacks + interrupt_event + SSE |
| 低可靠性（长运行易失败） | 重试成本高 | 检查点恢复 | Redis Checkpointer + 断线恢复 |
| 非确定性（LLM 输出不可预测） | 需人工介入 | Human-in-the-Loop | HITL 审批 + PAUSED / resume |

### 2.3 设计决策：自研简化版状态机

aPaaS 平台需要深度定制（租户隔离、审计日志、业务域子 Agent、动态工具开关），设计上保持框架无关的抽象：

- **Router** 做路由决策
- **Node** 做具体工作（Planning / Execution / Reflection）
- **Middleware** 拦截横切关注点（洋葱模型）
- **Checkpointer** 负责状态持久化

这套抽象可以落到任意底层 Agent 框架上，不被框架绑定。

---

## 三、编排层 — 状态机图

### 3.1 状态机图

```
                 ┌───────────────┐
  用户输入 ────▶│  PlanningNode │  任务规划与分解
                 └───────┬───────┘
                         │ 生成 plan
                         ▼
                 ┌───────────────┐       工具/技能/子Agent
      ┌────────▶│ ExecutionNode │─────────────┐
      │          └───────┬───────┘             │
      │                  │                     ▼
      │                  │              ┌───────────────┐
      │                  │              │  需要 HITL?   │
      │                  │              └───────┬───────┘
      │                  │                      │
      │                  │         ┌────────────┼────────────┐
      │                  │         │ approve    │ reject     │
      │                  │         ▼            ▼            ▼
      │                  │   继续执行      跳过步骤   ┌─────────────┐
      │                  │                           │  PAUSED     │
      │                  │                           │ 等待人工决策 │
      │                  │                           └─────────────┘
      │                  │
      │          ┌───────▼───────┐       需重新规划
      │          │ReflectionNode │────────┐
      │          └───────┬───────┘         │
      │                  │                 │
      │                  │ 继续            ▼
      └──────────────────┘       回到 PlanningNode
                  │
                  │ 任务完成
                  ▼
            ┌───────────────┐
            │ MemoryCommit  │  提取记忆 + 持久化
            └───────────────┘
```

### 3.2 GraphState 核心字段

```python
@dataclass
class GraphState:
    # 身份与会话
    session_id: str
    thread_id: str
    tenant_id: str                          # 租户隔离边界
    user_id: str
    messages: list[Message]                 # 完整对话历史（支持多模态 content: list[ContentPart]）

    # 任务规划
    plan: TaskPlan | None = None
    current_step_index: int = 0

    # 执行追踪
    current_node: str = "router"
    total_llm_calls: int = 0
    total_tool_calls: int = 0
    consecutive_errors: int = 0
    consecutive_same_tool: int = 0
    replan_count: int = 0                   # 重规划次数（上限 3）

    # 状态控制
    status: AgentStatus = AgentStatus.RUNNING  # running/paused/completed/failed/max_turns/aborted
    pause_reason: str | None = None

    # 上下文
    memory_context: str = ""                # 记忆召回注入
    system_prompt: str = ""
    checkpoint_version: int = 0

    # 多模态扩展
    parsed_files: list[ParsedFile] = field(default_factory=list)   # 用户上传的图片/文档（FileProcessMiddleware 写入）
    artifacts: list[Artifact] = field(default_factory=list)         # Agent 生成物（代码 / 报告 / 图表）
    images: list[ImageData] = field(default_factory=list)           # Agent 生成或引用的图片

    # 压缩层协作
    file_list: list[FileInfo] = field(default_factory=list)  # 虚拟文件（Layer 0）
```

### 3.3 Router 路由决策（7 级优先级）

| 优先级 | 条件 | 路由目标 |
|:---:|:---|:---|
| 1 | `status != RUNNING` | 终止 |
| 2 | `total_llm_calls >= 200` | 终止（MAX_TURNS） |
| 3 | `consecutive_errors >= 5` 或 `consecutive_same_tool >= 4` | ReflectionNode（stuck 自救） |
| 4 | `plan is None` | PlanningNode |
| 5 | 所有步骤 COMPLETED | ReflectionNode（最终反思 + 记忆提取） |
| 6 | 当前步骤 FAILED | ReflectionNode（失败分析） |
| 7 | 当前步骤 PENDING/RUNNING | ExecutionNode |

### 3.4 主循环（框架无关伪代码）

```
GraphEngine.run(state):
  while True:
    node = Router.next_node(state)                 # 路由决策
    if node is None: break                          # 终止

    for mw in middlewares:                          # 中间件前处理（注册顺序）
      state = mw.before_step(state)

    state = node.execute(state)                     # Node 执行

    for mw in reversed(middlewares):                # 中间件后处理（逆序）
      state = mw.after_step(state)

    checkpoint_store.save(state)                    # 保存检查点到 Redis
    yield state                                     # 流式输出给前端

    if state.status == PAUSED: break                # HITL 暂停
```

### 3.5 三个核心 Node

| Node | 职责 | 内部逻辑 | 输出 |
|:---|:---|:---|:---|
| PlanningNode | 任务分解 | 判断复杂度 → 简单任务单步计划 / 复杂任务 LLM 生成多步计划（≤ 15 步）→ 注入历史经验 | `state.plan` |
| ExecutionNode | 步骤执行 | 内部 mini loop：LLM → 解析响应 → 有 tool_use？→ 并行执行工具 → 继续；纯文本？→ 步骤完成 | 步骤 COMPLETED / FAILED |
| ReflectionNode | 反思决策 | 判断类型：最终反思（提取记忆）/ 失败分析（retry/skip/replan/escalate/abort）/ stuck 自救 / 用户纠正反思 | 状态变更 / plan 清空 |

### 3.6 HITL 暂停与恢复

```
暂停: HITLMiddleware.before_tool_call() 拦截危险操作
  → state.status = PAUSED, pause_reason = "..."
  → 保存检查点 → 退出主循环 → 前端展示审批界面

恢复: GraphEngine.resume(session_id, decision)
  ├─ approve → 继续执行被暂停的操作
  ├─ reject  → 跳过当前步骤，继续 ReflectionNode
  ├─ abort   → 终止任务
  └─ 超时 1h → 自动 ABORTED
```

### 3.7 错误处理分级（16 级）

| 级别 | 场景 | 处理 |
|:---:|:---|:---|
| L1–L4 | 工具级（校验 / 执行 / 超时 / 权限） | 返回错误 tool_result，LLM 自行修正 |
| L5–L7 | LLM 可重试（超时 / 限流 / 服务端） | 指数退避重试，最多 3 次 |
| L8 | LLM 不可重试（认证失败） | 直接 FAILED |
| L9–L10 | 轮次耗尽（步骤级 / 全局级） | 步骤级→反思分析；全局级→终止 |
| L11–L12 | 连续错误 / 重复工具 | Router → ReflectionNode stuck 自救 |
| L13 | 重新规划 ≥ 3 次 | FAILED |
| L14 | HITL 超时（1h） | ABORTED |
| L15–L16 | 中间件 / 检查点异常 | 记录日志，降级不阻塞主流程 |

---

## 四、中间件栈

### 4.1 中间件接口

```python
class Middleware(Protocol):
    name: str

    async def before_step(self, state: GraphState) -> GraphState: ...
    async def after_step(self, state: GraphState) -> GraphState: ...
    async def wrap_model_call(self, state: GraphState, call_fn): ...
    async def before_tool_call(self, tool_name: str, input_data: dict) -> dict | None: ...
    async def after_tool_call(self, tool_name: str, result: ToolResult) -> ToolResult: ...
```

### 4.2 中间件清单（20 个，按执行顺序）

| # | 中间件 | 阶段 | 职责 |
|:---:|:---|:---|:---|
| 1 | TracingMiddleware | before_agent / all hooks | 采集 span 写入 `ai_trace_span` |
| 2 | AgentLoggingMiddleware | before_agent / wrap_tool_call | 结构化日志 |
| 3 | DanglingToolCallMiddleware | before_agent | 修复遗留的未闭合 tool_call |
| 4 | FileProcessMiddleware | before_agent | **多模态**：解析上传文件 → `parsed_files`，识别 image / document |
| 5 | InputTransformMiddleware | before_agent | 输入预处理管线（见 4.3） |
| 6 | MemoryMiddleware | before_agent / after_agent | 记忆召回 + 提取写入（Middleware 提供） |
| 7 | SummarizationMiddleware | before_model | 上下文压缩（四层架构，见第七章） |
| 8 | TodoMiddleware | before_model | 任务清单管理 |
| 9 | SubagentLimitMiddleware | before_tool_call | 子 Agent 并发数限制 |
| 10 | MultimodalInjectMiddleware | before_model | **多模态**：将图片 / 文档 URL 以 OpenAI 兼容格式注入到 HumanMessage |
| 11 | GuardrailMiddleware | wrap_tool_call | 安全护栏 + 租户隔离 |
| 12 | LoopDetectionMiddleware | after_model | 循环检测（连续相同工具 / 错误） |
| 13 | ToolErrorHandlingMiddleware | after_tool_call | 工具异常分级处理 |
| 14 | HITLMiddleware | before_tool_call | 危险操作人工审批 |
| 15 | ClarificationMiddleware | after_model | 澄清中断（需用户补充信息） |
| 16 | OutputValidationMiddleware | after_model | 输出长度 + 内容审查 |
| 17 | ContentReviewMiddleware | 嵌入 4.3 / 16 | 敏感词拦截（输入 + 输出） |
| 18 | OutputRenderMiddleware | after_model | 结构化输出渲染 + **AG-UI 事件派发 / A2UI 组件触发**（识别 ToolResult.render_hint → 发 CUSTOM 事件） |
| 19 | TitleMiddleware | after_agent | 自动生成会话标题 |
| 20 | TenantMiddleware | before_step | 租户上下文注入 + 工具过滤 |

### 4.3 InputTransformMiddleware 子管线

```
用户输入
   │
   ▼
┌─────────────────────────┐
│ ContentReviewTransformer│  敏感词拦截（优先级最高）
└─────────────────────────┘
   │
   ▼
┌─────────────────────────┐
│ PIIRedactTransformer    │  PII 脱敏（身份证 / 手机号 / 邮箱）
└─────────────────────────┘
   │
   ▼
┌─────────────────────────┐
│ MultimodalTransformer   │  多模态内容格式化
└─────────────────────────┘
   │
   ▼
  送入 Agent 循环
```

---

## 五、能力层（三维度）

> 核心原则：Tool 是 LLM 的手，Skill 是 Agent 的 SOP，Middleware 是系统的器官。三者单向依赖：Skill 编排 Tool → Tool 调用 Middleware 接口 → Middleware 不感知 Tool 存在。

### 5.1 边界定义

```
┌─────────────────────────────────────────────────────────────┐
│ Tool（工具）= LLM 的手                                       │
│   一次原子操作，LLM 通过 function calling 直接调用。         │
│   输入参数 → 执行 → 返回结果。无状态、单步、确定性。           │
│   统一由 ToolRegistry 管理，不允许 Middleware 直接注册。          │
└─────────────────────────────────────────────────────────────┘
                              │
                              │ 调用
                              ▼
┌─────────────────────────────────────────────────────────────┐
│ Middleware（中间件）= 系统的器官                                   │
│   可插拔基础设施能力：LLM / Memory / Search / Notification…  │
│   有生命周期、有配置、有状态，影响 Agent 整体行为。            │
│   通过 MiddlewareContext 向 Tool / Middleware 提供能力。          │
└─────────────────────────────────────────────────────────────┘
                              ▲
                              │ 编排
                              │
┌─────────────────────────────┴──────────────────────────────┐
│ Skill（技能）= Agent 的 SOP                                 │
│   多步业务流程 + 执行策略的 prompt 模板。                    │
│   需要多次 Tool 调用才能完成，有判断、有分支、有经验沉淀。    │
│   两种执行模式：inline（注入当前对话）/ fork（启动子 Agent）。│
└────────────────────────────────────────────────────────────┘
```

### 5.2 判断三问

对任一能力问三个问题就能定位：

```
Q1: LLM 能一次调用直接完成吗？   → 是 → Tool
Q2: 需要多步推理、多次工具调用？ → 是 → Skill
Q3: 是基础设施，需初始化/配置/可替换？ → 是 → Middleware
```

---

### 5.3 Middleware 维度（9 个基础设施中间件）

#### 5.3.1 Middleware 接口

```python
class Middleware(ABC):
    name: str                              # 中间件唯一名称
    version: str

    async def initialize(self, config: dict) -> None: ...   # 生命周期：启动
    async def shutdown(self) -> None: ...                   # 生命周期：关闭
    def is_healthy(self) -> bool: ...                       # 健康检查

    # 向 MiddlewareContext 暴露的接口由各 Middleware 自行定义
    # 如 memory_middleware.recall() / search_middleware.search() / llm_middleware.complete()
```

#### 5.3.2 MiddlewareContext — Tool 访问 Middleware 的统一入口

```python
@dataclass
class MiddlewareContext:
    """Tool 调用时传入的上下文，通过它访问所有已启用的 Middleware。

    核心约束：Middleware 未启用时，context 对应字段为 None。
    Tool 的 is_enabled() 据此判断是否在工具列表中暴露。
    """
    tenant_id: str
    user_id: str
    session_id: str

    llm: LLMMiddleware | None = None
    memory: MemoryMiddleware | None = None
    search: SearchMiddleware | None = None
    company: CompanyDataMiddleware | None = None
    financial: FinancialDataMiddleware | None = None
    notification: NotificationMiddleware | None = None
    doc_parse: DocumentParseMiddleware | None = None
    image_gen: ImageGenMiddleware | None = None
    audit: AuditMiddleware | None = None

    tool_registry: ToolRegistry | None = None
    skill_registry: SkillRegistry | None = None
```

#### 5.3.3 7 个核心 Middleware

| Middleware | 职责 | 向 Context 暴露 | 替代性 | 依赖的 Tool |
|:---|:---|:---|:---:|:---|
| `llm-middleware` | LLM 网关（主模型 + 辅助模型路由） | `context.llm` | ✅ 可切换供应商 | 所有（基础设施） |
| `memory-middleware` | 长期记忆引擎（VikingMemoryEngine） | `context.memory` | ✅ 可替换后端 | search_memories, save_memory |
| `search-middleware` | 网络搜索（可替换供应商） | `context.search` | ✅ | web_search |
| `company-data-middleware` | 企业工商数据 | `context.company` | ✅ | company_info |
| `financial-data-middleware` | 上市公司财报 | `context.financial` | ✅ | financial_report |
| `notification-middleware` | 推送通知（IM / 邮件 / 短信） | `context.notification` | ✅ | send_notification |
| `document-parse-middleware` | 多模态文档解析（LKEAP / Tika / Unstructured 等） | `context.doc_parse` | ✅ | load_file_content |
| `image-gen-middleware` | AI 生图（OpenAI / 字节豆包 / 百度文心一格 等供应商可替换） | `context.image_gen` | ✅ | generate_image |
| `audit-middleware` | 审计日志（合规） | `context.audit` | ✅ | 所有中间件 |

#### 5.3.4 Middleware 生命周期

```
启动阶段（租户初始化时）:
  MiddlewareRegistry.load(tenant_config)
    → 读取租户的 Middleware 启用列表
    → 按依赖关系排序
    → middleware.initialize(config)
    → 注入 MiddlewareContext

运行阶段:
  Tool.call(input_data, context)
    → 通过 context.xxx 访问 Middleware
    → Middleware 接口调用

关闭阶段（租户卸载 / 服务关停）:
  按启动逆序 middleware.shutdown()
    → 释放连接、清理缓存
```

#### 5.3.5 Middleware 的权力边界

| 能做 | 不能做 |
|:---|:---|
| 提供基础设施接口（存储 / 检索 / 通知 …） | 直接注册 Tool（破坏 ToolRegistry 唯一真相源） |
| 注入 Middleware（如 memory-middleware 注入 MemoryMiddleware） | 修改其他 Middleware 的状态 |
| 订阅 Agent 生命周期事件 | 直接与 LLM 通信绕过 llm-middleware |
| 对外暴露管理 API（配额 / 开关 / 健康） | 跨租户共享状态 |

---

### 5.4 Tool 维度（15 个 CRM 业务工具）

#### 5.4.1 Tool 统一接口（四组字段）

```python
class Tool(ABC):
    # ══ 核心（必须实现）══
    name: str                                              # 唯一名称
    def input_schema(self) -> dict: ...                    # JSON Schema
    async def call(self, input_data, context, on_progress) -> ToolResult: ...
    async def description(self, input_data) -> str: ...    # 动态描述

    # ══ 注册与发现 ══
    aliases: list[str]                                     # 别名
    search_hint: str | None                                # 延迟加载的搜索关键词
    should_defer: bool = False                             # 是否延迟加载
    tags: list[str]
    def is_enabled(self, context) -> bool: ...             # 运行时开关（检查 Middleware）

    # ══ 安全与权限 ══
    def validate_input(self, input_data) -> ValidationResult: ...
    async def check_permissions(self, input_data, context) -> PermissionDecision: ...
    def is_read_only(self, input_data) -> bool: ...
    def is_destructive(self, input_data) -> bool: ...      # 触发 HITL

    # ══ 输出控制 & 压缩协作 ══
    max_result_size_chars: int = 50_000                    # 每工具独立预算
    summary_threshold: int = 500                            # Layer 1 摘要阈值
    summary_max_words: int = 150
    render_type: str | None = None                          # 前端渲染组件
    code_extractable: bool = False                          # 零 LLM 成本摘要
```

#### 5.4.2 17 个 CRM 工具清单

按用户业务场景组织（而非技术 API），底层通过 aPaaS 元数据驱动实现通用性：

| 分类 | 工具名 | 典型用户表达 | 依赖 Middleware |
|:---|:---|:---|:---|
| **查系统数据** | query_data | "查一下上个月的客户" | — |
| | modify_data | "建一个新客户" / "删除测试数据" | — |
| | analyze_data | "各渠道转化率" / "月度趋势" | — |
| **管系统配置** | query_schema | "客户有哪些字段" | — |
| | modify_schema | "加一个行业字段" | — |
| | query_permission | "谁能看这些数据" | — |
| **查外部信息** | web_search | "搜一下行业动态" | search-middleware |
| | company_info | "查公司背景" | company-data-middleware |
| | financial_report | "看财务状况" | financial-data-middleware |
| **协作与记忆** | ask_user | "你想怎么分析？" | — |
| | search_memories | "之前怎么解决的" | memory-middleware |
| | save_memory | "记住这个偏好" | memory-middleware |
| | send_notification | "通知销售经理" | notification-middleware |
| **多模态** | load_file_content | "看看我刚上传的合同" / "这张截图里写的什么" | document-parse-middleware（文档）/ 直接走 VLM（图片） |
| | generate_image | "画一个产品架构图" | image-gen-middleware |
| **任务编排** | delegate_task | "帮我校验配置" | — |
| | start_async_task | "后台调研竞品" | — |

> 工具总数：17 个。

#### 5.4.3 工具权限矩阵（四层）

```
第一层 · 工具准入     → AgentFactory（enabled_tools/disabled_tools）
第二层 · 租户隔离     → TenantMiddleware 自动注入 tenant_id
第三层 · 业务数据权限 → 后端微服务 RBAC + 行级权限（透传 user_id）
第四层 · 危险操作审批 → HITLMiddleware（is_destructive 判定）
```

| 工具 | 只读 | HITL | 租户隔离 | 数据权限 |
|:---|:---:|:---:|:---:|:---:|
| query_data | ✅ | ❌ | ✅ | ✅ 后端过滤 |
| modify_data (create/update) | ❌ | 可配置 | ✅ | ✅ |
| modify_data (delete) | ❌ | ✅ 必须 | ✅ | ✅ |
| analyze_data | ✅ | ❌ | ✅ | ✅ |
| query_schema | ✅ | ❌ | ✅ | ❌ |
| modify_schema | ❌ | ✅ 必须 | ✅ | ❌ |
| query_permission | ✅ | ❌ | ✅ | ❌ |
| web_search | ✅ | ❌ | ❌ | ❌ |
| company_info | ✅ | ❌ | ✅ 配额 | ❌ |
| financial_report | ✅ | ❌ | ✅ 配额 | ❌ |
| ask_user | — | ❌ | ❌ | ❌ |
| search_memories | ✅ | ❌ | ✅ 路径 | ❌ |
| save_memory | ❌ | ❌ | ✅ 路径 | ❌ |
| send_notification | — | ❌ | ✅ | ❌ |
| delegate_task / start_async_task | — | ❌ | ✅ | ❌ |

#### 5.4.4 延迟加载策略

9 个常用工具初始激活，6 个低频工具进入延迟池（通过 `search_hint` 触发加载）：

```
常用（直接激活）:
  query_data / query_schema / analyze_data / query_permission
  ask_user / search_memories / save_memory
  delegate_task / start_async_task

延迟（搜索激活）:
  web_search / company_info / financial_report
  modify_data / modify_schema / send_notification

收益: 初始 schema token -40%，大部分对话不加载延迟工具
```

#### 5.4.5 ToolResult 扩展

```python
@dataclass
class ToolResult:
    content: str                        # 返回给 LLM 的文本
    is_error: bool = False
    metadata: dict = {}                 # 不给 LLM 的附加信息
    render_hint: RenderHint | None      # 前端渲染提示
    virtual_file: FileInfo | None       # 原文虚拟文件（Layer 0）

    # 多模态扩展
    attachments: list[Attachment] = []  # 工具产出的多模态附件（图片 / 文档 URL）
    artifacts: list[Artifact] = []      # 工具生成的 artifact（图表 / 报告 / 代码）


@dataclass
class Attachment:
    """多模态附件 — 由 MultimodalInjectMiddleware 消费，注入下一轮 HumanMessage"""
    type: str                           # "input_image" | "input_file"
    url: str                            # 图片或文档 URL
    file_name: str = ""
    mime_type: str = ""

    # 序列化为工具文本尾部的标记，供 MultimodalInjectMiddleware 识别：
    # <!--MULTIMODAL_ATTACHMENTS:[{"type":"input_image","image_url":"..."}]-->
```

---

### 5.5 Skill 维度（12 个业务技能）

#### 5.5.1 SkillDefinition 数据结构

```python
@dataclass
class SkillDefinition:
    # 核心标识
    name: str                               # 技能唯一名称
    description: str                        # 一句话描述（必填，LLM 判断何时调用）
    prompt: str = ""                        # SOP 提示词（Markdown body）

    # 发现与触发
    when_to_use: str = ""                   # 触发关键词，| 分隔（如 "诊断|排查|问题"）
    arguments: list[str] = []               # 命名参数列表（prompt 中用 {arg} 占位）

    # 执行配置
    context: str = "inline"                 # "inline" | "fork"
    allowed_tools: list[str] = []           # 额外允许的工具
    model: str = ""                         # 指定模型（空=继承主模型）
    agent: str = ""                         # fork 模式下的子 Agent 类型（可选）

    # 可选元数据（SKILL.md frontmatter 支持）
    # risk_level:  "read_only" | "write" | "destructive"
    # version:     语义化版本号
    # owner:       所有者
    # max_tool_calls: 最大工具调用数
    # timeout_ms:  超时时间
```

#### 5.5.2 12 个内置 Skill

| Skill | 功能 | 模式 | 允许工具 | 依赖 Middleware |
|:---|:---|:---:|:---|:---|
| verify_config | 元数据配置校验 | inline | query_schema | — |
| diagnose | 业务问题诊断 | fork | query_schema, query_data, query_permission, search_memories | memory-middleware |
| config_entity | 业务对象配置向导 | fork | query_schema, query_data, ask_user | — |
| batch_data | 批量数据操作 | fork | query_data, modify_data, ask_user | — |
| data_analysis | 业务数据分析 | fork | query_schema, query_data, analyze_data | — |
| migration | 数据迁移 | fork | query_schema, modify_data, ask_user | — |
| permission_audit | 权限审计 | fork | query_permission, query_data, query_schema | — |
| skillify | 操作转技能 | fork | 全部 | — |
| competitive_analysis | 竞品分析 | fork | web_search, company_info, financial_report, query_data | search/company/financial-middleware |
| customer_onboarding | 客户入职引导 | fork | query_data, query_schema, ask_user, send_notification | notification-middleware |
| deal_coaching | 商机辅导 | fork | query_data, analyze_data, search_memories | memory-middleware |
| report_generation | 报告生成 | fork | query_data, analyze_data, web_search | search-middleware |

#### 5.5.3 两种执行模式

| 模式 | 行为 | 适用场景 |
|:---|:---|:---|
| **inline** | 将 prompt 作为工具返回值注入当前对话，LLM 按 SOP 继续在**主 Agent 上下文**里调用 Tool | 轻量技能（verify_config / customer_360）；不启动子 Agent，零额外会话成本；能继承主 Agent 的历史上下文 |
| **fork** | 启动**子 Agent 独立执行**，工具集 = 主 Agent 工具集 ∩ skill.allowed_tools | 复杂任务（diagnose / data_analysis）；需要隔离上下文、限制工具、限制轮次；可指定专属 agent 类型 |

#### 5.5.4 SKILL.md 声明式定义

Skill 用 Markdown + YAML frontmatter 声明，无需写代码就能开发新技能。文件放在技能目录下的子文件夹里（`SKILL.md` 为固定文件名）：

```markdown
---
name: account-insight                    # 技能名（缺省则取目录名）
description: 深度分析客户的业务全景        # 一句话描述，LLM 据此判断何时调用
when_to_use: 客户洞察|客户分析|account分析  # 触发关键词，| 分隔
arguments:                                 # 命名参数，prompt 中用 {arg} 占位
  - account_id
allowed-tools:                             # 额外允许的工具
  - query_schema
  - query_data
  - analyze_data
context: fork                              # inline / fork
agent: analytics                           # fork 模式下指定子 Agent 类型（可选）
model: ""                                  # 指定模型（空=继承主模型）
risk_level: read_only                      # 风险等级（read_only / write / destructive）
version: 1.0.0
owner: CRM-Product
max_tool_calls: 15                         # 最大工具调用数
timeout_ms: 45000
---

你是一位资深 CRM 客户分析专家。请对客户 {account_id} 进行深度洞察分析。

## 分析步骤

### 步骤 1: 获取客户基本信息
调用 query_data(action="get", entity_api_key="account", record_id="{account_id}")
提取：公司名称、行业、规模、负责人。

### 步骤 2: 分析商机全景
调用 analyze_data(entity_api_key="opportunity", metrics=[...], group_by="stage", filters={...})
了解各阶段商机数量和金额分布。

### 步骤 3: ...

## 输出格式

按以下结构输出分析报告：
...
```

**SKILL.md 必填字段**：`description` + `context`（inline / fork）。其余字段有合理默认值。

#### 5.5.5 Skill 多源加载优先级（后加载覆盖先加载）

```
1. 内置技能（bundled）        src/skills/crm_skills.py 定义为 SkillDefinition 对象
                            启动时自动注册
2. 项目技能（project）        ./skills/definitions/<name>/SKILL.md
                            SkillLoader.discover() 启动时扫描加载
3. 自动生成技能（auto）       ./skills/auto-generated/<name>/SKILL.md
                            SkillGenerator 运行时写入
4. 租户数据库技能（tenant）   ai_skill_definition 表存储，按租户加载
                            租户管理后台可配置，热更新
5. Middleware 提供的技能         Middleware.initialize 阶段向 SkillRegistry 注册
```

#### 5.5.6 Skill 扩展路径（从简单到复杂）

开发一个新 Skill 有四条路径，按成本由低到高：

**路径 A：写一份 SKILL.md**（推荐，零代码）

```
1. 在 skills/definitions/<skill-name>/ 下新建 SKILL.md
2. 填写 frontmatter（name / description / when_to_use / arguments / allowed-tools / context）
3. 在 body 里写 SOP 提示词（描述 LLM 如何分步骤调用 Tool）
4. 重启（或调用 SkillRegistry.reload()），SkillLoader 自动发现并注册
5. LLM 在下一轮对话中即可通过 skills_tool 调用
```

适合：绝大多数业务技能（查客户 360、竞品分析、报告生成、权限审计等）。

**路径 B：代码里声明 SkillDefinition**（适合内置技能 / 测试 / 动态生成）

```python
from src.skills.base import SkillDefinition

CUSTOMER_360 = SkillDefinition(
    name="customer_360",
    description="生成客户 360 度全景视图",
    when_to_use="客户详情|360|全景",
    arguments=["account_id"],
    allowed_tools=["query_data"],
    context="inline",
    prompt="""你现在需要生成客户 {account_id} 的 360 度全景视图。
    ## 步骤 1: ...
    ## 步骤 2: ...""",
)
registry.register(CUSTOMER_360)
```

适合：启动时就要加载的平台级技能。

**路径 C：租户级配置（管理后台）**

```
管理员登录 → 租户技能管理 → 新建技能
   ├─ 填写表单（与 SKILL.md 字段一一对应）
   ├─ 在线编辑 SOP 提示词
   ├─ 选择允许的工具（从租户启用的工具列表中选）
   └─ 保存 → 写入 ai_skill_definition 表
       ↓
SkillRegistry 监听配置变更事件 → 热更新
       ↓
该租户的 Agent 下一轮对话生效
```

适合：每个租户业务流程不同，需要独立配置的场景。

**路径 D：Middleware 提供技能**（最重）

```python
class MyMiddleware(Middleware):
    async def initialize(self, config):
        # Middleware 启动时向 SkillRegistry 注册一批技能
        from .skills import MY_SKILL_1, MY_SKILL_2
        config.skill_registry.register(MY_SKILL_1)
        config.skill_registry.register(MY_SKILL_2)
```

适合：需要打包一组相关技能 + 配套 Tool + 基础设施的完整能力模块（如"财报分析 Middleware"同时提供 financial_report Tool + 3 个财报解读 Skill）。

#### 5.5.7 SOP 提示词编写指南

好的 Skill prompt 本质上是一份**给 LLM 看的 SOP**，有固定模板：

```
你的身份定位: "你是一位资深 XX 专家"（设定角色，影响回复风格）
任务目标:    一句话说清要做什么
分步骤 SOP:   每步明确：
              - 调哪个 Tool
              - 传什么参数（用 {arg} 占位符）
              - 期望什么结果
              - 失败时如何处理
输出格式:     给出模板（表格 / 列表 / Markdown 结构）
风险约束:     禁止事项（"必须使用工具获取真实数据，不得编造"）
```

一个写得好的 Skill 的判断标准：
1. **可验证**：每步都有明确的输入输出，能复现
2. **参数化**：用 `{arg}` 占位可变部分，而不是硬编码
3. **容错**：告诉 LLM 数据缺失时如何降级（继续？补充？终止？）
4. **边界清晰**：when_to_use 覆盖用户可能的 3-5 种表述方式

#### 5.5.8 Skill 执行链路

```
LLM 判断: "这个任务需要走 SOP"
  ↓
LLM 调用 skills_tool(skill_name="account-insight", arguments={"account_id":"acc_001"})
  ↓
SkillsTool.call() → SkillExecutor.execute()
  ├─ SkillRegistry.get("account-insight")
  ├─ skill.format_prompt(arguments)   # 替换 {account_id} 占位符
  │
  ├─ context == "inline":
  │    返回 formatted_prompt 作为 ToolResult
  │    LLM 看到 prompt 后继续在主对话中调用 query_data / analyze_data ...
  │
  └─ context == "fork":
       AgentFactory.build(agent_name=skill.agent, depth=current_depth+1)
          → 工具集 = 主 Agent 工具集 ∩ skill.allowed_tools
       构建 HumanMessage（包含 formatted_prompt）作为任务指令
       agent.ainvoke({"messages": [human_msg]}, thread_id="skill-xxx-...")
       提取最后一条 AIMessage 作为结果返回
  ↓
SkillTracker.record(execution)        # 记录本次执行的 tool_calls / tokens / duration
  ↓
SkillOptimizer.should_optimize(skill_name)?   # 每 N 次检查一次
  ├─ 是 → 异步触发 optimize()，不阻塞主流程
  └─ 否 → 跳过
  ↓
ToolResult 返回给主 Agent，LLM 基于结果继续对话
```

#### 5.5.9 Skill 自改进循环（SkillTracker + SkillOptimizer + SkillGenerator）

Skill 系统内置**使用数据反哺自身**的闭环：

```
┌──────────────────────────────────────────────────────────┐
│ Phase 1 · 记录（每次执行都写入）                           │
│                                                          │
│ SkillTracker.record(SkillExecution{                      │
│   skill_name, arguments, tool_calls,                    │
│   total_tokens, duration_ms, output,                    │
│   user_feedback (accepted/retry/abandoned/unknown)      │
│ })                                                       │
│   ↓ 持久化                                                │
│ skill_metrics.db                                         │
│   ├─ skill_executions  明细表                             │
│   └─ skill_metrics     聚合表（success_rate / avg_tokens）│
└───────────────────────────┬──────────────────────────────┘
                            ▼
┌──────────────────────────────────────────────────────────┐
│ Phase 2 · 评估（达到阈值时触发）                           │
│                                                          │
│ SkillOptimizer.should_optimize(skill_name)               │
│   触发条件: 执行次数达 optimize_threshold (默认 5) 的整数倍 │
└───────────────────────────┬──────────────────────────────┘
                            ▼
┌──────────────────────────────────────────────────────────┐
│ Phase 3 · 优化（LLM 改写 SKILL.md）                        │
│                                                          │
│ SkillOptimizer.optimize(skill_name)                      │
│   ├─ 读取当前 SKILL.md                                    │
│   ├─ 拉取最近 5 次执行轨迹                                 │
│   ├─ 拉取 metrics（成功率 / 耗时 / token）                 │
│   ├─ LLM 评估 prompt:                                    │
│   │   "SOP 步骤是否都被执行？                              │
│   │    工具调用顺序是否合理？                              │
│   │    参数是否有硬编码应该参数化？                         │
│   │    when_to_use 是否准确？"                            │
│   ├─ LLM 输出改进版 SKILL.md 或 "NO_CHANGE"                │
│   ├─ 校验新版本 (SkillLoader.validate)                    │
│   ├─ 备份旧版本 (.v{N}.md.bak)                            │
│   ├─ 写入新版本                                           │
│   └─ SkillRegistry.register(new_skill)  热更新            │
└───────────────────────────┬──────────────────────────────┘
                            ▼
┌──────────────────────────────────────────────────────────┐
│ Phase 4 · 淘汰（长期低效的技能自动下线）                    │
│                                                          │
│ should_retire 判据:                                      │
│   - 执行次数 ≥ 3 次，但成功率 < 30%，或                    │
│   - 连续 30 天未使用                                      │
│                                                          │
│ SkillOptimizer.cleanup_retiring()                        │
│   删除 SKILL.md + 从 SkillRegistry 下线                   │
└──────────────────────────────────────────────────────────┘
```

**自动生成新 Skill（SkillGenerator）**：

```
场景: 用户让 Agent 完成一个复杂任务（调用 >= 5 次工具）
    ↓
任务完成 → AutoGenerateMiddleware.after_agent
    ↓
SkillGenerator.should_generate(messages)?  # tool_count >= 5
    ├─ 是 → generate_with_llm(messages)
    │    LLM 从对话中提取任务模式
    │    生成 SKILL.md（name / description / when_to_use / arguments / SOP）
    │    写入 ./skills/auto-generated/<name>/SKILL.md
    │    自动注册到 SkillRegistry
    │    下次用户说类似的话 → LLM 直接调用该技能（一次搞定 vs 5 次工具调用）
    └─ 否 → 跳过
```

**效果度量**（对齐 Hermes Agent 的指标体系）：

| 指标 | 含义 | 用途 |
|:---|:---|:---|
| success_rate | user_feedback == "accepted" 的比例 | 判断 SOP 是否有效 |
| avg_tokens | 平均消耗的 token | 判断提示词是否臃肿 |
| avg_duration_ms | 平均执行耗时 | 判断是否需要切换轻量模型 |
| total_executions | 累计执行次数 | 判断是否被真实使用 |
| last_used | 最后使用时间 | 淘汰判据 |
| version | 当前版本号 | 追溯历史变更 |

#### 5.5.10 Skill 开发清单（Checklist）

开发一个新业务 Skill 前，对照以下清单确认：

| ✓ | 检查项 |
|:---:|:---|
| ☐ | 任务是否需要多步骤 LLM 推理？（是 → Skill；否 → Tool） |
| ☐ | 所需工具是否都已在 ToolRegistry 注册？ |
| ☐ | SOP 步骤是否清晰可验证？（每步有输入输出） |
| ☐ | 参数是否都用 `{arg}` 占位，没有硬编码业务值？ |
| ☐ | when_to_use 是否覆盖了用户的 3-5 种表述？ |
| ☐ | context 选择是否正确？（短任务 inline / 长任务 fork） |
| ☐ | allowed-tools 是否是执行 SOP 所需的**最小集合**？ |
| ☐ | 输出格式是否有明确模板？ |
| ☐ | 失败 / 数据缺失的降级路径是否说明？ |
| ☐ | risk_level 是否标注正确？（write / destructive 需走 HITL） |
| ☐ | 是否写了至少一个端到端测试用例？ |


---

### 5.6 三维度协作总览

```
┌────────────────────────────────────────────────────────────────┐
│                         User Request                           │
└──────────────────────────────┬─────────────────────────────────┘
                               │
                  ┌────────────▼────────────┐
                  │      Lead Agent          │
                  └────────────┬────────────┘
                               │
        ┌──────────────────────┼──────────────────────┐
        │                      │                      │
        ▼                      ▼                      ▼
  ┌───────────┐          ┌───────────┐          ┌───────────┐
  │   Tool    │          │   Skill   │          │  Middleware   │
  │ (LLM直调) │          │(Agent SOP)│          │(基础设施) │
  └─────┬─────┘          └─────┬─────┘          └─────▲─────┘
        │                      │                      │
        │ 调用接口              │ 编排多个 Tool         │ 提供能力
        └──────────────────────┼──────────────────────┘
                               │
                               ▼
                     ┌──────────────────┐
                     │   Middleware Context │
                     │ (llm/memory/...)  │
                     └──────────────────┘
```

---

## 六、记忆系统（VikingMemoryEngine）

> 由 memory-middleware 提供，详见《VikingMemoryEngine-长期记忆系统设计.md》《记忆提取与检索.md》《记忆遗忘与反思-设计方案.md》《记忆与系统数据一致性设计.md》。

### 6.1 4 类分类体系

记忆统一为 **4 类**，全部由 LLM 四路并行从用户对话中提取：

| 类别 | 主语判据 | 说明 | 合并策略 | CRM 示例 |
|:---|:---|:---|:---|:---|
| agent_rules | 主语"你"（Agent） | 用户对 Agent 的角色定义与行为准则 | LLM 合并（矛盾以新为准） | "你是我的数据分析助理，回复不超过100字" |
| profile | 主语"我"描述身份 | 用户身份、角色、背景 | 始终追加合并 | "华东区销售总监，管理15人团队" |
| preferences | 主语"我"表达偏好 | 偏好与习惯（按语义 slug 独立） | 同 slug 替换 | "data_display：偏好表格" |
| entities | 主语为第三方 | 客户 / 联系人 / 商机 / 合同 | 同 merge_key 替换 | "华为/ERP项目：500万，谈判阶段" |

> 历史设计中的 `soul` 已在实现里统一命名为 `agent_rules`；历史讨论中出现的 `events / cases / patterns / tools / skills` 不在记忆体系内（运行时指标与经验沉淀走独立机制，见 §6.7）。

### 6.2 存储架构（PG 权威 + 向量库检索）

```
PG (权威数据源 ai_agent_memory 表):
  4 类全量 + L0/L1/L2
  ├── memory_id, tenant_id, user_id, category
  ├── abstract (L0) / overview (L1) / content (L2)
  ├── merge_key, parent_entity, biz_id/biz_parent_id
  ├── status (active/stale/archived/deleted)
  ├── active_count, confidence, last_accessed_at
  └── vector_synced, vector_id

向量库 (语义检索索引):
  只存需要语义检索的类别
  ├── id = memory_id
  ├── embedding = embed(abstract)
  ├── FilterIndex: status, category, tenant_id, user_id, parent_entity
  └── 稀疏向量（BM25）

类别与存储的对应关系:
  仅 PG（精确查询，无语义检索需求）:
    profile, agent_rules
  PG + 向量库（需要语义检索）:
    entities, preferences

同步机制:
  写入: PG 先写 → 异步队列 → 向量库（vector_synced=1）
  状态: 定时任务批量更新 status 到向量库
  检索: 只读向量库（实时）
        异步写 PG（last_accessed_at + active_count）
```

### 6.3 四层召回

| 层 | 触发 | 召回方式 | Token 成本 |
|:---:|:---|:---|:---|
| 1 | 会话开始（一次） | profile + agent_rules 全量注入 | 固定 ~500 |
| 2 | 每轮用户消息 | 意图检测 → entities/preferences 目录递归检索 → 重排序 | ~200–1000 |
| 3 | Agent 主动调用 | search_memories 工具 | 按需 |
| 4 | 技能执行 | 拦截 skill 加载，追加使用经验（来自 §6.7 经验存储） | ~100–500 |

### 6.4 记忆提取原则（四路并行提取器）

```
设计目标:
  1. 一个维度一个 prompt    — 降低分类混淆，四路并行
  2. 只接收 user 消息        — 不从 tool 结果或 assistant 回复中提取
  3. 主语判据               — 用主语区分四个类别（唯一边界依据）
  4. 注入已有记忆           — profile / agent_rules 注入旧内容避免重复提取

四个提取器:
  PROFILE_EXTRACTOR        主语"我"，描述身份 / 角色 / 背景
  PREFERENCES_EXTRACTOR    主语"我"，表达喜好 / 习惯 / 倾向（按 slug 拆分）
  AGENT_RULES_EXTRACTOR    主语"你"，指令 / 约束 / 角色定义
  ENTITIES_EXTRACTOR       主语为第三方，陈述客观事实

不提取:
  - 一次性操作指令（"帮我查XX"）
  - 系统字段值（精确金额、概率、电话等）— 属于业务数据，不是记忆
  - tool 结果里的业务数据（属于 Scratchpad / 工具上下文）
  - 用户与 Agent 的闲聊内容
```

### 6.5 记忆遗忘（三阶段淡化）

```
active ──过期+30天无检索──▶ stale ──30天无检索──▶ archived ──30天无检索──▶ deleted
  ▲                          │                      │
  │        被检索命中          │       被检索命中       │
  └──────────────────────────┴──────────────────────┘
```

| 类别 | active 期 | + stale | + archived | 总生命周期 |
|:---|:---:|:---:|:---:|:---:|
| entities | 180d | 30d | 30d | 240d |
| preferences | 不遗忘，同 slug 自动替换 | — | — | ∞ |
| profile | 不遗忘，超长自动精炼（> 200 字） | — | — | ∞ |
| agent_rules | 不遗忘，超长自动精炼（> 300 字） | — | — | ∞ |

### 6.6 记忆反思（三种触发）

反思只对 **entities** 类别触发（其他三类靠合并策略已足够）：

| 触发 | 时机 | 动作 |
|:---|:---|:---|
| 会话反思 | 每轮对话后（5s 冷却） | 跨 merge_key 冲突检测 |
| 失败反思 | AI / Tool 失败时（60s 冷却） | 检查是否记忆导致错误 |
| 用户纠正反思 | 用户说"不对 / 错了"时（30s 冷却） | 修正旧记忆 |

冲突检测二步法：LLM 分类关系（`identical` / `contradiction` / `evolution` / `unrelated`）→ 规则映射动作（`discard_new` / `archive_old` / `update_old` / `keep_both`）。

### 6.7 运行时经验数据（不属于记忆体系）

部分历史设计中出现的 `events / cases / patterns / tools / skills` 在实际系统里**不作为记忆类别**存在，而是通过独立机制沉淀：

| 数据类型 | 存储 | 产生方式 | 消费者 |
|:---|:---|:---|:---|
| 业务事件（events） | 业务系统本身 + `ai_trace` | 由业务服务产生（签约、客户更名等） | 通过 query_data 工具查询，不进记忆 |
| 失败案例（cases） | ReflectionNode 的内部状态 + 审计日志 | Agent 失败分析的临时产物 | 下一轮对话的 system prompt 局部注入 |
| 经验模式（patterns） | skill 的 prompt 模板（SKILL.md） | SkillOptimizer 从高频成功路径归纳 | 技能执行时自动加载 |
| 工具统计（tools） | SQLite 指标库 `skill_metrics.db` | ToolErrorHandlingMiddleware 实时记录 | SkillOptimizer 判断是否优化技能 |
| 技能统计（skills） | 同上 | SkillTracker 记录每次执行的耗时/成功率/token | 同上 |

**为什么不放进记忆体系**：记忆是"从对话中理解用户"，而工具/技能统计是"系统对自己行为的观测"——两者的生命周期、更新频率、检索方式完全不同。把它们塞进 `ai_agent_memory` 只会污染记忆的语义空间。

**对外表现**：从用户视角看，"Agent 记住了某个工作流程" 是感知到的，但这不通过记忆系统实现，而是通过**技能经验注入**（SkillMiddleware 在技能执行时读 SKILL.md 追加使用经验）。

---

## 七、上下文压缩（四层架构）

> 详见《上下文压缩设计.md》。

### 7.1 四层总览

```
Layer 0 · Scratchpad（外部工作区）
  完整数据不进 LLM 上下文，Agent 按需查询（Redis / PG / 内存）
       ↓
Layer 1 · 源头隔离（100% 对话触发）
  ├─ 前端组件分流（render_type → UI 渲染，不进 LLM）
  ├─ 工具结果 > 阈值 → 两层摘要
  │   1. 代码格式化提取（零 LLM 成本）
  │   2. LLM 摘要兜底
  └─ 原文保存虚拟文件 FileInfo
       ↓
Layer 2 · 当前轮次裁剪（5+ 步复杂任务触发）
  ├─ Pass 1: MD5 去重
  ├─ Pass 2: 保护区外旧 ToolMessage 替换为一行摘要
  └─ Pass 3: tool_call 参数截断（>500 → 200）
       ↓
Layer 3 · 回复摘要回写（>500 字符触发）
  ├─ answerSummary（异步写 PG）
  └─ sessionSummary（迭代更新写 Redis）
       ↓
Layer 4 · 历史上下文构建（100% 非首轮触发）
  双套视图 + sessionSummary 注入 + Prompt Cache
```

### 7.2 CRM 不可回避的六类大数据源

| 类型 | 场景 | 量级 |
|:---|:---|:---|
| D1 大文本字段 | 商机需求描述、客户备注 | 2K–20K 字符 |
| D2 搜索全文 | 竞品定价页、案例详情 | 10K–80K 字符 |
| D3 百级列表 | 总监看全部 pipeline | 15K–75K 字符 |
| D4 跨实体关联 | 客户+商机+联系人+活动+合同 | 20K–120K 字符 |
| D5 对话全文 | 一个月 WhatsApp + 语音转文字 | 5K–100K 字符 |
| D6 元数据定义 | 实体 30–50 字段完整 schema | 5K–20K 字符 |

### 7.3 动态阈值

| 工具类型 | summary_threshold | max_words |
|:---|:---:|:---:|
| 查询类（query_data / query_schema） | 300 | 100 |
| 分析类（analyze_data） | 800 | 200 |
| 外部信息（web_search） | 500 | 150 |
| 财务报价（financial_report） | 1500 | 300 |
| 确认类（save_memory / ask_user） | ∞ | — |

---

## 八、多模态支持

多模态是 CRM 场景的刚需：销售上传合同截图、扫描件、产品照片；总监让 Agent 读 Excel 月报；客服处理用户发来的故障截图；Agent 生成架构图 / 流程图 / 图表回复用户。系统在**输入 / 理解 / 生成 / 存储 / 记忆**五个环节原生支持多模态。

### 8.1 支持的媒体类型

| 类别 | 扩展名 | 处理方式 | 上下文占用 |
|:---|:---|:---|:---|
| 图片 | png / jpg / jpeg / gif / webp / bmp / svg | 直接送入多模态 LLM（VLM） | 按图片 token 计费 |
| 文档 | pdf / docx / xlsx / pptx / csv / txt / md | 文档解析服务（可插拔，腾讯云 LKEAP / 自部署 OCR 等）→ Markdown + 结构化 JSON | 文本 token |
| 屏幕截图 | png / jpg | 走图片路径 | 同图片 |
| 语音 | mp3 / wav / m4a | ASR 转写 + 原音频保留 | 文本 token（转写文本） |
| Agent 生成物 | 图片 / Markdown / 代码 / 图表 JSON | artifact 持久化，前端渲染 | 仅摘要进入上下文 |

### 8.2 多模态数据流（端到端）

```
┌──────────────────────────────────────────────────────────────┐
│ 用户侧                                                        │
│  上传文件 / 拖拽图片 / 粘贴截图 / 录音 → 前端                   │
└───────────────────────────┬──────────────────────────────────┘
                            │ multipart/form-data
                            ▼
┌──────────────────────────────────────────────────────────────┐
│ 上传层 — UploadManager                                        │
│  1. 保存文件到对象存储（COS / OSS）→ 生成 URL                  │
│  2. 识别 MIME 类型 → 记录 FileMetadata                        │
│  3. 文档类型 → 调文档解析服务（腾讯云 LKEAP / 自部署）→ Markdown │
│  4. 图片类型 → 不预处理（直接走 VLM）                          │
│  5. 语音类型 → 调 ASR 获取转写                                │
└───────────────────────────┬──────────────────────────────────┘
                            │ configurable["files"] = [...]
                            ▼
┌──────────────────────────────────────────────────────────────┐
│ FileProcessMiddleware.before_agent                           │
│  识别 fileType：image / document / audio                     │
│  归一化字段 → state.thread_data.parsed_files                  │
│  每个文件: {fileName, fileType, content(文本), url, mediaId}  │
└───────────────────────────┬──────────────────────────────────┘
                            │
          ┌─────────────────┼─────────────────┐
          │                 │                 │
          ▼                 ▼                 ▼
     图片路径          文档路径            Agent 主动调用
     (direct VLM)   (load_file_content)   (load_file_content)
          │                 │                 │
          │                 │                 │
┌─────────▼──────────┐  ┌──▼──────────────┐  │
│ Multimodal         │  │ 文本内容直接注入 │  │
│ InjectMiddleware   │  │ LLM 上下文       │  │
│ .before_model      │  │ (>10K 自动截断)  │  │
│                    │  │                  │  │
│ 将 image url 以    │  └──────────────────┘  │
│ {"type":"image_url"│                        │
│  "image_url":{"url"│   当图片未预注入时 ────┘
│  :"..."}} 格式     │   load_file_content 返回
│ 插入 HumanMessage  │   ATTACHMENT_MARKER，
│                    │   下一轮再注入
└─────────┬──────────┘
          │
          ▼
    多模态 LLM (VLM)
     ├─ 看图回答问题
     ├─ 提取图表数据
     └─ 理解截图内容
          │
          ▼
     回复文本 / 调用工具 / 生成 artifact
```

### 8.3 多模态消息格式（OpenAI 兼容，豆包 / DeepSeek / Claude 通用）

```python
# 用户消息含图片
HumanMessage(content=[
    {"type": "text", "text": "帮我看这张合同截图里的总金额"},
    {"type": "image_url", "image_url": {"url": "https://cos.../contract.png"}},
])

# 用户消息含文档（文本化后）
HumanMessage(content=[
    {"type": "text", "text": "分析这份月报"},
    {"type": "text", "text": "[附件: monthly_report.pdf]\n## 1. 销售概况\n..."},
])

# Agent 生成图片回复
AIMessage(content=[
    {"type": "text", "text": "按你的需求画了一张架构图，要点如下："},
], artifacts=[
    Artifact(id="artifact_001", type="image", title="系统架构图",
             content="https://cos.../generated/arch.png"),
])
```

### 8.4 图片路径 — 直接走 VLM

```
上传图片 → UploadManager 存 COS → URL 回传
              │
              ▼
   FileProcessMiddleware 写入 parsed_files
              │
              ▼
   MultimodalInjectMiddleware.before_model
     检查 parsed_files 中的 fileType == "image"
     将 image URL 以 content part 格式拼入最新 HumanMessage
              │
              ▼
   多模态 LLM 看图 + 文 → 回复
```

**关键设计**：图片不需要 LLM 主动调用工具就能看到，系统自动注入。这符合"用户拖了图就是想让 Agent 看到"的直觉。

### 8.5 文档路径 — 解析 + 按需加载

```
上传文档 → UploadManager
            │
            ├─ PDF/DOCX/PPTX/XLSX → 文档解析服务（可插拔）→ Markdown + 结构化 JSON
            │   （保留表格 / 公式 / 图片描述；供应商可替换：腾讯云 LKEAP / 自部署 OCR / Apache Tika 等）
            ├─ CSV/TXT/MD → 直接文本读取
            └─ 存 parsed_files.content (文本) + .url (原文件)

LLM 调用 load_file_content 工具 →
  ├─ 文件有 content 字段 → 返回文本（超 10K 自动截断）
  ├─ 文件只有 URL（扫描 PDF 等图片型文档）
  │   → 返回 ATTACHMENT_MARKER 标记
  │   → MultimodalInjectMiddleware 下一轮注入为 input_file
  │   → VLM 读图式理解
  └─ 图片文件 → 同上，注入为 input_image
```

**关键设计**：文档不自动注入，由 LLM 按需通过 `load_file_content` 工具加载，避免长文档占满上下文。

### 8.6 Agent 生成物（Artifact / Image）

Agent 的输出不只是文本，还包括结构化生成物：

| 类型 | 生成方式 | 存储 | 前端渲染 |
|:---|:---|:---|:---|
| artifact · 代码 | LLM 直接输出 | `state.artifacts` + ai_message_ext | Monaco / 代码块 |
| artifact · 文档 | LLM 输出 Markdown | 同上 | Markdown 渲染 |
| artifact · 图表 | LLM 输出 chart schema（Vega-Lite / ECharts） | 同上 | 图表组件 |
| image · 生成图 | `generate_image` 工具调图像生成厂商（OpenAI / 字节豆包 / 百度文心一格 等） | COS + `state.images` | `<img>` |
| image · 数据可视化 | LLM 输出 chart → 前端渲染 → 截图存档 | COS + `state.images` | `<img>` |

Artifact 持久化到 `ai_message_ext` 表（type='artifact'），前端通过 AG-UI 事件流增量接收（`ARTIFACT_CREATED` / `ARTIFACT_UPDATED`）。

### 8.7 多模态 × 上下文压缩

多模态内容的压缩策略与文本不同：

```
┌─────────────────────────────────────────────────────────────┐
│ Layer 1 · 源头隔离                                           │
│  图片 content part → 保留（视觉信息不可摘要）                │
│  文档 load_file_content 结果 → 按阈值摘要（见 7.3）           │
│  Artifact → 摘要进 LLM，原文存 parsed_files                  │
└─────────────────────────────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────────────────────────┐
│ Layer 2 · 轮次裁剪                                           │
│  同一图片 URL 重复注入 → 去重（只保留最新一次）               │
│  旧轮次 image content part → 替换为 "[历史图片: xxx]" 文本   │
│  保护当前轮次的所有图片 + 最近 3 轮的图片                    │
└─────────────────────────────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────────────────────────┐
│ Layer 3 · 回复摘要                                           │
│  Agent 理解图片后的文字结论 → 写入 answerSummary             │
│  （下次调用时只看得到结论，不重复消耗视觉 token）             │
└─────────────────────────────────────────────────────────────┘
```

**图片 Token 控制**：
- 单图 2000 × 2000 约 1200 tokens（以主流多模态模型为参考，具体计费规则视厂商而定）
- 单轮对话默认最多 5 张图片（超限自动降质 / 截断）
- 历史轮次图片超过 3 轮未引用 → 替换为文字占位符

### 8.8 多模态 × 记忆

多模态内容的记忆有两条原则：**视觉内容不存向量库，存文字结论**。

```
用户上传合同截图 → VLM 识别 → Agent 回复"合同金额500万，甲方华为"
  ↓
LLM 提取 → entities 记忆
  abstract: "华为合同：金额500万"
  content:  "用户上传了华为合同截图，识别到甲方华为、金额500万..."
  metadata: {source_type: "image_extracted", image_url: "..."}

下次检索"华为合同金额" → 直接命中文字记忆，无需重新读图
```

| 场景 | 存什么 | 不存什么 |
|:---|:---|:---|
| 合同 / 截图识别 | 识别出的关键字段（金额 / 客户 / 日期） + 原图 URL | 图片本身的 embedding |
| 产品照片 | 用户/Agent 对照片的描述和判断 | 原图 embedding |
| 图表截图 | 图表的数据结论、趋势判断 | 像素级信息 |

原图 URL 存在 `ai_message_ext.attachments` 表，记忆只存文字抽象。如果未来需要以图搜图，可以单独加一个 `image_memory` 表，但不混入现有 4 类。

### 8.9 多模态 × AG-UI / A2UI

多模态的展示离不开前端协议支撑（详见第十章）：

```
图片消息       → CUSTOM "attachment_added" (type: input_image)
Agent 生成图   → CUSTOM "artifact_created" (type: image, url)
Artifact 流式 → CUSTOM "artifact_updated" (content_delta)
音频播放       → CUSTOM "attachment_added" (type: audio, url)
图表 Artifact → A2UI ComponentMatcher 匹配 chart_block → 前端渲染 Vega-Lite
看图分析过程   → REASONING_CONTENT 下发推理过程给前端可视化
```

VLM 的视觉理解能力 + AG-UI 的流式推理事件 = 前端可以把"Agent 看图的思考过程"动态展示给用户（如高亮关注区域、分步骤输出结论）。

### 8.10 语音（可选扩展）

| 输入 | 处理 | 产出 |
|:---|:---|:---|
| 用户录音 | ASR 转写（腾讯云 ASR / 豆包语音） | 文本 content，原音频存 COS |
| 销售通话录音 | ASR + 说话人分离 + 情感分析 | 结构化 JSON，写 entities 记忆 |
| Agent 语音回复 | TTS 合成 | 音频 URL，AG-UI 事件下发 |

语音转写后走纯文本路径，不占用 VLM token。

### 8.11 安全与合规

| 风险 | 控制点 |
|:---|:---|
| 违规图片（色情 / 暴力 / 政治敏感） | FileProcessMiddleware 调用图像审查 API → 拒绝 / 模糊处理 |
| OCR 泄漏 PII（身份证 / 银行卡） | 文档解析返回后经 PII 脱敏管线 |
| 水印泄露（商业机密） | Artifact 生成图加上租户水印 |
| 图片链接越权访问 | 所有图片 URL 附带租户签名，失效时间 1h |
| 文件格式攻击（恶意 PDF） | UploadManager 白名单 + 大小限制（图片 ≤ 20MB，文档 ≤ 100MB） |

### 8.12 前端侧多模态展示

对齐 CRM 系统的视觉规范，多模态交互提供以下专属组件：

| 组件 | 用途 |
|:---|:---|
| ImageMessage | 用户/Agent 图片消息气泡 |
| FileMessage | 文档消息（图标 + 文件名 + 大小 + 下载） |
| ImagePreviewModal | 图片放大预览 |
| ArtifactPanel | 右侧 artifact 面板（代码 / 文档 / 图表多 tab） |
| AudioPlayer | 语音消息播放器 |
| UploadDropzone | 拖拽上传区（含粘贴图片） |

---

## 九、子 Agent 设计

### 9.1 两种模式

| 模式 | 触发工具 | 执行 | 适用场景 |
|:---|:---|:---|:---|
| 同步 | `delegate_task` | 阻塞等待 | 短任务（<2min）：查询、校验、分析 |
| 异步 | `start_async_task` | 不阻塞 | 长任务（>2min）：调研、批处理、迁移 |

### 9.2 继承与隔离

```
继承: tenant_id / user_id / llm-middleware / memory-middleware / 审计日志
隔离: messages（独立历史）/ session_id（派生）/ notification（不发）/ HITL（不弹）
限制: 工具按 agent_type 裁剪 / max_llm_calls 独立 / depth ≤ 3
```

### 9.3 7 个业务域子 Agent

| 域 | 类型 | 工具集 | 典型任务 |
|:---|:---|:---|:---|
| 销售 | sales | query_data, analyze_data, company_info, financial_report, web_search, search_memories | 客户背景、商机分析、竞品调研 |
| 客服 | service | query_data, query_schema, web_search, search_memories, ask_user | 诊断问题、搜方案 |
| 分析 | analytics | query_data, analyze_data, financial_report, web_search, search_memories | 数据统计、趋势、异常 |
| 配置 | config | query_schema, query_data, query_permission, search_memories, ask_user | 对象配置、字段规则 |
| 数据 | data_ops | query_schema, query_data, analyze_data, modify_data, ask_user | 数据清理、批量更新 |
| 调研 | research | web_search, company_info, financial_report, search_memories | 行业、尽调、政策 |
| 通用 | general | 主 Agent 全部（除编排工具） | 无法归类 |

### 9.4 工具裁剪算法

```
最终工具集 = 主 Agent 工具集 ∩ 业务域默认工具集 ∩ LLM 请求工具集

约束:
  - delegate_task / start_async_task 只有主 Agent 可用（不可递归派生）
  - 每个域工具集是最小必要集合
  - 租户可覆盖默认配置
```

### 9.5 异步子 Agent 管理工具

| 工具 | 功能 |
|:---|:---|
| start_async_task | 启动，返回 task_id |
| check_async_task | 查状态 / 取结果 |
| update_async_task | 发送后续指令（有状态） |
| cancel_async_task | 取消 |
| list_async_tasks | 列出全部任务 |

---

## 十、协议层（AG-UI + A2UI）

Agent 与前端的交互通过两个开放协议解耦：**AG-UI** 承担实时事件流（Agent 在做什么），**A2UI** 承担动态组件渲染（Agent 输出该怎么展示）。两者配合，第三方前端只要实现协议就能接入系统，无需知道后端实现细节。

### 10.1 协议职责分工

```
┌────────────────────────────────────────────────────────────┐
│                      Agent 运行时                           │
└──────────────┬──────────────────────────────┬──────────────┘
               │                              │
               │ astream_events                │ render_hint
               │                              │  + custom data
               ▼                              ▼
       ┌──────────────────┐          ┌───────────────────┐
       │  AG-UI Converter │          │ A2UI Progressive  │
       │                  │          │   Renderer        │
       │ 运行时事件 →     │          │                   │
       │ AG-UI 标准事件流  │          │ STEP 边界 →        │
       │                  │          │ 组件 loading/     │
       └────────┬─────────┘          │ delta/complete    │
                │                     └──────┬────────────┘
                │                            │
                └──────────┬─────────────────┘
                           │ SSE 事件流
                           ▼
                  ┌──────────────────┐
                  │    前端 (任意)    │
                  │  React / Vue /   │
                  │  小程序 / 第三方  │
                  └──────────────────┘
```

| 协议 | 定位 | 内容 | 参考 |
|:---|:---|:---|:---|
| **AG-UI** | Agent ↔ UI **事件流协议** | 运行状态、文本流、工具调用、推理过程、消息快照 | [ag-ui.com/concepts/events](https://docs.ag-ui.com/concepts/events) |
| **A2UI** | Agent-to-UI **动态组件协议** | 根据 Agent 输出内容渲染业务组件（客户画像卡 / BANT 分析 / Pipeline 看板 …） | 本项目自定义，基于 AG-UI `CUSTOM` 事件扩展 |

### 10.2 AG-UI 事件类型

```python
class AGUIEventType(str, Enum):
    # ── 运行生命周期 ──
    RUN_STARTED = "RUN_STARTED"
    RUN_FINISHED = "RUN_FINISHED"
    RUN_ERROR = "RUN_ERROR"

    # ── 文本消息流（三段式状态机）──
    TEXT_MESSAGE_START = "TEXT_MESSAGE_START"
    TEXT_MESSAGE_CONTENT = "TEXT_MESSAGE_CONTENT"    # delta 增量
    TEXT_MESSAGE_END = "TEXT_MESSAGE_END"

    # ── 工具调用 ──
    TOOL_CALL_START = "TOOL_CALL_START"
    TOOL_CALL_ARGS = "TOOL_CALL_ARGS"                # 参数增量
    TOOL_CALL_END = "TOOL_CALL_END"
    TOOL_CALL_RESULT = "TOOL_CALL_RESULT"

    # ── 步骤（Skill / SubAgent 边界）──
    STEP_STARTED = "STEP_STARTED"                    # skill_apikey, step_index
    STEP_FINISHED = "STEP_FINISHED"                  # status: completed/failed

    # ── 推理过程（thinking 模型）──
    REASONING_STARTED = "REASONING_STARTED"
    REASONING_CONTENT = "REASONING_CONTENT"          # delta 增量
    REASONING_FINISHED = "REASONING_FINISHED"

    # ── 状态同步 ──
    MESSAGES_SNAPSHOT = "MESSAGES_SNAPSHOT"          # 完整消息列表

    # ── 扩展通道（A2UI 走这里）──
    CUSTOM = "CUSTOM"
```

### 10.3 AG-UI 事件流示例（SSE 格式）

```
event: RUN_STARTED
data: {"run_id":"r_001","thread_id":"t_abc"}

event: TEXT_MESSAGE_START
data: {"message_id":"m_001"}

event: TEXT_MESSAGE_CONTENT
data: {"message_id":"m_001","delta":"我来查一下华为"}

event: TEXT_MESSAGE_CONTENT
data: {"message_id":"m_001","delta":"的商机情况。"}

event: TEXT_MESSAGE_END
data: {"message_id":"m_001"}

event: TOOL_CALL_START
data: {"tool_call_id":"tc_001","tool_name":"query_data"}

event: TOOL_CALL_ARGS
data: {"tool_call_id":"tc_001","args":{"entity":"opportunity","filters":{"customer":"华为"}}}

event: TOOL_CALL_END
data: {"tool_call_id":"tc_001"}

event: TOOL_CALL_RESULT
data: {"tool_call_id":"tc_001","result":{"records":[...],"count":3}}

event: CUSTOM
data: {"name":"component_loading","value":{"apikey":"pipeline_dashboard","state":"loading"}}

event: CUSTOM
data: {"name":"component_complete","value":{"apikey":"pipeline_dashboard","data":{...}}}

event: TEXT_MESSAGE_START
data: {"message_id":"m_002"}

event: TEXT_MESSAGE_CONTENT
data: {"message_id":"m_002","delta":"华为有 3 个活跃商机，总金额 780 万。"}

event: TEXT_MESSAGE_END
data: {"message_id":"m_002"}

event: RUN_FINISHED
data: {"run_id":"r_001","thread_id":"t_abc"}
```

### 10.4 A2UI 协议（Agent 驱动动态组件）

A2UI 解决的核心问题：**Agent 想展示专业业务组件（如客户画像卡、BANT 四象限、Pipeline 看板），但不应该让后端关心前端组件代码**。协议让 Agent 通过语义 key 指定"要渲染什么"，前端负责"怎么渲染"。

#### 10.4.1 核心概念

```
skill_apikey    — Agent 执行的技能标识（如 customer_360_analysis）
                  由后端 Skill 注册表管理
component_apikey — 前端组件库中注册的业务组件标识（如 customer_profile_card）
                  由前端组件库维护
ComponentMatcher — 二者的映射层（skill_apikey → component_apikey）
                  可以是静态映射、租户配置、Schema 匹配
```

#### 10.4.2 生命周期（loading → delta → complete / error）

```
┌────────────────────────────────────────────────────────────┐
│ 1. STEP_STARTED                                             │
│    Agent: 开始执行 skill "customer_360_analysis"            │
│    A2UI:  ComponentMatcher 查找对应组件                     │
│    推送 CUSTOM "component_loading"                         │
│    前端: 渲染骨架屏 / Loading 状态                          │
└────────────────────────────────────────────────────────────┘
                             │
                             ▼
┌────────────────────────────────────────────────────────────┐
│ 2. 执行过程中（可选）                                       │
│    Skill 通过 renderer.push_delta() 推送中间数据            │
│    推送 CUSTOM "component_delta"                           │
│    前端: 流式更新组件内容                                    │
└────────────────────────────────────────────────────────────┘
                             │
                             ▼
┌────────────────────────────────────────────────────────────┐
│ 3. STEP_FINISHED                                            │
│    skill 完成 → 推送 CUSTOM "component_complete" + 数据     │
│    skill 失败 → 推送 CUSTOM "component_error" + 错误信息    │
│    前端: 切换到完成态 / 错误态                              │
└────────────────────────────────────────────────────────────┘
```

#### 10.4.3 ComponentMatcher 接口

```python
class ComponentMatcher:
    """将 Skill 执行意图映射到前端组件"""

    def resolve(self, skill_apikey: str) -> str | None:
        """skill_apikey → component_apikey（未匹配返回 None 走纯文本回复）"""

    def register(self, skill_apikey: str, component_apikey: str) -> None:
        """注册映射关系"""

    def warmup(self) -> None:
        """启动时预热（加载配置 / 缓存）"""


# 三种典型实现
class StaticComponentMatcher(ComponentMatcher):
    """配置文件静态映射（默认实现）"""

class TenantComponentMatcher(ComponentMatcher):
    """按租户查库匹配（同一 skill 不同租户用不同组件）"""

class SchemaComponentMatcher(ComponentMatcher):
    """按数据 schema 自动匹配（Agent 返回什么结构就渲染什么组件）"""
```

#### 10.4.4 Tool.render_hint 与 A2UI 的衔接

Tool 返回结果时可以声明 `render_hint`，直接指定前端组件：

```python
# Tool 中返回（不走 Skill 边界，直接触发组件）
return ToolResult(
    content="华为科技: 年营收1200亿，通信行业龙头",
    render_hint=RenderHint(
        render_type="customer_profile_card",         # component_apikey
        props_data={
            "name": "华为科技",
            "revenue": "1200亿",
            "industry": "通信",
            "contacts": [...],
        },
        template="{name}年营收{revenue}，{industry}行业龙头",  # 降级文本
    ),
)

# OutputRenderMiddleware 识别后发出 CUSTOM 事件
→ CUSTOM "component_complete" { apikey: "customer_profile_card", data: {...} }
```

### 10.5 A2UI 典型业务组件清单（CRM 场景）

| 组件 apikey | 对应 Skill / Tool | 用途 |
|:---|:---|:---|
| pipeline_dashboard | pipeline_analysis skill | Pipeline 看板（阶段 / 负责人 / 金额分布） |
| customer_profile_card | query_data (customer) + company_info | 客户 360 画像卡 |
| bant_analysis | deal_coaching skill | BANT 四象限分析（Budget / Authority / Need / Timeline） |
| competitive_matrix | competitive_analysis skill | 竞品对比矩阵 |
| data_grid | query_data | 结构化数据表格（可排序 / 筛选 / 导出） |
| chart_block | analyze_data | 图表区块（柱状 / 折线 / 饼图） |
| permission_tree | query_permission | 权限树可视化 |
| schema_designer | query_schema / modify_schema | 元数据配置向导 |
| todo_tracker | TodoMiddleware | Agent 任务清单 |
| trace_panel | TracingMiddleware | 执行链路可视化 |

### 10.6 AG-UI × 多模态

多模态生成物（图片 / Artifact / 语音）通过 AG-UI 事件流独立下发：

```
event: CUSTOM
data: {"name":"artifact_created","value":{
  "artifact_id":"a_001","type":"image","title":"系统架构图","url":"..."
}}

event: CUSTOM
data: {"name":"artifact_updated","value":{
  "artifact_id":"a_001","content_delta":"..."
}}

event: CUSTOM
data: {"name":"attachment_added","value":{
  "type":"input_image","url":"...","role":"assistant"
}}
```

### 10.7 协议管道工厂

```python
def create_agui_pipeline(
    run_id: str,
    thread_id: str,
    history_messages: list[dict] | None = None,
    component_map: dict[str, str] | None = None,
) -> tuple[AGUIConverter, ProgressiveRenderer]:
    """创建 AG-UI 转换 + A2UI 渲染管道

    用法:
        converter, renderer = create_agui_pipeline(run_id, thread_id)
        async for event in renderer.process(
            converter.convert(agent.astream_events())
        ):
            yield event.to_sse()
    """
```

### 10.8 协议的开放性

| 特性 | 收益 |
|:---|:---|
| 标准化事件类型 | 第三方前端可按协议对接，不锁定特定框架 |
| 组件语义解耦 | 后端只管 skill_apikey，前端按需实现 component_apikey |
| 增量更新 | STEP + delta 机制支持组件内流式渲染 |
| 降级友好 | 组件未注册时自动走 `template` 纯文本回复 |
| 多端适配 | 同一套事件流可驱动 Web / 小程序 / 桌面端 |
| 审计可回放 | 事件流完整存档后可按时间戳重放整个对话 |

---

## 十一、内容审查（Content Review）

> 详见《内容审查设计方案.md》。

### 11.1 两阶段审查

```
输入审查  — ContentReviewTransformer（InputTransformMiddleware 内）
           在 PII 脱敏之前拦截违规内容

输出审查  — OutputValidationMiddleware（after_model hook）
           每轮 LLM 输出后拦截（含工具结果再送 LLM 前）

图像审查  — FileProcessMiddleware（详见第八章 8.11）
           用户上传图片送入 VLM 前做视觉内容审查
```

### 11.2 配置模型

```python
@dataclass
class ContentReviewConfig:
    keywords: list[str]           # 敏感词列表
    input_message: str            # 输入拦截提示
    output_message: str           # 输出拦截提示
    is_input: bool = True
    is_output: bool = True
    case_sensitive: bool = False
```

### 11.3 降级策略

```
审查异常 → 放行，记录日志
审查命中输入 → 替换 HumanMessage 为拦截提示 → Agent 回复"无法处理"
审查命中输出 → 替换 AIMessage 为拦截提示 → Agent 停止循环
审查命中图像 → 拒绝注入 VLM，返回"图片涉及违规内容"
```

---

## 十二、数据库模型

> 详见《数据库表设计.md》。

### 12.1 核心表

| 表 | 用途 | 关键字段 |
|:---|:---|:---|
| ai_agent_memory | 记忆权威源（4 类 + L0/L1/L2） | memory_id, category (profile/preferences/agent_rules/entities), abstract, overview, content, merge_key, parent_entity, biz_id, status, vector_synced |
| ai_conversation | 会话元数据 | thread_id, title, summary, token_count |
| ai_message | 用户 Q&A 对 | thread_id, role, content, trace_id |
| ai_message_ext | 附件 / 卡片 / 反馈 / **artifact / image** | message_id, type (attachment/artifact/image/card/feedback), payload |
| ai_upload_file | 用户上传文件元数据（多模态入口） | file_id, thread_id, file_name, mime_type, size, url, markdown_path, parse_status |
| ai_trace | 完整执行 trace | trace_id, session_id, duration, token_total |
| ai_trace_span | 单步 span | trace_id, span_type (context/memory/llm/tool/file_parse), parent_span_id |
| ai_content_review_log | 审查拦截审计 | action, keyword, original, replaced, modality (text/image) |
| ai_token_usage | Token 消耗聚合 | tenant_id, date, model, prompt_tokens, completion_tokens, **vision_tokens** |
| skill_metrics | 技能 / 工具执行统计（非记忆） | skill_name / tool_name, execution_id, duration_ms, success, token_used, error_type |

### 12.2 关键索引

```sql
idx_memory_user_cat        (tenant_id, user_id, category, delete_flg)
uk_memory_merge            (tenant_id, user_id, category, merge_key)   UNIQUE
idx_memory_parent          (tenant_id, user_id, parent_entity)
idx_memory_biz_id          (biz_id)
idx_memory_status_time     (tenant_id, category, status, updated_at)
idx_memory_vector_sync     (vector_synced, updated_at)
idx_memory_thread          (tenant_id, thread_id)
idx_upload_thread          (tenant_id, thread_id, delete_flg)
idx_message_ext_type       (message_id, type)
```

### 12.3 基线约束（对齐 aPaaS 平台）

```
1. BaseEntity 6 字段必须: id / delete_flg / created_at / created_by / updated_at / updated_by
2. 布尔统一 xxxFlg + SMALLINT(0/1)，禁用 Boolean / ENUM / AUTO_INCREMENT
3. 所有 DDL 兼容 MySQL + PostgreSQL
4. 字段命名 snake_case（表/列）+ camelCase（api_key / Java 字段）
5. 租户隔离 tenant_id BIGINT 必填，默认 0
6. 多模态文件 URL 带租户签名，过期时间 1h
```

---

## 十三、系统横切关注点

### 13.1 租户隔离（TenantMiddleware）

```
before_step:
  1. 根据 state.tenant_id 加载租户配置
  2. 注入租户上下文到 system prompt（名称 / 行业 / 规模）
  3. 按租户开关过滤 Tool / Skill / Middleware
  4. 隔离记忆空间（所有查询加 tenant_id 过滤）
  5. 隔离审计日志
  6. 隔离上传文件（COS 路径按 tenant_id 分隔）
```

### 13.2 审计日志（AuditMiddleware + audit-middleware）

记录维度：

| 层级 | 记录内容 |
|:---|:---|
| LLM 调用 | prompt_hash / model / tokens_in/out / **vision_tokens** / latency / cost |
| Tool 执行 | tool_name / input / output_hash / 成功失败 / latency |
| 文件解析 | file_id / mime_type / parse_backend / duration |
| 状态变更 | 节点切换 / HITL 暂停恢复 / 错误升级 |
| 记忆写入 | memory_id / category / 冲突检测结果 |
| 内容审查 | 命中规则 / 替换前后 / 审查模态（text/image） |

落地位置：`ai_trace` + `ai_trace_span` + `ai_content_review_log`。

### 13.3 观测与调试

- 前端链路面板 `/static/trace_explorer.html`
- 记忆浏览器 `/static/memory_browser.html`
- 按 source 过滤（Agent / Middleware / Tool / Skill / SubAgent）
- Span 级耗时、token、状态展示

---

## 十四、核心设计原则

1. **抽象层优先** — Router / Node / Middleware / Middleware 接口稳定，底层框架可替换
2. **单向依赖** — Skill → Tool → Middleware，逆向禁止
3. **ToolRegistry 唯一真相源** — 禁止 Middleware 直接注册 Tool，Tool 通过 `is_enabled()` 检查 Middleware
4. **元数据驱动** — 业务对象、字段、权限全部走 aPaaS 元数据，Agent 不硬编码业务 Schema
5. **租户隔离优先** — 所有存储、缓存、队列、索引、上传文件都按 tenant_id 分隔
6. **多模态原生** — 图片 / 文档 / 语音 / 生成物作为一等公民，不绕弯子做文本转换
7. **协议开放** — AG-UI + A2UI 标准化事件与组件协议，前端按协议对接即可，不锁定实现
8. **优雅降级** — 审查 / 记忆 / Middleware / 文件解析失败不阻塞主流程
9. **可观测** — 从 LLM 调用到文件解析全链路 span 可追溯
10. **渐进沉淀** — 会话 → 记忆 → 技能，用户行为持续反哺系统能力
