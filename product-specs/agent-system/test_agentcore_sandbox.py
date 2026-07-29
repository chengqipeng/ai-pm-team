#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = ["bedrock-agentcore", "boto3"]
# ///
"""
AWS AgentCore 沙箱（Code Interpreter）场景测试 —— 对标腾讯 AGS 版 test_sandbox.py

对齐腾讯三要素（工作目录（对标/sandbox/.skills）· 目录隔离 · 文件同步 S3）：
主流程：开会话 -> 建工作目录 /sandbox/.skills -> 执行分析脚本产出报告到工作目录
        -> 同会话状态保持 -> 工作目录整体同步 s3://桶/sessions/{session_id}/ -> 关闭
隔离测试：沙箱A在 /sandbox/.skills 建 a/ 目录、沙箱B建 b/ 目录，验证互相看不到（默认和主流程一起跑）
交互shell：python3 test_agentcore_sandbox.py shell [存活秒数，默认900]
          命令逐条在沙箱内执行（`py <代码>` 跑 python，exit 退出销毁）

运行：uv run test_agentcore_sandbox.py [shell]   # 无参数=主流程+隔离全跑；PEP723 自动装依赖
     （或 pip install bedrock-agentcore boto3 后直接 python3 跑）
凭证：标准 AWS 环境变量（各自的 AKSK）：
       export AWS_ACCESS_KEY_ID=xxx
       export AWS_SECRET_ACCESS_KEY=xxx
     区域固定 ap-southeast-1（p10）
S3  ：SANDBOX_SYNC_BUCKET（默认 agentcore-sandbox-p10 —— 本次评估创建的测试专用桶，
     带自动清理策略，非线上业务桶）；不可达时 sync 步自动跳过

与腾讯版差异：
- 工作目录隔离是 microVM 级自带（整个文件系统每会话独立），无需 subPath 挂载参数
- 文件同步 S3 = 脚本拉取工作目录后按 session 前缀上传（生产=Runtime 里 sync 工具做同一件事）
- AgentCore CI 会话没有 pause/resume，改为验证同会话内文件跨调用保持
- 注意：CI 的工作目录不持久（会话销毁即没）；生产方案里持久性由 Runtime 的
  Session Storage 提供（同 session 回来数据自动恢复）——那部分需部署后验证，已于 2026-07-02 真机验证过
"""

import json
import os
import sys
import time

REGION = "ap-southeast-1"

if not (os.environ.get("AWS_ACCESS_KEY_ID") or os.environ.get("AWS_PROFILE")):
    sys.exit("缺少 AWS 凭证：请先 export AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY（你自己的 AKSK）")
CI_ID = "aws.codeinterpreter.v1"  # 系统内置沙箱，无需自建
WORKDIR = "/tmp/sandbox/.skills"  # 对齐腾讯工作目录语义；内置沙箱根目录不可写故挂 /tmp 下
# 注：生产 Runtime 的 Session Storage 挂载路径限定 /mnt/ 前缀（如 /mnt/skills），
#     腾讯能用 /sandbox/.skills 是自定义镜像里预建的目录，两边都是"约定路径"而已
SYNC_BUCKET = os.environ.get("SANDBOX_SYNC_BUCKET", "agentcore-sandbox-p10")  # 测试专用桶（评估期建，自动清理），非线上桶

from bedrock_agentcore.tools.code_interpreter_client import CodeInterpreter  # noqa: E402


def invoke_text(ci: CodeInterpreter, tool: str, params: dict) -> str:
    """调用沙箱工具并拼接文本输出。"""
    resp = ci.invoke(tool, params)
    parts = []
    for ev in resp.get("stream", []):
        for c in ev.get("result", {}).get("content", []):
            if c.get("type") == "text":
                parts.append(c["text"])
    return "\n".join(parts)


def main():
    # 1. 开沙箱会话
    print("[1] 创建沙箱会话...")
    ci = CodeInterpreter(region=REGION)
    session_id = ci.start(name="acdemo_scenario", session_timeout_seconds=900)
    print(f"    会话ID: {session_id}")
    invoke_text(ci, "executeCommand", {"command": f"mkdir -p {WORKDIR}"})
    print(f"    工作目录已建: {WORKDIR}")

    # 2. 写入一段数据分析脚本（写进沙箱文件系统）
    print("[2] 写入分析脚本...")
    script = '''
import json
import platform
import sys
from datetime import datetime

data = [
    {"name": "服务A", "qps": 1200, "latency_ms": 45, "error_rate": 0.02},
    {"name": "服务B", "qps": 800, "latency_ms": 120, "error_rate": 0.05},
    {"name": "服务C", "qps": 3500, "latency_ms": 12, "error_rate": 0.001},
    {"name": "服务D", "qps": 600, "latency_ms": 200, "error_rate": 0.08},
    {"name": "服务E", "qps": 2200, "latency_ms": 30, "error_rate": 0.01},
]

total_qps = sum(d["qps"] for d in data)
avg_latency = sum(d["latency_ms"] for d in data) / len(data)
unhealthy = [d for d in data if d["error_rate"] > 0.03]

report = {
    "generated_at": datetime.now().isoformat(),
    "environment": {"python": sys.version, "platform": platform.platform()},
    "summary": {
        "total_services": len(data),
        "total_qps": total_qps,
        "avg_latency_ms": round(avg_latency, 2),
        "unhealthy_count": len(unhealthy),
    },
    "unhealthy_services": unhealthy,
    "recommendation": "服务D错误率过高(8%),建议排查" if any(d["name"] == "服务D" for d in unhealthy) else "所有服务正常",
}

with open("/tmp/sandbox/.skills/report.json", "w") as f:
    json.dump(report, f, ensure_ascii=False, indent=2)

print(f"报告已生成: /tmp/sandbox/.skills/report.json")
print(f"共分析 {len(data)} 个服务, 发现 {len(unhealthy)} 个异常")
'''
    out = invoke_text(ci, "executeCode", {
        "language": "python",
        "code": f"open('/tmp/analyze.py','w').write({script!r}); print('written')",
    })
    print(f"    {out.strip()}")

    # 3. 执行脚本
    print("[3] 执行分析脚本...")
    out = invoke_text(ci, "executeCommand", {"command": "python3 /tmp/analyze.py"})
    print(f"    输出: {out.strip()}")

    # 4. 读取生成的报告
    print("[4] 读取报告...")
    report_content = invoke_text(ci, "executeCommand", {"command": f"cat {WORKDIR}/report.json"})
    print(f"    报告内容:\n{report_content}")

    # 5. 同会话二次调用，验证文件还在（AgentCore CI 无 pause/resume，等几秒再查）
    print("[5] 等待后同会话再次读取，验证状态保持...")
    time.sleep(3)
    data = json.loads(invoke_text(ci, "executeCommand", {"command": f"cat {WORKDIR}/report.json"}))
    print(f"    报告生成时间: {data['generated_at']}")
    print(f"    异常服务数: {data['summary']['unhealthy_count']}")
    print(f"    建议: {data['recommendation']}")

    # 6. 工作目录整体同步 S3：sessions/{session_id}/ 前缀（=路线2 sync 工具的语义）
    print(f"[6] 同步工作目录 {WORKDIR} -> s3://{SYNC_BUCKET}/sessions/{session_id}/ ...")
    try:
        import boto3
        s3 = boto3.client("s3", region_name=REGION)
        files = [f for f in invoke_text(
            ci, "executeCommand",
            {"command": f"find {WORKDIR} -type f"}).split("\n") if f.strip()]
        for path in files:
            content = invoke_text(ci, "executeCommand", {"command": f"cat {path}"})
            rel = path[len(WORKDIR) + 1:]
            key = f"sessions/{session_id}/{rel}"
            s3.put_object(Bucket=SYNC_BUCKET, Key=key, Body=content.encode())
            print(f"    已上传: s3://{SYNC_BUCKET}/{key}")
        url = s3.generate_presigned_url(
            "get_object",
            Params={"Bucket": SYNC_BUCKET, "Key": f"sessions/{session_id}/report.json"},
            ExpiresIn=3600)
        print(f"    预签名URL(1h): {url[:100]}...")
    except Exception as e:  # 桶不在/无权限时跳过，不影响沙箱测试
        print(f"    跳过（{type(e).__name__}: {e}）")

    # 7. 关闭会话
    print("[7] 关闭沙箱会话...")
    ci.stop()
    print("    已关闭")

    print("\n[完成] 全部流程执行成功")


def test_isolation():
    """会话隔离测试：两个 CI 会话各写文件，验证互相看不到（microVM 级自带隔离）"""
    print("[测试] 创建两个沙箱会话...")
    ci_a = CodeInterpreter(region=REGION)
    ci_b = CodeInterpreter(region=REGION)
    sid_a = ci_a.start(name="acdemo_iso_a", session_timeout_seconds=300)
    sid_b = ci_b.start(name="acdemo_iso_b", session_timeout_seconds=300)
    print(f"    会话A: {sid_a}")
    print(f"    会话B: {sid_b}")

    print(f"\n[1] 沙箱A 在 {WORKDIR} 下建 a/ 目录并写文件 ...")
    invoke_text(ci_a, "executeCommand",
                {"command": f"mkdir -p {WORKDIR}/a && echo 'I am session A: {sid_a}' > {WORKDIR}/a/hello.txt"})
    print(f"[2] 沙箱B 在 {WORKDIR} 下建 b/ 目录并写文件 ...")
    invoke_text(ci_b, "executeCommand",
                {"command": f"mkdir -p {WORKDIR}/b && echo 'I am session B: {sid_b}' > {WORKDIR}/b/hello.txt"})

    print(f"\n[3] 沙箱A 列出 {WORKDIR} ...")
    ls_a = invoke_text(ci_a, "executeCommand", {"command": f"ls {WORKDIR}/"})
    print(f"    {ls_a.strip()}")
    print(f"[4] 沙箱B 列出 {WORKDIR} ...")
    ls_b = invoke_text(ci_b, "executeCommand", {"command": f"ls {WORKDIR}/"})
    print(f"    {ls_b.strip()}")

    print("[5] 沙箱A 尝试读 B 的 b/hello.txt ...")
    r = invoke_text(ci_a, "executeCommand", {"command": f"cat {WORKDIR}/b/hello.txt 2>&1; echo EXIT:$?"})
    print(f"    结果: {r.strip()}")
    print("[6] 沙箱B 尝试读 A 的 a/hello.txt ...")
    r = invoke_text(ci_b, "executeCommand", {"command": f"cat {WORKDIR}/a/hello.txt 2>&1; echo EXIT:$?"})
    print(f"    结果: {r.strip()}")

    print("\n" + "=" * 50)
    a_sees_b = "b" in ls_a.split()
    b_sees_a = "a" in ls_b.split()
    if not a_sees_b and not b_sees_a:
        print("✅ 隔离验证通过：A 的 a/ 目录和 B 的 b/ 目录互不可见")
    else:
        print("❌ 隔离验证失败：")
        if a_sees_b:
            print("   - 沙箱A 能看到 B 的 b/ 目录")
        if b_sees_a:
            print("   - 沙箱B 能看到 A 的 a/ 目录")

    print("\n[清理] 关闭会话...")
    ci_a.stop()
    ci_b.stop()
    print("    完成")


def shell():
    """交互式沙箱 shell：敲什么在沙箱里执行什么，体感等于"进去看"。"""
    ttl = int(sys.argv[2]) if len(sys.argv) > 2 else 900
    print(f"[*] 创建沙箱会话（TTL {ttl}s）...")
    ci = CodeInterpreter(region=REGION)
    sid = ci.start(name="interactive_shell", session_timeout_seconds=ttl)
    print(f"[*] 已进入沙箱 {sid}")
    print("[*] 直接敲 shell 命令；`py <代码>` 执行 python；exit 退出\n")
    try:
        while True:
            try:
                line = input("sandbox$ ").strip()
            except EOFError:
                break
            if not line:
                continue
            if line in ("exit", "quit"):
                break
            try:
                if line.startswith("py "):
                    out = invoke_text(ci, "executeCode",
                                      {"language": "python", "code": line[3:]})
                else:
                    out = invoke_text(ci, "executeCommand", {"command": line})
                print(out)
            except Exception as e:
                print(f"[!] {type(e).__name__}: {e}")
    finally:
        print("\n[*] 销毁沙箱会话...")
        ci.stop()
        print("[*] 已退出")


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    if mode == "shell":
        shell()
    else:
        print("========== 场景测试 ==========")
        main()
        print("\n========== 隔离验证 ==========")
        test_isolation()
