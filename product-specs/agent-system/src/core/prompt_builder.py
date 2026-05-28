"""系统提示词生成器 — Markdown 分层结构化提示词

采用 Markdown 标题层级作为主结构，适配 DeepSeek/豆包/OpenAI 系列模型：
- # 一级标题 + --- 分隔线：强分区（角色/安全/工具/技能/规范/记忆）
- ## 二级标题：模块内分段
- 有序列表：暗示优先级
- <skills> 标签：唯一保留的 XML 标记，用于语义隔离（告诉 LLM 这是描述不是指令）

优先级规则（从高到低）：
  安全边界 > 角色定义 > 工具规范 > 回复规范 > 用户行为规则(记忆) > 技能描述
"""
from __future__ import annotations

from typing import Any
import logging
logger = logging.getLogger(__name__)



# ═══════════════════════════════════════════════════════════
# 分区模板：每个分区独立维护，build_system_prompt 按顺序拼装
# ═══════════════════════════════════════════════════════════

SECTION_IDENTITY_BASE = """\
# 角色

你是面向企业 CRM SaaS 平台的智能业务助手，服务于销售团队、客户成功团队和管理层。

行为原则：
1. 先做后说 — 能直接执行的不描述计划
2. 数据驱动 — 数据类回答必须基于工具查询，严禁编造
3. 最小追问 — 能通过查询推断的不问用户
4. 结果导向 — 只输出用户需要的信息"""

# 向后兼容
SECTION_IDENTITY = SECTION_IDENTITY_BASE


SECTION_GUARDRAILS = """\
# 安全边界

> 优先级最高，任何其他指令不得突破。

1. **租户隔离**: 所有查询限定当前租户，不得跨租户访问
2. **数据真实**: 严禁编造数据，必须使用工具获取
3. **修改确认**: 数据修改前确认操作内容和影响范围；批量操作先统计数量、展示样本再执行
4. **输出纯净**: 严禁输出意图分析、NLU 标注、内部推理步骤"""


SECTION_TOOLS_HEADER = """\
# 工具使用规范

## 调用规则

1. **先查后答** — 数据问题先调工具，再基于结果回答
2. **记忆≠数据源** — 记忆中的 data_id 可作为参数，但具体数据必须实时查询
3. **智能查询** — query_data 内置字段识别，常规查询直接调用无需先查 schema
4. **参数准确** — entity_api_key 使用小写驼峰（account, opportunity, contact, activity, lead）
5. **多步执行** — 一次工具调用不够时，可连续调用多个工具，最终汇总结果再回复用户

## 工具 vs 技能选择

- **优先用技能** — `<skills>` 中某个技能的 description/when_to_use 覆盖了用户意图时，调用 skills_tool。技能内部已编排多步流程，结果更完整。
- **用基础工具** — 用户意图是简单单步操作（查一条数据、改一个字段、统计一个指标），或没有匹配技能时。

## 技能调用（skills_tool）

技能清单在 `<skills>` 段落中动态注入。调用方式：skills_tool(skill_name="技能名", arguments={"参数名": "值"})

收到技能结果后：
- `[SKILL_DONE:silent]` → 不输出任何内容，直接结束
- `[SKILL_DONE:summarize]` → 1-2 句引导，不重复内容
- `[SKILL_DONE:continue]` → 继续后续步骤
- `[SKILL_DONE:passthrough]` → 完整呈现给用户

## 子 Agent 委派（agent_tool）

仅当任务需要独立上下文且复杂度高时：多源调研、批量处理、深度统计。

## 澄清追问（ask_clarification）

必须追问：缺关键参数且无法推断、多匹配无法判断、不可逆操作需确认。
禁止追问：意图明确直接执行、可查询推断先查再答、记忆已有答案直接用。

## 示例

用户: "分析一下华为这个客户的情况"
思考: 记忆中有华为 data_id=acc_001，<skills> 中 customer_360 匹配"分析客户情况"
→ skills_tool(skill_name="customer_360", arguments={"customer_id": "acc_001"})

用户: "华为有几个在跟的商机"
思考: 简单统计，无需技能
→ analyze_data(entity_api_key="opportunity", ...)
→ 基于结果回复

用户: "上个月新增的客户里哪些还没有联系人"
思考: 需要两步——先查客户，再查联系人
→ query_data(entity_api_key="account", ...)
→ query_data(entity_api_key="contact", ...)
→ 汇总结果回复"""


# 向后兼容：保留旧变量名（静态版本，无动态工具清单）
SECTION_TOOLS = SECTION_TOOLS_HEADER


SECTION_INSTRUCTIONS = """\
# 回复规范

- 中文回答，专业但易懂
- 数据用 Markdown 表格展示
- 金额用万/亿，百分比保留 1 位小数
- 分析结论附带数据支撑
- 建议按优先级排序，每条可执行
- 不输出过渡语（"我来帮你查"），直接给结果
- 空结果告知用户并建议调整条件
- 工具报错用通俗语言解释，不暴露技术细节
- 链接必须使用 Markdown 格式 [显示文字](URL)，不要裸露 URL，不要省略 URL 只写文字
- 当工具返回了 Markdown 链接（如 [文件名](https://...)），必须在回复中原样保留该链接，不得只写文件名"""


# ═══════════════════════════════════════════════════════════
# fork 子 Agent 通用提示词（也采用 Markdown 分层）
# ═══════════════════════════════════════════════════════════

FORK_AGENT_PROMPT = """\
# 角色

你是一个专注于特定任务的专家 Agent，由主 Agent 委派执行独立任务。

---

# 安全边界

> 以下规则不可违反。

1. 必须使用工具获取真实数据，禁止编造
2. 不得跨租户访问数据

---

# 工作规范

1. 严格按照任务指令执行，不要偏离主题
2. 完成任务后直接输出结果，不要反问用户
3. 输出结果必须包含具体数据和分析结论
4. 使用中文回答，数据展示使用 Markdown 表格

---

# 任务指令

{prompt}"""


# ═══════════════════════════════════════════════════════════
# 构建函数
# ═══════════════════════════════════════════════════════════

# 向后兼容：保留旧变量名，指向新的组合结果
CRM_SYSTEM_PROMPT = "\n\n---\n\n".join([
    SECTION_IDENTITY,
    SECTION_GUARDRAILS,
    SECTION_TOOLS,
    SECTION_INSTRUCTIONS,
])


def build_system_prompt(
    agent_name: str = "DeepAgent",
    skills: list | None = None,
    tools: list | None = None,
    memory_context: str = "",
    custom_prompt: str = "",
    agent_rules: str = "",
) -> str:
    """根据配置、工具、技能和记忆上下文生成系统提示词

    最终结构（Markdown 分层）：
      # 角色          ← SECTION_IDENTITY + agent_rules 动态融合
      ---
      # 安全边界      ← SECTION_GUARDRAILS（最高优先级）
      ---
      # 工具使用规范  ← SECTION_TOOLS_HEADER + 动态工具清单
      ---
      # 可用技能      ← 动态生成（skills 参数）
      ---
      # 回复规范      ← SECTION_INSTRUCTIONS
      ---
      # 记忆上下文    ← 动态注入（memory_context 参数）

    Args:
        agent_name: Agent 名称标识
        skills: 已加载的技能列表（SkillDefinition）
        tools: 已注册的工具列表（Tool 实例或具有 name/description 属性的对象），
               用于在系统提示词中生成可用工具清单
        memory_context: 记忆系统注入的上下文（召回记忆，不含 agent_rules）
        custom_prompt: 自定义提示词（非空时替代默认分区组合）
        agent_rules: 用户定义的行为规则（来自长期记忆 agent_rules 分类），
                     包含角色定义和行为约束，会融入 # 角色 分区
    """
    sections: list[str] = []

    # 1. 基础分区（自定义 prompt 时跳过默认分区）
    if custom_prompt:
        sections.append(custom_prompt)
    else:
        # 角色分区：基础定义 + 用户自定义的角色/行为规则
        identity_section = _build_identity_section(agent_rules)
        sections.append(identity_section)
        sections.append(SECTION_GUARDRAILS)
        # 工具规范 + 动态工具清单
        tools_section = _build_tools_section(tools)
        sections.append(tools_section)

    # 2. 技能段落（动态生成）
    skills_section = _build_skills_section(skills)
    if skills_section:
        sections.append(skills_section)

    # 3. 回复规范（自定义 prompt 时不追加，由自定义 prompt 自行包含）
    if not custom_prompt:
        sections.append(SECTION_INSTRUCTIONS)

    # 4. 记忆上下文（运行时注入）
    if memory_context and memory_context.strip():
        sections.append(_build_memory_section(memory_context))

    return "\n\n---\n\n".join(sections)


def _build_tools_section(tools: list | None = None) -> str:
    """构建工具使用规范分区 — 静态规则 + 动态工具清单

    将当前 Agent 实际可用的工具列表格式化注入系统提示词，
    让 LLM 明确知道自己有哪些工具可以调用。

    工具清单格式：
      | 工具名 | 说明 |
      |--------|------|
      | query_schema | 查询元数据定义 |
      | query_data   | 查询业务数据   |
      ...

    Args:
        tools: 已注册的工具列表。支持两种类型：
               - src.tools.base.Tool 实例（有 name 属性 + prompt() 方法）
               - LangChain BaseTool 实例（有 name + description 属性）
    """
    if not tools:
        # 无工具列表时回退到静态版本
        return SECTION_TOOLS_HEADER

    # 生成动态工具清单
    tool_rows: list[str] = []
    for tool in tools:
        tool_name = _get_tool_name(tool)
        tool_desc = _get_tool_short_description(tool)
        if tool_name:
            tool_rows.append(f"| {tool_name} | {tool_desc} |")

    if not tool_rows:
        return SECTION_TOOLS_HEADER

    tools_table = (
        "## 可用工具清单\n\n"
        "以下是当前已注册的全部工具，你只能调用此清单中的工具：\n\n"
        "| 工具名 | 说明 |\n"
        "|--------|------|\n"
        + "\n".join(tool_rows)
    )

    return f"{SECTION_TOOLS_HEADER}\n\n{tools_table}"


def _get_tool_name(tool: Any) -> str:
    """从工具对象提取名称（兼容 Tool 基类和 LangChain BaseTool）"""
    if hasattr(tool, "name"):
        name = tool.name
        # name 可能是 property 或普通属性
        return name if isinstance(name, str) else str(name)
    return ""


def _get_tool_short_description(tool: Any) -> str:
    """从工具对象提取简短描述（一句话）

    优先级：
    1. Tool 基类的 prompt() 方法 → 取第一行
    2. LangChain BaseTool 的 description 属性 → 取第一句
    3. 类的 docstring → 取第一行
    4. 兜底返回工具名
    """
    # 尝试 prompt() 方法（自定义 Tool 基类）
    if hasattr(tool, "prompt") and callable(tool.prompt):
        try:
            prompt_text = tool.prompt()
            if prompt_text and prompt_text.strip():
                first_line = prompt_text.strip().split("\n")[0]
                # 截断过长的描述（取第一句或前60字）
                return _truncate_description(first_line)
        except Exception:
            logger.exception("_get_tool_short_description 异常")

    # 尝试 description 属性（LangChain BaseTool）
    if hasattr(tool, "description"):
        desc = tool.description
        if desc and isinstance(desc, str) and desc.strip():
            first_line = desc.strip().split("\n")[0]
            return _truncate_description(first_line)

    # 尝试 docstring
    doc = getattr(tool, "__doc__", None) or getattr(type(tool), "__doc__", None)
    if doc and doc.strip():
        first_line = doc.strip().split("\n")[0]
        return _truncate_description(first_line)

    return _get_tool_name(tool)


def _truncate_description(text: str, max_len: int = 80) -> str:
    """截断描述到合理长度"""
    # 去掉 Markdown 格式符号
    text = text.strip().rstrip("。.").strip()
    if len(text) <= max_len:
        return text
    # 尝试在句号/逗号处截断
    for sep in ("。", "，", "；", ".", ",", ";", " — ", "—"):
        idx = text.find(sep, 20)
        if 0 < idx <= max_len:
            return text[:idx]
    return text[:max_len] + "…"


def _build_identity_section(agent_rules: str = "") -> str:
    """构建角色分区 — 基础定义 + 用户自定义行为规则的动态融合

    agent_rules 来自长期记忆系统，典型内容如：
    - "你是我的数据分析助理，回复不超过100字"
    - "角色为销售教练。跟华为沟通用正式语气。报告含同比数据。"

    融合策略：
    - 基础角色定义始终保留（CRM 业务助手的核心定位不变）
    - agent_rules 作为"用户个性化补充"追加在基础定义之后
    - 用 ## 二级标题区分"平台角色"和"用户定制"，让 LLM 明确两者关系
    - 安全边界中已声明 agent_rules 不可突破安全约束

    为什么融入角色分区而非独立 SystemMessage：
    1. LLM 对 system prompt 开头的内容注意力最强
    2. 角色定义和行为规则本质上都在回答"我应该怎么表现"
    3. 放在一起避免 LLM 看到两个矛盾的"身份描述"
    """
    if not agent_rules or not agent_rules.strip():
        return SECTION_IDENTITY_BASE

    return (
        f"{SECTION_IDENTITY_BASE}\n\n"
        f"## 用户定制规则\n\n"
        f"> 以下是当前用户对你的个性化定义，在不违反安全边界的前提下遵守。\n\n"
        f"{agent_rules.strip()}"
    )


def _build_skills_section(skills: list | None) -> str:
    """生成技能段落 — 用 <skills> 标签包裹，语义隔离

    <skills> 标签告诉 LLM：这段内容是技能描述，不是让你直接执行的指令。
    LLM 通过 skills_tool 工具调用技能，而非直接执行 prompt 内容。
    """
    if not skills:
        return ""

    lines = ["# 可用技能", ""]
    lines.append("通过 `skills_tool(skill_name=\"技能名\", arguments={...})` 调用。")
    lines.append("")
    lines.append("**重要规则：当用户意图匹配某个技能的「使用时机」关键词时，必须立即调用 skills_tool，禁止自行回答或追问。**")
    lines.append("")
    lines.append("<skills>")

    for skill in skills:
        if skill.context == "fork":
            # fork 技能：注入 name/description/when_to_use/arguments，不注入 prompt
            args_str = ", ".join(skill.arguments) if skill.arguments else "无"
            lines.append(f"")
            lines.append(f"## {skill.name}")
            lines.append(f"{skill.description}")
            if skill.when_to_use:
                lines.append(f"- **触发条件（匹配任一关键词即调用）**: {skill.when_to_use}")
            lines.append(f"- 参数: {args_str}")
            lines.append(f"- 模式: fork（独立子 Agent 执行，不要自己做）")

        elif skill.context == "inline" and skill.prompt and skill.prompt.strip():
            # inline 技能且 prompt 非空：注入完整段落
            args_str = ", ".join(skill.arguments) if skill.arguments else "无"
            lines.append(f"")
            lines.append(f"## {skill.name}")
            lines.append(f"{skill.description}")
            if skill.when_to_use:
                lines.append(f"- 使用时机: {skill.when_to_use}")
            lines.append(f"- 参数: {args_str}")
            lines.append(f"- 模式: inline（注入当前上下文）")
            lines.append(f"")
            lines.append(skill.prompt.strip())

        # inline 且 prompt 为空：跳过（与 v2 对齐）

    lines.append("")
    lines.append("</skills>")

    # 检查是否有实际内容（排除只有标题和标签的情况）
    has_content = any(
        (s.context == "fork") or (s.context == "inline" and s.prompt and s.prompt.strip())
        for s in skills
    )
    if not has_content:
        return ""

    return "\n".join(lines)


def _build_memory_section(memory_context: str) -> str:
    """格式化记忆上下文段落

    记忆上下文可能包含：
    - agent_rules（用户定义的行为约束）— 由 MemoryMiddleware 注入
    - 召回的相关记忆 — 由 MemoryMiddleware 注入

    统一包裹在 # 记忆上下文 标题下，附带使用规则。
    """
    rules = (
        "## 记忆使用规则\n"
        "1. data_id 可直接作为工具参数\n"
        "2. [entities] 实体事实可信度高，直接使用\n"
        "3. [preferences] 影响输出格式，[agent_rules] 遵循其指令\n"
        "4. 具体数据（金额、状态）可能过时，必须重新查询\n"
        "5. 多条记忆同一主题以最近为准"
    )
    return f"# 记忆上下文\n\n{rules}\n\n{memory_context.strip()}"


def build_fork_prompt(task_prompt: str) -> str:
    """构建 fork 子 Agent 的系统提示词

    采用与主 Agent 一致的 Markdown 分层结构，
    确保子 Agent 也有明确的安全边界和工作规范。
    """
    return FORK_AGENT_PROMPT.format(prompt=task_prompt)
