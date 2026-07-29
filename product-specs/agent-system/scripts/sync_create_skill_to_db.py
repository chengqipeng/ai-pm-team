"""将 create_skill 的 SKILL.md 完整内容同步到数据库

运行方式:
    python scripts/sync_create_skill_to_db.py

功能:
    1. 读取 skills/definitions/create_skill/SKILL.md
    2. 解析 YAML frontmatter + Markdown body
    3. 写入 ai_skill + ai_skill_definition 表（upsert）
    4. 标记 system_flg=1（只读，前端不可编辑）

注意:
    - 数据库是运行时唯一数据源，SKILL.md 仅作为开发态版本管理
    - 每次修改 SKILL.md 后需要运行此脚本同步到数据库
    - 运行时 SkillRegistry.load_from_db() 从数据库加载，不读取文件
"""
from __future__ import annotations

import json
import os
import sys
import time
import yaml

# 确保 src 可 import
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def parse_skill_md(file_path: str) -> dict:
    """解析 SKILL.md: YAML frontmatter + Markdown body"""
    with open(file_path, "r", encoding="utf-8") as f:
        content = f.read()

    if not content.startswith("---"):
        raise ValueError("SKILL.md must start with ---")

    parts = content.split("---", 2)
    if len(parts) < 3:
        raise ValueError("SKILL.md frontmatter not closed")

    fm_text = parts[1].strip()
    body = parts[2].strip()

    fm = yaml.safe_load(fm_text) or {}

    return {
        "name": fm.get("name", ""),
        "description": fm.get("description", ""),
        "when_to_use": fm.get("when_to_use", ""),
        "context": fm.get("context", "inline"),
        "agent": fm.get("agent", ""),
        "model": fm.get("model", ""),
        "allowed_tools": fm.get("allowed-tools", fm.get("allowed_tools", [])),
        "arguments": fm.get("arguments", []),
        "prompt": body,
    }


def sync_to_db(skill_data: dict) -> None:
    """将解析后的 Skill 数据写入数据库"""
    from src.store.pg_pool import get_conn

    api_key = skill_data["name"]
    now = int(time.time() * 1000)

    allowed_tools_json = json.dumps(skill_data["allowed_tools"], ensure_ascii=False)
    arguments_json = json.dumps(skill_data["arguments"], ensure_ascii=False)

    with get_conn() as conn:
        cur = conn.cursor()

        # ═══ 1. ai_skill 主记录 ═══
        cur.execute("""
            INSERT INTO ai_skill (
                id, api_key, tenant_id,
                name, description, owner, category, tags, icon, sort_num,
                current_version, enabled_flg, system_flg,
                exec_count, success_count, avg_duration_ms,
                ext_info,
                delete_flg, created_at, created_by, updated_at, updated_by
            ) VALUES (
                900000000000001, %s, 0,
                %s, %s, 'AI-Platform', 'automation',
                '["skill","create","automation"]', '🛠️', 1,
                '1.0.0', 1, 1,
                0, 0, 0,
                '{}',
                0, %s, 0, %s, 0
            )
            ON CONFLICT (tenant_id, api_key) WHERE delete_flg = 0
            DO UPDATE SET
                name = EXCLUDED.name,
                description = EXCLUDED.description,
                system_flg = 1,
                updated_at = EXCLUDED.updated_at
        """, (
            api_key,
            '创建技能',
            skill_data["description"],
            now, now,
        ))

        # ═══ 2. ai_skill_definition 版本内容 ═══
        cur.execute("""
            INSERT INTO ai_skill_definition (
                id, skill_api_key, tenant_id, version,
                name, description,
                when_to_use, category, context, agent, model,
                allowed_tools, arguments, prompt,
                requires_confirmation, max_tool_calls, timeout_ms,
                risk_level,
                output_mode, post_output_behavior,
                published_by,
                delete_flg, created_at, created_by, updated_at, updated_by
            ) VALUES (
                900000000000101, %s, 0, '1.0.0',
                %s, %s,
                %s, 'automation', %s, %s, %s,
                %s, %s, %s,
                0, 20, 120000,
                'mutating',
                'text', 'silent',
                0,
                0, %s, 0, %s, 0
            )
            ON CONFLICT (tenant_id, skill_api_key, version) WHERE delete_flg = 0
            DO UPDATE SET
                name = EXCLUDED.name,
                description = EXCLUDED.description,
                when_to_use = EXCLUDED.when_to_use,
                context = EXCLUDED.context,
                allowed_tools = EXCLUDED.allowed_tools,
                arguments = EXCLUDED.arguments,
                prompt = EXCLUDED.prompt,
                max_tool_calls = EXCLUDED.max_tool_calls,
                timeout_ms = EXCLUDED.timeout_ms,
                updated_at = EXCLUDED.updated_at
        """, (
            api_key,
            '创建技能',
            skill_data["description"],
            skill_data["when_to_use"],
            skill_data["context"],
            skill_data["agent"] or "",
            skill_data["model"] or "",
            allowed_tools_json,
            arguments_json,
            skill_data["prompt"],
            now, now,
        ))

        conn.commit()

    print(f"✅ create_skill 已同步到数据库")
    print(f"   - api_key: {api_key}")
    print(f"   - prompt 长度: {len(skill_data['prompt'])} 字符")
    print(f"   - allowed_tools: {skill_data['allowed_tools']}")
    print(f"   - system_flg: 1 (只读)")


def main():
    # 定位 SKILL.md 文件
    script_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(script_dir)
    skill_md_path = os.path.join(
        project_root, "skills", "definitions", "create_skill", "SKILL.md"
    )

    if not os.path.exists(skill_md_path):
        print(f"❌ 文件不存在: {skill_md_path}")
        sys.exit(1)

    print(f"📄 读取: {skill_md_path}")
    skill_data = parse_skill_md(skill_md_path)

    print(f"📝 解析完成:")
    print(f"   - name: {skill_data['name']}")
    print(f"   - description: {skill_data['description'][:50]}...")
    print(f"   - prompt: {len(skill_data['prompt'])} 字符")
    print(f"   - allowed_tools: {skill_data['allowed_tools']}")
    print(f"   - arguments: {skill_data['arguments']}")

    print(f"\n🔄 写入数据库...")
    sync_to_db(skill_data)


if __name__ == "__main__":
    main()
