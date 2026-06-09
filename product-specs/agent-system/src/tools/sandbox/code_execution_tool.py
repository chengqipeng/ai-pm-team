"""
Code Execution Tool — 在远程沙盒中执行代码片段

支持 Python、JavaScript、Shell。
代码写入临时文件后执行，执行完自动清理。
"""
from __future__ import annotations

import logging
import uuid
import shlex
from typing import Any, Callable

from src.tools.base import Tool
from src.core.dtypes import ToolResult
from .backend_base import Backend

logger = logging.getLogger(__name__)

# 语言 → 执行命令映射
LANGUAGE_RUNNERS = {
    "python": "python3",
    "python3": "python3",
    "javascript": "node",
    "js": "node",
    "node": "node",
    "sh": "sh",
}

# 语言 → 文件扩展名映射
LANGUAGE_EXTENSIONS = {
    "python": ".py",
    "python3": ".py",
    "javascript": ".js",
    "js": ".js",
    "node": ".js",
    "sh": ".sh",
}


class CodeExecutionTool(Tool):
    """代码执行 — 在远程沙盒中运行代码片段"""

    def __init__(self, backend: Backend):
        self._backend = backend

    @classmethod
    def create(cls, tenant_id: int = 0, db_row=None) -> "CodeExecutionTool":
        """自包含初始化 — 自动解析沙盒 backend"""
        from src.tools.factory import ToolCreateSkipped
        try:
            from src.tools.sandbox import _get_shared_sandbox_backend
            return cls(backend=_get_shared_sandbox_backend())
        except ValueError as e:
            raise ToolCreateSkipped(f"沙盒未配置: {e}")

    @property
    def name(self) -> str:
        return "execute_code"

    @property
    def aliases(self) -> list[str]:
        return ["run_code"]

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "language": {
                    "type": "string",
                    "description": "编程语言: python, javascript, sh",
                    "enum": list(LANGUAGE_RUNNERS.keys()),
                },
                "code": {
                    "type": "string",
                    "description": "要执行的代码",
                },
                "timeout": {
                    "type": "integer",
                    "description": "超时时间（秒），默认 60",
                    "default": 60,
                },
            },
            "required": ["language", "code"],
        }

    def prompt(self) -> str:
        return (
            "execute_code — 在远程沙盒中执行代码片段（编程逻辑处理）。\n"
            "支持语言: python, node, sh\n"
            "\n"
            "适用场景（需要编程逻辑时才用）:\n"
            "- 需要多步数据处理逻辑（循环、条件判断、数据转换）\n"
            "- 需要对数据做计算、过滤、聚合等处理后返回结果\n"
            "- 用户明确要求写代码或运行脚本\n"
            "\n"
            "不要使用 execute_code 的场景（用 terminal 代替）:\n"
            "- 简单系统命令: df/top/ps/free/uname/ls → terminal\n"
            "- 包安装: pip3 install/npm install → terminal\n"
            "- git 操作 → terminal\n"
            "\n"
            "用法: execute_code(language='python', code='x = [1,2,3]\\nprint(sum(x))')\n"
            "代码执行后直接返回结果，不要因结果不理想而自行换方式重试。"
        )

    def _resolve_tmp_dir(self) -> str:
        """根据当前 Skill 上下文确定临时文件目录

        - 有 Skill 上下文 → /sandbox/.skills/{skill_name}/tmp
        - 无 Skill 上下文 → /sandbox/.skills/.global/tmp（兜底）
        """
        try:
            from src.skills.context import get_skill_context
            from src.tools.sandbox.script_syncer import SKILL_BASE_DIR

            ctx = get_skill_context()
            if ctx and ctx.skill_name:
                return f"{SKILL_BASE_DIR}/{ctx.skill_name}/tmp"
        except Exception:
            pass

        # 兜底：非 skill 触发的代码执行
        from src.tools.sandbox.script_syncer import SKILL_BASE_DIR
        return f"{SKILL_BASE_DIR}/.global/tmp"

    async def call(
        self,
        input_data: dict,
        context: Any = None,
        on_progress: Callable[[Any], None] | None = None,
    ) -> ToolResult:
        language = input_data.get("language", "python")
        code = input_data.get("code", "")
        timeout = input_data.get("timeout", 60)

        if not code:
            return ToolResult(content="代码不能为空", is_error=True)

        if language not in LANGUAGE_RUNNERS:
            supported = ", ".join(LANGUAGE_RUNNERS.keys())
            return ToolResult(
                content=f"不支持的语言: {language}。支持: {supported}",
                is_error=True,
            )

        if not self._backend.is_connected:
            await self._backend.connect()

        runner = LANGUAGE_RUNNERS[language]
        ext = LANGUAGE_EXTENSIONS[language]
        # 临时文件写入 skill 专属 tmp 目录
        tmp_dir = self._resolve_tmp_dir()
        tmp_file = f"{tmp_dir}/exec_{uuid.uuid4().hex[:12]}{ext}"

        try:
            # 1. 确保临时目录存在
            await self._backend.execute(f"mkdir -p {tmp_dir}")

            # 2. 写入临时文件
            write_result = await self._backend.write_file(tmp_file, code)
            if write_result.is_error:
                return ToolResult(
                    content=f"写入代码文件失败: {write_result.output}",
                    is_error=True,
                )

            # 3. 执行
            exec_command = f"{runner} {tmp_file}"
            result = await self._backend.execute(exec_command, timeout=timeout)

            # 4. 返回结果
            if result.timed_out:
                return ToolResult(
                    content=f"代码执行超时 ({timeout}s)",
                    is_error=True,
                )

            if result.is_error:
                return ToolResult(
                    content=f"Exit code: {result.exit_code}\n{result.output}",
                    is_error=True,
                )

            return ToolResult(content=result.output or "(无输出)")

        finally:
            # 5. 清理临时文件
            await self._backend.execute(f"rm -f {tmp_file}")

    def is_read_only(self, input_data: dict) -> bool:
        return False
