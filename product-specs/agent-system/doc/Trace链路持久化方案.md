# Trace 链路持久化方案

## 1. 问题定义

当前 Trace 数据全部存在内存中（`Tracer` 类的 `_traces` dict），进程重启即丢失。
index.html 前端需要完整的链路数据支撑 8 个页面：总览仪表盘、Trace Explorer、Trace 详情、Session 浏览器、工具调用分析、意图分析、告警中心、用量报表。

需要将 Trace 数据持久化到 PG（paas_ai schema），同时保持现有内存 Tracer 的实时性（SSE 推送）。

## 2. index.html 链路结构 → 数据库映射

### 2.1 Trace 详情页的链路节点

index.html 展示的一次完整 Trace 包含以下节点（按时间线排列）：

```
📋 context_build          120ms    ← before_agent 阶段
🔍 memory_retrieval       1,800ms  ← MemoryMiddleware
🧠 intent_analysis        600ms    ← 意图分析
🤖 llm_call               580ms    ← 首次 LLM（可能是意图判断）
🌲 hierarchical_search    400ms    ← 分层检索（skill 维度）
  ├─ 🔎 vector_search     80ms       子步骤
  ├─ ⚖️ rerank            60ms       子步骤
  ├─ 🔎 vector_search     70ms       子步骤
  └─ ⚖️ rerank            50ms       子步骤
🌲 hierarchical_search    350ms    ← 分层检索（resource 维度）
🌲 hierarchical_search    300ms    ← 分层检索（memory 维度）
🤖 llm_call Iter 1        2,200ms  ← ReAct 第 1 轮 LLM
🔧 tool:exec_command      500ms    ← 工具调用
🤖 llm_call Iter 2        1,800ms  ← ReAct 第 2 轮 LLM（final）
```

### 2.2 映射到 ai_trace_span 表

每个节点对应 `ai_trace_span` 的一行记录。子步骤通过 `parent_span_id` 关联父节点。

```
ai_trace_span 记录示例：

span_id  | parent | span_type            | span_name                    | duration_ms | metadata
---------|--------|----------------------|------------------------------|-------------|------------------
sp_01    |        | context_build        | context_build                | 120         | {message_count:12, estimated_tokens:4800}
sp_02    |        | memory_retrieval     | memory_retrieval             | 1800        | {query_used:"...", dimensions:[...], hit_count:5}
sp_03    |        | intent_analysis      | intent_analysis              | 600         | {task_type:"操作型", matched_skills:["verify_config"]}
sp_04    |        | llm_call             | llm_call                     | 580         | {output_tokens:200}
sp_05    |        | hierarchical_search  | hierarchical_search skill    | 400         | {search_type:"skill", hit_count:3}
sp_05a   | sp_05  | vector_search        | vector_search                | 80          | {dimension:"task_history", result_count:2}
sp_05b   | sp_05  | rerank               | rerank                       | 60          | {dimension:"task_history", scored_count:2}
sp_05c   | sp_05  | vector_search        | vector_search                | 70          | {dimension:"domain_knowledge", result_count:1}
sp_05d   | sp_05  | rerank               | rerank                       | 50          | {dimension:"domain_knowledge", scored_count:1}
sp_06    |        | hierarchical_search  | hierarchical_search resource | 350         | {search_type:"resource", hit_count:2}
sp_07    |        | hierarchical_search  | hierarchical_search memory   | 300         | {search_type:"memory", hit_count:1}
sp_08    |        | llm_call             | llm_call Iter 1              | 2200        | {iteration:1, output_tokens:5000, tool_calls:["exec_command"], is_final:false}
sp_09    |        | tool_call            | tool:exec_command            | 500         | {input:"...", output:"...", status:"success"}
sp_10    |        | llm_call             | llm_call Iter 2              | 1800        | {iteration:2, output_tokens:7200, is_final:true}
```

### 2.3 span_type 完整枚举

| span_type | 图标 | 说明 | 来源 | metadata 关键字段 |
|-----------|------|------|------|-------------------|
| context_build | 📋 | 上下文构建 | TracingMiddleware.before_agent | message_count, estimated_tokens |
| memory_retrieval | 🔍 | 记忆检索 | MemoryMiddleware | query_used, dimensions, hit_count, items_preview |
| intent_analysis | 🧠 | 意图分析 | TracingMiddleware.before_model | task_type, matched_skills, confidence |
| llm_call | 🤖 | LLM 调用 | TracingMiddleware.after_model | iteration, output_tokens, tool_calls, is_final |
| hierarchical_search | 🌲 | 分层检索 | FTSMemoryEngine.retrieve | search_type(skill/resource/memory), hit_count |
| vector_search | 🔎 | 向量搜索（子步骤） | FTSMemoryEngine.retrieve | dimension, query, result_count |
| rerank | ⚖️ | 重排序（子步骤） | FTSMemoryEngine.retrieve | dimension, scored_count |
| tool_call | 🔧 | 工具调用 | TracingMiddleware.wrap_tool_call | input, output, status |
| memory_extract | 📝 | 记忆提取 | MemoryMiddleware.aafter_agent | extracted_count, dimensions |
| clarification | ❓ | 澄清追问 | ClarificationMiddleware | clarification_type, question, options |
| content_review | 🛡️ | 内容审查 | ContentReviewTransformer | review_type, blocked_keywords |
| compression | 📦 | 上下文压缩 | SummarizationMiddleware | original_count, compressed_count |
| subagent | 🔀 | 子 Agent 委派 | AgentTool | agent_name, instruction |
| error | ❌ | 异常 | 各中间件 | error_type, error_message |
| request | 👤 | 用户输入 | Tracer.start_trace | message |
| response | 🤖 | Agent 输出 | Tracer.finish_trace | content_length |

## 3. 数据流设计

### 3.1 写入时序

```
用户发送消息
  │
  ├─ server.py: tracer.start_trace()
  │    → 内存 Trace 对象创建
  │    → PG: INSERT ai_trace (status=running)
  │    → PG: INSERT ai_trace_span (request span)
  │
  ├─ Agent 执行中（SSE 实时推送）
  │    TracingMiddleware 各钩子产生 span
  │    → 内存 Trace.spans 追加
  │    → SSE 推送 mw_span 事件给前端
  │    （此阶段不写 PG，避免高频写入）
  │
  ├─ Agent 执行完成
  │    server.py: tracer.finish_trace()
  │    → 内存 Trace 标记完成
  │    → PG: 批量 INSERT ai_trace_span（所有 span 一次性写入）
  │    → PG: UPDATE ai_trace (status/duration/tokens/span_count)
  │    → PG: INSERT ai_message
  │    → PG: UPDATE ai_conversation (message_count/tokens)
  │    → PG: INSERT ai_token_usage
  │
  └─ 异步记忆提取（DebounceQueue 回调后）
       → PG: INSERT ai_trace_span (memory_extract span)
```

### 3.2 读取场景

| 页面 | 查询 | SQL 模式 |
|------|------|----------|
| 总览仪表盘 | 最近 24h 聚合统计 | `SELECT COUNT(*), SUM(total_tokens) FROM ai_trace WHERE start_time > ?` |
| Trace Explorer | 分页列表 + 筛选 | `SELECT * FROM ai_trace WHERE tenant_id=? AND status=? ORDER BY start_time DESC` |
| Trace 详情 | 单条 trace + 所有 span | `SELECT * FROM ai_trace WHERE trace_id=?` + `SELECT * FROM ai_trace_span WHERE trace_id=? ORDER BY start_time` |
| Session 浏览器 | 按 thread_id 查消息列表 | `SELECT * FROM ai_message WHERE thread_id=? ORDER BY sequence` |
| 工具调用分析 | 按 tool_call 聚合 | `SELECT span_name, COUNT(*), AVG(duration_ms) FROM ai_trace_span WHERE span_type='tool_call' GROUP BY span_name` |
| 意图分析 | 按 intent_analysis 聚合 | `SELECT metadata->>'task_type', COUNT(*) FROM ai_trace_span WHERE span_type='intent_analysis' GROUP BY 1` |
| 告警中心 | 实时指标查询 | `SELECT COUNT(*) FROM ai_trace WHERE status='error' AND start_time > ? ` |
| 用量报表 | 按时间/模型/Agent 聚合 | `SELECT model, SUM(total_tokens), SUM(cost) FROM ai_token_usage GROUP BY model` |

## 4. 实现方案

### 4.1 TraceWriter — 异步持久化写入器

```python
class TraceWriter:
    """将内存 Trace 异步持久化到 PG

    设计原则：
    - Agent 执行期间不写 PG（避免影响延迟）
    - 执行完成后批量写入（一次 trace 的所有 span 一次性 INSERT）
    - 写入失败不影响主流程（降级为仅内存）
    """

    def on_trace_start(trace: Trace, tenant_id: int) -> None
        """trace 开始时写入 ai_trace（status=running）"""

    def on_trace_finish(trace: Trace, tenant_id: int, conversation_id: int) -> None
        """trace 完成时：
        1. 批量写入所有 ai_trace_span
        2. 更新 ai_trace（status/duration/tokens）
        3. 写入 ai_message
        4. 更新 ai_conversation
        5. 写入 ai_token_usage
        """
```

### 4.2 与现有 Tracer 的集成

```python
# server.py 中的改动

# trace 开始
trace = tracer.start_trace(thread_id, req.message, model=TEXT_MODEL, agent_name="CRM-Agent")
trace_writer.on_trace_start(trace, tenant_id=1)  # 新增

# trace 完成
tracer.finish_trace(trace_id, "success", full_content)
trace_writer.on_trace_finish(trace, tenant_id=1, conversation_id=conv.id)  # 新增
```

### 4.3 Trace 详情 API 的数据源切换

```python
@app.get("/api/traces/{trace_id}")
async def get_trace(trace_id: str):
    # 优先从内存读（实时性）
    trace = tracer.get_trace(trace_id)
    if trace:
        return {"trace": trace.to_dict(), "timeline": trace.to_timeline()}

    # 内存没有 → 从 PG 读（历史数据）
    db_trace = TraceDAO.get_by_trace_id(trace_id)
    if db_trace is None:
        return JSONResponse({"error": "Trace not found"}, status_code=404)
    db_spans = TraceSpanDAO.list_by_trace(trace_id)
    return {"trace": _format_db_trace(db_trace, db_spans)}
```

## 5. Trace 详情页的前端数据结构

对齐 index.html 的 Trace 详情页，API 返回的 JSON 结构：

```json
{
  "trace": {
    "trace_id": "abc-123-def-456",
    "thread_id": "cli__local__user123",
    "user_id": "sender_456",
    "model": "doubao-1-5-pro-32k",
    "status": "success",
    "start_time": 1713160812,
    "total_duration_ms": 6720,
    "total_tokens": 13580,
    "total_cost": 0.12,
    "iteration_count": 2,
    "tool_count": 1,
    "user_input": "帮我写一个 Python 异步爬虫",
    "agent_output": "好的，我来帮你实现...",
    "agent_name": "CRM-Agent",
    "spans": [
      {
        "span_id": "sp_01",
        "parent_span_id": "",
        "span_type": "context_build",
        "span_name": "context_build",
        "status": "success",
        "duration_ms": 120,
        "start_time": 1713160812000,
        "metadata": {"message_count": 12, "estimated_tokens": 4800}
      },
      {
        "span_id": "sp_02",
        "parent_span_id": "",
        "span_type": "memory_retrieval",
        "span_name": "memory_retrieval",
        "status": "success",
        "duration_ms": 1800,
        "metadata": {
          "query_used": "Python 异步爬虫",
          "dimensions": ["task_history", "domain_knowledge", "user_profile"],
          "hit_count": 5,
          "items_preview": [
            {"dimension": "task_history", "content": "上次写过 aiohttp 爬虫..."}
          ]
        }
      },
      {
        "span_id": "sp_05",
        "parent_span_id": "",
        "span_type": "hierarchical_search",
        "span_name": "hierarchical_search skill",
        "status": "success",
        "duration_ms": 400,
        "metadata": {"search_type": "skill", "hit_count": 3},
        "children": [
          {"span_id": "sp_05a", "span_type": "vector_search", "duration_ms": 80, "metadata": {"dimension": "task_history"}},
          {"span_id": "sp_05b", "span_type": "rerank", "duration_ms": 60, "metadata": {"dimension": "task_history"}}
        ]
      },
      {
        "span_id": "sp_08",
        "parent_span_id": "",
        "span_type": "llm_call",
        "span_name": "llm_call Iter 1",
        "status": "success",
        "duration_ms": 2200,
        "metadata": {
          "iteration": 1,
          "output_tokens": 5000,
          "tool_calls": ["exec_command"],
          "is_final": false
        }
      },
      {
        "span_id": "sp_09",
        "parent_span_id": "",
        "span_type": "tool_call",
        "span_name": "tool:exec_command",
        "status": "success",
        "duration_ms": 500,
        "input_data": {"tool_name": "exec_command", "input": "pip install aiohttp"},
        "output_data": {"output": "Successfully installed aiohttp-3.9.1"}
      },
      {
        "span_id": "sp_10",
        "parent_span_id": "",
        "span_type": "llm_call",
        "span_name": "llm_call Iter 2",
        "status": "success",
        "duration_ms": 1800,
        "metadata": {
          "iteration": 2,
          "output_tokens": 7200,
          "is_final": true
        }
      }
    ]
  },
  "timeline": [
    {"span_id": "sp_01", "type": "context_build", "name": "context_build", "offset_ms": 0, "duration_ms": 120, "status": "success"},
    {"span_id": "sp_02", "type": "memory_retrieval", "name": "memory_retrieval", "offset_ms": 120, "duration_ms": 1800, "status": "success"},
    {"span_id": "sp_08", "type": "llm_call", "name": "llm_call Iter 1", "offset_ms": 2920, "duration_ms": 2200, "status": "success"},
    {"span_id": "sp_09", "type": "tool_call", "name": "tool:exec_command", "offset_ms": 5120, "duration_ms": 500, "status": "success"},
    {"span_id": "sp_10", "type": "llm_call", "name": "llm_call Iter 2", "offset_ms": 5620, "duration_ms": 1800, "status": "success"}
  ]
}
```

## 6. Session 浏览器的数据结构

对齐 index.html 的 Session 浏览器页面：

```json
{
  "session": {
    "thread_id": "cli__local__user123",
    "user_id": "sender_456",
    "channel": "CLI",
    "created_at": 1713160800,
    "last_active_at": 1713163500,
    "message_count": 12,
    "total_tokens": 89200,
    "total_cost": 0.78,
    "duration_minutes": 45
  },
  "messages": [
    {
      "sequence": 1,
      "query": "帮我写一个 Python 异步爬虫",
      "answer": "好的，我来帮你实现...",
      "trace_summary": {
        "trace_id": "abc-123",
        "search_types": ["skill", "resource", "memory"],
        "tools_used": ["exec_command"],
        "total_tokens": 13580,
        "duration_ms": 6700,
        "iteration_count": 2,
        "cost": 0.12
      },
      "created_at": 1713160812
    },
    {
      "sequence": 2,
      "query": "加上错误重试机制",
      "answer": "已经添加了指数退避重试机制...",
      "trace_summary": {
        "trace_id": "def-456",
        "search_types": ["skill", "resource"],
        "tools_used": ["read_file", "write_file"],
        "total_tokens": 8200,
        "duration_ms": 4200,
        "iteration_count": 3,
        "cost": 0.07
      },
      "created_at": 1713161130
    }
  ]
}
```

## 7. 聚合查询（仪表盘 + 报表）

### 7.1 总览仪表盘所需的 6 个指标

```sql
-- 请求量 + 环比
SELECT COUNT(*) as total,
       COUNT(*) FILTER (WHERE start_time > :yesterday) as today
FROM ai_trace WHERE tenant_id = :tid AND start_time > :24h_ago;

-- Token 消耗
SELECT SUM(total_tokens), SUM(input_tokens), SUM(output_tokens)
FROM ai_token_usage WHERE tenant_id = :tid AND created_at > :24h_ago;

-- 预估成本
SELECT SUM(cost) FROM ai_token_usage WHERE tenant_id = :tid AND created_at > :24h_ago;

-- 平均延迟 + P95
SELECT AVG(duration_ms), PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY duration_ms)
FROM ai_trace WHERE tenant_id = :tid AND start_time > :24h_ago;

-- 成功率
SELECT status, COUNT(*) FROM ai_trace
WHERE tenant_id = :tid AND start_time > :24h_ago GROUP BY status;

-- 平均迭代
SELECT AVG(iteration_count) FROM ai_trace
WHERE tenant_id = :tid AND start_time > :24h_ago;
```

### 7.2 工具调用分析

```sql
-- 工具概览表
SELECT
    span_name as tool_name,
    COUNT(*) as call_count,
    COUNT(*) FILTER (WHERE status = 'success') * 100.0 / COUNT(*) as success_rate,
    AVG(duration_ms) as avg_duration,
    PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY duration_ms) as p95_duration
FROM ai_trace_span
WHERE tenant_id = :tid AND span_type = 'tool_call' AND created_at > :7d_ago
GROUP BY span_name
ORDER BY call_count DESC;

-- 调用链模式（连续工具调用序列）
SELECT tools_chain, COUNT(*) as chain_count
FROM (
    SELECT trace_id, STRING_AGG(span_name, '→' ORDER BY start_time) as tools_chain
    FROM ai_trace_span
    WHERE span_type = 'tool_call' AND created_at > :7d_ago
    GROUP BY trace_id
) sub
GROUP BY tools_chain ORDER BY chain_count DESC LIMIT 5;
```

### 7.3 意图分析

```sql
-- 任务类型分布
SELECT metadata::json->>'task_type' as task_type, COUNT(*)
FROM ai_trace_span
WHERE span_type = 'intent_analysis' AND created_at > :7d_ago
GROUP BY 1;

-- 零结果检索
SELECT metadata::json->>'query' as query, metadata::json->>'search_type' as search_type, COUNT(*)
FROM ai_trace_span
WHERE span_type IN ('hierarchical_search', 'vector_search')
  AND (metadata::json->>'hit_count')::int = 0
  AND created_at > :7d_ago
GROUP BY 1, 2 ORDER BY 3 DESC LIMIT 10;
```

## 8. 实现清单

| 序号 | 文件 | 改动 |
|------|------|------|
| 1 | `src/store/trace_writer.py` | 新建 TraceWriter 类 |
| 2 | `server.py` | 集成 TraceWriter（on_trace_start / on_trace_finish） |
| 3 | `server.py` | /api/traces/{id} 增加 PG fallback |
| 4 | `server.py` | 新增 /api/sessions/{thread_id} API |
| 5 | `server.py` | 新增 /api/dashboard/stats API |
| 6 | `server.py` | 新增 /api/tools/stats API |
