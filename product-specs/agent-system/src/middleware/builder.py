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
    llm: Any = None,
) -> list[AgentMiddleware]:
    """根据 Features 开关动态组装中间件列表

    Args:
        features: Features 实例（有 memory_enabled/guardrail_enabled/subagent_enabled 属性）
        system_prompt: 系统提示词（传给 AgentLoggingMiddleware）
        agent_name: Agent 名称
        memory_engine: MemoryEngine 实例（传给 MemoryMiddleware）
        file_upload_enabled: 是否启用文件上传处理链路
        llm: LLM 实例（传给 TitleMiddleware 用于生成标题）
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

    # 内容审查服务（输入+输出共用同一实例，LLM 用于语义审查）
    review_service = ContentReviewService(llm=llm)

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
            # 尝试从 features 中获取 engine 类型，支持 "fts"、"mem0"、"viking"
            engine_type = getattr(features, "memory_engine_type", "fts") if features else "fts"
            if engine_type == "viking":
                try:
                    from src.memory.viking_engine import VikingMemoryEngine
                    vdb_url = getattr(features, "vdb_url", "http://10.60.2.17") if features else "http://10.60.2.17"
                    vdb_key = getattr(features, "vdb_key", "") if features else ""
                    vdb_username = getattr(features, "vdb_username", "root") if features else "root"
                    vdb_database = getattr(features, "vdb_database", "viking_memory") if features else "viking_memory"
                    vdb_collection = getattr(features, "vdb_collection", "memories") if features else "memories"
                    use_pg = getattr(features, "viking_use_pg", True) if features else True
                    agent_rules_threshold = getattr(features, "viking_agent_rules_threshold", 5) if features else 5
                    engine = VikingMemoryEngine(
                        vdb_url=vdb_url,
                        vdb_key=vdb_key,
                        vdb_username=vdb_username,
                        database_name=vdb_database,
                        collection_name=vdb_collection,
                        llm=llm,
                        use_pg=use_pg,
                        agent_rules_threshold=agent_rules_threshold,
                    )
                    middleware.append(MemoryMiddleware(engine=engine))
                    logger.info("已启用 Viking 记忆引擎（腾讯 VectorDB: %s, PG: %s）", vdb_url, use_pg)
                except Exception as e:
                    logger.warning("Viking 记忆引擎初始化失败: %s，回退到默认", e)
                    middleware.append(MemoryMiddleware())
            elif engine_type == "mem0":
                try:
                    from src.memory.mem0_engine import Mem0MemoryEngine
                    mem0_config = getattr(features, "mem0_config", {}) if features else {}
                    mem0_instructions = getattr(features, "mem0_custom_instructions", "") if features else ""
                    # 腾讯云向量数据库配置（非空时启用）
                    tencent_vdb_url = getattr(features, "tencent_vdb_url", "") if features else ""
                    tencent_vdb_config = None
                    if tencent_vdb_url:
                        tencent_vdb_config = {
                            "url": tencent_vdb_url,
                            "key": getattr(features, "tencent_vdb_key", ""),
                            "username": getattr(features, "tencent_vdb_username", "root"),
                            "database_name": getattr(features, "tencent_vdb_database", "mem0_db"),
                            "collection_name": getattr(features, "tencent_vdb_collection", "mem0_memories"),
                        }
                    engine = Mem0MemoryEngine(
                        mem0_config=mem0_config,  # 空 dict 时自动使用豆包 2.0 默认配置
                        llm=llm,
                        custom_instructions=mem0_instructions or None,
                        tencent_vdb_config=tencent_vdb_config,
                    )
                    middleware.append(MemoryMiddleware(engine=engine))
                    vdb_label = "腾讯云 VectorDB" if tencent_vdb_config else "ChromaDB"
                    logger.info("已启用 Mem0 记忆引擎（豆包 2.0 + %s）", vdb_label)
                except ImportError:
                    logger.warning("mem0ai 未安装，回退到默认 MemoryMiddleware")
                    middleware.append(MemoryMiddleware())
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
        TitleMiddleware(llm=llm),
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
