"""
DeepAgent 集成测试 — 验证 GraphEngine + Router + 三 Node + 中间件
使用 MockLLMClient，不需要真实 API Key
"""
import asyncio
import sys
import os

# 确保 src 在 path 中
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.dtypes import Message, MessageRole, ToolResult
from src.llm_client import MockLLMClient
from src.tools import Tool, ToolRegistry
from src.graph.state import GraphState, AgentStatus, StepStatus, AgentLimits
from src.graph.router import Router
from src.graph.engine import GraphEngine
from src.graph.factory import AgentFactory, AgentConfig
from src.nodes.planning import PlanningNode
from src.nodes.execution import ExecutionNode
from src.nodes.reflection import ReflectionNode
from src.middleware.base import PluginContext
from src.middleware.tenant import TenantMiddleware
from src.middleware.audit import AuditMiddleware
from src.middleware.context import ContextMiddleware
from src.middleware.hitl import HITLMiddleware, HITLRule


# ── 测试用的 Mock Tool ──

class EchoTool(Tool):
    @property
    def name(self): return "echo"
    def input_schema(self): return {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]}
    async def call(self, input_data, context, on_progress=None):
        return ToolResult(content=f"Echo: {input_data.get('text', '')}")
    async def description(self, input_data): return f"Echo: {input_data.get('text', '')}"
    def prompt(self): return "回显输入文本"


class FailTool(Tool):
    @property
    def name(self): return "fail_tool"
    def input_schema(self): return {"type": "object", "properties": {}}
    async def call(self, input_data, context, on_progress=None):
        return ToolResult(content="操作失败: 模拟错误", is_error=True)
    async def description(self, input_data): return "fail"
    def prompt(self): return "总是失败的工具"


class DeleteTool(Tool):
    @property
    def name(self): return "delete_data"
    def input_schema(self): return {"type": "object", "properties": {"id": {"type": "string"}}}
    async def call(self, input_data, context, on_progress=None):
        return ToolResult(content=f"已删除 {input_data.get('id')}")
    async def description(self, input_data): return "删除数据"
    def is_destructive(self, input_data): return True
    def prompt(self): return "删除数据（破坏性操作）"


# ── 辅助函数 ──

def make_registry(*tools):
    reg = ToolRegistry()
    for t in tools:
        reg.register(t)
    return reg


def make_state(user_msg: str, **kw) -> GraphState:
    state = GraphState(
        tenant_id="test_tenant",
        user_id="test_user",
        messages=[Message(role=MessageRole.USER, content=user_msg)],
        system_prompt="你是测试助手。",
        **kw,
    )
    return state


passed = 0
failed = 0

def check(name, condition):
    global passed, failed
    if condition:
        print(f"  ✅ {name}")
        passed += 1
    else:
        print(f"  ❌ {name}")
        failed += 1


# ═══════════════════════════════════════════
# 测试 1: Router 路由决策
# ═══════════════════════════════════════════

def test_router():
    print("\n📦 1. Router 路由决策")
    router = Router()

    # 无计划 → planning
    s = GraphState()
    check("无计划 → planning", router.next_node(s) == "planning")

    # 非 RUNNING → None
    s2 = GraphState(status=AgentStatus.COMPLETED)
    check("COMPLETED → None", router.next_node(s2) is None)

    # 预算耗尽 → reflection
    s3 = GraphState(total_llm_calls=200)
    node = router.next_node(s3)
    check("预算耗尽 → reflection", node == "reflection")

    # stuck → reflection
    s4 = GraphState(consecutive_errors=5)
    from src.graph.state import TaskPlan, TaskStep
    s4.plan = TaskPlan(goal="test", steps=[TaskStep(description="step1")])
    check("连续错误 → reflection", router.next_node(s4) == "reflection")

    # 预算警告
    s5 = GraphState(total_llm_calls=165)
    warning = router.inject_budget_warning(s5)
    check("80% 预算警告", warning is not None and "80%" in warning)

    s6 = GraphState(total_llm_calls=195)
    warning2 = router.inject_budget_warning(s6)
    check("95% 预算警告", warning2 is not None and "URGENT" in warning2)


# ═══════════════════════════════════════════
# 测试 2: PlanningNode
# ═══════════════════════════════════════════

async def test_planning():
    print("\n📦 2. PlanningNode")

    # 简单任务 → 单步计划
    mock_llm = MockLLMClient()
    ctx = PluginContext(llm=mock_llm, tool_registry=make_registry())
    node = PlanningNode()

    state = make_state("查一下客户信息")
    state = await node.execute(state, ctx)
    check("简单任务 → 单步计划", state.plan is not None and len(state.plan.steps) == 1)
    check("LLM 未调用（简单任务）", mock_llm.call_count == 0)

    # 复杂任务 → LLM 规划
    mock_llm2 = MockLLMClient()
    mock_llm2.add_text_response('{"goal": "分析销售数据", "steps": [{"description": "查询元数据"}, {"description": "查询数据"}, {"description": "生成报告"}]}')
    ctx2 = PluginContext(llm=mock_llm2, tool_registry=make_registry())

    state2 = make_state("帮我分析上个月的销售数据，找出转化率最低的渠道，然后给出优化建议")
    state2 = await node.execute(state2, ctx2)
    check("复杂任务 → 多步计划", state2.plan is not None and len(state2.plan.steps) == 3)
    check("LLM 已调用", mock_llm2.call_count == 1)


# ═══════════════════════════════════════════
# 测试 3: ExecutionNode
# ═══════════════════════════════════════════

async def test_execution():
    print("\n📦 3. ExecutionNode")

    # 纯文本响应 → 步骤完成
    mock_llm = MockLLMClient()
    mock_llm.add_text_response("客户信息如下: 华为技术有限公司")

    registry = make_registry(EchoTool())
    ctx = PluginContext(llm=mock_llm, tool_registry=registry, middlewares=[])

    from src.graph.state import TaskPlan, TaskStep
    state = make_state("查客户")
    state.plan = TaskPlan(goal="查客户", steps=[TaskStep(description="查询客户信息")])
    state.system_prompt = "你是测试助手。"

    node = ExecutionNode()
    state = await node.execute(state, ctx)
    check("纯文本 → 步骤完成", state.plan.steps[0].status == StepStatus.COMPLETED)
    check("step_index 推进", state.current_step_index == 1)

    # 工具调用 → 执行 → 再次 LLM → 完成
    mock_llm2 = MockLLMClient()
    mock_llm2.add_tool_call_response("echo", {"text": "hello"})
    mock_llm2.add_text_response("工具返回: Echo: hello")

    state2 = make_state("测试工具")
    state2.plan = TaskPlan(goal="test", steps=[TaskStep(description="调用 echo")])
    state2.system_prompt = "你是测试助手。"
    ctx2 = PluginContext(llm=mock_llm2, tool_registry=registry, middlewares=[])

    state2 = await node.execute(state2, ctx2)
    check("工具调用 → 步骤完成", state2.plan.steps[0].status == StepStatus.COMPLETED)
    check("工具调用计数", state2.total_tool_calls == 1)
    check("LLM 调用计数", state2.total_llm_calls == 2)


# ═══════════════════════════════════════════
# 测试 4: ReflectionNode
# ═══════════════════════════════════════════

async def test_reflection():
    print("\n📦 4. ReflectionNode")

    node = ReflectionNode()
    mock_llm = MockLLMClient()
    ctx = PluginContext(llm=mock_llm, tool_registry=make_registry(), middlewares=[])

    # Stuck 自救
    from src.graph.state import TaskPlan, TaskStep
    state = make_state("test")
    state.plan = TaskPlan(goal="test", steps=[TaskStep(description="s1", status=StepStatus.RUNNING)])
    state.consecutive_errors = 5
    state = await node.execute(state, ctx)
    check("stuck → 重置计数器", state.consecutive_errors == 0)
    check("stuck → 注入 prompt", any("STUCK" in str(m.content) for m in state.messages))

    # 最终反思
    state2 = make_state("test")
    state2.plan = TaskPlan(goal="test", steps=[TaskStep(description="s1", status=StepStatus.COMPLETED)])
    state2.messages.append(Message(role=MessageRole.ASSISTANT, content="任务完成"))
    state2 = await node.execute(state2, ctx)
    check("最终反思 → COMPLETED", state2.status == AgentStatus.COMPLETED)

    # 步骤失败 → LLM 分析
    mock_llm3 = MockLLMClient()
    mock_llm3.add_text_response('{"strategy": "skip", "reason": "步骤不重要"}')
    ctx3 = PluginContext(llm=mock_llm3, tool_registry=make_registry(), middlewares=[])

    state3 = make_state("test")
    state3.plan = TaskPlan(goal="test", steps=[
        TaskStep(description="s1", status=StepStatus.FAILED, error="超时"),
        TaskStep(description="s2"),
    ])
    state3 = await node.execute(state3, ctx3)
    check("失败分析 → skip", state3.plan.steps[0].status == StepStatus.SKIPPED)
    check("失败分析 → 推进", state3.current_step_index == 1)


# ═══════════════════════════════════════════
# 测试 5: HITL 中断
# ═══════════════════════════════════════════

async def test_hitl():
    print("\n📦 5. HITL 中断")

    registry = make_registry(DeleteTool())
    hitl = HITLMiddleware()

    mock_ctx = PluginContext(llm=MockLLMClient(), tool_registry=registry, middlewares=[])
    state = make_state("删除数据")

    result = await hitl.before_tool_call("delete_data", {"id": "123"}, state, mock_ctx)
    check("破坏性操作 → 暂停", state.status == AgentStatus.PAUSED)
    check("返回 None（阻止执行）", result is None)
    check("暂停原因", state.pause_reason is not None and "破坏性" in state.pause_reason)


# ═══════════════════════════════════════════
# 测试 6: GraphEngine 端到端
# ═══════════════════════════════════════════

async def test_engine_e2e():
    print("\n📦 6. GraphEngine 端到端")

    mock_llm = MockLLMClient()
    # PlanningNode 会判断为简单任务，不调 LLM
    # ExecutionNode 调 LLM → 纯文本响应
    mock_llm.add_text_response("华为技术有限公司，成立于1987年，注册资本4104113万元。")
    # ReflectionNode 最终反思不调 LLM（无 memory plugin）

    registry = make_registry(EchoTool())
    config = AgentConfig(
        tenant_id="t1",
        user_id="u1",
        llm_client=mock_llm,
        tool_registry=registry,
        enable_hitl=False,
        enable_audit=False,
    )

    engine, sys_prompt = AgentFactory.create(config)
    state = GraphState(
        tenant_id="t1",
        user_id="u1",
        system_prompt=sys_prompt,
        messages=[Message(role=MessageRole.USER, content="查一下华为的信息")],
    )

    states = []
    async for s in engine.run(state):
        states.append(s)

    final = states[-1]
    check("最终状态 COMPLETED", final.status == AgentStatus.COMPLETED)
    check("有最终回答", bool(final.final_answer))
    check("LLM 调用 >= 1", final.total_llm_calls >= 1)


# ═══════════════════════════════════════════
# 测试 7: AgentFactory 创建
# ═══════════════════════════════════════════

def test_factory():
    print("\n📦 7. AgentFactory")

    mock_llm = MockLLMClient()
    registry = make_registry(EchoTool())

    config = AgentConfig(
        tenant_id="t1",
        user_id="u1",
        llm_client=mock_llm,
        tool_registry=registry,
    )

    engine, sys_prompt = AgentFactory.create(config)
    check("engine 创建成功", engine is not None)
    check("system_prompt 非空", len(sys_prompt) > 0)
    check("system_prompt 包含工具提示", "echo" in sys_prompt.lower() or "可用工具" in sys_prompt)


# ═══════════════════════════════════════════
# 测试 8: ContextMiddleware 压缩
# ═══════════════════════════════════════════

async def test_context_middleware():
    print("\n📦 8. ContextMiddleware")

    mw = ContextMiddleware()

    # 代码提取
    import json
    data = json.dumps({"records": [{"name": "华为"}, {"name": "腾讯"}, {"name": "阿里"}], "total": 3})
    extracted = mw._try_code_extract(data)
    check("JSON 代码提取", extracted is not None and "3条" in extracted)

    # MD5 去重
    from src.dtypes import Message, MessageRole, ToolResultBlock
    long_content = "long result data " * 50
    msgs = [
        Message(role=MessageRole.USER, content="q1"),
        Message(role=MessageRole.USER, content="tool result", tool_result_blocks=[
            ToolResultBlock(tool_use_id="t1", content=long_content)
        ]),
        Message(role=MessageRole.USER, content="q2"),
        Message(role=MessageRole.USER, content="tool result", tool_result_blocks=[
            ToolResultBlock(tool_use_id="t2", content=long_content)
        ]),
    ]
    deduped = mw._pass1_dedup(msgs)
    # 第一个重复的（index 1）应该被替换，第二个（index 3）保留
    first_tr = deduped[1].tool_result_blocks[0].content if deduped[1].tool_result_blocks else ""
    second_tr = deduped[3].tool_result_blocks[0].content if deduped[3].tool_result_blocks else ""
    check("MD5 去重", "重复" in first_tr and "重复" not in second_tr)


# ═══════════════════════════════════════════
# 运行所有测试
# ═══════════════════════════════════════════

if __name__ == "__main__":
    test_router()
    asyncio.run(test_planning())
    asyncio.run(test_execution())
    asyncio.run(test_reflection())
    asyncio.run(test_hitl())
    asyncio.run(test_engine_e2e())
    test_factory()
    asyncio.run(test_context_middleware())

    print(f"\n{'='*50}")
    print(f"  DeepAgent 测试: {passed} passed, {failed} failed")
    print(f"{'='*50}")
    sys.exit(1 if failed else 0)
