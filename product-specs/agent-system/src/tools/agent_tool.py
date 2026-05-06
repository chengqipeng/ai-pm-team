"""AgentTool — 子 Agent 委派工具（Pydantic BaseTool）

模型通过调用此工具，传入 agent_name 和 instruction，
构建子 Agent 实例并执行。
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, TYPE_CHECKING
from uuid import uuid4

from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class AgentToolInput(BaseModel):
    agent_name: str = Field(default="default", description="子 Agent 名称，default 使用主 Agent 同配置")
    instruction: str = Field(description="传递给子 Agent 的执行指令")


class AgentTool(BaseTool):
    """创建子 Agent 执行任务"""

    name: str = "agent_tool"
    description: str = (
        "创建子 Agent 执行复杂任务。传入 agent_name（子 Agent 名称，默认 default）"
        "和 instruction（执行指令）。"
    )
    args_schema: type[BaseModel] = AgentToolInput

    agent_factory: Any = None
    parent_thread_id: str = "default"
    current_depth: int = 0

    model_config = {"arbitrary_types_allowed": True}

    def _run(self, agent_name: str = "default", instruction: str = "") -> str:
        import concurrent.futures
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        if loop and loop.is_running():
            with concurrent.futures.ThreadPoolExecutor() as pool:
                return pool.submit(asyncio.run,
                    self._arun(agent_name=agent_name, instruction=instruction)).result()
        return asyncio.run(self._arun(agent_name=agent_name, instruction=instruction))

    async def _arun(self, agent_name: str = "default", instruction: str = "") -> str:
        if self.agent_factory is None:
            return "Error: AgentFactory 未配置"

        logger.info("[agent_tool] agent=%s, depth=%d", agent_name, self.current_depth)
        agent = await self.agent_factory.build(agent_name, self.current_depth)
        sub_thread_id = f"{self.parent_thread_id}-{agent_name}-{uuid4().hex[:8]}"

        result = await agent.ainvoke(
            {"messages": [HumanMessage(content=instruction)]},
            config={"configurable": {"thread_id": sub_thread_id}},
        )

        messages = result.get("messages", [])
        for msg in reversed(messages):
            if isinstance(msg, AIMessage):
                content = msg.content
                if isinstance(content, list):
                    return "".join(c.get("text", "") if isinstance(c, dict) else str(c) for c in content)
                return str(content)
        return ""
