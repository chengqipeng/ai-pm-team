"""流式过滤器单元测试 — 验证 StreamAnalysisFilter 的正确性"""
from src.core.stream_filter import StreamAnalysisFilter


def _simulate(tokens: list[str]) -> str:
    """模拟流式输入，返回最终用户可见的文本"""
    f = StreamAnalysisFilter()
    out = []
    for t in tokens:
        out.append(f.feed(t))
    out.append(f.flush())
    return "".join(out)


def test_case_1_user_scenario():
    """用户实际场景：改写 + 实体 + 代词 + 业务概念"""
    tokens = [
        "我负责华东区",
        "改写：",
        "我负责华东区。",
        "提取实体：",
        "华东区，",
        "无歧义代词，",
        "业务概念：",
        "区域管辖。",
        "我已经记住啦",
        "，您负责华东区的业务。",
    ]
    result = _simulate(tokens)
    print(f"[case_1] 输出: {result!r}")
    assert "改写" not in result, f"改写未过滤: {result}"
    assert "实体" not in result, f"实体未过滤: {result}"
    assert "业务概念" not in result, f"业务概念未过滤: {result}"
    assert "我负责华东区" in result
    assert "我已经记住啦" in result
    print("[case_1] ✓ 通过")


def test_case_2_cross_token_pattern():
    """pattern 跨 token 边界：'改'在token1末尾，'写：'在token2"""
    tokens = [
        "我负责华东区改",
        "写：",
        "xxx内容。",
        "正常回复",
    ]
    result = _simulate(tokens)
    print(f"[case_2] 输出: {result!r}")
    assert "改写" not in result
    assert "xxx内容" not in result
    assert "我负责华东区" in result
    assert "正常回复" in result
    print("[case_2] ✓ 通过")


def test_case_3_no_end_char():
    """Skip 模式但流直接结束（没遇到句号）— flush 应丢弃"""
    tokens = [
        "正常开头",
        "改写：",
        "没有结束标记的改写内容",
    ]
    result = _simulate(tokens)
    print(f"[case_3] 输出: {result!r}")
    assert "改写" not in result
    assert "没有结束标记" not in result
    assert result == "正常开头"
    print("[case_3] ✓ 通过")


def test_case_4_clean_output():
    """干净输出（无 NLU 分析）— 应原样输出"""
    tokens = [
        "您好，",
        "我可以帮您",
        "查询华东区的",
        "客户数据。",
    ]
    result = _simulate(tokens)
    print(f"[case_4] 输出: {result!r}")
    assert result == "您好，我可以帮您查询华东区的客户数据。"
    print("[case_4] ✓ 通过")


def test_case_5_english_end_char():
    """英文结束标记"""
    tokens = [
        "Hello. ",
        "改写: ",
        "some content.",
        " End.",
    ]
    result = _simulate(tokens)
    print(f"[case_5] 输出: {result!r}")
    assert "改写" not in result
    assert "some content" not in result
    assert "Hello. " in result
    assert " End." in result
    print("[case_5] ✓ 通过")


def test_case_6_multiple_patterns_sequential():
    """连续多个 NLU 片段"""
    tokens = [
        "改写：A。",
        "实体：B。",
        "代词：C。",
        "意图：D。",
        "实际回复",
    ]
    result = _simulate(tokens)
    print(f"[case_6] 输出: {result!r}")
    assert result == "实际回复"
    print("[case_6] ✓ 通过")


def test_case_7_newline_end():
    """换行作为结束标记"""
    tokens = [
        "改写：",
        "分析内容\n",
        "正常文本",
    ]
    result = _simulate(tokens)
    print(f"[case_7] 输出: {result!r}")
    assert "改写" not in result
    assert "分析内容" not in result
    assert "正常文本" in result
    print("[case_7] ✓ 通过")


def test_case_8_long_pattern_priority():
    """长 pattern 优先级：'改写后的查询：' 不应被误匹配为 '改写：'"""
    tokens = [
        "改写后的查询：abc。",
        "正常",
    ]
    result = _simulate(tokens)
    print(f"[case_8] 输出: {result!r}")
    assert "改写" not in result
    assert "abc" not in result
    assert result == "正常"
    print("[case_8] ✓ 通过")


def test_case_9_single_char_tokens():
    """极端情况：每个 token 只有 1 个字符（模拟 LLM 单 token 流式输出）"""
    text = "开头改写：被过滤的内容。恢复"
    tokens = list(text)  # 每个字符一个 token
    result = _simulate(tokens)
    print(f"[case_9] 输出: {result!r}")
    assert "改写" not in result
    assert "被过滤的内容" not in result
    assert result == "开头恢复"
    print("[case_9] ✓ 通过")


def test_case_10_empty_token():
    """空 token 处理"""
    tokens = ["", "正常", "", "文本", ""]
    result = _simulate(tokens)
    print(f"[case_10] 输出: {result!r}")
    assert result == "正常文本"
    print("[case_10] ✓ 通过")


if __name__ == "__main__":
    print("=" * 70)
    print("  StreamAnalysisFilter 单元测试")
    print("=" * 70)
    test_case_1_user_scenario()
    test_case_2_cross_token_pattern()
    test_case_3_no_end_char()
    test_case_4_clean_output()
    test_case_5_english_end_char()
    test_case_6_multiple_patterns_sequential()
    test_case_7_newline_end()
    test_case_8_long_pattern_priority()
    test_case_9_single_char_tokens()
    test_case_10_empty_token()
    print("=" * 70)
    print("  ✓ 所有测试通过")
    print("=" * 70)
