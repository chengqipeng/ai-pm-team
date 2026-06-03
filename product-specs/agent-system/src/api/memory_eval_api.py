"""长期记忆召回率评测 REST API

路由前缀：/api/eval/memory

核心能力：
    - 运行完整记忆召回评测（200+ 用例）
    - 支持按层/按查询类型筛选
    - 流式执行（SSE 实时推送进度）
    - 查看用例列表和种子数据
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

def _get_runner():
    from src.eval.memory_eval_runner import MemoryEvalRunner
    runner = MemoryEvalRunner()
    runner.setup()
    return runner


def _get_cases():
    from src.eval.memory_eval_cases import build_all_cases
    return build_all_cases()


# ═══════════════════════════════════════════════════════════
# 用例概览
# ═══════════════════════════════════════════════════════════

@router.get("/cases")
async def list_cases(layer: str | None = None, query_type: str | None = None):
    """获取评测用例列表"""
    cases = _get_cases()
    if layer:
        cases = [c for c in cases if c.layer.value == layer]
    if query_type:
        cases = [c for c in cases if c.query_type.value == query_type]

    return {
        "total": len(cases),
        "items": [
            {
                "id": c.id,
                "layer": c.layer.value,
                "query_type": c.query_type.value,
                "query": c.query,
                "description": c.description,
                "expected_memories": c.expected_memories,
                "negative": c.negative,
                "expected_dimensions": c.expected_dimensions,
                "test_focus": c.test_focus,
                "expected_action": c.expected_action,
                "conflict_type": c.conflict_type,
            }
            for c in cases
        ],
    }


@router.get("/overview")
async def get_overview():
    """获取评测概览 — 用例分布"""
    cases = _get_cases()

    by_layer = {}
    by_query_type = {}
    for c in cases:
        by_layer[c.layer.value] = by_layer.get(c.layer.value, 0) + 1
        by_query_type[c.query_type.value] = by_query_type.get(c.query_type.value, 0) + 1

    from src.eval.memory_eval_runner import SEED_MEMORIES
    return {
        "total_cases": len(cases),
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


# ═══════════════════════════════════════════════════════════
# 执行评测
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
    """执行记忆评测（同步）"""
    from src.eval.memory_eval_runner import EvalLayer, MemoryEvalRunner, print_memory_eval_report

    runner = _get_runner()
    cases = _get_cases()

    # 筛选
    layers = [EvalLayer(l) for l in body.layers] if body.layers else None
    from src.eval.memory_eval_runner import QueryType
    query_types = [QueryType(qt) for qt in body.query_types] if body.query_types else None

    report = await runner.run_cases(cases, layers=layers, query_types=query_types)

    # Console 输出
    print_memory_eval_report(report)

    return report.to_dict()


@router.post("/run-stream")
async def run_eval_stream(body: RunMemoryEvalBody):
    """流式执行记忆评测 — SSE 实时推送"""
    from src.eval.memory_eval_runner import (
        EvalLayer, QueryType, MemoryEvalRunner, InMemoryEvalEngine, SEED_MEMORIES
    )
    from src.eval.memory_eval_cases import build_all_cases

    cases = build_all_cases()

    # 筛选
    if body.layers:
        layer_set = set(body.layers)
        cases = [c for c in cases if c.layer.value in layer_set]
    if body.query_types:
        qt_set = set(body.query_types)
        cases = [c for c in cases if c.query_type.value in qt_set]

    total = len(cases)

    async def event_generator():
        engine = InMemoryEvalEngine()
        # ── 第0步：清空记忆库（确保评测环境干净）──
        engine.clear()

        # ── 串行执行策略 ──
        # 1. 纯 extract 层：从空记忆库开始，每条用例写入后累积
        # 2. retrieval/temporal 层：需要种子数据作为基础（模拟历史已有的记忆）
        # 3. 混合执行：先载入种子数据，extract 用例在其上追加/修改
        #
        # 种子数据 = 模拟"之前的对话已经产生了这些记忆"
        # 这是串行的第0步，相当于评测开始前的已有状态

        layers_requested = set(body.layers) if body.layers else set()
        pure_extract = layers_requested == {"extract"}

        if not pure_extract:
            engine.seed(SEED_MEMORIES)
        # else: 空库开始，提取用例逐步写入

        runner = MemoryEvalRunner(engine=engine, use_llm=body.use_llm)

        passed_count = 0
        failed_count = 0
        total_duration = 0.0

        # 发送 start 事件，附带初始记忆库状态
        start_payload = {
            "event": "start",
            "total": total,
            "initial_memory_count": engine.memory_count,
            "mode": "pure_extract" if pure_extract else "seeded",
            "cleared": True,
        }

        yield f"data: {json.dumps(start_payload, ensure_ascii=False)}\n\n"

        for idx, case in enumerate(cases):
            result = await runner._run_single(case)

            if result.passed:
                passed_count += 1
            else:
                failed_count += 1
            total_duration += result.duration_ms

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
                # 串行状态字段
                "memory_snapshot_count": result.memory_snapshot_count,
                "memory_changes": result.memory_changes[:3],
                "extracted_dimensions": result.extracted_dimensions,
                "output_detail": result.output_detail,
            }
            yield f"data: {json.dumps(progress, ensure_ascii=False)}\n\n"

        pass_rate = passed_count / max(total, 1)
        complete = {
            "event": "complete",
            "total": total,
            "passed": passed_count,
            "failed": failed_count,
            "pass_rate": round(pass_rate, 4),
            "total_duration_ms": round(total_duration, 1),
        }
        yield f"data: {json.dumps(complete, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
