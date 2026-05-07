"""提示词边界验证脚本 — 用 doubao 模型跑 10 个用例验证四路提取准确性

使用方法：
    python test_prompts.py

需要环境变量：
    DOUBAO_API_KEY — 豆包 API Key
    DOUBAO_MODEL — 模型名（默认 doubao-1-5-lite-32k-250115）
"""
import asyncio
import json
import os
import sys

# 添加项目路径
sys.path.insert(0, os.path.dirname(__file__))

from src.memory.extraction.prompts import (
    PROFILE_EXTRACT_PROMPT,
    PREFERENCES_EXTRACT_PROMPT,
    AGENT_RULES_EXTRACT_PROMPT,
    ENTITIES_EXTRACT_PROMPT,
)

# 50 个测试用例
TEST_CASES = [
    # ── 1-10: 基础场景 ──
    {"id": 1, "input": "你是我的销售数据分析助理，回复简洁不超过200字",
     "expect": {"profile": False, "preferences": False, "agent_rules": True, "entities": False}},
    {"id": 2, "input": "我是华东区销售总监，管理15人团队",
     "expect": {"profile": True, "preferences": False, "agent_rules": False, "entities": False}},
    {"id": 3, "input": "我喜欢用图表展示重要数据，辅助数据用表格",
     "expect": {"profile": False, "preferences": True, "agent_rules": False, "entities": False}},
    {"id": 4, "input": "华为的张伟说话很直接，开会不要绕弯子",
     "expect": {"profile": False, "preferences": False, "agent_rules": False, "entities": True}},
    {"id": 5, "input": "华为内部审批流程复杂，至少要3-4周",
     "expect": {"profile": False, "preferences": False, "agent_rules": False, "entities": True}},
    {"id": 6, "input": "帮我查一下华为的商机",
     "expect": {"profile": False, "preferences": False, "agent_rules": False, "entities": False}},
    {"id": 7, "input": "之前让你用表格，现在改成图表展示重要数据",
     "expect": {"profile": False, "preferences": False, "agent_rules": True, "entities": False}},
    {"id": 8, "input": "你要专注金融行业分析，我们公司主要做金融客户",
     "expect": {"profile": True, "preferences": False, "agent_rules": True, "entities": False}},
    {"id": 9, "input": "帮我把这个客户标记为重点",
     "expect": {"profile": False, "preferences": False, "agent_rules": False, "entities": False}},
    {"id": 10, "input": "我们的竞争对手主要是Salesforce和纷享销客",
     "expect": {"profile": True, "preferences": False, "agent_rules": False, "entities": False}},

    # ── 11-20: agent_rules 边界 ──
    {"id": 11, "input": "你不要编造数据，所有数据必须来自系统查询",
     "expect": {"profile": False, "preferences": False, "agent_rules": True, "entities": False}},
    {"id": 12, "input": "你每次分析先给总结，再给明细",
     "expect": {"profile": False, "preferences": False, "agent_rules": True, "entities": False}},
    {"id": 13, "input": "你说话要专业一点，不要太口语化",
     "expect": {"profile": False, "preferences": False, "agent_rules": True, "entities": False}},
    {"id": 14, "input": "你帮我审合同的流程：先看关键条款，再看风险点",
     "expect": {"profile": False, "preferences": False, "agent_rules": True, "entities": False}},
    {"id": 15, "input": "取消之前不超过200字的限制，可以详细一些",
     "expect": {"profile": False, "preferences": False, "agent_rules": True, "entities": False}},
    {"id": 16, "input": "你的跟进节奏改一下，从3/7/14天改成1/3/7天",
     "expect": {"profile": False, "preferences": False, "agent_rules": True, "entities": False}},
    {"id": 17, "input": "你不能直接给客户报价，必须先经过我确认",
     "expect": {"profile": False, "preferences": False, "agent_rules": True, "entities": False}},
    {"id": 18, "input": "回复用中文，专业术语可以保留英文",
     "expect": {"profile": False, "preferences": False, "agent_rules": True, "entities": False}},
    {"id": 19, "input": "分析报告要包含同比环比数据",
     "expect": {"profile": False, "preferences": False, "agent_rules": True, "entities": False}},
    {"id": 20, "input": "你要熟悉SaaS行业的销售流程",
     "expect": {"profile": False, "preferences": False, "agent_rules": True, "entities": False}},

    # ── 21-30: preferences 边界 ──
    {"id": 21, "input": "我习惯每周一早上看上周的数据汇总",
     "expect": {"profile": False, "preferences": True, "agent_rules": False, "entities": False}},
    {"id": 22, "input": "我不喜欢长篇大论，简洁就好",
     "expect": {"profile": False, "preferences": True, "agent_rules": False, "entities": False}},
    {"id": 23, "input": "我偏好用折线图看趋势变化",
     "expect": {"profile": False, "preferences": True, "agent_rules": False, "entities": False}},
    {"id": 24, "input": "金额我习惯看万为单位，不要用元",
     "expect": {"profile": False, "preferences": True, "agent_rules": False, "entities": False}},
    {"id": 25, "input": "我喜欢先看结论再看过程",
     "expect": {"profile": False, "preferences": True, "agent_rules": False, "entities": False}},
    {"id": 26, "input": "我倾向于用邮件沟通重要事项",
     "expect": {"profile": False, "preferences": True, "agent_rules": False, "entities": False}},
    {"id": 27, "input": "我一般下午3点后才有时间处理非紧急事务",
     "expect": {"profile": False, "preferences": True, "agent_rules": False, "entities": False}},
    {"id": 28, "input": "我觉得饼图比柱状图更直观",
     "expect": {"profile": False, "preferences": True, "agent_rules": False, "entities": False}},
    {"id": 29, "input": "我更关注转化率而不是绝对数量",
     "expect": {"profile": False, "preferences": True, "agent_rules": False, "entities": False}},
    {"id": 30, "input": "我喜欢用颜色区分不同优先级",
     "expect": {"profile": False, "preferences": True, "agent_rules": False, "entities": False}},

    # ── 31-40: entities 边界 ──
    {"id": 31, "input": "泰克科技的张总负责采购决策，李经理负责技术评估",
     "expect": {"profile": False, "preferences": False, "agent_rules": False, "entities": True}},
    {"id": 32, "input": "腾讯云那边的项目已经进入POC阶段了",
     "expect": {"profile": False, "preferences": False, "agent_rules": False, "entities": True}},
    {"id": 33, "input": "张伟比较看重产品的稳定性，对价格不太敏感",
     "expect": {"profile": False, "preferences": False, "agent_rules": False, "entities": True}},
    {"id": 34, "input": "华为那边的合同下个月到期，需要提前续约",
     "expect": {"profile": False, "preferences": False, "agent_rules": False, "entities": True}},
    {"id": 35, "input": "泰克科技是一家汽车零部件供应商，年营收约5亿",
     "expect": {"profile": False, "preferences": False, "agent_rules": False, "entities": True}},
    {"id": 36, "input": "李娜是华为CRM项目的技术负责人",
     "expect": {"profile": False, "preferences": False, "agent_rules": False, "entities": True}},
    {"id": 37, "input": "这个客户之前用的是竞品的方案，切换成本比较高",
     "expect": {"profile": False, "preferences": False, "agent_rules": False, "entities": True}},
    {"id": 38, "input": "华为内部有三个部门在用我们的产品",
     "expect": {"profile": False, "preferences": False, "agent_rules": False, "entities": True}},
    {"id": 39, "input": "张总喜欢看PPT，汇报材料要做得精美",
     "expect": {"profile": False, "preferences": False, "agent_rules": False, "entities": True}},
    {"id": 40, "input": "腾讯那边的决策链比较长，需要过三级审批",
     "expect": {"profile": False, "preferences": False, "agent_rules": False, "entities": True}},

    # ── 41-50: 不提取 + 混合 + 边界模糊 ──
    {"id": 41, "input": "好的，明白了",
     "expect": {"profile": False, "preferences": False, "agent_rules": False, "entities": False}},
    {"id": 42, "input": "帮我创建一个新的商机",
     "expect": {"profile": False, "preferences": False, "agent_rules": False, "entities": False}},
    {"id": 43, "input": "把刚才的分析结果导出为Excel",
     "expect": {"profile": False, "preferences": False, "agent_rules": False, "entities": False}},
    {"id": 44, "input": "我是产品经理，我喜欢用思维导图整理需求",
     "expect": {"profile": True, "preferences": True, "agent_rules": False, "entities": False}},
    {"id": 45, "input": "你要用markdown格式输出，我们团队有20人",
     "expect": {"profile": True, "preferences": False, "agent_rules": True, "entities": False}},
    {"id": 46, "input": "华为的王总很注重细节，你跟他沟通要准备充分",
     "expect": {"profile": False, "preferences": False, "agent_rules": False, "entities": True}},
    {"id": 47, "input": "谢谢",
     "expect": {"profile": False, "preferences": False, "agent_rules": False, "entities": False}},
    {"id": 48, "input": "我负责互联网和金融两个行业的大客户",
     "expect": {"profile": True, "preferences": False, "agent_rules": False, "entities": False}},
    {"id": 49, "input": "下次查询数据的时候自动加上时间范围筛选",
     "expect": {"profile": False, "preferences": False, "agent_rules": True, "entities": False}},
    {"id": 50, "input": "客户反馈我们的响应速度比竞品快，这是优势",
     "expect": {"profile": False, "preferences": False, "agent_rules": False, "entities": True}},
]

PROMPTS = {
    "profile": PROFILE_EXTRACT_PROMPT,
    "preferences": PREFERENCES_EXTRACT_PROMPT,
    "agent_rules": AGENT_RULES_EXTRACT_PROMPT,
    "entities": ENTITIES_EXTRACT_PROMPT,
}

FILL_PARAMS = {
    "profile": {"existing_profile": "（无）", "user_messages": None, "output_language": "auto"},
    "preferences": {"user_messages": None, "output_language": "auto"},
    "agent_rules": {"existing_rules": "（无）", "user_messages": None, "output_language": "auto"},
    "entities": {"existing_entities": "（无）", "conversation": None, "output_language": "auto"},
}

# 输入字段名映射
INPUT_FIELD = {
    "profile": "user_messages",
    "preferences": "user_messages",
    "agent_rules": "user_messages",
    "entities": "conversation",
}


def has_extraction(response_text: str, dimension: str) -> bool:
    """判断 LLM 输出是否有有效提取"""
    try:
        if "{" not in response_text:
            return False
        json_str = response_text[response_text.index("{"):response_text.rindex("}") + 1]
        data = json.loads(json_str)

        if dimension == "profile":
            profile = data.get("profile", {})
            return bool(profile.get("content", ""))
        elif dimension == "preferences":
            prefs = data.get("preferences", [])
            return len(prefs) > 0
        elif dimension == "agent_rules":
            rules = data.get("agent_rules", {})
            return bool(rules.get("content", ""))
        elif dimension == "entities":
            entities = data.get("entities", [])
            return len(entities) > 0
    except (json.JSONDecodeError, ValueError):
        pass
    return False


async def call_llm(prompt: str) -> str:
    """调用豆包模型"""
    from langchain_openai import ChatOpenAI

    api_key = os.environ.get("DOUBAO_API_KEY", "")
    model = os.environ.get("DOUBAO_MODEL", "doubao-1-5-lite-32k-250115")
    base_url = os.environ.get("DOUBAO_BASE_URL", "https://ark.cn-beijing.volces.com/api/v3")

    if not api_key:
        print("❌ 请设置 DOUBAO_API_KEY 环境变量")
        sys.exit(1)

    llm = ChatOpenAI(
        model=model,
        api_key=api_key,
        base_url=base_url,
        temperature=0,
    )
    result = await llm.ainvoke(prompt)
    return result.content


async def run_test(case: dict) -> dict:
    """跑一个用例的四路提取"""
    results = {}
    for dim, prompt_template in PROMPTS.items():
        params = dict(FILL_PARAMS[dim])
        params[INPUT_FIELD[dim]] = f"[human]: {case['input']}"

        prompt = prompt_template.format(**params)
        response = await call_llm(prompt)
        extracted = has_extraction(response, dim)
        results[dim] = {
            "extracted": extracted,
            "expected": case["expect"][dim],
            "pass": extracted == case["expect"][dim],
            "response": response[:200],
        }
    return results


async def main():
    print("=" * 60)
    print("记忆提取提示词边界验证（doubao 2.0 lite）")
    print("=" * 60)

    total = 0
    passed = 0
    failures = []

    for case in TEST_CASES:
        print(f"\n--- 用例 {case['id']}: {case['input'][:40]}...")
        results = await run_test(case)

        all_pass = True
        for dim, r in results.items():
            total += 1
            status = "✅" if r["pass"] else "❌"
            if r["pass"]:
                passed += 1
            else:
                all_pass = False
                failures.append(f"用例{case['id']} {dim}: 期望{'提取' if r['expected'] else '不提取'}, 实际{'提取' if r['extracted'] else '不提取'}")

            print(f"  {status} {dim}: {'提取' if r['extracted'] else '空'} (期望{'提取' if r['expected'] else '空'})")
            if not r["pass"]:
                print(f"     响应: {r['response'][:100]}...")

    print(f"\n{'=' * 60}")
    print(f"结果: {passed}/{total} 通过 ({passed/total*100:.0f}%)")
    if failures:
        print(f"\n失败项:")
        for f in failures:
            print(f"  ❌ {f}")


if __name__ == "__main__":
    asyncio.run(main())
