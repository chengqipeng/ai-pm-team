# Hermes Agent — Create Skill 能力详解

> 基于 [NousResearch/hermes-agent](https://github.com/nousresearch/hermes-agent) 源码 `tools/skill_manager_tool.py`、Skills System 文档、Prompt Assembly 文档深度分析。

---

## 一、Create Skill 在整体架构中的位置

```
┌─────────────────────────────────────────────────────────────────────┐
│                     AIAgent (run_agent.py)                           │
│                                                                     │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐              │
│  │ Prompt       │  │ Agent Loop   │  │ Tool         │              │
│  │ Builder      │  │ (对话循环)    │  │ Dispatch     │              │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘              │
│         │                  │                  │                      │
│         │                  │                  ▼                      │
│         │                  │         ┌──────────────────┐           │
│         │                  │         │ skill_manage()   │ ◄── 核心  │
│         │                  │         │ (创建/修补/删除)  │           │
│         │                  │         └────────┬─────────┘           │
│         │                  │                  │                      │
│         ▼                  ▼                  ▼                      │
│  ┌─────────────────────────────────────────────────────────┐        │
│  │              ~/.hermes/skills/ (持久化存储)               │        │
│  │  SKILL.md + references/ + templates/ + scripts/          │        │
│  └─────────────────────────────────────────────────────────┘        │
└─────────────────────────────────────────────────────────────────────┘
```

**Create Skill 是 Hermes 自我改进闭环的核心执行器** — 它将 Agent 在对话中积累的经验转化为可复用的程序性知识。

---

## 二、触发机制：什么时候创建 Skill

### 2.1 系统提示中的创建指令

在 `SKILL_MANAGE_SCHEMA` 的 description 中，明确定义了创建时机：

```
Create when:
- 复杂任务成功完成（5+ 次工具调用）
- 克服了错误/异常后找到了正确路径
- 用户纠正后的方法有效
- 发现了非平凡的工作流
- 用户明确要求记住某个流程
```

### 2.2 Memory Nudge 触发（每 10 轮自省）

每 10 轮对话，Agent 运行内部审查，评估：
1. 是否有值得保存到长期记忆的偏好/事实？
2. **是否有可以抽象为可复用技能的工作流？**
3. 是否有需要更新的现有技能？

### 2.3 后台自我改进审查 (Background Self-Improvement Review)


源码中有一个关键的溯源区分：

```python
# tools/skill_manager_tool.py 中的 provenance 逻辑
from tools.skill_provenance import is_background_review

if action == "create":
    if is_background_review():
        mark_agent_created(name)  # 标记为 agent 自主创建
```

- **前台创建**（用户指导）：用户在对话中要求 Agent 创建 Skill → 属于用户
- **后台创建**（自主反思）：Background Review Fork 自主决定创建 → 标记为 `agent-created`，受 Curator 管理

### 2.4 任务完成后的主动提议

系统提示中明确要求：

> "After difficult/iterative tasks, offer to save as a skill. Skip for simple one-offs. Confirm with user before creating/deleting."

Agent 在完成复杂任务后会**主动询问用户**是否要保存为 Skill，而非静默创建。

---

## 三、Create Skill 的完整执行流程

### 3.1 Tool Schema 定义

```python
SKILL_MANAGE_SCHEMA = {
    "name": "skill_manage",
    "description": "Manage skills (create, update, delete)...",
    "parameters": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["create", "patch", "edit", "delete", "write_file", "remove_file"]
            },
            "name": {
                "type": "string",
                "description": "Skill name (lowercase, hyphens/underscores, max 64 chars)"
            },
            "content": {
                "type": "string",
                "description": "Full SKILL.md content (YAML frontmatter + markdown body)"
            },
            "category": {
                "type": "string",
                "description": "Optional category for organizing (e.g., 'devops', 'data-science')"
            },
            ...
        },
        "required": ["action", "name"],
    },
}
```

### 3.2 创建流程详解 (`_create_skill` 函数)

```python
def _create_skill(name: str, content: str, category: str = None) -> Dict[str, Any]:
    """Create a new user skill with SKILL.md content."""
    
    # ===== Step 1: 名称验证 =====
    err = _validate_name(name)
    # 规则: lowercase, hyphens/underscores, max 64 chars
    # 正则: ^[a-z0-9][a-z0-9._-]*$
    
    # ===== Step 2: 分类验证 =====
    err = _validate_category(category)
    # 单层目录名，不允许 / 或 \
    
    # ===== Step 3: 内容验证 — Frontmatter =====
    err = _validate_frontmatter(content)
    # 必须以 --- 开头
    # 必须有闭合的 ---
    # YAML 必须可解析
    # 必须包含 'name' 字段
    # 必须包含 'description' 字段 (≤1024 chars)
    # frontmatter 后必须有正文内容
    
    # ===== Step 4: 内容大小验证 =====
    err = _validate_content_size(content)
    # 上限: 100,000 字符 (~36k tokens at 2.75 chars/token)
    
    # ===== Step 5: 名称冲突检查 =====
    existing = _find_skill(name)
    # 搜索所有 skill 目录（本地 + external_dirs）
    # 如果同名 skill 已存在，拒绝创建
    
    # ===== Step 6: 创建目录结构 =====
    skill_dir = _resolve_skill_dir(name, category)
    # 如果有 category: ~/.hermes/skills/{category}/{name}/
    # 如果没有:       ~/.hermes/skills/{name}/
    skill_dir.mkdir(parents=True, exist_ok=True)
    
    # ===== Step 7: 原子写入 SKILL.md =====
    skill_md = skill_dir / "SKILL.md"
    _atomic_write_text(skill_md, content)
    # 使用临时文件 + os.replace() 确保原子性
    # 进程崩溃不会留下半写文件
    
    # ===== Step 8: 安全扫描 =====
    scan_error = _security_scan_skill(skill_dir)
    if scan_error:
        shutil.rmtree(skill_dir, ignore_errors=True)  # 回滚
        return {"success": False, "error": scan_error}
    # 检查: 数据外泄、提示注入、破坏性命令、供应链信号
    # 注意: 默认关闭 (skills.guard_agent_created: false)
    # 因为 Agent 已经可以通过 terminal() 执行相同代码
    
    # ===== Step 9: 清除 Prompt 缓存 =====
    clear_skills_system_prompt_cache(clear_snapshot=True)
    # 新 skill 需要在下次会话中出现在 skills index 中
    
    # ===== Step 10: 遥测标记 =====
    if is_background_review():
        mark_agent_created(name)  # Curator 可管理
    
    # ===== Step 11: 返回结果 =====
    return {
        "success": True,
        "message": f"Skill '{name}' created.",
        "path": str(skill_dir.relative_to(SKILLS_DIR)),
        "skill_md": str(skill_md),
        "hint": "To add reference files, use skill_manage(action='write_file', ...)"
    }
```


### 3.3 原子写入机制

```python
def _atomic_write_text(file_path: Path, content: str, encoding: str = "utf-8") -> None:
    """
    原子写入文本内容到文件。
    使用临时文件 + os.replace() 确保目标文件永远不会处于半写状态。
    """
    file_path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_path = tempfile.mkstemp(
        dir=str(file_path.parent),
        prefix=f".{file_path.name}.tmp.",
        suffix="",
    )
    try:
        with os.fdopen(fd, "w", encoding=encoding) as f:
            f.write(content)
        atomic_replace(temp_path, file_path)  # os.replace — 原子操作
    except Exception:
        try:
            os.unlink(temp_path)  # 清理临时文件
        except OSError:
            logger.error("Failed to remove temporary file %s", temp_path)
        raise
```

**设计意图**：即使进程在写入过程中崩溃，SKILL.md 也不会处于损坏状态。

---

## 四、SKILL.md 的内容规范

### 4.1 必须的 Frontmatter 结构

```yaml
---
name: deploy-k8s-service          # 必须，lowercase + hyphens
description: Deploy a containerized service to Kubernetes  # 必须，≤1024 chars
version: 1.0.0                    # 推荐
author: Hermes Agent              # 推荐
license: MIT                      # 可选
platforms: [macos, linux]         # 可选，限制 OS
metadata:
  hermes:
    tags: [kubernetes, deployment, devops]  # 可选
    category: devops                        # 可选
    requires_toolsets: [terminal]           # 可选，条件激活
    fallback_for_toolsets: [browser]        # 可选，条件隐藏
    config:                                 # 可选，配置项
      - key: k8s.namespace
        description: "Default Kubernetes namespace"
        default: "default"
        prompt: "Enter your default K8s namespace"
required_environment_variables:             # 可选，环境变量
  - name: KUBECONFIG
    prompt: "Path to kubeconfig file"
    help: "Usually at ~/.kube/config"
    required_for: "Kubernetes cluster access"
---
```

### 4.2 推荐的正文结构

```markdown
# Deploy K8s Service

Brief intro — one sentence describing what this skill does.

## When to Use
- User asks to deploy a service to Kubernetes
- User mentions "k8s", "kubectl", "pod", "deployment"
- After a Docker image has been built and needs to go live

## Quick Reference
| Command | Purpose |
|---------|---------|
| kubectl apply -f | Apply a manifest |
| kubectl rollout status | Check deployment progress |
| kubectl logs -f | Stream pod logs |

## Procedure
1. Verify kubectl is configured: `kubectl cluster-info`
2. Check if namespace exists: `kubectl get ns ${namespace}`
3. If not, create it: `kubectl create ns ${namespace}`
4. Build the deployment manifest (see templates/)
5. Apply: `kubectl apply -f deployment.yaml`
6. Wait for rollout: `kubectl rollout status deployment/${name} -n ${namespace}`
7. Verify pods are running: `kubectl get pods -n ${namespace} -l app=${name}`

## Pitfalls
- **ImagePullBackOff**: Check image name/tag, verify registry credentials
- **CrashLoopBackOff**: Check logs with `kubectl logs`, likely app startup failure
- **Pending pods**: Check node resources with `kubectl describe node`
- **Service not reachable**: Verify service type (ClusterIP vs LoadBalancer)

## Verification
Run `kubectl get all -n ${namespace} -l app=${name}` and confirm:
- Deployment shows READY = desired count
- Pods show STATUS = Running
- Service has an EXTERNAL-IP (if LoadBalancer type)
```

### 4.3 系统提示中对 Skill 质量的要求

源码中 `SKILL_MANAGE_SCHEMA` 的 description 明确指出好的 Skill 应该包含：

> "Good skills: trigger conditions, numbered steps with exact commands, pitfalls section, verification steps."

即：
1. **触发条件** — 什么时候应该使用这个 Skill
2. **编号步骤 + 精确命令** — 不是模糊描述，而是可直接执行的指令
3. **陷阱/坑** — 已知的失败模式和修复方法
4. **验证步骤** — 如何确认操作成功

---

## 五、Skill 的生命周期管理

### 5.1 创建后的即时效果

```python
# 创建成功后立即清除 prompt 缓存
from agent.prompt_builder import clear_skills_system_prompt_cache
clear_skills_system_prompt_cache(clear_snapshot=True)
```

- 新 Skill 在**下一个会话**中自动出现在 Skills Index 中
- 当前会话中不会自动加载（保护 prompt caching）
- 用户可以用 `/reset` 强制刷新当前会话

### 5.2 Skills Index 在系统提示中的呈现


根据 Prompt Assembly 文档，Skills Index 是系统提示的第 7 层：

```
## Skills (mandatory)
Before replying, scan the skills below. If one clearly matches
your task, load it with skill_view(name) and follow its instructions.
...
<available_skills>
  software-development:
    - code-review: Structured code review workflow
    - test-driven-development: TDD methodology
  devops:
    - deploy-k8s-service: Deploy a containerized service to Kubernetes  ← 新创建的
  research:
    - arxiv: Search and summarize arXiv papers
</available_skills>
```

**渐进式加载 (Progressive Disclosure)**：

```
Level 0: skills_list()           → [{name, description, category}, ...]  (~3k tokens)
Level 1: skill_view(name)        → Full SKILL.md content                 (varies)
Level 2: skill_view(name, path)  → Specific reference file               (varies)
```

Agent 只在需要时才加载完整 Skill 内容，避免 token 浪费。

### 5.3 使用遥测追踪

```json
// ~/.hermes/skills/.usage.json
{
  "deploy-k8s-service": {
    "use_count": 0,        // skill 被加载到对话 prompt 的次数
    "view_count": 0,       // agent 调用 skill_view 的次数
    "patch_count": 0,      // skill_manage patch/edit 的次数
    "last_used_at": null,
    "last_viewed_at": null,
    "last_patched_at": null,
    "created_at": "2026-05-22T10:30:00Z",
    "state": "active",
    "pinned": false,
    "archived_at": null
  }
}
```

遥测计数器递增时机：
- `view_count`：Agent 调用 `skill_view` 查看该 Skill
- `use_count`：Skill 被加载到对话的 prompt 中
- `patch_count`：`skill_manage` 的 patch/edit/write_file/remove_file 操作

### 5.4 Curator 生命周期管理

对于 `agent-created` 的 Skill：

```
active ──(30天未使用)──► stale ──(90天未使用)──► archived
                                                    │
                                                    ▼
                                        ~/.hermes/skills/.archive/
                                        (可通过 hermes curator restore 恢复)
```

- **永不自动删除**，最严重操作是归档
- 每次 Curator 运行前自动备份整个 skills 目录
- Pin 保护的 Skill 不受 Curator 影响

---

## 六、Skill 的自我改进机制

### 6.1 即时修补 (Patch on Use)

系统提示中的关键指令：

> "If you used a skill and hit issues not covered by it, patch it immediately."

当 Agent 使用某个 Skill 但遇到了 Skill 未覆盖的问题时，**立即修补**：

```python
def _patch_skill(name, old_string, new_string, file_path=None, replace_all=False):
    """Targeted find-and-replace within a skill file."""
    
    # 1. 查找 Skill
    existing = _find_skill(name)
    
    # 2. 确定目标文件（默认 SKILL.md，可指定 supporting file）
    target = skill_dir / "SKILL.md" if not file_path else skill_dir / file_path
    
    # 3. 模糊匹配引擎（容忍空白差异、缩进差异、转义序列）
    from tools.fuzzy_match import fuzzy_find_and_replace
    new_content, match_count, _strategy, match_error = fuzzy_find_and_replace(
        content, old_string, new_string, replace_all
    )
    
    # 4. 验证修改后的 frontmatter 仍然完整
    if not file_path:
        err = _validate_frontmatter(new_content)
    
    # 5. 原子写入 + 安全扫描
    _atomic_write_text(target, new_content)
    scan_error = _security_scan_skill(skill_dir)
    if scan_error:
        _atomic_write_text(target, original_content)  # 回滚
    
    # 6. 遥测: bump patch_count
    bump_patch(name)
```

**模糊匹配**是关键设计 — Agent 不需要精确匹配原文的每个空格和缩进，`fuzzy_find_and_replace` 处理了：
- 空白规范化
- 缩进差异
- 转义序列
- 块锚点匹配

### 6.2 支撑文件系统 (Supporting Files)

Skill 不仅仅是一个 SKILL.md，还可以包含完整的文件结构：

```
my-skill/
├── SKILL.md                    # 主指令文件
├── references/                 # 参考文档（API 文档、规范等）
│   ├── api-docs.md
│   └── examples.md
├── templates/                  # 模板文件（配置模板、代码模板等）
│   └── deployment.yaml
├── scripts/                    # 可执行脚本
│   └── setup.sh
└── assets/                     # 补充资源
    └── diagram.png
```

通过 `skill_manage(action='write_file')` 添加支撑文件：

```python
skill_manage(
    action="write_file",
    name="deploy-k8s-service",
    file_path="templates/deployment.yaml",
    file_content="apiVersion: apps/v1\nkind: Deployment\n..."
)
```

限制：
- 文件必须在 `references/`、`templates/`、`scripts/`、`assets/` 之一下
- 单文件上限 1 MiB
- 内容上限 100,000 字符
- 路径遍历防护（禁止 `..`）

### 6.3 模板变量替换

SKILL.md 中可以使用模板变量，加载时自动替换：

| 变量 | 含义 |
|------|------|
| `${HERMES_SKILL_DIR}` | Skill 目录的绝对路径 |
| `${HERMES_SESSION_ID}` | 当前会话 ID |

```markdown
To analyse the input, run:
    node ${HERMES_SKILL_DIR}/scripts/analyse.js <input>
```

Agent 看到的是替换后的绝对路径，可以直接通过 `terminal` 工具执行。


### 6.4 离线进化优化 (GEPA)

通过 `hermes-agent-self-evolution` 项目，Skill 可以被离线进化优化：

```bash
# 使用合成评估数据进化一个 Skill
python -m evolution.skills.evolve_skill \
    --skill deploy-k8s-service \
    --iterations 10 \
    --eval-source synthetic

# 使用真实会话历史进化
python -m evolution.skills.evolve_skill \
    --skill deploy-k8s-service \
    --iterations 10 \
    --eval-source sessiondb
```

进化过程：
1. 读取当前 SKILL.md
2. 生成评估数据集（合成 or 从 Session DB 导入）
3. GEPA 优化器读取执行轨迹，理解**为什么**失败
4. 提出候选变体
5. 通过约束门控（测试、大小限制 ≤15KB、语义保持）
6. 最佳变体提交 PR 供人工审查

---

## 七、安全机制

### 7.1 名称验证

```python
VALID_NAME_RE = re.compile(r'^[a-z0-9][a-z0-9._-]*$')
MAX_NAME_LENGTH = 64
```

- 只允许小写字母、数字、连字符、下划线、点
- 必须以字母或数字开头
- 最长 64 字符

### 7.2 内容大小限制

| 限制项 | 值 | 说明 |
|--------|-----|------|
| SKILL.md 内容 | 100,000 chars | ~36k tokens |
| 支撑文件 | 1 MiB (1,048,576 bytes) | 单文件 |
| Description | 1,024 chars | Frontmatter 中 |

### 7.3 安全扫描 (Security Guard)

```python
def _security_scan_skill(skill_dir: Path) -> Optional[str]:
    """扫描 skill 目录。如果被阻止返回错误字符串，否则返回 None。"""
    if not _GUARD_AVAILABLE:
        return None
    if not _guard_agent_created_enabled():
        return None  # 默认关闭
    
    result = scan_skill(skill_dir, source="agent-created")
    allowed, reason = should_allow_install(result)
    
    if allowed is False:
        # 危险发现 → 回滚创建
        return f"Security scan blocked this skill ({reason}):\n{report}"
    if allowed is None:
        # "ask" 判定 → 对 agent-created 视为阻止
        return f"Security scan blocked this skill ({reason}):\n{report}"
```

扫描检查项：
- **数据外泄模式** — 尝试将数据发送到外部
- **提示注入** — 试图覆盖系统指令
- **破坏性命令** — rm -rf、格式化磁盘等
- **供应链信号** — 可疑的依赖或下载

**默认关闭的原因**：Agent 已经可以通过 `terminal()` 工具执行相同的代码路径，扫描只增加摩擦而不增加实际安全性。用户可以通过 `hermes config set skills.guard_agent_created true` 开启。

### 7.4 路径安全

```python
from tools.path_security import has_traversal_component, validate_within_dir

# 禁止路径遍历
if has_traversal_component(file_path):  # 检测 ..
    return "Path traversal ('..') is not allowed."

# 确保文件在 skill 目录内
error = validate_within_dir(target, skill_dir)
```

### 7.5 Pin 保护

```python
def _pinned_guard(name: str) -> Optional[str]:
    """如果 skill 被 pin 保护，拒绝删除。"""
    rec = skill_usage.get_record(name)
    if rec.get("pinned"):
        return (
            f"Skill '{name}' is pinned and cannot be deleted. "
            f"Ask the user to run `hermes curator unpin {name}`."
        )
```

- Pin 只保护**删除**操作
- Patch 和 Edit 仍然允许（Skill 可以被改进）
- 设计哲学：保护不可逆操作，允许可逆改进

---

## 八、条件激活与发现机制

### 8.1 平台限制

```yaml
platforms: [macos, linux]  # 只在这些 OS 上显示
```

不匹配的平台上，Skill 自动从系统提示、`skills_list()`、斜杠命令中隐藏。

### 8.2 工具集依赖

```yaml
metadata:
  hermes:
    requires_toolsets: [web]           # 只在 web 工具集可用时显示
    requires_tools: [web_search]       # 只在特定工具可用时显示
    fallback_for_toolsets: [browser]   # 只在 browser 不可用时显示（降级方案）
    fallback_for_tools: [browser_navigate]
```

典型用例：`duckduckgo-search` Skill 设置 `fallback_for_toolsets: [web]`，当用户没有配置 `FIRECRAWL_API_KEY` 时自动出现作为免费替代。

### 8.3 环境变量声明

```yaml
required_environment_variables:
  - name: KUBECONFIG
    prompt: "Path to kubeconfig"
    help: "Usually at ~/.kube/config"
    required_for: "Kubernetes cluster access"
```

- 缺失的环境变量**不会隐藏** Skill
- 在本地 CLI 加载时安全提示输入
- 设置后自动传递到 `execute_code` 和 `terminal` 沙箱
- Gateway/消息平台不会在聊天中收集密钥

### 8.4 配置项声明

```yaml
metadata:
  hermes:
    config:
      - key: k8s.namespace
        description: "Default Kubernetes namespace"
        default: "default"
        prompt: "Enter your default K8s namespace"
```

- 存储在 `config.yaml` 的 `skills.config` 下
- Skill 加载时自动注入到上下文中
- Agent 无需读取 config.yaml 即可知道配置值

---

## 九、与其他子系统的交互

### 9.1 与 Prompt Builder 的交互

```
创建 Skill → clear_skills_system_prompt_cache()
                    │
                    ▼
下次会话 → prompt_builder.py 重新构建 Skills Index
                    │
                    ▼
新 Skill 出现在系统提示的 <available_skills> 中
```

### 9.2 与 Session Search 的交互

Agent 可以通过 `session_search` 工具搜索过去的会话，找到曾经解决过的问题，然后将解决方案提炼为 Skill。

### 9.3 与 Delegation 的交互

子 Agent（通过 `delegate_task` 生成）**不能**创建 Skill：
- 子 Agent 使用 `skip_context_files` 模式
- 子 Agent 的工具集是父 Agent 的子集
- 只有主 Agent 或后台审查 Fork 可以创建 Skill

### 9.4 与 Cron 的交互

Cron 任务可以引用 Skill：
```yaml
# cron job 配置
skills: [deploy-k8s-service]  # 任务执行时加载这些 Skill
```

如果 Curator 归档了一个被 Cron 引用的 Skill，rename map 会记录变更，方便追踪。

---

## 十、完整的数据流图

```
┌─────────────────────────────────────────────────────────────────────────┐
│                        Skill 创建的完整数据流                             │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  ┌──────────┐     ┌──────────────┐     ┌──────────────┐               │
│  │ 触发源   │     │ 验证层       │     │ 持久化层     │               │
│  │          │     │              │     │              │               │
│  │ • 用户   │     │ • 名称校验   │     │ • 原子写入   │               │
│  │   请求   │────►│ • 内容校验   │────►│ • 目录创建   │               │
│  │ • Memory │     │ • 大小限制   │     │ • 安全扫描   │               │
│  │   Nudge  │     │ • 冲突检查   │     │ • 遥测记录   │               │
│  │ • 后台   │     │ • Frontmatter│     │              │               │
│  │   Review │     │   解析       │     │              │               │
│  └──────────┘     └──────────────┘     └──────┬───────┘               │
│                                                │                       │
│                                                ▼                       │
│  ┌──────────────────────────────────────────────────────────┐         │
│  │                 ~/.hermes/skills/{category}/{name}/        │         │
│  │                                                           │         │
│  │  SKILL.md          references/     templates/   scripts/  │         │
│  │  (主指令)          (参考文档)      (模板)       (脚本)    │         │
│  └──────────────────────────────────┬───────────────────────┘         │
│                                     │                                  │
│              ┌──────────────────────┼──────────────────────┐          │
│              ▼                      ▼                      ▼          │
│  ┌───────────────┐    ┌───────────────┐    ┌───────────────┐         │
│  │ Prompt Cache  │    │ .usage.json   │    │ Curator       │         │
│  │ 清除          │    │ 遥测追踪      │    │ 生命周期管理  │         │
│  │               │    │               │    │               │         │
│  │ 下次会话      │    │ use_count     │    │ active→stale  │         │
│  │ 自动加载      │    │ view_count    │    │ →archived     │         │
│  │ 到 Skills     │    │ patch_count   │    │               │         │
│  │ Index         │    │ state         │    │ 7天/30天/90天 │         │
│  └───────────────┘    └───────────────┘    └───────────────┘         │
│                                                                        │
│              ┌─────────────────────────────────────────┐              │
│              │         使用阶段                         │              │
│              │                                         │              │
│              │  skills_list() → skill_view(name)       │              │
│              │       │              │                   │              │
│              │       ▼              ▼                   │              │
│              │  ~3k tokens    Full SKILL.md loaded     │              │
│              │  (索引)        (按需加载)               │              │
│              │                      │                   │              │
│              │                      ▼                   │              │
│              │              Agent 按步骤执行            │              │
│              │                      │                   │              │
│              │                      ▼                   │              │
│              │              遇到问题？                  │              │
│              │              ├── Yes → patch 即时修补    │              │
│              │              └── No  → 完成，bump use   │              │
│              └─────────────────────────────────────────┘              │
│                                                                        │
│              ┌─────────────────────────────────────────┐              │
│              │         进化阶段 (离线)                  │              │
│              │                                         │              │
│              │  Session DB → 评估数据集                 │              │
│              │       │                                  │              │
│              │       ▼                                  │              │
│              │  GEPA 反思式进化                         │              │
│              │       │                                  │              │
│              │       ▼                                  │              │
│              │  候选变体 → 约束门控 → PR 审查           │              │
│              └─────────────────────────────────────────┘              │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## 十一、设计决策总结

| 决策 | 选择 | 原因 |
|------|------|------|
| Skill 格式 | Markdown + YAML frontmatter | 人类可读、LLM 友好、版本控制友好 |
| 存储位置 | 文件系统 (~/.hermes/skills/) | 简单、可 git 管理、可跨工具共享 |
| 写入方式 | 原子写入 (tmpfile + replace) | 防止崩溃导致数据损坏 |
| 加载方式 | 渐进式 (index → full → file) | 最小化 token 消耗 |
| 修改方式 | Patch 优先于 Edit | 更省 token，更精确 |
| 安全扫描 | 默认关闭 | Agent 已有 terminal 权限，扫描只增加摩擦 |
| 删除保护 | Pin 机制 | 防止不可逆损失，但允许内容改进 |
| 生命周期 | Curator 自动管理 | 防止 Skill 无限堆积 |
| 进化优化 | GEPA + PR 审查 | 自动化改进但保留人工把关 |
| 溯源区分 | 前台 vs 后台创建 | 用户创建的不受 Curator 管理 |
| 条件激活 | requires/fallback 声明 | 避免无关 Skill 污染 prompt |
| 跨会话生效 | 清除 cache，下次会话加载 | 保护当前会话的 prompt caching |

---

## 十二、对 aPaaS 平台的启示

### 12.1 可借鉴的核心模式

1. **Skill = 可执行的程序性知识**：不是"记住了什么"，而是"知道怎么做"
2. **渐进式加载**：索引 → 摘要 → 全文，按需消耗 token
3. **即时修补**：使用中发现问题立即修正，不等离线审查
4. **原子写入**：任何时刻崩溃都不会损坏数据
5. **遥测驱动生命周期**：基于实际使用数据决定保留/归档
6. **条件激活**：根据当前环境动态显示/隐藏能力

### 12.2 在 aPaaS 中的映射

| Hermes 概念 | aPaaS 映射 |
|-------------|-----------|
| Skill | 业务流程模板 / 操作手册 |
| SKILL.md | 流程定义文档（元数据 + 步骤） |
| references/ | 关联的 API 文档、数据模型说明 |
| templates/ | 表单模板、配置模板 |
| scripts/ | 自动化脚本、数据迁移脚本 |
| Curator | 模板版本管理 + 废弃策略 |
| GEPA 进化 | 基于执行日志的流程优化 |
| Memory Nudge | 操作审计 → 自动提炼最佳实践 |

---

## 参考资料

- [tools/skill_manager_tool.py](https://raw.githubusercontent.com/NousResearch/hermes-agent/main/tools/skill_manager_tool.py) — 完整源码
- [Skills System 文档](https://hermes-agent.nousresearch.com/docs/user-guide/features/skills)
- [Creating Skills 开发者指南](https://hermes-agent.nousresearch.com/docs/developer-guide/creating-skills)
- [Prompt Assembly 文档](https://hermes-agent.nousresearch.com/docs/developer-guide/prompt-assembly)
- [Curator 文档](https://hermes-agent.nousresearch.com/docs/zh-Hans/user-guide/features/curator)
- [Working with Skills 指南](https://hermes-agent.nousresearch.com/docs/guides/work-with-skills)
- [hermes-agent-self-evolution](https://github.com/NousResearch/hermes-agent-self-evolution) — 离线进化优化

> Content was rephrased for compliance with licensing restrictions. All sources are MIT licensed open-source projects.
