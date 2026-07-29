#!/usr/bin/env python3
"""多轮对话模拟 — 验证 AG-UI Chat 接口的 recall_context 正常工作

测试场景：
  1. 模拟 5+ 轮对话（前几轮包含大量业务数据），让上下文压缩触发
  2. 在后续轮次追问前面轮次的详细内容
  3. 验证 LLM 主动调用 recall_context 工具
  4. 验证恢复的原文数据与原始数据一致

运行方式：
  # 方式 1：需要启动服务器（默认 http://localhost:8001）
  .venv/bin/python test_recall_context_multiturn.py --live

  # 方式 2：直接调用 adapter（不需要 HTTP 服务器）
  .venv/bin/python test_recall_context_multiturn.py --direct

  # 方式 3：只测试 ContextArchive 存档 + 检索（单元级）
  .venv/bin/python test_recall_context_multiturn.py --unit

环境变量：
  AGENT_BASE_URL  — AG-UI 服务地址（默认 http://localhost:8001）
  DEEPSEEK_API_KEY — LLM API Key
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
import uuid
from typing import Any

sys.path.insert(0, os.path.dirname(__file__))

# 加载 .env
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(__file__), ".env"), override=False)
except ImportError:
    pass


# ═══════════════════════════════════════════════════════════
# 配置
# ═══════════════════════════════════════════════════════════

BASE_URL = os.environ.get("AGENT_BASE_URL", "http://localhost:8001")
THREAD_ID = f"test-recall-{uuid.uuid4().hex[:8]}"

# 多轮对话场景数据
CONVERSATIONS = [
    # ── 轮次 1: 查询客户概览 ──
    {
        "message": "帮我查一下 PT Sentosa 这个客户的详细信息",
        "description": "首轮：查询客户基本信息",
        "expected_contains": [],  # 首轮不检查
    },
    # ── 轮次 2: 包含大量数据的报价场景 ──
    {
        "message": "针对 PT Sentosa，生成一份报价方案。他们需要 CRM 标准版 50 个用户，制造业模块 30 个用户。年付折扣 15%，付款条件是签约付 30%、上线付 40%、验收付 30%。合同期 2 年。",
        "description": "轮次2：生成包含详细数据的报价",
        "expected_contains": [],
    },
    # ── 轮次 3: 竞品分析 ──
    {
        "message": "PT Sentosa 目前也在看 Odoo 和 Salesforce，帮我做一下竞品分析。Odoo 报价 $24.90/user/月，Salesforce Enterprise 是 $165/user/月。",
        "description": "轮次3：竞品价格对比",
        "expected_contains": [],
    },
    # ── 轮次 4: 实施计划 ──
    {
        "message": "确定方案后，给我一份实施计划。分三期：第一期 4 周做基础 CRM 上线（客户管理+商机管理），第二期 3 周做制造业模块对接（BOM+MRP），第三期 2 周做数据迁移和培训。每期结束有验收里程碑。",
        "description": "轮次4：详细实施计划",
        "expected_contains": [],
    },
    # ── 轮次 5: 讨论其他话题（填充对话）──
    {
        "message": "Q3 还有哪些重点商机需要跟进？帮我列出签约概率 > 60% 的 Top5。",
        "description": "轮次5：商机列表（填充上下文）",
        "expected_contains": [],
    },
    # ── 轮次 6: 继续填充 ──
    {
        "message": "农业银行那个项目进展怎么样了？上周他们提了一个定制需求，要支持多法人实体的权限隔离。帮我评估下开发工作量。",
        "description": "轮次6：其他客户讨论（继续填充）",
        "expected_contains": [],
    },
    # ── 轮次 7: 再次填充 ──
    {
        "message": "帮我生成本周工作周报，涵盖：1）PT Sentosa 报价已完成 2）农业银行定制需求评估中 3）Q3 商机跟进优先级已排定",
        "description": "轮次7：周报生成（继续填充上下文）",
        "expected_contains": [],
    },
    # ═══ 轮次 8+: 追问之前的具体内容 → 应触发 recall_context ═══
    {
        "message": "之前 PT Sentosa 报价方案里的具体付款条件是什么？签约付多少、上线付多少？",
        "description": "🔍 轮次8：追问轮次2的付款条件详情 → 验证 recall_context",
        "expected_contains": ["30%", "40%", "签约", "上线", "验收"],
        "verify_recall": True,
    },
    {
        "message": "之前做竞品分析的时候，Odoo 和 Salesforce 的具体价格是多少？",
        "description": "🔍 轮次9：追问轮次3的竞品价格 → 验证 recall_context",
        "expected_contains": ["24.90", "165"],
        "verify_recall": True,
    },
]


# ═══════════════════════════════════════════════════════════
# 方式 1: HTTP 请求调用（--live）
# ═══════════════════════════════════════════════════════════

async def test_live():
    """通过 HTTP 请求调用 /api/chat/agui 接口"""
    import httpx

    print(f"\n{'═' * 70}")
    print(f"  多轮对话测试 — AG-UI Chat HTTP 模式")
    print(f"  服务地址: {BASE_URL}")
    print(f"  Thread ID: {THREAD_ID}")
    print(f"{'═' * 70}\n")

    results = []

    async with httpx.AsyncClient(timeout=120.0) as client:
        for i, turn in enumerate(CONVERSATIONS, 1):
            print(f"\n{'─' * 60}")
            print(f"  轮次 {i}: {turn['description']}")
            print(f"  用户: {turn['message'][:80]}...")
            print(f"{'─' * 60}")

            # 调用 AG-UI Chat 接口
            response = await client.post(
                f"{BASE_URL}/api/chat/agui",
                json={
                    "threadId": THREAD_ID,
                    "message": turn["message"],
                },
                headers={"Accept": "text/event-stream"},
            )

            if response.status_code != 200:
                print(f"  ❌ HTTP {response.status_code}: {response.text[:200]}")
                results.append({"turn": i, "success": False, "error": f"HTTP {response.status_code}"})
                continue

            # 解析 SSE 事件流
            events = _parse_sse_response(response.text)
            turn_result = _analyze_events(events, turn, i)
            results.append(turn_result)

            # 打印结果摘要
            _print_turn_result(turn_result)

            # 轮次间间隔（给上下文压缩留时间）
            if i < len(CONVERSATIONS):
                await asyncio.sleep(1.0)

    _print_summary(results)


# ═══════════════════════════════════════════════════════════
# 方式 2: 直接调用 adapter（--direct）
# ═══════════════════════════════════════════════════════════

async def test_direct():
    """直接调用 NeoAgentV2Adapter.execute_agui()"""
    print(f"\n{'═' * 70}")
    print(f"  多轮对话测试 — Direct Adapter 模式")
    print(f"  Thread ID: {THREAD_ID}")
    print(f"{'═' * 70}\n")

    from src.agents.adapter import neo_agent_v2_adapter

    results = []

    for i, turn in enumerate(CONVERSATIONS, 1):
        print(f"\n{'─' * 60}")
        print(f"  轮次 {i}: {turn['description']}")
        print(f"  用户: {turn['message'][:80]}...")
        print(f"{'─' * 60}")

        events = []
        try:
            async for event in neo_agent_v2_adapter.execute_agui(
                thread_id=THREAD_ID,
                user_input=turn["message"],
            ):
                events.append(event)
        except Exception as e:
            print(f"  ❌ 执行异常: {type(e).__name__}: {e}")
            results.append({"turn": i, "success": False, "error": str(e)})
            continue

        # 分析事件流
        turn_result = _analyze_agui_events(events, turn, i)
        results.append(turn_result)

        _print_turn_result(turn_result)

        # 轮次间间隔
        if i < len(CONVERSATIONS):
            await asyncio.sleep(0.5)

    _print_summary(results)


# ═══════════════════════════════════════════════════════════
# 方式 3: 单元测试 ContextArchive + RecallContextTool（--unit）
# ═══════════════════════════════════════════════════════════

async def test_unit():
    """纯单元测试：验证 ContextArchive 存档/检索 + RecallContextTool 逻辑

    ContextArchive 已迁移到纯 VDB 架构（dense + BM25 hybrid_search）。
    本测试 mock VDB 层和 Embedding 层，使用内存存储验证核心逻辑链路。
    """
    print(f"\n{'═' * 70}")
    print(f"  recall_context 单元测试（不依赖完整 Agent 链路）")
    print(f"{'═' * 70}\n")

    from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
    from src.middleware.context_archive import ContextArchive

    # ═══ Mock VDB + Embedding 层：内存模拟向量检索 ═══
    _vdb_store: list[dict] = []  # 所有写入的记录

    class MockEmbedding:
        """Mock embedding — 返回固定长度的伪向量"""
        def embed_query(self, text: str) -> list[float]:
            # 简单 hash → 伪向量（用于模拟，不做真正语义匹配）
            import hashlib
            h = hashlib.md5(text.encode()).hexdigest()
            return [int(h[i:i+2], 16) / 255.0 for i in range(0, 32, 2)]

    class MockVDB:
        """Mock VDB — 内存存储 + BM25 关键词匹配模拟"""
        def upsert(self, records: list[dict]) -> None:
            _vdb_store.extend(records)

        def hybrid_search(self, vector, query_text: str, top_k: int = 5,
                          filter_expr: str = None, dense_weight: float = 0.6,
                          sparse_weight: float = 0.4) -> list[dict]:
            """模拟 BM25 检索 — 基于关键词匹配计算 score"""
            candidates = _vdb_store
            # 应用 filter（简单解析 thread_id）
            if filter_expr:
                import re
                m = re.search(r'thread_id\s*=\s*"([^"]+)"', filter_expr)
                if m:
                    tid = m.group(1)
                    candidates = [r for r in candidates if r.get("thread_id") == tid]

            # BM25 模拟: query_text 分词 → 匹配 abstract 字段
            query_tokens = set(query_text.lower().split())
            # 加入中文字符级别匹配
            cn_chars = set(c for c in query_text if '\u4e00' <= c <= '\u9fa5')

            scored = []
            for record in candidates:
                abstract = (record.get("abstract", "") or "").lower()
                user_query = (record.get("user_query", "") or "").lower()
                answer = (record.get("answer_preview", "") or "").lower()
                searchable = f"{abstract} {user_query} {answer}"

                # 计算匹配 score
                score = 0.0
                for token in query_tokens:
                    if token and token in searchable:
                        score += 0.3
                for ch in cn_chars:
                    if ch in searchable:
                        score += 0.05
                # 完整子串匹配加分
                if query_text.lower() in searchable:
                    score += 0.5

                if score > 0:
                    record_copy = dict(record)
                    record_copy["score"] = min(score, 1.0)
                    scored.append(record_copy)

            scored.sort(key=lambda x: x["score"], reverse=True)
            return scored[:top_k]

        def query_by_filter(self, filter_expr: str, limit: int = 1) -> list[dict]:
            """按 filter 精确查询"""
            import re
            # 支持 id = "xxx" 和 thread_id = "xxx" 过滤
            id_match = re.search(r'id\s*=\s*"([^"]+)"', filter_expr)
            thread_match = re.search(r'thread_id\s*=\s*"([^"]+)"', filter_expr)

            results = []
            for record in _vdb_store:
                if id_match and record.get("id") == id_match.group(1):
                    results.append(record)
                elif thread_match and record.get("thread_id") == thread_match.group(1):
                    results.append(record)
            return results[:limit]

        def delete(self, ids: list[str]) -> None:
            nonlocal _vdb_store
            _vdb_store = [r for r in _vdb_store if r.get("id") not in ids]

    passed = 0
    failed = 0

    def check(name: str, condition: bool, detail: str = ""):
        nonlocal passed, failed
        if condition:
            print(f"  ✅ {name}")
            passed += 1
        else:
            print(f"  ❌ {name} — {detail}")
            failed += 1

    try:
        # ── 测试 1: 索引建立 ──
        print("\n▶ 测试 1: ContextArchive 消息索引建立")

        archive = ContextArchive(tenant_id=1)
        thread_id = f"unit-test-{uuid.uuid4().hex[:8]}"

        # 注入 Mock VDB + Embedding（绕过延迟初始化）
        archive._vdb = MockVDB()
        archive._vdb_init_attempted = True
        archive._embedding = MockEmbedding()

        archive.set_context(tenant_id=1, thread_id=thread_id)

        # 模拟 3 轮对话消息
        messages = [
            # 轮次 1
            HumanMessage(content="帮我查 PT Sentosa 的客户信息"),
            AIMessage(content="", tool_calls=[{"id": "tc1", "name": "query_data", "args": {"entity": "account", "filter": "name=PT Sentosa"}}]),
            ToolMessage(content='{"name": "PT Sentosa", "industry": "制造业", "size": "200人", "revenue": "$5M"}', tool_call_id="tc1", name="query_data"),
            AIMessage(content="PT Sentosa 是一家制造业客户，规模 200 人，年营收约 $5M。"),

            # 轮次 2
            HumanMessage(content="生成报价方案：CRM 标准版 50 用户，年付折扣 15%，付款条件签约 30%+上线 40%+验收 30%"),
            AIMessage(content="", tool_calls=[{"id": "tc2", "name": "analyze_data", "args": {"action": "generate_quote"}}]),
            ToolMessage(content='{"total": "$45,000", "discount": "15%", "final": "$38,250", "payment_terms": "30%签约+40%上线+30%验收"}', tool_call_id="tc2", name="analyze_data"),
            AIMessage(content="报价方案已生成：CRM 标准版 50 用户，总价 $45,000，年付 15% 折扣后 $38,250。付款条件：签约付 30%（$11,475）、上线付 40%（$15,300）、验收付 30%（$11,475）。"),

            # 轮次 3
            HumanMessage(content="对比一下 Odoo 的价格，他们报价 $24.90/user/月"),
            AIMessage(content="竞品对比：Odoo 报价 $24.90/user/月，50 用户年费约 $14,940。我们的方案虽然总价更高，但包含制造业模块和专业实施服务。"),
        ]

        added = archive.index_messages(messages, thread_id=thread_id)
        check("索引建立: 3 轮对话", added == 3, f"实际 {added} 轮")

        # ── 测试 2: 精确 turn_id 检索 ──
        print("\n▶ 测试 2: 按 turn_id 精确检索")

        results = archive.search("turn:2", top_k=1)
        check("turn:2 精确检索命中", len(results) == 1, f"命中 {len(results)} 条")
        if results:
            check("turn:2 包含报价内容", "报价" in results[0].user_query or "报价" in results[0].answer_preview,
                  f"query={results[0].user_query[:50]}")

        # ── 测试 3: 关键词检索 ──
        print("\n▶ 测试 3: 按关键词检索")

        results = archive.search("PT Sentosa 付款条件", top_k=3)
        check("关键词搜索命中", len(results) > 0, "无命中结果")
        if results:
            # 应该命中轮次 2（包含付款条件）
            has_payment = any("付款" in r.answer_preview or "30%" in r.answer_preview for r in results)
            check("搜索结果包含付款条件", has_payment,
                  f"结果: {[r.answer_preview[:50] for r in results]}")

        # ── 测试 4: 实体搜索 ──
        print("\n▶ 测试 4: 按实体名检索")

        results = archive.search("PT Sentosa 报价", top_k=3)
        check("实体搜索命中", len(results) > 0, "无命中结果")
        if results:
            has_sentosa = any("PT Sentosa" in r.user_query or "Sentosa" in r.original_messages_json for r in results)
            check("结果包含 PT Sentosa", has_sentosa)

        # ── 测试 5: 原文恢复 ──
        print("\n▶ 测试 5: 原文恢复（从 original_messages_json）")

        results = archive.search("turn:2", top_k=1)
        if results:
            entry = results[0]
            check("原文 JSON 非空", bool(entry.original_messages_json))
            if entry.original_messages_json:
                original = json.loads(entry.original_messages_json)
                check("原文消息条数正确", len(original) == 4, f"实际 {len(original)} 条")
                # 验证工具结果是否完整保留
                tool_results = [m for m in original if m.get("role") == "tool"]
                has_full_data = any("$38,250" in (m.get("content", "") or "") for m in tool_results)
                check("工具结果原文包含完整数据 ($38,250)", has_full_data)
        else:
            check("turn:2 查询成功", False, "未命中")

        # ── 测试 6: RecallContextTool 集成 ──
        print("\n▶ 测试 6: RecallContextTool 工具调用")

        from src.tools.builtins.recall_context_tool import RecallContextTool
        from src.middleware.context_archive_service import ContextArchiveService

        # RecallContextTool 需要 archive_service（非 archive 本身）
        archive_service = ContextArchiveService(archive)
        tool = RecallContextTool(archive_service=archive_service)

        result = await tool._arun(query="PT Sentosa 付款条件")
        check("recall_context 返回非空", bool(result))
        check("recall_context 包含'历史存档'或'轮次'", "历史存档" in result or "轮次" in result,
              f"结果前 100 字: {result[:100]}")
        check("recall_context 包含付款数据", "30%" in result or "38,250" in result,
              f"结果前 200 字: {result[:200]}")

        # ── 测试 7: 数据时效性标注 ──
        print("\n▶ 测试 7: 数据时效性标注")

        results = archive.search("turn:2", top_k=1)
        if results:
            age_desc = archive.get_data_age_description(results[0])
            check("时效性描述非空", bool(age_desc))
            is_stale = archive.is_data_likely_stale(results[0])
            check("新数据不应标记为过时", not is_stale,
                  f"时效: {age_desc}, stale={is_stale}")

        # ── 测试 8: 无存档时的优雅处理 ──
        print("\n▶ 测试 8: 无存档时的优雅处理")

        empty_archive = ContextArchive(tenant_id=1)
        empty_archive._vdb = MockVDB()  # 空的 VDB
        empty_archive._vdb_init_attempted = True
        empty_archive._embedding = MockEmbedding()
        empty_archive.set_context(tenant_id=1, thread_id="nonexistent-thread")
        empty_service = ContextArchiveService(empty_archive)
        empty_tool = RecallContextTool(archive_service=empty_service)
        empty_result = await empty_tool._arun(query="任意查询")
        check("无存档返回友好提示", "没有" in empty_result or "未找到" in empty_result,
              f"结果: {empty_result[:80]}")

        # ── 测试 9: Odoo 关键词检索 ──
        print("\n▶ 测试 9: Odoo 竞品价格检索")

        result = await tool._arun(query="Odoo 价格")
        check("recall_context Odoo 返回非空", bool(result))
        check("recall_context 包含 Odoo 价格", "24.90" in result or "Odoo" in result,
              f"结果前 200 字: {result[:200]}")

        # ── 测试 10: turn_id 精确恢复 ──
        print("\n▶ 测试 10: turn:1 精确恢复（客户信息）")

        result = await tool._arun(query="turn:1", mode="full", turn_id=1)
        check("turn:1 恢复非空", bool(result))
        check("turn:1 包含 PT Sentosa", "Sentosa" in result or "制造业" in result,
              f"结果前 200 字: {result[:200]}")

    except Exception as e:
        import traceback
        print(f"\n  ❌ 测试异常: {type(e).__name__}: {e}")
        traceback.print_exc()
        failed += 1

    # ── 汇总 ──
    print(f"\n{'═' * 70}")
    print(f"  单元测试结果: ✅ {passed} 通过 / ❌ {failed} 失败 / 共 {passed + failed}")
    print(f"{'═' * 70}\n")

    return failed == 0


# ═══════════════════════════════════════════════════════════
# 辅助函数
# ═══════════════════════════════════════════════════════════

def _parse_sse_response(text: str) -> list[dict]:
    """解析 SSE 文本为事件列表"""
    events = []
    current_event_type = None
    current_data_lines = []

    for line in text.split("\n"):
        if line.startswith("event: "):
            current_event_type = line[7:].strip()
        elif line.startswith("data: "):
            current_data_lines.append(line[6:])
        elif line == "" and current_event_type:
            data_str = "\n".join(current_data_lines)
            try:
                data = json.loads(data_str)
            except json.JSONDecodeError:
                data = {"raw": data_str}
            events.append({"type": current_event_type, "data": data})
            current_event_type = None
            current_data_lines = []

    return events


def _analyze_events(events: list[dict], turn: dict, turn_idx: int) -> dict:
    """分析 HTTP SSE 事件流"""
    result = {
        "turn": turn_idx,
        "description": turn["description"],
        "success": True,
        "event_count": len(events),
        "text_content": "",
        "tool_calls": [],
        "has_recall_context": False,
        "recall_context_result": "",
        "expected_match": [],
    }

    for event in events:
        t = event["type"]
        d = event["data"]

        if t == "TEXT_MESSAGE_CONTENT":
            result["text_content"] += d.get("delta", "")
        elif t == "TOOL_CALL_START":
            tool_name = d.get("tool_call_name", "") or d.get("name", "")
            result["tool_calls"].append(tool_name)
            if tool_name == "recall_context":
                result["has_recall_context"] = True
        elif t == "TOOL_CALL_RESULT":
            content = d.get("content", "")
            if "历史存档" in content or "轮次" in content:
                result["recall_context_result"] = content
        elif t == "RUN_ERROR":
            result["success"] = False
            result["error"] = d.get("message", "")

    # 验证预期内容
    full_text = result["text_content"] + result["recall_context_result"]
    for expected in turn.get("expected_contains", []):
        if expected in full_text:
            result["expected_match"].append((expected, True))
        else:
            result["expected_match"].append((expected, False))

    # 验证 recall_context 调用（如果标记了）
    if turn.get("verify_recall"):
        if not result["has_recall_context"]:
            # recall_context 未被调用但内容仍然正确 = 上下文未被压缩（正常情况）
            if all(m[1] for m in result["expected_match"]):
                result["recall_not_needed"] = True
            else:
                result["recall_expected_but_missing"] = True

    return result


def _analyze_agui_events(events: list, turn: dict, turn_idx: int) -> dict:
    """分析 adapter 直接产出的 AGUIEvent 对象"""
    result = {
        "turn": turn_idx,
        "description": turn["description"],
        "success": True,
        "event_count": len(events),
        "text_content": "",
        "tool_calls": [],
        "has_recall_context": False,
        "recall_context_result": "",
        "expected_match": [],
    }

    for event in events:
        t_val = getattr(event.type, "value", None) or str(event.type)
        data = event.data if hasattr(event, "data") else {}

        if t_val == "TEXT_MESSAGE_CONTENT":
            result["text_content"] += data.get("delta", "")
        elif t_val == "TOOL_CALL_START":
            tool_name = data.get("tool_call_name", "") or data.get("name", "")
            result["tool_calls"].append(tool_name)
            if tool_name == "recall_context":
                result["has_recall_context"] = True
        elif t_val == "TOOL_CALL_RESULT":
            content = data.get("content", "")
            if "历史存档" in content or "轮次" in content:
                result["recall_context_result"] = content
        elif t_val == "RUN_ERROR":
            result["success"] = False
            result["error"] = data.get("message", "")

    # 验证预期内容
    full_text = result["text_content"] + result["recall_context_result"]
    for expected in turn.get("expected_contains", []):
        if expected in full_text:
            result["expected_match"].append((expected, True))
        else:
            result["expected_match"].append((expected, False))

    if turn.get("verify_recall"):
        if not result["has_recall_context"]:
            if all(m[1] for m in result["expected_match"]):
                result["recall_not_needed"] = True
            else:
                result["recall_expected_but_missing"] = True

    return result


def _print_turn_result(result: dict):
    """打印单轮结果"""
    status = "✅" if result["success"] else "❌"
    print(f"\n  {status} 事件数: {result['event_count']}")
    print(f"     文本长度: {len(result['text_content'])} 字符")

    if result["tool_calls"]:
        print(f"     工具调用: {result['tool_calls']}")

    if result.get("has_recall_context"):
        print(f"     🔍 recall_context 已触发！")
        if result["recall_context_result"]:
            print(f"     恢复内容(前 200 字): {result['recall_context_result'][:200]}")

    if result.get("recall_not_needed"):
        print(f"     ℹ️  上下文未压缩，recall_context 不需要（数据仍在窗口内）")

    if result.get("recall_expected_but_missing"):
        print(f"     ⚠️  预期 recall_context 但未调用，且数据验证不通过")

    if result.get("expected_match"):
        for keyword, matched in result["expected_match"]:
            mark = "✓" if matched else "✗"
            print(f"     {mark} 预期包含 '{keyword}': {'是' if matched else '否'}")

    # 打印回复摘要
    if result["text_content"]:
        preview = result["text_content"][:200].replace("\n", " ")
        print(f"     回复摘要: {preview}...")


def _print_summary(results: list[dict]):
    """打印测试总结"""
    print(f"\n\n{'═' * 70}")
    print(f"  测试总结")
    print(f"{'═' * 70}")

    total = len(results)
    success = sum(1 for r in results if r["success"])
    recall_triggered = sum(1 for r in results if r.get("has_recall_context"))
    recall_not_needed = sum(1 for r in results if r.get("recall_not_needed"))

    print(f"\n  总轮次: {total}")
    print(f"  成功: {success}/{total}")
    print(f"  recall_context 触发次数: {recall_triggered}")
    if recall_not_needed:
        print(f"  recall_context 未需要（数据仍在窗口）: {recall_not_needed}")

    # 验证结果
    verify_turns = [r for r in results if any(kw for kw, _ in r.get("expected_match", []))]
    if verify_turns:
        print(f"\n  验证轮次详情:")
        for r in verify_turns:
            all_matched = all(m[1] for m in r["expected_match"])
            status = "✅" if all_matched else "⚠️"
            print(f"    {status} 轮次 {r['turn']}: {r['description']}")
            for kw, matched in r["expected_match"]:
                print(f"       {'✓' if matched else '✗'} '{kw}'")

    # 最终判定
    print(f"\n{'─' * 70}")
    if recall_triggered > 0:
        print("  ✅ recall_context 工具在多轮对话中被正常调用")
        print("     → 上下文压缩 + 存档 + 检索恢复链路验证通过")
    elif recall_not_needed == len(verify_turns):
        print("  ℹ️  所有追问轮次的数据仍在上下文窗口内（未触发压缩）")
        print("     → 需要更多轮次或更大数据量来触发压缩")
        print("     → 建议使用 --unit 模式单独测试存档+检索逻辑")
    else:
        print("  ⚠️  recall_context 未被触发，且部分预期内容未匹配")
        print("     → 可能原因: 1) LLM 未主动调用工具 2) 上下文未压缩 3) 工具未注册")
    print(f"{'═' * 70}\n")


# ═══════════════════════════════════════════════════════════
# 入口
# ═══════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="AG-UI Chat 多轮对话 + recall_context 验证")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--live", action="store_true", help="HTTP 模式（需要服务器运行）")
    group.add_argument("--direct", action="store_true", help="直接调用 adapter（无需 HTTP）")
    group.add_argument("--unit", action="store_true", help="单元测试 ContextArchive + RecallContextTool")
    args = parser.parse_args()

    if args.live:
        asyncio.run(test_live())
    elif args.direct:
        asyncio.run(test_direct())
    elif args.unit:
        asyncio.run(test_unit())


if __name__ == "__main__":
    main()
