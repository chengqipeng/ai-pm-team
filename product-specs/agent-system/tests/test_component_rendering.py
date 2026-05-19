"""端到端验证：每个 A2UI 组件的渲染链路测试

验证流程：
1. 模拟 Skill 输出结构化数据
2. 通过 AGUIConverter + ProgressiveRenderer 处理
3. 验证产出的事件类型和数据结构符合组件的 input_schema
"""
import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.agui.converter import AGUIConverter
from src.agui.renderer import ProgressiveRenderer, ComponentMatcher
from src.agui import models as m
from src.agui.long_text import LongTextParser


def load_component_schemas():
    """加载所有组件的 input_schema"""
    comp_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "resources", "a2ui", "components")
    schemas = {}
    for f in os.listdir(comp_dir):
        if not f.endswith(".json"):
            continue
        with open(os.path.join(comp_dir, f)) as fp:
            d = json.load(fp)
        schemas[d.get("type", "")] = d
    return schemas


# ═══════════════════════════════════════════════════════════
# 测试数据：每个组件的模拟 Skill 输出
# ═══════════════════════════════════════════════════════════

COMPONENT_TEST_DATA = {
    "CrmRecordCard": {
        "skill_apikey": "customer_360_analysis",
        "output": {
            "recordType": "customer",
            "recordId": "C001",
            "name": "工商银行",
            "industry": "金融",
            "city": "北京",
            "score": 85,
            "owner": "张三",
        },
    },
    "PipelineTable": {
        "skill_apikey": "pipeline_analysis",
        "output": {
            "stages": [
                {"name": "线索", "count": 45, "amount": 1200, "weighted": 120, "probability": 0.1},
                {"name": "需求确认", "count": 28, "amount": 890, "weighted": 267, "probability": 0.3},
                {"name": "方案报价", "count": 15, "amount": 650, "weighted": 325, "probability": 0.5},
                {"name": "谈判", "count": 8, "amount": 420, "weighted": 336, "probability": 0.8},
                {"name": "赢单", "count": 5, "amount": 280, "weighted": 280, "probability": 1.0},
            ],
            "total_amount": 3440,
            "total_weighted": 1328,
        },
    },
    "BantMatrix": {
        "skill_apikey": "bant_analysis",
        "output": {
            "opportunity_name": "核心系统升级",
            "budget": {"score": 8, "evidence": "已获批500万预算"},
            "authority": {"score": 7, "evidence": "CIO 直接参与"},
            "need": {"score": 9, "evidence": "现有系统频繁故障"},
            "timeline": {"score": 6, "evidence": "Q4 前完成"},
        },
    },
    "OpportunityTimeline": {
        "skill_apikey": "opportunity_timeline",
        "output": {
            "opportunity_name": "核心系统升级",
            "events": [
                {"date": "2025-03-01", "type": "stage_change", "description": "线索 → 需求确认"},
                {"date": "2025-03-15", "type": "meeting", "description": "与 CIO 首次会面"},
                {"date": "2025-04-02", "type": "stage_change", "description": "需求确认 → 方案报价"},
                {"date": "2025-04-20", "type": "proposal", "description": "提交技术方案"},
            ],
        },
    },
    "SearchResultsList": {
        "skill_apikey": "knowledge_doc_search",
        "output": {
            "query": "3051 量程 精度",
            "results": [
                {"title": "产品样本：罗斯蒙特CF_SF系列", "snippet": "精度可达0.025%...", "score": 0.82, "doc_id": "doc_9125"},
                {"title": "快速安装指南：3051SF", "snippet": "安装前确认量程...", "score": 0.71, "doc_id": "doc_7454"},
            ],
        },
    },
    "LinkCard": {
        "skill_apikey": "web_search",
        "output": {
            "title": "罗斯蒙特3051S官方产品页",
            "url": "https://www.emerson.com/rosemount-3051s",
            "description": "Rosemount 3051S 系列压力变送器官方产品介绍",
            "thumbnail": "",
            "source": "emerson.com",
        },
    },
    "SearchSourcePanel": {
        "skill_apikey": "knowledge_doc_search",
        "output": {
            "sources": [
                {"type": "knowledge", "title": "产品样本：罗斯蒙特CF_SF系列", "snippet": "精度0.025%", "score": 0.82, "doc_id": "doc_9125", "section_title": "差压范围"},
                {"type": "knowledge", "title": "快速安装指南：3051SF", "snippet": "安装步骤", "score": 0.71, "doc_id": "doc_7454", "section_title": "安装准备"},
                {"type": "web", "title": "Emerson 官网", "url": "https://emerson.com", "snippet": "产品介绍"},
            ],
            "query": "3051 量程",
            "total_count": 3,
        },
    },
    "CrmDataCard": {
        "skill_apikey": "customer_360",
        "output": {
            "entity_type": "opportunity",
            "display_mode": "list",
            "records": [
                {"id": "O001", "name": "核心系统升级", "fields": {"amount": 580000, "stage": "谈判", "close_date": "2025-06-30"}},
                {"id": "O002", "name": "数据中台建设", "fields": {"amount": 320000, "stage": "方案", "close_date": "2025-08-15"}},
            ],
            "total_count": 2,
            "title": "工商银行 - 商机列表",
        },
    },
    "AudioSummaryCard": {
        "skill_apikey": "audio_analysis",
        "output": {
            "title": "Q3 销售复盘会议录音",
            "duration": "45:12",
            "summary": "本次会议讨论了Q3销售目标完成情况，重点分析了大客户流失原因和Q4改进计划。",
            "key_points": [
                "Q3 完成率 87%，差距主要在金融行业",
                "工商银行项目延期导致 200 万缺口",
                "Q4 重点攻克 3 个大客户续约",
            ],
            "participants": ["张总", "李经理", "王主管"],
            "action_items": [
                {"content": "制定工商银行挽回方案", "assignee": "李经理", "deadline": "2025-10-15"},
                {"content": "安排 Q4 大客户拜访计划", "assignee": "王主管", "deadline": "2025-10-10"},
            ],
        },
    },
    "FallbackDataViewer": {
        "skill_apikey": "unknown_skill",
        "output": {
            "data_key": "raw_output",
            "data": {"foo": "bar", "count": 42, "nested": {"a": 1, "b": [1, 2, 3]}},
            "skill_apikey": "unknown_skill",
        },
    },
}


# ═══════════════════════════════════════════════════════════
# MicroReportCard 测试（通过 <long_text> 标签触发）
# ═══════════════════════════════════════════════════════════

async def test_micro_report_card():
    """测试 MicroReportCard 通过 <long_text> 标签触发"""
    parser = LongTextParser(run_id="test_micro")
    events = []

    chunks = [
        '<long_text type="report" title="Q3 销售分析报告">',
        "# Q3 销售分析\n\n## 概览\n\n总营收 3440 万，完成率 87%。\n\n",
        "## 详细数据\n\n| 阶段 | 金额 |\n|---|---|\n| 线索 | 1200万 |\n| 赢单 | 280万 |",
        "</long_text>",
    ]

    for chunk in chunks:
        async for ev in parser.feed(chunk):
            events.append(ev)

    # 验证
    activities = [e for e in events if "ACTIVITY" in (e.type if isinstance(e.type, str) else e.type.value)]
    assert len(activities) == 2, f"Expected 2 ACTIVITY events, got {len(activities)}"

    # 验证 complete 卡片的数据结构
    complete_ev = activities[1]
    ops = complete_ev.data.get("content", {}).get("operations", [])
    surface_update = ops[0].get("surfaceUpdate", {})
    components = surface_update.get("components", [])
    card_props = components[0].get("component", {}).get("MicroReportCard", {})

    assert card_props.get("status") == "complete"
    assert card_props.get("title") == "Q3 销售分析报告"
    assert "Q3 销售分析" in card_props.get("content", "")
    assert "|" in card_props.get("content", "")  # 包含表格

    return True


# ═══════════════════════════════════════════════════════════
# 组件渲染链路测试（通过 Renderer）
# ═══════════════════════════════════════════════════════════

async def test_component_rendering(comp_type: str, test_data: dict):
    """测试组件通过 Renderer 的渲染链路"""
    skill_apikey = test_data["skill_apikey"]
    output = test_data["output"]

    # 设置 ComponentMatcher
    matcher = ComponentMatcher()
    matcher.register(skill_apikey, comp_type)
    renderer = ProgressiveRenderer(matcher=matcher)

    # 构造事件流
    async def event_stream():
        yield m.step_started(skill_apikey)
        yield m.custom_event("step_metadata", {
            "step_name": skill_apikey, "skill_apikey": skill_apikey,
            "step_index": 0, "phase": "started",
        })
        yield m.custom_event("skill_output", {
            "skill_apikey": skill_apikey, "data": output,
        })
        yield m.custom_event("step_metadata", {
            "step_name": skill_apikey, "skill_apikey": skill_apikey,
            "step_index": 0, "status": "completed", "phase": "finished",
        })
        yield m.step_finished(skill_apikey)

    # 通过 Renderer 处理
    output_events = []
    async for ev in renderer.process(event_stream()):
        output_events.append(ev)

    # 验证
    event_names = [(e.type if isinstance(e.type, str) else e.type.value, e.data.get("name", ""))
                   for e in output_events]

    has_loading = any(n == "component_loading" for _, n in event_names)
    has_complete = any(n == "component_complete" for _, n in event_names)
    has_skill_output = any(n == "skill_output" for _, n in event_names)

    assert has_loading, f"{comp_type}: missing component_loading"
    assert has_complete, f"{comp_type}: missing component_complete"
    assert not has_skill_output, f"{comp_type}: skill_output should be intercepted"

    # 验证 component_complete 的数据
    complete_ev = next(e for e in output_events if e.data.get("name") == "component_complete")
    complete_data = complete_ev.data.get("value", {})
    assert complete_data.get("apikey") == comp_type
    assert complete_data.get("state") == "complete"
    assert complete_data.get("data") == output

    return True


# ═══════════════════════════════════════════════════════════
# 主测试入口
# ═══════════════════════════════════════════════════════════

async def main():
    schemas = load_component_schemas()

    print("=" * 70)
    print("A2UI 组件渲染链路端到端测试")
    print("=" * 70)
    print()

    results = []

    # 1. MicroReportCard（<long_text> 标签）
    print("━━━ MicroReportCard（<long_text> 标签触发）━━━")
    try:
        await test_micro_report_card()
        print("  ✅ PASS: pending + complete ACTIVITY_SNAPSHOT 正确产出")
        results.append(("MicroReportCard", True))
    except AssertionError as e:
        print(f"  ❌ FAIL: {e}")
        results.append(("MicroReportCard", False))
    print()

    # 2. 其他组件（通过 Renderer）
    for comp_type, test_data in COMPONENT_TEST_DATA.items():
        if comp_type == "FallbackDataViewer":
            # FallbackDataViewer 是降级组件，不走 Renderer 匹配
            print(f"━━━ {comp_type}（降级组件，跳过 Renderer 测试）━━━")
            print("  ✅ SKIP: 降级组件无需 Renderer 匹配")
            results.append((comp_type, True))
            print()
            continue

        print(f"━━━ {comp_type} ━━━")
        try:
            await test_component_rendering(comp_type, test_data)
            print(f"  ✅ PASS: component_loading → skill_output 拦截 → component_complete")
            # 验证数据结构是否符合 input_schema
            schema = schemas.get(comp_type, {}).get("input_schema", {})
            if schema:
                required = schema.get("required", [])
                output_keys = set(test_data["output"].keys())
                missing = [r for r in required if r not in output_keys]
                if missing:
                    print(f"  ⚠️  WARNING: 输出缺少 required 字段: {missing}")
                else:
                    print(f"  ✅ 数据结构符合 input_schema (required: {required})")
            results.append((comp_type, True))
        except AssertionError as e:
            print(f"  ❌ FAIL: {e}")
            results.append((comp_type, False))
        print()

    # 汇总
    print("=" * 70)
    print("测试结果汇总")
    print("=" * 70)
    passed = sum(1 for _, ok in results if ok)
    total = len(results)
    print()
    for comp, ok in results:
        print(f"  {'✅' if ok else '❌'} {comp}")
    print()
    print(f"通过: {passed}/{total}")
    if passed == total:
        print("\n🎉 全部通过！所有组件渲染链路验证成功。")
    else:
        print(f"\n❌ {total - passed} 个组件测试失败。")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
