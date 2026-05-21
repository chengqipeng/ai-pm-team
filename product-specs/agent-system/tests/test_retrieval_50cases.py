"""50 个场景化检索验证 — 写入测试数据 + 执行查询 + 验证结果

运行:
  cd product-specs/agent-system
  .venv/bin/python3 tests/test_retrieval_50cases.py
"""
from __future__ import annotations

import asyncio
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("DEEPSEEK_API_KEY", "sk-HdY98AcN68JhtXLp8oeIATEL4PWq9rzRcCAhI8G4SOtBbtSw")


# ═══════════════════════════════════════════════════════════
# 测试数据
# ═══════════════════════════════════════════════════════════

TEST_USER_ID = "test_retrieval_50"
TEST_COLLECTION = "agent_memories"

# 目录节点
DIRECTORIES = [
    {
        "id": "dir_huawei", "category": "entities", "merge_key": "华为科技",
        "parent_entity": "", "is_leaf": "false", "status": "active",
        "abstract": "华为科技: 张伟说话直接喜欢PPT，ERP项目内部有分歧，审批流程至少3-4周",
        "overview": "## 联系人洞察\n- 张伟: 说话直接，汇报用PPT\n- 李娜: 新技术对接人\n## 商机洞察\n- ERP项目: 内部有分歧\n## 内部流程\n- 审批: IT部门→采购委员会，3-4周",
        "content": "",
        "uri": "viking://user/memories/entities/华为科技/",
        "parent_uri": "viking://user/memories/entities/",
    },
    {
        "id": "dir_tencent", "category": "entities", "merge_key": "腾讯",
        "parent_entity": "", "is_leaf": "false", "status": "active",
        "abstract": "腾讯: 王总决策风格保守，云项目预算紧张，喜欢看ROI数据",
        "overview": "## 联系人\n- 王总: 决策保守，需数据支撑\n## 商机\n- 云项目: 预算紧张，要求POC",
        "content": "",
        "uri": "viking://user/memories/entities/腾讯/",
        "parent_uri": "viking://user/memories/entities/",
    },
    {
        "id": "dir_xiaomi", "category": "entities", "merge_key": "小米",
        "parent_entity": "", "is_leaf": "false", "status": "active",
        "abstract": "小米: IoT项目张总是决策人，预计Q3签约，内部流程快",
        "overview": "## 联系人\n- 张总: 技术背景\n## 商机\n- IoT项目: Q3签约",
        "content": "",
        "uri": "viking://user/memories/entities/小米/",
        "parent_uri": "viking://user/memories/entities/",
    },
]

# 叶子节点
LEAVES = [
    {
        "id": "mem_hw_zhangwei", "category": "entities", "merge_key": "华为科技/张伟",
        "parent_entity": "华为科技", "is_leaf": "true", "status": "active",
        "abstract": "华为科技/张伟: 说话直接不绕弯子，汇报用PPT带数据，开会控制30分钟",
        "content": "张伟说话直接不绕弯子，汇报时喜欢用PPT带数据，每次开会控制在30分钟以内。建议和他沟通时直接说重点，不要铺垫太多。",
        "uri": "viking://user/memories/entities/华为科技/张伟",
        "parent_uri": "viking://user/memories/entities/华为科技/",
    },
    {
        "id": "mem_hw_erp", "category": "entities", "merge_key": "华为科技/ERP项目",
        "parent_entity": "华为科技", "is_leaf": "true", "status": "active",
        "abstract": "华为科技/ERP项目: 张伟和李娜意见有分歧，建议分别沟通",
        "content": "华为科技ERP项目中张伟和李娜意见有分歧，张伟倾向方案A，李娜倾向方案B。建议分别沟通，了解各自顾虑后再统一。",
        "uri": "viking://user/memories/entities/华为科技/ERP项目",
        "parent_uri": "viking://user/memories/entities/华为科技/",
    },
    {
        "id": "mem_hw_approval", "category": "entities", "merge_key": "华为科技/审批流程",
        "parent_entity": "华为科技", "is_leaf": "true", "status": "active",
        "abstract": "华为科技/审批流程: IT部门后还需采购委员会，至少3-4周",
        "content": "华为内部审批流程复杂，先过IT部门评审，再过采购委员会审批，整个流程至少需要3-4周。建议提前准备材料。",
        "uri": "viking://user/memories/entities/华为科技/审批流程",
        "parent_uri": "viking://user/memories/entities/华为科技/",
    },
    {
        "id": "mem_hw_lina", "category": "entities", "merge_key": "华为科技/李娜",
        "parent_entity": "华为科技", "is_leaf": "true", "status": "active",
        "abstract": "华为科技/李娜: 新的技术对接人，替代张伟负责技术方案对接",
        "content": "李娜是华为科技新的技术对接人，替代张伟负责技术方案对接工作。所有技术方案文档发给李娜。",
        "uri": "viking://user/memories/entities/华为科技/李娜",
        "parent_uri": "viking://user/memories/entities/华为科技/",
    },
    {
        "id": "mem_tc_wang", "category": "entities", "merge_key": "腾讯/王总",
        "parent_entity": "腾讯", "is_leaf": "true", "status": "active",
        "abstract": "腾讯/王总: 决策风格保守，需要充分数据支撑，不喜欢冒险",
        "content": "腾讯王总决策风格保守，做决定前需要充分的数据支撑和ROI分析，不喜欢冒险。建议准备详细的数据报告。",
        "uri": "viking://user/memories/entities/腾讯/王总",
        "parent_uri": "viking://user/memories/entities/腾讯/",
    },
    {
        "id": "mem_tc_cloud", "category": "entities", "merge_key": "腾讯/云项目",
        "parent_entity": "腾讯", "is_leaf": "true", "status": "active",
        "abstract": "腾讯/云项目: 预算紧张，要求先做POC验证效果再决定",
        "content": "腾讯云项目预算紧张，王总要求先做小规模POC验证效果，看到明确ROI后再决定是否全面推进。",
        "uri": "viking://user/memories/entities/腾讯/云项目",
        "parent_uri": "viking://user/memories/entities/腾讯/",
    },
    {
        "id": "mem_xm_iot", "category": "entities", "merge_key": "小米/IoT项目",
        "parent_entity": "小米", "is_leaf": "true", "status": "active",
        "abstract": "小米/IoT项目: 张总是决策人，预计Q3签约，内部流程快",
        "content": "小米IoT项目张总是最终决策人，项目预计Q3签约。小米内部流程比较快，审批周期短。",
        "uri": "viking://user/memories/entities/小米/IoT项目",
        "parent_uri": "viking://user/memories/entities/小米/",
    },
    {
        "id": "mem_xm_zhang", "category": "entities", "merge_key": "小米/张总",
        "parent_entity": "小米", "is_leaf": "true", "status": "active",
        "abstract": "小米/张总: 技术背景，喜欢看技术方案细节，关注性能指标",
        "content": "小米张总有技术背景，喜欢看技术方案的细节，特别关注性能指标和技术架构。",
        "uri": "viking://user/memories/entities/小米/张总",
        "parent_uri": "viking://user/memories/entities/小米/",
    },
    {
        "id": "mem_pref_display", "category": "preferences", "merge_key": "数据展示/格式偏好",
        "parent_entity": "数据展示", "is_leaf": "true", "status": "active",
        "abstract": "数据展示/格式偏好: 重要数据用图表展示，辅助数据用表格",
        "content": "用户偏好重要数据用图表展示更直观，辅助数据用表格呈现。",
        "uri": "viking://user/memories/preferences/数据展示/格式偏好",
        "parent_uri": "viking://user/memories/preferences/数据展示/",
    },
    {
        "id": "mem_pref_time", "category": "preferences", "merge_key": "数据查看/时间习惯",
        "parent_entity": "数据查看", "is_leaf": "true", "status": "active",
        "abstract": "数据查看/时间习惯: 每周一早上查看上周数据总结",
        "content": "用户习惯每周一早上查看上周的数据总结。",
        "uri": "viking://user/memories/preferences/数据查看/时间习惯",
        "parent_uri": "viking://user/memories/preferences/数据查看/",
    },
]

# 查询用例（前 20 个先跑）
QUERIES = [
    # 第一组：精确客户名匹配
    {"id": 1, "query": "华为的情况", "expect_ids": ["dir_huawei", "mem_hw_zhangwei", "mem_hw_erp", "mem_hw_approval"]},
    {"id": 2, "query": "腾讯的情况", "expect_ids": ["dir_tencent", "mem_tc_wang", "mem_tc_cloud"]},
    {"id": 3, "query": "小米的项目", "expect_ids": ["dir_xiaomi", "mem_xm_iot", "mem_xm_zhang"]},
    {"id": 4, "query": "华为张伟", "expect_ids": ["mem_hw_zhangwei", "dir_huawei"]},
    {"id": 5, "query": "腾讯王总", "expect_ids": ["mem_tc_wang", "dir_tencent"]},
    # 第二组：联系人查询
    {"id": 6, "query": "张伟是什么风格", "expect_ids": ["mem_hw_zhangwei"]},
    {"id": 7, "query": "和张伟开会要注意什么", "expect_ids": ["mem_hw_zhangwei"]},
    {"id": 8, "query": "王总的决策风格", "expect_ids": ["mem_tc_wang"]},
    {"id": 9, "query": "李娜是谁", "expect_ids": ["mem_hw_lina"]},
    {"id": 10, "query": "华为的技术对接人", "expect_ids": ["mem_hw_lina"]},
    # 第三组：商机/项目查询
    {"id": 11, "query": "ERP项目怎么样了", "expect_ids": ["mem_hw_erp"]},
    {"id": 12, "query": "华为ERP项目的分歧", "expect_ids": ["mem_hw_erp"]},
    {"id": 13, "query": "云项目的预算", "expect_ids": ["mem_tc_cloud"]},
    {"id": 14, "query": "IoT项目什么时候签约", "expect_ids": ["mem_xm_iot"]},
    {"id": 15, "query": "哪个项目有分歧", "expect_ids": ["mem_hw_erp"]},
    # 第四组：流程/策略
    {"id": 16, "query": "华为的审批要多久", "expect_ids": ["mem_hw_approval"]},
    {"id": 17, "query": "决策保守的客户", "expect_ids": ["mem_tc_wang", "dir_tencent"]},
    {"id": 18, "query": "喜欢看数据的联系人", "expect_ids": ["mem_tc_wang", "mem_xm_zhang"]},
    {"id": 19, "query": "需要做POC的项目", "expect_ids": ["mem_tc_cloud"]},
    {"id": 20, "query": "我的数据展示偏好", "expect_ids": ["mem_pref_display"]},
]


async def run_test():
    from src.memory.viking_engine import VikingMemoryEngine
    from langchain_openai import OpenAIEmbeddings

    print("=" * 70)
    print("50 场景检索验证 — 写入测试数据 + 执行查询")
    print("=" * 70)

    # 初始化引擎
    emb = OpenAIEmbeddings(
        model="doubao-embedding-text-240715",
        api_key=os.environ.get("EMBEDDING_API_KEY", "651621e7-e495-4728-93ef-ed380e9ddcd1"),
        base_url="https://ark.cn-beijing.volces.com/api/v3/",
        check_embedding_ctx_length=False,
    )

    engine = VikingMemoryEngine(
        vdb_url="http://10.60.2.17",
        vdb_key="bRG3NETg13tv5Fn68VTdkxaJXH9tMQzhKeT3unck",
        vdb_username="root",
        database_name="viking_memory",
        collection_name=TEST_COLLECTION,
        embedding_model=emb,
    )

    # ── Step 1: 写入测试数据 ──
    print("\n写入测试数据...")
    all_docs = DIRECTORIES + LEAVES
    for doc in all_docs:
        doc["user_id"] = TEST_USER_ID
        doc["overview"] = doc.get("overview", "")
        doc["content"] = doc.get("content", "")
        # 向量化 abstract
        vec = await asyncio.to_thread(emb.embed_query, doc["abstract"])
        doc["vector"] = vec

    await asyncio.to_thread(engine._vdb.upsert, all_docs)
    print(f"  写入 {len(all_docs)} 条文档（{len(DIRECTORIES)} 目录 + {len(LEAVES)} 叶子）")

    # 等待索引生效
    await asyncio.sleep(2)

    # ── Step 2: 执行查询 ──
    print(f"\n执行 {len(QUERIES)} 个查询...\n")

    passed = 0
    failed = 0
    results = []

    for q in QUERIES:
        qid = q["id"]
        query = q["query"]
        expect_ids = set(q["expect_ids"])

        t0 = time.time()
        try:
            result = await engine.retrieve(query, user_id=TEST_USER_ID, top_k=5)
            elapsed = time.time() - t0

            hit_ids = [item.metadata.get("id", "") for item in result.items]
            hit_set = set(hit_ids)

            # 检查期望的 ID 是否在 Top-5 中
            matched = expect_ids & hit_set
            missed = expect_ids - hit_set
            precision = len(matched) / len(expect_ids) if expect_ids else 1.0

            if precision >= 0.5:  # 至少命中一半期望结果
                status = "✅"
                passed += 1
            else:
                status = "❌"
                failed += 1

            # 打印结果
            hit_abstracts = [item.content[:40] for item in result.items[:3]]
            print(f"  {status} #{qid:2d} | {query:<20s} | 命中: {hit_ids[:3]} | 耗时: {elapsed:.2f}s")
            if missed:
                print(f"       缺失: {missed}")

            results.append({
                "id": qid, "query": query, "status": status,
                "hit_ids": hit_ids, "expect_ids": list(expect_ids),
                "precision": precision, "elapsed": elapsed,
            })

        except Exception as e:
            elapsed = time.time() - t0
            print(f"  ❌ #{qid:2d} | {query:<20s} | 错误: {e}")
            failed += 1
            results.append({"id": qid, "query": query, "status": "❌", "error": str(e)})

    # ── Step 3: 汇总 ──
    print(f"\n{'=' * 70}")
    print(f"结果: {passed} 通过, {failed} 失败, 通过率 {passed/(passed+failed)*100:.0f}%")
    avg_time = sum(r.get("elapsed", 0) for r in results) / len(results)
    print(f"平均耗时: {avg_time:.2f}s")
    print(f"{'=' * 70}")

    # ── Step 4: 清理测试数据 ──
    try:
        all_ids = [d["id"] for d in all_docs]
        await asyncio.to_thread(engine._vdb.delete, all_ids)
        print(f"\n已清理 {len(all_ids)} 条测试数据")
    except Exception as e:
        print(f"\n清理失败: {e}")


if __name__ == "__main__":
    asyncio.run(run_test())
