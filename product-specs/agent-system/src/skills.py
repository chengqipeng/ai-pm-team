"""
Skills 体系 — SkillDefinition + SkillRegistry + SkillExecutor + SkillsTool

对应 design.md §6: Skills 系统
- SkillDefinition: 技能数据结构（name/prompt/context/allowed_tools/agent）
- SkillRegistry: 注册/查找/按 context 筛选
- SkillExecutor: 路由 inline / fork(通用) / fork(指定agent)
- SkillsTool: 注册到 ToolRegistry，LLM 通过 function calling 调用
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Awaitable

from .dtypes import ToolResult, Message, MessageRole
from .tools import Tool

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════
# SkillDefinition
# ═══════════════════════════════════════════════════════════

@dataclass
class SkillDefinition:
    """
    技能定义 — 对应 design.md §6.1 Skill 数据模型

    context="inline": prompt 作为工具返回值注入当前对话，LLM 按 SOP 继续执行
    context="fork":   创建独立子 Agent 执行，返回结果
    """
    name: str                                    # 技能唯一标识
    description: str                             # 一句话描述（必填，用于 LLM 判断何时调用）
    prompt: str = ""                             # 技能提示词（Markdown body）
    when_to_use: str = ""                        # 何时使用（注入 system prompt）
    arguments: list[str] = field(default_factory=list)       # 命名参数列表
    allowed_tools: list[str] = field(default_factory=list)   # 额外允许的工具
    model: str = ""                              # 指定模型（空=继承主模型）
    context: str = "inline"                      # inline | fork
    agent: str = ""                              # fork 模式下指定的子 Agent 名称

    def format_prompt(self, arguments: dict[str, str]) -> str:
        """替换 prompt 中的 {arg} 占位符"""
        result = self.prompt
        for key, value in arguments.items():
            result = result.replace(f"{{{key}}}", str(value))
        return result


# ═══════════════════════════════════════════════════════════
# SkillRegistry
# ═══════════════════════════════════════════════════════════

class SkillRegistry:
    """技能注册表 — 对应 design.md §6.3"""

    def __init__(self):
        self._skills: dict[str, SkillDefinition] = {}

    def register(self, skill: SkillDefinition) -> None:
        if skill.name in self._skills:
            logger.warning(f"Skill '{skill.name}' already registered, overwriting")
        self._skills[skill.name] = skill

    def get(self, name: str) -> SkillDefinition | None:
        return self._skills.get(name)

    def list_all(self) -> list[SkillDefinition]:
        return list(self._skills.values())

    def list_by_context(self, context: str) -> list[SkillDefinition]:
        return [s for s in self._skills.values() if s.context == context]

    def unregister(self, name: str) -> None:
        self._skills.pop(name, None)

    def match_by_intent(self, intent: str) -> SkillDefinition | None:
        """按意图关键词匹配技能"""
        for skill in self._skills.values():
            if skill.when_to_use:
                keywords = skill.when_to_use.split("|")
                if any(kw.strip() in intent for kw in keywords):
                    return skill
        return None

    def build_skills_prompt_section(self) -> str:
        """生成注入 system prompt 的 <skills> 标签内容"""
        if not self._skills:
            return ""
        lines = ["\n## 可用技能（通过 skills_tool 调用）"]
        for s in self._skills.values():
            args_str = ", ".join(s.arguments) if s.arguments else "无"
            lines.append(f"- **{s.name}**: {s.description}")
            if s.when_to_use:
                lines.append(f"  使用时机: {s.when_to_use}")
            lines.append(f"  参数: {args_str} | 模式: {s.context}")
        lines.append("")
        lines.append("调用方式: skills_tool(skill_name=\"技能名\", arguments={\"参数名\": \"值\"})")
        return "\n".join(lines)


# ═══════════════════════════════════════════════════════════
# SkillLoader — 从 SKILL.md 文件加载技能
# ═══════════════════════════════════════════════════════════

class SkillValidationError(Exception):
    def __init__(self, message: str, errors: list[str] | None = None):
        super().__init__(message)
        self.errors = errors or []


class SkillLoader:
    """
    技能文件加载器 — 对应 design.md §6.3

    从 SKILL.md 文件加载技能定义:
    - discover(skills_dir): 扫描目录下所有 SKILL.md
    - load(skill_path): 加载单个 SKILL.md
    - parse(content): 解析 frontmatter + body
    - validate(skill): 校验必填字段和格式
    """

    @staticmethod
    def discover(skills_dir: str) -> list[SkillDefinition]:
        """扫描目录下所有子目录的 SKILL.md 文件"""
        from pathlib import Path
        skills = []
        base = Path(skills_dir)
        if not base.is_dir():
            return skills

        for skill_md in base.rglob("SKILL.md"):
            try:
                skill = SkillLoader.load(str(skill_md))
                skills.append(skill)
            except (SkillValidationError, Exception) as e:
                logger.warning(f"Failed to load {skill_md}: {e}")
        return skills

    @staticmethod
    def load(skill_path: str) -> SkillDefinition:
        """加载单个 SKILL.md 文件"""
        from pathlib import Path
        path = Path(skill_path)
        if not path.exists():
            raise SkillValidationError(f"File not found: {skill_path}")

        content = path.read_text(encoding="utf-8")
        skill = SkillLoader.parse(content)

        # name 未指定时取目录名
        if not skill.name:
            skill.name = path.parent.name

        SkillLoader.validate(skill)
        return skill

    @staticmethod
    def parse(content: str) -> SkillDefinition:
        """解析 SKILL.md: YAML frontmatter + Markdown body"""
        import yaml

        content = content.strip()
        if not content.startswith("---"):
            raise SkillValidationError("SKILL.md must start with ---")

        # 分离 frontmatter 和 body
        parts = content.split("---", 2)
        if len(parts) < 3:
            raise SkillValidationError("SKILL.md frontmatter not closed (missing second ---)")

        fm_text = parts[1].strip()
        body = parts[2].strip()

        try:
            fm = yaml.safe_load(fm_text) or {}
        except yaml.YAMLError as e:
            raise SkillValidationError(f"YAML parse error: {e}")

        return SkillDefinition(
            name=fm.get("name", ""),
            description=fm.get("description", ""),
            prompt=body,
            when_to_use=fm.get("when_to_use", ""),
            arguments=fm.get("arguments", []),
            allowed_tools=fm.get("allowed-tools", fm.get("allowed_tools", [])),
            model=fm.get("model", ""),
            context=fm.get("context", "inline"),
            agent=fm.get("agent", ""),
        )

    @staticmethod
    def validate(skill: SkillDefinition) -> None:
        """校验技能定义"""
        errors = []
        if not skill.description:
            errors.append("description is required")
        if skill.context not in ("inline", "fork"):
            errors.append(f"context must be 'inline' or 'fork', got '{skill.context}'")
        if not isinstance(skill.arguments, list):
            errors.append("arguments must be a list")
        if not isinstance(skill.allowed_tools, list):
            errors.append("allowed-tools must be a list")
        if errors:
            raise SkillValidationError(f"Validation failed for '{skill.name}'", errors)


# ═══════════════════════════════════════════════════════════
# SkillExecutor — 路由 inline / fork
# ═══════════════════════════════════════════════════════════

class SkillExecutor:
    """
    技能执行调度器 — 对应 design.md §6.4

    inline: 返回 formatted_prompt，LLM 继续推理
    fork(通用): 创建子 Agent，用 skill.prompt 作为 system_prompt
    fork(指定agent): 加载 SubagentConfig 构建专属子 Agent
    """

    def __init__(self, registry: SkillRegistry, context: Any = None, subagent_registry: Any = None):
        self._registry = registry
        self._context = context  # PluginContext
        self._subagent_registry = subagent_registry  # SubagentRegistry

    async def execute(
        self,
        skill_name: str,
        arguments: dict[str, str],
        parent_thread_id: str = "",
    ) -> str:
        """执行技能，返回结果文本"""
        skill = self._registry.get(skill_name)
        if not skill:
            raise SkillExecutionError(f"技能 '{skill_name}' 未注册")

        formatted_prompt = skill.format_prompt(arguments)
        logger.info(f"SkillExecutor: {skill_name} (context={skill.context})")

        if skill.context == "inline":
            return await self._execute_inline(skill, formatted_prompt)
        elif skill.context == "fork":
            return await self._execute_fork(skill, formatted_prompt, arguments)
        else:
            raise SkillExecutionError(f"未知的 context 模式: {skill.context}")

    async def _execute_inline(self, skill: SkillDefinition, prompt: str) -> str:
        """
        inline 模式 — 返回 prompt 文本，由 LLM 继续推理

        对应 design.md §6.4 inline 模式:
        prompt 作为工具返回值注入对话，LLM 根据 prompt 中的 SOP 继续调用 Tool
        """
        logger.info(f"Skill inline: {skill.name} ({len(prompt)} chars)")
        return prompt

    async def _execute_fork(
        self, skill: SkillDefinition, prompt: str, arguments: dict
    ) -> str:
        """
        fork 模式 — 创建独立子 Agent 执行

        对应 design.md §6.4 fork 模式:
        - agent 为空: 通用执行（skill.prompt 作为 instruction）
        - agent 非空: 加载 SubagentConfig 构建专属子 Agent
        """
        if not self._context or not self._context.llm:
            raise SkillExecutionError("fork 模式需要 PluginContext.llm")

        # 检查是否指定了子 Agent 配置
        sub_config = None
        if skill.agent and self._subagent_registry:
            sub_config = self._subagent_registry.get(skill.agent)
            if not sub_config:
                logger.warning(f"SubagentConfig '{skill.agent}' not found, using generic fork")

        if sub_config:
            return await self._execute_fork_with_config(skill, prompt, arguments, sub_config)
        else:
            return await self._execute_fork_generic(skill, prompt, arguments)

    async def _execute_fork_generic(
        self, skill: SkillDefinition, prompt: str, arguments: dict
    ) -> str:
        """通用 fork — 用 create_deep_agent 创建子 Agent"""
        sub_system_prompt = (
            f"你是一个专注于以下任务的专家 Agent。\n\n"
            f"## 任务指令\n{prompt}\n\n"
            f"## 工作规范\n"
            f"1. 必须使用工具获取真实数据，禁止编造\n"
            f"2. 完成任务后直接输出结果，不要询问用户\n"
            f"3. 用中文回答\n"
        )
        sub_registry = self._build_sub_tool_registry(skill)
        return await self._run_fork_agent(skill, sub_system_prompt, sub_registry, arguments)

    async def _execute_fork_with_config(
        self, skill: SkillDefinition, prompt: str, arguments: dict, sub_config: Any
    ) -> str:
        """指定 agent 的 fork — 加载 SubagentConfig"""
        sub_system_prompt = sub_config.system_prompt or prompt
        if prompt and sub_config.system_prompt:
            sub_system_prompt += f"\n\n## 当前任务\n{prompt}"

        from .tools import ToolRegistry
        sub_registry = ToolRegistry()
        if sub_config.tool_names and self._context.tool_registry:
            for tool_name in sub_config.tool_names:
                tool = self._context.tool_registry.find_by_name(tool_name)
                if tool:
                    sub_registry.register(tool)
        else:
            sub_registry = self._build_sub_tool_registry(skill)

        logger.info(f"Skill fork (agent={sub_config.name}): tools={len(sub_registry.all_tools)}")
        return await self._run_fork_agent(skill, sub_system_prompt, sub_registry, arguments)

    def _build_sub_tool_registry(self, skill: SkillDefinition):
        """从主 Agent 的 registry 中裁剪工具集"""
        from .tools import ToolRegistry
        sub_registry = ToolRegistry()
        if skill.allowed_tools and self._context.tool_registry:
            for tool_name in skill.allowed_tools:
                tool = self._context.tool_registry.find_by_name(tool_name)
                if tool:
                    sub_registry.register(tool)
        elif self._context.tool_registry:
            for tool in self._context.tool_registry.all_tools:
                if tool.name != "skills_tool":
                    sub_registry.register(tool)
        return sub_registry

    async def _run_fork_agent(self, skill, system_prompt, tool_registry, arguments) -> str:
        """用 create_deep_agent 创建并执行子 Agent"""
        from .langchain_agent import create_deep_agent, LangChainAgentConfig, adapt_tools

        args_text = "\n".join(f"- {k}: {v}" for k, v in arguments.items()) if arguments else ""
        instruction = skill.description
        if args_text:
            instruction += f"\n\n参数:\n{args_text}"

        # 获取 API 配置（从 PluginContext 的 llm 中提取）
        api_key = ""
        api_base = "https://api.deepseek.com"
        if hasattr(self._context, 'llm') and self._context.llm:
            llm = self._context.llm
            if hasattr(llm, '_async_client'):
                api_key = getattr(llm._async_client, 'api_key', '')
                api_base = str(getattr(llm._async_client, 'base_url', api_base))

        config = LangChainAgentConfig(
            model=skill.model or "deepseek-chat",
            api_key=api_key,
            api_base=api_base,
            tool_registry=tool_registry,
            system_prompt=system_prompt,
        )

        sub_agent = create_deep_agent(config)
        logger.info(f"Skill fork: {skill.name} → 子 Agent 启动")

        result = await sub_agent.ainvoke({
            "messages": [{"role": "user", "content": instruction}]
        })

        # 提取最后一条 AI 消息作为结果
        messages = result.get("messages", [])
        for msg in reversed(messages):
            if hasattr(msg, "content") and msg.content and not hasattr(msg, "tool_calls"):
                logger.info(f"Skill fork: {skill.name} → 完成")
                return msg.content

        return "子 Agent 执行完成但无输出"


class SkillExecutionError(Exception):
    pass


# ═══════════════════════════════════════════════════════════
# SkillsTool — LLM 调用技能的统一入口
# ═══════════════════════════════════════════════════════════

class SkillsTool(Tool):
    """
    技能调用工具 — 对应 design.md §6.5

    注册到 ToolRegistry，LLM 通过 function calling 调用:
    skills_tool(skill_name="verify_config", arguments={"entity": "opportunity"})
    """

    def __init__(self, executor: SkillExecutor):
        self._executor = executor

    @property
    def name(self) -> str:
        return "skills_tool"

    def input_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "skill_name": {
                    "type": "string",
                    "description": "要调用的技能名称",
                },
                "arguments": {
                    "type": "object",
                    "description": "传递给技能的命名参数（键值对）",
                    "additionalProperties": {"type": "string"},
                },
            },
            "required": ["skill_name"],
        }

    async def call(self, input_data: dict, context: Any, on_progress=None) -> ToolResult:
        skill_name = input_data.get("skill_name", "")
        arguments = input_data.get("arguments", {})

        try:
            result = await self._executor.execute(skill_name, arguments)
            return ToolResult(content=result)
        except SkillExecutionError as e:
            return ToolResult(content=f"技能执行失败: {e}", is_error=True)
        except Exception as e:
            logger.error(f"SkillsTool error: {e}")
            return ToolResult(content=f"技能执行异常: {e}", is_error=True)

    def prompt(self) -> str:
        return (
            "调用已注册的技能。传入 skill_name（技能名称）和 arguments（参数字典）。"
            "技能会返回执行指引或分析结果。"
        )
