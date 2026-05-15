"""配置数据模型 — Pydantic BaseModel"""
from __future__ import annotations

from typing import Any
from pydantic import BaseModel, Field


class AppSettings(BaseModel):
    name: str = "deepagent"
    debug: bool = False
    log_level: str = "INFO"
    host: str = "0.0.0.0"
    port: int = 8001


class ProviderConfig(BaseModel):
    api_key: str = ""
    api_base: str = ""
    extra: dict[str, Any] = Field(default_factory=dict)


class ModelSettings(BaseModel):
    default_model: str = "doubao-seed-2-0-lite-260215"
    default_api_key: str = "651621e7-e495-4728-93ef-ed380e9ddcd1"
    default_api_base: str = "https://ark.cn-beijing.volces.com/api/v3/"
    providers: dict[str, ProviderConfig] = Field(default_factory=dict)


class MemorySettings(BaseModel):
    enabled: bool = True
    engine: str = "fts"  # "fts" | "mem0"
    storage_dir: str = "./data/memory"
    debounce_seconds: float = 5.0
    vector_store_provider: str = "chromadb"
    vector_store_dir: str = "./data/chromadb"
    embedding_model: str = "text-embedding-3-small"
    # mem0 专用配置（默认使用豆包 2.0）
    mem0_config: dict[str, Any] = Field(default_factory=dict)
    mem0_custom_instructions: str = ""
    mem0_model: str = "doubao-seed-2-0-lite-260215"
    mem0_embedding_model: str = "doubao-embedding-text-240715"
    # 腾讯云向量数据库配置（mem0 通过 LangChain 桥接）
    tencent_vdb_url: str = ""
    tencent_vdb_key: str = ""
    tencent_vdb_username: str = "root"
    tencent_vdb_database: str = "mem0_db"
    tencent_vdb_collection: str = "mem0_memories"


class KnowledgeSettings(BaseModel):
    """知识库配置 — 腾讯云 LKEAP 文档解析 + 知识检索 + PG 任务队列

    所有凭证默认硬编码在此；需要替换时直接改这里（或在构造时覆盖）。
    Secret 以 base64 形式存储，运行时由 lkeap_client._maybe_decode_base64 解码。
    """
    enabled: bool = True

    # ── 腾讯云 LKEAP 配置（base64 编码，使用时自动解码）──
    lkeap_secret_id: str = "QUtJRHVnVkZzTnNIZjJKVVlSSjJlOGMyVHlPaHYyNzk0cVR6"
    lkeap_secret_key: str = "VG13endnQ3hkQVdxMzh6cWFCZjFCQjZ4Zko0bk5qdTc="
    lkeap_region: str = "ap-guangzhou"

    # ── Embedding 模型 ──
    embedding_model: str = "lke-text-embedding-v1"
    embedding_dim: int = 1024

    # ── 腾讯云向量数据库（单库多租户，tenant_id 字段隔离） ──
    vdb_url: str = "http://10.60.2.17"
    vdb_key: str = "bRG3NETg13tv5Fn68VTdkxaJXH9tMQzhKeT3unck"
    vdb_username: str = "root"
    vdb_database: str = "knowledge"
    vdb_chunk_collection: str = "kb_chunks"
    vdb_doc_metadata_collection: str = "kb_doc_metadata"

    # ── 腾讯云 COS 对象存储（文件上传后持久化到 COS，URL 存 PG） ──
    cos_secret_id: str = ""       # 通过环境变量 COS_SECRET_ID 注入
    cos_secret_key: str = ""      # 通过环境变量 COS_SECRET_KEY 注入
    cos_bucket: str = "domainverify-1253467224"
    cos_region: str = "ap-beijing"
    cos_key_prefix: str = "knowledge/"   # COS 对象 key 前缀

    # ── 本地文件存储 ──
    upload_dir: str = "./data/knowledge/uploads"      # 原始上传文件
    parsed_dir: str = "./data/knowledge/parsed"       # LKEAP 解析产物

    # ── BM25 倒排（复用 MemoryStorage 的 SQLite FTS5） ──
    bm25_dimension_prefix: str = "kb_"                # 最终为 kb_{knowledge_base_id}

    # ── 检索参数默认值 ──
    default_top_k: int = 5
    rerank_top_k: int = 10
    rrf_k: int = 60
    expand_context_n: int = 1
    enable_self_query: bool = True
    enable_rerank: bool = True
    enable_query_rewrite: bool = False

    # ── 入库 Worker ──
    # LKEAP 连接池硬限制 = 10，需严格控制并发避免连接池耗尽导致卡死
    # 每个 Worker 串行处理任务，embedding 阶段内部 2 并发
    # 总连接占用 ≈ worker_count × (1 parse + 2 embed) = 2 × 3 = 6，安全
    ingest_worker_count: int = 2        # 2 个 Worker 协程
    ingest_batch_size: int = 1          # 每次出队 1 个任务，串行处理
    ingest_poll_interval_ms: int = 500
    lkeap_concurrency: int = 4          # LKEAP 解析并发信号量（保护 parse 阶段）
    reclaim_interval_ms: int = 30000
    vector_max_retry: int = 5


class ToolSettings(BaseModel):
    builtin_enabled: bool = True
    tools_dir: str = ""
    tool_names: list[str] = Field(default_factory=list)


class SkillSettings(BaseModel):
    skills_dir: str = ""  # 已废弃，保留兼容。Skill 唯一数据源为 ai_skill_definition 表
    skill_names: list[str] = Field(default_factory=list)
    auto_generate: bool = False
    min_tool_calls_for_autogen: int = 5


class GuardrailSettings(BaseModel):
    enabled: bool = True
    allowed_tools: list[str] = Field(default_factory=list)


class AppConfig(BaseModel):
    """应用顶层配置"""
    app: AppSettings = Field(default_factory=AppSettings)
    model: ModelSettings = Field(default_factory=ModelSettings)
    memory: MemorySettings = Field(default_factory=MemorySettings)
    knowledge: KnowledgeSettings = Field(default_factory=KnowledgeSettings)
    tool: ToolSettings = Field(default_factory=ToolSettings)
    skills: SkillSettings = Field(default_factory=SkillSettings)
    guardrails: GuardrailSettings = Field(default_factory=GuardrailSettings)
    version: str = "1.0"
