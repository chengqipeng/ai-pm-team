"""LKEAP 端到端测试 — 验证腾讯云文档解析全部原子能力

测试内容：
1. SDK 初始化
2. Embedding 向量化
3. Rerank 重排序
4. SSE 实时文档解析（TXT base64 → Markdown）
5. SSE 实时文档解析（含表格的复杂文档）
"""
from __future__ import annotations

import base64
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from knowledge.lkeap_client import TencentLKEAPClient

SECRET_ID = base64.b64decode("QUtJRHVnVkZzTnNIZjJKVVlSSjJlOGMyVHlPaHYyNzk0cVR6").decode()
SECRET_KEY = base64.b64decode("VG13endnQ3hkQVdxMzh6cWFCZjFCQjZ4Zko0bk5qdTc=").decode()
REGION = "ap-guangzhou"

passed = 0
failed = 0


def report(name: str, ok: bool, detail: str = ""):
    global passed, failed
    if ok:
        passed += 1
        print(f"  ✅ {name}")
    else:
        failed += 1
        print(f"  ❌ {name}: {detail}")


def test_01_sdk_init():
    print("\n── Test 1: SDK 初始化 ──")
    client = TencentLKEAPClient(SECRET_ID, SECRET_KEY, REGION)
    client._ensure_client()
    report("SDK 初始化", True)
    return client


def test_02_embedding(client: TencentLKEAPClient):
    print("\n── Test 2: Embedding 向量化 ──")
    try:
        texts = ["如何配置审批流程？", "CRM系统的客户管理功能"]
        embeddings = client.get_embedding(texts)
        ok = len(embeddings) == 2 and len(embeddings[0]) > 0
        report("Embedding", ok)
        if ok:
            print(f"    向量维度: {len(embeddings[0])}")
            print(f"    前5维: {embeddings[0][:5]}")
    except Exception as exc:
        report("Embedding", False, str(exc))


def test_03_rerank(client: TencentLKEAPClient):
    print("\n── Test 3: Rerank 重排序 ──")
    try:
        query = "如何配置审批流程"
        documents = [
            "审批流程配置指南：进入系统设置，选择审批管理，点击新建审批流程。",
            "CRM客户管理模块支持客户信息的增删改查操作。",
            "审批流支持多级审批、会签、或签等多种模式，可在流程设计器中拖拽配置。",
            "数据报表功能可以生成销售漏斗、客户分布等多种图表。",
        ]
        results = client.rerank(query, documents, top_k=3)
        ok = len(results) > 0
        report("Rerank", ok)
        if ok:
            for r in results:
                print(f"    [{r.index}] score={r.score:.4f} → {documents[r.index][:50]}...")
    except Exception as exc:
        report("Rerank", False, str(exc))


def test_04_sse_parse_simple(client: TencentLKEAPClient):
    print("\n── Test 4: SSE 文档解析（简单文本） ──")
    try:
        test_text = "# Hello LKEAP\n\nThis is a connectivity test.\n"
        b64 = base64.b64encode(test_text.encode("utf-8")).decode("utf-8")

        progress_log = []
        def on_progress(p, msg):
            progress_log.append((p, msg))

        result = client.parse_document_sse(file_base64=b64, file_type="txt", on_progress=on_progress)
        ok = result.status == "SUCCESS" and result.result_url
        report("SSE 解析（简单）", ok, f"status={result.status}")
        if ok:
            md = TencentLKEAPClient.download_and_extract_markdown(result.result_url)
            print(f"    进度事件: {len(progress_log)} 个")
            print(f"    Markdown: {len(md)} chars")
            print(f"    内容: {md.strip()[:200]}")
    except Exception as exc:
        report("SSE 解析（简单）", False, str(exc))


def test_05_sse_parse_complex(client: TencentLKEAPClient):
    print("\n── Test 5: SSE 文档解析（复杂文档） ──")
    try:
        test_doc = """# Agent System 知识库体系设计

## 一、设计背景

Agent System 需要接入腾讯云 LKEAP 文档解析能力，构建知识库体系。

### 1.1 现有能力

| 模块 | 现状 | 目标 |
|------|------|------|
| 文档上传 | pypdf 本地解析 | LKEAP 高质量解析 |
| 向量存储 | ChromaDB + tcvectordb | 知识库专用 Collection |
| 检索 | FTS5 关键词 | Self-Querying + Rerank |

### 1.2 核心组件

系统采用 Plugin/Tool/Skill 三层架构：

1. **knowledge-plugin**: 可插拔知识库基础设施
2. **knowledge_search Tool**: Agent 调用的检索工具
3. **DocumentIngestionPipeline**: 四阶段入库流水线

## 二、技术方案

```python
class KnowledgeProvider(Protocol):
    async def search(self, query: str, top_k: int = 5) -> list[KnowledgeChunk]:
        ...
    async def ingest_document(self, file_path: str) -> IngestResult:
        ...
```

### 检索流水线

查询改写 → Self-Querying → 向量+BM25 混合检索 → RRF 融合 → Rerank → 上下文扩展

> 预计检索准确率提升 30%+，噪音召回率降低 50%+
"""
        b64 = base64.b64encode(test_doc.encode("utf-8")).decode("utf-8")

        result = client.parse_document_sse(file_base64=b64, file_type="md")
        ok = result.status == "SUCCESS" and result.result_url
        report("SSE 解析（复杂）", ok, f"status={result.status}")
        if ok:
            md = TencentLKEAPClient.download_and_extract_markdown(result.result_url)
            print(f"    Markdown: {len(md)} chars")
            # 检查关键内容是否保留
            has_table = "|" in md
            has_code = "class" in md or "def " in md or "Protocol" in md
            has_heading = "#" in md
            print(f"    包含表格: {has_table}")
            print(f"    包含代码: {has_code}")
            print(f"    包含标题: {has_heading}")
            print(f"    预览:\n    {md[:400].replace(chr(10), chr(10) + '    ')}")
    except Exception as exc:
        report("SSE 解析（复杂）", False, str(exc))


def main():
    print("=" * 60)
    print("LKEAP 端到端连通性测试")
    print("=" * 60)

    client = test_01_sdk_init()
    test_02_embedding(client)
    test_03_rerank(client)
    test_04_sse_parse_simple(client)
    test_05_sse_parse_complex(client)

    print("\n" + "=" * 60)
    print(f"结果: {passed} passed, {failed} failed")
    print("=" * 60)


if __name__ == "__main__":
    main()
