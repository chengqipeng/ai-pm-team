"""只验证 preferences prompt 的边界"""
import asyncio, json, os, sys
sys.path.insert(0, os.path.dirname(__file__))
from src.memory.extraction.prompts import PREFERENCES_EXTRACT_PROMPT
from langchain_openai import ChatOpenAI

llm = ChatOpenAI(
    model=os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-flash"),
    api_key=os.environ.get("DEEPSEEK_API_KEY", "sk-HdY98AcN68JhtXLp8oeIATEL4PWq9rzRcCAhI8G4SOtBbtSw"),
    base_url=os.environ.get("DEEPSEEK_API_BASE", "https://tokenhub.tencentmaas.com/v1"),
    temperature=0,
)

# (id, input, should_extract)
CASES = [
    # 应该不提取（对 Agent 的指令）
    (7, "之前让你用表格，现在改成图表展示重要数据", False),
    (14, "你帮我审合同的流程：先看关键条款，再看风险点", False),
    (16, "你的跟进节奏改一下，从3/7/14天改成1/3/7天", False),
    (19, "分析报告要包含同比环比数据", False),
    (18, "回复用中文，专业术语可以保留英文", False),
    (11, "你不要编造数据，所有数据必须来自系统查询", False),
    # 应该提取（用户偏好）
    (3, "我喜欢用图表展示重要数据，辅助数据用表格", True),
    (21, "我习惯每周一早上看上周的数据汇总", True),
    (22, "我不喜欢长篇大论，简洁就好", True),
    (23, "我偏好用折线图看趋势变化", True),
    (24, "金额我习惯看万为单位，不要用元", True),
    (25, "我喜欢先看结论再看过程", True),
    (28, "我觉得饼图比柱状图更直观", True),
    (29, "我更关注转化率而不是绝对数量", True),
    (27, "我一般下午3点后才有时间处理非紧急事务", True),
]


async def test_one(case_id, text, expect):
    prompt = PREFERENCES_EXTRACT_PROMPT.format(user_messages=f"[human]: {text}", output_language="auto")
    result = await llm.ainvoke(prompt)
    content = result.content
    try:
        if "{" in content:
            data = json.loads(content[content.index("{"):content.rindex("}") + 1])
            extracted = len(data.get("preferences", [])) > 0
        else:
            extracted = False
    except Exception:
        extracted = False
    passed = extracted == expect
    mark = "PASS" if passed else "FAIL"
    exp_str = "extract" if expect else "empty"
    act_str = "extract" if extracted else "empty"
    print(f"[{mark}] case {case_id:2d}: expect={exp_str:7s} actual={act_str:7s} | {text[:40]}")
    return passed


async def main():
    results = []
    for case_id, text, expect in CASES:
        r = await test_one(case_id, text, expect)
        results.append(r)
    total = len(results)
    passed = sum(results)
    print(f"\nResult: {passed}/{total} passed ({passed/total*100:.0f}%)")


if __name__ == "__main__":
    asyncio.run(main())
