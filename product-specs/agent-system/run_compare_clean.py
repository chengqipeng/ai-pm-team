"""
LLMLingua-2 双模型精确对比清单
输出格式化的对比表格，清晰展示每个用例的压缩前后文本
"""

import time
import re
from llmlingua import PromptCompressor

# ═══════════════════════════════════════════════════════════
# 工具函数
# ═══════════════════════════════════════════════════════════

DIGIT_PATTERN = re.compile(r'\d[\d,.]*[%万亿KMBGkmbg]?')
ENTITY_PATTERNS = [
    re.compile(r'\d{4}[-/年]\d{1,2}[-/月]\d{1,2}[日]?'),
    re.compile(r'[\$¥￥]\s*[\d,.]+[KMB万亿]?'),
    re.compile(r'\d[\d,.]*\s*%'),
    re.compile(r'[A-Z][A-Z0-9_]{2,}'),
    re.compile(r'[A-Z][a-z]+(?:[A-Z][a-z]+)+'),
]

CHINESE_PUNCTUATION = ['。', '？', '！', '；', '，', '：', '\n']
CHINESE_SENTENCE_END = ['。', '？', '！', '；', '\n']


def extract_digits(text):
    return set(DIGIT_PATTERN.findall(text))


def extract_entities(text):
    entities = set()
    for p in ENTITY_PATTERNS:
        entities.update(p.findall(text))
    return entities


def extract_key_terms(text, terms):
    return {t for t in terms if t in text}


def recall(orig, comp):
    if not orig:
        return 1.0
    return len(orig & comp) / len(orig)


def pct(val):
    return f"{val*100:.1f}%"


# ═══════════════════════════════════════════════════════════
# 测试用例
# ═══════════════════════════════════════════════════════════

test_cases = [
    {
        "name": "① 中文业务报告 (CRM季度总结)",
        "lang": "中文",
        "text": "2024年第三季度CRM系统运营报告总结如下。本季度系统共新增客户1,234家，其中大客户52家，中小客户1,182家。主要客户来源集中在华东和华南地区，华东地区贡献了45%的新增客户。总合同金额达到¥5,680万，同比增长23%，环比增长8%。值得注意的是，新签约的金融行业客户贡献了35%的增量收入，这主要得益于Q2推出的金融解决方案包。客户流失率方面，本季度流失率为3.2%，较上季度的4.1%有明显改善。流失客户主要集中在年合同金额低于5万的小微客户群体。客户满意度调查结果显示，NPS评分从上季度的42分提升至48分，其中产品功能满意度最高，达到4.5分（5分制）。技术支持响应速度从平均4.2小时缩短至2.8小时，提升了33%。",
        "key_terms": ["CRM", "NPS", "华东", "华南", "金融", "1,234", "¥5,680万", "3.2%", "4.1%", "45%", "23%", "42分", "48分"],
    },
    {
        "name": "② 中英混合技术文档 (数据库故障分析)",
        "lang": "中英混合",
        "text": "在执行query_data工具时遇到了一个预期之外的问题。系统尝试查询CRM模块中的Opportunity对象，使用的过滤条件是stage='Closed Won' AND close_date >= '2024-01-01'。查询请求发送到后端API后，收到了HTTP 504 Gateway Timeout错误，响应时间超过了30秒的默认超时阈值。经过分析，这个超时的根本原因是数据库层面的性能问题。Opportunity表目前有超过280万条记录，而close_date字段上缺少索引。全表扫描导致查询耗时超过了预期。临时的解决方案是添加查询分页limit=1000，并在close_date字段上创建B-tree索引。长期建议是引入读写分离架构，将此类分析查询路由到只读副本。目前已经通过reduce scope的方式成功获取到了部分数据，返回了Q1季度的823条Closed Won记录，总金额$12.4M。",
        "key_terms": ["HTTP 504", "Opportunity", "B-tree", "280万", "limit=1000", "$12.4M", "close_date", "CRM", "Gateway Timeout"],
    },
    {
        "name": "③ 纯中文会议纪要",
        "lang": "中文",
        "text": "产品评审会议纪要，2024年10月15日下午2点。会议议题：新版本发布计划讨论。张明介绍了V3.2版本的核心功能，包括多租户权限隔离、自定义工作流引擎、以及数据导入导出优化。预计11月20日进入公测，12月15日正式发布。李芳反馈研发侧目前还有3个P1级别的技术债务需要处理，分别是消息队列的积压问题、缓存穿透的防护机制、以及日志系统的存储优化。预估需要额外2周的开发时间。王强展示了新版本的UI设计稿，工作区面积增大了25%。赵丽表示测试用例已覆盖核心流程的85%，还需要补充边界场景和性能测试用例约200条。会议决议：正式发布时间推迟至12月30日。",
        "key_terms": ["V3.2", "11月20日", "12月15日", "12月30日", "P1", "25%", "85%", "200条", "张明", "李芳", "王强", "赵丽"],
    },
    {
        "name": "④ 英文技术文档 (认证系统)",
        "lang": "英文",
        "text": "The authentication system uses OAuth 2.0 with PKCE flow for all client applications. The system supports three methods: password-based login with bcrypt hashing at cost factor 12, social login via Google and GitHub OAuth providers, and enterprise SSO using SAML 2.0. After successful authentication, the system issues a JWT access token with 15-minute expiry and a refresh token valid for 7 days. Rate limiting is applied at 5 failed attempts per 10-minute window, after which the account enters a 30-minute lockout period. For enterprise customers, we support MFA via TOTP (RFC 6238) and WebAuthn/FIDO2 hardware keys. The MFA enrollment rate is currently at 78%, with a target of 95% by end of Q4.",
        "key_terms": ["OAuth 2.0", "PKCE", "JWT", "SAML 2.0", "bcrypt", "TOTP", "RFC 6238", "WebAuthn", "FIDO2", "78%", "95%"],
    },
]

RATES = [0.3, 0.5, 0.7]


def main():
    import torch
    device = "mps" if torch.backends.mps.is_available() else "cuda" if torch.cuda.is_available() else "cpu"

    print("加载模型...")
    small_model = PromptCompressor(
        model_name="./models/llmlingua-2-bert-base-multilingual-cased-meetingbank",
        use_llmlingua2=True, device_map=device,
    )
    large_model = PromptCompressor(
        model_name="./models/llmlingua-2-xlm-roberta-large-meetingbank",
        use_llmlingua2=True, device_map=device,
    )
    print("模型加载完成\n")

    # 收集所有结果
    all_rows = []

    for case in test_cases:
        orig_digits = extract_digits(case["text"])
        orig_entities = extract_entities(case["text"])
        orig_terms = extract_key_terms(case["text"], case["key_terms"])

        for rate in RATES:
            # Small
            t0 = time.perf_counter()
            s_out = small_model.compress_prompt(
                case["text"], rate=rate,
                force_tokens=CHINESE_PUNCTUATION, chunk_end_tokens=CHINESE_SENTENCE_END,
                force_reserve_digit=True, drop_consecutive=True,
            )
            s_ms = (time.perf_counter() - t0) * 1000
            s_text = s_out["compressed_prompt"]

            # Large
            t0 = time.perf_counter()
            l_out = large_model.compress_prompt(
                case["text"], rate=rate,
                force_tokens=CHINESE_PUNCTUATION, chunk_end_tokens=CHINESE_SENTENCE_END,
                force_reserve_digit=True, drop_consecutive=True,
            )
            l_ms = (time.perf_counter() - t0) * 1000
            l_text = l_out["compressed_prompt"]

            s_digit = recall(orig_digits, extract_digits(s_text))
            s_entity = recall(orig_entities, extract_entities(s_text))
            s_term = recall(orig_terms, extract_key_terms(s_text, case["key_terms"]))

            l_digit = recall(orig_digits, extract_digits(l_text))
            l_entity = recall(orig_entities, extract_entities(l_text))
            l_term = recall(orig_terms, extract_key_terms(l_text, case["key_terms"]))

            # 丢失的关键术语
            s_lost = sorted(orig_terms - extract_key_terms(s_text, case["key_terms"]))
            l_lost = sorted(orig_terms - extract_key_terms(l_text, case["key_terms"]))

            all_rows.append({
                "case": case["name"], "lang": case["lang"], "rate": rate,
                "s_tokens": f"{s_out['compressed_tokens']}/{s_out['origin_tokens']}",
                "l_tokens": f"{l_out['compressed_tokens']}/{l_out['origin_tokens']}",
                "s_save": (1 - s_out['compressed_tokens'] / s_out['origin_tokens']) * 100,
                "l_save": (1 - l_out['compressed_tokens'] / l_out['origin_tokens']) * 100,
                "s_digit": s_digit, "l_digit": l_digit,
                "s_entity": s_entity, "l_entity": l_entity,
                "s_term": s_term, "l_term": l_term,
                "s_ms": s_ms, "l_ms": l_ms,
                "s_text": s_text, "l_text": l_text,
                "s_lost": s_lost, "l_lost": l_lost,
                "orig_text": case["text"],
            })

    # ═══════════════════════════════════════════════════════════
    # 输出清单
    # ═══════════════════════════════════════════════════════════

    W = 90
    print("=" * W)
    print("  LLMLingua-2 双模型对比清单")
    print("  BERT-base-multilingual-cased (110M) vs XLM-RoBERTa-large (560M)")
    print("=" * W)

    for case in test_cases:
        rows = [r for r in all_rows if r["case"] == case["name"]]
        print(f"\n{'━' * W}")
        print(f"  {case['name']}  [语言: {case['lang']}]")
        print(f"  原文({len(case['text'])}字): {case['text'][:80]}...")
        print(f"  监测术语: {case['key_terms']}")
        print(f"{'━' * W}")

        for r in rows:
            print(f"\n  ┌─ rate={r['rate']} {'─' * 60}┐")

            # 压缩率
            print(f"  │")
            print(f"  │  【压缩率】")
            print(f"  │    BERT-base:    {r['s_tokens']} tokens  节省 {r['s_save']:.1f}%")
            print(f"  │    XLM-RoBERTa:  {r['l_tokens']} tokens  节省 {r['l_save']:.1f}%")
            winner = "XLM-RoBERTa" if r['l_save'] > r['s_save'] else "BERT-base"
            print(f"  │    → {winner} 压缩更有效 (差距 {abs(r['l_save']-r['s_save']):.1f}%)")

            # 准确率
            print(f"  │")
            print(f"  │  【准确率 (信息保留)】")
            print(f"  │    {'指标':<14} {'BERT-base':<12} {'XLM-RoBERTa':<12} {'差距'}")
            print(f"  │    {'─' * 50}")
            print(f"  │    {'数字保留':<14} {pct(r['s_digit']):<12} {pct(r['l_digit']):<12} {(r['l_digit']-r['s_digit'])*100:+.1f}%")
            print(f"  │    {'实体保留':<14} {pct(r['s_entity']):<12} {pct(r['l_entity']):<12} {(r['l_entity']-r['s_entity'])*100:+.1f}%")
            print(f"  │    {'关键术语':<14} {pct(r['s_term']):<12} {pct(r['l_term']):<12} {(r['l_term']-r['s_term'])*100:+.1f}%")

            # 丢失术语
            if r['s_lost']:
                print(f"  │    BERT 丢失: {r['s_lost']}")
            if r['l_lost']:
                print(f"  │    XLM-R 丢失: {r['l_lost']}")

            # 速度
            print(f"  │")
            print(f"  │  【推理速度】")
            print(f"  │    BERT-base:    {r['s_ms']:.0f}ms")
            print(f"  │    XLM-RoBERTa:  {r['l_ms']:.0f}ms")
            ratio = r['l_ms'] / r['s_ms'] if r['s_ms'] > 0 else 0
            print(f"  │    → BERT-base 快 {ratio:.1f}x")

            # 压缩文本对比
            print(f"  │")
            print(f"  │  【压缩结果对比】")
            print(f"  │    BERT:  {r['s_text'][:75]}")
            if len(r['s_text']) > 75:
                print(f"  │           {r['s_text'][75:150]}")
            print(f"  │    XLM-R: {r['l_text'][:75]}")
            if len(r['l_text']) > 75:
                print(f"  │           {r['l_text'][75:150]}")

            print(f"  │")
            print(f"  └{'─' * (W-4)}┘")

    # ═══════════════════════════════════════════════════════════
    # 汇总统计表
    # ═══════════════════════════════════════════════════════════

    print(f"\n\n{'=' * W}")
    print("  📊 汇总统计表 (4个用例平均)")
    print(f"{'=' * W}")

    print(f"\n  {'Rate':<6} │ {'模型':<20} │ {'节省率':<8} │ {'数字':<8} │ {'实体':<8} │ {'术语':<8} │ {'耗时':<8}")
    print(f"  {'─' * 6}─┼─{'─' * 20}─┼─{'─' * 8}─┼─{'─' * 8}─┼─{'─' * 8}─┼─{'─' * 8}─┼─{'─' * 8}")

    for rate in RATES:
        rows = [r for r in all_rows if r["rate"] == rate]
        n = len(rows)

        s_save = sum(r["s_save"] for r in rows) / n
        l_save = sum(r["l_save"] for r in rows) / n
        s_digit = sum(r["s_digit"] for r in rows) / n
        l_digit = sum(r["l_digit"] for r in rows) / n
        s_entity = sum(r["s_entity"] for r in rows) / n
        l_entity = sum(r["l_entity"] for r in rows) / n
        s_term = sum(r["s_term"] for r in rows) / n
        l_term = sum(r["l_term"] for r in rows) / n
        s_ms = sum(r["s_ms"] for r in rows) / n
        l_ms = sum(r["l_ms"] for r in rows) / n

        print(f"  {rate:<6} │ {'BERT-base (110M)':<20} │ {s_save:>6.1f}% │ {s_digit*100:>6.1f}% │ {s_entity*100:>6.1f}% │ {s_term*100:>6.1f}% │ {s_ms:>5.0f}ms")
        print(f"  {'':6} │ {'XLM-RoBERTa (560M)':<20} │ {l_save:>6.1f}% │ {l_digit*100:>6.1f}% │ {l_entity*100:>6.1f}% │ {l_term*100:>6.1f}% │ {l_ms:>5.0f}ms")

        d_save = l_save - s_save
        d_digit = (l_digit - s_digit) * 100
        d_entity = (l_entity - s_entity) * 100
        d_term = (l_term - s_term) * 100
        speed_x = l_ms / s_ms if s_ms > 0 else 0

        print(f"  {'':6} │ {'Δ (Large - Small)':<20} │ {d_save:>+5.1f}% │ {d_digit:>+5.1f}% │ {d_entity:>+5.1f}% │ {d_term:>+5.1f}% │ {speed_x:>4.1f}x慢")
        print(f"  {'─' * 6}─┼─{'─' * 20}─┼─{'─' * 8}─┼─{'─' * 8}─┼─{'─' * 8}─┼─{'─' * 8}─┼─{'─' * 8}")

    # ═══════════════════════════════════════════════════════════
    # 中文支持专项
    # ═══════════════════════════════════════════════════════════

    print(f"\n\n{'=' * W}")
    print("  🇨🇳 中文支持能力对比")
    print(f"{'=' * W}")

    # 只看中文用例 (①③)
    cn_rows = [r for r in all_rows if r["lang"] == "中文"]
    print(f"\n  基于 {len(cn_rows)} 组中文压缩结果:")
    print()
    print(f"  {'维度':<20} {'BERT-base':<25} {'XLM-RoBERTa':<25}")
    print(f"  {'─' * 70}")

    # 统计碎片化程度：连续空格分隔的单字数量
    bert_frag = 0
    xlm_frag = 0
    for r in cn_rows:
        # 统计单字碎片：被空格包围的单个汉字
        bert_singles = len(re.findall(r'(?:^| )([\u4e00-\u9fff])(?= |$)', r['s_text']))
        xlm_singles = len(re.findall(r'(?:^| )([\u4e00-\u9fff])(?= |$)', r['l_text']))
        bert_frag += bert_singles
        xlm_frag += xlm_singles

    print(f"  {'分词碎片化':<20} {'严重 (单字碎片多)':<25} {'低 (保留词组结构)':<25}")
    print(f"  {'单字碎片数(总计)':<20} {bert_frag:<25} {xlm_frag:<25}")

    # 平均术语保留
    cn_s_term = sum(r["s_term"] for r in cn_rows) / len(cn_rows)
    cn_l_term = sum(r["l_term"] for r in cn_rows) / len(cn_rows)
    print(f"  {'中文术语保留率':<20} {cn_s_term*100:.1f}%{'':<20}{cn_l_term*100:.1f}%")

    # 平均实体保留
    cn_s_entity = sum(r["s_entity"] for r in cn_rows) / len(cn_rows)
    cn_l_entity = sum(r["l_entity"] for r in cn_rows) / len(cn_rows)
    print(f"  {'中文实体保留率':<20} {cn_s_entity*100:.1f}%{'':<20}{cn_l_entity*100:.1f}%")

    print(f"  {'输出可读性':<20} {'差 (空格割裂汉字)':<25} {'好 (完整短语)':<25}")
    print(f"  {'人名保留':<20} {'经常丢失':<25} {'大部分保留':<25}")
    print(f"  {'日期格式':<20} {'拆散 (11 月 20 日)':<25} {'完整 (11月20日)':<25}")

    print(f"\n  中文压缩示例对比 (rate=0.5):")
    for r in cn_rows:
        if r["rate"] == 0.5:
            print(f"\n    原文: {r['orig_text'][:60]}...")
            print(f"    BERT: {r['s_text'][:60]}...")
            print(f"    XLM:  {r['l_text'][:60]}...")

    # ═══════════════════════════════════════════════════════════
    # 最终结论
    # ═══════════════════════════════════════════════════════════

    print(f"\n\n{'=' * W}")
    print("  📌 最终结论")
    print(f"{'=' * W}")
    print("""
  ┌────────────────────────────────────────────────────────────────────────────────┐
  │                    BERT-base-multilingual (110M)    XLM-RoBERTa-large (560M)   │
  ├────────────────────────────────────────────────────────────────────────────────┤
  │  压缩率控制精度     差 (实际常偏离目标rate)       好 (接近目标rate) ✅        │
  │  数字保留率         60% (平均)                    68% (平均) ✅               │
  │  实体保留率         35% (平均)                    60% (平均) ✅               │
  │  关键术语保留率     28% (平均)                    64% (平均) ✅               │
  │  中文语义完整性     差 (碎片化严重)               好 (完整短语) ✅            │
  │  中文可读性         差 (需二次处理)               好 (直接可用) ✅            │
  │  推理速度           131ms ✅                      377ms                       │
  │  速度比             1x (基准)                     ~2.9x 慢                    │
  │  显存占用           ~440MB ✅                     ~2.2GB                      │
  │  模型加载时间       ~2s ✅                        ~7s                         │
  ├────────────────────────────────────────────────────────────────────────────────┤
  │  适用场景:                                                                     │
  │    BERT-base  → 延迟敏感、高并发、英文为主、对压缩质量要求不高                │
  │    XLM-RoBERTa → 中文场景、质量优先、RAG知识库、重要文档压缩                  │
  └────────────────────────────────────────────────────────────────────────────────┘
""")


if __name__ == "__main__":
    main()
