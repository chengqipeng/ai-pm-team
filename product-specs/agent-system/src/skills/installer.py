"""技能安装器 — 从 URL / 本地路径 / Git 仓库安装技能包到本地目录

支持的安装源：
1. 本地目录路径（包含 SKILL.md）
2. 本地 .tar.gz / .zip 压缩包
3. HTTP(S) URL（下载 .tar.gz / .zip）
4. Git 仓库 URL（git clone）

安装流程：
1. 解析安装源类型
2. 下载/解压到临时目录
3. 验证 SKILL.md 格式
4. 复制到目标技能目录
5. 注册到 SkillRegistry（如果提供）
"""
from __future__ import annotations

import logging
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class SkillInstaller:
    """技能安装器

    Args:
        skills_dir: 技能安装目标目录
        skill_registry: 可选的 SkillRegistry，安装后自动注册
    """

    def __init__(self, skills_dir: str = "./skills/installed",
                 skill_registry: Any = None) -> None:
        self._skills_dir = Path(skills_dir)
        self._skill_registry = skill_registry

    def install_from_path(self, source_path: str) -> str:
        """从本地路径安装技能

        Args:
            source_path: 包含 SKILL.md 的目录路径，或 .tar.gz/.zip 压缩包路径

        Returns:
            安装后的技能目录路径

        Raises:
            FileNotFoundError: 源路径不存在
            ValueError: 源路径中没有 SKILL.md
        """
        source = Path(source_path)
        if not source.exists():
            raise FileNotFoundError(f"源路径不存在: {source_path}")

        # 压缩包
        if source.suffix in (".gz", ".zip") or source.name.endswith(".tar.gz"):
            return self._install_from_archive(source)

        # 目录
        if source.is_dir():
            return self._install_from_dir(source)

        raise ValueError(f"不支持的源类型: {source_path}")

    def install_from_url(self, url: str) -> str:
        """从 URL 下载并安装技能

        Args:
            url: HTTP(S) URL（.tar.gz / .zip）或 Git 仓库 URL

        Returns:
            安装后的技能目录路径
        """
        if url.endswith(".git") or "github.com" in url or "gitlab.com" in url:
            return self._install_from_git(url)
        return self._install_from_http(url)

    def uninstall(self, skill_name: str) -> bool:
        """卸载技能

        Args:
            skill_name: 技能名称

        Returns:
            是否成功卸载
        """
        skill_dir = self._skills_dir / skill_name
        if not skill_dir.exists():
            logger.warning("技能 '%s' 不存在: %s", skill_name, skill_dir)
            return False

        shutil.rmtree(skill_dir)
        logger.info("已卸载技能: %s", skill_name)

        if self._skill_registry is not None:
            self._skill_registry.unregister(skill_name)

        return True

    def list_installed(self) -> list[dict[str, str]]:
        """列出所有已安装的技能"""
        if not self._skills_dir.exists():
            return []

        installed = []
        for entry in sorted(self._skills_dir.iterdir()):
            if entry.is_dir():
                skill_md = entry / "SKILL.md"
                if skill_md.exists():
                    # 读取 description
                    desc = self._extract_description(skill_md)
                    installed.append({"name": entry.name, "path": str(entry), "description": desc})
        return installed

    def _install_from_dir(self, source_dir: Path) -> str:
        """从目录安装"""
        skill_md = source_dir / "SKILL.md"
        if not skill_md.exists():
            # 检查子目录
            for sub in source_dir.iterdir():
                if sub.is_dir() and (sub / "SKILL.md").exists():
                    return self._install_from_dir(sub)
            raise ValueError(f"目录中未找到 SKILL.md: {source_dir}")

        # 验证 SKILL.md
        self._validate_skill_md(skill_md)

        # 确定技能名
        skill_name = self._extract_skill_name(skill_md, source_dir.name)

        # 复制到目标目录
        target_dir = self._skills_dir / skill_name
        if target_dir.exists():
            logger.warning("覆盖已存在的技能: %s", skill_name)
            shutil.rmtree(target_dir)

        self._skills_dir.mkdir(parents=True, exist_ok=True)
        shutil.copytree(source_dir, target_dir)
        logger.info("技能安装完成: %s → %s", source_dir, target_dir)

        # 注册到 SkillRegistry
        self._auto_register(target_dir / "SKILL.md")

        return str(target_dir)

    def _install_from_archive(self, archive_path: Path) -> str:
        """从压缩包安装"""
        tmp_dir = tempfile.mkdtemp(prefix="skill_install_")
        try:
            # 解压
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

            # 在解压目录中查找 SKILL.md
            tmp = Path(tmp_dir)
            skill_dirs = list(tmp.rglob("SKILL.md"))
            if not skill_dirs:
                raise ValueError(f"压缩包中未找到 SKILL.md: {archive_path}")

            return self._install_from_dir(skill_dirs[0].parent)
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    def _install_from_http(self, url: str) -> str:
        """从 HTTP URL 下载并安装"""
        import urllib.request

        tmp_dir = tempfile.mkdtemp(prefix="skill_download_")
        try:
            # 推断文件名
            filename = url.rsplit("/", 1)[-1] or "skill_package.tar.gz"
            download_path = Path(tmp_dir) / filename

            logger.info("下载技能包: %s", url)
            urllib.request.urlretrieve(url, str(download_path))

            return self.install_from_path(str(download_path))
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    def _install_from_git(self, url: str) -> str:
        """从 Git 仓库克隆并安装"""
        import subprocess

        tmp_dir = tempfile.mkdtemp(prefix="skill_git_")
        try:
            logger.info("克隆技能仓库: %s", url)
            subprocess.run(
                ["git", "clone", "--depth", "1", url, tmp_dir],
                check=True, capture_output=True, timeout=60,
            )
            return self.install_from_path(tmp_dir)
        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"Git clone 失败: {e.stderr.decode()[:200]}") from e
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    def _validate_skill_md(self, skill_md: Path) -> None:
        """验证 SKILL.md 格式"""
        from src.skills.base import SkillLoader, SkillValidationError

        content = skill_md.read_text(encoding="utf-8")
        skill = SkillLoader.parse(content)
        SkillLoader.validate(skill)

    def _extract_skill_name(self, skill_md: Path, fallback: str) -> str:
        """从 SKILL.md 提取技能名"""
        from src.skills.base import SkillLoader

        content = skill_md.read_text(encoding="utf-8")
        skill = SkillLoader.parse(content)
        return skill.name if skill.name else fallback

    def _extract_description(self, skill_md: Path) -> str:
        """从 SKILL.md 提取描述"""
        try:
            from src.skills.base import SkillLoader
            content = skill_md.read_text(encoding="utf-8")
            skill = SkillLoader.parse(content)
            return skill.description
        except Exception:
            return ""

    def _auto_register(self, skill_md: Path) -> None:
        """安装后自动注册到 SkillRegistry"""
        if self._skill_registry is None:
            return
        try:
            from src.skills.base import SkillLoader
            skill = SkillLoader.load(str(skill_md))
            self._skill_registry.register(skill)
            logger.info("技能已注册: %s", skill.name)
        except Exception as e:
            logger.warning("技能注册失败: %s", e)
