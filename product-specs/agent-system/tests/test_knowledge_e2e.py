"""知识库端到端测试

覆盖：
    1. 建表 + 建立测试 KB/Schema/Binding
    2. 上传一份示例 Markdown 文档
    3. Worker 异步处理：解析(跳过 LKEAP)→清洗→打标(mock LLM)→切分→索引
    4. 查询任务进度
    5. 执行一次混合检索（mock VDB）
    6. 清理测试数据

环境依赖：
    - PG_HOST / PG_PORT / PG_DB / PG_USER / PG_PASSWORD 已配置
    - paas_ai schema 下已执行 sql/init_knowledge_tables.sql

为避免对真实 LKEAP / tcvectordb / LLM 产生依赖，本脚本用 mock 实现打桩。
真实联通性测试见 test_lkeap_e2e.py。

运行方式：
    python tests/test_knowledge_e2e.py
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


# ═══════════════════════════════════════════════════════════
# Mock 组件（绕开外部依赖）
# ═══════════════════════════════════════════════════════════

class MockLKEAPClient:
    """模拟 LKEAP 客户端 — 解析返回固定 Markdown，embedding 返回固定向量"""

    SUPPORTED_TYPES = {"md", "txt", "pdf", "docx"}

    @classmethod
    def is_supported(cls, file_type: str) -> bool:
        return file_type.lower().lstrip(".") in cls.SUPPORTED_TYPES

    def parse_document_sse(self, file_base64=None, file_type=None, **kwargs):
        """返回一个假的 ParseResult"""
        from knowledge.lkeap_client import ParseResult
        # 解码 base64 文本，直接作为 "解析结果"
        import base64
        text = base64.b64decode(file_base64).decode("utf-8") if file_base64 else ""
        # 缓存到模块属性，供 download_and_extract_markdown 读取
        MockLKEAPClient._last_md = text
        return ParseResult(
            status="SUCCESS",
            task_id="mock_task_001",
            markdown_content=text,
            result_url="mock://result.zip",
            success_page_num=1,
            fail_page_num=0,
        )

    async def parse_document(self, file_base64=None, file_type=None, **kwargs):
        return self.parse_document_sse(file_base64=file_base64, file_type=file_type)

    @staticmethod
    def download_and_extract_markdown(result_url: str) -> str:
        return getattr(MockLKEAPClient, "_last_md", "")

    def get_embedding(self, texts: list[str], model: str = "") -> list[list[float]]:
        # 固定 8 维向量，基于文本长度生成（有区分度即可）
        vecs = []
        for t in texts:
            seed = len(t)
            vecs.append([(seed + i) * 0.001 for i in range(8)])
        return vecs

    def rerank(self, query: str, documents: list[str], top_k: int = 5):
        """按文本长度模拟打分，降序"""
        from knowledge.lkeap_client import RerankItem
        items = [
            RerankItem(index=i, score=1.0 / (1 + len(d)))
            for i, d in enumerate(documents)
        ]
        items.sort(key=lambda x: x.score, reverse=True)
        return items[:top_k]


def _install_lkeap_patch():
    """把 TencentLKEAPClient.download_and_extract_markdown 替换为 Mock 的实现

    因为 ingestion.py 里直接调用 TencentLKEAPClient.download_and_extract_markdown
    这个 classmethod，所以要通过 monkey-patch 绕过。
    """
    from knowledge import lkeap_client as lk_mod
    lk_mod.TencentLKEAPClient.download_and_extract_markdown = staticmethod(
        MockLKEAPClient.download_and_extract_markdown,
    )


class MockVectorStore:
    """模拟 tcvectordb — 内存 dict 存储，search 按 cosine 近似"""

    def __init__(self):
        self._chunks: dict[str, dict] = {}
        self._summaries: dict[str, dict] = {}

    def upsert_chunks(self, records: list[dict]) -> int:
        for r in records:
            if not r.get("tenant_id"):
                raise ValueError("tenant_id required")
            self._chunks[r["id"]] = dict(r)
        return len(records)

    def upsert_summaries(self, records: list[dict]) -> int:
        for r in records:
            self._summaries[r["id"]] = dict(r)
        return len(records)

    def search_chunks(
        self, tenant_id: str, vector: list[float],
        query_text: str = "", extra_filter: str = "",
        top_k: int = 20, **kwargs,
    ) -> list[dict]:
        # 忽略向量相似度，直接按租户 + filter 返回全部（测试够用）
        if not tenant_id:
            raise ValueError("tenant_id required")
        results = []
        for chunk in self._chunks.values():
            if chunk.get("tenant_id") != tenant_id:
                continue
            # 简化 filter 匹配
            results.append({**chunk, "score": 0.5})
        return results[:top_k]

    def search_summaries(self, tenant_id, vector, extra_filter="", top_k=10):
        return []

    def delete_by_doc(self, tenant_id: str, doc_id: str):
        self._chunks = {k: v for k, v in self._chunks.items() if v.get("doc_id") != doc_id}
        self._summaries = {k: v for k, v in self._summaries.items() if v.get("doc_id") != doc_id}

    def delete_by_knowledge_base(self, tenant_id, knowledge_base_id):
        pass


class MockLLM:
    """模拟 LLM — Auto-Tag / Self-Query 都返回固定 JSON"""

    async def ainvoke(self, prompt: str):
        result = MagicMock()
        if "元数据过滤" in prompt or "查询分析" in prompt or "filters" in prompt:
            # Self-Query
            result.content = json.dumps({
                "semantic_query": "测试查询",
                "filters": {},
            }, ensure_ascii=False)
        else:
            # Auto-Tag
            result.content = json.dumps({
                "metadata": {
                    "docCategory": "产品手册",
                    "industryVertical": "制造业",
                    "businessStage": None,
                    "targetAudience": None,
                    "productService": None,
                    "datePublished": "2024-06-01",
                },
                "summary": "这是一份测试文档的摘要，描述产品使用方法。",
                "keywords": ["产品", "手册", "测试"],
            }, ensure_ascii=False)
        return result


# ═══════════════════════════════════════════════════════════
# 测试主体
# ═══════════════════════════════════════════════════════════

TENANT_ID = 99999
KB_API_KEY = "test-kb-e2e"


async def run_e2e():
    """E2E 流程"""
    from store.knowledge_dao import (
        KnowledgeBaseBindingDAO, KnowledgeBaseDAO, KnowledgeChunkDAO,
        KnowledgeDatasetDAO, KnowledgeDocumentDAO, KnowledgeIngestLogDAO,
        KnowledgeIngestQueueDAO, KnowledgeSchemaDAO,
    )
    from store.knowledge_models import (
        KnowledgeBaseBindingRow, KnowledgeBaseRow, KnowledgeSchemaRow,
    )
    from knowledge import (
        DocumentCleaningService, DocumentIngestionPipeline, DocumentQualityScorer,
        IngestionGuard, IngestSupervisor, KnowledgeRetriever, PgIngestQueue,
        StandaloneKnowledgeProvider,
    )

    # —— 检查 PG 连接 ——
    try:
        from store.pg_pool import get_conn
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute("SELECT 1")
            assert cur.fetchone()[0] == 1
        print("✅ PG 连接正常")
    except Exception as exc:
        print(f"❌ PG 连接失败: {exc}")
        print("   请确保 paas_db 可用并已执行 sql/init_knowledge_tables.sql")
        return False

    # —— 清理历史测试数据 ——
    with get_conn() as conn:
        cur = conn.cursor()
        for tbl in [
            "ai_knowledge_chunk", "ai_knowledge_segment",
            "ai_knowledge_document", "ai_knowledge_ingest_log",
            "ai_knowledge_ingest_queue", "ai_knowledge_base_binding",
            "ai_knowledge_dataset", "ai_knowledge_schema",
            "ai_knowledge_base",
        ]:
            cur.execute(f"DELETE FROM {tbl} WHERE tenant_id = %s", (TENANT_ID,))
    print("✅ 历史数据已清理")

    # —— Step 1: 建立 Schema ——
    schema_row = KnowledgeSchemaRow(
        tenant_id=TENANT_ID,
        name="default",
        knowledge_base_id=0,
        fields=json.dumps([
            {"field": "docCategory", "type": "enum",
             "enum": ["产品手册", "成功案例", "销售话术"]},
            {"field": "industryVertical", "type": "enum",
             "enum": ["制造业", "金融服务", "互联网"]},
        ], ensure_ascii=False),
    )
    KnowledgeSchemaDAO.insert(schema_row)
    print(f"✅ Schema 创建: id={schema_row.id}")

    # —— Step 2: 建立知识库 ——
    kb = KnowledgeBaseRow(
        tenant_id=TENANT_ID,
        api_key=KB_API_KEY,
        name="E2E 测试知识库",
        description="自动化测试用",
        schema_id=schema_row.id,
    )
    KnowledgeBaseDAO.insert(kb)
    print(f"✅ 知识库创建: id={kb.id} api_key={kb.api_key}")

    # —— Step 3: Agent 绑定 ——
    binding = KnowledgeBaseBindingRow(
        tenant_id=TENANT_ID,
        knowledge_base_id=kb.id,
        agent_name="*",
        scope="read",
    )
    KnowledgeBaseBindingDAO.insert(binding)
    print(f"✅ Agent 绑定（全局可见）")

    # —— Step 4: 组装 Pipeline ——
    lkeap = MockLKEAPClient()
    _install_lkeap_patch()  # 把 classmethod 也替换掉，避免 mock:// URL 报错
    vdb = MockVectorStore()
    llm = MockLLM()
    guard = IngestionGuard(lkeap_concurrency=2)
    cleaner = DocumentCleaningService()
    scorer = DocumentQualityScorer()

    with tempfile.TemporaryDirectory() as tmp_parsed:
        pipeline = DocumentIngestionPipeline(
            lkeap=lkeap,
            vector_store=vdb,
            cleaning_service=cleaner,
            quality_scorer=scorer,
            llm=llm,
            guard=guard,
            parsed_dir=tmp_parsed,
        )
        queue = PgIngestQueue()
        retriever = KnowledgeRetriever(
            vector_store=vdb,
            lkeap=lkeap,
            llm=llm,
            expand_context_n=1,
        )
        supervisor = IngestSupervisor(
            pipeline=pipeline,
            worker_count=1,
            batch=2,
            poll_interval_ms=300,
            reclaim_interval_ms=5000,
            queue=queue,
        )

        with tempfile.TemporaryDirectory() as tmp_upload:
            provider = StandaloneKnowledgeProvider(
                lkeap=lkeap,
                vector_store=vdb,
                retriever=retriever,
                queue=queue,
                guard=guard,
                upload_dir=tmp_upload,
            )

            # —— Step 5: 启动 Worker ——
            await supervisor.start()
            print("✅ IngestSupervisor 启动")

            # —— Step 6: 上传文档 ——
            sample_md = """# 产品手册 v2

## 概述

本产品提供企业级知识管理能力，支持多种文档格式的自动解析和语义检索。

## 核心功能

### 文档解析
- 支持 PDF / DOCX / PPTX
- 表格和公式识别
- 图片 OCR

### 智能检索
- 向量相似度检索
- BM25 关键词检索
- 混合排序

## 适用行业

制造业、金融服务、互联网企业。
"""
            with tempfile.NamedTemporaryFile(
                suffix=".md", delete=False, mode="w", encoding="utf-8",
            ) as tmp_file:
                tmp_file.write(sample_md)
                sample_path = tmp_file.name

            try:
                result = await provider.ingest_document(
                    tenant_id=TENANT_ID,
                    knowledge_base_id=kb.id,
                    file_path=sample_path,
                    file_name="产品手册v2.md",
                    user_metadata={"title": "产品手册 v2（E2E 测试）"},
                )
                print(
                    f"✅ 文档入队: task_id={result.task_id[:24]}… "
                    f"doc_id={result.doc_id[:24]}… status={result.status}",
                )
                task_id = result.task_id
                doc_id = result.doc_id
            finally:
                os.unlink(sample_path)

            # —— Step 7: 等待 Worker 处理 ——
            deadline = time.time() + 30
            final_status = None
            while time.time() < deadline:
                info = await provider.get_ingest_status(task_id)
                if info is None:
                    await asyncio.sleep(0.5)
                    continue
                if info.get("queue_status") in ("success", "dead"):
                    final_status = info
                    break
                await asyncio.sleep(0.5)

            if not final_status:
                print(f"❌ 任务未在 30s 内完成")
                await supervisor.stop(timeout=5)
                return False

            if final_status.get("queue_status") != "success":
                print(f"❌ 任务失败: {final_status}")
                await supervisor.stop(timeout=5)
                return False

            print(
                f"✅ 任务完成: phase={final_status['phase']}, "
                f"chunks={final_status['chunk_count']}, "
                f"segments={final_status['segment_count']}, "
                f"quality={final_status['quality_score']}, "
                f"耗时={final_status['total_duration_ms']}ms",
            )

            # —— Step 8: 验证 PG 数据 ——
            doc = KnowledgeDocumentDAO.get_by_doc_id(doc_id)
            assert doc is not None
            assert doc.parse_status == "parsed"
            assert doc.clean_status == "cleaned"
            assert doc.chunk_status == "indexed"
            assert doc.chunk_count > 0
            assert doc.segment_count > 0
            assert doc.quality_score > 0
            print(
                f"✅ PG 文档状态: parse={doc.parse_status} clean={doc.clean_status} "
                f"chunk={doc.chunk_status} quality={doc.quality_score}",
            )

            chunks = KnowledgeChunkDAO.list_by_doc(doc_id)
            synced = [c for c in chunks if c.vector_synced == 1]
            print(
                f"✅ 切片入库: {len(chunks)} 条, {len(synced)} 已同步向量库",
            )
            assert all(c.doc_category == "产品手册" for c in chunks if c.doc_category)

            # —— Step 9: 检索 ——
            hits = await provider.search(
                tenant_id=TENANT_ID,
                query="产品有什么功能",
                knowledge_base_id=kb.id,
                top_k=3,
                agent_name="CRM-Agent",
            )
            print(f"✅ 检索返回 {len(hits)} 条结果")
            for i, h in enumerate(hits[:2], 1):
                print(
                    f"   {i}. [{h.score:.3f}] {h.document_title} "
                    f"[{h.chunk_type}] {h.content[:60]}…",
                )
            assert len(hits) > 0

            # —— Step 10: 查询单个文档详情 ——
            doc_info = await provider.get_document_info(doc_id)
            assert doc_info is not None
            print(
                f"✅ 文档详情: title={doc_info.title} chunks={doc_info.chunk_count} "
                f"quality={doc_info.quality_score}",
            )

            # —— Step 11: 删除文档 ——
            ok = await provider.delete_document(TENANT_ID, doc_id)
            assert ok
            doc_after = KnowledgeDocumentDAO.get_by_doc_id(doc_id)
            assert doc_after is None  # 软删后 get_by_doc_id 返回 None
            print("✅ 文档软删成功")

            # —— Step 12: 停止 Worker ——
            await supervisor.stop(timeout=5)
            print("✅ IngestSupervisor 已停止")

    print("\n🎉 端到端测试全部通过")
    return True


if __name__ == "__main__":
    # 配置日志
    import logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    logging.getLogger("knowledge").setLevel(logging.INFO)

    try:
        ok = asyncio.run(run_e2e())
        sys.exit(0 if ok else 1)
    except Exception:
        import traceback
        traceback.print_exc()
        sys.exit(1)
