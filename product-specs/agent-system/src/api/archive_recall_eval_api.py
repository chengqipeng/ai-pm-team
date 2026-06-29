"""上下文存档检索评测 REST API

路由前缀：/api/eval/archive-recall

核心能力：
  - 种子数据初始化到真实 VDB（collection: archive_recall_eval）
  - 运行 200 条存档检索评测（走真实 VDB hybrid_search）
  - SSE 流式执行实时推送
  - 按分类筛选和查看详情
"""
from __future__ import annotations

import json
import logging
import os
import time
import asyncio

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/eval/archive-recall", tags=["archive-recall-eval"])


# ═══════════════════════════════════════════════════════════
# VDB + Embedding 配置
# ═══════════════════════════════════════════════════════════

_VDB_URL = os.environ.get("TENCENT_VDB_URL", "http://10.60.2.17")
_VDB_KEY = os.environ.get("TENCENT_VDB_KEY", "bRG3NETg13tv5Fn68VTdkxaJXH9tMQzhKeT3unck")
_VDB_USER = os.environ.get("TENCENT_VDB_USERNAME", "root")
_VDB_DB = os.environ.get("TENCENT_VDB_DATABASE", "viking_memory")
_VDB_COLLECTION = "archive_recall_eval"

_EMBED_MODEL = os.environ.get("EMBEDDING_MODEL", "text-embedding-3-small")
_EMBED_API_KEY = os.environ.get("AGENT_API_KEY") or os.environ.get(
    "OPENAI_API_KEY", "sk-HdY98AcN68JhtXLp8oeIATEL4PWq9rzRcCAhI8G4SOtBbtSw"
)
_EMBED_API_BASE = os.environ.get("AGENT_API_BASE", "https://tokenhub.tencentmaas.com/v1")


# ═══════════════════════════════════════════════════════════
# 内存存储（评测报告）
# ═══════════════════════════════════════════════════════════

_reports: list[dict] = []
_latest_results: list[dict] = []


# ═══════════════════════════════════════════════════════════
# 请求模型
# ═══════════════════════════════════════════════════════════

class RunEvalBody(BaseModel):
    categories: list[str] = Field(default_factory=list)
    # use_real_vdb 保留为兼容字段，始终为 True（已移除 Mock 模式）
    use_real_vdb: bool = True


# ═══════════════════════════════════════════════════════════
# 辅助函数
# ═══════════════════════════════════════════════════════════

def _get_vdb():
    """获取真实 VDB 连接"""
    from src.memory.viking_engine import VectorStore
    return VectorStore(
        url=_VDB_URL, key=_VDB_KEY, username=_VDB_USER,
        database_name=_VDB_DB, collection_name=_VDB_COLLECTION,
    )


def _get_embedding():
    """获取 Embedding 客户端 — 使用本地 Qwen3-Embedding-0.6B"""
    from src.embedding import LocalEmbedding
    return LocalEmbedding()


# ═══════════════════════════════════════════════════════════
# 种子数据同步
# ═══════════════════════════════════════════════════════════

@router.post("/sync-seed")
async def sync_seed_to_vdb():
    """将 30 轮种子对话数据同步到真实 VDB

    流程:
      1. 生成 embedding
      2. 写入 VDB collection: archive_recall_eval
      3. VDB 自动生成 BM25 sparse vector（对 abstract 字段）

    幂等: 使用 upsert（相同 id 覆盖）
    """
    from src.eval.archive_recall_eval_runner import build_seed_conversation_data

    seed_data = build_seed_conversation_data()
    vdb = _get_vdb()
    embedding = _get_embedding()

    # 批量生成 embedding
    records = []
    errors = []
    for turn in seed_data:
        turn_id = turn["turn_id"]

        # BM25 索引：纯原文（user_query + answer_preview），不追加辅助词
        bm25_text = f"{turn['user_query']} {turn['answer_preview']}"[:800]

        # Dense embedding：原文 + 实体 + 工具名（语义更全面）
        embed_text = (
            f"{turn['user_query']} {turn['answer_preview']} "
            f"{turn.get('entities_text', '')} {turn.get('tool_names', '')}"
        )[:800]

        try:
            vector = embedding.embed_query(embed_text)
        except Exception as e:
            errors.append(f"turn_{turn_id}: embedding failed: {e}")
            continue

        record = {
            "id": f"eval_archive_turn_{turn_id}",
            "vector": vector,
            # FilterIndex 字段
            "tenant_id": "eval",
            "thread_id": "eval_session_001",
            "turn_id": str(turn_id),
            "has_decision": "1" if any(kw in turn.get("keywords", "") for kw in ["确认", "更新", "砍价", "签约"]) else "0",
            "task_id": "",
            # 检索字段
            "user_query": turn["user_query"][:500],
            "answer_preview": turn["answer_preview"][:500],
            "entities_text": turn.get("entities_text", "")[:300],
            "tool_names_text": turn.get("tool_names", "")[:200],
            # 业务对象标签（增强同工具多次调用的区分）
            "biz_object": turn.get("biz_object", ""),
            "action_subtype": turn.get("action_subtype", ""),
            # BM25 编码源：纯原文
            "abstract": bm25_text,
            # 原文
            "content": json.dumps(turn, ensure_ascii=False),
            # 元数据
            "keywords_json": turn.get("keywords", ""),
            "message_count": "4",
            "archived_at": str(int(time.time() * 1000)),
            "data_timestamp": str(int(time.time() * 1000)),
        }
        records.append(record)

    # 写入 VDB
    if records:
        try:
            vdb.upsert(records)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"VDB 写入失败: {e}")

    return {
        "synced": len(records),
        "errors": errors,
        "collection": _VDB_COLLECTION,
        "vdb_url": _VDB_URL,
        "message": f"已同步 {len(records)} 轮次到 VDB collection '{_VDB_COLLECTION}'",
    }


@router.get("/seed-status")
async def check_seed_status():
    """检查种子数据是否已同步到 VDB"""
    try:
        vdb = _get_vdb()
        results = vdb.query_by_filter('thread_id = "eval_session_001"', limit=5)
        return {
            "synced": len(results) > 0,
            "count": len(results),
            "sample_ids": [r.get("id", "") for r in results[:3]],
        }
    except Exception as e:
        return {"synced": False, "error": str(e)}


# ═══════════════════════════════════════════════════════════
# 评测 API
# ═══════════════════════════════════════════════════════════

@router.get("/overview")
async def overview():
    """获取评测概览"""
    from src.eval.archive_recall_eval_cases import build_archive_recall_cases
    cases = build_archive_recall_cases()
    by_category = {}
    for c in cases:
        by_category.setdefault(c.category, 0)
        by_category[c.category] += 1
    return {"total_cases": len(cases), "by_category": by_category, "categories": list(by_category.keys())}


@router.get("/cases")
async def list_cases(category: str | None = None):
    """获取评测用例"""
    from src.eval.archive_recall_eval_cases import build_archive_recall_cases
    cases = build_archive_recall_cases()
    if category:
        cases = [c for c in cases if c.category == category]
    return {
        "cases": [{"id": c.id, "category": c.category, "query": c.query,
                   "active_entities": c.active_entities, "expect_hit_turns": c.expect_hit_turns,
                   "expect_intent": c.expect_intent, "expect_no_hit": c.expect_no_hit,
                   "description": c.description} for c in cases],
        "total": len(cases),
    }


@router.get("/seed-data")
async def get_seed_data():
    """获取种子对话数据"""
    from src.eval.archive_recall_eval_runner import build_seed_conversation_data
    return {"turns": build_seed_conversation_data(), "total": 30}


@router.post("/run")
async def run_eval(body: RunEvalBody):
    """执行评测（真实 VDB + LLM Rewrite，无 Mock 模式）"""
    from src.eval.archive_recall_eval_cases import build_archive_recall_cases
    from src.eval.archive_recall_eval_runner import (
        ArchiveRecallEvalRunner, RealVDBArchiveEngine, LLMArchiveQueryRewriter,
        print_archive_recall_report,
    )

    cases = build_archive_recall_cases()
    if body.categories:
        cat_set = set(body.categories)
        cases = [c for c in cases if c.category in cat_set]

    # 始终使用真实 VDB + LLM Rewrite
    engine = RealVDBArchiveEngine()
    rewriter = LLMArchiveQueryRewriter()
    runner = ArchiveRecallEvalRunner(engine=engine, rewriter=rewriter)

    # 检查环境就绪
    status = runner.setup()
    if not status["vdb_ready"]:
        raise HTTPException(
            status_code=412,
            detail=f"VDB 种子数据未初始化（record_count={status['record_count']}）。"
                   f"请先调用 POST /api/eval/archive-recall/sync-seed"
        )

    report = await runner.run_all(cases)
    print_archive_recall_report(report)

    report_dict = report.to_dict()
    report_dict["report_key"] = f"ar_rpt_{int(time.time())}"
    report_dict["created_at"] = int(time.time() * 1000)
    report_dict["use_real_vdb"] = True
    report_dict["use_llm_rewrite"] = True
    _reports.insert(0, report_dict)

    global _latest_results
    _latest_results = [r.to_dict() for r in report.results]

    return report_dict


@router.post("/run-stream")
async def run_eval_stream(body: RunEvalBody):
    """流式执行评测 — SSE（真实 VDB + LLM Rewrite）"""
    from src.eval.archive_recall_eval_cases import build_archive_recall_cases
    from src.eval.archive_recall_eval_runner import (
        ArchiveRecallEvalRunner, RealVDBArchiveEngine, LLMArchiveQueryRewriter,
    )

    cases = build_archive_recall_cases()
    if body.categories:
        cat_set = set(body.categories)
        cases = [c for c in cases if c.category in cat_set]

    # 始终使用真实 VDB + LLM Rewrite
    engine = RealVDBArchiveEngine()
    rewriter = LLMArchiveQueryRewriter()

    async def event_stream():
        runner = ArchiveRecallEvalRunner(engine=engine, rewriter=rewriter)

        # 环境检查
        status = runner.setup()
        if not status["vdb_ready"]:
            yield f"data: {json.dumps({'type': 'error', 'message': 'VDB 种子数据未初始化，请先调用 sync-seed'})}\n\n"
            return

        total = len(cases)
        yield f"data: {json.dumps({'type': 'start', 'total': total, 'use_real_vdb': True, 'use_llm_rewrite': True})}\n\n"

        # 并发执行，按完成顺序逐条推送
        semaphore = asyncio.Semaphore(10)
        passed = 0
        failed = 0
        results = []
        completed = 0

        async def run_one(case):
            async with semaphore:
                return await runner._run_single(case)

        tasks = [asyncio.create_task(run_one(case)) for case in cases]

        for coro in asyncio.as_completed(tasks):
            result = await coro
            results.append(result)
            completed += 1
            if result.passed:
                passed += 1
            else:
                failed += 1

            yield f"data: {json.dumps({'type': 'progress', 'index': completed, 'total': total, 'passed': passed, 'failed': failed, 'result': result.to_dict()}, ensure_ascii=False)}\n\n"

        n = max(total, 1)
        yield f"data: {json.dumps({'type': 'complete', 'total': total, 'passed': passed, 'failed': failed, 'pass_rate': round(passed/n,4), 'avg_recall': round(sum(r.recall_at_k for r in results)/n,4), 'avg_precision': round(sum(r.precision_at_k for r in results)/n,4), 'rewrite_accuracy': round(sum(1 for r in results if r.rewrite_passed)/n,4)}, ensure_ascii=False)}\n\n"

        global _latest_results
        _latest_results = [r.to_dict() for r in results]

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.get("/reports")
async def list_reports(limit: int = 10):
    return {"items": _reports[:limit], "total": len(_reports)}


@router.get("/reports/latest-results")
async def get_latest_results():
    if not _latest_results:
        return {"results": [], "total": 0}
    return {"results": _latest_results, "total": len(_latest_results)}
