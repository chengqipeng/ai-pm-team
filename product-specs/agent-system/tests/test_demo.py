"""pytest 入口 — 调用 demo.py 中的所有测试函数"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("DEEPSEEK_API_KEY", "sk-a86b7e7ca89e4a4283c0a8a7bcb34b9c")

# 导入 demo 中所有测试函数
from demo import (
    demo_tool_adapter, demo_create_agent,
    demo_skill_definition, demo_skill_executor, demo_skill_loader,
    demo_exceptions, demo_pydantic_skills_tool, demo_agent_tool,
    demo_agent_factory, demo_prompt_builder,
    demo_middleware_imports, demo_guardrail, demo_clarification,
    demo_memory_middleware, demo_plugin_lifecycle,
    demo_micro_compact, demo_auto_compact, demo_full_compact,
    demo_circuit_breaker, demo_tool_loader,
    demo_memory_storage, demo_fts_engine, demo_debounce_queue,
    demo_memory_updater, demo_memory_prompt,
    demo_model_router, demo_skill_generator, demo_agent_config,
    demo_thread_state, demo_output_render, demo_subagent_config,
    demo_real_api,
)

# A. LangChain Agent
test_tool_adapter = demo_tool_adapter
test_create_agent = demo_create_agent

# B. 技能系统
test_skill_definition = demo_skill_definition
test_skill_executor = demo_skill_executor
test_skill_loader = demo_skill_loader

# C. Pydantic 工具 + AgentFactory
test_exceptions = demo_exceptions
test_pydantic_skills_tool = demo_pydantic_skills_tool
test_agent_tool = demo_agent_tool
test_agent_factory = demo_agent_factory
test_prompt_builder = demo_prompt_builder

# D. 中间件
test_middleware_imports = demo_middleware_imports
test_guardrail = demo_guardrail
test_clarification = demo_clarification
test_memory_middleware = demo_memory_middleware
test_plugin_lifecycle = demo_plugin_lifecycle

# E. 三层压缩
test_micro_compact = demo_micro_compact
test_auto_compact = demo_auto_compact
test_full_compact = demo_full_compact
test_circuit_breaker = demo_circuit_breaker
test_tool_loader = demo_tool_loader

# F. 记忆系统
test_memory_storage = demo_memory_storage
test_fts_engine = demo_fts_engine
test_debounce_queue = demo_debounce_queue
test_memory_updater = demo_memory_updater
test_memory_prompt = demo_memory_prompt

# G. 路由 / 技能生成 / AgentConfig
test_model_router = demo_model_router
test_skill_generator = demo_skill_generator
test_agent_config = demo_agent_config

# H. ThreadState / OutputRender
test_thread_state = demo_thread_state
test_output_render = demo_output_render
test_subagent_config = demo_subagent_config

# I. 真实 API
test_real_api = demo_real_api
