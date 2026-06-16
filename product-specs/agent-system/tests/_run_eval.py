"""运行完整 250 条评测（真实 VDB + LLM Rewrite，10 并发）"""
import sys
import os
import asyncio
import json
import time

sys.path.insert(0, '.')

from dotenv import load_dotenv
load_dotenv()

from src.eval.archive_recall_eval_runner import (
    ArchiveRecallEvalRunner, RealVDBArchiveEngine, LLMArchiveQueryRewriter,
    build_seed_conversation_data, print_archive_recall_report,
)
from src.eval.archive_recall_eval_cases import build_archive_recall_cases


async def sync_seed():
    """重新同步种子数据（带新字段 biz_object, action_subtype）"""
    from langchain_openai import OpenAIEmbeddings
    from src.memory.viking_engine import VectorStore

    vdb = VectorStore(
        url=os.environ.get("TENCENT_VDB_URL", "http://10.60.2.17"),
        key=os.environ.get("TENCENT_VDB_KEY", "bRG3NETg13tv5Fn68VTdkxaJXH9tMQzhKeT3unck"),
        username="root", database_name="viking_memory",
        collection_name="archive_recall_eval",
    )
    embedding = OpenAIEmbeddings(
        model=os.environ.get("EMBEDDING_MODEL", "doubao-embedding-text-240715"),
        api_key=os.environ.get("EMBEDDING_API_KEY") or os.environ.get("DOUBAO_API_KEY"),
        base_url=os.environ.get("EMBEDDING_API_BASE", "https://ark.cn-beijing.volces.com/api/v3/"),
        check_embedding_ctx_length=False,
    )

    seed_data = build_seed_conversation_data()
    records = []
    for turn in seed_data:
        turn_id = turn["turn_id"]
        bm25_text = f"{turn['user_query']} {turn['answer_preview']}"[:800]
        embed_text = (
            f"{turn['user_query']} {turn['answer_preview']} "
            f"{turn.get('entities_text', '')} {turn.get('tool_names', '')}"
        )[:800]

        vector = embedding.embed_query(embed_text)

        record = {
            "id": f"eval_archive_turn_{turn_id}",
            "vector": vector,
            "tenant_id": "eval",
            "thread_id": "eval_session_001",
            "turn_id": str(turn_id),
            "has_decision": "1" if any(kw in turn.get("keywords", "") for kw in ["确认", "更新", "砍价", "签约"]) else "0",
            "task_id": "",
            "user_query": turn["user_query"][:500],
            "answer_preview": turn["answer_preview"][:500],
            "entities_text": turn.get("entities_text", "")[:300],
            "tool_names_text": turn.get("tool_names", "")[:200],
            "biz_object": turn.get("biz_object", ""),
            "action_subtype": turn.get("action_subtype", ""),
            "abstract": bm25_text,
            "content": json.dumps(turn, ensure_ascii=False),
            "keywords_json": turn.get("keywords", ""),
            "message_count": "4",
            "archived_at": str(int(time.time() * 1000)),
            "data_timestamp": str(int(time.time() * 1000)),
        }
        records.append(record)

    vdb.upsert(records)
    print(f"[sync] 已同步 {len(records)} 轮种子数据到 VDB")


async def run_eval(concurrency: int = 10):
    """运行 250 条评测（并发）"""
    engine = RealVDBArchiveEngine()
    rewriter = LLMArchiveQueryRewriter()
    runner = ArchiveRecallEvalRunner(engine=engine, rewriter=rewriter)

    status = runner.setup()
    print(f"[setup] VDB ready={status['vdb_ready']}, records={status['record_count']}")

    if not status['vdb_ready']:
        print("[ERROR] VDB 未就绪")
        return

    cases = build_archive_recall_cases()
    print(f"[eval] 开始评测 {len(cases)} 条用例（并发={concurrency}）...\n")

    start = time.time()
    report = await runner.run_all(cases, concurrency=concurrency)
    elapsed = time.time() - start

    print_archive_recall_report(report)
    print(f"  实际耗时: {elapsed:.1f}s（并发={concurrency}）")
    print(f"  平均每条: {elapsed/len(cases)*1000:.0f}ms")

    # 失败用例详情
    failed = [r for r in report.results if not r.passed]
    if failed:
        print(f"\n失败用例详情 ({len(failed)}条):")
        for r in failed[:50]:
            rw_flag = " [RW]" if not r.rewrite_passed else ""
            rc_flag = " [RC]" if not r.recall_passed else ""
            print(f"  {r.case_id} [{r.category}]{rw_flag}{rc_flag} \"{r.query[:40]}\"")
            if not r.rewrite_passed:
                print(f"    rewritten=\"{r.rewritten_query[:50]}\" intent={r.detected_intent}")
            if not r.recall_passed:
                print(f"    {r.detail} | hit={r.hit_turn_ids[:5]} expect={r.expected_turn_ids}")



async def main():
    # Step 1: 同步种子数据
    print("=" * 60)
    print("  Step 1: 同步种子数据到 VDB")
    print("=" * 60)
    await sync_seed()
    print()

    # Step 2: 并发评测
    print("=" * 60)
    print("  Step 2: 运行 250 条评测 (真实VDB + LLM, 2并发)")
    print("=" * 60)
    await run_eval(concurrency=2)


if __name__ == "__main__":
    asyncio.run(main())
