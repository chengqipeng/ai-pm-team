"""Provider 抽象基类 — 按类型定义接口

业务域服务（neo-ai-salescloud-service 等）实现这些接口，
提供 HTTP API 供 Agent 运行时通过 FeignClient 远程调用。

设计参考 v1 NeoApiClient 的调用模式：
    - 按服务名调用（app_name），而非硬编码 URL
    - Tool 和 Middleware 均通过远程 HTTP 回调执行
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from neo_ai_registry.models import MiddlewareDefinition


class ToolProvider(ABC):
    """Tool Provider 抽象接口

    业务域服务实现此接口，对外暴露 Tool 执行能力。
    Agent 运行时通过 FeignClient 按服务名远程调用。
    """

    @abstractmethod
    def execute_tool(
        self,
        api_key: str,
        input_data: dict[str, Any],
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """根据 api_key 执行指定 Tool

        Args:
            api_key: Tool 唯一标识，对应 ToolDefinition.api_key，
                     用于路由到具体的 Tool handler 实现。
            input_data: Tool 入参字典，字段定义由 ToolDefinition.input_schema 约束，
                        由 LLM Function Calling 生成并传入。
            context: 执行上下文信息（可选），包含：
                     - tenant_id (int): 当前租户 ID
                     - user_id (int): 当前用户 ID
                     - trace_id (str): 链路追踪 ID
                     - thread_id (str): Agent 会话 ID
                     - message_id (str): 当前消息 ID
                     为 None 时表示无上下文。

        Returns:
            Tool 执行结果字典，通常包含：
            - status (str): "success" | "error"
            - data/records/message: 具体业务数据
            返回值将作为 ToolMessage 内容回传给 LLM。

        Raises:
            NotImplementedError: 当 api_key 对应的 handler 未注册时抛出。
        """
        ...


class MiddlewareProvider(ABC):
    """Middleware Provider 抽象接口

    业务域服务实现此接口，对外暴露 Middleware 执行能力。
    Agent 运行时通过 FeignClient 按服务名远程调用中间件钩子。

    设计参考 v1 模式：中间件执行不限于本地实例化，
    支持远程回调业务域服务执行自定义中间件逻辑。
    """

    @abstractmethod
    def execute_middleware(
        self,
        api_key: str,
        hook: str,
        payload: dict[str, Any],
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """根据 api_key 执行指定 Middleware 的某个生命周期钩子

        Args:
            api_key: Middleware 唯一标识，对应 MiddlewareDefinition.api_key，
                     用于路由到具体的 Middleware 实现。
            hook: 生命周期钩子名称，取值范围：
                  - "before_agent": Agent 执行开始前
                  - "after_agent": Agent 执行完成后
                  - "before_model": 每次 LLM 调用前
                  - "after_model": 每次 LLM 调用后
                  - "wrap_tool_call": 工具调用时
            payload: 钩子入参字典，内容因 hook 类型而异：
                     - before_agent/after_agent: {"messages": [...], "state": {...}}
                     - before_model/after_model: {"messages": [...], "model_output": {...}}
                     - wrap_tool_call: {"tool_name": "...", "tool_input": {...}}
            context: 执行上下文信息（可选），包含：
                     - tenant_id (int): 当前租户 ID
                     - user_id (int): 当前用户 ID
                     - trace_id (str): 链路追踪 ID
                     - thread_id (str): Agent 会话 ID
                     - agent_name (str): 当前 Agent 名称

        Returns:
            中间件执行结果字典：
            - action (str): "continue" | "modify" | "abort"
              - "continue": 不修改，继续执行
              - "modify": 修改 state，返回 patch 数据
              - "abort": 中止当前流程
            - patch (dict): action="modify" 时，需要合并到 state 的数据
            - message (str): action="abort" 时，返回给用户的提示信息

        Raises:
            NotImplementedError: 当 api_key 对应的 handler 未注册时抛出。
        """
        ...
