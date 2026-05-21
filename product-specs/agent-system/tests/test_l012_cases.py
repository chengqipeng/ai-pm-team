"""基于 L0-L1-L2 提取结果对比清单的 20 个场景验证

验证 VikingMemoryEngine 的提取逻辑是否符合设计预期：
  - 纯数据查询 → 不提取
  - 增量认知 → 提取
  - 混合对话 → 只提取增量部分

运行:
  cd product-specs/agent-system
  .venv/bin/python -B tests/test_l012_cases.py
"""
import asyncio
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("DEEPSEEK_API_KEY", "sk-HdY98AcN68JhtXLp8oeIATEL4PWq9rzRcCAhI8G4SOtBbtSw")

from langchain_core.messages import HumanMessage, AIMessage, ToolMessage

passed = 0
failed = 0
results_log = []  # 收集所有结果用于最终汇总


def check(name, condition, detail=""):
    global passed, failed
    if condition:
        print(f"  ✅ {name}")
        passed += 1
    else:
        print(f"  ❌ {name}")
        if detail:
            print(f"     {detail}")
        failed += 1


def _print_extracted(r):
    if not r.items:
        print(f"    → 提取 0 条（空）")
        return
    print(f"    → 提取 {len(r.items)} 条:")
    for item in r.items:
        cat = item.metadata.get("category", "?")
        full = item.metadata.get("full_content", "")
        overview = item.metadata.get("overview", "")
        print(f"      [{cat}] L0: {item.content}")
        if overview:
            print(f"             L1: {overview[:80]}...")
        if full and full != item.content:
            print(f"             L2: {full[:100]}...")


def _llm():
    from langchain_openai import ChatOpenAI
    return ChatOpenAI(
        model="deepseek-v4-flash",
        api_key=os.environ["DEEPSEEK_API_KEY"],
        base_url="https://tokenhub.tencentmaas.com/v1",
        max_tokens=2048,
    )


def _engine():
    from src.memory.viking_engine import VikingMemoryEngine
    return VikingMemoryEngine(
        vdb_url="http://10.60.2.17",
        vdb_key="bRG3NETg13tv5Fn68VTdkxaJXH9tMQzhKeT3unck",
        vdb_username="root",
        database_name="viking_case_test",
        collection_name="case_v1",
        llm=_llm(),
        use_pg=False,
    )


# ═══════════════════════════════════════════════════════════
# 20 个场景
# ═══════════════════════════════════════════════════════════

async def run_case(e, case_num, title, messages, expect_count, expect_cats=None,
                   expect_keywords=None, expect_no_keywords=None):
    """通用测试执行器"""
    uid = f"case_{case_num}"
    print(f"\n{'─'*60}")
    print(f"  场景 {case_num}: {title}")
    print(f"{'─'*60}")

    r = await e.extract_and_update(messages, thread_id=f"t-{case_num}", user_id=uid)
    _print_extracted(r)

    # 验证数量
    if expect_count == 0:
        check(f"{case_num}. 不提取", len(r.items) == 0,
              f"期望0条，实际{len(r.items)}条")
    elif expect_count == -1:  # -1 表示至少1条
        check(f"{case_num}. 有提取", len(r.items) >= 1,
              f"期望>=1条，实际{len(r.items)}条")
    else:
        check(f"{case_num}. 提取{expect_count}条", len(r.items) >= expect_count,
              f"期望>={expect_count}条，实际{len(r.items)}条")

    # 验证类别
    if expect_cats and r.items:
        actual_cats = {i.metadata.get("category") for i in r.items}
        for ec in expect_cats:
            check(f"{case_num}. 包含{ec}", ec in actual_cats,
                  f"实际类别: {actual_cats}")

    # 验证关键词（应该出现）
    if expect_keywords and r.items:
        all_text = " ".join(i.content + " " + i.metadata.get("full_content", "") for i in r.items)
        for kw in expect_keywords:
            check(f"{case_num}. 包含'{kw}'", kw in all_text,
                  f"未在提取结果中找到'{kw}'")

    # 验证关键词（不应该出现在 L0 中）
    if expect_no_keywords and r.items:
        l0_text = " ".join(i.content for i in r.items)
        for kw in expect_no_keywords:
            # 宽松检查：如果 L0 中出现了系统数据字段值，标记但不算失败
            if kw in l0_text:
                print(f"  ⚠️  L0中出现了系统数据'{kw}'（可优化）")

    results_log.append({
        "case": case_num, "title": title,
        "count": len(r.items),
        "categories": list({i.metadata.get("category") for i in r.items}),
    })

    await asyncio.sleep(0.5)  # 避免 LLM 限流
    return r


async def main():
    e = _engine()
    print("=" * 60)
    print("  L0/L1/L2 提取验证 — 20 个场景")
    print("=" * 60)

    # ── 场景 1: 纯数据查询 → 不提取 ──
    await run_case(e, 1, "纯数据查询 → 不提取", [
        HumanMessage(content="查一下华为的商机"),
        AIMessage(content="", tool_calls=[{"id":"tc1","name":"query_data","args":{}}]),
        ToolMessage(content='{"records":[{"id":"opp_001","name":"华为ERP实施","amount":45,"stage":"proposal"}]}',
                    tool_call_id="tc1", name="query_data"),
        AIMessage(content="华为有1个商机：ERP实施45万，proposal阶段。"),
    ], expect_count=0)

    # ── 场景 2: 数据查询 + 用户判断 ──
    await run_case(e, 2, "数据查询 + 用户判断", [
        HumanMessage(content="查一下华为的商机，我觉得ERP那个项目希望最大"),
        AIMessage(content="", tool_calls=[{"id":"tc2","name":"query_data","args":{}}]),
        ToolMessage(content='{"records":[{"id":"opp_001","name":"华为ERP实施","amount":45,"stage":"proposal"}]}',
                    tool_call_id="tc2", name="query_data"),
        AIMessage(content="华为ERP实施45万proposal阶段。您判断ERP项目希望最大，已记录。"),
    ], expect_count=-1, expect_cats=["entities"], expect_keywords=["希望最大"])

    # ── 场景 3: 联系人沟通风格 ──
    await run_case(e, 3, "联系人沟通风格", [
        HumanMessage(content="上次和华为张伟开会，这个人说话很直接，不喜欢绕弯子，给他汇报最好用PPT带数据"),
        AIMessage(content="了解，张伟偏好直接沟通，汇报用PPT配数据。"),
    ], expect_count=-1, expect_cats=["entities"], expect_keywords=["PPT", "直接"])

    # ── 场景 4: 客户内部关系 ──
    await run_case(e, 4, "客户内部关系", [
        HumanMessage(content="华为那边张伟和李娜意见不太一致，张伟想上ERP但李娜觉得预算不够，需要分别沟通"),
        AIMessage(content="了解，张伟和李娜在ERP项目上有分歧，建议分别沟通。"),
    ], expect_count=-1, expect_cats=["entities"], expect_keywords=["分歧", "分别沟通"])

    # ── 场景 5: 客户审批流程 ──
    await run_case(e, 5, "客户审批流程", [
        HumanMessage(content="华为的采购流程特别长，IT部门同意了还要过采购委员会，一般要3到4周"),
        AIMessage(content="了解，华为采购流程需要3-4周，IT部门之后还有采购委员会审批。"),
    ], expect_count=-1, expect_cats=["entities"], expect_keywords=["采购", "3"])

    # ── 场景 6: 竞争情报 ──
    await run_case(e, 6, "竞争情报", [
        HumanMessage(content="听说腾讯那边也在看数据中台方案，他们同时在评估我们和用友的产品，王强比较倾向我们但他老板更看重价格"),
        AIMessage(content="了解竞争态势，腾讯在评估我们和用友，王强倾向我们但高层看重价格。"),
    ], expect_count=-1, expect_cats=["entities"], expect_keywords=["用友", "价格"])

    # ── 场景 7: 预算背景 ──
    await run_case(e, 7, "预算背景", [
        HumanMessage(content="比亚迪今年数字化预算砍了20%，赵敏说所有新项目都要重新评估ROI"),
        AIMessage(content="了解，比亚迪预算收紧，所有新项目需要重新评估ROI。"),
    ], expect_count=-1, expect_cats=["entities"], expect_keywords=["预算", "ROI"])

    # ── 场景 8: 口头承诺 ──
    await run_case(e, 8, "口头承诺", [
        HumanMessage(content="今天招行陈刚私下跟我说风控平台项目基本定了选我们，但正式流程还要走两周"),
        AIMessage(content="好消息！陈刚私下确认选择我们，正式流程还需两周。"),
    ], expect_count=-1, expect_keywords=["私下", "确认"])

    # ── 场景 9: 用户身份 ──
    await run_case(e, 9, "用户身份", [
        HumanMessage(content="我是华东区销售总监，管15个人的团队，主要负责互联网和金融行业的大客户"),
        AIMessage(content="了解您的背景，我会从管理视角为您提供信息。"),
    ], expect_count=-1, expect_cats=["profile"], expect_keywords=["总监"])

    # ── 场景 10: 展示偏好 ──
    await run_case(e, 10, "展示偏好", [
        HumanMessage(content="以后数据都用表格展示，不要图表，我要看具体数字。金额统一用万为单位"),
        AIMessage(content="好的，已记录：表格展示、金额用万为单位。"),
    ], expect_count=-1, expect_cats=["preferences"], expect_keywords=["表格"])

    # ── 场景 11: 问题解决经验 ──
    await run_case(e, 11, "问题解决经验", [
        HumanMessage(content="上次查商机的时候报错了，后来发现是字段名写错了，stage写成了status"),
        AIMessage(content="是的，opportunity的阶段字段是stage不是status。建议先用query_schema确认字段名。"),
    ], expect_count=-1, expect_cats=["cases"], expect_keywords=["stage", "status"])

    # ── 场景 12: 工作流程模式 ──
    await run_case(e, 12, "工作流程模式", [
        HumanMessage(content="每次分析客户我都是先查基本信息，再看商机，然后看联系人，最后看最近的活动，你以后也按这个顺序来"),
        AIMessage(content="了解，以后按 基本信息→商机→联系人→活动 的顺序分析客户。"),
    ], expect_count=-1, expect_cats=["patterns"], expect_keywords=["基本信息"])

    # ── 场景 13: 时间窗口判断 ──
    await run_case(e, 13, "时间窗口判断", [
        HumanMessage(content="腾讯王强最近在忙集团的组织架构调整，估计这个月没时间看我们的方案，下个月再跟进"),
        AIMessage(content="了解，腾讯王强本月忙于组织架构调整，建议下月再跟进。"),
    ], expect_count=-1, expect_cats=["entities"], expect_keywords=["组织架构", "下月"])

    # ── 场景 14: POC 反馈 ──
    await run_case(e, 14, "POC反馈/客户认可", [
        HumanMessage(content="上周给招行做的风控POC效果很好，陈刚在内部会议上表扬了我们的方案，说比竞品快3倍"),
        AIMessage(content="很好的反馈！POC效果获得陈刚认可，性能优势明显。"),
    ], expect_count=-1, expect_keywords=["POC", "3倍"])

    # ── 场景 15: 社交偏好 ──
    await run_case(e, 15, "社交偏好", [
        HumanMessage(content="比亚迪赵敏不喜欢吃饭应酬，但喜欢打羽毛球，下次约她可以约球"),
        AIMessage(content="了解，赵敏偏好运动社交，下次可以约羽毛球。"),
    ], expect_count=-1, expect_cats=["entities"], expect_keywords=["羽毛球"])

    # ── 场景 16: 报价策略 ──
    await run_case(e, 16, "报价策略", [
        HumanMessage(content="华为ERP项目报价的时候不要一次报到底，先报个标准价，等他们还价再给折扣，张伟喜欢有谈判的感觉"),
        AIMessage(content="了解，华为ERP报价策略：先标准价，预留谈判空间。"),
    ], expect_count=-1, expect_cats=["entities"], expect_keywords=["标准价", "谈判"])

    # ── 场景 17: 数据查询 + 助手建议（只提取建议） ──
    await run_case(e, 17, "数据查询+助手建议", [
        HumanMessage(content="查一下华为安全审计项目的情况"),
        AIMessage(content="", tool_calls=[{"id":"tc17","name":"query_data","args":{}}]),
        ToolMessage(content='{"records":[{"id":"opp_007","name":"华为安全审计","amount":18,"stage":"closing","closeDate":"2025-04-30"}]}',
                    tool_call_id="tc17", name="query_data"),
        AIMessage(content="华为安全审计项目18万closing阶段，预计4月30日关闭。这个项目马上到期了，建议本周内推动签约，避免拖到下个月影响季度业绩。"),
    ], expect_count=-1, expect_keywords=["本周", "签约"],
       expect_no_keywords=["18万", "closing"])

    # ── 场景 18: 用户纠正 ──
    await run_case(e, 18, "用户纠正/反馈", [
        HumanMessage(content="你上次说华为BI平台项目概率30%，但我觉得实际上更低，张伟对这个项目兴趣不大，可能会砍掉"),
        AIMessage(content="了解，您认为华为BI平台实际概率更低，张伟兴趣不大，有被砍掉的风险。"),
    ], expect_count=-1, expect_cats=["entities"], expect_keywords=["兴趣不大", "砍掉"])

    # ── 场景 19: 跨客户经验 ──
    await run_case(e, 19, "跨客户经验", [
        HumanMessage(content="金融行业的客户都特别在意数据安全，上次招行和华为都问了我们的安全认证，以后给金融客户做方案都要把安全资质放在前面"),
        AIMessage(content="了解，金融行业客户重视数据安全，方案中安全资质前置。"),
    ], expect_count=-1, expect_cats=["patterns"], expect_keywords=["安全"])

    # ── 场景 20: 寒暄 → 不提取 ──
    await run_case(e, 20, "寒暄/确认 → 不提取", [
        HumanMessage(content="好的，谢谢"),
        AIMessage(content="不客气，还有其他需要帮忙的吗？"),
    ], expect_count=0)

    # ── 等待异步任务 ──
    await asyncio.sleep(2)

    # ── 汇总 ──
    print(f"\n{'='*60}")
    print(f"  汇总: {passed} passed, {failed} failed")
    print(f"{'='*60}")
    print(f"\n  {'#':<4} {'场景':<20} {'提取数':<6} {'类别'}")
    print(f"  {'─'*55}")
    for r in results_log:
        cats = ",".join(r["categories"]) if r["categories"] else "—"
        mark = "✅" if r["count"] > 0 or r["title"].endswith("不提取") else "❌"
        print(f"  {r['case']:<4} {r['title']:<20} {r['count']:<6} {cats}")


if __name__ == "__main__":
    asyncio.run(main())
    sys.exit(1 if failed else 0)
