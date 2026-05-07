"""文档清洗服务 — 4 Stage 流水线

对标 neo-ai-data-process-service 的 DocumentCleaningServiceImpl。
产出双层文本：
    - display_content: 保留表格 HTML / 图片占位（展示用）
    - content: 纯文本（喂 Embedding / BM25）

以及清洗信号：
    - clean_ratio: 被清洗掉的字符比例
    - dropped_* 计数（编码/噪声/空行）
"""
from __future__ import annotations

import logging
import re
import unicodedata
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════
# 结果与配置
# ═══════════════════════════════════════════════════════════

@dataclass
class CleaningSignals:
    """清洗过程的量化信号 — 作为质量评分输入"""
    original_chars: int = 0
    cleaned_chars: int = 0
    dropped_control: int = 0       # BOM / 零宽 / 控制字符
    dropped_format: int = 0        # 页码 / 页眉 / 页脚 / 水印
    dropped_blank: int = 0         # 连续空行合并掉的字符
    dropped_gibberish: int = 0     # 乱码检测移除

    @property
    def clean_ratio(self) -> float:
        """被清洗掉的字符比例（0.0~1.0）"""
        if self.original_chars == 0:
            return 0.0
        dropped = self.original_chars - self.cleaned_chars
        return max(0.0, min(1.0, dropped / self.original_chars))


@dataclass
class CleaningResult:
    """清洗结果"""
    display_content: str          # 展示层（保留结构）
    content: str                  # 检索层（纯文本）
    signals: CleaningSignals = field(default_factory=CleaningSignals)


@dataclass
class CleaningConfig:
    """清洗配置 — 所有 Stage 默认启用"""
    # Stage 1
    normalize_unicode: bool = True
    strip_control_chars: bool = True
    # Stage 2
    remove_page_numbers: bool = True
    remove_headers_footers: bool = True
    watermark_keywords: tuple[str, ...] = (
        "机密", "绝密", "内部资料", "仅供内部", "仅限内部", "confidential",
    )
    # Stage 3
    collapse_blank_lines: bool = True
    collapse_spaces: bool = True
    detect_gibberish: bool = True
    gibberish_threshold: float = 0.30   # 单行非常规字符比例 > 阈值则丢弃


# ═══════════════════════════════════════════════════════════
# 正则常量
# ═══════════════════════════════════════════════════════════

# 零宽字符 / BOM
_ZERO_WIDTH_RE = re.compile(r"[\u200B-\u200D\uFEFF\u2060]")

# C0/C1 控制字符（保留 \t \n \r）
_CONTROL_CHARS_RE = re.compile(r"[\x00-\x08\x0B\x0C\x0E-\x1F\x7F-\x9F]")

# 页码模式：
#   - 行内仅数字（1~5 位）
#   - "第 N 页"、"Page N"、"N / M"
_PAGE_NUMBER_PATTERNS = [
    re.compile(r"^\s*\d{1,5}\s*$"),
    re.compile(r"^\s*第\s*\d+\s*页\s*(/\s*共?\s*\d+\s*页\s*)?$"),
    re.compile(r"^\s*Page\s*\d+(\s*/\s*\d+)?\s*$", re.IGNORECASE),
    re.compile(r"^\s*-\s*\d+\s*-\s*$"),
    re.compile(r"^\s*\d+\s*/\s*\d+\s*$"),
]

# 连续空行（3+ 空行合并为 1）
_MULTI_BLANK_RE = re.compile(r"\n{3,}")

# 连续空格（非代码块内）
_MULTI_SPACE_RE = re.compile(r"[ \t]{3,}")


# ═══════════════════════════════════════════════════════════
# DocumentCleaningService
# ═══════════════════════════════════════════════════════════

class DocumentCleaningService:
    """4 Stage 清洗流水线"""

    def __init__(self, config: CleaningConfig | None = None) -> None:
        self._config = config or CleaningConfig()

    def clean(self, markdown: str) -> CleaningResult:
        """清洗文本，返回双层输出 + 信号"""
        if not markdown:
            return CleaningResult(display_content="", content="", signals=CleaningSignals())

        signals = CleaningSignals(original_chars=len(markdown))

        # Stage 1 — 编码清洗（Display + Content 共同基础）
        text = self._stage1_encoding(markdown, signals)

        # Stage 2 — 格式噪声（Content 层才做；Display 保留原始视觉结构中被认为无意义的部分）
        content_s2 = self._stage2_format_noise(text, signals)

        # Stage 3 — 内容噪声（连续空行、多余空格、乱码）
        content_s3 = self._stage3_content_noise(content_s2, signals)

        # Stage 4 — 双层输出
        # display：Stage 1 的产物（不做 Stage 2/3 的激进清洗，保留排版和表格 HTML/LaTeX）
        display = text
        # content：Stage 1~3 全部产物
        content = content_s3
        signals.cleaned_chars = len(content)

        logger.debug(
            "Cleaning done: %d → %d chars (ratio=%.3f, control=%d, format=%d, blank=%d, gibberish=%d)",
            signals.original_chars, signals.cleaned_chars, signals.clean_ratio,
            signals.dropped_control, signals.dropped_format,
            signals.dropped_blank, signals.dropped_gibberish,
        )
        return CleaningResult(display_content=display, content=content, signals=signals)

    # ── Stage 1: 编码清洗 ──

    def _stage1_encoding(self, text: str, sig: CleaningSignals) -> str:
        before = len(text)
        if self._config.normalize_unicode:
            text = unicodedata.normalize("NFC", text)
        if self._config.strip_control_chars:
            text = _ZERO_WIDTH_RE.sub("", text)
            text = _CONTROL_CHARS_RE.sub("", text)
        sig.dropped_control = max(0, before - len(text))
        return text

    # ── Stage 2: 格式噪声 ──

    def _stage2_format_noise(self, text: str, sig: CleaningSignals) -> str:
        if not (self._config.remove_page_numbers or self._config.remove_headers_footers):
            return text

        lines = text.split("\n")
        kept: list[str] = []
        dropped_chars = 0

        # 页眉/页脚识别：在文档前 20% / 后 20% 位置高频重复的短行
        header_footer: set[str] = set()
        if self._config.remove_headers_footers and len(lines) > 50:
            freq: dict[str, int] = {}
            for ln in lines:
                stripped = ln.strip()
                if 2 <= len(stripped) <= 60:
                    freq[stripped] = freq.get(stripped, 0) + 1
            # 出现 5 次以上且长度短的行判定为页眉/页脚
            for s, cnt in freq.items():
                if cnt >= 5 and not s.startswith(("#", "|", "-", "*", ">")):
                    header_footer.add(s)

        watermarks = [w.lower() for w in self._config.watermark_keywords]

        for ln in lines:
            stripped = ln.strip()

            # 页码
            if self._config.remove_page_numbers and any(
                p.match(stripped) for p in _PAGE_NUMBER_PATTERNS
            ):
                dropped_chars += len(ln) + 1
                continue

            # 页眉/页脚
            if stripped in header_footer:
                dropped_chars += len(ln) + 1
                continue

            # 水印（整行只包含水印关键词的那种场景）
            lower = stripped.lower()
            if lower and len(lower) <= 20 and any(w in lower for w in watermarks):
                dropped_chars += len(ln) + 1
                continue

            kept.append(ln)

        sig.dropped_format += dropped_chars
        return "\n".join(kept)

    # ── Stage 3: 内容噪声 ──

    def _stage3_content_noise(self, text: str, sig: CleaningSignals) -> str:
        before = len(text)

        # 连续空行折叠
        if self._config.collapse_blank_lines:
            text = _MULTI_BLANK_RE.sub("\n\n", text)

        # 连续空格压缩（避免误杀代码缩进：3+ 连续空格压成 2 个）
        if self._config.collapse_spaces:
            text = _MULTI_SPACE_RE.sub("  ", text)

        sig.dropped_blank += max(0, before - len(text))

        # 乱码检测：按行判定，非常规字符比例 > threshold 的行丢弃
        if self._config.detect_gibberish:
            before = len(text)
            kept: list[str] = []
            threshold = self._config.gibberish_threshold
            for ln in text.split("\n"):
                if not ln.strip():
                    kept.append(ln)
                    continue
                if self._is_gibberish(ln, threshold):
                    continue
                kept.append(ln)
            text = "\n".join(kept)
            sig.dropped_gibberish += max(0, before - len(text))

        return text

    @staticmethod
    def _is_gibberish(line: str, threshold: float) -> bool:
        """粗粒度乱码判定：高比例非 CJK / 非 ASCII 可打印字符 → 视为乱码"""
        if len(line) < 10:
            return False  # 太短的行不做乱码判定（可能是短标题）
        normal = 0
        total = 0
        for ch in line:
            total += 1
            # CJK 统一表意 / 常用标点 / 数字 / ASCII 可见
            code = ord(ch)
            if 0x4E00 <= code <= 0x9FFF:         # CJK Unified Ideographs
                normal += 1
            elif 0x3000 <= code <= 0x303F:       # CJK 符号和标点
                normal += 1
            elif 0xFF00 <= code <= 0xFFEF:       # 全角 ASCII
                normal += 1
            elif 0x20 <= code <= 0x7E:           # ASCII 可打印
                normal += 1
            elif ch in "\t":
                normal += 1
        if total == 0:
            return False
        ratio_abnormal = 1.0 - normal / total
        return ratio_abnormal > threshold
