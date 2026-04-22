"""tools — Tool 基类、ToolRegistry、ToolLoader、AgentTool、SkillsTool、CRM 工具"""
from .base import Tool, ToolRegistry
from .loader import ToolLoader
from .agent_tool import AgentTool, AgentToolInput
from .skills_tool import SkillsTool as PydanticSkillsTool, SkillsToolInput
from .crm_backend import CrmSimulatedBackend
from .crm_tools import register_crm_tools
