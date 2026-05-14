"""执行工具表迁移：建表 + 插入预置工具定义"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from src.store.pg_pool import get_conn

DDL = """
CREATE TABLE IF NOT EXISTS ai_tool_definition (
    id              BIGINT PRIMARY KEY,
    api_key         VARCHAR(100) NOT NULL,
    tenant_id       BIGINT NOT NULL DEFAULT 0,
    name            VARCHAR(200) NOT NULL DEFAULT '',
    description     VARCHAR(1000) NOT NULL DEFAULT '',
    input_schema    TEXT NOT NULL DEFAULT '{}',
    prompt          TEXT NOT NULL DEFAULT '',
    category        VARCHAR(50) DEFAULT '',
    tags            TEXT DEFAULT '[]',
    icon            VARCHAR(100) DEFAULT '',
    read_only_flg   SMALLINT NOT NULL DEFAULT 1,
    destructive_flg SMALLINT NOT NULL DEFAULT 0,
    enabled_flg     SMALLINT NOT NULL DEFAULT 1,
    system_flg      SMALLINT NOT NULL DEFAULT 0,
    sort_num        INT NOT NULL DEFAULT 0,
    ext_info        TEXT DEFAULT '{}',
    delete_flg      SMALLINT NOT NULL DEFAULT 0,
    created_at      BIGINT NOT NULL,
    created_by      BIGINT NOT NULL DEFAULT 0,
    updated_at      BIGINT NOT NULL,
    updated_by      BIGINT NOT NULL DEFAULT 0
);

CREATE UNIQUE INDEX IF NOT EXISTS uk_tool_def_apikey
    ON ai_tool_definition(tenant_id, api_key) WHERE delete_flg = 0;
CREATE INDEX IF NOT EXISTS idx_tool_def_category
    ON ai_tool_definition(tenant_id, category) WHERE delete_flg = 0;
CREATE INDEX IF NOT EXISTS idx_tool_def_enabled
    ON ai_tool_definition(tenant_id, enabled_flg) WHERE delete_flg = 0;
"""

# 预置工具数据
TOOLS = [
    {
        "id": 3000000000000001,
        "api_key": "query_data",
        "name": "查询业务数据",
        "description": "查询 CRM 系统中的业务数据记录（客户、商机、联系人、活动、线索），支持条件筛选、分页、排序",
        "category": "data",
        "read_only_flg": 1,
        "destructive_flg": 0,
        "sort_num": 10,
    },
    {
        "id": 3000000000000002,
        "api_key": "modify_data",
        "name": "修改业务数据",
        "description": "修改 CRM 系统中的业务数据（创建、更新、删除记录），执行前需用户确认",
        "category": "data",
        "read_only_flg": 0,
        "destructive_flg": 1,
        "sort_num": 20,
    },
    {
        "id": 3000000000000003,
        "api_key": "analyze_data",
        "name": "数据聚合分析",
        "description": "对业务数据进行聚合统计分析（求和、计数、平均值、最大最小值 + 分组）",
        "category": "data",
        "read_only_flg": 1,
        "destructive_flg": 0,
        "sort_num": 30,
    },
    {
        "id": 3000000000000004,
        "api_key": "ask_user",
        "name": "向用户确认",
        "description": "向用户发起简单的是/否确认，用于数据修改前的操作确认",
        "category": "interaction",
        "read_only_flg": 1,
        "destructive_flg": 0,
        "sort_num": 40,
    },
    {
        "id": 3000000000000005,
        "api_key": "ask_clarification",
        "name": "向用户澄清追问",
        "description": "信息不足或有歧义时中断执行并追问用户，获取缺失的关键信息",
        "category": "interaction",
        "read_only_flg": 1,
        "destructive_flg": 0,
        "sort_num": 50,
    },
    {
        "id": 3000000000000006,
        "api_key": "manage_memory",
        "name": "管理记忆",
        "description": "管理 Agent 的对话记忆（查看、搜索、删除、清空），仅在用户主动要求时使用",
        "category": "memory",
        "read_only_flg": 0,
        "destructive_flg": 0,
        "sort_num": 60,
    },
    {
        "id": 3000000000000007,
        "api_key": "memory_read",
        "name": "读取记忆详情",
        "description": "按需读取记忆的 L1 概览或 L2 完整内容，当 L0 摘要不够回答问题时使用",
        "category": "memory",
        "read_only_flg": 1,
        "destructive_flg": 0,
        "sort_num": 70,
    },
    {
        "id": 3000000000000008,
        "api_key": "web_search",
        "name": "网络搜索",
        "description": "通过百度 AI 搜索获取实时信息，用于回答需要最新数据的问题",
        "category": "external",
        "read_only_flg": 1,
        "destructive_flg": 0,
        "sort_num": 80,
    },
]


def main():
    print("开始执行工具表迁移...")

    with get_conn() as conn:
        cur = conn.cursor()

        # 1. 建表
        print("  [1/2] 创建 ai_tool_definition 表...")
        cur.execute(DDL)

        # 2. 插入预置工具
        print("  [2/2] 插入预置工具数据...")
        now = 1746489600000
        for t in TOOLS:
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

    # 验证
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT api_key, name, category FROM ai_tool_definition WHERE delete_flg = 0 ORDER BY sort_num")
        rows = cur.fetchall()
        print(f"\n✅ 迁移完成！共 {len(rows)} 个工具：")
        for r in rows:
            print(f"   {r[0]:20s} {r[1]} [{r[2]}]")


if __name__ == "__main__":
    main()
