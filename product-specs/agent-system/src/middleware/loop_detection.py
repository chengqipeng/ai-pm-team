"""循环检测中间件 — 防止 Agent 陷入重复工具调用的死循环

## 问题背景

LLM 在 ReAct 循环中可能陷入"工具调用死循环"：反复用相同参数调用同一个工具，
期望得到不同结果，但实际上每次返回都一样。这会导致：
- Token 无限消耗（每轮迭代都消耗 input + output tokens）
- 用户等待超时（循环可能持续数十轮）
- 最终触发 LangGraph 的 recursion_limit 硬限制，返回不友好的错误

## 典型触发场景

### 场景 1：查询条件错误导致空结果循环
  用户: "查一下张三在北京的商机"
  Iter 1: query_data(entity="opportunity", filters={owner:"张三", city:"北京"}) → 0 条
  Iter 2: query_data(entity="opportunity", filters={owner:"张三", city:"北京"}) → 0 条  ← 重复
  Iter 3: query_data(entity="opportunity", filters={owner:"张三", city:"北京"}) → 0 条  ← 重复
  ...LLM 不断重试相同查询，期望数据"出现"

### 场景 2：工具返回错误但 LLM 不换策略
  用户: "帮我更新客户信息"
  Iter 1: modify_data(entity="account", data={name:"新名称"}) → Error: record_id required
  Iter 2: modify_data(entity="account", data={name:"新名称"}) → Error: record_id required  ← 重复
  Iter 3: modify_data(entity="account", data={name:"新名称"}) → Error: record_id required  ← 重复
  ...LLM 不理解错误原因，反复用相同参数重试

### 场景 3：分析任务中的无限细化循环
  用户: "分析商机 Pipeline"
  Iter 1: analyze_data(entity="opportunity", metrics=[{field:"amount", function:"sum"}], group_by="stage")
  Iter 2: analyze_data(entity="opportunity", metrics=[{field:"amount", function:"sum"}], group_by="stage")  ← 重复
  ...LLM 对结果不满意，但不知道如何改变查询

### 场景 4：多工具组合循环
  Iter 1: query_schema("opportunity") → 字段列表
  Iter 2: query_data(entity="opportunity", filters={}) → 数据
  Iter 3: query_schema("opportunity") → 字段列表  ← 回到 Iter 1
  Iter 4: query_data(entity="opportunity", filters={}) → 数据  ← 回到 Iter 2
  ...两个工具交替调用形成循环

## 检测算法

### 核心思路：滑动窗口 + 调用指纹哈希

1. 每次 LLM 返回 tool_calls 时，将 tool_calls 序列化为 JSON 并计算 MD5 哈希
   - 排序 tool_calls（按 name + args），确保顺序无关
   - 哈希只取前 12 位（碰撞概率极低）

2. 维护每个 thread_id 的调用历史（滑动窗口，默认 20 条）

3. 统计当前哈希在窗口内出现的次数：
   - count >= warn_threshold (3)：注入警告消息，提醒 LLM 停止重复
   - count >= hard_limit (5)：强制剥离 tool_calls，迫使 LLM 直接回复

### 两级响应机制

第一级 — 软警告（warn_threshold=3）：
  注入 HumanMessage: "[循环检测] 你正在重复相同的工具调用。请停止调用工具，直接给出最终答案。"
  效果：大多数 LLM 看到这条消息后会停止循环，给出基于已有数据的回答。
  每个哈希只警告一次（避免警告本身也形成循环）。

第二级 — 强制停止（hard_limit=5）：
  直接修改 AIMessage，清空 tool_calls，追加内容:
  "[强制停止] 重复工具调用超过安全限制。请直接给出最终答案。"
  效果：LLM 被迫在下一轮给出最终回复（因为没有 tool_calls 要执行）。

### 为什么不用简单的"连续 N 次相同"检测？

因为场景 4（多工具交替循环）中，连续两次调用不同，但整体形成循环。
滑动窗口 + 哈希计数能检测到这种非连续的重复模式。

## 内存管理

- 每个 thread_id 维护独立的调用历史
- 使用 OrderedDict 做 LRU 淘汰，最多保留 100 个 thread 的历史
- 线程安全（threading.Lock）

## 在中间件管道中的位置

```
after_model 执行顺序：
  TracingMiddleware.after_model      → 记录 llm_call span
  AgentLoggingMiddleware.after_model → 打印工具调用日志
  SubagentLimitMiddleware.after_model → 子 Agent 并发限制
  LoopDetectionMiddleware.after_model → ★ 循环检测（本中间件）
  OutputValidationMiddleware.after_model → 输出校验
```

排在 SubagentLimitMiddleware 之后：先限制子 Agent 数量，再检测循环。
排在 OutputValidationMiddleware 之前：循环检测可能修改消息，需要在输出校验前完成。

## 配置参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| warn_threshold | 3 | 软警告阈值（同一哈希出现 N 次时注入警告） |
| hard_limit | 5 | 强制停止阈值（同一哈希出现 N 次时剥离 tool_calls） |
| window_size | 20 | 滑动窗口大小（保留最近 N 次调用的哈希） |
"""

import hashlib
import json
import logging
import threading
from collections import OrderedDict, defaultdict
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage
from langchain.agents.middleware.types import AgentMiddleware, AgentState
from langgraph.config import get_config
from langgraph.runtime import Runtime

logger = logging.getLogger(__name__)


class LoopDetectionMiddleware(AgentMiddleware):
    """检测重复工具调用，两级响应：软警告 → 强制停止

    算法：滑动窗口内统计 tool_calls 的 MD5 哈希出现次数。
    - count >= warn_threshold：注入警告 HumanMessage（每个哈希只警告一次）
    - count >= hard_limit：剥离 tool_calls，强制 LLM 直接回复
    """

    def __init__(self, warn_threshold: int = 3, hard_limit: int = 5, window_size: int = 20):
        super().__init__()
        self.warn_threshold = warn_threshold
        self.hard_limit = hard_limit
        self.window_size = window_size
        self._lock = threading.Lock()
        # LRU 缓存：thread_id → 最近 N 次调用的哈希列表
        self._history: OrderedDict[str, list[str]] = OrderedDict()
        # 已警告的哈希集合：thread_id → {hash1, hash2, ...}（避免重复警告）
        self._warned: dict[str, set[str]] = defaultdict(set)

    def after_model(self, state: AgentState, runtime: Runtime) -> dict[str, Any] | None:
        """在 LLM 返回后检查 tool_calls 是否重复"""
        messages = state.get("messages", [])
        if not messages:
            return None

        last_msg = messages[-1]
        if not isinstance(last_msg, AIMessage):
            return None

        tool_calls = getattr(last_msg, "tool_calls", None)
        if not tool_calls:
            # 没有 tool_calls = LLM 给出了最终回复，不需要检测
            return None

        try:
            configurable = get_config().get("configurable", {})
            thread_id = configurable.get("thread_id", "default")
        except Exception:
            thread_id = "default"

        # 计算 tool_calls 的指纹哈希
        # 排序确保 [query_data, analyze_data] 和 [analyze_data, query_data] 产生相同哈希
        normalized = sorted(
            [{"name": tc.get("name", ""), "args": tc.get("args", {})} for tc in tool_calls],
            key=lambda tc: (tc["name"], json.dumps(tc["args"], sort_keys=True, default=str)),
        )
        call_hash = hashlib.md5(
            json.dumps(normalized, sort_keys=True, default=str).encode()
        ).hexdigest()[:12]

        with self._lock:
            # 初始化或更新 LRU
            if thread_id not in self._history:
                self._history[thread_id] = []
                # LRU 淘汰：超过 100 个 thread 时移除最久未使用的
                while len(self._history) > 100:
                    evicted, _ = self._history.popitem(last=False)
                    self._warned.pop(evicted, None)
            else:
                self._history.move_to_end(thread_id)

            # 追加到滑动窗口
            history = self._history[thread_id]
            history.append(call_hash)
            if len(history) > self.window_size:
                history[:] = history[-self.window_size:]

            # 统计当前哈希在窗口内的出现次数
            count = history.count(call_hash)

            # ── 第二级：强制停止 ──
            # 剥离 tool_calls，追加强制停止提示，LLM 下一轮必须直接回复
            if count >= self.hard_limit:
                tool_names = [tc.get("name", "?") for tc in tool_calls]
                logger.error(
                    "Loop hard limit reached: thread=%s, count=%d, tools=%s, hash=%s",
                    thread_id, count, tool_names, call_hash,
                )
                stripped = last_msg.model_copy(update={
                    "tool_calls": [],
                    "content": (last_msg.content or "")
                        + "\n\n[强制停止] 重复工具调用超过安全限制（相同调用已出现 "
                        + str(count) + " 次）。请基于已有信息直接给出最终答案。",
                })
                return {"messages": [stripped]}

            # ── 第一级：软警告 ──
            # 注入警告消息，提醒 LLM 换策略。每个哈希只警告一次。
            if count >= self.warn_threshold and call_hash not in self._warned[thread_id]:
                self._warned[thread_id].add(call_hash)
                tool_names = [tc.get("name", "?") for tc in tool_calls]
                logger.warning(
                    "Repetitive tool calls detected: thread=%s, count=%d, tools=%s, hash=%s",
                    thread_id, count, tool_names, call_hash,
                )
                return {"messages": [HumanMessage(
                    content=(
                        "[循环检测] 你正在重复相同的工具调用（已出现 " + str(count) + " 次）。"
                        "请停止重复调用，基于已有数据直接给出最终答案，或换一种查询方式。"
                    )
                )]}

        return None
