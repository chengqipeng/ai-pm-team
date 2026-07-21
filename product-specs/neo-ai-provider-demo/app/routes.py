"""Provider 路由 — 使用 SDK 自动生成

SDK 的 create_provider_router 自动处理：
- state 初始化（线程隔离）
- handler 执行（sync/async 兼容）
- set_state patch 收集
- 响应组装（result + state_patch）

Provider 业务开发者只需关注 handler 逻辑，不感知 SDK 内部机制。
"""
from neo_ai_registry.fastapi import create_provider_router
from app.registry_setup import registry

# 一行代码生成标准 Provider 路由
router = create_provider_router(registry)
