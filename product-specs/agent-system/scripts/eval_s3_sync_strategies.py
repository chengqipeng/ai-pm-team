#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = ["bedrock-agentcore", "boto3"]
# ///
"""
AWS 沙箱 S3 同步策略验证脚本

验证三种策略的可行性和性能：
  A. 收尾 sync（当前实现）
  B. write_file 双写（推荐验证）
  C. 定时增量 sync（重度方案）

运行：uv run scripts/eval_s3_sync_strategies.py
凭证：export AWS_ACCESS_KEY_ID=xxx && export AWS_SECRET_ACCESS_KEY=xxx
"""
import asyncio
import json
import os
import sys
import time
from dataclasses import dataclass

REGION = os.environ.get("AWS_SANDBOX_REGION", "ap-southeast-1")
SYNC_BUCKET = os.environ.get("AWS_SANDBOX_SYNC_BUCKET", "agentcore-sandbox-p10")
WORKDIR = "/tmp/sandbox/.skills"

if not (os.environ.get("AWS_ACCESS_KEY_ID") or os.environ.get("AWS_PROFILE")):
    sys.exit("缺少 AWS 凭证：export AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY")

from bedrock_agentcore.tools.code_interpreter_client import CodeInterpreter


def invoke_text(ci, tool, params):
    resp = ci.invoke(tool, params)
    parts = []
    for ev in resp.get("stream", []):
        for c in ev.get("result", {}).get("content", []):
            if c.get("type") == "text":
                parts.append(c["text"])
    return "\n".join(parts)


@dataclass
class ExperimentResult:
    name: str
    passed: bool
    detail: str
    metrics: dict = None


# ═══════════════════════════════════════════════════
# 实验 1：收尾 sync 可靠性（策略 A 基线）
# ═══════════════════════════════════════════════════

def experiment_1_baseline_sync():
    """验证正常 disconnect 路径下收尾 sync 能正确保存所有文件"""
    print("\n" + "=" * 60)
    print("实验 1：收尾 sync 可靠性（策略 A 基线）")
    print("=" * 60)

    import boto3
    s3 = boto3.client("s3", region_name=REGION)

    ci = CodeInterpreter(region=REGION)
    sid = ci.start(name="eval_exp1", session_timeout_seconds=600)
    print(f"  会话: {sid}")

    # 三种写入方式
    invoke_text(ci, "executeCommand", {"command": f"mkdir -p {WORKDIR}"})

    # 方式1: shell echo
    invoke_text(ci, "executeCommand",
                {"command": f"echo 'from shell' > {WORKDIR}/shell.txt"})

    # 方式2: python 脚本写入
    invoke_text(ci, "executeCode", {
        "language": "python",
        "code": f"open('{WORKDIR}/python.json', 'w').write(json.dumps({{'source': 'python'}}))\nimport json\nprint('written')"
    })

    # 方式3: 大文件
    invoke_text(ci, "executeCode", {
        "language": "python",
        "code": f"open('{WORKDIR}/large.csv', 'w').write('row\\n' * 5000)\nprint('written')"
    })

    # 收尾 sync
    print("  执行收尾 sync...")
    files_output = invoke_text(ci, "executeCommand",
                               {"command": f"find {WORKDIR} -type f"})
    files = [f.strip() for f in files_output.split("\n") if f.strip()]
    print(f"  工作目录文件数: {len(files)}")

    prefix = f"sessions/{sid}"
    synced = 0
    for fpath in files:
        content = invoke_text(ci, "executeCommand", {"command": f"cat {fpath}"})
        rel = fpath[len(WORKDIR) + 1:]
        key = f"{prefix}/{rel}"
        s3.put_object(Bucket=SYNC_BUCKET, Key=key, Body=content.encode())
        synced += 1

    ci.stop()
    print(f"  已同步 {synced} 个文件到 S3")

    # 验证
    results = {}
    for expected in ["shell.txt", "python.json", "large.csv"]:
        key = f"{prefix}/{expected}"
        try:
            resp = s3.get_object(Bucket=SYNC_BUCKET, Key=key)
            size = resp["ContentLength"]
            results[expected] = f"✅ 存在 ({size} bytes)"
        except Exception as e:
            results[expected] = f"❌ 缺失 ({e})"

    for f, status in results.items():
        print(f"  {f}: {status}")

    passed = all("✅" in v for v in results.values())
    return ExperimentResult(
        name="收尾 sync 可靠性",
        passed=passed,
        detail=str(results),
        metrics={"files_synced": synced},
    )


# ═══════════════════════════════════════════════════
# 实验 2：TTL 超时数据丢失确认
# ═══════════════════════════════════════════════════

def experiment_2_ttl_expiry():
    """确认 TTL 超时时未 sync 的数据确实丢失"""
    print("\n" + "=" * 60)
    print("实验 2：TTL 超时数据丢失（最短 TTL=300s，需等待 ~5min）")
    print("  [提示] 此实验耗时较长，可跳过（按 Ctrl+C）")
    print("=" * 60)

    ci = CodeInterpreter(region=REGION)
    sid = ci.start(name="eval_exp2_ttl", session_timeout_seconds=300)
    print(f"  会话: {sid} (TTL=300s)")

    invoke_text(ci, "executeCommand",
                {"command": f"mkdir -p {WORKDIR} && echo 'will be lost' > {WORKDIR}/ephemeral.txt"})
    content = invoke_text(ci, "executeCommand", {"command": f"cat {WORKDIR}/ephemeral.txt"})
    print(f"  写入内容: {content.strip()}")
    print(f"  故意不调 sync/stop，等待 TTL 超时...")

    # 等待超时（300s + 30s buffer）
    wait_seconds = 330
    for i in range(0, wait_seconds, 30):
        remaining = wait_seconds - i
        print(f"  等待中... {remaining}s remaining")
        time.sleep(min(30, remaining))

    # 尝试调用——应该失败
    try:
        invoke_text(ci, "executeCommand", {"command": "echo alive"})
        print("  ❌ 会话仍存活（不预期）")
        ci.stop()
        return ExperimentResult(name="TTL 超时验证", passed=False, detail="会话未超时")
    except Exception as e:
        print(f"  ✅ 会话已超时: {type(e).__name__}")
        return ExperimentResult(
            name="TTL 超时验证",
            passed=True,
            detail=f"确认：TTL 超时后数据丢失，会话不可用 ({e})",
            metrics={"ttl_seconds": 300},
        )


# ═══════════════════════════════════════════════════
# 实验 3：write_file 双写性能测试（策略 B）
# ═══════════════════════════════════════════════════

def experiment_3_dual_write_perf():
    """测量 write_file + 异步 S3 PUT 的延迟开销"""
    print("\n" + "=" * 60)
    print("实验 3：write_file 双写性能（策略 B）")
    print("=" * 60)

    import boto3
    s3 = boto3.client("s3", region_name=REGION)

    ci = CodeInterpreter(region=REGION)
    sid = ci.start(name="eval_exp3_perf", session_timeout_seconds=600)
    invoke_text(ci, "executeCommand", {"command": f"mkdir -p {WORKDIR}"})
    print(f"  会话: {sid}")

    content_1k = "x" * 1024
    content_10k = "y" * 10240

    # 对照组：纯沙箱写入
    print("  对照组：纯沙箱写入 (20次 x 1KB)...")
    times_baseline = []
    for i in range(20):
        t0 = time.time()
        invoke_text(ci, "executeCode", {
            "language": "python",
            "code": f"open('{WORKDIR}/baseline_{i}.txt', 'w').write('{'x' * 1024}')\nprint('ok')"
        })
        times_baseline.append(time.time() - t0)

    # 实验组：沙箱写入 + 同步 S3 PUT（模拟"最坏情况"同步双写）
    print("  实验组：沙箱写入 + 同步 S3 PUT (20次 x 1KB)...")
    times_dual = []
    for i in range(20):
        t0 = time.time()
        invoke_text(ci, "executeCode", {
            "language": "python",
            "code": f"open('{WORKDIR}/dual_{i}.txt', 'w').write('{'x' * 1024}')\nprint('ok')"
        })
        # 同步 S3 PUT（最坏情况，实际应异步）
        s3.put_object(
            Bucket=SYNC_BUCKET,
            Key=f"sessions/{sid}/dual_{i}.txt",
            Body=content_1k.encode(),
        )
        times_dual.append(time.time() - t0)

    # 仅 S3 PUT 延迟
    print("  单独 S3 PUT 延迟 (20次 x 1KB)...")
    times_s3_only = []
    for i in range(20):
        t0 = time.time()
        s3.put_object(
            Bucket=SYNC_BUCKET,
            Key=f"sessions/{sid}/s3only_{i}.txt",
            Body=content_1k.encode(),
        )
        times_s3_only.append(time.time() - t0)

    ci.stop()

    # 统计
    def stats(times):
        times.sort()
        p50 = times[len(times) // 2]
        p95 = times[int(len(times) * 0.95)]
        avg = sum(times) / len(times)
        return {"avg_ms": int(avg * 1000), "p50_ms": int(p50 * 1000), "p95_ms": int(p95 * 1000)}

    baseline_stats = stats(times_baseline)
    dual_stats = stats(times_dual)
    s3_stats = stats(times_s3_only)

    print(f"\n  结果:")
    print(f"    纯沙箱写入:     avg={baseline_stats['avg_ms']}ms  p50={baseline_stats['p50_ms']}ms  p95={baseline_stats['p95_ms']}ms")
    print(f"    双写(同步S3):   avg={dual_stats['avg_ms']}ms  p50={dual_stats['p50_ms']}ms  p95={dual_stats['p95_ms']}ms")
    print(f"    单独 S3 PUT:    avg={s3_stats['avg_ms']}ms  p50={s3_stats['p50_ms']}ms  p95={s3_stats['p95_ms']}ms")
    print(f"    双写额外开销:   ~{dual_stats['avg_ms'] - baseline_stats['avg_ms']}ms (= S3 PUT 延迟)")
    print(f"    → 如果改为异步 PUT，write_file 延迟 ≈ 纯沙箱写入延迟")

    overhead = dual_stats["avg_ms"] - baseline_stats["avg_ms"]
    passed = True  # 这是性能测量，不存在 pass/fail

    return ExperimentResult(
        name="双写性能测试",
        passed=passed,
        detail=f"S3 PUT 额外开销 ~{overhead}ms（异步化后为 0）",
        metrics={
            "baseline": baseline_stats,
            "dual_write_sync": dual_stats,
            "s3_put_only": s3_stats,
            "overhead_ms": overhead,
        },
    )


# ═══════════════════════════════════════════════════
# 实验 4：恢复完整性（connect 时 restore from S3）
# ═══════════════════════════════════════════════════

def experiment_4_restore_integrity():
    """验证从 S3 恢复后文件内容完整"""
    print("\n" + "=" * 60)
    print("实验 4：S3 恢复完整性")
    print("=" * 60)

    import boto3
    s3 = boto3.client("s3", region_name=REGION)

    # 准备测试文件
    test_files = {
        "report.json": json.dumps({"key": "value", "中文": "测试", "数组": [1, 2, 3]}, ensure_ascii=False),
        "code.py": "# -*- coding: utf-8 -*-\ndef hello():\n    print('你好世界')\n",
        "data.csv": "name,age,city\n张三,25,北京\n李四,30,上海\n" * 100,
        "nested/deep/config.yaml": "server:\n  host: 0.0.0.0\n  port: 8080\n",
    }

    session_key = f"eval_restore_{int(time.time())}"
    prefix = f"sessions/{session_key}"

    # 上传到 S3（模拟之前 sync 过的数据）
    print(f"  上传 {len(test_files)} 个文件到 S3 (prefix={prefix}/)...")
    for rel_path, content in test_files.items():
        s3.put_object(
            Bucket=SYNC_BUCKET,
            Key=f"{prefix}/{rel_path}",
            Body=content.encode("utf-8"),
        )

    # 创建新沙箱，模拟 restore
    ci = CodeInterpreter(region=REGION)
    sid = ci.start(name="eval_exp4_restore", session_timeout_seconds=600)
    invoke_text(ci, "executeCommand", {"command": f"mkdir -p {WORKDIR}"})
    print(f"  新会话: {sid}")

    # 从 S3 下载到沙箱
    print("  从 S3 恢复文件到沙箱...")
    paginator = s3.get_paginator("list_objects_v2")
    pages = paginator.paginate(Bucket=SYNC_BUCKET, Prefix=f"{prefix}/")

    restored = 0
    for page in pages:
        for obj in page.get("Contents", []):
            s3_key = obj["Key"]
            rel = s3_key[len(prefix) + 1:]
            if not rel:
                continue
            resp = s3.get_object(Bucket=SYNC_BUCKET, Key=s3_key)
            content = resp["Body"].read().decode("utf-8")
            target = f"{WORKDIR}/{rel}"

            # 用 python 写入沙箱
            invoke_text(ci, "executeCode", {
                "language": "python",
                "code": f"import os\nos.makedirs(os.path.dirname({target!r}) or '.', exist_ok=True)\nopen({target!r},'w',encoding='utf-8').write({content!r})\nprint('ok')"
            })
            restored += 1

    print(f"  恢复了 {restored} 个文件")

    # 验证完整性
    print("  验证文件内容...")
    results = {}
    for rel_path, expected in test_files.items():
        actual = invoke_text(ci, "executeCommand", {"command": f"cat {WORKDIR}/{rel_path}"})
        match = actual.strip() == expected.strip()
        results[rel_path] = "✅ 一致" if match else f"❌ 不一致 (len: {len(actual)} vs {len(expected)})"
        print(f"    {rel_path}: {results[rel_path]}")

    ci.stop()

    passed = all("✅" in v for v in results.values())
    return ExperimentResult(
        name="S3 恢复完整性",
        passed=passed,
        detail=str(results),
        metrics={"files_restored": restored, "files_verified": len(results)},
    )


# ═══════════════════════════════════════════════════
# 实验 5：定时 sync 开销估算（策略 C）
# ═══════════════════════════════════════════════════

def experiment_5_periodic_sync_cost():
    """测量 find + diff + upload 的开销，评估心跳 sync 成本"""
    print("\n" + "=" * 60)
    print("实验 5：定时 sync 开销估算（策略 C）")
    print("=" * 60)

    import boto3
    s3 = boto3.client("s3", region_name=REGION)

    ci = CodeInterpreter(region=REGION)
    sid = ci.start(name="eval_exp5_periodic", session_timeout_seconds=600)
    invoke_text(ci, "executeCommand", {"command": f"mkdir -p {WORKDIR}"})
    print(f"  会话: {sid}")

    # 创建模拟工作负载：20 个文件
    print("  创建 20 个测试文件...")
    invoke_text(ci, "executeCode", {
        "language": "python",
        "code": f"""
import os
for i in range(20):
    path = f'{WORKDIR}/file_{{i:03d}}.txt'
    with open(path, 'w') as f:
        f.write(f'content {{i}}\\n' * 100)
print('created 20 files')
"""
    })

    # 测量 find 命令耗时
    t0 = time.time()
    files_output = invoke_text(ci, "executeCommand",
                               {"command": f"find {WORKDIR} -type f -newer /tmp/.sync_marker 2>/dev/null || find {WORKDIR} -type f"})
    find_time = time.time() - t0
    files = [f.strip() for f in files_output.split("\n") if f.strip()]
    print(f"  find 耗时: {int(find_time * 1000)}ms, 发现 {len(files)} 个文件")

    # 测量全量 sync 耗时
    t0 = time.time()
    for fpath in files:
        content = invoke_text(ci, "executeCommand", {"command": f"cat {fpath}"})
        rel = fpath[len(WORKDIR) + 1:]
        s3.put_object(Bucket=SYNC_BUCKET, Key=f"sessions/{sid}/{rel}", Body=content.encode())
    full_sync_time = time.time() - t0
    print(f"  全量 sync 耗时: {int(full_sync_time * 1000)}ms ({len(files)} 个文件)")

    # 模拟增量：只改 3 个文件
    invoke_text(ci, "executeCommand", {"command": f"touch /tmp/.sync_marker"})
    time.sleep(1)
    invoke_text(ci, "executeCode", {
        "language": "python",
        "code": f"""
for i in [0, 5, 10]:
    with open(f'{WORKDIR}/file_{{i:03d}}.txt', 'a') as f:
        f.write('updated\\n')
print('updated 3 files')
"""
    })

    # 测量增量 sync
    t0 = time.time()
    changed_output = invoke_text(ci, "executeCommand",
                                  {"command": f"find {WORKDIR} -type f -newer /tmp/.sync_marker"})
    changed = [f.strip() for f in changed_output.split("\n") if f.strip()]
    for fpath in changed:
        content = invoke_text(ci, "executeCommand", {"command": f"cat {fpath}"})
        rel = fpath[len(WORKDIR) + 1:]
        s3.put_object(Bucket=SYNC_BUCKET, Key=f"sessions/{sid}/{rel}", Body=content.encode())
    incr_sync_time = time.time() - t0
    print(f"  增量 sync 耗时: {int(incr_sync_time * 1000)}ms ({len(changed)} 个变更文件)")

    ci.stop()

    # 成本估算
    # 假设心跳间隔 30s，Agent 任务平均 5min = 10 次心跳
    # 每次心跳 = 1 次 find + N 次 cat + N 次 S3 PUT
    print(f"\n  成本估算（假设心跳=30s，任务=5min，文件数=20）:")
    print(f"    每次心跳延迟: ~{int(incr_sync_time * 1000)}ms（增量）")
    print(f"    每任务心跳次数: ~10")
    print(f"    每任务额外 S3 PUT: ~{len(changed) * 10} 次（估算）")
    print(f"    S3 PUT 费用: $0.005/1000次 → 每任务 ~${len(changed) * 10 * 0.005 / 1000:.6f}")

    return ExperimentResult(
        name="定时 sync 开销",
        passed=True,
        detail=f"全量={int(full_sync_time*1000)}ms, 增量={int(incr_sync_time*1000)}ms",
        metrics={
            "find_ms": int(find_time * 1000),
            "full_sync_ms": int(full_sync_time * 1000),
            "incr_sync_ms": int(incr_sync_time * 1000),
            "total_files": len(files),
            "changed_files": len(changed),
        },
    )


# ═══════════════════════════════════════════════════
# 主入口
# ═══════════════════════════════════════════════════

def main():
    print("=" * 60)
    print("  AWS 沙箱 S3 同步策略验证")
    print(f"  区域: {REGION} | 桶: {SYNC_BUCKET}")
    print("=" * 60)

    results = []

    # 实验 1: 基线
    try:
        results.append(experiment_1_baseline_sync())
    except Exception as e:
        print(f"  ❌ 实验 1 失败: {e}")
        results.append(ExperimentResult("收尾 sync 可靠性", False, str(e)))

    # 实验 3: 双写性能（先于实验 2，因为实验 2 要等 5 分钟）
    try:
        results.append(experiment_3_dual_write_perf())
    except Exception as e:
        print(f"  ❌ 实验 3 失败: {e}")
        results.append(ExperimentResult("双写性能测试", False, str(e)))

    # 实验 4: 恢复完整性
    try:
        results.append(experiment_4_restore_integrity())
    except Exception as e:
        print(f"  ❌ 实验 4 失败: {e}")
        results.append(ExperimentResult("S3 恢复完整性", False, str(e)))

    # 实验 5: 定时 sync 开销
    try:
        results.append(experiment_5_periodic_sync_cost())
    except Exception as e:
        print(f"  ❌ 实验 5 失败: {e}")
        results.append(ExperimentResult("定时 sync 开销", False, str(e)))

    # 实验 2: TTL 超时（最后跑，耗时长）
    if "--skip-ttl" not in sys.argv:
        try:
            results.append(experiment_2_ttl_expiry())
        except KeyboardInterrupt:
            print("\n  跳过 TTL 实验")
            results.append(ExperimentResult("TTL 超时验证", True, "跳过（用户中断）"))
        except Exception as e:
            print(f"  ❌ 实验 2 失败: {e}")
            results.append(ExperimentResult("TTL 超时验证", False, str(e)))
    else:
        print("\n  跳过 TTL 实验 (--skip-ttl)")

    # 汇总
    print("\n" + "=" * 60)
    print("  验证结果汇总")
    print("=" * 60)
    for r in results:
        status = "✅" if r.passed else "❌"
        print(f"  {status} {r.name}: {r.detail[:80]}")
        if r.metrics:
            print(f"     指标: {r.metrics}")

    print("\n  决策建议:")
    # 如果实验 3 有结果，给出建议
    exp3 = next((r for r in results if "双写" in r.name and r.metrics), None)
    if exp3 and exp3.metrics:
        overhead = exp3.metrics.get("overhead_ms", 0)
        if overhead < 200:
            print(f"  → 策略 B（write_file 双写）可行：S3 PUT 开销 ~{overhead}ms，异步化后不影响延迟")
            print(f"  → 推荐采用策略 B + 收尾兜底 sync")
        else:
            print(f"  → S3 PUT 延迟较高 ({overhead}ms)，建议评估是否可接受或改用策略 A")

    print("=" * 60)


if __name__ == "__main__":
    main()
