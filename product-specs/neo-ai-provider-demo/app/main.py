"""业务域服务 Provider Demo — 主入口（带 Eureka 注册）"""
from fastapi import FastAPI

from app.registry_setup import registry
from app.routes import router
from app.eureka_setup import register, deregister

app = FastAPI(title="Neo AI Provider Demo (Sales Domain)", version="0.1.0")
app.include_router(router)


@app.on_event("startup")
async def startup():
    await register()


@app.on_event("shutdown")
async def shutdown():
    await deregister()


@app.get("/health")
def health():
    return {"status": "ok", "domain": registry.domain, "registered": registry.summary()}
