#!/usr/bin/env python3
"""
DeepAgent CRM Demo — 完整业务逻辑演示

除 LLM 外，所有业务逻辑均为真实模拟:
  - CrmSimulatedBackend: 内存 CRM 数据库，5 客户 / 5 联系人 / 7 商机 / 5 活动 / 5 线索
  - 真实 CRUD: 查询/过滤/分页/排序/创建/更新/删除/聚合
  - 真实元数据: 5 个实体 Schema + 字段定义 + 关联关系
  - 真实权限: 角色/数据范围模拟

运行: poetry run python demo.py
"""
import asyncio
import json
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

from src.dtypes import Message, MessageRole, ToolResult
from src.tools import ToolRegistry
from src.llm_client import MockLLMClient
from src.graph.state import GraphState, AgentStatus, StepStatus
from src.graph.factory import AgentFactory, AgentConfig
from src.crm_backend import CrmSimulatedBackend
from src.crm_tools import register_crm_tools


def header(title: str):
    print(f"\n{'━'*64}")
    print(f"  {title}")
    print(f"{'━'*64}")

def print_state(s: GraphState, backend: CrmSimulatedBackend | None = None):
    parts = [f"status={s.status.value}", f"llm={s.total_llm_calls}", f"tools={s.total_tool_calls}"]
    if s.plan:
        done = sum(1 for st in s.plan.steps if st.status in (StepStatus.COMPLETED, StepStatus.SKIPPED))
        parts.append(f"steps={done}/{len(s.plan.steps)}")
    if s.file_list:
        parts.append(f"虚拟文件={len(s.file_list)}")
    if backend:
        parts.append(f"审计日志={len(backend.audit_log)}条")
    print(f"  📊 {', '.join(parts)}")

def build(mock: MockLLMClient, backend: CrmSimulatedBackend, **kw):
    registry = ToolRegistry()
    register_crm_tools(registry, backend)
    engine, prompt = AgentFactory.create(AgentConfig(
        tenant_id="tenant_001", user_id="user_zhang",
        llm_client=mock, tool_registry=registry,
        enable_audit=False, **kw,
    ))
    return engine, prompt, registry


# ═══════════════════════════════════════════════════════════
# 场景 1: 查询客户列表 + 过滤 + 排序
# ═══════════════════════════════════════════════════════════

async def demo_1():
    header("场景 1: 查询客户列表（真实过滤 + 排序）")
    backend = CrmSimulatedBackend()
    mock = MockLLMClient()

    # LLM 决定查询活跃客户，按营收降序
    mock.add_tool_call_response("query_data", {
        "action": "query", "entity_api_key": "account",
        "filters": {"activeFlg": 1}, "order_by": "-annualRevenue",
    })
    mock.add_text_response(
        "系统中有 4 个活跃客户，按营收排序:\n"
        "1. 华为 8809 亿\n2. 腾讯 6090 亿\n3. 比亚迪 6020 亿\n4. 招商银行 3400 亿\n"
        "万科已标记为不活跃。"
    )

    engine, prompt, _ = build(mock, backend, enable_hitl=False)
    s = GraphState(system_prompt=prompt, messages=[Message(role=MessageRole.USER, content="查一下活跃客户，按营收排序")])
    async for s in engine.run(s): pass

    print(f"  [User] 查一下活跃客户，按营收排序")
    print(f"  [Agent] {s.final_answer}")
    print_state(s, backend)


# ═══════════════════════════════════════════════════════════
# 场景 2: 查客户详情 + 关联商机 + 联系人（多步计划）
# ═══════════════════════════════════════════════════════════

async def demo_2():
    header("场景 2: 客户 360 视图（客户 + 商机 + 联系人 + 活动）")
    backend = CrmSimulatedBackend()
    mock = MockLLMClient()

    # Planning: 4 步
    mock.add_text_response(json.dumps({"goal": "华为360视图", "steps": [
        {"description": "查询华为客户详情"},
        {"description": "查询华为的商机"},
        {"description": "查询华为的联系人"},
        {"description": "汇总分析"},
    ]}))
    # Step 1: 查客户
    mock.add_tool_call_response("query_data", {"action": "get", "entity_api_key": "account", "record_id": "acc_001"})
    mock.add_text_response("已获取华为基本信息。")
    # Step 2: 查商机
    mock.add_tool_call_response("query_data", {"action": "query", "entity_api_key": "opportunity", "filters": {"accountId": "acc_001"}})
    mock.add_text_response("已获取华为的 4 个商机。")
    # Step 3: 查联系人
    mock.add_tool_call_response("query_data", {"action": "query", "entity_api_key": "contact", "filters": {"accountId": "acc_001"}})
    mock.add_text_response("已获取华为的 2 个联系人。")
    # Step 4: 汇总
    mock.add_text_response(
        "# 华为 360 视图\n"
        "- 基本信息: 通信设备/深圳/207,000人/营收8809亿/评分95\n"
        "- 商机(4个): ERP $45万(proposal) / CRM $28万(negotiation) / BI $15万(qualification) / 安全审计 $18万(closing)\n"
        "- 联系人: 张伟(IT总监,主要) / 李娜(采购经理)\n"
        "- 建议: CRM部署和安全审计即将关闭，优先跟进"
    )

    engine, prompt, _ = build(mock, backend, enable_hitl=False)
    s = GraphState(system_prompt=prompt, messages=[Message(role=MessageRole.USER, content="帮我分析华为的完整情况，对比商机和联系人")])
    async for s in engine.run(s): pass

    print(f"  [User] 帮我分析华为的完整情况，对比商机和联系人")
    print(f"  [Agent] {s.final_answer}")
    print_state(s, backend)


# ═══════════════════════════════════════════════════════════
# 场景 3: 数据聚合分析（Pipeline 分析）
# ═══════════════════════════════════════════════════════════

async def demo_3():
    header("场景 3: Pipeline 分析（真实聚合计算）")
    backend = CrmSimulatedBackend()
    mock = MockLLMClient()

    # LLM 调用聚合工具: 按阶段分组统计商机金额
    mock.add_tool_call_response("analyze_data", {
        "entity_api_key": "opportunity",
        "metrics": [{"field": "amount", "function": "sum"}, {"field": "amount", "function": "count"}],
        "group_by": "stage",
    })
    # 再查总体指标
    mock.add_tool_call_response("analyze_data", {
        "entity_api_key": "opportunity",
        "metrics": [{"field": "amount", "function": "sum"}, {"field": "amount", "function": "avg"}, {"field": "probability", "function": "avg"}],
    })
    mock.add_text_response(
        "# Pipeline 分析报告\n"
        "总商机: 7 个，总金额 373 万\n"
        "按阶段分布:\n"
        "- closing: 1个/18万 (即将成交)\n"
        "- negotiation: 2个/148万 (谈判中)\n"
        "- proposal: 2个/107万 (方案阶段)\n"
        "- qualification: 1个/15万\n"
        "- prospecting: 1个/85万\n"
        "平均赢单概率: 57.9%\n"
        "建议: 重点推进 negotiation 阶段的招行风控(120万)和华为CRM(28万)"
    )

    engine, prompt, _ = build(mock, backend, enable_hitl=False)
    s = GraphState(system_prompt=prompt, messages=[Message(role=MessageRole.USER, content="分析一下当前的 Pipeline 情况")])
    async for s in engine.run(s): pass

    print(f"  [User] 分析一下当前的 Pipeline 情况")
    print(f"  [Agent] {s.final_answer}")
    print_state(s, backend)


# ═══════════════════════════════════════════════════════════
# 场景 4: 创建记录 + 更新记录（真实写入）
# ═══════════════════════════════════════════════════════════

async def demo_4():
    header("场景 4: 创建活动 + 更新商机阶段（真实写入数据库）")
    backend = CrmSimulatedBackend()
    mock = MockLLMClient()

    # Planning: 2 步
    mock.add_text_response(json.dumps({"goal": "记录跟进", "steps": [
        {"description": "创建跟进活动"},
        {"description": "更新商机阶段"},
    ]}))
    # Step 1: 创建活动
    mock.add_tool_call_response("modify_data", {
        "action": "create", "entity_api_key": "activity",
        "data": {"type": "call", "subject": "华为CRM报价确认电话",
                 "description": "与李娜确认最终报价和实施时间表",
                 "accountId": "acc_001", "opportunityId": "opp_002", "contactId": "con_002",
                 "dueDate": "2025-04-22", "status": "pending"},
    })
    mock.add_text_response("已创建跟进活动。")
    # Step 2: 更新商机阶段
    mock.add_tool_call_response("modify_data", {
        "action": "update", "entity_api_key": "opportunity",
        "record_id": "opp_002",
        "data": {"stage": "closing", "probability": 90, "lastActivityDate": "2025-04-21"},
    })
    mock.add_text_response(
        "已完成:\n"
        "1. 创建了华为CRM报价确认电话活动\n"
        "2. 华为CRM部署商机阶段从 negotiation 更新为 closing，赢单概率提升到 90%"
    )

    engine, prompt, _ = build(mock, backend, enable_hitl=False)
    s = GraphState(system_prompt=prompt, messages=[Message(role=MessageRole.USER, content="帮我记录一下华为CRM的跟进情况，然后把商机阶段改为closing")])
    async for s in engine.run(s): pass

    print(f"  [User] 帮我记录华为CRM跟进，把商机阶段改为closing")
    print(f"  [Agent] {s.final_answer}")

    # 验证数据真实写入
    opp = await backend.query_data("opportunity", {"id": "opp_002"})
    opp_record = opp["data"]["records"][0]
    acts = await backend.query_data("activity", {"opportunityId": "opp_002"})
    print(f"\n  ✅ 数据库验证:")
    print(f"     商机 opp_002 阶段: {opp_record['stage']} (概率: {opp_record['probability']}%)")
    print(f"     关联活动数: {acts['data']['total']} 条")
    print_state(s, backend)


# ═══════════════════════════════════════════════════════════
# 场景 5: 删除过期线索（HITL 审批 + 真实删除）
# ═══════════════════════════════════════════════════════════

async def demo_5():
    header("场景 5: 批量删除过期线索（HITL 审批 + 真实删除）")
    backend = CrmSimulatedBackend()
    mock = MockLLMClient()

    # Planning: 3 步
    mock.add_text_response(json.dumps({"goal": "清理过期线索", "steps": [
        {"description": "统计过期线索数量"},
        {"description": "确认后删除"},
        {"description": "报告结果"},
    ]}))
    # Step 1: 统计
    mock.add_tool_call_response("query_data", {"action": "count", "entity_api_key": "lead", "filters": {"status": "expired"}})
    mock.add_text_response("有 2 条过期线索。")
    # Step 2: 删除（触发 HITL）
    mock.add_tool_call_response("modify_data", {
        "action": "delete", "entity_api_key": "lead",
        "data": {"filters": {"status": "expired"}},
    })
    mock.add_text_response("已删除 2 条过期线索。")
    # Step 3: 报告
    mock.add_text_response("清理完成: 删除了 2 条过期线索（测试公司A的吴芳、测试公司B的郑浩），剩余 3 条有效线索。")

    engine, prompt, _ = build(mock, backend, enable_hitl=True)
    s = GraphState(system_prompt=prompt, messages=[Message(role=MessageRole.USER, content="帮我清理过期的线索，统计数量然后删除")])

    print(f"  [User] 帮我清理过期的线索，统计数量然后删除")

    # 第一轮: 执行到 HITL 暂停
    async for s in engine.run(s): pass

    if s.status == AgentStatus.PAUSED:
        print(f"  ⏸️  暂停: {s.pause_reason}")

        # 验证删除前数据
        leads_before = await backend.query_data("lead", {})
        print(f"  📋 删除前线索数: {leads_before['data']['total']}")
        print(f"  [User] 确认删除 ✓")

        # 恢复
        async for s in engine.resume(s, "approve"): pass

    # 验证删除后数据
    leads_after = await backend.query_data("lead", {})
    expired = await backend.query_data("lead", {"status": "expired"})
    print(f"\n  [Agent] {s.final_answer}")
    print(f"\n  ✅ 数据库验证:")
    print(f"     删除后线索数: {leads_after['data']['total']}")
    print(f"     过期线索数: {expired['data']['total']}")
    print_state(s, backend)


# ═══════════════════════════════════════════════════════════
# 场景 6: 元数据查询 + 上下文压缩
# ═══════════════════════════════════════════════════════════

async def demo_6():
    header("场景 6: 元数据查询 + 上下文压缩（大结果自动摘要）")
    backend = CrmSimulatedBackend()
    mock = MockLLMClient()

    # LLM 先查实体列表，再查 opportunity 的字段定义
    mock.add_tool_call_response("query_schema", {"query_type": "list_entities"})
    mock.add_tool_call_response("query_schema", {"query_type": "entity_items", "entity_api_key": "opportunity"})
    mock.add_text_response(
        "系统有 5 个业务对象: 客户/联系人/商机/活动/线索。\n"
        "商机有 9 个字段: 名称/客户/金额/阶段/概率/关闭日期/负责人/来源/最后活动日期。\n"
        "阶段选项: prospecting → qualification → proposal → negotiation → closing → won/lost"
    )

    engine, prompt, _ = build(mock, backend, enable_hitl=False)
    s = GraphState(system_prompt=prompt, messages=[Message(role=MessageRole.USER, content="系统有哪些业务对象？商机有哪些字段？")])
    async for s in engine.run(s): pass

    print(f"  [User] 系统有哪些业务对象？商机有哪些字段？")
    print(f"  [Agent] {s.final_answer}")
    if s.file_list:
        print(f"\n  📦 上下文压缩:")
        for f in s.file_list:
            print(f"     {f.file_path}: {len(f.content)}字符 → 摘要: {f.summary[:60]}...")
    print_state(s, backend)


# ═══════════════════════════════════════════════════════════
# 场景 7: 长期记忆（画像 + 召回 + 提取）
# ═══════════════════════════════════════════════════════════

async def demo_7():
    header("场景 7: 长期记忆（画像注入 + 自动召回 + 记忆提取）")
    backend = CrmSimulatedBackend()

    # 构建 memory plugin
    class DemoMemory:
        def __init__(self):
            self.store = [
                {"category": "profile", "content": "用户是销售经理张三，负责深圳区域大客户，偏好简洁报告"},
                {"category": "cases", "content": "上次分析华为时发现CRM部署项目赢单概率最高(80%)，建议优先跟进"},
                {"category": "patterns", "content": "华为采购决策链: IT总监张伟推荐→采购经理李娜审批→VP最终决策"},
                {"category": "entities", "content": "华为关键联系人: 张伟(IT总监,主要决策影响者), 李娜(采购经理,预算审批)"},
            ]
        async def recall(self, query, categories=None, max_results=5):
            results = []
            for e in self.store:
                if categories and e["category"] not in categories:
                    continue
                if any(c in e["content"] for c in query if len(c) > 1):
                    results.append(e)
                if len(results) >= max_results:
                    break
            return results
        async def commit(self, entry):
            self.store.append(entry)

    memory = DemoMemory()
    mock = MockLLMClient()

    # ExecutionNode: 查商机 + 回答
    mock.add_tool_call_response("query_data", {"action": "query", "entity_api_key": "opportunity",
        "filters": {"accountId": "acc_001"}, "order_by": "-probability"})
    mock.add_text_response(
        "基于历史经验和当前数据:\n"
        "华为有 4 个商机，按赢单概率排序:\n"
        "1. 安全审计 $18万 (closing, 90%) — 本月可关闭\n"
        "2. CRM部署 $28万 (negotiation, 80%) — 上次分析也建议优先跟进\n"
        "3. ERP实施 $45万 (proposal, 60%)\n"
        "4. BI平台 $15万 (qualification, 30%)\n"
        "建议: 联系张伟(IT总监)推进安全审计签约，同时让李娜(采购经理)加速CRM审批"
    )
    # ReflectionNode: 记忆提取
    mock.add_text_response(json.dumps([
        {"category": "cases", "content": "2025-04-21 华为商机分析: 安全审计即将关闭($18万), CRM部署进入谈判($28万)", "importance": "high"},
        {"category": "patterns", "content": "华为安全审计从proposal到closing仅用2个月，决策速度快于其他项目", "importance": "medium"},
    ]))

    registry = ToolRegistry()
    register_crm_tools(registry, backend)
    engine, prompt = AgentFactory.create(AgentConfig(
        tenant_id="tenant_001", user_id="user_zhang",
        llm_client=mock, tool_registry=registry,
        memory_plugin=memory, enable_hitl=False, enable_audit=False,
    ))
    s = GraphState(system_prompt=prompt, messages=[Message(role=MessageRole.USER, content="帮我看看华为的商机，给出跟进建议")])
    async for s in engine.run(s): pass

    print(f"  [User] 帮我看看华为的商机，给出跟进建议")
    if s.memory_context:
        print(f"\n  🧠 记忆注入:")
        for line in s.memory_context.strip().split("\n")[:6]:
            if line.strip():
                print(f"     {line.strip()}")
    print(f"\n  [Agent] {s.final_answer}")

    new_memories = memory.store[4:]  # 排除预置的 4 条
    if new_memories:
        print(f"\n  💾 新提取记忆:")
        for m in new_memories:
            print(f"     [{m['category']}] {m['content'][:80]}")
    print_state(s, backend)


# ═══════════════════════════════════════════════════════════
# 场景 8: Stuck 自救 + 反思
# ═══════════════════════════════════════════════════════════

async def demo_8():
    header("场景 8: Stuck 自救（连续错误 → 反思 → 换策略成功）")
    backend = CrmSimulatedBackend()
    mock = MockLLMClient()

    # LLM 连续调用不存在的工具
    for _ in range(5):
        mock.add_tool_call_response("web_search", {"query": "华为最新动态"})
    # Stuck recovery 后换策略，用内部数据
    mock.add_tool_call_response("query_data", {"action": "query", "entity_api_key": "account", "filters": {"name": "华为技术有限公司"}})
    mock.add_text_response("华为技术有限公司，通信设备行业，207,000人，年营收8809亿，评分95。")

    engine, prompt, _ = build(mock, backend, enable_hitl=False)
    s = GraphState(system_prompt=prompt, messages=[Message(role=MessageRole.USER, content="查一下华为的最新情况")])
    async for s in engine.run(s): pass

    stuck = any("STUCK" in str(getattr(m, "content", "")) for m in s.messages)
    print(f"  [User] 查一下华为的最新情况")
    print(f"  🔄 Stuck 自救触发: {'是' if stuck else '否'}")
    print(f"  [Agent] {s.final_answer}")
    print_state(s, backend)


# ═══════════════════════════════════════════════════════════
# 场景 9: 失败 → replan → 成功
# ═══════════════════════════════════════════════════════════

async def demo_9():
    header("场景 9: 失败分析 → replan → 用新方案成功")
    backend = CrmSimulatedBackend()
    mock = MockLLMClient()

    # 第一次规划
    mock.add_text_response(json.dumps({"goal": "竞品分析", "steps": [
        {"description": "搜索竞品信息"}, {"description": "对比分析"}]}))
    # Step 1 失败（web_search 不存在）
    mock.add_tool_call_response("web_search", {"query": "竞品分析"})
    mock.add_tool_call_response("web_search", {"query": "竞品"})
    mock.add_tool_call_response("web_search", {"query": "competitor"})
    # 步骤预算耗尽 → ReflectionNode 分析 → replan
    mock.add_text_response('{"strategy": "replan", "reason": "搜索工具不可用，改用内部数据对比客户"}')
    # 第二次规划
    mock.add_text_response(json.dumps({"goal": "用内部数据", "steps": [{"description": "对比客户数据"}]}))
    # 新方案成功
    mock.add_tool_call_response("analyze_data", {
        "entity_api_key": "account",
        "metrics": [{"field": "annualRevenue", "function": "sum"}, {"field": "annualRevenue", "function": "avg"}],
    })
    mock.add_text_response(
        "基于内部客户数据分析:\n"
        "5 个客户总营收 22.92 亿，平均 4.58 亿。\n"
        "华为(8809亿)和腾讯(6090亿)是最大客户，占总营收 65%。"
    )

    # 用完整 registry — web_search 不存在但 analyze_data 存在
    # 第一次规划尝试 web_search（失败），replan 后改用 analyze_data（成功）
    engine, prompt, _ = build(mock, backend, enable_hitl=False, max_step_llm_calls=3)
    s = GraphState(system_prompt=prompt, messages=[Message(role=MessageRole.USER, content="帮我分析一下竞品情况然后对比客户数据")])
    async for s in engine.run(s): pass

    print(f"  [User] 帮我分析一下竞品情况然后对比客户数据")
    print(f"  🔄 重规划次数: {s.replan_count}")
    print(f"  [Agent] {s.final_answer}")
    print_state(s, backend)


# ═══════════════════════════════════════════════════════════
# 主入口
# ═══════════════════════════════════════════════════════════

async def main():
    print("=" * 64)
    print("  DeepAgent CRM Demo — 完整业务逻辑")
    print("  数据库: 5客户 / 5联系人 / 7商机 / 5活动 / 5线索")
    print("  除 LLM 外全部真实模拟")
    print("=" * 64)

    await demo_1()   # 查询 + 过滤 + 排序
    await demo_2()   # 客户 360 视图（多步）
    await demo_3()   # Pipeline 聚合分析
    await demo_4()   # 创建 + 更新（真实写入）
    await demo_5()   # 删除 + HITL 审批
    await demo_6()   # 元数据 + 上下文压缩
    await demo_7()   # 长期记忆
    await demo_8()   # Stuck 自救
    await demo_9()   # 失败 → replan

    print(f"\n{'='*64}")
    print("  全部 9 个场景演示完成 ✅")
    print(f"{'='*64}")


if __name__ == "__main__":
    asyncio.run(main())
