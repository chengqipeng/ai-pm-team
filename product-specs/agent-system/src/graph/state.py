"""
GraphState — 图状态机的完整状态定义
对应产品设计 §3.3.1 + Agent-Core-详细设计 §一
"""
from __future__ import annotations

import uuid
import time
import asyncio
from enum import Enum
from dataclasses import dataclass, field
from typing import Any, Callable, Awaitable


class AgentStatus(str, Enum):
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    MAX_TURNS = "max_turns"
    ABORTED = "aborted"


class StepStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class TaskStep:
    description: str
    status: StepStatus = StepStatus.PENDING
    agent_type: str | None = None
    tools: list[str] | None = None
    result: str = ""
    error: str = ""
    llm_calls: int = 0
    max_llm_calls: int = 20


@dataclass
class TaskPlan:
    goal: str
    steps: list[TaskStep] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)


@dataclass
class AgentLimits:
    MAX_TOTAL_LLM_CALLS: int = 200
    MAX_STEP_LLM_CALLS: int = 20
    MAX_CONSECUTIVE_ERRORS: int = 5
    MAX_CONSECUTIVE_SAME_TOOL: int = 4
    MAX_REPLAN_COUNT: int = 3
    HITL_TIMEOUT_SECONDS: int = 3600
    BUDGET_WARNING_80: int = 160
    BUDGET_WARNING_95: int = 190


@dataclass
class FileInfo:
    """虚拟文件 — 保留工具结果原文供后续引用"""
    file_path: str
    content: str
    summary: str
    extend: dict = field(default_factory=dict)


@dataclass
class AgentCallbacks:
    on_tool_start: Callable[[str, dict], Any] | None = None
    on_tool_end: Callable[[str, Any], Any] | None = None
    on_stream_delta: Callable[[str], Any] | None = None
    on_status_change: Callable[[str, str], Any] | None = None
    on_plan_created: Callable[[TaskPlan], Any] | None = None
    on_step_progress: Callable[[int, int, str], Any] | None = None
    on_approval_request: Callable[[str, dict], Awaitable[str]] | None = None
    on_memory_extracted: Callable[[list], Any] | None = None


@dataclass
class GraphState:
    """图状态机的完整状态 — 所有 Node 和 Middleware 通过读写此对象通信"""

    # 身份与会话
    session_id: str = field(default_factory=lambda: f"sess_{uuid.uuid4().hex[:12]}")
    tenant_id: str = ""
    user_id: str = ""
    messages: list = field(default_factory=list)

    # 任务规划
    plan: TaskPlan | None = None
    current_step_index: int = 0

    # 执行追踪
    current_node: str = "router"
    total_llm_calls: int = 0
    total_tool_calls: int = 0
    consecutive_errors: int = 0
    consecutive_same_tool: int = 0
    last_tool_name: str = ""
    replan_count: int = 0

    # 状态控制
    status: AgentStatus = AgentStatus.RUNNING
    pause_reason: str | None = None
    final_answer: str = ""

    # 上下文
    memory_context: str = ""
    system_prompt: str = ""
    file_list: list[FileInfo] = field(default_factory=list)
    language_name: str = "zh-CN"

    # 中断
    interrupt_event: asyncio.Event = field(default_factory=asyncio.Event)

    # 检查点
    checkpoint_version: int = 0

    # 内部引用（不序列化）
    _limits: AgentLimits = field(default_factory=AgentLimits, repr=False)

    @property
    def current_step(self) -> TaskStep | None:
        if self.plan and 0 <= self.current_step_index < len(self.plan.steps):
            return self.plan.steps[self.current_step_index]
        return None

    @property
    def all_steps_done(self) -> bool:
        if not self.plan:
            return False
        return all(
            s.status in (StepStatus.COMPLETED, StepStatus.SKIPPED)
            for s in self.plan.steps
        )

    @property
    def budget_ratio(self) -> float:
        if self._limits.MAX_TOTAL_LLM_CALLS == 0:
            return 1.0
        return self.total_llm_calls / self._limits.MAX_TOTAL_LLM_CALLS
