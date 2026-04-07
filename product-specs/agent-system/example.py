"""
完整使用示例 — 真实 Anthropic API 调用
设置 ANTHROPIC_API_KEY 环境变量后运行:
  export ANTHROPIC_API_KEY=sk-ant-...
  python example.py
"""
import asyncio
import json
import os
import sys
import logging

from src.types import Message, MessageRole
from src.engine import QueryEngine, QueryEngineConfig
from src.hooks import (
    HookDefinition, HookEvent, HookMatcher, HookAction, HookActionType,
)
from src.session import SessionStorage

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("example")


def create_llm_client():
    """创建真实 Anthropic 客户端"""
    from src.llm_client import AnthropicClient
    return AnthropicClient(
        default_model="claude-sonnet-4-20250514",
        default_max_tokens=4096,
    )


async def main():
    # 检查 API key
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("❌ ANTHROPIC_API_KEY not set.")
        print("   export ANTHROPIC_API_KEY=sk-ant-...")
        sys.exit(1)

    print("=" * 60)
    print("  Agent + Skills + Tools — Real API Demo")
    print("=" * 60)

    llm = create_llm_client()

    engine = QueryEngine(QueryEngineConfig(
        llm_client=llm,
        model="claude-sonnet-4-20250514",
        project_root=".",
        permission_mode="acceptEdits",
        enable_session=True,
        max_turns=10,
    ))

    # 注册一个审计 hook
    await engine.initialize()
    engine.hook_registry.register(HookDefinition(
        name="audit-writes",
        event=HookEvent.POST_TOOL_USE,
        matcher=HookMatcher(tool_category="write"),
        action=HookAction(
            type=HookActionType.ASK_AGENT,
            prompt="Write operation: {{tool_name}}",
        ),
    ))

    print(f"\n📋 Session: {engine.session_id}")
    print(f"📦 Tools: {', '.join(t.name for t in engine.tool_registry.all_tools)}")
    print(f"🎯 Skills: {len(engine.skill_registry.all_skills)}")
    print()

    # 用户 prompt
    prompt = (
        "Read the file product-specs/agent-system/src/types.py, "
        "count how many dataclass definitions it has, "
        "and tell me the names of all Enum classes defined in it."
    )
    print(f"[User] {prompt}\n")

    async for msg in engine.submit_message(prompt):
        role = msg.role.value.upper()
        if msg.tool_use_blocks:
            for tu in msg.tool_use_blocks:
                inp = json.dumps(tu.input, ensure_ascii=False)
                if len(inp) > 80:
                    inp = inp[:80] + "..."
                print(f"  [{role}] 🔧 {tu.name}({inp})")
        elif msg.tool_result_blocks:
            for tr in msg.tool_result_blocks:
                preview = tr.content[:120].replace("\n", " ")
                icon = "❌" if tr.is_error else "✅"
                print(f"  [{role}] {icon} {preview}")
        elif msg.role == MessageRole.SYSTEM:
            print(f"  [SYS] ⚙️  {str(msg.content)[:120]}")
        elif msg.content:
            print(f"  [{role}] 💬 {str(msg.content)[:500]}")
        print()

    # 用量统计
    print("=" * 60)
    print(f"  Messages: {len(engine.messages)}")
    print(f"  Usage: {llm.total_usage}")
    print(f"  Session: {engine.session_id}")
    print("=" * 60)

    await engine.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
