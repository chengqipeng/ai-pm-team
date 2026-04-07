"""
会话持久化 — 借鉴 utils/sessionStorage.ts
Transcript 记录 / Session Resume / 文件历史快照

核心职责:
1. 将每轮对话记录为 JSONL transcript 文件
2. 支持 --resume 从上次中断处恢复
3. 管理文件历史快照 (用于 undo)
4. 子 Agent 的 sidechain transcript

借鉴源码:
  - src/utils/sessionStorage.ts: recordTranscript, flushSessionStorage
  - src/utils/fileHistory.ts: fileHistoryMakeSnapshot
  - src/history.ts: addToHistory, getLastSessionLog
  - src/tools/AgentTool/runAgent.ts: recordSidechainTranscript
"""
from __future__ import annotations

import os
import json
import time
import logging
import hashlib
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import Any

from .types import Message, MessageRole, ToolUseBlock, ToolResultBlock

logger = logging.getLogger(__name__)

# 默认会话存储目录
DEFAULT_PROJECT_DIR = ".agent-sessions"


def _get_session_dir(project_root: str, session_id: str) -> Path:
    """获取会话目录"""
    return Path(project_root) / DEFAULT_PROJECT_DIR / session_id


# ─── Transcript 序列化 ───

def _message_to_dict(msg: Message) -> dict:
    """将 Message 序列化为可 JSON 化的 dict"""
    d: dict[str, Any] = {
        "role": msg.role.value,
        "uuid": msg.uuid,
        "timestamp": msg.timestamp,
    }
    if msg.content:
        d["content"] = msg.content if isinstance(msg.content, str) else str(msg.content)
    if msg.tool_use_blocks:
        d["tool_use_blocks"] = [
            {"id": b.id, "name": b.name, "input": b.input}
            for b in msg.tool_use_blocks
        ]
    if msg.tool_result_blocks:
        d["tool_result_blocks"] = [
            {"tool_use_id": b.tool_use_id, "content": b.content, "is_error": b.is_error}
            for b in msg.tool_result_blocks
        ]
    if msg.is_compact_boundary:
        d["is_compact_boundary"] = True
    if msg.api_error:
        d["api_error"] = msg.api_error
    if msg.usage:
        d["usage"] = msg.usage
    return d


def _dict_to_message(d: dict) -> Message:
    """从 dict 反序列化为 Message"""
    tool_use_blocks = []
    for b in d.get("tool_use_blocks", []):
        tool_use_blocks.append(ToolUseBlock(
            id=b["id"], name=b["name"], input=b.get("input", {}),
        ))

    tool_result_blocks = []
    for b in d.get("tool_result_blocks", []):
        tool_result_blocks.append(ToolResultBlock(
            tool_use_id=b["tool_use_id"],
            content=b.get("content", ""),
            is_error=b.get("is_error", False),
        ))

    return Message(
        role=MessageRole(d["role"]),
        content=d.get("content", ""),
        tool_use_blocks=tool_use_blocks,
        tool_result_blocks=tool_result_blocks,
        uuid=d.get("uuid", ""),
        timestamp=d.get("timestamp", 0),
        is_compact_boundary=d.get("is_compact_boundary", False),
        api_error=d.get("api_error"),
        usage=d.get("usage"),
    )


# ─── Session Storage ───

class SessionStorage:
    """
    会话存储管理器 (借鉴 utils/sessionStorage.ts)

    存储结构:
      .agent-sessions/
        {session_id}/
          transcript.jsonl     ← 主对话 transcript
          metadata.json        ← 会话元数据
          subagents/
            {agent_id}.jsonl   ← 子 Agent sidechain transcript
          tool-results/
            {id}.txt           ← 持久化的大工具结果
          file-snapshots/
            {uuid}/            ← 文件历史快照
    """

    def __init__(self, project_root: str = ".", session_id: str | None = None):
        self._project_root = project_root
        self._session_id = session_id or self._generate_session_id()
        self._session_dir = _get_session_dir(project_root, self._session_id)
        self._transcript_path = self._session_dir / "transcript.jsonl"
        self._metadata_path = self._session_dir / "metadata.json"
        self._write_queue: list[dict] = []
        self._last_flush_time = 0.0
        self._initialized = False

    @property
    def session_id(self) -> str:
        return self._session_id

    @property
    def session_dir(self) -> Path:
        return self._session_dir

    def _ensure_dirs(self) -> None:
        """确保目录结构存在"""
        if self._initialized:
            return
        self._session_dir.mkdir(parents=True, exist_ok=True)
        (self._session_dir / "subagents").mkdir(exist_ok=True)
        (self._session_dir / "tool-results").mkdir(exist_ok=True)
        (self._session_dir / "file-snapshots").mkdir(exist_ok=True)
        self._initialized = True

    def _generate_session_id(self) -> str:
        """生成会话 ID (时间戳 + 随机后缀)"""
        ts = time.strftime("%Y%m%d_%H%M%S")
        suffix = hashlib.md5(str(time.time()).encode()).hexdigest()[:6]
        return f"{ts}_{suffix}"

    # ─── Transcript 记录 ───

    async def record_transcript(self, messages: list[Message]) -> None:
        """
        记录 transcript (借鉴 sessionStorage.ts:recordTranscript)
        使用 JSONL 格式，每条消息一行
        """
        self._ensure_dirs()
        try:
            with open(self._transcript_path, "w", encoding="utf-8") as f:
                for msg in messages:
                    line = json.dumps(_message_to_dict(msg), ensure_ascii=False)
                    f.write(line + "\n")
        except Exception as e:
            logger.error(f"Failed to record transcript: {e}")

    async def append_transcript(self, message: Message) -> None:
        """追加单条消息到 transcript"""
        self._ensure_dirs()
        try:
            with open(self._transcript_path, "a", encoding="utf-8") as f:
                line = json.dumps(_message_to_dict(message), ensure_ascii=False)
                f.write(line + "\n")
        except Exception as e:
            logger.error(f"Failed to append transcript: {e}")

    async def load_transcript(self) -> list[Message]:
        """加载 transcript (用于 session resume)"""
        if not self._transcript_path.exists():
            return []
        messages = []
        try:
            with open(self._transcript_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        d = json.loads(line)
                        messages.append(_dict_to_message(d))
        except Exception as e:
            logger.error(f"Failed to load transcript: {e}")
        return messages

    # ─── 子 Agent Sidechain Transcript ───

    async def record_sidechain(self, agent_id: str, messages: list[Message]) -> None:
        """
        记录子 Agent 的 sidechain transcript
        (借鉴 runAgent.ts:recordSidechainTranscript)
        """
        self._ensure_dirs()
        path = self._session_dir / "subagents" / f"{agent_id}.jsonl"
        try:
            with open(path, "w", encoding="utf-8") as f:
                for msg in messages:
                    line = json.dumps(_message_to_dict(msg), ensure_ascii=False)
                    f.write(line + "\n")
        except Exception as e:
            logger.error(f"Failed to record sidechain for {agent_id}: {e}")

    # ─── 工具结果持久化 ───

    async def persist_tool_result(self, tool_use_id: str, content: str) -> str:
        """
        持久化大工具结果到磁盘 (借鉴 toolResultStorage.ts:persistToolResult)
        返回文件路径
        """
        self._ensure_dirs()
        is_json = content.strip().startswith("{") or content.strip().startswith("[")
        ext = ".json" if is_json else ".txt"
        path = self._session_dir / "tool-results" / f"{tool_use_id}{ext}"
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(content)
            return str(path)
        except Exception as e:
            logger.error(f"Failed to persist tool result: {e}")
            return ""

    async def load_tool_result(self, tool_use_id: str) -> str | None:
        """加载持久化的工具结果"""
        for ext in [".txt", ".json"]:
            path = self._session_dir / "tool-results" / f"{tool_use_id}{ext}"
            if path.exists():
                return path.read_text(encoding="utf-8")
        return None

    # ─── 文件历史快照 ───

    async def make_file_snapshot(
        self, message_uuid: str, file_paths: list[str]
    ) -> None:
        """
        创建文件历史快照 (借鉴 fileHistory.ts:fileHistoryMakeSnapshot)
        在用户消息提交时，对即将被修改的文件创建快照
        """
        self._ensure_dirs()
        snapshot_dir = self._session_dir / "file-snapshots" / message_uuid
        snapshot_dir.mkdir(parents=True, exist_ok=True)
        for file_path in file_paths:
            try:
                if os.path.exists(file_path):
                    content = open(file_path, "r", encoding="utf-8").read()
                    safe_name = file_path.replace("/", "__").replace("\\", "__")
                    (snapshot_dir / safe_name).write_text(content, encoding="utf-8")
            except Exception as e:
                logger.debug(f"Failed to snapshot {file_path}: {e}")

    async def restore_file_snapshot(self, message_uuid: str) -> dict[str, str]:
        """恢复文件快照，返回 {原始路径: 内容}"""
        snapshot_dir = self._session_dir / "file-snapshots" / message_uuid
        if not snapshot_dir.exists():
            return {}
        restored = {}
        for f in snapshot_dir.iterdir():
            original_path = f.name.replace("__", "/")
            restored[original_path] = f.read_text(encoding="utf-8")
        return restored

    # ─── 会话元数据 ───

    async def save_metadata(self, metadata: dict) -> None:
        """保存会话元数据"""
        self._ensure_dirs()
        metadata.setdefault("session_id", self._session_id)
        metadata.setdefault("created_at", time.time())
        metadata["updated_at"] = time.time()
        try:
            with open(self._metadata_path, "w", encoding="utf-8") as f:
                json.dump(metadata, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"Failed to save metadata: {e}")

    async def load_metadata(self) -> dict:
        """加载会话元数据"""
        if not self._metadata_path.exists():
            return {}
        try:
            with open(self._metadata_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    # ─── 会话列表 ───

    @classmethod
    def list_sessions(cls, project_root: str = ".") -> list[dict]:
        """列出所有会话"""
        sessions_dir = Path(project_root) / DEFAULT_PROJECT_DIR
        if not sessions_dir.exists():
            return []
        sessions = []
        for d in sorted(sessions_dir.iterdir(), reverse=True):
            if d.is_dir():
                meta_path = d / "metadata.json"
                meta = {}
                if meta_path.exists():
                    try:
                        meta = json.loads(meta_path.read_text())
                    except Exception:
                        pass
                sessions.append({
                    "session_id": d.name,
                    "path": str(d),
                    **meta,
                })
        return sessions

    @classmethod
    def get_latest_session_id(cls, project_root: str = ".") -> str | None:
        """获取最近的会话 ID"""
        sessions = cls.list_sessions(project_root)
        return sessions[0]["session_id"] if sessions else None
