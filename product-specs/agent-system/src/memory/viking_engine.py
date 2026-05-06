"""VikingMemoryEngine — 基于 OpenViking 范式的长期记忆引擎

四路并行提取架构：
  - profile: 用户画像（PG 存储，OVERWRITE）
  - preferences: 用户偏好（向量库，按 slug 合并）
  - agent_rules: Agent 行为准则（PG 存储，LLM 融合）
  - entities: 实体与事实（向量库，按 merge_key 合并）

核心能力：
  P0: 4类分类 + L0/L1/L2三层 + profile增量合并 + preferences按slug合并
  P1: BM25混合检索 + 意图分析多路查询 + active_count热度统计
  P2: 记忆遗忘 + 会话压缩触发
  P3: 目录递归检索 + 反思修正

存储: 腾讯向量库（tcvectordb SDK 直连）
LLM: 豆包（去重/合并/意图分析）
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import uuid4

from ..middleware.memory import (
    MemoryEngine, MemoryDimension, MemoryItem,
    MemoryRetrievalResult, MemoryExtractionResult,
)

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════
# 记忆分类体系
# ═══════════════════════════════════════════════════════════

class MemoryCategory(str, Enum):
    PROFILE = "profile"
    PREFERENCES = "preferences"
    ENTITIES = "entities"
    AGENT_RULES = "agent_rules"

# 可合并的类别（新记忆可以与旧记忆合并）
_MERGEABLE_CATEGORIES = {
    MemoryCategory.PROFILE, MemoryCategory.PREFERENCES,
    MemoryCategory.ENTITIES, MemoryCategory.AGENT_RULES,
}

# 4类 → 4维度映射
_CATEGORY_TO_DIMENSION = {
    MemoryCategory.PROFILE: MemoryDimension.USER_PROFILE,
    MemoryCategory.PREFERENCES: MemoryDimension.USER_PROFILE,
    MemoryCategory.ENTITIES: MemoryDimension.CUSTOMER_CONTEXT,
    MemoryCategory.AGENT_RULES: MemoryDimension.USER_PROFILE,
}

# 遗忘策略：各类别保留天数
_RETENTION_DAYS = {
    "profile": 9999, "preferences": 9999, "agent_rules": 9999,  # 不遗忘
    "entities": 180,
}

# 三阶段淡化参数
_STALE_GRACE_DAYS = 30        # 过期后进入 stale 的观察期（天）
_ARCHIVE_GRACE_DAYS = 30      # stale 后进入 archived 的观察期（天）

# agent_rules/profile 精炼阈值
_AGENT_RULES_MAX_CHARS = 300
_PROFILE_MAX_CHARS = 200

# tools/skills 统计衰减
_TOOL_DECAY_FACTOR = 0.7      # 每月衰减系数

# 反思：只对 entities 类别触发会话反思
_REFLECTION_CATEGORIES = {"entities"}

# 反思：关系类型到 action 的映射（规则映射，不靠 LLM）
_RELATION_TO_ACTION = {
    "identical":     "discard_new",
    "contradiction": "archive_old",
    "evolution":     "update_old",
    "unrelated":     "keep_both",
}

# 反思：相似度阈值（向量召回后过滤）
_REFLECTION_SIMILARITY_THRESHOLD = 0.7


# ═══════════════════════════════════════════════════════════
# 反思触发冷却管理
# ═══════════════════════════════════════════════════════════

class ReflectionCooldown:
    """反思触发冷却 — 防止高频触发导致 LLM 调用爆炸"""

    _COOLDOWNS = {
        "session": 5,           # 会话反思：5 秒
        "failure": 60,          # 失败反思：60 秒
        "correction": 30,       # 用户纠正反思：30 秒
        "global": 6 * 3600,     # 全局反思：6 小时
    }

    _last_triggered: dict[str, float] = {}  # "{type}:{key}" -> timestamp

    @classmethod
    def can_trigger(cls, reflection_type: str, key: str) -> bool:
        """key 是 thread_id 或 user_id"""
        k = f"{reflection_type}:{key}"
        now = time.time()
        last = cls._last_triggered.get(k, 0)
        cooldown = cls._COOLDOWNS.get(reflection_type, 60)
        if now - last < cooldown:
            return False
        cls._last_triggered[k] = now
        return True


# ═══════════════════════════════════════════════════════════
# 数据结构
# ═══════════════════════════════════════════════════════════

@dataclass
class MemoryRecord:
    id: str = ""
    category: str = "entities"
    abstract: str = ""          # L0
    overview: str = ""          # L1（结构化 Markdown）
    content: str = ""           # L2
    merge_key: str = ""
    user_id: str = ""
    parent_entity: str = ""
    score: float = 0.0
    active_count: int = 0
    created_at: str = ""
    updated_at: str = ""


# ═══════════════════════════════════════════════════════════
# 提示词（去重/意图/合并/聚合/反思 — 提取已迁移到 extraction 模块）
# ═══════════════════════════════════════════════════════════

DEDUP_PROMPT = """判断如何更新长期记忆。

候选记忆:
  摘要: {candidate_abstract}
  内容: {candidate_content}

已有相似记忆:
{existing_memories}

## 候选级别决策
- skip: 候选冗余（重复/改写/过于模糊），不存储，不修改已有记忆
- create: 候选是有效的新信息，独立存储
- merge: 候选和某条已有记忆是同一主题，应合并（提供合并后的内容）
- delete: 候选使某条已有记忆完全失效

## 关键删除边界（非破坏性优先）
- 部分冲突（某些陈述冲突，其他仍有效）→ 用 merge，不要 delete
- 仅在整个已有记忆完全过时/失效时才 delete
- 绝不能因为主题/方面不匹配而删除（不同方面的记忆互不影响）
- 不确定时选择 skip 或 merge，而非 delete

## 决策优先级
1. 候选冗余 → skip
2. 同主题更新/部分矛盾 → merge（生成合并后内容）
3. 明显独立的新信息 → create
4. 已有记忆完全失效 → delete（极少使用）

返回 JSON:
{{"decision":"skip|create|merge|delete","target_id":"目标ID（merge/delete时必填）","reason":"原因","merged_abstract":"合并后摘要（merge时必填）","merged_overview":"合并后概览（merge时必填）","merged_content":"合并后完整内容（merge时必填，保留旧记忆中仍有效的信息+候选的新信息）"}}"""

AGENT_RULES_MERGE_PROMPT = """将以下用户对 Agent 的角色定义和行为准则整合为一段连贯的描述。

已有行为准则:
{existing_rules}

新增定义:
{new_definitions}

要求:
1. 合并已有准则和新增定义，保留所有有效的角色定义和行为准则
2. 如果新增定义和已有准则矛盾，以新增为准
3. 用第二人称描述（"你是..."、"你要..."）
4. 控制在 300 字以内

直接输出合并后的行为准则文本，不要其他内容。"""

PROFILE_MERGE_PROMPT = """将以下用户身份信息整合为一段连贯的用户画像描述。

已有用户画像:
{existing_profile}

新增信息:
{new_info}

要求:
1. 合并已有画像和新增信息，保留所有有效的身份信息
2. 如果新增信息和已有画像矛盾，以新增为准（如职位变更）
3. 用第三人称描述（"用户是..."）
4. 控制在 200 字以内

直接输出合并后的用户画像文本，不要其他内容。"""

AGGREGATE_L1_PROMPT = """将以下多条记忆聚合为一个结构化 Markdown 目录。

目录路径: {directory_path}
记忆条目:
{l2_list}

要求:
1. 用 ## 标题分组，相关信息归到同一标题下
2. 用 - 列表列出具体信息
3. 保留所有有效信息，不要遗漏
4. 如果有矛盾信息，保留最新的

直接输出 Markdown，不要包裹在代码块中。"""

AGGREGATE_L0_PROMPT = """将以下结构化目录压缩为一句话摘要（不超过100字）。

目录路径: {directory_path}
目录内容:
{l1_content}

直接输出一句话摘要，不要其他内容。"""

REFINE_PROMPT = """压缩以下{type_name}到{max_chars}字以内。
保留所有关键信息（身份、职责、约束、流程、禁止），去掉冗余修饰语。
用简洁短句，不要套话。

原文:
{content}

直接输出压缩后的文本。"""

# ── 反思：关系判断 prompt（4 选 1 简单分类任务）──
REFLECTION_RELATION_PROMPT = """判断新记忆与已有记忆的关系。

新记忆: {new}
已有记忆: {old}

关系类型只有 4 种：
- identical: 完全相同的信息（字面重复）
- contradiction: 直接矛盾（相同主体，不同结论，如"张伟是对接人" vs "李娜是对接人"）
- evolution: 信息演进（旧信息过时或被新信息补充，但不完全矛盾，如"方案阶段" → "谈判阶段"）
- unrelated: 不相关（检索召回有误，不是同一主题）

只返回一个词（identical/contradiction/evolution/unrelated），不要解释。"""

# ── 反思：evolution 场景的合并 prompt ──
EVOLUTION_MERGE_PROMPT = """将旧记忆和新记忆合并为一条完整的最新状态描述。

旧记忆: {old_content}
新记忆: {new_content}

要求：
1. 保留旧记忆中仍然有效的信息
2. 用新记忆的信息覆盖已变化的部分
3. 不超过 200 字

直接输出合并后的完整内容。"""


# ═══════════════════════════════════════════════════════════
# 预过滤 + 工具统计提取
# ═══════════════════════════════════════════════════════════

_SKIP_PATTERNS = frozenset(
    "你好 您好 hi hello hey 在吗 好的 ok 是的 对 嗯 收到 明白 了解 "
    "谢谢 感谢 thanks 再见 拜拜 bye".split()
)


def _should_extract(messages: list, min_turns: int = 1, min_tokens: int = 50) -> bool:
    """预过滤 + P2 会话压缩触发阈值"""
    last_human = ""
    last_ai = ""
    has_tool_error = False
    has_tool_success = False
    turn_count = 0
    total_chars = 0

    for msg in reversed(messages):
        msg_type = getattr(msg, "type", "")
        content = getattr(msg, "content", "")
        if not isinstance(content, str):
            content = str(content) if content else ""
        total_chars += len(content)
        if msg_type == "human":
            if not last_human:
                last_human = content.strip()
            turn_count += 1
        elif msg_type == "ai" and not last_ai and content.strip():
            last_ai = content.strip()
        elif msg_type == "tool":
            status = getattr(msg, "status", "success")
            if status == "error":
                has_tool_error = True
            else:
                has_tool_success = True
        if last_human and last_ai:
            break

    if last_human and last_human.lower() in _SKIP_PATTERNS:
        return False

    # AI 回复太短时的处理：
    # 放宽到 2 个字符（只过滤完全空回复和单字回复如"嗯"）
    # 让提示词来决定是否值得提取，而不是在预过滤阶段硬判断
    if not last_ai or len(last_ai) < 2:
        return False
    if has_tool_error and not has_tool_success:
        return False
    return True


def _convert_messages(messages: list) -> str:
    """将消息列表转换为提取用的文本格式。
    
    标注最后一轮（最后一条 human + 最后一条 ai）为"本轮对话"，
    之前的消息标注为"历史上下文"，让 LLM 只提取本轮新增的信息。
    """
    # 找到最后一轮的边界
    last_human_idx = -1
    for i in range(len(messages) - 1, -1, -1):
        if getattr(messages[i], "type", "") == "human":
            last_human_idx = i
            break

    recent = messages[-10:]
    # 计算 recent 中最后一轮的起始位置
    last_round_start = max(0, last_human_idx - (len(messages) - len(recent)))

    lines = []
    in_last_round = False
    for idx, msg in enumerate(recent):
        msg_type = getattr(msg, "type", "")
        content = getattr(msg, "content", "")
        if not isinstance(content, str) or not content.strip():
            continue

        # 判断是否进入最后一轮
        if idx >= last_round_start and not in_last_round:
            if lines:
                lines.append("")
            lines.append("--- 以下是本轮对话（只提取本轮新增的信息）---")
            in_last_round = True

        if msg_type == "human":
            lines.append(f"[用户] {content}")
        elif msg_type == "ai" and content.strip():
            lines.append(f"[助手] {content}")
        elif msg_type == "tool":
            name = getattr(msg, "name", "tool")
            lines.append(f"[工具:{name}] {content[:300]}")
    return "\n".join(lines)


def _extract_query_reply(messages: list) -> tuple[str, str]:
    """从消息列表中提取最后一轮的用户问题和大模型回复"""
    user_query = ""
    agent_reply = ""
    for msg in reversed(messages):
        msg_type = getattr(msg, "type", "")
        content = getattr(msg, "content", "")
        if not isinstance(content, str):
            content = str(content) if content else ""
        if msg_type == "ai" and content.strip() and not agent_reply:
            agent_reply = content.strip()[:2000]
        elif msg_type == "human" and content.strip() and not user_query:
            user_query = content.strip()[:1000]
        if user_query and agent_reply:
            break
    return user_query, agent_reply


# ═══════════════════════════════════════════════════════════
# VectorStore — 腾讯向量库直连（支持 BM25 混合检索）
# ═══════════════════════════════════════════════════════════

class VectorStore:
    """腾讯向量库操作封装 — 支持 filter index + BM25 稀疏向量"""

    def __init__(self, url: str, key: str, username: str = "root",
                 database_name: str = "viking_memory",
                 collection_name: str = "memories",
                 embedding_dims: int = 2560):
        import tcvectordb
        self._client = tcvectordb.VectorDBClient(url=url, username=username, key=key, timeout=30)
        self._db_name = database_name
        self._coll_name = collection_name
        self._dims = embedding_dims
        self._db = None
        self._coll = None
        self._bm25 = None  # BM25 编码器（延迟初始化）

    def _ensure_collection(self):
        if self._coll is not None:
            return
        try:
            self._db = self._client.create_database(self._db_name)
        except Exception:
            self._db = self._client.database(self._db_name)

        # 尝试获取已有 collection
        try:
            self._coll = self._db.describe_collection(self._coll_name)
            return
        except Exception:
            pass

        # 尝试创建新 collection
        try:
            from tcvectordb.model.index import Index, VectorIndex, FilterIndex, HNSWParams, SparseIndex
            from tcvectordb.model.enum import FieldType, IndexType, MetricType

            index = Index(
                FilterIndex(name="id", field_type=FieldType.String, index_type=IndexType.PRIMARY_KEY),
                VectorIndex(name="vector", dimension=self._dims, index_type=IndexType.HNSW,
                            metric_type=MetricType.COSINE, params=HNSWParams(m=16, efconstruction=200)),
                SparseIndex(name="sparse_vector"),
                FilterIndex(name="user_id", field_type=FieldType.String, index_type=IndexType.FILTER),
                FilterIndex(name="category", field_type=FieldType.String, index_type=IndexType.FILTER),
                FilterIndex(name="parent_entity", field_type=FieldType.String, index_type=IndexType.FILTER),
                FilterIndex(name="parent_uri", field_type=FieldType.String, index_type=IndexType.FILTER),
                FilterIndex(name="is_leaf", field_type=FieldType.String, index_type=IndexType.FILTER),
                FilterIndex(name="status", field_type=FieldType.String, index_type=IndexType.FILTER),
            )
            self._coll = self._db.create_collection(
                name=self._coll_name, shard=1, replicas=1,
                description="Viking Memory Engine (with BM25)", index=index,
            )
            logger.info("Created collection: %s/%s", self._db_name, self._coll_name)
        except Exception as e:
            # collection 已存在但 describe 失败 → 直接获取
            logger.warning("Create collection failed (%s), getting existing", e)
            self._coll = self._db.collection(self._coll_name)

    def _get_bm25(self):
        """延迟初始化 BM25 编码器"""
        if self._bm25 is None:
            try:
                from tcvdb_text.encoder import BM25Encoder
                self._bm25 = BM25Encoder.default()
            except Exception as e:
                logger.warning("BM25Encoder init failed: %s", e)
        return self._bm25

    def upsert(self, records: list[dict]):
        self._ensure_collection()
        if not records:
            return
        # 为每条记录生成 BM25 稀疏向量
        bm25 = self._get_bm25()
        if bm25:
            for rec in records:
                text = rec.get("abstract", "") or rec.get("text", "")
                if text and "sparse_vector" not in rec:
                    try:
                        sparse = bm25.encode_texts([text])
                        if sparse and sparse[0]:
                            rec["sparse_vector"] = sparse[0]
                    except Exception:
                        pass
        # 尝试写入（如果 collection 不支持 sparse_vector，去掉该字段重试）
        try:
            self._coll.upsert(records)
        except Exception as e:
            if "sparse_vector" in str(e) or "fieldName" in str(e):
                for rec in records:
                    rec.pop("sparse_vector", None)
                self._coll.upsert(records)
            else:
                raise

    def search(self, vector: list[float], top_k: int = 5,
               filter_expr: str | None = None) -> list[dict]:
        """纯向量检索"""
        self._ensure_collection()
        from tcvectordb.model.document import Filter
        params = {"vectors": [vector], "limit": top_k}
        if filter_expr:
            params["filter"] = Filter(filter_expr)
        results = self._coll.search(**params)
        return self._parse_results(results)

    def hybrid_search(self, vector: list[float], query_text: str,
                      top_k: int = 5, filter_expr: str | None = None,
                      dense_weight: float = 0.3, sparse_weight: float = 0.7) -> list[dict]:
        """P1: BM25 混合检索（稠密 + 稀疏）"""
        self._ensure_collection()
        bm25 = self._get_bm25()
        if not bm25:
            return self.search(vector, top_k, filter_expr)

        try:
            from tcvectordb.model.document import AnnSearch, KeywordSearch, WeightedRerank, Filter

            sparse_vec = bm25.encode_queries([query_text])
            if not sparse_vec or not sparse_vec[0]:
                return self.search(vector, top_k, filter_expr)

            ann = AnnSearch(field_name="vector", data=vector)
            kw = KeywordSearch(field_name="sparse_vector", data=sparse_vec[0])
            rerank = WeightedRerank(
                field_list=["vector", "sparse_vector"],
                weight=[dense_weight, sparse_weight],
            )

            kwargs: dict[str, Any] = {
                "ann": [ann],
                "match": [kw],
                "rerank": rerank,
                "limit": top_k,
            }
            if filter_expr:
                kwargs["filter"] = Filter(filter_expr)

            results = self._coll.hybrid_search(**kwargs)
            return self._parse_results(results)
        except Exception as e:
            logger.warning("Hybrid search failed: %s, fallback to vector search", e)
            return self.search(vector, top_k, filter_expr)

    def update_active_count(self, doc_id: str):
        """P1: 热度 +1"""
        self._ensure_collection()
        try:
            self._coll.update(
                filter=None,
                document_ids=[doc_id],
                update_fields={"active_count": 1},  # 增量更新
            )
        except Exception as e:
            logger.debug("Update active_count failed for %s: %s", doc_id, e)

    def delete(self, ids: list[str]):
        self._ensure_collection()
        if ids:
            self._coll.delete(document_ids=ids)

    def query_by_filter(self, filter_expr: str, limit: int = 100) -> list[dict]:
        self._ensure_collection()
        from tcvectordb.model.document import Filter
        result = self._coll.query(filter=Filter(filter_expr), limit=limit)
        docs = []
        for doc in (result.get("documents", []) if isinstance(result, dict) else result):
            if isinstance(doc, dict):
                docs.append(doc)
        return docs

    @staticmethod
    def _parse_results(results) -> list[dict]:
        parsed = []
        for doc_list in results:
            for doc in doc_list:
                if isinstance(doc, dict):
                    parsed.append(doc)
                else:
                    d = {"id": doc.id, "score": doc.score}
                    if hasattr(doc, "fields") and doc.fields:
                        d.update(doc.fields)
                    parsed.append(d)
        return parsed


# ═══════════════════════════════════════════════════════════
# VikingMemoryEngine — 主引擎（完整版）
# ═══════════════════════════════════════════════════════════

class VikingMemoryEngine(MemoryEngine):
    """基于 OpenViking 范式的长期记忆引擎（完整版）

    存储分层:
      PG（精确查询）: profile, agent_rules
      向量库（语义检索）: entities, events, cases, patterns, preferences
    """

    # 走 PG 存储的类别（不需要向量检索）
    _PG_CATEGORIES = {"profile", "agent_rules"}
    # 走向量库的类别（需要语义检索）
    _VDB_CATEGORIES = {"entities", "preferences"}

    # ── URI 构建 ──

    @staticmethod
    def _build_uri(category: str, merge_key: str = "", parent_entity: str = "") -> str:
        """构建 viking:// URI"""
        from .viking_fs import _CATEGORY_SPACE
        space = _CATEGORY_SPACE.get(category, "user")
        parts = [space, "memories", category]
        if parent_entity:
            parts.append(parent_entity)
        if merge_key:
            leaf = merge_key.split("/")[-1] if "/" in merge_key else merge_key
            if leaf and leaf != parent_entity:
                parts.append(leaf)
        return "viking://" + "/".join(p for p in parts if p)

    @staticmethod
    def _build_parent_uri(category: str, parent_entity: str = "") -> str:
        """构建父目录 URI（带尾部斜杠）"""
        from .viking_fs import _CATEGORY_SPACE
        space = _CATEGORY_SPACE.get(category, "user")
        parts = [space, "memories", category]
        if parent_entity:
            parts.append(parent_entity)
        return "viking://" + "/".join(parts) + "/"

    async def _ensure_directory_node(self, category: str, parent_entity: str,
                                     user_id: str, query_vec: list[float] | None = None):
        """确保目录节点存在于向量库中（is_leaf=false）

        对齐 apps-agent：目录节点的 L0/L1 由系统 LLM 聚合生成。
          L0（abstract）：从所有叶子 content 聚合为一句话摘要
          L1（overview）：从所有叶子 content 聚合为结构化 Markdown 导航
        每次叶子变更后重新聚合。
        """
        import asyncio
        if not parent_entity:
            return

        dir_uri = self._build_parent_uri(category, parent_entity)
        dir_id = f"dir_{hashlib.md5(f'{user_id}:{dir_uri}'.encode()).hexdigest()[:16]}"

        try:
            # 收集该目录下所有叶子的 content
            filter_expr = f'user_id = "{user_id}" and parent_entity = "{parent_entity}" and category = "{category}" and is_leaf = "true"'
            leaves = await asyncio.to_thread(self._vdb.query_by_filter, filter_expr, 50)
            if not leaves:
                return

            dir_path = f"{category}/{parent_entity}"
            leaf_contents = [l.get("content", "") or l.get("abstract", "") for l in leaves if l.get("content") or l.get("abstract")]
            if not leaf_contents:
                return

            # LLM 聚合生成 L0 和 L1（对齐 apps-agent）
            if self._llm:
                # 生成 L1（结构化 Markdown 导航）
                l2_text = "\n".join(f"- {c[:200]}" for c in leaf_contents)
                try:
                    prompt_l1 = AGGREGATE_L1_PROMPT.format(directory_path=dir_path, l2_list=l2_text)
                    result_l1 = await self._llm.ainvoke(prompt_l1)
                    l1 = (getattr(result_l1, "content", None) or str(result_l1)).strip()
                except Exception as e:
                    logger.debug("Directory L1 generation failed: %s", e)
                    l1 = "\n".join(f"- {c[:80]}" for c in leaf_contents)

                # 生成 L0（一句话聚合摘要）
                try:
                    prompt_l0 = AGGREGATE_L0_PROMPT.format(directory_path=dir_path, l1_content=l1)
                    result_l0 = await self._llm.ainvoke(prompt_l0)
                    l0 = (getattr(result_l0, "content", None) or str(result_l0)).strip()
                except Exception as e:
                    logger.debug("Directory L0 generation failed: %s", e)
                    l0 = f"{parent_entity}: " + "; ".join(c[:30] for c in leaf_contents[:5])
            else:
                # 无 LLM 时 fallback 到简单拼接
                l1 = "\n".join(f"- {c[:80]}" for c in leaf_contents)
                l0 = f"{parent_entity}: " + "; ".join(c[:30] for c in leaf_contents[:5])

            if len(l0) > 200:
                l0 = l0[:200]

            # 向量化目录 L0（用于检索匹配）
            try:
                dir_vec = await asyncio.to_thread(self._emb.embed_query, l0)
            except Exception:
                if query_vec is not None:
                    dir_vec = query_vec
                else:
                    return

            parent_of_dir = self._build_parent_uri(category)

            await asyncio.to_thread(self._vdb.upsert, [{
                "id": dir_id, "vector": dir_vec,
                "text": l0, "abstract": l0,
                "overview": l1,  # ← L1 结构化导航
                "content": "",
                "category": category, "merge_key": parent_entity,
                "parent_entity": "", "user_id": user_id,
                "uri": dir_uri, "parent_uri": parent_of_dir,
                "is_leaf": "false",
                "status": "active",
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }])
            logger.debug("Directory node upserted (LLM aggregated): %s (%d leaves)", dir_uri, len(leaves))
        except Exception as e:
            logger.debug("Directory node creation failed: %s", e)

    def __init__(
        self,
        vdb_url: str = "http://10.60.2.17",
        vdb_key: str = "",
        vdb_username: str = "root",
        database_name: str = "viking_memory",
        collection_name: str = "memories",
        llm: Any = None,
        embedding_model: Any = None,
        agent_rules_threshold: int = 5,
    ) -> None:
        self._llm = llm
        self._emb = embedding_model or self._default_embedding()
        self._vdb = VectorStore(
            url=vdb_url, key=vdb_key, username=vdb_username,
            database_name=database_name, collection_name=collection_name,
        )
        self._agent_rules_threshold = agent_rules_threshold
        self._new_memory_count: dict[str, int] = {}
        self._agent_rules_cache: dict[str, str] = {}
        self._use_pg = True  # PG 是必须的，profile/agent_rules 只存 PG

        # 初始化 PG 表（统一使用 ai_agent_memory）
        try:
            from ..store.memory_dao import MemoryDAO
            MemoryDAO.ensure_table()
            self._pg = MemoryDAO
            logger.info("PG memory store initialized (ai_agent_memory — all categories)")
        except Exception as e:
            logger.error("PG memory store init FAILED: %s — profile/agent_rules will not work!", e)
            self._pg = None

    @staticmethod
    def _default_embedding():
        from langchain_openai import OpenAIEmbeddings
        api_key = os.environ.get("DOUBAO_API_KEY", "651621e7-e495-4728-93ef-ed380e9ddcd1")
        return OpenAIEmbeddings(
            model="doubao-embedding-text-240715", api_key=api_key,
            base_url="https://ark.cn-beijing.volces.com/api/v3/",
            check_embedding_ctx_length=False,
        )

    # ── MemoryEngine 接口 ──

    async def rewrite_query(self, messages: list, current_query: str,
                            tenant_id: str | None = None) -> str:
        """查询改写 — 仅在多轮对话时调用 LLM 解析代词"""
        human_count = sum(1 for m in messages if getattr(m, "type", "") == "human")
        if human_count <= 1 or not self._llm:
            return current_query
        try:
            ctx = []
            for msg in reversed(messages[-10:]):
                mt = getattr(msg, "type", "")
                c = getattr(msg, "content", "")
                if mt in ("human", "ai") and isinstance(c, str) and c.strip():
                    ctx.insert(0, f"[{mt}] {c[:200]}")
            prompt = (
                "根据对话上下文改写查询，提取实体名和业务概念，解析代词，输出不超过50字。\n\n"
                f"上下文:\n" + "\n".join(ctx[-6:]) + f"\n\n当前: {current_query}\n改写:"
            )
            result = await self._llm.ainvoke(prompt)
            r = (getattr(result, "content", None) or str(result)).strip()
            if 0 < len(r) < 100:
                return r
        except Exception as e:
            logger.warning("Query rewrite failed: %s", e)
        return current_query

    async def retrieve(
        self, query: str,
        dimensions: list[MemoryDimension] | None = None,
        tenant_id: str | None = None,
        user_id: str | None = None,
        top_k: int = 5,
    ) -> MemoryRetrievalResult:
        """检索记忆 — 全局向量搜索 + 递归目录展开 + 收敛检测"""
        import asyncio
        import heapq
        uid = user_id or "default"
        ALPHA = 0.5  # 分数传播权重
        MAX_CONVERGENCE = 3
        GLOBAL_TOPK = 10

        try:
            query_vec = await asyncio.to_thread(self._emb.embed_query, query)
        except Exception as e:
            logger.error("Embedding failed: %s", e)
            return MemoryRetrievalResult(query_used=query)

        all_results: list[dict] = []
        seen_ids: set[str] = set()

        # ── 全局向量搜索 ──
        global_filter = f'user_id = "{uid}" and category != "_aggregate"'
        try:
            global_results = await asyncio.to_thread(
                self._vdb.hybrid_search, query_vec, query, GLOBAL_TOPK, global_filter,
            )
        except Exception:
            try:
                global_results = await asyncio.to_thread(
                    self._vdb.search, query_vec, GLOBAL_TOPK, global_filter,
                )
            except Exception:
                global_results = []

        for r in global_results:
            doc_id = r.get("id", "")
            if doc_id and doc_id not in seen_ids:
                seen_ids.add(doc_id)
                all_results.append(r)

        # ── Step 2: 分离目录节点和叶子节点 ──
        collected: list[dict] = []  # 最终收集的叶子
        dir_queue: list[tuple[float, str]] = []  # (-score, parent_uri) 优先队列

        for r in all_results:
            score = float(r.get("score", 0))

            if r.get("is_leaf") == "false":
                # 目录节点 → 入队等待递归展开
                dir_uri = r.get("uri", "") or r.get("parent_uri", "")
                if dir_uri:
                    heapq.heappush(dir_queue, (-score, dir_uri))
            else:
                # 叶子节点 → 直接收集
                r["_final_score"] = score
                collected.append(r)

        # ── Step 3: 递归展开目录 ──
        prev_topk_ids: list[str] = []
        unchanged_rounds = 0

        while dir_queue and unchanged_rounds < MAX_CONVERGENCE:
            neg_score, current_uri = heapq.heappop(dir_queue)
            parent_score = -neg_score

            # 搜索该目录下的子节点（用 parent_uri 前缀过滤）
            try:
                child_filter = f'user_id = "{uid}" and parent_uri = "{current_uri}"'
                children = await asyncio.to_thread(
                    self._vdb.search, query_vec, 10, child_filter,
                )
            except Exception:
                children = []

            for child in children:
                child_id = child.get("id", "")
                if child_id in seen_ids:
                    continue
                seen_ids.add(child_id)

                child_score = float(child.get("score", 0))
                # 分数传播: α × 自身分数 + (1-α) × 父目录分数
                final_score = ALPHA * child_score + (1 - ALPHA) * parent_score

                if child.get("is_leaf") == "false":
                    # 子目录 → 继续递归
                    child_uri = child.get("uri", "")
                    if child_uri and final_score > 0.3:
                        heapq.heappush(dir_queue, (-final_score, child_uri))
                else:
                    # 叶子 → 收集
                    child["_final_score"] = final_score
                    collected.append(child)

            # 收敛检测: Top-K 是否变化
            current_topk = sorted(collected, key=lambda x: x.get("_final_score", 0), reverse=True)[:top_k]
            current_topk_ids = [c.get("id", "") for c in current_topk]
            if current_topk_ids == prev_topk_ids:
                unchanged_rounds += 1
            else:
                unchanged_rounds = 0
                prev_topk_ids = current_topk_ids

        # ── Step 4: 构建返回结果（返回 L0 摘要，Agent 按需加载 L1/L2）──
        collected.sort(key=lambda x: x.get("_final_score", 0), reverse=True)
        items: list[MemoryItem] = []
        hit_ids: list[tuple[str, str]] = []  # (doc_id, status) 用于异步更新 PG

        for r in collected[:top_k]:
            status = r.get("status", "active")  # 兼容旧数据
            is_directory = r.get("is_leaf") == "false"

            # 目录节点 → 返回 L0（聚合摘要）
            # 叶子节点 → 返回 abstract（L0 摘要）
            abstract = r.get("abstract", "") or r.get("text", "")
            if not abstract:
                continue

            cat_str = r.get("category", "entities")
            dim = _CATEGORY_TO_DIMENSION.get(
                MemoryCategory(cat_str) if cat_str in [c.value for c in MemoryCategory] else MemoryCategory.ENTITIES,
                MemoryDimension.DOMAIN_KNOWLEDGE,
            )

            score = float(r.get("_final_score", r.get("score", 0.5)))

            # stale 降权 + 标注
            if status == "stale":
                score *= 0.5
                abstract = f"[可能过时] {abstract}"

            uri = r.get("uri", "")
            node_type = "directory" if is_directory else "leaf"
            items.append(MemoryItem(
                dimension=dim,
                content=abstract,  # 返回 L0 摘要（目录和叶子都返回 abstract）
                confidence=score,
                metadata={"id": r.get("id", ""), "category": cat_str,
                          "uri": uri,
                          "type": node_type,  # directory 或 leaf
                          "has_overview": is_directory,  # 目录有 L1 可加载
                          "has_content": not is_directory,  # 叶子有 content 可加载
                          "status": status,
                          "source_type": r.get("source_type", "insight")},
            ))

            doc_id = r.get("id", "")
            if doc_id:
                hit_ids.append((doc_id, status))

            doc_id = r.get("id", "")
            if doc_id:
                hit_ids.append((doc_id, status))

        # 异步批量更新 PG（last_accessed_at + active_count + 复活）
        if hit_ids:
            asyncio.create_task(self._update_access_batch(hit_ids))

        items.sort(key=lambda x: x.confidence, reverse=True)
        return MemoryRetrievalResult(items=items[:top_k], query_used=query)

    async def extract_and_update(
        self, messages: list, thread_id: str,
        tenant_id: str | None = None,
        user_id: str | None = None,
    ) -> MemoryExtractionResult:
        """提取记忆 — 四路并行提取 + 语义去重 + 分类合并"""
        import asyncio
        uid = user_id or "default"
        tid = tenant_id or "default"
        extracted: list[MemoryItem] = []

        # 预过滤（含 P2 会话压缩触发阈值）
        if not _should_extract(messages):
            return MemoryExtractionResult(source_thread_id=thread_id)

        # 提取用户问题和大模型回复（用于 PG 记录来源）
        user_query, agent_reply = _extract_query_reply(messages)

        # ── 四路并行提取（P0 优化核心）──
        from src.memory.extraction import MemoryExtractor
        extractor = MemoryExtractor(llm=self._llm, state_provider=self)
        extraction_result = await extractor.extract_all(
            messages=messages,
            tenant_id=tid,
            user_id=uid,
            thread_id=thread_id,
            output_language="auto",
        )

        # 转换为候选列表（兼容下游 _dedup_and_store）
        candidates = []
        for item in extraction_result.items:
            cand = {
                "category": self._map_dimension_to_category(item.dimension),
                "abstract": item.abstract,
                "overview": item.overview,
                "content": item.content,
                "merge_key": item.merge_key,
                "parent_entity": item.parent_entity,
                "source_type": item.source_type,
            }
            candidates.append(cand)

        if not candidates:
            return MemoryExtractionResult(source_thread_id=thread_id)

        # 语义去重 + 分类合并策略 + 写入
        for cand in candidates:
            record = await self._dedup_and_store(cand, uid, thread_id)
            if record:
                dim = _CATEGORY_TO_DIMENSION.get(
                    MemoryCategory(record.category) if record.category in [c.value for c in MemoryCategory] else MemoryCategory.ENTITIES,
                    MemoryDimension.DOMAIN_KNOWLEDGE,
                )
                extracted.append(MemoryItem(
                    dimension=dim, content=record.abstract,
                    metadata={"id": record.id, "category": record.category,
                              "full_content": record.content,
                              "overview": record.overview},
                ))
                # 同步写入 PG（用于前端查询展示，不影响运行态）
                asyncio.create_task(self._sync_to_pg(record, uid, thread_id, cand, user_query, agent_reply))

        # 会话结束反思（异步，不阻塞提取流程）
        if extracted:
            asyncio.create_task(self._safe_reflect_on_session(extracted, uid))

        # ── Agent Rules 角色定义更新 ──
        has_rules = any(item.metadata.get("category") == "agent_rules" for item in extracted)
        if has_rules:
            asyncio.create_task(self._update_agent_rules(uid))

        logger.info("VikingEngine: extracted %d memories from thread %s (tenant=%s)", len(extracted), thread_id, tid)
        return MemoryExtractionResult(items=extracted, source_thread_id=thread_id)

    @staticmethod
    def _map_dimension_to_category(dimension: str) -> str:
        """将新提取器的 dimension 映射为存储 category"""
        if dimension == "profile":
            return "profile"
        elif dimension == "preferences":
            return "preferences"
        elif dimension == "agent_rules":
            return "agent_rules"
        elif dimension == "entities":
            return "entities"
        return "entities"

    # ── StateProvider 协议实现（供 MemoryExtractor 调用）──

    async def get_profile(self, tenant_id: str, user_id: str) -> str:
        """获取已有 profile 文本"""
        import asyncio
        if self._pg:
            try:
                row = await asyncio.to_thread(self._pg.get_profile, user_id)
                if row and row.content:
                    return row.content
            except Exception:
                pass
        return ""

    async def get_agent_rules(self, tenant_id: str, user_id: str) -> str:
        """获取已有 agent_rules 文本"""
        import asyncio
        rules = self._agent_rules_cache.get(user_id, "")
        if not rules and self._pg:
            try:
                row = await asyncio.to_thread(self._pg.get_agent_rules, user_id)
                if row and row.content:
                    rules = row.content
            except Exception:
                pass
        return rules

    async def get_entity_index(self, tenant_id: str, user_id: str) -> str:
        """获取已有实体索引摘要"""
        import asyncio
        try:
            filter_expr = f'user_id = "{user_id}" and category = "entities"'
            results = await asyncio.to_thread(self._vdb.query_by_filter, filter_expr, 20)
            if results:
                lines = [f"- [{r.get('merge_key', '')}] {r.get('abstract', '')[:60]}" for r in results]
                return "\n".join(lines)
        except Exception:
            pass
        return ""

    async def _safe_reflect_on_session(self, items: list[MemoryItem], user_id: str):
        """安全包装 reflect_on_session，异常不影响主流程"""
        try:
            stats = await self.reflect_on_session(items, user_id)
            if stats.get("conflicts", 0) > 0:
                logger.info("Session reflection: %s", stats)
        except Exception as e:
            logger.warning("Session reflection failed: %s", e)

    async def _sync_to_pg(self, record: MemoryRecord, user_id: str, thread_id: str,
                         candidate: dict, user_query: str = "", agent_reply: str = "",
                         tenant_id: str = ""):
        """同步写入 PG — 仅用于前端查询展示，不影响运行态"""
        import asyncio
        try:
            from src.store.pg_pool import get_conn
            from src.core.context import get_context
            now = int(time.time() * 1000)
            source_type = candidate.get("source_type", "insight")
            parent_entity = candidate.get("parent_entity", record.parent_entity or "")

            # 从全局上下文获取 tenant_id
            if not tenant_id:
                ctx = get_context()
                tenant_id = str(ctx.tenant_id)

            def _do_pg_write():
                with get_conn() as conn:
                    with conn.cursor() as cur:
                        if record.merge_key:
                            cur.execute("""
                                INSERT INTO ai_agent_memory
                                    (memory_id, tenant_id, user_id, category, source_type,
                                     abstract, overview, content, merge_key, parent_entity,
                                     thread_id, status, vector_synced, vector_id,
                                     user_query, agent_reply,
                                     created_at, updated_at)
                                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                                ON CONFLICT (tenant_id, user_id, category, merge_key)
                                    WHERE merge_key != '' AND delete_flg = 0
                                DO UPDATE SET
                                    abstract = EXCLUDED.abstract,
                                    overview = EXCLUDED.overview,
                                    content = EXCLUDED.content,
                                    source_type = EXCLUDED.source_type,
                                    parent_entity = EXCLUDED.parent_entity,
                                    thread_id = EXCLUDED.thread_id,
                                    vector_id = EXCLUDED.vector_id,
                                    user_query = EXCLUDED.user_query,
                                    agent_reply = EXCLUDED.agent_reply,
                                    updated_at = EXCLUDED.updated_at
                            """, (record.id, tenant_id, user_id, record.category, source_type,
                                  record.abstract, record.overview, record.content,
                                  record.merge_key, parent_entity,
                                  thread_id, "active", 1, record.id,
                                  user_query, agent_reply,
                                  now, now))
                        else:
                            cur.execute("""
                                INSERT INTO ai_agent_memory
                                    (memory_id, tenant_id, user_id, category, source_type,
                                     abstract, overview, content, merge_key, parent_entity,
                                     thread_id, status, vector_synced, vector_id,
                                     user_query, agent_reply,
                                     created_at, updated_at)
                                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                            """, (record.id, tenant_id, user_id, record.category, source_type,
                                  record.abstract, record.overview, record.content,
                                  record.merge_key, parent_entity,
                                  thread_id, "active", 1, record.id,
                                  user_query, agent_reply,
                                  now, now))

            await asyncio.to_thread(_do_pg_write)
            logger.debug("PG synced: [%s] %s", record.category, record.abstract[:50])
        except Exception as e:
            logger.debug("PG sync failed (non-critical): %s", e)


    # ── PG 存储（profile/agent_rules/tools/skills）──

    async def _store_to_pg(self, category, merge_key, abstract, overview, content,
                           user_id, parent_entity, thread_id) -> MemoryRecord | None:
        """将 PG 类别的记忆写入 PostgreSQL

        agent_rules/profile: 每用户只有一条，新增内容和已有记录 LLM 合并
        tools/skills: 按 merge_key upsert
        """
        import asyncio

        # ── agent_rules 和 profile: 读取已有 → LLM 合并 → 写回一条 ──
        if category in ("agent_rules", "profile"):
            return await self._merge_single_record(category, content, user_id, thread_id)

        # ── tools/skills: 按 merge_key upsert ──
        try:
            from src.core.context import get_context
            ctx = get_context()
            row_id = await asyncio.to_thread(
                self._pg.upsert,
                user_id=user_id, category=category, merge_key=merge_key or category,
                abstract=abstract, overview=overview, content=content,
                metadata={"parent_entity": parent_entity, "thread_id": thread_id},
                tenant_id=ctx.tenant_id,
            )
            logger.debug("PG stored: [%s] %s (id=%s)", category, abstract[:50], row_id)
            return MemoryRecord(
                id=str(row_id), category=category, abstract=abstract,
                overview=overview, content=content, merge_key=merge_key,
                user_id=user_id, parent_entity=parent_entity,
            )
        except Exception as e:
            logger.error("PG store failed: %s", e)
            return None

    async def _merge_single_record(self, category: str, new_content: str,
                                   user_id: str, thread_id: str) -> MemoryRecord | None:
        """agent_rules/profile 合并逻辑：读取已有 → LLM 合并 → 写回一条

        每个用户的 agent_rules 和 profile 各只有一条记录。
        每次提取到新的增量片段时，和已有记录合并成一条完整描述。
        PG 不可用时 fallback 到内存缓存。
        """
        import asyncio
        mk = category  # merge_key 固定为 "agent_rules" 或 "profile"

        # 1. 读取已有记录（PG）
        existing_content = ""
        if category == "agent_rules":
            existing_content = self._agent_rules_cache.get(user_id, "")
        if not existing_content and self._pg:
            try:
                if category == "agent_rules":
                    row = await asyncio.to_thread(self._pg.get_agent_rules, user_id)
                else:
                    row = await asyncio.to_thread(self._pg.get_profile, user_id)
                if row and row.content:
                    existing_content = row.content
            except Exception:
                pass

        # 2. LLM 合并（已有 + 新增 → 一条完整描述）
        if self._llm and existing_content:
            if category == "agent_rules":
                prompt = AGENT_RULES_MERGE_PROMPT.format(existing_rules=existing_content, new_definitions=new_content)
            else:
                prompt = PROFILE_MERGE_PROMPT.format(existing_profile=existing_content, new_info=new_content)
            try:
                result = await self._llm.ainvoke(prompt)
                merged = (getattr(result, "content", None) or str(result)).strip()
            except Exception as e:
                logger.warning("LLM merge %s failed: %s, fallback to append", category, e)
                merged = (existing_content + "\n" + new_content).strip()
        elif existing_content:
            merged = (existing_content + "\n" + new_content).strip()
        else:
            merged = new_content.strip()

        # 3. 写回 PG（一条记录）
        abstract = f"{'Agent行为准则' if category == 'agent_rules' else '用户身份'}: {merged[:100]}"
        row_id = ""
        if self._pg:
            try:
                from src.core.context import get_context
                ctx = get_context()
                row_id = str(await asyncio.to_thread(
                    self._pg.upsert,
                    user_id=user_id, category=category, merge_key=mk,
                    abstract=abstract, overview="", content=merged,
                    metadata={"thread_id": thread_id},
                    tenant_id=ctx.tenant_id,
                ))
                logger.debug("PG merged [%s]: %s", category, merged[:80])
            except Exception as e:
                logger.error("PG merge %s failed: %s", category, e)
                return None
        else:
            logger.error("PG not available, cannot store %s", category)
            return None

        # 4. 更新 agent_rules 缓存
        if category == "agent_rules":
            self._agent_rules_cache[user_id] = merged

        # 5. 异步精炼检查（超长自动压缩）
        asyncio.create_task(self._refine_if_needed(category, user_id))

        return MemoryRecord(
            id=str(row_id) if row_id else "",
            category=category, abstract=abstract,
            overview="", content=merged, merge_key=mk,
            user_id=user_id, parent_entity="",
        )

    # ── 语义去重 + 分类合并策略 ──

    async def _dedup_and_store(self, candidate: dict, user_id: str, thread_id: str) -> MemoryRecord | None:
        import asyncio

        abstract = candidate.get("abstract", "")
        overview = candidate.get("overview", "")
        content = candidate.get("content", abstract)
        category = candidate.get("category", "entities")
        merge_key = candidate.get("merge_key", "")
        parent_entity = candidate.get("parent_entity", "")
        source_type = candidate.get("source_type", "insight")

        if not abstract or len(abstract) < 5:
            return None

        now = datetime.now(timezone.utc).isoformat()

        # ── PG 路由：profile/agent_rules → PG 存储 ──
        if self._use_pg and self._pg and category in self._PG_CATEGORIES:
            return await self._store_to_pg(category, merge_key, abstract, overview, content,
                                           user_id, parent_entity, thread_id)

        # ── 以下走向量库（entities / preferences）──

        # 向量化
        try:
            vec = await asyncio.to_thread(self._emb.embed_query, abstract)
        except Exception as e:
            logger.error("Embedding failed: %s", e)
            return None

        # ── 分类合并策略（仅向量库类别）──

        # 有 merge_key → 按 key 合并
        if merge_key:
            return await self._merge_by_key(vec, category, merge_key, abstract, overview, content,
                                            user_id, parent_entity, thread_id, now, source_type)

        # 无 merge_key → 语义去重后独立存储
        return await self._dedup_create(vec, category, merge_key, abstract, overview, content,
                                        user_id, parent_entity, thread_id, now, source_type)

    async def _merge_profile(self, vec, abstract, overview, content, user_id, thread_id, now) -> MemoryRecord | None:
        """P0: profile 始终合并"""
        import asyncio
        merged_content = content
        try:
            filter_expr = f'user_id = "{user_id}" and category = "profile"'
            existing = await asyncio.to_thread(self._vdb.search, vec, 1, filter_expr)
            if existing:
                old_id = existing[0].get("id", "")
                old_content = existing[0].get("content", "")
                if old_content:
                    merged_content = old_content + "\n" + content
                if old_id:
                    await asyncio.to_thread(self._vdb.delete, [old_id])
        except Exception as e:
            logger.debug("Profile merge search failed: %s", e)

        record_id = str(uuid4())
        try:
            await asyncio.to_thread(self._vdb.upsert, [{
                "id": record_id, "vector": vec, "text": abstract,
                "abstract": abstract, "overview": overview, "content": merged_content,
                "category": "profile", "merge_key": "profile",
                "parent_entity": "", "user_id": user_id,
                "thread_id": thread_id,
                "created_at": now, "updated_at": now,
            }])
        except Exception as e:
            logger.error("Profile merge write failed: %s", e)
            return None
        return MemoryRecord(id=record_id, category="profile", abstract=abstract,
                            overview=overview, content=merged_content, user_id=user_id,
                            created_at=now, updated_at=now)

    async def _merge_by_key(self, vec, category, merge_key, abstract, overview, content,
                            user_id, parent_entity, thread_id, now, source_type="insight") -> MemoryRecord | None:
        """P0: 按 merge_key 合并 — 同 key 时 LLM 生成合并内容（保留旧记忆中仍有效的信息）"""
        import asyncio
        try:
            filter_expr = f'user_id = "{user_id}" and category = "{category}"'
            existing = await asyncio.to_thread(self._vdb.search, vec, 3, filter_expr)
            # 查找同 merge_key 的已有记忆
            for e in existing:
                if e.get("merge_key") == merge_key and e.get("score", 0) > 0.8:
                    old_id = e.get("id", "")
                    old_content = e.get("content", "")
                    old_abstract = e.get("abstract", e.get("text", ""))
                    if old_id:
                        # 如果有 LLM，用 LLM 生成合并内容（保留旧记忆中仍有效的信息）
                        if self._llm and old_content and old_content != content:
                            try:
                                decision, _, m_abs, m_ovw, m_cont = await self._llm_dedup(
                                    abstract, content, [e])
                                if decision == "skip":
                                    return None
                                if decision == "merge":
                                    abstract = m_abs
                                    overview = m_ovw or overview
                                    content = m_cont
                            except Exception:
                                pass  # LLM 失败时 fallback 到直接替换
                        await asyncio.to_thread(self._vdb.delete, [old_id])
                        logger.debug("Merged %s: %s", category, merge_key)
                    break
        except Exception as e:
            logger.debug("Merge search failed: %s", e)

        record_id = str(uuid4())
        leaf_uri = self._build_uri(category, merge_key, parent_entity)
        parent_uri = self._build_parent_uri(category, parent_entity)
        try:
            await asyncio.to_thread(self._vdb.upsert, [{
                "id": record_id, "vector": vec, "text": abstract,
                "abstract": abstract, "overview": overview, "content": content,
                "category": category, "merge_key": merge_key,
                "parent_entity": parent_entity, "user_id": user_id,
                "uri": leaf_uri, "parent_uri": parent_uri, "is_leaf": "true",
                "thread_id": thread_id, "source_type": source_type,
                "status": "active",
                "created_at": now, "updated_at": now,
            }])
            # 异步更新目录节点
            if parent_entity:
                asyncio.create_task(self._ensure_directory_node(category, parent_entity, user_id))
        except Exception as e:
            logger.error("Merge write failed: %s", e)
            return None
        return MemoryRecord(id=record_id, category=category, abstract=abstract,
                            overview=overview, content=content, merge_key=merge_key,
                            user_id=user_id, parent_entity=parent_entity,
                            created_at=now, updated_at=now)

    async def _dedup_create(self, vec, category, merge_key, abstract, overview, content,
                            user_id, parent_entity, thread_id, now, source_type="insight") -> MemoryRecord | None:
        """events/cases: 语义去重 — 向量预筛 + LLM 精判"""
        import asyncio
        try:
            filter_expr = f'user_id = "{user_id}" and category = "{category}"'
            existing = await asyncio.to_thread(self._vdb.search, vec, 3, filter_expr)
        except Exception:
            existing = []

        decision = "create"
        if existing and existing[0].get("score", 0) > 0.9 and self._llm:
            try:
                decision, target_id, merged_abs, merged_ovw, merged_cont = await self._llm_dedup(abstract, content, existing)
                if decision == "skip":
                    return None
                if decision == "merge" and target_id:
                    await asyncio.to_thread(self._vdb.delete, [target_id])
                    abstract = merged_abs
                    overview = merged_ovw or overview
                    content = merged_cont
                if decision == "delete" and target_id:
                    await asyncio.to_thread(self._vdb.delete, [target_id])
            except Exception:
                pass

        record_id = str(uuid4())
        leaf_uri = self._build_uri(category, merge_key, parent_entity)
        parent_uri = self._build_parent_uri(category, parent_entity)
        try:
            await asyncio.to_thread(self._vdb.upsert, [{
                "id": record_id, "vector": vec, "text": abstract,
                "abstract": abstract, "overview": overview, "content": content,
                "category": category, "merge_key": merge_key,
                "parent_entity": parent_entity, "user_id": user_id,
                "uri": leaf_uri, "parent_uri": parent_uri, "is_leaf": "true",
                "thread_id": thread_id, "source_type": source_type,
                "status": "active",
                "created_at": now, "updated_at": now,
            }])
            if parent_entity:
                asyncio.create_task(self._ensure_directory_node(category, parent_entity, user_id))
        except Exception as e:
            logger.error("Dedup create write failed: %s", e)
            return None
        return MemoryRecord(id=record_id, category=category, abstract=abstract,
                            overview=overview, content=content, merge_key=merge_key,
                            user_id=user_id, parent_entity=parent_entity,
                            created_at=now, updated_at=now)

    async def _llm_dedup(self, abstract, content, existing) -> tuple[str, str, str, str, str]:
        """去重判断 — 返回 (decision, target_id, merged_abstract, merged_overview, merged_content)"""
        existing_text = "\n".join(
            f"  ID: {e.get('id','')}\n  摘要: {e.get('abstract', e.get('text',''))}\n  内容: {e.get('content','')[:200]}\n  相似度: {e.get('score',0):.3f}"
            for e in existing[:3]
        )
        prompt = DEDUP_PROMPT.format(candidate_abstract=abstract, candidate_content=content,
                                     existing_memories=existing_text)
        result = await self._llm.ainvoke(prompt)
        text = (getattr(result, "content", None) or str(result)).strip()
        try:
            if "{" in text:
                d = json.loads(text[text.index("{"):text.rindex("}") + 1])
                return (d.get("decision", "create"), d.get("target_id", ""),
                        d.get("merged_abstract", abstract),
                        d.get("merged_overview", ""),
                        d.get("merged_content", content))
        except Exception:
            pass
        return "create", "", abstract, "", content


    # ── Agent Rules — 用户对 Agent 的行为准则 ──

    async def _update_agent_rules(self, user_id: str):
        """当提取到 agent_rules 类记忆时，确保缓存同步

        合并逻辑和 PG 写入已在 _merge_single_record 中完成（tenant_id=1）。
        此方法仅确保内存缓存是最新的。
        """
        import asyncio
        try:
            # 从 PG 读取最新值刷新缓存
            if self._use_pg and self._pg:
                row = await asyncio.to_thread(self._pg.get_agent_rules, user_id)
                if row and row.content:
                    self._agent_rules_cache[user_id] = row.content
                    logger.info("Agent rules cache refreshed for user %s: %s", user_id, row.content[:80])
        except Exception as e:
            logger.error("Agent rules cache refresh failed: %s", e)

    def get_agent_rules_text(self, user_id: str) -> str:
        """获取 Agent 行为准则 — 优先内存缓存 → PG → 空"""
        # 内存缓存
        rules = self._agent_rules_cache.get(user_id, "")
        if rules:
            return f"<agent_rules>\n{rules}\n</agent_rules>"
        # PG 查询
        if self._use_pg and self._pg:
            try:
                row = self._pg.get_agent_rules(user_id)
                if row and row.content:
                    self._agent_rules_cache[user_id] = row.content
                    return f"<agent_rules>\n{row.content}\n</agent_rules>"
            except Exception as e:
                logger.debug("PG get_agent_rules failed: %s", e)
        return ""

    # ── P2: 记忆遗忘（三阶段淡化 + 精炼 + 统计衰减）──

    async def _update_access_batch(self, hits: list[tuple[str, str]]):
        """批量更新 PG 的 last_accessed_at + active_count，stale/archived 复活

        Args:
            hits: [(doc_id, status), ...] 本次检索命中的记忆
        """
        import asyncio
        revive_ids = [doc_id for doc_id, status in hits if status in ("stale", "archived")]
        normal_ids = [doc_id for doc_id, status in hits if status not in ("stale", "archived")]

        try:
            from src.store.pg_pool import get_conn
            now_ms = int(time.time() * 1000)

            def _do():
                with get_conn() as conn:
                    with conn.cursor() as cur:
                        if normal_ids:
                            for doc_id in normal_ids:
                                cur.execute("""
                                    UPDATE ai_agent_memory
                                    SET last_accessed_at = %s, active_count = active_count + 1
                                    WHERE (vector_id = %s OR memory_id = %s) AND delete_flg = 0
                                """, (now_ms, doc_id, doc_id))
                        if revive_ids:
                            for doc_id in revive_ids:
                                cur.execute("""
                                    UPDATE ai_agent_memory
                                    SET status = 'active', last_accessed_at = %s,
                                        active_count = active_count + 1, updated_at = %s
                                    WHERE (vector_id = %s OR memory_id = %s) AND delete_flg = 0
                                """, (now_ms, now_ms, doc_id, doc_id))

            await asyncio.to_thread(_do)

            # 复活的记忆同步向量库 status
            for doc_id in revive_ids:
                asyncio.create_task(self._sync_status_to_vdb(doc_id, "active"))
                logger.info("Memory revived: %s → active", doc_id)
        except Exception as e:
            logger.debug("Update access batch failed: %s", e)

    async def _sync_status_to_vdb(self, doc_id: str, new_status: str):
        """同步单条记忆的 status 到向量库"""
        import asyncio
        try:
            docs = await asyncio.to_thread(self._vdb.query_by_filter, f'id = "{doc_id}"', 1)
            if docs:
                doc = docs[0]
                doc["status"] = new_status
                doc["updated_at"] = datetime.now(timezone.utc).isoformat()
                await asyncio.to_thread(self._vdb.upsert, [doc])
        except Exception as e:
            logger.debug("Sync status to VDB failed for %s: %s", doc_id, e)

    async def _refine_if_needed(self, category: str, user_id: str):
        """agent_rules/profile 超长时自动精炼"""
        import asyncio
        max_chars = _AGENT_RULES_MAX_CHARS if category == "agent_rules" else _PROFILE_MAX_CHARS
        type_name = "Agent行为准则" if category == "agent_rules" else "用户画像（Profile）"

        # 读取当前内容
        content = ""
        if category == "agent_rules":
            content = self._agent_rules_cache.get(user_id, "")
            if not content and self._pg:
                try:
                    row = await asyncio.to_thread(self._pg.get_agent_rules, user_id)
                    content = row.content if row else ""
                except Exception:
                    pass
        else:
            if self._pg:
                try:
                    row = await asyncio.to_thread(self._pg.get_profile, user_id)
                    content = row.content if row else ""
                except Exception:
                    pass

        if not content or len(content) <= max_chars or not self._llm:
            return

        # LLM 精炼
        try:
            prompt = REFINE_PROMPT.format(type_name=type_name, max_chars=max_chars, content=content)
            result = await self._llm.ainvoke(prompt)
            refined = (getattr(result, "content", None) or str(result)).strip()

            if len(refined) >= len(content):
                return  # LLM 反而写更长了，放弃

            abstract = f"{'Agent行为准则' if category == 'agent_rules' else '用户身份'}: {refined[:100]}"
            if self._pg:
                await asyncio.to_thread(
                    self._pg.upsert,
                    user_id=user_id, category=category, merge_key=category,
                    abstract=abstract, content=refined,
                )
            if category == "agent_rules":
                self._agent_rules_cache[user_id] = refined

            logger.info("Refined %s for %s: %d → %d chars", category, user_id, len(content), len(refined))
        except Exception as e:
            logger.warning("Refine %s failed: %s", category, e)

    async def decay_memories(self, user_id: str | None = None) -> dict:
        """三阶段淡化 — 建议每天执行一次

        从 PG 读取 last_accessed_at 判断状态转换，然后同步 status 到向量库。

        状态转换：
          active   → stale:    过期 + 30天无检索
          stale    → archived: 持续 30 天无检索
          archived → deleted:  持续 30 天无检索

        Returns:
            {"to_stale": N, "to_archived": N, "deleted": N}
        """
        import asyncio
        stats = {"to_stale": 0, "to_archived": 0, "deleted": 0}
        now_ms = int(time.time() * 1000)
        day_ms = 86400 * 1000

        try:
            from src.store.pg_pool import get_conn
        except Exception:
            logger.warning("PG not available, skip decay")
            return stats

        for category, retention_days in _RETENTION_DAYS.items():
            if retention_days >= 9999:
                continue

            try:
                def _query_category():
                    with get_conn() as conn:
                        with conn.cursor() as cur:
                            sql = """
                                SELECT memory_id, vector_id, status, created_at,
                                       COALESCE(NULLIF(last_accessed_at, 0), updated_at, created_at) as last_access
                                FROM ai_agent_memory
                                WHERE category = %s AND delete_flg = 0
                            """
                            params = [category]
                            if user_id:
                                sql += " AND user_id = %s"
                                params.append(user_id)
                            cur.execute(sql, params)
                            cols = [d[0] for d in cur.description]
                            return [dict(zip(cols, row)) for row in cur.fetchall()]

                rows = await asyncio.to_thread(_query_category)
            except Exception as e:
                logger.warning("Decay query failed for %s: %s", category, e)
                continue

            to_stale = []
            to_archive = []
            to_delete = []

            for row in rows:
                vid = row.get("vector_id") or row.get("memory_id", "")
                status = row.get("status", "active")
                created_at = row.get("created_at", 0) or 0
                last_access = row.get("last_access", 0) or created_at

                age_days = (now_ms - created_at) / day_ms if created_at else 0
                days_since_access = (now_ms - last_access) / day_ms if last_access else 9999

                if status == "active":
                    if age_days > retention_days and days_since_access > _STALE_GRACE_DAYS:
                        to_stale.append(vid)
                elif status == "stale":
                    if days_since_access > _ARCHIVE_GRACE_DAYS:
                        to_archive.append(vid)
                elif status == "archived":
                    if days_since_access > _ARCHIVE_GRACE_DAYS:
                        to_delete.append(vid)

            # 批量更新
            if to_stale:
                await self._batch_update_status_pg(to_stale, "stale")
                for vid in to_stale:
                    asyncio.create_task(self._sync_status_to_vdb(vid, "stale"))
                stats["to_stale"] += len(to_stale)
                logger.info("Decay: %d %s → stale", len(to_stale), category)

            if to_archive:
                await self._batch_update_status_pg(to_archive, "archived")
                for vid in to_archive:
                    asyncio.create_task(self._sync_status_to_vdb(vid, "archived"))
                stats["to_archived"] += len(to_archive)
                logger.info("Decay: %d %s → archived", len(to_archive), category)

            if to_delete:
                # 向量库物理删除
                try:
                    await asyncio.to_thread(self._vdb.delete, to_delete)
                except Exception as e:
                    logger.warning("VDB delete failed: %s", e)
                # PG 软删除
                await self._batch_update_status_pg(to_delete, "deleted", soft_delete=True)
                stats["deleted"] += len(to_delete)
                logger.info("Decay: %d %s deleted", len(to_delete), category)

        return stats

    async def _batch_update_status_pg(self, doc_ids: list[str], new_status: str,
                                      soft_delete: bool = False):
        """批量更新 PG 中的 status"""
        import asyncio
        try:
            from src.store.pg_pool import get_conn
            now_ms = int(time.time() * 1000)

            def _do():
                with get_conn() as conn:
                    with conn.cursor() as cur:
                        for doc_id in doc_ids:
                            if soft_delete:
                                cur.execute("""
                                    UPDATE ai_agent_memory
                                    SET status = %s, delete_flg = 1, updated_at = %s
                                    WHERE (vector_id = %s OR memory_id = %s)
                                """, (new_status, now_ms, doc_id, doc_id))
                            else:
                                cur.execute("""
                                    UPDATE ai_agent_memory
                                    SET status = %s, updated_at = %s
                                    WHERE (vector_id = %s OR memory_id = %s) AND delete_flg = 0
                                """, (new_status, now_ms, doc_id, doc_id))

            await asyncio.to_thread(_do)
        except Exception as e:
            logger.debug("Batch update status PG failed: %s", e)

    async def cleanup_expired(self, user_id: str | None = None) -> int:
        """兼容旧接口 — 内部调用 decay_memories"""
        stats = await self.decay_memories(user_id)
        return stats.get("deleted", 0)

    # ── P3: 反思修正 ──

    async def reflect_on_failure(self, messages: list, error: str, user_id: str) -> None:
        """P3: 失败驱动反思 — 任务失败后检查是否因错误记忆导致"""
        if not self._llm:
            return
        try:
            import asyncio
            conversation = _convert_messages(messages)
            vec = await asyncio.to_thread(self._emb.embed_query, conversation[:200])
            filter_expr = f'user_id = "{user_id}" and status != "archived"'
            related = await asyncio.to_thread(self._vdb.search, vec, 5, filter_expr)

            if not related:
                return

            prompt = (
                f"任务失败，错误: {error}\n\n"
                f"相关记忆:\n" + "\n".join(f"- [ID:{m.get('id','')}] [{m.get('category')}] {m.get('abstract','')}" for m in related) +
                "\n\n这些记忆中是否有错误或过时的信息导致了失败？"
                "如果有，返回 JSON: {\"problematic_ids\": [\"id1\"], \"reason\": \"原因\"}\n"
                "如果没有，返回: {\"problematic_ids\": []}"
            )
            result = await self._llm.ainvoke(prompt)
            text = (getattr(result, "content", None) or str(result)).strip()
            if "{" in text:
                data = json.loads(text[text.index("{"):text.rindex("}") + 1])
                bad_ids = data.get("problematic_ids", [])
                reason = data.get("reason", "")
                if bad_ids:
                    # 向量库删除
                    await asyncio.to_thread(self._vdb.delete, bad_ids)
                    # PG 同步软删
                    await self._batch_update_status_pg(bad_ids, "deleted", soft_delete=True)
                    # 记录反思日志
                    for bid in bad_ids:
                        await self._log_reflection(
                            user_id=user_id, reflection_type="failure",
                            old_memory_id=bid, relation="error",
                            action="delete", llm_reason=reason,
                            trigger_source=error[:500],
                        )
                    logger.info("Failure reflection: deleted %d problematic memories", len(bad_ids))
        except Exception as e:
            logger.warning("Failure reflection failed: %s", e)

    async def reflect_on_correction(self, correction_text: str, user_id: str) -> None:
        """P3: 用户反馈反思 — 用户说"不对/错了"时修正记忆"""
        if not self._llm:
            return
        try:
            import asyncio
            vec = await asyncio.to_thread(self._emb.embed_query, correction_text)
            filter_expr = f'user_id = "{user_id}" and status != "archived"'
            related = await asyncio.to_thread(self._vdb.search, vec, 5, filter_expr)

            if not related:
                return

            prompt = (
                f"用户纠正: {correction_text}\n\n"
                f"相关记忆:\n" + "\n".join(f"- [ID:{m.get('id','')}] {m.get('abstract','')}" for m in related) +
                "\n\n哪些记忆和用户的纠正内容矛盾，需要删除？"
                "返回 JSON: {\"delete_ids\": [\"id1\"], \"reason\": \"原因\"}"
            )
            result = await self._llm.ainvoke(prompt)
            text = (getattr(result, "content", None) or str(result)).strip()
            if "{" in text:
                data = json.loads(text[text.index("{"):text.rindex("}") + 1])
                del_ids = data.get("delete_ids", [])
                reason = data.get("reason", "")
                if del_ids:
                    # 向量库删除
                    await asyncio.to_thread(self._vdb.delete, del_ids)
                    # PG 同步软删
                    await self._batch_update_status_pg(del_ids, "deleted", soft_delete=True)
                    # 记录反思日志
                    for did in del_ids:
                        await self._log_reflection(
                            user_id=user_id, reflection_type="correction",
                            old_memory_id=did, relation="contradiction",
                            action="delete", llm_reason=reason,
                            trigger_source=correction_text[:500],
                        )
                    logger.info("Correction reflection: deleted %d memories", len(del_ids))
        except Exception as e:
            logger.warning("Correction reflection failed: %s", e)

    # ── 会话结束反思（两步法：关系判断 + 规则映射）──

    async def reflect_on_session(self, extracted_items: list[MemoryItem], user_id: str) -> dict:
        """会话结束反思 — 检查本次提取的新记忆是否与已有记忆矛盾

        改造点：
          1. 只对 entities/events 类别的新记忆触发（其他类别靠 merge 已足够）
          2. 两步法 prompt（Step 1 关系判断 + Step 2 规则映射到 action）
          3. 操作时同步更新 PG（archive_old/discard_new 都同步 PG 状态）

        Returns:
            {"checked": N, "conflicts": N, "resolved": N, "actions": [...]}
        """
        if not self._llm or not extracted_items:
            return {"checked": 0, "conflicts": 0, "resolved": 0, "actions": []}

        import asyncio
        stats = {"checked": 0, "conflicts": 0, "resolved": 0, "actions": []}
        new_ids = {i.metadata.get("id", "") for i in extracted_items if i.metadata.get("id")}

        # 类别过滤：只对 entities/events 触发反思
        targets = [i for i in extracted_items
                   if i.metadata.get("category") in _REFLECTION_CATEGORIES]
        if not targets:
            return stats

        for item in targets:
            stats["checked"] += 1
            try:
                cat = item.metadata.get("category", "")
                # 检索已有的相似记忆（同类别 + 排除 archived）
                vec = await asyncio.to_thread(self._emb.embed_query, item.content)
                filter_expr = f'user_id = "{user_id}" and category = "{cat}" and status != "archived"'
                candidates = await asyncio.to_thread(self._vdb.search, vec, 5, filter_expr)

                # 排除本次会话写入的记忆
                candidates = [c for c in candidates if c.get("id", "") not in new_ids]

                # 过滤高相似度候选
                high_sim = [c for c in candidates
                            if c.get("score", 0) > _REFLECTION_SIMILARITY_THRESHOLD]
                if not high_sim:
                    continue

                # 对每个候选单独判断关系（避免一次 prompt 处理多条）
                for old in high_sim:
                    relation = await self._classify_relation(item.content, old)

                    if relation == "unrelated":
                        continue

                    stats["conflicts"] += 1
                    action = _RELATION_TO_ACTION.get(relation, "keep_both")

                    resolved = await self._apply_reflection_action(
                        action, item, old, user_id, relation,
                    )
                    if resolved:
                        stats["resolved"] += 1
                    stats["actions"].append({
                        "new_id": item.metadata.get("id", ""),
                        "old_id": old.get("id", ""),
                        "new_content": item.content[:50],
                        "old_content": old.get("abstract", old.get("content", ""))[:50],
                        "relation": relation,
                        "action": action,
                    })

            except Exception as e:
                logger.warning("Session reflection failed for memory: %s", e)

        if stats["conflicts"] > 0:
            logger.info("Session reflection: checked=%d, conflicts=%d, resolved=%d",
                        stats["checked"], stats["conflicts"], stats["resolved"])
        return stats

    async def _classify_relation(self, new_content: str, old: dict) -> str:
        """Step 1: LLM 判断新旧记忆的关系类型（4 选 1）"""
        old_content = old.get("content", old.get("abstract", ""))
        prompt = REFLECTION_RELATION_PROMPT.format(
            new=new_content[:300],
            old=old_content[:300],
        )
        try:
            result = await self._llm.ainvoke(prompt)
            text = (getattr(result, "content", None) or str(result)).strip().lower()
            for rel in ("identical", "contradiction", "evolution", "unrelated"):
                if rel in text:
                    return rel
        except Exception as e:
            logger.debug("Classify relation failed: %s", e)
        return "unrelated"

    async def _apply_reflection_action(self, action: str, new_item, old: dict,
                                        user_id: str, relation: str) -> bool:
        """Step 2: 按 action 执行反思决策"""
        import asyncio
        old_id = old.get("id", "")
        new_id = new_item.metadata.get("id", "")

        try:
            if action == "discard_new" and new_id:
                await asyncio.to_thread(self._vdb.delete, [new_id])
                await self._batch_update_status_pg([new_id], "deleted", soft_delete=True)
                await self._log_reflection(
                    user_id=user_id, reflection_type="session",
                    old_memory_id=old_id, new_memory_id=new_id,
                    relation=relation, action=action,
                )
                return True

            elif action == "archive_old" and old_id:
                # 归档旧记忆（不物理删除，允许后续复活）
                await self._sync_status_to_vdb(old_id, "archived")
                await self._batch_update_status_pg([old_id], "archived")
                await self._log_reflection(
                    user_id=user_id, reflection_type="session",
                    old_memory_id=old_id, new_memory_id=new_id,
                    relation=relation, action=action,
                )
                return True

            elif action == "update_old" and old_id:
                # evolution 场景：LLM 合并新旧内容 → 覆盖旧记忆
                merged = await self._merge_evolution(new_item.content, old)
                if merged:
                    await self._update_memory_content(old_id, merged, old, user_id)
                    # 新记忆丢弃（避免重复）
                    if new_id:
                        await asyncio.to_thread(self._vdb.delete, [new_id])
                        await self._batch_update_status_pg([new_id], "deleted", soft_delete=True)
                    await self._log_reflection(
                        user_id=user_id, reflection_type="session",
                        old_memory_id=old_id, new_memory_id=new_id,
                        relation=relation, action=action,
                        llm_reason=merged[:200],
                    )
                    return True

            # keep_both: 不操作，但记录日志
            await self._log_reflection(
                user_id=user_id, reflection_type="session",
                old_memory_id=old_id, new_memory_id=new_id,
                relation=relation, action=action,
            )
            return True

        except Exception as e:
            logger.warning("Apply reflection action failed: %s", e)
            return False

    async def _merge_evolution(self, new_content: str, old: dict) -> str:
        """evolution 场景：LLM 合并新旧内容"""
        try:
            prompt = EVOLUTION_MERGE_PROMPT.format(
                old_content=old.get("content", old.get("abstract", ""))[:500],
                new_content=new_content[:500],
            )
            result = await self._llm.ainvoke(prompt)
            merged = (getattr(result, "content", None) or str(result)).strip()
            return merged if merged else ""
        except Exception as e:
            logger.debug("Merge evolution failed: %s", e)
            return ""

    async def _update_memory_content(self, doc_id: str, new_content: str,
                                      old_doc: dict, user_id: str):
        """更新记忆内容（向量库 delete+upsert + PG UPDATE）"""
        import asyncio
        now = datetime.now(timezone.utc).isoformat()

        # 重新 embed
        try:
            new_vec = await asyncio.to_thread(self._emb.embed_query, new_content[:100])
        except Exception as e:
            logger.debug("Re-embed failed for %s: %s", doc_id, e)
            return

        # 向量库更新（delete + upsert）
        old_doc.update({
            "vector": new_vec,
            "text": new_content[:100],
            "abstract": new_content[:100],
            "content": new_content,
            "updated_at": now,
            "status": "active",  # evolution 后状态恢复为 active
        })
        try:
            await asyncio.to_thread(self._vdb.delete, [doc_id])
            await asyncio.to_thread(self._vdb.upsert, [old_doc])
        except Exception as e:
            logger.warning("Update memory content in VDB failed: %s", e)

        # 同步 PG
        try:
            from src.store.pg_pool import get_conn
            now_ms = int(time.time() * 1000)
            def _pg_update():
                with get_conn() as conn:
                    with conn.cursor() as cur:
                        cur.execute("""
                            UPDATE ai_agent_memory
                            SET abstract = %s, content = %s, status = 'active', updated_at = %s
                            WHERE (vector_id = %s OR memory_id = %s) AND delete_flg = 0
                        """, (new_content[:100], new_content, now_ms, doc_id, doc_id))
            await asyncio.to_thread(_pg_update)
        except Exception as e:
            logger.debug("PG update for evolution failed: %s", e)

    async def _log_reflection(self, user_id: str, reflection_type: str,
                              old_memory_id: str = "", new_memory_id: str = "",
                              relation: str = "", action: str = "",
                              llm_reason: str = "", trigger_source: str = ""):
        """写入反思日志"""
        import asyncio
        try:
            from src.store.pg_pool import get_conn
            now_ms = int(time.time() * 1000)
            def _do():
                with get_conn() as conn:
                    with conn.cursor() as cur:
                        cur.execute("""
                            INSERT INTO ai_memory_reflection_log
                                (tenant_id, user_id, reflection_type, trigger_source,
                                 old_memory_id, new_memory_id, relation, action,
                                 llm_reason, created_at)
                            VALUES (1, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        """, (user_id, reflection_type, (trigger_source or "")[:500],
                              old_memory_id or "", new_memory_id or "",
                              relation or "", action or "",
                              (llm_reason or "")[:1000], now_ms))
            await asyncio.to_thread(_do)
        except Exception as e:
            logger.debug("Log reflection failed: %s", e)

    # ── 定期全局反思 ──

    async def reflect_global(self, user_id: str) -> dict:
        """定期全局反思 — 碎片合并 + 一致性检查 + 过时检测

        参考 OpenViking 的 weekly_global_reflection 设计。
        建议每天或每周执行一次。

        Returns:
            {"merged": N, "inconsistencies": N, "stale_marked": N}
        """
        import asyncio
        stats = {"merged": 0, "inconsistencies": 0, "stale_marked": 0}

        if not self._llm:
            return stats

        # ── Step 1: 碎片化检测与合并 ──
        logger.info("Global reflection Step 1: fragment detection for user %s", user_id)

        for category in ("entities", "preferences"):
            try:
                filter_expr = f'user_id = "{user_id}" and category = "{category}"'
                all_memories = await asyncio.to_thread(
                    self._vdb.query_by_filter, filter_expr, 200,
                )
                if len(all_memories) < 2:
                    continue

                # 按 merge_key 分组
                groups: dict[str, list[dict]] = {}
                for m in all_memories:
                    mk = m.get("merge_key", "")
                    if mk:
                        groups.setdefault(mk, []).append(m)

                # 同 merge_key 超过 1 条 → 需要合并
                for mk, items in groups.items():
                    if len(items) <= 1:
                        continue

                    # LLM 合并
                    abstracts = "\n".join(f"- [ID:{m.get('id','')}] {m.get('abstract','')}" for m in items)
                    prompt = (
                        f"以下是关于 '{mk}' 的 {len(items)} 条记忆，请合并为 1 条。\n\n"
                        f"{abstracts}\n\n"
                        "保留最新、最完整的信息，丢弃重复和过时的。\n"
                        '返回 JSON: {"abstract":"合并后摘要","content":"合并后完整内容"}'
                    )
                    try:
                        result = await self._llm.ainvoke(prompt)
                        text = (getattr(result, "content", None) or str(result)).strip()
                        if "{" in text:
                            merged = json.loads(text[text.index("{"):text.rindex("}") + 1])
                            # 删除旧条目
                            old_ids = [m.get("id", "") for m in items if m.get("id")]
                            if old_ids:
                                await asyncio.to_thread(self._vdb.delete, old_ids)
                            # 写入合并后的新条目
                            new_abstract = merged.get("abstract", items[0].get("abstract", ""))
                            new_vec = await asyncio.to_thread(self._emb.embed_query, new_abstract)
                            await asyncio.to_thread(self._vdb.upsert, [{
                                "id": str(__import__("uuid").uuid4()),
                                "vector": new_vec,
                                "text": new_abstract,
                                "abstract": new_abstract,
                                "content": merged.get("content", new_abstract),
                                "category": category,
                                "merge_key": mk,
                                "parent_entity": items[0].get("parent_entity", ""),
                                "user_id": user_id,
                                "updated_at": datetime.now(timezone.utc).isoformat(),
                            }])
                            stats["merged"] += len(items) - 1
                            logger.debug("Merged %d fragments for %s/%s", len(items), category, mk)
                    except Exception as e:
                        logger.debug("Fragment merge failed for %s: %s", mk, e)

            except Exception as e:
                logger.warning("Global reflection fragment scan failed for %s: %s", category, e)

        # ── Step 2: 一致性检查（profile vs preferences）──
        logger.info("Global reflection Step 2: consistency check for user %s", user_id)

        try:
            profile = None
            if self._use_pg and self._pg:
                profile = await asyncio.to_thread(self._pg.get_profile, user_id)

            # preferences 从向量库查询
            prefs_results = []
            try:
                prefs_filter = f'user_id = "{user_id}" and category = "preferences"'
                prefs_results = await asyncio.to_thread(
                    self._vdb.query_by_filter, prefs_filter, 50,
                )
            except Exception:
                pass

            if profile and prefs_results:
                profile_text = profile.content or profile.abstract
                prefs_text = "\n".join(f"- {p.get('abstract', '')}" for p in prefs_results)

                prompt = (
                    "检查用户身份和偏好是否一致。\n\n"
                    f"用户身份 (profile):\n{profile_text}\n\n"
                    f"用户偏好 (preferences):\n{prefs_text}\n\n"
                    "是否有矛盾或不一致？\n"
                    '返回 JSON: {"consistent": true/false, "issues": ["问题描述1","问题描述2"]}'
                )
                result = await self._llm.ainvoke(prompt)
                text = (getattr(result, "content", None) or str(result)).strip()
                if "{" in text:
                    data = json.loads(text[text.index("{"):text.rindex("}") + 1])
                    issues = data.get("issues", [])
                    stats["inconsistencies"] = len(issues)
                    if issues:
                        logger.info("Consistency issues found: %s", issues)
        except Exception as e:
            logger.debug("Consistency check failed: %s", e)

        # ── Step 3: 三阶段淡化 ──
        decay_stats = await self.decay_memories(user_id)
        stats["to_stale"] = decay_stats.get("to_stale", 0)
        stats["to_archived"] = decay_stats.get("to_archived", 0)
        stats["deleted"] = decay_stats.get("deleted", 0)

        logger.info("Global reflection done: merged=%d, inconsistencies=%d, decayed=%s",
                     stats["merged"], stats["inconsistencies"], decay_stats)
        return stats

    # ── 记忆管理 ──

    def list_memories(self, user_id: str, category: str | None = None, limit: int = 20) -> list[dict]:
        filter_expr = f'user_id = "{user_id}"'
        if category:
            filter_expr += f' and category = "{category}"'
        try:
            return self._vdb.query_by_filter(filter_expr, limit)
        except Exception as e:
            logger.error("List memories failed: %s", e)
            return []

    def delete_memories(self, ids: list[str]) -> int:
        try:
            self._vdb.delete(ids)
            return len(ids)
        except Exception as e:
            logger.error("Delete memories failed: %s", e)
            return 0

    # ── VikingFS 集成 ──

    def get_fs(self, user_id: str) -> "VikingFS":
        """获取该用户的虚拟文件系统视图"""
        from .viking_fs import VikingFS
        return VikingFS(pg_dao=self._pg, vdb=self._vdb, user_id=user_id)

    def tree(self, user_id: str, uri: str = "", max_depth: int = 3) -> str:
        """展示用户记忆的目录树"""
        fs = self.get_fs(user_id)
        if not uri:
            # 展示 user + agent 两棵树
            lines = []
            lines.append(fs.tree("viking://user/memories/", max_depth))
            lines.append("")
            lines.append(fs.tree("viking://agent/memories/", max_depth))
            return "\n".join(lines)
        return fs.tree(uri, max_depth)

    def read_uri(self, user_id: str, uri: str, level: str = "L2") -> dict | None:
        """通过 URI 读取记忆内容"""
        fs = self.get_fs(user_id)
        node = fs.read(uri, level)
        if node:
            return {
                "uri": node.uri, "name": node.name, "category": node.category,
                "abstract": node.abstract, "overview": node.overview,
                "content": node.content,
            }
        return None

    def read_memory_detail(self, user_id: str, memory_id: str, level: str = "L2") -> dict | None:
        """按 ID 读取记忆详情（供 memory_read 工具调用）

        目录节点（is_leaf=false）：
          level="L1" → 返回 overview（结构化导航）
        叶子节点（is_leaf=true）：
          level="L2" → 返回 content（完整记忆内容）

        Args:
            user_id: 用户 ID
            memory_id: 记忆 ID（向量库中的 doc id）
            level: "L1" 返回目录 overview，"L2" 返回叶子 content
        """
        try:
            docs = self._vdb.query_by_filter(f'id = "{memory_id}"', 1)
            if not docs:
                return None
            doc = docs[0]
            is_directory = doc.get("is_leaf") == "false"

            result = {
                "id": doc.get("id", ""),
                "category": doc.get("category", ""),
                "merge_key": doc.get("merge_key", ""),
                "uri": doc.get("uri", ""),
                "is_directory": is_directory,
            }

            if level == "L1":
                # 目录的结构化概览
                result["overview"] = doc.get("overview", "")
            else:
                # 叶子的完整内容
                result["content"] = doc.get("content", "") or doc.get("abstract", "")

            return result
        except Exception as e:
            logger.debug("read_memory_detail failed for %s: %s", memory_id, e)
            return None

    def find_by_keyword(self, user_id: str, keyword: str) -> list[dict]:
        """通过关键词在虚拟文件系统中搜索"""
        fs = self.get_fs(user_id)
        nodes = fs.find(keyword)
        return [
            {"uri": n.uri, "name": n.name, "category": n.category, "abstract": n.abstract}
            for n in nodes
        ]

    # ── 目录级聚合 ──

    async def aggregate_directory(
        self, user_id: str, category: str, parent_entity: str = ""
    ) -> dict:
        """聚合某个目录下所有 L2，生成目录级 L0 和 L1

        示例:
          aggregate_directory("u1", "entities", "华为科技")
          → 查询 parent_entity="华为科技" 的所有 entities 记忆
          → 从所有 L2 聚合生成:
              L1: "## 商机洞察\n- ERP项目: 张总倾向方案B\n## 联系人洞察\n- 张伟: 说话直接..."
              L0: "华为科技: ERP项目张总倾向方案B，张伟说话直接，审批流程3-4周"

        Returns:
            {"l0": str, "l1": str, "l2_count": int, "l2_items": list}
        """
        import asyncio

        # 1. 收集该目录下所有记忆
        l2_items = []
        dir_path = f"{category}/{parent_entity}" if parent_entity else category

        # 从向量库查询
        if category in self._VDB_CATEGORIES:
            try:
                filter_parts = [f'user_id = "{user_id}"', f'category = "{category}"']
                if parent_entity:
                    filter_parts.append(f'parent_entity = "{parent_entity}"')
                filter_expr = " and ".join(filter_parts)
                results = await asyncio.to_thread(
                    self._vdb.query_by_filter, filter_expr, 100,
                )
                for r in results:
                    l2_items.append({
                        "abstract": r.get("abstract", ""),
                        "content": r.get("content", ""),
                        "merge_key": r.get("merge_key", ""),
                    })
            except Exception as e:
                logger.warning("Aggregate VDB query failed: %s", e)

        # 从 PG 查询
        if category in self._PG_CATEGORIES and self._use_pg and self._pg:
            try:
                rows = await asyncio.to_thread(
                    self._pg.get_by_user_category, user_id, category,
                )
                for r in rows:
                    if parent_entity and parent_entity not in r.merge_key:
                        continue
                    l2_items.append({
                        "abstract": r.abstract,
                        "content": r.content,
                        "merge_key": r.merge_key,
                    })
            except Exception as e:
                logger.warning("Aggregate PG query failed: %s", e)

        if not l2_items:
            return {"l0": "", "l1": "", "l2_count": 0, "l2_items": []}

        # 2. 如果没有 LLM，用简单拼接
        if not self._llm:
            l1 = "\n".join(f"- {item['abstract']}" for item in l2_items)
            l0 = "; ".join(item["abstract"][:30] for item in l2_items[:5])
            return {"l0": l0, "l1": l1, "l2_count": len(l2_items), "l2_items": l2_items}

        # 3. LLM 聚合生成 L1
        l2_text = "\n".join(
            f"- [{item['merge_key']}] {item['content']}" if item["merge_key"]
            else f"- {item['content']}"
            for item in l2_items
        )
        try:
            prompt_l1 = AGGREGATE_L1_PROMPT.format(
                directory_path=dir_path, l2_list=l2_text,
            )
            result = await self._llm.ainvoke(prompt_l1)
            l1 = (getattr(result, "content", None) or str(result)).strip()
        except Exception as e:
            logger.warning("Aggregate L1 failed: %s", e)
            l1 = "\n".join(f"- {item['abstract']}" for item in l2_items)

        # 4. LLM 压缩生成 L0
        try:
            prompt_l0 = AGGREGATE_L0_PROMPT.format(
                directory_path=dir_path, l1_content=l1,
            )
            result = await self._llm.ainvoke(prompt_l0)
            l0 = (getattr(result, "content", None) or str(result)).strip()
        except Exception as e:
            logger.warning("Aggregate L0 failed: %s", e)
            l0 = "; ".join(item["abstract"][:30] for item in l2_items[:5])

        return {"l0": l0, "l1": l1, "l2_count": len(l2_items), "l2_items": l2_items}

    async def aggregate_all_directories(self, user_id: str) -> dict[str, dict]:
        """聚合用户所有目录，返回 {目录路径: {l0, l1, l2_count}}"""
        import asyncio
        result = {}

        # 收集所有 parent_entity
        parents_by_cat: dict[str, set[str]] = {}
        for cat in list(self._VDB_CATEGORIES):
            try:
                filter_expr = f'user_id = "{user_id}" and category = "{cat}"'
                memories = await asyncio.to_thread(
                    self._vdb.query_by_filter, filter_expr, 200,
                )
                parents = set()
                for m in memories:
                    pe = m.get("parent_entity", "")
                    if pe:
                        parents.add(pe)
                parents_by_cat[cat] = parents
            except Exception:
                continue

        # 对每个有 parent_entity 的目录聚合
        for cat, parents in parents_by_cat.items():
            if not parents:
                # 无 parent_entity 的类别，整个类别聚合
                agg = await self.aggregate_directory(user_id, cat)
                if agg["l2_count"] > 0:
                    result[cat] = agg
            else:
                for pe in parents:
                    agg = await self.aggregate_directory(user_id, cat, pe)
                    if agg["l2_count"] > 0:
                        result[f"{cat}/{pe}"] = agg

        return result

    # ── 实体重命名级联更新 ──

    async def rename_entity(self, user_id: str, old_name: str, new_name: str) -> dict:
        """实体重命名 — 级联更新所有相关记忆的 merge_key / parent_entity / abstract

        场景: CRM 系统中客户名从 "华为科技" 改为 "深圳华为科技"
        影响: 所有 parent_entity="华为科技" 和 merge_key 包含 "华为科技" 的记忆

        Returns:
            {"updated": N, "errors": N}
        """
        import asyncio
        stats = {"updated": 0, "errors": 0}

        # 1. 查询向量库中所有 parent_entity = old_name 的记忆
        try:
            filter_expr = f'user_id = "{user_id}" and parent_entity = "{old_name}"'
            children = await asyncio.to_thread(self._vdb.query_by_filter, filter_expr, 200)
        except Exception as e:
            logger.error("Rename query children failed: %s", e)
            children = []

        # 2. 查询 merge_key = old_name 的顶层记忆（客户汇总）
        try:
            filter_expr2 = f'user_id = "{user_id}" and category = "entities"'
            all_entities = await asyncio.to_thread(self._vdb.query_by_filter, filter_expr2, 200)
            top_level = [m for m in all_entities if m.get("merge_key") == old_name]
        except Exception as e:
            logger.error("Rename query top-level failed: %s", e)
            top_level = []

        all_to_update = children + top_level
        if not all_to_update:
            logger.info("Rename: no memories found for '%s'", old_name)
            return stats

        # 3. 逐条更新
        for m in all_to_update:
            try:
                old_id = m.get("id", "")
                if not old_id:
                    continue

                # 替换字段中的旧名称
                new_merge_key = m.get("merge_key", "").replace(old_name, new_name)
                new_parent = m.get("parent_entity", "").replace(old_name, new_name)
                new_abstract = m.get("abstract", "").replace(old_name, new_name)
                new_content = m.get("content", "").replace(old_name, new_name)
                new_overview = m.get("overview", "").replace(old_name, new_name)

                # 重新 embed 更新后的 abstract
                new_vec = await asyncio.to_thread(self._emb.embed_query, new_abstract)

                # 删旧写新（tcvectordb 不支持原地更新所有字段）
                await asyncio.to_thread(self._vdb.delete, [old_id])
                await asyncio.to_thread(self._vdb.upsert, [{
                    "id": old_id, "vector": new_vec,
                    "text": new_abstract, "abstract": new_abstract,
                    "overview": new_overview, "content": new_content,
                    "category": m.get("category", "entities"),
                    "merge_key": new_merge_key,
                    "parent_entity": new_parent,
                    "user_id": user_id,
                    "source_type": m.get("source_type", "insight"),
                    "thread_id": m.get("thread_id", ""),
                    "created_at": m.get("created_at", ""),
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                }])
                stats["updated"] += 1
            except Exception as e:
                logger.warning("Rename update failed for %s: %s", m.get("id"), e)
                stats["errors"] += 1

        # 4. 同步更新 PG 中的记忆（如果有）
        if self._use_pg and self._pg:
            try:
                pg_memories = await asyncio.to_thread(
                    self._pg.get_by_user_category, user_id, "entities",
                )
                for row in pg_memories:
                    if old_name in row.merge_key or old_name in row.abstract:
                        new_mk = row.merge_key.replace(old_name, new_name)
                        new_abs = row.abstract.replace(old_name, new_name)
                        new_cont = row.content.replace(old_name, new_name)
                        await asyncio.to_thread(
                            self._pg.upsert,
                            user_id=user_id, category="entities",
                            merge_key=new_mk, abstract=new_abs, content=new_cont,
                        )
                        stats["updated"] += 1
            except Exception as e:
                logger.warning("PG rename failed: %s", e)

        # 5. 记录一条 events 记忆
        try:
            event_abstract = f"{datetime.now().strftime('%Y-%m-%d')} 客户{old_name}更名为{new_name}"
            event_vec = await asyncio.to_thread(self._emb.embed_query, event_abstract)
            await asyncio.to_thread(self._vdb.upsert, [{
                "id": str(uuid4()), "vector": event_vec,
                "text": event_abstract, "abstract": event_abstract,
                "overview": "", "content": f"客户名称变更：{old_name} → {new_name}，所有相关记忆已级联更新。",
                "category": "entities", "merge_key": "",
                "parent_entity": new_name, "user_id": user_id,
                "source_type": "insight",
                "thread_id": "system_rename",
                "created_at": datetime.now(timezone.utc).isoformat(),
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }])
        except Exception as e:
            logger.warning("Rename event record failed: %s", e)

        logger.info("Rename '%s' → '%s': updated %d, errors %d",
                     old_name, new_name, stats["updated"], stats["errors"])
        return stats
