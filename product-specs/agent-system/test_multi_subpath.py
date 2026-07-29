#!/usr/bin/env python3
"""
验证：一个沙箱是否可以挂载多个 subPath

测试发现：
  - 同一 name 挂载多次时，API 要求必须指定不同的 mountPath
  - 本脚本测试各种 mountPath 组合
"""

import os
import json

os.environ["E2B_DOMAIN"] = "ap-beijing.tencentags.com"
os.environ["E2B_API_KEY"] = "ark_dGTlMcosC-n-ZNhfKyW8aBJm3c0KNLXzjSkT7t_3WWc"

from e2b import Sandbox

TEMPLATE = "code-sandbox"


def safe_run(sandbox, cmd):
    """执行命令，不抛异常"""
    try:
        result = sandbox.commands.run(f"bash -c '{cmd}'")
        return result.stdout.strip()
    except Exception as e:
        return f"[ERROR] {e}"


def test_scenario(name, mounts):
    """通用测试场景"""
    print(f"\n{'─' * 60}")
    print(f"[{name}]")
    print(f"  挂载配置: {json.dumps(mounts)}")

    sandbox = None
    try:
        sandbox = Sandbox.create(
            template=TEMPLATE,
            timeout=300,
            metadata={"x-mounts": json.dumps(mounts)}
        )
        print(f"  ✅ 沙箱创建成功: {sandbox.sandbox_id}")

        # 查看所有 virtiofs 挂载
        print(f"\n  挂载信息:")
        output = safe_run(sandbox, "mount | grep virtio")
        for line in output.split("\n"):
            if line.strip():
                print(f"    {line.strip()}")

        # df 查看磁盘使用
        print(f"\n  磁盘信息:")
        output = safe_run(sandbox, "df -h | grep -v tmpfs | grep -v overlay")
        for line in output.split("\n"):
            if line.strip():
                print(f"    {line.strip()}")

        # 检查各挂载路径
        paths_to_check = set()
        for m in mounts:
            mp = m.get("mountPath", "/sandbox")
            paths_to_check.add(mp)
        paths_to_check.add("/sandbox")  # 默认也检查

        for path in sorted(paths_to_check):
            print(f"\n  [{path}]:")
            # 检查是否存在
            exists = safe_run(sandbox, f"test -d {path} && echo YES || echo NO")
            print(f"    存在: {exists}")
            if "YES" in exists:
                # 列目录
                ls_output = safe_run(sandbox, f"ls -la {path}/ 2>&1 | head -10")
                print(f"    内容: {ls_output}")
                # 写入测试
                write_result = safe_run(sandbox, f"echo test_write > {path}/write_test.txt 2>&1 && echo WRITE_OK || echo WRITE_FAIL")
                print(f"    写入: {write_result}")
                # 读取验证
                if "WRITE_OK" in write_result:
                    read_result = safe_run(sandbox, f"cat {path}/write_test.txt 2>&1")
                    print(f"    读回: {read_result}")

        return True

    except Exception as e:
        print(f"  ❌ 异常: {type(e).__name__}: {e}")
        return False

    finally:
        if sandbox:
            try:
                sandbox.kill()
                print(f"\n  沙箱已销毁")
            except:
                pass


def main():
    print("=" * 60)
    print("验证：一个沙箱能否挂载同一 COS 的多个 subPath")
    print("=" * 60)

    results = {}

    # 场景 1: 同一 COS，不同 subPath，不同 mountPath
    results["多subPath+多mountPath"] = test_scenario(
        "场景1: 同一 COS，不同 subPath，不同 mountPath",
        [
            {"name": "cos-aitools", "subPath": "data/path-alpha", "mountPath": "/mnt/alpha"},
            {"name": "cos-aitools", "subPath": "data/path-beta", "mountPath": "/mnt/beta"},
        ]
    )

    # 场景 2: 不带 subPath + 带 subPath
    results["根+subPath"] = test_scenario(
        "场景2: COS 根目录(/sandbox) + subPath(/mnt/extra)",
        [
            {"name": "cos-aitools", "mountPath": "/sandbox"},
            {"name": "cos-aitools", "subPath": "data/extra", "mountPath": "/mnt/extra"},
        ]
    )

    # 场景 3: 不带 subPath 的默认挂载 + 额外 subPath 挂载
    results["默认+额外"] = test_scenario(
        "场景3: 默认挂载(无mountPath) + 额外subPath挂载",
        [
            {"name": "cos-aitools"},
            {"name": "cos-aitools", "subPath": "data/extra2", "mountPath": "/mnt/extra2"},
        ]
    )

    # 场景 4: 对照组 - 单挂载不带 subPath
    results["对照-无subPath"] = test_scenario(
        "场景4 对照: 单个挂载，不带 subPath",
        [{"name": "cos-aitools"}]
    )

    # 场景 5: 对照组 - 单挂载带 subPath
    results["对照-有subPath"] = test_scenario(
        "场景5 对照: 单个挂载，带 subPath",
        [{"name": "cos-aitools", "subPath": "data/path-alpha"}]
    )

    # 总结
    print("\n" + "=" * 60)
    print("总结")
    print("=" * 60)
    for name, ok in results.items():
        print(f"  {name}: {'✅ 成功' if ok else '❌ 失败'}")


if __name__ == "__main__":
    main()
