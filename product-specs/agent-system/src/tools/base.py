"""
Tools 体系 — Tool 统一接口 + ToolRegistry
新架构中工具执行由 ExecutionNode 内部处理，不再需要独立的 execute_tool_use 函数。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable

from src.core.dtypes import ToolResult, ValidationResult


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
    """工具注册表 — 工具的唯一真相源

    注册时结合数据库 ai_tool_definition 表进行验证：
    - 只有数据库中存在且 enabled_flg=1 的工具才会被注册
    - 数据库中不存在的工具会被跳过并记录警告
    - 支持 skip_db_check 模式（测试或无数据库环境）
    """

    def __init__(self, skip_db_check: bool = False):
        self._tools: dict[str, Tool] = {}
        self._alias_map: dict[str, str] = {}
        self._skip_db_check = skip_db_check
        self._db_enabled_tools: set[str] | None = None

    def _load_db_config(self) -> set[str]:
        """从数据库加载已启用的工具 api_key 集合（只加载一次）

        Raises:
            ConfigurationError: 数据库不可用时抛出异常，不再静默降级
        """
        if self._db_enabled_tools is not None:
            return self._db_enabled_tools
        try:
            from src.store.tool_dao import ToolDefinitionDAO
            rows = ToolDefinitionDAO.list_all(tenant_id=0, enabled_only=True)
            self._db_enabled_tools = {r.api_key for r in rows}
        except Exception as e:
            import logging
            from src.core.exceptions import ConfigurationError
            logging.getLogger(__name__).error(
                "ToolRegistry: 无法加载数据库工具配置: %s", e
            )
            if not self._skip_db_check:
                raise ConfigurationError(
                    f"ToolRegistry 无法加载数据库工具配置: {e}。"
                    f"请检查数据库连接，或使用 skip_db_check=True 跳过校验（仅限测试环境）"
                ) from e
            # skip_db_check=True 时（测试环境）允许降级
            self._db_enabled_tools = None
        return self._db_enabled_tools or set()

    def register(self, tool: Tool) -> None:
        """注册工具 — 结合数据库验证

        Raises:
            ToolNotEnabledError: 工具在数据库中未启用或不存在时抛出异常
        """
        import logging
        from src.core.exceptions import ToolNotEnabledError
        logger = logging.getLogger(__name__)

        if not self._skip_db_check:
            enabled_tools = self._load_db_config()
            if enabled_tools and tool.name not in enabled_tools:
                raise ToolNotEnabledError(tool.name)

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

    def reload_db_config(self) -> None:
        """重新加载数据库配置（启用/禁用工具后调用）"""
        self._db_enabled_tools = None
        self._load_db_config()
