"""四路并行记忆提取器

P0 优化实现：
- 4 路并行 LLM 调用（profile / preferences / agent_rules / entities）
- 输入过滤：profile/preferences/agent_rules 仅 user 消息，entities 全量
- 已有状态注入：profile/agent_rules 注入已有记忆避免重复
- 多租户隔离：tenant_id 全链路
- 输出语言控制：output_language 参数
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from .prompts import (
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
    """四路提取的汇总结果"""
    items: list[ExtractionItem] = field(default_factory=list)
    tenant_id: str = ""
    user_id: str = ""
    thread_id: str = ""
    duration_ms: float = 0.0
    errors: list[str] = field(default_factory=list)


# ═══════════════════════════════════════════════════════════
# 数值过滤规则（P1-9 前置实现）
# ═══════════════════════════════════════════════════════════

import re

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
    # 移除所有精确值后，剩余有效文字 < 10 字则认为无增量认知
    cleaned = text
    for pattern in _NUMERIC_PATTERNS:
        cleaned = pattern.sub("", cleaned)
    # 移除标点和空白
    cleaned = re.sub(r'[\s\W]+', '', cleaned)
    return len(cleaned) < 10


# ═══════════════════════════════════════════════════════════
# 核心提取器
# ═══════════════════════════════════════════════════════════

class MemoryExtractor:
    """四路并行记忆提取器

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
        """四路并行提取，返回汇总结果"""
        start = time.monotonic()
        result = ExtractionResult(
            tenant_id=tenant_id, user_id=user_id, thread_id=thread_id,
        )

        if not messages or not self._llm:
            return result

        # 预处理：提取用户原始消息（排除 middleware 注入的系统指令）
        user_messages = self._filter_user_messages(messages)
        user_text = self._format_messages(user_messages) if user_messages else ""

        if not user_text:
            return result

        # 获取已有状态（并行）
        existing_profile, existing_rules, existing_entities = await self._load_existing_state(
            tenant_id, user_id
        )

        # 四路并行提取（全部只用 user 消息）
        tasks = [
            self._extract_profile(user_text, existing_profile, output_language),
            self._extract_preferences(user_text, output_language),
            self._extract_agent_rules(user_text, existing_rules, output_language),
            self._extract_entities(user_text, existing_entities, output_language),
        ]

        results = await asyncio.gather(*tasks, return_exceptions=True)
        dimension_names = ["profile", "preferences", "agent_rules", "entities"]

        for i, res in enumerate(results):
            if isinstance(res, Exception):
                error_msg = f"{dimension_names[i]} 提取失败: {res}"
                logger.error(error_msg, exc_info=True)
                result.errors.append(error_msg)
            elif res:
                result.items.extend(res)

        # 跨维度去重：如果 agent_rules 有提取结果，过滤掉与其重叠的 preferences
        result.items = self._post_filter(result.items)

        result.duration_ms = (time.monotonic() - start) * 1000
        logger.info(
            "MemoryExtractor: extracted %d items in %.0fms (tenant=%s, user=%s, errors=%d)",
            len(result.items), result.duration_ms, tenant_id, user_id, len(result.errors),
        )
        return result

    # ─────────────────────────────────────────────────────
    # 四路提取实现
    # ─────────────────────────────────────────────────────

    async def _extract_profile(
        self, user_text: str, existing: str, output_language: str,
    ) -> list[ExtractionItem]:
        """提取用户画像"""
        prompt = PROFILE_EXTRACT_PROMPT.format(
            existing_profile=existing or "（无历史画像）",
            user_messages=user_text,
            output_language=output_language,
        )
        data = await self._invoke_llm(prompt)
        if not data:
            return []

        profile = data.get("profile", {})
        content = profile.get("content", "")
        if not content:
            return []

        return [ExtractionItem(
            dimension="profile",
            content=content,
            abstract=f"用户画像: {content[:80]}",
            merge_key="profile",
            source_type="insight",
        )]

    async def _extract_preferences(
        self, user_text: str, output_language: str,
    ) -> list[ExtractionItem]:
        """提取用户偏好"""
        prompt = PREFERENCES_EXTRACT_PROMPT.format(
            user_messages=user_text,
            output_language=output_language,
        )
        data = await self._invoke_llm(prompt)
        if not data:
            return []

        preferences = data.get("preferences", [])
        if not preferences:
            return []

        items = []
        for pref in preferences:
            slug = pref.get("slug", "")
            abstract = pref.get("abstract", "")
            if not abstract:
                continue

            items.append(ExtractionItem(
                dimension="preferences",
                slug=slug,
                abstract=abstract,
                overview=pref.get("overview", ""),
                content=pref.get("content", abstract),
                merge_key=f"preferences/{slug}" if slug else "preferences",
                parent_entity="preferences",
                source_type="insight",
            ))

        # slug 去重校验：同一 slug 只保留最后一条
        seen_slugs: dict[str, ExtractionItem] = {}
        for item in items:
            seen_slugs[item.slug] = item
        return list(seen_slugs.values())

    async def _extract_agent_rules(
        self, user_text: str, existing: str, output_language: str,
    ) -> list[ExtractionItem]:
        """提取 Agent 行为准则（原 soul）"""
        prompt = AGENT_RULES_EXTRACT_PROMPT.format(
            existing_rules=existing or "（无历史规则）",
            user_messages=user_text,
            output_language=output_language,
        )
        data = await self._invoke_llm(prompt)
        if not data:
            return []

        rules = data.get("agent_rules", {})
        content = rules.get("content", "")
        if not content:
            return []

        return [ExtractionItem(
            dimension="agent_rules",
            content=content,
            abstract=f"Agent行为准则: {content[:80]}",
            merge_key="agent_rules",
            source_type="insight",
        )]

    async def _extract_entities(
        self, conversation: str, existing: str, output_language: str,
    ) -> list[ExtractionItem]:
        """提取实体与事实"""
        prompt = ENTITIES_EXTRACT_PROMPT.format(
            existing_entities=existing or "（无已有实体）",
            conversation=conversation,
            output_language=output_language,
        )
        data = await self._invoke_llm(prompt)
        if not data:
            return []

        entities = data.get("entities", [])
        if not entities:
            return []

        items = []
        for ent in entities:
            abstract = ent.get("abstract", "")
            if not abstract or len(abstract) < 5:
                continue

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
                    # 尝试修复常见 JSON 格式问题后重试
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
        """尝试修复常见的 LLM JSON 输出问题并解析。

        常见问题：
        1. 尾部多余逗号 (trailing comma)
        2. 单引号代替双引号
        3. 未转义的换行符
        4. 值中缺少逗号分隔（如 "key1": "val1" "key2": "val2"）
        """
        import re

        text = raw
        # 1. 替换未转义的换行/制表符
        text = text.replace("\n", "\\n").replace("\t", "\\t")
        # 2. 移除尾部逗号 (,] 或 ,})
        text = re.sub(r",\s*([}\]])", r"\1", text)
        # 3. 尝试修复缺少逗号的情况: "..." "..." → "...", "..."
        text = re.sub(r'"\s*\n?\s*"', '", "', text)
        # 4. 修复 }" 或 ]" 后缺少逗号的情况
        text = re.sub(r'([}\]])\s*"', r'\1, "', text)

        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # 5. 最后尝试：单引号替换为双引号
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
