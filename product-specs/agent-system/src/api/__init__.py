"""REST API 路由模块"""
from .knowledge_api import router as knowledge_router
from .a2ui_routes import a2ui_router

__all__ = ["knowledge_router", "a2ui_router"]
