# Agent 异常场景分析与修复方案

> 基于 neo_agent_v2 自动化测试问题清单（wiki pageId=148133739）逐条对照当前 agent-system 代码分析。
> 每个问题附带可复现的场景示例、老项目处理方式、当前代码差距、修复方案。

---

## 问题 1：LLM 文本提到工具但未发 tool_call

### 场景示例

```
用户: "帮我查一下华为科技的商机"

期望行为:
  AIMessage(tool_calls=[{name: "query_data", args: {action: "query", entity_api_key: "opportunity", filters: {"account_name": "华为科技"}}}])

实际异常行为:
  AIMessage(content="好的，我来帮你查询华为科技的商机。我会使用 query_data 工具来查询 opportunity 实体...")
  → LLM 在文本中"描述"了要调用的工具，但没有实际发起 tool_call
  → Agent 直接把这段文本当作最终回复返回给用户
  → 用户看到的是一段"计划"而不是实际数据
```

### 触发条件

- 工具数量多（当前 7+ 个），LLM 在选择工具时犹豫，倾向于先"说明"再执行
- 豆包/DeepSeek 偶发，官方接口也有此问题（wiki 原文："主子 agent 均出现，柱子接口频发"）
- 用户指令模糊时更容易触发（如"帮我看看客户情况"）

### 老项目处理方式

- 切换官方模型 + 修改提示词，强调"必须使用 Tool"
- 主 Agent 只给 2 个工具（`execute_task` + `answer_question`），选择空间极小
- 提示词中用"禁止做法"硬约束：`"禁止做法：你亲自执行具体任务"`

### 当前代码差距

- `CRM_SYSTEM_PROMPT` 有 `"必须使用工具获取真实数据"` 但缺少"禁止做法"段落
- 没有运行时检测机制——`OutputValidationMiddleware.after_model()` 只做长度校验和敏感词审查，不检测文本中是否包含工具名
- 工具数量多（7+），LLM 选择空间大

### 修复方案

在 `OutputValidationMiddleware.after_model()` 中增加工具名检测：

```python
# 伪代码
TOOL_NAMES = {"query_schema", "query_data", "modify_data", "analyze_data", ...}

if not tool_calls and any(name in content for name in TOOL_NAMES):
    return {"messages": [HumanMessage(
        content="[纠错] 你在文本中提到了工具名但没有实际调用。请直接使用工具执行操作，不要在文本中描述。"
    )]}
```

在 `CRM_SYSTEM_PROMPT` 中增加"禁止做法"段落：

```
## 禁止做法
- 禁止在文本中描述"我要调用 xxx 工具"然后不实际调用
- 禁止编造数据或凭记忆回答数据类问题
- 禁止在参数中使用占位符（如 {account_id}），必须使用实际值
```

---

## 问题 2：Function name 不在预期范围（返回 ActionName 而非 ToolName）

### 场景示例

```
用户: "帮我生成一份作战计划"

期望行为:
  AIMessage(tool_calls=[{name: "skills_tool", args: {skill_name: "actionPlanGenerator", arguments: {...}}}])

实际异常行为:
  AIMessage(tool_calls=[{name: "actionPlanGenerator__c__c__c", args: {...}}])
  → LLM 返回的 tool name 是业务 Action 的 apiKey，不是注册的工具名
  → LangGraph 找不到这个工具 → 抛出 KeyError
  → ToolErrorHandlingMiddleware 捕获后返回通用错误: "Tool 'actionPlanGenerator__c__c__c' failed with KeyError"
  → LLM 看到通用错误，不知道该用什么工具，可能继续用错误的名字重试
```

### 触发条件

- 系统提示词中包含了 Action 的 apiKey（如技能描述中的 `actionPlanGenerator__c__c__c`）
- LLM 混淆了 Tool name 和 Action apiKey
- 豆包官方接口、DeepSeek 官方接口偶发

### 老项目处理方式

- 引入纠错机制：检测到 Tool 不在范围内时，回复模型 `"Tool不存在，请使用我给你的Tool解决问题"`
- 明确列出可用工具范围

### 当前代码差距

- `ToolErrorHandlingMiddleware` 返回的错误消息是通用的 `"Tool 'xxx' failed with KeyError"`
- 没有列出可用工具名，LLM 无法自行纠正
- 没有在 `wrap_tool_call` 阶段主动检测 tool name 是否合法

### 修复方案

在 `ToolErrorHandlingMiddleware._error_message()` 中，对 KeyError/工具不存在的情况返回可用工具列表：

```python
@staticmethod
def _error_message(request, exc):
    tool_name = request.tool_call.get("name", "unknown")
    if isinstance(exc, KeyError) or "not found" in str(exc).lower():
        available = ", ".join(REGISTERED_TOOL_NAMES)  # 从 ToolRegistry 获取
        return ToolMessage(
            content=f"Error: Tool '{tool_name}' 不存在。可用的工具有: {available}。请使用正确的工具名重试。",
            tool_call_id=request.tool_call.get("id", ""),
            name=tool_name, status="error",
        )
    # ... 其他错误走通用逻辑
```

---

## 问题 3：Function 参数不符合要求（参数名错误、多参数、少参数）

### 场景示例

```
用户: "按阶段统计商机金额"

期望行为:
  analyze_data(entity_api_key="opportunity", metrics=[{"field":"amount","function":"sum"}], group_by="stage")

实际异常行为 A（参数名错误）:
  analyze_data(entity="opportunity", metric=[{"field":"amount","func":"sum"}], groupBy="stage")
  → "entity" 应为 "entity_api_key"，"metric" 应为 "metrics"，"func" 应为 "function"
  → Pydantic 校验失败

实际异常行为 B（参数格式错误）:
  query_data(action="query", entity_api_key="opportunity", filters="owner_name=张三")
  → filters 应为 JSON 对象 {"owner_name": "张三"}，实际传了字符串
  → 下游解析失败

实际异常行为 C（少参数）:
  modify_data(action="update", entity_api_key="opportunity", data={"amount": 1000000})
  → 缺少 record_id（update 时必填）
  → 工具返回 "update 操作需要 record_id"，但 LLM 可能不知道如何获取 record_id
```

### 老项目处理方式

- Tool 参数给出示例和详细描述
- 子 Agent 提示词中直接内嵌每个 Action 的参数 schema 和提取来源

### 当前代码差距

- `input_schema()` 有 `description` 和 `enum`，但没有 `examples` 字段
- `prompt()` 中有典型用法示例，但 LLM 可能不参考 prompt 中的示例来构造参数

### 修复方案

在 `input_schema()` 中增加 `examples`：

```python
def input_schema(self):
    return {
        "type": "object",
        "properties": {
            "filters": {
                "type": "object",
                "description": "过滤条件 {字段: 值}",
                "examples": [{"owner_name": "张三"}, {"stage": "谈判", "amount_gt": 100000}],
            },
            # ...
        },
    }
```

---

## 问题 4：参数缺失时反复调用不相关工具凑参数

### 场景示例

```
用户: "生成华为科技的作战计划"

技能参数要求:
  - productName（必填）
  - bestPractices（必填，需从知识库获取）
  - riskDiagnosis（必填，需从上下文获取）
  - account（必填，需从 identify_record_byname 获取客户 ID）

期望行为:
  1. skills_tool(skill_name="actionPlanGenerator", arguments={productName: "ERP", account: "华为科技", ...})
  2. 技能内部按顺序调用 Action 获取参数

实际异常行为:
  Iter 1: query_data(entity="account", filters={"name":"华为科技"}) → 查到客户 ID
  Iter 2: query_data(entity="opportunity", filters={"account_id":"xxx"}) → 查到商机
  Iter 3: analyze_data(entity="opportunity", ...) → 分析商机
  Iter 4: query_data(entity="activity", filters={"account_id":"xxx"}) → 查活动记录
  Iter 5: query_data(entity="contact", filters={"account_id":"xxx"}) → 查联系人
  → Agent 不断调用不同工具试图"凑齐"参数，但每次调用的工具和参数都不同
  → LoopDetectionMiddleware 不触发（因为每次 tool_calls 哈希不同）
  → 最终消耗大量 token，可能超时
```

### 老项目处理方式

三层防护：
1. 子 Agent 提示词：`"执行前检查历史 execute_task，不要重复调用"`
2. 子 Agent 提参失败时返回：`"缺少下面参数：医院(account)"`
3. 主 Agent 退出条件：`"若返回结果不正确或者无任务需要执行，则进行步骤4（总结回复）"`

### 当前代码差距

- `LoopDetectionMiddleware` 只检测完全相同的 tool_calls 哈希重复
- 子 Agent（`FORK_AGENT_PROMPT`）没有参数缺失时的退出策略
- 没有"无效调用次数"计数器

### 修复方案

1. 在 `LoopDetectionMiddleware` 中增加"无效调用"检测——连续 N 次工具调用返回错误或空结果时触发警告
2. 在 `FORK_AGENT_PROMPT` 中增加退出策略：

```
## 参数缺失处理
- 如果所需参数无法从上下文或工具调用中获取，直接返回"缺少以下参数：xxx"
- 禁止为了凑参数而调用不相关的工具
- 最多尝试 3 次工具调用，仍无法获取参数则返回缺失说明
```

---

## 问题 5：第一轮不执行工具，直接文本回复

### 场景示例

```
用户: "查一下张三的客户"

期望行为:
  AIMessage(tool_calls=[{name: "query_data", args: {action: "query", entity_api_key: "account", filters: {"owner_name": "张三"}}}])

实际异常行为:
  AIMessage(content="好的，我可以帮你查询张三负责的客户信息。请问你需要查看哪些具体信息呢？比如客户名称、行业、营收等？")
  → LLM 第一轮选择"追问"而不是直接查询
  → 用户需要再回复一次才能触发实际查询
  → 多消耗一轮对话
```

### 触发条件

- 用户指令看似完整但 LLM 认为不够具体
- 寒暄类消息（"你好"、"在吗"）
- 模糊查询（"帮我看看"、"查一下情况"）

### 老项目处理方式

- 代码预先执行"意图识别"工具，取消 Agent 第一次自主思考
- 意图识别结果直接填充到上下文中，Agent 从第二步开始执行

### 当前代码差距

- 完全依赖 LLM 自主决定是否调用工具
- `CRM_SYSTEM_PROMPT` 中有 `"先查后答"` 软约束，但无代码级预执行

### 修复方案

在 `MemoryMiddleware.abefore_agent()` 或新增 `IntentPreloadMiddleware` 中，对首轮消息做意图预判：

```python
# 伪代码
if is_first_message(messages) and looks_like_data_query(current_query):
    # 预注入提示，强制 Agent 先调用工具
    return {"messages": [SystemMessage(
        content="[系统提示] 用户的问题涉及数据查询，请直接调用工具获取数据，不要追问。"
    )]}
```

---

## 问题 6：参数使用占位符而非实际值

### 场景示例

```
用户: "把华为科技的商机金额改成 500 万"

期望行为:
  1. query_data(action="query", entity_api_key="opportunity", filters={"account_name":"华为科技"}) → 获取 record_id
  2. modify_data(action="update", entity_api_key="opportunity", record_id="opp_001", data={"amount": 5000000})

实际异常行为:
  modify_data(action="update", entity_api_key="opportunity", record_id="{opportunity_id}", data={"amount": 5000000})
  → record_id 使用了占位符 "{opportunity_id}" 而不是实际值
  → 工具执行失败: "记录 {opportunity_id} 不存在"
```

### 老项目处理方式

- 子 Agent 提示词中明确定义占位符规则：`"若参数需要的内容过大，超过500个字符，使用 file_name 作为该参数占位符"`
- 只有特定条件下才允许占位符，且格式固定为 file_name

### 当前代码差距

- 没有任何关于占位符的规则
- 没有运行时检测参数中是否包含占位符模式

### 修复方案

1. 在 `CRM_SYSTEM_PROMPT` 的"禁止做法"中增加：`"禁止在参数中使用占位符（如 {account_id}、{record_id}），必须使用实际值"`
2. 在 `_make_lc_tool()` 的 `_arun()` 中增加占位符检测：

```python
import re
PLACEHOLDER_PATTERN = re.compile(r'\{[a-zA-Z_]+\}')

async def _arun(**kwargs):
    for key, value in kwargs.items():
        if isinstance(value, str) and PLACEHOLDER_PATTERN.search(value):
            return f"Error: 参数 '{key}' 包含占位符 '{value}'，请使用实际值。先用 query_data 查询获取实际的 ID 或值。"
    # ... 正常执行
```

---

## 问题 7：子 Agent 澄清中断判断不稳定

### 场景示例

```
技能: "客户 360 分析"
参数: account_name（必填）

场景 A — 应该澄清但没有澄清:
  用户: "帮我分析一下客户"
  子 Agent: 直接调用 query_data(entity="account") 查询所有客户
  → 应该先问"你要分析哪个客户？"

场景 B — 不应该澄清但触发了澄清:
  用户: "分析华为科技的客户 360"
  子 Agent: ask_clarification(question="请问你要分析哪个客户？")
  → 用户已经说了"华为科技"，不应该再追问

场景 C — 多值时应该澄清:
  用户: "分析张三的客户"
  子 Agent: query_data → 查到 3 个"张三"
  → 应该问"找到 3 个张三，你要分析哪个？"但子 Agent 直接选了第一个
```

### 老项目处理方式

精确的 2 条触发规则：
1. 当任务参数提取到多个值，但参数描述明确只需要一个值时
2. 参数描述明确说明提取到多个参数值需要用户澄清或确认时

### 当前代码差距

- 子 Agent 的 `FORK_AGENT_PROMPT` 写的是 `"完成任务后直接输出结果，不要反问用户"`
- 子 Agent 的 `allowed_tools` 通常不包含 `ask_clarification`
- 主 Agent 的 `AskClarificationTool` 有 4 种澄清类型，但子 Agent 无法使用

### 修复方案

1. 子 Agent 的 `allowed_tools` 中加入 `ask_clarification`
2. `FORK_AGENT_PROMPT` 修改为：

```
## 澄清规则
- 参数完整时直接执行，不要追问
- 以下情况必须使用 ask_clarification 追问：
  1. 参数提取到多个值但只需要一个（如查到 3 个同名客户）
  2. 关键必填参数无法从上下文中提取
- 其他情况禁止追问，直接基于已有信息执行
```

---

## 问题 8：同一工具连续执行 2 次，第二次提参来源错误

### 场景示例

```
技能编排: 先执行 get_account_info 获取客户信息，再执行 get_opportunity_info 获取商机信息

Iter 1: execute_action(action="get_account_info", params={account_name: "华为科技"})
  → 返回: {name: "华为科技", id: "acc_001", industry: "通信", revenue: "8809亿"}

Iter 2: execute_action(action="get_opportunity_info", params={account_id: "acc_001", stage: "通信"})
  → 错误！stage 参数应该从用户指令或默认值获取，但 LLM 从 get_account_info 的结果中错误提取了 industry="通信" 作为 stage
  → 实际上 get_opportunity_info 不需要 stage 参数，或者 stage 应该是 "negotiation" 等商机阶段值
```

### 触发条件

- 上下文中有多个工具的返回结果，LLM 混淆了参数来源
- `SummarizationMiddleware._micro_compact()` 截断旧 ToolMessage 后，关键信息丢失，LLM 从错误的上下文中提取
- 连续调用同类工具时更容易触发

### 老项目处理方式

- 文件系统隔离：每个 Action 的执行结果存储为独立文件（`FileInfo`）
- 子 Agent 通过 `read_task_result(file_name)` 按需读取特定 Action 的结果
- 参数提取来源明确：`"提取来源包括 <用户指令>、<任务参数描述>、<历史执行结果>"`

### 当前代码差距

- 所有工具结果在同一个消息列表中，没有按工具隔离
- `_micro_compact()` 截断旧 ToolMessage 到 2000 字符，可能丢失关键字段
- 没有"参数来源"的约束机制

### 修复方案

1. 在技能执行的 `FORK_AGENT_PROMPT` 中增加参数来源约束：

```
## 参数提取规则
- 每次调用工具时，独立从以下来源提取参数（按优先级）：
  1. 用户原始指令中的明确值
  2. 当前任务的参数描述中的默认值
  3. 前置任务的执行结果（仅提取该任务返回的字段）
- 禁止从不相关工具的返回结果中提取参数
- 如果不确定参数值，宁可留空让工具报错，也不要猜测
```

2. `_micro_compact()` 保留最近 2 个 ToolMessage 的完整内容，只截断更早的：

```python
keep_recent_tools = 2  # 保留最近 2 个 ToolMessage 完整
```

---

## 问题 9：长任务编排时思考内容变长，单次思考耗时 20s+

### 场景示例

```
用户: "帮我生成华为科技的完整作战计划"

编排步骤:
  1. get_account_info → 客户信息（~500 tokens 返回）
  2. search_webinfo → 网络搜索（~2000 tokens 返回）
  3. get_bestPractices → 知识库检索（~1500 tokens 返回）
  4. get_riskDiagnosis → 风险诊断（~3000 tokens 返回）
  5. actionPlanGenerator → 生成作战计划

到第 5 步时的上下文:
  system_prompt: ~2000 tokens
  会话历史: ~500 tokens
  4 次工具调用的 AIMessage: ~800 tokens
  4 次工具返回的 ToolMessage: ~7000 tokens
  总计: ~10300 tokens

问题:
  → 第 5 步 LLM 输入 10K+ tokens，思考时间从第 1 步的 2s 增长到 15-20s
  → 用户等待总时间: 2+3+5+10+20 = 40s
  → 如果中间有重试，可能超过 60s
```

### 老项目处理方式

- 主 Agent 只看**总结**（每个 Tool result 同步生成摘要，用 flash 模型 ~1s）
- 子 Agent 按需通过 `read_task_result(file_name)` 读取原文
- 会话历史只加载最近 5 轮的总结版本
- 组件摘要方案：根据 schema 结构化遍历生成字符串

### 当前代码差距

- `SummarizationMiddleware` 的 `max_tokens=100_000` 远超实际模型窗口（32K）
- 压缩永远不触发——在达到 50K 阈值之前，模型已经因为超出 32K 窗口而报错
- 即使手动修正阈值，`_auto_compact()` 只是截断到 300 字符，不是 LLM 生成的摘要
- 没有"原文+总结"双存储机制

### 修复方案

1. 立即修正 `SummarizationMiddleware` 默认参数：

```python
SummarizationMiddleware(
    max_tokens=30_000,          # 对齐 doubao-seed-2-0-lite 的实际窗口
    micro_threshold=0.30,       # 9K tokens 开始裁剪 ToolMessage
    auto_threshold=0.60,        # 18K tokens 开始生成摘要
    full_threshold=0.85,        # 25.5K tokens 全量压缩
    tool_output_max_chars=1000, # ToolMessage 裁剪到 1000 字符（原 2000）
)
```

2. `_auto_compact()` 改为 LLM 生成摘要（用 flash 模型）：

```python
async def _auto_compact_with_llm(self, messages, estimated):
    summary = await self._flash_llm.ainvoke(
        f"请用 200 字以内总结以下对话的关键信息（保留数据名称、ID、关键数字）：\n{context}"
    )
    return {"messages": [SystemMessage(content=summary)] + recent}
```

---

## 问题 10：历史会话文本过长，多轮会话依赖上下文原文、影响意图

### 场景示例

```
第 1 轮: 用户问"查华为的客户信息" → Agent 返回 500 字的客户详情
第 2 轮: 用户问"他们的商机呢" → Agent 返回 800 字的商机列表
第 3 轮: 用户问"按阶段统计一下" → Agent 返回 600 字的统计表格
第 4 轮: 用户问"帮我查一下腾讯的情况"

到第 4 轮时的上下文:
  system_prompt: ~2000 tokens
  第 1 轮完整对话: ~800 tokens（含工具调用和返回）
  第 2 轮完整对话: ~1200 tokens
  第 3 轮完整对话: ~1000 tokens
  第 4 轮用户消息: ~20 tokens
  总计: ~5020 tokens

问题:
  → 第 1-3 轮的华为相关上下文占据大量 token
  → LLM 在处理第 4 轮"腾讯"查询时，注意力被华为的历史数据干扰
  → 可能返回华为的数据而不是腾讯的
  → 或者在 filters 中混入华为的条件
```

### 老项目处理方式

双存储架构：
- 每轮会话存储：回复原文 + 回复总结
- 回复原文（文本 + 组件模板化）存储到文件系统
- 回复总结（摘要文本 + 组件摘要）用 LLM 生成（flash 模型 ~1s）
- 运行时：主 Agent 使用回复总结进行编排
- 子 Agent 按需通过 `read_task_result` 读取回复原文

### 当前代码差距

- 完全没有"原文+总结"双存储
- `SummarizationMiddleware` 的三层压缩都是运行时临时处理，没有持久化
- `MemoryMiddleware` 的记忆提取是跨会话的长期记忆，不是会话内的轮次摘要
- `_auto_compact()` 的截断（300 字符）会丢失关键信息

### 修复方案

实现会话内轮次摘要机制：

```python
class TurnSummaryMiddleware(AgentMiddleware):
    """每轮对话结束后，异步生成本轮摘要，替换历史中的完整内容"""

    def __init__(self, flash_llm=None, max_history_turns=5):
        self._flash_llm = flash_llm  # 用 flash 模型快速生成摘要
        self._max_turns = max_history_turns
        self._summaries: dict[str, list] = {}  # thread_id → [摘要列表]

    async def aafter_agent(self, state, runtime):
        # 异步生成本轮摘要
        messages = state.get("messages", [])
        last_ai = self._get_last_ai_content(messages)
        if last_ai and len(last_ai) > 500:
            summary = await self._generate_summary(last_ai)
            # 存储摘要，下次 before_agent 时用摘要替换原文
            self._store_summary(thread_id, summary)

    async def abefore_agent(self, state, runtime):
        # 用摘要替换超过 max_turns 的历史轮次
        messages = state.get("messages", [])
        if len(messages) > self._max_turns * 2:
            compacted = self._replace_old_turns_with_summaries(messages)
            return {"messages": compacted}
```

---

## 汇总：修复优先级

| 优先级 | 问题 | 修复工作量 | 影响面 |
|:---|:---|:---|:---|
| P0 | 问题 9：`max_tokens=100K` 导致压缩不触发 | 改 1 行配置 | 所有长对话场景 |
| P0 | 问题 4：参数缺失时无退出策略 | 改提示词 + 增加无效调用检测 | 复杂编排场景 |
| P1 | 问题 10：缺少轮次摘要机制 | 新增 `TurnSummaryMiddleware` | 多轮对话场景 |
| P1 | 问题 2：工具名纠错 | 改 `ToolErrorHandlingMiddleware` | 所有工具调用 |
| P1 | 问题 8：参数来源混淆 | 改提示词 + 调整截断策略 | 多步骤编排 |
| P2 | 问题 1：文本提到工具但未调用 | 增加检测逻辑 | 偶发 |
| P2 | 问题 7：子 Agent 澄清规则 | 改提示词 + 开放工具 | 子 Agent 场景 |
| P2 | 问题 5：首轮不执行工具 | 增加预注入逻辑 | 首轮对话 |
| P3 | 问题 6：参数占位符 | 增加检测 + 改提示词 | 偶发 |
| P3 | 问题 3：参数格式错误 | 增加 examples | 偶发 |

---

> 参考来源：
> - Wiki: [Agent自动化测试&问题梳理](https://wiki.ingageapp.com/pages/viewpage.action?pageId=148133739)
> - Wiki: [Agent架构](https://wiki.ingageapp.com/pages/viewpage.action?pageId=148116241)
> - Wiki: [Agent Tool设计](https://wiki.ingageapp.com/pages/viewpage.action?pageId=145980775)
> - Wiki: [上下文管理](https://wiki.ingageapp.com/pages/viewpage.action?pageId=145977588)
> - 当前代码: `src/middleware/loop_detection.py`, `summarization.py`, `tool_error_handling.py`, `output_validation.py`, `guardrail.py`
> - 当前代码: `src/tools/crm_tools.py`, `src/core/prompt_builder.py`, `server.py`
