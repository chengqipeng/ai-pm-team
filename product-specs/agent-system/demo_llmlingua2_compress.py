"""
LLMLingua-2 中文语义压缩 Demo
基于 microsoft/llmlingua-2-xlm-roberta-large-meetingbank

原理：
  将 prompt 压缩建模为 token classification 问题
  用 XLM-RoBERTa-large (双向 Transformer encoder) 预测每个 token 的重要性
  保留高重要性 token，删除低重要性 token
  训练数据来自 GPT-4 对 MeetingBank 的压缩蒸馏

依赖：pip install llmlingua torch transformers
需要 GPU（推荐）或较大内存 CPU（可运行但慢）
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Optional

# ═══════════════════════════════════════════════════════════
# 数据类型
# ═══════════════════════════════════════════════════════════


@dataclass
class CompressResult:
    """压缩结果"""
    compressed: str
    original_tokens: int
    compressed_tokens: int
    ratio: str              # 如 "3.2x"
    savings_pct: str        # 如 "68.5%"
    duration_ms: float
    model_name: str


# ═══════════════════════════════════════════════════════════
# LLMLingua2 中文压缩器
# ═══════════════════════════════════════════════════════════


class LLMLingua2ChineseCompressor:
    """基于 LLMLingua-2 的中文语义压缩器

    核心配置要点：
    1. 使用 xlm-roberta-large 多语言模型（覆盖 100 种语言，中文属于高资源语言）
    2. force_tokens 保留中文标点作为语义边界
    3. chunk_end_tokens 适配中文句号
    4. 支持结构化压缩（对不同部分设置不同压缩率）
    """

    # 中文标点符号（作为语义边界必须保留）
    CHINESE_PUNCTUATION = [
        '。', '？', '！', '；',  # 句末标点
        '，',                     # 逗号（句内边界）
        '：',                     # 冒号（引出关键内容）
        '\n',                     # 换行
    ]

    # 中文句末标点（用于 chunk 分割）
    CHINESE_SENTENCE_END = ['。', '？', '！', '；', '\n']

    def __init__(
        self,
        model_name: str = "microsoft/llmlingua-2-xlm-roberta-large-meetingbank",
        device: str = "auto",
        use_small_model: bool = False,
    ):
        """初始化压缩器

        Args:
            model_name: HuggingFace 模型名称
                - "microsoft/llmlingua-2-xlm-roberta-large-meetingbank" (默认，效果最好)
                - "microsoft/llmlingua-2-bert-base-multilingual-cased-meetingbank" (小模型，更快)
            device: 设备选择
                - "auto": 自动选择（有 GPU 用 GPU，否则 CPU）
                - "cuda": 强制 GPU
                - "mps": Apple Silicon GPU
                - "cpu": CPU（慢但可用）
            use_small_model: 是否使用小模型（bert-base-multilingual）
        """
        if use_small_model:
            model_name = "microsoft/llmlingua-2-bert-base-multilingual-cased-meetingbank"

        if device == "auto":
            import torch
            if torch.cuda.is_available():
                device = "cuda"
            elif hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
                device = "mps"
            else:
                device = "cpu"

        self.model_name = model_name
        self.device = device

        print(f"[LLMLingua2] 加载模型: {model_name}")
        print(f"[LLMLingua2] 设备: {device}")

        from llmlingua import PromptCompressor

        self.compressor = PromptCompressor(
            model_name=model_name,
            use_llmlingua2=True,
            device_map=device,
        )
        print("[LLMLingua2] 模型加载完成")

    def compress(
        self,
        text: str,
        rate: float = 0.5,
        target_token: int = -1,
        force_tokens: Optional[list[str]] = None,
        chunk_end_tokens: Optional[list[str]] = None,
        force_reserve_digit: bool = True,
        drop_consecutive: bool = True,
        context_level_rate: float = 1.0,
    ) -> CompressResult:
        """压缩中文文本

        Args:
            text: 要压缩的中文文本
            rate: 压缩率（0.5 = 保留 50% 的 token）
                - 0.3: 激进压缩（适合长文档概要）
                - 0.5: 平衡压缩（默认推荐）
                - 0.7: 保守压缩（适合重要内容）
            target_token: 目标 token 数（与 rate 互斥，-1 表示使用 rate）
            force_tokens: 强制保留的 token 列表
                - 默认保留中文标点作为语义边界
            chunk_end_tokens: 分块结束标记
                - 默认使用中文句号和换行
            force_reserve_digit: 是否强制保留包含数字的 token（推荐开启）
            drop_consecutive: 是否丢弃连续出现的 force_tokens（避免连续标点）
            context_level_rate: 上下文级压缩率（1.0 = 不做上下文级压缩）

        Returns:
            CompressResult
        """
        t0 = time.perf_counter()

        # 设置默认的中文 force_tokens
        if force_tokens is None:
            force_tokens = self.CHINESE_PUNCTUATION

        # 设置默认的中文 chunk_end_tokens
        if chunk_end_tokens is None:
            chunk_end_tokens = self.CHINESE_SENTENCE_END

        # 调用 LLMLingua-2 压缩
        result = self.compressor.compress_prompt(
            text,
            rate=rate,
            target_token=target_token,
            force_tokens=force_tokens,
            chunk_end_tokens=chunk_end_tokens,
            force_reserve_digit=force_reserve_digit,
            drop_consecutive=drop_consecutive,
            context_level_rate=context_level_rate,
        )

        duration_ms = (time.perf_counter() - t0) * 1000

        return CompressResult(
            compressed=result["compressed_prompt"],
            original_tokens=result["origin_tokens"],
            compressed_tokens=result["compressed_tokens"],
            ratio=result["ratio"],
            savings_pct=f"{(1 - result['compressed_tokens']/result['origin_tokens']) * 100:.1f}%",
            duration_ms=duration_ms,
            model_name=self.model_name,
        )

    def compress_structured(
        self,
        text: str,
        instruction: str = "",
        question: str = "",
        rate: float = 0.5,
    ) -> CompressResult:
        """结构化压缩 — 对指令/问题不压缩，仅压缩上下文内容

        适用场景：RAG 检索结果压缩、Agent 对话历史压缩

        Args:
            text: 上下文内容（会被压缩）
            instruction: 系统指令（不压缩）
            question: 用户问题（不压缩）
            rate: 上下文的压缩率
        """
        t0 = time.perf_counter()

        # 使用结构化标记
        # instruction 和 question 设为不压缩，context 按 rate 压缩
        structured_prompt = ""

        if instruction:
            structured_prompt += f"<llmlingua, compress=False>{instruction}</llmlingua>"

        structured_prompt += f"<llmlingua, rate={rate}>{text}</llmlingua>"

        if question:
            structured_prompt += f"<llmlingua, compress=False>{question}</llmlingua>"

        result = self.compressor.structured_compress_prompt(
            structured_prompt,
            instruction="",
            question="",
            rate=rate,
            force_tokens=self.CHINESE_PUNCTUATION,
            chunk_end_tokens=self.CHINESE_SENTENCE_END,
            force_reserve_digit=True,
            drop_consecutive=True,
        )

        duration_ms = (time.perf_counter() - t0) * 1000

        return CompressResult(
            compressed=result["compressed_prompt"],
            original_tokens=result["origin_tokens"],
            compressed_tokens=result["compressed_tokens"],
            ratio=result["ratio"],
            savings_pct=f"{(1 - result['compressed_tokens']/result['origin_tokens']) * 100:.1f}%",
            duration_ms=duration_ms,
            model_name=self.model_name,
        )

    def compress_with_labels(
        self,
        text: str,
        rate: float = 0.5,
    ) -> tuple[CompressResult, str]:
        """压缩并返回逐词标注（用于分析和调试）

        返回每个词及其保留/删除标签，方便观察模型在中文上的判断逻辑。

        Returns:
            (CompressResult, labeled_prompt)
            labeled_prompt 格式: "word1 1\t\t|\t\tword2 0\t\t|\t\t..."
            其中 1=保留, 0=删除
        """
        t0 = time.perf_counter()

        result = self.compressor.compress_prompt(
            text,
            rate=rate,
            force_tokens=self.CHINESE_PUNCTUATION,
            chunk_end_tokens=self.CHINESE_SENTENCE_END,
            force_reserve_digit=True,
            drop_consecutive=True,
            return_word_label=True,
        )

        duration_ms = (time.perf_counter() - t0) * 1000

        compress_result = CompressResult(
            compressed=result["compressed_prompt"],
            original_tokens=result["origin_tokens"],
            compressed_tokens=result["compressed_tokens"],
            ratio=result["ratio"],
            savings_pct=f"{(1 - result['compressed_tokens']/result['origin_tokens']) * 100:.1f}%",
            duration_ms=duration_ms,
            model_name=self.model_name,
        )

        labeled = result.get("fn_labeled_original_prompt", "")
        return compress_result, labeled


# ═══════════════════════════════════════════════════════════
# Demo
# ═══════════════════════════════════════════════════════════


def demo():
    """运行 LLMLingua-2 中文压缩 demo"""
    print("=" * 70)
    print("LLMLingua-2 中文语义压缩 Demo")
    print("模型: xlm-roberta-large (token classification for compression)")
    print("=" * 70)

    # 初始化压缩器
    try:
        compressor = LLMLingua2ChineseCompressor(
            device="auto",
            use_small_model=False,  # 改为 True 可用小模型（更快但效果稍差）
        )
    except ImportError as e:
        print(f"\n❌ 缺少依赖: {e}")
        print("\n请安装依赖:")
        print("  pip install llmlingua torch transformers")
        print("\n如果只需要 CPU 推理（较慢但可用）:")
        print("  pip install llmlingua torch --index-url https://download.pytorch.org/whl/cpu transformers")
        return

    # ── 测试用例 ──
    test_cases = [
        {
            "name": "中文业务报告（CRM 分析）",
            "text": """2024年第三季度CRM系统运营报告总结如下。本季度系统共新增客户1,234家，其中大客户52家，中小客户1,182家。主要客户来源集中在华东和华南地区，华东地区贡献了45%的新增客户。总合同金额达到¥5,680万，同比增长23%，环比增长8%。值得注意的是，新签约的金融行业客户贡献了35%的增量收入，这主要得益于Q2推出的金融解决方案包。客户流失率方面，本季度流失率为3.2%，较上季度的4.1%有明显改善。流失客户主要集中在年合同金额低于5万的小微客户群体。客户满意度调查结果显示，NPS评分从上季度的42分提升至48分，其中产品功能满意度最高，达到4.5分（5分制）。技术支持响应速度从平均4.2小时缩短至2.8小时，提升了33%。另外需要说明的是，系统在9月15日进行了一次大版本升级，升级过程中出现了约2小时的服务中断，影响了约350家客户的正常使用。事后已向受影响客户发送了致歉邮件并提供了一个月的服务延期补偿。总体来看，本季度各项核心指标均保持健康增长态势，建议Q4重点关注金融行业的深度拓展以及小微客户的留存策略优化。""",
            "rates": [0.3, 0.5, 0.7],
        },
        {
            "name": "中英混合 Agent 对话（查询失败分析）",
            "text": """在执行query_data工具时遇到了一个预期之外的问题。系统尝试查询CRM模块中的Opportunity对象，使用的过滤条件是stage='Closed Won' AND close_date >= '2024-01-01'。查询请求发送到后端API后，收到了HTTP 504 Gateway Timeout错误，响应时间超过了30秒的默认超时阈值。经过分析，这个超时的根本原因是数据库层面的性能问题。Opportunity表目前有超过280万条记录，而close_date字段上缺少索引。全表扫描导致查询耗时超过了预期。另外值得一提的是，同一时间段内有一个定时任务正在执行数据同步，占用了大量的数据库连接池资源。临时的解决方案是添加查询分页limit=1000，并在close_date字段上创建B-tree索引。长期建议是引入读写分离架构，将此类分析查询路由到只读副本。目前已经通过reduce scope的方式成功获取到了部分数据，返回了Q1季度的823条Closed Won记录，总金额$12.4M。""",
            "rates": [0.3, 0.5, 0.7],
        },
        {
            "name": "中文会议纪要",
            "text": """产品评审会议纪要，2024年10月15日下午2点，参会人员：张明（产品）、李芳（研发）、王强（设计）、赵丽（测试）。会议议题一：新版本发布计划讨论。张明介绍了V3.2版本的核心功能，包括多租户权限隔离、自定义工作流引擎、以及数据导入导出优化。预计11月20日进入公测，12月15日正式发布。李芳反馈研发侧目前还有3个P1级别的技术债务需要处理，分别是消息队列的积压问题、缓存穿透的防护机制、以及日志系统的存储优化。预估需要额外2周的开发时间。王强展示了新版本的UI设计稿，主要变化是导航栏从顶部改为侧边栏布局，工作区面积增大了25%。赵丽表示测试用例已覆盖核心流程的85%，还需要补充边界场景和性能测试用例约200条。会议决议：正式发布时间推迟至12月30日，李芳团队优先处理消息队列积压问题，王强下周三前提交最终设计稿供评审。""",
            "rates": [0.5],
        },
    ]

    for i, case in enumerate(test_cases, 1):
        print(f"\n{'═' * 70}")
        print(f"测试 {i}: {case['name']}")
        print(f"原文长度: {len(case['text'])} 字符")
        print(f"{'═' * 70}")

        for rate in case["rates"]:
            result = compressor.compress(
                text=case["text"],
                rate=rate,
            )

            print(f"\n  ── 压缩率 rate={rate} ──")
            print(f"  Token: {result.original_tokens} → {result.compressed_tokens} ({result.ratio} 压缩)")
            print(f"  节省: {result.savings_pct}")
            print(f"  耗时: {result.duration_ms:.1f}ms")
            print(f"  结果: {result.compressed[:200]}{'...' if len(result.compressed) > 200 else ''}")

    # ── 带标注的压缩（调试用）──
    print(f"\n{'═' * 70}")
    print("调试模式：逐词保留/删除标注")
    print(f"{'═' * 70}")

    short_text = "客户满意度调查结果显示，NPS评分从上季度的42分提升至48分，其中产品功能满意度最高，达到4.5分。"
    result, labeled = compressor.compress_with_labels(short_text, rate=0.5)

    print(f"\n原文: {short_text}")
    print(f"压缩: {result.compressed}")
    print(f"\n逐词标注 (1=保留, 0=删除):")

    if labeled:
        # 解析标注结果
        word_sep = '\t\t|\t\t'
        label_sep = ' '
        pairs = labeled.split(word_sep)
        kept_words = []
        dropped_words = []
        for pair in pairs[:50]:  # 只显示前 50 个
            parts = pair.rsplit(label_sep, 1)
            if len(parts) == 2:
                word, label = parts
                if label.strip() == '1':
                    kept_words.append(word)
                else:
                    dropped_words.append(word)

        print(f"  保留 ({len(kept_words)}): {'|'.join(kept_words[:30])}")
        print(f"  删除 ({len(dropped_words)}): {'|'.join(dropped_words[:30])}")

    # ── 结构化压缩示例 ──
    print(f"\n{'═' * 70}")
    print("结构化压缩：指令不压缩 + 上下文压缩 + 问题不压缩")
    print(f"{'═' * 70}")

    context_text = """本季度系统共新增客户1,234家，其中大客户52家，中小客户1,182家。主要客户来源集中在华东和华南地区，华东地区贡献了45%的新增客户。总合同金额达到¥5,680万，同比增长23%，环比增长8%。客户流失率方面，本季度流失率为3.2%，较上季度的4.1%有明显改善。"""
    instruction = "你是一个数据分析助手，请根据以下信息回答问题。"
    question = "本季度新增了多少客户？增长率是多少？"

    result = compressor.compress_structured(
        text=context_text,
        instruction=instruction,
        question=question,
        rate=0.5,
    )

    print(f"\n  指令（不压缩）: {instruction}")
    print(f"  问题（不压缩）: {question}")
    print(f"  上下文（压缩 rate=0.5）:")
    print(f"    原文: {context_text[:100]}...")
    print(f"    压缩: {result.compressed[:200]}")
    print(f"  Token: {result.original_tokens} → {result.compressed_tokens}")
    print(f"  耗时: {result.duration_ms:.1f}ms")


# ═══════════════════════════════════════════════════════════
# 配置建议
# ═══════════════════════════════════════════════════════════

CHINESE_COMPRESSION_CONFIGS = {
    "conservative": {
        "description": "保守压缩 — 适合重要文档、合同、法律文本",
        "rate": 0.7,
        "force_tokens": ['。', '？', '！', '；', '，', '：', '\n'],
        "force_reserve_digit": True,
        "drop_consecutive": True,
    },
    "balanced": {
        "description": "平衡压缩 — 适合会议纪要、业务报告、邮件",
        "rate": 0.5,
        "force_tokens": ['。', '？', '！', '；', '\n'],
        "force_reserve_digit": True,
        "drop_consecutive": True,
    },
    "aggressive": {
        "description": "激进压缩 — 适合长文档概要、日志、Agent历史",
        "rate": 0.33,
        "force_tokens": ['。', '\n'],
        "force_reserve_digit": True,
        "drop_consecutive": True,
    },
    "agent_context": {
        "description": "Agent 上下文压缩 — 适合对话历史、工具输出",
        "rate": 0.4,
        "force_tokens": ['。', '？', '\n', ':', '='],
        "force_reserve_digit": True,
        "drop_consecutive": True,
    },
}


def print_configs():
    """打印推荐配置"""
    print("\n推荐的中文压缩配置:")
    print("=" * 60)
    for name, config in CHINESE_COMPRESSION_CONFIGS.items():
        print(f"\n  [{name}]")
        print(f"  {config['description']}")
        print(f"  rate={config['rate']}, force_tokens={config['force_tokens']}")


if __name__ == "__main__":
    demo()
