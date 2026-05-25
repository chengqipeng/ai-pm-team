# Agent 级别反思机制深度分析 — 基于 Hermes Agent 源码

> 基于 [NousResearch/hermes-agent](https://github.com/nousresearch/hermes-agent) 及其配套项目 [hermes-agent-self-evolution](https://github.com/NousResearch/hermes-agent-self-evolution) 的源码与架构文档进行深度分析。

---

## 一、总体架构：反思机制的三层设计

Hermes Agent 的反思机制并非单一模块，而是一个**三层递进**的系统：

```
┌─────────────────────────────────────────────────────────────────┐
│  Layer 3: 离线进化 (Offline Evolution)                           │
│  hermes-agent-self-evolution — DSPy + GEPA 反思式进化优化        │
│  周期：天/周级 | 粒度：Skill/Prompt/Tool 全文本                  │
└─────────────────────────────────────────────────────────────────┘
                              ▲
┌─────────────────────────────────────────────────────────────────┐
│  Layer 2: 后台维护 (Background Maintenance)                      │
│  Curator + Memory Nudge — 周期性自省与知识整理                    │
│  周期：每10轮/每7天 | 粒度：Skill 生命周期 + 记忆持久化          │
└─────────────────────────────────────────────────────────────────┘
                              ▲
┌─────────────────────────────────────────────────────────────────┐
│  Layer 1: 在线反馈 (Online Feedback Loop)                        │
│  Agent Loop + Skill Self-Improvement — 即时学习与技能创建         │
│  周期：每轮/每次任务 | 粒度：单次对话中的经验提取                │
└─────────────────────────────────────────────────────────────────┘
```

---

## 二、Layer 1：在线反馈循环 — Agent Loop 内的即时反思

### 2.1 核心循环结构 (run_agent.py → AIAgent)

Hermes 的 Agent Loop 是一个同步编排引擎，核心流程：

```python
run_conversation():
  1. 生成 task_id
  2. 将用户消息追加到对话历史
  3. 构建/复用缓存的系统提示 (prompt_builder.py)
  4. 检查是否需要预压缩 (>50% 上下文)
  5. 从对话历史构建 API 消息
  6. 注入临时提示层 (预算警告、上下文压力)
  7. 应用 Anthropic 提示缓存标记
  8. 发起可中断的 API 调用
  9. 解析响应:
     - 如果是 tool_calls → 执行工具 → 追加结果 → 回到步骤 5
     - 如果是文本响应 → 持久化会话 → 刷新记忆 → 返回
```

**反思触发点**：在步骤 9 的循环中，Agent 具备以下反思能力：

| 机制 | 触发条件 | 反思行为 |
|------|----------|----------|
| 工具执行失败重试 | 工具返回错误 | 分析错误原因，调整参数重试 |
| 迭代预算追踪 | 接近 90 轮上限 | 总结已完成工作，规划剩余步骤 |
| 上下文压缩 | 超过 50% 上下文窗口 | 结构化总结中间对话，保留关键决策 |
| Fallback 模型切换 | 主模型 429/5xx | 自动切换备用模型继续工作 |

### 2.2 即时技能创建 (skill_manager_tool.py)

这是 Hermes 最核心的"从经验中学习"机制。源码中 `SKILL_MANAGE_SCHEMA` 的描述明确定义了创建时机：

```
创建条件：
- 复杂任务成功完成（5+ 次工具调用）
- 克服了错误/异常
- 用户纠正后的方法有效
- 发现了非平凡的工作流
- 用户明确要求记住某个流程

更新条件：
- 指令过时/错误
- 发现 OS 特定的失败
- 使用中发现遗漏的步骤或陷阱
```

**关键设计**：如果 Agent 使用了某个 Skill 但遇到了 Skill 未覆盖的问题，它会**立即 patch 该 Skill**：

> "If you used a skill and hit issues not covered by it, patch it immediately."

这是一种**即时反思 + 即时修正**的模式，不需要等待离线评估。

### 2.3 结构化压缩作为反思 (context_compressor.py)

上下文压缩不仅是资源管理，更是一种**强制反思**。压缩时生成的结构化摘要模板：

```markdown
## Goal
[用户试图完成什么]

## Constraints & Preferences
[用户偏好、编码风格、约束、重要决策]

## Progress
### Done
[已完成的工作 — 具体文件路径、执行的命令、结果]
### In Progress
[正在进行的工作]
### Blocked
[遇到的阻塞或问题]

## Key Decisions
[重要的技术决策及原因]

## Relevant Files
[读取、修改或创建的文件 — 每个附简要说明]

## Next Steps
[接下来需要做什么]

## Critical Context
[具体值、错误消息、配置细节]
```

**迭代再压缩**：后续压缩时，前一次的摘要会传给 LLM，指示它**更新而非重新总结**。这保证了信息在多次压缩中不丢失 — 项目从 "In Progress" 移到 "Done"，新进展被添加，过时信息被移除。

---

## 三、Layer 2：后台维护 — 周期性自省机制

### 3.1 Memory Nudge（记忆推送）

每 **10 轮对话**，Hermes 运行一次内部审查：

- 审查最近的对话内容
- 判断是否有值得保存到持久记忆的信息
- 判断是否有可以自动化为新 Skill 的工作流
- **无需用户主动要求**即可触发

这个机制的核心洞察是：**Agent 自己决定什么值得记住**，而不是记录一切或什么都不记。

实现方式：在 Agent Loop 内部，每 N 轮后注入一个"自省提示"，让 Agent 在后台 fork 中评估当前对话的价值。

### 3.2 Curator（技能策展人）

Curator 是一个**后台维护进程**，专门管理 Agent 自动创建的技能的生命周期：

```
active → stale (30天未使用) → archived (90天未使用)
```

#### 运行机制

1. **触发条件**：不是 cron 守护进程，而是惰性检查
   - 距上次运行超过 `interval_hours`（默认 7 天）
   - Agent 空闲超过 `min_idle_hours`（默认 2 小时）

2. **两阶段执行**：
   - **Phase 1 — 确定性转换**（无 LLM）：基于使用频率的状态迁移
   - **Phase 2 — LLM 审查**（辅助模型，max_iterations=8）：
     - 调查所有 agent-created skills
     - 逐个决定：保留 / patch / 合并重叠项 / 归档

3. **安全保障**：
   - 永远不自动删除，最严重的操作是归档（可恢复）
   - 每次运行前自动备份 `~/.hermes/skills/`
   - 支持 pin 保护关键技能
   - 所有变更生成报告 (`~/.hermes/logs/curator/`)

#### 使用遥测 (.usage.json)

```json
{
  "my-skill": {
    "use_count": 12,
    "view_count": 34,
    "last_used_at": "2026-04-24T18:12:03Z",
    "patch_count": 3,
    "state": "active",
    "pinned": false
  }
}
```

这个遥测数据驱动了 Curator 的决策 — 它知道哪些技能被频繁使用，哪些已经过时。

### 3.3 Skill Provenance（技能溯源）

源码中有一个关键区分：

```python
# 只有后台自我改进审查 fork 创建的技能才标记为 agent-created
# 前台 skill_manage(create) 调用是用户指导的，属于用户
if is_background_review():
    mark_agent_created(name)
```

这意味着 Curator 只管理 Agent **自主创建**的技能，用户手动创建的不受影响。

---

## 四、Layer 3：离线进化 — DSPy + GEPA 反思式优化

### 4.1 hermes-agent-self-evolution 架构

这是一个独立的进化优化管道，使用 GEPA（Genetic-Pareto Prompt Evolution）来自动进化 Hermes 的各种文本组件：

```
读取当前 skill/prompt/tool ──► 生成评估数据集
                                      │
                                      ▼
                                 GEPA Optimizer ◄── 执行轨迹
                                      │                    ▲
                                      ▼                    │
                                 候选变体 ──────────► 评估
                                      │
                                 约束门控 (测试、大小限制、基准)
                                      │
                                      ▼
                                 最佳变体 ──► PR 提交到 hermes-agent
```

#### 优化阶段规划

| 阶段 | 目标 | 引擎 | 状态 |
|------|------|------|------|
| Phase 1 | Skill 文件 (SKILL.md) | DSPy + GEPA | ✅ 已实现 |
| Phase 2 | Tool 描述 | DSPy + GEPA | 🔲 计划中 |
| Phase 3 | 系统提示片段 | DSPy + GEPA | 🔲 计划中 |
| Phase 4 | Tool 实现代码 | Darwinian Evolver | 🔲 计划中 |
| Phase 5 | 持续改进循环 | 自动化管道 | 🔲 计划中 |

### 4.2 GEPA 的反思机制核心

GEPA 的核心创新在于**反思式提示变异**（Reflective Prompt Mutation）：

```
1. 初始化候选池（未优化的程序）
2. 迭代：
   a. 从 Pareto 前沿采样一个候选
   b. 从训练集采样一个 minibatch
   c. 收集执行轨迹 + 反馈
   d. 选择目标模块进行改进
   e. LLM 反思：基于反思式元提示和收集的反馈，为目标模块提出新指令
   f. 在 minibatch 上运行新候选；如果改进，在 Pareto 验证集上评估
   g. 更新候选池/Pareto 前沿
   h. [可选] 系统感知的合并/交叉：组合不同谱系的最佳模块
3. 直到预算耗尽
4. 返回验证集上聚合性能最佳的候选
```

**关键区别于传统优化**：GEPA 不仅使用标量分数，还利用**文本反馈**作为优化信号。这包括：
- 评估日志
- 代码轨迹
- 解析失败
- 约束违反
- 错误消息字符串
- 子模块级别的反馈

### 4.3 Fitness 评估（fitness.py）

```python
class FitnessScore:
    correctness: float       # 输出是否正确 (0-1)
    procedure_following: float  # 是否遵循了技能的流程 (0-1)
    conciseness: float       # 是否适当简洁 (0-1)
    length_penalty: float    # 过于冗长的惩罚 (0-1)
    feedback: str            # 文本反馈，供 GEPA 反思分析使用

    @property
    def composite(self) -> float:
        raw = 0.5 * correctness + 0.3 * procedure_following + 0.2 * conciseness
        return max(0.0, raw - length_penalty)
```

LLM-as-Judge 评估器使用 DSPy 的 `ChainOfThought` 模式，在评估时不仅打分，还生成**可操作的改进建议**，这些建议直接反馈给 GEPA 的反思循环。

### 4.4 护栏（Guardrails）

每个进化变体必须通过：

1. **完整测试套件** — `pytest tests/ -q` 100% 通过
2. **大小限制** — Skills ≤15KB，tool 描述 ≤500 字符
3. **缓存兼容性** — 不能在对话中途改变
4. **语义保持** — 不能偏离原始目的
5. **PR 审查** — 所有变更经过人工审查，永不直接提交

---

## 五、设计模式提炼：如何设计 Agent 级别的反思机制

### 5.1 核心设计原则

基于 Hermes Agent 的实践，提炼出以下设计原则：

#### 原则 1：分层反思，频率递减

```
即时反思 (每轮)  →  周期反思 (每10轮/每天)  →  进化反思 (每周/每月)
   成本低              成本中                    成本高
   粒度细              粒度中                    粒度粗
   风险低              风险中                    风险高（需护栏）
```

#### 原则 2：Agent 自主决定什么值得记住

不是记录一切（token 爆炸），也不是什么都不记（每次从零开始），而是让 Agent 自己判断价值。Hermes 的 Memory Nudge 每 10 轮触发一次自省，由 Agent 决定是否持久化。

#### 原则 3：反思产物必须可操作

- 不是生成"总结报告"然后丢弃
- 而是生成**可复用的 Skill 文件**、**可更新的记忆条目**、**可进化的提示文本**
- 每个反思产物都有明确的消费者和使用场景

#### 原则 4：反思必须有安全边界

- Curator 永不删除，只归档
- 进化变体必须通过测试套件
- Pin 机制保护关键资产
- 所有变更可回滚

#### 原则 5：反思与执行分离

- 反思在后台 fork 中运行，不阻塞主对话
- 使用独立的 prompt cache，不污染当前会话
- 辅助模型可以与主模型不同（成本优化）

### 5.2 实现参考架构

```
┌─────────────────────────────────────────────────────────────────────┐
│                        Agent 反思系统                                │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  ┌─────────────┐   ┌─────────────┐   ┌─────────────┐              │
│  │ 即时反思    │   │ 周期反思    │   │ 进化反思    │              │
│  │             │   │             │   │             │              │
│  │ • 工具失败  │   │ • Memory    │   │ • GEPA      │              │
│  │   重试分析  │   │   Nudge     │   │   优化器    │              │
│  │ • 上下文    │   │ • Curator   │   │ • Fitness   │              │
│  │   压缩总结  │   │   审查      │   │   评估      │              │
│  │ • Skill     │   │ • 使用遥测  │   │ • Pareto    │              │
│  │   即时修补  │   │   分析      │   │   前沿选择  │              │
│  └──────┬──────┘   └──────┬──────┘   └──────┬──────┘              │
│         │                  │                  │                     │
│         ▼                  ▼                  ▼                     │
│  ┌─────────────────────────────────────────────────────────┐       │
│  │              知识存储层                                   │       │
│  │                                                         │       │
│  │  MEMORY.md    USER.md    Skills/    Sessions (SQLite)   │       │
│  │  (声明式)    (用户模型)  (程序式)   (FTS5 全文检索)      │       │
│  └─────────────────────────────────────────────────────────┘       │
│                                                                     │
│  ┌─────────────────────────────────────────────────────────┐       │
│  │              安全与治理层                                 │       │
│  │                                                         │       │
│  │  Pin 保护 | 备份/回滚 | 测试门控 | PR 审查 | 遥测追踪  │       │
│  └─────────────────────────────────────────────────────────┘       │
└─────────────────────────────────────────────────────────────────────┘
```

### 5.3 关键实现细节

#### 1. Memory Nudge 的实现模式

```python
# 伪代码 — 基于 Hermes 的实现模式
class AgentLoop:
    def run_conversation(self):
        turn_count = 0
        while turn_count < max_turns:
            response = self.call_llm()
            self.handle_response(response)
            turn_count += 1
            
            # 每 N 轮触发自省
            if turn_count % NUDGE_INTERVAL == 0:
                self._background_self_review()
    
    def _background_self_review(self):
        """在后台 fork 中运行，不阻塞主对话"""
        # 获取最近 N 轮对话
        recent_turns = self.history[-NUDGE_INTERVAL:]
        
        # 让辅助模型评估
        review_prompt = """
        审查以下对话片段，判断：
        1. 是否有值得保存到长期记忆的偏好/事实？
        2. 是否有可以抽象为可复用技能的工作流？
        3. 是否有需要更新的现有技能？
        """
        
        # 执行审查（使用辅助模型，不消耗主对话 token）
        result = self.auxiliary_client.call(review_prompt, recent_turns)
        
        # 根据结果执行操作
        if result.should_save_memory:
            self.memory_manager.update(result.memory_entries)
        if result.should_create_skill:
            self.skill_manager.create(result.skill_draft)
```

#### 2. Skill 自我改进的触发模式

```python
# 基于 skill_manager_tool.py 的设计
# 当 Agent 使用 Skill 遇到问题时，立即修补

def after_skill_execution(skill_name, execution_result):
    if execution_result.had_issues:
        # 不等待离线审查，立即修补
        patch_content = generate_patch(
            skill_name=skill_name,
            issue=execution_result.issue_description,
            solution=execution_result.workaround_used
        )
        skill_manage(
            action="patch",
            name=skill_name,
            old_string=...,  # 需要修改的部分
            new_string=patch_content  # 包含新发现的陷阱/步骤
        )
```

#### 3. 进化优化的集成模式

```python
# 基于 hermes-agent-self-evolution 的设计
from evolution.core.fitness import LLMJudge, FitnessScore

def evolve_skill(skill_name, iterations=10, eval_source="synthetic"):
    # 1. 读取当前 Skill
    current_skill = read_skill(skill_name)
    
    # 2. 生成/导入评估数据
    if eval_source == "synthetic":
        eval_data = generate_synthetic_tasks(current_skill)
    elif eval_source == "sessiondb":
        eval_data = import_from_sessions(skill_name)
    
    # 3. 配置 GEPA 优化器
    gepa = dspy.GEPA(
        metric=skill_fitness_metric,  # 包含文本反馈的评估函数
        auto="medium",
        reflection_lm=dspy.LM("gpt-5", temperature=1.0),
    )
    
    # 4. 运行进化
    optimized = gepa.compile(
        student=SkillModule(current_skill),
        trainset=eval_data,
    )
    
    # 5. 护栏检查
    assert run_tests()  # 测试套件必须通过
    assert len(optimized.skill_text) <= 15_000  # 大小限制
    
    # 6. 提交 PR（人工审查）
    create_pr(skill_name, optimized.skill_text)
```

---

## 六、对比分析：Hermes 反思机制 vs 其他方案

| 维度 | Hermes Agent | 传统 ReAct | Reflexion (Shinn et al.) |
|------|-------------|-----------|--------------------------|
| 反思粒度 | 三层（即时/周期/进化） | 单层（即时） | 两层（即时/episode） |
| 知识持久化 | Skill + Memory + Session | 无 | Episode memory |
| 跨会话学习 | ✅ 完整支持 | ❌ | 部分支持 |
| 自主创建能力 | ✅ 自动创建 Skill | ❌ | ❌ |
| 知识维护 | ✅ Curator 自动管理 | ❌ | ❌ |
| 进化优化 | ✅ GEPA 反思式进化 | ❌ | ❌ |
| 安全边界 | ✅ Pin/备份/测试/PR | 无 | 无 |
| 成本控制 | 辅助模型 + 分层频率 | 每轮全量 | 每 episode 全量 |

---

## 七、设计建议：在 aPaaS 平台中实现 Agent 反思

基于以上分析，针对 aPaaS 元数据驱动平台的 Agent 系统，建议：

### 7.1 最小可行反思系统

1. **即时层**：工具执行失败时的错误分析 + 重试策略调整
2. **会话层**：上下文压缩时的结构化总结（Goal/Progress/Decisions）
3. **跨会话层**：Memory Nudge 机制，每 N 轮自省一次

### 7.2 进阶反思系统

4. **技能创建**：复杂任务完成后自动提取可复用流程
5. **技能维护**：Curator 模式管理技能生命周期
6. **进化优化**：GEPA 模式离线优化 Prompt/Skill

### 7.3 关键实现建议

- **反思与执行分离**：使用后台 fork，不阻塞用户交互
- **辅助模型策略**：反思任务使用便宜快速的模型，降低成本
- **遥测驱动**：基于使用数据决定维护策略，而非固定规则
- **人机协作**：进化结果需要人工审查（PR 模式），不自动部署
- **可回滚设计**：所有反思产物的变更都可以撤销

---

## 参考资料

- [Hermes Agent 源码](https://github.com/nousresearch/hermes-agent) — MIT License
- [Hermes Agent Self-Evolution](https://github.com/NousResearch/hermes-agent-self-evolution) — MIT License
- [Hermes Agent 架构文档](https://hermes-agent.nousresearch.com/docs/developer-guide/architecture)
- [Agent Loop Internals](https://hermes-agent.nousresearch.com/docs/developer-guide/agent-loop)
- [GEPA: Reflective Prompt Evolution](https://dspy.ai/api/optimizers/GEPA/overview/) — DSPy 文档
- [Curator 文档](https://hermes-agent.nousresearch.com/docs/zh-Hans/user-guide/features/curator)

> Content was rephrased for compliance with licensing restrictions. All sources are MIT licensed open-source projects.
