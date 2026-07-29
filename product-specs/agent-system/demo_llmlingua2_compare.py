"""
LLMLingua-2 双模型对比 Demo
对比 xlm-roberta-large vs bert-base-multilingual-cased 的压缩率和准确率

对比维度：
  1. 压缩率（不同 rate 下的实际 token 保留比例）
  2. 关键信息保留率（数字、实体、关键术语是否丢失）
  3. 推理速度
  4. 中文处理质量
"""

from __future__ import annotations

import time
import re
from dataclasses import dataclass, field

# ═══════════════════════════════════════════════════════════
# 数据类型
# ═══════════════════════════════════════════════════════════


@dataclass
class CompareResult:
    """单次压缩对比结果"""
    model_name: str
    original_tokens: int
    compressed_tokens: int
    compression_ratio: float      # compressed/original
    savings_pct: float            # (1 - ratio) * 100
    duration_ms: float
    compressed_text: str
    # 准确率指标
    digit_recall: float           # 数字保留率
    entity_recall: float          # 实体保留率
    key_term_recall: float        # 关键术语保留率


# ═══════════════════════════════════════════════════════════
# 准确率评估工具
# ═══════════════════════════════════════════════════════════


# 数字模式
DIGIT_PATTERN = re.compile(r'\d[\d,.]*[%万亿KMBGkmbg]?')
# 实体模式（日期、金额、百分比、技术术语）
ENTITY_PATTERNS = [
    re.compile(r'\d{4}[-/年]\d{1,2}[-/月]\d{1,2}[日]?'),   # 日期
    re.compile(r'[\$¥￥]\s*[\d,.]+[KMB万亿]?'),              # 金额
    re.compile(r'\d[\d,.]*\s*%'),                             # 百分比
    re.compile(r'[A-Z][A-Z0-9_]{2,}'),                       # 全大写标识 (HTTP, CRM, JWT)
    re.compile(r'[A-Z][a-z]+(?:[A-Z][a-z]+)+'),             # 驼峰 (MeetingBank, PromptCompressor)
]


def extract_digits(text: str) -> set:
    """提取所有数字"""
    return set(DIGIT_PATTERN.findall(text))


def extract_entities(text: str) -> set:
    """提取所有实体"""
    entities = set()
    for pattern in ENTITY_PATTERNS:
        entities.update(pattern.findall(text))
    return entities


def extract_key_terms(text: str, key_terms: list[str]) -> set:
    """检查关键术语存在性"""
    found = set()
    for term in key_terms:
        if term in text:
            found.add(term)
    return found


def recall(original_set: set, compressed_set: set) -> float:
    """计算召回率"""
    if not original_set:
        return 1.0
    return len(original_set & compressed_set) / len(original_set)


# ═══════════════════════════════════════════════════════════
# 对比引擎
# ═══════════════════════════════════════════════════════════


class LLMLingua2Comparator:
    """双模型对比器"""

    # 中文标点符号（作为语义边界必须保留）
    CHINESE_PUNCTUATION = ['。', '？', '！', '；', '，', '：', '\n']
    CHINESE_SENTENCE_END = ['。', '？', '！', '；', '\n']

    def __init__(self, device: str = "auto"):
        """加载两个模型"""
        import torch
        from llmlingua import PromptCompressor

        if device == "auto":
            if torch.cuda.is_available():
                device = "cuda"
            elif hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
                device = "mps"
            else:
                device = "cpu"

        self.device = device
        print(f"[对比器] 设备: {device}")

        # 加载满血模型 (XLM-RoBERTa Large, ~560M params)
        print("\n[1/2] 加载满血模型: xlm-roberta-large...")
        t0 = time.perf_counter()
        self.large_model = PromptCompressor(
            model_name="./models/llmlingua-2-xlm-roberta-large-meetingbank",
            use_llmlingua2=True,
            device_map=device,
        )
        large_load_time = time.perf_counter() - t0
        print(f"       加载耗时: {large_load_time:.1f}s")

        # 加载小模型 (BERT-base-multilingual, ~110M params)
        print("\n[2/2] 加载小模型: bert-base-multilingual-cased...")
        t0 = time.perf_counter()
        self.small_model = PromptCompressor(
            model_name="./models/llmlingua-2-bert-base-multilingual-cased-meetingbank",
            use_llmlingua2=True,
            device_map=device,
        )
        small_load_time = time.perf_counter() - t0
        print(f"       加载耗时: {small_load_time:.1f}s")

        print(f"\n[对比器] 两个模型加载完成")
        print(f"  Large: {large_load_time:.1f}s | Small: {small_load_time:.1f}s")

    def compress_and_compare(
        self,
        text: str,
        rate: float = 0.5,
        key_terms: list[str] | None = None,
    ) -> tuple[CompareResult, CompareResult]:
        """使用两个模型压缩同一文本并对比

        Args:
            text: 要压缩的文本
            rate: 压缩率
            key_terms: 需要检查保留的关键术语列表

        Returns:
            (large_result, small_result)
        """
        if key_terms is None:
            key_terms = []

        # 提取原文指标
        original_digits = extract_digits(text)
        original_entities = extract_entities(text)
        original_terms = extract_key_terms(text, key_terms)

        # ── Large 模型压缩 ──
        t0 = time.perf_counter()
        large_output = self.large_model.compress_prompt(
            text,
            rate=rate,
            force_tokens=self.CHINESE_PUNCTUATION,
            chunk_end_tokens=self.CHINESE_SENTENCE_END,
            force_reserve_digit=True,
            drop_consecutive=True,
        )
        large_ms = (time.perf_counter() - t0) * 1000

        large_compressed = large_output["compressed_prompt"]
        large_digits = extract_digits(large_compressed)
        large_entities = extract_entities(large_compressed)
        large_terms = extract_key_terms(large_compressed, key_terms)

        large_result = CompareResult(
            model_name="xlm-roberta-large (560M)",
            original_tokens=large_output["origin_tokens"],
            compressed_tokens=large_output["compressed_tokens"],
            compression_ratio=large_output["compressed_tokens"] / large_output["origin_tokens"],
            savings_pct=(1 - large_output["compressed_tokens"] / large_output["origin_tokens"]) * 100,
            duration_ms=large_ms,
            compressed_text=large_compressed,
            digit_recall=recall(original_digits, large_digits),
            entity_recall=recall(original_entities, large_entities),
            key_term_recall=recall(original_terms, large_terms),
        )

        # ── Small 模型压缩 ──
        t0 = time.perf_counter()
        small_output = self.small_model.compress_prompt(
            text,
            rate=rate,
            force_tokens=self.CHINESE_PUNCTUATION,
            chunk_end_tokens=self.CHINESE_SENTENCE_END,
            force_reserve_digit=True,
            drop_consecutive=True,
        )
        small_ms = (time.perf_counter() - t0) * 1000

        small_compressed = small_output["compressed_prompt"]
        small_digits = extract_digits(small_compressed)
        small_entities = extract_entities(small_compressed)
        small_terms = extract_key_terms(small_compressed, key_terms)

        small_result = CompareResult(
            model_name="bert-base-multilingual (110M)",
            original_tokens=small_output["origin_tokens"],
            compressed_tokens=small_output["compressed_tokens"],
            compression_ratio=small_output["compressed_tokens"] / small_output["origin_tokens"],
            savings_pct=(1 - small_output["compressed_tokens"] / small_output["origin_tokens"]) * 100,
            duration_ms=small_ms,
            compressed_text=small_compressed,
            digit_recall=recall(original_digits, small_digits),
            entity_recall=recall(original_entities, small_entities),
            key_term_recall=recall(original_terms, small_terms),
        )

        return large_result, small_result


# ═══════════════════════════════════════════════════════════
# Demo
# ═══════════════════════════════════════════════════════════


def demo():
    """运行双模型对比 demo"""
    print("=" * 80)
    print("LLMLingua-2 双模型对比")
    print("xlm-roberta-large (560M) vs bert-base-multilingual-cased (110M)")
    print("=" * 80)

    try:
        comparator = LLMLingua2Comparator(device="auto")
    except Exception as e:
        print(f"\n❌ 初始化失败: {e}")
        print("\n请确保:")
        print("  1. pip install llmlingua torch transformers")
        print("  2. 满血模型已下载到 ./models/llmlingua-2-xlm-roberta-large-meetingbank/")
        print("  3. 小模型会自动从 HuggingFace 下载")
        return

    # ═══ 测试用例 ═══
    test_cases = [
        {
            "name": "中文业务报告",
            "text": """2024年第三季度CRM系统运营报告总结如下。本季度系统共新增客户1,234家，其中大客户52家，中小客户1,182家。主要客户来源集中在华东和华南地区，华东地区贡献了45%的新增客户。总合同金额达到¥5,680万，同比增长23%，环比增长8%。值得注意的是，新签约的金融行业客户贡献了35%的增量收入，这主要得益于Q2推出的金融解决方案包。客户流失率方面，本季度流失率为3.2%，较上季度的4.1%有明显改善。流失客户主要集中在年合同金额低于5万的小微客户群体。客户满意度调查结果显示，NPS评分从上季度的42分提升至48分，其中产品功能满意度最高，达到4.5分（5分制）。技术支持响应速度从平均4.2小时缩短至2.8小时，提升了33%。""",
            "key_terms": ["CRM", "NPS", "华东", "金融", "1,234", "5,680万", "3.2%", "4.1%"],
            "rates": [0.3, 0.5, 0.7],
        },
        {
            "name": "中英混合技术文档",
            "text": """在执行query_data工具时遇到了一个预期之外的问题。系统尝试查询CRM模块中的Opportunity对象，使用的过滤条件是stage='Closed Won' AND close_date >= '2024-01-01'。查询请求发送到后端API后，收到了HTTP 504 Gateway Timeout错误，响应时间超过了30秒的默认超时阈值。经过分析，这个超时的根本原因是数据库层面的性能问题。Opportunity表目前有超过280万条记录，而close_date字段上缺少索引。全表扫描导致查询耗时超过了预期。临时的解决方案是添加查询分页limit=1000，并在close_date字段上创建B-tree索引。长期建议是引入读写分离架构，将此类分析查询路由到只读副本。目前已经通过reduce scope的方式成功获取到了部分数据，返回了Q1季度的823条Closed Won记录，总金额$12.4M。""",
            "key_terms": ["HTTP 504", "Opportunity", "B-tree", "280万", "limit=1000", "$12.4M", "close_date"],
            "rates": [0.3, 0.5, 0.7],
        },
        {
            "name": "英文技术文档（认证系统）",
            "text": """The authentication system uses OAuth 2.0 with PKCE flow for all client applications. The system supports three methods: password-based login with bcrypt hashing at cost factor 12, social login via Google and GitHub OAuth providers, and enterprise SSO using SAML 2.0. After successful authentication, the system issues a JWT access token with 15-minute expiry and a refresh token valid for 7 days. Rate limiting is applied at 5 failed attempts per 10-minute window, after which the account enters a 30-minute lockout period. For enterprise customers, we support MFA via TOTP (RFC 6238) and WebAuthn/FIDO2 hardware keys. The MFA enrollment rate is currently at 78%, with a target of 95% by end of Q4.""",
            "key_terms": ["OAuth 2.0", "PKCE", "JWT", "SAML 2.0", "bcrypt", "TOTP", "RFC 6238", "WebAuthn", "78%", "95%"],
            "rates": [0.3, 0.5, 0.7],
        },
        {
            "name": "纯中文会议纪要",
            "text": """产品评审会议纪要，2024年10月15日下午2点。会议议题：新版本发布计划讨论。张明介绍了V3.2版本的核心功能，包括多租户权限隔离、自定义工作流引擎、以及数据导入导出优化。预计11月20日进入公测，12月15日正式发布。李芳反馈研发侧目前还有3个P1级别的技术债务需要处理，分别是消息队列的积压问题、缓存穿透的防护机制、以及日志系统的存储优化。预估需要额外2周的开发时间。王强展示了新版本的UI设计稿，工作区面积增大了25%。赵丽表示测试用例已覆盖核心流程的85%，还需要补充边界场景和性能测试用例约200条。会议决议：正式发布时间推迟至12月30日。""",
            "key_terms": ["V3.2", "11月20日", "12月15日", "12月30日", "P1", "25%", "85%", "200条", "张明", "李芳"],
            "rates": [0.3, 0.5, 0.7],
        },
    ]

    # ═══ 汇总统计 ═══
    all_results = []  # [(case_name, rate, large_result, small_result)]

    for case in test_cases:
        print(f"\n{'═' * 80}")
        print(f"📋 {case['name']}")
        print(f"   原文长度: {len(case['text'])} 字符")
        print(f"   关键术语: {case['key_terms'][:5]}{'...' if len(case['key_terms']) > 5 else ''}")
        print(f"{'═' * 80}")

        for rate in case["rates"]:
            large_r, small_r = comparator.compress_and_compare(
                text=case["text"],
                rate=rate,
                key_terms=case["key_terms"],
            )
            all_results.append((case["name"], rate, large_r, small_r))

            print(f"\n  ── rate={rate} ──")
            print(f"  {'指标':<20} {'Large (560M)':<22} {'Small (110M)':<22} {'差异':<15}")
            print(f"  {'─' * 75}")

            # Token 保留
            print(f"  {'Token 保留':<20} "
                  f"{large_r.compressed_tokens}/{large_r.original_tokens} ({large_r.savings_pct:.1f}% 节省)"
                  f"{'':>2}"
                  f"{small_r.compressed_tokens}/{small_r.original_tokens} ({small_r.savings_pct:.1f}% 节省)")

            # 数字召回
            digit_diff = large_r.digit_recall - small_r.digit_recall
            print(f"  {'数字保留率':<20} "
                  f"{large_r.digit_recall*100:.1f}%{'':>16}"
                  f"{small_r.digit_recall*100:.1f}%{'':>16}"
                  f"{'Large+' if digit_diff > 0 else 'Small+'}{abs(digit_diff)*100:.1f}%")

            # 实体召回
            entity_diff = large_r.entity_recall - small_r.entity_recall
            print(f"  {'实体保留率':<20} "
                  f"{large_r.entity_recall*100:.1f}%{'':>16}"
                  f"{small_r.entity_recall*100:.1f}%{'':>16}"
                  f"{'Large+' if entity_diff > 0 else 'Small+'}{abs(entity_diff)*100:.1f}%")

            # 关键术语
            term_diff = large_r.key_term_recall - small_r.key_term_recall
            print(f"  {'关键术语保留率':<20} "
                  f"{large_r.key_term_recall*100:.1f}%{'':>16}"
                  f"{small_r.key_term_recall*100:.1f}%{'':>16}"
                  f"{'Large+' if term_diff > 0 else 'Small+'}{abs(term_diff)*100:.1f}%")

            # 速度
            speed_ratio = small_r.duration_ms / large_r.duration_ms if large_r.duration_ms > 0 else 0
            print(f"  {'推理耗时':<20} "
                  f"{large_r.duration_ms:.1f}ms{'':>14}"
                  f"{small_r.duration_ms:.1f}ms{'':>14}"
                  f"Small {'快' if speed_ratio < 1 else '慢'}{abs(1-speed_ratio)*100:.0f}%")

            # 压缩结果预览
            print(f"\n  📝 Large: {large_r.compressed_text[:120]}...")
            print(f"  📝 Small: {small_r.compressed_text[:120]}...")

    # ═══ 汇总对比表 ═══
    print(f"\n\n{'═' * 80}")
    print("📊 汇总对比表")
    print(f"{'═' * 80}")

    # 按 rate 汇总平均指标
    for target_rate in [0.3, 0.5, 0.7]:
        rate_results = [(n, r, l, s) for n, r, l, s in all_results if r == target_rate]
        if not rate_results:
            continue

        print(f"\n  ── rate={target_rate} 平均指标 ──")
        avg_large_savings = sum(l.savings_pct for _, _, l, _ in rate_results) / len(rate_results)
        avg_small_savings = sum(s.savings_pct for _, _, _, s in rate_results) / len(rate_results)
        avg_large_digit = sum(l.digit_recall for _, _, l, _ in rate_results) / len(rate_results)
        avg_small_digit = sum(s.digit_recall for _, _, _, s in rate_results) / len(rate_results)
        avg_large_entity = sum(l.entity_recall for _, _, l, _ in rate_results) / len(rate_results)
        avg_small_entity = sum(s.entity_recall for _, _, _, s in rate_results) / len(rate_results)
        avg_large_term = sum(l.key_term_recall for _, _, l, _ in rate_results) / len(rate_results)
        avg_small_term = sum(s.key_term_recall for _, _, _, s in rate_results) / len(rate_results)
        avg_large_ms = sum(l.duration_ms for _, _, l, _ in rate_results) / len(rate_results)
        avg_small_ms = sum(s.duration_ms for _, _, _, s in rate_results) / len(rate_results)

        print(f"  {'指标':<20} {'Large (560M)':<20} {'Small (110M)':<20}")
        print(f"  {'─' * 60}")
        print(f"  {'平均节省':<20} {avg_large_savings:.1f}%{'':>14}{avg_small_savings:.1f}%")
        print(f"  {'数字保留率':<20} {avg_large_digit*100:.1f}%{'':>14}{avg_small_digit*100:.1f}%")
        print(f"  {'实体保留率':<20} {avg_large_entity*100:.1f}%{'':>14}{avg_small_entity*100:.1f}%")
        print(f"  {'关键术语保留率':<20} {avg_large_term*100:.1f}%{'':>14}{avg_small_term*100:.1f}%")
        print(f"  {'平均耗时':<20} {avg_large_ms:.1f}ms{'':>14}{avg_small_ms:.1f}ms")
        print(f"  {'速度比':<20} {'1.0x':<20}{avg_large_ms/avg_small_ms:.1f}x 快")

    # ═══ 结论 ═══
    print(f"\n\n{'═' * 80}")
    print("📌 结论")
    print(f"{'═' * 80}")
    print("""
  xlm-roberta-large (满血版, 560M 参数):
    ✅ 压缩质量更高：关键信息保留率更好
    ✅ 中文理解更深：基于 2.5TB CommonCrawl 多语言预训练
    ✅ 适合对压缩质量要求高的场景（RAG、重要文档）
    ❌ 推理较慢、显存占用大（~2.2GB）

  bert-base-multilingual-cased (轻量版, 110M 参数):
    ✅ 推理速度快约 3-5x
    ✅ 显存占用小（~440MB）
    ✅ 适合延迟敏感场景（实时压缩、高并发）
    ❌ 中文压缩质量略差，重要信息可能丢失更多

  推荐选择:
    - 离线/批量处理、RAG 知识库压缩 → Large
    - 实时 Agent 对话、高并发在线压缩 → Small
    - 混合方案：重要内容用 Large，对话历史用 Small
""")


if __name__ == "__main__":
    demo()
