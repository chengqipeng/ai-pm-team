"""
Wiki (Confluence) MCP Server — Basic Auth + REST API
"""
import asyncio
import os
import re
import sys

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp import types
import requests
from requests.auth import HTTPBasicAuth

WIKI_URL = os.environ.get("WIKI_URL", "https://wiki.ingageapp.com").rstrip("/")
WIKI_USER = os.environ.get("WIKI_USER", "")
WIKI_PASS = os.environ.get("WIKI_PASS", "")

app = Server("wiki-mcp")
_auth = None


def _get_auth():
    global _auth
    if _auth is None:
        _auth = HTTPBasicAuth(WIKI_USER, WIKI_PASS)
    return _auth


def _get(path, params=None):
    r = requests.get(f"{WIKI_URL}/rest/api/{path}", params=params, auth=_get_auth(), verify=False, timeout=30)
    r.raise_for_status()
    return r.json()


def _post(path, data):
    r = requests.post(f"{WIKI_URL}/rest/api/{path}", json=data, auth=_get_auth(), verify=False, timeout=30,
                      headers={"Content-Type": "application/json"})
    r.raise_for_status()
    return r.json()


def _put(path, data):
    r = requests.put(f"{WIKI_URL}/rest/api/{path}", json=data, auth=_get_auth(), verify=False, timeout=30,
                     headers={"Content-Type": "application/json"})
    r.raise_for_status()
    return r.json()


def _delete(path):
    r = requests.delete(f"{WIKI_URL}/rest/api/{path}", auth=_get_auth(), verify=False, timeout=30)
    r.raise_for_status()


def html_to_md(html):
    if not html:
        return ""
    t = html
    for i in range(1, 7):
        t = re.sub(rf"<h{i}[^>]*>(.*?)</h{i}>", lambda m, n=i: f"\n{'#'*n} {m.group(1).strip()}\n", t, flags=re.DOTALL)
    def cvt_table(m):
        rows = re.findall(r"<tr[^>]*>(.*?)</tr>", m.group(0), re.DOTALL)
        md = []
        for idx, row in enumerate(rows):
            cells = [re.sub(r"<[^>]+>", "", c).strip() for c in re.findall(r"<t[hd][^>]*>(.*?)</t[hd]>", row, re.DOTALL)]
            md.append("| " + " | ".join(cells) + " |")
            if idx == 0:
                md.append("| " + " | ".join(["---"]*len(cells)) + " |")
        return "\n" + "\n".join(md) + "\n"
    t = re.sub(r"<table[^>]*>.*?</table>", cvt_table, t, flags=re.DOTALL)
    t = re.sub(r"<li[^>]*>(.*?)</li>", r"\n- \1", t, flags=re.DOTALL)
    t = re.sub(r"<[uo]l[^>]*>|</[uo]l>", "", t)
    t = re.sub(r'<ac:structured-macro[^>]*ac:name="code"[^>]*>.*?<ac:plain-text-body>\s*<!\[CDATA\[(.*?)\]\]>\s*</ac:plain-text-body>\s*</ac:structured-macro>',
               lambda m: f"\n```\n{m.group(1)}\n```\n", t, flags=re.DOTALL)
    t = re.sub(r"<strong[^>]*>(.*?)</strong>", r"**\1**", t, flags=re.DOTALL)
    t = re.sub(r"<em[^>]*>(.*?)</em>", r"*\1*", t, flags=re.DOTALL)
    t = re.sub(r'<a[^>]*href="([^"]*)"[^>]*>(.*?)</a>', r"[\2](\1)", t, flags=re.DOTALL)
    t = re.sub(r"<br\s*/?>", "\n", t)
    t = re.sub(r"<p[^>]*>", "\n", t)
    t = re.sub(r"</p>", "\n", t)
    t = re.sub(r"<ac:structured-macro[^>]*>.*?</ac:structured-macro>", "", t, flags=re.DOTALL)
    t = re.sub(r"<ac:[^>]*>|</ac:[^>]*>|<ri:[^>]*>|</ri:[^>]*>", "", t)
    t = re.sub(r"<[^>]+>", "", t)
    t = re.sub(r"\n{3,}", "\n\n", t)
    return t.strip()


def _page_tree(pid, depth=3, cur=0):
    if cur >= depth:
        return []
    data = _get(f"content/{pid}/child/page", {"limit": 100, "expand": "version"})
    out = []
    for c in data.get("results", []):
        ch = _page_tree(c["id"], depth, cur+1)
        out.append({"id": c["id"], "title": c["title"], "depth": cur+1, "children": ch, "n": len(ch)})
    return out


def _flat_tree(tree, indent=0):
    lines = []
    for n in tree:
        sfx = f" ({n['n']} 子页面)" if n['n'] else ""
        lines.append(f"{'  '*indent}- [ID:{n['id']}] {n['title']}{sfx}")
        lines.extend(_flat_tree(n["children"], indent+1))
    return lines


@app.list_tools()
async def list_tools():
    return [
        types.Tool(name="wiki_search", description="搜索 Wiki，支持关键词或 CQL",
                   inputSchema={"type": "object", "properties": {
                       "query": {"type": "string"}, "cql": {"type": "string"},
                       "space_key": {"type": "string"}, "limit": {"type": "integer", "default": 10}}}),
        types.Tool(name="wiki_get_page", description="读取页面（→ Markdown）",
                   inputSchema={"type": "object", "properties": {"page_id": {"type": "string"}, "max_length": {"type": "integer", "default": 0}}, "required": ["page_id"]}),
        types.Tool(name="wiki_get_page_tree", description="子页面树",
                   inputSchema={"type": "object", "properties": {"page_id": {"type": "string"}, "depth": {"type": "integer", "default": 3}}, "required": ["page_id"]}),
        types.Tool(name="wiki_batch_get_pages", description="批量读取页面",
                   inputSchema={"type": "object", "properties": {"page_ids": {"type": "array", "items": {"type": "string"}}, "max_length_per_page": {"type": "integer", "default": 0}}, "required": ["page_ids"]}),
        types.Tool(name="wiki_create_page", description="创建页面",
                   inputSchema={"type": "object", "properties": {"space_key": {"type": "string"}, "title": {"type": "string"}, "content": {"type": "string"}, "parent_id": {"type": "string"}}, "required": ["space_key", "title", "content"]}),
        types.Tool(name="wiki_update_page", description="更新页面",
                   inputSchema={"type": "object", "properties": {"page_id": {"type": "string"}, "title": {"type": "string"}, "content": {"type": "string"}}, "required": ["page_id", "title", "content"]}),
        types.Tool(name="wiki_delete_page", description="删除页面",
                   inputSchema={"type": "object", "properties": {"page_id": {"type": "string"}}, "required": ["page_id"]}),
        types.Tool(name="wiki_add_comment", description="添加评论",
                   inputSchema={"type": "object", "properties": {"page_id": {"type": "string"}, "comment": {"type": "string"}}, "required": ["page_id", "comment"]}),
        types.Tool(name="wiki_get_attachments", description="附件列表",
                   inputSchema={"type": "object", "properties": {"page_id": {"type": "string"}}, "required": ["page_id"]}),
    ]


@app.call_tool()
async def call_tool(name, arguments):
    try:
        if name == "wiki_search":
            cql = arguments.get("cql")
            if not cql:
                q = arguments.get("query", "")
                sk = arguments.get("space_key")
                cql = f'text ~ "{q}"'
                if sk:
                    cql += f' AND space = "{sk}"'
            data = _get("content/search", {"cql": cql, "limit": arguments.get("limit", 10), "expand": "space,version"})
            rs = data.get("results", [])
            if not rs:
                return [types.TextContent(type="text", text="未找到")]
            lines = [f"共 {data.get('totalSize', len(rs))} 条（显示 {len(rs)} 条）\n"]
            for r in rs:
                lines.append(f"  [ID:{r['id']}] [{r.get('space',{}).get('key','-')}] {r['title']}")
                lines.append(f"    修改: {(r.get('version',{}).get('when') or '-')[:10]} | {WIKI_URL}{r['_links'].get('webui','')}")
            return [types.TextContent(type="text", text="\n".join(lines))]

        elif name == "wiki_get_page":
            data = _get(f"content/{arguments['page_id']}", {"expand": "body.storage,version,space,ancestors"})
            text = html_to_md(data.get("body",{}).get("storage",{}).get("value",""))
            ml = arguments.get("max_length", 0)
            trunc = ml and ml > 0 and len(text) > ml
            if trunc:
                text = text[:ml]
            anc = data.get("ancestors", [])
            bc = " > ".join([a["title"] for a in anc] + [data["title"]])
            hdr = f"# {data['title']}\n\n- 空间: {data.get('space',{}).get('name','-')}\n- 路径: {bc}\n- 版本: v{data.get('version',{}).get('number','-')}\n- 修改: {(data.get('version',{}).get('when') or '-')[:10]}\n- 链接: {WIKI_URL}{data['_links'].get('webui','')}\n\n---\n\n"
            return [types.TextContent(type="text", text=hdr + text + ("\n\n---\n*（已截断）*" if trunc else ""))]

        elif name == "wiki_get_page_tree":
            pd = _get(f"content/{arguments['page_id']}", {"expand": "space"})
            tree = _page_tree(arguments["page_id"], arguments.get("depth", 3))
            lines = _flat_tree(tree)
            return [types.TextContent(type="text", text=f"页面树：{pd['title']}\n子页面数：{len(lines)}\n\n" + ("\n".join(lines) if lines else "无子页面"))]

        elif name == "wiki_batch_get_pages":
            pids = arguments["page_ids"][:10]
            ml = arguments.get("max_length_per_page", 0)
            parts = []
            for pid in pids:
                try:
                    d = _get(f"content/{pid}", {"expand": "body.storage,version,space"})
                    t = html_to_md(d.get("body",{}).get("storage",{}).get("value",""))
                    if ml and ml > 0 and len(t) > ml:
                        t = t[:ml] + "\n\n*（已截断）*"
                    parts.append(f"## {d['title']} (ID:{pid})\n\n{t}")
                except Exception as e:
                    parts.append(f"## 页面 {pid} 失败: {e}")
            return [types.TextContent(type="text", text="\n\n---\n\n".join(parts))]

        elif name == "wiki_create_page":
            body = {"type": "page", "title": arguments["title"], "space": {"key": arguments["space_key"]},
                    "body": {"storage": {"value": arguments["content"], "representation": "storage"}}}
            if arguments.get("parent_id"):
                body["ancestors"] = [{"id": arguments["parent_id"]}]
            d = _post("content", body)
            return [types.TextContent(type="text", text=f"创建成功！ID: {d['id']}\n{WIKI_URL}{d['_links'].get('webui','')}")]

        elif name == "wiki_update_page":
            cur = _get(f"content/{arguments['page_id']}", {"expand": "version"})
            nv = cur["version"]["number"] + 1
            d = _put(f"content/{arguments['page_id']}", {"type": "page", "title": arguments["title"],
                     "version": {"number": nv}, "body": {"storage": {"value": arguments["content"], "representation": "storage"}}})
            return [types.TextContent(type="text", text=f"更新成功！v{nv}\n{WIKI_URL}{d['_links'].get('webui','')}")]

        elif name == "wiki_delete_page":
            _delete(f"content/{arguments['page_id']}")
            return [types.TextContent(type="text", text=f"页面 {arguments['page_id']} 已删除")]

        elif name == "wiki_add_comment":
            d = _post("content", {"type": "comment", "container": {"id": arguments["page_id"], "type": "page"},
                      "body": {"storage": {"value": arguments["comment"], "representation": "storage"}}})
            return [types.TextContent(type="text", text=f"评论成功 (ID: {d['id']})")]

        elif name == "wiki_get_attachments":
            data = _get(f"content/{arguments['page_id']}/child/attachment", {"limit": 50})
            rs = data.get("results", [])
            if not rs:
                return [types.TextContent(type="text", text="无附件")]
            lines = [f"共 {len(rs)} 个附件：\n"]
            for a in rs:
                lines.append(f"  [{a['title']}] {a.get('extensions',{}).get('mediaType','-')} | {a.get('extensions',{}).get('fileSize',0)/1024:.1f} KB")
            return [types.TextContent(type="text", text="\n".join(lines))]

        return [types.TextContent(type="text", text=f"未知工具: {name}")]
    except Exception as e:
        return [types.TextContent(type="text", text=f"错误: {e}")]


async def main():
    async with stdio_server() as (r, w):
        await app.run(r, w, app.create_initialization_options())

if __name__ == "__main__":
    asyncio.run(main())
