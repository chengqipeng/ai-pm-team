"""关键词提取 — jieba TF-IDF 本地提取

对标 neo-ai-data-process-service 的 KeywordExtractServiceImpl。
不依赖 LLM，同步完成，作为 LLM 打标的辅助输入 + 降级兜底。

用法：
    extractor = KeywordExtractor()
    keywords = extractor.extract("文档全文...", top_k=20)
    # → ["压力变送器", "罗斯蒙特", "HART协议", ...]
"""
from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

# 停用词（高频无意义词）
_STOP_WORDS: set[str] = {
    "的", "了", "在", "是", "我", "有", "和", "就", "不", "人", "都", "一",
    "一个", "上", "也", "很", "到", "说", "要", "去", "你", "会", "着",
    "没有", "看", "好", "自己", "这", "他", "她", "它", "们", "那", "些",
    "什么", "怎么", "如何", "可以", "能", "但", "而", "或", "与", "及",
    "等", "中", "为", "以", "对", "从", "被", "把", "让", "向", "于",
    "其", "之", "所", "如", "则", "因", "此", "该", "本", "将", "已",
    "进行", "通过", "使用", "提供", "包括", "支持", "需要", "可能",
    "以及", "其中", "同时", "目前", "根据", "相关", "主要", "具有",
    "the", "a", "an", "is", "are", "was", "were", "be", "been",
    "being", "have", "has", "had", "do", "does", "did", "will",
    "would", "could", "should", "may", "might", "shall", "can",
    "of", "in", "to", "for", "with", "on", "at", "from", "by",
    "and", "or", "but", "not", "this", "that", "it", "as",
}

# 过滤：太短或纯数字/标点的词
_MIN_WORD_LEN = 2
_PURE_NUM_RE = re.compile(r"^[\d.,%+\-*/=<>]+$")
_PURE_PUNCT_RE = re.compile(r"^[\W_]+$")


class KeywordExtractor:
    """基于 jieba TF-IDF 的关键词提取器

    jieba 是纯 Python 实现，无需额外编译。首次调用时延迟加载。
    """

    def __init__(self, stop_words: set[str] | None = None) -> None:
        self._stop_words = stop_words or _STOP_WORDS
        self._jieba_loaded = False

    def _ensure_jieba(self) -> None:
        if self._jieba_loaded:
            return
        try:
            import jieba  # noqa: F401
            import jieba.analyse  # noqa: F401
            # 静默加载（jieba 首次加载会打印日志）
            jieba.setLogLevel(logging.WARNING)
            self._jieba_loaded = True
        except ImportError:
            raise RuntimeError(
                "jieba 未安装。请执行: pip install jieba。"
                "关键词提取需要 jieba 分词库。"
            )

    def extract(
        self,
        text: str,
        top_k: int = 20,
        with_weight: bool = False,
    ) -> list[str] | list[tuple[str, float]]:
        """提取关键词

        Args:
            text: 文档全文（建议传清洗后的 content）
            top_k: 返回数量
            with_weight: 是否返回 (keyword, weight) 元组

        Returns:
            关键词列表（按 TF-IDF 权重降序）
        """
        if not text or not text.strip():
            return []

        self._ensure_jieba()
        import jieba.analyse

        # jieba TF-IDF 提取
        raw = jieba.analyse.extract_tags(
            text,
            topK=top_k * 3,  # 多提一些，后面过滤
            withWeight=True,
        )

        # 过滤
        filtered: list[tuple[str, float]] = []
        for word, weight in raw:
            if len(word) < _MIN_WORD_LEN:
                continue
            if word.lower() in self._stop_words:
                continue
            if _PURE_NUM_RE.match(word):
                continue
            if _PURE_PUNCT_RE.match(word):
                continue
            filtered.append((word, weight))
            if len(filtered) >= top_k:
                break

        if with_weight:
            return filtered
        return [w for w, _ in filtered]

    def extract_with_textrank(
        self,
        text: str,
        top_k: int = 10,
    ) -> list[str]:
        """TextRank 提取（作为 TF-IDF 的补充，侧重语义关联）"""
        if not text or not text.strip():
            return []

        self._ensure_jieba()
        import jieba.analyse

        raw = jieba.analyse.textrank(
            text,
            topK=top_k * 2,
            withWeight=False,
        )

        # 过滤
        filtered: list[str] = []
        for word in raw:
            if len(word) < _MIN_WORD_LEN:
                continue
            if word.lower() in self._stop_words:
                continue
            if _PURE_NUM_RE.match(word):
                continue
            filtered.append(word)
            if len(filtered) >= top_k:
                break
        return filtered

    def extract_combined(
        self,
        text: str,
        top_k: int = 20,
    ) -> list[str]:
        """TF-IDF + TextRank 合并去重（覆盖面更广）

        策略：TF-IDF Top-15 + TextRank Top-10，合并去重后取 top_k。
        """
        tfidf = self.extract(text, top_k=15)
        textrank = self.extract_with_textrank(text, top_k=10)

        # 合并去重（保持 TF-IDF 优先顺序）
        seen: set[str] = set()
        combined: list[str] = []
        for w in tfidf + textrank:
            if w not in seen:
                seen.add(w)
                combined.append(w)
        return combined[:top_k]
