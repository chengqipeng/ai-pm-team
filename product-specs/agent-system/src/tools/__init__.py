"""tools — Tool 基类、ToolRegistry、ToolLoader、AgentTool、SkillsTool、CRM 工具"""
from .base import Tool, ToolRegistry
from .loader import ToolLoader
from .crm_backend import CrmSimulatedBackend
from .crm_tools import register_crm_tools

# 延迟导入避免循环依赖（skills_tool → skills.base → tools.base）
def __getattr__(name):
    if name == "PydanticSkillsTool" or name == "SkillsToolInput":
        from .skills_tool import SkillsTool as PydanticSkillsTool, SkillsToolInput
        return PydanticSkillsTool if name == "PydanticSkillsTool" else SkillsToolInput
    if name == "AgentTool" or name == "AgentToolInput":
        from .agent_tool import AgentTool, AgentToolInput
        return AgentTool if name == "AgentTool" else AgentToolInput
    raise AttributeError(f"module 'src.tools' has no attribute {name!r}")
