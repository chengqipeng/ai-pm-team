# Agent + Skills + Tools 技术设计方案

> 基于 my-claude-code 项目源码深度分析，设计面向 aPaaS 平台的智能 Agent 系统

## 1. 设计背景与目标

### 1.1 源码分析结论

通过对 my-claude-code 项目的深度代码分析，提炼出以下核心架构模式：

| 维度 | my-claude-code 实现 | 本方案借鉴点 |
|------|---------------------|-------------|
| Agent 循环 | `query.ts` → `queryLoop()` 异步生成器驱动的 agentic loop | 采用相同的 while(true) + yield 模式 |
| 工具抽象 | `Tool.ts` 35+ 字段的结构化类型，`buildTool()` 工厂函数 | 统一 Tool 接口 + 工厂模式 |
| 技能系统 | `bundledSkills.ts` + `loadSkillsDir.ts` 多源加载 | 分层技能注册（内置/文件/插件/MCP） |
| 子 Agent | `AgentTool` + `runAgent()` 独立工具池 + 权限隔离 | 星型编排 + 工具池独立组装 |
| 容错机制 | `categorizeRetryableAPIError()` + 权限拒绝追踪 + 自动压缩 | 分级重试 + 反思 + 降级 |
| 状态管理 | `AppStateStore` 外部存储 + React `useSyncExternalStore` | 不可变状态 + 订阅模式 |

### 1.2 设计目标

1. Agent 自身逻辑完整性：完整的消息循环、上下文管理、生命周期控制
2. Skill 体系设计：多源加载、动态发现、隔离执行
3. Tools 体系设计：统一接口、权限控制、结果预算
4. 完整调用逻辑：从用户输入到工具执行到结果回传的全链路
5. 容错与反思机制：重试、降级、自我纠错

---

## 2. 整体架构

### 2.1 三层架构总览

```
┌─────────────────────────────────────────────────────────┐
│                    用户交互层 (UI Layer)                   │
│  Chat UI / CLI / SDK / API                               │
└──────────────────────┬──────────────────────────────────┘
                       │ UserMessage
                       ▼
┌─────────────────────────────────────────────────────────┐
│                  Agent 编排层 (Orchestration)              │
│                                                          │
│  ┌──────────┐  ┌──────────┐  ┌──────────────────────┐   │
│  │ Agent    │  │ Context  │  │ State Manager        │   │
│  │ Loop     │  │ Manager  │  │ (AppStateStore)      │   │
│  │ Engine   │  │          │  │                      │   │
│  └────┬─────┘  └────┬─────┘  └──────────┬───────────┘   │
│       │              │                    │               │
│  ┌────▼──────────────▼────────────────────▼───────────┐  │
│  │           Skill Router / Dispatcher                 │  │
│  └────────────────────┬───────────────────────────────┘  │
└───────────────────────┼──────────────────────────────────┘
                        │ ToolUse / SkillInvoke
                        ▼
┌─────────────────────────────────────────────────────────┐
│                  执行层 (Execution Layer)                  │
│                                                          │
│  ┌────────────┐ ┌────────────┐ ┌────────────────────┐   │
│  │ Built-in   │ │ MCP Tools  │ │ Sub-Agent          │   │
│  │ Tools      │ │            │ │ (Fork/Named)       │   │
│  └────────────┘ └────────────┘ └────────────────────┘   │
│  ┌────────────┐ ┌────────────┐ ┌────────────────────┐   │
│  │ Bundled    │ │ File-based │ │ Plugin Skills      │   │
│  │ Skills     │ │ Skills     │ │                    │   │
│  └────────────┘ └────────────┘ └────────────────────┘   │
└─────────────────────────────────────────────────────────┘
```

### 2.2 核心数据流

```
用户输入 → processUserInput() → 解析斜杠命令/参数替换
    ↓
QueryEngine.submitMessage()
    ├── 组装 SystemPrompt (systemContext + userContext + claudeMd)
    ├── 构建 ToolUseContext (tools + permissions + state)
    ├── 调用 query() 进入 agentic loop
    │   ├── API 调用 (Claude/其他 LLM)
    │   ├── 流式接收 tool_use blocks
    │   ├── 对每个 tool_use:
    │   │   ├── findToolByName() → 查找工具
    │   │   ├── validateInput() → 输入校验
    │   │   ├── canUseTool() → 权限检查 (allow/deny/ask)
    │   │   ├── tool.call() → 执行操作
    │   │   ├── mapToolResultToToolResultBlockParam() → 格式化结果
    │   │   └── yield Message → 流式返回
    │   └── 判断是否继续循环 (有 tool_use → 继续; 纯文本 → 结束)
    └── 返回最终结果
```

---

## 3. Agent 核心设计（逻辑完整性）

### 3.1 Agent Loop Engine

借鉴 `query.ts:queryLoop()` 的设计，Agent 循环引擎是整个系统的心脏：

```typescript
// 核心类型定义
interface AgentLoopState {
  messages: Message[]              // 对话历史
  toolUseContext: ToolUseContext    // 工具执行上下文
  turnCount: number                // 当前轮次
  maxTurns?: number                // 最大轮次限制
  hasAttemptedReactiveCompact: boolean  // 是否已尝试上下文压缩
  maxOutputTokensRecoveryCount: number  // token 超限恢复次数
}

// Agent Loop 核心逻辑 (借鉴 query.ts:241 queryLoop)
async function* agentLoop(params: AgentLoopParams): AsyncGenerator<Message> {
  let state: AgentLoopState = initializeState(params)

  while (true) {
    // 1. 上下文预处理
    let messagesForQuery = applyContextManagement(state.messages)

    // 2. 组装完整 System Prompt
    const fullSystemPrompt = buildSystemPrompt(
      params.systemPrompt,
      params.systemContext,
      params.userContext
    )

    // 3. 调用 LLM API
    const response = await callLLM({
      systemPrompt: fullSystemPrompt,
      messages: messagesForQuery,
      tools: state.toolUseContext.options.tools,
      maxOutputTokens: state.maxOutputTokensOverride
    })

    // 4. 处理响应
    const assistantMessage = parseResponse(response)
    yield assistantMessage

    // 5. 提取 tool_use blocks
    const toolUseBlocks = extractToolUseBlocks(assistantMessage)

    // 6. 终止条件判断
    if (toolUseBlocks.length === 0) {
      return // 纯文本响应，结束循环
    }
    if (state.turnCount >= (state.maxTurns ?? Infinity)) {
      return // 达到最大轮次
    }

    // 7. 并行执行工具调用
    const toolResults = await executeTools(toolUseBlocks, state.toolUseContext)
    for (const result of toolResults) {
      yield result
    }

    // 8. 更新状态，进入下一轮
    state = {
      ...state,
      messages: [...state.messages, assistantMessage, ...toolResults],
      turnCount: state.turnCount + 1
    }
  }
}
```

### 3.2 Agent 定义模型

借鉴 `loadAgentsDir.ts` 的 `AgentDefinition` 类型：

```typescript
// Agent 定义 (借鉴 loadAgentsDir.ts:BaseAgentDefinition)
interface AgentDefinition {
  // 身份标识
  agentType: string           // 唯一类型标识 (如 "Explore", "Plan", "CodeReview")
  whenToUse: string           // 使用场景描述，供父 Agent 选择

  // 能力边界
  tools?: string[]            // 允许使用的工具白名单 (["*"] = 全部)
  disallowedTools?: string[]  // 禁止使用的工具黑名单
  skills?: string[]           // 预加载的技能列表

  // 运行配置
  model?: string              // 使用的模型 ("inherit" = 继承父 Agent)
  maxTurns?: number           // 最大执行轮次
  permissionMode?: PermissionMode  // 权限模式

  // Prompt 构建
  getSystemPrompt: () => string    // 系统提示词生成函数
  omitClaudeMd?: boolean           // 是否省略 CLAUDE.md 上下文

  // 来源标记
  source: 'built-in' | 'user' | 'project' | 'plugin' | 'managed'
}
```

### 3.3 内置 Agent 类型

借鉴 `builtInAgents.ts` 和各 built-in agent 定义：

| Agent 类型 | 职责 | 工具限制 | 模型策略 | 源码参考 |
|-----------|------|---------|---------|---------|
| GeneralPurpose | 通用任务执行 | 全部工具 | inherit | `generalPurposeAgent.ts` |
| Explore | 只读代码搜索 | 禁止 Edit/Write/Agent | haiku (快速) | `exploreAgent.ts` |
| Plan | 方案规划 | 禁止 Edit/Write | inherit | `planAgent.ts` |
| Verification | 结果验证 | 只读 + Bash | inherit | `verificationAgent.ts` |
| CodeGuide | 代码引导 | 只读 | inherit | `claudeCodeGuideAgent.ts` |

### 3.4 多 Agent 编排模式

借鉴 `coordinatorMode.ts` 和 `AgentTool.tsx`：

#### 3.4.1 星型编排（Coordinator Mode）

```
                    ┌──────────────┐
                    │  Coordinator │
                    │  (只编排,     │
                    │   不执行)     │
                    └──────┬───────┘
                           │
              ┌────────────┼────────────┐
              ▼            ▼            ▼
        ┌──────────┐ ┌──────────┐ ┌──────────┐
        │ Worker A │ │ Worker B │ │ Worker C │
        │ (研究)   │ │ (编码)   │ │ (测试)   │
        └──────────┘ └──────────┘ └──────────┘
```

Coordinator 的工具集被严格限制（借鉴 `coordinatorMode.ts:80`）：
- `Agent` — 启动新 Worker
- `SendMessage` — 向已有 Worker 发送后续指令
- `TaskStop` — 中途停止 Worker

Worker 的工具通过 `ASYNC_AGENT_ALLOWED_TOOLS` 过滤，显式排除 `INTERNAL_WORKER_TOOLS`（TeamCreate/TeamDelete/SendMessage/SyntheticOutput），防止不可控递归。

#### 3.4.2 Fork 子进程模式

借鉴 `forkSubagent.ts`，Fork 模式的核心优势是 Prompt Cache 共享：

```
父 Agent 的完整对话历史
    ↓ 共享前缀 (cache hit)
Fork 子进程 A ← 独立指令
Fork 子进程 B ← 独立指令
Fork 子进程 C ← 独立指令
```

关键设计：所有 fork 子进程共享父 Agent 的完整 assistant 消息，用相同的占位符 `tool_result` 填充，只有最后一个 text 块包含各自的指令。

### 3.5 Agent 上下文管理

借鉴 `context.ts` 和 `QueryEngine.ts`：

```typescript
// 上下文分层结构
interface AgentContext {
  // 系统上下文 (不可变，每会话一次)
  systemContext: {
    platform: string        // 操作系统
    gitStatus: string       // Git 状态
    currentDate: string     // 当前日期
  }

  // 用户上下文 (可变，每轮更新)
  userContext: {
    claudeMd: string        // CLAUDE.md 内容 (项目规范)
    memoryFiles: string[]   // 记忆文件
    coordinatorContext?: {}  // Coordinator 模式附加上下文
  }

  // 工具执行上下文 (每次工具调用传递)
  toolUseContext: ToolUseContext  // 见 3.6 节
}
```

### 3.6 ToolUseContext — 工具执行的统一上下文

借鉴 `Tool.ts` 中的 `ToolUseContext` 类型，这是贯穿整个调用链的核心上下文对象：

```typescript
interface ToolUseContext {
  // 状态访问
  getAppState: () => AppState
  setAppState: (f: (prev: AppState) => AppState) => void

  // Agent 标识
  agentId?: AgentId
  queryTracking?: { chainId: string; depth: number }

  // 工具配置
  options: {
    tools: Tools                    // 当前可用工具列表
    mainLoopModel: string           // 主循环模型
    isNonInteractiveSession: boolean
  }

  // 文件状态缓存
  readFileState: FileStateCache

  // 内容替换状态 (大结果持久化)
  contentReplacementState?: ContentReplacementState

  // 通知系统
  addNotification?: (notification: Notification) => void
}
```

---

## 4. Skill 体系设计

### 4.1 Skill 定义模型

借鉴 `bundledSkills.ts` 的 `BundledSkillDefinition`：

```typescript
// Skill 定义 (借鉴 bundledSkills.ts:BundledSkillDefinition)
interface SkillDefinition {
  // 基础信息
  name: string                    // 唯一名称
  description: string             // 描述
  aliases?: string[]              // 别名
  whenToUse?: string              // 使用场景 (供 AI 自动选择)
  argumentHint?: string           // 参数提示

  // 能力约束
  allowedTools?: string[]         // 允许使用的工具子集
  model?: string                  // 指定模型
  disableModelInvocation?: boolean // 禁止模型调用 (纯本地执行)

  // 执行配置
  context?: 'inline' | 'fork'    // 执行模式: 内联 vs 独立子 Agent
  agent?: string                  // 关联的 Agent 类型
  hooks?: HooksSettings           // 技能级别的 Hook 配置

  // 附加资源
  files?: Record<string, string>  // 随技能分发的参考文件

  // 核心执行函数
  getPromptForCommand: (
    args: string,
    context: ToolUseContext
  ) => Promise<ContentBlockParam[]>
}
```

### 4.2 Skill 多源加载体系

借鉴 `loadSkillsDir.ts` 的分层加载机制：

```
Skill 加载优先级 (高 → 低):
┌─────────────────────────────────────────────┐
│ 1. Bundled Skills (内置技能)                  │
│    源码: src/skills/bundled/                  │
│    注册: registerBundledSkill()               │
│    特点: 编译进二进制，所有用户可用             │
├─────────────────────────────────────────────┤
│ 2. Policy Skills (策略管控技能)               │
│    路径: {managedPath}/.claude/skills/        │
│    特点: 企业管理员下发，不可禁用              │
├─────────────────────────────────────────────┤
│ 3. User Skills (用户自定义技能)               │
│    路径: ~/.claude/skills/                    │
│    特点: 用户级别，跨项目共享                  │
├─────────────────────────────────────────────┤
│ 4. Project Skills (项目级技能)                │
│    路径: .claude/skills/                      │
│    特点: 项目级别，团队共享                    │
├─────────────────────────────────────────────┤
│ 5. Plugin Skills (插件提供的技能)             │
│    来源: 插件 manifest 声明                   │
│    特点: 可启用/禁用，版本管理                 │
├─────────────────────────────────────────────┤
│ 6. MCP Skills (MCP 协议提供的技能)            │
│    来源: MCP Server 的 prompts                │
│    特点: 远程动态加载                          │
└─────────────────────────────────────────────┘
```

### 4.3 Skill 文件格式

借鉴 `loadSkillsDir.ts` 的 Frontmatter 解析：

```markdown
---
name: code-review
description: 对代码变更进行深度审查
aliases: [review, cr]
when-to-use: 当用户完成代码编写后自动触发
allowed-tools: [Read, Bash, Grep, Glob]
model: inherit
context: fork
effort: high
hooks:
  pre-tool-use:
    - match: Bash
      prompt: "确保命令是只读的"
---

你是一个代码审查专家。请对以下代码变更进行审查：

1. 检查代码风格是否符合项目规范
2. 检查是否存在潜在的 bug
3. 检查性能问题
4. 给出改进建议

${CLAUDE_SKILL_DIR} 包含审查规则参考文件。
```

### 4.4 Skill 执行流程

借鉴 `SkillTool.ts` 的 `executeForkedSkill()`：

```
用户/AI 触发 Skill
    ↓
SkillTool.call({ skill_name, args })
    ├── getAllCommands() → 查找匹配的 Command
    ├── 判断执行模式:
    │   ├── context: 'inline' → 直接注入 prompt 到当前对话
    │   └── context: 'fork'  → 启动独立子 Agent
    │       ├── createAgentId()
    │       ├── getPromptForCommand(args, context)
    │       │   ├── 参数替换 (${1}, ${CLAUDE_SKILL_DIR})
    │       │   ├── Shell 命令执行 (!`command`)
    │       │   └── 返回 ContentBlockParam[]
    │       ├── prepareForkedCommandContext()
    │       │   ├── 构建初始消息
    │       │   └── 设置工具白名单
    │       └── runAgent()
    │           ├── getAgentSystemPrompt()
    │           ├── assembleToolPool()
    │           ├── query() → 进入 agentic loop
    │           └── 返回执行结果
    └── 返回 ToolResult
```

### 4.5 内置 Skill 清单

借鉴 `src/skills/bundled/` 目录：

| Skill | 功能 | 执行模式 | 源码 |
|-------|------|---------|------|
| verify | 验证代码变更的正确性 | fork | `verify.ts` |
| remember | 将信息持久化到记忆文件 | inline | `remember.ts` |
| debug | 调试问题的系统化方法 | fork | `debug.ts` |
| loop | 循环执行直到条件满足 | fork | `loop.ts` |
| simplify | 简化复杂代码 | fork | `simplify.ts` |
| skillify | 将操作转化为可复用技能 | inline | `skillify.ts` |
| stuck | 当 Agent 陷入困境时的自救 | inline | `stuck.ts` |
| batch | 批量处理多个文件 | fork | `batch.ts` |

---

## 5. Tools 体系设计

### 5.1 Tool 统一接口

借鉴 `Tool.ts` 的 35+ 字段结构化类型：

```typescript
// Tool 统一接口 (借鉴 Tool.ts:362)
interface Tool<Input, Output, Progress> {
  // ===== 核心四要素 =====
  name: string
  description: (input: Input, ctx: DescriptionContext) => Promise<string>
  inputSchema: z.ZodType<Input>
  call: (
    input: Input,
    context: ToolUseContext,
    canUseTool: CanUseToolFn,
    parentMessage: AssistantMessage,
    onProgress?: (progress: Progress) => void
  ) => Promise<ToolResult<Output>>

  // ===== 注册与发现 =====
  aliases?: string[]           // 别名 (向后兼容)
  searchHint?: string          // ToolSearch 关键词
  shouldDefer?: boolean        // 延迟加载
  alwaysLoad?: boolean         // 始终加载
  isEnabled?: () => boolean    // 运行时开关

  // ===== 安全与权限 =====
  validateInput?: (input: Input) => ValidationResult
  checkPermissions?: (input: Input, ctx: ToolUseContext) => PermissionResult
  isReadOnly?: (input: Input) => boolean
  isDestructive?: (input: Input) => boolean

  // ===== 输出控制 =====
  maxResultSizeChars?: number  // 结果字符上限
  mapToolResultToToolResultBlockParam: (result: Output) => ToolResultBlockParam

  // ===== Prompt 注入 =====
  prompt: () => string         // 工具使用说明，注入 System Prompt
}
```

### 5.2 Tool 注册与组装

借鉴 `tools.ts` 的 `getTools()` 和 `getAllBaseTools()`：

```typescript
// 工具注册表 (借鉴 tools.ts:191 getAllBaseTools)
function assembleToolPool(permissionContext: ToolPermissionContext): Tools {
  const tools: Tool[] = []

  // 1. 固定工具 (始终可用)
  tools.push(
    AgentTool,        // 子 Agent 启动
    BashTool,         // Shell 命令执行
    FileReadTool,     // 文件读取
    FileEditTool,     // 文件编辑
    FileWriteTool,    // 文件写入
    WebFetchTool,     // Web 内容获取
    WebSearchTool,    // Web 搜索
    SkillTool,        // 技能调用
    AskUserTool,      // 向用户提问
  )

  // 2. 条件工具 (运行时检查)
  if (!hasEmbeddedSearchTools()) {
    tools.push(GlobTool, GrepTool)
  }
  if (isTaskSystemEnabled()) {
    tools.push(TaskCreateTool, TaskUpdateTool, TaskListTool, TaskGetTool)
  }

  // 3. MCP 工具 (动态加载)
  tools.push(...getMcpTools())

  // 4. 权限过滤
  return filterToolsByDenyRules(tools, permissionContext)
}
```

### 5.3 Tool 分类体系

借鉴 `src/tools/` 目录结构：

```
工具分类:
├── 文件操作 (File Operations)
│   ├── FileReadTool    — 文件读取 (支持行范围、图片处理)
│   ├── FileWriteTool   — 文件创建/覆盖写入
│   ├── FileEditTool    — 文件局部编辑 (old_string → new_string)
│   ├── GlobTool        — 文件模式匹配搜索
│   ├── GrepTool        — 文件内容正则搜索
│   └── NotebookEditTool — Jupyter Notebook 编辑
│
├── 命令执行 (Shell Execution)
│   ├── BashTool        — Bash 命令执行 (含安全校验)
│   └── PowerShellTool  — PowerShell 命令执行 (Windows)
│
├── Agent 协作 (Agent Collaboration)
│   ├── AgentTool       — 启动子 Agent
│   ├── SendMessageTool — 向已有 Agent 发送消息
│   ├── TaskStopTool    — 停止 Agent
│   ├── TeamCreateTool  — 创建 Agent 团队
│   └── TeamDeleteTool  — 删除 Agent 团队
│
├── 任务管理 (Task Management)
│   ├── TaskCreateTool  — 创建任务
│   ├── TaskUpdateTool  — 更新任务状态
│   ├── TaskListTool    — 列出任务
│   ├── TaskGetTool     — 获取任务详情
│   └── TaskOutputTool  — 获取任务输出
│
├── Web 能力 (Web Capabilities)
│   ├── WebFetchTool    — 获取网页内容
│   ├── WebSearchTool   — Web 搜索
│   └── WebBrowserTool  — 浏览器操作
│
├── 规划与控制 (Planning & Control)
│   ├── EnterPlanModeTool  — 进入规划模式
│   ├── ExitPlanModeTool   — 退出规划模式
│   ├── TodoWriteTool      — 待办事项管理
│   └── ToolSearchTool     — 工具搜索 (延迟加载)
│
├── 技能调用 (Skill Invocation)
│   └── SkillTool       — 统一技能调用入口
│
└── 扩展工具 (Extension)
    ├── MCPTool          — MCP 协议工具代理
    ├── ListMcpResourcesTool — 列出 MCP 资源
    └── ReadMcpResourceTool  — 读取 MCP 资源
```

### 5.4 Tool 调用链路详解

借鉴 `docs/tools/what-are-tools.mdx` 的完整链路：

```
Step 1: API 返回 tool_use block
  { "type": "tool_use", "name": "Bash", "input": { "command": "ls -la" } }
    ↓
Step 2: findToolByName("Bash")
  遍历 tools 数组，匹配 name 或 aliases
    ↓
Step 3: validateInput(input)
  Zod schema 校验 + 自定义校验逻辑
  失败 → 返回 { type: "error", error: "Invalid input: ..." }
    ↓
Step 4: canUseTool(tool, input, context, message, toolUseId)
  权限检查链:
  ├── hasPermissionsToUseTool() → 规则匹配
  │   ├── behavior: "allow" → 直接通过
  │   ├── behavior: "deny"  → 直接拒绝
  │   └── behavior: "ask"   → 进入交互流程
  │       ├── handleCoordinatorPermission() (Coordinator 模式)
  │       ├── handleSwarmWorkerPermission() (Swarm 模式)
  │       └── handleInteractivePermission() (交互模式)
  └── 返回 PermissionDecision
    ↓
Step 5: tool.call(input, context, canUseTool, message, onProgress)
  执行实际操作，通过 onProgress 回调实时更新 UI
    ↓
Step 6: mapToolResultToToolResultBlockParam(result)
  将 Output 转为 API 格式的 ToolResultBlockParam
    ↓
Step 7: 结果预算控制
  if (result.length > maxResultSizeChars) {
    持久化到磁盘 → 返回预览 + 文件路径
  }
    ↓
Step 8: 追加到对话历史 → 进入下一轮 Agent Loop
```

### 5.5 Tool 权限模型

借鉴 `Tool.ts` 的 `ToolPermissionContext` 和 `useCanUseTool.tsx`：

```typescript
// 权限模式 (借鉴 types/permissions.ts)
type PermissionMode =
  | 'default'            // 默认: 危险操作需确认
  | 'acceptEdits'        // 自动接受编辑操作
  | 'bypassPermissions'  // 跳过所有权限检查
  | 'auto'               // 分类器自动判断
  | 'bubble'             // 上浮到父 Agent 终端

// 权限上下文 (借鉴 Tool.ts:ToolPermissionContext)
interface ToolPermissionContext {
  mode: PermissionMode
  alwaysAllowRules: ToolPermissionRulesBySource  // 始终允许规则
  alwaysDenyRules: ToolPermissionRulesBySource    // 始终拒绝规则
  alwaysAskRules: ToolPermissionRulesBySource     // 始终询问规则
  shouldAvoidPermissionPrompts?: boolean  // 后台 Agent 自动拒绝
  awaitAutomatedChecksBeforeDialog?: boolean  // 先等自动检查
}

// 权限决策流程
async function resolvePermission(
  tool: Tool, input: any, context: ToolUseContext
): Promise<PermissionDecision> {
  // 1. 规则匹配
  const ruleResult = matchPermissionRules(tool, input, context)
  if (ruleResult.behavior === 'allow') return ruleResult
  if (ruleResult.behavior === 'deny') return ruleResult

  // 2. 分类器检查 (auto 模式)
  if (context.permissionMode === 'auto') {
    const classifierResult = await runClassifier(tool, input)
    if (classifierResult.confidence === 'high') return classifierResult
  }

  // 3. 交互式确认 (ask 模式)
  if (context.shouldAvoidPermissionPrompts) {
    return { behavior: 'deny', reason: 'Background agent cannot prompt' }
  }
  return await promptUser(tool, input)
}
```

### 5.6 Tool 结果预算控制

借鉴 `applyToolResultBudget()` 机制：

```typescript
// 结果预算配置 (借鉴各 Tool 的 maxResultSizeChars)
const RESULT_BUDGETS: Record<string, number> = {
  BashTool:     30_000,    // 命令输出
  SkillTool:    100_000,   // 技能执行结果
  FileReadTool: Infinity,  // 文件内容不限 (避免 Read→file→Read 循环)
  GrepTool:     50_000,    // 搜索结果
  WebFetchTool: 50_000,    // 网页内容
}

// 超出预算的处理
async function applyToolResultBudget(
  messages: Message[],
  replacementState: ContentReplacementState
): Message[] {
  for (const msg of messages) {
    if (msg.toolResult && msg.toolResult.length > budget) {
      // 持久化到磁盘
      const filePath = await persistToDisk(msg.toolResult)
      // 替换为预览 + 路径
      msg.toolResult = truncate(msg.toolResult, budget) +
        `\n[Full output saved to: ${filePath}]`
    }
  }
  return messages
}
```

---

## 6. Agent + Skills + Tools 完整调用逻辑

### 6.1 端到端调用序列图

```
用户                Agent Loop           Skill Router         Tool Executor
 │                     │                     │                     │
 │── "审查这段代码" ──→│                     │                     │
 │                     │                     │                     │
 │                     │── 组装 SystemPrompt ─│                     │
 │                     │── 调用 LLM API ─────│                     │
 │                     │                     │                     │
 │                     │←─ tool_use: SkillTool("code-review") ────│
 │                     │                     │                     │
 │                     │── validateInput() ──│                     │
 │                     │── canUseTool() ─────│                     │
 │                     │                     │                     │
 │                     │── SkillTool.call() ─→│                     │
 │                     │                     │── 查找 Skill 定义    │
 │                     │                     │── 判断 context: fork │
 │                     │                     │                     │
 │                     │                     │── createAgentId() ──│
 │                     │                     │── getPromptForCommand()
 │                     │                     │── assembleToolPool() │
 │                     │                     │                     │
 │                     │                     │── runAgent() ───────→│
 │                     │                     │                     │
 │                     │                     │   ┌─ Sub-Agent Loop ─┐
 │                     │                     │   │ LLM API 调用      │
 │                     │                     │   │ tool_use: Read    │
 │                     │                     │   │ → FileReadTool    │
 │                     │                     │   │ tool_use: Grep    │
 │                     │                     │   │ → GrepTool        │
 │                     │                     │   │ tool_use: Bash    │
 │                     │                     │   │ → BashTool        │
 │                     │                     │   │ 纯文本响应 → 结束  │
 │                     │                     │   └──────────────────┘
 │                     │                     │                     │
 │                     │                     │←─ ToolResult ────────│
 │                     │←─ SkillResult ──────│                     │
 │                     │                     │                     │
 │                     │── 追加到对话历史 ────│                     │
 │                     │── 调用 LLM API ─────│                     │
 │                     │←─ 纯文本响应 ───────│                     │
 │                     │                     │                     │
 │←─ "审查完成，发现3个问题..." ──────────────│                     │
```

### 6.2 子 Agent 启动的完整链路

借鉴 `AgentTool.tsx:239` → `runAgent.ts:248` 的完整路径：

```
AI 生成 tool_use: Agent({ prompt: "修复 bug", subagent_type: "Explore" })
    ↓
AgentTool.call()                              ← 入口
  ├── 解析 effectiveType (fork vs 命名 agent)
  ├── filterDeniedAgents()                    ← 权限过滤
  ├── 检查 requiredMcpServers                 ← MCP 依赖验证 (最长等 30s)
  ├── assembleToolPool(workerPermissionContext) ← 独立组装工具池
  ├── createAgentWorktree()                   ← 可选 worktree 隔离
    ↓
runAgent()                                    ← 核心执行
  ├── getAgentSystemPrompt()                  ← 构建 agent 专属 system prompt
  │   ├── 基础 system prompt
  │   ├── 注入 agent 定义的 getSystemPrompt()
  │   └── 注入 skill 预加载 prompt
  ├── initializeAgentMcpServers()             ← agent 级 MCP 服务器
  ├── executeSubagentStartHooks()             ← Hook 注入
  ├── resolveAgentTools()                     ← 工具过滤
  │   ├── useExactTools ? 直接使用父工具 (Fork)
  │   └── 根据 agent.tools 白名单过滤
  ├── query()                                 ← 进入标准 agentic loop
  │   ├── 消息流逐条 yield
  │   └── recordSidechainTranscript()         ← JSONL 持久化
    ↓
finalizeAgentTool()                           ← 结果汇总
  ├── 提取文本内容 + usage 统计
  └── mapToolResultToToolResultBlockParam()   ← 格式化为 tool_result
```

### 6.3 工具池独立组装机制

借鉴 `AgentTool.tsx:573-577`，子 Agent 的工具池完全独立于父 Agent：

```typescript
// 子 Agent 工具池组装 (借鉴 AgentTool.tsx)
function assembleWorkerToolPool(
  parentAppState: AppState,
  agentDefinition: AgentDefinition
): Tools {
  // 1. 使用 Agent 自身的权限模式 (不继承父 Agent)
  const workerPermissionContext = {
    ...parentAppState.toolPermissionContext,
    mode: agentDefinition.permissionMode ?? 'acceptEdits'
  }

  // 2. 独立组装工具池
  const workerTools = assembleToolPool(
    workerPermissionContext,
    parentAppState.mcp.tools  // MCP 工具继承
  )

  // 3. 根据 Agent 定义过滤
  return resolveAgentTools(agentDefinition, workerTools)
}

// resolveAgentTools 的过滤逻辑 (借鉴 runAgent.ts:500)
function resolveAgentTools(
  agent: AgentDefinition,
  availableTools: Tools
): Tools {
  if (agent.tools?.includes('*')) return availableTools

  const allowSet = new Set(agent.tools ?? [])
  const denySet = new Set(agent.disallowedTools ?? [])

  return availableTools.filter(tool =>
    (allowSet.size === 0 || allowSet.has(tool.name)) &&
    !denySet.has(tool.name)
  )
}
```

### 6.4 Coordinator 通信协议

借鉴 `coordinatorMode.ts` 的 `<task-notification>` 协议：

```xml
<!-- Worker 完成后，Coordinator 收到的通知 -->
<task-notification>
  <task-id>agent-a1b</task-id>
  <status>completed|failed|killed</status>
  <summary>Agent "Investigate auth bug" completed</summary>
  <result>Found null pointer in src/auth/validate.ts:42...</result>
  <usage>
    <total_tokens>15000</total_tokens>
    <tool_uses>8</tool_uses>
    <duration_ms>12500</duration_ms>
  </usage>
</task-notification>
```

Coordinator 的核心职责是综合（Synthesis），System Prompt 明确要求：
- 不能懒惰地委派理解（"based on your findings, fix the bug" 是禁止的）
- 必须在 prompt 中证明自己理解了问题（包含文件路径、行号、具体变更）
- 每个 Worker 的 prompt 必须是完整的任务描述

---

## 7. 容错调用与反思机制

### 7.1 分级错误处理策略

借鉴 `categorizeRetryableAPIError()` 和 `query.ts` 的错误处理：

```
错误分级:
┌─────────────────────────────────────────────────────────┐
│ Level 1: 输入校验错误 (Validation Error)                 │
│ 处理: 返回错误信息给 LLM，让其自行修正                    │
│ 示例: Zod schema 校验失败、文件路径不存在                  │
│ 源码: validateInput() → { result: false, message: "..." }│
├─────────────────────────────────────────────────────────┤
│ Level 2: 权限拒绝 (Permission Denied)                    │
│ 处理: 返回拒绝原因，LLM 可选择替代方案                    │
│ 示例: 用户拒绝执行危险命令                                │
│ 源码: canUseTool() → { behavior: 'deny' }               │
├─────────────────────────────────────────────────────────┤
│ Level 3: 工具执行错误 (Tool Execution Error)              │
│ 处理: 返回错误详情，LLM 可重试或换工具                    │
│ 示例: Bash 命令执行失败、文件编辑冲突                     │
│ 源码: tool.call() throws → catch → error tool_result    │
├─────────────────────────────────────────────────────────┤
│ Level 4: API 可重试错误 (Retryable API Error)            │
│ 处理: 指数退避重试 (最多 3 次)                            │
│ 示例: 429 Rate Limit、500 Server Error、网络超时          │
│ 源码: categorizeRetryableAPIError()                      │
├─────────────────────────────────────────────────────────┤
│ Level 5: 上下文溢出 (Context Overflow)                   │
│ 处理: 自动压缩 (microcompact/autocompact/snip)           │
│ 示例: 对话历史超出 token 限制                             │
│ 源码: applyToolResultBudget() + microcompact()           │
├─────────────────────────────────────────────────────────┤
│ Level 6: 不可恢复错误 (Fatal Error)                      │
│ 处理: 终止 Agent Loop，返回错误给用户                     │
│ 示例: 认证失败、模型不可用                                │
│ 源码: throw → 退出 while(true) 循环                      │
└─────────────────────────────────────────────────────────┘
```

### 7.2 自动重试机制

```typescript
// API 错误分类与重试 (借鉴 services/api/errors.ts)
function categorizeRetryableAPIError(error: APIError): RetryCategory {
  if (error.status === 429) return 'rate_limit'      // 退避重试
  if (error.status === 500) return 'server_error'     // 退避重试
  if (error.status === 529) return 'overloaded'       // 长退避重试
  if (error.code === 'ECONNRESET') return 'network'   // 立即重试
  return 'non_retryable'                              // 不重试
}

// 重试策略
async function retryWithBackoff<T>(
  fn: () => Promise<T>,
  maxRetries: number = 3
): Promise<T> {
  for (let attempt = 0; attempt <= maxRetries; attempt++) {
    try {
      return await fn()
    } catch (error) {
      const category = categorizeRetryableAPIError(error)
      if (category === 'non_retryable' || attempt === maxRetries) throw error

      const delay = calculateBackoff(attempt, category)
      await sleep(delay)
    }
  }
  throw new Error('Unreachable')
}

function calculateBackoff(attempt: number, category: RetryCategory): number {
  const base = category === 'overloaded' ? 10000 : 1000
  return base * Math.pow(2, attempt) + Math.random() * 1000
}
```

### 7.3 上下文压缩与管理

借鉴 `query.ts` 的多层压缩机制：

```
上下文管理策略 (按执行顺序):

1. Tool Result Budget (工具结果预算)
   ├── 每条消息的工具结果不超过 maxResultSizeChars
   ├── 超出部分持久化到磁盘
   └── 源码: applyToolResultBudget()

2. History Snip (历史裁剪)
   ├── 当对话历史过长时，裁剪早期消息
   ├── 保留最近的 N 轮对话
   └── 源码: snipCompactIfNeeded()

3. Microcompact (微压缩)
   ├── 压缩工具调用的中间结果
   ├── 保留关键信息，移除冗余
   └── 源码: microcompact()

4. Context Collapse (上下文折叠)
   ├── 将多轮工具调用折叠为摘要
   ├── 保留语义，减少 token 消耗
   └── 源码: applyCollapsesIfNeeded()

5. Autocompact (自动压缩)
   ├── 当 token 使用接近限制时触发
   ├── 对整个对话历史进行摘要压缩
   └── 源码: autocompact tracking in queryLoop
```

### 7.4 反思机制设计

```typescript
// 反思触发条件
interface ReflectionTrigger {
  // 1. 工具执行失败后的自我纠错
  toolExecutionFailed: {
    maxRetries: 3
    strategy: 'retry_with_different_params' | 'switch_tool' | 'ask_user'
  }

  // 2. 验证 Agent 的结果校验
  verificationFailed: {
    trigger: 'post_implementation'
    agent: 'Verification'
    action: 'revert_and_retry' | 'fix_issues' | 'escalate'
  }

  // 3. 陷入循环检测
  stuckDetection: {
    sameToolCallThreshold: 3    // 连续 3 次相同工具调用
    noProgressThreshold: 5      // 5 轮无实质进展
    action: 'invoke_stuck_skill' | 'change_approach' | 'ask_user'
  }

  // 4. Token 预算耗尽
  budgetExhausted: {
    action: 'compact_and_continue' | 'summarize_and_stop'
  }
}

// 反思执行流程
async function executeWithReflection(
  agentLoop: AgentLoop,
  trigger: ReflectionTrigger
): Promise<void> {
  // 检测是否需要反思
  if (detectStuckPattern(agentLoop.state)) {
    // 注入反思 prompt
    agentLoop.injectMessage({
      role: 'user',
      content: `[System] 检测到你可能陷入了循环。请：
        1. 回顾你最近的 ${agentLoop.state.turnCount} 轮操作
        2. 分析为什么没有取得进展
        3. 提出一个不同的方法
        4. 如果确实无法解决，请使用 AskUserQuestion 工具寻求帮助`
    })
  }

  // 验证阶段反思
  if (agentLoop.state.phase === 'post_implementation') {
    const verifyResult = await runVerificationAgent(agentLoop.state)
    if (!verifyResult.passed) {
      agentLoop.injectMessage({
        role: 'user',
        content: `[Verification] 验证失败：${verifyResult.issues.join(', ')}
          请修复这些问题后重新验证。`
      })
    }
  }
}
```

### 7.5 权限拒绝追踪与降级

借鉴 `useCanUseTool.tsx` 的拒绝追踪机制：

```typescript
// 拒绝追踪 (借鉴 utils/permissions/denialTracking.ts)
interface DenialTrackingState {
  denials: Array<{
    toolName: string
    display: string
    reason: string
    timestamp: number
  }>
  consecutiveDenials: number
}

// 降级策略
function handleDenialEscalation(state: DenialTrackingState): Action {
  if (state.consecutiveDenials >= 3) {
    // 连续 3 次拒绝 → 切换到 ask 模式
    return { action: 'switch_to_ask_mode' }
  }
  if (state.consecutiveDenials >= 5) {
    // 连续 5 次拒绝 → 停止并通知用户
    return { action: 'stop_and_notify_user' }
  }
  return { action: 'continue' }
}
```

### 7.6 Fork 递归防护

借鉴 `AgentTool.tsx:332` 的双重防线：

```typescript
// Fork 递归防护 (借鉴 AgentTool.tsx)
function preventForkRecursion(context: ToolUseContext): boolean {
  // 防线 1: querySource 检查
  if (context.options.querySource === 'agent:builtin:fork') {
    return true // 已经是 fork，禁止再次 fork
  }

  // 防线 2: 消息扫描 (降级兜底)
  const hasForkBoilerplate = context.messages.some(msg =>
    msg.content?.includes('<fork-boilerplate>')
  )
  return hasForkBoilerplate
}
```

---

## 8. 状态管理设计

### 8.1 AppState 结构

借鉴 `AppStateStore.ts` 的状态设计：

```typescript
interface AppState {
  // Agent 状态
  messages: Message[]
  isLoading: boolean
  mainLoopModel: string

  // 工具权限
  toolPermissionContext: ToolPermissionContext

  // MCP 状态
  mcp: {
    tools: Tool[]
    commands: Command[]
    clients: MCPServerConnection[]
  }

  // 任务状态
  tasks: Map<string, TaskState>

  // 文件历史
  fileHistory: FileHistoryState

  // 性能追踪
  usage: {
    totalTokens: number
    totalCost: number
    apiDuration: number
  }
}
```

### 8.2 状态更新模式

借鉴 `AppState.tsx` 的 `useSyncExternalStore` 模式：

```typescript
// 外部存储 + 不可变更新 (借鉴 state/store.ts)
function createStore(initialState: AppState): AppStateStore {
  let state = initialState
  const listeners = new Set<() => void>()

  return {
    getState: () => state,
    setState: (updater: (prev: AppState) => AppState) => {
      const newState = updater(state)
      if (newState !== state) {
        state = newState
        listeners.forEach(l => l())
      }
    },
    subscribe: (listener: () => void) => {
      listeners.add(listener)
      return () => listeners.delete(listener)
    }
  }
}
```

---

## 9. 关键设计模式总结

| 模式 | 源码位置 | 本方案应用 |
|------|---------|-----------|
| 异步生成器驱动循环 | `query.ts:queryLoop()` | Agent Loop Engine |
| 结构化类型工具接口 | `Tool.ts:Tool<I,O,P>` | 统一 Tool 接口 |
| 工厂函数构建工具 | `Tool.ts:buildTool()` | Tool 注册 |
| 延迟 Schema 解析 | `lazySchema()` | 避免循环依赖 |
| 多源分层加载 | `loadSkillsDir.ts` | Skill 加载体系 |
| 独立工具池组装 | `AgentTool.tsx:assembleToolPool()` | 子 Agent 隔离 |
| Prompt Cache 共享 | `forkSubagent.ts` | Fork 模式优化 |
| 不可变状态 + 订阅 | `AppStateStore.ts` | 状态管理 |
| 结果预算控制 | `applyToolResultBudget()` | 上下文管理 |
| 分级错误处理 | `categorizeRetryableAPIError()` | 容错机制 |
| 权限拒绝追踪 | `denialTracking.ts` | 降级策略 |
| Feature Flag 门控 | `feature()` + `isEnvTruthy()` | 渐进式发布 |
| XML 通信协议 | `<task-notification>` | Coordinator 通信 |
| Memoize 缓存 | `memoize()` on getCommands/getSkills | 性能优化 |

---

## 10. 与 aPaaS 平台的集成点

### 10.1 元数据驱动的 Agent 配置

将 Agent/Skill/Tool 的定义存储为平台元数据：

```
元数据实体关系:
Agent 定义 (md_agent)
  ├── 1:N → Skill 绑定 (md_agent_skill)
  ├── 1:N → Tool 白名单 (md_agent_tool)
  ├── 1:1 → System Prompt 模板 (md_agent_prompt)
  └── 1:N → Hook 配置 (md_agent_hook)

Skill 定义 (md_skill)
  ├── 1:N → Tool 依赖 (md_skill_tool)
  ├── 1:1 → Prompt 模板 (md_skill_prompt)
  └── 1:N → 参考文件 (md_skill_file)

Tool 定义 (md_tool)
  ├── 1:1 → Input Schema (md_tool_input)
  ├── 1:1 → Permission Rule (md_tool_permission)
  └── 1:1 → Result Budget (md_tool_budget)
```

### 10.2 运行时集成

```
aPaaS 平台
    ↓ 加载 Agent 定义
Agent Runtime
    ├── 从元数据加载 AgentDefinition
    ├── 从元数据加载 SkillDefinition[]
    ├── 从元数据加载 ToolDefinition[]
    ├── assembleToolPool() → 组装工具池
    ├── loadSkills() → 加载技能
    └── agentLoop() → 启动 Agent 循环
```

---

## 附录 A: 源码文件索引

| 文件 | 核心职责 |
|------|---------|
| `src/query.ts` | Agent 循环引擎 (queryLoop) |
| `src/QueryEngine.ts` | 查询引擎 (submitMessage, 状态管理) |
| `src/Tool.ts` | Tool 类型定义 (35+ 字段接口) |
| `src/tools.ts` | Tool 注册表 (getTools, assembleToolPool) |
| `src/tools/AgentTool/AgentTool.tsx` | 子 Agent 启动入口 |
| `src/tools/AgentTool/runAgent.ts` | 子 Agent 执行核心 |
| `src/tools/AgentTool/builtInAgents.ts` | 内置 Agent 定义 |
| `src/tools/AgentTool/loadAgentsDir.ts` | Agent 定义加载 |
| `src/tools/AgentTool/forkSubagent.ts` | Fork 子进程模式 |
| `src/tools/AgentTool/prompt.ts` | Agent 工具 Prompt |
| `src/tools/SkillTool/SkillTool.ts` | 技能调用工具 |
| `src/skills/bundledSkills.ts` | 内置技能注册 |
| `src/skills/loadSkillsDir.ts` | 技能目录加载 |
| `src/coordinator/coordinatorMode.ts` | Coordinator 模式 |
| `src/hooks/useCanUseTool.tsx` | 权限检查 Hook |
| `src/state/AppStateStore.ts` | 应用状态存储 |
| `src/context.ts` | 上下文管理 |

---

## 11. 上下文管理详细设计

上下文管理是 Agent 系统中最复杂、最关键的子系统。它决定了 Agent 在每一轮对话中"看到什么"、"记住什么"、"忘记什么"。基于对 my-claude-code 源码的深度分析，上下文管理涉及 **五个层次**、**三个生命周期阶段**、**六种压缩策略**。

### 11.1 上下文管理总体架构

```
┌─────────────────────────────────────────────────────────────────┐
│                    上下文管理总体架构                              │
│                                                                  │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │ Layer 1: 静态上下文 (会话级，一次加载)                      │   │
│  │  ├── System Prompt (系统提示词)                            │   │
│  │  ├── System Context (Git 状态、平台信息)                   │   │
│  │  ├── User Context (CLAUDE.md、记忆文件、日期)              │   │
│  │  └── Coordinator Context (Worker 工具列表、MCP 服务器)     │   │
│  └──────────────────────────────────────────────────────────┘   │
│                           ↓ 每轮注入                             │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │ Layer 2: 动态附件 (轮次级，每轮计算)                       │   │
│  │  ├── @文件引用附件                                         │   │
│  │  ├── MCP 资源附件                                          │   │
│  │  ├── 技能列表附件 (skill_listing_delta)                    │   │
│  │  ├── Agent 列表附件 (agent_listing_delta)                  │   │
│  │  ├── 计划模式附件 (plan_mode_instructions)                 │   │
│  │  ├── 条件记忆附件 (nested_memory)                          │   │
│  │  ├── 任务提醒附件 (todo_reminder)                          │   │
│  │  ├── Token 用量附件                                        │   │
│  │  └── 诊断信息附件 (LSP diagnostics)                        │   │
│  └──────────────────────────────────────────────────────────┘   │
│                           ↓ 每轮注入                             │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │ Layer 3: 对话历史 (累积，持续增长)                          │   │
│  │  ├── User Messages (用户消息)                              │   │
│  │  ├── Assistant Messages (助手消息 + tool_use blocks)       │   │
│  │  ├── Tool Results (工具执行结果)                            │   │
│  │  └── Attachment Messages (附件消息)                         │   │
│  └──────────────────────────────────────────────────────────┘   │
│                           ↓ 按需触发                             │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │ Layer 4: 上下文压缩 (防溢出，多策略协同)                    │   │
│  │  ├── Tool Result Budget (工具结果预算控制)                  │   │
│  │  ├── History Snip (历史裁剪)                               │   │
│  │  ├── Microcompact (微压缩 / Cache Editing)                 │   │
│  │  ├── Context Collapse (上下文折叠)                          │   │
│  │  ├── Autocompact (自动全量压缩)                             │   │
│  │  └── Reactive Compact (响应式压缩)                          │   │
│  └──────────────────────────────────────────────────────────┘   │
│                           ↓ 压缩后恢复                           │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │ Layer 5: 压缩后上下文恢复                                   │   │
│  │  ├── 文件状态恢复 (最近读取的文件重新附加)                   │   │
│  │  ├── 异步 Agent 状态恢复                                    │   │
│  │  ├── 计划模式恢复                                           │   │
│  │  ├── 技能状态恢复                                           │   │
│  │  ├── 工具列表重新公告 (deferred_tools_delta)                │   │
│  │  └── MCP 指令重新公告                                       │   │
│  └──────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
```

### 11.2 静态上下文：会话级一次加载

#### 11.2.1 System Prompt 组装

借鉴 `queryContext.ts:fetchSystemPromptParts()` 和 `QueryEngine.ts:submitMessage()`：

```typescript
// System Prompt 组装流程 (借鉴 queryContext.ts)
async function fetchSystemPromptParts({
  tools,              // 当前可用工具列表
  mainLoopModel,      // 主循环模型
  additionalWorkingDirectories,  // 额外工作目录
  mcpClients,         // MCP 客户端列表
  customSystemPrompt, // 自定义系统提示词 (SDK 场景)
}): Promise<{
  defaultSystemPrompt: string[]   // 默认系统提示词片段数组
  userContext: Record<string, string>
  systemContext: Record<string, string>
}> {
  // 三路并行加载，最大化启动速度
  const [defaultSystemPrompt, userContext, systemContext] = await Promise.all([
    customSystemPrompt !== undefined
      ? Promise.resolve([])                    // SDK 自定义 → 跳过默认
      : getSystemPrompt(tools, mainLoopModel, additionalWorkingDirectories, mcpClients),
    getUserContext(),                           // CLAUDE.md + 日期
    customSystemPrompt !== undefined
      ? Promise.resolve({})                    // SDK 自定义 → 跳过系统上下文
      : getSystemContext(),                    // Git 状态
  ])
  return { defaultSystemPrompt, userContext, systemContext }
}

// 最终 System Prompt 组装 (借鉴 QueryEngine.ts:submitMessage)
const systemPrompt = asSystemPrompt([
  ...(customPrompt !== undefined ? [customPrompt] : defaultSystemPrompt),
  ...(memoryMechanicsPrompt ? [memoryMechanicsPrompt] : []),
  ...(appendSystemPrompt ? [appendSystemPrompt] : []),
])
```

关键设计点：
- `getSystemPrompt()` 包含工具描述、使用规则、安全约束等，是最大的 prompt 片段
- `asSystemPrompt()` 将多个片段拼接为最终的 system prompt 数组
- SDK 场景下 `customSystemPrompt` 完全替换默认 prompt，`appendSystemPrompt` 追加

#### 11.2.2 System Context — Git 状态快照

借鉴 `context.ts:getSystemContext()` 和 `getGitStatus()`：

```typescript
// System Context 加载 (借鉴 context.ts)
// 使用 memoize 确保每会话只加载一次
const getSystemContext = memoize(async (): Promise<Record<string, string>> => {
  // 远程模式或禁用 Git 指令时跳过
  const gitStatus = isRemoteMode() || !shouldIncludeGitInstructions()
    ? null
    : await getGitStatus()

  return {
    ...(gitStatus && { gitStatus }),
    // 可选的 cache breaker 注入 (调试用)
    ...(injection ? { cacheBreaker: `[CACHE_BREAKER: ${injection}]` } : {}),
  }
})

// Git 状态快照 (借鉴 context.ts:getGitStatus)
const getGitStatus = memoize(async (): Promise<string | null> => {
  // 五路并行获取 Git 信息
  const [branch, mainBranch, status, log, userName] = await Promise.all([
    getBranch(),
    getDefaultBranch(),
    execFileNoThrow(gitExe(), ['status', '--short']),
    execFileNoThrow(gitExe(), ['log', '--oneline', '-n', '5']),
    execFileNoThrow(gitExe(), ['config', 'user.name']),
  ])

  // 状态超过 2000 字符时截断
  const truncatedStatus = status.length > MAX_STATUS_CHARS
    ? status.substring(0, MAX_STATUS_CHARS) + '\n... (truncated)'
    : status

  return [
    'This is the git status at the start of the conversation.',
    `Current branch: ${branch}`,
    `Main branch: ${mainBranch}`,
    ...(userName ? [`Git user: ${userName}`] : []),
    `Status:\n${truncatedStatus || '(clean)'}`,
    `Recent commits:\n${log}`,
  ].join('\n\n')
})
```

关键设计点：
- `memoize` 确保 Git 状态只在会话开始时获取一次（快照语义）
- 明确告知模型"这是会话开始时的快照，不会在对话中更新"
- 状态超过 2000 字符时截断，避免占用过多上下文空间
- 五路并行获取 Git 信息，最大化加载速度

#### 11.2.3 User Context — CLAUDE.md 记忆文件体系

借鉴 `context.ts:getUserContext()` 和 `utils/claudemd.ts`：

```typescript
// User Context 加载 (借鉴 context.ts)
const getUserContext = memoize(async (): Promise<Record<string, string>> => {
  const shouldDisableClaudeMd =
    isEnvTruthy(process.env.CLAUDE_CODE_DISABLE_CLAUDE_MDS) ||
    (isBareMode() && getAdditionalDirectoriesForClaudeMd().length === 0)

  const claudeMd = shouldDisableClaudeMd
    ? null
    : getClaudeMds(filterInjectedMemoryFiles(await getMemoryFiles()))

  // 缓存供 auto-mode 分类器使用 (避免循环依赖)
  setCachedClaudeMdContent(claudeMd || null)

  return {
    ...(claudeMd && { claudeMd }),
    currentDate: `Today's date is ${getLocalISODate()}.`,
  }
})
```

CLAUDE.md 记忆文件的加载顺序（借鉴 `claudemd.ts` 文件头注释）：

```
记忆文件加载优先级 (低 → 高，后加载的优先级更高):

1. Managed Memory (管理员下发)
   路径: /etc/claude-code/CLAUDE.md
   特点: 全局指令，所有用户生效，不可禁用

2. User Memory (用户级)
   路径: ~/.claude/CLAUDE.md
   特点: 私有全局指令，跨项目共享

3. Project Memory (项目级)
   路径: CLAUDE.md, .claude/CLAUDE.md, .claude/rules/*.md
   发现: 从当前目录向上遍历到根目录
   特点: 检入代码库，团队共享
   优先级: 越靠近当前目录优先级越高

4. Local Memory (本地私有)
   路径: CLAUDE.local.md
   特点: 项目级私有指令，不检入代码库
```

记忆文件的 `@include` 指令支持：

```markdown
<!-- 在 CLAUDE.md 中引用其他文件 -->
@./docs/coding-standards.md
@~/global-rules.md
@/absolute/path/to/rules.md

<!-- 支持的文件类型: .md, .txt, .json, .yaml, .ts, .py 等 100+ 种文本格式 -->
<!-- 循环引用自动检测和防护 -->
<!-- 不存在的文件静默忽略 -->
```

#### 11.2.4 Coordinator Context — 多 Agent 编排上下文

借鉴 `coordinatorMode.ts:getCoordinatorUserContext()`：

```typescript
// Coordinator 模式附加上下文 (借鉴 coordinatorMode.ts:80)
function getCoordinatorUserContext(
  mcpClients: ReadonlyArray<{ name: string }>,
  scratchpadDir?: string,
): Record<string, string> {
  if (!isCoordinatorMode()) return {}

  // 动态生成 Worker 可用工具列表
  const workerTools = isSimpleMode()
    ? [BASH_TOOL_NAME, FILE_READ_TOOL_NAME, FILE_EDIT_TOOL_NAME].sort().join(', ')
    : Array.from(ASYNC_AGENT_ALLOWED_TOOLS)
        .filter(name => !INTERNAL_WORKER_TOOLS.has(name))
        .sort()
        .join(', ')

  let content = `Workers spawned via Agent tool have access to: ${workerTools}`

  // 注入 MCP 服务器列表
  if (mcpClients.length > 0) {
    content += `\nMCP servers: ${mcpClients.map(c => c.name).join(', ')}`
  }

  // 注入 Scratchpad 目录 (跨 Worker 共享知识库)
  if (scratchpadDir) {
    content += `\nScratchpad directory: ${scratchpadDir}`
  }

  return { coordinatorContext: content }
}
```

### 11.3 动态附件：轮次级上下文注入

#### 11.3.1 附件系统总览

借鉴 `utils/attachments.ts:getAttachments()` — 这是一个 3000+ 行的核心文件，管理所有动态上下文注入：

```typescript
// 附件获取主函数 (借鉴 attachments.ts:743)
async function getAttachments(
  input: string | null,          // 用户输入文本
  toolUseContext: ToolUseContext, // 工具执行上下文
  ideSelection: IDESelection,    // IDE 选中内容
  queuedCommands: QueuedCommand[], // 排队命令
  messages?: Message[],          // 对话历史
  querySource?: QuerySource,     // 查询来源
): Promise<Attachment[]> {
  const attachments: Attachment[] = []

  // ===== 用户输入驱动的附件 =====
  if (input) {
    // @文件引用: 解析 @path 语法，读取文件内容
    attachments.push(...await processAtMentionedFiles(input, context))
    // MCP 资源引用: 解析 @mcp://resource 语法
    attachments.push(...await processMcpResourceAttachments(input, context))
    // Agent 引用: 解析 @agent-name 语法
    attachments.push(...processAgentMentions(input, agents))
    // 技能发现: 基于用户输入搜索相关技能
    attachments.push(...await getSkillDiscoveryAttachments(input, messages))
  }

  // ===== 轮次驱动的附件 (每轮自动注入) =====
  // 技能列表 (增量更新，避免 cache bust)
  attachments.push(...await getSkillListingAttachments(messages))
  // Agent 列表 (增量更新)
  attachments.push(...getAgentListingDeltaAttachment(context, messages))
  // 工具列表 (延迟加载的工具增量公告)
  attachments.push(...getDeferredToolsDeltaAttachment(tools, model, messages))
  // MCP 指令 (MCP 服务器使用说明)
  attachments.push(...getMcpInstructionsDeltaAttachment(mcpClients, tools))

  // ===== 状态驱动的附件 =====
  // 计划模式指令 (进入 plan mode 后每轮注入)
  attachments.push(...await getPlanModeAttachments(messages))
  // 任务提醒 (定期提醒未完成的 TODO)
  attachments.push(...await getTodoReminderAttachments(messages))
  // Token 用量提醒 (接近限制时警告)
  attachments.push(...getTokenUsageAttachment(messages))
  // 压缩提醒 (建议用户执行 /compact)
  attachments.push(...getCompactionReminderAttachment(messages))

  // ===== 条件记忆附件 =====
  // 嵌套记忆: 当读取的文件匹配 CLAUDE.md 的 globs 模式时触发
  attachments.push(...await getNestedMemoryAttachments(context))
  // 相关记忆: 基于语义相关性的记忆文件预取
  attachments.push(...await getRelevantMemoryAttachments(messages))

  // ===== IDE 集成附件 =====
  // IDE 选中内容
  attachments.push(...await getSelectedLinesFromIDE(ideSelection))
  // IDE 打开的文件
  attachments.push(...await getOpenedFileFromIDE(context))
  // LSP 诊断信息
  attachments.push(...await getDiagnosticAttachments(context))

  // ===== 排队命令附件 =====
  attachments.push(...getQueuedCommandAttachments(queuedCommands))

  // 去重: 避免同一记忆文件被多次注入
  return filterDuplicateMemoryAttachments(attachments)
}
```

#### 11.3.2 增量附件机制 (Delta Attachments)

借鉴 `attachments.ts` 的 `getDeferredToolsDeltaAttachment()` 和 `getAgentListingDeltaAttachment()`：

```
增量附件的核心思想:
  不是每轮都发送完整的工具/Agent/技能列表，
  而是只发送与上一轮相比的"增量变化"。

为什么这样设计？
  工具列表 (~10KB) 嵌入在 tool schema 中，每次变化都会导致
  整个 tool schema 的 prompt cache 失效 (cache bust)。
  将动态列表移到 attachment message 中，tool schema 保持不变，
  cache 命中率从 ~90% 提升到 ~98%。

实现方式:
  1. 首次: 发送完整列表 (full announcement)
  2. 后续: 对比上一轮的列表，只发送新增/移除的条目
  3. 压缩后: 重新发送完整列表 (因为压缩清除了历史)
```

#### 11.3.3 条件记忆附件 (Nested Memory)

借鉴 `attachments.ts:getNestedMemoryAttachmentsForFile()` 和 `claudemd.ts` 的 globs 机制：

```
条件记忆触发流程:

1. CLAUDE.md 中定义 globs 模式:
   ---
   globs: ["src/auth/**/*.ts", "src/security/**"]
   ---
   当处理认证相关文件时，请遵循以下安全规范...

2. Agent 读取文件 src/auth/login.ts 时:
   FileReadTool.call() → 记录文件路径到 readFileState

3. 下一轮 getAttachments() 时:
   检查 readFileState 中的新文件路径
   → 匹配 CLAUDE.md 的 globs 模式
   → 命中 → 注入对应的记忆文件内容作为附件

4. 去重: loadedNestedMemoryPaths 追踪已加载的路径，避免重复注入
```

#### 11.3.4 相关记忆预取 (Relevant Memory Prefetch)

借鉴 `attachments.ts:startRelevantMemoryPrefetch()`：

```typescript
// 相关记忆预取 (借鉴 attachments.ts:2362)
// 使用 Disposable 模式，在 query loop 的 using 语句中自动清理
function startRelevantMemoryPrefetch(
  messages: Message[],
  toolUseContext: ToolUseContext,
): Disposable & { settledAt: Promise<void> } {
  // 在 API 调用期间并行执行语义搜索
  // 搜索与当前对话相关的记忆文件
  // 结果在 API 响应后消费，不阻塞主流程
}
```

### 11.4 上下文压缩：六策略协同防溢出

#### 11.4.1 压缩策略执行顺序

借鉴 `query.ts:queryLoop()` 中的压缩管线：

```
每轮 API 调用前的上下文处理管线:

messagesForQuery = getMessagesAfterCompactBoundary(messages)
        │
        ▼
Step 1: Tool Result Budget (工具结果预算)
        │ applyToolResultBudget()
        │ 将超出 maxResultSizeChars 的工具结果替换为预览+文件路径
        │ 在 microcompact 之前执行，因为 MC 按 tool_use_id 操作
        ▼
Step 2: History Snip (历史裁剪) [feature('HISTORY_SNIP')]
        │ snipCompactIfNeeded()
        │ 裁剪最早的对话轮次，释放 token 空间
        │ 返回 tokensFreed 供后续阈值计算使用
        ▼
Step 3: Microcompact (微压缩)
        │ microcompact()
        │ 清除旧的工具调用输入/结果，保留最近的 N 个
        │ 两种实现: API-based (clear_tool_uses) vs Cached (cache editing)
        ▼
Step 4: Context Collapse (上下文折叠) [feature('CONTEXT_COLLAPSE')]
        │ applyCollapsesIfNeeded()
        │ 将多轮工具调用折叠为摘要
        │ 在 autocompact 之前执行，可能使 autocompact 不必触发
        ▼
Step 5: Autocompact (自动全量压缩)
        │ autocompact()
        │ 当 token 使用接近限制时，调用 LLM 生成对话摘要
        │ 替换整个对话历史为摘要 + 恢复附件
        ▼
Step 6: Reactive Compact (响应式压缩) [feature('REACTIVE_COMPACT')]
        │ 当 API 返回 prompt_too_long 错误时触发
        │ 作为 autocompact 的兜底机制
        ▼
最终: messagesForQuery → 发送给 LLM API
```

#### 11.4.2 Tool Result Budget — 工具结果预算控制

借鉴 `utils/toolResultStorage.ts`：

```typescript
// 工具结果预算控制 (借鉴 toolResultStorage.ts)

// 每个工具的结果字符上限
const TOOL_RESULT_BUDGETS = {
  BashTool:         30_000,    // 命令输出
  SkillTool:        100_000,   // 技能执行结果
  FileReadTool:     Infinity,  // 文件内容不限 (避免 Read→file→Read 循环)
  GrepTool:         50_000,    // 搜索结果
  WebFetchTool:     50_000,    // 网页内容
  WebSearchTool:    30_000,    // 搜索结果
  DEFAULT:          50_000,    // 默认上限
}

// 每条消息的总结果预算
const MAX_TOOL_RESULTS_PER_MESSAGE_CHARS = 800_000

// 超出预算的处理流程
async function applyToolResultBudget(
  messages: Message[],
  contentReplacementState?: ContentReplacementState,
  persistCallback?: (records: ReplacementRecord[]) => void,
  unlimitedTools?: Set<string>,  // 不受预算限制的工具 (如 FileRead)
): Promise<Message[]> {
  for (const message of messages) {
    // 1. 收集候选: 找出所有工具结果块
    const candidates = collectCandidatesFromMessage(message)

    // 2. 分区: 已替换的 vs 新的
    const { alreadyReplaced, fresh } = partitionByPriorDecision(
      candidates, contentReplacementState
    )

    // 3. 选择替换目标: 从最旧的开始，直到总量低于预算
    const toReplace = selectFreshToReplace(fresh, budgetLimit)

    // 4. 执行替换:
    for (const candidate of toReplace) {
      if (candidate.size > persistenceThreshold) {
        // 大结果 → 持久化到磁盘
        const filePath = await persistToDisk(candidate.content)
        candidate.content = generatePreview(candidate.content, 500) +
          `\n<persisted-output>${filePath}</persisted-output>`
      } else {
        // 小结果 → 直接清除
        candidate.content = '[Old tool result content cleared]'
      }
    }

    // 5. 记录替换状态 (用于会话恢复时重建)
    if (persistCallback) {
      persistCallback(toReplace.map(c => c.toRecord()))
    }
  }
  return messages
}
```

关键设计点：
- `FileReadTool` 设为 `Infinity` 是刻意的：如果持久化文件内容到磁盘，模型会用 Read 工具再次读取，形成循环
- `contentReplacementState` 追踪已替换的结果，确保会话恢复时能重建相同的替换
- 替换从最旧的结果开始，保留最近的结果（时间局部性原则）

#### 11.4.3 Microcompact — 微压缩

借鉴 `services/compact/apiMicrocompact.ts`：

```typescript
// API-based Microcompact (借鉴 apiMicrocompact.ts)
// 利用 API 原生的 context_management 能力

// 可清除结果的工具 (搜索/读取类)
const TOOLS_CLEARABLE_RESULTS = [
  'Bash', 'Glob', 'Grep', 'Read', 'WebFetch', 'WebSearch'
]

// 可清除调用的工具 (写入类，只清除输入不清除结果)
const TOOLS_CLEARABLE_USES = [
  'FileEdit', 'FileWrite', 'NotebookEdit'
]

function getAPIContextManagement(options?: {
  hasThinking?: boolean
  clearAllThinking?: boolean
}): ContextManagementConfig | undefined {
  const strategies: ContextEditStrategy[] = []

  // 策略 1: Thinking 块管理
  // 保留最近的 thinking 块，清除旧的 (节省大量 token)
  if (hasThinking && !isRedactThinkingActive) {
    strategies.push({
      type: 'clear_thinking_20251015',
      keep: clearAllThinking
        ? { type: 'thinking_turns', value: 1 }  // 只保留最后 1 轮
        : 'all',                                  // 保留全部
    })
  }

  // 策略 2: 工具结果清除
  // 当 input_tokens 超过 180K 时触发
  // 保留最近 40K tokens 的工具结果
  strategies.push({
    type: 'clear_tool_uses_20250919',
    trigger: { type: 'input_tokens', value: 180_000 },
    clear_at_least: { type: 'input_tokens', value: 140_000 },
    clear_tool_inputs: TOOLS_CLEARABLE_RESULTS,
  })

  return { edits: strategies }
}
```

两种 Microcompact 实现对比：

| 维度 | API Microcompact | Cached Microcompact |
|------|-----------------|-------------------|
| 实现位置 | API 服务端 | 客户端本地 |
| 触发条件 | input_tokens 超阈值 | tool_use 数量超阈值 |
| 操作方式 | `clear_tool_uses` API 参数 | 本地编辑 cache_edits |
| 优势 | 无需本地计算 | 精确控制，支持 cache editing |
| 适用场景 | 通用 | 需要 prompt cache 优化 |

#### 11.4.4 Autocompact — 自动全量压缩

借鉴 `services/compact/compact.ts:compactConversation()`：

```typescript
// Autocompact 完整流程 (借鉴 compact.ts:389)
async function compactConversation(
  messages: Message[],
  context: ToolUseContext,
  cacheSafeParams: CacheSafeParams,
  suppressFollowUpQuestions: boolean,
  customInstructions?: string,
  isAutoCompact: boolean = false,
): Promise<CompactionResult> {

  // 1. 执行 PreCompact Hooks
  const hookResult = await executePreCompactHooks({
    trigger: isAutoCompact ? 'auto' : 'manual',
    customInstructions,
  })

  // 2. 构建压缩请求
  const compactPrompt = getCompactPrompt(customInstructions)
  const summaryRequest = createUserMessage({ content: compactPrompt })

  // 3. 调用 LLM 生成摘要 (支持 prompt-too-long 重试)
  let messagesToSummarize = messages
  for (;;) {
    const summaryResponse = await streamCompactSummary({
      messages: messagesToSummarize,
      summaryRequest,
      appState,
      context,
    })
    const summary = getAssistantMessageText(summaryResponse)

    if (!summary?.startsWith(PROMPT_TOO_LONG_ERROR_MESSAGE)) break

    // prompt-too-long → 截断最旧的消息组，重试
    messagesToSummarize = truncateHeadForPTLRetry(messagesToSummarize)
  }

  // 4. 清除文件状态缓存
  context.readFileState.clear()
  context.loadedNestedMemoryPaths?.clear()

  // 5. 并行生成恢复附件
  const [fileAttachments, asyncAgentAttachments] = await Promise.all([
    // 恢复最近读取的文件 (最多 N 个)
    createPostCompactFileAttachments(preCompactReadFileState, context),
    // 恢复异步 Agent 状态
    createAsyncAgentAttachmentsIfNeeded(context),
  ])

  // 6. 恢复其他状态
  const planAttachment = createPlanAttachmentIfNeeded(context.agentId)
  const skillAttachment = createSkillAttachmentIfNeeded(context.agentId)

  // 7. 重新公告工具/Agent/MCP 列表 (压缩清除了历史中的增量公告)
  const toolsDelta = getDeferredToolsDeltaAttachment(tools, model, [])
  const agentDelta = getAgentListingDeltaAttachment(context, [])
  const mcpDelta = getMcpInstructionsDeltaAttachment(mcpClients, tools)

  // 8. 执行 SessionStart Hooks
  const hookMessages = await processSessionStartHooks('compact')

  // 9. 构建压缩后消息
  return {
    summaryMessages: [compactBoundaryMessage, summaryMessage],
    attachments: [
      ...fileAttachments,
      ...asyncAgentAttachments,
      planAttachment,
      skillAttachment,
      ...toolsDelta,
      ...agentDelta,
      ...mcpDelta,
    ],
    hookResults: hookMessages,
  }
}
```

压缩后的消息结构：

```
压缩前:
  [user₁, assistant₁, user₂(tool_result), assistant₂, ..., userₙ]
  (可能数百条消息，数十万 tokens)

压缩后:
  [compact_boundary,           ← 标记压缩边界
   user(summary),              ← LLM 生成的对话摘要
   attachment(file₁),          ← 最近读取的文件恢复
   attachment(file₂),
   attachment(plan),           ← 计划模式恢复
   attachment(skills),         ← 技能状态恢复
   attachment(tools_delta),    ← 工具列表重新公告
   attachment(agent_delta),    ← Agent 列表重新公告
   attachment(mcp_delta)]      ← MCP 指令重新公告
  (通常 10-20 条消息，数万 tokens)
```

#### 11.4.5 Context Collapse — 上下文折叠

借鉴 `utils/collapseReadSearch.ts` 和 `query.ts` 中的 `contextCollapse` 引用：

```
Context Collapse 的核心思想:
  不是等到 token 溢出才压缩，而是在每轮主动将
  "低价值"的工具调用组折叠为摘要。

折叠目标 (可折叠的工具调用):
  ├── 搜索类: Glob, Grep, WebSearch
  ├── 读取类: FileRead, WebFetch
  ├── Shell 只读类: ls, cat, head, tail, git log
  └── Hook 摘要: PostToolUse hook summaries

不可折叠的工具调用:
  ├── 写入类: FileEdit, FileWrite, Bash(写入命令)
  ├── Agent 类: Agent, SendMessage
  └── 用户交互: AskUserQuestion

折叠规则:
  1. 连续的可折叠工具调用 → 合并为一个摘要组
  2. 遇到不可折叠的工具调用或用户文本 → 断开组
  3. 摘要包含: 工具名、文件路径、关键发现
  4. 折叠是"读时投影" — 原始消息保留在内存中，
     只在发送给 API 时应用折叠视图

与 Autocompact 的协同:
  Context Collapse 在 Autocompact 之前执行。
  如果折叠后 token 使用量降到阈值以下，
  Autocompact 就不需要触发，保留了更细粒度的上下文。
```

#### 11.4.6 Reactive Compact — 响应式压缩

```
Reactive Compact 是 Autocompact 的兜底机制:

触发条件:
  API 返回 prompt_too_long 错误
  (Autocompact 的阈值估算不准确，或上下文突然增长)

处理流程:
  1. 拦截 prompt_too_long 错误 (不返回给用户)
  2. 立即执行 compactConversation()
  3. 用压缩后的消息重新发送 API 请求
  4. 如果压缩后仍然 too long → 截断最旧消息组重试
  5. 最多重试 MAX_PTL_RETRIES 次

与 max_output_tokens 恢复的区别:
  - prompt_too_long: 输入太长 → 压缩输入
  - max_output_tokens: 输出被截断 → 增加 maxOutputTokens 重试
```

### 11.5 子 Agent 的上下文隔离

#### 11.5.1 命名 Agent 的上下文构建

借鉴 `runAgent.ts:248`：

```typescript
// 命名 Agent 的上下文构建 (借鉴 runAgent.ts)
async function* runAgent({ agentDefinition, promptMessages, toolUseContext }) {
  // 1. 获取基础上下文
  const [baseUserContext, baseSystemContext] = await Promise.all([
    override?.userContext ?? getUserContext(),
    override?.systemContext ?? getSystemContext(),
  ])

  // 2. 只读 Agent 省略 CLAUDE.md (节省 token)
  // Explore/Plan 是只读搜索 Agent，不需要 commit/PR/lint 规则
  // 每周节省 ~5-15 Gtok (3400万+ Explore 调用)
  const shouldOmitClaudeMd = agentDefinition.omitClaudeMd
  const resolvedUserContext = shouldOmitClaudeMd
    ? omit(baseUserContext, 'claudeMd')
    : baseUserContext

  // 3. Explore/Plan 省略 Git 状态 (节省 token)
  // 如果需要 Git 信息，它们会自己执行 `git status`
  const resolvedSystemContext =
    agentDefinition.agentType === 'Explore' || agentDefinition.agentType === 'Plan'
      ? omit(baseSystemContext, 'gitStatus')
      : baseSystemContext

  // 4. 构建 Agent 专属 System Prompt
  const agentSystemPrompt = await getAgentSystemPrompt(agentDefinition)

  // 5. 独立的文件状态缓存
  const agentReadFileState = forkContextMessages
    ? cloneFileStateCache(toolUseContext.readFileState)  // Fork: 克隆父缓存
    : createFileStateCacheWithSizeLimit(CACHE_SIZE)      // 命名: 全新缓存

  // 6. 独立的权限模式
  const agentPermissionMode = agentDefinition.permissionMode ?? 'acceptEdits'
}
```

#### 11.5.2 Fork Agent 的 Prompt Cache 共享

借鉴 `forkSubagent.ts`：

```
Fork Agent 的上下文共享策略:

目标: 最大化 Prompt Cache 命中率

实现:
  父 Agent 的完整对话历史 (assistant messages + tool_use blocks)
      ↓ 共享前缀 (所有 fork 完全相同)
  所有 tool_result 替换为统一占位符:
    "Fork started — processing in background"
      ↓ 共享前缀 (所有 fork 完全相同)
  最后一个 text block 包含各自的指令
      ↓ 各 fork 不同 (cache miss 只在这里)

效果:
  假设父 Agent 对话历史 = 100K tokens
  Fork A 的独立指令 = 500 tokens
  Fork B 的独立指令 = 800 tokens

  Fork A 的 API 请求: 100K (cache hit) + 500 (cache miss)
  Fork B 的 API 请求: 100K (cache hit) + 800 (cache miss)

  cache 命中率 ≈ 99.5%

关键约束:
  - Fork 不能设置不同的 model (不同模型无法共享 cache)
  - Fork 保留 Agent 工具 (为了 cache-identical tool defs)
  - 但通过 querySource 检查防止递归 fork
```

#### 11.5.3 子 Agent 上下文大小控制

```
子 Agent 的上下文优化策略:

1. 省略不必要的上下文:
   ├── Explore/Plan: 省略 CLAUDE.md (omitClaudeMd: true)
   ├── Explore/Plan: 省略 Git 状态
   └── Worker: 省略 Coordinator 上下文

2. 独立的文件状态缓存:
   ├── 命名 Agent: 全新缓存 (不继承父 Agent 的文件读取历史)
   └── Fork Agent: 克隆父缓存 (继承已读文件，避免重复读取)

3. 独立的 contentReplacementState:
   ├── 命名 Agent: 全新状态
   └── Fork Agent: 克隆父状态 (保持 prompt cache 稳定性)

4. maxTurns 限制:
   ├── 防止子 Agent 无限循环
   └── 默认值由 Agent 定义指定
```

### 11.6 上下文管理的性能优化

#### 11.6.1 Memoize 缓存策略

```typescript
// 会话级缓存 (借鉴 context.ts)
const getSystemContext = memoize(async () => { ... })  // 每会话一次
const getUserContext = memoize(async () => { ... })    // 每会话一次
const getGitStatus = memoize(async () => { ... })      // 每会话一次

// 项目级缓存 (借鉴 loadSkillsDir.ts)
const getSkillDirCommands = memoize(async (cwd) => { ... })  // 按 cwd 缓存

// 缓存失效:
// setSystemPromptInjection() 时清除 getUserContext 和 getSystemContext 的缓存
// 文件变更时通过 skillChangeDetector 触发技能缓存刷新
```

#### 11.6.2 并行加载策略

```
启动时并行加载:
  Promise.all([
    getSystemPrompt(),     // 系统提示词
    getUserContext(),       // 用户上下文
    getSystemContext(),     // 系统上下文
  ])

每轮并行加载:
  Promise.all([
    processAtMentionedFiles(),    // @文件引用
    processMcpResourceAttachments(), // MCP 资源
    getSkillListingAttachments(),   // 技能列表
    getDiagnosticAttachments(),     // 诊断信息
  ])

压缩后并行恢复:
  Promise.all([
    createPostCompactFileAttachments(),  // 文件恢复
    createAsyncAgentAttachmentsIfNeeded(), // Agent 恢复
  ])
```

#### 11.6.3 上下文预取 (Prefetch)

```typescript
// 相关记忆预取 (借鉴 attachments.ts)
// 在 API 调用期间并行执行，不阻塞主流程
using pendingMemoryPrefetch = startRelevantMemoryPrefetch(
  state.messages,
  state.toolUseContext,
)

// 技能发现预取 (借鉴 query.ts)
// 在模型流式输出期间并行执行
const pendingSkillPrefetch = skillPrefetch?.startSkillDiscoveryPrefetch(
  null, messages, toolUseContext
)

// 预取结果在工具执行后消费 (不阻塞流式输出)
```

### 11.7 上下文管理源码文件索引

| 文件 | 核心职责 |
|------|---------|
| `src/context.ts` | 系统/用户上下文加载 (memoized) |
| `src/utils/queryContext.ts` | System Prompt 组装 |
| `src/utils/claudemd.ts` | CLAUDE.md 记忆文件发现与加载 |
| `src/utils/attachments.ts` | 动态附件系统 (3000+ 行核心) |
| `src/utils/toolResultStorage.ts` | 工具结果预算控制与持久化 |
| `src/services/compact/compact.ts` | 全量压缩 (compactConversation) |
| `src/services/compact/apiMicrocompact.ts` | API 微压缩策略 |
| `src/services/compact/cachedMicrocompact.ts` | 缓存微压缩 (cache editing) |
| `src/services/compact/snipCompact.ts` | 历史裁剪 |
| `src/services/compact/autoCompact.ts` | 自动压缩触发逻辑 |
| `src/utils/collapseReadSearch.ts` | 搜索/读取结果折叠 |
| `src/utils/collapseHookSummaries.ts` | Hook 摘要折叠 |
| `src/coordinator/coordinatorMode.ts` | Coordinator 上下文注入 |
| `src/tools/AgentTool/runAgent.ts` | 子 Agent 上下文构建 |
| `src/tools/AgentTool/forkSubagent.ts` | Fork 上下文共享 |
| `src/query.ts` | 上下文压缩管线编排 |
