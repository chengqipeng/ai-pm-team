"""Tool 评测用例 DAO — 持久化 CRUD

职责：
    - 用例（ai_eval_tool_case）的增删改查
    - 按 tool_name / method_name / category 筛选
    - 评测报告（ai_eval_tool_report）持久化
    - 用例执行结果明细（ai_eval_tool_case_result）存储
"""
from __future__ import annotations

import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from .pg_pool import get_conn

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════
# 数据模型
# ═══════════════════════════════════════════════════════════

@dataclass
class EvalToolCase:
    """评测用例数据模型"""
    id: int = 0
    suite_id: int = 0
    case_key: str = ""
    tool_name: str = ""
    method_name: str = ""
    description: str = ""
    category: str = "normal"
    input_data: dict = field(default_factory=dict)
    assertions: list = field(default_factory=list)
    setup_steps: list = field(default_factory=list)
    cleanup_steps: list = field(default_factory=list)
    tags: list = field(default_factory=list)
    priority: int = 0
    timeout_ms: int = 10000
    enabled: bool = True
    generated_by: str = "manual"
    source_params: dict | None = None
    status: str = "active"
    created_at: int = 0
    updated_at: int = 0

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "suite_id": self.suite_id,
            "case_key": self.case_key,
            "tool_name": self.tool_name,
            "method_name": self.method_name,
            "description": self.description,
            "category": self.category,
            "input_data": self.input_data,
            "assertions": self.assertions,
            "setup_steps": self.setup_steps,
            "cleanup_steps": self.cleanup_steps,
            "tags": self.tags,
            "priority": self.priority,
            "timeout_ms": self.timeout_ms,
            "enabled": self.enabled,
            "generated_by": self.generated_by,
            "status": self.status,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


@dataclass
class EvalToolReport:
    """评测报告数据模型"""
    id: int = 0
    report_key: str = ""
    suite_id: int = 0
    trigger_type: str = "manual"
    filter_tools: list = field(default_factory=list)
    filter_methods: list = field(default_factory=list)
    filter_categories: list = field(default_factory=list)
    total: int = 0
    passed: int = 0
    failed: int = 0
    error_count: int = 0
    pass_rate: float = 0.0
    total_duration_ms: float = 0.0
    by_tool: dict = field(default_factory=dict)
    by_method: dict = field(default_factory=dict)
    by_category: dict = field(default_factory=dict)
    failures: list = field(default_factory=list)
    status: str = "running"
    created_at: int = 0
    completed_at: int | None = None


# ═══════════════════════════════════════════════════════════
# Suite DAO
# ═══════════════════════════════════════════════════════════

class EvalSuiteDAO:

    @staticmethod
    def get_default_suite_id() -> int:
        """获取默认 Suite 的 ID，不存在则创建"""
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute("SELECT id FROM ai_eval_tool_suite WHERE suite_key = 'default'")
            row = cur.fetchone()
            if row:
                return row[0]
            # 创建
            now = int(time.time() * 1000)
            cur.execute("""
                INSERT INTO ai_eval_tool_suite (suite_key, name, description, created_at, updated_at)
                VALUES ('default', 'Tool 评测 — 默认全量', '覆盖所有内置工具的正常/异常/边界/副作用场景', %s, %s)
                RETURNING id
            """, (now, now))
            return cur.fetchone()[0]


# ═══════════════════════════════════════════════════════════
# Case DAO
# ═══════════════════════════════════════════════════════════

class EvalCaseDAO:

    @staticmethod
    def insert(case: EvalToolCase) -> int:
        """插入用例，返回 ID"""
        now = int(time.time() * 1000)
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO ai_eval_tool_case
                (suite_id, case_key, tool_name, method_name, description, category,
                 input_data, assertions, setup_steps, cleanup_steps, tags, priority, timeout_ms,
                 enabled, generated_by, source_params, status, created_at, updated_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (suite_id, case_key) DO UPDATE SET
                    tool_name=EXCLUDED.tool_name, method_name=EXCLUDED.method_name,
                    description=EXCLUDED.description, category=EXCLUDED.category,
                    input_data=EXCLUDED.input_data, assertions=EXCLUDED.assertions,
                    setup_steps=EXCLUDED.setup_steps, cleanup_steps=EXCLUDED.cleanup_steps,
                    tags=EXCLUDED.tags,
                    priority=EXCLUDED.priority, timeout_ms=EXCLUDED.timeout_ms,
                    enabled=EXCLUDED.enabled, generated_by=EXCLUDED.generated_by,
                    source_params=EXCLUDED.source_params, status=EXCLUDED.status,
                    updated_at=EXCLUDED.updated_at
                RETURNING id
            """, (
                case.suite_id, case.case_key, case.tool_name, case.method_name,
                case.description, case.category,
                json.dumps(case.input_data, ensure_ascii=False),
                json.dumps(case.assertions, ensure_ascii=False),
                json.dumps(case.setup_steps, ensure_ascii=False),
                json.dumps(case.cleanup_steps, ensure_ascii=False),
                json.dumps(case.tags, ensure_ascii=False),
                case.priority, case.timeout_ms,
                case.enabled, case.generated_by,
                json.dumps(case.source_params) if case.source_params else None,
                case.status, now, now,
            ))
            return cur.fetchone()[0]

    @staticmethod
    def batch_insert(cases: list[EvalToolCase]) -> int:
        """批量插入用例，返回插入数量"""
        if not cases:
            return 0
        count = 0
        for case in cases:
            EvalCaseDAO.insert(case)
            count += 1
        return count

    @staticmethod
    def list_by_tool(
        suite_id: int,
        tool_name: str | None = None,
        method_name: str | None = None,
        category: str | None = None,
        enabled_only: bool = True,
        limit: int = 500,
        offset: int = 0,
    ) -> list[EvalToolCase]:
        """按条件查询用例"""
        with get_conn() as conn:
            cur = conn.cursor()
            conditions = ["suite_id = %s"]
            params: list[Any] = [suite_id]

            if tool_name:
                conditions.append("tool_name = %s")
                params.append(tool_name)
            if method_name:
                conditions.append("method_name = %s")
                params.append(method_name)
            if category:
                conditions.append("category = %s")
                params.append(category)
            if enabled_only:
                conditions.append("enabled = TRUE")

            where = " AND ".join(conditions)
            cur.execute(f"""
                SELECT id, suite_id, case_key, tool_name, method_name, description,
                       category, input_data, assertions, setup_steps, cleanup_steps, tags,
                       priority, timeout_ms, enabled, generated_by, source_params,
                       status, created_at, updated_at
                FROM ai_eval_tool_case
                WHERE {where}
                ORDER BY priority DESC, id ASC
                LIMIT %s OFFSET %s
            """, (*params, limit, offset))

            results = []
            for row in cur.fetchall():
                results.append(EvalToolCase(
                    id=row[0], suite_id=row[1], case_key=row[2],
                    tool_name=row[3], method_name=row[4], description=row[5],
                    category=row[6],
                    input_data=row[7] if isinstance(row[7], dict) else json.loads(row[7] or "{}"),
                    assertions=row[8] if isinstance(row[8], list) else json.loads(row[8] or "[]"),
                    setup_steps=row[9] if isinstance(row[9], list) else json.loads(row[9] or "[]"),
                    cleanup_steps=row[10] if isinstance(row[10], list) else json.loads(row[10] or "[]"),
                    tags=row[11] if isinstance(row[11], list) else json.loads(row[11] or "[]"),
                    priority=row[12], timeout_ms=row[13], enabled=row[14],
                    generated_by=row[15],
                    source_params=row[16] if isinstance(row[16], (dict, type(None))) else json.loads(row[16] or "null"),
                    status=row[17], created_at=row[18], updated_at=row[19],
                ))
            return results

    @staticmethod
    def count_by_tool(suite_id: int) -> dict:
        """按工具 + 方法统计用例数"""
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT tool_name, method_name, category, COUNT(*)
                FROM ai_eval_tool_case
                WHERE suite_id = %s AND enabled = TRUE AND status = 'active'
                GROUP BY tool_name, method_name, category
                ORDER BY tool_name, method_name
            """, (suite_id,))
            result = {}
            for row in cur.fetchall():
                tool = row[0]
                method = row[1] or "_default"
                cat = row[2]
                count = row[3]
                if tool not in result:
                    result[tool] = {}
                if method not in result[tool]:
                    result[tool][method] = {"total": 0, "by_category": {}}
                result[tool][method]["total"] += count
                result[tool][method]["by_category"][cat] = count
            return result

    @staticmethod
    def get_tools_and_methods(suite_id: int) -> dict[str, list[str]]:
        """获取所有工具及其方法列表"""
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT DISTINCT tool_name, method_name
                FROM ai_eval_tool_case
                WHERE suite_id = %s AND enabled = TRUE AND status = 'active'
                ORDER BY tool_name, method_name
            """, (suite_id,))
            result: dict[str, list[str]] = {}
            for row in cur.fetchall():
                tool = row[0]
                method = row[1] or ""
                if tool not in result:
                    result[tool] = []
                if method and method not in result[tool]:
                    result[tool].append(method)
            return result

    @staticmethod
    def delete_by_tool(suite_id: int, tool_name: str, method_name: str | None = None) -> int:
        """删除指定工具/方法的所有用例"""
        with get_conn() as conn:
            cur = conn.cursor()
            if method_name:
                cur.execute("""
                    DELETE FROM ai_eval_tool_case
                    WHERE suite_id = %s AND tool_name = %s AND method_name = %s
                """, (suite_id, tool_name, method_name))
            else:
                cur.execute("""
                    DELETE FROM ai_eval_tool_case
                    WHERE suite_id = %s AND tool_name = %s
                """, (suite_id, tool_name))
            return cur.rowcount

    @staticmethod
    def delete_by_id(case_id: int) -> bool:
        """删除单个用例"""
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute("DELETE FROM ai_eval_tool_case WHERE id = %s", (case_id,))
            return cur.rowcount > 0


# ═══════════════════════════════════════════════════════════
# Report DAO
# ═══════════════════════════════════════════════════════════

class EvalReportDAO:

    @staticmethod
    def create_report(
        suite_id: int,
        trigger_type: str = "manual",
        filter_tools: list = None,
        filter_methods: list = None,
        filter_categories: list = None,
    ) -> str:
        """创建评测报告记录，返回 report_key"""
        report_key = f"rpt_{uuid.uuid4().hex[:12]}"
        now = int(time.time() * 1000)
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO ai_eval_tool_report
                (report_key, suite_id, trigger_type, filter_tools, filter_methods,
                 filter_categories, status, created_at)
                VALUES (%s,%s,%s,%s,%s,%s,'running',%s)
            """, (
                report_key, suite_id, trigger_type,
                json.dumps(filter_tools or []),
                json.dumps(filter_methods or []),
                json.dumps(filter_categories or []),
                now,
            ))
        return report_key

    @staticmethod
    def complete_report(
        report_key: str,
        total: int, passed: int, failed: int, error_count: int,
        pass_rate: float, total_duration_ms: float,
        by_tool: dict, by_method: dict, by_category: dict,
        failures: list,
    ) -> None:
        """更新报告为完成状态"""
        now = int(time.time() * 1000)
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute("""
                UPDATE ai_eval_tool_report SET
                    total=%s, passed=%s, failed=%s, error_count=%s,
                    pass_rate=%s, total_duration_ms=%s,
                    by_tool=%s, by_method=%s, by_category=%s,
                    failures=%s, status='completed', completed_at=%s
                WHERE report_key=%s
            """, (
                total, passed, failed, error_count,
                pass_rate, total_duration_ms,
                json.dumps(by_tool, ensure_ascii=False),
                json.dumps(by_method, ensure_ascii=False),
                json.dumps(by_category, ensure_ascii=False),
                json.dumps(failures, ensure_ascii=False),
                now, report_key,
            ))

    @staticmethod
    def list_reports(limit: int = 20, offset: int = 0) -> list[dict]:
        """查询报告列表"""
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT report_key, suite_id, trigger_type, filter_tools, filter_methods,
                       total, passed, failed, error_count, pass_rate, total_duration_ms,
                       by_tool, by_method, status, created_at, completed_at
                FROM ai_eval_tool_report
                ORDER BY created_at DESC
                LIMIT %s OFFSET %s
            """, (limit, offset))
            results = []
            for row in cur.fetchall():
                results.append({
                    "report_key": row[0],
                    "suite_id": row[1],
                    "trigger_type": row[2],
                    "filter_tools": row[3] if isinstance(row[3], list) else json.loads(row[3] or "[]"),
                    "filter_methods": row[4] if isinstance(row[4], list) else json.loads(row[4] or "[]"),
                    "total": row[5],
                    "passed": row[6],
                    "failed": row[7],
                    "error_count": row[8],
                    "pass_rate": float(row[9] or 0),
                    "total_duration_ms": float(row[10] or 0),
                    "by_tool": row[11] if isinstance(row[11], dict) else json.loads(row[11] or "{}"),
                    "by_method": row[12] if isinstance(row[12], dict) else json.loads(row[12] or "{}"),
                    "status": row[13],
                    "created_at": row[14],
                    "completed_at": row[15],
                })
            return results

    @staticmethod
    def get_report(report_key: str) -> dict | None:
        """获取单个报告详情"""
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT report_key, suite_id, trigger_type, filter_tools, filter_methods,
                       filter_categories, total, passed, failed, error_count,
                       pass_rate, total_duration_ms, by_tool, by_method, by_category,
                       failures, status, created_at, completed_at
                FROM ai_eval_tool_report WHERE report_key = %s
            """, (report_key,))
            row = cur.fetchone()
            if not row:
                return None
            return {
                "report_key": row[0],
                "suite_id": row[1],
                "trigger_type": row[2],
                "filter_tools": row[3] if isinstance(row[3], list) else json.loads(row[3] or "[]"),
                "filter_methods": row[4] if isinstance(row[4], list) else json.loads(row[4] or "[]"),
                "filter_categories": row[5] if isinstance(row[5], list) else json.loads(row[5] or "[]"),
                "total": row[6],
                "passed": row[7],
                "failed": row[8],
                "error_count": row[9],
                "pass_rate": float(row[10] or 0),
                "total_duration_ms": float(row[11] or 0),
                "by_tool": row[12] if isinstance(row[12], dict) else json.loads(row[12] or "{}"),
                "by_method": row[13] if isinstance(row[13], dict) else json.loads(row[13] or "{}"),
                "by_category": row[14] if isinstance(row[14], dict) else json.loads(row[14] or "{}"),
                "failures": row[15] if isinstance(row[15], list) else json.loads(row[15] or "[]"),
                "status": row[16],
                "created_at": row[17],
                "completed_at": row[18],
            }


# ═══════════════════════════════════════════════════════════
# Case Result DAO
# ═══════════════════════════════════════════════════════════

class EvalCaseResultDAO:

    @staticmethod
    def batch_insert(report_id: int, results: list[dict]) -> None:
        """批量插入用例执行结果"""
        if not results:
            return
        now = int(time.time() * 1000)
        with get_conn() as conn:
            cur = conn.cursor()
            # 批量查找 case_key -> case DB id 映射
            case_keys = [r.get("case_key", "") for r in results if r.get("case_key")]
            case_id_map = {}
            if case_keys:
                # 分批查询避免 SQL 太长
                for i in range(0, len(case_keys), 100):
                    batch = case_keys[i:i+100]
                    placeholders = ",".join(["%s"] * len(batch))
                    cur.execute(f"SELECT id, case_key FROM ai_eval_tool_case WHERE case_key IN ({placeholders})", batch)
                    for row in cur.fetchall():
                        case_id_map[row[1]] = row[0]

            for r in results:
                case_key = r.get("case_key", "")
                case_db_id = case_id_map.get(case_key, 0)
                if case_db_id == 0:
                    continue  # 跳过找不到对应用例的结果
                cur.execute("""
                    INSERT INTO ai_eval_tool_case_result
                    (report_id, case_id, case_key, tool_name, method_name,
                     category, passed, duration_ms, input_data, tool_output, is_error,
                     assertion_results, error_message, created_at)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                """, (
                    report_id, case_db_id, case_key,
                    r.get("tool_name", ""), r.get("method_name", ""),
                    r.get("category", ""), r.get("passed", False),
                    r.get("duration_ms", 0),
                    json.dumps(r.get("input_data", {}), ensure_ascii=False),
                    r.get("tool_output", ""),
                    r.get("is_error", False),
                    json.dumps(r.get("assertion_results", []), ensure_ascii=False),
                    r.get("error_message", ""), now,
                ))
    @staticmethod
    def list_by_report(report_id: int) -> list[dict]:
        """查询报告下的用例结果"""
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT case_key, tool_name, method_name, category,
                       passed, duration_ms, input_data, tool_output, is_error,
                       assertion_results, error_message
                FROM ai_eval_tool_case_result
                WHERE report_id = %s
                ORDER BY id ASC
            """, (report_id,))
            results = []
            for row in cur.fetchall():
                results.append({
                    "case_key": row[0],
                    "tool_name": row[1],
                    "method_name": row[2],
                    "category": row[3],
                    "passed": row[4],
                    "duration_ms": float(row[5] or 0),
                    "input_data": row[6] if isinstance(row[6], dict) else json.loads(row[6] or "{}"),
                    "tool_output": row[7],
                    "is_error": row[8],
                    "assertion_results": row[9] if isinstance(row[9], list) else json.loads(row[9] or "[]"),
                    "error_message": row[10],
                })
            return results
