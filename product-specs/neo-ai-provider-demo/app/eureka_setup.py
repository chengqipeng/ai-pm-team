"""Eureka 注册 — Provider Demo 启动时注册到 Eureka"""
import py_eureka_client.eureka_client as eureka_client

EUREKA_URL = "https://admin:AdminEureka1234@discovery-dev.ingageapp.com/eureka/"
APP_NAME = "neo-ai-provider-demo"
PORT = 8002


async def register():
    await eureka_client.init_async(
        eureka_server=EUREKA_URL,
        app_name=APP_NAME,
        instance_port=PORT,
        renewal_interval_in_secs=5,
        duration_in_secs=15,
    )


async def deregister():
    await eureka_client.stop_async()
