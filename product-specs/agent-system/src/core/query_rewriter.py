"""用户问题改写服务 — 入口层 NLU 预处理

## 设计原则

1. **独立服务，不是 Middleware**
   完全脱离 LangGraph 执行上下文。LLM 调用不会被主 Agent 的 astream_events
   捕获，不会出现在用户可见的事件流和 trace 中。

2. **一次性前处理**
   仅在请求入口处（/api/chat 或 adapter.execute 等）调用一次，结果直接作为
   Agent 的输入。主 Agent 循环内不再触发任何改写。

3. **替换，不是注入**
   改写结果直接替换用户的 HumanMessage.content。Agent 看到的是一句干净、
   自包含的问题，看不到任何"改写""原文""真实意图"等上下文提示。

4. **不污染推理链路**
   改写调用的 LLM 事件被显式禁用 callbacks，不会出现在：
   - 主 Agent 的 astream_events 流
   - TracingMiddleware 记录的 span
   - 前端推理链路面板

## 在架构中的位置

```
┌────────────────────────────────────────────────────────────┐
│  [入口层] server.py / adapter.execute                       │
│                                                             │
│  1. 收到 request                                            │
│  2. 构建 history messages                                   │
│  3. ★ await QueryRewriter.rewrite(history, user_input)     │
│     └─ 独立 LLM 调用，callbacks=[]，不进任何 trace         │
│  4. 把改写后的 query 作为 HumanMessage 追加                 │
│  5. 调用 agent.astream_events(...)                          │
└────────────────────────────────────────────────────────────┘
                           ↓
┌────────────────────────────────────────────────────────────┐
│  [主 Agent 循环] 用户可见流                                  │
│                                                             │
│  LLM 只看到干净的 messages 列表                             │
│  无 <query_context>、无 SystemMessage 注入                  │
│  推理链路里不存在 query_rewrite 节点                        │
└────────────────────────────────────────────────────────────┘
```
"""
from __future__ import annotations

import logging
import re
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, AIMessage, BaseMessage

logger = logging.getLogger(__name__)


# 常见的 LLM 输出前缀（改写不应该包含这些）
_OUTPUT_PREFIXES = (
    "改写后的查询：", "改写后的查询:",
    "改写后的检索关键词：", "改写后的检索关键词:",
    "改写后：", "改写后:",
    "改写：", "改写:",
    "Rewrite:", "rewrite:", "Query:", "query:",
)

# 分析标注的清理正则（改写不应该包含这些）
_ANNOTATION_PATTERNS = [
    re.compile(r"[，,；;]\s*实体名?[：:][^。！？\n]*"),
    re.compile(r"[，,；;]\s*代词[^。！？\n]*"),
    re.compile(r"[，,；;]\s*指代[^。！？\n]*"),
    re.compile(r"[，,；;]\s*业务概念[：:][^。！？\n]*"),
    re.compile(r"[，,；;]\s*提取实体[：:][^。！？\n]*"),
    re.compile(r"[，,；;]\s*意图[分析]*[：:][^。！？\n]*"),
]


class QueryRewriter:
    """用户问题改写服务"""

    def __init__(self, llm: BaseChatModel | None = None, enabled: bool = True):
        self._llm = llm
        self._enabled = enabled

    async def rewrite(
        self,
        history_messages: list[BaseMessage],
        current_query: str,
        *,
        thread_id: str | None = None,
    ) -> str:
        """改写当前用户查询

        Args:
            history_messages: 历史对话（不含当前消息）
            current_query: 当前用户输入
            thread_id: 会话 ID，用于 trace 记录（可选）

        Returns:
            改写后的查询。以下情况返回原查询：
            - 未启用 / 没有 LLM
            - 单轮对话（无历史）
            - LLM 调用失败
            - 改写结果不合理
        """
        import time
        start = time.monotonic()

        if not self._enabled or not self._llm or not current_query.strip():
            self._record_span(current_query, current_query, False,
                              (time.monotonic() - start) * 1000, thread_id)
            return current_query

        # 单轮对话不改写（无历史可参考）
        has_history = any(
            isinstance(m, (HumanMessage, AIMessage))
            and isinstance(m.content, str) and m.content.strip()
            for m in history_messages
        )
        if not has_history:
            self._record_span(current_query, current_query, False,
                              (time.monotonic() - start) * 1000, thread_id)
            return current_query

        try:
            rewritten = await self._rewrite_with_llm(history_messages, current_query)
        except Exception as e:
            logger.warning("[QueryRewriter] 改写失败，使用原查询: %s", e)
            rewritten = current_query

        duration_ms = (time.monotonic() - start) * 1000
        self._record_span(current_query, rewritten,
                          rewritten != current_query, duration_ms, thread_id)
        return rewritten

    @staticmethod
    def _record_span(
        original: str, rewritten: str, changed: bool,
        duration_ms: float, thread_id: str | None,
    ) -> None:
        """向 TracingMiddleware 记录改写 span（可选）

        仅记录输入/输出/耗时元数据，不会泄露 LLM 调用事件到主 Agent 流。
        """
        try:
            from src.middleware.tracing import tracing_middleware
            # TracingMiddleware 用 contextvar 获取 thread_id，手动记录时需要伪造上下文
            if thread_id:
                from langgraph.config import get_config as _gc
                # 最佳努力：优先用当前 runtime config；否则直接写入指定 thread_id
                tracing_middleware._add_to_thread(
                    thread_id, "query_rewrite", "query_rewrite", duration_ms,
                    {
                        "original_query": original[:500],
                        "rewritten_query": rewritten[:500],
                        "changed": changed,
                        "source": "entry",
                    },
                )
            else:
                tracing_middleware.record_query_rewrite(
                    original_query=original, rewritten_query=rewritten,
                    changed=changed, duration_ms=duration_ms,
                )
        except Exception as e:
            logger.debug("[QueryRewriter] 记录 span 失败（不影响功能）: %s", e)

    async def _rewrite_with_llm(
        self,
        history_messages: list[BaseMessage],
        current_query: str,
    ) -> str:
        # 构建对话上下文（最近 5 轮）
        context_lines: list[str] = []
        count = 0
        for msg in reversed(history_messages):
            if not isinstance(msg, (HumanMessage, AIMessage)):
                continue
            content = msg.content if isinstance(msg.content, str) else str(msg.content)
            if not content.strip():
                continue
            role = "用户" if isinstance(msg, HumanMessage) else "助手"
            context_lines.insert(0, f"{role}: {content[:200]}")
            count += 1
            if count >= 10:  # 最多 5 轮
                break

        if not context_lines:
            return current_query

        context_block = "\n".join(context_lines)
        prompt = (
            "你是 CRM 系统的查询改写模块。将用户最新问题改写为一句自包含的完整查询。\n\n"
            "## 规则\n"
            "1. 代词替换：将 他/她/它/那个/这个/第N个/后面那个/最大的 替换为上文对应的具体名称\n"
            "2. 省略补全：补全被省略的主语、宾语、时间范围或筛选条件\n"
            "3. 条件继承：当用户说 换成X/改成X/X呢 时，保留原查询结构，只替换变化的条件\n"
            "4. 指令补全：当用户说 对/好的/以后都这样 确认某个设置时，将确认的完整内容补全\n"
            "5. 不改写：如果最新问题已经自包含（不依赖上下文就能理解），原样输出\n"
            "6. 不添加：禁止添加上文未提及的信息，禁止推测用户未表达的意图\n\n"
            "## 输出格式\n"
            "- 只输出一句改写后的查询\n"
            "- 不输出分析过程、不标注实体、不解释代词\n"
            "- 不超过 80 字\n\n"
            f"## 对话上下文\n{context_block}\n\n"
            f"## 用户最新问题\n{current_query}\n\n"
            "## 改写结果\n"
        )

        # 关键：callbacks=[] 阻止事件传播到主 Agent 的 astream_events 流
        # tags 便于日志排查（不暴露给前端）
        result = await self._llm.ainvoke(
            prompt,
            config={
                "callbacks": [],
                "tags": ["__query_rewriter_internal__"],
                "run_name": "query_rewriter_internal",
            },
        )

        rewritten = getattr(result, "content", None) or str(result)
        rewritten = self._clean_output(rewritten)

        # 合理性校验
        if not rewritten:
            return current_query
        if len(rewritten) > 150:
            logger.warning("[QueryRewriter] 输出过长 (%d 字)，使用原查询", len(rewritten))
            return current_query
        # 句号过多通常表示 LLM 在输出解释而不是查询
        if rewritten.count("。") > 1:
            logger.warning("[QueryRewriter] 输出含多个句号，使用原查询: %s", rewritten[:80])
            return current_query

        logger.info("[QueryRewriter] '%s' → '%s'",
                    current_query[:60], rewritten[:60])
        return rewritten

    @staticmethod
    def _clean_output(text: str) -> str:
        """清洗 LLM 改写输出 — 去除前缀和分析标注"""
        text = text.strip()

        # 去除常见前缀
        for prefix in _OUTPUT_PREFIXES:
            if text.startswith(prefix):
                text = text[len(prefix):].strip()
                break

        # 去除分析标注（实体/代词/业务概念等）
        for pattern in _ANNOTATION_PATTERNS:
            text = pattern.sub("", text)

        # 去除引号包裹
        if len(text) >= 2:
            pairs = [('"', '"'), ("'", "'"), ("\u201c", "\u201d"), ("\u2018", "\u2019")]
            for lq, rq in pairs:
                if text[0] == lq and text[-1] == rq:
                    text = text[1:-1]
                    break

        return text.strip()


# ═══════════════════════════════════════════════════════════
# 全局单例（懒加载）
# ═══════════════════════════════════════════════════════════

_global_rewriter: QueryRewriter | None = None


def get_query_rewriter() -> QueryRewriter:
    """获取全局 QueryRewriter 实例（懒加载）

    默认使用 AGENT_MODEL / AGENT_API_KEY / AGENT_API_BASE 环境变量，
    未配置时回退到豆包 lite 模型。
    """
    global _global_rewriter
    if _global_rewriter is not None:
        return _global_rewriter

    import os
    try:
        from langchain_openai import ChatOpenAI
        model_name = os.environ.get("AGENT_MODEL", "doubao-seed-2-0-lite-260215")
        api_key = (os.environ.get("AGENT_API_KEY")
                   or os.environ.get("DOUBAO_API_KEY", "651621e7-e495-4728-93ef-ed380e9ddcd1"))
        api_base = os.environ.get("AGENT_API_BASE", "https://ark.cn-beijing.volces.com/api/v3/")
        llm = ChatOpenAI(
            model=model_name,
            api_key=api_key,
            base_url=api_base,
            max_tokens=256,  # 改写输出很短，限制 token 节省成本和延迟
        )
        _global_rewriter = QueryRewriter(llm=llm, enabled=True)
        logger.info("[QueryRewriter] 初始化完成: model=%s", model_name)
    except Exception as e:
        logger.warning("[QueryRewriter] 初始化失败，使用 noop: %s", e)
        _global_rewriter = QueryRewriter(llm=None, enabled=False)

    return _global_rewriter


def set_query_rewriter(rewriter: QueryRewriter) -> None:
    """覆盖全局 QueryRewriter（测试用）"""
    global _global_rewriter
    _global_rewriter = rewriter
