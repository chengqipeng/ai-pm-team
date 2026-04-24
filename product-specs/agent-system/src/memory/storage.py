"""记忆存储 — 原子文件 I/O + SQLite FTS5 全文搜索

MemoryStorage 提供两种存储模式：
1. 文件模式：每用户一个 .md 文件，原子写入（写临时文件 → os.rename）
2. SQLite FTS5 模式：全文搜索索引，支持快速语义检索
"""
from __future__ import annotations

import logging
import os
import sqlite3
import tempfile
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class MemoryStorage:
    """原子文件 I/O + SQLite FTS5 全文搜索的记忆存储"""

    def __init__(self, storage_dir: str = "./data/memory") -> None:
        self._storage_dir = Path(storage_dir)
        self._db_path = self._storage_dir / "memory.db"
        self._conn: sqlite3.Connection | None = None

    def _ensure_db(self) -> sqlite3.Connection:
        """延迟初始化 SQLite + FTS5"""
        if self._conn is not None:
            return self._conn
        self._storage_dir.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        # 创建 FTS5 虚拟表
        self._conn.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts USING fts5(
                user_id, dimension, content, metadata,
                created_at UNINDEXED,
                tokenize='unicode61'
            )
        """)
        # 普通表用于精确查询
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS memories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                dimension TEXT NOT NULL DEFAULT '',
                content TEXT NOT NULL,
                metadata TEXT DEFAULT '{}',
                created_at REAL NOT NULL
            )
        """)
        self._conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_memories_user ON memories(user_id)
        """)
        self._conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_memories_dimension ON memories(user_id, dimension)
        """)
        self._conn.commit()
        logger.info("MemoryStorage initialized: %s", self._db_path)
        return self._conn

    # ── FTS5 操作 ──

    def add(self, user_id: str, content: str, dimension: str = "",
            metadata: str = "{}") -> int:
        """添加记忆条目，同时写入 FTS5 索引和普通表"""
        conn = self._ensure_db()
        now = time.time()
        cursor = conn.execute(
            "INSERT INTO memories (user_id, dimension, content, metadata, created_at) VALUES (?, ?, ?, ?, ?)",
            (user_id, dimension, content, metadata, now),
        )
        row_id = cursor.lastrowid
        conn.execute(
            "INSERT INTO memory_fts (user_id, dimension, content, metadata, created_at) VALUES (?, ?, ?, ?, ?)",
            (user_id, dimension, content, metadata, str(now)),
        )
        conn.commit()
        return row_id

    def search(self, query: str, user_id: str | None = None,
               dimension: str | None = None, top_k: int = 5) -> list[dict]:
        """FTS5 全文搜索，中文自动 fallback 到 LIKE"""
        conn = self._ensure_db()

        # FTS5 unicode61 对中文分词支持有限，优先尝试 FTS5，失败则 LIKE
        # 构建 FTS5 查询：每个词用 OR 连接
        words = query.strip().split()
        if not words:
            return []

        # 尝试 FTS5
        fts_terms = " OR ".join(f'"{w}"' for w in words if w)
        conditions = [f"memory_fts MATCH '{fts_terms}'"]
        params: list[Any] = []
        if user_id:
            conditions.append("user_id = ?")
            params.append(user_id)
        if dimension:
            conditions.append("dimension = ?")
            params.append(dimension)

        where = " AND ".join(conditions)
        sql = f"""
            SELECT user_id, dimension, content, metadata, created_at, rank
            FROM memory_fts WHERE {where}
            ORDER BY rank LIMIT ?
        """
        params.append(top_k)

        try:
            rows = conn.execute(sql, params).fetchall()
            if rows:
                return [
                    {"user_id": r[0], "dimension": r[1], "content": r[2],
                     "metadata": r[3], "created_at": float(r[4]), "rank": r[5]}
                    for r in rows
                ]
        except sqlite3.OperationalError:
            pass

        # FTS5 无结果或失败 → LIKE fallback
        return self._search_like(query, user_id, dimension, top_k)

    def _search_like(self, query: str, user_id: str | None,
                     dimension: str | None, top_k: int) -> list[dict]:
        """FTS5 查询失败时的 LIKE fallback — 多词 OR 匹配"""
        conn = self._ensure_db()

        # 拆分查询词，每个词一个 LIKE 条件，用 OR 连接
        words = [w.strip() for w in query.split() if w.strip()]
        if not words:
            words = [query.strip()]

        like_conditions = [f"content LIKE ?" for _ in words]
        like_params: list[Any] = [f"%{w}%" for w in words]

        # 组合：(word1 OR word2 OR ...) AND user_id AND dimension
        word_clause = "(" + " OR ".join(like_conditions) + ")"
        conditions = [word_clause]
        params = list(like_params)

        if user_id:
            conditions.append("user_id = ?")
            params.append(user_id)
        if dimension:
            conditions.append("dimension = ?")
            params.append(dimension)
        where = " AND ".join(conditions)
        sql = f"SELECT user_id, dimension, content, metadata, created_at FROM memories WHERE {where} ORDER BY created_at DESC LIMIT ?"
        params.append(top_k)
        rows = conn.execute(sql, params).fetchall()
        return [
            {"user_id": r[0], "dimension": r[1], "content": r[2],
             "metadata": r[3], "created_at": r[4], "rank": 0.0}
            for r in rows
        ]

    def get_by_user(self, user_id: str, dimension: str | None = None,
                    limit: int = 50) -> list[dict]:
        """按用户 ID 精确查询"""
        conn = self._ensure_db()
        if dimension:
            rows = conn.execute(
                "SELECT id, user_id, dimension, content, metadata, created_at FROM memories WHERE user_id = ? AND dimension = ? ORDER BY created_at DESC LIMIT ?",
                (user_id, dimension, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT id, user_id, dimension, content, metadata, created_at FROM memories WHERE user_id = ? ORDER BY created_at DESC LIMIT ?",
                (user_id, limit),
            ).fetchall()
        return [
            {"id": r[0], "user_id": r[1], "dimension": r[2], "content": r[3],
             "metadata": r[4], "created_at": r[5]}
            for r in rows
        ]

    def count(self, user_id: str | None = None) -> int:
        """统计记忆条目数"""
        conn = self._ensure_db()
        if user_id:
            return conn.execute("SELECT COUNT(*) FROM memories WHERE user_id = ?", (user_id,)).fetchone()[0]
        return conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0]

    def delete_by_ids(self, ids: list[int]) -> int:
        """按 ID 批量删除记忆（memories 表 + memory_fts 表同步）"""
        if not ids:
            return 0
        conn = self._ensure_db()
        # 先查出要删除的内容，用于同步删除 FTS5 表
        placeholders = ",".join("?" for _ in ids)
        rows = conn.execute(
            f"SELECT user_id, dimension, content, created_at FROM memories WHERE id IN ({placeholders})",
            ids,
        ).fetchall()
        # 删除普通表
        conn.execute(f"DELETE FROM memories WHERE id IN ({placeholders})", ids)
        # 同步删除 FTS5 表（FTS5 没有 rowid 关联，用内容匹配删除）
        for r in rows:
            try:
                conn.execute(
                    "DELETE FROM memory_fts WHERE user_id = ? AND dimension = ? AND content = ? AND created_at = ?",
                    (r[0], r[1], r[2], str(r[3])),
                )
            except sqlite3.OperationalError:
                pass
        conn.commit()
        return len(rows)

    def delete_by_user(self, user_id: str) -> int:
        """删除用户所有记忆"""
        conn = self._ensure_db()
        conn.execute("DELETE FROM memories WHERE user_id = ?", (user_id,))
        conn.execute("DELETE FROM memory_fts WHERE user_id = ?", (user_id,))
        conn.commit()
        return conn.total_changes

    def cleanup_expired(self, cutoff_time: float, dimension: str | None = None) -> int:
        """删除指定时间之前的过期记忆"""
        conn = self._ensure_db()
        if dimension:
            rows = conn.execute(
                "SELECT id FROM memories WHERE created_at < ? AND dimension = ?",
                (cutoff_time, dimension),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT id FROM memories WHERE created_at < ?",
                (cutoff_time,),
            ).fetchall()
        ids = [r[0] for r in rows]
        return self.delete_by_ids(ids)

    def cleanup_overflow(self, user_id: str, dimension: str, max_count: int) -> int:
        """按容量上限淘汰最旧的记忆，保留最新的 max_count 条"""
        conn = self._ensure_db()
        # 查出超出上限的旧记录 ID
        rows = conn.execute(
            "SELECT id FROM memories WHERE user_id = ? AND dimension = ? ORDER BY created_at DESC",
            (user_id, dimension),
        ).fetchall()
        if len(rows) <= max_count:
            return 0
        overflow_ids = [r[0] for r in rows[max_count:]]
        return self.delete_by_ids(overflow_ids)

    # ── 文件模式（短期记忆/用户画像） ──

    def read_file(self, user_id: str) -> str:
        """读取用户记忆文件"""
        safe_id = user_id.replace("/", "_").replace("\\", "_").replace("..", "_")
        path = self._storage_dir / f"{safe_id}.md"
        try:
            return path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return ""

    def write_file(self, user_id: str, content: str) -> None:
        """原子写入用户记忆文件（写临时文件 → os.rename）"""
        safe_id = user_id.replace("/", "_").replace("\\", "_").replace("..", "_")
        path = self._storage_dir / f"{safe_id}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.stem}_", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(content)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, str(path))
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None
