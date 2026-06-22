"""生成 knowledge_search 召回率评测用例 — 完整版

覆盖维度：
- Level 1: 产品型号精确召回 (32条)
- Level 2: 意图×主题域交叉 (36条)
- Level 3: 同一文档多种问法 (60条)
- Level 4: 对比/跨域/负例/模糊 (22条)
- Level 5: 元数据过滤精准召回 (10条)

共 160 条新增（加上已有 50 条 = 总 210 条召回用例）
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.chdir(os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv
load_dotenv()

from src.eval.tool_eval_runner import ToolEvalCase, Assertion, AssertionType
from src.store.eval_dao import EvalCaseDAO, EvalToolCase, EvalSuiteDAO

suite_id = EvalSuiteDAO.get_default_suite_id()
print(f"Suite ID: {suite_id}")

cases = []

# ═══════════════════════════════════════════════════════════════════
# Level 1: 产品型号精确召回 — 补齐未覆盖高频产品 (20条)
# ═══════════════════════════════════════════════════════════════════

level1 = [
    ("ks_r51", "2088压力变送器", "罗斯蒙特2088压力变送器安装指南", "doc_0f1bd7607dee44158948"),
    ("ks_r52", "2051压力变送器", "罗斯蒙特2051压力变送器产品资料", "doc_7c05c9e4705d429bb55a"),
    ("ks_r53", "3051CF流量计", "罗斯蒙特3051CF差压流量计", "doc_61bb2b38953f47fd86a2"),
    ("ks_r54", "3051SFA阿牛巴一体化", "3051SFA一体化阿牛巴流量计", "doc_e1d22995350c4f98b06d"),
    ("ks_r55", "644温度变送器", "罗斯蒙特644温度变送器产品规格", "doc_fd44f91e496d4de58cb4"),
    ("ks_r56", "148温度变送器", "罗斯蒙特148温度变送器安装", "doc_26a7842b9767411a80da"),
    ("ks_r57", "3144P温度变送器", "罗斯蒙特3144P温度变送器", "doc_75ac174ed2bd4f5993e4"),
    ("ks_r58", "1208C雷达液位计", "Rosemount 1208C雷达液位计", "doc_febb4e17972b4ad7b8cb"),
    ("ks_r59", "3308无线导波雷达", "罗斯蒙特3308无线导波雷达液位计", "doc_05612ecef7e14ff2bed7"),
    ("ks_r60", "2140液位检测器", "罗斯蒙特2140振动音叉液位检测器", "doc_2b9e12993de34712adc9"),
    ("ks_r61", "1199密封系统", "罗斯蒙特1199远传差压液位变送器", "doc_6379208ec0c442ba8458"),
    ("ks_r62", "1595调节孔板", "罗斯蒙特1595 Conditioning Orifice Plate", "doc_37f386e9c86f4d9ba976"),
    ("ks_r63", "2051CF流量计", "罗斯蒙特2051CF系列流量计变送器", "doc_0b4443dbd38845c7b4de"),
    ("ks_r64", "无线压力表产品", "罗斯蒙特无线压力表 WirelessHART", "doc_5b8d110649f74533ab54"),
    ("ks_r65", "Incus超声波探测器", "Incus超声波气体泄漏探测器", "doc_1522da7d92da4507a2d4"),
    ("ks_r66", "3051DG压力变送器", "罗斯蒙特3051DG压力变送器选型", "doc_80733b3ca5cc4d4bb946"),
    ("ks_r67", "5900C雷达液位计", "罗斯蒙特5900C雷达液位计", "doc_9c66a6843d6e4d42ba01"),
    ("ks_r68", "2120认证文档", "罗斯蒙特2120液位开关产品认证", "doc_c14e6ea3471f435d98c0"),
    ("ks_r69", "3051S系列全线", "罗斯蒙特3051S系列仪表产品线", "doc_bcdca202fb5b4091ad19"),
    ("ks_r70", "2240S多点温度", "罗斯蒙特2240S多点温度变送器", "doc_568ad120da0743d69cb0"),
]

for case_id, desc, query, expected_doc_id in level1:
    cases.append(ToolEvalCase(
        id=case_id,
        tool_name="knowledge_search",
        description=f"召回L1-型号 | {desc} → {expected_doc_id[:12]}",
        category="recall",
        input_data={"query": query, "top_k": 5},
        assertions=[
            Assertion(type=AssertionType.NOT_ERROR, description="不应报错"),
            Assertion(type=AssertionType.CONTAINS, expected=expected_doc_id, description=f"必须命中 {expected_doc_id[:16]}"),
        ],
    ))

# ═══════════════════════════════════════════════════════════════════
# Level 2: 意图×主题域交叉 (36条) — 每域6种意图
# ═══════════════════════════════════════════════════════════════════

level2 = [
    # ── 压力测量域 ──
    ("ks_r71", "压力-选型", "腐蚀性介质用什么压力变送器比较好", "doc_9dc2672c58da4cf89c7d"),
    ("ks_r72", "压力-安装", "3051压力变送器现场怎么接线通电", "doc_09488ff565004906a9b0"),
    ("ks_r73", "压力-参数", "罗斯蒙特3051量程范围和参考精度是多少", "doc_9dc2672c58da4cf89c7d"),
    ("ks_r74", "压力-故障", "压力变送器零点漂移偏差大怎么处理", "doc_9dc2672c58da4cf89c7d"),
    ("ks_r75", "压力-对比", "2088和3051压力变送器有什么区别该选哪个", "doc_9dc2672c58da4cf89c7d"),
    ("ks_r76", "压力-原理", "差压式压力变送器的测量原理是什么", "doc_9dc2672c58da4cf89c7d"),
    # ── 物位测量域 ──
    ("ks_r77", "物位-选型", "强腐蚀性液体储罐用哪种液位计", "doc_c1733cd7ab0148cb95b6"),
    ("ks_r78", "物位-安装", "5300导波雷达液位计的导波杆怎么安装", "doc_cfea79c827754f3c9229"),
    ("ks_r79", "物位-参数", "5408雷达液位变送器最大测量距离是多少", "doc_c1733cd7ab0148cb95b6"),
    ("ks_r80", "物位-故障", "雷达液位计出现虚假液位回波怎么解决", "doc_c1733cd7ab0148cb95b6"),
    ("ks_r81", "物位-对比", "导波雷达5300和非接触雷达5408有什么区别", "doc_49ef5ef96e3f41c18c56"),
    ("ks_r82", "物位-原理", "FMCW调频连续波雷达液位测量工作原理", "doc_c0b6142c389f4eff8ec0"),
    # ── 温度测量域 ──
    ("ks_r83", "温度-选型", "300度以上高温环境用什么温度传感器合适", "doc_fd44f91e496d4de58cb4"),
    ("ks_r84", "温度-安装", "温度变送器热套管安装深度和方向要求", "doc_26a7842b9767411a80da"),
    ("ks_r85", "温度-参数", "644温度变送器的测量精度和响应时间", "doc_fd44f91e496d4de58cb4"),
    ("ks_r86", "温度-故障", "温度变送器显示值和实际温度偏差大怎么办", "doc_fd44f91e496d4de58cb4"),
    ("ks_r87", "温度-对比", "铂电阻和热电偶温度测量哪个精度更高", "doc_fd44f91e496d4de58cb4"),
    ("ks_r88", "温度-原理", "非侵入式X-well温度测量的工作原理", "doc_655ff1952dbd446db6d5"),
    # ── 差压流量域 ──
    ("ks_r89", "流量-选型", "工厂蒸汽管道流量测量用什么流量计", "doc_ffe39f882fd24237"),
    ("ks_r90", "流量-安装", "阿牛巴流量计的安装方向和直管段要求", "doc_e1d22995350c4f98b06d"),
    ("ks_r91", "流量-参数", "3051SMV多参量流量变送器可以测多大管径", "doc_e9c1a046512349ef9019"),
    ("ks_r92", "流量-故障", "差压流量计读数波动大不稳定的原因", "doc_ffe39f882fd24237"),
    ("ks_r93", "流量-对比", "阿牛巴和孔板流量计哪个压损更小", "doc_e1d22995350c4f98b06d"),
    ("ks_r94", "流量-原理", "差压式流量测量伯努利方程基本原理", "doc_ffe39f882fd24237"),
    # ── 分析域 ──
    ("ks_r95", "分析-选型", "锅炉烟气含氧量分析用什么仪表", "doc_6b56e8dd891f4bd5afba"),
    ("ks_r96", "分析-安装", "CX2100直插式氧量分析仪安装位置要求", "doc_6b56e8dd891f4bd5afba"),
    ("ks_r97", "分析-参数", "在线pH分析仪量程和精度指标", "doc_39164863277a4cd5"),
    ("ks_r98", "分析-故障", "氧量分析仪标定失败探头响应慢", "doc_6b56e8dd891f4bd5afba"),
    ("ks_r99", "分析-对比", "直插式和抽取式烟气分析仪的区别", "doc_6b56e8dd891f4bd5afba"),
    ("ks_r100", "分析-原理", "电化学氧量分析和氧化锆的测量原理", "doc_6b56e8dd891f4bd5afba"),
    # ── 无线域 ──
    ("ks_r101", "无线-选型", "工厂无线监测需要哪些设备组网", "doc_5ab387282fab4fdbbf84"),
    ("ks_r102", "无线-安装", "1420无线网关天线安装高度和朝向", "doc_5ab387282fab4fdbbf84"),
    ("ks_r103", "无线-参数", "WirelessHART无线变送器电池续航寿命", "doc_5b8d110649f74533ab54"),
    ("ks_r104", "无线-故障", "无线仪表信号丢包通讯不稳定排查", "doc_5ab387282fab4fdbbf84"),
    ("ks_r105", "无线-对比", "WirelessHART和工业WiFi有什么区别", "doc_5ab387282fab4fdbbf84"),
    ("ks_r106", "无线-原理", "WirelessHART自组网mesh网络原理", "doc_5ab387282fab4fdbbf84"),
]

for case_id, desc, query, expected_doc_id in level2:
    cases.append(ToolEvalCase(
        id=case_id,
        tool_name="knowledge_search",
        description=f"召回L2-意图 | {desc} → {expected_doc_id[:12]}",
        category="recall",
        input_data={"query": query, "top_k": 5},
        assertions=[
            Assertion(type=AssertionType.NOT_ERROR, description="不应报错"),
            Assertion(type=AssertionType.CONTAINS, expected=expected_doc_id, description=f"必须命中 {expected_doc_id[:16]}"),
        ],
    ))

# ═══════════════════════════════════════════════════════════════════
# Level 3: 同一文档多种自然语言问法 (60条) — 15文档×4问法
# ═══════════════════════════════════════════════════════════════════

level3_docs = [
    # (base_id, doc_id, 问法1-型号, 问法2-场景, 问法3-口语, 问法4-英文/术语)
    ("ks_r107", "doc_9dc2672c58da4cf89c7d",  # 3051压力
     "Rosemount 3051 pressure transmitter datasheet",
     "石油化工高压管道压力测量推荐什么变送器",
     "最常用的那款压力表叫什么型号",
     "支持HART协议的4-20mA压力变送器"),
    ("ks_r111", "doc_49ef5ef96e3f41c18c56",  # 5300导波
     "Rosemount 5300 guided wave radar level transmitter",
     "有搅拌器的反应釜里面测液位用什么",
     "那种有根杆子伸到罐里测高度的仪器",
     "TDR时域反射导波雷达液位计选型"),
    ("ks_r115", "doc_ffe39f882fd24237",  # 双碳蒸汽
     "差压流量计蒸汽能源计量方案",
     "工厂蒸汽费用太高想精准计量该怎么办",
     "国家要求碳排放管控蒸汽流量怎么准确测",
     "steam flow metering for carbon emission"),
    ("ks_r119", "doc_c0b6142c389f4eff8ec0",  # 1408H
     "Rosemount 1408H 80GHz FMCW radar level",
     "制药车间卫生级液位测量用什么传感器",
     "有没有不接触介质就能测液位的小巧仪器",
     "3-A认证食品级非接触雷达液位计"),
    ("ks_r123", "doc_655ff1952dbd446db6d5",  # X-well非侵入温度
     "Rosemount X-well非侵入式温度测量技术",
     "管道不能停车开孔但需要加测温点怎么办",
     "有没有不用在管子上打洞就能测温度的方法",
     "clamp-on non-intrusive temperature measurement"),
    ("ks_r127", "doc_e9c1a046512349ef9019",  # 3051SMV
     "Rosemount 3051SMV multivariable transmitter",
     "同时测蒸汽的压力温度流量用一台仪表行吗",
     "那种一台表能测好几个参数的流量计",
     "多参量变送器质量流量补偿计算"),
    ("ks_r131", "doc_c1733cd7ab0148cb95b6",  # 5408
     "Rosemount 5408 non-contacting radar level",
     "化工罐区需要SIL2认证的液位仪表",
     "不接触液体表面就能测液位高度的那种雷达",
     "IEC 61508 SIL2 certified level transmitter"),
    ("ks_r135", "doc_6b56e8dd891f4bd5afba",  # CX2100
     "Rosemount CX2100 in-situ oxygen analyzer",
     "燃煤锅炉出口烟道氧含量怎么测比较准",
     "那个插在烟囱里面直接测氧气的分析仪",
     "zirconia O2 analyzer for combustion optimization"),
    ("ks_r139", "doc_5ab387282fab4fdbbf84",  # 1420网关
     "Rosemount 1420 wireless gateway configuration",
     "工厂要建无线仪表监测网络的核心设备是什么",
     "那个连接所有无线仪表汇总数据的盒子",
     "WirelessHART gateway DCS integration setup"),
    ("ks_r143", "doc_cf7a0fceab8642149a83",  # ET210腐蚀
     "Rosemount Permasense ET210 corrosion monitoring",
     "关键管道壁厚减薄腐蚀在线实时监测方案",
     "管子被腐蚀薄了怎么提前知道会不会漏",
     "non-intrusive pipe wall thickness monitoring"),
    ("ks_r147", "doc_ab8d88c50f98491c9b82",  # TankMaster罐区
     "TankMaster罐区管理软件系统",
     "储罐区几十个罐的库存和安全怎么统一管理",
     "有没有软件能一个屏幕看到所有罐的液位",
     "tank farm inventory management SCADA software"),
    ("ks_r151", "doc_fd44f91e496d4de58cb4",  # 644温度
     "Rosemount 644 temperature transmitter specifications",
     "高精度工业温度测量4-20mA输出用什么变送器",
     "测温度的那个小方块变送器选哪款",
     "HART temperature transmitter Pt100 RTD input"),
    ("ks_r155", "doc_05612ecef7e14ff2bed7",  # 3308无线导波
     "Rosemount 3308 wireless guided wave radar",
     "偏远位置储罐不方便布线用什么测液位",
     "不拉电缆线就能无线传液位数据的仪器",
     "battery powered wireless level measurement"),
    ("ks_r159", "doc_0d8f78fa04a64cf28c7d",  # 销售易
     "Neocrm销售易CRM产品介绍",
     "国产CRM系统有什么推荐的品牌",
     "那家腾讯投资的做客户管理软件的公司叫什么",
     "China CRM SaaS vendor Gartner Magic Quadrant"),
    ("ks_r163", "doc_944a31b8caa04aff",  # 光伏玻璃
     "差压流量计光伏玻璃熔窑天然气测量",
     "光伏玻璃生产线窑炉燃气流量怎么精确控制",
     "玻璃厂烧天然气的那个炉子气体流量不好测",
     "float glass furnace natural gas flow measurement"),
]

idx = 0
for base_id, doc_id, q1, q2, q3, q4 in level3_docs:
    queries = [q1, q2, q3, q4]
    labels = ["英文/术语", "场景描述", "口语/模糊", "专业术语"]
    for i, (q, label) in enumerate(zip(queries, labels)):
        cid = f"ks_r{107 + idx}"
        idx += 1
        cases.append(ToolEvalCase(
            id=cid,
            tool_name="knowledge_search",
            description=f"召回L3-{label} | {doc_id[:12]} 问法{i+1}",
            category="recall",
            input_data={"query": q, "top_k": 5},
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="不应报错"),
                Assertion(type=AssertionType.CONTAINS, expected=doc_id, description=f"必须命中 {doc_id[:16]}"),
            ],
        ))

# ═══════════════════════════════════════════════════════════════════
# Level 4: 对比/跨域/负例/模糊 (22条)
# ═══════════════════════════════════════════════════════════════════

# 对比类 — 验证同时命中两篇文档
compare_cases = [
    ("ks_r167", "5300和5408液位计有什么区别怎么选", "doc_49ef5ef96e3f41c18c56", "doc_c1733cd7ab0148cb95b6"),
    ("ks_r168", "2088和3051压力变送器性能对比", "doc_0f1bd7607dee44158948", "doc_9dc2672c58da4cf89c7d"),
    ("ks_r169", "雷达液位计和导波雷达各自适用什么场景", "doc_49ef5ef96e3f41c18c56", "doc_c1733cd7ab0148cb95b6"),
    ("ks_r170", "有线仪表和无线仪表维护成本哪个低", "doc_5ab387282fab4fdbbf84", None),
    ("ks_r171", "差压式液位和雷达液位测量哪个更准确", "doc_49ef5ef96e3f41c18c56", None),
]

for case_id, query, doc_id1, doc_id2 in compare_cases:
    asserts = [
        Assertion(type=AssertionType.NOT_ERROR, description="不应报错"),
        Assertion(type=AssertionType.CONTAINS, expected=doc_id1, description=f"必须命中 {doc_id1[:16]}"),
    ]
    if doc_id2:
        asserts.append(Assertion(type=AssertionType.CONTAINS, expected=doc_id2, description=f"必须同时命中 {doc_id2[:16]}"))
    cases.append(ToolEvalCase(
        id=case_id,
        tool_name="knowledge_search",
        description=f"召回L4-对比 | {query[:30]}",
        category="recall",
        input_data={"query": query, "top_k": 10},
        assertions=asserts,
    ))

# 负例类 — 验证不应命中仪表文档
negative_cases = [
    ("ks_r172", "Python Django Web开发入门教程", True),
    ("ks_r173", "上海浦东新区明天天气预报", True),
    ("ks_r174", "如何申请ISO9001质量管理体系认证流程", True),
    ("ks_r175", "年终总结PPT模板下载", True),
    ("ks_r176", "员工食堂本周菜单", True),
    ("ks_r177", "如何写好一份商业计划书", True),
    ("ks_r178", "公司团建活动方案推荐", True),
]

for case_id, query, expect_empty in negative_cases:
    cases.append(ToolEvalCase(
        id=case_id,
        tool_name="knowledge_search",
        description=f"召回L4-负例 | {query[:25]}不应命中",
        category="recall",
        input_data={"query": query, "top_k": 5},
        assertions=[
            Assertion(type=AssertionType.NOT_ERROR, description="不应报错"),
            Assertion(type=AssertionType.CONTAINS, expected="未找到", description="无关查询应返回未找到"),
        ],
    ))

# 模糊/噪声类 — 验证不崩溃且合理响应
fuzzy_cases = [
    ("ks_r179", "测东西不准了帮我查查", False, "测量"),
    ("ks_r180", "那个仪器坏了", False, None),
    ("ks_r181", "罗斯蒙特", False, "罗斯蒙特"),
    ("ks_r182", "帮我查一下之前看过的那个文档", True, None),
    ("ks_r183", "对", True, None),
    ("ks_r184", "液位", False, "液位"),
    ("ks_r185", "怎么测", False, None),
    ("ks_r186", "3051", False, "3051"),
    ("ks_r187", "变送器", False, "变送器"),
    ("ks_r188", "安装手册", False, "安装"),
]

for case_id, query, expect_empty, expect_keyword in fuzzy_cases:
    asserts = [Assertion(type=AssertionType.NOT_ERROR, description="不应报错")]
    if expect_empty:
        asserts.append(Assertion(type=AssertionType.CONTAINS, expected="未找到", description="过于模糊应返回未找到"))
    elif expect_keyword:
        asserts.append(Assertion(type=AssertionType.CONTAINS, expected=expect_keyword, description=f"模糊查询结果应包含'{expect_keyword}'"))
    cases.append(ToolEvalCase(
        id=case_id,
        tool_name="knowledge_search",
        description=f"召回L4-模糊 | '{query}'",
        category="recall",
        input_data={"query": query, "top_k": 5},
        assertions=asserts,
    ))

# ═══════════════════════════════════════════════════════════════════
# Level 5: 元数据过滤精准召回 (10条)
# ═══════════════════════════════════════════════════════════════════

level5 = [
    ("ks_r189", "过滤-操作指南+3051", {"query": "3051压力变送器安装步骤", "doc_category": "操作指南", "top_k": 5},
     "doc_09488ff565004906a9b0", "过滤操作指南应命中3051安装手册"),
    ("ks_r190", "过滤-产品手册+644", {"query": "644温度变送器产品规格", "doc_category": "产品手册", "top_k": 5},
     "doc_fd44f91e496d4de58cb4", "过滤产品手册应命中644产品样本"),
    ("ks_r191", "过滤-制造业+流量", {"query": "制造业蒸汽流量计量方案", "industry": "制造业", "top_k": 5},
     "doc_ffe39f882fd24237", "制造业过滤应命中蒸汽计量文档"),
    ("ks_r192", "过滤-能源化工+压力", {"query": "化工管道压力测量", "industry": "能源化工", "top_k": 5},
     "doc_9dc2672c58da4cf89c7d", "能源化工应命中3051"),
    ("ks_r193", "过滤-技术人员+安装", {"query": "雷达液位计现场安装调试", "target_audience": "技术人员", "top_k": 5},
     "doc_cfea79c827754f3c9229", "技术人员应命中安装类文档"),
    ("ks_r194", "过滤-售前+产品手册", {"query": "压力变送器选型推荐", "business_stage": "售前咨询", "doc_category": "产品手册", "top_k": 5},
     "doc_9dc2672c58da4cf89c7d", "售前+产品手册应命中3051产品样本"),
    ("ks_r195", "过滤-解决方案+无线", {"query": "无线仪表方案", "doc_category": "解决方案", "top_k": 5},
     None, "解决方案+无线 应有结果"),
    ("ks_r196", "过滤-实施交付+温度", {"query": "温度变送器安装接线", "business_stage": "实施交付", "top_k": 5},
     "doc_26a7842b9767411a80da", "实施交付应命中148安装手册"),
    ("ks_r197", "过滤-成功案例", {"query": "差压流量计行业应用案例", "doc_category": "成功案例", "top_k": 5},
     None, "成功案例过滤应有结果"),
    ("ks_r198", "过滤-产品手册+液位", {"query": "液位计产品选型手册", "doc_category": "产品手册", "top_k": 5},
     "doc_49ef5ef96e3f41c18c56", "产品手册应命中5300产品样本"),
]

for case_id, desc, input_data, expected_doc_id, assert_desc in level5:
    asserts = [Assertion(type=AssertionType.NOT_ERROR, description="不应报错")]
    if expected_doc_id:
        asserts.append(Assertion(type=AssertionType.CONTAINS, expected=expected_doc_id, description=assert_desc))
    else:
        asserts.append(Assertion(type=AssertionType.NOT_CONTAINS, expected="未找到", description=assert_desc))
    cases.append(ToolEvalCase(
        id=case_id,
        tool_name="knowledge_search",
        description=f"召回L5-过滤 | {desc}",
        category="recall",
        input_data=input_data,
        assertions=asserts,
    ))

# ═══════════════════════════════════════════════════════════════════
# 写入 DB
# ═══════════════════════════════════════════════════════════════════

print(f"\n生成用例总数: {len(cases)}")
print(f"  Level 1 (型号精确): {len(level1)}")
print(f"  Level 2 (意图交叉): {len(level2)}")
print(f"  Level 3 (多种问法): {idx}")
print(f"  Level 4 (对比/负例/模糊): {len(compare_cases) + len(negative_cases) + len(fuzzy_cases)}")
print(f"  Level 5 (过滤召回): {len(level5)}")

count = 0
for c in cases:
    db_case = EvalToolCase(
        suite_id=suite_id,
        case_key=c.id,
        tool_name=c.tool_name,
        method_name="",
        description=c.description,
        category=c.category,
        input_data=c.input_data,
        assertions=[a.to_dict() for a in c.assertions],
        setup_steps=c.setup_steps,
        cleanup_steps=c.cleanup_steps,
        generated_by="preset",
    )
    EvalCaseDAO.insert(db_case)
    count += 1

print(f"\n✅ 已写入 DB: {count} 条")

# 验证总数
all_recall = EvalCaseDAO.list_by_tool(suite_id, tool_name="knowledge_search", category="recall", limit=500)
print(f"DB 中 knowledge_search recall 用例总数: {len(all_recall)}")
