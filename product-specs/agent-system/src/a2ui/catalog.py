"""A2UI Catalog — 组件目录定义、注册与协商

对齐规范：v0.8 §2.1 Catalog Negotiation
- Agent Card 声明 `supportedCatalogIds` + `acceptsInlineCatalogs`
- 客户端消息 metadata 带 `a2uiClientCapabilities`
- Agent 通过 `beginRendering.catalogId` 选定该 surface 使用的 catalog

对齐 apps-agent 实现：
- 支持从 `resources/a2ui/components/*.json` 加载组件元数据
- 组件 JSON 扩展 `skill_bindings`（bind/prefer）和 `supported_model_names`
- 这些元数据被 `ComponentMatcherV2` 消费，实现 5 层匹配

典型用法：

    registry = CatalogRegistry()
    registry.register_standard()
    registry.load_from_dir(Path("./resources/a2ui/components"))
    chosen = registry.negotiate(
        client_supported=["std-v08", "viking.crm-v1"],
        client_inline=None,
        accepts_inline=False,
    )
    # chosen → 服务端可用 & 客户端能渲染的 catalog id
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════
# CatalogDefinition
# ═══════════════════════════════════════════════════════════

# A2UI v0.8 官方标准 catalog id
STANDARD_V08 = "https://a2ui.org/specification/v0_8/standard_catalog_definition.json"

# 本项目 CRM 业务 catalog id（示例）
VIKING_CRM_V1 = "https://viking.tencent.com/a2ui/crm-v1.json"


@dataclass
class ComponentMeta:
    """单个组件的元数据（从 resources/a2ui/components/*.json 加载）。

    字段设计对齐 apps-agent `service/agent_agui/components/*.json`：
    - type: 组件标识（前端 Registry 查找 key）
    - description: LLM 上下文
    - input_schema: props schema（用于 schema 匹配）
    - skill_bindings: {bind: [...], prefer: [...]} 静态绑定
    - supported_model_names: 该组件能消费的 ModelName 类型
    """
    type: str
    description: str = ""
    input_schema: dict[str, Any] = field(default_factory=dict)
    skill_bindings: dict[str, list[str]] = field(default_factory=dict)
    supported_model_names: list[str] = field(default_factory=list)
    # 可选：样式 / 子组件 schema 等扩展字段
    extra: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> "ComponentMeta":
        type_name = data.get("type") or data.get("name") or ""
        if not type_name:
            raise ValueError(f"Component JSON missing 'type' field: {data!r}")
        return cls(
            type=type_name,
            description=data.get("description", ""),
            input_schema=data.get("input_schema") or data.get("schema") or {},
            skill_bindings=data.get("skill_bindings") or {},
            supported_model_names=data.get("supported_model_names") or [],
            extra={k: v for k, v in data.items() if k not in {
                "type", "name", "description", "input_schema", "schema",
                "skill_bindings", "supported_model_names",
            }},
        )

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "type": self.type,
            "description": self.description,
            "input_schema": self.input_schema,
        }
        if self.skill_bindings:
            out["skill_bindings"] = self.skill_bindings
        if self.supported_model_names:
            out["supported_model_names"] = self.supported_model_names
        if self.extra:
            out.update(self.extra)
        return out


@dataclass
class CatalogDefinition:
    """单个 catalog 定义（v0.8 §2.1）。"""
    catalog_id: str
    components: dict[str, ComponentMeta] = field(default_factory=dict)
    styles: dict[str, dict] = field(default_factory=dict)

    def register(self, meta: ComponentMeta) -> None:
        if meta.type in self.components:
            logger.warning("Catalog %s: component %s already registered, overriding",
                           self.catalog_id, meta.type)
        self.components[meta.type] = meta

    def get(self, type_name: str) -> ComponentMeta | None:
        return self.components.get(type_name)

    def list_components(self) -> list[ComponentMeta]:
        return list(self.components.values())

    def to_dict(self) -> dict[str, Any]:
        return {
            "catalogId": self.catalog_id,
            "components": {t: m.to_dict() for t, m in self.components.items()},
            "styles": dict(self.styles),
        }


# ═══════════════════════════════════════════════════════════
# CatalogRegistry — 服务端注册表 + 协商
# ═══════════════════════════════════════════════════════════

class CatalogRegistry:
    """管理服务端已知的 catalog 集合。"""

    STANDARD_V08 = STANDARD_V08

    def __init__(self) -> None:
        self._catalogs: dict[str, CatalogDefinition] = {}
        self._default_catalog_id: str | None = None

    # ── 注册 ──

    def register(self, catalog: CatalogDefinition) -> None:
        if catalog.catalog_id in self._catalogs:
            logger.warning("Catalog %s already registered, overriding", catalog.catalog_id)
        self._catalogs[catalog.catalog_id] = catalog

    def register_standard(self) -> CatalogDefinition:
        """注册 A2UI v0.8 标准 catalog 的空骨架（具体组件由前端内置提供）。"""
        std = CatalogDefinition(catalog_id=STANDARD_V08)
        # 标准 catalog 的 18 个基础组件（前端 v0.8 客户端已内置实现）
        for ct in [
            "Text", "Image", "Icon", "Divider", "Video", "AudioPlayer",
            "Row", "Column", "List", "Card", "Tabs", "Modal",
            "Button", "TextField", "CheckBox", "Slider", "DateTimeInput", "MultipleChoice",
        ]:
            std.register(ComponentMeta(type=ct, description=f"A2UI v0.8 standard {ct}"))
        self.register(std)
        if self._default_catalog_id is None:
            self._default_catalog_id = STANDARD_V08
        return std

    def load_from_dir(self, directory: str | os.PathLike, catalog_id: str) -> CatalogDefinition:
        """从目录扫描组件 JSON 文件，全部挂到同一 catalog 下。"""
        path = Path(directory)
        catalog = self._catalogs.get(catalog_id) or CatalogDefinition(catalog_id=catalog_id)
        if not path.is_dir():
            logger.warning("Catalog dir not found: %s", path)
            self.register(catalog)
            return catalog
        count = 0
        for fp in sorted(path.glob("*.json")):
            try:
                data = json.loads(fp.read_text(encoding="utf-8"))
            except Exception:
                logger.warning("Failed to load catalog component %s", fp, exc_info=True)
                continue
            try:
                meta = ComponentMeta.from_json(data)
            except ValueError as exc:
                logger.warning("Invalid component JSON %s: %s", fp, exc)
                continue
            catalog.register(meta)
            count += 1
        logger.info("Catalog %s: loaded %d components from %s", catalog_id, count, path)
        self.register(catalog)
        return catalog

    def set_default(self, catalog_id: str) -> None:
        if catalog_id not in self._catalogs:
            raise ValueError(f"Unknown catalog_id: {catalog_id}")
        self._default_catalog_id = catalog_id

    # ── 查询 ──

    def get(self, catalog_id: str) -> CatalogDefinition | None:
        return self._catalogs.get(catalog_id)

    def supported_ids(self) -> list[str]:
        return list(self._catalogs.keys())

    def default_id(self) -> str:
        return self._default_catalog_id or STANDARD_V08

    # ── 协商（v0.8 §2.1）──

    def negotiate(
        self,
        client_supported: list[str] | None = None,
        client_inline: list[dict] | None = None,
        *,
        accepts_inline: bool = False,
    ) -> str:
        """根据客户端能力选择 catalog id。

        优先级：
        1. 客户端 inline catalog（仅当 accepts_inline=True）
        2. 服务端 default catalog 若在客户端支持列表
        3. 双方交集里的第一个（排序稳定）
        4. 标准 catalog 兜底
        """
        client_supported = client_supported or []

        # 1. inline catalog（本地开发用，生产默认关闭）
        if accepts_inline and client_inline:
            for raw in client_inline:
                if isinstance(raw, dict) and raw.get("catalogId"):
                    cid = raw["catalogId"]
                    inline_catalog = _parse_inline_catalog(raw)
                    self.register(inline_catalog)
                    return cid

        # 2. default
        default = self.default_id()
        if default in client_supported:
            return default

        # 3. 交集
        for cid in self.supported_ids():
            if cid in client_supported:
                return cid

        # 4. 兜底 standard
        if STANDARD_V08 not in self._catalogs:
            self.register_standard()
        return STANDARD_V08

    def advertise(self, *, accepts_inline: bool = False) -> dict[str, Any]:
        """生成 Agent Card 用的 A2UI 扩展声明。"""
        return {
            "uri": "https://a2ui.org/a2a-extension/a2ui/v0.8",
            "params": {
                "supportedCatalogIds": self.supported_ids(),
                "acceptsInlineCatalogs": accepts_inline,
            },
        }


def _parse_inline_catalog(raw: dict) -> CatalogDefinition:
    cid = raw["catalogId"]
    catalog = CatalogDefinition(catalog_id=cid)
    for type_name, schema in (raw.get("components") or {}).items():
        meta = ComponentMeta(
            type=type_name,
            input_schema=schema if isinstance(schema, dict) else {},
        )
        catalog.register(meta)
    catalog.styles = dict(raw.get("styles") or {})
    return catalog


# ═══════════════════════════════════════════════════════════
# ComponentMatcherV2 — 注册表驱动的 5 层匹配
# ═══════════════════════════════════════════════════════════

SCHEMA_MATCH_THRESHOLD = 0.6


class ComponentMatcherV2:
    """组件-Skill 5 层匹配（对齐 apps-agent）。

    Layer 1: bind（静态一对一）
    Layer 2: prefer（静态首选）
    Layer 3: ModelName（按 supported_model_names 匹配）
    Layer 4: Schema 字段重叠（≥ 0.6）
    Layer 5: LLM fallback（可关闭）

    缓存：启动时 warmup() 预计算；支持原子 rewarmup() 替换。
    """

    def __init__(self, registry: CatalogRegistry, *,
                 catalog_id: str | None = None,
                 llm_fallback: bool = False) -> None:
        self._registry = registry
        self._catalog_id = catalog_id or registry.default_id()
        self._llm_fallback = llm_fallback
        # 预计算缓存
        self._bind_map: dict[str, str] = {}
        self._prefer_map: dict[str, list[str]] = {}
        self._model_name_map: dict[str, list[str]] = {}
        self._schema_cache: dict[str, list[str]] = {}

    # ── 预热 ──

    def warmup(self, skills: list[Any] | None = None) -> None:
        self._build_cache(skills)

    def rewarmup(self, skills: list[Any] | None = None) -> None:
        new_bind: dict[str, str] = {}
        new_prefer: dict[str, list[str]] = {}
        new_mn: dict[str, list[str]] = {}
        new_schema: dict[str, list[str]] = {}
        self._build_static_maps(new_bind, new_prefer, new_mn)
        if skills:
            self._build_schema_cache(skills, new_schema)
        self._bind_map, self._prefer_map = new_bind, new_prefer
        self._model_name_map, self._schema_cache = new_mn, new_schema

    # ── 解析 ──

    def resolve(
        self,
        skill_apikey: str,
        output_schema: dict | None = None,
        output_model_names: list[str] | None = None,
    ) -> str | None:
        # 1. bind
        if skill_apikey in self._bind_map:
            return self._bind_map[skill_apikey]
        # 2. prefer
        candidates = self._prefer_map.get(skill_apikey)
        if candidates:
            return candidates[0]
        # 3. model_name
        for mn in (output_model_names or []):
            hits = self._model_name_map.get(mn, [])
            if len(hits) == 1:
                return hits[0]
            if len(hits) > 1:
                return self._fallback(skill_apikey, hits)
        # 4. schema
        hits = self._schema_cache.get(skill_apikey, [])
        if not hits and output_schema:
            hits = self._match_schema_dynamic(output_schema)
        if len(hits) == 1:
            return hits[0]
        if len(hits) > 1:
            return self._fallback(skill_apikey, hits)
        return None

    # ── 内部 ──

    def _build_cache(self, skills: list[Any] | None) -> None:
        self._build_static_maps(self._bind_map, self._prefer_map, self._model_name_map)
        if skills:
            self._build_schema_cache(skills, self._schema_cache)

    def _build_static_maps(
        self,
        bind: dict[str, str],
        prefer: dict[str, list[str]],
        model_name_map: dict[str, list[str]],
    ) -> None:
        catalog = self._registry.get(self._catalog_id)
        if catalog is None:
            return
        for comp in catalog.list_components():
            for skill_key in comp.skill_bindings.get("bind", []):
                bind[skill_key] = comp.type
            for skill_key in comp.skill_bindings.get("prefer", []):
                prefer.setdefault(skill_key, []).append(comp.type)
            for mn in comp.supported_model_names:
                model_name_map.setdefault(mn, []).append(comp.type)

    def _build_schema_cache(self, skills: list[Any], cache: dict[str, list[str]]) -> None:
        for skill in skills:
            schema = getattr(skill, "output_schema", None)
            if isinstance(schema, str):
                try:
                    schema = json.loads(schema)
                except (json.JSONDecodeError, TypeError):
                    continue
            if not isinstance(schema, dict):
                continue
            matches = self._match_schema_dynamic(schema)
            if matches:
                key = getattr(skill, "apikey", None) or getattr(skill, "name", None)
                if key:
                    cache[key] = matches

    def _match_schema_dynamic(self, skill_schema: dict) -> list[str]:
        skill_fields = set((skill_schema.get("properties") or {}).keys())
        if not skill_fields:
            return []
        catalog = self._registry.get(self._catalog_id)
        if catalog is None:
            return []
        ranked: list[tuple[float, str]] = []
        for comp in catalog.list_components():
            input_schema = comp.input_schema or {}
            comp_fields = set((input_schema.get("properties") or input_schema).keys())
            if not comp_fields:
                continue
            overlap = len(skill_fields & comp_fields) / max(len(skill_fields), len(comp_fields))
            if overlap >= SCHEMA_MATCH_THRESHOLD:
                ranked.append((overlap, comp.type))
        ranked.sort(key=lambda x: -x[0])
        return [t for _, t in ranked]

    def _fallback(self, skill_apikey: str, candidates: list[str]) -> str:
        if not self._llm_fallback:
            return candidates[0]
        try:
            return self._llm_pick(skill_apikey, candidates)
        except Exception:
            logger.warning("LLM fallback failed for %s, using first candidate",
                           skill_apikey, exc_info=True)
            return candidates[0]

    def _llm_pick(self, skill_apikey: str, candidates: list[str]) -> str:
        """默认实现：直接返回首选。子类可覆盖以接入真正的 LLM。"""
        return candidates[0]
