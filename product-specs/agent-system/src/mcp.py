"""
MCP (Model Context Protocol) 集成 — 借鉴 services/mcp/

MCP 允许通过标准协议连接外部工具服务器，动态扩展 Agent 的工具集。

借鉴源码:
  - src/services/mcp/client.ts: getMcpToolsCommandsAndResources
  - src/services/mcp/types.ts: McpServerConfig, MCPServerConnection
  - src/tools/MCPTool/MCPTool.ts: MCP 工具代理
  - src/tools/ListMcpResourcesTool/: 列出 MCP 资源
  - src/tools/ReadMcpResourceTool/: 读取 MCP 资源
"""
from __future__ import annotations

import json
import logging
import asyncio
from dataclasses import dataclass, field
from typing import Any

from .types import ToolResult, ValidationResult, PermissionDecision, PermissionBehavior
from .tools import Tool, ToolUseContext

logger = logging.getLogger(__name__)


# ─── MCP Server 配置 (借鉴 services/mcp/types.ts) ───

@dataclass
class McpServerConfig:
    """MCP 服务器配置"""
    name: str
    command: str                          # 启动命令 (如 "uvx")
    args: list[str] = field(default_factory=list)  # 命令参数
    env: dict[str, str] = field(default_factory=dict)  # 环境变量
    disabled: bool = False
    auto_approve: list[str] = field(default_factory=list)  # 自动批准的工具


@dataclass
class McpToolDefinition:
    """MCP 工具定义 (从 MCP 服务器获取)"""
    name: str                             # 工具名 (如 "mcp__server__tool")
    description: str
    input_schema: dict[str, Any]          # JSON Schema
    server_name: str                      # 所属服务器名


@dataclass
class McpResource:
    """MCP 资源定义"""
    uri: str
    name: str
    description: str = ""
    mime_type: str = "text/plain"
    server_name: str = ""


# ─── MCP 连接状态 ───

class McpConnectionStatus:
    CONNECTED = "connected"
    PENDING = "pending"
    DISCONNECTED = "disconnected"
    ERROR = "error"


@dataclass
class McpServerConnection:
    """MCP 服务器连接状态 (借鉴 services/mcp/types.ts:MCPServerConnection)"""
    name: str
    config: McpServerConfig
    status: str = McpConnectionStatus.DISCONNECTED
    tools: list[McpToolDefinition] = field(default_factory=list)
    resources: list[McpResource] = field(default_factory=list)
    error: str | None = None
    process: Any = None  # subprocess handle


# ─── MCP Client Manager ───

class McpClientManager:
    """
    MCP 客户端管理器 (借鉴 services/mcp/client.ts)
    管理多个 MCP 服务器的连接、工具发现、调用代理
    """

    def __init__(self):
        self._connections: dict[str, McpServerConnection] = {}

    async def connect(self, config: McpServerConfig) -> McpServerConnection:
        """
        连接到 MCP 服务器 (借鉴 services/mcp/client.ts)
        启动子进程，通过 stdio 通信
        """
        if config.disabled:
            return McpServerConnection(
                name=config.name, config=config,
                status=McpConnectionStatus.DISCONNECTED,
            )

        conn = McpServerConnection(
            name=config.name, config=config,
            status=McpConnectionStatus.PENDING,
        )
        self._connections[config.name] = conn

        try:
            # 启动 MCP 服务器进程
            env = {**dict(__import__("os").environ), **config.env}
            proc = await asyncio.create_subprocess_exec(
                config.command, *config.args,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
            )
            conn.process = proc
            conn.status = McpConnectionStatus.CONNECTED

            # 发送 initialize 请求获取工具列表
            tools = await self._discover_tools(conn)
            conn.tools = tools

            resources = await self._discover_resources(conn)
            conn.resources = resources

            logger.info(
                f"MCP server '{config.name}' connected: "
                f"{len(tools)} tools, {len(resources)} resources"
            )

        except Exception as e:
            conn.status = McpConnectionStatus.ERROR
            conn.error = str(e)
            logger.error(f"Failed to connect MCP server '{config.name}': {e}")

        return conn

    async def disconnect(self, server_name: str) -> None:
        """断开 MCP 服务器"""
        conn = self._connections.get(server_name)
        if conn and conn.process:
            try:
                conn.process.terminate()
                await asyncio.wait_for(conn.process.wait(), timeout=5)
            except Exception:
                conn.process.kill()
            conn.status = McpConnectionStatus.DISCONNECTED
            conn.process = None

    async def disconnect_all(self) -> None:
        """断开所有 MCP 服务器"""
        for name in list(self._connections.keys()):
            await self.disconnect(name)

    def get_all_tools(self) -> list[McpToolDefinition]:
        """获取所有已连接服务器的工具"""
        tools = []
        for conn in self._connections.values():
            if conn.status == McpConnectionStatus.CONNECTED:
                tools.extend(conn.tools)
        return tools

    def get_all_resources(self) -> list[McpResource]:
        """获取所有已连接服务器的资源"""
        resources = []
        for conn in self._connections.values():
            if conn.status == McpConnectionStatus.CONNECTED:
                resources.extend(conn.resources)
        return resources

    def get_connection(self, server_name: str) -> McpServerConnection | None:
        return self._connections.get(server_name)

    @property
    def connected_servers(self) -> list[str]:
        return [
            name for name, conn in self._connections.items()
            if conn.status == McpConnectionStatus.CONNECTED
        ]

    async def call_tool(
        self, server_name: str, tool_name: str, arguments: dict
    ) -> str:
        """
        调用 MCP 工具 (借鉴 MCPTool.ts)
        通过 JSON-RPC 协议与 MCP 服务器通信
        """
        conn = self._connections.get(server_name)
        if not conn or conn.status != McpConnectionStatus.CONNECTED:
            return f"MCP server '{server_name}' not connected"

        if not conn.process or not conn.process.stdin or not conn.process.stdout:
            return f"MCP server '{server_name}' process not available"

        # 构建 JSON-RPC 请求
        request = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": tool_name,
                "arguments": arguments,
            },
        }

        try:
            # 发送请求
            request_bytes = (json.dumps(request) + "\n").encode()
            conn.process.stdin.write(request_bytes)
            await conn.process.stdin.drain()

            # 读取响应
            response_line = await asyncio.wait_for(
                conn.process.stdout.readline(), timeout=30
            )
            response = json.loads(response_line.decode())

            if "error" in response:
                return f"MCP error: {response['error'].get('message', 'unknown')}"

            result = response.get("result", {})
            content_parts = result.get("content", [])
            text_parts = [
                p.get("text", "") for p in content_parts
                if p.get("type") == "text"
            ]
            return "\n".join(text_parts) or json.dumps(result)

        except asyncio.TimeoutError:
            return f"MCP tool call timed out after 30s"
        except Exception as e:
            return f"MCP tool call error: {e}"

    async def _discover_tools(self, conn: McpServerConnection) -> list[McpToolDefinition]:
        """
        发现 MCP 服务器提供的工具 (通过 JSON-RPC tools/list)
        """
        if not conn.process or not conn.process.stdin or not conn.process.stdout:
            return []

        request = {
            "jsonrpc": "2.0",
            "id": 0,
            "method": "tools/list",
            "params": {},
        }
        try:
            request_bytes = (json.dumps(request) + "\n").encode()
            conn.process.stdin.write(request_bytes)
            await conn.process.stdin.drain()

            response_line = await asyncio.wait_for(
                conn.process.stdout.readline(), timeout=10
            )
            response = json.loads(response_line.decode())
            tools_data = response.get("result", {}).get("tools", [])

            tools = []
            for td in tools_data:
                tools.append(McpToolDefinition(
                    name=td.get("name", ""),
                    description=td.get("description", ""),
                    input_schema=td.get("inputSchema", {"type": "object", "properties": {}}),
                    server_name=conn.name,
                ))
            return tools
        except asyncio.TimeoutError:
            logger.warning(f"MCP tools/list timed out for '{conn.name}'")
            return []
        except Exception as e:
            logger.error(f"MCP tools/list failed for '{conn.name}': {e}")
            return []

    async def _discover_resources(self, conn: McpServerConnection) -> list[McpResource]:
        """发现 MCP 服务器提供的资源 (通过 JSON-RPC resources/list)"""
        if not conn.process or not conn.process.stdin or not conn.process.stdout:
            return []

        request = {
            "jsonrpc": "2.0",
            "id": 0,
            "method": "resources/list",
            "params": {},
        }
        try:
            request_bytes = (json.dumps(request) + "\n").encode()
            conn.process.stdin.write(request_bytes)
            await conn.process.stdin.drain()

            response_line = await asyncio.wait_for(
                conn.process.stdout.readline(), timeout=10
            )
            response = json.loads(response_line.decode())
            resources_data = response.get("result", {}).get("resources", [])

            resources = []
            for rd in resources_data:
                resources.append(McpResource(
                    uri=rd.get("uri", ""),
                    name=rd.get("name", ""),
                    description=rd.get("description", ""),
                    mime_type=rd.get("mimeType", "text/plain"),
                    server_name=conn.name,
                ))
            return resources
        except asyncio.TimeoutError:
            logger.warning(f"MCP resources/list timed out for '{conn.name}'")
            return []
        except Exception as e:
            logger.error(f"MCP resources/list failed for '{conn.name}': {e}")
            return []


# ─── MCP Tool 代理 (借鉴 MCPTool.ts) ───

class McpToolProxy(Tool):
    """
    MCP 工具代理 (借鉴 tools/MCPTool/MCPTool.ts)
    将 MCP 服务器的工具包装为本地 Tool 接口
    """

    def __init__(
        self,
        tool_def: McpToolDefinition,
        mcp_manager: McpClientManager,
    ):
        self._tool_def = tool_def
        self._mcp_manager = mcp_manager

    @property
    def name(self) -> str:
        # MCP 工具名格式: mcp__{server}__{tool} (借鉴 MCPTool.ts)
        return f"mcp__{self._tool_def.server_name}__{self._tool_def.name}"

    async def description(self, input_data: dict) -> str:
        return self._tool_def.description

    def input_schema(self) -> dict[str, Any]:
        return self._tool_def.input_schema

    async def call(
        self, input_data: dict, context: ToolUseContext, on_progress=None
    ) -> ToolResult:
        result = await self._mcp_manager.call_tool(
            self._tool_def.server_name,
            self._tool_def.name,
            input_data,
        )
        is_error = result.startswith("MCP error:") or result.startswith("MCP tool call error:")
        return ToolResult(content=result, is_error=is_error)

    def prompt(self) -> str:
        return self._tool_def.description


# ─── MCP 配置加载 (借鉴 .kiro/settings/mcp.json) ───

def load_mcp_configs(config_path: str = ".kiro/settings/mcp.json") -> list[McpServerConfig]:
    """
    从配置文件加载 MCP 服务器配置
    (借鉴 .kiro/settings/mcp.json 格式)
    """
    path = __import__("pathlib").Path(config_path)
    if not path.exists():
        return []

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        servers = data.get("mcpServers", {})
        configs = []
        for name, config in servers.items():
            configs.append(McpServerConfig(
                name=name,
                command=config.get("command", ""),
                args=config.get("args", []),
                env=config.get("env", {}),
                disabled=config.get("disabled", False),
                auto_approve=config.get("autoApprove", []),
            ))
        return configs
    except Exception as e:
        logger.error(f"Failed to load MCP config from {config_path}: {e}")
        return []
