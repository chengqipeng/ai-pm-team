"""腾讯云向量数据库 + Mem0 连通性测试

验证：
  1. tcvectordb SDK 连接
  2. LangChain TencentVectorDB 桥接
  3. Mem0MemoryEngine + 腾讯向量库 完整链路（写入→检索→删除）

运行：
  cd product-specs/agent-system
  .venv/bin/python tests/test_tencent_vdb.py
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("DEEPSEEK_API_KEY", "sk-HdY98AcN68JhtXLp8oeIATEL4PWq9rzRcCAhI8G4SOtBbtSw")

TENCENT_VDB_CONFIG = {
    "url": "http://10.60.2.17",
    "key": "bRG3NETg13tv5Fn68VTdkxaJXH9tMQzhKeT3unck",
    "username": "root",
    "database_name": "mem0_test_db",
    "collection_name": "mem0_2560d",
}

passed = 0
failed = 0


def check(name, condition):
    global passed, failed
    if condition:
        print(f"  ✅ {name}")
        passed += 1
    else:
        print(f"  ❌ {name}")
        failed += 1


# ═══════════════════════════════════════════════════════════
# 1. tcvectordb SDK 原生连接测试
# ═══════════════════════════════════════════════════════════

def test_tcvectordb_connection():
    print("\n📦 1. tcvectordb SDK 连接测试")
    try:
        import tcvectordb
        from tcvectordb.model.database import Database

        client = tcvectordb.VectorDBClient(
            url=TENCENT_VDB_CONFIG["url"],
            username=TENCENT_VDB_CONFIG["username"],
            key=TENCENT_VDB_CONFIG["key"],
            timeout=10,
        )
        check("tcvectordb 客户端创建成功", client is not None)

        # 列出数据库
        dbs = client.list_databases()
        db_names = [db.database_name for db in dbs]
        check(f"列出数据库成功 ({len(db_names)} 个)", len(db_names) >= 0)
        print(f"    已有数据库: {db_names[:5]}")

    except Exception as e:
        check(f"连接失败: {e}", False)


# ═══════════════════════════════════════════════════════════
# 2. LangChain TencentVectorDB 桥接测试
# ═══════════════════════════════════════════════════════════

def test_langchain_bridge():
    print("\n📦 2. LangChain TencentVectorDB 桥接测试")
    try:
        from langchain_community.vectorstores import TencentVectorDB
        from langchain_community.vectorstores.tencentvectordb import ConnectionParams
        from langchain_openai import OpenAIEmbeddings

        # 构建 embedding
        embedding = OpenAIEmbeddings(
            model="doubao-embedding-text-240715",
            api_key=os.environ.get("EMBEDDING_API_KEY", "651621e7-e495-4728-93ef-ed380e9ddcd1"),
            base_url="https://ark.cn-beijing.volces.com/api/v3/",
            check_embedding_ctx_length=False,
        )
        check("OpenAIEmbeddings 创建成功", embedding is not None)

        # 构建连接
        conn = ConnectionParams(
            url=TENCENT_VDB_CONFIG["url"],
            key=TENCENT_VDB_CONFIG["key"],
            username=TENCENT_VDB_CONFIG["username"],
            timeout=10,
        )

        from langchain_community.vectorstores.tencentvectordb import IndexParams
        index_params = IndexParams(dimension=2560, metric_type="COSINE")

        vdb = TencentVectorDB(
            embedding=embedding,
            connection_params=conn,
            index_params=index_params,
            database_name=TENCENT_VDB_CONFIG["database_name"],
            collection_name=TENCENT_VDB_CONFIG["collection_name"],
        )
        check("TencentVectorDB 实例创建成功", vdb is not None)

        # 写入测试文档
        ids = vdb.add_texts(
            texts=["华为科技是通信行业龙头企业，年营收8809亿"],
            metadatas=[{"source": "test", "user_id": "test_user"}],
        )
        check(f"写入文档成功 (ids={ids})", len(ids) > 0)

        # 相似度搜索
        results = vdb.similarity_search("华为科技", k=1)
        check("相似度搜索成功", len(results) > 0)
        if results:
            print(f"    搜索结果: {results[0].page_content[:80]}")

        print("#test_langchain_bridge finish ")
    except Exception as e:
        check(f"桥接失败: {e}", False)
        import traceback
        traceback.print_exc()


# ═══════════════════════════════════════════════════════════
# 3. Mem0MemoryEngine + 腾讯向量库 完整链路
# ═══════════════════════════════════════════════════════════

async def test_mem0_with_tencent_vdb():
    print("\n📦 3. Mem0MemoryEngine + 腾讯向量库 完整链路")
    try:
        from src.memory.mem0_engine import Mem0MemoryEngine
        from langchain_core.messages import HumanMessage, AIMessage

        engine = Mem0MemoryEngine(
            tencent_vdb_config=TENCENT_VDB_CONFIG,
        )
        check("Mem0MemoryEngine 初始化成功（腾讯向量库）", engine is not None)

        # 写入记忆（用全新客户，验证结构化提取效果）
        import time as _time
        messages = [
            HumanMessage(content="帮我查一下小米集团的商机和联系人"),
            AIMessage(content="小米集团目前有2个活跃商机：IoT平台项目650万处于方案阶段，"
                              "智能工厂项目1800万处于谈判阶段。主要联系人是李总（CTO），"
                              "电话139-8888-6666。另外王经理（采购总监）负责供应链对接。"),
        ]

        result = await engine.extract_and_update(
            messages, thread_id="tencent-vdb-test", user_id="vdb-test-user"
        )
        check("记忆写入成功", len(result.items) > 0)
        if result.items:
            print(f"    写入 {len(result.items)} 条记忆:")
            for item in result.items:
                print(f"      [{item.dimension.value}] {item.content[:60]}...")

        # 检索记忆（等待索引构建）
        import time
        time.sleep(2)  # tcvectordb 索引构建需要短暂延迟

        retrieve_result = await engine.retrieve(
            query="小米集团 商机 联系人",
            user_id="vdb-test-user",
            top_k=5,
        )
        check("记忆检索成功", len(retrieve_result.items) > 0)
        if retrieve_result.items:
            print(f"    检索到 {len(retrieve_result.items)} 条:")
            for item in retrieve_result.items:
                print(f"      [score={item.confidence:.3f}] {item.content[:60]}...")

        # 清理测试数据
        engine.clear_all_memories("vdb-test-user")
        check("测试数据清理完成", True)

    except Exception as e:
        check(f"完整链路失败: {e}", False)
        import traceback
        traceback.print_exc()


# ═══════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("=" * 60)
    print("  腾讯云向量数据库 + Mem0 连通性测试")
    print("=" * 60)

    test_tcvectordb_connection()
    test_langchain_bridge()
    asyncio.run(test_mem0_with_tencent_vdb())

    print(f"\n{'=' * 60}")
    print(f"  连通性测试: {passed} passed, {failed} failed")
    print(f"{'=' * 60}")
    sys.exit(1 if failed else 0)
