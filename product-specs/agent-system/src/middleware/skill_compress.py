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
import os
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
      1. Token 预算是第一优先级 — 基于实际 token 占比决定保护区大小
      2. 如果 token 预算的切割点落在 Skill 执行中间，将切割点推进到 Skill 起始位置
      3. min_tail 硬底线仍为原值
      4. max_tail 上限 30 条，防止巨型 Skill 过度保护尾部
    """

    def __init__(self, min_tail_messages: int = 5, max_tail_messages: int = 30):
        self.min_tail = min_tail_messages
        self.max_tail = max_tail_messages

    def compute_tail_start(self, messages: list, keep_recent: int, head_end: int = 0,
                           token_budget: int = 0) -> int:
        """计算 Skill 边界感知的尾部保护起始位置

        Args:
            messages: 完整消息列表
            keep_recent: 基础保护条数（来自各 Pass 的 keep_recent 参数）
            head_end: 头部保护区结束位置（system prompt 等）
            token_budget: Token 预算（>0 时启用预算优先模式，对齐 Hermes _find_tail_cut_by_tokens）
                          预算含义: 尾部保护区最多占用的 token 数

        Returns:
            尾部保护的起始 index — messages[返回值:] 都应被保护
        """
        n = len(messages)
        if n <= keep_recent:
            return 0

        # ── Token 预算优先：按实际内容量决定保护区大小 ──
        if token_budget > 0:
            budget_cut = self._find_cut_by_token_budget(messages, head_end, token_budget)
            # 取 token 预算和固定条数中更大的保护范围（更小的 index）
            base_cut = min(budget_cut, n - keep_recent)
        else:
            # 无预算时退化为固定条数
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

    def _find_cut_by_token_budget(self, messages: list, head_end: int, token_budget: int) -> int:
        """从消息列表末尾向前累积 token，直到超出预算，返回尾部保护区起始 index

        对齐 Hermes Agent _find_tail_cut_by_tokens 算法：
        - 中英混合场景使用 2 字符/token（偏保守，宁多保护不漏保护）
        - soft_ceiling = 1.5 × budget（允许包含一条大消息而不截断）
        - 硬底线 min_tail = 3 条（极端情况仍保持最低可用性）
        - tool_call 参数也计入 token 预算

        Args:
            messages: 完整消息列表
            head_end: 头部保护区结束位置
            token_budget: 尾部保护区的 token 预算

        Returns:
            尾部保护区起始 index — messages[返回值:] 应被保护
        """
        n = len(messages)
        min_tail = min(3, n - head_end - 1) if n - head_end > 1 else 0
        soft_ceiling = int(token_budget * 1.5)
        accumulated = 0
        cut_idx = n

        for i in range(n - 1, head_end - 1, -1):
            msg = messages[i]
            content = getattr(msg, "content", "") or ""

            # Token 估算：中英混合 2 字符/token（与 _estimate_tokens 一致）
            if isinstance(content, str):
                msg_tokens = len(content) // 2 + 10  # +10 角色/元数据开销
            elif isinstance(content, list):
                msg_tokens = sum(
                    len(b.get("text", "")) // 2 if isinstance(b, dict) else len(str(b)) // 2
                    for b in content
                ) + 10
            else:
                msg_tokens = 10

            # tool_calls 参数也计入预算
            tool_calls = getattr(msg, "tool_calls", None)
            if tool_calls:
                for tc in tool_calls:
                    args = tc.get("args", {})
                    msg_tokens += len(str(args)) // 4  # 参数通常是 JSON/英文，用 4 字符/token

            # 超过 soft_ceiling 且已满足 min_tail → 停止累积
            if accumulated + msg_tokens > soft_ceiling and (n - i) >= min_tail:
                break
            accumulated += msg_tokens
            cut_idx = i

        # 确保至少 min_tail 条
        fallback_cut = n - min_tail
        cut_idx = min(cut_idx, fallback_cut)

        # 如果预算能覆盖全部消息（小对话），强制切到 head 后面让压缩有可操作空间
        if cut_idx <= head_end:
            cut_idx = max(fallback_cut, head_end + 1)

        return cut_idx

    def _is_skill_active(self, messages: list, skill_start_idx: int) -> bool:
        """判断从 skill_start_idx 开始的 Skill 是否正在执行中（未找到终止标记）

        终止标记判断:
          - Fork: ToolMessage(name="skills_tool") 内容以 [SKILL_DONE: 开头
          - Inline: AIMessage 内容含 [INLINE_SKILL_DONE:

        放弃判断（interrupt 被用户跳过）:
          - Skill 段内有 ask_user 调用（AIMessage.tool_calls 含 ask_user）
          - 该 ask_user 调用后没有对应的 ToolMessage（按 tool_call_id 精确匹配）
          - 但后续出现了 HumanMessage（用户发了新消息，跳过了确认）
          → 视为已放弃，返回 False

        并行 tool_calls 处理:
          - 用 tool_call_id 集合跟踪所有未响应的 ask_user 调用
          - ToolMessage 通过 tool_call_id 精确消除对应的 pending 记录
          - 避免并行场景下其他工具的 ToolMessage 误清除 ask_user 状态

        注意: inline 模式的 prompt 返回也是 ToolMessage(name="skills_tool")，
        但内容不以 [SKILL_DONE: 开头 → 不视为终止。

        Args:
            messages: 完整消息列表
            skill_start_idx: Skill 启动的 AIMessage index

        Returns:
            True = 正在执行中（没有终止标记）
            False = 已完成或已放弃
        """
        # 跟踪所有未响应的 ask_user 调用的 tool_call_id
        pending_ask_user_ids: set[str] = set()

        for i in range(skill_start_idx + 1, len(messages)):
            msg = messages[i]
            if isinstance(msg, ToolMessage):
                tool_name = getattr(msg, "name", "") or ""
                if tool_name == "skills_tool":
                    content = getattr(msg, "content", "") or ""
                    if content.strip().startswith("[SKILL_DONE:"):
                        return False
                # 通过 tool_call_id 精确消除对应的 pending ask_user
                tc_id = getattr(msg, "tool_call_id", "") or ""
                if tc_id and tc_id in pending_ask_user_ids:
                    pending_ask_user_ids.discard(tc_id)

            elif isinstance(msg, AIMessage):
                content = getattr(msg, "content", "") or ""
                if "[INLINE_SKILL_DONE:" in content:
                    return False
                # 收集所有 ask_user 调用的 tool_call_id
                tool_calls = getattr(msg, "tool_calls", None)
                if tool_calls:
                    for tc in tool_calls:
                        if tc.get("name") == "ask_user":
                            tc_id = tc.get("id", "")
                            if tc_id:
                                pending_ask_user_ids.add(tc_id)

            elif isinstance(msg, HumanMessage):
                # 出现 HumanMessage 且有未响应的 ask_user → Skill 被放弃
                if pending_ask_user_ids:
                    logger.debug(
                        "[SkillTailProtect] Skill(start=%d) 有 %d 个 ask_user 未响应"
                        "(ids=%s)，用户发送新消息(idx=%d)，视为已放弃",
                        skill_start_idx, len(pending_ask_user_ids),
                        pending_ask_user_ids, i,
                    )
                    return False

        return True  # 未找到任何终止标记 → 正在执行中

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
    max_skill_tokens: int = 4000,
    user_query: str = "",
) -> list:
    """Skill 执行完成后的即时内部压缩

    时机: skills_tool 返回最终结果后、主 Agent 继续之前
    目标: 将 Skill 内部 20-30 条消息精简为 ~8 条

    触发条件（任一满足即触发）:
      1. Skill 内部消息数 > min_skill_messages（默认 8）
      2. Skill 内部估算 token 总量 > max_skill_tokens（默认 4000）
         — 覆盖"少轮次但单条结果巨大"的场景

    压缩策略（按优先级）:
      1. LLMLingua-2 段级语义压缩（纯文本部分，LLMLINGUA_ENABLED=1 时启用）
      2. CRM 规则摘要（结构化 JSON 数据 + LLMLingua-2 降级兜底）

    保留:
      - Skill 启动: AIMessage(tool_calls=[skills_tool]) — 第1条
      - Skill 启动确认: ToolMessage (skill 启动) — 第2条（如果有）
      - 最后 N 轮内部工具调用（最近的推理上下文）
      - Skill 最终结果: ToolMessage(name="skills_tool") — 最后1条

    Args:
        messages: 完整消息列表
        skill_start_idx: Skill 启动的 AIMessage index
        skill_end_idx: Skill 最终结果的 ToolMessage index（inclusive）
        min_skill_messages: Skill 内部消息数低于此值时按条数不触发
        max_skill_tokens: Skill 内部 token 总量超过此值时强制触发（覆盖少轮大内容场景）
        user_query: 用户当前问题（用于 LLMLingua-2 密度检测和上下文信号）

    Returns:
        压缩后的完整消息列表（原地替换 Skill 内部部分）
    """
    if skill_end_idx <= skill_start_idx:
        return messages

    skill_messages = messages[skill_start_idx:skill_end_idx + 1]
    n = len(skill_messages)

    # 估算 Skill 内部 token 总量（2 字符/token，偏保守）
    skill_tokens = sum(
        len(getattr(m, "content", "") or "") // 2
        for m in skill_messages
    )

    # 双条件触发：条数不够 AND token 也不超 → 不压缩
    if n <= min_skill_messages and skill_tokens <= max_skill_tokens:
        return messages

    # 保护头部（启动调用 + 可能的启动确认）和尾部（最终结果 + 最后2轮内部调用）
    protect_head = 2  # skills_tool 调用 AIMessage + 第一个 ToolMessage
    protect_tail = 5  # 最后2轮内部调用（2 AIMessage + 对应 ToolMessage）+ 最终结果

    # 确保头尾不重叠
    if protect_head + protect_tail >= n:
        # 消息数不足以做"删除中间条目"模式
        # 但如果是 token 触发，改用"就地压缩大内容"模式
        if skill_tokens > max_skill_tokens:
            return _inplace_compress_skill(messages, skill_start_idx, skill_end_idx)
        return messages

    middle_start = protect_head
    middle_end = n - protect_tail

    # ═══ 优先尝试 LLMLingua-2 段级压缩 ═══
    compacted_middle = _llmlingua_skill_compress(
        skill_messages, middle_start, middle_end,
        user_query=user_query,
        target_max_chars=2000,
    )

    # LLMLingua-2 不可用或效果不佳 → 降级到原有逐条压缩
    if compacted_middle is None:
        compacted_middle = _per_message_compact(skill_messages, middle_start, middle_end)

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


def _per_message_compact(skill_messages: list, middle_start: int, middle_end: int) -> list:
    """逐条压缩中间消息 — 原有 CRM 规则逻辑（作为 LLMLingua-2 的降级路径）"""
    compacted_middle: list = []

    for i in range(middle_start, middle_end):
        msg = skill_messages[i]

        if isinstance(msg, ToolMessage):
            content = msg.content if isinstance(msg.content, str) else str(msg.content)
            if len(content) > 150:
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
                short_content = content[:80] + "..." if len(content) > 80 else content
                compacted_middle.append(AIMessage(
                    content=short_content,
                    tool_calls=tool_calls,
                ))
                continue
            elif len(content) > 200:
                compacted_middle.append(AIMessage(
                    content=content[:100] + f"...[已压缩，原{len(content)}字]"
                ))
                continue

        compacted_middle.append(msg)

    return compacted_middle


# ═══════════════════════════════════════════════════════════
# LLMLingua-2 段级 Skill 压缩
# ═══════════════════════════════════════════════════════════


def _llmlingua_skill_compress(
    skill_messages: list,
    middle_start: int,
    middle_end: int,
    user_query: str = "",
    target_max_chars: int = 2000,
) -> list | None:
    """使用 LLMLingua-2 对 Skill 中间消息做语义压缩

    与逐条 _skill_internal_one_liner 的区别：
      1. 非结构化文本拼接后整体压缩（跨条上下文感知）
      2. token-level 保留预测（非暴力截断）
      3. 压缩 rate 由目标字符数倒推（自适应）

    降级条件（返回 None）：
      - LLMLingua-2 未启用 / 初始化失败
      - 中间段纯文本内容 < 500 字（太短不值得调用模型）
      - 压缩后 ratio ≥ 0.9（压缩效果不显著）

    Args:
        skill_messages: Skill 段的完整消息列表
        middle_start: 中间区域起始 index (相对于 skill_messages)
        middle_end: 中间区域结束 index (exclusive)
        user_query: 用户当前问题（用于密度检测和上下文信号）
        target_max_chars: 中间区域压缩后的目标最大字符数

    Returns:
        压缩后的中间消息列表，或 None（降级到逐条压缩）
    """
    if os.environ.get("LLMLINGUA_ENABLED", "0") != "1":
        return None

    try:
        from src.middleware.compression_engine import (
            CompressionEngine,
            CompressLevel,
            LLMLINGUA_DENSITY_PATTERNS,
            LLMLINGUA_DENSITY_THRESHOLDS,
            LLMLINGUA_FORCE_TOKENS,
            LLMLINGUA_CHUNK_END_TOKENS,
        )
    except ImportError:
        return None

    engine = CompressionEngine.get_instance()

    # ═══ Phase 1: 分流 — 区分结构化 vs 纯文本 ═══
    structured_indices: list[int] = []    # JSON 内容 → CRM 规则处理
    text_segments: list[tuple[int, str, str]] = []  # (index, role_tag, content)

    for i in range(middle_start, middle_end):
        msg = skill_messages[i]
        content = getattr(msg, "content", "") or ""
        if isinstance(content, list):
            content = str(content)

        if isinstance(msg, ToolMessage):
            stripped = content.strip()
            if stripped.startswith(("{", "[")) and len(content) > 150:
                # JSON 结构化 → 走 CRM 规则
                structured_indices.append(i)
            elif len(content) > 100:
                # 纯文本 ToolMessage → 加入 LLMLingua 批次
                tool_name = getattr(msg, "name", "") or "tool"
                text_segments.append((i, f"[{tool_name}]", content))

        elif isinstance(msg, AIMessage):
            tool_calls = getattr(msg, "tool_calls", None)
            if tool_calls:
                # 有 tool_calls → content 部分是规划文本
                if len(content) > 100:
                    text_segments.append((i, "[reasoning]", content))
            elif len(content) > 100:
                # 纯文本 AIMessage → 加入批次
                text_segments.append((i, "[plan]", content))

    # ═══ 前置检查：纯文本内容是否足够长 ═══
    total_text_chars = sum(len(seg[2]) for seg in text_segments)
    if total_text_chars < 500:
        return None  # 太短，LLMLingua-2 开销不值得

    # ═══ Phase 2: 拼接 + LLMLingua-2 批量压缩 ═══

    # 拼接为带分隔标记的文本块
    SEPARATOR = "\n§§§\n"
    combined_text = SEPARATOR.join(
        f"{tag} {content}" for _, tag, content in text_segments
    )

    # 计算目标 rate：根据结构化部分已占用的空间，倒推文本部分的预算
    structured_budget = len(structured_indices) * 150  # 每条结构化摘要约 150 字
    text_budget = max(500, target_max_chars - structured_budget)
    target_rate = min(0.7, max(0.25, text_budget / max(total_text_chars, 1)))

    # 获取 LLMLingua-2 压缩器
    compressor = engine._ensure_llmlingua()
    if compressor is None:
        return None

    try:
        # 密度检测 — 高密度文本保守压缩
        compiled_density = [re.compile(p) for p in LLMLINGUA_DENSITY_PATTERNS]
        entity_count = sum(len(p.findall(combined_text)) for p in compiled_density)
        density = entity_count / max(1, len(combined_text) / 100)

        if density > LLMLINGUA_DENSITY_THRESHOLDS["skip"]:
            return None  # 全是数据密集内容，不适合语义压缩

        # 密度越高 rate 越保守
        if density > LLMLINGUA_DENSITY_THRESHOLDS["high"]:
            target_rate = max(target_rate, 0.7)
        elif density > LLMLINGUA_DENSITY_THRESHOLDS["medium"]:
            target_rate = max(target_rate, 0.55)

        # 小数点保护预处理
        DECIMAL_PLACEHOLDER = "\u2299"
        protected_text, decimal_map = _protect_decimals(combined_text, DECIMAL_PLACEHOLDER)

        # 执行压缩 — 保护分隔符 token
        separator_token = "§§§"
        force_tokens = list(LLMLINGUA_FORCE_TOKENS) + [separator_token]

        result = compressor.compress_prompt(
            protected_text,
            rate=target_rate,
            force_tokens=force_tokens,
            chunk_end_tokens=list(LLMLINGUA_CHUNK_END_TOKENS),
            force_reserve_digit=True,
            drop_consecutive=True,
        )

        compressed = result.get("compressed_prompt", "")
        if not compressed or not compressed.strip():
            return None

        # 还原小数点
        for placeholder_str, original_str in decimal_map:
            compressed = compressed.replace(placeholder_str, original_str)

        # 后处理：清理多余空格
        compressed = re.sub(r'(?<=[。！？；])\s+(?=[\u4e00-\u9fff])', '', compressed)

        # 兜底回补丢失的关键数值
        compressed = engine._recover_missing_numbers(combined_text, compressed)

        ratio = len(compressed) / total_text_chars if total_text_chars > 0 else 1.0
        if ratio >= 0.9:
            return None  # 压缩效果不显著

    except Exception as e:
        logger.debug("[PostSkillCompact] LLMLingua-2 段级压缩异常: %s", e)
        return None

    # ═══ Phase 3: 拆分回消息结构 + 组装结果 ═══

    # 按分隔符拆回各段
    compressed_parts = compressed.split(separator_token)

    # 构建压缩后的消息列表
    compacted_middle: list = []
    text_seg_idx = 0

    for i in range(middle_start, middle_end):
        msg = skill_messages[i]

        if i in structured_indices:
            # 结构化数据走 CRM 规则（不变）
            content = getattr(msg, "content", "") or ""
            tool_name = getattr(msg, "name", "") or ""
            summary = _skill_internal_one_liner(tool_name, content)
            compacted_middle.append(ToolMessage(
                content=summary,
                tool_call_id=getattr(msg, "tool_call_id", ""),
                name=tool_name,
            ))

        elif any(seg[0] == i for seg in text_segments):
            # 纯文本 — 用 LLMLingua-2 压缩后的内容替换
            if text_seg_idx < len(compressed_parts):
                compressed_content = compressed_parts[text_seg_idx].strip()
                text_seg_idx += 1
            else:
                # 分隔符被 LLMLingua-2 部分删除时的兜底
                compressed_content = "[已压缩]"

            # 去掉 role_tag 前缀（[tool_name] / [reasoning] / [plan]）
            compressed_content = re.sub(r'^\[[\w_]+\]\s*', '', compressed_content)

            if not compressed_content:
                compressed_content = "[已压缩]"

            if isinstance(msg, ToolMessage):
                compacted_middle.append(ToolMessage(
                    content=compressed_content,
                    tool_call_id=getattr(msg, "tool_call_id", ""),
                    name=getattr(msg, "name", ""),
                ))
            elif isinstance(msg, AIMessage):
                tool_calls = getattr(msg, "tool_calls", None)
                if tool_calls:
                    compacted_middle.append(AIMessage(
                        content=compressed_content,
                        tool_calls=tool_calls,
                    ))
                else:
                    compacted_middle.append(AIMessage(content=compressed_content))
        else:
            # 短内容 / 其他类型 → 保留原样
            compacted_middle.append(msg)

    logger.info(
        "[PostSkillCompact] LLMLingua-2 段级压缩: "
        "文本部分 %d→%d 字符 (target_rate=%.2f, 实际ratio=%.2f), "
        "结构化 %d 条走规则",
        total_text_chars, len(compressed), target_rate, ratio,
        len(structured_indices),
    )

    return compacted_middle


def _protect_decimals(content: str, placeholder: str) -> tuple[str, list[tuple[str, str]]]:
    """保护小数点，防止 LLMLingua-2 将 3.14 压缩为 314

    将 数字.数字 中的小数点替换为罕见占位符，压缩后还原。
    匹配：3.14, 0.12, 99.9, 192.168.1.1, v3.11.9 等。
    """
    decimal_map: list[tuple[str, str]] = []
    pattern = re.compile(r'(\d+)\.(\d+)')

    def replacer(m: re.Match) -> str:
        original = m.group(0)
        replaced = m.group(1) + placeholder + m.group(2)
        decimal_map.append((replaced, original))
        return replaced

    protected = pattern.sub(replacer, content)
    return protected, decimal_map


def _inplace_compress_skill(
    messages: list, skill_start_idx: int, skill_end_idx: int
) -> list:
    """就地压缩 Skill 大内容（少轮次但 token 高的场景）

    不删除任何条目，而是对每条消息的 content 做就地压缩:
      - 保留第一条（skills_tool 调用）和最后一条（最终结果）完整
      - 中间的 ToolMessage > 500 字:
          - 结构化 JSON → CRM 规则摘要
          - 纯文本 ≥ 1000 字 + LLMLingua-2 启用 → 语义压缩
          - 其他 → CRM 规则摘要
      - 中间的 AIMessage:
          - 有 tool_calls 且 > 150 字 → 截断规划文本
          - 纯文本 ≥ 800 字 + LLMLingua-2 启用 → 语义压缩
          - 纯文本 > 300 字 → 截断到 150 字

    适用场景: Skill 只调了 3-5 次工具，但某些工具返回了 5K-15K 字符的结果。
    """
    result = list(messages)

    # 保护第一条和最后一条
    for i in range(skill_start_idx + 1, skill_end_idx):
        msg = result[i]

        if isinstance(msg, ToolMessage):
            content = msg.content if isinstance(msg.content, str) else str(msg.content)
            if len(content) > 500:
                tool_name = getattr(msg, "name", "") or ""
                stripped = content.strip()

                # 结构化 JSON → CRM 规则摘要
                if stripped.startswith(("{", "[")):
                    summary = _skill_internal_one_liner(tool_name, content)
                # 纯文本 ≥ 1000 字 + LLMLingua-2 启用 → 语义压缩
                elif (
                    len(content) >= 1000
                    and os.environ.get("LLMLINGUA_ENABLED", "0") == "1"
                ):
                    try:
                        from src.middleware.compression_engine import (
                            CompressionEngine, CompressLevel,
                        )
                        engine = CompressionEngine.get_instance()
                        compress_result = engine.compress(
                            content=content,
                            tool_name=tool_name,
                            level=CompressLevel.AGGRESSIVE,
                        )
                        summary = (
                            compress_result.content
                            if compress_result.is_compressed
                            else _skill_internal_one_liner(tool_name, content)
                        )
                    except Exception:
                        summary = _skill_internal_one_liner(tool_name, content)
                else:
                    summary = _skill_internal_one_liner(tool_name, content)

                result[i] = ToolMessage(
                    content=summary,
                    tool_call_id=getattr(msg, "tool_call_id", ""),
                    name=tool_name,
                )

        elif isinstance(msg, AIMessage):
            content = msg.content if isinstance(msg.content, str) else ""
            tool_calls = getattr(msg, "tool_calls", None)

            if tool_calls and len(content) > 150:
                short_content = content[:150] + "..."
                result[i] = AIMessage(content=short_content, tool_calls=tool_calls)
            elif not tool_calls and len(content) > 300:
                # 长规划文本 ≥ 800 字 + LLMLingua-2 启用 → 语义压缩
                if (
                    len(content) >= 800
                    and os.environ.get("LLMLINGUA_ENABLED", "0") == "1"
                ):
                    try:
                        from src.middleware.compression_engine import (
                            CompressionEngine, CompressLevel,
                        )
                        engine = CompressionEngine.get_instance()
                        compress_result = engine.compress(
                            content=content,
                            tool_name="",
                            level=CompressLevel.AGGRESSIVE,
                        )
                        if compress_result.is_compressed:
                            result[i] = AIMessage(content=compress_result.content)
                        else:
                            result[i] = AIMessage(
                                content=content[:150] + f"...[已压缩，原{len(content)}字]"
                            )
                    except Exception:
                        result[i] = AIMessage(
                            content=content[:150] + f"...[已压缩，原{len(content)}字]"
                        )
                else:
                    result[i] = AIMessage(
                        content=content[:150] + f"...[已压缩，原{len(content)}字]"
                    )

    # 日志
    original_tokens = sum(
        len(getattr(messages[i], "content", "") or "") // 2
        for i in range(skill_start_idx, skill_end_idx + 1)
    )
    new_tokens = sum(
        len(getattr(result[i], "content", "") or "") // 2
        for i in range(skill_start_idx, skill_end_idx + 1)
    )
    n = skill_end_idx - skill_start_idx + 1
    logger.info(
        "[PostSkillCompact] 就地压缩: %d 条不变, ~%d→%d tokens (节省%.0f%%)",
        n, original_tokens, new_tokens,
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
    """Skill 内部工具调用的一行摘要（用于 post_skill_compact）

    已统一到 CompressionEngine，此函数作为代理入口。
    使用 AGGRESSIVE 级别压缩（Skill 内部中间步骤可以极致压缩）。
    """
    try:
        from src.middleware.compression_engine import compress, CompressLevel
        result = compress(
            content, tool_name=tool_name,
            level=CompressLevel.AGGRESSIVE,
        )
        if result.is_compressed:
            return result.content
    except Exception:
        pass  # 降级到旧逻辑

    # 降级：CompressionEngine 不可用时走原有逻辑
    import json as _json

    stripped = content.strip()
    if stripped.startswith("{") or stripped.startswith("["):
        try:
            data = _json.loads(stripped)
            if isinstance(data, dict):
                return _one_liner_json_object(tool_name, data)
            elif isinstance(data, list):
                return _one_liner_json_array(tool_name, data)
        except _json.JSONDecodeError:
            pass

    return _one_liner_text(tool_name, content)


def _one_liner_json_object(tool_name: str, data: dict) -> str:
    """JSON 对象: 提取关键字段 + records 子结构聚合 + 嵌套数字提取"""
    # 如果包含 records 列表（query_data 典型返回）
    if "records" in data and isinstance(data["records"], list):
        records = data["records"]
        return _one_liner_json_array(tool_name, records)

    # 如果包含 fields 列表（query_schema 典型返回）
    if "fields" in data and isinstance(data["fields"], list):
        entity = data.get("entity") or data.get("name") or data.get("object") or ""
        fields = data["fields"]
        count = len(fields)
        field_names = []
        for f in fields[:6]:
            if isinstance(f, dict):
                field_names.append(f.get("api_key") or f.get("name") or f.get("label") or "")
        names_str = ", ".join(n for n in field_names if n)
        extra = f"...等{count}个" if count > 6 else ""
        return f"[{tool_name}] {entity} 字段定义({count}个): {names_str}{extra}"

    # 单条记录: 提取业务关键字段
    key_fields = ["name", "id", "amount", "stage", "status", "title",
                  "type", "owner", "close_date", "probability"]
    parts = []
    for k in key_fields:
        v = data.get(k)
        if v is not None and v != "":
            parts.append(f"{k}={v}")
    if parts:
        return f"[{tool_name}] {', '.join(str(p) for p in parts[:8])}"

    # 嵌套结构: 递归提取数字型值和子对象的关键字段
    num_parts = _extract_nested_numbers(data)
    if num_parts:
        return f"[{tool_name}] {', '.join(num_parts[:8])}"

    # 兜底: key 数量 + 前几个 key
    keys = list(data.keys())[:6]
    return f"[{tool_name}] 对象({len(data)}字段): {', '.join(keys)}"


def _extract_nested_numbers(data: dict, prefix: str = "", depth: int = 0) -> list[str]:
    """从嵌套 JSON 中提取数字型值（金额、百分比、计数等）

    最多递归 2 层，提取所有数字和含数字的字符串值。
    """
    if depth > 2:
        return []
    parts: list[str] = []
    for k, v in data.items():
        label = f"{prefix}{k}" if prefix else k
        if isinstance(v, (int, float)) and v != 0:
            parts.append(f"{label}={v:g}")
        elif isinstance(v, str) and re.search(r'\d', v) and len(v) < 30:
            parts.append(f"{label}={v}")
        elif isinstance(v, dict) and depth < 2:
            parts.extend(_extract_nested_numbers(v, prefix=f"{label}.", depth=depth + 1))
        elif isinstance(v, list) and len(v) > 0 and depth < 2:
            if isinstance(v[0], dict):
                # 列表取前 2 条的关键字段
                for i, item in enumerate(v[:2]):
                    name = item.get("name") or item.get("title") or ""
                    amt = item.get("amount")
                    if name or amt:
                        parts.append(f"{label}[{i}]={name}{'/' + str(amt) if amt else ''}")
            elif isinstance(v[0], (int, float)):
                parts.append(f"{label}=[{v[0]}...{v[-1]}]({len(v)}项)")
    return parts


def _one_liner_json_array(tool_name: str, data: list) -> str:
    """JSON 数组: 记录数 + 样本名 + 金额聚合"""
    count = len(data)
    parts = [f"返回{count}条"]

    if count > 0 and isinstance(data[0], dict):
        # 提取前 5 条的 name/title
        names = []
        for item in data[:5]:
            n = item.get("name") or item.get("title") or item.get("subject") or ""
            if n:
                names.append(str(n)[:20])
        if names:
            names_str = ", ".join(names)
            if count > 5:
                names_str += f"...等{count}条"
            parts.append(names_str)

        # 金额聚合（如果有 amount 字段）
        amounts = []
        for item in data:
            amt = item.get("amount")
            if amt is not None:
                try:
                    amounts.append(float(amt))
                except (ValueError, TypeError):
                    pass
        if amounts:
            total = sum(amounts)
            parts.append(f"总金额{total:,.0f}")

        # 阶段分布（如果有 stage 字段）
        stages: dict[str, int] = {}
        for item in data:
            s = item.get("stage") or item.get("status")
            if s:
                stages[str(s)] = stages.get(str(s), 0) + 1
        if stages:
            stage_str = "/".join(f"{k}:{v}" for k, v in list(stages.items())[:4])
            parts.append(stage_str)

    return f"[{tool_name}] {', '.join(parts)}"


def _one_liner_text(tool_name: str, content: str) -> str:
    """非 JSON 文本: 提取关键数字 + 前缀预览"""
    # 提取关键数字（金额、百分比、日期）
    key_numbers = []

    amounts = re.findall(
        r'[\$¥￥]\s*[\d,.]+[KMB万亿]?|\d[\d,.]*\s*(?:万|亿|USD|CNY|元)',
        content[:2000],
    )
    if amounts:
        unique = list(dict.fromkeys(amounts[:5]))
        key_numbers.append(f"金额:{','.join(unique)}")

    pcts = re.findall(r'\d+\.?\d*\s*%', content[:2000])
    if pcts:
        unique = list(dict.fromkeys(pcts[:4]))
        key_numbers.append(f"比例:{','.join(unique)}")

    dates = re.findall(r'\d{4}[-/]\d{1,2}[-/]\d{1,2}', content[:1000])
    if dates:
        unique = list(dict.fromkeys(dates[:3]))
        key_numbers.append(f"日期:{','.join(unique)}")

    # 组装: 工具名 + 前缀预览 + 关键数字
    preview = content[:80].replace("\n", " ").strip()
    key_str = f" [{'; '.join(key_numbers)}]" if key_numbers else ""
    return f"[{tool_name}] {preview}...{key_str} ({len(content)}字符)"

