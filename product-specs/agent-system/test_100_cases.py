"""100 个用例验证四路提取准确率"""
import asyncio, json, os, sys
sys.path.insert(0, os.path.dirname(__file__))
from src.memory.extraction.prompts import (
    PROFILE_EXTRACT_PROMPT, PREFERENCES_EXTRACT_PROMPT,
    AGENT_RULES_EXTRACT_PROMPT, ENTITIES_EXTRACT_PROMPT,
)
from langchain_openai import ChatOpenAI

llm = ChatOpenAI(
    model="deepseek-v4-flash",
    api_key=os.environ.get("DEEPSEEK_API_KEY", "sk-HdY98AcN68JhtXLp8oeIATEL4PWq9rzRcCAhI8G4SOtBbtSw"),
    base_url="https://tokenhub.tencentmaas.com/v1",
    temperature=0,
)

# 100 个测试用例: (id, input, {dimension: should_extract})
CASES = [
    # ── 1-20: agent_rules（应提取）──
    (1, "你是我的销售数据分析助理，回复简洁不超过200字", {"agent_rules": True, "preferences": False, "profile": False, "entities": False}),
    (2, "你不要编造数据，所有数据必须来自系统查询", {"agent_rules": True, "preferences": False, "profile": False, "entities": False}),
    (3, "你每次分析先给总结，再给明细", {"agent_rules": True, "preferences": False, "profile": False, "entities": False}),
    (4, "你说话要专业一点，不要太口语化", {"agent_rules": True, "preferences": False, "profile": False, "entities": False}),
    (5, "你帮我审合同的流程：先看关键条款，再看风险点", {"agent_rules": True, "preferences": False, "profile": False, "entities": False}),
    (6, "取消之前不超过200字的限制，可以详细一些", {"agent_rules": True, "preferences": False, "profile": False, "entities": False}),
    (7, "之前让你用表格，现在改成图表展示重要数据", {"agent_rules": True, "preferences": False, "profile": False, "entities": False}),
    (8, "你不能直接给客户报价，必须先经过我确认", {"agent_rules": True, "preferences": False, "profile": False, "entities": False}),
    (9, "回复用中文，专业术语可以保留英文", {"agent_rules": True, "preferences": False, "profile": False, "entities": False}),
    (10, "分析报告要包含同比环比数据", {"agent_rules": True, "preferences": False, "profile": False, "entities": False}),
    (11, "你要熟悉SaaS行业的销售流程", {"agent_rules": True, "preferences": False, "profile": False, "entities": False}),
    (12, "你的跟进节奏改一下，从3/7/14天改成1/3/7天", {"agent_rules": True, "preferences": False, "profile": False, "entities": False}),
    (13, "下次查询数据的时候自动加上时间范围筛选", {"agent_rules": True, "preferences": False, "profile": False, "entities": False}),
    (14, "你要用markdown格式输出", {"agent_rules": True, "preferences": False, "profile": False, "entities": False}),
    (15, "给我的周报要包含本周新增客户和商机转化率", {"agent_rules": True, "preferences": False, "profile": False, "entities": False}),
    (16, "你回复不要用emoji", {"agent_rules": True, "preferences": False, "profile": False, "entities": False}),
    (17, "每次给建议的时候要附上数据支撑", {"agent_rules": True, "preferences": False, "profile": False, "entities": False}),
    (18, "你要记住我的客户优先级排序", {"agent_rules": True, "preferences": False, "profile": False, "entities": False}),
    (19, "输出表格时列宽要对齐", {"agent_rules": True, "preferences": False, "profile": False, "entities": False}),
    (20, "你分析数据时要考虑季节性因素", {"agent_rules": True, "preferences": False, "profile": False, "entities": False}),

    # ── 21-40: preferences（应提取）──
    (21, "我喜欢用图表展示重要数据，辅助数据用表格", {"preferences": True, "agent_rules": False, "profile": False, "entities": False}),
    (22, "我习惯每周一早上看上周的数据汇总", {"preferences": True, "agent_rules": False, "profile": False, "entities": False}),
    (23, "我不喜欢长篇大论，简洁就好", {"preferences": True, "agent_rules": False, "profile": False, "entities": False}),
    (24, "我偏好用折线图看趋势变化", {"preferences": True, "agent_rules": False, "profile": False, "entities": False}),
    (25, "金额我习惯看万为单位，不要用元", {"preferences": True, "agent_rules": False, "profile": False, "entities": False}),
    (26, "我喜欢先看结论再看过程", {"preferences": True, "agent_rules": False, "profile": False, "entities": False}),
    (27, "我倾向于用邮件沟通重要事项", {"preferences": True, "agent_rules": False, "profile": False, "entities": False}),
    (28, "我一般下午3点后才有时间处理非紧急事务", {"preferences": True, "agent_rules": False, "profile": False, "entities": False}),
    (29, "我觉得饼图比柱状图更直观", {"preferences": True, "agent_rules": False, "profile": False, "entities": False}),
    (30, "我更关注转化率而不是绝对数量", {"preferences": True, "agent_rules": False, "profile": False, "entities": False}),
    (31, "我喜欢用颜色区分不同优先级", {"preferences": True, "agent_rules": False, "profile": False, "entities": False}),
    (32, "我通常周五下午做复盘", {"preferences": True, "agent_rules": False, "profile": False, "entities": False}),
    (33, "我不喜欢太多数字堆砌，要有分析", {"preferences": True, "agent_rules": False, "profile": False, "entities": False}),
    (34, "我习惯把重要客户放在前面看", {"preferences": True, "agent_rules": False, "profile": False, "entities": False}),
    (35, "我喜欢对比分析，看同行差距", {"preferences": True, "agent_rules": False, "profile": False, "entities": False}),
    (36, "我一般早上9点前处理邮件", {"preferences": True, "agent_rules": False, "profile": False, "entities": False}),
    (37, "我偏好简短的摘要而不是长报告", {"preferences": True, "agent_rules": False, "profile": False, "entities": False}),
    (38, "我觉得漏斗图展示转化最清晰", {"preferences": True, "agent_rules": False, "profile": False, "entities": False}),
    (39, "我更喜欢看百分比而不是绝对值", {"preferences": True, "agent_rules": False, "profile": False, "entities": False}),
    (40, "我习惯用红黄绿标记紧急程度", {"preferences": True, "agent_rules": False, "profile": False, "entities": False}),

    # ── 41-55: profile（应提取）──
    (41, "我是华东区销售总监，管理15人团队", {"profile": True, "preferences": False, "agent_rules": False, "entities": False}),
    (42, "我们公司主要做金融客户", {"profile": True, "preferences": False, "agent_rules": False, "entities": False}),
    (43, "我负责互联网和金融两个行业的大客户", {"profile": True, "preferences": False, "agent_rules": False, "entities": False}),
    (44, "我们的竞争对手主要是Salesforce和纷享销客", {"profile": True, "preferences": False, "agent_rules": False, "entities": False}),
    (45, "我的KPI是季度营收增长20%", {"profile": True, "preferences": False, "agent_rules": False, "entities": False}),
    (46, "我在这个公司工作了5年", {"profile": True, "preferences": False, "agent_rules": False, "entities": False}),
    (47, "我们团队有20人，分3个小组", {"profile": True, "preferences": False, "agent_rules": False, "entities": False}),
    (48, "我是产品经理，负责CRM模块", {"profile": True, "preferences": False, "agent_rules": False, "entities": False}),
    (49, "我们公司是做企业软件的", {"profile": True, "preferences": False, "agent_rules": False, "entities": False}),
    (50, "我叫张明，大家叫我老张", {"profile": True, "preferences": False, "agent_rules": False, "entities": False}),
    (51, "我主要负责华北区的业务", {"profile": True, "preferences": False, "agent_rules": False, "entities": False}),
    (52, "我们部门今年的目标是3000万", {"profile": True, "preferences": False, "agent_rules": False, "entities": False}),
    (53, "我是技术出身，后来转做销售管理", {"profile": True, "preferences": False, "agent_rules": False, "entities": False}),
    (54, "我们公司在深圳，客户主要在珠三角", {"profile": True, "preferences": False, "agent_rules": False, "entities": False}),
    (55, "我带的团队主要做中大型客户", {"profile": True, "preferences": False, "agent_rules": False, "entities": False}),

    # ── 56-75: entities（应提取）──
    (56, "华为的张伟说话很直接，开会不要绕弯子", {"entities": True, "preferences": False, "agent_rules": False, "profile": False}),
    (57, "华为内部审批流程复杂，至少要3-4周", {"entities": True, "preferences": False, "agent_rules": False, "profile": False}),
    (58, "泰克科技的张总负责采购决策，李经理负责技术评估", {"entities": True, "preferences": False, "agent_rules": False, "profile": False}),
    (59, "腾讯云那边的项目已经进入POC阶段了", {"entities": True, "preferences": False, "agent_rules": False, "profile": False}),
    (60, "张伟比较看重产品的稳定性，对价格不太敏感", {"entities": True, "preferences": False, "agent_rules": False, "profile": False}),
    (61, "华为那边的合同下个月到期，需要提前续约", {"entities": True, "preferences": False, "agent_rules": False, "profile": False}),
    (62, "泰克科技是一家汽车零部件供应商", {"entities": True, "preferences": False, "agent_rules": False, "profile": False}),
    (63, "李娜是华为CRM项目的技术负责人", {"entities": True, "preferences": False, "agent_rules": False, "profile": False}),
    (64, "这个客户之前用的是竞品的方案，切换成本比较高", {"entities": True, "preferences": False, "agent_rules": False, "profile": False}),
    (65, "华为内部有三个部门在用我们的产品", {"entities": True, "preferences": False, "agent_rules": False, "profile": False}),
    (66, "张总喜欢看PPT，汇报材料要做得精美", {"entities": True, "preferences": False, "agent_rules": False, "profile": False}),
    (67, "腾讯那边的决策链比较长，需要过三级审批", {"entities": True, "preferences": False, "agent_rules": False, "profile": False}),
    (68, "客户反馈我们的响应速度比竞品快", {"entities": True, "preferences": False, "agent_rules": False, "profile": False}),
    (69, "华为的王总很注重细节", {"entities": True, "preferences": False, "agent_rules": False, "profile": False}),
    (70, "泰克科技去年换了新的CTO", {"entities": True, "preferences": False, "agent_rules": False, "profile": False}),
    (71, "百度那边的预算已经批下来了", {"entities": True, "preferences": False, "agent_rules": False, "profile": False}),
    (72, "阿里的项目负责人是刘总", {"entities": True, "preferences": False, "agent_rules": False, "profile": False}),
    (73, "字节跳动内部在评估三家供应商", {"entities": True, "preferences": False, "agent_rules": False, "profile": False}),
    (74, "美团那边对接口性能要求很高", {"entities": True, "preferences": False, "agent_rules": False, "profile": False}),
    (75, "京东的采购流程比较规范，需要走招标", {"entities": True, "preferences": False, "agent_rules": False, "profile": False}),

    # ── 76-90: 不提取（操作指令/短语/查询）──
    (76, "帮我查一下华为的商机", {"agent_rules": False, "preferences": False, "profile": False, "entities": False}),
    (77, "帮我把这个客户标记为重点", {"agent_rules": False, "preferences": False, "profile": False, "entities": False}),
    (78, "好的，明白了", {"agent_rules": False, "preferences": False, "profile": False, "entities": False}),
    (79, "帮我创建一个新的商机", {"agent_rules": False, "preferences": False, "profile": False, "entities": False}),
    (80, "把刚才的分析结果导出为Excel", {"agent_rules": False, "preferences": False, "profile": False, "entities": False}),
    (81, "谢谢", {"agent_rules": False, "preferences": False, "profile": False, "entities": False}),
    (82, "查一下上个月的销售数据", {"agent_rules": False, "preferences": False, "profile": False, "entities": False}),
    (83, "帮我发一封邮件给张总", {"agent_rules": False, "preferences": False, "profile": False, "entities": False}),
    (84, "刷新一下数据", {"agent_rules": False, "preferences": False, "profile": False, "entities": False}),
    (85, "继续", {"agent_rules": False, "preferences": False, "profile": False, "entities": False}),
    (86, "帮我统计一下本周新增客户数", {"agent_rules": False, "preferences": False, "profile": False, "entities": False}),
    (87, "把这个商机的阶段改成谈判中", {"agent_rules": False, "preferences": False, "profile": False, "entities": False}),
    (88, "帮我看看有没有逾期的跟进任务", {"agent_rules": False, "preferences": False, "profile": False, "entities": False}),
    (89, "对", {"agent_rules": False, "preferences": False, "profile": False, "entities": False}),
    (90, "帮我生成一份客户拜访计划", {"agent_rules": False, "preferences": False, "profile": False, "entities": False}),

    # ── 91-100: 混合输入（多维度同时提取）──
    (91, "你要专注金融行业分析，我们公司主要做金融客户", {"agent_rules": True, "profile": True, "preferences": False, "entities": False}),
    (92, "我是产品经理，我喜欢用思维导图整理需求", {"profile": True, "preferences": True, "agent_rules": False, "entities": False}),
    (93, "你要用markdown格式输出，我们团队有20人", {"agent_rules": True, "profile": True, "preferences": False, "entities": False}),
    (94, "华为的张总很注重细节，你跟他沟通要准备充分", {"entities": True, "agent_rules": False, "preferences": False, "profile": False}),
    (95, "我负责华北区，我喜欢每天早上看数据", {"profile": True, "preferences": True, "agent_rules": False, "entities": False}),
    (96, "你回复要简洁，腾讯那边项目进展顺利", {"agent_rules": True, "entities": True, "preferences": False, "profile": False}),
    (97, "我是销售总监，你要帮我跟踪重点客户", {"profile": True, "agent_rules": True, "preferences": False, "entities": False}),
    (98, "我习惯用表格看数据，华为的李总偏好PPT", {"preferences": True, "entities": True, "agent_rules": False, "profile": False}),
    (99, "我们公司做SaaS，我偏好看月度趋势", {"profile": True, "preferences": True, "agent_rules": False, "entities": False}),
    (100, "你不要用太多专业术语，百度那边的项目快签约了", {"agent_rules": True, "entities": True, "preferences": False, "profile": False}),
]

PROMPTS = {
    "profile": (PROFILE_EXTRACT_PROMPT, {"existing_profile": "（无）", "user_messages": None, "output_language": "auto"}, "user_messages"),
    "preferences": (PREFERENCES_EXTRACT_PROMPT, {"user_messages": None, "output_language": "auto"}, "user_messages"),
    "agent_rules": (AGENT_RULES_EXTRACT_PROMPT, {"existing_rules": "（无）", "user_messages": None, "output_language": "auto"}, "user_messages"),
    "entities": (ENTITIES_EXTRACT_PROMPT, {"existing_entities": "（无）", "conversation": None, "output_language": "auto"}, "conversation"),
}

def has_extraction(content: str, dim: str) -> bool:
    try:
        if "{" not in content:
            return False
        data = json.loads(content[content.index("{"):content.rindex("}")+1])
        if dim == "profile":
            return bool(data.get("profile", {}).get("content", ""))
        elif dim == "preferences":
            return len(data.get("preferences", [])) > 0
        elif dim == "agent_rules":
            return bool(data.get("agent_rules", {}).get("content", ""))
        elif dim == "entities":
            return len(data.get("entities", [])) > 0
    except:
        pass
    return False

async def test_case(case_id, text, expects):
    results = {}
    for dim, (prompt_tpl, params, input_field) in PROMPTS.items():
        if dim not in expects:
            continue
        p = dict(params)
        p[input_field] = f"[human]: {text}"
        prompt = prompt_tpl.format(**p)
        try:
            resp = await llm.ainvoke(prompt)
            extracted = has_extraction(resp.content, dim)
        except Exception as e:
            extracted = None
        expected = expects[dim]
        results[dim] = (extracted == expected, extracted, expected)
    return results

async def main():
    total_checks = 0
    total_passed = 0
    failures = []

    for case_id, text, expects in CASES:
        results = await test_case(case_id, text, expects)
        all_pass = all(p for p, _, _ in results.values())
        for dim, (passed, actual, expected) in results.items():
            total_checks += 1
            if passed:
                total_passed += 1
            else:
                failures.append((case_id, dim, expected, actual, text[:35]))
        if not all_pass:
            failed_dims = [d for d, (p, _, _) in results.items() if not p]
            print(f"FAIL case {case_id:3d}: {failed_dims} | {text[:40]}")

    print(f"\n{'='*60}")
    print(f"Total: {total_passed}/{total_checks} passed ({total_passed/total_checks*100:.1f}%)")
    print(f"Cases: {100 - len(set(f[0] for f in failures))}/100 fully passed")
    if failures:
        print(f"\nFailures ({len(failures)}):")
        for cid, dim, exp, act, txt in failures[:20]:
            print(f"  case {cid:3d} {dim:12s}: expect={'Y' if exp else 'N'} actual={'Y' if act else 'N'} | {txt}")

if __name__ == "__main__":
    asyncio.run(main())
