"""
Backend 抽象基类 — 所有执行后端实现此接口

支持的后端:
  - local: 本地执行
  - ssh: SSH 远程执行
  - docker: Docker 容器执行 (未来扩展)
  - sandbox_api: 沙盒 API 调用 (未来扩展)
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ExecutionResult:
    """命令执行结果"""
    stdout: str = ""
    stderr: str = ""
    exit_code: int = 0
    timed_out: bool = False

    @property
    def output(self) -> str:
        """合并输出"""
        parts = []
        if self.stdout:
            parts.append(self.stdout)
        if self.stderr:
            parts.append(self.stderr)
        return "\n".join(parts)

    @property
    def is_error(self) -> bool:
        return self.exit_code != 0 or self.timed_out


@dataclass
class BackendConfig:
    """后端配置"""
    backend_type: str = "local"  # local | ssh | docker | sandbox_api

    # SSH 配置
    ssh_host: str = ""
    ssh_user: str = ""
    ssh_key: str = ""
    ssh_port: int = 22

    # 通用配置
    timeout: int = 180
    persistent_shell: bool = True
    working_dir: str = ""

    # 资源限制
    max_output_chars: int = 50000


class Backend(ABC):
    """执行后端抽象基类"""

    def __init__(self, config: BackendConfig):
        self.config = config

    @abstractmethod
    async def execute(self, command: str, timeout: int | None = None) -> ExecutionResult:
        """执行命令"""
        ...

    @abstractmethod
    async def write_file(self, path: str, content: str) -> ExecutionResult:
        """写文件"""
        ...

    @abstractmethod
    async def read_file(self, path: str) -> ExecutionResult:
        """读文件"""
        ...

    @abstractmethod
    async def file_exists(self, path: str) -> bool:
        """检查文件是否存在"""
        ...

    @abstractmethod
    async def connect(self) -> None:
        """建立连接"""
        ...

    @abstractmethod
    async def disconnect(self) -> None:
        """断开连接"""
        ...

    @property
    @abstractmethod
    def is_connected(self) -> bool:
        """是否已连接"""
        ...
