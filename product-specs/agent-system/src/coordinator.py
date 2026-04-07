"""
Coordinator 模式 — 借鉴 coordinator/coordinatorMode.ts
星型编排架构: Coordinator 居中编排，Worker 外围执行

核心设计:
- Coordinator 被剥夺所有"动手"工具，只保留编排能力 (Agent/SendMessage/TaskStop)
- Worker 的工具通过 ASYNC_AGENT_ALLOWED_TOOLS 过滤
- 通信协议: <task-notification> XML 格式
- Scratchpad: 跨 Worker 的共享知识库

借鉴源码:
  - src/coordinator/coordinatorMode.ts: isCoordinatorMode, getCoordinatorUserContext
  - src/coordinator/workerAgent.ts: getCoordinatorAgents
  - docs/agent/coordinator-and-swarm.mdx: 架构文档
"""
from __future__ import annotations

import time
import logging
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Any
from enum import Enum

from .types import (
    Message, MessageRole, ToolPermissionContext, TaskStatus,
    create_agent_id, AgentId,
)

logger = logging.getLogger(__name__)


# ─── Coordinator 允许的工具 (借鉴 coordinatorMode.ts) ───

COORDINATOR_ALLOWED_TOOLS = {"agent", "send_message", "task_stop"}

# Worker 禁止的内部工具 (防止不可控递归)
INTERNAL_WORKER_TOOLS = {"team_create", "team_delete", "send_message", "synthetic_output"}


# ─── Task Notification 协议 (借鉴 coordinatorMode.ts 的 XML 通信) ───

@dataclass
class TaskNotification:
    """
    Worker 完成后发送给 Coordinator 的通知
    (借鉴 <task-notification> XML 协议)
    """
    task_id: str
    status: TaskStatus
    summary: str
    result: str
    usage: dict[str, int] = field(default_factory=dict)

    def to_xml(self) -> str:
        """序列化为 XML (借鉴 coordinatorMode.ts 的通知格式)"""
        lines = [
            "<task-notification>",
            f"  <task-id>{self.task_id}</task-id>",
            f"  <status>{self.status.value}</status>",
            f"  <summary>{self.summary}</summary>",
            f"  <result>{self.result}</result>",
            "  <usage>",
            f"    <total_tokens>{self.usage.get('total_tokens', 0)}</total_tokens>",
            f"    <tool_uses>{self.usage.get('tool_uses', 0)}</tool_uses>",
            f"    <duration_ms>{self.usage.get('duration_ms', 0)}</duration_ms>",
            "  </usage>",
            "</task-notification>",
        ]
        return "\n".join(lines)

    @classmethod
    def from_xml(cls, xml_str: str) -> TaskNotification | None:
        """从 XML 反序列化"""
        try:
            root = ET.fromstring(xml_str)
            return cls(
                task_id=root.findtext("task-id", ""),
                status=TaskStatus(root.findtext("status", "completed")),
                summary=root.findtext("summary", ""),
                result=root.findtext("result", ""),
                usage={
                    "total_tokens": int(root.findtext("usage/total_tokens", "0")),
                    "tool_uses": int(root.findtext("usage/tool_uses", "0")),
                    "duration_ms": int(root.findtext("usage/duration_ms", "0")),
                },
            )
        except Exception as e:
            logger.error(f"Failed to parse task notification: {e}")
            return None


# ─── Worker 状态追踪 ───

@dataclass
class WorkerState:
    """Worker 运行状态"""
    agent_id: AgentId
    description: str
    status: TaskStatus = TaskStatus.RUNNING
    start_time: float = field(default_factory=time.time)
    end_time: float | None = None
    result: str | None = None
    usage: dict[str, int] = field(default_factory=dict)


# ─── Coordinator 上下文 ───

class CoordinatorContext:
    """
    Coordinator 模式上下文管理 (借鉴 coordinatorMode.ts:getCoordinatorUserContext)
    """

    def __init__(
        self,
        worker_tools: list[str] | None = None,
        mcp_servers: list[str] | None = None,
        scratchpad_dir: str | None = None,
    ):
        self._workers: dict[AgentId, WorkerState] = {}
        self._worker_tools = worker_tools or []
        self._mcp_servers = mcp_servers or []
        self._scratchpad_dir = scratchpad_dir
        self._notifications: list[TaskNotification] = []

    def get_user_context(self) -> dict[str, str]:
        """
        生成 Coordinator 附加上下文 (借鉴 getCoordinatorUserContext)
        注入到 System Prompt 中
        """
        parts = []

        # Worker 可用工具列表
        if self._worker_tools:
            tools_str = ", ".join(sorted(self._worker_tools))
            parts.append(f"Workers spawned via Agent tool have access to: {tools_str}")

        # MCP 服务器列表
        if self._mcp_servers:
            parts.append(f"MCP servers available: {', '.join(self._mcp_servers)}")

        # Scratchpad 目录
        if self._scratchpad_dir:
            parts.append(
                f"Scratchpad directory: {self._scratchpad_dir}\n"
                "  - Workers can freely read/write here without permission approval\n"
                "  - Use for persistent cross-worker knowledge\n"
                "  - Structure is up to you (no fixed format)"
            )

        # 当前 Worker 状态
        if self._workers:
            status_lines = ["Current workers:"]
            for wid, ws in self._workers.items():
                status_lines.append(
                    f"  - {wid}: {ws.description} [{ws.status.value}]"
                )
            parts.append("\n".join(status_lines))

        if not parts:
            return {}
        return {"coordinator_context": "\n\n".join(parts)}

    # ─── Worker 生命周期管理 ───

    def register_worker(self, agent_id: AgentId, description: str) -> None:
        """注册新 Worker"""
        self._workers[agent_id] = WorkerState(
            agent_id=agent_id, description=description,
        )
        logger.info(f"Worker registered: {agent_id} - {description}")

    def complete_worker(
        self, agent_id: AgentId, result: str, usage: dict[str, int] | None = None
    ) -> TaskNotification:
        """
        标记 Worker 完成并生成通知
        (借鉴 <task-notification> 协议)
        """
        worker = self._workers.get(agent_id)
        if not worker:
            return TaskNotification(
                task_id=agent_id, status=TaskStatus.FAILED,
                summary="Unknown worker", result="Worker not found",
            )

        worker.status = TaskStatus.COMPLETED
        worker.end_time = time.time()
        worker.result = result
        worker.usage = usage or {}

        notification = TaskNotification(
            task_id=agent_id,
            status=TaskStatus.COMPLETED,
            summary=f'Agent "{worker.description}" completed',
            result=result,
            usage={
                **worker.usage,
                "duration_ms": int((worker.end_time - worker.start_time) * 1000),
            },
        )
        self._notifications.append(notification)
        return notification

    def fail_worker(self, agent_id: AgentId, error: str) -> TaskNotification:
        """标记 Worker 失败"""
        worker = self._workers.get(agent_id)
        if worker:
            worker.status = TaskStatus.FAILED
            worker.end_time = time.time()

        notification = TaskNotification(
            task_id=agent_id,
            status=TaskStatus.FAILED,
            summary=f'Agent "{worker.description if worker else agent_id}" failed',
            result=error,
        )
        self._notifications.append(notification)
        return notification

    def kill_worker(self, agent_id: AgentId) -> TaskNotification:
        """终止 Worker"""
        worker = self._workers.get(agent_id)
        if worker:
            worker.status = TaskStatus.KILLED
            worker.end_time = time.time()

        notification = TaskNotification(
            task_id=agent_id,
            status=TaskStatus.KILLED,
            summary=f'Agent "{worker.description if worker else agent_id}" killed',
            result="Stopped by coordinator",
        )
        self._notifications.append(notification)
        return notification

    def get_active_workers(self) -> list[WorkerState]:
        """获取所有活跃 Worker"""
        return [w for w in self._workers.values() if w.status == TaskStatus.RUNNING]

    def get_pending_notifications(self) -> list[TaskNotification]:
        """获取并清空待处理通知"""
        notifications = list(self._notifications)
        self._notifications.clear()
        return notifications

    # ─── Coordinator System Prompt ───

    @staticmethod
    def get_coordinator_system_prompt() -> str:
        """
        Coordinator 的 System Prompt (借鉴 coordinatorMode.ts:111-369)
        核心要求: 不写代码、不读文件、不执行命令 — 只做编排
        """
        return """You are a Coordinator agent. Your role is to orchestrate work across multiple Worker agents.

## Your Capabilities
- Launch new Workers via the `agent` tool
- Send follow-up instructions to existing Workers via `send_message`
- Stop Workers that are going in the wrong direction via `task_stop`

## Your Constraints
- You do NOT write code, read files, or execute commands directly
- You ONLY orchestrate: understand requirements, assign tasks, synthesize results

## Core Principles

### Never Delegate Understanding
Do NOT write prompts like "based on your findings, fix the bug" or "based on the research, implement it."
Those phrases push synthesis onto the worker instead of doing it yourself.
Write prompts that prove YOU understood: include file paths, line numbers, what specifically to change.

### Complete Task Descriptions
Each Worker starts with zero context. Brief them like a smart colleague who just walked in:
- Explain what you're trying to accomplish and why
- Describe what you've already learned or ruled out
- Give enough context for judgment calls

### Synthesis is YOUR Job
When Workers return results, YOU must:
1. Read and understand their findings
2. Identify gaps or conflicts
3. Make decisions about next steps
4. Provide clear, specific instructions for follow-up work

## Communication Protocol
Workers send <task-notification> messages when they complete. These arrive as user-role messages.
Use the <task-id> for SendMessage's `to` parameter to continue a conversation with a specific Worker.
"""


# ─── Coordinator 模式工具过滤 ───

def filter_coordinator_tools(tools: list[Any]) -> list[Any]:
    """
    过滤 Coordinator 的工具集 (借鉴 coordinatorMode.ts)
    Coordinator 只保留编排工具
    """
    return [t for t in tools if getattr(t, "name", "") in COORDINATOR_ALLOWED_TOOLS]


def filter_worker_tools(tools: list[Any]) -> list[Any]:
    """
    过滤 Worker 的工具集 (借鉴 coordinatorMode.ts)
    Worker 排除内部工具，防止不可控递归
    """
    return [t for t in tools if getattr(t, "name", "") not in INTERNAL_WORKER_TOOLS]
