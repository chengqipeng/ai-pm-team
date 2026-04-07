"""
完整测试套件 — 真实文件系统 + 真实命令执行 + 真实 HTTP
Agent Loop 使用 MockLLMClient (控制 LLM 响应来验证循环逻辑)
其余全部真实执行。
"""
import asyncio, json, os, sys, tempfile, shutil, time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.types import *
from src.state import AppState, AppStateStore
from src.tools import *
from src.builtin_tools import *
from src.skills import *
from src.context import *
from src.hooks import *
from src.session import SessionStorage, _message_to_dict, _dict_to_message
from src.coordinator import *
from src.plugins import *
from src.agent import *
from src.engine import QueryEngine, QueryEngineConfig
from src.llm_client import MockLLMClient

def run(coro):
    loop = asyncio.new_event_loop()
    try: return loop.run_until_complete(coro)
    finally: loop.close()

def ctx():
    s = AppStateStore()
    return ToolUseContext(get_app_state=s.get_state, set_app_state=s.set_state)

passed = failed = 0
errors = []
def test(name):
    def dec(fn):
        global passed, failed
        try: fn(); passed += 1; print(f"  ✅ {name}")
        except Exception as e: failed += 1; errors.append((name,e)); print(f"  ❌ {name}: {e}")
    return dec

# ═══════════════════════════════════════
print("\n📦 1. Types")
# ═══════════════════════════════════════

@test("create_agent_id unique")
def _():
    ids = {create_agent_id() for _ in range(100)}
    assert len(ids) == 100

@test("Message fields")
def _():
    m = Message(role=MessageRole.USER, content="hi")
    assert m.uuid and m.timestamp > 0 and m.tool_use_blocks == []

@test("TaskStatus terminal states")
def _():
    assert TaskStatus.COMPLETED.value == "completed"

# ═══════════════════════════════════════
print("\n📦 2. State")
# ═══════════════════════════════════════

@test("AppStateStore immutable update + subscribe")
def _():
    s = AppStateStore()
    calls = []
    unsub = s.subscribe(lambda: calls.append(1))
    old = s.get_state()
    s.set_state(lambda st: AppState(is_loading=True, tool_permission_context=st.tool_permission_context))
    assert s.get_state().is_loading and not old.is_loading and len(calls) == 1
    unsub()
    s.set_state(lambda st: AppState(is_loading=False, tool_permission_context=st.tool_permission_context))
    assert len(calls) == 1

# ═══════════════════════════════════════
print("\n📦 3. Builtin Tools — 真实执行")
# ═══════════════════════════════════════

@test("FileReadTool 真实读取 + 行范围 + 缓存")
def _():
    fd, p = tempfile.mkstemp(suffix=".txt"); os.write(fd, b"a\nb\nc\nd\n"); os.close(fd)
    try:
        c = ctx()
        r = run(FileReadTool().call({"path": p}, c))
        assert not r.is_error and "a\nb\nc\nd" in r.content and p in c.read_file_state
        r2 = run(FileReadTool().call({"path": p, "start_line": 2, "end_line": 3}, ctx()))
        assert r2.content == "b\nc\n"
    finally: os.unlink(p)

@test("FileReadTool 不存在 → is_error")
def _():
    assert run(FileReadTool().call({"path": "/no/such/file"}, ctx())).is_error

@test("FileWriteTool 创建目录 + 写入")
def _():
    d = tempfile.mkdtemp(); p = os.path.join(d, "sub", "f.txt")
    try:
        r = run(FileWriteTool().call({"path": p, "content": "hello"}, ctx()))
        assert not r.is_error and open(p).read() == "hello"
    finally: shutil.rmtree(d)

@test("FileEditTool 替换 + 校验 + 多匹配报错")
def _():
    fd, p = tempfile.mkstemp(); os.write(fd, b"aaa bbb aaa"); os.close(fd)
    try:
        assert FileEditTool().validate_input({"old_string": "x", "new_string": "x"}).valid is False
        r = run(FileEditTool().call({"path": p, "old_string": "aaa", "new_string": "z"}, ctx()))
        assert r.is_error and "2 locations" in r.content
    finally: os.unlink(p)

@test("BashTool 真实执行 + 失败 + 超时 + stderr")
def _():
    r1 = run(BashTool().call({"command": "echo real_exec"}, ctx()))
    assert "real_exec" in r1.content and not r1.is_error
    r2 = run(BashTool().call({"command": "false"}, ctx()))
    assert r2.is_error
    r3 = run(BashTool().call({"command": "sleep 10", "timeout": 1}, ctx()))
    assert r3.is_error and "timed out" in r3.content.lower()
    r4 = run(BashTool().call({"command": "echo err >&2"}, ctx()))
    assert "err" in r4.content

@test("GrepTool 真实搜索项目文件")
def _():
    r = run(GrepTool().call({"pattern": "class FileReadTool", "path": "product-specs/agent-system/src/", "include": "*.py"}, ctx()))
    assert "FileReadTool" in r.content

@test("GlobTool 真实查找")
def _():
    r = run(GlobTool().call({"pattern": "product-specs/agent-system/src/*.py"}, ctx()))
    assert "tools.py" in r.content and "agent.py" in r.content

@test("WebFetchTool 真实 HTTP 请求")
def _():
    r = run(WebFetchTool().call({"url": "https://httpbin.org/get", "max_chars": 5000}, ctx()))
    assert not r.is_error and "httpbin" in r.content.lower()

@test("WebFetchTool 校验 URL 格式")
def _():
    v = WebFetchTool().validate_input({"url": "not-a-url"})
    assert not v.valid

@test("WebSearchTool 真实搜索")
def _():
    r = run(WebSearchTool().call({"query": "python programming language", "max_results": 3}, ctx()))
    assert not r.is_error
    # DuckDuckGo 可能返回结果也可能被限流，两种都接受
    assert "python" in r.content.lower() or "Search" in r.content

@test("TodoWriteTool 完整 CRUD")
def _():
    todo_file = ".agent-todo.md"
    try:
        # add
        r = run(TodoWriteTool().call({"action": "add", "content": "task one"}, ctx()))
        assert not r.is_error and "task one" in r.content
        r = run(TodoWriteTool().call({"action": "add", "content": "task two"}, ctx()))
        # read
        r = run(TodoWriteTool().call({"action": "read"}, ctx()))
        assert "task one" in r.content and "task two" in r.content
        # complete
        r = run(TodoWriteTool().call({"action": "complete", "index": 1}, ctx()))
        assert not r.is_error
        # remove
        r = run(TodoWriteTool().call({"action": "remove", "index": 2}, ctx()))
        assert not r.is_error
        # clear
        r = run(TodoWriteTool().call({"action": "clear"}, ctx()))
        assert not r.is_error
    finally:
        if os.path.exists(todo_file): os.unlink(todo_file)

@test("NotebookEditTool 真实 .ipynb 操作")
def _():
    fd, p = tempfile.mkstemp(suffix=".ipynb")
    nb = {"nbformat": 4, "nbformat_minor": 5, "metadata": {}, "cells": []}
    os.write(fd, json.dumps(nb).encode()); os.close(fd)
    try:
        t = NotebookEditTool()
        r = run(t.call({"path": p, "action": "add_cell", "cell_type": "code", "content": "print('hi')"}, ctx()))
        assert not r.is_error
        r = run(t.call({"path": p, "action": "read"}, ctx()))
        assert "print" in r.content
        r = run(t.call({"path": p, "action": "edit_cell", "cell_index": 0, "content": "x = 1"}, ctx()))
        assert not r.is_error
        r = run(t.call({"path": p, "action": "delete_cell", "cell_index": 0}, ctx()))
        assert not r.is_error
    finally: os.unlink(p)

@test("register_builtin_tools 注册 13 个工具")
def _():
    reg = ToolRegistry(); register_builtin_tools(reg)
    names = {t.name for t in reg.all_tools}
    expected = {"file_read","file_write","file_edit","bash","grep","glob","ask_user",
                "web_fetch","web_search","todo_write","send_message","task_stop","notebook_edit"}
    assert expected == names, f"Missing: {expected - names}, Extra: {names - expected}"

# ═══════════════════════════════════════
print("\n📦 4. Tools — 权限 + 执行链路")
# ═══════════════════════════════════════

@test("ToolRegistry 权限过滤")
def _():
    reg = ToolRegistry(); register_builtin_tools(reg)
    pool = reg.assemble_tool_pool(ToolPermissionContext(always_deny_rules=["bash","file_write"]))
    names = {t.name for t in pool}
    assert "bash" not in names and "file_write" not in names and "file_read" in names

@test("can_use_tool allow/deny/acceptEdits/bypass")
def _():
    assert run(can_use_tool(FileReadTool(), {}, ctx(), ToolPermissionContext(always_allow_rules=["file_read"]))).behavior == PermissionBehavior.ALLOW
    assert run(can_use_tool(BashTool(), {}, ctx(), ToolPermissionContext(always_deny_rules=["bash"]))).behavior == PermissionBehavior.DENY
    assert run(can_use_tool(FileReadTool(), {}, ctx(), ToolPermissionContext(mode="acceptEdits"))).behavior == PermissionBehavior.ALLOW
    assert run(can_use_tool(FileWriteTool(), {}, ctx(), ToolPermissionContext(mode="bypassPermissions"))).behavior == PermissionBehavior.ALLOW

@test("execute_tool_use 完整链路")
def _():
    reg = ToolRegistry(); register_builtin_tools(reg)
    r = run(execute_tool_use(ToolUseBlock(id="t1", name="bash", input={"command": "echo chain"}), ctx(), ToolPermissionContext(mode="acceptEdits"), reg))
    assert not r.is_error and "chain" in r.content and r.tool_use_id == "t1"

@test("execute_tool_use 未知工具 + 校验失败")
def _():
    r1 = run(execute_tool_use(ToolUseBlock(id="t", name="xxx", input={}), ctx(), ToolPermissionContext(), ToolRegistry()))
    assert r1.is_error and "Unknown" in r1.content
    reg = ToolRegistry(); reg.register(FileEditTool())
    r2 = run(execute_tool_use(ToolUseBlock(id="t", name="file_edit", input={"path":"x","old_string":"a","new_string":"a"}), ctx(), ToolPermissionContext(mode="acceptEdits"), reg))
    assert r2.is_error and "Validation" in r2.content

@test("execute_tools_parallel 真实并行")
def _():
    reg = ToolRegistry(); register_builtin_tools(reg)
    results = run(execute_tools_parallel(
        [ToolUseBlock(id="t1",name="bash",input={"command":"echo A"}), ToolUseBlock(id="t2",name="bash",input={"command":"echo B"})],
        ctx(), ToolPermissionContext(mode="acceptEdits"), reg))
    assert len(results) == 2 and any("A" in r.content for r in results) and any("B" in r.content for r in results)

# ═══════════════════════════════════════
print("\n📦 5. Skills — 完整 prompt 生成")
# ═══════════════════════════════════════

@test("register_builtin_skills 注册 8 个技能")
def _():
    reg = SkillRegistry(); register_builtin_skills(reg)
    names = {s.name for s in reg.all_skills}
    expected = {"verify","debug","stuck","remember","batch","loop","simplify","skillify"}
    assert expected == names, f"Missing: {expected - names}"

@test("verify skill prompt 包含验证步骤")
def _():
    reg = SkillRegistry(); register_builtin_skills(reg)
    p = run(reg.find("verify").get_prompt("auth module"))
    assert "git diff" in p and "Run existing tests" in p and "auth module" in p

@test("debug skill prompt 包含5阶段")
def _():
    reg = SkillRegistry(); register_builtin_skills(reg)
    p = run(reg.find("debug").get_prompt("NullPointer"))
    assert "Reproduce" in p and "Locate" in p and "NullPointer" in p

@test("stuck skill prompt 包含恢复策略")
def _():
    reg = SkillRegistry(); register_builtin_skills(reg)
    p = run(reg.find("stuck").get_prompt())
    assert "Recovery Strategies" in p and "Ask the user" in p

@test("remember skill prompt 包含 CLAUDE.md 指令")
def _():
    reg = SkillRegistry(); register_builtin_skills(reg)
    p = run(reg.find("remember").get_prompt("always use type hints"))
    assert "CLAUDE.md" in p and "type hints" in p

@test("batch skill prompt 包含批量协议")
def _():
    reg = SkillRegistry(); register_builtin_skills(reg)
    p = run(reg.find("batch").get_prompt("add docstrings"))
    assert "Discover files" in p and "add docstrings" in p

@test("loop skill prompt 包含迭代限制")
def _():
    reg = SkillRegistry(); register_builtin_skills(reg)
    p = run(reg.find("loop").get_prompt("fix build"))
    assert "Maximum 10 iterations" in p and "fix build" in p

@test("simplify skill prompt 包含简化清单")
def _():
    reg = SkillRegistry(); register_builtin_skills(reg)
    p = run(reg.find("simplify").get_prompt("src/auth.py"))
    assert "Simplification Checklist" in p and "src/auth.py" in p

@test("skillify skill prompt 包含输出格式")
def _():
    reg = SkillRegistry(); register_builtin_skills(reg)
    p = run(reg.find("skillify").get_prompt("deploy to staging"))
    assert ".claude/skills/" in p and "deploy to staging" in p

@test("Skill 别名查找")
def _():
    reg = SkillRegistry(); register_builtin_skills(reg)
    assert reg.find("v") is not None and reg.find("v").name == "verify"
    assert reg.find("d") is not None and reg.find("d").name == "debug"
    assert reg.find("sk") is not None and reg.find("sk").name == "skillify"

@test("SkillRegistry load_from_directory 真实文件")
def _():
    d = tempfile.mkdtemp()
    try:
        with open(os.path.join(d, "my-skill.md"), "w") as f:
            f.write("---\nname: my-skill\ndescription: test\n---\nDo: ${1}")
        reg = SkillRegistry(); count = reg.load_from_directory(d)
        assert count == 1
        p = run(reg.find("my-skill").get_prompt("hello"))
        assert "hello" in p
    finally: shutil.rmtree(d)

# ═══════════════════════════════════════
print("\n📦 6. Context — 压缩 + 附件 + 记忆")
# ═══════════════════════════════════════

@test("ContextCompressor tool_result_budget 截断大结果")
def _():
    c = ContextCompressor()
    a = Message(role=MessageRole.ASSISTANT, tool_use_blocks=[ToolUseBlock(id="t1", name="bash", input={})])
    u = Message(role=MessageRole.USER, tool_result_blocks=[ToolResultBlock(tool_use_id="t1", content="x"*100_000)])
    result = c.apply_tool_result_budget([a, u])
    assert len(result[1].tool_result_blocks[0].content) < 100_000

@test("ContextCompressor snip + microcompact")
def _():
    c = ContextCompressor()
    msgs = [Message(role=MessageRole.USER, content=f"message content number {i} " * 10) for i in range(30)]
    snipped, freed = c.snip_history(msgs, keep_recent=10)
    assert len(snipped) == 10 and freed > 0
    # microcompact 需要 tool_result 消息
    tool_msgs = []
    for i in range(10):
        tool_msgs.append(Message(role=MessageRole.ASSISTANT, tool_use_blocks=[ToolUseBlock(id=f"t{i}", name="grep", input={})]))
        tool_msgs.append(Message(role=MessageRole.USER, tool_result_blocks=[ToolResultBlock(tool_use_id=f"t{i}", content=f"r{i}")]))
    mc = c.microcompact(tool_msgs)
    assert "cleared" in mc[1].tool_result_blocks[0].content.lower()
    assert "r9" in mc[-1].tool_result_blocks[0].content

@test("ContextCompressor local_summarize 降级")
def _():
    c = ContextCompressor()  # 无 llm_call
    msgs = [Message(role=MessageRole.USER, content="x"*200_000) for _ in range(5)]
    result = run(c.autocompact(msgs, "sys"))
    assert result is not None and "summary" in result.summary.lower()

@test("AttachmentManager token 警告 + reset")
def _():
    mgr = AttachmentManager()
    msgs = [Message(role=MessageRole.USER, content="x"*200_000) for _ in range(5)]
    atts = run(mgr.get_attachments(None, msgs, [], []))
    assert any(a.tag == "token_warning" for a in atts)
    mgr.reset_after_compact()
    assert len(mgr._sent_skill_names) == 0

@test("load_memory_files 真实 CLAUDE.md")
def _():
    d = tempfile.mkdtemp()
    try:
        with open(os.path.join(d, "CLAUDE.md"), "w") as f: f.write("# Rules\nUse type hints.")
        r = load_memory_files(d)
        assert r and "type hints" in r
    finally: shutil.rmtree(d)

# ═══════════════════════════════════════
print("\n📦 7. Hooks")
# ═══════════════════════════════════════

@test("HookMatcher 精确/通配/分类/正则")
def _():
    assert HookMatcher(tool_name="bash").matches("bash")
    assert not HookMatcher(tool_name="bash").matches("grep")
    assert HookMatcher(tool_name="*").matches("anything")
    assert HookMatcher(tool_category="write").matches("file_write")
    assert not HookMatcher(tool_category="write").matches("file_read")
    assert HookMatcher(tool_pattern=r"file_.*").matches("file_read")

@test("HookRegistry + HookExecutor 真实执行")
def _():
    reg = HookRegistry()
    reg.register(HookDefinition(name="audit", event=HookEvent.POST_TOOL_USE, matcher=HookMatcher(tool_name="bash"),
        action=HookAction(type=HookActionType.ASK_AGENT, prompt="Audited {{tool_name}}")))
    ex = HookExecutor(reg)
    results = run(ex.execute_post_tool_use("bash", {"command": "ls"}, "output", False))
    assert len(results) == 1 and results[0].success and "bash" in results[0].output

@test("HookExecutor run_command 真实执行")
def _():
    reg = HookRegistry()
    reg.register(HookDefinition(name="cmd", event=HookEvent.POST_TOOL_USE, matcher=HookMatcher(tool_name="*"),
        action=HookAction(type=HookActionType.RUN_COMMAND, command="echo hook_ran")))
    ex = HookExecutor(reg)
    results = run(ex.execute_post_tool_use("bash", {}, "", False))
    assert results[0].success and "hook_ran" in results[0].output

@test("HookExecutor denial 检测")
def _():
    ex = HookExecutor(HookRegistry())
    assert ex._check_denial("Access denied") and not ex._check_denial("All good")

# ═══════════════════════════════════════
print("\n📦 8. Session — 真实文件 I/O")
# ═══════════════════════════════════════

@test("SessionStorage transcript 读写往返")
def _():
    d = tempfile.mkdtemp()
    try:
        s = SessionStorage(project_root=d)
        msgs = [Message(role=MessageRole.USER, content="hello"), Message(role=MessageRole.ASSISTANT, content="hi",
            tool_use_blocks=[ToolUseBlock(id="t1", name="bash", input={"cmd": "ls"})], usage={"input_tokens": 100})]
        run(s.record_transcript(msgs))
        loaded = run(s.load_transcript())
        assert len(loaded) == 2 and loaded[0].content == "hello"
        assert loaded[1].tool_use_blocks[0].name == "bash"
    finally: shutil.rmtree(d)

@test("SessionStorage tool_result 持久化 + 加载")
def _():
    d = tempfile.mkdtemp()
    try:
        s = SessionStorage(project_root=d)
        path = run(s.persist_tool_result("big", "x"*100_000))
        assert path and os.path.exists(path)
        loaded = run(s.load_tool_result("big"))
        assert loaded and len(loaded) == 100_000
    finally: shutil.rmtree(d)

@test("SessionStorage 文件快照 + 恢复")
def _():
    d = tempfile.mkdtemp(); f = os.path.join(d, "test.txt")
    with open(f, "w") as fh: fh.write("original")
    try:
        s = SessionStorage(project_root=d)
        run(s.make_file_snapshot("m1", [f]))
        with open(f, "w") as fh: fh.write("modified")
        restored = run(s.restore_file_snapshot("m1"))
        assert "original" in list(restored.values())[0]
    finally: shutil.rmtree(d)

@test("SessionStorage list_sessions")
def _():
    d = tempfile.mkdtemp()
    try:
        for sid in ["s1", "s2"]:
            s = SessionStorage(project_root=d, session_id=sid)
            run(s.save_metadata({"test": True}))
        assert len(SessionStorage.list_sessions(d)) == 2
    finally: shutil.rmtree(d)

# ═══════════════════════════════════════
print("\n📦 9. Coordinator")
# ═══════════════════════════════════════

@test("Worker 生命周期 + TaskNotification XML 往返")
def _():
    c = CoordinatorContext(worker_tools=["bash"])
    c.register_worker("a1", "Research")
    assert len(c.get_active_workers()) == 1
    n = c.complete_worker("a1", "Found bug", {"total_tokens": 500})
    assert n.status == TaskStatus.COMPLETED
    xml = n.to_xml()
    assert "<task-id>a1</task-id>" in xml
    restored = TaskNotification.from_xml(xml)
    assert restored.task_id == "a1" and restored.usage["total_tokens"] == 500
    assert len(c.get_active_workers()) == 0

@test("filter_coordinator/worker_tools")
def _():
    class T:
        def __init__(self, n): self.name = n
    tools = [T("agent"), T("bash"), T("send_message"), T("team_create")]
    assert {t.name for t in filter_coordinator_tools(tools)} == {"agent", "send_message"}
    assert "team_create" not in {t.name for t in filter_worker_tools(tools)}

# ═══════════════════════════════════════
print("\n📦 10. Plugins")
# ═══════════════════════════════════════

@test("PluginRegistry 注册 + 启用/禁用 + load_skills_into")
def _():
    pr = PluginRegistry()
    pr.register(LoadedPlugin(name="p1", manifest=PluginManifest(name="p1", version="1.0",
        skills=[{"name": "ps1", "description": "plugin skill", "prompt": "do ${1}"}])))
    assert len(pr.get_enabled_plugins()) == 1
    pr.disable("p1@user"); assert len(pr.get_enabled_plugins()) == 0
    pr.enable("p1@user"); assert len(pr.get_enabled_plugins()) == 1
    sr = SkillRegistry(); pr.load_skills_into(sr)
    assert sr.find("ps1") is not None

@test("PluginRegistry load_from_directory 真实文件")
def _():
    d = tempfile.mkdtemp(); pd = os.path.join(d, "myplugin"); os.makedirs(pd)
    with open(os.path.join(pd, "manifest.json"), "w") as f: json.dump({"name": "myplugin", "version": "0.1"}, f)
    try:
        plugins = PluginRegistry.load_from_directory(d)
        assert len(plugins) == 1 and plugins[0].name == "myplugin"
    finally: shutil.rmtree(d)

# ═══════════════════════════════════════
print("\n📦 11. Agent — Loop + 反思 + 子Agent")
# ═══════════════════════════════════════

@test("categorize_retryable_error")
def _():
    assert categorize_retryable_error(Exception("429")) == RetryCategory.RATE_LIMIT
    assert categorize_retryable_error(Exception("500")) == RetryCategory.SERVER_ERROR
    assert categorize_retryable_error(Exception("auth")) == RetryCategory.NON_RETRYABLE

@test("detect_stuck_pattern 连续相同工具 (4次触发)")
def _():
    s = ReflectionState()
    for _ in range(3): assert detect_stuck_pattern(s, "bash", False) is None
    assert detect_stuck_pattern(s, "bash", False) is not None

@test("detect_stuck_pattern 连续错误 (3次触发)")
def _():
    s = ReflectionState()
    assert detect_stuck_pattern(s, "a", True) is None
    assert detect_stuck_pattern(s, "b", True) is None
    assert detect_stuck_pattern(s, "c", True) is not None

@test("get_builtin_agents 3个 + Explore 禁止写入")
def _():
    agents = get_builtin_agents()
    assert len(agents) == 3 and {a.agent_type for a in agents} == {"Explore", "Plan", "Verification"}
    explore = [a for a in agents if a.agent_type == "Explore"][0]
    assert "file_edit" in explore.disallowed_tools and explore.omit_claude_md

@test("AgentLoopEngine 完整循环: tool_call → text 结束")
def _():
    client = MockLLMClient()
    client.add_tool_call_response("bash", {"command": "echo test"})
    client.add_text_response("Done.")
    reg = ToolRegistry(); register_builtin_tools(reg)
    engine = AgentLoopEngine(llm_client=client, tool_registry=reg, skill_registry=SkillRegistry(),
        store=AppStateStore(), config=AgentLoopConfig(system_prompt="test", max_turns=10))
    collected = []
    async def _r():
        async for m in engine.run([Message(role=MessageRole.USER, content="go")]): collected.append(m)
    run(_r())
    assert any(m.tool_use_blocks for m in collected)
    assert any("Done" in str(m.content) for m in collected)

@test("AgentLoopEngine max_turns 限制")
def _():
    client = MockLLMClient()
    for _ in range(20): client.add_tool_call_response("bash", {"command": "echo loop"})
    reg = ToolRegistry(); register_builtin_tools(reg)
    engine = AgentLoopEngine(llm_client=client, tool_registry=reg, skill_registry=SkillRegistry(),
        store=AppStateStore(), config=AgentLoopConfig(system_prompt="test", max_turns=3))
    collected = []
    async def _r():
        async for m in engine.run([Message(role=MessageRole.USER, content="go")]): collected.append(m)
    run(_r())
    assert any("Max turns" in str(m.content) for m in collected)

# ═══════════════════════════════════════
print("\n📦 12. Engine — 端到端集成")
# ═══════════════════════════════════════

@test("QueryEngine 初始化 → 提交 → 响应 → session 持久化")
def _():
    client = MockLLMClient(); client.add_text_response("Hello!")
    d = tempfile.mkdtemp()
    try:
        e = QueryEngine(QueryEngineConfig(llm_client=client, project_root=d, permission_mode="acceptEdits", enable_session=True))
        collected = []
        async def _r():
            async for m in e.submit_message("Hi"): collected.append(m)
        run(_r())
        assert any("Hello" in str(m.content) for m in collected)
        assert e.session_id and len(SessionStorage.list_sessions(d)) >= 1
        run(e.shutdown())
    finally: shutil.rmtree(d)

@test("QueryEngine 多轮工具调用")
def _():
    client = MockLLMClient()
    client.add_tool_call_response("bash", {"command": "echo A"})
    client.add_tool_call_response("file_read", {"path": __file__})
    client.add_text_response("Analysis done.")
    d = tempfile.mkdtemp()
    try:
        e = QueryEngine(QueryEngineConfig(llm_client=client, project_root=d, permission_mode="bypassPermissions", enable_session=False))
        collected = []
        async def _r():
            async for m in e.submit_message("Analyze"): collected.append(m)
        run(_r())
        tool_calls = [m for m in collected if m.tool_use_blocks]
        assert len(tool_calls) == 2
        run(e.shutdown())
    finally: shutil.rmtree(d)

@test("QueryEngine session resume")
def _():
    d = tempfile.mkdtemp()
    try:
        c1 = MockLLMClient(); c1.add_text_response("First")
        e1 = QueryEngine(QueryEngineConfig(llm_client=c1, project_root=d, enable_session=True))
        async def _r1():
            async for _ in e1.submit_message("Hello"): pass
        run(_r1())
        sid = e1.session_id; run(e1.shutdown())
        c2 = MockLLMClient(); c2.add_text_response("Resumed")
        e2 = QueryEngine(QueryEngineConfig(llm_client=c2, project_root=d, session_id=sid, enable_session=True))
        resumed = run(e2.resume_session(sid))
        assert len(resumed) >= 2
        run(e2.shutdown())
    finally: shutil.rmtree(d)

@test("QueryEngine 注册了全部 15 个工具 (13 builtin + skill + agent)")
def _():
    d = tempfile.mkdtemp()
    try:
        e = QueryEngine(QueryEngineConfig(llm_client=MockLLMClient(), project_root=d, enable_session=False))
        run(e.initialize())
        names = {t.name for t in e.tool_registry.all_tools}
        assert "skill" in names and "agent" in names and "bash" in names
        assert len(names) == 15, f"Got {len(names)}: {names}"
        run(e.shutdown())
    finally: shutil.rmtree(d)

# ═══════════════════════════════════════
print("\n" + "=" * 60)
print(f"  结果: {passed} passed, {failed} failed")
print("=" * 60)
if errors:
    print("\n❌ 失败详情:")
    for name, err in errors: print(f"  - {name}: {err}")

# 清理
if os.path.exists(".agent-sessions"): shutil.rmtree(".agent-sessions")
if os.path.exists(".agent-todo.md"): os.unlink(".agent-todo.md")
sys.exit(1 if failed else 0)
