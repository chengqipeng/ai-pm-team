"""Registry 初始化 — 从配置文件加载

Tool/Middleware 定义来自 config/tools.yaml，handler 通过 api_key 自动匹配。
新增 Tool 只需：1. config/tools.yaml 加配置  2. handler 文件写函数  3. registry_loader 加映射
"""
from app.registry_loader import load_registry

# 启动时从配置文件加载
registry = load_registry(domain="sales")
