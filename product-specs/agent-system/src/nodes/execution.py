"""
ExecutionNode — 步骤执行，对应产品设计 §3.3.4 + Agent-Core §四
内部 mini agent loop: LLM → 解析 → 工具执行 → 继续
"""
from __future__ import annotations

import json
import asyncio
import logging
from typing import Any

from ..graph.state import GraphState, AgentStatus, StepStatus
from ..middleware.base import PluginContext
from ..dtypes import (
    Message, MessageRole, ToolUseBlock, ToolResultBlock, ToolResult,
)

logger = logging.getLogger(__name__)


class ExecutionNode:

    async def execute(self, state: GraphState, context: PluginContext) -> GraphState:
        step = state.current_step
        if not step:
            return state

        step.status = StepStatus.RUNNING

        # 构建工具 schema 列表
        tool_schemas = self._build_tool_schemas(step, context)

        # 构建 system prompt（含当前步骤指令）
        sys_prompt = state.system_prompt
        if step.description:
            sys_prompt += f"\n\n## 当前任务步骤\n{step.description}"

        # Mini agent loop
        while step.status == StepStatus.RUNNING:
            # 步骤级预算
            if step.llm_calls >= step.max_llm_calls:
                step.status = StepStatus.FAILED
                step.error = "步骤 LLM 调用次数超限"
                break

            # stuck 检测 — 让 Router 接管
            if (state.consecutive_errors >= state._limits.MAX_CONSECUTIVE_ERRORS
                    or state.consecutive_same_tool >= state._limits.MAX_CONSECUTIVE_SAME_TOOL):
                break  # 退出 mini loop，Router 会路由到 ReflectionNode

            # 调用 LLM
            api_messages = self._to_api_messages(state)
            try:
                response = await context.llm.call(
                    system_prompt=sys_prompt,
                    messages=api_messages,
                    tools=tool_schemas if tool_schemas else None,
                )
            except Exception as e:
                state.consecutive_errors += 1
                logger.error(f"LLM call failed: {e}")
                if state.consecutive_errors >= state._limits.MAX_CONSECUTIVE_ERRORS:
                    step.status = StepStatus.FAILED
                    step.error = str(e)
                break

            state.total_llm_calls += 1
            step.llm_calls += 1

            # 解析响应
            assistant_msg, tool_uses = self._parse_response(response)
            state.messages.append(assistant_msg)

            # 无 tool_use → 步骤完成
            if not tool_uses:
                step.status = StepStatus.COMPLETED
                step.result = assistant_msg.content if isinstance(assistant_msg.content, str) else ""
                state.consecutive_errors = 0
                state.consecutive_same_tool = 0
                # 推进到下一步
                state.current_step_index += 1
                break

            # 执行工具
            for tu in tool_uses:
                tool_result = await self._execute_one_tool(tu, state, context)

                if state.status == AgentStatus.PAUSED:
                    return state  # HITL 暂停

                # 追加 tool_result 消息
                state.messages.append(Message(
                    role=MessageRole.USER,
                    content=[{
                        "type": "tool_result",
                        "tool_use_id": tu.id,
                        "content": tool_result.content,
                    }],
                ))

                # 回调
                if context.callbacks and context.callbacks.on_tool_end:
                    context.callbacks.on_tool_end(tu.name, tool_result)

        return state

    async def _execute_one_tool(
        self, tu: ToolUseBlock, state: GraphState, context: PluginContext
    ) -> ToolResultBlock:
        """执行单个工具，含中间件拦截"""
        tool_input = dict(tu.input)

        # before_tool_call 中间件链
        for mw in context.middlewares:
            try:
                result = await mw.before_tool_call(tu.name, tool_input, state, context)
                if result is None:
                    if state.status == AgentStatus.PAUSED:
                        return ToolResultBlock(tool_use_id=tu.id, content="操作已暂停，等待确认", is_error=True)
                    return ToolResultBlock(tool_use_id=tu.id, content="操作被拒绝", is_error=True)
                tool_input = result
            except Exception as e:
                logger.warning(f"Middleware {getattr(mw, 'name', '?')} before_tool_call error: {e}")

        # 查找工具
        tool = context.tool_registry.find_by_name(tu.name) if context.tool_registry else None
        if not tool:
            self._update_tracking(state, tu.name, True)
            return ToolResultBlock(tool_use_id=tu.id, content=f"未知工具: {tu.name}", is_error=True)

        # 回调
        if context.callbacks and context.callbacks.on_tool_start:
            context.callbacks.on_tool_start(tu.name, tool_input)

        # 执行
        try:
            result = await asyncio.wait_for(
                tool.call(tool_input, context),
                timeout=60,
            )
            state.total_tool_calls += 1
            self._update_tracking(state, tu.name, result.is_error)
            tool_result_block = ToolResultBlock(
                tool_use_id=tu.id,
                content=result.content,
                is_error=result.is_error,
            )
        except asyncio.TimeoutError:
            self._update_tracking(state, tu.name, True)
            tool_result_block = ToolResultBlock(
                tool_use_id=tu.id, content="工具执行超时", is_error=True,
            )
        except Exception as e:
            self._update_tracking(state, tu.name, True)
            tool_result_block = ToolResultBlock(
                tool_use_id=tu.id, content=f"工具执行异常: {e}", is_error=True,
            )

        # after_tool_call 中间件链（逆序）
        for mw in reversed(context.middlewares):
            try:
                tool_result_block = await mw.after_tool_call(tu.name, tool_result_block, state, context)
            except Exception as e:
                logger.warning(f"Middleware after_tool_call error: {e}")

        return tool_result_block

    def _update_tracking(self, state: GraphState, tool_name: str, is_error: bool):
        if is_error:
            state.consecutive_errors += 1
        else:
            state.consecutive_errors = 0
        if tool_name == state.last_tool_name:
            state.consecutive_same_tool += 1
        else:
            state.consecutive_same_tool = 0
        state.last_tool_name = tool_name

    def _build_tool_schemas(self, step, context: PluginContext) -> list[dict]:
        if not context.tool_registry:
            return []
        tools = context.tool_registry.all_tools
        # 按步骤限制过滤
        if step.tools:
            allowed = set(step.tools)
            tools = [t for t in tools if t.name in allowed]
        schemas = []
        for t in tools:
            if hasattr(t, "is_enabled") and not t.is_enabled():
                continue
            schemas.append({
                "name": t.name,
                "description": t.prompt() if hasattr(t, "prompt") else t.name,
                "input_schema": t.input_schema() if hasattr(t, "input_schema") else {"type": "object", "properties": {}},
            })
        return schemas

    def _to_api_messages(self, state: GraphState) -> list[dict]:
        """将 state.messages 转为 LLM API 格式"""
        api_msgs = []
        for msg in state.messages:
            role = str(msg.role.value) if hasattr(msg.role, "value") else str(msg.role)
            if role == "system":
                continue  # system prompt 单独传
            content = msg.content
            if isinstance(content, list):
                # 可能包含 tool_result blocks
                api_msgs.append({"role": role, "content": content})
            elif isinstance(content, str) and content.strip():
                api_msgs.append({"role": role, "content": content})
            # tool_use_blocks → assistant 消息中的 tool_calls
            if hasattr(msg, "tool_use_blocks") and msg.tool_use_blocks:
                # 已经在 content 中以 list 形式存在
                pass
        return api_msgs if api_msgs else [{"role": "user", "content": "[empty]"}]

    def _parse_response(self, response: dict) -> tuple[Message, list[ToolUseBlock]]:
        """解析 LLM 响应为 Message + tool_use 列表"""
        content_blocks = response.get("content", [])
        text_parts = []
        tool_uses = []

        for block in content_blocks:
            if block.get("type") == "text":
                text_parts.append(block.get("text", ""))
            elif block.get("type") == "tool_use":
                tool_uses.append(ToolUseBlock(
                    id=block.get("id", ""),
                    name=block.get("name", ""),
                    input=block.get("input", {}),
                ))

        text = "\n".join(text_parts)
        msg = Message(
            role=MessageRole.ASSISTANT,
            content=text if not tool_uses else content_blocks,
            tool_use_blocks=tool_uses,
            usage=response.get("usage"),
        )
        return msg, tool_uses
