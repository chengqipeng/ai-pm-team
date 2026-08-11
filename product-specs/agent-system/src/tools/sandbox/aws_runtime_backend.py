"""
AWS Agent Runtime Sandbox Backend — 通过 Bedrock AgentCore Runtime (invoke_agent_runtime) 执行命令

与 aws_agentcore_backend.py (Code Interpreter) 的区别：
  - CI: 使用平台内置沙箱 (aws.codeinterpreter.v1)，免部署免镜像
  - Runtime: 使用自定义容器镜像 (agentcore-sandbox:v8)，有 EFS 持久化

特性:
  - 通过 invoke_agent_runtime 调用自定义 handler (exec/read/write/info)
  - EFS 持久化存储（写入即持久，跨 session 存活，14 天保留）
  - 会话级复用（runtimeSessionId → 同一 microVM）
  - 用户隔离（user_id → EFS 子目录 NFS 挂载）
  - 会话过期自动恢复（再次 invoke 同 sessionId 自动拉新 VM + 挂回 EFS）
  - 兼容 Backend 抽象接口，Tool 层零改动

依赖:
  pip install boto3

对齐腾讯版行为（上层使用方零感知）:
  - connect() = 首次 invoke 隐式创建 microVM（冷启动 ~27s）
  - disconnect(force_kill=False) = 无需操作（EFS 自动持久化，无需 sync）
  - disconnect(force_kill=True) = stop_runtime_session
  - write_file = handler action=write（直接写 EFS，天然持久化）
  - execute = handler action=exec
  - read_file = handler action=read

与腾讯版的核心差异:
  - 无 pause/resume（无此 API）
  - 冷启动 ~27s（腾讯 3~5s）
  - EFS 天然持久化（无需 S3 sync）
  - 不同 user_id 通过 NFS 挂载隔离（非 COS subPath）
"""
from __future__ import annotations

import asyncio
import json
import logging
import shlex
import uuid
from dataclasses import dataclass
from typing import Any

from .backend_base import Backend, BackendConfig, ExecutionResult

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


@dataclass
class AWSRuntimeConfig:
    """AWS Agent Runtime 沙箱后端配置"""
    region: str = "ap-southeast-1"
    runtime_arn: str = ""                    # Runtime ARN（直传，免 List 权限）
    runtime_name: str = ""                   # Runtime 名字（需 ListAgentRuntimes 权限）
    timeout: int = 60                        # 单命令超时（1~300s）
    max_output_chars: int = 50000            # 输出截断阈值
    working_dir: str = "/sandbox/.skills"    # 沙箱工作目录（handler 固定路径）
    aws_access_key_id: str = ""              # 可选 AKSK（留空走默认凭证链）
    aws_secret_access_key: str = ""


class AWSRuntimeSandboxBackend(Backend):
    """AWS Bedrock AgentCore Runtime 沙箱后端

    通过 invoke_agent_runtime 调用自定义容器内 handler 执行命令、读写文件。
    EFS 持久化存储提供天然持久化能力，无需额外 S3 sync。

    隔离策略:
      - microVM 级隔离（不同 runtimeSessionId → 不同 VM）
      - EFS 子目录隔离（不同 user_id → handler 通过 NFS 挂载到不同目录）

    数据持久化策略（对齐腾讯 COS 挂载语义）:
      - write_file → 直接写 EFS，天然持久化（等价于 COS 写入即落盘）
      - execute → 命令产出在 EFS 工作目录下，天然持久化
      - disconnect → EFS 数据自动保留 14 天，无需额外操作
      - connect → 同 user_id 自动挂回 EFS 子目录（历史数据立即可见）
    """

    def __init__(self, config: AWSRuntimeConfig):
        backend_config = BackendConfig(
            backend_type="aws_runtime",
            timeout=config.timeout,
            working_dir=config.working_dir,
            max_output_chars=config.max_output_chars,
        )
        super().__init__(backend_config)
        self._runtime_config = config
        self._client = None
        self._runtime_arn: str | None = None
        self._session_id: str | None = None
        self._user_id: str | None = None
        self._connected = False

    @property
    def is_connected(self) -> bool:
        return self._connected

    @property
    def session_id(self) -> str | None:
        return self._session_id

    # ═══════════════════════════════════════════════════════
    # Backend 接口实现
    # ═══════════════════════════════════════════════════════

    async def connect(self, session_id: str | None = None) -> None:
        """建立连接 — 确定 ARN + 生成 sessionId + 首次 invoke 拉起 microVM

        首次 invoke 即隐式创建 microVM（冷启动 ~27s）。
        后续调用复用同一 microVM（热调用 ~260ms）。
        """
        if self._connected:
            return

        import boto3

        # 构建 boto3 client
        kwargs = {"region_name": self._runtime_config.region}
        if self._runtime_config.aws_access_key_id:
            kwargs["aws_access_key_id"] = self._runtime_config.aws_access_key_id
            kwargs["aws_secret_access_key"] = self._runtime_config.aws_secret_access_key

        self._client = boto3.client("bedrock-agentcore", **kwargs)

        # 确定 Runtime ARN
        if self._runtime_config.runtime_arn:
            self._runtime_arn = self._runtime_config.runtime_arn
        elif self._runtime_config.runtime_name:
            self._runtime_arn = await asyncio.to_thread(
                self._get_runtime_arn, self._runtime_config.runtime_name
            )
        else:
            raise ValueError("必须配置 AWS_RUNTIME_ARN 或 AWS_RUNTIME_NAME")

        # 确定 session_id（runtimeSessionId，>= 33 字符）
        self._session_id = session_id or self._generate_session_id()

        # 确定 user_id（EFS 子目录名，业务映射: tenant_user_conv）
        self._user_id = self._build_user_id()

        logger.info(
            "[sandbox] 后端=AWSRuntime | arn=%s | session=%s | user=%s",
            self._runtime_arn, self._session_id[:30] + "...", self._user_id,
        )

        # 首次 invoke（触发 microVM 创建 + EFS 挂载）
        try:
            result = await self._invoke("info", {})
            self._connected = True
            logger.info(
                "[sandbox] 连接成功: workspace=%s",
                result.get("workspace", "unknown"),
            )
        except Exception as e:
            logger.error("[sandbox] 连接失败: %s", e)
            raise

    async def disconnect(self, force_kill: bool = False) -> None:
        """断开连接

        force_kill=False: 无操作（EFS 天然持久化，session Idle 后自动回收）
        force_kill=True: 调用 stop_runtime_session 立即终止

        注意：即使 force_kill，EFS 数据仍保留 14 天。
        """
        if not self._connected:
            return

        if force_kill and self._client and self._runtime_arn and self._session_id:
            try:
                await asyncio.to_thread(
                    self._client.stop_runtime_session,
                    agentRuntimeArn=self._runtime_arn,
                    runtimeSessionId=self._session_id,
                )
                logger.info("[sandbox] session 已 stop: %s", self._session_id)
            except Exception as e:
                logger.warning("[sandbox] stop_runtime_session 失败 (non-fatal): %s", e)
        else:
            logger.info(
                "[sandbox] 断开连接（不终止 session，等待 Idle 自动回收）: %s",
                self._session_id,
            )

        self._connected = False

    async def execute(self, command: str, timeout: int | None = None) -> ExecutionResult:
        """在沙箱中执行命令"""
        if not self.is_connected:
            await self.connect()

        effective_timeout = min(timeout or self._runtime_config.timeout, 300)

        logger.info("[sandbox] execute: cmd=%s", command[:100])

        try:
            result = await self._invoke("exec", {
                "command": command,
                "timeout": effective_timeout,
            })

            if result.get("status") != "ok":
                return ExecutionResult(
                    stdout="",
                    stderr=result.get("error", result.get("message", str(result))),
                    exit_code=result.get("exit_code", -1),
                )

            stdout = result.get("stdout", "")
            stderr = result.get("stderr", "")

            # 输出截断
            if len(stdout) > self.config.max_output_chars:
                keep_head = int(self.config.max_output_chars * 0.4)
                keep_tail = int(self.config.max_output_chars * 0.6)
                stdout = stdout[:keep_head] + "\n\n[OUTPUT TRUNCATED]\n\n" + stdout[-keep_tail:]

            return ExecutionResult(
                stdout=stdout,
                stderr=stderr,
                exit_code=result.get("exit_code", 0),
            )

        except Exception as e:
            if self._is_session_expired(e):
                logger.warning("[sandbox] session 过期，重建...")
                await self._reconnect()
                return await self.execute(command, timeout)

            logger.error("[sandbox] execute 失败: %s", e)
            return ExecutionResult(stdout="", stderr=f"执行失败: {e}", exit_code=-1)

    async def write_file(self, path: str, content: str) -> ExecutionResult:
        """写文件到沙箱（直接写 EFS，天然持久化）"""
        if not self.is_connected:
            await self.connect()

        # handler 要求相对路径（相对于 /sandbox/.skills）
        rel_path = self._to_relative_path(path)
        logger.info("[sandbox] write_file: path=%s (rel=%s) size=%d", path, rel_path, len(content))

        try:
            result = await self._invoke("write", {"path": rel_path, "content": content})

            if result.get("status") == "ok":
                return ExecutionResult(stdout=f"已写入: {path}", exit_code=0)
            else:
                return ExecutionResult(
                    stderr=f"写文件失败: {result.get('error', result.get('message', str(result)))}",
                    exit_code=-1,
                )
        except Exception as e:
            if self._is_session_expired(e):
                await self._reconnect()
                return await self.write_file(path, content)
            logger.error("[sandbox] write_file 失败: %s", e)
            return ExecutionResult(stderr=f"写文件失败: {e}", exit_code=-1)

    async def read_file(self, path: str) -> ExecutionResult:
        """从沙箱读取文件"""
        if not self.is_connected:
            await self.connect()

        # handler 要求相对路径
        rel_path = self._to_relative_path(path)
        logger.info("[sandbox] read_file: path=%s (rel=%s)", path, rel_path)

        try:
            result = await self._invoke("read", {"path": rel_path})

            if result.get("status") == "ok":
                return ExecutionResult(stdout=result.get("content", ""), exit_code=0)
            else:
                msg = result.get("error", result.get("message", ""))
                return ExecutionResult(stderr=f"读文件失败: {msg}", exit_code=1)
        except Exception as e:
            if self._is_session_expired(e):
                await self._reconnect()
                return await self.read_file(path)
            logger.error("[sandbox] read_file 失败: %s", e)
            return ExecutionResult(stderr=f"读文件失败: {e}", exit_code=-1)

    async def file_exists(self, path: str) -> bool:
        """检查文件是否存在"""
        if not self.is_connected:
            await self.connect()
        try:
            result = await self._invoke("exec", {
                "command": f"test -e {shlex.quote(path)} && echo yes || echo no",
                "timeout": 10,
            })
            return result.get("stdout", "").strip() == "yes"
        except Exception:
            return False

    # ═══════════════════════════════════════════════════════
    # 内部：invoke_agent_runtime 调用
    # ═══════════════════════════════════════════════════════

    async def _invoke(self, action: str, params: dict) -> dict:
        """调用 handler，返回 JSON 响应"""
        payload = json.dumps({
            "user_id": self._user_id,
            "action": action,
            "params": params,
        }).encode()

        resp = await asyncio.to_thread(
            self._client.invoke_agent_runtime,
            agentRuntimeArn=self._runtime_arn,
            runtimeSessionId=self._session_id,
            payload=payload,
        )
        return json.loads(resp["response"].read())

    # ═══════════════════════════════════════════════════════
    # 内部：会话管理
    # ═══════════════════════════════════════════════════════

    def _get_runtime_arn(self, name: str) -> str:
        """按名字查 ARN"""
        import boto3
        kwargs = {"region_name": self._runtime_config.region}
        if self._runtime_config.aws_access_key_id:
            kwargs["aws_access_key_id"] = self._runtime_config.aws_access_key_id
            kwargs["aws_secret_access_key"] = self._runtime_config.aws_secret_access_key

        client = boto3.client("bedrock-agentcore-control", **kwargs)
        paginator = client.get_paginator("list_agent_runtimes")
        for page in paginator.paginate(PaginationConfig={"PageSize": 100}):
            for rt in page.get("agentRuntimes", []):
                if rt["agentRuntimeName"] == name:
                    return rt["agentRuntimeArn"]
        raise LookupError(f"找不到 Runtime: {name}")

    def _generate_session_id(self) -> str:
        """生成 runtimeSessionId（>= 33 字符）"""
        # 优先从业务上下文获取（保证同一对话复用同一 session）
        context_id = self._get_context_session_id()
        if context_id and len(context_id) >= 33:
            return context_id
        # 不够长时用 UUID
        return str(uuid.uuid4())

    def _build_user_id(self) -> str:
        """构建 user_id（EFS 目录名）: tenant_user_conv 三级组合"""
        try:
            from src.core.context import get_context
            ctx = get_context()
            parts = []
            if ctx.tenant_id:
                parts.append(f"t{ctx.tenant_id}")
            if ctx.user_id:
                parts.append(f"u{ctx.user_id}")
            if ctx.thread_id:
                # thread_id 可能含特殊字符，取前 20 字符
                parts.append(ctx.thread_id[:20])
            if parts:
                return "_".join(parts)
        except Exception:
            pass
        return "default"

    def _get_context_session_id(self) -> str | None:
        """从业务上下文获取 thread_id 作为 session 标识"""
        try:
            from src.core.context import get_context
            return get_context().thread_id
        except Exception:
            return None

    def _is_session_expired(self, error: Exception) -> bool:
        """判断是否为 session 过期错误"""
        error_str = str(error).lower()
        return any(kw in error_str for kw in (
            "session not found", "not found", "resourcenotfoundexception",
            "session is not active", "connection refused", "retryableconflict",
        ))

    def _to_relative_path(self, path: str) -> str:
        """将绝对路径转为相对于工作目录的相对路径

        handler 要求 read/write 的 path 为相对路径（相对于 /sandbox/.skills）。
        如果传入绝对路径，自动去掉工作目录前缀。
        """
        work_dir = self._runtime_config.working_dir.rstrip("/")
        if path.startswith(work_dir + "/"):
            return path[len(work_dir) + 1:]
        if path.startswith("/"):
            # 其他绝对路径，去掉开头的 /
            return path.lstrip("/")
        return path

    async def _reconnect(self) -> None:
        """session 过期后重建（EFS 数据自动恢复）"""
        logger.info("[sandbox] 重建连接: session=%s", self._session_id)
        self._connected = False
        # 保留 session_id 和 user_id（EFS 数据与这两个关联）
        await self.connect(session_id=self._session_id)


# ═══════════════════════════════════════════════════════
# 工厂方法
# ═══════════════════════════════════════════════════════

def create_aws_runtime_backend_from_env(
    config_dict: dict[str, str] | None = None,
) -> AWSRuntimeSandboxBackend:
    """从配置创建 AWS Runtime 沙箱 Backend

    .env 配置项:
      AWS_RUNTIME_ARN          — Runtime ARN（推荐，免 List 权限）
      AWS_RUNTIME_NAME         — Runtime 名字（需 ListAgentRuntimes 权限）
      AWS_RUNTIME_REGION       — 区域（默认 ap-southeast-1）
      AWS_RUNTIME_TIMEOUT      — 单命令超时秒数（默认 60，最大 300）
      AWS_ACCESS_KEY_ID        — 可选 AKSK
      AWS_SECRET_ACCESS_KEY    — 可选 AKSK
      SANDBOX_MAX_OUTPUT_CHARS — 输出截断（默认 50000）
    """
    import os

    def _get(key: str, default: str = "") -> str:
        if config_dict:
            return config_dict.get(key, default)
        return os.environ.get(key, default)

    runtime_arn = _get("AWS_RUNTIME_ARN")
    runtime_name = _get("AWS_RUNTIME_NAME")

    if not runtime_arn and not runtime_name:
        raise ValueError(
            "AWS Runtime 未配置。请在 .env 中设置: "
            "AWS_RUNTIME_ARN=arn:aws:bedrock-agentcore:... 或 AWS_RUNTIME_NAME=test_runtime"
        )

    config = AWSRuntimeConfig(
        region=_get("AWS_RUNTIME_REGION", "ap-southeast-1"),
        runtime_arn=runtime_arn,
        runtime_name=runtime_name,
        timeout=int(_get("AWS_RUNTIME_TIMEOUT", "60")),
        max_output_chars=int(_get("SANDBOX_MAX_OUTPUT_CHARS", "50000")),
        working_dir=_get("SANDBOX_WORKING_DIR", "/sandbox/.skills"),
        aws_access_key_id=_get("AWS_ACCESS_KEY_ID"),
        aws_secret_access_key=_get("AWS_SECRET_ACCESS_KEY"),
    )

    return AWSRuntimeSandboxBackend(config)
