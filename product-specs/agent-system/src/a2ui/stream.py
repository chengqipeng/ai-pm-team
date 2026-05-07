"""A2UI Mode A — 独立 JSONL / SSE 流输出适配器

与 Mode B（嵌入 AG-UI ACTIVITY_SNAPSHOT）对比：

| 通道 | 报文形态 | 适用客户端 |
|:---|:---|:---|
| Mode B | AG-UI SSE，A2UI 嵌在 `ACTIVITY_SNAPSHOT.content.operations[]` | CopilotKit v2 等一体化客户端（默认） |
| Mode A | 纯 A2UI JSONL，每行一条 `surfaceUpdate / dataModelUpdate / beginRendering / deleteSurface` | 原生 A2UI 客户端（Flutter / Web 独立 SDK） |

本模块提供两种编码：
- `a2ui_jsonl_stream`      — 每条消息一行 JSON（`application/x-ndjson`）
- `a2ui_sse_stream`        — 标准 SSE（`text/event-stream`，event 名 = `a2ui`）
"""
from __future__ import annotations

import json
from typing import AsyncIterable, AsyncIterator, Iterable

from .models import A2UIMessage


async def a2ui_jsonl_stream(
    messages: AsyncIterable[A2UIMessage] | Iterable[A2UIMessage],
) -> AsyncIterator[str]:
    """输出 NDJSON（每条消息一行）。

    可直接传给 FastAPI `StreamingResponse`:

        return StreamingResponse(
            a2ui_jsonl_stream(messages),
            media_type="application/x-ndjson",
        )
    """
    if hasattr(messages, "__aiter__"):
        async for msg in messages:  # type: ignore[assignment,misc]
            yield msg.to_jsonl() + "\n"
    else:
        for msg in messages:  # type: ignore[assignment]
            yield msg.to_jsonl() + "\n"


async def a2ui_sse_stream(
    messages: AsyncIterable[A2UIMessage] | Iterable[A2UIMessage],
    *,
    event_name: str = "a2ui",
) -> AsyncIterator[str]:
    """输出 SSE，每条消息打成一个 `event: a2ui\\ndata: <json>\\n\\n`。"""
    if hasattr(messages, "__aiter__"):
        async for msg in messages:  # type: ignore[assignment,misc]
            yield _sse_frame(event_name, msg.to_dict())
    else:
        for msg in messages:  # type: ignore[assignment]
            yield _sse_frame(event_name, msg.to_dict())


def _sse_frame(event_name: str, payload: dict) -> str:
    return f"event: {event_name}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
