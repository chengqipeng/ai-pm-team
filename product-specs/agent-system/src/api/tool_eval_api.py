"""Tool 评测 REST API（v2 — DB 持久化 + 分类/方法级执行）

路由前缀：/api/eval/tools

核心能力：
    - 用例存储在数据库，支持自动组合生成
    - 按工具分类执行（如执行 query_schema 下所有用例）
    - 按方法级执行（如执行 query_schema/list_entities 下所有用例）
    - 参数组合自动覆盖正向 + 逆向场景
    - 报告持久化

路由：
    GET    /api/eval/tools/catalog            获取用例目录树（工具→方法→分类）
    GET    /api/eval/tools/cases              查询用例列表（支持筛选）
    POST   /api/eval/tools/cases              创建自定义用例
    DELETE /api/eval/tools/cases/{id}         删除用例
    POST   /api/eval/tools/generate           自动生成参数组合用例
    POST   /api/eval/tools/run                执行评测（支持工具/方法/分类筛选）
    POST   /api/eval/tools/run-single         执行单个临时用例
    GET    /api/eval/tools/reports            历史报告列表
    GET    /api/eval/tools/reports/{key}      报告详情
    POST   /api/eval/tools/sync-presets       将预置用例同步到 DB
"""
from __future__ import annotations

import logging
import time
import uuid
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/eval/tools", tags=["tool-eval"])


# ═══════════════════════════════════════════════════════════
# Pydantic 请求模型
# ═══════════════════════════════════════════════════════════

class AssertionBody(BaseModel):
    type: str
    target: str = "content"
    expected: Any = None
    description: str = ""


class RunEvalBody(BaseModel):
    """执行评测请求 — 支持多维度筛选"""
    # 兼容旧前端
    suite_id: str = "suite_default"
    # 筛选维度（可组合）
    tool_names: list[str] = Field(default_factory=list)      # 按工具: ["query_schema"]
    method_names: list[str] = Field(default_factory=list)    # 按方法: ["list_entities", "entity"]
    categories: list[str] = Field(default_factory=list)      # 按分类: ["normal", "error"]
    case_ids: list[int] = Field(default_factory=list)        # 按用例 ID
    tags: list[str] = Field(default_factory=list)            # 按标签: ["positive"]


class RunSingleBody(BaseModel):
    """执行单个临时用例"""
    tool_name: str
    input_data: dict = Field(default_factory=dict)
    assertions: list[AssertionBody] = Field(default_factory=list)
    setup_steps: list[dict] = Field(default_factory=list)
    cleanup_steps: list[dict] = Field(default_factory=list)


class CreateCaseBody(BaseModel):
    """创建自定义用例"""
    tool_name: str
    method_name: str = ""
    description: str = ""
    input_data: dict = Field(default_factory=dict)
    assertions: list[AssertionBody] = Field(default_factory=list)
    category: str = "normal"
    setup_steps: list[dict] = Field(default_factory=list)
    cleanup_steps: list[dict] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    priority: int = 0


class GenerateCasesBody(BaseModel):
    """自动生成参数组合用例"""
    tool_name: str | None = None      # None=全部工具
    method_name: str | None = None    # None=该工具全部方法
    max_positive: int = 50            # 正向用例上限
    save_to_db: bool = True           # 是否直接存入 DB
    overwrite: bool = False           # 是否覆盖已有用例


class SyncPresetsBody(BaseModel):
    """同步预置用例到 DB"""
    overwrite: bool = False


# ═══════════════════════════════════════════════════════════
# 辅助函数
# ═══════════════════════════════════════════════════════════

def _get_runner():
    from src.eval.tool_eval_runner import ToolEvalRunner
    return ToolEvalRunner()


def _body_to_assertion(body: AssertionBody):
    from src.eval.tool_eval_runner import Assertion, AssertionType
    return Assertion(
        type=AssertionType(body.type),
        target=body.target,
        expected=body.expected,
        description=body.description,
    )


def _get_suite_id() -> int:
    """获取默认 suite_id（兼容 DB 不可用时降级）"""
    try:
        from src.store.eval_dao import EvalSuiteDAO
        return EvalSuiteDAO.get_default_suite_id()
    except Exception:
        return 0  # fallback, 调用方应 catch 并降级


# ═══════════════════════════════════════════════════════════
# 目录/概览
# ═══════════════════════════════════════════════════════════

@router.get("/catalog")
async def get_catalog():
    """获取用例目录树

    返回结构：
    {
      "query_schema": {
        "methods": ["list_entities", "entity", "entity_items", ...],
        "stats": {
          "list_entities": {"total": 5, "by_category": {"normal": 2, "error": 2, "boundary": 1}},
          ...
        },
        "total": 25
      },
      ...
    }
    """
    from src.store.eval_dao import EvalCaseDAO
    suite_id = _get_suite_id()
    count_data = EvalCaseDAO.count_by_tool(suite_id)
    tools_methods = EvalCaseDAO.get_tools_and_methods(suite_id)

    catalog = {}
    for tool, methods in tools_methods.items():
        tool_total = 0
        method_stats = {}
        for method in methods:
            if tool in count_data and method in count_data[tool]:
                stats = count_data[tool][method]
                method_stats[method] = stats
                tool_total += stats["total"]
        catalog[tool] = {
            "methods": methods,
            "stats": method_stats,
            "total": tool_total,
        }
    return {"catalog": catalog}


@router.get("/cases")
async def list_cases(
    tool_name: str | None = None,
    method_name: str | None = None,
    category: str | None = None,
    limit: int = 200,
    offset: int = 0,
):
    """查询用例列表 — 支持多维度筛选，必须从 DB 查询"""
    from src.store.eval_dao import EvalCaseDAO
    suite_id = _get_suite_id()
    cases = EvalCaseDAO.list_by_tool(
        suite_id, tool_name=tool_name, method_name=method_name,
        category=category, limit=limit, offset=offset,
    )
    return {
        "items": [c.to_dict() for c in cases],
        "total": len(cases),
        "filters": {"tool_name": tool_name, "method_name": method_name, "category": category},
    }


# ═══════════════════════════════════════════════════════════
# 用例管理
# ═══════════════════════════════════════════════════════════

@router.post("/cases", status_code=201)
async def create_case(body: CreateCaseBody):
    """创建自定义评测用例"""
    from src.store.eval_dao import EvalCaseDAO, EvalToolCase
    suite_id = _get_suite_id()
    case_key = f"custom_{uuid.uuid4().hex[:8]}"

    case = EvalToolCase(
        suite_id=suite_id,
        case_key=case_key,
        tool_name=body.tool_name,
        method_name=body.method_name,
        description=body.description,
        category=body.category,
        input_data=body.input_data,
        assertions=[a.dict() for a in body.assertions],
        setup_steps=body.setup_steps,
        cleanup_steps=body.cleanup_steps,
        tags=body.tags,
        priority=body.priority,
        generated_by="manual",
    )
    case_id = EvalCaseDAO.insert(case)
    case.id = case_id
    return case.to_dict()


@router.delete("/cases/{case_id}")
async def delete_case(case_id: int):
    """删除用例"""
    from src.store.eval_dao import EvalCaseDAO
    success = EvalCaseDAO.delete_by_id(case_id)
    if not success:
        raise HTTPException(status_code=404, detail=f"用例 {case_id} 不存在")
    return {"message": f"用例 {case_id} 已删除"}


# ═══════════════════════════════════════════════════════════
# 自动生成
# ═══════════════════════════════════════════════════════════

@router.post("/generate")
async def generate_cases(body: GenerateCasesBody):
    """自动生成参数组合用例

    根据工具的 input_schema 自动推导所有参数组合，覆盖：
    - 正向：合法参数的笛卡尔积/pairwise 组合
    - 逆向：单参数非法值
    - 边界：边界值探测
    - 缺失：必填参数缺失
    """
    from src.eval.case_combination_generator import generate_all_cases, generate_cases_summary

    # 先获取概览
    summary = generate_cases_summary(body.tool_name, body.method_name)

    # 生成用例
    cases = generate_all_cases(
        tool_name=body.tool_name,
        method_name=body.method_name,
        max_positive=body.max_positive,
    )

    result = {
        "summary": summary,
        "total_generated": len(cases),
        "saved_to_db": False,
    }

    if body.save_to_db and cases:
        from src.store.eval_dao import EvalCaseDAO, EvalToolCase
        suite_id = _get_suite_id()

        # 如果覆盖模式，先删除已有自动生成的用例
        if body.overwrite:
            if body.tool_name:
                EvalCaseDAO.delete_by_tool(suite_id, body.tool_name, body.method_name)
            # else: 不做全量删除（太危险）

        # 转换并插入
        db_cases = []
        for c in cases:
            # 从 description 推断 method_name
            method_name = ""
            for tool_specs in []:
                pass
            # 从 input_data 推断
            method_name = (
                c.input_data.get("query_type")
                or c.input_data.get("action")
                or ""
            )

            db_case = EvalToolCase(
                suite_id=suite_id,
                case_key=c.id,
                tool_name=c.tool_name,
                method_name=method_name,
                description=c.description,
                category=c.category,
                input_data=c.input_data,
                assertions=[a.to_dict() for a in c.assertions],
                setup_steps=c.setup_steps,
                cleanup_steps=c.cleanup_steps if hasattr(c, 'cleanup_steps') else [],
                tags=[],
                generated_by="auto_combination",
            )
            db_cases.append(db_case)

        inserted = EvalCaseDAO.batch_insert(db_cases)
        result["saved_to_db"] = True
        result["inserted_count"] = inserted

    # 返回生成的用例预览（前 20 条）
    result["preview"] = [c.to_dict() for c in cases[:20]]

    return result


@router.post("/sync-presets")
async def sync_presets(body: SyncPresetsBody):
    """将内存预置用例同步到 DB"""
    from src.eval.tool_eval_presets import build_default_suite
    from src.store.eval_dao import EvalCaseDAO, EvalToolCase

    suite = build_default_suite()
    suite_id = _get_suite_id()

    count = 0
    for c in suite.cases:
        # 推断 method_name
        method_name = (
            c.input_data.get("query_type")
            or c.input_data.get("action")
            or ""
        )

        db_case = EvalToolCase(
            suite_id=suite_id,
            case_key=c.id,
            tool_name=c.tool_name,
            method_name=method_name,
            description=c.description,
            category=c.category,
            input_data=c.input_data,
            assertions=[a.to_dict() for a in c.assertions],
            setup_steps=c.setup_steps,
            cleanup_steps=c.cleanup_steps,
            generated_by="preset",
        )
        EvalCaseDAO.insert(db_case)
        count += 1

    return {"message": f"同步完成，共 {count} 条用例", "count": count}


# ═══════════════════════════════════════════════════════════
# 评测执行
# ═══════════════════════════════════════════════════════════

@router.post("/run")
async def run_eval(body: RunEvalBody):
    """执行评测 — 支持按工具/方法/分类/标签筛选

    典型用法：
    - 执行全部用例：{}
    - 执行 query_schema 下所有用例：{"tool_names": ["query_schema"]}
    - 执行 query_schema/list_entities：{"tool_names": ["query_schema"], "method_names": ["list_entities"]}
    - 只执行逆向用例：{"categories": ["error"]}
    """
    from src.eval.tool_eval_runner import ToolEvalCase, ToolEvalSuite, Assertion, AssertionType, print_report

    # 加载用例 — 必须从 DB 查询
    from src.store.eval_dao import EvalCaseDAO
    suite_id = _get_suite_id()
    if suite_id == 0:
        raise HTTPException(status_code=500, detail="DB suite 不可用，请先执行建表迁移")

    # 按筛选条件分别查询
    all_cases_raw = []
    if body.tool_names:
        for tn in body.tool_names:
            method_filter = body.method_names[0] if len(body.method_names) == 1 else None
            category_filter = body.categories[0] if len(body.categories) == 1 else None
            all_cases_raw.extend(
                EvalCaseDAO.list_by_tool(
                    suite_id, tool_name=tn,
                    method_name=method_filter,
                    category=category_filter,
                )
            )
    else:
        all_cases_raw = EvalCaseDAO.list_by_tool(suite_id)

    if not all_cases_raw:
        raise HTTPException(status_code=400, detail="DB 中无用例，请先同步预置用例或自动生成")

    # 进一步筛选（多方法/多分类组合）
    if body.method_names and len(body.method_names) > 1:
        all_cases_raw = [c for c in all_cases_raw if c.method_name in body.method_names]
    if body.categories and len(body.categories) > 1:
        all_cases_raw = [c for c in all_cases_raw if c.category in body.categories]
    if body.tags:
        all_cases_raw = [c for c in all_cases_raw if any(t in c.tags for t in body.tags)]

    # 转为 ToolEvalCase
    cases = []
    for c in all_cases_raw:
        assertions = []
        for a_dict in c.assertions:
            assertions.append(Assertion(
                type=AssertionType(a_dict["type"]),
                target=a_dict.get("target", "content"),
                expected=a_dict.get("expected"),
                description=a_dict.get("description", ""),
            ))
        cases.append(ToolEvalCase(
            id=c.case_key,
            tool_name=c.tool_name,
            description=c.description,
            input_data=c.input_data,
            assertions=assertions,
            category=c.category,
            setup_steps=c.setup_steps,
            cleanup_steps=c.cleanup_steps,
            timeout_ms=c.timeout_ms,
        ))

    if not cases:
        raise HTTPException(status_code=400, detail="筛选后无可执行的用例")

    # 构建 Suite 并执行
    filtered_suite = ToolEvalSuite(
        id="suite_default",
        name="Tool 评测",
        description="",
        cases=cases,
    )

    runner = _get_runner()
    report = await runner.run_suite(filtered_suite)
    print_report(report)

    # 构建按 method 维度的统计
    by_method: dict[str, dict] = {}
    for r in report.results:
        # 从 input_data 推断 method
        method = ""
        if r.tool_result:
            pass  # 无法直接从 result 获取
        # 从 case 的 input_data 推断
        for c in cases:
            if c.id == r.case_id:
                method = c.input_data.get("query_type") or c.input_data.get("action") or "_default"
                break
        key = f"{r.tool_name}/{method}"
        if key not in by_method:
            by_method[key] = {"total": 0, "passed": 0, "failed": 0}
        by_method[key]["total"] += 1
        if r.passed:
            by_method[key]["passed"] += 1
        else:
            by_method[key]["failed"] += 1

    # 响应
    report_dict = report.to_dict()
    report_dict["report_id"] = f"rpt_{uuid.uuid4().hex[:8]}"
    report_dict["by_method"] = by_method
    report_dict["created_at"] = int(time.time() * 1000)
    report_dict["filters"] = {
        "tool_names": body.tool_names,
        "method_names": body.method_names,
        "categories": body.categories,
    }

    # 尝试持久化报告
    try:
        from src.store.eval_dao import EvalReportDAO, EvalCaseResultDAO
        suite_id = _get_suite_id()
        report_key = EvalReportDAO.create_report(
            suite_id=suite_id,
            filter_tools=body.tool_names,
            filter_methods=body.method_names,
            filter_categories=body.categories,
        )
        EvalReportDAO.complete_report(
            report_key=report_key,
            total=report.total, passed=report.passed,
            failed=report.failed, error_count=report.error,
            pass_rate=report.pass_rate,
            total_duration_ms=report.total_duration_ms,
            by_tool=report.by_tool, by_method=by_method,
            by_category=report.by_category, failures=report.failures,
        )
        report_dict["report_id"] = report_key

        # 持久化每条用例的执行结果（含 input_data + tool_output）
        case_results_for_db = []
        for r in report.results:
            case_results_for_db.append({
                "case_key": r.case_id,
                "tool_name": r.tool_name,
                "method_name": "",
                "category": r.category,
                "passed": r.passed,
                "duration_ms": r.duration_ms,
                "input_data": r.input_data,
                "tool_output": (r.tool_result.content if r.tool_result else "").replace("\x00", ""),
                "is_error": r.tool_result.is_error if r.tool_result else False,
                "assertion_results": [a.to_dict() for a in r.assertion_results],
                "error_message": (r.error or "").replace("\x00", ""),
            })
        # 获取报告 DB id
        from src.store.pg_pool import get_conn
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute("SELECT id FROM ai_eval_tool_report WHERE report_key = %s", (report_key,))
            row = cur.fetchone()
            if row:
                EvalCaseResultDAO.batch_insert(row[0], case_results_for_db)
    except Exception as e:
        logger.warning(f"报告持久化失败: {e}")

    return report_dict


@router.post("/run-stream")
async def run_eval_stream(body: RunEvalBody):
    """流式执行评测 — 通过 SSE 实时推送每条用例执行进度

    事件类型：
    - start: 开始 {total}
    - progress: 单条用例完成 {index, total, case_id, passed, ...}
    - complete: 全部完毕 {report_id, total, passed, failed, pass_rate}
    """
    import json as _json
    from fastapi.responses import StreamingResponse
    from src.eval.tool_eval_runner import ToolEvalCase, Assertion, AssertionType

    # 加载用例
    from src.store.eval_dao import EvalCaseDAO
    suite_id = _get_suite_id()
    if suite_id == 0:
        raise HTTPException(status_code=500, detail="DB suite 不可用")

    all_cases_raw = []
    if body.tool_names:
        for tn in body.tool_names:
            method_filter = body.method_names[0] if len(body.method_names) == 1 else None
            category_filter = body.categories[0] if len(body.categories) == 1 else None
            all_cases_raw.extend(
                EvalCaseDAO.list_by_tool(suite_id, tool_name=tn, method_name=method_filter, category=category_filter)
            )
    else:
        all_cases_raw = EvalCaseDAO.list_by_tool(suite_id)

    if not all_cases_raw:
        raise HTTPException(status_code=400, detail="DB 中无用例")

    if body.method_names and len(body.method_names) > 1:
        all_cases_raw = [c for c in all_cases_raw if c.method_name in body.method_names]
    if body.categories and len(body.categories) > 1:
        all_cases_raw = [c for c in all_cases_raw if c.category in body.categories]
    if body.tags:
        all_cases_raw = [c for c in all_cases_raw if any(t in c.tags for t in body.tags)]

    cases = []
    for c in all_cases_raw:
        assertions = []
        for a_dict in c.assertions:
            assertions.append(Assertion(
                type=AssertionType(a_dict["type"]),
                target=a_dict.get("target", "content"),
                expected=a_dict.get("expected"),
                description=a_dict.get("description", ""),
            ))
        cases.append(ToolEvalCase(
            id=c.case_key, tool_name=c.tool_name, description=c.description,
            input_data=c.input_data, assertions=assertions, category=c.category,
            setup_steps=c.setup_steps, cleanup_steps=c.cleanup_steps, timeout_ms=c.timeout_ms,
        ))

    if not cases:
        raise HTTPException(status_code=400, detail="筛选后无可执行的用例")

    total = len(cases)

    async def event_generator():
        runner = _get_runner()
        passed_count = 0
        failed_count = 0
        results_all = []

        yield f"data: {_json.dumps({'event': 'start', 'total': total}, ensure_ascii=False)}\n\n"

        for idx, case in enumerate(cases):
            result = await runner.run_case(case)
            results_all.append(result)
            if result.passed:
                passed_count += 1
            else:
                failed_count += 1

            progress_data = {
                "event": "progress",
                "index": idx + 1,
                "total": total,
                "case_id": result.case_id,
                "tool_name": result.tool_name,
                "description": result.description,
                "category": result.category,
                "passed": result.passed,
                "duration_ms": round(result.duration_ms, 1),
                "input_data": result.input_data,
                "tool_output": result.tool_result.content[:2000] if result.tool_result else None,
                "is_error": result.tool_result.is_error if result.tool_result else None,
                "assertion_results": [a.to_dict() for a in result.assertion_results],
                "error": result.error,
                "running_passed": passed_count,
                "running_failed": failed_count,
            }
            yield f"data: {_json.dumps(progress_data, ensure_ascii=False)}\n\n"

        # 持久化
        total_duration = sum(r.duration_ms for r in results_all)
        pass_rate = passed_count / max(total, 1)
        report_key = ""
        try:
            from src.store.eval_dao import EvalReportDAO, EvalCaseResultDAO
            report_key = EvalReportDAO.create_report(
                suite_id=suite_id, filter_tools=body.tool_names,
                filter_methods=body.method_names, filter_categories=body.categories,
            )
            by_tool = {}
            for r in results_all:
                if r.tool_name not in by_tool:
                    by_tool[r.tool_name] = {"total": 0, "passed": 0, "failed": 0}
                by_tool[r.tool_name]["total"] += 1
                if r.passed:
                    by_tool[r.tool_name]["passed"] += 1
                else:
                    by_tool[r.tool_name]["failed"] += 1
            EvalReportDAO.complete_report(
                report_key=report_key, total=total, passed=passed_count,
                failed=failed_count, error_count=0, pass_rate=pass_rate,
                total_duration_ms=total_duration, by_tool=by_tool,
                by_method={}, by_category={}, failures=[],
            )
            case_results_for_db = [{
                "case_key": r.case_id, "tool_name": r.tool_name, "method_name": "",
                "category": r.category, "passed": r.passed, "duration_ms": r.duration_ms,
                "input_data": r.input_data,
                "tool_output": (r.tool_result.content if r.tool_result else "").replace("\x00", ""),
                "is_error": r.tool_result.is_error if r.tool_result else False,
                "assertion_results": [a.to_dict() for a in r.assertion_results],
                "error_message": (r.error or "").replace("\x00", ""),
            } for r in results_all]
            from src.store.pg_pool import get_conn
            with get_conn() as conn:
                cur = conn.cursor()
                cur.execute("SELECT id FROM ai_eval_tool_report WHERE report_key = %s", (report_key,))
                row = cur.fetchone()
                if row:
                    EvalCaseResultDAO.batch_insert(row[0], case_results_for_db)
        except Exception as e:
            logger.warning(f"流式报告持久化失败: {e}")

        complete_data = {
            "event": "complete",
            "report_id": report_key,
            "total": total,
            "passed": passed_count,
            "failed": failed_count,
            "pass_rate": round(pass_rate, 4),
            "total_duration_ms": round(total_duration, 1),
        }
        yield f"data: {_json.dumps(complete_data, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/run-single")
async def run_single_case(body: RunSingleBody):
    """执行单个临时用例（无需存入 DB）"""
    from src.eval.tool_eval_runner import ToolEvalCase

    case = ToolEvalCase(
        id=f"adhoc_{uuid.uuid4().hex[:6]}",
        tool_name=body.tool_name,
        description=f"临时用例 - {body.tool_name}",
        input_data=body.input_data,
        assertions=[_body_to_assertion(a) for a in body.assertions],
        setup_steps=body.setup_steps,
        cleanup_steps=body.cleanup_steps,
    )

    runner = _get_runner()
    result = await runner.run_case(case)

    status = "✅ PASS" if result.passed else "❌ FAIL"
    print(f"\n[Tool 评测] {status} | {body.tool_name} | {result.duration_ms:.0f}ms")
    if not result.passed:
        for ar in result.assertion_results:
            if not ar.passed:
                print(f"  → {ar.assertion.type.value}: {ar.message}")

    return result.to_dict()


# ═══════════════════════════════════════════════════════════
# 报告管理
# ═══════════════════════════════════════════════════════════

@router.get("/reports")
async def list_reports(limit: int = 20):
    """获取历史报告列表"""
    try:
        from src.store.eval_dao import EvalReportDAO
        reports = EvalReportDAO.list_reports(limit=limit)
        return {"items": reports, "total": len(reports)}
    except Exception:
        return {"items": [], "total": 0, "source": "db_unavailable"}


@router.get("/reports/{report_key}")
async def get_report(report_key: str):
    """获取报告详情（含每条用例的 input/output）"""
    from src.store.eval_dao import EvalReportDAO, EvalCaseResultDAO
    report = EvalReportDAO.get_report(report_key)
    if not report:
        raise HTTPException(status_code=404, detail=f"报告 '{report_key}' 不存在")

    # 加载用例级执行结果
    from src.store.pg_pool import get_conn
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT id FROM ai_eval_tool_report WHERE report_key = %s", (report_key,))
        row = cur.fetchone()
        if row:
            report["results"] = EvalCaseResultDAO.list_by_report(row[0])

    return report


# ═══════════════════════════════════════════════════════════
# 兼容旧接口（保留）
# ═══════════════════════════════════════════════════════════

@router.get("/suites")
async def list_suites():
    """获取可用评测集列表"""
    from src.store.eval_dao import EvalCaseDAO
    suite_id = _get_suite_id()
    tools_methods = EvalCaseDAO.get_tools_and_methods(suite_id)
    cases_raw = EvalCaseDAO.list_by_tool(suite_id, limit=2000)
    return {
        "items": [{
            "id": "suite_default",
            "name": "Tool 评测 — 默认全量",
            "description": "覆盖所有内置工具的正常/异常/边界/副作用场景",
            "total_cases": len(cases_raw),
            "tools_covered": list(tools_methods.keys()),
            "methods_covered": tools_methods,
        }],
    }


@router.get("/suites/{suite_id}")
async def get_suite(suite_id: str):
    """获取评测集详情（含所有用例）— 必须从 DB 查询"""
    from src.store.eval_dao import EvalCaseDAO
    db_suite_id = _get_suite_id()
    cases_raw = EvalCaseDAO.list_by_tool(db_suite_id, limit=2000)
    cases_list = []
    for c in cases_raw:
        cases_list.append({
            "id": c.case_key,
            "tool_name": c.tool_name,
            "description": c.description,
            "input_data": c.input_data,
            "assertions": c.assertions,
            "category": c.category,
            "setup_steps": c.setup_steps,
            "cleanup_steps": c.cleanup_steps,
            "timeout_ms": c.timeout_ms,
        })
    return {
        "id": "suite_default",
        "name": "Tool 评测 — 默认全量",
        "description": "覆盖所有内置工具的正常/异常/边界/副作用场景",
        "cases": cases_list,
        "total": len(cases_list),
    }
