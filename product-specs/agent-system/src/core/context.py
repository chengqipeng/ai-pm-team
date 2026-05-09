"""RequestContext — 请求级全局上下文

使用 Python contextvars 实现请求隔离的全局上下文。
每个请求（API 调用）在入口处 set_context，后续所有模块通过 get_context() 获取。

用法：
    # 入口处设置（server.py）
    from src.core.context import set_context, RequestContext
    set_context(RequestContext(tenant_id=1, user_id="user_001", thread_id="abc123"))

    # 任意深层模块获取
    from src.core.context import get_context
    ctx = get_context()
    print(ctx.tenant_id)  # 1
"""
from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass, field


# ═══════════════════════════════════════════════════════════
# 全局默认租户 ID / 用户 ID
# ═══════════════════════════════════════════════════════════
# - 与 paas-platform-service seed 数据对齐（init_paas_auth_data.sql 里所有 p_user 的
#   tenant_id 都是 292193，"鸿阳科技"），保证 HTTP backend 登录后拿到的 JWT 里的
#   tenantId 与 agent-system RequestContext/TraceWriter/ai_* 表的 tenant_id 一致
# - 可通过环境变量 DEFAULT_TENANT_ID / DEFAULT_USER_ID 覆盖
import os as _os

DEFAULT_TENANT_ID: int = int(_os.getenv("DEFAULT_TENANT_ID", "292193"))
DEFAULT_USER_ID: int = int(_os.getenv("DEFAULT_USER_ID", "100000000000000006"))
DEFAULT_USER_NAME: str = _os.getenv("DEFAULT_USER_NAME", "张伟")
DEFAULT_USER_PHONE: str = _os.getenv("DEFAULT_USER_PHONE", "13800000001")


@dataclass
class RequestContext:
    """贯穿单次请求生命周期的上下文"""

    # 租户隔离
    tenant_id: int = DEFAULT_TENANT_ID

    # 用户身份
    user_id: str = ""

    # 会话标识
    thread_id: str = ""

    # Agent 信息
    agent_name: str = "CRM-Agent"

    # 扩展参数（业务自定义）
    extend_params: dict = field(default_factory=dict)


# ── 全局 ContextVar ──
# 每个 asyncio Task 自动继承父 Task 的 context，无需手动传递
_request_ctx: ContextVar[RequestContext] = ContextVar(
    "request_ctx", default=RequestContext()
)


def get_context() -> RequestContext:
    """获取当前请求的上下文（任意模块可调用）"""
    return _request_ctx.get()


def set_context(ctx: RequestContext) -> None:
    """设置当前请求的上下文（仅在请求入口调用）"""
    _request_ctx.set(ctx)
