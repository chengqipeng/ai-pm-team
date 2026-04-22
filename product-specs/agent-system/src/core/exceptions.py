"""
统一异常层次结构 — 所有自定义异常均继承自 DeepAgentError
"""


class DeepAgentError(Exception):
    """所有 DeepAgent 异常的基类"""


# ── 配置相关 ──

class ConfigurationError(DeepAgentError):
    def __init__(self, message: str = "", *, missing_fields: list[str] | None = None):
        self.missing_fields: list[str] = missing_fields or []
        if not message and self.missing_fields:
            message = f"缺失必需配置项: {', '.join(self.missing_fields)}"
        super().__init__(message)


# ── 技能系统 ──

class SkillValidationError(DeepAgentError):
    def __init__(self, message: str = "", *, errors: list[dict] | None = None):
        self.errors: list[dict] = errors or []
        super().__init__(message)


class SkillActivationError(DeepAgentError):
    def __init__(self, skill_name: str, missing_tools: list[str] | None = None):
        self.skill_name = skill_name
        self.missing_tools = missing_tools or []
        msg = f"技能激活失败: {skill_name}"
        if self.missing_tools:
            msg += f", 缺失工具: {', '.join(self.missing_tools)}"
        super().__init__(msg)


class SkillExecutionError(DeepAgentError):
    def __init__(self, skill_name: str = "", detail: str = ""):
        self.skill_name = skill_name
        self.detail = detail
        msg = f"技能执行失败: {skill_name}" if skill_name else detail
        if skill_name and detail:
            msg += f", 详情: {detail}"
        super().__init__(msg)


# ── 护栏系统 ──

class AuthorizationDeniedError(DeepAgentError):
    def __init__(self, tool_name: str, reason: str = ""):
        self.tool_name = tool_name
        self.reason = reason
        super().__init__(f"授权拒绝 - 工具: {tool_name}, 原因: {reason}")


# ── 凭证相关 ──

class CredentialError(DeepAgentError):
    def __init__(self, provider_name: str, detail: str = ""):
        self.provider_name = provider_name
        msg = f"凭证错误 ({provider_name})"
        if detail:
            msg += f": {detail}"
        super().__init__(msg)
