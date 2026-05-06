"""
数据库连接管理
p_common_metadata 和 p_tenant_data 都在同一个 PG 库中
"""
import psycopg2
import psycopg2.extras
from .config import OLD_DB


def get_pg():
    """PG 连接（元数据 + 业务数据都在这里）"""
    conn = psycopg2.connect(**OLD_DB)
    conn.autocommit = False
    return conn


def get_pg_dict():
    """PG 连接（返回 dict cursor）"""
    conn = psycopg2.connect(**OLD_DB)
    conn.autocommit = False
    return conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
