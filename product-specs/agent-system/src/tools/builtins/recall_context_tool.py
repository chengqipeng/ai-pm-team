"""recall_context 工具 — 从压缩存档中恢复被压缩的历史对话原文

当上下文被压缩后，摘要中标注了 [📦 turn:N] 的内容只保留了摘要级别的信息。
LLM 在需要具体细节时（如付款条件、完整数据表、原始工具输出），通过此工具
按 turn_id 或关键词检索被压缩的原始内容。

数据存储:
  - PG 持久化: ai_context_archive 表（唯一数据源，禁止降级）

数据时效性:
  - 每条恢复内容标注数据采集时间
  - 超过 4 小时的状态性数据提示 LLM 考虑使用业务工具重查
  - 结论性/结构性信息（报价条款、合同条件）即使过期仍然有效

恢复策略（禁止降级）:
  - 仅从 PG original_messages_json 恢复完整原文
  - 若原文不可用，直接告知不可用，不提供摘要级降级数据
"""
from __future__ import annotations

import json
import logging
from typing import Any

from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class RecallContextInput(BaseModel):
    query: str = Field(
        description=(
            "要检索的内容。可以是:\n"
            "- 精确的 turn_id: 如 'turn:3' 或 'turn_3'\n"
            "- 关键词描述: 如 'PT Sentosa 付款条件'\n"
            "- 实体名: 如 '华为竞品定价'"
        )
    )


class RecallContextTool(BaseTool):
    """从压缩存档中检索被压缩的历史对话细节

    适用场景:
      - 用户追问摘要中标注 [📦 turn:N] 的具体内容
      - 用户问"之前...的具体细节是什么"
      - 摘要中有关键数字但缺少完整上下文
      - 需要引用之前的工具返回结果原文
      - 恢复结论性信息（报价条款、分析结论、合同条件）

    不适用:
      - 查询当前系统最新数据（应使用 query_data 等业务工具）
      - 当前轮次中的内容（还未被压缩，直接在上下文中）
      - 需要实时状态的数据（商机阶段变化、库存、实时价格）
    """

    name: str = "recall_context"
    description: str = (
        "检索被压缩的历史对话细节。"
        "当上下文摘要中标记了 [📦 turn:N] 的内容不够详细时，"
        "输入 turn_id（如 'turn:3'）或关键词（如 'PT Sentosa 付款条件'）来获取完整原文。"
        "注意: 只能检索本会话中已被压缩的历史内容，不能查询系统最新数据。"
        "返回的数据会标注采集时间——如果数据涉及状态变化且已过时，请改用业务工具重查。"
    )
    args_schema: type[BaseModel] = RecallContextInput

    # 由外部注入（AgentFactory 构建时传入）
    archive: Any = None       # ContextArchive 实例

    model_config = {"arbitrary_types_allowed": True}

    def _run(self, query: str) -> str:
        """同步版本"""
        import asyncio
        try:
            loop = asyncio.get_running_loop()
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                return pool.submit(asyncio.run, self._arun(query)).result()
        except RuntimeError:
            return asyncio.run(self._arun(query))

    async def _arun(self, query: str) -> str:
        """异步版本 — 主执行逻辑"""
        # 检查存档是否可用
        if not self.archive or not self.archive.has_entries():
            return (
                "当前会话没有被压缩的历史内容。\n"
                "如果需要查询系统数据，请使用 query_data 等业务工具。"
            )

        # Step 1: 在存档索引中搜索
        matched_entries = self.archive.search(query, top_k=3)

        if not matched_entries:
            return (
                "历史存档中未找到与查询相关的内容。\n"
                "可能的原因: 该信息不在被压缩的历史中，或关键词不匹配。\n"
                "建议: 使用业务工具（如 query_data、web_search）重新查询最新数据。"
            )

        # Step 2: 按优先级恢复每条匹配的原文
        results = []
        for entry in matched_entries:
            recovered = self._recover_content(entry)
            age_desc = self.archive.get_data_age_description(entry)
            is_stale = self.archive.is_data_likely_stale(entry)

            header = (
                f"[📦 轮次 {entry.turn_id} | "
                f"问题: {entry.user_query[:60]}{'...' if len(entry.user_query) > 60 else ''} | "
                f"⏱️ {age_desc}]"
            )

            # 时效性警告
            staleness_warning = ""
            if is_stale:
                staleness_warning = (
                    "\n⚠️ 时效性提醒: 此数据采集时间较早，"
                    "如果涉及状态变化（商机阶段/价格/库存等），"
                    "建议使用 query_data 等工具确认最新状态。"
                )

            results.append(f"{header}{staleness_warning}\n{recovered}")

        output = "从历史存档中恢复以下内容:\n\n" + "\n\n---\n\n".join(results)

        # 限制输出长度（避免恢复的原文太长挤占上下文）
        if len(output) > 4000:
            output = output[:4000] + "\n\n[输出已截断，如需更多细节请缩小查询范围]"

        return output

    def _recover_content(self, entry) -> str:
        """从存档恢复内容（仅使用 PG 原文，禁止降级）"""
        if entry.original_messages_json:
            original = self._format_from_json(entry.original_messages_json)
            if original:
                return original

        return "[该轮次的完整原文不可用，建议使用业务工具重新查询]"

    def _format_from_json(self, messages_json: str) -> str | None:
        """从序列化的 JSON 消息恢复为可读文本"""
        try:
            messages = json.loads(messages_json)
            if not messages:
                return None

            parts = []
            for msg in messages:
                role = msg.get("role", "unknown")
                content = msg.get("content", "")
                if not content or not content.strip():
                    # 即使内容为空，如果有 tool_calls 也展示
                    tool_calls = msg.get("tool_calls")
                    if tool_calls:
                        tc_names = [tc.get("name", "?") for tc in tool_calls]
                        parts.append(f"[调用工具: {', '.join(tc_names)}]")
                    continue

                if role == "human":
                    parts.append(f"[用户] {content[:800]}")
                elif role == "tool":
                    tool_name = msg.get("name", "") or "tool"
                    # 工具结果可能很长，限制在 1200 字符
                    parts.append(f"[工具结果:{tool_name}] {content[:1200]}")
                elif role == "ai":
                    tool_calls = msg.get("tool_calls")
                    if tool_calls:
                        tc_names = [tc.get("name", "?") for tc in tool_calls]
                        parts.append(f"[调用工具: {', '.join(tc_names)}]")
                    if content.strip():
                        parts.append(f"[助手] {content[:1000]}")

            return "\n".join(parts) if parts else None

        except (json.JSONDecodeError, TypeError) as e:
            logger.debug("[RecallContext] JSON 解析失败: %s", e)
            return None
