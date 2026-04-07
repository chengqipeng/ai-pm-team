"""
上下文管理 — 借鉴 context.ts / claudemd.ts / attachments.ts
五层上下文架构: 静态上下文 → 动态附件 → 对话历史 → 压缩 → 恢复
"""
from __future__ import annotations

import os
import time
import asyncio
import hashlib
import functools
from pathlib import Path
from dataclasses import dataclass, field
from typing import Any

from .types import Message, MessageRole


# ─── Layer 1: 静态上下文 (会话级) ───

MAX_STATUS_CHARS = 2000


def _memoize(fn):
    """会话级 memoize (借鉴 context.ts 的 lodash memoize)"""
    cache: dict[str, Any] = {}

    @functools.wraps(fn)
    async def wrapper(*args, **kwargs):
        key = f"{args}_{kwargs}"
        if key not in cache:
            cache[key] = await fn(*args, **kwargs)
        return cache[key]

    wrapper.cache = cache
    wrapper.clear_cache = lambda: cache.clear()
    return wrapper


@_memoize
async def get_git_status() -> str | None:
    """获取 Git 状态快照 (借鉴 context.ts:getGitStatus)"""
    try:
        proc = await asyncio.create_subprocess_exec(
            "git", "rev-parse", "--is-inside-work-tree",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
        if proc.returncode != 0:
            return None

        branch_proc = await asyncio.create_subprocess_exec(
            "git", "branch", "--show-current",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        branch_out, _ = await branch_proc.communicate()
        branch = branch_out.decode().strip()

        status_proc = await asyncio.create_subprocess_exec(
            "git", "--no-optional-locks", "status", "--short",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        status_out, _ = await status_proc.communicate()
        status = status_out.decode().strip()

        if len(status) > MAX_STATUS_CHARS:
            status = status[:MAX_STATUS_CHARS] + "\n... (truncated)"

        log_proc = await asyncio.create_subprocess_exec(
            "git", "--no-optional-locks", "log", "--oneline", "-n", "5",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        log_out, _ = await log_proc.communicate()
        log = log_out.decode().strip()

        return "\n\n".join([
            "Git status snapshot (will not update during conversation).",
            f"Current branch: {branch}",
            f"Status:\n{status or '(clean)'}",
            f"Recent commits:\n{log}",
        ])
    except Exception:
        return None


@_memoize
async def get_system_context() -> dict[str, str]:
    """系统上下文 (借鉴 context.ts:getSystemContext)"""
    import platform
    git_status = await get_git_status()
    ctx: dict[str, str] = {}
    if git_status:
        ctx["git_status"] = git_status
    ctx["platform"] = platform.system()
    return ctx


@_memoize
async def get_user_context(project_root: str = ".") -> dict[str, str]:
    """用户上下文 — CLAUDE.md 记忆文件 (借鉴 context.ts:getUserContext)"""
    from datetime import date
    ctx: dict[str, str] = {"current_date": f"Today's date is {date.today().isoformat()}."}
    claude_md = load_memory_files(project_root)
    if claude_md:
        ctx["claude_md"] = claude_md
    return ctx


# ─── CLAUDE.md 记忆文件体系 (借鉴 claudemd.ts) ───

MEMORY_FILE_NAMES = ["CLAUDE.md", ".claude/CLAUDE.md"]
MEMORY_LOCAL_NAMES = ["CLAUDE.local.md"]
MEMORY_RULES_DIR = ".claude/rules"
MEMORY_INSTRUCTION_PROMPT = (
    "Codebase and user instructions are shown below. "
    "Be sure to adhere to these instructions. "
    "IMPORTANT: These instructions OVERRIDE any default behavior."
)
MAX_MEMORY_CHARS = 40_000


def load_memory_files(project_root: str = ".") -> str | None:
    """
    加载记忆文件 (借鉴 claudemd.ts)
    优先级: Managed → User → Project → Local
    """
    sections: list[str] = []

    # 1. User memory (~/.claude/CLAUDE.md)
    user_home = Path.home() / ".claude" / "CLAUDE.md"
    if user_home.exists():
        sections.append(_read_memory_file(user_home, "user"))

    # 2. Project memory (向上遍历)
    root = Path(project_root).resolve()
    project_files: list[tuple[Path, str]] = []
    current = root
    while current != current.parent:
        for name in MEMORY_FILE_NAMES:
            p = current / name
            if p.exists():
                project_files.append((p, "project"))
        rules_dir = current / MEMORY_RULES_DIR
        if rules_dir.is_dir():
            for md in sorted(rules_dir.glob("*.md")):
                project_files.append((md, "project-rule"))
        current = current.parent

    # 反转: 越靠近 cwd 优先级越高 (后加载)
    for path, source in reversed(project_files):
        sections.append(_read_memory_file(path, source))

    # 3. Local memory
    for name in MEMORY_LOCAL_NAMES:
        p = root / name
        if p.exists():
            sections.append(_read_memory_file(p, "local"))

    if not sections:
        return None

    combined = "\n\n---\n\n".join(sections)
    if len(combined) > MAX_MEMORY_CHARS:
        combined = combined[:MAX_MEMORY_CHARS] + "\n... (truncated)"
    return f"{MEMORY_INSTRUCTION_PROMPT}\n\n{combined}"


def _read_memory_file(path: Path, source: str) -> str:
    try:
        content = path.read_text(encoding="utf-8")
        return f"[{source}: {path}]\n{content}"
    except Exception:
        return ""


# ─── Layer 2: 动态附件 (轮次级) ───

@dataclass
class Attachment:
    """动态附件 (借鉴 attachments.ts)"""
    tag: str          # 附件类型标签
    content: str      # 附件内容
    priority: int = 0 # 优先级 (高优先级后注入)


class AttachmentManager:
    """
    附件管理器 (借鉴 attachments.ts:getAttachments)
    每轮计算动态附件，注入到用户消息中
    """

    def __init__(self):
        self._sent_skill_names: set[str] = set()
        self._sent_agent_types: set[str] = set()
        self._loaded_nested_memory_paths: set[str] = set()

    async def get_attachments(
        self,
        user_input: str | None,
        messages: list[Message],
        tools: list[Any],
        agents: list[Any],
    ) -> list[Attachment]:
        attachments: list[Attachment] = []

        # 技能列表增量 (delta attachment, 避免 cache bust)
        skill_delta = self._get_skill_listing_delta(tools)
        if skill_delta:
            attachments.append(skill_delta)

        # Agent 列表增量
        agent_delta = self._get_agent_listing_delta(agents)
        if agent_delta:
            attachments.append(agent_delta)

        # Token 用量提醒
        token_att = self._get_token_usage_attachment(messages)
        if token_att:
            attachments.append(token_att)

        return sorted(attachments, key=lambda a: a.priority)

    def _get_skill_listing_delta(self, tools: list[Any]) -> Attachment | None:
        current_names = {t.name for t in tools if hasattr(t, "name")}
        new_names = current_names - self._sent_skill_names
        if not new_names:
            return None
        self._sent_skill_names |= new_names
        listing = "\n".join(f"- {n}" for n in sorted(new_names))
        return Attachment(tag="skill_listing_delta", content=listing)

    def _get_agent_listing_delta(self, agents: list[Any]) -> Attachment | None:
        current = {getattr(a, "agent_type", str(a)) for a in agents}
        new_types = current - self._sent_agent_types
        if not new_types:
            return None
        self._sent_agent_types |= new_types
        listing = "\n".join(f"- {t}" for t in sorted(new_types))
        return Attachment(tag="agent_listing_delta", content=listing)

    def _get_token_usage_attachment(self, messages: list[Message]) -> Attachment | None:
        total_chars = sum(len(str(m.content)) for m in messages)
        estimated_tokens = total_chars // 4
        if estimated_tokens > 150_000:
            return Attachment(
                tag="token_warning",
                content=f"Context is ~{estimated_tokens:,} tokens. Consider using /compact.",
                priority=10,
            )
        return None

    def reset_after_compact(self):
        """压缩后重置 (需要重新公告完整列表)"""
        self._sent_skill_names.clear()
        self._sent_agent_types.clear()
        self._loaded_nested_memory_paths.clear()


# ─── Layer 4: 上下文压缩 ───

@dataclass
class CompactionResult:
    summary: str
    pre_compact_tokens: int
    post_compact_tokens: int
    attachments: list[Attachment] = field(default_factory=list)


class ContextCompressor:
    """
    上下文压缩器 (借鉴 compact.ts + apiMicrocompact.ts + snipCompact.ts)
    六策略协同: Budget → Snip → Microcompact → Collapse → Autocompact → Reactive
    """

    # 工具结果预算 (借鉴各 Tool 的 maxResultSizeChars)
    RESULT_BUDGETS: dict[str, int] = {
        "bash": 30_000,
        "skill": 100_000,
        "file_read": 999_999_999,  # Infinity — 避免 Read→file→Read 循环
        "grep": 50_000,
        "web_fetch": 50_000,
        "DEFAULT": 50_000,
    }
    AUTOCOMPACT_TRIGGER_TOKENS = 150_000
    AUTOCOMPACT_TARGET_TOKENS = 40_000

    def __init__(self, llm_call: Any = None):
        self._llm_call = llm_call

    def apply_tool_result_budget(
        self, messages: list[Message]
    ) -> list[Message]:
        """Step 1: 工具结果预算控制 (借鉴 toolResultStorage.ts)"""
        for msg in messages:
            for block in msg.tool_result_blocks:
                budget = self._get_budget(block.tool_use_id, messages)
                if len(block.content) > budget:
                    preview = block.content[:500]
                    block.content = (
                        f"{preview}\n\n[Result truncated: "
                        f"{len(block.content):,} chars exceeded budget of {budget:,}]"
                    )
        return messages

    def snip_history(
        self, messages: list[Message], keep_recent: int = 20
    ) -> tuple[list[Message], int]:
        """Step 2: 历史裁剪 (借鉴 snipCompact.ts)"""
        if len(messages) <= keep_recent:
            return messages, 0
        snipped = messages[-keep_recent:]
        freed = sum(len(str(m.content)) // 4 for m in messages[:-keep_recent])
        return snipped, freed

    def microcompact(self, messages: list[Message]) -> list[Message]:
        """
        Step 3: 微压缩 (借鉴 apiMicrocompact.ts)
        清除旧的搜索/读取类工具结果，保留最近的
        """
        CLEARABLE_TOOLS = {"bash", "glob", "grep", "file_read", "web_fetch", "web_search"}
        tool_result_msgs = [
            (i, m) for i, m in enumerate(messages)
            if m.tool_result_blocks
        ]
        if len(tool_result_msgs) <= 5:
            return messages

        # 保留最近 5 个工具结果，清除更早的可清除结果
        for idx, msg in tool_result_msgs[:-5]:
            for block in msg.tool_result_blocks:
                tool_name = self._find_tool_name(block.tool_use_id, messages)
                if tool_name and tool_name.lower() in CLEARABLE_TOOLS:
                    block.content = "[Old tool result cleared by microcompact]"
        return messages

    def collapse_read_search(self, messages: list[Message]) -> list[Message]:
        """
        Step 4: 上下文折叠 (借鉴 collapseReadSearch.ts)
        将连续的搜索/读取工具调用折叠为摘要
        """
        COLLAPSIBLE = {"glob", "grep", "file_read", "web_search"}
        result: list[Message] = []
        collapse_group: list[Message] = []

        for msg in messages:
            is_collapsible = (
                msg.tool_use_blocks
                and all(
                    self._find_tool_name(b.id, messages) in COLLAPSIBLE
                    for b in msg.tool_use_blocks
                    if self._find_tool_name(b.id, messages)
                )
            )
            if is_collapsible:
                collapse_group.append(msg)
            else:
                if collapse_group:
                    result.append(self._summarize_collapse_group(collapse_group))
                    collapse_group = []
                result.append(msg)

        if collapse_group:
            result.append(self._summarize_collapse_group(collapse_group))
        return result

    async def autocompact(
        self, messages: list[Message], system_prompt: str
    ) -> CompactionResult | None:
        """
        Step 5: 自动全量压缩 (借鉴 compact.ts:compactConversation)
        当 token 使用接近限制时，调用 LLM 生成对话摘要
        """
        estimated_tokens = sum(len(str(m.content)) // 4 for m in messages)
        if estimated_tokens < self.AUTOCOMPACT_TRIGGER_TOKENS:
            return None

        if not self._llm_call:
            # 无 LLM 时使用本地摘要: 提取关键信息
            summary = self._local_summarize(messages)
            return CompactionResult(
                summary=summary,
                pre_compact_tokens=estimated_tokens,
                post_compact_tokens=len(summary) // 4,
            )

        # 构建压缩 prompt (借鉴 compact.ts:getCompactPrompt)
        compact_prompt = (
            "Summarize the conversation so far. Preserve:\n"
            "- All important context and decisions made\n"
            "- File paths that were read or modified\n"
            "- Current task state and what remains to be done\n"
            "- Any errors encountered and how they were resolved\n"
            "Be concise but thorough. Do not lose critical information."
        )

        try:
            summary = await self._llm_call(compact_prompt, messages)
        except Exception:
            # LLM 调用失败时降级为本地摘要
            summary = self._local_summarize(messages)

        return CompactionResult(
            summary=summary,
            pre_compact_tokens=estimated_tokens,
            post_compact_tokens=len(summary) // 4,
        )

    def _local_summarize(self, messages: list[Message]) -> str:
        """
        本地摘要 (无 LLM 时的降级方案)
        提取: 用户请求、工具调用、助手回复的关键片段
        """
        parts = []
        for msg in messages:
            if msg.role == MessageRole.USER and msg.content and not msg.tool_result_blocks:
                text = str(msg.content)[:300]
                parts.append(f"[User] {text}")
            elif msg.role == MessageRole.ASSISTANT and msg.content and not msg.tool_use_blocks:
                text = str(msg.content)[:300]
                parts.append(f"[Assistant] {text}")
            elif msg.tool_use_blocks:
                for b in msg.tool_use_blocks:
                    parts.append(f"[Tool call] {b.name}({str(b.input)[:100]})")
            elif msg.tool_result_blocks:
                for b in msg.tool_result_blocks:
                    status = "error" if b.is_error else "ok"
                    parts.append(f"[Tool result: {status}] {b.content[:100]}")
        return "Conversation summary:\n" + "\n".join(parts[-30:])

    def _get_budget(self, tool_use_id: str, messages: list[Message]) -> int:
        name = self._find_tool_name(tool_use_id, messages)
        if name:
            return self.RESULT_BUDGETS.get(name.lower(), self.RESULT_BUDGETS["DEFAULT"])
        return self.RESULT_BUDGETS["DEFAULT"]

    def _find_tool_name(self, tool_use_id: str, messages: list[Message]) -> str | None:
        for msg in messages:
            for block in msg.tool_use_blocks:
                if block.id == tool_use_id:
                    return block.name
        return None

    def _summarize_collapse_group(self, group: list[Message]) -> Message:
        tool_names = []
        for msg in group:
            for b in msg.tool_use_blocks:
                tool_names.append(b.name)
        summary = f"[Collapsed {len(group)} search/read operations: {', '.join(tool_names)}]"
        return Message(role=MessageRole.SYSTEM, content=summary)
