"""本地启动 MCP Demo — 使用 SDK 的 create_mcp_app(config_dir=...) + 绕过 Eureka 注册"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
# neo_ai_infr_basic 从 sys.argv[0] 所在目录找 resources/application.yml
os.chdir(os.path.join(os.path.dirname(os.path.abspath(__file__)), "app"))

from app.main import app
# 清除 Eureka startup（本地不需要注册）
app.router.on_startup.clear()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8003)
