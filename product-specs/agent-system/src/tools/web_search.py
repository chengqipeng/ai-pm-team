"""百度 AI 搜索工具 — 基于千帆 AI Search API

API: https://qianfan.baidubce.com/v2/ai_search
认证: X-Appbuilder-Authorization: Bearer {API_KEY}
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any

import requests

from .base import Tool, ToolResult

logger = logging.getLogger(__name__)

BAIDU_SEARCH_API = "https://qianfan.baidubce.com/v2/ai_search"
DEFAULT_API_KEY = "bce-v3/ALTAK-qg2VbkRV4G5jLGNGZMxkO/5ccfbb769296579d3c02a5fad278d0df4f0b154f"


class WebSearchTool(Tool):
    """百度 AI 搜索 — 联网搜索实时信息"""

    def __init__(self, api_key: str = ""):
        self._api_key = api_key or os.environ.get("BAIDU_SEARCH_API_KEY", DEFAULT_API_KEY)

    @classmethod
    def create(cls, tenant_id: int = 0, db_row=None) -> "WebSearchTool":
        """自包含初始化 — API key 从环境变量获取"""
        return cls()

    @property
    def name(self) -> str:
        return "web_search"

    def input_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "搜索关键词"},
            },
            "required": ["query"],
        }

    def description(self) -> str:
        return (
            "联网搜索实时信息 — 使用百度 AI 搜索获取互联网上的最新内容。\n"
            "何时使用：当用户询问的信息不在 CRM 系统中，需要从互联网获取时使用。\n"
            "例如：行业动态、竞品信息、公司新闻、技术趋势、政策法规等。\n"
            "参数：\n"
            "  - query（必填）：搜索关键词，尽量具体\n"
            "典型用法：\n"
            "  · '销售易最近有什么新闻' → web_search(query='销售易 最新新闻 2026')\n"
            "  · '华为今年的营收情况' → web_search(query='华为 2026 年营收')\n"
            "  · 'CRM行业趋势' → web_search(query='CRM行业趋势 2026')\n"
            "注意：搜索结果来自互联网，可能不完全准确，建议交叉验证"
        )

    async def call(self, input_data: dict[str, Any], context: Any = None, on_progress=None) -> ToolResult:
        query = input_data.get("query", "")
        if not query:
            return ToolResult(content="搜索关键词不能为空", is_error=True)

        try:
            headers = {
                "Content-Type": "application/json",
                "X-Appbuilder-Authorization": f"Bearer {self._api_key}",
            }
            body = {
                "messages": [{"role": "user", "content": query}],
                "stream": False,
            }

            resp = requests.post(BAIDU_SEARCH_API, headers=headers, json=body, timeout=15)
            data = resp.json()

            if "code" in data and data["code"] != 0:
                return ToolResult(
                    content=f"搜索失败: {data.get('message', '未知错误')}",
                    is_error=True,
                )

            # 解析搜索结果
            references = data.get("references", [])
            answer = data.get("answer", "")

            # 格式化输出
            parts = []
            if answer:
                parts.append(f"**AI 摘要：**\n{answer}\n")

            if references:
                parts.append(f"**搜索结果（{len(references)} 条）：**")
                for ref in references[:5]:
                    title = ref.get("title", "")
                    url = ref.get("url", "")
                    content = ref.get("content", "")[:200]
                    date = ref.get("date", "")
                    parts.append(f"\n{ref.get('id', '')}. **{title}**")
                    if date:
                        parts.append(f"   日期: {date}")
                    if content:
                        parts.append(f"   摘要: {content}")
                    if url:
                        parts.append(f"   链接: {url}")

            if not parts:
                return ToolResult(content="未找到相关搜索结果")

            return ToolResult(content="\n".join(parts))

        except requests.Timeout:
            return ToolResult(content="搜索超时，请稍后重试", is_error=True)
        except Exception as e:
            logger.error("Web search failed: %s", e)
            return ToolResult(content=f"搜索出错: {str(e)}", is_error=True)
