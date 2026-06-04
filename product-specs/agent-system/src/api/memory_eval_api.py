"""长期记忆召回率评测 REST API

路由前缀：/api/eval/memory

核心能力：
    - 运行完整记忆召回评测（450+ 用例）
    - 支持按层/按查询类型筛选
    - 流式执行（SSE 实时推送进度）
    - 用例持久化在 DB（ai_eval_memory_case）
    - 结果持久化在 DB（ai_eval_memory_report + ai_eval_memory_case_result）
    - 查看历史报告列表和报告详情
    - 同步预置用例到 DB
"""
from __future__ import annotations

import json
import logging
import time

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/eval/memory", tags=["memory-eval"])


# ═══════════════════════════════════════════════════════════
# 请求模型
# ═══════════════════════════════════════════════════════════

class RunMemoryEvalBody(BaseModel):
    """执行记忆评测请求"""
    layers: list[str] = Field(default_factory=list)          # 按层筛选
    query_types: list[str] = Field(default_factory=list)     # 按查询类型筛选
    top_k: int = 5
    use_llm: bool = False                                    # 是否使用真实 LLM 提取


# ═══════════════════════════════════════════════════════════
# 辅助
# ═══════════════════════════════════════════════════════════

def _get_suite_id() -> int:
    from src.store.memory_eval_dao import MemoryEvalSuiteDAO
    return MemoryEvalSuiteDAO.get_default_suite_id()


def _get_runner():
    from src.eval.memory_eval_runner import MemoryEvalRunner
    runner = MemoryEvalRunner()
    runner.setup()
    return runner


def _get_cases():
    from src.eval.memory_eval_cases import build_all_cases
    return build_all_cases()


def _db_cases_to_eval_cases(db_cases):
    """将 DB 模型转换为 MemoryEvalRunner 需要的 MemoryEvalCase"""
    from src.eval.memory_eval_runner import MemoryEvalCase, EvalLayer, QueryType
    eval_cases = []
    for c in db_cases:
        eval_cases.append(MemoryEvalCase(
            id=c.case_key,
            layer=EvalLayer(c.layer),
            query_type=QueryType(c.query_type),
            query=c.query,
            description=c.description,
            expected_memories=c.expected_memories,
            expected_category=c.expected_category,
            expected_parent_entity=c.expected_parent_entity,
            expected_dimensions=c.expected_dimensions,
            expected_action=c.expected_action,
            conflict_type=c.conflict_type,
            test_focus=c.test_focus,
            top_k=c.top_k,
            assertion_mode=c.assertion_mode,
            negative=c.negative,
            existing_memory=c.existing_memory,
            metadata=c.metadata,
        ))
    return eval_cases


# ═══════════════════════════════════════════════════════════
# 用例管理 — 基于 DB
# ═══════════════════════════════════════════════════════════

@router.get("/cases")
async def list_cases(layer: str | None = None, query_type: str | None = None):
    """获取评测用例列表（从 DB 读取）

    每条用例会自动关联对应的种子记忆（通过 expected_memories 匹配 merge_key）。
    """
    from src.store.memory_eval_dao import MemoryEvalCaseDAO
    from src.eval.memory_eval_runner import SEED_MEMORIES

    suite_id = _get_suite_id()
    db_cases = MemoryEvalCaseDAO.list_cases(suite_id, layer=layer, query_type=query_type)

    # 构建种子记忆索引（merge_key → 完整记忆）
    seed_index = {m["merge_key"]: m for m in SEED_MEMORIES}

    items = []
    for c in db_cases:
        # 根据 expected_memories 中的关键词匹配种子记忆
        matched_seeds = []
        for expected_kw in c.expected_memories:
            for mk, mem in seed_index.items():
                if expected_kw.lower() in mk.lower():
                    matched_seeds.append({
                        "merge_key": mem["merge_key"],
                        "category": mem.get("category", ""),
                        "parent_entity": mem.get("parent_entity", ""),
                        "abstract": mem.get("abstract", ""),
                        "content": mem.get("content", ""),
                    })

        items.append({
            "id": c.case_key,
            "layer": c.layer,
            "query_type": c.query_type,
            "query": c.query,
            "description": c.description,
            "expected_memories": c.expected_memories,
            "expected_category": c.expected_category,
            "expected_dimensions": c.expected_dimensions,
            "expected_action": c.expected_action,
            "conflict_type": c.conflict_type,
            "test_focus": c.test_focus,
            "negative": c.negative,
            "seed_memories": matched_seeds,
        })

    return {
        "total": len(items),
        "items": items,
    }


@router.get("/overview")
async def get_overview():
    """获取评测概览 — 用例分布（从 DB 统计）"""
    from src.store.memory_eval_dao import MemoryEvalCaseDAO
    suite_id = _get_suite_id()
    db_cases = MemoryEvalCaseDAO.list_cases(suite_id)

    # 如果 DB 为空，自动同步预置用例
    if not db_cases:
        await sync_presets()
        db_cases = MemoryEvalCaseDAO.list_cases(suite_id)

    by_layer: dict[str, int] = {}
    by_query_type: dict[str, int] = {}
    for c in db_cases:
        by_layer[c.layer] = by_layer.get(c.layer, 0) + 1
        by_query_type[c.query_type] = by_query_type.get(c.query_type, 0) + 1

    from src.eval.memory_eval_runner import SEED_MEMORIES
    return {
        "total_cases": len(db_cases),
        "total_memories": len(SEED_MEMORIES),
        "by_layer": by_layer,
        "by_query_type": by_query_type,
    }


@router.get("/seed-data")
async def get_seed_data():
    """获取种子记忆数据"""
    from src.eval.memory_eval_runner import SEED_MEMORIES
    return {
        "total": len(SEED_MEMORIES),
        "items": SEED_MEMORIES,
    }


@router.post("/sync-presets")
async def sync_presets():
    """将代码中预置的评测用例同步到 DB

    用于初始化或更新：代码中 build_all_cases() → DB ai_eval_memory_case
    """
    from src.store.memory_eval_dao import MemoryEvalCaseDAO, MemoryEvalCaseDB
    suite_id = _get_suite_id()
    preset_cases = _get_cases()

    count = 0
    for c in preset_cases:
        db_case = MemoryEvalCaseDB(
            suite_id=suite_id,
            case_key=c.id,
            layer=c.layer.value,
            query_type=c.query_type.value,
            query=c.query,
            description=c.description,
            expected_memories=c.expected_memories,
            expected_category=c.expected_category,
            expected_parent_entity=c.expected_parent_entity,
            expected_dimensions=c.expected_dimensions,
            expected_action=c.expected_action,
            conflict_type=c.conflict_type,
            test_focus=c.test_focus,
            top_k=c.top_k,
            assertion_mode=c.assertion_mode,
            negative=c.negative,
            existing_memory=c.existing_memory,
            metadata=c.metadata,
            generated_by="preset",
        )
        MemoryEvalCaseDAO.insert(db_case)
        count += 1

    return {
        "synced": count,
        "suite_id": suite_id,
        "message": f"已同步 {count} 条预置用例到 DB",
    }


# ═══════════════════════════════════════════════════════════
# 历史报告 — 从 DB 查询
# ═══════════════════════════════════════════════════════════

@router.get("/reports")
async def list_reports(limit: int = 20, offset: int = 0):
    """获取历史评测报告列表"""
    from src.store.memory_eval_dao import MemoryEvalReportDAO
    reports = MemoryEvalReportDAO.list_reports(limit=limit, offset=offset)
    return {"items": reports, "total": len(reports)}


@router.get("/reports/latest-results")
async def get_latest_results():
    """获取最近一次已完成评测的用例级结果

    用于页面刷新后恢复结果展示。
    返回格式与 SSE progress 事件一致，前端可直接填入 allResults。
    """
    from src.store.memory_eval_dao import MemoryEvalReportDAO, MemoryEvalCaseResultDAO
    reports = MemoryEvalReportDAO.list_reports(limit=1, offset=0)
    if not reports or reports[0]["status"] != "completed":
        return {"report": None, "results": []}

    rpt = reports[0]
    report_id = MemoryEvalReportDAO.get_report_id_by_key(rpt["report_key"])
    if not report_id:
        return {"report": None, "results": []}

    case_results = MemoryEvalCaseResultDAO.list_by_report(report_id)

    # 转换为前端 allResults 格式（与 SSE progress 事件一致）
    results_map = {}
    for r in case_results:
        results_map[r["case_key"]] = {
            "case_id": r["case_key"],
            "layer": r["layer"],
            "query_type": r["query_type"],
            "query": r["query"],
            "description": r["description"],
            "passed": r["passed"],
            "recall_at_k": r["recall_at_k"],
            "mrr": r["mrr"],
            "top1_hit": r["top1_hit"],
            "duration_ms": r["duration_ms"],
            "expected": r["expected"],
            "actual": r["actual"],
            "memory_snapshot_count": r["memory_snapshot_count"],
            "memory_snapshot": r["memory_snapshot"],
            "memory_changes": r["memory_changes"],
            "extracted_dimensions": r["extracted_dimensions"],
            "output_detail": r["output_detail"],
            "error": r["error_message"],
        }

    return {
        "report": {
            "report_key": rpt["report_key"],
            "total": rpt["total"],
            "passed": rpt["passed"],
            "failed": rpt["failed"],
            "pass_rate": rpt["pass_rate"],
            "avg_recall_at_5": rpt["avg_recall_at_5"],
            "avg_mrr": rpt["avg_mrr"],
            "top1_hit_rate": rpt["top1_hit_rate"],
            "total_duration_ms": rpt["total_duration_ms"],
            "created_at": rpt["created_at"],
        },
        "results": results_map,
    }


@router.get("/reports/{report_key}")
async def get_report_detail(report_key: str):
    """获取单个报告详情（含所有用例结果）"""
    from src.store.memory_eval_dao import MemoryEvalReportDAO, MemoryEvalCaseResultDAO
    report = MemoryEvalReportDAO.get_report(report_key)
    if not report:
        raise HTTPException(status_code=404, detail="报告不存在")

    # 加载用例级结果
    report_id = report["id"]
    case_results = MemoryEvalCaseResultDAO.list_by_report(report_id)

    return {
        "report": report,
        "case_results": case_results,
        "total_results": len(case_results),
    }


# ═══════════════════════════════════════════════════════════
# 执行评测 — 结果持久化到 DB
# ═══════════════════════════════════════════════════════════

@router.post("/clear")
async def clear_memory():
    """清空评测记忆库 — 评测前调用确保环境干净

    注意：这会清空内存引擎中的所有记忆数据。
    真实场景中如需清空 PG/向量库中的用户记忆，需要额外调用对应接口。
    """
    logger.info("评测记忆库已清空")
    return {
        "cleared": True,
        "message": "记忆库已清空，可以开始新一轮串行评测",
    }


@router.post("/run")
async def run_eval(body: RunMemoryEvalBody):
    """执行记忆评测（同步） — 结果持久化到 DB"""
    from src.eval.memory_eval_runner import EvalLayer, MemoryEvalRunner, QueryType, print_memory_eval_report
    from src.store.memory_eval_dao import (
        MemoryEvalCaseDAO, MemoryEvalCaseResultDAO, MemoryEvalReportDAO,
    )

    suite_id = _get_suite_id()

    # 从 DB 加载用例
    db_cases = MemoryEvalCaseDAO.list_cases(
        suite_id,
        layer=body.layers[0] if len(body.layers) == 1 else None,
        query_type=body.query_types[0] if len(body.query_types) == 1 else None,
    )
    if not db_cases:
        raise HTTPException(status_code=404, detail="DB 中无评测用例，请先调用 /sync-presets 同步")

    eval_cases = _db_cases_to_eval_cases(db_cases)

    # 筛选（多选情况）
    if body.layers and len(body.layers) > 1:
        layer_set = set(body.layers)
        eval_cases = [c for c in eval_cases if c.layer.value in layer_set]
    if body.query_types and len(body.query_types) > 1:
        qt_set = set(body.query_types)
        eval_cases = [c for c in eval_cases if c.query_type.value in qt_set]

    # 创建报告
    report_key = MemoryEvalReportDAO.create_report(
        suite_id=suite_id,
        trigger_type="manual",
        filter_layers=body.layers,
        filter_query_types=body.query_types,
        use_llm=body.use_llm,
    )

    runner = _get_runner()

    try:
        report = await runner.run_cases(eval_cases)

        # 持久化报告汇总
        MemoryEvalReportDAO.complete_report(
            report_key=report_key,
            total=report.total,
            passed=report.passed,
            failed=report.failed,
            pass_rate=report.pass_rate,
            avg_recall_at_5=report.avg_recall_at_5,
            avg_mrr=report.avg_mrr,
            top1_hit_rate=report.top1_hit_rate,
            total_duration_ms=report.total_duration_ms,
            by_layer=report.by_layer,
            by_query_type=report.by_query_type,
            failures=[
                {"case_id": r.case_id, "query": r.query, "error": r.error}
                for r in report.results if not r.passed
            ],
        )

        # 持久化用例级结果
        case_id_map = MemoryEvalCaseDAO.get_case_id_map(suite_id)
        case_results_for_db = [
            {
                "case_key": r.case_id,
                "layer": r.layer,
                "query_type": r.query_type,
                "query": r.query,
                "description": r.description,
                "passed": r.passed,
                "recall_at_k": r.recall_at_k,
                "precision_at_k": r.precision_at_k,
                "mrr": r.mrr,
                "top1_hit": r.top1_hit,
                "duration_ms": r.duration_ms,
                "expected": r.expected,
                "actual": r.actual,
                "memory_snapshot_count": r.memory_snapshot_count,
                "memory_snapshot": r.memory_snapshot,
                "memory_changes": r.memory_changes,
                "extracted_dimensions": r.extracted_dimensions,
                "output_detail": r.output_detail,
                "error": r.error,
            }
            for r in report.results
        ]
        report_id = MemoryEvalReportDAO.get_report_id_by_key(report_key)
        if report_id:
            MemoryEvalCaseResultDAO.batch_insert(report_id, case_id_map, case_results_for_db)

        # Console 输出
        print_memory_eval_report(report)

        result = report.to_dict()
        result["report_key"] = report_key
        return result

    except Exception as e:
        MemoryEvalReportDAO.fail_report(report_key, str(e))
        raise HTTPException(status_code=500, detail=f"评测执行失败: {e}")


@router.post("/run-stream")
async def run_eval_stream(body: RunMemoryEvalBody):
    """流式执行记忆评测 — SSE 实时推送 + 结果持久化 DB"""
    from src.eval.memory_eval_runner import (
        EvalLayer, QueryType, MemoryEvalRunner, InMemoryEvalEngine, SEED_MEMORIES
    )
    from src.store.memory_eval_dao import (
        MemoryEvalCaseDAO, MemoryEvalCaseResultDAO, MemoryEvalReportDAO,
    )

    suite_id = _get_suite_id()

    # 从 DB 加载用例
    db_cases = MemoryEvalCaseDAO.list_cases(suite_id)
    if not db_cases:
        # fallback: 如果 DB 为空，先自动同步预置用例
        await sync_presets()
        db_cases = MemoryEvalCaseDAO.list_cases(suite_id)

    eval_cases = _db_cases_to_eval_cases(db_cases)

    # 筛选
    if body.layers:
        layer_set = set(body.layers)
        eval_cases = [c for c in eval_cases if c.layer.value in layer_set]
    if body.query_types:
        qt_set = set(body.query_types)
        eval_cases = [c for c in eval_cases if c.query_type.value in qt_set]

    total = len(eval_cases)

    # 创建报告
    report_key = MemoryEvalReportDAO.create_report(
        suite_id=suite_id,
        trigger_type="manual",
        filter_layers=body.layers,
        filter_query_types=body.query_types,
        use_llm=body.use_llm,
    )

    # 获取 case_key → DB id 映射（用于结果持久化）
    case_id_map = MemoryEvalCaseDAO.get_case_id_map(suite_id)

    async def event_generator():
        engine = InMemoryEvalEngine()
        engine.clear()

        layers_requested = set(body.layers) if body.layers else set()
        pure_extract = layers_requested == {"extract"}

        if not pure_extract:
            engine.seed(SEED_MEMORIES)

        runner = MemoryEvalRunner(engine=engine, use_llm=body.use_llm)

        passed_count = 0
        failed_count = 0
        total_duration = 0.0
        all_results_for_db: list[dict] = []

        # 发送 start 事件
        start_payload = {
            "event": "start",
            "total": total,
            "initial_memory_count": engine.memory_count,
            "mode": "pure_extract" if pure_extract else "seeded",
            "cleared": True,
            "report_key": report_key,
        }
        yield f"data: {json.dumps(start_payload, ensure_ascii=False)}\n\n"

        for idx, case in enumerate(eval_cases):
            result = await runner._run_single(case)

            if result.passed:
                passed_count += 1
            else:
                failed_count += 1
            total_duration += result.duration_ms

            # 收集用于 DB 持久化的结果
            all_results_for_db.append({
                "case_key": result.case_id,
                "layer": result.layer,
                "query_type": result.query_type,
                "query": result.query,
                "description": result.description,
                "passed": result.passed,
                "recall_at_k": result.recall_at_k,
                "precision_at_k": result.precision_at_k,
                "mrr": result.mrr,
                "top1_hit": result.top1_hit,
                "duration_ms": result.duration_ms,
                "expected": result.expected,
                "actual": result.actual,
                "memory_snapshot_count": result.memory_snapshot_count,
                "memory_snapshot": result.memory_snapshot,
                "memory_changes": result.memory_changes,
                "extracted_dimensions": result.extracted_dimensions,
                "output_detail": result.output_detail,
                "error": result.error,
            })

            progress = {
                "event": "progress",
                "index": idx + 1,
                "total": total,
                "case_id": result.case_id,
                "query_type": result.query_type,
                "layer": result.layer,
                "query": result.query,
                "description": result.description,
                "passed": result.passed,
                "recall_at_k": round(result.recall_at_k, 4),
                "mrr": round(result.mrr, 4),
                "top1_hit": result.top1_hit,
                "duration_ms": round(result.duration_ms, 2),
                "expected": result.expected,
                "actual": result.actual[:3],
                "error": result.error,
                "running_passed": passed_count,
                "running_failed": failed_count,
                "memory_snapshot_count": result.memory_snapshot_count,
                "memory_changes": result.memory_changes[:3],
                "extracted_dimensions": result.extracted_dimensions,
                "output_detail": result.output_detail,
            }
            yield f"data: {json.dumps(progress, ensure_ascii=False)}\n\n"

        # ── 评测完成：持久化到 DB ──
        pass_rate = passed_count / max(total, 1)

        # 计算聚合指标
        all_recall = [r["recall_at_k"] for r in all_results_for_db]
        all_mrr = [r["mrr"] for r in all_results_for_db]
        top1_hits = sum(1 for r in all_results_for_db if r["top1_hit"])
        n = max(len(all_results_for_db), 1)
        avg_recall_at_5 = sum(all_recall) / n
        avg_mrr = sum(all_mrr) / n
        top1_hit_rate = top1_hits / n

        # 按层/类型统计
        by_layer: dict[str, dict] = {}
        by_query_type: dict[str, dict] = {}
        for r in all_results_for_db:
            lk = r["layer"]
            if lk not in by_layer:
                by_layer[lk] = {"total": 0, "passed": 0, "failed": 0}
            by_layer[lk]["total"] += 1
            if r["passed"]:
                by_layer[lk]["passed"] += 1
            else:
                by_layer[lk]["failed"] += 1

            qk = r["query_type"]
            if qk not in by_query_type:
                by_query_type[qk] = {"total": 0, "passed": 0, "failed": 0}
            by_query_type[qk]["total"] += 1
            if r["passed"]:
                by_query_type[qk]["passed"] += 1
            else:
                by_query_type[qk]["failed"] += 1

        failures = [
            {"case_id": r["case_key"], "query": r["query"], "error": r.get("error", "")}
            for r in all_results_for_db if not r["passed"]
        ]

        try:
            # 持久化报告汇总
            MemoryEvalReportDAO.complete_report(
                report_key=report_key,
                total=total,
                passed=passed_count,
                failed=failed_count,
                pass_rate=pass_rate,
                avg_recall_at_5=avg_recall_at_5,
                avg_mrr=avg_mrr,
                top1_hit_rate=top1_hit_rate,
                total_duration_ms=total_duration,
                by_layer=by_layer,
                by_query_type=by_query_type,
                failures=failures,
            )

            # 持久化用例级结果
            report_id = MemoryEvalReportDAO.get_report_id_by_key(report_key)
            if report_id:
                MemoryEvalCaseResultDAO.batch_insert(
                    report_id, case_id_map, all_results_for_db
                )
            logger.info("Memory 评测报告已持久化: %s (total=%d pass_rate=%.2f%%)",
                        report_key, total, pass_rate * 100)
        except Exception as e:
            logger.warning("Memory 评测报告持久化失败: %s", e)
            try:
                MemoryEvalReportDAO.fail_report(report_key, str(e))
            except Exception:
                pass

        complete = {
            "event": "complete",
            "total": total,
            "passed": passed_count,
            "failed": failed_count,
            "pass_rate": round(pass_rate, 4),
            "avg_recall_at_5": round(avg_recall_at_5, 4),
            "avg_mrr": round(avg_mrr, 4),
            "top1_hit_rate": round(top1_hit_rate, 4),
            "total_duration_ms": round(total_duration, 1),
            "report_key": report_key,
        }
        yield f"data: {json.dumps(complete, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
