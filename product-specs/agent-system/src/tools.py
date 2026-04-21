"""
Tools 体系 — Tool 统一接口 + ToolRegistry
新架构中工具执行由 ExecutionNode 内部处理，不再需要独立的 execute_tool_use 函数。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable

from .dtypes import ToolResult, ValidationResult


class Tool(ABC):
    """
    工具基类 — 所有工具必须实现 name / input_schema / call
    description 和 prompt 可选覆盖。
    """

    # ═══ 核心（必须实现） ═══

    @property
    @abstractmethod
    def name(self) -> str: ...

    @abstractmethod
    def input_schema(self) -> dict[str, Any]: ...

    @abstractmethod
    async def call(
        self,
        input_data: dict,
        context: Any,
        on_progress: Callable[[Any], None] | None = None,
    ) -> ToolResult: ...

    async def description(self, input_data: dict) -> str:
        """动态描述 — 根据实际参数生成人类可读的操作描述"""
        return self.name

    # ═══ 注册与发现 ═══

    @property
    def aliases(self) -> list[str]:
        return []

    @property
    def search_hint(self) -> str | None:
        return None

    @property
    def should_defer(self) -> bool:
        return False

    def is_enabled(self) -> bool:
        return True

    @property
    def tags(self) -> list[str]:
        return []

    # ═══ 安全与权限 ═══

    def validate_input(self, input_data: dict) -> ValidationResult:
        return ValidationResult(valid=True)

    def is_read_only(self, input_data: dict) -> bool:
        return False

    def is_destructive(self, input_data: dict) -> bool:
        return False

    # ═══ 输出控制 ═══

    @property
    def max_result_size_chars(self) -> int:
        return 50_000

    def prompt(self) -> str:
        """工具使用说明，注入到 system prompt"""
        return ""

    # ═══ 压缩协作 ═══

    @property
    def summary_threshold(self) -> int:
        return 500

    @property
    def summary_max_words(self) -> int:
        return 150

    @property
    def code_extractable(self) -> bool:
        return False


class ToolRegistry:
    """工具注册表 — 工具的唯一真相源"""

    def __init__(self):
        self._tools: dict[str, Tool] = {}
        self._alias_map: dict[str, str] = {}

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool
        for alias in tool.aliases:
            self._alias_map[alias] = tool.name

    def unregister(self, name: str) -> None:
        self._tools.pop(name, None)

    def find_by_name(self, name: str) -> Tool | None:
        if name in self._tools:
            return self._tools[name]
        canonical = self._alias_map.get(name)
        if canonical:
            return self._tools.get(canonical)
        return None

    @property
    def all_tools(self) -> list[Tool]:
        return list(self._tools.values())
