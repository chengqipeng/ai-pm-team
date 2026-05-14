"""迁移脚本：向 ai_tool_definition 表新增 knowledge_search 和 list_knowledge_bases 工具

执行方式：
    cd product-specs/agent-system
    python scripts/migrate_add_knowledge_tools.py

前置条件：
    - ai_tool_definition 表已存在（由 run_migrate_tools.py 创建）
    - .env 中配置了数据库连接
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from src.store.pg_pool import get_conn

TOOLS = [
    {
        "id": 3000000000000011,
        "api_key": "knowledge_search",
        "name": "知识库检索",
        "description": "检索 AI 知识库中的文档，支持自然语言查询、元数据过滤、多维度排序",
        "category": "knowledge",
        "read_only_flg": 1,
        "destructive_flg": 0,
        "sort_num": 90,
    },
    {
        "id": 3000000000000012,
        "api_key": "list_knowledge_bases",
        "name": "列出知识库",
        "description": "列出当前租户可用的知识库列表（含 ID、名称、描述、文档数量）",
        "category": "knowledge",
        "read_only_flg": 1,
        "destructive_flg": 0,
        "sort_num": 91,
    },
]


def main():
    print("开始新增知识库工具定义...")

    with get_conn() as conn:
        cur = conn.cursor()

        import time
        now = int(time.time())

        # 获取当前最大 ID，避免冲突
        cur.execute("SELECT COALESCE(MAX(id), 3000000000000000) FROM ai_tool_definition")
        max_id = cur.fetchone()[0]

        for i, t in enumerate(TOOLS, start=1):
            tool_id = max_id + i
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
                tool_id, t["api_key"], t["name"], t["description"],
                t["category"], t["read_only_flg"], t["destructive_flg"],
                t["sort_num"], now, now,
            ))
            print(f"  ✓ {t['api_key']} ({t['name']})")

        conn.commit()

    # 验证
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT api_key, name, category, enabled_flg
            FROM ai_tool_definition
            WHERE api_key IN ('knowledge_search', 'list_knowledge_bases')
              AND delete_flg = 0
        """)
        rows = cur.fetchall()
        print(f"\n✅ 迁移完成！验证结果（{len(rows)} 条）：")
        for r in rows:
            status = "启用" if r[3] == 1 else "禁用"
            print(f"   {r[0]:30s} | {r[1]:10s} | {r[2]:10s} | {status}")

    if len(rows) < 2:
        print("\n⚠️  部分工具可能已存在（ON CONFLICT DO NOTHING），请手动确认。")


if __name__ == "__main__":
    main()
