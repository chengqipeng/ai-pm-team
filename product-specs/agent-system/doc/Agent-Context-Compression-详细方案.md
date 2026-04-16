# Agent 上下文压缩详细方案

> 本文档定义 Agent 系统的上下文管理和压缩机制。上下文窗口是 Agent 最稀缺的资源——所有对话历史、工具结果、系统提示词都在争夺有限的 token 空间。压缩策略直接决定了 Agent 能处理多复杂的任务。

---

## 一、问题定义

### 1.1 上下文窗口的构成

```
一次 LLM 调用的 token 分配:

┌─────────────────────────────────────────────────────┐
│                  模型上下文窗口                        │
│              （如 DeepSeek: 64K tokens）               │
│                                                      │
│  ┌──────────────┐                                    │
│  │ System Prompt │  ~2K tokens（固定）                 │
│  │ 工具定义       │  ~3K tokens（16 个工具的 schema）   │
│  └──────────────┘                                    │
│  ┌──────────────┐                                    │
│  │ 对话历史      │  动态增长（每轮 +500~5000 tokens）  │
│  │ 工具调用结果   │  可能很大（单次查询结果 10K+）       │
│  └──────────────┘                                    │
│  ┌──────────────┐                                    │
│  │ 输出空间      │  ~8K tokens（max_tokens 配置）      │
│  └──────────────┘                                    │
│                                                      │
│  可用于对话历史的空间 = 窗口大小 - system - 工具定义 - 输出 │
│  ≈ 64K - 2K - 3K - 8K = 51K tokens                  │
│                                                      │
└─────────────────────────────────────────────────────┘
```

### 1.2 为什么需要压缩

一个典型的 2B 业务任务（如"分析上个月的销售数据并生成报告"）可能产生：
- 5 轮 LLM 对话 × 500 tokens/轮 = 2,500 tokens
- 3 次 query_data 调用 × 5,000 tokens/结果 = 15,000 tokens
- 1 次 analyze_data 调用 × 3,000 tokens = 3,000 tokens
- 1 次 web_search 调用 × 2,000 tokens = 2,000 tokens
- 总计: ~22,500 tokens

如果任务更复杂（10+ 步骤），很容易超过 51K 的可用空间。不压缩就会：
1. LLM 调用失败（超出上下文窗口）
2. 早期的重要信息被截断
3. LLM 的推理质量下降（上下文太长时注意力分散）

---

## 二、压缩策略体系

### 2.1 五层压缩策略（按执行顺序）

```
每轮 LLM 调用前，ContextMiddleware.before_step() 按以下顺序执行:

Layer 1: 工具结果预算控制（Tool Result Budget）
  ↓ 每个工具结果不超过 max_result_size_chars
Layer 2: 大结果外置（Result Eviction）
  ↓ 超大结果写入文件，用摘要+路径替代
Layer 3: 历史裁剪（History Snip）
  ↓ 保留最近 N 轮，裁剪更早的
Layer 4: 旧结果清理（Microcompact）
  ↓ 清除旧的工具调用结果，只保留最近的
Layer 5: LLM 摘要压缩（Summarize）
  ↓ 调用 LLM 对历史对话生成摘要

触发条件:
  Layer 1-2: 每轮都执行（轻量，无 LLM 调用）
  Layer 3-4: 上下文占比 > 50% 时执行（轻量，无 LLM 调用）
  Layer 5:   上下文占比 > 85% 时执行（重量，需要 LLM 调用）
```

### 2.2 Layer 1: 工具结果预算控制

**时机**: 每次工具调用返回后立即执行（在 ExecutionNode 内部）

**逻辑**:
```
tool_result = await tool.call(input, context)

budget = tool.max_result_size_chars  # 每个工具有自己的预算

if len(tool_result.content) > budget:
    # 截断，保留头部 + 尾部
    head = tool_result.content[:budget * 0.7]   # 前 70%
    tail = tool_result.content[-budget * 0.2:]  # 后 20%
    tool_result.content = (
        head + 
        f"\n\n... [结果已截断，原始 {len(tool_result.content)} 字符，"
        f"保留前 {len(head)} + 后 {len(tail)} 字符] ...\n\n" +
        tail
    )
```

**各工具的预算配置**:

| 工具 | max_result_size_chars | 理由 |
|------|----------------------|------|
| query_data | 50,000 | 查询结果可能包含多条记录 |
| modify_data | 5,000 | 操作结果通常很短 |
| analyze_data | 30,000 | 统计结果中等大小 |
| query_schema | 100,000 | 元数据定义需要完整，截断会导致理解错误 |
| modify_schema | 5,000 | 操作结果通常很短 |
| query_permission | 20,000 | 权限配置中等大小 |
| web_search | 30,000 | 搜索结果 |
| web_fetch | 50,000 | 网页内容可能很长 |
| company_info | 30,000 | 工商信息 |
| financial_report | 50,000 | 财报数据可能很大 |
| ask_user | 无限制 | 用户输入不截断 |
| search_memories | 20,000 | 记忆搜索结果 |
| save_memory | 1,000 | 确认信息很短 |
| send_notification | 1,000 | 确认信息很短 |

### 2.3 Layer 2: 大结果外置（Result Eviction）

**时机**: 工具结果超过 budget 的 2 倍时，不截断而是外置到文件

**逻辑**:
```
if len(tool_result.content) > budget * 2:
    # 结果太大，截断不够，需要外置
    file_path = await checkpoint_store.save_tool_result(
        session_id, tool_use_id, tool_result.content
    )
    
    # 生成摘要替代原始内容
    summary = _generate_local_summary(tool_result.content, max_chars=2000)
    
    tool_result.content = (
        f"{summary}\n\n"
        f"[完整结果已保存到文件: {file_path}，共 {len(original)} 字符。"
        f"如需查看完整内容，请使用相关工具重新查询。]"
    )
```

**本地摘要生成**（不调用 LLM，纯规则）:
```python
def _generate_local_summary(content: str, max_chars: int = 2000) -> str:
    """从大结果中提取关键信息，不调用 LLM"""
    lines = content.split('\n')
    
    # 策略 1: 如果是 JSON 数组，提取记录数和前 3 条
    if content.strip().startswith('[') or '"records"' in content[:200]:
        try:
            data = json.loads(content)
            records = data if isinstance(data, list) else data.get('records', [])
            total = data.get('total', len(records)) if isinstance(data, dict) else len(records)
            preview = json.dumps(records[:3], ensure_ascii=False, indent=2)
            return f"共 {total} 条记录，前 3 条预览:\n{preview[:max_chars]}"
        except json.JSONDecodeError:
            pass
    
    # 策略 2: 取头部 + 尾部
    if len(content) > max_chars:
        head = content[:int(max_chars * 0.7)]
        tail = content[-int(max_chars * 0.2):]
        return f"{head}\n...\n{tail}"
    
    return content[:max_chars]
```

### 2.4 Layer 3: 历史裁剪（History Snip）

**时机**: ContextMiddleware.before_step() 中，当上下文占比 > 50% 时执行

**逻辑**:
```
estimated_tokens = context.llm.estimate_tokens(all_messages_text)
window_size = context.llm.get_context_window_size()
ratio = estimated_tokens / window_size

if ratio > CONTEXT_COMPRESS_RATIO (0.5):
    # 保留最近 N 轮对话，裁剪更早的
    keep_recent = 20  # 保留最近 20 条消息
    
    if len(state.messages) > keep_recent:
        snipped = state.messages[:-(keep_recent)]
        state.messages = state.messages[-(keep_recent):]
        
        # 在裁剪点插入标记
        state.messages.insert(0, Message(
            role=MessageRole.SYSTEM,
            content=f"[历史对话已裁剪，移除了 {len(snipped)} 条早期消息]"
        ))
```

**裁剪规则**:
1. 永远不裁剪 system prompt
2. 保留最近 20 条消息（可配置）
3. tool_use 和 tool_result 必须成对保留（不能只留 tool_use 没有 result）
4. 裁剪点插入标记消息，让 LLM 知道有历史被移除

### 2.5 Layer 4: 旧结果清理（Microcompact）

**时机**: 与 Layer 3 同时执行（上下文占比 > 50%）

**逻辑**: 对保留的消息中，清除旧的工具调用结果（只保留最近 5 个工具结果的完整内容，更早的替换为一行摘要）

```
tool_result_messages = [
    (i, msg) for i, msg in enumerate(state.messages)
    if msg.tool_result_blocks
]

if len(tool_result_messages) > 5:
    # 保留最近 5 个工具结果，清除更早的
    for idx, msg in tool_result_messages[:-5]:
        for block in msg.tool_result_blocks:
            if not block.is_error:  # 错误结果保留（LLM 需要知道什么失败了）
                original_len = len(block.content)
                block.content = f"[旧工具结果已压缩，原始 {original_len} 字符]"
```

**清理规则**:
1. 错误结果不清理（LLM 需要知道什么失败了，避免重复犯错）
2. 最近 5 个工具结果保留完整内容
3. 更早的工具结果替换为一行摘要
4. query_schema 的结果不清理（元数据定义在整个任务中都需要）

### 2.6 Layer 5: LLM 摘要压缩（Summarize）

**时机**: ContextMiddleware.before_step() 中，当上下文占比 > 85% 时执行

**这是最重量级的压缩，需要调用 LLM。**

**执行流程**:
```
if ratio > CONTEXT_FORCE_COMPRESS_RATIO (0.85):
    
    # Step 1: 压缩前记忆刷新（借鉴 Hermes）
    if context.memory is not None:
        extracted = await context.memory.flush_before_compress(
            messages_to_compress
        )
        # 将即将被压缩的消息中的业务知识提取并持久化
        # 防止压缩后知识丢失
    
    # Step 2: 确定压缩范围
    # 保护最后 N 条消息不被压缩
    protect_last_n = 10
    messages_to_compress = state.messages[:-protect_last_n]
    messages_to_keep = state.messages[-protect_last_n:]
    
    # Step 3: 调用 LLM 生成摘要
    compress_prompt = COMPRESS_PROMPT.format(
        message_count=len(messages_to_compress),
    )
    
    summary_response = await context.llm.call(
        system_prompt=compress_prompt,
        messages=[{
            "role": "user",
            "content": _format_messages_for_summary(messages_to_compress)
        }],
        max_tokens=2000,  # 摘要不超过 2000 tokens
    )
    
    summary_text = _extract_text(summary_response)
    
    # Step 4: 重建消息历史
    state.messages = [
        Message(
            role=MessageRole.SYSTEM,
            content=f"[以下是之前对话的摘要]\n{summary_text}\n[摘要结束，以下是最近的对话]",
        ),
    ] + messages_to_keep
```

**压缩 Prompt**:
```python
COMPRESS_PROMPT = """你是一个对话摘要专家。请将以下 {message_count} 条对话消息压缩为一段简洁的摘要。

## 必须保留的信息
- 用户的原始请求和意图
- 已完成的步骤和关键结果
- 当前任务的进展状态（完成了什么，还剩什么）
- 重要的数据发现和结论
- 遇到的错误和解决方式
- 用户表达的偏好和约束

## 可以省略的信息
- 工具调用的详细参数
- 工具返回的原始数据（只保留关键数字和结论）
- 中间的试错过程（只保留最终成功的方法）
- 重复的确认对话

## 输出格式
直接输出摘要文本，不要加标题或格式标记。控制在 1500 字以内。"""
```

---

## 三、压缩触发的完整时序

```
ContextMiddleware.before_step(state, node, context):
  
  # 1. 估算当前上下文大小
  all_text = state.system_prompt + ''.join(str(m.content) for m in state.messages)
  estimated_tokens = context.llm.estimate_tokens(all_text)
  window_size = context.llm.get_context_window_size()
  ratio = estimated_tokens / (window_size - 8192)  # 减去输出空间
  
  # 2. 根据占比决定压缩级别
  if ratio <= 0.5:
      # 安全区间，不压缩
      return state
  
  if ratio <= 0.85:
      # 警告区间: 执行轻量压缩（Layer 3 + 4，无 LLM 调用）
      state = _snip_history(state, keep_recent=20)
      state = _microcompact(state, keep_recent_results=5)
      
      callbacks.on_status_change("executing", "compressing")
      return state
  
  # 危险区间: 执行重量压缩（Layer 3 + 4 + 5，需要 LLM 调用）
  callbacks.on_status_change("executing", "compressing")
  
  # 先刷新记忆
  if context.memory:
      await context.memory.flush_before_compress(
          [{"role": m.role.value, "content": str(m.content)} 
           for m in state.messages[:-10]]
      )
  
  # 轻量压缩
  state = _snip_history(state, keep_recent=20)
  state = _microcompact(state, keep_recent_results=5)
  
  # 如果轻量压缩后仍然超过 85%，执行 LLM 摘要
  new_ratio = _estimate_ratio(state, context)
  if new_ratio > 0.85:
      state = await _summarize(state, context, protect_last_n=10)
  
  return state
```

---

## 四、工具结果预算与压缩的协作

```
工具执行时（ExecutionNode 内部）:
  tool_result = await tool.call(input, context)
  │
  ├── Layer 1: 结果预算控制
  │   len(result) > max_result_size_chars?
  │   → 截断（保留头 70% + 尾 20%）
  │
  ├── Layer 2: 大结果外置
  │   len(result) > max_result_size_chars * 2?
  │   → 写入文件 + 生成本地摘要替代
  │
  └── 追加到 state.messages

下一轮 LLM 调用前（ContextMiddleware.before_step）:
  │
  ├── 估算上下文占比
  │
  ├── > 50%: Layer 3 + 4
  │   → 裁剪早期历史
  │   → 清除旧工具结果（保留最近 5 个）
  │
  └── > 85%: Layer 5
      → 记忆刷新（防止知识丢失）
      → LLM 摘要压缩
```

---

## 五、特殊场景处理

### 5.1 query_schema 结果的保护

元数据定义（query_schema 的结果）在整个任务执行过程中都需要——LLM 需要知道业务对象有哪些字段才能正确构建查询条件。

**规则**: query_schema 的工具结果在 Layer 4（Microcompact）中不被清理，即使它不在最近 5 个结果中。

```python
def _microcompact(state, keep_recent_results=5):
    # ...
    for idx, msg in tool_result_messages[:-keep_recent_results]:
        for block in msg.tool_result_blocks:
            tool_name = _find_tool_name(block.tool_use_id, state.messages)
            if tool_name == "query_schema":
                continue  # 保护元数据定义，不清理
            if not block.is_error:
                block.content = f"[旧工具结果已压缩]"
```

### 5.2 子 Agent 的压缩策略

子 Agent 有独立的上下文窗口，但轮次更少（默认 15-30 轮），通常不需要压缩。

**规则**:
- 子 Agent 的 ContextMiddleware 使用更激进的阈值：50% → 40%，85% → 70%
- 子 Agent 不执行 Layer 5（LLM 摘要），因为轮次少，Layer 3+4 足够
- 子 Agent 的 keep_recent 更小：20 → 10

### 5.3 HITL 暂停恢复后的压缩

用户可能在 HITL 暂停后很久才恢复（几分钟到几小时）。恢复时上下文可能已经很大。

**规则**: `GraphEngine.resume()` 恢复后，在进入主循环前先执行一次 ContextMiddleware 压缩检查。

### 5.4 压缩失败的降级

Layer 5（LLM 摘要）可能失败（LLM 调用超时、限流等）。

**降级策略**:
```
LLM 摘要失败:
  → 不中断主流程
  → 降级为更激进的 Layer 3: keep_recent 从 20 降到 10
  → 降级为更激进的 Layer 4: keep_recent_results 从 5 降到 2
  → 记录日志: "LLM 摘要压缩失败，已降级为激进裁剪"
```

---

## 六、配置参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| CONTEXT_COMPRESS_RATIO | 0.5 | 上下文占比超过此值触发轻量压缩 |
| CONTEXT_FORCE_COMPRESS_RATIO | 0.85 | 上下文占比超过此值触发 LLM 摘要压缩 |
| SNIP_KEEP_RECENT | 20 | 历史裁剪时保留的最近消息数 |
| MICROCOMPACT_KEEP_RESULTS | 5 | 旧结果清理时保留的最近工具结果数 |
| SUMMARIZE_PROTECT_LAST_N | 10 | LLM 摘要时保护的最近消息数 |
| SUMMARIZE_MAX_TOKENS | 2000 | LLM 摘要的最大 token 数 |
| SUB_AGENT_COMPRESS_RATIO | 0.4 | 子 Agent 的轻量压缩阈值 |
| SUB_AGENT_FORCE_RATIO | 0.7 | 子 Agent 的强制压缩阈值 |
| SUB_AGENT_KEEP_RECENT | 10 | 子 Agent 的历史保留数 |

---

## 七、与其他模块的交互

| 模块 | 交互方式 |
|------|---------|
| ExecutionNode | Layer 1+2 在工具执行后立即执行（ExecutionNode 内部） |
| ContextMiddleware | Layer 3+4+5 在每轮 LLM 调用前执行（before_step） |
| memory-plugin | Layer 5 执行前调用 flush_before_compress() 刷新记忆 |
| CheckpointStore | Layer 2 的大结果外置写入 CheckpointStore |
| AgentCallbacks | 压缩时触发 on_status_change("executing", "compressing") |
| LLM Plugin | Layer 5 调用 LLM 生成摘要；estimate_tokens() 估算 token 数 |
| AgentLimits | 阈值配置来源 |
