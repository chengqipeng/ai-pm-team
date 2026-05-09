"""诊断脚本：检查 Redis checkpointer + memory 中存储的历史消息

用法: python scripts/inspect_thread_history.py <thread_id>
"""
import asyncio
import sys
import json
from pathlib import Path

# 确保能导入 src
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


async def inspect(thread_id: str):
    print("=" * 70)
    print(f"  诊断 thread_id: {thread_id}")
    print("=" * 70)

    # 1. 检查 Redis checkpointer 里的消息历史
    print("\n── [1/2] Redis Checkpointer 历史消息 ──")
    try:
        from src.core.checkpointer import create_async_redis_checkpointer
        cp = await create_async_redis_checkpointer()
        config = {"configurable": {"thread_id": thread_id}}

        # 获取最近的 checkpoint
        tuple_result = await cp.aget_tuple(config)
        if tuple_result is None:
            print("  → 没有找到该 thread 的历史记录（全新对话）")
        else:
            state = tuple_result.checkpoint.get("channel_values", {}).get("messages", [])
            print(f"  → 找到 {len(state)} 条历史消息")
            for i, msg in enumerate(state):
                msg_type = getattr(msg, "type", "unknown")
                content = getattr(msg, "content", "")
                if isinstance(content, str):
                    preview = content[:200]
                else:
                    preview = str(content)[:200]
                print(f"\n  [{i}] [{msg_type}]")
                print(f"      {preview}")

                # 标记污染内容
                nlu_markers = ["改写：", "改写:", "实体：", "实体名：",
                               "代词解析", "代词：", "业务概念："]
                for m in nlu_markers:
                    if m in str(content):
                        print(f"      ⚠️ 含污染标记: {m}")
                        break
    except Exception as e:
        print(f"  ❌ 读取 Redis 失败: {e}")

    # 2. 检查长期记忆中存储的内容
    print("\n── [2/2] 长期记忆检索（query=我负责华东区） ──")
    try:
        from src.memory.fts_engine import FTSMemoryEngine
        mem = FTSMemoryEngine(storage_dir="./data/memory", llm=None)
        from src.middleware.memory import MemoryDimension
        result = await mem.retrieve(
            query="我负责华东区",
            dimensions=list(MemoryDimension),
            user_id="100000000000000000",
            top_k=10,
        )
        if not result.items:
            print("  → 记忆库中无匹配记录")
        else:
            print(f"  → 命中 {len(result.items)} 条记忆")
            for i, item in enumerate(result.items):
                print(f"\n  [{i}] [{item.dimension.value}] (confidence={item.confidence:.2f})")
                print(f"      {item.content[:200]}")

                nlu_markers = ["改写：", "改写:", "实体：", "实体名：",
                               "代词解析", "代词：", "业务概念："]
                for m in nlu_markers:
                    if m in item.content:
                        print(f"      ⚠️ 含污染标记: {m}")
                        break
    except Exception as e:
        print(f"  ❌ 读取记忆失败: {e}")

    print("\n" + "=" * 70)
    print("  诊断完成")
    print("=" * 70)


if __name__ == "__main__":
    thread_id = sys.argv[1] if len(sys.argv) > 1 else "4f455ddab583"
    asyncio.run(inspect(thread_id))
