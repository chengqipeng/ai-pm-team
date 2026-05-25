# Skills 系统详细设计 — 程序性记忆的自动固化与持续改进

> 基于 Hermes Agent 源码（`tools/skill_manager_tool.py`、`tools/skills_tool.py`、`tools/skill_usage.py`）的完整逆向分析，输出 Agent 自主创建/改进 Skill 的详细实现逻辑。

---

## 一、设计哲学

**核心理念**：Agent 完成复杂任务后，将成功路径固化为可复用的程序性知识（Skill），并在后续使用中持续改进。

| 设计原则 | 实现方式 | 设计意图 |
|:---|:---|:---|
| 程序性记忆 | SKILL.md = 步骤化操作手册 | 不是"知道什么"，而是"怎么做" |
| 自动固化 | 复杂任务后 Agent 主动创建 | 无需用户干预 |
| 持续改进 | 使用中发现问题立即 patch | Skill 越用越好 |
| 渐进式加载 | 三级加载（列表→内容→文件） | 最小化 token 消耗 |
| 生命周期管理 | 使用追踪 + Curator 自动归档 | 过时 Skill 自动淘汰 |

---

## 二、整体架构

```
┌─────────────────────────────────────────────────────────────────────┐
│                     Agent 对话循环                                    │
│                                                                      │
│  用户请求 → Agent 执行任务（5+ tool calls）→ 任务成功                 │
│                                                                      │
│  触发条件判断：                                                       │
│  ├── 复杂任务（5+ 工具调用）？                                        │
│  ├── 遇到错误后找到正确路径？                                         │
│  ├── 用户纠正了方法？                                                 │
│  └── 发现非平凡工作流？                                               │
│           │                                                          │
│           ▼ YES                                                      │
│  skill_manage(action="create", name="...", content="...")             │
└─────────────────────────────────────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────────────────────────────────┐
│                     Skills 存储层                                     │
│                                                                      │
│  ~/.hermes/skills/                                                   │
│  ├── devops/                    # 分类目录                            │
│  │   └── deploy-k8s/                                                 │
│  │       ├── SKILL.md           # 主指令文件（必需）                   │
│  │       ├── references/        # 参考文档                            │
│  │       ├── templates/         # 输出模板                            │
│  │       ├── scripts/           # 辅助脚本                            │
│  │       └── assets/            # 补充文件                            │
│  ├── .usage.json                # 使用遥测数据                        │
│  ├── .bundled_manifest          # 内置 Skill 清单                     │
│  ├── .hub/                      # Hub 安装状态                        │
│  └── .archive/                  # 归档的过时 Skill                    │
└─────────────────────────────────────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────────────────────────────────┐
│                     后续使用 & 持续改进                                │
│                                                                      │
│  用户请求匹配 Skill → skill_view() 加载 → Agent 按步骤执行            │
│       │                                                              │
│       ├── 执行顺利 → bump_use() 记录使用                              │
│       └── 遇到问题 → skill_manage(action="patch") 立即修复            │
│                                                                      │
│  Curator 定期检查：                                                   │
│  ├── 长期未使用 → 标记 stale                                          │
│  ├── 超期未使用 → 自动归档到 .archive/                                │
│  └── 用户 pin → 永不自动删除                                          │
└─────────────────────────────────────────────────────────────────────┘
```


---

## 三、Skill 创建的触发逻辑

### 3.1 触发条件（Tool Description 中的行为引导）

Agent 通过 `skill_manage` tool 的 description 被引导在以下场景创建 Skill：

```
Create when:
  - 复杂任务成功（5+ tool calls）
  - 遇到错误后找到正确路径
  - 用户纠正的方法生效了
  - 发现了非平凡的工作流
  - 用户明确要求记住某个流程

Skip for:
  - 简单的一次性任务
  - 无需确认即可完成的操作
```

### 3.2 创建流程（源码逻辑）

```python
def _create_skill(name: str, content: str, category: str = None) -> Dict:
    """创建新 Skill 的完整流程"""
    
    # 1. 名称校验
    #    - 非空，≤64 chars
    #    - 正则：^[a-z0-9][a-z0-9._-]*$（小写、数字、连字符）
    #    - 文件系统安全、URL 友好
    
    # 2. 分类校验（可选）
    #    - 单层目录名，不含 / 或 \
    #    - 同样的命名规则
    
    # 3. 内容校验
    #    - 必须有 YAML frontmatter（--- 开头和结尾）
    #    - frontmatter 必须包含 name 和 description
    #    - description ≤ 1024 chars
    #    - frontmatter 后必须有正文内容
    #    - 总大小 ≤ 100,000 chars（~36k tokens）
    
    # 4. 名称冲突检查
    #    - 在所有 skills 目录（本地 + external_dirs）中搜索
    #    - 同名 Skill 已存在 → 拒绝
    
    # 5. 创建目录 + 原子写入 SKILL.md
    #    - mkdir -p ~/.hermes/skills/{category}/{name}/
    #    - 原子写入：tempfile + fsync + os.replace
    
    # 6. 安全扫描（可选，默认关闭）
    #    - 检测注入/泄露模式
    #    - 扫描失败 → 回滚（删除整个目录）
    
    # 7. 清除 Skills 系统 prompt 缓存
    #    - 新 Skill 立即出现在 skills index 中
    
    # 8. 标记来源（Curator 遥测）
    #    - 如果是后台自我改进创建 → mark_agent_created(name)
    #    - 如果是用户指导创建 → 不标记（用户拥有，Curator 不碰）
```

### 3.3 SKILL.md 格式规范

```yaml
---
name: deploy-k8s                    # 必需，≤64 chars
description: Kubernetes 部署流程     # 必需，≤1024 chars
version: 1.0.0                      # 可选
platforms: [macos, linux]           # 可选，限制平台
metadata:
  hermes:
    tags: [kubernetes, devops]      # 可选，分类标签
    category: devops                # 可选，分类
    fallback_for_toolsets: [web]    # 可选，条件激活
    requires_toolsets: [terminal]   # 可选，条件激活
---

# Deploy to Kubernetes

## When to Use
- 用户要求部署到 K8s 集群
- 需要更新现有部署的镜像版本

## Procedure
1. 检查 kubectl 连接状态
2. 验证 deployment YAML 格式
3. 执行 kubectl apply
4. 等待 rollout 完成
5. 验证 pod 状态

## Pitfalls
- 忘记检查 namespace 是否正确
- 镜像 tag 使用 latest 导致缓存问题

## Verification
- kubectl get pods -n {namespace} 显示 Running
- kubectl rollout status deployment/{name} 返回成功
```

---

## 四、Skill 的持续改进机制

### 4.1 Patch 操作 — 首选的改进方式

```python
def _patch_skill(name, old_string, new_string, file_path=None, replace_all=False):
    """定向修改 Skill 内容（比 edit 更 token 高效）"""
    
    # 1. 定位 Skill 目录
    # 2. 确定目标文件（默认 SKILL.md，可指定 file_path）
    # 3. 模糊匹配查找 old_string
    #    - 使用 fuzzy_find_and_replace 引擎
    #    - 处理空白差异、缩进差异、转义字符
    #    - 默认要求唯一匹配（replace_all=True 可替换所有）
    # 4. 执行替换
    # 5. 校验替换后的内容
    #    - 大小限制检查
    #    - 如果是 SKILL.md → 校验 frontmatter 完整性
    # 6. 原子写入 + 安全扫描
    #    - 扫描失败 → 回滚到原始内容
    # 7. 更新遥测：bump_patch(name)
```

**为什么 patch 优于 edit**：
- `patch`：只传输变更部分（old_string + new_string），token 消耗小
- `edit`：传输完整 SKILL.md 内容，token 消耗大
- 规则：小修改用 patch，大重构用 edit

### 4.2 改进触发场景

```
Agent 加载 Skill → 按步骤执行 → 遇到问题
    │
    ├── 步骤过时（命令已变）→ patch 更新命令
    ├── 缺少步骤（遗漏关键操作）→ patch 添加步骤
    ├── Pitfall 未覆盖（新发现的坑）→ patch 添加 pitfall
    ├── 平台差异（macOS vs Linux）→ patch 添加条件分支
    └── 用户纠正（"不要这样做"）→ patch 修正方法
```

Tool Description 中的引导：
```
Update when: instructions stale/wrong, OS-specific failures,
missing steps or pitfalls found during use.
If you used a skill and hit issues not covered by it, patch it immediately.
```

### 4.3 Edit 操作 — 大规模重写

```python
def _edit_skill(name: str, content: str) -> Dict:
    """完全替换 SKILL.md 内容（用于大规模重构）"""
    
    # 1. 校验新内容（frontmatter + 大小）
    # 2. 定位现有 Skill
    # 3. 备份原始内容（用于回滚）
    # 4. 原子写入新内容
    # 5. 安全扫描（失败则回滚）
    # 6. 更新遥测：bump_patch(name)
```

### 4.4 支撑文件管理

```python
# 添加参考文档
skill_manage(action="write_file", name="deploy-k8s",
             file_path="references/helm-values.md",
             file_content="# Helm Values 参考\n...")

# 添加模板
skill_manage(action="write_file", name="deploy-k8s",
             file_path="templates/deployment.yaml",
             file_content="apiVersion: apps/v1\n...")

# 添加脚本
skill_manage(action="write_file", name="deploy-k8s",
             file_path="scripts/validate.sh",
             file_content="#!/bin/bash\nkubectl get pods...")

# 删除过时文件
skill_manage(action="remove_file", name="deploy-k8s",
             file_path="references/old-api.md")
```

**允许的子目录**：`references/`、`templates/`、`scripts/`、`assets/`

---

## 五、渐进式加载机制（Progressive Disclosure）

### 5.1 三级加载

```
Level 0: skills_list()
    → 返回所有 Skill 的 {name, description, category}
    → ~3k tokens（轻量，适合 system prompt 中的 index）
    
Level 1: skill_view(name)
    → 返回完整 SKILL.md 内容 + 元数据 + linked_files 列表
    → 按需加载，只在 Agent 决定使用时才消耗 token
    
Level 2: skill_view(name, file_path)
    → 返回特定参考文件/模板/脚本内容
    → 最细粒度，只加载需要的辅助文件
```

### 5.2 System Prompt 中的 Skills Index

```
## Skills (mandatory)
Before replying, scan the skills below. If one clearly matches
your task, load it with skill_view(name) and follow its instructions.

<available_skills>
  devops:
    - deploy-k8s: Kubernetes deployment workflow
    - docker-compose: Docker Compose orchestration
  data-science:
    - axolotl: Fine-tune LLMs with Axolotl
    - vllm: Deploy models with vLLM
</available_skills>
```

**关键设计**：只有名称和描述进入 system prompt，完整内容按需加载。

### 5.3 条件激活（Conditional Activation）

```yaml
metadata:
  hermes:
    fallback_for_toolsets: [web]      # web 工具不可用时才显示
    requires_toolsets: [terminal]     # 需要 terminal 工具才显示
    fallback_for_tools: [web_search]  # 特定工具不可用时显示
    requires_tools: [terminal]        # 需要特定工具才显示
```

不满足条件的 Skill 从 index 中隐藏，减少噪声。


---

## 六、使用追踪与生命周期管理

### 6.1 遥测数据结构（.usage.json）

```json
{
  "deploy-k8s": {
    "created_by": "agent",           // "agent" = Curator 可管理
    "use_count": 12,                 // skill_view 加载次数
    "view_count": 15,                // 浏览次数
    "last_used_at": "2026-05-20T10:30:00+00:00",
    "last_viewed_at": "2026-05-22T08:15:00+00:00",
    "patch_count": 3,                // 被修改次数
    "last_patched_at": "2026-05-18T14:20:00+00:00",
    "created_at": "2026-04-01T09:00:00+00:00",
    "state": "active",              // active | stale | archived
    "pinned": false,                // true = 永不自动删除
    "archived_at": null
  }
}
```

### 6.2 遥测触发点

| 事件 | 触发位置 | 更新字段 |
|:---|:---|:---|
| Agent 加载 Skill | `skill_view()` → `bump_view()` + `bump_use()` | view_count, use_count, last_*_at |
| Agent 修改 Skill | `skill_manage(patch/edit/write_file)` → `bump_patch()` | patch_count, last_patched_at |
| Agent 创建 Skill | `skill_manage(create)` → `mark_agent_created()` | created_by, created_at |
| Agent 删除 Skill | `skill_manage(delete)` → `forget()` | 删除整条记录 |

### 6.3 生命周期状态机

```
                    ┌─────────────────────────────────┐
                    │                                 │
                    ▼                                 │
┌──────────┐   超期未使用   ┌──────────┐   超期未使用   ┌──────────────┐
│  active  │ ──────────► │  stale   │ ──────────► │  archived    │
│  (活跃)   │             │  (过时)   │             │  (归档)       │
└──────────┘             └──────────┘             └──────────────┘
     ▲                        │                        │
     │                        │ 被使用                  │ hermes curator restore
     │                        ▼                        │
     └────────────────── 自动恢复 ◄────────────────────┘
     
     ┌──────────┐
     │  pinned  │  ← 正交状态，任何 state 都可以 pin
     │  (钉住)   │  → 阻止自动删除，但允许 patch/edit
     └──────────┘
```

### 6.4 Curator 自动管理

```python
# Curator 定期检查逻辑（简化）
for skill in list_agent_created_skill_names():
    record = get_record(skill)
    last_activity = latest_activity_at(record)
    
    if record["pinned"]:
        continue  # 钉住的不碰
    
    days_inactive = (now - parse(last_activity)).days
    
    if days_inactive > archive_after_days:
        archive_skill(skill)  # 移到 .archive/
    elif days_inactive > stale_after_days:
        set_state(skill, "stale")  # 标记过时
```

**关键约束**：
- Curator 只管理 `created_by == "agent"` 的 Skill
- 内置 Skill（bundled）和 Hub 安装的 Skill 永远不被 Curator 碰
- 用户手动创建的 Skill 也不被 Curator 管理
- Pin 保护只阻止删除，不阻止改进（patch/edit 仍可执行）

### 6.5 来源判定逻辑

```python
def is_agent_created(skill_name: str) -> bool:
    """判断 Skill 是否由 Agent 创建（非内置、非 Hub）"""
    bundled = _read_bundled_manifest_names()   # .bundled_manifest
    hub = _read_hub_installed_names()          # .hub/lock.json
    return skill_name not in (bundled | hub)

def _is_curator_managed_record(record) -> bool:
    """判断 Skill 是否受 Curator 管理"""
    return record.get("created_by") == "agent"
```

---

## 七、安全机制

### 7.1 内容安全扫描

```python
# 注入检测模式
_INJECTION_PATTERNS = [
    "ignore previous instructions",
    "ignore all previous",
    "you are now",
    "disregard your",
    "forget your instructions",
    "new instructions:",
    "system prompt:",
    "<system>",
    "]]>",
]
```

扫描时机：
- `skill_view()` 加载时 → 检测到注入模式 → 警告日志（仍然加载）
- `skill_manage(create/edit/patch/write_file)` 写入时 → 可选安全扫描 → 阻止则回滚

### 7.2 路径安全

```python
# 防止路径穿越
from tools.path_security import has_traversal_component, validate_within_dir

# write_file/remove_file 只允许在以下子目录操作
ALLOWED_SUBDIRS = {"references", "templates", "scripts", "assets"}

# 验证解析后的路径仍在 skill 目录内
target = skill_dir / file_path
error = validate_within_dir(target, skill_dir)
```

### 7.3 大小限制

| 限制 | 值 | 目的 |
|:---|:---|:---|
| SKILL.md 内容 | 100,000 chars (~36k tokens) | 防止 Skill 膨胀 |
| 支撑文件 | 1 MiB (1,048,576 bytes) | 防止大文件 |
| Skill 名称 | 64 chars | 文件系统兼容 |
| Description | 1,024 chars | 控制 index 大小 |

### 7.4 Pin 保护

```python
def _pinned_guard(name: str) -> Optional[str]:
    """Pin 保护只阻止删除，不阻止改进"""
    record = skill_usage.get_record(name)
    if record.get("pinned"):
        return (
            f"Skill '{name}' is pinned and cannot be deleted. "
            f"Ask the user to run `hermes curator unpin {name}` "
            f"if they want to delete it. "
            f"Patches and edits are allowed on pinned skills."
        )
    return None
```

---

## 八、与 System Prompt 的集成

### 8.1 Skills Guidance（行为引导）

在 system prompt 的 Layer 2 中：

```
You have a skills system for procedural memory. When you complete a
complex task (5+ tool calls), consider saving the approach as a skill.
Before replying, scan the skills index. If one clearly matches your
task, load it with skill_view(name) and follow its instructions.
```

### 8.2 Skills Index 注入

在 system prompt 的 Layer 7 中，自动生成的 skills index：

```python
def _find_all_skills(skip_disabled=False) -> List[Dict]:
    """扫描所有 Skill 目录，生成 index"""
    # 1. 扫描 ~/.hermes/skills/ + external_dirs
    # 2. 过滤：平台不兼容的、被禁用的
    # 3. 只提取 name + description + category
    # 4. 按 category → name 排序
    # 返回轻量列表，注入 system prompt
```

### 8.3 Prompt Cache 兼容

```
Skill 创建/修改后：
    clear_skills_system_prompt_cache(clear_snapshot=True)
    → 下次会话重建 skills index
    → 当前会话的 system prompt 不变（冻结快照模式）
```

---

## 九、Delete 与 Consolidation

### 9.1 删除操作

```python
def _delete_skill(name: str, absorbed_into: Optional[str] = None):
    """删除 Skill，支持声明合并意图"""
    
    # 1. 查找 Skill
    # 2. Pin 保护检查（pinned → 拒绝）
    # 3. absorbed_into 校验
    #    - 非空 → 目标 Skill 必须存在
    #    - 不能指向自己
    # 4. shutil.rmtree 删除目录
    # 5. 清理空的分类目录
    # 6. 遥测：forget(name) 删除使用记录
```

### 9.2 Consolidation 模式

```python
# 合并场景：多个小 Skill 合并为一个大 Skill
# 步骤：
# 1. 创建/patch 目标 umbrella Skill
# 2. 删除源 Skill，声明 absorbed_into

skill_manage(action="delete", name="deploy-docker",
             absorbed_into="deploy-containers")
# → "Skill 'deploy-docker' deleted. Content absorbed into 'deploy-containers'."
```

**设计意图**：让 Curator 和下游工具（如 cron job）知道被删除的 Skill 内容去了哪里。

---

## 十、完整的 Skill 生命周期示例

```
Day 1: 用户要求部署 K8s 应用
    │
    ▼
Agent 执行 8 个 tool calls，成功部署
    │
    ▼
Agent: "这个部署流程比较复杂，要保存为 Skill 吗？"
User: "好的"
    │
    ▼
skill_manage(action="create", name="deploy-k8s", category="devops",
             content="---\nname: deploy-k8s\n...")
    │
    ▼
Day 5: 用户再次要求部署
    │
    ▼
Agent 扫描 skills index → 匹配 deploy-k8s
    │
    ▼
skill_view("deploy-k8s") → 加载完整内容
    │
    ▼
Agent 按步骤执行 → 发现步骤 3 的命令已过时
    │
    ▼
skill_manage(action="patch", name="deploy-k8s",
             old_string="kubectl apply -f deploy.yaml",
             new_string="kubectl apply -f deploy.yaml --server-side")
    │
    ▼
Day 15: Agent 在另一次部署中发现新的 pitfall
    │
    ▼
skill_manage(action="patch", name="deploy-k8s",
             old_string="## Pitfalls\n- 忘记检查 namespace",
             new_string="## Pitfalls\n- 忘记检查 namespace\n- 镜像拉取策略需要设为 Always")
    │
    ▼
Day 60: Curator 检查 → 最近 30 天未使用 → 标记 stale
    │
    ▼
Day 90: Curator 检查 → 最近 60 天未使用 → 归档到 .archive/
    │
    ▼
Day 100: 用户又需要部署
    │
    ▼
hermes curator restore deploy-k8s → 恢复到 skills/
```

---

## 十一、aPaaS Agent 系统的 Skills 设计方案

### 11.1 Skill 类型映射

| Hermes Skill 类型 | aPaaS 映射 | 示例 |
|:---|:---|:---|
| 工作流 Skill | 元数据配置 SOP | "创建实体+字段+校验规则"完整流程 |
| 工具使用 Skill | API 调用最佳实践 | "批量导入元数据的正确姿势" |
| 故障排除 Skill | 常见问题解决方案 | "字段映射冲突的排查步骤" |
| 模板 Skill | 配置模板 | "标准 CRM 实体的字段模板" |

### 11.2 aPaaS Skill 示例

```yaml
---
name: create-entity-with-rules
description: 创建实体对象并配置校验规则的标准流程
version: 1.0.0
metadata:
  hermes:
    tags: [entity, checkRule, metadata]
    category: metadata-config
---

# 创建实体并配置校验规则

## When to Use
- 用户要求创建新的业务对象（实体）
- 需要同时配置字段和校验规则

## Procedure
1. 确认实体基本信息（apiKey, label, description）
2. 确认 apiKey 命名规范（camelCase，{模块}_{对象}格式）
3. 调用 POST /metarepo/entities 创建实体
4. 逐个创建字段（POST /metarepo/entities/{apiKey}/items）
   - 注意 item apiKey 必须 camelCase
   - 布尔字段必须 xxxFlg 后缀 + Integer(0/1)
5. 创建校验规则（POST /metarepo/entities/{apiKey}/checkRules）
6. 验证：GET /metarepo/entities/{apiKey} 确认完整性

## Pitfalls
- apiKey 不能用 snake_case，必须 camelCase
- 布尔字段禁止 enable*/is* 前缀，统一 xxxFlg
- 忘记创建国际化字段（labelKey, descriptionKey）
- 字段类型选错导致 db_column 分配浪费

## Verification
- 实体列表中能看到新创建的实体
- 字段数量与预期一致
- 校验规则在数据录入时生效
```

### 11.3 自动创建触发场景

| 场景 | 触发条件 | 生成的 Skill |
|:---|:---|:---|
| 首次配置复杂实体 | 5+ API 调用成功 | 实体配置 SOP |
| 解决字段映射冲突 | 遇到错误→找到解法 | 冲突排查指南 |
| 用户纠正命名规范 | 用户说"不要这样命名" | 命名规范速查 |
| 批量操作成功 | 发现高效批量路径 | 批量操作最佳实践 |

---

## 十二、关键设计决策总结

| 决策 | 选择 | 理由 |
|:---|:---|:---|
| 存储格式 | Markdown + YAML frontmatter | 人类可读、Git 友好、无依赖 |
| 加载策略 | 渐进式三级加载 | 最小化 token 消耗 |
| 改进方式 | patch 优先于 edit | token 高效，变更可追踪 |
| 生命周期 | 自动归档而非删除 | 可恢复，不丢失知识 |
| 来源追踪 | 显式标记 agent_created | 区分用户创建 vs Agent 创建 |
| 安全模型 | 写入时扫描 + 路径限制 | Skill 内容进入 prompt，是攻击面 |
| 并发安全 | 文件锁 + 原子写入 | 多会话/多平台并发安全 |
| Pin 语义 | 只阻止删除，不阻止改进 | 保护重要 Skill 同时允许进化 |

---

## 十三、与 Memory 系统的分工

| 维度 | Memory | Skills |
|:---|:---|:---|
| 知识类型 | 声明性（事实、偏好） | 程序性（步骤、流程） |
| 粒度 | 单条事实（1-2 句话） | 完整操作手册（多步骤） |
| 容量 | 有界（3,575 chars） | 无界（每个 Skill ≤100K chars） |
| 注入方式 | 始终在 system prompt 中 | 按需加载（skill_view） |
| 管理方式 | Agent 自主 add/replace/remove | Agent 自主 create/patch/delete |
| 生命周期 | 手动管理（Agent 决定） | 自动管理（Curator 归档） |
| 适用场景 | "用户偏好 TypeScript" | "如何配置 K8s 部署" |

**协作模式**：
- Memory 记住"用户喜欢批量操作" → 影响 Agent 选择哪个 Skill
- Skill 记录"批量操作的具体步骤" → Agent 按步骤执行
- 执行中发现新事实 → 写入 Memory
- 执行中发现步骤问题 → patch Skill

---

*来源：[NousResearch/hermes-agent](https://github.com/NousResearch/hermes-agent) 源码逆向分析*
*Content was rephrased for compliance with licensing restrictions*
