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
    sandbox = Sandbox.create(template=TEMPLATE, timeout=600)
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


if __name__ == "__main__":
    main()
