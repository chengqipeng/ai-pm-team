"""manage_memory — 管理 Agent 记忆（内置工具）

依赖本地 MemoryEngine 实例，必须在 Agent 进程内执行。
"""
from neo_ai_registry.models import ToolDefinition, ToolType


class ManageMemoryTool(ToolDefinition):
    """管理 Agent 记忆 — 查询、删除、清空"""

    api_key: str = "manage_memory"
    name: str = "管理记忆"
    description: str = "管理 Agent 的对话记忆（查看、搜索、删除、清空）。只有用户主动要求管理记忆时才调用。"
    type: ToolType = ToolType.BUILTIN
    input_schema: dict = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["list", "delete", "clear"],
                "description": "操作类型",
            },
            "keyword": {
                "type": "string",
                "description": "搜索/删除的关键词",
            },
        },
        "required": ["action"],
    }

    async def execute(self, input_data: dict, context: dict) -> dict:
        action = input_data.get("action", "")
        keyword = input_data.get("keyword", "")

        if action == "list":
            return {
                "status": "success",
                "memories": [
                    {"id": 1, "content": "用户偏好：回答简洁，数据用表格展示", "dimension": "user_profile"},
                    {"id": 2, "content": "仁科是华东区重点客户，负责人张三", "dimension": "customer_context"},
                ],
                "total": 2,
            }
        elif action == "delete":
            return {"status": "success", "deleted": 1, "keyword": keyword}
        elif action == "clear":
            return {"status": "success", "deleted": 5, "message": "已清空所有记忆"}

        return {"status": "error", "message": f"未知操作: {action}"}
