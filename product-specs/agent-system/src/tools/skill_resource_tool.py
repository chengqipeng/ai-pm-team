"""read_skill_resource 工具 — 从 ai_skill_resource 表读取 Skill 关联的知识文件

供 fork 模式的子 Agent 在运行时按需加载知识文件（行业包、策略库、竞争剧本等）。
对应 Skill prompt 中的 `read_skill_resource(skill_name="...", resource_name="...")` 调用。
"""
from __future__ import annotations

import logging
from src.tools.base import Tool
from src.core.dtypes import ToolResult

logger = logging.getLogger(__name__)


class ReadSkillResourceTool(Tool):
    """读取 Skill 关联的知识资源文件"""

    def __init__(self, tenant_id: int = 0):
        self._tenant_id = tenant_id

    @property
    def name(self) -> str:
        return "read_skill_resource"

    def input_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "skill_name": {
                    "type": "string",
                    "description": "技能标识（api_key），如 accountInsight、account-insight",
                },
                "resource_name": {
                    "type": "string",
                    "description": "资源文件路径，如 knowledge/industries/_index.md",
                },
            },
            "required": ["skill_name", "resource_name"],
        }

    async def call(self, input_data: dict, context=None, on_progress=None) -> ToolResult:
        skill_name = input_data.get("skill_name", "").strip()
        resource_name = input_data.get("resource_name", "").strip()

        if not skill_name:
            return ToolResult(content="skill_name 不能为空", is_error=True)
        if not resource_name:
            return ToolResult(content="resource_name 不能为空", is_error=True)

        try:
            from src.store.pg_pool import get_conn

            with get_conn() as conn:
                cur = conn.cursor()

                # 尝试精确匹配 skill_api_key
                cur.execute("""
                    SELECT content, content_type, description
                    FROM ai_skill_resource
                    WHERE skill_api_key = %s AND path = %s AND node_type = 'file'
                          AND tenant_id = %s AND delete_flg = 0 AND enabled_flg = 1
                """, (skill_name, resource_name, self._tenant_id))
                row = cur.fetchone()

                # 如果没找到，尝试连字符/下划线互换
                if row is None:
                    alt_name = skill_name.replace('-', '_') if '-' in skill_name else skill_name.replace('_', '-')
                    cur.execute("""
                        SELECT content, content_type, description
                        FROM ai_skill_resource
                        WHERE skill_api_key = %s AND path = %s AND node_type = 'file'
                              AND tenant_id = %s AND delete_flg = 0 AND enabled_flg = 1
                    """, (alt_name, resource_name, self._tenant_id))
                    row = cur.fetchone()

                # 如果还没找到，尝试 camelCase → kebab-case 或 kebab-case → camelCase
                if row is None:
                    import re
                    if any(c.isupper() for c in skill_name):
                        # camelCase → kebab-case
                        alt2 = re.sub(r'([a-z])([A-Z])', r'\1-\2', skill_name).lower()
                    else:
                        # kebab-case → camelCase
                        parts = skill_name.split('-')
                        alt2 = parts[0] + ''.join(p.capitalize() for p in parts[1:]) if len(parts) > 1 else skill_name
                    if alt2 != skill_name:
                        cur.execute("""
                            SELECT content, content_type, description
                            FROM ai_skill_resource
                            WHERE skill_api_key = %s AND path = %s AND node_type = 'file'
                                  AND tenant_id = %s AND delete_flg = 0 AND enabled_flg = 1
                        """, (alt2, resource_name, self._tenant_id))
                        row = cur.fetchone()

            if row is None:
                # 列出该 skill 下可用的资源文件
                available = self._list_available(skill_name)
                hint = f"未找到资源文件: {resource_name}"
                if available:
                    hint += f"\n\n可用的资源文件:\n" + "\n".join(f"  - {p}" for p in available[:20])
                return ToolResult(content=hint, is_error=True)

            content, content_type, description = row
            if not content:
                return ToolResult(content=f"资源文件 {resource_name} 内容为空", is_error=True)

            # 返回文件内容（带元信息头）
            header = f"# 📄 {resource_name}\n"
            if description:
                header += f"> {description}\n"
            header += "\n"

            return ToolResult(content=header + content)

        except Exception as e:
            logger.warning("read_skill_resource failed: skill=%s path=%s err=%s", skill_name, resource_name, e)
            return ToolResult(content=f"读取资源文件失败: {e}", is_error=True)

    def _list_available(self, skill_name: str) -> list[str]:
        """列出该 skill 下所有可用的文件路径"""
        try:
            from src.store.pg_pool import get_conn
            import re

            # 尝试多种名称格式
            names = [skill_name]
            alt = skill_name.replace('-', '_') if '-' in skill_name else skill_name.replace('_', '-')
            if alt != skill_name:
                names.append(alt)
            kebab = re.sub(r'([a-z])([A-Z])', r'\1-\2', skill_name).lower()
            if kebab != skill_name and kebab not in names:
                names.append(kebab)

            with get_conn() as conn:
                cur = conn.cursor()
                placeholders = ','.join(['%s'] * len(names))
                cur.execute(f"""
                    SELECT path FROM ai_skill_resource
                    WHERE skill_api_key IN ({placeholders}) AND node_type = 'file'
                          AND tenant_id = %s AND delete_flg = 0 AND enabled_flg = 1
                    ORDER BY path
                """, (*names, self._tenant_id))
                return [r[0] for r in cur.fetchall()]
        except Exception:
            return []

    def prompt(self) -> str:
        return (
            "读取 Skill 关联的知识资源文件（行业知识包、策略库、竞争剧本等）。\n"
            "何时使用：当 Skill prompt 中指示你加载知识文件时调用。\n"
            "参数说明：\n"
            "  - skill_name（必填）：技能标识，如 accountInsight 或 account-insight\n"
            "  - resource_name（必填）：资源文件路径，如 knowledge/industries/_index.md\n"
            "典型用法：\n"
            "  · 加载行业索引 → read_skill_resource(skill_name='account-insight', resource_name='knowledge/industries/_index.md')\n"
            "  · 加载策略库 → read_skill_resource(skill_name='account-insight', resource_name='knowledge/analysis-strategies/signal-patterns.md')\n"
            "注意：按需加载，不要一次性加载所有文件"
        )

    def is_read_only(self, input_data) -> bool:
        return True
