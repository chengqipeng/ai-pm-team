"""
Tencent Sandbox Backend — 通过腾讯云 Agent Runtime (E2B SDK) 执行命令

特性:
  - 按需创建沙箱实例，天然多租户隔离
  - 会话级沙箱复用（sandbox_id 持久化到 ai_conversation.ext_info）
  - 支持暂停/恢复（降低成本，保留状态）
  - 沙箱过期自动重建
  - 兼容 Backend 抽象接口，Tool 层零改动
  - 通过 asyncio.to_thread 包装同步 E2B SDK

依赖:
  pip install e2b e2b-code-interpreter
"""
from __future__ import annotations

import asyncio
import json
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

    @property
    def api_base_url(self) -> str:
        """E2B 兼容 API 的基础地址"""
        return f"https://api.{self._tencent_config.e2b_domain}"

    async def connect(self, sandbox_id: str | None = None) -> None:
        """创建或恢复沙箱实例（会话级复用）

        优先级:
          1. 如果当前已连接，直接返回
          2. 从 ai_conversation.ext_info 读取该会话绑定的 sandbox_id
          3. 如果存在，尝试恢复（connect）；如果沙箱已过期则重建
          4. 如果不存在，创建新沙箱并将 sandbox_id 写入 ai_conversation

        Args:
            sandbox_id: 显式指定沙箱 ID（优先级最高，跳过数据库查询）
        """
        if self._connected and self._sandbox is not None:
            return

        self._setup_env()

        from e2b import Sandbox

        logger.info(
            "[sandbox] 后端类型=TencentSandbox | API=%s | template=%s",
            self.api_base_url, self._tencent_config.template,
        )

        # 如果没有显式传入 sandbox_id，从数据库加载
        if not sandbox_id:
            sandbox_id = self._load_sandbox_id_from_db()

        if sandbox_id:
            # 尝试恢复已有沙箱
            try:
                logger.info("[sandbox] 恢复沙箱: POST %s/sandboxes/%s/resume", self.api_base_url, sandbox_id)
                self._sandbox = await asyncio.to_thread(
                    Sandbox.connect, sandbox_id
                )
                self._sandbox_id = sandbox_id
                self._connected = True
                logger.info(
                    "[sandbox] 沙箱已恢复: id=%s, template=%s",
                    sandbox_id, self._tencent_config.template,
                )
                return
            except Exception as e:
                logger.warning("[sandbox] 恢复沙箱失败 (id=%s): %s，沙箱可能已过期，将创建新沙箱", sandbox_id, e)

        # 创建新沙箱
        logger.info("[sandbox] 创建沙箱: POST %s/sandboxes {template=%s, timeout=%d}",
                    self.api_base_url, self._tencent_config.template, self._tencent_config.timeout)
        self._sandbox = await asyncio.to_thread(
            Sandbox.create,
            template=self._tencent_config.template,
            timeout=self._tencent_config.timeout,
        )
        self._sandbox_id = self._sandbox.sandbox_id
        self._connected = True
        logger.info(
            "[sandbox] 沙箱已创建: id=%s, template=%s, timeout=%ds",
            self._sandbox_id,
            self._tencent_config.template,
            self._tencent_config.timeout,
        )

        # 持久化 sandbox_id 到数据库
        self._save_sandbox_id_to_db(self._sandbox_id)

        # 初始化预置文件
        await self._init_preset_files()

    async def disconnect(self, force_kill: bool = False) -> None:
        """断开沙箱连接

        Args:
            force_kill: True=销毁沙箱, False=暂停沙箱（保留状态）
        """
        if not self._connected or self._sandbox is None:
            return

        try:
            if force_kill:
                logger.info("[sandbox] 销毁沙箱: DELETE %s/sandboxes/%s", self.api_base_url, self._sandbox_id)
                await asyncio.to_thread(self._sandbox.kill)
                logger.info("[sandbox] 沙箱已销毁: id=%s", self._sandbox_id)
                self._sandbox_id = None
            else:
                try:
                    logger.info("[sandbox] 暂停沙箱: POST %s/sandboxes/%s/pause", self.api_base_url, self._sandbox_id)
                    await asyncio.to_thread(self._sandbox.pause)
                    logger.info("[sandbox] 沙箱已暂停: id=%s", self._sandbox_id)
                except Exception as e:
                    # pause 不支持时直接 kill
                    logger.warning("[sandbox] 暂停失败，执行销毁: %s", e)
                    await asyncio.to_thread(self._sandbox.kill)
                    self._sandbox_id = None
        except Exception as e:
            logger.error("[sandbox] 断开沙箱失败: %s", e)
        finally:
            self._sandbox = None
            self._connected = False

    async def execute(self, command: str, timeout: int | None = None) -> ExecutionResult:
        """在沙箱中执行 Shell 命令"""
        if not self.is_connected:
            await self.connect()

        # 如果有待保存的 sandbox_id（会话记录延迟创建），尝试重试
        if getattr(self, '_pending_save_thread_id', None):
            self._retry_save_sandbox_id()

        effective_timeout = timeout or self.config.timeout

        # 如果有工作目录，先 cd
        if self.config.working_dir:
            command = f"cd {shlex.quote(self.config.working_dir)} 2>/dev/null; {command}"

        logger.info("[sandbox] 执行命令: POST %s/sandboxes/%s/commands | cmd=%s",
                    self.api_base_url, self._sandbox_id, command[:100])

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

        logger.info("[sandbox] 写文件: POST %s/sandboxes/%s/files | path=%s, size=%d",
                    self.api_base_url, self._sandbox_id, path, len(content))

        try:
            await asyncio.to_thread(self._sandbox.files.write, path, content)
            return ExecutionResult(stdout=f"已写入: {path}", exit_code=0)
        except Exception as e:
            logger.error("[sandbox] 写文件失败 %s: %s", path, e)
            return ExecutionResult(
                stderr=f"写文件失败: {str(e)}",
                exit_code=-1,
            )

    async def read_file(self, path: str) -> ExecutionResult:
        """从沙箱读取文件"""
        if not self.is_connected:
            await self.connect()

        logger.info("[sandbox] 读文件: GET %s/sandboxes/%s/files | path=%s",
                    self.api_base_url, self._sandbox_id, path)

        try:
            content = await asyncio.to_thread(self._sandbox.files.read, path)
            return ExecutionResult(stdout=content, exit_code=0)
        except Exception as e:
            logger.error("[sandbox] 读文件失败 %s: %s", path, e)
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

    def _load_sandbox_id_from_db(self) -> str | None:
        """从 ai_conversation.ext_info 中读取当前会话绑定的 sandbox_id"""
        try:
            from src.core.context import get_context
            ctx = get_context()
            thread_id = ctx.thread_id
            tenant_id = ctx.tenant_id

            if not thread_id:
                logger.debug("[sandbox] 无 thread_id，跳过数据库查询")
                return None

            from src.store.pg_pool import get_conn

            with get_conn() as conn:
                cur = conn.cursor()
                cur.execute(
                    "SELECT ext_info FROM ai_conversation "
                    "WHERE tenant_id=%s AND thread_id=%s AND delete_flg=0",
                    (tenant_id, thread_id),
                )
                row = cur.fetchone()

            if not row or not row[0]:
                return None

            ext_info = json.loads(row[0]) if isinstance(row[0], str) else row[0]
            sandbox_id = ext_info.get("sandbox_id")

            if sandbox_id:
                logger.info("[sandbox] 从数据库加载 sandbox_id: thread=%s → sandbox=%s", thread_id, sandbox_id)

            return sandbox_id

        except Exception as e:
            logger.warning("[sandbox] 从数据库加载 sandbox_id 失败 (non-fatal): %s", e)
            return None

    def _save_sandbox_id_to_db(self, sandbox_id: str) -> None:
        """将 sandbox_id 写入 ai_conversation.ext_info（JSON merge）"""
        try:
            from src.core.context import get_context
            ctx = get_context()
            thread_id = ctx.thread_id
            tenant_id = ctx.tenant_id

            if not thread_id:
                logger.debug("[sandbox] 无 thread_id，跳过数据库写入")
                return

            from src.store.pg_pool import get_conn
            import time

            now = int(time.time() * 1000)

            with get_conn() as conn:
                cur = conn.cursor()

                # 读取现有 ext_info
                cur.execute(
                    "SELECT ext_info FROM ai_conversation "
                    "WHERE tenant_id=%s AND thread_id=%s AND delete_flg=0",
                    (tenant_id, thread_id),
                )
                row = cur.fetchone()

                if row:
                    # 更新已有记录
                    existing = {}
                    if row[0]:
                        existing = json.loads(row[0]) if isinstance(row[0], str) else row[0]
                    existing["sandbox_id"] = sandbox_id
                    cur.execute(
                        "UPDATE ai_conversation SET ext_info=%s, updated_at=%s "
                        "WHERE tenant_id=%s AND thread_id=%s AND delete_flg=0",
                        (json.dumps(existing, ensure_ascii=False), now, tenant_id, thread_id),
                    )
                    logger.info("[sandbox] sandbox_id 已保存到数据库: thread=%s → sandbox=%s", thread_id, sandbox_id)
                else:
                    # 会话记录尚未创建（首次对话，TraceWriter 还没写入）
                    # 暂存到实例变量，等会话记录创建后再写入
                    logger.info("[sandbox] 会话记录尚未创建，sandbox_id 暂存: thread=%s → sandbox=%s", thread_id, sandbox_id)
                    self._pending_save_thread_id = thread_id
                    self._pending_save_tenant_id = tenant_id

        except Exception as e:
            logger.warning("[sandbox] 保存 sandbox_id 到数据库失败 (non-fatal): %s", e)

    def _retry_save_sandbox_id(self) -> None:
        """重试保存 sandbox_id（用于会话记录延迟创建的场景）"""
        thread_id = getattr(self, '_pending_save_thread_id', None)
        tenant_id = getattr(self, '_pending_save_tenant_id', None)
        if not thread_id or not self._sandbox_id:
            return

        try:
            from src.store.pg_pool import get_conn
            import time

            now = int(time.time() * 1000)

            with get_conn() as conn:
                cur = conn.cursor()
                cur.execute(
                    "SELECT ext_info FROM ai_conversation "
                    "WHERE tenant_id=%s AND thread_id=%s AND delete_flg=0",
                    (tenant_id, thread_id),
                )
                row = cur.fetchone()
                if row:
                    existing = {}
                    if row[0]:
                        existing = json.loads(row[0]) if isinstance(row[0], str) else row[0]
                    existing["sandbox_id"] = self._sandbox_id
                    cur.execute(
                        "UPDATE ai_conversation SET ext_info=%s, updated_at=%s "
                        "WHERE tenant_id=%s AND thread_id=%s AND delete_flg=0",
                        (json.dumps(existing, ensure_ascii=False), now, tenant_id, thread_id),
                    )
                    logger.info("[sandbox] sandbox_id 延迟保存成功: thread=%s → sandbox=%s", thread_id, self._sandbox_id)
                    self._pending_save_thread_id = None
                    self._pending_save_tenant_id = None
        except Exception as e:
            logger.debug("[sandbox] 延迟保存 sandbox_id 重试失败: %s", e)

    async def _init_preset_files(self) -> None:
        """沙箱创建后自动写入预置文件（测试数据等）"""
        preset_files = self._get_preset_files()
        if not preset_files:
            return

        for path, content in preset_files.items():
            try:
                await asyncio.to_thread(self._sandbox.files.write, path, content)
                logger.info("[sandbox] 预置文件已写入: %s (%d bytes)", path, len(content))
            except Exception as e:
                logger.warning("[sandbox] 预置文件写入失败: %s → %s", path, e)

    def _get_preset_files(self) -> dict[str, str]:
        """返回需要预置到沙箱的文件 {路径: 内容}

        可通过子类覆盖或从配置文件加载。
        """
        return {
            "/tmp/test_sales.csv": (
                "date,revenue,orders,avg_price\n"
                "2024-01,120000,450,266.67\n"
                "2024-02,135000,520,259.62\n"
                "2024-03,128000,480,266.67\n"
                "2024-04,142000,550,258.18\n"
                "2024-05,155000,600,258.33\n"
                "2024-06,148000,570,259.65\n"
                "2024-07,162000,620,261.29\n"
                "2024-08,170000,650,261.54\n"
                "2024-09,158000,590,267.80\n"
                "2024-10,175000,680,257.35\n"
                "2024-11,185000,720,256.94\n"
                "2024-12,195000,750,260.00\n"
            ),
        }

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
