# Memory 系统详细设计 — 有界策展式记忆

> 基于 Hermes Agent 源码（`tools/memory_tool.py`、`agent/memory_manager.py`、`agent/memory_provider.py`）的完整逆向分析，输出可落地的 Agent Memory 系统设计。

---

## 一、设计哲学

**核心理念**：Memory 不是"记住一切"，而是"只记住最重要的"。

| 设计原则 | Hermes 实现 | 设计意图 |
|:---|:---|:---|
| 有界（Bounded） | 硬性字符限制 2,200 / 1,375 chars | 强制信息密度，防止 token 膨胀 |
| 策展式（Curated） | Agent 自主决定 add/replace/remove | 不是被动记录，是主动筛选 |
| 冻结快照（Frozen Snapshot） | 会话开始时注入，中途不变 | 保护 LLM prefix cache |
| 双存储分离 | MEMORY（环境事实）vs USER（用户画像） | 不同生命周期、不同淘汰策略 |
| 安全扫描 | 写入前检测注入/泄露模式 | Memory 注入 system prompt，是攻击面 |

---

## 二、整体架构

```
┌─────────────────────────────────────────────────────────────────────┐
│                        System Prompt                                  │
│  ┌────────────────────────────────────────────────────────────────┐  │
│  │ ══════════════════════════════════════════════                  │  │
│  │ MEMORY (your personal notes) [67% — 1,474/2,200 chars]         │  │
│  │ ══════════════════════════════════════════════                  │  │
│  │ User's project is a Rust web service using Axum + SQLx         │  │
│  │ §                                                              │  │
│  │ This machine runs Ubuntu 22.04, has Docker installed           │  │
│  │ §                                                              │  │
│  │ User prefers concise responses                                 │  │
│  └────────────────────────────────────────────────────────────────┘  │
│                    ↑ 冻结快照（会话开始时捕获，中途不变）               │
└─────────────────────────────────────────────────────────────────────┘
         │                                    ▲
         │ Agent 看到 Memory 内容              │ 下次会话刷新
         ▼                                    │
┌─────────────────────────────────────────────────────────────────────┐
│                     memory tool (运行时)                              │
│                                                                      │
│  ┌──────────┐   ┌──────────────┐   ┌──────────────┐                │
│  │ add      │   │ replace      │   │ remove       │                │
│  │ 新增条目  │   │ 子串匹配替换  │   │ 子串匹配删除  │                │
│  └────┬─────┘   └──────┬───────┘   └──────┬───────┘                │
│       │                 │                   │                        │
│       └─────────────────┼───────────────────┘                        │
│                         ▼                                            │
│              ┌─────────────────────┐                                 │
│              │  MemoryStore        │                                 │
│              │  (内存 + 磁盘持久化) │                                 │
│              └──────────┬──────────┘                                 │
│                         │                                            │
│              ┌──────────▼──────────┐                                 │
│              │  ~/.hermes/memories/ │                                 │
│              │  ├── MEMORY.md      │                                 │
│              │  └── USER.md        │                                 │
│              └─────────────────────┘                                 │
└─────────────────────────────────────────────────────────────────────┘
```


---

## 三、数据模型

### 3.1 存储结构

```
~/.hermes/memories/
├── MEMORY.md          # Agent 个人笔记（环境、约定、教训）
├── MEMORY.md.lock     # 文件锁（并发安全）
├── USER.md            # 用户画像（偏好、风格、身份）
└── USER.md.lock       # 文件锁
```

### 3.2 条目格式

```markdown
条目1内容（可多行）
§
条目2内容
§
条目3内容
```

- **分隔符**：`\n§\n`（section sign，非常规字符，避免与内容冲突）
- **条目可多行**：一个条目可以包含换行，只有 `§` 才是条目边界
- **无 ID、无时间戳**：极简设计，靠子串匹配定位条目

### 3.3 容量约束

| 存储 | 字符上限 | 约合 Token | 典型条目数 | 用途 |
|:---|:---|:---|:---|:---|
| MEMORY.md | 2,200 chars | ~800 tokens | 8-15 条 | 环境事实、项目约定、工具技巧 |
| USER.md | 1,375 chars | ~500 tokens | 5-10 条 | 用户身份、偏好、沟通风格 |
| **合计** | **3,575 chars** | **~1,300 tokens** | — | 每次对话的固定 token 成本 |

**为什么用字符而非 Token**：字符计数是模型无关的，不依赖特定 tokenizer。

---

## 四、核心类设计（源码逆向）

### 4.1 MemoryStore — 存储引擎

```python
class MemoryStore:
    """有界策展式记忆存储引擎"""
    
    def __init__(self, memory_char_limit=2200, user_char_limit=1375):
        self.memory_entries: List[str] = []      # 实时状态
        self.user_entries: List[str] = []        # 实时状态
        self.memory_char_limit = memory_char_limit
        self.user_char_limit = user_char_limit
        # 冻结快照 — 会话开始时捕获，中途不变
        self._system_prompt_snapshot: Dict[str, str] = {"memory": "", "user": ""}
```

**双状态设计**：
- `_system_prompt_snapshot`：冻结快照，用于 system prompt 注入，保护 prefix cache
- `memory_entries` / `user_entries`：实时状态，tool 调用后立即更新，持久化到磁盘

### 4.2 关键操作

#### add — 新增条目

```python
def add(self, target: str, content: str) -> Dict[str, Any]:
    # 1. 内容不能为空
    # 2. 安全扫描（注入/泄露检测）
    # 3. 获取文件锁
    # 4. 从磁盘重新加载（获取最新状态）
    # 5. 去重检查（拒绝完全相同的条目）
    # 6. 容量检查（新增后是否超限）
    #    - 超限 → 返回错误 + 当前所有条目 + 使用量
    #    - 未超限 → 追加 + 持久化
    # 7. 返回成功响应（含所有条目 + 使用百分比）
```

#### replace — 子串匹配替换

```python
def replace(self, target: str, old_text: str, new_content: str) -> Dict[str, Any]:
    # 1. old_text 和 new_content 不能为空
    # 2. 安全扫描新内容
    # 3. 获取文件锁 + 重新加载
    # 4. 子串匹配：找到包含 old_text 的条目
    #    - 0 匹配 → 错误
    #    - 多匹配（不同内容）→ 错误，要求更精确
    #    - 多匹配（相同内容，即重复条目）→ 操作第一个
    #    - 1 匹配 → 继续
    # 5. 容量检查（替换后是否超限）
    # 6. 执行替换 + 持久化
```

#### remove — 子串匹配删除

```python
def remove(self, target: str, old_text: str) -> Dict[str, Any]:
    # 逻辑同 replace，但不需要 new_content
    # 匹配到条目后直接 pop
```


### 4.3 并发安全机制

```python
@contextmanager
def _file_lock(path: Path):
    """独占文件锁，保护 read-modify-write 操作"""
    lock_path = path.with_suffix(path.suffix + ".lock")  # 独立锁文件
    # Unix: fcntl.flock(LOCK_EX)
    # Windows: msvcrt.locking(LK_LOCK)

@staticmethod
def _write_file(path: Path, entries: List[str]):
    """原子写入：temp file + fsync + rename"""
    # 1. 写入临时文件（同目录，确保同文件系统）
    # 2. fsync 确保数据落盘
    # 3. atomic_replace（os.replace）原子替换
    # 好处：读者永远看到完整文件（旧的或新的），不会看到半写状态
```

**为什么不用 open("w") + flock**：
- `open("w")` 在获取锁之前就会截断文件
- 并发读者可能看到空文件
- 原子 rename 彻底避免这个问题

---

## 五、System Prompt 注入机制

### 5.1 冻结快照模式

```
会话开始
    │
    ▼
load_from_disk()
    │
    ├── 读取 MEMORY.md → memory_entries
    ├── 读取 USER.md → user_entries
    ├── 去重
    └── 捕获 _system_prompt_snapshot ← 此后不再变化
    │
    ▼
build_system_prompt()
    │
    ├── ... 其他层 ...
    ├── Layer 5: _system_prompt_snapshot["memory"]  ← 冻结
    ├── Layer 6: _system_prompt_snapshot["user"]    ← 冻结
    ├── ... 其他层 ...
    │
    ▼
整个会话期间 system prompt 不变
    │
    ▼
Agent 调用 memory tool → 更新磁盘 → 下次会话生效
```

### 5.2 注入格式

```
══════════════════════════════════════════════
MEMORY (your personal notes) [67% — 1,474/2,200 chars]
══════════════════════════════════════════════
User's project is a Rust web service at ~/code/myapi using Axum + SQLx
§
This machine runs Ubuntu 22.04, has Docker and Podman installed
§
User prefers concise responses, dislikes verbose explanations

══════════════════════════════════════════════
USER PROFILE (who the user is) [45% — 619/1,375 chars]
══════════════════════════════════════════════
Name: Alice, Senior Backend Engineer
§
Prefers TypeScript over JavaScript, uses Vim keybindings
§
Timezone: US/Pacific, works 9am-6pm
```

**关键设计**：
- 显示使用百分比 → Agent 知道容量压力，主动合并条目
- 使用 `═` 分隔线 → 视觉清晰，不与内容混淆
- 标注 chars 数 → Agent 可以估算新条目是否放得下

### 5.3 为什么冻结快照？

| 如果中途更新 prompt | 冻结快照 |
|:---|:---|
| 每次 memory 写入都重建 system prompt | system prompt 整个会话不变 |
| 破坏 LLM prefix cache | prefix cache 完整保留 |
| 每轮推理都要重新计算 KV cache | 只有首轮计算，后续复用 |
| 成本高、延迟大 | 成本低、延迟小 |
| 可能导致模型行为不一致 | 行为一致可预测 |

---

## 六、Tool Schema 设计 — 引导 Agent 行为

### 6.1 完整 Schema

```json
{
  "name": "memory",
  "description": "Save durable information to persistent memory that survives across sessions...",
  "parameters": {
    "type": "object",
    "properties": {
      "action": {
        "type": "string",
        "enum": ["add", "replace", "remove"]
      },
      "target": {
        "type": "string",
        "enum": ["memory", "user"]
      },
      "content": {
        "type": "string",
        "description": "The entry content. Required for 'add' and 'replace'."
      },
      "old_text": {
        "type": "string",
        "description": "Short unique substring identifying the entry to replace or remove."
      }
    },
    "required": ["action", "target"]
  }
}
```


### 6.2 Description 中的行为引导（关键设计）

Tool description 不仅描述功能，更**引导 Agent 何时、如何使用 Memory**：

```
WHEN TO SAVE (do this proactively, don't wait to be asked):
- User corrects you or says 'remember this' / 'don't do that again'
- User shares a preference, habit, or personal detail
- You discover something about the environment
- You learn a convention, API quirk, or workflow
- You identify a stable fact that will be useful again

PRIORITY: User preferences and corrections > environment facts > procedural knowledge

Do NOT save:
- Task progress, session outcomes, completed-work logs
- Temporary TODO state
- Things easily re-discovered via web search
```

**设计洞察**：通过 tool description 实现"元认知引导" — 告诉 Agent 什么值得记住、什么不值得，而不是靠 Agent 自己摸索。

### 6.3 子串匹配而非 ID

```python
# 替换操作不需要精确匹配全文，只需唯一子串
memory(action="replace", target="memory",
       old_text="dark mode",  # 只要这个子串能唯一定位一个条目
       content="User prefers light mode in VS Code, dark mode in terminal")
```

**为什么不用 ID**：
- Agent 不需要记住条目 ID
- 子串匹配更自然，更接近人类思维
- 减少 tool call 的参数复杂度
- 如果子串匹配多个条目 → 返回错误，要求更精确

---

## 七、安全扫描机制

### 7.1 威胁模型

Memory 内容会被注入 system prompt，因此是一个**攻击面**：
- 恶意用户可能通过对话诱导 Agent 将注入 payload 写入 Memory
- 下次会话时，payload 从 system prompt 执行

### 7.2 扫描规则

```python
_MEMORY_THREAT_PATTERNS = [
    # Prompt 注入
    (r'ignore\s+(previous|all|above|prior)\s+instructions', "prompt_injection"),
    (r'you\s+are\s+now\s+', "role_hijack"),
    (r'do\s+not\s+tell\s+the\s+user', "deception_hide"),
    (r'system\s+prompt\s+override', "sys_prompt_override"),
    (r'disregard\s+(your|all|any)\s+(instructions|rules|guidelines)', "disregard_rules"),
    
    # 数据泄露
    (r'curl\s+[^\n]*\$\{?\w*(KEY|TOKEN|SECRET|PASSWORD)', "exfil_curl"),
    (r'wget\s+[^\n]*\$\{?\w*(KEY|TOKEN|SECRET|PASSWORD)', "exfil_wget"),
    (r'cat\s+[^\n]*(\.env|credentials|\.netrc|\.pgpass)', "read_secrets"),
    
    # 持久化后门
    (r'authorized_keys', "ssh_backdoor"),
    (r'\$HOME/\.ssh|\~/\.ssh', "ssh_access"),
]

# 不可见 Unicode 字符检测
_INVISIBLE_CHARS = {'\u200b', '\u200c', '\u200d', '\u2060', '\ufeff', ...}
```

### 7.3 扫描时机

```
用户对话 → Agent 决定写入 Memory → _scan_memory_content() → 通过/拒绝
                                         │
                                    检测注入模式
                                    检测泄露模式
                                    检测不可见字符
                                         │
                                    拒绝 → 返回错误，不写入
```

---

## 八、MemoryManager — 插件化架构

### 8.1 Provider 模式

```python
class MemoryManager:
    """编排内置 provider + 至多一个外部 provider"""
    
    def __init__(self):
        self._providers: List[MemoryProvider] = []
        self._tool_to_provider: Dict[str, MemoryProvider] = {}
        self._has_external: bool = False  # 只允许一个外部 provider
```

**约束**：只允许一个外部 Memory Provider（防止 tool schema 膨胀和后端冲突）。

### 8.2 Provider 生命周期

```
Agent 启动
    │
    ▼
MemoryManager.initialize_all(session_id)
    │
    ├── builtin provider: 加载 MEMORY.md / USER.md
    └── external provider (如 Honcho): 连接后端、创建资源
    │
    ▼
每轮对话开始
    │
    ├── on_turn_start(turn_number, message)
    ├── prefetch_all(user_message) → 注入上下文
    │
    ▼
对话进行中
    │
    ├── handle_tool_call() → 路由到正确的 provider
    ├── on_memory_write() → 通知外部 provider 镜像写入
    │
    ▼
每轮对话结束
    │
    ├── sync_all(user_content, assistant_content)
    └── queue_prefetch_all(user_msg) → 预取下轮上下文
    │
    ▼
会话结束
    │
    ├── on_session_end(messages)
    └── shutdown_all()
```


### 8.3 Provider 抽象接口

```python
class MemoryProvider(ABC):
    """可插拔的记忆后端"""
    
    @property
    @abstractmethod
    def name(self) -> str: ...           # "builtin", "honcho", "mem0"
    
    @abstractmethod
    def is_available(self) -> bool: ...   # 检查配置/凭证
    
    @abstractmethod
    def initialize(self, session_id, **kwargs): ...  # 启动
    
    def system_prompt_block(self) -> str: ...   # 静态 prompt 注入
    def prefetch(self, query) -> str: ...       # 每轮预取上下文
    def sync_turn(self, user, assistant): ...   # 每轮同步
    
    @abstractmethod
    def get_tool_schemas(self) -> List[Dict]: ...  # 暴露的工具
    def handle_tool_call(self, tool_name, args): ...  # 处理调用
    
    # 可选钩子
    def on_turn_start(self, turn_number, message, **kwargs): ...
    def on_session_end(self, messages): ...
    def on_session_switch(self, new_session_id, **kwargs): ...
    def on_pre_compress(self, messages) -> str: ...
    def on_memory_write(self, action, target, content, metadata=None): ...
    def on_delegation(self, task, result, **kwargs): ...
```

### 8.4 流式输出安全 — StreamingContextScrubber

外部 Provider 可能在 prefetch 中注入 `<memory-context>` 块，这些内容不应暴露给用户：

```python
class StreamingContextScrubber:
    """状态机式流式文本清洗器"""
    
    # 问题：<memory-context> 标签可能跨 chunk 边界
    # 解决：维护状态机，跨 delta 追踪 span 开闭
    
    def feed(self, text: str) -> str:
        """输入一个 delta，返回可见部分"""
        # 在 span 内 → 丢弃内容
        # 在 span 外 → 输出内容
        # 遇到可能的标签前缀 → hold back 等待确认
    
    def flush(self) -> str:
        """流结束时释放 hold back 的内容"""
```

---

## 九、容量管理策略 — Agent 如何"忘记"

### 9.1 容量满时的交互流程

```
Agent 尝试 add 新条目
    │
    ▼
MemoryStore.add() 检测到超限
    │
    ▼
返回错误响应：
{
  "success": false,
  "error": "Memory at 2,100/2,200 chars. Adding this entry (250 chars) 
            would exceed the limit. Replace or remove existing entries first.",
  "current_entries": ["条目1", "条目2", ...],  ← 展示所有现有条目
  "usage": "2,100/2,200"
}
    │
    ▼
Agent 看到所有条目 → 自主决定：
    ├── 合并相关条目（replace 多条为一条）
    ├── 删除过时条目（remove）
    └── 然后再 add 新条目
```

### 9.2 Agent 的"遗忘"决策

Agent 通过 system prompt 中的使用百分比感知容量压力：

```
MEMORY (your personal notes) [92% — 2,024/2,200 chars]
```

**设计意图**：当 Agent 看到 >80% 时，应主动合并/清理，而不是等到满了才被动处理。

### 9.3 信息密度优化示例

```markdown
# 差：3 条独立条目（~180 chars）
User runs macOS 14 Sonoma
§
User uses Homebrew for package management
§
User has Docker Desktop and Podman installed

# 好：1 条合并条目（~95 chars）
User runs macOS 14 Sonoma, uses Homebrew, has Docker Desktop and Podman.
```

Agent 被引导写出"紧凑、信息密集"的条目，而非冗长描述。

---

## 十、与 Prompt Assembly 的集成

### 10.1 在 System Prompt 中的位置

```
Layer 1: Agent Identity (SOUL.md)
Layer 2: Tool-aware behavior guidance
Layer 3: Honcho static block
Layer 4: Optional system message
Layer 5: ★ Frozen MEMORY snapshot ★    ← 这里
Layer 6: ★ Frozen USER profile ★       ← 这里
Layer 7: Skills index
Layer 8: Context files (AGENTS.md)
Layer 9: Timestamp + session ID
Layer 10: Platform hint
```

### 10.2 Memory Guidance（行为引导文本）

在 Layer 2 中，有专门的 Memory 使用指导：

```
You have persistent memory across sessions. Save durable facts using
the memory tool: user preferences, environment details, tool quirks,
and stable conventions. Memory is injected into every turn, so keep
it compact and focused on facts that will still matter later.
```

这段文本告诉 Agent：
1. 你有持久记忆
2. 用 memory tool 保存
3. 保持紧凑
4. 只保存"以后还重要"的事实

---

## 十一、配置项

```yaml
# ~/.hermes/config.yaml
memory:
  memory_enabled: true          # 是否启用 MEMORY.md
  user_profile_enabled: true    # 是否启用 USER.md
  memory_char_limit: 2200       # MEMORY 字符上限（~800 tokens）
  user_char_limit: 1375         # USER 字符上限（~500 tokens）
  provider: null                # 外部 provider（honcho/mem0/hindsight/...）
```

---

## 十二、与外部 Memory Provider 的协作

### 12.1 内置 vs 外部

| 维度 | 内置 (builtin) | 外部 (Honcho/Mem0/...) |
|:---|:---|:---|
| 始终活跃 | ✅ | 可选，至多一个 |
| 存储 | 本地 Markdown 文件 | 远程后端（知识图谱/向量库） |
| 容量 | 有界（3,575 chars） | 无限 |
| 注入方式 | system prompt 冻结快照 | prefetch 动态注入 user message |
| 成本 | 固定 ~1,300 tokens/会话 | 按需，可能更高 |
| 适用场景 | 关键事实始终可见 | 深度回忆、语义搜索 |

### 12.2 写入镜像

当内置 memory tool 写入时，通知外部 provider 同步：

```python
def on_memory_write(self, action, target, content, metadata=None):
    """外部 provider 可以镜像内置 memory 的写入"""
    # 例如 Honcho 可以将 memory 条目同步到知识图谱
    # 实现跨会话的语义检索
```

---

## 十三、aPaaS Agent 系统的 Memory 设计方案

### 13.1 双存储映射

| Hermes 概念 | aPaaS 映射 | 内容示例 |
|:---|:---|:---|
| MEMORY.md | `AGENT_MEMORY.md` | 租户的元模型命名偏好、常用字段类型、项目约定 |
| USER.md | `USER_PROFILE.md` | 用户角色、权限范围、操作习惯、沟通风格 |

### 13.2 aPaaS 特化的存储内容

**AGENT_MEMORY（环境事实）**：
```
该租户使用 camelCase 命名元模型字段，entity api_key 格式为 {模块}_{对象}
§
常用字段类型：varchar(文本)、int(整数)、datetime(日期时间)、pick(选项)
§
该租户有 15 个自定义实体，最大的是 customerOrder（42 个字段）
§
校验规则偏好：必填用 required，格式用 regex，跨字段用 formula
```

**USER_PROFILE（用户画像）**：
```
张工，高级配置工程师，负责 CRM 模块的元数据配置
§
偏好批量操作，不喜欢逐条确认；习惯先建字段再配规则
§
对 API 接口熟悉，可以直接给出 JSON 格式的配置
```


### 13.3 多租户隔离设计

```
/agent-memory/
├── tenant_{tenantId}/
│   ├── user_{userId}/
│   │   ├── AGENT_MEMORY.md      # 该用户视角的环境记忆
│   │   ├── USER_PROFILE.md      # 该用户画像
│   │   └── SESSION_INDEX.db     # 会话索引（SQLite）
│   └── shared/
│       └── TENANT_CONTEXT.md    # 租户级共享知识（只读）
└── global/
    └── PLATFORM_KNOWLEDGE.md    # 平台级知识（所有租户共享）
```

**隔离原则**：
- 用户 A 的 Memory 对用户 B 不可见
- 租户 X 的 Memory 对租户 Y 不可见
- 平台级知识（如元模型类型列表）所有人共享

### 13.4 aPaaS 特化的安全扫描

除了 Hermes 的通用威胁模式，aPaaS 需要额外检测：

```python
_APAAS_THREAT_PATTERNS = [
    # 跨租户数据泄露
    (r'tenant_id\s*[=:]\s*\d+', "cross_tenant_leak"),
    # SQL 注入载荷
    (r"(UNION\s+SELECT|DROP\s+TABLE|DELETE\s+FROM)", "sql_injection"),
    # 权限提升
    (r'(admin|superuser|root)\s*(role|permission|access)', "privilege_escalation"),
    # 敏感数据存储
    (r'(password|secret|token)\s*[=:]\s*\S+', "credential_storage"),
]
```

### 13.5 容量规划

| 场景 | MEMORY 上限 | USER 上限 | 理由 |
|:---|:---|:---|:---|
| 轻量 Agent（问答） | 2,200 chars | 1,375 chars | 与 Hermes 一致 |
| 配置 Agent（元数据操作） | 4,000 chars | 2,000 chars | 需要记住更多元模型约定 |
| 高级 Agent（全流程） | 6,000 chars | 3,000 chars | 需要记住复杂业务规则 |

---

## 十四、关键设计决策总结

### 14.1 为什么有界？

| 无界记忆的问题 | 有界记忆的解法 |
|:---|:---|
| Token 成本线性增长 | 固定 ~1,300 tokens/会话 |
| 信息噪声淹没关键事实 | 强制只保留最重要的 |
| Agent 不需要"遗忘"能力 | Agent 必须学会取舍 |
| 旧信息可能过时但仍占位 | 容量压力迫使更新 |
| 无法预测 prompt 长度 | 长度完全可控 |

### 14.2 为什么 Agent 自主管理？

| 人工管理 | Agent 自主管理 |
|:---|:---|
| 用户需要手动维护 | 零用户负担 |
| 用户不知道 Agent 需要什么 | Agent 知道自己缺什么 |
| 更新不及时 | 实时更新 |
| 格式不统一 | Agent 自己控制格式 |

### 14.3 为什么冻结快照？

```
性能收益：
  - Anthropic prefix cache: 首次计算后，后续轮次复用 KV cache
  - 节省 ~50% 的推理延迟（对长 system prompt）
  - 节省 ~75% 的 token 计费（cached tokens 打折）

一致性收益：
  - Agent 在整个会话中看到相同的 Memory
  - 不会因为中途写入导致行为突变
  - 调试更容易（prompt 是确定性的）
```

### 14.4 为什么用文件而非数据库？

| 文件存储 | 数据库存储 |
|:---|:---|
| 零依赖，任何环境都能运行 | 需要 DB 进程 |
| 人类可读可编辑 | 需要工具查看 |
| Git 友好，可版本控制 | 不适合 Git |
| 原子 rename 保证一致性 | 需要事务 |
| 适合小数据量（<4KB） | 适合大数据量 |

---

## 十五、实现路线图

### Phase 1：基础 Memory（2 周）
- [ ] MemoryStore 核心类（add/replace/remove）
- [ ] 文件持久化 + 原子写入
- [ ] 安全扫描
- [ ] System Prompt 冻结快照注入
- [ ] Tool Schema + 行为引导

### Phase 2：多租户隔离（1 周）
- [ ] 租户/用户级目录隔离
- [ ] 权限校验
- [ ] 租户级共享知识

### Phase 3：外部 Provider 集成（2 周）
- [ ] MemoryProvider 抽象接口
- [ ] MemoryManager 编排层
- [ ] 向量检索 Provider（语义搜索）
- [ ] 写入镜像机制

### Phase 4：进化优化（持续）
- [ ] Memory 使用效果评估
- [ ] 自动合并/清理策略优化
- [ ] 基于 GEPA 的 Memory Guidance 文本进化

---

## 十六、参考源码索引

| 文件 | 职责 | 关键类/函数 |
|:---|:---|:---|
| `tools/memory_tool.py` | Memory 工具实现 | `MemoryStore`, `memory_tool()`, `MEMORY_SCHEMA` |
| `agent/memory_manager.py` | Provider 编排 | `MemoryManager`, `StreamingContextScrubber` |
| `agent/memory_provider.py` | Provider 抽象接口 | `MemoryProvider` (ABC) |
| `agent/prompt_builder.py` | Prompt 组装 | `build_system_prompt()` |
| `hermes_constants.py` | 路径常量 | `get_hermes_home()` |

---

*来源：[NousResearch/hermes-agent](https://github.com/NousResearch/hermes-agent) 源码逆向分析*
*Content was rephrased for compliance with licensing restrictions*
