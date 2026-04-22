#!/usr/bin/env python3
"""
DeepAgent Tool / Skill / SubAgent 全链路 Demo

展示三层能力的区别:
  场景 1: Tool 直接调用 — LLM function calling → query_data
  场景 2: Skill inline  — LLM → skills_tool → SOP prompt 注入 → LLM 按 SOP 调 Tool
  场景 3: Skill fork    — LLM → skills_tool → 子 Agent 独立执行 → 返回结果
  场景 4: Skill fork+agent — LLM → skills_tool → SubagentConfig 专属子 Agent

运行: poetry run python demo.py
"""
import asyncio, json, sys, os
sys.path.insert(0, os.path.dirname(__file__))
os.environ.setdefault("DEEPSEEK_API_KEY", "sk-a86b7e7ca89e4a4283c0a8a7bcb34b9c")

from src.dtypes import Message, MessageRole, ToolResult
from src.tools import ToolRegistry
from src.llm_client import MockLLMClient
from src.graph.state import GraphState, AgentStatus, StepStatus
from src.graph.factory import AgentFactory, AgentConfig
from src.crm_backend import CrmSimulatedBackend
from src.crm_tools import register_crm_tools
from src.skills import SkillRegistry, SkillExecutor, SkillsTool
from src.crm_skills import register_crm_skills, register_crm_subagents
from src.subagent_config import SubagentRegistry


def hdr(n, title, mode):
    print(f"\n{'━'*70}")
    print(f"  场景 {n}: {title}")
    print(f"  模式: {mode}")
    print(f"{'━'*70}")

def p(indent, icon, msg):
    prefix = "  " + "│ " * indent
    for i, line in enumerate(str(msg).split("\n")[:5]):
        print(f"{prefix}{icon + ' ' if i == 0 else '  '}{line[:120]}")

def ok(msg): print(f"  ✅ {msg}")


# ═══════════════════════════════════════════════════════════
# 场景 1: Tool 直接调用（LLM function calling）
# ═══════════════════════════════════════════════════════════

async def scene_1():
    hdr(1, "Tool 直接调用", "LLM → function_calling → query_data → 结果")
    p(0, "📖", "Tool 是原子操作，LLM 直接通过 function calling 调用，一次调用一次返回")

    backend = CrmSimulatedBackend()
    mock = MockLLMClient()
    mock.add_tool_call_response("query_data", {
        "action": "query", "entity_api_key": "account",
        "filters": {"activeFlg": 1}, "order_by": "-annualRevenue",
    })
    mock.add_text_response("活跃客户按营收排序: 华为8809亿 > 腾讯6090亿 > 比亚迪6020亿 > 招行3400亿。")

    reg = ToolRegistry()
    register_crm_tools(reg, backend)
    engine, prompt = AgentFactory.create(AgentConfig(
        llm_client=mock, tool_registry=reg, enable_hitl=False, enable_audit=False,
    ))
    s = GraphState(system_prompt=prompt, messages=[Message(role=MessageRole.USER, content="查一下活跃客户")])
    async for s in engine.run(s): pass

    p(0, "👤", "用户: 查一下活跃客户")
    p(0, "🔧", f"Tool 调用: query_data(action=query, entity=account, filters={{activeFlg:1}})")
    p(0, "💬", f"Agent: {s.final_answer}")
    ok(f"Tool 直接调用: LLM={mock.call_count}次 工具={s.total_tool_calls}次")


# ═══════════════════════════════════════════════════════════
# 场景 2: Skill inline（SOP prompt 注入当前对话）
# ═══════════════════════════════════════════════════════════

async def scene_2():
    hdr(2, "Skill inline — 配置校验", "LLM → skills_tool → SOP prompt 注入 → LLM 按 SOP 调 Tool")
    p(0, "📖", "inline Skill 返回 SOP prompt 作为工具结果，LLM 收到后按 SOP 继续调用 Tool")

    backend = CrmSimulatedBackend()
    mock = MockLLMClient()

    # LLM 第 1 轮: 决定调用 skills_tool（inline 技能）
    mock.add_tool_call_response("skills_tool", {
        "skill_name": "verify_config",
        "arguments": {"entity": "opportunity"},
    }, text="让我调用配置校验技能。")

    # LLM 第 2 轮: 收到 SOP prompt 后，按步骤 1 调用 query_schema
    mock.add_tool_call_response("query_schema", {
        "query_type": "entity_items", "entity_api_key": "opportunity",
    })

    # LLM 第 3 轮: 收到 schema 后，按步骤 3 查关联关系
    mock.add_tool_call_response("query_schema", {
        "query_type": "entity_links", "entity_api_key": "opportunity",
    })

    # LLM 第 4 轮: 输出校验报告
    mock.add_text_response(
        "## 校验报告: opportunity\n"
        "🟢 PASS: 9个字段定义完整，api_key 符合 camelCase\n"
        "🟢 PASS: PICK_LIST 字段(stage/source)有 options 定义\n"
        "🟡 WARNING: closeDate 字段建议添加必填约束\n"
        "VERDICT: PASS"
    )

    # 构建 SkillRegistry + SkillsTool
    skill_reg = SkillRegistry()
    register_crm_skills(skill_reg)

    reg = ToolRegistry()
    register_crm_tools(reg, backend)
    # SkillsTool 由 AgentFactory 自动注册（因为传了 skill_registry）

    engine, prompt = AgentFactory.create(AgentConfig(
        llm_client=mock, tool_registry=reg, skill_registry=skill_reg,
        enable_hitl=False, enable_audit=False,
    ))

    p(0, "👤", "用户: 帮我校验一下商机的配置")
    s = GraphState(system_prompt=prompt, messages=[Message(role=MessageRole.USER, content="帮我校验一下商机的配置")])
    async for s in engine.run(s): pass

    p(0, "🎯", "执行链路:")
    p(1, "1️⃣", "LLM 决定调用 skills_tool(skill_name='verify_config', arguments={entity:'opportunity'})")
    p(1, "2️⃣", "SkillExecutor(inline) → 返回 SOP prompt（包含 4 个步骤）")
    p(1, "3️⃣", "LLM 收到 SOP prompt → 按步骤调用 query_schema(entity_items)")
    p(1, "4️⃣", "LLM 继续按 SOP → 调用 query_schema(entity_links)")
    p(1, "5️⃣", "LLM 综合数据 → 输出校验报告")
    p(0, "💬", f"Agent: {s.final_answer[:200]}")
    ok(f"Skill inline: LLM={mock.call_count}次 工具={s.total_tool_calls}次 (skills_tool + query_schema×2)")

    # 验证 system prompt 包含技能信息
    has_skills = "skills_tool" in prompt and "verify_config" in prompt
    ok(f"System prompt 包含技能描述: {has_skills}")


# ═══════════════════════════════════════════════════════════
# 场景 3: Skill fork（通用子 Agent）
# ═══════════════════════════════════════════════════════════

async def scene_3():
    hdr(3, "Skill fork — Pipeline 分析", "LLM → skills_tool → 子 Agent 独立执行 → 返回结果")
    p(0, "📖", "fork Skill 创建独立子 Agent，用 skill.prompt 作为 system_prompt，裁剪工具集")

    backend = CrmSimulatedBackend()
    mock = MockLLMClient()

    # 主 Agent: 调用 skills_tool
    mock.add_tool_call_response("skills_tool", {
        "skill_name": "pipeline_analysis",
        "arguments": {"filters": "全部商机"},
    }, text="让我调用 Pipeline 分析技能。")

    # 子 Agent 的 LLM 响应（共享同一个 mock）
    mock.add_tool_call_response("analyze_data", {
        "entity_api_key": "opportunity",
        "metrics": [{"field": "amount", "function": "sum"}, {"field": "amount", "function": "count"}],
        "group_by": "stage",
    })
    mock.add_text_response(
        "Pipeline 分析结果:\n"
        "- closing: 1个/18万\n- negotiation: 2个/148万\n- proposal: 2个/107万\n"
        "- qualification: 1个/15万\n- prospecting: 1个/85万\n"
        "总计: 7个商机/373万\n建议: 重点推进 negotiation 阶段的招行风控(120万)"
    )

    # 主 Agent 收到子 Agent 结果后总结
    mock.add_text_response("根据 Pipeline 分析，当前有 7 个商机总金额 373 万，建议重点推进招行风控项目。")

    skill_reg = SkillRegistry()
    register_crm_skills(skill_reg)

    reg = ToolRegistry()
    register_crm_tools(reg, backend)

    engine, prompt = AgentFactory.create(AgentConfig(
        llm_client=mock, tool_registry=reg, skill_registry=skill_reg,
        enable_hitl=False, enable_audit=False,
    ))

    p(0, "👤", "用户: 帮我分析一下商机 Pipeline")
    s = GraphState(system_prompt=prompt, messages=[Message(role=MessageRole.USER, content="帮我分析一下商机 Pipeline")])
    async for s in engine.run(s): pass

    p(0, "🎯", "执行链路:")
    p(1, "1️⃣", "LLM 决定调用 skills_tool(skill_name='pipeline_analysis')")
    p(1, "2️⃣", "SkillExecutor(fork) → 创建子 Agent")
    p(2, "🔧", "子 Agent 工具集: query_data, analyze_data（从 allowed_tools 裁剪）")
    p(2, "📜", "子 Agent system_prompt: skill.prompt（Pipeline 分析 SOP）")
    p(2, "⚡", "子 Agent 独立执行: analyze_data(group_by=stage) → 生成报告")
    p(1, "3️⃣", "子 Agent 结果返回给主 Agent")
    p(1, "4️⃣", "主 Agent 总结输出")
    p(0, "💬", f"Agent: {s.final_answer[:200]}")
    ok(f"Skill fork: 主Agent LLM + 子Agent LLM = {mock.call_count}次总调用")


# ═══════════════════════════════════════════════════════════
# 场景 4: Skill fork + SubagentConfig（专属子 Agent）
# ═══════════════════════════════════════════════════════════

async def scene_4():
    hdr(4, "Skill fork + SubagentConfig — 数据分析", "LLM → skills_tool → SubagentConfig 专属子 Agent")
    p(0, "📖", "指定 agent='data_analyst' 时，加载 SubagentConfig 构建专属子 Agent（独立 prompt/tools/预算）")

    backend = CrmSimulatedBackend()
    mock = MockLLMClient()

    # 主 Agent: 调用 skills_tool
    mock.add_tool_call_response("skills_tool", {
        "skill_name": "data_analysis",
        "arguments": {"entity": "opportunity", "dimensions": "按阶段和来源"},
    }, text="让我调用数据分析技能。")

    # 子 Agent（data_analyst）的 LLM 响应
    mock.add_tool_call_response("query_schema", {
        "query_type": "entity_items", "entity_api_key": "opportunity",
    })
    mock.add_tool_call_response("analyze_data", {
        "entity_api_key": "opportunity",
        "metrics": [{"field": "amount", "function": "sum"}, {"field": "amount", "function": "count"}],
        "group_by": "source",
    })
    mock.add_text_response(
        "数据分析报告:\n"
        "按来源: inbound 2个/165万, outbound 2个/100万, referral 2个/46万, partner 1个/62万\n"
        "发现: inbound 来源的商机金额最高，建议加大线上获客投入"
    )

    # 主 Agent 总结
    mock.add_text_response("数据分析完成: inbound 来源商机金额最高(165万)，建议加大线上获客。")

    skill_reg = SkillRegistry()
    register_crm_skills(skill_reg)

    subagent_reg = SubagentRegistry()
    register_crm_subagents(subagent_reg)

    reg = ToolRegistry()
    register_crm_tools(reg, backend)

    engine, prompt = AgentFactory.create(AgentConfig(
        llm_client=mock, tool_registry=reg,
        skill_registry=skill_reg, subagent_registry=subagent_reg,
        enable_hitl=False, enable_audit=False,
    ))

    p(0, "👤", "用户: 帮我分析商机数据，按阶段和来源维度")
    s = GraphState(system_prompt=prompt, messages=[Message(role=MessageRole.USER, content="帮我分析商机数据，按阶段和来源维度")])
    async for s in engine.run(s): pass

    p(0, "🎯", "执行链路:")
    p(1, "1️⃣", "LLM 决定调用 skills_tool(skill_name='data_analysis', arguments={entity:'opportunity'})")
    p(1, "2️⃣", "SkillExecutor 检测 skill.agent='data_analyst' → 查找 SubagentConfig")
    p(2, "📋", "SubagentConfig: name=data_analyst, max_llm=15, tools=[query_schema,query_data,analyze_data]")
    p(2, "📜", "专属 system_prompt: '你是一位专业的 CRM 数据分析师...'")
    p(1, "3️⃣", "构建专属子 Agent（独立 engine + 独立 prompt + 裁剪工具集）")
    p(1, "4️⃣", "子 Agent 执行: query_schema → analyze_data(group_by=source) → 生成报告")
    p(1, "5️⃣", "结果返回主 Agent → 总结输出")
    p(0, "💬", f"Agent: {s.final_answer[:200]}")
    ok(f"Skill fork+agent: 总 LLM={mock.call_count}次")


# ═══════════════════════════════════════════════════════════
# 对比总结
# ═══════════════════════════════════════════════════════════

async def summary():
    print(f"\n{'━'*70}")
    print("  Tool / Skill / SubAgent 对比总结")
    print(f"{'━'*70}")
    print("""
  ┌──────────────┬────────────────────────────────────────────┐
  │ 层级         │ 调用链路                                    │
  ├──────────────┼────────────────────────────────────────────┤
  │ Tool         │ LLM → function_calling → tool.call()       │
  │ (原子操作)    │ 一次调用，一次返回                           │
  ├──────────────┼────────────────────────────────────────────┤
  │ Skill inline │ LLM → skills_tool → SOP prompt 注入        │
  │ (SOP 注入)   │ → LLM 按 SOP 多次调用 Tool                  │
  ├──────────────┼────────────────────────────────────────────┤
  │ Skill fork   │ LLM → skills_tool → 创建子 Agent           │
  │ (通用子Agent) │ → 子 Agent 独立执行 → 返回结果              │
  ├──────────────┼────────────────────────────────────────────┤
  │ Skill fork   │ LLM → skills_tool → SubagentConfig         │
  │ +agent       │ → 专属 prompt/tools/预算 → 独立执行         │
  │ (专属子Agent) │                                            │
  └──────────────┴────────────────────────────────────────────┘
  """)


# ═══════════════════════════════════════════════════════════
# 主入口
# ═══════════════════════════════════════════════════════════

async def main():
    print("=" * 70)
    print("  DeepAgent Tool / Skill / SubAgent 全链路 Demo")
    print("=" * 70)

    await scene_1()   # Tool 直接调用
    await scene_2()   # Skill inline
    await scene_3()   # Skill fork（通用）
    await scene_4()   # Skill fork + SubagentConfig
    await summary()

    print(f"\n{'='*70}")
    print("  4 个场景全部完成 ✅")
    print(f"{'='*70}")


if __name__ == "__main__":
    asyncio.run(main())
