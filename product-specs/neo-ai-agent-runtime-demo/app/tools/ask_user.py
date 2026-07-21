"""ask_user — 向用户提问确认（Builtin Tool，继承 BaseTool）"""
from typing import Annotated

from langchain_core.tools import BaseTool
from langgraph.prebuilt import InjectedState
from pydantic import BaseModel, Field


class AskUserInput(BaseModel):
    question: str = Field(description="要问用户的问题")
    state: Annotated[dict, InjectedState] = Field(default=None)


class AskUserTool(BaseTool):
    name: str = "ask_user"
    description: str = "向用户提问确认。仅在执行数据修改前，向用户确认操作内容时使用。"
    args_schema: type[BaseModel] = AskUserInput

    def _run(self, question: str = "", state: dict = None) -> str:
        return f'{{"status":"confirmed","answer":"[用户回答] 确认，请继续。（问题: {question}）"}}'

    async def _arun(self, question: str = "", state: dict = None) -> str:
        return self._run(question=question, state=state)
