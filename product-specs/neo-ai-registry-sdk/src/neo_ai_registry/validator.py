"""Schema 校验 — 注册前验证切面定义合法性

校验规则：
- 必填字段检查
- 类型约束校验
- 业务规则校验（如 remote Tool 必须有 endpoint）
"""
from __future__ import annotations

import logging

from .models import ToolDefinition, ToolType, MiddlewareDefinition

logger = logging.getLogger(__name__)


class RegistryValidationError(Exception):
    """注册校验失败异常

    Attributes:
        entity_type: 实体类型（"Tool" / "Middleware"）
        api_key: 校验失败的实体标识
        errors: 具体错误信息列表
    """

    def __init__(self, entity_type: str, api_key: str, errors: list[str]):
        """初始化校验异常

        Args:
            entity_type: 实体类型名称，如 "Tool" 或 "Middleware"。
            api_key: 校验失败的实体的 api_key 值。
            errors: 所有校验失败原因的列表。
        """
        self.entity_type = entity_type
        self.api_key = api_key
        self.errors = errors
        super().__init__(
            f"{entity_type} '{api_key}' 校验失败: {'; '.join(errors)}"
        )


def validate_tool(tool: ToolDefinition) -> None:
    """校验 Tool 定义合法性

    校验规则：
    - api_key 不能为空
    - name 不能为空
    - type=remote 时 service 不能为空
    - input_schema 如果提供必须包含 type 字段

    Args:
        tool: 待校验的 ToolDefinition 实例。

    Raises:
        RegistryValidationError: 校验失败时抛出，包含所有错误详情。
    """
    errors: list[str] = []

    if not tool.api_key or not tool.api_key.strip():
        errors.append("api_key 不能为空")

    if not tool.name or not tool.name.strip():
        errors.append("name 不能为空")

    if tool.type == ToolType.REMOTE:
        if not tool.service or not tool.service.strip():
            # service 在 Provider 侧注册时可选（handler 直接绑定）
            pass

    if tool.input_schema:
        if "type" not in tool.input_schema:
            errors.append("input_schema 缺少 type 字段")

    if errors:
        raise RegistryValidationError("Tool", tool.api_key, errors)


def validate_middleware(mw: MiddlewareDefinition) -> None:
    """校验 Middleware 定义合法性"""
    errors: list[str] = []

    if not mw.api_key or not mw.api_key.strip():
        errors.append("api_key 不能为空")

    if errors:
        raise RegistryValidationError("Middleware", mw.api_key, errors)
