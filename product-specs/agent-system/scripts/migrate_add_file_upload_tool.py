"""迁移脚本：向 ai_tool_definition 表新增 file_upload 工具

执行方式：
    cd product-specs/agent-system
    python scripts/migrate_add_file_upload_tool.py

前置条件：
    - ai_tool_definition 表已存在
    - .env 中配置了数据库连接
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from src.store.pg_pool import get_conn

TOOL = {
    "api_key": "file_upload",
    "name": "文件上传（COS）",
    "description": "将本地文件上传到腾讯云 COS 对象存储，返回可通过浏览器直接访问的链接。适用于生成的 HTML 报告、文档、图片等需要分享的文件。",
    "category": "file",
    "read_only_flg": 0,
    "destructive_flg": 0,
    "sort_num": 100,
}


def main():
    print("开始新增 file_upload 工具定义...")

    with get_conn() as conn:
        cur = conn.cursor()

        now = int(time.time())

        # 获取当前最大 ID
        cur.execute("SELECT COALESCE(MAX(id), 3000000000000000) FROM ai_tool_definition")
        max_id = cur.fetchone()[0]
        tool_id = max_id + 1

        cur.execute("""
            INSERT INTO ai_tool_definition
            (id, api_key, tenant_id, name, description, input_schema, prompt,
             category, tags, icon, read_only_flg, destructive_flg,
             enabled_flg, system_flg, sort_num, ext_info,
             delete_flg, created_at, created_by, updated_at, updated_by)
            VALUES (%s, %s, 0, %s, %s, '{}', '',
                    %s, '["file", "upload", "cos", "share"]', '', %s, %s,
                    1, 1, %s, '{}',
                    0, %s, 0, %s, 0)
            ON CONFLICT (tenant_id, api_key) WHERE delete_flg = 0 DO NOTHING
        """, (
            tool_id, TOOL["api_key"], TOOL["name"], TOOL["description"],
            TOOL["category"], TOOL["read_only_flg"], TOOL["destructive_flg"],
            TOOL["sort_num"], now, now,
        ))
        print(f"  ✓ {TOOL['api_key']} ({TOOL['name']})")

        conn.commit()

    # 验证
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT api_key, name, enabled_flg FROM ai_tool_definition "
            "WHERE api_key = 'file_upload' AND delete_flg = 0"
        )
        row = cur.fetchone()
        if row:
            print(f"\n验证通过: api_key={row[0]}, name={row[1]}, enabled={row[2]}")
        else:
            print("\n⚠️ 验证失败：未找到 file_upload 记录")
            sys.exit(1)

    print("\n完成！")


if __name__ == "__main__":
    main()
