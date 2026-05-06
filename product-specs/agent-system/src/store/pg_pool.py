"""PostgreSQL 连接池 — 基于 psycopg2 的简单连接池"""
from __future__ import annotations

import logging
import os
from contextlib import contextmanager
from typing import Generator

import psycopg2
from psycopg2 import pool as pg_pool

logger = logging.getLogger(__name__)

_pool: pg_pool.ThreadedConnectionPool | None = None


def get_pool() -> pg_pool.ThreadedConnectionPool:
    """获取全局连接池（懒初始化）"""
    global _pool
    if _pool is not None:
        return _pool

    _pool = pg_pool.ThreadedConnectionPool(
        minconn=2,
        maxconn=10,
        host=os.environ.get("PG_HOST", "127.0.0.1"),
        port=int(os.environ.get("PG_PORT", "5432")),
        dbname=os.environ.get("PG_DB", "paas_db"),
        user=os.environ.get("PG_USER", "postgres"),
        password=os.environ.get("PG_PASSWORD", "123456"),
        options="-c search_path=paas_ai",
    )
    logger.info("PG 连接池初始化完成: %s:%s/%s schema=paas_ai",
                os.environ.get("PG_HOST", "127.0.0.1"),
                os.environ.get("PG_PORT", "5432"),
                os.environ.get("PG_DB", "paas_db"))
    return _pool


def close_pool() -> None:
    global _pool
    if _pool:
        _pool.closeall()
        _pool = None


@contextmanager
def get_conn() -> Generator:
    """从连接池获取连接（自动归还）"""
    p = get_pool()
    conn = p.getconn()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        p.putconn(conn)
