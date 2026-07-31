"""推荐引擎入口 — 信号 → 规则匹配 → 卡片去重排序 → 输出"""
from __future__ import annotations

import logging
import re
from typing import Any

from .cards import RecommendationCard, card_store
from .defaults import get_default_cards
from .rules import BUILTIN_RULES
from .signals import UserSignal, signal_buffer

logger = logging.getLogger(__name__)


def collect_signals_from_run(
    thread_id: str,
    user_message: str,
    tool_calls: list[str],
    tool_results: list[dict[str, Any]] | None = None,
    origin_intent: str = "",
) -> None:
    """从一次 Agent run 的执行结果中提取信号并写入缓冲"""
    if not thread_id:
        return

    # 1. 对话意图信号
    if user_message:
        entity_type, action = _infer_intent(user_message, origin_intent)
        signal_buffer.append(thread_id, UserSignal(
            signal_type="chat_intent",
            entity_type=entity_type,
            action=action,
            context={"message": user_message[:200], "origin_intent": origin_intent},
        ))

    # 2. 工具调用信号
    for tool_name in tool_calls:
        entity_type = _tool_to_entity(tool_name)
        action = _tool_to_action(tool_name)
        signal_buffer.append(thread_id, UserSignal(
            signal_type="tool_call",
            entity_type=entity_type,
            action=action,
            context={"tool_name": tool_name},
        ))

    # 3. 查询失败信号（从 tool_results 中检测）
    for result in (tool_results or []):
        content = str(result.get("content", ""))
        if any(kw in content for kw in ("未找到", "不存在", "not found", "no results")):
            query_text = result.get("query_text") or user_message[:50]
            signal_buffer.append(thread_id, UserSignal(
                signal_type="tool_call",
                entity_type=result.get("entity_type", ""),
                action="failed_query",
                context={"query_text": query_text, "result_preview": content[:200]},
            ))


def collect_ui_action_signal(
    thread_id: str,
    action_name: str,
    context: dict[str, Any],
) -> None:
    """从前端 UI 操作中提取信号"""
    entity_type = str(context.get("entityApiKey", "account"))
    entity_key = str(context.get("recordApiKey", ""))
    action = _ui_action_to_action(action_name)

    signal_buffer.append(thread_id, UserSignal(
        signal_type="ui_action",
        entity_type=entity_type,
        entity_key=entity_key or None,
        action=action,
        context={
            "action_name": action_name,
            "name": context.get("name") or context.get("accountName", ""),
            "owner": context.get("owner") or context.get("ownerName", ""),
            "accountId": context.get("accountId", ""),
        },
    ))


async def evaluate_recommendations(
    thread_id: str,
    user_message: str = "",
    tool_calls: list[str] | None = None,
    origin_intent: str = "",
) -> list[dict[str, Any]]:
    """评估并生成推荐卡片，返回可序列化的卡片列表"""
    try:
        # 采集本次 run 的信号
        collect_signals_from_run(
            thread_id, user_message, tool_calls or [], origin_intent=origin_intent)

        # 获取近期信号
        signals = signal_buffer.get_recent(thread_id, window_minutes=60)

        if not signals:
            # 无信号时返回默认卡片
            defaults = get_default_cards()
            card_store.merge(thread_id, defaults)
            return card_store.get_serialized(thread_id)

        # 运行所有规则
        context: dict[str, Any] = {"origin_intent": origin_intent}
        candidates: list[RecommendationCard] = []
        for rule in BUILTIN_RULES:
            try:
                result = rule.evaluate(signals, context)
                candidates.extend(result)
            except Exception:
                logger.exception("Rule %s evaluation failed", type(rule).__name__)

        # 无候选时补充默认
        if not candidates:
            candidates = get_default_cards()

        # 合并去重
        card_store.merge(thread_id, candidates)
        return card_store.get_serialized(thread_id)

    except Exception:
        logger.exception("evaluate_recommendations failed for thread=%s", thread_id)
        # 降级返回默认卡片
        return [c.to_dict() for c in get_default_cards()]


# ═══════════════════════════════════════════════════════════
# 内部辅助
# ═══════════════════════════════════════════════════════════

def _infer_intent(message: str, origin_intent: str = "") -> tuple[str, str]:
    """从消息文本推断 entity_type 和 action"""
    text = message.lower()
    entity = "account"
    if re.search(r"商机|opportunit|pipeline", text):
        entity = "opportunity"
    elif re.search(r"联系人|contact", text):
        entity = "contact"
    elif re.search(r"活动|activity|日程", text):
        entity = "activity"
    elif re.search(r"线索|lead", text):
        entity = "lead"

    action = "query"
    if origin_intent == "customer_insight" or re.search(r"洞察|分析|insight", text):
        action = "insight"
    elif re.search(r"新建|创建|create|add", text):
        action = "create"
    elif re.search(r"编辑|修改|update|edit", text):
        action = "edit"
    elif re.search(r"详情|详细|查看|view", text):
        action = "view"

    return entity, action


def _tool_to_entity(tool_name: str) -> str:
    name = tool_name.lower()
    if "opportunity" in name or "pipeline" in name:
        return "opportunity"
    if "contact" in name:
        return "contact"
    if "activity" in name:
        return "activity"
    if "lead" in name:
        return "lead"
    return "account"


def _tool_to_action(tool_name: str) -> str:
    name = tool_name.lower()
    if "query" in name or "search" in name or "list" in name:
        return "query"
    if "create" in name or "add" in name:
        return "create"
    if "update" in name or "edit" in name or "modify" in name:
        return "edit"
    if "insight" in name or "analyze" in name:
        return "insight"
    return "query"


def _ui_action_to_action(action_name: str) -> str:
    name = action_name.lower()
    if "view" in name or "detail" in name:
        return "view"
    if "create" in name or "add" in name or "new" in name:
        return "create"
    if "edit" in name or "update" in name:
        return "edit"
    if "refresh" in name or "query" in name:
        return "query"
    if "insight" in name:
        return "insight"
    return "view"
