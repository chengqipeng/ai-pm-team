"""QueryRewriter 单元测试"""
import asyncio
from src.core.query_rewriter import QueryRewriter
from langchain_core.messages import HumanMessage, AIMessage


class MockLLM:
    """模拟 LLM，同时验证 callbacks=[] 隔离"""
    def __init__(self, response):
        self._response = response
        self.invoke_count = 0
        self.last_config = None

    async def ainvoke(self, prompt, config=None):
        self.invoke_count += 1
        self.last_config = config
        # 关键校验：callbacks 必须被显式设置为 []
        assert config is not None, "config 必须传入"
        assert config.get("callbacks") == [], \
            f"callbacks 应为 []，实际 {config.get('callbacks')}"
        assert "__query_rewriter_internal__" in config.get("tags", []), \
            "必须带内部 tag"

        class Result:
            def __init__(self, content):
                self.content = content
        return Result(self._response)


async def test_single_turn_no_rewrite():
    """单轮对话（无历史）不触发改写"""
    llm = MockLLM("should not be called")
    rewriter = QueryRewriter(llm=llm)
    result = await rewriter.rewrite([], "我负责华东区")
    assert result == "我负责华东区"
    assert llm.invoke_count == 0, "单轮对话不应调用 LLM"
    print("✓ test_single_turn_no_rewrite")


async def test_multi_turn_rewrite():
    """多轮对话正常改写"""
    llm = MockLLM("华为ERP项目的进展如何")
    rewriter = QueryRewriter(llm=llm)
    history = [
        HumanMessage(content="华为 ERP 项目现在什么阶段"),
        AIMessage(content="在方案阶段"),
    ]
    result = await rewriter.rewrite(history, "进展怎么样")
    assert llm.invoke_count == 1, "多轮应该调用 LLM 一次"
    assert result == "华为ERP项目的进展如何"
    print(f"✓ test_multi_turn_rewrite: '{result}'")


async def test_pollution_cleanup():
    """LLM 输出带污染时自动清洗"""
    llm = MockLLM("改写：查询华东区情况，实体名：华东区，代词解析：我指代用户")
    rewriter = QueryRewriter(llm=llm)
    history = [
        HumanMessage(content="我是销售"),
        AIMessage(content="好的"),
    ]
    result = await rewriter.rewrite(history, "华东区情况")
    print(f"  清洗前: '改写：查询华东区情况，实体名：华东区，代词解析：我指代用户'")
    print(f"  清洗后: {result!r}")
    assert "改写" not in result, f"未清洗改写前缀: {result}"
    assert "实体名" not in result, f"未清洗实体标注: {result}"
    assert "代词" not in result, f"未清洗代词标注: {result}"
    print("✓ test_pollution_cleanup")


async def test_no_llm_fallback():
    """未配置 LLM 时 fallback 到原文"""
    rewriter = QueryRewriter(llm=None)
    history = [HumanMessage(content="x"), AIMessage(content="y")]
    result = await rewriter.rewrite(history, "他怎么说")
    assert result == "他怎么说"
    print("✓ test_no_llm_fallback")


async def test_callback_isolation():
    """关键测试：验证 callbacks=[] 阻止事件传播"""
    llm = MockLLM("改写后的查询")
    rewriter = QueryRewriter(llm=llm)
    history = [HumanMessage(content="华为"), AIMessage(content="是客户")]
    await rewriter.rewrite(history, "他怎么样")
    # MockLLM.ainvoke 内部已经 assert 了 callbacks=[]
    assert llm.last_config.get("callbacks") == []
    assert "__query_rewriter_internal__" in llm.last_config.get("tags", [])
    print("✓ test_callback_isolation: 改写调用被隔离于主 Agent 流之外")


async def test_too_long_output_fallback():
    """输出过长时 fallback 到原文"""
    long_response = "改写后的查询" * 50  # > 150 字符
    llm = MockLLM(long_response)
    rewriter = QueryRewriter(llm=llm)
    history = [HumanMessage(content="x"), AIMessage(content="y")]
    result = await rewriter.rewrite(history, "原始查询")
    assert result == "原始查询", f"过长输出应 fallback 原文: {result}"
    print("✓ test_too_long_output_fallback")


async def test_multiple_sentences_fallback():
    """输出含多个句号时 fallback（说明 LLM 在解释而非改写）"""
    llm = MockLLM("这是改写的结果。这是解释。还有补充说明。")
    rewriter = QueryRewriter(llm=llm)
    history = [HumanMessage(content="x"), AIMessage(content="y")]
    result = await rewriter.rewrite(history, "原始查询")
    assert result == "原始查询", f"多句号应 fallback: {result}"
    print("✓ test_multiple_sentences_fallback")


async def main():
    print("=" * 70)
    print("  QueryRewriter 单元测试")
    print("=" * 70)
    await test_single_turn_no_rewrite()
    await test_multi_turn_rewrite()
    await test_pollution_cleanup()
    await test_no_llm_fallback()
    await test_callback_isolation()
    await test_too_long_output_fallback()
    await test_multiple_sentences_fallback()
    print("=" * 70)
    print("  ✓ 所有测试通过")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())
