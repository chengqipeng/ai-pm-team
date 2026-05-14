"""REST API 路由模块"""
from .knowledge_api import router as knowledge_router
from .a2ui_routes import a2ui_router
from .metarepo_api import router as metarepo_router
from .skill_api import router as skill_router
from .skill_category_api import router as skill_category_router
from .tool_api import router as tool_router
from .mock_data_api import router as mock_data_router

__all__ = [
    "knowledge_router",
    "a2ui_router",
    "metarepo_router",
    "skill_router",
    "skill_category_router",
    "tool_router",
    "mock_data_router",
]
