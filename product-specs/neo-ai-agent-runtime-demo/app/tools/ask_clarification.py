"""ask_clarification — 向用户澄清追问（Builtin Tool，继承 BaseTool）"""
from typing import Annotated, Optional

from langchain_core.tools import BaseTool
from langgraph.prebuilt import InjectedState
from pydantic import BaseModel, Field


class AskClarificationInput(BaseModel):
    question: str = Field(description="要问用户的具体问题")
    clarification_type: str = Field(description="澄清类型: missing_info/ambiguous_requirement/approach_choice/risk_confirmation")
    options: Optional[list[str]] = Field(default=None, description="可选项列表")
    state: Annotated[dict, InjectedState] = Field(default=None)


class AskClarificationTool(BaseTool):
    name: str = "ask_clarification"
    description: str = "向用户澄清追问，获取缺失的关键信息后再继续执行。"
    args_schema: type[BaseModel] = AskClarificationInput

    def _run(self, question: str = "", clarification_type: str = "missing_info", options: list = None, state: dict = None) -> str:
        import json
        icons = {"missing_info": "❓", "ambiguous_requirement": "🤔", "approach_choice": "🔀", "risk_confirmation": "⚠️"}
        parts = [f"{icons.get(clarification_type, '❓')} {question}"]
        if options:
            parts += [f"  {i}. {o}" for i, o in enumerate(options, 1)]
        return json.dumps({"status": "clarification_requested", "message": "\n".join(parts)}, ensure_ascii=False)

    async def _arun(self, **kwargs) -> str:
        return self._run(**kwargs)
