"""目录递归检索 Demo — 模拟生产环境的完整链路

生产链路:
  用户查询 → LLM 意图分析（识别 parent_entity + category）→ 向量库精确 filter → 返回结果

不使用任何字符串包含判断，全部依赖:
  1. LLM 输出的 parent_entity（精确实体名）
  2. 向量库的 filter 精确匹配
  3. 向量相似度排序

运行:
  cd product-specs/agent-system
  .venv/bin/python -B tests/test_viking_directory_search.py
  或
  .venv/bin/python -m pytest tests/test_viking_directory_search.py -v -s
"""
import asyncio
import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("DEEPSEEK_API_KEY", "sk-HdY98AcN68JhtXLp8oeIATEL4PWq9rzRcCAhI8G4SOtBbtSw")

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


def _get_llm():
    from langchain_openai import ChatOpenAI
    return ChatOpenAI(
        model="deepseek-v4-flash",
        api_key=os.environ["DEEPSEEK_API_KEY"],
        base_url="https://tokenhub.tencentmaas.com/v1",
        max_tokens=1024,
    )


def _get_emb():
    from langchain_openai import OpenAIEmbeddings
    return OpenAIEmbeddings(
        model="doubao-embedding-text-240715",
        api_key=os.environ.get("EMBEDDING_API_KEY", "651621e7-e495-4728-93ef-ed380e9ddcd1"),
        base_url="https://ark.cn-beijing.volces.com/api/v3/",
        check_embedding_ctx_length=False,
    )


# ═══════════════════════════════════════════════════════════
# 生产级意图分析 Prompt
# ═══════════════════════════════════════════════════════════

DIRECTORY_INTENT_PROMPT = """你是 CRM 系统的查询分析器。分析用户查询，识别目标实体和查询类型。

## 已知客户列表
{known_customers}

## 输出要求
1. parent_entity: 用户查询的目标客户名（必须精确匹配已知客户列表中的名称，如果不确定则为空）
2. category: 目标记忆类别（entities/events/preferences/profile）
3. sub_queries: 1-3 个检索子查询

## 示例
用户: "华为的商机情况" → {{"parent_entity": "华为科技", "category": "entities", "sub_queries": ["华为科技 商机 金额 阶段"]}}
用户: "任正非公司的联系人" → {{"parent_entity": "华为科技", "category": "entities", "sub_queries": ["华为科技 联系人 电话 职位"]}}
用户: "最近有什么重要事件" → {{"parent_entity": "", "category": "events", "sub_queries": ["近期 重要事件 决策 里程碑"]}}
用户: "我的偏好设置" → {{"parent_entity": "", "category": "preferences", "sub_queries": ["用户偏好 设置"]}}

## 用户查询
{query}

返回严格 JSON（不要其他文字）:"""


async def analyze_intent(llm, query: str, known_customers: list[str]) -> dict:
    """生产级意图分析 — LLM 识别 parent_entity + category"""
    prompt = DIRECTORY_INTENT_PROMPT.format(
        known_customers="\n".join(f"- {c}" for c in known_customers),
        query=query,
    )
    result = await llm.ainvoke(prompt)
    text = (getattr(result, "content", None) or str(result)).strip()
    try:
        if "{" in text:
            return json.loads(text[text.index("{"):text.rindex("}") + 1])
    except Exception:
        pass
    return {"parent_entity": "", "category": "", "sub_queries": [query]}


async def directory_search(vdb, emb, uid: str, intent: dict, top_k: int = 5) -> list[dict]:
    """生产级目录式检索 — 根据意图分析结果构建 filter + 向量搜索"""
    all_results = []
    seen_ids = set()

    for sq in intent.get("sub_queries", []):
        vec = emb.embed_query(sq)

        # 构建 filter（精确匹配，不是字符串包含）
        filter_parts = [f'user_id = "{uid}"']
        if intent.get("parent_entity"):
            filter_parts.append(f'parent_entity = "{intent["parent_entity"]}"')
        if intent.get("category"):
            filter_parts.append(f'category = "{intent["category"]}"')
        filter_expr = " and ".join(filter_parts)

        results = vdb.search(vector=vec, top_k=top_k, filter_expr=filter_expr)
        for r in results:
            rid = r.get("id", "")
            if rid and rid not in seen_ids:
                seen_ids.add(rid)
                all_results.append(r)

    # 按 score 排序
    all_results.sort(key=lambda x: x.get("score", 0), reverse=True)
    return all_results[:top_k]


# ═══════════════════════════════════════════════════════════
# 数据准备
# ═══════════════════════════════════════════════════════════

KNOWN_CUSTOMERS = ["华为科技", "腾讯", "小米集团"]

TEST_MEMORIES = [
    # 华为科技（6 条）
    {"category": "entities", "abstract": "华为科技: 通信行业龙头，3个商机总金额780万",
     "content": "华为科技是通信行业龙头企业，当前有3个活跃商机，总金额780万。",
     "merge_key": "华为科技", "parent_entity": ""},
    {"category": "entities", "abstract": "华为科技/ERP升级: 金额500万，谈判阶段",
     "content": "华为科技的ERP升级项目，金额500万，处于谈判阶段，预计下月签约。",
     "merge_key": "华为科技/ERP升级", "parent_entity": "华为科技"},
    {"category": "entities", "abstract": "华为科技/云迁移: 金额200万，方案阶段",
     "content": "华为科技的云迁移项目，金额200万，处于方案阶段。",
     "merge_key": "华为科技/云迁移", "parent_entity": "华为科技"},
    {"category": "entities", "abstract": "华为科技/安全审计: 金额80万，closing阶段",
     "content": "华为科技的安全审计项目，金额80万，处于closing阶段。",
     "merge_key": "华为科技/安全审计", "parent_entity": "华为科技"},
    {"category": "entities", "abstract": "华为科技/张总: 职位CTO，电话139-0001-0001",
     "content": "华为科技联系人张总，职位CTO，电话139-0001-0001。",
     "merge_key": "华为科技/张总", "parent_entity": "华为科技"},
    {"category": "entities", "abstract": "华为科技/李经理: 职位采购总监，电话138-0002-0002",
     "content": "华为科技联系人李经理，职位采购总监，电话138-0002-0002。",
     "merge_key": "华为科技/李经理", "parent_entity": "华为科技"},

    # 腾讯（4 条）
    {"category": "entities", "abstract": "腾讯: 互联网巨头，2个商机总金额2000万",
     "content": "腾讯是互联网巨头，当前有2个活跃商机，总金额2000万。",
     "merge_key": "腾讯", "parent_entity": ""},
    {"category": "entities", "abstract": "腾讯/云服务升级: 金额800万，谈判阶段",
     "content": "腾讯的云服务升级项目，金额800万，处于谈判阶段。",
     "merge_key": "腾讯/云服务升级", "parent_entity": "腾讯"},
    {"category": "entities", "abstract": "腾讯/AI平台: 金额1200万，方案阶段",
     "content": "腾讯的AI平台项目，金额1200万，处于方案阶段。",
     "merge_key": "腾讯/AI平台", "parent_entity": "腾讯"},
    {"category": "entities", "abstract": "腾讯/马总: 职位VP，电话137-0003-0003",
     "content": "腾讯联系人马总，职位VP，电话137-0003-0003。",
     "merge_key": "腾讯/马总", "parent_entity": "腾讯"},

    # 小米集团（4 条）
    {"category": "entities", "abstract": "小米集团: IoT龙头，2个商机总金额2450万",
     "content": "小米集团是IoT行业龙头，当前有2个活跃商机，总金额2450万。",
     "merge_key": "小米集团", "parent_entity": ""},
    {"category": "entities", "abstract": "小米集团/IoT平台: 金额650万，方案阶段",
     "content": "小米集团的IoT平台项目，金额650万，处于方案阶段。",
     "merge_key": "小米集团/IoT平台", "parent_entity": "小米集团"},
    {"category": "entities", "abstract": "小米集团/智能工厂: 金额1800万，谈判阶段",
     "content": "小米集团的智能工厂项目，金额1800万，处于谈判阶段。",
     "merge_key": "小米集团/智能工厂", "parent_entity": "小米集团"},
    {"category": "entities", "abstract": "小米集团/李总: 职位CTO，电话139-0004-0004",
     "content": "小米集团联系人李总，职位CTO，电话139-0004-0004。",
     "merge_key": "小米集团/李总", "parent_entity": "小米集团"},

    # 偏好（2 条）
    {"category": "preferences", "abstract": "数据展示偏好: 表格格式",
     "content": "用户偏好使用表格展示数据。",
     "merge_key": "数据展示偏好", "parent_entity": ""},
    {"category": "preferences", "abstract": "回复风格偏好: 简洁，给结论",
     "content": "用户偏好简洁的回复风格，直接给结论。",
     "merge_key": "回复风格偏好", "parent_entity": ""},

    # 事件（2 条）
    {"category": "events", "abstract": "2026-04-28 华为ERP项目评审通过",
     "content": "2026-04-28与华为张总开会，ERP项目评审通过，预计下周签约。",
     "merge_key": "", "parent_entity": "华为科技"},
    {"category": "events", "abstract": "2026-04-25 腾讯云服务项目启动会",
     "content": "2026-04-25腾讯云服务升级项目启动会，确定了技术方案和时间表。",
     "merge_key": "", "parent_entity": "腾讯"},
]


async def setup_data():
    """写入测试数据"""
    from src.memory.viking_engine import VikingMemoryEngine
    from uuid import uuid4

    engine = VikingMemoryEngine(
        vdb_url="http://10.60.2.17",
        vdb_key="bRG3NETg13tv5Fn68VTdkxaJXH9tMQzhKeT3unck",
        database_name="viking_dir_test_v2",
        collection_name="dir_demo_v2",
        llm=None,
    )
    emb = _get_emb()
    uid = "prod_user"

    print("写入 18 条测试记忆...")
    for m in TEST_MEMORIES:
        vec = emb.embed_query(m["abstract"])
        engine._vdb.upsert([{
            "id": str(uuid4()), "vector": vec,
            "text": m["abstract"], "abstract": m["abstract"],
            "overview": "", "content": m["content"],
            "category": m["category"], "merge_key": m["merge_key"],
            "parent_entity": m["parent_entity"],
            "user_id": uid, "thread_id": "setup",
            "created_at": "2026-04-28T00:00:00+00:00",
            "updated_at": "2026-04-28T00:00:00+00:00",
        }])
    print("等待索引构建...")
    time.sleep(8)
    return engine._vdb, emb, uid


# ═══════════════════════════════════════════════════════════
# Demo 1: 精确客户查询 — "华为的商机情况"
# ═══════════════════════════════════════════════════════════

async def demo_exact_customer(llm, vdb, emb, uid):
    print("\n" + "=" * 60)
    print("  Demo 1: 精确客户查询")
    print("  用户: '华为的商机情况'")
    print("=" * 60)

    # Step 1: LLM 意图分析
    intent = await analyze_intent(llm, "华为的商机情况", KNOWN_CUSTOMERS)
    print(f"\n  LLM 意图分析结果:")
    print(f"    parent_entity: '{intent.get('parent_entity', '')}'")
    print(f"    category: '{intent.get('category', '')}'")
    print(f"    sub_queries: {intent.get('sub_queries', [])}")

    check("1.1 LLM识别出华为科技", intent.get("parent_entity") == "华为科技")
    check("1.2 LLM识别类别entities", intent.get("category") == "entities")

    # Step 2: 目录式检索
    results = await directory_search(vdb, emb, uid, intent, top_k=5)
    print(f"\n  检索结果 ({len(results)} 条):")
    for r in results:
        pe = r.get("parent_entity", "")
        print(f"    [score={r.get('score',0):.3f}] [parent={pe}] {r.get('abstract','')[:60]}")

    check("1.3 有检索结果", len(results) > 0)
    # 验证：所有结果的 parent_entity 都是华为科技（由向量库 filter 保证，不是字符串判断）
    all_correct = all(r.get("parent_entity") == "华为科技" for r in results)
    check("1.4 结果全部属于华为科技（filter保证）", all_correct)
    check("1.5 不包含腾讯或小米", not any(r.get("parent_entity") in ("腾讯", "小米集团") for r in results))


# ═══════════════════════════════════════════════════════════
# Demo 2: 同义词/别名查询 — "任正非公司的销售机会"
# ═══════════════════════════════════════════════════════════

async def demo_synonym_query(llm, vdb, emb, uid):
    print("\n" + "=" * 60)
    print("  Demo 2: 同义词/别名查询")
    print("  用户: '任正非公司的销售机会'")
    print("=" * 60)

    intent = await analyze_intent(llm, "任正非公司的销售机会", KNOWN_CUSTOMERS)
    print(f"\n  LLM 意图分析结果:")
    print(f"    parent_entity: '{intent.get('parent_entity', '')}'")
    print(f"    sub_queries: {intent.get('sub_queries', [])}")

    # LLM 应该能理解"任正非公司"就是"华为科技"
    check("2.1 LLM理解别名→华为科技", intent.get("parent_entity") == "华为科技")

    results = await directory_search(vdb, emb, uid, intent, top_k=5)
    print(f"\n  检索结果 ({len(results)} 条):")
    for r in results:
        print(f"    [score={r.get('score',0):.3f}] {r.get('abstract','')[:60]}")

    check("2.2 有检索结果", len(results) > 0)


# ═══════════════════════════════════════════════════════════
# Demo 3: 多实体查询 — "华为的商机和联系人"
# ═══════════════════════════════════════════════════════════

async def demo_multi_type_query(llm, vdb, emb, uid):
    print("\n" + "=" * 60)
    print("  Demo 3: 多类型查询")
    print("  用户: '华为的商机和联系人'")
    print("=" * 60)

    intent = await analyze_intent(llm, "华为的商机和联系人", KNOWN_CUSTOMERS)
    print(f"\n  LLM 意图分析结果:")
    print(f"    parent_entity: '{intent.get('parent_entity', '')}'")
    print(f"    sub_queries: {intent.get('sub_queries', [])}")

    check("3.1 识别出华为科技", intent.get("parent_entity") == "华为科技")
    check("3.2 生成多个子查询", len(intent.get("sub_queries", [])) >= 2)

    results = await directory_search(vdb, emb, uid, intent, top_k=8)
    print(f"\n  检索结果 ({len(results)} 条):")
    for r in results:
        print(f"    [score={r.get('score',0):.3f}] {r.get('abstract','')[:60]}")

    # 验证同时包含商机和联系人
    abstracts = " ".join(r.get("abstract", "") for r in results)
    check("3.3 包含商机信息", "金额" in abstracts or "阶段" in abstracts)
    check("3.4 包含联系人信息", "职位" in abstracts or "电话" in abstracts)
    check("3.5 全部属于华为", all(r.get("parent_entity") == "华为科技" for r in results))


# ═══════════════════════════════════════════════════════════
# Demo 4: 两级下钻 — "哪个客户的商机金额最大"
# ═══════════════════════════════════════════════════════════

async def demo_two_level_drill(llm, vdb, emb, uid):
    print("\n" + "=" * 60)
    print("  Demo 4: 两级下钻")
    print("  用户: '哪个客户的商机金额最大'")
    print("=" * 60)

    # Step 1: 无特定客户 → 搜索顶层客户汇总（parent_entity 为空）
    intent = await analyze_intent(llm, "哪个客户的商机金额最大", KNOWN_CUSTOMERS)
    print(f"\n  LLM 意图分析:")
    print(f"    parent_entity: '{intent.get('parent_entity', '')}' （应为空，因为问的是所有客户）")

    # 搜索顶层汇总
    vec = emb.embed_query("客户 商机 金额 总额")
    top_results = vdb.search(
        vector=vec, top_k=5,
        filter_expr=f'user_id = "{uid}" and parent_entity = ""',
    )
    print(f"\n  Step 1 — 顶层客户汇总 ({len(top_results)} 条):")
    for r in top_results:
        print(f"    [score={r.get('score',0):.3f}] {r.get('abstract','')[:60]}")

    check("4.1 找到顶层客户汇总", len(top_results) >= 2)

    # Step 2: 选得分最高的客户，下钻查看详情
    if top_results:
        best_customer = top_results[0].get("merge_key", "")
        print(f"\n  Step 2 — 下钻 '{best_customer}' 的子条目:")

        drill_vec = emb.embed_query(f"{best_customer} 商机 详情 金额")
        children = vdb.search(
            vector=drill_vec, top_k=10,
            filter_expr=f'user_id = "{uid}" and parent_entity = "{best_customer}"',
        )
        for r in children:
            print(f"    [score={r.get('score',0):.3f}] {r.get('abstract','')[:60]}")

        check(f"4.2 下钻到{best_customer}子条目", len(children) >= 2)
        check(f"4.3 子条目全属于{best_customer}",
              all(r.get("parent_entity") == best_customer for r in children))


# ═══════════════════════════════════════════════════════════
# Demo 5: 跨类别查询 — "华为最近有什么重要事件"
# ═══════════════════════════════════════════════════════════

async def demo_cross_category(llm, vdb, emb, uid):
    print("\n" + "=" * 60)
    print("  Demo 5: 跨类别查询")
    print("  用户: '华为最近有什么重要事件'")
    print("=" * 60)

    intent = await analyze_intent(llm, "华为最近有什么重要事件", KNOWN_CUSTOMERS)
    print(f"\n  LLM 意图分析:")
    print(f"    parent_entity: '{intent.get('parent_entity', '')}'")
    print(f"    category: '{intent.get('category', '')}'")

    check("5.1 识别出华为科技", intent.get("parent_entity") == "华为科技")
    check("5.2 识别类别events", intent.get("category") == "events")

    results = await directory_search(vdb, emb, uid, intent, top_k=5)
    print(f"\n  检索结果 ({len(results)} 条):")
    for r in results:
        print(f"    [score={r.get('score',0):.3f}] [cat={r.get('category','')}] {r.get('abstract','')[:60]}")

    check("5.3 有检索结果", len(results) > 0)
    # 应该只返回华为的事件，不返回腾讯的事件
    check("5.4 全部属于华为", all(r.get("parent_entity") == "华为科技" for r in results))


# ═══════════════════════════════════════════════════════════
# Demo 6: 无特定客户查询 — "我的偏好设置"
# ═══════════════════════════════════════════════════════════

async def demo_no_customer(llm, vdb, emb, uid):
    print("\n" + "=" * 60)
    print("  Demo 6: 无特定客户查询")
    print("  用户: '我的偏好设置'")
    print("=" * 60)

    intent = await analyze_intent(llm, "我的偏好设置", KNOWN_CUSTOMERS)
    print(f"\n  LLM 意图分析:")
    print(f"    parent_entity: '{intent.get('parent_entity', '')}'")
    print(f"    category: '{intent.get('category', '')}'")

    check("6.1 无特定客户（parent_entity为空）", intent.get("parent_entity", "") == "")
    check("6.2 识别类别preferences", intent.get("category") == "preferences")

    results = await directory_search(vdb, emb, uid, intent, top_k=5)
    print(f"\n  检索结果 ({len(results)} 条):")
    for r in results:
        print(f"    [score={r.get('score',0):.3f}] {r.get('abstract','')[:60]}")

    check("6.3 有检索结果", len(results) > 0)


# ═══════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════

async def main():
    global passed, failed
    print("=" * 60)
    print("  目录递归检索 Demo（生产级链路）")
    print("  LLM 意图分析 → parent_entity 精确 filter → 向量检索")
    print("=" * 60)

    vdb, emb, uid = await setup_data()
    llm = _get_llm()

    await demo_exact_customer(llm, vdb, emb, uid)
    await demo_synonym_query(llm, vdb, emb, uid)
    await demo_multi_type_query(llm, vdb, emb, uid)
    await demo_two_level_drill(llm, vdb, emb, uid)
    await demo_cross_category(llm, vdb, emb, uid)
    await demo_no_customer(llm, vdb, emb, uid)

    print(f"\n{'=' * 60}")
    print(f"  目录递归检索 Demo: {passed} passed, {failed} failed")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    asyncio.run(main())
    sys.exit(1 if failed else 0)


# pytest 兼容入口
import pytest

@pytest.mark.asyncio
async def test_directory_search_all():
    await main()
    assert failed == 0, f"{failed} checks failed"
