# Hermes Agent Skill 远程执行机制详解

## 核心流程：从 Skill 加载到虚拟机执行

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        Mac (Agent 大脑)                                      │
│                                                                             │
│  ① 用户输入 "/plan 写一个 Python 脚本"                                       │
│       │                                                                     │
│       ▼                                                                     │
│  ② skills_list() → 匹配到 "plan" skill                                     │
│       │                                                                     │
│       ▼                                                                     │
│  ③ skill_view("plan") → 加载 SKILL.md 全文到 prompt                         │
│       │                                                                     │
│       ▼                                                                     │
│  ④ prompt_builder.py 组装 system prompt:                                    │
│     [SOUL.md] + [MEMORY.md] + [Skill 指令] + [工具 schema] + [上下文]        │
│       │                                                                     │
│       ▼                                                                     │
│  ⑤ AIAgent → LLM API 调用 (Anthropic/OpenAI/OpenRouter...)                  │
│       │                                                                     │
│       ▼                                                                     │
│  ⑥ LLM 返回 tool_call: terminal(command="python3 hello.py")                 │
│       │                                                                     │
│       ▼                                                                     │
│  ⑦ model_tools.handle_function_call("terminal", {command: "..."})           │
│       │                                                                     │
│       ▼                                                                     │
│  ⑧ tools/registry.dispatch("terminal", args)                                │
│       │                                                                     │
│       ▼                                                                     │
│  ⑨ tools/terminal_tool.py → 检查 backend 配置 → "ssh"                       │
│       │                                                                     │
│       ▼                                                                     │
│  ⑩ tools/environments/ssh.py → SSH 连接到虚拟机                              │
│                                                                             │
└──────────────────────────────────┬──────────────────────────────────────────┘
                                   │
                              SSH 连接
                                   │
                                   ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                        CentOS 虚拟机 (Terminal Backend)                       │
│                                                                             │
│  ⑪ 接收命令 "python3 hello.py"                                              │
│       │                                                                     │
│       ▼                                                                     │
│  ⑫ 在 persistent shell (bash -l) 中执行                                     │
│       │                                                                     │
│       ▼                                                                     │
│  ⑬ 返回 stdout/stderr 输出                                                  │
│                                                                             │
└──────────────────────────────────┬──────────────────────────────────────────┘
                                   │
                              SSH 返回
                                   │
                                   ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                        Mac (继续)                                            │
│                                                                             │
│  ⑭ 输出字符串返回给 AIAgent                                                  │
│       │                                                                     │
│       ▼                                                                     │
│  ⑮ 追加到 conversation history: {role: "tool", content: "输出..."}           │
│       │                                                                     │
│       ▼                                                                     │
│  ⑯ 继续循环：再次调用 LLM → 可能产生更多 tool_call → 或返回最终回复           │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 一、Skill 加载阶段（Mac 上完成）

### 1.1 渐进式发现

Agent 不会一次性加载所有 Skill 内容。采用三级加载：

```
Level 0: skills_list()
         → 返回所有 skill 的 [{name, description, category}]
         → 约 3k tokens，注入到 system prompt
         → Agent 知道有哪些 skill 可用

Level 1: skill_view(name)
         → 用户触发 /plan 或 Agent 自主决定需要某 skill
         → 加载完整 SKILL.md 内容 + 元数据
         → 注入到当前 user message

Level 2: skill_view(name, path)
         → 加载 skill 的 references/ 下的特定文件
         → 按需深入
```

### 1.2 Skill 内容注入位置

```python
# agent/prompt_builder.py 中的 system prompt 组装顺序：

system_prompt = [
    SOUL.md,                    # 人格身份
    MEMORY.md + USER.md,        # 持久记忆
    skills_list(),              # 所有 skill 的索引（Level 0）
    tool_schemas,               # 可用工具的 JSON schema
    context_files,              # AGENTS.md / .hermes.md
    model_specific_guidance,    # 模型特定指令
]

# 当 skill 被激活时，完整内容作为 user message 注入：
user_message = f"[Skill: {skill_name}]\n{skill_content}\n\nUser request: {user_input}"
```

### 1.3 Skill 中的脚本引用

Skill 可以包含可执行脚本：

```
~/.hermes/skills/my-skill/
├── SKILL.md              ← 指令文档（告诉 Agent 如何使用脚本）
├── scripts/
│   ├── setup.sh          ← Agent 可以通过 terminal tool 调用
│   └── process.py        ← Agent 可以通过 execute_code 调用
├── references/
│   └── api-docs.md       ← 参考文档（Level 2 加载）
└── templates/
    └── output.md         ← 输出模板
```

SKILL.md 中会写类似：

```markdown
## Procedure
1. 运行 setup 脚本: `bash ~/.hermes/skills/my-skill/scripts/setup.sh`
2. 处理数据: `python3 ~/.hermes/skills/my-skill/scripts/process.py`
```

Agent 读到这些指令后，会通过 `terminal` tool 发出对应命令。

---

## 二、命令路由阶段（Mac → 虚拟机）

### 2.1 Tool Registry 分发

```python
# tools/registry.py — 简化逻辑

class ToolRegistry:
    _tools = {}  # {tool_name: ToolEntry}

    def dispatch(self, name, args, **kwargs):
        entry = self._tools[name]
        # 调用 handler，handler 内部决定在哪里执行
        return entry.handler(**args, **kwargs)
```

### 2.2 Terminal Tool 的 Backend 选择

```python
# tools/terminal_tool.py — 简化逻辑

def handle_terminal(command, background=False, timeout=180, **kwargs):
    backend = get_configured_backend()  # 读取 config.yaml 中的 terminal.backend

    if backend == "local":
        return environments.local.execute(command, ...)
    elif backend == "docker":
        return environments.docker.execute(command, ...)
    elif backend == "ssh":
        return environments.ssh.execute(command, ...)
    elif backend == "modal":
        return environments.modal.execute(command, ...)
    # ...
```

### 2.3 SSH Backend 的具体实现

```python
# tools/environments/ssh.py — 核心机制

class SSHBackend:
    def __init__(self):
        self.host = os.environ["TERMINAL_SSH_HOST"]      # 192.168.56.101
        self.user = os.environ["TERMINAL_SSH_USER"]      # hermes
        self.key = os.environ.get("TERMINAL_SSH_KEY")    # ~/.ssh/hermes_vm_key
        self.port = os.environ.get("TERMINAL_SSH_PORT", "22")

        # ControlMaster 连接复用（避免每次命令都重新握手）
        self.control_path = f"/tmp/hermes-ssh-{self.host}"

        # Persistent Shell（默认开启）
        # 保持一个长生命周期的 bash -l 进程
        self.persistent_shell = True

    def connect(self):
        """初始化时建立 SSH 连接"""
        ssh_args = [
            "ssh",
            "-o", "BatchMode=yes",
            "-o", "StrictHostKeyChecking=accept-new",
            "-o", f"ControlPath={self.control_path}",
            "-o", "ControlMaster=auto",
            "-o", "ControlPersist=300",  # 5分钟空闲保活
            "-i", self.key,
            "-p", self.port,
            f"{self.user}@{self.host}",
        ]
        # 启动 persistent bash session
        # 通过临时文件进行 IPC 通信

    def execute(self, command, cwd=None, timeout=180):
        """执行命令并返回输出"""
        if self.persistent_shell:
            # 通过已有的 bash session 执行
            # cwd 变更会保持（cd /tmp 后下次命令还在 /tmp）
            # export 的变量会保持
            result = self._send_to_persistent_shell(command)
        else:
            # 一次性 SSH 命令
            result = self._one_shot_execute(command)

        return result.stdout + result.stderr
```

### 2.4 Persistent Shell 的状态保持

SSH 后端默认启用 persistent shell，意味着：

```bash
# 第一次 tool call
$ cd /home/hermes/project
$ export MY_VAR=hello

# 第二次 tool call（状态保持！）
$ pwd
/home/hermes/project    ← cd 生效了
$ echo $MY_VAR
hello                   ← export 生效了
```

这是通过保持一个长生命周期的 `bash -l` 进程实现的，命令通过临时文件 IPC 发送。

---

## 三、文件同步机制

### 3.1 Skills 目录同步到虚拟机

SSH 后端使用 rsync 将 skills 同步到远程：

```
Mac: ~/.hermes/skills/my-skill/scripts/setup.sh
                    │
                    │  rsync (在首次使用或 skill 变更时)
                    ▼
VM:  ~/.hermes/skills/my-skill/scripts/setup.sh
```

同步时机：
- Hermes 启动时
- Skill 被加载（skill_view）时
- Skill 内容变更时

### 3.2 凭证文件同步

Skill 声明的 `required_credential_files` 会被同步：

```yaml
# SKILL.md frontmatter
required_credential_files:
  - path: google_token.json
    description: Google OAuth2 token
```

同步方式：
- SSH 后端 → rsync 上传到远程 `~/.hermes/`
- Docker 后端 → bind-mount 只读 (`-v host:container:ro`)
- Modal 后端 → Modal mount API + 每次命令前 sync

### 3.3 环境变量穿透

```yaml
# SKILL.md frontmatter
required_environment_variables:
  - name: TENOR_API_KEY
    prompt: Tenor API key
```

当 Skill 被加载时：
1. 检查 Mac 上是否设置了 `TENOR_API_KEY`
2. 如果设置了，注册为 passthrough 变量
3. SSH 执行命令时，通过 `env TENOR_API_KEY=xxx command` 传递

### 3.4 远程文件回同步

当会话结束时，SSH 后端会将远程修改的文件同步回 Mac：

```
VM 上 Agent 创建/修改的文件
        │
        │  rsync (会话结束时)
        ▼
Mac: ~/.hermes/cache/remote-syncs/<session-id>/
```

配置：
```yaml
terminal:
  file_sync_max_mb: 100     # 单文件最大 100MB
  file_sync_enabled: true   # 默认开启
```

---

## 四、完整时序图

```
时间轴 →

Mac (Agent)                              CentOS VM
    │                                        │
    │  ① 用户: "/plan 写 Python 脚本"         │
    │                                        │
    │  ② 加载 plan skill 到 prompt            │
    │                                        │
    │  ③ 调用 LLM API ──────────────────▶ (云端 LLM)
    │                                        │
    │  ④ LLM 返回:                           │
    │     tool_call: terminal(                │
    │       command="cat > hello.py << 'EOF'  │
    │       print('Hello World')             │
    │       EOF")                             │
    │                                        │
    │  ⑤ registry.dispatch("terminal")       │
    │                                        │
    │  ⑥ ssh.execute(command) ──────────────▶│
    │                                        │  ⑦ bash -l 执行命令
    │                                        │     创建 hello.py
    │                                        │
    │  ⑧ 收到输出 "" ◀──────────────────────│
    │                                        │
    │  ⑨ LLM 返回:                           │
    │     tool_call: terminal(                │
    │       command="python3 hello.py")       │
    │                                        │
    │  ⑩ ssh.execute(command) ──────────────▶│
    │                                        │  ⑪ python3 hello.py
    │                                        │     输出 "Hello World"
    │                                        │
    │  ⑫ 收到 "Hello World" ◀───────────────│
    │                                        │
    │  ⑬ LLM 返回最终回复:                    │
    │     "已创建并运行 hello.py，输出..."     │
    │                                        │
    │  ⑭ 显示给用户                           │
    │                                        │
```

---

## 五、关键设计细节

### 5.1 为什么 Skill 不直接在虚拟机上"运行"

Skill 本质是**给 LLM 看的指令文档**，不是可执行程序：

```
❌ 错误理解: Skill = 在虚拟机上运行的程序
✅ 正确理解: Skill = 注入到 LLM prompt 的指令 → LLM 据此生成 tool_call → tool_call 在虚拟机执行
```

这个设计的好处：
- Skill 是纯文本，不依赖任何运行时环境
- 同一个 Skill 可以适配不同的 backend（Docker/SSH/Modal）
- Agent 可以灵活组合多个 Skill 的知识

### 5.2 SSH ControlMaster 连接复用

避免每次命令都重新 TCP 握手 + SSH 认证：

```
第一次连接: TCP 握手 → SSH 认证 → 建立 ControlMaster socket
后续命令:   复用 ControlMaster socket → 直接执行（毫秒级）
空闲 5 分钟后: 自动关闭 ControlMaster
```

### 5.3 命令超时与错误处理

```yaml
terminal:
  timeout: 180  # 每条命令最长 180 秒
```

超时后：
1. 命令被 kill
2. 返回已有的 stdout/stderr + 超时错误信息
3. Agent 收到错误，可以决定重试或换策略

### 5.4 execute_code vs terminal

| 工具 | 用途 | 在虚拟机上的行为 |
|------|------|-----------------|
| `terminal` | 执行 shell 命令 | 通过 SSH persistent shell 执行 |
| `execute_code` | 执行 Python/JS 代码片段 | 写入临时文件 → 通过 SSH 执行 |
| `write_file` | 写文件 | 通过 SSH 写入远程文件系统 |
| `read_file` | 读文件 | 通过 SSH 读取远程文件 |

所有文件操作工具都走同一个 SSH backend，保证一致性。

---

## 六、总结

```
┌─────────────────────────────────────────────────────────────┐
│                    执行链路总结                                │
│                                                             │
│  Skill (SKILL.md)                                           │
│    ↓ 注入到 prompt（Mac 上，纯文本）                          │
│  LLM 推理                                                   │
│    ↓ 生成 tool_call（Mac 上，API 调用）                       │
│  Tool Registry                                              │
│    ↓ 路由到 terminal_tool（Mac 上，Python 代码）              │
│  SSH Backend                                                │
│    ↓ 通过 SSH 发送命令（网络传输）                            │
│  虚拟机 Bash                                                 │
│    ↓ 执行命令，返回输出                                       │
│  Agent 继续循环                                              │
│    ↓ 直到任务完成                                            │
└─────────────────────────────────────────────────────────────┘
```

**一句话总结：** Skill 是 Agent 的"知识"，存在 Mac 上注入到 LLM；LLM 根据知识生成"动作"（tool_call）；动作通过 SSH 在虚拟机上执行。三者解耦，互不依赖。
