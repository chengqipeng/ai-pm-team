"""FTSMemoryEngine — 生产级记忆引擎，基于 SQLite FTS5

解决的问题：
1. 中文分词：按标点/停用词切分 + N-gram 子串匹配
2. LLM 驱动提取：通过 MemoryUpdater 用 LLM 智能提取记忆
3. 4 维度全覆盖：user_profile / customer_context / task_history / domain_knowledge
4. 去重合并：相同 thread 的 task_history 只保留最新一条
5. 串联 DebounceQueue：高频写入自动合并
6. 时间衰减：检索时近期记忆权重更高
"""
from __future__ import annotations

import json
import logging
import re
import time
from typing import Any

from ..middleware.memory import (
    MemoryEngine, MemoryDimension, MemoryItem,
    MemoryRetrievalResult, MemoryExtractionResult,
)
from .storage import MemoryStorage
from .queue import DebounceQueue

logger = logging.getLogger(__name__)

# 中文停用词（高频无意义词）
_STOP_WORDS = frozenset(
    "的 了 在 是 我 有 和 就 不 人 都 一 一个 上 也 很 到 说 要 去 你 会 着 没有 看 好 "
    "自己 这 他 她 它 们 那 些 什么 怎么 为什么 可以 能 吗 呢 吧 啊 哦 嗯 请 帮 帮我 "
    "一下 下 把 被 让 给 从 对 但 而 如果 因为 所以 虽然 然后 还 又 再 已经".split()
)

# 客户/实体名称模式
_ENTITY_PATTERNS = [
    re.compile(r'[\u4e00-\u9fff]{2,6}(?:科技|公司|集团|有限|股份|银行|保险|证券)'),  # 公司名
    re.compile(r'[\u4e00-\u9fff]{2,3}(?=的|说|要|给|跟|和|与)'),  # 人名（后接助词）
    re.compile(r'(?:account|opportunity|contact|lead|activity)\b', re.IGNORECASE),  # 实体 API key
]


def _extract_chinese_keywords(text: str, max_words: int = 15) -> list[str]:
    """中文关键词提取 — 按标点切分 + 过滤停用词 + 提取实体名"""
    keywords = []

    # 1. 提取实体名（公司名、人名）
    for pattern in _ENTITY_PATTERNS:
        for match in pattern.finditer(text):
            word = match.group().strip()
            if word and word not in _STOP_WORDS and len(word) >= 2:
                keywords.append(word)

    # 2. 按标点和空格切分
    segments = re.split(r'[，。！？、；：\s,.\?!;:\n\t]+', text)
    for seg in segments:
        seg = seg.strip()
        if not seg or len(seg) < 2:
            continue
        # 对长句做 2-4 字的滑动窗口
        if len(seg) > 4:
            for n in (4, 3, 2):
                for i in range(len(seg) - n + 1):
                    gram = seg[i:i + n]
                    if gram not in _STOP_WORDS and not all(c in _STOP_WORDS for c in gram):
                        keywords.append(gram)
        elif seg not in _STOP_WORDS:
            keywords.append(seg)

    # 去重保序
    seen = set()
    unique = []
    for w in keywords:
        if w not in seen:
            seen.add(w)
            unique.append(w)
    return unique[:max_words]


class FTSMemoryEngine(MemoryEngine):
    """生产级 FTS5 记忆引擎

    Args:
        storage: MemoryStorage 实例
        storage_dir: 存储目录（storage 为 None 时使用）
        llm: LLM 实例（需实现 ainvoke），用于智能记忆提取
        debounce_seconds: 防抖队列窗口（秒）
        cleanup_every_n: 每 N 次写入触发一次清理检查
        retention_days: 各维度记忆保留天数
        max_per_dimension: 各维度每用户最大记忆条数
    """

    # 默认各维度保留天数
    _DEFAULT_RETENTION_DAYS: dict[str, int] = {
        "task_history": 30,
        "customer_context": 90,
        "user_profile": 180,
        "domain_knowledge": 365,
    }

    # 默认各维度每用户最大条数
    _DEFAULT_MAX_PER_DIMENSION: dict[str, int] = {
        "task_history": 100,
        "customer_context": 200,
        "user_profile": 50,
        "domain_knowledge": 50,
    }

    def __init__(
        self,
        storage: MemoryStorage | None = None,
        storage_dir: str = "./data/memory",
        llm: Any = None,
        debounce_seconds: float = 5.0,
        cleanup_every_n: int = 20,
        retention_days: dict[str, int] | None = None,
        max_per_dimension: dict[str, int] | None = None,
    ) -> None:
        self._storage = storage or MemoryStorage(storage_dir)
        self._llm = llm
        self._queue = DebounceQueue(
            debounce_seconds=debounce_seconds,
            handler=self._handle_queued_update,
        )
        self._write_count: int = 0
        self._cleanup_every_n = cleanup_every_n
        self._retention_days = {**self._DEFAULT_RETENTION_DAYS, **(retention_days or {})}
        self._max_per_dimension = {**self._DEFAULT_MAX_PER_DIMENSION, **(max_per_dimension or {})}

    @property
    def storage(self) -> MemoryStorage:
        return self._storage

    async def rewrite_query(self, messages: list, current_query: str) -> str:
        """多轮对话查询改写 — LLM 优先，规则 fallback

        LLM 可用时：调用 LLM 理解多轮上下文，提取核心检索意图
        LLM 不可用时：规则提取中文关键词（N-gram + 实体名）
        """
        # LLM 改写（核心能力）
        if self._llm is not None:
            try:
                return await self._llm_rewrite(messages, current_query)
            except Exception as e:
                logger.warning("LLM rewrite_query failed, fallback to rules: %s", e)

        # 规则 fallback
        all_text = current_query
        human_count = 0
        for msg in reversed(messages):
            if getattr(msg, "type", "") == "human" or type(msg).__name__ == "HumanMessage":
                content = getattr(msg, "content", "")
                if isinstance(content, str) and content.strip():
                    all_text += " " + content
                    human_count += 1
                    if human_count >= 3:
                        break

        keywords = _extract_chinese_keywords(all_text)
        return " ".join(keywords) if keywords else current_query

    async def _llm_rewrite(self, messages: list, current_query: str) -> str:
        """用 LLM 理解多轮对话上下文，改写为精准检索查询"""
        # 构建对话上下文（最近 5 轮）
        context_lines = []
        count = 0
        for msg in reversed(messages):
            msg_type = getattr(msg, "type", "")
            content = getattr(msg, "content", "")
            if not isinstance(content, str) or not content.strip():
                continue
            if msg_type in ("human", "ai"):
                context_lines.insert(0, f"[{msg_type}]: {content[:200]}")
                count += 1
                if count >= 10:
                    break

        prompt = (
            "你是一个查询改写助手。根据以下多轮对话上下文，将用户的最新问题改写为"
            "适合全文搜索的关键词查询。\n\n"
            "要求：\n"
            "1. 提取核心实体名（人名、公司名、产品名）\n"
            "2. 提取关键业务概念（商机、客户、金额、阶段等）\n"
            "3. 解析代词指代（'他'→具体人名，'那个'→具体实体）\n"
            "4. 只输出关键词，用空格分隔，不要输出完整句子\n"
            "5. 最多 10 个关键词\n\n"
            "对话上下文：\n" + "\n".join(context_lines) + "\n\n"
            f"当前问题：{current_query}\n\n"
            "改写后的检索关键词："
        )

        result = await self._llm.ainvoke(prompt)
        rewritten = getattr(result, "content", None) or str(result)
        rewritten = rewritten.strip()

        # 验证输出合理性（不超过 200 字符，不是完整句子）
        if len(rewritten) > 200 or "。" in rewritten or "，" in rewritten:
            # LLM 输出不合理，fallback 到提取关键词
            keywords = _extract_chinese_keywords(rewritten)
            return " ".join(keywords[:10]) if keywords else current_query

        logger.info("LLM rewrite: '%s' → '%s'", current_query[:50], rewritten[:50])
        return rewritten

    async def retrieve(
        self, query: str,
        dimensions: list[MemoryDimension] | None = None,
        user_id: str | None = None,
        top_k: int = 5,
    ) -> MemoryRetrievalResult:
        """FTS5 检索 + 时间衰减加权 — 同时向 TracingMiddleware 记录 hierarchical_search spans"""
        items: list[MemoryItem] = []
        now = time.time()

        # 提取查询关键词用于多路检索
        keywords = _extract_chinese_keywords(query)
        search_queries = [query]  # 原始查询
        if keywords:
            search_queries.append(" ".join(keywords[:5]))  # 关键词查询
            # 每个关键词也单独搜一次（提高召回率）
            for kw in keywords[:3]:
                if len(kw) >= 2:
                    search_queries.append(kw)

        dims = dimensions or list(MemoryDimension)
        seen_contents: set[str] = set()  # 去重

        # 按 index.html 的 hierarchical_search 格式，分 skill / resource / memory 三路检索
        # 映射: skill → task_history + domain_knowledge, resource → customer_context, memory → user_profile
        _dim_to_search_type = {
            MemoryDimension.TASK_HISTORY: "skill",
            MemoryDimension.DOMAIN_KNOWLEDGE: "skill",
            MemoryDimension.CUSTOMER_CONTEXT: "resource",
            MemoryDimension.USER_PROFILE: "memory",
        }

        # 按 search_type 分组执行，记录 hierarchical_search spans
        search_type_dims: dict[str, list[MemoryDimension]] = {}
        for dim in dims:
            st = _dim_to_search_type.get(dim, "memory")
            search_type_dims.setdefault(st, []).append(dim)

        for search_type, type_dims in search_type_dims.items():
            hs_start = time.monotonic()
            type_items: list[MemoryItem] = []
            children_spans: list[dict] = []

            for search_q in search_queries:
                for dim in type_dims:
                    # vector_search 子步骤
                    vs_start = time.monotonic()
                    results = self._storage.search(
                        search_q, user_id=user_id, dimension=dim.value, top_k=top_k,
                    )
                    vs_dur = (time.monotonic() - vs_start) * 1000
                    children_spans.append({
                        "type": "vector_search",
                        "name": "vector_search",
                        "duration_ms": vs_dur,
                        "metadata": {
                            "dimension": dim.value,
                            "query": search_q[:50],
                            "result_count": len(results),
                            "results": [
                                {"content": r["content"][:200], "dimension": r.get("dimension", ""),
                                 "rank": r.get("rank", 0)}
                                for r in results[:10]
                            ],
                        },
                    })

                    # rerank 子步骤
                    rr_start = time.monotonic()
                    for r in results:
                        content = r["content"]
                        content_key = content[:100]
                        if content_key in seen_contents:
                            continue
                        seen_contents.add(content_key)

                        created_at = r.get("created_at", now)
                        if isinstance(created_at, str):
                            try:
                                created_at = float(created_at)
                            except ValueError:
                                created_at = now
                        days_ago = (now - created_at) / 86400
                        time_decay = max(0.1, 1.0 - days_ago * 0.1 / 7)
                        bm25_score = 1.0 / (1.0 + abs(r.get("rank", 0)))
                        confidence = bm25_score * time_decay

                        type_items.append(MemoryItem(
                            dimension=dim,
                            content=content,
                            confidence=confidence,
                            metadata=json.loads(r.get("metadata", "{}")) if isinstance(r.get("metadata"), str) else {},
                        ))
                    rr_dur = (time.monotonic() - rr_start) * 1000
                    children_spans.append({
                        "type": "rerank",
                        "name": "rerank",
                        "duration_ms": rr_dur,
                        "metadata": {
                            "dimension": dim.value,
                            "scored_count": len(type_items),
                            "scored_items": [
                                {"content": it.content[:200], "confidence": round(it.confidence, 3),
                                 "dimension": it.dimension.value}
                                for it in type_items[-len(results):]  # 本轮新增的
                            ][:10],
                        },
                    })

            hs_dur = (time.monotonic() - hs_start) * 1000
            items.extend(type_items)

            # 向 TracingMiddleware 记录 hierarchical_search span
            try:
                from src.middleware.tracing import tracing_middleware
                tracing_middleware.record_hierarchical_search(
                    search_type=search_type,
                    duration_ms=hs_dur,
                    hit_count=len(type_items),
                    children=children_spans,
                )
            except Exception as e:
                logger.debug("Failed to record hierarchical_search span: %s", e)

        # 按 confidence 排序，取 top_k
        items.sort(key=lambda x: x.confidence, reverse=True)
        return MemoryRetrievalResult(items=items[:top_k], query_used=query)

    async def extract_and_update(
        self, messages: list, thread_id: str,
        user_id: str | None = None,
    ) -> MemoryExtractionResult:
        """从对话中提取关键信息并持久化 — 4 维度全覆盖 + 去重"""
        extracted: list[MemoryItem] = []
        uid = user_id or "default"

        # 提取最后一轮对话
        last_human = ""
        last_ai = ""
        tool_names_used: list[str] = []
        for msg in reversed(messages):
            msg_type = getattr(msg, "type", "")
            content = getattr(msg, "content", "")
            if not isinstance(content, str):
                content = str(content) if content else ""
            if msg_type == "human" and not last_human:
                last_human = content
            elif msg_type == "ai" and not last_ai and content.strip():
                last_ai = content
            elif msg_type == "tool":
                tool_name = getattr(msg, "name", "")
                if tool_name and tool_name not in tool_names_used:
                    tool_names_used.append(tool_name)
            if last_human and last_ai:
                break

        if not last_human or not last_ai:
            return MemoryExtractionResult(source_thread_id=thread_id)

        # ── 维度 1: task_history — 去重（同 thread 只保留最新） ──
        task_summary = f"问: {last_human[:200]}\n答: {last_ai[:300]}"
        if tool_names_used:
            task_summary += f"\n使用工具: {', '.join(tool_names_used[:5])}"

        # 删除同 thread 的旧 task_history
        existing = self._storage.get_by_user(uid, dimension=MemoryDimension.TASK_HISTORY.value, limit=100)
        for old in existing:
            meta = old.get("metadata", "{}")
            if isinstance(meta, str):
                try:
                    meta = json.loads(meta)
                except json.JSONDecodeError:
                    meta = {}
            if meta.get("thread_id") == thread_id:
                # 标记为已替换（FTS5 不支持 DELETE by rowid，用普通表删除）
                conn = self._storage._ensure_db()
                conn.execute("DELETE FROM memories WHERE id = ?", (old["id"],))
                conn.commit()

        self._storage.add(
            user_id=uid, content=task_summary,
            dimension=MemoryDimension.TASK_HISTORY.value,
            metadata=json.dumps({"thread_id": thread_id, "timestamp": time.time(),
                                  "tools": tool_names_used[:5]}, ensure_ascii=False),
        )
        extracted.append(MemoryItem(dimension=MemoryDimension.TASK_HISTORY, content=task_summary))

        # ── 维度 2: user_profile — 偏好检测 ──
        preference_markers = ["我喜欢", "我习惯", "我偏好", "请用", "我需要", "我是",
                              "以后都", "默认用", "不要用", "别用"]
        for marker in preference_markers:
            if marker in last_human:
                self._storage.add(
                    user_id=uid, content=last_human[:500],
                    dimension=MemoryDimension.USER_PROFILE.value,
                    metadata=json.dumps({"thread_id": thread_id, "marker": marker}, ensure_ascii=False),
                )
                extracted.append(MemoryItem(dimension=MemoryDimension.USER_PROFILE, content=last_human[:500]))
                break

        # ── 维度 3: customer_context — 客户/实体信息提取 ──
        combined = last_human + " " + last_ai
        for pattern in _ENTITY_PATTERNS:
            entities = pattern.findall(combined)
            if entities:
                entity_info = f"提及实体: {', '.join(set(entities[:5]))}\n上下文: {combined[:300]}"
                self._storage.add(
                    user_id=uid, content=entity_info,
                    dimension=MemoryDimension.CUSTOMER_CONTEXT.value,
                    metadata=json.dumps({"thread_id": thread_id, "entities": list(set(entities[:5]))}, ensure_ascii=False),
                )
                extracted.append(MemoryItem(dimension=MemoryDimension.CUSTOMER_CONTEXT, content=entity_info))
                break

        # ── 维度 4: domain_knowledge — 通过 LLM 提取（如果可用） ──
        if self._llm is not None:
            try:
                from .updater import MemoryUpdater
                updater = MemoryUpdater(llm=self._llm)
                existing_knowledge = self._storage.read_file(f"{uid}_knowledge")
                updated = await updater.extract_and_update(messages[-6:], existing_knowledge)
                if updated and updated != existing_knowledge:
                    self._storage.write_file(f"{uid}_knowledge", updated)
                    self._storage.add(
                        user_id=uid, content=updated[:500],
                        dimension=MemoryDimension.DOMAIN_KNOWLEDGE.value,
                        metadata=json.dumps({"thread_id": thread_id, "source": "llm_extraction"}, ensure_ascii=False),
                    )
                    extracted.append(MemoryItem(dimension=MemoryDimension.DOMAIN_KNOWLEDGE, content=updated[:500]))
            except Exception as e:
                logger.warning("LLM memory extraction failed: %s", e)

        logger.info("Extracted %d memory items (%s) from thread %s",
                     len(extracted), [i.dimension.value for i in extracted], thread_id)

        # 写入计数器 — 每 N 次触发清理
        self._write_count += 1
        if self._write_count >= self._cleanup_every_n:
            self._write_count = 0
            try:
                deleted = self.cleanup(user_id=uid)
                if deleted > 0:
                    logger.info("Auto cleanup: removed %d expired/overflow memories for user %s", deleted, uid)
            except Exception as e:
                logger.warning("Auto cleanup failed: %s", e)

        return MemoryExtractionResult(items=extracted, source_thread_id=thread_id)

    async def _handle_queued_update(self, thread_id: str, messages: list) -> None:
        """DebounceQueue 回调 — 合并后的记忆更新"""
        await self.extract_and_update(messages, thread_id)

    def cleanup(self, user_id: str | None = None) -> int:
        """清理过期和超量记忆

        两阶段清理：
        1. TTL 过期：按维度删除超过保留天数的记忆
        2. 容量淘汰：按维度删除超过上限的最旧记忆

        Args:
            user_id: 指定用户清理；None 则只做全局 TTL 过期清理

        Returns:
            删除的记忆条数
        """
        total_deleted = 0
        now = time.time()

        # 阶段 1: TTL 过期清理（按维度不同保留天数）
        for dimension, days in self._retention_days.items():
            cutoff = now - days * 86400
            deleted = self._storage.cleanup_expired(cutoff, dimension=dimension)
            if deleted > 0:
                logger.info("TTL cleanup: removed %d expired '%s' memories (older than %d days)",
                            deleted, dimension, days)
            total_deleted += deleted

        # 阶段 2: 容量淘汰（需要指定用户）
        if user_id:
            for dimension, max_count in self._max_per_dimension.items():
                deleted = self._storage.cleanup_overflow(user_id, dimension, max_count)
                if deleted > 0:
                    logger.info("Overflow cleanup: removed %d '%s' memories for user %s (max %d)",
                                deleted, dimension, user_id, max_count)
                total_deleted += deleted

        return total_deleted

    def cleanup_all_users(self) -> int:
        """清理所有用户的过期和超量记忆（适合定时任务调用）"""
        total_deleted = 0
        now = time.time()

        # TTL 过期清理
        for dimension, days in self._retention_days.items():
            cutoff = now - days * 86400
            deleted = self._storage.cleanup_expired(cutoff, dimension=dimension)
            total_deleted += deleted

        # 容量淘汰 — 遍历所有用户
        conn = self._storage._ensure_db()
        users = conn.execute("SELECT DISTINCT user_id FROM memories").fetchall()
        for (uid,) in users:
            for dimension, max_count in self._max_per_dimension.items():
                deleted = self._storage.cleanup_overflow(uid, dimension, max_count)
                total_deleted += deleted

        if total_deleted > 0:
            logger.info("Full cleanup completed: removed %d memories across %d users",
                        total_deleted, len(users))
        return total_deleted

    def submit_for_extraction(self, thread_id: str, messages: list) -> None:
        """提交到防抖队列（供 MemoryMiddleware.aafter_agent 调用）"""
        self._queue.submit(thread_id, messages)

    # ── 面向 Agent 的记忆管理（供 ManageMemoryTool 调用） ──

    def list_memories(self, user_id: str, keyword: str = "",
                      dimension: str | None = None, limit: int = 20) -> list[dict]:
        """列出用户记忆（可按关键词和维度筛选）"""
        uid = user_id or "default"
        return self._storage.search_and_list(uid, keyword, dimension, limit)

    def delete_memories_by_keyword(self, user_id: str, keyword: str,
                                   dimension: str | None = None) -> int:
        """按关键词删除匹配的记忆"""
        uid = user_id or "default"
        matched = self._storage.search_and_list(uid, keyword, dimension, limit=100)
        if not matched:
            return 0
        ids = [m["id"] for m in matched]
        deleted = self._storage.delete_by_ids(ids)
        logger.info("Deleted %d memories matching keyword '%s' for user %s", deleted, keyword, uid)
        return deleted

    def delete_memories_by_ids(self, ids: list[int]) -> int:
        """按 ID 列表删除记忆"""
        return self._storage.delete_by_ids(ids)

    def clear_all_memories(self, user_id: str) -> int:
        """清空用户所有记忆"""
        uid = user_id or "default"
        deleted = self._storage.delete_by_user(uid)
        logger.info("Cleared all memories for user %s, deleted %d", uid, deleted)
        return deleted
