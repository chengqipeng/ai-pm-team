"""Skill 模式上下文压缩增强 — 解决 Skill 执行导致的上下文膨胀问题

解决的三个核心缺口：
  1. min_tail_messages 在 Skill 模式下保护不够 → Skill 边界感知的尾部保护
  2. 并发 tool_calls 的工具组切割风险 → 深度边界对齐（原子组保护）
  3. 多轮 Skill 迭代摘要信息衰减 → SkillResultAnchor 持久锚点

额外增强：
  4. Post-Skill Compact — Skill 结束后即时压缩内部消息，在源头控制膨胀

设计参考：
  - 缺口分析文档 §4.1 ~ §4.4
  - Hermes Agent: _align_boundary_backward
  - Claude Code: MicroCompact 保护区逻辑
"""
from __future__ import annotations

import logging
import re
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════
# §4.1 Skill 执行边界感知的尾部保护
# ═══════════════════════════════════════════════════════════

class SkillAwareTailProtection:
    """Skill 模式下的尾部保护 — 以 Skill 执行为原子单位

    解决问题: 固定 min_tail_messages=5/6 在 Skill 产生 20-27 条消息时，
    压缩切割点容易落在 Skill 内部，导致用户追问时无法回溯具体查询细节。

    规则:
      1. Token 预算是第一优先级（基础逻辑不变）
      2. 如果 token 预算的切割点落在 Skill 执行中间，将切割点推进到 Skill 起始位置
      3. min_tail 硬底线仍为原值
      4. max_tail 上限 30 条，防止巨型 Skill 过度保护尾部
    """

    def __init__(self, min_tail_messages: int = 5, max_tail_messages: int = 30):
        self.min_tail = min_tail_messages
        self.max_tail = max_tail_messages

    def compute_tail_start(self, messages: list, keep_recent: int, head_end: int = 0) -> int:
        """计算 Skill 边界感知的尾部保护起始位置

        Args:
            messages: 完整消息列表
            keep_recent: 基础保护条数（来自各 Pass 的 keep_recent 参数）
            head_end: 头部保护区结束位置（system prompt 等）

        Returns:
            尾部保护的起始 index — messages[返回值:] 都应被保护
        """
        n = len(messages)
        if n <= keep_recent:
            return 0

        # 基础切割点
        base_cut = n - keep_recent

        # 确保不小于 head_end
        base_cut = max(base_cut, head_end)

        # 检查切割点是否落在 Skill 执行内部
        skill_boundary = self._find_enclosing_skill_start(messages, base_cut, head_end)

        if skill_boundary is not None and skill_boundary < base_cut:
            # 切割点在 Skill 内部 → 推到 Skill 起始前（完整保护该 Skill）
            protected_count = n - skill_boundary
            if protected_count <= self.max_tail:
                logger.debug(
                    "[SkillTailProtect] 切割点 %d 在 Skill 内部，推进到 %d (保护 %d 条)",
                    base_cut, skill_boundary, protected_count,
                )
                return skill_boundary
            else:
                # Skill 太大，超过 max_tail → 保留基础切割点（Skill 会被部分压缩）
                logger.debug(
                    "[SkillTailProtect] Skill 过大 (%d 条 > max_tail %d)，保留基础切割",
                    protected_count, self.max_tail,
                )
                return base_cut

        return base_cut

    def _find_enclosing_skill_start(
        self, messages: list, cut_idx: int, head_end: int
    ) -> int | None:
        """查找 cut_idx 所处的 Skill 执行边界

        Skill 执行的标识:
          - 起始: AIMessage 含 tool_calls 中有 name="skills_tool"
          - 结束: ToolMessage 且 name="skills_tool"（返回最终结果）

        如果 cut_idx 在起始和结束之间 → 返回起始位置
        如果 cut_idx 不在 Skill 内部 → 返回 None
        """
        # 从 cut_idx 向前找最近的 skills_tool 启动
        skill_start = None

        for i in range(cut_idx - 1, max(head_end - 1, -1), -1):
            msg = messages[i]

            # 检查是否是 skills_tool 的结果返回（意味着 cut_idx 在这个 Skill 之后）
            if isinstance(msg, ToolMessage):
                tool_name = getattr(msg, "name", "") or ""
                if tool_name == "skills_tool":
                    # cut_idx 在此 Skill 结束之后 → 不在 Skill 内部
                    return None

            # 检查是否是 skills_tool 的调用发起
            if isinstance(msg, AIMessage) and getattr(msg, "tool_calls", None):
                for tc in msg.tool_calls:
                    if tc.get("name") == "skills_tool":
                        skill_start = i
                        break
                if skill_start is not None:
                    break

        if skill_start is None:
            return None

        # 从 skill_start 向后找对应的 skills_tool 结果
        skill_end = None
        for i in range(skill_start + 1, len(messages)):
            msg = messages[i]
            if isinstance(msg, ToolMessage):
                tool_name = getattr(msg, "name", "") or ""
                if tool_name == "skills_tool":
                    skill_end = i
                    break

        if skill_end is None:
            # Skill 正在执行中（还没有最终结果）→ 保护到当前位置
            return skill_start

        # cut_idx 在 [skill_start, skill_end] 之间 → 整个 Skill 纳入保护
        if skill_start <= cut_idx <= skill_end:
            return skill_start

        return None


# ═══════════════════════════════════════════════════════════
# §4.2 工具组原子性增强 — 深度边界对齐
# ═══════════════════════════════════════════════════════════

def align_boundary_deep(messages: list, idx: int) -> int:
    """深度边界对齐 — 处理并发 tool_calls 场景

    问题: 一个 AIMessage 可能带 3-5 个并发 tool_calls，对应 3-5 个 ToolMessage。
    如果切割点落在这组 ToolMessage 中间，会破坏 tool_call/tool_result 的对应关系。

    解决: 确保 AIMessage + 其所有对应 ToolMessage 作为原子组，整组保护或整组压缩。

    Args:
        messages: 完整消息列表
        idx: 原始切割点

    Returns:
        调整后的切割点（向前移动到组的起始之前）
    """
    if idx <= 0 or idx >= len(messages):
        return idx

    # 检查 idx 位置是否是 ToolMessage
    if not isinstance(messages[idx], ToolMessage):
        # 不是 ToolMessage，检查 idx-1 是否属于某个并发组的中间
        if idx > 0 and isinstance(messages[idx - 1], ToolMessage):
            # 可能切在一组 ToolMessage 的末尾后面
            pass
        else:
            return idx

    # 从 idx 向前找连续的 ToolMessage 块
    check = idx
    while check > 0 and isinstance(messages[check - 1], ToolMessage):
        check -= 1

    # 如果 idx 本身是 ToolMessage，往前找
    if isinstance(messages[idx], ToolMessage):
        check = idx
        while check > 0 and isinstance(messages[check - 1], ToolMessage):
            check -= 1

    # check 现在指向第一个连续 ToolMessage 的位置
    # 它前面应该是对应的 AIMessage(tool_calls)
    parent_idx = check - 1
    if parent_idx < 0:
        return idx

    parent = messages[parent_idx]
    if not isinstance(parent, AIMessage) or not getattr(parent, "tool_calls", None):
        return idx

    # 找到了父 AIMessage → 统计它有多少个 tool_calls
    expected_results = len(parent.tool_calls)

    # 父 AIMessage 之后应该有 expected_results 个 ToolMessage
    group_start = parent_idx
    group_end = parent_idx + 1 + expected_results  # exclusive

    # 如果 idx 在这个组内部 → 回退到组的起始
    if group_start <= idx < group_end:
        logger.debug(
            "[AlignDeep] 切割点 %d 在工具组 [%d, %d) 内部 (%d 个并发调用)，回退到 %d",
            idx, group_start, group_end, expected_results, group_start,
        )
        return group_start

    return idx


# ═══════════════════════════════════════════════════════════
# §4.3 Skill 结果锚点 — 防止多次迭代压缩导致关键数据衰减
# ═══════════════════════════════════════════════════════════

class SkillResultAnchor:
    """Skill 执行结果的持久化锚点

    解决问题: 多轮 Skill 执行经过 3+ 次迭代压缩后，早期 Skill 的关键数据
    （金额、日期、搜索词）逐步衰减为模糊描述。

    策略: Skill 结束时，用正则提取结构化"锚点摘要"，存入 session 级缓存。
    后续压缩的摘要生成 prompt 中注入这些锚点，确保关键数据永不衰减。
    """

    def __init__(self, max_anchors: int = 10):
        self._anchors: dict[str, str] = {}  # execution_id → 锚点文本
        self._max_anchors = max_anchors

    @property
    def anchors(self) -> dict[str, str]:
        return dict(self._anchors)

    @property
    def anchor_count(self) -> int:
        return len(self._anchors)

    def on_skill_complete(
        self,
        skill_name: str,
        skill_result: str,
        tool_calls_history: list | None = None,
    ) -> str | None:
        """Skill 执行完成时，提取并存储锚点

        Args:
            skill_name: 技能名称
            skill_result: 技能执行最终结果文本
            tool_calls_history: Skill 内部的 tool_call 消息历史（可选）

        Returns:
            提取的锚点文本，如果未提取到则返回 None
        """
        anchor = self._extract_anchor(skill_name, skill_result, tool_calls_history or [])
        if anchor:
            execution_id = f"{skill_name}_{len(self._anchors)}"
            self._anchors[execution_id] = anchor

            # 限制锚点数量（FIFO 淘汰最早的）
            while len(self._anchors) > self._max_anchors:
                oldest_key = next(iter(self._anchors))
                del self._anchors[oldest_key]

            logger.info("[SkillAnchor] 提取锚点: %s → %s", execution_id, anchor[:80])
            return anchor
        return None

    def _extract_anchor(
        self, skill_name: str, result: str, history: list
    ) -> str:
        """从 Skill 执行结果中提取不可丢失的关键数据（零 LLM 成本）

        提取规则:
          - 金额数字（$xxx, ¥xxx, xxxK, xxx万）
          - 日期（yyyy-mm-dd, xx月xx日）
          - 百分比（xx%）
          - 从 tool_calls 历史中提取查询的实体和搜索词
        """
        parts = [f"[{skill_name}]"]

        # 金额
        amounts = re.findall(
            r'[\$¥￥]\s*[\d,.]+[KMB万亿]?|\d[\d,.]*\s*(?:万|亿|USD|CNY|IDR|元)',
            result,
        )
        if amounts:
            unique_amounts = list(dict.fromkeys(amounts[:10]))  # 去重保序
            parts.append(f"金额: {', '.join(unique_amounts)}")

        # 日期
        dates = re.findall(
            r'\d{4}[-/]\d{1,2}[-/]\d{1,2}|\d{1,2}月\d{1,2}日',
            result,
        )
        if dates:
            unique_dates = list(dict.fromkeys(dates[:5]))
            parts.append(f"日期: {', '.join(unique_dates)}")

        # 百分比
        percentages = re.findall(r'\d+\.?\d*\s*%', result)
        if percentages:
            unique_pct = list(dict.fromkeys(percentages[:5]))
            parts.append(f"比例: {', '.join(unique_pct)}")

        # 从 tool_calls 历史中提取查询参数
        entities_queried: set[str] = set()
        search_queries: list[str] = []

        for msg in history:
            if isinstance(msg, AIMessage) and getattr(msg, "tool_calls", None):
                for tc in msg.tool_calls:
                    args = tc.get("args", {})
                    tc_name = tc.get("name", "")
                    if tc_name == "query_data":
                        entity = args.get("entity", "")
                        if entity:
                            entities_queried.add(entity)
                    elif tc_name == "web_search":
                        query = args.get("query", "")
                        if query:
                            search_queries.append(query)

        if entities_queried:
            parts.append(f"查询实体: {', '.join(sorted(entities_queried))}")
        if search_queries:
            parts.append(f"搜索: {'; '.join(search_queries[:5])}")

        # 只有提取到实际数据才返回锚点
        if len(parts) > 1:
            return " | ".join(parts)
        return ""

    def inject_into_summary_prompt(self, prompt: str) -> str:
        """在摘要生成/迭代更新时注入锚点，防止关键数据在压缩中丢失

        Args:
            prompt: 原始摘要生成 prompt

        Returns:
            注入锚点后的 prompt
        """
        if not self._anchors:
            return prompt

        anchor_section = "\n".join(f"  - {v}" for v in self._anchors.values())
        injection = (
            "\n\n## 不可丢失的 Skill 执行锚点（必须在摘要中保留）\n"
            f"{anchor_section}\n"
            "上述锚点中的精确数字、日期、搜索词必须原样保留在摘要中。\n"
        )
        return prompt + injection

    def get_anchor_summary(self) -> str:
        """获取所有锚点的合并文本（用于注入压缩后的摘要消息中）"""
        if not self._anchors:
            return ""
        lines = ["[Skill执行锚点-关键数据]"]
        for anchor in self._anchors.values():
            lines.append(f"  {anchor}")
        return "\n".join(lines)

    def clear(self) -> None:
        """清空所有锚点（会话结束时调用）"""
        self._anchors.clear()


# ═══════════════════════════════════════════════════════════
# §4.4 Post-Skill Compact — Skill 结束后即时内部压缩
# ═══════════════════════════════════════════════════════════

def post_skill_compact(
    messages: list,
    skill_start_idx: int,
    skill_end_idx: int,
    min_skill_messages: int = 8,
) -> list:
    """Skill 执行完成后的即时内部压缩

    时机: skills_tool 返回最终结果后、主 Agent 继续之前
    目标: 将 Skill 内部 20-30 条消息精简为 ~8 条

    保留:
      - Skill 启动: AIMessage(tool_calls=[skills_tool]) — 第1条
      - Skill 启动确认: ToolMessage (skill 启动) — 第2条（如果有）
      - 最后 N 轮内部工具调用（最近的推理上下文）
      - Skill 最终结果: ToolMessage(name="skills_tool") — 最后1条

    压缩:
      - 中间工具调用 → CRM 信息一行摘要（零 LLM 成本）
      - 去掉冗长的中间 AIMessage 规划文本

    Args:
        messages: 完整消息列表
        skill_start_idx: Skill 启动的 AIMessage index
        skill_end_idx: Skill 最终结果的 ToolMessage index（inclusive）
        min_skill_messages: Skill 内部消息数低于此值时不压缩

    Returns:
        压缩后的完整消息列表（原地替换 Skill 内部部分）
    """
    if skill_end_idx <= skill_start_idx:
        return messages

    skill_messages = messages[skill_start_idx:skill_end_idx + 1]
    n = len(skill_messages)

    if n <= min_skill_messages:
        # Skill 够短，不处理
        return messages

    # 保护头部（启动调用 + 可能的启动确认）和尾部（最终结果 + 最后2轮内部调用）
    protect_head = 2  # skills_tool 调用 AIMessage + 第一个 ToolMessage
    protect_tail = 5  # 最后2轮内部调用（2 AIMessage + 对应 ToolMessage）+ 最终结果

    # 确保头尾不重叠
    if protect_head + protect_tail >= n:
        return messages

    # 中间区域做信息摘要替换
    compacted_middle: list = []
    middle_start = protect_head
    middle_end = n - protect_tail

    for i in range(middle_start, middle_end):
        msg = skill_messages[i]

        if isinstance(msg, ToolMessage):
            content = msg.content if isinstance(msg.content, str) else str(msg.content)
            if len(content) > 150:
                # 压缩为一行摘要
                tool_name = getattr(msg, "name", "") or ""
                summary = _skill_internal_one_liner(tool_name, content)
                compacted_middle.append(ToolMessage(
                    content=summary,
                    tool_call_id=getattr(msg, "tool_call_id", ""),
                    name=tool_name,
                ))
                continue

        elif isinstance(msg, AIMessage):
            content = msg.content if isinstance(msg.content, str) else ""
            tool_calls = getattr(msg, "tool_calls", None)

            if tool_calls:
                # 保留 tool_calls 结构但截断规划文本
                short_content = content[:80] + "..." if len(content) > 80 else content
                compacted_middle.append(AIMessage(
                    content=short_content,
                    tool_calls=tool_calls,
                ))
                continue
            elif len(content) > 200:
                # 纯文本规划 → 截断
                compacted_middle.append(AIMessage(
                    content=content[:100] + f"...[已压缩，原{len(content)}字]"
                ))
                continue

        # 其他情况保留原样
        compacted_middle.append(msg)

    # 组装结果
    result = (
        messages[:skill_start_idx]
        + skill_messages[:protect_head]
        + compacted_middle
        + skill_messages[n - protect_tail:]
        + messages[skill_end_idx + 1:]
    )

    original_tokens = sum(len(getattr(m, "content", "") or "") for m in skill_messages) // 2
    new_skill_msgs = (
        skill_messages[:protect_head]
        + compacted_middle
        + skill_messages[n - protect_tail:]
    )
    new_tokens = sum(len(getattr(m, "content", "") or "") for m in new_skill_msgs) // 2

    logger.info(
        "[PostSkillCompact] Skill 内部 %d→%d 条, ~%d→%d tokens (节省%.0f%%)",
        n, len(new_skill_msgs), original_tokens, new_tokens,
        (1 - new_tokens / max(original_tokens, 1)) * 100,
    )

    return result


def find_completed_skill_boundaries(messages: list) -> list[tuple[int, int]]:
    """扫描消息列表，找出所有已完成的 Skill 执行边界

    Returns:
        [(start_idx, end_idx), ...] — 每个 Skill 的起止 index
    """
    boundaries: list[tuple[int, int]] = []
    i = 0
    while i < len(messages):
        msg = messages[i]
        if isinstance(msg, AIMessage) and getattr(msg, "tool_calls", None):
            for tc in msg.tool_calls:
                if tc.get("name") == "skills_tool":
                    # 找到 Skill 启动，向后找结束
                    skill_start = i
                    skill_end = None
                    for j in range(i + 1, len(messages)):
                        if isinstance(messages[j], ToolMessage):
                            tm_name = getattr(messages[j], "name", "") or ""
                            if tm_name == "skills_tool":
                                skill_end = j
                                break
                    if skill_end is not None:
                        boundaries.append((skill_start, skill_end))
                        i = skill_end  # 跳到 Skill 结束位置继续扫描
                    break
        i += 1
    return boundaries


# ═══════════════════════════════════════════════════════════
# 辅助函数
# ═══════════════════════════════════════════════════════════

def _skill_internal_one_liner(tool_name: str, content: str) -> str:
    """Skill 内部工具调用的一行摘要（用于 post_skill_compact）"""
    import json as _json

    # JSON 结构化数据 → 提取关键字段
    stripped = content.strip()
    if stripped.startswith("{") or stripped.startswith("["):
        try:
            data = _json.loads(stripped)
            if isinstance(data, dict):
                # 单条记录
                key_fields = ["name", "id", "amount", "stage", "status", "title", "type"]
                parts = [f"{k}={data[k]}" for k in key_fields if k in data and data[k]]
                if parts:
                    return f"[{tool_name}] {', '.join(str(p) for p in parts[:6])}"
                # records 列表
                if "records" in data and isinstance(data["records"], list):
                    count = len(data["records"])
                    return f"[{tool_name}] 返回{count}条记录"
            elif isinstance(data, list):
                return f"[{tool_name}] 返回{len(data)}条数据"
        except _json.JSONDecodeError:
            pass

    # 非 JSON → 取前 80 字符
    preview = content[:80].replace("\n", " ").strip()
    return f"[{tool_name}] {preview}... ({len(content)}字符)"
