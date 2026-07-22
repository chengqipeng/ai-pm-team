"""模拟 LangGraph 调用 Middleware 的流程

验证 builtin（本地）和 remote（FeignClient）middleware 在各生命周期阶段的执行。

对齐 neo-apps-ai-agent-service 中 create_agent(middleware=[...]) 后：
    START → before_agent → before_model → model → after_model → tools → (loop) → after_agent → END

本脚本模拟这个流程，手动调用每个 middleware 的对应钩子方法。
"""
from __future__ import annotations

import asyncio
import logging
import sys

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)


async def main():
    """模拟 LangGraph 调用 middleware 的完整生命周期"""
    from app.agent_loader import AgentLoader
    from app.agent_state import create_thread_state, create_configurable

    # ── 初始化 ──
    loader = AgentLoader()
    loader.load()

    # 获取所有 middleware（builtin + remote 已转换为 AgentMiddleware）
    middlewares = loader.get_middlewares()
    logger.info("=" * 60)
    logger.info("已加载 %d 个 AgentMiddleware:", len(middlewares))
    for m in middlewares:
        logger.info("  - %s (%s)", getattr(m, "name", "?"), type(m).__name__)
    logger.info("=" * 60)

    # ── 模拟图 state + configurable ──
    state = create_thread_state(user_input="查仁科的商机")
    configurable = create_configurable()

    # LangGraph 中 middleware 接收的 state 是 dict 视图
    # runtime 参数在 Demo 中用 None 占位（LangGraph Runtime 对象）
    runtime = None

    # ═══════════════════════════════════════════════════════════
    # 模拟 LangGraph 生命周期调用
    # ═══════════════════════════════════════════════════════════

    logger.info("\n▶ 阶段 1: before_agent（仅执行一次）")
    logger.info("-" * 40)
    for m in middlewares:
        name = getattr(m, "name", "?")
        # LangGraph 检测：只调用覆写了 before_agent 的 middleware
        from langchain.agents.middleware.types import AgentMiddleware
        if m.__class__.abefore_agent is not AgentMiddleware.abefore_agent:
            logger.info("  调用 %s.abefore_agent ...", name)
            try:
                result = await m.abefore_agent(state, runtime)
                logger.info("  → 返回: %s", _truncate(result))
                if isinstance(result, dict):
                    state.update(result)  # LangGraph 会 merge patch 到 state
            except Exception as e:
                logger.error("  → 异常: %s", e)
        elif m.__class__.before_agent is not AgentMiddleware.before_agent:
            logger.info("  调用 %s.before_agent ...", name)
            try:
                result = m.before_agent(state, runtime)
                logger.info("  → 返回: %s", _truncate(result))
                if isinstance(result, dict):
                    state.update(result)
            except Exception as e:
                logger.error("  → 异常: %s", e)

    logger.info("\n▶ 阶段 2: before_model（每个循环执行）")
    logger.info("-" * 40)
    for m in middlewares:
        name = getattr(m, "name", "?")
        if m.__class__.abefore_model is not AgentMiddleware.abefore_model:
            logger.info("  调用 %s.abefore_model ...", name)
            try:
                result = await m.abefore_model(state, runtime)
                logger.info("  → 返回: %s", _truncate(result))
            except Exception as e:
                logger.error("  → 异常: %s", e)
        elif m.__class__.before_model is not AgentMiddleware.before_model:
            logger.info("  调用 %s.before_model ...", name)
            try:
                result = m.before_model(state, runtime)
                logger.info("  → 返回: %s", _truncate(result))
            except Exception as e:
                logger.error("  → 异常: %s", e)

    logger.info("\n▶ 阶段 3: [模拟 LLM 返回 tool_call]")
    logger.info("-" * 40)
    logger.info("  LLM 返回: tool_calls=[{name:'query_customer', args:{...}}]")

    logger.info("\n▶ 阶段 4: after_model（LLM 返回后）")
    logger.info("-" * 40)
    for m in middlewares:
        name = getattr(m, "name", "?")
        if m.__class__.aafter_model is not AgentMiddleware.aafter_model:
            logger.info("  调用 %s.aafter_model ...", name)
            try:
                result = await m.aafter_model(state, runtime)
                logger.info("  → 返回: %s", _truncate(result))
            except Exception as e:
                logger.error("  → 异常: %s", e)
        elif m.__class__.after_model is not AgentMiddleware.after_model:
            logger.info("  调用 %s.after_model ...", name)
            try:
                result = m.after_model(state, runtime)
                logger.info("  → 返回: %s", _truncate(result))
            except Exception as e:
                logger.error("  → 异常: %s", e)

    logger.info("\n▶ 阶段 5: wrap_tool_call（工具调用包装）")
    logger.info("-" * 40)
    # 模拟 ToolCallRequest
    mock_request = type("MockRequest", (), {
        "tool_call": {"id": "call_001", "name": "query_customer", "args": {"customer_name": "仁科"}},
    })()

    async def mock_handler(request):
        """模拟工具执行 handler"""
        from langchain_core.messages import ToolMessage
        return ToolMessage(content='{"status":"success"}', tool_call_id=request.tool_call["id"])

    for m in middlewares:
        name = getattr(m, "name", "?")
        if m.__class__.awrap_tool_call is not AgentMiddleware.awrap_tool_call:
            logger.info("  调用 %s.awrap_tool_call ...", name)
            try:
                result = await m.awrap_tool_call(mock_request, mock_handler)
                content = getattr(result, "content", str(result))
                logger.info("  → 返回: %s", content[:100])
            except Exception as e:
                logger.error("  → 异常: %s", e)
        elif m.__class__.wrap_tool_call is not AgentMiddleware.wrap_tool_call:
            logger.info("  调用 %s.wrap_tool_call ...", name)
            try:
                result = m.wrap_tool_call(mock_request, lambda r: mock_handler(r))
                logger.info("  → 返回: %s", str(result)[:100])
            except Exception as e:
                logger.error("  → 异常: %s", e)

    logger.info("\n▶ 阶段 6: after_agent（仅执行一次，Agent 结束时）")
    logger.info("-" * 40)
    for m in middlewares:
        name = getattr(m, "name", "?")
        if m.__class__.aafter_agent is not AgentMiddleware.aafter_agent:
            logger.info("  调用 %s.aafter_agent ...", name)
            try:
                result = await m.aafter_agent(state, runtime)
                logger.info("  → 返回: %s", _truncate(result))
            except Exception as e:
                logger.error("  → 异常: %s", e)
        elif m.__class__.after_agent is not AgentMiddleware.after_agent:
            logger.info("  调用 %s.after_agent ...", name)
            try:
                result = m.after_agent(state, runtime)
                logger.info("  → 返回: %s", _truncate(result))
            except Exception as e:
                logger.error("  → 异常: %s", e)

    logger.info("\n" + "=" * 60)
    logger.info("✅ Middleware 生命周期模拟完成")
    logger.info("=" * 60)


def _truncate(obj, max_len=100):
    s = str(obj)
    return s[:max_len] + "..." if len(s) > max_len else s


if __name__ == "__main__":
    asyncio.run(main())
