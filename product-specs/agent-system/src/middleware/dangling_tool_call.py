"""修复悬空 tool_call 中间件

## 问题背景

LangGraph 的 ReAct 循环中，消息序列必须满足严格的配对约束：
每个 AIMessage 中的 tool_call 都必须有一个对应的 ToolMessage 响应。
如果 AIMessage 包含 tool_calls 但缺少对应的 ToolMessage，LLM 下一轮调用
会报错（OpenAI/Doubao API 要求 tool_call 和 tool_result 严格配对）。

## 什么是"悬空 tool_call"

当 Agent 执行到一半被中断时，会出现 AIMessage 中有 tool_calls 但没有
对应 ToolMessage 的情况。常见触发场景：

### 场景 1：用户中断（最常见）
  用户发送消息 → Agent 回复 AIMessage(tool_calls=[query_data(...)]) →
  工具开始执行 → 用户点击"停止" → 工具执行被取消 →
  下次用户发消息时，历史中有 tool_call 但没有 tool_result

  消息序列：
    HumanMessage("查一下张三的商机")
    AIMessage(tool_calls=[{id:"tc_1", name:"query_data", args:{...}}])  ← 有 tool_call
    HumanMessage("算了，帮我查客户列表吧")                                ← 没有 tc_1 的 ToolMessage！
                                                                          LLM 会报错

### 场景 2：服务重启 / 会话恢复
  Agent 执行中 → 服务重启 → checkpointer 恢复了上次的消息历史 →
  最后一条 AIMessage 有 tool_calls 但工具从未执行完成

### 场景 3：工具执行超时
  AIMessage(tool_calls=[analyze_data(...)]) → 工具执行超过 timeout →
  框架丢弃了超时的工具结果 → tool_call 悬空

### 场景 4：ClarificationMiddleware 拦截后的后续对话
  AIMessage(tool_calls=[ask_clarification(...)]) → 中间件拦截并返回 interrupt →
  用户回复后开始新一轮 → 如果 interrupt 机制未正确补充 ToolMessage → 悬空

## 修复策略

在 before_agent 阶段（Agent 开始处理新消息前），扫描最后一条 AIMessage：
- 收集所有已有 ToolMessage 的 tool_call_id
- 检查最后一条 AIMessage 的 tool_calls 是否都有对应的 ToolMessage
- 对缺失的 tool_call 补充一个 status="error" 的 ToolMessage
- 这样 LLM 看到的是"上次工具调用失败了"，会自然地重新规划

## 修复前后对比

修复前（会报错）：
    HumanMessage("查张三的商机")
    AIMessage(tool_calls=[{id:"tc_1", name:"query_data"}])
    HumanMessage("算了查客户列表")
    → LLM API Error: tool_call tc_1 没有对应的 tool result

修复后（正常运行）：
    HumanMessage("查张三的商机")
    AIMessage(tool_calls=[{id:"tc_1", name:"query_data"}])
    ToolMessage(tool_call_id="tc_1", content="Error: ...interrupted", status="error")  ← 自动补充
    HumanMessage("算了查客户列表")
    → LLM 正常处理，理解上次工具调用失败，按新指令继续
"""

import logging
from typing import Any
from langchain_core.messages import AIMessage, ToolMessage
from langchain.agents.middleware.types import AgentMiddleware, AgentState
from langgraph.runtime import Runtime

logger = logging.getLogger(__name__)


class DanglingToolCallMiddleware(AgentMiddleware):
    """修复上一轮悬挂的 tool_calls — 补充 error ToolMessage 使消息序列合法

    只检查最后一条 AIMessage，因为更早的 AIMessage 如果有悬空 tool_call，
    在之前的 before_agent 调用中已经被修复过了。
    """

    def before_agent(self, state: AgentState, runtime: Runtime) -> dict[str, Any] | None:
        messages = state.get("messages", [])
        if not messages:
            return None

        # 收集所有已存在的 ToolMessage 的 tool_call_id
        existing_ids = {
            msg.tool_call_id for msg in messages if isinstance(msg, ToolMessage)
        }

        # 只检查最后一条 AIMessage 的 tool_calls
        patches: list[ToolMessage] = []
        for msg in reversed(messages):
            if isinstance(msg, AIMessage) and getattr(msg, "tool_calls", None):
                for tc in msg.tool_calls:
                    tc_id = tc.get("id", "")
                    if tc_id and tc_id not in existing_ids:
                        patches.append(ToolMessage(
                            content="Error: This tool call was not executed (previous session interrupted).",
                            tool_call_id=tc_id,
                            name=tc.get("name", "unknown"),
                            status="error",
                        ))
                        logger.warning("Patched dangling tool call: %s (id=%s)", tc.get("name"), tc_id)
                break  # 只检查最后一条 AIMessage

        return {"messages": patches} if patches else None
