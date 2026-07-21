"""manage_memory — 管理 Agent 记忆（Builtin Tool，继承 BaseTool）"""
import json
from typing import Annotated, Optional

from langchain_core.tools import BaseTool
from langgraph.prebuilt import InjectedState
from pydantic import BaseModel, Field


class ManageMemoryInput(BaseModel):
    action: str = Field(description="操作类型: list/delete/clear")
    keyword: Optional[str] = Field(default=None, description="搜索/删除的关键词")
    state: Annotated[dict, InjectedState] = Field(default=None)


class ManageMemoryTool(BaseTool):
    name: str = "manage_memory"
    description: str = "管理 Agent 的对话记忆（查看、搜索、删除、清空）。只有用户主动要求管理记忆时才调用。"
    args_schema: type[BaseModel] = ManageMemoryInput

    def _run(self, action: str = "", keyword: str = None, state: dict = None) -> str:
        if action == "list":
            return json.dumps({
                "status": "success",
                "memories": [
                    {"id": 1, "content": "用户偏好：回答简洁，数据用表格展示", "dimension": "user_profile"},
                    {"id": 2, "content": "仁科是华东区重点客户，负责人张三", "dimension": "customer_context"},
                ],
                "total": 2,
            }, ensure_ascii=False)
        elif action == "delete":
            return json.dumps({"status": "success", "deleted": 1, "keyword": keyword}, ensure_ascii=False)
        elif action == "clear":
            return json.dumps({"status": "success", "deleted": 5, "message": "已清空所有记忆"}, ensure_ascii=False)
        return json.dumps({"status": "error", "message": f"未知操作: {action}"}, ensure_ascii=False)

    async def _arun(self, **kwargs) -> str:
        return self._run(**kwargs)
