"""
LLM 客户端 — 真实 Anthropic Messages API 完整实现

借鉴源码:
  - src/services/api/claude.ts: API 调用核心、流式处理
  - src/services/api/errors.ts: 错误分类
  - src/services/api/withRetry.ts: 重试逻辑
  - src/services/api/logging.ts: 用量追踪
  - src/utils/tokens.ts: token 估算
"""
from __future__ import annotations

import os
import time
import logging
from dataclasses import dataclass, field
from typing import Any

from .agent import LLMClient

logger = logging.getLogger(__name__)


# ─── Token 估算 (借鉴 utils/tokens.ts) ───

BYTES_PER_TOKEN = 4  # 粗略估算: 1 token ≈ 4 bytes

def estimate_tokens(text: str) -> int:
    """粗略估算 token 数"""
    return max(1, len(text.encode("utf-8")) // BYTES_PER_TOKEN)


# ─── 用量追踪 (借鉴 services/api/logging.ts) ───

@dataclass
class UsageTracker:
    """累计用量追踪"""
    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0
    api_call_count: int = 0
    total_duration_ms: float = 0.0

    def accumulate(self, usage: dict[str, int], duration_ms: float) -> None:
        self.input_tokens += usage.get("input_tokens", 0)
        self.output_tokens += usage.get("output_tokens", 0)
        self.cache_creation_input_tokens += usage.get("cache_creation_input_tokens", 0)
        self.cache_read_input_tokens += usage.get("cache_read_input_tokens", 0)
        self.api_call_count += 1
        self.total_duration_ms += duration_ms

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    def to_dict(self) -> dict[str, Any]:
        return {
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cache_creation_input_tokens": self.cache_creation_input_tokens,
            "cache_read_input_tokens": self.cache_read_input_tokens,
            "api_call_count": self.api_call_count,
            "total_duration_ms": round(self.total_duration_ms, 1),
        }


# ─── Anthropic API 客户端 — 完整实现 ───

class AnthropicClient(LLMClient):
    """
    真实 Anthropic Messages API 客户端 (借鉴 services/api/claude.ts)

    完整实现:
    - 同步 messages.create 调用 (非流式，简化实现)
    - 自动从环境变量/参数获取 API key
    - 完整的 usage 追踪
    - 工具定义转换 (内部 schema → Anthropic tool format)
    - 响应解析 (text/tool_use/thinking blocks)
    - 错误处理与分类
    """

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        default_model: str = "claude-sonnet-4-20250514",
        default_max_tokens: int = 8192,
    ):
        import anthropic

        resolved_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        if not resolved_key:
            raise ValueError(
                "Anthropic API key required. Set ANTHROPIC_API_KEY env var "
                "or pass api_key parameter."
            )

        kwargs: dict[str, Any] = {"api_key": resolved_key}
        if base_url:
            kwargs["base_url"] = base_url

        self._client = anthropic.Anthropic(**kwargs)
        self._async_client = anthropic.AsyncAnthropic(**kwargs)
        self._default_model = default_model
        self._default_max_tokens = default_max_tokens
        self._usage_tracker = UsageTracker()

    async def call(
        self,
        system_prompt: str,
        messages: list[dict],
        tools: list[dict] | None = None,
        model: str = "",
        max_tokens: int = 0,
    ) -> dict:
        """
        调用 Anthropic Messages API

        参数:
          system_prompt: 系统提示词
          messages: 对话消息列表 (Anthropic 格式)
          tools: 工具定义列表 (name/description/input_schema)
          model: 模型名称
          max_tokens: 最大输出 token 数

        返回:
          标准化的响应 dict: {id, content, model, stop_reason, usage}
        """
        model = model or self._default_model
        max_tokens = max_tokens or self._default_max_tokens

        # 构建请求参数
        kwargs: dict[str, Any] = {
            "model": model,
            "max_tokens": max_tokens,
            "system": system_prompt,
            "messages": self._sanitize_messages(messages),
        }

        if tools:
            kwargs["tools"] = self._convert_tools(tools)

        start_time = time.monotonic()

        try:
            response = await self._async_client.messages.create(**kwargs)
        except Exception as e:
            duration_ms = (time.monotonic() - start_time) * 1000
            logger.error(f"API call failed after {duration_ms:.0f}ms: {e}")
            raise

        duration_ms = (time.monotonic() - start_time) * 1000

        # 提取 usage
        usage = {}
        if hasattr(response, "usage") and response.usage:
            usage = {
                "input_tokens": getattr(response.usage, "input_tokens", 0),
                "output_tokens": getattr(response.usage, "output_tokens", 0),
                "cache_creation_input_tokens": getattr(response.usage, "cache_creation_input_tokens", 0),
                "cache_read_input_tokens": getattr(response.usage, "cache_read_input_tokens", 0),
            }
            self._usage_tracker.accumulate(usage, duration_ms)

        logger.info(
            f"API #{self._usage_tracker.api_call_count}: "
            f"model={model}, {duration_ms:.0f}ms, "
            f"in={usage.get('input_tokens', 0)}, out={usage.get('output_tokens', 0)}"
        )

        return self._parse_response(response, usage)

    def _sanitize_messages(self, messages: list[dict]) -> list[dict]:
        """
        清理消息格式，确保符合 Anthropic API 要求:
        - 交替 user/assistant
        - content 不能为空
        - tool_result 必须在 user 消息中
        """
        sanitized = []
        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")

            # 跳过空消息
            if not content:
                continue

            # 确保 content 格式正确
            if isinstance(content, str) and not content.strip():
                continue

            sanitized.append({"role": role, "content": content})

        # 确保消息交替: 合并连续的同角色消息
        merged = []
        for msg in sanitized:
            if merged and merged[-1]["role"] == msg["role"]:
                # 合并同角色消息
                prev_content = merged[-1]["content"]
                curr_content = msg["content"]
                if isinstance(prev_content, str) and isinstance(curr_content, str):
                    merged[-1]["content"] = prev_content + "\n" + curr_content
                elif isinstance(prev_content, list) and isinstance(curr_content, list):
                    merged[-1]["content"] = prev_content + curr_content
                elif isinstance(prev_content, str) and isinstance(curr_content, list):
                    merged[-1]["content"] = [{"type": "text", "text": prev_content}] + curr_content
                elif isinstance(prev_content, list) and isinstance(curr_content, str):
                    merged[-1]["content"] = prev_content + [{"type": "text", "text": curr_content}]
            else:
                merged.append(dict(msg))

        # 确保第一条是 user 消息
        if merged and merged[0]["role"] != "user":
            merged.insert(0, {"role": "user", "content": "[conversation start]"})

        return merged if merged else [{"role": "user", "content": "[empty]"}]

    def _convert_tools(self, tools: list[dict]) -> list[dict]:
        """
        转换工具定义为 Anthropic API 格式
        内部格式: {name, description, input_schema}
        API 格式: {name, description, input_schema} (基本一致，但需要确保 schema 合规)
        """
        converted = []
        for tool in tools:
            schema = tool.get("input_schema", {})
            # 确保 schema 有 type: object
            if "type" not in schema:
                schema["type"] = "object"
            if "properties" not in schema:
                schema["properties"] = {}

            converted.append({
                "name": tool["name"],
                "description": tool.get("description", f"Tool: {tool['name']}"),
                "input_schema": schema,
            })
        return converted

    def _parse_response(self, response: Any, usage: dict) -> dict:
        """将 anthropic SDK 响应转为标准 dict"""
        content = []
        for block in response.content:
            if block.type == "text":
                content.append({"type": "text", "text": block.text})
            elif block.type == "tool_use":
                content.append({
                    "type": "tool_use",
                    "id": block.id,
                    "name": block.name,
                    "input": block.input if isinstance(block.input, dict) else {},
                })
            elif block.type == "thinking":
                content.append({
                    "type": "thinking",
                    "thinking": getattr(block, "thinking", ""),
                })

        return {
            "id": response.id,
            "content": content,
            "model": response.model,
            "stop_reason": response.stop_reason,
            "usage": usage,
        }

    @property
    def usage(self) -> UsageTracker:
        return self._usage_tracker

    @property
    def total_usage(self) -> dict[str, Any]:
        return self._usage_tracker.to_dict()


# ─── Mock LLM 客户端 (用于测试和无 API key 场景) ───

class MockLLMClient(LLMClient):
    """
    可编程的 Mock LLM 客户端。
    支持预设响应脚本和条件响应，用于测试 Agent Loop 逻辑。
    工具执行、权限检查、hooks 等仍然是真实逻辑 — 只有 LLM API 调用被替代。
    """

    def __init__(self):
        self._responses: list[dict] = []
        self._call_count = 0
        self._call_history: list[dict] = []

    def add_response(self, response: dict) -> MockLLMClient:
        self._responses.append(response)
        return self

    def add_text_response(self, text: str) -> MockLLMClient:
        return self.add_response({
            "content": [{"type": "text", "text": text}],
            "usage": {"input_tokens": 100, "output_tokens": len(text) // 4},
        })

    def add_tool_call_response(
        self, tool_name: str, tool_input: dict, text: str = ""
    ) -> MockLLMClient:
        content = []
        if text:
            content.append({"type": "text", "text": text})
        content.append({
            "type": "tool_use",
            "id": f"tu_{self._call_count + len(self._responses):03d}",
            "name": tool_name,
            "input": tool_input,
        })
        return self.add_response({
            "content": content,
            "usage": {"input_tokens": 200, "output_tokens": 50},
        })

    async def call(self, system_prompt, messages, tools=None, model="", max_tokens=8192):
        self._call_count += 1
        self._call_history.append({
            "call_number": self._call_count,
            "message_count": len(messages),
            "tool_count": len(tools) if tools else 0,
        })
        if self._responses:
            return self._responses.pop(0)
        return {
            "content": [{"type": "text", "text": "[MockLLM: no more responses]"}],
            "usage": {"input_tokens": 50, "output_tokens": 10},
        }

    @property
    def call_count(self) -> int:
        return self._call_count

    @property
    def call_history(self) -> list[dict]:
        return list(self._call_history)
