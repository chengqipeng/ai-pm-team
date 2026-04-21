"""
AsyncSubAgentManager — 异步子 Agent 管理，对应产品设计 §3.6.4
fire-and-forget 模式，后台执行，主 Agent 不阻塞
"""
from __future__ import annotations

import time
import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class AsyncTask:
    task_id: str
    name: str = ""
    status: str = "pending"       # pending/running/completed/failed/cancelled
    prompt: str = ""
    result: str = ""
    error: str = ""
    created_at: float = field(default_factory=time.time)
    _cancel_event: asyncio.Event = field(default_factory=asyncio.Event, repr=False)


class AsyncSubAgentManager:

    def __init__(self):
        self._tasks: dict[str, AsyncTask] = {}

    async def start_task(
        self, task_id: str, name: str, prompt: str,
        engine_factory: Any = None, config: Any = None,
    ) -> str:
        """启动异步任务，立即返回 task_id"""
        task = AsyncTask(task_id=task_id, name=name, prompt=prompt, status="running")
        self._tasks[task_id] = task

        if engine_factory and config:
            asyncio.create_task(self._run(task, engine_factory, config))
        else:
            task.status = "failed"
            task.error = "No engine factory provided"

        return task_id

    async def check_task(self, task_id: str) -> dict:
        task = self._tasks.get(task_id)
        if not task:
            return {"task_id": task_id, "status": "not_found"}
        return {
            "task_id": task_id,
            "name": task.name,
            "status": task.status,
            "result": task.result if task.status == "completed" else "",
            "error": task.error if task.status == "failed" else "",
            "elapsed_seconds": round(time.time() - task.created_at, 1),
        }

    async def cancel_task(self, task_id: str) -> bool:
        task = self._tasks.get(task_id)
        if task and task.status == "running":
            task._cancel_event.set()
            task.status = "cancelled"
            return True
        return False

    async def list_tasks(self) -> list[dict]:
        return [await self.check_task(tid) for tid in self._tasks]

    async def _run(self, task: AsyncTask, engine_factory, config):
        try:
            from .graph.factory import AgentFactory
            from .graph.state import GraphState
            from .dtypes import Message, MessageRole

            engine, sys_prompt = AgentFactory.create(config)
            state = GraphState(
                tenant_id=config.tenant_id,
                user_id=config.user_id,
                system_prompt=sys_prompt,
                messages=[Message(role=MessageRole.USER, content=task.prompt)],
            )

            async for s in engine.run(state):
                if task._cancel_event.is_set():
                    task.status = "cancelled"
                    return

            task.status = "completed"
            task.result = s.final_answer or "任务完成"
        except Exception as e:
            task.status = "failed"
            task.error = str(e)
            logger.error(f"Async task {task.task_id} failed: {e}")
