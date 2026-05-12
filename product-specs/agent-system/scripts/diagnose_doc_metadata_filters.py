"""诊断脚本：检查 kb_doc_metadata 集合中文档的 FilterIndex 字段值

用途：当 Self-Querying 提取了 filter 但路B返回 0 结果时，
     用此脚本验证 VDB 中文档的实际字段值是否与 filter 匹配。

用法：
    python scripts/diagnose_doc_metadata_filters.py \
        --tenant_id 123456 \
        --kb_id 328462335922409472

输出：
    1. 该知识库所有文档的 doc_category / industry / business_stage 等字段值
    2. 与期望 filter 值的匹配情况
    3. 可能的不匹配原因
"""
from __future__ import annotations

import argparse
import json
import os
import sys

# 添加项目根目录到 path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def main():
    parser = argparse.ArgumentParser(description="诊断 kb_doc_metadata 的 FilterIndex 字段值")
    parser.add_argument("--tenant_id", required=True, help="租户 ID")
    parser.add_argument("--kb_id", required=True, help="知识库 ID")
    parser.add_argument("--filter_field", default=None, help="要检查的字段名（如 doc_category）")
    parser.add_argument("--filter_value", default=None, help="期望的字段值（如 产品手册）")
    args = parser.parse_args()

    from src.knowledge.vdb_writer import KnowledgeVectorStore

    # 初始化 VDB 连接
    vdb = KnowledgeVectorStore(
        url=os.environ.get("TCVDB_URL", ""),
        api_key=os.environ.get("TCVDB_API_KEY", ""),
        database_name=os.environ.get("TCVDB_DATABASE", "knowledge"),
    )
    vdb._ensure_collections()

    from tcvectordb.model.document import Filter

    # 1. 查询该知识库所有文档的元数据字段
    filter_expr = (
        f'tenant_id = "{args.tenant_id}" '
        f'and knowledge_base_id = "{args.kb_id}" '
        f'and status = "active"'
    )
    print(f"\n{'='*60}")
    print(f"诊断 kb_doc_metadata FilterIndex 字段")
    print(f"{'='*60}")
    print(f"tenant_id:        {args.tenant_id}")
    print(f"knowledge_base_id: {args.kb_id}")
    print(f"基础 filter:       {filter_expr}")
    print(f"{'='*60}\n")

    try:
        results = vdb._doc_meta_coll.query(
            filter=Filter(filter_expr),
            output_fields=[
                "id", "tenant_id", "knowledge_base_id",
                "doc_category", "industry", "business_stage",
                "target_audience", "product_service",
                "title", "status",
            ],
            limit=100,
        )
    except Exception as exc:
        print(f"❌ VDB 查询失败: {exc}")
        return

    if isinstance(results, list):
        docs = results
    else:
        docs = vdb._parse_results(results)

    if not docs:
        print("❌ 该知识库在 VDB kb_doc_metadata 中无任何文档！")
        print("   可能原因：")
        print("   1. 文档入库流水线未完成 Phase 4b（文档元数据索引）")
        print("   2. tenant_id 或 knowledge_base_id 不匹配")
        print("   3. VDB 集合被清空")
        return

    print(f"✅ 找到 {len(docs)} 个文档\n")

    # 2. 展示每个文档的 FilterIndex 字段值
    print(f"{'doc_id':<40} {'title':<30} {'doc_category':<15} {'industry':<15} {'business_stage':<15}")
    print("-" * 115)

    field_values = {
        "doc_category": set(),
        "industry": set(),
        "business_stage": set(),
        "target_audience": set(),
        "product_service": set(),
    }

    for doc in docs:
        doc_id = doc.get("id", "?")
        title = (doc.get("title") or "")[:28]
        dc = doc.get("doc_category") or "(空)"
        ind = doc.get("industry") or "(空)"
        bs = doc.get("business_stage") or "(空)"

        print(f"{doc_id:<40} {title:<30} {dc:<15} {ind:<15} {bs:<15}")

        for field in field_values:
            val = doc.get(field)
            if val:
                field_values[field].add(val)

    # 3. 汇总所有字段的唯一值
    print(f"\n{'='*60}")
    print("字段值汇总（VDB 中实际存储的值）")
    print(f"{'='*60}")
    for field, values in field_values.items():
        if values:
            print(f"  {field}: {sorted(values)}")
        else:
            print(f"  {field}: (全部为空 — 文档未被打标)")

    # 4. 如果指定了期望值，检查匹配情况
    if args.filter_field and args.filter_value:
        print(f"\n{'='*60}")
        print(f"匹配检查: {args.filter_field} = \"{args.filter_value}\"")
        print(f"{'='*60}")

        matched = [
            doc for doc in docs
            if doc.get(args.filter_field) == args.filter_value
        ]
        print(f"  匹配文档数: {len(matched)} / {len(docs)}")

        if not matched:
            actual_values = field_values.get(args.filter_field, set())
            print(f"\n  ❌ 无匹配！VDB 中该字段的实际值为: {sorted(actual_values) if actual_values else '(全部为空)'}")
            print(f"  期望值: \"{args.filter_value}\"")
            if actual_values:
                # 检查是否是大小写/空格/同义词问题
                for av in actual_values:
                    if args.filter_value.lower() in av.lower() or av.lower() in args.filter_value.lower():
                        print(f"  ⚠️ 可能的近似匹配: \"{av}\" ≈ \"{args.filter_value}\"")
            print(f"\n  可能原因:")
            print(f"    1. LLM 打标时输出了不同的分类值（如\"技术手册\"而非\"产品手册\"）")
            print(f"    2. Schema 枚举值与 LLM 输出不一致")
            print(f"    3. 文档入库时 LLM 不可用，打标被跳过（metadata 为空）")
            print(f"    4. VDB 写入时 doc_category/industry 字段未正确传入")

    # 5. 尝试用带 filter 的条件查询，验证 VDB filter 是否工作
    if args.filter_field and args.filter_value:
        print(f"\n{'='*60}")
        print(f"VDB Filter 验证")
        print(f"{'='*60}")

        test_filter = (
            f'{filter_expr} and {args.filter_field} = "{args.filter_value}"'
        )
        print(f"  测试 filter: {test_filter}")

        try:
            test_results = vdb._doc_meta_coll.query(
                filter=Filter(test_filter),
                output_fields=["id", "doc_category", "industry"],
                limit=10,
            )
            if isinstance(test_results, list):
                test_docs = test_results
            else:
                test_docs = vdb._parse_results(test_results)
            print(f"  结果: {len(test_docs)} 个文档")
            if test_docs:
                for td in test_docs:
                    print(f"    - {td.get('id')}: dc={td.get('doc_category')}, ind={td.get('industry')}")
        except Exception as exc:
            print(f"  ❌ 查询失败: {exc}")


if __name__ == "__main__":
    main()
