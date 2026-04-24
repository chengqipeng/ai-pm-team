"""本地调试启动入口 — 直接 F5 / Run 即可 debug server.py

用法:
  1. VS Code / Kiro: F5 启动调试（需配合 launch.json）
  2. 命令行: python run_server.py
  3. 指定端口: python run_server.py --port 8002
  4. 指定 host: python run_server.py --host 127.0.0.1 --port 8001
"""
import argparse
import os
import sys

# 确保项目根目录在 sys.path 中
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# 默认环境变量
os.environ.setdefault("DOUBAO_API_KEY", "651621e7-e495-4728-93ef-ed380e9ddcd1")


def main():
    parser = argparse.ArgumentParser(description="DeepAgent Debug Server")
    parser.add_argument("--host", default="0.0.0.0", help="绑定地址 (默认 0.0.0.0)")
    parser.add_argument("--port", type=int, default=8001, help="端口 (默认 8001)")
    parser.add_argument("--reload", action="store_true", help="启用热重载")
    args = parser.parse_args()

    import uvicorn
    uvicorn.run(
        "server:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level="info",
    )


if __name__ == "__main__":
    main()
