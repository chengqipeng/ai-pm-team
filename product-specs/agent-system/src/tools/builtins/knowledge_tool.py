"""knowledge_search 工具 — Agent 通过此工具检索知识库

核心能力：
    - 查询改写（多轮对话的指代消解）
    - Self-Querying（从查询提取 metadata 过滤条件）
    - 三路并行召回（切片混合检索 + 文档摘要向量 + PG 元数据文本）
    - 归一化多维度加权排序（α×相关性 + β×元数据 + γ×文档属性）
    - Parent-Child 上下文扩展

Schema 动态注入：
    工具的 description 会在 tenant_id 可用时，追加租户专属的元数据字段枚举值，
    帮助 LLM 在自然语言查询中显式提及受控词，提升 Self-Querying 准确率。

Provider 来源：
    langgraph config.configurable.knowledge_provider
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════
# 输入 Schema
# ═══════════════════════════════════════════════════════════

class KnowledgeSearchInput(BaseModel):
    query: str = Field(
        description="检索问题，用自然语言描述你要查找的知识",
    )
    knowledge_base_id: int | None = Field(
        default=None,
        description="知识库 ID（可选，不指定则在当前 Agent 可访问的全部知识库中检索）",
    )
    top_k: int = Field(
        default=5, ge=1, le=20,
        description="最大返回数量，默认 5",
    )
    doc_category: str | None = Field(
        default=None,
        description="文档类别过滤（可选）",
    )
    industry: str | None = Field(
        default=None,
        description="行业过滤（可选）",
    )
    business_stage: str | None = Field(
        default=None,
        description="业务阶段过滤（可选）",
    )
    target_audience: str | None = Field(
        default=None,
        description="目标受众过滤（可选）",
    )


# ═══════════════════════════════════════════════════════════
# Tool 实现
# ═══════════════════════════════════════════════════════════

_BASE_DESCRIPTION = (
    "检索 AI 知识库中的文档。适用于：产品手册、销售话术、成功案例、"
    "内部政策、竞品分析、解决方案、合同模板、技术白皮书、培训材料、FAQ 等。"
    "支持自然语言查询，系统会自动理解查询意图并过滤相关文档。"
    "不适用于实时业务数据（如 CRM 客户/商机），那些应使用 xql_search。"
)


# 模块级缓存（不能放到 BaseTool 的 class 内，Pydantic 会把类注解当成 Field）
_DESCRIPTION_CACHE: dict[tuple[int, int], tuple[float, str]] = {}
_DESCRIPTION_CACHE_TTL = 300.0  # 5 分钟


class KnowledgeSearchTool(BaseTool):
    """知识库检索工具 — 支持 Schema 动态注入"""

    name: str = "knowledge_search"
    description: str = _BASE_DESCRIPTION
    args_schema: type[BaseModel] = KnowledgeSearchInput

    model_config = {"arbitrary_types_allowed": True}

    def _run(
        self, query: str,
        knowledge_base_id: int | None = None,
        top_k: int = 5,
        doc_category: str | None = None,
        industry: str | None = None,
        business_stage: str | None = None,
        target_audience: str | None = None,
    ) -> str:
        return asyncio.run(self._arun(
            query=query,
            knowledge_base_id=knowledge_base_id,
            top_k=top_k,
            doc_category=doc_category,
            industry=industry,
            business_stage=business_stage,
            target_audience=target_audience,
        ))

    async def _arun(
        self, query: str,
        knowledge_base_id: int | None = None,
        top_k: int = 5,
        doc_category: str | None = None,
        industry: str | None = None,
        business_stage: str | None = None,
        target_audience: str | None = None,
    ) -> str:
        # 从 langgraph runtime config 获取 provider 和租户上下文
        ctx = self._runtime_config()
        provider = ctx.get("knowledge_provider")
        tenant_id = int(ctx.get("tenant_id", 0) or 0)
        user_id = ctx.get("user_id", "") or ""
        thread_id = ctx.get("thread_id", "") or ""
        trace_id = ctx.get("trace_id", "") or ""

        if provider is None:
            return "知识库未启用，请联系管理员配置 knowledge-plugin。"
        if tenant_id <= 0:
            return "缺少租户上下文，无法检索知识库。"

        # 构造过滤条件（工具参数层 + Self-Querying 自动识别，互不冲突）
        filters: dict = {}
        if doc_category:
            filters["docCategory"] = doc_category
        if industry:
            filters["industryVertical"] = industry
        if business_stage:
            filters["businessStage"] = business_stage
        if target_audience:
            filters["targetAudience"] = target_audience

        try:
            results = await provider.search(
                tenant_id=tenant_id,
                query=query,
                knowledge_base_id=knowledge_base_id,
                filters=filters or None,
                top_k=top_k,
                enable_self_query=True,
                user_id=user_id,
                thread_id=thread_id,
                trace_id=trace_id,
            )
        except Exception as exc:
            logger.exception("Knowledge search failed: %s", exc)
            return f"知识库检索失败: {exc}"

        if not results:
            return f"未找到与 '{query}' 相关的知识文档。"

        return self._format_results(query, results)

    # ═══════════════════════════════════════════════════════════
    # Schema 动态注入
    # ═══════════════════════════════════════════════════════════

    def get_dynamic_description(
        self, tenant_id: int, knowledge_base_id: int = 0,
    ) -> str:
        """根据租户 Schema 生成带受控词表提示的描述。

        由调用方（如 SkillExecutor / 工具注册机）在知道 tenant_id 时提前调用，
        得到的字符串可覆盖到 prompt 中喂给 LLM，帮助它用正确的枚举值。

        缓存：相同 tenant_id + kb_id 组合 300 秒内直接复用。
        """
        import time
        if tenant_id <= 0:
            return _BASE_DESCRIPTION

        cache_key = (tenant_id, knowledge_base_id)
        cached = _DESCRIPTION_CACHE.get(cache_key)
        if cached:
            ts, desc = cached
            if time.time() - ts < _DESCRIPTION_CACHE_TTL:
                return desc

        try:
            from src.store.knowledge_dao import KnowledgeSchemaDAO
            row = KnowledgeSchemaDAO.get_for_kb(tenant_id, knowledge_base_id)
        except Exception as exc:
            logger.debug("Failed to fetch schema for dynamic description: %s", exc)
            return _BASE_DESCRIPTION

        if row is None or not row.fields:
            return _BASE_DESCRIPTION

        try:
            fields = json.loads(row.fields)
        except json.JSONDecodeError:
            return _BASE_DESCRIPTION

        desc = self._compose_description(fields)
        _DESCRIPTION_CACHE[cache_key] = (time.time(), desc)
        return desc

    @staticmethod
    def _compose_description(fields: list[dict]) -> str:
        """把 Schema 字段编织成 description 附加段"""
        lines = [_BASE_DESCRIPTION, "", "## 可用的元数据过滤字段（建议在查询中显式提及）"]
        for f in fields:
            fname = f.get("field", "")
            ftype = f.get("type", "string")
            desc = f.get("description", "")
            enum_vals = f.get("enum") or []
            if not fname:
                continue
            bits = [f"- **{fname}** ({ftype})"]
            if desc:
                bits.append(f"：{desc}")
            if enum_vals:
                shown = "、".join(str(v) for v in enum_vals[:8])
                more = f"…等 {len(enum_vals)} 项" if len(enum_vals) > 8 else ""
                bits.append(f"，可选值：{shown}{more}")
            lines.append("".join(bits))
        lines.append("")
        lines.append(
            "示例：查询「制造业的成功案例」时，系统会自动识别过滤 "
            "{docCategory: 成功案例, industryVertical: 制造业}。"
        )
        return "\n".join(lines)

    @classmethod
    def clear_description_cache(cls) -> None:
        """手动清除缓存（Schema 更新后调用）"""
        _DESCRIPTION_CACHE.clear()

    # ═══════════════════════════════════════════════════════════
    # 辅助
    # ═══════════════════════════════════════════════════════════

    @staticmethod
    def _runtime_config() -> dict[str, Any]:
        """从 langgraph runtime 获取 configurable 字典（非 langgraph 场景返回空）"""
        try:
            from langgraph.config import get_config
            return get_config().get("configurable", {}) or {}
        except Exception:
            return {}

    @staticmethod
    def _format_results(query: str, results) -> str:
        """把检索结果渲染为 Markdown 文本"""
        parts: list[str] = [f"## 知识库检索：{query}\n"]
        for i, chunk in enumerate(results, 1):
            parts.append(f"### 结果 {i}: {chunk.document_title or '未知文档'}")
            meta_bits = []
            if chunk.section_title:
                meta_bits.append(f"**章节**: {chunk.section_title}")
            if chunk.metadata.get("docCategory"):
                meta_bits.append(f"**类别**: {chunk.metadata['docCategory']}")
            if chunk.metadata.get("industryVertical"):
                meta_bits.append(f"**行业**: {chunk.metadata['industryVertical']}")
            meta_bits.append(f"**相关度**: {chunk.score:.3f}")
            parts.append(" | ".join(meta_bits))
            parts.append("")
            parts.append(chunk.content)
            if chunk.expanded_context:
                parts.append("\n**扩展上下文**：")
                parts.append(chunk.expanded_context)
            parts.append("\n---")
        parts.append(f"\n共 {len(results)} 条结果。")
        return "\n".join(parts)
