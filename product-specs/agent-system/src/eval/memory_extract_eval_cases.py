"""四维度记忆提取场景评测用例集（250 条）

覆盖：
  A. Profile 正例（25 条）
  B. Preferences 正例（25 条）
  C. Agent Rules 正例（25 条）
  D. Entities 正例（25 条）
  E. 不提取场景（30 条）
  F. 混合意图（30 条）
  G. 边界对抗（40 条）
  H. 反思验证（50 条）

对齐《四维度记忆提取场景测试用例.md》设计文档。
"""
from __future__ import annotations

from .memory_eval_runner import MemoryEvalCase, EvalLayer, QueryType


def build_extract_cases() -> list[MemoryEvalCase]:
    """构建四维度提取评测用例集"""
    cases = []
    cases.extend(_profile_cases())
    cases.extend(_preferences_cases())
    cases.extend(_agent_rules_cases())
    cases.extend(_entities_cases())
    cases.extend(_no_extract_cases())
    cases.extend(_mixed_intent_cases())
    cases.extend(_boundary_cases())
    cases.extend(_reflect_cases())
    return cases


# ═══════════════════════════════════════════════════════════
# A. Profile 正例（#1 ~ #25）
# ═══════════════════════════════════════════════════════════

def _profile_cases() -> list[MemoryEvalCase]:
    """用户对"我/我们团队/我们公司"的稳定属性描述"""
    return [
        MemoryEvalCase(
            id="ext_profile_01", layer=EvalLayer.EXTRACT, query_type=QueryType.EXTRACT_PROFILE,
            query="在这个行业干了十年了，从技术转管理",
            description="Profile正例 — 省略\"我\"的履历描述",
            expected_dimensions=["profile"],
            test_focus="省略\"我\"的履历描述",
        ),
        MemoryEvalCase(
            id="ext_profile_02", layer=EvalLayer.EXTRACT, query_type=QueryType.EXTRACT_PROFILE,
            query="团队刚扩到20人，压力挺大的",
            description="Profile正例 — 口语化+省略主语+团队规模",
            expected_dimensions=["profile"],
            test_focus="口语化+省略主语+团队规模",
        ),
        MemoryEvalCase(
            id="ext_profile_03", layer=EvalLayer.EXTRACT, query_type=QueryType.EXTRACT_PROFILE,
            query="之前在阿里做过3年，后来跳到现在这家",
            description="Profile正例 — 履历描述无\"我是\"",
            expected_dimensions=["profile"],
            test_focus="履历描述无\"我是\"",
        ),
        MemoryEvalCase(
            id="ext_profile_04", layer=EvalLayer.EXTRACT, query_type=QueryType.EXTRACT_PROFILE,
            query="华南区的客户都归我管",
            description="Profile正例 — 倒装句式+区域职责",
            expected_dimensions=["profile"],
            test_focus="倒装句式+区域职责",
        ),
        MemoryEvalCase(
            id="ext_profile_05", layer=EvalLayer.EXTRACT, query_type=QueryType.EXTRACT_PROFILE,
            query="我不再负责华东区了，上个月调到华南",
            description="Profile正例 — 否定+更新（调岗）",
            expected_dimensions=["profile"],
            test_focus="否定+更新（调岗）",
        ),
        MemoryEvalCase(
            id="ext_profile_06", layer=EvalLayer.EXTRACT, query_type=QueryType.EXTRACT_PROFILE,
            query="既是产品经理也兼任售前，忙得要死",
            description="Profile正例 — 复合角色+口语",
            expected_dimensions=["profile"],
            test_focus="复合角色+口语",
        ),
        MemoryEvalCase(
            id="ext_profile_07", layer=EvalLayer.EXTRACT, query_type=QueryType.EXTRACT_PROFILE,
            query="说实话我就是个打杂的，什么都管",
            description="Profile正例 — 自嘲式身份描述",
            expected_dimensions=["profile"],
            test_focus="自嘲式身份描述",
        ),
        MemoryEvalCase(
            id="ext_profile_08", layer=EvalLayer.EXTRACT, query_type=QueryType.EXTRACT_PROFILE,
            query="我们是做ToB SaaS的，客户主要是中大型企业",
            description="Profile正例 — \"我们\"描述公司业务",
            expected_dimensions=["profile"],
            test_focus="\"我们\"描述公司业务",
        ),
        MemoryEvalCase(
            id="ext_profile_09", layer=EvalLayer.EXTRACT, query_type=QueryType.EXTRACT_PROFILE,
            query="今年KPI是3000万，去年完成了2800",
            description="Profile正例 — 数值型画像信息",
            expected_dimensions=["profile"],
            test_focus="数值型画像信息",
        ),
        MemoryEvalCase(
            id="ext_profile_10", layer=EvalLayer.EXTRACT, query_type=QueryType.EXTRACT_PROFILE,
            query="负责的客户有200多个，大部分是金融行业",
            description="Profile正例 — 省略\"我\"+数值+行业",
            expected_dimensions=["profile"],
            test_focus="省略\"我\"+数值+行业",
        ),
        MemoryEvalCase(
            id="ext_profile_11", layer=EvalLayer.EXTRACT, query_type=QueryType.EXTRACT_PROFILE,
            query="刚来三个月，还在熟悉业务",
            description="Profile正例 — 时间状态描述",
            expected_dimensions=["profile"],
            test_focus="时间状态描述",
        ),
        MemoryEvalCase(
            id="ext_profile_12", layer=EvalLayer.EXTRACT, query_type=QueryType.EXTRACT_PROFILE,
            query="我老板是销售VP，他让我重点盯互联网客户",
            description="Profile正例 — 间接身份+汇报关系",
            expected_dimensions=["profile"],
            test_focus="间接身份+汇报关系",
        ),
        MemoryEvalCase(
            id="ext_profile_13", layer=EvalLayer.EXTRACT, query_type=QueryType.EXTRACT_PROFILE,
            query="我们部门不加班，文化比较宽松",
            description="Profile正例 — 组织文化描述",
            expected_dimensions=["profile"],
            test_focus="组织文化描述",
        ),
        MemoryEvalCase(
            id="ext_profile_14", layer=EvalLayer.EXTRACT, query_type=QueryType.EXTRACT_PROFILE,
            query="公司总部在深圳，北京是分公司",
            description="Profile正例 — 组织地理信息",
            expected_dimensions=["profile"],
            test_focus="组织地理信息",
        ),
        MemoryEvalCase(
            id="ext_profile_15", layer=EvalLayer.EXTRACT, query_type=QueryType.EXTRACT_PROFILE,
            query="我们团队都用飞书协作",
            description="Profile正例 — 团队工具是组织画像",
            expected_dimensions=["profile"],
            test_focus="团队工具是组织画像",
        ),
        MemoryEvalCase(
            id="ext_profile_16", layer=EvalLayer.EXTRACT, query_type=QueryType.EXTRACT_PROFILE,
            query="我手下有3个SDR，2个AE",
            description="Profile正例 — 团队结构",
            expected_dimensions=["profile"],
            test_focus="团队结构",
        ),
        MemoryEvalCase(
            id="ext_profile_17", layer=EvalLayer.EXTRACT, query_type=QueryType.EXTRACT_PROFILE,
            query="我是技术出身，后来转做售前",
            description="Profile正例 — 职业转型背景",
            expected_dimensions=["profile"],
            test_focus="职业转型背景",
        ),
        MemoryEvalCase(
            id="ext_profile_18", layer=EvalLayer.EXTRACT, query_type=QueryType.EXTRACT_PROFILE,
            query="我们公司去年融了B轮，估值3个亿",
            description="Profile正例 — 公司阶段信息",
            expected_dimensions=["profile"],
            test_focus="公司阶段信息",
        ),
        MemoryEvalCase(
            id="ext_profile_19", layer=EvalLayer.EXTRACT, query_type=QueryType.EXTRACT_PROFILE,
            query="我的客户主要集中在长三角地区",
            description="Profile正例 — 业务覆盖区域",
            expected_dimensions=["profile"],
            test_focus="业务覆盖区域",
        ),
        MemoryEvalCase(
            id="ext_profile_20", layer=EvalLayer.EXTRACT, query_type=QueryType.EXTRACT_PROFILE,
            query="我们产品客单价在50-200万之间",
            description="Profile正例 — 产品定价区间",
            expected_dimensions=["profile"],
            test_focus="产品定价区间",
        ),
        MemoryEvalCase(
            id="ext_profile_21", layer=EvalLayer.EXTRACT, query_type=QueryType.EXTRACT_PROFILE,
            query="我是今年1月入职的，之前在Oracle",
            description="Profile正例 — 入职时间+前公司",
            expected_dimensions=["profile"],
            test_focus="入职时间+前公司",
        ),
        MemoryEvalCase(
            id="ext_profile_22", layer=EvalLayer.EXTRACT, query_type=QueryType.EXTRACT_PROFILE,
            query="我们公司的优势是响应速度快",
            description="Profile正例 — 公司竞争优势",
            expected_dimensions=["profile"],
            test_focus="公司竞争优势",
        ),
        MemoryEvalCase(
            id="ext_profile_23", layer=EvalLayer.EXTRACT, query_type=QueryType.EXTRACT_PROFILE,
            query="我直接向CEO汇报",
            description="Profile正例 — 汇报层级",
            expected_dimensions=["profile"],
            test_focus="汇报层级",
        ),
        MemoryEvalCase(
            id="ext_profile_24", layer=EvalLayer.EXTRACT, query_type=QueryType.EXTRACT_PROFILE,
            query="我们部门今年的目标是签10个大客户",
            description="Profile正例 — 团队目标",
            expected_dimensions=["profile"],
            test_focus="团队目标",
        ),
        MemoryEvalCase(
            id="ext_profile_25", layer=EvalLayer.EXTRACT, query_type=QueryType.EXTRACT_PROFILE,
            query="我同时负责新签和续约两条线",
            description="Profile正例 — 职责范围",
            expected_dimensions=["profile"],
            test_focus="职责范围",
        ),
    ]


# ═══════════════════════════════════════════════════════════
# B. Preferences 正例（#26 ~ #50）
# ═══════════════════════════════════════════════════════════

def _preferences_cases() -> list[MemoryEvalCase]:
    """用户自己的喜好、习惯、厌恶或个人标准"""
    return [
        MemoryEvalCase(
            id="ext_pref_01", layer=EvalLayer.EXTRACT, query_type=QueryType.EXTRACT_PREFERENCES,
            query="每次你给我的报告我都跳过前面直接看结论",
            description="Preferences正例 — 行为暗示偏好，无偏好动词",
            expected_dimensions=["preferences"],
            test_focus="行为暗示偏好，无偏好动词",
        ),
        MemoryEvalCase(
            id="ext_pref_02", layer=EvalLayer.EXTRACT, query_type=QueryType.EXTRACT_PREFERENCES,
            query="那种密密麻麻的表格我根本看不下去",
            description="Preferences正例 — 否定式隐性偏好",
            expected_dimensions=["preferences"],
            test_focus="否定式隐性偏好",
        ),
        MemoryEvalCase(
            id="ext_pref_03", layer=EvalLayer.EXTRACT, query_type=QueryType.EXTRACT_PREFERENCES,
            query="大客户我一般亲自跟，小客户让团队处理",
            description="Preferences正例 — 条件性工作习惯",
            expected_dimensions=["preferences"],
            test_focus="条件性工作习惯",
        ),
        MemoryEvalCase(
            id="ext_pref_04", layer=EvalLayer.EXTRACT, query_type=QueryType.EXTRACT_PREFERENCES,
            query="受不了那种啰嗦的回复，直接说重点就行",
            description="Preferences正例 — \"受不了\"替代\"不喜欢\"",
            expected_dimensions=["preferences"],
            test_focus="\"受不了\"替代\"不喜欢\"",
        ),
        MemoryEvalCase(
            id="ext_pref_05", layer=EvalLayer.EXTRACT, query_type=QueryType.EXTRACT_PREFERENCES,
            query="数据嘛，能用图就别用表，一目了然",
            description="Preferences正例 — 极度口语化偏好",
            expected_dimensions=["preferences"],
            test_focus="极度口语化偏好",
        ),
        MemoryEvalCase(
            id="ext_pref_06", layer=EvalLayer.EXTRACT, query_type=QueryType.EXTRACT_PREFERENCES,
            query="周五下午我一般不安排客户拜访",
            description="Preferences正例 — 时间习惯",
            expected_dimensions=["preferences"],
            test_focus="时间习惯",
        ),
        MemoryEvalCase(
            id="ext_pref_07", layer=EvalLayer.EXTRACT, query_type=QueryType.EXTRACT_PREFERENCES,
            query="如果是紧急的事情微信说，不急的发邮件",
            description="Preferences正例 — 条件性沟通偏好",
            expected_dimensions=["preferences"],
            test_focus="条件性沟通偏好",
        ),
        MemoryEvalCase(
            id="ext_pref_08", layer=EvalLayer.EXTRACT, query_type=QueryType.EXTRACT_PREFERENCES,
            query="我对数据精度要求高，小数点后两位",
            description="Preferences正例 — \"要求高\"替代\"喜欢\"",
            expected_dimensions=["preferences"],
            test_focus="\"要求高\"替代\"喜欢\"",
        ),
        MemoryEvalCase(
            id="ext_pref_09", layer=EvalLayer.EXTRACT, query_type=QueryType.EXTRACT_PREFERENCES,
            query="看报表的时候我更在意同比，环比参考就行",
            description="Preferences正例 — 程度性偏好",
            expected_dimensions=["preferences"],
            test_focus="程度性偏好",
        ),
        MemoryEvalCase(
            id="ext_pref_10", layer=EvalLayer.EXTRACT, query_type=QueryType.EXTRACT_PREFERENCES,
            query="别给我发那种长报告，一页纸搞定最好",
            description="Preferences正例 — 否定+无\"我喜欢\"",
            expected_dimensions=["preferences"],
            test_focus="否定+无\"我喜欢\"",
        ),
        MemoryEvalCase(
            id="ext_pref_11", layer=EvalLayer.EXTRACT, query_type=QueryType.EXTRACT_PREFERENCES,
            query="我这个人比较视觉化，文字太多就头疼",
            description="Preferences正例 — 自我描述式偏好",
            expected_dimensions=["preferences"],
            test_focus="自我描述式偏好",
        ),
        MemoryEvalCase(
            id="ext_pref_12", layer=EvalLayer.EXTRACT, query_type=QueryType.EXTRACT_PREFERENCES,
            query="早上9点前别给我推消息，那时候在开晨会",
            description="Preferences正例 — 时间+否定偏好",
            expected_dimensions=["preferences"],
            test_focus="时间+否定偏好",
        ),
        MemoryEvalCase(
            id="ext_pref_13", layer=EvalLayer.EXTRACT, query_type=QueryType.EXTRACT_PREFERENCES,
            query="我喜欢用图表展示重要数据，辅助数据用表格",
            description="Preferences正例 — 标准偏好动词+条件",
            expected_dimensions=["preferences"],
            test_focus="标准偏好动词+条件",
        ),
        MemoryEvalCase(
            id="ext_pref_14", layer=EvalLayer.EXTRACT, query_type=QueryType.EXTRACT_PREFERENCES,
            query="我习惯每天早上先看数据看板",
            description="Preferences正例 — 时间习惯",
            expected_dimensions=["preferences"],
            test_focus="时间习惯",
        ),
        MemoryEvalCase(
            id="ext_pref_15", layer=EvalLayer.EXTRACT, query_type=QueryType.EXTRACT_PREFERENCES,
            query="我比较在意客户的反馈速度",
            description="Preferences正例 — \"在意\"表达偏好",
            expected_dimensions=["preferences"],
            test_focus="\"在意\"表达偏好",
        ),
        MemoryEvalCase(
            id="ext_pref_16", layer=EvalLayer.EXTRACT, query_type=QueryType.EXTRACT_PREFERENCES,
            query="我一般不加班，效率优先",
            description="Preferences正例 — 工作习惯",
            expected_dimensions=["preferences"],
            test_focus="工作习惯",
        ),
        MemoryEvalCase(
            id="ext_pref_17", layer=EvalLayer.EXTRACT, query_type=QueryType.EXTRACT_PREFERENCES,
            query="我讨厌开没有议程的会",
            description="Preferences正例 — \"讨厌\"表达厌恶",
            expected_dimensions=["preferences"],
            test_focus="\"讨厌\"表达厌恶",
        ),
        MemoryEvalCase(
            id="ext_pref_18", layer=EvalLayer.EXTRACT, query_type=QueryType.EXTRACT_PREFERENCES,
            query="我倾向于先打电话再发邮件确认",
            description="Preferences正例 — \"倾向于\"偏好动词",
            expected_dimensions=["preferences"],
            test_focus="\"倾向于\"偏好动词",
        ),
        MemoryEvalCase(
            id="ext_pref_19", layer=EvalLayer.EXTRACT, query_type=QueryType.EXTRACT_PREFERENCES,
            query="我觉得有对比的数据更好理解",
            description="Preferences正例 — \"我觉得\"表达偏好",
            expected_dimensions=["preferences"],
            test_focus="\"我觉得\"表达偏好",
        ),
        MemoryEvalCase(
            id="ext_pref_20", layer=EvalLayer.EXTRACT, query_type=QueryType.EXTRACT_PREFERENCES,
            query="我喜欢用飞书沟通，微信太杂了",
            description="Preferences正例 — 工具偏好+否定对比",
            expected_dimensions=["preferences"],
            test_focus="工具偏好+否定对比",
        ),
        MemoryEvalCase(
            id="ext_pref_21", layer=EvalLayer.EXTRACT, query_type=QueryType.EXTRACT_PREFERENCES,
            query="我看东西比较快，信息密度高一点没关系",
            description="Preferences正例 — 自我描述式",
            expected_dimensions=["preferences"],
            test_focus="自我描述式",
        ),
        MemoryEvalCase(
            id="ext_pref_22", layer=EvalLayer.EXTRACT, query_type=QueryType.EXTRACT_PREFERENCES,
            query="我不太喜欢被动等消息，有进展主动告诉我",
            description="Preferences正例 — 否定偏好+期望",
            expected_dimensions=["preferences"],
            test_focus="否定偏好+期望",
        ),
        MemoryEvalCase(
            id="ext_pref_23", layer=EvalLayer.EXTRACT, query_type=QueryType.EXTRACT_PREFERENCES,
            query="我习惯周一开会定本周计划",
            description="Preferences正例 — 时间+工作习惯",
            expected_dimensions=["preferences"],
            test_focus="时间+工作习惯",
        ),
        MemoryEvalCase(
            id="ext_pref_24", layer=EvalLayer.EXTRACT, query_type=QueryType.EXTRACT_PREFERENCES,
            query="我更关注转化率而不是线索数量",
            description="Preferences正例 — 程度对比偏好",
            expected_dimensions=["preferences"],
            test_focus="程度对比偏好",
        ),
        MemoryEvalCase(
            id="ext_pref_25", layer=EvalLayer.EXTRACT, query_type=QueryType.EXTRACT_PREFERENCES,
            query="我烦那种没有结论的分析，看完不知道该干嘛",
            description="Preferences正例 — \"烦\"表达厌恶",
            expected_dimensions=["preferences"],
            test_focus="\"烦\"表达厌恶",
        ),
    ]


# ═══════════════════════════════════════════════════════════
# C. Agent Rules 正例（#51 ~ #75）
# ═══════════════════════════════════════════════════════════

def _agent_rules_cases() -> list[MemoryEvalCase]:
    """对 Agent 未来行为的持久约束（含无"你"字指令）"""
    return [
        MemoryEvalCase(
            id="ext_rules_01", layer=EvalLayer.EXTRACT, query_type=QueryType.EXTRACT_AGENT_RULES,
            query="你是我的销售数据分析助理",
            description="Agent Rules正例 — 角色定义",
            expected_dimensions=["agent_rules"],
            test_focus="角色定义",
        ),
        MemoryEvalCase(
            id="ext_rules_02", layer=EvalLayer.EXTRACT, query_type=QueryType.EXTRACT_AGENT_RULES,
            query="你回复不要超过100字",
            description="Agent Rules正例 — 标准约束指令",
            expected_dimensions=["agent_rules"],
            test_focus="标准约束指令",
        ),
        MemoryEvalCase(
            id="ext_rules_03", layer=EvalLayer.EXTRACT, query_type=QueryType.EXTRACT_AGENT_RULES,
            query="分析报告要包含同比环比数据",
            description="Agent Rules正例 — 无\"你\"字的输出要求",
            expected_dimensions=["agent_rules"],
            test_focus="无\"你\"字的输出要求",
        ),
        MemoryEvalCase(
            id="ext_rules_04", layer=EvalLayer.EXTRACT, query_type=QueryType.EXTRACT_AGENT_RULES,
            query="回复控制在100字以内",
            description="Agent Rules正例 — 无主语的约束指令",
            expected_dimensions=["agent_rules"],
            test_focus="无主语的约束指令",
        ),
        MemoryEvalCase(
            id="ext_rules_05", layer=EvalLayer.EXTRACT, query_type=QueryType.EXTRACT_AGENT_RULES,
            query="以后查数据的时候自动加上时间范围",
            description="Agent Rules正例 — \"以后\"暗示持久规则",
            expected_dimensions=["agent_rules"],
            test_focus="\"以后\"暗示持久规则",
        ),
        MemoryEvalCase(
            id="ext_rules_06", layer=EvalLayer.EXTRACT, query_type=QueryType.EXTRACT_AGENT_RULES,
            query="取消之前不超过200字的限制",
            description="Agent Rules正例 — 撤销/更新指令",
            expected_dimensions=["agent_rules"],
            test_focus="撤销/更新指令",
        ),
        MemoryEvalCase(
            id="ext_rules_07", layer=EvalLayer.EXTRACT, query_type=QueryType.EXTRACT_AGENT_RULES,
            query="跟客户沟通的邮件要用正式语气",
            description="Agent Rules正例 — 无\"你\"的行为约束",
            expected_dimensions=["agent_rules"],
            test_focus="无\"你\"的行为约束",
        ),
        MemoryEvalCase(
            id="ext_rules_08", layer=EvalLayer.EXTRACT, query_type=QueryType.EXTRACT_AGENT_RULES,
            query="重要客户的分析要单独出一份详细报告",
            description="Agent Rules正例 — 条件性输出规则",
            expected_dimensions=["agent_rules"],
            test_focus="条件性输出规则",
        ),
        MemoryEvalCase(
            id="ext_rules_09", layer=EvalLayer.EXTRACT, query_type=QueryType.EXTRACT_AGENT_RULES,
            query="不要自动发邮件，先让我过目",
            description="Agent Rules正例 — 无\"你\"的禁止指令",
            expected_dimensions=["agent_rules"],
            test_focus="无\"你\"的禁止指令",
        ),
        MemoryEvalCase(
            id="ext_rules_10", layer=EvalLayer.EXTRACT, query_type=QueryType.EXTRACT_AGENT_RULES,
            query="每次给我建议的时候列出pros和cons",
            description="Agent Rules正例 — 无\"你\"的格式要求",
            expected_dimensions=["agent_rules"],
            test_focus="无\"你\"的格式要求",
        ),
        MemoryEvalCase(
            id="ext_rules_11", layer=EvalLayer.EXTRACT, query_type=QueryType.EXTRACT_AGENT_RULES,
            query="上次那个分析太浅了，以后要深入一些",
            description="Agent Rules正例 — 隐性规则（反馈暗示持久）",
            expected_dimensions=["agent_rules"],
            test_focus="隐性规则（反馈暗示持久）",
        ),
        MemoryEvalCase(
            id="ext_rules_12", layer=EvalLayer.EXTRACT, query_type=QueryType.EXTRACT_AGENT_RULES,
            query="客户数据不要对外分享，内部使用",
            description="Agent Rules正例 — 安全约束",
            expected_dimensions=["agent_rules"],
            test_focus="安全约束",
        ),
        MemoryEvalCase(
            id="ext_rules_13", layer=EvalLayer.EXTRACT, query_type=QueryType.EXTRACT_AGENT_RULES,
            query="先确认需求再动手，别自作主张",
            description="Agent Rules正例 — 口语化流程约束",
            expected_dimensions=["agent_rules"],
            test_focus="口语化流程约束",
        ),
        MemoryEvalCase(
            id="ext_rules_14", layer=EvalLayer.EXTRACT, query_type=QueryType.EXTRACT_AGENT_RULES,
            query="你要专注于金融行业的客户分析",
            description="Agent Rules正例 — 领域定义",
            expected_dimensions=["agent_rules"],
            test_focus="领域定义",
        ),
        MemoryEvalCase(
            id="ext_rules_15", layer=EvalLayer.EXTRACT, query_type=QueryType.EXTRACT_AGENT_RULES,
            query="你每次回答前先确认我的需求",
            description="Agent Rules正例 — 流程约束",
            expected_dimensions=["agent_rules"],
            test_focus="流程约束",
        ),
        MemoryEvalCase(
            id="ext_rules_16", layer=EvalLayer.EXTRACT, query_type=QueryType.EXTRACT_AGENT_RULES,
            query="你给我建议的时候要给出至少三个方案",
            description="Agent Rules正例 — 输出数量约束",
            expected_dimensions=["agent_rules"],
            test_focus="输出数量约束",
        ),
        MemoryEvalCase(
            id="ext_rules_17", layer=EvalLayer.EXTRACT, query_type=QueryType.EXTRACT_AGENT_RULES,
            query="你不要编造数据，不确定就说不知道",
            description="Agent Rules正例 — 诚实性约束",
            expected_dimensions=["agent_rules"],
            test_focus="诚实性约束",
        ),
        MemoryEvalCase(
            id="ext_rules_18", layer=EvalLayer.EXTRACT, query_type=QueryType.EXTRACT_AGENT_RULES,
            query="你帮我写邮件的时候要用正式的商务语气",
            description="Agent Rules正例 — 风格约束",
            expected_dimensions=["agent_rules"],
            test_focus="风格约束",
        ),
        MemoryEvalCase(
            id="ext_rules_19", layer=EvalLayer.EXTRACT, query_type=QueryType.EXTRACT_AGENT_RULES,
            query="你做预测分析时要给出置信度",
            description="Agent Rules正例 — 输出内容约束",
            expected_dimensions=["agent_rules"],
            test_focus="输出内容约束",
        ),
        MemoryEvalCase(
            id="ext_rules_20", layer=EvalLayer.EXTRACT, query_type=QueryType.EXTRACT_AGENT_RULES,
            query="金额统一用万元为单位",
            description="Agent Rules正例 — 无主语格式指令",
            expected_dimensions=["agent_rules"],
            test_focus="无主语格式指令",
        ),
        MemoryEvalCase(
            id="ext_rules_21", layer=EvalLayer.EXTRACT, query_type=QueryType.EXTRACT_AGENT_RULES,
            query="你就像我的私人助理一样",
            description="Agent Rules正例 — 比喻式角色定义",
            expected_dimensions=["agent_rules"],
            test_focus="比喻式角色定义",
        ),
        MemoryEvalCase(
            id="ext_rules_22", layer=EvalLayer.EXTRACT, query_type=QueryType.EXTRACT_AGENT_RULES,
            query="之前让你用表格，现在改成图表",
            description="Agent Rules正例 — 更新覆盖指令",
            expected_dimensions=["agent_rules"],
            test_focus="更新覆盖指令",
        ),
        MemoryEvalCase(
            id="ext_rules_23", layer=EvalLayer.EXTRACT, query_type=QueryType.EXTRACT_AGENT_RULES,
            query="你现在可以自动发邮件了，不用每次都问我",
            description="Agent Rules正例 — 取消旧约束",
            expected_dimensions=["agent_rules"],
            test_focus="取消旧约束",
        ),
        MemoryEvalCase(
            id="ext_rules_24", layer=EvalLayer.EXTRACT, query_type=QueryType.EXTRACT_AGENT_RULES,
            query="你的跟进节奏改一下，从3/7/14天改成1/3/7天",
            description="Agent Rules正例 — 更新流程参数",
            expected_dimensions=["agent_rules"],
            test_focus="更新流程参数",
        ),
        MemoryEvalCase(
            id="ext_rules_25", layer=EvalLayer.EXTRACT, query_type=QueryType.EXTRACT_AGENT_RULES,
            query="你说话要结构化，先结论后论据",
            description="Agent Rules正例 — 沟通风格指令",
            expected_dimensions=["agent_rules"],
            test_focus="沟通风格指令",
        ),
    ]


# ═══════════════════════════════════════════════════════════
# D. Entities 正例（#76 ~ #100）
# ═══════════════════════════════════════════════════════════

def _entities_cases() -> list[MemoryEvalCase]:
    """第三方客观事实（客户、联系人、竞品等）"""
    return [
        MemoryEvalCase(
            id="ext_entity_01", layer=EvalLayer.EXTRACT, query_type=QueryType.EXTRACT_ENTITIES,
            query="华为的张伟说话很直接，开会不要绕弯子",
            description="Entities正例 — 标准第三方人物描述",
            expected_dimensions=["entities"],
            test_focus="标准第三方人物描述",
        ),
        MemoryEvalCase(
            id="ext_entity_02", layer=EvalLayer.EXTRACT, query_type=QueryType.EXTRACT_ENTITIES,
            query="张总那边最近在忙重组，估计这个月没空",
            description="Entities正例 — 省略公司名的实体信息",
            expected_dimensions=["entities"],
            test_focus="省略公司名的实体信息",
        ),
        MemoryEvalCase(
            id="ext_entity_03", layer=EvalLayer.EXTRACT, query_type=QueryType.EXTRACT_ENTITIES,
            query="华为和腾讯都在评估我们的方案，但侧重点不同",
            description="Entities正例 — 多实体混合",
            expected_dimensions=["entities"],
            test_focus="多实体混合",
        ),
        MemoryEvalCase(
            id="ext_entity_04", layer=EvalLayer.EXTRACT, query_type=QueryType.EXTRACT_ENTITIES,
            query="我觉得这个客户不太靠谱，拖了三个月了",
            description="Entities正例 — \"这个客户\"指代+主观判断",
            expected_dimensions=["entities"],
            test_focus="\"这个客户\"指代+主观判断",
        ),
        MemoryEvalCase(
            id="ext_entity_05", layer=EvalLayer.EXTRACT, query_type=QueryType.EXTRACT_ENTITIES,
            query="听说他们内部在打架，技术部和采购部意见不一致",
            description="Entities正例 — \"他们\"指代+内部关系",
            expected_dimensions=["entities"],
            test_focus="\"他们\"指代+内部关系",
        ),
        MemoryEvalCase(
            id="ext_entity_06", layer=EvalLayer.EXTRACT, query_type=QueryType.EXTRACT_ENTITIES,
            query="王强这个人吧，表面热情但决策很慢",
            description="Entities正例 — 口语化人物评价",
            expected_dimensions=["entities"],
            test_focus="口语化人物评价",
        ),
        MemoryEvalCase(
            id="ext_entity_07", layer=EvalLayer.EXTRACT, query_type=QueryType.EXTRACT_ENTITIES,
            query="泰克科技去年营收5个亿，今年目标8个亿",
            description="Entities正例 — 公司数据+趋势",
            expected_dimensions=["entities"],
            test_focus="公司数据+趋势",
        ),
        MemoryEvalCase(
            id="ext_entity_08", layer=EvalLayer.EXTRACT, query_type=QueryType.EXTRACT_ENTITIES,
            query="那个项目其实是张伟在推，李娜只是挂名",
            description="Entities正例 — 内部权力关系",
            expected_dimensions=["entities"],
            test_focus="内部权力关系",
        ),
        MemoryEvalCase(
            id="ext_entity_09", layer=EvalLayer.EXTRACT, query_type=QueryType.EXTRACT_ENTITIES,
            query="比亚迪的预算审批要过五关斩六将",
            description="Entities正例 — 比喻式流程描述",
            expected_dimensions=["entities"],
            test_focus="比喻式流程描述",
        ),
        MemoryEvalCase(
            id="ext_entity_10", layer=EvalLayer.EXTRACT, query_type=QueryType.EXTRACT_ENTITIES,
            query="陈刚私下说基本定了选我们，但别声张",
            description="Entities正例 — 口头承诺+保密",
            expected_dimensions=["entities"],
            test_focus="口头承诺+保密",
        ),
        MemoryEvalCase(
            id="ext_entity_11", layer=EvalLayer.EXTRACT, query_type=QueryType.EXTRACT_ENTITIES,
            query="这家公司的决策链特别长，从部门到集团要两个月",
            description="Entities正例 — \"这家公司\"指代",
            expected_dimensions=["entities"],
            test_focus="\"这家公司\"指代",
        ),
        MemoryEvalCase(
            id="ext_entity_12", layer=EvalLayer.EXTRACT, query_type=QueryType.EXTRACT_ENTITIES,
            query="上次见面他提到竞品报价比我们低20%",
            description="Entities正例 — 竞争情报",
            expected_dimensions=["entities"],
            test_focus="竞争情报",
        ),
        MemoryEvalCase(
            id="ext_entity_13", layer=EvalLayer.EXTRACT, query_type=QueryType.EXTRACT_ENTITIES,
            query="赵敏下个月要去美国出差，这段时间联系不上",
            description="Entities正例 — 时效性信息",
            expected_dimensions=["entities"],
            test_focus="时效性信息",
        ),
        MemoryEvalCase(
            id="ext_entity_14", layer=EvalLayer.EXTRACT, query_type=QueryType.EXTRACT_ENTITIES,
            query="华为内部审批流程复杂，至少要3-4周",
            description="Entities正例 — 客户流程事实",
            expected_dimensions=["entities"],
            test_focus="客户流程事实",
        ),
        MemoryEvalCase(
            id="ext_entity_15", layer=EvalLayer.EXTRACT, query_type=QueryType.EXTRACT_ENTITIES,
            query="腾讯在同时评估用友和我们",
            description="Entities正例 — 竞品+客户关联",
            expected_dimensions=["entities"],
            test_focus="竞品+客户关联",
        ),
        MemoryEvalCase(
            id="ext_entity_16", layer=EvalLayer.EXTRACT, query_type=QueryType.EXTRACT_ENTITIES,
            query="招行对安全认证要求很高，必须有等保三级",
            description="Entities正例 — 客户合规要求",
            expected_dimensions=["entities"],
            test_focus="客户合规要求",
        ),
        MemoryEvalCase(
            id="ext_entity_17", layer=EvalLayer.EXTRACT, query_type=QueryType.EXTRACT_ENTITIES,
            query="张总喜欢看PPT，不喜欢看长文档",
            description="Entities正例 — 第三方偏好",
            expected_dimensions=["entities"],
            test_focus="第三方偏好",
        ),
        MemoryEvalCase(
            id="ext_entity_18", layer=EvalLayer.EXTRACT, query_type=QueryType.EXTRACT_ENTITIES,
            query="客户反馈我们响应速度比竞品快",
            description="Entities正例 — 第三方反馈（主语是客户）",
            expected_dimensions=["entities"],
            test_focus="第三方反馈（主语是客户）",
        ),
        MemoryEvalCase(
            id="ext_entity_19", layer=EvalLayer.EXTRACT, query_type=QueryType.EXTRACT_ENTITIES,
            query="华为那边要求用正式语气沟通",
            description="Entities正例 — 客户要求（陈述式）",
            expected_dimensions=["entities"],
            test_focus="客户要求（陈述式）",
        ),
        MemoryEvalCase(
            id="ext_entity_20", layer=EvalLayer.EXTRACT, query_type=QueryType.EXTRACT_ENTITIES,
            query="比亚迪之前用SAP，体验不太好",
            description="Entities正例 — 客户历史系统",
            expected_dimensions=["entities"],
            test_focus="客户历史系统",
        ),
        MemoryEvalCase(
            id="ext_entity_21", layer=EvalLayer.EXTRACT, query_type=QueryType.EXTRACT_ENTITIES,
            query="小米的技术团队偏好微服务架构",
            description="Entities正例 — 客户技术偏好",
            expected_dimensions=["entities"],
            test_focus="客户技术偏好",
        ),
        MemoryEvalCase(
            id="ext_entity_22", layer=EvalLayer.EXTRACT, query_type=QueryType.EXTRACT_ENTITIES,
            query="字节的孙丽做事雷厉风行，邮件必须当天回",
            description="Entities正例 — 联系人风格+要求",
            expected_dimensions=["entities"],
            test_focus="联系人风格+要求",
        ),
        MemoryEvalCase(
            id="ext_entity_23", layer=EvalLayer.EXTRACT, query_type=QueryType.EXTRACT_ENTITIES,
            query="阿里内部有自研CRM团队，我们要证明比自研好",
            description="Entities正例 — 内部竞争情报",
            expected_dimensions=["entities"],
            test_focus="内部竞争情报",
        ),
        MemoryEvalCase(
            id="ext_entity_24", layer=EvalLayer.EXTRACT, query_type=QueryType.EXTRACT_ENTITIES,
            query="京东的刘洋很务实，只看落地效果不看PPT",
            description="Entities正例 — 联系人决策风格",
            expected_dimensions=["entities"],
            test_focus="联系人决策风格",
        ),
        MemoryEvalCase(
            id="ext_entity_25", layer=EvalLayer.EXTRACT, query_type=QueryType.EXTRACT_ENTITIES,
            query="美团要求私有化部署，数据不能出他们的机房",
            description="Entities正例 — 客户部署要求",
            expected_dimensions=["entities"],
            test_focus="客户部署要求",
        ),
    ]


# ═══════════════════════════════════════════════════════════
# E. 不提取场景（#101 ~ #130）
# ═══════════════════════════════════════════════════════════

def _no_extract_cases() -> list[MemoryEvalCase]:
    """抑制过度提取 — 这些都不应产生任何记忆"""
    return [
        MemoryEvalCase(
            id="ext_none_01", layer=EvalLayer.EXTRACT, query_type=QueryType.EXTRACT_NONE,
            query="帮我查一下上个月的销售数据",
            description="不提取 — 纯操作指令",
            expected_dimensions=[], negative=True,
            test_focus="纯操作指令",
        ),
        MemoryEvalCase(
            id="ext_none_02", layer=EvalLayer.EXTRACT, query_type=QueryType.EXTRACT_NONE,
            query="好的，收到",
            description="不提取 — 简单确认",
            expected_dimensions=[], negative=True,
            test_focus="简单确认",
        ),
        MemoryEvalCase(
            id="ext_none_03", layer=EvalLayer.EXTRACT, query_type=QueryType.EXTRACT_NONE,
            query="把这个商机的阶段改成proposal",
            description="不提取 — 数据修改指令",
            expected_dimensions=[], negative=True,
            test_focus="数据修改指令",
        ),
        MemoryEvalCase(
            id="ext_none_04", layer=EvalLayer.EXTRACT, query_type=QueryType.EXTRACT_NONE,
            query="发一封邮件给张总，内容就按上次说的",
            description="不提取 — 一次性操作",
            expected_dimensions=[], negative=True,
            test_focus="一次性操作",
        ),
        MemoryEvalCase(
            id="ext_none_05", layer=EvalLayer.EXTRACT, query_type=QueryType.EXTRACT_NONE,
            query="嗯嗯，继续",
            description="不提取 — 对话延续",
            expected_dimensions=[], negative=True,
            test_focus="对话延续",
        ),
        MemoryEvalCase(
            id="ext_none_06", layer=EvalLayer.EXTRACT, query_type=QueryType.EXTRACT_NONE,
            query="等一下，我想想",
            description="不提取 — 思考中",
            expected_dimensions=[], negative=True,
            test_focus="思考中",
        ),
        MemoryEvalCase(
            id="ext_none_07", layer=EvalLayer.EXTRACT, query_type=QueryType.EXTRACT_NONE,
            query="算了，不用了",
            description="不提取 — 取消操作（非取消规则）",
            expected_dimensions=[], negative=True,
            test_focus="取消操作（非取消规则）",
        ),
        MemoryEvalCase(
            id="ext_none_08", layer=EvalLayer.EXTRACT, query_type=QueryType.EXTRACT_NONE,
            query="这个数据对吗？帮我核实一下",
            description="不提取 — 质疑+操作",
            expected_dimensions=[], negative=True,
            test_focus="质疑+操作",
        ),
        MemoryEvalCase(
            id="ext_none_09", layer=EvalLayer.EXTRACT, query_type=QueryType.EXTRACT_NONE,
            query="把刚才的结果导出Excel发给我",
            description="不提取 — 导出操作",
            expected_dimensions=[], negative=True,
            test_focus="导出操作",
        ),
        MemoryEvalCase(
            id="ext_none_10", layer=EvalLayer.EXTRACT, query_type=QueryType.EXTRACT_NONE,
            query="今天天气不错",
            description="不提取 — 闲聊",
            expected_dimensions=[], negative=True,
            test_focus="闲聊",
        ),
        MemoryEvalCase(
            id="ext_none_11", layer=EvalLayer.EXTRACT, query_type=QueryType.EXTRACT_NONE,
            query="帮我约一下明天下午3点和张总的会",
            description="不提取 — 日程操作",
            expected_dimensions=[], negative=True,
            test_focus="日程操作",
        ),
        MemoryEvalCase(
            id="ext_none_12", layer=EvalLayer.EXTRACT, query_type=QueryType.EXTRACT_NONE,
            query="刚才那个分析再跑一遍",
            description="不提取 — 重复操作",
            expected_dimensions=[], negative=True,
            test_focus="重复操作",
        ),
        MemoryEvalCase(
            id="ext_none_13", layer=EvalLayer.EXTRACT, query_type=QueryType.EXTRACT_NONE,
            query="华为的商机有几个？",
            description="不提取 — 纯查询",
            expected_dimensions=[], negative=True,
            test_focus="纯查询",
        ),
        MemoryEvalCase(
            id="ext_none_14", layer=EvalLayer.EXTRACT, query_type=QueryType.EXTRACT_NONE,
            query="这个月还有多少预算？",
            description="不提取 — 纯查询",
            expected_dimensions=[], negative=True,
            test_focus="纯查询",
        ),
        MemoryEvalCase(
            id="ext_none_15", layer=EvalLayer.EXTRACT, query_type=QueryType.EXTRACT_NONE,
            query="帮我标记这个客户为VIP",
            description="不提取 — 数据操作",
            expected_dimensions=[], negative=True,
            test_focus="数据操作",
        ),
        MemoryEvalCase(
            id="ext_none_16", layer=EvalLayer.EXTRACT, query_type=QueryType.EXTRACT_NONE,
            query="上面那个表格能不能横向展示？",
            description="不提取 — 当前操作请求（非持久偏好）",
            expected_dimensions=[], negative=True,
            test_focus="当前操作请求（非持久偏好）",
        ),
        MemoryEvalCase(
            id="ext_none_17", layer=EvalLayer.EXTRACT, query_type=QueryType.EXTRACT_NONE,
            query="这次分析深入一些",
            description="不提取 — 单次调整（非持久）",
            expected_dimensions=[], negative=True,
            test_focus="单次调整（非持久）",
        ),
        MemoryEvalCase(
            id="ext_none_18", layer=EvalLayer.EXTRACT, query_type=QueryType.EXTRACT_NONE,
            query="感觉你像私人助理",
            description="不提取 — 感叹/评价（非指令）",
            expected_dimensions=[], negative=True,
            test_focus="感叹/评价（非指令）",
        ),
        MemoryEvalCase(
            id="ext_none_19", layer=EvalLayer.EXTRACT, query_type=QueryType.EXTRACT_NONE,
            query="帮我问一下张总预算够不够",
            description="不提取 — 操作指令",
            expected_dimensions=[], negative=True,
            test_focus="操作指令",
        ),
        MemoryEvalCase(
            id="ext_none_20", layer=EvalLayer.EXTRACT, query_type=QueryType.EXTRACT_NONE,
            query="下周二我要去拜访客户B",
            description="不提取 — 一次性日程",
            expected_dimensions=[], negative=True,
            test_focus="一次性日程",
        ),
        MemoryEvalCase(
            id="ext_none_21", layer=EvalLayer.EXTRACT, query_type=QueryType.EXTRACT_NONE,
            query="谢谢，辛苦了",
            description="不提取 — 礼貌用语",
            expected_dimensions=[], negative=True,
            test_focus="礼貌用语",
        ),
        MemoryEvalCase(
            id="ext_none_22", layer=EvalLayer.EXTRACT, query_type=QueryType.EXTRACT_NONE,
            query="这个方案不错，就这样吧",
            description="不提取 — 确认/评价",
            expected_dimensions=[], negative=True,
            test_focus="确认/评价",
        ),
        MemoryEvalCase(
            id="ext_none_23", layer=EvalLayer.EXTRACT, query_type=QueryType.EXTRACT_NONE,
            query="帮我把这段话翻译成英文",
            description="不提取 — 一次性翻译操作",
            expected_dimensions=[], negative=True,
            test_focus="一次性翻译操作",
        ),
        MemoryEvalCase(
            id="ext_none_24", layer=EvalLayer.EXTRACT, query_type=QueryType.EXTRACT_NONE,
            query="再详细说说第三点",
            description="不提取 — 追问当前内容",
            expected_dimensions=[], negative=True,
            test_focus="追问当前内容",
        ),
        MemoryEvalCase(
            id="ext_none_25", layer=EvalLayer.EXTRACT, query_type=QueryType.EXTRACT_NONE,
            query="华为那个项目金额是多少来着？",
            description="不提取 — 纯查询",
            expected_dimensions=[], negative=True,
            test_focus="纯查询",
        ),
        MemoryEvalCase(
            id="ext_none_26", layer=EvalLayer.EXTRACT, query_type=QueryType.EXTRACT_NONE,
            query="你刚才说的那个数据来源是哪里",
            description="不提取 — 追问来源",
            expected_dimensions=[], negative=True,
            test_focus="追问来源",
        ),
        MemoryEvalCase(
            id="ext_none_27", layer=EvalLayer.EXTRACT, query_type=QueryType.EXTRACT_NONE,
            query="帮我生成一份本周的工作总结",
            description="不提取 — 一次性生成任务",
            expected_dimensions=[], negative=True,
            test_focus="一次性生成任务",
        ),
        MemoryEvalCase(
            id="ext_none_28", layer=EvalLayer.EXTRACT, query_type=QueryType.EXTRACT_NONE,
            query="这个客户的联系方式是什么",
            description="不提取 — 纯查询",
            expected_dimensions=[], negative=True,
            test_focus="纯查询",
        ),
        MemoryEvalCase(
            id="ext_none_29", layer=EvalLayer.EXTRACT, query_type=QueryType.EXTRACT_NONE,
            query="把刚才的内容整理成邮件格式",
            description="不提取 — 当前操作",
            expected_dimensions=[], negative=True,
            test_focus="当前操作",
        ),
        MemoryEvalCase(
            id="ext_none_30", layer=EvalLayer.EXTRACT, query_type=QueryType.EXTRACT_NONE,
            query="算了还是用表格吧",
            description="不提取 — 单次调整（无泛化对象）",
            expected_dimensions=[], negative=True,
            test_focus="单次调整（无泛化对象）",
        ),
    ]


# ═══════════════════════════════════════════════════════════
# F. 混合意图场景（#131 ~ #160）
# ═══════════════════════════════════════════════════════════

def _mixed_intent_cases() -> list[MemoryEvalCase]:
    """一句话触发两个或以上维度，各路独立提取"""
    return [
        MemoryEvalCase(
            id="ext_mixed_01", layer=EvalLayer.EXTRACT, query_type=QueryType.EXTRACT_MIXED,
            query="我是做金融行业的，你要熟悉银行的业务流程",
            description="混合意图 — 身份+领域指令",
            expected_dimensions=["profile", "agent_rules"],
            test_focus="身份+领域指令",
        ),
        MemoryEvalCase(
            id="ext_mixed_02", layer=EvalLayer.EXTRACT, query_type=QueryType.EXTRACT_MIXED,
            query="我喜欢简洁的风格，你回复不要超过3句话",
            description="混合意图 — 偏好+约束",
            expected_dimensions=["preferences", "agent_rules"],
            test_focus="偏好+约束",
        ),
        MemoryEvalCase(
            id="ext_mixed_03", layer=EvalLayer.EXTRACT, query_type=QueryType.EXTRACT_MIXED,
            query="我是华东区的，华为张伟是我的重点客户",
            description="混合意图 — 身份+实体关系",
            expected_dimensions=["profile", "entities"],
            test_focus="身份+实体关系",
        ),
        MemoryEvalCase(
            id="ext_mixed_04", layer=EvalLayer.EXTRACT, query_type=QueryType.EXTRACT_MIXED,
            query="我习惯看表格，你以后都用表格展示",
            description="混合意图 — 偏好+持久指令",
            expected_dimensions=["preferences", "agent_rules"],
            test_focus="偏好+持久指令",
        ),
        MemoryEvalCase(
            id="ext_mixed_05", layer=EvalLayer.EXTRACT, query_type=QueryType.EXTRACT_MIXED,
            query="我管理10人团队，主要跟进腾讯和阿里",
            description="混合意图 — 身份+实体（关系动词）",
            expected_dimensions=["profile", "entities"],
            test_focus="身份+实体（关系动词）",
        ),
        MemoryEvalCase(
            id="ext_mixed_06", layer=EvalLayer.EXTRACT, query_type=QueryType.EXTRACT_MIXED,
            query="你是我的销售助理，我负责华南区",
            description="混合意图 — 角色定义+身份",
            expected_dimensions=["agent_rules", "profile"],
            test_focus="角色定义+身份",
        ),
        MemoryEvalCase(
            id="ext_mixed_07", layer=EvalLayer.EXTRACT, query_type=QueryType.EXTRACT_MIXED,
            query="我不喜欢长报告，你控制在一页以内",
            description="混合意图 — 偏好+约束",
            expected_dimensions=["preferences", "agent_rules"],
            test_focus="偏好+约束",
        ),
        MemoryEvalCase(
            id="ext_mixed_08", layer=EvalLayer.EXTRACT, query_type=QueryType.EXTRACT_MIXED,
            query="我们公司做SaaS的，竞品是Salesforce",
            description="混合意图 — 公司信息+竞品实体",
            expected_dimensions=["profile", "entities"],
            test_focus="公司信息+竞品实体",
        ),
        MemoryEvalCase(
            id="ext_mixed_09", layer=EvalLayer.EXTRACT, query_type=QueryType.EXTRACT_MIXED,
            query="我偏好邮件沟通，你发邮件前先让我确认",
            description="混合意图 — 偏好+流程约束",
            expected_dimensions=["preferences", "agent_rules"],
            test_focus="偏好+流程约束",
        ),
        MemoryEvalCase(
            id="ext_mixed_10", layer=EvalLayer.EXTRACT, query_type=QueryType.EXTRACT_MIXED,
            query="我是技术出身，华为那边的技术评估我来对接",
            description="混合意图 — 背景+客户关系",
            expected_dimensions=["profile", "entities"],
            test_focus="背景+客户关系（关系动词）",
        ),
        MemoryEvalCase(
            id="ext_mixed_11", layer=EvalLayer.EXTRACT, query_type=QueryType.EXTRACT_MIXED,
            query="你要专注制造业，我在这个行业做了8年",
            description="混合意图 — 领域指令+经验",
            expected_dimensions=["agent_rules", "profile"],
            test_focus="领域指令+经验",
        ),
        MemoryEvalCase(
            id="ext_mixed_12", layer=EvalLayer.EXTRACT, query_type=QueryType.EXTRACT_MIXED,
            query="我喜欢数据驱动决策，分析报告要有数据支撑",
            description="混合意图 — 偏好+输出要求",
            expected_dimensions=["preferences", "agent_rules"],
            test_focus="偏好+输出要求",
        ),
        MemoryEvalCase(
            id="ext_mixed_13", layer=EvalLayer.EXTRACT, query_type=QueryType.EXTRACT_MIXED,
            query="我负责大客户，张伟和李娜是我的关键联系人",
            description="混合意图 — 职责+实体",
            expected_dimensions=["profile", "entities"],
            test_focus="职责+实体",
        ),
        MemoryEvalCase(
            id="ext_mixed_14", layer=EvalLayer.EXTRACT, query_type=QueryType.EXTRACT_MIXED,
            query="你说话直接点，我这个人不喜欢绕弯子",
            description="混合意图 — 指令+性格偏好",
            expected_dimensions=["agent_rules", "preferences"],
            test_focus="指令+性格偏好",
        ),
        MemoryEvalCase(
            id="ext_mixed_15", layer=EvalLayer.EXTRACT, query_type=QueryType.EXTRACT_MIXED,
            query="我习惯周一开会，你每周一早上给我准备会议材料",
            description="混合意图 — 习惯+持久指令",
            expected_dimensions=["preferences", "agent_rules"],
            test_focus="习惯+持久指令",
        ),
        MemoryEvalCase(
            id="ext_mixed_16", layer=EvalLayer.EXTRACT, query_type=QueryType.EXTRACT_MIXED,
            query="你是我的CRM顾问，我们用的是纷享销客",
            description="混合意图 — 角色+工具信息",
            expected_dimensions=["agent_rules", "profile"],
            test_focus="角色+工具信息",
        ),
        MemoryEvalCase(
            id="ext_mixed_17", layer=EvalLayer.EXTRACT, query_type=QueryType.EXTRACT_MIXED,
            query="我喜欢看折线图，你做趋势分析时用折线图",
            description="混合意图 — 偏好+格式指令",
            expected_dimensions=["preferences", "agent_rules"],
            test_focus="偏好+格式指令",
        ),
        MemoryEvalCase(
            id="ext_mixed_18", layer=EvalLayer.EXTRACT, query_type=QueryType.EXTRACT_MIXED,
            query="我们团队有8个人，主要服务字节和美团",
            description="混合意图 — 团队+客户",
            expected_dimensions=["profile", "entities"],
            test_focus="团队+客户（关系动词）",
        ),
        MemoryEvalCase(
            id="ext_mixed_19", layer=EvalLayer.EXTRACT, query_type=QueryType.EXTRACT_MIXED,
            query="你要用通俗语言，我们团队不都是技术背景",
            description="混合意图 — 风格指令+团队背景",
            expected_dimensions=["agent_rules", "profile"],
            test_focus="风格指令+团队背景",
        ),
        MemoryEvalCase(
            id="ext_mixed_20", layer=EvalLayer.EXTRACT, query_type=QueryType.EXTRACT_MIXED,
            query="我在意响应速度，你收到消息后1小时内回复",
            description="混合意图 — 偏好+时效约束",
            expected_dimensions=["preferences", "agent_rules"],
            test_focus="偏好+时效约束",
        ),
        MemoryEvalCase(
            id="ext_mixed_21", layer=EvalLayer.EXTRACT, query_type=QueryType.EXTRACT_MIXED,
            query="我是新来的产品经理，你帮我熟悉CRM模块的功能",
            description="混合意图 — 身份+任务定义",
            expected_dimensions=["profile", "agent_rules"],
            test_focus="身份+任务定义",
        ),
        MemoryEvalCase(
            id="ext_mixed_22", layer=EvalLayer.EXTRACT, query_type=QueryType.EXTRACT_MIXED,
            query="我更关注转化率，你每次分析都要带转化漏斗",
            description="混合意图 — 偏好+输出要求",
            expected_dimensions=["preferences", "agent_rules"],
            test_focus="偏好+输出要求",
        ),
        MemoryEvalCase(
            id="ext_mixed_23", layer=EvalLayer.EXTRACT, query_type=QueryType.EXTRACT_MIXED,
            query="我们公司主打金融行业，招行是我们的标杆客户",
            description="混合意图 — 公司定位+客户",
            expected_dimensions=["profile", "entities"],
            test_focus="公司定位+客户",
        ),
        MemoryEvalCase(
            id="ext_mixed_24", layer=EvalLayer.EXTRACT, query_type=QueryType.EXTRACT_MIXED,
            query="你要专业一点，我是技术出身的",
            description="混合意图 — 风格指令+背景",
            expected_dimensions=["agent_rules", "profile"],
            test_focus="风格指令+背景",
        ),
        MemoryEvalCase(
            id="ext_mixed_25", layer=EvalLayer.EXTRACT, query_type=QueryType.EXTRACT_MIXED,
            query="我讨厌啰嗦，你回复精炼一些",
            description="混合意图 — 厌恶+约束",
            expected_dimensions=["preferences", "agent_rules"],
            test_focus="厌恶+约束",
        ),
        MemoryEvalCase(
            id="ext_mixed_26", layer=EvalLayer.EXTRACT, query_type=QueryType.EXTRACT_MIXED,
            query="我负责华东区，腾讯王强是我最大的客户",
            description="混合意图 — 区域+客户关系",
            expected_dimensions=["profile", "entities"],
            test_focus="区域+客户关系",
        ),
        MemoryEvalCase(
            id="ext_mixed_27", layer=EvalLayer.EXTRACT, query_type=QueryType.EXTRACT_MIXED,
            query="你是我的竞品分析师，我们主要和用友竞争",
            description="混合意图 — 角色+竞品信息",
            expected_dimensions=["agent_rules", "entities"],
            test_focus="角色+竞品信息",
        ),
        MemoryEvalCase(
            id="ext_mixed_28", layer=EvalLayer.EXTRACT, query_type=QueryType.EXTRACT_MIXED,
            query="我喜欢结构化表达，你回复用1234列出来",
            description="混合意图 — 偏好+格式指令",
            expected_dimensions=["preferences", "agent_rules"],
            test_focus="偏好+格式指令",
        ),
        MemoryEvalCase(
            id="ext_mixed_29", layer=EvalLayer.EXTRACT, query_type=QueryType.EXTRACT_MIXED,
            query="我们公司200人规模，华为是我们最大的客户",
            description="混合意图 — 公司规模+客户",
            expected_dimensions=["profile", "entities"],
            test_focus="公司规模+客户",
        ),
        MemoryEvalCase(
            id="ext_mixed_30", layer=EvalLayer.EXTRACT, query_type=QueryType.EXTRACT_MIXED,
            query="你要像军师一样给我出谋划策，我比较依赖数据决策",
            description="混合意图 — 角色风格+决策偏好",
            expected_dimensions=["agent_rules", "preferences"],
            test_focus="角色风格+决策偏好",
        ),
    ]


# ═══════════════════════════════════════════════════════════
# G. 边界对抗场景（#161 ~ #200）
# ═══════════════════════════════════════════════════════════

def _boundary_cases() -> list[MemoryEvalCase]:
    """专门测试维度间混淆的模糊归属"""
    return [
        # G1. Preferences vs Agent Rules 边界（#161 ~ #175）
        MemoryEvalCase(
            id="ext_boundary_01", layer=EvalLayer.EXTRACT, query_type=QueryType.EXTRACT_BOUNDARY,
            query="金额统一用万为单位",
            description="边界 — 无主语，隐含主语是Agent输出→rules",
            expected_dimensions=["agent_rules"],
            test_focus="pref vs rules: 无主语，隐含主语是Agent输出→rules",
        ),
        MemoryEvalCase(
            id="ext_boundary_02", layer=EvalLayer.EXTRACT, query_type=QueryType.EXTRACT_BOUNDARY,
            query="我要求金额用万为单位",
            description="边界 — \"我要求\"是个人标准表达→pref",
            expected_dimensions=["preferences"],
            test_focus="pref vs rules: \"我要求\"是个人标准表达→pref",
        ),
        MemoryEvalCase(
            id="ext_boundary_03", layer=EvalLayer.EXTRACT, query_type=QueryType.EXTRACT_BOUNDARY,
            query="数据展示要有对比",
            description="边界 — 无主语输出要求→rules",
            expected_dimensions=["agent_rules"],
            test_focus="pref vs rules: 无主语输出要求→rules",
        ),
        MemoryEvalCase(
            id="ext_boundary_04", layer=EvalLayer.EXTRACT, query_type=QueryType.EXTRACT_BOUNDARY,
            query="我觉得有对比的数据更好理解",
            description="边界 — \"我觉得\"是偏好→pref",
            expected_dimensions=["preferences"],
            test_focus="pref vs rules: \"我觉得\"是偏好→pref",
        ),
        MemoryEvalCase(
            id="ext_boundary_05", layer=EvalLayer.EXTRACT, query_type=QueryType.EXTRACT_BOUNDARY,
            query="报告里要有图表",
            description="边界 — 主语是Agent产物\"报告\"→rules",
            expected_dimensions=["agent_rules"],
            test_focus="pref vs rules: 主语是Agent产物\"报告\"→rules",
        ),
        MemoryEvalCase(
            id="ext_boundary_06", layer=EvalLayer.EXTRACT, query_type=QueryType.EXTRACT_BOUNDARY,
            query="我更喜欢看图表而不是纯文字",
            description="边界 — \"我更喜欢\"是偏好→pref",
            expected_dimensions=["preferences"],
            test_focus="pref vs rules: \"我更喜欢\"是偏好→pref",
        ),
        MemoryEvalCase(
            id="ext_boundary_07", layer=EvalLayer.EXTRACT, query_type=QueryType.EXTRACT_BOUNDARY,
            query="每次分析都要带上数据来源",
            description="边界 — \"每次\"暗示持久+主语是分析→rules",
            expected_dimensions=["agent_rules"],
            test_focus="pref vs rules: \"每次\"暗示持久+主语是分析→rules",
        ),
        MemoryEvalCase(
            id="ext_boundary_08", layer=EvalLayer.EXTRACT, query_type=QueryType.EXTRACT_BOUNDARY,
            query="我比较看重数据来源的可靠性",
            description="边界 — \"我比较看重\"是个人标准→pref",
            expected_dimensions=["preferences"],
            test_focus="pref vs rules: \"我比较看重\"是个人标准→pref",
        ),
        MemoryEvalCase(
            id="ext_boundary_09", layer=EvalLayer.EXTRACT, query_type=QueryType.EXTRACT_BOUNDARY,
            query="邮件要简短专业",
            description="边界 — 主语是Agent产物\"邮件\"→rules",
            expected_dimensions=["agent_rules"],
            test_focus="pref vs rules: 主语是Agent产物\"邮件\"→rules",
        ),
        MemoryEvalCase(
            id="ext_boundary_10", layer=EvalLayer.EXTRACT, query_type=QueryType.EXTRACT_BOUNDARY,
            query="我喜欢简短专业的邮件风格",
            description="边界 — \"我喜欢\"是偏好→pref",
            expected_dimensions=["preferences"],
            test_focus="pref vs rules: \"我喜欢\"是偏好→pref",
        ),
        MemoryEvalCase(
            id="ext_boundary_11", layer=EvalLayer.EXTRACT, query_type=QueryType.EXTRACT_BOUNDARY,
            query="以后分析要深入一些",
            description="边界 — \"以后\"暗示持久→rules",
            expected_dimensions=["agent_rules"],
            test_focus="rules vs 不提取: \"以后\"暗示持久→rules",
        ),
        MemoryEvalCase(
            id="ext_boundary_12", layer=EvalLayer.EXTRACT, query_type=QueryType.EXTRACT_BOUNDARY,
            query="回复要带上参考链接",
            description="边界 — 主语是Agent产物\"回复\"→rules",
            expected_dimensions=["agent_rules"],
            test_focus="pref vs rules: 主语是Agent产物\"回复\"→rules",
        ),
        MemoryEvalCase(
            id="ext_boundary_13", layer=EvalLayer.EXTRACT, query_type=QueryType.EXTRACT_BOUNDARY,
            query="我希望能看到参考链接",
            description="边界 — \"我希望\"是偏好→pref",
            expected_dimensions=["preferences"],
            test_focus="pref vs rules: \"我希望\"是偏好→pref",
        ),
        MemoryEvalCase(
            id="ext_boundary_14", layer=EvalLayer.EXTRACT, query_type=QueryType.EXTRACT_BOUNDARY,
            query="汇报按优先级排序",
            description="边界 — 主语是Agent产物\"汇报\"→rules",
            expected_dimensions=["agent_rules"],
            test_focus="pref vs rules: 主语是Agent产物\"汇报\"→rules",
        ),
        MemoryEvalCase(
            id="ext_boundary_15", layer=EvalLayer.EXTRACT, query_type=QueryType.EXTRACT_BOUNDARY,
            query="我习惯按优先级看事情",
            description="边界 — \"我习惯\"是个人习惯→pref",
            expected_dimensions=["preferences"],
            test_focus="pref vs rules: \"我习惯\"是个人习惯→pref",
        ),
        # G2. Profile vs Preferences 边界（#176 ~ #182）
        MemoryEvalCase(
            id="ext_boundary_16", layer=EvalLayer.EXTRACT, query_type=QueryType.EXTRACT_BOUNDARY,
            query="我们部门不加班",
            description="边界 — 组织文化→profile",
            expected_dimensions=["profile"],
            test_focus="profile vs pref: 组织文化→profile",
        ),
        MemoryEvalCase(
            id="ext_boundary_17", layer=EvalLayer.EXTRACT, query_type=QueryType.EXTRACT_BOUNDARY,
            query="我一般不加班",
            description="边界 — 个人习惯→pref",
            expected_dimensions=["preferences"],
            test_focus="profile vs pref: 个人习惯→pref",
        ),
        MemoryEvalCase(
            id="ext_boundary_18", layer=EvalLayer.EXTRACT, query_type=QueryType.EXTRACT_BOUNDARY,
            query="我们团队都用飞书",
            description="边界 — 团队工具是组织属性→profile",
            expected_dimensions=["profile"],
            test_focus="profile vs pref: 团队工具是组织属性→profile",
        ),
        MemoryEvalCase(
            id="ext_boundary_19", layer=EvalLayer.EXTRACT, query_type=QueryType.EXTRACT_BOUNDARY,
            query="我喜欢用飞书沟通",
            description="边界 — 个人偏好→pref",
            expected_dimensions=["preferences"],
            test_focus="profile vs pref: 个人偏好→pref",
        ),
        MemoryEvalCase(
            id="ext_boundary_20", layer=EvalLayer.EXTRACT, query_type=QueryType.EXTRACT_BOUNDARY,
            query="我们公司注重数据驱动",
            description="边界 — 组织文化→profile",
            expected_dimensions=["profile"],
            test_focus="profile vs pref: 组织文化→profile",
        ),
        MemoryEvalCase(
            id="ext_boundary_21", layer=EvalLayer.EXTRACT, query_type=QueryType.EXTRACT_BOUNDARY,
            query="我个人比较注重数据驱动",
            description="边界 — 个人风格→pref",
            expected_dimensions=["preferences"],
            test_focus="profile vs pref: 个人风格→pref",
        ),
        MemoryEvalCase(
            id="ext_boundary_22", layer=EvalLayer.EXTRACT, query_type=QueryType.EXTRACT_BOUNDARY,
            query="我们的工作节奏很快",
            description="边界 — 组织节奏→profile",
            expected_dimensions=["profile"],
            test_focus="profile vs pref: 组织节奏→profile",
        ),
        # G3. Entities vs Profile 边界（#183 ~ #190）
        MemoryEvalCase(
            id="ext_boundary_23", layer=EvalLayer.EXTRACT, query_type=QueryType.EXTRACT_BOUNDARY,
            query="我们公司的优势是响应速度快",
            description="边界 — 自述公司特征→profile",
            expected_dimensions=["profile"],
            test_focus="profile vs entities: 自述公司特征→profile",
        ),
        MemoryEvalCase(
            id="ext_boundary_24", layer=EvalLayer.EXTRACT, query_type=QueryType.EXTRACT_BOUNDARY,
            query="客户反馈我们响应速度比竞品快",
            description="边界 — 第三方反馈→entities",
            expected_dimensions=["entities"],
            test_focus="profile vs entities: 第三方反馈→entities",
        ),
        MemoryEvalCase(
            id="ext_boundary_25", layer=EvalLayer.EXTRACT, query_type=QueryType.EXTRACT_BOUNDARY,
            query="我们的竞争对手主要是Salesforce",
            description="边界 — 描述自己的竞争格局→profile",
            expected_dimensions=["profile"],
            test_focus="profile vs entities: 描述自己的竞争格局→profile",
        ),
        MemoryEvalCase(
            id="ext_boundary_26", layer=EvalLayer.EXTRACT, query_type=QueryType.EXTRACT_BOUNDARY,
            query="Salesforce最近在降价抢客户",
            description="边界 — 第三方行为事实→entities",
            expected_dimensions=["entities"],
            test_focus="profile vs entities: 第三方行为事实→entities",
        ),
        MemoryEvalCase(
            id="ext_boundary_27", layer=EvalLayer.EXTRACT, query_type=QueryType.EXTRACT_BOUNDARY,
            query="我们公司是做企业软件的",
            description="边界 — 自述公司业务→profile",
            expected_dimensions=["profile"],
            test_focus="profile vs entities: 自述公司业务→profile",
        ),
        MemoryEvalCase(
            id="ext_boundary_28", layer=EvalLayer.EXTRACT, query_type=QueryType.EXTRACT_BOUNDARY,
            query="这家公司是做企业软件的",
            description="边界 — 描述第三方→entities",
            expected_dimensions=["entities"],
            test_focus="profile vs entities: 描述第三方→entities",
        ),
        MemoryEvalCase(
            id="ext_boundary_29", layer=EvalLayer.EXTRACT, query_type=QueryType.EXTRACT_BOUNDARY,
            query="之前在阿里做过3年",
            description="边界 — 纯履历→profile",
            expected_dimensions=["profile"],
            test_focus="profile vs entities: 纯履历→profile",
        ),
        MemoryEvalCase(
            id="ext_boundary_30", layer=EvalLayer.EXTRACT, query_type=QueryType.EXTRACT_BOUNDARY,
            query="阿里最近在裁员，我们可以挖人",
            description="边界 — 第三方事实→entities",
            expected_dimensions=["entities"],
            test_focus="profile vs entities: 第三方事实→entities",
        ),
        # G4. Entities vs Agent Rules 边界（#191 ~ #196）
        MemoryEvalCase(
            id="ext_boundary_31", layer=EvalLayer.EXTRACT, query_type=QueryType.EXTRACT_BOUNDARY,
            query="华为那边要求用正式语气沟通",
            description="边界 — 陈述客户要求→entities",
            expected_dimensions=["entities"],
            test_focus="entities vs rules: 陈述客户要求→entities",
        ),
        MemoryEvalCase(
            id="ext_boundary_32", layer=EvalLayer.EXTRACT, query_type=QueryType.EXTRACT_BOUNDARY,
            query="跟华为沟通要用正式语气",
            description="边界 — 命令Agent行为→rules",
            expected_dimensions=["agent_rules"],
            test_focus="entities vs rules: 命令Agent行为→rules",
        ),
        MemoryEvalCase(
            id="ext_boundary_33", layer=EvalLayer.EXTRACT, query_type=QueryType.EXTRACT_BOUNDARY,
            query="招行的合规要求是必须有等保三级",
            description="边界 — 陈述客户事实→entities",
            expected_dimensions=["entities"],
            test_focus="entities vs rules: 陈述客户事实→entities",
        ),
        MemoryEvalCase(
            id="ext_boundary_34", layer=EvalLayer.EXTRACT, query_type=QueryType.EXTRACT_BOUNDARY,
            query="给招行的方案要突出安全合规",
            description="边界 — 命令Agent输出→rules",
            expected_dimensions=["agent_rules"],
            test_focus="entities vs rules: 命令Agent输出→rules",
        ),
        MemoryEvalCase(
            id="ext_boundary_35", layer=EvalLayer.EXTRACT, query_type=QueryType.EXTRACT_BOUNDARY,
            query="字节那边决策很快，拖了就没戏",
            description="边界 — 陈述客户特点→entities",
            expected_dimensions=["entities"],
            test_focus="entities vs rules: 陈述客户特点→entities",
        ),
        MemoryEvalCase(
            id="ext_boundary_36", layer=EvalLayer.EXTRACT, query_type=QueryType.EXTRACT_BOUNDARY,
            query="跟字节的项目要快速响应，不能拖",
            description="边界 — 命令Agent行为→rules",
            expected_dimensions=["agent_rules"],
            test_focus="entities vs rules: 命令Agent行为→rules",
        ),
        # G5. 持久 vs 单次 边界（#197 ~ #200）
        MemoryEvalCase(
            id="ext_boundary_37", layer=EvalLayer.EXTRACT, query_type=QueryType.EXTRACT_BOUNDARY,
            query="以后分析要深入一些",
            description="边界 — \"以后\"=持久→rules",
            expected_dimensions=["agent_rules"],
            test_focus="持久 vs 单次: \"以后\"=持久→rules",
        ),
        MemoryEvalCase(
            id="ext_boundary_38", layer=EvalLayer.EXTRACT, query_type=QueryType.EXTRACT_BOUNDARY,
            query="这次分析深入一些",
            description="边界 — \"这次\"=单次→不提取",
            expected_dimensions=[], negative=True,
            test_focus="持久 vs 单次: \"这次\"=单次→不提取",
        ),
        MemoryEvalCase(
            id="ext_boundary_39", layer=EvalLayer.EXTRACT, query_type=QueryType.EXTRACT_BOUNDARY,
            query="你就像我的私人助理一样",
            description="边界 — 角色定义（比喻式）→rules",
            expected_dimensions=["agent_rules"],
            test_focus="持久 vs 单次: 角色定义（比喻式）→rules",
        ),
        MemoryEvalCase(
            id="ext_boundary_40", layer=EvalLayer.EXTRACT, query_type=QueryType.EXTRACT_BOUNDARY,
            query="感觉你像私人助理",
            description="边界 — 感叹/评价（非指令）→不提取",
            expected_dimensions=[], negative=True,
            test_focus="持久 vs 单次: 感叹/评价（非指令）→不提取",
        ),
    ]


# ═══════════════════════════════════════════════════════════
# H. 反思验证场景（#201 ~ #250）
# ═══════════════════════════════════════════════════════════

def _reflect_cases() -> list[MemoryEvalCase]:
    """验证记忆反思修正机制"""
    cases = []
    cases.extend(_reflect_user_feedback())
    cases.extend(_reflect_conflict())
    cases.extend(_reflect_session_end())
    cases.extend(_reflect_failure())
    cases.extend(_reflect_global())
    return cases


def _reflect_user_feedback() -> list[MemoryEvalCase]:
    """H1. 用户反馈反思 — 用户纠正触发（#201 ~ #220）"""
    return [
        MemoryEvalCase(
            id="ext_reflect_fb_01", layer=EvalLayer.EXTRACT, query_type=QueryType.REFLECT_USER_FEEDBACK,
            query="不对，我已经调到华南区了",
            description="反思 — 显式纠正\"不对\"+信息更正",
            expected_dimensions=["profile"],
            existing_memory={"dimension": "profile", "content": "用户负责华东区"},
            expected_action="update_old",
            test_focus="显式纠正\"不对\"+信息更正",
        ),
        MemoryEvalCase(
            id="ext_reflect_fb_02", layer=EvalLayer.EXTRACT, query_type=QueryType.REFLECT_USER_FEEDBACK,
            query="我改主意了，以后还是用图表吧",
            description="反思 — \"我改主意了\"触发偏好更新",
            expected_dimensions=["preferences"],
            existing_memory={"dimension": "preferences", "content": "用户喜欢表格展示"},
            expected_action="update_old",
            test_focus="\"我改主意了\"触发偏好更新",
        ),
        MemoryEvalCase(
            id="ext_reflect_fb_03", layer=EvalLayer.EXTRACT, query_type=QueryType.REFLECT_USER_FEEDBACK,
            query="之前说的100字太短了，改成200字",
            description="反思 — 参数更新",
            expected_dimensions=["agent_rules"],
            existing_memory={"dimension": "agent_rules", "content": "回复不超过100字"},
            expected_action="update_old",
            test_focus="参数更新",
        ),
        MemoryEvalCase(
            id="ext_reflect_fb_04", layer=EvalLayer.EXTRACT, query_type=QueryType.REFLECT_USER_FEEDBACK,
            query="错了，张伟已经升VP了",
            description="反思 — \"错了\"+事实更正",
            expected_dimensions=["entities"],
            existing_memory={"dimension": "entities", "content": "华为张伟是技术总监"},
            expected_action="update_old",
            test_focus="\"错了\"+事实更正",
        ),
        MemoryEvalCase(
            id="ext_reflect_fb_05", layer=EvalLayer.EXTRACT, query_type=QueryType.REFLECT_USER_FEEDBACK,
            query="其实腾讯已经不考虑用友了，现在只看我们",
            description="反思 — \"其实\"暗示纠正",
            expected_dimensions=["entities"],
            existing_memory={"dimension": "entities", "content": "腾讯在评估用友"},
            expected_action="update_old",
            test_focus="\"其实\"暗示纠正",
        ),
        MemoryEvalCase(
            id="ext_reflect_fb_06", layer=EvalLayer.EXTRACT, query_type=QueryType.REFLECT_USER_FEEDBACK,
            query="更正一下，现在团队扩到20人了",
            description="反思 — \"更正一下\"显式纠正",
            expected_dimensions=["profile"],
            existing_memory={"dimension": "profile", "content": "团队15人"},
            expected_action="update_old",
            test_focus="\"更正一下\"显式纠正",
        ),
        MemoryEvalCase(
            id="ext_reflect_fb_07", layer=EvalLayer.EXTRACT, query_type=QueryType.REFLECT_USER_FEEDBACK,
            query="算了，你现在可以自动发了",
            description="反思 — 撤销旧规则",
            expected_dimensions=["agent_rules"],
            existing_memory={"dimension": "agent_rules", "content": "不要自动发邮件"},
            expected_action="archive_old",
            test_focus="撤销旧规则",
        ),
        MemoryEvalCase(
            id="ext_reflect_fb_08", layer=EvalLayer.EXTRACT, query_type=QueryType.REFLECT_USER_FEEDBACK,
            query="不是这样的，他们预算砍了，现在只有1200万",
            description="反思 — \"不是这样的\"+数值更正",
            expected_dimensions=["entities"],
            existing_memory={"dimension": "entities", "content": "比亚迪预算1500万"},
            expected_action="update_old",
            test_focus="\"不是这样的\"+数值更正",
        ),
        MemoryEvalCase(
            id="ext_reflect_fb_09", layer=EvalLayer.EXTRACT, query_type=QueryType.REFLECT_USER_FEEDBACK,
            query="最近改了，现在下午才有空看",
            description="反思 — 隐式纠正（\"改了\"）",
            expected_dimensions=["preferences"],
            existing_memory={"dimension": "preferences", "content": "用户习惯早上看数据"},
            expected_action="update_old",
            test_focus="隐式纠正（\"改了\"）",
        ),
        MemoryEvalCase(
            id="ext_reflect_fb_10", layer=EvalLayer.EXTRACT, query_type=QueryType.REFLECT_USER_FEEDBACK,
            query="陈刚已经离职了，现在是王磊接手",
            description="反思 — 人事变动更正",
            expected_dimensions=["entities"],
            existing_memory={"dimension": "entities", "content": "招行陈刚是关键决策人"},
            expected_action="update_old",
            test_focus="人事变动更正",
        ),
        MemoryEvalCase(
            id="ext_reflect_fb_11", layer=EvalLayer.EXTRACT, query_type=QueryType.REFLECT_USER_FEEDBACK,
            query="从今天起你的角色改成客户成功经理",
            description="反思 — 角色覆盖",
            expected_dimensions=["agent_rules"],
            existing_memory={"dimension": "agent_rules", "content": "你是我的销售助理"},
            expected_action="update_old",
            test_focus="角色覆盖",
        ),
        MemoryEvalCase(
            id="ext_reflect_fb_12", layer=EvalLayer.EXTRACT, query_type=QueryType.REFLECT_USER_FEEDBACK,
            query="今年目标调了，变成3500万",
            description="反思 — 数值更新",
            expected_dimensions=["profile"],
            existing_memory={"dimension": "profile", "content": "用户KPI是3000万"},
            expected_action="update_old",
            test_focus="数值更新",
        ),
        MemoryEvalCase(
            id="ext_reflect_fb_13", layer=EvalLayer.EXTRACT, query_type=QueryType.REFLECT_USER_FEEDBACK,
            query="他们后来说2周就够了",
            description="反思 — 第三方要求变更",
            expected_dimensions=["entities"],
            existing_memory={"dimension": "entities", "content": "字节要求1个月试用"},
            expected_action="update_old",
            test_focus="第三方要求变更",
        ),
        MemoryEvalCase(
            id="ext_reflect_fb_14", layer=EvalLayer.EXTRACT, query_type=QueryType.REFLECT_USER_FEEDBACK,
            query="现在我更喜欢用飞书了，邮件太慢",
            description="反思 — 偏好演进",
            expected_dimensions=["preferences"],
            existing_memory={"dimension": "preferences", "content": "用户偏好邮件沟通"},
            expected_action="update_old",
            test_focus="偏好演进",
        ),
        MemoryEvalCase(
            id="ext_reflect_fb_15", layer=EvalLayer.EXTRACT, query_type=QueryType.REFLECT_USER_FEEDBACK,
            query="不用每周一了，改成每天早上",
            description="反思 — 频率参数更新",
            expected_dimensions=["agent_rules"],
            existing_memory={"dimension": "agent_rules", "content": "每周一推送待办"},
            expected_action="update_old",
            test_focus="频率参数更新",
        ),
        MemoryEvalCase(
            id="ext_reflect_fb_16", layer=EvalLayer.EXTRACT, query_type=QueryType.REFLECT_USER_FEEDBACK,
            query="马总最近态度变了，不怎么压价了",
            description="反思 — 行为模式变化",
            expected_dimensions=["entities"],
            existing_memory={"dimension": "entities", "content": "阿里马总压价厉害"},
            expected_action="update_old",
            test_focus="行为模式变化",
        ),
        MemoryEvalCase(
            id="ext_reflect_fb_17", layer=EvalLayer.EXTRACT, query_type=QueryType.REFLECT_USER_FEEDBACK,
            query="我现在不只做新签了，续约也归我管",
            description="反思 — 职责扩展（非替代）",
            expected_dimensions=["profile"],
            existing_memory={"dimension": "profile", "content": "用户负责新签"},
            expected_action="update_old",
            test_focus="职责扩展（非替代）",
        ),
        MemoryEvalCase(
            id="ext_reflect_fb_18", layer=EvalLayer.EXTRACT, query_type=QueryType.REFLECT_USER_FEEDBACK,
            query="跟海外客户的报告改成英文",
            description="反思 — 条件分支新增",
            expected_dimensions=["agent_rules"],
            existing_memory={"dimension": "agent_rules", "content": "分析报告用中文"},
            expected_action="keep_both",
            test_focus="条件分支新增",
        ),
        MemoryEvalCase(
            id="ext_reflect_fb_19", layer=EvalLayer.EXTRACT, query_type=QueryType.REFLECT_USER_FEEDBACK,
            query="听说小米那边也开始控预算了",
            description="反思 — \"听说\"间接信息更正",
            expected_dimensions=["entities"],
            existing_memory={"dimension": "entities", "content": "小米预算充足"},
            expected_action="update_old",
            test_focus="\"听说\"间接信息更正",
        ),
        MemoryEvalCase(
            id="ext_reflect_fb_20", layer=EvalLayer.EXTRACT, query_type=QueryType.REFLECT_USER_FEEDBACK,
            query="其实详细一点也行，之前是因为太忙没时间看",
            description="反思 — 偏好撤销+原因说明",
            expected_dimensions=["preferences"],
            existing_memory={"dimension": "preferences", "content": "用户不喜欢长报告"},
            expected_action="archive_old",
            test_focus="偏好撤销+原因说明",
        ),
    ]


def _reflect_conflict() -> list[MemoryEvalCase]:
    """H2. 冲突检测反思 — 新记忆与已有记忆矛盾（#221 ~ #235）"""
    return [
        MemoryEvalCase(
            id="ext_reflect_cf_01", layer=EvalLayer.EXTRACT, query_type=QueryType.REFLECT_CONFLICT,
            query="我现在负责华南区",
            description="冲突 — 同维度直接矛盾（区域变更）",
            expected_dimensions=["profile"],
            existing_memory={"dimension": "profile", "content": "负责华东区"},
            expected_action="update_old", conflict_type="contradiction",
            test_focus="同维度直接矛盾",
        ),
        MemoryEvalCase(
            id="ext_reflect_cf_02", layer=EvalLayer.EXTRACT, query_type=QueryType.REFLECT_CONFLICT,
            query="我现在更喜欢图表了",
            description="冲突 — 偏好变更",
            expected_dimensions=["preferences"],
            existing_memory={"dimension": "preferences", "content": "喜欢表格"},
            expected_action="update_old", conflict_type="contradiction",
            test_focus="偏好变更",
        ),
        MemoryEvalCase(
            id="ext_reflect_cf_03", layer=EvalLayer.EXTRACT, query_type=QueryType.REFLECT_CONFLICT,
            query="华为今年预算收紧了不少",
            description="冲突 — 信息演进（预算状态变化）",
            expected_dimensions=["entities"],
            existing_memory={"dimension": "entities", "content": "华为预算充足"},
            expected_action="update_old", conflict_type="evolution",
            test_focus="时间演进",
        ),
        MemoryEvalCase(
            id="ext_reflect_cf_04", layer=EvalLayer.EXTRACT, query_type=QueryType.REFLECT_CONFLICT,
            query="回复200字以内就行",
            description="冲突 — 规则参数冲突",
            expected_dimensions=["agent_rules"],
            existing_memory={"dimension": "agent_rules", "content": "回复≤100字"},
            expected_action="update_old", conflict_type="contradiction",
            test_focus="规则参数冲突",
        ),
        MemoryEvalCase(
            id="ext_reflect_cf_05", layer=EvalLayer.EXTRACT, query_type=QueryType.REFLECT_CONFLICT,
            query="张伟已经升VP了",
            description="冲突 — 职位升迁（人事变动）",
            expected_dimensions=["entities"],
            existing_memory={"dimension": "entities", "content": "张伟是技术总监"},
            expected_action="update_old", conflict_type="evolution",
            test_focus="人事变动",
        ),
        MemoryEvalCase(
            id="ext_reflect_cf_06", layer=EvalLayer.EXTRACT, query_type=QueryType.REFLECT_CONFLICT,
            query="团队已经扩到20人了",
            description="冲突 — 规模变化",
            expected_dimensions=["profile"],
            existing_memory={"dimension": "profile", "content": "团队10人"},
            expected_action="update_old", conflict_type="evolution",
            test_focus="数值演进",
        ),
        MemoryEvalCase(
            id="ext_reflect_cf_07", layer=EvalLayer.EXTRACT, query_type=QueryType.REFLECT_CONFLICT,
            query="腾讯已经排除用友了",
            description="冲突 — 竞品状态变化",
            expected_dimensions=["entities"],
            existing_memory={"dimension": "entities", "content": "腾讯评估用友"},
            expected_action="update_old", conflict_type="evolution",
            test_focus="竞品状态变化",
        ),
        MemoryEvalCase(
            id="ext_reflect_cf_08", layer=EvalLayer.EXTRACT, query_type=QueryType.REFLECT_CONFLICT,
            query="我现在改下午看数据了",
            description="冲突 — 习惯变更",
            expected_dimensions=["preferences"],
            existing_memory={"dimension": "preferences", "content": "早上看数据"},
            expected_action="update_old", conflict_type="contradiction",
            test_focus="时间习惯冲突",
        ),
        MemoryEvalCase(
            id="ext_reflect_cf_09", layer=EvalLayer.EXTRACT, query_type=QueryType.REFLECT_CONFLICT,
            query="比亚迪选型推迟到Q4了",
            description="冲突 — 时间线变化",
            expected_dimensions=["entities"],
            existing_memory={"dimension": "entities", "content": "比亚迪Q3选型"},
            expected_action="update_old", conflict_type="evolution",
            test_focus="时间线变化",
        ),
        MemoryEvalCase(
            id="ext_reflect_cf_10", layer=EvalLayer.EXTRACT, query_type=QueryType.REFLECT_CONFLICT,
            query="你可以自动发邮件了",
            description="冲突 — 约束取消",
            expected_dimensions=["agent_rules"],
            existing_memory={"dimension": "agent_rules", "content": "不要自动发邮件"},
            expected_action="update_old", conflict_type="contradiction",
            test_focus="规则撤销",
        ),
        MemoryEvalCase(
            id="ext_reflect_cf_11", layer=EvalLayer.EXTRACT, query_type=QueryType.REFLECT_CONFLICT,
            query="招行项目延期了，至少还要一个月",
            description="冲突 — 进度变化",
            expected_dimensions=["entities"],
            existing_memory={"dimension": "entities", "content": "招行项目2周内签约"},
            expected_action="update_old", conflict_type="evolution",
            test_focus="项目进度冲突",
        ),
        MemoryEvalCase(
            id="ext_reflect_cf_12", layer=EvalLayer.EXTRACT, query_type=QueryType.REFLECT_CONFLICT,
            query="我们现在也做医疗行业了",
            description="冲突 — 业务扩展（非矛盾）",
            expected_dimensions=["profile"],
            existing_memory={"dimension": "profile", "content": "公司做金融客户"},
            expected_action="update_old", conflict_type="evolution",
            test_focus="信息扩展（非矛盾）",
        ),
        MemoryEvalCase(
            id="ext_reflect_cf_13", layer=EvalLayer.EXTRACT, query_type=QueryType.REFLECT_CONFLICT,
            query="张伟态度转变了，开始倾向竞品",
            description="冲突 — 关键人态度变化",
            expected_dimensions=["entities"],
            existing_memory={"dimension": "entities", "content": "华为张伟支持我们"},
            expected_action="update_old", conflict_type="contradiction",
            test_focus="关键人态度变化",
        ),
        MemoryEvalCase(
            id="ext_reflect_cf_14", layer=EvalLayer.EXTRACT, query_type=QueryType.REFLECT_CONFLICT,
            query="我现在改用微信沟通了",
            description="冲突 — 工具偏好变更",
            expected_dimensions=["preferences"],
            existing_memory={"dimension": "preferences", "content": "用飞书沟通"},
            expected_action="update_old", conflict_type="contradiction",
            test_focus="工具偏好冲突",
        ),
        MemoryEvalCase(
            id="ext_reflect_cf_15", layer=EvalLayer.EXTRACT, query_type=QueryType.REFLECT_CONFLICT,
            query="你现在也要关注医疗行业",
            description="冲突 — 规则扩展",
            expected_dimensions=["agent_rules"],
            existing_memory={"dimension": "agent_rules", "content": "专注金融行业"},
            expected_action="update_old", conflict_type="evolution",
            test_focus="领域扩展",
        ),
    ]


def _reflect_session_end() -> list[MemoryEvalCase]:
    """H3. 会话结束反思 — 会话 commit 后一致性检查（#236 ~ #242）"""
    return [
        MemoryEvalCase(
            id="ext_reflect_se_01", layer=EvalLayer.EXTRACT, query_type=QueryType.REFLECT_SESSION_END,
            query="我调到华南区了",
            description="会话反思 — 区域变更影响关联实体",
            expected_dimensions=["profile"],
            existing_memory={"dimension": "profile", "content": "华东区销售总监",
                           "related": [{"dimension": "entities", "content": "华为是重点客户"}]},
            expected_action="update_old",
            test_focus="跨维度一致性：区域变更影响实体",
        ),
        MemoryEvalCase(
            id="ext_reflect_se_02", layer=EvalLayer.EXTRACT, query_type=QueryType.REFLECT_SESSION_END,
            query="你现在专注制造业",
            description="会话反思 — 领域变更影响实体优先级",
            expected_dimensions=["agent_rules"],
            existing_memory={"dimension": "agent_rules", "content": "专注金融行业",
                           "related": [{"dimension": "entities", "content": "招行/华为金融项目"}]},
            expected_action="update_old",
            test_focus="规则变更影响实体优先级",
        ),
        MemoryEvalCase(
            id="ext_reflect_se_03", layer=EvalLayer.EXTRACT, query_type=QueryType.REFLECT_SESSION_END,
            query="我现在需要详细分析",
            description="会话反思 — 偏好与规则矛盾检测",
            expected_dimensions=["preferences"],
            existing_memory={"dimension": "preferences", "content": "喜欢简洁",
                           "related": [{"dimension": "agent_rules", "content": "回复≤100字"}]},
            expected_action="update_old",
            test_focus="偏好与规则一致性",
        ),
        MemoryEvalCase(
            id="ext_reflect_se_04", layer=EvalLayer.EXTRACT, query_type=QueryType.REFLECT_SESSION_END,
            query="我现在也负责续约了",
            description="会话反思 — 职责扩展建议补充规则",
            expected_dimensions=["profile"],
            existing_memory={"dimension": "profile", "content": "负责新签",
                           "related": [{"dimension": "agent_rules", "content": "跟进节奏3/7/14天"}]},
            expected_action="update_old",
            test_focus="职责扩展触发规则补充建议",
        ),
        MemoryEvalCase(
            id="ext_reflect_se_05", layer=EvalLayer.EXTRACT, query_type=QueryType.REFLECT_SESSION_END,
            query="张伟离职了",
            description="会话反思 — 关键人变更影响项目记忆",
            expected_dimensions=["entities"],
            existing_memory={"dimension": "entities", "content": "张伟是决策人",
                           "related": [{"dimension": "entities", "content": "华为ERP项目进行中"}]},
            expected_action="update_old",
            test_focus="人事变动影响项目",
        ),
        MemoryEvalCase(
            id="ext_reflect_se_06", layer=EvalLayer.EXTRACT, query_type=QueryType.REFLECT_SESSION_END,
            query="华为新对接人李娜风格谨慎",
            description="会话反思 — 无矛盾的一致性确认",
            expected_dimensions=["entities"],
            existing_memory={"dimension": "agent_rules", "content": "给华为用正式语气",
                           "related": [{"dimension": "entities", "content": "华为张伟说话直接"}]},
            expected_action="",
            test_focus="无需修正的一致性确认",
        ),
        MemoryEvalCase(
            id="ext_reflect_se_07", layer=EvalLayer.EXTRACT, query_type=QueryType.REFLECT_SESSION_END,
            query="公司刚完成C轮",
            description="会话反思 — 同维度信息演进",
            expected_dimensions=["profile"],
            existing_memory={"dimension": "profile", "content": "公司200人,B轮融资"},
            expected_action="update_old",
            test_focus="同维度信息演进",
        ),
    ]


def _reflect_failure() -> list[MemoryEvalCase]:
    """H4. 失败驱动反思 — 任务失败后记忆审查（#243 ~ #248）"""
    return [
        MemoryEvalCase(
            id="ext_reflect_fail_01", layer=EvalLayer.EXTRACT, query_type=QueryType.REFLECT_FAILURE,
            query="张伟现在要看ROI数据不看PPT了",
            description="失败反思 — 过时记忆导致失败",
            expected_dimensions=["entities"],
            existing_memory={"dimension": "entities", "content": "张伟是技术总监，喜欢看PPT",
                           "task": "给华为张伟准备PPT汇报", "failure": "张伟已升VP，现在要看ROI数据"},
            expected_action="update_old",
            test_focus="过时记忆导致失败",
        ),
        MemoryEvalCase(
            id="ext_reflect_fail_02", layer=EvalLayer.EXTRACT, query_type=QueryType.REFLECT_FAILURE,
            query="腾讯对价格很敏感，应该直接给优惠价",
            description="失败反思 — 策略记忆不适用特定客户",
            expected_dimensions=["entities"],
            existing_memory={"dimension": "agent_rules", "content": "报价先报标准价",
                           "task": "给腾讯报价", "failure": "VP直接拒绝，说价格太高没诚意"},
            expected_action="update_old",
            test_focus="策略记忆不适用特定客户",
        ),
        MemoryEvalCase(
            id="ext_reflect_fail_03", layer=EvalLayer.EXTRACT, query_type=QueryType.REFLECT_FAILURE,
            query="招行审批实际花了6周，以后要预留buffer",
            description="失败反思 — 时效性记忆过时",
            expected_dimensions=["entities"],
            existing_memory={"dimension": "entities", "content": "招行审批2周",
                           "task": "安排招行签约时间", "failure": "实际6周，错过客户预期"},
            expected_action="update_old",
            test_focus="时效性记忆过时",
        ),
        MemoryEvalCase(
            id="ext_reflect_fail_04", layer=EvalLayer.EXTRACT, query_type=QueryType.REFLECT_FAILURE,
            query="赵敏已经调岗了，新负责人是王磊",
            description="失败反思 — 人事变动未及时更新",
            expected_dimensions=["entities"],
            existing_memory={"dimension": "entities", "content": "比亚迪赵敏是关键决策人",
                           "task": "联系赵敏推进项目", "failure": "赵敏已调岗"},
            expected_action="update_old",
            test_focus="人事变动未及时更新",
        ),
        MemoryEvalCase(
            id="ext_reflect_fail_05", layer=EvalLayer.EXTRACT, query_type=QueryType.REFLECT_FAILURE,
            query="海外客户要用英文",
            description="失败反思 — 规则缺少条件分支",
            expected_dimensions=["agent_rules"],
            existing_memory={"dimension": "agent_rules", "content": "用中文回复",
                           "task": "给海外客户写邮件", "failure": "客户看不懂中文"},
            expected_action="keep_both",
            test_focus="规则缺少条件分支",
        ),
        MemoryEvalCase(
            id="ext_reflect_fail_06", layer=EvalLayer.EXTRACT, query_type=QueryType.REFLECT_FAILURE,
            query="竞品分析要详细，简洁偏好不适用于分析类任务",
            description="失败反思 — 偏好不适用于所有场景",
            expected_dimensions=["preferences"],
            existing_memory={"dimension": "preferences", "content": "用户喜欢简洁回复",
                           "task": "给用户做深度竞品分析", "failure": "用户说太简单没参考价值"},
            expected_action="keep_both",
            test_focus="偏好不适用于所有场景",
        ),
    ]


def _reflect_global() -> list[MemoryEvalCase]:
    """H5. 定期全局反思 — 碎片合并与一致性审计（#249 ~ #250）"""
    return [
        MemoryEvalCase(
            id="ext_reflect_gl_01", layer=EvalLayer.EXTRACT, query_type=QueryType.REFLECT_GLOBAL,
            query="",  # 全局反思无特定查询
            description="全局反思 — 碎片化检测与合并",
            expected_dimensions=["entities"],
            existing_memory={"dimension": "entities", "fragments": [
                "张伟说话直接", "张伟喜欢PPT", "张伟是技术总监"
            ], "expected_merge": "合并为完整的张伟画像记忆"},
            expected_action="update_old",
            test_focus="碎片化检测与合并",
        ),
        MemoryEvalCase(
            id="ext_reflect_gl_02", layer=EvalLayer.EXTRACT, query_type=QueryType.REFLECT_GLOBAL,
            query="",  # 全局反思无特定查询
            description="全局反思 — 过时记忆淘汰",
            expected_dimensions=["profile"],
            existing_memory={"dimension": "profile", "fragments": [
                {"content": "负责华东区", "created_days_ago": 90, "access_count": 0},
                {"content": "负责华南区", "created_days_ago": 7, "access_count": 5},
            ], "expected_action": "归档旧的华东区记忆，保留华南区"},
            expected_action="archive_old",
            test_focus="过时记忆淘汰",
        ),
    ]
