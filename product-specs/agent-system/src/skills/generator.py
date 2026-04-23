"""自动技能生成 — 任务完成后自动创建 SKILL.md

借鉴 Hermes Agent 的自改进学习循环：
1. 检测任务是否足够复杂（工具调用数 >= 阈值）
2. 从对话中提取任务模式
3. 生成 SKILL.md 文件
4. 注册到 SkillRegistry
"""
from __future__ import annotations

import logging
import os
import re
import time
from pathlib import Path
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

logger = logging.getLogger(__name__)


class SkillGenerator:
    """自动技能生成器

    参数:
        skills_dir: 技能文件保存目录
        min_tool_calls: 触发技能生成的最小工具调用数
        skill_registry: 可选的 SkillRegistry，生成后自动注册
    """

    def __init__(
        self,
        skills_dir: str = "./skills/auto-generated",
        min_tool_calls: int = 5,
        skill_registry: Any = None,
        llm: Any = None,
    ) -> None:
        self._skills_dir = Path(skills_dir)
        self._min_tool_calls = min_tool_calls
        self._skill_registry = skill_registry
        self._llm = llm  # LLM 实例，用于高质量技能生成

    def should_generate(self, messages: list) -> bool:
        """判断是否应该生成技能（工具调用数 >= 阈值）"""
        tool_call_count = sum(
            1 for m in messages if isinstance(m, ToolMessage)
        )
        return tool_call_count >= self._min_tool_calls

    async def generate_with_llm(self, messages: list) -> str | None:
        """LLM 驱动的技能生成（优先使用）

        如果有 optimizer，委托给 SkillOptimizer.generate_from_conversation。
        否则 fallback 到规则生成。
        """
        if self._llm is not None and self.should_generate(messages):
            try:
                from .optimizer import SkillOptimizer
                from .tracker import SkillTracker
                optimizer = SkillOptimizer(
                    llm=self._llm,
                    tracker=SkillTracker(),  # 临时 tracker
                    skills_dir=str(self._skills_dir),
                    skill_registry=self._skill_registry,
                )
                return await optimizer.generate_from_conversation(messages, self._min_tool_calls)
            except Exception as e:
                logger.warning("LLM 技能生成失败，fallback 到规则: %s", e)
        return self.generate(messages)

    def generate(self, messages: list, task_description: str = "") -> str | None:
        """从对话中生成 SKILL.md 文件（规则提取 fallback）

        返回生成的文件路径，失败返回 None
        """
        if not self.should_generate(messages):
            return None

        # 提取任务信息
        task_info = self._extract_task_info(messages)
        if not task_info["description"]:
            return None

        # 生成技能名
        skill_name = self._generate_skill_name(task_info["description"])

        # 构建 SKILL.md 内容
        content = self._build_skill_content(skill_name, task_info)

        # 写入文件
        skill_dir = self._skills_dir / skill_name
        skill_dir.mkdir(parents=True, exist_ok=True)
        skill_path = skill_dir / "SKILL.md"
        skill_path.write_text(content, encoding="utf-8")

        logger.info("Auto-generated skill: %s → %s", skill_name, skill_path)

        # 自动注册到 SkillRegistry
        if self._skill_registry is not None:
            try:
                from src.skills.base import SkillLoader
                skill_def = SkillLoader.parse(content)
                if not skill_def.name:
                    skill_def.name = skill_name
                self._skill_registry.register(skill_def)
                logger.info("Auto-registered skill: %s", skill_name)
            except Exception as e:
                logger.warning("Failed to register auto-generated skill: %s", e)

        return str(skill_path)

    def _extract_task_info(self, messages: list) -> dict:
        """从对话中提取任务信息"""
        info = {
            "description": "",
            "tools_used": [],
            "arguments": [],
            "steps": [],
        }

        # 提取第一条用户消息作为任务描述
        for msg in messages:
            if isinstance(msg, HumanMessage):
                content = msg.content if isinstance(msg.content, str) else str(msg.content)
                info["description"] = content[:200]
                break

        # 提取使用的工具和参数
        seen_tools = set()
        for msg in messages:
            if isinstance(msg, AIMessage):
                tool_calls = getattr(msg, "tool_calls", None)
                if tool_calls:
                    for tc in tool_calls:
                        name = tc.get("name", "")
                        if name and name not in seen_tools:
                            seen_tools.add(name)
                            info["tools_used"].append(name)
                            # 提取参数名
                            args = tc.get("args", {})
                            for arg_name in args:
                                if arg_name not in info["arguments"]:
                                    info["arguments"].append(arg_name)

        # 提取执行步骤
        step_num = 0
        for msg in messages:
            if isinstance(msg, AIMessage):
                content = msg.content if isinstance(msg.content, str) else ""
                tool_calls = getattr(msg, "tool_calls", None)
                if tool_calls:
                    for tc in tool_calls:
                        step_num += 1
                        info["steps"].append(f"{step_num}. 调用 {tc.get('name', '')} 工具")
                elif content.strip():
                    step_num += 1
                    info["steps"].append(f"{step_num}. {content[:100]}")

        return info

    def _generate_skill_name(self, description: str) -> str:
        """从描述生成技能名（kebab-case）"""
        # 提取中文关键词
        keywords = re.findall(r'[\u4e00-\u9fff]+', description)
        if keywords:
            name = "-".join(keywords[:3])
        else:
            words = re.findall(r'[a-zA-Z]+', description)
            name = "-".join(w.lower() for w in words[:3])

        if not name:
            name = f"auto-skill-{int(time.time())}"

        # 确保唯一性
        base_name = name
        counter = 1
        while (self._skills_dir / name / "SKILL.md").exists():
            name = f"{base_name}-{counter}"
            counter += 1

        return name

    def _build_skill_content(self, skill_name: str, task_info: dict) -> str:
        """构建 SKILL.md 内容"""
        tools_list = "\n".join(f"  - {t}" for t in task_info["tools_used"]) if task_info["tools_used"] else "  []"
        steps_text = "\n".join(task_info["steps"][:10]) if task_info["steps"] else "（无步骤记录）"

        content = f"""---
name: {skill_name}
description: {task_info['description'][:100]}
when_to_use: {self._extract_when_to_use(task_info['description'])}
arguments: []
allowed-tools:
{tools_list}
context: inline
---

## 任务执行步骤

{steps_text}

## 注意事项

- 必须使用工具获取真实数据，禁止编造
- 按照上述步骤顺序执行
- 此技能由系统自动生成于 {time.strftime('%Y-%m-%d %H:%M')}
"""
        return content

    @staticmethod
    def _extract_when_to_use(description: str) -> str:
        """从描述中提取使用时机关键词"""
        keywords = re.findall(r'[\u4e00-\u9fff]{2,4}', description)
        if keywords:
            return "|".join(keywords[:3])
        return ""
