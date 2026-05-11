#!/usr/bin/env python3
"""查询改写 + 关键词提取 — 逻辑准确性自动验证

验证范围：
1. QueryRewriter._clean_output() — 输出清洗逻辑
2. QueryRewriter 合理性校验（长度、句号数）
3. KeywordExtractor — TF-IDF / TextRank / Combined 提取
4. _extract_json_object — JSON 解析鲁棒性
5. 检索层 _local_keywords 与 KeywordExtractor 一致性对比
6. Self-Querying filter 构造逻辑

运行方式：
    python3 tests/verify_rewrite_and_keywords.py
"""
import sys
import os
import re
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ═══════════════════════════════════════════════════════════
# 测试计数器
# ═══════════════════════════════════════════════════════════
_pass = 0
_fail = 0
_errors = []


def check(name: str, condition: bool, detail: str = ""):
    global _pass, _fail
    if condition:
        _pass += 1
        print(f"  [PASS] {name}")
    else:
        _fail += 1
        msg = f"  [FAIL] {name}" + (f" — {detail}" if detail else "")
        print(msg)
        _errors.append(msg)


# ═══════════════════════════════════════════════════════════
# 1. QueryRewriter._clean_output 测试
# ═══════════════════════════════════════════════════════════
print("\n" + "=" * 70)
print("  1. QueryRewriter._clean_output() 输出清洗逻辑")
print("=" * 70)

from src.core.query_rewriter import QueryRewriter

clean = QueryRewriter._clean_output

# 1.1 前缀清洗
check("去除中文前缀'改写后的查询：'",
      clean("改写后的查询：华为ERP项目进展如何") == "华为ERP项目进展如何")
check("去除中文前缀'改写后：'",
      clean("改写后：查询本月业绩") == "查询本月业绩")
check("去除英文前缀'Query:'",
      clean("Query: what is the status") == "what is the status")
check("去除英文前缀'rewrite:'",
      clean("rewrite: check order status") == "check order status")

# 1.2 引号清洗
check("去除双引号包裹",
      clean('"华为ERP项目进展如何"') == "华为ERP项目进展如何")
check("去除中文引号包裹",
      clean("\u201c华为ERP项目进展如何\u201d") == "华为ERP项目进展如何")
check("去除单引号包裹",
      clean("'查询本月业绩'") == "查询本月业绩")
check("不去除非配对引号",
      clean('"华为ERP项目') == '"华为ERP项目')

# 1.3 标注清洗
check("去除实体标注",
      "实体" not in clean("华为ERP项目进展如何，实体：华为、ERP"))
check("去除代词标注",
      "代词" not in clean("华为ERP项目进展如何，代词指代已替换"))
check("去除意图分析标注",
      "意图" not in clean("查询华为ERP项目进展，意图分析：查询项目状态"))

# 1.4 空输入
check("空字符串返回空",
      clean("") == "")
check("纯空格返回空",
      clean("   ") == "")

# 1.5 正常输入不被误伤
check("正常查询不被修改",
      clean("帮我查一下华为的商机") == "帮我查一下华为的商机")
check("包含'实体'但不在标注位置不被误伤",
      "实体关系" in clean("帮我查实体关系图"))


# ═══════════════════════════════════════════════════════════
# 2. QueryRewriter 合理性校验逻辑
# ═══════════════════════════════════════════════════════════
print("\n" + "=" * 70)
print("  2. QueryRewriter 合理性校验逻辑")
print("=" * 70)

# 模拟 _rewrite_with_llm 中的校验逻辑
def validate_rewrite(rewritten: str, original: str = "测试查询") -> tuple[bool, str]:
    """模拟 QueryRewriter._rewrite_with_llm 中的校验"""
    rewritten = QueryRewriter._clean_output(rewritten)
    if not rewritten:
        return False, "空输出"
    if len(rewritten) > 150:
        return False, f"过长({len(rewritten)}字)"
    if rewritten.count("。") > 1:
        return False, f"多句号({rewritten.count('。')}个)"
    return True, "通过"

check("正常改写通过校验",
      validate_rewrite("华为ERP项目进展如何")[0])
check("空输出被拒绝",
      not validate_rewrite("")[0])
check("超长输出被拒绝(151字)",
      not validate_rewrite("华" * 151)[0])
check("150字刚好通过",
      validate_rewrite("华" * 150)[0])
check("多句号被拒绝",
      not validate_rewrite("华为ERP项目进展如何。目前在方案阶段。预计下月签约。")[0])
check("单句号通过",
      validate_rewrite("华为ERP项目进展如何。")[0])
check("无句号通过",
      validate_rewrite("华为ERP项目进展如何")[0])


# ═══════════════════════════════════════════════════════════
# 3. KeywordExtractor 关键词提取
# ═══════════════════════════════════════════════════════════
print("\n" + "=" * 70)
print("  3. KeywordExtractor 关键词提取")
print("=" * 70)

from src.knowledge.keyword_extract import KeywordExtractor

extractor = KeywordExtractor()

# 测试文本（模拟工业产品文档）
test_doc = """
罗斯蒙特3051压力变送器是一款高精度的工业测量仪表，广泛应用于石油化工、
电力、冶金等行业。该变送器采用HART通信协议，支持4-20mA模拟信号输出，
测量精度达到0.05%，量程范围从0.3kPa到68.9MPa。

产品特点：
- 10年稳定性，长期可靠运行
- 100:1量程比，灵活适应不同工况
- 通过IEC 61508标准SIL2安全认证
- 支持HART/FOUNDATION Fieldbus/Profibus PA多种通信协议
- 316L不锈钢材质，耐腐蚀

安装要求：
1. 安装位置应避免振动和高温
2. 引压管长度不超过15米
3. 法兰连接需使用指定扭矩
"""

# 3.1 TF-IDF 提取
keywords_tfidf = extractor.extract(test_doc, top_k=10)
print(f"  TF-IDF Top-10: {keywords_tfidf}")

check("TF-IDF 返回非空列表",
      len(keywords_tfidf) > 0)
check("TF-IDF 返回数量 <= top_k",
      len(keywords_tfidf) <= 10)
check("TF-IDF 包含核心产品词",
      any(w in " ".join(keywords_tfidf) for w in ["变送器", "压力", "罗斯蒙特", "3051"]))
check("TF-IDF 包含技术术语",
      any(w in " ".join(keywords_tfidf) for w in ["HART", "量程", "精度", "SIL2"]))
check("TF-IDF 不包含停用词'的'",
      "的" not in keywords_tfidf)
check("TF-IDF 不包含停用词'是'",
      "是" not in keywords_tfidf)
check("TF-IDF 不包含纯数字",
      not any(re.match(r"^[\d.,%]+$", w) for w in keywords_tfidf))

# 3.2 TextRank 提取
keywords_textrank = extractor.extract_with_textrank(test_doc, top_k=10)
print(f"  TextRank Top-10: {keywords_textrank}")

check("TextRank 返回非空列表",
      len(keywords_textrank) > 0)
check("TextRank 不包含停用词",
      not any(w in ["的", "了", "是", "在"] for w in keywords_textrank))

# 3.3 Combined 提取
keywords_combined = extractor.extract_combined(test_doc, top_k=20)
print(f"  Combined Top-20: {keywords_combined}")

check("Combined 返回非空列表",
      len(keywords_combined) > 0)
check("Combined 数量 <= top_k",
      len(keywords_combined) <= 20)
check("Combined 覆盖 TF-IDF 结果",
      len(set(keywords_tfidf[:5]) & set(keywords_combined)) >= 3,
      f"TF-IDF前5={keywords_tfidf[:5]} vs Combined={keywords_combined[:10]}")
check("Combined 无重复",
      len(keywords_combined) == len(set(keywords_combined)))

# 3.4 空输入
check("空文本返回空列表",
      extractor.extract("") == [])
check("纯空格返回空列表",
      extractor.extract("   ") == [])

# 3.5 短文本
short_text = "罗斯蒙特3051压力变送器"
keywords_short = extractor.extract(short_text, top_k=5)
print(f"  短文本关键词: {keywords_short}")
check("短文本能提取关键词",
      len(keywords_short) >= 1)

# 3.6 英文混合
mixed_text = "HART协议支持4-20mA信号输出，兼容Profibus PA和FOUNDATION Fieldbus"
keywords_mixed = extractor.extract(mixed_text, top_k=10)
print(f"  中英混合关键词: {keywords_mixed}")
check("中英混合能提取",
      len(keywords_mixed) >= 1)


# ═══════════════════════════════════════════════════════════
# 4. _extract_json_object JSON 解析鲁棒性
# ═══════════════════════════════════════════════════════════
print("\n" + "=" * 70)
print("  4. _extract_json_object JSON 解析鲁棒性")
print("=" * 70)

from src.knowledge.ingestion import _extract_json_object

# 4.1 标准 JSON
check("标准 JSON 解析",
      _extract_json_object('{"key": "value"}') == {"key": "value"})

# 4.2 带 markdown 代码块
check("markdown json 代码块",
      _extract_json_object('```json\n{"key": "value"}\n```') == {"key": "value"})

# 4.3 前后有文字
check("前后有文字的 JSON",
      _extract_json_object('这是结果：{"key": "value"} 以上是输出') == {"key": "value"})

# 4.4 嵌套 JSON
nested = '{"metadata": {"docCategory": "产品手册"}, "summary": "测试", "keywords": ["a", "b"]}'
parsed = _extract_json_object(nested)
check("嵌套 JSON 解析",
      parsed is not None and parsed["metadata"]["docCategory"] == "产品手册")

# 4.5 无效输入
check("纯文本返回 None",
      _extract_json_object("这不是JSON") is None)
check("空字符串返回 None",
      _extract_json_object("") is None)
check("None 输入不崩溃",
      _extract_json_object(None) is None if True else True)  # 可能会报错

# 4.6 LLM 典型输出格式
llm_output = """根据文档内容分析如下：

```json
{
  "rewritten_query": "罗斯蒙特3051压力变送器技术参数",
  "keywords": ["罗斯蒙特", "3051", "压力变送器", "参数"],
  "intent": "查询产品技术参数",
  "expansion_terms": ["规格", "量程"]
}
```

以上是改写结果。"""
parsed_llm = _extract_json_object(llm_output)
check("LLM 典型输出解析",
      parsed_llm is not None and parsed_llm.get("rewritten_query") == "罗斯蒙特3051压力变送器技术参数")
check("LLM 输出 keywords 是列表",
      parsed_llm is not None and isinstance(parsed_llm.get("keywords"), list))

# 4.7 含转义字符的 JSON
escaped = '{"query": "查询\\"引号\\"内容", "keywords": ["a\\nb"]}'
parsed_escaped = _extract_json_object(escaped)
check("含转义字符的 JSON",
      parsed_escaped is not None and "引号" in parsed_escaped.get("query", ""))


# ═══════════════════════════════════════════════════════════
# 5. 检索层 _local_keywords 与 KeywordExtractor 一致性
# ═══════════════════════════════════════════════════════════
print("\n" + "=" * 70)
print("  5. 检索层 _local_keywords 与 KeywordExtractor 一致性对比")
print("=" * 70)

from src.knowledge.retriever import KnowledgeRetriever

# 创建一个最小化的 retriever（不需要真实的 VDB/LKEAP）
class FakeVDB:
    pass

retriever = KnowledgeRetriever(vector_store=FakeVDB())

# 对比同一文本的关键词提取结果
test_query = "罗斯蒙特3051压力变送器的安装方法和技术参数"

local_kw = retriever._local_keywords(test_query)
extractor_kw = extractor.extract(test_query, top_k=8)

print(f"  retriever._local_keywords: {local_kw}")
print(f"  KeywordExtractor.extract:  {extractor_kw}")

check("_local_keywords 返回非空",
      len(local_kw) > 0)
check("_local_keywords 数量合理(<=8)",
      len(local_kw) <= 8)

# 检查一致性问题：_local_keywords 是否包含停用词
from src.knowledge.keyword_extract import _STOP_WORDS
local_has_stopwords = [w for w in local_kw if w.lower() in _STOP_WORDS]
check("_local_keywords 无停用词泄漏",
      len(local_has_stopwords) == 0,
      f"泄漏的停用词: {local_has_stopwords}" if local_has_stopwords else "")

# 检查 extractor 是否更严格
extractor_has_stopwords = [w for w in extractor_kw if w.lower() in _STOP_WORDS]
check("KeywordExtractor 无停用词泄漏",
      len(extractor_has_stopwords) == 0,
      f"泄漏的停用词: {extractor_has_stopwords}" if extractor_has_stopwords else "")


# ═══════════════════════════════════════════════════════════
# 6. Filter 构造逻辑
# ═══════════════════════════════════════════════════════════
print("\n" + "=" * 70)
print("  6. Self-Querying Filter 构造逻辑")
print("=" * 70)

# 测试 _build_chunk_filter
filter_expr = retriever._build_chunk_filter(
    knowledge_base_id=2001,
    filters={"docCategory": "产品手册", "industryVertical": "制造业"},
)
print(f"  chunk_filter: {filter_expr}")

check("filter 包含 kb_id",
      'knowledge_base_id = "2001"' in filter_expr)
check("filter 包含 status=active",
      'status = "active"' in filter_expr)
check("filter 映射 docCategory → doc_category",
      'doc_category = "产品手册"' in filter_expr)
check("filter 映射 industryVertical → industry",
      'industry = "制造业"' in filter_expr)

# 空过滤条件
filter_empty = retriever._build_chunk_filter(knowledge_base_id=2001, filters={})
check("空 filters 只有 kb_id 和 status",
      filter_empty.count("=") == 2)

# None 值过滤
filter_none = retriever._build_chunk_filter(
    knowledge_base_id=2001,
    filters={"docCategory": None, "industryVertical": ""},
)
check("None/空值被过滤掉",
      "doc_category" not in filter_none and "industry" not in filter_none)

# 列表值
filter_list = retriever._build_chunk_filter(
    knowledge_base_id=2001,
    filters={"docCategory": ["产品手册", "技术白皮书"]},
)
print(f"  list_filter: {filter_list}")
check("列表值生成 OR 表达式",
      "or" in filter_list and "产品手册" in filter_list and "技术白皮书" in filter_list)

# SQL 注入防护
filter_inject = retriever._build_chunk_filter(
    knowledge_base_id=2001,
    filters={"docCategory": '产品手册"; DROP TABLE --'},
)
check("特殊字符被转义",
      '\\"' in filter_inject)

# 无 kb_id
filter_no_kb = retriever._build_chunk_filter(knowledge_base_id=None, filters={})
check("无 kb_id 时不包含 knowledge_base_id",
      "knowledge_base_id" not in filter_no_kb)


# ═══════════════════════════════════════════════════════════
# 7. 入口层 vs 检索层改写触发条件
# ═══════════════════════════════════════════════════════════
print("\n" + "=" * 70)
print("  7. 改写触发条件验证")
print("=" * 70)

from langchain_core.messages import HumanMessage, AIMessage

# 模拟入口层 QueryRewriter 的触发条件
rewriter = QueryRewriter(llm=None, enabled=True)  # 无 LLM，测试逻辑分支

import asyncio

# 7.1 无历史不改写
result = asyncio.run(rewriter.rewrite([], "查询华为商机"))
check("无历史消息 → 不改写",
      result == "查询华为商机")

# 7.2 有历史但 LLM 为 None → 不改写
history = [HumanMessage(content="你好"), AIMessage(content="你好，有什么可以帮您？")]
result = asyncio.run(rewriter.rewrite(history, "查询华为商机"))
check("有历史但无 LLM → 不改写",
      result == "查询华为商机")

# 7.3 空查询不改写
result = asyncio.run(rewriter.rewrite(history, ""))
check("空查询 → 不改写",
      result == "")

# 7.4 纯空格查询不改写
result = asyncio.run(rewriter.rewrite(history, "   "))
check("纯空格查询 → 不改写",
      result == "   ")

# 7.5 disabled 不改写
disabled_rewriter = QueryRewriter(llm=object(), enabled=False)
result = asyncio.run(disabled_rewriter.rewrite(history, "查询华为商机"))
check("disabled=False → 不改写",
      result == "查询华为商机")


# ═══════════════════════════════════════════════════════════
# 8. 关键词提取边界场景
# ═══════════════════════════════════════════════════════════
print("\n" + "=" * 70)
print("  8. 关键词提取边界场景")
print("=" * 70)

# 8.1 纯英文文本
english_text = "The Rosemount 3051 pressure transmitter supports HART protocol with 4-20mA output signal"
kw_en = extractor.extract(english_text, top_k=10)
print(f"  纯英文关键词: {kw_en}")
check("纯英文能提取关键词",
      len(kw_en) >= 1)

# 8.2 重复文本
repeat_text = "压力变送器 " * 100
kw_repeat = extractor.extract(repeat_text, top_k=10)
print(f"  重复文本关键词: {kw_repeat}")
check("重复文本不崩溃",
      isinstance(kw_repeat, list))

# 8.3 特殊字符文本
special_text = "!@#$%^&*()_+-=[]{}|;':\",./<>?"
kw_special = extractor.extract(special_text, top_k=10)
check("纯特殊字符返回空或少量结果",
      len(kw_special) <= 2)

# 8.4 超长文本（模拟大文档）
long_text = test_doc * 50  # ~15000 字
kw_long = extractor.extract(long_text, top_k=20)
check("超长文本能正常提取",
      len(kw_long) > 0 and len(kw_long) <= 20)

# 8.5 with_weight 模式
kw_weighted = extractor.extract(test_doc, top_k=5, with_weight=True)
check("with_weight 返回元组列表",
      len(kw_weighted) > 0 and isinstance(kw_weighted[0], tuple))
check("权重值在合理范围",
      all(0 < w <= 1.0 for _, w in kw_weighted))
check("权重降序排列",
      all(kw_weighted[i][1] >= kw_weighted[i+1][1] for i in range(len(kw_weighted)-1)))


# ═══════════════════════════════════════════════════════════
# 9. AUTO_TAG_PROMPT 模板验证
# ═══════════════════════════════════════════════════════════
print("\n" + "=" * 70)
print("  9. AUTO_TAG_PROMPT 模板格式验证")
print("=" * 70)

from src.knowledge.ingestion import AUTO_TAG_PROMPT

# 验证 prompt 模板的占位符
check("AUTO_TAG_PROMPT 包含 schema_json 占位符",
      "{schema_json}" in AUTO_TAG_PROMPT)
check("AUTO_TAG_PROMPT 包含 candidate_keywords 占位符",
      "{candidate_keywords}" in AUTO_TAG_PROMPT)
check("AUTO_TAG_PROMPT 包含 document_content 占位符",
      "{document_content}" in AUTO_TAG_PROMPT)

# 验证格式化不报错
try:
    formatted = AUTO_TAG_PROMPT.format(
        schema_json='[{"field": "docCategory", "type": "enum"}]',
        candidate_keywords="压力变送器, HART, 量程",
        document_content="测试文档内容...",
    )
    check("AUTO_TAG_PROMPT 格式化成功", True)
    check("格式化后包含候选关键词",
          "压力变送器, HART, 量程" in formatted)
except Exception as e:
    check("AUTO_TAG_PROMPT 格式化成功", False, str(e))


# ═══════════════════════════════════════════════════════════
# 10. QUERY_REWRITE_PROMPT 模板验证
# ═══════════════════════════════════════════════════════════
print("\n" + "=" * 70)
print("  10. QUERY_REWRITE_PROMPT 模板格式验证")
print("=" * 70)

from src.knowledge.retriever import QUERY_REWRITE_PROMPT, SELF_QUERY_PROMPT

check("QUERY_REWRITE_PROMPT 包含 conversation_history",
      "{conversation_history}" in QUERY_REWRITE_PROMPT)
check("QUERY_REWRITE_PROMPT 包含 query",
      "{query}" in QUERY_REWRITE_PROMPT)

try:
    formatted_rw = QUERY_REWRITE_PROMPT.format(
        conversation_history="[用户]: 查华为商机\n[助手]: 华为有3个商机",
        query="最大的那个呢",
    )
    check("QUERY_REWRITE_PROMPT 格式化成功", True)
except Exception as e:
    check("QUERY_REWRITE_PROMPT 格式化成功", False, str(e))

check("SELF_QUERY_PROMPT 包含 schema_fields",
      "{schema_fields}" in SELF_QUERY_PROMPT)
check("SELF_QUERY_PROMPT 包含 query",
      "{query}" in SELF_QUERY_PROMPT)

try:
    formatted_sq = SELF_QUERY_PROMPT.format(
        schema_fields='[{"field": "docCategory"}]',
        query="制造业的成功案例",
    )
    check("SELF_QUERY_PROMPT 格式化成功", True)
except Exception as e:
    check("SELF_QUERY_PROMPT 格式化成功", False, str(e))


# ═══════════════════════════════════════════════════════════
# 汇总报告
# ═══════════════════════════════════════════════════════════
print("\n" + "=" * 70)
print(f"  验证完成: {_pass} PASS / {_fail} FAIL / {_pass + _fail} TOTAL")
print("=" * 70)

if _errors:
    print("\n  失败项:")
    for e in _errors:
        print(f"    {e}")

sys.exit(0 if _fail == 0 else 1)
