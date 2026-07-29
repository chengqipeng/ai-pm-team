"""调用 AG-UI chat 接口验证 csv-trend-analysis Skill 端到端执行

通过 HTTP 调用 /api/chat/agui 端点，模拟真实用户对话。
解析 SSE 事件流，提取工具调用和最终回复。
"""
import httpx
import json
import sys
import uuid
import time


API_BASE = "http://127.0.0.1:8001"
THREAD_ID = f"test-skill-script-{uuid.uuid4().hex[:8]}"
USER_MESSAGE = "帮我分析 /tmp/test_sales.csv 的数据趋势"


def call_chat_agui(message: str, thread_id: str):
    """调用 /api/chat/agui 并解析 SSE 事件流"""
    url = f"{API_BASE}/api/chat/agui"
    payload = {
        "threadId": thread_id,
        "message": message,
        "history": [],
    }

    print(f"\n{'─' * 60}")
    print(f"  用户: {message}")
    print(f"  thread: {thread_id}")
    print(f"{'─' * 60}\n")

    tool_calls = []
    text_parts = []
    events_count = 0

    with httpx.stream("POST", url, json=payload, timeout=180.0) as response:
        if response.status_code != 200:
            print(f"❌ HTTP {response.status_code}")
            print(response.text)
            return

        for line in response.iter_lines():
            if not line or not line.startswith("data: "):
                continue

            data_str = line[6:]  # 去掉 "data: " 前缀
            if data_str == "[DONE]":
                break

            try:
                event = json.loads(data_str)
            except json.JSONDecodeError:
                continue

            events_count += 1
            event_type = event.get("type", "")

            # 工具调用开始
            if event_type == "TOOL_CALL_START":
                tc = event.get("toolCall", {})
                tool_name = tc.get("name", "?")
                tool_calls.append({"name": tool_name, "args": ""})
                print(f"  🔧 工具调用: {tool_name}")

            # 工具调用参数
            elif event_type == "TOOL_CALL_ARGS":
                if tool_calls:
                    tool_calls[-1]["args"] += event.get("delta", "")

            # 工具调用结束
            elif event_type == "TOOL_CALL_END":
                if tool_calls:
                    tc = tool_calls[-1]
                    args_preview = tc["args"][:100] if tc["args"] else ""
                    print(f"       参数: {args_preview}...")

            # 文本消息
            elif event_type == "TEXT_MESSAGE_CONTENT":
                delta = event.get("delta", "")
                text_parts.append(delta)

            # 运行结束
            elif event_type == "RUN_FINISHED":
                break

    # 汇总
    full_text = "".join(text_parts)
    print(f"\n{'─' * 60}")
    print(f"  📊 执行统计:")
    print(f"     事件总数: {events_count}")
    print(f"     工具调用: {len(tool_calls)} 次")
    for i, tc in enumerate(tool_calls, 1):
        print(f"       #{i} {tc['name']}")
    print(f"     回复长度: {len(full_text)} 字符")
    print(f"{'─' * 60}")

    if full_text:
        # 只显示前 500 字符
        preview = full_text[:500]
        print(f"\n  📝 Agent 回复（前 500 字）:\n")
        for line in preview.split("\n"):
            print(f"     {line}")
        if len(full_text) > 500:
            print(f"\n     ... (共 {len(full_text)} 字符)")

    # 验证
    print(f"\n{'─' * 60}")
    print(f"  ✅ 验证:")

    # 检查是否调用了 terminal 执行脚本
    terminal_calls = [tc for tc in tool_calls if tc["name"] == "terminal"]
    has_script_call = any("analyze.py" in tc.get("args", "") for tc in terminal_calls)
    print(f"     调用了 terminal: {'✅' if terminal_calls else '❌'} ({len(terminal_calls)} 次)")
    print(f"     执行了 analyze.py: {'✅' if has_script_call else '❌'}")

    # 检查回复中是否包含趋势信息
    has_trend = any(kw in full_text for kw in ["上升", "下降", "趋势", "revenue", "📈"])
    print(f"     回复含趋势分析: {'✅' if has_trend else '❌'}")

    # 检查是否触发了循环（工具调用 > 10 次说明可能有问题）
    if len(tool_calls) > 10:
        print(f"     ⚠️  工具调用过多 ({len(tool_calls)} 次)，可能存在循环")
    else:
        print(f"     工具调用合理: ✅ ({len(tool_calls)} 次)")

    print(f"{'─' * 60}\n")
    return full_text


if __name__ == "__main__":
    print("=" * 60)
    print("  AG-UI Chat 接口 — Skill 脚本执行验证")
    print("=" * 60)

    start = time.time()
    result = call_chat_agui(USER_MESSAGE, THREAD_ID)
    elapsed = time.time() - start

    print(f"\n  总耗时: {elapsed:.1f}s")
    if result:
        print("  🎉 测试完成")
    else:
        print("  ❌ 测试失败")
