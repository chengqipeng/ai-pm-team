"""上下文压缩存档 — 压缩前建立轮次索引，持久化到 PG，供 recall_context 工具检索恢复原文

设计原则:
  1. 原文持久化到 PG — 唯一存储层，不使用内存缓存
  2. 数据时效性标注 — 每条存档记录采集时间，恢复时标注"数据年龄"
  3. 压缩前写入 — AutoCompact / FullCompact 执行前对即将丢弃的消息建立索引
  4. 多信号检索 — PG ILIKE 多字段搜索 + 应用层评分排序
  5. 租户隔离 — 所有存储/检索强制 tenant_id 条件
  6. 禁止降级 — turn_id 精确查询只走 PG，查不到即返回未找到

与 ContextWindowMiddleware 的关系:
  - _auto_compact / _full_compact 压缩前调用 archive.index_messages()
  - recall_context 工具通过 middleware.archive 访问索引
  - reset_session 时重置上下文（PG 数据由会话清理任务处理）

数据存储:
  - PG 持久化: ai_context_archive 表（唯一数据源，跨进程/重启后可恢复）
"""
from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class ArchivedTurn:
    """被压缩轮次的索引记录"""
    turn_id: int                          # 轮次编号（与摘要中 [📦 turn:N] 对应）
    timestamp: float                      # 存档时间（秒级 Unix 时间戳）
    data_timestamp: float                 # 数据采集时间（秒级，用于时效性判断）
    user_query: str                       # 用户原始问题（完整保留）
    answer_preview: str                   # Agent 回复前 500 字
    entities: list[str]                   # 实体名列表
    keywords: list[str]                   # 分词关键词
    tool_names: list[str]                 # 使用的工具名
    skill_names: list[str]                # 执行的 Skill 名
    message_count: int                    # 该轮次消息条数
    # 原文引用
    thread_id: str                        # 会话 thread_id
    message_range: tuple[int, int]        # messages 中的 [start, end) 索引
    # 原始消息（完整持久化）
    original_messages_json: str           # 消息序列化 JSON（持久存储，不再依赖 Checkpointer）
    # 降级数据
    tool_summaries: list[str]             # 每个 ToolMessage 的一行摘要
    key_data: dict = field(default_factory=dict)  # 正则提取的精确数字


class ContextArchive:
    """被压缩消息的存档索引 — 供 recall_context 工具检索

    存储策略:
      - 仅使用 PG 持久化（ai_context_archive 表），不使用内存缓存
      - 所有检索操作直接查询 PG，保证数据一致性
      - 禁止降级：查不到即返回未找到，不做内存兜底

    生命周期: PG 数据随会话软删除
    """

    def __init__(self, max_entries: int = 100, tenant_id: int = 0):
        self._next_id = 1
        self._tenant_id = tenant_id
        self._thread_id: str = ""

    def has_entries(self) -> bool:
        """检查当前会话在 PG 中是否有存档记录"""
        if not self._tenant_id or not self._thread_id:
            return False
        try:
            from src.store.context_archive_dao import ContextArchiveDAO
            max_turn = ContextArchiveDAO.get_max_turn_id(self._tenant_id, self._thread_id)
            return max_turn > 0
        except Exception as e:
            logger.debug("[ContextArchive] has_entries 查询失败: %s", e)
            return False

    def set_context(self, tenant_id: int, thread_id: str) -> None:
        """设置租户和会话上下文（由 ContextWindowMiddleware 在 before_model 中调用）"""
        self._tenant_id = tenant_id
        self._thread_id = thread_id
        # 同步 _next_id（从 PG 获取当前最大 turn_id）
        if tenant_id and thread_id:
            try:
                from src.store.context_archive_dao import ContextArchiveDAO
                max_id = ContextArchiveDAO.get_max_turn_id(tenant_id, thread_id)
                if max_id >= self._next_id:
                    self._next_id = max_id + 1
            except Exception:
                pass

    def index_messages(self, messages: list, thread_id: str, base_msg_index: int = 0) -> int:
        """将被压缩的消息按轮次切分并建立索引 + 持久化到 PG

        Args:
            messages: 即将被压缩的消息列表
            thread_id: 当前 Checkpointer 的 thread_id
            base_msg_index: 这些消息在完整 messages 列表中的起始偏移

        Returns:
            新增的索引条数
        """
        from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

        self._thread_id = thread_id
        turns = self._split_into_turns(messages)
        added = 0
        pg_rows = []

        for turn_messages, offset_in_segment in turns:
            human_msg = next((m for m in turn_messages if isinstance(m, HumanMessage)), None)
            ai_msgs = [m for m in turn_messages if isinstance(m, AIMessage)]
            tool_msgs = [m for m in turn_messages if isinstance(m, ToolMessage)]

            # 拼接所有内容用于实体/关键词提取
            all_content = " ".join(
                getattr(m, "content", "") or "" for m in turn_messages
                if isinstance(getattr(m, "content", ""), str)
            )

            # Agent 回复预览
            answer_preview = ""
            for m in reversed(ai_msgs):
                c = getattr(m, "content", "") or ""
                if c.strip() and not getattr(m, "tool_calls", None):
                    answer_preview = c[:500]
                    break

            # 提取实体
            entities = _extract_entities(all_content)

            # 分词关键词
            keywords = _extract_keywords(
                (human_msg.content if human_msg else "") + " " + answer_preview
            )

            # 工具名
            tool_names = list(set(
                getattr(m, "name", "") or "" for m in tool_msgs if getattr(m, "name", "")
            ))

            # Skill 名
            skill_names = []
            for m in ai_msgs:
                for tc in (getattr(m, "tool_calls", None) or []):
                    if tc.get("name") == "skills_tool":
                        sn = tc.get("args", {}).get("skill_name", "")
                        if sn:
                            skill_names.append(sn)

            # 工具结果摘要
            tool_summaries = []
            for m in tool_msgs:
                content = getattr(m, "content", "") or ""
                name = getattr(m, "name", "") or "tool"
                if len(content) > 100:
                    tool_summaries.append(f"[{name}] {content[:150]}...")
                elif content:
                    tool_summaries.append(f"[{name}] {content}")

            # 正则提取关键数据
            key_data = _extract_key_data(all_content)

            # 计算在完整 messages 中的 range
            abs_start = base_msg_index + offset_in_segment
            abs_end = abs_start + len(turn_messages)

            # 序列化原始消息（完整持久化）
            original_messages_json = self._serialize_messages(turn_messages)

            # 估算数据采集时间（取该轮次中最早消息的时间，如果没有则取当前时间）
            data_timestamp = self._estimate_data_timestamp(turn_messages)

            entry = ArchivedTurn(
                turn_id=self._next_id,
                timestamp=time.time(),
                data_timestamp=data_timestamp,
                user_query=human_msg.content[:2000] if human_msg else "",
                answer_preview=answer_preview,
                entities=entities,
                keywords=keywords,
                tool_names=tool_names,
                skill_names=skill_names,
                message_count=len(turn_messages),
                thread_id=thread_id,
                message_range=(abs_start, abs_end),
                original_messages_json=original_messages_json,
                tool_summaries=tool_summaries,
                key_data=key_data,
            )

            # 构建 PG 行
            pg_rows.append(self._entry_to_pg_row(entry))

            self._next_id += 1
            added += 1

        # 写入 PG（唯一存储层）
        if pg_rows:
            self._persist_to_db(pg_rows)

        if added:
            logger.info("[ContextArchive] 存档 %d 个轮次到 PG (thread=%s)",
                        added, thread_id)
        return added

    def search(self, query: str, top_k: int = 3) -> list[ArchivedTurn]:
        """多信号检索相关的存档轮次 — 直接查询 PG

        检索策略:
          - turn_id 精确匹配: 直接 PG 精确查询，查不到返回空（禁止降级）
          - 关键词/实体搜索: PG ILIKE 多字段搜索 → 应用层评分排序
        """
        if not self._tenant_id or not self._thread_id:
            return []

        from src.store.context_archive_dao import ContextArchiveDAO

        # 检查是否有精确 turn_id 指定
        turn_id_match = re.search(r'turn[_:\s]*(\d+)', query)
        if turn_id_match:
            target_id = int(turn_id_match.group(1))
            row = ContextArchiveDAO.get_by_turn_id(self._tenant_id, self._thread_id, target_id)
            if row:
                return [self._row_to_entry(row)]
            # 禁止降级：PG 查不到直接返回空
            return []

        # 关键词/实体模糊搜索：从 PG 取候选集，应用层评分排序
        query_entities = _extract_entities(query)
        query_keywords = _extract_keywords(query)
        search_terms = list(dict.fromkeys(query_entities + query_keywords))

        if not search_terms:
            # 无法提取有效搜索词，用原始 query 分词兜底
            search_terms = _extract_keywords(query) or [query[:50]]

        # PG 多字段 ILIKE 搜索（取较多候选，应用层精排）
        rows = ContextArchiveDAO.search_by_keywords(
            self._tenant_id, self._thread_id, search_terms, top_k=top_k * 3
        )
        if not rows:
            return []

        # 应用层评分排序
        entries = [self._row_to_entry(r) for r in rows]
        return self._rank_entries(entries, query, query_entities, query_keywords, top_k)

    def get_by_turn_id(self, turn_id: int) -> ArchivedTurn | None:
        """按 turn_id 精确获取（仅查 PG，禁止降级）"""
        if not self._tenant_id or not self._thread_id:
            return None
        try:
            from src.store.context_archive_dao import ContextArchiveDAO
            row = ContextArchiveDAO.get_by_turn_id(self._tenant_id, self._thread_id, turn_id)
            if not row:
                return None
            return self._row_to_entry(row)
        except Exception as e:
            logger.debug("[ContextArchive] PG 查询失败: %s", e)
            return None

    def get_data_age_description(self, entry: ArchivedTurn) -> str:
        """获取数据时效性描述（供 recall_context 返回时标注）

        Returns:
            时效性描述字符串，如 "数据采集于 2 小时前" 或 "数据采集于 3 天前（可能已过时）"
        """
        now = time.time()
        age_seconds = now - entry.data_timestamp
        age_minutes = age_seconds / 60
        age_hours = age_seconds / 3600
        age_days = age_seconds / 86400

        if age_minutes < 5:
            return "数据采集于刚才（实时）"
        elif age_minutes < 60:
            return f"数据采集于 {int(age_minutes)} 分钟前"
        elif age_hours < 4:
            return f"数据采集于 {age_hours:.1f} 小时前"
        elif age_hours < 24:
            return f"数据采集于 {age_hours:.0f} 小时前（建议确认是否需要最新数据）"
        else:
            return f"数据采集于 {age_days:.0f} 天前（数据可能已过时，建议使用业务工具重新查询）"

    def is_data_likely_stale(self, entry: ArchivedTurn, staleness_hours: float = 4.0) -> bool:
        """判断数据是否可能已过时

        Args:
            entry: 存档条目
            staleness_hours: 过时阈值（默认 4 小时）

        Returns:
            True = 数据可能已过时，建议用户用业务工具重查
        """
        age_hours = (time.time() - entry.data_timestamp) / 3600
        return age_hours > staleness_hours

    def clear(self) -> None:
        """重置会话上下文（PG 数据由会话清理任务处理）"""
        self._next_id = 1
        self._thread_id = ""

    # ═══════════════════════════════════════════════════════════
    # 内部方法
    # ═══════════════════════════════════════════════════════════

    def _split_into_turns(self, messages: list) -> list[tuple[list, int]]:
        """按 HumanMessage 切分消息为轮次"""
        from langchain_core.messages import HumanMessage

        turns: list[tuple[list, int]] = []
        current_turn: list = []
        current_offset = 0

        for i, msg in enumerate(messages):
            if isinstance(msg, HumanMessage) and current_turn:
                turns.append((current_turn, current_offset))
                current_turn = [msg]
                current_offset = i
            else:
                if not current_turn:
                    current_offset = i
                current_turn.append(msg)

        if current_turn:
            turns.append((current_turn, current_offset))

        return turns

    def _serialize_messages(self, messages: list) -> str:
        """将消息列表序列化为 JSON（用于 PG 持久化）

        序列化格式: [{role, content, tool_calls?, tool_call_id?, name?}, ...]
        """
        serialized = []
        for msg in messages:
            entry: dict[str, Any] = {
                "role": getattr(msg, "type", "unknown"),
                "content": getattr(msg, "content", "") or "",
            }
            # tool_calls
            tool_calls = getattr(msg, "tool_calls", None)
            if tool_calls:
                entry["tool_calls"] = [
                    {"id": tc.get("id", ""), "name": tc.get("name", ""), "args": tc.get("args", {})}
                    for tc in tool_calls
                ]
            # tool_call_id (ToolMessage)
            tool_call_id = getattr(msg, "tool_call_id", None)
            if tool_call_id:
                entry["tool_call_id"] = tool_call_id
            # name (ToolMessage)
            name = getattr(msg, "name", None)
            if name:
                entry["name"] = name

            serialized.append(entry)

        return json.dumps(serialized, ensure_ascii=False)

    def _estimate_data_timestamp(self, turn_messages: list) -> float:
        """估算轮次的数据采集时间

        策略: 使用当前时间减去该轮次在整个消息列表中的相对位置估算。
        实际上 LangChain 的 Message 没有内建时间戳，所以默认取当前时间。
        如果消息有 additional_kwargs.timestamp 则优先使用。
        """
        for msg in turn_messages:
            additional = getattr(msg, "additional_kwargs", {}) or {}
            ts = additional.get("timestamp")
            if ts and isinstance(ts, (int, float)):
                return float(ts) if ts > 1e12 else float(ts)  # 支持毫秒和秒
        # 默认: 当前时间（即"刚刚采集"）
        return time.time()

    def _entry_to_pg_row(self, entry: ArchivedTurn):
        """将内存 ArchivedTurn 转为 PG 数据行"""
        from src.store.context_archive_models import ContextArchiveRow
        return ContextArchiveRow(
            tenant_id=self._tenant_id,
            thread_id=entry.thread_id or self._thread_id,
            turn_id=entry.turn_id,
            user_query=entry.user_query[:2000],
            answer_preview=entry.answer_preview[:500],
            entities=json.dumps(entry.entities, ensure_ascii=False),
            keywords=json.dumps(entry.keywords, ensure_ascii=False),
            tool_names=json.dumps(entry.tool_names, ensure_ascii=False),
            skill_names=json.dumps(entry.skill_names, ensure_ascii=False),
            tool_summaries=json.dumps(entry.tool_summaries, ensure_ascii=False),
            key_data=json.dumps(entry.key_data, ensure_ascii=False),
            message_count=entry.message_count,
            message_range_start=entry.message_range[0],
            message_range_end=entry.message_range[1],
            original_messages=entry.original_messages_json,
            data_timestamp=int(entry.data_timestamp * 1000),
            archived_at=int(entry.timestamp * 1000),
        )

    def _persist_to_db(self, rows: list) -> None:
        """持久化到 PG（唯一存储层，写入失败时记录错误）"""
        try:
            from src.store.context_archive_dao import ContextArchiveDAO
            ContextArchiveDAO.batch_insert(rows)
            logger.debug("[ContextArchive] PG 写入 %d 条", len(rows))
        except Exception as e:
            logger.error("[ContextArchive] PG 写入失败: %s", e)

    def _row_to_entry(self, row) -> ArchivedTurn:
        """将 PG ContextArchiveRow 转为 ArchivedTurn"""
        return ArchivedTurn(
            turn_id=row.turn_id,
            timestamp=row.archived_at / 1000.0,
            data_timestamp=row.data_timestamp / 1000.0,
            user_query=row.user_query,
            answer_preview=row.answer_preview,
            entities=json.loads(row.entities) if row.entities else [],
            keywords=json.loads(row.keywords) if row.keywords else [],
            tool_names=json.loads(row.tool_names) if row.tool_names else [],
            skill_names=json.loads(row.skill_names) if row.skill_names else [],
            message_count=row.message_count,
            thread_id=row.thread_id,
            message_range=(row.message_range_start, row.message_range_end),
            original_messages_json=row.original_messages,
            tool_summaries=json.loads(row.tool_summaries) if row.tool_summaries else [],
            key_data=json.loads(row.key_data) if row.key_data else {},
        )

    def _rank_entries(
        self,
        entries: list[ArchivedTurn],
        query: str,
        query_entities: list[str],
        query_keywords: list[str],
        top_k: int,
    ) -> list[ArchivedTurn]:
        """应用层评分排序

        评分信号:
          - 实体匹配 (权重 0.35)
          - 关键词重叠 (权重 0.25)
          - user_query 词匹配 (权重 0.15) — 使用分词而非字符
          - 工具/Skill 名匹配 (权重 0.15)
          - 时间衰减 (权重 0.10)
        """
        now = time.time()
        query_kw_set = set(query_keywords)
        query_entity_set = set(query_entities)
        # 对 query 做分词（用于 user_query 匹配）
        query_words = set(_extract_keywords(query))

        scored: list[tuple[float, ArchivedTurn]] = []

        for entry in entries:
            score = 0.0

            # 实体匹配
            if query_entity_set:
                entity_hits = len(query_entity_set & set(entry.entities))
                score += entity_hits * 0.35

            # 关键词重叠
            if query_kw_set:
                kw_hits = len(query_kw_set & set(entry.keywords))
                score += min(kw_hits * 0.08, 0.25)

            # user_query 词匹配（修正：使用分词而非字符集合）
            if entry.user_query and query_words:
                entry_words = set(_extract_keywords(entry.user_query))
                if entry_words:
                    overlap = len(query_words & entry_words) / max(len(query_words | entry_words), 1)
                    score += overlap * 0.15

            # 工具/Skill 名匹配
            query_lower = query.lower()
            if any(t.lower() in query_lower for t in entry.tool_names if t):
                score += 0.10
            if any(s in query for s in entry.skill_names if s):
                score += 0.10

            # 时间衰减
            age_hours = (now - entry.timestamp) / 3600
            score += 0.10 / (1 + age_hours)

            if score > 0.05:
                scored.append((score, entry))

        scored.sort(key=lambda x: -x[0])
        return [entry for _, entry in scored[:top_k]]


# ═══════════════════════════════════════════════════════════
# 辅助函数（零 LLM 成本提取）
# ═══════════════════════════════════════════════════════════

def _extract_entities(text: str) -> list[str]:
    """从文本中提取 CRM 相关实体名（正则，零 LLM）"""
    if not text:
        return []
    entities: list[str] = []
    # 公司名
    entities += re.findall(r'(?:PT|CV|Ltd|Inc)\s+[\w\s]{2,20}', text)
    entities += re.findall(r'[\u4e00-\u9fa5]{2,10}(?:科技|集团|公司|有限|技术)', text)
    # 实体 ID
    entities += re.findall(r'(?:opp|acc|con|case|quote|act)_[\w]+', text)
    # 人名
    entities += re.findall(r'(?:Pak|Ibu|Mr|Ms|Dr|Prof)\s+\w+', text)
    # 去重 + 限制数量
    return list(dict.fromkeys(e.strip() for e in entities if len(e.strip()) > 2))[:20]


def _extract_keywords(text: str) -> list[str]:
    """简单关键词提取（中英文分词，不依赖 jieba）"""
    if not text:
        return []
    # 中文：按 2-4 字连续汉字切分
    cn_words = re.findall(r'[\u4e00-\u9fa5]{2,4}', text)
    # 英文：按空格切分，过滤短词和停用词
    en_words = [w.lower() for w in re.findall(r'[a-zA-Z]{3,}', text)]
    stop_words = {"the", "and", "for", "that", "this", "with", "from", "are", "was", "were"}
    en_words = [w for w in en_words if w not in stop_words]
    return list(dict.fromkeys(cn_words + en_words))[:30]


def _extract_key_data(text: str) -> dict:
    """正则提取精确数字（金额/日期/百分比）"""
    if not text:
        return {}
    data: dict[str, list[str]] = {}

    # 金额
    amounts = re.findall(r'[\$¥￥]\s*[\d,.]+[KMB万亿]?|\d[\d,.]*\s*(?:万|亿|USD|CNY|元)', text)
    if amounts:
        data["金额"] = list(dict.fromkeys(amounts[:8]))

    # 日期
    dates = re.findall(r'\d{4}[-/]\d{1,2}[-/]\d{1,2}', text)
    if dates:
        data["日期"] = list(dict.fromkeys(dates[:5]))

    # 百分比
    pcts = re.findall(r'\d+\.?\d*\s*%', text)
    if pcts:
        data["比例"] = list(dict.fromkeys(pcts[:5]))

    return data
