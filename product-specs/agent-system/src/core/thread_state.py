"""ThreadState — LangGraph 原生 MessagesState + 扩展字段

替代旧的 GraphState dataclass，使用 LangGraph 原生的 MessagesState 基类，
支持 Artifact、ImageData 和自定义 reducer。
"""
from __future__ import annotations

import json
import operator
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Annotated, Any

from langgraph.graph import MessagesState
from langchain_core.messages import messages_from_dict, message_to_dict


@dataclass
class Artifact:
    """Agent 生成的 artifact（代码、文档等）"""
    id: str
    type: str
    title: str
    content: str
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id, "type": self.type, "title": self.title,
            "content": self.content, "created_at": self.created_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Artifact:
        created_at = data.get("created_at")
        if isinstance(created_at, str):
            created_at = datetime.fromisoformat(created_at)
        elif created_at is None:
            created_at = datetime.now(timezone.utc)
        return cls(id=data["id"], type=data["type"], title=data["title"],
                   content=data["content"], created_at=created_at)


@dataclass
class ImageData:
    """Agent 生成或引用的图片数据"""
    id: str
    url: str
    alt_text: str
    data: bytes | None = None

    def to_dict(self) -> dict[str, Any]:
        import base64
        result: dict[str, Any] = {"id": self.id, "url": self.url, "alt_text": self.alt_text}
        result["data"] = base64.b64encode(self.data).decode("ascii") if self.data else None
        return result

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ImageData:
        import base64
        raw = data.get("data")
        decoded = base64.b64decode(raw) if isinstance(raw, str) else (raw if isinstance(raw, bytes) else None)
        return cls(id=data["id"], url=data["url"], alt_text=data["alt_text"], data=decoded)


def artifacts_reducer(existing: list[Artifact], new: list[Artifact]) -> list[Artifact]:
    """增量追加 + 按 ID 更新"""
    by_id: dict[str, int] = {a.id: idx for idx, a in enumerate(existing)}
    result = list(existing)
    for artifact in new:
        if artifact.id in by_id:
            result[by_id[artifact.id]] = artifact
        else:
            by_id[artifact.id] = len(result)
            result.append(artifact)
    return result


class ThreadState(MessagesState):
    """Agent 运行时线程状态 — 继承 MessagesState 获得 messages 字段"""
    artifacts: Annotated[list[Artifact], artifacts_reducer]
    images: Annotated[list[ImageData], operator.add]
    title: str | None
    thread_data: dict[str, Any]


# ── JSON 序列化 ──

def thread_state_to_json(state: dict[str, Any]) -> str:
    return json.dumps(_state_to_serializable(state), ensure_ascii=False)


def thread_state_from_json(json_str: str) -> dict[str, Any]:
    return _state_from_serializable(json.loads(json_str))


def _state_to_serializable(state: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    if "messages" in state:
        result["messages"] = [message_to_dict(m) for m in state["messages"]]
    if "artifacts" in state:
        result["artifacts"] = [a.to_dict() for a in state["artifacts"]]
    if "images" in state:
        result["images"] = [img.to_dict() for img in state["images"]]
    for key in ("title", "thread_data"):
        if key in state:
            result[key] = state[key]
    return result


def _state_from_serializable(raw: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    if "messages" in raw:
        result["messages"] = messages_from_dict(raw["messages"])
    if "artifacts" in raw:
        result["artifacts"] = [Artifact.from_dict(a) for a in raw["artifacts"]]
    if "images" in raw:
        result["images"] = [ImageData.from_dict(img) for img in raw["images"]]
    for key in ("title", "thread_data"):
        if key in raw:
            result[key] = raw[key]
    return result
