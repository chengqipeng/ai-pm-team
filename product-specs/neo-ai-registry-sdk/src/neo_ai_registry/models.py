"""数据模型 — 注册表核心实体（Tool + Middleware）

所有模型使用 Pydantic v2 BaseModel，支持：
- JSON Schema 自动生成（用于注册前校验）
- 序列化/反序列化（HTTP 传输）
- 字段默认值和类型约束
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
    BUILTIN = "builtin"     # Agent 进程内执行（纯函数）
    REMOTE = "remote"       # HTTP 回调业务域服务
    MCP = "mcp"             # 经 neo-ai-mcp-service 执行


class MiddlewareHook(str, Enum):
    """中间件钩子类型"""
    BEFORE_AGENT = "before_agent"
    AFTER_AGENT = "after_agent"
    BEFORE_MODEL = "before_model"
    AFTER_MODEL = "after_model"
    WRAP_TOOL_CALL = "wrap_tool_call"


# ═══════════════════════════════════════════════════════════
# Tool 定义
# ═══════════════════════════════════════════════════════════

class ToolDefinition(BaseModel):
    """Tool 注册定义"""

    api_key: str = Field(..., description="Tool 唯一标识")
    name: str = Field(..., description="Tool 显示名称")
    description: str = Field("", description="功能描述（注入 LLM Function Calling）")
    domain: str = Field("", description="所属业务域（sales/marketing/basic/platform）")

    # 执行方式
    type: ToolType = Field(ToolType.BUILTIN, description="执行类型")
    endpoint: str = Field("", description="远程 Tool 回调地址（type=remote 时必填）")
    input_schema: dict[str, Any] = Field(default_factory=dict, description="JSON Schema 入参定义")
    output_schema: dict[str, Any] = Field(default_factory=dict, description="JSON Schema 出参定义")

    # 安全与限制
    read_only_flg: bool = Field(True, description="是否只读操作")
    destructive_flg: bool = Field(False, description="是否破坏性操作")
    timeout_ms: int = Field(5000, description="超时时间（毫秒）")
    retry_policy: dict[str, Any] = Field(
        default_factory=lambda: {"max_retries": 2, "backoff_ms": 1000},
        description="重试策略",
    )

    # 元信息
    category: str = Field("", description="分类标签")
    tags: list[str] = Field(default_factory=list, description="标签列表")
    icon: str = Field("", description="图标")
    sort_num: int = Field(0, description="排序权重")
    enabled_flg: bool = Field(True, description="是否启用")

    # Prompt 注入（可选）
    prompt: str = Field("", description="Tool 使用说明，注入 system prompt")


# ═══════════════════════════════════════════════════════════
# Middleware 定义
# ═══════════════════════════════════════════════════════════

class MiddlewareDefinition(BaseModel):
    """Middleware 注册定义"""

    api_key: str = Field(..., description="中间件唯一标识")
    name: str = Field(..., description="中间件显示名称")
    description: str = Field("", description="功能描述")

    # 执行配置
    hooks: list[MiddlewareHook] = Field(
        default_factory=list,
        description="激活的生命周期钩子",
    )
    module_path: str = Field("", description="Python 模块路径（如 src.middleware.logging）")
    class_name: str = Field("", description="中间件类名")
    config: dict[str, Any] = Field(default_factory=dict, description="初始化参数")

    # 排序与控制
    sort_num: int = Field(0, description="执行顺序（越小越先执行）")
    enabled_flg: bool = Field(True, description="是否启用")

    # 条件加载
    required_features: list[str] = Field(
        default_factory=list,
        description="依赖的 Feature 开关（全部满足才加载）",
    )

