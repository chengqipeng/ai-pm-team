"""文档质量评分 — 对标 QualityScoreServiceImpl

综合打分公式（0.0 ~ 1.0）：
    quality_score = 0.3·完整度 + 0.3·结构度 + 0.2·内容密度 + 0.2·清洗分数

分项信号：
    - completeness: 1 - failed_pages / total_pages
    - structure:    标题覆盖率（有 H1/H2/H3 的占比）+ 平均段落长度合理性
    - density:      非空白字符 / 总字符，理想 ≥0.7
    - clean_score:  1 - clean_ratio（清洗比例越低越好）

低于 0.4 的文档标记 quality_warning，检索时可选过滤。
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import asdict, dataclass, field

from .cleaning import CleaningSignals

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════
# 结果模型
# ═══════════════════════════════════════════════════════════

@dataclass
class QualityScoreResult:
    """质量评分结果"""
    score: float = 0.0                       # 综合分 0.0~1.0
    completeness: float = 0.0
    structure: float = 0.0
    density: float = 0.0
    clean_score: float = 0.0
    signals: dict = field(default_factory=dict)   # 原始输入信号（入库时存到 quality_signals 字段）

    @property
    def is_warning(self) -> bool:
        return self.score < 0.4

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False)


# ═══════════════════════════════════════════════════════════
# DocumentQualityScorer
# ═══════════════════════════════════════════════════════════

# Markdown 标题正则
_H1_RE = re.compile(r"^#\s+", re.MULTILINE)
_H2_RE = re.compile(r"^##\s+", re.MULTILINE)
_H3_RE = re.compile(r"^###\s+", re.MULTILINE)


class DocumentQualityScorer:
    """文档质量评分器"""

    def __init__(
        self,
        w_completeness: float = 0.3,
        w_structure: float = 0.3,
        w_density: float = 0.2,
        w_clean: float = 0.2,
        ideal_density: float = 0.7,
        ideal_paragraph_len: int = 100,
    ) -> None:
        # 权重必须归一
        total = w_completeness + w_structure + w_density + w_clean
        assert abs(total - 1.0) < 1e-6, f"权重之和必须为 1.0，当前: {total}"

        self._w_c = w_completeness
        self._w_s = w_structure
        self._w_d = w_density
        self._w_clean = w_clean
        self._ideal_density = ideal_density
        self._ideal_paragraph_len = ideal_paragraph_len

    def score(
        self,
        content: str,
        cleaning_signals: CleaningSignals | None = None,
        total_pages: int = 0,
        failed_pages: int = 0,
    ) -> QualityScoreResult:
        """计算综合质量分

        Args:
            content: 清洗后的文本（用于结构/密度评估）
            cleaning_signals: 清洗信号（用于 clean_score）
            total_pages: 总页数（完整度计算）
            failed_pages: 解析失败页数
        """
        completeness = self._completeness(total_pages, failed_pages)
        structure = self._structure(content)
        density = self._density(content)
        clean_score = self._clean_score(cleaning_signals)

        score = (
            self._w_c * completeness
            + self._w_s * structure
            + self._w_d * density
            + self._w_clean * clean_score
        )

        signals_dict = {
            "total_pages": total_pages,
            "failed_pages": failed_pages,
            "content_chars": len(content),
        }
        if cleaning_signals:
            signals_dict.update({
                "clean_ratio": round(cleaning_signals.clean_ratio, 4),
                "dropped_control": cleaning_signals.dropped_control,
                "dropped_format": cleaning_signals.dropped_format,
                "dropped_blank": cleaning_signals.dropped_blank,
                "dropped_gibberish": cleaning_signals.dropped_gibberish,
            })

        result = QualityScoreResult(
            score=round(max(0.0, min(1.0, score)), 4),
            completeness=round(completeness, 4),
            structure=round(structure, 4),
            density=round(density, 4),
            clean_score=round(clean_score, 4),
            signals=signals_dict,
        )
        logger.debug(
            "Quality scored: %.3f (c=%.2f s=%.2f d=%.2f clean=%.2f)",
            result.score, result.completeness, result.structure,
            result.density, result.clean_score,
        )
        return result

    # ── 子评分 ──

    @staticmethod
    def _completeness(total_pages: int, failed_pages: int) -> float:
        """完整度：1 - 失败页比例"""
        if total_pages <= 0:
            return 1.0    # 无分页概念（如 TXT/MD）→ 视为完整
        failed_pages = max(0, min(failed_pages, total_pages))
        return 1.0 - failed_pages / total_pages

    def _structure(self, content: str) -> float:
        """结构度：标题覆盖率 × 0.5 + 段落长度合理性 × 0.5"""
        if not content:
            return 0.0

        # 标题覆盖率：有 H1 → 0.4，有 H2 → +0.3，有 H3 → +0.3
        has_h1 = bool(_H1_RE.search(content))
        has_h2 = bool(_H2_RE.search(content))
        has_h3 = bool(_H3_RE.search(content))
        heading = (0.4 if has_h1 else 0) + (0.3 if has_h2 else 0) + (0.3 if has_h3 else 0)

        # 段落长度合理性：平均段落长度越接近 ideal 分数越高
        paragraphs = [p for p in content.split("\n\n") if p.strip()]
        if not paragraphs:
            return heading * 0.5
        avg_len = sum(len(p) for p in paragraphs) / len(paragraphs)
        # 偏离 ideal_paragraph_len 越远越低；极短（< 20）或极长（> 5×ideal）都降分
        if avg_len < 20:
            para_score = 0.3
        elif avg_len > self._ideal_paragraph_len * 5:
            para_score = 0.5   # 长段落常见于合同类文档，不至于太差
        else:
            # 以 ideal 为中心的高斯衰减（简化为线性）
            dev = abs(avg_len - self._ideal_paragraph_len) / self._ideal_paragraph_len
            para_score = max(0.4, 1.0 - min(dev, 1.0) * 0.5)

        return heading * 0.5 + para_score * 0.5

    def _density(self, content: str) -> float:
        """内容密度：非空白字符 / 总字符

        理想密度 0.7：达标得满分，向下线性衰减到 0.3 时得 0 分。
        """
        if not content:
            return 0.0
        total = len(content)
        non_blank = len(re.sub(r"\s", "", content))
        if total == 0:
            return 0.0
        ratio = non_blank / total
        if ratio >= self._ideal_density:
            return 1.0
        # 线性插值：ratio = 0.3 → 0.0， ratio = ideal → 1.0
        base = 0.3
        if ratio <= base:
            return 0.0
        return (ratio - base) / (self._ideal_density - base)

    @staticmethod
    def _clean_score(signals: CleaningSignals | None) -> float:
        """清洗分数：1 - clean_ratio（清洗掉的越少越好）

        无信号时视为 1.0（保守）。
        """
        if signals is None:
            return 1.0
        return max(0.0, 1.0 - signals.clean_ratio)
