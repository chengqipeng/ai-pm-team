"""
Terminal Tool — 在远程沙盒中执行 Shell 命令

LLM 通过此工具执行任意 shell 命令，命令在配置的后端（SSH/Docker/Local）上执行。
"""
from __future__ import annotations

import logging
from typing import Any, Callable

from src.tools.base import Tool
from src.core.dtypes import ToolResult
from .backend_base import Backend

logger = logging.getLogger(__name__)


class TerminalTool(Tool):
    """远程终端 — 在沙盒环境中执行 Shell 命令"""

    def __init__(self, backend: Backend):
        self._backend = backend

    @property
    def name(self) -> str:
        return "terminal"

    @property
    def aliases(self) -> list[str]:
        return ["shell", "run_command"]

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "要执行的 Shell 命令",
                },
                "timeout": {
                    "type": "integer",
                    "description": "超时时间（秒），默认 180",
                    "default": 180,
                },
            },
            "required": ["command"],
        }

    def prompt(self) -> str:
        return (
            "terminal — 在远程沙盒中执行 Shell 命令。\n"
            "支持所有标准 Linux 命令。工作目录和环境变量跨命令保持。\n"
            "用法: terminal(command='df -h && free -m')\n"
            "\n"
            "不要用 cat/head/tail 读文件 — 用 read_file。\n"
            "不要用 grep/find 搜索 — 用 search_files。\n"
            "不要用 echo/cat heredoc 创建文件 — 用 write_file。\n"
            "不要用 terminal 执行 Python/JS 脚本 — 用 execute_code。\n"
            "terminal 适用于: 系统命令(df/top/ps/free/uname)、包管理、"
            "git 操作、进程管理、网络诊断。\n"
            "安装 Python 包使用: /usr/local/bin/python3 -m pip install <包名>\n"
            "执行 Python 脚本使用: /usr/local/bin/python3 <脚本路径>\n"
            "\n"
            "命令返回结果后（包括空结果或报错），直接基于结果回复用户，"
            "不要自行重试或换方式探索。"
        )

    async def call(
        self,
        input_data: dict,
        context: Any = None,
        on_progress: Callable[[Any], None] | None = None,
    ) -> ToolResult:
        command = input_data.get("command", "")
        timeout = input_data.get("timeout", 180)

        if not command:
            return ToolResult(content="命令不能为空", is_error=True)

        # 确保后端已连接
        if not self._backend.is_connected:
            try:
                await self._backend.connect()
            except Exception as e:
                return ToolResult(
                    content=f"沙盒连接失败: {str(e)}",
                    is_error=True,
                )

        # 执行命令
        result = await self._backend.execute(command, timeout=timeout)

        if result.timed_out:
            return ToolResult(
                content=f"命令执行超时 ({timeout}s): {command}",
                is_error=True,
            )

        if result.is_error:
            return ToolResult(
                content=f"Exit code: {result.exit_code}\n{result.output}",
                is_error=True,
            )

        return ToolResult(content=result.output or "(无输出)")

    async def description(self, input_data: dict) -> str:
        command = input_data.get("command", "")
        return f"执行命令: {command[:80]}"

    def is_read_only(self, input_data: dict) -> bool:
        return False

    def is_destructive(self, input_data: dict) -> bool:
        """检测危险命令"""
        command = input_data.get("command", "")
        dangerous_patterns = [
            "rm -rf /",
            "mkfs",
            "dd if=/dev/zero",
            "> /dev/sd",
            ":(){ :|:& };:",
        ]
        return any(p in command for p in dangerous_patterns)
