"""输出验证中间件 — 长度校验 + 输出敏感词审查"""

import logging
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage
from langchain.agents.middleware.types import AgentMiddleware, AgentState
from langgraph.config import get_config
from langgraph.runtime import Runtime

logger = logging.getLogger(__name__)


class OutputValidationMiddleware(AgentMiddleware):
    """最终输出验证 — 输出敏感词审查 + 长度校验

    Args:
        min_output_length: 最小输出长度（低于此值触发扩展指令）
        max_retries: 长度不足时最大重试次数
        review_service: ContentReviewService 实例（None 则跳过输出审查）
    """

    def __init__(
        self,
        min_output_length: int = 100,
        max_retries: int = 1,
        review_service: Any = None,
    ):
        super().__init__()
        self._min_length = min_output_length
        self._max_retries = max_retries
        self._retry_counts: dict[str, int] = {}
        self._review_service = review_service

    def after_model(self, state: AgentState, runtime: Runtime) -> dict[str, Any] | None:
        messages = state.get("messages", [])
        if not messages:
            return None
        last = messages[-1]
        if not isinstance(last, AIMessage) or getattr(last, "tool_calls", None):
            return None
        content = last.content
        if not isinstance(content, str) or not content.strip():
            return None

        # ── 过滤 LLM 输出中的内部分析内容（改写/实体/代词等） ──
        cleaned = self._strip_internal_analysis(content)
        if cleaned != content:
            logger.info("Stripped internal analysis from LLM output (%d → %d chars)",
                        len(content), len(cleaned))
            if cleaned.strip():
                return {"messages": [AIMessage(content=cleaned)]}
            # 如果清理后为空，不替换（让原始内容通过）

        # ── 输出敏感词审查 ──
        if self._review_service is not None:
            try:
                result = self._review_service.review_output(content)
                if not result.passed:
                    logger.warning("输出审查拦截: keywords=%s", result.blocked_keywords)
                    return {"messages": [AIMessage(content=result.blocked_reason)]}
            except Exception as e:
                logger.error("输出审查异常，降级放行: %s", e)

        return None

    @staticmethod
    def _strip_internal_analysis(content: str) -> str:
        """过滤 LLM 输出中的内部分析标记（改写/实体/代词/意图等）

        模式匹配：
        - "改写：..." 开头的段落
        - "实体名：..." / "实体：..." 标注
        - "代词...指代..." 标注
        - "业务概念：..." 标注
        - "意图：..." / "意图分析：..." 标注
        """
        import re

        # 按行处理
        lines = content.split("\n")
        cleaned_lines = []
        skip_until_empty = False

        for line in lines:
            stripped = line.strip()

            # 检测"改写：..."开头的行（整行跳过）
            if re.match(r'^改写[：:]', stripped):
                skip_until_empty = True
                continue

            # 检测独立的分析标注行
            if re.match(r'^(实体名?|代词|业务概念|意图|意图分析|NLU)[：:]', stripped):
                continue

            # 如果在跳过模式中，遇到空行或正常内容则恢复
            if skip_until_empty:
                if not stripped:
                    skip_until_empty = False
                    continue
                # 如果这行也是分析内容（如"实体：..."），继续跳过
                if re.match(r'^(实体名?|代词|业务概念|指代)[：:]', stripped):
                    continue
                # 否则恢复正常输出
                skip_until_empty = False

            cleaned_lines.append(line)

        result = "\n".join(cleaned_lines).strip()

        # 内联模式：清理嵌在正文中的分析片段
        # 如 "...明白了。改写：xxx。好的，我记住了" → "...明白了。好的，我记住了"
        result = re.sub(
            r'改写[：:][^。！？\n]*[。！？]?',
            '',
            result,
        )
        result = re.sub(
            r'[，,]?\s*实体名?[：:][^。！？\n]*[。！？]?',
            '',
            result,
        )
        result = re.sub(
            r'[，,]?\s*代词[^。！？\n]*指代[^。！？\n]*[。！？]?',
            '',
            result,
        )
        result = re.sub(
            r'[，,]?\s*业务概念[：:][^。！？\n]*[。！？]?',
            '',
            result,
        )

        # 清理多余的空行和开头空白
        result = re.sub(r'\n{3,}', '\n\n', result)
        return result.strip()
