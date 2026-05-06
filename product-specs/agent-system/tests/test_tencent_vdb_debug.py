"""Debug: 定位 mem0 + 腾讯向量库检索失败的具体原因"""
import asyncio, os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("DOUBAO_API_KEY", "651621e7-e495-4728-93ef-ed380e9ddcd1")

async def main():
    from src.memory.mem0_engine import Mem0MemoryEngine
    from langchain_openai import OpenAIEmbeddings

    engine = Mem0MemoryEngine(
        tencent_vdb_config={
            "url": "http://10.60.2.17",
            "key": "bRG3NETg13tv5Fn68VTdkxaJXH9tMQzhKeT3unck",
            "username": "root",
            "database_name": "mem0_test_db",
            "collection_name": "mem0_2560d",
        },
    )

    # Step 1: 检查 patch 是否生效
    vs = engine._mem0.vector_store
    print(f"1. vector_store type: {type(vs).__name__}")
    print(f"   search method: {vs.search}")
    is_patched = "native_search" in str(vs.search) or "fixed_search" in str(vs.search)
    print(f"   is patched: {is_patched}")

    # Step 2: 手动 embed + 调用 patched search
    emb = OpenAIEmbeddings(
        model="doubao-embedding-text-240715",
        api_key=os.environ["DOUBAO_API_KEY"],
        base_url="https://ark.cn-beijing.volces.com/api/v3/",
        check_embedding_ctx_length=False,
    )
    vec = emb.embed_query("腾讯 商机")
    print(f"\n2. query vector dim: {len(vec)}")

    results = vs.search(query="腾讯 商机", vectors=vec, top_k=5, filters={"user_id": "vdb-test-user"})
    print(f"   patched search results: {len(results)}")
    for r in results:
        print(f"   id={r.id}, score={r.score}, data={str(r.payload.get('data',''))[:80]}")

    # Step 3: 调用 engine.retrieve
    print(f"\n3. engine.retrieve:")
    result = await engine.retrieve(query="腾讯 商机", user_id="vdb-test-user", top_k=5)
    print(f"   items: {len(result.items)}")
    for item in result.items:
        print(f"   [{item.dimension.value}] score={item.confidence:.3f} {item.content[:60]}")

    # Step 4: 调用 mem0 原生 search
    print(f"\n4. mem0 raw search:")
    try:
        raw = engine._mem0.search(query="腾讯 商机", top_k=5, filters={"user_id": "vdb-test-user"})
        print(f"   raw results count: {len(raw.get('results', []))}")
        for r in raw.get("results", []):
            print(f"   memory={r.get('memory','')[:80]}, score={r.get('score')}")
    except Exception as e:
        print(f"   ERROR: {e}")
        import traceback
        traceback.print_exc()

asyncio.run(main())
