"""Tool 评测执行引擎

设计原则：
    1. 直接调用 Tool.call()，不经过 Agent 推理层
    2. 每个 TestCase 执行前重置 Backend 数据（保证隔离性）
    3. 支持正常/异常/边界/副作用四类断言
    4. 结果输出到 Console（结构化格式）

使用方式：
    runner = ToolEvalRunner()
    result = await runner.run_case(case)
    report = await runner.run_suite(suite)
"""
from __future__ import annotations

import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from src.tools.base import Tool, ToolRegistry
from src.core.dtypes import ToolResult

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════
# 数据模型
# ═══════════════════════════════════════════════════════════

class AssertionType(str, Enum):
    """断言类型"""
    EQUALS = "equals"               # 精确匹配字段值
    CONTAINS = "contains"           # 包含子串
    NOT_CONTAINS = "not_contains"   # 不包含子串
    IS_ERROR = "is_error"           # 期望返回错误
    NOT_ERROR = "not_error"         # 期望不返回错误
    JSON_PATH = "json_path"         # JSON 路径取值断言
    REGEX = "regex"                 # 正则匹配
    TYPE_CHECK = "type_check"       # 类型校验（int/str/list/dict）
    RANGE = "range"                 # 数值范围
    LENGTH = "length"               # 数组/字符串长度
    SIDE_EFFECT = "side_effect"     # 副作用验证（执行后再查一次）


@dataclass
class Assertion:
    """单条断言规则"""
    type: AssertionType
    # 断言目标：content / is_error / json_path 表达式
    target: str = "content"
    # 期望值（含义取决于 type）
    expected: Any = None
    # 可选描述
    description: str = ""

    def to_dict(self) -> dict:
        return {
            "type": self.type.value,
            "target": self.target,
            "expected": self.expected,
            "description": self.description,
        }


@dataclass
class ToolEvalCase:
    """单个工具评测用例"""
    id: str = ""
    tool_name: str = ""
    description: str = ""
    # 工具输入参数
    input_data: dict = field(default_factory=dict)
    # 断言列表
    assertions: list[Assertion] = field(default_factory=list)
    # 标签（用于分类：normal / error / boundary / side_effect）
    category: str = "normal"
    # 前置操作（如先 create 再 query 验证副作用）
    setup_steps: list[dict] = field(default_factory=list)
    # 后置清理（用例执行完成后清理初始化数据，保证环境干净）
    cleanup_steps: list[dict] = field(default_factory=list)
    # 超时 ms
    timeout_ms: int = 10000

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "tool_name": self.tool_name,
            "description": self.description,
            "input_data": self.input_data,
            "assertions": [a.to_dict() for a in self.assertions],
            "category": self.category,
            "setup_steps": self.setup_steps,
            "cleanup_steps": self.cleanup_steps,
            "timeout_ms": self.timeout_ms,
        }


@dataclass
class ToolEvalSuite:
    """工具评测集"""
    id: str = ""
    name: str = ""
    description: str = ""
    cases: list[ToolEvalCase] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "cases": [c.to_dict() for c in self.cases],
            "total": len(self.cases),
        }


@dataclass
class AssertionResult:
    """单条断言验证结果"""
    passed: bool = False
    assertion: Assertion = field(default_factory=Assertion)
    actual_value: Any = None
    message: str = ""

    def to_dict(self) -> dict:
        return {
            "passed": self.passed,
            "type": self.assertion.type.value,
            "description": self.assertion.description,
            "expected": self.assertion.expected,
            "actual": str(self.actual_value)[:500] if self.actual_value is not None else None,
            "message": self.message,
        }


@dataclass
class CaseResult:
    """单个用例执行结果"""
    case_id: str = ""
    tool_name: str = ""
    description: str = ""
    category: str = ""
    passed: bool = False
    # 工具输入参数
    input_data: dict = field(default_factory=dict)
    # 工具原始返回
    tool_result: ToolResult | None = None
    # 断言详情
    assertion_results: list[AssertionResult] = field(default_factory=list)
    # 性能
    duration_ms: float = 0.0
    # 错误（执行级别错误，非业务错误）
    error: str = ""

    def to_dict(self) -> dict:
        return {
            "case_id": self.case_id,
            "tool_name": self.tool_name,
            "description": self.description,
            "category": self.category,
            "passed": self.passed,
            "duration_ms": round(self.duration_ms, 1),
            "input_data": self.input_data,
            "assertion_results": [a.to_dict() for a in self.assertion_results],
            "tool_output": self.tool_result.content if self.tool_result else None,
            "is_error": self.tool_result.is_error if self.tool_result else None,
            "error": self.error,
        }


@dataclass
class SuiteReport:
    """评测集报告"""
    suite_id: str = ""
    suite_name: str = ""
    total: int = 0
    passed: int = 0
    failed: int = 0
    error: int = 0
    pass_rate: float = 0.0
    total_duration_ms: float = 0.0
    # 按工具分组统计
    by_tool: dict = field(default_factory=dict)
    # 按分类统计
    by_category: dict = field(default_factory=dict)
    # 详细结果
    results: list[CaseResult] = field(default_factory=list)
    # 失败用例摘要
    failures: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "suite_id": self.suite_id,
            "suite_name": self.suite_name,
            "total": self.total,
            "passed": self.passed,
            "failed": self.failed,
            "error": self.error,
            "pass_rate": round(self.pass_rate, 4),
            "total_duration_ms": round(self.total_duration_ms, 1),
            "by_tool": self.by_tool,
            "by_category": self.by_category,
            "results": [r.to_dict() for r in self.results],
            "failures": self.failures,
        }


# ═══════════════════════════════════════════════════════════
# 断言引擎
# ═══════════════════════════════════════════════════════════

class AssertionEngine:
    """工具评测断言引擎"""

    def check(self, tool_result: ToolResult, assertion: Assertion) -> AssertionResult:
        """执行单条断言"""
        try:
            if assertion.type == AssertionType.IS_ERROR:
                return self._check_is_error(tool_result, assertion)
            elif assertion.type == AssertionType.NOT_ERROR:
                return self._check_not_error(tool_result, assertion)
            elif assertion.type == AssertionType.CONTAINS:
                return self._check_contains(tool_result, assertion)
            elif assertion.type == AssertionType.NOT_CONTAINS:
                return self._check_not_contains(tool_result, assertion)
            elif assertion.type == AssertionType.EQUALS:
                return self._check_equals(tool_result, assertion)
            elif assertion.type == AssertionType.JSON_PATH:
                return self._check_json_path(tool_result, assertion)
            elif assertion.type == AssertionType.REGEX:
                return self._check_regex(tool_result, assertion)
            elif assertion.type == AssertionType.TYPE_CHECK:
                return self._check_type(tool_result, assertion)
            elif assertion.type == AssertionType.RANGE:
                return self._check_range(tool_result, assertion)
            elif assertion.type == AssertionType.LENGTH:
                return self._check_length(tool_result, assertion)
            else:
                return AssertionResult(
                    passed=False, assertion=assertion,
                    message=f"未知断言类型: {assertion.type}",
                )
        except Exception as e:
            return AssertionResult(
                passed=False, assertion=assertion,
                message=f"断言执行异常: {e}",
            )

    def _check_is_error(self, result: ToolResult, assertion: Assertion) -> AssertionResult:
        passed = result.is_error is True
        return AssertionResult(
            passed=passed, assertion=assertion,
            actual_value=result.is_error,
            message="" if passed else f"期望 is_error=True，实际 is_error={result.is_error}",
        )

    def _check_not_error(self, result: ToolResult, assertion: Assertion) -> AssertionResult:
        passed = result.is_error is not True
        return AssertionResult(
            passed=passed, assertion=assertion,
            actual_value=result.is_error,
            message="" if passed else f"期望 is_error=False，实际 is_error={result.is_error}",
        )

    def _check_contains(self, result: ToolResult, assertion: Assertion) -> AssertionResult:
        content = result.content or ""
        expected = str(assertion.expected)
        passed = expected in content
        return AssertionResult(
            passed=passed, assertion=assertion,
            actual_value=content[:200],
            message="" if passed else f"内容中未找到 '{expected}'",
        )

    def _check_not_contains(self, result: ToolResult, assertion: Assertion) -> AssertionResult:
        content = result.content or ""
        expected = str(assertion.expected)
        passed = expected not in content
        return AssertionResult(
            passed=passed, assertion=assertion,
            actual_value=content[:200],
            message="" if passed else f"内容中不应包含 '{expected}'",
        )

    def _check_equals(self, result: ToolResult, assertion: Assertion) -> AssertionResult:
        content = result.content or ""
        # 尝试 JSON 解析后比较
        try:
            actual = json.loads(content)
            target = assertion.target
            if target != "content" and "." in target:
                # 支持简单的点分路径
                for key in target.split("."):
                    actual = actual[key] if isinstance(actual, dict) else actual[int(key)]
            passed = actual == assertion.expected
            return AssertionResult(
                passed=passed, assertion=assertion,
                actual_value=actual,
                message="" if passed else f"期望 {assertion.expected}，实际 {actual}",
            )
        except (json.JSONDecodeError, KeyError, IndexError, TypeError):
            passed = content.strip() == str(assertion.expected).strip()
            return AssertionResult(
                passed=passed, assertion=assertion,
                actual_value=content[:200],
                message="" if passed else f"值不匹配",
            )

    def _check_json_path(self, result: ToolResult, assertion: Assertion) -> AssertionResult:
        """JSON 路径取值断言 — target 为路径如 'data.status'，expected 为期望值"""
        content = result.content or ""
        try:
            data = json.loads(content)
            path = assertion.target
            value = data
            for key in path.split("."):
                if isinstance(value, dict):
                    value = value[key]
                elif isinstance(value, list):
                    value = value[int(key)]
                else:
                    raise KeyError(f"无法在 {type(value)} 上取 key={key}")
            passed = value == assertion.expected
            return AssertionResult(
                passed=passed, assertion=assertion,
                actual_value=value,
                message="" if passed else f"路径 '{path}' 期望 {assertion.expected}，实际 {value}",
            )
        except (json.JSONDecodeError, KeyError, IndexError, TypeError, ValueError) as e:
            return AssertionResult(
                passed=False, assertion=assertion,
                message=f"JSON 路径解析失败: {e}",
            )

    def _check_regex(self, result: ToolResult, assertion: Assertion) -> AssertionResult:
        import re
        content = result.content or ""
        pattern = str(assertion.expected)
        passed = bool(re.search(pattern, content))
        return AssertionResult(
            passed=passed, assertion=assertion,
            actual_value=content[:200],
            message="" if passed else f"内容未匹配正则 '{pattern}'",
        )

    def _check_type(self, result: ToolResult, assertion: Assertion) -> AssertionResult:
        content = result.content or ""
        expected_type = str(assertion.expected)
        try:
            data = json.loads(content)
            type_map = {"dict": dict, "list": list, "str": str, "int": int, "float": float}
            expected_cls = type_map.get(expected_type)
            if expected_cls is None:
                return AssertionResult(passed=False, assertion=assertion, message=f"未知类型: {expected_type}")
            passed = isinstance(data, expected_cls)
            return AssertionResult(
                passed=passed, assertion=assertion,
                actual_value=type(data).__name__,
                message="" if passed else f"期望类型 {expected_type}，实际 {type(data).__name__}",
            )
        except json.JSONDecodeError:
            passed = expected_type == "str"
            return AssertionResult(
                passed=passed, assertion=assertion,
                actual_value="str (non-JSON)",
                message="" if passed else f"内容非 JSON，无法校验类型 {expected_type}",
            )

    def _check_range(self, result: ToolResult, assertion: Assertion) -> AssertionResult:
        content = result.content or ""
        try:
            data = json.loads(content)
            path = assertion.target
            value = data
            for key in path.split("."):
                if isinstance(value, dict):
                    value = value[key]
                elif isinstance(value, list):
                    value = value[int(key)]
            # expected 格式: {"min": 0, "max": 100}
            expected = assertion.expected
            min_val = expected.get("min", float("-inf"))
            max_val = expected.get("max", float("inf"))
            passed = min_val <= float(value) <= max_val
            return AssertionResult(
                passed=passed, assertion=assertion,
                actual_value=value,
                message="" if passed else f"值 {value} 不在范围 [{min_val}, {max_val}]",
            )
        except Exception as e:
            return AssertionResult(passed=False, assertion=assertion, message=f"范围检查失败: {e}")

    def _check_length(self, result: ToolResult, assertion: Assertion) -> AssertionResult:
        content = result.content or ""
        try:
            data = json.loads(content)
            path = assertion.target
            value = data
            if path != "content":
                for key in path.split("."):
                    if isinstance(value, dict):
                        value = value[key]
                    elif isinstance(value, list):
                        value = value[int(key)]
            # expected 格式: {"min": 1, "max": 10} 或直接 int
            actual_len = len(value) if hasattr(value, '__len__') else 0
            if isinstance(assertion.expected, int):
                passed = actual_len == assertion.expected
                msg = f"长度期望 {assertion.expected}，实际 {actual_len}"
            else:
                min_len = assertion.expected.get("min", 0)
                max_len = assertion.expected.get("max", float("inf"))
                passed = min_len <= actual_len <= max_len
                msg = f"长度 {actual_len} 不在 [{min_len}, {max_len}]"
            return AssertionResult(
                passed=passed, assertion=assertion,
                actual_value=actual_len,
                message="" if passed else msg,
            )
        except Exception as e:
            return AssertionResult(passed=False, assertion=assertion, message=f"长度检查失败: {e}")


# ═══════════════════════════════════════════════════════════
# 执行引擎
# ═══════════════════════════════════════════════════════════

class ToolEvalRunner:
    """Tool 评测执行引擎

    核心职责：
    1. 通过 ToolRegistry 获取 Tool 实例
    2. 每个 case 执行前重置 Backend 状态
    3. 执行 setup_steps（前置操作）
    4. 调用 tool.call(input_data, context)
    5. 运行断言引擎验证结果
    6. 汇总报告
    """

    def __init__(self, registry: ToolRegistry | None = None):
        self._registry = registry
        self._assertion_engine = AssertionEngine()
        self._backend = None

    def _ensure_registry(self) -> ToolRegistry:
        """确保 ToolRegistry 可用"""
        if self._registry is not None:
            return self._registry

        # 构建评测专用的 Registry（隔离，不依赖 DB）
        from src.tools.base import ToolRegistry
        from src.tools.crm_backend import CrmSimulatedBackend
        from src.tools.crm_tools import register_crm_tools
        from src.tools.metarepo_backend import MetarepoSimulatedBackend
        from src.tools.metarepo_tools import register_metarepo_tools

        reg = ToolRegistry(skip_db_check=True)
        backend = CrmSimulatedBackend()
        self._backend = backend

        # 注册 CRM 工具（不启用 memory，评测中 memory 工具单独测试）
        register_crm_tools(reg, backend, memory_engine=None)
        # 注册 Metarepo 工具
        metarepo_backend = MetarepoSimulatedBackend()
        register_metarepo_tools(reg, metarepo_backend)

        # 注册沙盒工具（terminal, execute_code, read_file, write_file, search_files）
        try:
            from src.tools.sandbox import _get_shared_sandbox_backend
            sandbox_backend = _get_shared_sandbox_backend()
            from src.tools.sandbox.terminal_tool import TerminalTool
            from src.tools.sandbox.code_execution_tool import CodeExecutionTool
            from src.tools.sandbox.file_tools import ReadFileTool, WriteFileTool, SearchFilesTool
            reg.register(TerminalTool(sandbox_backend))
            reg.register(CodeExecutionTool(sandbox_backend))
            reg.register(ReadFileTool(sandbox_backend))
            reg.register(WriteFileTool(sandbox_backend))
            reg.register(SearchFilesTool(sandbox_backend))
            logger.info("评测 Registry: 沙盒工具已注册")
        except Exception as e:
            logger.warning("评测 Registry: 沙盒工具注册跳过 (%s)", e)

        # 注册记忆工具（使用 mock memory engine）
        try:
            from src.tools.crm_tools import ManageMemoryTool, MemoryReadTool
            memory_engine = self._build_mock_memory_engine()
            if memory_engine:
                reg.register(ManageMemoryTool(memory_engine))
                reg.register(MemoryReadTool(memory_engine))
                logger.info("评测 Registry: 记忆工具已注册")
        except Exception as e:
            logger.warning("评测 Registry: 记忆工具注册跳过 (%s)", e)

        # 注册 Web 搜索工具
        try:
            from src.tools.web_search import WebSearchTool
            reg.register(WebSearchTool())
            logger.info("评测 Registry: web_search 已注册")
        except Exception as e:
            logger.warning("评测 Registry: web_search 注册跳过 (%s)", e)

        # 注册知识库工具（knowledge_search, list_knowledge_bases, knowledge_doc_detail）
        try:
            from src.tools.knowledge_tools import (
                KnowledgeSearchAdapterTool,
                ListKnowledgeBasesTool,
                KnowledgeDocDetailAdapterTool,
            )
            reg.register(KnowledgeSearchAdapterTool())
            reg.register(ListKnowledgeBasesTool())
            reg.register(KnowledgeDocDetailAdapterTool())
            logger.info("评测 Registry: 知识库工具已注册")
        except Exception as e:
            logger.warning("评测 Registry: 知识库工具注册跳过 (%s)", e)

        # 注册文件上传工具
        try:
            from src.tools.file_upload_tool import FileUploadTool
            reg.register(FileUploadTool())
            logger.info("评测 Registry: file_upload 已注册")
        except Exception as e:
            logger.warning("评测 Registry: file_upload 注册跳过 (%s)", e)

        self._registry = reg
        return reg

    def _build_mock_memory_engine(self):
        """构建评测用的 Mock 记忆引擎"""
        try:
            import os
            if os.environ.get("DISABLE_MEMORY", "").strip() in ("1", "true", "yes"):
                return None
            from src.memory.viking_engine import VikingMemoryEngine
            from langchain_openai import ChatOpenAI
            _api_key = os.environ.get("AGENT_API_KEY") or os.environ.get("DEEPSEEK_API_KEY", "")
            if not _api_key:
                return None
            _api_base = os.environ.get("AGENT_API_BASE", "https://tokenhub.tencentmaas.com/v1")
            aux_llm = ChatOpenAI(
                model="deepseek-v4-flash", api_key=_api_key, base_url=_api_base, max_tokens=2048,
            )
            return VikingMemoryEngine(
                vdb_url=os.environ.get("TENCENT_VDB_URL", "http://10.60.2.17"),
                vdb_key=os.environ.get("TENCENT_VDB_KEY", "bRG3NETg13tv5Fn68VTdkxaJXH9tMQzhKeT3unck"),
                vdb_username=os.environ.get("TENCENT_VDB_USERNAME", "root"),
                database_name=os.environ.get("TENCENT_VDB_DATABASE", "viking_memory"),
                collection_name=os.environ.get("TENCENT_VDB_COLLECTION", "agent_memories"),
                llm=aux_llm,
            )
        except Exception as e:
            logger.warning("Mock memory engine 构建失败: %s", e)
            return None

    def _reset_backend(self):
        """重置 CRM Backend 数据为初始 seed data"""
        if self._backend is not None:
            from src.tools.crm_backend import build_seed_data
            self._backend._data = build_seed_data()
            self._backend._audit_log = []

    def _build_context(self) -> Any:
        """构建评测用的最小化 context"""
        return {"tenant_id": 0, "user_id": "eval_user", "eval_mode": True}

    async def run_case(self, case: ToolEvalCase) -> CaseResult:
        """执行单个评测用例"""
        reg = self._ensure_registry()
        result = CaseResult(
            case_id=case.id,
            tool_name=case.tool_name,
            description=case.description,
            category=case.category,
            input_data=case.input_data,
        )

        # 重置 Backend
        self._reset_backend()

        # 查找工具
        tool = reg.find_by_name(case.tool_name)
        if tool is None:
            result.error = f"工具 '{case.tool_name}' 未注册"
            result.passed = False
            return result

        context = self._build_context()

        # 执行 setup_steps（前置操作）
        for step in case.setup_steps:
            setup_tool_name = step.get("tool_name") or step.get("tool") or case.tool_name
            setup_tool = reg.find_by_name(setup_tool_name)
            if setup_tool is None:
                result.error = f"setup_step 工具未注册: {setup_tool_name}"
                result.passed = False
                return result
            try:
                setup_input = step.get("input_data") or step.get("input") or {}
                setup_result = await setup_tool.call(setup_input, context)
                # 检查 setup_step 返回值：如果执行报错则标记失败
                if setup_result and getattr(setup_result, 'is_error', False):
                    result.error = f"setup_step 返回错误: [{setup_tool_name}] {setup_result.content}"
                    result.passed = False
                    return result
            except Exception as e:
                result.error = f"setup_step 执行失败: {e}"
                result.passed = False
                return result

        # 执行目标工具
        start = time.monotonic()
        try:
            tool_result = await tool.call(case.input_data, context)
            result.tool_result = tool_result
        except Exception as e:
            result.duration_ms = (time.monotonic() - start) * 1000
            # 某些断言期望工具抛异常
            result.tool_result = ToolResult(content=str(e), is_error=True)

        result.duration_ms = (time.monotonic() - start) * 1000

        # 执行断言
        all_passed = True
        for assertion in case.assertions:
            if assertion.type == AssertionType.SIDE_EFFECT:
                # 副作用验证：再执行一次查询
                ar = await self._check_side_effect(reg, context, assertion)
            else:
                ar = self._assertion_engine.check(result.tool_result, assertion)
            result.assertion_results.append(ar)
            if not ar.passed:
                all_passed = False

        result.passed = all_passed

        # 执行 cleanup_steps（后置清理，保证环境干净）
        # 策略：如果有显式 cleanup_steps 则执行；否则自动清理 setup_steps 中写入的文件
        cleanup_steps = case.cleanup_steps
        if not cleanup_steps and case.setup_steps:
            # 自动推导清理步骤：删除 setup_steps 中 write_file 写入的文件
            cleanup_steps = self._derive_cleanup_steps(case.setup_steps)

        for step in cleanup_steps:
            cleanup_tool_name = step.get("tool_name") or step.get("tool") or "terminal"
            cleanup_tool = reg.find_by_name(cleanup_tool_name)
            if cleanup_tool:
                try:
                    cleanup_input = step.get("input_data") or step.get("input") or {}
                    await cleanup_tool.call(cleanup_input, context)
                except Exception as e:
                    logger.warning("cleanup_step 执行失败 [%s]: %s", cleanup_tool_name, e)

        return result

    def _derive_cleanup_steps(self, setup_steps: list[dict]) -> list[dict]:
        """从 setup_steps 自动推导清理步骤 — 删除写入的文件"""
        paths_to_clean = []
        for step in setup_steps:
            tool = step.get("tool_name") or step.get("tool") or ""
            inp = step.get("input_data") or step.get("input") or {}
            if tool == "write_file" and inp.get("path"):
                paths_to_clean.append(inp["path"])
        if not paths_to_clean:
            return []
        # 用 terminal 的 rm -f 批量删除
        rm_cmd = "rm -f " + " ".join(f"'{p}'" for p in paths_to_clean)
        return [{"tool": "terminal", "input": {"command": rm_cmd}}]

    async def _check_side_effect(
        self, reg: ToolRegistry, context: Any, assertion: Assertion
    ) -> AssertionResult:
        """副作用验证 — 执行目标工具后再查一次确认数据变更"""
        # expected 格式: {"verify_tool": "query_data", "verify_input": {...}, "verify_path": "status", "verify_value": "cancelled"}
        expected = assertion.expected
        if not isinstance(expected, dict):
            return AssertionResult(passed=False, assertion=assertion, message="side_effect 配置格式错误")

        verify_tool = reg.find_by_name(expected.get("verify_tool", "query_data"))
        if not verify_tool:
            return AssertionResult(passed=False, assertion=assertion, message="验证工具不存在")

        try:
            verify_result = await verify_tool.call(expected.get("verify_input", {}), context)

            if verify_result.is_error:
                return AssertionResult(
                    passed=False, assertion=assertion,
                    message=f"副作用验证失败: 验证工具返回错误 — {verify_result.content[:200]}",
                )

            verify_path = expected.get("verify_path", "")
            verify_value = expected.get("verify_value")

            # 尝试 JSON 解析；如果内容不是 JSON，使用字符串包含匹配
            try:
                data = json.loads(verify_result.content)
                # 如果 verify_path 非空，按路径取值做精确匹配
                if verify_path:
                    value = data
                    for key in verify_path.split("."):
                        if not key:
                            continue
                        if isinstance(value, dict):
                            value = value.get(key)
                        elif isinstance(value, list) and key.isdigit():
                            value = value[int(key)]
                    passed = value == verify_value
                    return AssertionResult(
                        passed=passed, assertion=assertion,
                        actual_value=value,
                        message="" if passed else f"副作用验证失败: 期望 {verify_value}，实际 {value}",
                    )
                else:
                    # verify_path 为空 — 对原始文本做 contains 检查
                    content = verify_result.content or ""
                    passed = str(verify_value) in content
                    return AssertionResult(
                        passed=passed, assertion=assertion,
                        actual_value=content[:200] if not passed else verify_value,
                        message="" if passed else f"副作用验证失败: 文本内容中未找到 '{verify_value}'",
                    )
            except (json.JSONDecodeError, ValueError):
                # 非 JSON 内容（如 read_file 返回原始文本）— 使用字符串包含匹配
                content = verify_result.content or ""
                passed = str(verify_value) in content
                return AssertionResult(
                    passed=passed, assertion=assertion,
                    actual_value=content[:200] if not passed else verify_value,
                    message="" if passed else f"副作用验证失败: 文本内容中未找到 '{verify_value}'",
                )
        except Exception as e:
            return AssertionResult(passed=False, assertion=assertion, message=f"副作用验证异常: {e}")

    async def run_suite(self, suite: ToolEvalSuite) -> SuiteReport:
        """执行评测集，返回完整报告"""
        report = SuiteReport(
            suite_id=suite.id,
            suite_name=suite.name,
            total=len(suite.cases),
        )

        start = time.monotonic()

        for case in suite.cases:
            case_result = await self.run_case(case)
            report.results.append(case_result)

            if case_result.error:
                report.error += 1
            elif case_result.passed:
                report.passed += 1
            else:
                report.failed += 1
                report.failures.append({
                    "case_id": case_result.case_id,
                    "tool_name": case_result.tool_name,
                    "description": case_result.description,
                    "failed_assertions": [
                        a.to_dict() for a in case_result.assertion_results if not a.passed
                    ],
                })

        report.total_duration_ms = (time.monotonic() - start) * 1000
        report.pass_rate = report.passed / max(report.total, 1)

        # 按工具分组统计
        tool_stats: dict[str, dict] = {}
        for r in report.results:
            if r.tool_name not in tool_stats:
                tool_stats[r.tool_name] = {"total": 0, "passed": 0, "failed": 0}
            tool_stats[r.tool_name]["total"] += 1
            if r.passed:
                tool_stats[r.tool_name]["passed"] += 1
            else:
                tool_stats[r.tool_name]["failed"] += 1
        report.by_tool = tool_stats

        # 按分类统计
        cat_stats: dict[str, dict] = {}
        for r in report.results:
            cat = r.category or "unknown"
            if cat not in cat_stats:
                cat_stats[cat] = {"total": 0, "passed": 0, "failed": 0}
            cat_stats[cat]["total"] += 1
            if r.passed:
                cat_stats[cat]["passed"] += 1
            else:
                cat_stats[cat]["failed"] += 1
        report.by_category = cat_stats

        return report


# ═══════════════════════════════════════════════════════════
# Console 输出
# ═══════════════════════════════════════════════════════════

def print_report(report: SuiteReport):
    """将评测报告输出到 Console"""
    print()
    print("═══ Tool 评测报告 ═══")
    print(f"评测集: {report.suite_name}")
    print(f"总用例: {report.total} | 通过: {report.passed} | 失败: {report.failed} | 错误: {report.error}")
    print(f"Pass Rate: {report.pass_rate:.1%} | 总耗时: {report.total_duration_ms:.0f}ms")
    print()

    # 按工具分组
    print("── 按工具 ──")
    for tool_name, stats in report.by_tool.items():
        status = "✅" if stats["failed"] == 0 else "⚠️"
        print(f"  {status} {tool_name:<20} {stats['passed']}/{stats['total']}")
    print()

    # 失败详情
    if report.failures:
        print("── 失败详情 ──")
        for f in report.failures:
            print(f"  ❌ [{f['tool_name']}] {f['description']}")
            for a in f["failed_assertions"]:
                print(f"     → {a['type']}: {a['message']}")
        print()

    # 按分类
    print("── 按分类 ──")
    for cat, stats in report.by_category.items():
        print(f"  {cat:<12} {stats['passed']}/{stats['total']}")
    print()
    print("═" * 40)
