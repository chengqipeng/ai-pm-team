# Skill 压缩边界识别 — 深度分析方案

## 一、问题定义

上下文压缩需要识别 Skill 执行的边界（起止位置），以便：
1. **Post-Skill Compact**：对已完成 Skill 的内部消息做压缩（20条→10条）
2. **§4.1 尾部保护**：确保正在执行的 Skill 不被压缩切断
3. **SkillResultAnchor**：从 Skill 结果中提取锚点

**核心难点**：Inline 模式的 Skill 没有明确的"执行结束"标记。

---

## 二、两种模式的消息结构差异

### Fork 模式（有明确终止标记 ✅）

```
主 Agent 消息链:
  [N]   AIMessage: tool_calls=[{name:"skills_tool", args:{skill_name:"竞品调研"}}]
  [N+1] ToolMessage(name="skills_tool"): "[SKILL_DONE:silent] 竞品调研 已将完整结果..."

子 Agent 消息链（独立 thread，不在主 Agent 中）:
  [0] HumanMessage: 任务指令
  ... 内部工具调用 ...
  [K] AIMessage: 最终结果
```

**可靠信号**：`ToolMessage` 内容以 `[SKILL_DONE:...]` 开头 → 确定是 fork 最终结果。

### Inline 模式（无终止标记 ⚠️）

```
主 Agent 消息链:
  [N]   AIMessage: tool_calls=[{name:"skills_tool", args:{skill_name:"竞品调研"}}]
  [N+1] ToolMessage(name="skills_tool"): "你是竞品调研专家...请按以下SOP执行..."
  [N+2] AIMessage: tool_calls=[{name:"web_search"}]     ← 按 SOP 执行
  [N+3] ToolMessage(name="web_search"): "..."
  ...
  [N+K] AIMessage: "分析报告完成..."                     ← 无标记，不确定是否是结束
  [N+K+1] AIMessage: tool_calls=[{name:"modify_data"}]  ← Skill 后续？独立决策？
```

**无可靠信号**：Inline 完成后 LLM 不会发出任何特殊标记。

---

## 三、穷举场景及边界识别需求

| # | 场景 | 消息拓扑 | 边界识别需求 |
|---|------|---------|-------------|
| S1 | 单个 Fork | `[H]→[skills_tool]→[TM:SKILL_DONE]→[AI:回复]→[H]` | 精确：(N, N+1) |
| S2 | 单个 Inline（短） | `[H]→[skills_tool]→[TM:prompt]→[AI:tool]→[TM]→[AI:回复]→[H]` | 理想：(N, N+5)，实际：(N, HumanMsg-1) |
| S3 | Inline + 后续独立工具 | `[H]→[skills_tool]→...Skill内部...→[AI:tool]→[TM]→[AI:最终]→[H]` | 理想：Skill 段和后续分开，实际：合并为一段 |
| S4 | 两个连续 Inline | `[H]→[skills_tool A]→...→[skills_tool B]→...→[H]` | 理想：两个段，实际：合并为一段 |
| S5 | Inline + Fork | `[H]→[skills_tool A inline]→...→[skills_tool B fork]→[TM:SKILL_DONE]→[H]` | A 段和 B 段分开 |
| S6 | Fork + Inline | `[H]→[skills_tool A fork]→[TM:SKILL_DONE]→[skills_tool B inline]→...→[H]` | A 段和 B 段分开 |
| S7 | Inline 正在执行 | `[H]→[skills_tool]→[TM:prompt]→[AI:tool]→[TM]→(waiting)` | 不识别为已完成 |
| S8 | 两个 Inline 中间有独立操作 | `[H]→[skills_tool A]→...→[AI:独立]→[TM]→[skills_tool B]→...→[H]` | 合并为一段 |
| S9 | 超大 Inline (35+ 条) | `[H]→[skills_tool]→[TM:prompt]→...(35条)...→[AI:回复]→[H]` | 整段识别 |
| S10 | 上一轮 Inline + 本轮追问 | `[H1]→[skills_tool]→...→[AI]→[H2]→[AI:tool]→[TM]→[AI]` | 上一轮段和本轮分开 |

---

## 四、分析：精确切分 vs 粗粒度合并

### 方案 A：精确切分每个 Skill（理想但不可行）

需要知道"LLM 什么时候认为 Skill SOP 执行完毕"——这是 LLM 的内部状态，外部无法观察。

**可能的信号（都不可靠）**：
- AIMessage 无 tool_calls → 可能是 Skill 总结，也可能是中间思考
- AIMessage 内容包含"完成"/"报告" → 启发式太脆弱
- SkillContext 被清除 → Inline 模式下 context 不会被主动清除（一直持续到下一个 Skill 或会话结束）

**结论**：不可行。

### 方案 B：以 `skills_tool` 调用为分割点

**规则**：
- 每个 `skills_tool` 调用开始一个新的"Skill 段"
- 上一个 Skill 段在新 `skills_tool` 调用的前一条消息结束
- 最后一个 Skill 段在 `HumanMessage` 前一条消息结束

**场景 S4 示例**：
```
[0] skills_tool A → Skill 段 A 开始
[1] TM:prompt_A
[2] web_search
[3] TM
[4] AI:回复_A
[5] query_data      ← 归属不确定（A 的后续？独立？B 的准备？）
[6] TM
[7] skills_tool B   ← Skill 段 B 开始 → 段 A 终止于 [6]
[8] TM:prompt_B
[9] analyze_data
[10] TM
[11] AI:最终回复     ← 段 B 终止于 [11]（下一条是 HumanMessage）
[12] HumanMessage
```

**问题**：[5]-[6] 被划入"段 A"还是"段 B"？按此方案划入段 A。

**Post-Skill Compact 对段 A 的处理**：
```
段 A = [0]-[6]，共 7 条
protect_head = 2: [0],[1]
protect_tail = 5: [2]-[6]（由于 7-2=5，中间为空）
→ 实际不触发压缩（段不够长）
```

这个方案的问题：**段太短时（<8条）不触发 Post-Skill Compact**。但这不是问题——短段本身不需要压缩。

### 方案 C（推荐）：利用 `[SKILL_DONE]` 标记 + `skills_tool` 分割 + HumanMessage 终止

**三重信号组合**：

| 信号 | 可靠性 | 含义 |
|------|--------|------|
| `ToolMessage` 内容以 `[SKILL_DONE:` 开头 | **100%** | Fork Skill 执行完毕（终止标记） |
| 新的 `skills_tool` 调用 | **100%** | 上一个 Skill 肯定结束了 |
| `HumanMessage` | **100%** | 当前轮次所有 Skill 肯定结束了 |
| 消息末尾 + 最后是 ToolMessage/AI(tool_calls) | **95%** | Skill 可能还在执行 |

**核心策略**：
1. Fork 模式用 `[SKILL_DONE:]` 精确定位终止 → 独立的 2 条段
2. Inline 模式用 `skills_tool` / `HumanMessage` 做"至少到这里结束"的判断
3. 多个 inline Skill 之间**各自独立成段**（以新 skills_tool 为分割点）
4. 每个段独立做 Post-Skill Compact

---

## 五、推荐实现方案

```python
def find_completed_skill_boundaries(messages):
    """
    策略：按 skills_tool 调用逐个切分，每个切分段独立处理
    
    Fork: [skills_tool] → [TM:SKILL_DONE] = 2 条，不触发 compact
    Inline: [skills_tool] → (内部工具) → 终止于:
            - 下一个 skills_tool（不含）
            - 或 HumanMessage（不含）
            - 或消息末尾（如果看起来已完成）
    """
    boundaries = []
    
    # 1. 收集所有 skills_tool 调用位置
    skill_starts = []
    for i, msg in enumerate(messages):
        if isinstance(msg, AIMessage) and tool_calls contains "skills_tool":
            skill_starts.append(i)
    
    # 2. 对每个 skills_tool 调用确定其终止位置
    for idx, start in enumerate(skill_starts):
        # 找对应的 ToolMessage(name="skills_tool")
        tm_idx = find_next_skills_tool_tm(messages, start)
        if tm_idx is None:
            continue  # 正在启动中
        
        # 检查是否 fork（内容含 [SKILL_DONE:]）
        content = messages[tm_idx].content or ""
        if content.strip().startswith("[SKILL_DONE:"):
            # Fork: 精确段 = [start, tm_idx]
            boundaries.append((start, tm_idx))
            continue
        
        # Inline: 从 tm_idx 向后找终止
        # 终止 = min(下一个 skills_tool 的 start - 1, 下一个 HumanMessage - 1, 消息末尾)
        next_boundary = len(messages) - 1  # 默认到末尾
        
        # 检查是否有下一个 skills_tool
        if idx + 1 < len(skill_starts):
            next_boundary = min(next_boundary, skill_starts[idx + 1] - 1)
        
        # 检查是否有 HumanMessage
        for j in range(tm_idx + 1, next_boundary + 1):
            if isinstance(messages[j], HumanMessage):
                next_boundary = j - 1
                break
        
        # 检查是否正在执行中（末尾是工具调用）
        if next_boundary == len(messages) - 1:
            last = messages[next_boundary]
            if isinstance(last, ToolMessage) or (isinstance(last, AIMessage) and last.tool_calls):
                continue  # 可能还在执行，不加入
        
        if next_boundary > start + 1:  # 段长度 > 2 才有意义
            boundaries.append((start, next_boundary))
    
    return boundaries
```

---

## 六、各场景验证

| # | 场景 | 识别结果 | Post-Skill Compact 行为 | 正确性 |
|---|------|---------|------------------------|--------|
| S1 | 单个 Fork | `[(N, N+1)]` → 2条 | 不触发（<8条） | ✅ |
| S2 | 单个 Inline（短，6条） | `[(N, N+5)]` | 不触发（<8条） | ✅ |
| S3 | Inline + 后续工具（12条） | `[(N, N+11)]` → 包含后续工具 | 触发：head=2, tail=5, 中间压缩 | ✅ 后续工具在 tail 保护区内 |
| S4 | 两个连续 Inline | `[(N, M-1), (M, K)]` 各自独立 | 各段独立处理 | ✅ |
| S5 | Inline + Fork | `[(N, M-1), (M, M+1)]` | 段1 触发，段2 不触发 | ✅ |
| S6 | Fork + Inline | `[(N, N+1), (N+2, K)]` | 段1 不触发，段2 触发 | ✅ |
| S7 | Inline 正在执行 | 不加入 boundaries | 不触发 | ✅ §4.1 保护 |
| S8 | 两 Inline 中间有独立操作 | `[(N, M-1), (M, K)]` 独立操作划入段1尾部 | 段1 的 tail=5 覆盖独立操作 | ✅ |
| S9 | 超大 Inline (35+ 条) | `[(N, K)]` → 一个大段 | 触发：head=2, tail=5, 中间大量压缩 | ✅ |
| S10 | 上一轮 Inline + 本轮追问 | `[(N, H1-1)]` 上一轮段到 H1 之前 | 触发压缩上一轮 Skill | ✅ 本轮不受影响 |

---

## 七、与 §4.1 保护区的配合

`_find_enclosing_skill_start` 也需要同步更新逻辑：

**原始**：从 cut_idx 向前找 `skills_tool` 调用，向后找 `ToolMessage(name="skills_tool")` 作为终止。

**问题**：Inline 模式下找到的第一个 `ToolMessage(name="skills_tool")` 是 prompt 返回，不是终止。

**修复**：
```python
def _find_enclosing_skill_start(messages, cut_idx, head_end):
    # 从 cut_idx 向前找 skills_tool 调用
    skill_start = find_preceding_skills_tool_call(messages, cut_idx, head_end)
    if skill_start is None:
        return None
    
    # 找对应的 ToolMessage
    tm_idx = find_next_skills_tool_tm(messages, skill_start)
    if tm_idx is None:
        return skill_start  # 正在启动
    
    # Fork 检查
    if messages[tm_idx].content.startswith("[SKILL_DONE:"):
        # Fork: 边界只有 [skill_start, tm_idx]
        if skill_start <= cut_idx <= tm_idx:
            return skill_start
        return None  # cut_idx 在 fork 之后
    
    # Inline: 边界延伸到下一个 skills_tool / HumanMessage
    inline_end = find_inline_end(messages, tm_idx, ...)
    if skill_start <= cut_idx <= inline_end:
        return skill_start
    
    return None  # cut_idx 在 inline 段之后
```

---

## 八、关键设计决策总结

| 决策 | 选择 | 原因 |
|------|------|------|
| Fork 终止识别 | `[SKILL_DONE:]` 内容前缀 | 100% 可靠信号，代码中已有 |
| Inline 终止识别 | 下一个 `skills_tool` 或 `HumanMessage` | 唯二的确定性终止信号 |
| 多 Inline Skill 切分 | 各自独立成段 | 每段独立 compact，tail 保护更精准 |
| "Skill 后续独立操作"归属 | 划入前一个 Skill 段的尾部 | 被 protect_tail 保护，不会被压缩 |
| Inline 正在执行判断 | 末尾是 ToolMessage 或 AI(tool_calls) | 95%+ 准确率 |
| 单个段是否触发 compact | 段长度 > min_skill_messages(8) | 短段不需要压缩 |

---

## 九、实施优先级

1. **P0**：`[SKILL_DONE:]` 前缀检测（区分 Fork/Inline）— 0.5 天
2. **P0**：以 `skills_tool` 调用为分割点，各段独立识别 — 1 天  
3. **P1**：`_find_enclosing_skill_start` 同步更新（支持 Inline 段）— 0.5 天
4. **P2**：Inline 模式增加显式终止标记（需改 Skill 执行流程）— 2 天

P2 是最终解：在 inline Skill SOP 完成后，让系统主动注入一条 `[INLINE_SKILL_DONE: skill_name]` 标记到消息链。但这需要改动 Agent 执行循环逻辑，短期内用 P0+P1 的启发式方案足够。
