"""业务域服务 Provider Demo — 主入口"""
from fastapi import FastAPI

from app.registry_setup import registry
from app.routes import router

app = FastAPI(title="Neo AI Provider Demo (Sales Domain)", version="0.1.0")
app.include_router(router)


@app.get("/health")
def health():
    return {"status": "ok", "domain": registry.domain, "registered": registry.summary()}
