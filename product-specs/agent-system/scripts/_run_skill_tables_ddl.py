"""一次性执行 sql/init_tables.sql 中 skill 相关的 4 张表 DDL

提取第 9~12 号表：ai_skill_definition / ai_skill_version / ai_skill_policy / ai_skill_exec_log
所有 DDL 是 `CREATE TABLE IF NOT EXISTS`，幂等。
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def main() -> int:
    sql_file = ROOT / "sql" / "init_tables.sql"
    content = sql_file.read_text(encoding="utf-8")

    # 仅截取 `-- 9. Skill 定义主表` 到文件末尾前（skill 四张表都在这区间）
    marker = "-- 9. Skill 定义主表"
    idx = content.find(marker)
    if idx < 0:
        logger.error("在 init_tables.sql 中找不到 skill DDL 起始标记")
        return 1
    skill_ddl = content[idx:]

    # 兜底：如果后面还有非 skill 表，按 "-- 13." 截断
    cut = skill_ddl.find("\n-- 13.")
    if cut > 0:
        skill_ddl = skill_ddl[:cut]

    skill_ddl = "SET search_path TO paas_ai;\n" + skill_ddl

    from src.store.pg_pool import get_conn

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(skill_ddl)
        conn.commit()
        with conn.cursor() as cur:
            cur.execute(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema='paas_ai' AND table_name LIKE 'ai_skill%' "
                "ORDER BY table_name"
            )
            tables = [r[0] for r in cur.fetchall()]

    logger.info("已建表: %s", tables)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
