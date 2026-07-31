"""AI 工作台推荐引擎 — 信号采集 + 模式识别 + 卡片生成"""
from .signals import UserSignal, SignalBuffer, signal_buffer
from .cards import RecommendationCard, CardStore, card_store
from .engine import evaluate_recommendations
from .defaults import get_default_cards

__all__ = [
    "UserSignal",
    "SignalBuffer",
    "signal_buffer",
    "RecommendationCard",
    "CardStore",
    "card_store",
    "evaluate_recommendations",
    "get_default_cards",
]
