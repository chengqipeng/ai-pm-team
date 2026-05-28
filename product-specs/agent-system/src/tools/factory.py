"""ToolFactory — 数据库驱动的工具注册

设计原则：
    1. 数据库 ai_tool_definition 表是工具注册的唯一权威源
    2. 每个 Tool 类通过 classmethod `create()` 实现自包含初始化（依赖自行解析）
    3. ToolFactory 只负责：读 DB → 匹配 Tool 类 → 调用 create() → 注册到 Registry
    4. 工具的启用/禁用、元数据完全由数据库控制

使用方式：
    from src.tools.factory import ToolFactory

    reg = ToolRegistry(skip_db_check=True)  # Factory 自己做 DB 校验，不需要 Registry 再校验
    factory = ToolFactory(tenant_id=0)
    factory.register_all(reg)
"""
from __future__ import annotations

import logging
from typing import Any

from src.tools.base import Tool, ToolRegistry

logger = logging.getLogger(__name__)


class ToolFactory:
    """数据库驱动的工具工厂

    从 ai_tool_definition 表读取已启用的工具列表，
    根据 api_key 匹配对应的 Tool 类，调用其 create() 类方法完成实例化。

    每个 Tool 类的 create() 方法负责自行解析所需依赖（环境变量、后端连接等），
    Factory 不关心具体依赖细节。
    """

    def __init__(self, tenant_id: int = 0):
        self._tenant_id = tenant_id
        self._tool_class_map: dict[str, type[Tool]] = {}
        self._register_builtin_classes()

    def _register_builtin_classes(self) -> None:
        """注册所有内置 Tool 类的映射（api_key → Tool class）

        这是代码与数据库的唯一桥接点：
        - 数据库决定"哪些工具启用"
        - 这里决定"api_key 对应哪个实现类"
        """
        # CRM 业务工具
        from src.tools.crm_tools import (
            QuerySchemaTool, QueryDataTool, ModifyDataTool,
            AnalyzeDataTool, AskUserTool, AskClarificationTool,
            ManageMemoryTool, MemoryReadTool,
        )
        self._tool_class_map["query_schema"] = QuerySchemaTool
        self._tool_class_map["query_data"] = QueryDataTool
        self._tool_class_map["modify_data"] = ModifyDataTool
        self._tool_class_map["analyze_data"] = AnalyzeDataTool
        self._tool_class_map["ask_user"] = AskUserTool
        self._tool_class_map["ask_clarification"] = AskClarificationTool
        self._tool_class_map["manage_memory"] = ManageMemoryTool
        self._tool_class_map["memory_read"] = MemoryReadTool

        # Metarepo 元数据工具
        from src.tools.metarepo_tools import BrowseMetamodelTool, QueryMetadataTool
        self._tool_class_map["browse_metamodel"] = BrowseMetamodelTool
        self._tool_class_map["query_metadata"] = QueryMetadataTool

        # 知识库工具
        from src.tools.knowledge_tools import (
            KnowledgeSearchAdapterTool, ListKnowledgeBasesTool,
            KnowledgeDocDetailAdapterTool,
        )
        self._tool_class_map["knowledge_search"] = KnowledgeSearchAdapterTool
        self._tool_class_map["list_knowledge_bases"] = ListKnowledgeBasesTool
        self._tool_class_map["knowledge_doc_detail"] = KnowledgeDocDetailAdapterTool

        # 技能管理工具
        from src.tools.manage_skill_tool import ManageSkillTool
        self._tool_class_map["manage_skill"] = ManageSkillTool

        # 技能资源加载工具
        from src.tools.skill_resource_tool import ReadSkillResourceTool
        self._tool_class_map["read_skill_resource"] = ReadSkillResourceTool

        # COS 文件上传工具
        from src.tools.cos_upload_tool import CosUploadTool
        self._tool_class_map["cos_upload"] = CosUploadTool

        # 百度 AI 搜索
        from src.tools.web_search import WebSearchTool
        self._tool_class_map["web_search"] = WebSearchTool

        # 沙盒工具
        from src.tools.sandbox import (
            TerminalTool, CodeExecutionTool, ReadFileTool,
            WriteFileTool, SearchFilesTool,
        )
        self._tool_class_map["terminal"] = TerminalTool
        self._tool_class_map["execute_code"] = CodeExecutionTool
        self._tool_class_map["read_file"] = ReadFileTool
        self._tool_class_map["write_file"] = WriteFileTool
        self._tool_class_map["search_files"] = SearchFilesTool

    def register_all(self, registry: ToolRegistry) -> dict[str, str]:
        """从数据库读取已启用工具，逐一实例化并注册

        Returns:
            注册结果摘要 {api_key: "ok" | "skipped:原因" | "failed:错误"}
        """
        from src.store.tool_dao import ToolDefinitionDAO

        results: dict[str, str] = {}

        # 从数据库获取所有已启用的工具定义
        try:
            db_tools = ToolDefinitionDAO.list_all(
                tenant_id=self._tenant_id, enabled_only=True
            )
        except Exception as e:
            logger.error("ToolFactory: 无法加载数据库工具配置: %s", e)
            raise RuntimeError(
                f"ToolFactory 无法加载数据库工具配置: {e}。请检查数据库连接。"
            ) from e

        logger.info(
            "ToolFactory: 数据库中 %d 个已启用工具，代码中 %d 个已注册类",
            len(db_tools), len(self._tool_class_map),
        )

        for row in db_tools:
            api_key = row.api_key

            # 查找对应的 Tool 类
            tool_cls = self._tool_class_map.get(api_key)
            if tool_cls is None:
                # 数据库中有定义但代码中没有实现 — 跳过（可能是未来版本的工具）
                results[api_key] = "skipped:no_implementation"
                logger.debug("ToolFactory: %s 无对应实现类，跳过", api_key)
                continue

            # 调用 Tool 类的 create() 工厂方法
            try:
                tool_instance = tool_cls.create(
                    tenant_id=self._tenant_id,
                    db_row=row,
                )
            except ToolCreateSkipped as e:
                # 工具主动跳过（依赖不满足但非致命）
                results[api_key] = f"skipped:{e}"
                logger.info("ToolFactory: %s 跳过注册 — %s", api_key, e)
                continue
            except Exception as e:
                # 工具初始化失败
                results[api_key] = f"failed:{type(e).__name__}:{e}"
                logger.warning("ToolFactory: %s 初始化失败: %s", api_key, e)
                continue

            # 注册到 Registry（跳过 DB 校验，因为 Factory 已经做了）
            registry._tools[tool_instance.name] = tool_instance
            for alias in tool_instance.aliases:
                registry._alias_map[alias] = tool_instance.name
            results[api_key] = "ok"

        # 统计
        ok_count = sum(1 for v in results.values() if v == "ok")
        skip_count = sum(1 for v in results.values() if v.startswith("skipped"))
        fail_count = sum(1 for v in results.values() if v.startswith("failed"))
        logger.info(
            "ToolFactory: 注册完成 — 成功=%d, 跳过=%d, 失败=%d",
            ok_count, skip_count, fail_count,
        )

        return results

    def register_class(self, api_key: str, tool_cls: type[Tool]) -> None:
        """动态注册额外的 Tool 类映射（供插件/扩展使用）"""
        self._tool_class_map[api_key] = tool_cls


class ToolCreateSkipped(Exception):
    """工具主动跳过注册（依赖不满足但非致命错误）

    Tool.create() 中抛出此异常表示"当前环境不支持此工具，跳过即可"。
    与普通 Exception 不同，不会被视为错误。
    """
    pass
