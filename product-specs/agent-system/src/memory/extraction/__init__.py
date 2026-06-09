"""记忆提取模块 — 统一单次提取 v3

v3: 单次 LLM 调用完成四维度提取（UNIFIED_EXTRACT_PROMPT）
v2: [DEPRECATED] 四路并行提取（保留导入供测试/回退使用）
"""

from .extractor import MemoryExtractor, ExtractionItem, ExtractionResult
from .prompts import (
    UNIFIED_EXTRACT_PROMPT,
    # v2 遗留（供测试和 eval 对比使用）
    PROFILE_EXTRACT_PROMPT,
    PREFERENCES_EXTRACT_PROMPT,
    AGENT_RULES_EXTRACT_PROMPT,
    ENTITIES_EXTRACT_PROMPT,
)

__all__ = [
    "MemoryExtractor",
    "ExtractionItem",
    "ExtractionResult",
    "UNIFIED_EXTRACT_PROMPT",
    # v2 遗留导出
    "PROFILE_EXTRACT_PROMPT",
    "PREFERENCES_EXTRACT_PROMPT",
    "AGENT_RULES_EXTRACT_PROMPT",
    "ENTITIES_EXTRACT_PROMPT",
]
