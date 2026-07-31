"""A2UI v0.8 消息模型 — 符合规范的 dataclass + JSONL 序列化

所有消息都是以下四种之一（参考 a2ui v0.8 规范 §2.2 ~ §4.1）：

- SurfaceUpdate   → {"surfaceUpdate": {"surfaceId", "components": [...]}}
- DataModelUpdate → {"dataModelUpdate": {"surfaceId", "path?", "contents": [...]}}
- BeginRendering  → {"beginRendering": {"surfaceId", "root", "catalogId?"}}
- DeleteSurface   → {"deleteSurface": {"surfaceId"}}

所有消息都有 .to_dict() 与 .to_jsonl()：
- to_dict()  返回可直接 JSON 序列化的 dict（用于嵌到 AG-UI CUSTOM/ACTIVITY 事件）
- to_jsonl() 返回一行 JSON 文本（用于严格的 A2UI JSONL 流）

邻接表 / BoundValue / DataEntry 设计初衷：让 LLM 结构化输出更稳定。
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any


# ═══════════════════════════════════════════════════════════
# BoundValue — 组件属性的值（字面量 | 数据路径 | 两者兼有=初始化）
# ═══════════════════════════════════════════════════════════

@dataclass
class BoundValue:
    """对应 A2UI v0.8 规范 §4.2 BoundValue

    使用约束：literal_* 和 path 至少提供一个。
    同时提供时为"初始化简写"（客户端先把 literal 写入 path，再绑定）。
    """
    path: str | None = None
    literal_string: str | None = None
    literal_number: float | None = None
    literal_boolean: bool | None = None
    literal_array: list[Any] | None = None

    def to_dict(self) -> dict:
        out: dict[str, Any] = {}
        if self.path is not None:
            out["path"] = self.path
        if self.literal_string is not None:
            out["literalString"] = self.literal_string
        if self.literal_number is not None:
            out["literalNumber"] = self.literal_number
        if self.literal_boolean is not None:
            out["literalBoolean"] = self.literal_boolean
        if self.literal_array is not None:
            out["literalArray"] = self.literal_array
        if not out:
            raise ValueError("BoundValue 必须至少提供一个字段（path / literal_*）")
        return out


def literal(value: Any) -> BoundValue:
    """根据 Python 值类型生成对应的字面量 BoundValue"""
    if isinstance(value, bool):  # 注意必须在 int 之前（bool 是 int 的子类）
        return BoundValue(literal_boolean=value)
    if isinstance(value, (int, float)):
        return BoundValue(literal_number=float(value))
    if isinstance(value, list):
        return BoundValue(literal_array=value)
    return BoundValue(literal_string=str(value))


def path_bind(path: str, default: Any = None) -> BoundValue:
    """绑定到数据模型路径；可选提供 default 作为初始化默认值"""
    bv = BoundValue(path=path)
    if default is not None:
        seeded = literal(default)
        bv.literal_string = seeded.literal_string
        bv.literal_number = seeded.literal_number
        bv.literal_boolean = seeded.literal_boolean
        bv.literal_array = seeded.literal_array
    return bv


# ═══════════════════════════════════════════════════════════
# DataEntry — dataModelUpdate.contents 的邻接表条目
# ═══════════════════════════════════════════════════════════

@dataclass
class DataEntry:
    """对应 A2UI v0.8 §4.1 DataEntry

    每个 entry 必须有 key，且只有一个 value_*（邻接表约束）。

    字段对齐 v0.8 规范：`value_list` 对应 `valueList`（规范名）。
    `value_array` 作为 deprecated 别名保留，构造时任一者都能用；序列化时优先
    用 `valueList`（规范名），同时附带 `valueArray` 供老前端兼容。
    """
    key: str
    value_string: str | None = None
    value_int: int | None = None
    value_number: float | None = None
    value_boolean: bool | None = None
    value_map: list["DataEntry"] | None = None
    value_list: list[Any] | None = None
    # deprecated 别名（构造时接受，与 value_list 同义）
    value_array: list[Any] | None = None

    def __post_init__(self) -> None:
        # 合并 value_array（deprecated）到 value_list
        if self.value_array is not None and self.value_list is None:
            self.value_list = self.value_array

    def to_dict(self) -> dict:
        out: dict[str, Any] = {"key": self.key}
        # 保持与 A2UI 规范命名一致（camelCase）
        if self.value_string is not None:
            out["valueString"] = self.value_string
        elif self.value_int is not None:
            out["valueInt"] = self.value_int
        elif self.value_number is not None:
            out["valueNumber"] = self.value_number
        elif self.value_boolean is not None:
            out["valueBoolean"] = self.value_boolean
        elif self.value_map is not None:
            out["valueMap"] = [e.to_dict() for e in self.value_map]
        elif self.value_list is not None:
            out["valueList"] = self.value_list
            # 兼容老前端（仅在 value_array 未显式禁用时）
            out["valueArray"] = self.value_list
        else:
            raise ValueError(f"DataEntry(key={self.key!r}) 必须提供一个 value_*")
        return out


def entry_string(key: str, value: str) -> DataEntry:
    return DataEntry(key=key, value_string=value)

def entry_int(key: str, value: int) -> DataEntry:
    return DataEntry(key=key, value_int=value)

def entry_number(key: str, value: float) -> DataEntry:
    return DataEntry(key=key, value_number=value)

def entry_boolean(key: str, value: bool) -> DataEntry:
    return DataEntry(key=key, value_boolean=value)

def entry_map(key: str, entries: list[DataEntry]) -> DataEntry:
    return DataEntry(key=key, value_map=entries)

def entry_list(key: str, items: list[Any]) -> DataEntry:
    return DataEntry(key=key, value_list=items)


def dict_to_entries(data: dict[str, Any]) -> list[DataEntry]:
    """把普通 Python dict 递归转换为 DataEntry 列表"""
    out: list[DataEntry] = []
    for k, v in data.items():
        if isinstance(v, bool):
            out.append(entry_boolean(k, v))
        elif isinstance(v, int):
            out.append(entry_int(k, v))
        elif isinstance(v, float):
            out.append(entry_number(k, v))
        elif isinstance(v, str):
            out.append(entry_string(k, v))
        elif isinstance(v, dict):
            out.append(entry_map(k, dict_to_entries(v)))
        elif isinstance(v, list):
            out.append(entry_list(k, v))
        elif v is None:
            out.append(entry_string(k, ""))
        else:
            out.append(entry_string(k, str(v)))
    return out


# ═══════════════════════════════════════════════════════════
# Component — 组件实例（邻接表，通过 id 引用）
# ═══════════════════════════════════════════════════════════

@dataclass
class Component:
    """对应 A2UI v0.8 §2.3 ~ §2.4

    wire 格式: {"id": "<id>", "component": {"<Type>": {<props>}}}

    props 的 schema 由 Catalog 决定，协议不强约束。
    """
    id: str
    type: str
    props: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"id": self.id, "component": {self.type: self.props}}


# ═══════════════════════════════════════════════════════════
# 四种消息类型
# ═══════════════════════════════════════════════════════════

@dataclass
class SurfaceUpdate:
    surface_id: str
    components: list[Component]

    def to_dict(self) -> dict:
        return {
            "surfaceUpdate": {
                "surfaceId": self.surface_id,
                "components": [c.to_dict() for c in self.components],
            }
        }

    def to_jsonl(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False)


@dataclass
class DataModelUpdate:
    surface_id: str
    contents: list[DataEntry]
    path: str | None = None

    def to_dict(self) -> dict:
        body: dict[str, Any] = {
            "surfaceId": self.surface_id,
            "contents": [e.to_dict() for e in self.contents],
        }
        if self.path is not None:
            body["path"] = self.path
        return {"dataModelUpdate": body}

    def to_jsonl(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False)


@dataclass
class BeginRendering:
    surface_id: str
    root: str
    catalog_id: str | None = None

    def to_dict(self) -> dict:
        body: dict[str, Any] = {"surfaceId": self.surface_id, "root": self.root}
        if self.catalog_id is not None:
            body["catalogId"] = self.catalog_id
        return {"beginRendering": body}

    def to_jsonl(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False)


@dataclass
class DeleteSurface:
    surface_id: str

    def to_dict(self) -> dict:
        return {"deleteSurface": {"surfaceId": self.surface_id}}

    def to_jsonl(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False)


# 类型别名：任意 A2UI 消息
A2UIMessage = SurfaceUpdate | DataModelUpdate | BeginRendering | DeleteSurface


# ═══════════════════════════════════════════════════════════
# 客户端入站消息（v0.8 §5）
# ═══════════════════════════════════════════════════════════

@dataclass
class UserAction:
    """客户端 → 服务端：用户交互事件（§5.2）"""
    name: str
    surface_id: str
    source_component_id: str
    timestamp: str
    context: dict[str, Any] = field(default_factory=dict)
    action_id: str | None = None

    def to_dict(self) -> dict:
        body: dict[str, Any] = {
            "name": self.name,
            "surfaceId": self.surface_id,
            "sourceComponentId": self.source_component_id,
            "timestamp": self.timestamp,
            "context": self.context,
        }
        if self.action_id is not None:
            body["actionId"] = self.action_id
        return {"userAction": body}


@dataclass
class ClientError:
    """客户端 → 服务端：渲染/绑定错误（§5.3）"""
    message: str
    component_id: str | None = None
    surface_id: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        body: dict[str, Any] = {"message": self.message}
        if self.component_id is not None:
            body["componentId"] = self.component_id
        if self.surface_id is not None:
            body["surfaceId"] = self.surface_id
        body.update(self.extra)
        return {"error": body}


ClientEvent = UserAction | ClientError
