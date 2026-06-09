"""
ScriptSyncer — Skill 脚本同步器

将 ai_skill_resource 中 scripts/ 目录下的文件增量同步到沙盒文件系统。

设计对齐 Hermes Agent 的 rsync 机制：
  - Hermes: ~/.hermes/skills/{name}/scripts/ → rsync → 远程沙盒
  - 本系统: ai_skill_resource (DB) → ScriptSyncer → 远程沙盒

增量同步策略：
  - 首次执行: 全量写入所有 scripts/ 文件
  - 重复执行: 对比 content_hash，仅同步变更文件
  - 沙盒重建: manifest 不存在，自动全量同步

使用方式：
    from src.tools.sandbox.script_syncer import ScriptSyncer

    syncer = ScriptSyncer(backend=ssh_backend, tenant_id=0)
    result = await syncer.sync("csv-trend-analysis", version="1.0.0")
    print(f"同步完成: {result.synced} 文件写入, {result.skipped} 跳过")
"""
from __future__ import annotations

import hashlib
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any

from .backend_base import Backend

logger = logging.getLogger(__name__)

# 沙盒中 Skill 脚本的根目录（从 .env 读取，支持按后端类型自动选择默认值）
def _resolve_skill_base_dir() -> str:
    """从 .env 读取 SKILL_BASE_DIR，未配置时根据 SANDBOX_BACKEND 选择默认值"""
    import os
    from pathlib import Path

    # 优先读 os.environ（支持运行时覆盖）
    env_val = os.environ.get("SKILL_BASE_DIR", "").strip()
    if env_val:
        return env_val.rstrip("/")

    # 从 .env 文件读取
    config: dict[str, str] = {}
    candidates = [
        Path.cwd() / ".env",
        Path(__file__).resolve().parents[3] / ".env",  # src/tools/sandbox → 项目根
    ]
    for env_path in candidates:
        if env_path.exists():
            with open(env_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    if "=" in line:
                        key, _, value = line.partition("=")
                        config[key.strip()] = value.strip().strip('"').strip("'")
            break

    file_val = config.get("SKILL_BASE_DIR", "").strip()
    if file_val:
        return file_val.rstrip("/")

    # 未配置 → 根据 SANDBOX_BACKEND 选择默认值
    backend_type = config.get("SANDBOX_BACKEND", "ssh").strip().lower()
    if backend_type == "tencent":
        return "/sandbox/.skills"
    return "/sandbox/.skills"


SKILL_BASE_DIR = _resolve_skill_base_dir()

# 同步状态文件名
MANIFEST_FILE = ".sync_manifest.json"


@dataclass
class SyncResult:
    """同步结果"""
    synced: int = 0          # 实际写入的文件数
    skipped: int = 0         # hash 未变跳过的文件数
    errors: list[str] = field(default_factory=list)  # 错误信息
    duration_ms: float = 0.0  # 耗时


@dataclass
class ScriptFile:
    """待同步的脚本文件"""
    path: str           # 相对路径，如 scripts/analyze.py
    content: str        # 文件内容
    content_hash: str   # 内容 MD5 哈希


class ScriptSyncer:
    """Skill 脚本同步器 — 将 DB 中的脚本文件增量同步到沙盒

    核心流程:
    1. 从 ai_skill_resource 查询 scripts/ 下所有文件
    2. 从沙盒读取 .sync_manifest.json（上次同步状态）
    3. 对比 content_hash，确定需要同步的文件
    4. 通过 Backend.write_file() 写入沙盒
    5. 设置执行权限
    6. 更新 manifest
    """

    def __init__(self, backend: Backend, tenant_id: int = 0):
        self._backend = backend
        self._tenant_id = tenant_id

    async def sync(
        self,
        skill_name: str,
        version: str = "1.0.0",
        force: bool = False,
    ) -> SyncResult:
        """同步 Skill 的 scripts/ 目录到沙盒

        Args:
            skill_name: Skill 的 api_key
            version: 版本号
            force: 强制全量同步（忽略 manifest）

        Returns:
            SyncResult 包含同步统计
        """
        start = time.monotonic()
        result = SyncResult()

        # 1. 确保后端已连接
        if not self._backend.is_connected:
            try:
                await self._backend.connect()
            except Exception as e:
                result.errors.append(f"沙盒连接失败: {e}")
                return result

        # 2. 从 DB 查询脚本文件
        db_files = self._query_script_files(skill_name, version)
        if not db_files:
            logger.info("[script_syncer] skill=%s 无 scripts/ 文件，跳过同步", skill_name)
            return result

        skill_dir = f"{SKILL_BASE_DIR}/{skill_name}"
        manifest_path = f"{skill_dir}/{MANIFEST_FILE}"

        # 3. 读取沙盒中的 manifest
        remote_manifest: dict[str, str] = {}
        if not force:
            remote_manifest = await self._read_remote_manifest(manifest_path)

        # 4. 对比 hash，确定需要同步的文件
        to_sync: list[ScriptFile] = []
        for f in db_files:
            if force or remote_manifest.get(f.path) != f.content_hash:
                to_sync.append(f)
            else:
                result.skipped += 1

        if not to_sync:
            logger.info("[script_syncer] skill=%s 所有文件 hash 一致，无需同步", skill_name)
            result.duration_ms = (time.monotonic() - start) * 1000
            return result

        # 5. 创建目录结构
        await self._ensure_directories(skill_dir, to_sync)

        # 6. 写入文件
        for f in to_sync:
            remote_path = f"{skill_dir}/{f.path}"
            write_result = await self._backend.write_file(remote_path, f.content)
            if write_result.is_error:
                result.errors.append(f"写入失败 {f.path}: {write_result.output}")
                logger.warning("[script_syncer] 写入失败: %s → %s", f.path, write_result.output)
            else:
                result.synced += 1

        # 7. 设置执行权限
        await self._set_permissions(skill_dir)

        # 8. 自动安装依赖（如果配置了 auto_install）
        await self._auto_install_deps(skill_name, skill_dir, version)

        # 9. 更新 manifest
        new_manifest = {f.path: f.content_hash for f in db_files}
        manifest_content = json.dumps(new_manifest, indent=2)
        await self._backend.write_file(manifest_path, manifest_content)

        result.duration_ms = (time.monotonic() - start) * 1000
        logger.info(
            "[script_syncer] 同步完成: skill=%s, synced=%d, skipped=%d, errors=%d, %.0fms",
            skill_name, result.synced, result.skipped, len(result.errors), result.duration_ms,
        )
        return result

    # ─── 内部方法 ───

    def _query_script_files(self, skill_name: str, version: str) -> list[ScriptFile]:
        """从 ai_skill_resource 查询 scripts/ 下所有文件

        只查询 node_type='file' 且 path 以 'scripts/' 开头的记录。
        """
        try:
            from src.store.pg_pool import get_conn

            with get_conn() as conn:
                cur = conn.cursor()
                cur.execute("""
                    SELECT path, content
                    FROM ai_skill_resource
                    WHERE skill_api_key = %s
                      AND version = %s
                      AND tenant_id = %s
                      AND node_type = 'file'
                      AND path LIKE 'scripts/%%'
                      AND delete_flg = 0
                      AND enabled_flg = 1
                    ORDER BY path
                """, (skill_name, version, self._tenant_id))

                files = []
                for row in cur.fetchall():
                    path, content = row
                    if content is None:
                        continue
                    content_hash = hashlib.md5(content.encode("utf-8")).hexdigest()
                    files.append(ScriptFile(
                        path=path,
                        content=content,
                        content_hash=content_hash,
                    ))

                logger.debug("[script_syncer] 查询到 %d 个脚本文件: skill=%s", len(files), skill_name)
                return files

        except Exception as e:
            logger.error("[script_syncer] 查询脚本文件失败: skill=%s, err=%s", skill_name, e)
            return []

    async def _read_remote_manifest(self, manifest_path: str) -> dict[str, str]:
        """从沙盒读取同步状态 manifest

        Returns:
            {path: content_hash} 字典，文件不存在时返回空字典
        """
        exists = await self._backend.file_exists(manifest_path)
        if not exists:
            return {}

        result = await self._backend.read_file(manifest_path)
        if result.is_error:
            return {}

        try:
            manifest = json.loads(result.stdout)
            if isinstance(manifest, dict):
                return manifest
        except (json.JSONDecodeError, TypeError):
            pass

        return {}

    async def _ensure_directories(self, skill_dir: str, files: list[ScriptFile]) -> None:
        """确保沙盒中的目录结构存在"""
        # 收集所有需要的目录
        dirs: set[str] = set()
        for f in files:
            parts = f.path.split("/")
            for i in range(1, len(parts)):
                dirs.add("/".join(parts[:i]))

        # 始终创建 output/ 和 tmp/ 目录
        dirs.add("output")
        dirs.add("tmp")

        if dirs:
            # 一次性创建所有目录
            mkdir_cmd = " ".join(f"'{skill_dir}/{d}'" for d in sorted(dirs))
            await self._backend.execute(f"mkdir -p {mkdir_cmd}")

    async def _set_permissions(self, skill_dir: str) -> None:
        """设置脚本文件的执行权限"""
        # 对 .py 和 .sh 文件设置可执行权限
        await self._backend.execute(
            f"find {skill_dir}/scripts -type f \\( -name '*.py' -o -name '*.sh' \\) "
            f"-exec chmod +x {{}} \\;"
        )

    async def _auto_install_deps(self, skill_name: str, skill_dir: str, version: str) -> None:
        """自动安装 Python 依赖（仅在首次同步或依赖变更时执行）

        安装策略:
        1. 优先使用 scripts/requirements.txt（如果存在）
        2. 否则使用 ext_info.script_execution.required_packages 列表
        3. 通过 .deps_installed 标记文件避免重复安装
        """
        deps_marker = f"{skill_dir}/.deps_installed"

        # 检查是否已安装（marker 文件存在 = 已装过）
        marker_exists = await self._backend.file_exists(deps_marker)
        if marker_exists:
            # 检查 requirements.txt 的 hash 是否变了
            req_path = f"{skill_dir}/scripts/requirements.txt"
            req_exists = await self._backend.file_exists(req_path)
            if req_exists:
                # 读取 marker 中记录的 hash
                marker_result = await self._backend.read_file(deps_marker)
                old_hash = marker_result.stdout.strip() if not marker_result.is_error else ""
                # 读取当前 requirements.txt 的 hash
                req_result = await self._backend.execute(f"md5sum {req_path} | cut -d' ' -f1")
                new_hash = req_result.stdout.strip() if not req_result.is_error else ""
                if old_hash == new_hash:
                    logger.debug("[script_syncer] 依赖未变更，跳过安装: %s", skill_name)
                    return
            else:
                logger.debug("[script_syncer] 依赖已安装且无 requirements.txt: %s", skill_name)
                return

        # 确定 pip 命令（兼容不同环境）
        pip_cmd = await self._resolve_pip_command()
        if not pip_cmd:
            logger.warning("[script_syncer] 未找到 pip，跳过依赖安装: %s", skill_name)
            return

        # 安装依赖
        req_path = f"{skill_dir}/scripts/requirements.txt"
        req_exists = await self._backend.file_exists(req_path)

        if req_exists:
            # 方式 1: 使用 requirements.txt
            install_result = await self._backend.execute(
                f"{pip_cmd} install -r {req_path} -q --disable-pip-version-check",
                timeout=120,
            )
            if install_result.is_error:
                logger.warning("[script_syncer] pip install 失败: %s\n%s",
                               skill_name, install_result.output[:300])
                return

            # 记录 hash 到 marker
            hash_result = await self._backend.execute(f"md5sum {req_path} | cut -d' ' -f1")
            req_hash = hash_result.stdout.strip() if not hash_result.is_error else "installed"
            await self._backend.write_file(deps_marker, req_hash)
        else:
            # 方式 2: 从 ext_info 获取包列表
            packages = self._get_required_packages(skill_name, version)
            if packages:
                pkg_str = " ".join(f"'{p}'" for p in packages)
                install_result = await self._backend.execute(
                    f"{pip_cmd} install {pkg_str} -q --disable-pip-version-check",
                    timeout=120,
                )
                if install_result.is_error:
                    logger.warning("[script_syncer] pip install 失败: %s\n%s",
                                   skill_name, install_result.output[:300])
                    return
                await self._backend.write_file(deps_marker, "installed")

        logger.info("[script_syncer] 依赖安装完成: %s", skill_name)

    async def _resolve_pip_command(self) -> str:
        """检测沙盒中可用的 pip 命令（优先使用 python3.11 的 pip）"""
        for cmd in ("/usr/local/bin/python3 -m pip", "python3 -m pip", "pip3", "pip"):
            result = await self._backend.execute(f"{cmd} --version 2>/dev/null")
            if not result.is_error and "python 3.6" not in result.stdout.lower():
                return cmd
        return ""

    def _get_required_packages(self, skill_name: str, version: str) -> list[str]:
        """从 ai_skill.ext_info 中获取 required_packages 列表"""
        try:
            from src.store.pg_pool import get_conn

            with get_conn() as conn:
                cur = conn.cursor()
                cur.execute("""
                    SELECT ext_info FROM ai_skill
                    WHERE api_key = %s AND tenant_id = %s AND delete_flg = 0
                """, (skill_name, self._tenant_id))
                row = cur.fetchone()

            if row and row[0]:
                ext = json.loads(row[0]) if isinstance(row[0], str) else row[0]
                script_cfg = ext.get("script_execution", {})
                return script_cfg.get("required_packages", [])
        except Exception as e:
            logger.warning("[script_syncer] 获取 required_packages 失败: %s", e)
        return []

    # ─── 便捷方法 ───

    def get_skill_dir(self, skill_name: str) -> str:
        """获取 Skill 在沙盒中的目录路径（供模板变量替换使用）"""
        return f"{SKILL_BASE_DIR}/{skill_name}"

    async def is_synced(self, skill_name: str, version: str = "1.0.0") -> bool:
        """检查 Skill 脚本是否已同步（manifest 存在且 hash 全部匹配）"""
        skill_dir = f"{SKILL_BASE_DIR}/{skill_name}"
        manifest_path = f"{skill_dir}/{MANIFEST_FILE}"

        remote_manifest = await self._read_remote_manifest(manifest_path)
        if not remote_manifest:
            return False

        db_files = self._query_script_files(skill_name, version)
        if not db_files:
            return True  # 无脚本文件，视为已同步

        for f in db_files:
            if remote_manifest.get(f.path) != f.content_hash:
                return False

        return True

    async def cleanup(self, skill_name: str) -> None:
        """清理沙盒中某个 Skill 的脚本目录"""
        skill_dir = f"{SKILL_BASE_DIR}/{skill_name}"
        await self._backend.execute(f"rm -rf {skill_dir}")
        logger.info("[script_syncer] 已清理: %s", skill_dir)
