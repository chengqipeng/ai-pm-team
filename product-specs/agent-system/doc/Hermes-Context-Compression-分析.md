# CRM Agent 上下文压缩 — 业务与技术闭环设计

> 设计原则：不回避大数据问题。CRM 业务中的大文本字段、完整搜索结果、百级商机列表是客观存在的业务现实。本方案正面解决"数据就是这么大"的问题，从业务维度和技术维度分别设计闭环方案。

---

## 一、问题定义：CRM 场景中不可回避的大数据问题

### 1.1 六类不可回避的大数据源

| 编号 | 数据源 | 业务现实 | 真实数据量 | 为什么不能砍 |
|------|--------|---------|-----------|-------------|
| D1 | 大文本字段 | 客户的"备注"字段、商机的"需求描述"、活动的"会议纪要" | 单字段 2K-20K 字符 | 销售写了详细的客户背景和需求分析，砍掉等于丢失核心业务信息 |
| D2 | 完整搜索全文 | 竞品调研需要抓取完整网页内容，不是 snippet 能替代的 | 单页 10K-80K 字符 | snippet 只有 200 字，无法获取定价表、功能对比矩阵等结构化信息 |
| D3 | 百级商机列表 | 销售总监要看全部 pipeline，不是 Top 10 | 100-500 条 × 150 字符/条 = 15K-75K 字符 | 管理层需要全局视角，过滤后看不到长尾问题 |
| D4 | 跨实体完整关联 | 一个客户的所有商机+联系人+活动+报价+合同 | 4-8 个实体 × 5K-15K = 20K-120K 字符 | 拜访准备需要完整画像，缺任何一个维度都不完整 |
| D5 | 对话记录全文 | 一个月的 WhatsApp 聊天记录，含语音转文字 | 50-200 条 × 100-500 字符 = 5K-100K 字符 | 经理要复盘具体沟通细节，摘要无法替代原文中的语气和承诺 |
| D6 | 元数据完整定义 | 一个实体 30-50 个字段的完整 schema | 单实体 5K-20K 字符 | Agent 构建查询/修改操作时需要知道每个字段的类型、选项值、校验规则 |

### 1.2 核心矛盾  

```
业务需求：完整数据 → LLM 才能做出准确判断
技术限制：上下文窗口有限（64K-200K tokens）→ 放不下所有数据
用户体验：压缩延迟 → 用户等待时间增加

三者不可能同时满足，必须在不同场景下做不同的取舍。
```

---

## 二、技术架构：三层处理模型

不是简单的"压缩"，而是一个完整的数据处理管线：

```
                    ┌─────────────────────────────┐
                    │  Layer 0: 外部存储层          │
                    │  数据不进入上下文，但 Agent    │
                    │  可以按需读取                  │
                    │  技术: Scratchpad / File Store │
                    └──────────────┬──────────────┘
                                   │
                    ┌──────────────▼──────────────┐
                    │  Layer 1: 语义提取层          │
                    │  大数据进入前先做语义提取      │
                    │  提取物进入上下文，原文存外部   │
                    │  技术: 专用提取 Prompt / NER   │
                    └──────────────┬──────────────┘
                                   │
                    ┌──────────────▼──────────────┐
                    │  Layer 2: 上下文管理层        │
                    │  已在上下文中的数据的生命周期   │
                    │  管理（保护/压缩/清理/摘要）   │
                    │  技术: Microcompact / Summary  │
                    └──────────────┬──────────────┘
                                   │
                    ┌──────────────▼──────────────┐
                    │  Layer 3: 迭代摘要层          │
                    │  长对话的渐进式信息浓缩        │
                    │  技术: Hermes 迭代摘要机制     │
                    └─────────────────────────────┘
```

关键创新：**Layer 0（外部存储）和 Layer 1（语义提取）是 CRM 场景必须新增的**，Hermes 原始设计中没有这两层。

---

## 三、逐问题详细设计

### D1: 大文本字段处理

#### 业务维度

CRM 中的大文本字段是业务核心资产：

```
场景 1: 商机的"需求描述"字段
  内容: 销售花了 2 小时写的客户需求分析，包含:
  - 客户当前业务流程描述（3000 字）
  - 痛点分析（2000 字）
  - 客户组织架构和决策链（1500 字）
  - 竞品使用情况（1000 字）
  - 预算和时间线（500 字）
  总计: ~8000 字 ≈ 4000 tokens

场景 2: 活动的"会议纪要"字段
  内容: 一次 2 小时客户会议的完整纪要:
  - 参会人员和议程（500 字）
  - 讨论内容逐项记录（5000 字）
  - 客户提出的问题和我方回答（3000 字）
  - 行动项和下一步（1000 字）
  总计: ~9500 字 ≈ 4750 tokens

场景 3: 客户的"备注"字段
  内容: 多个销售在不同时期追加的备注:
  - 2024/03: 初次接触背景（1000 字）
  - 2024/06: 第一次丢单原因分析（2000 字）
  - 2025/01: 重新激活原因（1500 字）
  - 2025/03: 当前跟进策略（1000 字）
  总计: ~5500 字 ≈ 2750 tokens
```

**业务要求**：Agent 在分析商机时，需要理解需求描述的完整语境；在准备拜访时，需要看到会议纪要中的具体承诺；在制定策略时，需要了解历史备注中的丢单原因。这些不能靠"只看前 200 字"解决。

#### 技术维度：双通道处理

```
┌─────────────────────────────────────────────────────────────┐
│ 大文本字段的双通道处理                                        │
│                                                              │
│ 通道 A: 语义提取（进入上下文）                                │
│                                                              │
│ 当 Tool 返回包含大文本字段时（>1000 字符）:                    │
│                                                              │
│ 1. 调用语义提取器（轻量 LLM 或规则引擎）:                     │
│    输入: 原始大文本                                           │
│    输出: 结构化提取物                                         │
│                                                              │
│    示例 — 商机需求描述的提取:                                  │
│    原文: 8000 字的需求分析                                    │
│    提取物:                                                    │
│    {                                                         │
│      "core_needs": ["生产排程自动化", "库存实时可视"],          │
│      "pain_points": ["Excel排程每月出错3-5次", "库存盘点靠人工"],│
│      "decision_chain": {                                     │
│        "champion": "Pak Budi (IT Manager)",                  │
│        "economic_buyer": "Ibu Sari (CFO)",                   │
│        "end_users": "工厂主管 + 仓库团队 50人"                │
│      },                                                      │
│      "budget_signal": "$40K-50K，年付优先",                   │
│      "timeline": "希望3个月内上线核心模块",                    │
│      "competitors_mentioned": ["Odoo（免费版在用）", "SAP（太贵放弃）"],│
│      "key_quotes": [                                         │
│        "老板说如果能解决排程问题，预算不是问题",                │
│        "之前 Odoo 用了半年没推起来，这次想找有实施保障的"       │
│      ]                                                       │
│    }                                                         │
│    提取物大小: ~800 字符 ≈ 400 tokens（原文的 10%）           │
│                                                              │
│    示例 — 会议纪要的提取:                                     │
│    原文: 9500 字的会议纪要                                    │
│    提取物:                                                    │
│    {                                                         │
│      "attendees": ["Pak Budi", "Ibu Sari", "我方: 张三+李四"],│
│      "decisions": [                                          │
│        "客户同意进入POC阶段",                                 │
│        "POC范围: 生产排程模块，50个用户"                       │
│      ],                                                      │
│      "commitments": {                                        │
│        "customer": ["下周提供现有排程数据", "安排工厂参观"],    │
│        "us": ["3天内出POC方案", "提供沙箱环境"]               │
│      },                                                      │
│      "objections": [                                         │
│        {"issue": "实施周期太长", "response": "承诺核心模块8周"},│
│        {"issue": "数据迁移风险", "response": "提供免费迁移服务"}│
│      ],                                                      │
│      "next_steps": "4/22 POC启动会",                         │
│      "sentiment": "积极，CFO首次参会且态度正面"                │
│    }                                                         │
│    提取物大小: ~600 字符 ≈ 300 tokens（原文的 6%）            │
│                                                              │
│ 通道 B: 原文存储（不进入上下文，按需读取）                     │
│                                                              │
│ 原文写入 Scratchpad（Agent 的临时工作区）:                     │
│   scratchpad.write(                                          │
│     key="opp_xxx_requirement_desc",                          │
│     content=原始8000字需求描述,                                │
│     ttl=session_lifetime  // 会话结束后自动清理               │
│   )                                                          │
│                                                              │
│ 当 Agent 后续需要原文时:                                      │
│   content = scratchpad.read(key="opp_xxx_requirement_desc")  │
│   // 按需读取，不常驻上下文                                   │
│                                                              │
│ 当 Agent 需要原文中的特定段落时:                               │
│   content = scratchpad.search(                               │
│     key="opp_xxx_requirement_desc",                          │
│     query="竞品使用情况"                                      │
│   )                                                          │
│   // 语义搜索，只返回相关段落                                  │
└─────────────────────────────────────────────────────────────┘
```

#### 语义提取器的技术实现

```python
class FieldExtractor:
    """大文本字段的语义提取器"""
    
    # 按字段类型配置不同的提取 prompt
    EXTRACT_PROMPTS = {
        "requirement_desc": """
            从以下商机需求描述中提取结构化信息:
            - core_needs: 核心需求列表
            - pain_points: 痛点（含量化数据）
            - decision_chain: 决策链（角色+姓名）
            - budget_signal: 预算信号
            - timeline: 时间线
            - competitors_mentioned: 提到的竞品
            - key_quotes: 关键原话（最多3句，必须是原文）
            
            原文:
            {content}
        """,
        "meeting_notes": """
            从以下会议纪要中提取:
            - attendees: 参会人
            - decisions: 会上做出的决策
            - commitments: 双方承诺（分客户和我方）
            - objections: 客户异议及我方回应
            - next_steps: 下一步
            - sentiment: 整体情绪判断
            
            原文:
            {content}
        """,
        "account_notes": """
            从以下客户备注中提取:
            - timeline: 按时间线整理的关键事件
            - current_strategy: 当前跟进策略
            - historical_issues: 历史问题（如丢单原因）
            - relationship_map: 关系网络
            
            原文:
            {content}
        """
    }
    
    async def extract(self, field_type: str, content: str, context) -> dict:
        """
        对大文本字段做语义提取
        
        返回:
          extracted: 结构化提取物（进入上下文）
          scratchpad_key: 原文在 Scratchpad 中的 key（按需读取）
        """
        if len(content) < 1000:
            # 小文本不需要提取，直接进入上下文
            return {"extracted": content, "scratchpad_key": None}
        
        # 1. 原文存入 Scratchpad
        key = f"{field_type}_{hash(content)[:8]}"
        await context.scratchpad.write(key=key, content=content)
        
        # 2. 语义提取
        prompt = self.EXTRACT_PROMPTS.get(field_type, self.EXTRACT_PROMPTS["generic"])
        extracted = await context.llm.call(
            system_prompt="你是一个信息提取助手。只输出JSON，不要解释。",
            messages=[{"role": "user", "content": prompt.format(content=content)}],
            max_tokens=1000,
            model="fast"  # 用快速模型做提取，降低延迟
        )
        
        return {
            "extracted": extracted,
            "scratchpad_key": key,
            "original_size": len(content),
            "extracted_size": len(extracted)
        }
```

#### 按需回读原文的流程

```
场景: Agent 已经看到了提取物，但需要回读原文

用户: "需求描述里关于竞品的部分具体写了什么"

Agent 的处理:
  1. 检查提取物中的 competitors_mentioned: ["Odoo", "SAP"]
  2. 判断: 提取物只有竞品名称，没有详细描述
  3. 从 Scratchpad 按需读取:
     content = scratchpad.search(
       key="opp_xxx_requirement_desc",
       query="竞品 Odoo SAP 使用情况"
     )
     → 返回原文中关于竞品的段落（~1000 字符）
  4. 这 1000 字符临时进入上下文，Agent 基于它回答
  5. 下一轮，这段临时内容作为普通 tool_result 被管理
     → 超出最近 N 个后被 Microcompact 清理

关键: 原文不是丢了，而是"存在但不占上下文空间"。
Agent 随时可以回读，但只读需要的部分。
```

#### 闭环验证

```
业务闭环:
  ✅ Agent 能理解商机需求的核心要点（通过提取物）
  ✅ Agent 能回答关于原文细节的追问（通过 Scratchpad 回读）
  ✅ 销售写的详细内容不会丢失（原文完整存储）

技术闭环:
  ✅ 8000 字原文 → 800 字提取物进入上下文（节省 90%）
  ✅ 提取延迟: ~500ms（快速模型）
  ✅ Scratchpad 回读延迟: ~50ms（本地存储）
  ✅ 原文生命周期: 会话结束自动清理，不占持久存储
```


---

### D2: 网络搜索全文处理

#### 业务维度

CRM 场景中的搜索不是"查个天气"，而是深度竞品调研：

```
场景 1: "帮我调研 Odoo 在印尼的完整定价体系"
  需要的信息:
  - Odoo 官网定价页的完整价格表（按版本、按用户数、按模块）
  - 印尼本地合作伙伴的实施报价（通常在合作伙伴网站上）
  - 用户论坛上的真实成本反馈（隐性成本：定制、培训、维护）
  
  snippet 能给的: "Odoo Enterprise $24.90/user/month"
  实际需要的: 完整的价格矩阵 + 模块加价 + 用户数阶梯 + 实施费用
  → 必须抓取完整网页

场景 2: "搜一下 Salesforce 在东南亚的客户案例"
  需要的信息:
  - 案例的完整描述（行业、规模、痛点、方案、效果）
  - 不是一句话摘要，而是可以拿来做竞品对比的详细信息
  
  snippet 能给的: "Salesforce helped PT XYZ improve sales by 30%"
  实际需要的: 怎么做到的？用了哪些模块？实施了多久？团队多大？
  → 必须抓取案例详情页

场景 3: "调研东南亚 CRM 市场 2025 年的竞争格局"
  需要的信息:
  - 市场份额数据（通常在分析报告中，表格形式）
  - 各厂商的产品定位对比
  - 区域差异（印尼 vs 泰国 vs 越南）
  → 可能需要抓取 3-5 个完整网页
```

**业务要求**：竞品调研的价值在于信息的完整性和可对比性。snippet 级别的信息只能给出"知道有这个东西"，无法支撑"做出决策"。

#### 技术维度：搜索-抓取-提取-存储 管线

```
┌─────────────────────────────────────────────────────────────┐
│ 完整的搜索处理管线                                            │
│                                                              │
│ Step 1: 搜索（web_search）                                   │
│   输入: "Odoo pricing Indonesia 2025"                        │
│   输出: 5-10 条搜索结果（标题 + URL + snippet）               │
│   大小: ~2K tokens                                           │
│   → 搜索结果本身很小，直接进入上下文                           │
│                                                              │
│ Step 2: 智能选择抓取目标                                      │
│   Agent 基于搜索结果判断哪些页面值得抓取:                      │
│   - 结果 1: Odoo 官网定价页 → ✅ 抓取（官方数据）             │
│   - 结果 2: 博客文章"Odoo vs SAP" → ✅ 抓取（对比信息）       │
│   - 结果 3: Odoo 论坛帖子 → ❌ 跳过（用户讨论，信息密度低）   │
│   - 结果 4: 印尼合作伙伴网站 → ✅ 抓取（本地定价）            │
│   - 结果 5: 新闻稿 → ❌ 跳过（信息在 snippet 中已足够）       │
│                                                              │
│   Agent 选择抓取 3 个页面（而非全部 5 个）                     │
│   → 这是 Agent 的推理决策，不是硬编码规则                      │
│                                                              │
│ Step 3: 抓取全文（web_fetch）                                 │
│   对每个选中的 URL 抓取完整内容:                               │
│   - 页面 A: Odoo 定价页 → 35K 字符（含 HTML 噪音）           │
│   - 页面 B: 对比博客 → 20K 字符                              │
│   - 页面 C: 合作伙伴网站 → 15K 字符                          │
│   总计: 70K 字符 ≈ 17.5K tokens                              │
│   → 这个量直接放进上下文会占 34%，不可接受                     │
│                                                              │
│ Step 4: 语义提取（关键步骤）                                  │
│   对每个抓取的全文做目标导向的提取:                             │
│                                                              │
│   提取 Prompt:                                               │
│   "用户正在调研 Odoo 在印尼的定价。                            │
│    从以下网页内容中提取:                                       │
│    1. 产品版本和对应价格（完整价格表）                         │
│    2. 用户数阶梯定价                                          │
│    3. 模块加价信息                                            │
│    4. 实施/服务费用                                           │
│    5. 与竞品的对比数据                                        │
│    6. 印尼本地化的特殊定价                                    │
│    保留所有精确数字，不要概括。                                │
│    如果某项信息不存在，标注'未提及'。"                         │
│                                                              │
│   页面 A 提取物:                                              │
│   {                                                          │
│     "source": "odoo.com/pricing",                            │
│     "pricing_table": {                                       │
│       "community": "免费（开源）",                            │
│       "enterprise": {                                        │
│         "base": "$24.90/user/month (annual)",                │
│         "monthly": "$31.10/user/month",                      │
│         "modules": {                                         │
│           "CRM": "included",                                 │
│           "Manufacturing": "+$18/user/month",                │
│           "Inventory": "+$12/user/month",                    │
│           "Accounting": "+$12/user/month"                    │
│         }                                                    │
│       }                                                      │
│     },                                                       │
│     "volume_discount": "50+ users: 15% off, 100+: 25% off", │
│     "implementation": "未提及（官网不公开实施费用）",           │
│     "indonesia_specific": "未提及"                            │
│   }                                                          │
│   提取物大小: ~500 tokens（原文 8750 tokens 的 5.7%）         │
│                                                              │
│ Step 5: 原文存入 Scratchpad                                   │
│   3 个页面的原文全部存入 Scratchpad:                           │
│   scratchpad.write("odoo_pricing_page", 页面A全文)            │
│   scratchpad.write("odoo_vs_sap_blog", 页面B全文)             │
│   scratchpad.write("odoo_partner_id", 页面C全文)              │
│                                                              │
│ Step 6: 提取物进入上下文                                      │
│   3 个提取物合计 ~1500 tokens 进入上下文                       │
│   Agent 基于提取物生成竞品分析                                 │
│   如果需要更多细节 → 从 Scratchpad 回读特定段落               │
└─────────────────────────────────────────────────────────────┘
```

#### 搜索全文的生命周期管理

```
时间线:

T0: 用户要求调研 Odoo 定价
T1: web_search 返回 5 条结果（2K tokens 进入上下文）
T2: Agent 选择 3 个 URL 抓取
T3: web_fetch × 3 → 70K 字符全文
    → 全文存入 Scratchpad（不进入上下文）
    → 语义提取 → 1.5K tokens 提取物进入上下文
T4: Agent 生成 Odoo 定价分析（assistant 消息 ~500 tokens）
T5: 用户追问 "Odoo 的制造模块具体包含什么功能"
    → Agent 从 Scratchpad 回读 odoo_pricing_page
    → 搜索 "manufacturing module features"
    → 返回相关段落 ~800 tokens 临时进入上下文
T6: Agent 回答后，T5 的临时内容作为普通 tool_result 管理
T7: 用户切换话题 → Scratchpad 中的网页内容在会话结束时清理

上下文占用:
  T1: 2K（搜索结果）
  T3: 2K + 1.5K = 3.5K（搜索结果 + 提取物）
  T4: 3.5K + 0.5K = 4K（+ 分析结论）
  T5: 4K + 0.8K = 4.8K（+ 临时回读）
  
  对比不做提取: T3 时直接放入 70K 字符 = 17.5K tokens
  节省: 17.5K → 3.5K = 80% 的上下文空间
```

#### 提取质量保障

```
问题: 语义提取可能遗漏关键信息怎么办？

保障机制 1: 提取物中标注"未提及"
  → Agent 看到"实施费用: 未提及"时
  → 知道需要从其他来源获取这个信息
  → 而不是误以为"没有实施费用"

保障机制 2: 提取物附带原文引用位置
  {
    "implementation": "未提及（官网不公开实施费用）",
    "_source_section": "pricing_page#section-3"  // 原文位置标记
  }
  → Agent 如果怀疑提取有误，可以精确回读原文对应段落

保障机制 3: 关键数字交叉验证
  从 3 个不同来源提取的 Odoo 定价:
  - 官网: $24.90/user/month
  - 博客: $25/user/month
  - 合作伙伴: $24.90/user/month + 本地税
  → Agent 对比发现一致 → 可信度高
  → 如果不一致 → 标注差异，让用户判断

保障机制 4: 用户可以要求看原文
  用户: "让我看看 Odoo 官网原文怎么写的"
  → Agent 从 Scratchpad 读取原文
  → 完整返回给用户（此时原文临时进入上下文）
```

#### 闭环验证

```
业务闭环:
  ✅ 竞品定价的完整价格矩阵被提取（不是只有一个数字）
  ✅ 多来源交叉验证确保数据准确
  ✅ 用户可以追问细节，Agent 能回读原文回答
  ✅ 最终输出的竞品分析报告信息完整

技术闭环:
  ✅ 70K 字符全文 → 1.5K tokens 提取物进入上下文（节省 91%）
  ✅ 原文完整保存在 Scratchpad，不丢失
  ✅ 按需回读延迟 ~50ms
  ✅ 语义提取延迟 ~800ms/页（快速模型并行处理 3 页 ≈ 1s）
  ✅ 会话结束自动清理，不占持久存储
```

---

### D3: 百级商机列表处理

#### 业务维度

```
场景: 销售总监说"把本月所有商机拉出来，我要看完整 pipeline"

业务现实:
  - 20 个销售 × 平均 5 个活跃商机 = 100 个商机
  - 每个商机: 名称、客户、金额、阶段、负责人、预计关闭日期、
    最近活动日期、健康度、风险标签、竞品信息
  - 每条 ~200 字符 × 100 条 = 20K 字符 ≈ 5K tokens
  
  这还只是基本字段。如果总监要看:
  - 每个商机的最近一条活动摘要 → +100 × 100 字符 = +10K 字符
  - 每个商机的联系人覆盖情况 → +100 × 50 字符 = +5K 字符
  总计: 35K 字符 ≈ 8.75K tokens

为什么不能只看 Top 10:
  - 总监需要发现长尾问题: "为什么有 15 个商机超过 30 天没跟进"
  - 总监需要全局分布: "谈判阶段的商机是不是太少了"
  - 总监需要按人看: "Andi 手上是不是商机太多了"
  → 这些分析需要完整数据集，不是 Top 10 能回答的
```

#### 技术维度：分层处理 + 工作区暂存

```
┌─────────────────────────────────────────────────────────────┐
│ 百级列表的处理策略                                            │
│                                                              │
│ 核心思路: 完整数据存 Scratchpad，统计视图进上下文              │
│                                                              │
│ Step 1: 完整查询                                             │
│   query_data(entity="opportunity",                           │
│     filter="closeDate <= '2025-04-30' AND status='open'")    │
│   → 返回 100 条完整记录                                      │
│   → 35K 字符 ≈ 8.75K tokens                                 │
│                                                              │
│ Step 2: 全量数据存入 Scratchpad                               │
│   scratchpad.write(                                          │
│     key="pipeline_202504_full",                              │
│     content=完整100条记录的JSON,                              │
│     metadata={                                               │
│       "entity": "opportunity",                               │
│       "count": 100,                                          │
│       "query_time": "2025-04-17T10:30:00"                    │
│     }                                                        │
│   )                                                          │
│                                                              │
│ Step 3: 生成多维统计视图（在 Tool 内部计算，不靠 LLM）        │
│   {                                                          │
│     "total": 100, "total_amount": "$3.6M",                   │
│                                                              │
│     "by_stage": {                                            │
│       "prospecting":  {"count": 25, "amount": "$450K",       │
│                        "avg_age_days": 12},                  │
│       "qualification":{"count": 30, "amount": "$1.2M",       │
│                        "avg_age_days": 22},                  │
│       "proposal":     {"count": 20, "amount": "$890K",       │
│                        "avg_age_days": 18},                  │
│       "negotiation":  {"count": 18, "amount": "$720K",       │
│                        "avg_age_days": 15},                  │
│       "closing":      {"count": 7,  "amount": "$380K",       │
│                        "avg_age_days": 8}                    │
│     },                                                       │
│                                                              │
│     "by_owner": {                                            │
│       "Andi":  {"count": 8,  "amount": "$280K", "at_risk": 3},│
│       "Budi":  {"count": 12, "amount": "$520K", "at_risk": 1},│
│       "Citra": {"count": 10, "amount": "$380K", "at_risk": 2},│
│       ...                                                    │
│     },                                                       │
│                                                              │
│     "health": {                                              │
│       "healthy": 55, "at_risk": 30, "critical": 15          │
│     },                                                       │
│                                                              │
│     "alerts": [                                              │
│       "15个商机超过30天未跟进",                                │
│       "谈判阶段商机数环比减少40%",                             │
│       "Andi的8个商机中3个处于风险状态",                        │
│       "本月预计关闭$380K，目标$500K，缺口$120K"               │
│     ],                                                       │
│                                                              │
│     "top_risk": [                                            │
│       {"name":"PT ABC-ERP","amount":"$65K",                  │
│        "risk":"15天未联系+竞品威胁","owner":"Andi"},           │
│       {"name":"CV XYZ-CRM","amount":"$42K",                  │
│        "risk":"阶段停留25天","owner":"Budi"},                  │
│       ...前10个风险商机                                       │
│     ],                                                       │
│                                                              │
│     "scratchpad_key": "pipeline_202504_full"                 │
│     // ↑ 告诉 Agent 完整数据在哪里                            │
│   }                                                          │
│   统计视图大小: ~2K tokens                                    │
│                                                              │
│ Step 4: 统计视图进入上下文                                    │
│   Agent 基于统计视图回答总监的问题                             │
│   如果总监追问具体商机 → 从 Scratchpad 读取                   │
│                                                              │
│ Step 5: 按需下钻                                             │
│   总监: "Andi 的那 3 个风险商机具体是哪些"                    │
│   → Agent 从 Scratchpad 读取:                                │
│     scratchpad.query(                                        │
│       key="pipeline_202504_full",                            │
│       filter="owner='Andi' AND health='at_risk'"             │
│     )                                                        │
│   → 返回 3 条完整记录 ~600 tokens 临时进入上下文              │
│                                                              │
│   总监: "按金额从大到小排一下所有商机"                         │
│   → Agent 从 Scratchpad 读取全量数据                          │
│   → 但不是把 100 条全放进上下文                               │
│   → 而是在 Tool 内部排序后返回:                               │
│     "按金额排序的完整列表已生成，共100条。                     │
│      前10名: [列表]                                           │
│      如需查看完整列表或特定区间，请告诉我。"                   │
│   → 或者: 生成一个可下载的排序表格文件                        │
└─────────────────────────────────────────────────────────────┘
```

#### Scratchpad 的查询能力

```
Scratchpad 不是简单的 key-value 存储，它支持结构化查询:

scratchpad.query(key, filter, sort, limit, fields)

示例:
  # 查 Andi 的风险商机
  scratchpad.query(
    key="pipeline_202504_full",
    filter="owner='Andi' AND health='at_risk'",
    sort="amount DESC"
  )
  
  # 查超过 30 天未跟进的商机
  scratchpad.query(
    key="pipeline_202504_full",
    filter="last_activity_days > 30",
    sort="last_activity_days DESC"
  )
  
  # 查特定阶段的商机
  scratchpad.query(
    key="pipeline_202504_full",
    filter="stage='negotiation'",
    fields=["name", "amount", "owner", "close_date"]
  )

技术实现:
  Scratchpad 内部用 SQLite 或 DuckDB 存储结构化数据
  支持 SQL-like 的过滤、排序、聚合
  查询延迟 < 10ms（本地内存数据库）
```

#### 闭环验证

```
业务闭环:
  ✅ 总监能看到全局 pipeline 分布（通过统计视图）
  ✅ 总监能发现长尾问题（"15个商机超30天未跟进"在 alerts 中）
  ✅ 总监能按任意维度下钻（通过 Scratchpad 查询）
  ✅ 总监能看到完整排序列表（通过 Scratchpad 排序 + 分页返回）

技术闭环:
  ✅ 100 条完整数据 → 2K tokens 统计视图进入上下文（节省 77%）
  ✅ 完整数据在 Scratchpad 中可查询，不丢失
  ✅ 下钻查询延迟 < 10ms
  ✅ 统计计算在 Tool 内部完成，不消耗 LLM tokens
```

---

## 四、销售闭环八阶段的上下文压缩细化设计

> 本节将东南亚 CRM AI 销售闭环的八个阶段（获客→首次触达→需求挖掘→方案呈现→报价谈判→决策推进→签约回款→交接实施）逐一映射到上下文压缩架构，分析每个阶段的数据膨胀特征、压缩策略和跨阶段数据流转。

### 4.0 八阶段总览：数据膨胀与压缩难度矩阵

| 阶段 | Agent 角色 | 典型工具调用 | 单次会话数据量 | 膨胀主因 | 压缩难度 | 对应数据源 |
|------|-----------|------------|--------------|---------|---------|-----------|
| S1 获客 | 线索富化+评分 | company_info×1, web_search×2, query_data×1 | 8K-15K tokens | D2+D4 外部数据源多 | 低 | D2, D4 |
| S2 首次触达 | 破冰话术生成 | query_data×2, search_memories×1, web_search×1 | 5K-10K tokens | D1 客户备注大文本 | 低 | D1, D4 |
| S3 需求挖掘 | 实时对话辅助 | 实时转录流×N, query_data×3, save_memory×5 | 15K-40K tokens | D5 对话记录全文 | **高** | D1, D5 |
| S4 方案呈现 | 方案自动生成 | query_data×4, search_memories×2, web_search×2 | 12K-25K tokens | D4 跨实体关联 | 中 | D1, D2, D4 |
| S5 报价谈判 | 定价策略+谈判辅助 | analyze_data×3, query_data×2, financial_report×1 | 10K-20K tokens | D3 历史成交数据 | 中 | D3, D4 |
| S6 决策推进 | 决策地图+推进建议 | query_data×5, search_memories×3, web_search×1 | 15K-30K tokens | D4+D5 多人多轮 | **高** | D1, D4, D5 |
| S7 签约回款 | 合同生成+回款跟踪 | query_data×3, modify_data×2, web_search×1 | 8K-15K tokens | D1 合同条款大文本 | 低 | D1, D4 |
| S8 交接实施 | 交接档案生成 | query_data×6, search_memories×5 | 20K-50K tokens | D4+D5 全链路回溯 | **最高** | D1, D4, D5 |

**关键发现**：压缩难度最高的是 S3（需求挖掘）、S6（决策推进）和 S8（交接实施），因为它们涉及 D5（对话记录全文）和跨阶段数据回溯。

---

### 4.1 S1 获客阶段：AI 线索富化与评分

#### 业务场景

```
触发: 市场活动带来新线索，只有姓名+公司名+手机号
Agent 任务: 自动补全公司信息、联系人职位、技术栈、匹配度评分

工具调用链:
  Step 1: company_info("PT Sentosa Jaya") → 工商数据 ~1800 tokens
  Step 2: web_search("PT Sentosa Jaya 招聘 IT") → 技术栈推断 ~2100 tokens
  Step 3: web_search("PT Sentosa Jaya 融资 扩张") → 近期动态 ~2100 tokens
  Step 4: query_data(entity="account", filter={industry: "制造业"}) → ICP 匹配 ~1500 tokens
  Step 5: Agent 生成评分 + 分配建议 ~500 tokens

总计: ~8000 tokens，占 51K 的 15.7%
```

#### 压缩分析

```
结论: 不需要压缩

原因:
  - 5 次工具调用，总量 <10K tokens
  - 线索富化是"一次性任务"：Agent 查完数据、生成评分后，会话通常结束
  - 不存在多轮追问导致的上下文累积

特殊处理:
  - company_info 返回的工商数据中可能包含完整经营范围（~2000 字符）
  - 经营范围对评分有用（判断主营业务），但不需要全文进入上下文
  - 处理: company_info Tool 内部截取经营范围前 200 字符 + "..."
  - 完整经营范围存入 Scratchpad，按需回读

评分结果的持久化:
  - Agent 生成的评分和富化数据通过 modify_data 写回 CRM
  - 不依赖上下文保持 → 即使会话结束，数据已持久化
```

#### 跨阶段数据流转

```
获客阶段的输出是触达阶段的输入:

获客阶段 Agent 写入 CRM:
  account.industry = "制造业"
  account.employee_count = 200
  account.tech_stack = "Excel, 手工排程"
  account.lead_score = 87
  account.enrichment_notes = "正在招 IT Manager，可能要换系统"

触达阶段 Agent 读取 CRM:
  query_data(entity="account", record_id=xxx)
  → 获取上面写入的所有字段
  → 不需要从获客阶段的上下文中"继承"任何信息
  → 跨阶段数据通过 CRM 持久化传递，不通过上下文传递

这是销售闭环压缩设计的核心原则:
  ✅ 每个阶段的 Agent 输出写入 CRM
  ✅ 下一阶段的 Agent 从 CRM 读取
  ✅ 阶段间不共享上下文 → 不存在跨阶段的上下文膨胀
```

---

### 4.2 S2 首次触达：AI 辅助破冰

#### 业务场景

```
触发: 销售准备联系新线索，让 Agent 生成个性化触达方案
Agent 任务: 基于客户画像生成个性化话术、推荐触达渠道和时间

工具调用链:
  Step 1: query_data(entity="account", record_id=xxx) → 客户画像 ~800 tokens
  Step 2: query_data(entity="contact", filter={accountId: xxx}) → 联系人 ~600 tokens
  Step 3: search_memories("制造业 破冰 话术 成功案例") → 历史最佳实践 ~1200 tokens
  Step 4: web_search("PT Sentosa Jaya 最新动态") → 个性化素材 ~2100 tokens
  Step 5: Agent 生成个性化触达方案（含话术模板）~800 tokens

总计: ~5500 tokens，占 51K 的 10.8%
```

#### 压缩分析

```
结论: 不需要压缩

特殊场景 — 未响应自动跟进:
  销售发送消息后，Agent 需要跟踪响应并在 48h/3天/7天 后建议跟进。
  这不是一个连续会话，而是多次独立触发:

  T+0h:  Agent 生成首次触达话术 → 会话结束
  T+48h: 定时任务触发 → 新会话 → Agent 查询客户状态 → 生成跟进建议
  T+7d:  定时任务触发 → 新会话 → Agent 查询客户状态 → 建议换渠道

  每次都是独立会话，上下文从零开始，不存在累积问题。
  跟进策略的"记忆"通过 CRM 字段（last_contact_date, contact_attempts）传递。
```

#### 客户备注大文本的处理（D1 场景）

```
触达阶段可能遇到的 D1 问题:

query_data 返回的 account 记录中，notes 字段可能很大:
  account.notes = "
    2024/03: 初次接触，客户对 ERP 有兴趣但预算未确定...（1000字）
    2024/06: 参加了我们的线下活动，和 Pak Budi 聊了30分钟...（1500字）
    2024/09: 竞品 Odoo 在跟进，客户在比较...（800字）
    2025/01: 客户主动联系，说 Odoo 实施失败了...（1200字）
  "
  总计: ~4500 字符 ≈ 2250 tokens

处理策略（复用 D1 双通道方案）:
  通道 A: 语义提取 → 提取物进入上下文
    {
      "timeline": [
        {"date": "2024/03", "event": "初次接触，对ERP有兴趣，预算未定"},
        {"date": "2024/06", "event": "线下活动接触 Pak Budi"},
        {"date": "2024/09", "event": "竞品 Odoo 在跟进"},
        {"date": "2025/01", "event": "Odoo 实施失败，客户主动回来"}
      ],
      "current_status": "客户主动回来，竞品失败，窗口期",
      "key_person": "Pak Budi",
      "key_quote": "Odoo 用了半年没推起来"
    }
    提取物: ~400 tokens（原文的 18%）

  通道 B: 原文存 Scratchpad
    Agent 生成话术时如果需要引用具体细节 → 回读

  对触达话术生成的价值:
    提取物中的 "Odoo 实施失败" + "客户主动回来" 
    → Agent 生成话术: "Pak Budi，听说贵司之前的系统项目遇到了一些挑战，
      我们在制造业有很多成功案例，方便聊聊吗？"
    → 话术精准命中客户痛点，不需要看完 4500 字原文
```

---

### 4.3 S3 需求挖掘：AI 实时对话辅助（高压缩难度）

#### 业务场景

```
触发: 销售与客户进行视频会议/电话/WhatsApp 语音通话
Agent 任务: 实时转录 + 分析 + 侧边栏提示（BANT/MEDDIC 框架）

这是压缩难度最高的阶段之一，因为:
  1. 实时转录产生大量 D5 数据（对话记录全文）
  2. Agent 需要持续引用对话上下文做实时分析
  3. 一次通话可能持续 30-60 分钟 = 大量文本
```

#### 上下文膨胀分析

```
一次 45 分钟的客户通话:

语音转文字速率: ~150 字/分钟（中文/印尼语混合）
45 分钟 × 150 字 = 6750 字 ≈ 3375 tokens（纯对话文本）

但 Agent 不是只看文本，还需要:
  - 客户历史数据（query_data）: ~2000 tokens
  - BANT 框架模板: ~500 tokens
  - 已识别的信息点: 随对话增长
  - 实时提示建议: 每 5 分钟一次 × 9 次 = ~2700 tokens

总计: 3375 + 2000 + 500 + 2700 = ~8575 tokens（理想情况）

但实际问题更复杂:
  实时转录是流式的，每 30 秒推送一段文本
  45 分钟 = 90 段推送
  每段 ~75 字 ≈ 38 tokens
  如果每段都作为独立的 tool_result 进入上下文:
    90 × 38 = 3420 tokens（文本）+ 90 × 20（消息开销）= 5220 tokens
  
  加上 Agent 每 5 分钟的分析回复（9 次 × 300 tokens）= 2700 tokens
  
  总计: 5220 + 2000 + 500 + 2700 = ~10420 tokens = 20.4%
  
  看起来还好？但如果通话延长到 90 分钟（大客户深度沟通）:
  → 转录: ~10440 tokens
  → 分析回复: ~5400 tokens
  → 总计: ~18340 tokens = 36%
  → 接近需要压缩的区间
```

#### 压缩策略：滑动窗口 + 结构化沉淀

```
┌─────────────────────────────────────────────────────────────┐
│ 实时对话辅助的压缩架构                                        │
│                                                              │
│ 核心思路: 对话文本用滑动窗口，已识别信息用结构化沉淀           │
│                                                              │
│ Layer A: 滑动窗口（最近 10 分钟的原文）                       │
│                                                              │
│   上下文中只保留最近 10 分钟的转录原文（~1500 字 ≈ 750 tokens）│
│   更早的转录文本从上下文中移除                                 │
│   → 但不是丢弃，而是存入 Scratchpad                           │
│                                                              │
│   scratchpad.append(                                         │
│     key="call_transcript_20250417",                          │
│     content=older_transcript_segment,                        │
│     metadata={timestamp: "10:15:30", speaker: "customer"}    │
│   )                                                          │
│                                                              │
│ Layer B: 结构化沉淀（BANT/MEDDIC 实时更新）                   │
│                                                              │
│   Agent 每次分析后更新一个结构化对象（常驻上下文）:            │
│   {                                                          │
│     "bant": {                                                │
│       "budget": {                                            │
│         "status": "identified",                              │
│         "detail": "$40K-50K，年付优先",                       │
│         "source": "客户在 10:23 提到",                        │
│         "confidence": 0.8                                    │
│       },                                                     │
│       "authority": {                                         │
│         "status": "partially_identified",                    │
│         "detail": "Pak Budi 是推荐者，最终决策者未知",         │
│         "source": "从对话推断",                               │
│         "confidence": 0.6                                    │
│       },                                                     │
│       "need": {                                              │
│         "status": "identified",                              │
│         "detail": "生产排程自动化，库存实时可视",              │
│         "source": "客户在 10:08 和 10:15 详细描述",           │
│         "confidence": 0.9                                    │
│       },                                                     │
│       "timeline": {                                          │
│         "status": "identified",                              │
│         "detail": "希望3个月内上线核心模块",                   │
│         "source": "客户在 10:31 明确表示",                    │
│         "confidence": 0.9                                    │
│       }                                                      │
│     },                                                       │
│     "risk_signals": [                                        │
│       {"signal": "客户说'先看看'出现2次", "severity": "medium"},│
│       {"signal": "提到竞品Odoo在报价", "severity": "high"}    │
│     ],                                                       │
│     "action_items": [                                        │
│       {"who": "us", "what": "3天内出POC方案", "deadline": "4/20"},│
│       {"who": "customer", "what": "提供现有排程数据"}         │
│     ],                                                       │
│     "unanswered_questions": [                                │
│       "决策流程和审批链",                                     │
│       "是否有IT团队支持实施"                                  │
│     ]                                                        │
│   }                                                          │
│   结构化沉淀大小: ~800 tokens（固定，不随通话时长增长）        │
│                                                              │
│ Layer C: 实时提示生成                                         │
│                                                              │
│   Agent 基于 Layer A（最近原文）+ Layer B（结构化沉淀）生成提示│
│   提示内容:                                                   │
│   "💡 建议下一个问题:                                         │
│    客户提到预算约$40K-50K，但决策人还不清楚。                  │
│    建议问: 'Pak Budi，这个项目最终是谁来拍板？                │
│    通常贵司采购这类系统需要走什么流程？'"                      │
│                                                              │
│   提示生成只需要:                                             │
│   - 最近 10 分钟原文（750 tokens）→ 理解当前话题              │
│   - 结构化沉淀（800 tokens）→ 知道还缺什么信息               │
│   - 客户历史（2000 tokens）→ 背景参考                        │
│   总计: ~3550 tokens，远小于完整转录                           │
└─────────────────────────────────────────────────────────────┘
```

#### 通话结束后的处理

```
通话结束时，Agent 执行"通话后自动输出":

1. 从 Scratchpad 读取完整转录:
   full_transcript = scratchpad.read("call_transcript_20250417")
   → 完整 45 分钟转录 ~6750 字

2. 基于完整转录 + 结构化沉淀，生成:
   a. 会议摘要（按 BANT/MEDDIC 框架）→ save_memory
   b. 客户需求清单 → modify_data(entity="opportunity", fields={requirement_desc: ...})
   c. 行动项 → modify_data(entity="activity", ...)
   d. 商机阶段建议 → modify_data(entity="opportunity", fields={stage: ...})
   e. 风险标记 → modify_data(entity="opportunity", fields={risk_tags: ...})

3. 所有输出写入 CRM，不依赖上下文保持

4. 完整转录存入长期记忆（如果 memory-plugin 启用）:
   save_memory(content=full_transcript, tags=["call", "PT Sentosa Jaya", "2025-04-17"])

上下文占用（通话后生成阶段）:
  结构化沉淀: 800 tokens
  完整转录临时读入: 3375 tokens（从 Scratchpad）
  生成输出: ~2000 tokens
  总计: ~6175 tokens = 12.1%
  → 不需要压缩
```

#### 闭环验证

```
业务闭环:
  ✅ 销售在通话中实时看到 BANT 覆盖情况和建议问题
  ✅ 通话结束后自动生成结构化摘要，销售确认即可
  ✅ 所有承诺和行动项被记录，不会遗漏
  ✅ 完整转录可追溯（存在 memory 中）

技术闭环:
  ✅ 45 分钟通话的上下文占用控制在 ~3550 tokens（滑动窗口+结构化沉淀）
  ✅ 90 分钟通话也不会膨胀（窗口大小固定）
  ✅ 通话后生成阶段临时读入完整转录，生成完毕后释放
  ✅ 实时提示延迟 < 2s（只处理最近 10 分钟 + 结构化沉淀）
```

---

### D6: 元数据完整定义处理

#### 业务维度

```
场景: Agent 需要帮销售创建一条商机记录

业务现实:
  CRM 的 opportunity 实体有 35 个字段:
  - 15 个系统字段（名称、阶段、金额、概率、关闭日期...）
  - 10 个自定义字段（行业分类、产品线、竞品、渠道来源...）
  - 5 个关联字段（客户、联系人、负责人、协同人、上级商机）
  - 5 个规则字段（必填校验、值域校验、级联规则、默认值...）

  完整 schema 定义: ~15K 字符 ≈ 3750 tokens

为什么不能砍:
  - Agent 不知道"阶段"字段的选项值 → 传了一个不存在的阶段 → API 报错
  - Agent 不知道"金额"字段是必填的 → 创建时漏了 → API 报错
  - Agent 不知道"行业分类"和"产品线"有级联关系 → 选了不匹配的组合 → 数据错误
  - Agent 不知道"关闭日期"不能早于今天 → 传了过去的日期 → 校验失败

  每一个字段的类型、选项值、校验规则都可能影响 Agent 的操作正确性。
```

#### 技术维度：Schema 缓存 + 按需加载

```
核心思路: Schema 是"半静态"数据——在一个会话中几乎不会变化。
因此可以用缓存策略，而不是每次都完整加载。

┌─────────────────────────────────────────────────────────────┐
│ Schema 三级缓存架构                                          │
│                                                              │
│ Level 1: 骨架层（始终在上下文中，~800 tokens/实体）           │
│                                                              │
│   Agent 首次查询某实体 schema 时，骨架层自动注入上下文:        │
│   {                                                          │
│     "entity": "opportunity",                                 │
│     "label": "商机",                                         │
│     "fields": [                                              │
│       {"key":"name","label":"商机名称","type":"VARCHAR",      │
│        "required":true},                                     │
│       {"key":"stage","label":"阶段","type":"PICK_LIST",      │
│        "required":true,"options_count":7},                   │
│       {"key":"amount","label":"金额","type":"DECIMAL",       │
│        "required":true},                                     │
│       {"key":"close_date","label":"预计关闭","type":"DATE",  │
│        "required":true},                                     │
│       {"key":"account_id","label":"客户","type":"LOOKUP",    │
│        "target":"account","required":true},                  │
│       ...全部35个字段的 key+label+type+required              │
│     ],                                                       │
│     "links": [                                               │
│       {"target":"contact","type":"MANY_TO_MANY"},            │
│       {"target":"activity","type":"ONE_TO_MANY"}             │
│     ]                                                        │
│   }                                                          │
│                                                              │
│   骨架层告诉 Agent:                                          │
│   - 有哪些字段、什么类型、是否必填                            │
│   - 有哪些关联实体                                           │
│   - 但不包含: 选项值列表、校验规则详情、级联规则              │
│                                                              │
│ Level 2: 详情层（Scratchpad 缓存，按需读取）                  │
│                                                              │
│   完整 schema 存入 Scratchpad:                                │
│   scratchpad.write("schema_opportunity", 完整15K定义)         │
│                                                              │
│   当 Agent 需要某个字段的详情时:                               │
│   scratchpad.query(                                          │
│     key="schema_opportunity",                                │
│     filter="field_key='stage'"                               │
│   )                                                          │
│   → 返回 stage 字段的完整定义:                                │
│   {                                                          │
│     "key": "stage",                                          │
│     "type": "PICK_LIST",                                     │
│     "options": [                                             │
│       {"value":"prospecting","label":"初步接触","probability":10},│
│       {"value":"qualification","label":"需求确认","probability":20},│
│       {"value":"proposal","label":"方案评估","probability":40},│
│       {"value":"negotiation","label":"商务谈判","probability":60},│
│       {"value":"closing","label":"即将签约","probability":80},│
│       {"value":"won","label":"赢单","probability":100},      │
│       {"value":"lost","label":"输单","probability":0}        │
│     ],                                                       │
│     "validation": {"not_backward": true},                    │
│     "cascade": {"triggers_probability_update": true}         │
│   }                                                          │
│   ~300 tokens，只在需要时临时进入上下文                        │
│                                                              │
│ Level 3: 会话级缓存（跨轮复用）                               │
│                                                              │
│   同一个会话中第二次查询同一实体的 schema:                     │
│   → 直接从 Scratchpad 读取，不再调用后端 API                  │
│   → 延迟从 ~200ms（API 调用）降到 < 10ms（本地读取）         │
│                                                              │
│   缓存失效条件:                                               │
│   - 会话结束                                                 │
│   - 用户执行了 modify_schema 操作（schema 可能变了）          │
│   - 缓存时间超过 30 分钟（防止其他用户修改了 schema）         │
└─────────────────────────────────────────────────────────────┘
```

#### Agent 操作时的 Schema 使用流程

```
用户: "帮我创建一个商机，客户是 PT Sentosa Jaya，金额 $45K"

Agent 的处理流程:

Step 1: 检查上下文中是否有 opportunity 的骨架层
  → 有 → 知道需要哪些必填字段
  → 没有 → 先查询 schema，骨架层进入上下文

Step 2: 从骨架层判断缺少哪些必填字段
  必填: name ✅(可以从客户名生成), stage ❌, amount ✅($45K), 
        close_date ❌, account_id ✅(PT Sentosa Jaya)
  缺少: stage, close_date

Step 3: 需要知道 stage 的选项值 → 从 Scratchpad 读取详情
  → 获取 7 个阶段选项
  → 新商机默认用 "prospecting"

Step 4: close_date 需要推断 → 问用户或用默认值
  Agent: "预计什么时候关闭？默认设为 3 个月后（7月17日）"

Step 5: 构建完整的创建请求
  modify_data(entity="opportunity", action="create", data={
    "name": "PT Sentosa Jaya - ERP",
    "stage": "prospecting",
    "amount": 45000,
    "close_date": "2025-07-17",
    "account_id": "acc_xxx"
  })

整个过程中:
  - 骨架层（800 tokens）始终在上下文中
  - stage 详情（300 tokens）临时读入，用完后作为普通 tool_result 管理
  - 完整 schema（3750 tokens）始终在 Scratchpad 中，不占上下文
```

#### 闭环验证

```
业务闭环:
  ✅ Agent 知道所有字段的类型和必填性（骨架层）
  ✅ Agent 能获取选项值和校验规则（详情层按需读取）
  ✅ 创建/修改操作不会因为字段错误而失败
  ✅ 级联规则被正确处理

技术闭环:
  ✅ 15K 完整 schema → 800 tokens 骨架层常驻上下文（节省 79%）
  ✅ 详情按需读取，用完释放
  ✅ 会话级缓存避免重复 API 调用
  ✅ schema 变更时缓存自动失效
```

---

## 四、Scratchpad 技术架构

Scratchpad 是本方案的核心基础设施，所有大数据问题的解决都依赖它。

### 4.1 定位

```
Scratchpad = Agent 的"工作台"

类比: 人在办公桌上工作时——
  - 眼前的屏幕 = 上下文窗口（能同时看到的信息有限）
  - 桌上的文件夹 = Scratchpad（随手可以翻阅，但不是时刻盯着）
  - 文件柜 = 持久存储/Memory（需要起身去拿，但长期保存）

Scratchpad 的特征:
  - 会话级生命周期（会话结束自动清理）
  - 低延迟读写（< 10ms）
  - 支持结构化查询（filter/sort/aggregate）
  - 支持语义搜索（对非结构化文本）
  - 容量: 单会话最大 10MB（足够存几十个网页全文）
```

### 4.2 数据模型

```python
class ScratchpadEntry:
    key: str                    # 唯一标识
    content_type: str           # "json" | "text" | "table"
    content: Any                # 实际内容
    metadata: dict              # 来源、大小、创建时间等
    ttl: int                    # 过期时间（秒），0=会话结束时清理
    
class Scratchpad:
    """Agent 的会话级工作区"""
    
    async def write(self, key: str, content: Any, 
                    content_type: str = "auto", ttl: int = 0) -> None:
        """写入数据"""
    
    async def read(self, key: str) -> Any:
        """读取完整数据"""
    
    async def query(self, key: str, filter: str = None, 
                    sort: str = None, limit: int = None,
                    fields: list = None) -> Any:
        """结构化查询（仅对 json/table 类型）"""
    
    async def search(self, key: str, query: str, 
                     top_k: int = 3) -> list:
        """语义搜索（对 text 类型，返回最相关的段落）"""
    
    async def aggregate(self, key: str, 
                        group_by: str, metrics: list) -> dict:
        """聚合计算（仅对 json/table 类型）"""
    
    async def delete(self, key: str) -> None:
        """删除数据"""
    
    async def list_keys(self) -> list:
        """列出所有 key 及其 metadata"""
```

### 4.3 存储实现

```
结构化数据（JSON/Table）:
  → 内存中的 DuckDB 实例
  → 支持 SQL 查询、聚合、排序
  → 单会话独立实例，会话结束销毁

非结构化文本（网页全文、大文本字段）:
  → 内存中的文本块 + 向量索引
  → 支持语义搜索（embedding + cosine similarity）
  → 分段存储（按段落/章节切分），支持段落级检索

容量管理:
  → 单会话上限 10MB
  → 超过上限时按 LRU 淘汰最早写入的数据
  → 淘汰前检查是否有 Agent 正在引用（通过 key 的最近访问时间）
```

### 4.4 Scratchpad 作为 Agent Tool 暴露

```
Agent 可以直接使用 Scratchpad 作为工具:

工具定义:
  scratchpad_write(key, content)     — 写入数据
  scratchpad_read(key)               — 读取完整数据
  scratchpad_query(key, filter, ...) — 结构化查询
  scratchpad_search(key, query)      — 语义搜索

但更常见的用法是: Tool 内部自动使用 Scratchpad

  query_data 返回大量记录时:
    → Tool 内部自动将全量数据写入 Scratchpad
    → 返回给 Agent 的是统计视图 + scratchpad_key
    → Agent 需要下钻时调用 scratchpad_query

  web_fetch 抓取网页时:
    → Tool 内部自动将全文写入 Scratchpad
    → 同时调用语义提取器生成提取物
    → 返回给 Agent 的是提取物 + scratchpad_key
    → Agent 需要原文时调用 scratchpad_read 或 scratchpad_search
```

---

## 五、上下文生命周期管理（Layer 2）

Scratchpad 解决了"大数据不进入上下文"的问题。但已经在上下文中的数据仍然需要管理。

### 5.1 CRM 场景的 Microcompact 规则

```
保护规则（不被清理）:
  1. Schema 骨架层 — 当前会话涉及的实体骨架（最多 3 个实体）
  2. Context Anchor — Agent 生成的关键业务摘要
     - customer_profile: 客户画像摘要
     - pipeline_overview: Pipeline 统计视图
     - competitive_intel: 竞品结构化数据
     - coaching_summary: Coaching 迭代摘要
  3. 最近 N 个 tool_result（默认 5，报表分析模式下 8）
  4. 错误结果 — is_error=true 的操作结果

清理规则:
  超出保护范围的 tool_result → 替换为一行摘要:
  "[已压缩: query_data(opportunity) 返回 3 条记录, scratchpad_key=pipeline_full]"
  
  关键: 清理摘要中保留 scratchpad_key
  → Agent 后续如果需要这些数据，可以从 Scratchpad 重新读取
  → 这是和 Hermes 的核心区别: Hermes 清理后数据就丢了，我们清理后数据还在 Scratchpad 中
```

### 5.2 Context Anchor 机制

```
Anchor 是 Agent 生成的高密度业务摘要，跨轮保护:

创建时机:
  - Agent 完成客户 360 视图查询后 → 生成 customer_profile anchor
  - Agent 完成 pipeline 分析后 → 生成 pipeline_overview anchor
  - Agent 从搜索中提取竞品数据后 → 生成 competitive_intel anchor
  - Coaching 对话超过 8 轮后 → 生成 coaching_summary anchor

Anchor 的大小控制:
  每个 anchor 上限 500 tokens
  同类型 anchor 最多保留 2 个（当前 + 上一个）
  所有 anchor 合计上限 2000 tokens

Anchor 的降级:
  当用户明确切换话题时（如从客户 A 切换到客户 B）:
  → 客户 A 的 anchor 降级为"可清理"
  → 下次 Microcompact 时被清理
  → 但 Scratchpad 中的原始数据仍然存在
```

---

## 六、迭代摘要层（Layer 3）— 借鉴 Hermes

### 6.1 触发条件

```
当 Microcompact 后上下文仍然 > 70% 时，触发 LLM 摘要。

CRM 场景中这通常发生在:
  - 20+ 轮的 Coaching 对话
  - 连续分析 5+ 个商机的深度会话
  - 跨多个客户的对比分析会话
```

### 6.2 CRM 专用摘要模板

```
根据会话类型自动选择模板:

═══ 客户分析会话 ═══
## 客户
[客户名称和基本信息]
## 商机状态
[活跃商机的阶段、金额、风险——保留精确数字]
## 关键发现
[从数据中发现的洞察]
## 已执行操作
[已经在 CRM 中做的修改]
## 待办
[下一步行动]
## 关键数据
[不能丢失的精确数字、日期、人名]

═══ Pipeline 分析会话 ═══
## 分析范围
[时间范围、区域、团队]
## 数据发现
[按维度列出发现——每个发现必须有精确数字]
## 归因分析
[问题的根因分析]
## 已讨论结论
[管理层确认的决策]
## 待深入方向
[还没分析完的维度]

═══ Coaching 会话 ═══
## 目标
[coaching 的核心目标]
## 数据发现
[销售的业绩数据、对比数据——精确数字]
## 策略决策
[已确认的改进策略]
## 行动项
[已创建的任务和提醒]
## 待确认
[未决事项]
```

### 6.3 迭代更新（借鉴 Hermes 核心机制）

```
第一次摘要: 从零生成
第二次摘要: 在第一次基础上更新

Prompt:
"以下是上一次的会话摘要，以及之后新增的对话。
 请更新摘要:
 - 已完成的事项从'待办'移到'已执行'
 - 新发现的数据追加到'数据发现'
 - 新确认的决策追加到'策略决策'
 - 所有数字必须精确保留
 
 上一次摘要:
 {previous_summary}
 
 新增对话:
 {new_turns}"

关键: 迭代更新避免了信息随压缩次数增加而衰减。
Hermes 的实验表明，迭代摘要在 5 次压缩后信息保留率仍 > 85%，
而从零摘要在第 3 次压缩后就降到 < 60%。
```

---

## 七、完整架构总图

```
用户消息进入
    │
    ▼
┌─────────────────────────────────────────────────────────┐
│ Tool 执行层                                              │
│                                                          │
│ Tool 返回数据时自动判断:                                  │
│ ├→ 小数据（< 3K tokens）→ 直接进入上下文                 │
│ ├→ 大文本字段（> 1000 字符）→ Layer 1 语义提取           │
│ ├→ 大列表（> 20 条记录）→ 全量存 Scratchpad + 统计视图   │
│ ├→ 网页全文（web_fetch）→ 全文存 Scratchpad + 语义提取   │
│ └→ Schema → 骨架层进上下文 + 完整定义存 Scratchpad       │
└──────────────────────┬──────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────┐
│ Layer 0: Scratchpad（外部存储）                           │
│                                                          │
│ 存储: 大文本原文、网页全文、完整列表、完整 Schema          │
│ 能力: 结构化查询、语义搜索、聚合计算                      │
│ 生命周期: 会话级，自动清理                                │
│ 容量: 10MB/会话                                          │
└──────────────────────┬──────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────┐
│ Layer 1: 语义提取（进入上下文的是提取物）                  │
│                                                          │
│ 大文本字段 → 结构化提取（需求/承诺/竞品/信号）            │
│ 网页全文 → 目标导向提取（定价表/功能对比/案例数据）       │
│ 大列表 → 统计视图（分布/趋势/异常/Top N）                │
│ 对话记录 → 滑动窗口 + 结构化沉淀                         │
│                                                          │
│ 提取物大小: 原文的 5-20%                                  │
│ 提取延迟: 500-1000ms（快速模型）                          │
└──────────────────────┬──────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────┐
│ Layer 2: 上下文管理（Microcompact）                       │
│                                                          │
│ 保护: Schema骨架 / Context Anchor / 最近N个结果 / 错误    │
│ 清理: 旧 tool_result → 一行摘要（保留 scratchpad_key）   │
│ 触发: ratio > 50% 时执行                                 │
│ 延迟: < 5ms（纯规则，无 LLM 调用）                       │
└──────────────────────┬──────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────┐
│ Layer 3: 迭代摘要（Hermes 机制）                          │
│                                                          │
│ 触发: Microcompact 后仍 > 70%                            │
│ 方式: 按会话类型选择摘要模板，迭代更新                    │
│ 延迟: 2-4s（LLM 调用，异步执行不阻塞）                   │
│ 信息保留: > 85%（迭代更新 vs 从零摘要的 60%）            │
└─────────────────────────────────────────────────────────┘
```

### 各层的职责边界

| 层 | 解决什么问题 | 延迟 | 信息损失 |
|----|------------|------|---------|
| Scratchpad | 大数据不进入上下文 | < 10ms | 零（原文完整保存） |
| 语义提取 | 大数据的精华进入上下文 | 500-1000ms | 低（结构化提取，关键信息保留） |
| Microcompact | 已在上下文中的旧数据清理 | < 5ms | 低（assistant 消化结果保留，原文在 Scratchpad） |
| 迭代摘要 | 超长对话的信息浓缩 | 2-4s（异步） | 中（迭代更新保留 85%+） |

### 与 Hermes 原始设计的对比

| 维度 | Hermes | 本方案 | 差异原因 |
|------|--------|--------|---------|
| 外部存储 | 无 | Scratchpad | CRM 数据量大且需要按需回读 |
| 语义提取 | 无 | 按字段类型/数据源提取 | CRM 大文本字段和网页全文是常态 |
| 数据清理后可恢复 | 否（清理即丢失） | 是（Scratchpad 中有原文） | CRM 用户经常追问历史细节 |
| 摘要模板 | 通用 7 段 | 按会话类型 4 种模板 | CRM 场景差异大 |
| 迭代摘要 | 有 | 有（直接借鉴） | 核心机制一致 |
| 边界对齐 | tool_call/result 成对 | 同上 | 核心机制一致 |
| 孤立对清理 | 有 | 有（直接借鉴） | 核心机制一致 |

---

> 本方案的核心创新是引入 Scratchpad + 语义提取的双层架构，将 Hermes 的"有损压缩"升级为"无损存储 + 有损视图"。大数据不是被丢弃，而是被存储在 Scratchpad 中，上下文中只放语义提取物。Agent 随时可以回读原文，用户追问细节时不会遇到"信息已丢失"的问题。这是 CRM 场景对通用 Agent 压缩机制的核心改进。
