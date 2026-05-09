"""端到端示例（Mode A）：从同一套 Skill 产出的 AG-UI 事件流里投影出纯 A2UI 消息。

演示链路：

  Skill (A2UIRenderHelper) → AG-UI 事件流 (含 ACTIVITY_SNAPSHOT + STATE_SNAPSHOT)
                                        │
                                        ▼
                              A2UIProjector
                                        │
                                        ▼
                              纯 A2UI JSONL 消息流
                              （前端 Flutter/Web A2UI 客户端可直接消费）

运行：
    .venv/bin/python demo_a2ui_mode_a.py

输出：
    每行一条 A2UI v0.8 JSONL 消息，按顺序打印。
"""
from __future__ import annotations

import asyncio
import json
import sys
import uuid

sys.path.insert(0, ".")

from src.a2ui import (
    A2UIBuilder,
    A2UIProjector,
    A2UIRenderHelper,
    CatalogRegistry,
    Component,
    VIKING_CRM_V1,
)


def load_catalog() -> CatalogRegistry:
    reg = CatalogRegistry()
    reg.register_standard()
    reg.load_from_dir("resources/a2ui/components", catalog_id=VIKING_CRM_V1)
    if reg.get(VIKING_CRM_V1) and reg.get(VIKING_CRM_V1).components:
        reg.set_default(VIKING_CRM_V1)
    return reg


def build_customers_surface(ui: A2UIBuilder, data_path: str) -> None:
    ui.add(Component(id="row_tpl", type="CrmRecordCard", props={
        "recordType": {"literalString": "customer"},
        "recordId": {"path": "./id"},
    }))
    ui.list_template("customers_list", data_binding=data_path, template_id="row_tpl")
    ui.column("root", children=[
        ui.text("title", literal="Q3 新签 Top10 客户", usage_hint="h2"),
        "customers_list",
    ])


async def produce_agui_events():
    """模拟一次完整的 Agent run：生成 AG-UI 事件流"""
    run_id = uuid.uuid4().hex
    helper = A2UIRenderHelper(run_id=run_id, catalog_registry=load_catalog())

    customers = [
        {"id": "C1", "name": "工商银行", "amount": 58.0, "stage": "谈判"},
        {"id": "C2", "name": "农业银行", "amount": 42.5, "stage": "报价"},
        {"id": "C3", "name": "中国银行", "amount": 37.2, "stage": "验收"},
    ]
    for event in helper.render(
        render_type="customers_top",
        data=customers,
        surface_fn=build_customers_surface,
        notification_message="✅ Q3 Top10 已加载",
    ):
        yield event


async def main():
    projector = A2UIProjector()  # 默认只保留 A2UI 操作，丢弃其他事件
    count = 0
    print("=== Mode A JSONL output ===\n")
    async for msg in projector.project(produce_agui_events()):
        count += 1
        line = msg.to_jsonl()
        # 美化输出
        obj = json.loads(line)
        print(f"--- [{count}] {list(obj.keys())[0]} ---")
        print(json.dumps(obj, ensure_ascii=False, indent=2))
        print()
    print(f"=== 共投影出 {count} 条 A2UI 消息 ===")


if __name__ == "__main__":
    asyncio.run(main())
