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
    KnowledgeIngestLogDAO, KnowledgeSchemaDAO,
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

## 候选关键词（TF-IDF 自动提取，供参考）
{candidate_keywords}

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
  "summary": "200-300字的文档摘要，概括核心内容和关键信息",
  "keywords": ["最多 10 个关键词"]
}}

注意：
1. 元数据值必须从 Schema 枚举值中选择，无法匹配时设为 null
2. summary 控制在 200-300 字，概括文档核心主题、关键数据点、适用场景
3. keywords 优先从候选关键词中精选，可补充遗漏的核心概念，最多 10 个
4. 确保输出是完整合法的 JSON，不要被截断
"""


# ═══════════════════════════════════════════════════════════
# 内置默认 Schema（对标旧方案 preset_tag_groups.json）
# 当租户未配置 ai_knowledge_schema 时自动使用
# ═══════════════════════════════════════════════════════════

_DEFAULT_SCHEMA_FIELDS = [
    # ── 核心分类（必填）─────────────────────────────────
    {
        "field": "docCategory",
        "type": "enum",
        "required": True,
        "description": "文档类别（必填）",
        "enum": [
            "产品手册", "技术白皮书", "解决方案", "成功案例",
            "销售话术", "培训材料", "FAQ", "内部政策",
            "竞品分析", "合同模板", "行业报告", "操作指南",
            "API 文档", "会议纪要", "客户沟通记录", "其他",
        ],
    },
    # ── 业务维度 ─────────────────────────────────────────
    {
        "field": "industryVertical",
        "type": "enum",
        "required": False,
        "description": "所属行业",
        "enum": [
            "制造业", "金融服务", "互联网", "医疗健康",
            "教育培训", "零售消费", "能源化工", "政府公共",
            "房地产", "物流运输", "农林牧渔", "批发贸易",
            "建筑工程", "文化娱乐", "通用/跨行业",
        ],
    },
    {
        "field": "businessStage",
        "type": "enum",
        "required": False,
        "description": "适用业务阶段（销售 / 服务 / 实施 等生命周期阶段）",
        "enum": [
            "市场推广", "线索获取", "售前咨询", "需求调研",
            "方案设计", "产品演示", "商务谈判", "合同签订",
            "实施交付", "上线培训", "售后服务", "客户成功",
            "续费拓展", "通用",
        ],
    },
    {
        "field": "targetAudience",
        "type": "enum",
        "required": False,
        "description": "目标受众（文档面向的角色）",
        "enum": [
            "CEO/COO", "CFO", "CIO/CTO", "业务负责人",
            "销售负责人", "一线销售", "市场人员", "实施顾问",
            "技术人员", "运维人员", "产品经理", "终端用户",
            "财务人员", "人事行政", "通用",
        ],
    },
    {
        "field": "productService",
        "type": "string",
        "required": False,
        "description": "涉及的产品/服务名称，多个用逗号分隔（自由填写）",
    },
    {
        "field": "businessFunction",
        "type": "enum",
        "required": False,
        "description": "业务职能（文档归属的职能域）",
        "enum": [
            "销售", "市场", "售前", "交付/实施", "客户成功",
            "产品", "研发", "运维", "客服", "财务",
            "人力资源", "法务/合规", "采购/供应链", "行政", "IT/信息化",
            "战略/投资", "通用",
        ],
    },
    {
        "field": "region",
        "type": "enum",
        "required": False,
        "description": "适用地域/区域",
        "enum": [
            "中国大陆", "港澳台", "北美", "欧洲", "亚太（不含大中华）",
            "中东", "拉美", "非洲", "全球/跨区域",
        ],
        "default": "中国大陆",
    },
    # ── 访问控制 / 可见性 ────────────────────────────────
    {
        "field": "confidentiality",
        "type": "enum",
        "required": False,
        "description": "保密级别",
        "enum": ["公开", "内部", "机密", "绝密"],
        "default": "内部",
    },
    {
        "field": "audience_scope",
        "type": "enum",
        "required": False,
        "description": "适用团队范围",
        "enum": [
            "全公司", "销售团队", "售前团队", "实施团队",
            "技术团队", "客服团队", "管理层", "合作伙伴",
        ],
    },
    # ── 内容形态 ─────────────────────────────────────────
    {
        "field": "contentFormat",
        "type": "enum",
        "required": False,
        "description": "文档内容形态",
        "enum": [
            "纯文本", "图文混合", "表格密集", "流程图",
            "代码示例", "视频/音频转写", "数据报告", "长文档（>50 页）",
        ],
    },
    {
        "field": "language",
        "type": "enum",
        "required": False,
        "description": "主要语言",
        "enum": ["中文", "英文", "中英混合", "其他"],
        "default": "中文",
    },
    # ── 时效性 ─────────────────────────────────────────
    {
        "field": "datePublished",
        "type": "date",
        "required": False,
        "description": "文档发布/生效日期，格式 YYYY-MM-DD（影响 γ 维度时效性衰减）",
    },
    {
        "field": "dateExpires",
        "type": "date",
        "required": False,
        "description": "文档过期日期（如政策/价格到期），格式 YYYY-MM-DD",
    },
    {
        "field": "version",
        "type": "string",
        "required": False,
        "description": "文档版本号，如 v1.2.3 / 2024Q2",
    },
    {
        "field": "documentStatus",
        "type": "enum",
        "required": False,
        "description": "文档生命周期状态（已废弃/已归档可做 filter 排除）",
        "enum": ["草稿", "审核中", "已发布", "已更新", "已归档", "已废弃"],
        "default": "已发布",
    },
    {
        "field": "reviewCycle",
        "type": "enum",
        "required": False,
        "description": "复审周期（用于知识运营/合规过期提醒）",
        "enum": ["无需复审", "季度", "半年", "年度", "两年", "按需"],
        "default": "年度",
    },
    # ── 来源与治理 ──────────────────────────────────────
    {
        "field": "source",
        "type": "enum",
        "required": False,
        "description": "文档来源（影响可信度与引用策略）",
        "enum": [
            "内部原创", "内部汇编", "客户提供", "合作伙伴",
            "外部采购", "公开资料", "监管/标准机构", "AI 生成", "其他",
        ],
        "default": "内部原创",
    },
    # ── 自由文本字段 ────────────────────────────────────
    {
        "field": "tags",
        "type": "string",
        "required": False,
        "description": "自由标签，多个用逗号分隔（辅助检索）",
    },
    {
        "field": "author",
        "type": "string",
        "required": False,
        "description": "作者/归属部门",
    },
]


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
        - 截断的 JSON（尝试补齐括号）
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

    # Step 4: JSON 被截断 — 尝试暴力补齐
    if depth > 0:
        fragment = stripped[start:]
        # 如果截断在字符串内，先关闭字符串
        if in_string:
            fragment += '"'
        # 补齐所有未关闭的括号
        # 重新扫描确定需要补什么
        close_chars = _calc_close_brackets(fragment)
        candidate = fragment + close_chars
        try:
            result = json.loads(candidate)
            if isinstance(result, dict):
                return result
        except json.JSONDecodeError:
            pass

        # 最后手段：截断到最后一个完整的逗号位置再补齐
        last_comma = fragment.rfind(",")
        if last_comma > 0:
            trimmed = fragment[:last_comma]
            # 关闭可能未闭合的字符串
            q_count = sum(1 for c in trimmed if c == '"') - sum(1 for i, c in enumerate(trimmed) if c == '"' and i > 0 and trimmed[i-1] == '\\')
            if q_count % 2 != 0:
                trimmed += '"'
            close_chars = _calc_close_brackets(trimmed)
            candidate = trimmed + close_chars
            try:
                result = json.loads(candidate)
                if isinstance(result, dict):
                    return result
            except json.JSONDecodeError:
                pass

    return None


def _calc_close_brackets(text: str) -> str:
    """扫描文本，返回需要补齐的闭合括号字符串"""
    stack: list[str] = []
    in_string = False
    escape = False
    for ch in text:
        if escape:
            escape = False
            continue
        if ch == '\\':
            escape = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == '{':
            stack.append('}')
        elif ch == '[':
            stack.append(']')
        elif ch in ('}', ']'):
            if stack and stack[-1] == ch:
                stack.pop()
    return ''.join(reversed(stack))


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
        # 切片参数（对齐 data-process ChunkingConfig 默认值）
        #   chunk_target_chars=400：句子累加到这个长度就切一个 chunk
        #   chunk_min_chars=100：尾部过短的 chunk 合并回前一个
        #   chunk_max_chars=500：超过就在句子边界强制切
        #   chunk_overlap_sentences=2：保留最后 2 个句子作为下一个 chunk 的开头
        chunk_target_chars: int = 400,
        chunk_min_chars: int = 100,
        chunk_max_chars: int = 500,
        chunk_overlap_sentences: int = 2,
        # Segment 参数
        segment_min_chars: int = 3000,
        segment_target_chars: int = 4000,
        segment_max_chars: int = 6000,
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
        # Chunk 参数（句子级切分）
        self._chunk_target = chunk_target_chars
        self._chunk_min = chunk_min_chars
        self._chunk_max = chunk_max_chars
        self._chunk_overlap_sentences = chunk_overlap_sentences
        # Segment 参数
        self._seg_min = segment_min_chars
        self._seg_target = segment_target_chars
        self._seg_max = segment_max_chars

    # ═══ IngestPipeline 协议入口 ═══

    async def run(self, task: IngestTask) -> None:
        """执行完整流水线。由 IngestWorker 调用。

        任何异常都会：
            1. 记录 ERROR 日志（含堆栈 + task/doc 上下文）
            2. 更新 document 状态为 failed（parse_error / clean_error）
            3. 更新 ingest_log 为 failed + error_message
            4. 继续抛出，由 Worker 调 queue.nack 决定重试 / 死信
        """
        payload = task.payload
        doc_id = payload.get("doc_id", "")
        if not doc_id:
            raise ValueError(f"Task {task.task_id} missing doc_id in payload")

        logger.info(
            "Pipeline start: task_id=%s doc_id=%s tenant=%s kb=%s file=%s type=%s size=%s",
            task.task_id, doc_id, task.tenant_id, task.knowledge_base_id,
            payload.get("file_name"), payload.get("file_type"),
            payload.get("file_size"),
        )

        phase = "parsing"
        try:
            KnowledgeIngestLogDAO.update_phase(task.task_id, "parsing", 5)

            # Phase 1: LKEAP 解析
            t0 = time.time()
            markdown, page_count, failed_pages = await self._phase1_parse(task, payload)
            parse_ms = int((time.time() - t0) * 1000)
            logger.info(
                "Pipeline phase=parse done: task=%s doc=%s pages=%d failed_pages=%s "
                "markdown_chars=%d elapsed=%dms",
                task.task_id, doc_id, page_count,
                failed_pages, len(markdown or ""), parse_ms,
            )
            KnowledgeIngestLogDAO.update_phase(
                task.task_id, "cleaning", 25, "parse_duration_ms", parse_ms,
            )

            # Phase 1.5: 清洗
            phase = "cleaning"
            t0 = time.time()
            cleaning: CleaningResult = self._cleaner.clean(markdown)
            clean_ms = int((time.time() - t0) * 1000)
            logger.info(
                "Pipeline phase=clean done: task=%s doc=%s original=%d cleaned=%d "
                "clean_ratio=%.3f elapsed=%dms",
                task.task_id, doc_id, cleaning.signals.original_chars,
                cleaning.signals.cleaned_chars, cleaning.signals.clean_ratio, clean_ms,
            )
            KnowledgeDocumentDAO.update_clean_status(doc_id, "cleaned")
            KnowledgeIngestLogDAO.update_phase(
                task.task_id, "tagging", 40, "clean_duration_ms", clean_ms,
            )

            # Phase 2: 候选关键词提取（本地 jieba TF-IDF）+ LLM 打标 + 质量评分
            phase = "tagging"
            t0 = time.time()

            # 2a. 本地关键词提取（不依赖 LLM，同步完成）
            candidate_keywords = self._extract_candidate_keywords(cleaning.content)
            logger.info(
                "Pipeline phase=keywords: task=%s doc=%s candidates=%d top5=%s",
                task.task_id, doc_id, len(candidate_keywords),
                candidate_keywords[:5],
            )

            # 2b. LLM 打标（把候选关键词喂给 LLM 辅助）
            metadata, summary, keywords = await self._phase2_auto_tag(
                task, cleaning.content, candidate_keywords,
            )
            quality = self._scorer.score(
                content=cleaning.content,
                cleaning_signals=cleaning.signals,
                total_pages=page_count,
                failed_pages=len(failed_pages),
            )
            logger.info(
                "Pipeline phase=tag done: task=%s doc=%s metadata_keys=%s "
                "summary_len=%d keywords=%d quality=%.3f elapsed=%dms",
                task.task_id, doc_id, list(metadata.keys()),
                len(summary or ""), len(keywords or []), quality.score,
                int((time.time() - t0) * 1000),
            )
            KnowledgeDocumentDAO.update_metadata(
                doc_id=doc_id,
                summary=summary,
                keywords=json.dumps(keywords, ensure_ascii=False),
                metadata=json.dumps(metadata, ensure_ascii=False),
                quality_score=quality.score,
                quality_signals=quality.to_json(),
                date_published=self._parse_date(metadata.get("datePublished")),
                candidate_keywords=json.dumps(candidate_keywords, ensure_ascii=False),
            )
            tag_ms = int((time.time() - t0) * 1000)
            KnowledgeIngestLogDAO.update_phase(
                task.task_id, "splitting", 55, "tagging_duration_ms", tag_ms,
            )

            # Phase 3: 两级切分（segment 只作为 section_path 来源，不落 PG）
            phase = "splitting"
            t0 = time.time()
            segments, chunks = await self._phase3_split(
                task, doc_id, cleaning, markdown,
            )
            # 把打标出来的元数据冗余到 chunk 上（加速检索过滤）
            self._apply_metadata_to_chunks(chunks, metadata, task)
            KnowledgeChunkDAO.batch_insert(chunks)
            # 聚合 section_path → toc（供文档级 BM25 召回使用）
            toc = self._build_toc(chunks, task, task_payload_file_name=payload.get("file_name", ""))
            if toc:
                try:
                    KnowledgeDocumentDAO.update_toc(doc_id, toc)
                except Exception as exc:
                    logger.warning(
                        "update_toc failed (non-fatal): doc=%s err=%s", doc_id, exc,
                    )
            KnowledgeDocumentDAO.update_chunk_status(
                doc_id, "indexed",
                chunk_count=len(chunks),
                segment_count=len(segments),
            )
            # KB 统计：切片已入 PG 就立即 +1 / +N，不等 Phase 4
            # （Phase 4 失败不影响文档在 PG 中的存在与切片检索能力）
            KnowledgeBaseDAO.update_stats(
                task.knowledge_base_id,
                doc_delta=1,
                chunk_delta=len(chunks),
            )
            split_ms = int((time.time() - t0) * 1000)
            logger.info(
                "Pipeline phase=split done: task=%s doc=%s segments=%d chunks=%d elapsed=%dms",
                task.task_id, doc_id, len(segments), len(chunks), split_ms,
            )
            KnowledgeIngestLogDAO.update_phase(
                task.task_id, "indexing", 75, "split_duration_ms", split_ms,
            )

            # Phase 4: 向量库索引（chunks + 文档摘要）
            phase = "indexing"
            t0 = time.time()
            vector_count = await self._phase4_index(task, doc_id, chunks, summary)
            index_ms = int((time.time() - t0) * 1000)
            logger.info(
                "Pipeline phase=index done: task=%s doc=%s vectors=%d elapsed=%dms",
                task.task_id, doc_id, vector_count, index_ms,
            )
            KnowledgeIngestLogDAO.update_phase(
                task.task_id, "indexing", 95, "index_duration_ms", index_ms,
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
                "Pipeline done: task=%s doc=%s segments=%d chunks=%d quality=%.2f",
                task.task_id, doc_id, len(segments), len(chunks), quality.score,
            )
        except Exception as exc:
            # 把失败信息写进 document + ingest_log 方便排查
            err_msg = f"{type(exc).__name__}: {exc}"
            logger.exception(
                "Pipeline failed: task=%s doc=%s phase=%s error=%s",
                task.task_id, doc_id, phase, err_msg,
            )
            try:
                if phase in ("parsing",):
                    KnowledgeDocumentDAO.update_parse_status(
                        doc_id, "failed", parse_error=err_msg[:2000],
                    )
                elif phase == "cleaning":
                    KnowledgeDocumentDAO.update_clean_status(
                        doc_id, "failed", clean_error=err_msg[:2000],
                    )
                elif phase in ("tagging", "splitting", "indexing"):
                    KnowledgeDocumentDAO.update_chunk_status(doc_id, "failed")
            except Exception as db_exc:
                logger.error(
                    "Pipeline failed to record state: task=%s db_error=%s",
                    task.task_id, db_exc,
                )

            try:
                KnowledgeIngestLogDAO.finish(
                    task_id=task.task_id,
                    status="failed",
                    error_message=f"[{phase}] {err_msg}",
                )
            except Exception:
                logger.exception("ingestion.py L651 异常")

            # 继续抛，让 Worker 走 nack → 退避重试
            raise

    # ═══ Phase 1: LKEAP 解析 ═══

    async def _phase1_parse(
        self, task: IngestTask, payload: dict,
    ) -> tuple[str, int, list[int]]:
        """返回 (markdown, page_count, failed_pages)"""
        doc_id = payload["doc_id"]
        file_path = payload.get("file_path", "")
        file_type = payload.get("file_type", "").lower().lstrip(".")

        if not file_path or not os.path.exists(file_path):
            err = f"文件不存在或已被删除: {file_path}"
            logger.error("Phase1 file-check failed: doc=%s %s", doc_id, err)
            KnowledgeDocumentDAO.update_parse_status(
                doc_id, "failed", parse_error=err,
            )
            raise FileNotFoundError(err)

        if not TencentLKEAPClient.is_supported(file_type):
            err = f"LKEAP 不支持的文件类型: {file_type}"
            logger.error("Phase1 type-check failed: doc=%s %s", doc_id, err)
            KnowledgeDocumentDAO.update_parse_status(
                doc_id, "failed", parse_error=err,
            )
            raise ValueError(err)

        KnowledgeDocumentDAO.update_parse_status(doc_id, "parsing")

        # 优先使用 COS URL（避免大文件 base64 传输），降级用本地文件 base64
        cos_url = payload.get("cos_url", "")
        file_url: str | None = cos_url if cos_url else None
        file_base64: str | None = None

        if not file_url:
            # 无 COS URL，走本地文件 → base64
            try:
                with open(file_path, "rb") as f:
                    data = f.read()
            except Exception as exc:
                logger.exception(
                    "Phase1 read file failed: doc=%s path=%s: %s",
                    doc_id, file_path, exc,
                )
                KnowledgeDocumentDAO.update_parse_status(
                    doc_id, "failed",
                    parse_error=f"读取文件失败: {exc}"[:2000],
                )
                raise
            file_base64 = base64.b64encode(data).decode("utf-8")
        else:
            # 有 COS URL，仍需读取文件大小用于日志
            try:
                data = open(file_path, "rb").read() if os.path.exists(file_path) else b""
            except Exception:
                data = b""

        # 小文件用 SSE（准实时），大文件用异步轮询（SSE 对 100M 以上不支持）
        file_size_for_mode = len(data) if data else payload.get("file_size", 0)
        logger.info(
            "Phase1 LKEAP calling: doc=%s type=%s size=%d mode=%s source=%s",
            doc_id, file_type, file_size_for_mode,
            "sse" if file_size_for_mode < 50 * 1024 * 1024 else "async",
            "cos_url" if file_url else "base64",
        )
        try:
            async with self._guard.acquire_lkeap_slot():
                if file_size_for_mode < 50 * 1024 * 1024:
                    result: ParseResult = await asyncio.to_thread(
                        self._lkeap.parse_document_sse,
                        file_url=file_url,
                        file_base64=file_base64,
                        file_type=file_type,
                    )
                else:
                    result = await self._lkeap.parse_document(
                        file_url=file_url,
                        file_base64=file_base64,
                        file_type=file_type,
                        poll_interval=3.0, max_wait=1800.0,
                    )
        except Exception as exc:
            logger.exception(
                "Phase1 LKEAP API error: doc=%s file=%s: %s",
                doc_id, payload.get("file_name"), exc,
            )
            KnowledgeDocumentDAO.update_parse_status(
                doc_id, "failed",
                parse_error=f"LKEAP API 调用失败: {type(exc).__name__}: {exc}"[:2000],
            )
            raise

        logger.info(
            "Phase1 LKEAP returned: doc=%s status=%s task_id=%s "
            "success_pages=%s fail_pages=%s failed_pages=%s result_url=%s",
            doc_id, result.status, result.task_id,
            result.success_page_num, result.fail_page_num,
            result.failed_pages, (result.result_url or "")[:80],
        )

        if result.status != "SUCCESS":
            err = f"LKEAP status={result.status} task_id={result.task_id}"
            logger.error("Phase1 LKEAP non-success: doc=%s %s", doc_id, err)
            KnowledgeDocumentDAO.update_parse_status(
                doc_id, "failed", parse_error=err,
            )
            raise RuntimeError(err)

        # 下载解析产物 + 保存到本地 parsed_dir
        try:
            markdown = await asyncio.to_thread(
                TencentLKEAPClient.download_and_extract_markdown, result.result_url,
            )
        except Exception as exc:
            logger.exception(
                "Phase1 download markdown failed: doc=%s url=%s: %s",
                doc_id, (result.result_url or "")[:80], exc,
            )
            KnowledgeDocumentDAO.update_parse_status(
                doc_id, "failed",
                parse_error=f"下载解析结果失败: {type(exc).__name__}: {exc}"[:2000],
            )
            raise

        if not markdown or not markdown.strip():
            err = (
                "解析结果为空（LKEAP 返回的 zip 未包含可用的文本内容）。"
                "可能原因：文档为纯图片/扫描件且 OCR 失败、文档加密、或文件损坏。"
                f" file={payload.get('file_name', '')} type={file_type}"
            )
            logger.error("Phase1 empty markdown: doc=%s %s", doc_id, err)
            KnowledgeDocumentDAO.update_parse_status(
                doc_id, "failed", parse_error=err[:2000],
            )
            raise RuntimeError(err)

        page_count = (result.success_page_num or 0) + (result.fail_page_num or 0)
        failed_pages = result.failed_pages or []

        # 存解析产物
        doc_dir = self._parsed_dir / doc_id
        doc_dir.mkdir(parents=True, exist_ok=True)
        md_path = doc_dir / "content.md"
        try:
            md_path.write_text(markdown, encoding="utf-8")
        except Exception as exc:
            logger.warning(
                "Phase1 save parsed markdown failed (non-fatal): doc=%s path=%s: %s",
                doc_id, md_path, exc,
            )
            # 保存失败不影响后续流程

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
            "Phase1 complete: doc=%s chars=%d pages=%d failed_pages=%d",
            doc_id, len(markdown), page_count, len(failed_pages),
        )
        return markdown, page_count, failed_pages

    # ═══ Phase 2: LLM 打标 ═══

    async def _phase2_auto_tag(
        self, task: IngestTask, content: str,
        candidate_keywords: list[str] | None = None,
    ) -> tuple[dict, str, list[str]]:
        """返回 (metadata, summary, keywords)

        - 有 Schema + LLM → 带受控词表的严格打标
        - 无 Schema 但有 LLM → 用通用 prompt 提取 summary + keywords（metadata 空）
        - 无 LLM → 直接降级：summary 取正文前 300 字，keywords 用候选关键词
        - user_metadata 始终覆盖自动打标结果（用户手动指定优先）
        """
        user_meta = task.payload.get("user_metadata") or {}
        doc_id = task.payload.get("doc_id", "")
        candidates = candidate_keywords or []

        if not self._llm:
            logger.info(
                "Phase2 skip LLM: task=%s doc=%s (no llm injected, use candidates as keywords)",
                task.task_id, doc_id,
            )
            summary = content[:300] if content else ""
            # 降级：直接用候选关键词前 10 个作为 keywords
            return dict(user_meta), summary, candidates[:10]

        # 取 Schema（可能为空）
        try:
            schema_row = await asyncio.to_thread(
                KnowledgeSchemaDAO.get_for_kb, task.tenant_id, task.knowledge_base_id,
            )
        except Exception as exc:
            logger.warning(
                "Phase2 fetch schema failed (will use empty schema): %s",
                exc,
            )
            schema_row = None

        schema_fields: list = []
        if schema_row and schema_row.fields:
            try:
                schema_fields = json.loads(schema_row.fields) or []
            except json.JSONDecodeError:
                logger.warning(
                    "Phase2 schema.fields not valid JSON: schema_id=%s",
                    schema_row.id,
                )
                schema_fields = []

        # 无 Schema 时使用内置默认字段（对标旧方案 preset_tag_groups.json）
        if not schema_fields:
            schema_fields = _DEFAULT_SCHEMA_FIELDS

        prompt = AUTO_TAG_PROMPT.format(
            schema_json=json.dumps(schema_fields, ensure_ascii=False, indent=2),
            candidate_keywords=", ".join(candidates) if candidates else "（无候选词）",
            document_content=content[:8000],
        )

        logger.debug(
            "Phase2 LLM call: task=%s doc=%s schema_fields=%d content_len=%d",
            task.task_id, doc_id, len(schema_fields), len(content),
        )
        try:
            resp = await self._llm.ainvoke(prompt)
            text = getattr(resp, "content", None) or str(resp)
        except Exception as exc:
            logger.exception(
                "Phase2 auto-tag LLM call failed (fallback to content prefix): task=%s doc=%s: %s",
                task.task_id, doc_id, exc,
            )
            return dict(user_meta), content[:300], []

        parsed = _extract_json_object(text)
        if parsed is None:
            logger.warning(
                "Phase2 auto-tag response not valid JSON: task=%s doc=%s raw=%s",
                task.task_id, doc_id, text[:500],
            )
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

    # 标题识别正则（对齐 data-process，扩展中文章节识别）
    _LEVEL1_TITLE = re.compile(
        r"^(#\s+.+"
        r"|第[一二三四五六七八九十百千零〇]+[章部篇].*"
        r"|[一二三四五六七八九十]+[、.]\s*.+"
        r"|\d{1,2}\.\s+.{2,})$"
    )
    _LEVEL2_TITLE = re.compile(
        r"^(#{2,3}\s+.+"
        r"|第[一二三四五六七八九十百千零〇]+[节款项].*"
        r"|[（(][一二三四五六七八九十]+[）)].*"
        r"|\d{1,2}\.\d{1,2}[.\s].*)$"
    )
    _PAGE_NUMBER_TITLE = re.compile(r"^#{1,6}\s+\d{1,5}\s*$")

    @classmethod
    def _classify_title(cls, line: str) -> int:
        """返回标题级别：0=不是标题, 1=一级, 2=二级"""
        if not line:
            return 0
        trimmed = line.strip()
        if not trimmed or len(trimmed) > 80:
            return 0
        # 页码型标题（"# 123"）不算
        if cls._PAGE_NUMBER_TITLE.match(trimmed):
            return 0
        if cls._LEVEL1_TITLE.match(trimmed):
            return 1
        if cls._LEVEL2_TITLE.match(trimmed):
            return 2
        return 0

    def _split_segments(
        self, doc_id: str, task: IngestTask, content: str,
    ) -> list[KnowledgeSegmentRow]:
        """按标题树做 Segment 切分（对齐 data-process splitToSegments）

        规则：
          1. 一级标题（H1/第X章/一、/1. ...）→ 强制分段
          2. 二级标题（H2/H3/第X节/(一)/1.1 ...）→ 当前已过 seg_min 才分段
          3. 空行：当前已过 2000 字符 → 分段
          4. 超过 seg_max：**回溯找句子边界**强制切
          5. 末尾对过短段做碎片合并（balance_segments）
        """
        now_ms = int(time.time() * 1000)

        # 先把内容按规则切成 list[str]（段文本），再包装为 KnowledgeSegmentRow
        lines = content.split("\n")
        pieces: list[str] = []     # 纯文本段
        current = ""

        for line in lines:
            level = self._classify_title(line)

            # 一级标题：强制分段
            if level == 1 and current:
                pieces.append(current)
                current = line + "\n"
                continue

            # 二级标题：超过 min_size 才分段
            if level == 2 and len(current) > self._seg_min:
                pieces.append(current)
                current = line + "\n"
                continue

            # 空行 + 累积 > 2000 字符 → 分段（保持段落边界）
            if not line.strip() and len(current) > 2000:
                pieces.append(current)
                current = ""
                continue

            current += line + "\n"

            # 超过 max_size：回溯找句子边界
            if len(current) > self._seg_max:
                split_point = self._find_last_sentence_boundary(
                    current, self._seg_max,
                )
                pieces.append(current[:split_point])
                current = current[split_point:]

        if current:
            pieces.append(current)

        # 碎片合并
        pieces = [p for p in pieces if p.strip()]
        pieces = self._balance_segments(pieces, self._seg_min)

        # 构造 KnowledgeSegmentRow（为每段推断标题 + 层级 + 路径）
        segments: list[KnowledgeSegmentRow] = []
        start_offset = 0
        current_h1 = ""
        current_h2 = ""
        for idx, seg_text in enumerate(pieces):
            seg_text_stripped = seg_text.strip()
            if not seg_text_stripped:
                continue
            # 段内第一行是否是标题？用来设置 title + section_path + heading_level
            first_line = seg_text_stripped.split("\n", 1)[0]
            level = self._classify_title(first_line)
            title = ""
            heading_level = 0
            if level == 1:
                title = first_line.lstrip("# ").strip()
                current_h1 = title
                current_h2 = ""
                heading_level = 1
            elif level == 2:
                title = first_line.lstrip("# ").strip()
                current_h2 = title
                heading_level = 2
            # 路径：h1 / h2（两级都有时拼接）
            path_parts = [p for p in [current_h1, current_h2] if p]
            section_path = " / ".join(path_parts)

            segments.append(KnowledgeSegmentRow(
                segment_id=f"seg_{uuid.uuid4().hex[:20]}",
                tenant_id=task.tenant_id,
                knowledge_base_id=task.knowledge_base_id,
                doc_id=doc_id,
                title=title,
                section_path=section_path,
                content=seg_text_stripped,
                content_tokens=self._rough_tokens(seg_text_stripped),
                segment_index=idx,
                heading_level=heading_level,
                start_offset=start_offset,
                end_offset=start_offset + len(seg_text_stripped),
                created_at=now_ms,
                updated_at=now_ms,
            ))
            start_offset += len(seg_text_stripped) + 1

        # 完全没有标题的文档也要产出至少一个段
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
        """本地切分：每个 Segment 内按**句子累加**切 Chunk（对齐 data-process）

        规则：
            1. 按 `_split_by_sentence` 拆句
            2. 累积到 `chunk_target_chars` 时切一个 chunk，但必须 >= `chunk_min_chars`
            3. 超过 `chunk_max_chars` 必须切
            4. 切出后**保留最后 N 个句子**作为下一个 chunk 的开头（语义连贯）
            5. 尾部 chunk 若 < `chunk_min_chars` 合并到前一个
        """
        chunks: list[KnowledgeChunkRow] = []
        now_ms = int(time.time() * 1000)
        global_idx = 0

        overlap_n = max(0, int(self._chunk_overlap_sentences))

        for seg in segments:
            text = seg.content
            if not text.strip():
                continue

            sentences = self._split_by_sentence(text)
            if not sentences:
                continue

            seg_chunks: list[str] = []
            current: list[str] = []
            current_len = 0
            last_sentences: list[str] = []   # 保留作 overlap 用

            def flush_chunk() -> None:
                nonlocal current, current_len, last_sentences
                if current_len == 0:
                    return
                seg_chunks.append("".join(current))
                # overlap：保留最后 N 个句子作为下一段开头
                if overlap_n > 0:
                    tail = last_sentences[-overlap_n:]
                    current = list(tail)
                    current_len = sum(len(s) for s in tail)
                    last_sentences = list(tail)
                else:
                    current = []
                    current_len = 0
                    last_sentences = []

            for s in sentences:
                slen = len(s)
                # 单句超长：先 flush 当前，再硬切这句
                if slen > self._chunk_max:
                    if current_len >= self._chunk_min:
                        flush_chunk()
                    # 在句子内按字符硬切（但尽量按边界回溯）
                    pos = 0
                    while pos < slen:
                        end = min(pos + self._chunk_max, slen)
                        if end < slen:
                            end = self._find_last_sentence_boundary(
                                s, end, max_lookback=min(200, self._chunk_max // 2),
                            )
                            if end <= pos:
                                end = pos + self._chunk_max
                        piece = s[pos:end]
                        seg_chunks.append(piece)
                        pos = end
                    current, current_len, last_sentences = [], 0, []
                    continue

                # 常规句子：累加后检查是否到阈值
                new_len = current_len + slen
                if new_len > self._chunk_max:
                    flush_chunk()
                    # flush 后保留的 overlap 可能已经填入 current
                    new_len = current_len + slen

                current.append(s)
                current_len += slen
                last_sentences.append(s)

                # 达到目标长度且 >= min：切
                if current_len >= self._chunk_target and current_len >= self._chunk_min:
                    flush_chunk()

            # 尾部：剩余内容
            if current_len > 0:
                tail_text = "".join(current)
                if tail_text.strip():
                    if len(tail_text) < self._chunk_min and seg_chunks:
                        # 尾部过短合并到前一个
                        seg_chunks[-1] = seg_chunks[-1] + tail_text
                    else:
                        seg_chunks.append(tail_text)

            # 生成 ChunkRow
            for piece in seg_chunks:
                if not piece.strip():
                    continue
                chunks.append(self._mk_chunk(
                    doc_id, task, seg, piece, global_idx, now_ms,
                ))
                global_idx += 1

            seg.chunk_count = len([c for c in seg_chunks if c.strip()])

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

    # ═══════════════════════════════════════════════════════════
    # 句子级切分工具（对齐 data-process DocumentSplitServiceImpl）
    # ═══════════════════════════════════════════════════════════

    # 句子结束符（中英混合）
    _SENTENCE_ENDS = "\u3002\uff01\uff1f\uff1b.!?;"

    @classmethod
    def _split_by_sentence(cls, text: str) -> list[str]:
        """按句号/换行切分成句子列表，保留标点。

        英文 `.` 后必须是空格/大写字母才算句子结束（避免 U.S.A. / 3.14 被切开）。
        对齐 data-process splitBySentence。
        """
        if not text:
            return []
        sentences: list[str] = []
        current: list[str] = []
        n = len(text)
        for i, c in enumerate(text):
            current.append(c)
            if c == "\n":
                sentences.append("".join(current))
                current = []
            elif c in cls._SENTENCE_ENDS:
                if c == ".":
                    # 英文句号消歧：后面是空格/大写才算
                    if i + 1 < n:
                        nxt = text[i + 1]
                        if nxt.isupper() or nxt.isspace():
                            sentences.append("".join(current))
                            current = []
                else:
                    sentences.append("".join(current))
                    current = []
        if current:
            sentences.append("".join(current))
        return sentences

    @classmethod
    def _find_last_sentence_boundary(
        cls, text: str, limit: int, max_lookback: int = 500,
    ) -> int:
        """从 limit 位置往前最多 max_lookback 字符找句子边界，返回切分位置。

        找不到则返回 limit（硬切）。对齐 data-process findLastSentenceBoundary。
        """
        if limit >= len(text):
            return len(text)
        start = max(0, limit - max_lookback)
        for i in range(limit - 1, start - 1, -1):
            c = text[i]
            if c in cls._SENTENCE_ENDS or c == "\n":
                return i + 1
        return limit

    @classmethod
    def _balance_segments(cls, segments: list[str], min_size: int) -> list[str]:
        """碎片合并：过短 segment 向相邻合并，避免产生多个几十字的孤立段。

        规则（对齐 data-process balanceSegments）：
        1. 中间过短（< min_size/2）向下合并到下一个
        2. 尾部过短（< min_size/3）向上合并到上一个
        """
        if len(segments) <= 1:
            return segments

        # 第一轮：中间过短向下合并
        balanced: list[str] = []
        pending: str | None = None
        for i, seg in enumerate(segments):
            if pending is not None:
                seg = pending + "\n" + seg
                pending = None
            is_last = (i == len(segments) - 1)
            if len(seg) < min_size // 2 and not is_last:
                pending = seg
            else:
                balanced.append(seg)

        # pending 未消化，合并到最后一个
        if pending is not None:
            if balanced:
                last = balanced.pop()
                balanced.append(last + "\n" + pending)
            else:
                balanced.append(pending)

        # 第二轮：尾部过短向上合并
        if len(balanced) >= 2:
            last = balanced[-1]
            if len(last) < min_size // 3:
                balanced.pop()
                prev = balanced.pop()
                balanced.append(prev + "\n" + last)

        return balanced

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
    def _build_toc(
        chunks: list[KnowledgeChunkRow],
        task: IngestTask | None = None,
        task_payload_file_name: str = "",
        max_chars: int = 8000,
    ) -> str:
        """构建文档目录索引（对齐 data-process directoryPath + 新方案独有章节增强）。

        Toc 同时包含两类信号，供 B2 元数据文本召回做 match：

        1. **外部路径**（对齐 data-process directoryPath 语义）：
           knowledge_base_name/dataset_name/file_name

        2. **内部章节大纲**（新方案独有增强）：
           所有切片 section_path 去重后按首次出现顺序拼接

        例如：
            产品手册库/压力仪表/罗斯蒙特3051DG产品样本.pdf
            第一章 产品介绍
            第二章 技术参数 / 2.1 量程范围
            第三章 安装指南

        对扫描件 PDF（无章节标题）仍会产生第 1 行的文件路径信号。
        """
        parts: list[str] = []
        seen_sections: set[str] = set()
        total = 0

        # ── 1. 外部路径（文件位置标识）──
        if task is not None:
            ext_parts: list[str] = []
            # KB 名
            try:
                from src.store.knowledge_dao import KnowledgeBaseDAO, KnowledgeDatasetDAO
                kb = KnowledgeBaseDAO.get_by_id(task.knowledge_base_id)
                if kb and kb.name:
                    ext_parts.append(kb.name.strip())
                # dataset 名（可选）
                if task.dataset_id:
                    ds = KnowledgeDatasetDAO.get_by_id(task.dataset_id)
                    if ds and ds.name:
                        ext_parts.append(ds.name.strip())
            except Exception as exc:
                logger.debug("Build toc: external path query failed: %s", exc)
            # 文件名
            fname = (task_payload_file_name or "").strip()
            if not fname:
                fname = (task.payload.get("file_name") or "").strip()
            if fname:
                ext_parts.append(fname)
            if ext_parts:
                ext_path = "/".join(ext_parts)
                parts.append(ext_path)
                total += len(ext_path) + 1

        # ── 2. 内部章节大纲 ──
        for c in chunks:
            path = (c.section_path or "").strip()
            if not path or path in seen_sections:
                continue
            seen_sections.add(path)
            parts.append(path)
            total += len(path) + 1
            if total >= max_chars:
                break

        return "\n".join(parts)

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

    def _extract_candidate_keywords(self, content: str) -> list[str]:
        """本地 jieba TF-IDF 提取候选关键词 Top-20

        不依赖 LLM，同步完成。作为 LLM 打标的辅助输入 + 降级兜底。
        jieba 未安装时降级为空列表（不阻塞流水线）。
        """
        if not content:
            return []
        try:
            from .keyword_extract import KeywordExtractor
            extractor = KeywordExtractor()
            return extractor.extract_combined(content, top_k=20)
        except ImportError:
            logger.warning(
                "jieba 未安装，跳过候选关键词提取。"
                "建议执行: pip install jieba"
            )
            return []
        except Exception as exc:
            logger.warning("候选关键词提取失败（非致命）: %s", exc)
            return []

    # ═══ Phase 4: 向量索引 ═══

    async def _phase4_index(
        self, task: IngestTask, doc_id: str,
        chunks: list[KnowledgeChunkRow], summary: str,
    ) -> int:
        """写 VDB（kb_chunks + kb_doc_metadata），并回填 vector_synced=1"""
        if not chunks:
            logger.info("Phase4 skip: doc=%s 无 chunks 可索引", doc_id)
            return 0

        # 1. chunk 向量化
        logger.info(
            "Phase4 embedding chunks: doc=%s count=%d avg_len=%d",
            doc_id, len(chunks),
            sum(len(c.content) for c in chunks) // len(chunks),
        )
        texts_for_embed = [c.content[:2000] for c in chunks]
        try:
            vectors = await self._embed_many(texts_for_embed)
        except Exception as exc:
            logger.exception(
                "Phase4 embedding failed: doc=%s count=%d: %s",
                doc_id, len(chunks), exc,
            )
            raise

        if not vectors or len(vectors) != len(chunks):
            err = (
                f"Embedding 返回数量不匹配: expected {len(chunks)}, got {len(vectors)}"
            )
            logger.error("Phase4 embed mismatch: doc=%s %s", doc_id, err)
            raise RuntimeError(err)

        chunk_records: list[dict] = []
        synced_ids: list[str] = []
        empty_count = 0
        for c, vec in zip(chunks, vectors):
            if not vec:
                empty_count += 1
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
                # 🆕 全文内容 — VDB 直接返回，不再回 PG 拉
                "content": c.content[:8000],
                "section_title": c.section_title,
                "chunk_index": c.chunk_index,
            })
            synced_ids.append(c.chunk_id)

        if empty_count:
            logger.warning(
                "Phase4 skipped %d chunks with empty embedding vectors (doc=%s)",
                empty_count, doc_id,
            )

        if not chunk_records:
            logger.error(
                "Phase4 no valid vectors to upsert (doc=%s, all embedding empty)",
                doc_id,
            )
            raise RuntimeError("所有切片的 embedding 向量都为空")

        # 写 VDB（分批，每批 20 条，避免单次请求过大超时）
        try:
            logger.info(
                "Phase4 VDB upsert: doc=%s records=%d dim=%d",
                doc_id, len(chunk_records),
                len(vectors[0]) if vectors and vectors[0] else 0,
            )
            batch_size = 20
            for batch_start in range(0, len(chunk_records), batch_size):
                batch = chunk_records[batch_start:batch_start + batch_size]
                await asyncio.to_thread(self._vdb.upsert_chunks, batch)
            await asyncio.to_thread(
                KnowledgeChunkDAO.mark_vector_synced,
                synced_ids,
                "lkeap/default",
                len(vectors[0]) if vectors and vectors[0] else 0,
            )
        except Exception as exc:
            logger.exception(
                "Phase4 VDB upsert_chunks failed: doc=%s count=%d: %s",
                doc_id, len(chunk_records), exc,
            )
            # 把每条 chunk 标记失败，Worker 后续可补偿
            for cid in synced_ids:
                try:
                    await asyncio.to_thread(
                        KnowledgeChunkDAO.mark_vector_failed, cid, str(exc),
                    )
                except Exception:
                    logger.exception("ingestion.py L1589 异常")
            raise

        # 2. 文档级元数据向量化 + 写入 kb_doc_metadata collection
        #    携带 summary 向量 + 5 路 BM25 文本 + γ 属性 + Schema 过滤字段
        #    失败不中断（doc_metadata 走 γ 维度，缺失只是 β/γ 维度扣分）
        try:
            if summary:
                summary_vecs = await self._embed_many([summary])
                summary_vec = summary_vecs[0] if summary_vecs else None
            else:
                summary_vec = None

            if summary_vec:
                # 回读 PG 拿最新的文档全字段（summary/keywords/toc/quality 等）
                doc_row = await asyncio.to_thread(
                    KnowledgeDocumentDAO.get_by_doc_id, doc_id,
                )
                if doc_row is None:
                    logger.warning("Phase4 doc_metadata: doc=%s not found in PG", doc_id)
                else:
                    doc_meta_record = self._build_doc_metadata_record(
                        doc_row=doc_row,
                        summary_vector=summary_vec,
                        chunks=chunks,
                    )
                    await asyncio.to_thread(
                        self._vdb.upsert_doc_metadata, [doc_meta_record],
                    )
                    logger.debug("Phase4 doc_metadata upsert ok: doc=%s", doc_id)
        except Exception as exc:
            logger.warning(
                "Phase4 doc_metadata upsert failed (non-fatal): doc=%s: %s",
                doc_id, exc,
            )

        return len(chunk_records)

    @staticmethod
    def _build_doc_metadata_record(
        doc_row,
        summary_vector: list[float],
        chunks: list[KnowledgeChunkRow],
    ) -> dict:
        """构造 kb_doc_metadata 集合的一条写入记录（文档级）。

        携带所有 β 路 BM25 文本字段 + γ 属性 + Schema 过滤字段。
        BM25 稀疏向量由 vdb_writer.upsert_doc_metadata 内部编码，这里传原文。
        """
        import json as _json
        # keywords / candidate_keywords 是 JSON 字符串，解开后拼成空格分隔的文本便于 BM25
        def _expand_json_list(text: str) -> str:
            if not text:
                return ""
            try:
                items = _json.loads(text)
                if isinstance(items, list):
                    return " ".join(str(x) for x in items if x)
            except Exception:
                logger.exception("_expand_json_list 异常")
            return text

        keywords_text = _expand_json_list(doc_row.keywords or "")
        candidate_text = _expand_json_list(doc_row.candidate_keywords or "")

        # 从切片样本取 Schema 字段（所有 chunk 被 _apply_metadata_to_chunks 冗余成相同值）
        sample = chunks[0] if chunks else None
        doc_category = sample.doc_category if sample else ""
        industry = sample.industry if sample else ""
        business_stage = sample.business_stage if sample else ""
        target_audience = sample.target_audience if sample else ""
        product_service = sample.product_service if sample else ""

        return {
            "id": doc_row.doc_id,
            # 摘要向量（VDB 要求字段名必须是 "vector"）
            "vector": summary_vector,
            # BM25 文本字段（vdb_writer 内部编码）
            "title": doc_row.title or "",
            "summary": doc_row.summary or "",
            "keywords": keywords_text,
            "candidate_keywords": candidate_text,
            "toc": doc_row.toc or "",
            # 租户/业务字段
            "tenant_id": str(doc_row.tenant_id),
            "knowledge_base_id": str(doc_row.knowledge_base_id),
            "dataset_id": str(doc_row.dataset_id),
            "doc_category": doc_category,
            "industry": industry,
            "business_stage": business_stage,
            "target_audience": target_audience,
            "product_service": product_service,
            "status": "active",
            # γ 维度属性（quality_score 因 VDB FilterIndex 不支持 Double，×10000 存 Uint64）
            "quality_score_x10k": int(round(float(doc_row.quality_score or 0.0) * 10000)),
            "date_published": int(doc_row.date_published or 0),
            "created_at": int(doc_row.created_at or 0),
            "search_hit_count": int(doc_row.search_hit_count or 0),
        }

    async def _embed_many(self, texts: list[str]) -> list[list[float]]:
        """批量向量化 — 优先用注入的 embedding_fn，否则用 LKEAP

        LKEAP GetEmbedding 单次只接受 1 个 Input，所以只能逐条调用。
        使用有界并发（2）平衡吞吐和连接池限制（max=10）。
        不走全局 guard 信号量（那个只保护重量级的 parse 操作）。
        """
        if not texts:
            return []
        if self._embedding_fn is not None:
            try:
                if asyncio.iscoroutinefunction(self._embedding_fn):
                    return [await self._embedding_fn(t) for t in texts]
                return await asyncio.to_thread(
                    lambda: [self._embedding_fn(t) for t in texts]
                )
            except Exception as exc:
                logger.exception(
                    "_embed_many via embedding_fn failed (count=%d): %s",
                    len(texts), exc,
                )
                raise

        # 默认走 LKEAP — 逐条调用 + 有界并发（2 并发，避免打满连接池）
        concurrency = 2
        sem = asyncio.Semaphore(concurrency)
        results: list[list[float]] = [None] * len(texts)  # type: ignore[assignment]

        async def _one(idx: int, text: str):
            async with sem:
                try:
                    vecs = await asyncio.to_thread(
                        self._lkeap.get_embedding, [text],
                    )
                    results[idx] = vecs[0] if vecs and vecs[0] else []
                except Exception as exc:
                    logger.exception(
                        "_embed_many via LKEAP failed at index %d/%d (text_len=%d): %s",
                        idx, len(texts), len(text), exc,
                    )
                    raise

        logger.info(
            "_embed_many start: count=%d concurrency=%d avg_len=%d",
            len(texts), concurrency,
            sum(len(t) for t in texts) // max(1, len(texts)),
        )
        await asyncio.gather(*(_one(i, t) for i, t in enumerate(texts)))
        return results
