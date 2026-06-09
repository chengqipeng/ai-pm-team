#!/usr/bin/env python3
"""Script to write the updated tencent_sandbox_backend.py"""
import os

TARGET = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tencent_sandbox_backend.py")

CONTENT = '''\
"""
Tencent Sandbox Backend \u2014 \u901a\u8fc7\u817e\u8baf\u4e91 Agent Runtime (E2B SDK) \u6267\u884c\u547d\u4ee4

\u7279\u6027:
  - \u6309\u9700\u521b\u5efa\u6c99\u7bb1\u5b9e\u4f8b\uff0c\u5929\u7136\u591a\u79df\u6237\u9694\u79bb
  - \u4f1a\u8bdd\u7ea7\u6c99\u7bb1\u590d\u7528\uff08sandbox_id \u6301\u4e45\u5316\u5230 ai_conversation.ext_info\uff09
  - \u901a\u8fc7 metadata.x-mounts.subPath \u5b9e\u73b0\u4f1a\u8bdd\u7ea7 COS \u6570\u636e\u9694\u79bb
  - \u652f\u6301\u6682\u505c/\u6062\u590d\uff08\u964d\u4f4e\u6210\u672c\uff0c\u4fdd\u7559\u72b6\u6001\uff09
  - \u6c99\u7bb1\u8fc7\u671f\u81ea\u52a8\u91cd\u5efa
  - \u517c\u5bb9 Backend \u62bd\u8c61\u63a5\u53e3\uff0cTool \u5c42\u96f6\u6539\u52a8
  - \u901a\u8fc7 asyncio.to_thread \u5305\u88c5\u540c\u6b65 E2B SDK

\u4f9d\u8d56:
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
    """\u817e\u8baf\u4e91\u6c99\u7bb1\u540e\u7aef\u914d\u7f6e"""
    e2b_domain: str = "ap-beijing.tencentags.com"
    e2b_api_key: str = ""
    template: str = "code-sandbox"
    timeout: int = 3600              # \u6c99\u7bb1\u5b58\u6d3b\u65f6\u95f4\uff08\u79d2\uff09
    max_output_chars: int = 50000    # \u8f93\u51fa\u622a\u65ad\u9608\u503c
    working_dir: str = "/home/user"  # \u9ed8\u8ba4\u5de5\u4f5c\u76ee\u5f55
    mount_name: str = "cos-aitools"  # COS \u6302\u8f7d\u540d\u79f0


class TencentSandboxBackend(Backend):
    """\u817e\u8baf\u4e91 Agent Runtime \u6c99\u7bb1\u540e\u7aef

    \u901a\u8fc7 E2B \u517c\u5bb9 SDK \u5728\u817e\u8baf\u4e91\u6c99\u7bb1\u4e2d\u6267\u884c\u547d\u4ee4\u3001\u8bfb\u5199\u6587\u4ef6\u3002
    \u6c99\u7bb1\u751f\u547d\u5468\u671f: connect() \u521b\u5efa \u2192 \u4f7f\u7528 \u2192 disconnect() \u9500\u6bc1/\u6682\u505c

    \u6570\u636e\u9694\u79bb\u7b56\u7565:
      \u521b\u5efa\u6c99\u7bb1\u65f6\u901a\u8fc7 metadata \u4e2d\u7684 x-mounts.subPath \u6307\u5b9a\u4f1a\u8bdd\u7ea7\u5b50\u76ee\u5f55\uff0c
      \u6bcf\u4e2a\u4f1a\u8bdd\u7684 /sandbox \u6302\u8f7d\u70b9\u6307\u5411 COS \u7684\u72ec\u7acb\u8def\u5f84\uff0c\u4e92\u4e0d\u53ef\u89c1\u3002
    """

    def __init__(self, config: TencentSandboxConfig):
        # \u6784\u9020\u4e00\u4e2a BackendConfig \u4f20\u7ed9\u7236\u7c7b\uff08\u4fdd\u6301\u63a5\u53e3\u517c\u5bb9\uff09
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
        """\u5f53\u524d\u6c99\u7bb1\u5b9e\u4f8b ID\uff08\u53ef\u7528\u4e8e\u6301\u4e45\u5316\u5230 session\uff09"""
        return self._sandbox_id

    @property
    def api_base_url(self) -> str:
        """E2B \u517c\u5bb9 API \u7684\u57fa\u7840\u5730\u5740"""
        return f"https://api.{self._tencent_config.e2b_domain}"

    async def connect(self, sandbox_id: str | None = None, session_id: str | None = None) -> None:
        """\u521b\u5efa\u6216\u6062\u590d\u6c99\u7bb1\u5b9e\u4f8b\uff08\u4f1a\u8bdd\u7ea7\u590d\u7528 + SubPath \u6570\u636e\u9694\u79bb\uff09

        \u4f18\u5148\u7ea7:
          1. \u5982\u679c\u5f53\u524d\u5df2\u8fde\u63a5\uff0c\u76f4\u63a5\u8fd4\u56de
          2. \u4ece ai_conversation.ext_info \u8bfb\u53d6\u8be5\u4f1a\u8bdd\u7ed1\u5b9a\u7684 sandbox_id
          3. \u5982\u679c\u5b58\u5728\uff0c\u5c1d\u8bd5\u6062\u590d\uff08connect\uff09\uff1b\u5982\u679c\u6c99\u7bb1\u5df2\u8fc7\u671f\u5219\u91cd\u5efa
          4. \u5982\u679c\u4e0d\u5b58\u5728\uff0c\u521b\u5efa\u65b0\u6c99\u7bb1\u5e76\u5c06 sandbox_id \u5199\u5165 ai_conversation

        \u521b\u5efa\u6c99\u7bb1\u65f6\u901a\u8fc7 metadata.x-mounts \u7684 subPath \u5b9e\u73b0\u4f1a\u8bdd\u7ea7\u6570\u636e\u9694\u79bb\uff0c
        \u6bcf\u4e2a\u4f1a\u8bdd\u7684\u6301\u4e45\u5316\u6587\u4ef6\u5b58\u50a8\u5728 COS \u7684\u72ec\u7acb\u5b50\u76ee\u5f55\u4e2d\uff08data/{session_id}\uff09\u3002

        Args:
            sandbox_id: \u663e\u5f0f\u6307\u5b9a\u6c99\u7bb1 ID\uff08\u4f18\u5148\u7ea7\u6700\u9ad8\uff0c\u8df3\u8fc7\u6570\u636e\u5e93\u67e5\u8be2\uff09
            session_id: \u4f1a\u8bdd ID\uff0c\u7528\u4e8e subPath \u9694\u79bb\u3002\u4e0d\u4f20\u5219\u81ea\u52a8\u4ece context \u83b7\u53d6 thread_id\u3002
        """
        if self._connected and self._sandbox is not None:
            return

        self._setup_env()

        from e2b import Sandbox

        logger.info(
            "[sandbox] \u540e\u7aef\u7c7b\u578b=TencentSandbox | API=%s | template=%s",
            self.api_base_url, self._tencent_config.template,
        )

        # \u786e\u5b9a session_id\uff08\u7528\u4e8e subPath \u9694\u79bb\uff09
        if not session_id:
            session_id = self._get_session_id()

        # \u5982\u679c\u6ca1\u6709\u663e\u5f0f\u4f20\u5165 sandbox_id\uff0c\u4ece\u6570\u636e\u5e93\u52a0\u8f7d
        if not sandbox_id:
            sandbox_id = self._load_sandbox_id_from_db()

        if sandbox_id:
            # \u5c1d\u8bd5\u6062\u590d\u5df2\u6709\u6c99\u7bb1
            try:
                logger.info("[sandbox] \u6062\u590d\u6c99\u7bb1: POST %s/sandboxes/%s/resume", self.api_base_url, sandbox_id)
                self._sandbox = await asyncio.to_thread(
                    Sandbox.connect, sandbox_id
                )
                self._sandbox_id = sandbox_id
                self._connected = True
                logger.info(
                    "[sandbox] \u6c99\u7bb1\u5df2\u6062\u590d: id=%s, template=%s",
                    sandbox_id, self._tencent_config.template,
                )
                return
            except Exception as e:
                logger.warning("[sandbox] \u6062\u590d\u6c99\u7bb1\u5931\u8d25 (id=%s): %s\uff0c\u6c99\u7bb1\u53ef\u80fd\u5df2\u8fc7\u671f\uff0c\u5c06\u521b\u5efa\u65b0\u6c99\u7bb1", sandbox_id, e)

        # \u6784\u5efa metadata\uff08\u542b subPath \u4f1a\u8bdd\u9694\u79bb\uff09
        metadata = self._build_sandbox_metadata(session_id)

        # \u521b\u5efa\u65b0\u6c99\u7bb1
        logger.info(
            "[sandbox] \u521b\u5efa\u6c99\u7bb1: POST %s/sandboxes {template=%s, timeout=%d, subPath=data/%s}",
            self.api_base_url, self._tencent_config.template,
            self._tencent_config.timeout, session_id or "none",
        )
        self._sandbox = await asyncio.to_thread(
            Sandbox.create,
            template=self._tencent_config.template,
            timeout=self._tencent_config.timeout,
            metadata=metadata,
        )
        self._sandbox_id = self._sandbox.sandbox_id
        self._connected = True
        logger.info(
            "[sandbox] \u6c99\u7bb1\u5df2\u521b\u5efa: id=%s, template=%s, timeout=%ds, session=%s",
            self._sandbox_id,
            self._tencent_config.template,
            self._tencent_config.timeout,
            session_id or "none",
        )

        # \u6301\u4e45\u5316 sandbox_id \u5230\u6570\u636e\u5e93
        self._save_sandbox_id_to_db(self._sandbox_id)

        # \u521d\u59cb\u5316\u9884\u7f6e\u6587\u4ef6
        await self._init_preset_files()

    async def disconnect(self, force_kill: bool = False) -> None:
        """\u65ad\u5f00\u6c99\u7bb1\u8fde\u63a5

        Args:
            force_kill: True=\u9500\u6bc1\u6c99\u7bb1, False=\u6682\u505c\u6c99\u7bb1\uff08\u4fdd\u7559\u72b6\u6001\uff09
        """
        if not self._connected or self._sandbox is None:
            return

        try:
            if force_kill:
                logger.info("[sandbox] \u9500\u6bc1\u6c99\u7bb1: DELETE %s/sandboxes/%s", self.api_base_url, self._sandbox_id)
                await asyncio.to_thread(self._sandbox.kill)
                logger.info("[sandbox] \u6c99\u7bb1\u5df2\u9500\u6bc1: id=%s", self._sandbox_id)
                self._sandbox_id = None
            else:
                try:
                    logger.info("[sandbox] \u6682\u505c\u6c99\u7bb1: POST %s/sandboxes/%s/pause", self.api_base_url, self._sandbox_id)
                    await asyncio.to_thread(self._sandbox.pause)
                    logger.info("[sandbox] \u6c99\u7bb1\u5df2\u6682\u505c: id=%s", self._sandbox_id)
                except Exception as e:
                    # pause \u4e0d\u652f\u6301\u65f6\u76f4\u63a5 kill
                    logger.warning("[sandbox] \u6682\u505c\u5931\u8d25\uff0c\u6267\u884c\u9500\u6bc1: %s", e)
                    await asyncio.to_thread(self._sandbox.kill)
                    self._sandbox_id = None
        except Exception as e:
            logger.error("[sandbox] \u65ad\u5f00\u6c99\u7bb1\u5931\u8d25: %s", e)
        finally:
            self._sandbox = None
            self._connected = False

    async def execute(self, command: str, timeout: int | None = None) -> ExecutionResult:
        """\u5728\u6c99\u7bb1\u4e2d\u6267\u884c Shell \u547d\u4ee4"""
        if not self.is_connected:
            await self.connect()

        # \u5982\u679c\u6709\u5f85\u4fdd\u5b58\u7684 sandbox_id\uff08\u4f1a\u8bdd\u8bb0\u5f55\u5ef6\u8fdf\u521b\u5efa\uff09\uff0c\u5c1d\u8bd5\u91cd\u8bd5
        if getattr(self, '_pending_save_thread_id', None):
            self._retry_save_sandbox_id()

        effective_timeout = timeout or self.config.timeout

        # \u5982\u679c\u6709\u5de5\u4f5c\u76ee\u5f55\uff0c\u5148 cd
        if self.config.working_dir:
            command = f"cd {shlex.quote(self.config.working_dir)} 2>/dev/null; {command}"

        logger.info("[sandbox] \u6267\u884c\u547d\u4ee4: POST %s/sandboxes/%s/commands | cmd=%s",
                    self.api_base_url, self._sandbox_id, command[:100])

        try:
            result = await asyncio.to_thread(
                self._sandbox.commands.run, command
            )
            stdout = result.stdout or ""
            stderr = result.stderr or ""

            # \u8f93\u51fa\u622a\u65ad\u4fdd\u62a4
            if len(stdout) > self.config.max_output_chars:
                keep_head = int(self.config.max_output_chars * 0.4)
                keep_tail = int(self.config.max_output_chars * 0.6)
                stdout = (
                    stdout[:keep_head]
                    + "\\n\\n[OUTPUT TRUNCATED]\\n\\n"
                    + stdout[-keep_tail:]
                )

            return ExecutionResult(
                stdout=stdout,
                stderr=stderr,
                exit_code=result.exit_code if hasattr(result, 'exit_code') else 0,
            )

        except Exception as e:
            error_msg = str(e)
            # E2B SDK \u7684 CommandExitException \u5305\u542b exit code \u548c stderr
            if "CommandExitException" in type(e).__name__ or "exited with code" in error_msg:
                # \u89e3\u6790\u9000\u51fa\u7801
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
                    stderr=f"\u547d\u4ee4\u6267\u884c\u8d85\u65f6 ({effective_timeout}s)",
                    exit_code=-1,
                    timed_out=True,
                )

            logger.error("\u6c99\u7bb1\u547d\u4ee4\u6267\u884c\u5931\u8d25: %s", e)
            return ExecutionResult(
                stdout="",
                stderr=f"\u6c99\u7bb1\u6267\u884c\u9519\u8bef: {error_msg}",
                exit_code=-1,
            )

    async def write_file(self, path: str, content: str) -> ExecutionResult:
        """\u5199\u6587\u4ef6\u5230\u6c99\u7bb1"""
        if not self.is_connected:
            await self.connect()

        logger.info("[sandbox] \u5199\u6587\u4ef6: POST %s/sandboxes/%s/files | path=%s, size=%d",
                    self.api_base_url, self._sandbox_id, path, len(content))

        try:
            await asyncio.to_thread(self._sandbox.files.write, path, content)
            return ExecutionResult(stdout=f"\u5df2\u5199\u5165: {path}", exit_code=0)
        except Exception as e:
            logger.error("[sandbox] \u5199\u6587\u4ef6\u5931\u8d25 %s: %s", path, e)
            return ExecutionResult(
                stderr=f"\u5199\u6587\u4ef6\u5931\u8d25: {str(e)}",
                exit_code=-1,
            )

    async def read_file(self, path: str) -> ExecutionResult:
        """\u4ece\u6c99\u7bb1\u8bfb\u53d6\u6587\u4ef6"""
        if not self.is_connected:
            await self.connect()

        logger.info("[sandbox] \u8bfb\u6587\u4ef6: GET %s/sandboxes/%s/files | path=%s",
                    self.api_base_url, self._sandbox_id, path)

        try:
            content = await asyncio.to_thread(self._sandbox.files.read, path)
            return ExecutionResult(stdout=content, exit_code=0)
        except Exception as e:
            logger.error("[sandbox] \u8bfb\u6587\u4ef6\u5931\u8d25 %s: %s", path, e)
            return ExecutionResult(
                stderr=f"\u8bfb\u6587\u4ef6\u5931\u8d25: {str(e)}",
                exit_code=-1,
            )

    async def file_exists(self, path: str) -> bool:
        """\u68c0\u67e5\u6c99\u7bb1\u4e2d\u6587\u4ef6\u662f\u5426\u5b58\u5728"""
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

    # \u2500\u2500\u2500 \u817e\u8baf\u6c99\u7bb1\u7279\u6709\u65b9\u6cd5 \u2500\u2500\u2500

    async def pause(self) -> None:
        """\u6682\u505c\u6c99\u7bb1\uff08\u4fdd\u7559\u72b6\u6001\uff0c\u505c\u6b62\u8ba1\u8d39\uff09"""
        if self._sandbox is None:
            return
        await asyncio.to_thread(self._sandbox.pause)
        self._connected = False
        logger.info("\u817e\u8baf\u6c99\u7bb1\u5df2\u6682\u505c: id=%s", self._sandbox_id)

    async def resume(self) -> None:
        """\u6062\u590d\u5df2\u6682\u505c\u7684\u6c99\u7bb1"""
        if self._sandbox_id is None:
            raise RuntimeError("\u6ca1\u6709\u53ef\u6062\u590d\u7684\u6c99\u7bb1\uff08sandbox_id \u4e3a\u7a7a\uff09")
        await self.connect(sandbox_id=self._sandbox_id)

    def get_sandbox_url(self) -> str | None:
        """\u83b7\u53d6\u6c99\u7bb1 Web \u8bbf\u95ee\u5730\u5740\uff08\u5982\u679c\u662f All-In-One \u7c7b\u578b\uff09"""
        if self._sandbox is None:
            return None
        try:
            token = self._sandbox._envd_access_token
            host = self._sandbox.get_host(9000)
            return f"https://{host}/?access_token={token}"
        except Exception:
            return None

    # \u2500\u2500\u2500 \u5185\u90e8\u65b9\u6cd5 \u2500\u2500\u2500

    def _get_session_id(self) -> str | None:
        """\u83b7\u53d6\u5f53\u524d\u4f1a\u8bdd ID\uff08thread_id\uff09\uff0c\u7528\u4e8e subPath \u9694\u79bb

        Returns:
            \u4f1a\u8bdd ID \u5b57\u7b26\u4e32\uff0c\u83b7\u53d6\u5931\u8d25\u65f6\u8fd4\u56de None
        """
        try:
            from src.core.context import get_context
            ctx = get_context()
            session_id = ctx.thread_id
            if session_id:
                logger.debug("[sandbox] \u83b7\u53d6 session_id: %s", session_id)
            return session_id
        except Exception as e:
            logger.debug("[sandbox] \u83b7\u53d6 session_id \u5931\u8d25: %s", e)
            return None

    def _build_sandbox_metadata(self, session_id: str | None) -> dict[str, str]:
        """\u6784\u5efa\u6c99\u7bb1\u521b\u5efa\u65f6\u7684 metadata \u53c2\u6570

        \u901a\u8fc7 x-mounts \u7684 subPath \u5b57\u6bb5\u5b9e\u73b0\u4f1a\u8bdd\u7ea7 COS \u6570\u636e\u9694\u79bb\u3002
        \u53c2\u8003 test_sandbox_1.py \u4e2d\u7684 test_subpath_isolation() \u5b9e\u73b0\u3002

        Args:
            session_id: \u4f1a\u8bdd ID\uff0c\u7528\u4e8e\u6784\u9020 subPath\u3002\u4e3a None \u65f6\u4e0d\u6302\u8f7d\u9694\u79bb\u76ee\u5f55\u3002

        Returns:
            metadata \u5b57\u5178\uff0c\u4f9b Sandbox.create(metadata=...) \u4f7f\u7528
        """
        metadata = {}
        if session_id:
            metadata["x-mounts"] = json.dumps([{
                "name": self._tencent_config.mount_name,
                "subPath": f"data/{session_id}"
            }])
            logger.debug(
                "[sandbox] \u6784\u5efa metadata: mount=%s, subPath=data/%s",
                self._tencent_config.mount_name, session_id,
            )
        return metadata

    def _load_sandbox_id_from_db(self) -> str | None:
        """\u4ece ai_conversation.ext_info \u4e2d\u8bfb\u53d6\u5f53\u524d\u4f1a\u8bdd\u7ed1\u5b9a\u7684 sandbox_id"""
        try:
            from src.core.context import get_context
            ctx = get_context()
            thread_id = ctx.thread_id
            tenant_id = ctx.tenant_id

            if not thread_id:
                logger.debug("[sandbox] \u65e0 thread_id\uff0c\u8df3\u8fc7\u6570\u636e\u5e93\u67e5\u8be2")
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
                logger.info("[sandbox] \u4ece\u6570\u636e\u5e93\u52a0\u8f7d sandbox_id: thread=%s \u2192 sandbox=%s", thread_id, sandbox_id)

            return sandbox_id

        except Exception as e:
            logger.warning("[sandbox] \u4ece\u6570\u636e\u5e93\u52a0\u8f7d sandbox_id \u5931\u8d25 (non-fatal): %s", e)
            return None

    def _save_sandbox_id_to_db(self, sandbox_id: str) -> None:
        """\u5c06 sandbox_id \u5199\u5165 ai_conversation.ext_info\uff08JSON merge\uff09"""
        try:
            from src.core.context import get_context
            ctx = get_context()
            thread_id = ctx.thread_id
            tenant_id = ctx.tenant_id

            if not thread_id:
                logger.debug("[sandbox] \u65e0 thread_id\uff0c\u8df3\u8fc7\u6570\u636e\u5e93\u5199\u5165")
                return

            from src.store.pg_pool import get_conn
            import time

            now = int(time.time() * 1000)

            with get_conn() as conn:
                cur = conn.cursor()

                # \u8bfb\u53d6\u73b0\u6709 ext_info
                cur.execute(
                    "SELECT ext_info FROM ai_conversation "
                    "WHERE tenant_id=%s AND thread_id=%s AND delete_flg=0",
                    (tenant_id, thread_id),
                )
                row = cur.fetchone()

                if row:
                    # \u66f4\u65b0\u5df2\u6709\u8bb0\u5f55
                    existing = {}
                    if row[0]:
                        existing = json.loads(row[0]) if isinstance(row[0], str) else row[0]
                    existing["sandbox_id"] = sandbox_id
                    cur.execute(
                        "UPDATE ai_conversation SET ext_info=%s, updated_at=%s "
                        "WHERE tenant_id=%s AND thread_id=%s AND delete_flg=0",
                        (json.dumps(existing, ensure_ascii=False), now, tenant_id, thread_id),
                    )
                    logger.info("[sandbox] sandbox_id \u5df2\u4fdd\u5b58\u5230\u6570\u636e\u5e93: thread=%s \u2192 sandbox=%s", thread_id, sandbox_id)
                else:
                    # \u4f1a\u8bdd\u8bb0\u5f55\u5c1a\u672a\u521b\u5efa\uff08\u9996\u6b21\u5bf9\u8bdd\uff0cTraceWriter \u8fd8\u6ca1\u5199\u5165\uff09
                    # \u6682\u5b58\u5230\u5b9e\u4f8b\u53d8\u91cf\uff0c\u7b49\u4f1a\u8bdd\u8bb0\u5f55\u521b\u5efa\u540e\u518d\u5199\u5165
                    logger.info("[sandbox] \u4f1a\u8bdd\u8bb0\u5f55\u5c1a\u672a\u521b\u5efa\uff0csandbox_id \u6682\u5b58: thread=%s \u2192 sandbox=%s", thread_id, sandbox_id)
                    self._pending_save_thread_id = thread_id
                    self._pending_save_tenant_id = tenant_id

        except Exception as e:
            logger.warning("[sandbox] \u4fdd\u5b58 sandbox_id \u5230\u6570\u636e\u5e93\u5931\u8d25 (non-fatal): %s", e)

    def _retry_save_sandbox_id(self) -> None:
        """\u91cd\u8bd5\u4fdd\u5b58 sandbox_id\uff08\u7528\u4e8e\u4f1a\u8bdd\u8bb0\u5f55\u5ef6\u8fdf\u521b\u5efa\u7684\u573a\u666f\uff09"""
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
                    logger.info("[sandbox] sandbox_id \u5ef6\u8fdf\u4fdd\u5b58\u6210\u529f: thread=%s \u2192 sandbox=%s", thread_id, self._sandbox_id)
                    self._pending_save_thread_id = None
                    self._pending_save_tenant_id = None
        except Exception as e:
            logger.debug("[sandbox] \u5ef6\u8fdf\u4fdd\u5b58 sandbox_id \u91cd\u8bd5\u5931\u8d25: %s", e)

    async def _init_preset_files(self) -> None:
        """\u6c99\u7bb1\u521b\u5efa\u540e\u81ea\u52a8\u5199\u5165\u9884\u7f6e\u6587\u4ef6\uff08\u6d4b\u8bd5\u6570\u636e\u7b49\uff09"""
        preset_files = self._get_preset_files()
        if not preset_files:
            return

        for path, content in preset_files.items():
            try:
                await asyncio.to_thread(self._sandbox.files.write, path, content)
                logger.info("[sandbox] \u9884\u7f6e\u6587\u4ef6\u5df2\u5199\u5165: %s (%d bytes)", path, len(content))
            except Exception as e:
                logger.warning("[sandbox] \u9884\u7f6e\u6587\u4ef6\u5199\u5165\u5931\u8d25: %s \u2192 %s", path, e)

    def _get_preset_files(self) -> dict[str, str]:
        """\u8fd4\u56de\u9700\u8981\u9884\u7f6e\u5230\u6c99\u7bb1\u7684\u6587\u4ef6 {\u8def\u5f84: \u5185\u5bb9}

        \u53ef\u901a\u8fc7\u5b50\u7c7b\u8986\u76d6\u6216\u4ece\u914d\u7f6e\u6587\u4ef6\u52a0\u8f7d\u3002
        """
        return {
            "/tmp/test_sales.csv": (
                "date,revenue,orders,avg_price\\n"
                "2024-01,120000,450,266.67\\n"
                "2024-02,135000,520,259.62\\n"
                "2024-03,128000,480,266.67\\n"
                "2024-04,142000,550,258.18\\n"
                "2024-05,155000,600,258.33\\n"
                "2024-06,148000,570,259.65\\n"
                "2024-07,162000,620,261.29\\n"
                "2024-08,170000,650,261.54\\n"
                "2024-09,158000,590,267.80\\n"
                "2024-10,175000,680,257.35\\n"
                "2024-11,185000,720,256.94\\n"
                "2024-12,195000,750,260.00\\n"
            ),
        }

    def _setup_env(self) -> None:
        """\u8bbe\u7f6e E2B SDK \u6240\u9700\u7684\u73af\u5883\u53d8\u91cf"""
        import os
        os.environ["E2B_DOMAIN"] = self._tencent_config.e2b_domain
        os.environ["E2B_API_KEY"] = self._tencent_config.e2b_api_key


def create_tencent_backend_from_env(config_dict: dict[str, str] | None = None) -> TencentSandboxBackend:
    """\u4ece\u914d\u7f6e\u5b57\u5178\u521b\u5efa\u817e\u8baf\u6c99\u7bb1 Backend

    Args:
        config_dict: \u914d\u7f6e\u5b57\u5178\uff08\u901a\u5e38\u6765\u81ea dotenv_values(".env")\uff09\u3002
                     \u4e0d\u4f20\u5219\u4ece os.environ \u8bfb\u53d6\u3002

    Raises:
        ValueError: \u7f3a\u5c11\u5fc5\u9700\u914d\u7f6e\u9879\u65f6\u629b\u51fa
    """
    import os

    def _get(key: str, default: str = "") -> str:
        if config_dict:
            return config_dict.get(key, default)
        return os.environ.get(key, default)

    api_key = _get("TENCENT_SANDBOX_API_KEY")
    if not api_key:
        raise ValueError(
            "TENCENT_SANDBOX_API_KEY \u672a\u914d\u7f6e\u3002"
            "\u8bf7\u5728 .env \u4e2d\u8bbe\u7f6e: TENCENT_SANDBOX_API_KEY=ark_xxx"
        )

    config = TencentSandboxConfig(
        e2b_domain=_get("TENCENT_SANDBOX_DOMAIN", "ap-beijing.tencentags.com"),
        e2b_api_key=api_key,
        template=_get("TENCENT_SANDBOX_TEMPLATE", "code-sandbox"),
        timeout=int(_get("TENCENT_SANDBOX_TIMEOUT", "3600")),
        max_output_chars=int(_get("SANDBOX_MAX_OUTPUT_CHARS", "50000")),
        working_dir=_get("SANDBOX_WORKING_DIR", "/home/user"),
        mount_name=_get("TENCENT_SANDBOX_MOUNT_NAME", "cos-aitools"),
    )

    return TencentSandboxBackend(config)
'''

with open(TARGET, 'w', encoding='utf-8') as f:
    f.write(CONTENT)

print(f"Done. Written {len(CONTENT)} chars.")
