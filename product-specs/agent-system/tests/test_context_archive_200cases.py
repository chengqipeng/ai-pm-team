"""ContextArchive 200+ 场景召回率评测

基于 5 个客户 × 30 轮对话 = 150 轮存档数据，覆盖 10 大类 × 20+ 细分查询场景。
纯 PG 关键词降级模式下的基线评测（不依赖 VDB / embedding / 外部服务）。

场景分类:
  A. 精确实体召回 (30 用例) — 按客户名/商机ID/联系人精确检索
  B. 模糊语义召回 (25 用例) — 同义词/改写/口语化查询
  C. 变更追踪检索 (25 用例) — 金额/日期/状态等属性变更
  D. 工具结果检索 (20 用例) — 按工具类型/返回内容检索
  E. 时间线排序验证 (20 用例) — 时间升序 + 跨轮次连续性
  F. 跨任务检索   (20 用例) — 不同任务间的实体关联
  G. 决策过程追踪 (20 用例) — 用户决策链完整性
  H. 负例验证     (20 用例) — 不应命中的查询
  I. 数据时效性   (10 用例) — 过时标注正确性
  J. 分级返回     (10 用例) — full 模式原文展开

运行: python3 tests/test_context_archive_200cases.py
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import sys
import time
import types
from dataclasses import dataclass, field
from typing import Any

# ═══════════════════════════════════════════════════════════
# 环境准备
# ═══════════════════════════════════════════════════════════

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Mock 消息类
class HumanMessage:
    type = "human"
    def __init__(self, content, **kw):
        self.content = content
        self.additional_kwargs = kw.get("additional_kwargs", {})

class AIMessage:
    type = "ai"
    def __init__(self, content="", tool_calls=None, **kw):
        self.content = content
        self.tool_calls = tool_calls or []
        self.additional_kwargs = kw.get("additional_kwargs", {})

class ToolMessage:
    type = "tool"
    def __init__(self, content, name="tool", tool_call_id="", **kw):
        self.content = content
        self.name = name
        self.tool_call_id = tool_call_id
        self.additional_kwargs = kw.get("additional_kwargs", {})

# Mock 模块注入
mock_messages = types.ModuleType("langchain_core.messages")
mock_messages.HumanMessage = HumanMessage
mock_messages.AIMessage = AIMessage
mock_messages.ToolMessage = ToolMessage
sys.modules["langchain_core.messages"] = mock_messages
for mod_name in [
    "langchain_core", "langchain_core.language_models",
    "langchain_core.language_models.chat_models",
    "langchain", "langchain.agents", "langchain.agents.middleware",
    "langchain.agents.middleware.types", "langchain_openai",
]:
    if mod_name not in sys.modules:
        sys.modules[mod_name] = types.ModuleType(mod_name)
class _MockMW: pass
sys.modules["langchain.agents.middleware.types"].AgentMiddleware = _MockMW


# Mock DAO
class MockDAO:
    _store: dict[str, list] = {}

    @classmethod
    def reset(cls): cls._store = {}

    @classmethod
    def batch_insert(cls, rows):
        for r in rows:
            cls._store.setdefault(r.thread_id, []).append(r)

    @classmethod
    def get_max_turn_id(cls, tenant_id, thread_id):
        rows = cls._store.get(thread_id, [])
        return max((r.turn_id for r in rows), default=0)

    @classmethod
    def get_by_turn_id(cls, tenant_id, thread_id, turn_id):
        for r in cls._store.get(thread_id, []):
            if r.turn_id == turn_id and r.delete_flg == 0:
                return r
        return None

    @classmethod
    def list_by_thread(cls, tenant_id, thread_id, limit=100):
        rows = cls._store.get(thread_id, [])
        return sorted([r for r in rows if r.delete_flg == 0], key=lambda r: r.turn_id)[:limit]

    @classmethod
    def search_by_keywords(cls, tenant_id, thread_id, keywords, top_k=5):
        rows = cls._store.get(thread_id, [])
        scored = []
        for r in rows:
            if r.delete_flg != 0: continue
            text = f"{r.user_query} {r.entities} {r.keywords} {r.answer_preview} {r.tool_names}".lower()
            score = sum(1 for kw in keywords if kw.lower() in text)
            if score > 0: scored.append((score, r))
        scored.sort(key=lambda x: -x[0])
        return [r for _, r in scored[:top_k]]

    @classmethod
    def search_by_entities(cls, tenant_id, thread_id, entity_names, top_k=5):
        rows = cls._store.get(thread_id, [])
        results = []
        for r in rows:
            if r.delete_flg != 0: continue
            for e in entity_names:
                if e.lower() in r.entities.lower():
                    results.append(r); break
        return results[:top_k]

    @classmethod
    def search_decisions(cls, tenant_id, thread_id, top_k=20):
        rows = cls._store.get(thread_id, [])
        return [r for r in rows if r.delete_flg == 0 and r.has_decision == 1][:top_k]

mock_dao_mod = types.ModuleType("src.store.context_archive_dao")
mock_dao_mod.ContextArchiveDAO = MockDAO
sys.modules["src.store.context_archive_dao"] = mock_dao_mod

mock_pg = types.ModuleType("src.store.pg_pool")
mock_pg.get_conn = lambda: None
sys.modules["src.store.pg_pool"] = mock_pg

_ctr = [0]
def _nid(): _ctr[0] += 1; return _ctr[0]
mock_sf = types.ModuleType("src.store.snowflake")
mock_sf.next_id = _nid
sys.modules["src.store.snowflake"] = mock_sf

sys.modules["src.middleware"] = types.ModuleType("src.middleware")

import importlib.util
def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod

_base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 先加载 models（被 dao import）
_models_mod = _load("src.store.context_archive_models", os.path.join(_base, "src/store/context_archive_models.py"))
sys.modules["src.store.context_archive_models"] = _models_mod

# 加载 archive_query_rewriter（被 context_archive_service 延迟导入）
_aqr = _load("src.middleware.archive_query_rewriter", os.path.join(_base, "src/middleware/archive_query_rewriter.py"))

_ca = _load("src.middleware.context_archive", os.path.join(_base, "src/middleware/context_archive.py"))
_cas = _load("src.middleware.context_archive_service", os.path.join(_base, "src/middleware/context_archive_service.py"))
ContextArchive = _ca.ContextArchive
ContextArchiveService = _cas.ContextArchiveService


# ═══════════════════════════════════════════════════════════
# 对话数据生成 — 5 个客户 × 6 轮 = 30 轮基础对话
# ═══════════════════════════════════════════════════════════

def _tc(n): return f"tc{n}"

def build_conversations() -> list:
    """构建 5 个客户的完整对话历史（30 轮 × 约 4 条/轮 ≈ 120+ 条消息）"""
    msgs = []
    tc = [0]
    def tid():
        tc[0] += 1; return f"tc{tc[0]}"

    # ════════ 客户 1: PT Sentosa — 报价谈判全流程 ════════
    # 轮次 1: 查客户
    msgs += [
        HumanMessage("帮我查一下 PT Sentosa 的客户信息"),
        AIMessage(tool_calls=[{"id": tid(), "name": "query_data", "args": {"entity": "account", "filter": "name=PT Sentosa"}}]),
        ToolMessage('{"name":"PT Sentosa Jaya","industry":"制造业","employees":200,"revenue":"$5M","location":"Jakarta"}', name="query_data", tool_call_id=tc[0]),
        AIMessage("PT Sentosa Jaya 是一家位于 Jakarta 的制造业公司，200人规模，年营收$5M。"),
    ]
    # 轮次 2: 查商机
    msgs += [
        HumanMessage("他们的商机情况怎样"),
        AIMessage(tool_calls=[{"id": tid(), "name": "query_data", "args": {"entity": "opportunity", "filter": "account=PT Sentosa"}}]),
        ToolMessage('{"id":"opp_001","amount":"$45K","stage":"proposal","close_date":"2025-05-15","owner":"Andi"}', name="query_data", tool_call_id=tc[0]),
        AIMessage("PT Sentosa 有商机 opp_001，金额$45K，proposal阶段，预计2025-05-15关闭，负责人Andi。"),
    ]
    # 轮次 3: 生成报价
    msgs += [
        HumanMessage("帮我生成一份报价方案"),
        AIMessage(tool_calls=[{"id": tid(), "name": "analyze_data", "args": {"task": "generate_quote"}}]),
        ToolMessage('{"quote":"Q-001","amount":"$45K","discount":"15%","final":"$38,250","payment":"签约30%+上线40%+验收30%","includes":"8周实施+3个月支持"}', name="analyze_data", tool_call_id=tc[0]),
        AIMessage("报价Q-001：总价$45K，年付15%折扣=$38,250。付款：签约30%+上线40%+验收30%。含8周实施+3个月免费支持。"),
    ]
    # 轮次 4: 竞品调研
    msgs += [
        HumanMessage("Odoo 的定价是多少，做个对比"),
        AIMessage(tool_calls=[{"id": tid(), "name": "web_search", "args": {"query": "Odoo pricing 2025"}}]),
        ToolMessage('{"answer":"Odoo Standard $24.90/user/month, Manufacturing +$18/user/month, 200人年费约$103K"}', name="web_search", tool_call_id=tc[0]),
        AIMessage("Odoo: 标准$24.90/user/month + Manufacturing $18 = $42.90/user/month，200人年费约$103K。比我们$45K贵一倍多。"),
    ]
    # 轮次 5: 客户砍价
    msgs += [
        HumanMessage("客户说报价太贵了，要求降到$40K"),
        AIMessage("了解。将报价从$45K调整到$40K，年付15%折扣后最终价格$34,000。需要我更新报价单吗？"),
    ]
    # 轮次 6: 确认新报价
    msgs += [
        HumanMessage("确认，按$40K更新报价，付款条件不变"),
        AIMessage(tool_calls=[{"id": tid(), "name": "execute_task", "args": {"task": "update_quote", "id": "Q-001", "amount": "$40K"}}]),
        ToolMessage('{"success":true,"quote_id":"Q-001","amount":"$40K","final":"$34,000"}', name="execute_task", tool_call_id=tc[0]),
        AIMessage("已更新报价Q-001：总价$40K，折扣后$34,000。付款条件不变：签约30%+上线40%+验收30%。"),
    ]

    # ════════ 客户 2: CV XYZ — 合同续约 ════════
    # 轮次 7: 查合同
    msgs += [
        HumanMessage("CV XYZ 的合同什么时候到期"),
        AIMessage(tool_calls=[{"id": tid(), "name": "query_data", "args": {"entity": "contract", "filter": "account=CV XYZ"}}]),
        ToolMessage('{"id":"con_005","end_date":"2025-06-30","amount":"$20K/year","status":"active","auto_renew":false}', name="query_data", tool_call_id=tc[0]),
        AIMessage("CV XYZ合同con_005将于2025-06-30到期，年费$20K，不自动续约。建议提前2个月启动续约流程。"),
    ]
    # 轮次 8: 续约方案
    msgs += [
        HumanMessage("帮我做个续约方案，涨价10%"),
        AIMessage(tool_calls=[{"id": tid(), "name": "analyze_data", "args": {"task": "renewal_proposal", "current": "$20K", "increase": "10%"}}]),
        ToolMessage('{"new_amount":"$22K/year","justification":"新增AI功能+SLA升级","competitor_risk":"中等-Salesforce在接触"}', name="analyze_data", tool_call_id=tc[0]),
        AIMessage("续约方案：年费$20K→$22K(+10%)。理由：新增AI功能+SLA升级。风险：Salesforce在接触客户，竞争压力中等。"),
    ]
    # 轮次 9: 客户要求维持原价
    msgs += [
        HumanMessage("客户说不接受涨价，要求维持$20K"),
        AIMessage("理解。如果维持$20K原价，建议去掉SLA升级保留AI功能，或者签3年锁定当前价格。需要哪个方案？"),
    ]
    # 轮次 10: 最终决策
    msgs += [
        HumanMessage("选3年锁定方案"),
        AIMessage(tool_calls=[{"id": tid(), "name": "execute_task", "args": {"task": "update_contract", "id": "con_005", "term": "3years", "amount": "$20K/year"}}]),
        ToolMessage('{"success":true,"contract":"con_005","term":"3年","amount":"$20K/year","new_end":"2028-06-30"}', name="execute_task", tool_call_id=tc[0]),
        AIMessage("已更新合同con_005：3年期锁定$20K/year，新到期日2028-06-30。"),
    ]

    # ════════ 客户 3: 华为科技 — 大客户复杂商机 ════════
    # 轮次 11: 查客户画像
    msgs += [
        HumanMessage("查一下华为科技的客户画像"),
        AIMessage(tool_calls=[{"id": tid(), "name": "query_data", "args": {"entity": "account", "filter": "name=华为科技"}}]),
        ToolMessage('{"name":"华为科技","industry":"ICT","employees":207000,"revenue":"¥8809亿","tier":"S级","owner":"张磊"}', name="query_data", tool_call_id=tc[0]),
        AIMessage("华为科技：ICT行业，20.7万人，年营收¥8809亿，S级客户，客户经理张磊。"),
    ]
    # 轮次 12: BANT 分析
    msgs += [
        HumanMessage("做个 BANT 分析"),
        AIMessage(tool_calls=[{"id": tid(), "name": "analyze_data", "args": {"task": "bant_analysis", "account": "华为科技"}}]),
        ToolMessage('{"budget":"¥500万以上","authority":"张总-VP级决策者","need":"数字化转型-ERP替换","timeline":"Q3启动POC"}', name="analyze_data", tool_call_id=tc[0]),
        AIMessage("华为科技BANT：Budget ¥500万+，Authority 张总(VP级)，Need 数字化转型/ERP替换，Timeline Q3启动POC。"),
    ]
    # 轮次 13: 竞品情报
    msgs += [
        HumanMessage("华为那边 SAP 报了多少钱"),
        AIMessage(tool_calls=[{"id": tid(), "name": "web_search", "args": {"query": "SAP ERP enterprise pricing 2025"}}]),
        ToolMessage('{"answer":"SAP S/4HANA Cloud: $150-300/user/month, 华为规模估算年费约¥3000万"}', name="web_search", tool_call_id=tc[0]),
        AIMessage("SAP报价估算：S/4HANA Cloud $150-300/user/month，华为规模年费约¥3000万。我们方案可以做到¥500万以内。"),
    ]
    # 轮次 14: 联系人
    msgs += [
        HumanMessage("华为科技的关键决策人是谁"),
        AIMessage(tool_calls=[{"id": tid(), "name": "query_data", "args": {"entity": "contact", "filter": "account=华为科技"}}]),
        ToolMessage('{"contacts":[{"name":"张总","title":"VP数字化","role":"决策者"},{"name":"李工","title":"IT总监","role":"技术评估"},{"name":"王助理","title":"采购经理","role":"流程推进"}]}', name="query_data", tool_call_id=tc[0]),
        AIMessage("华为科技决策链：张总(VP,决策者)→李工(IT总监,技术评估)→王助理(采购经理,流程推进)。"),
    ]
    # 轮次 15: POC规划
    msgs += [
        HumanMessage("规划一下华为的POC方案"),
        AIMessage(tool_calls=[{"id": tid(), "name": "execute_task", "args": {"task": "create_poc_plan", "account": "华为科技", "duration": "4weeks"}}]),
        ToolMessage('{"poc_id":"POC-HW-001","duration":"4周","scope":"采购模块+审批流","success_criteria":"处理效率提升30%","resources":"2SA+1PM"}', name="execute_task", tool_call_id=tc[0]),
        AIMessage("华为POC方案POC-HW-001：4周，范围采购模块+审批流，成功标准处理效率提升30%，资源2SA+1PM。"),
    ]
    # 轮次 16: POC结果
    msgs += [
        HumanMessage("华为POC结果怎么样"),
        AIMessage(tool_calls=[{"id": tid(), "name": "query_data", "args": {"entity": "poc_result", "filter": "poc_id=POC-HW-001"}}]),
        ToolMessage('{"poc_id":"POC-HW-001","result":"pass","efficiency_gain":"42%","feedback":"张总满意，李工提出集成需求","next_step":"商务谈判"}', name="query_data", tool_call_id=tc[0]),
        AIMessage("华为POC通过！效率提升42%（超过30%目标），张总满意，李工提出系统集成需求。下一步进入商务谈判。"),
    ]

    # ════════ 客户 4: 腾讯云 — 技术型客户 ════════
    # 轮次 17: 需求调研
    msgs += [
        HumanMessage("腾讯云那边提了什么需求"),
        AIMessage(tool_calls=[{"id": tid(), "name": "query_data", "args": {"entity": "requirement", "filter": "account=腾讯云"}}]),
        ToolMessage('{"requirements":[{"id":"REQ-TC-001","title":"API对接","priority":"P0"},{"id":"REQ-TC-002","title":"多租户隔离","priority":"P0"},{"id":"REQ-TC-003","title":"日志审计","priority":"P1"}]}', name="query_data", tool_call_id=tc[0]),
        AIMessage("腾讯云需求：P0-API对接、P0-多租户隔离、P1-日志审计。"),
    ]
    # 轮次 18: 技术方案
    msgs += [
        HumanMessage("针对腾讯云的需求出个技术方案"),
        AIMessage(tool_calls=[{"id": tid(), "name": "analyze_data", "args": {"task": "technical_proposal", "account": "腾讯云"}}]),
        ToolMessage('{"proposal":"TP-TC-001","api":"RESTful+GraphQL双协议","isolation":"Schema级隔离+行级权限","audit":"ELK日志+实时告警","timeline":"8周交付","cost":"¥80万"}', name="analyze_data", tool_call_id=tc[0]),
        AIMessage("腾讯云技术方案TP-TC-001：RESTful+GraphQL双协议、Schema级隔离、ELK日志审计。8周交付，费用¥80万。"),
    ]
    # 轮次 19: 报价
    msgs += [
        HumanMessage("腾讯云的报价定多少"),
        AIMessage(tool_calls=[{"id": tid(), "name": "execute_task", "args": {"task": "create_quote", "account": "腾讯云", "amount": "¥80万"}}]),
        ToolMessage('{"quote_id":"Q-TC-001","amount":"¥80万","payment":"里程碑付款：需求确认20%+开发完成40%+验收20%+上线20%","validity":"30天"}', name="execute_task", tool_call_id=tc[0]),
        AIMessage("腾讯云报价Q-TC-001：¥80万，里程碑付款(需求确认20%+开发40%+验收20%+上线20%)，有效期30天。"),
    ]
    # 轮次 20: 砍价
    msgs += [
        HumanMessage("腾讯那边说¥80万太贵，最多¥60万"),
        AIMessage("¥60万的话需要砍掉GraphQL协议支持和实时告警，只保留RESTful+Schema隔离+基础日志。这样可以接受吗？"),
    ]
    # 轮次 21: 折中
    msgs += [
        HumanMessage("GraphQL必须保留，日志审计可以降级，最终¥68万行不行"),
        AIMessage(tool_calls=[{"id": tid(), "name": "execute_task", "args": {"task": "update_quote", "id": "Q-TC-001", "amount": "¥68万"}}]),
        ToolMessage('{"success":true,"quote_id":"Q-TC-001","amount":"¥68万","scope":"RESTful+GraphQL+Schema隔离+基础日志(不含实时告警)"}', name="execute_task", tool_call_id=tc[0]),
        AIMessage("已更新报价Q-TC-001：¥68万，含RESTful+GraphQL+Schema隔离+基础日志（不含实时告警）。"),
    ]

    # ════════ 客户 5: 比亚迪 — 快速成交 ════════
    # 轮次 22: 查客户
    msgs += [
        HumanMessage("比亚迪的客户信息"),
        AIMessage(tool_calls=[{"id": tid(), "name": "query_data", "args": {"entity": "account", "filter": "name=比亚迪"}}]),
        ToolMessage('{"name":"比亚迪","industry":"汽车制造","employees":90000,"revenue":"¥6023亿","tier":"A级"}', name="query_data", tool_call_id=tc[0]),
        AIMessage("比亚迪：汽车制造业，9万人，年营收¥6023亿，A级客户。"),
    ]
    # 轮次 23: 商机
    msgs += [
        HumanMessage("比亚迪有什么商机"),
        AIMessage(tool_calls=[{"id": tid(), "name": "query_data", "args": {"entity": "opportunity", "filter": "account=比亚迪"}}]),
        ToolMessage('{"id":"opp_BYD_001","amount":"¥150万","stage":"negotiation","close_date":"2025-04-30","product":"供应链管理模块"}', name="query_data", tool_call_id=tc[0]),
        AIMessage("比亚迪商机opp_BYD_001：¥150万，negotiation阶段，预计2025-04-30成交，产品供应链管理模块。"),
    ]
    # 轮次 24: 签约
    msgs += [
        HumanMessage("比亚迪签约了，¥150万全款，帮我更新"),
        AIMessage(tool_calls=[{"id": tid(), "name": "execute_task", "args": {"task": "close_deal", "opp_id": "opp_BYD_001", "amount": "¥150万"}}]),
        ToolMessage('{"success":true,"opportunity":"opp_BYD_001","stage":"closed_won","amount":"¥150万","contract":"CON-BYD-001"}', name="execute_task", tool_call_id=tc[0]),
        AIMessage("比亚迪商机opp_BYD_001已成交！金额¥150万，合同编号CON-BYD-001。恭喜！"),
    ]
    # 轮次 25: pipeline总览
    msgs += [
        HumanMessage("给我看看整体pipeline情况"),
        AIMessage(tool_calls=[{"id": tid(), "name": "analyze_data", "args": {"task": "pipeline_summary"}}]),
        ToolMessage('{"total":"¥850万","count":12,"stages":{"prospecting":3,"qualification":2,"proposal":3,"negotiation":2,"closing":2},"won_this_month":"¥150万","forecast":"¥320万"}', name="analyze_data", tool_call_id=tc[0]),
        AIMessage("Pipeline总览：总额¥850万，12个商机。本月成交¥150万(比亚迪)，预测未来30天¥320万。"),
    ]
    # 轮次 26: 风险商机
    msgs += [
        HumanMessage("有哪些高风险的商机"),
        AIMessage(tool_calls=[{"id": tid(), "name": "analyze_data", "args": {"task": "risk_analysis"}}]),
        ToolMessage('{"at_risk":[{"opp":"opp_001","account":"PT Sentosa","reason":"报价反复，决策周期长"},{"opp":"opp_TC_001","account":"腾讯云","reason":"预算压缩，技术选型未定"}]}', name="analyze_data", tool_call_id=tc[0]),
        AIMessage("高风险商机：1) PT Sentosa opp_001 — 报价反复，决策周期长；2) 腾讯云 — 预算压缩，技术选型未定。"),
    ]
    # 轮次 27: 活动记录
    msgs += [
        HumanMessage("上周跟华为科技有什么互动"),
        AIMessage(tool_calls=[{"id": tid(), "name": "query_data", "args": {"entity": "activity", "filter": "account=华为科技,date>=last_week"}}]),
        ToolMessage('{"activities":[{"type":"会议","date":"2025-03-10","attendees":"张总,李工","summary":"POC汇报，讨论商务条款"},{"type":"邮件","date":"2025-03-12","to":"王助理","summary":"发送正式报价单¥480万"}]}', name="query_data", tool_call_id=tc[0]),
        AIMessage("上周华为互动：3/10会议(张总+李工,POC汇报)、3/12邮件(发王助理正式报价¥480万)。"),
    ]
    # 轮次 28: 华为报价调整
    msgs += [
        HumanMessage("华为那边张总说¥480万太高，能不能做到¥420万"),
        AIMessage("¥420万需要减少实施周期从12周到8周，或去掉2个定制模块。具体怎么调？"),
    ]
    # 轮次 29: 确认华为报价
    msgs += [
        HumanMessage("减少实施周期到8周，保留全部模块，报价¥450万"),
        AIMessage(tool_calls=[{"id": tid(), "name": "execute_task", "args": {"task": "update_quote", "account": "华为科技", "amount": "¥450万", "impl_weeks": 8}}]),
        ToolMessage('{"success":true,"quote_id":"Q-HW-001","amount":"¥450万","impl_duration":"8周","modules":"全部保留"}', name="execute_task", tool_call_id=tc[0]),
        AIMessage("已更新华为报价Q-HW-001：¥450万，实施8周，全部模块保留。"),
    ]
    # 轮次 30: 回顾总结
    msgs += [
        HumanMessage("总结一下本周所有客户的进展"),
        AIMessage("本周进展：\n1. PT Sentosa：报价降到$40K已确认\n2. CV XYZ：3年锁定$20K续约完成\n3. 华为科技：POC通过，报价¥450万待审批\n4. 腾讯云：报价¥68万已确认\n5. 比亚迪：¥150万已签约成交"),
    ]

    return msgs


# ═══════════════════════════════════════════════════════════
# 200+ 评测用例
# ═══════════════════════════════════════════════════════════

@dataclass
class Case:
    id: str
    category: str
    query: str
    expected_turns: list[int] = field(default_factory=list)  # 期望命中的轮次
    expected_entity: str = ""
    expect_change: bool = False
    expect_no_hit: bool = False  # 负例
    expect_sorted: bool = True
    mode: str = "timeline"
    target_turn_id: int | None = None


def build_cases() -> list[Case]:
    """生成 200+ 细分场景用例"""
    cases = []

    # ════════════════════════════════════════════════════════
    # A. 精确实体召回 (30)
    # ════════════════════════════════════════════════════════
    cases += [
        Case("A01", "精确实体", "PT Sentosa 客户信息", [1], "PT Sentosa"),
        Case("A02", "精确实体", "PT Sentosa 商机", [2], "PT Sentosa"),
        Case("A03", "精确实体", "PT Sentosa 报价", [3, 5, 6], "PT Sentosa"),
        Case("A04", "精确实体", "CV XYZ 合同", [7], "CV XYZ"),
        Case("A05", "精确实体", "CV XYZ 续约", [8, 9, 10], "CV XYZ"),
        Case("A06", "精确实体", "华为科技 客户画像", [11], "华为科技"),
        Case("A07", "精确实体", "华为科技 BANT", [12], "华为科技"),
        Case("A08", "精确实体", "华为科技 联系人", [14], "华为科技"),
        Case("A09", "精确实体", "华为科技 POC", [15, 16], "华为科技"),
        Case("A10", "精确实体", "华为科技 报价", [27, 28, 29], "华为科技"),
        Case("A11", "精确实体", "腾讯云 需求", [17], "腾讯云"),
        Case("A12", "精确实体", "腾讯云 技术方案", [18], "腾讯云"),
        Case("A13", "精确实体", "腾讯云 报价", [19, 20, 21], "腾讯云"),
        Case("A14", "精确实体", "比亚迪 客户信息", [22], "比亚迪"),
        Case("A15", "精确实体", "比亚迪 商机", [23], "比亚迪"),
        Case("A16", "精确实体", "比亚迪 签约", [24], "比亚迪"),
        Case("A17", "精确实体", "opp_001 商机详情", [2], "PT Sentosa"),
        Case("A18", "精确实体", "con_005 合同", [7, 10], "CV XYZ"),
        Case("A19", "精确实体", "Q-001 报价单", [3, 6]),
        Case("A20", "精确实体", "Q-TC-001 报价", [19, 21]),
        Case("A21", "精确实体", "POC-HW-001", [15, 16]),
        Case("A22", "精确实体", "张总 华为", [12, 14, 16, 27, 28]),
        Case("A23", "精确实体", "Andi PT Sentosa", [2]),
        Case("A24", "精确实体", "pipeline 总览", [25]),
        Case("A25", "精确实体", "风险商机", [26]),
        Case("A26", "精确实体", "CON-BYD-001", [24]),
        Case("A27", "精确实体", "opp_BYD_001", [23, 24]),
        Case("A28", "精确实体", "REQ-TC-001 API对接", [17]),
        Case("A29", "精确实体", "TP-TC-001 技术方案", [18]),
        Case("A30", "精确实体", "Q-HW-001", [29]),
    ]

    # ════════════════════════════════════════════════════════
    # B. 模糊语义召回 (25)
    # ════════════════════════════════════════════════════════
    cases += [
        Case("B01", "模糊语义", "制造业客户", [1, 22]),
        Case("B02", "模糊语义", "Jakarta 的公司", [1]),
        Case("B03", "模糊语义", "年费二十万的合同", [7, 8, 9, 10]),
        Case("B04", "模糊语义", "S级大客户", [11]),
        Case("B05", "模糊语义", "汽车行业客户", [22]),
        Case("B06", "模糊语义", "ICT 行业", [11]),
        Case("B07", "模糊语义", "做POC的客户", [15, 16]),
        Case("B08", "模糊语义", "已签约的商机", [24]),
        Case("B09", "模糊语义", "本月成交了多少", [24, 25]),
        Case("B10", "模糊语义", "还在谈判的客户", [23]),
        Case("B11", "模糊语义", "涨价方案", [8]),
        Case("B12", "模糊语义", "API 接口需求", [17]),
        Case("B13", "模糊语义", "多租户架构", [17, 18]),
        Case("B14", "模糊语义", "ERP替换项目", [12]),
        Case("B15", "模糊语义", "供应链管理", [23]),
        Case("B16", "模糊语义", "折扣优惠", [3, 6]),
        Case("B17", "模糊语义", "付款条件", [3, 6, 19]),
        Case("B18", "模糊语义", "里程碑付款", [19]),
        Case("B19", "模糊语义", "实施周期多长", [3, 15, 29]),
        Case("B20", "模糊语义", "免费技术支持", [3]),
        Case("B21", "模糊语义", "竞品对比", [4, 13]),
        Case("B22", "模糊语义", "SAP 报价多少", [13]),
        Case("B23", "模糊语义", "Odoo 多少钱", [4]),
        Case("B24", "模糊语义", "哪些客户砍过价", [5, 9, 20, 28]),
        Case("B25", "模糊语义", "审批流相关", [15]),
    ]

    # ════════════════════════════════════════════════════════
    # C. 变更追踪 (25)
    # ════════════════════════════════════════════════════════
    cases += [
        Case("C01", "变更追踪", "PT Sentosa 报价怎么变的", [3, 5, 6], expect_change=True),
        Case("C02", "变更追踪", "CV XYZ 合同金额变化", [7, 8, 9, 10], expect_change=True),
        Case("C03", "变更追踪", "腾讯云报价调整历史", [19, 20, 21], expect_change=True),
        Case("C04", "变更追踪", "华为科技报价从多少降到多少", [27, 28, 29], expect_change=True),
        Case("C05", "变更追踪", "$45K 后来改成多少了", [3, 5, 6], expect_change=True),
        Case("C06", "变更追踪", "¥80万最后谈到多少", [19, 20, 21], expect_change=True),
        Case("C07", "变更追踪", "合同期限怎么变的", [7, 10], expect_change=True),
        Case("C08", "变更追踪", "PT Sentosa 折扣变没变", [3, 6]),
        Case("C09", "变更追踪", "实施周期从12周改到多少", [28, 29], expect_change=True),
        Case("C10", "变更追踪", "腾讯云方案砍了哪些功能", [20, 21], expect_change=True),
        Case("C11", "变更追踪", "¥450万是怎么定下来的", [28, 29]),
        Case("C12", "变更追踪", "$40K 的报价谁同意的", [5, 6]),
        Case("C13", "变更追踪", "CV XYZ 最终选了哪个方案", [9, 10]),
        Case("C14", "变更追踪", "腾讯云 GraphQL 保留了吗", [21]),
        Case("C15", "变更追踪", "日志审计最后怎么处理的", [21]),
        Case("C16", "变更追踪", "比亚迪成交价格和最初一样吗", [23, 24]),
        Case("C17", "变更追踪", "PT Sentosa 付款条件改了没", [3, 6]),
        Case("C18", "变更追踪", "华为POC范围有没有调整", [15, 16]),
        Case("C19", "变更追踪", "pipeline 总额变化", [25]),
        Case("C20", "变更追踪", "Q-001 金额变更记录", [3, 6], expect_change=True),
        Case("C21", "变更追踪", "con_005 到期日变了吗", [7, 10], expect_change=True),
        Case("C22", "变更追踪", "商机阶段从proposal到哪了", [2]),
        Case("C23", "变更追踪", "腾讯云付款方式有变吗", [19, 21]),
        Case("C24", "变更追踪", "¥480万为什么降到¥450万", [27, 28, 29], expect_change=True),
        Case("C25", "变更追踪", "$20K 续约维持原价的原因", [8, 9, 10]),
    ]

    # ════════════════════════════════════════════════════════
    # D. 工具结果检索 (20)
    # ════════════════════════════════════════════════════════
    cases += [
        Case("D01", "工具结果", "query_data 查到了什么", [1, 2, 7, 11, 14, 17, 22, 23, 27]),
        Case("D02", "工具结果", "web_search 搜了什么", [4, 13]),
        Case("D03", "工具结果", "analyze_data 分析结果", [3, 8, 12, 18, 25, 26]),
        Case("D04", "工具结果", "execute_task 执行了什么", [6, 10, 15, 19, 21, 24, 29]),
        Case("D05", "工具结果", "哪次查询用了 web_search", [4, 13]),
        Case("D06", "工具结果", "pipeline_summary 结果", [25]),
        Case("D07", "工具结果", "risk_analysis 结果", [26]),
        Case("D08", "工具结果", "bant_analysis 结果", [12]),
        Case("D09", "工具结果", "generate_quote 生成了什么", [3]),
        Case("D10", "工具结果", "create_poc_plan 内容", [15]),
        Case("D11", "工具结果", "update_quote 执行记录", [6, 21, 29]),
        Case("D12", "工具结果", "update_contract 执行记录", [10]),
        Case("D13", "工具结果", "close_deal 成交记录", [24]),
        Case("D14", "工具结果", "renewal_proposal 方案", [8]),
        Case("D15", "工具结果", "technical_proposal 方案", [18]),
        Case("D16", "工具结果", "create_quote 腾讯", [19]),
        Case("D17", "工具结果", "查询客户活动记录", [27]),
        Case("D18", "工具结果", "poc_result 查询结果", [16]),
        Case("D19", "工具结果", "requirement 需求查询", [17]),
        Case("D20", "工具结果", "contact 联系人查询", [14]),
    ]

    # ════════════════════════════════════════════════════════
    # E. 时间线排序 (20)
    # ════════════════════════════════════════════════════════
    cases += [
        Case("E01", "时间线", "PT Sentosa 从开始到报价确认", [1, 2, 3, 5, 6]),
        Case("E02", "时间线", "CV XYZ 续约全过程", [7, 8, 9, 10]),
        Case("E03", "时间线", "华为科技从调研到POC", [11, 12, 13, 14, 15, 16]),
        Case("E04", "时间线", "腾讯云从需求到报价", [17, 18, 19, 20, 21]),
        Case("E05", "时间线", "比亚迪从查询到签约", [22, 23, 24]),
        Case("E06", "时间线", "所有报价相关的轮次", [3, 5, 6, 19, 20, 21, 27, 28, 29]),
        Case("E07", "时间线", "所有签约成交记录", [10, 24]),
        Case("E08", "时间线", "所有竞品调研", [4, 13]),
        Case("E09", "时间线", "所有砍价谈判", [5, 9, 20, 28]),
        Case("E10", "时间线", "PT Sentosa 报价时间线", [3, 5, 6]),
        Case("E11", "时间线", "华为报价谈判过程", [27, 28, 29]),
        Case("E12", "时间线", "腾讯云报价谈判过程", [19, 20, 21]),
        Case("E13", "时间线", "本周客户互动时间线", [27]),
        Case("E14", "时间线", "所有 POC 相关事件", [15, 16]),
        Case("E15", "时间线", "pipeline 分析记录", [25, 26]),
        Case("E16", "时间线", "所有 execute_task 按时间", [6, 10, 15, 19, 21, 24, 29]),
        Case("E17", "时间线", "华为科技全部互动历史", [11, 12, 13, 14, 15, 16, 27, 28, 29]),
        Case("E18", "时间线", "最早的客户查询", [1]),
        Case("E19", "时间线", "最后一次报价更新", [29]),
        Case("E20", "时间线", "所有合同相关操作", [7, 8, 9, 10, 24]),
    ]

    # ════════════════════════════════════════════════════════
    # F. 跨任务检索 (20)
    # ════════════════════════════════════════════════════════
    cases += [
        Case("F01", "跨任务", "PT Sentosa 和华为的报价对比", [3, 5, 6, 27, 28, 29]),
        Case("F02", "跨任务", "哪些客户的报价超过¥100万", [23, 27, 28, 29]),
        Case("F03", "跨任务", "制造业客户有哪些", [1, 22]),
        Case("F04", "跨任务", "所有使用 web_search 的场景", [4, 13]),
        Case("F05", "跨任务", "用 execute_task 更新过报价的客户", [6, 21, 29]),
        Case("F06", "跨任务", "成交金额最大的客户", [24]),
        Case("F07", "跨任务", "有竞品威胁的客户", [4, 8, 13, 26]),
        Case("F08", "跨任务", "Salesforce 和 SAP 竞争", [8, 13]),
        Case("F09", "跨任务", "所有 P0 需求", [17]),
        Case("F10", "跨任务", "涉及 VP 级决策者的客户", [12, 14]),
        Case("F11", "跨任务", "本月forecast多少", [25]),
        Case("F12", "跨任务", "所有已确认的报价", [6, 21, 29]),
        Case("F13", "跨任务", "自动续约问题", [7]),
        Case("F14", "跨任务", "3年长期合同", [10]),
        Case("F15", "跨任务", "所有关于付款条件的讨论", [3, 6, 19]),
        Case("F16", "跨任务", "涉及砍价的轮次", [5, 9, 20, 28]),
        Case("F17", "跨任务", "有哪些客户在proposal阶段", [2]),
        Case("F18", "跨任务", "negotiation阶段的商机", [23]),
        Case("F19", "跨任务", "涉及技术评估的客户", [14, 16, 17, 18]),
        Case("F20", "跨任务", "所有周报相关总结", [25, 30]),
    ]

    # ════════════════════════════════════════════════════════
    # G. 决策过程追踪 (20)
    # ════════════════════════════════════════════════════════
    cases += [
        Case("G01", "决策追踪", "PT Sentosa $45K为什么降价", [3, 5, 6]),
        Case("G02", "决策追踪", "CV XYZ 为什么选3年方案", [8, 9, 10]),
        Case("G03", "决策追踪", "华为POC为什么通过了", [15, 16]),
        Case("G04", "决策追踪", "腾讯云为什么砍到¥68万", [19, 20, 21]),
        Case("G05", "决策追踪", "比亚迪为什么这么快签约", [23, 24]),
        Case("G06", "决策追踪", "华为实施周期为什么缩短", [28, 29]),
        Case("G07", "决策追踪", "¥480万降价的原因", [27, 28, 29]),
        Case("G08", "决策追踪", "续约不涨价的理由", [8, 9, 10]),
        Case("G09", "决策追踪", "去掉实时告警的决策", [20, 21]),
        Case("G10", "决策追踪", "GraphQL 保留的决策依据", [20, 21]),
        Case("G11", "决策追踪", "PT Sentosa 最终接受了什么", [6]),
        Case("G12", "决策追踪", "腾讯云最终方案包含什么", [21]),
        Case("G13", "决策追踪", "华为最终报价确认过程", [29]),
        Case("G14", "决策追踪", "客户砍价时我们让步了什么", [5, 6, 9, 10, 20, 21, 28, 29]),
        Case("G15", "决策追踪", "哪些报价是客户先提的价格", [5, 20, 28]),
        Case("G16", "决策追踪", "折中方案是怎么谈的", [21, 29]),
        Case("G17", "决策追踪", "SLA升级为什么被砍", [8, 9]),
        Case("G18", "决策追踪", "¥60万方案缺什么功能", [20]),
        Case("G19", "决策追踪", "为什么选里程碑付款", [19]),
        Case("G20", "决策追踪", "比亚迪全款付的原因", [24]),
    ]

    # ════════════════════════════════════════════════════════
    # H. 负例验证 (20)
    # ════════════════════════════════════════════════════════
    cases += [
        Case("H01", "负例", "Amazon 的客户信息", expect_no_hit=True),
        Case("H02", "负例", "Microsoft Teams 集成", expect_no_hit=True),
        Case("H03", "负例", "阿里巴巴的商机", expect_no_hit=True),
        Case("H04", "负例", "Slack 渠道配置", expect_no_hit=True),
        Case("H05", "负例", "京东物流合同", expect_no_hit=True),
        Case("H06", "负例", "Kubernetes 部署方案", expect_no_hit=True),
        Case("H07", "负例", "AWS Lambda 费用", expect_no_hit=True),
        Case("H08", "负例", "字节跳动广告投放", expect_no_hit=True),
        Case("H09", "负例", "opp_999 不存在的商机", expect_no_hit=True),
        Case("H10", "负例", "CON-FAKE-001 假合同", expect_no_hit=True),
        Case("H11", "负例", "2024年Q1的数据", expect_no_hit=True),
        Case("H12", "负例", "招聘Java工程师", expect_no_hit=True),
        Case("H13", "负例", "公司年会策划", expect_no_hit=True),
        Case("H14", "负例", "小红书营销方案", expect_no_hit=True),
        Case("H15", "负例", "特斯拉自动驾驶", expect_no_hit=True),
        Case("H16", "负例", "GPT-5 发布时间", expect_no_hit=True),
        Case("H17", "负例", "NBA季后赛赛程", expect_no_hit=True),
        Case("H18", "负例", "iPhone 16 价格", expect_no_hit=True),
        Case("H19", "负例", "Python 3.13 新特性", expect_no_hit=True),
        Case("H20", "负例", "Docker Compose 配置", expect_no_hit=True),
    ]

    # ════════════════════════════════════════════════════════
    # I. 数据时效性 (10)
    # ════════════════════════════════════════════════════════
    cases += [
        Case("I01", "时效性", "PT Sentosa 最新报价是多少", [6]),
        Case("I02", "时效性", "CV XYZ 合同现在的状态", [10]),
        Case("I03", "时效性", "华为报价现在是多少", [29]),
        Case("I04", "时效性", "腾讯云最终确认的金额", [21]),
        Case("I05", "时效性", "比亚迪合同编号", [24]),
        Case("I06", "时效性", "pipeline当前总额", [25]),
        Case("I07", "时效性", "华为POC最终结果", [16]),
        Case("I08", "时效性", "腾讯云方案最终范围", [21]),
        Case("I09", "时效性", "华为实施周期现在是多久", [29]),
        Case("I10", "时效性", "CV XYZ 新的到期日是什么", [10]),
    ]

    # ════════════════════════════════════════════════════════
    # J. 分级返回 / full 模式 (10)
    # ════════════════════════════════════════════════════════
    cases += [
        Case("J01", "full模式", "轮次3的完整内容", mode="full", target_turn_id=3),
        Case("J02", "full模式", "轮次10的完整内容", mode="full", target_turn_id=10),
        Case("J03", "full模式", "轮次16的完整内容", mode="full", target_turn_id=16),
        Case("J04", "full模式", "轮次21的完整内容", mode="full", target_turn_id=21),
        Case("J05", "full模式", "轮次24的完整内容", mode="full", target_turn_id=24),
        Case("J06", "full模式", "轮次29的完整内容", mode="full", target_turn_id=29),
        Case("J07", "full模式", "轮次1的完整内容", mode="full", target_turn_id=1),
        Case("J08", "full模式", "轮次15的完整内容", mode="full", target_turn_id=15),
        Case("J09", "full模式", "轮次25的完整内容", mode="full", target_turn_id=25),
        Case("J10", "full模式", "轮次30的完整内容", mode="full", target_turn_id=30),
    ]

    return cases


# ═══════════════════════════════════════════════════════════
# 评测引擎
# ═══════════════════════════════════════════════════════════

@dataclass
class Result:
    case_id: str
    category: str
    passed: bool
    recall: float = 0.0
    precision: float = 0.0
    detail: str = ""

async def evaluate(service: ContextArchiveService, archive: ContextArchive, case: Case) -> Result:
    """评测单个用例"""
    try:
        r = await service.recall(
            query=case.query, mode=case.mode, top_k=10,
            target_turn_id=case.target_turn_id,
        )
    except Exception as e:
        return Result(case.id, case.category, False, detail=f"异常: {e}")

    # full 模式: 只检查是否返回了内容
    if case.mode == "full":
        has_content = bool(r.full_content) or ("完整内容" in r.formatted_output)
        return Result(case.id, case.category, has_content, 1.0 if has_content else 0.0, 1.0 if has_content else 0.0,
                      f"full模式: {'有内容' if has_content else '无内容'}")

    hit_turns = [t.turn_id for t in r.timeline]

    # 负例
    if case.expect_no_hit:
        if not hit_turns:
            return Result(case.id, case.category, True, 1.0, 1.0, "负例正确: 无命中")
        else:
            return Result(case.id, case.category, False, 0.0, 0.0, f"负例错误: 命中了 {hit_turns}")

    # 正例
    if not case.expected_turns:
        # 无具体期望轮次，只检查是否有结果
        has_result = len(hit_turns) > 0
        return Result(case.id, case.category, has_result, 1.0 if has_result else 0.0, 1.0 if has_result else 0.0,
                      f"命中: {hit_turns}")

    exp_set = set(case.expected_turns)
    hit_set = set(hit_turns)
    recall = len(exp_set & hit_set) / max(len(exp_set), 1)
    precision = len(exp_set & hit_set) / max(len(hit_set), 1) if hit_set else 0.0

    # 实体检查
    entity_ok = True
    if case.expected_entity:
        all_ents = []
        for t in r.timeline:
            all_ents.extend(t.entities)
        entity_ok = any(case.expected_entity in e for e in all_ents)

    # 时间线排序检查
    ts_list = [t.timestamp for t in r.timeline]
    sorted_ok = all(ts_list[i] <= ts_list[i+1] for i in range(len(ts_list)-1))

    # 变更检测
    change_ok = True
    if case.expect_change:
        change_ok = len(r.changes) > 0

    passed = recall >= 0.3 and entity_ok and sorted_ok and change_ok
    detail = f"R={recall:.0%} P={precision:.0%} 命中{hit_turns[:5]}{'...' if len(hit_turns)>5 else ''}"
    if case.expected_entity:
        detail += f" E:{'✓' if entity_ok else '✗'}"
    if case.expect_change:
        detail += f" Δ:{'✓' if change_ok else '✗'}"
    if not sorted_ok:
        detail += " ⚠排序"
    return Result(case.id, case.category, passed, recall, precision, detail)


async def main():
    # 初始化
    MockDAO.reset()
    _ctr[0] = 0
    archive = ContextArchive(tenant_id=1001)
    archive.set_context(tenant_id=1001, thread_id="eval_200")
    msgs = build_conversations()
    n = archive.index_messages(msgs, thread_id="eval_200")
    service = ContextArchiveService(archive)
    cases = build_cases()

    print(f"\n{'═'*70}")
    print(f"  ContextArchive 200 场景召回率评测")
    print(f"  对话: {len(msgs)} 条消息 → {n} 轮存档 | 用例: {len(cases)} 个")
    print(f"{'═'*70}\n")

    # 执行
    results: list[Result] = []
    for case in cases:
        r = await evaluate(service, archive, case)
        results.append(r)

    # 分类统计
    cats = {}
    for r in results:
        cats.setdefault(r.category, []).append(r)

    total_pass = sum(1 for r in results if r.passed)
    total = len(results)
    avg_recall = sum(r.recall for r in results) / total
    avg_precision = sum(r.precision for r in results) / total

    # 打印分类结果
    for cat, cat_results in cats.items():
        cat_pass = sum(1 for r in cat_results if r.passed)
        cat_total = len(cat_results)
        cat_recall = sum(r.recall for r in cat_results) / cat_total
        status = "✅" if cat_pass / cat_total >= 0.7 else "⚠️" if cat_pass / cat_total >= 0.5 else "❌"
        print(f"  {status} {cat:8s} | {cat_pass:2d}/{cat_total:2d} ({cat_pass/cat_total*100:4.0f}%) | Recall {cat_recall:.0%}")

        # 打印失败用例
        failures = [r for r in cat_results if not r.passed]
        for f in failures[:3]:  # 每类最多显示3个失败
            print(f"       ❌ {f.case_id}: {f.detail}")
        if len(failures) > 3:
            print(f"       ... 还有 {len(failures)-3} 个失败")
        print()

    # 总结
    print(f"{'─'*70}")
    print(f"  总计: {total_pass}/{total} 通过 ({total_pass/total*100:.1f}%)")
    print(f"  平均召回率: {avg_recall:.1%}")
    print(f"  平均精确率: {avg_precision:.1%}")
    print(f"{'─'*70}")
    print(f"\n  注: 当前为 PG 关键词降级模式（无 VDB）。")
    print(f"  接入 VDB(embedding+BM25) 后预期提升 15-25%。")
    print(f"{'═'*70}\n")

    return total_pass, total


if __name__ == "__main__":
    p, t = asyncio.run(main())
    sys.exit(0 if p / t >= 0.6 else 1)
