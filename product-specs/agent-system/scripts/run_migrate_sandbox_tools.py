"""执行沙盒工具表迁移：插入 5 个远程执行工具定义到 ai_tool_definition"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from src.store.pg_pool import get_conn

SANDBOX_TOOLS = [
    {
        "id": 3000000000000101,
        "api_key": "terminal",
        "name": "远程终端",
        "description": "在远程沙盒环境中执行 Shell 命令，支持所有标准 Linux 命令，工作目录和环境变量跨命令保持",
        "category": "sandbox",
        "read_only_flg": 0,
        "destructive_flg": 0,
        "sort_num": 100,
    },
    {
        "id": 3000000000000102,
        "api_key": "execute_code",
        "name": "代码执行",
        "description": "在远程沙盒中执行代码片段，支持 Python、JavaScript、Bash、Ruby、Go",
        "category": "sandbox",
        "read_only_flg": 0,
        "destructive_flg": 0,
        "sort_num": 110,
    },
    {
        "id": 3000000000000103,
        "api_key": "read_file",
        "name": "读取文件",
        "description": "读取远程沙盒中的文件内容，支持按行范围读取大文件",
        "category": "sandbox",
        "read_only_flg": 1,
        "destructive_flg": 0,
        "sort_num": 120,
    },
    {
        "id": 3000000000000104,
        "api_key": "write_file",
        "name": "写入文件",
        "description": "在远程沙盒中创建或覆盖文件，自动创建父目录",
        "category": "sandbox",
        "read_only_flg": 0,
        "destructive_flg": 0,
        "sort_num": 130,
    },
    {
        "id": 3000000000000105,
        "api_key": "search_files",
        "name": "搜索文件",
        "description": "在远程沙盒中递归搜索文件内容，支持正则表达式和文件名过滤",
        "category": "sandbox",
        "read_only_flg": 1,
        "destructive_flg": 0,
        "sort_num": 140,
    },
]


def main():
    print("开始插入沙盒执行工具...")

    now = 1748131200000  # 2025-05-25

    with get_conn() as conn:
        cur = conn.cursor()

        for t in SANDBOX_TOOLS:
            cur.execute("""
                INSERT INTO ai_tool_definition
                (id, api_key, tenant_id, name, description, input_schema, prompt,
                 category, tags, icon, read_only_flg, destructive_flg,
                 enabled_flg, system_flg, sort_num, ext_info,
                 delete_flg, created_at, created_by, updated_at, updated_by)
                VALUES (%s, %s, 0, %s, %s, '{}', '',
                        %s, '[]', '', %s, %s,
                        1, 1, %s, '{}',
                        0, %s, 0, %s, 0)
                ON CONFLICT (tenant_id, api_key) WHERE delete_flg = 0 DO NOTHING
            """, (
                t["id"], t["api_key"], t["name"], t["description"],
                t["category"], t["read_only_flg"], t["destructive_flg"],
                t["sort_num"], now, now,
            ))

        conn.commit()

    # 验证
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT api_key, name, category, enabled_flg
            FROM ai_tool_definition
            WHERE category = 'sandbox' AND delete_flg = 0
            ORDER BY sort_num
        """)
        rows = cur.fetchall()
        print(f"\n✅ 完成！sandbox 类别共 {len(rows)} 个工具：")
        for r in rows:
            status = "🟢" if r[3] else "⚪"
            print(f"   {status} {r[0]:15s} {r[1]} [{r[2]}]")


if __name__ == "__main__":
    main()
