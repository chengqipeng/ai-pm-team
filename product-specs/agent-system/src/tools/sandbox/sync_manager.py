"""
SandboxSyncManager — S3 双向同步管理器

职责：沙箱文件 ↔ S3 双向同步，嵌入 AWSAgentCoreSandboxBackend 内部，上层 Tool/Middleware 零感知。

三级同步策略：
  1. write_file 即时双写 — 每次 write_file 后异步上传单文件到 S3
  2. execute 后增量 sync — 每 N 次 execute 或命令含重定向时，find -newer 增量上传
  3. disconnect 全量兜底 — 会话结束时全量 sync（uploads/ + outputs/ + workspace/）

恢复策略：
  connect 时从 S3 按前缀全量下载到沙箱工作目录

S3 路径约定（对齐腾讯 COS subPath）：
  s3://{bucket}/{prefix}/{context_session_id}/uploads/xxx
  s3://{bucket}/{prefix}/{context_session_id}/outputs/xxx
  s3://{bucket}/{prefix}/{context_session_id}/workspace/xxx

依赖：boto3
"""
from __future__ import annotations

import asyncio
import logging
import re
import shlex
import time
from typing import Callable, Awaitable

logger = logging.getLogger(__name__)

# 检测命令中是否有文件输出（重定向 > 或 tee）
_REDIRECT_PATTERN = re.compile(r'(?:>|>>|\btee\b)')


class SandboxSyncManager:
    """沙箱 ↔ S3 双向同步管理器"""

    def __init__(
        self,
        bucket: str,
        prefix: str,
        region: str,
        working_dir: str,
        sync_interval: int = 5,
    ):
        """
        Args:
            bucket: S3 桶名
            prefix: S3 前缀（如 sandbox/{tenant}/{user}/{conversation}）
            region: AWS 区域
            working_dir: 沙箱工作根目录（如 /tmp/sandbox）
            sync_interval: 每 N 次 execute 触发一次增量 sync
        """
        self._bucket = bucket
        self._prefix = prefix
        self._region = region
        self._working_dir = working_dir
        self._sync_interval = sync_interval
        self._execute_count = 0
        self._sync_marker = "/tmp/.sandbox_sync_marker"
        self._pending_tasks: list[asyncio.Task] = []

    @property
    def s3_prefix(self) -> str:
        return self._prefix

    # ═══════════════════════════════════════════════════════
    # 对外接口（由 Backend 在各生命周期调用）
    # ═══════════════════════════════════════════════════════

    async def restore(
        self,
        invoke_command: Callable[[str], Awaitable[str]],
        invoke_code: Callable[[str, str], Awaitable[str]],
    ) -> int:
        """connect 后调用：从 S3 恢复全部文件到沙箱

        Args:
            invoke_command: 沙箱 executeCommand 的异步回调
            invoke_code: 沙箱 executeCode 的异步回调 (language, code)

        Returns:
            恢复的文件数量
        """
        if not self._bucket:
            return 0

        try:
            import boto3

            s3 = boto3.client("s3", region_name=self._region)
            prefix = f"{self._prefix}/"

            paginator = s3.get_paginator("list_objects_v2")
            pages = paginator.paginate(Bucket=self._bucket, Prefix=prefix)

            restored = 0
            for page in pages:
                for obj in page.get("Contents", []):
                    s3_key = obj["Key"]
                    rel_path = s3_key[len(prefix):]
                    if not rel_path:
                        continue

                    # 下载文件内容
                    response = await asyncio.to_thread(
                        s3.get_object, Bucket=self._bucket, Key=s3_key
                    )
                    content = response["Body"].read().decode("utf-8")
                    target_path = f"{self._working_dir}/{rel_path}"

                    # 写入沙箱
                    write_code = (
                        f"import os\n"
                        f"os.makedirs(os.path.dirname({target_path!r}) or '.', exist_ok=True)\n"
                        f"with open({target_path!r}, 'w', encoding='utf-8') as f:\n"
                        f"    f.write({content!r})\n"
                    )
                    await invoke_code("python", write_code)
                    restored += 1

            if restored > 0:
                logger.info("[sync] S3 恢复完成: %d 个文件, prefix=%s", restored, prefix)

            # 设置 sync marker（用于后续增量检测）
            await invoke_command(f"touch {self._sync_marker}")

            return restored

        except ImportError:
            logger.warning("[sync] boto3 未安装，跳过 S3 恢复")
            return 0
        except Exception as e:
            logger.warning("[sync] S3 恢复失败 (non-fatal): %s", e)
            return 0

    async def on_write(self, path: str, content: str) -> None:
        """write_file 后调用：异步上传单文件到 S3（fire-and-forget）

        只对工作目录内的文件触发 S3 同步，目录外的文件忽略。

        Args:
            path: 沙箱内文件路径
            content: 文件内容
        """
        if not self._bucket:
            return
        if not path.startswith(self._working_dir):
            return

        rel_path = path[len(self._working_dir):].lstrip("/")
        if not rel_path:
            return

        s3_key = f"{self._prefix}/{rel_path}"

        # fire-and-forget：异步上传，不阻塞 write_file 返回
        task = asyncio.create_task(self._upload_one(s3_key, content))
        self._pending_tasks.append(task)
        # 清理已完成的 task 引用
        self._pending_tasks = [t for t in self._pending_tasks if not t.done()]

    async def on_execute(
        self,
        command: str,
        invoke_command: Callable[[str], Awaitable[str]],
    ) -> None:
        """execute 后调用：计数器驱动 + 重定向检测触发增量 sync

        触发条件（满足任一即触发）：
          - 命令含重定向（> 或 tee）
          - 执行计数器 % sync_interval == 0

        Args:
            command: 刚执行的命令
            invoke_command: 沙箱 executeCommand 回调
        """
        if not self._bucket:
            return

        self._execute_count += 1
        has_redirect = bool(_REDIRECT_PATTERN.search(command))
        should_sync = has_redirect or (self._execute_count % self._sync_interval == 0)

        if should_sync:
            # 直接 await 增量 sync（保证 execute 返回时文件已落 S3）
            await self._safe_incremental_sync(invoke_command)

    async def incremental_sync(
        self,
        invoke_command: Callable[[str], Awaitable[str]],
    ) -> int:
        """增量同步：find -newer marker 找到变更文件并上传 S3

        Args:
            invoke_command: 沙箱 executeCommand 回调

        Returns:
            同步的文件数量
        """
        if not self._bucket:
            return 0

        try:
            # 找出 sync_marker 之后修改的文件
            find_cmd = (
                f"find {self._working_dir} -type f -newer {self._sync_marker} 2>/dev/null"
            )
            output = await invoke_command(find_cmd)
            files = [f.strip() for f in output.split("\n") if f.strip()]

            if not files:
                return 0

            import boto3
            s3 = boto3.client("s3", region_name=self._region)

            synced = 0
            for file_path in files:
                try:
                    content = await invoke_command(f"cat {shlex.quote(file_path)}")
                    rel_path = file_path[len(self._working_dir):].lstrip("/")
                    if not rel_path:
                        continue
                    s3_key = f"{self._prefix}/{rel_path}"
                    await asyncio.to_thread(
                        s3.put_object,
                        Bucket=self._bucket,
                        Key=s3_key,
                        Body=content.encode("utf-8"),
                    )
                    synced += 1
                except Exception as e:
                    logger.debug("[sync] 增量上传失败 %s: %s", file_path, e)

            # 更新 marker
            await invoke_command(f"touch {self._sync_marker}")

            if synced > 0:
                logger.info("[sync] 增量同步完成: %d 个文件", synced)
            return synced

        except Exception as e:
            logger.debug("[sync] 增量同步失败 (non-fatal): %s", e)
            return 0

    async def final_sync(
        self,
        invoke_command: Callable[[str], Awaitable[str]],
    ) -> int:
        """disconnect 前调用：全量 sync 工作目录到 S3

        Args:
            invoke_command: 沙箱 executeCommand 回调

        Returns:
            同步的文件数量
        """
        if not self._bucket:
            return 0

        # 先等待所有 pending 异步 task 完成
        if self._pending_tasks:
            await asyncio.gather(*self._pending_tasks, return_exceptions=True)
            self._pending_tasks.clear()

        try:
            import boto3

            # 全量扫描工作目录
            find_cmd = f"find {self._working_dir} -type f 2>/dev/null"
            output = await invoke_command(find_cmd)
            files = [f.strip() for f in output.split("\n") if f.strip()]

            if not files:
                logger.info("[sync] 工作目录为空，无需全量同步")
                return 0

            s3 = boto3.client("s3", region_name=self._region)
            synced = 0

            for file_path in files:
                try:
                    content = await invoke_command(f"cat {shlex.quote(file_path)}")
                    rel_path = file_path[len(self._working_dir):].lstrip("/")
                    if not rel_path:
                        continue
                    s3_key = f"{self._prefix}/{rel_path}"
                    await asyncio.to_thread(
                        s3.put_object,
                        Bucket=self._bucket,
                        Key=s3_key,
                        Body=content.encode("utf-8"),
                    )
                    synced += 1
                except Exception as e:
                    logger.warning("[sync] 全量上传失败 %s: %s", file_path, e)

            logger.info("[sync] 全量同步完成: %d 个文件", synced)
            return synced

        except ImportError:
            logger.warning("[sync] boto3 未安装，跳过全量同步")
            return 0
        except Exception as e:
            logger.warning("[sync] 全量同步失败 (non-fatal): %s", e)
            return 0

    # ═══════════════════════════════════════════════════════
    # 内部方法
    # ═══════════════════════════════════════════════════════

    async def _upload_one(self, s3_key: str, content: str) -> None:
        """上传单文件到 S3（异步 task 内调用）"""
        try:
            import boto3
            s3 = boto3.client("s3", region_name=self._region)
            await asyncio.to_thread(
                s3.put_object,
                Bucket=self._bucket,
                Key=s3_key,
                Body=content.encode("utf-8"),
            )
            logger.debug("[sync] 即时上传: s3://%s/%s", self._bucket, s3_key)
        except Exception as e:
            logger.debug("[sync] 即时上传失败 %s: %s", s3_key, e)

    async def _safe_incremental_sync(
        self,
        invoke_command: Callable[[str], Awaitable[str]],
    ) -> None:
        """安全包装增量 sync（异常不外抛）"""
        try:
            await self.incremental_sync(invoke_command)
        except Exception as e:
            logger.debug("[sync] 异步增量同步异常: %s", e)
