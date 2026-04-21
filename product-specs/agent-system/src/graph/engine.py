"""
GraphEngine — 图状态机编排引擎主循环
对应产品设计 §3.3.3 + Agent-Core §二
"""
from __future__ import annotations

import json
import logging
import asyncio
from pathlib import Path
from typing import AsyncIterator, Any
from dataclasses import dataclass, field

from .state import GraphState, AgentStatus, AgentLimits
from .router import Router
from ..middleware.base import PluginContext

logger = logging.getLogger(__name__)


class CheckpointStore:
    """检查点存储 — JSON 文件，可替换为 Redis/PG"""

    def __init__(self, base_dir: str = ".checkpoints"):
        self._base = Path(base_dir)
        self._base.mkdir(parents=True, exist_ok=True)

    async def save(self, state: GraphState) -> None:
        path = self._base / f"{state.session_id}.json"
        data = {
            "session_id": state.session_id,
            "tenant_id": state.tenant_id,
            "user_id": state.user_id,
            "status": state.status.value,
            "current_step_index": state.current_step_index,
            "total_llm_calls": state.total_llm_calls,
            "total_tool_calls": state.total_tool_calls,
            "pause_reason": state.pause_reason,
            "checkpoint_version": state.checkpoint_version,
            "final_answer": state.final_answer,
        }
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2))

    async def load(self, session_id: str) -> dict | None:
        path = self._base / f"{session_id}.json"
        if not path.exists():
            return None
        return json.loads(path.read_text())


class GraphEngine:
    """
    图状态机编排引擎 — 洋葱模型中间件 + Router 路由 + Node 执行
    每步 yield state 实现流式输出
    """

    def __init__(
        self,
        nodes: dict[str, Any],
        middleware_stack: list[Any],
        context: PluginContext,
        limits: AgentLimits | None = None,
        checkpoint_store: CheckpointStore | None = None,
    ):
        self._nodes = nodes
        self._middlewares = middleware_stack
        self._context = context
        self._limits = limits or AgentLimits()
        self._router = Router(self._limits)
        self._checkpoint = checkpoint_store

    async def run(self, state: GraphState) -> AsyncIterator[GraphState]:
        """主循环"""
        state._limits = self._limits

        while True:
            # 路由决策
            node_name = self._router.next_node(state)
            if node_name is None:
                break

            node = self._nodes.get(node_name)
            if not node:
                logger.error(f"Unknown node: {node_name}")
                state.status = AgentStatus.FAILED
                break

            state.current_node = node_name

            # 预算警告
            warning = self._router.inject_budget_warning(state)
            if warning:
                state.system_prompt += warning

            # 中间件前处理（按注册顺序）
            for mw in self._middlewares:
                try:
                    state = await asyncio.wait_for(
                        mw.before_step(state, self._context), timeout=30
                    )
                except Exception as e:
                    logger.warning(f"Middleware {getattr(mw, 'name', '?')} before_step error: {e}")

            # Node 执行
            try:
                state = await node.execute(state, self._context)
            except Exception as e:
                logger.error(f"Node {node_name} execution error: {e}")
                state.consecutive_errors += 1

            # 中间件后处理（逆序）
            for mw in reversed(self._middlewares):
                try:
                    state = await asyncio.wait_for(
                        mw.after_step(state, self._context), timeout=30
                    )
                except Exception as e:
                    logger.warning(f"Middleware after_step error: {e}")

            # 检查点
            if self._checkpoint:
                state.checkpoint_version += 1
                try:
                    await self._checkpoint.save(state)
                except Exception as e:
                    logger.warning(f"Checkpoint save error: {e}")

            yield state

            # HITL 暂停
            if state.status == AgentStatus.PAUSED:
                break

        yield state

    async def resume(
        self, state: GraphState, decision: str, user_message: str = ""
    ) -> AsyncIterator[GraphState]:
        """从 HITL 暂停中恢复"""
        if decision == "approve":
            state.status = AgentStatus.RUNNING
            state.pause_reason = None
        elif decision == "reject":
            state.status = AgentStatus.RUNNING
            state.pause_reason = None
            if state.current_step:
                state.current_step.status = StepStatus.SKIPPED
                state.current_step_index += 1
        elif decision == "abort":
            state.status = AgentStatus.ABORTED
            yield state
            return
        else:
            raise ValueError(f"Unknown decision: {decision}")

        if user_message:
            from ..dtypes import Message, MessageRole
            state.messages.append(Message(role=MessageRole.USER, content=user_message))

        async for s in self.run(state):
            yield s
