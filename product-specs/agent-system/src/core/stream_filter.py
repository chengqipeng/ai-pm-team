"""流式输出过滤器 — 去除 LLM 输出中的 NLU 分析片段

问题背景：
部分模型（如 doubao-seed-2-0-lite）在回复用户时会自发输出 NLU 分析过程，
例如："改写：xxx。实体：xxx。代词：xxx 指代 xxx。业务概念：xxx。" 之后才是正常回复。
这些内部分析不应展示给用户。

解决方案：
在 token 流下发到前端前做流式过滤。用状态机 + buffer 实现：
- 识别"改写：/实体：/代词：/业务概念：/意图：/指代：/提取实体："等起始标记
- 进入 skip 模式，持续丢弃 token 直到遇到结束字符（。！？.!?\n）
- 支持 token 被切断在 pattern 中间的情况（buffer 预读）
"""

from __future__ import annotations

# NLU 分析片段的起始标记（按长度降序，优先长匹配）
_NLU_START_PATTERNS = (
    "改写后的查询：", "改写后的查询:",
    "改写后：", "改写后:",
    "意图分析：", "意图分析:",
    "提取实体：", "提取实体:",
    "业务概念：", "业务概念:",
    "实体名：", "实体名:",
    "改写：", "改写:",
    "实体：", "实体:",
    "代词：", "代词:",
    "意图：", "意图:",
    "指代：", "指代:",
)

# 结束标记（遇到这些字符就结束 skip 模式）
_NLU_END_CHARS = frozenset("。！？\n.!?")

# 用于检测 pattern 最长前缀的长度
_MAX_PATTERN_LEN = max(len(p) for p in _NLU_START_PATTERNS)


class StreamAnalysisFilter:
    """流式分析片段过滤器 — 有状态，每个对话 thread 一个实例

    用法:
        f = StreamAnalysisFilter()
        for token in stream:
            out = f.feed(token)
            if out:
                yield out
        # 流结束后刷新 buffer
        final = f.flush()
        if final:
            yield final
    """

    __slots__ = ("_buffer", "_skipping")

    def __init__(self) -> None:
        self._buffer: str = ""
        self._skipping: bool = False

    def feed(self, token: str) -> str:
        """处理一个新 token，返回可下发的文本（可能为空字符串）"""
        if not token:
            return ""

        output: list[str] = []
        buffer = self._buffer + token
        skipping = self._skipping
        i = 0
        n = len(buffer)

        while i < n:
            if skipping:
                if buffer[i] in _NLU_END_CHARS:
                    # 结束 skip，跳过这个结束字符本身
                    skipping = False
                    i += 1
                else:
                    i += 1
                continue

            # 正常模式：检查是否匹配某个 pattern
            matched_pattern = None
            for pattern in _NLU_START_PATTERNS:
                plen = len(pattern)
                if i + plen <= n and buffer[i:i + plen] == pattern:
                    matched_pattern = pattern
                    break

            if matched_pattern is not None:
                skipping = True
                i += len(matched_pattern)
                continue

            # 检查 buffer[i:] 是否是某个 pattern 的前缀（需要等更多 token）
            remaining = n - i
            if remaining < _MAX_PATTERN_LEN:
                # 可能还在 pattern 中间，检查是否是任一 pattern 的前缀
                suffix = buffer[i:]
                is_prefix = any(
                    p.startswith(suffix) and len(suffix) < len(p)
                    for p in _NLU_START_PATTERNS
                )
                if is_prefix:
                    break  # 保留到 buffer，等下一个 token

            # 正常字符
            output.append(buffer[i])
            i += 1

        # 更新状态
        self._buffer = buffer[i:]
        self._skipping = skipping
        return "".join(output)

    def flush(self) -> str:
        """刷新剩余 buffer。流结束时调用。

        修复：之前在 skip 模式下直接丢弃所有 buffer，导致 LLM 最终回复
        如果以 NLU 分析开头（如"意图：确认修改。好的，已为您更新..."），
        整段回复被吞掉。

        新策略：skip 模式下仍尝试从 buffer 中提取结束标记之后的正常内容。
        如果 buffer 全是分析内容（无结束标记），才丢弃。
        """
        remaining = self._buffer
        self._buffer = ""
        if self._skipping:
            self._skipping = False
            # 尝试从 remaining 中找到结束标记，输出其后的正常内容
            for i, ch in enumerate(remaining):
                if ch in _NLU_END_CHARS:
                    # 结束标记之后的内容是正常文本
                    after = remaining[i + 1:].lstrip()
                    if after:
                        return after
            # 没有结束标记，整段可能是分析内容，丢弃
            return ""
        return remaining
