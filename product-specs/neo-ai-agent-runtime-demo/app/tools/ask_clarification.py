"""ask_clarification — 向用户澄清追问（内置工具）

信息不足或有歧义时中断执行并追问。
"""
from neo_ai_registry.models import ToolDefinition, ToolType


class AskClarificationTool(ToolDefinition):
    """向用户澄清追问"""

    api_key: str = "ask_clarification"
    name: str = "向用户澄清追问"
    description: str = "向用户澄清追问，获取缺失的关键信息后再继续执行。"
    type: ToolType = ToolType.BUILTIN
    input_schema: dict = {
        "type": "object",
        "properties": {
            "question": {"type": "string", "description": "要问用户的具体问题"},
            "clarification_type": {
                "type": "string",
                "enum": ["missing_info", "ambiguous_requirement", "approach_choice", "risk_confirmation"],
                "description": "澄清类型",
            },
            "options": {
                "type": "array",
                "items": {"type": "string"},
                "description": "可选项列表（approach_choice 时使用）",
            },
        },
        "required": ["question", "clarification_type"],
    }

    async def execute(self, input_data: dict, context: dict) -> dict:
        question = input_data.get("question", "")
        ctype = input_data.get("clarification_type", "missing_info")
        options = input_data.get("options", [])

        icons = {"missing_info": "❓", "ambiguous_requirement": "🤔", "approach_choice": "🔀", "risk_confirmation": "⚠️"}
        parts = [f"{icons.get(ctype, '❓')} {question}"]
        if options:
            parts += [f"  {i}. {o}" for i, o in enumerate(options, 1)]

        return {"status": "clarification_requested", "message": "\n".join(parts)}
