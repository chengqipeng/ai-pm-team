"""流式 PII 还原器 — 在 SSE 推送前将占位符还原为原始值

问题背景：
InputTransformMiddleware 在 before_agent 阶段将用户输入中的 PII 替换为占位符
（如 <PII:CN_PHONE_1>），LLM 输出中可能包含这些占位符。OutputRenderMiddleware
的 after_agent 阶段做 PII 还原，但此时 token 已经通过 SSE 流式推送给前端了。

解决方案：
在 token 流下发到前端前做流式 PII 还原。用 buffer 机制处理占位符被切断在
多个 chunk 中间的情况：
- 遇到 '<' 或 'PII:' 等占位符起始标记时进入 buffer 模式
- 积累 buffer 直到匹配完整占位符或确认不是占位符
- 匹配成功则输出原始值，匹配失败则原样输出 buffer 内容

兼容 LLM 幻觉导致的占位符变形（对齐 PIIRedactTransformer.restore_pii）：
- 标准格式: <PII:CN_PHONE_1>
- 无尖括号: PII:CN_PHONE_1
- 纯 key:   CN_PHONE_1
- 大小写不敏感
"""

from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

# 占位符最大长度（<PII:CN_BANK_CARD_99> = 22 字符），留足余量
_MAX_PLACEHOLDER_LEN = 30

# 可能是占位符起始的字符/字符串
_TRIGGER_CHARS = frozenset("<PC")  # '<' for <PII:, 'P' for PII:, 'C' for CN_


class StreamPIIRestorer:
    """流式 PII 还原器 — 有状态，每个对话 thread 一个实例

    用法:
        restorer = StreamPIIRestorer(input_metadata)
        for token in stream:
            out = restorer.feed(token)
            if out:
                yield out
        # 流结束后刷新 buffer
        final = restorer.flush()
        if final:
            yield final
    """

    __slots__ = ("_buffer", "_placeholders", "_pattern", "_enabled", "_key_map", "_metadata_ref")

    def __init__(self, input_metadata: dict[str, Any] | None = None) -> None:
        self._buffer: str = ""
        self._placeholders: dict[str, str] = {}
        self._pattern: re.Pattern | None = None
        self._enabled: bool = False
        self._key_map: dict[str, str] = {}
        # 保持对 input_metadata 的引用，以便延迟获取 pii_placeholders
        # （InputTransformMiddleware.before_agent 在 astream_events 内部执行，
        #   会在流式输出开始前将 pii_placeholders 写入此 dict）
        self._metadata_ref: dict[str, Any] | None = input_metadata

        if input_metadata:
            pii_placeholders = input_metadata.get("pii_placeholders", {})
            if pii_placeholders:
                self._placeholders = pii_placeholders
                self._enabled = True
                self._build_pattern()

    def update_placeholders(self, placeholders: dict[str, str]) -> None:
        """动态更新占位符映射（InputTransformMiddleware 执行后调用）"""
        if placeholders:
            self._placeholders = placeholders
            self._enabled = True
            self._build_pattern()

    def _build_pattern(self) -> None:
        """构建匹配正则 — 对齐 PIIRedactTransformer.restore_pii"""
        if not self._placeholders:
            self._pattern = None
            return

        # 提取核心 key（去掉 <PII: 和 >）
        key_map: dict[str, str] = {}
        for placeholder, original in self._placeholders.items():
            core = placeholder.replace("<PII:", "").replace(">", "")
            key_map[core.upper()] = original

        # 按 key 长度降序排列
        sorted_keys = sorted(key_map.keys(), key=len, reverse=True)
        keys_pattern = '|'.join(re.escape(k) for k in sorted_keys)

        # 前缀 < 和 PII: 分别可选，兼容各种变体
        self._pattern = re.compile(
            r'<?(?:PII:)?(' + keys_pattern + r')\s*>?',
            re.IGNORECASE,
        )
        # 保存 key_map 供替换使用
        self._key_map = key_map

    def feed(self, token: str) -> str:
        """处理一个新 token，返回可下发的文本（可能为空字符串）"""
        if not token:
            return ""

        # 延迟初始化：首次 feed 时检查 metadata_ref 中是否已有 pii_placeholders
        # （InputTransformMiddleware.before_agent 在 astream_events 内部执行，
        #   会在第一个 LLM token 产出前完成 PII 脱敏并写入 placeholders）
        if not self._enabled and self._metadata_ref:
            pii_placeholders = self._metadata_ref.get("pii_placeholders", {})
            if pii_placeholders:
                self._placeholders = pii_placeholders
                self._enabled = True
                self._build_pattern()
                logger.info("[StreamPIIRestorer] 延迟加载 %d 个 PII 占位符", len(pii_placeholders))

        if not self._enabled:
            return token

        buffer = self._buffer + token
        output: list[str] = []
        i = 0
        n = len(buffer)

        while i < n:
            ch = buffer[i]

            # 检查是否可能是占位符的起始
            if ch in _TRIGGER_CHARS:
                remaining = buffer[i:]

                # 尝试完整匹配
                match = self._pattern.match(remaining) if self._pattern else None
                if match:
                    # 匹配成功 → 输出原始值
                    key = match.group(1).upper()
                    original = self._key_map.get(key, match.group(0))
                    output.append(original)
                    i += match.end()
                    continue

                # 检查是否可能是不完整的占位符（需要更多 token）
                if len(remaining) < _MAX_PLACEHOLDER_LEN:
                    # 检查 remaining 是否像占位符的前缀
                    if self._looks_like_placeholder_prefix(remaining):
                        # 保留到 buffer，等下一个 token
                        self._buffer = remaining
                        return "".join(output)

                # 不是占位符，正常输出
                output.append(ch)
                i += 1
            else:
                output.append(ch)
                i += 1

        self._buffer = ""
        return "".join(output)

    def flush(self) -> str:
        """刷新剩余 buffer。流结束时调用。"""
        remaining = self._buffer
        self._buffer = ""
        if not remaining:
            return ""

        # 最后一次尝试匹配（可能是完整的占位符）
        if self._pattern:
            match = self._pattern.match(remaining)
            if match and match.end() == len(remaining):
                key = match.group(1).upper()
                return self._key_map.get(key, remaining)

        # 不是占位符，原样输出
        return remaining

    def _looks_like_placeholder_prefix(self, text: str) -> bool:
        """判断文本是否像占位符的前缀（不完整的占位符）

        占位符格式: <PII:CN_PHONE_1> 或 PII:CN_PHONE_1 或 CN_PHONE_1
        前缀示例: '<', '<P', '<PII', '<PII:', '<PII:CN', 'P', 'PI', 'PII:', 'CN_'
        """
        # 标准格式前缀
        prefixes = ("<", "<P", "<PI", "<PII", "<PII:", "PII:", "PII", "PI", "CN_")
        text_upper = text.upper()

        for prefix in prefixes:
            if text_upper.startswith(prefix):
                # 进一步验证：前缀之后的字符应该是字母、数字、下划线或 >
                after = text_upper[len(prefix):]
                if not after or all(c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_> :" for c in after):
                    return True

        return False
