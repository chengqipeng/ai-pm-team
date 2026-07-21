"""ask_user — 向用户提问确认（内置工具）

依赖 LangGraph interrupt() 暂停执行等待用户输入，必须在 Agent 进程内执行。
"""
from neo_ai_registry.models import ToolDefinition, ToolType


class AskUserTool(ToolDefinition):
    """向用户发起确认"""

    api_key: str = "ask_user"
    name: str = "向用户提问确认"
    description: str = "向用户提问确认。仅在执行数据修改前，向用户确认操作内容时使用。"
    type: ToolType = ToolType.BUILTIN
    input_schema: dict = {
        "type": "object",
        "properties": {
            "question": {"type": "string", "description": "要问用户的问题"},
        },
        "required": ["question"],
    }

    async def execute(self, input_data: dict, context: dict) -> dict:
        question = input_data.get("question", "")
        # 实际生产中通过 LangGraph interrupt() 暂停，等待用户回复
        return {
            "status": "confirmed",
            "answer": f"[用户回答] 确认，请继续。（问题: {question}）",
        }
