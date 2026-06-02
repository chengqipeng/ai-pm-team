"""Tool 评测预置用例

为每个内置工具提供标准的评测用例集，覆盖正常/异常/边界/副作用四类场景。
基于 CrmSimulatedBackend 的 seed data 设计。
"""
from __future__ import annotations

from src.eval.tool_eval_runner import (
    ToolEvalSuite, ToolEvalCase, Assertion, AssertionType,
)


def build_query_schema_cases() -> list[ToolEvalCase]:
    """query_schema 工具评测用例"""
    return [
        ToolEvalCase(
            id="qs_01",
            tool_name="query_schema",
            description="list_entities - 列出所有业务对象",
            category="normal",
            input_data={"query_type": "list_entities"},
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="不应报错"),
                Assertion(type=AssertionType.CONTAINS, expected="account", description="包含 account"),
                Assertion(type=AssertionType.CONTAINS, expected="opportunity", description="包含 opportunity"),
                Assertion(type=AssertionType.CONTAINS, expected="contact", description="包含 contact"),
            ],
        ),
        ToolEvalCase(
            id="qs_02",
            tool_name="query_schema",
            description="entity - 查看 opportunity 定义",
            category="normal",
            input_data={"query_type": "entity", "entity_api_key": "opportunity"},
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="不应报错"),
                Assertion(type=AssertionType.CONTAINS, expected="amount", description="包含 amount 字段"),
                Assertion(type=AssertionType.CONTAINS, expected="stage", description="包含 stage 字段"),
            ],
        ),
        ToolEvalCase(
            id="qs_03",
            tool_name="query_schema",
            description="entity_items - 查看字段列表",
            category="normal",
            input_data={"query_type": "entity_items", "entity_api_key": "account"},
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="不应报错"),
                Assertion(type=AssertionType.CONTAINS, expected="name", description="包含 name 字段"),
            ],
        ),
        ToolEvalCase(
            id="qs_04",
            tool_name="query_schema",
            description="不存在的 entity - 应返回错误",
            category="error",
            input_data={"query_type": "entity", "entity_api_key": "nonexistent_xyz"},
            assertions=[
                Assertion(type=AssertionType.IS_ERROR, description="应返回错误"),
            ],
        ),
        ToolEvalCase(
            id="qs_05",
            tool_name="query_schema",
            description="entity_pick_options - 查询选项值",
            category="normal",
            input_data={"query_type": "entity_pick_options", "entity_api_key": "opportunity", "item_api_key": "stage"},
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="不应报错"),
            ],
        ),
    ]


def build_query_data_cases() -> list[ToolEvalCase]:
    """query_data 工具评测用例"""
    return [
        ToolEvalCase(
            id="qd_01",
            tool_name="query_data",
            description="query - 查询所有客户",
            category="normal",
            input_data={"action": "query", "entity_api_key": "account"},
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="不应报错"),
                Assertion(type=AssertionType.CONTAINS, expected="records", description="返回 records 字段"),
            ],
        ),
        ToolEvalCase(
            id="qd_02",
            tool_name="query_data",
            description="query - 按 owner_name 过滤",
            category="normal",
            input_data={"action": "query", "entity_api_key": "opportunity", "filters": {"owner_name": "张三"}},
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="不应报错"),
                Assertion(type=AssertionType.CONTAINS, expected="张三", description="结果包含张三"),
            ],
        ),
        ToolEvalCase(
            id="qd_03",
            tool_name="query_data",
            description="get - 按 ID 查单条记录",
            category="normal",
            input_data={"action": "get", "entity_api_key": "account", "record_id": "acc_001"},
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="不应报错"),
                Assertion(type=AssertionType.CONTAINS, expected="acc_001", description="返回对应记录"),
            ],
        ),
        ToolEvalCase(
            id="qd_04",
            tool_name="query_data",
            description="get - 不存在的 ID",
            category="error",
            input_data={"action": "get", "entity_api_key": "account", "record_id": "acc_999999"},
            assertions=[
                Assertion(type=AssertionType.IS_ERROR, description="应返回错误"),
                Assertion(type=AssertionType.CONTAINS, expected="不存在", description="提示不存在"),
            ],
        ),
        ToolEvalCase(
            id="qd_05",
            tool_name="query_data",
            description="count - 统计记录数",
            category="normal",
            input_data={"action": "count", "entity_api_key": "account"},
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="不应报错"),
                Assertion(type=AssertionType.CONTAINS, expected="记录数", description="返回统计结果"),
            ],
        ),
        ToolEvalCase(
            id="qd_06",
            tool_name="query_data",
            description="query - 分页参数",
            category="boundary",
            input_data={"action": "query", "entity_api_key": "opportunity", "page": 1, "page_size": 2},
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="不应报错"),
            ],
        ),
        ToolEvalCase(
            id="qd_07",
            tool_name="query_data",
            description="query - 不存在的 entity",
            category="error",
            input_data={"action": "query", "entity_api_key": "nonexistent_entity"},
            assertions=[
                Assertion(type=AssertionType.IS_ERROR, description="应返回错误"),
            ],
        ),
    ]


def build_modify_data_cases() -> list[ToolEvalCase]:
    """modify_data 工具评测用例"""
    return [
        ToolEvalCase(
            id="md_01",
            tool_name="modify_data",
            description="create - 创建新客户",
            category="normal",
            input_data={
                "action": "create",
                "entity_api_key": "account",
                "data": {"name": "评测新客户", "industry": "科技", "owner_name": "评测员"},
            },
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="不应报错"),
                Assertion(type=AssertionType.CONTAINS, expected="评测新客户", description="返回创建的数据"),
            ],
        ),
        ToolEvalCase(
            id="md_02",
            tool_name="modify_data",
            description="update - 更新客户名称",
            category="normal",
            input_data={
                "action": "update",
                "entity_api_key": "account",
                "record_id": "acc_001",
                "data": {"name": "更新后的名称"},
            },
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="不应报错"),
                Assertion(type=AssertionType.CONTAINS, expected="更新后的名称", description="返回更新后的数据"),
            ],
        ),
        ToolEvalCase(
            id="md_03",
            tool_name="modify_data",
            description="update - 不存在的记录",
            category="error",
            input_data={
                "action": "update",
                "entity_api_key": "account",
                "record_id": "acc_not_exist",
                "data": {"name": "xxx"},
            },
            assertions=[
                Assertion(type=AssertionType.IS_ERROR, description="应返回错误"),
            ],
        ),
        ToolEvalCase(
            id="md_04",
            tool_name="modify_data",
            description="delete - 删除记录",
            category="normal",
            input_data={
                "action": "delete",
                "entity_api_key": "account",
                "record_id": "acc_001",
            },
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="不应报错"),
            ],
        ),
        ToolEvalCase(
            id="md_05",
            tool_name="modify_data",
            description="create 副作用验证 - 创建后可查到",
            category="side_effect",
            input_data={
                "action": "create",
                "entity_api_key": "account",
                "data": {"name": "副作用测试客户", "industry": "金融"},
            },
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="创建不应报错"),
                Assertion(
                    type=AssertionType.SIDE_EFFECT,
                    description="创建后通过 query 能查到",
                    expected={
                        "verify_tool": "query_data",
                        "verify_input": {"action": "query", "entity_api_key": "account", "filters": {"name": "副作用测试客户"}},
                        "verify_path": "records.0.name",
                        "verify_value": "副作用测试客户",
                    },
                ),
            ],
        ),
    ]


def build_analyze_data_cases() -> list[ToolEvalCase]:
    """analyze_data 工具评测用例"""
    return [
        ToolEvalCase(
            id="ad_01",
            tool_name="analyze_data",
            description="sum - 商机金额汇总",
            category="normal",
            input_data={
                "entity_api_key": "opportunity",
                "metrics": [{"field": "amount", "function": "sum"}],
            },
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="不应报错"),
            ],
        ),
        ToolEvalCase(
            id="ad_02",
            tool_name="analyze_data",
            description="count + group_by - 按阶段统计商机数",
            category="normal",
            input_data={
                "entity_api_key": "opportunity",
                "metrics": [{"field": "id", "function": "count"}],
                "group_by": "stage",
            },
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="不应报错"),
            ],
        ),
        ToolEvalCase(
            id="ad_03",
            tool_name="analyze_data",
            description="不存在的 entity",
            category="error",
            input_data={
                "entity_api_key": "nonexistent",
                "metrics": [{"field": "id", "function": "count"}],
            },
            assertions=[
                Assertion(type=AssertionType.IS_ERROR, description="应返回错误"),
            ],
        ),
    ]


def build_metarepo_cases() -> list[ToolEvalCase]:
    """browse_metamodel / query_metadata 工具评测用例"""
    return [
        ToolEvalCase(
            id="mr_01",
            tool_name="browse_metamodel",
            description="列出所有元模型",
            category="normal",
            input_data={"action": "list"},
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="不应报错"),
            ],
        ),
        ToolEvalCase(
            id="mr_02",
            tool_name="query_metadata",
            description="查询元数据实例",
            category="normal",
            input_data={"metamodel_api_key": "entity", "action": "list"},
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="不应报错"),
            ],
        ),
    ]


def build_default_suite() -> ToolEvalSuite:
    """构建默认的完整评测集"""
    all_cases = (
        build_query_schema_cases()
        + build_query_data_cases()
        + build_modify_data_cases()
        + build_analyze_data_cases()
        + build_metarepo_cases()
    )

    return ToolEvalSuite(
        id="suite_default",
        name="Tool 评测 — 默认全量",
        description="覆盖所有内置工具的正常/异常/边界/副作用场景",
        cases=all_cases,
    )
