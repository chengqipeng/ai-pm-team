"""ContextMiddleware — 上下文压缩，对应上下文压缩方案四层机制"""
from __future__ import annotations

import hashlib
from .base import PluginContext
from ..state import GraphState
from ..dtypes import MessageRole


class ContextMiddleware:
    name = "context"

    async def before_step(self, state: GraphState, context: PluginContext) -> GraphState:
        """Layer 2: 轮次裁剪（ToolMessage >= 5 时触发）"""
        tool_msgs = [m for m in state.messages if self._is_tool_result(m)]
        if len(tool_msgs) < 5:
            return state
        total_chars = sum(len(self._get_content(m)) for m in tool_msgs)
        if total_chars < 3000:
            return state
        state.messages = self._pass1_dedup(state.messages)
        return state

    async def after_step(self, state: GraphState, context: PluginContext) -> GraphState:
        return state

    async def before_tool_call(self, tool_name, input_data, state, context):
        return input_data

    async def after_tool_call(self, tool_name, result, state, context):
        """Layer 1: 源头隔离 — 大结果摘要"""
        content = getattr(result, "content", "")
        if len(content) > 500:
            # 尝试代码提取
            extracted = self._try_code_extract(content)
            if extracted:
                from ..state import FileInfo
                state.file_list.append(FileInfo(
                    file_path=f"/action_result/{tool_name}_{state.total_tool_calls}",
                    content=content,
                    summary=extracted,
                ))
                result.content = extracted
        return result

    # ── 内部方法 ──

    def _pass1_dedup(self, messages: list) -> list:
        """MD5 去重 — 从末尾向前遍历，相同内容只保留最新"""
        seen: dict[str, int] = {}
        result = list(messages)
        for i in range(len(result) - 1, -1, -1):
            if not self._is_tool_result(result[i]):
                continue
            content = self._get_content(result[i])
            if len(content) < 100:
                continue
            h = hashlib.md5(content.encode()).hexdigest()[:12]
            if h in seen:
                # 替换为引用
                if hasattr(result[i], "tool_result_blocks") and result[i].tool_result_blocks:
                    result[i].tool_result_blocks[0].content = "[重复结果 — 与最近一次相同查询结果一致]"
                elif hasattr(result[i], "content"):
                    result[i].content = "[重复结果 — 与最近一次相同查询结果一致]"
            else:
                seen[h] = i
        return result

    def _try_code_extract(self, content: str) -> str | None:
        """零 LLM 成本的代码格式化提取"""
        import json
        stripped = content.strip()
        if not (stripped.startswith("[") or stripped.startswith("{")):
            return None
        try:
            data = json.loads(stripped)
            if isinstance(data, dict) and "records" in data:
                records = data["records"]
                total = data.get("total", len(records))
                names = [r.get("name") or r.get("label") or "" for r in records[:5]]
                names_str = ", ".join(n for n in names if n)
                if total > 5:
                    names_str += f"...等{total}条"
                return f"查询返回{total}条记录: {names_str}"
            if isinstance(data, list):
                count = len(data)
                names = [item.get("name") or item.get("label") or "" for item in data[:5]]
                names_str = ", ".join(n for n in names if n)
                return f"返回{count}条: {names_str}"
        except (json.JSONDecodeError, TypeError, AttributeError):
            pass
        return None

    @staticmethod
    def _is_tool_result(msg) -> bool:
        if hasattr(msg, "tool_result_blocks") and msg.tool_result_blocks:
            return True
        if hasattr(msg, "role") and hasattr(msg, "content"):
            if isinstance(msg.content, list):
                return any(
                    isinstance(b, dict) and b.get("type") == "tool_result"
                    for b in msg.content
                )
        return False

    @staticmethod
    def _get_content(msg) -> str:
        if hasattr(msg, "tool_result_blocks") and msg.tool_result_blocks:
            return msg.tool_result_blocks[0].content or ""
        if hasattr(msg, "content"):
            if isinstance(msg.content, str):
                return msg.content
            if isinstance(msg.content, list):
                parts = []
                for b in msg.content:
                    if isinstance(b, dict):
                        parts.append(b.get("content", "") or b.get("text", ""))
                return " ".join(parts)
        return ""
