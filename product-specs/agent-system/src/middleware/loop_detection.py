"""循环检测中间件 — 直接继承 LangChain AgentMiddleware"""

import hashlib
import json
import logging
import threading
from collections import OrderedDict, defaultdict
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage
from langchain.agents.middleware.types import AgentMiddleware, AgentState
from langgraph.config import get_config
from langgraph.runtime import Runtime

logger = logging.getLogger(__name__)


class LoopDetectionMiddleware(AgentMiddleware):
    """检测重复 tool_calls，warn → hard_limit 剥离"""

    def __init__(self, warn_threshold: int = 3, hard_limit: int = 5, window_size: int = 20):
        super().__init__()
        self.warn_threshold = warn_threshold
        self.hard_limit = hard_limit
        self.window_size = window_size
        self._lock = threading.Lock()
        self._history: OrderedDict[str, list[str]] = OrderedDict()
        self._warned: dict[str, set[str]] = defaultdict(set)

    def after_model(self, state: AgentState, runtime: Runtime) -> dict[str, Any] | None:
        messages = state.get("messages", [])
        if not messages:
            return None

        last_msg = messages[-1]
        if not isinstance(last_msg, AIMessage):
            return None

        tool_calls = getattr(last_msg, "tool_calls", None)
        if not tool_calls:
            return None

        try:
            configurable = get_config().get("configurable", {})
            thread_id = configurable.get("thread_id", "default")
        except Exception:
            thread_id = "default"

        normalized = sorted(
            [{"name": tc.get("name", ""), "args": tc.get("args", {})} for tc in tool_calls],
            key=lambda tc: (tc["name"], json.dumps(tc["args"], sort_keys=True, default=str)),
        )
        call_hash = hashlib.md5(json.dumps(normalized, sort_keys=True, default=str).encode()).hexdigest()[:12]

        with self._lock:
            if thread_id not in self._history:
                self._history[thread_id] = []
                while len(self._history) > 100:
                    evicted, _ = self._history.popitem(last=False)
                    self._warned.pop(evicted, None)
            else:
                self._history.move_to_end(thread_id)

            history = self._history[thread_id]
            history.append(call_hash)
            if len(history) > self.window_size:
                history[:] = history[-self.window_size:]

            count = history.count(call_hash)

            if count >= self.hard_limit:
                logger.error("Loop hard limit: count=%d", count)
                stripped = last_msg.model_copy(update={
                    "tool_calls": [],
                    "content": (last_msg.content or "") + "\n\n[强制停止] 重复工具调用超过安全限制。请直接给出最终答案。",
                })
                return {"messages": [stripped]}

            if count >= self.warn_threshold and call_hash not in self._warned[thread_id]:
                self._warned[thread_id].add(call_hash)
                logger.warning("Repetitive tool calls: count=%d", count)
                return {"messages": [HumanMessage(content="[循环检测] 你正在重复相同的工具调用。请停止调用工具，直接给出最终答案。")]}

        return None
