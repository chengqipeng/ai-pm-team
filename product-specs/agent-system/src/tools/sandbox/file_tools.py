"""
File Tools — 远程文件读写操作

提供 read_file、write_file、search_files 工具，
通过后端在远程沙盒中操作文件。
"""
from __future__ import annotations

import logging
import shlex
from typing import Any, Callable

from src.tools.base import Tool
from src.core.dtypes import ToolResult
from .backend_base import Backend

logger = logging.getLogger(__name__)


class ReadFileTool(Tool):
    """读取远程文件内容"""

    def __init__(self, backend: Backend):
        self._backend = backend

    @classmethod
    def create(cls, tenant_id: int = 0, db_row=None) -> "ReadFileTool":
        """自包含初始化 — 自动解析沙盒 backend"""
        from src.tools.factory import ToolCreateSkipped
        try:
            from src.tools.sandbox import _get_shared_sandbox_backend
            return cls(backend=_get_shared_sandbox_backend())
        except ValueError as e:
            raise ToolCreateSkipped(f"沙盒未配置: {e}")

    @property
    def name(self) -> str:
        return "read_file"

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "文件路径（绝对路径或相对于工作目录）",
                },
                "offset": {
                    "type": "integer",
                    "description": "起始行号（从 0 开始），默认 0",
                    "default": 0,
                },
                "limit": {
                    "type": "integer",
                    "description": "读取行数，默认 2000",
                    "default": 2000,
                },
            },
            "required": ["path"],
        }

    def prompt(self) -> str:
        return (
            "read_file — 读取远程沙盒中的文件内容。\n"
            "支持按行范围读取大文件。\n"
            "用法: read_file(path='/sandbox/app/main.py')\n"
            "     read_file(path='main.py', offset=10, limit=50)"
        )

    async def call(
        self,
        input_data: dict,
        context: Any = None,
        on_progress: Callable[[Any], None] | None = None,
    ) -> ToolResult:
        path = input_data.get("path", "")
        offset = input_data.get("offset", 0)
        limit = input_data.get("limit", 2000)

        if not path:
            return ToolResult(content="文件路径不能为空", is_error=True)

        if not self._backend.is_connected:
            await self._backend.connect()

        # 检查文件是否存在
        exists = await self._backend.file_exists(path)
        if not exists:
            return ToolResult(content=f"文件不存在: {path}", is_error=True)

        # 按行范围读取
        if offset > 0 or limit < 2000:
            start = offset + 1
            end = offset + limit
            command = f"sed -n '{start},{end}p' {shlex.quote(path)}"
            result = await self._backend.execute(command)
        else:
            result = await self._backend.read_file(path)

        if result.is_error:
            return ToolResult(content=f"读取失败: {result.output}", is_error=True)

        return ToolResult(content=result.stdout or "(空文件)")

    def is_read_only(self, input_data: dict) -> bool:
        return True


class WriteFileTool(Tool):
    """写入文件到远程沙盒"""

    def __init__(self, backend: Backend):
        self._backend = backend

    @classmethod
    def create(cls, tenant_id: int = 0, db_row=None) -> "WriteFileTool":
        """自包含初始化 — 自动解析沙盒 backend"""
        from src.tools.factory import ToolCreateSkipped
        try:
            from src.tools.sandbox import _get_shared_sandbox_backend
            return cls(backend=_get_shared_sandbox_backend())
        except ValueError as e:
            raise ToolCreateSkipped(f"沙盒未配置: {e}")

    @property
    def name(self) -> str:
        return "write_file"

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "文件路径",
                },
                "content": {
                    "type": "string",
                    "description": "文件内容",
                },
            },
            "required": ["path", "content"],
        }

    def prompt(self) -> str:
        return (
            "write_file — 在远程沙箱中创建或覆盖文件。\n"
            "所有文件必须写入 /sandbox/.skills/ 目录下。\n"
            "Skill 执行中: 输出文件写入 ${SKILL_OUTPUT_DIR}，临时文件写入 ${SKILL_TMP_DIR}。\n"
            "非 Skill 场景: 写入 /sandbox/.skills/.global/output/。\n"
            "自动创建父目录。路径不在 /sandbox/.skills/ 下时会自动重定向。\n"
            "用法: write_file(path='/sandbox/.skills/my-skill/output/report.html', content='...')"
        )

    def _normalize_path(self, path: str) -> str:
        """规范化文件路径，确保所有文件写入 /sandbox/.skills/ 目录下

        规则:
        - 已在 /sandbox/.skills/ 下 → 原样返回
        - 不在 /sandbox/.skills/ 下 → 重定向到当前 skill 的 output/ 目录
        - 无 skill 上下文 → 重定向到 /sandbox/.skills/.global/output/
        """
        from src.tools.sandbox.script_syncer import SKILL_BASE_DIR

        # 已经在合法目录下，直接返回
        if path.startswith(f"{SKILL_BASE_DIR}/"):
            return path

        # 提取文件名
        import os
        filename = os.path.basename(path)

        # 确定目标目录
        try:
            from src.skills.context import get_skill_context
            ctx = get_skill_context()
            if ctx and ctx.skill_name:
                target_dir = f"{SKILL_BASE_DIR}/{ctx.skill_name}/output"
            else:
                target_dir = f"{SKILL_BASE_DIR}/.global/output"
        except Exception:
            target_dir = f"{SKILL_BASE_DIR}/.global/output"

        new_path = f"{target_dir}/{filename}"
        logger.info("[write_file] 路径重定向: %s → %s", path, new_path)
        return new_path

    async def call(
        self,
        input_data: dict,
        context: Any = None,
        on_progress: Callable[[Any], None] | None = None,
    ) -> ToolResult:
        path = input_data.get("path", "")
        content = input_data.get("content", "")

        if not path:
            return ToolResult(content="文件路径不能为空", is_error=True)

        # 路径规范化：所有文件必须在 /sandbox/.skills/ 目录下
        path = self._normalize_path(path)

        if not self._backend.is_connected:
            await self._backend.connect()

        # 确保父目录存在
        parent_dir = "/".join(path.split("/")[:-1])
        if parent_dir:
            await self._backend.execute(f"mkdir -p {shlex.quote(parent_dir)}")

        # 写入文件
        result = await self._backend.write_file(path, content)

        if result.is_error:
            return ToolResult(content=f"写入失败: {result.output}", is_error=True)

        # 确认写入
        line_count = content.count("\n") + 1
        return ToolResult(content=f"已写入 {path} ({line_count} 行)")

    def is_read_only(self, input_data: dict) -> bool:
        return False


class SearchFilesTool(Tool):
    """在远程沙盒中搜索文件内容"""

    def __init__(self, backend: Backend):
        self._backend = backend

    @classmethod
    def create(cls, tenant_id: int = 0, db_row=None) -> "SearchFilesTool":
        """自包含初始化 — 自动解析沙盒 backend"""
        from src.tools.factory import ToolCreateSkipped
        try:
            from src.tools.sandbox import _get_shared_sandbox_backend
            return cls(backend=_get_shared_sandbox_backend())
        except ValueError as e:
            raise ToolCreateSkipped(f"沙盒未配置: {e}")

    @property
    def name(self) -> str:
        return "search_files"

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "pattern": {
                    "type": "string",
                    "description": "搜索模式（支持正则）",
                },
                "path": {
                    "type": "string",
                    "description": "搜索目录，默认当前目录",
                    "default": ".",
                },
                "include": {
                    "type": "string",
                    "description": "文件名过滤（如 '*.py'）",
                    "default": "",
                },
            },
            "required": ["pattern"],
        }

    def prompt(self) -> str:
        return (
            "search_files — 在远程沙盒中搜索文件内容。\n"
            "使用 grep 进行递归搜索，支持正则表达式。\n"
            "用法: search_files(pattern='TODO', path='src/', include='*.py')"
        )

    async def call(
        self,
        input_data: dict,
        context: Any = None,
        on_progress: Callable[[Any], None] | None = None,
    ) -> ToolResult:
        pattern = input_data.get("pattern", "")
        path = input_data.get("path", ".")
        include = input_data.get("include", "")

        if not pattern:
            return ToolResult(content="搜索模式不能为空", is_error=True)

        if not self._backend.is_connected:
            await self._backend.connect()

        # 构建 grep 命令
        cmd_parts = ["grep", "-rn", "--color=never"]
        if include:
            cmd_parts.extend(["--include", shlex.quote(include)])
        cmd_parts.append(shlex.quote(pattern))
        cmd_parts.append(shlex.quote(path))

        command = " ".join(cmd_parts)
        result = await self._backend.execute(command)

        # grep 返回 1 表示没找到（不是错误）
        if result.exit_code == 1 and not result.stderr:
            return ToolResult(content="未找到匹配内容")

        if result.exit_code > 1:
            return ToolResult(content=f"搜索失败: {result.output}", is_error=True)

        return ToolResult(content=result.stdout or "未找到匹配内容")

    def is_read_only(self, input_data: dict) -> bool:
        return True
