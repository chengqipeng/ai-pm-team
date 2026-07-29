#!/usr/bin/env python3
"""
验证：同一个 COS 桶的同一个 subPath 是否可以同时挂载到多个沙箱

测试场景：
  1. 用沙箱 A 创建并写入文件到 /sandbox（使用固定 subPath）
  2. 同时创建沙箱 B，挂载相同的 subPath
  3. 验证沙箱 B 是否能读到沙箱 A 写入的文件
  4. 验证沙箱 B 是否能写入新文件
  5. 验证沙箱 A 是否能看到沙箱 B 写入的文件

结论判定：
  - 如果两者都能读 → 同一 subPath 可多沙箱同时只读挂载
  - 如果能写 → 同一 subPath 可多沙箱同时读写挂载
  - 如果写失败 → 只读限制确认
"""

import os
import json
import time

os.environ["E2B_DOMAIN"] = "ap-beijing.tencentags.com"
os.environ["E2B_API_KEY"] = "ark_dGTlMcosC-n-ZNhfKyW8aBJm3c0KNLXzjSkT7t_3WWc"

from e2b import Sandbox

TEMPLATE = "code-sandbox"
SHARED_SUBPATH = "data/shared-mount-test"


def test_same_subpath_multi_sandbox():
    """测试同一 subPath 同时挂载到多个沙箱"""

    print("=" * 60)
    print("测试：同一 COS subPath 同时挂载到多个沙箱")
    print(f"subPath: {SHARED_SUBPATH}")
    print("=" * 60)

    sandbox_a = None
    sandbox_b = None

    try:
        # ─── Step 1: 创建沙箱 A ───
        print(f"\n[1] 创建沙箱 A (subPath={SHARED_SUBPATH})...")
        sandbox_a = Sandbox.create(
            template=TEMPLATE,
            timeout=300,
            metadata={
                "x-mounts": json.dumps([{
                    "name": "cos-aitools",
                    "subPath": SHARED_SUBPATH,
                }])
            }
        )
        print(f"    ✅ 沙箱 A 创建成功: {sandbox_a.sandbox_id}")

        # ─── Step 2: 沙箱 A 检查 /sandbox 目录状态 ───
        print("\n[2] 沙箱 A: 检查 /sandbox 挂载状态...")
        result = sandbox_a.commands.run("ls -la /sandbox/ 2>&1; echo EXIT:$?")
        print(f"    ls /sandbox/: {result.stdout.strip()}")

        # ─── Step 3: 沙箱 A 尝试写入文件 ───
        print("\n[3] 沙箱 A: 尝试写入文件 /sandbox/from_a.txt...")
        result = sandbox_a.commands.run(
            'echo "Hello from sandbox A - $(date)" > /sandbox/from_a.txt 2>&1; echo EXIT:$?'
        )
        print(f"    写入结果: {result.stdout.strip()}")

        a_can_write = "EXIT:0" in result.stdout
        if a_can_write:
            print("    ✅ 沙箱 A 写入成功")
        else:
            print("    ❌ 沙箱 A 写入失败（只读）")

        # ─── Step 4: 创建沙箱 B（同一 subPath） ───
        print(f"\n[4] 创建沙箱 B (相同 subPath={SHARED_SUBPATH})...")
        sandbox_b = Sandbox.create(
            template=TEMPLATE,
            timeout=300,
            metadata={
                "x-mounts": json.dumps([{
                    "name": "cos-aitools",
                    "subPath": SHARED_SUBPATH,
                }])
            }
        )
        print(f"    ✅ 沙箱 B 创建成功: {sandbox_b.sandbox_id}")
        print("    （同一 subPath 可以被多个沙箱同时挂载 — API 不阻止）")

        # ─── Step 5: 沙箱 B 检查 /sandbox 目录 ───
        print("\n[5] 沙箱 B: 列出 /sandbox/ 目录...")
        result = sandbox_b.commands.run("ls -la /sandbox/ 2>&1")
        print(f"    ls /sandbox/:\n    {result.stdout.strip()}")

        # ─── Step 6: 沙箱 B 尝试读取沙箱 A 写入的文件 ───
        print("\n[6] 沙箱 B: 尝试读取 /sandbox/from_a.txt...")
        result = sandbox_b.commands.run("cat /sandbox/from_a.txt 2>&1; echo EXIT:$?")
        print(f"    读取结果: {result.stdout.strip()}")

        b_can_read_a = "EXIT:0" in result.stdout and "Hello from sandbox A" in result.stdout
        if b_can_read_a:
            print("    ✅ 沙箱 B 能读到沙箱 A 写入的文件（共享可见）")
        else:
            print("    ❌ 沙箱 B 看不到沙箱 A 写入的文件")

        # ─── Step 7: 沙箱 B 尝试写入文件 ───
        print("\n[7] 沙箱 B: 尝试写入文件 /sandbox/from_b.txt...")
        result = sandbox_b.commands.run(
            'echo "Hello from sandbox B - $(date)" > /sandbox/from_b.txt 2>&1; echo EXIT:$?'
        )
        print(f"    写入结果: {result.stdout.strip()}")

        b_can_write = "EXIT:0" in result.stdout
        if b_can_write:
            print("    ✅ 沙箱 B 写入成功")
        else:
            print("    ❌ 沙箱 B 写入失败（只读）")

        # ─── Step 8: 沙箱 A 检查是否能看到沙箱 B 的文件 ───
        print("\n[8] 沙箱 A: 尝试读取 /sandbox/from_b.txt...")
        result = sandbox_a.commands.run("cat /sandbox/from_b.txt 2>&1; echo EXIT:$?")
        print(f"    读取结果: {result.stdout.strip()}")

        a_can_read_b = "EXIT:0" in result.stdout and "Hello from sandbox B" in result.stdout
        if a_can_read_b:
            print("    ✅ 沙箱 A 能读到沙箱 B 写入的文件（双向共享）")
        else:
            print("    ❌ 沙箱 A 看不到沙箱 B 写入的文件")

        # ─── Step 9: 额外验证 — df 查看挂载信息 ───
        print("\n[9] 沙箱 A: 查看挂载信息...")
        result = sandbox_a.commands.run("df -h /sandbox/ 2>&1; mount | grep sandbox 2>&1")
        print(f"    {result.stdout.strip()}")

        # ─── 总结 ───
        print("\n" + "=" * 60)
        print("测试总结")
        print("=" * 60)
        print(f"  同一 subPath 创建多个沙箱:  ✅ 可以（API 不阻止）")
        print(f"  沙箱 A 写入 /sandbox:        {'✅ 可写' if a_can_write else '❌ 只读'}")
        print(f"  沙箱 B 写入 /sandbox:        {'✅ 可写' if b_can_write else '❌ 只读'}")
        print(f"  沙箱 B 读取 A 的文件:        {'✅ 可见' if b_can_read_a else '❌ 不可见'}")
        print(f"  沙箱 A 读取 B 的文件:        {'✅ 可见' if a_can_read_b else '❌ 不可见'}")

        if a_can_write and b_can_write and b_can_read_a and a_can_read_b:
            print("\n  🎉 结论: 同一 subPath 可多沙箱同时读写挂载，数据实时共享")
        elif a_can_write and b_can_write:
            print("\n  📝 结论: 同一 subPath 可多沙箱同时读写，但不实时共享（各自独立副本）")
        elif not a_can_write and not b_can_write:
            print("\n  🔒 结论: 同一 subPath 多沙箱挂载后均为只读（virtiofs 限制确认）")
        else:
            print("\n  ⚠️  结论: 行为不一致，需进一步排查")

    except Exception as e:
        print(f"\n❌ 测试异常: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()

    finally:
        # 清理
        print("\n[清理] 销毁沙箱...")
        if sandbox_a:
            try:
                sandbox_a.kill()
                print(f"    沙箱 A ({sandbox_a.sandbox_id}) 已销毁")
            except Exception as e:
                print(f"    沙箱 A 销毁失败: {e}")
        if sandbox_b:
            try:
                sandbox_b.kill()
                print(f"    沙箱 B ({sandbox_b.sandbox_id}) 已销毁")
            except Exception as e:
                print(f"    沙箱 B 销毁失败: {e}")


if __name__ == "__main__":
    test_same_subpath_multi_sandbox()
