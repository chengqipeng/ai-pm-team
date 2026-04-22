"""
LangChain Agent 迁移测试 — 验证 create_agent 与 DeepAgent 工具/技能的集成
"""
import asyncio
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("DEEPSEEK_API_KEY", "sk-a86b7e7ca89e4a4283c0a8a7bcb34b9c")

from src.tools import ToolRegistry
from src.crm_backend import CrmSimulatedBackend
from src.crm_tools import register_crm_tools
from src.skills import SkillDefinition, SkillRegistry
from src.langchain_agent import (
    adapt_tools, create_deep_agent, LangChainAgentConfig,
    DeepAgentMiddlewareAdapter,
)
from langchain_core.messages import ToolMessage

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


def test_tool_adapter():
    print("\n\U0001f4e6 1. Tool → BaseTool 适配")

    backend = CrmSimulatedBackend()
    reg = ToolRegistry()
    register_crm_tools(reg, backend)

    lc_tools = adapt_tools(reg)
    check(f"适配 {len(lc_tools)} 个工具", len(lc_tools) == 5)

    names = {t.name for t in lc_tools}
    check("query_schema", "query_schema" in names)
    check("query_data", "query_data" in names)
    check("modify_data", "modify_data" in names)
    check("analyze_data", "analyze_data" in names)
    check("ask_user", "ask_user" in names)

    # 测试工具执行
    query_tool = next(t for t in lc_tools if t.name == "query_data")
    result = asyncio.run(query_tool.ainvoke(
        '{"action": "count", "entity_api_key": "account"}'
    ))
    check("工具执行返回结果", "5" in str(result) or "account" in str(result))


def test_create_agent():
    print("\n\U0001f4e6 2. create_deep_agent 创建")

    backend = CrmSimulatedBackend()
    reg = ToolRegistry()
    register_crm_tools(reg, backend)

    skill_reg = SkillRegistry()
    skill_reg.register(SkillDefinition(
        name="verify_config",
        description="校验配置",
        prompt="校验 {entity} 的配置",
        arguments=["entity"],
        context="inline",
        when_to_use="校验|检查",
    ))

    config = LangChainAgentConfig(
        model="deepseek-chat",
        api_key=os.environ.get("DEEPSEEK_API_KEY", ""),
        api_base="https://api.deepseek.com",
        tool_registry=reg,
        skill_registry=skill_reg,
        system_prompt="你是 CRM 助手。必须使用工具获取数据。",
    )

    agent = create_deep_agent(config)
    check("Agent 创建成功", agent is not None)
    check("Agent 类型正确", "CompiledStateGraph" in type(agent).__name__)


async def test_agent_invoke():
    print("\n\U0001f4e6 3. Agent 真实调用（DeepSeek API）")

    api_key = os.environ.get("DEEPSEEK_API_KEY", "")
    if not api_key:
        print("  ⏭️ 跳过（无 API Key）")
        return

    backend = CrmSimulatedBackend()
    reg = ToolRegistry()
    register_crm_tools(reg, backend)

    config = LangChainAgentConfig(
        model="deepseek-chat",
        api_key=api_key,
        api_base="https://api.deepseek.com",
        tool_registry=reg,
        system_prompt=(
            "你是 CRM 助手。必须使用 query_data 工具查询数据，禁止编造。\n"
            "数据库有: account(客户), opportunity(商机), contact(联系人)\n"
            "用中文回答。"
        ),
    )

    agent = create_deep_agent(config)

    print("  ⏳ 调用 DeepSeek API...")
    result = await agent.ainvoke({
        "messages": [
            {"role": "user", "content": "系统中有多少个客户？"}
        ]
    })

    messages = result.get("messages", [])
    check("有返回消息", len(messages) > 0)

    # 检查是否调用了工具
    tool_calls = [m for m in messages if hasattr(m, "tool_calls") and m.tool_calls]
    tool_results = [m for m in messages if isinstance(m, ToolMessage)]
    check("调用了工具", len(tool_calls) > 0 or len(tool_results) > 0)

    # 最后一条消息应该是 AI 的回答
    last = messages[-1]
    content = last.content if hasattr(last, "content") else str(last)
    print(f"  💬 回答: {content[:150]}")
    check("有最终回答", len(content) > 0)


if __name__ == "__main__":
    test_tool_adapter()
    test_create_agent()
    asyncio.run(test_agent_invoke())

    print(f"\n{'='*60}")
    print(f"  LangChain Agent 测试: {passed} passed, {failed} failed")
    print(f"{'='*60}")
    sys.exit(1 if failed else 0)
