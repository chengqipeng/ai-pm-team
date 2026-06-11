"""上下文窗口管理中间件 — 统一的上下文压缩与控制

设计哲学（对齐 Hermes Agent）：
  "不到阈值不压缩 → 到了阈值一次性处理"
  — 窗口没有压力时历史数据完整保留，窗口有压力时统一裁剪，
  — 但当前轮次（最后一条 HumanMessage 之后）始终完整保护。

wrap_tool_call 阶段（安全网 + 锚点）：
  - 仅做安全网截断（超大结果 >50K 才触发）— 正常结果完整保留
  - Skill 完成时触发锚点提取

before_model 阶段（阈值触发时统一压缩）：
  - Post-Skill Compact: Skill 内部 >8 条 → 即时裁剪（始终执行）
  - MD5 去重: 相同内容只保留最新一份（始终执行）
  - 阈值触发:
    - MicroCompact (≥50%): 保护区外旧 ToolMessage → 摘要 + args 截断
    - AutoCompact (≥75%): 保护区外全部消息 → LLM 结构化摘要（迭代更新）+ 锚点
    - FullCompact (≥90%): LLM 全量压缩 + 锚点 + 重注入最近交互
  - 熔断机制: 连续 N 次压缩失败后停止重试

保护区确定（对齐 Hermes _find_tail_cut_by_tokens）：
  1. 当前轮次锚定: 最后一条 HumanMessage 之后的所有消息 → 绝对保护
  2. Skill 边界感知 (§4.1): 如果切割点在 Skill 内部 → 推进到 Skill 起始
  3. 工具组原子性 (§4.2): 如果切割点在并发 ToolMessage 中间 → 回退到父 AIMessage
  4. 最后用户消息锚定: 确保最近的 HumanMessage 在保护区内

Skill 模式增强（对应缺口分析 §4）：
  - §4.1 Skill 执行边界感知的尾部保护
  - §4.2 工具组原子性增强（深度边界对齐）
  - §4.3 Skill 结果锚点（防止迭代压缩数据衰减）
  - §4.4 Post-Skill Compact（Skill 结束即收缩）

Hermes 对齐增强（Phase 1-4）：
  - Phase 1: 辅助 LLM 路由 — 压缩任务路由到 AUXILIARY 模型（便宜快速）
  - Phase 2: 结构化摘要模板 — CRM 7-section 模板替代行级截断
  - Phase 3: 迭代摘要 — _previous_summary 跨压缩周期保持，增量更新
  - Phase 4: 自动 Focus Topic — 从当前 Skill 推断压缩焦点

参考：
  - Hermes: _prune_old_tool_results + _find_tail_cut_by_tokens（阈值触发 → 统一处理）
  - Hermes: _generate_summary + _previous_summary（迭代摘要 + 12-section 模板）
  - Hermes: auxiliary_client.py（辅助 LLM 路由）
  - Claude Code: MicroCompact / AutoCompact / FullCompact（三层级联）
"""
from __future__ import annotations

import hashlib
import json
import logging
import time
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain.agents.middleware.types import AgentMiddleware, AgentState
from langgraph.prebuilt.tool_node import ToolCallRequest
from langgraph.runtime import Runtime
from langgraph.types import Command

from src.middleware.skill_compress import (
    SkillAwareTailProtection,
    SkillResultAnchor,
    align_boundary_deep,
    find_completed_skill_boundaries,
    post_skill_compact,
)
from src.middleware.context_archive import ContextArchive
from src.core.model_router import ModelRouter, TaskType

logger = logging.getLogger(__name__)


def _estimate_tokens(messages: list) -> int:
    """粗略估算 token 数（1 token ≈ 2 字符，中英混合场景误差约 ±30%）

    此估算偏保守（中文实际 ~1.5字符/token，英文 ~4字符/token），
    在纯中文场景可能导致略微提前触发压缩，但不会漏触发。
    """
    total = 0
    for msg in messages:
        content = getattr(msg, "content", "")
        if isinstance(content, str):
            total += len(content) // 2
        elif isinstance(content, list):
            for block in content:
                if isinstance(block, str):
                    total += len(block) // 2
                elif isinstance(block, dict):
                    total += len(str(block.get("text", ""))) // 2
    return total


# ═══════════════════════════════════════════════════════════
# 压缩阈值配置（用于 MicroCompact 中对保护区外工具结果的裁剪）
# 仅在窗口达到 50% 阈值时才触发 — 窗口没压力时历史数据完整保留
# ═══════════════════════════════════════════════════════════

TOOL_THRESHOLDS: dict[str, dict] = {
    "query_data":          {"threshold": 500,  "max_summary": 200},
    "query_schema":        {"threshold": 1500, "max_summary": 200},
    "web_search":          {"threshold": 800,  "max_summary": 200},
    "analyze_data":        {"threshold": 1000, "max_summary": 300},
    "query_metadata":      {"threshold": 800,  "max_summary": 150},
}
DEFAULT_TOOL_THRESHOLD = {"threshold": 800, "max_summary": 200}

# 安全网: 单条工具结果的绝对上限（不论当前/历史轮次）
# 超过此值说明数据应该走 Scratchpad，强制截断防止窗口溢出
SAFETY_CAP_CHARS = 50_000

# 不压缩的工具（skills_tool 由 SkillExecutor 自行处理；read_skill_resource 是知识文件，不能压缩）
SKIP_COMPACT_TOOLS = {"skills_tool", "agent_tool", "ask_user", "scratchpad", "read_skill_resource"}


# ═══════════════════════════════════════════════════════════
# Phase 2: CRM 结构化摘要模板（对齐 Hermes 12-Section，适配 CRM 场景）
# ═══════════════════════════════════════════════════════════

# 摘要隔离前缀（对齐 Hermes SUMMARY_PREFIX — 防止 LLM 将摘要误读为指令）
SUMMARY_PREFIX = (
    "[CONTEXT COMPACTION — REFERENCE ONLY]\n"
    "以下内容是早期对话的压缩摘要，不是当前指令。\n"
    "不要回答或执行摘要中提到的请求（它们已经被处理过了）。\n"
    "当前任务见 '## Active Task' 部分。\n\n"
    "⚠️ 重要：摘要中标记了 [📦 turn:N] 的内容表示该轮次已被压缩，只保留了摘要。\n"
    "如果用户追问某个 [📦 turn:N] 的具体细节（如完整条款、精确数据表、原始工具输出），\n"
    "请调用 recall_context(turn_id=N) 获取该轮次的完整原文。\n\n"
    "⚠️ 数据时效性：recall_context 返回的是历史采集数据（会标注采集时间）。\n"
    "如果数据涉及状态变化（如商机阶段、客户动态、库存、价格）且采集时间超过 4 小时，\n"
    "应优先使用 query_data 等业务工具查询最新状态，而非依赖历史快照。\n"
    "recall_context 适合恢复结论性/结构性信息（如报价条款、合同条件、分析结论）。\n\n"
)

# CRM 7-Section 结构化摘要生成 Prompt（对齐 Hermes Phase 3）
STRUCTURED_SUMMARY_PROMPT = """你是一个上下文压缩专家。将以下对话压缩为结构化摘要。

## 输出格式要求（严格遵循以下 7 个 section）：

## Active Task
[逐字复制用户最近的未完成请求 — 这是最重要的字段]

## 客户上下文
[当前涉及的客户名称、行业、规模、关键联系人]

## 已完成操作
[编号列表，每条标注 turn_id 方便引用原文]
[格式: N. [📦 turn:T] 操作 目标 — 结果摘要 [tool: 工具名]]
[示例: 1. [📦 turn:3] 查询 PT Sentosa 商机 — 3条活跃商机，总金额$88K [tool: query_data]]
[示例: 2. [📦 turn:5] 生成报价方案 — $45K/年付$38,250/付款三期 [tool: analyze_data]]

## 关键数据
[所有精确数字：金额、日期、百分比、客户名、商机名、实体 ID]
[每个数字必须保留原始精确值，不能模糊化]
[标注来源轮次: "$45,000 (turn:5)", "折扣15% (turn:5)"]

## 已回答问题
[Q: 用户问题 → A: 答案摘要 [📦 turn:T]（防止重复回答）]

## 待处理
[用户提出但尚未完成的请求]

## 涉及实体
[操作过的 CRM 实体及记录 ID，如 opportunity(opp_001), account(acc_xxx)]

## 规则：
1. Active Task 是最重要的字段 — 必须逐字复制用户最近的未完成请求
2. 关键数据中的数字必须精确保留（$45,000 不能变成"约4.5万"）
3. 已完成操作必须标注 [📦 turn:T]，T 是对话中该操作发生的轮次编号
4. "待处理"用 remaining 语义，不是 next steps（避免被误读为指令）
5. 摘要总长度控制在 1500 字以内
6. [📦 turn:T] 标记告诉后续 AI：如果需要该轮次的完整细节，调用 recall_context(turn_id=T)

{focus_topic_instruction}

## 待压缩的对话内容（每轮标注了 turn_id）：
{conversation}
"""

# Phase 3: 迭代摘要更新 Prompt（对齐 Hermes 的 PRESERVE/ADD/MOVE/UPDATE 策略）
ITERATIVE_SUMMARY_PROMPT = """你是一个上下文压缩专家。基于上次摘要和新增对话，更新结构化摘要。

## 更新规则（严格遵循）：
- PRESERVE: 保留上次摘要中所有仍然相关的信息（包括 [📦 turn:T] 标记）
- ADD: 将新完成的操作添加到"已完成操作"列表（继续编号，标注新的 turn_id）
- MOVE: 已完成的项从"待处理"移到"已完成操作"
- MOVE: 已回答的问题添加到"已回答问题"（保留 [📦 turn:T] 标记）
- UPDATE: 更新"Active Task"为用户最近的未完成请求
- UPDATE: 更新"关键数据"中的新发现数字（标注来源 turn_id）
- CRITICAL: Active Task 必须反映用户最新的未完成请求
- CRITICAL: 所有 [📦 turn:T] 标记必须原样保留，这是检索原文的索引

## 上次摘要：
{previous_summary}

## 新增对话内容（每轮标注了 turn_id）：
{new_conversation}

{focus_topic_instruction}

## 输出格式（严格遵循 7 个 section，保留所有 [📦 turn:T] 标记）：
## Active Task
## 客户上下文
## 已完成操作
## 关键数据
## 已回答问题
## 待处理
## 涉及实体

请直接输出更新后的结构化摘要，不要添加解释。
"""



class ContextWindowMiddleware(AgentMiddleware):
    """上下文窗口管理 — 阈值触发式压缩（对齐 Hermes 模式）

    核心原则: 不到阈值不压缩。窗口没有压力时历史数据完整保留，
    窗口有压力时统一裁剪，但当前轮次（最后 HumanMessage 之后）始终完整保护。

    wrap_tool_call: 安全网截断（仅 >50K 极端情况）+ Skill 锚点提取
    before_model:  Post-Skill Compact + MD5 去重 + 阈值触发压缩
                   （MicroCompact / AutoCompact / FullCompact）
    """

    def __init__(
        self,
        max_tokens: int = 100_000,
        micro_threshold: float = 0.50,
        auto_threshold: float = 0.75,
        full_threshold: float = 0.90,
        tool_output_max_chars: int = 2_000,
        max_consecutive_failures: int = 3,
        llm: Any = None,
        model_router: ModelRouter | None = None,
        # Skill 模式增强参数
        skill_min_tail: int = 5,
        skill_max_tail: int = 30,
        post_skill_compact_threshold: int = 8,
        # 安全网参数
        safety_cap_chars: int = SAFETY_CAP_CHARS,
    ):
        super().__init__()
        self._max_tokens = max_tokens
        self._micro_trigger = int(max_tokens * micro_threshold)
        self._auto_trigger = int(max_tokens * auto_threshold)
        self._full_trigger = int(max_tokens * full_threshold)
        self._tool_output_max_chars = tool_output_max_chars
        self._max_failures = max_consecutive_failures
        self._consecutive_failures = 0
        self._llm = llm
        self._model_router = model_router
        self._safety_cap = safety_cap_chars

        # §4.1 Skill 边界感知尾部保护
        self._skill_tail_protection = SkillAwareTailProtection(
            min_tail_messages=skill_min_tail,
            max_tail_messages=skill_max_tail,
        )
        # §4.3 Skill 结果锚点（session 级别，跨多轮压缩持久）
        self._skill_anchors = SkillResultAnchor()
        # §4.4 Post-Skill Compact 阈值
        self._post_skill_compact_threshold = post_skill_compact_threshold

        # Phase 3: 迭代摘要状态（对齐 Hermes self._previous_summary）
        self._previous_summary: str | None = None
        # Phase 4: 自动 Focus Topic（从最近执行的 Skill 推断）
        self._current_focus_topic: str | None = None
        # 反抖动：连续低效压缩计数（对齐 Hermes _ineffective_compression_count）
        self._ineffective_compression_count: int = 0
        # 格式化时记录的轮次数（供存档使用）
        self._last_format_turn_count: int = 0
        # 压缩存档索引（供 recall_context 工具检索恢复原文）
        self._archive = ContextArchive(max_entries=100)
        # 当前 thread_id（由 before_model 从 runtime 获取，供存档引用 Checkpointer）
        self._current_thread_id: str = ""

    # ═══════════════════════════════════════════════════════════
    # wrap_tool_call: 安全网 + Skill 锚点提取
    # 对齐 Hermes: 工具结果完整保留，不做源头压缩
    # 仅在极端情况（>50K）做安全网截断
    # ═══════════════════════════════════════════════════════════

    async def awrap_tool_call(self, request: ToolCallRequest, handler) -> ToolMessage | Command:
        tool_name = request.tool_call.get("name", "unknown")
        tool_call_id = request.tool_call.get("id", "")

        result = await handler(request)

        # §4.3: skills_tool 完成时提取锚点（§4.4 Post-Skill Compact 延迟到 before_model 执行）
        if tool_name == "skills_tool":
            skill_name = request.tool_call.get("args", {}).get("skill_name", "")
            self._on_skill_tool_complete(result, skill_name=skill_name)
            return result

        # 跳过不需要处理的工具
        if tool_name in SKIP_COMPACT_TOOLS:
            return result

        # ── 安全网: 仅对超大结果做紧急截断（正常结果完整保留）──
        # 对齐 Hermes 设计: 当前轮次的工具结果 LLM 需要完整看到
        # 延迟压缩在 before_model._deferred_compress 中对历史轮次处理
        content = getattr(result, "content", "")
        if not isinstance(content, str):
            content = str(content)

        if len(content) > self._safety_cap:
            original_len = len(content)
            # 超大结果: 代码提取摘要 → 截断兜底
            summary = _try_code_extract(tool_name, content)
            if not summary:
                summary = _fallback_truncate(tool_name, content, self._safety_cap // 10)
            result.content = summary
            logger.warning(
                "[ContextWindow] 安全网截断 %s: %d→%d chars (原文超过安全上限 %d)",
                tool_name, original_len, len(summary), self._safety_cap,
            )
            self._record_compact_span(tool_name, original_len, len(summary),
                                      original_content=content[:2000],
                                      summary_content=summary,
                                      tool_call_id=tool_call_id)

        return result

    async def _llm_summarize(self, content: str, tool_name: str, max_words: int) -> str | None:
        """使用辅助 LLM 生成摘要（Phase 1: 路由到 AUXILIARY 模型）"""
        llm = self._get_auxiliary_llm()
        if not llm:
            return None
        try:
            from langchain_core.messages import HumanMessage as HM
            prompt = (
                f"请将以下工具 `{tool_name}` 的返回结果压缩为不超过 {max_words} 字的摘要。\n"
                f"要求：保留关键数据（数字、名称、状态），去掉冗余描述。\n\n"
                f"原文：\n{content[:3000]}"
            )
            # §4.3 注入锚点到摘要 prompt，确保关键数据不丢
            prompt = self._skill_anchors.inject_into_summary_prompt(prompt)
            resp = await llm.ainvoke([HM(content=prompt)])
            return resp.content[:max_words * 3]
        except Exception as e:
            logger.warning("[ContextWindow] LLM summarize failed: %s", e)
            return None

    def _get_auxiliary_llm(self) -> Any | None:
        """Phase 1: 获取辅助 LLM — 优先使用 ModelRouter 路由到 AUXILIARY 模型

        降级链路：ModelRouter.AUXILIARY → self._llm → None
        辅助模型通常是便宜快速的模型（如 deepseek-v4-flash），
        与主推理模型分离，摘要失败不影响主推理。
        """
        if self._model_router:
            try:
                return self._model_router.get_model(TaskType.AUXILIARY)
            except Exception as e:
                logger.warning("[ContextWindow] ModelRouter.AUXILIARY 获取失败: %s, 降级到 self._llm", e)
        return self._llm

    # ═══════════════════════════════════════════════════════════
    # §4.3 + §4.4: Skill 完成时的锚点提取与内部压缩
    # ═══════════════════════════════════════════════════════════

    def _on_skill_tool_complete(self, result: ToolMessage | Any, skill_name: str = "") -> None:
        """skills_tool 返回结果时触发锚点提取 + Focus Topic 更新

        注意: Post-Skill Compact 在 before_model 中执行（此时才能访问完整 messages）。
        这里负责锚点提取 + Phase 4 Focus Topic 推断。
        """
        content = getattr(result, "content", "")
        if not isinstance(content, str):
            content = str(content)

        # 技能名称优先从 tool_call args 获取（最准确），其次从结果标记中提取
        if not skill_name:
            import re
            match = re.search(r'\[SKILL_DONE:\w+\]\s*(\S+)', content)
            if match:
                skill_name = match.group(1)
            else:
                skill_name = "unknown_skill"

        # §4.3 提取锚点
        self._skill_anchors.on_skill_complete(
            skill_name=skill_name,
            skill_result=content,
            tool_calls_history=[],  # wrap_tool_call 中无法访问完整历史
        )

        # Phase 4: 从 Skill 名称推断 Focus Topic
        self._update_focus_from_skill(skill_name)

    def _apply_post_skill_compact(self, messages: list) -> list:
        """§4.4 Post-Skill Compact — 在 before_model 中对已完成的 Skill 做即时内部压缩

        扫描消息列表中所有已完成的 Skill 执行，如果其内部消息数超过阈值则压缩。
        从后向前处理以保持 index 稳定性。
        """
        boundaries = find_completed_skill_boundaries(messages)
        if not boundaries:
            return messages

        # 从后向前压缩，避免 index 偏移
        for start_idx, end_idx in reversed(boundaries):
            skill_msg_count = end_idx - start_idx + 1
            if skill_msg_count > self._post_skill_compact_threshold:
                messages = post_skill_compact(
                    messages, start_idx, end_idx,
                    min_skill_messages=self._post_skill_compact_threshold,
                )

        return messages

    def _update_focus_from_skill(self, skill_name: str) -> None:
        """Phase 4: 从 Skill 名称自动推断 Focus Topic

        CRM 场景中的 Skill → Topic 映射:
        让压缩器在生成摘要时优先保留与当前任务相关的信息。
        """
        # Skill 名称 → Focus Topic 映射表
        _SKILL_TOPIC_MAP: dict[str, str] = {
            "报价": "报价/金额/折扣/竞品定价/付款条件",
            "quote": "报价/金额/折扣/竞品定价/付款条件",
            "pricing": "报价/金额/折扣/竞品定价/付款条件",
            "竞品": "竞品/定价/市场份额/优劣势对比",
            "competitor": "竞品/定价/市场份额/优劣势对比",
            "拜访": "客户画像/商机/联系人/历史互动/需求",
            "visit": "客户画像/商机/联系人/历史互动/需求",
            "pipeline": "商机/阶段/金额/赢率/跟进状态",
            "漏斗": "商机/阶段/金额/赢率/跟进状态",
            "coaching": "销售人员/业绩/风险商机/跟进策略",
            "分析": "数据/指标/趋势/对比/结论",
            "analysis": "数据/指标/趋势/对比/结论",
            "调研": "行业/竞品/趋势/数据/来源",
            "research": "行业/竞品/趋势/数据/来源",
        }

        skill_lower = skill_name.lower()
        for keyword, topic in _SKILL_TOPIC_MAP.items():
            if keyword in skill_lower:
                self._current_focus_topic = topic
                logger.info("[ContextWindow] Phase 4: Skill '%s' → Focus Topic '%s'",
                            skill_name, topic)
                return
        # 无匹配时不清除现有 topic（保持上一个 Skill 的 topic）

    # ═══════════════════════════════════════════════════════════
    # 保护区计算辅助 — 对齐 Hermes _find_tail_cut_by_tokens
    # ═══════════════════════════════════════════════════════════

    def _find_current_turn_start(self, messages: list) -> int:
        """找到当前轮次的起始位置（最后一条 HumanMessage 的 index）

        对齐 Hermes 的 _ensure_last_user_message_in_tail:
        确保最近的 HumanMessage 之后的所有消息都在保护区内。
        这保证了 LLM 不会丢失当前任务上下文。
        """
        for i in range(len(messages) - 1, -1, -1):
            if isinstance(messages[i], HumanMessage):
                return i
        return 0

    # ═══════════════════════════════════════════════════════════
    # before_model: 阈值触发式压缩（对齐 Hermes 模式）
    # ═══════════════════════════════════════════════════════════

    def before_model(self, state: AgentState, runtime: Runtime) -> dict[str, Any] | None:
        messages = state.get("messages", [])

        # 获取 thread_id（供存档引用 Checkpointer）
        try:
            config = getattr(runtime, "config", None) or {}
            if isinstance(config, dict):
                self._current_thread_id = config.get("configurable", {}).get("thread_id", "")
                _tenant_id = config.get("configurable", {}).get("tenant_id", 0)
            else:
                self._current_thread_id = getattr(config, "get", lambda *a: "")(
                    "configurable", {}).get("thread_id", "")
                _tenant_id = getattr(config, "get", lambda *a: 0)(
                    "configurable", {}).get("tenant_id", 0)
            # 设置存档上下文（供 PG 持久化使用）
            if self._current_thread_id:
                self._archive.set_context(int(_tenant_id or 0), self._current_thread_id)
        except Exception:
            pass

        # §4.4 Post-Skill Compact — Skill 结束即收缩（始终执行，与阈值无关）
        messages = self._apply_post_skill_compact(messages)

        # MD5 去重（始终执行）
        dedup_result = self._md5_dedup(messages)
        if dedup_result is not None:
            messages = dedup_result["messages"]

        if len(messages) < 4:
            self._record_window_span(
                len(messages), 0, "skip", "消息数不足",
                messages_before=messages)
            return dedup_result

        # 熔断检查
        if self._consecutive_failures >= self._max_failures:
            self._record_window_span(
                len(messages), 0, "circuit_break",
                f"熔断（连续{self._consecutive_failures}次失败）",
                messages_before=messages)
            return dedup_result

        estimated = _estimate_tokens(messages)

        try:
            # Pass 3: FullCompact（含 §4.1 Skill 边界感知 + §4.3 锚点注入）
            if estimated >= self._full_trigger:
                result = self._full_compact(messages, estimated)
                if result:
                    self._consecutive_failures = 0
                    new_est = _estimate_tokens(result["messages"])
                    self._record_window_span(
                        len(messages), estimated, "full_compact",
                        f"超过90%阈值（{estimated}/{self._max_tokens}）",
                        new_est, len(result["messages"]), messages, result["messages"])
                    return result

            # Pass 2: AutoCompact（含 §4.1 Skill 边界感知 + §4.2 工具组原子性）
            if estimated >= self._auto_trigger:
                result = self._auto_compact(messages, estimated)
                if result:
                    self._consecutive_failures = 0
                    new_est = _estimate_tokens(result["messages"])
                    self._record_window_span(
                        len(messages), estimated, "auto_compact",
                        f"超过75%阈值（{estimated}/{self._max_tokens}）",
                        new_est, len(result["messages"]), messages, result["messages"])
                    return result

            # Pass 1: MicroCompact（含 §4.1 Skill 边界感知 + §4.2 工具组原子性）
            if estimated >= self._micro_trigger:
                result = self._micro_compact(messages, estimated)
                if result:
                    new_est = _estimate_tokens(result["messages"])
                    self._record_window_span(
                        len(messages), estimated, "micro_compact",
                        f"超过50%阈值（{estimated}/{self._max_tokens}）",
                        new_est, len(result["messages"]), messages, result["messages"])
                    return result

        except Exception as e:
            self._consecutive_failures += 1
            logger.error("Compression failed (%d/%d): %s",
                         self._consecutive_failures, self._max_failures, e)
            self._record_window_span(
                len(messages), estimated, "error",
                f"压缩失败: {str(e)[:100]}", messages_before=messages)

        # 无需压缩
        self._record_window_span(
            len(messages), estimated, "none", "未达到压缩阈值",
            messages_before=messages)
        return dedup_result

    # ═══════════════════════════════════════════════════════════
    # Pass 0: MD5 去重
    # ═══════════════════════════════════════════════════════════

    def _md5_dedup(self, messages: list) -> dict[str, Any] | None:
        """相同内容的 ToolMessage 只保留最新一份"""
        seen: dict[str, int] = {}
        modified = False
        result = list(messages)

        for i in range(len(result) - 1, -1, -1):
            if not isinstance(result[i], ToolMessage):
                continue
            content = result[i].content or ""
            if len(content) < 100:
                continue
            h = hashlib.md5(content.encode("utf-8")).hexdigest()[:12]
            if h in seen:
                result[i] = ToolMessage(
                    content="[重复结果 — 与最近一次相同查询结果一致]",
                    tool_call_id=getattr(result[i], "tool_call_id", ""),
                )
                modified = True
            else:
                seen[h] = i

        if modified:
            logger.info("[ContextWindow] MD5 去重: 移除重复 ToolMessage")
            return {"messages": result}
        return None

    # ═══════════════════════════════════════════════════════════
    # MicroCompact — 当前轮次保护 + 历史 ToolMessage 裁剪
    # 对齐 Hermes _prune_old_tool_results: 保护区外旧结果 → 信息摘要替换
    # ═══════════════════════════════════════════════════════════

    def _micro_compact(self, messages: list, estimated: int) -> dict[str, Any] | None:
        """裁剪保护区外旧 ToolMessage + tool_call 参数截断

        保护区确定（对齐 Hermes tail protection）:
          1. 当前轮次锚定: 最后 HumanMessage 之后的所有消息 → 绝对保护
          2. §4.1 Skill 边界感知: 切割点在 Skill 内部 → 推进到 Skill 起始
          3. §4.2 工具组原子性: 切割点在并发 ToolMessage 中间 → 回退到父 AIMessage
          4. 取 max(基础 keep_recent, 当前轮次起始) 作为最终保护区

        压缩区处理（对齐 Hermes Pass 2 + Pass 3）:
          - 旧 ToolMessage > 200 字 → CRM 一行摘要（零 LLM 成本）
          - 旧 AIMessage tool_call args > 500 字 → 截断到 200 字
        """
        base_keep_recent = 6

        # 当前轮次锚定: 确保最后 HumanMessage 之后全部保护
        current_turn_start = self._find_current_turn_start(messages)

        # §4.1 Skill 边界感知的尾部保护
        skill_tail_start = self._skill_tail_protection.compute_tail_start(
            messages, keep_recent=base_keep_recent, head_end=0,
        )

        # 取最小 index（最大保护范围）: 当前轮次 vs Skill 边界 vs 基础 keep_recent
        tail_start = min(current_turn_start, skill_tail_start)

        # §4.2 深度边界对齐 — 不在工具组中间切割
        tail_start = align_boundary_deep(messages, tail_start)

        if tail_start <= 0 or tail_start >= len(messages):
            return None

        old_messages = messages[:tail_start]
        recent = messages[tail_start:]
        modified = False
        compacted = []

        for msg in old_messages:
            if isinstance(msg, ToolMessage):
                content = msg.content if isinstance(msg.content, str) else str(msg.content)
                if len(content) > 200:
                    # CRM 专用摘要模板（对齐 Hermes _summarize_tool_result）
                    summary = _crm_tool_summary(msg)
                    compacted.append(ToolMessage(
                        content=summary,
                        tool_call_id=getattr(msg, "tool_call_id", ""),
                        name=getattr(msg, "name", ""),
                    ))
                    modified = True
                    continue
            # tool_call 参数截断（对齐 Hermes Pass 3）
            elif isinstance(msg, AIMessage) and getattr(msg, "tool_calls", None):
                tc_modified = False
                new_tool_calls = []
                for tc in msg.tool_calls:
                    args_str = json.dumps(tc.get("args", {}), ensure_ascii=False)
                    if len(args_str) > 500:
                        tc = dict(tc)
                        tc["args"] = {"_truncated": args_str[:200] + "..."}
                        tc_modified = True
                    new_tool_calls.append(tc)
                if tc_modified:
                    compacted.append(AIMessage(
                        content=msg.content, tool_calls=new_tool_calls))
                    modified = True
                    continue
            compacted.append(msg)

        if not modified:
            return None

        new_estimated = _estimate_tokens(compacted + recent)
        logger.info("[ContextWindow] MicroCompact: %d → %d tokens (保护区从 idx %d 起, 当前轮 idx %d)",
                    estimated, new_estimated, tail_start, current_turn_start)
        return {"messages": compacted + recent}

    # ═══════════════════════════════════════════════════════════
    # Pass 2: AutoCompact — LLM 结构化摘要 + 迭代更新 + Focus Topic
    # 对齐 Hermes Phase 2-4: _generate_summary + _previous_summary + focus_topic
    # ═══════════════════════════════════════════════════════════

    def _auto_compact(self, messages: list, estimated: int) -> dict[str, Any] | None:
        """LLM 结构化摘要替换旧消息（对齐 Hermes Phase 3 + Phase 4）

        Phase 2: 使用 CRM 7-section 模板生成结构化摘要（替代行级截断）
        Phase 3: 迭代更新 — 传入上次摘要，要求 PRESERVE/ADD/MOVE/UPDATE
        Phase 4: 自动 Focus Topic — 从当前 Skill 推断压缩焦点

        分区模型:
          - Head 保护区: SystemMessage + 第一条 HumanMessage（保留全局身份/指令）
          - 压缩区: head_end ... tail_start（送入 LLM 摘要）
          - 尾部保护区: tail_start ... 末尾（完整拼接回去）

        §4.3 增强: 锚点注入到摘要 prompt 中
        降级策略: LLM 摘要失败 → fallback 到行级截断（零 LLM 成本）
        """
        base_keep_recent = 4

        # ── Head 保护区: SystemMessage + 第一条 HumanMessage ──
        head_end = 0
        head_messages = []
        first_human_found = False
        for i, msg in enumerate(messages):
            role = getattr(msg, "type", "unknown")
            if role == "system":
                head_messages.append(msg)
                head_end = i + 1
            elif isinstance(msg, HumanMessage) and not first_human_found:
                head_messages.append(msg)
                first_human_found = True
                head_end = i + 1
                break
            else:
                break

        # ── 尾部保护区计算 ──
        current_turn_start = self._find_current_turn_start(messages)
        skill_tail_start = self._skill_tail_protection.compute_tail_start(
            messages, keep_recent=base_keep_recent, head_end=head_end,
        )
        tail_start = min(current_turn_start, skill_tail_start)
        tail_start = align_boundary_deep(messages, tail_start)

        # 确保 tail_start 不小于 head_end
        tail_start = max(tail_start, head_end)

        if tail_start <= head_end or tail_start >= len(messages):
            return None

        to_summarize = messages[head_end:tail_start]
        recent = messages[tail_start:]

        # *** 压缩前存档: 将即将被压缩的消息建立索引（供 recall_context 恢复）***
        if self._current_thread_id:
            self._archive.index_messages(to_summarize, self._current_thread_id, base_msg_index=head_end)

        # 将 middle 区消息格式化为对话文本（供 LLM 摘要）
        conversation_text = self._format_messages_for_summary(to_summarize)
        if not conversation_text.strip():
            return None

        # Phase 4: 构建 Focus Topic 指令
        focus_instruction = self._build_focus_topic_instruction()

        # 尝试 LLM 结构化摘要（Phase 2 + Phase 3）
        summary_text = self._generate_structured_summary(
            conversation_text, focus_instruction
        )

        if not summary_text:
            # LLM 失败 → fallback 到行级截断（保持向后兼容）
            summary_text = self._fallback_line_summary(to_summarize)

        # §4.3 注入 Skill 锚点到摘要中
        anchor_summary = self._skill_anchors.get_anchor_summary()
        if anchor_summary:
            summary_text += "\n\n" + anchor_summary

        # 反抖动检查（对齐 Hermes anti-thrashing）
        new_messages = head_messages + [SystemMessage(content=SUMMARY_PREFIX + summary_text)] + recent
        new_estimated = _estimate_tokens(new_messages)
        savings_ratio = 1 - new_estimated / max(estimated, 1)

        if savings_ratio < 0.10:
            self._ineffective_compression_count += 1
            if self._ineffective_compression_count >= 2:
                logger.warning(
                    "[ContextWindow] 反抖动: 连续 %d 次压缩节省 <10%%, 跳过",
                    self._ineffective_compression_count,
                )
                return None
        else:
            self._ineffective_compression_count = 0

        logger.info(
            "[ContextWindow] AutoCompact: %d → %d tokens (节省%.0f%%, 保护区从 idx %d 起, %s)",
            estimated, new_estimated, savings_ratio * 100, tail_start,
            "迭代更新" if self._previous_summary else "首次生成",
        )
        return {"messages": new_messages}

    def _generate_structured_summary(
        self, conversation_text: str, focus_instruction: str
    ) -> str | None:
        """Phase 2 + 3: 生成/更新结构化摘要

        如果存在 _previous_summary（Phase 3 迭代更新）:
          使用 ITERATIVE_SUMMARY_PROMPT + 上次摘要 + 新增对话

        如果不存在（首次压缩）:
          使用 STRUCTURED_SUMMARY_PROMPT + 完整对话

        返回: 结构化摘要文本，或 None（LLM 不可用/失败时）
        """
        llm = self._get_auxiliary_llm()
        if not llm:
            return None

        try:
            from langchain_core.messages import HumanMessage as HM

            if self._previous_summary:
                # Phase 3: 迭代更新 — 传入上次摘要 + 新增对话
                prompt = ITERATIVE_SUMMARY_PROMPT.format(
                    previous_summary=self._previous_summary,
                    new_conversation=conversation_text[:6000],
                    focus_topic_instruction=focus_instruction,
                )
            else:
                # Phase 2: 首次生成 — 完整对话 → 结构化摘要
                prompt = STRUCTURED_SUMMARY_PROMPT.format(
                    conversation=conversation_text[:8000],
                    focus_topic_instruction=focus_instruction,
                )

            # §4.3 注入锚点到摘要 prompt
            prompt = self._skill_anchors.inject_into_summary_prompt(prompt)

            # LLM 调用：优先使用同步 invoke（before_model 是同步方法）
            # LangChain 的 ChatOpenAI 同时支持 invoke（同步）和 ainvoke（异步）
            resp = llm.invoke([HM(content=prompt)])

            summary = resp.content[:4000]  # 限制摘要长度

            # Phase 3: 存储为 _previous_summary（跨压缩周期保持）
            self._previous_summary = summary

            logger.info(
                "[ContextWindow] LLM 结构化摘要生成成功 (%d 字符, %s)",
                len(summary), "迭代更新" if self._previous_summary else "首次",
            )
            return summary

        except Exception as e:
            logger.warning("[ContextWindow] LLM 结构化摘要失败: %s, 降级到行级截断", e)
            return None

    def _fallback_line_summary(self, to_summarize: list) -> str:
        """LLM 不可用时的 fallback：行级截断拼接（零 LLM 成本，向后兼容）"""
        parts = []
        for msg in to_summarize[-12:]:
            content = getattr(msg, "content", "")
            if not isinstance(content, str) or not content.strip():
                continue
            role = getattr(msg, "type", "unknown")
            max_len = 300 if role in ("human", "ai") else 150
            truncated = content[:max_len] + ("..." if len(content) > max_len else "")
            parts.append(f"[{role}] {truncated}")

        if not parts:
            return "[历史摘要] 无有效内容"
        return "[历史摘要 — LLM 不可用，行级截断]\n" + "\n".join(parts)

    def _format_messages_for_summary(self, messages: list) -> str:
        """将消息列表格式化为带 turn_id 标注的对话文本（供 LLM 摘要使用）

        输出格式示例:
          === turn:1 ===
          用户: 帮我查一下 PT Sentosa
          助手: [调用工具: query_data] 
          工具结果(query_data): 返回3条记录...
          助手: PT Sentosa 是一家制造业公司...

          === turn:2 ===
          用户: 生成报价方案
          ...
        """
        parts = []
        current_turn = 0
        turn_started = False

        for msg in messages:
            content = getattr(msg, "content", "")
            if not isinstance(content, str) or not content.strip():
                continue
            role = getattr(msg, "type", "unknown")

            if role == "system":
                continue  # 跳过 system 消息
            elif role == "human":
                # 新轮次开始
                current_turn += 1
                turn_started = True
                parts.append(f"\n=== turn:{current_turn} ===")
                parts.append(f"用户: {content[:500]}")
            elif role == "ai":
                if not turn_started:
                    # 没有 HumanMessage 开头的消息（可能是 Skill 内部）
                    if not current_turn:
                        current_turn = 1
                        parts.append(f"\n=== turn:{current_turn} ===")
                        turn_started = True

                # AI 消息可能包含 tool_calls
                tool_calls = getattr(msg, "tool_calls", None)
                if tool_calls:
                    tc_names = [tc.get("name", "?") for tc in tool_calls]
                    parts.append(f"助手: [调用工具: {', '.join(tc_names)}] {content[:200]}")
                elif content.strip():
                    parts.append(f"助手: {content[:500]}")
            elif role == "tool":
                tool_name = getattr(msg, "name", "") or ""
                parts.append(f"工具结果({tool_name}): {content[:300]}")

        # 记录总轮次数供存档使用
        self._last_format_turn_count = current_turn
        return "\n".join(parts)

    def _build_focus_topic_instruction(self) -> str:
        """Phase 4: 构建 Focus Topic 指令（从当前 Skill 推断压缩焦点）

        对齐 Hermes 的 /compress <topic> 命令，但改为自动推断:
        - 从最近执行的 Skill 名称推断 topic
        - 相关内容分配 60-70% 摘要 token 预算
        """
        if not self._current_focus_topic:
            return ""
        return (
            f"\n## Focus Topic 引导\n"
            f"当前任务焦点: {self._current_focus_topic}\n"
            f"请将 60-70% 的摘要篇幅分配给与 '{self._current_focus_topic}' 相关的内容。\n"
            f"不相关的内容更激进地压缩（一行摘要或省略）。\n"
        )

    def update_focus_topic(self, topic: str | None) -> None:
        """外部更新 Focus Topic（由 SkillMiddleware 在 Skill 开始执行时调用）

        典型映射:
          Skill="报价谈判" → topic="报价/金额/折扣/竞品定价"
          Skill="客户拜访准备" → topic="客户画像/商机/联系人/竞品"
          Skill="竞品调研" → topic="竞品/定价/市场份额/优劣势"
        """
        self._current_focus_topic = topic
        if topic:
            logger.info("[ContextWindow] Focus Topic 更新: %s", topic)

    # ═══════════════════════════════════════════════════════════
    # Pass 3: FullCompact — LLM 全量压缩 + Skill 边界感知 + 锚点注入
    # 对齐 Hermes Phase 4 (Full Compact) + Claude Code FullCompact
    # ═══════════════════════════════════════════════════════════

    def _full_compact(self, messages: list, estimated: int) -> dict[str, Any] | None:
        """全量压缩 — LLM 结构化摘要 + 保留 system + head 保护区 + 尾部保护区 + 锚点

        与 AutoCompact 的区别:
          - AutoCompact 保护区 4 条，FullCompact 保护区 8 条（更多最近上下文）
          - FullCompact 对中间区全部消息做摘要（不限 12 条）
          - FullCompact 强制迭代更新（即使首次也用上次 AutoCompact 的 _previous_summary）
          - FullCompact 重注入最近 3 个 tool_results（对齐 Claude Code 压缩后文件重注入）

        分区模型:
          - Head 保护区: SystemMessage + 第一条 HumanMessage（全局指令/身份信息）
          - 压缩区: head_end ... tail_start（全部送入 LLM 摘要）
          - 尾部保护区: tail_start ... 末尾（当前轮次 + Skill 边界保护）

        保护区: max(当前轮次, Skill 边界, 基础 keep_recent=8)
        §4.3 增强: 锚点注入确保关键数据不丢
        """
        new_messages = []
        recent_tool_results = []
        recent_human = None

        # ── Head 保护区: SystemMessage + 第一条 HumanMessage ──
        # 第一条 HumanMessage 通常包含用户的全局指令（如"用英文回答""我是客户经理张三"等）
        # 这些信息一旦丢失，后续交互可能出现角色/语言/风格偏差
        head_end = 0
        first_human_found = False
        for i, msg in enumerate(messages):
            role = getattr(msg, "type", "unknown")
            if role == "system":
                new_messages.append(msg)
                head_end = i + 1
            elif isinstance(msg, HumanMessage) and not first_human_found:
                new_messages.append(msg)
                first_human_found = True
                head_end = i + 1
                break
            else:
                break

        # ── 尾部保护区计算 ──
        base_keep = 8
        current_turn_start = self._find_current_turn_start(messages)
        skill_tail_start = self._skill_tail_protection.compute_tail_start(
            messages, keep_recent=base_keep, head_end=head_end,
        )
        tail_start = min(current_turn_start, skill_tail_start)
        tail_start = align_boundary_deep(messages, tail_start)

        # 确保 tail_start 不小于 head_end（避免保护区重叠）
        tail_start = max(tail_start, head_end)

        # 保护区内提取最近的 tool results 和 human message（用于重注入）
        for msg in reversed(messages[tail_start:]):
            if isinstance(msg, ToolMessage) and len(recent_tool_results) < 3:
                recent_tool_results.append(msg)
            elif isinstance(msg, HumanMessage) and recent_human is None:
                recent_human = msg

        # ── 压缩区: head_end ... tail_start ──
        to_summarize = []
        for msg in messages[head_end:tail_start]:
            content = getattr(msg, "content", "")
            if not isinstance(content, str):
                continue
            to_summarize.append(msg)

        # *** 压缩前存档: 将即将被压缩的消息建立索引（供 recall_context 恢复）***
        if self._current_thread_id and to_summarize:
            self._archive.index_messages(to_summarize, self._current_thread_id, base_msg_index=head_end)

        # 尝试 LLM 结构化摘要
        conversation_text = self._format_messages_for_summary(to_summarize)
        focus_instruction = self._build_focus_topic_instruction()

        if conversation_text.strip():
            summary = self._generate_structured_summary(
                conversation_text, focus_instruction
            )
            if summary:
                compact_summary = SUMMARY_PREFIX + summary
            else:
                # LLM 失败 — fallback 到截断式摘要
                summary_parts = []
                for msg in to_summarize[-20:]:
                    content = getattr(msg, "content", "")
                    if isinstance(content, str) and content.strip():
                        role = getattr(msg, "type", "unknown")
                        summary_parts.append(f"[{role}] {content[:100]}")
                compact_summary = "[全量压缩摘要 — LLM 不可用]\n" + "\n".join(summary_parts)

            # §4.3 注入 Skill 锚点到全量压缩摘要中
            anchor_summary = self._skill_anchors.get_anchor_summary()
            if anchor_summary:
                compact_summary += "\n\n" + anchor_summary

            new_messages.append(SystemMessage(content=compact_summary))

        # 重注入最近的 tool_calls + results（对齐 Claude Code 压缩后文件重注入）
        if recent_tool_results:
            tool_calls = []
            for tm in recent_tool_results:
                tc_id = getattr(tm, "tool_call_id", "")
                tc_name = getattr(tm, "name", "") or "tool"
                tool_calls.append({"id": tc_id, "name": tc_name, "args": {}})
            if tool_calls:
                new_messages.append(AIMessage(content="", tool_calls=tool_calls))
                new_messages.extend(reversed(recent_tool_results))
        if recent_human:
            new_messages.append(recent_human)

        new_estimated = _estimate_tokens(new_messages)
        logger.info("[ContextWindow] FullCompact: %d → %d tokens (Skill边界感知, 锚点%d个)",
                    estimated, new_estimated, self._skill_anchors.anchor_count)
        return {"messages": new_messages}

    # ═══════════════════════════════════════════════════════════
    # Tracing
    # ═══════════════════════════════════════════════════════════

    def _record_compact_span(self, tool_name: str, original_len: int, summary_len: int,
                             skipped: bool = False,
                             original_content: str = "", summary_content: str = "",
                             tool_call_id: str = "") -> None:
        """记录源头压缩 span（含原文和压缩后内容）

        注意：此方法在 awrap_tool_call 中调用，即工具执行完成后立即记录。
        compact span 属于当前循环的工具执行阶段（不是下一个循环的 before_model）。
        通过 _iter_count 标记所属循环，供前端正确归组。
        """
        try:
            from src.middleware.tracing import tracing_middleware
            config = TOOL_THRESHOLDS.get(tool_name, DEFAULT_TOOL_THRESHOLD)
            # 获取当前循环编号（与 TracingMiddleware 的 _iter_count 一致）
            tid = tracing_middleware._tid()
            current_iteration = tracing_middleware._iter_count.get(tid, 0)

            if skipped:
                tracing_middleware._add("tool_result_compact", f"compact:{tool_name}", 0,
                    metadata={"tool_name": tool_name, "tool_call_id": tool_call_id,
                              "iteration": current_iteration},
                    input_data={"tool_name": tool_name, "content_length": original_len,
                                "threshold": config["threshold"],
                                "tool_call_id": tool_call_id,
                                "iteration": current_iteration},
                    output_data={"action": "skip", "reason": f"未超阈值({original_len}/{config['threshold']})"},
                    detail=f"上下文检查: {tool_name} {original_len}字符 ≤ 阈值{config['threshold']} → 保留原文",
                )
            else:
                ratio = round(1 - summary_len / max(original_len, 1), 2)
                tracing_middleware._add("tool_result_compact", f"compact:{tool_name}", 0,
                    metadata={"tool_name": tool_name, "tool_call_id": tool_call_id,
                              "iteration": current_iteration},
                    input_data={
                        "tool_name": tool_name,
                        "original_length": original_len,
                        "threshold": config["threshold"],
                        "original_content": original_content[:2000],
                        "tool_call_id": tool_call_id,
                        "iteration": current_iteration,
                    },
                    output_data={
                        "summary_length": summary_len,
                        "compression_ratio": f"{ratio:.0%}",
                        "action": "compressed",
                        "summary_content": summary_content[:500],
                    },
                    detail=f"源头压缩: {tool_name} {original_len}→{summary_len}字符 (节省{ratio:.0%})",
                )
        except Exception:
            logger.exception("[ContextWindow] _record_compact_span 异常")

    def _record_window_span(
        self, messages_count: int, estimated_tokens: int,
        action: str, reason: str,
        compressed_tokens: int = 0, messages_after: int = 0,
        messages_before: list | None = None, messages_result: list | None = None,
    ) -> None:
        """记录窗口管理 span（覆盖 MiddlewareTracingWrapper 的通用 span）"""
        try:
            from src.middleware.tracing import tracing_middleware
            has_effect = action not in ("none", "skip", "circuit_break")
            detail = f"{'✅ ' + action if has_effect else '⏭️ 无需压缩'}: {reason}"
            if has_effect:
                detail += f" → {estimated_tokens}→{compressed_tokens} tokens"

            # 构建上下文消息预览
            input_messages_preview = []
            if messages_before:
                for m in messages_before[-15:]:
                    m_type = getattr(m, "type", "unknown")
                    m_content = getattr(m, "content", "")
                    if not isinstance(m_content, str):
                        m_content = str(m_content)[:500]
                    input_messages_preview.append({"role": m_type, "content": m_content[:500]})

            output_messages_preview = []
            if has_effect and messages_result:
                for m in messages_result[-10:]:
                    m_type = getattr(m, "type", "unknown")
                    m_content = getattr(m, "content", "")
                    if not isinstance(m_content, str):
                        m_content = str(m_content)[:500]
                    output_messages_preview.append({"role": m_type, "content": m_content[:500]})

            tid = None
            try:
                from langgraph.config import get_config
                tid = get_config().get("configurable", {}).get("thread_id")
            except Exception:
                pass  # 非 runnable context 中无法获取 thread_id，跳过 tracing

            if tid:
                tracing_middleware._spans.setdefault(tid, [])
                # 覆盖 MiddlewareTracingWrapper 记录的通用 span
                for i in range(len(tracing_middleware._spans[tid]) - 1, -1, -1):
                    s = tracing_middleware._spans[tid][i]
                    if (s.get("type") == "middleware"
                            and s.get("metadata", {}).get("middleware_name") == "ContextWindowMiddleware"
                            and s.get("metadata", {}).get("phase") == "before_model"):
                        s["input_data"] = {
                            "messages_count": messages_count,
                            "estimated_tokens": estimated_tokens,
                            "thresholds": {"micro": self._micro_trigger, "auto": self._auto_trigger, "full": self._full_trigger},
                            "context_messages": input_messages_preview,
                        }
                        s["output_data"] = {
                            "action": action, "has_effect": has_effect, "reason": reason,
                            "compressed_tokens": compressed_tokens, "messages_after": messages_after,
                            "compressed_messages": output_messages_preview if has_effect else [],
                        }
                        s["detail"] = detail
                        break
        except Exception:
            logger.exception("[ContextWindow] _record_window_span 异常")

    def reset_circuit_breaker(self) -> None:
        self._consecutive_failures = 0
        self._ineffective_compression_count = 0

    def reset_session(self) -> None:
        """会话结束时重置所有会话级状态"""
        self._consecutive_failures = 0
        self._ineffective_compression_count = 0
        self._previous_summary = None
        self._current_focus_topic = None
        self._skill_anchors.clear()
        self._archive.clear()
        self._current_thread_id = ""

    @property
    def archive(self) -> ContextArchive:
        """供 RecallContextTool 访问的压缩存档索引"""
        return self._archive


# ═══════════════════════════════════════════════════════════
# 源头压缩：代码格式化提取（零 LLM 成本）
# ═══════════════════════════════════════════════════════════

def _try_code_extract(tool_name: str, content: str) -> str | None:
    """尝试用代码规则提取摘要"""
    stripped = content.strip()
    if stripped.startswith("{") or stripped.startswith("["):
        try:
            data = json.loads(stripped)
            return _extract_from_json(tool_name, data)
        except json.JSONDecodeError:
            pass

    if tool_name == "web_search":
        lines = content.split("\n")
        meaningful = [l.strip() for l in lines if l.strip() and 20 < len(l.strip()) <= 200][:3]
        if meaningful:
            return f"[web_search] ({len(content)}字符)\n" + "\n".join(meaningful)
        # 单行长文本（无换行符）→ 取前 200 字符
        return f"[web_search] ({len(content)}字符)\n{content[:200]}..."

    # 通用: 保留前 200 字符 + 元信息
    if len(content) > 500:
        return f"[{tool_name}] ({len(content)}字符, {content.count(chr(10))+1}行)\n{content[:200]}..."

    return None


def _extract_from_json(tool_name: str, data: Any) -> str | None:
    """从 JSON 数据提取摘要"""
    if isinstance(data, dict) and "records" in data:
        records = data["records"]
        if isinstance(records, list):
            count = len(records)
            names = [str(r.get("name", r.get("subject", r.get("id", ""))))
                     for r in records[:5]]
            names_str = ", ".join(n for n in names if n)
            extra = f"...等{count}条" if count > 5 else ""
            amounts = [r.get("amount", 0) for r in records if r.get("amount")]
            # 金额直接求和，不假设单位（CRM 数据可能是美元/人民币/卢比等）
            amount_str = f", 总金额{sum(float(a) for a in amounts):,.0f}" if amounts else ""
            return f"查询返回{count}条记录: {names_str}{extra}{amount_str}"

    if isinstance(data, dict) and "records" not in data:
        key_fields = ["name", "id", "industry", "city", "amount", "stage",
                      "status", "probability", "title", "type"]
        parts = [f"{k}={data[k]}" for k in key_fields if k in data and data[k]]
        if parts:
            return f"记录: {', '.join(str(p) for p in parts[:8])}"

    if isinstance(data, list):
        count = len(data)
        if count > 0 and isinstance(data[0], dict):
            names = [str(r.get("name", r.get("title", ""))) for r in data[:5]]
            return f"返回{count}条: {', '.join(n for n in names if n)}"
        return f"返回{count}项数据"

    return None


def _crm_tool_summary(msg: ToolMessage) -> str:
    """CRM 工具专用一行摘要（用于 MicroCompact 替换旧 ToolMessage）"""
    content = msg.content if isinstance(msg.content, str) else str(msg.content)
    tool_name = getattr(msg, "name", "") or ""

    # JSON 数据提取
    stripped = content.strip()
    if stripped.startswith("{") or stripped.startswith("["):
        try:
            data = json.loads(stripped)
            extracted = _extract_from_json(tool_name, data)
            if extracted:
                return extracted
        except json.JSONDecodeError:
            pass

    # 通用：保留前 100 字符
    preview = content[:100].replace("\n", " ")
    return f"[{tool_name or 'tool'}] {preview}... ({len(content)}字符)"


def _fallback_truncate(tool_name: str, content: str, max_chars: int) -> str:
    """兜底截断（保留 max_chars*2 字符，给后续阅读留足上下文）"""
    preview = content[:max_chars * 2]
    return f"[{tool_name}] {preview}...\n[已截断, 原文{len(content)}字符]"


# 向后兼容别名
SummarizationMiddleware = ContextWindowMiddleware
