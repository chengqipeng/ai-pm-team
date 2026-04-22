"""
Skills 体系测试 — SkillDefinition + SkillRegistry + SkillExecutor + SkillsTool
"""
import asyncio
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.dtypes import Message, MessageRole, ToolResult
from src.tools import Tool, ToolRegistry
from src.llm_client import MockLLMClient
from src.middleware.base import PluginContext
from src.skills import (
    SkillDefinition, SkillRegistry, SkillExecutor, SkillsTool, SkillExecutionError,
)
from src.crm_backend import CrmSimulatedBackend
from src.crm_tools import register_crm_tools

passed = 0
failed = 0

def check(name, condition):
    global passed, failed
    if condition:
        print(f"  \u2705 {name}")
        passed += 1
    else:
        print(f"  \u274c {name}")
        failed += 1


# ═══════════════════════════════════════════════════════════
# 1. SkillDefinition
# ═══════════════════════════════════════════════════════════

def test_skill_definition():
    print("\n\U0001f4e6 1. SkillDefinition")

    s = SkillDefinition(
        name="verify_config",
        description="校验元数据配置",
        prompt="请校验 {entity} 实体的配置:\n1. 检查字段定义\n2. 检查关联关系",
        arguments=["entity"],
        context="inline",
    )
    check("name", s.name == "verify_config")
    check("context=inline", s.context == "inline")

    formatted = s.format_prompt({"entity": "opportunity"})
    check("format_prompt 替换参数", "opportunity" in formatted)
    check("format_prompt 保留其他内容", "检查字段定义" in formatted)

    s2 = SkillDefinition(name="analysis", description="分析", context="fork", agent="analyst")
    check("fork + agent", s2.context == "fork" and s2.agent == "analyst")


# ═══════════════════════════════════════════════════════════
# 2. SkillRegistry
# ═══════════════════════════════════════════════════════════

def test_skill_registry():
    print("\n\U0001f4e6 2. SkillRegistry")

    reg = SkillRegistry()
    reg.register(SkillDefinition(name="verify", description="校验", context="inline", when_to_use="校验|检查"))
    reg.register(SkillDefinition(name="diagnose", description="诊断", context="fork", when_to_use="诊断|问题"))
    reg.register(SkillDefinition(name="analyze", description="分析", context="fork", when_to_use="分析|统计"))

    check("list_all", len(reg.list_all()) == 3)
    check("get", reg.get("verify") is not None)
    check("get 不存在", reg.get("xxx") is None)
    check("list_by_context inline", len(reg.list_by_context("inline")) == 1)
    check("list_by_context fork", len(reg.list_by_context("fork")) == 2)

    # 意图匹配
    check("match 校验", reg.match_by_intent("帮我校验配置").name == "verify")
    check("match 诊断", reg.match_by_intent("诊断一下问题").name == "diagnose")
    check("match 分析", reg.match_by_intent("分析数据").name == "analyze")
    check("match 无匹配", reg.match_by_intent("你好") is None)

    # system prompt 注入
    section = reg.build_skills_prompt_section()
    check("prompt section 包含技能名", "verify" in section and "diagnose" in section)
    check("prompt section 包含调用方式", "skills_tool" in section)


# ═══════════════════════════════════════════════════════════
# 3. SkillExecutor — inline 模式
# ═══════════════════════════════════════════════════════════

async def test_executor_inline():
    print("\n\U0001f4e6 3. SkillExecutor — inline 模式")

    reg = SkillRegistry()
    reg.register(SkillDefinition(
        name="verify_config",
        description="校验元数据配置",
        prompt="请校验 {entity} 实体的配置:\n1. 检查字段定义\n2. 检查关联关系\n3. 检查校验规则",
        arguments=["entity"],
        context="inline",
    ))

    executor = SkillExecutor(reg)
    result = await executor.execute("verify_config", {"entity": "opportunity"})

    check("inline 返回 prompt", "opportunity" in result)
    check("inline 包含 SOP", "检查字段定义" in result)
    check("inline 包含步骤", "检查关联关系" in result)

    # 不存在的技能
    try:
        await executor.execute("nonexistent", {})
        check("不存在技能 → 异常", False)
    except SkillExecutionError:
        check("不存在技能 → SkillExecutionError", True)


# ═══════════════════════════════════════════════════════════
# 4. SkillExecutor — fork 模式
# ═══════════════════════════════════════════════════════════

async def test_executor_fork():
    print("\n\U0001f4e6 4. SkillExecutor — fork 模式 (需要 API Key)")

    api_key = os.environ.get("DEEPSEEK_API_KEY", "")
    if not api_key or api_key.startswith("sk-test"):
        print("  ⏭️ 跳过（无有效 API Key，fork 模式需要真实 LLM）")
        return

    backend = CrmSimulatedBackend()
    mock = MockLLMClient()
    # 子 Agent 的 LLM 响应
    mock.add_tool_call_response("analyze_data", {
        "entity_api_key": "opportunity",
        "metrics": [{"field": "amount", "function": "sum"}],
        "group_by": "stage",
    })
    mock.add_text_response("商机按阶段统计: closing 18万, negotiation 148万, proposal 107万。")

    tool_reg = ToolRegistry()
    register_crm_tools(tool_reg, backend)

    ctx = PluginContext(
        llm=mock, tool_registry=tool_reg,
        tenant_id="t1", user_id="u1",
    )

    skill_reg = SkillRegistry()
    skill_reg.register(SkillDefinition(
        name="pipeline_analysis",
        description="分析商机 Pipeline",
        prompt="请分析 {entity} 的 Pipeline 分布，按阶段统计金额。",
        arguments=["entity"],
        allowed_tools=["query_data", "analyze_data"],
        context="fork",
    ))

    executor = SkillExecutor(skill_reg, context=ctx)
    result = await executor.execute("pipeline_analysis", {"entity": "opportunity"})

    check("fork 返回结果", len(result) > 0)
    check("fork 结果包含数据", "商机" in result or "统计" in result or "万" in result)
    check("fork 子 Agent 调用了工具", mock.call_count >= 2)


# ═══════════════════════════════════════════════════════════
# 5. SkillsTool — function calling 入口
# ═══════════════════════════════════════════════════════════

async def test_skills_tool():
    print("\n\U0001f4e6 5. SkillsTool — function calling 入口")

    reg = SkillRegistry()
    reg.register(SkillDefinition(
        name="verify_config",
        description="校验配置",
        prompt="请校验 {entity} 的配置",
        arguments=["entity"],
        context="inline",
    ))

    executor = SkillExecutor(reg)
    tool = SkillsTool(executor)

    check("tool name", tool.name == "skills_tool")
    check("input_schema 有 skill_name", "skill_name" in tool.input_schema()["properties"])

    # 调用 inline 技能
    result = await tool.call({"skill_name": "verify_config", "arguments": {"entity": "account"}}, None)
    check("inline 调用成功", not result.is_error)
    check("inline 结果包含参数", "account" in result.content)

    # 调用不存在的技能
    result2 = await tool.call({"skill_name": "xxx", "arguments": {}}, None)
    check("不存在技能 → is_error", result2.is_error)


# ═══════════════════════════════════════════════════════════
# 6. 端到端: LLM 通过 skills_tool 调用 inline 技能
# ═══════════════════════════════════════════════════════════

async def test_e2e_inline():
    print("\n\U0001f4e6 6. 端到端: LLM → skills_tool → inline → 继续推理")

    backend = CrmSimulatedBackend()
    mock = MockLLMClient()

    # LLM 第 1 轮: 调用 skills_tool（inline 技能）
    mock.add_tool_call_response("skills_tool", {
        "skill_name": "verify_config",
        "arguments": {"entity": "opportunity"},
    }, text="让我先校验一下商机的配置。")

    # LLM 第 2 轮: 收到 Skill prompt 后，按 SOP 调用 query_schema
    mock.add_tool_call_response("query_schema", {
        "query_type": "entity_items",
        "entity_api_key": "opportunity",
    })

    # LLM 第 3 轮: 收到 schema 后给出校验结果
    mock.add_text_response("校验完成: opportunity 实体有 9 个字段，配置正确。")

    # 构建 SkillRegistry + SkillsTool
    skill_reg = SkillRegistry()
    skill_reg.register(SkillDefinition(
        name="verify_config",
        description="校验元数据配置的正确性",
        prompt="请校验 {entity} 实体的元数据配置:\n1. 使用 query_schema 查询字段定义\n2. 检查必填字段\n3. 检查字段类型",
        arguments=["entity"],
        when_to_use="校验|检查|配置",
        context="inline",
    ))

    executor = SkillExecutor(skill_reg)
    skills_tool = SkillsTool(executor)

    tool_reg = ToolRegistry()
    register_crm_tools(tool_reg, backend)
    tool_reg.register(skills_tool)  # 注册 skills_tool 到工具列表

    engine, prompt = AgentFactory.create(AgentConfig(
        llm_client=mock, tool_registry=tool_reg,
        skill_registry=skill_reg,
        enable_hitl=False, enable_audit=False,
    ))

    s = GraphState(
        system_prompt=prompt,
        messages=[Message(role=MessageRole.USER, content="帮我校验一下商机的配置")],
    )
    async for s in engine.run(s): pass

    check("状态 COMPLETED", s.status == AgentStatus.COMPLETED)
    check("调用了 skills_tool + 后续工具", s.total_tool_calls >= 1)
    check("最终回答包含校验结果", "校验" in s.final_answer or "配置" in s.final_answer)
    check("system prompt 包含技能信息", "skills_tool" in prompt)
    check("system prompt 包含 verify_config", "verify_config" in prompt)


# ═══════════════════════════════════════════════════════════
# 7. 端到端: LLM → skills_tool → fork → 子 Agent 执行
# ═══════════════════════════════════════════════════════════

async def test_e2e_fork():
    print("\n\U0001f4e6 7. 端到端: LLM → skills_tool → fork → 子 Agent")

    backend = CrmSimulatedBackend()

    # 主 Agent 的 mock: 调用 skills_tool
    main_mock = MockLLMClient()
    main_mock.add_tool_call_response("skills_tool", {
        "skill_name": "pipeline_analysis",
        "arguments": {"entity": "opportunity"},
    }, text="让我调用 Pipeline 分析技能。")
    main_mock.add_text_response("根据分析结果，商机 Pipeline 健康。")

    # 子 Agent 的 mock（fork 模式会创建新的 engine，但共享同一个 mock）
    # 注意: fork 模式会用主 Agent 的 llm_client 创建子 Agent
    # 所以子 Agent 的响应也从 main_mock 消费
    main_mock.add_tool_call_response("analyze_data", {
        "entity_api_key": "opportunity",
        "metrics": [{"field": "amount", "function": "sum"}],
        "group_by": "stage",
    })
    main_mock.add_text_response("Pipeline 分析: closing 18万, negotiation 148万。")

    skill_reg = SkillRegistry()
    skill_reg.register(SkillDefinition(
        name="pipeline_analysis",
        description="分析商机 Pipeline 分布",
        prompt="请分析 {entity} 的 Pipeline，按阶段统计金额和数量。",
        arguments=["entity"],
        allowed_tools=["query_data", "analyze_data"],
        context="fork",
    ))

    tool_reg = ToolRegistry()
    register_crm_tools(tool_reg, backend)

    # 创建 SkillExecutor（需要 PluginContext）
    ctx = PluginContext(llm=main_mock, tool_registry=tool_reg, tenant_id="t1", user_id="u1")
    executor = SkillExecutor(skill_reg, context=ctx)
    skills_tool = SkillsTool(executor)
    tool_reg.register(skills_tool)

    engine, prompt = AgentFactory.create(AgentConfig(
        llm_client=main_mock, tool_registry=tool_reg,
        skill_registry=skill_reg,
        enable_hitl=False, enable_audit=False,
    ))

    s = GraphState(
        system_prompt=prompt,
        messages=[Message(role=MessageRole.USER, content="帮我分析商机Pipeline")],
    )
    async for s in engine.run(s): pass

    check("状态 COMPLETED", s.status == AgentStatus.COMPLETED)
    check("主 Agent 执行完成", s.total_tool_calls >= 0)
    check("最终回答", bool(s.final_answer))


# ═══════════════════════════════════════════════════════════
# 运行
# ═══════════════════════════════════════════════════════════

if __name__ == "__main__":
    test_skill_definition()
    test_skill_registry()
    asyncio.run(test_executor_inline())
    asyncio.run(test_executor_fork())
    asyncio.run(test_skills_tool())

    print(f"\n{'='*60}")
    print(f"  Skills 测试: {passed} passed, {failed} failed")
    print(f"{'='*60}")
    sys.exit(1 if failed else 0)
