"""默认推荐卡片 — 首次登录或空会话时的兜底"""
from __future__ import annotations

from .cards import RecommendationCard


def get_default_cards() -> list[RecommendationCard]:
    """返回默认快捷卡片（替代原欢迎页静态卡片）"""
    return [
        RecommendationCard(
            card_id="default-active-customers",
            title="查看活跃客户",
            icon="🏢",
            command="帮我查一下活跃客户，按营收排序",
            priority=3,
            category="action_suggestion",
            dedup_key="default_active_customers",
        ),
        RecommendationCard(
            card_id="default-pipeline",
            title="Pipeline 分析",
            icon="📈",
            command="帮我分析商机 Pipeline，按阶段统计金额",
            priority=3,
            category="action_suggestion",
            dedup_key="default_pipeline",
        ),
        RecommendationCard(
            card_id="default-customer-count",
            title="客户统计",
            icon="📊",
            command="系统中有多少个客户？",
            priority=4,
            category="action_suggestion",
            dedup_key="default_customer_count",
        ),
        RecommendationCard(
            card_id="default-config-check",
            title="配置校验",
            icon="🔍",
            command="帮我校验商机的元数据配置",
            priority=4,
            category="action_suggestion",
            dedup_key="default_config_check",
        ),
    ]
