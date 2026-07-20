"""数据存储层 — 从配置文件加载模拟数据（替代 MySQL）

生产环境：Tool handler 通过 NeoApiClient 调用后端服务（数据来自 MySQL）
Demo 环境：从 config/mock_data.yaml 加载模拟数据，提供查询能力

Usage:
    from app.data_store import data_store

    # 查询客户
    records = data_store.query("crm", "accounts", {"industry": "互联网"})

    # 搜索知识库
    results = data_store.search_knowledge("审批流", top_k=3)

    # 获取元数据
    entities = data_store.get_entities()
    fields = data_store.get_fields("account")
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

_DEFAULT_DATA_PATH = os.path.join(
    os.path.dirname(os.path.dirname(__file__)),
    "config", "mock_data.yaml",
)


class DataStore:
    """模拟数据存储 — 从 YAML 配置加载，提供类 DB 查询能力"""

    def __init__(self, data_path: str = ""):
        self._data: dict[str, Any] = {}
        self._path = data_path or _DEFAULT_DATA_PATH
        self._load()

    def _load(self):
        """加载配置文件"""
        path = Path(self._path)
        if not path.exists():
            logger.warning("模拟数据文件不存在: %s", self._path)
            return
        with open(path, encoding="utf-8") as f:
            self._data = yaml.safe_load(f) or {}
        logger.info("模拟数据加载完成: %s", list(self._data.keys()))

    # ═══════════════════════════════════════════════════════════
    # CRM 查询
    # ═══════════════════════════════════════════════════════════

    def query(self, domain: str, collection: str, conditions: dict[str, Any] | None = None, limit: int = 10) -> list[dict]:
        """通用查询 — 模拟 SQL SELECT

        Args:
            domain: 数据域（crm / knowledge / metadata）
            collection: 集合名（accounts / opportunities / contacts）
            conditions: 查询条件（字段名→值，模糊匹配）
            limit: 返回数量限制
        """
        records = self._data.get(domain, {}).get(collection, [])
        if not conditions:
            return records[:limit]

        # 简单过滤：所有条件 AND，字符串包含匹配
        filtered = []
        for record in records:
            match = True
            for key, value in conditions.items():
                record_val = str(record.get(key, ""))
                if str(value).lower() not in record_val.lower():
                    match = False
                    break
            if match:
                filtered.append(record)
        return filtered[:limit]

    def get_by_id(self, domain: str, collection: str, record_id: str) -> dict | None:
        """按 ID 查询单条记录"""
        records = self._data.get(domain, {}).get(collection, [])
        for record in records:
            if record.get("id") == record_id:
                return record
        return None

    # ═══════════════════════════════════════════════════════════
    # 知识库检索
    # ═══════════════════════════════════════════════════════════

    def search_knowledge(self, query: str, knowledge_base_id: str = "", top_k: int = 5) -> list[dict]:
        """知识库语义检索（模拟）— 关键词匹配

        Args:
            query: 检索关键词
            knowledge_base_id: 知识库 ID 过滤（可选）
            top_k: 返回条数
        """
        documents = self._data.get("knowledge", {}).get("documents", [])
        results = []
        for doc in documents:
            if knowledge_base_id and doc.get("knowledge_base") != knowledge_base_id:
                continue
            for chunk in doc.get("chunks", []):
                content = chunk.get("content", "")
                # 简单关键词匹配模拟语义检索
                if any(kw in content for kw in query):
                    results.append({
                        "doc_title": doc["doc_title"],
                        "chunk": content,
                        "score": chunk.get("score", 0.5),
                        "knowledge_base": doc.get("knowledge_base", ""),
                    })
        # 按 score 排序
        results.sort(key=lambda x: x["score"], reverse=True)
        return results[:top_k]

    def list_knowledge_bases(self) -> list[dict]:
        """列出知识库"""
        return self._data.get("knowledge", {}).get("knowledge_bases", [])

    # ═══════════════════════════════════════════════════════════
    # 元数据查询
    # ═══════════════════════════════════════════════════════════

    def get_entities(self) -> list[dict]:
        """获取所有实体"""
        return self._data.get("metadata", {}).get("entities", [])

    def get_fields(self, entity_api_key: str) -> list[dict]:
        """获取实体字段"""
        fields = self._data.get("metadata", {}).get("fields", {})
        return fields.get(entity_api_key, [])


# 全局单例
data_store = DataStore()
