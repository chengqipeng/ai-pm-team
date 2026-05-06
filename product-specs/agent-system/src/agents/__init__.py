"""agents — Agent 工厂、配置、加载、适配器、子 Agent"""
from .agent_config import AgentConfig, AgentLoader, AgentRegistry, Features
from .agent_factory import AgentFactory
from .langchain_agent import create_deep_agent, adapt_tools, LangChainAgentConfig
from .subagent_config import (SubagentConfig, SubagentRegistry, SubagentDefinition,
                               SubagentTask, SubagentResult, TaskType)
from .subagent_factory import SubagentFactory
from .subagent_executor import SubagentExecutor
from .adapter import NeoAgentV2Adapter, neo_agent_v2_adapter
