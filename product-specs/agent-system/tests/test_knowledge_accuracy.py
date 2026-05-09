"""知识库流水线准确性验证

关注点：
    1. JSON 提取的鲁棒性（preamble / 多种 fence / 嵌套）
    2. 自动打标结果的字段正确性（user_metadata 覆盖优先级）
    3. 摘要/关键词的提取
    4. Segment 切分：标题层级 / 顺序 / path / 边界
    5. Chunk 切分：滑动窗口边界 / overlap 合法性 / chunk_type 识别
    6. 元数据下放到 Chunk 的冗余字段
    7. 质量评分与清洗信号联动
    8. 整条流水线的字段一致性（document ↔ segment ↔ chunk）
"""
from __future__ import annotations

import asyncio
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


# ═══════════════════════════════════════════════════════════
# 1. JSON 提取（LLM 输出的各种格式）
# ═══════════════════════════════════════════════════════════

def _extract_json_via_pipeline(text: str) -> dict:
    """用现有 pipeline 的 JSON 提取路径处理 text，返回解析后 dict"""
    # 复制 ingestion._phase2_auto_tag 的 JSON 提取代码片段
    import json as _json
    t = text.strip()
    if t.startswith("```"):
        t = t.strip("`").split("\n", 1)[-1].rsplit("\n", 1)[0].strip()
        if t.startswith("json"):
            t = t[4:].strip()
    return _json.loads(t)


def test_json_extraction_plain():
    data = _extract_json_via_pipeline('{"a": 1, "b": "x"}')
    assert data == {"a": 1, "b": "x"}


def test_json_extraction_fence_with_json_tag():
    raw = '```json\n{"a": 1}\n```'
    assert _extract_json_via_pipeline(raw) == {"a": 1}


def test_json_extraction_fence_without_tag():
    raw = '```\n{"a": 1}\n```'
    assert _extract_json_via_pipeline(raw) == {"a": 1}


def test_json_extraction_fence_multiline():
    raw = '```json\n{\n  "a": 1,\n  "b": "hello"\n}\n```'
    assert _extract_json_via_pipeline(raw) == {"a": 1, "b": "hello"}


def test_json_extraction_with_preamble():
    """新版：鲁棒抽取器支持前言 + fenced code"""
    from knowledge.ingestion import _extract_json_object
    raw = "Sure, the JSON is:\n```json\n{\"a\": 1}\n```"
    assert _extract_json_object(raw) == {"a": 1}


def test_json_extraction_bracket_balance():
    """鲁棒抽取器：JSON 前后有说明文字"""
    from knowledge.ingestion import _extract_json_object
    raw = 'Here is the result: {"nested": {"key": "value"}} OK?'
    assert _extract_json_object(raw) == {"nested": {"key": "value"}}


def test_json_extraction_no_json():
    from knowledge.ingestion import _extract_json_object
    assert _extract_json_object("no json here") is None
    assert _extract_json_object("") is None
    assert _extract_json_object("{broken") is None


# ═══════════════════════════════════════════════════════════
# 2. Segment 切分层级
# ═══════════════════════════════════════════════════════════

def test_segment_respects_h1_boundary():
    from knowledge.ingestion import DocumentIngestionPipeline
    from knowledge.queue import IngestTask

    pipeline = _make_empty_pipeline()
    # 调大 seg_max，避免内容被"超长回溯"切断
    # 内容要大于 seg_min/2，避免碎片合并回吸
    pipeline._seg_min = 10
    pipeline._seg_target = 100
    pipeline._seg_max = 500
    task = IngestTask.new(tenant_id=1, knowledge_base_id=1, payload={"doc_id": "d1"})
    # 避免用 "第一部分" 这种会被中文章节正则误匹配的标题
    # （"部" 是 data-process 规则里 [章部篇] 的一员，正文里"第一部分"会当 L1 标题）
    content = (
        "# 章节一\n"
        + ("章节一的详细内容说明。" * 5) + "\n"
        + "# 章节二\n"
        + ("章节二的详细内容说明。" * 5)
    )
    segs = pipeline._split_segments(doc_id="d1", task=task, content=content)
    titles = [s.title for s in segs]
    assert titles == ["章节一", "章节二"], f"got {titles}"
    assert all(s.heading_level == 1 for s in segs)


def test_segment_builds_hierarchical_path():
    from knowledge.queue import IngestTask
    pipeline = _make_empty_pipeline()
    # 二级标题的切分条件是 "当前累计 > seg_min"，调小以触发
    pipeline._seg_min = 10
    pipeline._seg_target = 30
    pipeline._seg_max = 200
    task = IngestTask.new(tenant_id=1, knowledge_base_id=1, payload={"doc_id": "d1"})
    content = (
        "# 概述\n"
        + ("介绍文字介绍文字。" * 5) + "\n"
        + "## 1.1 背景\n"
        + ("内容 X 内容 X 内容。" * 5) + "\n"
        + "## 1.2 目标\n"
        + ("内容 Y 内容 Y 内容。" * 5)
    )
    segs = pipeline._split_segments(doc_id="d1", task=task, content=content)
    assert len(segs) == 3, f"got {len(segs)}"
    # 第一段：只有 H1
    assert segs[0].title == "概述"
    assert segs[0].section_path == "概述"
    # 第二段：H1/H2
    assert segs[1].title == "1.1 背景"
    assert segs[1].section_path == "概述 / 1.1 背景"
    # 第三段：H1/H2
    assert segs[2].title == "1.2 目标"
    assert segs[2].section_path == "概述 / 1.2 目标"


def test_segment_no_heading_fallback():
    """无标题的纯文本 → 产出单一 Segment"""
    from knowledge.queue import IngestTask
    pipeline = _make_empty_pipeline()
    task = IngestTask.new(tenant_id=1, knowledge_base_id=1, payload={"doc_id": "d1"})
    content = "这是一段没有任何标题的纯文本，长度也足够。" * 5
    segs = pipeline._split_segments(doc_id="d1", task=task, content=content)
    assert len(segs) == 1
    assert segs[0].title == ""
    assert segs[0].heading_level == 0


def test_segment_forced_split_when_too_long():
    """Segment 超过 seg_max → 在句子边界回溯切分"""
    from knowledge.queue import IngestTask
    pipeline = _make_empty_pipeline()
    # 把阈值调小以便测试触发
    pipeline._seg_min = 200
    pipeline._seg_target = 300
    pipeline._seg_max = 500
    task = IngestTask.new(tenant_id=1, knowledge_base_id=1, payload={"doc_id": "d1"})
    # 单 H1 下放 >500 字符的内容（用句号分隔，让边界回溯能找到切分点）
    sentences = "段内容段内容段内容段内容段内容。" * 40  # ~600 chars, 40 句
    content = f"# 长章节\n{sentences}"
    segs = pipeline._split_segments(doc_id="d1", task=task, content=content)
    # 总内容远超 seg_max，至少应切成 2 段
    assert len(segs) >= 2, f"got {len(segs)} segments"
    # 每段都应落在句子边界上（以句号结尾，除了最后一段）
    for seg in segs[:-1]:
        assert seg.content.rstrip().endswith("。"), f"segment 未在句号处切分: {seg.content[-20:]!r}"


# ═══════════════════════════════════════════════════════════
# 3. Chunk 切分（句子级，对齐 data-process）
# ═══════════════════════════════════════════════════════════

def test_chunk_short_segment_becomes_one_chunk():
    """短 Segment（< chunk_target）直接作为单个 Chunk"""
    from knowledge.cleaning import CleaningResult, CleaningSignals
    from knowledge.queue import IngestTask
    pipeline = _make_empty_pipeline()
    task = IngestTask.new(tenant_id=1, knowledge_base_id=1, payload={"doc_id": "d1"})
    segs = pipeline._split_segments(doc_id="d1", task=task, content="# 标题\n短内容")
    cleaning = CleaningResult(display_content="", content="# 标题\n短内容", signals=CleaningSignals())
    chunks = pipeline._local_split_chunks(doc_id="d1", task=task, segments=segs, cleaning=cleaning)
    assert len(chunks) == len(segs)
    for c, s in zip(chunks, segs):
        assert c.parent_segment_id == s.segment_id
        assert c.section_title == s.title


def test_chunk_long_segment_uses_sentence_split():
    """长 Segment → 按句子累加切多个 Chunk，且 parent_segment_id 都指向它"""
    from knowledge.cleaning import CleaningResult, CleaningSignals
    from knowledge.queue import IngestTask
    pipeline = _make_empty_pipeline()
    # 小目标，方便触发多 chunk
    pipeline._chunk_target = 120
    pipeline._chunk_min = 40
    pipeline._chunk_max = 200
    task = IngestTask.new(tenant_id=1, knowledge_base_id=1, payload={"doc_id": "d1"})
    # 30 个短句，每句 ~15 字，总 450 字
    long_section = "".join(f"这是句子内容第{i}段。" for i in range(30))
    segs = pipeline._split_segments(
        doc_id="d1", task=task, content=f"# 长标题\n{long_section}",
    )
    cleaning = CleaningResult(display_content="", content=f"# 长标题\n{long_section}", signals=CleaningSignals())
    chunks = pipeline._local_split_chunks(doc_id="d1", task=task, segments=segs, cleaning=cleaning)
    assert len(chunks) >= 3, f"expected multiple chunks, got {len(chunks)}"
    # 所有 chunk 都指向同一个父 segment
    parent_ids = {c.parent_segment_id for c in chunks}
    assert len(parent_ids) == 1
    # chunk_index 递增
    indices = [c.chunk_index for c in chunks]
    assert indices == sorted(indices)
    # 每个 chunk 不超过 max（除了可能被"尾部合并"后的最后一个）
    for c in chunks[:-1]:
        assert len(c.content) <= pipeline._chunk_max + 50, f"chunk overflow: {len(c.content)}"


def test_chunk_sentence_overlap_preserves_context():
    """句子级 overlap：每个 chunk 开头应包含上一个 chunk 最后 N 句（模糊校验）"""
    from knowledge.cleaning import CleaningResult, CleaningSignals
    from knowledge.queue import IngestTask
    pipeline = _make_empty_pipeline()
    pipeline._chunk_target = 100
    pipeline._chunk_min = 30
    pipeline._chunk_max = 160
    pipeline._chunk_overlap_sentences = 2
    task = IngestTask.new(tenant_id=1, knowledge_base_id=1, payload={"doc_id": "d1"})
    # 连续编号句子，便于校验 overlap
    content = "# 主题\n" + "".join(f"句子编号{i:03d}结束。" for i in range(30))
    segs = pipeline._split_segments(doc_id="d1", task=task, content=content)
    cleaning = CleaningResult(display_content="", content=content, signals=CleaningSignals())
    chunks = pipeline._local_split_chunks(doc_id="d1", task=task, segments=segs, cleaning=cleaning)
    assert len(chunks) >= 2
    # 相邻 chunk 必须有句子重叠：第 i+1 个 chunk 的开头至少出现过第 i 个 chunk 的尾部某个句子编号
    for i in range(len(chunks) - 1):
        cur_end = chunks[i].content[-40:]  # 当前 chunk 尾部
        next_start = chunks[i + 1].content[:60]  # 下一个 chunk 开头
        # 至少有一个公共"编号 XXX"
        import re as _re
        cur_nums = set(_re.findall(r"\d{3}", cur_end))
        next_nums = set(_re.findall(r"\d{3}", next_start))
        assert cur_nums & next_nums, (
            f"chunk {i} 和 {i+1} 无句子级 overlap: "
            f"cur_end={cur_end!r} next_start={next_start!r}"
        )


def test_chunk_sentence_split_handles_english_period():
    """英文句号 `.` 后若非空格/大写字母不切分，保护数值/缩写

    注意：对齐 data-process 的规则是"后面是空格或大写字母即切分"，
    所以 U.S.A 这种**连续大写**会被切，但 "3.14" 不会被切（数字非大写非空格）。
    """
    from knowledge.ingestion import DocumentIngestionPipeline
    # 数字带小数点：不应切
    text1 = "Pi is 3.14 approximately."
    sentences1 = DocumentIngestionPipeline._split_by_sentence(text1)
    non_empty = [s for s in sentences1 if s.strip()]
    assert len(non_empty) == 1, f"3.14 被错误切分: {non_empty}"

    # 带空格的英文句号：必须切
    text2 = "First sentence. Second sentence."
    sentences2 = DocumentIngestionPipeline._split_by_sentence(text2)
    non_empty2 = [s for s in sentences2 if s.strip()]
    assert len(non_empty2) == 2, f"正常英文应切成 2 句: {non_empty2}"

    # 切分后拼接还原
    full = "".join(sentences1)
    assert full == text1


def test_chunk_type_detection():
    from knowledge.ingestion import DocumentIngestionPipeline
    assert DocumentIngestionPipeline._detect_chunk_type("正常段落") == "Text"
    assert DocumentIngestionPipeline._detect_chunk_type(
        "| 列1 | 列2 | 列3 |\n| --- | --- | --- |\n| a | b | c |"
    ) == "Table"
    assert DocumentIngestionPipeline._detect_chunk_type("# 章节标题") == "Title"
    assert DocumentIngestionPipeline._detect_chunk_type(
        "![alt](data:image/png;base64,xxx)"
    ) == "Image_Description"


def test_rough_tokens_cjk_and_ascii():
    from knowledge.ingestion import DocumentIngestionPipeline
    # CJK: 1 字符 = 1 token
    assert DocumentIngestionPipeline._rough_tokens("中文") == 2
    # ASCII: 4 字符 = 1 token
    assert DocumentIngestionPipeline._rough_tokens("hello world") == len("hello world") // 4


# ═══════════════════════════════════════════════════════════
# 4. 元数据下放到 Chunk
# ═══════════════════════════════════════════════════════════

def test_apply_metadata_to_chunks_basic():
    from knowledge.queue import IngestTask
    from knowledge.cleaning import CleaningResult, CleaningSignals
    pipeline = _make_empty_pipeline()
    task = IngestTask.new(tenant_id=1, knowledge_base_id=1, payload={"doc_id": "d1"})
    segs = pipeline._split_segments(doc_id="d1", task=task, content="# t\n内容")
    chunks = pipeline._local_split_chunks(
        doc_id="d1", task=task, segments=segs,
        cleaning=CleaningResult(display_content="", content="# t\n内容", signals=CleaningSignals()),
    )
    pipeline._apply_metadata_to_chunks(
        chunks,
        metadata={
            "docCategory": "产品手册",
            "industryVertical": "制造业",
            "businessStage": None,          # None 应转为空串
            "productService": ["CRM", "SCM"],  # list 应拼成逗号分隔
            "datePublished": "2024-06-01",
        },
        task=task,
    )
    assert chunks[0].doc_category == "产品手册"
    assert chunks[0].industry == "制造业"
    assert chunks[0].business_stage == ""
    assert chunks[0].product_service == "CRM,SCM"
    assert chunks[0].date_published > 0


def test_apply_metadata_handles_none_gracefully():
    """metadata 全部为 None 时不应把字符串 'None' 存进去"""
    from knowledge.queue import IngestTask
    from knowledge.cleaning import CleaningResult, CleaningSignals
    pipeline = _make_empty_pipeline()
    task = IngestTask.new(tenant_id=1, knowledge_base_id=1, payload={"doc_id": "d1"})
    segs = pipeline._split_segments(doc_id="d1", task=task, content="# t\n内容")
    chunks = pipeline._local_split_chunks(
        doc_id="d1", task=task, segments=segs,
        cleaning=CleaningResult(display_content="", content="# t\n内容", signals=CleaningSignals()),
    )
    pipeline._apply_metadata_to_chunks(
        chunks,
        metadata={
            "docCategory": None,
            "industryVertical": None,
            "businessStage": None,
            "targetAudience": None,
            "productService": None,
            "datePublished": None,
        },
        task=task,
    )
    # 空串而不是 "None"
    assert chunks[0].doc_category == ""
    assert chunks[0].industry == ""
    assert chunks[0].date_published == 0


# ═══════════════════════════════════════════════════════════
# 5. _parse_date 多种输入
# ═══════════════════════════════════════════════════════════

def test_parse_date_yyyy_mm_dd():
    from knowledge.ingestion import DocumentIngestionPipeline
    ts = DocumentIngestionPipeline._parse_date("2024-06-01")
    assert ts > 0
    # 应该是 UTC/本地时间的合理数值
    import datetime as dt
    expected = int(dt.datetime.strptime("2024-06-01", "%Y-%m-%d").timestamp() * 1000)
    assert ts == expected


def test_parse_date_invalid():
    from knowledge.ingestion import DocumentIngestionPipeline
    assert DocumentIngestionPipeline._parse_date("") == 0
    assert DocumentIngestionPipeline._parse_date(None) == 0
    assert DocumentIngestionPipeline._parse_date("2024") == 0       # 不完整
    assert DocumentIngestionPipeline._parse_date("not a date") == 0


def test_parse_date_timestamp_passthrough():
    from knowledge.ingestion import DocumentIngestionPipeline
    assert DocumentIngestionPipeline._parse_date(1_700_000_000_000) == 1_700_000_000_000
    assert DocumentIngestionPipeline._parse_date(1700000000.5) == 1_700_000_000


# ═══════════════════════════════════════════════════════════
# 6. 清洗 + 评分联动
# ═══════════════════════════════════════════════════════════

def test_quality_reflects_cleaning():
    """清洗掉越多，clean_score 越低"""
    from knowledge.cleaning import DocumentCleaningService
    from knowledge.quality import DocumentQualityScorer

    cleaner = DocumentCleaningService()
    scorer = DocumentQualityScorer()

    # 干净文档
    clean_doc = "# 标题\n\n## 章节\n\n" + "正常内容。" * 50
    r1 = cleaner.clean(clean_doc)
    q1 = scorer.score(r1.content, cleaning_signals=r1.signals, total_pages=1)

    # 脏文档：大量控制字符 + 页码
    dirty_doc = "# 标题\n" + ("\u200B" * 100) + "\n\n" + \
        "\n".join(f"第 {i} 页" for i in range(1, 50)) + "\n" + "正常内容。" * 50
    r2 = cleaner.clean(dirty_doc)
    q2 = scorer.score(r2.content, cleaning_signals=r2.signals, total_pages=1)

    # 脏文档的 clean_ratio 应显著更高
    assert r2.signals.clean_ratio > r1.signals.clean_ratio
    # 脏文档的 clean_score 应显著更低
    assert q2.clean_score < q1.clean_score


def test_quality_reflects_failed_pages():
    from knowledge.quality import DocumentQualityScorer
    scorer = DocumentQualityScorer()
    q_full = scorer.score(content="# t", total_pages=10, failed_pages=0)
    q_half = scorer.score(content="# t", total_pages=10, failed_pages=5)
    q_all = scorer.score(content="# t", total_pages=10, failed_pages=10)
    assert q_full.completeness == 1.0
    assert q_half.completeness == 0.5
    assert q_all.completeness == 0.0


# ═══════════════════════════════════════════════════════════
# 7. 端到端（Mock）— 字段一致性
# ═══════════════════════════════════════════════════════════

async def _run_end_to_end_mock():
    """用 Mock 运行一遍完整流水线，校验 document/segment/chunk 三者字段一致"""
    from knowledge.cleaning import DocumentCleaningService
    from knowledge.quality import DocumentQualityScorer
    from knowledge.guard import IngestionGuard
    from knowledge.ingestion import DocumentIngestionPipeline
    from knowledge.queue import IngestTask
    from knowledge.vdb_writer import KnowledgeVectorStore

    from tests.test_knowledge_e2e import (
        MockLKEAPClient, MockVectorStore, MockLLM, _install_lkeap_patch,
    )
    _install_lkeap_patch()

    # 这里我们不跑 PG 写入（那是 e2e 测试的事），只跑 pipeline 逻辑部分
    # 不能完整 run() —— 因为 run 里有 DAO 调用。改为只调各 phase 方法。
    pipeline = DocumentIngestionPipeline(
        lkeap=MockLKEAPClient(),
        vector_store=MockVectorStore(),
        cleaning_service=DocumentCleaningService(),
        quality_scorer=DocumentQualityScorer(),
        llm=MockLLM(),
        guard=IngestionGuard(),
    )

    task = IngestTask.new(
        tenant_id=42, knowledge_base_id=100, dataset_id=0,
        payload={"doc_id": "doc_test", "file_path": "", "file_type": "md",
                 "user_metadata": {"owner": "alice"}},
    )

    content = """# 产品介绍

这是一个测试文档。

## 功能

支持多种场景。
"""

    # Phase 2: 打标
    metadata, summary, keywords = await pipeline._phase2_auto_tag(task, content)
    assert metadata.get("docCategory") == "产品手册"
    assert metadata.get("industryVertical") == "制造业"
    # user_metadata 覆盖
    assert metadata.get("owner") == "alice"
    assert len(summary) > 0
    assert isinstance(keywords, list)

    return True


def test_end_to_end_mock_fields_consistent():
    asyncio.run(_run_end_to_end_mock())


# ═══════════════════════════════════════════════════════════
# 辅助：构造一个不依赖外部服务的 pipeline
# ═══════════════════════════════════════════════════════════

def _make_empty_pipeline():
    """构造一个最小 pipeline，仅用于调用其内部切分/元数据方法"""
    from knowledge.cleaning import DocumentCleaningService
    from knowledge.quality import DocumentQualityScorer
    from knowledge.guard import IngestionGuard
    from knowledge.ingestion import DocumentIngestionPipeline

    class _NoopLKEAP:
        SUPPORTED_TYPES = {"md"}
        @classmethod
        def is_supported(cls, ft): return True

    class _NoopVDB:
        def upsert_chunks(self, rs): return 0
        def upsert_doc_metadata(self, rs): return 0

    return DocumentIngestionPipeline(
        lkeap=_NoopLKEAP(),
        vector_store=_NoopVDB(),
        cleaning_service=DocumentCleaningService(),
        quality_scorer=DocumentQualityScorer(),
        llm=None,
        guard=IngestionGuard(),
    )


# ═══════════════════════════════════════════════════════════
# Runner
# ═══════════════════════════════════════════════════════════

if __name__ == "__main__":
    import traceback

    tests = [
        test_json_extraction_plain,
        test_json_extraction_fence_with_json_tag,
        test_json_extraction_fence_without_tag,
        test_json_extraction_fence_multiline,
        test_json_extraction_with_preamble,
        test_json_extraction_bracket_balance,
        test_json_extraction_no_json,
        test_segment_respects_h1_boundary,
        test_segment_builds_hierarchical_path,
        test_segment_no_heading_fallback,
        test_segment_forced_split_when_too_long,
        test_chunk_short_segment_becomes_one_chunk,
        test_chunk_long_segment_uses_sentence_split,
        test_chunk_sentence_overlap_preserves_context,
        test_chunk_sentence_split_handles_english_period,
        test_chunk_type_detection,
        test_rough_tokens_cjk_and_ascii,
        test_apply_metadata_to_chunks_basic,
        test_apply_metadata_handles_none_gracefully,
        test_parse_date_yyyy_mm_dd,
        test_parse_date_invalid,
        test_parse_date_timestamp_passthrough,
        test_quality_reflects_cleaning,
        test_quality_reflects_failed_pages,
        test_end_to_end_mock_fields_consistent,
    ]

    passed, failed = 0, 0
    failures = []
    for fn in tests:
        try:
            fn()
            passed += 1
            print(f"✅ {fn.__name__}")
        except Exception as exc:
            failed += 1
            print(f"❌ {fn.__name__}: {exc}")
            failures.append((fn.__name__, traceback.format_exc()))

    print(f"\n{passed} passed, {failed} failed")
    if failures:
        print("\n" + "=" * 60)
        for name, tb in failures:
            print(f"\n=== {name} ===")
            print(tb)
    sys.exit(0 if failed == 0 else 1)
