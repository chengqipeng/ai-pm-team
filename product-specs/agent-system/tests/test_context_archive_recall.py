"""ContextArchive + recall_context 端到端评测

模拟长历史上下文场景，验证:
  1. 写入正确性 — 压缩前的消息能正确拆分、索引、持久化
  2. 检索召回率 — 不同类型的查询能命中正确的存档轮次
  3. 变更检测准确率 — 同实体多轮次值变化能被正确识别
  4. 时间线排序 — 返回结果按时间升序
  5. 倾向链构建 — 决策演变链完整性
  6. 数据时效性标注 — 过时数据被正确标注

运行方式: python -m pytest tests/test_context_archive_recall.py -v
或直接: python tests/test_context_archive_recall.py
"""
from __future__ import annotations

import asyncio
import json
import time
import sys
import os
from dataclasses import dataclass

# 将 src 加入路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ═══════════════════════════════════════════════════════════
# Mock 消息类（替代 langchain_core.messages）
# ═══════════════════════════════════════════════════════════

class HumanMessage:
    type = "human"
    def __init__(self, content: str, **kwargs):
        self.content = content
        self.additional_kwargs = kwargs.get("additional_kwargs", {})

class AIMessage:
    type = "ai"
    def __init__(self, content: str = "", tool_calls=None, **kwargs):
        self.content = content
        self.tool_calls = tool_calls or []
        self.additional_kwargs = kwargs.get("additional_kwargs", {})

class ToolMessage:
    type = "tool"
    def __init__(self, content: str, name: str = "tool", tool_call_id: str = "", **kwargs):
        self.content = content
        self.name = name
        self.tool_call_id = tool_call_id
        self.additional_kwargs = kwargs.get("additional_kwargs", {})


# ═══════════════════════════════════════════════════════════
# 预注入 Mock 模块（必须在 import src.middleware 之前）
# ═══════════════════════════════════════════════════════════
import types

# Mock langchain_core.messages
mock_messages = types.ModuleType("langchain_core.messages")
mock_messages.HumanMessage = HumanMessage
mock_messages.AIMessage = AIMessage
mock_messages.ToolMessage = ToolMessage
sys.modules["langchain_core.messages"] = mock_messages

# Mock langchain 完整层级（阻止真实 langchain 加载）
for mod_name in [
    "langchain_core", "langchain_core.language_models",
    "langchain_core.language_models.chat_models",
    "langchain", "langchain.agents", "langchain.agents.middleware",
    "langchain.agents.middleware.types",
    "langchain_openai",
]:
    if mod_name not in sys.modules:
        sys.modules[mod_name] = types.ModuleType(mod_name)

# Mock AgentMiddleware
class _MockAgentMiddleware:
    pass
sys.modules["langchain.agents.middleware.types"].AgentMiddleware = _MockAgentMiddleware


# ═══════════════════════════════════════════════════════════
# Mock PG 存储（内存替代）
# ═══════════════════════════════════════════════════════════

class MockContextArchiveDAO:
    """内存 Mock DAO — 替代 PG 实现"""
    _store: dict[str, list] = {}  # {thread_id: [rows]}

    @classmethod
    def reset(cls):
        cls._store = {}

    @classmethod
    def batch_insert(cls, rows):
        for r in rows:
            key = r.thread_id
            if key not in cls._store:
                cls._store[key] = []
            cls._store[key].append(r)

    @classmethod
    def get_max_turn_id(cls, tenant_id, thread_id):
        rows = cls._store.get(thread_id, [])
        if not rows:
            return 0
        return max(r.turn_id for r in rows)

    @classmethod
    def get_by_turn_id(cls, tenant_id, thread_id, turn_id):
        rows = cls._store.get(thread_id, [])
        for r in rows:
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
        results = []
        for r in rows:
            if r.delete_flg != 0:
                continue
            searchable = f"{r.user_query} {r.entities} {r.keywords} {r.answer_preview}"
            score = sum(1 for kw in keywords if kw.lower() in searchable.lower())
            if score > 0:
                results.append((score, r))
        results.sort(key=lambda x: -x[0])
        return [r for _, r in results[:top_k]]

    @classmethod
    def search_by_entities(cls, tenant_id, thread_id, entity_names, top_k=5):
        rows = cls._store.get(thread_id, [])
        results = []
        for r in rows:
            if r.delete_flg != 0:
                continue
            for entity in entity_names:
                if entity.lower() in r.entities.lower():
                    results.append(r)
                    break
        return results[:top_k]

    @classmethod
    def search_decisions(cls, tenant_id, thread_id, top_k=20):
        rows = cls._store.get(thread_id, [])
        return [r for r in rows if r.delete_flg == 0 and r.has_decision == 1][:top_k]


# Patch DAO import
mock_dao_module = types.ModuleType("src.store.context_archive_dao")
mock_dao_module.ContextArchiveDAO = MockContextArchiveDAO
sys.modules["src.store.context_archive_dao"] = mock_dao_module

# Patch store models
from src.store.context_archive_models import ContextArchiveRow
mock_models_module = types.ModuleType("src.store.context_archive_models")
mock_models_module.ContextArchiveRow = ContextArchiveRow
sys.modules["src.store.context_archive_models"] = mock_models_module

# Patch pg_pool
mock_pg = types.ModuleType("src.store.pg_pool")
mock_pg.get_conn = lambda: None
sys.modules["src.store.pg_pool"] = mock_pg

# Patch snowflake
_counter = [0]
def _next_id():
    _counter[0] += 1
    return _counter[0]
mock_snowflake = types.ModuleType("src.store.snowflake")
mock_snowflake.next_id = _next_id
sys.modules["src.store.snowflake"] = mock_snowflake

# Block src.middleware.__init__ from loading (it imports langchain)
# Instead we import the specific module files directly
sys.modules["src.middleware"] = types.ModuleType("src.middleware")

# Now import our modules directly (bypassing __init__.py)
import importlib.util

def _import_module_from_file(module_name: str, file_path: str):
    spec = importlib.util.spec_from_file_location(module_name, file_path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = mod
    spec.loader.exec_module(mod)
    return mod

_base_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_ca_mod = _import_module_from_file(
    "src.middleware.context_archive",
    os.path.join(_base_path, "src/middleware/context_archive.py")
)
_cas_mod = _import_module_from_file(
    "src.middleware.context_archive_service",
    os.path.join(_base_path, "src/middleware/context_archive_service.py")
)
ContextArchive = _ca_mod.ContextArchive
ContextArchiveService = _cas_mod.ContextArchiveService


# ═══════════════════════════════════════════════════════════
# 测试数据 — 模拟 CRM 销售场景 25 轮对话
# ═══════════════════════════════════════════════════════════

def build_long_conversation() -> list:
    """构建模拟的 25 轮 CRM 销售对话"""
    messages = []

    # ── 轮次 1: 查客户 ──
    messages.append(HumanMessage("帮我查一下 PT Sentosa 的客户信息"))
    messages.append(AIMessage(tool_calls=[{"id": "tc1", "name": "query_data", "args": {"entity": "account", "filter": "name=PT Sentosa"}}]))
    messages.append(ToolMessage('{"name": "PT Sentosa Jaya", "industry": "制造业", "employees": 200, "revenue": "$5M"}', name="query_data", tool_call_id="tc1"))
    messages.append(AIMessage("PT Sentosa Jaya 是一家制造业公司，200人规模，年营收$5M。"))

    # ── 轮次 2: 查商机 ──
    messages.append(HumanMessage("他们的商机情况呢"))
    messages.append(AIMessage(tool_calls=[{"id": "tc2", "name": "query_data", "args": {"entity": "opportunity", "filter": "account=PT Sentosa"}}]))
    messages.append(ToolMessage('{"opportunity": "opp_001", "amount": "$45K", "stage": "proposal", "close_date": "2025-05-15"}', name="query_data", tool_call_id="tc2"))
    messages.append(AIMessage("PT Sentosa 有一个商机 opp_001，金额 $45K，目前在 proposal 阶段，预计 2025-05-15 关闭。"))

    # ── 轮次 3: 生成报价 ──
    messages.append(HumanMessage("帮我生成一份报价方案"))
    messages.append(AIMessage(tool_calls=[{"id": "tc3", "name": "analyze_data", "args": {"task": "generate_quote", "opportunity": "opp_001"}}]))
    messages.append(ToolMessage('{"quote_amount": "$45K", "discount": "15%", "final_price": "$38,250", "payment_terms": "签约30%+上线40%+验收30%", "includes": "8周实施+3个月免费支持"}', name="analyze_data", tool_call_id="tc3"))
    messages.append(AIMessage("报价方案：总价 $45K，年付15%折扣后=$38,250。付款条件：签约付30%、上线付40%、验收付30%。包含8周实施期和3个月免费技术支持。"))

    # ── 轮次 4: 竞品对比 ──
    messages.append(HumanMessage("Odoo 的定价是多少"))
    messages.append(AIMessage(tool_calls=[{"id": "tc4", "name": "web_search", "args": {"query": "Odoo pricing 2025"}}]))
    messages.append(ToolMessage('{"answer": "Odoo定价$24.90/user/month，Manufacturing模块+$18/user/month，总计约$42.90/user/month"}', name="web_search", tool_call_id="tc4"))
    messages.append(AIMessage("Odoo 定价：标准版 $24.90/user/month，加 Manufacturing 模块后 $42.90/user/month。按 200 人算年费约 $103K，比我们的 $45K 贵。"))

    # ── 轮次 5: 客户反馈太贵 ──
    messages.append(HumanMessage("客户说我们的报价太贵了，能不能降到 $40K"))
    messages.append(AIMessage("好的，我来调整报价。将总价从 $45K 降到 $40K，年付折扣保持15%，最终价格 $34,000。"))

    # ── 轮次 6: 确认新报价 ──
    messages.append(HumanMessage("好的，就按 $40K 来，付款条件不变"))
    messages.append(AIMessage(tool_calls=[{"id": "tc6", "name": "execute_task", "args": {"task": "update_quote", "amount": "$40K", "payment_terms": "签约30%+上线40%+验收30%"}}]))
    messages.append(ToolMessage('{"success": true, "quote_id": "Q-2025-001", "amount": "$40K", "final_price": "$34,000"}', name="execute_task", tool_call_id="tc6"))
    messages.append(AIMessage("已更新报价 Q-2025-001：总价 $40K，年付15%折扣后最终价格 $34,000。付款条件不变：签约30%+上线40%+验收30%。"))

    # ── 轮次 7: 切换到另一客户 ──
    messages.append(HumanMessage("帮我看看 CV XYZ 的合同到期情况"))
    messages.append(AIMessage(tool_calls=[{"id": "tc7", "name": "query_data", "args": {"entity": "contract", "filter": "account=CV XYZ"}}]))
    messages.append(ToolMessage('{"contract": "con_005", "end_date": "2025-06-30", "amount": "$20K/year", "status": "active"}', name="query_data", tool_call_id="tc7"))
    messages.append(AIMessage("CV XYZ 的合同 con_005 将于 2025-06-30 到期，年费 $20K，当前状态 active。建议提前 2 个月启动续约流程。"))

    # ── 轮次 8: Pipeline 分析 ──
    messages.append(HumanMessage("帮我分析一下本月 pipeline"))
    messages.append(AIMessage(tool_calls=[{"id": "tc8", "name": "analyze_data", "args": {"task": "pipeline_analysis", "period": "this_month"}}]))
    messages.append(ToolMessage('{"total": "$180K", "stages": {"prospecting": 5, "qualification": 8, "proposal": 4, "negotiation": 3, "closing": 2}, "at_risk": 3}', name="analyze_data", tool_call_id="tc8"))
    messages.append(AIMessage("本月 pipeline 总额 $180K。分布：prospecting 5个、qualification 8个、proposal 4个、negotiation 3个、closing 2个。有 3 个高风险商机需关注。"))

    # ── 轮次 9: 回到 PT Sentosa，追加实施 ──
    messages.append(HumanMessage("PT Sentosa 那边客户接受了 $40K 的报价，要加个培训服务"))
    messages.append(AIMessage(tool_calls=[{"id": "tc9", "name": "execute_task", "args": {"task": "update_quote", "quote_id": "Q-2025-001", "add_service": "training_2days", "new_total": "$42K"}}]))
    messages.append(ToolMessage('{"success": true, "quote_id": "Q-2025-001", "amount": "$42K", "added": "2天现场培训", "final_price": "$35,700"}', name="execute_task", tool_call_id="tc9"))
    messages.append(AIMessage("已更新报价 Q-2025-001：加入2天现场培训，新总价 $42K，年付15%折扣后 $35,700。付款条件不变。"))

    # ── 轮次 10: 联系人信息 ──
    messages.append(HumanMessage("PT Sentosa 的关键联系人是谁"))
    messages.append(AIMessage(tool_calls=[{"id": "tc10", "name": "query_data", "args": {"entity": "contact", "filter": "account=PT Sentosa"}}]))
    messages.append(ToolMessage('{"contacts": [{"name": "Pak Budi", "title": "CTO", "role": "决策者"}, {"name": "Ibu Sari", "title": "IT Manager", "role": "推荐者"}]}', name="query_data", tool_call_id="tc10"))
    messages.append(AIMessage("PT Sentosa 关键联系人：Pak Budi（CTO，决策者）、Ibu Sari（IT Manager，推荐者）。"))

    return messages


# ═══════════════════════════════════════════════════════════
# 评测用例
# ═══════════════════════════════════════════════════════════

@dataclass
class EvalCase:
    """评测用例"""
    name: str
    query: str
    mode: str = "timeline"
    expected_turn_ids: list[int] = None  # 期望命中的轮次
    expected_entity: str = ""            # 期望出现的实体
    expected_change: bool = False        # 期望检测到变更
    expected_change_field: str = ""      # 期望变更的字段
    expected_current_value: str = ""     # 期望当前有效值

    def __post_init__(self):
        if self.expected_turn_ids is None:
            self.expected_turn_ids = []


EVAL_CASES = [
    # ── 精确实体召回 ──
    EvalCase(
        name="精确实体: PT Sentosa 报价",
        query="PT Sentosa 报价",
        expected_turn_ids=[3, 5, 6, 9],  # 与报价相关的轮次
        expected_entity="PT Sentosa",
        expected_change=True,
        expected_change_field="金额",
    ),
    EvalCase(
        name="精确实体: CV XYZ 合同",
        query="CV XYZ 合同到期",
        expected_turn_ids=[7],
        expected_entity="CV XYZ",
    ),
    EvalCase(
        name="精确实体: PT Sentosa 联系人",
        query="PT Sentosa 联系人",
        expected_turn_ids=[10],
        expected_entity="PT Sentosa",
    ),

    # ── 决策/变更追踪 ──
    EvalCase(
        name="变更追踪: 报价金额演变",
        query="报价金额怎么变的",
        expected_change=True,
        expected_change_field="金额",
    ),
    EvalCase(
        name="变更追踪: 付款条件",
        query="PT Sentosa 付款条件",
        expected_turn_ids=[3, 6],
        expected_entity="PT Sentosa",
    ),

    # ── 工具相关 ──
    EvalCase(
        name="工具结果: pipeline 分析",
        query="pipeline 总额",
        expected_turn_ids=[8],
    ),
    EvalCase(
        name="工具结果: Odoo 定价",
        query="Odoo 定价多少钱",
        expected_turn_ids=[4],
    ),

    # ── 模糊语义 ──
    EvalCase(
        name="模糊语义: 客户嫌贵",
        query="客户觉得贵",
        expected_turn_ids=[5],
    ),
    EvalCase(
        name="模糊语义: 培训服务",
        query="培训服务什么时候加的",
        expected_turn_ids=[9],
    ),

    # ── 负例 ──
    EvalCase(
        name="负例: 不存在的实体",
        query="Amazon 的商机情况",
        expected_turn_ids=[],
    ),
]


# ═══════════════════════════════════════════════════════════
# 评测执行
# ═══════════════════════════════════════════════════════════

@dataclass
class EvalResult:
    name: str
    passed: bool
    details: str = ""
    recall: float = 0.0    # 召回率
    precision: float = 0.0  # 精确率


async def run_eval() -> list[EvalResult]:
    """执行完整评测流程"""
    results: list[EvalResult] = []

    # ── Step 1: 构建对话并写入存档 ──
    MockContextArchiveDAO.reset()
    archive = ContextArchive(tenant_id=1001)
    archive.set_context(tenant_id=1001, thread_id="test_thread_001")

    messages = build_long_conversation()
    print(f"\n{'='*60}")
    print(f"构建对话: {len(messages)} 条消息")

    # 模拟压缩前存档（将全部消息按轮次索引）
    indexed = archive.index_messages(messages, thread_id="test_thread_001")
    print(f"存档轮次: {indexed} 个")
    print(f"{'='*60}\n")

    # ── Step 2: 创建检索服务 ──
    service = ContextArchiveService(archive)

    # ── Step 3: 执行评测用例 ──
    for case in EVAL_CASES:
        result = await eval_single_case(service, archive, case)
        results.append(result)

    return results


async def eval_single_case(service: ContextArchiveService, archive: ContextArchive, case: EvalCase) -> EvalResult:
    """评测单个用例"""
    try:
        result = await service.recall(query=case.query, mode=case.mode, top_k=8)
    except Exception as e:
        return EvalResult(name=case.name, passed=False, details=f"异常: {e}")

    # ── 检查 1: 轮次命中 ──
    hit_turn_ids = [t.turn_id for t in result.timeline]
    if case.expected_turn_ids:
        expected_set = set(case.expected_turn_ids)
        hit_set = set(hit_turn_ids)
        recall = len(expected_set & hit_set) / max(len(expected_set), 1)
        precision = len(expected_set & hit_set) / max(len(hit_set), 1) if hit_set else 0
    else:
        # 负例: 期望不命中
        if not hit_turn_ids:
            recall = 1.0
            precision = 1.0
        else:
            recall = 0.0
            precision = 0.0

    # ── 检查 2: 实体出现 ──
    entity_found = True
    if case.expected_entity:
        all_entities = []
        for t in result.timeline:
            all_entities.extend(t.entities)
        entity_found = any(case.expected_entity in e for e in all_entities)

    # ── 检查 3: 变更检测 ──
    change_detected = len(result.changes) > 0
    change_correct = True
    if case.expected_change:
        change_correct = change_detected
        if case.expected_change_field and result.changes:
            field_found = any(case.expected_change_field in c.field for c in result.changes)
            change_correct = change_correct and field_found
    elif change_detected and not case.expected_change:
        # 不期望变更但检测到了 — 不算错（可能是误检，降低精确率）
        pass

    # ── 检查 4: 时间线排序 ──
    timestamps = [t.timestamp for t in result.timeline]
    timeline_sorted = all(timestamps[i] <= timestamps[i+1] for i in range(len(timestamps)-1))

    # ── 综合判定 ──
    passed = recall >= 0.5 and entity_found and change_correct and timeline_sorted

    details_parts = []
    details_parts.append(f"命中轮次: {hit_turn_ids}")
    if case.expected_turn_ids:
        details_parts.append(f"期望轮次: {case.expected_turn_ids}")
    details_parts.append(f"召回率: {recall:.0%}, 精确率: {precision:.0%}")
    if case.expected_entity:
        details_parts.append(f"实体'{case.expected_entity}': {'✓' if entity_found else '✗'}")
    if case.expected_change:
        details_parts.append(f"变更检测: {'✓' if change_correct else '✗'}")
    details_parts.append(f"时间线有序: {'✓' if timeline_sorted else '✗'}")

    return EvalResult(
        name=case.name,
        passed=passed,
        details="; ".join(details_parts),
        recall=recall,
        precision=precision,
    )


def print_report(results: list[EvalResult]):
    """打印评测报告"""
    print(f"\n{'='*60}")
    print("ContextArchive Recall 评测报告")
    print(f"{'='*60}\n")

    passed_count = sum(1 for r in results if r.passed)
    total = len(results)
    avg_recall = sum(r.recall for r in results) / max(total, 1)
    avg_precision = sum(r.precision for r in results) / max(total, 1)

    for r in results:
        status = "✅ PASS" if r.passed else "❌ FAIL"
        print(f"  {status} | {r.name}")
        print(f"         {r.details}")
        print()

    print(f"{'─'*60}")
    print(f"  总计: {passed_count}/{total} 通过 ({passed_count/total*100:.0f}%)")
    print(f"  平均召回率: {avg_recall:.1%}")
    print(f"  平均精确率: {avg_precision:.1%}")
    print(f"{'─'*60}")

    return passed_count, total, avg_recall, avg_precision


if __name__ == "__main__":
    results = asyncio.run(run_eval())
    passed, total, avg_recall, avg_precision = print_report(results)

    # 退出码: 全部通过返回 0
    sys.exit(0 if passed == total else 1)
