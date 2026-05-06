"""目录级聚合 Demo — 多条 L2 → 聚合 L1 → 压缩 L0

模拟 CRM 销售场景：多轮对话逐步积累客户洞察，
然后展示目录级聚合效果（对齐 apps-agent v2 的 L0/L1/L2 架构）。

运行:
  cd product-specs/agent-system
  .venv/bin/python -B tests/test_directory_aggregate_demo.py
"""
import asyncio
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("DOUBAO_API_KEY", "651621e7-e495-4728-93ef-ed380e9ddcd1")

from langchain_core.messages import HumanMessage, AIMessage


def _llm():
    from langchain_openai import ChatOpenAI
    return ChatOpenAI(
        model="doubao-1-5-pro-32k-250115",
        api_key=os.environ["DOUBAO_API_KEY"],
        base_url="https://ark.cn-beijing.volces.com/api/v3/",
        max_tokens=2048,
    )


def _engine():
    from src.memory.viking_engine import VikingMemoryEngine
    return VikingMemoryEngine(
        vdb_url="http://10.60.2.17",
        vdb_key="bRG3NETg13tv5Fn68VTdkxaJXH9tMQzhKeT3unck",
        vdb_username="root",
        database_name="viking_agg_demo",
        collection_name="agg_demo_v1",
        llm=_llm(),
        use_pg=False,
    )


UID = "sales_wang"

# ═══════════════════════════════════════════════════════════
# 模拟 7 轮对话，逐步积累记忆
# ═══════════════════════════════════════════════════════════

CONVERSATIONS = [
    # 轮次 1: 华为 — 联系人沟通风格
    ("上次和华为张伟开会，这个人说话很直接，不喜欢绕弯子，给他汇报最好用PPT带数据",
     "了解，张伟偏好直接沟通，汇报用PPT配数据。"),

    # 轮次 2: 华为 — 内部关系
    ("华为那边张伟和李娜意见不太一致，张伟想上ERP但李娜觉得预算不够，需要分别沟通",
     "了解，张伟和李娜在ERP项目上有分歧。张伟支持上ERP，李娜担心预算。建议分别沟通。"),

    # 轮次 3: 华为 — 审批流程
    ("华为的采购流程特别长，IT部门同意了还要过采购委员会，一般要3到4周",
     "了解，华为采购流程需要3-4周，IT部门之后还有采购委员会审批。签约前需要预留足够时间。"),

    # 轮次 4: 华为 — 报价策略
    ("华为ERP项目报价的时候不要一次报到底，先报个标准价，等他们还价再给折扣，张伟喜欢有谈判的感觉",
     "了解，华为ERP报价策略：先标准价，预留谈判空间。张伟喜欢有谈判的感觉。"),

    # 轮次 5: 腾讯 — 竞争情报
    ("听说腾讯那边也在看数据中台方案，他们同时在评估我们和用友的产品，王强比较倾向我们但他老板更看重价格",
     "了解竞争态势。腾讯在评估我们和用友，王强倾向我们但高层看重价格。"),

    # 轮次 6: 腾讯 — 时间窗口
    ("腾讯王强最近在忙集团的组织架构调整，估计这个月没时间看我们的方案，下个月再跟进",
     "了解，腾讯王强本月忙于组织架构调整，建议下月再跟进。"),

    # 轮次 7: 用户偏好
    ("以后数据都用表格展示，不要图表。金额统一用万为单位。回复简洁不超过100字",
     "好的，已记录三个偏好：表格展示、金额用万、简洁回复不超过100字。"),
]


async def main():
    e = _engine()

    # ── Phase 1: 逐轮写入记忆 ──
    print("=" * 65)
    print("  Phase 1: 模拟 7 轮对话，逐步积累记忆")
    print("=" * 65)

    all_items = []
    for i, (q, a) in enumerate(CONVERSATIONS):
        r = await e.extract_and_update(
            [HumanMessage(content=q), AIMessage(content=a)],
            thread_id=f"conv-{i+1}", user_id=UID,
        )
        print(f"\n  轮次 {i+1}: {q[:40]}...")
        for item in r.items:
            cat = item.metadata.get("category", "?")
            print(f"    → [{cat}] {item.content}")
            all_items.append(item)
        await asyncio.sleep(0.3)

    print(f"\n  共积累 {len(all_items)} 条 L2 记忆")
    time.sleep(5)  # 等待向量库索引

    # ── Phase 2: 展示单条记忆级别的 L0/L1/L2 ──
    print(f"\n{'=' * 65}")
    print("  Phase 2: 单条记忆级别（当前架构）")
    print("=" * 65)

    memories = e.list_memories(UID, limit=20)
    by_parent: dict[str, list] = {}
    for m in memories:
        pe = m.get("parent_entity", "") or "（无父实体）"
        by_parent.setdefault(pe, []).append(m)

    for parent, items in sorted(by_parent.items()):
        print(f"\n  📁 {parent} ({len(items)} 条)")
        for m in items:
            print(f"    📄 L0: {m.get('abstract', '')[:60]}")
            if m.get("overview"):
                print(f"       L1: {m.get('overview', '')[:60]}...")
            print(f"       L2: {m.get('content', '')[:60]}...")

    # ── Phase 3: 目录级聚合 ──
    print(f"\n{'=' * 65}")
    print("  Phase 3: 目录级聚合（对齐 v2 架构）")
    print("=" * 65)

    # 收集所有 parent_entity
    parents = set()
    for m in memories:
        pe = m.get("parent_entity", "")
        if pe:
            parents.add(pe)

    for parent in sorted(parents):
        print(f"\n  {'─' * 60}")
        print(f"  📁 {parent}")
        print(f"  {'─' * 60}")

        agg = await e.aggregate_directory(UID, "entities", parent)

        # 展示 L2 条目
        print(f"\n  L2 条目 ({agg['l2_count']} 条):")
        for item in agg.get("l2_items", []):
            mk = item.get("merge_key", "")
            print(f"    • [{mk}] {item.get('content', '')[:70]}")

        # 展示聚合的 L1
        print(f"\n  目录级 L1（从 {agg['l2_count']} 条 L2 聚合）:")
        for line in agg["l1"].split("\n"):
            if line.strip():
                print(f"    {line}")

        # 展示聚合的 L0
        print(f"\n  目录级 L0（从 L1 压缩）:")
        print(f"    {agg['l0']}")

    # ── Phase 4: 整体聚合 ──
    print(f"\n{'=' * 65}")
    print("  Phase 4: 全量目录聚合")
    print("=" * 65)

    all_agg = await e.aggregate_all_directories(UID)
    for path, agg in sorted(all_agg.items()):
        print(f"\n  📁 {path} ({agg['l2_count']} 条 L2)")
        print(f"     L0: {agg['l0'][:80]}")

    # ── Phase 5: 对比展示 ──
    print(f"\n{'=' * 65}")
    print("  Phase 5: 架构对比")
    print("=" * 65)

    print(f"""
  当前架构（单条记忆级）:
    每条记忆独立存储，各自有 L0/L1/L2
    检索时: embed(单条L0) → cosine search → 返回匹配的单条记忆
    优势: 检索精确，更新简单
    劣势: 没有全貌视图

  v2 架构（目录级）:
    L2 是独立记忆条目（多条）
    L1 是从所有 L2 聚合的结构化目录（1条）
    L0 是从 L1 压缩的一句话摘要（1条）
    优势: 全貌视图，token 效率高
    劣势: L2 变更时需要重新聚合

  混合架构（当前实现）:
    存储: 保持单条记忆结构（不改）
    聚合: aggregate_directory() 按需生成目录级 L0/L1
    效果: 兼得两者优势
    """)

    print("=" * 65)
    print("  Demo 完成")
    print("=" * 65)


if __name__ == "__main__":
    asyncio.run(main())
