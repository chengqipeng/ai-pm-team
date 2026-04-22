"""
P2 功能测试 — SKILL.md 加载 / wrap_tool_call / Guardrail / Plugin 生命周期
"""
import asyncio, sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.state import GraphState  # import graph first to break cycle
from src.skills import SkillDefinition, SkillRegistry, SkillLoader, SkillValidationError
from src.middleware.guardrail import GuardrailMiddleware
from src.middleware.base import PluginContext
from src.dtypes import ToolResultBlock
from src.plugin import PluginRegistry, PluginManifest, MemoryPlugin, NotificationPlugin

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
# 1. SKILL.md 文件加载
# ═══════════════════════════════════════════════════════════

def test_skill_loader():
    print("\n\U0001f4e6 1. SKILL.md 文件加载")

    # 解析 inline 技能
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
    check("parse context", skill.context == "inline")
    check("parse arguments", skill.arguments == ["code", "language"])
    check("parse prompt", "代码审查专家" in skill.prompt)
    check("parse allowed_tools", skill.allowed_tools == [])

    # 解析 fork 技能
    content2 = """---
description: 安全审计
context: fork
agent: security-auditor
allowed-tools:
  - query_data
  - query_schema
---

审计 {scope} 的安全配置。
"""
    skill2 = SkillLoader.parse(content2)
    check("fork context", skill2.context == "fork")
    check("fork agent", skill2.agent == "security-auditor")
    check("fork allowed_tools", len(skill2.allowed_tools) == 2)

    # 验证失败: 缺少 description
    try:
        bad = SkillLoader.parse("---\ncontext: inline\n---\nprompt")
        SkillLoader.validate(bad)
        check("validation: missing description", False)
    except SkillValidationError as e:
        check("validation: missing description → error", "description" in str(e.errors))

    # 验证失败: 无效 context
    try:
        bad2 = SkillLoader.parse("---\ndescription: test\ncontext: unknown\n---\nprompt")
        SkillLoader.validate(bad2)
        check("validation: bad context", False)
    except SkillValidationError:
        check("validation: bad context → error", True)

    # discover 从目录加载
    skills_dir = os.path.join(os.path.dirname(__file__), "..", "skills", "definitions")
    if os.path.isdir(skills_dir):
        skills = SkillLoader.discover(skills_dir)
        check(f"discover: found {len(skills)} skills", len(skills) >= 2)
        names = {s.name for s in skills}
        check("discover: code-review", "code-review" in names)
        check("discover: security-audit", "security-audit" in names)
    else:
        check("discover: skills dir exists", False)


# ═══════════════════════════════════════════════════════════
# 2. GuardrailMiddleware (wrap_tool_call)
# ═══════════════════════════════════════════════════════════

async def test_guardrail():
    print("\n\U0001f4e6 2. GuardrailMiddleware (wrap_tool_call)")

    # 允许所有
    gw_all = GuardrailMiddleware(allowed_tools=None)
    result = await gw_all.wrap_tool_call("any_tool", {}, GraphState(), None)
    check("allowed=None → 放行", result is None)

    # 白名单
    gw = GuardrailMiddleware(allowed_tools=["query_data", "analyze_data"])

    r1 = await gw.wrap_tool_call("query_data", {}, GraphState(), None)
    check("白名单内 → 放行", r1 is None)

    r2 = await gw.wrap_tool_call("modify_data", {}, GraphState(), None)
    check("白名单外 → 拦截", r2 is not None)
    check("拦截结果 is_error", isinstance(r2, ToolResultBlock) and r2.is_error)
    check("拦截消息包含工具名", "modify_data" in r2.content)


# ═══════════════════════════════════════════════════════════
# 3. Plugin 生命周期
# ═══════════════════════════════════════════════════════════

async def test_plugin_lifecycle():
    print("\n\U0001f4e6 3. Plugin 生命周期")

    registry = PluginRegistry()

    # 注册 MemoryPlugin
    mem = MemoryPlugin(backend="memory")
    mem.seed([{"category": "profile", "content": "测试用户"}])
    registry.register(mem, PluginManifest(name="memory", description="记忆系统"))

    # 注册 NotificationPlugin
    notif = NotificationPlugin(channels=["in_app", "email"])
    registry.register(notif, PluginManifest(name="notification", description="通知系统"))

    check("注册 2 个 Plugin", len(registry.all_plugins) == 2)

    # 初始化
    await registry.initialize_all()
    check("初始化完成", len(registry.initialized_plugins) == 2)

    # 健康检查
    health = await registry.health_check_all()
    check("健康检查全部通过", all(health.values()))

    # 使用 MemoryPlugin
    recalled = await mem.recall("测试", categories=["profile"])
    check("MemoryPlugin recall", len(recalled) == 1)

    await mem.commit({"category": "cases", "content": "新记忆"})
    check("MemoryPlugin commit", len(mem._store) == 2)

    # 使用 NotificationPlugin
    ok_sent = await notif.send("测试通知", channel="in_app")
    check("NotificationPlugin send", ok_sent)
    check("NotificationPlugin 记录", len(notif.sent_messages) == 1)

    # 关闭
    await registry.shutdown_all()
    check("关闭完成", len(registry.initialized_plugins) == 0)

    # 获取 Plugin
    check("get by name", registry.get("memory") is mem)
    check("get manifest", registry.get_manifest("memory").description == "记忆系统")


# ═══════════════════════════════════════════════════════════
# 运行
# ═══════════════════════════════════════════════════════════

if __name__ == "__main__":
    test_skill_loader()
    asyncio.run(test_guardrail())
    asyncio.run(test_plugin_lifecycle())

    print(f"\n{'='*60}")
    print(f"  P2 功能测试: {passed} passed, {failed} failed")
    print(f"{'='*60}")
    sys.exit(1 if failed else 0)
