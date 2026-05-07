"""失败用例根因诊断

目的：判断每个失败是
  (a) 模型能力极限（Lite模型对歧义处理不稳定）— 换更强模型可解
  (b) Prompt 规则漏洞（模型推理合理但 prompt 没覆盖）— 微调 prompt 可解
  (c) 真歧义（人类也会分歧）— 不应追求"正确"

方法：
  1. 对每个失败用例，用同一 prompt 在 lite 模型上跑 5 次（temperature=0.3）看一致性
     - 如果 5 次都错 → 模型固有偏差或 prompt 漏洞
     - 如果 5 次不一致 → 模型能力极限
  2. 用 pro 模型（doubao-seed-1-6-250615）跑 1 次
     - 如果 pro 通过 lite 失败 → 可通过换模型解决
"""
import asyncio
import json
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("DOUBAO_API_KEY", "651621e7-e495-4728-93ef-ed380e9ddcd1")

from src.memory.extraction.prompts import (
    PROFILE_EXTRACT_PROMPT,
    PREFERENCES_EXTRACT_PROMPT,
    AGENT_RULES_EXTRACT_PROMPT,
    ENTITIES_EXTRACT_PROMPT,
)

PROMPTS = {
    "profile": PROFILE_EXTRACT_PROMPT,
    "preferences": PREFERENCES_EXTRACT_PROMPT,
    "agent_rules": AGENT_RULES_EXTRACT_PROMPT,
    "entities": ENTITIES_EXTRACT_PROMPT,
}
FILL_PARAMS = {
    "profile": {"existing_profile": "（无）", "output_language": "auto"},
    "preferences": {"output_language": "auto"},
    "agent_rules": {"existing_rules": "（无）", "output_language": "auto"},
    "entities": {"existing_entities": "（无）", "output_language": "auto"},
}
INPUT_FIELD = {
    "profile": "user_messages", "preferences": "user_messages",
    "agent_rules": "user_messages", "entities": "conversation",
}

# 来自 100 集 + 200 集的所有失败用例（id, input, expect_on_failing_dim, failing_dim）
FAILING_CASES = [
    # 从 100 集
    (11, "刚来三个月，还在熟悉业务", True, "profile"),
    (16, "受不了那种啰嗦的回复，直接说重点就行", False, "agent_rules"),
    (17, "数据嘛，能用图就别用表，一目了然", True, "preferences"),
    (29, "算了，还是用表格吧，图表看不清", False, "preferences"),
    # 从 200 集
    (26, "我常用中英双语，跟海外客户邮件基本都是英文", False, "preferences"),
    (47, "涉及金额超过50万的决策我要亲自过", False, "profile"),
    (102, "纷享销客在中腰部市场打得很凶，价格比我们低一半", False, "profile"),
    (113, "腾讯的Mike脾气比较急，沟通要直接", False, "agent_rules"),
    (163, "我是华为的合作伙伴，接下来重点盯这个客户", True, "agent_rules"),
    (166, "我是产品经理负责CRM模块，你帮我盯三个竞品：纷享、销售易、红圈", True, "agent_rules"),
    (173, "我在香港办公，输出默认用繁体，金额用港币", False, "preferences"),
    (176, "我更喜欢口头汇报，书面的就简写要点即可", True, "agent_rules"),
    (177, "宁德时代的王总不开会，你准备材料时多准备一份书面稿", True, "agent_rules"),
    (188, "以后别叫我老师，直接叫名字就行", False, "preferences"),
]


def extracted(response_text: str, dim: str) -> bool:
    try:
        if "{" not in response_text:
            return False
        json_str = response_text[response_text.index("{"):response_text.rindex("}") + 1]
        data = json.loads(json_str)
        if dim == "profile":
            return bool(data.get("profile", {}).get("content", ""))
        elif dim == "preferences":
            return len(data.get("preferences", [])) > 0
        elif dim == "agent_rules":
            return bool(data.get("agent_rules", {}).get("content", ""))
        elif dim == "entities":
            return len(data.get("entities", [])) > 0
    except Exception:
        return False


async def run_once(llm, text: str, dim: str) -> bool:
    params = dict(FILL_PARAMS[dim])
    params[INPUT_FIELD[dim]] = f"[human]: {text}"
    prompt = PROMPTS[dim].format(**params)
    res = await llm.ainvoke(prompt)
    return extracted(res.content, dim)


async def diagnose(case_id, text, expect, dim):
    from langchain_openai import ChatOpenAI

    # 1) Lite 模型，temperature=0.3 跑 5 次看一致性
    lite_t03 = ChatOpenAI(
        model="doubao-seed-2-0-lite-260215",
        api_key=os.environ["DOUBAO_API_KEY"],
        base_url="https://ark.cn-beijing.volces.com/api/v3/",
        temperature=0.3, max_tokens=2048,
    )
    lite_results = await asyncio.gather(*[run_once(lite_t03, text, dim) for _ in range(5)])
    lite_consistency = sum(r == expect for r in lite_results)  # 对的次数

    # 2) Pro 模型，temperature=0 单次
    try:
        pro = ChatOpenAI(
            model=os.environ.get("DOUBAO_PRO_MODEL", "doubao-seed-1-6-250615"),
            api_key=os.environ["DOUBAO_API_KEY"],
            base_url="https://ark.cn-beijing.volces.com/api/v3/",
            temperature=0, max_tokens=2048,
        )
        pro_result = await run_once(pro, text, dim)
        pro_ok = pro_result == expect
        pro_err = None
    except Exception as e:
        pro_ok = None
        pro_err = str(e)[:80]

    # 诊断结论
    if lite_consistency == 0:
        lite_verdict = "lite稳定错"
    elif lite_consistency == 5:
        lite_verdict = "lite稳定对(仅t=0场景有问题)"
    else:
        lite_verdict = f"lite不稳定({lite_consistency}/5对)"

    pro_verdict = ("pro对" if pro_ok else "pro错") if pro_ok is not None else f"pro失败:{pro_err}"

    if lite_consistency >= 4 and not pro_ok:
        root = "🟡 模型层歧义/模型能力差异（人也难）"
    elif lite_consistency <= 1 and pro_ok is False:
        root = "🔴 Prompt 规则漏洞（模型一致错，需改prompt）"
    elif pro_ok:
        root = "🟢 Lite能力极限（换Pro可解）"
    else:
        root = "🟠 边缘歧义（lite不稳定+pro不一致）"

    return {
        "id": case_id, "text": text, "dim": dim, "expect": expect,
        "lite_consistency": f"{lite_consistency}/5",
        "lite_results": lite_results,
        "pro_ok": pro_ok, "pro_err": pro_err,
        "root_cause": root,
    }


async def main():
    print("=" * 80)
    print(f"  失败用例根因诊断 — {len(FAILING_CASES)} 个用例")
    print(f"  策略: lite@t=0.3 x 5次 + pro@t=0 x 1次")
    print("=" * 80)

    results = []
    sem = asyncio.Semaphore(4)

    async def _run(tup):
        async with sem:
            return await diagnose(*tup)

    tasks = [_run(c) for c in FAILING_CASES]
    for fut in asyncio.as_completed(tasks):
        r = await fut
        print(f"\n#{r['id']} [{r['dim']}] {r['text']}")
        print(f"   期望: {'提取' if r['expect'] else '空'}  "
              f"Lite稳定性: {r['lite_consistency']}  "
              f"Pro: {'✓' if r['pro_ok'] else '✗' if r['pro_ok'] is False else 'N/A'}")
        print(f"   根因: {r['root_cause']}")
        results.append(r)

    # 分类汇总
    print("\n" + "=" * 80)
    print("  根因分类")
    print("=" * 80)
    counter = Counter(r["root_cause"] for r in results)
    for cause, n in counter.most_common():
        print(f"  {cause}: {n}条")

    print("\n  明细:")
    for cause in counter:
        print(f"\n  === {cause} ===")
        for r in results:
            if r["root_cause"] == cause:
                print(f"    #{r['id']} [{r['dim']}] {r['text'][:50]}")

    # 建议
    print("\n" + "=" * 80)
    print("  提升到100%的可行路径")
    print("=" * 80)
    green = counter.get("🟢 Lite能力极限（换Pro可解）", 0)
    red = counter.get("🔴 Prompt 规则漏洞（模型一致错，需改prompt）", 0)
    orange = counter.get("🟠 边缘歧义（lite不稳定+pro不一致）", 0)
    yellow = counter.get("🟡 模型层歧义/模型能力差异（人也难）", 0)
    print(f"  🟢 换 Pro 模型可解: {green} 条 → 成本↑，泛化能力↑")
    print(f"  🔴 改 prompt 可解 : {red} 条 → 成本0，但有再过拟合风险")
    print(f"  🟠 边缘歧义      : {orange} 条 → 多采样投票可改善")
    print(f"  🟡 真歧义/模型硬伤: {yellow} 条 → 即使人类也会分歧")

    total = len(results)
    if green + red >= total * 0.8:
        print("\n  ✅ 可行：绝大部分失败可通过换模型或精确改prompt修复")
    else:
        print("\n  ⚠️ 100% 难达成：很多失败属于真歧义，建议接受 95% 基线")


if __name__ == "__main__":
    asyncio.run(main())
