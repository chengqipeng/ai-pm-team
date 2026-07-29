"""
LLMLingua-2 中文压缩测试
模型: llmlingua-2-bert-base-multilingual-cased-meetingbank (本地)
设备: Mac CPU / MPS
"""

import time
from llmlingua import PromptCompressor


# ═══════════════════════════════════════════════════════════
# 初始化
# ═══════════════════════════════════════════════════════════

print("=" * 60)
print("LLMLingua-2 中文压缩测试")
print("=" * 60)

print("\n[1/4] 加载模型...")
t0 = time.perf_counter()

compressor = PromptCompressor(
    model_name="./models/llmlingua-2-bert-base-multilingual-cased-meetingbank",
    use_llmlingua2=True,
    device_map="mps",  # Mac Apple Silicon GPU，如果报错改为 "cpu"
)

load_time = time.perf_counter() - t0
print(f"  模型加载完成，耗时: {load_time:.1f}s")


# ═══════════════════════════════════════════════════════════
# 测试用例
# ═══════════════════════════════════════════════════════════

test_cases = [
    {
        "name": "中文业务报告",
        "text": (
            "2024年第三季度CRM系统运营报告总结如下。"
            "本季度系统共新增客户1,234家，其中大客户52家，中小客户1,182家。"
            "主要客户来源集中在华东和华南地区，华东地区贡献了45%的新增客户。"
            "总合同金额达到¥5,680万，同比增长23%，环比增长8%。"
            "值得注意的是，新签约的金融行业客户贡献了35%的增量收入，"
            "这主要得益于Q2推出的金融解决方案包。"
            "客户流失率方面，本季度流失率为3.2%，较上季度的4.1%有明显改善。"
            "流失客户主要集中在年合同金额低于5万的小微客户群体。"
            "客户满意度调查结果显示，NPS评分从上季度的42分提升至48分，"
            "其中产品功能满意度最高，达到4.5分（5分制）。"
            "技术支持响应速度从平均4.2小时缩短至2.8小时，提升了33%。"
        ),
    },
    {
        "name": "中英混合技术分析",
        "text": (
            "在执行query_data工具时遇到了HTTP 504 Gateway Timeout错误。"
            "系统尝试查询CRM模块中的Opportunity对象，"
            "过滤条件是stage='Closed Won' AND close_date >= '2024-01-01'。"
            "Opportunity表目前有超过280万条记录，close_date字段缺少索引。"
            "全表扫描导致查询耗时超过30秒超时阈值。"
            "同时有定时任务在执行数据同步，占用大量数据库连接池资源。"
            "临时方案：添加limit=1000分页，创建B-tree索引。"
            "长期建议：引入读写分离，分析查询路由到只读副本。"
            "目前已获取Q1季度823条Closed Won记录，总金额$12.4M。"
        ),
    },
    {
        "name": "会议纪要",
        "text": (
            "产品评审会议纪要，2024年10月15日下午2点。"
            "参会人员：张明（产品）、李芳（研发）、王强（设计）、赵丽（测试）。"
            "张明介绍了V3.2版本核心功能：多租户权限隔离、自定义工作流引擎、数据导入导出优化。"
            "预计11月20日公测，12月15日正式发布。"
            "李芳反馈还有3个P1级别技术债务：消息队列积压、缓存穿透防护、日志存储优化。"
            "预估需要额外2周开发时间。"
            "王强展示新UI设计稿，导航栏从顶部改为侧边栏，工作区面积增大25%。"
            "赵丽表示测试用例已覆盖核心流程85%，还需补充约200条边界和性能测试用例。"
            "决议：发布推迟至12月30日，优先处理消息队列积压问题。"
        ),
    },
]


# ═══════════════════════════════════════════════════════════
# 测试不同压缩率
# ═══════════════════════════════════════════════════════════

print("\n[2/4] 测试不同压缩率...")

for case in test_cases:
    print(f"\n{'─' * 60}")
    print(f"  {case['name']} (原文 {len(case['text'])} 字符)")
    print(f"{'─' * 60}")

    for rate in [0.7, 0.5, 0.33]:
        t0 = time.perf_counter()

        result = compressor.compress_prompt(
            case["text"],
            rate=rate,
            force_tokens=['。', '？', '！', '；', '，', '\n'],
            chunk_end_tokens=['。', '\n'],
            force_reserve_digit=True,
            drop_consecutive=True,
        )

        elapsed = (time.perf_counter() - t0) * 1000

        print(f"\n  rate={rate} | "
              f"{result['origin_tokens']}→{result['compressed_tokens']} tokens | "
              f"{result['ratio']} | "
              f"{elapsed:.0f}ms")
        print(f"  压缩结果: {result['compressed_prompt'][:120]}...")


# ═══════════════════════════════════════════════════════════
# 测试 force_tokens 对中文的影响
# ═══════════════════════════════════════════════════════════

print(f"\n\n[3/4] 对比 force_tokens 效果...")
print("─" * 60)

sample = test_cases[0]["text"]

# 不保留标点
result_no_punct = compressor.compress_prompt(
    sample,
    rate=0.5,
    force_tokens=[],
    force_reserve_digit=True,
)

# 保留中文标点
result_with_punct = compressor.compress_prompt(
    sample,
    rate=0.5,
    force_tokens=['。', '？', '！', '；', '，', '\n'],
    chunk_end_tokens=['。', '\n'],
    force_reserve_digit=True,
    drop_consecutive=True,
)

print(f"\n  无 force_tokens:")
print(f"    {result_no_punct['compressed_prompt'][:150]}...")
print(f"    tokens: {result_no_punct['compressed_tokens']}")

print(f"\n  有 force_tokens (保留中文标点):")
print(f"    {result_with_punct['compressed_prompt'][:150]}...")
print(f"    tokens: {result_with_punct['compressed_tokens']}")


# ═══════════════════════════════════════════════════════════
# 性能测试
# ═══════════════════════════════════════════════════════════

print(f"\n\n[4/4] 性能测试 (10 次压缩)...")
print("─" * 60)

times = []
for i in range(10):
    t0 = time.perf_counter()
    compressor.compress_prompt(
        test_cases[0]["text"],
        rate=0.5,
        force_tokens=['。', '！', '；', '，', '\n'],
        chunk_end_tokens=['。', '\n'],
        force_reserve_digit=True,
    )
    times.append((time.perf_counter() - t0) * 1000)

avg = sum(times) / len(times)
p50 = sorted(times)[4]
p95 = sorted(times)[9]

print(f"  文本长度: {len(test_cases[0]['text'])} 字符")
print(f"  平均: {avg:.0f}ms")
print(f"  P50:  {p50:.0f}ms")
print(f"  P95:  {p95:.0f}ms")

print("\n" + "=" * 60)
print("测试完成")
print("=" * 60)
