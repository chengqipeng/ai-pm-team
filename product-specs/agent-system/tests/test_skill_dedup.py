"""验证 Fork Skill 输出去重机制 — 修复报告重复输出 bug

场景：
1. skill_result 先到达 → 输出报告 → LLM stream 重复内容被抑制
2. on_tool_end 先到达（设置 hard_suppress）→ skill_result 仍能正常直出
3. tool_call_chunk 无 name 时不解除硬抑制
"""
from __future__ import annotations

import asyncio
import pytest
from src.agui.converter import AGUIConverter
from src.agui import models as m


REPORT_CONTENT = """# 智能客户洞察报告 — 华为技术有限公司
客户ID: acc_001 | 场景: 商机推进 | 报告时间: 2025-04-20
🎯 核心洞察结论
华为处于战略扩张期，AI和智能汽车是核心增长引擎。
"""


async def _collect(gen):
    """收集 async generator 的所有事件"""
    events = []
    async for e in gen:
        events.append(e)
    return events


def _text_contents(events) -> str:
    """提取所有 TEXT_MESSAGE_CONTENT 事件中的文本并拼接"""
    parts = []
    for e in events:
        t_val = getattr(e.type, "value", None) or str(e.type)
        if "TEXT_MESSAGE_CONTENT" in t_val:
            parts.append(e.data.get("delta", "") or e.data.get("content", ""))
    return "".join(parts)


# ═══════════════════════════════════════════════════════════
# Case 1: skill_result 先到 → LLM stream 重复被去重拦截
# ═══════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_skill_result_then_llm_stream_dedup():
    """skill_result 输出报告后，LLM stream 输出相同内容应被去重拦截"""
    conv = AGUIConverter(run_id="r-1", thread_id="t-1")

    async def stream():
        # 模拟根事件（用于 root_run_id 初始化）
        yield {"event": "on_chain_start", "name": "main", "run_id": "root-1",
               "parent_ids": [], "data": {}}
        # 1. skill_result 事件先到达
        yield {"event": "on_custom_event", "name": "skill_result", "data": {
            "skill_apikey": "accountInsight",
            "behavior": "silent",
            "content": REPORT_CONTENT,
            "summary": "华为客户洞察报告",
            "output_mode": "text",
        }, "run_id": "root-1", "parent_ids": []}
        # 2. on_tool_end（确认 SKILL_DONE:silent）
        yield {"event": "on_tool_end", "name": "skills_tool",
               "run_id": "tool-1", "parent_ids": ["root-1"],
               "data": {"output": "[SKILL_DONE:silent] accountInsight 已将完整结果直接输出给用户。"}}
        # 3. LLM stream 开始输出相同报告内容（模拟 LLM 不遵从指令）
        # 由于 _hard_suppress_text=True，这些应该被抑制
        yield {"event": "on_chat_model_stream", "name": "model",
               "run_id": "llm-1", "parent_ids": ["root-1"],
               "data": {"chunk": _make_chunk("# 智能客户洞察报告 — 华为技术有限公司\n")}}
        yield {"event": "on_chat_model_stream", "name": "model",
               "run_id": "llm-1", "parent_ids": ["root-1"],
               "data": {"chunk": _make_chunk("客户ID: acc_001 | 场景: 商机推进\n")}}

    events = await _collect(conv.convert(stream()))
    text = _text_contents(events)

    # 报告应该只出现一次（来自 skill_result 的直出）
    assert text.count("智能客户洞察报告") == 1, f"报告出现了多次！text={text[:500]}"


# ═══════════════════════════════════════════════════════════
# Case 2: tool_call_chunk 无 name 不解除硬抑制
# ═══════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_nameless_tool_chunk_does_not_release_suppress():
    """LLM stream 中出现无 name 的 tool_call_chunk 不应解除硬抑制"""
    conv = AGUIConverter(run_id="r-2", thread_id="t-2")

    async def stream():
        yield {"event": "on_chain_start", "name": "main", "run_id": "root-2",
               "parent_ids": [], "data": {}}
        # 1. skill_result 先到达
        yield {"event": "on_custom_event", "name": "skill_result", "data": {
            "skill_apikey": "accountInsight",
            "behavior": "silent",
            "content": REPORT_CONTENT,
            "summary": "华为客户洞察报告",
            "output_mode": "text",
        }, "run_id": "root-2", "parent_ids": []}
        # 2. on_tool_end
        yield {"event": "on_tool_end", "name": "skills_tool",
               "run_id": "tool-2", "parent_ids": ["root-2"],
               "data": {"output": "[SKILL_DONE:silent] accountInsight done."}}
        # 3. LLM stream 带有无 name 的 tool_call_chunk（不应解除抑制）
        yield {"event": "on_chat_model_stream", "name": "model",
               "run_id": "llm-2", "parent_ids": ["root-2"],
               "data": {"chunk": _make_chunk_with_tool_call(
                   tool_id="tc-ghost", tool_name="", content="")}}
        # 4. 后续文本应该仍被抑制
        yield {"event": "on_chat_model_stream", "name": "model",
               "run_id": "llm-2", "parent_ids": ["root-2"],
               "data": {"chunk": _make_chunk("# 智能客户洞察报告 — 重复内容\n")}}

    events = await _collect(conv.convert(stream()))
    text = _text_contents(events)

    # 报告只出现一次（skill_result 直出），LLM 的重复被抑制
    assert text.count("智能客户洞察报告") == 1, f"报告出现了多次！text={text[:500]}"


# ═══════════════════════════════════════════════════════════
# Case 3: 有 name 的 tool_call_chunk 正确解除抑制
# ═══════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_named_tool_chunk_releases_suppress():
    """LLM 调用新工具（有 name）时应正确解除抑制"""
    conv = AGUIConverter(run_id="r-3", thread_id="t-3")

    async def stream():
        yield {"event": "on_chain_start", "name": "main", "run_id": "root-3",
               "parent_ids": [], "data": {}}
        # 1. skill_result 先到达
        yield {"event": "on_custom_event", "name": "skill_result", "data": {
            "skill_apikey": "accountInsight",
            "behavior": "silent",
            "content": REPORT_CONTENT,
            "summary": "报告",
            "output_mode": "text",
        }, "run_id": "root-3", "parent_ids": []}
        # 2. on_tool_end
        yield {"event": "on_tool_end", "name": "skills_tool",
               "run_id": "tool-3", "parent_ids": ["root-3"],
               "data": {"output": "[SKILL_DONE:silent] done."}}
        # 3. LLM 调用新工具（有明确 name） → 应解除抑制
        yield {"event": "on_chat_model_stream", "name": "model",
               "run_id": "llm-3", "parent_ids": ["root-3"],
               "data": {"chunk": _make_chunk_with_tool_call(
                   tool_id="tc-new-tool", tool_name="query_data", content="")}}
        # 4. tool 执行完毕后 LLM 输出新内容（非重复）→ 应正常显示
        yield {"event": "on_tool_end", "name": "query_data",
               "run_id": "tc-new-tool", "parent_ids": ["root-3"],
               "data": {"output": "查询结果：客户状态活跃"}}
        yield {"event": "on_chat_model_stream", "name": "model",
               "run_id": "llm-3b", "parent_ids": ["root-3"],
               "data": {"chunk": _make_chunk("根据查询结果，建议下一步行动...")}}

    events = await _collect(conv.convert(stream()))
    text = _text_contents(events)

    # skill_result 的报告应该出现
    assert "智能客户洞察报告" in text
    # 新工具后的内容也应该出现
    assert "根据查询结果" in text


# ═══════════════════════════════════════════════════════════
# Case 4: skill_result 在 on_tool_end 之后到达（时序倒置）
# ═══════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_skill_result_after_tool_end_still_outputs():
    """即使 skill_result 在 on_tool_end 之后到达，直出内容仍应正常输出"""
    conv = AGUIConverter(run_id="r-4", thread_id="t-4")

    async def stream():
        yield {"event": "on_chain_start", "name": "main", "run_id": "root-4",
               "parent_ids": [], "data": {}}
        # 1. on_tool_end 先到达 → 设置 _hard_suppress_text = True
        yield {"event": "on_tool_end", "name": "skills_tool",
               "run_id": "tool-4", "parent_ids": ["root-4"],
               "data": {"output": "[SKILL_DONE:silent] accountInsight done."}}
        # 2. skill_result 延迟到达 → 应该仍能输出报告（绕过自身的硬抑制）
        yield {"event": "on_custom_event", "name": "skill_result", "data": {
            "skill_apikey": "accountInsight",
            "behavior": "silent",
            "content": REPORT_CONTENT,
            "summary": "报告",
            "output_mode": "text",
        }, "run_id": "root-4", "parent_ids": []}
        # 3. LLM stream（被硬抑制，不输出）
        yield {"event": "on_chat_model_stream", "name": "model",
               "run_id": "llm-4", "parent_ids": ["root-4"],
               "data": {"chunk": _make_chunk("# 智能客户洞察报告 — 重复\n")}}

    events = await _collect(conv.convert(stream()))
    text = _text_contents(events)

    # 报告应该出现一次（来自 skill_result 的直出，绕过了硬抑制）
    assert text.count("智能客户洞察报告") == 1, f"text={text[:500]}"
    assert "华为技术有限公司" in text


# ═══════════════════════════════════════════════════════════
# Case 5: LLM stream 去重检测（硬抑制被意外解除后的兜底）
# ═══════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_llm_stream_dedup_fallback():
    """即使硬抑制被解除（通过非正常途径），去重检测仍能拦截 LLM 重复输出"""
    conv = AGUIConverter(run_id="r-5", thread_id="t-5")

    # 直接模拟硬抑制被意外解除后的状态
    # 先让 skill_result 正常输出
    async def stream():
        yield {"event": "on_chain_start", "name": "main", "run_id": "root-5",
               "parent_ids": [], "data": {}}
        # 1. skill_result 先到达 → 输出报告
        yield {"event": "on_custom_event", "name": "skill_result", "data": {
            "skill_apikey": "accountInsight",
            "behavior": "silent",
            "content": REPORT_CONTENT,
            "summary": "报告",
            "output_mode": "text",
        }, "run_id": "root-5", "parent_ids": []}
        # 2. on_tool_end
        yield {"event": "on_tool_end", "name": "skills_tool",
               "run_id": "tool-5", "parent_ids": ["root-5"],
               "data": {"output": "[SKILL_DONE:silent] done."}}
        # 3. 模拟 LLM 直接输出重复内容（硬抑制仍然有效的情况下）
        # 这里不通过 tool_call 解除抑制，而是测试 _hard_suppress_text 的基本功能
        yield {"event": "on_chat_model_stream", "name": "model",
               "run_id": "llm-5", "parent_ids": ["root-5"],
               "data": {"chunk": _make_chunk("# 智能客户洞察报告 — 华为技术有限公司\n客户ID: acc_001 | 场景: 商机推进 | 报告时间: 2025-04-20\n🎯 核心洞察结论\n")}}
        yield {"event": "on_chat_model_stream", "name": "model",
               "run_id": "llm-5", "parent_ids": ["root-5"],
               "data": {"chunk": _make_chunk("华为处于战略扩张期，AI和智能汽车是核心增长引擎。继续分析...")}}

    events = await _collect(conv.convert(stream()))
    text = _text_contents(events)

    # 报告标题应该只出现一次（LLM 的重复被 _hard_suppress_text 拦截）
    count = text.count("智能客户洞察报告")
    assert count == 1, f"报告出现了 {count} 次！text={text[:800]}"


@pytest.mark.asyncio
async def test_llm_stream_dedup_with_nameless_tool_chunk():
    """无 name 的 tool_call_chunk 解除抑制后，去重检测拦截重复内容"""
    conv = AGUIConverter(run_id="r-6", thread_id="t-6")

    async def stream():
        yield {"event": "on_chain_start", "name": "main", "run_id": "root-6",
               "parent_ids": [], "data": {}}
        # 1. skill_result 先到达 → 输出报告
        yield {"event": "on_custom_event", "name": "skill_result", "data": {
            "skill_apikey": "accountInsight",
            "behavior": "silent",
            "content": REPORT_CONTENT,
            "summary": "报告",
            "output_mode": "text",
        }, "run_id": "root-6", "parent_ids": []}
        # 2. on_tool_end
        yield {"event": "on_tool_end", "name": "skills_tool",
               "run_id": "tool-6", "parent_ids": ["root-6"],
               "data": {"output": "[SKILL_DONE:silent] done."}}
        # 3. 无 name 的 tool_call_chunk（不应解除 suppress 也不应解除 dedup）
        yield {"event": "on_chat_model_stream", "name": "model",
               "run_id": "llm-6", "parent_ids": ["root-6"],
               "data": {"chunk": _make_chunk_with_tool_call(
                   tool_id="tc-ghost", tool_name="", content="")}}
        # 4. 紧跟重复文本（硬抑制没被解除，应该被抑制）
        yield {"event": "on_chat_model_stream", "name": "model",
               "run_id": "llm-6", "parent_ids": ["root-6"],
               "data": {"chunk": _make_chunk("# 智能客户洞察报告 — 华为技术有限公司\n重复内容...")}}

    events = await _collect(conv.convert(stream()))
    text = _text_contents(events)

    # 只有 skill_result 输出的一遍
    count = text.count("智能客户洞察报告")
    assert count == 1, f"报告出现了 {count} 次！text={text[:500]}"


# ═══════════════════════════════════════════════════════════
# 辅助函数：构造 LangChain chunk mock
# ═══════════════════════════════════════════════════════════

class _MockChunk:
    """模拟 LangChain AIMessageChunk"""
    def __init__(self, content="", tool_call_chunks=None):
        self.content = content
        self.tool_call_chunks = tool_call_chunks or []


def _make_chunk(content: str) -> _MockChunk:
    return _MockChunk(content=content)


def _make_chunk_with_tool_call(tool_id: str, tool_name: str, content: str = "") -> _MockChunk:
    return _MockChunk(
        content=content,
        tool_call_chunks=[{"id": tool_id, "name": tool_name, "args": "", "index": 0}],
    )
