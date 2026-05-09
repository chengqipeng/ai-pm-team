"""完整链路验证：创建 KB → 上传文档 → Pipeline 入库 → 检索验证

用法：
    .venv/bin/python scripts/test_full_pipeline.py
"""
import asyncio
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.config.models import KnowledgeSettings
from src.core.context import DEFAULT_TENANT_ID
from src.knowledge.factory import build_knowledge_provider
from src.knowledge.retriever import KnowledgeRetriever
from src.store.knowledge_dao import KnowledgeBaseDAO, KnowledgeDocumentDAO, KnowledgeSchemaDAO
from src.store.knowledge_models import KnowledgeBaseRow, KnowledgeSchemaRow


async def main() -> int:
    settings = KnowledgeSettings()
    tenant_id = DEFAULT_TENANT_ID
    print(f"=== 完整链路验证 (tenant_id={tenant_id}) ===\n")

    # 1. 创建 KB
    print("1. 创建知识库...")
    kb = KnowledgeBaseRow(
        tenant_id=tenant_id,
        api_key="test_approval_kb",
        name="审批流产品手册库",
        description="智能审批流产品手册",
        default_top_k=5,
        min_score=0.5,
        enable_self_query=1,
    )
    try:
        KnowledgeBaseDAO.insert(kb)
        print(f"   ✅ KB 创建成功: id={kb.id} name={kb.name}")
    except Exception as exc:
        # 可能已存在
        existing = KnowledgeBaseDAO.get_by_api_key(tenant_id, "test_approval_kb")
        if existing:
            kb = existing
            print(f"   ⚠️ KB 已存在: id={kb.id}")
        else:
            print(f"   ❌ KB 创建失败: {exc}")
            return 1

    # 2. 创建默认 Schema
    print("2. 初始化 Schema...")
    from src.knowledge.ingestion import _DEFAULT_SCHEMA_FIELDS
    existing_schema = KnowledgeSchemaDAO.get_for_kb(tenant_id, kb.id)
    if not existing_schema:
        schema = KnowledgeSchemaRow(
            tenant_id=tenant_id,
            name="default",
            knowledge_base_id=kb.id,
            fields=json.dumps(_DEFAULT_SCHEMA_FIELDS, ensure_ascii=False),
        )
        KnowledgeSchemaDAO.insert(schema)
        print(f"   ✅ Schema 创建成功 ({len(_DEFAULT_SCHEMA_FIELDS)} 字段)")
    else:
        print(f"   ⚠️ Schema 已存在")

    # 3. 构建 Provider + Supervisor
    print("3. 构建 Provider...")
    # 简化：不启动 LLM（Self-Querying/打标降级）
    provider, supervisor = build_knowledge_provider(settings, llm=None)
    await supervisor.start()
    print(f"   ✅ Provider + Supervisor 启动")

    # 4. 上传文档
    print("4. 上传文档...")
    file_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "data/knowledge/uploads/test_product_manual.md",
    )
    result = await provider.ingest_document(
        tenant_id=tenant_id,
        knowledge_base_id=kb.id,
        file_path=file_path,
        file_name="智能审批流产品手册.md",
    )
    print(f"   ✅ 入库任务提交: doc_id={result.doc_id} task_id={result.task_id}")

    # 5. 等待 Pipeline 完成（最多 60 秒）
    print("5. 等待 Pipeline 完成...")
    for i in range(60):
        await asyncio.sleep(1)
        doc = KnowledgeDocumentDAO.get_by_doc_id(result.doc_id)
        if doc and doc.chunk_status in ("indexed", "failed"):
            break
        if i % 10 == 9:
            print(f"   ... 等待中 ({i+1}s)")

    doc = KnowledgeDocumentDAO.get_by_doc_id(result.doc_id)
    if not doc or doc.chunk_status != "indexed":
        print(f"   ❌ Pipeline 未完成: status={doc.chunk_status if doc else 'None'}")
        print(f"      parse_error={doc.parse_error[:200] if doc else ''}")
        await supervisor.stop()
        return 1

    print(f"   ✅ Pipeline 完成: chunks={doc.chunk_count} segments={doc.segment_count}")
    print(f"      summary={doc.summary[:100]}..." if doc.summary else "      summary=(empty)")
    print(f"      toc={doc.toc[:100]}..." if doc.toc else "      toc=(empty)")

    # 6. 检索验证
    print("\n6. 检索验证...")
    retriever = KnowledgeRetriever(
        vector_store=provider._vdb,
        lkeap=provider._lkeap,
        llm=None,
        embedding_fn=None,
        expand_context_n=1,
    )

    test_queries = [
        ("条件分支怎么配置", 0.5),
        ("并行审批的场景", 0.5),
        ("数据库备份命令", 0.5),
        ("今天天气怎么样", 0.6),  # 无关 query
    ]

    for query, threshold in test_queries:
        chunks = await retriever.search(
            tenant_id=tenant_id,
            query=query,
            knowledge_base_id=kb.id,
            top_k=3,
            threshold=threshold,
            enable_self_query=False,
        )
        print(f"\n   Query: {query!r} (threshold={threshold})")
        print(f"   命中: {len(chunks)} 条")
        for c in chunks[:2]:
            print(f"     [{c.score:.4f}] {c.content[:80]!r}")

    # 7. 停止
    await supervisor.stop()
    print("\n\n=== 验证完成 ===")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
