"""长期记忆端到端验证 — 模拟真实多轮对话场景

场景：
  Session 1: 用户查询客户数据，表达偏好 "我喜欢用表格展示"
  Session 2: 用户查询商机数据（新 session），验证：
    - 上一轮的任务历史被检索到
    - 用户偏好 "表格展示" 被检索到并注入
    - 客户实体信息被检索到
  Session 3: 用户再次查询，验证记忆积累效果

全链路：FTSMemoryEngine → MemoryStorage(FTS5) → MemoryMiddleware → SystemMessage 注入
"""
import asyncio
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from langchain_core.messages import HumanMessage, AIMessage, ToolMessage, SystemMessage

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


async def test_full_memory_lifecycle():
    """完整记忆生命周期：写入 → 检索 → 注入 → 积累"""
    print("\n📦 1. 完整记忆生命周期")

    tmp = tempfile.mkdtemp()
    try:
        from src.memory.storage import MemoryStorage
        from src.memory.fts_engine import FTSMemoryEngine
        from src.middleware.memory import MemoryMiddleware, MemoryDimension

        storage = MemoryStorage(storage_dir=tmp)
        engine = FTSMemoryEngine(storage=storage, llm=None)  # 无 LLM，纯规则
        mw = MemoryMiddleware(engine=engine, enabled=True)

        # ═══ Session 1: 用户查询客户，表达偏好 ═══
        print("\n  --- Session 1: 查询客户 + 表达偏好 ---")

        session1_messages = [
            HumanMessage(content="我喜欢用表格展示数据，帮我查一下客户列表"),
            AIMessage(content="", tool_calls=[{"id": "tc1", "name": "query_data", "args": {"entity": "account"}}]),
            ToolMessage(content="查到 5 个客户：华为科技、腾讯、比亚迪、招商银行、阿里巴巴", tool_call_id="tc1", name="query_data"),
            AIMessage(content="| 客户名 | 行业 | 营收 |\n|---|---|---|\n| 华为科技 | 通信 | 8809亿 |\n| 腾讯 | 互联网 | 6090亿 |"),
        ]

        # 模拟 aafter_agent 触发记忆提取
        extract_result = await engine.extract_and_update(
            session1_messages, thread_id="session-1", user_id="user-001"
        )

        check("Session 1 提取到记忆", len(extract_result.items) > 0)
        dimensions = [item.dimension.value for item in extract_result.items]
        check("提取到 task_history", "task_history" in dimensions)
        check("提取到 user_profile（偏好表格）", "user_profile" in dimensions)
        check("提取到 customer_context（华为/腾讯）", "customer_context" in dimensions)

        # 验证持久化
        count = storage.count("user-001")
        check(f"持久化 {count} 条记忆", count >= 3)

        # ═══ Session 2: 新 session，查询商机 ═══
        print("\n  --- Session 2: 新 session 查询商机 ---")

        # 模拟 abefore_agent 检索记忆（用户问商机，但记忆中有客户信息）
        # 真实场景中 rewrite_query 会从上下文提取关键词
        # 这里直接用包含历史关键词的查询
        retrieve_result = await engine.retrieve(
            query="客户 数据 查询",
            user_id="user-001",
            top_k=5,
        )

        check("Session 2 检索到历史记忆", len(retrieve_result.items) > 0)

        # 检查检索到的内容
        all_content = " ".join(item.content for item in retrieve_result.items)
        check("检索到客户信息", "客户" in all_content or "华为" in all_content or "腾讯" in all_content)

        # 模拟 MemoryMiddleware 注入
        memory_text = mw._format_memory(retrieve_result)
        check("生成记忆注入文本", memory_text is not None and len(memory_text) > 0)
        if memory_text:
            check("注入文本包含 memory_context 标签", "memory_context" in memory_text)

        # Session 2 的对话
        session2_messages = [
            HumanMessage(content="帮我分析一下商机 Pipeline，按阶段统计"),
            AIMessage(content="", tool_calls=[{"id": "tc2", "name": "analyze_data", "args": {"group_by": "stage"}}]),
            ToolMessage(content="closing: 18万, negotiation: 148万, proposal: 107万", tool_call_id="tc2", name="analyze_data"),
            AIMessage(content="Pipeline 分析：closing 阶段 18万，negotiation 阶段 148万，建议重点推进 negotiation。"),
        ]

        extract_result2 = await engine.extract_and_update(
            session2_messages, thread_id="session-2", user_id="user-001"
        )
        check("Session 2 提取到记忆", len(extract_result2.items) > 0)

        # ═══ Session 3: 验证记忆积累 ═══
        print("\n  --- Session 3: 验证记忆积累 ---")

        total_count = storage.count("user-001")
        check(f"总记忆 {total_count} 条（两个 session 积累）", total_count >= 4)

        # 检索应该能找到两个 session 的内容
        retrieve_all = await engine.retrieve(
            query="客户 商机 分析",
            user_id="user-001",
            top_k=10,
        )
        check("跨 session 检索", len(retrieve_all.items) >= 2)

        # 按维度查询
        profile_items = storage.get_by_user("user-001", dimension="user_profile")
        check("用户画像持久化", len(profile_items) >= 1)
        if profile_items:
            check("画像包含表格偏好", "表格" in profile_items[0]["content"])

        task_items = storage.get_by_user("user-001", dimension="task_history")
        check("任务历史持久化", len(task_items) >= 2)

        customer_items = storage.get_by_user("user-001", dimension="customer_context")
        check("客户上下文持久化", len(customer_items) >= 1)

        storage.close()
    finally:
        shutil.rmtree(tmp)


async def test_query_rewrite():
    """查询改写 — 多轮对话上下文理解"""
    print("\n📦 2. 查询改写（规则模式）")

    tmp = tempfile.mkdtemp()
    try:
        from src.memory.storage import MemoryStorage
        from src.memory.fts_engine import FTSMemoryEngine

        storage = MemoryStorage(storage_dir=tmp)
        engine = FTSMemoryEngine(storage=storage, llm=None)

        # 多轮对话：用户先问张三，再问 "他的商机"
        messages = [
            HumanMessage(content="帮我查一下张三的客户信息"),
            AIMessage(content="张三是华为科技的销售总监"),
            HumanMessage(content="他的商机有哪些"),
        ]

        rewritten = await engine.rewrite_query(messages, "他的商机有哪些")
        check("改写后包含关键词", len(rewritten) > 0)
        # 规则模式下应该提取到 "张三" "客户" "商机" 等关键词
        check("改写后长度合理", len(rewritten) < 200)

        storage.close()
    finally:
        shutil.rmtree(tmp)


async def test_dedup_task_history():
    """任务历史去重 — 同 thread 只保留最新"""
    print("\n📦 3. 任务历史去重")

    tmp = tempfile.mkdtemp()
    try:
        from src.memory.storage import MemoryStorage
        from src.memory.fts_engine import FTSMemoryEngine

        storage = MemoryStorage(storage_dir=tmp)
        engine = FTSMemoryEngine(storage=storage, llm=None)

        # 同一个 thread 执行两次
        msgs1 = [HumanMessage(content="查客户"), AIMessage(content="查到 5 个")]
        msgs2 = [HumanMessage(content="查客户详情"), AIMessage(content="华为科技详情...")]

        await engine.extract_and_update(msgs1, thread_id="thread-A", user_id="u1")
        count1 = len(storage.get_by_user("u1", dimension="task_history"))

        await engine.extract_and_update(msgs2, thread_id="thread-A", user_id="u1")
        count2 = len(storage.get_by_user("u1", dimension="task_history"))

        check(f"第一次写入 {count1} 条", count1 == 1)
        check(f"第二次仍然 {count2} 条（去重）", count2 == 1)

        # 不同 thread 不去重
        msgs3 = [HumanMessage(content="查商机"), AIMessage(content="查到 7 个")]
        await engine.extract_and_update(msgs3, thread_id="thread-B", user_id="u1")
        count3 = len(storage.get_by_user("u1", dimension="task_history"))
        check(f"不同 thread 累加到 {count3} 条", count3 == 2)

        storage.close()
    finally:
        shutil.rmtree(tmp)


async def test_time_decay():
    """时间衰减 — 近期记忆权重更高"""
    print("\n📦 4. 时间衰减检索")

    tmp = tempfile.mkdtemp()
    try:
        import time
        from src.memory.storage import MemoryStorage
        from src.memory.fts_engine import FTSMemoryEngine

        storage = MemoryStorage(storage_dir=tmp)
        engine = FTSMemoryEngine(storage=storage, llm=None)

        # 写入一条 "旧" 记忆（手动设置 created_at 为 30 天前）
        conn = storage._ensure_db()
        old_time = time.time() - 30 * 86400
        conn.execute(
            "INSERT INTO memories (user_id, dimension, content, metadata, created_at) VALUES (?, ?, ?, ?, ?)",
            ("u1", "task_history", "旧记忆：30天前查询了客户数据", "{}", old_time),
        )
        conn.execute(
            "INSERT INTO memory_fts (user_id, dimension, content, metadata, created_at) VALUES (?, ?, ?, ?, ?)",
            ("u1", "task_history", "旧记忆：30天前查询了客户数据", "{}", str(old_time)),
        )
        conn.commit()

        # 写入一条 "新" 记忆
        storage.add("u1", "新记忆：刚才查询了客户数据", dimension="task_history")

        # 检索
        result = await engine.retrieve("客户数据", user_id="u1", top_k=2)
        check("检索到 2 条", len(result.items) == 2)

        if len(result.items) == 2:
            # 新记忆应该排在前面（confidence 更高）
            new_item = next((i for i in result.items if "新记忆" in i.content), None)
            old_item = next((i for i in result.items if "旧记忆" in i.content), None)
            check("新记忆存在", new_item is not None)
            check("旧记忆存在", old_item is not None)
            if new_item and old_item:
                check("新记忆 confidence > 旧记忆", new_item.confidence > old_item.confidence)

        storage.close()
    finally:
        shutil.rmtree(tmp)


async def test_debounce_integration():
    """防抖队列集成 — 高频写入合并"""
    print("\n📦 5. 防抖队列集成")

    tmp = tempfile.mkdtemp()
    try:
        from src.memory.storage import MemoryStorage
        from src.memory.fts_engine import FTSMemoryEngine

        storage = MemoryStorage(storage_dir=tmp)
        engine = FTSMemoryEngine(storage=storage, llm=None, debounce_seconds=0.1)

        # 快速提交 3 次到防抖队列
        engine.submit_for_extraction("thread-1", [
            HumanMessage(content="查客户"), AIMessage(content="5 个"),
        ])
        engine.submit_for_extraction("thread-1", [
            HumanMessage(content="查商机"), AIMessage(content="7 个"),
        ])
        engine.submit_for_extraction("thread-1", [
            HumanMessage(content="查联系人"), AIMessage(content="12 个"),
        ])

        check("pending 合并", engine._queue.pending_count("thread-1") == 6)

        # 手动 flush
        await engine._queue.flush("thread-1")
        check("flush 后无 pending", not engine._queue.has_pending("thread-1"))
        check("flush_count", engine._queue.flush_count == 1)

        storage.close()
    finally:
        shutil.rmtree(tmp)


async def test_memory_prompt_injection():
    """记忆提示词注入 — 验证 MemoryMiddleware 生成的 SystemMessage"""
    print("\n📦 6. 记忆提示词注入格式")

    tmp = tempfile.mkdtemp()
    try:
        from src.memory.storage import MemoryStorage
        from src.memory.fts_engine import FTSMemoryEngine
        from src.memory.prompt import build_memory_prompt, MemoryChunk

        storage = MemoryStorage(storage_dir=tmp)

        # 写入多维度记忆
        storage.add("u1", "用户偏好中文回复，喜欢表格展示", dimension="user_profile")
        storage.add("u1", "华为科技是 VIP 客户，年营收 8809 亿", dimension="customer_context")
        storage.add("u1", "上次查询了 5 个客户和 7 个商机", dimension="task_history")

        engine = FTSMemoryEngine(storage=storage, llm=None)

        # 检索
        result = await engine.retrieve("客户 商机", user_id="u1", top_k=5)
        check("检索到多维度记忆", len(result.items) >= 2)

        # 验证不同维度
        dims = set(item.dimension.value for item in result.items)
        check("包含多个维度", len(dims) >= 2)

        # 构建提示词
        short_term = storage.read_file("u1")  # 文件模式的短期记忆
        long_term = [MemoryChunk(id=str(i), content=item.content)
                     for i, item in enumerate(result.items)]
        prompt = build_memory_prompt(short_term=short_term, long_term_results=long_term)

        if long_term:
            check("提示词包含 long_term_memory 标签", "long_term_memory" in prompt)
            check("提示词包含实际内容", "客户" in prompt or "华为" in prompt)

        storage.close()
    finally:
        shutil.rmtree(tmp)


if __name__ == "__main__":
    asyncio.run(test_full_memory_lifecycle())
    asyncio.run(test_query_rewrite())
    asyncio.run(test_dedup_task_history())
    asyncio.run(test_time_decay())
    asyncio.run(test_debounce_integration())
    asyncio.run(test_memory_prompt_injection())

    print(f"\n{'='*60}")
    print(f"  长期记忆端到端验证: {passed} passed, {failed} failed")
    print(f"{'='*60}")
    sys.exit(1 if failed else 0)
