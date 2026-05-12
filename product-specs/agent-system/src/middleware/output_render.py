"""输出渲染中间件 — UI 组件映射

将 Agent 最终输出映射到 UI 组件协议（表格/报告/Dashboard）。
渲染器通过 register() 注册，按优先级匹配。
"""
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from langchain_core.messages import AIMessage
from langchain.agents.middleware.types import AgentMiddleware, AgentState
from langgraph.config import get_config
from langgraph.runtime import Runtime

logger = logging.getLogger(__name__)


@dataclass
class RenderResult:
    """渲染结果"""
    text: str
    components: list[dict[str, Any]] = field(default_factory=list)
    artifacts: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


class OutputRenderer(ABC):
    """输出渲染器接口"""
    @abstractmethod
    def can_render(self, content: str, metadata: dict[str, Any]) -> bool: ...
    @abstractmethod
    def render(self, content: str, metadata: dict[str, Any]) -> RenderResult: ...


class TableRenderer(OutputRenderer):
    """表格渲染器 — 检测 Markdown 表格并转换为结构化组件"""

    def can_render(self, content: str, metadata: dict[str, Any]) -> bool:
        # 检测 Markdown 表格（至少 2 行 | 分隔）
        lines = content.strip().split("\n")
        pipe_lines = [l for l in lines if "|" in l and l.strip().startswith("|")]
        return len(pipe_lines) >= 3

    def render(self, content: str, metadata: dict[str, Any]) -> RenderResult:
        lines = content.strip().split("\n")
        table_lines = [l for l in lines if "|" in l and l.strip().startswith("|")]
        if len(table_lines) < 3:
            return RenderResult(text=content)

        # 解析表头
        headers = [c.strip() for c in table_lines[0].split("|") if c.strip()]
        # 解析数据行（跳过分隔行）
        rows = []
        for line in table_lines[2:]:
            cells = [c.strip() for c in line.split("|") if c.strip()]
            if cells:
                rows.append(dict(zip(headers, cells)))

        return RenderResult(
            text=content,
            components=[{"type": "table", "headers": headers, "rows": rows}],
        )


class OutputRenderMiddleware(AgentMiddleware):
    """输出渲染中间件"""

    def __init__(self, renderers: list[OutputRenderer] | None = None):
        super().__init__()
        self._renderers: list[OutputRenderer] = renderers or []

    def register(self, renderer: OutputRenderer) -> None:
        self._renderers.append(renderer)

    def after_agent(self, state: AgentState, runtime: Runtime) -> dict[str, Any] | None:
        messages = state.get("messages", [])
        if not messages:
            return None

        last_ai = next(
            (m for m in reversed(messages)
             if isinstance(m, AIMessage) and not getattr(m, "tool_calls", None)),
            None,
        )
        if last_ai is None:
            return None

        content = last_ai.content
        if not isinstance(content, str) or not content.strip():
            return None

        configurable = get_config().get("configurable", {})
        metadata = configurable.get("render_metadata", {})

        changed = False

        # ── PII 还原：将 Agent 输出中的占位符还原为原始值 ──
        pii_placeholders = configurable.get("pii_placeholders", {})
        if not pii_placeholders:
            # 也尝试从 input_metadata 中获取（InputTransformMiddleware 写入）
            input_meta = configurable.get("input_metadata", {})
            pii_placeholders = input_meta.get("pii_placeholders", {})

        if pii_placeholders:
            from src.middleware.input_transform import PIIRedactTransformer
            restored = PIIRedactTransformer.restore_pii(content, pii_placeholders)
            if restored != content:
                last_ai.content = restored
                content = restored
                changed = True
                logger.info("PII 还原完成: %d 个占位符", len(pii_placeholders))

        # ── 渲染器匹配 ──
        if self._renderers:
            for renderer in self._renderers:
                try:
                    if renderer.can_render(content, metadata):
                        result = renderer.render(content, metadata)
                        logger.info("Output rendered by %s", type(renderer).__name__)
                        return {"render_result": result.text, "components": result.components}
                except Exception as e:
                    logger.error("Renderer %s failed: %s", type(renderer).__name__, e)

        if changed:
            return {"messages": [last_ai]}
        return None
