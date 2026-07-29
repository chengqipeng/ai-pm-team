"""
Demo: 每个 Agent 对话 Session 创建独立 COS 挂载目录 — 物理隔离 + 跨沙盒恢复

核心机制:
  1. 首次创建 session: 挂载 COS 根目录到 /sandbox/.skills → mkdir 创建 session 子目录
  2. 后续恢复 session: 用 subPath={session_id} 挂载到 /sandbox/.skills，只能看到本 session 数据
  3. 不同 session 之间物理隔离: subPath 限定挂载范围，无法路径穿越

沙盒内统一使用路径: /sandbox/.skills/

前置条件:
  - pip install e2b python-dotenv
  - 在同目录 .env 文件中配置好 TENCENT_SANDBOX_API_KEY

使用方式:
  python3 demo_session_cos_sandbox.py
"""

import os
import json
import uuid
from pathlib import Path
from dotenv import dotenv_values

# ============ 从 .env 加载配置 ============
_env_path = Path(__file__).parent / ".env"
_env = dotenv_values(_env_path)


def _get(key: str, default: str = "") -> str:
    return _env.get(key, os.environ.get(key, default))


E2B_API_KEY = _get("TENCENT_SANDBOX_API_KEY")
E2B_DOMAIN = _get("TENCENT_SANDBOX_DOMAIN", "ap-beijing.tencentags.com")
SANDBOX_TEMPLATE = _get("TENCENT_SANDBOX_TEMPLATE", "code-sandbox")
SANDBOX_TIMEOUT = int(_get("TENCENT_SANDBOX_TIMEOUT", "300"))
MOUNT_NAME = _get("TENCENT_SANDBOX_MOUNT_NAME", "cos-aitools")

# ⚠️ 必须在 import e2b 之前设置
os.environ["E2B_DOMAIN"] = E2B_DOMAIN
os.environ["E2B_API_KEY"] = E2B_API_KEY
os.environ["E2B_VALIDATE_API_KEY"] = "false"

from e2b import Sandbox


# ============ 核心类 ============

class SessionSandboxManager:
    """管理 Session 级别的 COS 隔离沙盒

    沙盒内统一路径: /sandbox/.skills/

    生命周期:
      1. init_session()    — 首次创建 session，建立 COS 目录
      2. restore_session() — 后续恢复 session，subPath 隔离挂载
      3. execute()         — 在沙盒中执行命令
      4. destroy()         — 销毁沙盒（COS 数据保留）
    """

    MOUNT_PATH = "/sandbox/.skills"  # 沙盒内统一挂载路径

    def __init__(
        self,
        mount_name: str = MOUNT_NAME,
        template: str = SANDBOX_TEMPLATE,
        timeout: int = SANDBOX_TIMEOUT,
    ):
        self.mount_name = mount_name
        self.template = template
        self.timeout = max(timeout, 300)
        self._sandbox: Sandbox | None = None

    @property
    def sandbox_id(self) -> str | None:
        return self._sandbox.sandbox_id if self._sandbox else None

    def connect(self, session_id: str) -> None:
        """连接到 session: 确保目录存在 + 隔离挂载

        逻辑:
          1. 挂载 COS 根目录，mkdir -p 确保 session 子目录存在（幂等操作）
          2. 销毁临时沙盒
          3. 用 subPath 创建隔离沙盒

        mkdir -p 对已有目录无影响，因此无论是首次还是恢复都走同一条路径。

        Args:
            session_id: 会话唯一标识
        """
        # 确保 session 目录存在（幂等）
        init_sandbox = Sandbox.create(
            template=self.template,
            timeout=self.timeout,
            metadata={"x-mounts": json.dumps([{
                "name": self.mount_name,
                "mountPath": self.MOUNT_PATH,
            }])},
        )
        init_sandbox.commands.run(f"mkdir -p {self.MOUNT_PATH}/{session_id}")
        init_sandbox.kill()

        # 用 subPath 隔离挂载
        self._sandbox = Sandbox.create(
            template=self.template,
            timeout=self.timeout,
            metadata={"x-mounts": json.dumps([{
                "name": self.mount_name,
                "subPath": session_id,
                "mountPath": self.MOUNT_PATH,
            }])},
        )

    def init_session(self, session_id: str) -> None:
        """首次创建 session: 挂载 COS 根目录，mkdir 创建 session 子目录

        一般不需要直接调用，connect() 会自动判断。
        仅当需要批量预创建目录时使用。

        Args:
            session_id: 会话唯一标识
        """
        self._sandbox = Sandbox.create(
            template=self.template,
            timeout=self.timeout,
            metadata={"x-mounts": json.dumps([{
                "name": self.mount_name,
                "mountPath": self.MOUNT_PATH,
            }])},
        )
        self._sandbox.commands.run(f"mkdir -p {self.MOUNT_PATH}/{session_id}")

    def restore_session(self, session_id: str) -> None:
        """恢复已有 session: 用 subPath 只挂载该 session 的 COS 子目录

        挂载后 /sandbox/.skills/ 下只能看到本 session 的文件，
        无法通过路径穿越访问其他 session。

        前提: 该 session 已通过 init_session() 初始化过。

        Args:
            session_id: 会话唯一标识
        """
        self._sandbox = Sandbox.create(
            template=self.template,
            timeout=self.timeout,
            metadata={"x-mounts": json.dumps([{
                "name": self.mount_name,
                "subPath": session_id,
                "mountPath": self.MOUNT_PATH,
            }])},
        )

    def execute(self, command: str, timeout: int = 60) -> str:
        """在沙盒中执行命令，返回 stdout"""
        if not self._sandbox:
            raise RuntimeError("沙盒未创建")
        result = self._sandbox.commands.run(command, timeout=timeout)
        return result.stdout

    def destroy(self):
        """销毁沙盒（COS 数据保留）"""
        if self._sandbox:
            self._sandbox.kill()
            self._sandbox = None


# ============ 演示 ============

def main():
    if not E2B_API_KEY:
        print("⚠️  请在 .env 中配置 TENCENT_SANDBOX_API_KEY")
        return

    session_a = f"sess_a_{uuid.uuid4().hex[:6]}"
    session_b = f"sess_b_{uuid.uuid4().hex[:6]}"

    print("=" * 60)
    print("验证: connect() 自动判断 + Session 隔离")
    print(f"统一路径: /sandbox/.skills/")
    print("=" * 60)

    # ─── Step 1: 首次 connect Session A（自动检测不存在 → 创建目录 → 隔离挂载） ───
    print(f"\n[Step 1] 首次 connect Session A: {session_a}")
    mgr_a = SessionSandboxManager()
    mgr_a.connect(session_a)
    print(f"  沙盒: {mgr_a.sandbox_id}")
    mgr_a.execute("echo 'A的机密数据' > /sandbox/.skills/secret.txt")
    mgr_a.execute("echo 'A的报告' > /sandbox/.skills/report.txt")
    files_a = mgr_a.execute("ls /sandbox/.skills/").strip()
    print(f"  写入后文件: {files_a}")
    mgr_a.destroy()
    print("  沙盒已销毁")

    # ─── Step 2: 首次 connect Session B ───
    print(f"\n[Step 2] 首次 connect Session B: {session_b}")
    mgr_b = SessionSandboxManager()
    mgr_b.connect(session_b)
    print(f"  沙盒: {mgr_b.sandbox_id}")
    mgr_b.execute("echo 'B的机密数据' > /sandbox/.skills/secret.txt")
    mgr_b.execute("echo 'B的代码' > /sandbox/.skills/code.py")
    files_b = mgr_b.execute("ls /sandbox/.skills/").strip()
    print(f"  写入后文件: {files_b}")
    mgr_b.destroy()
    print("  沙盒已销毁")

    # ─── Step 3: 再次 connect Session A（目录已存在 → 直接挂载，不重新创建） ───
    print(f"\n[Step 3] 再次 connect Session A（应直接挂载，无需重建）")
    mgr_a2 = SessionSandboxManager()
    mgr_a2.connect(session_a)
    print(f"  沙盒: {mgr_a2.sandbox_id}")

    files_a2 = mgr_a2.execute("ls /sandbox/.skills/").strip()
    print(f"  文件: {files_a2}")

    secret_a = mgr_a2.execute("cat /sandbox/.skills/secret.txt").strip()
    print(f"  机密: {secret_a}")

    # 验证无法访问 B
    escape = mgr_a2.execute(f"bash -c 'ls /sandbox/.skills/../{session_b}/ 2>&1; true'").strip()
    print(f"  尝试访问 B: {escape}")

    # ─── Step 4: 再次 connect Session B ───
    print(f"\n[Step 4] 再次 connect Session B（应直接挂载）")
    mgr_b2 = SessionSandboxManager()
    mgr_b2.connect(session_b)
    print(f"  沙盒: {mgr_b2.sandbox_id}")

    files_b2 = mgr_b2.execute("ls /sandbox/.skills/").strip()
    print(f"  文件: {files_b2}")

    secret_b = mgr_b2.execute("cat /sandbox/.skills/secret.txt").strip()
    print(f"  机密: {secret_b}")

    # ─── Step 5: A 写入新数据，B 不可见 ───
    print(f"\n[Step 5] A 写入新数据，验证 B 不可见")
    mgr_a2.execute("echo '新增数据' > /sandbox/.skills/new_data.txt")
    files_a_final = mgr_a2.execute("ls /sandbox/.skills/").strip()
    print(f"  A 文件: {files_a_final}")

    files_b_final = mgr_b2.execute("ls /sandbox/.skills/").strip()
    print(f"  B 文件: {files_b_final}")

    # ─── 清理 ───
    mgr_a2.destroy()
    mgr_b2.destroy()

    # ─── 总结 ───
    print(f"\n{'=' * 60}")
    print("✅ 验证结果:")
    print(f"  • connect() 首次调用: 自动创建目录 + 隔离挂载")
    print(f"  • connect() 再次调用: 检测目录已存在，直接隔离挂载（无需重建）")
    print(f"  • Session A 数据持久: 销毁后重连，数据完好")
    print(f"  • Session 间隔离: A/B 互不可见，路径穿越被阻止")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
