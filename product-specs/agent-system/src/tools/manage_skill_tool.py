"""ManageSkillTool — 通过对话管理技能定义（创建/更新/删除/列表）

供 create_skill 等 Skill 调用，实现对话式技能管理。
"""
from __future__ import annotations

import json
import logging
from typing import Any, Callable

from src.tools.base import Tool
from src.core.dtypes import ToolResult

logger = logging.getLogger(__name__)


class ManageSkillTool(Tool):
    """管理技能定义 — 创建/更新/删除/列表"""

    def __init__(self, skill_service=None):
        self._skill_service = skill_service

    @classmethod
    def create(cls, tenant_id: int = 0, db_row=None) -> "ManageSkillTool":
        """自包含初始化 — 无外部依赖"""
        return cls()

    @property
    def name(self) -> str:
        return "manage_skill"

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["create", "update", "delete", "list"],
                    "description": "操作类型: create=创建技能, update=更新技能, delete=删除技能, list=列出现有技能",
                },
                "skill_definition": {
                    "type": "object",
                    "description": "技能定义（create/update 时必填）",
                    "properties": {
                        "api_key": {"type": "string", "description": "技能唯一标识，snake_case 格式"},
                        "name": {"type": "string", "description": "技能中文名称"},
                        "description": {"type": "string", "description": "一句话描述技能用途"},
                        "when_to_use": {"type": "string", "description": "触发关键词，用|分隔"},
                        "category": {"type": "string", "description": "分类: crm/analysis/automation/custom"},
                        "arguments": {"type": "array", "items": {"type": "string"}, "description": "参数名列表"},
                        "argument_descriptions": {"type": "object", "description": "参数描述 {参数名: 描述}"},
                        "allowed_tools": {"type": "array", "items": {"type": "string"}, "description": "允许使用的工具列表"},
                        "max_tool_calls": {"type": "integer", "description": "最大工具调用次数"},
                        "timeout_ms": {"type": "integer", "description": "超时毫秒数"},
                        "prompt": {"type": "string", "description": "技能执行 Prompt（Markdown 格式，用 {参数名} 作占位符）"},
                        "ext_info": {"type": "object", "description": "扩展配置（如 script_execution、preload_resources）"},
                        "resources": {
                            "type": "array",
                            "description": "资源文件列表（scripts/references/knowledge 目录下的文件）",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "path": {"type": "string", "description": "文件路径，如 scripts/main.py 或 scripts/requirements.txt"},
                                    "content": {"type": "string", "description": "文件内容"},
                                    "content_type": {"type": "string", "description": "文件类型: py/txt/md/json/yaml"},
                                    "description": {"type": "string", "description": "文件用途说明"},
                                },
                                "required": ["path", "content"],
                            },
                        },
                    },
                },
                "api_key": {
                    "type": "string",
                    "description": "技能 api_key（update/delete 时必填）",
                },
            },
            "required": ["action"],
        }

    async def call(
        self,
        input_data: dict,
        context: Any,
        on_progress: Callable[[Any], None] | None = None,
    ) -> ToolResult:
        action = input_data.get("action", "")

        try:
            if action == "create":
                return await self._handle_create(input_data)
            elif action == "update":
                return await self._handle_update(input_data)
            elif action == "delete":
                return await self._handle_delete(input_data)
            elif action == "list":
                return await self._handle_list()
            else:
                return ToolResult(content=f"未知操作: {action}", is_error=True)
        except Exception as e:
            logger.exception("ManageSkillTool 执行失败: %s", e)
            return ToolResult(content=f"操作失败: {str(e)}", is_error=True)

    async def _handle_create(self, input_data: dict) -> ToolResult:
        """创建技能

        支持两种调用方式：
        1. 直接传入 skill_definition（标准方式）
        2. 从 ask_user resume 值中提取（对话式创建，用户确认后）
           resume 值格式: {"action": "confirm", "value": {...skill_definition...}}
        """
        definition = input_data.get("skill_definition")

        # 兼容：从 resume value 中提取定义（用户可能修改过）
        if not definition and input_data.get("action") == "create":
            value = input_data.get("value")
            if isinstance(value, dict) and "api_key" in value:
                definition = value

        if not definition:
            return ToolResult(content="创建技能需要提供 skill_definition", is_error=True)

        # 校验必填字段
        required_fields = ["api_key", "name", "description", "prompt"]
        missing = [f for f in required_fields if not definition.get(f)]
        if missing:
            return ToolResult(content=f"缺少必填字段: {', '.join(missing)}", is_error=True)

        # 校验 allowed_tools 是否在数据库中存在
        allowed_tools = definition.get("allowed_tools", [])
        if allowed_tools:
            validation_error = self._validate_tools(allowed_tools)
            if validation_error:
                return ToolResult(content=validation_error, is_error=True)

        # 校验 arguments 占位符（系统变量除外，脚本执行模式放宽）
        arguments = definition.get("arguments", [])
        prompt = definition.get("prompt", "")
        _SYSTEM_VARS = {"SKILL_DIR", "SKILL_NAME"}
        has_skill_dir = "${SKILL_DIR}" in prompt
        for arg in arguments:
            if arg in _SYSTEM_VARS:
                continue
            if has_skill_dir:
                continue
            if f"{{{arg}}}" not in prompt:
                return ToolResult(
                    content=f"参数 '{arg}' 在 prompt 中未找到对应的 {{{arg}}} 占位符",
                    is_error=True,
                )

        # 调用 SkillService 创建
        from src.skills.service import SkillService, SkillCreateRequest, SkillServiceError
        from src.api.skill_api import get_skill_service

        service = get_skill_service()
        req = SkillCreateRequest(
            api_key=definition["api_key"],
            name=definition["name"],
            description=definition["description"],
            prompt=definition["prompt"],
            when_to_use=definition.get("when_to_use", ""),
            category=definition.get("category", "custom"),
            arguments=arguments,
            allowed_tools=allowed_tools,
            max_tool_calls=definition.get("max_tool_calls", 15),
            timeout_ms=definition.get("timeout_ms", 45000),
        )

        try:
            result = service.create(req, tenant_id=0)
        except SkillServiceError as e:
            return ToolResult(content=f"创建失败: {str(e)}", is_error=True)

        # 保存 argument_descriptions
        arg_descs = definition.get("argument_descriptions", {})
        if arg_descs:
            from src.api.skill_api import _save_argument_descriptions
            _save_argument_descriptions(0, definition["api_key"], arg_descs)

        # 保存 ext_info（script_execution、preload_resources 等扩展配置）
        ext_info = definition.get("ext_info")
        if ext_info:
            self._save_ext_info(definition["api_key"], ext_info)

        # 创建资源文件（scripts/、references/、knowledge/ 目录下的文件）
        resources = definition.get("resources", [])
        resource_errors = []
        if resources:
            resource_errors = self._create_resources(definition["api_key"], resources)

        result_msg = (
            f"✅ 技能创建成功！\n"
            f"- api_key: {definition['api_key']}\n"
            f"- 名称: {definition['name']}\n"
            f"- 分类: {definition.get('category', 'custom')}\n"
            f"- 工具: {', '.join(allowed_tools)}\n"
            f"- 参数: {', '.join(arguments)}\n"
        )
        if resources:
            result_msg += f"- 资源文件: {len(resources)} 个\n"
        if resource_errors:
            result_msg += f"- ⚠️ 部分资源创建失败: {'; '.join(resource_errors)}\n"
        result_msg += "技能已立即生效，可以通过对话触发使用。"

        return ToolResult(content=result_msg)

    async def _handle_update(self, input_data: dict) -> ToolResult:
        """更新技能"""
        api_key = input_data.get("api_key") or input_data.get("skill_definition", {}).get("api_key")
        if not api_key:
            return ToolResult(content="更新技能需要提供 api_key", is_error=True)

        definition = input_data.get("skill_definition", {})
        if not definition:
            return ToolResult(content="更新技能需要提供 skill_definition", is_error=True)

        from src.skills.service import SkillService, SkillUpdateRequest, SkillServiceError
        from src.api.skill_api import get_skill_service

        service = get_skill_service()
        req = SkillUpdateRequest(
            name=definition.get("name"),
            description=definition.get("description"),
            prompt=definition.get("prompt"),
            when_to_use=definition.get("when_to_use"),
            category=definition.get("category"),
            arguments=definition.get("arguments"),
            allowed_tools=definition.get("allowed_tools"),
            max_tool_calls=definition.get("max_tool_calls"),
            timeout_ms=definition.get("timeout_ms"),
        )

        try:
            result = service.update(api_key, req, tenant_id=0)
        except SkillServiceError as e:
            return ToolResult(content=f"更新失败: {str(e)}", is_error=True)

        return ToolResult(content=f"✅ 技能 '{api_key}' 更新成功")

    async def _handle_delete(self, input_data: dict) -> ToolResult:
        """删除技能"""
        api_key = input_data.get("api_key")
        if not api_key:
            return ToolResult(content="删除技能需要提供 api_key", is_error=True)

        from src.skills.service import SkillServiceError
        from src.api.skill_api import get_skill_service

        service = get_skill_service()
        try:
            service.delete(api_key, tenant_id=0)
        except SkillServiceError as e:
            return ToolResult(content=f"删除失败: {str(e)}", is_error=True)

        return ToolResult(content=f"✅ 技能 '{api_key}' 已删除")

    async def _handle_list(self) -> ToolResult:
        """列出现有技能"""
        from src.store.skill_dao import SkillDAO

        rows = SkillDAO.list_all(tenant_id=0, include_platform=True)
        if not rows:
            return ToolResult(content="当前没有已注册的技能")

        lines = ["当前已注册的技能：\n"]
        for r in rows:
            enabled = "🟢" if getattr(r, "enabled_flg", 1) else "⚪"
            lines.append(f"{enabled} {r.api_key} — {r.name}")
        return ToolResult(content="\n".join(lines))

    def _validate_tools(self, tool_names: list[str]) -> str | None:
        """校验 allowed_tools 中的工具是否在数据库中存在且启用

        Raises:
            如果数据库不可用，返回错误信息（不再静默跳过）
        """
        try:
            from src.store.tool_dao import ToolDefinitionDAO
            db_tools = ToolDefinitionDAO.list_all(tenant_id=0, enabled_only=True)
            valid_names = {t.api_key for t in db_tools}
            invalid = [n for n in tool_names if n not in valid_names]
            if invalid:
                return f"以下工具不存在或未启用: {', '.join(invalid)}。可用工具: {', '.join(sorted(valid_names))}"
        except Exception as e:
            return f"工具校验失败（数据库不可用）: {e}。无法确认工具 {tool_names} 是否有效，请检查数据库连接后重试"
        return None

    def _save_ext_info(self, api_key: str, ext_info: dict) -> None:
        """保存 ext_info 到 ai_skill 主表"""
        import time
        try:
            from src.store.pg_pool import get_conn
            now = int(time.time() * 1000)
            with get_conn() as conn:
                cur = conn.cursor()
                cur.execute("""
                    UPDATE ai_skill SET ext_info = %s, updated_at = %s
                    WHERE api_key = %s AND tenant_id = 0 AND delete_flg = 0
                """, (json.dumps(ext_info, ensure_ascii=False), now, api_key))
        except Exception as e:
            logger.warning("保存 ext_info 失败: %s", e)

    def _create_resources(self, api_key: str, resources: list[dict]) -> list[str]:
        """创建资源文件到 ai_skill_resource 表

        Args:
            api_key: 技能标识
            resources: 资源文件列表，每项含 path/content/content_type/description

        Returns:
            错误信息列表（空列表表示全部成功）
        """
        import time
        errors = []

        try:
            from src.store.pg_pool import get_conn
            from src.store.snowflake import next_id

            now = int(time.time() * 1000)

            # 获取技能当前版本
            with get_conn() as conn:
                cur = conn.cursor()
                cur.execute("""
                    SELECT current_version FROM ai_skill
                    WHERE api_key = %s AND tenant_id = 0 AND delete_flg = 0
                """, (api_key,))
                row = cur.fetchone()
                version = row[0] if row else "1.0.0"

            # 收集需要创建的目录（自动从文件路径推导）
            dirs_to_create: set[str] = set()
            for res in resources:
                path = res.get("path", "")
                parts = path.split("/")
                # 逐级收集目录路径
                for i in range(1, len(parts)):
                    dir_path = "/".join(parts[:i])
                    dirs_to_create.add(dir_path)

            # 按深度排序目录（确保父目录先创建）
            sorted_dirs = sorted(dirs_to_create, key=lambda p: p.count("/"))

            with get_conn() as conn:
                cur = conn.cursor()
                dir_id_map: dict[str, int] = {}  # path → id

                # 创建目录节点
                for dir_path in sorted_dirs:
                    dir_name = dir_path.split("/")[-1]
                    depth = dir_path.count("/")
                    parent_path = "/".join(dir_path.split("/")[:-1])
                    parent_id = dir_id_map.get(parent_path) if parent_path else None

                    # 检查是否已存在
                    cur.execute("""
                        SELECT id FROM ai_skill_resource
                        WHERE skill_api_key = %s AND path = %s AND version = %s
                              AND tenant_id = 0 AND delete_flg = 0
                    """, (api_key, dir_path, version))
                    existing = cur.fetchone()
                    if existing:
                        dir_id_map[dir_path] = existing[0]
                        continue

                    dir_id = next_id()
                    cur.execute("""
                        INSERT INTO ai_skill_resource (
                            id, tenant_id, skill_api_key, version, parent_id,
                            node_type, name, path, depth,
                            content, content_type, content_size, description, icon, sort_num,
                            enabled_flg, delete_flg, created_at, created_by, updated_at, updated_by
                        ) VALUES (
                            %s, 0, %s, %s, %s,
                            'dir', %s, %s, %s,
                            NULL, '', 0, '', '📁', 0,
                            1, 0, %s, 0, %s, 0
                        )
                    """, (dir_id, api_key, version, parent_id,
                          dir_name, dir_path, depth, now, now))
                    dir_id_map[dir_path] = dir_id

                # 创建文件节点
                for res in resources:
                    path = res.get("path", "")
                    content = res.get("content", "")
                    content_type = res.get("content_type", "")
                    description = res.get("description", "")

                    if not path:
                        errors.append("资源文件缺少 path")
                        continue

                    # 自动推断 content_type
                    if not content_type:
                        ext = path.rsplit(".", 1)[-1] if "." in path else "txt"
                        content_type = ext

                    file_name = path.split("/")[-1]
                    depth = path.count("/")
                    parent_path = "/".join(path.split("/")[:-1])
                    parent_id = dir_id_map.get(parent_path) if parent_path else None
                    content_size = len(content.encode("utf-8")) if content else 0

                    # 检查是否已存在
                    cur.execute("""
                        SELECT id FROM ai_skill_resource
                        WHERE skill_api_key = %s AND path = %s AND version = %s
                              AND tenant_id = 0 AND delete_flg = 0
                    """, (api_key, path, version))
                    if cur.fetchone():
                        # 已存在则更新内容
                        cur.execute("""
                            UPDATE ai_skill_resource
                            SET content = %s, content_size = %s, content_type = %s,
                                description = %s, updated_at = %s
                            WHERE skill_api_key = %s AND path = %s AND version = %s
                                  AND tenant_id = 0 AND delete_flg = 0
                        """, (content, content_size, content_type, description,
                              now, api_key, path, version))
                        continue

                    file_id = next_id()
                    cur.execute("""
                        INSERT INTO ai_skill_resource (
                            id, tenant_id, skill_api_key, version, parent_id,
                            node_type, name, path, depth,
                            content, content_type, content_size, description, icon, sort_num,
                            enabled_flg, delete_flg, created_at, created_by, updated_at, updated_by
                        ) VALUES (
                            %s, 0, %s, %s, %s,
                            'file', %s, %s, %s,
                            %s, %s, %s, %s, '', 0,
                            1, 0, %s, 0, %s, 0
                        )
                    """, (file_id, api_key, version, parent_id,
                          file_name, path, depth,
                          content, content_type, content_size, description,
                          now, now))

                conn.commit()

        except Exception as e:
            logger.exception("创建资源文件失败: %s", e)
            errors.append(f"资源文件写入失败: {str(e)}")

        return errors

    def prompt(self) -> str:
        return (
            "管理 Agent 技能定义（创建、更新、删除、列表）。\n"
            "何时使用：用户要求创建新技能、修改已有技能、删除技能、或查看技能列表时使用。\n"
            "参数说明：\n"
            "  - action: create/update/delete/list\n"
            "  - skill_definition: 技能定义对象（create/update 时必填）\n"
            "  - api_key: 技能标识（update/delete 时必填）\n"
        )

    def is_read_only(self, input_data: dict) -> bool:
        return input_data.get("action") == "list"
