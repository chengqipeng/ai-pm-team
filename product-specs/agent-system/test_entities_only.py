"""验证 entities prompt 边界"""
import asyncio, json, os, sys
sys.path.insert(0, os.path.dirname(__file__))
from src.memory.extraction.prompts import ENTITIES_EXTRACT_PROMPT
from langchain_openai import ChatOpenAI

llm = ChatOpenAI(
    model="doubao-seed-2-0-lite-260215",
    api_key=os.environ.get("DOUBAO_API_KEY", "651621e7-e495-4728-93ef-ed380e9ddcd1"),
    base_url="https://ark.cn-beijing.volces.com/api/v3/",
    temperature=0,
)

CASES = [
    # 应该不提取
    (1, "你是我的销售数据分析助理，回复简洁不超过200字", False),
    (2, "我是华东区销售总监，管理15人团队", False),
    (3, "我喜欢用图表展示重要数据，辅助数据用表格", False),
    (6, "帮我查一下华为的商机", False),
    (8, "你要专注金融行业分析，我们公司主要做金融客户", False),
    (10, "我们的竞争对手主要是Salesforce和纷享销客", False),
    (16, "你的跟进节奏改一下，从3/7/14天改成1/3/7天", False),
    (17, "你不能直接给客户报价，必须先经过我确认", False),
    (19, "分析报告要包含同比环比数据", False),
    (21, "我习惯每周一早上看上周的数据汇总", False),
    (22, "我不喜欢长篇大论，简洁就好", False),
    (24, "金额我习惯看万为单位，不要用元", False),
    # 应该提取
    (4, "华为的张伟说话很直接，开会不要绕弯子", True),
    (5, "华为内部审批流程复杂，至少要3-4周", True),
    (31, "泰克科技的张总负责采购决策，李经理负责技术评估", True),
    (33, "张伟比较看重产品的稳定性，对价格不太敏感", True),
    (36, "李娜是华为CRM项目的技术负责人", True),
    (40, "腾讯那边的决策链比较长，需要过三级审批", True),
]

async def test_one(case_id, text, expect):
    prompt = ENTITIES_EXTRACT_PROMPT.format(existing_entities="（无）", conversation=f"[human]: {text}", output_language="auto")
    result = await llm.ainvoke(prompt)
    content = result.content
    try:
        if "{" in content:
            data = json.loads(content[content.index("{"):content.rindex("}")+1])
            extracted = len(data.get("entities", [])) > 0
        else:
            extracted = False
    except:
        extracted = False
    passed = extracted == expect
    mark = "PASS" if passed else "FAIL"
    print(f"[{mark}] case {case_id:2d}: expect={'extract' if expect else 'empty':7s} actual={'extract' if extracted else 'empty':7s} | {text[:40]}")
    return passed

async def main():
    results = []
    for cid, text, expect in CASES:
        r = await test_one(cid, text, expect)
        results.append(r)
    print(f"\nResult: {sum(results)}/{len(results)} passed ({sum(results)/len(results)*100:.0f}%)")

if __name__ == "__main__":
    asyncio.run(main())
