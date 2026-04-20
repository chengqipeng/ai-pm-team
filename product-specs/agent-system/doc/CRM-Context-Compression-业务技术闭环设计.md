# CRM Agent 上下文压缩 — 业务与技术闭环设计

> 面向东南亚 toB CRM 场景。不回避大数据问题，正面解决"数据就是这么大"的技术挑战。
> 每个问题从业务维度（为什么需要完整数据）和技术维度（如何处理完整数据）两个方向闭环。

---

## 一、核心矛盾与架构选择

### 1.1 CRM 场景中不可回避的六类大数据源

| 编号 | 数据源 | 业务现实举例 | 真实数据量 | 为什么不能砍 |
|------|--------|-------------|-----------|-------------|
| D1 | 大文本字段 | 商机"需求描述"、活动"会议纪要"、客户"备注" | 单字段 2K-20K 字符 | 销售写了详细客户背景，砍掉等于丢核心业务信息 |
| D2 | 搜索全文 | 竞品定价页、案例详情页、市场分析报告 | 单页 10K-80K 字符 | snippet 只有 200 字，拿不到定价表和功能对比矩阵 |
| D3 | 百级商机列表 | 总监要看全部 pipeline | 100-500 条，15K-75K 字符 | 管理层需要全局视角，Top10 看不到长尾问题 |
| D4 | 跨实体完整关联 | 客户的商机+联系人+活动+报价+合同 | 4-8 实体，20K-120K 字符 | 拜访准备需要完整画像，缺任何维度都不完整 |
| D5 | 对话记录全文 | 一个月的 WhatsApp 聊天含语音转文字 | 50-200 条，5K-100K 字符 | 经理要复盘具体沟通细节，摘要无法替代原文语气和承诺 |
| D6 | 元数据完整定义 | 实体 30-50 个字段的完整 schema | 单实体 5K-20K 字符 | Agent 构建查询/修改时需要字段类型、选项值、校验规则 |

### 1.2 核心矛盾

```
业务需求：完整数据 → LLM 才能做出准确判断
技术限制：上下文窗口有限（64K-200K tokens）→ 放不下所有数据
用户体验：压缩如果靠 LLM 摘要 → 3-5 秒额外延迟

三者不可能同时满足。解法不是"砍数据"，而是"分层存储 + 按需加载"。
```

### 1.3 架构选择：四层处理模型

```
┌─────────────────────────────────────────┐
│ Layer 0: Scratchpad（外部工作区）         │
│ 完整数据存在这里，不占上下文空间          │
│ Agent 可以随时按需查询/回读              │
│ 技术: 内存 SQLite / DuckDB              │
└────────────────┬────────────────────────┘
                 │ 语义提取 / 统计聚合
┌────────────────▼────────────────────────┐
│ Layer 1: 语义提取层                      │
│ 大数据进入上下文前先做结构化提取          │
│ 提取物进上下文，原文留在 Scratchpad      │
│ 技术: 专用提取 Prompt + 快速模型         │
└────────────────┬────────────────────────┘
                 │ 提取物 + 统计视图
┌────────────────▼────────────────────────┐
│ Layer 2: 上下文生命周期管理              │
│ 已在上下文中的数据的保护/压缩/清理       │
│ 技术: Microcompact + Context Anchor     │
└────────────────┬────────────────────────┘
                 │ 长对话触发
┌────────────────▼────────────────────────┐
│ Layer 3: 迭代摘要                        │
│ 20+ 轮长对话的渐进式信息浓缩             │
│ 技术: Hermes 迭代摘要 + CRM 专用模板    │
└─────────────────────────────────────────┘
```

**关键创新：Layer 0 和 Layer 1 是 CRM 场景必须新增的。** Hermes 原始设计只有 Layer 2 和 Layer 3，因为编码场景的数据量相对可控（文件内容可以按行读取）。CRM 场景的数据量级和结构化程度完全不同。

---

## 二、Scratchpad 技术设计（Layer 0）

### 2.1 为什么需要 Scratchpad

```
传统方案的问题：

方案 A: 大数据直接进上下文
  → 100 个商机 = 8.75K tokens，占上下文 17%
  → 加上其他数据，2-3 次查询就超 50%
  → 不可行

方案 B: 截断/过滤数据
  → 只返回 Top 10 商机 → 总监看不到全局
  → 只返回摘要字段 → 丢失需求描述等关键信息
  → 业务上不可接受

方案 C: Scratchpad（本方案）
  → 完整数据存在 Agent 可访问的外部工作区
  → 上下文中只放提取物/统计视图（体积小 80-95%）
  → Agent 需要细节时从 Scratchpad 按需读取
  → 业务完整性和技术可行性兼顾
```

### 2.2 Scratchpad 的能力定义

```python
class Scratchpad:
    """Agent 的外部工作区，存储不需要常驻上下文的完整数据"""
    
    async def write(self, key: str, content: Any, 
                    content_type: str = "text",  # text / json / table
                    metadata: dict = None,
                    ttl: str = "session") -> str:
        """
        写入数据
        - key: 唯一标识，如 "pipeline_202504_full"
        - content: 完整数据（文本、JSON、表格）
        - content_type: 数据类型，决定后续查询能力
          - "text": 支持语义搜索
          - "json": 支持字段过滤
          - "table": 支持 SQL-like 查询
        - ttl: 生命周期
          - "session": 会话结束清理
          - "1h" / "24h": 定时清理
        返回: 写入确认 + 数据摘要统计
        """
    
    async def read(self, key: str, 
                   max_chars: int = None) -> str:
        """读取完整内容或前 N 个字符"""
    
    async def search(self, key: str, query: str,
                     max_results: int = 3) -> list:
        """
        语义搜索（适用于 text 类型）
        在存储的文本中搜索与 query 语义相关的段落
        返回最相关的 N 个段落
        """
    
    async def query(self, key: str,
                    filter: str = None,
                    sort: str = None,
                    limit: int = None,
                    fields: list = None) -> list:
        """
        结构化查询（适用于 json/table 类型）
        支持过滤、排序、字段选择
        示例: query("pipeline_full", filter="owner='Andi' AND health='at_risk'")
        """
    
    async def aggregate(self, key: str,
                        group_by: str,
                        metrics: list) -> dict:
        """
        聚合统计（适用于 json/table 类型）
        示例: aggregate("pipeline_full", group_by="stage", 
                        metrics=["count", "sum(amount)"])
        """
    
    async def list_keys(self) -> list:
        """列出当前 Scratchpad 中的所有 key 及其元数据"""
    
    async def delete(self, key: str) -> bool:
        """手动删除"""
```

### 2.3 Scratchpad 的技术实现

```
存储引擎: 内存 SQLite（单会话隔离）

为什么选 SQLite:
  - 零部署成本（Python 内置）
  - 支持 SQL 查询（过滤、排序、聚合、JOIN）
  - 内存模式延迟 < 10ms
  - 单会话数据量通常 < 10MB，内存完全够

数据组织:
  每个 key 对应一张表
  text 类型 → 按段落分行存储，附加向量索引（用于语义搜索）
  json 类型 → 按记录分行存储，JSON 字段自动展开为列
  table 类型 → 直接建表

语义搜索实现:
  text 类型的数据写入时:
  1. 按段落切分（\n\n 或 句号分隔）
  2. 每个段落计算 embedding（用轻量模型，如 all-MiniLM-L6-v2）
  3. 存入 SQLite 的向量扩展（sqlite-vss）
  4. search() 时计算 query embedding → 余弦相似度 → Top N

生命周期:
  会话开始 → 创建内存 SQLite 实例
  会话中 → Agent 通过工具读写
  会话结束 → 销毁实例，内存释放
  异常断开 → 无持久化，自动清理
```

---

## 三、逐问题详细设计

### D1: 大文本字段 — 语义提取 + 原文暂存

#### 业务维度：为什么需要完整大文本

```
东南亚 CRM 场景中的大文本字段:

1. 商机"需求描述"（平均 5000-8000 字）
   印尼销售 Andi 花了 2 小时写的客户需求分析:
   - 客户当前业务流程（用 Excel 管排程，每月出错 3-5 次）
   - 组织架构（IT 部 2 人，工厂 50 人，CFO 管预算）
   - 竞品情况（Odoo 免费版用了半年没推起来）
   - 预算信号（老板说"能解决排程问题预算不是问题"）
   
   → Agent 分析商机时，需要理解"为什么客户愿意花 $45K"
   → 答案在需求描述的细节里，不在摘要里

2. 活动"会议纪要"（平均 3000-10000 字）
   一次 2 小时客户会议的完整记录:
   - 客户说"我们之前被 Odoo 的实施商坑过"（竞品情报）
   - 客户说"如果 5 月前能上线，Q3 预算可以批"（时间线）
   - 我方承诺"核心模块 8 周交付"（销售承诺）
   
   → 经理复盘时需要看到具体的原话和承诺
   → "客户对竞品有顾虑"这种摘要不够，要知道具体顾虑什么

3. 客户"备注"（累积 3000-6000 字）
   多个销售在不同时期追加:
   - 2024/03: 初次接触，客户在用 Odoo 但不满意
   - 2024/06: 报价 $50K 被拒，客户说太贵
   - 2025/01: 客户主动联系，Odoo 实施失败想换
   - 2025/03: 重新报价 $45K，客户在内部走审批
   
   → Agent 制定策略时需要知道完整历史
   → 不知道"2024 年报价被拒"就无法理解"为什么这次降了 $5K"
```

#### 技术维度：双通道处理流程

```
当 query_data 返回的记录中包含大文本字段（>1000 字符）时:

┌──────────────────────────────────────────────────────────┐
│ Step 1: 检测大文本字段                                     │
│                                                           │
│ Tool 返回的 opportunity 记录:                              │
│ {                                                         │
│   "name": "PT Sentosa - ERP",                             │
│   "amount": 45000,                                        │
│   "stage": "proposal",                                    │
│   "owner": "Andi",                                        │
│   "requirement_desc": "（8000 字的需求描述）",  ← 大文本    │
│   "close_date": "2025-05-15",                             │
│   ...其他 20 个普通字段                                    │
│ }                                                         │
│                                                           │
│ 检测: requirement_desc 长度 8000 > 阈值 1000 → 触发提取    │
└──────────────────┬───────────────────────────────────────┘
                   │
┌──────────────────▼───────────────────────────────────────┐
│ Step 2: 原文存入 Scratchpad                                │
│                                                           │
│ scratchpad.write(                                         │
│   key="opp_sentosa_requirement",                          │
│   content="（8000 字原文）",                               │
│   content_type="text"  // 支持后续语义搜索                  │
│ )                                                         │
└──────────────────┬───────────────────────────────────────┘
                   │
┌──────────────────▼───────────────────────────────────────┐
│ Step 3: 语义提取（用快速模型，~500ms）                      │
│                                                           │
│ 提取 Prompt（按字段类型选择）:                              │
│ "从以下商机需求描述中提取结构化信息。                        │
│  必须保留所有精确数字和关键原话。                            │
│  - core_needs: 核心需求                                    │
│  - pain_points: 痛点（含量化数据）                          │
│  - decision_chain: 决策链（角色+姓名）                      │
│  - budget_signal: 预算信号（原话）                          │
│  - timeline: 时间线                                        │
│  - competitors: 竞品信息（原话）                            │
│  - key_quotes: 最关键的 3 句原话"                           │
│                                                           │
│ 提取结果:                                                  │
│ {                                                         │
│   "core_needs": ["生产排程自动化", "库存实时可视化"],        │
│   "pain_points": ["Excel排程每月出错3-5次",                 │
│                   "库存盘点靠人工，每次耗时2天"],            │
│   "decision_chain": {                                     │
│     "champion": "Pak Budi (IT Manager)",                  │
│     "economic_buyer": "Ibu Sari (CFO)",                   │
│     "end_users": "工厂主管Pak Eko + 50人"                  │
│   },                                                      │
│   "budget_signal": "老板原话:'能解决排程问题预算不是问题'",  │
│   "timeline": "希望5月前上线核心模块（Q3预算窗口）",        │
│   "competitors": {                                        │
│     "Odoo": "免费版用了半年没推起来，实施商能力不足",       │
│     "SAP": "评估过，太贵放弃"                              │
│   },                                                      │
│   "key_quotes": [                                         │
│     "之前被Odoo实施商坑过，这次想找有保障的",               │
│     "如果5月前能上线，Q3预算可以批",                        │
│     "排程问题一天不解决，工厂每月多亏$2K"                   │
│   ],                                                      │
│   "_scratchpad_key": "opp_sentosa_requirement"             │
│ }                                                         │
│ 提取物: ~600 tokens（原文 4000 tokens 的 15%）             │
└──────────────────┬───────────────────────────────────────┘
                   │
┌──────────────────▼───────────────────────────────────────┐
│ Step 4: 替换后进入上下文                                    │
│                                                           │
│ 最终进入上下文的 opportunity 记录:                          │
│ {                                                         │
│   "name": "PT Sentosa - ERP",                             │
│   "amount": 45000,                                        │
│   "stage": "proposal",                                    │
│   "owner": "Andi",                                        │
│   "requirement_desc_extracted": {提取物},  ← 替换原文       │
│   "requirement_desc_full": "[Scratchpad: opp_sentosa_requirement]",│
│   "close_date": "2025-05-15",                             │
│   ...                                                     │
│ }                                                         │
│                                                           │
│ Agent 看到提取物就能做大部分分析                             │
│ 需要原文时通过 scratchpad_key 回读                          │
└──────────────────────────────────────────────────────────┘
```

#### 按需回读的完整流程

```
场景: Agent 已看到提取物，用户追问原文细节

用户: "需求描述里关于 Odoo 的部分具体怎么写的"

Agent 处理:
  1. 检查提取物: competitors.Odoo = "免费版用了半年没推起来"
  2. 判断: 提取物有结论但缺少细节（为什么没推起来？谁负责的？）
  3. 从 Scratchpad 语义搜索:
     results = scratchpad.search(
       key="opp_sentosa_requirement",
       query="Odoo 使用情况 实施 失败原因"
     )
     → 返回原文中 2 个相关段落（共 ~1200 字符 ≈ 600 tokens）:
     
     段落 1: "客户 2023 年引入 Odoo 社区版，由本地合作伙伴 PT Digital 
     实施。初期只上了 CRM 和库存模块。实施过程中发现排程模块需要大量
     定制，PT Digital 的开发能力不足，项目延期 3 个月..."
     
     段落 2: "Pak Budi 说'我们花了 $15K 的实施费，结果排程模块到现在
     还不能用。老板很生气，说这次换系统一定要找大公司'..."
  
  4. 这 2 个段落作为 tool_result 进入上下文
  5. Agent 基于段落回答用户
  6. 下一轮，这个 tool_result 按正常生命周期管理

关键: 不是"砍掉 Odoo 相关内容"，而是"完整保存，按需取用"。
```

#### D1 闭环验证

```
业务闭环:
  ✅ 8000 字需求描述的核心信息被提取（决策链、预算、竞品、时间线）
  ✅ 关键原话被保留（"能解决排程问题预算不是问题"）
  ✅ 用户追问细节时能回读原文对应段落
  ✅ 完整原文不丢失（在 Scratchpad 中）

技术闭环:
  ✅ 8000 字 → 600 tokens 提取物进入上下文（节省 85%）
  ✅ 提取延迟 ~500ms（快速模型）
  ✅ 回读延迟 ~50ms（Scratchpad 语义搜索）
  ✅ 原文会话结束自动清理
```

---

### D2: 搜索全文 — 抓取-提取-暂存管线

#### 业务维度：为什么 snippet 不够

```
东南亚 CRM 竞品调研的真实需求:

场景 1: "帮我调研 Odoo 在印尼的完整定价"
  snippet 能给的: "Odoo Enterprise starts at $24.90/user/month"
  实际需要的:
  - 完整价格矩阵（Community vs Enterprise vs Custom）
  - 模块加价（Manufacturing +$18, Inventory +$12...）
  - 用户数阶梯折扣（50+ users 15% off, 100+ 25% off）
  - 印尼本地合作伙伴的实施报价（$20K-$40K）
  - 隐性成本（定制开发、数据迁移、培训）
  → 这些信息分布在定价页的表格和脚注中，snippet 拿不到

场景 2: "搜一下 Salesforce 在泰国的客户案例"
  snippet 能给的: "Salesforce helped Thai company improve sales 30%"
  实际需要的:
  - 客户行业和规模（和我们的目标客户是否匹配）
  - 具体用了哪些模块（Sales Cloud? Service Cloud?）
  - 实施周期和团队规模
  - 量化效果的具体指标
  → 案例详情页通常有 2000-5000 字的完整描述

场景 3: "东南亚 CRM 市场 2025 竞争格局"
  snippet 能给的: "The SEA CRM market is expected to grow..."
  实际需要的:
  - 各厂商市场份额数据（表格）
  - 按国家的渗透率差异
  - 各厂商的产品定位和目标客群
  → 分析报告的核心数据在正文表格中，不在摘要里
```

#### 技术维度：完整的搜索处理管线

```
┌──────────────────────────────────────────────────────────┐
│ Phase 1: 搜索（web_search）                               │
│                                                           │
│ 输入: "Odoo ERP pricing Indonesia 2025 complete"          │
│ 输出: 5-10 条搜索结果（标题 + URL + snippet）              │
│ 大小: ~2K tokens → 直接进入上下文                          │
│                                                           │
│ 搜索结果示例:                                              │
│ 1. "Odoo Pricing | Odoo" - odoo.com/pricing               │
│ 2. "Odoo vs SAP: Complete Comparison 2025" - blog.xxx     │
│ 3. "Odoo Implementation Cost Indonesia" - partner.co.id   │
│ 4. "Odoo Review: Pros and Cons" - g2.com/products/odoo    │
│ 5. "CRM Software Pricing Guide SEA" - analyst-report.com  │
└──────────────────┬───────────────────────────────────────┘
                   │
┌──────────────────▼───────────────────────────────────────┐
│ Phase 2: Agent 智能选择抓取目标                            │
│                                                           │
│ Agent 基于搜索结果和用户意图判断:                           │
│ - 结果 1 (odoo.com/pricing) → ✅ 抓取（官方定价，必须看）  │
│ - 结果 2 (blog 对比文章) → ✅ 抓取（竞品对比信息）         │
│ - 结果 3 (印尼合作伙伴) → ✅ 抓取（本地实施报价）          │
│ - 结果 4 (G2 评测) → ❌ 跳过（用户评价，信息密度低）       │
│ - 结果 5 (分析报告) → ❌ 跳过（可能付费墙）                │
│                                                           │
│ 选择 3 个页面抓取                                          │
│ → 这是 Agent 的推理决策，不是硬编码规则                     │
│ → Agent 会解释为什么选这 3 个                              │
└──────────────────┬───────────────────────────────────────┘
                   │
┌──────────────────▼───────────────────────────────────────┐
│ Phase 3: 抓取全文（web_fetch）                             │
│                                                           │
│ 对每个 URL 抓取完整内容:                                   │
│ - 页面 A (Odoo 定价): 35K 字符 ≈ 8.75K tokens             │
│ - 页面 B (对比博客):  22K 字符 ≈ 5.5K tokens              │
│ - 页面 C (合作伙伴):  15K 字符 ≈ 3.75K tokens             │
│ 总计: 72K 字符 ≈ 18K tokens                               │
│                                                           │
│ 如果直接放进上下文: 占 35% → 不可接受                      │
└──────────────────┬───────────────────────────────────────┘
                   │
┌──────────────────▼───────────────────────────────────────┐
│ Phase 4: 全文存入 Scratchpad + 目标导向提取                │
│                                                           │
│ 4a. 全文存入 Scratchpad:                                   │
│   scratchpad.write("odoo_pricing_page", 页面A全文, "text") │
│   scratchpad.write("odoo_vs_sap_blog", 页面B全文, "text")  │
│   scratchpad.write("odoo_partner_id", 页面C全文, "text")   │
│                                                           │
│ 4b. 目标导向提取（关键：提取 prompt 包含用户意图）          │
│                                                           │
│   提取 Prompt:                                             │
│   "用户正在调研 Odoo 在印尼的定价，目的是和自家产品做竞品对比。│
│    从以下网页内容中提取:                                    │
│    1. 完整价格表（版本×用户数×模块，保留所有数字）           │
│    2. 折扣政策和阶梯定价                                   │
│    3. 实施/服务费用                                        │
│    4. 与其他 CRM/ERP 的对比数据                            │
│    5. 印尼本地化的特殊信息                                 │
│    6. 客户评价中提到的隐性成本                             │
│    保留所有精确数字。信息不存在则标注'页面未提及'。"         │
│                                                           │
│   页面 A 提取物（~500 tokens）:                            │
│   {                                                       │
│     "source": "odoo.com/pricing",                         │
│     "fetch_date": "2025-04-17",                           │
│     "pricing": {                                          │
│       "community": "免费（开源，无官方支持）",              │
│       "enterprise_annual": "$24.90/user/month",           │
│       "enterprise_monthly": "$31.10/user/month",          │
│       "modules": {                                        │
│         "CRM": "included in base",                        │
│         "Sales": "included in base",                      │
│         "Manufacturing": "+$18/user/month",               │
│         "Inventory": "+$12/user/month",                   │
│         "Accounting": "+$12/user/month",                  │
│         "HR": "+$10/user/month"                           │
│       },                                                  │
│       "volume_discount": "50+: 15% off, 100+: 25% off",  │
│       "hosting": "Odoo.sh $24/user/month or self-hosted"  │
│     },                                                    │
│     "not_mentioned": ["实施费用", "印尼本地定价", "培训费用"]│
│   }                                                       │
│                                                           │
│   页面 B 提取物（~400 tokens）:                            │
│   {                                                       │
│     "source": "blog comparison article",                  │
│     "comparison": {                                       │
│       "odoo_vs_sap": {                                    │
│         "price_ratio": "Odoo约为SAP的1/5到1/3",           │
│         "implementation_time": "Odoo 3-6月 vs SAP 12-18月",│
│         "customization": "Odoo开源可深度定制，SAP定制成本高"│
│       }                                                   │
│     },                                                    │
│     "hidden_costs_mentioned": [                           │
│       "Odoo定制开发费通常是license的2-3倍",                │
│       "数据迁移费用$5K-$15K",                              │
│       "年度维护费约license的20%"                           │
│     ]                                                     │
│   }                                                       │
│                                                           │
│   页面 C 提取物（~350 tokens）:                            │
│   {                                                       │
│     "source": "Indonesian Odoo partner",                  │
│     "local_pricing": {                                    │
│       "implementation": "$20K-$40K（视模块数量）",         │
│       "customization": "$150-$200/hour",                  │
│       "training": "$2K-$5K",                              │
│       "annual_support": "$5K-$10K"                        │
│     },                                                    │
│     "typical_total_cost": {                               │
│       "50_users_basic": "$35K-$55K first year",           │
│       "50_users_full": "$60K-$90K first year"             │
│     }                                                     │
│   }                                                       │
│                                                           │
│ 3 个提取物合计: ~1250 tokens                               │
│ 对比原文 18K tokens → 节省 93%                             │
└──────────────────┬───────────────────────────────────────┘
                   │
┌──────────────────▼───────────────────────────────────────┐
│ Phase 5: 提取物进入上下文，Agent 生成分析                   │
│                                                           │
│ Agent 基于 3 个提取物生成竞品定价分析:                      │
│                                                           │
│ "Odoo 在印尼的完整成本分析（50 用户 ERP 场景）:            │
│                                                           │
│  License 费用:                                             │
│  - Enterprise + Manufacturing + Inventory                  │
│  - ($24.90 + $18 + $12) × 50 users × 12 months           │
│  - = $32,940/year                                         │
│                                                           │
│  实施费用（一次性）:                                       │
│  - 本地合作伙伴报价: $20K-$40K                             │
│  - 定制开发: 通常是 license 的 2-3 倍 = $66K-$99K         │
│  - 数据迁移: $5K-$15K                                     │
│  - 培训: $2K-$5K                                          │
│                                                           │
│  第一年总成本: $126K-$192K                                 │
│  后续年度: $33K(license) + $10K(支持) = $43K/year          │
│                                                           │
│  对比我们的报价:                                           │
│  - PT Sentosa 报价 $45K（一次性）+ $12K/year 维护          │
│  - 第一年: $45K vs Odoo $126K-$192K → 我们便宜 64-76%     │
│  - 但 Odoo Community 版免费 → 低预算客户可能选免费版       │
│                                                           │
│  竞争策略建议:                                             │
│  1. 强调总拥有成本（TCO），不只比 license                   │
│  2. 强调实施成功率（Odoo 印尼实施失败率高）                 │
│  3. PT Sentosa 之前 Odoo 失败的经历是最好的论据"           │
│                                                           │
│ 这段分析 ~500 tokens                                       │
│ 上下文总占用: 2K(搜索) + 1.25K(提取物) + 0.5K(分析)       │
│ = 3.75K tokens（而非直接放全文的 20K tokens）               │
└──────────────────────────────────────────────────────────┘
```

#### 用户追问时的回读流程

```
用户: "Odoo 官网上 Manufacturing 模块具体包含哪些功能"

Agent 处理:
  1. 检查提取物: modules.Manufacturing = "+$18/user/month" → 只有价格没有功能
  2. 从 Scratchpad 语义搜索:
     results = scratchpad.search(
       key="odoo_pricing_page",
       query="Manufacturing module features capabilities"
     )
     → 返回定价页中关于 Manufacturing 的描述段落（~800 字符）
  3. 段落作为 tool_result 进入上下文
  4. Agent 基于段落回答

用户: "让我看看那个对比博客的原文"
  → Agent: scratchpad.read("odoo_vs_sap_blog", max_chars=5000)
  → 返回博客前 5000 字符进入上下文
  → 如果用户要看更多: scratchpad.read("odoo_vs_sap_blog", offset=5000)
```

#### D2 闭环验证

```
业务闭环:
  ✅ 完整价格矩阵被提取（不是只有一个 $24.90 的数字）
  ✅ 隐性成本被发现（定制费是 license 的 2-3 倍）
  ✅ 本地化信息被获取（印尼合作伙伴的实施报价）
  ✅ 多来源交叉验证（官网 + 博客 + 合作伙伴）
  ✅ 用户可以追问细节，Agent 能回读原文

技术闭环:
  ✅ 72K 字符全文 → 1.25K tokens 提取物进入上下文（节省 93%）
  ✅ 全文完整保存在 Scratchpad
  ✅ 语义提取 3 页并行 ~1s（快速模型）
  ✅ 回读延迟 ~50ms
  ✅ 会话结束自动清理
```
