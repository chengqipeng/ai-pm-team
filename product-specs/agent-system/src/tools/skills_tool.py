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
        "技能会返回完整的分析报告，收到报告后请根据指令决定如何处理。"
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
        # 在子 Agent 执行前捕获当前 callback config（子 Agent 可能覆盖 contextvars）
        try:
            from langchain_core.runnables.config import ensure_config
            _parent_config = ensure_config()
        except Exception:
            _parent_config = None

        arguments = self._normalize_arguments(arguments)
        result = await self.skill_executor.execute(skill_name, arguments, self.parent_thread_id)

        # 判断 Skill 的 context 模式
        skill = self.skill_executor._registry.get(skill_name)
        is_inline = skill and skill.context == "inline"

        if is_inline:
            # inline 模式：Skill 已通过 allowed-tools 完成执行，result 就是最终结果
            return result

        # ═══ Fork 模式：子 Agent 已执行完毕，结果是完整报告 ═══
        behavior = self._resolve_post_output_behavior(skill)
        output_mode = getattr(skill, "output_mode", "text") if skill else "text"
        summary = self._generate_summary(result)

        # passthrough 模式：不走 dispatch，直接返回完整结果给 LLM
        if behavior == "passthrough":
            return result

        # 其他模式：通过 skill_result 事件直出子 Agent 结果
        dispatch_success = False
        if result:
            try:
                from langchain_core.callbacks import adispatch_custom_event
                logger.info(
                    "[SkillsTool] attempting dispatch skill_result: skill=%s, output_mode=%s, config=%s",
                    skill_name, output_mode, type(_parent_config).__name__ if _parent_config else "None",
                )
                await adispatch_custom_event("skill_result", {
                    "skill_apikey": skill_name,
                    "behavior": behavior,
                    "content": result,
                    "summary": summary,
                    "output_mode": output_mode,
                }, config=_parent_config)
                dispatch_success = True
                logger.info(
                    "[SkillsTool] dispatch skill_result OK: skill=%s, behavior=%s, len=%d",
                    skill_name, behavior, len(result),
                )
            except Exception as exc:
                logger.warning(
                    "[SkillsTool] adispatch_custom_event failed (will use fallback): %s", exc,
                )
                dispatch_success = False

        # 根据 behavior 返回不同的控制指令给主 Agent LLM
        if behavior == "silent":
            if dispatch_success:
                # 事件已发出，子 Agent 结果已直出前端 → LLM 不需要再输出
                return (
                    f"[SKILL_DONE:silent] {skill_name} 已将完整结果（{len(result)}字）"
                    f"直接输出给用户。不要输出任何内容，直接结束本轮对话。"
                )
            else:
                # dispatch 失败，完整结果回传给 LLM 输出（converter 不会再抑制）
                return (
                    f"[SKILL_DONE:passthrough] {skill_name} 执行完成。\n\n"
                    + result
                )
        elif behavior == "summarize":
            if dispatch_success:
                return (
                    f"[SKILL_DONE:summarize] {skill_name} 已将完整结果直接输出给用户。\n"
                    f"摘要：{summary}\n"
                    f"请给出 1-2 句简短引导或追问建议，不要重复上面的内容。"
                )
            else:
                return (
                    f"[SKILL_DONE:passthrough] {skill_name} 执行完成。\n\n"
                    + result
                )
        elif behavior == "continue":
            if dispatch_success:
                return (
                    f"[SKILL_DONE:continue] {skill_name} 已将结果输出给用户。\n"
                    f"摘要：{summary}\n"
                    f"你可以根据用户原始意图继续调用其他工具完成后续步骤，"
                    f"或给出简短总结。不要重复已输出的内容。"
                )
            else:
                return (
                    f"[SKILL_DONE:passthrough] {skill_name} 执行完成。\n\n"
                    + result
                )
        else:
            return result

    @staticmethod
    def _resolve_post_output_behavior(skill) -> str:
        """根据 Skill 配置决定 post_output_behavior"""
        if skill is None:
            return "silent"
        return getattr(skill, "post_output_behavior", "silent") or "silent"

    @staticmethod
    def _generate_summary(result: str, max_len: int = 200) -> str:
        """提取结果摘要（前 N 字 + 结构化标题）"""
        if not result:
            return ""
        if len(result) <= max_len:
            return result
        # 取第一段非空行作为标题
        lines = [line.strip() for line in result.split("\n") if line.strip()]
        title = lines[0][:80] if lines else ""
        # 去掉 Markdown 标题标记
        if title.startswith("#"):
            title = title.lstrip("#").strip()
        return f"{title}...（共{len(result)}字）"

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
