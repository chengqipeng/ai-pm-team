"""SkillToolScopeMiddleware 单元测试

验证 Skill 级工具作用域隔离的核心逻辑：
1. 无 SkillContext 时放行
2. allowed_tools 为空时放行（向后兼容）
3. 工具在 allowed_tools 范围内时放行
4. 工具不在 allowed_tools 范围内时拦截
5. 豁免工具始终放行
6. 非严格模式仅警告不拦截
"""
import asyncio
import pytest
from unittest.mock import MagicMock, AsyncMock

from src.skills.context import (
    set_skill_context,
    get_skill_context,
    clear_skill_context,
    reset_skill_context,
    SkillContext,
)
from src.middleware.skill_tool_scope import SkillToolScopeMiddleware


def _make_request(tool_name: str, tool_call_id: str = "call_001", args: dict | None = None):
    """构造模拟的 ToolCallRequest"""
    request = MagicMock()
    request.tool_call = {
        "name": tool_name,
        "id": tool_call_id,
        "args": args or {},
    }
    return request


class TestSkillContext:
    """测试 SkillContext 的 set/get/clear 生命周期"""

    def test_default_is_none(self):
        """默认无上下文"""
        # 先清除可能残留的上下文
        reset_skill_context()
        assert get_skill_context() is None

    def test_set_and_get(self):
        """设置后可以获取"""
        token = set_skill_context("test_skill", ["query_data", "analyze_data"], "inline")
        try:
            ctx = get_skill_context()
            assert ctx is not None
            assert ctx.skill_name == "test_skill"
            assert ctx.allowed_tools == frozenset({"query_data", "analyze_data"})
            assert ctx.context_mode == "inline"
        finally:
            clear_skill_context(token)

    def test_clear_restores_previous(self):
        """clear 恢复到设置前的状态"""
        reset_skill_context()
        token = set_skill_context("skill_a", ["tool_1"])
        clear_skill_context(token)
        assert get_skill_context() is None

    def test_nested_context(self):
        """嵌套设置上下文"""
        token1 = set_skill_context("outer_skill", ["tool_a"])
        token2 = set_skill_context("inner_skill", ["tool_b"])

        ctx = get_skill_context()
        assert ctx.skill_name == "inner_skill"
        assert ctx.allowed_tools == frozenset({"tool_b"})

        clear_skill_context(token2)
        ctx = get_skill_context()
        assert ctx.skill_name == "outer_skill"

        clear_skill_context(token1)
        assert get_skill_context() is None

    def test_reset_without_token(self):
        """reset_skill_context 无条件清除"""
        set_skill_context("some_skill", ["tool_x"])
        reset_skill_context()
        assert get_skill_context() is None

    def test_empty_allowed_tools(self):
        """空 allowed_tools 列表"""
        token = set_skill_context("skill_no_limit", [])
        try:
            ctx = get_skill_context()
            assert ctx.allowed_tools == frozenset()
        finally:
            clear_skill_context(token)


class TestSkillToolScopeMiddleware:
    """测试 SkillToolScopeMiddleware 的拦截逻辑"""

    def setup_method(self):
        """每个测试前清除上下文"""
        reset_skill_context()
        self.middleware = SkillToolScopeMiddleware()

    def teardown_method(self):
        """每个测试后清除上下文"""
        reset_skill_context()

    def test_no_context_passthrough(self):
        """无 SkillContext 时放行"""
        request = _make_request("modify_data")
        handler = MagicMock(return_value="ok")

        result = self.middleware.wrap_tool_call(request, handler)

        handler.assert_called_once_with(request)
        assert result == "ok"

    def test_empty_allowed_tools_passthrough(self):
        """allowed_tools 为空时放行（向后兼容）"""
        set_skill_context("legacy_skill", [])
        request = _make_request("modify_data")
        handler = MagicMock(return_value="ok")

        result = self.middleware.wrap_tool_call(request, handler)

        handler.assert_called_once_with(request)
        assert result == "ok"

    def test_tool_in_scope_passthrough(self):
        """工具在 allowed_tools 范围内时放行"""
        set_skill_context("data_skill", ["query_data", "analyze_data"])
        request = _make_request("query_data")
        handler = MagicMock(return_value="data_result")

        result = self.middleware.wrap_tool_call(request, handler)

        handler.assert_called_once_with(request)
        assert result == "data_result"

    def test_tool_out_of_scope_blocked(self):
        """工具不在 allowed_tools 范围内时拦截"""
        set_skill_context("readonly_skill", ["query_data", "analyze_data"])
        request = _make_request("modify_data", "call_123")
        handler = MagicMock()

        result = self.middleware.wrap_tool_call(request, handler)

        handler.assert_not_called()
        assert result.content.startswith("Error:")
        assert "modify_data" in result.content
        assert "readonly_skill" in result.content
        assert result.status == "error"
        assert result.tool_call_id == "call_123"

    def test_exempt_tool_always_passes(self):
        """豁免工具始终放行"""
        set_skill_context("strict_skill", ["query_data"])

        for exempt_tool in ["skills_tool", "ask_user", "ask_clarification"]:
            request = _make_request(exempt_tool)
            handler = MagicMock(return_value="ok")
            result = self.middleware.wrap_tool_call(request, handler)
            handler.assert_called_once_with(request)
            assert result == "ok"

    def test_custom_exempt_tools(self):
        """自定义豁免工具"""
        mw = SkillToolScopeMiddleware(exempt_tools=["custom_tool"])
        set_skill_context("strict_skill", ["query_data"])

        request = _make_request("custom_tool")
        handler = MagicMock(return_value="ok")
        result = mw.wrap_tool_call(request, handler)

        handler.assert_called_once_with(request)
        assert result == "ok"

    def test_non_strict_mode_warns_only(self):
        """非严格模式仅警告不拦截"""
        mw = SkillToolScopeMiddleware(strict=False)
        set_skill_context("readonly_skill", ["query_data"])

        request = _make_request("modify_data")
        handler = MagicMock(return_value="data_modified")

        result = mw.wrap_tool_call(request, handler)

        handler.assert_called_once_with(request)
        assert result == "data_modified"

    def test_multiple_allowed_tools(self):
        """多个 allowed_tools 正确匹配"""
        set_skill_context("multi_tool_skill", [
            "query_data", "analyze_data", "query_schema", "web_search"
        ])

        for tool in ["query_data", "analyze_data", "query_schema", "web_search"]:
            request = _make_request(tool)
            handler = MagicMock(return_value="ok")
            result = self.middleware.wrap_tool_call(request, handler)
            handler.assert_called_once()

        # 不在列表中的工具被拦截
        request = _make_request("modify_data")
        handler = MagicMock()
        result = self.middleware.wrap_tool_call(request, handler)
        handler.assert_not_called()
        assert result.status == "error"

    @pytest.mark.asyncio
    async def test_async_no_context_passthrough(self):
        """异步：无 SkillContext 时放行"""
        request = _make_request("modify_data")
        handler = AsyncMock(return_value="ok")

        result = await self.middleware.awrap_tool_call(request, handler)

        handler.assert_called_once_with(request)
        assert result == "ok"

    @pytest.mark.asyncio
    async def test_async_tool_out_of_scope_blocked(self):
        """异步：工具不在范围内时拦截"""
        set_skill_context("readonly_skill", ["query_data"])
        request = _make_request("modify_data", "call_456")
        handler = AsyncMock()

        result = await self.middleware.awrap_tool_call(request, handler)

        handler.assert_not_called()
        assert result.status == "error"
        assert "modify_data" in result.content

    @pytest.mark.asyncio
    async def test_async_tool_in_scope_passthrough(self):
        """异步：工具在范围内时放行"""
        set_skill_context("data_skill", ["query_data", "analyze_data"])
        request = _make_request("analyze_data")
        handler = AsyncMock(return_value="analysis_result")

        result = await self.middleware.awrap_tool_call(request, handler)

        handler.assert_called_once_with(request)
        assert result == "analysis_result"

    def test_context_switch_between_skills(self):
        """Skill 切换时上下文正确更新"""
        # 第一个 Skill
        set_skill_context("skill_a", ["tool_1", "tool_2"])
        request = _make_request("tool_1")
        handler = MagicMock(return_value="ok")
        result = self.middleware.wrap_tool_call(request, handler)
        assert result == "ok"

        # tool_3 被 skill_a 拦截
        request = _make_request("tool_3")
        handler = MagicMock()
        result = self.middleware.wrap_tool_call(request, handler)
        assert result.status == "error"

        # 切换到 skill_b（允许 tool_3）
        set_skill_context("skill_b", ["tool_3", "tool_4"])
        request = _make_request("tool_3")
        handler = MagicMock(return_value="ok")
        result = self.middleware.wrap_tool_call(request, handler)
        assert result == "ok"

        # tool_1 被 skill_b 拦截
        request = _make_request("tool_1")
        handler = MagicMock()
        result = self.middleware.wrap_tool_call(request, handler)
        assert result.status == "error"

    def test_fork_mode_context_cleanup(self):
        """fork 模式上下文在 clear 后不再拦截"""
        token = set_skill_context("fork_skill", ["query_data"], "fork")

        # 在上下文中，modify_data 被拦截
        request = _make_request("modify_data")
        handler = MagicMock()
        result = self.middleware.wrap_tool_call(request, handler)
        assert result.status == "error"

        # 清除上下文后，modify_data 放行
        clear_skill_context(token)
        request = _make_request("modify_data")
        handler = MagicMock(return_value="ok")
        result = self.middleware.wrap_tool_call(request, handler)
        handler.assert_called_once()
        assert result == "ok"
