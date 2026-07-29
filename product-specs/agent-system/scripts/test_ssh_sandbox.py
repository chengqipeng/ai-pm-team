"""
SSH Sandbox 快速验证脚本

验证 SSH Backend 能否正常连接到远程虚拟机并执行命令。

使用方式:
  python scripts/test_ssh_sandbox.py

环境变量（或在 .env 中配置）:
  SANDBOX_SSH_HOST=172.17.2.118
  SANDBOX_SSH_USER=hermes
  SANDBOX_SSH_KEY=~/.ssh/hermes_vm_key
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.tools.sandbox import SSHBackend, TerminalTool, ReadFileTool, WriteFileTool, CodeExecutionTool
from src.tools.sandbox.backend_base import BackendConfig


async def main():
    print("=" * 60)
    print("  SSH Sandbox 连接验证")
    print("=" * 60)

    # 配置
    config = BackendConfig(
        backend_type="ssh",
        ssh_host=os.environ.get("SANDBOX_SSH_HOST", "172.17.2.118"),
        ssh_user=os.environ.get("SANDBOX_SSH_USER", "hermes"),
        ssh_key=os.environ.get("SANDBOX_SSH_KEY", os.path.expanduser("~/.ssh/hermes_vm_key")),
        ssh_port=int(os.environ.get("SANDBOX_SSH_PORT", "22")),
        timeout=30,
    )

    print(f"\n目标: {config.ssh_user}@{config.ssh_host}:{config.ssh_port}")
    print(f"密钥: {config.ssh_key}")

    # 创建后端
    backend = SSHBackend(config)

    # 测试 1: 连接
    print("\n--- 测试 1: SSH 连接 ---")
    try:
        await backend.connect()
        print("✅ 连接成功")
    except Exception as e:
        print(f"❌ 连接失败: {e}")
        return

    # 测试 2: Terminal Tool
    print("\n--- 测试 2: Terminal (whoami && hostname) ---")
    terminal = TerminalTool(backend)
    result = await terminal.call({"command": "whoami && hostname && uname -a"})
    print(f"{'✅' if not result.is_error else '❌'} {result.content}")

    # 测试 3: Write File
    print("\n--- 测试 3: Write File ---")
    write_tool = WriteFileTool(backend)
    result = await write_tool.call({
        "path": "/tmp/hermes_test.txt",
        "content": "Hello from Agent System!\nThis is a test file.",
    })
    print(f"{'✅' if not result.is_error else '❌'} {result.content}")

    # 测试 4: Read File
    print("\n--- 测试 4: Read File ---")
    read_tool = ReadFileTool(backend)
    result = await read_tool.call({"path": "/tmp/hermes_test.txt"})
    print(f"{'✅' if not result.is_error else '❌'} {result.content}")

    # 测试 5: Execute Code
    print("\n--- 测试 5: Execute Python Code ---")
    code_tool = CodeExecutionTool(backend)
    result = await code_tool.call({
        "language": "python",
        "code": "import platform\nprint(f'Python on {platform.node()}: {platform.python_version()}')",
    })
    print(f"{'✅' if not result.is_error else '❌'} {result.content}")

    # 测试 6: Search Files
    print("\n--- 测试 6: Search Files ---")
    from src.tools.sandbox import SearchFilesTool
    search_tool = SearchFilesTool(backend)
    result = await search_tool.call({
        "pattern": "Hello",
        "path": "/tmp/",
        "include": "*.txt",
    })
    print(f"{'✅' if not result.is_error else '❌'} {result.content}")

    # 清理
    print("\n--- 清理 ---")
    await backend.execute("rm -f /tmp/hermes_test.txt")
    await backend.disconnect()
    print("✅ 清理完成，连接已断开")

    print("\n" + "=" * 60)
    print("  所有测试通过！SSH Sandbox 工作正常。")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
