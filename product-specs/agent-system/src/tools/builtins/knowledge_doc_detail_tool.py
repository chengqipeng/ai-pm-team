"""knowledge_doc_detail 工具 — 获取文档目录 + 按章节获取完整内容

解决 knowledge_search 切片级检索的完整性问题：
- 模式 A（sections 为空）：返回文档目录结构，帮助 Agent 判断还有哪些章节
- 模式 B（指定 sections）：返回指定章节的完整内容（所有切片按顺序拼接）

典型调用流程：
    1. knowledge_search 命中某文档的几个切片
    2. knowledge_doc_detail(doc_id, sections=[]) → 获取目录
    3. knowledge_doc_detail(doc_id, sections=["差压范围","无补偿流量性能"]) → 获取完整章节
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════
# 输入 Schema
# ═══════════════════════════════════════════════════════════

class KnowledgeDocDetailInput(BaseModel):
    doc_id: str = Field(
        description="文档 ID（从 knowledge_search 结果中获取）",
    )
    sections: list[str] = Field(
        default_factory=list,
        description="要获取的章节标题列表。为空时返回文档目录；指定章节时返回该章节的完整内容",
    )


# ═══════════════════════════════════════════════════════════
# Tool 实现
# ═══════════════════════════════════════════════════════════

class KnowledgeDocDetailTool(BaseTool):
    """文档详情工具 — 获取目录或指定章节的完整内容"""

    name: str = "knowledge_doc_detail"
    description: str = (
        "获取知识库文档的目录结构或指定章节的完整内容。"
        "当 knowledge_search 返回的切片不够完整时，用此工具深入获取文档的特定章节。"
        "用法：1) sections 为空 → 返回文档目录（章节列表+切片数）；"
        "2) 指定 sections → 返回这些章节的完整文本内容。"
    )
    args_schema: type[BaseModel] = KnowledgeDocDetailInput

    model_config = {"arbitrary_types_allowed": True}

    def _run(self, doc_id: str, sections: list[str] | None = None) -> str:
        return asyncio.run(self._arun(doc_id=doc_id, sections=sections))

    async def _arun(self, doc_id: str, sections: list[str] | None = None) -> str:
        from src.store.knowledge_dao import KnowledgeChunkDAO, KnowledgeDocumentDAO

        if not doc_id:
            return "错误：doc_id 不能为空"

        # 获取文档基本信息
        doc = KnowledgeDocumentDAO.get_by_doc_id(doc_id)
        if doc is None:
            return f"错误：文档 {doc_id} 不存在"

        sections = sections or []

        if not sections:
            # 模式 A：返回文档目录
            return await self._get_toc(doc, doc_id)
        else:
            # 模式 B：返回指定章节的完整内容
            return await self._get_sections_content(doc, doc_id, sections)

    async def _get_toc(self, doc, doc_id: str) -> str:
        """返回文档目录结构"""
        from src.store.knowledge_dao import KnowledgeChunkDAO

        # 从 PG 查询章节分布
        section_stats = await asyncio.to_thread(
            self._query_section_stats, doc_id
        )

        parts: list[str] = []
        parts.append(f"## 📄 文档目录：{doc.title}")
        parts.append(f"")
        parts.append(f"| 信息 | 值 |")
        parts.append(f"|------|-----|")
        parts.append(f"| 文件名 | {doc.file_name} |")
        parts.append(f"| 类型 | {doc.file_type} |")
        parts.append(f"| 切片总数 | {doc.chunk_count} |")
        parts.append(f"| 质量分 | {doc.quality_score:.2f} |")
        if doc.summary:
            parts.append(f"| 摘要 | {doc.summary[:200]} |")
        parts.append("")

        if section_stats:
            parts.append("### 章节列表")
            parts.append("")
            parts.append("| 序号 | 章节标题 | 切片数 | 内容类型 |")
            parts.append("|------|----------|--------|----------|")
            for i, s in enumerate(section_stats, 1):
                title = s["title"] or "(无标题/正文)"
                parts.append(
                    f"| {i} | {title} | {s['count']} | {s['types']} |"
                )
            parts.append("")
            parts.append(
                f"共 {len(section_stats)} 个章节。"
                f"使用 knowledge_doc_detail(doc_id=\"{doc_id}\", sections=[\"章节标题\"]) "
                f"获取指定章节的完整内容。"
            )
        else:
            parts.append("该文档无章节结构信息。")

        return "\n".join(parts)

    async def _get_sections_content(
        self, doc, doc_id: str, sections: list[str]
    ) -> str:
        """返回指定章节的完整内容"""
        from src.store.knowledge_dao import KnowledgeChunkDAO

        chunks = await asyncio.to_thread(
            self._query_chunks_by_sections, doc_id, sections
        )

        if not chunks:
            return f"未找到章节 {sections} 的内容。请检查章节标题是否正确（可先用 sections=[] 获取目录）。"

        parts: list[str] = []
        parts.append(f"## 📄 {doc.title}")
        parts.append(f"")

        # 按章节分组输出
        current_section = None
        for chunk in chunks:
            section = chunk.section_title or "(正文)"
            if section != current_section:
                current_section = section
                parts.append(f"### {section}")
                parts.append("")
            # 优先使用 display_content（保留表格格式），回退到 content
            text = chunk.display_content if chunk.display_content else chunk.content
            if text:
                parts.append(text)
                parts.append("")

        parts.append(f"---")
        parts.append(f"📄 来源：{doc.title} | 章节：{', '.join(sections)} | 切片数：{len(chunks)}")

        return "\n".join(parts)

    @staticmethod
    def _query_section_stats(doc_id: str) -> list[dict]:
        """查询文档的章节统计信息"""
        from src.store.pg_pool import get_conn

        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT
                    section_title,
                    COUNT(*) as chunk_count,
                    MIN(chunk_index) as first_idx,
                    string_agg(DISTINCT chunk_type, ',' ORDER BY chunk_type) as types
                FROM ai_knowledge_chunk
                WHERE doc_id = %s AND delete_flg = 0
                GROUP BY section_title
                ORDER BY MIN(chunk_index)
            """, (doc_id,))
            rows = cur.fetchall()
            return [
                {
                    "title": r[0] or "",
                    "count": r[1],
                    "first_idx": r[2],
                    "types": r[3] or "Text",
                }
                for r in rows
            ]

    @staticmethod
    def _query_chunks_by_sections(
        doc_id: str, sections: list[str]
    ) -> list:
        """按 doc_id + section_title 获取切片"""
        from src.store.pg_pool import get_conn
        from src.store.knowledge_models import KnowledgeChunkRow

        with get_conn() as conn:
            cur = conn.cursor()
            # 支持匹配"(无标题)"为空字符串
            normalized = []
            for s in sections:
                if s in ("(无标题)", "(无标题/正文)", "(正文)", ""):
                    normalized.append("")
                else:
                    normalized.append(s)

            cur.execute("""
                SELECT id, chunk_id, doc_id, chunk_index, content,
                       display_content, section_title, section_path, chunk_type
                FROM ai_knowledge_chunk
                WHERE doc_id = %s
                  AND section_title = ANY(%s)
                  AND delete_flg = 0
                ORDER BY chunk_index
            """, (doc_id, normalized))

            rows = cur.fetchall()
            result = []
            for r in rows:
                chunk = KnowledgeChunkRow()
                chunk.id = r[0]
                chunk.chunk_id = r[1]
                chunk.doc_id = r[2]
                chunk.chunk_index = r[3]
                chunk.content = r[4] or ""
                chunk.display_content = r[5] or ""
                chunk.section_title = r[6] or ""
                chunk.section_path = r[7] or ""
                chunk.chunk_type = r[8] or "Text"
                result.append(chunk)
            return result
