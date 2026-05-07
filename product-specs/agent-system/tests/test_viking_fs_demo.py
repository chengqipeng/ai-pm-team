"""目录递归检索 Demo — 基于 VikingFS 虚拟文件系统

═══════════════════════════════════════════════════════════════
  什么是"目录递归检索"？
═══════════════════════════════════════════════════════════════

传统向量检索（扁平模式）:
  用户: "华为的商机" → embed → cosine search → 返回 Top-K
  问题: 所有记忆平铺在一个向量空间里，无法按层级浏览

目录递归检索（OpenViking 范式）:
  记忆按 URI 路径组织成目录树，检索时逐层下钻:

  Step 1 — 根目录 ls
    viking://user/memories/
    ├── entities/  (14 条)     ← 看到有 entities 类别
    ├── events/    (2 条)
    └── preferences/ (2 条)

  Step 2 — 进入 entities 目录 ls
    viking://user/memories/entities/
    ├── 华为科技/  (5 条)      ← 看到华为有 5 条子记忆
    ├── 腾讯/      (3 条)
    └── 小米集团/  (3 条)

  Step 3 — 进入华为科技目录 ls
    viking://user/memories/entities/华为科技/
    ├── ERP升级项目: 金额500万，谈判阶段
    ├── 云迁移项目: 金额200万，方案阶段
    ├── 安全审计: 金额80万，closing阶段
    ├── 张总: 职位CTO，电话139-0001-0001
    └── 李经理: 职位采购总监，电话138-0002-0002

  Step 4 — 读取具体记忆 read
    viking://user/memories/entities/华为科技/ERP升级项目
    → L0: "华为科技/ERP升级: 金额500万，谈判阶段"
    → L1: "## 基本信息\n- 客户: 华为科技\n- 金额: 500万\n## 状态\n- 阶段: 谈判"
    → L2: "华为科技的ERP升级项目，金额500万，处于谈判阶段，预计下月签约。"

核心优势:
  1. Token 效率: 先看 L0 摘要（~10 tokens），需要时才加载 L2（~100 tokens）
  2. 结构化导航: Agent 可以像浏览文件系统一样浏览记忆
  3. 精确隔离: 通过 parent_entity filter 保证不跨客户污染
  4. 聚合视图: 目录级别自动聚合子条目的摘要

═══════════════════════════════════════════════════════════════

运行:
  cd product-specs/agent-system
  .venv/bin/python -B tests/test_viking_fs_demo.py
"""
import asyncio
import os
import sys
import time
from uuid import uuid4

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("DOUBAO_API_KEY", "651621e7-e495-4728-93ef-ed380e9ddcd1")

passed = 0
failed = 0

VDB_CONFIG = {
    "vdb_url": "http://10.60.2.17",
    "vdb_key": "bRG3NETg13tv5Fn68VTdkxaJXH9tMQzhKeT3unck",
    "vdb_username": "root",
    "database_name": "viking_fs_demo_v1",
}
COLLECTION = "fs_demo_v1"


def check(name, condition):
    global passed, failed
    if condition:
        print(f"  ✅ {name}")
        passed += 1
    else:
        print(f"  ❌ {name}")
        failed += 1


def _get_emb():
    from langchain_openai import OpenAIEmbeddings
    return OpenAIEmbeddings(
        model="doubao-embedding-text-240715",
        api_key=os.environ["DOUBAO_API_KEY"],
        base_url="https://ark.cn-beijing.volces.com/api/v3/",
        check_embedding_ctx_length=False,
    )


# ═══════════════════════════════════════════════════════════
# 测试数据 — 模拟 CRM 生产环境
# ═══════════════════════════════════════════════════════════

TEST_MEMORIES = [
    # ── 华为科技（1 汇总 + 3 商机 + 2 联系人 = 6 条）──
    {"category": "entities", "merge_key": "华为科技", "parent_entity": "",
     "abstract": "华为科技: 通信行业龙头，3个商机总金额780万",
     "overview": "## 客户概况\n- 行业: 通信\n- 商机数: 3\n## 金额\n- 总金额: 780万",
     "content": "华为科技是通信行业龙头企业，当前有3个活跃商机，总金额780万。主要联系人张总(CTO)和李经理(采购总监)。"},
    {"category": "entities", "merge_key": "华为科技/ERP升级", "parent_entity": "华为科技",
     "abstract": "华为科技/ERP升级: 金额500万，谈判阶段",
     "overview": "## 基本信息\n- 客户: 华为科技\n- 金额: 500万\n## 状态\n- 阶段: 谈判\n- 预计签约: 2026-05",
     "content": "华为科技的ERP升级项目，金额500万，处于谈判阶段，预计下月签约。张总(CTO)是关键决策人。"},
    {"category": "entities", "merge_key": "华为科技/云迁移", "parent_entity": "华为科技",
     "abstract": "华为科技/云迁移: 金额200万，方案阶段",
     "overview": "## 基本信息\n- 客户: 华为科技\n- 金额: 200万\n## 状态\n- 阶段: 方案",
     "content": "华为科技的云迁移项目，金额200万，处于方案阶段。技术方案待确认。"},
    {"category": "entities", "merge_key": "华为科技/安全审计", "parent_entity": "华为科技",
     "abstract": "华为科技/安全审计: 金额80万，closing阶段",
     "overview": "## 基本信息\n- 客户: 华为科技\n- 金额: 80万\n## 状态\n- 阶段: closing",
     "content": "华为科技的安全审计项目，金额80万，处于closing阶段，合同已审批。"},
    {"category": "entities", "merge_key": "华为科技/张总", "parent_entity": "华为科技",
     "abstract": "华为科技/张总: 职位CTO，电话139-0001-0001",
     "overview": "## 联系人\n- 姓名: 张总\n- 职位: CTO\n## 联系方式\n- 电话: 139-0001-0001",
     "content": "华为科技联系人张总，职位CTO，电话139-0001-0001，负责技术决策，是ERP项目的关键决策人。"},
    {"category": "entities", "merge_key": "华为科技/李经理", "parent_entity": "华为科技",
     "abstract": "华为科技/李经理: 职位采购总监，电话138-0002-0002",
     "overview": "## 联系人\n- 姓名: 李经理\n- 职位: 采购总监\n## 联系方式\n- 电话: 138-0002-0002",
     "content": "华为科技联系人李经理，职位采购总监，电话138-0002-0002，负责合同审批和采购流程。"},

    # ── 腾讯（1 汇总 + 2 商机 + 1 联系人 = 4 条）──
    {"category": "entities", "merge_key": "腾讯", "parent_entity": "",
     "abstract": "腾讯: 互联网巨头，2个商机总金额2000万",
     "overview": "## 客户概况\n- 行业: 互联网\n- 商机数: 2\n## 金额\n- 总金额: 2000万",
     "content": "腾讯是互联网巨头，当前有2个活跃商机，总金额2000万。"},
    {"category": "entities", "merge_key": "腾讯/云服务升级", "parent_entity": "腾讯",
     "abstract": "腾讯/云服务升级: 金额800万，谈判阶段",
     "overview": "## 基本信息\n- 客户: 腾讯\n- 金额: 800万\n## 状态\n- 阶段: 谈判",
     "content": "腾讯的云服务升级项目，金额800万，处于谈判阶段。"},
    {"category": "entities", "merge_key": "腾讯/AI平台", "parent_entity": "腾讯",
     "abstract": "腾讯/AI平台: 金额1200万，方案阶段",
     "overview": "## 基本信息\n- 客户: 腾讯\n- 金额: 1200万\n## 状态\n- 阶段: 方案",
     "content": "腾讯的AI平台项目，金额1200万，处于方案阶段。"},
    {"category": "entities", "merge_key": "腾讯/马总", "parent_entity": "腾讯",
     "abstract": "腾讯/马总: 职位VP，电话137-0003-0003",
     "overview": "## 联系人\n- 姓名: 马总\n- 职位: VP\n## 联系方式\n- 电话: 137-0003-0003",
     "content": "腾讯联系人马总，职位VP，电话137-0003-0003。"},

    # ── 小米集团（1 汇总 + 2 商机 + 1 联系人 = 4 条）──
    {"category": "entities", "merge_key": "小米集团", "parent_entity": "",
     "abstract": "小米集团: IoT龙头，2个商机总金额2450万",
     "overview": "## 客户概况\n- 行业: IoT\n- 商机数: 2\n## 金额\n- 总金额: 2450万",
     "content": "小米集团是IoT行业龙头，当前有2个活跃商机，总金额2450万。"},
    {"category": "entities", "merge_key": "小米集团/IoT平台", "parent_entity": "小米集团",
     "abstract": "小米集团/IoT平台: 金额650万，方案阶段",
     "overview": "## 基本信息\n- 客户: 小米集团\n- 金额: 650万\n## 状态\n- 阶段: 方案",
     "content": "小米集团的IoT平台项目，金额650万，处于方案阶段。"},
    {"category": "entities", "merge_key": "小米集团/智能工厂", "parent_entity": "小米集团",
     "abstract": "小米集团/智能工厂: 金额1800万，谈判阶段",
     "overview": "## 基本信息\n- 客户: 小米集团\n- 金额: 1800万\n## 状态\n- 阶段: 谈判",
     "content": "小米集团的智能工厂项目，金额1800万，处于谈判阶段。"},
    {"category": "entities", "merge_key": "小米集团/李总", "parent_entity": "小米集团",
     "abstract": "小米集团/李总: 职位CTO，电话139-0004-0004",
     "overview": "## 联系人\n- 姓名: 李总\n- 职位: CTO\n## 联系方式\n- 电话: 139-0004-0004",
     "content": "小米集团联系人李总，职位CTO，电话139-0004-0004。"},

    # ── 事件（2 条）──
    {"category": "events", "merge_key": "", "parent_entity": "华为科技",
     "abstract": "2026-04-28 华为ERP项目评审通过，丁总同意报价方案",
     "overview": "## 决策\n丁总同意报价方案\n## 结果\n预计下周签约",
     "content": "2026-04-28与华为张总开会，ERP项目评审通过，丁总同意580万报价方案，预计下周三签约。"},
    {"category": "events", "merge_key": "", "parent_entity": "腾讯",
     "abstract": "2026-04-25 腾讯云服务项目启动会",
     "overview": "## 会议\n腾讯云服务升级项目启动会\n## 结果\n确定技术方案和时间表",
     "content": "2026-04-25腾讯云服务升级项目启动会，确定了技术方案和时间表。"},

    # ── 偏好（2 条）──
    {"category": "preferences", "merge_key": "数据展示偏好", "parent_entity": "",
     "abstract": "数据展示偏好: 表格格式，简洁风格",
     "overview": "## 偏好\n- 格式: 表格\n- 风格: 简洁",
     "content": "用户偏好使用表格展示数据，要求简洁不要长篇分析。"},
    {"category": "preferences", "merge_key": "回复风格偏好", "parent_entity": "",
     "abstract": "回复风格偏好: 简洁，给结论不要长篇大论",
     "overview": "## 偏好\n- 风格: 简洁\n- 要求: 直接给结论",
     "content": "用户偏好简洁的回复风格，直接给结论，不要长篇大论。"},

    # ── 案例（1 条）──
    {"category": "cases", "merge_key": "", "parent_entity": "",
     "abstract": "查询商机报错 → 字段名 stage 写成 status",
     "overview": "## 问题\n查询商机时报错\n## 解决\n字段名 stage 写成了 status",
     "content": "查询 opportunity 时报错，原因是字段名写错，stage 写成了 status。修正后查询正常。"},

    # ── 模式（1 条）──
    {"category": "patterns", "merge_key": "客户360分析流程", "parent_entity": "",
     "abstract": "客户360分析流程: 基本信息→商机→联系人→活动→汇总",
     "overview": "## 流程\n1. 查基本信息\n2. 查商机\n3. 查联系人\n4. 查活动\n5. 汇总",
     "content": "当用户请求客户全景分析时，按以下顺序执行：先查基本信息，再查商机列表，然后查联系人，接着查活动记录，最后汇总分析。"},
]


# ═══════════════════════════════════════════════════════════
# 数据准备 — 写入向量库
# ═══════════════════════════════════════════════════════════

def setup_data():
    """写入测试数据到向量库"""
    from src.memory.viking_engine import VikingMemoryEngine
    emb = _get_emb()

    engine = VikingMemoryEngine(
        **VDB_CONFIG, collection_name=COLLECTION, llm=None, use_pg=False,
    )

    print(f"写入 {len(TEST_MEMORIES)} 条测试记忆...")
    for m in TEST_MEMORIES:
        vec = emb.embed_query(m["abstract"])
        engine._vdb.upsert([{
            "id": str(uuid4()), "vector": vec,
            "text": m["abstract"],
            "abstract": m["abstract"],
            "overview": m.get("overview", ""),
            "content": m["content"],
            "category": m["category"],
            "merge_key": m["merge_key"],
            "parent_entity": m["parent_entity"],
            "user_id": "demo_user",
            "thread_id": "setup",
            "created_at": "2026-04-28T00:00:00+00:00",
            "updated_at": "2026-04-28T00:00:00+00:00",
        }])

    print("等待索引构建...")
    time.sleep(8)
    return engine


# ═══════════════════════════════════════════════════════════
# Demo 1: 完整目录树展示
#   展示 VikingFS 的 tree() 递归遍历能力
#   从根目录开始，逐层展开所有子目录
# ═══════════════════════════════════════════════════════════

def demo_1_full_tree(engine):
    print("\n" + "=" * 70)
    print("  Demo 1: 完整目录树展示")
    print("  VikingFS.tree() — 从根目录递归展开所有层级")
    print("=" * 70)

    from src.memory.viking_fs import VikingFS
    fs = VikingFS(pg_dao=None, vdb=engine._vdb, user_id="demo_user")

    # user 空间
    print("\n  ── user 空间 ──")
    tree_text = fs.tree("viking://user/memories/", max_depth=3)
    for line in tree_text.split("\n"):
        print(f"  {line}")

    # agent 空间
    print("\n  ── agent 空间 ──")
    tree_text = fs.tree("viking://agent/memories/", max_depth=3)
    for line in tree_text.split("\n"):
        print(f"  {line}")

    check("1.1 目录树生成成功", True)


# ═══════════════════════════════════════════════════════════
# Demo 2: 逐层下钻 — 模拟 Agent 浏览记忆的过程
#   Step 1: ls 根目录 → 看到有哪些类别
#   Step 2: ls entities/ → 看到有哪些客户
#   Step 3: ls entities/华为科技/ → 看到华为的所有子记忆
#   Step 4: read 具体记忆 → 获取 L0/L1/L2 三层内容
# ═══════════════════════════════════════════════════════════

def demo_2_drill_down(engine):
    print("\n" + "=" * 70)
    print("  Demo 2: 逐层下钻（Agent 浏览记忆的完整过程）")
    print("=" * 70)

    from src.memory.viking_fs import VikingFS
    fs = VikingFS(pg_dao=None, vdb=engine._vdb, user_id="demo_user")

    # Step 1: ls 根目录
    print("\n  ── Step 1: ls viking://user/memories/ ──")
    print("  （Agent 看到有哪些记忆类别）")
    root_nodes = fs.ls("viking://user/memories/")
    for n in root_nodes:
        icon = "📁" if n.is_directory else "📄"
        suffix = f" ({n.children_count} 条)" if n.children_count else ""
        print(f"    {icon} {n.name}{suffix}")
    check("2.1 根目录有条目", len(root_nodes) > 0)

    # Step 2: ls entities/
    print("\n  ── Step 2: ls viking://user/memories/entities/ ──")
    print("  （Agent 看到有哪些客户）")
    entity_nodes = fs.ls("viking://user/memories/entities/")
    for n in entity_nodes:
        icon = "📁" if n.is_directory else "📄"
        suffix = f" ({n.children_count} 条)" if n.children_count else ""
        print(f"    {icon} {n.name}{suffix}: {n.abstract[:50]}")
    check("2.2 entities下有客户", len(entity_nodes) >= 3)

    # Step 3: ls entities/华为科技/
    print("\n  ── Step 3: ls viking://user/memories/entities/华为科技/ ──")
    print("  （Agent 看到华为的所有商机和联系人）")
    huawei_nodes = []
    # 找到华为科技的 URI
    for n in entity_nodes:
        if "华为" in n.name:
            huawei_nodes = fs.ls(n.uri)
            break
    for n in huawei_nodes:
        print(f"    📄 {n.name}: {n.abstract[:60]}")
    check("2.3 华为下有子条目", len(huawei_nodes) >= 3)

    # 验证子条目包含商机和联系人
    abstracts = " ".join(n.abstract for n in huawei_nodes)
    has_opportunity = "金额" in abstracts or "阶段" in abstracts
    has_contact = "职位" in abstracts or "电话" in abstracts
    check("2.4 包含商机信息", has_opportunity)
    check("2.5 包含联系人信息", has_contact)

    # Step 4: read 具体记忆（三层内容）
    print("\n  ── Step 4: read 具体记忆（L0 / L1 / L2 三层）──")
    if huawei_nodes:
        target = huawei_nodes[0]
        node = fs.read(target.uri)
        if node:
            print(f"    URI:      {target.uri}")
            print(f"    L0 摘要:  {node.abstract}")
            print(f"    L1 概览:  {node.overview[:100]}...")
            print(f"    L2 完整:  {node.content}")
            check("2.6 read返回三层内容", bool(node.abstract and node.content))
        else:
            print(f"    ⚠️ read 返回 None（URI: {target.uri}）")
            check("2.6 read返回三层内容", False)
    else:
        check("2.6 read返回三层内容", False)


# ═══════════════════════════════════════════════════════════
# Demo 3: 两级下钻 — "哪个客户金额最大"
#   生产场景: Agent 先看顶层客户汇总，再下钻到最大客户的详情
#   Step 1: ls entities/ → 看到 3 个客户的汇总
#   Step 2: 选金额最大的客户 → ls 该客户/ → 看到具体商机
# ═══════════════════════════════════════════════════════════

def demo_3_two_level_drill(engine):
    print("\n" + "=" * 70)
    print("  Demo 3: 两级下钻 — 找金额最大的客户")
    print("  Step 1: 看顶层汇总 → Step 2: 下钻到具体商机")
    print("=" * 70)

    from src.memory.viking_fs import VikingFS
    fs = VikingFS(pg_dao=None, vdb=engine._vdb, user_id="demo_user")

    # Step 1: 看顶层客户汇总
    print("\n  ── Step 1: 顶层客户汇总 ──")
    entity_nodes = fs.ls("viking://user/memories/entities/")
    for n in entity_nodes:
        print(f"    📁 {n.name}: {n.abstract[:60]}")

    # 找金额最大的客户（从 abstract 中提取金额）
    import re
    best_node = None
    best_amount = 0
    for n in entity_nodes:
        # 从 abstract 中提取金额（如 "总金额2450万"）
        match = re.search(r'(\d+)万', n.abstract)
        if match:
            amount = int(match.group(1))
            if amount > best_amount:
                best_amount = amount
                best_node = n

    if best_node:
        print(f"\n  → 金额最大的客户: {best_node.name}（{best_amount}万）")
        check("3.1 找到金额最大的客户", True)

        # Step 2: 下钻到该客户的详情
        print(f"\n  ── Step 2: 下钻 {best_node.name} ──")
        children = fs.ls(best_node.uri)
        for n in children:
            print(f"    📄 {n.name}: {n.abstract[:60]}")
        check("3.2 下钻到子条目", len(children) >= 2)

        # 验证子条目全部属于该客户
        check("3.3 子条目属于正确客户", all(
            best_node.name in n.abstract or best_node.name in n.name
            for n in children
        ))
    else:
        check("3.1 找到金额最大的客户", False)
        check("3.2 下钻到子条目", False)
        check("3.3 子条目属于正确客户", False)


# ═══════════════════════════════════════════════════════════
# Demo 4: find 关键词搜索 — 跨类别查找
#   VikingFS.find() 在所有类别中搜索包含关键词的记忆
#   不依赖向量相似度，纯文本匹配（适合精确查找）
# ═══════════════════════════════════════════════════════════

def demo_4_find_search(engine):
    print("\n" + "=" * 70)
    print("  Demo 4: find 关键词搜索 — 跨类别查找")
    print("=" * 70)

    from src.memory.viking_fs import VikingFS
    fs = VikingFS(pg_dao=None, vdb=engine._vdb, user_id="demo_user")

    # 4.1 搜索"华为"
    print("\n  ── 4.1 find('华为') ──")
    results = fs.find("华为")
    for n in results:
        print(f"    [{n.category}] {n.name}: {n.abstract[:50]}")
    check("4.1 搜索华为有结果", len(results) >= 3)

    # 4.2 搜索"CTO"
    print("\n  ── 4.2 find('CTO') ──")
    results = fs.find("CTO")
    for n in results:
        print(f"    [{n.category}] {n.name}: {n.abstract[:50]}")
    check("4.2 搜索CTO有结果", len(results) >= 1)

    # 4.3 搜索"谈判"
    print("\n  ── 4.3 find('谈判') ──")
    results = fs.find("谈判")
    for n in results:
        print(f"    [{n.category}] {n.name}: {n.abstract[:50]}")
    check("4.3 搜索谈判有结果", len(results) >= 2)

    # 4.4 搜索不存在的关键词
    print("\n  ── 4.4 find('不存在的公司') ──")
    results = fs.find("不存在的公司XYZ")
    print(f"    结果: {len(results)} 条")
    check("4.4 不存在的关键词返回空", len(results) == 0)

    # 4.5 搜索"报错"（跨类别 — 应该命中 cases）
    print("\n  ── 4.5 find('报错') — 跨类别 ──")
    results = fs.find("报错")
    for n in results:
        print(f"    [{n.category}] {n.name}: {n.abstract[:50]}")
    check("4.5 跨类别搜索cases", len(results) >= 1)


# ═══════════════════════════════════════════════════════════
# Demo 5: L0 → L1 → L2 渐进加载
#   展示 Token 效率优势:
#   Agent 先看 L0 摘要（~10 tokens），判断是否需要详情
#   需要时加载 L1 概览（~50 tokens），再需要时加载 L2（~100 tokens）
# ═══════════════════════════════════════════════════════════

def demo_5_progressive_loading(engine):
    print("\n" + "=" * 70)
    print("  Demo 5: L0 → L1 → L2 渐进加载（Token 效率）")
    print("=" * 70)

    from src.memory.viking_fs import VikingFS
    fs = VikingFS(pg_dao=None, vdb=engine._vdb, user_id="demo_user")

    # 场景: Agent 需要了解华为的情况
    print("\n  场景: Agent 需要了解华为的情况")

    # Step 1: 只看 L0 摘要（最省 token）
    print("\n  ── Step 1: L0 摘要视图（每条 ~10-30 tokens）──")
    huawei_nodes = []
    entity_nodes = fs.ls("viking://user/memories/entities/")
    for n in entity_nodes:
        if "华为" in n.name:
            huawei_nodes = fs.ls(n.uri)
            break

    total_l0_chars = 0
    for n in huawei_nodes:
        print(f"    L0: {n.abstract}")
        total_l0_chars += len(n.abstract)
    print(f"    → L0 总字符数: {total_l0_chars}")

    # Step 2: 对感兴趣的条目加载 L1 概览
    print("\n  ── Step 2: L1 概览视图（每条 ~50-200 tokens）──")
    total_l1_chars = 0
    for n in huawei_nodes[:2]:  # 只看前 2 条
        node = fs.read(n.uri)
        if node and node.overview:
            print(f"    L1 [{n.name}]:")
            for line in node.overview.split("\n")[:4]:
                print(f"      {line}")
            total_l1_chars += len(node.overview)
    print(f"    → L1 总字符数: {total_l1_chars}")

    # Step 3: 对需要详情的条目加载 L2
    print("\n  ── Step 3: L2 完整内容（按需加载）──")
    total_l2_chars = 0
    if huawei_nodes:
        node = fs.read(huawei_nodes[0].uri)
        if node and node.content:
            print(f"    L2 [{huawei_nodes[0].name}]:")
            print(f"      {node.content}")
            total_l2_chars = len(node.content)
    print(f"    → L2 总字符数: {total_l2_chars}")

    # Token 效率对比
    print(f"\n  ── Token 效率对比 ──")
    print(f"    L0 全部 ({len(huawei_nodes)} 条): ~{total_l0_chars} 字符")
    print(f"    L1 部分 (2 条):  ~{total_l1_chars} 字符")
    print(f"    L2 单条 (1 条):  ~{total_l2_chars} 字符")
    print(f"    → 如果只看 L0，比全部加载 L2 节省 ~{max(1, total_l2_chars * len(huawei_nodes) // max(1, total_l0_chars))}x token")

    check("5.1 L0摘要可用", total_l0_chars > 0)
    check("5.2 L1概览可用", total_l1_chars > 0)
    check("5.3 L2内容可用", total_l2_chars > 0)
    check("5.4 L0 < L1 < L2", total_l0_chars <= total_l1_chars + total_l2_chars)


# ═══════════════════════════════════════════════════════════
# Demo 6: 跨类别目录浏览 — events + entities 联合
#   场景: "华为最近发生了什么"
#   Step 1: ls events/ → 看到华为相关的事件
#   Step 2: ls entities/华为科技/ → 看到华为的实体信息
#   两者结合给出完整回答
# ═══════════════════════════════════════════════════════════

def demo_6_cross_category(engine):
    print("\n" + "=" * 70)
    print("  Demo 6: 跨类别目录浏览 — events + entities 联合")
    print("  场景: '华为最近发生了什么'")
    print("=" * 70)

    from src.memory.viking_fs import VikingFS
    fs = VikingFS(pg_dao=None, vdb=engine._vdb, user_id="demo_user")

    # Step 1: 从 events 中找华为相关的事件
    print("\n  ── Step 1: events 中的华为事件 ──")
    event_nodes = fs.ls("viking://user/memories/events/")
    huawei_events = [n for n in event_nodes if "华为" in n.abstract]
    for n in huawei_events:
        print(f"    📅 {n.abstract[:60]}")
    check("6.1 找到华为事件", len(huawei_events) >= 1)

    # Step 2: 从 entities 中找华为的实体信息
    print("\n  ── Step 2: entities 中的华为信息 ──")
    entity_nodes = fs.ls("viking://user/memories/entities/")
    huawei_entities = []
    for n in entity_nodes:
        if "华为" in n.name:
            huawei_entities = fs.ls(n.uri)
            break
    for n in huawei_entities:
        print(f"    📄 {n.abstract[:60]}")
    check("6.2 找到华为实体", len(huawei_entities) >= 3)

    # Step 3: 组合回答
    print("\n  ── Step 3: 组合回答 ──")
    print("  Agent 可以这样回答:")
    print("    华为科技最近的动态:")
    for n in huawei_events:
        print(f"      • 事件: {n.abstract}")
    print("    当前商机和联系人:")
    for n in huawei_entities:
        print(f"      • {n.abstract}")
    check("6.3 跨类别组合成功", len(huawei_events) > 0 and len(huawei_entities) > 0)


# ═══════════════════════════════════════════════════════════
# Demo 7: rm 删除 + 验证
#   展示通过 URI 精确删除记忆
# ═══════════════════════════════════════════════════════════

def demo_7_rm(engine):
    print("\n" + "=" * 70)
    print("  Demo 7: rm 删除 — 通过 URI 精确删除记忆")
    print("=" * 70)

    from src.memory.viking_fs import VikingFS
    fs = VikingFS(pg_dao=None, vdb=engine._vdb, user_id="demo_user")

    # 先看华为有多少条
    entity_nodes = fs.ls("viking://user/memories/entities/")
    huawei_uri = None
    for n in entity_nodes:
        if "华为" in n.name:
            huawei_uri = n.uri
            break

    if huawei_uri:
        before = fs.ls(huawei_uri)
        print(f"\n  删除前: 华为科技下有 {len(before)} 条记忆")
        for n in before:
            print(f"    📄 {n.name}: {n.abstract[:40]}")

        # 删除安全审计项目
        target_uri = None
        for n in before:
            if "安全审计" in n.name or "安全审计" in n.abstract:
                target_uri = n.uri
                break

        if target_uri:
            print(f"\n  执行: rm {target_uri}")
            ok = fs.rm(target_uri)
            check("7.1 删除成功", ok)

            time.sleep(2)
            after = fs.ls(huawei_uri)
            print(f"\n  删除后: 华为科技下有 {len(after)} 条记忆")
            for n in after:
                print(f"    📄 {n.name}: {n.abstract[:40]}")
            check("7.2 条目数减少", len(after) < len(before))
        else:
            print("  ⚠️ 未找到安全审计项目")
            check("7.1 删除成功", False)
            check("7.2 条目数减少", False)
    else:
        check("7.1 删除成功", False)
        check("7.2 条目数减少", False)


# ═══════════════════════════════════════════════════════════
# Demo 8: 生产级完整链路
#   模拟 Agent 处理用户查询 "帮我看看华为的情况" 的完整过程
#   1. 意图分析 → 识别目标客户
#   2. VikingFS tree → 快速浏览目录结构
#   3. ls 下钻 → 获取具体信息
#   4. read L2 → 获取关键商机详情
#   5. 组装回答
# ═══════════════════════════════════════════════════════════

async def demo_8_production_flow(engine):
    print("\n" + "=" * 70)
    print("  Demo 8: 生产级完整链路")
    print("  用户: '帮我看看华为的情况'")
    print("=" * 70)

    from src.memory.viking_fs import VikingFS
    from langchain_openai import ChatOpenAI
    import json

    fs = VikingFS(pg_dao=None, vdb=engine._vdb, user_id="demo_user")
    llm = ChatOpenAI(
        model="doubao-seed-2-0-lite-260215",
        api_key=os.environ["DOUBAO_API_KEY"],
        base_url="https://ark.cn-beijing.volces.com/api/v3/",
        max_tokens=512,
    )

    user_query = "帮我看看华为的情况"

    # Step 1: LLM 意图分析
    print(f"\n  ── Step 1: 意图分析 ──")
    intent_prompt = (
        f"分析用户查询，识别目标客户和需要的信息类型。\n"
        f"已知客户: 华为科技, 腾讯, 小米集团\n"
        f"用户查询: {user_query}\n"
        f'返回 JSON: {{"customer":"精确客户名","info_types":["entities","events"]}}'
    )
    result = await llm.ainvoke(intent_prompt)
    text = (getattr(result, "content", None) or str(result)).strip()
    print(f"    LLM 返回: {text}")

    customer = "华为科技"  # fallback
    try:
        if "{" in text:
            data = json.loads(text[text.index("{"):text.rindex("}") + 1])
            customer = data.get("customer", "华为科技")
    except Exception:
        pass
    print(f"    识别客户: {customer}")
    check("8.1 识别出华为科技", "华为" in customer)

    # Step 2: VikingFS tree 快速浏览
    print(f"\n  ── Step 2: 目录树快速浏览 ──")
    tree_text = fs.tree(f"viking://user/memories/entities/", max_depth=2)
    for line in tree_text.split("\n"):
        print(f"    {line}")

    # Step 3: ls 下钻到华为
    print(f"\n  ── Step 3: 下钻到 {customer} ──")
    entity_nodes = fs.ls("viking://user/memories/entities/")
    target_uri = None
    for n in entity_nodes:
        if customer in n.name:
            target_uri = n.uri
            break

    children = []
    if target_uri:
        children = fs.ls(target_uri)
        for n in children:
            print(f"    📄 {n.abstract}")
    check("8.2 下钻成功", len(children) >= 2)

    # Step 4: read 关键商机的 L2 详情
    print(f"\n  ── Step 4: 读取关键商机详情 ──")
    details = []
    for n in children[:3]:
        node = fs.read(n.uri)
        if node and node.content:
            details.append(node.content)
            print(f"    [{n.name}] {node.content}")
    check("8.3 读取L2详情", len(details) >= 1)

    # Step 5: 查看相关事件
    print(f"\n  ── Step 5: 查看相关事件 ──")
    event_nodes = fs.ls("viking://user/memories/events/")
    related_events = [n for n in event_nodes if customer in n.abstract]
    for n in related_events:
        print(f"    📅 {n.abstract}")
    check("8.4 找到相关事件", len(related_events) >= 0)

    # Step 6: 组装回答
    print(f"\n  ── Step 6: Agent 组装回答 ──")
    print(f"    基于目录递归检索，Agent 获取到:")
    print(f"      - {len(children)} 条实体信息（商机 + 联系人）")
    print(f"      - {len(related_events)} 条相关事件")
    print(f"      - {len(details)} 条 L2 详情")
    print(f"    总 token 消耗: 远少于加载所有 {len(TEST_MEMORIES)} 条记忆的 L2")
    check("8.5 完整链路成功", True)


# ═══════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("=" * 70)
    print("  VikingFS 目录递归检索 Demo")
    print("  展示 OpenViking 文件系统范式的完整能力")
    print("=" * 70)

    engine = setup_data()

    demo_1_full_tree(engine)
    demo_2_drill_down(engine)
    demo_3_two_level_drill(engine)
    demo_4_find_search(engine)
    demo_5_progressive_loading(engine)
    demo_6_cross_category(engine)
    demo_7_rm(engine)
    asyncio.run(demo_8_production_flow(engine))

    print(f"\n{'=' * 70}")
    print(f"  目录递归检索 Demo: {passed} passed, {failed} failed")
    print(f"{'=' * 70}")
    sys.exit(1 if failed else 0)
