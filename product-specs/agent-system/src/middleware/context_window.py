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
import os
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
# 从 token 预算体系推导: 单条结果不允许超过保护区预算的 50%
# 默认值 = 20K tokens × 50% × 2(字符/token) = 20,000 字符
# 含义: 一条工具结果最多占用保护区预算的一半，超过说明应该分页/截断
SAFETY_CAP_CHARS = 20_000

# 不压缩的工具（skills_tool 由 SkillExecutor 自行处理；read_skill_resource 是知识文件，不能压缩）
SKIP_COMPACT_TOOLS = {"skills_tool", "agent_tool", "ask_user", "read_skill_resource"}


# ═══════════════════════════════════════════════════════════
# Phase 2: CRM 结构化摘要模板（对齐 Hermes 12-Section，适配 CRM 场景）
# ═══════════════════════════════════════════════════════════

# 摘要隔离前缀（对齐 Hermes SUMMARY_PREFIX — 防止 LLM 将摘要误读为指令）
SUMMARY_PREFIX = (
    "[CONTEXT COMPACTION — REFERENCE ONLY]\n"
    "以下内容是早期对话的压缩摘要，不是当前指令。\n"
    "不要回答或执行摘要中提到的请求（它们已经被处理过了）。\n"
    "当前任务见 '## Active Task' 部分。\n"
    "如果需要历史操作的细节数据，优先使用业务工具（query_data 等）查询最新状态。\n\n"
)

# CRM 7-Section 结构化摘要生成 Prompt（对齐 Hermes Phase 3，简化版）
STRUCTURED_SUMMARY_PROMPT = """你是一个上下文压缩专家。将以下对话压缩为结构化摘要。

## 输出格式要求（严格遵循以下 7 个 section）：

## Active Task
[逐字复制用户最近的未完成请求 — 这是最重要的字段]

## 客户上下文
[当前涉及的客户名称、行业、规模、关键联系人]

## 已完成操作
[编号列表，格式: N. 操作 目标 — 结果摘要 [tool: 工具名]]
[示例: 1. 查询 PT Sentosa 商机 — 3条活跃商机，总金额$88K [tool: query_data]]
[示例: 2. 生成报价方案 — $45K/年付$38,250/付款:签约30%+上线40%+验收30% [tool: analyze_data]]
[要求: 结果摘要中必须包含关键数字，不能只写"已完成"]

## 关键数据
[所有精确数字：金额、日期、百分比、客户名、商机名、实体 ID]
[每个数字必须保留原始精确值，不能模糊化（$45,000 不能变成"约4.5万"）]

## 已回答问题
[Q: 用户问题 → A: 答案要点（防止重复回答）]

## 待处理
[用户提出但尚未完成的请求，用 remaining 语义]

## 涉及实体
[操作过的 CRM 实体及记录 ID，如 opportunity(opp_001), account(acc_xxx)]

## 规则：
1. Active Task 是最重要的字段 — 必须逐字复制用户最近的未完成请求
2. 关键数据中的数字必须精确保留，不能模糊化
3. 已完成操作的结果摘要必须包含关键结论和数字（付款条件、金额、折扣等）
4. "待处理"用 remaining 语义，不是 next steps（避免被误读为指令）
5. 摘要总长度控制在 1500 字以内

{focus_topic_instruction}

## 待压缩的对话内容：
{conversation}
"""

# Phase 3: 迭代摘要更新 Prompt（对齐 Hermes 的 PRESERVE/ADD/MOVE/UPDATE 策略）
ITERATIVE_SUMMARY_PROMPT = """你是一个上下文压缩专家。基于上次摘要和新增对话，更新结构化摘要。

## 更新规则（严格遵循）：
- PRESERVE: 保留上次摘要中所有仍然相关的信息
- ADD: 将新完成的操作添加到"已完成操作"列表（继续编号）
- MOVE: 已完成的项从"待处理"移到"已完成操作"
- MOVE: 已回答的问题添加到"已回答问题"
- UPDATE: 更新"Active Task"为用户最近的未完成请求
- UPDATE: 更新"关键数据"中的新发现数字
- CRITICAL: Active Task 必须反映用户最新的未完成请求
- CRITICAL: 关键数据中的精确数字必须保留，不能模糊化
- EVICT: 当摘要超过 1200 字时，"已回答问题"只保留最近 3 条，"已完成操作"中纯查询操作可合并为一行

## 上次摘要：
{previous_summary}

## 新增对话内容：
{new_conversation}

{focus_topic_instruction}

## 输出格式（严格遵循 7 个 section）：
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

    wrap_tool_call: CompressionEngine 即时压缩 + 安全网截断 + Skill 锚点提取
    before_model:  Post-Skill Compact + MD5 去重 + 阈值触发压缩
                   （MicroCompact / AutoCompact / FullCompact）

    统一压缩引擎集成（CompressionEngine）：
    - wrap_tool_call 阶段：工具返回结果即时做内容块压缩（level=LIGHT）
    - MicroCompact 阶段：历史 ToolMessage 精细压缩（level=STANDARD）
    - AutoCompact/FullCompact 阶段：先预压缩再送 LLM 摘要（level=STANDARD）
    - 降级策略：CompressionEngine 不可用时自动降级为 CRM 规则摘要
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
        post_skill_compact_token_budget: int = 4000,
        # 安全网参数（None = 从 token 预算自动推导）
        safety_cap_chars: int | None = None,
        # Token 预算参数（对齐 Hermes _find_tail_cut_by_tokens）
        tail_token_budget_ratio: float = 0.20,
        # ── Headroom 压缩引擎参数 ──
        headroom_enabled: bool = True,
        headroom_min_chars: int = 500,
        headroom_max_ratio: float = 0.85,
        headroom_in_wrap: bool = True,
        headroom_in_micro: bool = True,
        headroom_in_auto_precompress: bool = True,
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

        # Token 预算：尾部保护区最多占 max_tokens 的 ratio 比例
        # 例如 max_tokens=100K, ratio=0.20 → 预算 20K tokens
        self._tail_token_budget = int(max_tokens * tail_token_budget_ratio)

        # 安全网阈值: 从 token 预算体系推导
        # 公式: 保护区 token 预算 × 50% × 2(字符/token)
        # 含义: 单条工具结果最多占用保护区预算的一半
        if safety_cap_chars is not None:
            self._safety_cap = safety_cap_chars
        else:
            self._safety_cap = int(self._tail_token_budget * 0.5 * 2)

        # ── 统一压缩引擎（CompressionEngine 单例）──
        self._headroom_enabled = headroom_enabled and os.environ.get("HEADROOM_ENABLED", "1") != "0"
        self._headroom_min_chars = headroom_min_chars
        self._headroom_max_ratio = headroom_max_ratio
        self._headroom_in_wrap = headroom_in_wrap
        self._headroom_in_micro = headroom_in_micro
        self._headroom_in_auto_precompress = headroom_in_auto_precompress
        self._compression_engine = None  # 延迟初始化

        if self._headroom_enabled:
            try:
                from src.middleware.compression_engine import CompressionEngine
                self._compression_engine = CompressionEngine.get_instance()
                logger.info(
                    "[ContextWindow] 统一压缩引擎已启用 "
                    "(wrap=%s, micro=%s, auto_precompress=%s, min_chars=%d, max_ratio=%.2f)",
                    headroom_in_wrap, headroom_in_micro, headroom_in_auto_precompress,
                    headroom_min_chars, headroom_max_ratio,
                )
            except Exception as e:
                logger.warning("[ContextWindow] CompressionEngine 加载失败: %s", e)
                self._compression_engine = None

        # 真实 token 跟踪（由 LLM 响应后通过 update_real_tokens 回填）
        self._last_real_prompt_tokens: int = 0
        # 本轮累计 token（用于前端展示）
        self._turn_input_tokens: int = 0
        self._turn_output_tokens: int = 0
        self._turn_llm_calls: int = 0
        # 最后一次压缩是否触发（用于前端展示）
        self._last_compression_triggered: bool = False

        # §4.1 Skill 边界感知尾部保护
        self._skill_tail_protection = SkillAwareTailProtection(
            min_tail_messages=skill_min_tail,
            max_tail_messages=skill_max_tail,
        )
        # §4.3 Skill 结果锚点（session 级别，跨多轮压缩持久）
        self._skill_anchors = SkillResultAnchor()
        # §4.4 Post-Skill Compact 阈值
        self._post_skill_compact_threshold = post_skill_compact_threshold
        self._post_skill_compact_token_budget = post_skill_compact_token_budget

        # Phase 3: 迭代摘要状态（对齐 Hermes self._previous_summary）
        self._previous_summary: str | None = None
        # Phase 4: 自动 Focus Topic（从最近执行的 Skill 推断）
        self._current_focus_topic: str | None = None
        # 反抖动：连续低效压缩计数（对齐 Hermes _ineffective_compression_count）
        self._ineffective_compression_count: int = 0
        # 格式化时记录的轮次数（供存档使用）
        self._last_format_turn_count: int = 0
        # 压缩存档索引（供 recall_context 工具检索恢复原文）
        self._archive = ContextArchive()
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

        content = getattr(result, "content", "")
        if not isinstance(content, str):
            content = str(content)

        # ── 统一压缩引擎即时压缩（在安全网之前执行）──
        # 对当前轮次的超大工具输出做结构保留式压缩
        # SmartCrusher 处理 JSON、CodeCompressor 处理代码、LogCompressor 处理日志等
        if (self._compression_engine and self._headroom_in_wrap
                and len(content) >= self._headroom_min_chars):
            from src.middleware.compression_engine import CompressLevel
            cr = self._compression_engine.compress(
                content=content,
                tool_name=tool_name,
                context=self._get_current_user_query(),
                level=CompressLevel.LIGHT,
            )
            if cr.ratio < self._headroom_max_ratio:
                original_len = len(content)
                result.content = cr.content
                content = cr.content  # 更新 content 供后续安全网检查
                self._record_headroom_span(
                    tool_name, original_len, cr.compressed_chars, cr.ratio, tool_call_id
                )

        # ── 安全网: Headroom 压缩后仍超上限时做紧急截断 ──
        if len(content) > self._safety_cap:
            original_len = len(content)
            # 超大结果: 代码提取摘要 → 截断兜底
            summary = _try_code_extract(tool_name, content)
            if not summary:
                summary = _fallback_truncate(tool_name, content, self._safety_cap // 10)
            result.content = summary
            logger.warning(
                "[ContextWindow] 安全网截断 %s: %d→%d chars (原文超过 token 预算推导上限 %d，"
                "即保护区预算 %d tokens 的 50%%)",
                tool_name, original_len, len(summary), self._safety_cap,
                self._tail_token_budget,
            )
            self._record_compact_span(tool_name, original_len, len(summary),
                                      original_content=content[:2000],
                                      summary_content=summary,
                                      tool_call_id=tool_call_id)

        return result

    def _get_current_user_query(self) -> str:
        """获取当前用户问题（用于 Headroom 相关性评分）

        从 LangGraph configurable 或 tracing 中获取，降级返回空字符串。
        """
        try:
            from langgraph.config import get_config
            config = get_config()
            # 优先从 configurable 中获取（由入口层设置）
            query = config.get("configurable", {}).get("current_query", "")
            if query:
                return query
        except Exception:
            pass
        return ""

    def _record_headroom_span(
        self, tool_name: str, original_len: int, compressed_len: int,
        ratio: float, tool_call_id: str = "",
    ) -> None:
        """记录 Headroom 压缩 tracing span"""
        try:
            from src.middleware.tracing import tracing_middleware
            tid = tracing_middleware._tid()
            current_iteration = tracing_middleware._iter_count.get(tid, 0)
            savings_pct = round((1 - ratio) * 100, 1)

            tracing_middleware._add(
                "headroom_compress", f"headroom:{tool_name}", 0,
                metadata={
                    "tool_name": tool_name,
                    "tool_call_id": tool_call_id,
                    "iteration": current_iteration,
                },
                input_data={
                    "tool_name": tool_name,
                    "original_chars": original_len,
                    "tool_call_id": tool_call_id,
                    "iteration": current_iteration,
                },
                output_data={
                    "compressed_chars": compressed_len,
                    "compression_ratio": f"{ratio:.2f}",
                    "savings_pct": f"{savings_pct}%",
                    "action": "headroom_compressed",
                },
                detail=(
                    f"Headroom 压缩: {tool_name} "
                    f"{original_len}→{compressed_len} chars (节省 {savings_pct}%)"
                ),
            )
        except Exception:
            pass  # tracing 失败不影响主流程

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

        # 获取当前用户问题（传给 LLMLingua-2 做密度检测和上下文信号）
        user_query = self._get_current_user_query()

        # 从后向前压缩，避免 index 偏移
        for start_idx, end_idx in reversed(boundaries):
            skill_msg_count = end_idx - start_idx + 1
            # 估算 Skill 内部 token（2 字符/token）
            skill_tokens = sum(
                len(getattr(m, "content", "") or "") // 2
                for m in messages[start_idx:end_idx + 1]
            )
            # 双条件触发：条数超阈值 OR token 超预算
            if (skill_msg_count > self._post_skill_compact_threshold
                    or skill_tokens > self._post_skill_compact_token_budget):
                messages = post_skill_compact(
                    messages, start_idx, end_idx,
                    min_skill_messages=self._post_skill_compact_threshold,
                    max_skill_tokens=self._post_skill_compact_token_budget,
                    user_query=user_query,
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

    def update_real_tokens(self, input_tokens: int, output_tokens: int = 0) -> None:
        """由外部（AGUIConverter / TracingMiddleware）在 LLM 响应后回填真实 token 数

        解决问题: _estimate_tokens 的 2 字符/token 估算有 ±30% 误差，
        使用 LLM 响应中的 usage_metadata.input_tokens 可精确触发压缩。

        Args:
            input_tokens: LLM 实际消耗的 prompt tokens（用于压缩阈值判断）
            output_tokens: LLM 输出 tokens（仅用于前端展示统计）
        """
        if input_tokens > 0:
            self._last_real_prompt_tokens = input_tokens
        # 累计本轮用量（用于 get_usage_summary）
        self._turn_input_tokens += input_tokens
        self._turn_output_tokens += output_tokens
        self._turn_llm_calls += 1

    def reset_turn_usage(self) -> None:
        """重置本轮用量统计（在每轮对话开始时由 Adapter 调用）"""
        self._turn_input_tokens = 0
        self._turn_output_tokens = 0
        self._turn_llm_calls = 0
        self._last_compression_triggered = False

    def get_usage_summary(self) -> dict[str, Any]:
        """获取本轮 Token 用量摘要（用于前端 usage_summary 事件推送）

        Returns:
            {
                "input_tokens": 总输入 token,
                "output_tokens": 总输出 token,
                "total_tokens": 总 token,
                "llm_calls": LLM 调用次数,
                "context_window": {
                    "max_tokens": 上下文窗口上限,
                    "estimated_used": 当前估算使用量,
                    "usage_percent": 使用百分比,
                    "tail_budget": 尾部预算 token 数,
                    "compression_triggered": 本轮是否触发了压缩,
                },
            }
        """
        # 使用最近一次真实值或估算值
        current_used = self._turn_input_tokens if self._turn_input_tokens > 0 else 0
        usage_pct = round(current_used / max(self._max_tokens, 1) * 100, 1)

        return {
            "input_tokens": self._turn_input_tokens,
            "output_tokens": self._turn_output_tokens,
            "total_tokens": self._turn_input_tokens + self._turn_output_tokens,
            "llm_calls": self._turn_llm_calls,
            "context_window": {
                "max_tokens": self._max_tokens,
                "estimated_used": current_used,
                "usage_percent": usage_pct,
                "tail_budget": self._tail_token_budget,
                "compression_triggered": self._last_compression_triggered,
            },
        }

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
    # 系统级自动注入：检测回溯信号 → 从存档恢复相关历史细节
    # 替代 recall_context 工具（不依赖 LLM 自主判断）
    # 检索策略: 向量语义 + BM25 混合检索（复用 VikingMemoryEngine 基础设施）
    # ═══════════════════════════════════════════════════════════

    # 回溯信号词（用户追问历史内容的语言模式）
    _RETROSPECT_SIGNALS = (
        "之前", "刚才", "上面", "前面", "earlier", "之前说的", "刚刚",
        "那个", "那次", "上次", "回顾", "回看",
        "具体", "详细", "细节", "完整", "原文",
        "怎么写的", "怎么说的", "什么条件", "什么方案",
        "付款条件", "报价方案", "合同条款",
    )

    def _auto_inject_archived_context(self, messages: list) -> dict[str, Any] | None:
        """系统级自动注入 — 检测用户是否在追问被压缩的历史内容

        检索策略（双路并行）:
          1. 向量语义检索: 将用户问题 embed → 在存档向量索引中做 cosine 相似度
          2. BM25 关键词检索: 对用户问题做 BM25 稀疏编码 → 关键词精确匹配
          3. 加权融合: dense_weight=0.3, sparse_weight=0.7（CRM 场景关键词更可靠）
          4. 降级: 向量库不可用时 fallback 到 PG ILIKE 检索

        触发条件（任一满足）:
          1. 当前问题包含回溯信号词（"之前""具体""付款条件"等）
          2. 当前问题提及摘要中出现过的实体名

        行为:
          - 从向量库/PG 存档中搜索相关轮次
          - 将恢复的内容作为 SystemMessage 注入到当前消息前
          - LLM 直接看到原文，无需调用任何工具

        限制:
          - 每轮最多注入 1 条（避免上下文膨胀）
          - 注入内容限制在 2000 字符以内
          - 无存档时静默跳过
        """
        if not self._archive or not self._archive.has_entries():
            return None

        # 获取当前用户问题
        current_query = ""
        for msg in reversed(messages):
            if isinstance(msg, HumanMessage):
                current_query = msg.content if isinstance(msg.content, str) else str(msg.content)
                break

        if not current_query or len(current_query) < 4:
            return None

        # 检测回溯信号
        if not self._has_retrospect_signal(current_query):
            return None

        # 优先使用向量+BM25混合检索，降级到PG关键词检索
        try:
            matched = self._archive.hybrid_search(current_query, top_k=1)
        except Exception as e:
            logger.debug("[AutoInject] 检索失败: %s", e)
            return None

        if not matched:
            return None

        entry = matched[0]

        # 格式化恢复内容（限制长度）
        recovered = self._format_archived_for_inject(entry)
        if not recovered:
            return None

        # 构建注入消息
        inject_content = (
            "[历史细节 — 系统自动恢复]\n"
            f"以下是与当前问题相关的历史对话详情"
            f"（原始问题: {entry.user_query[:60]}）:\n\n"
            f"{recovered}"
        )

        # 插入到最后一条 HumanMessage 之前
        inject_msg = SystemMessage(content=inject_content)
        new_messages = list(messages)
        insert_idx = len(new_messages) - 1
        for i in range(len(new_messages) - 1, -1, -1):
            if isinstance(new_messages[i], HumanMessage):
                insert_idx = i
                break
        new_messages.insert(insert_idx, inject_msg)

        logger.info(
            "[AutoInject] 自动注入历史细节: query='%s' → 命中 turn %d (%d字符)",
            current_query[:40], entry.turn_id, len(recovered),
        )
        return {"messages": new_messages}

    def _has_retrospect_signal(self, query: str) -> bool:
        """检测用户问题是否包含回溯信号（追问历史的语言模式）"""
        query_lower = query.lower()
        for signal in self._RETROSPECT_SIGNALS:
            if signal in query_lower:
                return True
        return False

    def _format_archived_for_inject(self, entry) -> str | None:
        """格式化存档内容用于自动注入（限制 2000 字符）"""
        import json as _json

        if not entry.original_messages_json:
            if entry.answer_preview:
                return f"[回复摘要] {entry.answer_preview}"
            return None

        try:
            messages_data = _json.loads(entry.original_messages_json)
        except (ValueError, TypeError):
            return entry.answer_preview if entry.answer_preview else None

        parts = []
        for msg in messages_data:
            role = msg.get("role", "")
            content = msg.get("content", "")
            if not content or not content.strip():
                continue
            if role == "human":
                parts.append(f"[用户] {content[:300]}")
            elif role == "tool":
                tool_name = msg.get("name", "tool")
                parts.append(f"[工具:{tool_name}] {content[:500]}")
            elif role == "ai" and content.strip():
                parts.append(f"[助手] {content[:500]}")

        if not parts:
            return entry.answer_preview if entry.answer_preview else None

        result = "\n".join(parts)
        if len(result) > 2000:
            result = result[:2000] + "\n[...已截断]"
        return result

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

        # ═══ 系统级自动注入：检测回溯信号 → 从存档恢复相关历史 ═══
        # 不依赖 LLM 主动调 recall_context，由系统在 before_model 阶段自动完成
        auto_inject_result = self._auto_inject_archived_context(messages)
        if auto_inject_result:
            messages = auto_inject_result["messages"]

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

        # 优先使用真实 token 数（由 LLM 响应回填），消除估算 ±30% 误差
        if self._last_real_prompt_tokens > 0:
            estimated = self._last_real_prompt_tokens
            self._last_real_prompt_tokens = 0  # 消费一次

        # 重置本轮压缩状态标记
        self._last_compression_triggered = False

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
            token_budget=self._tail_token_budget,
        )

        # 取最小 index（最大保护范围）: 当前轮次 vs Skill 边界 vs 基础 keep_recent
        tail_start = min(current_turn_start, skill_tail_start)

        # §4.2 深度边界对齐 — 不在工具组中间切割
        tail_start = align_boundary_deep(messages, tail_start)

        if tail_start <= 0 or tail_start >= len(messages):
            return None

        self._last_compression_triggered = True

        old_messages = messages[:tail_start]
        recent = messages[tail_start:]
        modified = False
        compacted = []
        current_query = self._get_current_user_query()

        for msg in old_messages:
            if isinstance(msg, ToolMessage):
                content = msg.content if isinstance(msg.content, str) else str(msg.content)
                if len(content) > 200:
                    # ── 统一压缩引擎精细压缩（优先）→ 降级到 CRM 一行摘要 ──
                    compressed_content = None

                    if self._compression_engine and self._headroom_in_micro and len(content) >= self._headroom_min_chars:
                        from src.middleware.compression_engine import CompressLevel
                        cr = self._compression_engine.compress(
                            content=content,
                            tool_name=getattr(msg, "name", ""),
                            context=current_query,
                            level=CompressLevel.STANDARD,
                        )
                        if cr.ratio < 0.90:  # 有效压缩
                            compressed_content = cr.content

                    # 降级：CompressionEngine 不可用 / 内容太短 / 压缩无效 → SUMMARY_ONLY
                    if compressed_content is None:
                        from src.middleware.compression_engine import CompressLevel as _CL
                        fallback_cr = CompressionEngine.get_instance().compress(
                            content, tool_name=getattr(msg, "name", ""),
                            level=_CL.SUMMARY_ONLY,
                        )
                        compressed_content = fallback_cr.content

                    compacted.append(ToolMessage(
                        content=compressed_content,
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
            token_budget=self._tail_token_budget,
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
        # 注意：存档使用原始消息（未经预压缩），确保 recall 时可恢复完整原文
        if self._current_thread_id:
            self._archive.index_messages(to_summarize, self._current_thread_id, base_msg_index=head_end)

        # ── 统一压缩引擎预压缩：减少 LLM 摘要输入 token ──
        # 目的：降低 50-60% LLM 输入成本
        # 原始消息已存档到 VDB，预压缩仅影响 LLM 看到的文本
        if self._compression_engine and self._headroom_in_auto_precompress:
            to_summarize_for_llm = self._engine_pre_compress(to_summarize)
        else:
            to_summarize_for_llm = to_summarize

        # 将 middle 区消息格式化为对话文本（供 LLM 摘要）
        conversation_text = self._format_messages_for_summary(to_summarize_for_llm)
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
        self._last_compression_triggered = True
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

    def _engine_pre_compress(self, messages: list) -> list:
        """对消息列表中的 ToolMessage 做统一压缩引擎预压缩

        用于 AutoCompact/FullCompact 送入 LLM 摘要前，减少 LLM 输入 token。
        不修改原始消息列表（创建新列表）。

        策略：
        - 仅处理 ToolMessage（用户消息和 AI 消息保持完整送入 LLM）
        - content > 500 字符才压缩（小内容不值得）
        - 压缩失败时静默跳过（保持原文）
        """
        from src.middleware.compression_engine import CompressLevel

        result = []
        for msg in messages:
            if isinstance(msg, ToolMessage):
                content = getattr(msg, "content", "")
                if isinstance(content, str) and len(content) > 500:
                    cr = self._compression_engine.compress(
                        content=content,
                        tool_name=getattr(msg, "name", ""),
                        context="",
                        level=CompressLevel.STANDARD,
                    )
                    if cr.ratio < 0.85:
                        result.append(ToolMessage(
                            content=cr.content,
                            tool_call_id=getattr(msg, "tool_call_id", ""),
                            name=getattr(msg, "name", ""),
                        ))
                        continue
            result.append(msg)
        return result

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
            token_budget=self._tail_token_budget,
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

        # ── 统一压缩引擎预压缩（FullCompact 也适用）──
        if self._compression_engine and self._headroom_in_auto_precompress:
            to_summarize_for_llm = self._engine_pre_compress(to_summarize)
        else:
            to_summarize_for_llm = to_summarize

        # 尝试 LLM 结构化摘要
        conversation_text = self._format_messages_for_summary(to_summarize_for_llm)
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
        self._last_compression_triggered = True
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
        """压缩存档索引（供自动注入和外部访问）"""
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
    """从 JSON 数据提取结构化摘要（通用 JSON 结构处理）"""
    if isinstance(data, dict) and "records" in data:
        records = data["records"]
        if isinstance(records, list):
            count = len(records)
            names = [str(r.get("name", r.get("subject", r.get("id", ""))))
                     for r in records[:5]]
            names_str = ", ".join(n for n in names if n)
            extra = f"...等{count}条" if count > 5 else ""
            amounts = [r.get("amount", 0) for r in records if r.get("amount")]
            amount_str = (f", 总金额{sum(float(a) for a in amounts):,.0f}"
                          if amounts else "")
            stages = [r.get("stage") for r in records if r.get("stage")]
            stage_str = (f", 阶段:{'/'.join(dict.fromkeys(stages))}"
                         if stages else "")
            return (f"[{tool_name}] 查询返回{count}条: "
                    f"{names_str}{extra}{amount_str}{stage_str}")

    if isinstance(data, dict) and "records" not in data:
        key_fields = ["name", "id", "industry", "city", "amount", "stage",
                      "status", "probability", "title", "type", "owner"]
        parts = [f"{k}={data[k]}" for k in key_fields
                 if k in data and data[k]]
        if parts:
            return f"[{tool_name}] 记录: {', '.join(str(p) for p in parts[:8])}"

    if isinstance(data, list):
        count = len(data)
        if count > 0 and isinstance(data[0], dict):
            names = [str(r.get("name", r.get("title", "")))
                     for r in data[:5]]
            extra = f"...等{count}条" if count > 5 else ""
            return (f"[{tool_name}] 返回{count}条: "
                    f"{', '.join(n for n in names if n)}{extra}")
        return f"[{tool_name}] 返回{count}项数据"

    return None


def _crm_tool_summary(msg: ToolMessage) -> str:
    """CRM 工具专用摘要（对齐 Hermes _summarize_tool_result — 按工具类型分发）

    每种工具提取最有价值的信息：查询目标、结果数、关键数据点。
    格式: [tool_name] 动作 目标 → 结果摘要
    """
    content = msg.content if isinstance(msg.content, str) else str(msg.content)
    tool_name = getattr(msg, "name", "") or ""

    # 尝试 JSON 解析
    data = None
    stripped = content.strip()
    if stripped.startswith("{") or stripped.startswith("["):
        try:
            data = json.loads(stripped)
        except json.JSONDecodeError:
            pass

    # 按工具类型分发专用摘要器
    summarizer = _TOOL_SUMMARIZERS.get(tool_name)
    if summarizer:
        result = summarizer(content, data, tool_name)
        if result:
            return result

    # JSON 通用提取（无专用摘要器时的 fallback）
    if data:
        extracted = _extract_from_json(tool_name, data)
        if extracted:
            return extracted

    # 最终兜底：工具名 + 前 150 字符 + 字符数
    preview = content[:150].replace("\n", " ").strip()
    return f"[{tool_name or 'tool'}] {preview}... ({len(content)}字符)"


# ═══════════════════════════════════════════════════════════
# 按工具类型的专用摘要生成器（对齐 Hermes _summarize_tool_result）
# ═══════════════════════════════════════════════════════════

def _summarize_query_data(content: str, data: Any | None, tool_name: str) -> str | None:
    """query_data: 提取记录数 + 名称列表 + 金额汇总 + 阶段分布"""
    if data:
        return _extract_from_json(tool_name, data)
    # 非 JSON: 尝试提取记录数
    import re as _re
    count_match = _re.search(r'(\d+)\s*(?:条|records?|items?|结果)', content[:300])
    count_str = f"{count_match.group(1)}条结果" if count_match else ""
    preview = content.split("\n")[0][:120] if "\n" in content else content[:120]
    return f"[query_data] {count_str} — {preview}"


def _summarize_query_schema(content: str, data: Any | None, tool_name: str) -> str | None:
    """query_schema: 提取实体名 + 字段数 + 关键字段名"""
    if data and isinstance(data, dict):
        fields = data.get("fields") or data.get("items") or data.get("columns")
        entity = data.get("entity") or data.get("name") or data.get("object") or ""
        if isinstance(fields, list):
            count = len(fields)
            field_names = [f.get("name", f.get("api_key", "")) for f in fields[:8]
                          if isinstance(f, dict)]
            names_str = ", ".join(n for n in field_names if n)
            extra = f"...等{count}个" if count > 8 else ""
            return (f"[query_schema] {entity} 字段定义({count}个): "
                    f"{names_str}{extra}")
    return None


def _summarize_web_search(content: str, data: Any | None, tool_name: str) -> str | None:
    """web_search: 提取搜索词 + 结果数 + 来源域名/关键发现"""
    import re as _re
    # 尝试从 JSON 结构提取
    if data and isinstance(data, dict):
        query = data.get("query") or data.get("keyword") or ""
        results = data.get("results") or data.get("items") or []
        if isinstance(results, list):
            count = len(results)
            titles = [r.get("title", "")[:40] for r in results[:3]
                      if isinstance(r, dict)]
            return (f"[web_search] 搜索'{query}' → {count}条结果: "
                    f"{'; '.join(t for t in titles if t)}")
    if data and isinstance(data, list):
        count = len(data)
        titles = [r.get("title", "")[:40] for r in data[:3]
                  if isinstance(r, dict)]
        return (f"[web_search] {count}条结果: "
                f"{'; '.join(t for t in titles if t)}")
    # 非 JSON: 提取有意义的文本行
    lines = content.split("\n")
    meaningful = [l.strip() for l in lines
                  if l.strip() and 15 < len(l.strip()) <= 200][:3]
    if meaningful:
        return f"[web_search] ({len(content)}字符) " + " | ".join(meaningful)
    # 最终: 取前 150 字符
    return f"[web_search] {content[:150].replace(chr(10), ' ')}..."


def _summarize_analyze_data(content: str, data: Any | None, tool_name: str) -> str | None:
    """analyze_data: 提取分析结论 + 关键数字（金额/百分比/日期）"""
    import re as _re
    # 提取关键数字
    amounts = _re.findall(r'[\$¥￥]\s*[\d,.]+[KMB万亿]?', content[:1000])
    pcts = _re.findall(r'\d+\.?\d*\s*%', content[:1000])
    dates = _re.findall(r'\d{4}[-/]\d{1,2}[-/]\d{1,2}', content[:500])
    # 提取第一行作为结论
    first_line = content.split("\n")[0][:150] if "\n" in content else content[:150]
    # 组装
    key_data_parts = []
    if amounts:
        key_data_parts.append(f"金额:{','.join(amounts[:3])}")
    if pcts:
        key_data_parts.append(f"比例:{','.join(pcts[:3])}")
    if dates:
        key_data_parts.append(f"日期:{','.join(dates[:2])}")
    key_data_str = f" [{'; '.join(key_data_parts)}]" if key_data_parts else ""
    return f"[analyze_data] {first_line}{key_data_str}"


def _summarize_knowledge_search(content: str, data: Any | None, tool_name: str) -> str | None:
    """knowledge_search: 提取命中数 + 文档标题/来源 + 相关度"""
    if data and isinstance(data, dict):
        results = data.get("results") or data.get("items") or []
        if isinstance(results, list):
            count = len(results)
            titles = [r.get("title", r.get("doc_name", ""))[:30]
                      for r in results[:3] if isinstance(r, dict)]
            return (f"[knowledge_search] 命中{count}条: "
                    f"{'; '.join(t for t in titles if t)}")
    if data and isinstance(data, list):
        count = len(data)
        titles = [r.get("title", r.get("doc_name", ""))[:30]
                  for r in data[:3] if isinstance(r, dict)]
        return (f"[knowledge_search] 命中{count}条: "
                f"{'; '.join(t for t in titles if t)}")
    # 非 JSON: 检索结果通常是格式化文本
    import re as _re
    count_match = _re.search(r'(\d+)\s*(?:条|results?|matches?|命中)', content[:200])
    count_str = f"命中{count_match.group(1)}条" if count_match else ""
    preview = content[:120].replace("\n", " ")
    return f"[knowledge_search] {count_str} — {preview}"


def _summarize_modify_data(content: str, data: Any | None, tool_name: str) -> str | None:
    """modify_data: 提取操作类型 + 目标实体 + 结果状态"""
    if data and isinstance(data, dict):
        action = data.get("action") or data.get("operation") or "修改"
        target = data.get("name") or data.get("id") or data.get("entity") or ""
        status = data.get("status") or data.get("result") or "完成"
        return f"[modify_data] {action} {target} → {status}"
    # 非 JSON
    preview = content[:100].replace("\n", " ")
    return f"[modify_data] {preview}"


def _summarize_browse_metamodel(content: str, data: Any | None, tool_name: str) -> str | None:
    """browse_metamodel: 提取元模型列表 + 数量"""
    if data:
        return _extract_from_json(tool_name, data)
    return None


def _summarize_query_metadata(content: str, data: Any | None, tool_name: str) -> str | None:
    """query_metadata: 提取元数据类型 + 记录数 + 关键字段"""
    if data:
        return _extract_from_json(tool_name, data)
    return None


# 注册工具摘要器映射
_TOOL_SUMMARIZERS: dict[str, Any] = {
    "query_data": _summarize_query_data,
    "query_schema": _summarize_query_schema,
    "web_search": _summarize_web_search,
    "analyze_data": _summarize_analyze_data,
    "knowledge_search": _summarize_knowledge_search,
    "modify_data": _summarize_modify_data,
    "browse_metamodel": _summarize_browse_metamodel,
    "query_metadata": _summarize_query_metadata,
}


def _fallback_truncate(tool_name: str, content: str, max_chars: int) -> str:
    """兜底截断（保留 max_chars*2 字符，给后续阅读留足上下文）"""
    preview = content[:max_chars * 2]
    return f"[{tool_name}] {preview}...\n[已截断, 原文{len(content)}字符]"


# 向后兼容别名
SummarizationMiddleware = ContextWindowMiddleware
