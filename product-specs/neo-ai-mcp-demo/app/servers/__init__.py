"""MCP Server 注册中心 — 从配置文件加载"""
from app.servers.registry import ServerRegistry
from app.config_loader import load_servers
from app.backend import init_backend

# 全局注册中心
server_registry = ServerRegistry()

# 从配置文件加载 Server/Tool 并获取 backend 配置
server_backends = load_servers(server_registry)

# 初始化各 Server 的 Backend FeignClient
init_backend(server_backends)
