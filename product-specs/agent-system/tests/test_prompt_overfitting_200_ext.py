"""四路提取提示词过拟合验证 — 200 个扩展测试场景

这是 test_prompt_overfitting_100.py 的补充扩展集，覆盖：
  - 多行业场景（研发/运维/投资/教育/医疗/客服/HR/法务）
  - 多种句式（长句/碎片/中英混合/反问/条件/时间状语）
  - 工具调用结果场景（含 ToolMessage 上下文）
  - 更多边界对抗（profile vs entities、preferences vs agent_rules 深度混淆）

场景分布（共 200 个）：
  A. Profile 正例（1-30）        30 — 多行业身份 / 组织特征 / 履历
  B. Preferences 正例（31-60）   30 — 多维度偏好 / 口语化 / 否定 / 条件
  C. Agent Rules 正例（61-90）   30 — 多领域指令 / 输出 / 流程 / 角色 / 安全
  D. Entities 正例（91-125）     35 — 多类型第三方 / 指代 / 关系 / 竞情 / 时效
  E. 不提取场景（126-160）       35 — 操作 / 寒暄 / 查询 / 确认 / 评价 / 系统数据
  F. 混合意图场景（161-185）     25 — 2-3 维度混合
  G. 边界对抗场景（186-200）     15 — 深度微妙歧义

运行:
  cd product-specs/agent-system
  .venv/bin/python -B tests/test_prompt_overfitting_200_ext.py
  .venv/bin/python -B tests/test_prompt_overfitting_200_ext.py --group G
  .venv/bin/python -B tests/test_prompt_overfitting_200_ext.py --start 180 --end 200
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
# 200 个扩展测试用例
# 格式: (id, group, input, expect_dict, test_goal)
# ═══════════════════════════════════════════════════════════

CASES = [
    # ══════════════════════════════════════════════════════
    # A. Profile 正例（1-30）多行业身份 / 组织特征 / 履历
    # ══════════════════════════════════════════════════════

    # —— 多行业身份 ——
    (1, "A", "我是一名临床医生，主要看心内科门诊",
        {"profile": True, "preferences": False, "agent_rules": False, "entities": False},
        "医疗行业身份"),
    (2, "A", "我们律所是做跨境并购的，合伙人有6个",
        {"profile": True, "preferences": False, "agent_rules": False, "entities": False},
        "法律行业+组织规模"),
    (3, "A", "本人在高校做科研，方向是 NLP",
        {"profile": True, "preferences": False, "agent_rules": False, "entities": False},
        "学术+英文术语混合"),
    (4, "A", "做私募二级的，主攻港股科技板块",
        {"profile": True, "preferences": False, "agent_rules": False, "entities": False},
        "金融投资+省略主语"),
    (5, "A", "在大厂做基础架构，偏向存储方向",
        {"profile": True, "preferences": False, "agent_rules": False, "entities": False},
        "研发岗位+省略主语"),
    (6, "A", "我是运维团队的 leader，团队12个人分成 SRE 和 DBA 两组",
        {"profile": True, "preferences": False, "agent_rules": False, "entities": False},
        "运维+中英混合+团队结构"),
    (7, "A", "做K12课外辅导十几年了，现在在做教研",
        {"profile": True, "preferences": False, "agent_rules": False, "entities": False},
        "教育行业履历"),
    (8, "A", "我在三甲医院做影像科主任",
        {"profile": True, "preferences": False, "agent_rules": False, "entities": False},
        "医疗管理职级"),
    (9, "A", "我负责公司的数据合规和法务审查",
        {"profile": True, "preferences": False, "agent_rules": False, "entities": False},
        "法务复合职能"),
    (10, "A", "客服团队的组长，负责电商售后板块",
        {"profile": True, "preferences": False, "agent_rules": False, "entities": False},
        "客服角色+省略主语"),

    # —— 组织特征 ——
    (11, "A", "我们公司刚拿到B轮融资，估值10亿左右",
        {"profile": True, "preferences": False, "agent_rules": False, "entities": False},
        "公司融资状态"),
    (12, "A", "我们团队实行弹性工作制，核心时间是10点到4点",
        {"profile": True, "preferences": False, "agent_rules": False, "entities": False},
        "团队工作制度"),
    (13, "A", "公司总部在上海，我在北京分公司",
        {"profile": True, "preferences": False, "agent_rules": False, "entities": False},
        "公司地理+个人驻地"),
    (14, "A", "我们业务线今年的目标是盈亏平衡",
        {"profile": True, "preferences": False, "agent_rules": False, "entities": False},
        "业务线目标"),
    (15, "A", "部门新接手了两个子系统，人手不够",
        {"profile": True, "preferences": False, "agent_rules": False, "entities": False},
        "部门状态描述"),

    # —— 履历与背景 ——
    (16, "A", "本科清华计算机，硕士去了CMU",
        {"profile": True, "preferences": False, "agent_rules": False, "entities": False},
        "学术履历"),
    (17, "A", "前两份工作都在游戏公司，最近转型做SaaS",
        {"profile": True, "preferences": False, "agent_rules": False, "entities": False},
        "职业转型履历"),
    (18, "A", "做过测试、开发、产品，算是全栈PM",
        {"profile": True, "preferences": False, "agent_rules": False, "entities": False},
        "多岗位复合背景"),
    (19, "A", "创业过一次失败了，现在回大厂打工",
        {"profile": True, "preferences": False, "agent_rules": False, "entities": False},
        "创业经历"),
    (20, "A", "我之前是临床医生后来转行做医药代表",
        {"profile": True, "preferences": False, "agent_rules": False, "entities": False},
        "跨行业转型"),

    # —— KPI 与职责 ——
    (21, "A", "今年我的OKR是把续费率提到90%",
        {"profile": True, "preferences": False, "agent_rules": False, "entities": False},
        "OKR + 数值目标"),
    (22, "A", "我盯着三个垂类的GMV，美妆母婴和食品",
        {"profile": True, "preferences": False, "agent_rules": False, "entities": False},
        "职责覆盖范围"),
    (23, "A", "负责的产品线ARR大概2000万",
        {"profile": True, "preferences": False, "agent_rules": False, "entities": False},
        "职责+ARR指标"),
    (24, "A", "管理的团队跨三个时区",
        {"profile": True, "preferences": False, "agent_rules": False, "entities": False},
        "跨区域管理"),
    (25, "A", "今年负责的项目是公司的S1战略项目",
        {"profile": True, "preferences": False, "agent_rules": False, "entities": False},
        "战略项目定位"),

    # —— 语言/地域 ——
    (26, "A", "我常用中英双语，跟海外客户邮件基本都是英文",
        {"profile": True, "preferences": False, "agent_rules": False, "entities": False},
        "语言画像（非偏好表达）"),
    (27, "A", "我在硅谷湾区工作，时区UTC-8",
        {"profile": True, "preferences": False, "agent_rules": False, "entities": False},
        "地域时区"),

    # —— 隐式身份 ——
    (28, "A", "公司给我配了两个助理一个司机",
        {"profile": True, "preferences": False, "agent_rules": False, "entities": False},
        "隐式高管身份"),
    (29, "A", "我是应届生刚入职两周",
        {"profile": True, "preferences": False, "agent_rules": False, "entities": False},
        "新人状态"),
    (30, "A", "退休返聘的，主要做顾问工作",
        {"profile": True, "preferences": False, "agent_rules": False, "entities": False},
        "特殊雇佣关系"),

    # ══════════════════════════════════════════════════════
    # B. Preferences 正例（31-60）多维度偏好
    # ══════════════════════════════════════════════════════

    # —— 数据展示类偏好 ——
    (31, "B", "我一般看周维度数据，日维度太碎",
        {"profile": False, "preferences": True, "agent_rules": False, "entities": False},
        "数据粒度偏好"),
    (32, "B", "我更在意留存曲线而不是DAU绝对数",
        {"profile": False, "preferences": True, "agent_rules": False, "entities": False},
        "关注指标偏好"),
    (33, "B", "看报表我只关心异常指标，正常的直接跳过",
        {"profile": False, "preferences": True, "agent_rules": False, "entities": False},
        "阅读习惯"),
    (34, "B", "我对配色不太挑但讨厌纯黑底",
        {"profile": False, "preferences": True, "agent_rules": False, "entities": False},
        "视觉偏好"),

    # —— 沟通偏好 ——
    (35, "B", "我习惯异步沟通，不太爱接电话",
        {"profile": False, "preferences": True, "agent_rules": False, "entities": False},
        "沟通方式偏好"),
    (36, "B", "开会我喜欢开摄像头，不然没氛围",
        {"profile": False, "preferences": True, "agent_rules": False, "entities": False},
        "会议偏好"),
    (37, "B", "文档我一般只读摘要和结论",
        {"profile": False, "preferences": True, "agent_rules": False, "entities": False},
        "阅读偏好"),

    # —— 工作习惯 ——
    (38, "B", "我习惯每天早上先清邮件再看任务",
        {"profile": False, "preferences": True, "agent_rules": False, "entities": False},
        "日常工作流偏好"),
    (39, "B", "我一般周日晚上复盘下周计划",
        {"profile": False, "preferences": True, "agent_rules": False, "entities": False},
        "复盘习惯"),
    (40, "B", "遇到难题我先画图再动手写代码",
        {"profile": False, "preferences": True, "agent_rules": False, "entities": False},
        "问题解决风格"),

    # —— 口语化/反问 ——
    (41, "B", "长邮件真的看得头大",
        {"profile": False, "preferences": True, "agent_rules": False, "entities": False},
        "抱怨式偏好"),
    (42, "B", "PPT太花哨反而抓不到重点",
        {"profile": False, "preferences": True, "agent_rules": False, "entities": False},
        "反向偏好"),
    (43, "B", "我对PPT没什么感觉，文档就行",
        {"profile": False, "preferences": True, "agent_rules": False, "entities": False},
        "无感型偏好"),
    (44, "B", "视频会议开多了真受不了",
        {"profile": False, "preferences": True, "agent_rules": False, "entities": False},
        "厌倦式偏好"),

    # —— 条件型 ——
    (45, "B", "工作日我一般不看群消息，等周报里汇总",
        {"profile": False, "preferences": True, "agent_rules": False, "entities": False},
        "时间条件偏好"),
    (46, "B", "出差期间我只处理紧急事项",
        {"profile": False, "preferences": True, "agent_rules": False, "entities": False},
        "场景条件偏好"),
    (47, "B", "涉及金额超过50万的决策我要亲自过",
        {"profile": False, "preferences": True, "agent_rules": False, "entities": False},
        "阈值条件习惯"),

    # —— 饮食/生活（偶尔影响工作场景）——
    (48, "B", "我不喝咖啡，下午一般喝茶",
        {"profile": False, "preferences": True, "agent_rules": False, "entities": False},
        "日常饮食偏好"),

    # —— 语言/书写风格偏好 ——
    (49, "B", "我喜欢中英混写，专业术语保留英文",
        {"profile": False, "preferences": True, "agent_rules": False, "entities": False},
        "书写风格偏好"),
    (50, "B", "我读文档更习惯看英文原版",
        {"profile": False, "preferences": True, "agent_rules": False, "entities": False},
        "阅读语言偏好"),

    # —— 工具偏好 ——
    (51, "B", "我习惯用Notion做笔记，Obsidian尝试过用不惯",
        {"profile": False, "preferences": True, "agent_rules": False, "entities": False},
        "工具偏好"),
    (52, "B", "代码我都用 VS Code，IDEA 不太适应",
        {"profile": False, "preferences": True, "agent_rules": False, "entities": False},
        "IDE偏好"),

    # —— 决策风格 ——
    (53, "B", "我做决策比较慢，喜欢看完所有数据再定",
        {"profile": False, "preferences": True, "agent_rules": False, "entities": False},
        "决策风格"),
    (54, "B", "遇到分歧我倾向先听反对意见",
        {"profile": False, "preferences": True, "agent_rules": False, "entities": False},
        "协商偏好"),

    # —— 汇报偏好 ——
    (55, "B", "汇报我习惯口头先过一遍，书面材料后补",
        {"profile": False, "preferences": True, "agent_rules": False, "entities": False},
        "汇报节奏偏好"),
    (56, "B", "我不太喜欢PPT汇报，直接白板讲更清楚",
        {"profile": False, "preferences": True, "agent_rules": False, "entities": False},
        "汇报形式偏好"),

    # —— 协作偏好 ——
    (57, "B", "我习惯一次性给完反馈，不喜欢来回多次",
        {"profile": False, "preferences": True, "agent_rules": False, "entities": False},
        "反馈节奏偏好"),
    (58, "B", "code review 我会逐行看，不喜欢粗略扫",
        {"profile": False, "preferences": True, "agent_rules": False, "entities": False},
        "评审风格偏好"),

    # —— 隐式偏好 ——
    (59, "B", "冗长的会议纪要我从来不读",
        {"profile": False, "preferences": True, "agent_rules": False, "entities": False},
        "隐式否定偏好"),
    (60, "B", "我对紧急通知比较敏感，一般5分钟内回",
        {"profile": False, "preferences": True, "agent_rules": False, "entities": False},
        "敏感度偏好"),

    # ══════════════════════════════════════════════════════
    # C. Agent Rules 正例（61-90）多领域指令
    # ══════════════════════════════════════════════════════

    # —— 角色定义（多行业）——
    (61, "C", "你是我的代码审查助手，帮我找出潜在bug",
        {"profile": False, "preferences": False, "agent_rules": True, "entities": False},
        "研发场景角色"),
    (62, "C", "以后就把你当我的投研助理来用",
        {"profile": False, "preferences": False, "agent_rules": True, "entities": False},
        "投资场景角色"),
    (63, "C", "你的定位是医学文献检索助手",
        {"profile": False, "preferences": False, "agent_rules": True, "entities": False},
        "医疗场景角色"),
    (64, "C", "你扮演我的合同审核AI，专盯风险条款",
        {"profile": False, "preferences": False, "agent_rules": True, "entities": False},
        "法务场景角色"),
    (65, "C", "你是我的英语口语陪练",
        {"profile": False, "preferences": False, "agent_rules": True, "entities": False},
        "学习场景角色"),

    # —— 输出格式 ——
    (66, "C", "代码片段要带上语言标记和注释",
        {"profile": False, "preferences": False, "agent_rules": True, "entities": False},
        "代码输出格式"),
    (67, "C", "所有涉及药品的信息要附上循证等级",
        {"profile": False, "preferences": False, "agent_rules": True, "entities": False},
        "医学输出要求"),
    (68, "C", "引用法条时要标注完整条款号",
        {"profile": False, "preferences": False, "agent_rules": True, "entities": False},
        "法律引用格式"),
    (69, "C", "财务分析里数字默认保留两位小数",
        {"profile": False, "preferences": False, "agent_rules": True, "entities": False},
        "数字精度"),
    (70, "C", "输出分析前先说明数据来源和时间范围",
        {"profile": False, "preferences": False, "agent_rules": True, "entities": False},
        "前置说明规则"),

    # —— 沟通风格 ——
    (71, "C", "回复客户的邮件一律英文，措辞要正式",
        {"profile": False, "preferences": False, "agent_rules": True, "entities": False},
        "语言+风格规则"),
    (72, "C", "跟研发同事交流可以随意点，用术语没关系",
        {"profile": False, "preferences": False, "agent_rules": True, "entities": False},
        "场景化风格"),
    (73, "C", "面向高管的材料要强调结论和ROI",
        {"profile": False, "preferences": False, "agent_rules": True, "entities": False},
        "受众适配"),

    # —— 工作流程 ——
    (74, "C", "每次写代码先给出伪代码，确认后再实现",
        {"profile": False, "preferences": False, "agent_rules": True, "entities": False},
        "研发流程"),
    (75, "C", "诊断建议前必须先列出鉴别诊断",
        {"profile": False, "preferences": False, "agent_rules": True, "entities": False},
        "医疗流程"),
    (76, "C", "给我的投资建议要包含下行风险评估",
        {"profile": False, "preferences": False, "agent_rules": True, "entities": False},
        "投资决策流程"),
    (77, "C", "每次改配置前先备份，并说明回滚步骤",
        {"profile": False, "preferences": False, "agent_rules": True, "entities": False},
        "运维操作流程"),

    # —— 禁止 ——
    (78, "C", "不要给出未经审核的医学建议",
        {"profile": False, "preferences": False, "agent_rules": True, "entities": False},
        "医疗安全禁令"),
    (79, "C", "代码生成时不要使用已弃用的API",
        {"profile": False, "preferences": False, "agent_rules": True, "entities": False},
        "代码禁令"),
    (80, "C", "禁止在未脱敏的情况下展示客户姓名",
        {"profile": False, "preferences": False, "agent_rules": True, "entities": False},
        "隐私禁令"),
    (81, "C", "合同里不能出现绝对化承诺",
        {"profile": False, "preferences": False, "agent_rules": True, "entities": False},
        "法律合规禁令"),

    # —— 更新/撤销 ——
    (82, "C", "之前让你输出 markdown，现在改成 HTML",
        {"profile": False, "preferences": False, "agent_rules": True, "entities": False},
        "格式切换"),
    (83, "C", "昨天的规则作废，重新按新版执行",
        {"profile": False, "preferences": False, "agent_rules": True, "entities": False},
        "批量撤销"),
    (84, "C", "取消前面关于字数限制的要求",
        {"profile": False, "preferences": False, "agent_rules": True, "entities": False},
        "精确撤销"),

    # —— 专业领域 ——
    (85, "C", "你要重点学习港美股的交易规则",
        {"profile": False, "preferences": False, "agent_rules": True, "entities": False},
        "领域聚焦"),
    (86, "C", "以后所有SQL都按PostgreSQL语法生成",
        {"profile": False, "preferences": False, "agent_rules": True, "entities": False},
        "技术栈约束"),

    # —— 隐性规则（反馈式）——
    (87, "C", "上次给的方案太理论了，以后要结合实际案例",
        {"profile": False, "preferences": False, "agent_rules": True, "entities": False},
        "反馈驱动规则"),
    (88, "C", "今天的回答有点绕，以后直接点",
        {"profile": False, "preferences": False, "agent_rules": True, "entities": False},
        "风格调整指令"),

    # —— 多规则合并 ——
    (89, "C", "技术文档用markdown，商务邮件用富文本",
        {"profile": False, "preferences": False, "agent_rules": True, "entities": False},
        "场景化输出规则"),
    (90, "C", "涉及客户数据时先脱敏再展示，默认隐藏手机号",
        {"profile": False, "preferences": False, "agent_rules": True, "entities": False},
        "复合安全规则"),

    # ══════════════════════════════════════════════════════
    # D. Entities 正例（91-125）多类型第三方
    # ══════════════════════════════════════════════════════

    # —— 客户公司属性 ——
    (91, "D", "字节跳动最近在自研推理框架，跟我们有合作机会",
        {"profile": False, "preferences": False, "agent_rules": False, "entities": True},
        "客户技术动态"),
    (92, "D", "招商银行总行的审批要过风控委员会",
        {"profile": False, "preferences": False, "agent_rules": False, "entities": True},
        "客户流程"),
    (93, "D", "小米生态链企业的采购都走集采平台",
        {"profile": False, "preferences": False, "agent_rules": False, "entities": True},
        "采购模式"),
    (94, "D", "万科集团的数字化预算今年压缩了30%",
        {"profile": False, "preferences": False, "agent_rules": False, "entities": True},
        "客户预算变化"),

    # —— 人物关系 ——
    (95, "D", "平安的周总和陈总是大学同学",
        {"profile": False, "preferences": False, "agent_rules": False, "entities": True},
        "客户内部私人关系"),
    (96, "D", "美团王兴对技术预算的决策权比较集中",
        {"profile": False, "preferences": False, "agent_rules": False, "entities": True},
        "决策集中度"),
    (97, "D", "蚂蚁的技术VP最近从阿里云调过去的",
        {"profile": False, "preferences": False, "agent_rules": False, "entities": True},
        "人员流动"),

    # —— 指代 ——
    (98, "D", "那个客户的法务部门特别强硬，改合同改了八轮",
        {"profile": False, "preferences": False, "agent_rules": False, "entities": True},
        "指代+流程描述"),
    (99, "D", "他们上个月换了CTO，现在路线图都要重定",
        {"profile": False, "preferences": False, "agent_rules": False, "entities": True},
        "他们指代+组织变动"),
    (100, "D", "这家券商的风控要求特别严，日志至少留三年",
        {"profile": False, "preferences": False, "agent_rules": False, "entities": True},
        "这家+合规要求"),

    # —— 竞品情报 ——
    (101, "D", "Salesforce 最近把 Agentforce 铺到大中华区了",
        {"profile": False, "preferences": False, "agent_rules": False, "entities": True},
        "国际竞品动态"),
    (102, "D", "纷享销客在中腰部市场打得很凶，价格比我们低一半",
        {"profile": False, "preferences": False, "agent_rules": False, "entities": True},
        "竞品价格策略"),
    (103, "D", "微盟和有赞的产品差异越来越小",
        {"profile": False, "preferences": False, "agent_rules": False, "entities": True},
        "竞品同质化"),

    # —— 时效性信息 ——
    (104, "D", "招行陈总下周去欧洲出差两周",
        {"profile": False, "preferences": False, "agent_rules": False, "entities": True},
        "联系窗口"),
    (105, "D", "京东双十一前三周不接新POC",
        {"profile": False, "preferences": False, "agent_rules": False, "entities": True},
        "时间节点约束"),
    (106, "D", "华为年底要做大架构调整，新项目先别推",
        {"profile": False, "preferences": False, "agent_rules": False, "entities": True},
        "组织周期"),

    # —— 口头承诺/私下消息 ——
    (107, "D", "vivo张总私下说这次PK他会投我们一票",
        {"profile": False, "preferences": False, "agent_rules": False, "entities": True},
        "私下承诺"),
    (108, "D", "小鹏采购侧面透露预算基本定了给我们",
        {"profile": False, "preferences": False, "agent_rules": False, "entities": True},
        "侧面消息"),

    # —— 竞争/评估态势 ——
    (109, "D", "网易在同时跟我们和用友谈，重点看集成能力",
        {"profile": False, "preferences": False, "agent_rules": False, "entities": True},
        "多方评估"),
    (110, "D", "顺丰对价格不敏感，更在意SLA",
        {"profile": False, "preferences": False, "agent_rules": False, "entities": True},
        "采购偏好"),

    # —— 人物评价/风格 ——
    (111, "D", "理想汽车的技术总监特别细节控，每个指标都问",
        {"profile": False, "preferences": False, "agent_rules": False, "entities": True},
        "人物风格"),
    (112, "D", "宁德时代的王总不太爱开会，更喜欢书面沟通",
        {"profile": False, "preferences": False, "agent_rules": False, "entities": True},
        "第三方沟通偏好"),
    (113, "D", "腾讯的Mike脾气比较急，沟通要直接",
        {"profile": False, "preferences": False, "agent_rules": False, "entities": True},
        "人物性格"),

    # —— 内部矛盾/分歧 ——
    (114, "D", "比亚迪的IT和业务部门这两年互相拆台",
        {"profile": False, "preferences": False, "agent_rules": False, "entities": True},
        "部门矛盾"),
    (115, "D", "海尔集团和海尔智家在技术选型上走的是两条线",
        {"profile": False, "preferences": False, "agent_rules": False, "entities": True},
        "关联公司分歧"),

    # —— 行业层面 ——
    (116, "D", "今年银行业对国产替代的推进特别激进",
        {"profile": False, "preferences": False, "agent_rules": False, "entities": True},
        "行业趋势（第三方层面）"),
    (117, "D", "新能源整车厂普遍在压供应商账期",
        {"profile": False, "preferences": False, "agent_rules": False, "entities": True},
        "行业普遍现象"),

    # —— 具体项目动态 ——
    (118, "D", "光大银行的数字化转型项目延期到Q3",
        {"profile": False, "preferences": False, "agent_rules": False, "entities": True},
        "项目节奏变化"),
    (119, "D", "长城汽车的数字孪生POC已经进入复盘阶段",
        {"profile": False, "preferences": False, "agent_rules": False, "entities": True},
        "项目阶段"),

    # —— 第三方反馈 ——
    (120, "D", "客户反馈我们的文档写得比竞品清楚",
        {"profile": False, "preferences": False, "agent_rules": False, "entities": True},
        "客户对我方评价"),
    (121, "D", "好几个头部客户都提到希望支持私有化部署",
        {"profile": False, "preferences": False, "agent_rules": False, "entities": True},
        "集体诉求"),

    # —— 历史交易/关系 ——
    (122, "D", "红杉和高瓴去年都参与了他们的C轮",
        {"profile": False, "preferences": False, "agent_rules": False, "entities": True},
        "投资方背景"),
    (123, "D", "我们和浦发合作了5年，对方KA团队比较稳定",
        {"profile": False, "preferences": False, "agent_rules": False, "entities": True},
        "合作关系史"),

    # —— 决策链 ——
    (124, "D", "三一重工这种大集团最终拍板的是董事长办公会",
        {"profile": False, "preferences": False, "agent_rules": False, "entities": True},
        "高层决策机制"),
    (125, "D", "瑞幸的采购决策流程很短，总监级就能签",
        {"profile": False, "preferences": False, "agent_rules": False, "entities": True},
        "决策链长度"),

    # ══════════════════════════════════════════════════════
    # E. 不提取场景（126-160）
    # ══════════════════════════════════════════════════════

    # —— 纯操作指令 ——
    (126, "E", "帮我把今天的工单按SLA排个序",
        {"profile": False, "preferences": False, "agent_rules": False, "entities": False},
        "排序操作"),
    (127, "E", "把这段代码重构成函数式风格",
        {"profile": False, "preferences": False, "agent_rules": False, "entities": False},
        "代码改写"),
    (128, "E", "帮我翻译一下这段话",
        {"profile": False, "preferences": False, "agent_rules": False, "entities": False},
        "翻译请求"),
    (129, "E", "查一下昨天的告警日志",
        {"profile": False, "preferences": False, "agent_rules": False, "entities": False},
        "日志查询"),
    (130, "E", "把这个文档导出PDF",
        {"profile": False, "preferences": False, "agent_rules": False, "entities": False},
        "导出操作"),
    (131, "E", "给这张图加个水印",
        {"profile": False, "preferences": False, "agent_rules": False, "entities": False},
        "图片处理"),
    (132, "E", "帮我总结这本书的主要观点",
        {"profile": False, "preferences": False, "agent_rules": False, "entities": False},
        "总结请求"),

    # —— 确认/寒暄 ——
    (133, "E", "明白了，这样可以",
        {"profile": False, "preferences": False, "agent_rules": False, "entities": False},
        "确认"),
    (134, "E", "辛苦了",
        {"profile": False, "preferences": False, "agent_rules": False, "entities": False},
        "感谢"),
    (135, "E", "晚上好",
        {"profile": False, "preferences": False, "agent_rules": False, "entities": False},
        "问候"),
    (136, "E", "哦对",
        {"profile": False, "preferences": False, "agent_rules": False, "entities": False},
        "附和"),
    (137, "E", "Ok Got it",
        {"profile": False, "preferences": False, "agent_rules": False, "entities": False},
        "英文确认"),

    # —— 纯查询 ——
    (138, "E", "Python里的生成器和迭代器有什么区别",
        {"profile": False, "preferences": False, "agent_rules": False, "entities": False},
        "知识问答"),
    (139, "E", "A股和港股的交易时间分别是什么",
        {"profile": False, "preferences": False, "agent_rules": False, "entities": False},
        "事实问答"),
    (140, "E", "糖尿病的诊断标准是什么",
        {"profile": False, "preferences": False, "agent_rules": False, "entities": False},
        "医学问答"),
    (141, "E", "JWT和Session的核心区别",
        {"profile": False, "preferences": False, "agent_rules": False, "entities": False},
        "技术问答"),
    (142, "E", "最近有什么好看的纪录片推荐",
        {"profile": False, "preferences": False, "agent_rules": False, "entities": False},
        "生活问答"),

    # —— 评价/感叹 ——
    (143, "E", "哇这个回答不错",
        {"profile": False, "preferences": False, "agent_rules": False, "entities": False},
        "感叹评价"),
    (144, "E", "这个思路挺有意思的",
        {"profile": False, "preferences": False, "agent_rules": False, "entities": False},
        "评价"),
    (145, "E", "你真聪明",
        {"profile": False, "preferences": False, "agent_rules": False, "entities": False},
        "夸奖"),
    (146, "E", "有点意思",
        {"profile": False, "preferences": False, "agent_rules": False, "entities": False},
        "简短评价"),

    # —— 一次性请求 ——
    (147, "E", "这次帮我列得详细一点",
        {"profile": False, "preferences": False, "agent_rules": False, "entities": False},
        "这次=一次性"),
    (148, "E", "刚才那段代码再讲讲",
        {"profile": False, "preferences": False, "agent_rules": False, "entities": False},
        "刚才=一次性"),
    (149, "E", "等会儿我们再回到这个话题",
        {"profile": False, "preferences": False, "agent_rules": False, "entities": False},
        "延后讨论"),

    # —— 数据/计算类请求 ——
    (150, "E", "算一下80的15%是多少",
        {"profile": False, "preferences": False, "agent_rules": False, "entities": False},
        "计算请求"),
    (151, "E", "帮我把华氏度转摄氏度",
        {"profile": False, "preferences": False, "agent_rules": False, "entities": False},
        "单位换算"),

    # —— 思考/停顿 ——
    (152, "E", "嗯让我想想",
        {"profile": False, "preferences": False, "agent_rules": False, "entities": False},
        "思考中"),
    (153, "E", "稍等，我查下资料",
        {"profile": False, "preferences": False, "agent_rules": False, "entities": False},
        "暂停"),
    (154, "E", "先这样吧",
        {"profile": False, "preferences": False, "agent_rules": False, "entities": False},
        "中止"),

    # —— 纯假设/虚拟 ——
    (155, "E", "假如用户量涨10倍，架构要怎么改",
        {"profile": False, "preferences": False, "agent_rules": False, "entities": False},
        "假设问答"),
    (156, "E", "如果我是投资人你会怎么评估这个项目",
        {"profile": False, "preferences": False, "agent_rules": False, "entities": False},
        "角色扮演问答"),

    # —— 纯系统数据复述 ——
    (157, "E", "确认下订单号ORD20251107001",
        {"profile": False, "preferences": False, "agent_rules": False, "entities": False},
        "订单号查询"),
    (158, "E", "这个手机号13812345678对应的客户是谁",
        {"profile": False, "preferences": False, "agent_rules": False, "entities": False},
        "纯字段查询"),

    # —— 含第三方但只是指令 ——
    (159, "E", "把华为这个客户的资料打包给我",
        {"profile": False, "preferences": False, "agent_rules": False, "entities": False},
        "含实体的操作指令"),
    (160, "E", "帮我给小米的联系人发个拜年短信",
        {"profile": False, "preferences": False, "agent_rules": False, "entities": False},
        "含实体的操作指令2"),

    # ══════════════════════════════════════════════════════
    # F. 混合意图场景（161-185）
    # ══════════════════════════════════════════════════════

    (161, "F", "我是做私募的，你以后重点跟踪港股科技板块",
        {"profile": True, "preferences": False, "agent_rules": True, "entities": False},
        "身份+领域指令"),
    (162, "F", "我习惯看周报，你每周一早上给我汇总",
        {"profile": False, "preferences": True, "agent_rules": True, "entities": False},
        "习惯+定时任务"),
    (163, "F", "我是华为的合作伙伴，接下来重点盯这个客户",
        {"profile": True, "preferences": False, "agent_rules": True, "entities": True},
        "身份+客户+指令三维"),
    (164, "F", "我们团队实行OKR，你以后汇总都按O和KR拆分",
        {"profile": True, "preferences": False, "agent_rules": True, "entities": False},
        "组织机制+格式指令"),
    (165, "F", "Stripe那边要求我们用他们的API规范，以后对接全部按这套来",
        {"profile": False, "preferences": False, "agent_rules": True, "entities": True},
        "第三方要求+对应指令"),
    (166, "F", "我是产品经理负责CRM模块，你帮我盯三个竞品：纷享、销售易、红圈",
        {"profile": True, "preferences": False, "agent_rules": True, "entities": True},
        "身份+竞品+指令"),
    (167, "F", "我不太喜欢长文，报告控制在500字内",
        {"profile": False, "preferences": True, "agent_rules": True, "entities": False},
        "偏好+规则"),
    (168, "F", "字节那个项目周总是负责人，以后相关分析都对标给他",
        {"profile": False, "preferences": False, "agent_rules": True, "entities": True},
        "第三方+指令关联"),
    (169, "F", "我是医生，你给的医学信息要标注循证等级",
        {"profile": True, "preferences": False, "agent_rules": True, "entities": False},
        "身份+输出要求"),
    (170, "F", "开会我习惯开摄像头，你帮我准备的资料要有讲稿",
        {"profile": False, "preferences": True, "agent_rules": True, "entities": False},
        "习惯+材料要求"),
    (171, "F", "我在研发团队，你以后生成的代码用 PEP8 规范",
        {"profile": True, "preferences": False, "agent_rules": True, "entities": False},
        "身份+代码规范"),
    (172, "F", "招行和平安是我的两个重点客户，我负责华东区的金融行业",
        {"profile": True, "preferences": False, "agent_rules": False, "entities": True},
        "职责+客户列表"),
    (173, "F", "我在香港办公，输出默认用繁体，金额用港币",
        {"profile": True, "preferences": False, "agent_rules": True, "entities": False},
        "地域+输出规则"),
    (174, "F", "我一般晚上处理文档，你发给我的邮件主题加【夜间】标签",
        {"profile": False, "preferences": True, "agent_rules": True, "entities": False},
        "习惯+邮件格式"),
    (175, "F", "我们公司主攻东南亚市场，你熟悉一下当地合规要求",
        {"profile": True, "preferences": False, "agent_rules": True, "entities": False},
        "公司市场+领域指令"),
    (176, "F", "我更喜欢口头汇报，书面的就简写要点即可",
        {"profile": False, "preferences": True, "agent_rules": True, "entities": False},
        "偏好+书面要求"),
    (177, "F", "宁德时代的王总不开会，你准备材料时多准备一份书面稿",
        {"profile": False, "preferences": False, "agent_rules": True, "entities": True},
        "第三方特征+适配指令"),
    (178, "F", "我们部门是扁平化管理，你给建议时不用区分上下级语气",
        {"profile": True, "preferences": False, "agent_rules": True, "entities": False},
        "组织文化+输出风格"),
    (179, "F", "我是新来的运维，你帮我熟悉一下现有监控体系",
        {"profile": True, "preferences": False, "agent_rules": False, "entities": False},
        "身份+一次性任务（非持久指令）"),
    (180, "F", "我不喜欢复杂的图，你画的架构图尽量简单",
        {"profile": False, "preferences": True, "agent_rules": True, "entities": False},
        "偏好+绘图规则"),
    (181, "F", "网易那个项目的决策人是Mike，以后这个项目的分析抄送给他",
        {"profile": False, "preferences": False, "agent_rules": True, "entities": True},
        "第三方角色+分发规则"),
    (182, "F", "我的KPI是续费率，你分析客户时优先看续费相关指标",
        {"profile": True, "preferences": False, "agent_rules": True, "entities": False},
        "KPI+分析重点"),
    (183, "F", "我是法务，你起草的合同要避开排他性条款",
        {"profile": True, "preferences": False, "agent_rules": True, "entities": False},
        "身份+合同规则"),
    (184, "F", "我对客户响应速度要求特别高，你优先处理客户相关消息",
        {"profile": False, "preferences": True, "agent_rules": True, "entities": False},
        "偏好+优先级规则"),
    (185, "F", "我带的两个实习生刚毕业，你给他们的建议要更基础一些",
        {"profile": True, "preferences": False, "agent_rules": True, "entities": False},
        "团队情况+受众适配"),

    # ══════════════════════════════════════════════════════
    # G. 边界对抗场景（186-200）深度微妙歧义
    # ══════════════════════════════════════════════════════

    (186, "G", "我的工作节奏一般是上午开会下午写代码",
        {"profile": False, "preferences": True, "agent_rules": False, "entities": False},
        "工作节奏=习惯偏好（非身份）[pref vs profile]"),
    (187, "G", "我的岗位要求是管理10人团队",
        {"profile": True, "preferences": False, "agent_rules": False, "entities": False},
        "岗位要求=画像（非偏好）[profile vs pref]"),
    (188, "G", "以后别叫我老师，直接叫名字就行",
        {"profile": False, "preferences": False, "agent_rules": True, "entities": False},
        "称呼指令=rules [rules vs pref]"),
    (189, "G", "我不喜欢别人叫我老师",
        {"profile": False, "preferences": True, "agent_rules": False, "entities": False},
        "称呼偏好 [rules vs pref]"),
    (190, "G", "客户那边要求用英文沟通",
        {"profile": False, "preferences": False, "agent_rules": False, "entities": True},
        "第三方要求=entities [entities vs rules]"),
    (191, "G", "跟客户沟通默认用英文",
        {"profile": False, "preferences": False, "agent_rules": True, "entities": False},
        "对Agent的默认规则 [entities vs rules]"),
    (192, "G", "我司规定周五不安排客户拜访",
        {"profile": True, "preferences": False, "agent_rules": False, "entities": False},
        "公司制度=画像 [profile vs rules]"),
    (193, "G", "你以后周五别安排客户拜访相关的任务",
        {"profile": False, "preferences": False, "agent_rules": True, "entities": False},
        "给Agent的约束 [profile vs rules]"),
    (194, "G", "我们家客户70%是制造业",
        {"profile": True, "preferences": False, "agent_rules": False, "entities": False},
        "用户方客户结构 [profile vs entities]"),
    (195, "G", "他们家客户70%是制造业",
        {"profile": False, "preferences": False, "agent_rules": False, "entities": True},
        "第三方客户结构 [profile vs entities]"),
    (196, "G", "张总说他喜欢图表",
        {"profile": False, "preferences": False, "agent_rules": False, "entities": True},
        "第三方偏好=entities [entities vs pref]"),
    (197, "G", "跟张总汇报的时候多用图表",
        {"profile": False, "preferences": False, "agent_rules": True, "entities": False},
        "针对第三方的输出规则 [entities vs rules]"),
    (198, "G", "这次和以后你都按这个格式输出",
        {"profile": False, "preferences": False, "agent_rules": True, "entities": False},
        "'以后'才是关键 [rules vs 不提取]"),
    (199, "G", "这次按这个格式输出就行",
        {"profile": False, "preferences": False, "agent_rules": False, "entities": False},
        "'这次'=一次性 [rules vs 不提取]"),
    (200, "G", "我公司英文名叫 Stripe Labs",
        {"profile": True, "preferences": False, "agent_rules": False, "entities": False},
        "公司别名=画像 [profile vs entities]"),
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
    result = await llm.ainvoke(prompt)
    return result.content


async def run_one_case(case_tuple, llm) -> dict:
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
            resp_short = r["response"].replace("\n", " ")[:150]
            print(f"      响应: {resp_short}")


def print_summary(all_results: list):
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
        "A": "Profile 正例（多行业身份/组织特征/履历）",
        "B": "Preferences 正例（多维度偏好/口语化）",
        "C": "Agent Rules 正例（多领域指令）",
        "D": "Entities 正例（多类型第三方）",
        "E": "不提取场景（过度提取抑制）",
        "F": "混合意图场景（多维度提取）",
        "G": "边界对抗场景（深度微妙歧义）",
    }

    print("\n" + "=" * 70)
    print("  分组汇总 (200 扩展集)")
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

    total_cases = sum(s.total_cases for s in groups.values())
    pass_cases = sum(s.pass_cases for s in groups.values())
    total_dims = sum(s.total_dims for s in groups.values())
    pass_dims = sum(s.pass_dims for s in groups.values())
    print(f"  {'─' * 66}")
    print(f"  {'总':<4} {'':<40} "
          f"{pass_cases}/{total_cases} ({pass_cases/total_cases*100:.0f}%)   "
          f"{pass_dims}/{total_dims} ({pass_dims/total_dims*100:.0f}%)")

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

    print("\n" + "=" * 70)
    print("  过拟合风险评估")
    print("=" * 70)
    a_e_total = sum(groups.get(g, GroupStat()).total_cases for g in "ABCDE")
    a_e_pass = sum(groups.get(g, GroupStat()).pass_cases for g in "ABCDE")
    fg_total = sum(groups.get(g, GroupStat()).total_cases for g in "FG")
    fg_pass = sum(groups.get(g, GroupStat()).pass_cases for g in "FG")
    a_e_pct = a_e_pass / max(1, a_e_total) * 100
    fg_pct = fg_pass / max(1, fg_total) * 100
    gap = a_e_pct - fg_pct
    print(f"  标准场景 (A-E) 通过率:  {a_e_pct:.0f}%  ({a_e_pass}/{a_e_total})")
    print(f"  对抗场景 (F-G) 通过率:  {fg_pct:.0f}%  ({fg_pass}/{fg_total})")
    print(f"  泛化差距 (A-E 减 F-G):  {gap:.0f}%")
    if gap > 20:
        print("  ⚠️  过拟合风险高")
    elif gap > 10:
        print("  ⚠️  存在一定过拟合")
    else:
        print("  ✅ 泛化能力良好")


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--group", type=str, default="", help="只跑某组：A/B/C/D/E/F/G")
    parser.add_argument("--start", type=int, default=1, help="起始用例 id")
    parser.add_argument("--end", type=int, default=200, help="结束用例 id")
    parser.add_argument("--concurrency", type=int, default=8, help="并发度")
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

    selected = [
        c for c in CASES
        if args.start <= c[0] <= args.end
        and (not args.group or c[1] == args.group.upper())
    ]

    print("=" * 70)
    print(f"  四路提示词过拟合验证【扩展200集】— 运行 {len(selected)} 个用例")
    print(f"  模型: {args.model}   并发: {args.concurrency}")
    print("=" * 70)

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
        if i % 20 == 0:
            print(f"\n  ... 进度: {i}/{len(selected)}")

    all_results.sort(key=lambda r: r["id"])
    print_summary(all_results)

    failed = sum(1 for r in all_results if not r["all_pass"])
    return failed


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
