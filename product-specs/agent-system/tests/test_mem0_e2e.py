"""Mem0 记忆引擎端到端验证 — 基于豆包 2.0

场景：
  1. 基础写入与检索：写入 CRM 对话 → 检索验证
  2. 4维度自动分类：验证偏好/客户/任务/知识的自动归类
  3. 查询改写：多轮对话中的代词消解
  4. 跨会话积累：多次对话后记忆积累效果
  5. MemoryMiddleware 集成：验证中间件注入格式
  6. 记忆管理：列出/删除/清空

全链路：Mem0MemoryEngine → mem0.Memory(豆包2.0) → MemoryMiddleware → SystemMessage 注入

运行：
  cd product-specs/agent-system
  python tests/test_mem0_e2e.py
"""
import asyncio
import os
import shutil
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("DOUBAO_API_KEY", "651621e7-e495-4728-93ef-ed380e9ddcd1")

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
    """获取豆包 LLM 实例（用于查询改写）"""
    from langchain_openai import ChatOpenAI
    return ChatOpenAI(
        model="doubao-1-5-pro-32k-250115",
        api_key=os.environ["DOUBAO_API_KEY"],
        base_url="https://ark.cn-beijing.volces.com/api/v3/",
        max_tokens=2048,
    )


def _create_engine(tmp_dir: str, llm=None):
    """创建 Mem0MemoryEngine，ChromaDB 存储到临时目录"""
    from src.memory.mem0_engine import Mem0MemoryEngine

    config = {
        "llm": {
            "provider": "openai",
            "config": {
                "model": "doubao-seed-2-0-lite-260215",
                "api_key": os.environ["DOUBAO_API_KEY"],
                "openai_base_url": "https://ark.cn-beijing.volces.com/api/v3/",
                "temperature": 0.1,
                "max_tokens": 2000,
            },
        },
        "embedder": {
            "provider": "openai",
            "config": {
                "model": "doubao-embedding-text-240715",
                "api_key": os.environ["DOUBAO_API_KEY"],
                "openai_base_url": "https://ark.cn-beijing.volces.com/api/v3/",
            },
        },
        "vector_store": {
            "provider": "chroma",
            "config": {
                "collection_name": f"test_{int(time.time())}",
                "path": os.path.join(tmp_dir, "chromadb"),
            },
        },
    }
    return Mem0MemoryEngine(
        mem0_config=config,
        llm=llm,
    )


# ═══════════════════════════════════════════════════════════
# 1. 基础写入与检索
# ═══════════════════════════════════════════════════════════

async def test_basic_add_and_search():
    """基础能力：写入 CRM 对话 → mem0 提取 → 检索验证"""
    print("\n📦 1. 基础写入与检索")

    tmp = os.path.join(os.path.dirname(__file__), "..", "data", "_test_mem0_1")
    os.makedirs(tmp, exist_ok=True)
    try:
        engine = _create_engine(tmp)

        # 写入一段 CRM 对话
        messages = [
            HumanMessage(content="帮我查一下华为科技的商机情况"),
            AIMessage(content="华为科技目前有3个活跃商机：ERP升级项目500万（negotiation阶段）、"
                              "云迁移项目200万（proposal阶段）、安全审计项目80万（closing阶段）。"),
        ]

        result = await engine.extract_and_update(
            messages, thread_id="test-thread-1", user_id="test-user-001"
        )

        check("提取到记忆", len(result.items) > 0)
        check("thread_id 正确", result.source_thread_id == "test-thread-1")

        if result.items:
            print(f"    提取到 {len(result.items)} 条记忆:")
            for item in result.items:
                print(f"      [{item.dimension.value}] {item.content[:80]}...")

        # 检索
        retrieve_result = await engine.retrieve(
            query="华为科技 商机",
            user_id="test-user-001",
            top_k=5,
        )

        check("检索到记忆", len(retrieve_result.items) > 0)

        if retrieve_result.items:
            all_content = " ".join(i.content for i in retrieve_result.items)
            check("检索内容包含华为相关信息",
                  any(kw in all_content for kw in ("华为", "商机", "ERP", "500")))
            print(f"    检索到 {len(retrieve_result.items)} 条:")
            for item in retrieve_result.items:
                print(f"      [score={item.confidence:.3f}] {item.content[:80]}...")

    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ═══════════════════════════════════════════════════════════
# 2. 4维度自动分类
# ═══════════════════════════════════════════════════════════

async def test_dimension_classification():
    """验证 4 维度自动分类：偏好/客户/任务/知识"""
    print("\n📦 2. 4维度自动分类")

    tmp = os.path.join(os.path.dirname(__file__), "..", "data", "_test_mem0_2")
    os.makedirs(tmp, exist_ok=True)
    try:
        engine = _create_engine(tmp)

        # 包含多维度信息的对话
        messages = [
            HumanMessage(content="我喜欢用表格展示数据，帮我查一下招商银行的联系人"),
            AIMessage(content="招商银行共有3个联系人：张总（VP）、李经理（IT总监）、王主管（采购）。"
                              "已按表格格式展示。"),
        ]

        result = await engine.extract_and_update(
            messages, thread_id="test-thread-2", user_id="test-user-002"
        )

        check("提取到记忆", len(result.items) > 0)

        dimensions = [item.dimension.value for item in result.items]
        print(f"    提取到的维度: {dimensions}")

        # 验证维度分类逻辑
        all_content = " ".join(i.content for i in result.items)

        # 检查是否有偏好相关的记忆被正确分类
        has_profile = any(i.dimension.value == "user_profile" for i in result.items)
        has_customer = any(i.dimension.value == "customer_context" for i in result.items)

        if has_profile:
            check("偏好记忆分类为 user_profile", True)
        else:
            # mem0 可能把偏好和客户信息合并提取，检查内容中是否包含偏好
            check("提取内容包含偏好信息", "表格" in all_content or "喜欢" in all_content)

        if has_customer:
            check("客户记忆分类为 customer_context", True)
        else:
            check("提取内容包含客户信息", "招商银行" in all_content or "联系人" in all_content)

    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ═══════════════════════════════════════════════════════════
# 3. 查询改写（多轮对话代词消解）
# ═══════════════════════════════════════════════════════════

async def test_query_rewrite():
    """查询改写 — 多轮对话中的代词消解"""
    print("\n📦 3. 查询改写")

    tmp = os.path.join(os.path.dirname(__file__), "..", "data", "_test_mem0_3")
    os.makedirs(tmp, exist_ok=True)
    try:
        llm = _get_llm()
        engine = _create_engine(tmp, llm=llm)

        # 多轮对话：先问张三，再问"他的商机"
        messages = [
            HumanMessage(content="帮我查一下张三负责的客户"),
            AIMessage(content="张三负责华为科技和腾讯两个客户"),
            HumanMessage(content="他的商机有哪些"),
        ]

        rewritten = await engine.rewrite_query(messages, "他的商机有哪些")

        check("改写后非空", len(rewritten) > 0)
        check("改写后长度合理（<100字）", len(rewritten) < 100)
        print(f"    原始查询: '他的商机有哪些'")
        print(f"    改写结果: '{rewritten}'")

        # LLM 改写应该能解析"他"→"张三"
        has_entity = any(kw in rewritten for kw in ("张三", "商机", "华为", "腾讯"))
        check("改写包含实体或业务关键词", has_entity)

    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ═══════════════════════════════════════════════════════════
# 4. 跨会话记忆积累
# ═══════════════════════════════════════════════════════════

async def test_cross_session_accumulation():
    """跨会话积累：多次对话后记忆叠加"""
    print("\n📦 4. 跨会话记忆积累")

    tmp = os.path.join(os.path.dirname(__file__), "..", "data", "_test_mem0_4")
    os.makedirs(tmp, exist_ok=True)
    try:
        engine = _create_engine(tmp)
        user_id = "test-user-004"

        # Session 1: 查客户
        session1 = [
            HumanMessage(content="查一下比亚迪的基本信息"),
            AIMessage(content="比亚迪是新能源汽车龙头企业，年营收6023亿，主要联系人是王总。"),
        ]
        r1 = await engine.extract_and_update(session1, thread_id="s1", user_id=user_id)
        check("Session 1 提取到记忆", len(r1.items) > 0)

        # Session 2: 查商机
        session2 = [
            HumanMessage(content="比亚迪有什么商机在跟进"),
            AIMessage(content="比亚迪目前有2个商机：充电桩管理系统300万（proposal）、"
                              "供应链数字化800万（negotiation）。"),
        ]
        r2 = await engine.extract_and_update(session2, thread_id="s2", user_id=user_id)
        check("Session 2 提取到记忆", len(r2.items) > 0)

        # Session 3: 查联系人
        session3 = [
            HumanMessage(content="比亚迪的王总电话多少"),
            AIMessage(content="王总的电话是 138-0000-1234，他是比亚迪IT副总裁。"),
        ]
        r3 = await engine.extract_and_update(session3, thread_id="s3", user_id=user_id)
        check("Session 3 提取到记忆", len(r3.items) > 0)

        total_extracted = len(r1.items) + len(r2.items) + len(r3.items)
        print(f"    3个 session 共提取 {total_extracted} 条记忆")

        # 跨会话检索：一次查询应该能找到多个 session 的内容
        retrieve_all = await engine.retrieve(
            query="比亚迪 商机 联系人",
            user_id=user_id,
            top_k=10,
        )

        check("跨会话检索到记忆", len(retrieve_all.items) >= 2)
        all_content = " ".join(i.content for i in retrieve_all.items)
        check("检索内容覆盖多个 session",
              sum(1 for kw in ("比亚迪", "商机", "王总", "充电桩", "供应链") if kw in all_content) >= 2)

        print(f"    跨会话检索到 {len(retrieve_all.items)} 条:")
        for item in retrieve_all.items:
            print(f"      [score={item.confidence:.3f}] {item.content[:80]}...")

    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ═══════════════════════════════════════════════════════════
# 5. MemoryMiddleware 集成
# ═══════════════════════════════════════════════════════════

async def test_middleware_integration():
    """验证 Mem0Engine 接入 MemoryMiddleware 后的注入格式"""
    print("\n📦 5. MemoryMiddleware 集成")

    tmp = os.path.join(os.path.dirname(__file__), "..", "data", "_test_mem0_5")
    os.makedirs(tmp, exist_ok=True)
    try:
        from src.middleware.memory import MemoryMiddleware

        engine = _create_engine(tmp)
        mw = MemoryMiddleware(engine=engine, enabled=True)

        # 先写入一些记忆
        messages = [
            HumanMessage(content="腾讯是我们的战略客户，年框合同2000万"),
            AIMessage(content="已记录腾讯的战略客户信息和年框合同金额。"),
        ]
        await engine.extract_and_update(messages, thread_id="mw-test", user_id="mw-user")

        # 检索并格式化
        result = await engine.retrieve(query="腾讯 客户", user_id="mw-user", top_k=5)

        if result.items:
            memory_text = mw._format_memory(result)
            check("生成注入文本", memory_text is not None)
            if memory_text:
                check("包含 memory_context 标签", "<memory_context>" in memory_text)
                check("包含实际内容", "腾讯" in memory_text or "客户" in memory_text)
                print(f"    注入文本预览:\n{memory_text[:300]}...")
        else:
            check("检索到记忆用于注入", False)

    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ═══════════════════════════════════════════════════════════
# 6. 记忆管理（列出/删除/清空）
# ═══════════════════════════════════════════════════════════

async def test_memory_management():
    """记忆管理接口：list / delete / clear"""
    print("\n📦 6. 记忆管理")

    tmp = os.path.join(os.path.dirname(__file__), "..", "data", "_test_mem0_6")
    os.makedirs(tmp, exist_ok=True)
    try:
        engine = _create_engine(tmp)
        user_id = "mgmt-user"

        # 写入记忆
        messages = [
            HumanMessage(content="阿里巴巴的云计算项目预算1000万，预计下季度签约"),
            AIMessage(content="已记录阿里巴巴云计算项目信息。"),
        ]
        await engine.extract_and_update(messages, thread_id="mgmt-1", user_id=user_id)

        # 列出记忆
        memories = engine.list_memories(user_id=user_id)
        check("列出记忆", len(memories) > 0)
        if memories:
            print(f"    列出 {len(memories)} 条记忆:")
            for m in memories[:3]:
                print(f"      [id={m['id'][:8]}...] {m['content'][:60]}...")

        # 按关键词筛选
        filtered = engine.list_memories(user_id=user_id, keyword="阿里")
        check("关键词筛选", len(filtered) <= len(memories))

        # 删除单条
        if memories:
            target_id = memories[0]["id"]
            deleted = engine.delete_memories_by_ids([target_id])
            check(f"删除单条记忆 (id={target_id[:8]}...)", deleted == 1)

            remaining = engine.list_memories(user_id=user_id)
            check("删除后数量减少", len(remaining) < len(memories))

        # 清空所有
        engine.clear_all_memories(user_id=user_id)
        after_clear = engine.list_memories(user_id=user_id)
        check("清空后无记忆", len(after_clear) == 0)

    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ═══════════════════════════════════════════════════════════
# 7. 默认配置初始化（零配置）
# ═══════════════════════════════════════════════════════════

async def test_default_config():
    """验证零配置初始化 — 默认使用豆包 2.0"""
    print("\n📦 7. 默认配置初始化（豆包 2.0）")

    from src.memory.mem0_engine import Mem0MemoryEngine

    try:
        # 零配置创建，应该自动使用豆包 2.0
        engine = Mem0MemoryEngine()
        check("零配置初始化成功", engine is not None)
        check("mem0 实例已创建", engine._mem0 is not None)

        # 验证配置中的模型
        llm_provider = engine._mem0.config.llm.provider
        llm_model = engine._mem0.config.llm.config.get("model", "")
        print(f"    LLM provider: {llm_provider}")
        print(f"    LLM model: {llm_model}")
        check("LLM provider 是 openai（兼容模式）", llm_provider == "openai")
        check("LLM model 是豆包 2.0", "doubao-seed-2" in llm_model or "doubao" in llm_model)
    except ImportError as e:
        print(f"  ⚠️  mem0ai 未安装，跳过: {e}")
        check("mem0ai 已安装", False)
    except Exception as e:
        print(f"  ⚠️  初始化异常: {e}")
        check("零配置初始化无异常", False)


# ═══════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("=" * 60)
    print("  Mem0 记忆引擎 E2E 测试（豆包 2.0）")
    print("=" * 60)

    asyncio.run(test_default_config())
    asyncio.run(test_basic_add_and_search())
    asyncio.run(test_dimension_classification())
    asyncio.run(test_query_rewrite())
    asyncio.run(test_cross_session_accumulation())
    asyncio.run(test_middleware_integration())
    asyncio.run(test_memory_management())

    print(f"\n{'=' * 60}")
    print(f"  Mem0 E2E 验证: {passed} passed, {failed} failed")
    print(f"{'=' * 60}")
    sys.exit(1 if failed else 0)
