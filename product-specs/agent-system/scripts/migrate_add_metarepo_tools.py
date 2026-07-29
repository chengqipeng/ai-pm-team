"""迁移脚本：向 ai_tool_definition 表补全所有代码中注册但 DB 缺失的工具

执行方式：
    cd product-specs/agent-system
    python3 scripts/migrate_add_metarepo_tools.py

前置条件：
    - ai_tool_definition 表已存在（由 run_migrate_tools.py 创建）
    - .env 中配置了数据库连接

修复问题：
    ToolRegistry.register() 有数据库白名单校验机制，工具必须在 ai_tool_definition 表中
    存在且 enabled_flg=1 才能注册成功。以下工具在代码中有完整实现，但 DB 中缺少记录：
    - browse_metamodel / query_metadata（metarepo 元模型浏览工具）
    - manage_skill（对话式技能管理工具）
    - ask_clarification / manage_memory / memory_read（CRM 交互 & 记忆工具）
    导致 AgentFactory 校验 Skill.allowed_tools 时抛出 SkillActivationError。
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from src.store.pg_pool import get_conn

TOOLS = [
    # ── Metarepo 工具 ──
    {
        "api_key": "browse_metamodel",
        "name": "浏览元模型",
        "description": "浏览元模型层结构（元模型注册信息、字段定义、物理列映射、枚举取值、元模型关联）",
        "category": "metarepo",
        "read_only_flg": 1,
        "destructive_flg": 0,
        "sort_num": 100,
    },
    {
        "api_key": "query_metadata",
        "name": "查询元数据实例",
        "description": "查询元数据实例层（业务对象、字段、选项值、关联关系、校验规则、业务类型）",
        "category": "metarepo",
        "read_only_flg": 1,
        "destructive_flg": 0,
        "sort_num": 110,
    },
    # ── 技能管理工具 ──
    {
        "api_key": "manage_skill",
        "name": "管理技能定义",
        "description": "通过对话管理技能定义（创建/更新/删除/列表），供 create_skill 技能调用",
        "category": "skill",
        "read_only_flg": 0,
        "destructive_flg": 0,
        "sort_num": 120,
    },
    # ── 交互 & 记忆工具 ──
    {
        "api_key": "ask_clarification",
        "name": "向用户澄清追问",
        "description": "信息不足或有歧义时中断执行并追问用户，获取缺失的关键信息",
        "category": "interaction",
        "read_only_flg": 1,
        "destructive_flg": 0,
        "sort_num": 50,
    },
    {
        "api_key": "manage_memory",
        "name": "管理记忆",
        "description": "管理 Agent 的对话记忆（查看、搜索、删除、清空），仅在用户主动要求时使用",
        "category": "memory",
        "read_only_flg": 0,
        "destructive_flg": 0,
        "sort_num": 60,
    },
    {
        "api_key": "memory_read",
        "name": "读取记忆详情",
        "description": "按需读取记忆的 L1 概览或 L2 完整内容，当 L0 摘要不够回答问题时使用",
        "category": "memory",
        "read_only_flg": 1,
        "destructive_flg": 0,
        "sort_num": 70,
    },
]


def _get_tool_schemas() -> dict[str, tuple[str, str]]:
    """从 Python 代码中提取工具的 input_schema 和 prompt，确保 DB 与代码一致。

    Returns:
        {api_key: (input_schema_json, prompt_text)}
    """
    import json
    from src.tools.metarepo_backend import MetarepoSimulatedBackend
    from src.tools.metarepo_tools import BrowseMetamodelTool, QueryMetadataTool
    from src.tools.manage_skill_tool import ManageSkillTool

    backend = MetarepoSimulatedBackend()
    tool_instances = [
        BrowseMetamodelTool(backend),
        QueryMetadataTool(backend),
        ManageSkillTool(),
    ]

    schemas: dict[str, tuple[str, str]] = {}
    for t in tool_instances:
        schema_json = json.dumps(t.input_schema(), ensure_ascii=False)
        prompt_text = t.prompt() if hasattr(t, "prompt") and callable(t.prompt) else ""
        schemas[t.name] = (schema_json, prompt_text)
    return schemas


def main():
    import json

    print("开始新增 metarepo & manage_skill 工具定义...")

    # 从代码中提取 input_schema + prompt
    tool_schemas = _get_tool_schemas()

    with get_conn() as conn:
        cur = conn.cursor()

        now = int(time.time() * 1000)

        # 获取当前最大 ID，避免冲突
        cur.execute("SELECT COALESCE(MAX(id), 3000000000000000) FROM ai_tool_definition")
        max_id = cur.fetchone()[0]

        for i, t in enumerate(TOOLS, start=1):
            tool_id = max_id + i
            schema_json, prompt_text = tool_schemas.get(t["api_key"], ("{}", ""))
            cur.execute("""
                INSERT INTO ai_tool_definition
                (id, api_key, tenant_id, name, description, input_schema, prompt,
                 category, tags, icon, read_only_flg, destructive_flg,
                 enabled_flg, system_flg, sort_num, ext_info,
                 delete_flg, created_at, created_by, updated_at, updated_by)
                VALUES (%s, %s, 0, %s, %s, %s, %s,
                        %s, '[]', '', %s, %s,
                        1, 1, %s, '{}',
                        0, %s, 0, %s, 0)
                ON CONFLICT (tenant_id, api_key) WHERE delete_flg = 0
                DO UPDATE SET input_schema = EXCLUDED.input_schema,
                              prompt = EXCLUDED.prompt,
                              updated_at = EXCLUDED.updated_at
            """, (
                tool_id, t["api_key"], t["name"], t["description"],
                schema_json, prompt_text,
                t["category"], t["read_only_flg"], t["destructive_flg"],
                t["sort_num"], now, now,
            ))
            print(f"  ✓ {t['api_key']} ({t['name']})")

        conn.commit()

    # 验证
    with get_conn() as conn:
        cur = conn.cursor()
        api_keys = [t["api_key"] for t in TOOLS]
        placeholders = ",".join(["%s"] * len(api_keys))
        cur.execute(f"""
            SELECT api_key, name, category, enabled_flg, input_schema
            FROM ai_tool_definition
            WHERE api_key IN ({placeholders})
              AND delete_flg = 0
        """, api_keys)
        rows = cur.fetchall()
        print(f"\n✅ 迁移完成！验证结果（{len(rows)} 条）：")
        for r in rows:
            status = "启用" if r[3] == 1 else "禁用"
            schema = json.loads(r[4]) if r[4] else {}
            param_count = len(schema.get("properties", {}))
            print(f"   {r[0]:20s} | {r[1]:10s} | {r[2]:10s} | {status} | {param_count} 个参数")

    if len(rows) < len(TOOLS):
        print(f"\n⚠️  部分工具可能已存在（ON CONFLICT DO NOTHING），请手动确认。")
    else:
        print("\n🎉 所有工具已就绪，重启服务后 Agent 构建应恢复正常。")


if __name__ == "__main__":
    main()
