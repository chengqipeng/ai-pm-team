"""A2UIBuilder — 流畅 API 构建 A2UI 消息三件套

面向 Skill / Middleware / IntentHandler 开发者，让你用 Pythonic 的方式
生成符合 A2UI v0.8 规范的 surfaceUpdate + dataModelUpdate + beginRendering。

典型用法:

    ui = A2UIBuilder(surface_id="pipeline", catalog_id="crm-v1")
    ui.column("root", children=[
        ui.text("title", literal="Q3 Pipeline 分析", usage_hint="h1"),
        ui.table("pipeline_table", data_path="/pipeline/stages"),
        ui.button("drill_down", label="查看详情", action="open_opportunity",
                  context={"stage": {"path": "/pipeline/selected_stage"}}),
    ])
    ui.data({"pipeline": {"stages": [...], "selected_stage": None}})
    messages = ui.build()  # → (SurfaceUpdate, DataModelUpdate, BeginRendering)
"""
from __future__ import annotations

from typing import Any

from .models import (
    BoundValue,
    Component,
    DataEntry,
    DataModelUpdate,
    BeginRendering,
    SurfaceUpdate,
    dict_to_entries,
    literal as _literal,
    path_bind as _path_bind,
)


def _normalize_bound(value: Any) -> dict:
    """把多种输入形式归一为 BoundValue dict:
    - BoundValue 实例 → 其 to_dict()
    - dict（已含 path / literal* 字段）→ 原样
    - 其他 → 通过 literal() 自动推断
    """
    if isinstance(value, BoundValue):
        return value.to_dict()
    if isinstance(value, dict) and (
        "path" in value or "literalString" in value
        or "literalNumber" in value or "literalBoolean" in value
        or "literalArray" in value
    ):
        return value
    return _literal(value).to_dict()


def _child_id(child: "str | Component") -> str:
    return child if isinstance(child, str) else child.id


class A2UIBuilder:
    """A2UI 消息构建器。

    线程安全提示：每个 Agent run 实例化一个 Builder，不要跨 run 复用。
    """

    def __init__(self, surface_id: str, catalog_id: str | None = None) -> None:
        self.surface_id = surface_id
        self.catalog_id = catalog_id
        self._components: list[Component] = []
        self._component_ids: set[str] = set()
        self._data_entries: list[DataEntry] = []
        self._data_path: str | None = None
        self._root_id: str | None = None
        self._root_explicit: bool = False

    # ── 基础操作 ──

    def add(self, component: Component, *, is_container: bool = False) -> str:
        """添加一个已构造好的 Component。

        root 选择策略：
        - `set_root()` 显式设置优先
        - 否则，第一个 `is_container=True` 的组件成为 root（避免 Python 参数求值顺序陷阱：
          children 里的叶子组件会先于外层 column/row 被 add，但容器才是真正的 root 候选）
        - 全都是叶子时，退化为第一个添加的组件
        """
        if component.id in self._component_ids:
            raise ValueError(f"组件 id 重复: {component.id}")
        self._components.append(component)
        self._component_ids.add(component.id)

        if self._root_explicit:
            return component.id

        if is_container:
            # 容器组件总是覆盖当前非显式 root（取最外层容器）
            self._root_id = component.id
        elif self._root_id is None:
            # 全叶子场景兜底
            self._root_id = component.id
        return component.id

    def set_root(self, component_id: str) -> "A2UIBuilder":
        """显式设置 root 组件 id"""
        if component_id not in self._component_ids:
            raise ValueError(f"root 指向不存在的组件: {component_id}")
        self._root_id = component_id
        self._root_explicit = True
        return self

    # ── 容器组件 ──

    def column(
        self,
        id: str,
        children: list["str | Component"] | None = None,
        alignment: str = "start",
        **extra,
    ) -> str:
        child_ids = [_child_id(c) for c in (children or [])]
        props: dict[str, Any] = {
            "alignment": alignment,
            "children": {"explicitList": child_ids},
        }
        props.update(extra)
        return self.add(Component(id=id, type="Column", props=props), is_container=True)

    def row(
        self,
        id: str,
        children: list["str | Component"] | None = None,
        alignment: str = "center",
        **extra,
    ) -> str:
        child_ids = [_child_id(c) for c in (children or [])]
        props: dict[str, Any] = {
            "alignment": alignment,
            "children": {"explicitList": child_ids},
        }
        props.update(extra)
        return self.add(Component(id=id, type="Row", props=props), is_container=True)

    def card(self, id: str, child: "str | Component", **extra) -> str:
        props: dict[str, Any] = {"child": _child_id(child)}
        props.update(extra)
        return self.add(Component(id=id, type="Card", props=props), is_container=True)

    def list_template(
        self,
        id: str,
        data_binding: str,
        template_id: str,
        **extra,
    ) -> str:
        """动态列表：根据数据路径 + 模板组件渲染"""
        props: dict[str, Any] = {
            "children": {
                "template": {
                    "dataBinding": data_binding,
                    "componentId": template_id,
                }
            },
        }
        props.update(extra)
        return self.add(Component(id=id, type="List", props=props), is_container=True)

    # ── 叶子组件 ──

    def text(
        self,
        id: str,
        literal: Any = None,
        path: str | None = None,
        usage_hint: str = "body",
        **extra,
    ) -> str:
        if literal is None and path is None:
            raise ValueError("text 必须提供 literal 或 path 之一")
        bound = _path_bind(path, literal).to_dict() if path else _literal(literal).to_dict()
        props: dict[str, Any] = {"text": bound, "usageHint": usage_hint}
        props.update(extra)
        return self.add(Component(id=id, type="Text", props=props))

    def image(self, id: str, url_literal: str | None = None,
              url_path: str | None = None, **extra) -> str:
        if url_literal is None and url_path is None:
            raise ValueError("image 必须提供 url_literal 或 url_path")
        bound = _path_bind(url_path, url_literal).to_dict() if url_path else _literal(url_literal).to_dict()
        props: dict[str, Any] = {"url": bound}
        props.update(extra)
        return self.add(Component(id=id, type="Image", props=props))

    def button(
        self,
        id: str,
        label: str | None = None,
        label_path: str | None = None,
        action: str = "",
        context: dict[str, Any] | None = None,
        child: "str | Component | None" = None,
        **extra,
    ) -> str:
        """按钮。

        label/label_path 会生成一个 Text 子组件作为 child（若未显式传 child）。
        action.context 中的每个值都会自动包装成 BoundValue。
        """
        action_obj: dict[str, Any] = {"name": action} if action else {}
        if context:
            action_obj["context"] = [
                {"key": k, "value": _normalize_bound(v)} for k, v in context.items()
            ]

        # 若未显式传 child，用 label 自动生成一个 Text 子组件
        if child is None and (label is not None or label_path is not None):
            child_component_id = f"{id}__label"
            # 避免重复注册（重跑时）
            if child_component_id not in self._component_ids:
                self.text(child_component_id, literal=label, path=label_path, usage_hint="button")
            child = child_component_id

        props: dict[str, Any] = {}
        if action_obj:
            props["action"] = action_obj
        if child is not None:
            props["child"] = _child_id(child)
        props.update(extra)
        return self.add(Component(id=id, type="Button", props=props))

    def text_field(
        self,
        id: str,
        path: str,
        label: str | None = None,
        placeholder: str | None = None,
        **extra,
    ) -> str:
        props: dict[str, Any] = {"value": _path_bind(path).to_dict()}
        if label is not None:
            props["label"] = _literal(label).to_dict()
        if placeholder is not None:
            props["placeholder"] = _literal(placeholder).to_dict()
        props.update(extra)
        return self.add(Component(id=id, type="TextField", props=props))

    # ── 业务组件 (CRM Catalog 示例) ──

    def crm_record_card(
        self,
        id: str,
        record_type: str,
        record_id_path: str,
        **extra,
    ) -> str:
        """CRM 实体卡片（客户/商机/合同）"""
        props: dict[str, Any] = {
            "recordType": _literal(record_type).to_dict(),
            "recordId": _path_bind(record_id_path).to_dict(),
        }
        props.update(extra)
        return self.add(Component(id=id, type="CrmRecordCard", props=props))

    def pipeline_table(
        self,
        id: str,
        stages_path: str,
        on_stage_click: str | None = None,
        **extra,
    ) -> str:
        props: dict[str, Any] = {"stages": _path_bind(stages_path).to_dict()}
        if on_stage_click:
            props["action"] = {
                "name": on_stage_click,
                "context": [
                    {"key": "stage", "value": {"path": f"{stages_path}/current"}}
                ],
            }
        props.update(extra)
        return self.add(Component(id=id, type="PipelineTable", props=props))

    # ── 数据模型 ──

    def data(
        self,
        payload: dict[str, Any] | None = None,
        path: str | None = None,
        *,
        entries: list[DataEntry] | None = None,
    ) -> "A2UIBuilder":
        """设置 dataModelUpdate 的内容。可重复调用，entry 会合并。

        - 传 payload（dict）→ 自动转 DataEntry（推荐）
        - 传 entries（list[DataEntry]）→ 直接使用（精确控制类型）
        - 传 path → 设置 DataModelUpdate.path
        """
        if path is not None:
            self._data_path = path
        if entries:
            self._data_entries.extend(entries)
        if payload:
            self._data_entries.extend(dict_to_entries(payload))
        return self

    # ── 生成 ──

    def build(self) -> tuple[SurfaceUpdate, DataModelUpdate | None, BeginRendering]:
        """产出三件套：SurfaceUpdate [+ DataModelUpdate] + BeginRendering"""
        if not self._components:
            raise ValueError(f"surface={self.surface_id} 没有任何组件")
        if self._root_id is None:
            raise ValueError(f"surface={self.surface_id} 未指定 root 组件")

        surface_update = SurfaceUpdate(
            surface_id=self.surface_id,
            components=list(self._components),
        )
        data_update: DataModelUpdate | None = None
        if self._data_entries:
            data_update = DataModelUpdate(
                surface_id=self.surface_id,
                contents=list(self._data_entries),
                path=self._data_path,
            )
        begin = BeginRendering(
            surface_id=self.surface_id,
            root=self._root_id,
            catalog_id=self.catalog_id,
        )
        return surface_update, data_update, begin

    def messages(self) -> list:
        """build() 的扁平版本，跳过 None（没有 data 时）"""
        su, du, br = self.build()
        return [m for m in (su, du, br) if m is not None]
