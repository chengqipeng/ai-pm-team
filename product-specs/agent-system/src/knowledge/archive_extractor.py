"""压缩包解析器 — 支持 ZIP / TAR / TAR.GZ / TAR.BZ2

上传压缩包后，自动解压并遍历内部所有支持的文档文件，
逐一提交到知识库入库流水线。

支持的压缩格式：
    - .zip
    - .tar
    - .tar.gz / .tgz
    - .tar.bz2 / .tbz2
    - .tar.xz / .txz
    - .gz (单文件 gzip)
    - .rar (需安装 rarfile + unrar)

安全措施：
    - 路径穿越检测（ZipSlip 防护）
    - 解压大小限制（默认 2GB）
    - 文件数量限制（默认 500）
    - 跳过隐藏文件和 __MACOSX 目录
    - 中文文件名编码自动检测（GBK/UTF-8）
"""
from __future__ import annotations

import gzip
import logging
import os
import shutil
import tarfile
import tempfile
import uuid
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Generator

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════
# 配置
# ═══════════════════════════════════════════════════════════

# 支持解析的文档扩展名（与 LKEAP SUPPORTED_TYPES 对齐）
SUPPORTED_DOC_EXTENSIONS: set[str] = {
    "pdf", "doc", "docx", "ppt", "pptx", "xls", "xlsx", "wps",
    "md", "txt", "csv", "html", "epub",
    "png", "jpg", "jpeg", "bmp", "gif", "webp", "heic",
    "eps", "icns", "im", "pcx", "ppm", "tiff", "xbm", "heif", "jp2",
}

# 支持的压缩格式扩展名
ARCHIVE_EXTENSIONS: set[str] = {
    "zip", "tar", "gz", "tgz", "bz2", "tbz2", "xz", "txz", "rar",
}

# 安全限制
MAX_EXTRACT_SIZE_BYTES: int = 2 * 1024 * 1024 * 1024  # 2GB
MAX_FILE_COUNT: int = 500

# 跳过的目录/文件前缀
SKIP_PREFIXES: tuple[str, ...] = (
    "__MACOSX",
    ".DS_Store",
    "._",
    ".git",
    ".svn",
    "Thumbs.db",
)


# ═══════════════════════════════════════════════════════════
# 数据模型
# ═══════════════════════════════════════════════════════════

@dataclass
class ExtractedFile:
    """解压后的单个文件信息"""
    file_path: str          # 解压后的绝对路径
    file_name: str          # 原始文件名（不含路径）
    relative_path: str      # 在压缩包内的相对路径（保留目录结构）
    file_type: str          # 扩展名（小写，不含点）
    file_size: int          # 文件大小（字节）


@dataclass
class ExtractionResult:
    """解压结果"""
    success: bool = True
    extract_dir: str = ""                           # 解压临时目录
    files: list[ExtractedFile] = field(default_factory=list)
    skipped_files: list[str] = field(default_factory=list)  # 不支持的文件
    error: str = ""
    total_size: int = 0
    archive_name: str = ""


# ═══════════════════════════════════════════════════════════
# 工具函数
# ═══════════════════════════════════════════════════════════

def is_archive(filename: str) -> bool:
    """判断文件是否为支持的压缩格式"""
    name_lower = filename.lower()
    # 处理复合扩展名
    if name_lower.endswith((".tar.gz", ".tar.bz2", ".tar.xz")):
        return True
    ext = name_lower.rsplit(".", 1)[-1] if "." in name_lower else ""
    return ext in ARCHIVE_EXTENSIONS


def _should_skip(name: str) -> bool:
    """判断是否应跳过该文件/目录"""
    basename = os.path.basename(name)
    # 跳过隐藏文件（以 . 开头，但保留 .md 等有效文件）
    if basename.startswith(".") and not any(
        basename.endswith(f".{ext}") for ext in SUPPORTED_DOC_EXTENSIONS
    ):
        return True
    # 跳过特定前缀
    for prefix in SKIP_PREFIXES:
        if prefix in name:
            return True
    return False


def _is_supported_file(filename: str) -> bool:
    """判断文件是否为支持的文档格式"""
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    return ext in SUPPORTED_DOC_EXTENSIONS


def _safe_extract_path(member_name: str, extract_dir: str) -> str | None:
    """安全路径检查 — 防止 ZipSlip 路径穿越攻击

    Returns:
        安全的目标路径，如果检测到路径穿越则返回 None
    """
    # 规范化路径
    target = os.path.normpath(os.path.join(extract_dir, member_name))
    # 确保目标路径在解压目录内
    if not target.startswith(os.path.normpath(extract_dir) + os.sep) \
            and target != os.path.normpath(extract_dir):
        return None
    return target


def _fix_zip_filename(info: "zipfile.ZipInfo") -> str:
    """修复 ZIP 文件中的中文文件名编码问题

    ZIP 规范中，当 flag_bits 的 bit 11 (0x800) 未设置时，
    文件名使用 CP437 编码（IBM PC 原始编码）。
    但中文 Windows 创建的 ZIP 实际使用 GBK 编码，
    Python zipfile 按 CP437 解码后会产生乱码。

    修复策略：
        1. 如果 UTF-8 flag 已设置 → 直接使用（已是 UTF-8）
        2. 否则尝试将原始字节按 GBK 解码
        3. GBK 失败则尝试 UTF-8
        4. 都失败则保留原样
    """
    # bit 11 = UTF-8 flag
    if info.flag_bits & 0x800:
        return info.filename

    # 获取原始字节：Python zipfile 已经按 CP437 解码了 filename，
    # 需要先编码回 CP437 得到原始字节，再用正确编码解码
    try:
        raw_bytes = info.filename.encode('cp437')
    except (UnicodeEncodeError, UnicodeDecodeError):
        # 如果 encode 回 cp437 失败，说明已经不是 cp437 了，保留原样
        return info.filename

    # 尝试 GBK 解码（中文 Windows 最常见）
    try:
        decoded = raw_bytes.decode('gbk')
        if decoded and not _has_garbled_chars(decoded):
            return decoded
    except (UnicodeDecodeError, ValueError):
        pass

    # 尝试 UTF-8 解码
    try:
        decoded = raw_bytes.decode('utf-8')
        if decoded and not _has_garbled_chars(decoded):
            return decoded
    except (UnicodeDecodeError, ValueError):
        pass

    # 尝试 Shift-JIS（日文 ZIP）
    try:
        decoded = raw_bytes.decode('shift_jis')
        if decoded:
            return decoded
    except (UnicodeDecodeError, ValueError):
        pass

    # 都失败，返回原始（可能乱码但至少不崩溃）
    return info.filename


def _has_garbled_chars(text: str) -> bool:
    """简单检测是否包含明显乱码字符（大量不可打印/替换字符）"""
    if not text:
        return False
    bad_count = sum(1 for c in text if ord(c) > 0xFFFF or c == '\ufffd')
    return bad_count > len(text) * 0.3


# ═══════════════════════════════════════════════════════════
# 核心解压逻辑
# ═══════════════════════════════════════════════════════════

class ArchiveExtractor:
    """压缩包解压器

    使用方式：
        extractor = ArchiveExtractor()
        result = extractor.extract(archive_path, archive_name="docs.zip")
        for f in result.files:
            # 提交到知识库
            await provider.ingest_document(...)
        # 清理
        extractor.cleanup(result.extract_dir)
    """

    def __init__(
        self,
        max_size: int = MAX_EXTRACT_SIZE_BYTES,
        max_files: int = MAX_FILE_COUNT,
    ) -> None:
        self._max_size = max_size
        self._max_files = max_files

    def extract(self, archive_path: str, archive_name: str = "") -> ExtractionResult:
        """解压压缩包，返回所有支持的文档文件列表

        Args:
            archive_path: 压缩包文件路径
            archive_name: 原始文件名（用于判断格式）

        Returns:
            ExtractionResult 包含解压后的文件列表
        """
        archive_name = archive_name or os.path.basename(archive_path)
        name_lower = archive_name.lower()

        # 创建临时解压目录
        extract_dir = tempfile.mkdtemp(prefix="kb_archive_")

        try:
            if name_lower.endswith(".zip"):
                self._extract_zip(archive_path, extract_dir)
            elif name_lower.endswith((".tar.gz", ".tgz")):
                self._extract_tar(archive_path, extract_dir, mode="r:gz")
            elif name_lower.endswith((".tar.bz2", ".tbz2")):
                self._extract_tar(archive_path, extract_dir, mode="r:bz2")
            elif name_lower.endswith((".tar.xz", ".txz")):
                self._extract_tar(archive_path, extract_dir, mode="r:xz")
            elif name_lower.endswith(".tar"):
                self._extract_tar(archive_path, extract_dir, mode="r:")
            elif name_lower.endswith(".gz") and not name_lower.endswith(".tar.gz"):
                self._extract_gzip(archive_path, extract_dir, archive_name)
            elif name_lower.endswith(".rar"):
                self._extract_rar(archive_path, extract_dir)
            else:
                return ExtractionResult(
                    success=False,
                    error=f"不支持的压缩格式: {archive_name}",
                    archive_name=archive_name,
                )
        except (zipfile.BadZipFile, tarfile.TarError) as exc:
            logger.error("Archive extraction failed: %s — %s", archive_name, exc)
            self.cleanup(extract_dir)
            return ExtractionResult(
                success=False,
                error=f"压缩包损坏或格式错误: {exc}",
                archive_name=archive_name,
            )
        except _ExtractionLimitError as exc:
            logger.warning("Archive extraction limit exceeded: %s — %s", archive_name, exc)
            self.cleanup(extract_dir)
            return ExtractionResult(
                success=False,
                error=str(exc),
                archive_name=archive_name,
            )
        except Exception as exc:
            logger.exception("Archive extraction unexpected error: %s — %s", archive_name, exc)
            self.cleanup(extract_dir)
            return ExtractionResult(
                success=False,
                error=f"解压失败: {type(exc).__name__}: {exc}",
                archive_name=archive_name,
            )

        # 遍历解压目录，收集支持的文件
        files: list[ExtractedFile] = []
        skipped: list[str] = []
        total_size = 0

        for root, dirs, filenames in os.walk(extract_dir):
            # 过滤掉需要跳过的目录
            dirs[:] = [d for d in dirs if not _should_skip(d)]

            for fname in filenames:
                if _should_skip(fname):
                    continue

                abs_path = os.path.join(root, fname)
                rel_path = os.path.relpath(abs_path, extract_dir)

                if not os.path.isfile(abs_path):
                    continue

                fsize = os.path.getsize(abs_path)
                total_size += fsize

                if _is_supported_file(fname):
                    ext = fname.rsplit(".", 1)[-1].lower() if "." in fname else ""
                    files.append(ExtractedFile(
                        file_path=abs_path,
                        file_name=fname,
                        relative_path=rel_path,
                        file_type=ext,
                        file_size=fsize,
                    ))
                else:
                    skipped.append(rel_path)

        logger.info(
            "Archive extracted: name=%s files=%d skipped=%d total_size=%d dir=%s",
            archive_name, len(files), len(skipped), total_size, extract_dir,
        )

        return ExtractionResult(
            success=True,
            extract_dir=extract_dir,
            files=files,
            skipped_files=skipped,
            total_size=total_size,
            archive_name=archive_name,
        )

    def _extract_zip(self, archive_path: str, extract_dir: str) -> None:
        """解压 ZIP 文件（自动修复中文文件名编码）"""
        total_size = 0
        file_count = 0

        with zipfile.ZipFile(archive_path, "r") as zf:
            for info in zf.infolist():
                # 跳过目录
                if info.is_dir():
                    continue

                # 修复中文文件名编码（GBK → UTF-8）
                fixed_filename = _fix_zip_filename(info)

                # 安全检查
                safe_path = _safe_extract_path(fixed_filename, extract_dir)
                if safe_path is None:
                    logger.warning(
                        "ZipSlip detected, skipping: %s", fixed_filename
                    )
                    continue

                # 大小限制
                total_size += info.file_size
                if total_size > self._max_size:
                    raise _ExtractionLimitError(
                        f"解压总大小超过限制 ({self._max_size // (1024*1024)}MB)"
                    )

                # 文件数量限制
                file_count += 1
                if file_count > self._max_files:
                    raise _ExtractionLimitError(
                        f"压缩包内文件数量超过限制 ({self._max_files})"
                    )

                # 确保父目录存在
                os.makedirs(os.path.dirname(safe_path), exist_ok=True)

                # 解压单个文件
                with zf.open(info) as src, open(safe_path, "wb") as dst:
                    shutil.copyfileobj(src, dst)

    def _extract_tar(self, archive_path: str, extract_dir: str, mode: str) -> None:
        """解压 TAR 系列文件（自动处理文件名编码）"""
        total_size = 0
        file_count = 0

        with tarfile.open(archive_path, mode) as tf:
            for member in tf.getmembers():
                # 只处理普通文件
                if not member.isfile():
                    continue

                # 修复 TAR 文件名编码（某些工具生成的 tar 使用 GBK）
                member_name = member.name
                try:
                    # 尝试检测并修复编码
                    raw = member_name.encode('utf-8', errors='surrogateescape')
                    # 如果包含高字节，尝试 GBK 解码
                    if any(b > 127 for b in raw):
                        try:
                            member_name = raw.decode('gbk')
                        except (UnicodeDecodeError, ValueError):
                            try:
                                member_name = raw.decode('utf-8')
                            except (UnicodeDecodeError, ValueError):
                                pass  # 保留原样
                except (UnicodeEncodeError, UnicodeDecodeError):
                    pass

                # 安全检查
                safe_path = _safe_extract_path(member_name, extract_dir)
                if safe_path is None:
                    logger.warning(
                        "Path traversal detected in tar, skipping: %s", member_name
                    )
                    continue

                # 大小限制
                total_size += member.size
                if total_size > self._max_size:
                    raise _ExtractionLimitError(
                        f"解压总大小超过限制 ({self._max_size // (1024*1024)}MB)"
                    )

                # 文件数量限制
                file_count += 1
                if file_count > self._max_files:
                    raise _ExtractionLimitError(
                        f"压缩包内文件数量超过限制 ({self._max_files})"
                    )

                # 确保父目录存在
                os.makedirs(os.path.dirname(safe_path), exist_ok=True)

                # 解压单个文件
                src = tf.extractfile(member)
                if src is None:
                    continue
                with open(safe_path, "wb") as dst:
                    shutil.copyfileobj(src, dst)

    def _extract_gzip(
        self, archive_path: str, extract_dir: str, archive_name: str
    ) -> None:
        """解压单文件 gzip"""
        # 去掉 .gz 后缀得到原始文件名
        inner_name = archive_name[:-3] if archive_name.lower().endswith(".gz") else archive_name
        if not inner_name:
            inner_name = "extracted_file"

        target_path = os.path.join(extract_dir, inner_name)
        total_size = 0

        with gzip.open(archive_path, "rb") as src, open(target_path, "wb") as dst:
            while True:
                chunk = src.read(65536)
                if not chunk:
                    break
                total_size += len(chunk)
                if total_size > self._max_size:
                    raise _ExtractionLimitError(
                        f"解压大小超过限制 ({self._max_size // (1024*1024)}MB)"
                    )
                dst.write(chunk)

    def _extract_rar(self, archive_path: str, extract_dir: str) -> None:
        """解压 RAR 文件（需要 rarfile 库 + unrar 命令行工具）"""
        try:
            import rarfile
        except ImportError:
            raise RuntimeError(
                "解压 RAR 文件需要安装 rarfile 库: pip install rarfile。"
                "同时需要系统安装 unrar 命令行工具。"
            )

        total_size = 0
        file_count = 0

        with rarfile.RarFile(archive_path, "r") as rf:
            for info in rf.infolist():
                if info.is_dir():
                    continue

                safe_path = _safe_extract_path(info.filename, extract_dir)
                if safe_path is None:
                    logger.warning(
                        "Path traversal detected in rar, skipping: %s", info.filename
                    )
                    continue

                total_size += info.file_size
                if total_size > self._max_size:
                    raise _ExtractionLimitError(
                        f"解压总大小超过限制 ({self._max_size // (1024*1024)}MB)"
                    )

                file_count += 1
                if file_count > self._max_files:
                    raise _ExtractionLimitError(
                        f"压缩包内文件数量超过限制 ({self._max_files})"
                    )

                os.makedirs(os.path.dirname(safe_path), exist_ok=True)
                with rf.open(info) as src, open(safe_path, "wb") as dst:
                    shutil.copyfileobj(src, dst)

    @staticmethod
    def cleanup(extract_dir: str) -> None:
        """清理解压临时目录"""
        if extract_dir and os.path.isdir(extract_dir):
            try:
                shutil.rmtree(extract_dir)
                logger.debug("Cleaned up extract dir: %s", extract_dir)
            except Exception as exc:
                logger.warning("Failed to cleanup extract dir %s: %s", extract_dir, exc)


# ═══════════════════════════════════════════════════════════
# 内部异常
# ═══════════════════════════════════════════════════════════

class _ExtractionLimitError(Exception):
    """解压限制超出"""
    pass
