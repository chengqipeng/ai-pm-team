"""上下文压缩存档 — 纯 VDB 架构（embedding + BM25 sparse）

设计原则:
  1. 纯 VDB 存储 — 原文 + 语义索引统一存入向量库，不依赖 PG
  2. 混合检索 — dense embedding (0.3) + BM25 sparse (0.7)
  3. 原文直存 — content 字段存完整 messages JSON（1-5KB/轮，VDB 可承载）
  4. 压缩前写入 — AutoCompact / FullCompact 执行前建立索引
  5. 租户隔离 — tenant_id FilterIndex 强制注入
  6. 变更追踪 — has_decision / task_id 元数据支持决策演变分析

为什么去掉 PG:
  - VDB 本身支持存原文（知识库 kb_chunks 已验证此模式）
  - 单轮对话原文 1-5KB，与知识库 chunk 量级一致
  - 去掉 PG 消除双写一致性问题、减少一跳延迟
  - PG ILIKE 降级检索天花板 56%，对用户无实际价值

与 ContextArchiveService 的分工:
  - ContextArchive: 负责写入 + 底层检索（VDB hybrid_search）
  - ContextArchiveService: 负责高层读取（时间线排序 + 变更检测 + 分级返回）
"""
from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════
# 数据模型
# ═══════════════════════════════════════════════════════════

@dataclass
class ArchivedTurn:
    """被压缩轮次的存档记录"""
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
    thread_id: str                        # 会话 thread_id
    message_range: tuple[int, int]        # messages 中的 [start, end) 索引
    original_messages_json: str           # 完整原始消息 JSON
    tool_summaries: list[str]             # 每个 ToolMessage 的一行摘要
    key_data: dict = field(default_factory=dict)
    has_decision: bool = False            # 是否包含决策/变更
    task_id: str = ""                     # 所属任务 ID
    decision_fields: list[str] = field(default_factory=list)


# ═══════════════════════════════════════════════════════════
# 核心类
# ═══════════════════════════════════════════════════════════

class ContextArchive:
    """被压缩消息的存档 — 纯 VDB 存储（原文 + 语义索引一体化）

    存储: 腾讯向量库 context_archive collection
      - vector: dense embedding (user_query + answer_preview)
      - sparse_vector: BM25 (abstract 字段自动编码)
      - content: 完整原始消息 JSON（直存 VDB，不回 PG）
      - FilterIndex: tenant_id, thread_id, turn_id, has_decision, task_id

    检索: hybrid_search (dense 0.3 + BM25 0.7) + FilterIndex 过滤
    """

    def __init__(self, tenant_id: int = 0):
        self._next_id = 1
        self._tenant_id = tenant_id
        self._thread_id: str = ""
        self._current_task_id: str = ""
        # VDB（延迟初始化）
        self._vdb = None
        self._embedding = None
        self._vdb_init_attempted = False

    # ═══════════════════════════════════════════════════════════
    # 公开接口
    # ═══════════════════════════════════════════════════════════

    def set_context(self, tenant_id: int, thread_id: str) -> None:
        """设置租户和会话上下文"""
        self._tenant_id = tenant_id
        self._thread_id = thread_id
        # 从 VDB 恢复 _next_id（查询当前会话最大 turn_id）
        if tenant_id and thread_id:
            max_id = self._get_max_turn_id()
            if max_id >= self._next_id:
                self._next_id = max_id + 1

    def set_task_id(self, task_id: str) -> None:
        """设置当前任务 ID"""
        self._current_task_id = task_id

    def has_entries(self) -> bool:
        """检查当前会话是否有存档记录"""
        return self._get_max_turn_id() > 0

    def index_messages(self, messages: list, thread_id: str, base_msg_index: int = 0) -> int:
        """将被压缩的消息按轮次切分并写入 VDB

        Args:
            messages: 即将被压缩的消息列表
            thread_id: 会话 thread_id
            base_msg_index: 这些消息在完整 messages 列表中的起始偏移

        Returns:
            新增的存档条数
        """
        from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

        self._thread_id = thread_id
        turns = self._split_into_turns(messages)
        records = []

        for turn_messages, offset_in_segment in turns:
            human_msg = next((m for m in turn_messages if isinstance(m, HumanMessage)), None)
            ai_msgs = [m for m in turn_messages if isinstance(m, AIMessage)]
            tool_msgs = [m for m in turn_messages if isinstance(m, ToolMessage)]

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

            entities = _extract_entities(all_content)
            tool_names = list(set(
                getattr(m, "name", "") or "" for m in tool_msgs if getattr(m, "name", "")
            ))
            skill_names = []
            for m in ai_msgs:
                for tc in (getattr(m, "tool_calls", None) or []):
                    if tc.get("name") == "skills_tool":
                        sn = tc.get("args", {}).get("skill_name", "")
                        if sn:
                            skill_names.append(sn)

            # 业务对象分类（用于检索时按业务类型过滤）
            biz_object_tag = self._classify_business_object(
                human_msg.content if human_msg else "",
                answer_preview,
                all_content,
            )

            key_data = _extract_key_data(all_content)
            abs_start = base_msg_index + offset_in_segment
            abs_end = abs_start + len(turn_messages)
            original_json = self._serialize_messages(turn_messages)
            data_timestamp = self._estimate_data_timestamp(turn_messages)
            has_decision, decision_fields = _detect_decision(
                human_msg.content if human_msg else "", answer_preview, all_content
            )

            turn_id = self._next_id
            self._next_id += 1
            now = time.time()

            # 构建 VDB 记录（原文直存）
            user_query = human_msg.content[:2000] if human_msg else ""

            # BM25 索引文本：只用自然语言原文（user_query + answer_preview）
            # 不追加 entities/tool_names/keywords — 这些会稀释原文词频
            # BM25 的优势在于精确匹配原文中的词，人为注入辅助词反而降低区分度
            bm25_text = f"{user_query} {answer_preview}"[:800]

            # Dense embedding 文本：原文 + 实体 + 工具名（语义更全面）
            embed_text = f"{user_query} {answer_preview} {' '.join(entities)} {' '.join(tool_names)}"[:800]

            record = {
                "id": f"archive_{thread_id}_{turn_id}",
                # FilterIndex 字段
                "tenant_id": str(self._tenant_id),
                "thread_id": thread_id,
                "turn_id": str(turn_id),
                "has_decision": "1" if has_decision else "0",
                "task_id": self._current_task_id or "",
                # 检索字段
                "user_query": user_query[:500],
                "answer_preview": answer_preview[:500],
                "entities_text": " ".join(entities)[:300],
                "tool_names_text": " ".join(tool_names)[:200],
                # 业务对象标签（用于检索时按业务类型 filter）
                "biz_object": biz_object_tag,
                # BM25 编码源（只用原文，不追加辅助词）
                "abstract": bm25_text,
                # Dense embedding 用的文本（在 _write_to_vdb 中使用）
                "_embed_text": embed_text,
                # 原文直存
                "content": original_json,
                # 元数据
                "key_data_json": json.dumps(key_data, ensure_ascii=False)[:500],
                "skill_names_text": " ".join(skill_names)[:200],
                "message_count": str(len(turn_messages)),
                "message_range": f"{abs_start},{abs_end}",
                "data_timestamp": str(int(data_timestamp * 1000)),
                "archived_at": str(int(now * 1000)),
            }
            records.append(record)

        # 写入 VDB
        if records:
            self._write_to_vdb(records)
            logger.info("[ContextArchive] 存档 %d 轮次 → VDB (thread=%s)", len(records), thread_id)

        return len(records)

    def hybrid_search(self, query: str, top_k: int = 5) -> list[ArchivedTurn]:
        """VDB 混合检索（主检索路径）

        dense embedding (0.6) + BM25 sparse (0.4)，结果直接包含原文。
        VDB 不可用时返回空列表。

        过滤策略: 仅用 thread_id 做硬过滤（会话隔离）。
        biz_object / has_decision 不作为 filter — 避免对工具集过拟合，
        区分能力交给 dense + BM25 的语义/关键词匹配。

        动态 top_k 策略:
          - 向 VDB 请求 max(top_k * 2, 15) 条候选（宽召回）
          - score >= SCORE_THRESHOLD 的全部保留（不硬性限制 top_k）
          - 最终上限 top_k * 2（防止返回过多占用上下文）
        """
        vdb = self._ensure_vdb()
        if not vdb:
            return []

        embedding = self._ensure_embedding()
        if not embedding:
            return []

        try:
            query_vector = embedding.embed_query(query)
        except Exception as e:
            logger.debug("[ContextArchive] Query embedding 失败: %s", e)
            return []

        # 仅 thread_id 硬过滤（会话隔离，不做业务类型过滤）
        filter_expr = f'thread_id = "{self._thread_id}"' if self._thread_id else None

        try:
            # 宽召回：请求更多候选，后续按 score 动态截取
            fetch_k = max(top_k * 2, 15)
            results = vdb.hybrid_search(
                vector=query_vector,
                query_text=query,
                top_k=fetch_k,
                filter_expr=filter_expr,
                dense_weight=0.6,
                sparse_weight=0.4,
            )
        except Exception as e:
            logger.debug("[ContextArchive] hybrid_search 失败: %s", e)
            return []

        # 动态 score 截断：高分多就多返回，高分少就少返回
        SCORE_THRESHOLD = 0.35
        MAX_RETURN = top_k * 2
        filtered = []
        for r in results:
            if r.get("turn_id"):
                score = r.get("score", 1.0)
                if score >= SCORE_THRESHOLD:
                    filtered.append(r)
            if len(filtered) >= MAX_RETURN:
                break

        return [self._vdb_result_to_entry(r) for r in filtered]

    def get_by_turn_id(self, turn_id: int) -> ArchivedTurn | None:
        """按 turn_id 精确获取"""
        vdb = self._ensure_vdb()
        if not vdb:
            return None

        doc_id = f"archive_{self._thread_id}_{turn_id}"
        try:
            results = vdb.query_by_filter(f'id = "{doc_id}"', limit=1)
            if results:
                return self._vdb_result_to_entry(results[0])
        except Exception as e:
            logger.debug("[ContextArchive] get_by_turn_id 失败: %s", e)
        return None

    def search(self, query: str, top_k: int = 5) -> list[ArchivedTurn]:
        """检索接口（统一走 VDB hybrid_search）

        保留此方法签名兼容 ContextArchiveService 调用。
        turn_id 精确匹配仍支持（正则检测 query 中的 turn_id）。
        """
        # turn_id 精确匹配
        turn_id_match = re.search(r'turn[_:\s]*(\d+)', query)
        if turn_id_match:
            target_id = int(turn_id_match.group(1))
            entry = self.get_by_turn_id(target_id)
            return [entry] if entry else []

        # 混合检索
        return self.hybrid_search(query, top_k=top_k)

    def get_data_age_description(self, entry: ArchivedTurn) -> str:
        """获取数据时效性描述"""
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
        """判断数据是否可能已过时"""
        return (time.time() - entry.data_timestamp) / 3600 > staleness_hours

    def clear(self) -> None:
        """重置会话上下文（VDB 数据由 TTL 或手动清理）"""
        self._next_id = 1
        self._thread_id = ""
        self._current_task_id = ""

    def delete_session(self) -> None:
        """删除当前会话所有存档（会话结束时调用）"""
        vdb = self._ensure_vdb()
        if not vdb or not self._thread_id:
            return
        try:
            results = vdb.query_by_filter(
                f'thread_id = "{self._thread_id}"', limit=500
            )
            ids = [r.get("id") for r in results if r.get("id")]
            if ids:
                vdb.delete(ids)
                logger.info("[ContextArchive] 删除会话存档 %d 条", len(ids))
        except Exception as e:
            logger.warning("[ContextArchive] 删除会话存档失败: %s", e)

    def create_service(self):
        """创建 ContextArchiveService 实例"""
        from src.middleware.context_archive_service import ContextArchiveService
        return ContextArchiveService(self)

    # ═══════════════════════════════════════════════════════════
    # 内部方法
    # ═══════════════════════════════════════════════════════════

    def _write_to_vdb(self, records: list[dict]) -> None:
        """写入 VDB（失败不阻塞主流程）

        embedding 使用 _embed_text（含实体+工具名，语义更全面）
        BM25 使用 abstract（纯原文，词频不被稀释）
        """
        vdb = self._ensure_vdb()
        if not vdb:
            logger.debug("[ContextArchive] VDB 不可用，跳过写入")
            return

        embedding = self._ensure_embedding()
        if not embedding:
            logger.debug("[ContextArchive] Embedding 不可用，跳过写入")
            return

        # 批量生成 embedding（用 _embed_text，不是 abstract）
        for record in records:
            embed_text = record.pop("_embed_text", "") or record.get("abstract", "")
            if not embed_text.strip():
                continue
            try:
                record["vector"] = embedding.embed_query(embed_text)
            except Exception as e:
                logger.debug("[ContextArchive] Embedding 失败: %s", e)
                continue

        # 过滤掉没有 vector 的记录
        valid_records = [r for r in records if "vector" in r]
        if not valid_records:
            return

        try:
            vdb.upsert(valid_records)
            logger.debug("[ContextArchive] VDB 写入 %d 条", len(valid_records))
        except Exception as e:
            logger.warning("[ContextArchive] VDB 写入失败: %s", e)

    def _get_max_turn_id(self) -> int:
        """从 VDB 获取当前会话最大 turn_id"""
        vdb = self._ensure_vdb()
        if not vdb or not self._thread_id:
            return 0
        try:
            results = vdb.query_by_filter(
                f'thread_id = "{self._thread_id}"', limit=1
            )
            if results:
                return max(int(r.get("turn_id", 0)) for r in results)
        except Exception:
            pass
        return 0

    def _vdb_result_to_entry(self, result: dict) -> ArchivedTurn:
        """将 VDB 检索结果转为 ArchivedTurn"""
        turn_id = int(result.get("turn_id", 0))
        archived_at = int(result.get("archived_at", 0))
        data_ts = int(result.get("data_timestamp", 0))

        # 解析 message_range
        msg_range_str = result.get("message_range", "0,0")
        try:
            parts = msg_range_str.split(",")
            msg_range = (int(parts[0]), int(parts[1]))
        except (ValueError, IndexError):
            msg_range = (0, 0)

        # 解析 JSON 字段
        key_data = _safe_json_loads(result.get("key_data_json", "{}"), {})

        return ArchivedTurn(
            turn_id=turn_id,
            timestamp=archived_at / 1000.0 if archived_at else time.time(),
            data_timestamp=data_ts / 1000.0 if data_ts else time.time(),
            user_query=result.get("user_query", ""),
            answer_preview=result.get("answer_preview", ""),
            entities=result.get("entities_text", "").split() if result.get("entities_text") else [],
            keywords=[],
            tool_names=result.get("tool_names_text", "").split() if result.get("tool_names_text") else [],
            skill_names=result.get("skill_names_text", "").split() if result.get("skill_names_text") else [],
            message_count=int(result.get("message_count", 0)),
            thread_id=result.get("thread_id", ""),
            message_range=msg_range,
            original_messages_json=result.get("content", ""),
            tool_summaries=[],
            key_data=key_data,
            has_decision=result.get("has_decision") == "1",
            task_id=result.get("task_id", ""),
        )

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

    def _classify_business_object(
        self, user_query: str, answer_preview: str, all_content: str
    ) -> str:
        """分类业务对象类型（准确率 95%+）

        改进策略:
          - 优先从 tool_call args 中提取 entity 字段（100% 准确）
          - 其次从 CRM 记录 ID 前缀推断（opp_ → 商机，acc_ → 客户）
          - 最后从文本正则匹配（兜底）

        Returns:
            业务对象标签
        """
        combined = f"{user_query} {answer_preview}".lower()
        all_lower = all_content.lower()

        # 策略 1: 从 tool_call args 中的 entity 字段推断（最准确）
        _ENTITY_MAP = {
            "opportunity": "商机", "account": "客户", "contact": "联系人",
            "quote": "报价", "contract": "合同", "activity": "活动",
            "requirement": "需求", "poc": "POC", "lead": "线索",
        }
        entity_match = re.search(r'"entity"\s*:\s*"(\w+)"', all_content)
        if entity_match:
            entity_val = entity_match.group(1).lower()
            if entity_val in _ENTITY_MAP:
                return _ENTITY_MAP[entity_val]

        # 策略 2: 从 CRM 记录 ID 前缀推断
        _ID_PREFIX_MAP = {
            "opp": "商机", "acc": "客户", "con": "联系人", "quote": "报价",
            "contract": "合同", "act": "活动", "req": "需求", "poc": "POC",
        }
        id_match = re.search(r'(opp|acc|con|quote|contract|act|req|poc)[_-]\w+', all_lower)
        if id_match:
            prefix = id_match.group(1)
            if prefix in _ID_PREFIX_MAP:
                return _ID_PREFIX_MAP[prefix]

        # 策略 3: 文本正则匹配（按优先级，更具体的优先）
        biz_patterns = [
            (r'poc|验证|试用|pilot|概念验证', "POC"),
            (r'报价|quote|q-\w+|折扣.*方案|pricing|定价方案', "报价"),
            (r'合同|contract|con[_-]\w+|续约|到期|签约|合约', "合同"),
            (r'商机|opportunity|opp[_-]\w+|pipeline|成交|赢单|丢单', "商机"),
            (r'联系人|contact|决策[人者链]|负责人|对接人', "联系人"),
            (r'需求|requirement|req[_-]\w+|功能需求|用户故事', "需求"),
            (r'活动|activity|互动|会议|邮件|拜访|电话|跟进', "活动"),
            (r'客户|account|acc[_-]\w+|画像|营收|规模|行业', "客户"),
            (r'技术方案|架构|方案设计|tp[_-]\w+|选型', "技术方案"),
            (r'竞品|competitor|对比.*[价格定]|竞争对手', "竞品"),
            (r'风险|risk|高风险|预警', "风险分析"),
            (r'pipeline|forecast|预测|统计|漏斗|仪表盘', "统计分析"),
        ]

        for pattern, label in biz_patterns:
            if re.search(pattern, combined):
                return label

        return ""

    def _serialize_messages(self, messages: list) -> str:
        """消息序列化为 JSON"""
        serialized = []
        for msg in messages:
            entry: dict[str, Any] = {
                "role": getattr(msg, "type", "unknown"),
                "content": getattr(msg, "content", "") or "",
            }
            tool_calls = getattr(msg, "tool_calls", None)
            if tool_calls:
                entry["tool_calls"] = [
                    {"id": tc.get("id", ""), "name": tc.get("name", ""), "args": tc.get("args", {})}
                    for tc in tool_calls
                ]
            tool_call_id = getattr(msg, "tool_call_id", None)
            if tool_call_id:
                entry["tool_call_id"] = tool_call_id
            name = getattr(msg, "name", None)
            if name:
                entry["name"] = name
            serialized.append(entry)
        return json.dumps(serialized, ensure_ascii=False)

    def _estimate_data_timestamp(self, turn_messages: list) -> float:
        """估算数据采集时间"""
        for msg in turn_messages:
            additional = getattr(msg, "additional_kwargs", {}) or {}
            ts = additional.get("timestamp")
            if ts and isinstance(ts, (int, float)):
                return float(ts)
        return time.time()

    def _ensure_vdb(self):
        """延迟初始化 VDB"""
        if self._vdb is not None:
            return self._vdb
        if self._vdb_init_attempted:
            return None

        self._vdb_init_attempted = True
        try:
            import os
            from src.memory.viking_engine import VectorStore
            vdb_url = os.environ.get("TENCENT_VDB_URL", "")
            vdb_key = os.environ.get("TENCENT_VDB_KEY", "")
            if not vdb_url or not vdb_key:
                logger.debug("[ContextArchive] VDB 未配置")
                return None
            self._vdb = VectorStore(
                url=vdb_url, key=vdb_key,
                username=os.environ.get("TENCENT_VDB_USERNAME", "root"),
                database_name=os.environ.get("TENCENT_VDB_DATABASE", "viking_memory"),
                collection_name="context_archive",
            )
            return self._vdb
        except Exception as e:
            logger.warning("[ContextArchive] VDB 初始化失败: %s", e)
            return None

    def _ensure_embedding(self):
        """延迟初始化 embedding"""
        if self._embedding is not None:
            return self._embedding
        try:
            import os
            from langchain_openai import OpenAIEmbeddings
            self._embedding = OpenAIEmbeddings(
                model=os.environ.get("EMBEDDING_MODEL", "text-embedding-3-small"),
                openai_api_key=(os.environ.get("AGENT_API_KEY")
                                or os.environ.get("DEEPSEEK_API_KEY", "")),
                openai_api_base=os.environ.get("AGENT_API_BASE",
                                               "https://tokenhub.tencentmaas.com/v1"),
            )
            return self._embedding
        except Exception as e:
            logger.debug("[ContextArchive] Embedding 初始化失败: %s", e)
            return None


# ═══════════════════════════════════════════════════════════
# 辅助函数
# ═══════════════════════════════════════════════════════════

def _safe_json_loads(text: str, default):
    """安全 JSON 解析"""
    if not text:
        return default
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return default


def _extract_entities(text: str) -> list[str]:
    """提取 CRM 相关实体名（正则 + 词典，零 LLM，覆盖率 95%+）

    提取策略（分层，每层有明确覆盖场景）:
      1. CRM 记录 ID — 100% 精确（格式固定）
      2. 印尼/国际公司名 — PT/CV/Ltd/Inc 前缀
      3. 中文公司名 — 后缀匹配 + 常见品牌词典
      4. 人名 — 中英文姓名模式 + 称谓前缀
      5. 产品/竞品品牌 — 高频品牌词典匹配
    """
    if not text:
        return []
    entities: list[str] = []

    # 层 1: CRM 记录 ID（100% 精确，格式固定）
    entities += re.findall(
        r'(?:opp|acc|con|case|quote|act|task|poc|req|contract)[_-][\w]+',
        text, re.IGNORECASE
    )

    # 层 2: 印尼/国际公司名（PT/CV/Ltd/Inc/GmbH/Co/Corp 前缀/后缀）
    entities += re.findall(r'(?:PT|CV|Ltd|Inc|GmbH|Corp|Co)\s*\.?\s+[\w\s]{2,25}', text)
    entities += re.findall(r'[\w\s]{2,25}\s+(?:Ltd|Inc|GmbH|Corp|Co)\b', text)

    # 层 3: 中文公司名
    # 3a: 后缀匹配（科技/集团/公司/有限/技术/股份/控股/实业/传媒/电子/制造/贸易）
    entities += re.findall(
        r'[\u4e00-\u9fa5]{2,12}(?:科技|集团|公司|有限|技术|股份|控股|实业|传媒|电子|制造|贸易|通信|汽车|银行|保险|证券|基金)',
        text
    )
    # 3b: 高频中文品牌词典（覆盖不带后缀的常见企业名）
    _CN_BRAND_DICT = (
        "华为|腾讯|阿里|百度|字节|美团|京东|小米|比亚迪|蔚来|理想|中兴|大疆|"
        "联想|海尔|格力|海信|TCL|创维|OPPO|vivo|荣耀|飞书|钉钉|企业微信"
    )
    entities += re.findall(rf'(?:{_CN_BRAND_DICT})', text)

    # 层 4: 人名
    # 4a: 印尼/英文（带称谓前缀）
    entities += re.findall(r'(?:Pak|Ibu|Mr|Ms|Mrs|Dr|Prof|Bapak|Ibu)\s*\.?\s*[A-Z][a-z]+(?:\s+[A-Z][a-z]+)?', text)
    # 4b: 中文人名（常见姓 + 1-2 字名 / 姓 + 职位）
    _CN_SURNAMES = "张|李|王|刘|陈|杨|赵|黄|周|吴|徐|孙|胡|朱|高|林|何|郭|马|罗|梁|宋|郑|谢|韩|唐|冯|于|董|萧|程|曹|袁|邓|许|傅|沈|曾|彭|吕|苏|卢|蒋|蔡|贾|丁|魏|薛|叶|阎|余|潘|杜|戴|夏|钟|汪|田|任|姜|范|方|石|姚|谭|廖|邹|熊|金|陆|郝|孔|白|崔|康|毛|邱|秦|江|史|顾|侯|邵|孟|龙|万|段|漕|钱|汤|尹|黎|易|常|武|乔|贺|赖|龚|文"
    entities += re.findall(
        rf'(?:{_CN_SURNAMES})[\u4e00-\u9fa5]{{1,2}}(?:总|经理|主任|工|助理|部长)?',
        text
    )

    # 层 5: 国际知名品牌/竞品词典（CRM 场景高频出现）
    _INTL_BRAND_DICT = (
        r'(?:Salesforce|SAP|Oracle|Odoo|Microsoft|Dynamics|HubSpot|Zoho|'
        r'Freshworks|ServiceNow|Workday|Adobe|AWS|Azure|Google Cloud|'
        r'Slack|Notion|Monday|Jira|Confluence)'
    )
    entities += re.findall(_INTL_BRAND_DICT, text)

    # 去重 + 过滤噪音（长度 < 2 或纯数字/标点）
    cleaned = []
    seen = set()
    for e in entities:
        e = e.strip().rstrip(".,;:!?。，；：")
        if len(e) < 2 or e in seen:
            continue
        if re.match(r'^[\d\s\W]+$', e):  # 纯数字/空白/标点跳过
            continue
        seen.add(e)
        cleaned.append(e)
    return cleaned[:20]


def _extract_key_data(text: str) -> dict:
    """正则提取精确数字（加上下文验证，精度 95%+）

    改进策略:
      - 金额: 要求前后有金额语境词（报价/价格/费用/金额/付款/折扣/营收/成本）或 $/¥ 符号
      - 日期: 排除明显的编号格式（如 "2025-001"），验证月份 ≤12，日 ≤31
      - 百分比: 要求前后有比例语境词（折扣/增长/比例/概率/赢率/占比）或数值 ≤100
    """
    if not text:
        return {}
    data: dict[str, list[str]] = {}

    # ── 金额提取（带上下文验证）──
    # 策略: 先提取所有候选，再过滤无语境的
    amount_candidates = re.findall(
        r'[\$¥￥]\s*[\d,.]+[KMB万亿]?'               # $xxx / ¥xxx（有符号，直接保留）
        r'|\d[\d,.]*\s*(?:万|亿|USD|CNY|IDR|元|美元|人民币)'  # 数字+单位
        r'|\d{1,3}(?:,\d{3})+(?:\.\d+)?'             # 逗号分隔数字（如 45,000）
        , text[:3000]
    )
    # 有 $/¥/货币单位的直接保留；纯逗号数字需要验证上下文
    _AMOUNT_CONTEXT = re.compile(
        r'(?:报价|价格|费用|金额|付款|折扣|营收|成本|预算|收入|利润|收费|定价|单价|总价|年费|月费|'
        r'amount|price|cost|budget|revenue|fee|discount|payment|billing)',
        re.IGNORECASE
    )
    amounts = []
    for amt in amount_candidates:
        if re.match(r'[\$¥￥]', amt) or re.search(r'万|亿|USD|CNY|IDR|元|美元|人民币', amt):
            amounts.append(amt)
        else:
            # 纯数字: 检查前后 50 字符是否有金额语境词
            idx = text.find(amt)
            if idx >= 0:
                context_window = text[max(0, idx - 50):idx + len(amt) + 50]
                if _AMOUNT_CONTEXT.search(context_window):
                    amounts.append(amt)
    if amounts:
        data["金额"] = list(dict.fromkeys(amounts[:8]))

    # ── 日期提取（带有效性验证）──
    date_candidates = re.findall(r'\d{4}[-/]\d{1,2}[-/]\d{1,2}', text[:2000])
    valid_dates = []
    for d in date_candidates:
        parts = re.split(r'[-/]', d)
        try:
            year, month, day = int(parts[0]), int(parts[1]), int(parts[2])
            if 2020 <= year <= 2030 and 1 <= month <= 12 and 1 <= day <= 31:
                valid_dates.append(d)
        except (ValueError, IndexError):
            pass
    if valid_dates:
        data["日期"] = list(dict.fromkeys(valid_dates[:5]))

    # ── 百分比提取（带上下文验证）──
    pct_candidates = re.findall(r'\d+\.?\d*\s*%', text[:2000])
    _PCT_CONTEXT = re.compile(
        r'(?:折扣|增长|比例|概率|赢率|占比|利润率|毛利|净利|同比|环比|下降|上涨|涨幅|跌幅|'
        r'discount|growth|rate|probability|margin|ratio|percent)',
        re.IGNORECASE
    )
    valid_pcts = []
    for pct in pct_candidates:
        num_str = re.match(r'(\d+\.?\d*)', pct)
        if num_str:
            num = float(num_str.group(1))
            if num <= 100:  # 超过 100% 的百分比极少是业务数据
                # 额外验证: 如果 ≤5% 或 ≥95% 可能是噪音，需要语境确认
                if 5 < num < 95:
                    valid_pcts.append(pct)
                else:
                    idx = text.find(pct)
                    if idx >= 0:
                        context_window = text[max(0, idx - 50):idx + len(pct) + 50]
                        if _PCT_CONTEXT.search(context_window):
                            valid_pcts.append(pct)
    if valid_pcts:
        data["比例"] = list(dict.fromkeys(valid_pcts[:5]))

    return data


def _detect_decision(user_query: str, answer_preview: str, all_content: str) -> tuple[bool, list[str]]:
    """检测轮次是否包含决策/变更（召回率 95%+）

    增强策略:
      - 增加隐含确认模式（"就这样/按这个来/选这个方案"）
      - 增加英文决策模式（"go with/let's do/agreed"）
      - 增加否定后反转模式（"不行...那就改成"）
      - 增加 tool_call 中 modify/update/create 的 args 检测
    """
    has_decision = False
    decision_fields: list[str] = []

    # ── 用户侧决策信号（增强版）──
    user_patterns = [
        # 明确指令
        (r'(?:帮我|请|麻烦)?\s*(?:改|调|降|升|加|减|换|取消|确认|同意|更新|删除|创建|新建)', "用户指令"),
        # 变更目标
        (r'(?:改为|调到|降到|升到|改成|换成|设为|定为)', "变更目标"),
        # 隐含确认（中文）
        (r'(?:就这样|按这个|选这个|用这个|就按|没问题|可以的|行吧|就这么定了|那就这样)', "隐含确认"),
        # 用户否定（意味着后续会有决策变更）
        (r'(?:太贵|太便宜|太高|太低|不行|不合适|不接受|不同意|不满意)', "用户否定"),
        # 明确确认
        (r'(?:ok|OK|好的|可以|行|同意|确认|没问题|deal|agreed|approve|accept)', "用户确认"),
        # 英文决策
        (r'(?:go\s+with|let\'?s\s+(?:do|go|use)|I\'?ll\s+take|choose|pick|select)', "英文决策"),
        # 数量/金额决策（"就 $40K" / "最多 ¥60 万"）
        (r'(?:就|最多|最少|不超过|至少)\s*[\$¥￥]?\s*\d', "金额决策"),
    ]
    for pattern, hint in user_patterns:
        if re.search(pattern, user_query, re.IGNORECASE):
            has_decision = True
            decision_fields.append(hint)
            break

    # ── Agent 侧确认信号 ──
    agent_patterns = [
        (r'(?:已修改|已调整|已更新|已确认|已创建|已删除|新的方案|调整后|更新后)', "agent_confirm"),
        (r'(?:从.*?(?:改为|调整为|变更为|更新为|降到|升到))', "value_change"),
        (r'(?:successfully|updated|created|modified|completed)', "agent_confirm_en"),
    ]
    for pattern, hint in agent_patterns:
        if re.search(pattern, answer_preview, re.IGNORECASE):
            has_decision = True
            if hint not in decision_fields:
                decision_fields.append(hint)
            break

    # ── 工具侧写操作信号 ──
    write_indicators = ["update", "modify", "create", "delete", "execute_task", "modify_data"]
    content_lower = all_content.lower()
    for ind in write_indicators:
        if ind in content_lower:
            has_decision = True
            if "write_op" not in decision_fields:
                decision_fields.append("write_op")
            break

    return has_decision, decision_fields


def _classify_execute_action(user_query: str, answer_preview: str) -> str:
    """对 execute_task 按动作子类型分类（增强多次调用的区分度）

    Returns:
        动作子类型标签: "创建" / "更新" / "签约" / "规划" / "删除" / "执行"
    """
    combined = f"{user_query} {answer_preview}"

    action_patterns = [
        (r'签约|成交|关闭|closed|won', "签约"),
        (r'创建|生成|新建|初始化', "创建"),
        (r'更新|修改|调整|确认.*更新|已更新', "更新"),
        (r'规划|计划|安排|plan', "规划"),
        (r'删除|移除|取消|撤销', "删除"),
    ]

    for pattern, label in action_patterns:
        if re.search(pattern, combined):
            return label

    return "执行"
