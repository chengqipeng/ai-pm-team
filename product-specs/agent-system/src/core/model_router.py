"""多模型路由 — 按任务类型选择最优模型

借鉴 Hermes Agent 的辅助 LLM 路由策略：
- 简单任务（摘要/分类/FAQ）→ 低成本模型
- 复杂推理（规划/分析/代码）→ 高能力模型
- 记忆提取/压缩 → 辅助模型
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_openai import ChatOpenAI

logger = logging.getLogger(__name__)


class TaskType(str, Enum):
    """任务类型分类"""
    SIMPLE = "simple"           # 摘要、分类、FAQ
    COMPLEX = "complex"         # 规划、分析、多步推理
    AUXILIARY = "auxiliary"      # 记忆提取、上下文压缩
    CODE = "code"               # 代码生成、审查
    DEFAULT = "default"         # 默认


@dataclass
class ModelConfig:
    """单个模型配置"""
    model: str
    api_key: str = ""
    api_base: str = "https://api.deepseek.com"
    temperature: float = 0.7
    max_tokens: int = 8192


@dataclass
class ModelRouterConfig:
    """模型路由配置"""
    default: ModelConfig = field(default_factory=lambda: ModelConfig(model="deepseek-chat"))
    routes: dict[str, ModelConfig] = field(default_factory=dict)


class ModelRouter:
    """多模型路由器 — 按任务类型选择模型

    用法:
        router = ModelRouter(config)
        model = router.get_model(TaskType.SIMPLE)
        model = router.route_by_content("帮我总结一下")
    """

    # 关键词 → 任务类型映射
    _KEYWORD_MAP: dict[str, TaskType] = {
        "总结": TaskType.SIMPLE,
        "摘要": TaskType.SIMPLE,
        "分类": TaskType.SIMPLE,
        "翻译": TaskType.SIMPLE,
        "规划": TaskType.COMPLEX,
        "分析": TaskType.COMPLEX,
        "设计": TaskType.COMPLEX,
        "对比": TaskType.COMPLEX,
        "代码": TaskType.CODE,
        "编程": TaskType.CODE,
        "实现": TaskType.CODE,
        "debug": TaskType.CODE,
        "压缩": TaskType.AUXILIARY,
        "提取记忆": TaskType.AUXILIARY,
    }

    def __init__(self, config: ModelRouterConfig) -> None:
        self._config = config
        self._model_cache: dict[str, BaseChatModel] = {}

    def get_model(self, task_type: TaskType = TaskType.DEFAULT) -> BaseChatModel:
        """按任务类型获取模型实例（带缓存）"""
        mc = self._config.routes.get(task_type.value, self._config.default)
        cache_key = f"{mc.model}:{mc.api_base}"
        if cache_key not in self._model_cache:
            self._model_cache[cache_key] = ChatOpenAI(
                model=mc.model,
                api_key=mc.api_key or self._config.default.api_key,
                base_url=mc.api_base or self._config.default.api_base,
                temperature=mc.temperature,
                max_tokens=mc.max_tokens,
            )
            logger.info("Created model: %s for task_type=%s", mc.model, task_type.value)
        return self._model_cache[cache_key]

    def route_by_content(self, content: str) -> BaseChatModel:
        """根据用户输入内容自动路由到合适的模型"""
        task_type = self.classify_task(content)
        return self.get_model(task_type)

    def classify_task(self, content: str) -> TaskType:
        """根据内容关键词分类任务类型"""
        content_lower = content.lower()
        for keyword, task_type in self._KEYWORD_MAP.items():
            if keyword in content_lower:
                return task_type
        return TaskType.DEFAULT

    @property
    def available_routes(self) -> dict[str, str]:
        """返回所有已配置的路由"""
        routes = {"default": self._config.default.model}
        for k, v in self._config.routes.items():
            routes[k] = v.model
        return routes
