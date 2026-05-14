"""文档质量评分 — 多维度综合评估

综合打分公式（0.0 ~ 1.0）：
    quality_score = 0.15·完整度 + 0.25·结构度 + 0.10·内容密度 + 0.10·清洗分数
                  + 0.20·信息丰富度 + 0.20·内容深度

分项信号：
    - completeness:    1 - failed_pages / total_pages
    - structure:       标题层级丰富度 + 段落长度合理性 + 目录深度
    - density:         非空白字符 / 总字符
    - clean_score:     1 - clean_ratio
    - richness:        信息丰富度（关键词多样性、数据点密度、专业术语覆盖）
    - depth:           内容深度（文档长度分级、段落展开度、列表/表格使用）

低于 0.4 的文档标记 quality_warning，检索时可选过滤。
"""
from __future__ import annotations

import json
import logging
import math
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
    richness: float = 0.0                    # 信息丰富度
    depth: float = 0.0                       # 内容深度
    signals: dict = field(default_factory=dict)

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
_H4_RE = re.compile(r"^####\s+", re.MULTILINE)

# 数据点正则（数字+单位、百分比、日期等）
_DATA_POINT_RE = re.compile(
    r"\d+[\.,]?\d*\s*[%％℃°]"       # 百分比、温度
    r"|\d+[\.,]\d+\s*[a-zA-Z]+"     # 数字+单位（如 3.5mm, 100kg）
    r"|\d{4}[-/]\d{1,2}[-/]\d{1,2}" # 日期
    r"|\$\s*\d+"                     # 金额
    r"|¥\s*\d+"                      # 人民币
)

# 列表项正则
_LIST_ITEM_RE = re.compile(r"^[\s]*[-*•]\s+|^\s*\d+[.)]\s+", re.MULTILINE)

# 表格行正则（Markdown 表格）
_TABLE_ROW_RE = re.compile(r"^\|.+\|$", re.MULTILINE)

# 图片引用
_IMAGE_RE = re.compile(r"!\[.*?\]\(.*?\)")


class DocumentQualityScorer:
    """文档质量评分器 — 6 维度综合评估"""

    def __init__(
        self,
        w_completeness: float = 0.15,
        w_structure: float = 0.25,
        w_density: float = 0.10,
        w_clean: float = 0.10,
        w_richness: float = 0.20,
        w_depth: float = 0.20,
    ) -> None:
        total = w_completeness + w_structure + w_density + w_clean + w_richness + w_depth
        assert abs(total - 1.0) < 1e-6, f"权重之和必须为 1.0，当前: {total}"

        self._w_c = w_completeness
        self._w_s = w_structure
        self._w_d = w_density
        self._w_clean = w_clean
        self._w_r = w_richness
        self._w_depth = w_depth

    def score(
        self,
        content: str,
        cleaning_signals: CleaningSignals | None = None,
        total_pages: int = 0,
        failed_pages: int = 0,
    ) -> QualityScoreResult:
        """计算综合质量分"""
        completeness = self._completeness(total_pages, failed_pages)
        structure = self._structure(content)
        density = self._density(content)
        clean_score = self._clean_score(cleaning_signals)
        richness = self._richness(content)
        depth = self._depth(content)

        score = (
            self._w_c * completeness
            + self._w_s * structure
            + self._w_d * density
            + self._w_clean * clean_score
            + self._w_r * richness
            + self._w_depth * depth
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
            richness=round(richness, 4),
            depth=round(depth, 4),
            signals=signals_dict,
        )
        logger.debug(
            "Quality scored: %.3f (c=%.2f s=%.2f d=%.2f clean=%.2f rich=%.2f depth=%.2f)",
            result.score, result.completeness, result.structure,
            result.density, result.clean_score, result.richness, result.depth,
        )
        return result

    # ── 子评分 ──

    @staticmethod
    def _completeness(total_pages: int, failed_pages: int) -> float:
        """完整度：1 - 失败页比例"""
        if total_pages <= 0:
            return 1.0
        failed_pages = max(0, min(failed_pages, total_pages))
        return 1.0 - failed_pages / total_pages

    def _structure(self, content: str) -> float:
        """结构度：标题层级丰富度 + 标题数量密度 + 段落长度合理性

        区分度改进：
        - 不仅看"有没有标题"，还看标题数量是否充足
        - 多级标题（H1+H2+H3+H4）比单级标题得分更高
        - 段落长度评估更严格
        """
        if not content:
            return 0.0

        content_len = len(content)

        # 标题层级丰富度（有多少级标题）
        h1_count = len(_H1_RE.findall(content))
        h2_count = len(_H2_RE.findall(content))
        h3_count = len(_H3_RE.findall(content))
        h4_count = len(_H4_RE.findall(content))
        total_headings = h1_count + h2_count + h3_count + h4_count

        # 层级数（用了几级标题）
        levels_used = sum([h1_count > 0, h2_count > 0, h3_count > 0, h4_count > 0])

        # 标题层级分：1级=0.3, 2级=0.6, 3级=0.85, 4级=1.0
        level_score = [0, 0.3, 0.6, 0.85, 1.0][min(levels_used, 4)]

        # 标题密度分：每 1000 字符应有 1-3 个标题为理想
        ideal_heading_per_1k = 2.0
        heading_density = (total_headings / max(1, content_len / 1000))
        if heading_density >= ideal_heading_per_1k:
            density_score = 1.0
        elif heading_density >= 0.5:
            density_score = heading_density / ideal_heading_per_1k
        else:
            density_score = 0.3  # 几乎没有标题

        # 段落长度合理性
        paragraphs = [p for p in content.split("\n\n") if p.strip()]
        if not paragraphs:
            para_score = 0.3
        else:
            avg_len = sum(len(p) for p in paragraphs) / len(paragraphs)
            # 理想段落长度 80-200 字符
            if 80 <= avg_len <= 200:
                para_score = 1.0
            elif 50 <= avg_len < 80 or 200 < avg_len <= 400:
                para_score = 0.8
            elif 30 <= avg_len < 50 or 400 < avg_len <= 800:
                para_score = 0.6
            elif avg_len < 30:
                para_score = 0.3  # 过于碎片化
            else:
                para_score = 0.4  # 段落过长，缺乏分段

        # 综合：层级 40% + 密度 30% + 段落 30%
        return level_score * 0.4 + density_score * 0.3 + para_score * 0.3

    def _density(self, content: str) -> float:
        """内容密度：非空白字符 / 总字符"""
        if not content:
            return 0.0
        total = len(content)
        non_blank = len(re.sub(r"\s", "", content))
        if total == 0:
            return 0.0
        ratio = non_blank / total
        if ratio >= self._ideal_density:
            return 1.0
        base = 0.3
        if ratio <= base:
            return 0.0
        return (ratio - base) / (self._ideal_density - base)

    @staticmethod
    def _clean_score(signals: CleaningSignals | None) -> float:
        """清洗分数：1 - clean_ratio"""
        if signals is None:
            return 1.0
        return max(0.0, 1.0 - signals.clean_ratio)

    def _richness(self, content: str) -> float:
        """信息丰富度：数据点密度 + 列表使用 + 表格使用 + 图片引用

        这个维度区分"信息密集的技术文档"和"空洞的概述文档"。
        """
        if not content:
            return 0.0

        content_len = len(content)
        chars_per_1k = max(1, content_len / 1000)

        # 数据点密度（数字、百分比、日期、金额等）
        data_points = len(_DATA_POINT_RE.findall(content))
        data_density = min(1.0, data_points / chars_per_1k / 3.0)  # 每千字 3 个数据点为满分

        # 列表使用（有序/无序列表项数量）
        list_items = len(_LIST_ITEM_RE.findall(content))
        list_score = min(1.0, list_items / chars_per_1k / 2.0)  # 每千字 2 个列表项为满分

        # 表格使用
        table_rows = len(_TABLE_ROW_RE.findall(content))
        table_score = min(1.0, table_rows / chars_per_1k / 1.5)  # 每千字 1.5 行表格为满分

        # 图片引用
        images = len(_IMAGE_RE.findall(content))
        image_score = min(1.0, images / chars_per_1k / 0.5)  # 每千字 0.5 张图为满分

        # 综合：数据点 40% + 列表 25% + 表格 20% + 图片 15%
        return data_density * 0.4 + list_score * 0.25 + table_score * 0.2 + image_score * 0.15

    def _depth(self, content: str) -> float:
        """内容深度：文档长度分级 + 段落展开度 + 内容多样性

        区分"简短说明"和"深度详尽的手册"。
        """
        if not content:
            return 0.0

        content_len = len(content)

        # 文档长度分级（对数曲线，避免线性增长）
        # 500字=0.2, 2000字=0.5, 5000字=0.7, 10000字=0.85, 20000字=0.95, 50000字=1.0
        if content_len <= 0:
            length_score = 0.0
        else:
            length_score = min(1.0, math.log(content_len / 500 + 1) / math.log(100))

        # 段落展开度：段落数量是否充足
        paragraphs = [p for p in content.split("\n\n") if p.strip() and len(p.strip()) > 20]
        para_count = len(paragraphs)
        # 10 段=0.5, 30 段=0.8, 50 段=1.0
        para_depth = min(1.0, para_count / 50)

        # 内容多样性：不同类型内容的混合度
        has_headings = bool(_H2_RE.search(content) or _H3_RE.search(content))
        has_lists = bool(_LIST_ITEM_RE.search(content))
        has_tables = bool(_TABLE_ROW_RE.search(content))
        has_images = bool(_IMAGE_RE.search(content))
        has_code = bool(re.search(r"```", content))
        diversity_count = sum([has_headings, has_lists, has_tables, has_images, has_code])
        diversity_score = min(1.0, diversity_count / 3.0)  # 3 种以上内容类型为满分

        # 综合：长度 40% + 段落展开 30% + 多样性 30%
        return length_score * 0.4 + para_depth * 0.3 + diversity_score * 0.3

    @property
    def _ideal_density(self) -> float:
        return 0.7
