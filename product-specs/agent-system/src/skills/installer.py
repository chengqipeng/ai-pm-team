"""技能安装器 — 把 SKILL.md 导入到 ai_skill_definition 数据库

安装源（仅作为 **导入入口**，最终数据落到 DB）：
1. 本地目录路径（包含 SKILL.md）
2. 本地 .tar.gz / .zip 压缩包
3. HTTP(S) URL（下载 .tar.gz / .zip）
4. Git 仓库 URL（git clone）

安装流程：
1. 解析安装源类型
2. 下载/解压到临时目录
3. 定位 SKILL.md 并解析 / 校验
4. UPSERT 到 ai_skill_definition + 写入 ai_skill_version
5. 注册到内存 SkillRegistry（如果提供）
6. 临时文件清理

设计要点：
- **不再写入任何本地"已安装"目录**，DB 是唯一数据源
- 适用于 CI / 运营 CLI / 运维批量导入
"""
from __future__ import annotations

import logging
import shutil
import tempfile
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class SkillInstaller:
    """技能安装器（DB 版）

    Args:
        skill_registry: 可选的 SkillRegistry，安装后同步注册到内存
        default_tenant_id: 安装到的目标租户（0 = 平台级）
        default_owner: 没有 owner 字段时的默认值
    """

    def __init__(self, skill_registry: Any = None, *,
                 default_tenant_id: int = 0,
                 default_owner: str = "imported") -> None:
        self._skill_registry = skill_registry
        self._default_tenant_id = default_tenant_id
        self._default_owner = default_owner

    # ── 公开入口 ──

    def install_from_path(self, source_path: str,
                           tenant_id: int | None = None) -> str:
        """从本地路径安装（目录或压缩包）

        Returns: 安装的 Skill api_key
        """
        source = Path(source_path)
        if not source.exists():
            raise FileNotFoundError(f"源路径不存在: {source_path}")

        if source.suffix in (".gz", ".zip") or source.name.endswith(".tar.gz"):
            return self._install_from_archive(source, tenant_id)
        if source.is_dir():
            return self._install_from_dir(source, tenant_id)
        raise ValueError(f"不支持的源类型: {source_path}")

    def install_from_url(self, url: str, tenant_id: int | None = None) -> str:
        """从 URL 下载并安装"""
        if url.endswith(".git") or "github.com" in url or "gitlab.com" in url:
            return self._install_from_git(url, tenant_id)
        return self._install_from_http(url, tenant_id)

    def uninstall(self, api_key: str, tenant_id: int | None = None) -> bool:
        """软删除 Skill（ai_skill_definition.delete_flg=1）"""
        from src.store.skill_dao import SkillDefinitionDAO

        tid = tenant_id if tenant_id is not None else self._default_tenant_id
        try:
            SkillDefinitionDAO.soft_delete(tid, api_key)
        except Exception as exc:
            logger.warning("卸载 Skill 失败 tenant=%d api_key=%s: %s", tid, api_key, exc)
            return False
        logger.info("已卸载 Skill: tenant=%d api_key=%s", tid, api_key)
        if self._skill_registry is not None:
            self._skill_registry.unregister(api_key)
        return True

    def list_installed(self, tenant_id: int | None = None) -> list[dict[str, Any]]:
        """列出已安装（DB 中未删除）的 Skill"""
        from src.store.skill_dao import SkillDefinitionDAO

        tid = tenant_id if tenant_id is not None else self._default_tenant_id
        rows = SkillDefinitionDAO.list_all(tenant_id=tid)
        return [
            {
                "api_key": r.api_key,
                "tenant_id": r.tenant_id,
                "name": r.name,
                "description": r.description,
                "status": r.status,
                "version": r.version,
            }
            for r in rows
        ]

    # ── 内部实现 ──

    def _install_from_dir(self, source_dir: Path, tenant_id: int | None) -> str:
        skill_md = source_dir / "SKILL.md"
        if not skill_md.exists():
            # 检查子目录
            for sub in source_dir.iterdir():
                if sub.is_dir() and (sub / "SKILL.md").exists():
                    return self._install_from_dir(sub, tenant_id)
            raise ValueError(f"目录中未找到 SKILL.md: {source_dir}")
        return self._import_skill_md(skill_md, tenant_id)

    def _install_from_archive(self, archive_path: Path, tenant_id: int | None) -> str:
        tmp_dir = tempfile.mkdtemp(prefix="skill_install_")
        try:
            if archive_path.name.endswith(".tar.gz") or archive_path.suffix == ".gz":
                import tarfile
                with tarfile.open(archive_path, "r:gz") as tar:
                    tar.extractall(tmp_dir)
            elif archive_path.suffix == ".zip":
                import zipfile
                with zipfile.ZipFile(archive_path, "r") as zf:
                    zf.extractall(tmp_dir)
            else:
                raise ValueError(f"不支持的压缩格式: {archive_path.suffix}")

            tmp = Path(tmp_dir)
            skill_dirs = list(tmp.rglob("SKILL.md"))
            if not skill_dirs:
                raise ValueError(f"压缩包中未找到 SKILL.md: {archive_path}")
            return self._import_skill_md(skill_dirs[0], tenant_id)
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    def _install_from_http(self, url: str, tenant_id: int | None) -> str:
        import urllib.request

        tmp_dir = tempfile.mkdtemp(prefix="skill_download_")
        try:
            filename = url.rsplit("/", 1)[-1] or "skill_package.tar.gz"
            download_path = Path(tmp_dir) / filename

            logger.info("下载技能包: %s", url)
            urllib.request.urlretrieve(url, str(download_path))
            return self.install_from_path(str(download_path), tenant_id)
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    def _install_from_git(self, url: str, tenant_id: int | None) -> str:
        import subprocess

        tmp_dir = tempfile.mkdtemp(prefix="skill_git_")
        try:
            logger.info("克隆技能仓库: %s", url)
            subprocess.run(
                ["git", "clone", "--depth", "1", url, tmp_dir],
                check=True, capture_output=True, timeout=60,
            )
            return self.install_from_path(tmp_dir, tenant_id)
        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"Git clone 失败: {e.stderr.decode()[:200]}") from e
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    def _import_skill_md(self, skill_md: Path, tenant_id: int | None) -> str:
        """解析 → 校验 → 写 DB → 内存注册"""
        from src.skills.base import SkillLoader, SkillRegistry

        content = skill_md.read_text(encoding="utf-8")
        skill = SkillLoader.parse(content)
        if not skill.name:
            skill.name = skill_md.parent.name
        SkillLoader.validate(skill)

        tid = tenant_id if tenant_id is not None else self._default_tenant_id
        skill.tenant_id = tid
        if not skill.owner:
            skill.owner = self._default_owner

        registry = self._skill_registry or SkillRegistry()
        registry.upsert_to_db(
            skill, tenant_id=tid, status="published",
            changelog=f"imported from {skill_md.name}",
        )
        if self._skill_registry is not None:
            self._skill_registry.register(skill)

        logger.info("Skill 已导入 DB: tenant=%d api_key=%s version=%s",
                    tid, skill.name, skill.version)
        return skill.name
