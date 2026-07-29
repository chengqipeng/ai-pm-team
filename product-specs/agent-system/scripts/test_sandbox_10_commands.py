"""
沙盒工具 10 项综合验证 — 模拟 Agent 实际调用场景

覆盖: terminal / write_file / read_file / execute_code / search_files
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.tools.sandbox import SSHBackend, TerminalTool, ReadFileTool, WriteFileTool, SearchFilesTool, CodeExecutionTool
from src.tools.sandbox.backend_base import BackendConfig


async def main():
    config = BackendConfig(
        backend_type="ssh",
        ssh_host=os.environ.get("SANDBOX_SSH_HOST", "172.17.2.118"),
        ssh_user=os.environ.get("SANDBOX_SSH_USER", "hermes"),
        ssh_key=os.environ.get("SANDBOX_SSH_KEY", os.path.expanduser("~/.ssh/hermes_vm_key")),
        ssh_port=22,
        timeout=30,
    )

    backend = SSHBackend(config)
    terminal = TerminalTool(backend)
    write_file = WriteFileTool(backend)
    read_file = ReadFileTool(backend)
    code_exec = CodeExecutionTool(backend)
    search = SearchFilesTool(backend)

    results = []

    print("=" * 60)
    print("  沙盒工具 10 项综合验证")
    print("=" * 60)

    # ① terminal: 查看系统信息
    print("\n① terminal: 查看系统信息")
    r = await terminal.call({"command": "uname -a && df -h / | tail -1"})
    ok = not r.is_error
    results.append(("terminal: 系统信息", ok))
    print(f"   {'✅' if ok else '❌'} {r.content[:100]}")

    # ② terminal: 创建项目目录
    print("\n② terminal: 创建项目目录")
    r = await terminal.call({"command": "mkdir -p /tmp/agent-test/src && ls -la /tmp/agent-test/"})
    ok = not r.is_error
    results.append(("terminal: 创建目录", ok))
    print(f"   {'✅' if ok else '❌'} {r.content[:100]}")

    # ③ write_file: 写入 Python 脚本
    print("\n③ write_file: 写入 Python 脚本")
    code = '''import json
import platform
import os

info = {
    "hostname": platform.node(),
    "python": platform.python_version(),
    "user": os.environ.get("USER", "unknown"),
    "cwd": os.getcwd(),
}
print(json.dumps(info, indent=2))
'''
    r = await write_file.call({"path": "/tmp/agent-test/src/info.py", "content": code})
    ok = not r.is_error
    results.append(("write_file: Python 脚本", ok))
    print(f"   {'✅' if ok else '❌'} {r.content}")

    # ④ write_file: 写入配置文件
    print("\n④ write_file: 写入配置文件")
    config_content = '''[app]
name = agent-test
version = 1.0.0
debug = true

[database]
host = localhost
port = 5432
'''
    r = await write_file.call({"path": "/tmp/agent-test/config.ini", "content": config_content})
    ok = not r.is_error
    results.append(("write_file: 配置文件", ok))
    print(f"   {'✅' if ok else '❌'} {r.content}")

    # ⑤ read_file: 读取刚写入的脚本
    print("\n⑤ read_file: 读取 Python 脚本")
    r = await read_file.call({"path": "/tmp/agent-test/src/info.py"})
    ok = not r.is_error and "platform" in r.content
    results.append(("read_file: 读取脚本", ok))
    print(f"   {'✅' if ok else '❌'} 内容长度: {len(r.content)} 字符, 包含 'platform': {'platform' in r.content}")

    # ⑥ execute_code: 运行 Python 脚本
    print("\n⑥ execute_code: 运行 Python")
    r = await code_exec.call({
        "language": "python",
        "code": "import platform; print(f'Hello from {platform.node()}, Python {platform.python_version()}')",
    })
    ok = not r.is_error and "Hello from" in r.content
    results.append(("execute_code: Python", ok))
    print(f"   {'✅' if ok else '❌'} {r.content.strip()}")

    # ⑦ execute_code: 运行 Bash 脚本
    print("\n⑦ execute_code: 运行 Bash")
    r = await code_exec.call({
        "language": "bash",
        "code": "echo \"Files in /tmp/agent-test:\"\nfind /tmp/agent-test -type f | sort",
    })
    ok = not r.is_error and "agent-test" in r.content
    results.append(("execute_code: Bash", ok))
    print(f"   {'✅' if ok else '❌'} {r.content.strip()}")

    # ⑧ search_files: 搜索文件内容
    print("\n⑧ search_files: 搜索 'debug'")
    r = await search.call({"pattern": "debug", "path": "/tmp/agent-test/"})
    ok = not r.is_error and "debug" in r.content.lower()
    results.append(("search_files: 搜索内容", ok))
    print(f"   {'✅' if ok else '❌'} {r.content.strip()}")

    # ⑨ terminal: 安装 pip 包并验证
    print("\n⑨ terminal: pip install + import 验证")
    r = await terminal.call({"command": "pip3 install --user requests 2>&1 | tail -3 && python3 -c 'import requests; print(f\"requests {requests.__version__} OK\")'"})
    ok = not r.is_error and "OK" in r.content
    results.append(("terminal: pip install", ok))
    print(f"   {'✅' if ok else '❌'} {r.content.strip()[-80:]}")

    # ⑩ terminal: 清理并验证
    print("\n⑩ terminal: 清理测试目录")
    r = await terminal.call({"command": "rm -rf /tmp/agent-test && test ! -d /tmp/agent-test && echo 'CLEANED'"})
    ok = not r.is_error and "CLEANED" in r.content
    results.append(("terminal: 清理", ok))
    print(f"   {'✅' if ok else '❌'} {r.content.strip()}")

    # 汇总
    await backend.disconnect()

    print("\n" + "=" * 60)
    print("  测试结果汇总")
    print("=" * 60)
    passed = sum(1 for _, ok in results if ok)
    for name, ok in results:
        print(f"  {'✅' if ok else '❌'} {name}")
    print(f"\n  通过: {passed}/10")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
