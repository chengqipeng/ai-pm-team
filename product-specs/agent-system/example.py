"""
DeepAgent 使用示例 — DeepSeek API 调用
设置 DEEPSEEK_API_KEY 环境变量后运行:
  export DEEPSEEK_API_KEY=sk-...
  python example.py
"""
import asyncio
import json
import os
import sys
import logging

from src.dtypes import Message, MessageRole, ToolResult
from src.tools import Tool, ToolRegistry
from src.graph.state import GraphState
from src.graph.factory import AgentFactory, AgentConfig

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("example")


# ── 示例工具 ──

class EchoTool(Tool):
    @property
    def name(self): return "echo"
    def input_schema(self): return {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]}
    async def call(self, input_data, context, on_progress=None):
        return ToolResult(content=f"Echo: {input_data.get('text', '')}")
    def prompt(self): return "回显输入文本，用于测试"


def create_llm_client():
    """创建 DeepSeek 客户端"""
    from src.llm_client import DeepSeekClient
    return DeepSeekClient(
        default_model="deepseek-chat",
        default_max_tokens=4096,
    )


async def main():
    if not os.environ.get("DEEPSEEK_API_KEY"):
        print("DEEPSEEK_API_KEY not set. Using MockLLMClient.")
        from src.llm_client import MockLLMClient
        llm = MockLLMClient()
        llm.add_text_response("华为技术有限公司，成立于1987年，是全球领先的ICT基础设施和智能终端提供商。")
    else:
        llm = create_llm_client()

    print("=" * 60)
    print("  DeepAgent — GraphEngine Demo")
    print("=" * 60)

    registry = ToolRegistry()
    registry.register(EchoTool())

    engine, sys_prompt = AgentFactory.create(AgentConfig(
        tenant_id="demo_tenant",
        user_id="demo_user",
        llm_client=llm,
        tool_registry=registry,
        enable_hitl=False,
    ))

    state = GraphState(
        tenant_id="demo_tenant",
        user_id="demo_user",
        system_prompt=sys_prompt,
        messages=[Message(role=MessageRole.USER, content="介绍一下华为公司")],
    )

    print(f"\n[User] 介绍一下华为公司\n")

    async for s in engine.run(state):
        if s.final_answer:
            print(f"[Agent] {s.final_answer[:500]}")

    print(f"\nStatus: {s.status.value}")
    print(f"LLM calls: {s.total_llm_calls}")
    print(f"Tool calls: {s.total_tool_calls}")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
