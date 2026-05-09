"""ContentReviewer 入口层毒性检测测试"""
import asyncio
from src.core.content_reviewer import ContentReviewer, ReviewDecision
from src.middleware.content_review import (
    ContentReviewService, ContentReviewRule, ContentReviewResult,
)
from src.middleware.tracing import tracing_middleware


def _fresh_tracer(thread_id: str):
    """清理 thread_id 对应的 spans，避免测试间污染"""
    tracing_middleware.clear(thread_id)


async def test_no_service_pass_through():
    """未配置 ContentReviewService 时全部放行"""
    reviewer = ContentReviewer(service=None)
    decision = await reviewer.review("任意内容")
    assert decision.passed is True
    print("✓ test_no_service_pass_through")


async def test_clean_input_pass():
    """干净输入通过审查"""
    _fresh_tracer("t1")
    service = ContentReviewService(
        rules=[ContentReviewRule(keywords=["脏话", "违禁词"])],
    )
    reviewer = ContentReviewer(service=service)
    decision = await reviewer.review("我负责华东区", thread_id="t1")
    assert decision.passed is True
    spans = tracing_middleware.get_spans("t1")
    assert any(s["type"] == "content_review" for s in spans), "应该记录 span"
    span = next(s for s in spans if s["type"] == "content_review")
    assert span["metadata"]["passed"] is True
    print(f"✓ test_clean_input_pass (记录 span: {span['metadata']})")


async def test_blocked_input():
    """命中敏感词的输入被拦截"""
    _fresh_tracer("t2")
    service = ContentReviewService(
        rules=[ContentReviewRule(
            keywords=["违禁词A", "违禁词B"],
            input_message="您的输入包含不当内容",
        )],
    )
    reviewer = ContentReviewer(service=service)
    decision = await reviewer.review("用户说了违禁词A什么的", thread_id="t2")
    assert decision.passed is False
    assert "违禁词A" in decision.blocked_keywords
    assert decision.blocked_reason == "您的输入包含不当内容"

    spans = tracing_middleware.get_spans("t2")
    review_span = next(s for s in spans if s["type"] == "content_review")
    assert review_span["metadata"]["passed"] is False
    assert "违禁词A" in review_span["metadata"]["blocked_keywords"]
    print(f"✓ test_blocked_input (拦截: {decision.blocked_keywords})")


async def test_llm_error_fallback_pass():
    """ContentReviewService.review_input 抛异常时降级放行"""
    _fresh_tracer("t3")

    class BrokenService:
        @property
        def enabled(self):
            return True

        def review_input(self, content):
            raise RuntimeError("mock failure")

    reviewer = ContentReviewer(service=BrokenService())
    decision = await reviewer.review("正常输入", thread_id="t3")
    assert decision.passed is True, "异常应降级放行"
    print("✓ test_llm_error_fallback_pass")


async def test_span_recorded_on_thread():
    """验证 span 被正确记录到指定 thread_id"""
    _fresh_tracer("t4")
    service = ContentReviewService(
        rules=[ContentReviewRule(keywords=["fuck"])],
    )
    reviewer = ContentReviewer(service=service)
    await reviewer.review("fuck you", thread_id="t4")
    spans = tracing_middleware.get_spans("t4")
    assert len(spans) == 1
    assert spans[0]["type"] == "content_review"
    assert spans[0]["metadata"]["direction"] == "input"
    print(f"✓ test_span_recorded_on_thread: {spans[0]['name']}")


async def main():
    print("=" * 70)
    print("  ContentReviewer 单元测试")
    print("=" * 70)
    await test_no_service_pass_through()
    await test_clean_input_pass()
    await test_blocked_input()
    await test_llm_error_fallback_pass()
    await test_span_recorded_on_thread()
    print("=" * 70)
    print("  ✓ 所有测试通过")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())
