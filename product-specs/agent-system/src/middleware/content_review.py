"""内容审查服务 — 敏感词匹配 + 配置管理

对齐老项目 ContentReviewService + ContentReviewConfig，
提供输入审查和输出审查的统一能力。

配置来源优先级：
1. 构造时直接传入 rules
2. 配置文件 data/content_review.yaml
3. 无配置 → 审查关闭（全部放行）

错误处理：审查异常时降级放行，不阻断 Agent 主流程。
"""
from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

_DEFAULT_CONFIG_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "data", "content_review.yaml",
)


@dataclass
class ContentReviewRule:
    """单条审查规则 — 对齐老项目 ContentReviewConfig"""
    keywords: list[str] = field(default_factory=list)
    input_message: str = "您的输入包含不当内容，请修改后重试。"
    output_message: str = "回复内容包含不当信息，已被系统拦截。"
    is_input: bool = True
    is_output: bool = True
    case_sensitive: bool = False
    _pattern: re.Pattern | None = field(default=None, repr=False)

    def compile(self) -> None:
        """编译关键词为正则（按长度降序，避免短词前缀匹配长词）"""
        if not self.keywords:
            self._pattern = None
            return
        sorted_kw = sorted(self.keywords, key=len, reverse=True)
        escaped = [re.escape(kw) for kw in sorted_kw if kw.strip()]
        if not escaped:
            self._pattern = None
            return
        flags = 0 if self.case_sensitive else re.IGNORECASE
        self._pattern = re.compile("|".join(escaped), flags)

    def match(self, text: str) -> list[str]:
        """返回命中的敏感词列表"""
        if self._pattern is None:
            return []
        return list(set(self._pattern.findall(text)))


@dataclass
class ContentReviewResult:
    """审查结果"""
    passed: bool = True
    blocked_keywords: list[str] = field(default_factory=list)
    blocked_reason: str = ""


class ContentReviewService:
    """内容审查服务 — 加载配置 + 执行输入/输出审查"""

    def __init__(
        self,
        rules: list[ContentReviewRule] | None = None,
        config_path: str | None = None,
        enabled: bool = True,
    ) -> None:
        self._enabled = enabled
        self._rules: list[ContentReviewRule] = []

        if rules:
            self._rules = rules
        else:
            path = config_path or _DEFAULT_CONFIG_PATH
            if os.path.exists(path):
                self._load_config(path)

        for rule in self._rules:
            rule.compile()

    def _load_config(self, path: str) -> None:
        try:
            import yaml
            with open(path, encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            self._enabled = data.get("enabled", True)
            for item in data.get("rules", []):
                self._rules.append(ContentReviewRule(
                    keywords=item.get("keywords", []),
                    input_message=item.get("input_message", "您的输入包含不当内容，请修改后重试。"),
                    output_message=item.get("output_message", "回复内容包含不当信息，已被系统拦截。"),
                    is_input=item.get("is_input", True),
                    is_output=item.get("is_output", True),
                    case_sensitive=item.get("case_sensitive", False),
                ))
        except Exception as e:
            logger.error("内容审查配置加载失败，降级为关闭: %s", e)
            self._enabled = False

    @property
    def enabled(self) -> bool:
        return self._enabled and bool(self._rules)

    def review_input(self, content: str) -> ContentReviewResult:
        """输入审查 — 审查异常时降级放行"""
        if not self.enabled:
            return ContentReviewResult(passed=True)
        try:
            for rule in self._rules:
                if not rule.is_input:
                    continue
                hits = rule.match(content)
                if hits:
                    logger.warning("输入审查命中: %s", hits)
                    return ContentReviewResult(
                        passed=False, blocked_keywords=hits,
                        blocked_reason=rule.input_message,
                    )
        except Exception as e:
            logger.error("输入审查异常，降级放行: %s", e)
        return ContentReviewResult(passed=True)

    def review_output(self, content: str) -> ContentReviewResult:
        """输出审查 — 审查异常时降级放行"""
        if not self.enabled:
            return ContentReviewResult(passed=True)
        try:
            for rule in self._rules:
                if not rule.is_output:
                    continue
                hits = rule.match(content)
                if hits:
                    logger.warning("输出审查命中: %s", hits)
                    return ContentReviewResult(
                        passed=False, blocked_keywords=hits,
                        blocked_reason=rule.output_message,
                    )
        except Exception as e:
            logger.error("输出审查异常，降级放行: %s", e)
        return ContentReviewResult(passed=True)
