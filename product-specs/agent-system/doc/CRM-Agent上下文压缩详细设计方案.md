# CRM Agent 上下文压缩详细设计方案

> 基于 Claude Code / Hermes Agent / neo-apps 三系统深度对比，取各家精华，面向 toB CRM SaaS 场景设计。
> 每个设计点标注参考来源：**[CC]** = Claude Code, **[HA]** = Hermes Agent, **[NA]** = neo-apps 现有实现, **[NEW]** = 本方案新增。
> 每个机制配有 CRM 真实业务场景举例。

---

## 一、整体架构

```
┌─────────────────────────────────────────────────────────────┐
│ Layer 1: 源头隔离（每次工具执行时）          [NA]  ← 主路径  │
│   工具结果 → 前端 UI 组件渲染（不进入 LLM 上下文）           │
│   工具结果 > 动态阈值 → 两层摘要（代码优先+LLM兜底）         │
│   原文 → 虚拟文件 FileInfo（当前会话内引用）                 │
│                                                              │
│   覆盖场景: 所有对话（100%触发）                             │
└──────────────────────┬──────────────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────────────┐
│ Layer 2: 当前轮次裁剪（reasoning 步数 ≥5 时）  [HA+NEW]     │
│   Pass 1: MD5 去重（LLM 重复调用同一工具时）                 │
│   Pass 2: 信息摘要替换（仅保护区外的旧 ToolMessage）         │
│   Pass 3: tool_call 参数截断                                │
│                                                              │
│   覆盖场景: 多步复杂任务（报价谈判/客户交接/竞品调研，       │
│            约 20-30% 的对话会触发）                           │
└──────────────────────┬──────────────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────────────┐
│ Layer 3: 回复摘要回写（每轮结束时）          [NA+HA] ← 主路径│
│   answerSummary 异步写入 DB                                 │
│   sessionSummary 迭代更新写入 Redis                         │
│                                                              │
│   覆盖场景: 回复 >500 字符时触发（约 60-70% 的对话）         │
└──────────────────────┬──────────────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────────────┐
│ Layer 4: 历史上下文构建（每次新对话开始时）  [NA+HA] ← 主路径│
│   双套视图 + sessionSummary 注入 + Prompt Cache             │
│                                                              │
│   覆盖场景: 所有非首轮对话（100%触发）                       │
└─────────────────────────────────────────────────────────────┘
```

**主路径（所有对话）**：Layer 1 → Layer 3 → Layer 4
**辅助路径（多步复杂任务）**：Layer 1 → **Layer 2** → Layer 3 → Layer 4

大部分 CRM 交互是 3-5 步的短对话（查客户→查商机→回复），只走主路径。Layer 2 只在 reasoning 循环步数 ≥5 且 ToolMessage 总量超过阈值时才触发。

---

## 二、Layer 1：源头隔离

### 2.1 前端组件分流 [NA]

**机制**：工具返回的结构化数据通过 `neo_ai_emit_custom` 推送给前端，按 schema + propsData 渲染为标准 UI 组件。组件数据不进入 LLM 上下文。

**场景举例：销售总监查看 Pipeline**

```
用户: "帮我看一下本月所有商机的 pipeline"

子 Agent 执行 query_data(entity="opportunity", filter="close_date <= 2025-04-30")
  → 返回 100 条商机记录，总计 35K 字符

处理流程:
  1. 前端组件渲染（不进入 LLM 上下文）:
     neo_ai_emit_custom(config, data={
       "by_stage": {"prospecting": 25, "qualification": 30, ...},
       "by_owner": {"Andi": {"count": 8, "amount": "$280K"}, ...},
       "total": 100, "total_amount": "$3.6M"
     }, render_type="pipeline_dashboard")
     → 前端渲染为 Pipeline 仪表盘卡片，用户立即看到

  2. LLM 上下文中只有摘要（~80 字）:
     ToolMessage: "查询 opportunity 实体返回 100 条商机，
     总金额$3.6M，按阶段分布: prospecting 25/qualification 30/
     proposal 20/negotiation 18/closing 7，15个商机超30天未跟进"

  3. 虚拟文件保留原文:
     FileInfo(file_path="/action_result",
              content="[100条商机的完整JSON]",
              summary="100条商机，总金额$3.6M...")

上下文占用: 80 字 ≈ 40 tokens（而非 35K 字符 ≈ 8,750 tokens）
节省: 99.5%
```

**场景举例：BANT 分析卡片**

```
用户: "帮我分析一下 PT Sentosa Jaya 这个商机的 BANT 情况"

子 Agent 执行 analyze_data(type="bant", opportunity_id="opp_xxx")
  → 返回 BANT 分析结果 2,800 字符

处理流程:
  1. 前端组件渲染:
     neo_ai_emit_custom(config, data={
       "budget": {"status": "identified", "detail": "$40K-50K，年付优先"},
       "authority": {"status": "partial", "detail": "Pak Budi 是推荐者"},
       "need": {"status": "identified", "detail": "生产排程自动化"},
       "timeline": {"status": "identified", "detail": "3个月内上线"}
     }, render_type="bant_analysis")
     → 前端渲染为 BANT 四象限卡片

  2. LLM 上下文中的摘要（~60 字）:
     ToolMessage: "PT Sentosa Jaya BANT分析: Budget $40-50K已确认,
     Authority 部分确认(Pak Budi推荐者), Need 已确认(排程自动化),
     Timeline 3个月"

上下文占用: 60 字 vs 原文 2,800 字符，节省 97.8%
```


### 2.2 工具结果动态摘要 [NA+HA+NEW]

**现有实现 [NA]**：`process_sub_agent_result` 中固定 500 字符阈值，超过时调用 `agent_summary_model()` 纯 LLM 摘要。这是新版 Agent（neo_agent）的逻辑，老版 Agent 没有此机制。

**新方案改进**：两层摘要策略（代码格式化优先 + LLM 兜底）+ 动态阈值。

#### 2.2.1 动态阈值表 [NEW]

阈值按工具返回数据的**信息密度**和**精确性要求**分三档，而非固定 500 字符一刀切：

| 工具类型 | 阈值 | 摘要字数上限 | 原因 |
|---------|------|------------|------|
| 查询类（query_data, query_schema） | 300 字符 | 100 字 | 返回列表数据，信息密度低，摘要即可 |
| 分析类（analyze_data, BANT） | 800 字符 | 200 字 | 返回洞察结论，需要保留更多推理依据 |
| 报价类（financial_report, pricing） | 1500 字符 | 300 字 | 含精确数字，摘要必须保留金额/折扣/日期 |
| 搜索类（web_search） | 500 字符 | 150 字 | 返回多条结果，保留关键结论和来源 |
| 子 Agent 结果（delegate_task） | 500 字符 | 200 字 | 已经是子 Agent 的总结，保留核心结论 |

```python
# 阈值配置 [NEW]
SUMMARY_THRESHOLDS = {
    "query_data":        {"threshold": 300, "max_words": 100},
    "query_schema":      {"threshold": 300, "max_words": 100},
    "search_memories":   {"threshold": 300, "max_words": 100},
    "analyze_data":      {"threshold": 800, "max_words": 200},
    "web_search":        {"threshold": 500, "max_words": 150},
    "delegate_task":     {"threshold": 500, "max_words": 200},
    "company_info":      {"threshold": 800, "max_words": 200},
    "financial_report":  {"threshold": 1500, "max_words": 300},
    "pricing_calculate": {"threshold": 1500, "max_words": 300},
    "query_quote":       {"threshold": 1500, "max_words": 300},
    "DEFAULT":           {"threshold": 500, "max_words": 150},
}
```

#### 2.2.2 两层摘要策略：代码格式化优先 + LLM 兜底 [HA+NA+NEW]

Hermes 的 `_summarize_tool_result` 启示：对结构化数据用代码规则提取（零 LLM 成本），只有非结构化文本才调 LLM。在 CRM 场景中，大部分工具返回的是结构化数据（JSON 列表、组件数据），代码提取能覆盖 60-70% 的场景。

```python
async def process_sub_agent_result(sub_agent_result, state):
    original_text = ""
    # ... 现有 TextContent/CustomContent 拼接逻辑不变 [NA] ...

    # 动态阈值 [NEW]
    config = get_summary_config(sub_agent_result.task_name)
    threshold = config["threshold"]
    max_words = config["max_words"]

    if len(original_text) <= threshold or state.sub_agent_result.return_direct:
        return original_text, original_text  # 不摘要

    # ── 第一层：代码格式化提取（零 LLM 成本）[HA 思路 + NEW CRM 实现] ──
    code_summary = try_code_extract(sub_agent_result)
    if code_summary:
        return original_text, code_summary

    # ── 第二层：代码提取失败，调用大模型 [NA 现有逻辑] ──
    model = agent_summary_model()
    response = await model.ainvoke([
        HumanMessage(content=SUMMARY_PROMPT.format(
            text=original_text, schema=schema,
            language_name=state.language_name,
            task_name=sub_agent_result.task_name,
            topic_inst=topic_instructions_str,
            max_words=max_words))
    ])
    return original_text, response.content
```

#### 2.2.3 代码格式化提取的实现 [HA 思路 + NEW CRM 实现]

```python
def try_code_extract(sub_agent_result) -> str | None:
    """尝试用代码规则提取摘要。成功返回摘要文本，失败返回 None 交给 LLM。"""
    results = sub_agent_result.result

    # 场景 1：纯 CustomContent（结构化组件数据）→ 从组件 data 提取关键字段
    custom_items = [item for item in results if isinstance(item, CustomContent)]
    if custom_items and not any(isinstance(item, TextContent) for item in results):
        parts = []
        for item in custom_items:
            extracted = extract_from_component(item.render_type, item.data)
            if extracted:
                parts.append(extracted)
        if parts:
            return "\n".join(parts)

    # 场景 2：JSON 列表（query_data 的典型返回）→ 提取记录数 + 关键字段
    text_items = [item.content for item in results if isinstance(item, TextContent)]
    combined = "".join(text_items)
    if combined.strip().startswith("[") or combined.strip().startswith("{"):
        extracted = extract_from_json(combined, sub_agent_result.task_name)
        if extracted:
            return extracted

    # 无法用代码提取 → 返回 None，交给 LLM
    return None


def extract_from_component(render_type: str, data: dict) -> str | None:
    """从已知组件类型的 data 中提取关键信息（零 LLM 成本）"""
    if render_type == "bant_analysis":
        b = data.get("budget", {})
        a = data.get("authority", {})
        n = data.get("need", {})
        t = data.get("timeline", {})
        return (f"BANT: Budget={b.get('detail','未知')}, "
                f"Authority={a.get('detail','未知')}, "
                f"Need={n.get('detail','未知')}, "
                f"Timeline={t.get('detail','未知')}")

    if render_type == "pipeline_dashboard":
        total = data.get("total", 0)
        amount = data.get("total_amount", "")
        stages = data.get("by_stage", {})
        stage_str = "/".join(f"{k} {v.get('count',0)}" for k, v in stages.items())
        return f"{total}条商机, 总金额{amount}, {stage_str}"

    if render_type == "customer_profile":
        name = data.get("name", "")
        industry = data.get("industry", "")
        size = data.get("employee_count", "")
        score = data.get("lead_score", "")
        return f"{name}, {industry}, {size}人, 评分{score}"

    return None  # 未知组件类型 → 交给 LLM


def extract_from_json(json_text: str, task_name: str) -> str | None:
    """从 JSON 列表中提取摘要（零 LLM 成本）"""
    try:
        data = json.loads(json_text)
    except json.JSONDecodeError:
        return None

    if isinstance(data, list):
        count = len(data)
        names = [item.get("name") or item.get("label") or "" for item in data[:5]]
        names_str = ", ".join(n for n in names if n)
        if count > 5:
            names_str += f"...等{count}条"
        return f"查询返回{count}条记录: {names_str}"

    return None
```

**场景举例：代码提取 vs LLM 提取的效果对比**

```
场景 A：查询 5 个联系人（结构化 JSON 列表）

  原文: '[{"name":"Pak Budi","title":"IT Manager",...},...]' (600字符)
  600 > 300（查询类阈值）→ 先尝试 try_code_extract()
  → extract_from_json() 解析 JSON 列表
  → "查询返回5条记录: Pak Budi, Ibu Sari, Pak Eko, Ibu Dewi, Pak Agus"
  → 成功！不调用 LLM
  成本: 0，延迟: <1ms

场景 B：BANT 分析卡片（CustomContent 组件数据）

  原文: CustomContent(render_type="bant_analysis", data={budget:..., authority:...})
  → 先尝试 try_code_extract()
  → extract_from_component("bant_analysis", data)
  → "BANT: Budget=$40-50K年付优先, Authority=Pak Budi推荐者, Need=排程自动化, Timeline=3个月"
  → 成功！不调用 LLM
  成本: 0，延迟: <1ms

场景 C：竞争态势分析（非结构化文本）

  原文: "竞争态势分析: 1. 主要竞品: Odoo..." (1,200字符)
  1200 > 800（分析类阈值）→ 先尝试 try_code_extract()
  → 不是 JSON，不是纯 CustomContent → 返回 None
  → 降级到 LLM 摘要
  成本: 1 次 LLM 调用，延迟: 1-2s
```

**场景举例：报价谈判中的精确数字保留**

```
用户: "帮我查一下 PT Sentosa Jaya 的历史报价和竞品 Odoo 的定价"

子 Agent 执行两个工具:
  1. query_data(entity="quote", filter={account: "PT Sentosa Jaya"})
     → 返回 3 条历史报价，1,200 字符

  2. web_search(query="Odoo pricing Indonesia 2025")
     → 返回搜索结果，2,100 字符

处理流程（报价类工具，阈值 1500）:

  工具 1（1,200 字符 < 1,500 阈值）:
    → 不触发摘要，原文完整作为 ToolMessage 回传
    → LLM 看到完整报价: "$45,000 (15% discount, net-30), $38,000 (20% discount, net-60)..."
    → 精确数字完整保留

  工具 2（2,100 字符 > 500 阈值，搜索类）:
    → 触发摘要，摘要 Prompt 要求保留精确数字
    → ToolMessage: "Odoo Enterprise $24.90/user/month(年付),
      制造模块+$18/user/month, 50+用户15%折扣,
      印尼合作伙伴实施费约$8,000-12,000"
    → 关键定价数字保留

对比现有方案（固定 500 字符阈值）:
  工具 1 也会触发摘要 → "$45,000" 可能被摘要为"约4.5万美元" → 精确性丢失
```

**场景举例：客户画像查询**

```
用户: "帮我看看 PT Sentosa Jaya 的完整信息"

子 Agent 执行 query_data(entity="account", record_id="acc_xxx")
  → 返回客户完整信息，800 字符

处理流程（查询类工具，阈值 300）:
  800 字符 > 300 阈值 → 触发摘要
  摘要 Prompt（SUMMARY_PROMPT）:
    保留 objectApiKey=account, id=acc_xxx
    保留关键字段: 公司名、行业、规模、评分
  
  ToolMessage（~80 字）:
    "PT Sentosa Jaya(acc_xxx), 制造业, 200人, 评分87,
     IT Manager在招聘, 去年营收增长30%, 竞品Odoo实施失败"

  虚拟文件保留完整 800 字符原文
  → 如果 reasoning 后续需要某个具体字段值，可从虚拟文件引用
```

### 2.3 CustomContent 文本化 [NA]

**机制**：UI 组件结果在生成摘要前，先转为文本。优先级：template2str > schema2str > data 原文。

**场景举例：会议纪要组件**

```
子 Agent 返回会议纪要分析结果:
  CustomContent(
    render_type="meeting_summary",
    schema={"attendees": "array", "decisions": "array", "action_items": "array"},
    data={
      "attendees": ["Pak Budi (IT Manager)", "Ibu Sari (CFO)"],
      "decisions": ["进入POC阶段", "POC范围: 生产排程模块"],
      "action_items": [
        {"who": "us", "what": "3天内出POC方案"},
        {"who": "customer", "what": "提供现有排程数据"}
      ]
    },
    template="会议参与者: {attendees}\n决策: {decisions}\n行动项: {action_items}"
  )

文本化流程:
  1. 尝试 template2str() → "会议参与者: Pak Budi, Ibu Sari\n决策: 进入POC阶段..."
     → 成功，使用模板文本（最可读）

  2. 如果无 template，尝试 schema2str() → "meeting_summary: attendees/decisions/action_items"
     → 保留字段结构

  3. 如果都没有 → "组件<meeting_summary>:{完整JSON data}"

文本化后再判断是否需要摘要（>800 字符阈值，分析类）
```

---

## 三、Layer 2：当前轮次工具结果裁剪

**触发条件 [NEW]**：不是每轮 reasoning 都执行，只在满足以下条件时触发：

```python
def should_run_layer2(messages: list) -> bool:
    """判断是否需要执行 Layer 2 裁剪"""
    tool_messages = [m for m in messages if isinstance(m, ToolMessage)]
    
    # 条件 1: ToolMessage 数量 ≥ 5（短对话不触发）
    if len(tool_messages) < 5:
        return False
    
    # 条件 2: ToolMessage 总字符数 > 3000（内容少不触发）
    total_chars = sum(len(m.content) for m in tool_messages)
    if total_chars < 3000:
        return False
    
    return True
```

**与 Layer 1 的职责边界 [NEW]**：

| | Layer 1（源头隔离） | Layer 2（当前轮次裁剪） |
|---|---|---|
| 时机 | 工具执行完毕时，立即处理 | reasoning 循环中，调用 LLM 前检查 |
| 对象 | 刚返回的单个工具结果 | 已在 messages 中的所有旧 ToolMessage |
| 核心价值 | 控制"进入"上下文的内容大小 | 清理已"在"上下文中但不再需要完整内容的旧消息 |
| 典型场景 | 每次工具调用都执行 | 只在多步复杂任务（≥5 步）中触发 |
| 与高阈值工具的关系 | 报价类工具（阈值 1500）可能不触发摘要，完整原文进入上下文 | 当这些完整原文被推出保护区后，Pass 2 用一行摘要替换 |

### 3.1 Pass 1: MD5 去重 [HA+NEW]

**Hermes 原始设计 [HA]**：在 `_prune_old_tool_results` 中，对完整消息链中所有 tool_result 内容做 MD5 哈希，从末尾向前遍历，相同内容只保留最新一份，旧副本替换为 `[Duplicate tool output — same content as a more recent call]`。跳过 <200 字符的短内容（不值得去重）。

**CRM 适配设计 [NEW]**：neo-apps 的上下文结构与 Hermes 不同——工具结果以 ToolMessage 摘要形式存在于当前轮次的 `state.messages` 中，不是完整的 tool_result 原文。因此去重对象和时机需要适配：

| 维度 | Hermes 原始 | CRM 适配 |
|------|------------|---------|
| 去重对象 | 完整 tool_result 原文（几千到几万字符） | ToolMessage 摘要（通常 100-300 字符） |
| 最小长度阈值 | 200 字符 | 100 字符（摘要本身就短，阈值相应降低） |
| 去重时机 | 压缩触发时（上下文超阈值） | 每轮 reasoning 前（预防性，避免累积） |
| 核心价值 | 避免同一文件读 5 次占 5 倍空间 | 避免 LLM 重复调用同一工具时摘要累积 |

**实现代码 [HA 算法 + NEW 适配]**：

```python
def deduplicate_tool_messages(messages: list) -> list:
    """
    在每轮 reasoning 前执行。
    从末尾向前遍历 [HA]，对 ToolMessage 内容做 MD5 哈希 [HA]，
    相同内容只保留最新一份，旧副本替换为引用。
    """
    content_hashes = {}  # MD5 前12位 → 最新消息的 index
    result = [msg for msg in messages]  # 浅拷贝

    # 从末尾向前遍历 [HA]：第一次遇到某个哈希 = 最新的那条，保留
    for i in range(len(result) - 1, -1, -1):
        msg = result[i]
        if not isinstance(msg, ToolMessage):
            continue
        content = msg.content or ""
        # 短内容不去重 [HA]：摘要本身就很短的不值得
        if len(content) < 100:  # [NEW] 从 200 降到 100，适配摘要长度
            continue

        h = hashlib.md5(content.encode("utf-8")).hexdigest()[:12]  # [HA] 取前12位

        if h in content_hashes:
            # 当前这条是更旧的副本 → 替换 [HA]
            result[i] = ToolMessage(
                content="[重复结果 — 与最近一次相同查询结果一致]",
                tool_call_id=msg.tool_call_id
            )
        else:
            # 第一次见（从末尾算起 = 最新的）→ 保留 [HA]
            content_hashes[h] = i

    return result
```

**调用位置 [NEW]**：在 `reasoning_node` 中，调用 LLM 之前：

```python
async def reasoning_node(state, config):
    messages = state.messages or []
    messages = deduplicate_tool_messages(messages)  # [NEW] 每轮 reasoning 前去重
    messages_ = [SystemMessage(...), *history, *messages]
    response = await neo_model.ainvoke(messages_, ...)
```

**为什么用 MD5 而不是字符串比较 [HA]**：tool 结果可能是几十 KB 的 JSON，逐字符比较 O(n²) 太慢。MD5 哈希只取前 12 位（48 bit），碰撞概率极低（2^48 ≈ 281 万亿），比较只需 O(1)。

**场景举例：销售反复查询同一客户**

```
Reasoning 循环中，LLM 执行了以下工具调用:

  Turn 1: query_data(entity="account", record_id="acc_xxx")
    → ToolMessage: "PT Sentosa Jaya, 制造业, 200人..." (800 chars)
    → MD5: "a1b2c3d4e5f6"

  Turn 2: query_data(entity="opportunity", filter={account: "acc_xxx"})
    → ToolMessage: "3条商机, 总金额$125K..." (1,200 chars)
    → MD5: "f7g8h9i0j1k2"

  Turn 3: query_data(entity="account", record_id="acc_xxx")  ← LLM 重复调用！
    → ToolMessage: "PT Sentosa Jaya, 制造业, 200人..." (800 chars)
    → MD5: "a1b2c3d4e5f6" ← 与 Turn 1 相同

去重处理（从末尾向前遍历）:
  Turn 3: MD5="a1b2c3d4e5f6" → 第一次见 → 保留原文
  Turn 2: MD5="f7g8h9i0j1k2" → 第一次见 → 保留原文
  Turn 1: MD5="a1b2c3d4e5f6" → 已存在！→ 替换为:
    "[重复结果 — 与最近一次相同查询结果一致]"

结果: Turn 1 从 800 chars → 60 chars，Turn 3 保留完整 800 chars
节省: 740 chars
```

**场景举例：多步骤任务中重复读取 Schema**

```
LLM 在创建商机前查询 schema，修改商机前又查询一次:

  Turn 1: query_schema(entity="opportunity")
    → 返回 35 个字段定义，5,000 chars
    → MD5: "x1y2z3..."

  Turn 5: query_schema(entity="opportunity")  ← 重复！
    → 返回相同的 35 个字段定义，5,000 chars
    → MD5: "x1y2z3..." ← 相同

去重: Turn 1 替换为引用，节省 5,000 chars
```

### 3.2 Pass 2: CRM 工具信息摘要替换 [HA+NEW]

**机制**：保护区外的旧 ToolMessage（>200 字符），用零 LLM 成本的规则生成信息丰富的一行摘要替换。保护区由 token 预算决定（从末尾向前累积 ~20K tokens）。

**在 CRM 场景中的实际价值 [NEW]**：

Pass 2 的收益取决于 Layer 1 是否已经摘要过：
- Layer 1 已摘要的 ToolMessage（100 字）→ Pass 2 压到 40 字，**收益小**
- Layer 1 未摘要的 ToolMessage（高阈值工具，1000+ 字符完整原文）→ Pass 2 压到 40 字，**收益大**

因此 Pass 2 主要服务于三个场景：
1. **报价谈判**：报价/财务类工具阈值 1500，完整原文留在上下文，步骤增多后被推出保护区
2. **竞品调研**：多次 web_search + financial_report 累积，早期结果被推出保护区
3. **客户交接**：8+ 步查询多个实体，早期查询结果被推出保护区

短对话（3-5 步）中所有 ToolMessage 都在保护区内，Pass 2 不会执行。

**CRM 工具摘要模板 [HA 模式 + NEW CRM 内容]**：

```python
def _summarize_crm_tool_result(tool_name, tool_args, tool_content):
    """CRM 工具专用信息摘要，零 LLM 成本"""
    
    if tool_name == "query_data":
        entity = tool_args.get("entity", "?")
        # 从返回内容中提取记录数
        count = extract_record_count(tool_content)
        total_amount = extract_total_amount(tool_content)
        amount_str = f", 总金额{total_amount}" if total_amount else ""
        return f"[query_data] 查询 {entity}，返回 {count} 条记录{amount_str}"
    
    if tool_name == "modify_data":
        entity = tool_args.get("entity", "?")
        action = tool_args.get("action", "update")
        record_name = extract_record_name(tool_content)
        return f"[modify_data] {action} {entity}({record_name})"
    
    if tool_name == "analyze_data":
        analysis_type = tool_args.get("type", "?")
        return f"[analyze_data] {analysis_type} 分析 ({len(tool_content):,} chars)"
    
    if tool_name == "query_schema":
        entity = tool_args.get("entity", "?")
        field_count = tool_content.count('"api_key"')
        return f"[query_schema] {entity} 实体定义，{field_count} 个字段"
    
    if tool_name == "web_search":
        query = tool_args.get("query", "?")
        return f"[web_search] 搜索 '{query}' ({len(tool_content):,} chars)"
    
    if tool_name == "financial_report":
        company = tool_args.get("company", "?")
        return f"[financial_report] {company} 财报 ({len(tool_content):,} chars)"
    
    if tool_name == "company_info":
        keyword = tool_args.get("keyword", "?")
        return f"[company_info] {keyword} 工商信息 ({len(tool_content):,} chars)"
    
    # 通用 fallback
    first_arg = next(iter(tool_args.values()), "")
    return f"[{tool_name}] {str(first_arg)[:40]} ({len(tool_content):,} chars)"
```

**场景举例：10 轮竞品调研对话**

```
销售经理让 Agent 调研华为并生成竞品分析报告，经过 10 轮对话:

  Turn 1: web_search("华为 2025 公司概况") → 2,100 chars
  Turn 2: financial_report("华为") → 3,500 chars
  Turn 3: company_info("华为技术有限公司") → 1,800 chars
  Turn 4: web_search("华为竞品 中兴 爱立信") → 2,200 chars
  Turn 5: financial_report("中兴") → 3,200 chars
  Turn 6: web_search("华为 5G 市场份额") → 1,900 chars
  Turn 7: analyze_data("competitive_comparison") → 2,500 chars
  Turn 8: query_data("opportunity", filter={competitor: "华为"}) → 1,500 chars
  Turn 9: web_search("华为 东南亚 合作伙伴") → 2,100 chars
  Turn 10: LLM 生成最终报告

保护区（token 预算 ~20K tokens，约 80K 字符）:
  Turn 7-9 在保护区内 → 完整保留

保护区外（Turn 1-6）的信息摘要替换:
  Turn 1: "[web_search] 搜索 '华为 2025 公司概况' (2,100 chars)"
  Turn 2: "[financial_report] 华为 财报 (3,500 chars)"
  Turn 3: "[company_info] 华为技术有限公司 工商信息 (1,800 chars)"
  Turn 4: "[web_search] 搜索 '华为竞品 中兴 爱立信' (2,200 chars)"
  Turn 5: "[financial_report] 中兴 财报 (3,200 chars)"
  Turn 6: "[web_search] 搜索 '华为 5G 市场份额' (1,900 chars)"

节省: Turn 1-6 原文 14,700 chars → 摘要 ~400 chars = 节省 97%
关键: LLM 仍然知道"之前查过华为财报、中兴财报、竞品对比"，
      只是看不到具体数字了（但 Turn 2 的 assistant 回复中已经
      包含了"华为营收8809亿"等关键数字，assistant 消息不被裁剪）
```

### 3.3 Pass 3: tool_call 参数截断 [HA]

**机制**：保护区外的 assistant 消息中，tool_call 的 arguments 超过 500 字符时截断到 200 字符。

**场景举例：modify_data 的大参数**

```
Turn 3 中 LLM 调用了:
  modify_data(entity="opportunity", action="update", data={
    "name": "PT Sentosa Jaya - ERP Implementation",
    "stage": "proposal",
    "amount": 45000,
    "close_date": "2025-07-17",
    "requirement_desc": "客户需要生产排程自动化系统，当前使用Excel..."(2000字),
    "meeting_notes": "2025-04-17 会议纪要：参会人员 Pak Budi..."(1500字)
  })
  → arguments 总计 ~4,000 字符

截断处理（保护区外时）:
  arguments → 前 200 字符 + "...[truncated]"
  → '{"entity":"opportunity","action":"update","data":{"name":"PT Sentosa Jaya - ERP Implementation","stage":"proposal","amount":45000,"close_date":"2025-07-17","requirement_desc":"客户需要生产排程自动化...[truncated]'

节省: 4,000 → 220 字符
LLM 仍然知道"修改了 opportunity 的 stage 和 amount"，
但看不到 requirement_desc 的完整内容（不影响后续推理）
```

---

## 四、Layer 3：回复摘要回写

### 4.1 answerSummary 异步生成 [NA+NEW]

**机制**：最终回复 >500 字符时，异步调用 LLM 生成摘要，写入 DB。不阻塞前端 message_finish。

**场景举例：竞品分析报告的摘要**

```
answer_question_node 生成了 2,000 字符的竞品分析报告:

  "# 华为竞品分析报告
   ## 一、公司概况
   华为技术有限公司成立于1987年，注册资本4104113万元...
   2025年实现营收8809亿元，净利润680亿元...
   ## 二、财务对比
   | 指标 | 华为 | 中兴 |
   | 营收 | 8809亿 | 1252亿 |
   ...
   ## 三、竞争格局
   ..."

处理流程:
  1. 流式推送给前端（用户实时看到报告内容）:
     async for chunk in model.astream(...):
         await neo_ai_emit_message(config, chunk)

  2. 异步生成摘要（不阻塞前端）:
     asyncio.create_task(update_answer_summary(response))
     await neo_ai_emit_message_finish(config)  ← 立即发送，不等摘要
     
     # 后台异步执行:
     answerSummary = "华为2025年营收8809亿/净利680亿/研发占比21.8%，
       对比中兴营收1252亿/净利88亿/研发占比18.2%。
       华为优势:全栈自研+5G领先，中兴优势:性价比+运营商关系。"
     message_.answerSummary = answerSummary  → 写入 DB

  3. 下次对话加载历史时:
     conversation_history 中使用 answerSummary（~120 字）
     而非完整报告（2,000 字符）

用户感知: 报告流式输出完毕后立即看到"完成"，无 1-3s 等待
```

**场景举例：短回复不触发摘要**

```
用户: "帮我把 PT Sentosa Jaya 的商机阶段改为 proposal"

Agent 回复（180 字符）:
  "已将 PT Sentosa Jaya 的商机阶段从 qualification 更新为 proposal，
   预计关闭日期 2025-07-17，金额 $45,000。"

处理: 180 < 500 → 不触发摘要
下次加载历史: 直接使用完整 answer（180 字符本身就很精简）
```

### 4.2 sessionSummary 迭代更新 [HA+NEW]

**机制**：每次会话维护一份结构化摘要，存入 Redis。首次从零生成，后续迭代更新（PRESERVE + ADD + MOVE）。

**CRM 专属摘要模板 [HA 结构 + NEW CRM 内容]**：

```
## Active Task
[逐字复制用户最近的未完成请求]

## 客户上下文
[当前涉及的客户名称、行业、规模]

## 已完成操作
[编号列表: N. 操作 目标 — 结果]

## 关键数据
[精确数字：金额、日期、百分比、客户名、商机名]

## 已回答问题
[已回答的用户问题及答案]

## 待处理
[未完成的用户请求]

## 涉及实体
[操作过的 CRM 实体及记录 ID]
```

**场景举例：20 轮 Coaching 对话的迭代摘要**

```
═══ 第 1 轮 ═══
用户: "帮我分析一下 Andi 这个月的销售业绩"
Agent: 查询 Andi 的商机数据，生成业绩分析

首次 sessionSummary（从零生成）:
  ## Active Task
  分析 Andi 本月销售业绩
  ## 客户上下文
  销售人员 Andi，本月数据
  ## 已完成操作
  1. 查询 Andi 的 opportunity 列表 — 8个商机，总金额$280K，3个at_risk
  ## 关键数据
  商机数: 8, 总金额: $280K, 风险商机: 3, 赢单率: 25%
  ## 已回答问题
  无
  ## 待处理
  无
  ## 涉及实体
  opportunity(opp_101~opp_108), user(andi_001)

═══ 第 5 轮 ═══
用户: "那 3 个风险商机具体是什么情况"
Agent: 查询 3 个风险商机详情

迭代更新 sessionSummary（传入上次摘要 + 新增内容）:
  ## Active Task
  分析 Andi 的 3 个风险商机详情
  ## 客户上下文
  销售人员 Andi，本月数据
  ## 已完成操作
  1. 查询 Andi 的 opportunity 列表 — 8个商机，总金额$280K，3个at_risk
  2. 查询风险商机 opp_103 详情 — PT ABC, $65K, 15天未联系+竞品威胁
  3. 查询风险商机 opp_105 详情 — CV XYZ, $42K, 阶段停留25天
  4. 查询风险商机 opp_107 详情 — PT DEF, $38K, 决策人变更
  ## 关键数据
  Andi 商机数: 8, 总金额: $280K, 风险商机: 3
  风险商机: opp_103($65K,PT ABC), opp_105($42K,CV XYZ), opp_107($38K,PT DEF)
  ## 已回答问题
  Q: Andi 本月业绩如何 → 8个商机$280K，赢单率25%，3个at_risk
  Q: 3个风险商机什么情况 → 分别是竞品威胁/阶段停留/决策人变更
  ## 待处理
  无
  ## 涉及实体
  opportunity(opp_101~opp_108), user(andi_001), account(acc_abc,acc_xyz,acc_def)

═══ 第 12 轮 ═══
用户: "帮 Andi 制定一个跟进策略"
Agent: 基于分析结果生成跟进策略

迭代更新:
  ## Active Task
  为 Andi 制定风险商机跟进策略
  ## 已完成操作
  1-4. (保留之前的)
  5. 分析 opp_103 竞品威胁 — Odoo 在报价，客户对价格敏感
  6. 分析 opp_105 停滞原因 — 客户内部预算审批延迟
  7. 生成跟进策略 — 3个商机分别制定差异化策略
  ## 关键数据
  (保留之前的 + 新增)
  opp_103 竞品: Odoo, 客户预算敏感
  opp_105 停滞原因: 预算审批延迟
  ## 已回答问题
  (保留之前的 + 新增)
  Q: 帮 Andi 制定跟进策略 → opp_103:价值差异化+ROI分析,
     opp_105:联系CFO推动审批, opp_107:重新mapping决策链
  ## 待处理
  无

关键: 第 12 轮时，第 1 轮的"Andi 8个商机$280K"仍然完整保留
     如果没有迭代摘要，第 6 轮后早期信息就开始衰减
```

### 4.3 摘要失败容错 [HA]

**场景举例：摘要 LLM 调用超时**

```
answer_question_node 生成了 1,500 字符的回复
asyncio.create_task(update_answer_summary(response))

后台执行:
  agent_summary_model().ainvoke([...])
  → 超时（30s timeout）
  → 捕获异常，answerSummary 保持为 None

下次加载历史时:
  _message.answerSummary → None
  fallback: 使用完整 _message.answer（1,500 字符）
  → 上下文稍大但不影响功能

冷却机制:
  摘要失败 → 设置 Redis key: summary_cooldown:{conversation_id} = 60s
  60s 内的后续回复 → 跳过摘要生成，直接使用完整 answer
  60s 后 → 恢复正常摘要
```

**场景举例：摘要模型不可用**

```
配置的摘要模型 gemini-flash 返回 404

处理:
  1. 首次失败: 记录日志，自动降级到主模型重试
  2. 主模型也失败: 设置冷却 600s（10分钟）
  3. 冷却期间: 所有回复跳过摘要，使用完整 answer
  4. 10分钟后: 恢复尝试

Redis 状态:
  summary_model_fallback:{conversation_id} = "main_model"  (TTL=1h)
  summary_cooldown:{conversation_id} = timestamp  (TTL=600s)
```


---

## 五、Layer 4：历史上下文构建

### 5.1 双套历史视图 [NA]

**机制**：从 DB 加载最近 5 轮历史，构建两套视图供不同节点使用。

**场景举例：第 6 轮对话的上下文构建**

```
数据库中的历史（最近 5 轮）:

  轮次 1: query="帮我查一下 PT Sentosa Jaya"
          answer="PT Sentosa Jaya 是一家制造业公司，200人..."(800字符)
          answerSummary="PT Sentosa Jaya, 制造业, 200人, 评分87"(50字符)

  轮次 2: query="这个客户有哪些商机"
          answer="PT Sentosa Jaya 有3个活跃商机: 1. ERP实施 $45K..."(1200字符)
          answerSummary="3个活跃商机: ERP $45K/CRM $28K/BI $15K, 总$88K"(60字符)

  轮次 3: query="帮我分析 ERP 这个商机的 BANT"
          answer="BANT分析结果: Budget $40-50K已确认..."(2800字符)
          answerSummary="BANT: B=$40-50K确认/A=Pak Budi推荐者/N=排程自动化/T=3个月"(70字符)

  轮次 4: query="竞品 Odoo 的定价是多少"
          answer="Odoo Enterprise $24.90/user/month..."(1500字符)
          answerSummary="Odoo Enterprise $24.90/user/month, 制造模块+$18, 50+用户15%折扣"(80字符)

  轮次 5: query="帮我生成一份报价方案"
          answer="# PT Sentosa Jaya 报价方案\n..."(3000字符)
          answerSummary="报价方案: $45K(年付15%折扣=$38.25K), 含ERP+排程模块, 8周实施"(75字符)

构建视图 1 — conversation_history（传给 reasoning）:
  [
    {role: "user", content: "帮我查一下 PT Sentosa Jaya"},
    {role: "assistant", content: "PT Sentosa Jaya, 制造业, 200人, 评分87"},  ← answerSummary
    {role: "user", content: "这个客户有哪些商机"},
    {role: "assistant", content: "3个活跃商机: ERP $45K/CRM $28K/BI $15K, 总$88K"},
    {role: "user", content: "帮我分析 ERP 这个商机的 BANT"},
    {role: "assistant", content: "BANT: B=$40-50K确认/A=Pak Budi推荐者/N=排程自动化/T=3个月"},
    {role: "user", content: "竞品 Odoo 的定价是多少"},
    {role: "assistant", content: "Odoo Enterprise $24.90/user/month, 制造模块+$18, 50+用户15%折扣"},
    {role: "user", content: "帮我生成一份报价方案"},
    {role: "assistant", content: "报价方案: $45K(年付15%折扣=$38.25K), 含ERP+排程模块, 8周实施"},
  ]
  总计: ~500 字符（5 轮 answerSummary）

构建视图 2 — file_list 虚拟文件（传给意图识别 + 按需引用）:
  [
    FileInfo(path="/conversation_history", name="history_1.md",
             content="PT Sentosa Jaya 是一家制造业公司，200人...",  ← 完整 answer
             summary="PT Sentosa Jaya, 制造业, 200人, 评分87",     ← answerSummary
             extend={"query": "帮我查一下 PT Sentosa Jaya"}),
    FileInfo(path="/conversation_history", name="history_2.md",
             content="PT Sentosa Jaya 有3个活跃商机...",
             summary="3个活跃商机: ERP $45K/CRM $28K/BI $15K",
             extend={"query": "这个客户有哪些商机"}),
    ...
  ]

reasoning 节点收到的上下文:
  [SystemPrompt] + [sessionSummary] + [conversation_history(~500字符)] + [当前messages]
  → 上下文精简，推理快

意图识别节点收到的上下文:
  从 file_list 提取: "user:帮我查一下...\nassistant:PT Sentosa Jaya, 制造业...\n..."
  → 只用 summary，不用完整 answer
```

### 5.2 sessionSummary 注入 [HA+NEW]

**机制**：从 Redis 加载 sessionSummary，作为 SystemMessage 注入 reasoning 循环。

**场景举例：第 15 轮 Coaching 对话**

```
Redis 中的 sessionSummary（经过多次迭代更新）:

  key: session_summary:conv_12345
  value: "
    ## Active Task
    为 Andi 的 opp_103 制定具体的竞品应对话术

    ## 客户上下文
    销售人员 Andi，本月 8 个商机，3 个 at_risk

    ## 已完成操作
    1. 查询 Andi pipeline — 8个商机$280K，赢单率25%
    2. 分析 3 个风险商机 — opp_103竞品/opp_105停滞/opp_107决策人变更
    3. 查询 opp_103 竞品 Odoo 定价 — $24.90/user/month
    4. 制定跟进策略 — 3个商机差异化策略
    5. 为 opp_105 联系 CFO — 已发送邮件模板

    ## 关键数据
    Andi: 8商机/$280K/赢单率25%
    opp_103: PT ABC, $65K, 竞品Odoo $24.90/user/month
    opp_105: CV XYZ, $42K, 预算审批延迟
    opp_107: PT DEF, $38K, 决策人从CTO变更为COO

    ## 已回答问题
    Q: Andi业绩 → 8商机$280K
    Q: 风险商机 → 3个(竞品/停滞/决策人变更)
    Q: 跟进策略 → 差异化(价值对比/推动审批/重新mapping)

    ## 待处理
    为 opp_103 制定竞品应对话术

    ## 涉及实体
    opportunity(opp_101~108), user(andi_001), account(acc_abc,acc_xyz,acc_def)
  "

注入 reasoning 的消息列表:
  [
    SystemMessage(content=SINGLE_AGENT_SYSTEM_PROMPT),
    SystemMessage(content="[CONTEXT COMPACTION — REFERENCE ONLY]...\n" + sessionSummary),
    *conversation_history,  ← 最近 5 轮的 answerSummary
    *messages               ← 当前轮次的消息
  ]

效果: 第 15 轮时，LLM 仍然知道第 1 轮的"Andi 8个商机$280K"
     和第 3 轮的"Odoo $24.90/user/month"
     → 不会重复查询，不会丢失关键数据
```

### 5.3 Prompt Cache [HA]

**机制**：对 Anthropic 模型应用 system_and_3 缓存策略，4 个 cache_control 断点。

**场景举例：多轮对话的缓存命中**

```
第 N 轮的 API 请求:
  messages = [
    {role: "system", content: "你是智能任务助手...",
     cache_control: {"type": "ephemeral"}},          ← 断点 1: system prompt（跨轮稳定）
    {role: "user", content: "帮我查客户"},
    {role: "assistant", content: "查询结果..."},
    {role: "user", content: "分析 BANT",
     cache_control: {"type": "ephemeral"}},          ← 断点 2: 倒数第 3 条
    {role: "assistant", content: "BANT 分析...",
     cache_control: {"type": "ephemeral"}},          ← 断点 3: 倒数第 2 条
    {role: "user", content: "竞品定价多少",
     cache_control: {"type": "ephemeral"}},          ← 断点 4: 最后一条
  ]

第 N+1 轮:
  system prompt 缓存命中（断点 1 不变）
  前面的消息缓存命中（前缀匹配）
  只有最后 1-2 条消息是新增的
  → 输入 token 成本降低 ~75%
```

---

## 六、辅助 LLM 路由 [HA]

**机制**：摘要调用使用便宜快速模型，与主推理模型分离。

**场景举例：成本优化**

```
配置:
  auxiliary:
    compression:
      model: "gemini-flash"        # 摘要用便宜模型
      timeout: 30
    intent:
      model: "gemini-flash"        # 意图识别用便宜模型
      timeout: 15

主推理: doubao-pro / qwen-max      # 强模型

一次完整对话的 LLM 调用:
  1. 语种识别: gemini-flash (0.01$/M tokens)     ~200 tokens
  2. 安全检查: gemini-flash                       ~300 tokens
  3. 意图识别: gemini-flash                       ~500 tokens
  4. Reasoning: doubao-pro (0.10$/M tokens)       ~3,000 tokens
  5. 子 Agent 执行: doubao-pro                    ~5,000 tokens
  6. 工具结果摘要: gemini-flash                   ~800 tokens
  7. 最终回复: doubao-pro                         ~2,000 tokens
  8. answerSummary: gemini-flash                  ~600 tokens
  9. sessionSummary 更新: gemini-flash            ~1,000 tokens

成本对比:
  全部用 doubao-pro: 12,400 tokens × $0.10/M = $0.00124
  分离后: 3,400 tokens(flash) × $0.01/M + 10,000 tokens(pro) × $0.10/M
        = $0.000034 + $0.001 = $0.001034
  节省: 16.6%
  
  规模化（100 租户 × 50 次/天）:
  全部 pro: $6.20/天
  分离后: $5.17/天
  月节省: ~$31
```

---

## 七、反抖动与熔断 [HA+CC]

**场景举例：反抖动保护**

```
场景: 用户上传了一个 50 页的 PDF 文档，Agent 反复分析

  压缩 #1: 上下文 45K tokens → 压缩后 42K tokens（节省 6.7%）
  压缩 #2: 上下文 44K tokens → 压缩后 41K tokens（节省 6.8%）
  → 连续 2 次节省 <10%

  压缩 #3: 跳过！
  日志: "Compression skipped — last 2 compressions saved <10% each.
         Consider starting a new session."

  原因: 上下文中大部分是当前轮次的 ToolMessage 摘要（在保护区内），
        可压缩的旧内容很少。继续压缩只会浪费 LLM 调用。
```

---

## 八、完整数据流（端到端场景）

### 8.1 短对话场景（主路径：Layer 1 → Layer 3 → Layer 4）

**场景：销售查询客户信息并修改商机阶段（3 步，不触发 Layer 2）**

```
用户: "帮我把 PT Sentosa Jaya 的 ERP 商机阶段改为 proposal"

Layer 4 — 历史构建:
  从 DB 加载最近 5 轮 answerSummary → conversation_history
  从 Redis 加载 sessionSummary → 注入 SystemMessage

意图识别 → topic: opportunity_management
Reasoning Step 1 → execute_task("query_opportunity")

Layer 1 — 源头隔离:
  子 Agent 查询商机 → 返回 600 字符
  600 > 300（查询类阈值）→ 两层摘要:
    代码提取: extract_from_json → "查询返回1条记录: PT Sentosa Jaya ERP"
    → 成功，不调 LLM
  ToolMessage: "查询返回1条记录: PT Sentosa Jaya ERP"

Reasoning Step 2 → execute_task("modify_opportunity")

Layer 1 — 源头隔离:
  子 Agent 修改商机 → 返回 150 字符（"修改成功"）
  150 < 300 → 不摘要，原文回传

Layer 2 检查: ToolMessage 数量 = 2 < 5 → 不触发

Reasoning Step 3 → answer_question

Layer 3 — 回复摘要:
  最终回复 180 字符 < 500 → 不触发 answerSummary
  sessionSummary 迭代更新（异步）

总 LLM 摘要调用: 0 次（代码提取覆盖）
总上下文: ~2,500 tokens
```

### 8.2 复杂对话场景（辅助路径：Layer 1 → Layer 2 → Layer 3 → Layer 4）

**场景：销售经理进行 Pipeline Review（跨 8 轮对话）**

```
═══ 第 1 轮 ═══
用户: "帮我看一下本月所有商机"

Layer 4 — 历史构建:
  首次对话，无历史，无 sessionSummary
  messages = [HumanMessage("帮我看一下本月所有商机")]

意图识别 → topic: pipeline_analysis
Reasoning → 调用 execute_task(task="query_pipeline")

Layer 1 — 源头隔离:
  子 Agent 执行 query_data → 返回 100 条商机 (35K chars)
  前端: neo_ai_emit_custom(pipeline_dashboard 组件)  ← 用户立即看到仪表盘
  LLM 摘要（查询类，阈值 300）:
    "100条商机, 总金额$3.6M, prospecting 25/qualification 30/proposal 20/
     negotiation 18/closing 7, 15个超30天未跟进"  (~90字)
  虚拟文件: FileInfo(content=35K原文, summary=90字摘要)

Layer 3 — 回复摘要:
  最终回复 1,200 字符 → asyncio.create_task(answerSummary)
  answerSummary: "本月100个商机$3.6M, 按阶段prospecting25/qual30/proposal20/
    nego18/closing7, 15个超30天未跟进, 谈判阶段环比减少40%"
  sessionSummary（首次生成）:
    ## Active Task: 分析本月 pipeline
    ## 已完成操作: 1. 查询 pipeline — 100商机$3.6M
    ## 关键数据: 100商机/$3.6M/15个超30天未跟进

═══ 第 3 轮 ═══
用户: "Andi 的那 3 个风险商机具体是什么情况"

Layer 4 — 历史构建:
  conversation_history: 轮次1-2 的 answerSummary (~200字符)
  sessionSummary 从 Redis 加载 → 注入 SystemMessage
  file_list: 轮次1-2 的虚拟文件

Reasoning → 调用 execute_task(task="query_risk_opportunities", params={owner:"Andi"})

Layer 1 — 源头隔离:
  子 Agent 查询 3 个风险商机详情 → 返回 2,400 chars
  前端: neo_ai_emit_custom(risk_opportunity_cards 组件)
  LLM 摘要（分析类，阈值 800）:
    "Andi 3个风险商机: opp_103 PT ABC $65K 15天未联系+竞品Odoo,
     opp_105 CV XYZ $42K 阶段停留25天, opp_107 PT DEF $38K 决策人变更"  (~120字)

Layer 2 — 工具结果裁剪:
  当前轮次只有 1 个 ToolMessage → 不触发裁剪（<保护区）

Layer 3 — 回复摘要:
  sessionSummary 迭代更新:
    ## 已完成操作: 1. 查询pipeline... 2. 查询Andi风险商机 — 3个详情
    ## 关键数据: (保留之前) + opp_103/$65K/竞品 + opp_105/$42K/停滞 + opp_107/$38K/决策人变更

═══ 第 6 轮 ═══
用户: "帮 Andi 制定跟进策略，特别是 opp_103 的竞品应对"

Layer 4 — 历史构建:
  conversation_history: 轮次2-5 的 answerSummary（轮次1已超出5轮窗口）
  sessionSummary: 包含轮次1的"100商机$3.6M"（迭代摘要保留了！）
  → 即使轮次1的 answerSummary 不在 conversation_history 中，
    sessionSummary 仍然保留了关键数据

Reasoning → 多步执行:
  Step 1: web_search("Odoo vs 我方产品 优势对比") → 2,100 chars
  Step 2: analyze_data("competitive_strategy", opp_id="opp_103") → 1,800 chars
  Step 3: 生成跟进策略

Layer 2 — 工具结果裁剪（Step 3 的 reasoning 前）:
  当前轮次有 2 个 ToolMessage
  都在保护区内（<20K tokens）→ 不裁剪

Layer 3 — 回复摘要:
  sessionSummary 迭代更新:
    ## Active Task: 为 opp_103 制定竞品应对话术
    ## 已完成操作: 1-4(保留) + 5. 搜索竞品对比 + 6. 生成跟进策略
    ## 已回答问题: Q:跟进策略 → opp_103价值差异化/opp_105推动审批/opp_107重新mapping

═══ 第 8 轮 ═══
用户: "把刚才的策略发给 Andi，并创建跟进任务"

Layer 4 — 历史构建:
  conversation_history: 轮次4-7 的 answerSummary
  sessionSummary: 完整保留了 8 轮的所有关键数据和操作历史
  → LLM 知道"刚才的策略"是什么（在 sessionSummary 的已完成操作中）

Reasoning → 执行:
  Step 1: send_notification(to="Andi", content=策略内容)
  Step 2: modify_data(entity="activity", action="create", data={type:"follow_up"...})

Layer 1 — 源头隔离:
  两个工具结果都 <300 字符 → 不触发摘要，原文回传

Layer 3 — 回复摘要:
  最终回复 350 字符 < 500 → 不触发 answerSummary
  sessionSummary 迭代更新:
    ## 已完成操作: 1-6(保留) + 7. 发送策略给Andi + 8. 创建跟进任务(activity_xxx)
    ## 待处理: None
```

**上下文占用统计（第 8 轮）**:

| 组成部分 | 大小 | 来源 |
|---------|------|------|
| System Prompt | ~2,000 tokens | 固定 |
| sessionSummary | ~400 tokens | Redis，迭代更新 |
| conversation_history（轮次4-7） | ~250 tokens | DB，answerSummary |
| 当前轮次 messages | ~500 tokens | 当前 reasoning |
| **总计** | **~3,150 tokens** | |

对比无压缩方案（8 轮完整消息链）: ~25,000 tokens
**节省: 87%**

---

## 九、各设计点参考来源汇总

| 设计点 | [CC] | [HA] | [NA] | [NEW] | 所在 Layer |
|--------|:----:|:----:|:----:|:-----:|-----------|
| 前端组件分流 | | | ✅ | | Layer 1 |
| 工具结果 LLM 摘要（>500 字符触发） | | | ✅ | | Layer 1 |
| 动态摘要阈值（按工具类型分三档） | | | | ✅ | Layer 1 |
| 两层摘要策略（代码格式化优先 + LLM 兜底） | | ✅(思路) | ✅(LLM层) | ✅(组合) | Layer 1 |
| 代码格式化提取（extract_from_component） | | ✅(思路) | | ✅(CRM实现) | Layer 1 |
| JSON 列表代码提取（extract_from_json） | | ✅(思路) | | ✅(CRM实现) | Layer 1 |
| CustomContent 文本化（template2str/schema2str） | | | ✅ | | Layer 1 |
| Layer 2 触发条件（ToolMessage ≥5 且总量 >3000） | | | | ✅ | Layer 2 |
| MD5 去重（从末尾向前遍历，取前12位） | | ✅ | | | Layer 2 |
| MD5 去重适配（阈值降到100，每轮reasoning前执行） | | | | ✅ | Layer 2 |
| CRM 工具信息摘要替换（零 LLM 成本规则模板） | | ✅(模式) | | ✅(CRM模板) | Layer 2 |
| tool_call 参数截断（>500截到200） | | ✅ | | | Layer 2 |
| answerSummary 回写（>500字符触发） | | | ✅ | | Layer 3 |
| answerSummary 异步化（asyncio.create_task） | | | | ✅ | Layer 3 |
| sessionSummary 迭代更新（PRESERVE/ADD/MOVE） | | ✅ | | | Layer 3 |
| sessionSummary 存 Redis（适配 SaaS 无状态） | | | | ✅ | Layer 3 |
| CRM 专属摘要模板（7 section） | | ✅(结构) | | ✅(CRM内容) | Layer 3 |
| 摘要前缀隔离指令（REFERENCE ONLY） | | ✅ | | | Layer 3 |
| 摘要失败冷却（60s/600s） | | ✅ | | | Layer 3 |
| 摘要模型降级（自动切换到主模型） | | ✅ | | | Layer 3 |
| 双套历史视图（conversation_history + file_list） | | | ✅ | | Layer 4 |
| sessionSummary 注入 reasoning | | ✅(注入方式) | | ✅(Redis加载) | Layer 4 |
| Prompt Cache system_and_3（4个断点） | | ✅ | | | Layer 4 |
| 辅助 LLM 路由（按 task 选模型） | | ✅ | | | 全局 |
| 反抖动（连续2次<10%跳过） | | ✅ | | | 全局 |
| 失败计数器存 Redis | ✅(思路) | | | ✅(SaaS适配) | 全局 |
| 虚拟文件 FileInfo（content+summary） | | | ✅ | | 全局 |
| 多语言摘要（按 language_name 返回） | | | ✅ | | 全局 |
| Redis 状态持久化（checkpoint+摘要+冷却） | | | ✅(checkpoint) | ✅(摘要+冷却) | 全局 |

**来源统计**：
- **[NA] 保留 11 项**：前端组件分流、LLM 摘要、CustomContent 文本化、answerSummary 回写、双套历史视图、虚拟文件、多语言摘要、Redis checkpoint 等
- **[HA] 引入 13 项**：MD5 去重、信息摘要替换、tool_call 截断、迭代摘要、摘要前缀隔离、失败冷却、模型降级、Prompt Cache、辅助 LLM 路由、反抖动、代码格式化提取思路等
- **[CC] 引入 1 项思路**：失败计数器/熔断器
- **[NEW] 新增 10 项**：动态阈值、两层摘要策略、代码格式化 CRM 实现、JSON 提取、MD5 适配、Layer 2 触发条件、answerSummary 异步化、sessionSummary 存 Redis、CRM 摘要模板内容、Redis 状态扩展
