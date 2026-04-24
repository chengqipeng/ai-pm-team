"""中间件动态组装 — 根据 Features 开关构建中间件管道"""
from __future__ import annotations

import logging
from typing import Any

from langchain.agents.middleware.types import AgentMiddleware

logger = logging.getLogger(__name__)


def build_middleware(
    features: Any = None,
    system_prompt: str = "",
    agent_name: str = "DeepAgent",
    memory_engine: Any = None,
    file_upload_enabled: bool = False,
) -> list[AgentMiddleware]:
    """根据 Features 开关动态组装中间件列表

    Args:
        features: Features 实例（有 memory_enabled/guardrail_enabled/subagent_enabled 属性）
        system_prompt: 系统提示词（传给 AgentLoggingMiddleware）
        agent_name: Agent 名称
        memory_engine: MemoryEngine 实例（传给 MemoryMiddleware）
        file_upload_enabled: 是否启用文件上传处理链路
    """
    from src.middleware import (
        AgentLoggingMiddleware,
        ClarificationMiddleware,
        DanglingToolCallMiddleware,
        FileProcessMiddleware,
        GuardrailMiddleware,
        InputTransformMiddleware,
        LoopDetectionMiddleware,
        MemoryMiddleware,
        MultimodalInjectMiddleware,
        MultimodalTransformer,
        OutputRenderMiddleware,
        OutputValidationMiddleware,
        SubagentLimitMiddleware,
        SummarizationMiddleware,
        TitleMiddleware,
        TodoMiddleware,
        ToolErrorHandlingMiddleware,
    )
    from src.middleware.input_transform import PIIRedactTransformer, ContentReviewTransformer
    from src.middleware.content_review import ContentReviewService
    from src.middleware.tracing import TracingMiddleware, tracing_middleware

    # 检查 features 中的 file_upload_enabled
    _file_upload = file_upload_enabled or (
        getattr(features, "file_upload_enabled", False) if features else False
    )

    middleware: list[AgentMiddleware] = [
        tracing_middleware,  # 全局单例，放最前面，记录完整链路
        AgentLoggingMiddleware(
            system_prompt=system_prompt,
            agent_name=agent_name,
        ),
        DanglingToolCallMiddleware(),
    ]

    # 文件预处理（按 features 开关）
    if _file_upload:
        middleware.append(FileProcessMiddleware())

    # 内容审查服务（输入+输出共用同一实例）
    review_service = ContentReviewService()

    # 输入转换：内容审查 → PII 脱敏 → 多模态转换
    input_transform = InputTransformMiddleware()
    input_transform.register(ContentReviewTransformer(review_service=review_service))
    input_transform.register(PIIRedactTransformer())
    if _file_upload:
        input_transform.register(MultimodalTransformer())
    middleware.append(input_transform)

    # 多模态注入（按 features 开关）
    if _file_upload:
        middleware.append(MultimodalInjectMiddleware())

    middleware.append(SummarizationMiddleware())

    # 记忆中间件（按 features 开关）
    memory_enabled = getattr(features, "memory_enabled", True) if features else True
    if memory_enabled:
        if memory_engine is not None:
            middleware.append(MemoryMiddleware(engine=memory_engine))
        else:
            middleware.append(MemoryMiddleware())

    middleware.append(TodoMiddleware())

    # 子 Agent 限制（按 features 开关）
    subagent_enabled = getattr(features, "subagent_enabled", True) if features else True
    if subagent_enabled:
        middleware.append(SubagentLimitMiddleware())

    # 安全护栏（按 features 开关）
    guardrail_enabled = getattr(features, "guardrail_enabled", True) if features else True
    if guardrail_enabled:
        middleware.append(GuardrailMiddleware())

    middleware += [
        LoopDetectionMiddleware(),
        ToolErrorHandlingMiddleware(),
        ClarificationMiddleware(),
        OutputValidationMiddleware(review_service=review_service),
        OutputRenderMiddleware(),
        TitleMiddleware(),
    ]

    logger.info("已组装 %d 个中间件 (memory=%s, guardrail=%s, subagent=%s)",
                len(middleware), memory_enabled, guardrail_enabled, subagent_enabled)
    return middleware


def _build_middleware_by_names(
    names: list[str],
    config: dict[str, Any] | None = None,
    base_dir: str = "",
) -> list[AgentMiddleware]:
    """按名称列表构建中间件

    支持私有中间件：base_dir/middlewares/ 下的同名中间件优先于全局。
    """
    from src.middleware import (
        AgentLoggingMiddleware,
        ClarificationMiddleware,
        DanglingToolCallMiddleware,
        GuardrailMiddleware,
        InputTransformMiddleware,
        LoopDetectionMiddleware,
        MemoryMiddleware,
        OutputRenderMiddleware,
        OutputValidationMiddleware,
        SubagentLimitMiddleware,
        SummarizationMiddleware,
        TitleMiddleware,
        TodoMiddleware,
        ToolErrorHandlingMiddleware,
    )

    # 全局中间件映射
    name_to_class: dict[str, type] = {
        "logging": AgentLoggingMiddleware,
        "dangling_tool_call": DanglingToolCallMiddleware,
        "input_transform": InputTransformMiddleware,
        "summarization": SummarizationMiddleware,
        "memory": MemoryMiddleware,
        "todo": TodoMiddleware,
        "subagent_limit": SubagentLimitMiddleware,
        "guardrail": GuardrailMiddleware,
        "loop_detection": LoopDetectionMiddleware,
        "tool_error_handling": ToolErrorHandlingMiddleware,
        "clarification": ClarificationMiddleware,
        "output_validation": OutputValidationMiddleware,
        "output_render": OutputRenderMiddleware,
        "title": TitleMiddleware,
    }

    # 合并私有中间件（私有优先覆盖全局同名）
    if base_dir:
        private_map = discover_private_middlewares(base_dir)
        name_to_class.update(private_map)

    config = config or {}
    middleware = []
    for name in names:
        cls = name_to_class.get(name)
        if cls is None:
            logger.warning("未知的中间件名称: %s，已跳过", name)
            continue
        mw_config = config.get(name, {})
        try:
            middleware.append(cls(**mw_config) if mw_config else cls())
        except Exception:
            logger.warning("中间件 '%s' 初始化失败，已跳过", name, exc_info=True)
    return middleware


def discover_private_middlewares(base_dir: str) -> dict[str, type]:
    """从 Agent 目录的 middlewares/ 子目录自动发现私有中间件

    扫描 middlewares/ 下所有 .py 文件，查找 AgentMiddleware 子类。
    返回 {中间件名称: 类} 的映射，名称取自文件名（不含 .py）。
    私有中间件同名时优先于全局中间件。
    """
    import importlib.util
    import inspect
    import os

    mw_dir = os.path.join(base_dir, "middlewares") if base_dir else ""
    if not mw_dir or not os.path.isdir(mw_dir):
        return {}

    private_map: dict[str, type] = {}
    seen: set[str] = set()

    for filename in sorted(os.listdir(mw_dir)):
        if filename.startswith("_"):
            continue
        if not filename.endswith(".py"):
            continue
        mw_name = filename[:-3]
        if mw_name in seen:
            continue
        seen.add(mw_name)

        module_path = os.path.join(mw_dir, filename)
        module_name = f"agent_mw__{os.path.basename(base_dir)}__{mw_name}"

        try:
            spec = importlib.util.spec_from_file_location(module_name, module_path)
            if spec is None or spec.loader is None:
                continue
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)

            for attr_name in dir(module):
                attr = getattr(module, attr_name)
                if (isinstance(attr, type)
                        and issubclass(attr, AgentMiddleware)
                        and attr is not AgentMiddleware
                        and not inspect.isabstract(attr)):
                    private_map[mw_name] = attr
                    logger.info("发现私有中间件: %s → %s (from %s)",
                                mw_name, attr.__name__, filename)
                    break  # 每个文件取第一个 AgentMiddleware 子类
        except Exception:
            logger.warning("私有中间件加载失败: %s", module_path, exc_info=True)

    return private_map
