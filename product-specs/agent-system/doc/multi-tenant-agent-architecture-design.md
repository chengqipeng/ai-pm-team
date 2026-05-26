# 多租户 Agent 云端部署架构设计

## 业务场景

ToB 产品，多用户通过 Web 入口访问云端 Agent，Agent 的 terminal/file/code 类命令在独立的云端沙盒中执行，需要支持多用户、多对话的完全隔离。

---

## 整体架构

```
┌─────────────────────────────────────────────────────────────────────────┐
│                          用户层                                          │
│                                                                         │
│   👤 用户A (浏览器)    👤 用户B (浏览器)    👤 用户C (浏览器)             │
│        │                    │                    │                      │
└────────┼────────────────────┼────────────────────┼──────────────────────┘
         │                    │                    │
         ▼                    ▼                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                      接入层 (API Gateway)                                │
│                                                                         │
│   • 用户认证 (JWT/OAuth)                                                │
│   • 请求路由                                                            │
│   • 限流/计费                                                           │
│   • WebSocket 长连接管理                                                 │
└────────┬────────────────────┬────────────────────┬──────────────────────┘
         │                    │                    │
         ▼                    ▼                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                      Agent 服务层 (云端节点 A)                            │
│                                                                         │
│   ┌─────────────────────────────────────────────────────────────────┐   │
│   │                  Agent Orchestrator (调度器)                      │   │
│   │                                                                 │   │
│   │  • 会话管理 (session per user per conversation)                  │   │
│   │  • Agent 实例池管理                                              │   │
│   │  • Skill 加载与缓存                                             │   │
│   │  • LLM Provider 路由                                            │   │
│   │  • Tool 分发决策 (本地 vs 远程)                                  │   │
│   └─────────────────────────────────────────────────────────────────┘   │
│                                                                         │
│   ┌───────────────┐  ┌───────────────┐  ┌───────────────┐              │
│   │ Agent 实例 1  │  │ Agent 实例 2  │  │ Agent 实例 N  │              │
│   │ (用户A-对话1) │  │ (用户A-对话2) │  │ (用户B-对话1) │              │
│   │               │  │               │  │               │              │
│   │ • Prompt      │  │ • Prompt      │  │ • Prompt      │              │
│   │ • LLM 调用   │  │ • LLM 调用   │  │ • LLM 调用   │              │
│   │ • 本地 Tools  │  │ • 本地 Tools  │  │ • 本地 Tools  │              │
│   └───────┬───────┘  └───────┬───────┘  └───────┬───────┘              │
│           │                  │                  │                       │
│   ┌───────┴──────────────────┴──────────────────┴───────────────────┐   │
│   │              本地执行的 Tools (无需隔离)                          │   │
│   │                                                                 │   │
│   │  web_search / web_extract / memory / skill_view / vision        │   │
│   │  session_search / todo / delegate_task / mcp_*                  │   │
│   └─────────────────────────────────────────────────────────────────┘   │
│                                                                         │
│   ┌─────────────────────────────────────────────────────────────────┐   │
│   │              共享存储                                             │   │
│   │                                                                 │   │
│   │  PostgreSQL (会话/记忆)  │  Redis (缓存/锁)  │  S3 (文件/产物)  │   │
│   └─────────────────────────────────────────────────────────────────┘   │
└────────────────────────────────┬────────────────────────────────────────┘
                                 │
                                 │  沙盒调度 API
                                 │
                                 ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                      沙盒执行层 (云端节点 B)                              │
│                                                                         │
│   ┌─────────────────────────────────────────────────────────────────┐   │
│   │              Sandbox Manager (沙盒管理器)                         │   │
│   │                                                                 │   │
│   │  • 沙盒生命周期管理 (创建/休眠/唤醒/销毁)                        │   │
│   │  • 资源配额分配 (CPU/内存/磁盘 per 用户)                         │   │
│   │  • 文件同步 (Skills/凭证 → 沙盒)                                │   │
│   │  • 产物回收 (沙盒 → 共享存储)                                    │   │
│   └─────────────────────────────────────────────────────────────────┘   │
│                                                                         │
│   ┌──────────────┐  ┌──────────────┐  ┌──────────────┐                 │
│   │  Sandbox A1  │  │  Sandbox A2  │  │  Sandbox B1  │                 │
│   │  用户A-对话1 │  │  用户A-对话2 │  │  用户B-对话1 │                 │
│   │              │  │              │  │              │                 │
│   │ ┌──────────┐ │  │ ┌──────────┐ │  │ ┌──────────┐ │                 │
│   │ │Container │ │  │ │Container │ │  │ │Container │ │                 │
│   │ │          │ │  │ │          │ │  │ │          │ │                 │
│   │ │ terminal │ │  │ │ terminal │ │  │ │ terminal │ │                 │
│   │ │ file ops │ │  │ │ file ops │ │  │ │ file ops │ │                 │
│   │ │ code exec│ │  │ │ code exec│ │  │ │ code exec│ │                 │
│   │ │          │ │  │ │          │ │  │ │          │ │                 │
│   │ │ CPU: 1核 │ │  │ │ CPU: 1核 │ │  │ │ CPU: 2核 │ │                 │
│   │ │ Mem: 2GB │ │  │ │ Mem: 2GB │ │  │ │ Mem: 4GB │ │                 │
│   │ │ Disk:10G │ │  │ │ Disk:10G │ │  │ │ Disk:20G │ │                 │
│   │ └──────────┘ │  │ └──────────┘ │  │ └──────────┘ │                 │
│   └──────────────┘  └──────────────┘  └──────────────┘                 │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## 核心设计：沙盒隔离模型

### 隔离粒度：每用户每对话一个沙盒

```
用户A ─┬─ 对话1 → Sandbox-A1 (独立容器)
       ├─ 对话2 → Sandbox-A2 (独立容器)
       └─ 对话3 → Sandbox-A3 (独立容器)

用户B ─┬─ 对话1 → Sandbox-B1 (独立容器)
       └─ 对话2 → Sandbox-B2 (独立容器)
```

### 为什么是"每对话"而不是"每用户"

| 粒度 | 优点 | 缺点 |
|------|------|------|
| 每用户一个沙盒 | 资源省、状态共享 | 对话间互相污染、无法并行 |
| **每对话一个沙盒** | **完全隔离、可并行、可独立回滚** | 资源消耗稍多 |
| 每命令一个沙盒 | 最强隔离 | 无状态保持、性能差 |

选择"每对话"是因为：
- 一个对话内的命令需要状态连续（cd、export 保持）
- 不同对话可能做不同项目，不应互相干扰
- 用户可以同时开多个对话并行工作

---

## 沙盒生命周期

```
创建 ──▶ 运行中 ──▶ 空闲 ──▶ 休眠 ──▶ 唤醒 ──▶ 运行中
  │                   │              │
  │                   │ (超时)       │ (用户回来)
  │                   ▼              │
  │               快照保存            │
  │                   │              │
  │                   ▼              │
  │               销毁容器 ──────────┘ (从快照恢复)
  │
  └──▶ 用户主动关闭 ──▶ 产物回收 ──▶ 销毁
```

### 状态管理

| 阶段 | 容器状态 | 文件系统 | 计费 |
|------|----------|----------|------|
| 运行中 | 活跃 | 可读写 | 按秒计费 |
| 空闲 (< 5min) | 活跃但无命令 | 可读写 | 按秒计费 |
| 休眠 (> 5min) | 已停止 | 快照保存到存储 | 仅存储费 |
| 销毁 (> 24h) | 已删除 | 产物归档到 S3 | 无 |

---

## Tool 路由决策

```python
# 伪代码：Agent Orchestrator 中的 Tool 路由逻辑

def route_tool_call(user_id, conversation_id, tool_name, args):

    # 本地执行的 Tools（不需要沙盒）
    LOCAL_TOOLS = {
        "web_search", "web_extract", "web_crawl",
        "vision_analyze", "text_to_speech",
        "memory", "todo", "session_search",
        "skills_list", "skill_view", "skill_manage",
        "delegate_task",
    }

    # 需要沙盒执行的 Tools
    SANDBOX_TOOLS = {
        "terminal", "execute_code",
        "write_file", "read_file", "patch",
        "search_files", "list_directory",
    }

    if tool_name in LOCAL_TOOLS:
        return execute_locally(tool_name, args)

    elif tool_name in SANDBOX_TOOLS:
        # 获取或创建该对话的沙盒
        sandbox = sandbox_manager.get_or_create(
            user_id=user_id,
            conversation_id=conversation_id
        )
        return sandbox.execute(tool_name, args)
```

---

## Sandbox Manager 详细设计

```python
# 伪代码：沙盒管理器

class SandboxManager:

    def get_or_create(self, user_id, conversation_id):
        sandbox_id = f"{user_id}-{conversation_id}"

        # 1. 检查是否有运行中的沙盒
        if sandbox_id in self.running_sandboxes:
            return self.running_sandboxes[sandbox_id]

        # 2. 检查是否有休眠的快照可恢复
        if self.has_snapshot(sandbox_id):
            return self.restore_from_snapshot(sandbox_id)

        # 3. 创建新沙盒
        return self.create_new(sandbox_id, user_id)

    def create_new(self, sandbox_id, user_id):
        # 获取用户的资源配额
        quota = self.get_user_quota(user_id)

        container = docker.create(
            image="agent-sandbox:latest",
            name=sandbox_id,
            # 安全加固
            cap_drop=["ALL"],
            cap_add=["DAC_OVERRIDE", "CHOWN", "FOWNER"],
            security_opt=["no-new-privileges"],
            pids_limit=256,
            # 资源限制（按用户套餐）
            cpu=quota.cpu,           # 1-4 核
            memory=quota.memory,     # 2-8 GB
            disk=quota.disk,         # 10-50 GB
            # 网络隔离
            network="sandbox-net",   # 独立网络命名空间
            # 环境变量（仅白名单）
            env=self.get_allowed_env(user_id),
        )

        # 同步 Skills 和凭证到沙盒
        self.sync_skills(container, user_id)
        self.sync_credentials(container, user_id)

        return Sandbox(container)
```
