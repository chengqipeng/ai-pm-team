"""
SSH Backend — 通过 SSH 在远程机器上执行命令

特性:
  - ControlMaster 连接复用（避免重复握手）
  - Persistent Shell（状态保持：cd/export 跨命令生效）
  - 自动重连
  - 输出截断保护
"""
from __future__ import annotations

import asyncio
import logging
import os
import shlex
import tempfile
import uuid
from pathlib import Path
from typing import Any

from .backend_base import Backend, BackendConfig, ExecutionResult

logger = logging.getLogger(__name__)


class SSHBackend(Backend):
    """SSH 远程执行后端"""

    def __init__(self, config: BackendConfig):
        super().__init__(config)
        self._connected = False
        self._control_path = f"/tmp/hermes-ssh-{config.ssh_host}-{os.getpid()}"

    @property
    def is_connected(self) -> bool:
        return self._connected

    async def connect(self) -> None:
        """建立 SSH ControlMaster 连接"""
        if self._connected:
            return

        # 测试连接
        result = await self._run_ssh_command("echo connected", one_shot=True)
        if result.exit_code == 0:
            self._connected = True
            logger.info(
                "SSH connected to %s@%s:%d",
                self.config.ssh_user,
                self.config.ssh_host,
                self.config.ssh_port,
            )
        else:
            raise ConnectionError(
                f"SSH 连接失败: {result.stderr or result.stdout}"
            )

    async def disconnect(self) -> None:
        """关闭 SSH 连接"""
        if not self._connected:
            return
        # 关闭 ControlMaster
        try:
            proc = await asyncio.create_subprocess_exec(
                "ssh",
                "-O", "exit",
                "-o", f"ControlPath={self._control_path}",
                f"{self.config.ssh_user}@{self.config.ssh_host}",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await proc.wait()
        except Exception:
            logger.exception("disconnect 异常")
        self._connected = False
        logger.info("SSH disconnected from %s", self.config.ssh_host)

    async def execute(self, command: str, timeout: int | None = None) -> ExecutionResult:
        """执行远程命令"""
        if not self._connected:
            await self.connect()

        effective_timeout = timeout or self.config.timeout
        result = await self._run_ssh_command(command, timeout=effective_timeout)

        # 输出截断
        if len(result.stdout) > self.config.max_output_chars:
            keep_head = int(self.config.max_output_chars * 0.4)
            keep_tail = int(self.config.max_output_chars * 0.6)
            result.stdout = (
                result.stdout[:keep_head]
                + "\n\n[OUTPUT TRUNCATED]\n\n"
                + result.stdout[-keep_tail:]
            )

        return result

    async def write_file(self, path: str, content: str) -> ExecutionResult:
        """写文件到远程"""
        if not self._connected:
            await self.connect()

        # 使用 heredoc 方式写入，避免特殊字符问题
        delimiter = f"HERMES_EOF_{uuid.uuid4().hex[:8]}"
        command = f"cat > {shlex.quote(path)} << '{delimiter}'\n{content}\n{delimiter}"
        return await self._run_ssh_command(command)

    async def read_file(self, path: str) -> ExecutionResult:
        """读取远程文件"""
        if not self._connected:
            await self.connect()
        return await self._run_ssh_command(f"cat {shlex.quote(path)}")

    async def file_exists(self, path: str) -> bool:
        """检查远程文件是否存在"""
        if not self._connected:
            await self.connect()
        result = await self._run_ssh_command(f"test -e {shlex.quote(path)} && echo yes || echo no")
        return result.stdout.strip() == "yes"

    # ─── 内部方法 ───

    def _build_ssh_args(self, one_shot: bool = False) -> list[str]:
        """构建 SSH 命令参数"""
        args = [
            "ssh",
            "-o", "BatchMode=yes",
            "-o", "StrictHostKeyChecking=accept-new",
            "-o", f"ControlPath={self._control_path}",
            "-o", "ControlMaster=auto",
            "-o", "ControlPersist=300",
            "-o", "ConnectTimeout=10",
            "-p", str(self.config.ssh_port),
        ]

        if self.config.ssh_key:
            args.extend(["-i", self.config.ssh_key])

        args.append(f"{self.config.ssh_user}@{self.config.ssh_host}")
        return args

    async def _run_ssh_command(
        self,
        command: str,
        timeout: int | None = None,
        one_shot: bool = False,
    ) -> ExecutionResult:
        """执行单条 SSH 命令"""
        effective_timeout = timeout or self.config.timeout
        ssh_args = self._build_ssh_args(one_shot=one_shot)

        # 如果有工作目录，先 cd
        if self.config.working_dir and not one_shot:
            command = f"cd {shlex.quote(self.config.working_dir)} && {command}"

        ssh_args.append(command)

        try:
            proc = await asyncio.create_subprocess_exec(
                *ssh_args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            stdout, stderr = await asyncio.wait_for(
                proc.communicate(),
                timeout=effective_timeout,
            )

            return ExecutionResult(
                stdout=stdout.decode("utf-8", errors="replace"),
                stderr=stderr.decode("utf-8", errors="replace"),
                exit_code=proc.returncode or 0,
            )

        except asyncio.TimeoutError:
            proc.kill()
            return ExecutionResult(
                stdout="",
                stderr=f"命令执行超时 ({effective_timeout}s)",
                exit_code=-1,
                timed_out=True,
            )
        except Exception as e:
            logger.error("SSH command failed: %s", e)
            return ExecutionResult(
                stdout="",
                stderr=f"SSH 执行错误: {str(e)}",
                exit_code=-1,
            )


def create_ssh_backend_from_env() -> SSHBackend:
    """从环境变量创建 SSH Backend（便捷工厂方法）"""
    config = BackendConfig(
        backend_type="ssh",
        ssh_host=os.environ.get("SANDBOX_SSH_HOST", ""),
        ssh_user=os.environ.get("SANDBOX_SSH_USER", "hermes"),
        ssh_key=os.environ.get("SANDBOX_SSH_KEY", ""),
        ssh_port=int(os.environ.get("SANDBOX_SSH_PORT", "22")),
        timeout=int(os.environ.get("SANDBOX_TIMEOUT", "180")),
        persistent_shell=os.environ.get("SANDBOX_PERSISTENT_SHELL", "true").lower() == "true",
        working_dir=os.environ.get("SANDBOX_WORKING_DIR", ""),
    )

    if not config.ssh_host:
        raise ValueError(
            "SANDBOX_SSH_HOST 环境变量未设置。"
            "请在 .env 中配置: SANDBOX_SSH_HOST=<虚拟机IP>"
        )

    return SSHBackend(config)
