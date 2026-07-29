"""数据迁移脚本：从旧 ai_skill_definition 初始化 ai_skill + 新 ai_skill_definition

执行方式：
    python -m scripts.migrate_to_three_tables

前提：
    1. 已执行 migrate_skill_version_refactor.sql（创建 ai_skill 表 + 新 ai_skill_definition 表）
    2. 旧 ai_skill_definition 表已 RENAME 为 ai_skill_definition_old
    3. .env 中数据库连接配置正确

逻辑：
    旧 ai_skill_definition 每行 → ai_skill（主记录）+ 新 ai_skill_definition（版本内容）
    ai_skill_resource 补齐 version 字段
"""
import logging
import sys
import time

sys.path.insert(0, ".")

from src.store.pg_pool import get_conn
from src.store.snowflake import next_id

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

OLD_TABLE = "ai_skill_definition_old"  # 旧表 RENAME 后的名字


def migrate():
    logger.info("开始迁移: %s → ai_skill + ai_skill_definition", OLD_TABLE)

    with get_conn() as conn:
        cur = conn.cursor()

        # 检查旧表是否存在
        cur.execute(
            "SELECT EXISTS(SELECT 1 FROM information_schema.tables WHERE table_name=%s)",
            (OLD_TABLE,),
        )
        if not cur.fetchone()[0]:
            logger.error("旧表 %s 不存在，请先执行: ALTER TABLE ai_skill_definition RENAME TO %s",
                         OLD_TABLE, OLD_TABLE)
            return

        # 读取旧表数据
        cur.execute(f"""
            SELECT id, api_key, tenant_id, name, description, when_to_use, owner,
                   context, agent, model, allowed_tools, arguments, prompt,
                   risk_level, requires_confirmation, max_tool_calls, timeout_ms,
                   version, exec_count, success_count, avg_duration_ms, ext_info,
                   delete_flg, created_at, created_by, updated_at, updated_by,
                   enabled_flg, category, tags, icon, sort_num, system_flg,
                   output_mode, component_apikey, post_output_behavior
            FROM {OLD_TABLE}
            WHERE delete_flg = 0
            ORDER BY tenant_id, api_key
        """)
        rows = cur.fetchall()
        logger.info("旧表读取 %d 行", len(rows))

        now = int(time.time() * 1000)
        skill_count = 0
        def_count = 0

        for row in rows:
            (old_id, api_key, tenant_id, name, description, when_to_use, owner,
             context, agent, model, allowed_tools, arguments, prompt,
             risk_level, requires_confirmation, max_tool_calls, timeout_ms,
             version, exec_count, success_count, avg_duration_ms, ext_info,
             delete_flg, created_at, created_by, updated_at, updated_by,
             enabled_flg, category, tags, icon, sort_num, system_flg,
             output_mode, component_apikey, post_output_behavior) = row

            version = version or "1.0.0"
            enabled_flg = enabled_flg if enabled_flg is not None else 1
            system_flg = system_flg if system_flg is not None else 0
            category = category or ""
            tags = tags or "[]"
            icon = icon or ""
            sort_num = sort_num or 0
            output_mode = output_mode or "text"
            component_apikey = component_apikey or ""
            post_output_behavior = post_output_behavior or "silent"

            # 1. 写入 ai_skill
            cur.execute("""
                INSERT INTO ai_skill
                (id, api_key, tenant_id, name, description, owner,
                 category, tags, icon, sort_num, current_version,
                 enabled_flg, system_flg, exec_count, success_count, avg_duration_ms,
                 ext_info, delete_flg, created_at, created_by, updated_at, updated_by)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (tenant_id, api_key) WHERE delete_flg = 0
                DO NOTHING
            """, (
                next_id(), api_key, tenant_id, name, description, owner or "",
                category, tags, icon, sort_num, version,
                enabled_flg, system_flg, exec_count or 0, success_count or 0, avg_duration_ms or 0,
                ext_info or "{}", 0, created_at, created_by, updated_at, updated_by,
            ))
            skill_count += 1

            # 2. 写入新 ai_skill_definition
            cur.execute("""
                INSERT INTO ai_skill_definition
                (id, skill_api_key, tenant_id, version, changelog,
                 when_to_use, context, agent, model, allowed_tools, arguments, prompt,
                 risk_level, requires_confirmation, max_tool_calls, timeout_ms,
                 output_mode, component_apikey, post_output_behavior,
                 published_by, delete_flg, created_at, created_by, updated_at, updated_by)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (tenant_id, skill_api_key, version) WHERE delete_flg = 0
                DO NOTHING
            """, (
                next_id(), api_key, tenant_id, version, "从旧表迁移",
                when_to_use or "", context or "inline", agent or "", model or "",
                allowed_tools or "[]", arguments or "[]", prompt or "",
                risk_level or "read_only", requires_confirmation or 0,
                max_tool_calls or 20, timeout_ms or 60000,
                output_mode, component_apikey, post_output_behavior,
                created_by, 0, created_at, created_by, updated_at, updated_by,
            ))
            def_count += 1

        # 3. ai_skill_resource 补齐 version
        cur.execute("""
            UPDATE ai_skill_resource r
            SET version = COALESCE(
                (SELECT current_version FROM ai_skill s
                 WHERE s.api_key = r.skill_api_key AND s.tenant_id = r.tenant_id AND s.delete_flg = 0),
                '1.0.0'
            )
            WHERE r.delete_flg = 0
        """)
        resource_updated = cur.rowcount

        conn.commit()

    logger.info("迁移完成: ai_skill=%d, ai_skill_definition=%d, resource_version_updated=%d",
                skill_count, def_count, resource_updated)


if __name__ == "__main__":
    migrate()
