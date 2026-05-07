"""四路提取提示词过拟合验证 — 100 个测试场景

针对 prompts.py 中的 PROFILE / PREFERENCES / AGENT_RULES / ENTITIES 四个提示词，
通过 100 个精心设计的场景验证其泛化能力，识别过拟合问题。

场景分布：
  A. Profile 正例（1-12）        — 测试泛化能力（省略主语、复合身份、否定更新）
  B. Preferences 正例（13-24）   — 测试隐性偏好识别
  C. Agent Rules 正例（25-36）   — 测试无"你"字指令
  D. Entities 正例（37-48）      — 测试非标准表达
  E. 不提取场景（49-64）         — 测试过度提取抑制
  F. 混合意图场景（65-80）       — 测试多维度提取
  G. 边界对抗场景（81-100）      — 测试维度混淆

运行:
  cd product-specs/agent-system
  .venv/bin/python -B tests/test_prompt_overfitting_100.py
  .venv/bin/python -B tests/test_prompt_overfitting_100.py --group G  # 只跑某组
  .venv/bin/python -B tests/test_prompt_overfitting_100.py --start 80 --end 100
"""
import argparse
import asyncio
import json
import os
import sys
from dataclasses import dataclass, field

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("DOUBAO_API_KEY", "651621e7-e495-4728-93ef-ed380e9ddcd1")

from src.memory.extraction.prompts import (
    PROFILE_EXTRACT_PROMPT,
    PREFERENCES_EXTRACT_PROMPT,
    AGENT_RULES_EXTRACT_PROMPT,
    ENTITIES_EXTRACT_PROMPT,
)


# ═══════════════════════════════════════════════════════════
# 100 个测试用例
# 格式: (id, group, input, expect_dict, test_goal)
# expect_dict: {profile: bool, preferences: bool, agent_rules: bool, entities: bool}
# ═══════════════════════════════════════════════════════════

CASES = [
    # ── A. Profile 正例（1-12）省略主语 / 复合身份 / 否定更新 ──
    (1, "A", "在这个行业干了十年了，从技术转管理",
        {"profile": True, "preferences": False, "agent_rules": False, "entities": False},
        "省略'我'的身份描述"),
    (2, "A", "团队刚扩到20人，压力挺大的",
        {"profile": True, "preferences": False, "agent_rules": False, "entities": False},
        "口语化+省略主语"),
    (3, "A", "之前在阿里做过3年，后来跳到现在这家",
        {"profile": True, "preferences": False, "agent_rules": False, "entities": False},
        "经历描述无'我是'"),
    (4, "A", "华南区的客户都归我管",
        {"profile": True, "preferences": False, "agent_rules": False, "entities": False},
        "倒装句式"),
    (5, "A", "我不再负责华东区了，上个月调到华南",
        {"profile": True, "preferences": False, "agent_rules": False, "entities": False},
        "否定+更新"),
    (6, "A", "既是产品经理也兼任售前，忙得要死",
        {"profile": True, "preferences": False, "agent_rules": False, "entities": False},
        "复合角色+口语"),
    (7, "A", "说实话我就是个打杂的，什么都管",
        {"profile": True, "preferences": False, "agent_rules": False, "entities": False},
        "自嘲式身份描述"),
    (8, "A", "我们是做ToB SaaS的，客户主要是中大型企业",
        {"profile": True, "preferences": False, "agent_rules": False, "entities": False},
        "'我们'描述公司"),
    (9, "A", "今年KPI是3000万，去年完成了2800",
        {"profile": True, "preferences": False, "agent_rules": False, "entities": False},
        "数值型画像信息"),
    (10, "A", "负责的客户有200多个，大部分是金融行业",
        {"profile": True, "preferences": False, "agent_rules": False, "entities": False},
        "省略'我'+数值"),
    (11, "A", "刚来三个月，还在熟悉业务",
        {"profile": True, "preferences": False, "agent_rules": False, "entities": False},
        "时间状态描述"),
    (12, "A", "我老板是销售VP，他让我重点盯互联网客户",
        {"profile": True, "preferences": False, "agent_rules": False, "entities": False},
        "间接身份+汇报关系"),

    # ── B. Preferences 正例（13-24）隐性偏好 / 条件偏好 / 否定偏好 ──
    (13, "B", "每次你给我的报告我都跳过前面直接看结论",
        {"profile": False, "preferences": True, "agent_rules": False, "entities": False},
        "行为暗示偏好，无偏好动词"),
    (14, "B", "那种密密麻麻的表格我根本看不下去",
        {"profile": False, "preferences": True, "agent_rules": False, "entities": False},
        "否定式隐性偏好"),
    (15, "B", "大客户我一般亲自跟，小客户让团队处理",
        {"profile": False, "preferences": True, "agent_rules": False, "entities": False},
        "条件性工作习惯"),
    (16, "B", "受不了那种啰嗦的回复，直接说重点就行",
        {"profile": False, "preferences": True, "agent_rules": False, "entities": False},
        "'受不了'替代'不喜欢'"),
    (17, "B", "数据嘛，能用图就别用表，一目了然",
        {"profile": False, "preferences": True, "agent_rules": False, "entities": False},
        "极度口语化偏好"),
    (18, "B", "周五下午我一般不安排客户拜访",
        {"profile": False, "preferences": True, "agent_rules": False, "entities": False},
        "时间习惯"),
    (19, "B", "如果是紧急的事情微信说，不急的发邮件",
        {"profile": False, "preferences": True, "agent_rules": False, "entities": False},
        "条件性沟通偏好"),
    (20, "B", "我对数据精度要求高，小数点后两位",
        {"profile": False, "preferences": True, "agent_rules": False, "entities": False},
        "'要求高'替代'喜欢'"),
    (21, "B", "看报表的时候我更在意同比，环比参考就行",
        {"profile": False, "preferences": True, "agent_rules": False, "entities": False},
        "程度性偏好"),
    (22, "B", "别给我发那种长报告，一页纸搞定最好",
        {"profile": False, "preferences": True, "agent_rules": False, "entities": False},
        "否定+无'我喜欢'"),
    (23, "B", "我这个人比较视觉化，文字太多就头疼",
        {"profile": False, "preferences": True, "agent_rules": False, "entities": False},
        "自我描述式偏好"),
    (24, "B", "早上9点前别给我推消息，那时候在开晨会",
        {"profile": False, "preferences": True, "agent_rules": False, "entities": False},
        "时间+否定偏好"),

    # ── C. Agent Rules 正例（25-36）无"你"字指令 / 更新撤销 / 隐性规则 ──
    (25, "C", "分析报告要包含同比环比数据",
        {"profile": False, "preferences": False, "agent_rules": True, "entities": False},
        "无'你'字的输出要求"),
    (26, "C", "回复控制在100字以内",
        {"profile": False, "preferences": False, "agent_rules": True, "entities": False},
        "无主语的约束指令"),
    (27, "C", "以后查数据的时候自动加上时间范围",
        {"profile": False, "preferences": False, "agent_rules": True, "entities": False},
        "'以后'暗示持久规则"),
    (28, "C", "取消之前不超过200字的限制",
        {"profile": False, "preferences": False, "agent_rules": True, "entities": False},
        "撤销/更新指令"),
    (29, "C", "算了，还是用表格吧，图表看不清",
        {"profile": False, "preferences": False, "agent_rules": True, "entities": False},
        "口语化更新指令"),
    (30, "C", "跟客户沟通的邮件要用正式语气",
        {"profile": False, "preferences": False, "agent_rules": True, "entities": False},
        "无'你'的行为约束"),
    (31, "C", "重要客户的分析要单独出一份详细报告",
        {"profile": False, "preferences": False, "agent_rules": True, "entities": False},
        "条件性输出规则"),
    (32, "C", "不要自动发邮件，先让我过目",
        {"profile": False, "preferences": False, "agent_rules": True, "entities": False},
        "无'你'的禁止指令"),
    (33, "C", "每次给我建议的时候列出pros和cons",
        {"profile": False, "preferences": False, "agent_rules": True, "entities": False},
        "无'你'的格式要求"),
    (34, "C", "上次那个分析太浅了，以后要深入一些",
        {"profile": False, "preferences": False, "agent_rules": True, "entities": False},
        "隐性规则（通过反馈暗示）"),
    (35, "C", "客户数据不要对外分享，内部使用",
        {"profile": False, "preferences": False, "agent_rules": True, "entities": False},
        "安全约束"),
    (36, "C", "先确认需求再动手，别自作主张",
        {"profile": False, "preferences": False, "agent_rules": True, "entities": False},
        "口语化流程约束"),

    # ── D. Entities 正例（37-48）非标准表达 ──
    (37, "D", "张总那边最近在忙重组，估计这个月没空",
        {"profile": False, "preferences": False, "agent_rules": False, "entities": True},
        "省略公司名的实体信息"),
    (38, "D", "华为和腾讯都在评估我们的方案，但侧重点不同",
        {"profile": False, "preferences": False, "agent_rules": False, "entities": True},
        "多实体混合"),
    (39, "D", "我觉得这个客户不太靠谱，拖了三个月了",
        {"profile": False, "preferences": False, "agent_rules": False, "entities": True},
        "'这个客户'指代+主观判断"),
    (40, "D", "听说他们内部在打架，技术部和采购部意见不一致",
        {"profile": False, "preferences": False, "agent_rules": False, "entities": True},
        "'他们'指代+内部关系"),
    (41, "D", "王强这个人吧，表面热情但决策很慢",
        {"profile": False, "preferences": False, "agent_rules": False, "entities": True},
        "口语化人物评价"),
    (42, "D", "泰克科技去年营收5个亿，今年目标8个亿",
        {"profile": False, "preferences": False, "agent_rules": False, "entities": True},
        "公司数据+趋势"),
    (43, "D", "那个项目其实是张伟在推，李娜只是挂名",
        {"profile": False, "preferences": False, "agent_rules": False, "entities": True},
        "内部权力关系"),
    (44, "D", "比亚迪的预算审批要过五关斩六将",
        {"profile": False, "preferences": False, "agent_rules": False, "entities": True},
        "比喻式流程描述"),
    (45, "D", "陈刚私下说基本定了选我们，但别声张",
        {"profile": False, "preferences": False, "agent_rules": False, "entities": True},
        "口头承诺+保密"),
    (46, "D", "这家公司的决策链特别长，从部门到集团要两个月",
        {"profile": False, "preferences": False, "agent_rules": False, "entities": True},
        "'这家公司'指代"),
    (47, "D", "上次见面他提到竞品报价比我们低20%",
        {"profile": False, "preferences": False, "agent_rules": False, "entities": True},
        "竞争情报"),
    (48, "D", "赵敏下个月要去美国出差，这段时间联系不上",
        {"profile": False, "preferences": False, "agent_rules": False, "entities": True},
        "时效性信息"),

    # ── E. 不提取场景（49-64）过度提取抑制 ──
    (49, "E", "帮我查一下上个月的销售数据",
        {"profile": False, "preferences": False, "agent_rules": False, "entities": False},
        "纯操作指令"),
    (50, "E", "好的，收到",
        {"profile": False, "preferences": False, "agent_rules": False, "entities": False},
        "简单确认"),
    (51, "E", "把这个商机的阶段改成proposal",
        {"profile": False, "preferences": False, "agent_rules": False, "entities": False},
        "数据修改指令"),
    (52, "E", "发一封邮件给张总，内容就按上次说的",
        {"profile": False, "preferences": False, "agent_rules": False, "entities": False},
        "一次性操作"),
    (53, "E", "嗯嗯，继续",
        {"profile": False, "preferences": False, "agent_rules": False, "entities": False},
        "对话延续"),
    (54, "E", "等一下，我想想",
        {"profile": False, "preferences": False, "agent_rules": False, "entities": False},
        "思考中"),
    (55, "E", "算了，不用了",
        {"profile": False, "preferences": False, "agent_rules": False, "entities": False},
        "取消操作（非取消规则）"),
    (56, "E", "这个数据对吗？帮我核实一下",
        {"profile": False, "preferences": False, "agent_rules": False, "entities": False},
        "质疑+操作"),
    (57, "E", "把刚才的结果导出Excel发给我",
        {"profile": False, "preferences": False, "agent_rules": False, "entities": False},
        "导出操作"),
    (58, "E", "今天天气不错",
        {"profile": False, "preferences": False, "agent_rules": False, "entities": False},
        "闲聊"),
    (59, "E", "帮我约一下明天下午3点和张总的会",
        {"profile": False, "preferences": False, "agent_rules": False, "entities": False},
        "日程操作"),
    (60, "E", "刚才那个分析再跑一遍",
        {"profile": False, "preferences": False, "agent_rules": False, "entities": False},
        "重复操作"),
    (61, "E", "华为的商机有几个？",
        {"profile": False, "preferences": False, "agent_rules": False, "entities": False},
        "纯查询"),
    (62, "E", "这个月还有多少预算？",
        {"profile": False, "preferences": False, "agent_rules": False, "entities": False},
        "纯查询"),
    (63, "E", "帮我标记这个客户为VIP",
        {"profile": False, "preferences": False, "agent_rules": False, "entities": False},
        "数据操作"),
    (64, "E", "上面那个表格能不能横向展示？",
        {"profile": False, "preferences": False, "agent_rules": False, "entities": False},
        "当前操作请求（非持久偏好）"),

    # ── F. 混合意图场景（65-80）多维度提取 ──
    (65, "F", "我是做金融行业的，你要熟悉银行的业务流程",
        {"profile": True, "preferences": False, "agent_rules": True, "entities": False},
        "身份+指令混合"),
    (66, "F", "我喜欢简洁的风格，你回复不要超过3句话",
        {"profile": False, "preferences": True, "agent_rules": True, "entities": False},
        "偏好+指令混合"),
    (67, "F", "我是华东区的，华为张伟是我的重点客户",
        {"profile": True, "preferences": False, "agent_rules": False, "entities": True},
        "身份+实体混合"),
    (68, "F", "我习惯看表格，你以后都用表格展示",
        {"profile": False, "preferences": True, "agent_rules": True, "entities": False},
        "偏好+指令重叠"),
    (69, "F", "我管理10人团队，主要跟进腾讯和阿里",
        {"profile": True, "preferences": False, "agent_rules": False, "entities": True},
        "身份+实体（客户名）"),
    (70, "F", "你是我的销售助理，我负责华南区",
        {"profile": True, "preferences": False, "agent_rules": True, "entities": False},
        "角色定义+身份"),
    (71, "F", "我不喜欢长报告，你控制在一页以内",
        {"profile": False, "preferences": True, "agent_rules": True, "entities": False},
        "偏好+约束"),
    (72, "F", "我们公司做SaaS的，竞品是Salesforce",
        {"profile": True, "preferences": False, "agent_rules": False, "entities": True},
        "公司信息+竞品实体"),
    (73, "F", "我偏好邮件沟通，你发邮件前先让我确认",
        {"profile": False, "preferences": True, "agent_rules": True, "entities": False},
        "偏好+流程约束"),
    (74, "F", "我是技术出身，华为那边的技术评估我来对接",
        {"profile": True, "preferences": False, "agent_rules": False, "entities": True},
        "背景+客户关系"),
    (75, "F", "你要专注制造业，我在这个行业做了8年",
        {"profile": True, "preferences": False, "agent_rules": True, "entities": False},
        "领域指令+经验"),
    (76, "F", "我喜欢数据驱动决策，分析报告要有数据支撑",
        {"profile": False, "preferences": True, "agent_rules": True, "entities": False},
        "偏好+输出要求"),
    (77, "F", "我负责大客户，张伟和李娜是我的关键联系人",
        {"profile": True, "preferences": False, "agent_rules": False, "entities": True},
        "职责+实体"),
    (78, "F", "你说话直接点，我这个人不喜欢绕弯子",
        {"profile": False, "preferences": True, "agent_rules": True, "entities": False},
        "指令+性格偏好"),
    (79, "F", "我是新来的产品经理，你帮我熟悉一下CRM模块",
        {"profile": True, "preferences": False, "agent_rules": False, "entities": False},
        "身份+一次性任务（非持久指令）"),
    (80, "F", "我习惯周一开会，你每周一早上给我准备会议材料",
        {"profile": False, "preferences": True, "agent_rules": True, "entities": False},
        "习惯+持久指令"),

    # ── G. 边界对抗场景（81-100）维度混淆 ──
    (81, "G", "金额统一用万为单位",
        {"profile": False, "preferences": False, "agent_rules": True, "entities": False},
        "无主语指令 vs 偏好 [pref vs rules]"),
    (82, "G", "我要求金额用万为单位",
        {"profile": False, "preferences": True, "agent_rules": False, "entities": False},
        "'我要求'是偏好表达 [pref vs rules]"),
    (83, "G", "数据展示要有对比",
        {"profile": False, "preferences": False, "agent_rules": True, "entities": False},
        "无主语输出要求 [pref vs rules]"),
    (84, "G", "我觉得有对比的数据更好理解",
        {"profile": False, "preferences": True, "agent_rules": False, "entities": False},
        "'我觉得'是偏好 [pref vs rules]"),
    (85, "G", "我们团队都用飞书",
        {"profile": True, "preferences": False, "agent_rules": False, "entities": False},
        "团队工具是画像信息 [profile vs pref]"),
    (86, "G", "我喜欢用飞书沟通",
        {"profile": False, "preferences": True, "agent_rules": False, "entities": False},
        "个人偏好 [profile vs pref]"),
    (87, "G", "张总喜欢看PPT",
        {"profile": False, "preferences": False, "agent_rules": False, "entities": True},
        "第三方偏好 [entities vs pref]"),
    (88, "G", "我喜欢看PPT",
        {"profile": False, "preferences": True, "agent_rules": False, "entities": False},
        "用户自己偏好 [entities vs pref]"),
    (89, "G", "华为那边要求用正式语气沟通",
        {"profile": False, "preferences": False, "agent_rules": False, "entities": True},
        "客户要求是实体信息 [entities vs rules]"),
    (90, "G", "跟华为沟通要用正式语气",
        {"profile": False, "preferences": False, "agent_rules": True, "entities": False},
        "对Agent的行为指令 [entities vs rules]"),
    (91, "G", "我们公司的优势是响应速度快",
        {"profile": True, "preferences": False, "agent_rules": False, "entities": False},
        "公司特征是画像 [profile vs entities]"),
    (92, "G", "客户反馈我们响应速度比竞品快",
        {"profile": False, "preferences": False, "agent_rules": False, "entities": True},
        "客户反馈是实体信息 [profile vs entities]"),
    (93, "G", "以后分析要深入一些",
        {"profile": False, "preferences": False, "agent_rules": True, "entities": False},
        "持久性指令 [rules vs 不提取]"),
    (94, "G", "这次分析深入一些",
        {"profile": False, "preferences": False, "agent_rules": False, "entities": False},
        "一次性操作请求 [rules vs 不提取]"),
    (95, "G", "我一般不加班",
        {"profile": False, "preferences": True, "agent_rules": False, "entities": False},
        "工作习惯偏好 [pref vs profile]"),
    (96, "G", "我们部门不加班",
        {"profile": True, "preferences": False, "agent_rules": False, "entities": False},
        "团队文化是画像 [pref vs profile]"),
    (97, "G", "张总说预算不够",
        {"profile": False, "preferences": False, "agent_rules": False, "entities": True},
        "第三方陈述 [entities vs 不提取]"),
    (98, "G", "帮我问一下张总预算够不够",
        {"profile": False, "preferences": False, "agent_rules": False, "entities": False},
        "操作指令 [entities vs 不提取]"),
    (99, "G", "你就像我的私人助理一样",
        {"profile": False, "preferences": False, "agent_rules": True, "entities": False},
        "角色定义（比喻式）[rules vs 不提取]"),
    (100, "G", "感觉你就像我的私人助理",
        {"profile": False, "preferences": False, "agent_rules": False, "entities": False},
        "感叹/评价（非指令）[rules vs 不提取]"),
]


# ═══════════════════════════════════════════════════════════
# Prompt 填充与调用
# ═══════════════════════════════════════════════════════════

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
            return bool(data.get("profile", {}).get("content", ""))
        elif dimension == "preferences":
            return len(data.get("preferences", [])) > 0
        elif dimension == "agent_rules":
            return bool(data.get("agent_rules", {}).get("content", ""))
        elif dimension == "entities":
            return len(data.get("entities", [])) > 0
    except (json.JSONDecodeError, ValueError):
        pass
    return False


async def call_llm(prompt: str, llm) -> str:
    """调用豆包模型"""
    result = await llm.ainvoke(prompt)
    return result.content


async def run_one_case(case_tuple, llm) -> dict:
    """跑一个用例的四路提取"""
    case_id, group, text, expect, goal = case_tuple
    results = {}
    for dim, prompt_template in PROMPTS.items():
        params = dict(FILL_PARAMS[dim])
        params[INPUT_FIELD[dim]] = f"[human]: {text}"
        prompt = prompt_template.format(**params)
        response = await call_llm(prompt, llm)
        extracted = has_extraction(response, dim)
        results[dim] = {
            "extracted": extracted,
            "expected": expect[dim],
            "pass": extracted == expect[dim],
            "response": response[:300],
        }
    return {
        "id": case_id, "group": group, "input": text, "goal": goal,
        "results": results,
        "all_pass": all(r["pass"] for r in results.values()),
    }


# ═══════════════════════════════════════════════════════════
# 汇总与分组统计
# ═══════════════════════════════════════════════════════════

@dataclass
class GroupStat:
    total_cases: int = 0
    pass_cases: int = 0
    total_dims: int = 0
    pass_dims: int = 0
    failures: list = field(default_factory=list)


def print_case_result(res: dict):
    case_id = res["id"]
    grp = res["group"]
    mark = "✅" if res["all_pass"] else "❌"
    print(f"\n{mark} [{grp}] 用例 {case_id}: {res['input']}")
    print(f"   目标: {res['goal']}")
    for dim, r in res["results"].items():
        dim_mark = "✓" if r["pass"] else "✗"
        exp = "提取" if r["expected"] else "空"
        act = "提取" if r["extracted"] else "空"
        print(f"   {dim_mark} {dim:12s}: 期望{exp} 实际{act}")
        if not r["pass"]:
            # 打印响应摘要帮助诊断
            resp_short = r["response"].replace("\n", " ")[:150]
            print(f"      响应: {resp_short}")


def print_summary(all_results: list):
    # 按组统计
    groups: dict = {}
    for res in all_results:
        g = res["group"]
        if g not in groups:
            groups[g] = GroupStat()
        stat = groups[g]
        stat.total_cases += 1
        if res["all_pass"]:
            stat.pass_cases += 1
        for dim, r in res["results"].items():
            stat.total_dims += 1
            if r["pass"]:
                stat.pass_dims += 1
            else:
                stat.failures.append({
                    "id": res["id"], "dim": dim,
                    "expected": r["expected"], "actual": r["extracted"],
                    "input": res["input"], "goal": res["goal"],
                })

    group_names = {
        "A": "Profile 正例（省略主语/复合身份/否定更新）",
        "B": "Preferences 正例（隐性偏好）",
        "C": "Agent Rules 正例（无'你'字指令）",
        "D": "Entities 正例（非标准表达）",
        "E": "不提取场景（过度提取抑制）",
        "F": "混合意图场景（多维度提取）",
        "G": "边界对抗场景（维度混淆）",
    }

    print("\n" + "=" * 70)
    print("  分组汇总")
    print("=" * 70)
    print(f"  {'组':<4} {'说明':<40} {'用例通过':<12} {'维度通过':<12}")
    print(f"  {'─' * 66}")
    for g in sorted(groups.keys()):
        stat = groups[g]
        case_pct = stat.pass_cases / stat.total_cases * 100 if stat.total_cases else 0
        dim_pct = stat.pass_dims / stat.total_dims * 100 if stat.total_dims else 0
        name = group_names.get(g, g)
        print(f"  {g:<4} {name:<40} "
              f"{stat.pass_cases}/{stat.total_cases} ({case_pct:>4.0f}%)   "
              f"{stat.pass_dims}/{stat.total_dims} ({dim_pct:>4.0f}%)")

    # 总计
    total_cases = sum(s.total_cases for s in groups.values())
    pass_cases = sum(s.pass_cases for s in groups.values())
    total_dims = sum(s.total_dims for s in groups.values())
    pass_dims = sum(s.pass_dims for s in groups.values())
    print(f"  {'─' * 66}")
    print(f"  {'总':<4} {'':<40} "
          f"{pass_cases}/{total_cases} ({pass_cases/total_cases*100:.0f}%)   "
          f"{pass_dims}/{total_dims} ({pass_dims/total_dims*100:.0f}%)")

    # 失败详情（按组）
    print("\n" + "=" * 70)
    print("  失败详情（按维度分类）")
    print("=" * 70)
    by_dim: dict = {}
    for g, stat in groups.items():
        for f in stat.failures:
            by_dim.setdefault(f["dim"], []).append({**f, "group": g})
    for dim in ["profile", "preferences", "agent_rules", "entities"]:
        fails = by_dim.get(dim, [])
        if not fails:
            continue
        print(f"\n  [{dim}] {len(fails)} 条失败:")
        for f in fails:
            exp = "应提取" if f["expected"] else "应为空"
            act = "提取了" if f["actual"] else "为空"
            print(f"    [{f['group']}] #{f['id']:<3} {exp}但{act} | {f['input'][:40]}")
            print(f"           目标: {f['goal']}")

    # 过拟合风险总结
    print("\n" + "=" * 70)
    print("  过拟合风险评估")
    print("=" * 70)
    a_d_pct = sum(groups.get(g, GroupStat()).pass_cases for g in "ABCDE") / \
              max(1, sum(groups.get(g, GroupStat()).total_cases for g in "ABCDE")) * 100
    fg_pct = sum(groups.get(g, GroupStat()).pass_cases for g in "FG") / \
             max(1, sum(groups.get(g, GroupStat()).total_cases for g in "FG")) * 100
    print(f"  标准场景 (A-E) 通过率:  {a_d_pct:.0f}%")
    print(f"  对抗场景 (F-G) 通过率:  {fg_pct:.0f}%")
    gap = a_d_pct - fg_pct
    print(f"  泛化差距 (A-E 减 F-G):  {gap:.0f}%")
    if gap > 20:
        print("  ⚠️  过拟合风险高：标准场景表现良好但对抗场景明显下滑，提示词过度依赖固定模式")
    elif gap > 10:
        print("  ⚠️  存在一定过拟合：对抗场景下滑明显，建议优化边界规则")
    else:
        print("  ✅ 泛化能力良好：标准场景与对抗场景差距小")


# ═══════════════════════════════════════════════════════════
# 主入口
# ═══════════════════════════════════════════════════════════

async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--group", type=str, default="", help="只跑某组：A/B/C/D/E/F/G")
    parser.add_argument("--start", type=int, default=1, help="起始用例 id")
    parser.add_argument("--end", type=int, default=100, help="结束用例 id")
    parser.add_argument("--concurrency", type=int, default=4, help="并发度")
    parser.add_argument("--model", type=str, default="doubao-seed-2-0-lite-260215")
    args = parser.parse_args()

    from langchain_openai import ChatOpenAI
    llm = ChatOpenAI(
        model=args.model,
        api_key=os.environ["DOUBAO_API_KEY"],
        base_url="https://ark.cn-beijing.volces.com/api/v3/",
        temperature=0,
        max_tokens=2048,
    )

    # 过滤用例
    selected = [
        c for c in CASES
        if args.start <= c[0] <= args.end
        and (not args.group or c[1] == args.group.upper())
    ]

    print("=" * 70)
    print(f"  四路提示词过拟合验证 — 运行 {len(selected)} 个用例")
    print(f"  模型: {args.model}   并发: {args.concurrency}")
    print("=" * 70)

    # 分批并发执行
    all_results = []
    sem = asyncio.Semaphore(args.concurrency)

    async def _run(case):
        async with sem:
            return await run_one_case(case, llm)

    tasks = [_run(c) for c in selected]
    for i, fut in enumerate(asyncio.as_completed(tasks), 1):
        res = await fut
        print_case_result(res)
        all_results.append(res)
        if i % 10 == 0:
            print(f"\n  ... 进度: {i}/{len(selected)}")

    # 按 id 排序后汇总
    all_results.sort(key=lambda r: r["id"])
    print_summary(all_results)

    # 退出码：全部通过返回 0，否则返回失败数
    failed = sum(1 for r in all_results if not r["all_pass"])
    return failed


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
