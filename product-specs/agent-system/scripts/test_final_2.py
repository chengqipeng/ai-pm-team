"""验证第 9、10 项测试"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.tools.sandbox import SSHBackend, TerminalTool, CodeExecutionTool
from src.tools.sandbox.backend_base import BackendConfig


async def main():
    config = BackendConfig(
        ssh_host="172.17.2.118",
        ssh_user="hermes",
        ssh_key=os.path.expanduser("~/.ssh/hermes_vm_key"),
        timeout=15,
    )
    backend = SSHBackend(config)
    terminal = TerminalTool(backend)
    code_exec = CodeExecutionTool(backend)

    # ⑨ execute_code: 验证 Python 环境完整性
    print("\n⑨ execute_code: Python 环境验证")
    r = await code_exec.call({
        "language": "python",
        "code": "import os, sys, json\nprint(json.dumps({'python': sys.version, 'user': os.getenv('USER','?')}))",
    })
    ok = not r.is_error and "python" in r.content
    print(f"   {'✅' if ok else '❌'} {r.content.strip()}")

    # ⑩ terminal: 多命令组合（创建+写入+执行+清理）
    print("\n⑩ terminal: 多命令组合验证")
    r = await terminal.call({
        "command": "echo 'print(2+2)' > /tmp/calc.py && python3 /tmp/calc.py && rm /tmp/calc.py && echo DONE"
    })
    ok = not r.is_error and "4" in r.content and "DONE" in r.content
    print(f"   {'✅' if ok else '❌'} {r.content.strip()}")

    await backend.disconnect()
    print("\n完成！")


if __name__ == "__main__":
    asyncio.run(main())
