"""
深度验证：切换到 XLM-RoBERTa 后，_try_llmlingua 中各逻辑步骤是否仍需保留

验证方法：对同一批文本，分别跑"有该逻辑"和"无该逻辑"两种模式，
量化对比压缩结果差异，判断每项逻辑的必要性。

验证项：
  1. _protect_decimals（小数点占位符保护）
  2. force_tokens 中文标点
  3. force_tokens 技术符号（: - _ / = @）
  4. force_reserve_digit=True
  5. 中文空格清理（步骤4前半段）
  6. 数字格式修复（步骤4后半段）
  7. _recover_missing_numbers 兜底回补
  8. use_sentence_level_filter
  9. density_patterns 密度检测
"""

import time
import re
from llmlingua import PromptCompressor

# ═══════════════════════════════════════════════════════════
# 工具
# ═══════════════════════════════════════════════════════════

DIGIT_PATTERN = re.compile(r'\d[\d,.]*[%万亿]?')


def extract_digits(text):
    return set(DIGIT_PATTERN.findall(text))


def extract_key_terms(text, terms):
    return {t for t in terms if t in text}


def recall(orig, comp):
    if not orig:
        return 1.0
    return len(orig & comp) / len(orig)


# ═══════════════════════════════════════════════════════════
# 测试文本
# ═══════════════════════════════════════════════════════════

test_cases = [
    {
        "name": "中文业务报告",
        "text": "2024年第三季度CRM系统运营报告总结如下。本季度系统共新增客户1,234家，其中大客户52家，中小客户1,182家。主要客户来源集中在华东和华南地区，华东地区贡献了45%的新增客户。总合同金额达到¥5,680万，同比增长23%，环比增长8%。值得注意的是，新签约的金融行业客户贡献了35%的增量收入，这主要得益于Q2推出的金融解决方案包。客户流失率方面，本季度流失率为3.2%，较上季度的4.1%有明显改善。",
        "key_terms": ["CRM", "1,234", "¥5,680万", "3.2%", "4.1%", "45%", "23%", "8%", "35%"],
        "decimals": ["3.2", "4.1"],
    },
    {
        "name": "中英混合故障报告",
        "text": "系统在2024-01-15 14:32发生了严重故障。Opportunity表查询耗时从平均2.5ms飙升至4500ms，HTTP 504错误率达到12.8%。数据库连接池使用率从40%暴涨至98.5%。经排查，root cause是close_date字段缺少B-tree索引，全表扫描280万条记录。临时方案：设置limit=1000分页、增加max_connections=200。恢复时间14:47，影响时长约15分钟。",
        "key_terms": ["HTTP 504", "B-tree", "close_date", "limit=1000", "max_connections=200", "280万", "2024-01-15"],
        "decimals": ["2.5", "12.8", "98.5"],
    },
    {
        "name": "纯中文会议纪要",
        "text": "产品评审会议纪要，2024年10月15日下午2点。张明介绍了V3.2版本的核心功能，包括多租户权限隔离、自定义工作流引擎。预计11月20日进入公测，12月15日正式发布。李芳反馈还有3个P1级别的技术债务需要处理。王强展示了新版UI设计稿，工作区面积增大了25%。赵丽表示测试用例已覆盖核心流程的85%，还需补充约200条。会议决议：正式发布时间推迟至12月30日。",
        "key_terms": ["V3.2", "11月20日", "12月15日", "12月30日", "P1", "25%", "85%", "张明", "李芳", "王强"],
        "decimals": ["3.2"],
    },
    {
        "name": "高密度配置文本",
        "text": "cluster_name=prod-cn-east cpu_limit=4000m memory_limit=8Gi replicas=3 max_surge=25% max_unavailable=1 readiness_probe_timeout=5s liveness_probe_period=10s hpa_min=2 hpa_max=8 hpa_cpu_target=70% pdb_min_available=2 node_selector=pool=high-mem tolerations=dedicated=ai:NoSchedule resource_quota_cpu=16000m resource_quota_memory=32Gi",
        "key_terms": ["cpu_limit=4000m", "memory_limit=8Gi", "hpa_cpu_target=70%", "replicas=3"],
        "decimals": [],
    },
]

RATE = 0.5  # 统一用 0.5 做验证

CHINESE_PUNCTUATION = ['。', '？', '！', '；', '，', '：', '\n']
TECH_SYMBOLS = [':', '-', '_', '/', '=', '@']
MONEY_SYMBOLS = ['%', '$', '¥']
CHINESE_SENTENCE_END = ['。', '？', '！', '；', '\n']


def protect_decimals(content, placeholder="\u2299"):
    """小数点占位符保护"""
    return re.sub(r'(\d+)\.(\d+)', rf'\1{placeholder}\2', content), placeholder


def fix_chinese_spaces(text):
    """中文空格清理"""
    text = re.sub(r'(?<=[\u4e00-\u9fff])\s+(?=[\u4e00-\u9fff])', '', text)
    text = re.sub(r'(?<=[\u4e00-\u9fff])\s+(?=[，。？！；：])', '', text)
    text = re.sub(r'(?<=[，。？！；：])\s+(?=[\u4e00-\u9fff])', '', text)
    return text


def fix_number_format(text):
    """数字格式修复"""
    text = re.sub(r'(\d)\s*,\s*(\d)', r'\1,\2', text)
    text = re.sub(r'(\d)\s*\.\s*(\d)', r'\1.\2', text)
    text = re.sub(r'(\d)\s*%', r'\1%', text)
    text = re.sub(r'(\d)\s+([\u4e00-\u9fff])', r'\1\2', text)
    text = re.sub(r'([\u4e00-\u9fff])\s+(\d)', r'\1\2', text)
    text = re.sub(r'(\d{1,2})\s*:\s*(\d{2})', r'\1:\2', text)
    text = re.sub(r'([A-Za-z0-9])\s*-\s*([A-Za-z0-9])', r'\1-\2', text)
    text = re.sub(r'([A-Za-z])\s*_\s*([A-Za-z])', r'\1_\2', text)
    return text


def recover_missing_numbers(original, compressed):
    """兜底回补"""
    critical_patterns = [
        re.compile(r'[\$¥￥]\s*\d[\d,.]*'),
        re.compile(r'\d+\.?\d*\s*%'),
        re.compile(r'\d{1,2}:\d{2}(?::\d{2})?'),
        re.compile(r'\d{4}-\d{2}-\d{2}'),
        re.compile(r'\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}'),
        re.compile(r'\d[\d,.]*\s*(?:ms|s|GB|MB|Gi|Mi)'),
    ]
    missing = []
    norm = re.sub(r'\s+', '', compressed)
    for p in critical_patterns:
        for m in p.finditer(original):
            v = m.group(0).strip()
            if len(v) >= 2 and re.sub(r'\s+', '', v) not in norm:
                missing.append(v)
    seen = set()
    unique = [x for x in missing if not (x in seen or seen.add(x))]
    return unique


# ═══════════════════════════════════════════════════════════
# 主验证
# ═══════════════════════════════════════════════════════════

def main():
    import torch
    device = "mps" if torch.backends.mps.is_available() else "cpu"

    print("加载 XLM-RoBERTa-large 模型...")
    model = PromptCompressor(
        model_name="./models/llmlingua-2-xlm-roberta-large-meetingbank",
        use_llmlingua2=True,
        device_map=device,
    )
    print(f"模型加载完成 (device={device})\n")

    W = 90
    print("=" * W)
    print("  深度验证: XLM-RoBERTa 下各逻辑步骤必要性")
    print("=" * W)

    # ═══════════════════════════════════════════════════════════
    # 验证 1: _protect_decimals 小数点保护
    # ═══════════════════════════════════════════════════════════
    print(f"\n\n{'━' * W}")
    print("  验证①: _protect_decimals（小数点占位符保护）")
    print(f"{'━' * W}")
    print("  假设: XLM-RoBERTa SentencePiece 不会将小数点拆开，占位符无意义")

    for case in test_cases:
        if not case["decimals"]:
            continue

        # 不保护小数点
        out_raw = model.compress_prompt(
            case["text"], rate=RATE,
            force_tokens=CHINESE_PUNCTUATION + TECH_SYMBOLS + MONEY_SYMBOLS,
            chunk_end_tokens=CHINESE_SENTENCE_END,
            force_reserve_digit=True, drop_consecutive=True,
        )
        raw_text = out_raw["compressed_prompt"]

        # 保护小数点
        protected, ph = protect_decimals(case["text"])
        out_protected = model.compress_prompt(
            protected, rate=RATE,
            force_tokens=CHINESE_PUNCTUATION + TECH_SYMBOLS + MONEY_SYMBOLS + [ph],
            chunk_end_tokens=CHINESE_SENTENCE_END,
            force_reserve_digit=True, drop_consecutive=True,
        )
        protected_text = out_protected["compressed_prompt"].replace(ph, ".")

        # 检查小数是否保留
        raw_decimals = [d for d in case["decimals"] if d in raw_text]
        pro_decimals = [d for d in case["decimals"] if d in protected_text]

        print(f"\n  [{case['name']}] 小数列表: {case['decimals']}")
        print(f"    不保护: 保留 {raw_decimals} ({len(raw_decimals)}/{len(case['decimals'])})")
        print(f"    有保护: 保留 {pro_decimals} ({len(pro_decimals)}/{len(case['decimals'])})")
        diff = len(pro_decimals) - len(raw_decimals)
        print(f"    → 保护增益: {'+' if diff >= 0 else ''}{diff} 项")

    # ═══════════════════════════════════════════════════════════
    # 验证 2: force_tokens 中文标点
    # ═══════════════════════════════════════════════════════════
    print(f"\n\n{'━' * W}")
    print("  验证②: force_tokens 中文标点")
    print(f"{'━' * W}")
    print("  假设: 中文标点作为语义边界仍然重要")

    for case in test_cases[:3]:  # 只测中文相关
        # 有中文标点 force
        out_with = model.compress_prompt(
            case["text"], rate=RATE,
            force_tokens=CHINESE_PUNCTUATION + TECH_SYMBOLS + MONEY_SYMBOLS,
            chunk_end_tokens=CHINESE_SENTENCE_END,
            force_reserve_digit=True, drop_consecutive=True,
        )

        # 无 force_tokens
        out_without = model.compress_prompt(
            case["text"], rate=RATE,
            force_tokens=[],
            chunk_end_tokens=CHINESE_SENTENCE_END,
            force_reserve_digit=True, drop_consecutive=True,
        )

        with_text = out_with["compressed_prompt"]
        without_text = out_without["compressed_prompt"]

        # 统计中文标点保留数量
        cn_puncts = ['。', '，', '？', '！', '；', '：']
        with_punct_count = sum(with_text.count(p) for p in cn_puncts)
        without_punct_count = sum(without_text.count(p) for p in cn_puncts)

        # 统计句子数（以句号分割）
        with_sentences = len([s for s in with_text.split('。') if s.strip()])
        without_sentences = len([s for s in without_text.split('。') if s.strip()])

        print(f"\n  [{case['name']}]")
        print(f"    有force: 标点{with_punct_count}个, 句子{with_sentences}句, tokens={out_with['compressed_tokens']}")
        print(f"    无force: 标点{without_punct_count}个, 句子{without_sentences}句, tokens={out_without['compressed_tokens']}")
        print(f"    有force: {with_text[:80]}")
        print(f"    无force: {without_text[:80]}")

    # ═══════════════════════════════════════════════════════════
    # 验证 3: force_tokens 技术符号
    # ═══════════════════════════════════════════════════════════
    print(f"\n\n{'━' * W}")
    print("  验证③: force_tokens 技术符号（: - _ / = @）")
    print(f"{'━' * W}")

    tech_case = test_cases[1]  # 中英混合故障报告
    # 有技术符号 force
    out_with = model.compress_prompt(
        tech_case["text"], rate=RATE,
        force_tokens=CHINESE_PUNCTUATION + TECH_SYMBOLS + MONEY_SYMBOLS,
        chunk_end_tokens=CHINESE_SENTENCE_END,
        force_reserve_digit=True, drop_consecutive=True,
    )
    # 只有中文标点 force（无技术符号）
    out_without = model.compress_prompt(
        tech_case["text"], rate=RATE,
        force_tokens=CHINESE_PUNCTUATION + MONEY_SYMBOLS,
        chunk_end_tokens=CHINESE_SENTENCE_END,
        force_reserve_digit=True, drop_consecutive=True,
    )

    with_text = out_with["compressed_prompt"]
    without_text = out_without["compressed_prompt"]

    # 检查技术术语完整性
    tech_terms = ["close_date", "limit=1000", "max_connections=200", "B-tree", "2024-01-15", "14:32"]
    with_found = [t for t in tech_terms if t in with_text]
    without_found = [t for t in tech_terms if t in without_text]

    print(f"\n  [{tech_case['name']}]")
    print(f"    监测术语: {tech_terms}")
    print(f"    有技术符号force: 保留 {with_found}")
    print(f"    无技术符号force: 保留 {without_found}")
    print(f"    差异: 有force多保留 {len(with_found) - len(without_found)} 项")
    print(f"    有force: {with_text[:100]}")
    print(f"    无force: {without_text[:100]}")

    # ═══════════════════════════════════════════════════════════
    # 验证 4: force_reserve_digit
    # ═══════════════════════════════════════════════════════════
    print(f"\n\n{'━' * W}")
    print("  验证④: force_reserve_digit=True")
    print(f"{'━' * W}")

    for case in test_cases[:3]:
        out_with = model.compress_prompt(
            case["text"], rate=RATE,
            force_tokens=CHINESE_PUNCTUATION,
            chunk_end_tokens=CHINESE_SENTENCE_END,
            force_reserve_digit=True, drop_consecutive=True,
        )
        out_without = model.compress_prompt(
            case["text"], rate=RATE,
            force_tokens=CHINESE_PUNCTUATION,
            chunk_end_tokens=CHINESE_SENTENCE_END,
            force_reserve_digit=False, drop_consecutive=True,
        )

        orig_digits = extract_digits(case["text"])
        with_digits = extract_digits(out_with["compressed_prompt"])
        without_digits = extract_digits(out_without["compressed_prompt"])

        with_recall = recall(orig_digits, with_digits)
        without_recall = recall(orig_digits, without_digits)

        print(f"\n  [{case['name']}] 原文数字: {len(orig_digits)} 个")
        print(f"    有force_digit: 保留 {len(with_digits)}/{len(orig_digits)} = {with_recall*100:.1f}%")
        print(f"    无force_digit: 保留 {len(without_digits)}/{len(orig_digits)} = {without_recall*100:.1f}%")
        print(f"    → 增益: {(with_recall-without_recall)*100:+.1f}%")

    # ═══════════════════════════════════════════════════════════
    # 验证 5: 中文空格清理
    # ═══════════════════════════════════════════════════════════
    print(f"\n\n{'━' * W}")
    print("  验证⑤: 中文空格清理（汉字间空格移除）")
    print(f"{'━' * W}")
    print("  假设: XLM-RoBERTa 输出不产生汉字间空格，清理无意义")

    for case in test_cases[:3]:
        out = model.compress_prompt(
            case["text"], rate=RATE,
            force_tokens=CHINESE_PUNCTUATION + TECH_SYMBOLS + MONEY_SYMBOLS,
            chunk_end_tokens=CHINESE_SENTENCE_END,
            force_reserve_digit=True, drop_consecutive=True,
        )
        raw_output = out["compressed_prompt"]

        # 统计汉字间空格数量
        cn_space_pattern = re.compile(r'(?<=[\u4e00-\u9fff])\s+(?=[\u4e00-\u9fff])')
        cn_punct_space1 = re.compile(r'(?<=[\u4e00-\u9fff])\s+(?=[，。？！；：])')
        cn_punct_space2 = re.compile(r'(?<=[，。？！；：])\s+(?=[\u4e00-\u9fff])')

        spaces_between_cn = len(cn_space_pattern.findall(raw_output))
        spaces_before_punct = len(cn_punct_space1.findall(raw_output))
        spaces_after_punct = len(cn_punct_space2.findall(raw_output))

        cleaned = fix_chinese_spaces(raw_output)
        chars_removed = len(raw_output) - len(cleaned)

        print(f"\n  [{case['name']}]")
        print(f"    汉字间空格: {spaces_between_cn} 处")
        print(f"    标点前空格: {spaces_before_punct} 处")
        print(f"    标点后空格: {spaces_after_punct} 处")
        print(f"    清理后移除: {chars_removed} 字符")
        print(f"    原始: {raw_output[:80]}")
        print(f"    清理: {cleaned[:80]}")

    # ═══════════════════════════════════════════════════════════
    # 验证 6: 数字格式修复
    # ═══════════════════════════════════════════════════════════
    print(f"\n\n{'━' * W}")
    print("  验证⑥: 数字格式修复（逗号/小数/百分号粘合）")
    print(f"{'━' * W}")
    print("  假设: XLM-RoBERTa 保留完整数字token，格式修复触发极少")

    for case in test_cases[:3]:
        out = model.compress_prompt(
            case["text"], rate=RATE,
            force_tokens=CHINESE_PUNCTUATION + TECH_SYMBOLS + MONEY_SYMBOLS,
            chunk_end_tokens=CHINESE_SENTENCE_END,
            force_reserve_digit=True, drop_consecutive=True,
        )
        raw_output = out["compressed_prompt"]

        # 检测需要修复的模式
        issues = {
            "数字,数字间空格": len(re.findall(r'\d\s+,\s*\d', raw_output)),
            "数字.数字间空格": len(re.findall(r'\d\s+\.\s*\d', raw_output)),
            "数字%间空格": len(re.findall(r'\d\s+%', raw_output)),
            "数字-汉字间空格": len(re.findall(r'\d\s+[\u4e00-\u9fff]', raw_output)),
            "汉字-数字间空格": len(re.findall(r'[\u4e00-\u9fff]\s+\d', raw_output)),
            "时间格式破坏": len(re.findall(r'\d{1,2}\s+:\s*\d{2}', raw_output)),
            "连字符断裂": len(re.findall(r'[A-Za-z0-9]\s+-\s+[A-Za-z0-9]', raw_output)),
            "下划线断裂": len(re.findall(r'[A-Za-z]\s+_\s+[A-Za-z]', raw_output)),
        }

        fixed = fix_number_format(raw_output)
        total_issues = sum(issues.values())

        print(f"\n  [{case['name']}] 格式问题总计: {total_issues} 处")
        for name, count in issues.items():
            if count > 0:
                print(f"    {name}: {count} 处")
        if total_issues == 0:
            print(f"    ✅ 无格式问题")

    # ═══════════════════════════════════════════════════════════
    # 验证 7: _recover_missing_numbers 兜底回补
    # ═══════════════════════════════════════════════════════════
    print(f"\n\n{'━' * W}")
    print("  验证⑦: _recover_missing_numbers 兜底回补")
    print(f"{'━' * W}")
    print("  假设: XLM-RoBERTa 丢失关键数据很少，回补机制触发少")

    for case in test_cases:
        out = model.compress_prompt(
            case["text"], rate=RATE,
            force_tokens=CHINESE_PUNCTUATION + TECH_SYMBOLS + MONEY_SYMBOLS,
            chunk_end_tokens=CHINESE_SENTENCE_END,
            force_reserve_digit=True, drop_consecutive=True,
        )
        compressed = out["compressed_prompt"]
        # 模拟完整后处理
        compressed_clean = fix_chinese_spaces(compressed)
        compressed_clean = fix_number_format(compressed_clean)

        missing = recover_missing_numbers(case["text"], compressed_clean)

        print(f"\n  [{case['name']}]")
        print(f"    缺失项: {len(missing)} 个")
        if missing:
            print(f"    具体: {missing[:8]}")
        else:
            print(f"    ✅ 无缺失")

    # ═══════════════════════════════════════════════════════════
    # 验证 8: use_sentence_level_filter
    # ═══════════════════════════════════════════════════════════
    print(f"\n\n{'━' * W}")
    print("  验证⑧: use_sentence_level_filter + keep_first/last_sentence")
    print(f"{'━' * W}")

    for case in test_cases[:3]:
        # 有 sentence filter
        out_with = model.compress_prompt(
            case["text"], rate=RATE,
            force_tokens=CHINESE_PUNCTUATION,
            chunk_end_tokens=CHINESE_SENTENCE_END,
            force_reserve_digit=True, drop_consecutive=True,
            use_sentence_level_filter=True,
            keep_first_sentence=1, keep_last_sentence=1,
            token_budget_ratio=1.6,
        )
        # 无 sentence filter
        out_without = model.compress_prompt(
            case["text"], rate=RATE,
            force_tokens=CHINESE_PUNCTUATION,
            chunk_end_tokens=CHINESE_SENTENCE_END,
            force_reserve_digit=True, drop_consecutive=True,
        )

        with_text = out_with["compressed_prompt"]
        without_text = out_without["compressed_prompt"]

        # 检查首末句保留
        first_sentence = case["text"].split('。')[0] + '。'
        last_sentence = case["text"].rstrip().rsplit('。', 2)[-2] + '。' if '。' in case["text"] else ""

        # 计算关键术语保留
        orig_terms = extract_key_terms(case["text"], case["key_terms"])
        with_terms = extract_key_terms(with_text, case["key_terms"])
        without_terms = extract_key_terms(without_text, case["key_terms"])

        print(f"\n  [{case['name']}]")
        print(f"    有filter: tokens={out_with['compressed_tokens']}, 术语={len(with_terms)}/{len(orig_terms)}")
        print(f"    无filter: tokens={out_without['compressed_tokens']}, 术语={len(without_terms)}/{len(orig_terms)}")

        # 首句检查
        first_key = first_sentence[:15]
        print(f"    首句('{first_key}...') 有filter={'在' if first_key in with_text else '不在'} | 无filter={'在' if first_key in without_text else '不在'}")
        print(f"    有filter: {with_text[:80]}")
        print(f"    无filter: {without_text[:80]}")

    # ═══════════════════════════════════════════════════════════
    # 验证 9: density_patterns 密度检测
    # ═══════════════════════════════════════════════════════════
    print(f"\n\n{'━' * W}")
    print("  验证⑨: density_patterns 密度拦截")
    print(f"{'━' * W}")
    print("  假设: 高密度文本即使用 XLM-RoBERTa 也不适合压缩")

    density_patterns = [
        re.compile(r'\d[\d,.]*\s*(?:ms|s|GB|MB|Mi|Gi|%|req/s)'),
        re.compile(r'\d{1,2}:\d{2}'),
        re.compile(r'\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}'),
        re.compile(r'[a-z_][\w.]*=[^\s,;]+'),
    ]

    for case in test_cases:
        entity_count = sum(len(p.findall(case["text"])) for p in density_patterns)
        density = entity_count / max(1, len(case["text"]) / 100)

        # 强制压缩高密度文本看效果
        out = model.compress_prompt(
            case["text"], rate=RATE,
            force_tokens=CHINESE_PUNCTUATION + TECH_SYMBOLS + MONEY_SYMBOLS,
            chunk_end_tokens=CHINESE_SENTENCE_END,
            force_reserve_digit=True, drop_consecutive=True,
        )
        compressed = out["compressed_prompt"]
        orig_terms = extract_key_terms(case["text"], case["key_terms"])
        comp_terms = extract_key_terms(compressed, case["key_terms"])
        term_recall = recall(orig_terms, comp_terms)

        missing = recover_missing_numbers(case["text"], compressed)

        action = "跳过" if density > 4 else "保守(0.75)" if density > 2.5 else "中等(0.65)" if density > 1.5 else "标准(0.5)"

        print(f"\n  [{case['name']}]")
        print(f"    密度: {density:.2f} (实体{entity_count}个/{len(case['text'])}字)")
        print(f"    当前策略: {action}")
        print(f"    强制压缩后: 术语保留={term_recall*100:.0f}%, 缺失数据={len(missing)}项")
        if density > 2.5:
            print(f"    → {'⚠️ 确认高密度拦截有效' if len(missing) > 3 or term_recall < 0.5 else '❓ 高密度但压缩效果尚可'}")

    # ═══════════════════════════════════════════════════════════
    # 最终总结
    # ═══════════════════════════════════════════════════════════
    print(f"\n\n{'=' * W}")
    print("  📌 验证总结: XLM-RoBERTa 下各逻辑必要性判定")
    print(f"{'=' * W}")
    print("""
  逻辑步骤                          验证结论                    建议
  ─────────────────────────────────────────────────────────────────────────
  (基于上述实际运行数据总结，见各验证项输出)
""")


if __name__ == "__main__":
    main()
