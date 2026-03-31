"""
Confluence Wiki MCP Server - 针对产品设计工作流优化
基于原版增强：大文档完整读取、子页面树、Markdown转换、附件列表、CQL高级搜索
"""
import os
import re
import asyncio
from pathlib import Path
from dotenv import load_dotenv

# 加载脚本同目录下的 .env 文件
load_dotenv(Path(__file__).parent / ".env")
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp import types
import requests
from requests.auth import HTTPBasicAuth

WIKI_URL = os.environ.get("WIKI_URL", "").rstrip("/")
WIKI_USER = os.environ.get("WIKI_USER", "")
WIKI_PASSWORD = os.environ.get("WIKI_PASSWORD", "")

app = Server("confluence-wiki-pm")

# --------------- HTTP helpers ---------------

def api(path: str, params: dict = None) -> dict:
    resp = requests.get(
        f"{WIKI_URL}/rest/api/{path}",
        params=params,
        auth=HTTPBasicAuth(WIKI_USER, WIKI_PASSWORD),
        verify=False,
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def api_post(path: str, data: dict) -> dict:
    resp = requests.post(
        f"{WIKI_URL}/rest/api/{path}",
        json=data,
        auth=HTTPBasicAuth(WIKI_USER, WIKI_PASSWORD),
        headers={"Content-Type": "application/json"},
        verify=False,
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def api_put(path: str, data: dict) -> dict:
    resp = requests.put(
        f"{WIKI_URL}/rest/api/{path}",
        json=data,
        auth=HTTPBasicAuth(WIKI_USER, WIKI_PASSWORD),
        headers={"Content-Type": "application/json"},
        verify=False,
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


# --------------- HTML → Markdown 转换 ---------------

def html_to_markdown(html: str) -> str:
    """将 Confluence storage format HTML 转为可读的 Markdown，保留表格和列表结构。"""
    if not html:
        return ""
    text = html

    # 标题
    for i in range(1, 7):
        text = re.sub(rf"<h{i}[^>]*>(.*?)</h{i}>", lambda m: f"\n{'#' * i} {m.group(1).strip()}\n", text, flags=re.DOTALL)

    # 表格 → Markdown table
    def convert_table(match):
        table_html = match.group(0)
        rows = re.findall(r"<tr[^>]*>(.*?)</tr>", table_html, re.DOTALL)
        md_rows = []
        for idx, row in enumerate(rows):
            cells = re.findall(r"<t[hd][^>]*>(.*?)</t[hd]>", row, re.DOTALL)
            cells = [re.sub(r"<[^>]+>", "", c).strip() for c in cells]
            md_rows.append("| " + " | ".join(cells) + " |")
            if idx == 0:
                md_rows.append("| " + " | ".join(["---"] * len(cells)) + " |")
        return "\n" + "\n".join(md_rows) + "\n"

    text = re.sub(r"<table[^>]*>.*?</table>", convert_table, text, flags=re.DOTALL)

    # 列表
    text = re.sub(r"<li[^>]*>(.*?)</li>", r"\n- \1", text, flags=re.DOTALL)
    text = re.sub(r"<[uo]l[^>]*>", "", text)
    text = re.sub(r"</[uo]l>", "", text)

    # 代码块
    text = re.sub(r'<ac:structured-macro[^>]*ac:name="code"[^>]*>.*?<ac:plain-text-body>\s*<!\[CDATA\[(.*?)\]\]>\s*</ac:plain-text-body>\s*</ac:structured-macro>',
                  lambda m: f"\n```\n{m.group(1)}\n```\n", text, flags=re.DOTALL)

    # 粗体、斜体
    text = re.sub(r"<strong[^>]*>(.*?)</strong>", r"**\1**", text, flags=re.DOTALL)
    text = re.sub(r"<em[^>]*>(.*?)</em>", r"*\1*", text, flags=re.DOTALL)

    # 链接
    text = re.sub(r'<a[^>]*href="([^"]*)"[^>]*>(.*?)</a>', r"[\2](\1)", text, flags=re.DOTALL)

    # 段落和换行
    text = re.sub(r"<br\s*/?>", "\n", text)
    text = re.sub(r"<p[^>]*>", "\n", text)
    text = re.sub(r"</p>", "\n", text)

    # Confluence 宏 - 提取纯文本
    text = re.sub(r"<ac:structured-macro[^>]*>.*?</ac:structured-macro>", "", text, flags=re.DOTALL)
    text = re.sub(r"<ac:[^>]*>", "", text)
    text = re.sub(r"</ac:[^>]*>", "", text)
    text = re.sub(r"<ri:[^>]*>", "", text)
    text = re.sub(r"</ri:[^>]*>", "", text)

    # 清除剩余 HTML 标签
    text = re.sub(r"<[^>]+>", "", text)

    # 清理多余空行
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


# --------------- 子页面树递归 ---------------

def get_page_tree(page_id: str, depth: int = 3, current: int = 0) -> list:
    """递归获取子页面树，返回 [{id, title, depth, children_count}]"""
    if current >= depth:
        return []
    data = api(f"content/{page_id}/child/page", {"limit": 100, "expand": "version"})
    results = []
    for child in data.get("results", []):
        children = get_page_tree(child["id"], depth, current + 1)
        results.append({
            "id": child["id"],
            "title": child["title"],
            "depth": current + 1,
            "children_count": len(children),
            "children": children,
        })
    return results


def flatten_tree(tree: list, indent: int = 0) -> list:
    """将树结构展平为带缩进的文本行"""
    lines = []
    for node in tree:
        prefix = "  " * indent
        lines.append(f"{prefix}- [ID:{node['id']}] {node['title']}" +
                      (f" ({node['children_count']} 子页面)" if node['children_count'] > 0 else ""))
        lines.extend(flatten_tree(node["children"], indent + 1))
    return lines


# --------------- Tool 定义 ---------------

@app.list_tools()
async def list_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name="wiki_list_spaces",
            description="列出所有 Wiki 空间",
            inputSchema={"type": "object", "properties": {
                "limit": {"type": "integer", "description": "返回数量，默认25", "default": 25}
            }},
        ),
        types.Tool(
            name="wiki_search",
            description="搜索 Wiki 内容，支持 CQL 高级查询。示例：text ~ '提示词模板' AND space = 'PROD'",
            inputSchema={"type": "object", "properties": {
                "query": {"type": "string", "description": "搜索关键词（自动包装为 CQL text ~）"},
                "cql": {"type": "string", "description": "直接传入完整 CQL 语句（优先于 query）"},
                "space_key": {"type": "string", "description": "限定搜索空间（可选，与 query 配合使用）"},
                "limit": {"type": "integer", "description": "返回数量，默认10", "default": 10},
            }},
        ),
        types.Tool(
            name="wiki_get_page",
            description="获取指定页面的完整内容，自动转为 Markdown 格式。支持通过 max_length 控制返回长度。",
            inputSchema={"type": "object", "properties": {
                "page_id": {"type": "string", "description": "页面 ID"},
                "max_length": {"type": "integer", "description": "最大返回字符数，默认不限制（0=不限制）", "default": 0},
            }, "required": ["page_id"]},
        ),
        types.Tool(
            name="wiki_get_page_tree",
            description="获取指定页面的子页面树结构，用于了解文档层级。",
            inputSchema={"type": "object", "properties": {
                "page_id": {"type": "string", "description": "父页面 ID"},
                "depth": {"type": "integer", "description": "递归深度，默认3", "default": 3},
            }, "required": ["page_id"]},
        ),
        types.Tool(
            name="wiki_get_pages_by_space",
            description="获取指定空间下的页面列表",
            inputSchema={"type": "object", "properties": {
                "space_key": {"type": "string", "description": "空间 Key，如 DEV"},
                "title": {"type": "string", "description": "按标题过滤（可选）"},
                "limit": {"type": "integer", "description": "返回数量，默认20", "default": 20},
            }, "required": ["space_key"]},
        ),
        types.Tool(
            name="wiki_get_attachments",
            description="获取指定页面的附件列表（图片、文档等）",
            inputSchema={"type": "object", "properties": {
                "page_id": {"type": "string", "description": "页面 ID"},
            }, "required": ["page_id"]},
        ),
        types.Tool(
            name="wiki_batch_get_pages",
            description="批量获取多个页面内容，适合一次性读取多层级文档。返回每个页面的 Markdown 内容。",
            inputSchema={"type": "object", "properties": {
                "page_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "页面 ID 列表，最多10个",
                },
                "max_length_per_page": {"type": "integer", "description": "每个页面最大字符数，默认不限制", "default": 0},
            }, "required": ["page_ids"]},
        ),
        types.Tool(
            name="wiki_create_page",
            description="在指定空间创建新页面",
            inputSchema={"type": "object", "properties": {
                "space_key": {"type": "string", "description": "空间 Key"},
                "title": {"type": "string", "description": "页面标题"},
                "content": {"type": "string", "description": "页面内容（纯文本或 HTML）"},
                "parent_id": {"type": "string", "description": "父页面 ID（可选）"},
            }, "required": ["space_key", "title", "content"]},
        ),
        types.Tool(
            name="wiki_update_page",
            description="更新已有页面内容",
            inputSchema={"type": "object", "properties": {
                "page_id": {"type": "string", "description": "页面 ID"},
                "title": {"type": "string", "description": "新标题"},
                "content": {"type": "string", "description": "新内容（纯文本或 HTML）"},
            }, "required": ["page_id", "title", "content"]},
        ),
        types.Tool(
            name="wiki_add_comment",
            description="给页面添加评论",
            inputSchema={"type": "object", "properties": {
                "page_id": {"type": "string", "description": "页面 ID"},
                "comment": {"type": "string", "description": "评论内容"},
            }, "required": ["page_id", "comment"]},
        ),
    ]


# --------------- Tool 实现 ---------------

@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:
    try:
        if name == "wiki_list_spaces":
            data = api("space", {"limit": arguments.get("limit", 25)})
            lines = [f"共 {len(data['results'])} 个空间：\n"]
            for s in data["results"]:
                lines.append(f"  [{s['key']}] {s['name']} - {WIKI_URL}{s['_links'].get('webui', '')}")
            return [types.TextContent(type="text", text="\n".join(lines))]

        elif name == "wiki_search":
            # 支持直接 CQL 或简单关键词
            cql = arguments.get("cql")
            if not cql:
                query = arguments.get("query", "")
                space_key = arguments.get("space_key")
                cql = f'text ~ "{query}"'
                if space_key:
                    cql += f' AND space = "{space_key}"'

            data = api("content/search", {
                "cql": cql,
                "limit": arguments.get("limit", 10),
                "expand": "space,version",
            })
            results = data.get("results", [])
            if not results:
                return [types.TextContent(type="text", text="未找到相关内容")]
            lines = [f"共找到 {data.get('totalSize', len(results))} 条结果（显示前 {len(results)} 条）：\n"]
            for r in results:
                space = r.get("space", {}).get("key", "-")
                version = r.get("version", {}).get("number", "-")
                modified = r.get("version", {}).get("when", "-")[:10] if r.get("version", {}).get("when") else "-"
                lines.append(
                    f"  [ID:{r['id']}] [{space}] {r['title']}\n"
                    f"    版本: v{version} | 最后修改: {modified}\n"
                    f"    链接: {WIKI_URL}{r['_links'].get('webui', '')}\n"
                )
            return [types.TextContent(type="text", text="\n".join(lines))]

        elif name == "wiki_get_page":
            data = api(f"content/{arguments['page_id']}", {
                "expand": "body.storage,version,space,ancestors",
            })
            body_html = data.get("body", {}).get("storage", {}).get("value", "")
            text = html_to_markdown(body_html)

            max_length = arguments.get("max_length", 0)
            truncated = False
            if max_length and max_length > 0 and len(text) > max_length:
                text = text[:max_length]
                truncated = True

            # 面包屑路径
            ancestors = data.get("ancestors", [])
            breadcrumb = " > ".join([a["title"] for a in ancestors] + [data["title"]]) if ancestors else data["title"]

            header = (
                f"# {data['title']}\n\n"
                f"- 空间: {data.get('space', {}).get('name', '-')}\n"
                f"- 路径: {breadcrumb}\n"
                f"- 版本: v{data.get('version', {}).get('number', '-')}\n"
                f"- 最后修改: {data.get('version', {}).get('when', '-')[:10]}\n"
                f"- 链接: {WIKI_URL}{data['_links'].get('webui', '')}\n"
                f"- 字符数: {len(text)}\n\n"
                f"---\n\n"
            )
            footer = "\n\n---\n*（内容过长已截断，可通过 max_length 参数调整）*" if truncated else ""
            return [types.TextContent(type="text", text=header + text + footer)]

        elif name == "wiki_get_page_tree":
            # 先获取当前页面标题
            page_data = api(f"content/{arguments['page_id']}", {"expand": "space"})
            tree = get_page_tree(arguments["page_id"], arguments.get("depth", 3))
            lines = flatten_tree(tree)
            header = (
                f"页面树：{page_data['title']}\n"
                f"空间：{page_data.get('space', {}).get('name', '-')}\n"
                f"子页面总数：{sum(1 for _ in lines)}\n\n"
            )
            if not lines:
                return [types.TextContent(type="text", text=header + "该页面没有子页面")]
            return [types.TextContent(type="text", text=header + "\n".join(lines))]

        elif name == "wiki_get_pages_by_space":
            params = {"spaceKey": arguments["space_key"], "limit": arguments.get("limit", 20), "expand": "version"}
            if arguments.get("title"):
                params["title"] = arguments["title"]
            data = api("content", params)
            results = data.get("results", [])
            if not results:
                return [types.TextContent(type="text", text="该空间下未找到页面")]
            lines = [f"共 {len(results)} 个页面：\n"]
            for r in results:
                lines.append(f"  [ID:{r['id']}] {r['title']}  链接: {WIKI_URL}{r['_links'].get('webui', '')}")
            return [types.TextContent(type="text", text="\n".join(lines))]

        elif name == "wiki_get_attachments":
            data = api(f"content/{arguments['page_id']}/child/attachment", {"limit": 50})
            results = data.get("results", [])
            if not results:
                return [types.TextContent(type="text", text="该页面没有附件")]
            lines = [f"共 {len(results)} 个附件：\n"]
            for att in results:
                size_kb = att.get("extensions", {}).get("fileSize", 0) / 1024
                media_type = att.get("extensions", {}).get("mediaType", "-")
                download_url = f"{WIKI_URL}{att['_links'].get('download', '')}"
                lines.append(
                    f"  [{att['title']}]\n"
                    f"    类型: {media_type} | 大小: {size_kb:.1f} KB\n"
                    f"    下载: {download_url}\n"
                )
            return [types.TextContent(type="text", text="\n".join(lines))]

        elif name == "wiki_batch_get_pages":
            page_ids = arguments["page_ids"][:10]  # 最多10个
            max_len = arguments.get("max_length_per_page", 0)
            all_results = []
            for pid in page_ids:
                try:
                    data = api(f"content/{pid}", {"expand": "body.storage,version,space"})
                    body_html = data.get("body", {}).get("storage", {}).get("value", "")
                    text = html_to_markdown(body_html)
                    if max_len and max_len > 0 and len(text) > max_len:
                        text = text[:max_len] + "\n\n*（已截断）*"
                    all_results.append(
                        f"## [{data['title']}] (ID:{pid})\n"
                        f"空间: {data.get('space', {}).get('name', '-')} | "
                        f"版本: v{data.get('version', {}).get('number', '-')}\n\n"
                        f"{text}\n"
                    )
                except Exception as e:
                    all_results.append(f"## [页面 {pid}] 读取失败: {str(e)}\n")

            return [types.TextContent(type="text", text=f"批量读取 {len(page_ids)} 个页面：\n\n" + "\n---\n\n".join(all_results))]

        elif name == "wiki_create_page":
            body = {
                "type": "page",
                "title": arguments["title"],
                "space": {"key": arguments["space_key"]},
                "body": {"storage": {"value": arguments["content"], "representation": "storage"}},
            }
            if arguments.get("parent_id"):
                body["ancestors"] = [{"id": arguments["parent_id"]}]
            data = api_post("content", body)
            return [types.TextContent(type="text", text=f"页面创建成功！\nID: {data['id']}\n链接: {WIKI_URL}{data['_links'].get('webui', '')}")]

        elif name == "wiki_update_page":
            current = api(f"content/{arguments['page_id']}", {"expand": "version"})
            new_version = current["version"]["number"] + 1
            body = {
                "type": "page",
                "title": arguments["title"],
                "version": {"number": new_version},
                "body": {"storage": {"value": arguments["content"], "representation": "storage"}},
            }
            data = api_put(f"content/{arguments['page_id']}", body)
            return [types.TextContent(type="text", text=f"页面更新成功！版本: v{new_version}\n链接: {WIKI_URL}{data['_links'].get('webui', '')}")]

        elif name == "wiki_add_comment":
            body = {
                "type": "comment",
                "container": {"id": arguments["page_id"], "type": "page"},
                "body": {"storage": {"value": arguments["comment"], "representation": "storage"}},
            }
            data = api_post("content", body)
            return [types.TextContent(type="text", text=f"评论添加成功！ID: {data['id']}")]

        else:
            return [types.TextContent(type="text", text=f"未知工具: {name}")]

    except requests.exceptions.HTTPError as e:
        status = e.response.status_code if e.response is not None else "unknown"
        return [types.TextContent(type="text", text=f"HTTP 错误 ({status}): {str(e)}")]
    except Exception as e:
        return [types.TextContent(type="text", text=f"错误: {str(e)}")]


async def main():
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
