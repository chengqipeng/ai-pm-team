#!/usr/bin/env python3
"""
腾讯云 AgentSandbox 场景测试
流程：创建沙箱 -> 写入脚本 -> 执行脚本生成报告 -> 读取报告 -> 暂停 -> 恢复 -> 验证数据 -> 删除
"""

import os
import time

os.environ["E2B_DOMAIN"] = "ap-beijing.tencentags.com"
os.environ["E2B_API_KEY"] = "ark_dGTlMcosC-n-ZNhfKyW8aBJm3c0KNLXzjSkT7t_3WWc"

from e2b import Sandbox

TEMPLATE = "code-sandbox"


def main():
    # 1. 创建沙箱
    print("[1] 创建沙箱...")
    sandbox = Sandbox.create(template=TEMPLATE, timeout=28800)
    print(f"    沙箱ID: {sandbox.sandbox_id}")
    input("    按回车继续...")

    # 2. 写入一段数据分析脚本到沙箱
    print("[2] 写入分析脚本...")
    script = '''
import json
import platform
import sys
from datetime import datetime

# 模拟数据分析任务
data = [
    {"name": "服务A", "qps": 1200, "latency_ms": 45, "error_rate": 0.02},
    {"name": "服务B", "qps": 800, "latency_ms": 120, "error_rate": 0.05},
    {"name": "服务C", "qps": 3500, "latency_ms": 12, "error_rate": 0.001},
    {"name": "服务D", "qps": 600, "latency_ms": 200, "error_rate": 0.08},
    {"name": "服务E", "qps": 2200, "latency_ms": 30, "error_rate": 0.01},
]

# 分析
total_qps = sum(d["qps"] for d in data)
avg_latency = sum(d["latency_ms"] for d in data) / len(data)
unhealthy = [d for d in data if d["error_rate"] > 0.03]

report = {
    "generated_at": datetime.now().isoformat(),
    "environment": {
        "python": sys.version,
        "platform": platform.platform(),
    },
    "summary": {
        "total_services": len(data),
        "total_qps": total_qps,
        "avg_latency_ms": round(avg_latency, 2),
        "unhealthy_count": len(unhealthy),
    },
    "unhealthy_services": unhealthy,
    "recommendation": "服务D错误率过高(8%),建议排查" if any(d["name"] == "服务D" for d in unhealthy) else "所有服务正常",
}

with open("/tmp/report.json", "w") as f:
    json.dump(report, f, ensure_ascii=False, indent=2)

print(f"报告已生成: /tmp/report.json")
print(f"共分析 {len(data)} 个服务, 发现 {len(unhealthy)} 个异常")
'''
    sandbox.files.write("/tmp/analyze.py", script)

    # 3. 执行脚本
    print("[3] 执行分析脚本...")
    result = sandbox.commands.run("python3 /tmp/analyze.py")
    print(f"    输出: {result.stdout.strip()}")

    # 4. 读取生成的报告
    print("[4] 读取报告...")
    report_content = sandbox.files.read("/tmp/report.json")
    print(f"    报告内容:\n{report_content}")
    input("    按回车继续暂停沙箱...")

    # 5. 暂停沙箱
    print("[5] 暂停沙箱...")
    sandbox.pause()
    print("    已暂停")

    # 6. 等待后恢复
    time.sleep(3)
    print("[6] 恢复沙箱...")
    sandbox = Sandbox.connect(sandbox.sandbox_id)
    print("    已恢复")

    # 7. 验证暂停前的数据还在
    print("[7] 验证数据持久性...")
    content = sandbox.files.read("/tmp/report.json")
    import json
    data = json.loads(content)
    print(f"    报告生成时间: {data['generated_at']}")
    print(f"    异常服务数: {data['summary']['unhealthy_count']}")
    print(f"    建议: {data['recommendation']}")
    input("    按回车删除沙箱...")

    # 8. 删除沙箱
    print("[8] 删除沙箱...")
    sandbox.kill()
    print("    已删除")

    print("\n[完成] 全部流程执行成功")


def test_subpath_isolation():
    """测试 SubPath 隔离：模拟两个会话各自创建沙箱，验证互相看不到对方文件"""
    import json
    import uuid

    session_a = f"session-{uuid.uuid4().hex[:8]}"
    session_b = f"session-{uuid.uuid4().hex[:8]}"
    print(f"[测试] 会话A: {session_a}, 会话B: {session_b}")

    # 1. 创建沙箱A，SubPath 指向会话A的目录
    print("\n[1] 创建沙箱A (subPath=data/{session_a})...")
    sandbox_a = Sandbox.create(
        template=TEMPLATE,
        timeout=300,
        metadata={
            "x-mounts": json.dumps([{
                "name": "cos-aitools",
                "subPath": f"data/{session_a}"
            }])
        }
    )
    print(f"    沙箱A ID: {sandbox_a.sandbox_id}")

    # 2. 创建沙箱B，SubPath 指向会话B的目录
    print(f"\n[2] 创建沙箱B (subPath=data/{session_b})...")
    sandbox_b = Sandbox.create(
        template=TEMPLATE,
        timeout=300,
        metadata={
            "x-mounts": json.dumps([{
                "name": "cos-aitools",
                "subPath": f"data/{session_b}"
            }])
        }
    )
    print(f"    沙箱B ID: {sandbox_b.sandbox_id}")

    # 3. 在沙箱A的 /sandbox 下写入文件
    print("\n[3] 沙箱A 写入文件 /sandbox/hello_a.txt...")
    sandbox_a.files.write("/sandbox/hello_a.txt", f"I am session A: {session_a}")

    # 4. 在沙箱B的 /sandbox 下写入文件
    print("[4] 沙箱B 写入文件 /sandbox/hello_b.txt...")
    sandbox_b.files.write("/sandbox/hello_b.txt", f"I am session B: {session_b}")

    # 5. 验证隔离：沙箱A列出 /sandbox 目录
    print("\n[5] 沙箱A 列出 /sandbox 目录...")
    result_a = sandbox_a.commands.run("ls -la /sandbox/")
    print(f"    {result_a.stdout}")

    # 6. 验证隔离：沙箱B列出 /sandbox 目录
    print("[6] 沙箱B 列出 /sandbox 目录...")
    result_b = sandbox_b.commands.run("ls -la /sandbox/")
    print(f"    {result_b.stdout}")

    # 7. 验证：沙箱A能否看到 hello_b.txt
    print("[7] 沙箱A 尝试读取 /sandbox/hello_b.txt...")
    result = sandbox_a.commands.run("cat /sandbox/hello_b.txt 2>&1; echo EXIT:$?")
    print(f"    结果: {result.stdout.strip()}")

    # 8. 验证：沙箱B能否看到 hello_a.txt
    print("[8] 沙箱B 尝试读取 /sandbox/hello_a.txt...")
    result = sandbox_b.commands.run("cat /sandbox/hello_a.txt 2>&1; echo EXIT:$?")
    print(f"    结果: {result.stdout.strip()}")

    # 判定
    print("\n" + "=" * 50)
    a_sees_b = "hello_b.txt" in sandbox_a.commands.run("ls /sandbox/").stdout
    b_sees_a = "hello_a.txt" in sandbox_b.commands.run("ls /sandbox/").stdout

    if not a_sees_b and not b_sees_a:
        print("✅ 隔离验证通过：A 和 B 互相看不到对方文件")
    else:
        print("❌ 隔离验证失败：")
        if a_sees_b:
            print("   - 沙箱A 能看到 B 的文件")
        if b_sees_a:
            print("   - 沙箱B 能看到 A 的文件")

    # 清理
    print("\n[清理] 删除沙箱...")
    sandbox_a.kill()
    sandbox_b.kill()
    print("    完成")


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "isolation":
        test_subpath_isolation()
    else:
        main()
