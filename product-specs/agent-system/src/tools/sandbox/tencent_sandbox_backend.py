"""
Tencent Sandbox Backend — 通过腾讯云 Agent Runtime (E2B SDK) 执行命令

特性:
  - 按需创建沙箱实例，天然多租户隔离
  - 支持暂停/恢复（降低成本，保留状态）
  - 沙箱复用（同 session 内复用同一沙箱）
  - 兼容 Backend 抽象接口，Tool 层零改动
  - 通过 asyncio.to_thread 包装同步 E2B SDK

依赖:
  pip install e2b e2b-code-interpreter
"""
from __future__ import annotations

import asyncio
import logging
import shlex
from dataclasses import dataclass
from typing import Any

from .backend_base import Backend, BackendConfig, ExecutionResult

logger = logging.getLogger(__name__)


@dataclass
class TencentSandboxConfig:
    """腾讯云沙箱后端配置"""
    e2b_domain: str = "ap-beijing.tencentags.com"
    e2b_api_key: str = ""
    template: str = "code-sandbox"
    timeout: int = 3600              # 沙箱存活时间（秒）
    max_output_chars: int = 50000    # 输出截断阈值
    working_dir: str = "/home/user"  # 默认工作目录


class TencentSandboxBackend(Backend):
    """腾讯云 Agent Runtime 沙箱后端

    通过 E2B 兼容 SDK 在腾讯云沙箱中执行命令、读写文件。
    沙箱生命周期: connect() 创建 → 使用 → disconnect() 销毁/暂停
    """

    def __init__(self, config: TencentSandboxConfig):
        # 构造一个 BackendConfig 传给父类（保持接口兼容）
        backend_config = BackendConfig(
            backend_type="tencent",
            timeout=config.timeout,
            working_dir=config.working_dir,
            max_output_chars=config.max_output_chars,
        )
        super().__init__(backend_config)
        self._tencent_config = config
        self._sandbox = None
        self._sandbox_id: str | None = None
        self._connected = False

    @property
    def is_connected(self) -> bool:
        return self._connected and self._sandbox is not None

    @property
    def sandbox_id(self) -> str | None:
        """当前沙箱实例 ID（可用于持久化到 session）"""
        return self._sandbox_id

    async def connect(self, sandbox_id: str | None = None) -> None:
        """创建或恢复沙箱实例

        Args:
            sandbox_id: 已有沙箱 ID（用于恢复暂停的沙箱）。
                        不传则创建新沙箱。
        """
        if self._connected and self._sandbox is not None:
            return

        self._setup_env()

        from e2b import Sandbox

        if sandbox_id:
            # 尝试恢复已有沙箱
            try:
                self._sandbox = await asyncio.to_thread(
                    Sandbox.connect, sandbox_id
                )
                self._sandbox_id = sandbox_id
                self._connected = True
                logger.info(
                    "腾讯沙箱已恢复: id=%s, template=%s",
                    sandbox_id, self._tencent_config.template,
                )
                return
            except Exception as e:
                logger.warning("恢复沙箱失败 (id=%s): %s，将创建新沙箱", sandbox_id, e)

        # 创建新沙箱
        self._sandbox = await asyncio.to_thread(
            Sandbox.create,
            template=self._tencent_config.template,
            timeout=self._tencent_config.timeout,
        )
        self._sandbox_id = self._sandbox.sandbox_id
        self._connected = True
        logger.info(
            "腾讯沙箱已创建: id=%s, template=%s, timeout=%ds",
            self._sandbox_id,
            self._tencent_config.template,
            self._tencent_config.timeout,
        )

    async def disconnect(self, force_kill: bool = False) -> None:
        """断开沙箱连接

        Args:
            force_kill: True=销毁沙箱, False=暂停沙箱（保留状态）
        """
        if not self._connected or self._sandbox is None:
            return

        try:
            if force_kill:
                await asyncio.to_thread(self._sandbox.kill)
                logger.info("腾讯沙箱已销毁: id=%s", self._sandbox_id)
                self._sandbox_id = None
            else:
                try:
                    await asyncio.to_thread(self._sandbox.pause)
                    logger.info("腾讯沙箱已暂停: id=%s", self._sandbox_id)
                except Exception as e:
                    # pause 不支持时直接 kill
                    logger.warning("暂停失败，执行销毁: %s", e)
                    await asyncio.to_thread(self._sandbox.kill)
                    self._sandbox_id = None
        except Exception as e:
            logger.error("断开沙箱失败: %s", e)
        finally:
            self._sandbox = None
            self._connected = False

    async def execute(self, command: str, timeout: int | None = None) -> ExecutionResult:
        """在沙箱中执行 Shell 命令"""
        if not self.is_connected:
            await self.connect()

        effective_timeout = timeout or self.config.timeout

        # 如果有工作目录，先 cd
        if self.config.working_dir:
            command = f"cd {shlex.quote(self.config.working_dir)} 2>/dev/null; {command}"

        try:
            result = await asyncio.to_thread(
                self._sandbox.commands.run, command
            )
            stdout = result.stdout or ""
            stderr = result.stderr or ""

            # 输出截断保护
            if len(stdout) > self.config.max_output_chars:
                keep_head = int(self.config.max_output_chars * 0.4)
                keep_tail = int(self.config.max_output_chars * 0.6)
                stdout = (
                    stdout[:keep_head]
                    + "\n\n[OUTPUT TRUNCATED]\n\n"
                    + stdout[-keep_tail:]
                )

            return ExecutionResult(
                stdout=stdout,
                stderr=stderr,
                exit_code=result.exit_code if hasattr(result, 'exit_code') else 0,
            )

        except Exception as e:
            error_msg = str(e)
            # E2B SDK 的 CommandExitException 包含 exit code 和 stderr
            if "CommandExitException" in type(e).__name__ or "exited with code" in error_msg:
                # 解析退出码
                exit_code = 1
                stderr = error_msg
                if hasattr(e, 'exit_code'):
                    exit_code = e.exit_code
                if hasattr(e, 'stderr'):
                    stderr = e.stderr
                return ExecutionResult(
                    stdout=getattr(e, 'stdout', ''),
                    stderr=stderr,
                    exit_code=exit_code,
                )

            if "timeout" in error_msg.lower():
                return ExecutionResult(
                    stdout="",
                    stderr=f"命令执行超时 ({effective_timeout}s)",
                    exit_code=-1,
                    timed_out=True,
                )

            logger.error("沙箱命令执行失败: %s", e)
            return ExecutionResult(
                stdout="",
                stderr=f"沙箱执行错误: {error_msg}",
                exit_code=-1,
            )

    async def write_file(self, path: str, content: str) -> ExecutionResult:
        """写文件到沙箱"""
        if not self.is_connected:
            await self.connect()

        try:
            await asyncio.to_thread(self._sandbox.files.write, path, content)
            return ExecutionResult(stdout=f"已写入: {path}", exit_code=0)
        except Exception as e:
            logger.error("写文件失败 %s: %s", path, e)
            return ExecutionResult(
                stderr=f"写文件失败: {str(e)}",
                exit_code=-1,
            )

    async def read_file(self, path: str) -> ExecutionResult:
        """从沙箱读取文件"""
        if not self.is_connected:
            await self.connect()

        try:
            content = await asyncio.to_thread(self._sandbox.files.read, path)
            return ExecutionResult(stdout=content, exit_code=0)
        except Exception as e:
            logger.error("读文件失败 %s: %s", path, e)
            return ExecutionResult(
                stderr=f"读文件失败: {str(e)}",
                exit_code=-1,
            )

    async def file_exists(self, path: str) -> bool:
        """检查沙箱中文件是否存在"""
        if not self.is_connected:
            await self.connect()

        try:
            result = await asyncio.to_thread(
                self._sandbox.commands.run,
                f"test -e {shlex.quote(path)} && echo yes || echo no",
            )
            return result.stdout.strip() == "yes"
        except Exception:
            return False

    # ─── 腾讯沙箱特有方法 ───

    async def pause(self) -> None:
        """暂停沙箱（保留状态，停止计费）"""
        if self._sandbox is None:
            return
        await asyncio.to_thread(self._sandbox.pause)
        self._connected = False
        logger.info("腾讯沙箱已暂停: id=%s", self._sandbox_id)

    async def resume(self) -> None:
        """恢复已暂停的沙箱"""
        if self._sandbox_id is None:
            raise RuntimeError("没有可恢复的沙箱（sandbox_id 为空）")
        await self.connect(sandbox_id=self._sandbox_id)

    def get_sandbox_url(self) -> str | None:
        """获取沙箱 Web 访问地址（如果是 All-In-One 类型）"""
        if self._sandbox is None:
            return None
        try:
            token = self._sandbox._envd_access_token
            host = self._sandbox.get_host(9000)
            return f"https://{host}/?access_token={token}"
        except Exception:
            return None

    # ─── 内部方法 ───

    def _setup_env(self) -> None:
        """设置 E2B SDK 所需的环境变量"""
        import os
        os.environ["E2B_DOMAIN"] = self._tencent_config.e2b_domain
        os.environ["E2B_API_KEY"] = self._tencent_config.e2b_api_key


def create_tencent_backend_from_env(config_dict: dict[str, str] | None = None) -> TencentSandboxBackend:
    """从配置字典创建腾讯沙箱 Backend

    Args:
        config_dict: 配置字典（通常来自 dotenv_values(".env")）。
                     不传则从 os.environ 读取。

    Raises:
        ValueError: 缺少必需配置项时抛出
    """
    import os

    def _get(key: str, default: str = "") -> str:
        if config_dict:
            return config_dict.get(key, default)
        return os.environ.get(key, default)

    api_key = _get("TENCENT_SANDBOX_API_KEY")
    if not api_key:
        raise ValueError(
            "TENCENT_SANDBOX_API_KEY 未配置。"
            "请在 .env 中设置: TENCENT_SANDBOX_API_KEY=ark_xxx"
        )

    config = TencentSandboxConfig(
        e2b_domain=_get("TENCENT_SANDBOX_DOMAIN", "ap-beijing.tencentags.com"),
        e2b_api_key=api_key,
        template=_get("TENCENT_SANDBOX_TEMPLATE", "code-sandbox"),
        timeout=int(_get("TENCENT_SANDBOX_TIMEOUT", "3600")),
        max_output_chars=int(_get("SANDBOX_MAX_OUTPUT_CHARS", "50000")),
        working_dir=_get("SANDBOX_WORKING_DIR", "/home/user"),
    )

    return TencentSandboxBackend(config)
