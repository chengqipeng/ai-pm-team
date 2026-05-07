# 知识库模块 — 集成指南

本模块实现了 `doc/知识库体系设计方案.md` 中的完整知识库能力。

## 模块地图

```
src/knowledge/
├── __init__.py              # 统一导出
├── factory.py               # 🚪 组装工厂：build_knowledge_provider(settings, llm)
│
├── lkeap_client.py          # 腾讯云 LKEAP API 封装（解析+切分+Embedding+Rerank）
├── vdb_writer.py            # KnowledgeVectorStore：tcvectordb 封装（多租户 FilterIndex 隔离）
│
├── cleaning.py              # DocumentCleaningService：4 Stage 文本清洗
├── quality.py               # DocumentQualityScorer：4 信号综合评分
│
├── guard.py                 # IngestionGuard：file_hash 去重 + LKEAP 并发限流
├── queue.py                 # PgIngestQueue + IngestTask（FOR UPDATE SKIP LOCKED）
├── worker.py                # IngestSupervisor + IngestWorker + Reclaimer 协程池
│
├── provider.py              # KnowledgeProvider 协议 + 数据模型
├── ingestion.py             # DocumentIngestionPipeline：5 阶段入库流水线
├── retriever.py             # KnowledgeRetriever：Self-Querying + 混合检索 + Rerank
└── standalone_provider.py   # StandaloneKnowledgeProvider：完整 Provider 实现
```

## 快速集成（3 步）

### 1. 建表

```bash
psql -U postgres -d paas_db -f sql/init_knowledge_tables.sql
```

### 2. 配置

在应用的 `YAML` / 环境变量中设置 `KnowledgeSettings`：

```python
from src.config.models import KnowledgeSettings

settings = KnowledgeSettings(
    enabled=True,
    lkeap_secret_id="AKID***",
    lkeap_secret_key="***",
    lkeap_region="ap-guangzhou",
    vdb_url="http://10.60.2.17",
    vdb_key="***",
    vdb_database="knowledge",
    embedding_dim=1024,
    upload_dir="./data/knowledge/uploads",
    parsed_dir="./data/knowledge/parsed",
    ingest_worker_count=4,
)
```

### 3. 启动 + 注入

```python
from src.knowledge import build_knowledge_provider

# 应用启动时
provider, supervisor = build_knowledge_provider(settings, llm=my_llm)
await supervisor.start()

# 注入给 Agent（通过 langgraph config）
agent_config = {
    "configurable": {
        "knowledge_provider": provider,
        "tenant_id": tenant_id,
        "agent_name": "CRM-Agent",
        "user_id": user_id,
        "thread_id": thread_id,
    }
}

# 注册 Tool
from src.tools.builtins.knowledge_tool import KnowledgeSearchTool
tool_registry.register(KnowledgeSearchTool())

# 应用退出时
await supervisor.stop()
```

## API 使用示例

### 用户上传文档

```python
result = await provider.ingest_document(
    tenant_id=1001,
    knowledge_base_id=2001,
    file_path="/tmp/产品手册.pdf",
    file_name="产品手册_v2.pdf",
    user_metadata={"title": "2024 年产品手册"},
)
# result.task_id: "kbi_abc123..."  → 给前端用于轮询进度
# result.doc_id:  "doc_xyz789..."   → 永久文档 ID
```

### 查询入库进度

```python
status = await provider.get_ingest_status(result.task_id)
# {
#   "task_id": "kbi_abc123...",
#   "queue_status": "running",        # pending / running / success / failed / dead
#   "doc_id": "doc_xyz789...",
#   "phase": "cleaning",              # upload/parsing/cleaning/tagging/splitting/indexing/done
#   "progress": 40,                   # 0 ~ 100
#   "quality_score": 0.0,             # 打分完成后才有
#   "chunk_count": 0,
#   "error_message": ""
# }
```

### Agent 检索（自动通过 Tool）

```text
User: 帮我找下制造业的成功案例

Agent 调用 knowledge_search(query="制造业的成功案例")
→ Self-Querying 识别过滤条件 {docCategory: "成功案例", industryVertical: "制造业"}
→ VDB 混合检索（向量 + BM25）
→ LKEAP Rerank 精排
→ Parent-Child 扩展前后切片
→ 返回 Top-5 相关文档
```

## 架构特点

| 特性 | 实现方式 |
|:---|:---|
| 无 Redis 依赖 | PG 行锁（`FOR UPDATE NOWAIT`）替代 Redis 锁 |
| 无 MQ 依赖 | PG 任务队列（`FOR UPDATE SKIP LOCKED`）替代 MQ |
| 多租户隔离 | VDB 共享库 + `tenant_id` FilterIndex 强制注入 |
| 幂等入库 | `uk_doc_hash` 唯一索引 + `IngestionGuard.check_duplicate` |
| 失败自动重试 | 指数退避（2^retry × 60s），耗尽进死信 |
| 崩溃恢复 | `Reclaimer` 定时扫描 running 超时任务复位 |
| 双层文本 | `display_content`（保留排版）+ `content`（喂 Embedding） |
| 两级切片 | Segment（章节级）+ Chunk（切片级），Parent-Child 扩展 |

## 测试

```bash
# 单元测试（不依赖 PG/VDB/LKEAP）
python tests/test_knowledge_unit.py

# LKEAP 端到端（需真实密钥）
python tests/test_lkeap_e2e.py
```

## 设计文档

完整设计见 `doc/知识库体系设计方案.md`。
