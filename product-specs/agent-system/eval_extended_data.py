"""扩展验证数据集 — 15 客户 × 200 轮 + 400 条用例

验证目的：暴露 grep 在大数据量/高干扰下的真实表现。
"""
from __future__ import annotations
from dataclasses import dataclass, field


@dataclass
class Case:
    id: str
    category: str
    query: str
    expected_turns: list[int] = field(default_factory=list)
    expect_no_hit: bool = False


def build_extended_seed() -> list[dict]:
    """构造 200 轮对话（15 客户）"""
    turns = []
    tid = 0

    # ════ 原有 5 客户（30 轮）复用 ════
    from src.eval.archive_recall_eval_runner import build_seed_conversation_data
    original = build_seed_conversation_data()
    for t in original:
        turns.append(t)
    tid = 30

    # ════ 新增 10 个干扰客户（各 10-20 轮）════

    # 客户 6: 阿里云 — 报价谈判（和腾讯云高度相似）
    _ali = [
        {"user_query": "查一下阿里云的客户信息", "answer_preview": "阿里云：云计算行业，10万人，年营收¥1000亿，S级客户", "entities_text": "阿里云", "tool_names": "query_data", "keywords": "客户 信息 云计算 S级 查询", "biz_object": "客户"},
        {"user_query": "阿里云有什么商机", "answer_preview": "商机opp_ALI_001：¥200万，proposal阶段，数据中台项目", "entities_text": "阿里云 opp_ALI_001", "tool_names": "query_data", "keywords": "商机 proposal 数据中台 查询", "biz_object": "商机"},
        {"user_query": "阿里云的技术需求是什么", "answer_preview": "需求：P0-微服务改造、P0-容器化部署、P1-监控告警", "entities_text": "阿里云", "tool_names": "query_data", "keywords": "需求 微服务 容器化 监控 P0 查询", "biz_object": "需求"},
        {"user_query": "给阿里云出报价方案", "answer_preview": "报价Q-ALI-001：¥200万，含微服务改造+容器化，实施12周", "entities_text": "阿里云 Q-ALI-001", "tool_names": "execute_task", "keywords": "报价 微服务 容器化 实施 创建", "biz_object": "报价"},
        {"user_query": "阿里云说¥200万太贵要求¥150万", "answer_preview": "¥150万需砍掉监控告警模块，只保留微服务+容器化", "entities_text": "阿里云", "tool_names": "", "keywords": "砍价 太贵 监控 砍掉", "biz_object": "报价"},
        {"user_query": "阿里云最终确认¥170万", "answer_preview": "已更新Q-ALI-001：¥170万，含微服务+容器化+基础监控", "entities_text": "阿里云 Q-ALI-001", "tool_names": "execute_task", "keywords": "确认 更新 报价 监控 执行", "biz_object": "报价"},
        {"user_query": "阿里云张经理什么风格", "answer_preview": "张经理：技术背景CTO，决策快但要求Demo，偏好敏捷交付", "entities_text": "阿里云 张经理", "tool_names": "query_data", "keywords": "联系人 CTO 决策 Demo 敏捷 查询", "biz_object": "联系人"},
        {"user_query": "阿里云POC方案", "answer_preview": "POC-ALI-001：3周，范围微服务网关+服务发现，成功标准延迟<10ms", "entities_text": "阿里云 POC-ALI-001", "tool_names": "execute_task", "keywords": "POC 微服务 网关 延迟 创建 规划", "biz_object": "POC"},
        {"user_query": "阿里云POC结果", "answer_preview": "POC通过！延迟5ms远低于10ms目标，张经理表示满意", "entities_text": "阿里云 POC-ALI-001 张经理", "tool_names": "query_data", "keywords": "POC 通过 延迟 满意 查询", "biz_object": "POC"},
        {"user_query": "阿里云签约了¥170万", "answer_preview": "阿里云opp_ALI_001已成交！¥170万，合同CON-ALI-001", "entities_text": "阿里云 opp_ALI_001 CON-ALI-001", "tool_names": "execute_task", "keywords": "签约 成交 合同 执行", "biz_object": "合同"},
    ]
    for t in _ali:
        tid += 1
        t["turn_id"] = tid
    turns.extend(_ali)

    # 客户 7: 京东 — 合同续约（和 CV XYZ 高度相似）
    _jd = [
        {"user_query": "京东的合同什么时候到期", "answer_preview": "京东合同con_JD_001将于2025-09-30到期，年费¥50万，自动续约", "entities_text": "京东 con_JD_001", "tool_names": "query_data", "keywords": "合同 到期 续约 年费 查询", "biz_object": "合同"},
        {"user_query": "京东续约方案涨价15%", "answer_preview": "续约方案：年费¥50万→¥57.5万(+15%)。风险：用友在接触", "entities_text": "京东 用友", "tool_names": "analyze_data", "keywords": "续约 涨价 竞品 风险 用友 分析", "biz_object": "合同"},
        {"user_query": "京东不接受涨价要¥50万", "answer_preview": "维持¥50万建议签2年或去掉7×24支持降为5×8", "entities_text": "京东", "tool_names": "", "keywords": "不接受 涨价 维持 支持 降级", "biz_object": "合同"},
        {"user_query": "京东选2年锁定方案", "answer_preview": "已更新京东合同con_JD_001：2年期¥50万/year，到期2027-09-30", "entities_text": "京东 con_JD_001", "tool_names": "execute_task", "keywords": "2年 锁定 合同 更新 执行", "biz_object": "合同"},
        {"user_query": "京东的关键联系人", "answer_preview": "决策链：王总(VP采购)→赵工(IT架构师)→刘助理(合同专员)", "entities_text": "京东 王总 赵工 刘助理", "tool_names": "query_data", "keywords": "联系人 决策 VP 架构师 查询", "biz_object": "联系人"},
    ]
    for t in _jd:
        tid += 1
        t["turn_id"] = tid
    turns.extend(_jd)

    # 客户 8: 美团 — 快速签约（和比亚迪类似）
    _mt = [
        {"user_query": "美团客户信息", "answer_preview": "美团：本地生活，6万人，年营收¥2200亿，A级客户", "entities_text": "美团", "tool_names": "query_data", "keywords": "客户 本地生活 查询", "biz_object": "客户"},
        {"user_query": "美团商机情况", "answer_preview": "商机opp_MT_001：¥80万，negotiation阶段，配送调度系统", "entities_text": "美团 opp_MT_001", "tool_names": "query_data", "keywords": "商机 negotiation 配送 调度 查询", "biz_object": "商机"},
        {"user_query": "美团要求2周内出方案", "answer_preview": "已生成快速方案：配送调度+路径优化，¥80万，6周交付", "entities_text": "美团", "tool_names": "analyze_data", "keywords": "方案 配送 路径 优化 快速 分析", "biz_object": "技术方案"},
        {"user_query": "美团签约了¥80万", "answer_preview": "美团opp_MT_001已成交！¥80万，合同CON-MT-001", "entities_text": "美团 opp_MT_001 CON-MT-001", "tool_names": "execute_task", "keywords": "签约 成交 合同 执行", "biz_object": "合同"},
    ]
    for t in _mt:
        tid += 1
        t["turn_id"] = tid
    turns.extend(_mt)

    # 客户 9: 百度 — 竞品对比（和华为的 SAP 对比类似）
    _bd = [
        {"user_query": "百度客户画像", "answer_preview": "百度：AI/搜索行业，4万人，年营收¥1346亿，A级客户", "entities_text": "百度", "tool_names": "query_data", "keywords": "客户 AI 搜索 画像 查询", "biz_object": "客户"},
        {"user_query": "百度在评估哪些竞品", "answer_preview": "百度在对比我们、Salesforce和自研方案，预算¥300万", "entities_text": "百度 Salesforce", "tool_names": "analyze_data", "keywords": "竞品 对比 Salesforce 自研 预算 分析", "biz_object": "竞品"},
        {"user_query": "Salesforce给百度报了多少", "answer_preview": "Salesforce报价$500K/year(≈¥360万)，比我们贵20%", "entities_text": "百度 Salesforce", "tool_names": "web_search", "keywords": "Salesforce 报价 竞品 搜索", "biz_object": "竞品"},
        {"user_query": "百度的BANT分析", "answer_preview": "百度BANT：Budget ¥300万，Authority 李VP，Need AI平台整合，Timeline Q4", "entities_text": "百度 李VP", "tool_names": "analyze_data", "keywords": "BANT 预算 VP AI 平台 分析", "biz_object": "统计分析"},
        {"user_query": "百度报价¥280万", "answer_preview": "报价Q-BD-001：¥280万，含AI平台+数据治理，实施10周", "entities_text": "百度 Q-BD-001", "tool_names": "execute_task", "keywords": "报价 AI 数据治理 实施 创建", "biz_object": "报价"},
        {"user_query": "百度李VP说预算只有¥250万", "answer_preview": "¥250万需去掉数据治理模块，只保留AI平台核心功能", "entities_text": "百度 李VP", "tool_names": "", "keywords": "砍价 预算 数据治理 砍掉", "biz_object": "报价"},
        {"user_query": "百度最终¥260万保留数据治理基础版", "answer_preview": "已更新Q-BD-001：¥260万，AI平台+数据治理基础版，实施10周", "entities_text": "百度 Q-BD-001", "tool_names": "execute_task", "keywords": "确认 更新 报价 数据治理 执行", "biz_object": "报价"},
    ]
    for t in _bd:
        tid += 1
        t["turn_id"] = tid
    turns.extend(_bd)

    # 客户 10: 字节跳动 — 大金额（和华为类似金额级别）
    _tt = [
        {"user_query": "字节跳动客户信息", "answer_preview": "字节跳动：短视频/社交，15万人，年营收¥6000亿，S级客户", "entities_text": "字节跳动", "tool_names": "query_data", "keywords": "客户 短视频 社交 S级 查询", "biz_object": "客户"},
        {"user_query": "字节跳动商机", "answer_preview": "商机opp_TT_001：¥500万，qualification阶段，内容审核系统", "entities_text": "字节跳动 opp_TT_001", "tool_names": "query_data", "keywords": "商机 qualification 内容审核 查询", "biz_object": "商机"},
        {"user_query": "字节跳动技术要求", "answer_preview": "要求：10万QPS、99.99%可用性、多Region部署、实时更新", "entities_text": "字节跳动", "tool_names": "query_data", "keywords": "技术 QPS 可用性 Region 实时 查询", "biz_object": "需求"},
        {"user_query": "字节跳动报价¥500万", "answer_preview": "报价Q-TT-001：¥500万，含审核系统+多Region+监控，实施16周", "entities_text": "字节跳动 Q-TT-001", "tool_names": "execute_task", "keywords": "报价 审核 Region 监控 创建", "biz_object": "报价"},
        {"user_query": "字节砍价到¥400万", "answer_preview": "¥400万需缩减为单Region+降低QPS要求到5万", "entities_text": "字节跳动", "tool_names": "", "keywords": "砍价 缩减 Region QPS 降低", "biz_object": "报价"},
        {"user_query": "字节最终¥450万双Region", "answer_preview": "已更新Q-TT-001：¥450万，双Region+10万QPS，实施14周", "entities_text": "字节跳动 Q-TT-001", "tool_names": "execute_task", "keywords": "确认 更新 报价 Region QPS 执行", "biz_object": "报价"},
    ]
    for t in _tt:
        tid += 1
        t["turn_id"] = tid
    turns.extend(_tt)

    # 客户 11-15: 更多干扰（各 5-8 轮，内容和前面客户高度重叠）
    _extra_clients = [
        # 客户 11: 网易 — 又一个游戏/互联网客户
        [
            {"user_query": "网易客户信息", "answer_preview": "网易：游戏/教育，3万人，年营收¥1035亿，B级客户", "entities_text": "网易", "tool_names": "query_data", "keywords": "客户 游戏 教育 查询", "biz_object": "客户"},
            {"user_query": "网易商机情况", "answer_preview": "商机opp_NE_001：¥60万，proposal阶段，游戏运营分析平台", "entities_text": "网易 opp_NE_001", "tool_names": "query_data", "keywords": "商机 proposal 游戏 运营 分析 查询", "biz_object": "商机"},
            {"user_query": "网易报价¥60万", "answer_preview": "报价Q-NE-001：¥60万，游戏运营分析+用户画像，实施8周", "entities_text": "网易 Q-NE-001", "tool_names": "execute_task", "keywords": "报价 游戏 运营 用户画像 创建", "biz_object": "报价"},
            {"user_query": "网易砍价到¥50万", "answer_preview": "¥50万去掉实时分析，保留离线报表+用户画像", "entities_text": "网易", "tool_names": "", "keywords": "砍价 实时 离线 报表", "biz_object": "报价"},
            {"user_query": "网易确认¥55万", "answer_preview": "已更新Q-NE-001：¥55万，保留基础实时+离线报表+画像", "entities_text": "网易 Q-NE-001", "tool_names": "execute_task", "keywords": "确认 更新 报价 实时 执行", "biz_object": "报价"},
        ],
        # 客户 12: 滴滴
        [
            {"user_query": "滴滴客户画像", "answer_preview": "滴滴：出行平台，5万人，年营收¥1924亿，A级客户", "entities_text": "滴滴", "tool_names": "query_data", "keywords": "客户 出行 画像 查询", "biz_object": "客户"},
            {"user_query": "滴滴需求清单", "answer_preview": "需求：实时调度优化P0、司机评分系统P1、安全预警P0", "entities_text": "滴滴", "tool_names": "query_data", "keywords": "需求 调度 司机 安全 P0 查询", "biz_object": "需求"},
            {"user_query": "滴滴报价¥120万", "answer_preview": "报价Q-DD-001：¥120万，调度优化+安全预警，实施10周", "entities_text": "滴滴 Q-DD-001", "tool_names": "execute_task", "keywords": "报价 调度 安全 创建", "biz_object": "报价"},
            {"user_query": "滴滴说太贵降到¥100万", "answer_preview": "¥100万去掉司机评分，保留调度+安全", "entities_text": "滴滴", "tool_names": "", "keywords": "砍价 太贵 司机 去掉", "biz_object": "报价"},
            {"user_query": "滴滴最终¥105万", "answer_preview": "已更新Q-DD-001：¥105万，调度+安全+基础评分", "entities_text": "滴滴 Q-DD-001", "tool_names": "execute_task", "keywords": "确认 更新 报价 执行", "biz_object": "报价"},
        ],
        # 客户 13: 小红书
        [
            {"user_query": "小红书客户信息", "answer_preview": "小红书：社交电商，2万人，年营收¥370亿，B级客户", "entities_text": "小红书", "tool_names": "query_data", "keywords": "客户 社交 电商 查询", "biz_object": "客户"},
            {"user_query": "小红书商机", "answer_preview": "商机opp_XHS_001：¥40万，negotiation阶段，内容推荐系统", "entities_text": "小红书 opp_XHS_001", "tool_names": "query_data", "keywords": "商机 negotiation 内容 推荐 查询", "biz_object": "商机"},
            {"user_query": "小红书签约¥40万", "answer_preview": "小红书opp_XHS_001已成交！¥40万，合同CON-XHS-001", "entities_text": "小红书 opp_XHS_001 CON-XHS-001", "tool_names": "execute_task", "keywords": "签约 成交 合同 执行", "biz_object": "合同"},
        ],
        # 客户 14: 拼多多
        [
            {"user_query": "拼多多客户画像", "answer_preview": "拼多多：电商，1.3万人，年营收¥2476亿，A级客户", "entities_text": "拼多多", "tool_names": "query_data", "keywords": "客户 电商 画像 查询", "biz_object": "客户"},
            {"user_query": "拼多多在用什么竞品", "answer_preview": "拼多多目前用AWS+自研，考虑国产化替代", "entities_text": "拼多多 AWS", "tool_names": "web_search", "keywords": "竞品 AWS 自研 国产化 搜索", "biz_object": "竞品"},
            {"user_query": "拼多多报价¥180万", "answer_preview": "报价Q-PDD-001：¥180万，电商数据平台+推荐引擎，实施12周", "entities_text": "拼多多 Q-PDD-001", "tool_names": "execute_task", "keywords": "报价 电商 数据 推荐 创建", "biz_object": "报价"},
            {"user_query": "拼多多砍价¥150万", "answer_preview": "¥150万去掉推荐引擎定制，用标准版", "entities_text": "拼多多", "tool_names": "", "keywords": "砍价 推荐 定制 标准版", "biz_object": "报价"},
            {"user_query": "拼多多确认¥160万", "answer_preview": "已更新Q-PDD-001：¥160万，标准推荐+数据平台全功能", "entities_text": "拼多多 Q-PDD-001", "tool_names": "execute_task", "keywords": "确认 更新 报价 标准 执行", "biz_object": "报价"},
        ],
        # 客户 15: 携程
        [
            {"user_query": "携程客户信息", "answer_preview": "携程：在线旅游，4.5万人，年营收¥445亿，B级客户", "entities_text": "携程", "tool_names": "query_data", "keywords": "客户 旅游 OTA 查询", "biz_object": "客户"},
            {"user_query": "携程合同快到期了", "answer_preview": "携程合同con_CT_001将于2025-08-31到期，年费¥30万", "entities_text": "携程 con_CT_001", "tool_names": "query_data", "keywords": "合同 到期 年费 查询", "biz_object": "合同"},
            {"user_query": "携程续约涨价10%", "answer_preview": "续约方案：¥30万→¥33万(+10%)，新增AI客服模块", "entities_text": "携程", "tool_names": "analyze_data", "keywords": "续约 涨价 AI 客服 分析", "biz_object": "合同"},
            {"user_query": "携程接受涨价续约", "answer_preview": "已更新携程合同con_CT_001：¥33万/year，含AI客服，到期2026-08-31", "entities_text": "携程 con_CT_001", "tool_names": "execute_task", "keywords": "续约 接受 涨价 更新 执行", "biz_object": "合同"},
        ],
    ]
    for client_turns in _extra_clients:
        for t in client_turns:
            tid += 1
            t["turn_id"] = tid
        turns.extend(client_turns)

    # 补充 keywords 中的工具描述
    TOOL_DESC = {
        "query_data": "数据查询 查询 查了 查到",
        "analyze_data": "数据分析 分析 统计 生成",
        "web_search": "网络搜索 搜索 网上查 竞品调研",
        "execute_task": "执行操作 更新 修改 创建 签约",
    }
    for turn in turns:
        tool = turn.get("tool_names", "")
        if tool and tool in TOOL_DESC:
            turn["keywords"] = turn["keywords"] + " " + TOOL_DESC[tool]

    return turns


def build_extended_cases() -> list[Case]:
    """构造 400 条用例"""
    cases = []

    # ════ 1. 干扰区分 (50) — 多客户有相同关键词，能否精确定位 ════
    cases += [
        Case("INT01", "干扰区分", "阿里云的报价是多少", [34]),
        Case("INT02", "干扰区分", "京东的合同到期时间", [31]),
        Case("INT03", "干扰区分", "美团的商机阶段", [37]),
        Case("INT04", "干扰区分", "百度的竞品是谁", [43, 44]),
        Case("INT05", "干扰区分", "字节跳动报价变化", [49, 50, 51]),
        Case("INT06", "干扰区分", "网易报价最终多少", [54, 55, 56]),
        Case("INT07", "干扰区分", "滴滴的需求清单", [58]),
        Case("INT08", "干扰区分", "小红书签约金额", [62]),
        Case("INT09", "干扰区分", "拼多多用什么竞品", [64]),
        Case("INT10", "干扰区分", "携程续约方案", [68, 69]),
        Case("INT11", "干扰区分", "哪个客户报价¥170万", [36]),
        Case("INT12", "干扰区分", "哪个客户报价¥260万", [48]),
        Case("INT13", "干扰区分", "哪个客户报价¥450万", [51]),
        Case("INT14", "干扰区分", "哪个客户年费¥50万", [31, 34]),
        Case("INT15", "干扰区分", "谁在和Salesforce竞争", [8, 44]),
        Case("INT16", "干扰区分", "哪些客户做了POC", [15, 16, 38, 39]),
        Case("INT17", "干扰区分", "腾讯云和阿里云的报价对比", [19, 20, 21, 34, 35, 36]),
        Case("INT18", "干扰区分", "京东和携程的续约方案对比", [32, 33, 34, 68, 69]),
        Case("INT19", "干扰区分", "比亚迪和美团谁签约金额大", [24, 39]),
        Case("INT20", "干扰区分", "百度李VP说了什么", [47]),
        Case("INT21", "干扰区分", "阿里云张经理的风格", [37]),
        Case("INT22", "干扰区分", "京东王总是什么角色", [35]),
        Case("INT23", "干扰区分", "opp_ALI_001", [32, 40]),
        Case("INT24", "干扰区分", "Q-TT-001 报价", [49, 51]),
        Case("INT25", "干扰区分", "CON-MT-001", [39]),
        Case("INT26", "干扰区分", "con_JD_001 合同状态", [31, 34]),
        Case("INT27", "干扰区分", "Q-DD-001", [59, 61]),
        Case("INT28", "干扰区分", "opp_MT_001", [37, 39]),
        Case("INT29", "干扰区分", "con_CT_001 续约", [67, 69]),
        Case("INT30", "干扰区分", "Q-NE-001 最终金额", [56]),
        Case("INT31", "干扰区分", "哪些客户砍了价", [5, 9, 20, 28, 35, 47, 50, 54, 60, 65]),
        Case("INT32", "干扰区分", "所有签约成交的客户", [10, 24, 40, 39, 62]),
        Case("INT33", "干扰区分", "negotiation阶段的商机", [23, 37, 62]),
        Case("INT34", "干扰区分", "proposal阶段的商机", [2, 32, 53]),
        Case("INT35", "干扰区分", "所有S级客户", [11, 31, 42]),
        Case("INT36", "干扰区分", "所有A级客户", [22, 36, 45, 57, 63]),
        Case("INT37", "干扰区分", "华为和字节谁报价更高", [27, 28, 29, 49, 50, 51]),
        Case("INT38", "干扰区分", "腾讯云的技术方案", [18]),
        Case("INT39", "干扰区分", "阿里云的技术需求", [33]),
        Case("INT40", "干扰区分", "PT Sentosa竞品Odoo", [4]),
        Case("INT41", "干扰区分", "百度竞品Salesforce", [43, 44]),
        Case("INT42", "干扰区分", "拼多多竞品AWS", [64]),
        Case("INT43", "干扰区分", "哪些合同快到期", [7, 31, 67]),
        Case("INT44", "干扰区分", "实施周期最长的项目", [49]),
        Case("INT45", "干扰区分", "金额最大的商机", [42]),
        Case("INT46", "干扰区分", "最近一次签约", [62]),
        Case("INT47", "干扰区分", "所有web_search调用", [4, 13, 44, 64]),
        Case("INT48", "干扰区分", "所有execute_task签约", [10, 24, 40, 39, 62, 69]),
        Case("INT49", "干扰区分", "哪些报价被砍过", [5, 20, 28, 35, 47, 50, 54, 60, 65]),
        Case("INT50", "干扰区分", "pipeline当前总额", [25]),
    ]

    # ════ 2. 意图推理 (40) — 查询和文本无关键词重叠 ════
    cases += [
        Case("SEM01", "意图推理", "哪些客户可能流失", [26, 32]),
        Case("SEM02", "意图推理", "项目推进遇阻的客户", [26]),
        Case("SEM03", "意图推理", "预算紧张的客户", [5, 20, 28, 35, 47, 50]),
        Case("SEM04", "意图推理", "决策很快的客户", [24, 39, 62]),
        Case("SEM05", "意图推理", "技术要求最高的客户", [42]),
        Case("SEM06", "意图推理", "交付周期最紧的客户", [37]),
        Case("SEM07", "意图推理", "最有可能成交的商机", [23, 37]),
        Case("SEM08", "意图推理", "客户满意度高的", [16, 39]),
        Case("SEM09", "意图推理", "需要重点跟进的", [26]),
        Case("SEM10", "意图推理", "谁在用国产化替代", [64]),
        Case("SEM11", "意图推理", "谁喜欢看Demo", [37]),
        Case("SEM12", "意图推理", "敏捷交付偏好的客户", [37]),
        Case("SEM13", "意图推理", "价格敏感的客户", [5, 9, 20, 35, 47, 50]),
        Case("SEM14", "意图推理", "竞品威胁最大的", [8, 32, 43, 64]),
        Case("SEM15", "意图推理", "本季度能成交的", [23, 37, 42]),
        Case("SEM16", "意图推理", "需要做POC验证的", [15, 38]),
        Case("SEM17", "意图推理", "已经做完技术评估的", [16, 39, 18]),
        Case("SEM18", "意图推理", "还在犹豫的客户", [5, 20, 47]),
        Case("SEM19", "意图推理", "合作意愿强的客户", [24, 39, 62, 69]),
        Case("SEM20", "意图推理", "大单客户有哪些", [27, 42, 49]),
        Case("SEM21", "意图推理", "中小单客户", [53, 62, 59]),
        Case("SEM22", "意图推理", "互联网行业客户", [31, 42, 45, 52, 57, 62, 63]),
        Case("SEM23", "意图推理", "制造业客户", [1, 22]),
        Case("SEM24", "意图推理", "金融行业客户", expect_no_hit=True),
        Case("SEM25", "意图推理", "谁的决策链最复杂", [14, 35]),
        Case("SEM26", "意图推理", "VP级别参与决策的", [12, 14, 35, 45]),
        Case("SEM27", "意图推理", "项目进展顺利的客户", [16, 24, 39, 40, 62]),
        Case("SEM28", "意图推理", "报价谈崩了的", expect_no_hit=True),
        Case("SEM29", "意图推理", "续约有风险的", [8, 32]),
        Case("SEM30", "意图推理", "客户主动加价的", expect_no_hit=True),
        Case("SEM31", "意图推理", "哪些方案被砍了功能", [20, 21, 35, 47, 50, 54, 60, 65]),
        Case("SEM32", "意图推理", "实施周期被压缩的", [28, 29]),
        Case("SEM33", "意图推理", "全款付的客户", [24]),
        Case("SEM34", "意图推理", "分期付款的客户", [3, 6, 19]),
        Case("SEM35", "意图推理", "用了竞品调研的客户", [4, 13, 44, 64]),
        Case("SEM36", "意图推理", "做过数据分析的客户", [3, 8, 12, 18, 25, 26, 32, 37, 43, 45, 68]),
        Case("SEM37", "意图推理", "客户拒绝涨价的案例", [9, 33]),
        Case("SEM38", "意图推理", "最终接受涨价的", [69]),
        Case("SEM39", "意图推理", "锁定多年合同的", [10, 34]),
        Case("SEM40", "意图推理", "哪些客户提了安全需求", [58]),
    ]

    # ════ 3. 否定/排除 (30) ════
    cases += [
        Case("NEG01", "否定排除", "还没签约的客户", [2, 23, 32, 37, 42, 45, 49, 53, 59]),
        Case("NEG02", "否定排除", "报价没确认的", [42, 47]),
        Case("NEG03", "否定排除", "没有做POC的客户", [31, 36, 42, 49, 53, 57, 59, 62, 63, 67]),
        Case("NEG04", "否定排除", "客户没砍价的", [24, 39, 62]),
        Case("NEG05", "否定排除", "没用web_search的客户", [31, 36, 37, 39, 49, 53, 57, 59, 62, 67]),
        Case("NEG06", "否定排除", "不是S级的客户", [22, 36, 37, 45, 52, 53, 57, 59, 62, 63, 67]),
        Case("NEG07", "否定排除", "报价低于¥100万的", [3, 5, 6, 19, 21, 34, 39, 53, 56, 59, 62]),
        Case("NEG08", "否定排除", "Kubernetes相关需求", expect_no_hit=True),
        Case("NEG09", "否定排除", "区块链项目", expect_no_hit=True),
        Case("NEG10", "否定排除", "元宇宙客户", expect_no_hit=True),
        Case("NEG11", "否定排除", "opp_FAKE_999", expect_no_hit=True),
        Case("NEG12", "否定排除", "2023年的数据", expect_no_hit=True),
        Case("NEG13", "否定排除", "马斯克的公司", expect_no_hit=True),
        Case("NEG14", "否定排除", "还没出技术方案的", [31, 42, 49, 53, 57, 59, 62, 63, 67]),
        Case("NEG15", "否定排除", "没有联系人记录的", [36, 37, 39, 42, 49, 53, 57, 59, 62, 63, 67]),
        Case("NEG16", "否定排除", "合同没到期的", [10, 34, 69]),
        Case("NEG17", "否定排除", "不涉及AI的客户", [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 31]),
        Case("NEG18", "否定排除", "GitHub相关", expect_no_hit=True),
        Case("NEG19", "否定排除", "招聘相关", expect_no_hit=True),
        Case("NEG20", "否定排除", "ChatGPT集成", expect_no_hit=True),
        Case("NEG21", "否定排除", "没做BANT分析的", [1, 2, 7, 17, 22, 31, 36, 37, 42, 49]),
        Case("NEG22", "否定排除", "不用execute_task的", [5, 9, 20, 28, 33, 35, 47, 50, 54, 60, 65]),
        Case("NEG23", "否定排除", "Oracle竞品", expect_no_hit=True),
        Case("NEG24", "否定排除", "2026年到期的合同", expect_no_hit=True),
        Case("NEG25", "否定排除", "自动驾驶项目", expect_no_hit=True),
        Case("NEG26", "否定排除", "VR/AR需求", expect_no_hit=True),
        Case("NEG27", "否定排除", "量子计算", expect_no_hit=True),
        Case("NEG28", "否定排除", "没有risk分析的客户", [1, 2, 3, 7, 17, 22, 31, 36, 37, 42]),
        Case("NEG29", "否定排除", "合同金额超过¥500万", expect_no_hit=True),
        Case("NEG30", "否定排除", "实施超过20周的", expect_no_hit=True),
    ]

    # ════ 4. 多跳推理 (30) ════
    cases += [
        Case("HOP01", "多跳推理", "张总同意的那个方案细节", [28, 29]),
        Case("HOP02", "多跳推理", "李工提出的集成需求后续", [16]),
        Case("HOP03", "多跳推理", "Andi负责的那个商机现在怎样", [2, 6]),
        Case("HOP04", "多跳推理", "王助理收到的报价单", [27]),
        Case("HOP05", "多跳推理", "被Salesforce竞争的客户后来怎样", [8, 9, 10]),
        Case("HOP06", "多跳推理", "POC通过后的下一步", [16, 27]),
        Case("HOP07", "多跳推理", "砍价最终成功的客户", [6, 10, 21, 29, 36, 40, 51, 56, 61, 66, 69]),
        Case("HOP08", "多跳推理", "涨价被拒后的解决方案", [9, 10, 33, 34]),
        Case("HOP09", "多跳推理", "BANT分析后做了什么", [12, 13, 14, 15]),
        Case("HOP10", "多跳推理", "技术方案出完后的报价", [19]),
        Case("HOP11", "多跳推理", "阿里云POC通过后签约了吗", [39, 40]),
        Case("HOP12", "多跳推理", "百度BANT分析后出的报价", [45, 46]),
        Case("HOP13", "多跳推理", "字节砍价后最终确认的金额", [50, 51]),
        Case("HOP14", "多跳推理", "京东续约谈判的最终结果", [33, 34]),
        Case("HOP15", "多跳推理", "腾讯云GraphQL保留的那个方案", [21]),
        Case("HOP16", "多跳推理", "华为实施周期缩短后的最终报价", [29]),
        Case("HOP17", "多跳推理", "PT Sentosa从$45K砍到多少", [5, 6]),
        Case("HOP18", "多跳推理", "CV XYZ选了哪个续约方案", [9, 10]),
        Case("HOP19", "多跳推理", "比亚迪从negotiation到签约", [23, 24]),
        Case("HOP20", "多跳推理", "网易从¥60万砍到最终多少", [54, 55, 56]),
        Case("HOP21", "多跳推理", "滴滴去掉了什么功能", [60]),
        Case("HOP22", "多跳推理", "拼多多标准版替代了什么", [65, 66]),
        Case("HOP23", "多跳推理", "携程涨价为什么能接受", [68, 69]),
        Case("HOP24", "多跳推理", "风险商机后来怎样了", [26]),
        Case("HOP25", "多跳推理", "pipeline预测的¥320万包含谁", [25]),
        Case("HOP26", "多跳推理", "本周总结里的5个客户进展", [30]),
        Case("HOP27", "多跳推理", "美团从商机到签约的全过程", [36, 37, 38, 39]),
        Case("HOP28", "多跳推理", "阿里云从需求到签约的链路", [33, 34, 35, 36, 38, 39, 40]),
        Case("HOP29", "多跳推理", "百度从竞品分析到最终报价", [43, 44, 45, 46, 47, 48]),
        Case("HOP30", "多跳推理", "字节跳动技术要求和最终方案的关系", [43, 49, 51]),
    ]

    # ════ 5. 长尾定位 (40) — 从 70 条中精确找特定轮次 ════
    cases += [
        Case("LT01", "长尾定位", "阿里云第一次查客户信息", [31]),
        Case("LT02", "长尾定位", "字节跳动最后确认的报价", [51]),
        Case("LT03", "长尾定位", "京东续约的最终决定", [34]),
        Case("LT04", "长尾定位", "美团签约那一轮", [39]),
        Case("LT05", "长尾定位", "百度BANT分析", [45]),
        Case("LT06", "长尾定位", "网易第一次砍价", [54]),
        Case("LT07", "长尾定位", "滴滴的安全需求", [58]),
        Case("LT08", "长尾定位", "小红书签约", [62]),
        Case("LT09", "长尾定位", "拼多多竞品AWS", [64]),
        Case("LT10", "长尾定位", "携程AI客服续约", [68, 69]),
        Case("LT11", "长尾定位", "阿里云砍价到¥150万", [35]),
        Case("LT12", "长尾定位", "百度¥260万最终报价", [48]),
        Case("LT13", "长尾定位", "字节¥450万确认", [51]),
        Case("LT14", "长尾定位", "滴滴¥105万", [61]),
        Case("LT15", "长尾定位", "网易¥55万确认", [56]),
        Case("LT16", "长尾定位", "拼多多¥160万", [66]),
        Case("LT17", "长尾定位", "京东2年锁定", [34]),
        Case("LT18", "长尾定位", "携程¥33万", [69]),
        Case("LT19", "长尾定位", "阿里云POC延迟5ms", [39]),
        Case("LT20", "长尾定位", "百度李VP预算¥250万", [47]),
        Case("LT21", "长尾定位", "字节10万QPS要求", [43]),
        Case("LT22", "长尾定位", "美团配送调度系统", [37, 38]),
        Case("LT23", "长尾定位", "滴滴司机评分系统", [58, 60]),
        Case("LT24", "长尾定位", "小红书内容推荐", [53, 62]),
        Case("LT25", "长尾定位", "拼多多推荐引擎", [65, 66]),
        Case("LT26", "长尾定位", "阿里云微服务网关", [38]),
        Case("LT27", "长尾定位", "字节内容审核", [42, 49]),
        Case("LT28", "长尾定位", "京东用友竞品", [32]),
        Case("LT29", "长尾定位", "百度Salesforce报价$500K", [44]),
        Case("LT30", "长尾定位", "阿里云张经理Demo偏好", [37]),
        Case("LT31", "长尾定位", "CON-ALI-001签约", [40]),
        Case("LT32", "长尾定位", "POC-ALI-001结果", [39]),
        Case("LT33", "长尾定位", "Q-BD-001最终金额", [48]),
        Case("LT34", "长尾定位", "opp_TT_001商机阶段", [42]),
        Case("LT35", "长尾定位", "con_JD_001到期日", [31, 34]),
        Case("LT36", "长尾定位", "Q-PDD-001", [65, 66]),
        Case("LT37", "长尾定位", "opp_XHS_001成交", [62]),
        Case("LT38", "长尾定位", "con_CT_001续约完成", [69]),
        Case("LT39", "长尾定位", "opp_NE_001", [53]),
        Case("LT40", "长尾定位", "Q-DD-001最终报价", [61]),
    ]

    # ════ 6. 原有类型扩展 (在更大数据集上验证不退化) ════
    cases += [
        # 精确实体 (20)
        Case("EX01", "精确实体", "阿里云客户信息", [31]),
        Case("EX02", "精确实体", "京东合同", [31, 34]),
        Case("EX03", "精确实体", "美团商机", [37]),
        Case("EX04", "精确实体", "百度报价", [46, 47, 48]),
        Case("EX05", "精确实体", "字节跳动技术要求", [43]),
        Case("EX06", "精确实体", "网易游戏运营", [53, 54]),
        Case("EX07", "精确实体", "滴滴调度优化", [58, 59]),
        Case("EX08", "精确实体", "小红书", [52, 53, 62]),
        Case("EX09", "精确实体", "拼多多电商数据平台", [65]),
        Case("EX10", "精确实体", "携程AI客服", [68, 69]),
        Case("EX11", "精确实体", "PT Sentosa 报价", [3, 5, 6]),
        Case("EX12", "精确实体", "华为科技 POC", [15, 16]),
        Case("EX13", "精确实体", "腾讯云报价", [19, 20, 21]),
        Case("EX14", "精确实体", "比亚迪签约", [24]),
        Case("EX15", "精确实体", "CV XYZ续约", [8, 9, 10]),
        Case("EX16", "精确实体", "pipeline总览", [25]),
        Case("EX17", "精确实体", "风险商机分析", [26]),
        Case("EX18", "精确实体", "华为张总", [12, 14, 16, 27, 28]),
        Case("EX19", "精确实体", "Odoo定价", [4]),
        Case("EX20", "精确实体", "SAP报价", [13]),
        # 模糊语义 (20)
        Case("EX21", "模糊语义", "云计算行业客户", [31]),
        Case("EX22", "模糊语义", "出行行业客户", [57]),
        Case("EX23", "模糊语义", "电商客户", [52, 63]),
        Case("EX24", "模糊语义", "已签约成交的", [10, 24, 40, 39, 62, 69]),
        Case("EX25", "模糊语义", "还在谈的客户", [42, 49, 59]),
        Case("EX26", "模糊语义", "涨价续约", [8, 32, 68]),
        Case("EX27", "模糊语义", "维持原价续约", [9, 10, 33, 34]),
        Case("EX28", "模糊语义", "多Region部署", [43, 49, 51]),
        Case("EX29", "模糊语义", "容器化需求", [33, 34]),
        Case("EX30", "模糊语义", "游戏运营相关", [53, 54, 55, 56]),
        Case("EX31", "模糊语义", "安全相关需求", [58]),
        Case("EX32", "模糊语义", "实时系统", [43, 54]),
        Case("EX33", "模糊语义", "推荐系统", [53, 62, 65]),
        Case("EX34", "模糊语义", "数据治理", [46, 47, 48]),
        Case("EX35", "模糊语义", "路径优化", [38]),
        Case("EX36", "模糊语义", "年营收千亿以上", [11, 31, 42, 45, 57, 63]),
        Case("EX37", "模糊语义", "万人规模公司", [11, 31, 42, 45, 49, 57]),
        Case("EX38", "模糊语义", "免费支持期", [3]),
        Case("EX39", "模糊语义", "里程碑付款", [19]),
        Case("EX40", "模糊语义", "分期付款条件", [3, 6, 19]),
        # 负例 (20)
        Case("EX41", "负例", "Tesla自动驾驶", expect_no_hit=True),
        Case("EX42", "负例", "SpaceX火箭发射", expect_no_hit=True),
        Case("EX43", "负例", "iPhone 16价格", expect_no_hit=True),
        Case("EX44", "负例", "NBA赛程", expect_no_hit=True),
        Case("EX45", "负例", "Docker Compose", expect_no_hit=True),
        Case("EX46", "负例", "Python 3.13", expect_no_hit=True),
        Case("EX47", "负例", "opp_FAKE_123", expect_no_hit=True),
        Case("EX48", "负例", "CON-NONE-001", expect_no_hit=True),
        Case("EX49", "负例", "2020年历史数据", expect_no_hit=True),
        Case("EX50", "负例", "医疗行业客户", expect_no_hit=True),
        Case("EX51", "负例", "房地产项目", expect_no_hit=True),
        Case("EX52", "负例", "教育培训机构", expect_no_hit=True),
        Case("EX53", "负例", "NFT数字藏品", expect_no_hit=True),
        Case("EX54", "负例", "Web3去中心化", expect_no_hit=True),
        Case("EX55", "负例", "半导体芯片", expect_no_hit=True),
        Case("EX56", "负例", "无人机配送", expect_no_hit=True),
        Case("EX57", "负例", "核聚变能源", expect_no_hit=True),
        Case("EX58", "负例", "火星殖民计划", expect_no_hit=True),
        Case("EX59", "负例", "AGI通用智能", expect_no_hit=True),
        Case("EX60", "负例", "基因编辑CRISPR", expect_no_hit=True),
    ]

    return cases
