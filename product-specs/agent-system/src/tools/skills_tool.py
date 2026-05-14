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
    arguments: dict[str, Any] = Field(default_factory=dict, description="传递给技能的命名参数，所有值应为字符串")


class SkillsTool(BaseTool):
    """统一技能调用工具（Pydantic BaseTool）"""

    name: str = "skills_tool"
    description: str = (
        "调用已注册的技能执行深度分析。传入 skill_name 和 arguments。"
        "技能会返回完整的分析报告，收到报告后请直接输出给用户，不要再做额外处理。"
    )
    args_schema: type[BaseModel] = SkillsToolInput

    skill_executor: SkillExecutor
    parent_thread_id: str = "default"

    model_config = {"arbitrary_types_allowed": True}

    def _run(self, skill_name: str, arguments: dict[str, Any] | None = None) -> str:
        arguments = self._normalize_arguments(arguments)
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

    async def _arun(self, skill_name: str, arguments: dict[str, Any] | None = None) -> str:
        arguments = self._normalize_arguments(arguments)
        result = await self.skill_executor.execute(skill_name, arguments, self.parent_thread_id)

        # 判断 Skill 的 context 模式
        skill = self.skill_executor._registry.get(skill_name)
        is_inline = skill and skill.context == "inline"

        if is_inline:
            # inline 模式：Skill 已通过 allowed-tools 完成执行，result 就是最终结果
            # 不要包含 SOP 指令文本，只返回执行结果
            return result
        elif result and len(result) > 200:
            # fork 模式：子 Agent 已执行完毕，结果是完整报告，直接输出
            return f"[技能执行完成，以下是完整分析报告，请直接输出给用户，不要再调用其他工具]\n\n{result}"
        return result

    @staticmethod
    def _normalize_arguments(arguments: dict[str, Any] | None) -> dict[str, str]:
        """将所有参数值规范化为字符串，兼容 LLM 传入列表/数字等非字符串类型"""
        if not arguments:
            return {}
        result = {}
        for k, v in arguments.items():
            if isinstance(v, str):
                result[k] = v
            elif isinstance(v, list):
                # 列表转为逗号分隔的字符串
                result[k] = ", ".join(str(item) for item in v)
            elif v is None:
                result[k] = ""
            else:
                result[k] = str(v)
        return result
