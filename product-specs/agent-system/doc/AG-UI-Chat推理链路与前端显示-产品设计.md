# AG-UI Chat 推理链路与前端显示 — Bug 修复记录

## 问题描述（2026-05-26）

用户反馈三个问题：
1. **刷新后链路数据丢失**：页面刷新后，右侧推理链路面板只显示极少数 span（如仅 1 个"记忆提取"），大量链路步骤丢失
2. **重复用户消息**：对话框中只输入了一次消息，但刷新后显示两个用户问题气泡
3. **推理链路位置不正确**：刷新后内联推理链路显示在错误的位置

## 根因分析

### 问题 1：链路数据丢失（核心 Bug）

**数据流**：
```
用户发送消息 → AG-UI SSE 流 → tracing_middleware 收集 spans → 流结束 → on_trace_finish 持久化
                                                                              ↓
刷新页面 → /api/conversations/:id/messages → read_trace_detail(trace_id) → 从 PG 读取 spans
```

**Bug 位置**：`src/api/a2ui_routes.py` 第 430-440 行

AG-UI 模式下 `tracer.start_trace()` 只在内存中创建了 trace 对象，但**没有调用 `trace_writer.on_trace_start(trace)`** 将记录写入 `ai_trace` 表。

而 SSE 模式（`server.py`）中是有这个调用的：
```python
trace = tracer.start_trace(thread_id, req.message, ...)
trace_writer.on_trace_start(trace)  # ← SSE 模式有，AG-UI 模式缺失
```

后果链：
1. `ai_trace` 表中没有该 trace_id 的记录
2. `on_trace_finish` 中 `TraceDAO.finish()` 执行 `UPDATE ... WHERE trace_id=%s`，匹配 0 行，静默失败
3. `ai_trace_span` 表中 spans 正常写入（INSERT 不依赖 ai_trace 记录）
4. 刷新后 `read_trace_detail(trace_id)` 先查 `ai_trace` 表，发现无记录直接返回 `None`
5. 前端拿到空 spans，链路数据丢失

### 问题 2：重复用户消息

**可能原因**：
- `_persist_message` 没有去重机制，如果 `on_trace_finish` 被异常重试或并发调用，同一个 trace 会写入多条 `ai_message` 记录
- 前端 `loadChat` 遍历所有消息记录，每条都渲染用户气泡

### 问题 3：推理链路位置不正确

**根因**：问题 1 导致 spans 为空或不完整，前端 `renderInlineSteps` 过滤后无核心步骤可渲染，但 `renderHistoricalTrace` 可能从降级逻辑获取到部分 span（如内存中的 live spans），导致显示位置与预期不符。

## 修复方案

### Fix 1：AG-UI 模式补充 `on_trace_start` 调用

**文件**：`src/api/a2ui_routes.py`

在 `tracer.start_trace()` 后立即调用 `trace_writer.on_trace_start(trace)`，确保 `ai_trace` 表中有记录。

### Fix 2：`_persist_message` 添加 trace_id 去重

**文件**：`src/store/trace_writer.py`

写入 `ai_message` 前先检查是否已存在相同 `trace_id` 的记录，避免重复写入。

### Fix 3：`read_trace_detail` 容错处理

**文件**：`src/store/trace_writer.py`

当 `ai_trace` 表中无记录时，不再直接返回 None，而是继续尝试从 `ai_trace_span` 表读取 spans（兼容历史脏数据）。

### Fix 4：前端过滤 `request`/`response` 标记 span

**文件**：`static/frontend.html`

- `HIDDEN_SPAN_TYPES` 增加 `response` 类型
- `renderHistoricalTrace` 预过滤掉 `request`/`response` 纯标记 span

## 影响范围

- 仅影响 AG-UI 模式的链路持久化和刷新恢复
- SSE 模式不受影响（已有 `on_trace_start` 调用）
- 修复后新产生的对话链路可正常恢复
- 历史脏数据通过 Fix 3 的容错逻辑兼容
