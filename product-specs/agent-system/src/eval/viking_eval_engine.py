"""基于真实 VikingMemoryEngine 的评测引擎

替代 InMemoryEvalEngine，使用真实的向量数据库和 LLM 提取。
通过独立 collection 实现评测隔离，不污染生产数据。

设计原则：
    1. 评测使用独立的 VDB collection（eval_agent_memories）
    2. seed / clear 操作直接写入/清空 VDB
    3. retrieve 调用真实向量检索（hybrid_search）
    4. extract 调用真实 LLM 四维度提取（MemoryExtractor）
    5. 接口兼容原 InMemoryEvalEngine，无缝替换
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Any

logger = logging.getLogger(__name__)

# 评测专用的 VDB collection 名称
EVAL_COLLECTION_NAME = "eval_agent_memories"
EVAL_DATABASE_NAME = os.environ.get("TENCENT_VDB_DATABASE", "viking_memory")


class VikingEvalEngine:
    """基于真实 VikingMemoryEngine 的评测引擎

    接口兼容 InMemoryEvalEngine，可直接替换。
    所有数据写入/检索均使用真实 VDB + Embedding。
    """

    def __init__(self):
        self._memories: list[dict] = []
        self._write_log: list[dict] = []
        self._viking_engine = None
        self._initialized = False

    def _ensure_engine(self):
        """延迟初始化 VikingMemoryEngine（评测专用 collection）"""
        if self._initialized:
            return
        try:
            from src.memory.viking_engine import VikingMemoryEngine
            from langchain_openai import ChatOpenAI

            api_key = (
                os.environ.get("AGENT_API_KEY")
                or os.environ.get("DEEPSEEK_API_KEY", "")
            )
            api_base = os.environ.get(
                "AGENT_API_BASE", "https://tokenhub.tencentmaas.com/v1"
            )

            if not api_key:
                raise RuntimeError("未配置 LLM API Key (AGENT_API_KEY / DEEPSEEK_API_KEY)")

            aux_llm = ChatOpenAI(
                model=os.environ.get("AGENT_MODEL", "deepseek-v4-flash"),
                api_key=api_key,
                base_url=api_base,
                max_tokens=2048,
                temperature=0,
            )

            self._viking_engine = VikingMemoryEngine(
                vdb_url=os.environ.get("TENCENT_VDB_URL", "http://10.60.2.17"),
                vdb_key=os.environ.get(
                    "TENCENT_VDB_KEY",
                    "bRG3NETg13tv5Fn68VTdkxaJXH9tMQzhKeT3unck",
                ),
                vdb_username=os.environ.get("TENCENT_VDB_USERNAME", "root"),
                database_name=EVAL_DATABASE_NAME,
                collection_name=EVAL_COLLECTION_NAME,
                llm=aux_llm,
            )
            self._initialized = True
            logger.info(
                "VikingEvalEngine 初始化成功 (collection=%s)", EVAL_COLLECTION_NAME
            )
        except Exception as e:
            logger.error("VikingEvalEngine 初始化失败: %s", e)
            raise RuntimeError(f"VikingEvalEngine 初始化失败: {e}") from e

    def seed(self, memories: list[dict]):
        """批量写入种子数据到 VDB

        先清空评测 collection，再批量插入种子记忆。
        """
        self._ensure_engine()
        # 清空现有数据
        self.clear()

        # 本地记录
        self._memories = [m.copy() for m in memories]

        # 批量写入 VDB
        records_to_upsert = []
        for mem in memories:
            record = self._memory_to_vdb_record(mem)
            records_to_upsert.append(record)

        if records_to_upsert:
            # 分批写入，每批 20 条
            batch_size = 20
            for i in range(0, len(records_to_upsert), batch_size):
                batch = records_to_upsert[i: i + batch_size]
                try:
                    self._viking_engine._vs.upsert(batch)
                except Exception as e:
                    logger.warning("种子数据写入 VDB 失败 (batch %d): %s", i, e)

        logger.info("种子数据写入完成: %d 条", len(memories))

    def _memory_to_vdb_record(self, mem: dict) -> dict:
        """将种子记忆转为 VDB record 格式"""
        merge_key = mem.get("merge_key", "")
        category = mem.get("category", "entities")
        content = mem.get("content", "")
        abstract = mem.get("abstract", "")
        parent_entity = mem.get("parent_entity", "")

        # 生成 embedding
        vector = self._get_embedding(content or abstract)

        return {
            "id": f"eval_{merge_key}",
            "vector": vector,
            "category": category,
            "merge_key": merge_key,
            "abstract": abstract,
            "content": content,
            "parent_entity": parent_entity,
            "user_id": "eval_user",
            "tenant_id": "eval_tenant",
            "status": "active",
        }

    def _get_embedding(self, text: str) -> list[float]:
        """获取文本的 embedding 向量"""
        try:
            from src.memory.embedding import get_embedding
            return get_embedding(text)
        except Exception:
            # fallback: 使用 VikingMemoryEngine 内置的 embedding
            if self._viking_engine and hasattr(self._viking_engine, '_embedding'):
                return self._viking_engine._embedding.embed_query(text)
            # 极端 fallback: 零向量（不应到达）
            logger.warning("Embedding 获取失败，使用零向量")
            return [0.0] * 1024

    def add_memory(self, memory: dict):
        """写入单条记忆（upsert 语义）"""
        self._ensure_engine()

        merge_key = memory.get("merge_key", "")

        # 更新本地记录
        found = False
        for i, m in enumerate(self._memories):
            if m.get("merge_key") == merge_key:
                self._memories[i] = memory.copy()
                self._write_log.append({"action": "update", "memory": memory})
                found = True
                break
        if not found:
            self._memories.append(memory.copy())
            self._write_log.append({"action": "insert", "memory": memory})

        # 写入 VDB
        record = self._memory_to_vdb_record(memory)
        try:
            self._viking_engine._vs.upsert([record])
        except Exception as e:
            logger.warning("add_memory 写入 VDB 失败: %s", e)

    def retrieve(
        self,
        query: str,
        top_k: int = 5,
        category: str = None,
        parent_entity: str = None,
    ) -> list[dict]:
        """使用真实向量检索（hybrid_search）"""
        self._ensure_engine()

        try:
            # 生成查询向量
            query_vector = self._get_embedding(query)

            # 构建过滤条件
            filter_parts = ['user_id = "eval_user"', 'status = "active"']
            if category:
                filter_parts.append(f'category = "{category}"')

            filter_expr = " AND ".join(filter_parts)

            # 调用真实的 hybrid_search
            results = self._viking_engine._vs.hybrid_search(
                vector=query_vector,
                query_text=query,
                top_k=top_k,
                filter_expr=filter_expr,
            )

            # 转为标准格式
            memories = []
            for r in results:
                memories.append({
                    "merge_key": r.get("merge_key", ""),
                    "category": r.get("category", ""),
                    "parent_entity": r.get("parent_entity", ""),
                    "abstract": r.get("abstract", ""),
                    "content": r.get("content", ""),
                })

            # 如果指定了 parent_entity，做后过滤
            if parent_entity and memories:
                filtered = [
                    m for m in memories if m.get("parent_entity") == parent_entity
                ]
                if filtered:
                    return filtered[:top_k]

            return memories[:top_k]

        except Exception as e:
            logger.error("retrieve 失败: %s", e)
            return []

    def clear(self):
        """清空评测 collection 中的所有数据"""
        self._memories = []
        self._write_log = []

        if not self._initialized:
            return

        try:
            # 删除所有 eval_user 的数据
            existing = self._viking_engine._vs.query_by_filter(
                filter_expr='user_id = "eval_user"', limit=10000
            )
            if existing:
                ids_to_delete = [r.get("id") for r in existing if r.get("id")]
                if ids_to_delete:
                    # 分批删除
                    batch_size = 100
                    for i in range(0, len(ids_to_delete), batch_size):
                        batch = ids_to_delete[i: i + batch_size]
                        self._viking_engine._vs.delete(batch)
            logger.info("评测 collection 已清空")
        except Exception as e:
            logger.warning("clear 清空 VDB 失败: %s", e)

    @property
    def memory_count(self) -> int:
        return len(self._memories)

    def snapshot(self) -> list[dict]:
        """返回当前记忆库的完整快照"""
        return [m.copy() for m in self._memories]

    def get_recent_changes(self, n: int = 5) -> list[dict]:
        """获取最近 n 条写入日志"""
        return self._write_log[-n:]

    async def extract_from_utterance_llm(self, utterance: str) -> dict:
        """真实 LLM 四路并行提取 — 调用 MemoryExtractor

        返回: {"action": "extract"|"none",
               "dimensions": [...],
               "memories_written": [...],
               "raw_items": [...]}
        """
        self._ensure_engine()

        result = {
            "action": "none",
            "dimensions": [],
            "memories_written": [],
            "memories_modified": [],
            "raw_items": [],
            "errors": [],
            "duration_ms": 0.0,
        }

        if not utterance or not utterance.strip():
            return result

        try:
            from src.memory.extraction import MemoryExtractor
            from langchain_core.messages import HumanMessage

            # 构造 StateProvider
            state_provider = _VikingEvalStateProvider(self)

            extractor = MemoryExtractor(
                llm=self._viking_engine._llm, state_provider=state_provider
            )

            messages = [HumanMessage(content=utterance)]
            start = time.time()

            extraction = await extractor.extract_all(
                messages=messages,
                tenant_id="eval_tenant",
                user_id="eval_user",
                thread_id="eval_thread",
                output_language="zh",
            )

            result["duration_ms"] = (time.time() - start) * 1000
            result["errors"] = extraction.errors

            if extraction.items:
                result["action"] = "extract"
                dims = set()
                for item in extraction.items:
                    dims.add(item.dimension)
                    mem = {
                        "merge_key": item.merge_key
                        or f"llm_{item.dimension}_{len(self._memories)}",
                        "category": item.dimension,
                        "parent_entity": item.parent_entity or "",
                        "abstract": item.abstract or item.overview or "",
                        "content": item.content or utterance,
                    }
                    self.add_memory(mem)
                    result["memories_written"].append(mem)
                    result["raw_items"].append(
                        {
                            "dimension": item.dimension,
                            "slug": item.slug,
                            "abstract": item.abstract,
                            "content": item.content,
                            "merge_key": item.merge_key,
                        }
                    )
                result["dimensions"] = list(dims)
            else:
                result["action"] = "none"

        except Exception as e:
            result["errors"].append(str(e))
            logger.error("LLM extraction failed: %s", e, exc_info=True)

        return result


class _VikingEvalStateProvider:
    """评测用 StateProvider — 从 VikingEvalEngine 的当前记忆中提取已有状态"""

    def __init__(self, engine: VikingEvalEngine):
        self._engine = engine

    async def get_profile(self, tenant_id: str, user_id: str) -> str:
        profile_mems = [
            m for m in self._engine._memories if m.get("category") == "profile"
        ]
        if not profile_mems:
            return ""
        return "\n".join(m.get("content", "") for m in profile_mems)

    async def get_agent_rules(self, tenant_id: str, user_id: str) -> str:
        rules_mems = [
            m for m in self._engine._memories if m.get("category") == "agent_rules"
        ]
        if not rules_mems:
            return ""
        return "\n".join(m.get("content", "") for m in rules_mems)

    async def get_entity_index(self, tenant_id: str, user_id: str) -> str:
        entity_mems = [
            m for m in self._engine._memories if m.get("category") == "entities"
        ]
        if not entity_mems:
            return ""
        lines = []
        for m in entity_mems[:20]:
            parent = m.get("parent_entity", "")
            abstract = m.get("abstract", "")
            if parent:
                lines.append(f"[{parent}] {abstract}")
            else:
                lines.append(abstract)
        return "\n".join(lines)
