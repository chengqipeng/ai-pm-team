"""文档入库流水线 — 5 阶段处理

对应 doc/知识库体系设计方案.md §4.1。

流水线：
    Phase 1: LKEAP 解析 (PDF/DOCX → Markdown)
    Phase 1.5: 文本清洗（4 Stage）
    Phase 2: LLM 自动打标 + 质量评分
    Phase 3: 两级切分（Segment + Chunk）
    Phase 4: 混合索引（PG + VDB）

实现 IngestPipeline 协议，供 IngestWorker 调用：
    pipeline.run(task)
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
import os
import re
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.store.knowledge_dao import (
    KnowledgeBaseDAO, KnowledgeChunkDAO, KnowledgeDocumentDAO,
    KnowledgeIngestLogDAO, KnowledgeSchemaDAO, KnowledgeSegmentDAO,
)
from src.store.knowledge_models import (
    KnowledgeChunkRow, KnowledgeSegmentRow,
)

from .cleaning import CleaningResult, DocumentCleaningService
from .guard import IngestionGuard
from .lkeap_client import ChunkInfo, ParseResult, TencentLKEAPClient
from .quality import DocumentQualityScorer
from .queue import IngestTask
from .vdb_writer import KnowledgeVectorStore

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════
# 自动打标 Prompt
# ═══════════════════════════════════════════════════════════

AUTO_TAG_PROMPT = """你是一个文档分类专家。请根据以下文档内容，提取元数据并生成摘要。

## 租户元数据 Schema
{schema_json}

## 文档内容（前 4000 字符）
{document_content}

## 输出要求
请严格以 JSON 格式输出（不要任何其他说明文字）：
{{
  "metadata": {{
    "docCategory": "从 Schema 枚举值中选择最匹配的",
    "industryVertical": "从 Schema 枚举值中选择",
    "businessStage": "从 Schema 枚举值中选择",
    "targetAudience": "从 Schema 枚举值中选择",
    "productService": "从 Schema 枚举值中选择",
    "datePublished": "从文档中提取日期，格式 YYYY-MM-DD，无则 null"
  }},
  "summary": "200-300 字的文档摘要，概括核心内容和关键信息",
  "keywords": ["关键词1", "关键词2", "关键词3"]
}}

注意：
1. 元数据值必须从 Schema 枚举值中选择，无法匹配时设为 null
2. 摘要要包含文档的核心主题、关键数据点、适用场景
3. keywords 最多 10 个
"""


# ═══════════════════════════════════════════════════════════
# JSON 鲁棒抽取工具
# ═══════════════════════════════════════════════════════════

def _extract_json_object(text: str) -> dict | None:
    """从 LLM 输出中鲁棒抽取第一个 JSON 对象

    处理的情况：
        - 纯 JSON: {"a": 1}
        - fenced code block: ```json\\n{...}\\n```
        - 带前言: "Sure, here's the result:\\n```json\\n{...}\\n```"
        - JSON 前后有冗余说明
    """
    if not text:
        return None
    # Step 1: 去掉可能的 Markdown 代码围栏
    stripped = text.strip()
    if stripped.startswith("```"):
        # 去掉第一行围栏
        lines = stripped.split("\n")
        if lines[0].strip().startswith("```"):
            lines = lines[1:]
        # 去掉最后一行围栏
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        stripped = "\n".join(lines).strip()

    # Step 2: 直接尝试解析
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        pass

    # Step 3: 查找第一个 "{" 并做括号平衡匹配
    start = stripped.find("{")
    if start < 0:
        return None
    depth = 0
    in_string = False
    escape = False
    for i in range(start, len(stripped)):
        ch = stripped[i]
        if escape:
            escape = False
            continue
        if ch == "\\":
            escape = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(stripped[start:i + 1])
                except json.JSONDecodeError:
                    return None
    return None


# ═══════════════════════════════════════════════════════════
# DocumentIngestionPipeline
# ═══════════════════════════════════════════════════════════

class DocumentIngestionPipeline:
    """文档入库五阶段流水线

    实现 IngestPipeline 协议（只要求 async run(task) 方法）。
    失败抛异常，由 IngestWorker 调 queue.nack 自动退避重试。
    """

    def __init__(
        self,
        lkeap: TencentLKEAPClient,
        vector_store: KnowledgeVectorStore,
        cleaning_service: DocumentCleaningService,
        quality_scorer: DocumentQualityScorer,
        llm: Any = None,
        embedding_fn: Any = None,
        guard: IngestionGuard | None = None,
        parsed_dir: str = "./data/knowledge/parsed",
        chunk_size_tokens: int = 800,
        chunk_overlap_tokens: int = 200,
        segment_target_chars: int = 4000,
    ) -> None:
        self._lkeap = lkeap
        self._vdb = vector_store
        self._cleaner = cleaning_service
        self._scorer = quality_scorer
        self._llm = llm
        self._embedding_fn = embedding_fn
        self._guard = guard or IngestionGuard()
        self._parsed_dir = Path(parsed_dir)
        self._parsed_dir.mkdir(parents=True, exist_ok=True)
        self._chunk_size = chunk_size_tokens
        self._chunk_overlap = chunk_overlap_tokens
        self._seg_target = segment_target_chars

    # ═══ IngestPipeline 协议入口 ═══

    async def run(self, task: IngestTask) -> None:
        """执行完整流水线。由 IngestWorker 调用。"""
        payload = task.payload
        doc_id = payload.get("doc_id", "")
        if not doc_id:
            raise ValueError(f"Task {task.task_id} missing doc_id in payload")

        KnowledgeIngestLogDAO.update_phase(task.task_id, "parsing", 5)
        # Phase 1: LKEAP 解析
        t0 = time.time()
        markdown, page_count, failed_pages = await self._phase1_parse(task, payload)
        parse_ms = int((time.time() - t0) * 1000)
        KnowledgeIngestLogDAO.update_phase(
            task.task_id, "cleaning", 25, "parse_duration_ms", parse_ms,
        )

        # Phase 1.5: 清洗
        t0 = time.time()
        cleaning: CleaningResult = self._cleaner.clean(markdown)
        clean_ms = int((time.time() - t0) * 1000)
        KnowledgeDocumentDAO.update_clean_status(doc_id, "cleaned")
        KnowledgeIngestLogDAO.update_phase(
            task.task_id, "tagging", 40, "clean_duration_ms", clean_ms,
        )

        # Phase 2: LLM 打标 + 质量评分
        t0 = time.time()
        metadata, summary, keywords = await self._phase2_auto_tag(
            task, cleaning.content,
        )
        quality = self._scorer.score(
            content=cleaning.content,
            cleaning_signals=cleaning.signals,
            total_pages=page_count,
            failed_pages=len(failed_pages),
        )
        KnowledgeDocumentDAO.update_metadata(
            doc_id=doc_id,
            summary=summary,
            keywords=json.dumps(keywords, ensure_ascii=False),
            metadata=json.dumps(metadata, ensure_ascii=False),
            quality_score=quality.score,
            quality_signals=quality.to_json(),
            date_published=self._parse_date(metadata.get("datePublished")),
        )
        tag_ms = int((time.time() - t0) * 1000)
        KnowledgeIngestLogDAO.update_phase(
            task.task_id, "splitting", 55, "tagging_duration_ms", tag_ms,
        )

        # Phase 3: 两级切分
        t0 = time.time()
        segments, chunks = await self._phase3_split(
            task, doc_id, cleaning, markdown,
        )
        # 批量写 Segment + Chunk
        KnowledgeSegmentDAO.batch_insert(segments)
        # 把打标出来的元数据冗余到 chunk 上（加速检索过滤）
        self._apply_metadata_to_chunks(chunks, metadata, task)
        KnowledgeChunkDAO.batch_insert(chunks)
        KnowledgeDocumentDAO.update_chunk_status(
            doc_id, "indexed",
            chunk_count=len(chunks),
            segment_count=len(segments),
        )
        split_ms = int((time.time() - t0) * 1000)
        KnowledgeIngestLogDAO.update_phase(
            task.task_id, "indexing", 75, "split_duration_ms", split_ms,
        )

        # Phase 4: 向量库索引（chunks + 文档摘要）
        t0 = time.time()
        vector_count = await self._phase4_index(task, doc_id, chunks, summary)
        index_ms = int((time.time() - t0) * 1000)
        KnowledgeIngestLogDAO.update_phase(
            task.task_id, "indexing", 95, "index_duration_ms", index_ms,
        )

        # 更新 KB 统计
        KnowledgeBaseDAO.update_stats(
            task.knowledge_base_id,
            doc_delta=1,
            chunk_delta=len(chunks),
        )

        # 收尾
        KnowledgeIngestLogDAO.finish(
            task_id=task.task_id,
            status="success",
            total_chars=len(cleaning.content),
            segment_count=len(segments),
            chunk_count=len(chunks),
            vector_count=vector_count,
            quality_score=quality.score,
        )
        logger.info(
            "Ingestion done: doc_id=%s, segments=%d, chunks=%d, quality=%.2f",
            doc_id, len(segments), len(chunks), quality.score,
        )

    # ═══ Phase 1: LKEAP 解析 ═══

    async def _phase1_parse(
        self, task: IngestTask, payload: dict,
    ) -> tuple[str, int, list[int]]:
        """返回 (markdown, page_count, failed_pages)"""
        doc_id = payload["doc_id"]
        file_path = payload.get("file_path", "")
        file_type = payload.get("file_type", "").lower().lstrip(".")

        if not file_path or not os.path.exists(file_path):
            raise FileNotFoundError(f"File not found: {file_path}")

        if not TencentLKEAPClient.is_supported(file_type):
            raise ValueError(f"Unsupported file type: {file_type}")

        KnowledgeDocumentDAO.update_parse_status(doc_id, "parsing")

        # 直接用本地文件 → base64
        with open(file_path, "rb") as f:
            data = f.read()
        file_base64 = base64.b64encode(data).decode("utf-8")

        # 小文件用 SSE（准实时），大文件用异步轮询（SSE 对 100M 以上不支持）
        async with self._guard.acquire_lkeap_slot():
            if len(data) < 50 * 1024 * 1024:
                result: ParseResult = await asyncio.to_thread(
                    self._lkeap.parse_document_sse,
                    file_base64=file_base64, file_type=file_type,
                )
            else:
                result = await self._lkeap.parse_document(
                    file_base64=file_base64, file_type=file_type,
                    poll_interval=3.0, max_wait=1800.0,
                )

        if result.status != "SUCCESS":
            KnowledgeDocumentDAO.update_parse_status(
                doc_id, "failed", parse_error=f"LKEAP status={result.status}",
            )
            raise RuntimeError(f"LKEAP parse failed: status={result.status}")

        # 下载解析产物 + 保存到本地 parsed_dir
        markdown = await asyncio.to_thread(
            TencentLKEAPClient.download_and_extract_markdown, result.result_url,
        )
        page_count = (result.success_page_num or 0) + (result.fail_page_num or 0)
        failed_pages = result.failed_pages or []

        # 存解析产物
        doc_dir = self._parsed_dir / doc_id
        doc_dir.mkdir(parents=True, exist_ok=True)
        md_path = doc_dir / "content.md"
        md_path.write_text(markdown, encoding="utf-8")

        # 更新 PG
        KnowledgeDocumentDAO.update_parse_status(
            doc_id=doc_id,
            parse_status="parsed",
            parse_task_id=result.task_id,
            parsed_md_url=str(md_path),
            page_count=page_count,
            total_chars=len(markdown),
        )

        logger.info(
            "Phase 1 parse done: doc_id=%s, %d chars, %d pages",
            doc_id, len(markdown), page_count,
        )
        return markdown, page_count, failed_pages

    # ═══ Phase 2: LLM 打标 ═══

    async def _phase2_auto_tag(
        self, task: IngestTask, content: str,
    ) -> tuple[dict, str, list[str]]:
        """返回 (metadata, summary, keywords)

        - 有 Schema + LLM → 带受控词表的严格打标
        - 无 Schema 但有 LLM → 用通用 prompt 提取 summary + keywords（metadata 空）
        - 无 LLM → 直接降级：summary 取正文前 300 字，metadata/keywords 空
        - user_metadata 始终覆盖自动打标结果（用户手动指定优先）
        """
        user_meta = task.payload.get("user_metadata") or {}

        if not self._llm:
            logger.info("Skip auto-tag (no llm)")
            summary = content[:300] if content else ""
            return dict(user_meta), summary, []

        # 取 Schema（可能为空）
        schema_row = await asyncio.to_thread(
            KnowledgeSchemaDAO.get_for_kb, task.tenant_id, task.knowledge_base_id,
        )
        schema_fields: list = []
        if schema_row and schema_row.fields:
            try:
                schema_fields = json.loads(schema_row.fields) or []
            except json.JSONDecodeError:
                schema_fields = []

        prompt = AUTO_TAG_PROMPT.format(
            schema_json=json.dumps(schema_fields, ensure_ascii=False, indent=2),
            document_content=content[:8000],
        )

        try:
            resp = await self._llm.ainvoke(prompt)
            text = getattr(resp, "content", None) or str(resp)
        except Exception as exc:
            logger.warning("Auto-tag LLM call failed: %s", exc)
            return dict(user_meta), content[:300], []

        parsed = _extract_json_object(text)
        if parsed is None:
            logger.warning("Auto-tag response not valid JSON: %s", text[:200])
            return dict(user_meta), content[:300], []

        metadata = parsed.get("metadata") or {}
        # 过滤 None / 空字符串
        metadata = {
            k: v for k, v in metadata.items()
            if v is not None and v != ""
        }
        # user_metadata 覆盖自动打标
        metadata.update({k: v for k, v in user_meta.items() if v is not None})

        summary = parsed.get("summary") or content[:300]
        keywords = parsed.get("keywords") or []
        if not isinstance(keywords, list):
            keywords = [str(keywords)]
        return metadata, summary, keywords

    # ═══ Phase 3: 两级切分 ═══

    async def _phase3_split(
        self, task: IngestTask, doc_id: str,
        cleaning: CleaningResult, original_markdown: str,
    ) -> tuple[list[KnowledgeSegmentRow], list[KnowledgeChunkRow]]:
        """返回 (segments, chunks)"""
        content = cleaning.content

        # ── Step 3a: Segment（章节级聚合） ──
        segments = self._split_segments(doc_id, task, content)

        # ── Step 3b: Chunk（切片级） ──
        # 优先尝试 LKEAP 多级切分；失败/无网络时本地降级
        chunks: list[KnowledgeChunkRow] = []
        try:
            chunks = await self._try_lkeap_split(task, doc_id, cleaning, segments)
        except Exception as exc:
            logger.info("LKEAP split unavailable (%s); fallback to local", exc)

        if not chunks:
            chunks = self._local_split_chunks(doc_id, task, segments, cleaning)

        return segments, chunks

    def _split_segments(
        self, doc_id: str, task: IngestTask, content: str,
    ) -> list[KnowledgeSegmentRow]:
        """按标题树做 Segment 切分

        规则：
            - 遇到 H1/H2 边界开新 Segment
            - Segment 超过 seg_target_chars × 2 → 强制截断开新段
        """
        segments: list[KnowledgeSegmentRow] = []
        now_ms = int(time.time() * 1000)

        # 按行遍历，累积 Segment
        lines = content.split("\n")
        buf: list[str] = []
        current_title = ""
        current_path: list[str] = []
        current_level = 0
        start_offset = 0
        buf_chars = 0
        segment_index = 0

        def flush():
            nonlocal buf, buf_chars, start_offset, segment_index
            if not buf:
                return
            seg_content = "\n".join(buf).strip()
            if not seg_content:
                buf, buf_chars = [], 0
                return
            segments.append(KnowledgeSegmentRow(
                segment_id=f"seg_{uuid.uuid4().hex[:20]}",
                tenant_id=task.tenant_id,
                knowledge_base_id=task.knowledge_base_id,
                doc_id=doc_id,
                title=current_title,
                section_path=" / ".join(current_path),
                content=seg_content,
                content_tokens=self._rough_tokens(seg_content),
                segment_index=segment_index,
                heading_level=current_level,
                start_offset=start_offset,
                end_offset=start_offset + len(seg_content),
                created_at=now_ms,
                updated_at=now_ms,
            ))
            segment_index += 1
            start_offset += len(seg_content) + 1
            buf, buf_chars = [], 0

        for ln in lines:
            m1 = re.match(r"^#\s+(.+)$", ln)
            m2 = re.match(r"^##\s+(.+)$", ln)
            is_heading = m1 or m2
            # 遇到新标题且 buf 非空 → flush
            if is_heading and buf_chars > 0:
                flush()

            if m1:
                current_title = m1.group(1).strip()
                current_path = [current_title]
                current_level = 1
            elif m2:
                current_title = m2.group(1).strip()
                if current_level < 1:
                    current_path = [current_title]
                else:
                    current_path = (current_path[:1] if current_path else []) + [current_title]
                current_level = 2

            # 单行超长（比如 PDF 未换行的超大段落）— 按字符硬切
            seg_cap = self._seg_target * 2
            if len(ln) >= seg_cap:
                # 先把之前累计的内容 flush（保持章节边界）
                if buf_chars > 0:
                    flush()
                # 按 seg_cap 硬切当前行
                pos = 0
                while pos < len(ln):
                    piece = ln[pos:pos + seg_cap]
                    buf.append(piece)
                    buf_chars += len(piece) + 1
                    flush()
                    pos += seg_cap
                continue

            buf.append(ln)
            buf_chars += len(ln) + 1

            # 超长强制截断（多行累积超过阈值）
            if buf_chars >= seg_cap:
                flush()

        flush()

        # 如果文档完全没有标题 → 产出单一 Segment
        if not segments and content.strip():
            segments.append(KnowledgeSegmentRow(
                segment_id=f"seg_{uuid.uuid4().hex[:20]}",
                tenant_id=task.tenant_id,
                knowledge_base_id=task.knowledge_base_id,
                doc_id=doc_id,
                title="",
                section_path="",
                content=content.strip(),
                content_tokens=self._rough_tokens(content),
                segment_index=0,
                heading_level=0,
                start_offset=0,
                end_offset=len(content),
                created_at=now_ms,
                updated_at=now_ms,
            ))
        return segments

    async def _try_lkeap_split(
        self, task: IngestTask, doc_id: str,
        cleaning: CleaningResult, segments: list[KnowledgeSegmentRow],
    ) -> list[KnowledgeChunkRow]:
        """尝试 LKEAP CreateSplitDocumentFlow（需要 file_base64，失败时回退本地）"""
        # LKEAP 切分需要原始文件，此处简化为不走 LKEAP 切分，统一用本地。
        # （LKEAP 的文本级切分接口目前没有从 markdown 文本直接切分的 API）
        return []

    def _local_split_chunks(
        self, doc_id: str, task: IngestTask,
        segments: list[KnowledgeSegmentRow], cleaning: CleaningResult,
    ) -> list[KnowledgeChunkRow]:
        """本地切分：每个 Segment 内按滑动窗口切 Chunk"""
        chunks: list[KnowledgeChunkRow] = []
        now_ms = int(time.time() * 1000)
        global_idx = 0

        chunk_char_size = max(32, self._chunk_size * 2)          # 粗略 1 token ≈ 2 chars；下限 32
        # overlap 防御：必须严格小于 chunk_char_size，否则滑动窗口会原地踏步
        chunk_overlap_chars = max(0, min(
            self._chunk_overlap * 2,
            chunk_char_size - 1,     # 至少推进 1 字符
        ))

        for seg in segments:
            # Segment 内滑动窗口
            text = seg.content
            if len(text) <= chunk_char_size:
                # 一个 Segment 就是一个 Chunk
                chunks.append(self._mk_chunk(
                    doc_id, task, seg, text, global_idx, now_ms,
                ))
                global_idx += 1
                seg.chunk_count = 1
                continue

            # 滑动窗口
            count_in_seg = 0
            start = 0
            while start < len(text):
                end = min(start + chunk_char_size, len(text))
                piece = text[start:end]
                chunks.append(self._mk_chunk(
                    doc_id, task, seg, piece, global_idx, now_ms,
                ))
                global_idx += 1
                count_in_seg += 1
                if end >= len(text):
                    break
                step = chunk_char_size - chunk_overlap_chars
                # 防御：step 必须为正，避免死循环
                if step <= 0:
                    step = 1
                start += step
            seg.chunk_count = count_in_seg

        return chunks

    def _mk_chunk(
        self, doc_id: str, task: IngestTask,
        seg: KnowledgeSegmentRow, text: str, idx: int, now_ms: int,
    ) -> KnowledgeChunkRow:
        ct = self._detect_chunk_type(text)
        return KnowledgeChunkRow(
            chunk_id=f"chunk_{uuid.uuid4().hex[:20]}",
            tenant_id=task.tenant_id,
            knowledge_base_id=task.knowledge_base_id,
            dataset_id=task.dataset_id,
            doc_id=doc_id,
            content=text,
            display_content=text,
            content_hash=hashlib.sha256(text.encode("utf-8")).hexdigest()[:32],
            content_tokens=self._rough_tokens(text),
            chunk_index=idx,
            chunk_type=ct,
            section_title=seg.title,
            section_path=seg.section_path,
            parent_segment_id=seg.segment_id,
            created_at=now_ms,
            updated_at=now_ms,
        )

    @staticmethod
    def _detect_chunk_type(text: str) -> str:
        """粗略判断切片类型"""
        t = text.strip()
        if t.count("|") > 5 and "\n" in t:
            return "Table"
        if t.startswith("![") or "data:image" in t:
            return "Image_Description"
        if t.startswith("#") and len(t.split("\n")[0]) < 200:
            return "Title"
        return "Text"

    @staticmethod
    def _rough_tokens(text: str) -> int:
        """粗略估算 token（中文按 1 字符 1 token，英文按 4 字符 1 token）"""
        if not text:
            return 0
        cjk = sum(1 for c in text if 0x4E00 <= ord(c) <= 0x9FFF)
        other = len(text) - cjk
        return cjk + other // 4

    def _apply_metadata_to_chunks(
        self,
        chunks: list[KnowledgeChunkRow],
        metadata: dict,
        task: IngestTask,
    ) -> None:
        """把文档级元数据冗余到每个 chunk 的过滤字段上"""
        for c in chunks:
            c.doc_category = str(metadata.get("docCategory") or "")[:100]
            c.industry = str(metadata.get("industryVertical") or "")[:100]
            c.business_stage = str(metadata.get("businessStage") or "")[:100]
            c.target_audience = str(metadata.get("targetAudience") or "")[:100]
            # productService 可能是 list
            ps = metadata.get("productService")
            if isinstance(ps, list):
                c.product_service = ",".join(str(x) for x in ps)[:500]
            else:
                c.product_service = str(ps or "")[:500]
            c.date_published = self._parse_date(metadata.get("datePublished"))

    @staticmethod
    def _parse_date(value) -> int:
        """把 'YYYY-MM-DD' 或时间戳转毫秒；失败返回 0"""
        if not value:
            return 0
        if isinstance(value, (int, float)):
            return int(value)
        try:
            import datetime as dt
            d = dt.datetime.strptime(str(value)[:10], "%Y-%m-%d")
            return int(d.timestamp() * 1000)
        except Exception:
            return 0

    # ═══ Phase 4: 向量索引 ═══

    async def _phase4_index(
        self, task: IngestTask, doc_id: str,
        chunks: list[KnowledgeChunkRow], summary: str,
    ) -> int:
        """写 VDB（kb_chunks + kb_doc_summary），并回填 vector_synced=1"""
        if not chunks:
            return 0

        # 1. chunk 向量化
        texts_for_embed = [c.content[:2000] for c in chunks]
        vectors = await self._embed_many(texts_for_embed)

        chunk_records: list[dict] = []
        synced_ids: list[str] = []
        for c, vec in zip(chunks, vectors):
            if not vec:
                continue
            chunk_records.append({
                "id": c.chunk_id,
                "vector": vec,
                "tenant_id": str(c.tenant_id),
                "knowledge_base_id": str(c.knowledge_base_id),
                "dataset_id": str(c.dataset_id),
                "doc_id": c.doc_id,
                "chunk_type": c.chunk_type,
                "doc_category": c.doc_category,
                "industry": c.industry,
                "business_stage": c.business_stage,
                "target_audience": c.target_audience,
                "product_service": c.product_service,
                "status": "active",
                "date_published": c.date_published,
                # 冗余展示字段
                "abstract": c.content[:200],
                "section_title": c.section_title,
                "chunk_index": c.chunk_index,
            })
            synced_ids.append(c.chunk_id)

        if chunk_records:
            try:
                await asyncio.to_thread(self._vdb.upsert_chunks, chunk_records)
                await asyncio.to_thread(
                    KnowledgeChunkDAO.mark_vector_synced,
                    synced_ids,
                    "lkeap/default",
                    len(vectors[0]) if vectors and vectors[0] else 0,
                )
            except Exception as exc:
                logger.exception("VDB chunk upsert failed: %s", exc)
                for cid in synced_ids:
                    await asyncio.to_thread(
                        KnowledgeChunkDAO.mark_vector_failed, cid, str(exc),
                    )
                raise

        # 2. 文档摘要向量化 + 写入 summary collection
        try:
            if summary:
                summary_vecs = await self._embed_many([summary])
                if summary_vecs and summary_vecs[0]:
                    await asyncio.to_thread(
                        self._vdb.upsert_summaries,
                        [{
                            "id": doc_id,
                            "vector": summary_vecs[0],
                            "tenant_id": str(task.tenant_id),
                            "knowledge_base_id": str(task.knowledge_base_id),
                            "doc_id": doc_id,
                            "doc_category": chunks[0].doc_category if chunks else "",
                            "industry": chunks[0].industry if chunks else "",
                            "status": "active",
                        }],
                    )
        except Exception as exc:
            logger.warning("VDB summary upsert failed (non-fatal): %s", exc)

        return len(chunk_records)

    async def _embed_many(self, texts: list[str]) -> list[list[float]]:
        """批量向量化 — 优先用注入的 embedding_fn，否则用 LKEAP"""
        if not texts:
            return []
        if self._embedding_fn is not None:
            if asyncio.iscoroutinefunction(self._embedding_fn):
                # 用户注入的异步函数一次一条（简化），批量时自行优化
                return [await self._embedding_fn(t) for t in texts]
            return await asyncio.to_thread(
                lambda: [self._embedding_fn(t) for t in texts]
            )
        # 默认走 LKEAP（单批最多 10 条，按需拆分）
        all_vecs: list[list[float]] = []
        for i in range(0, len(texts), 10):
            batch = texts[i:i + 10]
            vecs = await asyncio.to_thread(self._lkeap.get_embedding, batch)
            all_vecs.extend(vecs)
        return all_vecs
