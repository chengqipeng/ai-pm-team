"""统一记忆提取器 v3 — 单次 LLM 调用四维提取

替代原 v2 四路并行方案，核心变化：
- 4 次 LLM 调用 → 1 次
- 两阶段推理（_reasoning + result）保证分类质量
- 输出 schema 与下游完全兼容（ExtractionItem 不变）
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from .prompts import (
    UNIFIED_EXTRACT_PROMPT,
    # v2 遗留导入（供测试/回退使用）
    PROFILE_EXTRACT_PROMPT,
    PREFERENCES_EXTRACT_PROMPT,
    AGENT_RULES_EXTRACT_PROMPT,
    ENTITIES_EXTRACT_PROMPT,
)

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════
# 协议定义
# ═══════════════════════════════════════════════════════════

@runtime_checkable
class LLMInvoker(Protocol):
    """LLM 调用协议"""
    async def ainvoke(self, input: Any) -> Any: ...


@runtime_checkable
class StateProvider(Protocol):
    """已有状态查询协议"""
    async def get_profile(self, tenant_id: str, user_id: str) -> str: ...
    async def get_agent_rules(self, tenant_id: str, user_id: str) -> str: ...
    async def get_entity_index(self, tenant_id: str, user_id: str) -> str: ...


# ═══════════════════════════════════════════════════════════
# 提取结果数据模型
# ═══════════════════════════════════════════════════════════

@dataclass
class ExtractionItem:
    """单条提取结果"""
    dimension: str          # profile / preferences / agent_rules / entities
    slug: str = ""          # preferences 的子分类 slug
    abstract: str = ""
    overview: str = ""
    content: str = ""
    merge_key: str = ""
    parent_entity: str = ""
    source_type: str = "insight"


@dataclass
class ExtractionResult:
    """提取的汇总结果"""
    items: list[ExtractionItem] = field(default_factory=list)
    tenant_id: str = ""
    user_id: str = ""
    thread_id: str = ""
    duration_ms: float = 0.0
    errors: list[str] = field(default_factory=list)
    reasoning: list[dict] = field(default_factory=list)  # v3: 归属推理链


# ═══════════════════════════════════════════════════════════
# 数值过滤规则
# ═══════════════════════════════════════════════════════════

_NUMERIC_PATTERNS = [
    re.compile(r'\d{3,}[\.\d]*\s*[万元美]'),       # 金额：45万、280元
    re.compile(r'\d+%'),                            # 概率：60%
    re.compile(r'1[3-9]\d{9}'),                     # 手机号
    re.compile(r'\d{3,4}-\d{7,8}'),                 # 座机
    re.compile(r'[\w\.-]+@[\w\.-]+\.\w+'),          # 邮箱
]


def _contains_only_precise_values(text: str) -> bool:
    """检测文本是否仅包含精确字段值（无增量认知）"""
    if not text:
        return False
    cleaned = text
    for pattern in _NUMERIC_PATTERNS:
        cleaned = pattern.sub("", cleaned)
    cleaned = re.sub(r'[\s\W]+', '', cleaned)
    return len(cleaned) < 10


# ═══════════════════════════════════════════════════════════
# 核心提取器
# ═══════════════════════════════════════════════════════════

class MemoryExtractor:
    """统一记忆提取器 v3 — 单次 LLM 调用

    Usage:
        extractor = MemoryExtractor(llm=llm, state_provider=state_provider)
        result = await extractor.extract_all(
            messages=messages,
            tenant_id="tenant_001",
            user_id="user_001",
            thread_id="thread_001",
            output_language="auto",
        )
    """

    def __init__(
        self,
        llm: LLMInvoker | None = None,
        state_provider: StateProvider | None = None,
    ):
        self._llm = llm
        self._state = state_provider

    async def extract_all(
        self,
        messages: list,
        tenant_id: str,
        user_id: str,
        thread_id: str = "",
        output_language: str = "auto",
    ) -> ExtractionResult:
        """统一提取：单次 LLM 调用，四维度同时输出"""
        start = time.monotonic()
        result = ExtractionResult(
            tenant_id=tenant_id, user_id=user_id, thread_id=thread_id,
        )

        if not messages or not self._llm:
            return result

        # 预处理：提取用户原始消息
        user_messages = self._filter_user_messages(messages)
        user_text = self._format_messages(user_messages) if user_messages else ""

        if not user_text:
            return result

        # 并行加载已有状态
        existing_profile, existing_rules, existing_entities = await self._load_existing_state(
            tenant_id, user_id
        )

        # 构建统一 prompt
        prompt = UNIFIED_EXTRACT_PROMPT.format(
            existing_profile=existing_profile or "（无）",
            existing_rules=existing_rules or "（无）",
            existing_entities=existing_entities or "（无）",
            user_messages=user_text,
            output_language=output_language,
        )

        # 单次 LLM 调用
        data = await self._invoke_llm(prompt)
        if not data:
            result.errors.append("LLM 调用返回空结果")
            result.duration_ms = (time.monotonic() - start) * 1000
            return result

        # 解析 _reasoning（调试用）
        reasoning = data.get("_reasoning", [])
        result.reasoning = reasoning
        logger.debug("Extraction reasoning (%d sentences): %s", len(reasoning), reasoning)

        # 解析 result（兼容有/无 result 包裹层）
        result_data = self._extract_result_data(data)

        # 逐维度解析
        try:
            result.items.extend(self._parse_profile(result_data))
        except Exception as e:
            result.errors.append(f"profile 解析失败: {e}")

        try:
            result.items.extend(self._parse_preferences(result_data))
        except Exception as e:
            result.errors.append(f"preferences 解析失败: {e}")

        try:
            result.items.extend(self._parse_agent_rules(result_data))
        except Exception as e:
            result.errors.append(f"agent_rules 解析失败: {e}")

        try:
            result.items.extend(self._parse_entities(result_data))
        except Exception as e:
            result.errors.append(f"entities 解析失败: {e}")

        # 后处理过滤
        result.items = self._post_filter(result.items)

        result.duration_ms = (time.monotonic() - start) * 1000
        logger.info(
            "MemoryExtractor v3: extracted %d items in %.0fms (tenant=%s, user=%s, errors=%d)",
            len(result.items), result.duration_ms, tenant_id, user_id, len(result.errors),
        )
        return result

    # ─────────────────────────────────────────────────────
    # 结果解析：四维度
    # ─────────────────────────────────────────────────────

    @staticmethod
    def _extract_result_data(data: dict) -> dict:
        """兼容解析：支持 result 包裹层和直接输出两种格式"""
        if "result" in data and isinstance(data["result"], dict):
            return data["result"]
        # 直接是四维度结构（模型省略了 result 层）
        if any(k in data for k in ("profile", "preferences", "agent_rules", "entities")):
            return data
        return {}

    @staticmethod
    def _parse_profile(result_data: dict) -> list[ExtractionItem]:
        """解析 profile 维度"""
        profile = result_data.get("profile", {})
        if not isinstance(profile, dict):
            return []

        content = profile.get("content", "")
        if not content or not content.strip():
            return []

        return [ExtractionItem(
            dimension="profile",
            content=content.strip(),
            abstract=f"用户画像: {content[:80]}",
            merge_key="profile",
            source_type="insight",
        )]

    @staticmethod
    def _parse_preferences(result_data: dict) -> list[ExtractionItem]:
        """解析 preferences 维度"""
        preferences = result_data.get("preferences", [])
        if not isinstance(preferences, list) or not preferences:
            return []

        items = []
        seen_slugs: dict[str, ExtractionItem] = {}

        for pref in preferences:
            if not isinstance(pref, dict):
                continue
            slug = pref.get("slug", "")
            abstract = pref.get("abstract", "")
            if not abstract:
                continue

            # 硬截断
            if len(abstract) > 200:
                logger.warning("[extraction] preferences abstract 超长（%d 字符），截断", len(abstract))
                abstract = abstract[:200]

            item = ExtractionItem(
                dimension="preferences",
                slug=slug,
                abstract=abstract,
                overview=pref.get("overview", ""),
                content=pref.get("content", abstract),
                merge_key=f"preferences/{slug}" if slug else "preferences",
                parent_entity="preferences",
                source_type="insight",
            )
            # slug 去重：同 slug 只保留最后一条
            seen_slugs[slug] = item

        return list(seen_slugs.values())

    @staticmethod
    def _parse_agent_rules(result_data: dict) -> list[ExtractionItem]:
        """解析 agent_rules 维度"""
        rules = result_data.get("agent_rules", {})
        if not isinstance(rules, dict):
            return []

        content = rules.get("content", "")
        if not content or not content.strip():
            return []

        return [ExtractionItem(
            dimension="agent_rules",
            content=content.strip(),
            abstract=f"Agent行为准则: {content[:80]}",
            merge_key="agent_rules",
            source_type="insight",
        )]

    @staticmethod
    def _parse_entities(result_data: dict) -> list[ExtractionItem]:
        """解析 entities 维度"""
        entities = result_data.get("entities", [])
        if not isinstance(entities, list) or not entities:
            return []

        items = []
        for ent in entities:
            if not isinstance(ent, dict):
                continue
            abstract = ent.get("abstract", "")
            if not abstract or len(abstract) < 5:
                continue

            if len(abstract) > 200:
                logger.warning("[extraction] entities abstract 超长（%d 字符），截断", len(abstract))
                abstract = abstract[:200]

            content = ent.get("content", abstract)
            merge_key = ent.get("merge_key", "")
            parent_entity = ent.get("parent_entity", "")

            # source_type 推断
            source_type = "insight"
            insight_keywords = (
                "建议", "倾向", "敏感", "注意", "喜欢", "不喜欢",
                "习惯", "风格", "策略", "技巧", "关系", "分歧",
                "审批流程", "决策链", "内部", "偏好",
            )
            if not any(kw in content for kw in insight_keywords):
                source_type = "system_data"

            items.append(ExtractionItem(
                dimension="entities",
                abstract=abstract,
                overview=ent.get("overview", ""),
                content=content,
                merge_key=merge_key,
                parent_entity=parent_entity,
                source_type=source_type,
            ))

        return items

    # ─────────────────────────────────────────────────────
    # 工具方法
    # ─────────────────────────────────────────────────────

    async def _load_existing_state(
        self, tenant_id: str, user_id: str,
    ) -> tuple[str, str, str]:
        """并行加载已有状态"""
        if not self._state:
            return "", "", ""

        try:
            profile, rules, entities = await asyncio.gather(
                self._state.get_profile(tenant_id, user_id),
                self._state.get_agent_rules(tenant_id, user_id),
                self._state.get_entity_index(tenant_id, user_id),
                return_exceptions=True,
            )
            return (
                profile if isinstance(profile, str) else "",
                rules if isinstance(rules, str) else "",
                entities if isinstance(entities, str) else "",
            )
        except Exception as e:
            logger.warning("Failed to load existing state: %s", e)
            return "", "", ""

    async def _invoke_llm(self, prompt: str) -> dict | None:
        """调用 LLM 并解析 JSON 输出"""
        try:
            result = await self._llm.ainvoke(prompt)
            text = (getattr(result, "content", None) or str(result)).strip()
            if "{" in text and "}" in text:
                json_str = text[text.index("{"):text.rindex("}") + 1]
                try:
                    return json.loads(json_str)
                except json.JSONDecodeError:
                    repaired = self._repair_json(json_str)
                    if repaired is not None:
                        return repaired
                    logger.warning(
                        "LLM output JSON parse failed, raw text (first 500 chars): %s",
                        json_str[:500],
                    )
        except Exception as e:
            logger.error("LLM invocation failed: %s", e)
        return None

    @staticmethod
    def _repair_json(raw: str) -> dict | None:
        """尝试修复常见的 LLM JSON 输出问题并解析"""
        text = raw
        text = text.replace("\n", "\\n").replace("\t", "\\t")
        text = re.sub(r",\s*([}\]])", r"\1", text)
        text = re.sub(r'"\s*\n?\s*"', '", "', text)
        text = re.sub(r'([}\]])\s*"', r'\1, "', text)

        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        try:
            return json.loads(raw.replace("'", '"'))
        except json.JSONDecodeError:
            pass

        return None

    def _filter_user_messages(self, messages: list) -> list:
        """过滤出仅 user 消息"""
        user_msgs = []
        for msg in messages:
            msg_type = getattr(msg, "type", None) or getattr(msg, "role", "")
            if msg_type in ("human", "user"):
                user_msgs.append(msg)
        return user_msgs

    def _format_messages(self, messages: list) -> str:
        """格式化消息列表为文本"""
        lines = []
        for msg in messages:
            role = getattr(msg, "type", None) or getattr(msg, "role", "unknown")
            content = getattr(msg, "content", None) or str(msg)
            if isinstance(content, str):
                lines.append(f"[{role}]: {content[:500]}")
        return "\n".join(lines)

    def _post_filter(self, items: list[ExtractionItem]) -> list[ExtractionItem]:
        """后处理过滤：移除仅含精确数值的 entities 记忆"""
        filtered = []
        for item in items:
            if item.dimension == "entities" and _contains_only_precise_values(item.content):
                logger.debug("Filtered out precise-value-only item: %s", item.abstract[:50])
                continue
            filtered.append(item)
        return filtered


# ═══════════════════════════════════════════════════════════
# [DEPRECATED] v2 四路并行提取方法（注释保留供回退）
# ═══════════════════════════════════════════════════════════

# class MemoryExtractorV2:
#     """四路并行记忆提取器（已废弃）
#
#     原逻辑：
#     - extract_all 中创建 4 个 asyncio.Task 并行执行
#     - 每路独立调用 LLM（_extract_profile/_extract_preferences/
#       _extract_agent_rules/_extract_entities）
#     - 结果合并后 _post_filter
#
#     废弃原因：
#     - 4 次 LLM 调用成本高（input tokens 重复 4 倍）
#     - 维度边界冲突在各路独立判断时无法一致消解
#     - 统一提取 v3 用 CoT + 决策树在单次调用中完成
#
#     如需回退，将下方代码解除注释并恢复 extract_all 中的 asyncio.gather 逻辑：
#
#     async def _extract_profile(self, user_text, existing, output_language):
#         prompt = PROFILE_EXTRACT_PROMPT.format(
#             existing_profile=existing or "（无历史画像）",
#             user_messages=user_text, output_language=output_language)
#         data = await self._invoke_llm(prompt)
#         ...
#
#     async def _extract_preferences(self, user_text, output_language):
#         prompt = PREFERENCES_EXTRACT_PROMPT.format(
#             user_messages=user_text, output_language=output_language)
#         data = await self._invoke_llm(prompt)
#         ...
#
#     async def _extract_agent_rules(self, user_text, existing, output_language):
#         prompt = AGENT_RULES_EXTRACT_PROMPT.format(
#             existing_rules=existing or "（无历史规则）",
#             user_messages=user_text, output_language=output_language)
#         data = await self._invoke_llm(prompt)
#         ...
#
#     async def _extract_entities(self, conversation, existing, output_language):
#         prompt = ENTITIES_EXTRACT_PROMPT.format(
#             existing_entities=existing or "（无已有实体）",
#             conversation=conversation, output_language=output_language)
#         data = await self._invoke_llm(prompt)
#         ...
#     """
#     pass
