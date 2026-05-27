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
        """创建技能"""
        definition = input_data.get("skill_definition")
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

        return ToolResult(
            content=f"✅ 技能创建成功！\n"
                    f"- api_key: {definition['api_key']}\n"
                    f"- 名称: {definition['name']}\n"
                    f"- 分类: {definition.get('category', 'custom')}\n"
                    f"- 工具: {', '.join(allowed_tools)}\n"
                    f"- 参数: {', '.join(arguments)}\n"
                    f"技能已立即生效，可以通过对话触发使用。"
        )

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
        from src.store.skill_dao import SkillDefinitionDAO

        rows = SkillDefinitionDAO.list_all(tenant_id=0, include_platform=True)
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
