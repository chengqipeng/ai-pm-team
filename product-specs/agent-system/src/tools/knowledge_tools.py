"""知识库工具 — 注册到 ToolRegistry 供 Agent 使用

包含：
    - KnowledgeSearchAdapterTool: 知识库检索（适配自定义 Tool 基类）
    - ListKnowledgeBasesTool: 列出可用知识库
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Callable

from src.tools.base import Tool, ToolRegistry
from src.core.dtypes import ToolResult

logger = logging.getLogger(__name__)


class KnowledgeSearchAdapterTool(Tool):
    """知识库检索工具 — 适配 ToolRegistry 的 Tool 基类

    内部委托 KnowledgeSearchTool（LangChain BaseTool）的核心逻辑，
    但以自定义 Tool 基类形式注册到 ToolRegistry，使 SkillRegistry
    的 allowed_tools 校验能通过。
    """

    def __init__(self):
        from src.tools.builtins.knowledge_tool import KnowledgeSearchTool
        self._inner = KnowledgeSearchTool()
        self._provider = None  # 由 register_knowledge_tools 注入
        self._tenant_id = 0

    def set_provider(self, provider, tenant_id: int = 0):
        """注入 knowledge_provider（服务启动后调用）"""
        self._provider = provider
        self._tenant_id = tenant_id

    @property
    def name(self) -> str:
        return "knowledge_search"

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "检索问题，用自然语言描述你要查找的知识",
                },
                "knowledge_base_id": {
                    "type": "integer",
                    "description": "知识库 ID（可选，不指定则在当前 Agent 可访问的全部知识库中检索）",
                },
                "top_k": {
                    "type": "integer",
                    "description": "最大返回数量，默认 5",
                    "default": 5,
                },
                "doc_category": {
                    "type": "string",
                    "description": "文档类别过滤（可选）",
                },
                "industry": {
                    "type": "string",
                    "description": "行业过滤（可选）",
                },
                "business_stage": {
                    "type": "string",
                    "description": "业务阶段过滤（可选）",
                },
                "target_audience": {
                    "type": "string",
                    "description": "目标受众过滤（可选）",
                },
            },
            "required": ["query"],
        }

    async def call(
        self,
        input_data: dict,
        context: Any,
        on_progress: Callable[[Any], None] | None = None,
    ) -> ToolResult:
        # 优先使用直接注入的 provider（不依赖 langgraph get_config）
        provider = self._provider
        tenant_id = self._tenant_id

        # 降级 1：从 FastAPI app.state 动态获取（解决启动时序问题）
        if provider is None:
            try:
                import sys
                server_mod = sys.modules.get("server")
                if server_mod:
                    _app = getattr(server_mod, "app", None)
                    if _app:
                        provider = getattr(_app.state, "knowledge_provider", None)
                # 同时获取 tenant_id（如果未通过 set_provider 设置）
                if provider and not tenant_id:
                    from src.core.context import get_context
                    tenant_id = get_context().tenant_id
            except Exception:
                pass

        # 降级 2：尝试从 langgraph config 获取
        if provider is None:
            try:
                from langgraph.config import get_config
                ctx = get_config().get("configurable", {}) or {}
                provider = ctx.get("knowledge_provider")
                tenant_id = int(ctx.get("tenant_id", 0) or 0)
            except Exception:
                pass

        if provider is None:
            logger.error("knowledge_search: provider 未注入且 get_config 也取不到")
            return ToolResult(
                content="知识库 Provider 未注入，请检查服务配置。",
                is_error=True,
            )

        query = input_data.get("query", "")
        if not query:
            return ToolResult(content="query 参数不能为空", is_error=True)

        try:
            results = await provider.search(
                tenant_id=tenant_id,
                query=query,
                knowledge_base_id=input_data.get("knowledge_base_id"),
                filters=None,
                top_k=input_data.get("top_k", 5),
                enable_self_query=True,
            )
        except Exception as exc:
            logger.exception("knowledge_search 执行失败: %s", exc)
            return ToolResult(content=f"知识库检索失败: {exc}", is_error=True)

        if not results:
            return ToolResult(content=f"未找到与 '{query}' 相关的知识文档。")

        # 格式化结果
        from src.tools.builtins.knowledge_tool import KnowledgeSearchTool
        formatted = KnowledgeSearchTool._format_results(query, results)
        return ToolResult(content=formatted)

    def prompt(self) -> str:
        return (
            "检索 AI 知识库中的文档。适用于：产品手册、销售话术、成功案例、"
            "内部政策、竞品分析、解决方案、合同模板、技术白皮书、培训材料、FAQ 等。\n"
            "支持自然语言查询，系统会自动理解查询意图并过滤相关文档。\n"
            "不适用于实时业务数据（如 CRM 客户/商机），那些应使用 query_data。\n"
            "参数说明：\n"
            "  - query（必填）：自然语言检索问题\n"
            "  - knowledge_base_id（可选）：指定知识库 ID，不指定则全库检索\n"
            "  - top_k（可选）：最大返回数量，默认 5\n"
            "  - doc_category（可选）：按文档类别过滤\n"
            "  - industry（可选）：按行业过滤\n"
            "  - business_stage（可选）：按业务阶段过滤\n"
            "  - target_audience（可选）：按目标受众过滤"
        )


class ListKnowledgeBasesTool(Tool):
    """列出当前租户可用的知识库列表

    返回知识库的 ID、名称、描述、文档数量等信息，
    帮助 Agent 决定在哪个知识库中检索。
    """

    @property
    def name(self) -> str:
        return "list_knowledge_bases"

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {},
            "required": [],
        }

    async def call(
        self,
        input_data: dict,
        context: Any,
        on_progress: Callable[[Any], None] | None = None,
    ) -> ToolResult:
        # 从 langgraph runtime config 获取 provider 和租户上下文
        ctx = self._runtime_config()
        provider = ctx.get("knowledge_provider")
        tenant_id = int(ctx.get("tenant_id", 0) or 0)

        if provider is None:
            return ToolResult(
                content="知识库未启用，请联系管理员配置 knowledge-plugin。",
                is_error=True,
            )
        if tenant_id <= 0:
            return ToolResult(
                content="缺少租户上下文，无法列出知识库。",
                is_error=True,
            )

        try:
            bases = await provider.list_knowledge_bases(tenant_id=tenant_id)
        except Exception as exc:
            logger.exception("list_knowledge_bases 执行失败: %s", exc)
            return ToolResult(content=f"获取知识库列表失败: {exc}", is_error=True)

        if not bases:
            return ToolResult(content="当前租户下没有可用的知识库。")

        # 格式化输出
        items = []
        for kb in bases:
            items.append({
                "id": kb.id,
                "name": kb.name,
                "description": kb.description or "",
                "document_count": kb.document_count,
                "chunk_count": kb.chunk_count,
            })

        return ToolResult(
            content=json.dumps(items, ensure_ascii=False, indent=2),
        )

    def prompt(self) -> str:
        return (
            "列出当前租户可用的知识库。\n"
            "何时使用：\n"
            "  - 用户未指定知识库时，先调用此工具查看有哪些知识库可用\n"
            "  - 需要了解各知识库的文档数量和描述时调用\n"
            "返回：知识库列表（含 ID、名称、描述、文档数量）"
        )

    @staticmethod
    def _runtime_config() -> dict[str, Any]:
        """从 langgraph runtime 获取 configurable 字典"""
        try:
            from langgraph.config import get_config
            return get_config().get("configurable", {}) or {}
        except Exception:
            return {}


class KnowledgeDocDetailAdapterTool(Tool):
    """文档详情工具 — 获取文档目录或指定章节的完整内容

    当 knowledge_search 返回的切片不够完整时，用此工具深入获取文档的特定章节。
    """

    @property
    def name(self) -> str:
        return "knowledge_doc_detail"

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "doc_id": {
                    "type": "string",
                    "description": "文档 ID（从 knowledge_search 结果中获取）",
                },
                "sections": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "要获取的章节标题列表。为空时返回文档目录；指定章节时返回该章节的完整内容",
                },
            },
            "required": ["doc_id"],
        }

    async def call(
        self,
        input_data: dict,
        context: Any,
        on_progress: Callable[[Any], None] | None = None,
    ) -> ToolResult:
        from src.tools.builtins.knowledge_doc_detail_tool import KnowledgeDocDetailTool
        tool = KnowledgeDocDetailTool()
        doc_id = input_data.get("doc_id", "")
        sections = input_data.get("sections") or []

        if not doc_id:
            return ToolResult(content="doc_id 参数不能为空", is_error=True)

        try:
            result = await tool._arun(doc_id=doc_id, sections=sections)
            return ToolResult(content=result)
        except Exception as exc:
            logger.exception("knowledge_doc_detail 执行失败: %s", exc)
            return ToolResult(content=f"获取文档详情失败: {exc}", is_error=True)

    def prompt(self) -> str:
        return (
            "获取知识库文档的目录结构或指定章节的完整内容。\n"
            "当 knowledge_search 返回的切片不够完整时，用此工具深入获取文档的特定章节。\n"
            "用法：\n"
            "  1) sections 为空或不传 → 返回文档目录（章节列表+切片数）\n"
            "  2) 指定 sections → 返回这些章节的完整文本内容\n"
            "参数：\n"
            "  - doc_id（必填）：文档 ID，从 knowledge_search 结果中获取\n"
            "  - sections（可选）：章节标题列表，如 [\"差压范围\", \"测量类型\"]"
        )


def register_knowledge_tools(registry: ToolRegistry, provider=None, tenant_id: int = 0) -> None:
    """注册知识库相关工具到 ToolRegistry

    Args:
        registry: 工具注册表
        provider: KnowledgeProvider 实例（可选，启动后注入）
        tenant_id: 默认租户 ID
    """
    search_tool = KnowledgeSearchAdapterTool()
    if provider:
        search_tool.set_provider(provider, tenant_id)
    registry.register(search_tool)
    registry.register(ListKnowledgeBasesTool())
    registry.register(KnowledgeDocDetailAdapterTool())
