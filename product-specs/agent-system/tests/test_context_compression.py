"""上下文压缩机制自动化验证

覆盖范围:
  1. Stage 0: 安全网截断 + token 预算推导
  2. Stage 1: Post-Skill Compact (条数触发 + token触发 + 就地压缩)
  3. Stage 2: MD5 去重
  4. Stage 3: MicroCompact / AutoCompact / FullCompact
  5. 保护区: 当前轮次 / Skill 边界 / 工具组原子性
  6. Skill 边界识别: Fork / Inline / 兜底
  7. _is_skill_active: 终止标记区分
  8. _skill_internal_one_liner: 数据类型覆盖
  9. ContextArchive: 写入 + 检索
  10. 回溯信号检测 + 自动注入

运行: pytest tests/test_context_compression.py -v
"""
import json
import pytest
from unittest.mock import patch, MagicMock
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage, SystemMessage

from src.middleware.context_window import (
    ContextWindowMiddleware,
    SKIP_COMPACT_TOOLS,
    _crm_tool_summary,
    _try_code_extract,
)
from src.middleware.skill_compress import (
    SkillAwareTailProtection,
    SkillResultAnchor,
    align_boundary_deep,
    find_completed_skill_boundaries,
    post_skill_compact,
    _inplace_compress_skill,
    _skill_internal_one_liner,
)


# ═══════════════════════════════════════════════════════════
# 1. Token 预算推导
# ═══════════════════════════════════════════════════════════

class TestTokenBudgetDerivation:
    """安全网阈值从 token 预算体系推导"""

    def test_default_100k_window(self):
        mw = ContextWindowMiddleware(max_tokens=100_000)
        assert mw._tail_token_budget == 20_000
        assert mw._safety_cap == 20_000  # 20K * 0.5 * 2

    def test_64k_window(self):
        mw = ContextWindowMiddleware(max_tokens=64_000)
        assert mw._tail_token_budget == 12_800  # 64K * 0.2
        assert mw._safety_cap == 12_800  # 12.8K * 0.5 * 2

    def test_200k_window(self):
        mw = ContextWindowMiddleware(max_tokens=200_000)
        assert mw._tail_token_budget == 40_000
        assert mw._safety_cap == 40_000

    def test_explicit_override(self):
        mw = ContextWindowMiddleware(max_tokens=100_000, safety_cap_chars=50_000)
        assert mw._safety_cap == 50_000  # 显式传入优先

    def test_custom_tail_ratio(self):
        mw = ContextWindowMiddleware(max_tokens=100_000, tail_token_budget_ratio=0.30)
        assert mw._tail_token_budget == 30_000
        assert mw._safety_cap == 30_000  # 30K * 0.5 * 2

    def test_formula_relationship(self):
        """safety_cap = tail_token_budget × 50% × 2"""
        mw = ContextWindowMiddleware(max_tokens=100_000)
        expected = int(mw._tail_token_budget * 0.5 * 2)
        assert mw._safety_cap == expected


# ═══════════════════════════════════════════════════════════
# 2. 全局压缩阈值
# ═══════════════════════════════════════════════════════════

class TestGlobalThresholds:
    """三级压缩阈值正确性"""

    def test_thresholds(self):
        mw = ContextWindowMiddleware(max_tokens=100_000)
        assert mw._micro_trigger == 50_000
        assert mw._auto_trigger == 75_000
        assert mw._full_trigger == 90_000

    def test_skip_compact_tools(self):
        assert SKIP_COMPACT_TOOLS == {"skills_tool", "agent_tool", "ask_user", "read_skill_resource"}


# ═══════════════════════════════════════════════════════════
# 3. Post-Skill Compact
# ═══════════════════════════════════════════════════════════

class TestPostSkillCompact:
    """Post-Skill Compact 双条件触发 + 两种压缩模式"""

    def _make_skill_messages(self, tool_content_size=200, num_tool_calls=3):
        """生成 Skill 内部消息"""
        msgs = [
            HumanMessage(content="start"),
            AIMessage(content="", tool_calls=[{"id": "tc0", "name": "skills_tool", "args": {}}]),
            ToolMessage(content="SOP prompt", tool_call_id="tc0", name="skills_tool"),
        ]
        for i in range(1, num_tool_calls + 1):
            msgs.append(AIMessage(content=f"step {i}", tool_calls=[{"id": f"tc{i}", "name": "query_data", "args": {}}]))
            msgs.append(ToolMessage(content="x" * tool_content_size, tool_call_id=f"tc{i}", name="query_data"))
        msgs.append(AIMessage(content="[INLINE_SKILL_DONE:test] final"))
        return msgs

    def test_count_trigger(self):
        """消息数 > 8 触发"""
        msgs = self._make_skill_messages(tool_content_size=100, num_tool_calls=5)
        skill_start, skill_end = 1, len(msgs) - 1
        n = skill_end - skill_start + 1
        assert n > 8

        result = post_skill_compact(msgs, skill_start, skill_end, min_skill_messages=8, max_skill_tokens=4000)
        original_tokens = sum(len(getattr(m, "content", "") or "") // 2 for m in msgs[skill_start:skill_end + 1])
        new_tokens = sum(len(getattr(m, "content", "") or "") // 2 for m in result[skill_start:])
        assert new_tokens <= original_tokens

    def test_token_trigger(self):
        """消息数 < 8 但 token > 4000 触发（就地压缩）"""
        msgs = [
            HumanMessage(content="hi"),
            AIMessage(content="", tool_calls=[{"id": "tc0", "name": "skills_tool", "args": {}}]),
            ToolMessage(content="SOP", tool_call_id="tc0", name="skills_tool"),
            AIMessage(content="go", tool_calls=[{"id": "tc1", "name": "web_search", "args": {}}]),
            ToolMessage(content="A" * 12000, tool_call_id="tc1", name="web_search"),
            AIMessage(content="done " + "B" * 2000),
        ]
        skill_start, skill_end = 1, 5
        n = skill_end - skill_start + 1
        assert n < 8  # 不触发条数

        tokens_before = sum(len(getattr(m, "content", "") or "") // 2 for m in msgs[skill_start:skill_end + 1])
        assert tokens_before > 4000  # 触发 token

        result = post_skill_compact(msgs, skill_start, skill_end, min_skill_messages=8, max_skill_tokens=4000)
        tokens_after = sum(len(getattr(m, "content", "") or "") // 2 for m in result[skill_start:skill_end + 1])
        assert tokens_after < tokens_before

    def test_no_trigger_short_and_small(self):
        """条数不够且 token 不够 → 不压缩"""
        msgs = [
            HumanMessage(content="hi"),
            AIMessage(content="", tool_calls=[{"id": "tc0", "name": "skills_tool", "args": {}}]),
            ToolMessage(content="short SOP", tool_call_id="tc0", name="skills_tool"),
            AIMessage(content="ok", tool_calls=[{"id": "tc1", "name": "query_data", "args": {}}]),
            ToolMessage(content="short result", tool_call_id="tc1", name="query_data"),
            AIMessage(content="done"),
        ]
        result = post_skill_compact(msgs, 1, 5, min_skill_messages=8, max_skill_tokens=4000)
        assert result == msgs  # 未修改

    def test_inplace_preserves_first_and_last(self):
        """就地压缩模式保留第一条和最后一条完整"""
        msgs = [
            HumanMessage(content="hi"),
            AIMessage(content="FIRST", tool_calls=[{"id": "tc0", "name": "skills_tool", "args": {}}]),
            ToolMessage(content="X" * 8000, tool_call_id="tc0", name="skills_tool"),
            AIMessage(content="mid", tool_calls=[{"id": "tc1", "name": "web_search", "args": {}}]),
            ToolMessage(content="Y" * 10000, tool_call_id="tc1", name="web_search"),
            AIMessage(content="LAST " + "Z" * 3000),
        ]
        result = _inplace_compress_skill(msgs, 1, 5)
        assert result[1].content == "FIRST"  # 第一条完整
        assert result[5].content == msgs[5].content  # 最后一条完整
        assert len(result[4].content) < 10000  # 中间被压缩


# ═══════════════════════════════════════════════════════════
# 4. MD5 去重
# ═══════════════════════════════════════════════════════════

class TestMD5Dedup:
    """MD5 去重逻辑"""

    def test_dedup_removes_older_duplicate(self):
        mw = ContextWindowMiddleware()
        msgs = [
            HumanMessage(content="q1"),
            AIMessage(content="", tool_calls=[{"id": "tc1", "name": "query_data", "args": {}}]),
            ToolMessage(content="same content " * 20, tool_call_id="tc1", name="query_data"),
            AIMessage(content="", tool_calls=[{"id": "tc2", "name": "query_data", "args": {}}]),
            ToolMessage(content="same content " * 20, tool_call_id="tc2", name="query_data"),  # 重复
        ]
        result = mw._md5_dedup(msgs)
        assert result is not None
        # 旧的（idx 2）被替换，新的（idx 4）保留
        assert "重复结果" in result["messages"][2].content
        assert result["messages"][4].content == msgs[4].content

    def test_no_dedup_short_content(self):
        """content < 100 字不去重"""
        mw = ContextWindowMiddleware()
        msgs = [
            HumanMessage(content="q"),
            ToolMessage(content="short", tool_call_id="tc1"),
            ToolMessage(content="short", tool_call_id="tc2"),
        ]
        result = mw._md5_dedup(msgs)
        assert result is None  # 没有修改

    def test_no_dedup_unique_content(self):
        mw = ContextWindowMiddleware()
        msgs = [
            HumanMessage(content="q"),
            ToolMessage(content="content A " * 20, tool_call_id="tc1"),
            ToolMessage(content="content B " * 20, tool_call_id="tc2"),
        ]
        result = mw._md5_dedup(msgs)
        assert result is None


# ═══════════════════════════════════════════════════════════
# 5. 保护区计算
# ═══════════════════════════════════════════════════════════

class TestProtectionZone:
    """保护区确定逻辑"""

    def test_current_turn_start(self):
        mw = ContextWindowMiddleware()
        msgs = [
            SystemMessage(content="sys"),
            HumanMessage(content="q1"),
            AIMessage(content="a1"),
            HumanMessage(content="q2"),  # idx 3 = 当前轮次起始
            AIMessage(content="a2"),
        ]
        assert mw._find_current_turn_start(msgs) == 3

    def test_align_boundary_deep_in_tool_group(self):
        """切割点在并发 ToolMessage 中间 → 回退到父 AIMessage"""
        msgs = [
            HumanMessage(content="hi"),
            AIMessage(content="", tool_calls=[
                {"id": "tc1", "name": "a", "args": {}},
                {"id": "tc2", "name": "b", "args": {}},
                {"id": "tc3", "name": "c", "args": {}},
            ]),
            ToolMessage(content="r1", tool_call_id="tc1"),
            ToolMessage(content="r2", tool_call_id="tc2"),
            ToolMessage(content="r3", tool_call_id="tc3"),
            AIMessage(content="done"),
        ]
        assert align_boundary_deep(msgs, 3) == 1  # 回退到 AIMessage

    def test_align_boundary_deep_outside_group(self):
        """切割点不在工具组中间 → 不移动"""
        msgs = [
            HumanMessage(content="hi"),
            AIMessage(content="thought"),
            HumanMessage(content="next"),
        ]
        assert align_boundary_deep(msgs, 2) == 2


# ═══════════════════════════════════════════════════════════
# 6. Skill 边界识别
# ═══════════════════════════════════════════════════════════

class TestSkillBoundaryDetection:
    """三层 Skill 边界识别"""

    def test_fork_skill_detection(self):
        msgs = [
            HumanMessage(content="hi"),
            AIMessage(content="", tool_calls=[{"id": "tc1", "name": "skills_tool", "args": {}}]),
            ToolMessage(content="[SKILL_DONE:silent] result", tool_call_id="tc1", name="skills_tool"),
            AIMessage(content="done"),
        ]
        boundaries = find_completed_skill_boundaries(msgs)
        assert boundaries == [(1, 2)]

    def test_inline_skill_detection(self):
        msgs = [
            HumanMessage(content="hi"),
            AIMessage(content="", tool_calls=[{"id": "tc1", "name": "skills_tool", "args": {}}]),
            ToolMessage(content="SOP prompt...", tool_call_id="tc1", name="skills_tool"),
            AIMessage(content="step1", tool_calls=[{"id": "tc2", "name": "web_search", "args": {}}]),
            ToolMessage(content="results", tool_call_id="tc2", name="web_search"),
            AIMessage(content="[INLINE_SKILL_DONE:test] analysis"),
            HumanMessage(content="thanks"),
        ]
        boundaries = find_completed_skill_boundaries(msgs)
        assert boundaries == [(1, 5)]

    def test_active_skill_excluded(self):
        """正在执行的 Skill 不加入 boundaries"""
        msgs = [
            HumanMessage(content="hi"),
            AIMessage(content="", tool_calls=[{"id": "tc1", "name": "skills_tool", "args": {}}]),
            ToolMessage(content="SOP...", tool_call_id="tc1", name="skills_tool"),
            AIMessage(content="working", tool_calls=[{"id": "tc2", "name": "web_search", "args": {}}]),
            ToolMessage(content="partial", tool_call_id="tc2", name="web_search"),
        ]
        boundaries = find_completed_skill_boundaries(msgs)
        assert boundaries == []

    def test_two_consecutive_fork_skills(self):
        msgs = [
            HumanMessage(content="hi"),
            AIMessage(content="", tool_calls=[{"id": "tc1", "name": "skills_tool", "args": {}}]),
            ToolMessage(content="[SKILL_DONE:silent] A done", tool_call_id="tc1", name="skills_tool"),
            AIMessage(content="", tool_calls=[{"id": "tc2", "name": "skills_tool", "args": {}}]),
            ToolMessage(content="[SKILL_DONE:silent] B done", tool_call_id="tc2", name="skills_tool"),
        ]
        boundaries = find_completed_skill_boundaries(msgs)
        assert (1, 2) in boundaries
        assert (3, 4) in boundaries


# ═══════════════════════════════════════════════════════════
# 7. _is_skill_active
# ═══════════════════════════════════════════════════════════

class TestIsSkillActive:
    """Skill 活跃状态判断（修复后的逻辑）"""

    def setup_method(self):
        self.prot = SkillAwareTailProtection()

    def test_inline_prompt_not_treated_as_done(self):
        """inline prompt 返回不视为终止"""
        msgs = [
            AIMessage(content="", tool_calls=[{"id": "tc1", "name": "skills_tool", "args": {}}]),
            ToolMessage(content="SOP: please research...", tool_call_id="tc1", name="skills_tool"),
            AIMessage(content="searching", tool_calls=[{"id": "tc2", "name": "web_search", "args": {}}]),
            ToolMessage(content="results", tool_call_id="tc2", name="web_search"),
        ]
        assert self.prot._is_skill_active(msgs, 0) is True

    def test_fork_done_detected(self):
        """[SKILL_DONE:] 正确标识为已完成"""
        msgs = [
            AIMessage(content="", tool_calls=[{"id": "tc1", "name": "skills_tool", "args": {}}]),
            ToolMessage(content="[SKILL_DONE:silent] done", tool_call_id="tc1", name="skills_tool"),
        ]
        assert self.prot._is_skill_active(msgs, 0) is False

    def test_inline_done_detected(self):
        """[INLINE_SKILL_DONE:] 正确标识为已完成"""
        msgs = [
            AIMessage(content="", tool_calls=[{"id": "tc1", "name": "skills_tool", "args": {}}]),
            ToolMessage(content="SOP...", tool_call_id="tc1", name="skills_tool"),
            AIMessage(content="[INLINE_SKILL_DONE:test] done"),
        ]
        assert self.prot._is_skill_active(msgs, 0) is False

    def test_just_started(self):
        """刚启动，无后续消息"""
        msgs = [
            AIMessage(content="", tool_calls=[{"id": "tc1", "name": "skills_tool", "args": {}}]),
        ]
        assert self.prot._is_skill_active(msgs, 0) is True


# ═══════════════════════════════════════════════════════════
# 8. _skill_internal_one_liner 数据类型覆盖
# ═══════════════════════════════════════════════════════════

class TestSkillOneLiner:
    """一行摘要对各数据类型的处理"""

    def test_json_array_with_amounts(self):
        data = [
            {"name": "Deal A", "amount": 45000, "stage": "proposal"},
            {"name": "Deal B", "amount": 28000, "stage": "qualification"},
        ]
        result = _skill_internal_one_liner("query_data", json.dumps(data))
        assert "2条" in result
        assert "总金额" in result
        assert "73,000" in result or "73000" in result

    def test_json_object_with_records(self):
        data = {"records": [{"name": "X", "amount": 100}], "total": 1}
        result = _skill_internal_one_liner("query_data", json.dumps(data))
        assert "1条" in result

    def test_json_schema(self):
        data = {"entity": "opportunity", "fields": [
            {"api_key": "name"}, {"api_key": "amount"}, {"api_key": "stage"}
        ]}
        result = _skill_internal_one_liner("query_schema", json.dumps(data))
        assert "opportunity" in result
        assert "3个" in result

    def test_text_with_numbers(self):
        text = "Odoo pricing: $24.90/user, discount 15%, contract until 2025-12-31" + "x" * 200
        result = _skill_internal_one_liner("web_search", text)
        assert "金额" in result
        assert "$24.90" in result
        assert "15%" in result
        assert "2025-12-31" in result

    def test_text_without_numbers(self):
        text = "This is a plain description without any numbers or dates" + "y" * 200
        result = _skill_internal_one_liner("web_search", text)
        assert "字符" in result  # 有字符数标注

    def test_nested_json(self):
        data = {"summary": {"total_amount": 3600000, "win_rate": "32%"}}
        result = _skill_internal_one_liner("analyze_data", json.dumps(data))
        assert "3.6e+06" in result or "3600000" in result
        assert "32%" in result

    def test_empty_content(self):
        result = _skill_internal_one_liner("query_data", "")
        assert "[query_data]" in result

    def test_short_content(self):
        result = _skill_internal_one_liner("modify_data", "OK")
        assert "OK" in result

    def test_result_length_reasonable(self):
        """摘要不应超过 300 字符"""
        big_data = [{"name": f"item_{i}", "amount": i * 1000} for i in range(100)]
        result = _skill_internal_one_liner("query_data", json.dumps(big_data))
        assert len(result) < 300


# ═══════════════════════════════════════════════════════════
# 9. SkillResultAnchor
# ═══════════════════════════════════════════════════════════

class TestSkillResultAnchor:
    """Skill 锚点提取和注入"""

    def test_extract_amounts(self):
        anchor = SkillResultAnchor()
        result = anchor.on_skill_complete("报价", "方案: $45,000, 折扣15%, 日期2025-07-17", [])
        assert result is not None
        assert "$45,000" in result
        assert "15%" in result
        assert "2025-07-17" in result

    def test_max_anchors_fifo(self):
        anchor = SkillResultAnchor(max_anchors=3)
        for i in range(5):
            anchor.on_skill_complete(f"skill_{i}", f"金额${i * 1000}", [])
        assert anchor.anchor_count == 3

    def test_inject_into_prompt(self):
        anchor = SkillResultAnchor()
        anchor.on_skill_complete("test", "$100,000 报价", [])
        injected = anchor.inject_into_summary_prompt("original prompt")
        assert "不可丢失" in injected
        assert "$100,000" in injected

    def test_clear(self):
        anchor = SkillResultAnchor()
        anchor.on_skill_complete("test", "$999", [])
        anchor.clear()
        assert anchor.anchor_count == 0


# ═══════════════════════════════════════════════════════════
# 10. 回溯信号检测
# ═══════════════════════════════════════════════════════════

class TestRetrospectSignal:
    """回溯信号词检测"""

    def setup_method(self):
        self.mw = ContextWindowMiddleware()

    def test_signal_detected(self):
        assert self.mw._has_retrospect_signal("之前那个报价方案是什么") is True
        assert self.mw._has_retrospect_signal("付款条件具体怎么写的") is True
        assert self.mw._has_retrospect_signal("刚才说的金额") is True

    def test_no_signal(self):
        assert self.mw._has_retrospect_signal("帮我查一下客户") is False
        assert self.mw._has_retrospect_signal("生成报价") is False


# ═══════════════════════════════════════════════════════════
# 11. MicroCompact 逻辑
# ═══════════════════════════════════════════════════════════

class TestMicroCompact:
    """MicroCompact 规则裁剪"""

    def test_compresses_old_tool_messages(self):
        mw = ContextWindowMiddleware(max_tokens=100)  # 极小窗口强制触发
        msgs = [
            SystemMessage(content="sys"),
            HumanMessage(content="old question"),
            AIMessage(content="", tool_calls=[{"id": "tc1", "name": "query_data", "args": {}}]),
            ToolMessage(content="old result " * 50, tool_call_id="tc1", name="query_data"),  # >200字
            AIMessage(content="old answer"),
            HumanMessage(content="new question"),  # 当前轮次起始
            AIMessage(content="new answer"),
        ]
        result = mw._micro_compact(msgs, estimated=80)
        if result:
            # 旧的 ToolMessage 应该被压缩
            compressed_tm = result["messages"][3]
            assert len(compressed_tm.content) < len(msgs[3].content)

    def test_preserves_current_turn(self):
        """当前轮次消息不被压缩"""
        mw = ContextWindowMiddleware(max_tokens=100)
        msgs = [
            SystemMessage(content="sys"),
            HumanMessage(content="old"),
            AIMessage(content="old answer"),
            HumanMessage(content="current"),  # 当前轮次
            AIMessage(content="", tool_calls=[{"id": "tc1", "name": "query_data", "args": {}}]),
            ToolMessage(content="current result " * 50, tool_call_id="tc1", name="query_data"),
        ]
        result = mw._micro_compact(msgs, estimated=80)
        if result:
            # 当前轮次的 ToolMessage 应保持完整
            current_tm = result["messages"][5]
            assert current_tm.content == msgs[5].content


# ═══════════════════════════════════════════════════════════
# 12. 综合集成测试
# ═══════════════════════════════════════════════════════════

class TestIntegration:
    """端到端集成验证"""

    def test_full_before_model_flow(self):
        """完整的 before_model 流程不报错"""
        mw = ContextWindowMiddleware(max_tokens=100_000)
        msgs = [
            SystemMessage(content="You are an agent"),
            HumanMessage(content="Help me"),
            AIMessage(content="Sure", tool_calls=[{"id": "tc1", "name": "query_data", "args": {}}]),
            ToolMessage(content="result data", tool_call_id="tc1", name="query_data"),
            AIMessage(content="Here's what I found"),
        ]
        # 模拟 runtime
        mock_runtime = MagicMock()
        mock_runtime.config = {"configurable": {"thread_id": "test_thread", "tenant_id": 1}}
        state = {"messages": msgs}

        result = mw.before_model(state, mock_runtime)
        # 小消息不应触发压缩
        assert result is None or "messages" in result

    def test_post_skill_then_global_compact(self):
        """Post-Skill Compact 后全局压缩不冲突"""
        mw = ContextWindowMiddleware(max_tokens=100_000)

        # 构建一个大 Skill 段
        msgs = [
            SystemMessage(content="sys"),
            HumanMessage(content="research"),
            AIMessage(content="", tool_calls=[{"id": "tc0", "name": "skills_tool", "args": {"skill_name": "test"}}]),
            ToolMessage(content="SOP...", tool_call_id="tc0", name="skills_tool"),
        ]
        for i in range(1, 6):
            msgs.append(AIMessage(content=f"step {i}", tool_calls=[{"id": f"tc{i}", "name": "web_search", "args": {}}]))
            msgs.append(ToolMessage(content="X" * 3000, tool_call_id=f"tc{i}", name="web_search"))
        msgs.append(AIMessage(content="[INLINE_SKILL_DONE:test] done"))
        msgs.append(HumanMessage(content="thanks"))
        msgs.append(AIMessage(content="welcome"))

        # Post-Skill Compact
        result = mw._apply_post_skill_compact(msgs)
        assert len(result) <= len(msgs)  # 可能条数不变（就地压缩）或减少

        # 确保 MD5 去重不报错
        dedup = mw._md5_dedup(result)
        # 不管是否去重，流程正常

    def test_reset_session_clears_all(self):
        """reset_session 清理全部会话状态"""
        mw = ContextWindowMiddleware()
        mw._previous_summary = "some summary"
        mw._current_focus_topic = "报价"
        mw._consecutive_failures = 3
        mw._ineffective_compression_count = 2

        mw.reset_session()

        assert mw._previous_summary is None
        assert mw._current_focus_topic is None
        assert mw._consecutive_failures == 0
        assert mw._ineffective_compression_count == 0
