"""Tool 工具管理 REST API

路由前缀：/api/tools

提供：
    - GET    /api/tools              工具列表（从 ToolRegistry 读取已注册工具）
    - GET    /api/tools/{name}       工具详情
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/tools", tags=["tools"])

# 全局引用，由 server.py 启动后注入
_tool_registry = None


def set_tool_registry(registry) -> None:
    global _tool_registry
    _tool_registry = registry


def _get_registry():
    """获取 ToolRegistry（兼容 ToolLoader 和 ToolRegistry 两种实现）"""
    if _tool_registry is None:
        return None
    return _tool_registry


# ═══════════════════════════════════════════════════════════
# 工具列表
# ═══════════════════════════════════════════════════════════

@router.get("")
async def list_tools():
    """列出所有已注册的工具"""
    registry = _get_registry()
    if registry is None:
        return {"items": [], "message": "ToolRegistry 未初始化"}

    tools = []
    # 兼容 ToolRegistry（自定义 Tool 类）和 ToolLoader（LangChain BaseTool）
    if hasattr(registry, 'all_tools'):
        for tool in registry.all_tools:
            tools.append(_tool_to_dict(tool))
    elif hasattr(registry, '_registry'):
        # ToolLoader 模式
        for name, tool in registry._registry.items():
            tools.append(_lc_tool_to_dict(name, tool))

    # 按名称排序
    tools.sort(key=lambda t: t["name"])
    return {"items": tools, "total": len(tools)}


# ═══════════════════════════════════════════════════════════
# 工具详情
# ═══════════════════════════════════════════════════════════

@router.get("/{name}")
async def get_tool(name: str):
    """获取工具详情"""
    registry = _get_registry()
    if registry is None:
        raise HTTPException(status_code=503, detail="ToolRegistry 未初始化")

    tool = None
    if hasattr(registry, 'find_by_name'):
        tool = registry.find_by_name(name)
    elif hasattr(registry, '_registry'):
        tool = registry._registry.get(name)

    if tool is None:
        raise HTTPException(status_code=404, detail=f"工具 '{name}' 未找到")

    if hasattr(tool, 'input_schema') and callable(tool.input_schema):
        return _tool_to_detail(tool)
    else:
        return _lc_tool_to_detail(name, tool)


# ═══════════════════════════════════════════════════════════
# 序列化 — 自定义 Tool 类
# ═══════════════════════════════════════════════════════════

def _tool_to_dict(tool) -> dict:
    """将自定义 Tool 实例转为摘要字典"""
    return {
        "name": tool.name,
        "description": _get_tool_description(tool),
        "tags": getattr(tool, 'tags', []) if hasattr(tool, 'tags') else [],
        "read_only": tool.is_read_only({}) if hasattr(tool, 'is_read_only') else True,
        "aliases": tool.aliases if hasattr(tool, 'aliases') else [],
    }


def _tool_to_detail(tool) -> dict:
    """将自定义 Tool 实例转为详情字典"""
    d = _tool_to_dict(tool)
    schema = tool.input_schema() if callable(getattr(tool, 'input_schema', None)) else {}
    d.update({
        "input_schema": schema,
        "prompt": tool.prompt() if hasattr(tool, 'prompt') and callable(tool.prompt) else "",
        "max_result_size_chars": getattr(tool, 'max_result_size_chars', 50000),
        "should_defer": getattr(tool, 'should_defer', False),
    })
    return d


# ═══════════════════════════════════════════════════════════
# 序列化 — LangChain BaseTool
# ═══════════════════════════════════════════════════════════

def _lc_tool_to_dict(name: str, tool) -> dict:
    """将 LangChain BaseTool 实例转为摘要字典"""
    return {
        "name": getattr(tool, 'name', name),
        "description": getattr(tool, 'description', ''),
        "tags": [],
        "read_only": True,
        "aliases": [],
    }


def _lc_tool_to_detail(name: str, tool) -> dict:
    """将 LangChain BaseTool 实例转为详情字典"""
    d = _lc_tool_to_dict(name, tool)
    schema = {}
    if hasattr(tool, 'args_schema') and tool.args_schema:
        try:
            schema = tool.args_schema.model_json_schema()
        except Exception:
            pass
    d.update({
        "input_schema": schema,
        "prompt": "",
        "max_result_size_chars": 50000,
        "should_defer": False,
    })
    return d


def _get_tool_description(tool) -> str:
    """获取工具描述"""
    if hasattr(tool, 'description'):
        desc = tool.description
        if callable(desc):
            try:
                # description(input_data) 需要参数，用空 dict
                import asyncio
                result = desc({})
                if asyncio.iscoroutine(result):
                    return ""
                return result
            except Exception:
                return ""
        return desc if isinstance(desc, str) else ""
    return ""
