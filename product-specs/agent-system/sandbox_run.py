"""
腾讯云 Agent Runtime 沙箱 - 执行 Python 脚本
"""
import os

os.environ["E2B_DOMAIN"] = "ap-beijing.tencentags.com"
os.environ["E2B_API_KEY"] = "ark_dGTlMcosC-n-ZNhfKyW8aBJm3c0KNLXzjSkT7t_3WWc"

from e2b import Sandbox

TEMPLATE = "code-sandbox"


def run_python_in_sandbox(code: str, timeout: int = 600):
    """在沙箱中执行 Python 脚本"""
    print(f"正在创建沙箱 (template={TEMPLATE})...")
    sandbox = Sandbox.create(template=TEMPLATE, timeout=3600)
    print(f"沙箱已创建: {sandbox.sandbox_id}")

    try:
        # 写入脚本文件
        sandbox.files.write("/tmp/script.py", code)

        # 执行脚本
        print("执行中...\n" + "=" * 40)
        result = sandbox.commands.run("python3 /tmp/script.py")
        print(result.stdout)
        if result.stderr:
            print(f"[stderr] {result.stderr}")
        print("=" * 40)
        return result
    finally:
        sandbox.kill()
        print("沙箱已销毁")


if __name__ == "__main__":
    python_code = """
import sys
import platform
from datetime import datetime

print(f"Python 版本: {sys.version}")
print(f"平台: {platform.platform()}")
print(f"当前时间: {datetime.now().isoformat()}")
print("Hello from Tencent Agent Sandbox!")

result = sum(range(1, 101))
print(f"1+2+...+100 = {result}")
"""
    run_python_in_sandbox(python_code)
