"""Mem0MemoryEngine — 基于 mem0 的记忆引擎适配器

将 mem0 的 Memory/AsyncMemory 适配为项目的 MemoryEngine 接口，
使其可以无缝接入 MemoryMiddleware。

核心映射：
  - MemoryEngine.retrieve()          → mem0 Memory.search()
  - MemoryEngine.extract_and_update() → mem0 Memory.add()
  - MemoryEngine.rewrite_query()      → 规则 fallback（mem0 无内置查询改写）
  - MemoryDimension 4维度            → mem0 metadata.dimension 字段过滤
"""
from __future__ import annotations

import json
import logging
import re
import time
from typing import Any

from ..middleware.memory import (
    MemoryEngine,
    MemoryDimension,
    MemoryItem,
    MemoryRetrievalResult,
    MemoryExtractionResult,
)

logger = logging.getLogger(__name__)

# 复用 FTSMemoryEngine 的中文停用词和实体模式（查询改写 fallback）
_STOP_WORDS = frozenset(
    "的 了 在 是 我 有 和 就 不 人 都 一 一个 上 也 很 到 说 要 去 你 会 着 没有 看 好 "
    "自己 这 他 她 它 们 那 些 什么 怎么 为什么 可以 能 吗 呢 吧 啊 哦 嗯 请 帮 帮我 "
    "一下 下 把 被 让 给 从 对 但 而 如果 因为 所以 虽然 然后 还 又 再 已经".split()
)


def _extract_keywords(text: str, max_words: int = 10) -> list[str]:
    """轻量中文关键词提取 — 用于查询改写 fallback"""
    segments = re.split(r'[，。！？、；：\s,.\?!;:\n\t]+', text)
    keywords: list[str] = []
    seen: set[str] = set()
    for seg in segments:
        seg = seg.strip()
        if not seg or len(seg) < 2 or seg in _STOP_WORDS:
            continue
        if seg not in seen:
            seen.add(seg)
            keywords.append(seg)
    return keywords[:max_words]


# ── 维度映射：项目4维度 ↔ mem0 metadata ──

_DIMENSION_TO_CATEGORY = {
    MemoryDimension.USER_PROFILE: "user_profile",
    MemoryDimension.CUSTOMER_CONTEXT: "customer_context",
    MemoryDimension.TASK_HISTORY: "task_history",
    MemoryDimension.DOMAIN_KNOWLEDGE: "domain_knowledge",
}

_CATEGORY_TO_DIMENSION = {v: k for k, v in _DIMENSION_TO_CATEGORY.items()}

# 偏好标记词（复用 FTSMemoryEngine 逻辑）
_PREFERENCE_MARKERS = [
    "我喜欢", "我习惯", "我偏好", "请用", "我需要", "我是",
    "以后都", "默认用", "不要用", "别用",
]

# CRM 实体模式
_ENTITY_PATTERNS = [
    re.compile(r'[\u4e00-\u9fff]{2,6}(?:科技|公司|集团|有限|股份|银行|保险|证券)'),
    re.compile(r'(?:account|opportunity|contact|lead|activity)\b', re.IGNORECASE),
]


class Mem0MemoryEngine(MemoryEngine):
    """基于 mem0 的记忆引擎

    Args:
        mem0_config: mem0 MemoryConfig 字典或实例，传给 mem0.Memory()
        llm: LLM 实例（用于查询改写，可选）
        custom_instructions: 自定义提取指令（注入 mem0 的 prompt 参数）
        auto_categorize: 是否自动按4维度分类存储（True 时在 metadata 中标记 dimension）
    """

    # CRM 领域结构化提取指令 — 注入 mem0 的 add(prompt=...) 参数
    # 关键：告诉 LLM 按实体拆分、提炼关键字段、标注分类标签
    _DEFAULT_CRM_INSTRUCTIONS = (
        "你正在为 CRM 系统提取结构化记忆。请严格按以下规则提取：\n\n"

        "## 提取规则\n"
        "1. 每条记忆必须是一个独立的事实，不要复述原文\n"
        "2. 每条记忆以 [分类标签] 开头，标签只能是以下之一：\n"
        "   [客户] [商机] [联系人] [合同] [活动] [偏好] [任务] [知识]\n"
        "3. 提炼关键字段，丢弃修饰语和冗余描述\n"
        "4. 金额统一用「万」为单位，日期用 YYYY-MM-DD 格式\n"
        "5. 同一个实体的不同属性拆成多条记忆\n\n"

        "## 提取示例\n"
        "对话：用户问'查一下华为的商机'，AI回复'华为科技有3个商机：ERP升级500万在谈判阶段，云迁移200万在方案阶段'\n"
        "应提取为：\n"
        "- [客户] 华为科技 — 有3个活跃商机\n"
        "- [商机] 华为科技/ERP升级项目 — 金额500万，阶段：谈判\n"
        "- [商机] 华为科技/云迁移项目 — 金额200万，阶段：方案\n\n"

        "对话：用户说'我喜欢用表格展示'，AI回复'好的'\n"
        "应提取为：\n"
        "- [偏好] 用户偏好表格展示数据\n\n"

        "对话：用户问'张总电话多少'，AI回复'张总是华为IT副总裁，电话138-0000-1234'\n"
        "应提取为：\n"
        "- [联系人] 华为科技/张总 — 职位：IT副总裁，电话：138-0000-1234\n\n"

        "## 禁止\n"
        "- 禁止复述原文（如'截至2026-04-27，字节跳动共有3个生效合同：...'）\n"
        "- 禁止包含'用户请求查询'这类操作描述\n"
        "- 禁止把多个实体合并成一条记忆"
    )

    def __init__(
        self,
        mem0_config: dict[str, Any] | None = None,
        llm: Any = None,
        custom_instructions: str | None = None,
        auto_categorize: bool = True,
        tencent_vdb_config: dict[str, Any] | None = None,
    ) -> None:
        self._llm = llm
        self._custom_instructions = custom_instructions or self._DEFAULT_CRM_INSTRUCTIONS
        self._auto_categorize = auto_categorize
        self._mem0 = self._init_mem0(mem0_config or {}, tencent_vdb_config)

    # 豆包 2.0 默认配置
    _DEFAULT_DOUBAO_CONFIG = {
        "llm": {
            "provider": "openai",
            "config": {
                "model": "doubao-seed-2-0-lite-260215",
                "api_key": None,       # 运行时从 DOUBAO_API_KEY 环境变量读取
                "openai_base_url": "https://ark.cn-beijing.volces.com/api/v3/",
                "temperature": 0.1,
                "max_tokens": 2000,
            },
        },
        "embedder": {
            "provider": "openai",
            "config": {
                "model": "doubao-embedding-text-240715",
                "api_key": None,
                "openai_base_url": "https://ark.cn-beijing.volces.com/api/v3/",
            },
        },
        "vector_store": {
            "provider": "chroma",
            "config": {
                "collection_name": "mem0_crm",
                "path": "./data/mem0_chromadb",
            },
        },
    }

    @staticmethod
    def _init_mem0(config: dict[str, Any], tencent_vdb_config: dict[str, Any] | None = None) -> Any:
        """延迟导入并初始化 mem0.Memory，默认使用豆包 2.0

        Args:
            config: mem0 MemoryConfig 字典
            tencent_vdb_config: 腾讯云向量数据库配置，非空时通过 LangChain 桥接
                {
                    "url": "http://your-vdb-instance.tencentcloudapi.com",
                    "key": "your-api-key",
                    "username": "root",
                    "database_name": "mem0_db",
                    "collection_name": "mem0_memories",
                    "timeout": 30,
                }
        """
        import os

        try:
            from mem0 import Memory
            from mem0.configs.base import MemoryConfig
        except ImportError:
            raise ImportError(
                "mem0 未安装。请执行: pip install mem0ai\n"
                "或在 pyproject.toml 中添加 mem0ai 依赖。"
            )

        # 如果没有传入配置，使用豆包 2.0 默认配置
        if not config:
            config = Mem0MemoryEngine._build_doubao_config()

        # 自动注入 API key（从环境变量）
        config = Mem0MemoryEngine._inject_api_keys(config)

        # 腾讯云向量数据库：通过 LangChain provider 桥接
        post_init_patch = None
        if tencent_vdb_config:
            config, post_init_patch = Mem0MemoryEngine._apply_tencent_vdb(config, tencent_vdb_config)

        mem0_cfg = MemoryConfig(**config)
        mem0_instance = Memory(config=mem0_cfg)

        # 应用 post-init patch（修复 score 兼容性）
        if post_init_patch:
            post_init_patch(mem0_instance)

        return mem0_instance

    @staticmethod
    def _apply_tencent_vdb(config: dict[str, Any], vdb_config: dict[str, Any]) -> dict[str, Any]:
        """将腾讯云向量数据库配置注入 mem0 config（通过 LangChain 桥接）

        使用 langchain_community.vectorstores.TencentVectorDB 作为 mem0 的向量存储后端。
        需要安装: pip install tcvectordb langchain-community
        """
        try:
            from langchain_community.vectorstores import TencentVectorDB
            from langchain_community.vectorstores.tencentvectordb import ConnectionParams, IndexParams
            from langchain_openai import OpenAIEmbeddings
        except ImportError:
            raise ImportError(
                "腾讯云向量数据库依赖未安装。请执行:\n"
                "  pip install tcvectordb langchain-community langchain-openai"
            )

        import os
        api_key = os.environ.get("DOUBAO_API_KEY", "651621e7-e495-4728-93ef-ed380e9ddcd1")

        # 构建 embedding 模型（用于 LangChain VectorStore 初始化）
        # 注意：豆包 embedding API 不支持 token 数组输入，必须禁用 tiktoken
        emb_cfg = config.get("embedder", {}).get("config", {})
        embedding = OpenAIEmbeddings(
            model=emb_cfg.get("model", "doubao-embedding-text-240715"),
            api_key=emb_cfg.get("api_key") or api_key,
            base_url=emb_cfg.get("openai_base_url", "https://ark.cn-beijing.volces.com/api/v3/"),
            check_embedding_ctx_length=False,  # 禁用 tiktoken 分词，直接发送原始字符串
        )

        # 获取 embedding 维度（doubao-embedding-text-240715 = 2560）
        embedding_dims = vdb_config.get("embedding_dims", 2560)

        # 构建腾讯云向量数据库连接
        conn_params = ConnectionParams(
            url=vdb_config["url"],
            key=vdb_config["key"],
            username=vdb_config.get("username", "root"),
            timeout=vdb_config.get("timeout", 30),
        )

        index_params = IndexParams(dimension=embedding_dims, metric_type="COSINE")

        tencent_vdb = TencentVectorDB(
            embedding=embedding,
            connection_params=conn_params,
            index_params=index_params,
            database_name=vdb_config.get("database_name", "mem0_db"),
            collection_name=vdb_config.get("collection_name", "mem0_memories"),
        )

        # ── 核心兼容性修复 ──
        # 问题：mem0 的 Langchain wrapper 调用 similarity_search_by_vector → translate_filter（lark parser）
        #       → lark 不兼容 mem0 传入的 dict filter → crash
        # 同时 LangChain TencentVectorDB 的 similarity_search_by_vector 不返回 score → score=None
        #
        # 解决方案：直接 patch mem0 的 Langchain.search()，用 tcvectordb SDK 原生 API 搜索，
        #          绕过 LangChain 的 translate_filter，同时获取 score

        # 保存 tcvectordb collection 引用，供 patch 使用
        _tencent_collection = tencent_vdb.collection
        _tencent_embedding = embedding

        def _patch_mem0_langchain_search(mem0_instance):
            """Patch mem0 的 vector_store.search，用 tcvectordb 原生 API 替代 LangChain 搜索"""
            vs = mem0_instance.vector_store

            def _native_search(query, vectors, top_k=5, filters=None):
                from mem0.vector_stores.langchain import OutputData

                try:
                    result = _tencent_collection.search(
                        vectors=[vectors],
                        limit=top_k * 3,
                    )

                    parsed = []
                    for doc_list in result:
                        for doc in doc_list:
                            # tcvectordb 返回 dict: {"id": "...", "score": 0.88, "text": "..."}
                            if isinstance(doc, dict):
                                doc_id = doc.get("id", "")
                                doc_score = doc.get("score", 0.5)
                                doc_text = doc.get("text", "")
                            else:
                                doc_id = getattr(doc, "id", "") or ""
                                doc_score = getattr(doc, "score", 0.5) or 0.5
                                doc_text = ""
                                if hasattr(doc, "fields") and doc.fields:
                                    doc_text = doc.fields.get("text", "")

                            if not doc_text:
                                continue

                            # 构建 payload，确保 data 字段存在（mem0 必需）
                            payload = {"data": doc_text, "text": doc_text}

                            # 应用层 filter（tcvectordb 的 metadata 不在搜索结果中，跳过 filter）
                            # mem0 的 user_id filter 在写入时已通过 LangChain metadata 存储，
                            # 但 tcvectordb search 不返回 metadata，所以这里无法过滤
                            # 实际生产中应为每个 user 创建独立 collection 来隔离

                            parsed.append(OutputData(
                                id=str(doc_id),
                                score=float(doc_score) if doc_score is not None else 0.5,
                                payload=payload,
                            ))

                    return parsed[:top_k]

                except Exception as e:
                    logger.warning("Native tcvectordb search failed: %s, returning empty", e)
                    return []

            vs.search = _native_search

        # 替换 config 中的 vector_store 为 langchain provider
        config["vector_store"] = {
            "provider": "langchain",
            "config": {
                "client": tencent_vdb,
                "collection_name": vdb_config.get("collection_name", "mem0_memories"),
            },
        }

        logger.info(
            "Mem0 向量存储已切换为腾讯云 VectorDB (url=%s, db=%s, collection=%s)",
            vdb_config["url"],
            vdb_config.get("database_name", "mem0_db"),
            vdb_config.get("collection_name", "mem0_memories"),
        )

        return config, _patch_mem0_langchain_search

    @staticmethod
    def _build_doubao_config() -> dict[str, Any]:
        """构建豆包 2.0 默认配置"""
        import copy
        return copy.deepcopy(Mem0MemoryEngine._DEFAULT_DOUBAO_CONFIG)

    @staticmethod
    def _inject_api_keys(config: dict[str, Any]) -> dict[str, Any]:
        """从环境变量注入 API key — 与项目其他模块保持一致

        项目在 server.py / run_server.py 中已通过 os.environ.setdefault
        设置了 DOUBAO_API_KEY 默认值，这里直接读取。
        """
        import os

        api_key = os.environ.get("DOUBAO_API_KEY", "651621e7-e495-4728-93ef-ed380e9ddcd1")

        # 注入 LLM api_key
        llm_cfg = config.get("llm", {}).get("config", {})
        if not llm_cfg.get("api_key"):
            llm_cfg["api_key"] = api_key

        # 注入 Embedder api_key
        emb_cfg = config.get("embedder", {}).get("config", {})
        if not emb_cfg.get("api_key"):
            emb_cfg["api_key"] = api_key

        return config

    # ── MemoryEngine 接口实现 ──

    async def rewrite_query(self, messages: list, current_query: str,
                            tenant_id: str | None = None) -> str:
        """查询改写 — LLM优先，规则fallback

        mem0 本身不提供查询改写能力，这里复用 FTSMemoryEngine 的策略。
        """
        if self._llm is not None:
            try:
                return await self._llm_rewrite(messages, current_query)
            except Exception as e:
                logger.warning("Mem0Engine: LLM rewrite failed, fallback: %s", e)

        # 规则 fallback
        all_text = current_query
        for msg in reversed(messages[-6:]):
            msg_type = getattr(msg, "type", "")
            content = getattr(msg, "content", "")
            if msg_type == "human" and isinstance(content, str) and content.strip():
                all_text += " " + content

        keywords = _extract_keywords(all_text)
        return " ".join(keywords) if keywords else current_query

    async def _llm_rewrite(self, messages: list, current_query: str) -> str:
        """LLM 查询改写"""
        context_lines: list[str] = []
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
            "你是一个查询改写助手。根据多轮对话上下文，将用户最新问题改写为"
            "适合语义搜索的查询。\n\n"
            "要求：提取核心实体名和业务概念，解析代词指代，"
            "输出一句自然语言查询（不超过50字）。\n\n"
            "对话上下文：\n" + "\n".join(context_lines) + "\n\n"
            f"当前问题：{current_query}\n\n"
            "改写后的查询："
        )
        result = await self._llm.ainvoke(prompt)
        rewritten = getattr(result, "content", None) or str(result)
        rewritten = rewritten.strip()
        if len(rewritten) > 100:
            keywords = _extract_keywords(rewritten)
            return " ".join(keywords[:10]) if keywords else current_query
        return rewritten

    async def retrieve(
        self,
        query: str,
        dimensions: list[MemoryDimension] | None = None,
        tenant_id: str | None = None,
        user_id: str | None = None,
        top_k: int = 5,
    ) -> MemoryRetrievalResult:
        """检索记忆 — 调用 mem0 search + 维度过滤 + 时间衰减"""
        import asyncio

        uid = user_id or "default"
        now = time.time()

        # mem0 search（在线程池中执行，因为 mem0 Memory.search 是同步的）
        try:
            raw_results = await asyncio.to_thread(
                self._mem0.search,
                query=query,
                top_k=top_k * 3,  # over-fetch，后续按维度过滤
                filters={"user_id": uid},
            )
        except Exception as e:
            logger.error("Mem0 search failed: %s", e)
            return MemoryRetrievalResult(query_used=query)

        results_list = raw_results.get("results", [])
        items: list[MemoryItem] = []
        target_dims = set(d.value for d in (dimensions or list(MemoryDimension)))

        for r in results_list:
            memory_text = r.get("memory", "")
            score = r.get("score", 0.5)
            metadata = r.get("metadata", {}) or {}
            dim_value = metadata.get("dimension", "")

            # 维度过滤
            if dim_value and dim_value not in target_dims:
                continue

            # 如果没有维度标记，尝试推断
            dimension = self._infer_dimension(dim_value, memory_text)

            # 时间衰减（如果有 created_at）
            created_at = r.get("created_at") or metadata.get("created_at")
            if created_at:
                try:
                    from datetime import datetime, timezone
                    if isinstance(created_at, str):
                        dt = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
                        created_ts = dt.timestamp()
                    else:
                        created_ts = float(created_at)
                    days_ago = (now - created_ts) / 86400
                    time_decay = max(0.1, 1.0 - days_ago * 0.01)  # 100天衰减到0.1
                    score *= time_decay
                except (ValueError, TypeError):
                    pass

            items.append(MemoryItem(
                dimension=dimension,
                content=memory_text,
                confidence=score,
                metadata=metadata,
            ))

        # 按 confidence 排序，取 top_k
        items.sort(key=lambda x: x.confidence, reverse=True)
        return MemoryRetrievalResult(items=items[:top_k], query_used=query)

    async def extract_and_update(
        self,
        messages: list,
        thread_id: str,
        tenant_id: str | None = None,
        user_id: str | None = None,
    ) -> MemoryExtractionResult:
        """从对话中提取记忆 — 三层过滤 + mem0 add + 自动维度分类

        第一层：预过滤（代码规则，不调 LLM）— 判断这轮对话是否值得提取
        第二层：LLM 结构化提取（custom_instructions 控制）
        第三层：后处理分类 + 质量过滤
        """
        import asyncio

        uid = user_id or "default"
        extracted: list[MemoryItem] = []

        # ── 第一层：预过滤 — 判断是否值得提取 ──
        if not self._should_extract(messages):
            logger.debug("Mem0Engine: skipped extraction (pre-filter)")
            return MemoryExtractionResult(source_thread_id=thread_id)

        # 构建 mem0 消息格式
        mem0_messages = self._convert_messages(messages)
        if not mem0_messages:
            return MemoryExtractionResult(source_thread_id=thread_id)

        # ── 第二层：LLM 结构化提取（mem0 add）──
        try:
            result = await asyncio.to_thread(
                self._mem0.add,
                messages=mem0_messages,
                user_id=uid,
                metadata={"thread_id": thread_id},
                prompt=self._custom_instructions,
            )
        except Exception as e:
            logger.error("Mem0 add failed: %s", e)
            return MemoryExtractionResult(source_thread_id=thread_id)

        added_memories = result.get("results", [])

        # ── 第三层：后处理分类 + 质量过滤 ──
        if self._auto_categorize and added_memories:
            for mem in added_memories:
                memory_text = mem.get("memory", "")
                memory_id = mem.get("id", "")

                # 质量过滤：丢弃低质量记忆
                if not self._is_quality_memory(memory_text):
                    logger.debug("Mem0Engine: filtered low-quality memory: %s", memory_text[:50])
                    continue

                dimension = self._classify_dimension(memory_text, mem0_messages)

                # 更新 mem0 中的 metadata（添加 dimension 标记）
                try:
                    await asyncio.to_thread(
                        self._mem0.update,
                        memory_id=memory_id,
                        data=memory_text,
                        metadata={
                            "dimension": dimension.value,
                            "thread_id": thread_id,
                        },
                    )
                except Exception as e:
                    logger.debug("Mem0 metadata update failed for %s: %s", memory_id, e)

                extracted.append(MemoryItem(
                    dimension=dimension,
                    content=memory_text,
                    metadata={"mem0_id": memory_id, "thread_id": thread_id},
                ))

        logger.info(
            "Mem0Engine: extracted %d memories from thread %s",
            len(extracted), thread_id,
        )
        return MemoryExtractionResult(items=extracted, source_thread_id=thread_id)

    # ── 辅助方法 ──

    @staticmethod
    def _convert_messages(messages: list) -> list[dict[str, str]]:
        """将 LangChain Message 对象转为 mem0 消息格式"""
        converted: list[dict[str, str]] = []
        for msg in messages[-10:]:  # 最近10条
            msg_type = getattr(msg, "type", "")
            content = getattr(msg, "content", "")
            if not isinstance(content, str) or not content.strip():
                continue
            if msg_type == "human":
                converted.append({"role": "user", "content": content})
            elif msg_type == "ai" and content.strip():
                converted.append({"role": "assistant", "content": content})
        return converted

    # ── 第一层：预过滤规则 ──

    # 不值得提取记忆的对话模式
    _SKIP_PATTERNS = [
        # 寒暄
        "你好", "您好", "hi", "hello", "hey", "在吗",
        # 纯确认
        "好的", "ok", "是的", "对", "嗯", "收到", "明白", "了解",
        # 感谢
        "谢谢", "感谢", "thanks", "thank you",
        # 告别
        "再见", "拜拜", "bye",
    ]

    @classmethod
    def _should_extract(cls, messages: list) -> bool:
        """预过滤：判断这轮对话是否值得提取记忆

        跳过条件：
        1. 纯寒暄/确认/感谢（无业务信息）
        2. 只有用户消息没有 AI 回复（对话未完成）
        3. AI 回复太短（<50字，通常是确认或追问）
        4. 工具调用失败（ToolMessage status=error）
        """
        last_human = ""
        last_ai = ""
        has_tool_error = False
        has_tool_success = False

        for msg in reversed(messages):
            msg_type = getattr(msg, "type", "")
            content = getattr(msg, "content", "")
            if not isinstance(content, str):
                content = str(content) if content else ""

            if msg_type == "human" and not last_human:
                last_human = content.strip()
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

        # 条件 1：纯寒暄/确认
        if last_human and last_human.lower() in [p.lower() for p in cls._SKIP_PATTERNS]:
            return False

        # 条件 2：没有 AI 回复
        if not last_ai:
            return False

        # 条件 3：AI 回复太短（通常是追问或确认）
        if len(last_ai) < 50:
            return False

        # 条件 4：只有工具错误没有成功（查询失败，无有效数据）
        if has_tool_error and not has_tool_success:
            return False

        return True

    # ── 第三层：质量过滤规则 ──

    # 低质量记忆的特征模式
    _LOW_QUALITY_PATTERNS = [
        "用户请求查询", "用户发起查询", "用户询问", "用户要求",  # 操作描述，不是事实
        "截至20", "截止20",  # 原文复述的时间前缀
        "以上是", "以下是", "如下所示",  # 格式化前缀
    ]

    @classmethod
    def _is_quality_memory(cls, text: str) -> bool:
        """质量过滤：判断提取出的记忆是否值得保留

        过滤条件：
        1. 太短（<10字）— 信息量不足
        2. 太长（>200字）— 可能是原文复述
        3. 包含操作描述模式 — 不是事实性记忆
        4. 纯数字/标点 — 无意义
        """
        text = text.strip()

        # 去掉 [标签] 前缀后判断长度
        clean = text
        if clean.startswith("[") and "]" in clean:
            clean = clean[clean.index("]") + 1:].strip()

        # 条件 1：太短
        if len(clean) < 10:
            return False

        # 条件 2：太长（可能是原文复述）
        if len(clean) > 200:
            return False

        # 条件 3：操作描述模式
        for pattern in cls._LOW_QUALITY_PATTERNS:
            if clean.startswith(pattern):
                return False

        # 条件 4：纯数字/标点
        if all(c.isdigit() or c in ".,;:!?，。；：！？- " for c in clean):
            return False

        return True

    @staticmethod
    def _infer_dimension(dim_value: str, text: str) -> MemoryDimension:
        """从 metadata 或文本内容推断维度"""
        if dim_value and dim_value in _CATEGORY_TO_DIMENSION:
            return _CATEGORY_TO_DIMENSION[dim_value]

        # 基于内容启发式推断
        for marker in _PREFERENCE_MARKERS:
            if marker in text:
                return MemoryDimension.USER_PROFILE

        for pattern in _ENTITY_PATTERNS:
            if pattern.search(text):
                return MemoryDimension.CUSTOMER_CONTEXT

        if any(kw in text for kw in ("问:", "答:", "使用工具:", "查询", "分析")):
            return MemoryDimension.TASK_HISTORY

        return MemoryDimension.DOMAIN_KNOWLEDGE

    @classmethod
    def _classify_dimension(cls, memory_text: str, messages: list[dict]) -> MemoryDimension:
        """对提取出的记忆进行4维度分类

        优先识别 LLM 输出的 [分类标签] 前缀（如 [客户]、[商机]），
        fallback 到关键词匹配。
        """
        text = memory_text.strip()
        text_lower = text.lower()

        # ── 优先：识别 [分类标签] 前缀 ──
        _TAG_TO_DIMENSION = {
            "[客户]": MemoryDimension.CUSTOMER_CONTEXT,
            "[商机]": MemoryDimension.CUSTOMER_CONTEXT,
            "[联系人]": MemoryDimension.CUSTOMER_CONTEXT,
            "[合同]": MemoryDimension.CUSTOMER_CONTEXT,
            "[活动]": MemoryDimension.CUSTOMER_CONTEXT,
            "[偏好]": MemoryDimension.USER_PROFILE,
            "[任务]": MemoryDimension.TASK_HISTORY,
            "[知识]": MemoryDimension.DOMAIN_KNOWLEDGE,
        }
        for tag, dim in _TAG_TO_DIMENSION.items():
            if text.startswith(tag):
                return dim

        # ── fallback：关键词匹配 ──

        # 用户偏好
        for marker in _PREFERENCE_MARKERS:
            if marker in text:
                return MemoryDimension.USER_PROFILE
        if any(kw in text_lower for kw in ("偏好", "喜欢", "习惯", "prefer", "style")):
            return MemoryDimension.USER_PROFILE

        # 客户/实体上下文
        for pattern in _ENTITY_PATTERNS:
            if pattern.search(text):
                return MemoryDimension.CUSTOMER_CONTEXT
        if any(kw in text_lower for kw in ("客户", "商机", "联系人", "合同", "pipeline", "金额", "阶段")):
            return MemoryDimension.CUSTOMER_CONTEXT

        # 任务历史
        if any(kw in text_lower for kw in ("查询了", "分析了", "创建了", "修改了", "删除了", "执行了")):
            return MemoryDimension.TASK_HISTORY

        return MemoryDimension.DOMAIN_KNOWLEDGE

    # ── 面向 Agent 的记忆管理 ──

    def list_memories(self, user_id: str, keyword: str = "",
                      dimension: str | None = None, limit: int = 20) -> list[dict]:
        """列出用户记忆"""
        uid = user_id or "default"
        filters: dict[str, Any] = {"user_id": uid}
        if dimension:
            filters["dimension"] = dimension

        try:
            result = self._mem0.get_all(filters=filters, top_k=limit)
            memories = result.get("results", [])
            if keyword:
                memories = [m for m in memories if keyword in m.get("memory", "")]
            return [
                {
                    "id": m.get("id", ""),
                    "content": m.get("memory", ""),
                    "dimension": (m.get("metadata") or {}).get("dimension", ""),
                    "created_at": m.get("created_at", ""),
                }
                for m in memories
            ]
        except Exception as e:
            logger.error("Mem0 list_memories failed: %s", e)
            return []

    def delete_memories_by_ids(self, ids: list[str]) -> int:
        """按 ID 删除记忆"""
        deleted = 0
        for mid in ids:
            try:
                self._mem0.delete(memory_id=mid)
                deleted += 1
            except Exception as e:
                logger.warning("Mem0 delete failed for %s: %s", mid, e)
        return deleted

    def clear_all_memories(self, user_id: str) -> int:
        """清空用户所有记忆"""
        uid = user_id or "default"
        try:
            self._mem0.delete_all(user_id=uid)
            logger.info("Mem0: cleared all memories for user %s", uid)
            return 1
        except Exception as e:
            logger.error("Mem0 clear_all failed: %s", e)
            return 0
