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
                    "enum": ["create", "update", "delete", "list",
                             "create_version", "list_versions", "switch_version", "diff_versions",
                             "list_change_logs"],
                    "description": (
                        "操作类型: create=创建技能, update=更新技能(当前版本), delete=删除技能, list=列出现有技能, "
                        "create_version=创建新版本(复制当前版本后修改), list_versions=列出版本历史, "
                        "switch_version=切换到指定版本, diff_versions=对比两个版本差异, "
                        "list_change_logs=查看技能变更日志"
                    ),
                },
                "skill_definition": {
                    "type": "object",
                    "description": "技能定义（create/update/create_version 时必填）",
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
                    "description": "技能 api_key（update/delete/版本操作时必填）",
                },
                "version": {
                    "type": "string",
                    "description": "版本号（semver 格式如 1.1.0）。create_version 时为新版本号，switch_version 时为目标版本号",
                },
                "changelog": {
                    "type": "string",
                    "description": "版本变更说明（create_version 时使用）",
                },
                "base_version": {
                    "type": "string",
                    "description": "基准版本号（diff_versions 时必填，旧版本）",
                },
                "target_version": {
                    "type": "string",
                    "description": "目标版本号（diff_versions 时必填，新版本）",
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
            elif action == "create_version":
                return await self._handle_create_version(input_data)
            elif action == "list_versions":
                return await self._handle_list_versions(input_data)
            elif action == "switch_version":
                return await self._handle_switch_version(input_data)
            elif action == "diff_versions":
                return await self._handle_diff_versions(input_data)
            elif action == "list_change_logs":
                return await self._handle_list_change_logs(input_data)
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

        # 兼容 arguments 的两种格式：
        # - list: ["purpose", "recipient"] — 标准格式
        # - dict: {"purpose": "描述", "recipient": "描述"} — LLM 偶尔生成的格式
        raw_arguments = definition.get("arguments", [])
        if isinstance(raw_arguments, dict):
            # dict 格式：拆分为 arguments (list) + argument_descriptions (dict)
            arguments = list(raw_arguments.keys())
            # 合并到 argument_descriptions（不覆盖已有的）
            existing_descs = definition.get("argument_descriptions", {})
            merged_descs = {**raw_arguments, **existing_descs}
            definition["arguments"] = arguments
            definition["argument_descriptions"] = merged_descs
            logger.info("arguments 从 dict 格式自动转换为 list: %s", arguments)
        elif isinstance(raw_arguments, list):
            arguments = raw_arguments
        else:
            arguments = []
            definition["arguments"] = arguments

        # 校验 arguments 占位符（系统变量除外，脚本执行模式放宽，纯生成型放宽）
        prompt = definition.get("prompt", "")
        _SYSTEM_VARS = {"SKILL_DIR", "SKILL_NAME"}
        has_skill_dir = "${SKILL_DIR}" in prompt
        # 纯生成型技能（无工具调用或仅 ask_user）对占位符校验完全跳过
        is_generation_skill = not allowed_tools or set(allowed_tools) <= {"ask_user"}
        if not is_generation_skill:
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
        """更新技能 — 禁止直接修改生效中的版本，必须通过 create_version 创建新版本"""
        api_key = input_data.get("api_key") or input_data.get("skill_definition", {}).get("api_key")
        if not api_key:
            return ToolResult(content="更新技能需要提供 api_key", is_error=True)

        # 系统预置技能不允许更新
        error = self._check_system_skill(api_key)
        if error:
            return error

        definition = input_data.get("skill_definition", {})
        if not definition:
            return ToolResult(content="更新技能需要提供 skill_definition", is_error=True)

        # 禁止直接修改生效中的版本 — 必须通过 create_version 创建新版本
        return ToolResult(
            content=(
                f"❌ 禁止直接修改技能 '{api_key}' 的生效版本。\n"
                f"为保证线上稳定性，不允许直接更新正在运行的版本。\n\n"
                f"请使用 create_version 创建新版本后更新：\n"
                f"  manage_skill(\n"
                f"    action=\"create_version\",\n"
                f"    api_key=\"{api_key}\",\n"
                f"    version=\"<新版本号，如 1.1.0>\",\n"
                f"    changelog=\"<变更说明>\",\n"
                f"    skill_definition={{...修改内容...}}\n"
                f"  )\n\n"
                f"新版本创建后会自动成为生效版本。如需回滚可使用 switch_version。"
            ),
            is_error=True,
        )

    async def _handle_delete(self, input_data: dict) -> ToolResult:
        """删除技能"""
        api_key = input_data.get("api_key")
        if not api_key:
            return ToolResult(content="删除技能需要提供 api_key", is_error=True)

        # 系统预置技能不允许删除
        error = self._check_system_skill(api_key)
        if error:
            return error

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

    # ═══════════════════════════════════════════════════════════
    # 版本管理操作
    # ═══════════════════════════════════════════════════════════

    async def _handle_create_version(self, input_data: dict) -> ToolResult:
        """创建新版本（复制当前版本，然后应用 skill_definition 中的修改）"""
        api_key = input_data.get("api_key")
        if not api_key:
            return ToolResult(content="create_version 需要提供 api_key", is_error=True)

        # 系统预置技能不允许创建新版本
        error = self._check_system_skill(api_key)
        if error:
            return error

        version = input_data.get("version")
        if not version:
            return ToolResult(content="create_version 需要提供 version（如 1.1.0）", is_error=True)

        changelog = input_data.get("changelog", "")

        from src.skills.version_service import SkillVersionService, CreateVersionRequest, SkillVersionError
        from src.api.skill_api import get_version_service
        from src.store.skill_dao import SkillDAO

        service = get_version_service()

        # 获取当前版本号（用于日志记录）
        skill = SkillDAO.get_by_api_key(0, api_key)
        from_version = skill.current_version if skill else "unknown"

        try:
            # 1. 创建新版本（复制当前版本的 definition + resource）
            result = service.create_version(
                api_key, CreateVersionRequest(version=version, changelog=changelog),
                tenant_id=0
            )
        except SkillVersionError as e:
            return ToolResult(content=f"创建版本失败: {str(e)}", is_error=True)

        # 2. 如果提供了 skill_definition，在新版本上应用修改
        definition = input_data.get("skill_definition")
        change_fields = []
        if definition:
            from src.skills.service import SkillUpdateRequest, SkillServiceError
            from src.api.skill_api import get_skill_service

            svc = get_skill_service()
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
                svc.update(api_key, req, tenant_id=0)
            except SkillServiceError as e:
                return ToolResult(
                    content=f"⚠️ 版本 {version} 已创建，但应用修改失败: {str(e)}",
                    is_error=True,
                )

            # 收集变更字段列表
            for field in ("name", "description", "prompt", "when_to_use", "category",
                          "arguments", "allowed_tools", "max_tool_calls", "timeout_ms"):
                if definition.get(field) is not None:
                    change_fields.append(field)

            # 保存 argument_descriptions
            arg_descs = definition.get("argument_descriptions", {})
            if arg_descs:
                from src.api.skill_api import _save_argument_descriptions
                _save_argument_descriptions(0, api_key, arg_descs)

            # 保存 ext_info
            ext_info = definition.get("ext_info")
            if ext_info:
                self._save_ext_info(api_key, ext_info)
                change_fields.append("ext_info")

            # 更新资源文件
            resources = definition.get("resources", [])
            resource_errors = []
            if resources:
                resource_errors = self._create_resources(api_key, resources)
                change_fields.append(f"resources({len(resources)}个文件)")

        # 3. 记录变更日志
        change_summary = f"修改字段: {', '.join(change_fields)}" if change_fields else "仅创建版本快照"
        self._record_change_log(
            skill_api_key=api_key,
            action="create_version",
            from_version=from_version,
            to_version=version,
            changelog=changelog,
            change_summary=change_summary,
            change_detail={"changed_fields": change_fields} if change_fields else None,
            trigger_source="chat",
        )

        result_msg = (
            f"✅ 技能 '{api_key}' 新版本 v{version} 创建成功\n"
            f"- 变更前版本: v{from_version}\n"
            f"- 变更说明: {changelog or '(无)'}\n"
        )
        if change_fields:
            result_msg += f"- 修改字段: {', '.join(change_fields)}\n"
        result_msg += f"- 当前生效版本: v{version}\n"
        result_msg += f"- 📋 变更已记录到日志，可通过 list_versions 查看历史"

        return ToolResult(content=result_msg)

    async def _handle_list_versions(self, input_data: dict) -> ToolResult:
        """列出技能的版本历史"""
        api_key = input_data.get("api_key")
        if not api_key:
            return ToolResult(content="list_versions 需要提供 api_key", is_error=True)

        from src.skills.version_service import SkillVersionService, SkillVersionError
        from src.api.skill_api import get_version_service

        service = get_version_service()

        try:
            versions = service.list_versions(api_key, tenant_id=0)
        except SkillVersionError as e:
            return ToolResult(content=f"查询版本失败: {str(e)}", is_error=True)

        if not versions:
            return ToolResult(content=f"技能 '{api_key}' 没有版本记录")

        lines = [f"技能 '{api_key}' 的版本历史：\n"]
        for v in versions:
            current = " ← 当前生效" if v["is_current"] else ""
            changelog = f" ({v['changelog']})" if v.get("changelog") else ""
            lines.append(f"  v{v['version']}{current}{changelog}")
        return ToolResult(content="\n".join(lines))

    async def _handle_switch_version(self, input_data: dict) -> ToolResult:
        """切换到指定版本"""
        api_key = input_data.get("api_key")
        if not api_key:
            return ToolResult(content="switch_version 需要提供 api_key", is_error=True)

        # 系统预置技能不允许切换版本
        error = self._check_system_skill(api_key)
        if error:
            return error

        target_version = input_data.get("version") or input_data.get("target_version")
        if not target_version:
            return ToolResult(content="switch_version 需要提供 version（目标版本号）", is_error=True)

        from src.skills.version_service import SkillVersionService, SkillVersionError
        from src.api.skill_api import get_version_service
        from src.store.skill_dao import SkillDAO

        service = get_version_service()

        # 获取当前版本号（用于日志记录）
        skill = SkillDAO.get_by_api_key(0, api_key)
        from_version = skill.current_version if skill else "unknown"

        try:
            result = service.switch_version(api_key, target_version, tenant_id=0)
        except SkillVersionError as e:
            return ToolResult(content=f"切换版本失败: {str(e)}", is_error=True)

        # 记录变更日志（标记为回滚操作）
        self._record_change_log(
            skill_api_key=api_key,
            action="switch_version",
            from_version=from_version,
            to_version=target_version,
            changelog=f"从 v{from_version} 切换到 v{target_version}",
            change_summary=f"版本回滚/切换: v{from_version} → v{target_version}",
            rollback_flg=1,
            trigger_source="chat",
        )

        return ToolResult(
            content=(
                f"✅ 技能 '{api_key}' 已切换到 v{target_version}，立即生效\n"
                f"- 变更前版本: v{from_version}\n"
                f"- 📋 变更已记录到日志"
            )
        )

    async def _handle_diff_versions(self, input_data: dict) -> ToolResult:
        """对比两个版本的差异"""
        api_key = input_data.get("api_key")
        if not api_key:
            return ToolResult(content="diff_versions 需要提供 api_key", is_error=True)

        base_version = input_data.get("base_version")
        target_version = input_data.get("target_version")
        if not base_version or not target_version:
            return ToolResult(
                content="diff_versions 需要提供 base_version 和 target_version",
                is_error=True,
            )

        from src.skills.version_service import SkillVersionService, SkillVersionError
        from src.api.skill_api import get_version_service

        service = get_version_service()

        try:
            diff = service.diff_versions(api_key, base_version, target_version, tenant_id=0)
        except SkillVersionError as e:
            return ToolResult(content=f"版本对比失败: {str(e)}", is_error=True)

        if not diff.has_changes:
            return ToolResult(content=f"v{base_version} 与 v{target_version} 无差异")

        lines = [
            f"技能 '{api_key}' 版本对比: v{base_version} → v{target_version}\n",
            f"变更摘要: {diff.summary}\n",
        ]

        if diff.field_diffs:
            lines.append("字段变更:")
            for fd in diff.field_diffs:
                old_display = str(fd.old_value)[:80] if fd.old_value else "(空)"
                new_display = str(fd.new_value)[:80] if fd.new_value else "(空)"
                lines.append(f"  [{fd.diff_type}] {fd.field_label}: {old_display} → {new_display}")

        if diff.resource_diffs:
            changed = [r for r in diff.resource_diffs if r["diff_type"] != "unchanged"]
            if changed:
                lines.append("\n资源文件变更:")
                for r in changed:
                    lines.append(f"  [{r['diff_type']}] {r['path']}")

        return ToolResult(content="\n".join(lines))

    async def _handle_list_change_logs(self, input_data: dict) -> ToolResult:
        """查看技能变更日志"""
        api_key = input_data.get("api_key")
        if not api_key:
            return ToolResult(content="list_change_logs 需要提供 api_key", is_error=True)

        try:
            from src.store.pg_pool import get_conn
            import time

            with get_conn() as conn:
                cur = conn.cursor()
                cur.execute("""
                    SELECT action, from_version, to_version, changelog,
                           change_summary, rollback_flg, created_at
                    FROM ai_skill_change_log
                    WHERE skill_api_key = %s AND tenant_id = 0 AND delete_flg = 0
                    ORDER BY created_at DESC
                    LIMIT 20
                """, (api_key,))
                rows = cur.fetchall()

            if not rows:
                return ToolResult(content=f"技能 '{api_key}' 暂无变更日志")

            lines = [f"技能 '{api_key}' 的变更日志（最近 20 条）：\n"]
            for (action, from_ver, to_ver, cl, summary, rollback, ts) in rows:
                # 格式化时间
                dt = time.strftime("%Y-%m-%d %H:%M", time.localtime(ts / 1000))
                rollback_mark = " 🔄回滚" if rollback else ""
                ver_info = f"v{from_ver} → v{to_ver}" if from_ver and to_ver else (f"→ v{to_ver}" if to_ver else f"v{from_ver} →")
                lines.append(f"  [{dt}] {action}{rollback_mark} | {ver_info}")
                if cl:
                    lines.append(f"    说明: {cl[:100]}")
                if summary:
                    lines.append(f"    摘要: {summary[:100]}")
                lines.append("")

            return ToolResult(content="\n".join(lines))
        except Exception as e:
            return ToolResult(content=f"查询变更日志失败: {str(e)}", is_error=True)

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

    def _check_system_skill(self, api_key: str) -> ToolResult | None:
        """检查是否为系统预置技能，如果是则返回错误 ToolResult，否则返回 None"""
        try:
            from src.store.skill_dao import SkillDAO
            skill = SkillDAO.get_by_api_key(0, api_key)
            if skill and bool(skill.system_flg):
                return ToolResult(
                    content=(
                        f"❌ 系统预置技能 '{api_key}' 为只读，不允许修改。\n"
                        f"系统级技能（system_flg=1）由平台维护，通过代码发布更新，"
                        f"不支持通过对话或 API 修改。\n"
                        f"如需调整系统技能，请联系平台开发团队修改源码后重新部署。"
                    ),
                    is_error=True,
                )
        except Exception as e:
            logger.warning("检查 system_flg 失败: %s", e)
        return None

    def _record_change_log(
        self,
        skill_api_key: str,
        action: str,
        from_version: str = "",
        to_version: str = "",
        changelog: str = "",
        change_summary: str = "",
        change_detail: dict | None = None,
        analysis_report: str = "",
        trigger_source: str = "chat",
        rollback_flg: int = 0,
        rollback_from_log: int | None = None,
    ) -> None:
        """记录技能变更日志到 ai_skill_change_log 表"""
        import time
        try:
            from src.store.pg_pool import get_conn
            from src.store.snowflake import next_id

            now = int(time.time() * 1000)
            detail_json = json.dumps(change_detail or {}, ensure_ascii=False)

            with get_conn() as conn:
                conn.cursor().execute("""
                    INSERT INTO ai_skill_change_log (
                        id, tenant_id, skill_api_key,
                        action, from_version, to_version, changelog,
                        change_summary, change_detail, analysis_report,
                        trigger_source, thread_id, operator_id,
                        rollback_flg, rollback_from_log,
                        delete_flg, created_at, created_by, updated_at, updated_by
                    ) VALUES (
                        %s, 0, %s,
                        %s, %s, %s, %s,
                        %s, %s, %s,
                        %s, '', 0,
                        %s, %s,
                        0, %s, 0, %s, 0
                    )
                """, (
                    next_id(), skill_api_key,
                    action, from_version, to_version, changelog,
                    change_summary, detail_json, analysis_report,
                    trigger_source,
                    rollback_flg, rollback_from_log,
                    now, now,
                ))
                conn.commit()
            logger.info("变更日志已记录: %s %s v%s→v%s", action, skill_api_key, from_version, to_version)
        except Exception as e:
            logger.warning("记录变更日志失败（不影响主流程）: %s", e)

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
            "管理 Agent 技能定义（创建、更新、删除、列表、版本管理、变更日志）。\n"
            "何时使用：用户要求创建新技能、修改已有技能、删除技能、查看技能列表、管理技能版本、或查看变更历史时使用。\n"
            "参数说明：\n"
            "  - action: create/update/delete/list/create_version/list_versions/switch_version/diff_versions/list_change_logs\n"
            "  - skill_definition: 技能定义对象（create/update/create_version 时必填）\n"
            "  - api_key: 技能标识（update/delete/版本操作时必填）\n"
            "  - version: 版本号（create_version 时为新版本号，switch_version 时为目标版本号）\n"
            "  - changelog: 版本变更说明（create_version 时使用）\n"
            "  - base_version/target_version: 对比的两个版本号（diff_versions 时必填）\n"
            "\n"
            "版本管理说明：\n"
            "  - create_version: 基于当前版本创建新版本，可同时传入 skill_definition 应用修改\n"
            "  - list_versions: 查看技能的所有版本历史\n"
            "  - switch_version: 回滚/切换到指定版本（立即生效）\n"
            "  - diff_versions: 对比两个版本的差异\n"
            "  - list_change_logs: 查看技能的变更操作日志（谁、什么时候、做了什么）\n"
            "  - update（禁用）: 不允许直接修改生效版本，必须通过 create_version\n"
        )

    def is_read_only(self, input_data: dict) -> bool:
        return input_data.get("action") == "list"
