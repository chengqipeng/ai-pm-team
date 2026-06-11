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
            # 切割点在 Skill 内部 → 判断该 Skill 是否正在执行中
            is_active = self._is_skill_active(messages, skill_boundary)
            protected_count = n - skill_boundary

            if is_active:
                # 正在执行的 Skill → 无条件保护（不受 max_tail 限制）
                # 理由: 正在执行中的 Skill 如果被部分压缩，LLM 会丢失
                # 已完成的工具调用结果，导致后续工具选择和参数提取失败
                logger.debug(
                    "[SkillTailProtect] 切割点 %d 在正在执行的 Skill 内部，"
                    "无条件保护到 %d (保护 %d 条，忽略 max_tail 限制)",
                    base_cut, skill_boundary, protected_count,
                )
                return skill_boundary

            # 已完成的 Skill → 受 max_tail 限制
            if protected_count <= self.max_tail:
                logger.debug(
                    "[SkillTailProtect] 切割点 %d 在已完成的 Skill 内部，推进到 %d (保护 %d 条)",
                    base_cut, skill_boundary, protected_count,
                )
                return skill_boundary
            else:
                # 已完成的 Skill 太大，超过 max_tail → 保留基础切割点
                # 这种情况实际很少发生：Post-Skill Compact 已将完成的 Skill 从 20-30 条压缩到 ~10 条
                logger.debug(
                    "[SkillTailProtect] 已完成的 Skill 过大 (%d 条 > max_tail %d)，保留基础切割",
                    protected_count, self.max_tail,
                )
                return base_cut

        return base_cut

    def _is_skill_active(self, messages: list, skill_start_idx: int) -> bool:
        """判断从 skill_start_idx 开始的 Skill 是否正在执行中（未找到终止标记）

        Args:
            messages: 完整消息列表
            skill_start_idx: Skill 启动的 AIMessage index

        Returns:
            True = 正在执行中（没有终止的 ToolMessage(name="skills_tool")）
            False = 已完成
        """
        for i in range(skill_start_idx + 1, len(messages)):
            msg = messages[i]
            if isinstance(msg, ToolMessage):
                tool_name = getattr(msg, "name", "") or ""
                if tool_name == "skills_tool":
                    return False  # 找到终止标记 → 已完成
        return True  # 未找到终止标记 → 正在执行中

    def _find_enclosing_skill_start(
        self, messages: list, cut_idx: int, head_end: int
    ) -> int | None:
        """查找 cut_idx 所处的 Skill 执行边界

        支持 Fork 和 Inline 两种模式:
          - Fork: ToolMessage 内容以 [SKILL_DONE: 开头 → 精确终止
          - Inline: ToolMessage 是 prompt 返回 → 段延伸到下一个 skills_tool / HumanMessage

        如果 cut_idx 在 Skill 执行范围内 → 返回起始位置
        如果 cut_idx 不在 Skill 内部 → 返回 None
        """
        # 从 cut_idx 向前找最近的 skills_tool 启动
        skill_start = None

        for i in range(cut_idx - 1, max(head_end - 1, -1), -1):
            msg = messages[i]

            # 检查是否是 skills_tool 的 ToolMessage
            if isinstance(msg, ToolMessage):
                tool_name = getattr(msg, "name", "") or ""
                if tool_name == "skills_tool":
                    content = getattr(msg, "content", "") or ""
                    if content.strip().startswith("[SKILL_DONE:"):
                        # Fork 模式的终止标记 → cut_idx 在此 Skill 之后
                        return None
                    # Inline 模式的 prompt 返回 → 继续向前找 skills_tool 调用
                    # （这条 ToolMessage 是 Skill 内部的，不是终止）

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

        # 找到 skill_start 后，确定 Skill 的终止位置
        tm_idx = None
        for i in range(skill_start + 1, len(messages)):
            if isinstance(messages[i], ToolMessage):
                tm_name = getattr(messages[i], "name", "") or ""
                if tm_name == "skills_tool":
                    tm_idx = i
                    break

        if tm_idx is None:
            # 没有 ToolMessage 返回 → Skill 正在启动中 → 保护
            return skill_start

        # 区分 Fork / Inline
        content = getattr(messages[tm_idx], "content", "") or ""
        if content.strip().startswith("[SKILL_DONE:"):
            # Fork 模式: 段 = [skill_start, tm_idx]
            if skill_start <= cut_idx <= tm_idx:
                return skill_start
            return None  # cut_idx 在 fork 段之外

        # Inline 模式: 段延伸到下一个 skills_tool 调用或 HumanMessage
        inline_end = self._compute_inline_end(messages, tm_idx, skill_start)

        if skill_start <= cut_idx <= inline_end:
            return skill_start

        return None

    def _compute_inline_end(self, messages: list, prompt_return_idx: int, skill_start: int) -> int:
        """计算 inline Skill 段的终止位置（用于 §4.1 保护区判断）

        终止条件（与 find_completed_skill_boundaries 一致）:
          - 下一个 skills_tool 调用的前一条
          - 或下一个 HumanMessage 的前一条
          - 或消息末尾
        """
        segment_end = len(messages) - 1

        # 找下一个 skills_tool 调用
        for i in range(prompt_return_idx + 1, len(messages)):
            if isinstance(messages[i], AIMessage) and getattr(messages[i], "tool_calls", None):
                if any(tc.get("name") == "skills_tool" for tc in messages[i].tool_calls):
                    segment_end = min(segment_end, i - 1)
                    break

        # 找下一个 HumanMessage
        for i in range(prompt_return_idx + 1, segment_end + 1):
            if isinstance(messages[i], HumanMessage):
                segment_end = min(segment_end, i - 1)
                break

        return max(segment_end, prompt_return_idx)


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
    """找出已完成的、可压缩的 Skill 执行段

    三层识别策略（按可靠性递减）:
      1. Fork Skill: ToolMessage 内容以 [SKILL_DONE: 开头 → 精确段 = [调用, 返回]
      2. Inline Skill（有完成标记）: AIMessage 内容含 [INLINE_SKILL_DONE:xxx]
         → 精确段 = [skills_tool 调用, 含标记的 AIMessage]
      3. Inline Skill（无完成标记，兼容旧 Skill）: 以"轮次"为粒度
         → 段 = 该轮次内从 skills_tool 调用到 HumanMessage 之前

    设计决策:
      - 层 1 和层 2 是精确识别（依赖可靠标记），覆盖 95%+ 场景
      - 层 3 是兜底（旧 Skill 未注入完成标记指令时），以轮次为粒度处理
      - 正在执行的 Skill（无完成标记且在当前轮次末尾）不加入 boundaries

    Returns:
        [(start_idx, end_idx), ...] — 每个可压缩段的起止 index (inclusive)
    """
    boundaries: list[tuple[int, int]] = []
    covered_indices: set[int] = set()  # 已被识别的消息 index，避免重复

    # ═══ 层 1: Fork Skill 精确识别 ═══
    for i, msg in enumerate(messages):
        if not (isinstance(msg, AIMessage) and getattr(msg, "tool_calls", None)):
            continue
        if not any(tc.get("name") == "skills_tool" for tc in msg.tool_calls):
            continue
        # 找对应的 ToolMessage(name="skills_tool")
        for j in range(i + 1, len(messages)):
            if isinstance(messages[j], ToolMessage):
                tm_name = getattr(messages[j], "name", "") or ""
                if tm_name == "skills_tool":
                    content = getattr(messages[j], "content", "") or ""
                    if content.strip().startswith("[SKILL_DONE:"):
                        boundaries.append((i, j))
                        covered_indices.add(i)
                        covered_indices.add(j)
                    break

    # ═══ 层 2: Inline Skill 精确识别（有 [INLINE_SKILL_DONE:] 完成标记）═══
    for i, msg in enumerate(messages):
        if i in covered_indices:
            continue
        if not (isinstance(msg, AIMessage) and getattr(msg, "tool_calls", None)):
            continue
        if not any(tc.get("name") == "skills_tool" for tc in msg.tool_calls):
            continue

        # 找对应的 ToolMessage（prompt 返回，不是 [SKILL_DONE:]）
        tm_idx = None
        for j in range(i + 1, len(messages)):
            if isinstance(messages[j], ToolMessage):
                tm_name = getattr(messages[j], "name", "") or ""
                if tm_name == "skills_tool":
                    content = getattr(messages[j], "content", "") or ""
                    if not content.strip().startswith("[SKILL_DONE:"):
                        tm_idx = j  # 这是 inline prompt 返回
                    break

        if tm_idx is None:
            continue  # 没有 prompt 返回，跳过

        # 向后搜索 [INLINE_SKILL_DONE:xxx] 标记
        skill_end = None
        for j in range(tm_idx + 1, len(messages)):
            if isinstance(messages[j], HumanMessage):
                break  # 到了下一个轮次，标记不存在
            if isinstance(messages[j], AIMessage):
                content = getattr(messages[j], "content", "") or ""
                if "[INLINE_SKILL_DONE:" in content:
                    skill_end = j
                    break

        if skill_end is not None:
            # 精确识别成功
            if skill_end > i + 1:
                boundaries.append((i, skill_end))
                for k in range(i, skill_end + 1):
                    covered_indices.add(k)

    # ═══ 层 3: 兜底 — 无完成标记的 Inline Skill，以"轮次"为粒度 ═══
    # 找到包含未覆盖的 inline skills_tool 调用的轮次
    human_indices = [idx for idx, m in enumerate(messages) if isinstance(m, HumanMessage)]
    turn_starts = [0] + [idx + 1 for idx in human_indices]
    turn_ends = [idx - 1 for idx in human_indices] + [len(messages) - 1]

    for t_idx in range(len(turn_starts)):
        t_start = turn_starts[t_idx]
        t_end = turn_ends[t_idx]
        if t_start > t_end:
            continue

        # 检查该轮次是否有未覆盖的 inline skills_tool
        has_uncovered_inline = False
        first_skill_idx = None
        for k in range(t_start, t_end + 1):
            if k in covered_indices:
                continue
            msg = messages[k]
            if isinstance(msg, AIMessage) and getattr(msg, "tool_calls", None):
                if any(tc.get("name") == "skills_tool" for tc in msg.tool_calls):
                    # 确认是 inline（对应 TM 不含 [SKILL_DONE:]）
                    for j in range(k + 1, min(k + 5, len(messages))):
                        if isinstance(messages[j], ToolMessage):
                            tm_name = getattr(messages[j], "name", "") or ""
                            if tm_name == "skills_tool":
                                content = getattr(messages[j], "content", "") or ""
                                if not content.strip().startswith("[SKILL_DONE:"):
                                    has_uncovered_inline = True
                                    if first_skill_idx is None:
                                        first_skill_idx = k
                                break
            if has_uncovered_inline and first_skill_idx is not None:
                break

        if not has_uncovered_inline or first_skill_idx is None:
            continue

        # 轮次段: 从第一个 skills_tool 到轮次结束
        segment_start = first_skill_idx
        segment_end = t_end

        # 检查是否正在执行（最后一个轮次 + 末尾是 ToolMessage/AI(tool_calls)）
        if t_idx == len(turn_starts) - 1:
            last_msg = messages[segment_end]
            if isinstance(last_msg, ToolMessage):
                continue
            if isinstance(last_msg, AIMessage) and getattr(last_msg, "tool_calls", None):
                continue

        # 只有段足够长才处理
        if segment_end - segment_start + 1 > 2:
            # 排除已覆盖的范围
            overlap = any(
                s <= segment_start <= e or s <= segment_end <= e
                for s, e in boundaries
            )
            if not overlap:
                boundaries.append((segment_start, segment_end))

    # 按 start_idx 排序
    boundaries.sort(key=lambda x: x[0])
    return boundaries


# ═══════════════════════════════════════════════════════════
# 辅助函数
# ═══════════════════════════════════════════════════════════

def _detect_inline_mode(messages: list, prompt_return_idx: int) -> bool:
    """判断 skills_tool 的 ToolMessage 返回的是 inline prompt 还是 fork 最终结果

    启发式规则:
      1. 如果 prompt_return_idx 之后紧接着是 AIMessage(tool_calls) 且不含 skills_tool
         → inline 模式（LLM 在按 Skill prompt 中的 SOP 继续执行工具）
      2. 如果返回内容看起来像 SOP 指令（包含步骤编号、"请"/"按照"等指令词）
         → inline 模式
      3. 其他情况 → fork 模式（返回的是最终结果）
    """
    # 检查 prompt 返回内容是否像 SOP 指令
    content = getattr(messages[prompt_return_idx], "content", "") or ""
    if isinstance(content, str):
        # Inline prompt 通常包含步骤指引、工具使用说明
        inline_indicators = [
            "步骤", "Step ", "请按照", "请执行", "请使用",
            "1.", "1、", "第一步", "## 任务",
            "工具:", "调用", "SOP",
        ]
        indicator_count = sum(1 for ind in inline_indicators if ind in content)
        if indicator_count >= 2:
            return True

    # 检查 prompt_return_idx 之后是否紧跟 LLM 的工具调用（非 skills_tool）
    next_idx = prompt_return_idx + 1
    if next_idx < len(messages):
        next_msg = messages[next_idx]
        if isinstance(next_msg, AIMessage) and getattr(next_msg, "tool_calls", None):
            # 紧跟的工具调用中不含 skills_tool → LLM 在按 SOP 执行
            tc_names = [tc.get("name", "") for tc in next_msg.tool_calls]
            if "skills_tool" not in tc_names:
                return True

    return False


def _find_inline_skill_end(messages: list, prompt_return_idx: int) -> int | None:
    """找到 inline 模式 Skill 执行的终止位置

    核心难题: Inline 模式没有明确终止标记。Skill 按 SOP 执行工具后，主 Agent
    可能继续调用其他工具完成后续任务。两者在消息结构上完全一样。

    设计原则: "宁多不少" — 边界偏大（多保护几条）的损害远小于边界偏小（Skill
    内部被压缩导致 LLM 丢失上下文）。

    终止判断策略（综合多个信号）:
      1. 强终止: 下一个 HumanMessage → 用户发了新消息，Skill 肯定已结束
      2. 强终止: 下一个 skills_tool 调用 → 新 Skill 开始，旧 Skill 结束
      3. 弱终止: AIMessage 无 tool_calls 后面紧跟 HumanMessage → 对话轮次结束
      4. 模糊情况（Skill 完成后主 Agent 继续调工具）: 不在此处做精确切分，
         整体视为"Skill 执行段"。原因：
         - Post-Skill Compact 对这段做压缩时，保留了头尾（protect_head=2, protect_tail=5）
         - 即使多压缩了几条"后续"工具调用，损失的只是中间步骤的详细内容
         - 如果错误地在中间切断，Skill 内部工具调用会被 MicroCompact 压缩 → 更大损害
      5. 消息列表结束 + 最后消息有工具调用 → Skill 可能正在执行（返回 None）

    Returns:
        终止位置 index（inclusive），或 None（Skill 正在执行中/不确定）
    """
    last_meaningful_idx = prompt_return_idx  # 至少包含 prompt 返回

    for i in range(prompt_return_idx + 1, len(messages)):
        msg = messages[i]

        # 强终止条件 1: 下一个 HumanMessage — 用户开始新轮次
        if isinstance(msg, HumanMessage):
            # Skill 在 HumanMessage 之前的最后一条消息处结束
            return max(i - 1, prompt_return_idx)

        # 强终止条件 2: 下一个 skills_tool 调用 — 新 Skill 开始
        if isinstance(msg, AIMessage) and getattr(msg, "tool_calls", None):
            for tc in msg.tool_calls:
                if tc.get("name") == "skills_tool":
                    # 新 Skill 开始，当前 Skill 在上一条消息结束
                    return max(i - 1, prompt_return_idx)

        # 跟踪最后一条有实质内容的消息
        if isinstance(msg, ToolMessage):
            last_meaningful_idx = i
        elif isinstance(msg, AIMessage):
            last_meaningful_idx = i

    # 到了消息列表末尾
    last_msg = messages[-1] if messages else None

    # 如果最后一条是 ToolMessage 或 AIMessage(tool_calls) → 可能还在执行
    if isinstance(last_msg, ToolMessage):
        return None  # 正在执行中 — 不做 boundary 识别，让 §4.1 保护它
    if isinstance(last_msg, AIMessage) and getattr(last_msg, "tool_calls", None):
        return None  # 正在执行中

    # 最后是 AIMessage 无 tool_calls（最终回复） → Skill+后续 整段结束
    if last_meaningful_idx > prompt_return_idx:
        return last_meaningful_idx

    return None


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
