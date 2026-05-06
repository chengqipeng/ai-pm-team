"""
LLM 客户端 — DeepSeek OpenAI-Compatible API 完整实现

DeepSeek API 兼容 OpenAI Chat Completions 格式，使用 openai SDK 调用。
API 文档: https://platform.deepseek.com/api-docs

借鉴源码:
  - src/services/api/claude.ts: API 调用核心（结构参考）
  - src/services/api/errors.ts: 错误分类
  - src/services/api/withRetry.ts: 重试逻辑
  - src/services/api/logging.ts: 用量追踪
  - src/utils/tokens.ts: token 估算
"""
from __future__ import annotations

import os
import time
import json
import logging
from dataclasses import dataclass, field
from typing import Any

from src.core.dtypes import LLMClient

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


# ─── DeepSeek API 客户端 — 完整实现 ───

class DeepSeekClient(LLMClient):
    """
    DeepSeek Chat API 客户端 — 基于 OpenAI-Compatible 接口

    DeepSeek API 完全兼容 OpenAI Chat Completions 格式，使用 openai SDK 调用。
    API Base: https://api.deepseek.com
    文档: https://platform.deepseek.com/api-docs

    完整实现:
    - 异步 chat.completions.create 调用 (非流式，简化实现)
    - 自动从环境变量/参数获取 API key
    - 完整的 usage 追踪
    - 工具定义转换 (内部 schema → OpenAI function calling format)
    - 响应解析 (text/tool_calls blocks → 统一内部格式)
    - 错误处理与分类
    """

    DEFAULT_BASE_URL = "https://ark.cn-beijing.volces.com/api/v3/"

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        default_model: str = "doubao-1-5-pro-32k-250115",
        default_max_tokens: int = 8192,
    ):
        import openai

        resolved_key = api_key or os.environ.get("DOUBAO_API_KEY", "651621e7-e495-4728-93ef-ed380e9ddcd1")
        if not resolved_key:
            raise ValueError(
                "API key required. Set DOUBAO_API_KEY env var "
                "or pass api_key parameter."
            )

        self._async_client = openai.AsyncOpenAI(
            api_key=resolved_key,
            base_url=base_url or self.DEFAULT_BASE_URL,
        )
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
        调用 DeepSeek Chat Completions API

        参数:
          system_prompt: 系统提示词
          messages: 对话消息列表 (OpenAI 格式)
          tools: 工具定义列表 (name/description/input_schema)
          model: 模型名称 (deepseek-chat / deepseek-reasoner)
          max_tokens: 最大输出 token 数

        返回:
          标准化的响应 dict: {id, content, model, stop_reason, usage}
        """
        model = model or self._default_model
        max_tokens = max_tokens or self._default_max_tokens

        # 构建 OpenAI 格式的消息列表（system prompt 作为第一条 system 消息）
        api_messages = [{"role": "system", "content": system_prompt}]
        api_messages.extend(self._sanitize_messages(messages))

        # 构建请求参数
        kwargs: dict[str, Any] = {
            "model": model,
            "max_tokens": max_tokens,
            "messages": api_messages,
        }

        if tools:
            kwargs["tools"] = self._convert_tools(tools)
            kwargs["tool_choice"] = "auto"

        start_time = time.monotonic()

        try:
            response = await self._async_client.chat.completions.create(**kwargs)
        except Exception as e:
            duration_ms = (time.monotonic() - start_time) * 1000
            logger.error(f"DeepSeek API call failed after {duration_ms:.0f}ms: {e}")
            raise

        duration_ms = (time.monotonic() - start_time) * 1000

        # 提取 usage
        usage = {}
        if response.usage:
            usage = {
                "input_tokens": response.usage.prompt_tokens or 0,
                "output_tokens": response.usage.completion_tokens or 0,
                "cache_creation_input_tokens": getattr(
                    response.usage, "prompt_cache_miss_tokens", 0
                ),
                "cache_read_input_tokens": getattr(
                    response.usage, "prompt_cache_hit_tokens", 0
                ),
            }
            self._usage_tracker.accumulate(usage, duration_ms)

        logger.info(
            f"DeepSeek API #{self._usage_tracker.api_call_count}: "
            f"model={model}, {duration_ms:.0f}ms, "
            f"in={usage.get('input_tokens', 0)}, out={usage.get('output_tokens', 0)}"
        )

        return self._parse_response(response, usage)

    def _sanitize_messages(self, messages: list[dict]) -> list[dict]:
        """
        清理消息格式，确保符合 OpenAI Chat Completions API 要求:
        - assistant 消息中的 tool_use → tool_calls 字段
        - tool_result → role=tool + tool_call_id
        - 消息交替规则
        """
        sanitized = []
        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")

            # 跳过空消息
            if not content and role != "assistant":
                continue
            if isinstance(content, str) and not content.strip() and role != "assistant":
                continue

            # 处理 content 为 list 的情况
            if isinstance(content, list):
                text_parts = []
                tool_results = []
                tool_uses = []
                for block in content:
                    if isinstance(block, dict):
                        btype = block.get("type", "")
                        if btype == "text":
                            text_parts.append(block.get("text", ""))
                        elif btype == "tool_result":
                            tool_results.append(block)
                        elif btype == "tool_use":
                            tool_uses.append(block)

                # assistant 消息包含 tool_use → 转为 OpenAI tool_calls 格式
                if role == "assistant" and tool_uses:
                    tool_calls = []
                    for tu in tool_uses:
                        tool_calls.append({
                            "id": tu.get("id", ""),
                            "type": "function",
                            "function": {
                                "name": tu.get("name", ""),
                                "arguments": json.dumps(tu.get("input", {}), ensure_ascii=False),
                            },
                        })
                    assistant_msg = {
                        "role": "assistant",
                        "tool_calls": tool_calls,
                    }
                    # 如果有文本部分，加到 content
                    if text_parts:
                        assistant_msg["content"] = "\n".join(text_parts)
                    else:
                        assistant_msg["content"] = None
                    sanitized.append(assistant_msg)
                    continue

                # user 消息包含 tool_result → 转为 role=tool
                for tr in tool_results:
                    sanitized.append({
                        "role": "tool",
                        "tool_call_id": tr.get("tool_use_id", ""),
                        "content": tr.get("content", ""),
                    })

                if text_parts:
                    sanitized.append({"role": role, "content": "\n".join(text_parts)})
                continue

            sanitized.append({"role": role, "content": content})

        # 合并连续同角色消息（跳过 tool 和含 tool_calls 的 assistant）
        merged = []
        for msg in sanitized:
            if msg["role"] == "tool" or msg.get("tool_calls"):
                merged.append(dict(msg))
                continue
            if merged and merged[-1].get("role") == msg["role"] and not merged[-1].get("tool_calls"):
                prev = merged[-1].get("content", "")
                curr = msg.get("content", "")
                if isinstance(prev, str) and isinstance(curr, str):
                    merged[-1]["content"] = prev + "\n" + curr
                else:
                    merged.append(dict(msg))
            else:
                merged.append(dict(msg))

        return merged if merged else [{"role": "user", "content": "[empty]"}]

    def _convert_tools(self, tools: list[dict]) -> list[dict]:
        """
        转换工具定义为 OpenAI function calling 格式。
        内部格式: {name, description, input_schema}
        OpenAI 格式: {type: "function", function: {name, description, parameters}}
        """
        converted = []
        for tool in tools:
            schema = tool.get("input_schema", {})
            if "type" not in schema:
                schema["type"] = "object"
            if "properties" not in schema:
                schema["properties"] = {}

            converted.append({
                "type": "function",
                "function": {
                    "name": tool["name"],
                    "description": tool.get("description", f"Tool: {tool['name']}"),
                    "parameters": schema,
                },
            })
        return converted

    def _parse_response(self, response: Any, usage: dict) -> dict:
        """
        将 OpenAI SDK 响应转为统一的内部格式。
        
        OpenAI 格式:
          response.choices[0].message.content  → 文本
          response.choices[0].message.tool_calls  → 工具调用列表
          response.choices[0].finish_reason  → stop/tool_calls/length
        
        内部格式（与原 Anthropic 格式兼容，引擎层无需改动）:
          {content: [{type: "text", text: "..."}, {type: "tool_use", id, name, input}],
           stop_reason: "end_turn" / "tool_use" / "max_tokens"}
        """
        choice = response.choices[0] if response.choices else None
        if not choice:
            return {
                "id": response.id,
                "content": [{"type": "text", "text": ""}],
                "model": response.model,
                "stop_reason": "end_turn",
                "usage": usage,
            }

        message = choice.message
        content = []

        # 解析文本内容
        if message.content:
            # DeepSeek-Reasoner 可能返回 reasoning_content
            reasoning = getattr(message, "reasoning_content", None)
            if reasoning:
                content.append({"type": "thinking", "thinking": reasoning})
            content.append({"type": "text", "text": message.content})

        # 解析工具调用
        if message.tool_calls:
            for tc in message.tool_calls:
                # 解析 arguments（JSON 字符串 → dict）
                try:
                    args = json.loads(tc.function.arguments) if tc.function.arguments else {}
                except json.JSONDecodeError:
                    args = {"_raw": tc.function.arguments}

                content.append({
                    "type": "tool_use",
                    "id": tc.id,
                    "name": tc.function.name,
                    "input": args,
                })

        # 映射 finish_reason: OpenAI → 内部格式
        finish_reason_map = {
            "stop": "end_turn",
            "tool_calls": "tool_use",
            "length": "max_tokens",
            "content_filter": "end_turn",
        }
        stop_reason = finish_reason_map.get(choice.finish_reason, "end_turn")

        return {
            "id": response.id,
            "content": content if content else [{"type": "text", "text": ""}],
            "model": response.model,
            "stop_reason": stop_reason,
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
