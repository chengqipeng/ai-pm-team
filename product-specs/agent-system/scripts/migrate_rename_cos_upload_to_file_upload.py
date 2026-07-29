"""迁移脚本：将 ai_tool_definition 表中 cos_upload 重命名为 file_upload

执行方式：
    cd product-specs/agent-system
    python scripts/migrate_rename_cos_upload_to_file_upload.py

说明：
    数据库中 tools 的 api_key 仍为 cos_upload，需更新为 file_upload 以与代码保持一致。
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from src.store.pg_pool import get_conn


def main():
    print("开始将 cos_upload 重命名为 file_upload ...")

    with get_conn() as conn:
        cur = conn.cursor()

        # 先检查是否已存在 file_upload，避免冲突
        cur.execute(
            "SELECT id, api_key FROM ai_tool_definition "
            "WHERE api_key = 'file_upload' AND delete_flg = 0"
        )
        existing = cur.fetchone()
        if existing:
            print(f"⚠️  file_upload 已存在 (id={existing[0]})，无需迁移。")
            return

        # 执行重命名
        now = int(time.time())
        cur.execute("""
            UPDATE ai_tool_definition
            SET api_key = 'file_upload',
                updated_at = %s
            WHERE api_key = 'cos_upload'
              AND delete_flg = 0
        """, (now,))

        affected = cur.rowcount
        if affected == 0:
            print("⚠️  未找到 api_key = 'cos_upload' 的记录，跳过。")
            return

        conn.commit()
        print(f"  ✓ 已将 {affected} 条记录的 api_key 从 cos_upload 更新为 file_upload")

    # 验证
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT id, api_key, name, enabled_flg FROM ai_tool_definition "
            "WHERE api_key = 'file_upload' AND delete_flg = 0"
        )
        row = cur.fetchone()
        if row:
            print(f"\n验证通过: id={row[0]}, api_key={row[1]}, name={row[2]}, enabled={row[3]}")
        else:
            print("\n⚠️ 验证失败：未找到 file_upload 记录")
            sys.exit(1)

    print("\n完成！")


if __name__ == "__main__":
    main()
