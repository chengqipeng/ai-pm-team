"""20 个场景提取验证 + PG 同步验证

运行:
  cd product-specs/agent-system
  .venv/bin/python -B tests/test_l012_with_pg.py
"""
import asyncio
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("DOUBAO_API_KEY", "651621e7-e495-4728-93ef-ed380e9ddcd1")

from langchain_core.messages import HumanMessage, AIMessage, ToolMessage

passed = 0
failed = 0


def check(name, cond, detail=""):
    global passed, failed
    if cond:
        print(f"  ✅ {name}")
        passed += 1
    else:
        print(f"  ❌ {name}" + (f"  ({detail})" if detail else ""))
        failed += 1


def _llm():
    from langchain_openai import ChatOpenAI
    return ChatOpenAI(
        model="doubao-1-5-pro-32k-250115",
        api_key=os.environ["DOUBAO_API_KEY"],
        base_url="https://ark.cn-beijing.volces.com/api/v3/",
        max_tokens=2048,
    )


def _engine():
    from src.memory.viking_engine import VikingMemoryEngine
    return VikingMemoryEngine(
        vdb_url="http://10.60.2.17",
        vdb_key="bRG3NETg13tv5Fn68VTdkxaJXH9tMQzhKeT3unck",
        vdb_username="root",
        database_name="viking_l012_pg",
        collection_name="l012_pg_v1",
        llm=_llm(),
        use_pg=False,  # 运行态不用旧的 PG DAO，但 _sync_to_pg 会写新表
    )


# 所有场景统一用同一个 user_id，方便最后在前端查看
UID = "demo_sales_user"

CASES = [
    # (case_num, title, messages, expect_min_count, expect_cats, expect_keywords)
    (1, "纯数据查询→不提取", [
        HumanMessage(content="查一下华为的商机"),
        AIMessage(content="", tool_calls=[{"id": "tc1", "name": "query_data", "args": {}}]),
        ToolMessage(content='{"records":[{"id":"opp_001","name":"华为ERP实施","amount":45,"stage":"proposal"}]}', tool_call_id="tc1", name="query_data"),
        AIMessage(content="华为有1个商机：ERP实施45万，proposal阶段。"),
    ], 0, [], []),

    (2, "数据查询+用户判断", [
        HumanMessage(content="查一下华为的商机，我觉得ERP那个项目希望最大"),
        AIMessage(content="", tool_calls=[{"id": "tc2", "name": "query_data", "args": {}}]),
        ToolMessage(content='{"records":[{"id":"opp_001","name":"华为ERP实施","amount":45,"stage":"proposal"}]}', tool_call_id="tc2", name="query_data"),
        AIMessage(content="华为ERP实施45万proposal阶段。您判断ERP项目希望最大，已记录。"),
    ], 1, ["entities"], ["希望"]),

    (3, "联系人沟通风格", [
        HumanMessage(content="上次和华为张伟开会，这个人说话很直接，不喜欢绕弯子，给他汇报最好用PPT带数据"),
        AIMessage(content="了解，张伟偏好直接沟通，汇报用PPT配数据。我会记住这个沟通风格。"),
    ], 1, [], ["PPT"]),

    (4, "客户内部关系", [
        HumanMessage(content="华为那边张伟和李娜意见不太一致，张伟想上ERP但李娜觉得预算不够，需要分别沟通"),
        AIMessage(content="了解，张伟和李娜在ERP项目上有分歧。张伟支持上ERP，李娜担心预算。建议分别沟通，各个击破。"),
    ], 1, ["entities"], ["分歧"]),

    (5, "客户审批流程", [
        HumanMessage(content="华为的采购流程特别长，IT部门同意了还要过采购委员会，一般要3到4周"),
        AIMessage(content="了解，华为采购流程需要3-4周，IT部门之后还有采购委员会审批。签约前需要预留足够时间。"),
    ], 1, ["entities"], ["采购"]),

    (6, "竞争情报", [
        HumanMessage(content="听说腾讯那边也在看数据中台方案，他们同时在评估我们和用友的产品，王强比较倾向我们但他老板更看重价格"),
        AIMessage(content="了解竞争态势。腾讯在评估我们和用友，王强倾向我们但高层看重价格。需要在价格策略上做文章。"),
    ], 1, ["entities"], ["价格"]),

    (7, "预算背景", [
        HumanMessage(content="比亚迪今年数字化预算砍了20%，赵敏说所有新项目都要重新评估ROI"),
        AIMessage(content="了解，比亚迪预算收紧20%，所有新项目需要重新评估ROI。MES项目推进时需要重点准备ROI分析材料。"),
    ], 1, ["entities"], ["预算"]),

    (8, "口头承诺", [
        HumanMessage(content="今天招行陈刚私下跟我说风控平台项目基本定了选我们，但正式流程还要走两周"),
        AIMessage(content="好消息！陈刚私下确认选择我们，正式流程还需两周。在正式确认前建议保持低调，继续做好服务。"),
    ], 1, [], ["确认"]),

    (9, "用户身份", [
        HumanMessage(content="我是华东区销售总监，管15个人的团队，主要负责互联网和金融行业的大客户"),
        AIMessage(content="了解您的背景信息。您是华东区销售总监，管理15人团队，负责互联网和金融行业大客户。我会根据您的角色和职责来调整信息展示的维度。"),
    ], 1, ["profile"], ["总监"]),

    (10, "展示偏好", [
        HumanMessage(content="以后数据都用表格展示，不要图表，我要看具体数字。金额统一用万为单位"),
        AIMessage(content="好的，已记录您的偏好设置：数据用表格展示，不用图表，金额统一用万为单位。以后会严格按照这些偏好为您服务。"),
    ], 1, ["preferences"], ["表格"]),

    (11, "问题解决经验", [
        HumanMessage(content="上次查商机的时候报错了，后来发现是字段名写错了，stage写成了status"),
        AIMessage(content="是的，opportunity的阶段字段正确名称是stage而不是status。建议在查询前先用query_schema确认字段名，可以避免这类错误。"),
    ], 1, ["cases"], ["stage"]),

    (12, "工作流程模式", [
        HumanMessage(content="每次分析客户我都是先查基本信息，再看商机，然后看联系人，最后看最近的活动，你以后也按这个顺序来"),
        AIMessage(content="了解，以后按 基本信息→商机→联系人→活动 的顺序分析客户。这个流程很合理，先了解全貌再看细节。"),
    ], 1, ["patterns"], ["基本信息"]),

    (13, "时间窗口判断", [
        HumanMessage(content="腾讯王强最近在忙集团的组织架构调整，估计这个月没时间看我们的方案，下个月再跟进"),
        AIMessage(content="了解，腾讯王强本月忙于组织架构调整，没时间评估方案。建议下月初再联系跟进，届时组织架构调整应该已经完成。"),
    ], 1, ["entities"], ["组织架构"]),

    (14, "POC反馈", [
        HumanMessage(content="上周给招行做的风控POC效果很好，陈刚在内部会议上表扬了我们的方案，说比竞品快3倍"),
        AIMessage(content="很好的反馈！POC效果获得陈刚认可，性能比竞品快3倍是重要的竞争优势。建议把这个数据写入后续的商务方案中。"),
    ], 1, [], ["POC"]),

    (15, "社交偏好", [
        HumanMessage(content="比亚迪赵敏不喜欢吃饭应酬，但喜欢打羽毛球，下次约她可以约球，比约饭效果好"),
        AIMessage(content="了解赵敏的社交偏好。她不喜欢吃饭应酬但喜欢打羽毛球，下次约她建议约球而不是约饭，更容易拉近关系。"),
    ], 1, [], ["羽毛球"]),

    (16, "报价策略", [
        HumanMessage(content="华为ERP项目报价的时候不要一次报到底，先报个标准价，等他们还价再给折扣，张伟喜欢有谈判的感觉"),
        AIMessage(content="了解，华为ERP报价策略：先标准价，预留谈判空间。张伟喜欢有谈判的感觉，直接给底价反而会让他觉得还有空间。"),
    ], 1, ["entities"], ["标准价"]),

    (17, "数据查询+助手建议", [
        HumanMessage(content="查一下华为安全审计项目的情况"),
        AIMessage(content="", tool_calls=[{"id": "tc17", "name": "query_data", "args": {}}]),
        ToolMessage(content='{"records":[{"id":"opp_007","name":"华为安全审计","amount":18,"stage":"closing","closeDate":"2025-04-30"}]}', tool_call_id="tc17", name="query_data"),
        AIMessage(content="华为安全审计项目18万closing阶段，预计4月30日关闭。这个项目马上到期了，建议本周内推动签约，避免拖到下个月影响季度业绩。"),
    ], 1, [], ["本周"]),

    (18, "用户纠正", [
        HumanMessage(content="你上次说华为BI平台项目概率30%，但我觉得实际上更低，张伟对这个项目兴趣不大，可能会砍掉"),
        AIMessage(content="了解，您认为华为BI平台实际概率更低。张伟对这个项目兴趣不大，有被砍掉的风险。我会更新对这个项目的判断。"),
    ], 1, ["entities"], ["兴趣不大"]),

    (19, "跨客户经验", [
        HumanMessage(content="金融行业的客户都特别在意数据安全，上次招行和华为都问了我们的安全认证，以后给金融客户做方案都要把安全资质放在前面"),
        AIMessage(content="了解，金融行业客户重视数据安全。招行和华为都问过安全认证，以后给金融客户做方案时安全资质前置。"),
    ], 1, ["patterns"], ["安全"]),

    (20, "寒暄→不提取", [
        HumanMessage(content="好的，谢谢"),
        AIMessage(content="不客气，还有其他需要帮忙的吗？"),
    ], 0, [], []),
]


async def main():
    e = _engine()
    print("=" * 60)
    print("  20 场景提取 + PG 同步验证")
    print("=" * 60)

    for case_num, title, messages, expect_min, expect_cats, expect_kws in CASES:
        print(f"\n{'─'*60}")
        print(f"  场景 {case_num}: {title}")
        print(f"{'─'*60}")

        r = await e.extract_and_update(messages, thread_id=f"t-{case_num}", user_id=UID)

        if not r.items:
            print(f"    → 提取 0 条")
        else:
            print(f"    → 提取 {len(r.items)} 条:")
            for item in r.items:
                cat = item.metadata.get("category", "?")
                overview = item.metadata.get("overview", "")
                full = item.metadata.get("full_content", "")
                print(f"      [{cat}] L0: {item.content}")
                if overview:
                    print(f"             L1: {overview[:80]}...")
                if full and full != item.content:
                    print(f"             L2: {full[:100]}...")

        # 验证数量
        if expect_min == 0:
            check(f"{case_num}. 不提取", len(r.items) == 0, f"实际{len(r.items)}条")
        else:
            check(f"{case_num}. 提取>={expect_min}条", len(r.items) >= expect_min, f"实际{len(r.items)}条")

        # 验证类别
        if expect_cats and r.items:
            actual_cats = {i.metadata.get("category") for i in r.items}
            for ec in expect_cats:
                check(f"{case_num}. 类别含{ec}", ec in actual_cats, f"实际{actual_cats}")

        # 验证关键词
        if expect_kws and r.items:
            all_text = " ".join(i.content + " " + i.metadata.get("full_content", "") for i in r.items)
            for kw in expect_kws:
                check(f"{case_num}. 含'{kw}'", kw in all_text)

        await asyncio.sleep(0.3)

    # 等待所有异步 PG 写入完成
    print(f"\n{'─'*60}")
    print("  等待 PG 同步...")
    print(f"{'─'*60}")
    await asyncio.sleep(5)

    # 验证 PG 数据
    from src.store.pg_pool import get_conn
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT category, COUNT(*) FROM ai_agent_memory
            WHERE user_id = %s AND delete_flg = 0
            GROUP BY category ORDER BY category
        """, (UID,))
        pg_stats = cur.fetchall()

        cur.execute("""
            SELECT id, category, abstract, merge_key, parent_entity, source_type, thread_id
            FROM ai_agent_memory
            WHERE user_id = %s AND delete_flg = 0
            ORDER BY id
        """, (UID,))
        pg_rows = cur.fetchall()

    print(f"\n{'='*60}")
    print(f"  PG 同步结果: {UID}")
    print(f"{'='*60}")
    print(f"\n  按类别统计:")
    total_pg = 0
    for cat, cnt in pg_stats:
        print(f"    {cat}: {cnt} 条")
        total_pg += cnt
    print(f"    ────────")
    print(f"    总计: {total_pg} 条")

    print(f"\n  详细列表:")
    for row_id, cat, abstract, mk, pe, st, tid in pg_rows:
        print(f"    [{cat}] {abstract[:55]}")
        meta_parts = []
        if mk:
            meta_parts.append(f"key={mk}")
        if pe:
            meta_parts.append(f"parent={pe}")
        meta_parts.append(f"thread={tid}")
        print(f"           {', '.join(meta_parts)}")

    check("PG同步: 有数据", total_pg > 0, f"PG中{total_pg}条")
    check("PG同步: 多类别", len(pg_stats) >= 3, f"PG中{len(pg_stats)}个类别")

    print(f"\n{'='*60}")
    print(f"  汇总: {passed} passed, {failed} failed")
    print(f"  PG 中共 {total_pg} 条记忆，可在 /memory 页面查看")
    print(f"{'='*60}")


if __name__ == "__main__":
    asyncio.run(main())
    sys.exit(1 if failed else 0)
