"""L0 / L1 / L2 三层信息模型 — 场景化提取与检索 Demo

═══════════════════════════════════════════════════════════════════════
  L0 / L1 / L2 是什么？
═══════════════════════════════════════════════════════════════════════

  L0 — abstract（一句话摘要，~10-30 tokens）
    用途: 向量化（embedding 输入）、目录浏览、快速过滤
    格式: 可合并类型 "[合并键]: [描述]"，独立类型直接描述
    示例: "华为科技/ERP升级: 金额500万，谈判阶段"

  L1 — overview（结构化 Markdown，~50-200 tokens）
    用途: 重排序、内容导航、Agent 规划决策
    格式: 按类别不同的 Markdown 模板（标题 + 列表）
    示例: "## 基本信息\n- 客户: 华为科技\n- 金额: 500万\n## 状态\n- 阶段: 谈判"

  L2 — content（完整描述，无限制）
    用途: 最终回答生成、按需加载
    格式: 针对这条记忆的独立完整描述（不是原文复述）
    示例: "华为科技的ERP升级项目，金额500万，处于谈判阶段，预计下月签约。
           张总(CTO)是关键决策人，已同意报价方案。"

═══════════════════════════════════════════════════════════════════════
  提取流程: 对话 → LLM → L0 + L1 + L2 同时生成
═══════════════════════════════════════════════════════════════════════

  对话:
    [用户] 查一下华为的商机和联系人
    [助手] 华为有3个商机：ERP升级500万谈判阶段，云迁移200万方案阶段，
           安全审计80万closing。联系人张总(CTO)电话139-0001-0001。

  LLM 提取结果（一次调用，同时输出三层）:
    记忆 1:
      L0: "华为科技/ERP升级: 金额500万，谈判阶段"
      L1: "## 基本信息\n- 客户: 华为科技\n- 项目: ERP升级\n- 金额: 500万\n## 状态\n- 阶段: 谈判\n- 预计签约: 下月"
      L2: "华为科技的ERP升级项目，金额500万，处于谈判阶段，预计下月签约。"

    记忆 2:
      L0: "华为科技/张总: 职位CTO，电话139-0001-0001"
      L1: "## 联系人\n- 姓名: 张总\n- 职位: CTO\n## 联系方式\n- 电话: 139-0001-0001"
      L2: "华为科技联系人张总，职位CTO，电话139-0001-0001，负责技术决策。"

═══════════════════════════════════════════════════════════════════════
  检索流程: 查询 → 向量搜索 L0 → 返回 L0 + 按需加载 L1/L2
═══════════════════════════════════════════════════════════════════════

  向量库中存储的是 L0 的 embedding（abstract 字段）
  检索时:
    1. embed(query) → 在 L0 向量空间中搜索 → 返回 Top-K 的 L0 + score
    2. 默认注入 Agent: L0 摘要（~150 tokens / 5条）
    3. Agent 需要详情时: 加载 L1 overview（~500 tokens / 5条）
    4. Agent 需要完整内容时: 加载 L2 content（按需单条加载）

  Token 效率对比（5 条记忆）:
    只用 L0: ~150 tokens  ← 目录浏览、快速判断
    L0 + L1: ~650 tokens  ← 规划决策、重排序
    L0 + L2: ~800 tokens  ← 完整回答生成
    全量 L2:  ~800 tokens  ← 当前默认行为（浪费）

═══════════════════════════════════════════════════════════════════════

运行:
  cd product-specs/agent-system
  .venv/bin/python -B tests/test_l0_l1_l2_demo.py
"""
import asyncio
import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("DOUBAO_API_KEY", "651621e7-e495-4728-93ef-ed380e9ddcd1")

passed = 0
failed = 0


def check(name, condition):
    global passed, failed
    if condition:
        print(f"  ✅ {name}")
        passed += 1
    else:
        print(f"  ❌ {name}")
        failed += 1


def _llm():
    from langchain_openai import ChatOpenAI
    return ChatOpenAI(
        model="doubao-1-5-pro-32k-250115",
        api_key=os.environ["DOUBAO_API_KEY"],
        base_url="https://ark.cn-beijing.volces.com/api/v3/",
        max_tokens=2048,
    )


def _emb():
    from langchain_openai import OpenAIEmbeddings
    return OpenAIEmbeddings(
        model="doubao-embedding-text-240715",
        api_key=os.environ["DOUBAO_API_KEY"],
        base_url="https://ark.cn-beijing.volces.com/api/v3/",
        check_embedding_ctx_length=False,
    )


def _engine(collection):
    from src.memory.viking_engine import VikingMemoryEngine
    return VikingMemoryEngine(
        vdb_url="http://10.60.2.17",
        vdb_key="bRG3NETg13tv5Fn68VTdkxaJXH9tMQzhKeT3unck",
        vdb_username="root",
        database_name="viking_l012_demo",
        collection_name=collection,
        llm=_llm(),
        use_pg=False,
    )


# ═══════════════════════════════════════════════════════════════════════
# 各类别的 L0 / L1 / L2 模板（提取时 LLM 应该遵循的格式）
# ═══════════════════════════════════════════════════════════════════════

L012_TEMPLATES = """
┌─────────────────────────────────────────────────────────────────────┐
│  entities — 客户/商机/联系人/合同                                     │
├─────────────────────────────────────────────────────────────────────┤
│  L0: "[客户名/子实体名]: [关键属性1]，[关键属性2]"                      │
│      示例: "华为科技/ERP升级: 金额500万，谈判阶段"                      │
│      示例: "华为科技/张总: 职位CTO，电话139-xxxx"                       │
│      示例: "华为科技: 通信行业，3商机总金额780万"（顶层汇总）             │
│                                                                     │
│  L1: "## 基本信息                                                    │
│       - 客户: 华为科技                                                │
│       - 项目: ERP升级                                                 │
│       - 金额: 500万                                                   │
│       ## 状态                                                        │
│       - 阶段: 谈判                                                    │
│       - 预计签约: 2026-05"                                            │
│                                                                     │
│  L2: "华为科技的ERP升级项目，金额500万，处于谈判阶段，预计下月签约。      │
│       张总(CTO)是关键决策人，已同意报价方案。"                           │
├─────────────────────────────────────────────────────────────────────┤
│  events — 决策/里程碑/计划                                            │
├─────────────────────────────────────────────────────────────────────┤
│  L0: "YYYY-MM-DD [事件主题]，[结果/影响]"                              │
│      示例: "2026-04-28 华为ERP评审通过，丁总同意报价方案"                │
│                                                                     │
│  L1: "## 决策内容                                                    │
│       丁总同意580万报价方案                                            │
│       ## 原因                                                        │
│       项目评审通过，技术方案获认可                                      │
│       ## 后续                                                        │
│       预计下周三正式签约"                                              │
│                                                                     │
│  L2: "2026-04-28下午2点在华为总部与张总(CTO)开会，ERP项目评审通过。      │
│       丁总当场同意580万报价方案。下一步：下周三(2026-05-06)正式签约。     │
│       参会人：张总、李经理、我方王总。"                                  │
├─────────────────────────────────────────────────────────────────────┤
│  preferences — 用户偏好                                               │
├─────────────────────────────────────────────────────────────────────┤
│  L0: "[偏好方面]: [具体偏好]"                                          │
│      示例: "数据展示偏好: 表格格式，金额用万为单位"                      │
│                                                                     │
│  L1: "## 偏好领域                                                    │
│       - 领域: 数据展示                                                │
│       ## 具体偏好                                                    │
│       - 使用表格格式                                                  │
│       - 金额用万为单位，不要小数"                                      │
│                                                                     │
│  L2: "用户偏好使用表格展示数据，金额统一用万为单位且不显示小数点。        │
│       不要用图表，表格更方便查看具体数字。"                              │
├─────────────────────────────────────────────────────────────────────┤
│  profile — 用户身份                                                   │
├─────────────────────────────────────────────────────────────────────┤
│  L0: "[角色]，[团队/区域]，[核心职责]"                                  │
│      示例: "华东区销售总监，管理15人团队，负责互联网行业大客户"            │
│                                                                     │
│  L1: "## 身份                                                        │
│       - 角色: 销售总监                                                │
│       - 区域: 华东区                                                  │
│       ## 团队                                                        │
│       - 规模: 15人                                                    │
│       - 行业: 互联网"                                                 │
│                                                                     │
│  L2: "用户是华东区的销售总监，管着15个人的团队，主要负责互联网行业大客户。 │
│       熟悉CRM基本操作，不太熟悉数据分析函数。"                           │
├─────────────────────────────────────────────────────────────────────┤
│  cases — 问题 + 解决方案                                              │
├─────────────────────────────────────────────────────────────────────┤
│  L0: "[问题简述] → [解决方案简述]"                                     │
│      示例: "查询商机报错 → 字段名stage写成status，修正后解决"            │
│                                                                     │
│  L1: "## 问题                                                        │
│       查询 opportunity 时报错 field not found                         │
│       ## 原因                                                        │
│       字段名 stage 写成了 status                                      │
│       ## 解决方案                                                    │
│       修正字段名为 stage，建议先用 query_schema 确认"                   │
│                                                                     │
│  L2: "查询 opportunity 实体时报错 'field not found: status'。          │
│       排查发现是字段名拼写错误，opportunity 的阶段字段正确名称是 stage    │
│       而不是 status。修正后查询正常。建议在查询前先用 query_schema       │
│       确认字段名，可以避免这类错误。"                                   │
├─────────────────────────────────────────────────────────────────────┤
│  patterns — 可重复的工作流程                                          │
├─────────────────────────────────────────────────────────────────────┤
│  L0: "[流程名]: [步骤概要]"                                           │
│      示例: "客户360分析: 基本信息→商机→联系人→活动→汇总"                │
│                                                                     │
│  L1: "## 触发条件                                                    │
│       用户请求客户全景分析                                             │
│       ## 执行步骤                                                    │
│       1. 查基本信息（行业、规模）                                      │
│       2. 查商机列表（金额、阶段）                                      │
│       3. 查联系人（姓名、职位）                                        │
│       4. 查活动记录（最近30天）                                        │
│       5. 汇总分析"                                                    │
│                                                                     │
│  L2: "当用户请求客户全景分析时，按以下顺序执行：先查基本信息（行业、       │
│       规模、地区），再查商机列表（按金额排序），然后查联系人（关键决策人    │
│       优先），接着查最近30天的活动记录，最后汇总分析并给出跟进建议。"      │
├─────────────────────────────────────────────────────────────────────┤
│  tools — 工具使用统计                                                 │
├─────────────────────────────────────────────────────────────────────┤
│  L0: "[工具名]: 调用N次，成功率X%"                                     │
│      示例: "query_data: 本轮调用3次，成功率100%"                       │
│                                                                     │
│  L1: "## 工具统计                                                    │
│       - 工具: query_data                                              │
│       - 调用: 3次                                                     │
│       - 成功: 3次                                                     │
│       - 失败: 0次"                                                    │
│                                                                     │
│  L2: "工具 query_data 在本轮对话中调用3次，成功3次，失败0次，            │
│       成功率100%。主要用于查询客户和商机数据。"                          │
├─────────────────────────────────────────────────────────────────────┤
│  skills — 技能执行策略                                                │
├─────────────────────────────────────────────────────────────────────┤
│  L0: "[技能名]: [最佳执行顺序]"                                       │
│      示例: "Pipeline报告: 阶段统计→负责人统计→环比→建议"                │
│                                                                     │
│  L1: "## 技能信息                                                    │
│       - 名称: Pipeline报告                                            │
│       ## 推荐流程                                                    │
│       1. 按阶段统计金额和数量                                          │
│       2. 按负责人分组                                                  │
│       3. 与上月环比                                                    │
│       4. 生成跟进建议"                                                │
│                                                                     │
│  L2: "执行Pipeline报告技能时，最佳顺序是：先按阶段统计金额和数量，       │
│       再按负责人分组，然后与上月环比，最后生成跟进建议。                  │
│       注意：closing阶段的商机要单独标注预计签约日期。"                   │
└─────────────────────────────────────────────────────────────────────┘
"""


# ═══════════════════════════════════════════════════════════════════════
# Scene 1: 提取 — 一段对话同时产出 L0 + L1 + L2
# ═══════════════════════════════════════════════════════════════════════

async def scene_1_extraction():
    """场景 1: 从一段 CRM 对话中提取 L0/L1/L2 三层记忆"""
    print("\n" + "=" * 70)
    print("  Scene 1: 提取 — 一段对话同时产出 L0 + L1 + L2")
    print("=" * 70)

    from langchain_core.messages import HumanMessage, AIMessage
    e = _engine("l012_s1")

    conversation = [
        HumanMessage(content=(
            "帮我查一下华为的情况，包括商机、联系人。"
            "另外我以后想用表格展示数据，金额统一用万为单位。"
        )),
        AIMessage(content=(
            "华为科技当前有3个活跃商机：\n"
            "1. ERP升级项目 — 金额500万，谈判阶段，预计下月签约，关键决策人张总(CTO)\n"
            "2. 云迁移项目 — 金额200万，方案阶段\n"
            "3. 安全审计项目 — 金额80万，closing阶段，合同已审批\n\n"
            "联系人：\n"
            "- 张总，CTO，电话139-0001-0001，负责技术决策\n"
            "- 李经理，采购总监，电话138-0002-0002，负责合同审批\n\n"
            "已记录您的偏好：数据用表格展示，金额用万为单位。"
        )),
    ]

    print("\n  ── 输入对话 ──")
    for msg in conversation:
        role = "用户" if isinstance(msg, HumanMessage) else "助手"
        print(f"    [{role}] {msg.content[:120]}...")

    print("\n  ── LLM 提取中... ──")
    r = await e.extract_and_update(conversation, thread_id="s1", user_id="u_s1")

    print(f"\n  ── 提取结果: {len(r.items)} 条记忆 ──")
    for item in r.items:
        cat = item.metadata.get("category", "?")
        abstract = item.content  # L0
        overview = item.metadata.get("overview", "")  # L1
        full = item.metadata.get("full_content", "")  # L2

        print(f"\n    ┌── [{cat}] ──────────────────────────────")
        print(f"    │ L0 (abstract): {abstract}")
        if overview:
            for line in overview.split("\\n")[:4]:
                print(f"    │ L1 (overview): {line}")
        if full and full != abstract:
            print(f"    │ L2 (content):  {full[:120]}...")
        print(f"    └──────────────────────────────────────────")

    # 验证
    categories = {i.metadata.get("category") for i in r.items}
    print(f"\n  提取到的类别: {categories}")
    check("1.1 提取到entities", "entities" in categories)
    check("1.2 提取到preferences", "preferences" in categories or "profile" in categories)
    check("1.3 至少3条记忆", len(r.items) >= 3)

    # 验证 L0 格式
    for item in r.items:
        cat = item.metadata.get("category")
        l0 = item.content
        if cat == "entities":
            # entities 的 L0 应该是 "[合并键]: [描述]" 格式
            has_colon = ":" in l0 or "：" in l0
            check(f"1.4 entities L0格式 ({l0[:30]})", has_colon)
            break

    # 验证 L1 存在
    has_l1 = any(item.metadata.get("overview") for item in r.items)
    check("1.5 L1 overview存在", has_l1)

    # 验证 L2 存在且独立
    has_l2 = any(item.metadata.get("full_content") for item in r.items)
    check("1.6 L2 content存在", has_l2)

    await asyncio.sleep(1)
    return r


# ═══════════════════════════════════════════════════════════════════════
# Scene 2: 检索 — 向量搜索 L0，返回三层
# ═══════════════════════════════════════════════════════════════════════

async def scene_2_retrieval():
    """场景 2: 检索时向量搜索 L0，返回 L0 + L1 + L2 三层"""
    print("\n" + "=" * 70)
    print("  Scene 2: 检索 — 向量搜索 L0，返回三层内容")
    print("=" * 70)

    from langchain_core.messages import HumanMessage, AIMessage
    e = _engine("l012_s2")

    # 先写入数据
    print("\n  ── 写入测试数据 ──")
    for q, a in [
        ("查一下腾讯的商机",
         "腾讯有2个商机：云服务升级800万谈判阶段，AI平台1200万方案阶段。联系人马总(VP)电话137-0003-0003。"),
        ("我是华南区销售总监，管理20人团队",
         "了解，您是华南区销售总监，管理20人团队。我会从管理视角为您提供信息。"),
        ("上次查合同报错了，后来发现是日期格式不对，用YYYY-MM-DD就好了",
         "是的，合同查询的日期字段要求YYYY-MM-DD格式。建议查询前确认日期格式。"),
    ]:
        r = await e.extract_and_update(
            [HumanMessage(content=q), AIMessage(content=a)],
            thread_id="s2-setup", user_id="u_s2",
        )
        cats = {i.metadata.get("category") for i in r.items}
        print(f"    写入 {len(r.items)} 条: {cats}")

    time.sleep(5)

    # 检索
    print("\n  ── 检索: '腾讯的商机情况' ──")
    result = await e.retrieve("腾讯的商机情况", user_id="u_s2", top_k=5)

    print(f"\n  ── 检索结果: {len(result.items)} 条 ──")
    for item in result.items:
        cat = item.metadata.get("category", "?")
        abstract = item.metadata.get("abstract", "")
        overview = item.metadata.get("overview", "")

        print(f"\n    ┌── [score={item.confidence:.3f}] [{cat}] ──")
        print(f"    │ L0: {abstract[:80]}")
        if overview:
            print(f"    │ L1: {overview[:80]}...")
        print(f"    │ L2: {item.content[:80]}...")
        print(f"    └──────────────────────────────────────────")

    check("2.1 检索到结果", len(result.items) > 0)
    if result.items:
        top = result.items[0]
        check("2.2 L0 abstract存在", bool(top.metadata.get("abstract")))
        check("2.3 L2 content存在", bool(top.content))
        check("2.4 结果与腾讯相关", "腾讯" in top.content or "腾讯" in top.metadata.get("abstract", ""))


# ═══════════════════════════════════════════════════════════════════════
# Scene 3: 分层注入 — 展示不同层级注入 Agent 的 Token 效率
# ═══════════════════════════════════════════════════════════════════════

async def scene_3_layered_injection():
    """场景 3: 分层注入 — L0 / L0+L1 / L0+L2 三种注入策略的 Token 对比"""
    print("\n" + "=" * 70)
    print("  Scene 3: 分层注入 — 三种策略的 Token 效率对比")
    print("=" * 70)

    from langchain_core.messages import HumanMessage, AIMessage
    e = _engine("l012_s3")

    # 写入丰富数据
    print("\n  ── 写入多条记忆 ──")
    conversations = [
        ("查一下百度的商机", "百度有3个商机：AI搜索2000万谈判阶段，自动驾驶5000万方案阶段，云计算800万closing。"),
        ("百度的联系人是谁", "百度联系人：王总(CTO)电话136-0001-0001，赵经理(采购)电话135-0002-0002。"),
        ("上周和百度王总开了技术评审会", "已记录：上周与百度王总开技术评审会，AI搜索项目技术方案获批，预计下月进入商务谈判。"),
        ("我习惯每周一看Pipeline报告", "已记录：每周一查看Pipeline报告的习惯。"),
        ("查数据的时候先用query_schema确认字段", "好的建议，先确认字段名可以避免查询报错。"),
    ]
    for q, a in conversations:
        r = await e.extract_and_update(
            [HumanMessage(content=q), AIMessage(content=a)],
            thread_id="s3-setup", user_id="u_s3",
        )
        print(f"    写入 {len(r.items)} 条")

    time.sleep(5)

    # 检索
    result = await e.retrieve("百度的情况", user_id="u_s3", top_k=5)
    items = result.items

    if not items:
        print("  ⚠️ 无检索结果，跳过")
        check("3.1 有检索结果", False)
        return

    # ── 策略 A: 只注入 L0 ──
    print("\n  ── 策略 A: 只注入 L0（最省 token）──")
    l0_text = "<memory_context>\n"
    for item in items:
        abstract = item.metadata.get("abstract", item.content[:50])
        l0_text += f"  - [{item.metadata.get('category', '?')}] {abstract}\n"
    l0_text += "</memory_context>"
    l0_chars = len(l0_text)
    print(f"    {l0_text}")
    print(f"    → 字符数: {l0_chars}")

    # ── 策略 B: L0 + L1 ──
    print("\n  ── 策略 B: L0 + L1（规划决策用）──")
    l01_text = "<memory_context>\n"
    for item in items:
        abstract = item.metadata.get("abstract", item.content[:50])
        overview = item.metadata.get("overview", "")
        l01_text += f"  [{item.metadata.get('category', '?')}] {abstract}\n"
        if overview:
            for line in overview.replace("\\n", "\n").split("\n")[:3]:
                if line.strip():
                    l01_text += f"    {line.strip()}\n"
    l01_text += "</memory_context>"
    l01_chars = len(l01_text)
    print(f"    {l01_text[:300]}...")
    print(f"    → 字符数: {l01_chars}")

    # ── 策略 C: L0 + L2（完整回答用）──
    print("\n  ── 策略 C: L0 + L2（完整回答用）──")
    l02_text = "<memory_context>\n"
    for item in items:
        abstract = item.metadata.get("abstract", "")
        l02_text += f"  [{item.metadata.get('category', '?')}] {abstract}\n"
        l02_text += f"    详情: {item.content}\n"
    l02_text += "</memory_context>"
    l02_chars = len(l02_text)
    print(f"    {l02_text[:300]}...")
    print(f"    → 字符数: {l02_chars}")

    # ── 对比 ──
    print(f"\n  ── Token 效率对比 ──")
    print(f"    策略 A (L0 only):  {l0_chars:>5} 字符  ← 目录浏览、快速判断")
    print(f"    策略 B (L0 + L1):  {l01_chars:>5} 字符  ← 规划决策、重排序")
    print(f"    策略 C (L0 + L2):  {l02_chars:>5} 字符  ← 完整回答生成")
    if l0_chars > 0:
        print(f"    B/A 比值: {l01_chars / l0_chars:.1f}x")
        print(f"    C/A 比值: {l02_chars / l0_chars:.1f}x")

    check("3.1 有检索结果", len(items) > 0)
    check("3.2 L0 < L0+L1", l0_chars < l01_chars)
    check("3.3 L0+L1 <= L0+L2", l01_chars <= l02_chars)
    check("3.4 L0节省显著", l0_chars < l02_chars * 0.5)


# ═══════════════════════════════════════════════════════════════════════
# Scene 4: 8 类 × L0/L1/L2 完整提取验证
# ═══════════════════════════════════════════════════════════════════════

async def scene_4_all_categories():
    """场景 4: 一段复杂对话，验证 8 类记忆的 L0/L1/L2 提取质量"""
    print("\n" + "=" * 70)
    print("  Scene 4: 8 类 × L0/L1/L2 完整提取验证")
    print("=" * 70)

    from langchain_core.messages import HumanMessage, AIMessage, ToolMessage
    e = _engine("l012_s4")

    # 一段包含多种信息的复杂对话
    conversation = [
        HumanMessage(content=(
            "我是华东区销售总监，管理15人团队，负责互联网行业大客户。"
            "帮我查一下小米集团的商机，另外以后数据都用表格展示，金额用万为单位。"
        )),
        AIMessage(content="", tool_calls=[{"id": "tc1", "name": "query_data", "args": {"entity": "opportunity"}}]),
        ToolMessage(content="查到2个商机：IoT平台650万方案阶段，智能工厂1800万谈判阶段", tool_call_id="tc1", name="query_data"),
        AIMessage(content=(
            "小米集团当前有2个活跃商机：\n"
            "1. IoT平台项目 — 金额650万，方案阶段\n"
            "2. 智能工厂项目 — 金额1800万，谈判阶段，预计Q3签约\n\n"
            "联系人李总(CTO)，电话139-0004-0004。\n\n"
            "今天下午和小米李总确认了智能工厂项目的技术方案，他同意进入商务谈判阶段。\n\n"
            "已记录您的偏好：表格展示、金额用万为单位。\n\n"
            "提示：查询商机时建议先用 query_schema 确认字段名，"
            "上次有用户把 stage 写成 status 导致报错。\n\n"
            "客户全景分析的最佳流程是：基本信息→商机→联系人→活动→汇总。"
        )),
    ]

    print("\n  ── LLM 提取中... ──")
    r = await e.extract_and_update(conversation, thread_id="s4", user_id="u_s4")

    print(f"\n  ── 提取结果: {len(r.items)} 条记忆 ──")

    # 按类别分组展示
    by_cat: dict[str, list] = {}
    for item in r.items:
        cat = item.metadata.get("category", "unknown")
        by_cat.setdefault(cat, []).append(item)

    for cat in ["profile", "preferences", "entities", "events", "cases", "patterns", "tools", "skills"]:
        items = by_cat.get(cat, [])
        print(f"\n  ── {cat} ({len(items)} 条) ──")
        if not items:
            print(f"    （未提取到）")
            continue
        for item in items:
            abstract = item.content
            overview = item.metadata.get("overview", "")
            full = item.metadata.get("full_content", "")
            print(f"    L0: {abstract}")
            if overview:
                # 只显示前 2 行
                lines = overview.replace("\\n", "\n").split("\n")
                for line in lines[:2]:
                    if line.strip():
                        print(f"    L1: {line.strip()}")
                if len(lines) > 2:
                    print(f"    L1: ...({len(lines)} 行)")
            if full and full != abstract:
                print(f"    L2: {full[:100]}...")
            print()

    # 验证各类别
    extracted_cats = set(by_cat.keys())
    print(f"  提取到的类别: {extracted_cats}")

    check("4.1 提取到profile", "profile" in extracted_cats)
    check("4.2 提取到preferences", "preferences" in extracted_cats)
    check("4.3 提取到entities", "entities" in extracted_cats)
    check("4.4 提取到tools（自动统计）", "tools" in extracted_cats)

    # 验证 entities 的 L0 格式: "[合并键]: [描述]"
    entity_items = by_cat.get("entities", [])
    if entity_items:
        l0 = entity_items[0].content
        check("4.5 entities L0含冒号分隔", ":" in l0 or "：" in l0)
    else:
        check("4.5 entities L0含冒号分隔", False)

    # 验证 tools 的 L0 格式: "[工具名]: 调用N次，成功率X%"
    tool_items = by_cat.get("tools", [])
    if tool_items:
        l0 = tool_items[0].content
        check("4.6 tools L0含调用次数", "调用" in l0 or "次" in l0)
    else:
        check("4.6 tools L0含调用次数", False)

    # 验证 L1 overview 存在
    has_overview = any(
        item.metadata.get("overview")
        for items in by_cat.values()
        for item in items
    )
    check("4.7 至少一条有L1 overview", has_overview)

    # 验证 L2 content 独立（不同记忆的 content 不相同）
    contents = [
        item.metadata.get("full_content", "")
        for items in by_cat.values()
        for item in items
        if item.metadata.get("full_content")
    ]
    unique_contents = set(contents)
    check("4.8 L2 content各条独立", len(unique_contents) >= min(len(contents), 2))

    await asyncio.sleep(1)


# ═══════════════════════════════════════════════════════════════════════
# Scene 5: 生产级完整链路 — 提取 → 存储 → 检索 → 分层注入
# ═══════════════════════════════════════════════════════════════════════

async def scene_5_full_pipeline():
    """场景 5: 模拟生产环境的完整链路"""
    print("\n" + "=" * 70)
    print("  Scene 5: 生产级完整链路")
    print("  提取 → 存储(L0向量化) → 检索(L0匹配) → 分层注入")
    print("=" * 70)

    from langchain_core.messages import HumanMessage, AIMessage
    e = _engine("l012_s5")

    # ── 第一轮对话: 写入记忆 ──
    print("\n  ── 第一轮对话: 写入记忆 ──")
    r1 = await e.extract_and_update([
        HumanMessage(content="查一下京东的商机和联系人"),
        AIMessage(content=(
            "京东有2个商机：电商平台升级1500万谈判阶段，物流系统800万方案阶段。"
            "联系人刘总(VP)电话136-0005-0005，负责技术合作。"
        )),
    ], thread_id="s5-1", user_id="u_s5")
    print(f"    写入 {len(r1.items)} 条记忆:")
    for item in r1.items:
        print(f"      [{item.metadata.get('category')}] L0: {item.content}")

    time.sleep(5)

    # ── 第二轮对话: 检索记忆 ──
    print("\n  ── 第二轮对话: 用户问 '京东的情况怎么样' ──")
    print("  检索流程:")

    # Step 1: 查询改写
    rewritten = await e.rewrite_query(
        [HumanMessage(content="京东的情况怎么样")],
        "京东的情况怎么样",
    )
    print(f"    1. 查询改写: '{rewritten}'")

    # Step 2: 意图分析
    intents = await e._analyze_intent(rewritten)
    print(f"    2. 意图分析: {intents}")

    # Step 3: 向量检索（搜索 L0 的 embedding）
    result = await e.retrieve(rewritten, user_id="u_s5", top_k=5)
    print(f"    3. 向量检索: 命中 {len(result.items)} 条")

    # Step 4: 展示三层内容
    print(f"\n  ── 检索结果（三层展示）──")
    for i, item in enumerate(result.items):
        cat = item.metadata.get("category", "?")
        abstract = item.metadata.get("abstract", "")
        overview = item.metadata.get("overview", "")

        print(f"\n    记忆 {i + 1} [score={item.confidence:.3f}] [{cat}]")
        print(f"      L0: {abstract or item.content[:60]}")
        if overview:
            print(f"      L1: {overview[:80]}...")
        print(f"      L2: {item.content[:100]}...")

    # Step 5: 模拟分层注入
    print(f"\n  ── 分层注入策略 ──")
    print(f"    当前默认: 注入 L2 content（完整内容）")
    print(f"    优化方案: 先注入 L0 摘要，Agent 按需请求 L1/L2")
    print()

    # 构造 L0-only 注入
    l0_injection = "<memory_context>\n"
    for item in result.items:
        abstract = item.metadata.get("abstract", item.content[:50])
        l0_injection += f"  - [{item.metadata.get('category', '?')}] {abstract}\n"
    l0_injection += "</memory_context>"

    # 构造 L2 注入（当前默认）
    l2_injection = "<memory_context>\n"
    for item in result.items:
        l2_injection += f"  - [{item.metadata.get('category', '?')}] {item.content}\n"
    l2_injection += "</memory_context>"

    print(f"    L0 注入 ({len(l0_injection)} 字符):")
    print(f"      {l0_injection[:200]}...")
    print(f"    L2 注入 ({len(l2_injection)} 字符):")
    print(f"      {l2_injection[:200]}...")
    print(f"    节省: {(1 - len(l0_injection) / max(1, len(l2_injection))) * 100:.0f}%")

    check("5.1 检索到结果", len(result.items) > 0)
    check("5.2 结果与京东相关",
          any("京东" in i.content or "京东" in i.metadata.get("abstract", "") for i in result.items))
    check("5.3 L0注入更短", len(l0_injection) < len(l2_injection))


# ═══════════════════════════════════════════════════════════════════════
# Scene 6: L0 向量化质量验证
#   核心问题: L0 是 embedding 的输入，L0 的质量直接决定检索质量
#   验证: 用不同的查询检索，看 L0 的向量匹配是否准确
# ═══════════════════════════════════════════════════════════════════════

async def scene_6_l0_embedding_quality():
    """场景 6: L0 向量化质量 — L0 摘要的 embedding 是否能准确匹配查询"""
    print("\n" + "=" * 70)
    print("  Scene 6: L0 向量化质量验证")
    print("  L0 是 embedding 输入，L0 质量 = 检索质量")
    print("=" * 70)

    from langchain_core.messages import HumanMessage, AIMessage
    e = _engine("l012_s6")

    # 写入多种类别的记忆
    print("\n  ── 写入多类别记忆 ──")
    test_data = [
        ("查一下阿里巴巴的商机", "阿里巴巴有1个商机：云计算项目3000万，谈判阶段。联系人陈总(CTO)。"),
        ("我喜欢简洁的回复风格，不要长篇大论", "好的，已记录：简洁回复风格，直接给结论。"),
        ("上次查合同时日期格式不对导致报错", "是的，合同日期要用YYYY-MM-DD格式。这个经验值得记录。"),
        ("每次分析客户都是先查基本信息再查商机", "了解，这是您的分析习惯：基本信息→商机→联系人→汇总。"),
    ]
    for q, a in test_data:
        r = await e.extract_and_update(
            [HumanMessage(content=q), AIMessage(content=a)],
            thread_id="s6-setup", user_id="u_s6",
        )
        for item in r.items:
            print(f"    [{item.metadata.get('category')}] L0: {item.content[:60]}")

    time.sleep(5)

    # 测试不同查询的检索准确性
    test_queries = [
        ("阿里巴巴的商机", "entities", "阿里"),
        ("我的偏好设置", "preferences", "简洁"),
        ("之前遇到过什么报错", "cases", "报错"),
        ("分析客户的流程", "patterns", "分析"),
    ]

    print(f"\n  ── 检索质量验证 ──")
    for query, expected_cat, expected_keyword in test_queries:
        result = await e.retrieve(query, user_id="u_s6", top_k=3)
        print(f"\n    查询: '{query}'")
        if result.items:
            top = result.items[0]
            cat = top.metadata.get("category", "?")
            abstract = top.metadata.get("abstract", top.content[:50])
            print(f"    Top-1: [score={top.confidence:.3f}] [{cat}] {abstract}")
            hit = cat == expected_cat or expected_keyword in abstract or expected_keyword in top.content
            check(f"6.x '{query}' → {expected_cat}", hit)
        else:
            print(f"    ⚠️ 无结果")
            check(f"6.x '{query}' → {expected_cat}", False)


# ═══════════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("=" * 70)
    print("  L0 / L1 / L2 三层信息模型 — 场景化提取与检索 Demo")
    print("=" * 70)
    print(L012_TEMPLATES)

    async def run_all():
        await scene_1_extraction()
        await scene_2_retrieval()
        await scene_3_layered_injection()
        await scene_4_all_categories()
        await scene_5_full_pipeline()
        await scene_6_l0_embedding_quality()
        await asyncio.sleep(2)

    asyncio.run(run_all())

    print(f"\n{'=' * 70}")
    print(f"  L0/L1/L2 Demo: {passed} passed, {failed} failed")
    print(f"{'=' * 70}")
    sys.exit(1 if failed else 0)
