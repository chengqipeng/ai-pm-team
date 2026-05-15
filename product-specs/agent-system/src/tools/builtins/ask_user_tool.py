"""ask_user 工具 — 中断确认机制

利用 LangGraph 的 interrupt() API 暂停 Agent 执行，等待用户响应。

使用方式（Skill prompt 中指导 Agent 调用）：
    ask_user(
        interrupt_type="select",
        title="请选择目标客户",
        message="找到以下匹配的客户：",
        options=[
            {"id": "C001", "label": "华为技术有限公司", "description": "深圳·IT"},
            {"id": "C002", "label": "华为云计算技术", "description": "贵阳·云"},
        ]
    )

执行流程：
    1. Agent 调用 ask_user → 工具内部调用 interrupt(value)
    2. LangGraph 暂停执行，保存状态到 checkpointer
    3. 前端收到 interrupt 事件，渲染确认 UI
    4. 用户操作后，前端发送 resume → LangGraph 恢复执行
    5. interrupt() 返回用户选择的值 → ask_user 返回给 Agent
    6. Agent 继续后续工具调用
"""
from __future__ import annotations

import logging
import uuid
from typing import Any

from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class AskUserInput(BaseModel):
    """ask_user 工具输入参数"""
    interrupt_type: str = Field(
        description="中断类型: confirm(确认/取消) | select(单选) | multi_select(多选) | input(文本输入)",
    )
    title: str = Field(
        description="中断标题（显示在确认 UI 顶部）",
    )
    message: str = Field(
        default="",
        description="说明文字（可选，补充说明）",
    )
    options: list[dict] = Field(
        default_factory=list,
        description="选项列表（select/multi_select 时必填），每项含 id/label/description",
    )
    default_value: str = Field(
        default="",
        description="默认值（input 类型时可选）",
    )


class AskUserTool(BaseTool):
    """中断确认工具 — 调用 LangGraph interrupt() 暂停执行等待用户响应"""

    name: str = "ask_user"
    description: str = (
        "向用户发起确认请求，暂停执行等待用户响应。"
        "适用场景：模糊匹配需要用户选择、危险操作需要确认、需要用户补充信息。"
        "interrupt_type: confirm(确认/取消) | select(单选列表) | multi_select(多选) | input(文本输入)。"
        "select/multi_select 时必须提供 options 数组，每项含 {id, label, description}。"
    )
    args_schema: type[BaseModel] = AskUserInput

    def _run(
        self,
        interrupt_type: str = "confirm",
        title: str = "",
        message: str = "",
        options: list[dict] | None = None,
        default_value: str = "",
    ) -> str:
        """同步版本（不推荐，interrupt 需要异步环境）"""
        return self._do_interrupt(interrupt_type, title, message, options or [], default_value)

    async def _arun(
        self,
        interrupt_type: str = "confirm",
        title: str = "",
        message: str = "",
        options: list[dict] | None = None,
        default_value: str = "",
    ) -> str:
        """异步版本"""
        return self._do_interrupt(interrupt_type, title, message, options or [], default_value)

    def _do_interrupt(
        self,
        interrupt_type: str,
        title: str,
        message: str,
        options: list[dict],
        default_value: str,
    ) -> str:
        """调用 LangGraph interrupt() 暂停执行"""
        from langgraph.types import interrupt

        interrupt_id = f"int_{uuid.uuid4().hex[:12]}"

        # 构造传递给客户端的中断数据
        interrupt_value = {
            "interrupt_id": interrupt_id,
            "type": interrupt_type,
            "title": title,
            "message": message,
            "options": options,
            "default_value": default_value,
        }

        logger.info(
            "ask_user: interrupt type=%s title=%s options=%d",
            interrupt_type, title, len(options),
        )

        # ★ 核心调用：暂停 graph 执行，等待用户响应
        # interrupt() 会：
        #   1. 将 interrupt_value 保存到 checkpoint
        #   2. 抛出 GraphInterrupt 异常
        #   3. graph.invoke() 返回 {"__interrupt__": [...]}
        # 当用户 resume 时：
        #   interrupt() 返回用户传入的值
        user_response = interrupt(interrupt_value)

        # 执行到这里说明用户已经 resume 了
        logger.info("ask_user: resumed, response=%s", user_response)

        # 处理用户响应
        if isinstance(user_response, dict):
            if user_response.get("cancelled"):
                return "用户取消了操作"
            value = user_response.get("value", "")
            return str(value)
        return str(user_response)
