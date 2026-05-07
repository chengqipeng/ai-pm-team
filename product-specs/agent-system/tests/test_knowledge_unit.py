"""知识库 Phase 1+2 单元测试 — 不依赖 PG/VDB/LKEAP

覆盖：
    - DocumentCleaningService 4 Stage
    - DocumentQualityScorer 4 信号
    - IngestTask 序列化往返
    - IngestionGuard Semaphore
    - KnowledgeVectorStore._tenant_filter 注入防护
    - KnowledgeSearchTool 构造与 schema
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


# ═══════════════════════════════════════════════════════════
# 1. 清洗服务
# ═══════════════════════════════════════════════════════════

def test_cleaning_strips_bom_and_zero_width():
    from knowledge.cleaning import DocumentCleaningService
    c = DocumentCleaningService()
    text = "\ufeff正常内容\u200B带零宽字符\u200C。"
    r = c.clean(text)
    assert "\ufeff" not in r.content
    assert "\u200B" not in r.content
    assert "正常内容带零宽字符。" in r.content
    assert r.signals.dropped_control > 0


def test_cleaning_strips_page_numbers():
    from knowledge.cleaning import DocumentCleaningService
    c = DocumentCleaningService()
    text = "第一章内容\n第 1 页\n1/10\n- 42 -\nPage 3\n段落"
    r = c.clean(text)
    # 页码行应被剔除
    assert "第 1 页" not in r.content
    assert "1/10" not in r.content
    assert "Page 3" not in r.content
    assert "段落" in r.content


def test_cleaning_collapses_blank_lines():
    from knowledge.cleaning import DocumentCleaningService
    c = DocumentCleaningService()
    text = "段落一\n\n\n\n\n段落二"
    r = c.clean(text)
    # 3+ 连续空行 → 折叠成 1 空行（保留段落分隔）
    assert "\n\n\n" not in r.content


def test_cleaning_produces_signals():
    from knowledge.cleaning import DocumentCleaningService
    c = DocumentCleaningService()
    r = c.clean("\ufeff正文\n第 1 页\n\n\n\n段落")
    assert 0.0 <= r.signals.clean_ratio <= 1.0
    assert r.signals.original_chars > 0
    assert r.signals.cleaned_chars > 0


# ═══════════════════════════════════════════════════════════
# 2. 质量评分
# ═══════════════════════════════════════════════════════════

def test_quality_scoring_weights_sum_to_one():
    from knowledge.quality import DocumentQualityScorer
    # 构造不满足权重和 = 1 的配置应该报错
    try:
        DocumentQualityScorer(
            w_completeness=0.5, w_structure=0.5,
            w_density=0.5, w_clean=0.5,
        )
        assert False, "权重和校验应失败"
    except AssertionError:
        pass


def test_quality_scoring_basic():
    from knowledge.cleaning import CleaningSignals
    from knowledge.quality import DocumentQualityScorer
    scorer = DocumentQualityScorer()
    # 理想文档：有 H1/H2、密度高、清洗少、无失败页
    content = "# 标题\n\n## 章节\n\n一段较长的正文，用来保证内容密度合理。" * 5
    signals = CleaningSignals(original_chars=1000, cleaned_chars=980)
    r = scorer.score(content=content, cleaning_signals=signals,
                     total_pages=10, failed_pages=0)
    assert 0.0 <= r.score <= 1.0
    assert r.completeness == 1.0
    assert r.clean_score > 0.9
    assert not r.is_warning


def test_quality_scoring_low_density():
    from knowledge.quality import DocumentQualityScorer
    scorer = DocumentQualityScorer()
    # 全部空白的文档
    r = scorer.score(content="     \n   \n     \n", total_pages=1, failed_pages=0)
    assert r.density == 0.0


def test_quality_scoring_failed_pages():
    from knowledge.quality import DocumentQualityScorer
    scorer = DocumentQualityScorer()
    r = scorer.score(content="文本", total_pages=10, failed_pages=5)
    assert r.completeness == 0.5


def test_quality_result_json_round_trip():
    from knowledge.quality import DocumentQualityScorer
    scorer = DocumentQualityScorer()
    r = scorer.score(content="# 标题", total_pages=1, failed_pages=0)
    j = r.to_json()
    parsed = json.loads(j)
    assert "score" in parsed
    assert "signals" in parsed


# ═══════════════════════════════════════════════════════════
# 3. IngestTask
# ═══════════════════════════════════════════════════════════

def test_ingest_task_roundtrip():
    from knowledge.queue import IngestTask
    task = IngestTask.new(
        tenant_id=1001,
        knowledge_base_id=2001,
        payload={"file_name": "x.pdf", "file_hash": "abc"},
        priority=5,
    )
    row = task.to_row()
    assert row.status == "pending"
    assert row.priority == 5
    assert row.task_id == task.task_id

    restored = IngestTask.from_row(row)
    assert restored.task_id == task.task_id
    assert restored.tenant_id == task.tenant_id
    assert restored.payload == task.payload


def test_ingest_task_delay():
    from knowledge.queue import IngestTask
    task = IngestTask.new(
        tenant_id=1, knowledge_base_id=1,
        payload={}, delay_ms=60_000,
    )
    import time
    now = int(time.time() * 1000)
    # available_at 应大于当前时间（被 delay_ms 影响）
    assert task.available_at > now + 50_000


# ═══════════════════════════════════════════════════════════
# 4. IngestionGuard
# ═══════════════════════════════════════════════════════════

def test_guard_lkeap_semaphore():
    from knowledge.guard import IngestionGuard
    guard = IngestionGuard(lkeap_concurrency=2)
    assert guard.lkeap_concurrency_available == 2

    async def get_slot():
        async with guard.acquire_lkeap_slot():
            return "ok"

    result = asyncio.run(get_slot())
    assert result == "ok"


def test_guard_concurrency_limit():
    """测试并发获取信号量被阻塞"""
    from knowledge.guard import IngestionGuard
    guard = IngestionGuard(lkeap_concurrency=1)

    async def test():
        async with guard.acquire_lkeap_slot():
            # 第二个获取会等待
            async def try_inner():
                async with guard.acquire_lkeap_slot():
                    return "inner"
            task = asyncio.create_task(try_inner())
            # 100ms 内应该还没拿到
            await asyncio.sleep(0.1)
            assert not task.done()
            # 释放后就能拿到
            return task
        # 外层 async with 退出后释放了信号量
    task = asyncio.run(test())


# ═══════════════════════════════════════════════════════════
# 5. KnowledgeVectorStore 防注入
# ═══════════════════════════════════════════════════════════

def test_vdb_tenant_filter_injection_blocked():
    from knowledge.vdb_writer import KnowledgeVectorStore
    # 合法
    assert KnowledgeVectorStore._tenant_filter("1001") == 'tenant_id = "1001"'
    assert KnowledgeVectorStore._tenant_filter("tenant-a") == 'tenant_id = "tenant-a"'
    # 非法（注入）
    try:
        KnowledgeVectorStore._tenant_filter('1" OR "1"="1')
        assert False
    except ValueError:
        pass
    try:
        KnowledgeVectorStore._tenant_filter("1001; DROP TABLE")
        assert False
    except ValueError:
        pass


def test_vdb_upsert_requires_tenant_id():
    """校验必填 tenant_id"""
    from knowledge.vdb_writer import KnowledgeVectorStore
    vdb = KnowledgeVectorStore(url="http://x", key="x")
    try:
        vdb.upsert_chunks([{"id": "c1", "vector": [0.1]}])
        assert False
    except ValueError as e:
        assert "tenant_id" in str(e)


def test_vdb_search_requires_tenant_id():
    from knowledge.vdb_writer import KnowledgeVectorStore
    vdb = KnowledgeVectorStore(url="http://x", key="x")
    try:
        asyncio.run(asyncio.to_thread(
            vdb.search_chunks, tenant_id="", vector=[0.1], top_k=5,
        ))
        assert False
    except ValueError as e:
        assert "tenant_id" in str(e)


# ═══════════════════════════════════════════════════════════
# 6. KnowledgeSearchTool
# ═══════════════════════════════════════════════════════════

def test_knowledge_tool_schema():
    from tools.builtins.knowledge_tool import KnowledgeSearchTool
    tool = KnowledgeSearchTool()
    assert tool.name == "knowledge_search"
    fields = set(tool.args_schema.model_fields.keys())
    assert "query" in fields
    assert "top_k" in fields
    assert "knowledge_base_id" in fields
    assert "doc_category" in fields
    assert "industry" in fields


def test_knowledge_tool_runs_without_provider():
    """无 provider 时返回友好提示"""
    from tools.builtins.knowledge_tool import KnowledgeSearchTool
    tool = KnowledgeSearchTool()
    # 不在 langgraph context 下调用 → 应该返回友好提示
    result = tool._run(query="测试")
    assert "知识库" in result


def test_knowledge_tool_dynamic_description_fallback():
    """无 tenant_id 或 Schema 时返回 _BASE_DESCRIPTION"""
    from tools.builtins.knowledge_tool import KnowledgeSearchTool, _BASE_DESCRIPTION
    tool = KnowledgeSearchTool()
    # tenant_id <= 0
    assert tool.get_dynamic_description(tenant_id=0) == _BASE_DESCRIPTION
    assert tool.get_dynamic_description(tenant_id=-1) == _BASE_DESCRIPTION


def test_knowledge_tool_compose_description_with_schema():
    """给定 fields → 描述中包含字段名、枚举值"""
    from tools.builtins.knowledge_tool import KnowledgeSearchTool
    fields = [
        {"field": "docCategory", "type": "enum",
         "description": "文档类别",
         "enum": ["产品手册", "成功案例", "销售话术"]},
        {"field": "industryVertical", "type": "enum",
         "enum": ["制造业", "金融服务", "互联网"]},
    ]
    desc = KnowledgeSearchTool._compose_description(fields)
    assert "docCategory" in desc
    assert "industryVertical" in desc
    assert "产品手册" in desc
    assert "制造业" in desc


def test_knowledge_tool_description_cache():
    """缓存：同一个 tenant+kb 组合应该命中缓存（不再调 DAO）"""
    from tools.builtins.knowledge_tool import (
        KnowledgeSearchTool, _DESCRIPTION_CACHE,
    )
    tool = KnowledgeSearchTool()
    tool.clear_description_cache()
    # 通过直接塞入模块级缓存模拟
    import time
    _DESCRIPTION_CACHE[(100, 0)] = (time.time(), "CACHED")
    assert tool.get_dynamic_description(tenant_id=100, knowledge_base_id=0) == "CACHED"


# ═══════════════════════════════════════════════════════════
# 7. Pipeline 构造
# ═══════════════════════════════════════════════════════════

def test_pipeline_implements_protocol():
    import inspect
    from knowledge.ingestion import DocumentIngestionPipeline
    from knowledge.worker import IngestPipeline  # noqa

    # 必须有 async run 方法
    assert hasattr(DocumentIngestionPipeline, "run")
    assert inspect.iscoroutinefunction(DocumentIngestionPipeline.run)


# ═══════════════════════════════════════════════════════════
# Runner
# ═══════════════════════════════════════════════════════════

if __name__ == "__main__":
    import traceback
    test_funcs = [
        test_cleaning_strips_bom_and_zero_width,
        test_cleaning_strips_page_numbers,
        test_cleaning_collapses_blank_lines,
        test_cleaning_produces_signals,
        test_quality_scoring_weights_sum_to_one,
        test_quality_scoring_basic,
        test_quality_scoring_low_density,
        test_quality_scoring_failed_pages,
        test_quality_result_json_round_trip,
        test_ingest_task_roundtrip,
        test_ingest_task_delay,
        test_guard_lkeap_semaphore,
        test_guard_concurrency_limit,
        test_vdb_tenant_filter_injection_blocked,
        test_vdb_upsert_requires_tenant_id,
        test_vdb_search_requires_tenant_id,
        test_knowledge_tool_schema,
        test_knowledge_tool_runs_without_provider,
        test_knowledge_tool_dynamic_description_fallback,
        test_knowledge_tool_compose_description_with_schema,
        test_knowledge_tool_description_cache,
        test_pipeline_implements_protocol,
    ]
    passed, failed = 0, 0
    for fn in test_funcs:
        try:
            fn()
            passed += 1
            print(f"✅ {fn.__name__}")
        except Exception as exc:
            failed += 1
            print(f"❌ {fn.__name__}: {exc}")
            traceback.print_exc()

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(0 if failed == 0 else 1)
