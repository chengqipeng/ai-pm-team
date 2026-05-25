"""
Sandbox Tools — 远程沙盒执行工具集

提供 terminal、write_file、read_file、execute_code 等工具，
通过 SSH 后端在远程机器上执行命令和文件操作。

ScriptSyncer 负责将 Skill 的 scripts/ 目录从 DB 增量同步到沙盒。
"""
from .ssh_backend import SSHBackend, create_ssh_backend_from_env
from .terminal_tool import TerminalTool
from .file_tools import ReadFileTool, WriteFileTool, SearchFilesTool
from .code_execution_tool import CodeExecutionTool
from .script_syncer import ScriptSyncer, SyncResult, SKILL_BASE_DIR

__all__ = [
    "SSHBackend",
    "create_ssh_backend_from_env",
    "TerminalTool",
    "ReadFileTool",
    "WriteFileTool",
    "SearchFilesTool",
    "CodeExecutionTool",
    "ScriptSyncer",
    "SyncResult",
    "SKILL_BASE_DIR",
    "register_sandbox_tools",
]


def register_sandbox_tools(registry, backend=None):
    """注册沙盒执行工具到 ToolRegistry

    Args:
        registry: ToolRegistry 实例
        backend: Backend 实例（可选，不传则从环境变量自动创建 SSH Backend）

    Usage:
        from src.tools.sandbox import register_sandbox_tools, create_ssh_backend_from_env

        # 方式 1: 自动从环境变量创建
        register_sandbox_tools(registry)

        # 方式 2: 手动传入 backend
        backend = create_ssh_backend_from_env()
        register_sandbox_tools(registry, backend)
    """
    import logging
    logger = logging.getLogger(__name__)

    if backend is None:
        try:
            backend = create_ssh_backend_from_env()
        except ValueError as e:
            logger.warning("沙盒工具未注册: %s", e)
            return

    registry.register(TerminalTool(backend))
    registry.register(CodeExecutionTool(backend))
    registry.register(ReadFileTool(backend))
    registry.register(WriteFileTool(backend))
    registry.register(SearchFilesTool(backend))
    logger.info("✅ 沙盒工具已注册 (5 个): terminal, execute_code, read_file, write_file, search_files")
