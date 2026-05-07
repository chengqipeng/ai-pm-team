"""端到端示例：一个 Skill 用 A2UIRenderHelper 同时产出

- 业务数据（走 Shared State：STATE_SNAPSHOT / STATE_DELTA）
- UI 结构（走 ACTIVITY_SNAPSHOT：surfaceUpdate + beginRendering）
- 绑定关系（Builder 用 /data/<render_type> 路径绑定 Shared State）

场景："Q3 新签 Top10 客户" 查询。

运行：
    .venv/bin/python demo_a2ui_skill.py

输出：按顺序打印每条 AG-UI 事件，可直接喂给前端 SSE 通道。
"""
from __future__ import annotations

import json
import sys
import uuid

# 确保 src 可 import（demo 脚本放在项目根）
sys.path.insert(0, ".")

from src.a2ui import (
    A2UIBuilder,
    A2UIRenderHelper,
    CatalogRegistry,
    Component,
    VIKING_CRM_V1,
)


# ═══════════════════════════════════════════════════════════
# 1. 启动时一次性加载 Catalog（生产里放在 server.py 或 app factory）
# ═══════════════════════════════════════════════════════════

def load_catalog() -> CatalogRegistry:
    reg = CatalogRegistry()
    reg.register_standard()
    reg.load_from_dir("resources/a2ui/components", catalog_id=VIKING_CRM_V1)
    if reg.get(VIKING_CRM_V1) and reg.get(VIKING_CRM_V1).components:
        reg.set_default(VIKING_CRM_V1)
    return reg


# ═══════════════════════════════════════════════════════════
# 2. Skill 侧定义：如何把 data_path 包装成 surface 结构
#    (业务开发者只需写这个函数；数据/事件/下发全由 Helper 搞定)
# ═══════════════════════════════════════════════════════════

def build_customers_surface(ui: A2UIBuilder, data_path: str) -> None:
    """构建"客户 Top10"面板：标题 + 列表 + 模板行。

    `data_path` 由 Aggregator 分配，形如 `/data/customers_top`。
    """
    # 模板行：单个 CrmRecordCard 组件，引用当前项的 id
    ui.add(
        Component(
            id="customer_row_tpl",
            type="CrmRecordCard",
            props={
                "recordType": {"literalString": "customer"},
                "recordId": {"path": "./id"},  # 相对路径：当前列表项
            },
        )
    )

    # 动态列表：绑定数据路径 + 指定模板组件
    ui.list_template(
        "customers_list",
        data_binding=data_path,
        template_id="customer_row_tpl",
    )

    # 顶层 root：标题 + 列表
    ui.column(
        "root",
        children=[
            ui.text("title", literal="Q3 新签 Top10 客户", usage_hint="h2"),
            "customers_list",  # 直接引用已注册的组件 id
        ],
    )


# ═══════════════════════════════════════════════════════════
# 3. 主流程：Skill 被调用 → 生成数据 → Helper 一步完成下发
# ═══════════════════════════════════════════════════════════

def run_skill() -> list:
    # 假设当前 Agent run
    run_id = uuid.uuid4().hex
    thread_id = "t-demo"

    catalog = load_catalog()
    helper = A2UIRenderHelper(
        run_id=run_id,
        thread_id=thread_id,
        catalog_registry=catalog,
    )

    # ---- Skill 内部逻辑：调 CRM Tool 获取数据 ----
    customers = [
        {"id": "C1", "name": "工商银行", "amount": 58.0, "stage": "谈判"},
        {"id": "C2", "name": "农业银行", "amount": 42.5, "stage": "报价"},
        {"id": "C3", "name": "中国银行", "amount": 37.2, "stage": "验收"},
        {"id": "C4", "name": "建设银行", "amount": 35.0, "stage": "谈判"},
        {"id": "C5", "name": "招商银行", "amount": 30.1, "stage": "线索"},
    ]

    # ---- Helper 一步完成：数据 + 结构 + 下发 ----
    events = helper.render(
        render_type="customers_top",
        data=customers,
        surface_fn=build_customers_surface,
        notification_message="✅ Q3 新签 Top10 客户已加载",
    )

    # ---- 后续增量更新（例如用户点击"刷新"） ----
    customers_updated = [
        *customers,
        {"id": "C6", "name": "交通银行", "amount": 28.0, "stage": "初步"},
    ]
    events_update = helper.update_data("customers_top", customers_updated)

    return events + events_update


# ═══════════════════════════════════════════════════════════
# 4. 打印事件（SSE-like 格式）
# ═══════════════════════════════════════════════════════════

def format_event(event) -> str:
    return json.dumps(
        {"type": event.type, **event.data},
        ensure_ascii=False,
        indent=2,
    )


def main() -> None:
    events = run_skill()
    print(f"=== 产出 {len(events)} 个 AG-UI 事件 ===\n")
    for i, ev in enumerate(events, 1):
        title = ev.type
        # 针对关键事件给出说明
        if title == "STATE_SNAPSHOT":
            snap = ev.data["snapshot"]
            rt_keys = list((snap.get("data") or {}).keys())
            title += f"  (data.* keys = {rt_keys}, surfaces = {snap.get('panelSurfaceMap')})"
        elif title == "STATE_DELTA":
            title += f"  ({len(ev.data.get('delta', []))} JSON Patch ops)"
        elif title == "ACTIVITY_SNAPSHOT":
            ops = ev.data.get("content", {}).get("operations", [])
            op_keys = [list(o.keys())[0] for o in ops]
            title += f"  (surface={ev.data.get('message_id')}, operations={op_keys})"

        print(f"--- [{i}] {title} ---")
        print(format_event(ev))
        print()


if __name__ == "__main__":
    main()
