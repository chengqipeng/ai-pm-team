"""
AWS AgentCore Sandbox Backend — 通过 Bedrock AgentCore Code Interpreter 执行命令

特性:
  - 按需创建沙箱会话（microVM 级隔离，天然多租户）
  - 会话级复用（session_id 持久化到 ai_conversation.ext_info）
  - 三级 S3 同步（write 即时双写 + execute 增量 + disconnect 全量兜底）
  - connect 时从 S3 全量恢复（模拟 COS 挂载语义）
  - 沙箱过期自动重建 + S3 数据不丢
  - 兼容 Backend 抽象接口，Tool 层零改动
  - 通过 asyncio.to_thread 包装同步 SDK

依赖:
  pip install bedrock-agentcore boto3

对齐腾讯版行为（上层使用方零感知）:
  - connect() = start + mkdir + S3 restore（等价于 COS 挂载）
  - disconnect(force_kill=False) = S3 全量 sync + stop（等价于 pause）
  - disconnect(force_kill=True) = stop（等价于 kill）
  - write_file = 写沙箱 + 异步写 S3（等价于 COS 实时落盘）
  - execute = 沙箱执行 + 条件增量 sync（等价于 COS 对命令产出的持久化）
"""
from __future__ import annotations

import asyncio
import json
import logging
import shlex
from dataclasses import dataclass
from typing import Any

from .backend_base import Backend, BackendConfig, ExecutionResult
from .sync_manager import SandboxSyncManager

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


@dataclass
class AWSAgentCoreConfig:
    """AWS AgentCore 沙箱后端配置"""
    region: str = "ap-southeast-1"
    session_timeout: int = 3600          # 会话存活时间（秒），最大 28800
    max_output_chars: int = 50000        # 输出截断阈值
    working_dir: str = "/tmp/sandbox"    # 沙箱工作根目录（CI 非 root 不可写 /）
    sync_bucket: str = ""                # S3 同步桶名（空=不同步）
    sync_prefix: str = "sandbox"         # S3 基础前缀
    sync_interval: int = 5              # 每 N 次 execute 触发增量 sync
    network_mode: str = "PUBLIC"         # PUBLIC / SANDBOX / VPC


class AWSAgentCoreSandboxBackend(Backend):
    """AWS Bedrock AgentCore Code Interpreter 沙箱后端

    通过 AgentCore SDK 在独立 microVM 中执行命令、读写文件。
    内嵌 SandboxSyncManager 实现三级 S3 同步，上层 Tool/Middleware 无需任何改动。

    数据同步策略（对齐腾讯 COS 挂载语义）:
      - write_file → 写沙箱 + 异步写 S3（即时双写，关键产出不丢）
      - execute → 执行命令 + 条件增量 sync（命令产出文件持久化）
      - disconnect → 全量 sync 兜底（确保所有数据落 S3）
      - connect → 从 S3 全量恢复（新 microVM 立即看到历史数据）

    隔离策略:
      - microVM 天然隔离（比腾讯 COS subPath 更强）
      - S3 路径按 {tenant}/{user}/{conversation} 隔离
    """

    CI_TOOL_ID = "aws.codeinterpreter.v1"

    def __init__(self, config: AWSAgentCoreConfig):
        backend_config = BackendConfig(
            backend_type="aws",
            timeout=config.session_timeout,
            working_dir=config.working_dir,
            max_output_chars=config.max_output_chars,
        )
        super().__init__(backend_config)
        self._aws_config = config
        self._ci = None
        self._session_id: str | None = None
        self._connected = False
        self._sync_manager: SandboxSyncManager | None = None

    @property
    def is_connected(self) -> bool:
        return self._connected and self._ci is not None

    @property
    def session_id(self) -> str | None:
        return self._session_id

    # ═══════════════════════════════════════════════════════
    # Backend 接口实现
    # ═══════════════════════════════════════════════════════

    async def connect(self, session_id: str | None = None) -> None:
        """创建沙箱会话 + 建标准目录 + S3 恢复历史数据

        等价于腾讯版：Sandbox.create() + COS 挂载自动可见
        """
        if self._connected and self._ci is not None:
            return

        from bedrock_agentcore.tools.code_interpreter_client import CodeInterpreter

        # 获取身份上下文（用于 S3 路径隔离 + DB 持久化）
        context_session_id = self._get_session_id()
        tenant_id = self._get_tenant_id()
        user_id = self._get_user_id()

        logger.info(
            "[sandbox] 后端=AWSAgentCore | region=%s | timeout=%ds | workdir=%s | bucket=%s",
            self._aws_config.region, self._aws_config.session_timeout,
            self._aws_config.working_dir, self._aws_config.sync_bucket or "(无)",
        )

        # 创建 CI 会话
        self._ci = CodeInterpreter(region=self._aws_config.region)
        self._session_id = await asyncio.to_thread(
            self._ci.start,
            name=f"agent_{context_session_id or 'default'}",
            session_timeout_seconds=self._aws_config.session_timeout,
        )
        self._connected = True
        logger.info("[sandbox] 会话已创建: id=%s", self._session_id)

        # 创建标准目录布局（对齐腾讯的 /sandbox/workspace + uploads + outputs）
        workdir = self._aws_config.working_dir
        await self._invoke_command(
            f"mkdir -p {workdir}/workspace {workdir}/uploads {workdir}/outputs"
        )

        # 初始化 SyncManager
        s3_prefix = self._build_s3_prefix(tenant_id, user_id, context_session_id)
        self._sync_manager = SandboxSyncManager(
            bucket=self._aws_config.sync_bucket,
            prefix=s3_prefix,
            region=self._aws_config.region,
            working_dir=workdir,
            sync_interval=self._aws_config.sync_interval,
        )

        # 从 S3 恢复历史数据（等价于腾讯 COS 挂载后自动可见）
        if self._aws_config.sync_bucket and context_session_id:
            restored = await self._sync_manager.restore(
                self._invoke_command, self._invoke_code
            )
            if restored > 0:
                logger.info("[sandbox] 恢复历史数据: %d 个文件", restored)

        # 持久化 session_id
        self._save_session_id_to_db(self._session_id)

        # 写入预置文件
        await self._init_preset_files()

    async def disconnect(self, force_kill: bool = False) -> None:
        """关闭沙箱会话

        force_kill=False: 全量 sync 到 S3 后关闭（等价于腾讯 pause）
        force_kill=True: 直接关闭不 sync（等价于腾讯 kill）
        """
        if not self._connected or self._ci is None:
            return

        try:
            if not force_kill and self._sync_manager:
                logger.info("[sandbox] 执行全量 sync...")
                await self._sync_manager.final_sync(self._invoke_command)
            elif force_kill:
                logger.info("[sandbox] 强制关闭，跳过 sync")

            await asyncio.to_thread(self._ci.stop)
            logger.info("[sandbox] 会话已关闭: id=%s", self._session_id)
        except Exception as e:
            logger.error("[sandbox] 关闭失败: %s", e)
        finally:
            self._ci = None
            self._session_id = None
            self._connected = False
            self._sync_manager = None

    async def execute(self, command: str, timeout: int | None = None) -> ExecutionResult:
        """在沙箱中执行命令 + 条件触发增量 sync"""
        if not self.is_connected:
            await self.connect()

        if getattr(self, '_pending_save_thread_id', None):
            self._retry_save_session_id()

        effective_timeout = timeout or self.config.timeout
        raw_command = command  # 保留原始命令用于 sync 判断

        if self.config.working_dir:
            command = f"cd {shlex.quote(self.config.working_dir)} 2>/dev/null; {command}"

        logger.info("[sandbox] execute: session=%s | cmd=%s", self._session_id, raw_command[:100])

        try:
            stdout = await self._invoke_command(command)

            # 输出截断
            if len(stdout) > self.config.max_output_chars:
                keep_head = int(self.config.max_output_chars * 0.4)
                keep_tail = int(self.config.max_output_chars * 0.6)
                stdout = stdout[:keep_head] + "\n\n[OUTPUT TRUNCATED]\n\n" + stdout[-keep_tail:]

            # 触发增量 sync（异步，不阻塞返回）
            if self._sync_manager:
                await self._sync_manager.on_execute(raw_command, self._invoke_command)

            return ExecutionResult(stdout=stdout, stderr="", exit_code=0)

        except Exception as e:
            error_msg = str(e)

            if "timeout" in error_msg.lower():
                return ExecutionResult(
                    stdout="", stderr=f"命令执行超时 ({effective_timeout}s)",
                    exit_code=-1, timed_out=True,
                )

            if self._is_session_expired(e):
                logger.warning("[sandbox] 会话过期，重建后重试")
                await self._reconnect()
                try:
                    stdout = await self._invoke_command(command)
                    return ExecutionResult(stdout=stdout, stderr="", exit_code=0)
                except Exception as retry_e:
                    return ExecutionResult(
                        stdout="", stderr=f"沙箱执行错误: {retry_e}", exit_code=-1
                    )

            logger.error("[sandbox] 执行失败: %s", e)
            return ExecutionResult(stdout="", stderr=f"沙箱执行错误: {error_msg}", exit_code=-1)

    async def write_file(self, path: str, content: str) -> ExecutionResult:
        """写文件到沙箱 + 异步写 S3（即时双写）"""
        if not self.is_connected:
            await self.connect()

        logger.info("[sandbox] write_file: session=%s | path=%s, size=%d",
                    self._session_id, path, len(content))

        try:
            write_code = (
                f"import os\n"
                f"os.makedirs(os.path.dirname({path!r}) or '.', exist_ok=True)\n"
                f"with open({path!r}, 'w', encoding='utf-8') as f:\n"
                f"    f.write({content!r})\n"
                f"print('OK')\n"
            )
            result = await self._invoke_code("python", write_code)

            if "OK" in result:
                # 即时双写 S3（异步，不阻塞返回）
                if self._sync_manager:
                    await self._sync_manager.on_write(path, content)
                return ExecutionResult(stdout=f"已写入: {path}", exit_code=0)
            else:
                return ExecutionResult(stderr=f"写文件异常: {result}", exit_code=-1)

        except Exception as e:
            if self._is_session_expired(e):
                logger.warning("[sandbox] 写文件时会话过期，重建后重试: %s", path)
                await self._reconnect()
                try:
                    write_code = (
                        f"import os\n"
                        f"os.makedirs(os.path.dirname({path!r}) or '.', exist_ok=True)\n"
                        f"with open({path!r}, 'w', encoding='utf-8') as f:\n"
                        f"    f.write({content!r})\n"
                        f"print('OK')\n"
                    )
                    result = await self._invoke_code("python", write_code)
                    if "OK" in result:
                        if self._sync_manager:
                            await self._sync_manager.on_write(path, content)
                        return ExecutionResult(stdout=f"已写入: {path}", exit_code=0)
                except Exception as retry_e:
                    return ExecutionResult(stderr=f"写文件失败: {retry_e}", exit_code=-1)

            logger.error("[sandbox] 写文件失败 %s: %s", path, e)
            return ExecutionResult(stderr=f"写文件失败: {e}", exit_code=-1)

    async def read_file(self, path: str) -> ExecutionResult:
        """从沙箱读取文件"""
        if not self.is_connected:
            await self.connect()

        logger.info("[sandbox] read_file: session=%s | path=%s", self._session_id, path)

        try:
            # 用 test -f 先检查 + cat 读取，通过 EXIT_CODE 判断是否成功
            content = await self._invoke_command(
                f"cat {shlex.quote(path)} 2>/dev/null && echo __READ_OK__ || echo __READ_FAIL__"
            )
            if '__READ_FAIL__' in content or 'No such file' in content:
                return ExecutionResult(stderr=f"文件不存在: {path}", exit_code=1)
            # 去掉尾部的 __READ_OK__ 标记
            content = content.replace('__READ_OK__', '').rstrip()
            return ExecutionResult(stdout=content, exit_code=0)
        except Exception as e:
            if self._is_session_expired(e):
                logger.warning("[sandbox] 读文件时会话过期，重建后重试: %s", path)
                await self._reconnect()
                try:
                    content = await self._invoke_command(f"cat {shlex.quote(path)}")
                    return ExecutionResult(stdout=content, exit_code=0)
                except Exception as retry_e:
                    return ExecutionResult(stderr=f"读文件失败: {retry_e}", exit_code=-1)

            error_msg = str(e)
            if "No such file" in error_msg or "not found" in error_msg.lower():
                return ExecutionResult(stderr=f"文件不存在: {path}", exit_code=1)
            logger.error("[sandbox] 读文件失败 %s: %s", path, e)
            return ExecutionResult(stderr=f"读文件失败: {error_msg}", exit_code=-1)

    async def file_exists(self, path: str) -> bool:
        """检查文件是否存在"""
        if not self.is_connected:
            await self.connect()
        try:
            result = await self._invoke_command(
                f"test -e {shlex.quote(path)} && echo yes || echo no"
            )
            return result.strip() == "yes"
        except Exception:
            return False

    # ═══════════════════════════════════════════════════════
    # 内部：AgentCore SDK 调用
    # ═══════════════════════════════════════════════════════

    async def _invoke_command(self, command: str) -> str:
        result = await asyncio.to_thread(
            self._ci.invoke, "executeCommand", {"command": command}
        )
        return self._extract_text(result)

    async def _invoke_code(self, language: str, code: str) -> str:
        result = await asyncio.to_thread(
            self._ci.invoke, "executeCode", {"language": language, "code": code}
        )
        return self._extract_text(result)

    @staticmethod
    def _extract_text(response: dict) -> str:
        parts = []
        for ev in response.get("stream", []):
            for c in ev.get("result", {}).get("content", []):
                if c.get("type") == "text":
                    parts.append(c["text"])
        return "\n".join(parts)

    # ═══════════════════════════════════════════════════════
    # 内部：会话管理
    # ═══════════════════════════════════════════════════════

    def _is_session_expired(self, error: Exception) -> bool:
        error_str = str(error).lower()
        return any(kw in error_str for kw in (
            "session not found", "session expired", "not found",
            "resourcenotfoundexception", "already stopped",
            "session is not active", "connection refused",
        ))

    async def _reconnect(self) -> None:
        """会话过期重建（S3 数据自动恢复）"""
        logger.info("[sandbox] 会话过期 (id=%s)，重建中...", self._session_id)
        self._ci = None
        self._session_id = None
        self._connected = False
        self._sync_manager = None
        await self.connect()
        logger.info("[sandbox] 重建完成: id=%s", self._session_id)

    def _build_s3_prefix(
        self, tenant_id: str | None, user_id: str | None, session_id: str | None
    ) -> str:
        """构建 S3 路径前缀（对齐腾讯 COS user/{user_id}/conversation/{conv_id}）"""
        parts = [self._aws_config.sync_prefix]
        if tenant_id:
            parts.append(tenant_id)
        if user_id:
            parts.append(user_id)
        if session_id:
            parts.append(session_id)
        else:
            parts.append("default")
        return "/".join(parts)

    # ═══════════════════════════════════════════════════════
    # 内部：身份上下文
    # ═══════════════════════════════════════════════════════

    def _get_session_id(self) -> str | None:
        try:
            from src.core.context import get_context
            return get_context().thread_id
        except Exception:
            return None

    def _get_tenant_id(self) -> str | None:
        try:
            from src.core.context import get_context
            return str(get_context().tenant_id) if get_context().tenant_id else None
        except Exception:
            return None

    def _get_user_id(self) -> str | None:
        try:
            from src.core.context import get_context
            return str(get_context().user_id) if get_context().user_id else None
        except Exception:
            return None

    # ═══════════════════════════════════════════════════════
    # 内部：DB 持久化
    # ═══════════════════════════════════════════════════════

    def _save_session_id_to_db(self, ci_session_id: str) -> None:
        try:
            from src.core.context import get_context
            ctx = get_context()
            thread_id = ctx.thread_id
            tenant_id = ctx.tenant_id
            if not thread_id:
                return

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
                    existing = json.loads(row[0]) if row[0] and isinstance(row[0], str) else (row[0] or {})
                    existing["sandbox_id"] = ci_session_id
                    existing["sandbox_backend"] = "aws"
                    cur.execute(
                        "UPDATE ai_conversation SET ext_info=%s, updated_at=%s "
                        "WHERE tenant_id=%s AND thread_id=%s AND delete_flg=0",
                        (json.dumps(existing, ensure_ascii=False), now, tenant_id, thread_id),
                    )
                else:
                    self._pending_save_thread_id = thread_id
                    self._pending_save_tenant_id = tenant_id
        except Exception as e:
            logger.warning("[sandbox] DB 保存失败 (non-fatal): %s", e)

    def _retry_save_session_id(self) -> None:
        thread_id = getattr(self, '_pending_save_thread_id', None)
        tenant_id = getattr(self, '_pending_save_tenant_id', None)
        if not thread_id or not self._session_id:
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
                    existing = json.loads(row[0]) if row[0] and isinstance(row[0], str) else (row[0] or {})
                    existing["sandbox_id"] = self._session_id
                    existing["sandbox_backend"] = "aws"
                    cur.execute(
                        "UPDATE ai_conversation SET ext_info=%s, updated_at=%s "
                        "WHERE tenant_id=%s AND thread_id=%s AND delete_flg=0",
                        (json.dumps(existing, ensure_ascii=False), now, tenant_id, thread_id),
                    )
                    self._pending_save_thread_id = None
                    self._pending_save_tenant_id = None
        except Exception:
            pass

    # ═══════════════════════════════════════════════════════
    # 内部：预置文件
    # ═══════════════════════════════════════════════════════

    async def _init_preset_files(self) -> None:
        for path, content in self._get_preset_files().items():
            try:
                write_code = (
                    f"import os\n"
                    f"os.makedirs(os.path.dirname({path!r}) or '.', exist_ok=True)\n"
                    f"with open({path!r}, 'w') as f:\n"
                    f"    f.write({content!r})\n"
                )
                await self._invoke_code("python", write_code)
            except Exception as e:
                logger.warning("[sandbox] 预置文件写入失败: %s -> %s", path, e)

    def _get_preset_files(self) -> dict[str, str]:
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


# ═══════════════════════════════════════════════════════
# 工厂方法
# ═══════════════════════════════════════════════════════

def create_aws_backend_from_env(config_dict: dict[str, str] | None = None) -> AWSAgentCoreSandboxBackend:
    """从配置创建 AWS AgentCore 沙箱 Backend"""
    import os

    def _get(key: str, default: str = "") -> str:
        if config_dict:
            return config_dict.get(key, default)
        return os.environ.get(key, default)

    if not (_get("AWS_ACCESS_KEY_ID") or _get("AWS_PROFILE")):
        raise ValueError(
            "AWS 凭证未配置。请设置: AWS_ACCESS_KEY_ID + AWS_SECRET_ACCESS_KEY 或 AWS_PROFILE"
        )

    config = AWSAgentCoreConfig(
        region=_get("AWS_SANDBOX_REGION", "ap-southeast-1"),
        session_timeout=int(_get("AWS_SANDBOX_TIMEOUT", "3600")),
        max_output_chars=int(_get("SANDBOX_MAX_OUTPUT_CHARS", "50000")),
        working_dir=_get("SANDBOX_WORKING_DIR", "/tmp/sandbox"),
        sync_bucket=_get("AWS_SANDBOX_SYNC_BUCKET", ""),
        sync_prefix=_get("AWS_SANDBOX_SYNC_PREFIX", "sandbox"),
        sync_interval=int(_get("AWS_SANDBOX_SYNC_INTERVAL", "5")),
        network_mode=_get("AWS_SANDBOX_NETWORK_MODE", "PUBLIC"),
    )

    return AWSAgentCoreSandboxBackend(config)
