"""记忆提取模块 — 四路并行提取

P0 优化：将原 EXTRACTION_PROMPT 单 prompt 9 类拆为 4 路并行：
  - profile: 用户画像
  - preferences: 用户偏好
  - agent_rules: Agent 行为准则
  - entities: 实体与事实
"""

from .extractor import MemoryExtractor
from .prompts import (
    PROFILE_EXTRACT_PROMPT,
    PREFERENCES_EXTRACT_PROMPT,
    AGENT_RULES_EXTRACT_PROMPT,
    ENTITIES_EXTRACT_PROMPT,
)

__all__ = [
    "MemoryExtractor",
    "PROFILE_EXTRACT_PROMPT",
    "PREFERENCES_EXTRACT_PROMPT",
    "AGENT_RULES_EXTRACT_PROMPT",
    "ENTITIES_EXTRACT_PROMPT",
]
