"""链路评测 REST API

路由前缀：/api/eval/chain

核心能力：
    - 评测集（Suite）管理 — 创建/列出链路评测集
    - 用例（Case）管理 — 评测集内的链路测试用例 CRUD
    - 执行评测 — 全量/按集执行，返回 run_id
    - SSE 流式执行 — 实时推送每个用例进度和链路 Span
    - 运行历史 — 查看历史运行及链路回放详情
    - 对比报告 — 两次运行结果 diff

路由：
    GET    /api/eval/chain/suites                    评测集列表
    POST   /api/eval/chain/suites                    创建评测集
    GET    /api/eval/chain/suites/{id}/cases         评测集下的用例
    POST   /api/eval/chain/suites/{id}/cases         添加用例
    DELETE /api/eval/chain/suites/{id}/cases/{cid}   删除用例
    POST   /api/eval/chain/run                       执行评测（返回 run_id）
    POST   /api/eval/chain/run-stream                SSE 流式执行
    GET    /api/eval/chain/runs                      历史运行列表
    GET    /api/eval/chain/runs/{run_id}             运行详情（含所有用例结果）
    GET    /api/eval/chain/runs/{run_id}/cases/{id}  单个用例的链路回放数据
    GET    /api/eval/chain/reports/compare            对比两次运行的 diff
    GET    /api/eval/chain/stats                     全局统计（顶部卡片）
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/eval/chain", tags=["chain-eval"])


# ═══════════════════════════════════════════════════════════
# 内存存储（MVP — 后续可切换到 DB）
# ═══════════════════════════════════════════════════════════

# 评测集
_suites: dict[str, dict] = {}
# 用例：suite_id → [case, ...]
_cases: dict[str, list[dict]] = {}
# 运行记录
_runs: list[dict] = []
# 运行详情：run_id → {run_info + cases_results}
_run_details: dict[str, dict] = {}


def _init_demo_data():
    """初始化演示数据"""
    if _suites:
        return

    # 评测集 1：订单取消场景回归
    suite1_id = "suite_cancel_order"
    _suites[suite1_id] = {
        "id": suite1_id,
        "name": "订单取消场景回归",
        "description": "覆盖订单取消的正常/异常/边界场景，验证 Agent 推理链路",
        "created_at": int(time.time() * 1000) - 86400000,
        "updated_at": int(time.time() * 1000) - 600000,
    }
    _cases[suite1_id] = [
        {
            "id": "cancel_normal_001",
            "suite_id": suite1_id,
            "name": "正常取消待支付订单",
            "input": "取消我的订单 ORD-001",
            "expected_behavior": "确认取消 + 退款提示",
            "assertions": [
                {"type": "contains_any", "expected": ["已取消", "取消成功"], "description": "回复应包含取消确认"},
                {"type": "tool_call_check", "expected": "cancel_order", "mode": "must_call", "description": "应调用 cancel_order"},
            ],
            "mock_tools": {
                "query_data": {"status": "pending_payment", "order_id": "ORD-001", "amount": 299.0},
                "cancel_order": {"success": True, "refund_amount": 299.0},
            },
            "tags": ["normal", "cancel"],
        },
        {
            "id": "cancel_normal_refund",
            "suite_id": suite1_id,
            "name": "取消后退款确认",
            "input": "帮我取消订单 ORD-003，我要退款",
            "expected_behavior": "取消订单并确认退款流程",
            "assertions": [
                {"type": "contains_any", "expected": ["退款", "已取消"], "description": "应提及退款"},
                {"type": "tool_call_check", "expected": "cancel_order", "mode": "must_call", "description": "应调用 cancel_order"},
            ],
            "mock_tools": {
                "query_data": {"status": "pending_payment", "order_id": "ORD-003", "amount": 159.0},
                "cancel_order": {"success": True, "refund_amount": 159.0},
            },
            "tags": ["normal", "refund"],
        },
        {
            "id": "cancel_shipped_002",
            "suite_id": suite1_id,
            "name": "已发货订单不可取消",
            "input": "取消我的订单 ORD-002",
            "expected_behavior": "拒绝取消 + 说明原因（已发货）",
            "assertions": [
                {"type": "tool_call_check", "expected": "cancel_order", "mode": "must_not_call", "description": "cancel_order 不应被调用"},
                {"type": "contains_any", "expected": ["无法取消", "已发货", "不能取消"], "description": "回复应说明已发货不可取消"},
                {"type": "tool_call_check", "expected": "query_data", "mode": "must_call", "description": "应先查询订单状态"},
            ],
            "mock_tools": {
                "query_data": {"status": "shipped", "order_id": "ORD-002", "tracking_no": "SF123456"},
                "cancel_order": {"success": False, "reason": "已发货不可取消"},
            },
            "tags": ["error", "shipped"],
        },
        {
            "id": "cancel_not_found_003",
            "suite_id": suite1_id,
            "name": "订单不存在",
            "input": "取消订单 ORD-999",
            "expected_behavior": "提示订单不存在",
            "assertions": [
                {"type": "contains_any", "expected": ["不存在", "未找到", "找不到"], "description": "应提示订单不存在"},
            ],
            "mock_tools": {
                "query_data": None,
            },
            "tags": ["error", "not_found"],
        },
        {
            "id": "cancel_quality_004",
            "suite_id": suite1_id,
            "name": "回复质量(LLM Judge)",
            "input": "我昨天买的那个东西不想要了，帮我退了吧",
            "expected_behavior": "理解模糊表达，确认具体订单后取消",
            "assertions": [
                {"type": "llm_judge", "expected": "回复应友好、专业，正确理解用户退货意图", "description": "LLM 判定回复质量"},
            ],
            "mock_tools": {
                "query_data": {"status": "pending_shipment", "order_id": "ORD-005", "item": "蓝牙耳机", "amount": 199.0},
                "cancel_order": {"success": True, "refund_amount": 199.0},
            },
            "tags": ["quality"],
        },
        {
            "id": "cancel_ambiguous_005",
            "suite_id": suite1_id,
            "name": "模糊表达取消",
            "input": "那个订单别发了",
            "expected_behavior": "理解取消意图，查询最近订单并确认",
            "assertions": [
                {"type": "tool_call_check", "expected": "query_data", "mode": "must_call", "description": "应查询订单"},
            ],
            "mock_tools": {
                "query_data": {"status": "pending_shipment", "order_id": "ORD-006", "item": "手机壳"},
            },
            "tags": ["boundary", "ambiguous"],
        },
    ]

    # 评测集 2：客户查询链路
    suite2_id = "suite_customer_query"
    _suites[suite2_id] = {
        "id": suite2_id,
        "name": "客户查询链路",
        "description": "验证客户信息查询的完整链路",
        "created_at": int(time.time() * 1000) - 172800000,
        "updated_at": int(time.time() * 1000) - 3600000,
    }
    _cases[suite2_id] = [
        {
            "id": "cust_query_basic_001",
            "suite_id": suite2_id,
            "name": "基本客户信息查询",
            "input": "查看客户张三的信息",
            "expected_behavior": "返回客户基本信息",
            "assertions": [
                {"type": "tool_call_check", "expected": "query_data", "mode": "must_call", "description": "应调用查询"},
                {"type": "contains_any", "expected": ["张三"], "description": "应包含客户名称"},
            ],
            "mock_tools": {
                "query_data": {"name": "张三", "phone": "13800138000", "level": "VIP"},
            },
            "tags": ["normal"],
        },
        {
            "id": "cust_query_order_002",
            "suite_id": suite2_id,
            "name": "查询客户订单",
            "input": "张三最近有什么订单",
            "expected_behavior": "返回客户的订单列表",
            "assertions": [
                {"type": "tool_call_check", "expected": "query_data", "mode": "must_call", "description": "应查询订单"},
            ],
            "mock_tools": {
                "query_data": [
                    {"order_id": "ORD-100", "status": "completed", "amount": 599.0},
                    {"order_id": "ORD-101", "status": "pending", "amount": 299.0},
                ],
            },
            "tags": ["normal"],
        },
    ]

    # 评测集 3（空集，用于展示创建）
    suite3_id = "suite_refund_flow"
    _suites[suite3_id] = {
        "id": suite3_id,
        "name": "退款流程验证",
        "description": "验证退款链路各节点的正确性",
        "created_at": int(time.time() * 1000) - 3600000,
        "updated_at": int(time.time() * 1000) - 3600000,
    }
    _cases[suite3_id] = []

    # 初始化一些历史运行记录
    _init_demo_runs()


def _init_demo_runs():
    """初始化演示运行记录"""
    now = int(time.time() * 1000)

    # Run #5 — 最近的运行
    run5 = _create_demo_run(
        run_id="run_005",
        suite_id="suite_cancel_order",
        suite_name="订单取消场景回归",
        total=6, passed=5, failed=1,
        duration_ms=12400,
        token_total=9840,
        created_at=now - 600000,  # 10分钟前
    )
    _runs.append(run5)
    _run_details["run_005"] = _build_run5_detail(run5)

    # Run #4
    run4 = _create_demo_run(
        run_id="run_004",
        suite_id="suite_cancel_order",
        suite_name="订单取消场景回归",
        total=6, passed=5, failed=1,
        duration_ms=13200,
        token_total=10200,
        created_at=now - 86400000,
    )
    _runs.append(run4)

    # Run #3
    run3 = _create_demo_run(
        run_id="run_003",
        suite_id="suite_customer_query",
        suite_name="客户查询链路",
        total=2, passed=2, failed=0,
        duration_ms=4100,
        token_total=3200,
        created_at=now - 172800000,
    )
    _runs.append(run3)


def _create_demo_run(run_id, suite_id, suite_name, total, passed, failed, duration_ms, token_total, created_at):
    return {
        "run_id": run_id,
        "suite_id": suite_id,
        "suite_name": suite_name,
        "total": total,
        "passed": passed,
        "failed": failed,
        "pass_rate": passed / max(total, 1),
        "duration_ms": duration_ms,
        "token_total": token_total,
        "created_at": created_at,
        "status": "completed",
    }


def _build_run5_detail(run_info: dict) -> dict:
    """构建 Run#5 的完整详情（含链路回放数据）"""
    cases_results = [
        {
            "case_id": "cancel_normal_001",
            "case_name": "正常取消待支付订单",
            "status": "passed",
            "input": "取消我的订单 ORD-001",
            "final_response": "好的，已为您取消订单 ORD-001，退款 299 元将在 1-3 个工作日内退回原支付方式。",
            "latency_ms": 2070,
            "token_usage": {"input": 1200, "output": 80, "total": 1280},
            "chain": [
                {"id": "span_1", "type": "content_review", "status": "passed", "start_ms": 0, "duration_ms": 2, "metadata": {"passed": True}},
                {"id": "span_2", "type": "memory_retrieve", "status": "passed", "start_ms": 2, "duration_ms": 38, "metadata": {"hits": 1, "dimensions": ["user_profile"]}},
                {"id": "span_3", "type": "llm_call", "round": 1, "status": "passed", "start_ms": 40, "duration_ms": 820,
                 "metadata": {"model": "deepseek-v4-flash", "tokens_in": 320, "tokens_out": 45, "decision": "tool_call", "tool_name": "query_data", "tool_args": {"entity_api_key": "order", "conditions": {"order_id": "ORD-001"}}},
                 "expandable": {"input_messages": [{"role": "system", "content": "你是CRM助手..."}, {"role": "user", "content": "取消我的订单 ORD-001"}], "output_raw": "tool_call: query_data({...})"}},
                {"id": "span_4", "type": "tool_call", "tool_name": "query_data", "status": "passed", "start_ms": 860, "duration_ms": 2,
                 "metadata": {"is_mocked": True, "args": {"entity_api_key": "order", "conditions": {"order_id": "ORD-001"}}, "response": {"status": "pending_payment", "order_id": "ORD-001", "amount": 299.0}}},
                {"id": "span_5", "type": "llm_call", "round": 2, "status": "passed", "start_ms": 862, "duration_ms": 750,
                 "metadata": {"model": "deepseek-v4-flash", "tokens_in": 480, "tokens_out": 35, "decision": "tool_call", "tool_name": "cancel_order", "tool_args": {"order_id": "ORD-001"}},
                 "expandable": {"input_messages": [{"role": "system", "content": "你是CRM助手..."}, {"role": "user", "content": "取消我的订单 ORD-001"}, {"role": "tool", "content": "{\"status\":\"pending_payment\"}"}], "output_raw": "tool_call: cancel_order({order_id:'ORD-001'})"}},
                {"id": "span_6", "type": "tool_call", "tool_name": "cancel_order", "status": "passed", "start_ms": 1612, "duration_ms": 2,
                 "metadata": {"is_mocked": True, "args": {"order_id": "ORD-001"}, "response": {"success": True, "refund_amount": 299.0}}},
                {"id": "span_7", "type": "llm_call", "round": 3, "status": "passed", "start_ms": 1614, "duration_ms": 456,
                 "metadata": {"model": "deepseek-v4-flash", "tokens_in": 600, "tokens_out": 80, "decision": "final_response"},
                 "expandable": {"input_messages": [{"role": "system", "content": "你是CRM助手..."}, {"role": "user", "content": "取消我的订单 ORD-001"}, {"role": "tool", "content": "{\"success\":true,\"refund_amount\":299}"} ], "output_raw": "好的，已为您取消订单 ORD-001..."}},
            ],
            "assertions": [
                {"type": "contains_any", "passed": True, "detail": "回复包含'已取消'"},
                {"type": "tool_call_check", "passed": True, "detail": "cancel_order 被调用 ✓"},
            ],
        },
        {
            "case_id": "cancel_normal_refund",
            "case_name": "取消后退款确认",
            "status": "passed",
            "input": "帮我取消订单 ORD-003，我要退款",
            "final_response": "已为您取消订单 ORD-003，退款 159 元将退回原支付账户。",
            "latency_ms": 1850,
            "token_usage": {"input": 1100, "output": 65, "total": 1165},
            "chain": [
                {"id": "span_1", "type": "content_review", "status": "passed", "start_ms": 0, "duration_ms": 2, "metadata": {"passed": True}},
                {"id": "span_2", "type": "memory_retrieve", "status": "passed", "start_ms": 2, "duration_ms": 35, "metadata": {"hits": 1, "dimensions": ["user_profile"]}},
                {"id": "span_3", "type": "llm_call", "round": 1, "status": "passed", "start_ms": 37, "duration_ms": 780, "metadata": {"model": "deepseek-v4-flash", "tokens_in": 310, "tokens_out": 40, "decision": "tool_call", "tool_name": "query_data"}},
                {"id": "span_4", "type": "tool_call", "tool_name": "query_data", "status": "passed", "start_ms": 817, "duration_ms": 2, "metadata": {"is_mocked": True, "response": {"status": "pending_payment", "amount": 159.0}}},
                {"id": "span_5", "type": "llm_call", "round": 2, "status": "passed", "start_ms": 819, "duration_ms": 620, "metadata": {"decision": "tool_call", "tool_name": "cancel_order"}},
                {"id": "span_6", "type": "tool_call", "tool_name": "cancel_order", "status": "passed", "start_ms": 1439, "duration_ms": 1, "metadata": {"is_mocked": True, "response": {"success": True, "refund_amount": 159.0}}},
                {"id": "span_7", "type": "llm_call", "round": 3, "status": "passed", "start_ms": 1440, "duration_ms": 410, "metadata": {"decision": "final_response"}},
            ],
            "assertions": [
                {"type": "contains_any", "passed": True, "detail": "回复包含'退款'"},
                {"type": "tool_call_check", "passed": True, "detail": "cancel_order 被调用 ✓"},
            ],
        },
        {
            "case_id": "cancel_shipped_002",
            "case_name": "已发货订单不可取消",
            "status": "failed",
            "input": "取消我的订单 ORD-002",
            "final_response": "好的，已为您取消订单 ORD-002。",
            "latency_ms": 2120,
            "token_usage": {"input": 1550, "output": 100, "total": 1650},
            "chain": [
                {"id": "span_1", "type": "content_review", "status": "passed", "start_ms": 0, "duration_ms": 2, "metadata": {"passed": True}},
                {"id": "span_2", "type": "memory_retrieve", "status": "passed", "start_ms": 2, "duration_ms": 45, "metadata": {"hits": 2, "dimensions": ["user_profile", "customer_context"]}},
                {"id": "span_3", "type": "llm_call", "round": 1, "status": "passed", "start_ms": 47, "duration_ms": 850,
                 "metadata": {"model": "deepseek-v4-flash", "tokens_in": 320, "tokens_out": 45, "decision": "tool_call", "tool_name": "query_data", "tool_args": {"entity_api_key": "order", "action": "query", "conditions": {"order_id": "ORD-002"}}},
                 "expandable": {"input_messages": [{"role": "system", "content": "你是CRM助手，帮助用户处理订单相关问题。规则：已发货订单不可取消。"}, {"role": "user", "content": "取消我的订单 ORD-002"}], "output_raw": "tool_call: query_data({entity_api_key:'order', conditions:{order_id:'ORD-002'}})"}},
                {"id": "span_4", "type": "tool_call", "tool_name": "query_data", "status": "passed", "start_ms": 897, "duration_ms": 2,
                 "metadata": {"is_mocked": True, "args": {"entity_api_key": "order", "conditions": {"order_id": "ORD-002"}}, "response": {"status": "shipped", "tracking_no": "SF123456"}}},
                {"id": "span_5", "type": "llm_call", "round": 2, "status": "failed", "start_ms": 899, "duration_ms": 620,
                 "failure_reason": "Agent 未根据 status=shipped 判断不可取消",
                 "metadata": {"model": "deepseek-v4-flash", "tokens_in": 580, "tokens_out": 30, "decision": "tool_call", "tool_name": "cancel_order", "tool_args": {"order_id": "ORD-002"}, "expected_decision": "final_response", "expected_contains": "无法取消"},
                 "expandable": {"input_messages": [{"role": "system", "content": "你是CRM助手，帮助用户处理订单相关问题。规则：已发货订单不可取消。"}, {"role": "user", "content": "取消我的订单 ORD-002"}, {"role": "tool", "content": "{\"status\":\"shipped\",\"tracking_no\":\"SF123456\"}"}], "output_raw": "tool_call: cancel_order({order_id:'ORD-002'})"}},
                {"id": "span_6", "type": "tool_call", "tool_name": "cancel_order", "status": "warning", "start_ms": 1519, "duration_ms": 1,
                 "metadata": {"is_mocked": True, "args": {"order_id": "ORD-002"}, "response": {"success": False, "reason": "已发货不可取消"}}},
                {"id": "span_7", "type": "llm_call", "round": 3, "status": "failed", "start_ms": 1520, "duration_ms": 550,
                 "failure_reason": "回复 '好的，已为您取消' 无视 success=false",
                 "metadata": {"model": "deepseek-v4-flash", "tokens_in": 680, "tokens_out": 25, "decision": "final_response"},
                 "expandable": {"input_messages": [{"role": "system", "content": "你是CRM助手..."}, {"role": "user", "content": "取消我的订单 ORD-002"}, {"role": "tool", "content": "{\"success\":false,\"reason\":\"已发货不可取消\"}"}], "output_raw": "好的，已为您取消订单 ORD-002。"}},
            ],
            "assertions": [
                {"type": "tool_call_check", "passed": False, "detail": "cancel_order 不应被调用"},
                {"type": "contains_any", "passed": False, "detail": "回复应包含 '无法取消'/'已发货'"},
                {"type": "tool_call_check", "passed": True, "detail": "query_data 被调用 ✓"},
            ],
            "failure_attribution": {
                "type": "agent_reasoning_error",
                "node": "llm_call_2",
                "reason": "Agent 未根据 status='shipped' 判断不可取消",
                "suggestion": "检查 prompt 中是否有'已发货订单不可取消'的规则说明",
            },
        },
        {
            "case_id": "cancel_not_found_003",
            "case_name": "订单不存在",
            "status": "passed",
            "input": "取消订单 ORD-999",
            "final_response": "抱歉，未找到订单 ORD-999，请确认订单号是否正确。",
            "latency_ms": 1920,
            "token_usage": {"input": 900, "output": 50, "total": 950},
            "chain": [
                {"id": "span_1", "type": "content_review", "status": "passed", "start_ms": 0, "duration_ms": 2, "metadata": {"passed": True}},
                {"id": "span_2", "type": "memory_retrieve", "status": "passed", "start_ms": 2, "duration_ms": 30, "metadata": {"hits": 0, "dimensions": []}},
                {"id": "span_3", "type": "llm_call", "round": 1, "status": "passed", "start_ms": 32, "duration_ms": 800, "metadata": {"decision": "tool_call", "tool_name": "query_data"}},
                {"id": "span_4", "type": "tool_call", "tool_name": "query_data", "status": "passed", "start_ms": 832, "duration_ms": 2, "metadata": {"is_mocked": True, "response": None}},
                {"id": "span_5", "type": "llm_call", "round": 2, "status": "passed", "start_ms": 834, "duration_ms": 520, "metadata": {"decision": "final_response"}},
            ],
            "assertions": [
                {"type": "contains_any", "passed": True, "detail": "回复包含'未找到'"},
            ],
        },
        {
            "case_id": "cancel_quality_004",
            "case_name": "回复质量(LLM Judge)",
            "status": "passed",
            "input": "我昨天买的那个东西不想要了，帮我退了吧",
            "final_response": "好的，我帮您查看了最近的订单——蓝牙耳机（ORD-005，199元）。已为您取消并发起退款，预计1-3个工作日到账。还有其他需要帮助的吗？",
            "latency_ms": 3850,
            "token_usage": {"input": 1800, "output": 120, "total": 1920},
            "chain": [
                {"id": "span_1", "type": "content_review", "status": "passed", "start_ms": 0, "duration_ms": 3, "metadata": {"passed": True}},
                {"id": "span_2", "type": "memory_retrieve", "status": "passed", "start_ms": 3, "duration_ms": 42, "metadata": {"hits": 2, "dimensions": ["user_profile", "purchase_history"]}},
                {"id": "span_3", "type": "llm_call", "round": 1, "status": "passed", "start_ms": 45, "duration_ms": 1200, "metadata": {"decision": "tool_call", "tool_name": "query_data"}},
                {"id": "span_4", "type": "tool_call", "tool_name": "query_data", "status": "passed", "start_ms": 1245, "duration_ms": 2, "metadata": {"is_mocked": True, "response": {"order_id": "ORD-005", "item": "蓝牙耳机", "amount": 199.0, "status": "pending_shipment"}}},
                {"id": "span_5", "type": "llm_call", "round": 2, "status": "passed", "start_ms": 1247, "duration_ms": 900, "metadata": {"decision": "tool_call", "tool_name": "cancel_order"}},
                {"id": "span_6", "type": "tool_call", "tool_name": "cancel_order", "status": "passed", "start_ms": 2147, "duration_ms": 2, "metadata": {"is_mocked": True, "response": {"success": True, "refund_amount": 199.0}}},
                {"id": "span_7", "type": "llm_call", "round": 3, "status": "passed", "start_ms": 2149, "duration_ms": 680, "metadata": {"decision": "final_response"}},
                {"id": "span_8", "type": "llm_judge", "status": "passed", "start_ms": 2829, "duration_ms": 1020, "metadata": {"score": 0.92, "feedback": "回复友好专业，正确理解了模糊退货意图"}},
            ],
            "assertions": [
                {"type": "llm_judge", "passed": True, "detail": "LLM Judge 评分: 0.92 — 回复友好专业"},
            ],
        },
        {
            "case_id": "cancel_ambiguous_005",
            "case_name": "模糊表达取消",
            "status": "passed",
            "input": "那个订单别发了",
            "final_response": "好的，您是指最近的手机壳订单（ORD-006）吗？我已暂停发货，如确认取消请告知。",
            "latency_ms": 2230,
            "token_usage": {"input": 1300, "output": 75, "total": 1375},
            "chain": [
                {"id": "span_1", "type": "content_review", "status": "passed", "start_ms": 0, "duration_ms": 2, "metadata": {"passed": True}},
                {"id": "span_2", "type": "memory_retrieve", "status": "passed", "start_ms": 2, "duration_ms": 40, "metadata": {"hits": 1, "dimensions": ["recent_orders"]}},
                {"id": "span_3", "type": "llm_call", "round": 1, "status": "passed", "start_ms": 42, "duration_ms": 900, "metadata": {"decision": "tool_call", "tool_name": "query_data"}},
                {"id": "span_4", "type": "tool_call", "tool_name": "query_data", "status": "passed", "start_ms": 942, "duration_ms": 2, "metadata": {"is_mocked": True, "response": {"order_id": "ORD-006", "item": "手机壳", "status": "pending_shipment"}}},
                {"id": "span_5", "type": "llm_call", "round": 2, "status": "passed", "start_ms": 944, "duration_ms": 720, "metadata": {"decision": "final_response"}},
            ],
            "assertions": [
                {"type": "tool_call_check", "passed": True, "detail": "query_data 被调用 ✓"},
            ],
        },
    ]

    result = {
        **run_info,
        "cases": cases_results,
    }
    return result


# 初始化
_init_demo_data()


# ═══════════════════════════════════════════════════════════
# Pydantic 请求模型
# ═══════════════════════════════════════════════════════════

class CreateSuiteBody(BaseModel):
    name: str
    description: str = ""


class CreateCaseBody(BaseModel):
    name: str
    input: str
    expected_behavior: str = ""
    assertions: list[dict] = Field(default_factory=list)
    mock_tools: dict = Field(default_factory=dict)
    tags: list[str] = Field(default_factory=list)


class RunEvalBody(BaseModel):
    suite_ids: list[str] = Field(default_factory=list)  # 空 = 全部
    case_ids: list[str] = Field(default_factory=list)   # 指定用例


# ═══════════════════════════════════════════════════════════
# 全局统计
# ═══════════════════════════════════════════════════════════

@router.get("/stats")
async def get_stats():
    """全局统计 — 顶部卡片数据"""
    total_suites = len(_suites)
    total_cases = sum(len(cases) for cases in _cases.values())

    # 从最近一次运行计算通过率
    last_run = _runs[0] if _runs else None
    pass_rate = last_run["pass_rate"] if last_run else 0
    avg_duration = last_run["duration_ms"] / max(last_run["total"], 1) if last_run else 0

    # 上次运行时间
    last_run_at = last_run["created_at"] if last_run else None

    return {
        "total_suites": total_suites,
        "total_cases": total_cases,
        "pass_rate": round(pass_rate, 4),
        "avg_duration_ms": round(avg_duration, 1),
        "last_run_at": last_run_at,
        "total_runs": len(_runs),
    }


# ═══════════════════════════════════════════════════════════
# 评测集管理
# ═══════════════════════════════════════════════════════════

@router.get("/suites")
async def list_suites():
    """评测集列表"""
    result = []
    for sid, suite in _suites.items():
        cases = _cases.get(sid, [])
        # 找最近一次运行
        last_run = None
        for r in _runs:
            if r["suite_id"] == sid:
                last_run = r
                break
        result.append({
            **suite,
            "case_count": len(cases),
            "last_run": last_run,
        })
    return {"items": result}


@router.post("/suites", status_code=201)
async def create_suite(body: CreateSuiteBody):
    """创建评测集"""
    suite_id = f"suite_{uuid.uuid4().hex[:8]}"
    now = int(time.time() * 1000)
    suite = {
        "id": suite_id,
        "name": body.name,
        "description": body.description,
        "created_at": now,
        "updated_at": now,
    }
    _suites[suite_id] = suite
    _cases[suite_id] = []
    return suite


@router.get("/suites/{suite_id}/cases")
async def list_suite_cases(suite_id: str):
    """评测集下的用例"""
    if suite_id not in _suites:
        raise HTTPException(status_code=404, detail=f"评测集 {suite_id} 不存在")
    cases = _cases.get(suite_id, [])
    return {"items": cases, "total": len(cases)}


@router.post("/suites/{suite_id}/cases", status_code=201)
async def create_case(suite_id: str, body: CreateCaseBody):
    """添加用例"""
    if suite_id not in _suites:
        raise HTTPException(status_code=404, detail=f"评测集 {suite_id} 不存在")
    case_id = f"case_{uuid.uuid4().hex[:8]}"
    case = {
        "id": case_id,
        "suite_id": suite_id,
        "name": body.name,
        "input": body.input,
        "expected_behavior": body.expected_behavior,
        "assertions": body.assertions,
        "mock_tools": body.mock_tools,
        "tags": body.tags,
    }
    _cases[suite_id].append(case)
    _suites[suite_id]["updated_at"] = int(time.time() * 1000)
    return case


@router.delete("/suites/{suite_id}/cases/{case_id}")
async def delete_case(suite_id: str, case_id: str):
    """删除用例"""
    if suite_id not in _suites:
        raise HTTPException(status_code=404, detail=f"评测集 {suite_id} 不存在")
    cases = _cases.get(suite_id, [])
    _cases[suite_id] = [c for c in cases if c["id"] != case_id]
    return {"message": f"用例 {case_id} 已删除"}


# ═══════════════════════════════════════════════════════════
# 执行评测
# ═══════════════════════════════════════════════════════════

def _generate_mock_case_result(case: dict, is_failed: bool) -> dict:
    """为单个用例生成模拟的链路回放结果"""
    import random

    case_id = case["id"]
    latency_base = random.randint(1800, 2500)

    # 基础链路 Span
    spans = [
        {"id": f"span_1", "type": "content_review", "status": "passed",
         "start_ms": 0, "duration_ms": 2, "metadata": {"passed": True}},
        {"id": f"span_2", "type": "memory_retrieve", "status": "passed",
         "start_ms": 2, "duration_ms": random.randint(30, 50),
         "metadata": {"hits": random.randint(0, 3), "dimensions": ["user_profile"]}},
    ]

    current_ms = spans[-1]["start_ms"] + spans[-1]["duration_ms"]

    # LLM call 1 → tool_call
    llm1_dur = random.randint(700, 900)
    spans.append({
        "id": "span_3", "type": "llm_call", "round": 1, "status": "passed",
        "start_ms": current_ms, "duration_ms": llm1_dur,
        "metadata": {"model": "deepseek-v4-flash", "tokens_in": 320, "tokens_out": 45,
                     "decision": "tool_call", "tool_name": "query_data"},
        "expandable": {
            "input_messages": [
                {"role": "system", "content": "你是CRM助手，帮助用户处理业务问题。"},
                {"role": "user", "content": case.get("input", "")},
            ],
            "output_raw": "tool_call: query_data({...})",
        },
    })
    current_ms += llm1_dur

    # Tool call: query_data
    mock_tools = case.get("mock_tools", {})
    query_response = mock_tools.get("query_data", {"status": "ok"})
    spans.append({
        "id": "span_4", "type": "tool_call", "tool_name": "query_data", "status": "passed",
        "start_ms": current_ms, "duration_ms": 2,
        "metadata": {"is_mocked": True, "args": {"entity_api_key": "order"},
                     "response": query_response},
    })
    current_ms += 2

    if is_failed:
        # 失败场景：LLM call 2 做了错误决策
        llm2_dur = random.randint(550, 700)
        spans.append({
            "id": "span_5", "type": "llm_call", "round": 2, "status": "failed",
            "start_ms": current_ms, "duration_ms": llm2_dur,
            "failure_reason": "Agent 未根据返回数据做出正确判断",
            "metadata": {"model": "deepseek-v4-flash", "tokens_in": 580, "tokens_out": 30,
                         "decision": "tool_call", "tool_name": "cancel_order",
                         "expected_decision": "final_response"},
            "expandable": {
                "input_messages": [
                    {"role": "system", "content": "你是CRM助手，帮助用户处理业务问题。规则：已发货订单不可取消。"},
                    {"role": "user", "content": case.get("input", "")},
                    {"role": "tool", "content": json.dumps(query_response, ensure_ascii=False)},
                ],
                "output_raw": "tool_call: cancel_order({...})",
            },
        })
        current_ms += llm2_dur

        # Tool call: cancel_order (不应被调用)
        cancel_response = mock_tools.get("cancel_order", {"success": False, "reason": "不应执行"})
        spans.append({
            "id": "span_6", "type": "tool_call", "tool_name": "cancel_order", "status": "warning",
            "start_ms": current_ms, "duration_ms": 1,
            "metadata": {"is_mocked": True, "args": {}, "response": cancel_response},
        })
        current_ms += 1

        # LLM call 3: 错误回复
        llm3_dur = random.randint(450, 600)
        spans.append({
            "id": "span_7", "type": "llm_call", "round": 3, "status": "failed",
            "start_ms": current_ms, "duration_ms": llm3_dur,
            "failure_reason": "回复内容与工具返回结果矛盾",
            "metadata": {"model": "deepseek-v4-flash", "tokens_in": 680, "tokens_out": 25,
                         "decision": "final_response"},
            "expandable": {
                "input_messages": [
                    {"role": "system", "content": "你是CRM助手..."},
                    {"role": "user", "content": case.get("input", "")},
                    {"role": "tool", "content": json.dumps(cancel_response, ensure_ascii=False)},
                ],
                "output_raw": "好的，已为您处理。",
            },
        })
        current_ms += llm3_dur

        final_response = "好的，已为您处理。"
        assertions = [
            {"type": "tool_call_check", "passed": False, "detail": "cancel_order 不应被调用"},
            {"type": "contains_any", "passed": False, "detail": "回复应包含拒绝原因"},
            {"type": "tool_call_check", "passed": True, "detail": "query_data 被调用 ✓"},
        ]
        failure_attribution = {
            "type": "agent_reasoning_error",
            "node": "llm_call_2",
            "reason": "Agent 未根据工具返回数据做出正确决策",
            "suggestion": "检查 prompt 中是否有相关业务规则说明",
        }
    else:
        # 成功场景：LLM call 2 → final_response
        llm2_dur = random.randint(500, 700)
        spans.append({
            "id": "span_5", "type": "llm_call", "round": 2, "status": "passed",
            "start_ms": current_ms, "duration_ms": llm2_dur,
            "metadata": {"model": "deepseek-v4-flash", "tokens_in": 480, "tokens_out": 60,
                         "decision": "final_response"},
            "expandable": {
                "input_messages": [
                    {"role": "system", "content": "你是CRM助手..."},
                    {"role": "user", "content": case.get("input", "")},
                    {"role": "tool", "content": json.dumps(query_response, ensure_ascii=False)},
                ],
                "output_raw": "已为您处理，结果如下...",
            },
        })
        current_ms += llm2_dur

        final_response = "已为您处理完成。"
        assertions = [
            {"type": "tool_call_check", "passed": True, "detail": "query_data 被调用 ✓"},
            {"type": "contains_any", "passed": True, "detail": "回复符合预期"},
        ]
        failure_attribution = None

    result = {
        "case_id": case_id,
        "case_name": case.get("name", case_id),
        "status": "failed" if is_failed else "passed",
        "input": case.get("input", ""),
        "final_response": final_response,
        "latency_ms": current_ms,
        "token_usage": {"input": random.randint(800, 1600), "output": random.randint(50, 120),
                        "total": random.randint(900, 1700)},
        "chain": spans,
        "assertions": assertions,
    }
    if failure_attribution:
        result["failure_attribution"] = failure_attribution

    return result


def _build_run_detail(run_info: dict, target_cases: list[dict], failed_ids: set) -> dict:
    """为一次运行构建完整的详情数据（含所有用例的链路回放）"""
    cases_results = []
    for case in target_cases:
        is_failed = case["id"] in failed_ids
        cases_results.append(_generate_mock_case_result(case, is_failed))
    return {**run_info, "cases": cases_results}


@router.post("/run")
async def run_eval(body: RunEvalBody):
    """执行评测 — 同步模式，返回完整报告

    MVP 阶段：使用内存 demo 数据模拟执行结果。
    后续接入真实 chain_runner 引擎。
    """
    # 收集要执行的用例
    target_cases = []
    if body.suite_ids:
        for sid in body.suite_ids:
            target_cases.extend(_cases.get(sid, []))
    elif body.case_ids:
        for sid, cases in _cases.items():
            for c in cases:
                if c["id"] in body.case_ids:
                    target_cases.append(c)
    else:
        # 全部
        for cases in _cases.values():
            target_cases.extend(cases)

    if not target_cases:
        raise HTTPException(status_code=400, detail="无可执行的用例")

    # 模拟执行（MVP — 返回预设结果）
    run_id = f"run_{uuid.uuid4().hex[:6]}"
    now = int(time.time() * 1000)

    # 简单模拟：根据用例 ID 确定通过/失败
    failed_ids = {"cancel_shipped_002"}
    total = len(target_cases)
    passed = sum(1 for c in target_cases if c["id"] not in failed_ids)
    failed = total - passed

    run_info = {
        "run_id": run_id,
        "suite_id": body.suite_ids[0] if body.suite_ids else "all",
        "suite_name": _suites[body.suite_ids[0]]["name"] if body.suite_ids and body.suite_ids[0] in _suites else "全量评测",
        "total": total,
        "passed": passed,
        "failed": failed,
        "pass_rate": passed / max(total, 1),
        "duration_ms": total * 2100,
        "token_total": total * 1600,
        "created_at": now,
        "status": "completed",
    }
    _runs.insert(0, run_info)

    # 构建详情数据（链路回放）
    _run_details[run_id] = _build_run_detail(run_info, target_cases, failed_ids)

    return run_info


@router.post("/run-stream")
async def run_eval_stream(body: RunEvalBody):
    """SSE 流式执行 — 实时推送每个用例进度

    事件类型：
    - start: {total, suite_name}
    - case_start: {index, case_id, case_name}
    - span: {case_id, span} — 链路中的每个节点
    - case_complete: {index, case_id, status, latency_ms}
    - complete: {run_id, total, passed, failed, pass_rate}
    """
    # 收集用例
    target_cases = []
    suite_name = "评测运行"
    if body.suite_ids:
        for sid in body.suite_ids:
            target_cases.extend(_cases.get(sid, []))
        if body.suite_ids[0] in _suites:
            suite_name = _suites[body.suite_ids[0]]["name"]
    else:
        for cases in _cases.values():
            target_cases.extend(cases)

    if not target_cases:
        raise HTTPException(status_code=400, detail="无可执行的用例")

    total = len(target_cases)
    run_id = f"run_{uuid.uuid4().hex[:6]}"
    failed_ids = {"cancel_shipped_002"}

    async def event_generator():
        # start 事件
        yield f"data: {json.dumps({'event': 'start', 'run_id': run_id, 'total': total}, ensure_ascii=False)}\n\n"

        passed_count = 0
        failed_count = 0
        cases_results = []

        for idx, case in enumerate(target_cases):
            # case_start
            yield f"data: {json.dumps({'event': 'case_start', 'index': idx + 1, 'case_id': case['id'], 'case_name': case['name']}, ensure_ascii=False)}\n\n"

            # 模拟执行延迟
            await asyncio.sleep(0.3)

            is_failed = case["id"] in failed_ids

            # 模拟 span 推送
            spans = [
                {"type": "content_review", "status": "passed", "duration_ms": 2},
                {"type": "memory_retrieve", "status": "passed", "duration_ms": 35},
                {"type": "llm_call", "status": "passed" if not is_failed else "passed", "duration_ms": 820},
                {"type": "tool_call", "status": "passed", "duration_ms": 2},
            ]
            if is_failed:
                spans.append({"type": "llm_call", "status": "failed", "duration_ms": 620})
            for span in spans:
                yield f"data: {json.dumps({'event': 'span', 'case_id': case['id'], 'span': span}, ensure_ascii=False)}\n\n"
                await asyncio.sleep(0.05)

            status = "failed" if is_failed else "passed"
            if status == "passed":
                passed_count += 1
            else:
                failed_count += 1

            latency_ms = 2070 + (idx * 100)

            # 生成完整的用例结果（用于 _run_details）
            case_result = _generate_mock_case_result(case, is_failed)
            cases_results.append(case_result)

            # case_complete
            yield f"data: {json.dumps({'event': 'case_complete', 'index': idx + 1, 'total': total, 'case_id': case['id'], 'case_name': case['name'], 'status': status, 'latency_ms': latency_ms, 'running_passed': passed_count, 'running_failed': failed_count}, ensure_ascii=False)}\n\n"

        # complete
        now = int(time.time() * 1000)
        run_info = {
            "run_id": run_id,
            "suite_id": body.suite_ids[0] if body.suite_ids else "all",
            "suite_name": suite_name,
            "total": total,
            "passed": passed_count,
            "failed": failed_count,
            "pass_rate": passed_count / max(total, 1),
            "duration_ms": total * 2100,
            "token_total": total * 1600,
            "created_at": now,
            "status": "completed",
        }
        _runs.insert(0, run_info)

        # 保存详情数据（链路回放）
        _run_details[run_id] = {**run_info, "cases": cases_results}

        yield f"data: {json.dumps({'event': 'complete', **run_info}, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ═══════════════════════════════════════════════════════════
# 运行历史
# ═══════════════════════════════════════════════════════════

@router.get("/runs")
async def list_runs(limit: int = 20):
    """历史运行列表"""
    return {"items": _runs[:limit], "total": len(_runs)}


@router.get("/runs/{run_id}")
async def get_run(run_id: str):
    """运行详情"""
    detail = _run_details.get(run_id)
    if detail:
        return detail

    # 查找基本信息
    for r in _runs:
        if r["run_id"] == run_id:
            return {**r, "cases": []}

    raise HTTPException(status_code=404, detail=f"运行 {run_id} 不存在")


@router.get("/runs/{run_id}/cases/{case_id}")
async def get_run_case(run_id: str, case_id: str):
    """单个用例的链路回放数据"""
    detail = _run_details.get(run_id)
    if not detail:
        raise HTTPException(status_code=404, detail=f"运行 {run_id} 不存在")

    cases = detail.get("cases", [])
    for c in cases:
        if c["case_id"] == case_id:
            return c

    raise HTTPException(status_code=404, detail=f"用例 {case_id} 不存在于运行 {run_id} 中")


# ═══════════════════════════════════════════════════════════
# 对比报告
# ═══════════════════════════════════════════════════════════

@router.get("/reports/compare")
async def compare_runs(
    run_a: str = Query(..., description="运行 A 的 ID"),
    run_b: str = Query(..., description="运行 B 的 ID"),
):
    """对比两次运行的 diff"""
    detail_a = _run_details.get(run_a)
    detail_b = _run_details.get(run_b)

    if not detail_a or not detail_b:
        raise HTTPException(status_code=404, detail="指定的运行记录不存在")

    cases_a = {c["case_id"]: c for c in detail_a.get("cases", [])}
    cases_b = {c["case_id"]: c for c in detail_b.get("cases", [])}

    all_case_ids = set(cases_a.keys()) | set(cases_b.keys())
    diffs = []
    for cid in sorted(all_case_ids):
        a = cases_a.get(cid)
        b = cases_b.get(cid)
        if a and b:
            if a["status"] != b["status"]:
                diffs.append({
                    "case_id": cid,
                    "change": "status_change",
                    "from": a["status"],
                    "to": b["status"],
                })
        elif a and not b:
            diffs.append({"case_id": cid, "change": "removed"})
        elif b and not a:
            diffs.append({"case_id": cid, "change": "added"})

    return {
        "run_a": run_a,
        "run_b": run_b,
        "diffs": diffs,
        "summary": {
            "total_cases": len(all_case_ids),
            "changed": len(diffs),
            "pass_rate_a": detail_a.get("pass_rate", 0),
            "pass_rate_b": detail_b.get("pass_rate", 0),
        },
    }
