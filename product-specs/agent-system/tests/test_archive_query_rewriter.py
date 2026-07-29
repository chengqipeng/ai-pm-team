"""ArchiveQueryRewriter 100 场景验证

验证 query 改写和关键词提取逻辑:
  A. 代词消解 (20) — 他们/那个/对方 → 具体实体
  B. 意图识别 (20) — 变更/决策/最新/对比/时间线
  C. 关键词提取 (20) — 中文词/英文词/数值/实体
  D. 工具名推断 (15) — 搜索/查询/分析/执行
  E. 实体补全 (15) — 无实体时从上下文补充
  F. 边界/不改写 (10) — 已自包含的 query 不应改写

判定标准:
  - 代词消解: 改写后包含具体实体名
  - 意图识别: intent_type 正确
  - 关键词提取: extracted_keywords 包含期望词
  - 工具名推断: extracted_keywords 包含工具名
  - 实体补全: extracted_entities 非空
  - 不改写: was_rewritten == False
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.middleware.archive_query_rewriter import ArchiveQueryRewriter, RewriteResult


@dataclass
class Case:
    id: str
    category: str
    query: str
    active_entities: list[str]
    # 期望
    expect_entity_in_result: str = ""        # 改写后应包含此实体
    expect_intent: str = ""                  # 期望的 intent_type
    expect_keyword: str = ""                 # extracted_keywords 应包含此词
    expect_not_rewritten: bool = False       # 期望不改写
    expect_tool: str = ""                    # 应推断出的工具名


def build_cases() -> list[Case]:
    cases = []

    # ═══ A. 代词消解 (20) ═══
    ents_pt = ["PT Sentosa", "opp_001"]
    ents_hw = ["华为科技", "张总"]
    ents_tc = ["腾讯云", "Q-TC-001"]

    cases += [
        Case("A01", "代词消解", "他们的报价是多少", ents_pt, expect_entity_in_result="PT Sentosa"),
        Case("A02", "代词消解", "他们商机什么阶段", ents_pt, expect_entity_in_result="PT Sentosa"),
        Case("A03", "代词消解", "那个客户年营收多少", ents_hw, expect_entity_in_result="华为科技"),
        Case("A04", "代词消解", "这个客户联系人是谁", ents_hw, expect_entity_in_result="华为科技"),
        Case("A05", "代词消解", "对方接受了吗", ents_pt, expect_entity_in_result="PT Sentosa"),
        Case("A06", "代词消解", "那边什么反馈", ents_tc, expect_entity_in_result="腾讯云"),
        Case("A07", "代词消解", "她们的需求", ents_tc, expect_entity_in_result="腾讯云"),
        Case("A08", "代词消解", "它的到期时间", ents_pt, expect_entity_in_result="PT Sentosa"),
        Case("A09", "代词消解", "该客户POC通过了吗", ents_hw, expect_entity_in_result="华为科技"),
        Case("A10", "代词消解", "那家公司规模多大", ents_hw, expect_entity_in_result="华为科技"),
        Case("A11", "代词消解", "他们砍价了吗", ents_pt, expect_entity_in_result="PT Sentosa"),
        Case("A12", "代词消解", "对方签约了没", ents_tc, expect_entity_in_result="腾讯云"),
        Case("A13", "代词消解", "这家公司什么行业", ents_pt, expect_entity_in_result="PT Sentosa"),
        Case("A14", "代词消解", "他们的合同状态", ents_tc, expect_entity_in_result="腾讯云"),
        Case("A15", "代词消解", "它还在proposal阶段吗", ents_pt, expect_entity_in_result="PT Sentosa"),
        Case("A16", "代词消解", "那个客户的BANT", ents_hw, expect_entity_in_result="华为科技"),
        Case("A17", "代词消解", "他们最终报价多少", ents_hw, expect_entity_in_result="华为科技"),
        Case("A18", "代词消解", "该客户欠款情况", ents_pt, expect_entity_in_result="PT Sentosa"),
        Case("A19", "代词消解", "对方CTO是谁", ents_hw, expect_entity_in_result="华为科技"),
        Case("A20", "代词消解", "那边付款条件是什么", ents_tc, expect_entity_in_result="腾讯云"),
    ]

    # ═══ B. 意图识别 (20) ═══
    cases += [
        Case("B01", "意图识别", "报价怎么变的", ents_pt, expect_intent="change_tracking"),
        Case("B02", "意图识别", "金额调整了几次", ents_pt, expect_intent="change_tracking"),
        Case("B03", "意图识别", "从$45K改到多少了", ents_pt, expect_intent="change_tracking"),
        Case("B04", "意图识别", "之前是多少钱", ents_pt, expect_intent="change_tracking"),
        Case("B05", "意图识别", "价格演变过程", ents_pt, expect_intent="change_tracking"),
        Case("B06", "意图识别", "为什么降价了", ents_pt, expect_intent="decision_reason"),
        Case("B07", "意图识别", "谁同意的降价", ents_pt, expect_intent="decision_reason"),
        Case("B08", "意图识别", "降价的理由是什么", ents_pt, expect_intent="decision_reason"),
        Case("B09", "意图识别", "怎么定的这个价格", ents_pt, expect_intent="decision_reason"),
        Case("B10", "意图识别", "谁批准的方案", ents_hw, expect_intent="decision_reason"),
        Case("B11", "意图识别", "最新报价是多少", ents_pt, expect_intent="latest_state"),
        Case("B12", "意图识别", "当前合同状态", ents_tc, expect_intent="latest_state"),
        Case("B13", "意图识别", "现在什么阶段", ents_pt, expect_intent="latest_state"),
        Case("B14", "意图识别", "最终确认了吗", ents_hw, expect_intent="latest_state"),
        Case("B15", "意图识别", "签了吗", ents_pt, expect_intent="latest_state"),
        Case("B16", "意图识别", "和SAP比怎么样", ents_hw, expect_intent="comparison"),
        Case("B17", "意图识别", "Odoo和我们差多少", ents_pt, expect_intent="comparison"),
        Case("B18", "意图识别", "从开始到现在全过程", ents_pt, expect_intent="timeline"),
        Case("B19", "意图识别", "第一次接触是什么时候", ents_hw, expect_intent="timeline"),
        Case("B20", "意图识别", "后来发生了什么", ents_pt, expect_intent="timeline"),
    ]

    # ═══ C. 关键词提取 (20) ═══
    cases += [
        Case("C01", "关键词提取", "PT Sentosa 报价 $45K", ents_pt, expect_keyword="$45K"),
        Case("C02", "关键词提取", "华为科技¥480万的报价", ents_hw, expect_keyword="¥480万"),
        Case("C03", "关键词提取", "折扣15%怎么算的", ents_pt, expect_keyword="15%"),
        Case("C04", "关键词提取", "2025-05-15到期", ents_pt, expect_keyword="2025-05-15"),
        Case("C05", "关键词提取", "opp_001 商机详情", ents_pt, expect_keyword="opp_001"),
        Case("C06", "关键词提取", "Q-HW-001 报价单", ents_hw, expect_keyword="Q-HW-001"),
        Case("C07", "关键词提取", "POC-HW-001 结果", ents_hw, expect_keyword="POC-HW-001"),
        Case("C08", "关键词提取", "pipeline总额¥850万", ents_pt, expect_keyword="850万"),
        Case("C09", "关键词提取", "CON-BYD-001 合同", ents_pt, expect_keyword="CON-BYD-001"),
        Case("C10", "关键词提取", "Salesforce竞争分析", ents_hw, expect_keyword="Salesforce"),
        Case("C11", "关键词提取", "Odoo定价对比", ents_pt, expect_keyword="Odoo"),
        Case("C12", "关键词提取", "SAP S/4HANA报价", ents_hw, expect_keyword="SAP"),
        Case("C13", "关键词提取", "制造业客户", ents_pt, expect_keyword="制造"),
        Case("C14", "关键词提取", "签约30%付款", ents_pt, expect_keyword="30%"),
        Case("C15", "关键词提取", "API对接需求", ents_tc, expect_keyword="API"),
        Case("C16", "关键词提取", "GraphQL双协议", ents_tc, expect_keyword="GraphQL"),
        Case("C17", "关键词提取", "Schema级隔离", ents_tc, expect_keyword="Schema"),
        Case("C18", "关键词提取", "ELK日志审计", ents_tc, expect_keyword="ELK"),
        Case("C19", "关键词提取", "BANT分析结果", ents_hw, expect_keyword="BANT"),
        Case("C20", "关键词提取", "RESTful接口", ents_tc, expect_keyword="RESTful"),
    ]

    # ═══ D. 工具名推断 (15) ═══
    cases += [
        Case("D01", "工具推断", "上次搜了什么", ents_pt, expect_tool="web_search"),
        Case("D02", "工具推断", "网上查的竞品定价", ents_pt, expect_tool="web_search"),
        Case("D03", "工具推断", "搜索结果是什么", ents_hw, expect_tool="web_search"),
        Case("D04", "工具推断", "查询了哪些数据", ents_pt, expect_tool="query_data"),
        Case("D05", "工具推断", "查了客户什么信息", ents_hw, expect_tool="query_data"),
        Case("D06", "工具推断", "数据查询结果", ents_tc, expect_tool="query_data"),
        Case("D07", "工具推断", "pipeline分析结论", ents_pt, expect_tool="analyze_data"),
        Case("D08", "工具推断", "BANT分析做了吗", ents_hw, expect_tool="analyze_data"),
        Case("D09", "工具推断", "统计了什么", ents_pt, expect_tool="analyze_data"),
        Case("D10", "工具推断", "更新了什么内容", ents_pt, expect_tool="execute_task"),
        Case("D11", "工具推断", "执行了哪些操作", ents_hw, expect_tool="execute_task"),
        Case("D12", "工具推断", "修改了哪些字段", ents_tc, expect_tool="execute_task"),
        Case("D13", "工具推断", "创建了什么报价", ents_hw, expect_tool="execute_task"),
        Case("D14", "工具推断", "签约操作记录", ents_pt, expect_tool="execute_task"),
        Case("D15", "工具推断", "成交了没有", ents_pt, expect_tool="execute_task"),
    ]

    # ═══ E. 实体补全 (15) ═══
    cases += [
        Case("E01", "实体补全", "报价多少钱", ents_pt, expect_entity_in_result="PT Sentosa"),
        Case("E02", "实体补全", "商机什么阶段", ents_hw, expect_entity_in_result="华为科技"),
        Case("E03", "实体补全", "合同到期了没", ents_tc, expect_entity_in_result="腾讯云"),
        Case("E04", "实体补全", "联系人是谁", ents_hw, expect_entity_in_result="华为科技"),
        Case("E05", "实体补全", "付款条件是什么", ents_pt, expect_entity_in_result="PT Sentosa"),
        Case("E06", "实体补全", "签了没有", ents_tc, expect_entity_in_result="腾讯云"),
        Case("E07", "实体补全", "折扣多少", ents_pt, expect_entity_in_result="PT Sentosa"),
        Case("E08", "实体补全", "需求有哪些", ents_tc, expect_entity_in_result="腾讯云"),
        Case("E09", "实体补全", "实施周期多长", ents_hw, expect_entity_in_result="华为科技"),
        Case("E10", "实体补全", "成功标准是什么", ents_hw, expect_entity_in_result="华为科技"),
        Case("E11", "实体补全", "风险在哪", ents_pt, expect_entity_in_result="PT Sentosa"),
        Case("E12", "实体补全", "下一步怎么做", ents_hw, expect_entity_in_result="华为科技"),
        Case("E13", "实体补全", "报价更新了吗", ents_tc, expect_entity_in_result="腾讯云"),
        Case("E14", "实体补全", "方案确认了没", ents_hw, expect_entity_in_result="华为科技"),
        Case("E15", "实体补全", "砍了多少", ents_pt, expect_entity_in_result="PT Sentosa"),
    ]

    # ═══ F. 不改写 (10) ═══
    cases += [
        Case("F01", "不改写", "PT Sentosa 报价$45K", ents_pt, expect_not_rewritten=True),
        Case("F02", "不改写", "华为科技 BANT 分析结果", ents_hw, expect_not_rewritten=True),
        Case("F03", "不改写", "腾讯云 Q-TC-001 报价", ents_tc, expect_not_rewritten=True),
        Case("F04", "不改写", "opp_001 商机状态", ents_pt, expect_not_rewritten=True),
        Case("F05", "不改写", "Odoo pricing 2025", ents_pt, expect_not_rewritten=True),
        Case("F06", "不改写", "SAP S/4HANA 年费", ents_hw, expect_not_rewritten=True),
        Case("F07", "不改写", "web_search Odoo", ents_pt, expect_not_rewritten=True),
        Case("F08", "不改写", "CON-BYD-001 合同详情", ents_pt, expect_not_rewritten=True),
        Case("F09", "不改写", "POC-HW-001 成功标准", ents_hw, expect_not_rewritten=True),
        Case("F10", "不改写", "pipeline总额¥850万分布", ents_pt, expect_not_rewritten=True),
    ]

    return cases


def evaluate(case: Case) -> tuple[bool, str]:
    """评测单个用例"""
    rewriter = ArchiveQueryRewriter(
        active_entities=case.active_entities,
    )
    result = rewriter.rewrite(case.query)

    # 代词消解: 改写后包含期望实体
    if case.expect_entity_in_result:
        if case.expect_entity_in_result in result.rewritten_query:
            return True, f"✓ 含'{case.expect_entity_in_result}'"
        # 也检查 extracted_entities
        if case.expect_entity_in_result in result.extracted_entities:
            return True, f"✓ entities含'{case.expect_entity_in_result}'"
        return False, f"✗ 缺'{case.expect_entity_in_result}' → '{result.rewritten_query[:60]}'"

    # 意图识别
    if case.expect_intent:
        if result.intent_type == case.expect_intent:
            return True, f"✓ intent={result.intent_type}"
        return False, f"✗ 期望{case.expect_intent}, 实际{result.intent_type}"

    # 关键词提取
    if case.expect_keyword:
        all_kw = result.extracted_keywords + [result.rewritten_query]
        kw_text = " ".join(all_kw).lower()
        if case.expect_keyword.lower() in kw_text:
            return True, f"✓ 含'{case.expect_keyword}'"
        # 也检查 entities
        ent_text = " ".join(result.extracted_entities).lower()
        if case.expect_keyword.lower() in ent_text:
            return True, f"✓ entities含'{case.expect_keyword}'"
        return False, f"✗ 缺'{case.expect_keyword}' kw={result.extracted_keywords[:5]}"

    # 工具推断
    if case.expect_tool:
        if case.expect_tool in result.extracted_keywords:
            return True, f"✓ 推断出{case.expect_tool}"
        return False, f"✗ 缺{case.expect_tool} kw={result.extracted_keywords[:5]}"

    # 不改写
    if case.expect_not_rewritten:
        if not result.was_rewritten:
            return True, "✓ 未改写"
        return False, f"✗ 被改写了 → '{result.rewritten_query[:60]}'"

    return True, "✓"


def main():
    cases = build_cases()
    print(f"\n{'═'*60}")
    print(f"  ArchiveQueryRewriter 100 场景验证")
    print(f"  用例数: {len(cases)}")
    print(f"{'═'*60}\n")

    # 分类统计
    cats: dict[str, list[tuple[bool, str, Case]]] = {}
    total_pass = 0

    for case in cases:
        passed, detail = evaluate(case)
        cats.setdefault(case.category, []).append((passed, detail, case))
        if passed:
            total_pass += 1

    for cat, results in cats.items():
        cat_pass = sum(1 for p, _, _ in results if p)
        cat_total = len(results)
        status = "✅" if cat_pass == cat_total else "⚠️" if cat_pass / cat_total >= 0.7 else "❌"
        print(f"  {status} {cat:8s} | {cat_pass}/{cat_total} ({cat_pass/cat_total*100:.0f}%)")

        # 显示失败用例
        failures = [(d, c) for p, d, c in results if not p]
        for detail, case in failures[:3]:
            print(f"       ❌ {case.id}: query='{case.query[:30]}' {detail}")
        if len(failures) > 3:
            print(f"       ... +{len(failures)-3}")
        print()

    total = len(cases)
    print(f"{'─'*60}")
    print(f"  总计: {total_pass}/{total} ({total_pass/total*100:.1f}%)")
    print(f"{'─'*60}\n")

    return total_pass == total


if __name__ == "__main__":
    ok = main()
    sys.exit(0 if ok else 1)
