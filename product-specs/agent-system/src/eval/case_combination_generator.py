"""用例参数组合自动生成器

核心能力：
    1. 根据工具的 input_schema 自动推导所有参数组合
    2. 覆盖正向场景（valid combinations）和逆向场景（invalid/boundary）
    3. 支持按 tool_name + method_name 粒度生成
    4. 生成结果为 ToolEvalCase 列表，可直接入库

设计思路：
    - 每个工具方法对应一个 CombinationSpec（组合规格定义）
    - CombinationSpec 声明该方法的参数空间（valid values + invalid values + boundary values）
    - Generator 通过笛卡尔积 + 边界值分析 自动生成用例
    - 正向用例：所有合法参数的代表性组合
    - 逆向用例：单参数非法 + 多参数交叉非法
"""
from __future__ import annotations

import itertools
import uuid
from dataclasses import dataclass, field
from typing import Any

from src.eval.tool_eval_runner import ToolEvalCase, Assertion, AssertionType


# ═══════════════════════════════════════════════════════════
# 参数空间定义
# ═══════════════════════════════════════════════════════════

@dataclass
class ParamValueSet:
    """单个参数的值空间"""
    param_name: str
    # 正向合法值（至少一个）
    valid_values: list[Any] = field(default_factory=list)
    # 逆向非法值（期望触发错误）
    invalid_values: list[Any] = field(default_factory=list)
    # 边界值（可能正常也可能异常，视具体工具实现）
    boundary_values: list[Any] = field(default_factory=list)
    # 该参数是否必填
    required: bool = True
    # 缺省值（非必填时的默认）
    default_value: Any = None


@dataclass
class MethodCombinationSpec:
    """某个工具方法的参数组合规格"""
    tool_name: str
    method_name: str  # 对应 input_data 中的 action/query_type 等字段值
    # 决定方法的分派字段（如 query_type, action）
    dispatch_field: str = "query_type"
    dispatch_value: str = ""
    # 该方法的参数空间
    param_sets: list[ParamValueSet] = field(default_factory=list)
    # 固定参数（每个用例都带上）
    fixed_params: dict = field(default_factory=dict)
    # 正向用例的通用断言
    positive_assertions: list[Assertion] = field(default_factory=list)
    # 逆向用例的通用断言
    negative_assertions: list[Assertion] = field(default_factory=list)


# ═══════════════════════════════════════════════════════════
# 组合生成器
# ═══════════════════════════════════════════════════════════

class CaseCombinationGenerator:
    """参数组合用例生成器

    生成策略：
    1. 正向全覆盖：所有 required 参数的 valid_values 笛卡尔积
       - 如果组合数超过 max_positive，采用 pairwise（两两覆盖）策略
    2. 逆向单因子：每次只有一个参数取 invalid_value，其余取 valid 默认值
    3. 边界探测：每次一个参数取 boundary_value，其余取 valid 默认值
    4. 缺失参数：required 参数逐个缺失
    """

    def __init__(self, max_positive: int = 50, max_negative_per_param: int = 5):
        self.max_positive = max_positive
        self.max_negative_per_param = max_negative_per_param

    def generate(self, spec: MethodCombinationSpec) -> list[ToolEvalCase]:
        """根据 spec 生成全部用例"""
        cases: list[ToolEvalCase] = []
        cases.extend(self._generate_positive(spec))
        cases.extend(self._generate_negative(spec))
        cases.extend(self._generate_boundary(spec))
        cases.extend(self._generate_missing_required(spec))
        return cases

    def _generate_positive(self, spec: MethodCombinationSpec) -> list[ToolEvalCase]:
        """正向用例：合法参数组合"""
        cases = []
        # 收集所有参数的 valid values
        param_names = []
        param_value_lists = []
        for ps in spec.param_sets:
            if ps.valid_values:
                param_names.append(ps.param_name)
                param_value_lists.append(ps.valid_values)

        if not param_value_lists:
            # 无额外参数，只生成一个基础用例
            input_data = {spec.dispatch_field: spec.dispatch_value, **spec.fixed_params}
            cases.append(self._make_case(
                spec, input_data, "normal",
                f"{spec.method_name} - 基础调用",
                spec.positive_assertions,
                tags=["positive", "base"],
            ))
            return cases

        # 笛卡尔积
        all_combos = list(itertools.product(*param_value_lists))

        # 如果组合过多，采用 pairwise 采样
        if len(all_combos) > self.max_positive:
            all_combos = self._pairwise_sample(param_value_lists, self.max_positive)

        for idx, combo in enumerate(all_combos):
            input_data = {spec.dispatch_field: spec.dispatch_value, **spec.fixed_params}
            desc_parts = []
            for pname, pval in zip(param_names, combo):
                input_data[pname] = pval
                desc_parts.append(f"{pname}={self._format_value(pval)}")

            cases.append(self._make_case(
                spec, input_data, "normal",
                f"{spec.method_name} - 正向({', '.join(desc_parts)})",
                spec.positive_assertions,
                tags=["positive", "combination"],
            ))

        return cases

    def _generate_negative(self, spec: MethodCombinationSpec) -> list[ToolEvalCase]:
        """逆向用例：每次一个参数取非法值"""
        cases = []
        # 默认合法参数集（取每个参数的第一个 valid value）
        base_params = {}
        for ps in spec.param_sets:
            if ps.valid_values:
                base_params[ps.param_name] = ps.valid_values[0]
            elif ps.default_value is not None:
                base_params[ps.param_name] = ps.default_value

        for ps in spec.param_sets:
            for inv_val in ps.invalid_values[:self.max_negative_per_param]:
                input_data = {
                    spec.dispatch_field: spec.dispatch_value,
                    **spec.fixed_params,
                    **base_params,
                    ps.param_name: inv_val,
                }
                cases.append(self._make_case(
                    spec, input_data, "error",
                    f"{spec.method_name} - 逆向({ps.param_name}={self._format_value(inv_val)})",
                    spec.negative_assertions or [
                        Assertion(type=AssertionType.IS_ERROR, description="非法参数应返回错误"),
                    ],
                    tags=["negative", "invalid_param"],
                ))

        return cases

    def _generate_boundary(self, spec: MethodCombinationSpec) -> list[ToolEvalCase]:
        """边界用例：每次一个参数取边界值"""
        cases = []
        base_params = {}
        for ps in spec.param_sets:
            if ps.valid_values:
                base_params[ps.param_name] = ps.valid_values[0]
            elif ps.default_value is not None:
                base_params[ps.param_name] = ps.default_value

        for ps in spec.param_sets:
            for bv in ps.boundary_values:
                input_data = {
                    spec.dispatch_field: spec.dispatch_value,
                    **spec.fixed_params,
                    **base_params,
                    ps.param_name: bv,
                }
                # 边界值用例不确定是否报错，只断言不崩溃
                cases.append(self._make_case(
                    spec, input_data, "boundary",
                    f"{spec.method_name} - 边界({ps.param_name}={self._format_value(bv)})",
                    [
                        # 边界用例至少不应该异常崩溃（超时/500）
                        # 具体是否 is_error 取决于实现，此处不做强断言
                    ],
                    tags=["boundary"],
                ))

        return cases

    def _generate_missing_required(self, spec: MethodCombinationSpec) -> list[ToolEvalCase]:
        """缺失必填参数的用例"""
        cases = []
        required_params = [ps for ps in spec.param_sets if ps.required]

        # 构建完整的合法基础输入
        base_params = {}
        for ps in spec.param_sets:
            if ps.valid_values:
                base_params[ps.param_name] = ps.valid_values[0]

        for missing_ps in required_params:
            input_data = {
                spec.dispatch_field: spec.dispatch_value,
                **spec.fixed_params,
                **{k: v for k, v in base_params.items() if k != missing_ps.param_name},
            }
            cases.append(self._make_case(
                spec, input_data, "error",
                f"{spec.method_name} - 缺失必填参数({missing_ps.param_name})",
                [Assertion(type=AssertionType.IS_ERROR, description=f"缺少 {missing_ps.param_name} 应报错")],
                tags=["negative", "missing_required"],
            ))

        return cases

    def _make_case(
        self, spec: MethodCombinationSpec, input_data: dict,
        category: str, description: str, assertions: list[Assertion],
        tags: list[str] = None,
    ) -> ToolEvalCase:
        """构建 ToolEvalCase"""
        case_id = f"{spec.tool_name}_{spec.method_name}_{uuid.uuid4().hex[:6]}"
        return ToolEvalCase(
            id=case_id,
            tool_name=spec.tool_name,
            description=description,
            input_data=input_data,
            assertions=assertions if assertions else [
                Assertion(type=AssertionType.NOT_ERROR, description="不应报错"),
            ],
            category=category,
        )

    def _format_value(self, val: Any) -> str:
        """格式化参数值用于描述"""
        if isinstance(val, str):
            return f"'{val}'" if len(val) < 30 else f"'{val[:27]}...'"
        if isinstance(val, dict):
            return "{...}"
        if isinstance(val, list):
            return f"[{len(val)} items]"
        return str(val)

    def _pairwise_sample(self, value_lists: list[list], max_count: int) -> list[tuple]:
        """Pairwise（两两覆盖）采样 — 保证任意两个参数的所有值组合至少出现一次

        简化实现：取前 max_count 个组合（优先覆盖首尾值）
        """
        # 简化策略：先加入每个参数的所有首尾值组合，再随机补充
        result = []
        n = len(value_lists)

        # 策略1：每个参数的第一个值 + 其他参数轮换
        for i in range(n):
            for val in value_lists[i]:
                combo = []
                for j in range(n):
                    if j == i:
                        combo.append(val)
                    else:
                        combo.append(value_lists[j][0])
                result.append(tuple(combo))

        # 策略2：补充交叉组合
        if len(result) < max_count:
            all_combos = list(itertools.product(*value_lists))
            for combo in all_combos:
                if combo not in result:
                    result.append(combo)
                    if len(result) >= max_count:
                        break

        # 去重
        seen = set()
        unique = []
        for combo in result:
            key = str(combo)
            if key not in seen:
                seen.add(key)
                unique.append(combo)
                if len(unique) >= max_count:
                    break

        return unique


# ═══════════════════════════════════════════════════════════
# 内置工具的 CombinationSpec 定义
# ═══════════════════════════════════════════════════════════

def build_query_schema_specs() -> list[MethodCombinationSpec]:
    """query_schema 工具的所有方法组合规格"""
    return [
        # list_entities — 无额外参数
        MethodCombinationSpec(
            tool_name="query_schema",
            method_name="list_entities",
            dispatch_field="query_type",
            dispatch_value="list_entities",
            param_sets=[],
            positive_assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="不应报错"),
                Assertion(type=AssertionType.CONTAINS, expected="account", description="包含 account"),
            ],
        ),
        # entity — 查看单个业务对象定义
        MethodCombinationSpec(
            tool_name="query_schema",
            method_name="entity",
            dispatch_field="query_type",
            dispatch_value="entity",
            param_sets=[
                ParamValueSet(
                    param_name="entity_api_key",
                    valid_values=["account", "opportunity", "contact", "activity", "lead"],
                    invalid_values=["nonexistent_xyz", "", "123", "a" * 200],
                    boundary_values=["Account", "ACCOUNT"],  # 大小写
                    required=True,
                ),
            ],
            positive_assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="不应报错"),
            ],
            negative_assertions=[
                Assertion(type=AssertionType.IS_ERROR, description="不存在的 entity 应报错"),
            ],
        ),
        # entity_items
        MethodCombinationSpec(
            tool_name="query_schema",
            method_name="entity_items",
            dispatch_field="query_type",
            dispatch_value="entity_items",
            param_sets=[
                ParamValueSet(
                    param_name="entity_api_key",
                    valid_values=["account", "opportunity", "contact"],
                    invalid_values=["nonexistent", ""],
                    boundary_values=[],
                    required=True,
                ),
            ],
            positive_assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="不应报错"),
            ],
            negative_assertions=[
                Assertion(type=AssertionType.IS_ERROR, description="应返回错误"),
            ],
        ),
        # entity_links
        MethodCombinationSpec(
            tool_name="query_schema",
            method_name="entity_links",
            dispatch_field="query_type",
            dispatch_value="entity_links",
            param_sets=[
                ParamValueSet(
                    param_name="entity_api_key",
                    valid_values=["account", "opportunity", "contact"],
                    invalid_values=["nonexistent"],
                    boundary_values=[],
                    required=True,
                ),
            ],
            positive_assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="不应报错"),
            ],
            negative_assertions=[
                Assertion(type=AssertionType.IS_ERROR, description="应返回错误"),
            ],
        ),
        # entity_pick_options
        MethodCombinationSpec(
            tool_name="query_schema",
            method_name="entity_pick_options",
            dispatch_field="query_type",
            dispatch_value="entity_pick_options",
            param_sets=[
                ParamValueSet(
                    param_name="entity_api_key",
                    valid_values=["opportunity", "lead"],
                    invalid_values=["nonexistent"],
                    required=True,
                ),
                ParamValueSet(
                    param_name="item_api_key",
                    valid_values=["stage", "source"],
                    invalid_values=["nonexistent_field", ""],
                    required=True,
                ),
            ],
            positive_assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="不应报错"),
            ],
            negative_assertions=[
                Assertion(type=AssertionType.IS_ERROR, description="应返回错误"),
            ],
        ),
    ]


def build_query_data_specs() -> list[MethodCombinationSpec]:
    """query_data 工具的方法组合规格"""
    return [
        # query — 列表查询
        MethodCombinationSpec(
            tool_name="query_data",
            method_name="query",
            dispatch_field="action",
            dispatch_value="query",
            fixed_params={},
            param_sets=[
                ParamValueSet(
                    param_name="entity_api_key",
                    valid_values=["account", "opportunity", "contact"],
                    invalid_values=["nonexistent_entity", ""],
                    boundary_values=[],
                    required=True,
                ),
                ParamValueSet(
                    param_name="filters",
                    valid_values=[{}, {"owner_name": "张三"}, {"name": "华为"}],
                    invalid_values=[],
                    boundary_values=[{"nonexistent_field": "xxx"}],
                    required=False,
                    default_value={},
                ),
                ParamValueSet(
                    param_name="page",
                    valid_values=[1, 2],
                    invalid_values=[0, -1],
                    boundary_values=[9999],
                    required=False,
                    default_value=1,
                ),
                ParamValueSet(
                    param_name="page_size",
                    valid_values=[5, 10, 20],
                    invalid_values=[0, -1],
                    boundary_values=[1, 100],
                    required=False,
                    default_value=20,
                ),
                ParamValueSet(
                    param_name="order_by",
                    valid_values=["name", "-name", "created_at"],
                    invalid_values=[],
                    boundary_values=["nonexistent_field"],
                    required=False,
                ),
            ],
            positive_assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="不应报错"),
                Assertion(type=AssertionType.CONTAINS, expected="records", description="返回 records"),
            ],
            negative_assertions=[
                Assertion(type=AssertionType.IS_ERROR, description="应返回错误"),
            ],
        ),
        # get — 单条查询
        MethodCombinationSpec(
            tool_name="query_data",
            method_name="get",
            dispatch_field="action",
            dispatch_value="get",
            param_sets=[
                ParamValueSet(
                    param_name="entity_api_key",
                    valid_values=["account", "opportunity"],
                    invalid_values=["nonexistent"],
                    required=True,
                ),
                ParamValueSet(
                    param_name="record_id",
                    valid_values=["acc_001", "opp_001"],
                    invalid_values=["acc_999999", ""],
                    boundary_values=["acc_not_id_format_test"],
                    required=True,
                ),
            ],
            positive_assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="不应报错"),
            ],
            negative_assertions=[
                Assertion(type=AssertionType.IS_ERROR, description="应返回错误"),
            ],
        ),
        # count
        MethodCombinationSpec(
            tool_name="query_data",
            method_name="count",
            dispatch_field="action",
            dispatch_value="count",
            param_sets=[
                ParamValueSet(
                    param_name="entity_api_key",
                    valid_values=["account", "opportunity", "contact"],
                    invalid_values=["nonexistent"],
                    required=True,
                ),
                ParamValueSet(
                    param_name="filters",
                    valid_values=[{}, {"owner_name": "张三"}],
                    invalid_values=[],
                    required=False,
                    default_value={},
                ),
            ],
            positive_assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="不应报错"),
                Assertion(type=AssertionType.CONTAINS, expected="记录数", description="返回统计结果"),
            ],
            negative_assertions=[
                Assertion(type=AssertionType.IS_ERROR, description="应返回错误"),
            ],
        ),
    ]


def build_modify_data_specs() -> list[MethodCombinationSpec]:
    """modify_data 工具的方法组合规格"""
    return [
        # create
        MethodCombinationSpec(
            tool_name="modify_data",
            method_name="create",
            dispatch_field="action",
            dispatch_value="create",
            param_sets=[
                ParamValueSet(
                    param_name="entity_api_key",
                    valid_values=["account", "opportunity", "contact"],
                    invalid_values=["nonexistent", ""],
                    required=True,
                ),
                ParamValueSet(
                    param_name="data",
                    valid_values=[
                        {"name": "测试客户A", "industry": "科技"},
                        {"name": "测试客户B", "owner_name": "张三"},
                    ],
                    invalid_values=[{}, None],
                    boundary_values=[{"name": "x" * 500}],  # 超长名称
                    required=True,
                ),
            ],
            positive_assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="创建不应报错"),
            ],
            negative_assertions=[
                Assertion(type=AssertionType.IS_ERROR, description="应返回错误"),
            ],
        ),
        # update
        MethodCombinationSpec(
            tool_name="modify_data",
            method_name="update",
            dispatch_field="action",
            dispatch_value="update",
            param_sets=[
                ParamValueSet(
                    param_name="entity_api_key",
                    valid_values=["account", "opportunity"],
                    invalid_values=["nonexistent"],
                    required=True,
                ),
                ParamValueSet(
                    param_name="record_id",
                    valid_values=["acc_001", "opp_001"],
                    invalid_values=["acc_not_exist", ""],
                    required=True,
                ),
                ParamValueSet(
                    param_name="data",
                    valid_values=[
                        {"name": "更新名称"},
                        {"industry": "金融"},
                    ],
                    invalid_values=[{}],
                    required=True,
                ),
            ],
            positive_assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="更新不应报错"),
            ],
            negative_assertions=[
                Assertion(type=AssertionType.IS_ERROR, description="应返回错误"),
            ],
        ),
        # delete
        MethodCombinationSpec(
            tool_name="modify_data",
            method_name="delete",
            dispatch_field="action",
            dispatch_value="delete",
            param_sets=[
                ParamValueSet(
                    param_name="entity_api_key",
                    valid_values=["account"],
                    invalid_values=["nonexistent"],
                    required=True,
                ),
                ParamValueSet(
                    param_name="record_id",
                    valid_values=["acc_001"],
                    invalid_values=["acc_not_exist", ""],
                    required=True,
                ),
            ],
            positive_assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="删除不应报错"),
            ],
            negative_assertions=[
                Assertion(type=AssertionType.IS_ERROR, description="应返回错误"),
            ],
        ),
    ]


def build_analyze_data_specs() -> list[MethodCombinationSpec]:
    """analyze_data 工具的方法组合规格"""
    return [
        MethodCombinationSpec(
            tool_name="analyze_data",
            method_name="aggregate",
            dispatch_field="entity_api_key",
            dispatch_value="opportunity",
            param_sets=[
                ParamValueSet(
                    param_name="entity_api_key",
                    valid_values=["opportunity", "account"],
                    invalid_values=["nonexistent"],
                    required=True,
                ),
                ParamValueSet(
                    param_name="metrics",
                    valid_values=[
                        [{"field": "amount", "function": "sum"}],
                        [{"field": "id", "function": "count"}],
                        [{"field": "amount", "function": "avg"}],
                        [{"field": "amount", "function": "sum"}, {"field": "id", "function": "count"}],
                    ],
                    invalid_values=[
                        [],  # 空指标
                        [{"field": "nonexistent", "function": "sum"}],
                    ],
                    required=True,
                ),
                ParamValueSet(
                    param_name="group_by",
                    valid_values=[None, "stage", "owner_name"],
                    invalid_values=[],
                    boundary_values=["nonexistent_field"],
                    required=False,
                ),
                ParamValueSet(
                    param_name="filters",
                    valid_values=[{}, {"owner_name": "张三"}],
                    invalid_values=[],
                    required=False,
                    default_value={},
                ),
            ],
            positive_assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="不应报错"),
            ],
            negative_assertions=[
                Assertion(type=AssertionType.IS_ERROR, description="应返回错误"),
            ],
        ),
    ]


# ═══════════════════════════════════════════════════════════
# 顶层入口
# ═══════════════════════════════════════════════════════════

def get_all_combination_specs() -> dict[str, list[MethodCombinationSpec]]:
    """获取所有内置工具的组合规格，按工具名分组"""
    return {
        "query_schema": build_query_schema_specs(),
        "query_data": build_query_data_specs(),
        "modify_data": build_modify_data_specs(),
        "analyze_data": build_analyze_data_specs(),
    }


def generate_all_cases(
    tool_name: str | None = None,
    method_name: str | None = None,
    max_positive: int = 50,
) -> list[ToolEvalCase]:
    """生成用例入口

    Args:
        tool_name: 指定工具名（None=全部工具）
        method_name: 指定方法名（None=该工具全部方法）
        max_positive: 正向用例最大数

    Returns:
        生成的用例列表
    """
    generator = CaseCombinationGenerator(max_positive=max_positive)
    all_specs = get_all_combination_specs()
    cases = []

    for t_name, specs in all_specs.items():
        if tool_name and t_name != tool_name:
            continue
        for spec in specs:
            if method_name and spec.method_name != method_name:
                continue
            generated = generator.generate(spec)
            cases.extend(generated)

    return cases


def generate_cases_summary(
    tool_name: str | None = None,
    method_name: str | None = None,
) -> dict:
    """生成用例概览统计（不实际生成，只报告将生成多少）"""
    all_specs = get_all_combination_specs()
    generator = CaseCombinationGenerator()
    summary = {}

    for t_name, specs in all_specs.items():
        if tool_name and t_name != tool_name:
            continue
        tool_summary = {}
        for spec in specs:
            if method_name and spec.method_name != method_name:
                continue
            cases = generator.generate(spec)
            tool_summary[spec.method_name] = {
                "total": len(cases),
                "positive": sum(1 for c in cases if c.category == "normal"),
                "negative": sum(1 for c in cases if c.category == "error"),
                "boundary": sum(1 for c in cases if c.category == "boundary"),
            }
        if tool_summary:
            summary[t_name] = tool_summary

    return summary
