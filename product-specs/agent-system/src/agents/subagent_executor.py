"""SubagentExecutor — 双线程池异步执行子 Agent 任务

对齐 v2 subagents/executor.py：
- IO 线程池：处理 API 调用、网络请求等 IO 密集任务
- CPU 线程池：处理数据分析、计算等 CPU 密集任务
- submit → get_result 异步模式
"""
from __future__ import annotations

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable

from src.agents.subagent_config import SubagentResult, SubagentTask, TaskType

logger = logging.getLogger(__name__)

SubagentHandler = Callable[[SubagentTask], str]


class SubagentExecutor:
    """双线程池子 Agent 执行器"""

    def __init__(self, io_workers: int = 4, cpu_workers: int = 2) -> None:
        self._io_pool = ThreadPoolExecutor(max_workers=io_workers, thread_name_prefix="subagent-io")
        self._cpu_pool = ThreadPoolExecutor(max_workers=cpu_workers, thread_name_prefix="subagent-cpu")
        self._handlers: dict[str, SubagentHandler] = {}
        self._results: dict[str, SubagentResult] = {}
        self._pending: dict[str, asyncio.Future] = {}

    def register_handler(self, agent_name: str, handler: SubagentHandler) -> None:
        """注册子 Agent 的执行处理函数"""
        self._handlers[agent_name] = handler

    async def submit(self, task: SubagentTask, task_type: TaskType = TaskType.IO) -> str:
        """异步提交任务，返回 task_id"""
        handler = self._handlers.get(task.agent_name)
        if handler is None:
            raise ValueError(f"未注册的子 Agent: {task.agent_name}")

        pool = self._io_pool if task_type == TaskType.IO else self._cpu_pool
        loop = asyncio.get_running_loop()

        future = loop.run_in_executor(pool, self._execute, handler, task)
        self._pending[task.task_id] = future

        logger.info("已提交子 Agent 任务: task_id=%s, agent=%s, type=%s",
                     task.task_id, task.agent_name, task_type.value)
        return task.task_id

    def _execute(self, handler: SubagentHandler, task: SubagentTask) -> SubagentResult:
        """在线程池中执行，捕获所有异常"""
        try:
            output = handler(task)
            result = SubagentResult(task_id=task.task_id, success=True, output=output)
        except Exception as exc:
            logger.error("子 Agent 任务失败: task_id=%s, error=%s", task.task_id, exc)
            result = SubagentResult(task_id=task.task_id, success=False, output="", error=str(exc))
        self._results[task.task_id] = result
        return result

    async def get_result(self, task_id: str) -> SubagentResult:
        """获取任务结果，等待完成"""
        if task_id in self._results:
            return self._results[task_id]
        future = self._pending.get(task_id)
        if future is None:
            raise KeyError(f"未知的任务 ID: {task_id}")
        result = await future
        self._pending.pop(task_id, None)
        return result

    def shutdown(self, wait: bool = True) -> None:
        self._io_pool.shutdown(wait=wait)
        self._cpu_pool.shutdown(wait=wait)
        logger.info("子 Agent 执行器已关闭")
