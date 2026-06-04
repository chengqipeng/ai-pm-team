"""Memory 评测用例 DAO — 持久化 CRUD

职责：
    - 评测套件（ai_eval_memory_suite）管理
    - 用例（ai_eval_memory_case）的增删改查 + 同步预置用例
    - 评测报告（ai_eval_memory_report）持久化
    - 用例执行结果明细（ai_eval_memory_case_result）存储与查询
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
class MemoryEvalCaseDB:
    """记忆评测用例（DB 模型）"""
    id: int = 0
    suite_id: int = 0
    case_key: str = ""
    layer: str = ""
    query_type: str = ""
    query: str = ""
    description: str = ""
    expected_memories: list[str] = field(default_factory=list)
    expected_category: str = ""
    expected_parent_entity: str = ""
    expected_dimensions: list[str] = field(default_factory=list)
    expected_action: str = ""
    conflict_type: str = ""
    test_focus: str = ""
    top_k: int = 5
    assertion_mode: str = "any"
    negative: bool = False
    existing_memory: dict = field(default_factory=dict)
    metadata: dict = field(default_factory=dict)
    priority: int = 0
    enabled: bool = True
    generated_by: str = "preset"
    status: str = "active"
    created_at: int = 0
    updated_at: int = 0

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "suite_id": self.suite_id,
            "case_key": self.case_key,
            "layer": self.layer,
            "query_type": self.query_type,
            "query": self.query,
            "description": self.description,
            "expected_memories": self.expected_memories,
            "expected_category": self.expected_category,
            "expected_parent_entity": self.expected_parent_entity,
            "expected_dimensions": self.expected_dimensions,
            "expected_action": self.expected_action,
            "conflict_type": self.conflict_type,
            "test_focus": self.test_focus,
            "top_k": self.top_k,
            "assertion_mode": self.assertion_mode,
            "negative": self.negative,
            "existing_memory": self.existing_memory,
            "metadata": self.metadata,
            "priority": self.priority,
            "enabled": self.enabled,
            "generated_by": self.generated_by,
            "status": self.status,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


@dataclass
class MemoryEvalReportDB:
    """记忆评测报告（DB 模型）"""
    id: int = 0
    report_key: str = ""
    suite_id: int = 0
    trigger_type: str = "manual"
    filter_layers: list[str] = field(default_factory=list)
    filter_query_types: list[str] = field(default_factory=list)
    use_llm: bool = False
    total: int = 0
    passed: int = 0
    failed: int = 0
    pass_rate: float = 0.0
    avg_recall_at_5: float = 0.0
    avg_mrr: float = 0.0
    top1_hit_rate: float = 0.0
    total_duration_ms: float = 0.0
    by_layer: dict = field(default_factory=dict)
    by_query_type: dict = field(default_factory=dict)
    failures: list = field(default_factory=list)
    status: str = "running"
    created_at: int = 0
    completed_at: int | None = None


# ═══════════════════════════════════════════════════════════
# Suite DAO
# ═══════════════════════════════════════════════════════════

class MemoryEvalSuiteDAO:

    @staticmethod
    def get_default_suite_id() -> int:
        """获取默认 Suite 的 ID，不存在则创建"""
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute("SELECT id FROM ai_eval_memory_suite WHERE suite_key = 'default'")
            row = cur.fetchone()
            if row:
                return row[0]
            now = int(time.time() * 1000)
            cur.execute("""
                INSERT INTO ai_eval_memory_suite (suite_key, name, description, created_at, updated_at)
                VALUES ('default', 'Memory 评测 — 默认全量', '长期记忆召回率 + 四维度提取评测', %s, %s)
                RETURNING id
            """, (now, now))
            return cur.fetchone()[0]


# ═══════════════════════════════════════════════════════════
# Case DAO
# ═══════════════════════════════════════════════════════════

class MemoryEvalCaseDAO:

    @staticmethod
    def insert(case: MemoryEvalCaseDB) -> int:
        """插入/更新用例（UPSERT on suite_id + case_key），返回 ID"""
        now = int(time.time() * 1000)
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO ai_eval_memory_case
                (suite_id, case_key, layer, query_type, query, description,
                 expected_memories, expected_category, expected_parent_entity,
                 expected_dimensions, expected_action, conflict_type, test_focus,
                 top_k, assertion_mode, negative, existing_memory, metadata,
                 priority, enabled, generated_by, status, created_at, updated_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (suite_id, case_key) DO UPDATE SET
                    layer=EXCLUDED.layer, query_type=EXCLUDED.query_type,
                    query=EXCLUDED.query, description=EXCLUDED.description,
                    expected_memories=EXCLUDED.expected_memories,
                    expected_category=EXCLUDED.expected_category,
                    expected_parent_entity=EXCLUDED.expected_parent_entity,
                    expected_dimensions=EXCLUDED.expected_dimensions,
                    expected_action=EXCLUDED.expected_action,
                    conflict_type=EXCLUDED.conflict_type, test_focus=EXCLUDED.test_focus,
                    top_k=EXCLUDED.top_k, assertion_mode=EXCLUDED.assertion_mode,
                    negative=EXCLUDED.negative, existing_memory=EXCLUDED.existing_memory,
                    metadata=EXCLUDED.metadata, priority=EXCLUDED.priority,
                    enabled=EXCLUDED.enabled, generated_by=EXCLUDED.generated_by,
                    status=EXCLUDED.status, updated_at=EXCLUDED.updated_at
                RETURNING id
            """, (
                case.suite_id, case.case_key, case.layer, case.query_type,
                case.query, case.description,
                json.dumps(case.expected_memories, ensure_ascii=False),
                case.expected_category, case.expected_parent_entity,
                json.dumps(case.expected_dimensions, ensure_ascii=False),
                case.expected_action, case.conflict_type, case.test_focus,
                case.top_k, case.assertion_mode, case.negative,
                json.dumps(case.existing_memory, ensure_ascii=False),
                json.dumps(case.metadata, ensure_ascii=False),
                case.priority, case.enabled, case.generated_by,
                case.status, now, now,
            ))
            return cur.fetchone()[0]

    @staticmethod
    def batch_insert(cases: list[MemoryEvalCaseDB]) -> int:
        """批量插入用例，返回插入数量"""
        count = 0
        for case in cases:
            MemoryEvalCaseDAO.insert(case)
            count += 1
        return count

    @staticmethod
    def list_cases(
        suite_id: int,
        layer: str | None = None,
        query_type: str | None = None,
        enabled_only: bool = True,
        limit: int = 1000,
        offset: int = 0,
    ) -> list[MemoryEvalCaseDB]:
        """按条件查询用例"""
        with get_conn() as conn:
            cur = conn.cursor()
            conditions = ["suite_id = %s"]
            params: list[Any] = [suite_id]

            if layer:
                conditions.append("layer = %s")
                params.append(layer)
            if query_type:
                conditions.append("query_type = %s")
                params.append(query_type)
            if enabled_only:
                conditions.append("enabled = TRUE")

            where = " AND ".join(conditions)
            cur.execute(f"""
                SELECT id, suite_id, case_key, layer, query_type, query, description,
                       expected_memories, expected_category, expected_parent_entity,
                       expected_dimensions, expected_action, conflict_type, test_focus,
                       top_k, assertion_mode, negative, existing_memory, metadata,
                       priority, enabled, generated_by, status, created_at, updated_at
                FROM ai_eval_memory_case
                WHERE {where}
                ORDER BY priority DESC, id ASC
                LIMIT %s OFFSET %s
            """, (*params, limit, offset))

            results = []
            for row in cur.fetchall():
                results.append(MemoryEvalCaseDB(
                    id=row[0], suite_id=row[1], case_key=row[2],
                    layer=row[3], query_type=row[4], query=row[5],
                    description=row[6],
                    expected_memories=row[7] if isinstance(row[7], list) else json.loads(row[7] or "[]"),
                    expected_category=row[8] or "",
                    expected_parent_entity=row[9] or "",
                    expected_dimensions=row[10] if isinstance(row[10], list) else json.loads(row[10] or "[]"),
                    expected_action=row[11] or "",
                    conflict_type=row[12] or "",
                    test_focus=row[13] or "",
                    top_k=row[14], assertion_mode=row[15] or "any",
                    negative=row[16],
                    existing_memory=row[17] if isinstance(row[17], dict) else json.loads(row[17] or "{}"),
                    metadata=row[18] if isinstance(row[18], dict) else json.loads(row[18] or "{}"),
                    priority=row[19], enabled=row[20],
                    generated_by=row[21] or "preset",
                    status=row[22] or "active",
                    created_at=row[23], updated_at=row[24],
                ))
            return results

    @staticmethod
    def count_by_layer(suite_id: int) -> dict:
        """按层 + 查询类型统计用例数"""
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT layer, query_type, COUNT(*)
                FROM ai_eval_memory_case
                WHERE suite_id = %s AND enabled = TRUE AND status = 'active'
                GROUP BY layer, query_type
                ORDER BY layer, query_type
            """, (suite_id,))
            result: dict[str, dict] = {}
            for row in cur.fetchall():
                layer = row[0]
                qt = row[1]
                count = row[2]
                if layer not in result:
                    result[layer] = {"total": 0, "by_query_type": {}}
                result[layer]["total"] += count
                result[layer]["by_query_type"][qt] = count
            return result

    @staticmethod
    def get_case_id_map(suite_id: int) -> dict[str, int]:
        """获取 case_key → DB id 映射"""
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT id, case_key FROM ai_eval_memory_case WHERE suite_id = %s",
                (suite_id,)
            )
            return {row[1]: row[0] for row in cur.fetchall()}

    @staticmethod
    def delete_by_layer(suite_id: int, layer: str) -> int:
        """删除指定层的所有用例"""
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                "DELETE FROM ai_eval_memory_case WHERE suite_id = %s AND layer = %s",
                (suite_id, layer),
            )
            return cur.rowcount


# ═══════════════════════════════════════════════════════════
# Report DAO
# ═══════════════════════════════════════════════════════════

class MemoryEvalReportDAO:

    @staticmethod
    def create_report(
        suite_id: int,
        trigger_type: str = "manual",
        filter_layers: list | None = None,
        filter_query_types: list | None = None,
        use_llm: bool = False,
    ) -> str:
        """创建评测报告记录，返回 report_key"""
        report_key = f"mem_rpt_{uuid.uuid4().hex[:12]}"
        now = int(time.time() * 1000)
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO ai_eval_memory_report
                (report_key, suite_id, trigger_type, filter_layers, filter_query_types,
                 use_llm, status, created_at)
                VALUES (%s,%s,%s,%s,%s,%s,'running',%s)
            """, (
                report_key, suite_id, trigger_type,
                json.dumps(filter_layers or []),
                json.dumps(filter_query_types or []),
                use_llm, now,
            ))
        return report_key

    @staticmethod
    def complete_report(
        report_key: str,
        total: int, passed: int, failed: int,
        pass_rate: float,
        avg_recall_at_5: float,
        avg_mrr: float,
        top1_hit_rate: float,
        total_duration_ms: float,
        by_layer: dict,
        by_query_type: dict,
        failures: list,
    ) -> None:
        """更新报告为完成状态"""
        now = int(time.time() * 1000)
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute("""
                UPDATE ai_eval_memory_report SET
                    total=%s, passed=%s, failed=%s,
                    pass_rate=%s, avg_recall_at_5=%s, avg_mrr=%s, top1_hit_rate=%s,
                    total_duration_ms=%s,
                    by_layer=%s, by_query_type=%s, failures=%s,
                    status='completed', completed_at=%s
                WHERE report_key=%s
            """, (
                total, passed, failed,
                pass_rate, avg_recall_at_5, avg_mrr, top1_hit_rate,
                total_duration_ms,
                json.dumps(by_layer, ensure_ascii=False),
                json.dumps(by_query_type, ensure_ascii=False),
                json.dumps(failures[:50], ensure_ascii=False),  # 限制失败详情数量
                now, report_key,
            ))

    @staticmethod
    def fail_report(report_key: str, error: str) -> None:
        """标记报告为失败"""
        now = int(time.time() * 1000)
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute("""
                UPDATE ai_eval_memory_report SET
                    status='failed', failures=%s, completed_at=%s
                WHERE report_key=%s
            """, (
                json.dumps([{"error": error}]),
                now, report_key,
            ))

    @staticmethod
    def list_reports(limit: int = 20, offset: int = 0) -> list[dict]:
        """查询报告列表"""
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT report_key, suite_id, trigger_type, filter_layers, filter_query_types,
                       use_llm, total, passed, failed, pass_rate,
                       avg_recall_at_5, avg_mrr, top1_hit_rate, total_duration_ms,
                       by_layer, by_query_type, status, created_at, completed_at
                FROM ai_eval_memory_report
                ORDER BY created_at DESC
                LIMIT %s OFFSET %s
            """, (limit, offset))
            results = []
            for row in cur.fetchall():
                results.append({
                    "report_key": row[0],
                    "suite_id": row[1],
                    "trigger_type": row[2],
                    "filter_layers": row[3] if isinstance(row[3], list) else json.loads(row[3] or "[]"),
                    "filter_query_types": row[4] if isinstance(row[4], list) else json.loads(row[4] or "[]"),
                    "use_llm": row[5],
                    "total": row[6],
                    "passed": row[7],
                    "failed": row[8],
                    "pass_rate": float(row[9] or 0),
                    "avg_recall_at_5": float(row[10] or 0),
                    "avg_mrr": float(row[11] or 0),
                    "top1_hit_rate": float(row[12] or 0),
                    "total_duration_ms": float(row[13] or 0),
                    "by_layer": row[14] if isinstance(row[14], dict) else json.loads(row[14] or "{}"),
                    "by_query_type": row[15] if isinstance(row[15], dict) else json.loads(row[15] or "{}"),
                    "status": row[16],
                    "created_at": row[17],
                    "completed_at": row[18],
                })
            return results

    @staticmethod
    def get_report(report_key: str) -> dict | None:
        """获取单个报告详情"""
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT id, report_key, suite_id, trigger_type, filter_layers,
                       filter_query_types, use_llm, total, passed, failed,
                       pass_rate, avg_recall_at_5, avg_mrr, top1_hit_rate,
                       total_duration_ms, by_layer, by_query_type, failures,
                       status, created_at, completed_at
                FROM ai_eval_memory_report WHERE report_key = %s
            """, (report_key,))
            row = cur.fetchone()
            if not row:
                return None
            return {
                "id": row[0],
                "report_key": row[1],
                "suite_id": row[2],
                "trigger_type": row[3],
                "filter_layers": row[4] if isinstance(row[4], list) else json.loads(row[4] or "[]"),
                "filter_query_types": row[5] if isinstance(row[5], list) else json.loads(row[5] or "[]"),
                "use_llm": row[6],
                "total": row[7],
                "passed": row[8],
                "failed": row[9],
                "pass_rate": float(row[10] or 0),
                "avg_recall_at_5": float(row[11] or 0),
                "avg_mrr": float(row[12] or 0),
                "top1_hit_rate": float(row[13] or 0),
                "total_duration_ms": float(row[14] or 0),
                "by_layer": row[15] if isinstance(row[15], dict) else json.loads(row[15] or "{}"),
                "by_query_type": row[16] if isinstance(row[16], dict) else json.loads(row[16] or "{}"),
                "failures": row[17] if isinstance(row[17], list) else json.loads(row[17] or "[]"),
                "status": row[18],
                "created_at": row[19],
                "completed_at": row[20],
            }

    @staticmethod
    def get_report_id_by_key(report_key: str) -> int | None:
        """获取报告 DB ID"""
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT id FROM ai_eval_memory_report WHERE report_key = %s",
                (report_key,),
            )
            row = cur.fetchone()
            return row[0] if row else None


# ═══════════════════════════════════════════════════════════
# Case Result DAO
# ═══════════════════════════════════════════════════════════

class MemoryEvalCaseResultDAO:

    @staticmethod
    def batch_insert(report_id: int, case_id_map: dict[str, int], results: list[dict]) -> int:
        """批量插入用例执行结果

        Args:
            report_id: 报告 DB ID
            case_id_map: case_key → case DB id 映射
            results: 执行结果列表
        Returns:
            插入数量
        """
        if not results:
            return 0
        now = int(time.time() * 1000)
        count = 0
        with get_conn() as conn:
            cur = conn.cursor()
            for r in results:
                case_key = r.get("case_key", "") or r.get("case_id", "")
                case_db_id = case_id_map.get(case_key, 0)
                if case_db_id == 0:
                    continue
                cur.execute("""
                    INSERT INTO ai_eval_memory_case_result
                    (report_id, case_id, case_key, layer, query_type,
                     query, description, passed, recall_at_k, precision_at_k,
                     mrr, top1_hit, duration_ms, expected, actual,
                     memory_snapshot_count, memory_snapshot, memory_changes,
                     extracted_dimensions, output_detail, error_message, created_at)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                """, (
                    report_id, case_db_id, case_key,
                    r.get("layer", ""), r.get("query_type", ""),
                    r.get("query", ""), r.get("description", ""),
                    r.get("passed", False),
                    r.get("recall_at_k", 0), r.get("precision_at_k", 0),
                    r.get("mrr", 0), r.get("top1_hit", False),
                    r.get("duration_ms", 0),
                    json.dumps(r.get("expected", []), ensure_ascii=False),
                    json.dumps(r.get("actual", [])[:5], ensure_ascii=False),
                    r.get("memory_snapshot_count", 0),
                    json.dumps(r.get("memory_snapshot", []), ensure_ascii=False),
                    json.dumps(r.get("memory_changes", [])[:5], ensure_ascii=False),
                    json.dumps(r.get("extracted_dimensions", []), ensure_ascii=False),
                    json.dumps(r.get("output_detail", {}), ensure_ascii=False),
                    r.get("error", "") or r.get("error_message", ""),
                    now,
                ))
                count += 1
        return count

    @staticmethod
    def list_by_report(report_id: int) -> list[dict]:
        """查询报告下的所有用例结果"""
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT case_key, layer, query_type, query, description,
                       passed, recall_at_k, precision_at_k, mrr, top1_hit,
                       duration_ms, expected, actual, memory_snapshot_count,
                       memory_snapshot, memory_changes, extracted_dimensions,
                       output_detail, error_message
                FROM ai_eval_memory_case_result
                WHERE report_id = %s
                ORDER BY id ASC
            """, (report_id,))
            results = []
            for row in cur.fetchall():
                results.append({
                    "case_key": row[0],
                    "layer": row[1],
                    "query_type": row[2],
                    "query": row[3],
                    "description": row[4],
                    "passed": row[5],
                    "recall_at_k": float(row[6] or 0),
                    "precision_at_k": float(row[7] or 0),
                    "mrr": float(row[8] or 0),
                    "top1_hit": row[9],
                    "duration_ms": float(row[10] or 0),
                    "expected": row[11] if isinstance(row[11], list) else json.loads(row[11] or "[]"),
                    "actual": row[12] if isinstance(row[12], list) else json.loads(row[12] or "[]"),
                    "memory_snapshot_count": row[13],
                    "memory_snapshot": row[14] if isinstance(row[14], list) else json.loads(row[14] or "[]"),
                    "memory_changes": row[15] if isinstance(row[15], list) else json.loads(row[15] or "[]"),
                    "extracted_dimensions": row[16] if isinstance(row[16], list) else json.loads(row[16] or "[]"),
                    "output_detail": row[17] if isinstance(row[17], dict) else json.loads(row[17] or "{}"),
                    "error_message": row[18] or "",
                })
            return results
