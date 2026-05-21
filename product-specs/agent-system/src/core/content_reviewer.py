"""用户输入毒性检测 — 入口层（QueryRewriter 之前）

## 设计原则

1. **入口层独立执行**
   不是 Middleware，在 /api/chat 等入口处、QueryRewriter 之前一次性调用。
   原因：毒性内容应该在进入任何 LLM 调用之前被拦截（包括改写 LLM）。

2. **阻断式拦截**
   毒性内容被拦截时，直接返回拒绝响应，不进入后续的改写、记忆检索、
   主 Agent 推理等任何环节，节省 LLM 成本。

3. **两层审查**
   - L1: 关键词快速拦截（0 延迟，覆盖已知敏感词）
   - L2: LLM 语义审查（~500ms，覆盖变体、谐音、隐晦攻击）

4. **记录到 trace，但不进推理链路**
   审查耗时和结果记录到 trace 的 content_review span，供排查。
   审查的 LLM 调用用 callbacks=[] 隔离，不污染主 Agent 流。

## 在架构中的位置

```
┌────────────────────────────────────────────────────────┐
│  入口层执行顺序（新）                                    │
│                                                         │
│  1. ★ ContentReviewer.review()  ← 本模块                │
│     └─ 命中 → 返回拒绝响应，流程终止                     │
│  2. QueryRewriter.rewrite()                            │
│  3. 主 Agent 循环                                       │
└────────────────────────────────────────────────────────┘
```
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

from ..middleware.content_review import ContentReviewService, ContentReviewResult

logger = logging.getLogger(__name__)


@dataclass
class ReviewDecision:
    """入口层毒性检测的最终决策"""
    passed: bool = True
    blocked_reason: str = ""
    blocked_keywords: list[str] = field(default_factory=list)
    duration_ms: float = 0.0


class ContentReviewer:
    """入口层毒性检测服务 — 包装 ContentReviewService

    相比 ContentReviewTransformer（middleware），本服务：
    - 在任何 LLM 调用之前执行（包括改写 LLM），彻底拦截恶意输入
    - 阻断式：返回 ReviewDecision.passed=False 时，调用方应立即返回拒绝响应
    - 显式 trace：记录 content_review span
    """

    def __init__(self, service: ContentReviewService | None = None):
        self._service = service

    async def review(
        self,
        user_input: str,
        *,
        thread_id: str | None = None,
    ) -> ReviewDecision:
        """对用户输入做毒性检测

        Args:
            user_input: 用户原始输入
            thread_id: 会话 ID，用于 trace 记录

        Returns:
            ReviewDecision.passed=True 表示通过，可继续处理
            ReviewDecision.passed=False 表示拦截，调用方应返回拒绝响应
        """
        start = time.monotonic()

        if self._service is None or not self._service.enabled:
            duration_ms = (time.monotonic() - start) * 1000
            self._record_span("input", True, [], "", duration_ms, thread_id, user_input)
            return ReviewDecision(passed=True, duration_ms=duration_ms)

        try:
            # LLM 调用通过 ContentReviewService 完成，该服务内部未接入 callbacks
            # 机制；但调用链 /api/chat → ContentReviewer.review 完全在 LangGraph
            # astream_events 之外，所以不会产生 on_chat_model_stream 事件。
            result: ContentReviewResult = self._service.review_input(user_input)
        except Exception as e:
            logger.error("[ContentReviewer] 审查异常，降级放行: %s", e)
            duration_ms = (time.monotonic() - start) * 1000
            self._record_span("input", True, [], f"异常降级: {e}", duration_ms, thread_id, user_input)
            return ReviewDecision(passed=True, duration_ms=duration_ms)

        duration_ms = (time.monotonic() - start) * 1000
        self._record_span(
            "input", result.passed, result.blocked_keywords,
            result.blocked_reason, duration_ms, thread_id, user_input,
        )

        if not result.passed:
            logger.warning("[ContentReviewer] 输入被拦截: keywords=%s reason=%s",
                           result.blocked_keywords, result.blocked_reason)

        return ReviewDecision(
            passed=result.passed,
            blocked_reason=result.blocked_reason or "您的输入包含不当内容，请文明交流。",
            blocked_keywords=result.blocked_keywords,
            duration_ms=duration_ms,
        )

    @staticmethod
    def _record_span(
        direction: str, passed: bool, blocked_keywords: list[str],
        blocked_reason: str, duration_ms: float, thread_id: str | None,
        user_input: str = "",
    ) -> None:
        """记录 content_review span 到 TracingMiddleware"""
        try:
            from src.middleware.tracing import tracing_middleware
            input_preview = (user_input[:200] + "...") if len(user_input) > 200 else user_input
            if thread_id:
                tracing_middleware._add_to_thread(
                    thread_id, "content_review", f"content_review_{direction}",
                    duration_ms, {
                        "direction": direction,
                        "passed": passed,
                        "blocked_keywords": blocked_keywords,
                        "blocked_reason": blocked_reason[:200],
                    },
                    input_data={
                        "text": input_preview,
                        "direction": direction,
                        "review_type": "toxicity + keyword",
                    },
                    output_data={
                        "passed": passed,
                        "blocked_keywords": blocked_keywords,
                        "blocked_reason": blocked_reason[:200] if not passed else "",
                    },
                    detail=(
                        f"{'输入' if direction == 'input' else '输出'}审查 → "
                        f"{'✅ 通过' if passed else '❌ 拦截: ' + (blocked_reason[:80] or '命中关键词')}"
                    ),
                )
            else:
                tracing_middleware.record_content_review(
                    direction=direction, passed=passed,
                    blocked_keywords=blocked_keywords,
                    blocked_reason=blocked_reason,
                    duration_ms=duration_ms,
                    user_input=input_preview,
                )
        except Exception as e:
            logger.debug("[ContentReviewer] 记录 span 失败（不影响功能）: %s", e)


# ═══════════════════════════════════════════════════════════
# 全局单例（懒加载）
# ═══════════════════════════════════════════════════════════

_global_reviewer: ContentReviewer | None = None


def get_content_reviewer() -> ContentReviewer:
    """获取全局 ContentReviewer 实例（懒加载）

    默认加载 data/content_review.yaml 的规则 + 入口改写 LLM 做语义审查。
    """
    global _global_reviewer
    if _global_reviewer is not None:
        return _global_reviewer

    import os
    try:
        from langchain_openai import ChatOpenAI
        model_name = os.environ.get("AGENT_MODEL", "deepseek-v4-flash")
        api_key = (os.environ.get("AGENT_API_KEY")
                   or os.environ.get("DEEPSEEK_API_KEY", "sk-HdY98AcN68JhtXLp8oeIATEL4PWq9rzRcCAhI8G4SOtBbtSw"))
        api_base = os.environ.get("AGENT_API_BASE", "https://tokenhub.tencentmaas.com/v1")

        llm = ChatOpenAI(
            model=model_name,
            api_key=api_key,
            base_url=api_base,
            max_tokens=128,
        )

        service = ContentReviewService(llm=llm, llm_review_enabled=True)
        _global_reviewer = ContentReviewer(service=service)
        logger.info("[ContentReviewer] 初始化完成: model=%s", model_name)
    except Exception as e:
        logger.warning("[ContentReviewer] 初始化失败，使用 noop: %s", e)
        _global_reviewer = ContentReviewer(service=None)

    return _global_reviewer


def set_content_reviewer(reviewer: ContentReviewer) -> None:
    """覆盖全局 ContentReviewer（测试用）"""
    global _global_reviewer
    _global_reviewer = reviewer
