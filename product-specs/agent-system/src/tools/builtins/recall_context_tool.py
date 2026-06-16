"""recall_context 工具 — LLM 主动调用，从压缩存档中检索历史对话细节

使用场景:
  - 用户追问被压缩丢弃的具体信息（如"之前报价的付款条件是什么"）
  - 用户询问某事项的决策演变过程（如"报价是怎么定下来的"）
  - 用户追问某轮次的完整细节（如"轮次3具体做了什么"）

设计要点:
  1. 不同于 memory（记忆是提炼后的认知），recall 返回原始对话过程
  2. 按时间线排序，自动检测同实体的值变更
  3. 分级返回: 先给时间线摘要，LLM 判断是否需要展开某轮原文
  4. 标注数据时效性，提示可能过时的信息

工具注册: ToolRegistry.register_builtin("recall_context", RecallContextTool)
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class RecallContextTool:
    """从压缩存档中检索历史对话细节

    注意: 不继承 Tool ABC（因为参数签名不同），
    由 ContextWindowMiddleware 在初始化时注入到工具列表。
    """

    name: str = "recall_context"
    description: str = (
        "从被压缩的历史对话存档中检索细节。"
        "当用户追问摘要中没有的具体信息（如具体条款、详细数据、原话引用、"
        "决策过程）时使用。支持三种模式:\n"
        "- timeline: 返回相关轮次的时间线视图 + 变更检测（默认）\n"
        "- latest: 只返回最新相关状态\n"
        "- full: 展开某个轮次的完整对话原文（需指定 turn_id）\n\n"
        "输入参数:\n"
        "- query (必填): 要查找的关键词、实体名或问题描述\n"
        "- mode (可选): timeline / latest / full，默认 timeline\n"
        "- turn_id (可选): 展开某轮原文时指定轮次号\n"
        "- top_k (可选): 返回条数上限，默认 5"
    )

    # 工具元数据
    tags: list[str] = ["builtin", "context", "retrieval"]
    category: str = "context_management"

    # 压缩协作字段
    summary_threshold: int = 500
    compress_hint: str = "context_reference"

    def __init__(self, archive_service=None, **kwargs):
        """
        Args:
            archive_service: ContextArchiveService 实例（延迟注入）
        """
        self._archive_service = archive_service

    @property
    def parameters(self) -> dict:
        """JSON Schema 参数定义"""
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "要查找的关键词、实体名或问题描述",
                },
                "mode": {
                    "type": "string",
                    "enum": ["timeline", "latest", "full"],
                    "default": "timeline",
                    "description": "检索模式: timeline=时间线视图, latest=最新状态, full=展开某轮原文",
                },
                "turn_id": {
                    "type": "integer",
                    "description": "展开某轮原文时指定的轮次号（仅 mode=full 时需要）",
                },
                "top_k": {
                    "type": "integer",
                    "default": 5,
                    "description": "返回条数上限",
                },
            },
            "required": ["query"],
        }

    async def _arun(self, **kwargs) -> str:
        """异步执行"""
        query = kwargs.get("query", "")
        mode = kwargs.get("mode", "timeline")
        turn_id = kwargs.get("turn_id")
        top_k = kwargs.get("top_k", 5)

        if not query:
            return "错误: 请提供要查找的关键词或问题描述。"

        # 获取 service（延迟初始化）
        service = self._get_service()
        if not service:
            return "历史存档服务未初始化。建议使用业务工具重新查询最新数据。"

        try:
            result = await service.recall(
                query=query,
                mode=mode,
                top_k=top_k,
                target_turn_id=turn_id,
            )
            return result.to_llm_context()
        except Exception as e:
            logger.error("[recall_context] 检索失败: %s", e, exc_info=True)
            return f"历史存档检索失败: {e}。建议使用业务工具重新查询最新数据。"

    def _run(self, **kwargs) -> str:
        """同步执行（兼容）"""
        import asyncio
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as pool:
                    return pool.submit(asyncio.run, self._arun(**kwargs)).result()
            return loop.run_until_complete(self._arun(**kwargs))
        except Exception:
            return asyncio.run(self._arun(**kwargs))

    def _get_service(self):
        """获取 ContextArchiveService 实例"""
        if self._archive_service is not None:
            return self._archive_service

        # 尝试从全局上下文获取
        try:
            from src.core.context import get_current_context
            ctx = get_current_context()
            if ctx and hasattr(ctx, "archive_service"):
                self._archive_service = ctx.archive_service
                return self._archive_service
        except (ImportError, AttributeError):
            pass

        return None

    def set_archive_service(self, service) -> None:
        """注入 ContextArchiveService（由中间件在初始化时调用）"""
        self._archive_service = service
