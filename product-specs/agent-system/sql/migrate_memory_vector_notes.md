# 向量库数据清理

## 清理脚本

```python
async def cleanup_vector_categories(vdb):
    """删除向量库中已废弃分类的数据"""
    for old_cat in ("events", "cases", "patterns"):
        docs = await vdb.query_by_filter(f'category = "{old_cat}"', limit=1000)
        if docs:
            ids = [doc["id"] for doc in docs if doc.get("id")]
            await vdb.delete(ids)
            print(f"Deleted {len(ids)} docs with category={old_cat}")
```

## 注意
- soul/tools/skills 不在向量库中（存 PG），无需处理
- 清理后向量库只剩 entities 和 preferences 两类
