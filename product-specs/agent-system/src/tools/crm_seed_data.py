"""
CRM 种子数据 — 11 个客户 + 完整关联数据

数据关系：
- 11 个客户（跨行业：通信、互联网、制造、金融、零售、医疗）
- 每个客户 2-3 个联系人（共 28 个）
- 每个客户 1-3 个商机（共 22 个，覆盖所有阶段）
- 每个客户 1-3 个活动（共 22 个，覆盖所有类型）
- 10 个线索（独立于客户，部分已转化）

负责人分配：
- user_zhang（张明）：华东区销售总监，负责通信+互联网
- user_li（李强）：华南区销售经理，负责制造+金融
- user_wang（王芳）：华北区销售经理，负责零售+医疗
"""
from __future__ import annotations


def build_seed_data() -> dict[str, list[dict]]:
    """构建完整的 CRM 种子数据（10 客户 + 全量关联）"""

    data: dict[str, list[dict]] = {}

    # ═══════════════════════════════════════════════════════════
    # 客户（10 个）
    # ═══════════════════════════════════════════════════════════
    data["account"] = [
        {"id": "acc_001", "name": "华为技术有限公司", "industry": "通信设备", "city": "深圳",
         "employeeCount": 207000, "annualRevenue": 880900, "website": "huawei.com",
         "rating": 95, "activeFlg": 1, "ownerName": "张明", "createdAt": "2024-06-15 10:00:00", "updatedAt": "2025-04-20 09:00:00"},
        {"id": "acc_002", "name": "腾讯控股有限公司", "industry": "互联网", "city": "深圳",
         "employeeCount": 108000, "annualRevenue": 609000, "website": "tencent.com",
         "rating": 92, "activeFlg": 1, "ownerName": "张明", "createdAt": "2024-07-01 09:00:00", "updatedAt": "2025-04-18 14:00:00"},
        {"id": "acc_003", "name": "比亚迪股份有限公司", "industry": "制造业", "city": "深圳",
         "employeeCount": 290000, "annualRevenue": 602000, "website": "byd.com",
         "rating": 88, "activeFlg": 1, "ownerName": "李强", "createdAt": "2024-08-10 11:00:00", "updatedAt": "2025-04-15 10:00:00"},
        {"id": "acc_004", "name": "招商银行股份有限公司", "industry": "金融", "city": "深圳",
         "employeeCount": 110000, "annualRevenue": 340000, "website": "cmbchina.com",
         "rating": 90, "activeFlg": 1, "ownerName": "李强", "createdAt": "2024-05-20 08:00:00", "updatedAt": "2025-04-19 16:00:00"},
        {"id": "acc_005", "name": "阿里巴巴集团", "industry": "互联网", "city": "杭州",
         "employeeCount": 220000, "annualRevenue": 869000, "website": "alibaba.com",
         "rating": 93, "activeFlg": 1, "ownerName": "张明", "createdAt": "2024-09-01 10:00:00", "updatedAt": "2025-04-12 11:00:00"},
        {"id": "acc_006", "name": "中国平安保险集团", "industry": "金融", "city": "深圳",
         "employeeCount": 180000, "annualRevenue": 1218000, "website": "pingan.com",
         "rating": 91, "activeFlg": 1, "ownerName": "李强", "createdAt": "2024-04-15 09:00:00", "updatedAt": "2025-04-10 15:00:00"},
        {"id": "acc_007", "name": "京东集团", "industry": "零售", "city": "北京",
         "employeeCount": 390000, "annualRevenue": 1084000, "website": "jd.com",
         "rating": 85, "activeFlg": 1, "ownerName": "王芳", "createdAt": "2024-10-05 14:00:00", "updatedAt": "2025-03-28 09:00:00"},
        {"id": "acc_008", "name": "药明康德", "industry": "医疗", "city": "上海",
         "employeeCount": 44000, "annualRevenue": 403000, "website": "wuxiapptec.com",
         "rating": 82, "activeFlg": 1, "ownerName": "王芳", "createdAt": "2025-01-10 10:00:00", "updatedAt": "2025-04-08 11:00:00"},
        {"id": "acc_009", "name": "宁德时代", "industry": "制造业", "city": "宁德",
         "employeeCount": 120000, "annualRevenue": 402000, "website": "catl.com",
         "rating": 87, "activeFlg": 1, "ownerName": "李强", "createdAt": "2024-11-20 09:00:00", "updatedAt": "2025-04-05 14:00:00"},
        {"id": "acc_010", "name": "万科企业股份有限公司", "industry": "零售", "city": "深圳",
         "employeeCount": 45000, "annualRevenue": 460000, "website": "vanke.com",
         "rating": 65, "activeFlg": 0, "ownerName": "王芳", "createdAt": "2024-03-01 10:00:00", "updatedAt": "2024-12-15 09:00:00"},
        {"id": "acc_011", "name": "华为股份有限公司", "industry": "通信设备", "city": "东莞",
         "employeeCount": 195000, "annualRevenue": 720000, "website": "huawei-shares.com",
         "rating": 89, "activeFlg": 1, "ownerName": "张明", "createdAt": "2025-01-08 09:00:00", "updatedAt": "2025-05-10 14:00:00"},
    ]

    # ═══════════════════════════════════════════════════════════
    # 联系人（25 个，每客户 2-3 个）
    # ═══════════════════════════════════════════════════════════
    data["contact"] = [
        # 华为（3人）
        {"id": "con_001", "name": "张伟", "title": "IT总监", "phone": "13800001111", "email": "zhangwei@huawei.com",
         "accountId": "acc_001", "isPrimary": 1, "createdAt": "2024-06-20 09:00:00"},
        {"id": "con_002", "name": "李娜", "title": "采购经理", "phone": "13800002222", "email": "lina@huawei.com",
         "accountId": "acc_001", "isPrimary": 0, "createdAt": "2024-07-10 14:00:00"},
        {"id": "con_003", "name": "刘峰", "title": "项目经理", "phone": "13800003333", "email": "liufeng@huawei.com",
         "accountId": "acc_001", "isPrimary": 0, "createdAt": "2024-09-05 10:00:00"},
        # 腾讯（2人）
        {"id": "con_004", "name": "王强", "title": "CTO", "phone": "13900003333", "email": "wangqiang@tencent.com",
         "accountId": "acc_002", "isPrimary": 1, "createdAt": "2024-07-15 11:00:00"},
        {"id": "con_005", "name": "陈静", "title": "技术总监", "phone": "13900004444", "email": "chenjing@tencent.com",
         "accountId": "acc_002", "isPrimary": 0, "createdAt": "2024-08-20 09:00:00"},
        # 比亚迪（3人）
        {"id": "con_006", "name": "赵敏", "title": "数字化负责人", "phone": "13700004444", "email": "zhaomin@byd.com",
         "accountId": "acc_003", "isPrimary": 1, "createdAt": "2024-08-15 10:00:00"},
        {"id": "con_007", "name": "孙磊", "title": "生产部长", "phone": "13700005555", "email": "sunlei@byd.com",
         "accountId": "acc_003", "isPrimary": 0, "createdAt": "2024-09-10 14:00:00"},
        {"id": "con_008", "name": "周洁", "title": "IT经理", "phone": "13700006666", "email": "zhoujie@byd.com",
         "accountId": "acc_003", "isPrimary": 0, "createdAt": "2025-01-05 09:00:00"},
        # 招行（2人）
        {"id": "con_009", "name": "陈刚", "title": "信息部主管", "phone": "13600005555", "email": "chengang@cmb.com",
         "accountId": "acc_004", "isPrimary": 1, "createdAt": "2024-06-01 15:00:00"},
        {"id": "con_010", "name": "黄丽", "title": "风控总监", "phone": "13600006666", "email": "huangli@cmb.com",
         "accountId": "acc_004", "isPrimary": 0, "createdAt": "2024-10-15 10:00:00"},
        # 阿里（3人）
        {"id": "con_011", "name": "马超", "title": "VP技术", "phone": "15100001111", "email": "machao@alibaba.com",
         "accountId": "acc_005", "isPrimary": 1, "createdAt": "2024-09-10 09:00:00"},
        {"id": "con_012", "name": "林燕", "title": "采购总监", "phone": "15100002222", "email": "linyan@alibaba.com",
         "accountId": "acc_005", "isPrimary": 0, "createdAt": "2024-10-20 14:00:00"},
        {"id": "con_013", "name": "何涛", "title": "架构师", "phone": "15100003333", "email": "hetao@alibaba.com",
         "accountId": "acc_005", "isPrimary": 0, "createdAt": "2025-01-15 11:00:00"},
        # 平安（2人）
        {"id": "con_014", "name": "吴刚", "title": "科技部总经理", "phone": "13500001111", "email": "wugang@pingan.com",
         "accountId": "acc_006", "isPrimary": 1, "createdAt": "2024-05-01 09:00:00"},
        {"id": "con_015", "name": "郑芳", "title": "数据中心主任", "phone": "13500002222", "email": "zhengfang@pingan.com",
         "accountId": "acc_006", "isPrimary": 0, "createdAt": "2024-08-10 10:00:00"},
        # 京东（3人）
        {"id": "con_016", "name": "徐明", "title": "供应链VP", "phone": "13200001111", "email": "xuming@jd.com",
         "accountId": "acc_007", "isPrimary": 1, "createdAt": "2024-10-10 14:00:00"},
        {"id": "con_017", "name": "杨帆", "title": "技术经理", "phone": "13200002222", "email": "yangfan@jd.com",
         "accountId": "acc_007", "isPrimary": 0, "createdAt": "2024-11-05 09:00:00"},
        {"id": "con_018", "name": "罗琳", "title": "采购专员", "phone": "13200003333", "email": "luolin@jd.com",
         "accountId": "acc_007", "isPrimary": 0, "createdAt": "2025-02-10 10:00:00"},
        # 药明康德（2人）
        {"id": "con_019", "name": "谢军", "title": "信息化总监", "phone": "15800001111", "email": "xiejun@wuxiapptec.com",
         "accountId": "acc_008", "isPrimary": 1, "createdAt": "2025-01-15 09:00:00"},
        {"id": "con_020", "name": "韩雪", "title": "研发部经理", "phone": "15800002222", "email": "hanxue@wuxiapptec.com",
         "accountId": "acc_008", "isPrimary": 0, "createdAt": "2025-02-20 14:00:00"},
        # 宁德时代（2人）
        {"id": "con_021", "name": "曹阳", "title": "智能制造总监", "phone": "13100001111", "email": "caoyang@catl.com",
         "accountId": "acc_009", "isPrimary": 1, "createdAt": "2024-12-01 10:00:00"},
        {"id": "con_022", "name": "冯涛", "title": "IT部长", "phone": "13100002222", "email": "fengtao@catl.com",
         "accountId": "acc_009", "isPrimary": 0, "createdAt": "2025-01-20 09:00:00"},
        # 万科（3人）
        {"id": "con_023", "name": "蒋华", "title": "数字化总监", "phone": "13300001111", "email": "jianghua@vanke.com",
         "accountId": "acc_010", "isPrimary": 1, "createdAt": "2024-03-10 09:00:00"},
        {"id": "con_024", "name": "田静", "title": "项目经理", "phone": "13300002222", "email": "tianjing@vanke.com",
         "accountId": "acc_010", "isPrimary": 0, "createdAt": "2024-04-15 14:00:00"},
        {"id": "con_025", "name": "邓伟", "title": "采购主管", "phone": "13300003333", "email": "dengwei@vanke.com",
         "accountId": "acc_010", "isPrimary": 0, "createdAt": "2024-05-20 10:00:00"},
        # 华为股份（3人）
        {"id": "con_026", "name": "陈志远", "title": "数字化转型总监", "phone": "13400001111", "email": "chenzhiyuan@huawei-shares.com",
         "accountId": "acc_011", "isPrimary": 1, "createdAt": "2025-01-15 09:00:00"},
        {"id": "con_027", "name": "刘婷", "title": "采购部经理", "phone": "13400002222", "email": "liuting@huawei-shares.com",
         "accountId": "acc_011", "isPrimary": 0, "createdAt": "2025-02-10 14:00:00"},
        {"id": "con_028", "name": "王建国", "title": "IT架构师", "phone": "13400003333", "email": "wangjianguo@huawei-shares.com",
         "accountId": "acc_011", "isPrimary": 0, "createdAt": "2025-03-05 10:00:00"},
    ]

    # ═══════════════════════════════════════════════════════════
    # 商机（20 个，覆盖所有阶段，每客户 1-3 个）
    # ═══════════════════════════════════════════════════════════
    data["opportunity"] = [
        # 华为（4个商机）
        {"id": "opp_001", "name": "华为ERP实施", "accountId": "acc_001", "amount": 45.0,
         "stage": "proposal", "probability": 60, "closeDate": "2025-06-30", "ownerId": "user_zhang",
         "source": "inbound", "lastActivityDate": "2025-04-10", "createdAt": "2025-02-01 10:00:00"},
        {"id": "opp_002", "name": "华为CRM部署", "accountId": "acc_001", "amount": 28.0,
         "stage": "negotiation", "probability": 80, "closeDate": "2025-05-15", "ownerId": "user_zhang",
         "source": "referral", "lastActivityDate": "2025-04-18", "createdAt": "2025-01-20 09:00:00"},
        {"id": "opp_003", "name": "华为BI平台", "accountId": "acc_001", "amount": 15.0,
         "stage": "qualification", "probability": 30, "closeDate": "2025-08-01", "ownerId": "user_zhang",
         "source": "outbound", "lastActivityDate": "2025-03-25", "createdAt": "2025-03-10 14:00:00"},
        {"id": "opp_004", "name": "华为安全审计", "accountId": "acc_001", "amount": 18.0,
         "stage": "won", "probability": 100, "closeDate": "2025-04-30", "ownerId": "user_zhang",
         "source": "referral", "lastActivityDate": "2025-04-20", "createdAt": "2025-03-01 10:00:00"},
        # 腾讯（2个商机）
        {"id": "opp_005", "name": "腾讯数据中台", "accountId": "acc_002", "amount": 62.0,
         "stage": "proposal", "probability": 50, "closeDate": "2025-07-20", "ownerId": "user_zhang",
         "source": "partner", "lastActivityDate": "2025-04-15", "createdAt": "2025-02-15 11:00:00"},
        {"id": "opp_006", "name": "腾讯AI平台升级", "accountId": "acc_002", "amount": 38.0,
         "stage": "qualification", "probability": 35, "closeDate": "2025-09-01", "ownerId": "user_zhang",
         "source": "inbound", "lastActivityDate": "2025-04-02", "createdAt": "2025-03-20 09:00:00"},
        # 比亚迪（2个商机）
        {"id": "opp_007", "name": "比亚迪MES系统", "accountId": "acc_003", "amount": 85.0,
         "stage": "prospecting", "probability": 20, "closeDate": "2025-09-30", "ownerId": "user_li",
         "source": "outbound", "lastActivityDate": "2025-04-05", "createdAt": "2025-03-20 16:00:00"},
        {"id": "opp_008", "name": "比亚迪供应链优化", "accountId": "acc_003", "amount": 52.0,
         "stage": "proposal", "probability": 45, "closeDate": "2025-08-15", "ownerId": "user_li",
         "source": "referral", "lastActivityDate": "2025-04-12", "createdAt": "2025-02-28 10:00:00"},
        # 招行（2个商机）
        {"id": "opp_009", "name": "招行风控平台", "accountId": "acc_004", "amount": 120.0,
         "stage": "negotiation", "probability": 75, "closeDate": "2025-05-30", "ownerId": "user_li",
         "source": "inbound", "lastActivityDate": "2025-04-19", "createdAt": "2025-01-10 08:00:00"},
        {"id": "opp_010", "name": "招行智能客服", "accountId": "acc_004", "amount": 35.0,
         "stage": "closing", "probability": 90, "closeDate": "2025-05-10", "ownerId": "user_li",
         "source": "partner", "lastActivityDate": "2025-04-21", "createdAt": "2024-11-15 09:00:00"},
        # 阿里（2个商机）
        {"id": "opp_011", "name": "阿里云迁移咨询", "accountId": "acc_005", "amount": 30.0,
         "stage": "won", "probability": 100, "closeDate": "2025-03-15", "ownerId": "user_zhang",
         "source": "inbound", "lastActivityDate": "2025-03-15", "createdAt": "2024-12-01 10:00:00"},
        {"id": "opp_012", "name": "阿里数据治理", "accountId": "acc_005", "amount": 75.0,
         "stage": "proposal", "probability": 55, "closeDate": "2025-07-30", "ownerId": "user_zhang",
         "source": "partner", "lastActivityDate": "2025-04-16", "createdAt": "2025-02-10 14:00:00"},
        # 平安（2个商机）
        {"id": "opp_013", "name": "平安智能理赔", "accountId": "acc_006", "amount": 95.0,
         "stage": "negotiation", "probability": 70, "closeDate": "2025-06-15", "ownerId": "user_li",
         "source": "inbound", "lastActivityDate": "2025-04-18", "createdAt": "2025-01-20 09:00:00"},
        {"id": "opp_014", "name": "平安数据湖建设", "accountId": "acc_006", "amount": 150.0,
         "stage": "prospecting", "probability": 15, "closeDate": "2025-10-30", "ownerId": "user_li",
         "source": "outbound", "lastActivityDate": "2025-03-20", "createdAt": "2025-03-15 11:00:00"},
        # 京东（2个商机）
        {"id": "opp_015", "name": "京东仓储WMS升级", "accountId": "acc_007", "amount": 68.0,
         "stage": "qualification", "probability": 40, "closeDate": "2025-08-20", "ownerId": "user_wang",
         "source": "referral", "lastActivityDate": "2025-04-08", "createdAt": "2025-02-20 14:00:00"},
        {"id": "opp_016", "name": "京东配送路径优化", "accountId": "acc_007", "amount": 42.0,
         "stage": "lost", "probability": 0, "closeDate": "2025-03-01", "ownerId": "user_wang",
         "source": "outbound", "lastActivityDate": "2025-02-28", "createdAt": "2024-10-15 09:00:00"},
        # 药明康德（1个商机）
        {"id": "opp_017", "name": "药明LIMS系统", "accountId": "acc_008", "amount": 55.0,
         "stage": "proposal", "probability": 50, "closeDate": "2025-07-15", "ownerId": "user_wang",
         "source": "event", "lastActivityDate": "2025-04-10", "createdAt": "2025-02-05 10:00:00"},
        # 宁德时代（2个商机）
        {"id": "opp_018", "name": "宁德智能质检", "accountId": "acc_009", "amount": 48.0,
         "stage": "closing", "probability": 85, "closeDate": "2025-05-20", "ownerId": "user_li",
         "source": "inbound", "lastActivityDate": "2025-04-22", "createdAt": "2025-01-05 09:00:00"},
        {"id": "opp_019", "name": "宁德能源管理平台", "accountId": "acc_009", "amount": 72.0,
         "stage": "qualification", "probability": 35, "closeDate": "2025-09-15", "ownerId": "user_li",
         "source": "partner", "lastActivityDate": "2025-04-01", "createdAt": "2025-03-10 14:00:00"},
        # 万科（1个商机 — 已流失）
        {"id": "opp_020", "name": "万科智慧社区", "accountId": "acc_010", "amount": 38.0,
         "stage": "lost", "probability": 0, "closeDate": "2024-12-01", "ownerId": "user_wang",
         "source": "inbound", "lastActivityDate": "2024-11-20", "createdAt": "2024-08-01 10:00:00"},
        # 华为股份（2个商机）
        {"id": "opp_021", "name": "华为股份数字化办公平台", "accountId": "acc_011", "amount": 56.0,
         "stage": "proposal", "probability": 55, "closeDate": "2025-07-30", "ownerId": "user_zhang",
         "source": "inbound", "lastActivityDate": "2025-05-08", "createdAt": "2025-03-01 10:00:00"},
        {"id": "opp_022", "name": "华为股份智能运维系统", "accountId": "acc_011", "amount": 32.0,
         "stage": "qualification", "probability": 35, "closeDate": "2025-09-15", "ownerId": "user_zhang",
         "source": "referral", "lastActivityDate": "2025-04-28", "createdAt": "2025-04-01 09:00:00"},
    ]

    # ═══════════════════════════════════════════════════════════
    # 活动（20 个，覆盖所有类型，关联客户+商机+联系人）
    # ═══════════════════════════════════════════════════════════
    data["activity"] = [
        # 华为
        {"id": "act_001", "type": "meeting", "subject": "华为ERP需求讨论", "description": "与张伟讨论ERP实施范围和时间表",
         "accountId": "acc_001", "opportunityId": "opp_001", "contactId": "con_001",
         "dueDate": "2025-04-10", "status": "completed", "createdAt": "2025-04-08 09:00:00"},
        {"id": "act_002", "type": "call", "subject": "华为CRM报价跟进", "description": "与李娜确认CRM报价细节和折扣",
         "accountId": "acc_001", "opportunityId": "opp_002", "contactId": "con_002",
         "dueDate": "2025-04-18", "status": "completed", "createdAt": "2025-04-17 14:00:00"},
        {"id": "act_003", "type": "email", "subject": "华为BI方案初稿", "description": "发送BI平台技术方案初稿给刘峰",
         "accountId": "acc_001", "opportunityId": "opp_003", "contactId": "con_003",
         "dueDate": "2025-03-28", "status": "completed", "createdAt": "2025-03-25 10:00:00"},
        # 腾讯
        {"id": "act_004", "type": "email", "subject": "腾讯数据中台方案发送", "description": "发送技术方案给王强评审",
         "accountId": "acc_002", "opportunityId": "opp_005", "contactId": "con_004",
         "dueDate": "2025-04-15", "status": "completed", "createdAt": "2025-04-14 10:00:00"},
        {"id": "act_005", "type": "meeting", "subject": "腾讯AI平台需求调研", "description": "与陈静讨论AI平台升级需求",
         "accountId": "acc_002", "opportunityId": "opp_006", "contactId": "con_005",
         "dueDate": "2025-04-25", "status": "pending", "createdAt": "2025-04-20 09:00:00"},
        # 比亚迪
        {"id": "act_006", "type": "meeting", "subject": "比亚迪MES初步沟通", "description": "了解比亚迪生产线数字化需求和痛点",
         "accountId": "acc_003", "opportunityId": "opp_007", "contactId": "con_006",
         "dueDate": "2025-04-22", "status": "pending", "createdAt": "2025-04-20 09:00:00"},
        {"id": "act_007", "type": "task", "subject": "比亚迪供应链方案准备", "description": "准备供应链优化方案PPT",
         "accountId": "acc_003", "opportunityId": "opp_008", "contactId": "con_007",
         "dueDate": "2025-04-28", "status": "pending", "createdAt": "2025-04-15 14:00:00"},
        # 招行
        {"id": "act_008", "type": "task", "subject": "准备招行风控POC", "description": "准备POC环境和演示数据",
         "accountId": "acc_004", "opportunityId": "opp_009", "contactId": "con_009",
         "dueDate": "2025-04-25", "status": "pending", "createdAt": "2025-04-19 16:00:00"},
        {"id": "act_009", "type": "call", "subject": "招行智能客服合同确认", "description": "与陈刚确认合同条款",
         "accountId": "acc_004", "opportunityId": "opp_010", "contactId": "con_009",
         "dueDate": "2025-04-22", "status": "completed", "createdAt": "2025-04-21 10:00:00"},
        # 阿里
        {"id": "act_010", "type": "meeting", "subject": "阿里数据治理启动会", "description": "与马超、何涛讨论数据治理项目范围",
         "accountId": "acc_005", "opportunityId": "opp_012", "contactId": "con_011",
         "dueDate": "2025-04-20", "status": "completed", "createdAt": "2025-04-18 09:00:00"},
        {"id": "act_011", "type": "email", "subject": "阿里数据治理报价", "description": "发送正式报价给林燕",
         "accountId": "acc_005", "opportunityId": "opp_012", "contactId": "con_012",
         "dueDate": "2025-04-22", "status": "completed", "createdAt": "2025-04-20 14:00:00"},
        # 平安
        {"id": "act_012", "type": "meeting", "subject": "平安智能理赔方案演示", "description": "向吴刚演示智能理赔解决方案",
         "accountId": "acc_006", "opportunityId": "opp_013", "contactId": "con_014",
         "dueDate": "2025-04-18", "status": "completed", "createdAt": "2025-04-16 09:00:00"},
        {"id": "act_013", "type": "note", "subject": "平安数据湖初步接触", "description": "郑芳提到数据湖建设预算已获批",
         "accountId": "acc_006", "opportunityId": "opp_014", "contactId": "con_015",
         "dueDate": "2025-03-20", "status": "completed", "createdAt": "2025-03-20 15:00:00"},
        # 京东
        {"id": "act_014", "type": "meeting", "subject": "京东WMS需求评审", "description": "与徐明评审仓储系统升级需求",
         "accountId": "acc_007", "opportunityId": "opp_015", "contactId": "con_016",
         "dueDate": "2025-04-10", "status": "completed", "createdAt": "2025-04-08 14:00:00"},
        {"id": "act_015", "type": "call", "subject": "京东WMS技术对接", "description": "与杨帆讨论技术集成方案",
         "accountId": "acc_007", "opportunityId": "opp_015", "contactId": "con_017",
         "dueDate": "2025-04-15", "status": "completed", "createdAt": "2025-04-14 10:00:00"},
        # 药明康德
        {"id": "act_016", "type": "meeting", "subject": "药明LIMS方案讨论", "description": "与谢军讨论实验室信息管理系统需求",
         "accountId": "acc_008", "opportunityId": "opp_017", "contactId": "con_019",
         "dueDate": "2025-04-12", "status": "completed", "createdAt": "2025-04-10 09:00:00"},
        {"id": "act_017", "type": "email", "subject": "药明LIMS报价发送", "description": "发送LIMS系统报价方案",
         "accountId": "acc_008", "opportunityId": "opp_017", "contactId": "con_019",
         "dueDate": "2025-04-18", "status": "completed", "createdAt": "2025-04-16 14:00:00"},
        # 宁德时代
        {"id": "act_018", "type": "task", "subject": "宁德质检系统合同准备", "description": "准备智能质检系统的正式合同",
         "accountId": "acc_009", "opportunityId": "opp_018", "contactId": "con_021",
         "dueDate": "2025-04-25", "status": "pending", "createdAt": "2025-04-22 09:00:00"},
        {"id": "act_019", "type": "meeting", "subject": "宁德能源管理调研", "description": "调研宁德工厂能源管理现状",
         "accountId": "acc_009", "opportunityId": "opp_019", "contactId": "con_022",
         "dueDate": "2025-04-08", "status": "completed", "createdAt": "2025-04-05 10:00:00"},
        # 万科
        {"id": "act_020", "type": "note", "subject": "万科项目复盘", "description": "智慧社区项目丢单原因分析：预算削减+竞品低价",
         "accountId": "acc_010", "opportunityId": "opp_020", "contactId": "con_023",
         "dueDate": "2024-12-10", "status": "completed", "createdAt": "2024-12-05 09:00:00"},
        # 华为股份
        {"id": "act_021", "type": "meeting", "subject": "华为股份数字化办公需求调研", "description": "与陈志远讨论数字化办公平台的功能需求和实施计划",
         "accountId": "acc_011", "opportunityId": "opp_021", "contactId": "con_026",
         "dueDate": "2025-05-08", "status": "completed", "createdAt": "2025-05-06 09:00:00"},
        {"id": "act_022", "type": "email", "subject": "华为股份智能运维方案发送", "description": "发送智能运维系统技术方案给王建国评审",
         "accountId": "acc_011", "opportunityId": "opp_022", "contactId": "con_028",
         "dueDate": "2025-04-30", "status": "completed", "createdAt": "2025-04-28 14:00:00"},
    ]

    # ═══════════════════════════════════════════════════════════
    # 线索（10 个，独立于客户，覆盖各状态）
    # ═══════════════════════════════════════════════════════════
    data["lead"] = [
        {"id": "lead_001", "name": "刘洋", "company": "小米科技", "phone": "15000001111",
         "email": "liuyang@xiaomi.com", "source": "website", "status": "new", "score": 72, "createdAt": "2025-04-15 10:00:00"},
        {"id": "lead_002", "name": "孙丽", "company": "字节跳动", "phone": "15000002222",
         "email": "sunli@bytedance.com", "source": "event", "status": "contacted", "score": 85, "createdAt": "2025-04-10 14:00:00"},
        {"id": "lead_003", "name": "周明", "company": "美团", "phone": "15000003333",
         "email": "zhouming@meituan.com", "source": "referral", "status": "qualified", "score": 90, "createdAt": "2025-03-20 09:00:00"},
        {"id": "lead_004", "name": "吴芳", "company": "网易", "phone": "15000004444",
         "email": "wufang@netease.com", "source": "cold_call", "status": "new", "score": 45, "createdAt": "2025-04-18 10:00:00"},
        {"id": "lead_005", "name": "郑浩", "company": "滴滴出行", "phone": "15000005555",
         "email": "zhenghao@didi.com", "source": "advertisement", "status": "contacted", "score": 68, "createdAt": "2025-04-05 14:00:00"},
        {"id": "lead_006", "name": "钱进", "company": "蚂蚁集团", "phone": "15000006666",
         "email": "qianjin@antgroup.com", "source": "referral", "status": "qualified", "score": 92, "createdAt": "2025-03-10 09:00:00"},
        {"id": "lead_007", "name": "许晴", "company": "商汤科技", "phone": "15000007777",
         "email": "xuqing@sensetime.com", "source": "event", "status": "new", "score": 78, "createdAt": "2025-04-20 11:00:00"},
        {"id": "lead_008", "name": "韩磊", "company": "大疆创新", "phone": "15000008888",
         "email": "hanlei@dji.com", "source": "website", "status": "converted", "score": 95, "createdAt": "2025-02-15 10:00:00"},
        {"id": "lead_009", "name": "冯雪", "company": "科大讯飞", "phone": "15000009999",
         "email": "fengxue@iflytek.com", "source": "event", "status": "contacted", "score": 70, "createdAt": "2025-04-01 14:00:00"},
        {"id": "lead_010", "name": "陆涛", "company": "中兴通讯", "phone": "15000010000",
         "email": "lutao@zte.com", "source": "cold_call", "status": "expired", "score": 25, "createdAt": "2024-11-01 09:00:00"},
    ]

    return data
