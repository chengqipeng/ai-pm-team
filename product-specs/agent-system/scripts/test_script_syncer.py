"""
ScriptSyncer 端到端测试 — 验证 Skill 脚本从 DB 同步到沙盒

测试流程:
  1. 从 DB 读取 csv-trend-analysis 的 scripts/ 文件
  2. 通过 SSH Backend 同步到远程虚拟机
  3. 验证文件已写入正确路径
  4. 验证增量同步（第二次跳过）
  5. 验证脚本可执行

使用方式:
    python3 scripts/test_script_syncer.py

环境变量:
    SANDBOX_SSH_HOST=172.17.2.118
    SANDBOX_SSH_USER=hermes
    SANDBOX_SSH_KEY=~/.ssh/hermes_vm_key
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.tools.sandbox import SSHBackend, ScriptSyncer, SKILL_BASE_DIR
from src.tools.sandbox.backend_base import BackendConfig


async def main():
    print("=" * 70)
    print("  ScriptSyncer 端到端测试")
    print("=" * 70)

    # 配置 SSH Backend
    config = BackendConfig(
        backend_type="ssh",
        ssh_host=os.environ.get("SANDBOX_SSH_HOST", "172.17.2.118"),
        ssh_user=os.environ.get("SANDBOX_SSH_USER", "hermes"),
        ssh_key=os.environ.get("SANDBOX_SSH_KEY",
                               os.path.expanduser("~/.ssh/hermes_vm_key")),
        ssh_port=int(os.environ.get("SANDBOX_SSH_PORT", "22")),
        timeout=30,
    )

    print(f"\n目标: {config.ssh_user}@{config.ssh_host}:{config.ssh_port}")

    backend = SSHBackend(config)
    syncer = ScriptSyncer(backend=backend, tenant_id=0)

    skill_name = "csv-trend-analysis"
    skill_dir = syncer.get_skill_dir(skill_name)

    # ── 测试 0: 连接 ──
    print("\n--- 测试 0: SSH 连接 ---")
    try:
        await backend.connect()
        print("✅ 连接成功")
    except Exception as e:
        print(f"❌ 连接失败: {e}")
        return

    # ── 测试 1: 清理旧数据 ──
    print("\n--- 测试 1: 清理旧同步数据 ---")
    await syncer.cleanup(skill_name)
    print(f"✅ 已清理 {skill_dir}")

    # ── 测试 2: 首次全量同步 ──
    print("\n--- 测试 2: 首次全量同步 ---")
    result = await syncer.sync(skill_name, version="1.0.0")
    print(f"  synced: {result.synced}")
    print(f"  skipped: {result.skipped}")
    print(f"  errors: {result.errors}")
    print(f"  duration: {result.duration_ms:.0f}ms")

    if result.synced == 3 and not result.errors:
        print("✅ 首次同步: 3 个文件全量写入")
    else:
        print(f"❌ 预期 synced=3, 实际 synced={result.synced}, errors={result.errors}")

    # ── 测试 3: 验证文件存在 ──
    print("\n--- 测试 3: 验证沙盒中文件存在 ---")
    files_to_check = [
        f"{skill_dir}/scripts/analyze.py",
        f"{skill_dir}/scripts/utils.py",
        f"{skill_dir}/scripts/requirements.txt",
        f"{skill_dir}/.sync_manifest.json",
    ]
    all_exist = True
    for f in files_to_check:
        exists = await backend.file_exists(f)
        status = "✅" if exists else "❌"
        print(f"  {status} {f}")
        if not exists:
            all_exist = False

    if all_exist:
        print("✅ 所有文件已正确同步")
    else:
        print("❌ 部分文件缺失")

    # ── 测试 4: 验证文件内容 ──
    print("\n--- 测试 4: 验证 analyze.py 内容 ---")
    read_result = await backend.read_file(f"{skill_dir}/scripts/analyze.py")
    if not read_result.is_error and "def analyze_trend" in read_result.stdout:
        print(f"✅ analyze.py 内容正确 ({len(read_result.stdout)} 字符)")
    else:
        print(f"❌ 内容异常: {read_result.output[:100]}")

    # ── 测试 5: 增量同步（应全部跳过） ──
    print("\n--- 测试 5: 增量同步（无变更应跳过） ---")
    result2 = await syncer.sync(skill_name, version="1.0.0")
    print(f"  synced: {result2.synced}")
    print(f"  skipped: {result2.skipped}")

    if result2.synced == 0 and result2.skipped == 3:
        print("✅ 增量同步: hash 一致，全部跳过")
    else:
        print(f"❌ 预期 synced=0 skipped=3, 实际 synced={result2.synced} skipped={result2.skipped}")

    # ── 测试 6: is_synced 检查 ──
    print("\n--- 测试 6: is_synced 状态检查 ---")
    synced = await syncer.is_synced(skill_name, version="1.0.0")
    if synced:
        print("✅ is_synced=True（已同步）")
    else:
        print("❌ is_synced=False（不应该）")

    # ── 测试 7: 强制全量同步 ──
    print("\n--- 测试 7: 强制全量同步 (force=True) ---")
    result3 = await syncer.sync(skill_name, version="1.0.0", force=True)
    if result3.synced == 3:
        print(f"✅ 强制同步: 3 个文件重新写入 ({result3.duration_ms:.0f}ms)")
    else:
        print(f"❌ 预期 synced=3, 实际 synced={result3.synced}")

    # ── 测试 8: 验证执行权限 ──
    print("\n--- 测试 8: 验证脚本执行权限 ---")
    perm_result = await backend.execute(
        f"ls -la {skill_dir}/scripts/analyze.py | awk '{{print $1}}'"
    )
    perms = perm_result.stdout.strip()
    if "x" in perms:
        print(f"✅ 执行权限已设置: {perms}")
    else:
        print(f"❌ 缺少执行权限: {perms}")

    # ── 测试 9: 验证脚本可运行 ──
    print("\n--- 测试 9: 验证脚本可运行 (--help) ---")
    run_result = await backend.execute(
        f"python3 {skill_dir}/scripts/analyze.py --help"
    )
    if "usage" in run_result.stdout.lower() or "csv" in run_result.stdout.lower():
        print(f"✅ 脚本可执行:\n  {run_result.stdout.strip()[:100]}")
    elif "No module named" in run_result.output:
        print(f"⚠️  脚本语法正确但缺少依赖（预期行为）:\n  {run_result.output.strip()[:100]}")
    else:
        print(f"❌ 执行异常: {run_result.output[:200]}")

    # ── 清理 ──
    print("\n--- 清理 ---")
    await syncer.cleanup(skill_name)
    await backend.disconnect()
    print("✅ 清理完成，连接已断开")

    print("\n" + "=" * 70)
    print("  ScriptSyncer 测试完成")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())
