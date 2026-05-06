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
    default_model: str = "doubao-1-5-pro-32k-250115"
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
    """知识库配置 — 腾讯云 LKEAP 文档解析 + 知识检索"""
    enabled: bool = False
    # 腾讯云 LKEAP 配置
    lkeap_secret_id: str = ""
    lkeap_secret_key: str = ""
    lkeap_region: str = "ap-guangzhou"
    # Embedding 模型
    embedding_model: str = "lke-text-embedding-v1"
    # 知识库向量数据库（独立于记忆的向量库）
    vdb_collection: str = "knowledge_chunks"


class ToolSettings(BaseModel):
    builtin_enabled: bool = True
    tools_dir: str = ""
    tool_names: list[str] = Field(default_factory=list)


class SkillSettings(BaseModel):
    skills_dir: str = ""
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
