#!/usr/bin/env python3
"""
DeepAgent 全功能 Demo — 覆盖所有 37 个测试场景

运行: poetry run python demo.py

模块:
  A. LangChain Agent 集成（Tool 适配 / Agent 创建 / 真实 API 调用）
  B. 技能系统（SkillDefinition / SkillRegistry / SkillExecutor / SkillLoader）
  C. Pydantic 工具（SkillsTool / AgentTool / AgentFactory）
  D. 中间件栈（14 个中间件全覆盖）
  E. 三层上下文压缩 + 熔断
  F. 记忆系统（FTS5 存储 / FTSEngine / 防抖队列 / 记忆提示词）
  G. 多模型路由 / 自动技能生成 / AgentConfig YAML 发现
  H. ThreadState / OutputRender / Plugin 生命周期
  I. 真实豆包 API 端到端调用
"""
import asyncio
import json
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(__file__))
os.environ.setdefault("DOUBAO_API_KEY", "651621e7-e495-4728-93ef-ed380e9ddcd1")

passed = 0
failed = 0
total_sections = 0


def section(title):
    global total_sections
    total_sections += 1
    print(f"\n{'━'*70}")
    print(f"  {total_sections}. {title}")
    print(f"{'━'*70}")


def check(name, condition):
    global passed, failed
    if condition:
        print(f"  ✅ {name}")
        passed += 1
    else:
        print(f"  ❌ {name}")
        failed += 1


# ═══════════════════════════════════════════════════════════
# A. LangChain Agent 集成
# ═══════════════════════════════════════════════════════════

async def demo_tool_adapter():
    section("Tool → BaseTool 适配")
    from src.tools.base import ToolRegistry
    from src.tools.crm_backend import CrmSimulatedBackend
    from src.tools.crm_tools import register_crm_tools
    from src.agents.langchain_agent import adapt_tools

    backend = CrmSimulatedBackend()
    reg = ToolRegistry()
    register_crm_tools(reg, backend)
    lc_tools = adapt_tools(reg)

    check(f"适配 {len(lc_tools)} 个工具", len(lc_tools) == 5)
    names = {t.name for t in lc_tools}
    check("包含 query_schema/query_data/modify_data/analyze_data/ask_user",
          names == {"query_schema", "query_data", "modify_data", "analyze_data", "ask_user"})

    # 执行工具
    query_tool = next(t for t in lc_tools if t.name == "query_data")
    result = await query_tool.ainvoke('{"action": "count", "entity_api_key": "account"}')
    check("工具执行返回结果", "5" in str(result) or "account" in str(result))


def demo_create_agent():
    section("create_deep_agent 创建")
    from src.tools.base import ToolRegistry
    from src.tools.crm_backend import CrmSimulatedBackend
    from src.tools.crm_tools import register_crm_tools
    from src.skills.base import SkillDefinition, SkillRegistry
    from src.agents.langchain_agent import create_deep_agent, LangChainAgentConfig

    from src.core.prompt_builder import build_system_prompt as _build_prompt

    backend = CrmSimulatedBackend()
    reg = ToolRegistry()
    register_crm_tools(reg, backend)
    skill_reg = SkillRegistry()
    skill_reg.register(SkillDefinition(name="verify", description="校验", prompt="校验 {entity}",
                                        arguments=["entity"], context="inline", when_to_use="校验"))

    config = LangChainAgentConfig(
        model="doubao-1-5-pro-32k-250115", api_key=os.environ["DOUBAO_API_KEY"],
        api_base="https://ark.cn-beijing.volces.com/api/v3/", tool_registry=reg,
        skill_registry=skill_reg,
        system_prompt=_build_prompt(agent_name="CRM-Agent", skills=skill_reg.list_all()),
    )
    agent = create_deep_agent(config)
    check("Agent 创建成功", agent is not None)
    check("Agent 类型正确", "CompiledStateGraph" in type(agent).__name__)


# ═══════════════════════════════════════════════════════════
# B. 技能系统
# ═══════════════════════════════════════════════════════════

def demo_skill_definition():
    section("SkillDefinition + SkillRegistry")
    from src.skills.base import SkillDefinition, SkillRegistry

    s = SkillDefinition(name="verify_config", description="校验配置",
                        prompt="请校验 {entity} 的配置:\n1. 检查字段\n2. 检查关联",
                        arguments=["entity"], context="inline")
    check("name", s.name == "verify_config")
    check("context=inline", s.context == "inline")
    formatted = s.format_prompt({"entity": "opportunity"})
    check("format_prompt 替换参数", "opportunity" in formatted)
    check("format_prompt 保留其他内容", "检查字段" in formatted)

    s2 = SkillDefinition(name="analysis", description="分析", context="fork", agent="analyst")
    check("fork + agent", s2.context == "fork" and s2.agent == "analyst")

    reg = SkillRegistry()
    reg.register(SkillDefinition(name="verify", description="校验", context="inline", when_to_use="校验|检查"))
    reg.register(SkillDefinition(name="diagnose", description="诊断", context="fork", when_to_use="诊断|问题"))
    reg.register(SkillDefinition(name="analyze", description="分析", context="fork", when_to_use="分析|统计"))

    check("list_all=3", len(reg.list_all()) == 3)
    check("get", reg.get("verify") is not None)
    check("get 不存在", reg.get("xxx") is None)
    check("list_by_context inline=1", len(reg.list_by_context("inline")) == 1)
    check("list_by_context fork=2", len(reg.list_by_context("fork")) == 2)
    check("match_by_intent 校验", reg.match_by_intent("帮我校验配置").name == "verify")
    check("match_by_intent 诊断", reg.match_by_intent("诊断一下问题").name == "diagnose")
    check("match_by_intent 分析", reg.match_by_intent("分析数据").name == "analyze")
    check("match_by_intent 无匹配", reg.match_by_intent("你好") is None)
    section_text = reg.build_skills_prompt_section()
    check("prompt section 包含技能名", "verify" in section_text and "diagnose" in section_text)
    check("prompt section 包含调用方式", "skills_tool" in section_text)


async def demo_skill_executor():
    section("SkillExecutor inline + SkillsTool + SkillExecutor 属性")
    from src.skills.base import SkillDefinition, SkillRegistry, SkillExecutor, SkillsTool, SkillExecutionError

    reg = SkillRegistry()
    reg.register(SkillDefinition(name="verify_config", description="校验",
                                  prompt="请校验 {entity} 的配置:\n1. 检查字段定义\n2. 检查关联关系\n3. 检查校验规则",
                                  arguments=["entity"], context="inline"))
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

    # SkillsTool (旧版 Tool 基类)
    tool = SkillsTool(executor)
    check("SkillsTool name", tool.name == "skills_tool")
    check("input_schema 有 skill_name", "skill_name" in tool.input_schema()["properties"])
    tr = await tool.call({"skill_name": "verify_config", "arguments": {"entity": "account"}}, None)
    check("inline 调用成功", not tr.is_error)
    check("inline 结果包含参数", "account" in tr.content)
    tr2 = await tool.call({"skill_name": "xxx", "arguments": {}}, None)
    check("不存在技能 → is_error", tr2.is_error)

    # SkillExecutor._agent_factory 属性
    check("默认 _agent_factory 为 None", executor._agent_factory is None)
    executor._agent_factory = "injected"
    check("注入后可访问", executor._agent_factory == "injected")
    executor._agent_factory = None  # 还原


def demo_skill_loader():
    section("SKILL.md 文件加载")
    from src.skills.base import SkillLoader, SkillValidationError

    content = """---
description: 审查代码质量
when_to_use: 代码审查|review
arguments:
  - code
  - language
allowed-tools: []
context: inline
---

你是代码审查专家。请审查 {code}。
"""
    skill = SkillLoader.parse(content)
    check("parse description", skill.description == "审查代码质量")
    check("parse context=inline", skill.context == "inline")
    check("parse arguments", skill.arguments == ["code", "language"])

    # 从目录发现
    skills_dir = os.path.join(os.path.dirname(__file__), "skills", "definitions")
    if os.path.isdir(skills_dir):
        skills = SkillLoader.discover(skills_dir)
        check(f"discover: {len(skills)} skills", len(skills) >= 2)

    # 验证失败
    try:
        bad = SkillLoader.parse("---\ncontext: inline\n---\nprompt")
        SkillLoader.validate(bad)
        check("validation: missing description", False)
    except SkillValidationError:
        check("validation: missing description → error", True)


# ═══════════════════════════════════════════════════════════
# C. Pydantic 工具 + AgentFactory
# ═══════════════════════════════════════════════════════════

def demo_exceptions():
    section("统一异常体系")
    from src.core.exceptions import (DeepAgentError, ConfigurationError, SkillValidationError,
                                 SkillExecutionError, SkillActivationError,
                                 AuthorizationDeniedError, CredentialError)
    check("DeepAgentError 是 Exception", issubclass(DeepAgentError, Exception))
    check("SkillExecutionError 继承 DeepAgentError", issubclass(SkillExecutionError, DeepAgentError))
    check("SkillValidationError 继承 DeepAgentError", issubclass(SkillValidationError, DeepAgentError))

    e1 = ConfigurationError(missing_fields=["api_key", "model"])
    check("ConfigurationError.missing_fields", e1.missing_fields == ["api_key", "model"])
    check("ConfigurationError 消息", "api_key" in str(e1))

    e2 = SkillExecutionError(skill_name="verify", detail="超时")
    check("SkillExecutionError.skill_name", e2.skill_name == "verify")
    check("SkillExecutionError.detail", e2.detail == "超时")

    e3 = SkillActivationError("analyze", missing_tools=["query_data"])
    check("SkillActivationError", "query_data" in str(e3))

    e4 = AuthorizationDeniedError("modify_data", "只读权限")
    check("AuthorizationDeniedError", "modify_data" in str(e4))

    e5 = CredentialError("doubao", "key expired")
    check("CredentialError", "doubao" in str(e5))


async def demo_pydantic_skills_tool():
    section("Pydantic SkillsTool (BaseTool)")
    from src.skills.base import SkillDefinition, SkillRegistry, SkillExecutor
    from src.tools.skills_tool import SkillsTool

    reg = SkillRegistry()
    reg.register(SkillDefinition(name="verify", description="校验", prompt="校验 {entity}",
                                  arguments=["entity"], context="inline"))
    executor = SkillExecutor(reg)
    tool = SkillsTool(skill_executor=executor)
    check("Pydantic name", tool.name == "skills_tool")
    check("args_schema", tool.args_schema is not None)
    result = await tool._arun(skill_name="verify", arguments={"entity": "account"})
    check("执行成功", "account" in result)


def demo_agent_tool():
    section("AgentTool 结构")
    from src.tools.agent_tool import AgentTool, AgentToolInput
    tool = AgentTool()
    check("name=agent_tool", tool.name == "agent_tool")
    check("args_schema", tool.args_schema is AgentToolInput)
    check("无 factory → 错误", "未配置" in tool._run(instruction="test"))


def demo_agent_factory():
    section("AgentFactory (LRU 缓存 + 深度限制)")
    from src.agents.agent_factory import AgentFactory
    from langchain_openai import ChatOpenAI

    model = ChatOpenAI(model="doubao-1-5-pro-32k-250115", api_key=os.environ["DOUBAO_API_KEY"],
                       base_url="https://ark.cn-beijing.volces.com/api/v3/")
    from src.core.prompt_builder import build_system_prompt as _build
    factory = AgentFactory(default_model=model, default_system_prompt=_build(agent_name="CRM-Agent"))
    check("创建成功", factory is not None)
    check("max_depth=3", factory._max_depth == 3)
    check("cache 为空", len(factory._cache) == 0)
    factory.invalidate()
    check("invalidate 不崩溃", True)


def demo_prompt_builder():
    section("PromptBuilder 结构化提示词")
    from src.core.prompt_builder import build_system_prompt
    from src.skills.base import SkillDefinition

    p1 = build_system_prompt(agent_name="TestAgent")
    check("包含角色定义", "CRM" in p1 or "智能业务助手" in p1)
    check("包含工具使用规范", "工具" in p1)
    check("包含安全边界", "安全" in p1 or "确认" in p1)

    skills = [
        SkillDefinition(name="verify", description="校验配置", when_to_use="校验",
                        arguments=["entity"], context="inline", prompt="请校验 {entity}"),
        SkillDefinition(name="analyze", description="分析数据", context="fork"),
    ]
    p2 = build_system_prompt(skills=skills)
    check("包含 <skills> 标签", "<skills>" in p2)
    check("包含 inline 技能 prompt", "请校验" in p2)
    check("包含 fork 技能", "analyze" in p2)

    p3 = build_system_prompt(memory_context="<memory>用户偏好中文</memory>")
    check("包含记忆上下文", "用户偏好中文" in p3)


# ═══════════════════════════════════════════════════════════
# D. 中间件栈
# ═══════════════════════════════════════════════════════════

def demo_middleware_imports():
    section("14 个中间件导入验证")
    from langchain.agents.middleware.types import AgentMiddleware
    from src.middleware import (
        AgentLoggingMiddleware, ClarificationMiddleware, DanglingToolCallMiddleware,
        GuardrailMiddleware, InputTransformMiddleware, LoopDetectionMiddleware,
        MemoryMiddleware, MemoryEngine, MemoryDimension, NoopMemoryEngine,
        OutputValidationMiddleware, OutputRenderMiddleware,
        SubagentLimitMiddleware, SummarizationMiddleware, TitleMiddleware,
        TodoMiddleware, ToolErrorHandlingMiddleware,
    )
    all_mw = [AgentLoggingMiddleware, ClarificationMiddleware, DanglingToolCallMiddleware,
              GuardrailMiddleware, InputTransformMiddleware, LoopDetectionMiddleware,
              MemoryMiddleware, OutputValidationMiddleware, OutputRenderMiddleware,
              SubagentLimitMiddleware, SummarizationMiddleware, TitleMiddleware,
              TodoMiddleware, ToolErrorHandlingMiddleware]
    for cls in all_mw:
        check(f"{cls.__name__}", issubclass(cls, AgentMiddleware))
    check("NoopMemoryEngine 实现 MemoryEngine", issubclass(NoopMemoryEngine, MemoryEngine))
    check("MemoryDimension 有 4 个维度", len(MemoryDimension) == 4)


async def demo_guardrail():
    section("GuardrailMiddleware 白名单拦截")
    from unittest.mock import MagicMock
    from langchain_core.messages import ToolMessage
    from src.middleware.guardrail import GuardrailMiddleware

    gw = GuardrailMiddleware(allowed_tools=["query_data"])
    async def passthrough(r):
        return ToolMessage(content="ok", tool_call_id=r.tool_call["id"], name=r.tool_call["name"])

    req_ok = MagicMock(); req_ok.tool_call = {"id": "c1", "name": "query_data", "args": {}}
    r1 = await gw.awrap_tool_call(req_ok, passthrough)
    check("白名单内 → 放行", r1.content == "ok")

    req_bad = MagicMock(); req_bad.tool_call = {"id": "c2", "name": "modify_data", "args": {}}
    r2 = await gw.awrap_tool_call(req_bad, passthrough)
    check("白名单外 → 拦截", r2.status == "error")


async def demo_clarification():
    section("ClarificationMiddleware 澄清中断")
    from unittest.mock import MagicMock
    from langchain_core.messages import ToolMessage
    from src.middleware.clarification import ClarificationMiddleware

    mw = ClarificationMiddleware()
    async def passthrough(r):
        return ToolMessage(content="ok", tool_call_id=r.tool_call["id"], name=r.tool_call["name"])

    # 非 ask_clarification → 放行
    req_normal = MagicMock()
    req_normal.tool_call = {"id": "c1", "name": "query_data", "args": {}}
    r1 = await mw.awrap_tool_call(req_normal, passthrough)
    check("非 clarification → 放行", r1.content == "ok")

    # ask_clarification → 拦截
    req = MagicMock()
    req.tool_call = {"id": "c2", "name": "ask_clarification",
                     "args": {"question": "你要查哪个客户？", "clarification_type": "missing_info",
                              "options": ["A公司", "B公司"]}}
    r = await mw.awrap_tool_call(req, passthrough)
    check("拦截 ask_clarification", r.name == "ask_clarification")
    check("包含问题", "客户" in r.content)
    check("包含选项", "A公司" in r.content)


async def demo_memory_middleware():
    section("MemoryMiddleware + FTSMemoryEngine（真实 LLM）")
    from src.middleware.memory import MemoryMiddleware, MemoryDimension
    from src.memory.fts_engine import FTSMemoryEngine
    from src.memory.storage import MemoryStorage
    from langchain_openai import ChatOpenAI
    import tempfile, shutil

    tmp = tempfile.mkdtemp()
    try:
        llm = ChatOpenAI(model="doubao-1-5-pro-32k-250115",
                         api_key="651621e7-e495-4728-93ef-ed380e9ddcd1",
                         base_url="https://ark.cn-beijing.volces.com/api/v3/", max_tokens=1024)
        storage = MemoryStorage(storage_dir=tmp)
        engine = FTSMemoryEngine(storage=storage, llm=llm)
        mw = MemoryMiddleware(engine=engine)
        check("engine 属性", mw.engine is engine)
        check("FTSMemoryEngine rewrite", len(await engine.rewrite_query([], "test")) > 0)
        result = await engine.retrieve("test")
        check("空库检索返回空", len(result.items) == 0)
        storage.close()
    finally:
        shutil.rmtree(tmp)


async def demo_plugin_lifecycle():
    section("Plugin 生命周期")
    from src.plugins.base import PluginRegistry, PluginManifest, MemoryPlugin, NotificationPlugin

    registry = PluginRegistry()
    mem = MemoryPlugin(backend="memory")
    mem.seed([{"category": "profile", "content": "测试用户"}])
    registry.register(mem, PluginManifest(name="memory", description="记忆"))
    notif = NotificationPlugin(channels=["in_app"])
    registry.register(notif, PluginManifest(name="notification", description="通知"))

    check("注册 2 个 Plugin", len(registry.all_plugins) == 2)
    await registry.initialize_all()
    check("初始化完成", len(registry.initialized_plugins) == 2)

    health = await registry.health_check_all()
    check("健康检查通过", all(health.values()))

    recalled = await mem.recall("测试", categories=["profile"])
    check("MemoryPlugin recall", len(recalled) == 1)
    await mem.commit({"category": "cases", "content": "新记忆"})
    check("MemoryPlugin commit", len(mem._store) == 2)

    await notif.send("测试通知", channel="in_app")
    check("NotificationPlugin send", len(notif.sent_messages) == 1)

    await registry.shutdown_all()
    check("关闭完成", len(registry.initialized_plugins) == 0)


# ═══════════════════════════════════════════════════════════
# E. 三层上下文压缩 + 熔断
# ═══════════════════════════════════════════════════════════

def demo_micro_compact():
    section("MicroCompact — 裁剪旧 ToolMessage")
    from langchain_core.messages import HumanMessage, AIMessage, ToolMessage
    from src.middleware.summarization import SummarizationMiddleware

    class R: pass

    mw = SummarizationMiddleware(max_tokens=500, micro_threshold=0.2,
                                  auto_threshold=0.75, full_threshold=0.90, tool_output_max_chars=100)
    messages = [
        HumanMessage(content="查询客户数据"), AIMessage(content="", tool_calls=[{"id": "tc1", "name": "q", "args": {}}]),
        ToolMessage(content="x" * 500, tool_call_id="tc1", name="q"),
        AIMessage(content="查到了结果"), HumanMessage(content="再查一下详情"),
        AIMessage(content="", tool_calls=[{"id": "tc2", "name": "q2", "args": {}}]),
        ToolMessage(content="短结果", tool_call_id="tc2", name="q2"),
        HumanMessage(content="帮我总结一下"), AIMessage(content="好的我来总结"), HumanMessage(content="继续分析"),
    ]
    result = mw.before_model({"messages": messages}, R())
    if result:
        tool_msgs = [m for m in result["messages"] if isinstance(m, ToolMessage)]
        old = next((m for m in tool_msgs if m.name == "q"), None)
        check("旧 ToolMessage 被裁剪", old and len(old.content) < 500)
        check("裁剪标记", old and "truncated" in old.content)
    else:
        check("MicroCompact 触发", False); check("裁剪标记", False)


def demo_auto_compact():
    section("AutoCompact — 结构化摘要")
    from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
    from src.middleware.summarization import SummarizationMiddleware

    class R: pass

    mw = SummarizationMiddleware(max_tokens=200, micro_threshold=0.1, auto_threshold=0.3, full_threshold=0.95)
    messages = []
    for i in range(10):
        messages.append(HumanMessage(content=f"用户消息 {i} " + "内容" * 15))
        messages.append(AIMessage(content=f"AI 回复 {i} " + "回答" * 15))
    result = mw.before_model({"messages": messages}, R())
    check("AutoCompact 触发", result is not None)
    if result:
        check("首条是 SystemMessage", isinstance(result["messages"][0], SystemMessage))
        check("包含 context_summary", "context_summary" in result["messages"][0].content or "摘要" in result["messages"][0].content)
        check("消息数量减少", len(result["messages"]) < len(messages))


def demo_full_compact():
    section("FullCompact — 全量压缩 + 重注入")
    from langchain_core.messages import HumanMessage, AIMessage, ToolMessage, SystemMessage
    from src.middleware.summarization import SummarizationMiddleware

    class R: pass

    mw = SummarizationMiddleware(max_tokens=100, micro_threshold=0.3, auto_threshold=0.5, full_threshold=0.6)
    messages = []
    for i in range(8):
        messages.append(HumanMessage(content=f"问题 {i} " + "详细" * 30))
        messages.append(AIMessage(content="", tool_calls=[{"id": f"tc{i}", "name": "t", "args": {}}]))
        messages.append(ToolMessage(content=f"结果 {i} " + "数据" * 20, tool_call_id=f"tc{i}", name="t"))
        messages.append(AIMessage(content=f"回答 {i} " + "分析" * 20))
    result = mw.before_model({"messages": messages}, R())
    check("FullCompact 触发", result is not None)
    if result:
        check("包含 full_compact_summary", "full_compact_summary" in result["messages"][0].content)
        check("包含预算重置", "重置" in result["messages"][0].content)
        check("消息大幅减少", len(result["messages"]) < len(messages) // 2)


def demo_circuit_breaker():
    section("压缩熔断 + 向后兼容")
    from src.middleware.summarization import SummarizationMiddleware
    from langchain_core.messages import HumanMessage, AIMessage

    class R: pass

    mw = SummarizationMiddleware(max_tokens=100, max_consecutive_failures=2)
    mw._consecutive_failures = 2
    result = mw.before_model({"messages": [HumanMessage(content="x" * 500)] * 10}, R())
    check("熔断后跳过压缩", result is None)
    mw.reset_circuit_breaker()
    check("重置后计数归零", mw._consecutive_failures == 0)

    # 向后兼容旧参数
    mw_old = SummarizationMiddleware(max_tokens=100_000, trigger_ratio=0.75)
    check("旧参数 trigger_ratio 兼容", mw_old._auto_trigger == 75_000)
    result2 = mw_old.before_model({"messages": [HumanMessage(content="hi"), AIMessage(content="hello")]}, R())
    check("少量消息不触发", result2 is None)


def demo_tool_loader():
    section("ToolLoader 按名注册 + 加载")
    from src.tools.loader import ToolLoader
    from langchain_core.tools import StructuredTool

    loader = ToolLoader()
    def dummy(x: str = "") -> str: return "ok"
    for name in ["tool_a", "tool_b", "tool_c"]:
        loader.register_tool(name, StructuredTool.from_function(func=dummy, name=name, description=name))
    check("注册 3 个", len(loader) == 3)
    check("按名加载", len(loader.load_tools_by_names(["tool_a", "tool_c", "xxx"])) == 2)
    check("全量加载", len(loader.load_tools()) == 3)


# ═══════════════════════════════════════════════════════════
# F. 记忆系统
# ═══════════════════════════════════════════════════════════

def demo_memory_storage():
    section("MemoryStorage FTS5 全文搜索")
    tmp = tempfile.mkdtemp()
    try:
        from src.memory.storage import MemoryStorage
        storage = MemoryStorage(storage_dir=tmp)
        storage.add("u1", "客户张三喜欢微信沟通", dimension="user_profile")
        storage.add("u1", "商机金额 50 万", dimension="customer_context")
        storage.add("u1", "上次查询了客户列表", dimension="task_history")
        storage.add("u2", "偏好英文", dimension="user_profile")

        check("添加 4 条", storage.count() == 4)
        results = storage.search("客户", user_id="u1")
        check("FTS5 搜索", len(results) > 0 and any("客户" in r["content"] for r in results))
        check("按用户查询", len(storage.get_by_user("u1")) == 3)

        storage.write_file("u1", "# 画像\n张三 VIP")
        check("文件读写", "张三" in storage.read_file("u1"))
        storage.delete_by_user("u2")
        check("删除", storage.count("u2") == 0)
        storage.close()
    finally:
        shutil.rmtree(tmp)


async def demo_fts_engine():
    section("FTSMemoryEngine 维度化检索")
    tmp = tempfile.mkdtemp()
    try:
        from src.memory.fts_engine import FTSMemoryEngine
        from src.memory.storage import MemoryStorage
        from src.middleware.memory import MemoryEngine
        from langchain_core.messages import HumanMessage, AIMessage

        storage = MemoryStorage(storage_dir=tmp)
        engine = FTSMemoryEngine(storage=storage)
        check("实现 MemoryEngine", isinstance(engine, MemoryEngine))

        storage.add("u1", "客户张三商机 50 万", dimension="customer_context")
        storage.add("u1", "用户喜欢简洁回复", dimension="user_profile")

        result = await engine.retrieve("客户", user_id="u1")
        check("检索到结果", len(result.items) > 0)

        conv = [HumanMessage(content="我喜欢用表格展示"), AIMessage(content="好的")]
        extract = await engine.extract_and_update(conv, "t1", "u1")
        check("提取到记忆", len(extract.items) > 0)
        check("持久化", storage.count("u1") > 2)
        storage.close()
    finally:
        shutil.rmtree(tmp)


async def demo_debounce_queue():
    section("DebounceQueue 防抖合并")
    from src.memory.queue import DebounceQueue
    handled = []
    async def handler(tid, msgs): handled.append({"tid": tid, "n": len(msgs)})

    q = DebounceQueue(debounce_seconds=0.1, handler=handler)
    q.submit("t1", ["a"]); q.submit("t1", ["b", "c"])
    check("pending 合并", q.pending_count("t1") == 3)
    await q.flush("t1")
    check("flush 处理", len(handled) == 1 and handled[0]["n"] == 3)


async def demo_memory_updater():
    section("MemoryUpdater (真实 LLM)")
    from src.memory.updater import MemoryUpdater
    from langchain_core.messages import HumanMessage, AIMessage
    from langchain_openai import ChatOpenAI

    llm = ChatOpenAI(model="doubao-1-5-pro-32k-250115",
                     api_key="651621e7-e495-4728-93ef-ed380e9ddcd1",
                     base_url="https://ark.cn-beijing.volces.com/api/v3/", max_tokens=1024)
    updater = MemoryUpdater(llm=llm)

    # 无消息时返回现有记忆
    result = await updater.extract_and_update([], "existing")
    check("空消息返回现有", result == "existing")

    # 有消息时 LLM 提取
    msgs = [HumanMessage(content="我喜欢用表格展示数据"), AIMessage(content="好的，我会用表格")]
    result2 = await updater.extract_and_update(msgs, "用户偏好中文")
    check("LLM 提取记忆", len(result2) > 0)


def demo_memory_prompt():
    section("MemoryChunk + build_memory_prompt")
    from src.memory.prompt import MemoryChunk, build_memory_prompt
    check("空输入", build_memory_prompt() == "")
    p1 = build_memory_prompt(short_term="偏好中文")
    check("短期记忆", "short_term_memory" in p1)
    chunks = [MemoryChunk(id="1", content="张三 VIP"), MemoryChunk(id="2", content="5 个商机")]
    p2 = build_memory_prompt(long_term_results=chunks)
    check("长期记忆", "long_term_memory" in p2 and "张三" in p2)


# ═══════════════════════════════════════════════════════════
# G. 多模型路由 / 自动技能生成 / AgentConfig
# ═══════════════════════════════════════════════════════════

def demo_model_router():
    section("多模型路由")
    from src.core.model_router import ModelRouter, ModelRouterConfig, ModelConfig, TaskType

    config = ModelRouterConfig(
        default=ModelConfig(model="doubao-1-5-pro-32k-250115", api_key=os.environ["DOUBAO_API_KEY"]),
        routes={TaskType.SIMPLE.value: ModelConfig(model="doubao-1-5-pro-32k-250115", api_key=os.environ["DOUBAO_API_KEY"])},
    )
    router = ModelRouter(config)
    check("总结→SIMPLE", router.classify_task("帮我总结") == TaskType.SIMPLE)
    check("分析→COMPLEX", router.classify_task("分析数据") == TaskType.COMPLEX)
    check("代码→CODE", router.classify_task("写代码") == TaskType.CODE)
    check("未知→DEFAULT", router.classify_task("你好") == TaskType.DEFAULT)
    model = router.get_model(TaskType.SIMPLE)
    check("获取模型", model is not None)
    check("模型缓存", router.get_model(TaskType.SIMPLE) is model)


def demo_skill_generator():
    section("自动技能生成")
    tmp = tempfile.mkdtemp()
    try:
        from src.skills.generator import SkillGenerator
        from src.skills.base import SkillRegistry
        from langchain_core.messages import HumanMessage, AIMessage, ToolMessage

        reg = SkillRegistry()
        gen = SkillGenerator(skills_dir=tmp, min_tool_calls=3, skill_registry=reg)

        simple = [HumanMessage(content="你好"), AIMessage(content="你好！")]
        check("简单对话不生成", not gen.should_generate(simple))

        complex_msgs = [
            HumanMessage(content="查询客户并分析"),
            AIMessage(content="", tool_calls=[{"id": "tc1", "name": "query_data", "args": {"entity": "account"}}]),
            ToolMessage(content="5 个客户", tool_call_id="tc1", name="query_data"),
            AIMessage(content="", tool_calls=[{"id": "tc2", "name": "analyze_data", "args": {}}]),
            ToolMessage(content="分析结果", tool_call_id="tc2", name="analyze_data"),
            AIMessage(content="", tool_calls=[{"id": "tc3", "name": "query_schema", "args": {}}]),
            ToolMessage(content="schema", tool_call_id="tc3", name="query_schema"),
            AIMessage(content="完成"),
        ]
        check("复杂对话触发", gen.should_generate(complex_msgs))
        path = gen.generate(complex_msgs)
        check("生成文件", path is not None and os.path.isfile(path))
        content = open(path, encoding="utf-8").read()
        check("包含 frontmatter", content.startswith("---"))
        check("包含 allowed-tools", "query_data" in content)
        check("自动注册到 Registry", len(reg.list_all()) == 1)
    finally:
        shutil.rmtree(tmp)


def demo_agent_config():
    section("AgentConfig + AgentLoader + AgentRegistry")
    from src.agents.agent_config import AgentConfig, AgentLoader, AgentRegistry, Features

    f = Features.from_config({"memory_enabled": False, "unknown": True})
    check("Features.from_config", f.memory_enabled is False)

    registry = AgentRegistry()
    registry.register(AgentConfig(name="default", description="默认"))
    registry.register(AgentConfig(name="analyst", description="分析"))
    check("注册 2 个", len(registry) == 2)
    check("get", registry.get("default") is not None)

    defs_dir = os.path.join(os.path.dirname(__file__), "src", "agents", "definitions")
    if os.path.isdir(defs_dir):
        loader = AgentLoader(definitions_dir=defs_dir)
        configs = loader.discover()
        check(f"YAML 发现 {len(configs)} 个", len(configs) >= 1)
        if configs:
            check("default Agent", configs[0].name == "default")


# ═══════════════════════════════════════════════════════════
# H. ThreadState / OutputRender / SubagentConfig
# ═══════════════════════════════════════════════════════════

def demo_thread_state():
    section("ThreadState (LangGraph MessagesState)")
    from src.core.thread_state import (Artifact, ImageData, artifacts_reducer,
                                   thread_state_to_json, thread_state_from_json)
    from langchain_core.messages import HumanMessage

    a1 = Artifact(id="a1", type="code", title="test.py", content="print('hello')")
    check("Artifact 序列化", a1.to_dict()["id"] == "a1")
    check("Artifact 反序列化", Artifact.from_dict(a1.to_dict()).content == "print('hello')")

    img = ImageData(id="img1", url="https://example.com/img.png", alt_text="test", data=b"raw")
    check("ImageData 序列化", img.to_dict()["data"] is not None)
    check("ImageData 反序列化", ImageData.from_dict(img.to_dict()).data == b"raw")

    merged = artifacts_reducer(
        [Artifact(id="a1", type="code", title="v1", content="old")],
        [Artifact(id="a1", type="code", title="v2", content="new"),
         Artifact(id="a2", type="doc", title="readme", content="# README")],
    )
    check("reducer 更新+追加", len(merged) == 2 and merged[0].content == "new")

    state = {"messages": [HumanMessage(content="hello")], "artifacts": [a1],
             "images": [img], "title": "测试", "thread_data": {"k": "v"}}
    restored = thread_state_from_json(thread_state_to_json(state))
    check("JSON 往返", restored["title"] == "测试" and len(restored["artifacts"]) == 1)


def demo_output_render():
    section("OutputRenderMiddleware + TableRenderer")
    from src.middleware.output_render import TableRenderer

    renderer = TableRenderer()
    check("非表格不渲染", not renderer.can_render("普通文本", {}))

    table = "| 客户 | 金额 |\n| --- | --- |\n| 张三 | 50万 |\n| 李四 | 30万 |"
    check("表格可渲染", renderer.can_render(table, {}))
    result = renderer.render(table, {})
    check("component type=table", result.components[0]["type"] == "table")
    check("headers", result.components[0]["headers"] == ["客户", "金额"])
    check("rows 数据", result.components[0]["rows"][0]["客户"] == "张三")


def demo_subagent_config():
    section("SubagentConfig 补齐字段")
    from src.agents.subagent_config import SubagentConfig
    c = SubagentConfig(name="analyst", inherit_middleware=False, middleware_names=["logging"])
    check("inherit_middleware=False", c.inherit_middleware is False)
    check("默认 inherit=True", SubagentConfig(name="d").inherit_middleware is True)


# ═══════════════════════════════════════════════════════════
# I. 真实豆包 API 端到端
# ═══════════════════════════════════════════════════════════

async def demo_real_api():
    section("真实豆包 API 端到端调用")
    from src.tools.base import ToolRegistry
    from src.tools.crm_backend import CrmSimulatedBackend
    from src.tools.crm_tools import register_crm_tools
    from src.agents.langchain_agent import create_deep_agent, LangChainAgentConfig
    from langchain_core.messages import ToolMessage

    backend = CrmSimulatedBackend()
    reg = ToolRegistry()
    register_crm_tools(reg, backend)

    from src.core.prompt_builder import build_system_prompt as _bp

    config = LangChainAgentConfig(
        model="doubao-1-5-pro-32k-250115", api_key=os.environ["DOUBAO_API_KEY"],
        api_base="https://ark.cn-beijing.volces.com/api/v3/", tool_registry=reg,
        system_prompt=_bp(agent_name="CRM-Agent"),
    )
    agent = create_deep_agent(config)

    print("  ⏳ 调用豆包 API...")
    result = await agent.ainvoke({"messages": [{"role": "user", "content": "系统中有多少个客户？"}]})
    messages = result.get("messages", [])
    check("有返回消息", len(messages) > 0)

    tool_calls = [m for m in messages if hasattr(m, "tool_calls") and m.tool_calls]
    tool_results = [m for m in messages if isinstance(m, ToolMessage)]
    check("调用了工具", len(tool_calls) > 0 or len(tool_results) > 0)

    last = messages[-1]
    content = last.content if hasattr(last, "content") else str(last)
    print(f"  💬 回答: {content[:150]}")
    check("有最终回答", len(content) > 0)


# ═══════════════════════════════════════════════════════════
# 主入口
# ═══════════════════════════════════════════════════════════

async def main():
    print("=" * 70)
    print("  DeepAgent 全功能 Demo — 覆盖所有测试场景")
    print("=" * 70)

    # A. LangChain Agent
    await demo_tool_adapter()
    demo_create_agent()

    # B. 技能系统
    demo_skill_definition()
    await demo_skill_executor()
    demo_skill_loader()

    # C. Pydantic 工具 + AgentFactory
    demo_exceptions()
    await demo_pydantic_skills_tool()
    demo_agent_tool()
    demo_agent_factory()
    demo_prompt_builder()

    # D. 中间件栈
    demo_middleware_imports()
    await demo_guardrail()
    await demo_clarification()
    await demo_memory_middleware()
    await demo_plugin_lifecycle()

    # E. 三层压缩 + 熔断
    demo_micro_compact()
    demo_auto_compact()
    demo_full_compact()
    demo_circuit_breaker()
    demo_tool_loader()

    # F. 记忆系统
    demo_memory_storage()
    await demo_fts_engine()
    await demo_debounce_queue()
    await demo_memory_updater()
    demo_memory_prompt()

    # G. 路由 / 技能生成 / AgentConfig
    demo_model_router()
    demo_skill_generator()
    demo_agent_config()

    # H. ThreadState / OutputRender
    demo_thread_state()
    demo_output_render()
    demo_subagent_config()

    # I. 真实 API
    await demo_real_api()

    # 总结
    print(f"\n{'='*70}")
    print(f"  全功能 Demo: {passed} passed, {failed} failed ({total_sections} 个模块)")
    print(f"{'='*70}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
