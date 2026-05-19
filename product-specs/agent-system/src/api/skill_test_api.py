"""Skill 测试调试 REST API

路由前缀：/api/skills（挂载到 skill_api.py 的 router 上）

提供：
    - POST /api/skills/{api_key}/test/execute     完整执行测试
    - POST /api/skills/{api_key}/test/validate    验证测试用例
    - GET  /api/skills/{api_key}/test/cases       获取测试用例列表
    - POST /api/skills/{api_key}/test/cases       保存测试用例
    - PUT  /api/skills/{api_key}/test/cases/{id}  更新测试用例
    - DELETE /api/skills/{api_key}/test/cases/{id} 删除测试用例
    - POST /api/skills/{api_key}/test/batch       批量执行测试用例
"""
from __future__ import annotations

import json
import logging
import time
import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from src.skills.test_runner import (
    SkillTestRunner, TestResult, TestCase, MockConfig,
    StepType, StepStatus,
)
from src.store.skill_dao import SkillDefinitionDAO

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/skills", tags=["skill-test"])

# 全局 TestRunner 实例
_test_runner: SkillTestRunner | None = None

# 测试用例存储（内存，后续可迁移到 DB）
_test_cases: dict[str, list[TestCase]] = {}  # skill_api_key -> [TestCase]


def get_test_runner() -> SkillTestRunner:
    global _test_runner
    if _test_runner is None:
        from src.skills.base import SkillRegistry
        # 尝试获取全局 SkillRegistry
        try:
            from server import _skill_registry
            registry = _skill_registry
        except (ImportError, AttributeError):
            registry = None

        if registry is None:
            registry = SkillRegistry()
            registry.load_from_db(tenant_id=0)

        _test_runner = SkillTestRunner(skill_registry=registry)
    return _test_runner


def set_test_runner(runner: SkillTestRunner) -> None:
    global _test_runner
    _test_runner = runner


# ═══════════════════════════════════════════════════════════
# Pydantic 请求模型
# ═══════════════════════════════════════════════════════════

class MockConfigBody(BaseModel):
    tool_name: str
    mock_response: str
    enabled: bool = True


class ExecuteTestBody(BaseModel):
    """完整执行测试请求"""
    arguments: dict[str, str] = Field(default_factory=dict)
    mocks: list[MockConfigBody] = Field(default_factory=list)


class TestCaseBody(BaseModel):
    """测试用例请求体"""
    name: str = Field(..., min_length=1, max_length=100)
    arguments: dict[str, str] = Field(default_factory=dict)
    expected_keywords: list[str] = Field(default_factory=list)
    excluded_keywords: list[str] = Field(default_factory=list)
    expected_tools: list[str] = Field(default_factory=list)
    max_duration_ms: int = Field(default=0, ge=0)
    mocks: list[MockConfigBody] = Field(default_factory=list)


class BatchTestBody(BaseModel):
    """批量执行请求"""
    case_ids: list[str] = Field(default_factory=list)  # 空=执行全部


# ═══════════════════════════════════════════════════════════
# 完整执行测试
# ═══════════════════════════════════════════════════════════

@router.post("/{api_key}/test/execute")
async def execute_test(api_key: str, body: ExecuteTestBody, tenant_id: int = Query(0)):
    """完整执行 Skill 测试 — 返回逐步执行链路"""
    runner = get_test_runner()

    # 转换 Mock 配置
    mocks = [
        MockConfig(tool_name=m.tool_name, mock_response=m.mock_response, enabled=m.enabled)
        for m in body.mocks
    ] if body.mocks else None

    result = await runner.execute_full(
        skill_api_key=api_key,
        arguments=body.arguments,
        mocks=mocks,
        tenant_id=tenant_id,
    )

    return result.to_dict()


# ═══════════════════════════════════════════════════════════
# 测试用例管理
# ═══════════════════════════════════════════════════════════

@router.get("/{api_key}/test/cases")
async def list_test_cases(api_key: str):
    """获取 Skill 的测试用例列表"""
    cases = _test_cases.get(api_key, [])
    return {"items": [c.to_dict() for c in cases], "total": len(cases)}


@router.post("/{api_key}/test/cases", status_code=201)
async def create_test_case(api_key: str, body: TestCaseBody):
    """创建测试用例"""
    case = TestCase(
        id=f"tc_{uuid.uuid4().hex[:8]}",
        skill_api_key=api_key,
        name=body.name,
        arguments=body.arguments,
        expected_keywords=body.expected_keywords,
        excluded_keywords=body.excluded_keywords,
        expected_tools=body.expected_tools,
        max_duration_ms=body.max_duration_ms,
        mocks=[MockConfig(m.tool_name, m.mock_response, m.enabled) for m in body.mocks],
        last_result="not_run",
        created_at=int(time.time() * 1000),
    )

    if api_key not in _test_cases:
        _test_cases[api_key] = []
    _test_cases[api_key].append(case)

    return case.to_dict()


@router.put("/{api_key}/test/cases/{case_id}")
async def update_test_case(api_key: str, case_id: str, body: TestCaseBody):
    """更新测试用例"""
    cases = _test_cases.get(api_key, [])
    for i, c in enumerate(cases):
        if c.id == case_id:
            cases[i].name = body.name
            cases[i].arguments = body.arguments
            cases[i].expected_keywords = body.expected_keywords
            cases[i].excluded_keywords = body.excluded_keywords
            cases[i].expected_tools = body.expected_tools
            cases[i].max_duration_ms = body.max_duration_ms
            cases[i].mocks = [MockConfig(m.tool_name, m.mock_response, m.enabled) for m in body.mocks]
            return cases[i].to_dict()

    raise HTTPException(status_code=404, detail=f"测试用例 '{case_id}' 不存在")


@router.delete("/{api_key}/test/cases/{case_id}")
async def delete_test_case(api_key: str, case_id: str):
    """删除测试用例"""
    cases = _test_cases.get(api_key, [])
    for i, c in enumerate(cases):
        if c.id == case_id:
            cases.pop(i)
            return {"message": f"测试用例 '{case_id}' 已删除"}

    raise HTTPException(status_code=404, detail=f"测试用例 '{case_id}' 不存在")


# ═══════════════════════════════════════════════════════════
# 验证测试用例
# ═══════════════════════════════════════════════════════════

@router.post("/{api_key}/test/validate")
async def validate_test(api_key: str, body: ExecuteTestBody, tenant_id: int = Query(0)):
    """执行测试并验证结果（需要先有测试用例）"""
    runner = get_test_runner()
    cases = _test_cases.get(api_key, [])

    if not cases:
        raise HTTPException(status_code=400, detail="该 Skill 没有配置测试用例")

    # 找到匹配参数的用例（或第一个）
    target_case = cases[0]
    for c in cases:
        if c.arguments == body.arguments:
            target_case = c
            break

    mocks = [
        MockConfig(tool_name=m.tool_name, mock_response=m.mock_response, enabled=m.enabled)
        for m in body.mocks
    ] if body.mocks else [
        MockConfig(m.tool_name, m.mock_response, m.enabled)
        for m in target_case.mocks
    ]

    result = await runner.execute_full(
        skill_api_key=api_key,
        arguments=body.arguments or target_case.arguments,
        mocks=mocks,
        tenant_id=tenant_id,
    )

    validation = runner.validate_result(result, target_case)

    # 更新用例状态
    target_case.last_result = "pass" if validation["passed"] else "fail"
    target_case.last_run_at = int(time.time() * 1000)

    return {
        "test_result": result.to_dict(),
        "validation": validation,
        "test_case": target_case.to_dict(),
    }


# ═══════════════════════════════════════════════════════════
# 批量执行
# ═══════════════════════════════════════════════════════════

@router.post("/{api_key}/test/batch")
async def batch_test(api_key: str, body: BatchTestBody, tenant_id: int = Query(0)):
    """批量执行测试用例"""
    runner = get_test_runner()
    cases = _test_cases.get(api_key, [])

    if not cases:
        raise HTTPException(status_code=400, detail="该 Skill 没有配置测试用例")

    # 筛选要执行的用例
    if body.case_ids:
        target_cases = [c for c in cases if c.id in body.case_ids]
    else:
        target_cases = cases

    results = []
    for case in target_cases:
        mocks = [MockConfig(m.tool_name, m.mock_response, m.enabled) for m in case.mocks]

        result = await runner.execute_full(
            skill_api_key=api_key,
            arguments=case.arguments,
            mocks=mocks if mocks else None,
            tenant_id=tenant_id,
        )

        validation = runner.validate_result(result, case)

        # 更新用例状态
        case.last_result = "pass" if validation["passed"] else "fail"
        case.last_run_at = int(time.time() * 1000)

        results.append({
            "case_id": case.id,
            "case_name": case.name,
            "passed": validation["passed"],
            "failures": validation["failures"],
            "duration_ms": round(result.total_duration_ms, 1),
            "status": result.status,
        })

    total = len(results)
    passed = sum(1 for r in results if r["passed"])

    return {
        "total": total,
        "passed": passed,
        "failed": total - passed,
        "pass_rate": round(passed / max(total, 1), 3),
        "results": results,
    }
