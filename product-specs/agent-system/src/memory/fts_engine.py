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
    """

    def __init__(
        self,
        storage: MemoryStorage | None = None,
        storage_dir: str = "./data/memory",
        llm: Any = None,
        debounce_seconds: float = 5.0,
    ) -> None:
        self._storage = storage or MemoryStorage(storage_dir)
        self._llm = llm
        self._queue = DebounceQueue(
            debounce_seconds=debounce_seconds,
            handler=self._handle_queued_update,
        )

    @property
    def storage(self) -> MemoryStorage:
        return self._storage

    async def rewrite_query(self, messages: list, current_query: str) -> str:
        """多轮对话关键词提取 — 真实中文分词"""
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

    async def retrieve(
        self, query: str,
        dimensions: list[MemoryDimension] | None = None,
        user_id: str | None = None,
        top_k: int = 5,
    ) -> MemoryRetrievalResult:
        """FTS5 检索 + 时间衰减加权"""
        items: list[MemoryItem] = []
        now = time.time()

        # 提取查询关键词用于多路检索
        keywords = _extract_chinese_keywords(query)
        search_queries = [query]  # 原始查询
        if keywords:
            search_queries.append(" ".join(keywords[:5]))  # 关键词查询

        dims = dimensions or list(MemoryDimension)
        seen_contents: set[str] = set()  # 去重

        for search_q in search_queries:
            for dim in dims:
                results = self._storage.search(
                    search_q, user_id=user_id, dimension=dim.value, top_k=top_k,
                )
                for r in results:
                    content = r["content"]
                    # 内容去重（前 100 字符相同视为重复）
                    content_key = content[:100]
                    if content_key in seen_contents:
                        continue
                    seen_contents.add(content_key)

                    # 时间衰减：每过 7 天权重衰减 10%
                    created_at = r.get("created_at", now)
                    if isinstance(created_at, str):
                        try:
                            created_at = float(created_at)
                        except ValueError:
                            created_at = now
                    days_ago = (now - created_at) / 86400
                    time_decay = max(0.1, 1.0 - days_ago * 0.1 / 7)

                    # BM25 相关性
                    bm25_score = 1.0 / (1.0 + abs(r.get("rank", 0)))

                    # 综合分数
                    confidence = bm25_score * time_decay

                    items.append(MemoryItem(
                        dimension=dim,
                        content=content,
                        confidence=confidence,
                        metadata=json.loads(r.get("metadata", "{}")) if isinstance(r.get("metadata"), str) else {},
                    ))

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
        return MemoryExtractionResult(items=extracted, source_thread_id=thread_id)

    async def _handle_queued_update(self, thread_id: str, messages: list) -> None:
        """DebounceQueue 回调 — 合并后的记忆更新"""
        await self.extract_and_update(messages, thread_id)

    def submit_for_extraction(self, thread_id: str, messages: list) -> None:
        """提交到防抖队列（供 MemoryMiddleware.aafter_agent 调用）"""
        self._queue.submit(thread_id, messages)
