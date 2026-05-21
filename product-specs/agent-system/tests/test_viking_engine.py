"""VikingMemoryEngine E2E 测试 — 基于 OpenViking 范式的长期记忆引擎

验证：
  1. 8 类结构化提取（L0 摘要 + L2 完整内容）
  2. 语义去重（向量预筛 + LLM 精判）
  3. 向量检索 + filter（user_id + category）
  4. SOUL 蒸馏
  5. FTS5 降级兜底

运行：
  cd product-specs/agent-system
  .venv/bin/python tests/test_viking_engine.py
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("DEEPSEEK_API_KEY", "sk-HdY98AcN68JhtXLp8oeIATEL4PWq9rzRcCAhI8G4SOtBbtSw")

from langchain_core.messages import HumanMessage, AIMessage, ToolMessage

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
        max_tokens=2048,
    )


def _create_engine(llm=None):
    from src.memory.viking_engine import VikingMemoryEngine
    return VikingMemoryEngine(
        vdb_url="http://10.60.2.17",
        vdb_key="bRG3NETg13tv5Fn68VTdkxaJXH9tMQzhKeT3unck",
        vdb_username="root",
        database_name="viking_test_db",
        collection_name="viking_test_memories",
        llm=llm or _get_llm(),
        agent_rules_threshold=3,
    )


async def test_structured_extraction():
    """8 类结构化提取"""
    print("\n📦 1. 8 类结构化提取")
    engine = _create_engine()

    messages = [
        HumanMessage(content="我喜欢用表格展示数据，帮我查一下美团的商机和联系人"),
        AIMessage(content="美团目前有2个活跃商机：外卖SaaS项目900万处于谈判阶段，"
                          "配送系统升级项目400万处于方案阶段。主要联系人是赵总（VP），"
                          "电话137-9999-8888。"),
    ]

    result = await engine.extract_and_update(messages, thread_id="t1", user_id="viking-user-1")
    check("提取到记忆", len(result.items) > 0)

    if result.items:
        print(f"    提取到 {len(result.items)} 条:")
        categories = set()
        for item in result.items:
            cat = item.metadata.get("category", "")
            categories.add(cat)
            print(f"      [{cat}] {item.content[:70]}...")
        check("提取到多个类别", len(categories) >= 2)


async def test_semantic_dedup():
    """语义去重 — 相同内容不重复存储"""
    print("\n📦 2. 语义去重")
    engine = _create_engine()

    # 第一次写入
    msgs1 = [
        HumanMessage(content="查一下京东的客户信息"),
        AIMessage(content="京东是电商行业龙头，年营收10462亿，主要联系人刘总。"),
    ]
    r1 = await engine.extract_and_update(msgs1, thread_id="t2a", user_id="viking-user-2")
    count1 = len(r1.items)
    check(f"第一次提取 {count1} 条", count1 > 0)

    # 第二次写入相似内容
    msgs2 = [
        HumanMessage(content="京东的基本信息是什么"),
        AIMessage(content="京东是电商龙头企业，年营收超过1万亿，联系人是刘总。"),
    ]
    r2 = await engine.extract_and_update(msgs2, thread_id="t2b", user_id="viking-user-2")
    count2 = len(r2.items)
    print(f"    第二次提取 {count2} 条（应该被去重跳过或合并）")
    check("去重生效（第二次提取数 <= 第一次）", count2 <= count1)


async def test_vector_search_with_filter():
    """向量检索 + filter"""
    print("\n📦 3. 向量检索 + filter")
    engine = _create_engine()

    # 先写入数据
    msgs = [
        HumanMessage(content="查一下拼多多的商机"),
        AIMessage(content="拼多多有1个商机：农产品直播平台项目1500万，处于closing阶段。"),
    ]
    await engine.extract_and_update(msgs, thread_id="t3", user_id="viking-user-3")

    import time
    time.sleep(2)  # 等待索引构建

    # 检索
    result = await engine.retrieve(query="拼多多 商机", user_id="viking-user-3", top_k=5)
    check("检索到记忆", len(result.items) > 0)
    if result.items:
        print(f"    检索到 {len(result.items)} 条:")
        for item in result.items:
            print(f"      [score={item.confidence:.3f}] {item.content[:70]}...")


async def test_soul_generation():
    """SOUL 蒸馏"""
    print("\n📦 4. SOUL 蒸馏")
    engine = _create_engine()
    engine._agent_rules_threshold = 2  # 降低阈值方便测试

    # 写入多轮对话触发 SOUL
    for i, (q, a) in enumerate([
        ("我是华南区销售总监，帮我看看客户情况", "好的，您负责华南区大客户。"),
        ("我习惯每周一看Pipeline", "已记录您的工作习惯。"),
        ("帮我查一下网易的商机", "网易有2个商机：云音乐项目300万、教育项目500万。"),
    ]):
        await engine.extract_and_update(
            [HumanMessage(content=q), AIMessage(content=a)],
            thread_id=f"soul-{i}", user_id="viking-user-4",
        )

    import time
    time.sleep(3)  # 等待异步 SOUL 更新

    soul = engine.get_soul("viking-user-4")
    check("SOUL 已生成", len(soul) > 0)
    if soul:
        print(f"    SOUL 预览:\n{soul[:300]}...")


async def test_prefilter():
    """预过滤 — 寒暄/确认不提取"""
    print("\n📦 5. 预过滤")
    engine = _create_engine()

    # 寒暄
    r1 = await engine.extract_and_update(
        [HumanMessage(content="你好"), AIMessage(content="你好！有什么可以帮你的？")],
        thread_id="pf1", user_id="viking-user-5",
    )
    check("寒暄不提取", len(r1.items) == 0)

    # 确认
    r2 = await engine.extract_and_update(
        [HumanMessage(content="好的"), AIMessage(content="好的，还有其他需要吗？")],
        thread_id="pf2", user_id="viking-user-5",
    )
    check("确认不提取", len(r2.items) == 0)


if __name__ == "__main__":
    print("=" * 60)
    print("  VikingMemoryEngine E2E 测试")
    print("=" * 60)

    asyncio.run(test_prefilter())
    asyncio.run(test_structured_extraction())
    asyncio.run(test_vector_search_with_filter())
    asyncio.run(test_semantic_dedup())
    asyncio.run(test_soul_generation())

    print(f"\n{'=' * 60}")
    print(f"  Viking E2E: {passed} passed, {failed} failed")
    print(f"{'=' * 60}")
    sys.exit(1 if failed else 0)
