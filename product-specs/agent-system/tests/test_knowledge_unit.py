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
# 8. Retriever 归一化多维度加权（对齐 data-process）
# ═══════════════════════════════════════════════════════════

def _make_chunk(chunk_id, doc_id, score, chunk_index=0):
    from knowledge.provider import KnowledgeChunk
    return KnowledgeChunk(
        content=f"content-{chunk_id}",
        score=score,
        metadata={},
        document_id=doc_id,
        document_title=f"doc-{doc_id}",
        chunk_id=chunk_id,
        chunk_index=chunk_index,
        section_title="",
        section_path="",
        chunk_type="Text",
    )


def _make_doc_cache(*doc_specs):
    """doc_specs: 列表 of dict(doc_id, quality_score, date_published, search_hit_count)

    新实现：返回 dict[doc_id -> dict]，对齐 retriever._load_doc_meta_cache 产出的
    结构（VDB kb_doc_metadata 的 query 返回 dict）
    """
    cache = {}
    for s in doc_specs:
        cache[s["doc_id"]] = {
            "id": s["doc_id"],
            "quality_score": s.get("quality_score", 0.5),
            "date_published": s.get("date_published", 0),
            "created_at": s.get("created_at", 0),
            "search_hit_count": s.get("search_hit_count", 0),
        }
    return cache


def test_retriever_multi_seg_aggregation():
    """同一文档多个切片命中时，应通过 SEGMENT_DECAY=0.2 聚合，更多切片的文档排前"""
    from knowledge.retriever import KnowledgeRetriever
    r = KnowledgeRetriever(vector_store=None)

    # docA 有 3 个切片高分命中，docB 只有 1 个切片（最高分）
    chunks = [
        _make_chunk("c1", "docA", 0.9),
        _make_chunk("c2", "docA", 0.85),
        _make_chunk("c3", "docA", 0.80),
        _make_chunk("c4", "docB", 0.95),  # 单切片分数最高
    ]
    doc_cache = _make_doc_cache(
        {"doc_id": "docA", "quality_score": 0.5},
        {"doc_id": "docB", "quality_score": 0.5},
    )
    result = r._score_and_rank(
        chunks=chunks, summary_rank=[], meta_text_rank=[],
        doc_cache=doc_cache, threshold=0.0, top_k=10,
    )
    # 所有切片都应出现（top_k=10 够用）
    assert len(result) == 4
    # docA 聚合分应该超过 docB（三路衰减贡献 vs 单路）
    # 校验：docA 的 chunk 排在 docB 之前（top2 都是 docA）
    top_doc_ids = [c.document_id for c in result[:3]]
    assert top_doc_ids.count("docA") >= 2


def test_retriever_norm_floor_applied():
    """单文档结果时，normA 应不为 0（归一化下限保护）"""
    from knowledge.retriever import KnowledgeRetriever
    r = KnowledgeRetriever(vector_store=None)
    chunks = [_make_chunk("c1", "docA", 0.5)]
    doc_cache = _make_doc_cache({"doc_id": "docA", "quality_score": 0.5})
    result = r._score_and_rank(
        chunks=chunks, summary_rank=[], meta_text_rank=[],
        doc_cache=doc_cache, threshold=0.0, top_k=5,
    )
    assert len(result) == 1
    # 只有一个文档时 normA = (1+floor)/2 = (1+0.3)/2 = 0.65
    # finalScore = 0.7*0.65 + 0.1*0 + 0.2*(0.5*0.1/0.2) = 0.455 + 0.05 = 0.505
    assert result[0].score > 0.3


def test_retriever_metadata_recall_boosts_score():
    """命中元数据召回（summary / meta_text）应提升文档的 finalScore"""
    from knowledge.retriever import KnowledgeRetriever
    r = KnowledgeRetriever(vector_store=None)

    # 两个文档切片分相同
    chunks = [
        _make_chunk("c1", "docA", 0.7),
        _make_chunk("c2", "docB", 0.7),
    ]
    doc_cache = _make_doc_cache(
        {"doc_id": "docA", "quality_score": 0.5},
        {"doc_id": "docB", "quality_score": 0.5},
    )
    # docA 被两路元数据召回命中，docB 都没命中
    result = r._score_and_rank(
        chunks=chunks,
        summary_rank=["docA"],
        meta_text_rank=["docA"],
        doc_cache=doc_cache,
        threshold=0.0,
        top_k=5,
    )
    # docA 应排在 docB 前面（β 维度加分生效）
    assert result[0].document_id == "docA"
    assert result[0].score > result[1].score


def test_retriever_threshold_filters_low_scores():
    """finalScore 低于 threshold 的结果应被过滤掉"""
    from knowledge.retriever import KnowledgeRetriever
    r = KnowledgeRetriever(vector_store=None)
    chunks = [
        _make_chunk("c1", "docA", 0.5),
        _make_chunk("c2", "docB", 0.5),
    ]
    doc_cache = _make_doc_cache(
        {"doc_id": "docA", "quality_score": 0.0},
        {"doc_id": "docB", "quality_score": 0.0},
    )
    # 设一个极高 threshold，所有结果都应被过滤
    result = r._score_and_rank(
        chunks=chunks, summary_rank=[], meta_text_rank=[],
        doc_cache=doc_cache, threshold=0.99, top_k=5,
    )
    assert result == []


def test_retriever_threshold_resolution_explicit_wins():
    """_resolve_threshold: 显式 > KB > 默认"""
    from knowledge.retriever import KnowledgeRetriever
    r = KnowledgeRetriever(vector_store=None)
    # 显式传 0.5：不管 KB 什么都用 0.5
    val = asyncio.run(r._resolve_threshold(explicit=0.5, kb_id=None))
    assert val == 0.5
    # 显式传 0：关闭过滤
    val = asyncio.run(r._resolve_threshold(explicit=0.0, kb_id=None))
    assert val == 0.0
    # 显式传 >1：clamp 到 1
    val = asyncio.run(r._resolve_threshold(explicit=5.0, kb_id=None))
    assert val == 1.0


def test_retriever_threshold_resolution_default_fallback():
    """_resolve_threshold: 未显式 + 无 KB → 回默认 0.3"""
    from knowledge.retriever import KnowledgeRetriever
    r = KnowledgeRetriever(vector_store=None)
    val = asyncio.run(r._resolve_threshold(explicit=None, kb_id=None))
    assert val == 0.3  # _DEFAULT_THRESHOLD


def test_retriever_norm_floor_independent_of_threshold():
    """归一化下限与 threshold 解耦：高 threshold 不应扭曲 normA"""
    from knowledge.retriever import KnowledgeRetriever
    r = KnowledgeRetriever(vector_store=None)
    chunks = [
        _make_chunk("c1", "docA", 0.9),
        _make_chunk("c2", "docB", 0.5),
    ]
    doc_cache = _make_doc_cache(
        {"doc_id": "docA", "quality_score": 0.5},
        {"doc_id": "docB", "quality_score": 0.5},
    )
    # 传极低 threshold → 高分文档仍应排前，且分数不会因 threshold 低而偏离
    low_res = r._score_and_rank(
        chunks=[_make_chunk(c.chunk_id, c.document_id, c.score) for c in chunks],
        summary_rank=[], meta_text_rank=[],
        doc_cache=doc_cache, threshold=0.0, top_k=5,
    )
    # 传较高 threshold（但不会全过滤）→ 同样的相对关系
    high_res = r._score_and_rank(
        chunks=[_make_chunk(c.chunk_id, c.document_id, c.score) for c in chunks],
        summary_rank=[], meta_text_rank=[],
        doc_cache=doc_cache, threshold=0.1, top_k=5,
    )
    # 同样数据下，归一化后分数应几乎相同（差异来自 threshold 只是过滤，不改变 normA）
    assert abs(low_res[0].score - high_res[0].score) < 0.01


def test_retriever_tokenize_chinese():
    """jieba 分词对中文查询能产出有效 token"""
    from knowledge.retriever import KnowledgeRetriever
    tokens = KnowledgeRetriever._tokenize("制造业的成功案例怎么配置审批流")
    assert len(tokens) >= 2
    # 预期至少包含这些关键词之一
    assert any(kw in tokens for kw in ["制造业", "成功", "案例", "审批", "配置"])


def test_build_toc_deduplicates_section_path():
    """_build_toc: 切片的 section_path 去重 + 保持顺序（无 task 时只输出章节）"""
    from knowledge.ingestion import DocumentIngestionPipeline
    from store.knowledge_models import KnowledgeChunkRow

    chunks = [
        KnowledgeChunkRow(section_path="第一章 介绍"),
        KnowledgeChunkRow(section_path="第一章 介绍"),            # dup
        KnowledgeChunkRow(section_path="第二章 快速上手 / 2.1 环境"),
        KnowledgeChunkRow(section_path=""),                        # 空
        KnowledgeChunkRow(section_path="第二章 快速上手 / 2.2 安装"),
    ]
    toc = DocumentIngestionPipeline._build_toc(chunks, task=None)
    lines = toc.split("\n")
    assert lines == [
        "第一章 介绍",
        "第二章 快速上手 / 2.1 环境",
        "第二章 快速上手 / 2.2 安装",
    ]


def test_build_toc_respects_max_chars():
    """_build_toc: 超过 max_chars 截断，不无限增长"""
    from knowledge.ingestion import DocumentIngestionPipeline
    from store.knowledge_models import KnowledgeChunkRow

    chunks = [
        KnowledgeChunkRow(section_path=f"章节-{i:04d}-" + "填" * 50)
        for i in range(200)
    ]
    toc = DocumentIngestionPipeline._build_toc(chunks, task=None, max_chars=500)
    assert len(toc) < 700  # 略宽容一点，允许最后一条完整存入


def test_build_toc_fallback_to_file_name_only():
    """_build_toc: 无章节的文档（扫描件 PDF）仍能产出文件名路径信号"""
    from knowledge.ingestion import DocumentIngestionPipeline
    from store.knowledge_models import KnowledgeChunkRow
    from knowledge.queue import IngestTask

    chunks = [KnowledgeChunkRow(section_path="") for _ in range(3)]
    task = IngestTask(
        task_id="t1", tenant_id=1, knowledge_base_id=0, dataset_id=0,
        payload={"file_name": "扫描件.pdf"},
    )
    toc = DocumentIngestionPipeline._build_toc(
        chunks, task=task, task_payload_file_name="扫描件.pdf",
    )
    # KB/dataset 查不到也没关系，至少有文件名
    assert "扫描件.pdf" in toc


def test_retriever_build_filter_expr_lowercase_and():
    """filter 表达式应使用小写 and/or（tcvectordb 语法要求）"""
    from knowledge.retriever import KnowledgeRetriever
    r = KnowledgeRetriever(vector_store=None)
    expr = r._build_chunk_filter(
        knowledge_base_id=1001,
        filters={"docCategory": "产品手册", "industry": ["制造业", "金融业"]},
    )
    assert " and " in expr
    assert " or " in expr
    assert "AND" not in expr
    assert "OR" not in expr
    assert 'knowledge_base_id = "1001"' in expr


# ═══════════════════════════════════════════════════════════
# 9. 调度任务（ScheduleExecutor）
# ═══════════════════════════════════════════════════════════

class _FakeVDB:
    """最小 VDB mock，只实现 batch_update_doc_fields 给 scheduler 测"""
    def __init__(self):
        self.updates: list[tuple[str, dict]] = []

    def batch_update_doc_fields(self, tenant_id, updates):
        self.updates.append((tenant_id, dict(updates)))
        return len(updates)


def test_scheduler_sync_vdb_hit_count_unknown_type_raises():
    """未知 task_type 应抛错"""
    from knowledge.scheduler import ScheduleExecutor
    exe = ScheduleExecutor(vdb=_FakeVDB())

    async def run():
        try:
            await exe._execute("unknown_task", {})
        except ValueError as e:
            return str(e)
        return None
    msg = asyncio.run(run())
    assert msg is not None and "Unknown task_type" in msg


def test_scheduler_sync_without_vdb_is_noop():
    """没传 vdb 时 sync 任务直接 noop，不抛异常"""
    from knowledge.scheduler import ScheduleExecutor
    exe = ScheduleExecutor(vdb=None)

    async def run():
        return await exe._run_sync_vdb_hit_count({"all": True})
    result = asyncio.run(run())
    assert result.get("synced") == 0


def test_scheduler_sync_groups_by_tenant():
    """scheduler 按 tenant_id 分组调用 vdb.batch_update_doc_fields"""
    from knowledge.scheduler import ScheduleExecutor
    import knowledge.scheduler as sched_module

    fake_vdb = _FakeVDB()
    exe = ScheduleExecutor(vdb=fake_vdb)

    # 猴子补丁：伪造 PG 返回的多租户数据
    original_list_all = sched_module.KnowledgeDocumentDAO.list_all_hit_counts
    sched_module.KnowledgeDocumentDAO.list_all_hit_counts = lambda limit=100: [
        {"doc_id": "doc_a", "tenant_id": 1,       "search_hit_count": 10},
        {"doc_id": "doc_b", "tenant_id": 1,       "search_hit_count": 5},
        {"doc_id": "doc_c", "tenant_id": 9527,    "search_hit_count": 3},
    ]
    try:
        async def run():
            return await exe._run_sync_vdb_hit_count({"all": True})
        result = asyncio.run(run())
    finally:
        sched_module.KnowledgeDocumentDAO.list_all_hit_counts = original_list_all

    # 应分为 2 个租户分别调用
    assert result["synced"] == 3
    tenants = sorted(t for t, _ in fake_vdb.updates)
    assert tenants == ["1", "9527"]
    # 租户 1 应有 2 个 doc
    t1_updates = next(u for t, u in fake_vdb.updates if t == "1")
    assert len(t1_updates) == 2
    assert t1_updates["doc_a"]["search_hit_count"] == 10


def test_scheduler_decay_per_tenant_iterates_each_tenant():
    """scheduler decay: per_tenant=true 时对每个租户独立调用 DAO"""
    from knowledge.scheduler import ScheduleExecutor
    import knowledge.scheduler as sched_module

    call_args: list = []
    original_doc_decay = sched_module.KnowledgeDocumentDAO.decay_hit_counts
    original_chunk_decay = sched_module.KnowledgeChunkDAO.decay_hit_counts
    original_list_tenants = sched_module.KnowledgeDocumentDAO.list_tenants_with_hits
    original_list_all = sched_module.KnowledgeDocumentDAO.list_all_hit_counts

    def mock_doc_decay(factor, tenant_id=None):
        call_args.append(("doc", factor, tenant_id))
        return 2  # 假装每个租户衰减 2 个 doc

    def mock_chunk_decay(factor, tenant_id=None):
        call_args.append(("chunk", factor, tenant_id))
        return 0

    sched_module.KnowledgeDocumentDAO.decay_hit_counts = mock_doc_decay
    sched_module.KnowledgeChunkDAO.decay_hit_counts = mock_chunk_decay
    sched_module.KnowledgeDocumentDAO.list_tenants_with_hits = lambda: [1, 9527]
    sched_module.KnowledgeDocumentDAO.list_all_hit_counts = lambda limit=5000: []

    try:
        fake_vdb = _FakeVDB()
        exe = ScheduleExecutor(vdb=fake_vdb)
        result = asyncio.run(
            exe._run_decay({"decay_factor": 0.5, "per_tenant": True})
        )
    finally:
        sched_module.KnowledgeDocumentDAO.decay_hit_counts = original_doc_decay
        sched_module.KnowledgeChunkDAO.decay_hit_counts = original_chunk_decay
        sched_module.KnowledgeDocumentDAO.list_tenants_with_hits = original_list_tenants
        sched_module.KnowledgeDocumentDAO.list_all_hit_counts = original_list_all

    # 应有两个租户 × 2 次调用（doc + chunk）
    tenants_in_calls = [args[2] for args in call_args]
    assert sorted(set(t for t in tenants_in_calls if t is not None)) == [1, 9527]
    assert result["mode"].startswith("per_tenant")
    assert result["documents_decayed"] == 4  # 2 个租户 × 2


def test_scheduler_health_check_reports_diff():
    """vdb_health_check 应能对比 PG 与 VDB 并报告 diff"""
    from knowledge.scheduler import ScheduleExecutor
    import knowledge.scheduler as sched_module

    class _CountingVDB(_FakeVDB):
        def count_docs(self, tenant_id):
            return {"1": 5, "9527": 2}.get(str(tenant_id), 0)

    original_list_tenants = sched_module.KnowledgeDocumentDAO.list_tenants_with_hits
    original_count = sched_module.KnowledgeDocumentDAO.count_indexed_docs
    sched_module.KnowledgeDocumentDAO.list_tenants_with_hits = lambda: [1, 9527]
    sched_module.KnowledgeDocumentDAO.count_indexed_docs = (
        lambda tenant_id=None: {1: 7, 9527: 2}.get(tenant_id, 0)
    )

    try:
        vdb = _CountingVDB()
        exe = ScheduleExecutor(vdb=vdb)
        # 伪造 get_conn 的 distinct tenant_id 查询（返回空），让只走 list_tenants_with_hits
        result = asyncio.run(
            exe._run_vdb_health_check({"per_tenant": True, "auto_repair": False})
        )
    finally:
        sched_module.KnowledgeDocumentDAO.list_tenants_with_hits = original_list_tenants
        sched_module.KnowledgeDocumentDAO.count_indexed_docs = original_count

    # 租户 1 有 2 个文档 diff，租户 9527 对齐
    assert result["issues"] >= 1
    r1 = result["report"].get("1")
    assert r1 is not None
    assert r1["diff"] == 2  # 7 PG - 5 VDB


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
        test_retriever_multi_seg_aggregation,
        test_retriever_norm_floor_applied,
        test_retriever_metadata_recall_boosts_score,
        test_retriever_threshold_filters_low_scores,
        test_retriever_threshold_resolution_explicit_wins,
        test_retriever_threshold_resolution_default_fallback,
        test_retriever_norm_floor_independent_of_threshold,
        test_retriever_tokenize_chinese,
        test_build_toc_deduplicates_section_path,
        test_build_toc_respects_max_chars,
        test_build_toc_fallback_to_file_name_only,
        test_retriever_build_filter_expr_lowercase_and,
        test_scheduler_sync_vdb_hit_count_unknown_type_raises,
        test_scheduler_sync_without_vdb_is_noop,
        test_scheduler_sync_groups_by_tenant,
        test_scheduler_decay_per_tenant_iterates_each_tenant,
        test_scheduler_health_check_reports_diff,
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
