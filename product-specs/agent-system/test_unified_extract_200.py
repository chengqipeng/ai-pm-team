"""UNIFIED_EXTRACT_PROMPT v3 验证脚本 - 200条四维度记忆提取测试用例

使用统一单次提取 prompt（UNIFIED_EXTRACT_PROMPT）对全部 200 条用例进行验证。
每条用例仅调用 1 次 LLM，验证四维度提取归属准确性。

使用方法：
    python test_unified_extract_200.py              # 跑全部 200 条
    python test_unified_extract_200.py --batch A    # 跑指定批次
    python test_unified_extract_200.py --range 161-200  # 跑指定范围
    python test_unified_extract_200.py --concurrency 3  # 并发控制
"""
import argparse
import asyncio
import json
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent / ".env")
sys.path.insert(0, os.path.dirname(__file__))
from src.memory.extraction.prompts import UNIFIED_EXTRACT_PROMPT


@dataclass
class TestCase:
    id: int
    input: str
    expect: dict
    batch: str
    note: str = ""


TEST_CASES = [
    # A. Profile 正例 (#1~#25)
    TestCase(1, "在这个行业干了十年了，从技术转管理", {"profile": True, "preferences": False, "agent_rules": False, "entities": False}, "A"),
    TestCase(2, "团队刚扩到20人，压力挺大的", {"profile": True, "preferences": False, "agent_rules": False, "entities": False}, "A"),
    TestCase(3, "之前在阿里做过3年，后来跳到现在这家", {"profile": True, "preferences": False, "agent_rules": False, "entities": False}, "A"),
    TestCase(4, "华南区的客户都归我管", {"profile": True, "preferences": False, "agent_rules": False, "entities": False}, "A"),
    TestCase(5, "我不再负责华东区了，上个月调到华南", {"profile": True, "preferences": False, "agent_rules": False, "entities": False}, "A"),
    TestCase(6, "既是产品经理也兼任售前，忙得要死", {"profile": True, "preferences": False, "agent_rules": False, "entities": False}, "A"),
    TestCase(7, "说实话我就是个打杂的，什么都管", {"profile": True, "preferences": False, "agent_rules": False, "entities": False}, "A"),
    TestCase(8, "我们是做ToB SaaS的，客户主要是中大型企业", {"profile": True, "preferences": False, "agent_rules": False, "entities": False}, "A"),
    TestCase(9, "今年KPI是3000万，去年完成了2800", {"profile": True, "preferences": False, "agent_rules": False, "entities": False}, "A"),
    TestCase(10, "负责的客户有200多个，大部分是金融行业", {"profile": True, "preferences": False, "agent_rules": False, "entities": False}, "A"),
    TestCase(11, "刚来三个月，还在熟悉业务", {"profile": True, "preferences": False, "agent_rules": False, "entities": False}, "A"),
    TestCase(12, "我老板是销售VP，他让我重点盯互联网客户", {"profile": True, "preferences": False, "agent_rules": False, "entities": False}, "A"),
    TestCase(13, "我们部门不加班，文化比较宽松", {"profile": True, "preferences": False, "agent_rules": False, "entities": False}, "A"),
    TestCase(14, "公司总部在深圳，北京是分公司", {"profile": True, "preferences": False, "agent_rules": False, "entities": False}, "A"),
    TestCase(15, "我们团队都用飞书协作", {"profile": True, "preferences": False, "agent_rules": False, "entities": False}, "A"),
    TestCase(16, "我手下有3个SDR，2个AE", {"profile": True, "preferences": False, "agent_rules": False, "entities": False}, "A"),
    TestCase(17, "我是技术出身，后来转做售前", {"profile": True, "preferences": False, "agent_rules": False, "entities": False}, "A"),
    TestCase(18, "我们公司去年融了B轮，估值3个亿", {"profile": True, "preferences": False, "agent_rules": False, "entities": False}, "A"),
    TestCase(19, "我的客户主要集中在长三角地区", {"profile": True, "preferences": False, "agent_rules": False, "entities": False}, "A"),
    TestCase(20, "我们产品客单价在50-200万之间", {"profile": True, "preferences": False, "agent_rules": False, "entities": False}, "A"),
    TestCase(21, "我是今年1月入职的，之前在Oracle", {"profile": True, "preferences": False, "agent_rules": False, "entities": False}, "A"),
    TestCase(22, "我们公司的优势是响应速度快", {"profile": True, "preferences": False, "agent_rules": False, "entities": False}, "A"),
    TestCase(23, "我直接向CEO汇报", {"profile": True, "preferences": False, "agent_rules": False, "entities": False}, "A"),
    TestCase(24, "我们部门今年的目标是签10个大客户", {"profile": True, "preferences": False, "agent_rules": False, "entities": False}, "A"),
    TestCase(25, "我同时负责新签和续约两条线", {"profile": True, "preferences": False, "agent_rules": False, "entities": False}, "A"),
    # B. Preferences 正例 (#26~#50)
    TestCase(26, "每次你给我的报告我都跳过前面直接看结论", {"profile": False, "preferences": True, "agent_rules": False, "entities": False}, "B"),
    TestCase(27, "那种密密麻麻的表格我根本看不下去", {"profile": False, "preferences": True, "agent_rules": False, "entities": False}, "B"),
    TestCase(28, "大客户我一般亲自跟，小客户让团队处理", {"profile": False, "preferences": True, "agent_rules": False, "entities": False}, "B"),
    TestCase(29, "受不了那种啰嗦的回复，直接说重点就行", {"profile": False, "preferences": True, "agent_rules": False, "entities": False}, "B"),
    TestCase(30, "数据嘛，能用图就别用表，一目了然", {"profile": False, "preferences": True, "agent_rules": False, "entities": False}, "B"),
    TestCase(31, "周五下午我一般不安排客户拜访", {"profile": False, "preferences": True, "agent_rules": False, "entities": False}, "B"),
    TestCase(32, "如果是紧急的事情微信说，不急的发邮件", {"profile": False, "preferences": True, "agent_rules": False, "entities": False}, "B"),
    TestCase(33, "我对数据精度要求高，小数点后两位", {"profile": False, "preferences": True, "agent_rules": False, "entities": False}, "B"),
    TestCase(34, "看报表的时候我更在意同比，环比参考就行", {"profile": False, "preferences": True, "agent_rules": False, "entities": False}, "B"),
    TestCase(35, "别给我发那种长报告，一页纸搞定最好", {"profile": False, "preferences": True, "agent_rules": False, "entities": False}, "B"),
    TestCase(36, "我这个人比较视觉化，文字太多就头疼", {"profile": False, "preferences": True, "agent_rules": False, "entities": False}, "B"),
    TestCase(37, "早上9点前别给我推消息，那时候在开晨会", {"profile": False, "preferences": True, "agent_rules": False, "entities": False}, "B"),
    TestCase(38, "我喜欢用图表展示重要数据，辅助数据用表格", {"profile": False, "preferences": True, "agent_rules": False, "entities": False}, "B"),
    TestCase(39, "我习惯每天早上先看数据看板", {"profile": False, "preferences": True, "agent_rules": False, "entities": False}, "B"),
    TestCase(40, "我比较在意客户的反馈速度", {"profile": False, "preferences": True, "agent_rules": False, "entities": False}, "B"),
    TestCase(41, "我一般不加班，效率优先", {"profile": False, "preferences": True, "agent_rules": False, "entities": False}, "B"),
    TestCase(42, "我讨厌开没有议程的会", {"profile": False, "preferences": True, "agent_rules": False, "entities": False}, "B"),
    TestCase(43, "我倾向于先打电话再发邮件确认", {"profile": False, "preferences": True, "agent_rules": False, "entities": False}, "B"),
    TestCase(44, "我觉得有对比的数据更好理解", {"profile": False, "preferences": True, "agent_rules": False, "entities": False}, "B"),
    TestCase(45, "我喜欢用飞书沟通，微信太杂了", {"profile": False, "preferences": True, "agent_rules": False, "entities": False}, "B"),
    TestCase(46, "我看东西比较快，信息密度高一点没关系", {"profile": False, "preferences": True, "agent_rules": False, "entities": False}, "B"),
    TestCase(47, "我不太喜欢被动等消息，有进展主动告诉我", {"profile": False, "preferences": True, "agent_rules": False, "entities": False}, "B"),
    TestCase(48, "我习惯周一开会定本周计划", {"profile": False, "preferences": True, "agent_rules": False, "entities": False}, "B"),
    TestCase(49, "我更关注转化率而不是线索数量", {"profile": False, "preferences": True, "agent_rules": False, "entities": False}, "B"),
    TestCase(50, "我烦那种没有结论的分析，看完不知道该干嘛", {"profile": False, "preferences": True, "agent_rules": False, "entities": False}, "B"),
]

TEST_CASES += [
    # C. Agent Rules 正例 (#51~#75)
    TestCase(51, "你是我的销售数据分析助理", {"profile": False, "preferences": False, "agent_rules": True, "entities": False}, "C"),
    TestCase(52, "你回复不要超过100字", {"profile": False, "preferences": False, "agent_rules": True, "entities": False}, "C"),
    TestCase(53, "分析报告要包含同比环比数据", {"profile": False, "preferences": False, "agent_rules": True, "entities": False}, "C"),
    TestCase(54, "回复控制在100字以内", {"profile": False, "preferences": False, "agent_rules": True, "entities": False}, "C"),
    TestCase(55, "以后查数据的时候自动加上时间范围", {"profile": False, "preferences": False, "agent_rules": True, "entities": False}, "C"),
    TestCase(56, "取消之前不超过200字的限制", {"profile": False, "preferences": False, "agent_rules": True, "entities": False}, "C"),
    TestCase(57, "跟客户沟通的邮件要用正式语气", {"profile": False, "preferences": False, "agent_rules": True, "entities": False}, "C"),
    TestCase(58, "重要客户的分析要单独出一份详细报告", {"profile": False, "preferences": False, "agent_rules": True, "entities": False}, "C"),
    TestCase(59, "不要自动发邮件，先让我过目", {"profile": False, "preferences": False, "agent_rules": True, "entities": False}, "C"),
    TestCase(60, "每次给我建议的时候列出pros和cons", {"profile": False, "preferences": False, "agent_rules": True, "entities": False}, "C"),
    TestCase(61, "上次那个分析太浅了，以后要深入一些", {"profile": False, "preferences": False, "agent_rules": True, "entities": False}, "C"),
    TestCase(62, "客户数据不要对外分享，内部使用", {"profile": False, "preferences": False, "agent_rules": True, "entities": False}, "C"),
    TestCase(63, "先确认需求再动手，别自作主张", {"profile": False, "preferences": False, "agent_rules": True, "entities": False}, "C"),
    TestCase(64, "你要专注于金融行业的客户分析", {"profile": False, "preferences": False, "agent_rules": True, "entities": False}, "C"),
    TestCase(65, "你每次回答前先确认我的需求", {"profile": False, "preferences": False, "agent_rules": True, "entities": False}, "C"),
    TestCase(66, "你给我建议的时候要给出至少三个方案", {"profile": False, "preferences": False, "agent_rules": True, "entities": False}, "C"),
    TestCase(67, "你不要编造数据，不确定就说不知道", {"profile": False, "preferences": False, "agent_rules": True, "entities": False}, "C"),
    TestCase(68, "你帮我写邮件的时候要用正式的商务语气", {"profile": False, "preferences": False, "agent_rules": True, "entities": False}, "C"),
    TestCase(69, "你做预测分析时要给出置信度", {"profile": False, "preferences": False, "agent_rules": True, "entities": False}, "C"),
    TestCase(70, "金额统一用万元为单位", {"profile": False, "preferences": False, "agent_rules": True, "entities": False}, "C"),
    TestCase(71, "你就像我的私人助理一样", {"profile": False, "preferences": False, "agent_rules": True, "entities": False}, "C"),
    TestCase(72, "之前让你用表格，现在改成图表", {"profile": False, "preferences": False, "agent_rules": True, "entities": False}, "C"),
    TestCase(73, "你现在可以自动发邮件了，不用每次都问我", {"profile": False, "preferences": False, "agent_rules": True, "entities": False}, "C"),
    TestCase(74, "你的跟进节奏改一下，从3/7/14天改成1/3/7天", {"profile": False, "preferences": False, "agent_rules": True, "entities": False}, "C"),
    TestCase(75, "你说话要结构化，先结论后论据", {"profile": False, "preferences": False, "agent_rules": True, "entities": False}, "C"),
    # D. Entities 正例 (#76~#100)
    TestCase(76, "华为的张伟说话很直接，开会不要绕弯子", {"profile": False, "preferences": False, "agent_rules": False, "entities": True}, "D"),
    TestCase(77, "张总那边最近在忙重组，估计这个月没空", {"profile": False, "preferences": False, "agent_rules": False, "entities": True}, "D"),
    TestCase(78, "华为和腾讯都在评估我们的方案，但侧重点不同", {"profile": False, "preferences": False, "agent_rules": False, "entities": True}, "D"),
    TestCase(79, "我觉得这个客户不太靠谱，拖了三个月了", {"profile": False, "preferences": False, "agent_rules": False, "entities": True}, "D"),
    TestCase(80, "听说他们内部在打架，技术部和采购部意见不一致", {"profile": False, "preferences": False, "agent_rules": False, "entities": True}, "D"),
    TestCase(81, "王强这个人吧，表面热情但决策很慢", {"profile": False, "preferences": False, "agent_rules": False, "entities": True}, "D"),
    TestCase(82, "泰克科技去年营收5个亿，今年目标8个亿", {"profile": False, "preferences": False, "agent_rules": False, "entities": True}, "D"),
    TestCase(83, "那个项目其实是张伟在推，李娜只是挂名", {"profile": False, "preferences": False, "agent_rules": False, "entities": True}, "D"),
    TestCase(84, "比亚迪的预算审批要过五关斩六将", {"profile": False, "preferences": False, "agent_rules": False, "entities": True}, "D"),
    TestCase(85, "陈刚私下说基本定了选我们，但别声张", {"profile": False, "preferences": False, "agent_rules": False, "entities": True}, "D"),
    TestCase(86, "这家公司的决策链特别长，从部门到集团要两个月", {"profile": False, "preferences": False, "agent_rules": False, "entities": True}, "D"),
    TestCase(87, "上次见面他提到竞品报价比我们低20%", {"profile": False, "preferences": False, "agent_rules": False, "entities": True}, "D"),
    TestCase(88, "赵敏下个月要去美国出差，这段时间联系不上", {"profile": False, "preferences": False, "agent_rules": False, "entities": True}, "D"),
    TestCase(89, "华为内部审批流程复杂，至少要3-4周", {"profile": False, "preferences": False, "agent_rules": False, "entities": True}, "D"),
    TestCase(90, "腾讯在同时评估用友和我们", {"profile": False, "preferences": False, "agent_rules": False, "entities": True}, "D"),
    TestCase(91, "招行对安全认证要求很高，必须有等保三级", {"profile": False, "preferences": False, "agent_rules": False, "entities": True}, "D"),
    TestCase(92, "张总喜欢看PPT，不喜欢看长文档", {"profile": False, "preferences": False, "agent_rules": False, "entities": True}, "D"),
    TestCase(93, "客户反馈我们响应速度比竞品快", {"profile": False, "preferences": False, "agent_rules": False, "entities": True}, "D"),
    TestCase(94, "华为那边要求用正式语气沟通", {"profile": False, "preferences": False, "agent_rules": False, "entities": True}, "D"),
    TestCase(95, "比亚迪之前用SAP，体验不太好", {"profile": False, "preferences": False, "agent_rules": False, "entities": True}, "D"),
    TestCase(96, "小米的技术团队偏好微服务架构", {"profile": False, "preferences": False, "agent_rules": False, "entities": True}, "D"),
    TestCase(97, "字节的孙丽做事雷厉风行，邮件必须当天回", {"profile": False, "preferences": False, "agent_rules": False, "entities": True}, "D"),
    TestCase(98, "阿里内部有自研CRM团队，我们要证明比自研好", {"profile": False, "preferences": False, "agent_rules": False, "entities": True}, "D"),
    TestCase(99, "京东的刘洋很务实，只看落地效果不看PPT", {"profile": False, "preferences": False, "agent_rules": False, "entities": True}, "D"),
    TestCase(100, "美团要求私有化部署，数据不能出他们的机房", {"profile": False, "preferences": False, "agent_rules": False, "entities": True}, "D"),
    # E. 不提取 (#101~#130)
    TestCase(101, "帮我查一下上个月的销售数据", {"profile": False, "preferences": False, "agent_rules": False, "entities": False}, "E"),
    TestCase(102, "好的，收到", {"profile": False, "preferences": False, "agent_rules": False, "entities": False}, "E"),
    TestCase(103, "把这个商机的阶段改成proposal", {"profile": False, "preferences": False, "agent_rules": False, "entities": False}, "E"),
    TestCase(104, "发一封邮件给张总，内容就按上次说的", {"profile": False, "preferences": False, "agent_rules": False, "entities": False}, "E"),
    TestCase(105, "嗯嗯，继续", {"profile": False, "preferences": False, "agent_rules": False, "entities": False}, "E"),
    TestCase(106, "等一下，我想想", {"profile": False, "preferences": False, "agent_rules": False, "entities": False}, "E"),
    TestCase(107, "算了，不用了", {"profile": False, "preferences": False, "agent_rules": False, "entities": False}, "E"),
    TestCase(108, "这个数据对吗？帮我核实一下", {"profile": False, "preferences": False, "agent_rules": False, "entities": False}, "E"),
    TestCase(109, "把刚才的结果导出Excel发给我", {"profile": False, "preferences": False, "agent_rules": False, "entities": False}, "E"),
    TestCase(110, "今天天气不错", {"profile": False, "preferences": False, "agent_rules": False, "entities": False}, "E"),
    TestCase(111, "帮我约一下明天下午3点和张总的会", {"profile": False, "preferences": False, "agent_rules": False, "entities": False}, "E"),
    TestCase(112, "刚才那个分析再跑一遍", {"profile": False, "preferences": False, "agent_rules": False, "entities": False}, "E"),
    TestCase(113, "华为的商机有几个？", {"profile": False, "preferences": False, "agent_rules": False, "entities": False}, "E"),
    TestCase(114, "这个月还有多少预算？", {"profile": False, "preferences": False, "agent_rules": False, "entities": False}, "E"),
    TestCase(115, "帮我标记这个客户为VIP", {"profile": False, "preferences": False, "agent_rules": False, "entities": False}, "E"),
    TestCase(116, "上面那个表格能不能横向展示？", {"profile": False, "preferences": False, "agent_rules": False, "entities": False}, "E"),
    TestCase(117, "这次分析深入一些", {"profile": False, "preferences": False, "agent_rules": False, "entities": False}, "E"),
    TestCase(118, "感觉你像私人助理", {"profile": False, "preferences": False, "agent_rules": False, "entities": False}, "E"),
    TestCase(119, "帮我问一下张总预算够不够", {"profile": False, "preferences": False, "agent_rules": False, "entities": False}, "E"),
    TestCase(120, "下周二我要去拜访客户B", {"profile": False, "preferences": False, "agent_rules": False, "entities": False}, "E"),
    TestCase(121, "谢谢，辛苦了", {"profile": False, "preferences": False, "agent_rules": False, "entities": False}, "E"),
    TestCase(122, "这个方案不错，就这样吧", {"profile": False, "preferences": False, "agent_rules": False, "entities": False}, "E"),
    TestCase(123, "帮我把这段话翻译成英文", {"profile": False, "preferences": False, "agent_rules": False, "entities": False}, "E"),
    TestCase(124, "再详细说说第三点", {"profile": False, "preferences": False, "agent_rules": False, "entities": False}, "E"),
    TestCase(125, "华为那个项目金额是多少来着？", {"profile": False, "preferences": False, "agent_rules": False, "entities": False}, "E"),
    TestCase(126, "你刚才说的那个数据来源是哪里", {"profile": False, "preferences": False, "agent_rules": False, "entities": False}, "E"),
    TestCase(127, "帮我生成一份本周的工作总结", {"profile": False, "preferences": False, "agent_rules": False, "entities": False}, "E"),
    TestCase(128, "这个客户的联系方式是什么", {"profile": False, "preferences": False, "agent_rules": False, "entities": False}, "E"),
    TestCase(129, "把刚才的内容整理成邮件格式", {"profile": False, "preferences": False, "agent_rules": False, "entities": False}, "E"),
    TestCase(130, "算了还是用表格吧", {"profile": False, "preferences": False, "agent_rules": False, "entities": False}, "E"),
    # F. 混合意图 (#131~#160)
    TestCase(131, "我是做金融行业的，你要熟悉银行的业务流程", {"profile": True, "preferences": False, "agent_rules": True, "entities": False}, "F"),
    TestCase(132, "我喜欢简洁的风格，你回复不要超过3句话", {"profile": False, "preferences": True, "agent_rules": True, "entities": False}, "F"),
    TestCase(133, "我是华东区的，华为张伟是我的重点客户", {"profile": True, "preferences": False, "agent_rules": False, "entities": True}, "F"),
    TestCase(134, "我习惯看表格，你以后都用表格展示", {"profile": False, "preferences": True, "agent_rules": True, "entities": False}, "F"),
    TestCase(135, "我管理10人团队，主要跟进腾讯和阿里", {"profile": True, "preferences": False, "agent_rules": False, "entities": True}, "F"),
    TestCase(136, "你是我的销售助理，我负责华南区", {"profile": True, "preferences": False, "agent_rules": True, "entities": False}, "F"),
    TestCase(137, "我不喜欢长报告，你控制在一页以内", {"profile": False, "preferences": True, "agent_rules": True, "entities": False}, "F"),
    TestCase(138, "我们公司做SaaS的，竞品是Salesforce", {"profile": True, "preferences": False, "agent_rules": False, "entities": True}, "F"),
    TestCase(139, "我偏好邮件沟通，你发邮件前先让我确认", {"profile": False, "preferences": True, "agent_rules": True, "entities": False}, "F"),
    TestCase(140, "我是技术出身，华为那边的技术评估我来对接", {"profile": True, "preferences": False, "agent_rules": False, "entities": True}, "F"),
    TestCase(141, "你要专注制造业，我在这个行业做了8年", {"profile": True, "preferences": False, "agent_rules": True, "entities": False}, "F"),
    TestCase(142, "我喜欢数据驱动决策，分析报告要有数据支撑", {"profile": False, "preferences": True, "agent_rules": True, "entities": False}, "F"),
    TestCase(143, "我负责大客户，张伟和李娜是我的关键联系人", {"profile": True, "preferences": False, "agent_rules": False, "entities": True}, "F"),
    TestCase(144, "你说话直接点，我这个人不喜欢绕弯子", {"profile": False, "preferences": True, "agent_rules": True, "entities": False}, "F"),
    TestCase(145, "我习惯周一开会，你每周一早上给我准备会议材料", {"profile": False, "preferences": True, "agent_rules": True, "entities": False}, "F"),
    TestCase(146, "你是我的CRM顾问，我们用的是纷享销客", {"profile": True, "preferences": False, "agent_rules": True, "entities": False}, "F"),
    TestCase(147, "我喜欢看折线图，你做趋势分析时用折线图", {"profile": False, "preferences": True, "agent_rules": True, "entities": False}, "F"),
    TestCase(148, "我们团队有8个人，主要服务字节和美团", {"profile": True, "preferences": False, "agent_rules": False, "entities": True}, "F"),
    TestCase(149, "你要用通俗语言，我们团队不都是技术背景", {"profile": True, "preferences": False, "agent_rules": True, "entities": False}, "F"),
    TestCase(150, "我在意响应速度，你收到消息后1小时内回复", {"profile": False, "preferences": True, "agent_rules": True, "entities": False}, "F"),
    TestCase(151, "我是新来的产品经理，你帮我熟悉CRM模块的功能", {"profile": True, "preferences": False, "agent_rules": True, "entities": False}, "F"),
    TestCase(152, "我更关注转化率，你每次分析都要带转化漏斗", {"profile": False, "preferences": True, "agent_rules": True, "entities": False}, "F"),
    TestCase(153, "我们公司主打金融行业，招行是我们的标杆客户", {"profile": True, "preferences": False, "agent_rules": False, "entities": True}, "F"),
    TestCase(154, "你要专业一点，我是技术出身的", {"profile": True, "preferences": False, "agent_rules": True, "entities": False}, "F"),
    TestCase(155, "我讨厌啰嗦，你回复精炼一些", {"profile": False, "preferences": True, "agent_rules": True, "entities": False}, "F"),
    TestCase(156, "我负责华东区，腾讯王强是我最大的客户", {"profile": True, "preferences": False, "agent_rules": False, "entities": True}, "F"),
    TestCase(157, "你是我的竞品分析师，我们主要和用友竞争", {"profile": False, "preferences": False, "agent_rules": True, "entities": True}, "F"),
    TestCase(158, "我喜欢结构化表达，你回复用1234列出来", {"profile": False, "preferences": True, "agent_rules": True, "entities": False}, "F"),
    TestCase(159, "我们公司200人规模，华为是我们最大的客户", {"profile": True, "preferences": False, "agent_rules": False, "entities": True}, "F"),
    TestCase(160, "你要像军师一样给我出谋划策，我比较依赖数据决策", {"profile": False, "preferences": True, "agent_rules": True, "entities": False}, "F"),
    # G. 边界对抗 (#161~#200)
    TestCase(161, "金额统一用万为单位", {"profile": False, "preferences": False, "agent_rules": True, "entities": False}, "G"),
    TestCase(162, "我要求金额用万为单位", {"profile": False, "preferences": True, "agent_rules": False, "entities": False}, "G"),
    TestCase(163, "数据展示要有对比", {"profile": False, "preferences": False, "agent_rules": True, "entities": False}, "G"),
    TestCase(164, "我觉得有对比的数据更好理解", {"profile": False, "preferences": True, "agent_rules": False, "entities": False}, "G"),
    TestCase(165, "报告里要有图表", {"profile": False, "preferences": False, "agent_rules": True, "entities": False}, "G"),
    TestCase(166, "我更喜欢看图表而不是纯文字", {"profile": False, "preferences": True, "agent_rules": False, "entities": False}, "G"),
    TestCase(167, "每次分析都要带上数据来源", {"profile": False, "preferences": False, "agent_rules": True, "entities": False}, "G"),
    TestCase(168, "我比较看重数据来源的可靠性", {"profile": False, "preferences": True, "agent_rules": False, "entities": False}, "G"),
    TestCase(169, "邮件要简短专业", {"profile": False, "preferences": False, "agent_rules": True, "entities": False}, "G"),
    TestCase(170, "我喜欢简短专业的邮件风格", {"profile": False, "preferences": True, "agent_rules": False, "entities": False}, "G"),
    TestCase(171, "以后分析要深入一些", {"profile": False, "preferences": False, "agent_rules": True, "entities": False}, "G"),
    TestCase(172, "回复要带上参考链接", {"profile": False, "preferences": False, "agent_rules": True, "entities": False}, "G"),
    TestCase(173, "我希望能看到参考链接", {"profile": False, "preferences": True, "agent_rules": False, "entities": False}, "G"),
    TestCase(174, "汇报按优先级排序", {"profile": False, "preferences": False, "agent_rules": True, "entities": False}, "G"),
    TestCase(175, "我习惯按优先级看事情", {"profile": False, "preferences": True, "agent_rules": False, "entities": False}, "G"),
    TestCase(176, "我们部门不加班", {"profile": True, "preferences": False, "agent_rules": False, "entities": False}, "G"),
    TestCase(177, "我一般不加班", {"profile": False, "preferences": True, "agent_rules": False, "entities": False}, "G"),
    TestCase(178, "我们团队都用飞书", {"profile": True, "preferences": False, "agent_rules": False, "entities": False}, "G"),
    TestCase(179, "我喜欢用飞书沟通", {"profile": False, "preferences": True, "agent_rules": False, "entities": False}, "G"),
    TestCase(180, "我们公司注重数据驱动", {"profile": True, "preferences": False, "agent_rules": False, "entities": False}, "G"),
    TestCase(181, "我个人比较注重数据驱动", {"profile": False, "preferences": True, "agent_rules": False, "entities": False}, "G"),
    TestCase(182, "我们的工作节奏很快", {"profile": True, "preferences": False, "agent_rules": False, "entities": False}, "G"),
    TestCase(183, "我们公司的优势是响应速度快", {"profile": True, "preferences": False, "agent_rules": False, "entities": False}, "G"),
    TestCase(184, "客户反馈我们响应速度比竞品快", {"profile": False, "preferences": False, "agent_rules": False, "entities": True}, "G"),
    TestCase(185, "我们的竞争对手主要是Salesforce", {"profile": True, "preferences": False, "agent_rules": False, "entities": False}, "G"),
    TestCase(186, "Salesforce最近在降价抢客户", {"profile": False, "preferences": False, "agent_rules": False, "entities": True}, "G"),
    TestCase(187, "我们公司是做企业软件的", {"profile": True, "preferences": False, "agent_rules": False, "entities": False}, "G"),
    TestCase(188, "这家公司是做企业软件的", {"profile": False, "preferences": False, "agent_rules": False, "entities": True}, "G"),
    TestCase(189, "之前在阿里做过3年", {"profile": True, "preferences": False, "agent_rules": False, "entities": False}, "G"),
    TestCase(190, "阿里最近在裁员，我们可以挖人", {"profile": False, "preferences": False, "agent_rules": False, "entities": True}, "G"),
    TestCase(191, "华为那边要求用正式语气沟通", {"profile": False, "preferences": False, "agent_rules": False, "entities": True}, "G"),
    TestCase(192, "跟华为沟通要用正式语气", {"profile": False, "preferences": False, "agent_rules": True, "entities": False}, "G"),
    TestCase(193, "招行的合规要求是必须有等保三级", {"profile": False, "preferences": False, "agent_rules": False, "entities": True}, "G"),
    TestCase(194, "给招行的方案要突出安全合规", {"profile": False, "preferences": False, "agent_rules": True, "entities": False}, "G"),
    TestCase(195, "字节那边决策很快，拖了就没戏", {"profile": False, "preferences": False, "agent_rules": False, "entities": True}, "G"),
    TestCase(196, "跟字节的项目要快速响应，不能拖", {"profile": False, "preferences": False, "agent_rules": True, "entities": False}, "G"),
    TestCase(197, "以后分析要深入一些", {"profile": False, "preferences": False, "agent_rules": True, "entities": False}, "G"),
    TestCase(198, "这次分析深入一些", {"profile": False, "preferences": False, "agent_rules": False, "entities": False}, "G"),
    TestCase(199, "你就像我的私人助理一样", {"profile": False, "preferences": False, "agent_rules": True, "entities": False}, "G"),
    TestCase(200, "感觉你像私人助理", {"profile": False, "preferences": False, "agent_rules": False, "entities": False}, "G"),
]

# ═══════════════════════════════════════════════════════════
# LLM + 解析 + 执行
# ═══════════════════════════════════════════════════════════

_llm_instance = None


def _get_llm():
    global _llm_instance
    if _llm_instance is None:
        from langchain_openai import ChatOpenAI
        api_key = os.environ.get("OPENAI_API_KEY", "")
        base_url = os.environ.get("OPENAI_BASE_URL", "https://tokenhub.tencentmaas.com/v1")
        model = os.environ.get("OPENAI_MODEL_NAME", "deepseek-v4-flash")
        if not api_key:
            print("ERROR: OPENAI_API_KEY not set")
            sys.exit(1)
        _llm_instance = ChatOpenAI(model=model, api_key=api_key, base_url=base_url, temperature=0)
    return _llm_instance


async def call_llm(prompt):
    llm = _get_llm()
    result = await llm.ainvoke(prompt)
    return result.content


def parse_extraction_result(response_text):
    """解析 UNIFIED_EXTRACT_PROMPT 的 JSON 输出"""
    result = {"profile": False, "preferences": False, "agent_rules": False, "entities": False}
    try:
        if "{" not in response_text:
            return result
        json_str = response_text[response_text.index("{"):response_text.rindex("}") + 1]
        data = json.loads(json_str)
    except (json.JSONDecodeError, ValueError):
        return result
    if "result" in data and isinstance(data["result"], dict):
        data = data["result"]
    profile = data.get("profile", {})
    if isinstance(profile, dict) and profile.get("content", "").strip():
        result["profile"] = True
    prefs = data.get("preferences", [])
    if isinstance(prefs, list):
        valid = [p for p in prefs if isinstance(p, dict) and p.get("abstract", "").strip()]
        result["preferences"] = len(valid) > 0
    rules = data.get("agent_rules", {})
    if isinstance(rules, dict) and rules.get("content", "").strip():
        result["agent_rules"] = True
    entities = data.get("entities", [])
    if isinstance(entities, list):
        valid = [e for e in entities if isinstance(e, dict) and e.get("abstract", "").strip()]
        result["entities"] = len(valid) > 0
    return result


@dataclass
class CaseResult:
    case_id: int
    batch: str
    input_text: str
    expected: dict
    actual: dict
    passed: bool
    error: str = ""


async def run_single_case(case, semaphore):
    async with semaphore:
        prompt = UNIFIED_EXTRACT_PROMPT.format(
            existing_profile="（无）",
            existing_rules="（无）",
            existing_entities="（无）",
            user_messages=f"[human]: {case.input}",
            output_language="auto",
        )
        try:
            response = await call_llm(prompt)
            actual = parse_extraction_result(response)
        except Exception as e:
            return CaseResult(case.id, case.batch, case.input, case.expect, {}, False, str(e))
        all_pass = all(
            actual.get(d, False) == case.expect.get(d, False)
            for d in ("profile", "preferences", "agent_rules", "entities")
        )
        return CaseResult(case.id, case.batch, case.input, case.expect, actual, all_pass)


BATCH_NAMES = {
    "A": "Profile正例", "B": "Preferences正例", "C": "AgentRules正例",
    "D": "Entities正例", "E": "不提取", "F": "混合意图", "G": "边界对抗",
}


def print_report(results):
    print("\n" + "=" * 70)
    print("  UNIFIED_EXTRACT_PROMPT v3 — 四维度记忆提取验证报告")
    print("=" * 70)

    batch_stats = {}
    for r in results:
        batch_stats.setdefault(r.batch, {"total": 0, "passed": 0, "failures": []})
        batch_stats[r.batch]["total"] += 1
        if r.passed:
            batch_stats[r.batch]["passed"] += 1
        else:
            batch_stats[r.batch]["failures"].append(r)

    header = f"  {'批次':<6} {'名称':<16} {'通过率':<8} {'通过/总数'}"
    print(f"\n{header}")
    print("  " + "-" * 50)
    total_all = passed_all = 0
    for batch in sorted(batch_stats):
        s = batch_stats[batch]
        total_all += s["total"]
        passed_all += s["passed"]
        rate = s["passed"] / s["total"] * 100
        print(f"  {batch:<6} {BATCH_NAMES.get(batch, ''):<16} {rate:5.1f}%   {s['passed']}/{s['total']}")
    overall = passed_all / total_all * 100 if total_all else 0
    print("  " + "-" * 50)
    print(f"  {'合计':<6} {'ALL':<16} {overall:5.1f}%   {passed_all}/{total_all}")

    # 维度级指标
    dim_stats = {d: {"tp": 0, "fp": 0, "fn": 0, "tn": 0}
                 for d in ("profile", "preferences", "agent_rules", "entities")}
    for r in results:
        if r.error:
            continue
        for d in dim_stats:
            exp, act = r.expected.get(d, False), r.actual.get(d, False)
            if exp and act:
                dim_stats[d]["tp"] += 1
            elif not exp and act:
                dim_stats[d]["fp"] += 1
            elif exp and not act:
                dim_stats[d]["fn"] += 1
            else:
                dim_stats[d]["tn"] += 1

    print(f"\n  {'维度':<14} {'精确率':<8} {'召回率':<8} {'F1':<8} {'误提取率'}")
    print("  " + "-" * 50)
    for d in ("profile", "preferences", "agent_rules", "entities"):
        s = dim_stats[d]
        prec = s["tp"] / (s["tp"] + s["fp"]) * 100 if s["tp"] + s["fp"] else 0
        rec = s["tp"] / (s["tp"] + s["fn"]) * 100 if s["tp"] + s["fn"] else 0
        f1 = 2 * prec * rec / (prec + rec) if prec + rec else 0
        fpr = s["fp"] / (s["fp"] + s["tn"]) * 100 if s["fp"] + s["tn"] else 0
        print(f"  {d:<14} {prec:5.1f}%  {rec:5.1f}%  {f1:5.1f}%  {fpr:5.1f}%")

    # 失败详情
    failures = [r for r in results if not r.passed]
    if failures:
        print(f"\n  失败用例 ({len(failures)} 条):")
        print("  " + "-" * 50)
        for r in failures[:50]:
            wrongs = []
            for d in ("profile", "preferences", "agent_rules", "entities"):
                e, a = r.expected.get(d, False), r.actual.get(d, False)
                if e != a:
                    wrongs.append(f"{d}({'漏提' if e else '误提'})")
            print(f"  #{r.case_id:3d}[{r.batch}] {r.input_text[:32]:<32} | {', '.join(wrongs)}")

    # 达标判定
    print(f"\n  达标判定:")
    print("  " + "-" * 50)
    for b, t in [("A", 95), ("B", 95), ("C", 95), ("D", 95), ("E", 95)]:
        if b in batch_stats:
            r = batch_stats[b]["passed"] / batch_stats[b]["total"] * 100
            status = "PASS" if r >= t else "FAIL"
            print(f"  [{status}] {BATCH_NAMES[b]:<16} {r:5.1f}% (>={t}%)")
    if "F" in batch_stats:
        fr = [r for r in results if r.batch == "F"]
        full = sum(1 for r in fr if r.passed) / len(fr) * 100 if fr else 0
        part_count = sum(
            1 for r in fr
            if not r.error and any(r.actual.get(d) for d, v in r.expected.items() if v)
        )
        part = part_count / len(fr) * 100 if fr else 0
        print(f"  [{'PASS' if full >= 85 else 'FAIL'}] {'混合完整拆分':<16} {full:5.1f}% (>=85%)")
        print(f"  [{'PASS' if part >= 95 else 'FAIL'}] {'混合部分命中':<16} {part:5.1f}% (>=95%)")
    if "G" in batch_stats:
        gr = batch_stats["G"]["passed"] / batch_stats["G"]["total"] * 100
        print(f"  [{'PASS' if gr >= 80 else 'FAIL'}] {'边界对抗':<16} {gr:5.1f}% (>=80%)")

    print(f"\n{'=' * 70}")
    print(f"  总结: {passed_all}/{total_all} ({overall:.1f}%)")
    print(f"{'=' * 70}\n")


async def main():
    parser = argparse.ArgumentParser(description="UNIFIED_EXTRACT_PROMPT v3 验证")
    parser.add_argument("--batch", type=str, help="批次 (A/B/C/D/E/F/G)")
    parser.add_argument("--range", type=str, help="范围 (如 161-200)")
    parser.add_argument("--concurrency", type=int, default=5)
    parser.add_argument("--output", type=str, default="test_unified_results.json")
    args = parser.parse_args()

    cases = TEST_CASES
    if args.batch:
        cases = [c for c in cases if c.batch == args.batch.upper()]
    elif args.range:
        s, e = map(int, args.range.split("-"))
        cases = [c for c in cases if s <= c.id <= e]
    if not cases:
        print("No matching cases")
        return

    print(f"\n  UNIFIED_EXTRACT_PROMPT v3 验证")
    print(f"  用例: {len(cases)}  并发: {args.concurrency}")
    print(f"  模型: {os.environ.get('OPENAI_MODEL_NAME', 'deepseek-v4-flash')}")
    print(f"  端点: {os.environ.get('OPENAI_BASE_URL', 'https://tokenhub.tencentmaas.com/v1')}\n")

    sem = asyncio.Semaphore(args.concurrency)
    t0 = time.monotonic()
    tasks = [run_single_case(c, sem) for c in cases]
    results = []
    done = 0
    for coro in asyncio.as_completed(tasks):
        r = await coro
        results.append(r)
        done += 1
        if not r.passed:
            print(f"  FAIL #{r.case_id:3d}[{r.batch}] {r.input_text[:30]}")
        if done % 20 == 0:
            print(f"  进度: {done}/{len(cases)} ({time.monotonic() - t0:.0f}s)")

    results.sort(key=lambda x: x.case_id)
    elapsed = time.monotonic() - t0
    print(f"\n  耗时: {elapsed:.1f}s ({elapsed / len(cases):.1f}s/条)")
    print_report(results)

    out = os.path.join(os.path.dirname(__file__), args.output)
    with open(out, "w", encoding="utf-8") as f:
        json.dump([{
            "id": r.case_id, "batch": r.batch, "input": r.input_text,
            "expected": r.expected, "actual": r.actual,
            "passed": r.passed, "error": r.error,
        } for r in results], f, ensure_ascii=False, indent=2)
    print(f"  结果已保存: {out}")


if __name__ == "__main__":
    asyncio.run(main())
