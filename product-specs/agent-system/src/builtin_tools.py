"""
内置工具实现 — 借鉴 src/tools/ 目录
文件操作 / Shell 执行 / Agent 协作 / 技能调用
"""
from __future__ import annotations

import os
import re
import glob
import asyncio
import subprocess
from pathlib import Path
from typing import Any, Callable

from .types import ToolResult, ValidationResult, PermissionDecision, PermissionBehavior
from .tools import Tool, ToolUseContext


# ─── FileReadTool (借鉴 FileReadTool.ts) ───

class FileReadTool(Tool):
    @property
    def name(self) -> str:
        return "file_read"

    async def description(self, input_data: dict) -> str:
        return f"Read {input_data.get('path', 'file')}"

    def input_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path to read"},
                "start_line": {"type": "integer", "description": "Start line (optional)"},
                "end_line": {"type": "integer", "description": "End line (optional)"},
            },
            "required": ["path"],
        }

    async def call(self, input_data: dict, context: ToolUseContext, on_progress=None) -> ToolResult:
        path = input_data["path"]
        try:
            with open(path, "r", encoding="utf-8") as f:
                lines = f.readlines()
            start = input_data.get("start_line", 1) - 1
            end = input_data.get("end_line", len(lines))
            content = "".join(lines[max(0, start):end])
            # 记录到文件状态缓存
            context.read_file_state[path] = content[:200]
            return ToolResult(content=content)
        except Exception as e:
            return ToolResult(content=str(e), is_error=True)

    def is_read_only(self, input_data: dict) -> bool:
        return True

    @property
    def max_result_size_chars(self) -> int:
        return 999_999_999  # Infinity — 避免 Read→file→Read 循环

    def prompt(self) -> str:
        return "Read file contents. Supports optional line range."


# ─── FileWriteTool (借鉴 FileWriteTool.ts) ───

class FileWriteTool(Tool):
    @property
    def name(self) -> str:
        return "file_write"

    async def description(self, input_data: dict) -> str:
        return f"Write to {input_data.get('path', 'file')}"

    def input_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "content": {"type": "string"},
            },
            "required": ["path", "content"],
        }

    async def call(self, input_data: dict, context: ToolUseContext, on_progress=None) -> ToolResult:
        path = input_data["path"]
        try:
            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                f.write(input_data["content"])
            return ToolResult(content=f"Successfully wrote to {path}")
        except Exception as e:
            return ToolResult(content=str(e), is_error=True)

    def is_destructive(self, input_data: dict) -> bool:
        return True


# ─── FileEditTool (借鉴 FileEditTool.ts) ───

class FileEditTool(Tool):
    @property
    def name(self) -> str:
        return "file_edit"

    async def description(self, input_data: dict) -> str:
        return f"Edit {input_data.get('path', 'file')}"

    def input_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "old_string": {"type": "string"},
                "new_string": {"type": "string"},
            },
            "required": ["path", "old_string", "new_string"],
        }

    def validate_input(self, input_data: dict) -> ValidationResult:
        if input_data.get("old_string") == input_data.get("new_string"):
            return ValidationResult(valid=False, message="old_string and new_string are identical")
        return ValidationResult(valid=True)

    async def call(self, input_data: dict, context: ToolUseContext, on_progress=None) -> ToolResult:
        path = input_data["path"]
        try:
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()
            old = input_data["old_string"]
            if content.count(old) == 0:
                return ToolResult(content=f"old_string not found in {path}", is_error=True)
            if content.count(old) > 1:
                return ToolResult(content=f"old_string matches {content.count(old)} locations", is_error=True)
            new_content = content.replace(old, input_data["new_string"], 1)
            with open(path, "w", encoding="utf-8") as f:
                f.write(new_content)
            return ToolResult(content=f"Successfully edited {path}")
        except Exception as e:
            return ToolResult(content=str(e), is_error=True)


# ─── BashTool (借鉴 BashTool.ts) ───

class BashTool(Tool):
    TIMEOUT = 120

    @property
    def name(self) -> str:
        return "bash"

    async def description(self, input_data: dict) -> str:
        cmd = input_data.get("command", "")
        return f"Run: {cmd[:60]}{'...' if len(cmd) > 60 else ''}"

    def input_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "command": {"type": "string"},
                "timeout": {"type": "integer"},
            },
            "required": ["command"],
        }

    async def call(self, input_data: dict, context: ToolUseContext, on_progress=None) -> ToolResult:
        command = input_data["command"]
        timeout = input_data.get("timeout", self.TIMEOUT)
        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            output = stdout.decode("utf-8", errors="replace")
            if stderr:
                output += "\nSTDERR:\n" + stderr.decode("utf-8", errors="replace")
            if proc.returncode != 0:
                output = f"Exit code: {proc.returncode}\n{output}"
            return ToolResult(content=output, is_error=proc.returncode != 0)
        except asyncio.TimeoutError:
            return ToolResult(content=f"Command timed out after {timeout}s", is_error=True)
        except Exception as e:
            return ToolResult(content=str(e), is_error=True)

    @property
    def max_result_size_chars(self) -> int:
        return 30_000


# ─── GrepTool (借鉴 GrepTool.ts) ───

class GrepTool(Tool):
    @property
    def name(self) -> str:
        return "grep"

    async def description(self, input_data: dict) -> str:
        return f"Search for '{input_data.get('pattern', '')}'"

    def input_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "pattern": {"type": "string"},
                "path": {"type": "string", "default": "."},
                "include": {"type": "string"},
            },
            "required": ["pattern"],
        }

    async def call(self, input_data: dict, context: ToolUseContext, on_progress=None) -> ToolResult:
        pattern = input_data["pattern"]
        path = input_data.get("path", ".")
        include = input_data.get("include", "")
        cmd = f"grep -rn '{pattern}' {path}"
        if include:
            cmd += f" --include='{include}'"
        cmd += " 2>/dev/null | head -50"
        try:
            proc = await asyncio.create_subprocess_shell(
                cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=30)
            output = stdout.decode("utf-8", errors="replace")
            return ToolResult(content=output or "No matches found.")
        except Exception as e:
            return ToolResult(content=str(e), is_error=True)

    def is_read_only(self, input_data: dict) -> bool:
        return True

    @property
    def max_result_size_chars(self) -> int:
        return 50_000


# ─── GlobTool (借鉴 GlobTool.ts) ───

class GlobTool(Tool):
    @property
    def name(self) -> str:
        return "glob"

    async def description(self, input_data: dict) -> str:
        return f"Find files matching '{input_data.get('pattern', '')}'"

    def input_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {"pattern": {"type": "string"}},
            "required": ["pattern"],
        }

    async def call(self, input_data: dict, context: ToolUseContext, on_progress=None) -> ToolResult:
        pattern = input_data["pattern"]
        matches = glob.glob(pattern, recursive=True)
        if not matches:
            return ToolResult(content="No files found.")
        return ToolResult(content="\n".join(sorted(matches)[:100]))

    def is_read_only(self, input_data: dict) -> bool:
        return True


# ─── AskUserTool (借鉴 AskUserQuestionTool.ts) ───

class AskUserTool(Tool):
    """
    向用户提问工具。
    交互模式: 从 stdin 读取用户输入
    非交互模式: 返回等待提示 (由上层处理)
    """

    def __init__(self, interactive: bool = False):
        self._interactive = interactive

    @property
    def name(self) -> str:
        return "ask_user"

    async def description(self, input_data: dict) -> str:
        return "Ask the user a question"

    def input_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {"question": {"type": "string"}},
            "required": ["question"],
        }

    async def call(self, input_data: dict, context: ToolUseContext, on_progress=None) -> ToolResult:
        question = input_data["question"]
        if self._interactive:
            import sys
            print(f"\n🤖 Agent asks: {question}")
            print("Your answer (press Enter): ", end="", flush=True)
            try:
                loop = __import__("asyncio").get_event_loop()
                answer = await loop.run_in_executor(None, sys.stdin.readline)
                answer = answer.strip()
                if not answer:
                    answer = "[No response from user]"
                return ToolResult(content=answer)
            except Exception:
                return ToolResult(content="[Failed to read user input]", is_error=True)
        else:
            return ToolResult(content=f"[Waiting for user response to: {question}]")


# ─── WebFetchTool (借鉴 WebFetchTool.ts) ───

class WebFetchTool(Tool):
    """
    获取网页内容。使用 urllib 实现真实 HTTP 请求，
    支持 HTML 文本提取 (去除标签)。
    借鉴 src/tools/WebFetchTool/WebFetchTool.ts
    """

    @property
    def name(self) -> str:
        return "web_fetch"

    async def description(self, input_data: dict) -> str:
        return f"Fetch {input_data.get('url', 'URL')}"

    def input_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "URL to fetch"},
                "max_chars": {"type": "integer", "description": "Max response chars (default 50000)"},
            },
            "required": ["url"],
        }

    def validate_input(self, input_data: dict) -> ValidationResult:
        url = input_data.get("url", "")
        if not url.startswith(("http://", "https://")):
            return ValidationResult(valid=False, message="URL must start with http:// or https://")
        return ValidationResult(valid=True)

    async def call(self, input_data: dict, context: ToolUseContext, on_progress=None) -> ToolResult:
        import urllib.request
        import urllib.error
        url = input_data["url"]
        max_chars = input_data.get("max_chars", 50_000)
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "AgentFramework/1.0"})
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None, lambda: urllib.request.urlopen(req, timeout=30)
            )
            raw = response.read()
            charset = response.headers.get_content_charset() or "utf-8"
            text = raw.decode(charset, errors="replace")

            # 简易 HTML 标签剥离
            content_type = response.headers.get("Content-Type", "")
            if "html" in content_type.lower():
                text = _strip_html_tags(text)

            if len(text) > max_chars:
                text = text[:max_chars] + f"\n\n[Truncated at {max_chars:,} chars]"
            return ToolResult(content=text)
        except urllib.error.HTTPError as e:
            return ToolResult(content=f"HTTP {e.code}: {e.reason}", is_error=True)
        except Exception as e:
            return ToolResult(content=f"Fetch error: {e}", is_error=True)

    def is_read_only(self, input_data: dict) -> bool:
        return True

    @property
    def max_result_size_chars(self) -> int:
        return 50_000

    def prompt(self) -> str:
        return "Fetch content from a URL. Returns text content with HTML tags stripped."


def _strip_html_tags(html: str) -> str:
    """去除 HTML 标签，保留文本内容"""
    import re as _re
    # 移除 script/style 块
    text = _re.sub(r'<(script|style)[^>]*>.*?</\1>', '', html, flags=_re.DOTALL | _re.IGNORECASE)
    # 移除所有标签
    text = _re.sub(r'<[^>]+>', ' ', text)
    # 合并空白
    text = _re.sub(r'\s+', ' ', text).strip()
    return text


# ─── WebSearchTool (借鉴 WebSearchTool.ts) ───

class WebSearchTool(Tool):
    """
    Web 搜索工具。使用 DuckDuckGo HTML 搜索实现真实搜索，
    无需 API key。
    借鉴 src/tools/WebSearchTool/WebSearchTool.ts
    """

    @property
    def name(self) -> str:
        return "web_search"

    async def description(self, input_data: dict) -> str:
        return f"Search: {input_data.get('query', '')}"

    def input_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"},
                "max_results": {"type": "integer", "description": "Max results (default 5)"},
            },
            "required": ["query"],
        }

    async def call(self, input_data: dict, context: ToolUseContext, on_progress=None) -> ToolResult:
        import urllib.request
        import urllib.parse
        query = input_data["query"]
        max_results = input_data.get("max_results", 5)
        try:
            encoded = urllib.parse.quote_plus(query)
            url = f"https://html.duckduckgo.com/html/?q={encoded}"
            req = urllib.request.Request(url, headers={"User-Agent": "AgentFramework/1.0"})
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None, lambda: urllib.request.urlopen(req, timeout=15)
            )
            html = response.read().decode("utf-8", errors="replace")
            results = self._parse_ddg_results(html, max_results)
            if not results:
                return ToolResult(content=f"No results found for: {query}")
            output = f"Search results for: {query}\n\n"
            for i, r in enumerate(results, 1):
                output += f"{i}. {r['title']}\n   {r['url']}\n   {r['snippet']}\n\n"
            return ToolResult(content=output)
        except Exception as e:
            return ToolResult(content=f"Search error: {e}", is_error=True)

    def _parse_ddg_results(self, html: str, max_results: int) -> list[dict]:
        """从 DuckDuckGo HTML 结果页面提取搜索结果"""
        import re as _re
        results = []
        # 匹配结果链接
        links = _re.findall(
            r'<a[^>]+class="result__a"[^>]*href="([^"]*)"[^>]*>(.*?)</a>',
            html, _re.DOTALL
        )
        snippets = _re.findall(
            r'<a[^>]+class="result__snippet"[^>]*>(.*?)</a>',
            html, _re.DOTALL
        )
        for i, (url, title) in enumerate(links[:max_results]):
            snippet = _strip_html_tags(snippets[i]) if i < len(snippets) else ""
            title = _strip_html_tags(title)
            # DuckDuckGo 的 URL 是重定向链接，提取真实 URL
            real_url = url
            if "uddg=" in url:
                import urllib.parse as _up
                parsed = _up.parse_qs(_up.urlparse(url).query)
                real_url = parsed.get("uddg", [url])[0]
            results.append({"title": title, "url": real_url, "snippet": snippet})
        return results

    def is_read_only(self, input_data: dict) -> bool:
        return True

    @property
    def max_result_size_chars(self) -> int:
        return 30_000

    def prompt(self) -> str:
        return "Search the web using DuckDuckGo. Returns titles, URLs, and snippets."


# ─── TodoWriteTool (借鉴 TodoWriteTool.ts) ───

class TodoWriteTool(Tool):
    """
    待办事项管理工具。读写 .agent-todo.md 文件。
    借鉴 src/tools/TodoWriteTool/TodoWriteTool.ts
    """

    TODO_FILE = ".agent-todo.md"

    @property
    def name(self) -> str:
        return "todo_write"

    async def description(self, input_data: dict) -> str:
        action = input_data.get("action", "update")
        return f"Todo: {action}"

    def input_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["read", "add", "complete", "remove", "clear"],
                    "description": "Action to perform",
                },
                "content": {"type": "string", "description": "Todo item text (for add)"},
                "index": {"type": "integer", "description": "Item index (for complete/remove, 1-based)"},
            },
            "required": ["action"],
        }

    async def call(self, input_data: dict, context: ToolUseContext, on_progress=None) -> ToolResult:
        action = input_data["action"]
        try:
            items = self._load_todos()

            if action == "read":
                if not items:
                    return ToolResult(content="No todo items.")
                lines = []
                for i, item in enumerate(items, 1):
                    status = "✅" if item["done"] else "⬜"
                    lines.append(f"{i}. {status} {item['text']}")
                return ToolResult(content="\n".join(lines))

            elif action == "add":
                text = input_data.get("content", "").strip()
                if not text:
                    return ToolResult(content="No content provided", is_error=True)
                items.append({"text": text, "done": False})
                self._save_todos(items)
                return ToolResult(content=f"Added: {text} (total: {len(items)} items)")

            elif action == "complete":
                idx = input_data.get("index", 0) - 1
                if 0 <= idx < len(items):
                    items[idx]["done"] = True
                    self._save_todos(items)
                    return ToolResult(content=f"Completed: {items[idx]['text']}")
                return ToolResult(content=f"Invalid index: {idx + 1}", is_error=True)

            elif action == "remove":
                idx = input_data.get("index", 0) - 1
                if 0 <= idx < len(items):
                    removed = items.pop(idx)
                    self._save_todos(items)
                    return ToolResult(content=f"Removed: {removed['text']}")
                return ToolResult(content=f"Invalid index: {idx + 1}", is_error=True)

            elif action == "clear":
                self._save_todos([])
                return ToolResult(content=f"Cleared {len(items)} items")

            return ToolResult(content=f"Unknown action: {action}", is_error=True)
        except Exception as e:
            return ToolResult(content=f"Todo error: {e}", is_error=True)

    def _load_todos(self) -> list[dict]:
        p = Path(self.TODO_FILE)
        if not p.exists():
            return []
        items = []
        for line in p.read_text().strip().split("\n"):
            line = line.strip()
            if line.startswith("- [x]"):
                items.append({"text": line[6:].strip(), "done": True})
            elif line.startswith("- [ ]"):
                items.append({"text": line[6:].strip(), "done": False})
            elif line.startswith("- "):
                items.append({"text": line[2:].strip(), "done": False})
        return items

    def _save_todos(self, items: list[dict]) -> None:
        lines = ["# Agent Todo\n"]
        for item in items:
            check = "x" if item["done"] else " "
            lines.append(f"- [{check}] {item['text']}")
        Path(self.TODO_FILE).write_text("\n".join(lines) + "\n")

    def prompt(self) -> str:
        return "Manage a todo list. Actions: read, add, complete, remove, clear."


# ─── SendMessageTool (借鉴 SendMessageTool.ts) ───

class SendMessageTool(Tool):
    """
    向已有子 Agent 发送后续消息。
    借鉴 src/tools/SendMessageTool/SendMessageTool.ts
    在当前实现中，通过 coordinator context 的 worker 注册表路由消息。
    """

    @property
    def name(self) -> str:
        return "send_message"

    async def description(self, input_data: dict) -> str:
        return f"Send message to agent {input_data.get('to', '')}"

    def input_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "to": {"type": "string", "description": "Agent ID or name to send to"},
                "message": {"type": "string", "description": "Message content"},
            },
            "required": ["to", "message"],
        }

    async def call(self, input_data: dict, context: ToolUseContext, on_progress=None) -> ToolResult:
        to = input_data["to"]
        message = input_data["message"]
        # 在完整实现中，这会通过 coordinator 的 worker 注册表
        # 找到目标 agent 并注入消息到其消息队列
        return ToolResult(
            content=f"Message sent to {to}: {message[:200]}",
            metadata={"to": to, "message": message},
        )

    def prompt(self) -> str:
        return (
            "Send a follow-up message to an existing agent. "
            "Use the agent's ID (from a previous Agent tool call) as the 'to' field."
        )


# ─── TaskStopTool (借鉴 TaskStopTool.ts) ───

class TaskStopTool(Tool):
    """
    停止一个正在运行的子 Agent/Task。
    借鉴 src/tools/TaskStopTool/TaskStopTool.ts
    """

    @property
    def name(self) -> str:
        return "task_stop"

    async def description(self, input_data: dict) -> str:
        return f"Stop task {input_data.get('task_id', '')}"

    def input_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "task_id": {"type": "string", "description": "Task/Agent ID to stop"},
                "reason": {"type": "string", "description": "Reason for stopping"},
            },
            "required": ["task_id"],
        }

    async def call(self, input_data: dict, context: ToolUseContext, on_progress=None) -> ToolResult:
        task_id = input_data["task_id"]
        reason = input_data.get("reason", "Stopped by coordinator")
        return ToolResult(
            content=f"Task {task_id} stopped. Reason: {reason}",
            metadata={"task_id": task_id, "reason": reason},
        )

    def prompt(self) -> str:
        return "Stop a running agent or task by its ID."


# ─── NotebookEditTool (借鉴 NotebookEditTool.ts) ───

class NotebookEditTool(Tool):
    """
    Jupyter Notebook (.ipynb) 编辑工具。
    支持读取、添加 cell、编辑 cell、删除 cell。
    借鉴 src/tools/NotebookEditTool/NotebookEditTool.ts
    """

    @property
    def name(self) -> str:
        return "notebook_edit"

    async def description(self, input_data: dict) -> str:
        return f"Edit notebook {input_data.get('path', '')}"

    def input_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Path to .ipynb file"},
                "action": {
                    "type": "string",
                    "enum": ["read", "add_cell", "edit_cell", "delete_cell"],
                },
                "cell_index": {"type": "integer", "description": "Cell index (0-based)"},
                "cell_type": {"type": "string", "enum": ["code", "markdown"], "description": "Cell type for add"},
                "content": {"type": "string", "description": "Cell content"},
            },
            "required": ["path", "action"],
        }

    async def call(self, input_data: dict, context: ToolUseContext, on_progress=None) -> ToolResult:
        path = input_data["path"]
        action = input_data["action"]
        try:
            if action == "read":
                return self._read_notebook(path)
            nb = self._load_notebook(path)
            cells = nb.get("cells", [])

            if action == "add_cell":
                cell_type = input_data.get("cell_type", "code")
                content = input_data.get("content", "")
                new_cell = {
                    "cell_type": cell_type,
                    "source": content.split("\n"),
                    "metadata": {},
                }
                if cell_type == "code":
                    new_cell["outputs"] = []
                    new_cell["execution_count"] = None
                cells.append(new_cell)
                nb["cells"] = cells
                self._save_notebook(path, nb)
                return ToolResult(content=f"Added {cell_type} cell at index {len(cells) - 1}")

            elif action == "edit_cell":
                idx = input_data.get("cell_index", 0)
                if 0 <= idx < len(cells):
                    content = input_data.get("content", "")
                    cells[idx]["source"] = content.split("\n")
                    self._save_notebook(path, nb)
                    return ToolResult(content=f"Edited cell {idx}")
                return ToolResult(content=f"Invalid cell index: {idx}", is_error=True)

            elif action == "delete_cell":
                idx = input_data.get("cell_index", 0)
                if 0 <= idx < len(cells):
                    cells.pop(idx)
                    self._save_notebook(path, nb)
                    return ToolResult(content=f"Deleted cell {idx}")
                return ToolResult(content=f"Invalid cell index: {idx}", is_error=True)

            return ToolResult(content=f"Unknown action: {action}", is_error=True)
        except Exception as e:
            return ToolResult(content=f"Notebook error: {e}", is_error=True)

    def _load_notebook(self, path: str) -> dict:
        import json as _json
        with open(path, "r", encoding="utf-8") as f:
            return _json.load(f)

    def _save_notebook(self, path: str, nb: dict) -> None:
        import json as _json
        with open(path, "w", encoding="utf-8") as f:
            _json.dump(nb, f, indent=1, ensure_ascii=False)

    def _read_notebook(self, path: str) -> ToolResult:
        nb = self._load_notebook(path)
        cells = nb.get("cells", [])
        lines = [f"Notebook: {path} ({len(cells)} cells)\n"]
        for i, cell in enumerate(cells):
            ct = cell.get("cell_type", "unknown")
            source = "".join(cell.get("source", []))
            preview = source[:200].replace("\n", "\\n")
            lines.append(f"[{i}] {ct}: {preview}")
        return ToolResult(content="\n".join(lines))

    def is_destructive(self, input_data: dict) -> bool:
        return input_data.get("action") != "read"

    @property
    def search_hint(self) -> str:
        return "jupyter notebook ipynb"

    def prompt(self) -> str:
        return "Edit Jupyter notebooks (.ipynb). Actions: read, add_cell, edit_cell, delete_cell."


def register_builtin_tools(registry) -> None:
    """注册所有内置工具 (借鉴 tools.ts:getAllBaseTools)"""
    for tool_cls in [
        FileReadTool, FileWriteTool, FileEditTool,
        BashTool, GrepTool, GlobTool,
        AskUserTool,
        WebFetchTool, WebSearchTool,
        TodoWriteTool,
        SendMessageTool, TaskStopTool,
        NotebookEditTool,
    ]:
        registry.register(tool_cls())
