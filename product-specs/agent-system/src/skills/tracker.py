"""技能执行轨迹追踪 + 度量 + 淘汰

SkillTracker: 记录每次技能执行的轨迹
SkillMetrics: 技能效果度量（成功率/token/耗时）
"""
from __future__ import annotations

import json
import logging
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class SkillExecution:
    """单次技能执行轨迹"""
    skill_name: str
    arguments: dict[str, str] = field(default_factory=dict)
    tool_calls: list[dict] = field(default_factory=list)  # [{name, args, duration_ms, success}]
    total_tokens: int = 0
    duration_ms: float = 0.0
    output: str = ""
    user_feedback: str = "unknown"  # accepted / retry / abandoned / unknown
    timestamp: float = field(default_factory=time.time)
    version: int = 1  # 技能版本号


@dataclass
class SkillMetrics:
    """技能效果度量"""
    skill_name: str
    total_executions: int = 0
    success_count: int = 0
    retry_count: int = 0
    abandon_count: int = 0
    total_tokens: int = 0
    total_duration_ms: float = 0.0
    last_used: float = 0.0
    version: int = 1

    @property
    def success_rate(self) -> float:
        return self.success_count / max(self.total_executions, 1)

    @property
    def avg_tokens(self) -> float:
        return self.total_tokens / max(self.total_executions, 1)

    @property
    def avg_duration_ms(self) -> float:
        return self.total_duration_ms / max(self.total_executions, 1)

    @property
    def should_retire(self) -> bool:
        """连续低成功率或长期未使用 → 淘汰"""
        if self.total_executions < 3:
            return False
        days_unused = (time.time() - self.last_used) / 86400 if self.last_used else 999
        return self.success_rate < 0.3 or days_unused > 30


class SkillTracker:
    """技能执行追踪器 — SQLite 持久化"""

    def __init__(self, db_path: str = "./data/skill_metrics.db") -> None:
        self._db_path = Path(db_path)
        self._conn: sqlite3.Connection | None = None

    def _ensure_db(self) -> sqlite3.Connection:
        if self._conn is not None:
            return self._conn
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS skill_executions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                skill_name TEXT NOT NULL,
                arguments TEXT DEFAULT '{}',
                tool_calls TEXT DEFAULT '[]',
                total_tokens INTEGER DEFAULT 0,
                duration_ms REAL DEFAULT 0,
                output TEXT DEFAULT '',
                user_feedback TEXT DEFAULT 'unknown',
                version INTEGER DEFAULT 1,
                timestamp REAL NOT NULL
            )
        """)
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS skill_metrics (
                skill_name TEXT PRIMARY KEY,
                total_executions INTEGER DEFAULT 0,
                success_count INTEGER DEFAULT 0,
                retry_count INTEGER DEFAULT 0,
                abandon_count INTEGER DEFAULT 0,
                total_tokens INTEGER DEFAULT 0,
                total_duration_ms REAL DEFAULT 0,
                last_used REAL DEFAULT 0,
                version INTEGER DEFAULT 1
            )
        """)
        self._conn.commit()
        return self._conn

    def record(self, execution: SkillExecution) -> None:
        """记录一次技能执行"""
        conn = self._ensure_db()
        conn.execute(
            "INSERT INTO skill_executions (skill_name, arguments, tool_calls, total_tokens, duration_ms, output, user_feedback, version, timestamp) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (execution.skill_name, json.dumps(execution.arguments, ensure_ascii=False),
             json.dumps(execution.tool_calls, ensure_ascii=False),
             execution.total_tokens, execution.duration_ms,
             execution.output[:2000], execution.user_feedback,
             execution.version, execution.timestamp),
        )
        # 更新度量
        self._update_metrics(execution)
        conn.commit()

    def _update_metrics(self, execution: SkillExecution) -> None:
        conn = self._ensure_db()
        row = conn.execute("SELECT * FROM skill_metrics WHERE skill_name = ?",
                           (execution.skill_name,)).fetchone()
        if row is None:
            conn.execute(
                "INSERT INTO skill_metrics (skill_name, total_executions, success_count, retry_count, abandon_count, total_tokens, total_duration_ms, last_used, version) VALUES (?, 1, ?, ?, ?, ?, ?, ?, ?)",
                (execution.skill_name,
                 1 if execution.user_feedback == "accepted" else 0,
                 1 if execution.user_feedback == "retry" else 0,
                 1 if execution.user_feedback == "abandoned" else 0,
                 execution.total_tokens, execution.duration_ms,
                 execution.timestamp, execution.version),
            )
        else:
            conn.execute("""
                UPDATE skill_metrics SET
                    total_executions = total_executions + 1,
                    success_count = success_count + ?,
                    retry_count = retry_count + ?,
                    abandon_count = abandon_count + ?,
                    total_tokens = total_tokens + ?,
                    total_duration_ms = total_duration_ms + ?,
                    last_used = ?,
                    version = ?
                WHERE skill_name = ?
            """, (
                1 if execution.user_feedback == "accepted" else 0,
                1 if execution.user_feedback == "retry" else 0,
                1 if execution.user_feedback == "abandoned" else 0,
                execution.total_tokens, execution.duration_ms,
                execution.timestamp, execution.version,
                execution.skill_name,
            ))

    def get_metrics(self, skill_name: str) -> SkillMetrics | None:
        conn = self._ensure_db()
        row = conn.execute("SELECT * FROM skill_metrics WHERE skill_name = ?",
                           (skill_name,)).fetchone()
        if row is None:
            return None
        return SkillMetrics(
            skill_name=row[0], total_executions=row[1], success_count=row[2],
            retry_count=row[3], abandon_count=row[4], total_tokens=row[5],
            total_duration_ms=row[6], last_used=row[7], version=row[8],
        )

    def get_all_metrics(self) -> list[SkillMetrics]:
        conn = self._ensure_db()
        rows = conn.execute("SELECT * FROM skill_metrics ORDER BY total_executions DESC").fetchall()
        return [SkillMetrics(
            skill_name=r[0], total_executions=r[1], success_count=r[2],
            retry_count=r[3], abandon_count=r[4], total_tokens=r[5],
            total_duration_ms=r[6], last_used=r[7], version=r[8],
        ) for r in rows]

    def get_executions(self, skill_name: str, limit: int = 10) -> list[SkillExecution]:
        conn = self._ensure_db()
        rows = conn.execute(
            "SELECT * FROM skill_executions WHERE skill_name = ? ORDER BY timestamp DESC LIMIT ?",
            (skill_name, limit),
        ).fetchall()
        return [SkillExecution(
            skill_name=r[1], arguments=json.loads(r[2]), tool_calls=json.loads(r[3]),
            total_tokens=r[4], duration_ms=r[5], output=r[6],
            user_feedback=r[7], version=r[8], timestamp=r[9],
        ) for r in rows]

    def get_retiring_skills(self) -> list[str]:
        """获取应该淘汰的技能"""
        return [m.skill_name for m in self.get_all_metrics() if m.should_retire]

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None
