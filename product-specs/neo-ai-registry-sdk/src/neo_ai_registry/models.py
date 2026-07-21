"""数据模型 — 注册表核心实体（Tool + Middleware）

统一模型设计：
- ToolDefinition: 同时作为数据模型和基类
  - 有 execute() 方法 → builtin（本地执行）
  - 无 execute() 方法 → remote（FeignClient 远程调用）
- MiddlewareDefinition: 同理

所有 Tool/Middleware 统一走 Registry 注册，调用方通过 has_execute() 判断执行路径。
"""
from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


# ═══════════════════════════════════════════════════════════
# 枚举定义
# ═══════════════════════════════════════════════════════════

class ToolType(str, Enum):
    """Tool 执行类型"""
    BUILTIN = "builtin"     # Agent 进程内执行（有 execute 方法）
    REMOTE = "remote"       # HTTP 回调业务域服务（通过 FeignClient）
    MCP = "mcp"             # 经 neo-ai-mcp-service 执行


class MiddlewareHook(str, Enum):
    """中间件钩子类型"""
    BEFORE_AGENT = "before_agent"
    AFTER_AGENT = "after_agent"
    BEFORE_MODEL = "before_model"
    AFTER_MODEL = "after_model"
    WRAP_TOOL_CALL = "wrap_tool_call"


# ═══════════════════════════════════════════════════════════
# ToolDefinition — 统一模型（数据模型 + 可继承基类）
# ═══════════════════════════════════════════════════════════

class ToolDefinition(BaseModel):
    """Tool 统一定义 — 既是注册元数据，也是 Builtin Tool 的基类

    使用方式一：Remote Tool（纯数据注册，从 YAML/DB 加载）
        tool = ToolDefinition(api_key="query_customer", name="查询客户", type=ToolType.REMOTE, service="neo-ai-salescloud-service")

    使用方式二：Builtin Tool（继承并实现 execute 方法）
        class AskUserTool(ToolDefinition):
            api_key: str = "ask_user"
            name: str = "向用户提问确认"
            type: ToolType = ToolType.BUILTIN

            async def execute(self, input_data: dict, context: dict) -> dict:
                return {"answer": "确认"}
    """

    api_key: str = Field("", description="Tool 唯一标识")
    name: str = Field("", description="Tool 显示名称")
    description: str = Field("", description="功能描述（注入 LLM Function Calling）")
    domain: str = Field("", description="所属业务域（sales/marketing/basic/platform）")

    # 执行方式
    type: ToolType = Field(ToolType.REMOTE, description="执行类型（builtin/remote/mcp）")
    service: str = Field("", description="目标服务名（type=remote 时必填）")
    input_schema: dict[str, Any] = Field(default_factory=dict, description="JSON Schema 入参定义")

    # 安全与限制
    read_only_flg: bool = Field(True, description="是否只读操作")
    timeout_ms: int = Field(5000, description="超时时间（毫秒）")

    # 元信息
    category: str = Field("", description="分类标签")
    tags: list[str] = Field(default_factory=list, description="标签列表")
    sort_num: int = Field(0, description="排序权重")
    enabled_flg: bool = Field(True, description="是否启用")

    class Config:
        arbitrary_types_allowed = True

    def has_execute(self) -> bool:
        """判断是否有本地执行能力（已废弃，builtin tool 直接继承 BaseTool）"""
        return False

    def is_builtin(self) -> bool:
        """判断是否为 builtin 类型"""
        return self.type == ToolType.BUILTIN

    def to_base_tool(self, transport: Any) -> Any:
        """转换为 LangChain BaseTool 实例（类比 MiddlewareDefinition.to_agent_middleware）

        动态生成 BaseTool 子类：
        - args_schema 从 input_schema 生成（含 InjectedState）
        - builtin: _arun 调 execute()
        - remote: _arun 通过 FeignClient 远程调用

        Args:
            transport: Transport 实例。

        Returns:
            BaseTool 实例。
        """
        from neo_ai_registry.agent.tool_adapter import create_base_tool
        return create_base_tool(self, transport)

    @staticmethod
    def to_base_tools(definitions: list["ToolDefinition"], transport: Any) -> list:
        """批量转换为 BaseTool 列表

        Args:
            definitions: ToolDefinition 列表。
            transport: Transport 实例。

        Returns:
            BaseTool 实例列表。
        """
        from neo_ai_registry.agent.tool_adapter import create_base_tools
        return create_base_tools(definitions, transport)


# ═══════════════════════════════════════════════════════════
# MiddlewareDefinition — 纯数据模型（Remote middleware 注册）
# ═══════════════════════════════════════════════════════════

class MiddlewareDefinition(BaseModel):
    """Middleware 注册定义 — 纯数据模型

    描述一个远程业务切面的元数据。通过 to_agent_middleware(transport) 转换为
    LangChain AgentMiddleware 实例，可直接传给 create_agent(middleware=[...])。

    转换时参数适配：
    - LangGraph 侧：AgentMiddleware 钩子接收 (state: AgentState, runtime)
    - Provider 侧：统一 REST 接口 (hook, payload, state: ToolState)
    - 桥接逻辑：from_agent_state() 提取 → 远程调用 → state_patch → write_back()

    Usage:
        definition = MiddlewareDefinition(
            api_key="crm_query_state",
            service="neo-ai-provider-demo",
            hooks=["before_agent", "after_model"],
        )

        # 转换为 AgentMiddleware（类比 ToolState.from_agent_state）
        agent_mw = definition.to_agent_middleware(transport)
        create_agent(middleware=[..., agent_mw])
    """

    api_key: str = Field("", description="中间件唯一标识")
    name: str = Field("", description="中间件显示名称")
    description: str = Field("", description="功能描述")

    # 执行配置
    hooks: list[str] = Field(default_factory=list, description="激活的生命周期钩子")
    service: str = Field("", description="目标服务名（Eureka 注册名）")

    # 排序与控制
    sort_num: int = Field(0, description="执行顺序（越小越先执行）")
    enabled_flg: bool = Field(True, description="是否启用")
    required_features: list[str] = Field(default_factory=list, description="依赖的 Feature 开关")

    def to_agent_middleware(self, transport: Any) -> Any:
        """转换为 AgentMiddleware 实例（类比 ToolState.from_agent_state）

        动态生成类，只覆写 hooks 中声明的方法。LangGraph 的 create_agent
        通过 `cls.METHOD is not AgentMiddleware.METHOD` 检测覆写，
        只为实际覆写的方法注册图节点。

        钩子内部参数转换：
            AgentState → ToolState.from_agent_state() → 序列化为 (hook, payload, state)
            → FeignClient 远程调用 Provider
            → response.state_patch → ToolState.merge_patch() → write_back(AgentState)

        Args:
            transport: Transport 实例（NeoApiTransport）。

        Returns:
            AgentMiddleware 实例。
        """
        from neo_ai_registry.agent.middleware_adapter import create_remote_middleware
        return create_remote_middleware(self, transport)

    @staticmethod
    def to_agent_middlewares(definitions: list["MiddlewareDefinition"], transport: Any) -> list:
        """批量转换（按 sort_num 排序后转换）

        Args:
            definitions: MiddlewareDefinition 列表。
            transport: Transport 实例。

        Returns:
            AgentMiddleware 实例列表（已排序）。
        """
        sorted_defs = sorted(definitions, key=lambda d: d.sort_num)
        return [d.to_agent_middleware(transport) for d in sorted_defs]
