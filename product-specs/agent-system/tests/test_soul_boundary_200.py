"""200 场景验证 soul / profile / preferences 边界
分 4 批运行，每批 50 条。
运行: .venv/bin/python -B tests/test_soul_boundary_200.py --batch 1
"""
import asyncio, os, sys, json, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("DEEPSEEK_API_KEY", "sk-HdY98AcN68JhtXLp8oeIATEL4PWq9rzRcCAhI8G4SOtBbtSw")

CASES = [
    # ── soul: 角色定义 (1-20) ──
    (1, "soul", "你是我的数据分析助理"),
    (2, "soul", "你是一个专业的CRM顾问"),
    (3, "soul", "以后你就是我的销售教练"),
    (4, "soul", "你的角色是技术架构师"),
    (5, "soul", "你现在是我的客户成功经理"),
    (6, "soul", "从现在起你是我的市场分析师"),
    (7, "soul", "你就当自己是一个资深销售顾问"),
    (8, "soul", "你是帮我管理客户关系的AI助手"),
    (9, "soul", "你是我们团队的智能运营助理"),
    (10, "soul", "你要做我的合同审核助手"),
    (11, "soul", "你是专门帮我做竞品分析的助理"),
    (12, "soul", "你是我的日程管理和会议助理"),
    (13, "soul", "你是一个能帮我写周报的智能助理"),
    (14, "soul", "你是我在华东区的销售数据分析师"),
    (15, "soul", "以后你扮演我的投标顾问"),
    (16, "soul", "你是一个懂SaaS行业的售前顾问"),
    (17, "soul", "你的身份是我的客户回访专员"),
    (18, "soul", "以后就把你当作我的报价助手来用"),
    (19, "soul", "你现在的角色是渠道管理顾问"),
    (20, "soul", "把你自己定位成我的私人商务助理"),
    # ── soul: 行为约束 (21-40) ──
    (21, "soul", "你回复不要超过100字"),
    (22, "soul", "你不要主动推荐产品"),
    (23, "soul", "你每次回答前先确认我的需求"),
    (24, "soul", "你要优先处理紧急客户的问题"),
    (25, "soul", "你回复客户问题时要附上数据来源"),
    (26, "soul", "你不要在没有确认的情况下修改客户标签"),
    (27, "soul", "你给我建议的时候要给出至少三个方案"),
    (28, "soul", "你分析数据的时候要同时给出同比和环比"),
    (29, "soul", "你不要用太专业的术语，我团队里有新人"),
    (30, "soul", "你提到金额的时候统一用万元为单位"),
    (31, "soul", "你不要自动发送邮件，先让我确认内容"),
    (32, "soul", "你每次给我汇报时要按优先级排序"),
    (33, "soul", "你不要重复提醒我已经处理过的事项"),
    (34, "soul", "你回复的时候要区分事实和你的推测"),
    (35, "soul", "你帮我写邮件的时候要用正式的商务语气"),
    (36, "soul", "你做预测分析时要给出置信度"),
    (37, "soul", "你不要在客户面前暴露我们的内部策略"),
    (38, "soul", "你处理客户投诉时要先表达理解再给方案"),
    (39, "soul", "你不要编造数据，不确定就说不知道"),
    (40, "soul", "你不要替我做决定，只给建议"),
    # ── soul: 输出格式 (41-55) ──
    (41, "soul", "你给我的分析报告要有图表建议"),
    (42, "soul", "你输出的客户列表要按成交概率排序"),
    (43, "soul", "你给我的周报要包含本周新增线索数"),
    (44, "soul", "你做的竞品分析要用对比表格的形式"),
    (45, "soul", "你给我的客户画像要包含行业、规模、决策链"),
    (46, "soul", "你写的会议纪要要分为决议事项和待办事项两部分"),
    (47, "soul", "你给我的销售预测要用表格加趋势说明"),
    (48, "soul", "你回复我的时候要用markdown格式"),
    (49, "soul", "你做的方案要有目录和摘要"),
    (50, "soul", "你给我的数据分析结果要附上原始数据链接"),
    (51, "soul", "你帮我整理的客户跟进记录要按时间倒序"),
    (52, "soul", "你给我的报价单要包含有效期和付款条件"),
    (53, "soul", "你输出的内容要有清晰的标题和小标题"),
    (54, "soul", "你给我的日报要控制在一页A4纸以内"),
    (55, "soul", "你输出的所有表格都要有合计行"),
    # ── soul: 沟通风格 (56-70) ──
    (56, "soul", "你说话要专业一点，像咨询顾问"),
    (57, "soul", "你跟我说话可以随意一点，不用太正式"),
    (58, "soul", "你回复要简洁有力，不要啰嗦"),
    (59, "soul", "你要用数据说话，少用形容词"),
    (60, "soul", "你说话要有亲和力，像朋友一样"),
    (61, "soul", "你要用结构化的方式表达，先结论后论据"),
    (62, "soul", "你回复客户的语气要温和但坚定"),
    (63, "soul", "你要像一个老销售一样跟我聊，接地气一点"),
    (64, "soul", "你给客户写邮件要用敬语，体现尊重"),
    (65, "soul", "你分析问题的时候要客观中立"),
    (66, "soul", "你要用比喻和类比来解释复杂概念"),
    (67, "soul", "你跟我汇报工作要像给老板汇报一样，重点突出"),
    (68, "soul", "你说话要直接，不要绕弯子"),
    (69, "soul", "你要像教练一样引导我思考，不要直接给答案"),
    (70, "soul", "你回复要有逻辑层次，用1234列出来"),
    # ── soul: 工作流程+领域+禁止 (71-100) ──
    (71, "soul", "你每次分析客户先给我一个总结，我确认后再给详细数据"),
    (72, "soul", "你帮我写方案的流程是：先列大纲，我确认后再写正文"),
    (73, "soul", "你收到新线索后先做背景调查再分配给销售"),
    (74, "soul", "你帮我做客户拜访准备：先查历史记录，再列谈话要点"),
    (75, "soul", "你要专注于金融行业的客户分析"),
    (76, "soul", "你要熟悉SaaS产品的销售流程"),
    (77, "soul", "你需要了解医疗器械行业的合规要求"),
    (78, "soul", "你要精通制造业的供应链管理"),
    (79, "soul", "你的专业方向是教育行业的B端销售"),
    (80, "soul", "你要懂得房地产行业的客户开发策略"),
    (81, "soul", "你不要把A客户的信息透露给B客户"),
    (82, "soul", "你不要在没有我授权的情况下联系客户"),
    (83, "soul", "你不要给客户承诺我们做不到的功能"),
    (84, "soul", "你不要修改已经发给客户的报价"),
    (85, "soul", "你不要删除任何客户的历史记录"),
    (86, "soul", "你不要对客户的财务数据做主观评价"),
    (87, "soul", "你不要擅自给客户打折，折扣需要我审批"),
    (88, "soul", "你不要在非工作时间打扰客户"),
    (89, "soul", "你不要跳过审批流程直接执行操作"),
    (90, "soul", "你不要在季度末为了冲业绩给客户过度承诺"),
    (91, "soul", "你每天下班前帮我总结今天的工作进展和明天的计划"),
    (92, "soul", "你在我开会前15分钟提醒我，并准备好相关资料摘要"),
    (93, "soul", "你帮我做客户分层：先按营收分，再按活跃度分"),
    (94, "soul", "你做市场调研要按这个顺序：行业趋势、竞品动态、客户反馈"),
    (95, "soul", "你每个季度末帮我做一次客户满意度回顾"),
    (96, "soul", "你要专注于政企客户的大客户销售"),
    (97, "soul", "你需要掌握跨境电商的运营知识"),
    (98, "soul", "你要了解汽车行业的经销商管理模式"),
    (99, "soul", "你的知识范围要覆盖快消品行业的渠道管理"),
    (100, "soul", "你要熟悉互联网广告行业的投放策略"),
    # ── profile (101-130) ──
    (101, "profile", "我是华东区销售总监"),
    (102, "profile", "我管理15人的销售团队"),
    (103, "profile", "我负责互联网和金融行业的大客户"),
    (104, "profile", "我在这个公司工作了8年"),
    (105, "profile", "我是技术出身，后来转做销售管理"),
    (106, "profile", "我的KPI是季度营收增长20%"),
    (107, "profile", "我们公司是做企业软件的"),
    (108, "profile", "我负责华南区的制造业客户"),
    (109, "profile", "我的团队有8个人，分管不同区域"),
    (110, "profile", "我之前在Oracle工作过"),
    (111, "profile", "我是产品经理，负责CRM产品线"),
    (112, "profile", "我在深圳办公，经常出差到北京"),
    (113, "profile", "我是新来的，刚接手这个区域"),
    (114, "profile", "我同时负责售前和售后"),
    (115, "profile", "我的直属上级是销售VP"),
    (116, "profile", "我是华北区的渠道经理"),
    (117, "profile", "我负责公司最大的三个客户"),
    (118, "profile", "我的背景是计算机专业"),
    (119, "profile", "我在销售岗位做了10年"),
    (120, "profile", "我们团队今年的目标是3000万"),
    (121, "profile", "我是客户成功部门的负责人"),
    (122, "profile", "我管理的客户有200多个"),
    (123, "profile", "我主要做政府和央企的项目"),
    (124, "profile", "我是合伙人级别，负责战略客户"),
    (125, "profile", "我的专长是大客户谈判"),
    (126, "profile", "我们部门有30人，分成4个小组"),
    (127, "profile", "我负责公司在东南亚的业务"),
    (128, "profile", "我是从竞争对手那边跳过来的"),
    (129, "profile", "我同时兼任培训讲师"),
    (130, "profile", "我的年度预算是500万"),
    # ── preferences (131-160) ──
    (131, "preferences", "我喜欢表格展示数据"),
    (132, "preferences", "我习惯每天早上看数据报表"),
    (133, "preferences", "我不喜欢长篇大论的报告"),
    (134, "preferences", "我偏好用折线图看趋势"),
    (135, "preferences", "我喜欢简洁的回复风格"),
    (136, "preferences", "我习惯用万元为单位看金额"),
    (137, "preferences", "我不喜欢太多专业术语"),
    (138, "preferences", "我喜欢先看结论再看过程"),
    (139, "preferences", "我习惯每周五下午写周报"),
    (140, "preferences", "我偏好中文沟通"),
    (141, "preferences", "我喜欢用饼图看占比"),
    (142, "preferences", "我习惯按客户规模排序"),
    (143, "preferences", "我不喜欢弹窗提醒"),
    (144, "preferences", "我喜欢邮件沟通胜过即时消息"),
    (145, "preferences", "我习惯看季度对比数据"),
    (146, "preferences", "我偏好深色主题的界面"),
    (147, "preferences", "我喜欢数据导出为Excel格式"),
    (148, "preferences", "我习惯每月初做上月复盘"),
    (149, "preferences", "我不喜欢自动推送通知"),
    (150, "preferences", "我喜欢按行业分类查看客户"),
    (151, "preferences", "我习惯用手机看简报"),
    (152, "preferences", "我偏好柱状图看对比"),
    (153, "preferences", "我喜欢一页纸的摘要"),
    (154, "preferences", "我习惯按成交概率排序商机"),
    (155, "preferences", "我不喜欢太花哨的图表"),
    (156, "preferences", "我喜欢看同比增长率"),
    (157, "preferences", "我习惯每天下班前看一次待办"),
    (158, "preferences", "我偏好用钉钉沟通"),
    (159, "preferences", "我喜欢数据精确到小数点后两位"),
    (160, "preferences", "我习惯按时间线查看客户活动"),
    # ── 混淆场景: soul vs preferences (161-180) ──
    (161, "soul", "你给我用表格展示数据"),
    (162, "preferences", "我喜欢表格展示数据"),
    (163, "soul", "你回复要简洁"),
    (164, "preferences", "我喜欢简洁的回复"),
    (165, "soul", "你不要超过100字"),
    (166, "preferences", "我不喜欢长篇大论"),
    (167, "soul", "你用中文回复"),
    (168, "preferences", "我偏好中文沟通"),
    (169, "soul", "你给我的报告要有图表"),
    (170, "preferences", "我喜欢看图表"),
    (171, "soul", "你按优先级排序"),
    (172, "preferences", "我习惯按优先级看"),
    (173, "soul", "你先给结论再给过程"),
    (174, "preferences", "我喜欢先看结论"),
    (175, "soul", "你用markdown格式回复"),
    (176, "preferences", "我喜欢markdown格式"),
    (177, "soul", "你给我导出Excel"),
    (178, "preferences", "我喜欢Excel格式"),
    (179, "soul", "你每天早上给我推送报表"),
    (180, "preferences", "我习惯每天早上看报表"),
    # ── 混淆场景: soul vs profile (181-200) ──
    (181, "soul", "你是我的销售助理"),
    (182, "profile", "我是销售总监"),
    (183, "soul", "你要专注金融行业"),
    (184, "profile", "我负责金融行业"),
    (185, "soul", "你要熟悉制造业"),
    (186, "profile", "我在制造业工作了10年"),
    (187, "soul", "你是我的技术顾问"),
    (188, "profile", "我是技术出身"),
    (189, "soul", "你要管理我的客户关系"),
    (190, "profile", "我管理200个客户"),
    (191, "soul", "你要帮我做数据分析"),
    (192, "profile", "我的专长是数据分析"),
    (193, "soul", "你是我团队的AI助手"),
    (194, "profile", "我的团队有15人"),
    (195, "soul", "你要了解政企客户"),
    (196, "profile", "我主要做政企项目"),
    (197, "soul", "你要支持多语言"),
    (198, "profile", "我负责海外业务"),
    (199, "soul", "你是我的战略规划助手"),
    (200, "profile", "我是合伙人级别"),
]

async def run_batch(batch_num, batch_size=50):
    from langchain_core.messages import HumanMessage, AIMessage
    from langchain_openai import ChatOpenAI
    from src.memory.viking_engine import VikingMemoryEngine
    
    llm = ChatOpenAI(model="deepseek-v4-flash", api_key=os.environ["DEEPSEEK_API_KEY"],
                     base_url="https://tokenhub.tencentmaas.com/v1", max_tokens=2048)
    e = VikingMemoryEngine(vdb_url="http://10.60.2.17", vdb_key="bRG3NETg13tv5Fn68VTdkxaJXH9tMQzhKeT3unck",
                           database_name="viking_boundary_200", collection_name=f"boundary_b{batch_num}",
                           llm=llm, use_pg=False)
    
    start_idx = (batch_num - 1) * batch_size
    end_idx = min(start_idx + batch_size, len(CASES))
    batch = CASES[start_idx:end_idx]
    
    passed, failed, errors = 0, 0, []
    for num, expect, text in batch:
        reply = "好的。" if expect == "soul" else "了解。" if expect == "profile" else "好的。"
        r = await e.extract_and_update(
            [HumanMessage(content=text), AIMessage(content=reply)],
            thread_id=f"b{batch_num}-{num}", user_id=f"b{batch_num}_user",
        )
        cats = [item.metadata.get("category") for item in r.items]
        hit = expect in cats
        if hit:
            passed += 1
        else:
            failed += 1
            errors.append({"num": num, "expect": expect, "actual": cats or ["空"], "input": text})
        
        status = "PASS" if hit else "FAIL"
        actual = cats[0] if cats else "空"
        print(f"  [{status}] #{num:>3} 期望:{expect:<12} 实际:{actual:<12} {text[:35]}")
        await asyncio.sleep(0.3)
    
    print(f"\n  批次 {batch_num} 结果: {passed}/{len(batch)} 通过")
    if errors:
        print(f"  失败 {len(errors)} 条:")
        for e in errors[:10]:
            print(f"    #{e['num']} 期望{e['expect']} 实际{e['actual']} {e['input'][:30]}")
    return passed, failed, errors

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--batch", type=int, default=1, help="Batch number 1-4")
    args = parser.parse_args()
    asyncio.run(run_batch(args.batch))