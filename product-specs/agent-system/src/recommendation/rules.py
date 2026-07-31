"""内置推荐规则 — 从信号模式生成卡片候选"""
from __future__ import annotations

import re
import time
from abc import ABC, abstractmethod
from collections import Counter
from typing import Any

from .cards import RecommendationCard
from .signals import UserSignal


class PatternRule(ABC):
    """推荐规则基类"""

    @abstractmethod
    def evaluate(self, signals: list[UserSignal], context: dict[str, Any]) -> list[RecommendationCard]:
        ...


class RepeatViewRule(PatternRule):
    """用户连续查看同一实体 ≥ 2 次 → 推荐深度分析"""

    def evaluate(self, signals: list[UserSignal], context: dict[str, Any]) -> list[RecommendationCard]:
        # 统计 (entity_type, entity_key) 的 view/query 次数
        view_counter: Counter[tuple[str, str]] = Counter()
        entity_names: dict[tuple[str, str], str] = {}
        for s in signals:
            if s.action in ("view", "query", "insight") and s.entity_key:
                key = (s.entity_type, s.entity_key)
                view_counter[key] += 1
                name = s.context.get("name") or s.context.get("accountName") or s.entity_key
                entity_names[key] = name

        cards: list[RecommendationCard] = []
        for (entity_type, entity_key), count in view_counter.items():
            if count < 2:
                continue
            name = entity_names.get((entity_type, entity_key), entity_key)
            cards.append(RecommendationCard(
                card_id="",
                title=f"深度分析 {name}",
                icon="🔍",
                reason=f"您已查看 {name} {count} 次，建议生成完整洞察报告",
                command=f"帮我深度分析客户 {name}，CRM记录标识: {entity_key}",
                priority=2,
                category="insight",
            ))
        return cards


class MissingLinkRule(PatternRule):
    """查看客户后未查看商机/联系人 → 推荐关联查询"""

    def evaluate(self, signals: list[UserSignal], context: dict[str, Any]) -> list[RecommendationCard]:
        # 找到被查看的 account，检查是否有后续 opportunity/contact 操作
        viewed_accounts: dict[str, str] = {}  # entity_key → name
        has_related_action: set[str] = set()

        for s in signals:
            if s.entity_type == "account" and s.action in ("view", "query") and s.entity_key:
                name = s.context.get("name") or s.context.get("accountName") or s.entity_key
                viewed_accounts[s.entity_key] = name
            elif s.entity_type in ("opportunity", "contact") and s.entity_key:
                # 关联到 account
                account_key = s.context.get("accountId") or s.context.get("account_key")
                if account_key:
                    has_related_action.add(account_key)

        cards: list[RecommendationCard] = []
        for account_key, name in viewed_accounts.items():
            if account_key in has_related_action:
                continue
            cards.append(RecommendationCard(
                card_id="",
                title=f"查看 {name} 的商机情况",
                icon="📈",
                reason=f"您查看了 {name} 的客户信息，但尚未查看其商机和联系人",
                command=f"帮我查询客户 {name} 的商机列表",
                priority=3,
                category="action_suggestion",
            ))
        return cards[:2]  # 最多 2 张


class QueryFailedRule(PatternRule):
    """查询失败 → 推荐核实并重试"""

    def evaluate(self, signals: list[UserSignal], context: dict[str, Any]) -> list[RecommendationCard]:
        cards: list[RecommendationCard] = []
        for s in signals:
            if s.action != "failed_query":
                continue
            query_text = s.context.get("query_text", "")
            entity_type = s.entity_type or "记录"
            cards.append(RecommendationCard(
                card_id="",
                title="核实记录信息并重新查询",
                icon="🔄",
                reason=f"CRM系统中未找到与'{query_text}'匹配的{entity_type}，"
                       f"建议核实名称、所属实体类型及编号来源后重新查询",
                command=f"请用模糊搜索重新查找与 {query_text} 相关的{entity_type}",
                priority=2,
                category="action_suggestion",
            ))
        return cards[:1]


class SalesPersonFocusRule(PatternRule):
    """同一销售的商机被查看 ≥ 3 次 → 推荐汇总"""

    def evaluate(self, signals: list[UserSignal], context: dict[str, Any]) -> list[RecommendationCard]:
        owner_counter: Counter[str] = Counter()
        owner_names: dict[str, str] = {}

        for s in signals:
            if s.entity_type == "opportunity" and s.action in ("view", "query"):
                owner = s.context.get("owner") or s.context.get("ownerName")
                if owner:
                    owner_counter[owner] += 1
                    owner_names[owner] = owner

        cards: list[RecommendationCard] = []
        for owner, count in owner_counter.items():
            if count < 3:
                continue
            cards.append(RecommendationCard(
                card_id="",
                title=f"汇总 {owner} 的所有商机",
                icon="👤",
                reason=f"您已查看 {owner} 负责的商机 {count} 次，建议生成汇总分析",
                command=f"帮我查询 {owner} 负责的所有商机，按阶段分组统计",
                priority=2,
                category="insight",
            ))
        return cards[:1]


class TimeBasedRule(PatternRule):
    """时间敏感提醒（月底、首次登录等）"""

    def evaluate(self, signals: list[UserSignal], context: dict[str, Any]) -> list[RecommendationCard]:
        cards: list[RecommendationCard] = []
        now = time.localtime()
        days_left_in_month = 31 - now.tm_mday  # 粗略估计

        # 月底 5 天内
        if days_left_in_month <= 5:
            cards.append(RecommendationCard(
                card_id="",
                title="本月业绩汇总",
                icon="📊",
                reason=f"距月底还有 {days_left_in_month} 天，建议检查本月商机进展",
                command="帮我统计本月的商机成交情况和预计成交金额",
                priority=1,
                category="reminder",
                dedup_key="monthly_summary",
            ))

        # 周一
        if now.tm_wday == 0:
            cards.append(RecommendationCard(
                card_id="",
                title="本周工作规划",
                icon="📅",
                reason="新的一周开始，建议梳理本周待跟进客户和商机",
                command="帮我列出本周需要跟进的客户和即将到期的商机",
                priority=2,
                category="reminder",
                dedup_key="weekly_plan",
            ))

        return cards


class UnfinishedTaskRule(PatternRule):
    """创建操作后缺少跟进 → 提醒"""

    def evaluate(self, signals: list[UserSignal], context: dict[str, Any]) -> list[RecommendationCard]:
        # 找到 create 操作后 10 分钟内无后续 create/edit 操作的记录
        creates: list[UserSignal] = []
        followups: set[str] = set()

        for s in signals:
            if s.action == "create" and s.entity_key:
                creates.append(s)
            elif s.action in ("edit", "create") and s.entity_key:
                followups.add(s.entity_key)

        now = int(time.time() * 1000)
        cards: list[RecommendationCard] = []
        for s in creates:
            if s.entity_key in followups:
                continue
            if now - s.timestamp < 10 * 60_000:  # 10 分钟内不提醒
                continue
            name = s.context.get("name") or s.entity_key or ""
            entity_label = {"opportunity": "商机", "contact": "联系人",
                           "activity": "活动", "account": "客户"}.get(s.entity_type, "记录")
            cards.append(RecommendationCard(
                card_id="",
                title=f"为{entity_label} {name} 创建跟进计划",
                icon="📝",
                reason=f"您创建了{entity_label} {name}，但尚未添加跟进活动",
                command=f"帮我为{entity_label} {name} 创建一个跟进活动",
                priority=3,
                category="action_suggestion",
            ))
        return cards[:2]


# 全部内置规则
BUILTIN_RULES: list[PatternRule] = [
    RepeatViewRule(),
    MissingLinkRule(),
    QueryFailedRule(),
    SalesPersonFocusRule(),
    TimeBasedRule(),
    UnfinishedTaskRule(),
]
