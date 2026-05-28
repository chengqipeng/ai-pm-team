"""
Sandbox Tools — 远程沙盒执行工具集

提供 terminal、write_file、read_file、execute_code 等工具，
通过可切换的后端（SSH / 腾讯云沙箱）执行命令和文件操作。

后端切换：在 .env 文件中设置 SANDBOX_BACKEND=ssh 或 SANDBOX_BACKEND=tencent

ScriptSyncer 负责将 Skill 的 scripts/ 目录从 DB 增量同步到沙盒。
"""
from .backend_base import Backend, BackendConfig, ExecutionResult
from .ssh_backend import SSHBackend, create_ssh_backend_from_env
from .tencent_sandbox_backend import (
    TencentSandboxBackend,
    TencentSandboxConfig,
    create_tencent_backend_from_env,
)
from .terminal_tool import TerminalTool
from .file_tools import ReadFileTool, WriteFileTool, SearchFilesTool
from .code_execution_tool import CodeExecutionTool
from .script_syncer import ScriptSyncer, SyncResult, SKILL_BASE_DIR

__all__ = [
    # Backend
    "Backend",
    "BackendConfig",
    "ExecutionResult",
    "SSHBackend",
    "create_ssh_backend_from_env",
    "TencentSandboxBackend",
    "TencentSandboxConfig",
    "create_tencent_backend_from_env",
    "create_backend",
    # Tools
    "TerminalTool",
    "ReadFileTool",
    "WriteFileTool",
    "SearchFilesTool",
    "CodeExecutionTool",
    # ScriptSyncer
    "ScriptSyncer",
    "SyncResult",
    "SKILL_BASE_DIR",
    # 注册入口
    "register_sandbox_tools",
]

# ═══ 共享 sandbox backend 单例（供各 Tool.create() 使用） ═══

_shared_sandbox_backend: Backend | None = None
_sandbox_backend_resolved: bool = False


def _get_shared_sandbox_backend() -> Backend:
    """获取共享的沙盒 backend 单例

    Raises:
        ValueError: 沙盒未配置
    """
    global _shared_sandbox_backend, _sandbox_backend_resolved
    if _sandbox_backend_resolved:
        if _shared_sandbox_backend is None:
            raise ValueError("沙盒 backend 之前初始化失败")
        return _shared_sandbox_backend
    _sandbox_backend_resolved = True
    _shared_sandbox_backend = create_backend()
    return _shared_sandbox_backend


def _load_env_config() -> dict[str, str]:
    """从 .env 文件加载配置（不污染 os.environ）"""
    import os
    from pathlib import Path

    # 查找 .env 文件：优先当前工作目录，其次项目根目录
    candidates = [
        Path.cwd() / ".env",
        Path(__file__).resolve().parents[3] / ".env",  # src/tools/sandbox → 项目根
    ]

    for env_path in candidates:
        if env_path.exists():
            try:
                from dotenv import dotenv_values
                return dotenv_values(str(env_path))
            except ImportError:
                # dotenv 未安装，手动解析
                return _parse_env_file(str(env_path))

    # 没找到 .env，返回空字典（将使用默认值）
    return {}


def _parse_env_file(path: str) -> dict[str, str]:
    """简易 .env 解析器（不依赖 python-dotenv）"""
    config = {}
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, _, value = line.partition("=")
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                config[key] = value
    return config


def create_backend(config_override: dict[str, str] | None = None) -> Backend:
    """根据 .env 配置创建对应的沙箱后端

    读取 .env 中的 SANDBOX_BACKEND 字段决定使用哪个后端:
      - ssh: SSH 远程执行（默认，向后兼容）
      - tencent: 腾讯云 Agent Runtime 沙箱

    Args:
        config_override: 可选的配置覆盖字典（测试用）

    Returns:
        Backend 实例

    Raises:
        ValueError: 配置缺失或后端类型不支持时抛出
    """
    import logging
    logger = logging.getLogger(__name__)

    config = config_override or _load_env_config()
    backend_type = config.get("SANDBOX_BACKEND", "ssh").strip().lower()

    if backend_type == "tencent":
        logger.info(
            "[sandbox] 配置加载: SANDBOX_BACKEND=tencent | domain=%s | template=%s | API=%s",
            config.get("TENCENT_SANDBOX_DOMAIN", "ap-beijing.tencentags.com"),
            config.get("TENCENT_SANDBOX_TEMPLATE", "code-sandbox"),
            f"https://api.{config.get('TENCENT_SANDBOX_DOMAIN', 'ap-beijing.tencentags.com')}",
        )
        return create_tencent_backend_from_env(config)

    elif backend_type == "ssh":
        logger.info(
            "[sandbox] 配置加载: SANDBOX_BACKEND=ssh | host=%s | user=%s | port=%s",
            config.get("SANDBOX_SSH_HOST", ""),
            config.get("SANDBOX_SSH_USER", "hermes"),
            config.get("SANDBOX_SSH_PORT", "22"),
        )
        # 从 config 构建 SSH Backend
        ssh_host = config.get("SANDBOX_SSH_HOST", "")
        if not ssh_host:
            raise ValueError(
                "SANDBOX_BACKEND=ssh 但 SANDBOX_SSH_HOST 未配置。"
                "请在 .env 中设置 SANDBOX_SSH_HOST=<IP地址>"
            )
        backend_config = BackendConfig(
            backend_type="ssh",
            ssh_host=ssh_host,
            ssh_user=config.get("SANDBOX_SSH_USER", "hermes"),
            ssh_key=config.get("SANDBOX_SSH_KEY", ""),
            ssh_port=int(config.get("SANDBOX_SSH_PORT", "22")),
            timeout=int(config.get("SANDBOX_TIMEOUT", "180")),
            persistent_shell=config.get("SANDBOX_PERSISTENT_SHELL", "true").lower() == "true",
            working_dir=config.get("SANDBOX_WORKING_DIR", ""),
            max_output_chars=int(config.get("SANDBOX_MAX_OUTPUT_CHARS", "50000")),
        )
        return SSHBackend(backend_config)

    else:
        raise ValueError(
            f"不支持的 SANDBOX_BACKEND 值: '{backend_type}'。"
            f"可选: ssh / tencent"
        )


def register_sandbox_tools(registry, backend=None):
    """注册沙盒执行工具到 ToolRegistry

    根据 .env 中 SANDBOX_BACKEND 配置自动选择后端。

    Args:
        registry: ToolRegistry 实例
        backend: Backend 实例（可选，不传则从 .env 自动创建）

    Usage:
        from src.tools.sandbox import register_sandbox_tools

        # 方式 1: 自动从 .env 读取配置（推荐）
        register_sandbox_tools(registry)

        # 方式 2: 手动传入 backend
        from src.tools.sandbox import create_backend
        backend = create_backend()
        register_sandbox_tools(registry, backend)
    """
    import logging
    logger = logging.getLogger(__name__)

    if backend is None:
        try:
            backend = create_backend()
        except ValueError as e:
            logger.warning("沙盒工具未注册: %s", e)
            return

    registry.register(TerminalTool(backend))
    registry.register(CodeExecutionTool(backend))
    registry.register(ReadFileTool(backend))
    registry.register(WriteFileTool(backend))
    registry.register(SearchFilesTool(backend))

    backend_name = type(backend).__name__
    logger.info(
        "✅ 沙盒工具已注册 (5 个, 后端=%s): terminal, execute_code, read_file, write_file, search_files",
        backend_name,
    )
