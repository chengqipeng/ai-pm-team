"""链路评测体系验证脚本

验证内容：
1. 数据结构完整性（评测集、用例、运行记录）
2. 运行记录数学一致性（passed + failed == total）
3. 链路 Span 时序合法性（递增、非负）
4. 失败归因与实际链路节点匹配
5. 断言数据与用例状态逻辑一致
6. API 路由注册验证
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from src.api.chain_eval_api import _suites, _cases, _runs, _run_details


def test_data_structure():
    """1. 数据结构完整性"""
    print("=== 1. 数据结构验证 ===")
    print(f"评测集数量: {len(_suites)}")
    assert len(_suites) >= 2, f"期望至少2个评测集, 实际{len(_suites)}"

    for sid, suite in _suites.items():
        assert "id" in suite
        assert "name" in suite
        assert "created_at" in suite
        cases = _cases.get(sid, [])
        print(f"  [{sid}] {suite['name']} -- {len(cases)} 个用例")
        for c in cases:
            assert "id" in c, f"用例缺少 id"
            assert "input" in c, f"用例 {c['id']} 缺少 input"
            assert "assertions" in c, f"用例 {c['id']} 缺少 assertions"
            assert "name" in c, f"用例 {c['id']} 缺少 name"
    print("  ✅ 所有评测集/用例结构完整")


def test_run_records():
    """2. 运行记录数学一致性"""
    print(f"\n=== 2. 运行记录验证 ===")
    print(f"运行记录数: {len(_runs)}")
    assert len(_runs) >= 2, f"期望至少2条运行记录"

    for r in _runs:
        assert r["passed"] + r["failed"] == r["total"], \
            f"通过+失败 != 总数: {r['run_id']} ({r['passed']}+{r['failed']}!={r['total']})"
        assert 0 <= r["pass_rate"] <= 1, f"通过率越界: {r['run_id']}"
        expected_rate = r["passed"] / max(r["total"], 1)
        assert abs(r["pass_rate"] - expected_rate) < 0.001, \
            f"通过率计算不一致: {r['run_id']} ({r['pass_rate']} vs {expected_rate})"
        assert r["duration_ms"] > 0, f"耗时不能为0: {r['run_id']}"
        assert r["created_at"] > 0, f"创建时间无效: {r['run_id']}"
        print(f"  [{r['run_id']}] {r['suite_name']} -- {r['passed']}/{r['total']} ({r['pass_rate']*100:.1f}%)")
    print("  ✅ 运行记录数据一致")


def test_run5_detail():
    """3. Run#5 链路回放完整性"""
    print(f"\n=== 3. Run#5 链路回放验证 ===")
    detail = _run_details.get("run_005")
    assert detail is not None, "run_005 详情缺失"
    cases_results = detail["cases"]
    print(f"用例结果数: {len(cases_results)}")
    assert len(cases_results) == 6, f"期望6个用例结果, 实际{len(cases_results)}"

    passed_count = sum(1 for c in cases_results if c["status"] == "passed")
    failed_count = sum(1 for c in cases_results if c["status"] == "failed")
    print(f"通过: {passed_count}, 失败: {failed_count}")
    assert passed_count == 5, f"期望5通过, 实际{passed_count}"
    assert failed_count == 1, f"期望1失败, 实际{failed_count}"
    print("  ✅ 通过/失败计数正确")


def test_span_timeline():
    """4. 链路 Span 时序验证"""
    print(f"\n=== 4. 链路 Span 时序验证 ===")
    detail = _run_details["run_005"]
    cases_results = detail["cases"]

    for c in cases_results:
        chain = c.get("chain", [])
        if not chain:
            continue

        for i, span in enumerate(chain):
            # 必需字段
            assert "id" in span, f"Span 缺少 id: case={c['case_id']}, index={i}"
            assert "type" in span, f"Span 缺少 type: {span['id']}"
            assert "status" in span, f"Span 缺少 status: {span['id']}"
            assert "start_ms" in span, f"Span 缺少 start_ms: {span['id']}"
            assert "duration_ms" in span, f"Span 缺少 duration_ms: {span['id']}"
            # 非负
            assert span["start_ms"] >= 0, f"start_ms 为负: {span['id']}"
            assert span["duration_ms"] >= 0, f"duration_ms 为负: {span['id']}"
            # 时序递增
            if i > 0:
                assert span["start_ms"] >= chain[i-1]["start_ms"], \
                    f"时序回退: {c['case_id']} span[{i}] start={span['start_ms']} < prev start={chain[i-1]['start_ms']}"

        total_chain_ms = max(s["start_ms"] + s["duration_ms"] for s in chain)
        status_emoji = "✅" if c["status"] == "passed" else "❌"
        print(f"  [{c['case_id']}] {len(chain)} spans, "
              f"链路 {total_chain_ms}ms, case {c['latency_ms']}ms -- {status_emoji}")
    print("  ✅ 所有 Span 时序合法、递增、非负")


def test_failure_attribution():
    """5. 失败归因验证"""
    print(f"\n=== 5. 失败归因验证 ===")
    detail = _run_details["run_005"]
    failed_case = next(c for c in detail["cases"] if c["status"] == "failed")

    # 归因字段完整
    assert "failure_attribution" in failed_case, "失败用例缺少 failure_attribution"
    fa = failed_case["failure_attribution"]
    assert "type" in fa, "归因缺少 type"
    assert "node" in fa, "归因缺少 node"
    assert "reason" in fa, "归因缺少 reason"
    assert "suggestion" in fa, "归因缺少 suggestion"

    print(f"  失败用例: {failed_case['case_id']}")
    print(f"  归因类型: {fa['type']}")
    print(f"  问题节点: {fa['node']}")
    print(f"  原因: {fa['reason']}")
    print(f"  建议: {fa['suggestion']}")

    # 验证归因节点在链路中实际存在
    chain = failed_case["chain"]
    failed_spans = [s for s in chain if s["status"] == "failed"]
    assert len(failed_spans) >= 1, "失败用例中无 failed span"

    # 归因指向 llm_call_2（round=2 的 llm_call）
    llm_call_2 = next(
        (s for s in chain if s.get("type") == "llm_call" and s.get("round") == 2),
        None
    )
    assert llm_call_2 is not None, "归因指向的 llm_call round=2 不存在于链路中"
    assert llm_call_2["status"] == "failed", f"llm_call_2 应为 failed, 实际{llm_call_2['status']}"

    # 验证失败原因包含关键信息
    assert "shipped" in fa["reason"] or "发货" in fa["reason"], \
        f"归因原因未提及核心逻辑 (shipped): {fa['reason']}"

    print("  ✅ 归因节点存在且逻辑匹配")


def test_assertions_consistency():
    """6. 断言与用例状态一致性"""
    print(f"\n=== 6. 断言数据验证 ===")
    detail = _run_details["run_005"]

    for c in detail["cases"]:
        assertions = c.get("assertions", [])
        assert len(assertions) > 0, f"用例 {c['case_id']} 无断言"

        for a in assertions:
            assert "type" in a, f"断言缺 type: {c['case_id']}"
            assert "passed" in a, f"断言缺 passed: {c['case_id']}"
            assert "detail" in a, f"断言缺 detail: {c['case_id']}"
            assert isinstance(a["passed"], bool), f"passed 非 bool: {c['case_id']}"

        all_passed = all(a["passed"] for a in assertions)
        if c["status"] == "passed":
            assert all_passed, \
                f"用例 {c['case_id']} 状态=passed 但有断言失败: {[a for a in assertions if not a['passed']]}"
        if c["status"] == "failed":
            assert not all_passed, \
                f"用例 {c['case_id']} 状态=failed 但断言全通过"

        status_str = "PASS" if c["status"] == "passed" else "FAIL"
        print(f"  [{c['case_id']}] {len(assertions)} 断言 -- 状态一致 ✅")

    print("  ✅ 所有断言数据逻辑正确")


def test_expandable_data():
    """7. 可展开详情数据验证"""
    print(f"\n=== 7. 可展开详情验证 ===")
    detail = _run_details["run_005"]
    expandable_count = 0

    for c in detail["cases"]:
        chain = c.get("chain", [])
        for span in chain:
            if "expandable" in span:
                expandable_count += 1
                exp = span["expandable"]
                # LLM 节点必须有 input_messages
                if span["type"] == "llm_call":
                    assert "input_messages" in exp, \
                        f"LLM span 缺少 input_messages: {c['case_id']}/{span['id']}"
                    msgs = exp["input_messages"]
                    assert len(msgs) > 0, f"input_messages 为空: {c['case_id']}/{span['id']}"
                    for msg in msgs:
                        assert "role" in msg, f"message 缺少 role"
                        assert "content" in msg, f"message 缺少 content"
                    assert "output_raw" in exp, \
                        f"LLM span 缺少 output_raw: {c['case_id']}/{span['id']}"

    print(f"  含 expandable 的 Span: {expandable_count}")
    assert expandable_count >= 4, f"期望至少4个可展开节点, 实际{expandable_count}"
    print("  ✅ 可展开详情数据结构正确")


def test_span_type_metadata():
    """8. Span 类型与元数据匹配验证"""
    print(f"\n=== 8. Span 类型元数据验证 ===")
    detail = _run_details["run_005"]
    type_counts = {}

    for c in detail["cases"]:
        chain = c.get("chain", [])
        for span in chain:
            t = span["type"]
            type_counts[t] = type_counts.get(t, 0) + 1
            meta = span.get("metadata", {})

            # 类型特定验证
            if t == "content_review":
                assert "passed" in meta, f"content_review 缺少 passed 元数据"
            elif t == "memory_retrieve":
                assert "hits" in meta, f"memory_retrieve 缺少 hits 元数据"
            elif t == "llm_call":
                assert "decision" in meta, f"llm_call 缺少 decision 元数据"
                assert meta["decision"] in ("tool_call", "final_response"), \
                    f"llm_call decision 值非法: {meta['decision']}"
            elif t == "tool_call":
                assert "is_mocked" in meta, f"tool_call 缺少 is_mocked 元数据"
            elif t == "llm_judge":
                assert "score" in meta, f"llm_judge 缺少 score 元数据"

    print("  Span 类型分布:")
    for t, cnt in sorted(type_counts.items()):
        print(f"    {t}: {cnt}")
    print("  ✅ 所有 Span 类型元数据匹配")


def test_case_id_uniqueness():
    """9. 用例 ID 唯一性验证"""
    print(f"\n=== 9. 用例 ID 唯一性 ===")
    all_ids = []
    for sid, cases in _cases.items():
        for c in cases:
            all_ids.append(c["id"])

    duplicates = [x for x in all_ids if all_ids.count(x) > 1]
    assert len(duplicates) == 0, f"存在重复用例 ID: {set(duplicates)}"
    print(f"  总用例数: {len(all_ids)}, 无重复")
    print("  ✅ 用例 ID 全局唯一")


def test_api_import():
    """10. API Router 导入验证"""
    print(f"\n=== 10. API Router 验证 ===")
    from src.api.chain_eval_api import router
    assert router.prefix == "/api/eval/chain"
    routes = [r.path for r in router.routes]
    expected_paths = ["/stats", "/suites", "/runs", "/run", "/run-stream", "/reports/compare"]
    for ep in expected_paths:
        found = any(ep in r for r in routes)
        status = "✅" if found else "❌"
        print(f"  {status} {ep}")
        assert found, f"缺少路由: {ep}"
    print("  ✅ 所有预期路由已注册")


if __name__ == "__main__":
    print("=" * 60)
    print("    链路评测体系 — 完整验证")
    print("=" * 60)

    test_data_structure()
    test_run_records()
    test_run5_detail()
    test_span_timeline()
    test_failure_attribution()
    test_assertions_consistency()
    test_expandable_data()
    test_span_type_metadata()
    test_case_id_uniqueness()
    test_api_import()

    print("\n" + "=" * 60)
    print("  🎉 全部 10 项验证通过 — 评测体系数据完整、逻辑一致")
    print("=" * 60)
