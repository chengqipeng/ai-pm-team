"""SkillsTool — Pydantic BaseTool 版本，直接注册到 LangChain Agent

替代旧的 skills.py 中继承自定义 Tool 基类的 SkillsTool。
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field

from src.skills.base import SkillExecutor

logger = logging.getLogger(__name__)


class SkillsToolInput(BaseModel):
    skill_name: str = Field(description="要调用的技能名称")
    arguments: dict[str, str] = Field(default_factory=dict, description="传递给技能的命名参数")


class SkillsTool(BaseTool):
    """统一技能调用工具（Pydantic BaseTool）"""

    name: str = "skills_tool"
    description: str = (
        "调用已注册的技能。传入 skill_name（技能名称）和 arguments（命名参数字典）。"
        "系统会根据技能配置自动选择执行模式。"
    )
    args_schema: type[BaseModel] = SkillsToolInput

    skill_executor: SkillExecutor
    parent_thread_id: str = "default"

    model_config = {"arbitrary_types_allowed": True}

    def _run(self, skill_name: str, arguments: dict[str, str] | None = None) -> str:
        arguments = arguments or {}
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        if loop and loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                return pool.submit(asyncio.run,
                    self.skill_executor.execute(skill_name, arguments, self.parent_thread_id)).result()
        return asyncio.run(self.skill_executor.execute(skill_name, arguments, self.parent_thread_id))

    async def _arun(self, skill_name: str, arguments: dict[str, str] | None = None) -> str:
        arguments = arguments or {}
        return await self.skill_executor.execute(skill_name, arguments, self.parent_thread_id)
