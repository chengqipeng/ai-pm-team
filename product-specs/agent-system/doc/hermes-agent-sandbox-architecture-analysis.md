# Hermes Agent 沙盒隔离与分布式部署架构深度分析

> 基于 [NousResearch/hermes-agent](https://github.com/nousresearch/hermes-agent) 源代码和官方文档的深度分析

## 一、整体架构概览

Hermes Agent 采用**"大脑-手脚分离"**的架构设计，核心思想是：

```
┌─────────────────────────────────────────────────────────────────────┐
│                        Entry Points (入口层)                         │
│  CLI (cli.py)    Gateway (gateway/run.py)    ACP (acp_adapter/)     │
│  Batch Runner    API Server                  Python Library          │
└──────────┬──────────────┬───────────────────────┬───────────────────┘
           │              │                       │
           ▼              ▼                       ▼
┌─────────────────────────────────────────────────────────────────────┐
│                     AIAgent (run_agent.py) — "大脑"                  │
│  Prompt Builder  │  Provider Resolution  │  Tool Dispatch            │
└─────────┬─────────────────┬─────────────────────┬───────────────────┘
          │                 │                     │
          ▼                 ▼                     ▼
┌───────────────────┐  ┌──────────────────────────────────────────────┐
│ Session Storage   │  │ Tool Backends — "手脚" (可远程)               │
│ (SQLite + FTS5)   │  │ Terminal (7 backends: local/docker/ssh/       │
│                   │  │          modal/daytona/singularity/vercel)    │
│                   │  │ Browser (5 backends)                          │
│                   │  │ MCP (dynamic)                                 │
└───────────────────┘  └──────────────────────────────────────────────┘
```

**关键设计原则：** 一个 `AIAgent` 类服务于 CLI、Gateway、ACP、Batch 和 API Server 所有入口。平台差异只存在于入口层，不在 Agent 核心。

---

## 二、沙盒隔离的逻辑（深度分析）

### 2.1 七层安全模型

Hermes 采用纵深防御（defense-in-depth）安全模型，共七层：

| 层级 | 安全边界 | 实现位置 |
|------|----------|----------|
| 1 | 用户授权 (allowlists + DM pairing) | `gateway/pairing.py` |
| 2 | 危险命令审批 (human-in-the-loop) | `tools/approval.py` |
| 3 | 容器隔离 (Docker/Singularity/Modal) | `tools/environments/docker.py` |
| 4 | MCP 凭证过滤 | `tools/mcp_tool.py` |
| 5 | 上下文文件注入扫描 | `agent/prompt_builder.py` |
| 6 | 跨会话隔离 | `hermes_state.py` |
| 7 | 输入消毒 (working directory allowlist) | `tools/terminal_tool.py` |

### 2.2 容器隔离的具体实现

#### Docker 后端安全加固 (`tools/environments/docker.py`)

每个容器启动时强制应用以下安全参数：

```python
_SECURITY_ARGS = [
    "--cap-drop", "ALL",                          # 丢弃所有 Linux capabilities
    "--cap-add", "DAC_OVERRIDE",                  # 仅保留：写入 bind-mount 目录
    "--cap-add", "CHOWN",                         # 仅保留：包管理器需要
    "--cap-add", "FOWNER",                        # 仅保留：包管理器需要
    "--security-opt", "no-new-privileges",        # 阻止提权
    "--pids-limit", "256",                        # 限制进程数
    "--tmpfs", "/tmp:rw,nosuid,size=512m",        # 大小受限的 /tmp
    "--tmpfs", "/var/tmp:rw,noexec,nosuid,size=256m",  # 不可执行的 /var/tmp
    "--tmpfs", "/run:rw,noexec,nosuid,size=64m",  # 不可执行的 /run
]
```

#### 资源限制（可配置）

```yaml
terminal:
  backend: docker
  docker_image: "nikolaik/python-nodejs:python3.11-nodejs20"
  docker_forward_env: []       # 空 = 不泄露任何宿主环境变量
  container_cpu: 1             # CPU 核心数
  container_memory: 5120       # MB (默认 5GB)
  container_disk: 51200        # MB (默认 50GB)
  container_persistent: true   # 跨会话持久化文件系统
```

#### 文件系统持久化策略

- **持久模式** (`container_persistent: true`)：Bind-mount `/workspace` 和 `/root` 到 `~/.hermes/sandboxes/docker/<task_id>/`
- **临时模式** (`container_persistent: false`)：使用 tmpfs，容器清理后一切丢失

### 2.3 环境变量隔离机制

这是沙盒隔离中最精细的部分：

| 沙盒类型 | 默认行为 | Passthrough 机制 |
|----------|----------|------------------|
| `execute_code` | 阻止名称含 KEY/TOKEN/SECRET/PASSWORD 的变量 | Skill 声明的变量可穿透 |
| `terminal` (local) | 阻止 Hermes 基础设施变量 | Passthrough 变量绕过黑名单 |
| `terminal` (Docker) | 默认不传递任何宿主变量 | `docker_forward_env` + Skill 声明变量 |
| `terminal` (Modal) | 默认不传递任何宿主变量/文件 | 凭证文件挂载 + env sync |
| MCP | 仅传递 PATH/HOME/USER/LANG 等安全变量 | 仅 MCP 配置中显式声明的 env |

### 2.4 危险命令审批流程

```
命令提交 → UNRECOVERABLE_BLOCKLIST 检查（绝对拒绝）
         → DANGEROUS_PATTERNS 正则匹配
         → 容器后端？ → 跳过审批（容器本身是安全边界）
         → 本地后端？ → 触发审批回调
              → CLI: 交互式 [o]nce/[s]ession/[a]lways/[d]eny
              → Gateway: 发送到聊天等待用户回复
              → Smart: 辅助 LLM 评估风险自动决策
```

**关键设计：** 当使用 docker/singularity/modal/daytona/vercel_sandbox 后端时，危险命令检查被**完全跳过**，因为容器本身就是安全边界。

### 2.5 不可恢复操作黑名单（Hardline Blocklist）

即使开启 `--yolo` 模式，以下操作也**永远被拒绝**：

- `rm -rf /` 及其变体
- Fork bomb (`:(){ :|:& };:`)
- `mkfs.*` 格式化已挂载根设备
- `dd if=/dev/zero of=/dev/sd*`
- 管道远程脚本到 shell

---

## 三、Terminal Backend 与 Agent 大脑的分离部署

### 3.1 架构核心：Backend 抽象层

Terminal 系统通过 `tools/environments/` 目录下的后端实现，将"命令执行"从"决策推理"中完全解耦：

```
tools/environments/
├── local.py          # 本地执行
├── docker.py         # Docker 容器执行
├── ssh.py            # SSH 远程执行
├── modal.py          # Modal 云沙盒
├── daytona.py        # Daytona 云工作区
├── singularity.py    # HPC 容器
└── vercel_sandbox.py # Vercel 微虚拟机
```

### 3.2 分离部署模式

#### 模式 A：SSH 后端 — Agent 大脑与执行环境在不同机器

```
┌─────────────────────┐         SSH          ┌─────────────────────┐
│  Machine A (大脑)    │ ──────────────────▶  │  Machine B (手脚)    │
│                     │                      │                     │
│  - AIAgent          │                      │  - 命令执行          │
│  - Gateway          │                      │  - 文件操作          │
│  - Session DB       │                      │  - 代码运行          │
│  - LLM API 调用     │                      │  - 浏览器自动化      │
└─────────────────────┘                      └─────────────────────┘
```

配置方式：
```yaml
# ~/.hermes/config.yaml
terminal:
  backend: ssh

# ~/.hermes/.env (凭证不放 config.yaml，避免被 profile export 泄露)
TERMINAL_SSH_HOST=agent-worker.local
TERMINAL_SSH_USER=hermes
TERMINAL_SSH_KEY=~/.ssh/hermes_agent_key
```

#### 模式 B：Docker 后端 — 同机隔离

Agent 大脑在宿主机运行，所有命令在一个**长生命周期的 Docker 容器**中执行。该容器：
- 跨 tool call 存活
- 跨 `/new` 命令存活
- 跨 subagent 存活
- 仅在 Hermes 进程结束时销毁

#### 模式 C：Modal/Daytona — 无服务器云沙盒

```
┌─────────────────────┐       API Call       ┌─────────────────────┐
│  本地/VPS (大脑)     │ ──────────────────▶  │  Modal/Daytona 云    │
│                     │                      │                     │
│  - AIAgent          │                      │  - 按需启动沙盒      │
│  - 推理决策         │                      │  - 空闲时休眠        │
│  - 会话管理         │                      │  - 几乎零成本        │
└─────────────────────┘                      └─────────────────────┘
```

特点：
- **Daytona**：持久化云工作区，休眠时不计费
- **Modal**：无服务器沙盒，按秒计费，自动扩缩
- **Vercel Sandbox**：微虚拟机 + 快照持久化

### 3.3 跨机器部署时的 Skill/凭证同步

当 Terminal Backend 在远程时，Hermes 自动处理文件同步：

| 后端 | Skill 同步方式 | 凭证文件同步方式 |
|------|---------------|-----------------|
| Docker | Bind-mount `~/.hermes/skills/` (只读) | `-v host:container:ro` |
| SSH | rsync 上传 | rsync 上传 |
| Modal | Modal mount API | 每次命令前 sync |
| Local | 直接访问 | 直接访问 |

### 3.4 Gateway 作为"大脑"的网络入口

Gateway (`gateway/run.py`) 是一个长运行进程，负责：
1. 接收 20 个平台的消息（Telegram/Discord/Slack/WhatsApp/Signal 等）
2. 路由到正确的 session
3. 创建 AIAgent 实例处理消息
4. 将响应通过 adapter 回传

```
Telegram ─┐
Discord  ─┤
Slack    ─┼──▶ GatewayRunner._handle_message()
WhatsApp ─┤         │
Signal   ─┘         ▼
              AIAgent.run_conversation()
                     │
                     ▼
              Terminal Backend (local/docker/ssh/modal/...)
```

---

## 四、Skill 的部署位置

### 4.1 Skill 存储架构

```
~/.hermes/skills/                  ← 主目录，唯一真实来源 (source of truth)
├── mlops/                         ← 分类目录
│   ├── axolotl/
│   │   ├── SKILL.md               ← 主指令文件（必需）
│   │   ├── references/            ← 参考文档
│   │   ├── templates/             ← 输出模板
│   │   ├── scripts/               ← 可调用脚本
│   │   └── assets/                ← 补充文件
│   └── vllm/
│       └── SKILL.md
├── .hub/                          ← Skills Hub 状态
│   ├── lock.json
│   ├── quarantine/
│   └── audit.log
└── .bundled_manifest              ← 跟踪已同步的 bundled skills
```

### 4.2 三类 Skill 来源

| 类型 | 位置 | 说明 |
|------|------|------|
| **Bundled Skills** | 源码 `skills/` → 安装时复制到 `~/.hermes/skills/` | 随 Hermes 发行，每次 `hermes update` 同步 |
| **Optional Skills** | 源码 `optional-skills/` → 通过 `hermes skills install official/...` 安装 | 官方维护但需显式安装 |
| **Hub/Community Skills** | 从 agentskills.io / skills.sh / GitHub 等安装到 `~/.hermes/skills/` | 第三方，经安全扫描 |
| **Agent 自创 Skills** | Agent 通过 `skill_manage` 工具创建到 `~/.hermes/skills/` | Agent 的程序性记忆 |

### 4.3 Skill 的运行时加载机制（渐进式披露）

```
Level 0: skills_list()           → 仅返回 [{name, description, category}]  (~3k tokens)
Level 1: skill_view(name)        → 完整 SKILL.md 内容 + 元数据
Level 2: skill_view(name, path)  → 特定引用文件内容
```

Agent 只在**真正需要时**才加载完整 Skill 内容，最小化 token 消耗。

### 4.4 Skill 在沙盒中的可用性

当使用远程 Terminal Backend 时：
- **Docker**：`~/.hermes/skills/` 被 bind-mount 为只读卷到容器内
- **SSH**：通过 rsync 在每次命令前上传
- **Modal**：通过 Modal mount API 挂载

Skill 中声明的 `required_environment_variables` 会自动穿透到沙盒环境：

```yaml
# SKILL.md frontmatter
required_environment_variables:
  - name: TENOR_API_KEY
    prompt: Tenor API key
    help: Get a key from https://developers.google.com/tenor
```

### 4.5 外部 Skill 目录

支持指向 Hermes 外部的 Skill 目录（如团队共享目录）：

```yaml
# ~/.hermes/config.yaml
skills:
  external_dirs:
    - ~/.agents/skills
    - /home/shared/team-skills
    - ${SKILLS_REPO}/skills
```

---

## 五、关键设计洞察总结

### 5.1 "大脑"与"手脚"的解耦设计

| 组件 | 部署位置 | 职责 |
|------|----------|------|
| AIAgent (大脑) | 任意机器（VPS/本地/容器内） | LLM 调用、决策、会话管理、记忆 |
| Terminal Backend (手脚) | 可与大脑同机或异机 | 命令执行、文件操作、代码运行 |
| Gateway (耳朵/嘴巴) | 与大脑同进程 | 接收/发送消息到各平台 |
| Skills (知识) | `~/.hermes/skills/` + 自动同步到沙盒 | 程序性记忆，按需加载 |

### 5.2 沙盒隔离的核心哲学

> **"容器后端时，容器本身就是安全边界，不需要命令级审批。"**

这意味着：
- 本地后端 → 依赖 DANGEROUS_PATTERNS + 用户审批
- 容器后端 → 依赖容器隔离 + capability 限制 + 资源限制
- 两者互补，不重叠

### 5.3 对我们 aPaaS 平台的启示

1. **Terminal Backend 抽象层**是实现多租户隔离的关键模式 — 每个租户可以有独立的执行环境
2. **Skill 的渐进式加载**是控制 LLM token 成本的有效策略
3. **环境变量白名单机制**比黑名单更安全 — Docker 后端默认不传递任何变量
4. **凭证文件只读挂载**防止沙盒内代码篡改凭证
5. **SSH 后端模式**天然支持"大脑在云端，执行在客户环境"的部署拓扑

---

## 参考来源

- [Hermes Agent Architecture](https://hermes-agent.nousresearch.com/docs/developer-guide/architecture)
- [Tools Runtime](https://hermes-agent.nousresearch.com/docs/developer-guide/tools-runtime)
- [Security](https://hermes-agent.nousresearch.com/docs/user-guide/security)
- [Docker Guide](https://hermes-agent.nousresearch.com/docs/zh-Hans/user-guide/docker)
- [Skills System](https://hermes-agent.nousresearch.com/docs/user-guide/features/skills)
- [Agent Loop Internals](https://hermes-agent.nousresearch.com/docs/developer-guide/agent-loop)

Content was rephrased for compliance with licensing restrictions.
