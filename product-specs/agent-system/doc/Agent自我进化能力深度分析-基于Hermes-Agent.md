# Agent 自我进化能力深度分析 — 基于 Hermes Agent 源码

> 基于 [NousResearch/hermes-agent](https://github.com/NousResearch/hermes-agent) 及其配套仓库 [hermes-agent-self-evolution](https://github.com/NousResearch/hermes-agent-self-evolution) 的源码与架构文档，深度分析 Agent 级别自我进化能力的设计范式。

---

## 一、Hermes Agent 自我进化的整体架构

Hermes Agent 的核心定位是 **"The agent that grows with you"** — 一个具备闭环学习能力的 AI Agent。其自我进化能力分为两个层面：

| 层面 | 机制 | 运行时 | 进化粒度 |
|:---|:---|:---|:---|
| **运行时自适应**（Runtime） | Memory + Skills + Session Search | 每次对话中/跨会话 | 知识积累、行为模式固化 |
| **离线进化优化**（Offline） | DSPy + GEPA 进化管线 | 独立优化流程 | Skill 文本、Prompt、工具描述、代码 |

```
┌─────────────────────────────────────────────────────────────────┐
│                    运行时自适应层（Online）                        │
│                                                                  │
│  ┌──────────┐   ┌──────────────┐   ┌────────────────────┐       │
│  │ Memory   │   │ Skill 自动   │   │ Session Search     │       │
│  │ 持久记忆  │   │ 创建/改进    │   │ 跨会话检索         │       │
│  └────┬─────┘   └──────┬───────┘   └─────────┬──────────┘       │
│       │                 │                     │                   │
│       └─────────────────┼─────────────────────┘                   │
│                         ▼                                         │
│              ┌─────────────────────┐                              │
│              │  AIAgent 核心循环    │                              │
│              │  (run_agent.py)      │                              │
│              └─────────────────────┘                              │
└─────────────────────────────────────────────────────────────────┘
                          │ 产出执行轨迹 (Trajectories)
                          ▼
┌─────────────────────────────────────────────────────────────────┐
│                    离线进化层（Offline）                           │
│                                                                  │
│  ┌──────────────┐   ┌──────────────┐   ┌──────────────────┐     │
│  │ GEPA 反思式  │   │ Darwinian    │   │ 持续改进循环      │     │
│  │ Prompt 进化  │   │ Code Evolver │   │ (Cron + Monitor) │     │
│  └──────────────┘   └──────────────┘   └──────────────────┘     │
│                                                                  │
│  输出: Git Branch + PR → 人工审核 → 合并                         │
└─────────────────────────────────────────────────────────────────┘
```

---

## 二、运行时自适应机制（三大闭环）

### 2.1 Memory 系统 — 知识的持久化与压缩

**设计哲学**：有界、策展式记忆，而非无限堆积。

```
~/.hermes/memories/
├── MEMORY.md    # Agent 个人笔记（2,200 chars 上限）
└── USER.md      # 用户画像（1,375 chars 上限）
```

**关键设计决策**：

| 设计点 | 实现方式 | 设计意图 |
|:---|:---|:---|
| 容量硬限制 | MEMORY 2,200 chars / USER 1,375 chars | 强制信息密度，避免 token 浪费 |
| 冻结快照注入 | 会话开始时一次性注入 system prompt | 保护 prefix cache，降低推理成本 |
| Agent 自主管理 | 通过 `memory` tool 的 add/replace/remove | Agent 自己决定什么值得记住 |
| 安全扫描 | 写入前检测注入/泄露模式 | 防止 memory 被用作攻击向量 |
| 容量满时策略 | 返回错误 + 当前条目，Agent 自行合并 | 迫使 Agent 学会信息压缩 |

**进化意义**：Memory 是 Agent 的"短期进化"载体 — 它让 Agent 在不修改代码的情况下，通过积累事实性知识来改善后续行为。

### 2.2 Skills 系统 — 程序性记忆的自动固化

**核心机制**：Agent 在完成复杂任务后，自动将成功路径固化为可复用的 Skill。

```python
# Agent 创建 Skill 的触发条件（源码逻辑）：
# 1. 完成 5+ 工具调用的复杂任务
# 2. 遇到错误/死胡同后找到正确路径
# 3. 用户纠正了 Agent 的方法
# 4. 发现了非平凡的工作流
```

**Skill 的生命周期**：

```
发现非平凡工作流 → skill_manage(create) → SKILL.md 写入
                                              │
后续使用中发现改进点 → skill_manage(patch) ←──┘
                                              │
使用频率下降/过时 → skill_manage(delete) ←────┘
```

**渐进式加载（Progressive Disclosure）**：

```
Level 0: skills_list()           → 名称+描述列表    (~3k tokens)
Level 1: skill_view(name)        → 完整内容+元数据   (按需)
Level 2: skill_view(name, path)  → 特定参考文件      (按需)
```

**进化意义**：Skills 是 Agent 的"中期进化"载体 — 将一次性的问题解决经验转化为可复用的程序性知识，且在使用中持续自我改进。

### 2.3 Session Search — 跨会话的经验检索

```
SessionDB (SQLite + FTS5)
    │
    ├── 全文检索：关键词匹配历史对话
    ├── 会话谱系：压缩产生的父子关系追踪
    └── 滚动浏览：在找到的会话中前后翻阅
```

**与 Memory 的分工**：
- Memory = 始终在上下文中的关键事实（~1,300 tokens 固定成本）
- Session Search = 按需检索的完整历史（零 token 成本直到被调用）

---

## 三、离线进化管线（hermes-agent-self-evolution）

### 3.1 GEPA — 反思式 Prompt 进化

[GEPA (Genetic-Pareto)](https://arxiv.org/html/2507.19457v1) 是 ICLR 2026 Oral 论文提出的优化器，核心创新在于：**不仅知道"失败了"，还能理解"为什么失败"**。

```
传统进化优化：
  变异 → 评估（pass/fail）→ 选择 → 下一代

GEPA 反思式进化：
  变异 → 评估 → 读取执行轨迹 → 理解失败原因 → 定向改进 → 下一代
```

**性能对比**（论文数据）：
- 比 GRPO（强化学习）平均高 6pp，最高 19pp
- 使用的 rollouts 少 35 倍
- 比 MIPROv2（前代 DSPy 优化器）高 10%+
- 仅需 3 个样本即可启动优化

### 3.2 五阶段进化计划

| 阶段 | 优化目标 | 引擎 | 风险等级 | 状态 |
|:---|:---|:---|:---|:---|
| Phase 1 | Skill 文件 (SKILL.md) | DSPy + GEPA | 低 | ✅ 已实现 |
| Phase 2 | 工具描述文本 | DSPy + GEPA | 低 | 🔲 规划中 |
| Phase 3 | System Prompt 各段落 | DSPy + GEPA | 中 | 🔲 规划中 |
| Phase 4 | 工具实现代码 | Darwinian Evolver | 高 | 🔲 规划中 |
| Phase 5 | 持续自动改进循环 | 全部 | — | 🔲 规划中 |

### 3.3 进化管线的核心流程

```
┌─────────────────────────────────────────────┐
│  1. 选择优化目标                              │
│     读取当前版本作为 baseline                  │
│                                              │
│  2. 构建评估数据集                            │
│     来源 A: 合成生成（强模型读 Skill → 生成用例）│
│     来源 B: SessionDB 挖掘（真实使用 + LLM 评分）│
│     来源 C: 手工黄金集（高价值 Skill）          │
│     来源 D: 自动评估（如植入 bug 看能否修复）    │
│                                              │
│  3. 包装为 DSPy Module                        │
│     Skill 文本 → dspy.Signature               │
│     Agent 工作流 → dspy.ReAct                  │
│                                              │
│  4. 运行 GEPA 优化器                          │
│     读取执行轨迹 → 理解失败原因 → 定向变异      │
│     5-10 轮迭代，每轮评估多个候选              │
│                                              │
│  5. 约束门控                                  │
│     pytest 100% 通过                          │
│     字符限制（Skill ≤15KB, 工具描述 ≤500 chars）│
│     语义保持（不偏离原始目的）                  │
│     Benchmark 不回退（TBLite ±2%）             │
│                                              │
│  6. 部署（需人工审批）                         │
│     Git branch + PR + 指标对比                 │
│     人工 review → merge                       │
└─────────────────────────────────────────────┘
```

### 3.4 评估数据策略

**多源评估数据构建**是进化管线的关键创新：

```python
# 评估数据来源优先级
eval_sources = {
    "synthetic": "强模型生成 15-30 个 (task, rubric) 对",
    "sessiondb": "从真实会话中挖掘 + LLM-as-judge 评分",
    "golden":    "手工策展的黄金测试集",
    "auto":      "自动评估（如 arxiv 搜索已知论文）"
}

# 评分方式：LLM-as-judge + 多维度 rubric
rubric = {
    "procedure_followed": "Agent 是否遵循了 Skill 的步骤？(0-1)",
    "output_correct":     "输出是否正确/有用？(0-1)",
    "conciseness":        "是否在 token 预算内？(0-1)"
}
```

### 3.5 安全护栏设计

| 护栏 | 机制 | 目的 |
|:---|:---|:---|
| 测试套件门控 | pytest 必须 100% 通过 | 功能正确性 |
| 字符/Token 限制 | 进化文本不得超限 | 防止进化膨胀 |
| Prompt Cache 兼容 | 不在会话中途热替换 | 保护推理性能 |
| 语义保持检查 | 与原文对比语义相似度 | 防止目的漂移 |
| PR 审核 | 所有变更通过 PR，禁止直接提交 | 人类兜底 |
| Benchmark 门控 | TBLite/YC-Bench 不回退 | 防止局部优化损害全局 |
| Holdout 测试集 | 训练/验证/测试三分 | 防止过拟合 |

---

## 四、关键设计模式提炼

### 4.1 模式一：分层进化（Layered Evolution）

```
┌─────────────────────────────────────────┐
│ Layer 4: 代码进化（最高风险，最强护栏）    │  Darwinian Evolver
├─────────────────────────────────────────┤
│ Layer 3: System Prompt 进化              │  GEPA + Benchmark Gate
├─────────────────────────────────────────┤
│ Layer 2: 工具描述进化                    │  GEPA + 交叉评估
├─────────────────────────────────────────┤
│ Layer 1: Skill 文本进化（最低风险）       │  GEPA + LLM-as-judge
├─────────────────────────────────────────┤
│ Layer 0: Memory/Session（运行时自适应）   │  Agent 自主管理
└─────────────────────────────────────────┘
```

**设计原则**：风险越高的层级，护栏越严格，进化频率越低。

### 4.2 模式二：反思式进化（Reflective Evolution）

传统优化只看结果（pass/fail），GEPA 的核心创新是**读取执行轨迹来理解失败原因**：

```
传统: "这个 Skill 在 3/10 个测试中失败了" → 随机变异
GEPA: "这个 Skill 在步骤 3 让 Agent 选错了工具，因为描述中
       '搜索文件'被误解为 grep 而非 search_files" → 定向修改步骤 3
```

这使得进化效率极高 — 仅需 3 个样本即可启动有效优化。

### 4.3 模式三：闭环数据飞轮（Data Flywheel）

```
真实使用 → SessionDB 积累 → 挖掘评估数据 → 优化 Skill/Prompt
    ↑                                              │
    └──────────── 改进后的 Agent 产生更好的会话 ────┘
```

关键洞察：**Agent 的每次使用都在为自己的进化积累训练数据**。

### 4.4 模式四：进化与运行时解耦

```
hermes-agent (运行时)          hermes-agent-self-evolution (进化)
┌──────────────────┐           ┌──────────────────────────┐
│ 正常运行，服务用户 │           │ 读取 → 优化 → 输出 PR     │
│ 产出执行轨迹      │ ────────► │ 不修改运行时代码          │
│ 不感知进化过程    │           │ 所有变更通过 Git PR        │
└──────────────────┘           └──────────────────────────┘
```

**设计意图**：进化过程不干扰正常运行，所有改进通过版本控制流入。

### 4.5 模式五：成本可控的进化

| 操作 | 成本 | 说明 |
|:---|:---|:---|
| GEPA 一次优化 | ~$2-10 | 纯 API 调用，无 GPU 训练 |
| Darwinian Evolver | ~$2-9/任务 | 代码变异 + 评估 |
| TBLite 快速门控 | ~$20-50 | 100 任务回归检查 |
| 完整验证 | ~$50-200 | TerminalBench2 + YC-Bench |

**关键约束**：整个进化管线不需要 GPU 训练，全部通过 API 调用完成文本变异和评估。

---

## 五、对 aPaaS Agent 系统的设计启示

结合我们的 aPaaS 元数据驱动平台，Agent 自我进化能力可以在以下维度借鉴：

### 5.1 Skill 系统映射

| Hermes 概念 | aPaaS Agent 映射 | 应用场景 |
|:---|:---|:---|
| SKILL.md | Agent 操作手册/SOP | 元数据配置最佳实践、实体创建流程 |
| 自动创建 Skill | 从成功操作中提取 SOP | 用户完成复杂配置后自动总结步骤 |
| Skill 进化 | SOP 持续优化 | 根据用户反馈改进操作指导 |

### 5.2 Memory 系统映射

| Hermes 概念 | aPaaS Agent 映射 | 应用场景 |
|:---|:---|:---|
| MEMORY.md | 租户级 Agent 记忆 | 记住租户的元模型命名偏好、常用字段类型 |
| USER.md | 用户画像 | 记住用户角色、权限范围、操作习惯 |
| Session Search | 操作历史检索 | "上次我配置那个审批流是怎么做的？" |

### 5.3 进化管线映射

```
aPaaS Agent 进化管线设计：

Phase 1: 操作 SOP 进化
  - 优化"创建实体"、"配置校验规则"等 SOP 的指导文本
  - 评估指标：用户完成率、操作步骤数、错误率

Phase 2: 工具描述进化
  - 优化 API 接口描述，让 Agent 更准确地选择正确接口
  - 评估指标：接口选择准确率、参数填充正确率

Phase 3: 对话策略进化
  - 优化 Agent 的提问策略、信息收集顺序
  - 评估指标：对话轮次、用户满意度、任务完成率
```

### 5.4 关键设计建议

1. **从 Skill 系统开始**：最低风险、最高价值。让 Agent 在帮助用户配置元数据的过程中积累 SOP，然后用 GEPA 优化这些 SOP。

2. **构建评估数据飞轮**：每次用户操作都是潜在的训练数据。记录操作轨迹 → 评分 → 用于优化。

3. **严格的护栏设计**：aPaaS 场景下错误成本更高（可能影响业务数据），需要比 Hermes 更严格的约束门控。

4. **租户级隔离进化**：不同租户的 Agent 应该独立进化，避免跨租户知识泄露。

5. **人工审核不可省略**：所有进化产出必须经过人工审核，尤其是涉及数据操作的 SOP 变更。

---

## 六、总结

Hermes Agent 的自我进化设计展示了一个完整的范式：

```
运行时自适应（Memory + Skills + Session Search）
        ↓ 产出执行轨迹
离线进化优化（GEPA 反思式进化）
        ↓ 通过 PR 流入
改进后的 Agent 继续运行
        ↓ 产出更好的轨迹
更高质量的进化...
```

**核心洞察**：
1. 进化不是一次性的，而是持续的闭环
2. 反思式进化（理解"为什么"失败）远优于盲目变异
3. 安全护栏的严格程度应与进化层级的风险成正比
4. Agent 的每次使用都在为自己的进化积累数据
5. 进化过程与运行时完全解耦，通过版本控制桥接

这套设计为我们的 aPaaS Agent 系统提供了清晰的参考路径：从运行时 Memory/Skill 积累开始，逐步引入离线进化管线，最终实现 Agent 能力的持续自主提升。

---

*参考来源：*
- [NousResearch/hermes-agent](https://github.com/NousResearch/hermes-agent) — 主仓库
- [NousResearch/hermes-agent-self-evolution](https://github.com/NousResearch/hermes-agent-self-evolution) — 进化管线
- [Hermes Agent 架构文档](https://hermes-agent.nousresearch.com/docs/developer-guide/architecture)
- [GEPA 论文 (ICLR 2026 Oral)](https://arxiv.org/html/2507.19457v1)
- [DSPy GEPA 文档](https://dspy.ai/api/optimizers/GEPA/overview/)
