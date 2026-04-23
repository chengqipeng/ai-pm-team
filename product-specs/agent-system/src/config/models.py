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
    storage_dir: str = "./data/memory"
    debounce_seconds: float = 5.0
    vector_store_provider: str = "chromadb"
    vector_store_dir: str = "./data/chromadb"
    embedding_model: str = "text-embedding-3-small"


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
    tool: ToolSettings = Field(default_factory=ToolSettings)
    skills: SkillSettings = Field(default_factory=SkillSettings)
    guardrails: GuardrailSettings = Field(default_factory=GuardrailSettings)
    version: str = "1.0"
