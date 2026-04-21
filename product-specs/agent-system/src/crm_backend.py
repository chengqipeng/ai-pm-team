"""
CRM 模拟后端 — 完整的内存数据库 + CRUD + 聚合 + 元数据 + 权限
替代 MockServiceBackend，提供真实的业务逻辑。
"""
from __future__ import annotations

import uuid
import time
import copy
import re
from typing import Any
from dataclasses import dataclass, field


def _id() -> str:
    return uuid.uuid4().hex[:12]


def _now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


# ═══════════════════════════════════════════════════════════
# 元数据定义（Schema）
# ═══════════════════════════════════════════════════════════

ENTITY_SCHEMAS: dict[str, dict] = {
    "account": {
        "label": "客户",
        "api_key": "account",
        "items": [
            {"api_key": "name", "label": "公司名称", "item_type": "VARCHAR", "required": True},
            {"api_key": "industry", "label": "行业", "item_type": "PICK_LIST",
             "options": ["通信设备", "互联网", "制造业", "金融", "零售", "医疗"]},
            {"api_key": "city", "label": "城市", "item_type": "VARCHAR"},
            {"api_key": "employeeCount", "label": "员工数", "item_type": "INTEGER"},
            {"api_key": "annualRevenue", "label": "年营收(万元)", "item_type": "DECIMAL"},
            {"api_key": "website", "label": "网站", "item_type": "VARCHAR"},
            {"api_key": "rating", "label": "评分", "item_type": "INTEGER"},
            {"api_key": "activeFlg", "label": "是否活跃", "item_type": "INTEGER"},
        ],
        "links": [
            {"target": "contact", "type": "ONE_TO_MANY", "label": "联系人"},
            {"target": "opportunity", "type": "ONE_TO_MANY", "label": "商机"},
        ],
    },
    "contact": {
        "label": "联系人",
        "api_key": "contact",
        "items": [
            {"api_key": "name", "label": "姓名", "item_type": "VARCHAR", "required": True},
            {"api_key": "title", "label": "职位", "item_type": "VARCHAR"},
            {"api_key": "phone", "label": "电话", "item_type": "VARCHAR"},
            {"api_key": "email", "label": "邮箱", "item_type": "VARCHAR"},
            {"api_key": "accountId", "label": "所属客户", "item_type": "RELATIONSHIP"},
            {"api_key": "isPrimary", "label": "主要联系人", "item_type": "INTEGER"},
        ],
    },
    "opportunity": {
        "label": "商机",
        "api_key": "opportunity",
        "items": [
            {"api_key": "name", "label": "商机名称", "item_type": "VARCHAR", "required": True},
            {"api_key": "accountId", "label": "所属客户", "item_type": "RELATIONSHIP"},
            {"api_key": "amount", "label": "金额(万元)", "item_type": "DECIMAL"},
            {"api_key": "stage", "label": "阶段", "item_type": "PICK_LIST",
             "options": ["prospecting", "qualification", "proposal", "negotiation", "closing", "won", "lost"]},
            {"api_key": "probability", "label": "赢单概率(%)", "item_type": "INTEGER"},
            {"api_key": "closeDate", "label": "预计关闭日期", "item_type": "DATE"},
            {"api_key": "ownerId", "label": "负责人", "item_type": "RELATIONSHIP"},
            {"api_key": "source", "label": "来源", "item_type": "PICK_LIST",
             "options": ["inbound", "outbound", "referral", "partner"]},
            {"api_key": "lastActivityDate", "label": "最后活动日期", "item_type": "DATE"},
        ],
    },
    "activity": {
        "label": "活动",
        "api_key": "activity",
        "items": [
            {"api_key": "type", "label": "类型", "item_type": "PICK_LIST",
             "options": ["call", "email", "meeting", "task", "note"]},
            {"api_key": "subject", "label": "主题", "item_type": "VARCHAR", "required": True},
            {"api_key": "description", "label": "描述", "item_type": "TEXT"},
            {"api_key": "accountId", "label": "关联客户", "item_type": "RELATIONSHIP"},
            {"api_key": "opportunityId", "label": "关联商机", "item_type": "RELATIONSHIP"},
            {"api_key": "contactId", "label": "关联联系人", "item_type": "RELATIONSHIP"},
            {"api_key": "dueDate", "label": "截止日期", "item_type": "DATE"},
            {"api_key": "status", "label": "状态", "item_type": "PICK_LIST",
             "options": ["pending", "completed", "cancelled"]},
        ],
    },
    "lead": {
        "label": "线索",
        "api_key": "lead",
        "items": [
            {"api_key": "name", "label": "姓名", "item_type": "VARCHAR", "required": True},
            {"api_key": "company", "label": "公司", "item_type": "VARCHAR"},
            {"api_key": "phone", "label": "电话", "item_type": "VARCHAR"},
            {"api_key": "email", "label": "邮箱", "item_type": "VARCHAR"},
            {"api_key": "source", "label": "来源", "item_type": "PICK_LIST",
             "options": ["website", "advertisement", "referral", "event", "cold_call"]},
            {"api_key": "status", "label": "状态", "item_type": "PICK_LIST",
             "options": ["new", "contacted", "qualified", "converted", "expired"]},
            {"api_key": "score", "label": "评分", "item_type": "INTEGER"},
        ],
    },
}


# ═══════════════════════════════════════════════════════════
# 种子数据
# ═══════════════════════════════════════════════════════════

def build_seed_data() -> dict[str, list[dict]]:
    """构建完整的 CRM 种子数据"""
    data: dict[str, list[dict]] = {e: [] for e in ENTITY_SCHEMAS}

    # ── 客户 ──
    accounts = [
        {"id": "acc_001", "name": "华为技术有限公司", "industry": "通信设备", "city": "深圳",
         "employeeCount": 207000, "annualRevenue": 880900, "website": "huawei.com", "rating": 95, "activeFlg": 1},
        {"id": "acc_002", "name": "腾讯控股有限公司", "industry": "互联网", "city": "深圳",
         "employeeCount": 108000, "annualRevenue": 609000, "website": "tencent.com", "rating": 92, "activeFlg": 1},
        {"id": "acc_003", "name": "比亚迪股份有限公司", "industry": "制造业", "city": "深圳",
         "employeeCount": 290000, "annualRevenue": 602000, "website": "byd.com", "rating": 88, "activeFlg": 1},
        {"id": "acc_004", "name": "招商银行股份有限公司", "industry": "金融", "city": "深圳",
         "employeeCount": 110000, "annualRevenue": 340000, "website": "cmbchina.com", "rating": 90, "activeFlg": 1},
        {"id": "acc_005", "name": "万科企业股份有限公司", "industry": "零售", "city": "深圳",
         "employeeCount": 45000, "annualRevenue": 460000, "website": "vanke.com", "rating": 75, "activeFlg": 0},
    ]
    for a in accounts:
        a.setdefault("createdAt", "2025-01-15 10:00:00")
        a.setdefault("updatedAt", _now())
    data["account"] = accounts

    # ── 联系人 ──
    data["contact"] = [
        {"id": "con_001", "name": "张伟", "title": "IT总监", "phone": "13800001111", "email": "zhangwei@huawei.com",
         "accountId": "acc_001", "isPrimary": 1, "createdAt": "2025-01-20 09:00:00"},
        {"id": "con_002", "name": "李娜", "title": "采购经理", "phone": "13800002222", "email": "lina@huawei.com",
         "accountId": "acc_001", "isPrimary": 0, "createdAt": "2025-02-10 14:00:00"},
        {"id": "con_003", "name": "王强", "title": "CTO", "phone": "13900003333", "email": "wangqiang@tencent.com",
         "accountId": "acc_002", "isPrimary": 1, "createdAt": "2025-01-25 11:00:00"},
        {"id": "con_004", "name": "赵敏", "title": "数字化负责人", "phone": "13700004444", "email": "zhaomin@byd.com",
         "accountId": "acc_003", "isPrimary": 1, "createdAt": "2025-03-01 10:00:00"},
        {"id": "con_005", "name": "陈刚", "title": "信息部主管", "phone": "13600005555", "email": "chengang@cmb.com",
         "accountId": "acc_004", "isPrimary": 1, "createdAt": "2025-02-20 15:00:00"},
    ]

    # ── 商机 ──
    data["opportunity"] = [
        {"id": "opp_001", "name": "华为ERP实施", "accountId": "acc_001", "amount": 45.0,
         "stage": "proposal", "probability": 60, "closeDate": "2025-06-30", "ownerId": "user_zhang",
         "source": "inbound", "lastActivityDate": "2025-04-10", "createdAt": "2025-02-01 10:00:00"},
        {"id": "opp_002", "name": "华为CRM部署", "accountId": "acc_001", "amount": 28.0,
         "stage": "negotiation", "probability": 80, "closeDate": "2025-05-15", "ownerId": "user_li",
         "source": "referral", "lastActivityDate": "2025-04-18", "createdAt": "2025-01-20 09:00:00"},
        {"id": "opp_003", "name": "华为BI平台", "accountId": "acc_001", "amount": 15.0,
         "stage": "qualification", "probability": 30, "closeDate": "2025-08-01", "ownerId": "user_zhang",
         "source": "outbound", "lastActivityDate": "2025-03-25", "createdAt": "2025-03-10 14:00:00"},
        {"id": "opp_004", "name": "腾讯数据中台", "accountId": "acc_002", "amount": 62.0,
         "stage": "proposal", "probability": 50, "closeDate": "2025-07-20", "ownerId": "user_wang",
         "source": "partner", "lastActivityDate": "2025-04-15", "createdAt": "2025-02-15 11:00:00"},
        {"id": "opp_005", "name": "比亚迪MES系统", "accountId": "acc_003", "amount": 85.0,
         "stage": "prospecting", "probability": 20, "closeDate": "2025-09-30", "ownerId": "user_zhang",
         "source": "outbound", "lastActivityDate": "2025-04-05", "createdAt": "2025-03-20 16:00:00"},
        {"id": "opp_006", "name": "招行风控平台", "accountId": "acc_004", "amount": 120.0,
         "stage": "negotiation", "probability": 75, "closeDate": "2025-05-30", "ownerId": "user_li",
         "source": "inbound", "lastActivityDate": "2025-04-19", "createdAt": "2025-01-10 08:00:00"},
        {"id": "opp_007", "name": "华为安全审计", "accountId": "acc_001", "amount": 18.0,
         "stage": "closing", "probability": 90, "closeDate": "2025-04-30", "ownerId": "user_li",
         "source": "referral", "lastActivityDate": "2025-04-20", "createdAt": "2025-03-01 10:00:00"},
    ]

    # ── 活动 ──
    data["activity"] = [
        {"id": "act_001", "type": "meeting", "subject": "华为ERP需求讨论", "description": "与张伟讨论ERP实施范围和时间表",
         "accountId": "acc_001", "opportunityId": "opp_001", "contactId": "con_001",
         "dueDate": "2025-04-10", "status": "completed", "createdAt": "2025-04-08 09:00:00"},
        {"id": "act_002", "type": "call", "subject": "华为CRM报价跟进", "description": "与李娜确认CRM报价细节",
         "accountId": "acc_001", "opportunityId": "opp_002", "contactId": "con_002",
         "dueDate": "2025-04-18", "status": "completed", "createdAt": "2025-04-17 14:00:00"},
        {"id": "act_003", "type": "email", "subject": "腾讯数据中台方案发送", "description": "发送技术方案给王强",
         "accountId": "acc_002", "opportunityId": "opp_004", "contactId": "con_003",
         "dueDate": "2025-04-15", "status": "completed", "createdAt": "2025-04-14 10:00:00"},
        {"id": "act_004", "type": "task", "subject": "准备招行风控POC", "description": "准备POC环境和演示数据",
         "accountId": "acc_004", "opportunityId": "opp_006", "contactId": "con_005",
         "dueDate": "2025-04-25", "status": "pending", "createdAt": "2025-04-19 16:00:00"},
        {"id": "act_005", "type": "meeting", "subject": "比亚迪MES初步沟通", "description": "了解比亚迪生产线数字化需求",
         "accountId": "acc_003", "opportunityId": "opp_005", "contactId": "con_004",
         "dueDate": "2025-04-22", "status": "pending", "createdAt": "2025-04-20 09:00:00"},
    ]

    # ── 线索 ──
    data["lead"] = [
        {"id": "lead_001", "name": "刘洋", "company": "小米科技", "phone": "15000001111",
         "email": "liuyang@xiaomi.com", "source": "website", "status": "new", "score": 72, "createdAt": "2025-04-15 10:00:00"},
        {"id": "lead_002", "name": "孙丽", "company": "字节跳动", "phone": "15000002222",
         "email": "sunli@bytedance.com", "source": "event", "status": "contacted", "score": 85, "createdAt": "2025-04-10 14:00:00"},
        {"id": "lead_003", "name": "周明", "company": "美团", "phone": "15000003333",
         "email": "zhouming@meituan.com", "source": "referral", "status": "qualified", "score": 90, "createdAt": "2025-03-20 09:00:00"},
        {"id": "lead_004", "name": "吴芳", "company": "测试公司A", "phone": "15000004444",
         "email": "test@test.com", "source": "cold_call", "status": "expired", "score": 15, "createdAt": "2024-12-01 10:00:00"},
        {"id": "lead_005", "name": "郑浩", "company": "测试公司B", "phone": "15000005555",
         "email": "test2@test.com", "source": "advertisement", "status": "expired", "score": 20, "createdAt": "2024-11-15 10:00:00"},
    ]

    return data


# ═══════════════════════════════════════════════════════════
# CRM 模拟后端 — 完整 CRUD + 聚合 + 元数据
# ═══════════════════════════════════════════════════════════

class CrmSimulatedBackend:
    """
    内存 CRM 数据库，实现完整的 ServiceBackend 接口。
    支持: 查询/创建/更新/删除/计数/聚合/元数据查询/权限查询。
    """

    def __init__(self):
        self._data = build_seed_data()
        self._schemas = ENTITY_SCHEMAS
        self._audit_log: list[dict] = []

    # ── 元数据查询 ──

    async def query_metadata(self, query_type: str, **params) -> dict:
        entity_key = params.get("entity_api_key", "")

        if query_type == "list_entities":
            entities = [{"api_key": k, "label": v["label"]} for k, v in self._schemas.items()]
            return {"data": entities}

        if query_type == "entity" and entity_key in self._schemas:
            schema = self._schemas[entity_key]
            return {"data": schema}

        if query_type == "entity_items" and entity_key in self._schemas:
            return {"data": self._schemas[entity_key].get("items", [])}

        if query_type == "entity_links" and entity_key in self._schemas:
            return {"data": self._schemas[entity_key].get("links", [])}

        return {"data": {}, "error": f"未知查询: {query_type} {entity_key}"}

    # ── 数据 CRUD ──

    async def query_data(self, entity: str, filters: dict, **kw) -> dict:
        if entity not in self._data:
            return {"data": {"records": [], "total": 0}, "error": f"实体 {entity} 不存在"}

        records = self._data[entity]

        # 过滤
        if filters:
            records = [r for r in records if self._match_filters(r, filters)]

        total = len(records)

        # 排序
        order_by = kw.get("order_by")
        if order_by:
            desc = order_by.startswith("-")
            field_name = order_by.lstrip("-")
            records = sorted(records, key=lambda r: r.get(field_name, ""), reverse=desc)

        # 分页
        page = kw.get("page", 1)
        page_size = kw.get("page_size", 20)
        start = (page - 1) * page_size
        records = records[start:start + page_size]

        # 字段过滤
        fields = kw.get("fields")
        if fields:
            records = [{k: r.get(k) for k in ["id"] + fields if k in r} for r in records]

        return {"data": {"records": copy.deepcopy(records), "total": total}}

    async def mutate_data(self, entity: str, action: str, data: dict, **kw) -> dict:
        if entity not in self._data:
            return {"error": f"实体 {entity} 不存在"}

        if action == "create":
            record = {"id": f"{entity[:3]}_{_id()}", "createdAt": _now(), "updatedAt": _now()}
            record.update(data)
            # 必填校验
            schema = self._schemas.get(entity, {})
            for item in schema.get("items", []):
                if item.get("required") and item["api_key"] not in data:
                    return {"error": f"必填字段 {item['api_key']}({item['label']}) 缺失"}
            self._data[entity].append(record)
            self._log("create", entity, record["id"], data)
            return {"data": {"id": record["id"], "success": True, "record": copy.deepcopy(record)}}

        if action == "update":
            record_id = kw.get("record_id") or data.get("id")
            if not record_id:
                return {"error": "update 需要 record_id"}
            for r in self._data[entity]:
                if r["id"] == record_id:
                    old = copy.deepcopy(r)
                    r.update({k: v for k, v in data.items() if k != "id"})
                    r["updatedAt"] = _now()
                    self._log("update", entity, record_id, data, old=old)
                    return {"data": {"id": record_id, "success": True, "record": copy.deepcopy(r)}}
            return {"error": f"记录 {record_id} 不存在"}

        if action == "delete":
            record_id = kw.get("record_id") or data.get("id")
            if not record_id:
                # 批量删除（按 filters）
                filters = data.get("filters", {})
                if not filters:
                    return {"error": "delete 需要 record_id 或 filters"}
                before = len(self._data[entity])
                self._data[entity] = [r for r in self._data[entity] if not self._match_filters(r, filters)]
                deleted = before - len(self._data[entity])
                self._log("batch_delete", entity, f"filters={filters}", {"deleted_count": deleted})
                return {"data": {"success": True, "deleted_count": deleted}}
            # 单条删除
            before = len(self._data[entity])
            self._data[entity] = [r for r in self._data[entity] if r["id"] != record_id]
            if len(self._data[entity]) < before:
                self._log("delete", entity, record_id, {})
                return {"data": {"id": record_id, "success": True}}
            return {"error": f"记录 {record_id} 不存在"}

        return {"error": f"未知操作: {action}"}

    # ── 聚合查询 ──

    async def aggregate_data(self, entity: str, metrics: list, **kw) -> dict:
        if entity not in self._data:
            return {"data": {"results": []}, "error": f"实体 {entity} 不存在"}

        records = self._data[entity]
        filters = kw.get("filters", {})
        if filters:
            records = [r for r in records if self._match_filters(r, filters)]

        group_by = kw.get("group_by")
        results = []

        if group_by:
            # 分组聚合
            groups: dict[str, list] = {}
            for r in records:
                key = str(r.get(group_by, "未知"))
                groups.setdefault(key, []).append(r)

            for group_key, group_records in groups.items():
                row = {group_by: group_key}
                for m in metrics:
                    field_name = m.get("field", "")
                    func = m.get("function", "count")
                    row[f"{func}_{field_name}"] = self._calc_metric(group_records, field_name, func)
                results.append(row)
        else:
            # 全局聚合
            row = {}
            for m in metrics:
                field_name = m.get("field", "")
                func = m.get("function", "count")
                row[f"{func}_{field_name}"] = self._calc_metric(records, field_name, func)
            results.append(row)

        return {"data": {"results": results, "total_records": len(records)}}

    # ── 权限查询 ──

    async def query_permission(self, query_type: str, **kw) -> dict:
        # 模拟权限数据
        if query_type == "roles":
            return {"data": [
                {"api_key": "admin", "label": "管理员", "permissions": "全部"},
                {"api_key": "sales_manager", "label": "销售经理", "permissions": "本部门及下级"},
                {"api_key": "sales_rep", "label": "销售代表", "permissions": "本人"},
            ]}
        if query_type == "user_permissions":
            return {"data": {"role": "sales_manager", "data_scope": "本部门及下级",
                             "entities": ["account", "contact", "opportunity", "activity", "lead"]}}
        return {"data": {}}

    # ── 内部方法 ──

    def _match_filters(self, record: dict, filters: dict) -> bool:
        for key, value in filters.items():
            rec_val = record.get(key)
            if isinstance(value, str) and value.startswith(">"):
                try:
                    return float(rec_val or 0) > float(value[1:])
                except (ValueError, TypeError):
                    return False
            if isinstance(value, str) and value.startswith("<"):
                try:
                    return float(rec_val or 0) < float(value[1:])
                except (ValueError, TypeError):
                    return False
            if isinstance(value, list):
                if rec_val not in value:
                    return False
            elif rec_val != value:
                return False
        return True

    def _calc_metric(self, records: list, field_name: str, func: str) -> Any:
        if func == "count":
            return len(records)
        values = [r.get(field_name) for r in records if r.get(field_name) is not None]
        numeric = []
        for v in values:
            try:
                numeric.append(float(v))
            except (ValueError, TypeError):
                pass
        if not numeric:
            return 0
        if func == "sum":
            return round(sum(numeric), 2)
        if func == "avg":
            return round(sum(numeric) / len(numeric), 2)
        if func == "min":
            return min(numeric)
        if func == "max":
            return max(numeric)
        return len(records)

    def _log(self, action: str, entity: str, record_id: str, data: dict, **extra):
        self._audit_log.append({
            "action": action, "entity": entity, "record_id": record_id,
            "data": data, "timestamp": _now(), **extra,
        })

    @property
    def audit_log(self) -> list[dict]:
        return self._audit_log

    def get_stats(self) -> dict:
        """返回数据库统计"""
        return {entity: len(records) for entity, records in self._data.items()}
