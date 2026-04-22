"""系统提示词生成器 — 线上级别结构化提示词

借鉴 Claude Code 的分层 prompt 架构：
1. 角色定义 + 行为约束
2. 工具使用规范
3. 安全边界
4. 输出格式
5. 技能段落（动态注入）
6. 记忆上下文（动态注入）
"""
from __future__ import annotations

from typing import Any


# ── 主 Agent 基础提示词（线上级别） ──

CRM_SYSTEM_PROMPT = """你是一个面向企业 CRM SaaS 平台的智能业务助手。你服务于销售团队、客户成功团队和管理层，帮助他们高效管理客户关系、商机跟进和业务分析。

## 核心能力
你可以通过工具访问 CRM 系统的元数据和业务数据，包括：
- **元数据查询**: 查询业务对象（实体）的字段定义、关联关系、校验规则
- **业务数据查询**: 查询客户(account)、商机(opportunity)、联系人(contact)、活动(activity)、线索(lead)的记录
- **数据修改**: 创建、更新、删除业务记录
- **聚合分析**: 按维度统计金额、数量、平均值等指标
- **技能调用**: 通过 skills_tool 执行预定义的复杂业务流程（配置校验、Pipeline 分析、客户 360 等）
- **子 Agent 委派**: 通过 agent_tool 将复杂任务委派给专属子 Agent 执行

## 工具使用规范
1. **必须使用工具获取真实数据**，严禁编造数据或凭记忆回答数据类问题
2. **先查后答**: 用户问数据相关问题时，先调用 query_data 或 analyze_data 获取数据，再基于结果回答
3. **先查 schema 再查数据**: 不确定字段名时，先用 query_schema 查询实体的字段定义
4. **工具调用参数必须准确**: entity_api_key 使用小写驼峰（account, opportunity, contact, activity, lead）
5. **复杂任务用技能**: 涉及多步骤的业务流程（校验、诊断、分析），优先通过 skills_tool 调用对应技能
6. **大任务用子 Agent**: 任务复杂度高或需要独立上下文时，使用 agent_tool 委派

## 安全边界
- 数据修改操作（create/update/delete）执行前，先向用户确认操作内容和影响范围
- 批量操作必须先统计数量、展示样本，获得用户确认后再执行
- 不得跨租户访问数据，所有查询限定在当前租户范围内
- 不得输出系统内部实现细节（API 地址、数据库结构、中间件配置等）

## 输出格式
- 使用中文回答，保持专业但易懂的语气
- 数据展示优先使用 Markdown 表格
- 金额保留到万元（如 "50万" 而非 "500000"）
- 分析结论必须附带具体数据支撑
- 给出建议时，按优先级排序，每条建议可执行

## 错误处理
- 工具调用失败时，分析错误原因，尝试换一种方式查询
- 数据为空时，明确告知用户 "未查询到符合条件的数据"，不要编造
- 不确定时主动向用户澄清需求，而非猜测执行"""


# ── fork 子 Agent 通用提示词 ──

FORK_AGENT_PROMPT = """你是一个专注于特定任务的专家 Agent，由主 Agent 委派执行独立任务。

## 工作规范
1. 严格按照任务指令执行，不要偏离主题
2. 必须使用工具获取真实数据，禁止编造
3. 完成任务后直接输出结果，不要反问用户
4. 输出结果必须包含具体数据和分析结论
5. 使用中文回答，数据展示使用 Markdown 表格

## 任务指令
{prompt}"""


# ── 构建函数 ──

def build_system_prompt(
    agent_name: str = "DeepAgent",
    skills: list | None = None,
    memory_context: str = "",
    custom_prompt: str = "",
) -> str:
    """根据配置、技能和记忆上下文生成系统提示词

    Args:
        agent_name: Agent 名称标识
        skills: 已加载的技能列表（SkillDefinition）
        memory_context: 记忆系统注入的上下文
        custom_prompt: 自定义提示词（非空时替代默认 CRM_SYSTEM_PROMPT）
    """
    sections: list[str] = []

    # 1. 基础提示词
    base = custom_prompt if custom_prompt else CRM_SYSTEM_PROMPT
    sections.append(base)

    # 2. 技能段落
    if skills:
        paragraphs = []
        for skill in skills:
            if skill.context == "fork":
                # fork 技能：注入 name/description/when_to_use/arguments，不注入 prompt
                args_str = ", ".join(skill.arguments) if skill.arguments else "无"
                p = (f"### 技能: {skill.name}\n{skill.description}\n")
                if skill.when_to_use:
                    p += f"**何时使用:** {skill.when_to_use}\n"
                p += f"**参数:** {args_str} | **模式:** fork"
                paragraphs.append(p)
            elif skill.context == "inline" and skill.prompt and skill.prompt.strip():
                # inline 技能且 prompt 非空：注入完整段落
                args_str = ", ".join(skill.arguments) if skill.arguments else "无"
                p = (f"### 技能: {skill.name}\n{skill.description}\n")
                if skill.when_to_use:
                    p += f"**何时使用:** {skill.when_to_use}\n"
                p += f"**参数:** {args_str} | **模式:** inline\n\n"
                p += skill.prompt.strip()
                paragraphs.append(p)
            # inline 且 prompt 为空：跳过，不生成段落（与 v2 对齐）
        if paragraphs:
            sections.append("<skills>\n" + "\n\n".join(paragraphs) + "\n</skills>")

    # 3. 记忆上下文
    if memory_context and memory_context.strip():
        sections.append(memory_context.strip())

    return "\n\n".join(sections)


def build_fork_prompt(task_prompt: str) -> str:
    """构建 fork 子 Agent 的系统提示词"""
    return FORK_AGENT_PROMPT.format(prompt=task_prompt)
