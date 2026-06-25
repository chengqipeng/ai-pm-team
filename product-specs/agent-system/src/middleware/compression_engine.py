"""统一压缩引擎 — 系统中所有内容块压缩的唯一入口

设计原则：
  1. 单一入口：所有 ToolMessage / 文件内容 / 日志 的压缩都通过此模块
  2. 分级压缩：LIGHT / STANDARD / AGGRESSIVE / SUMMARY_ONLY 四级
  3. Headroom 优先、CRM 规则降级：有 headroom 走 ContentRouter，无则走旧规则摘要
  4. 全链路 tracing：每次压缩记录 span
  5. 统一配置：工具级 bias / 最小字符数 / 最大字符数 全部集中管理

调用链路：
  - ContextWindowMiddleware.awrap_tool_call → engine.compress(level=LIGHT)
  - ContextWindowMiddleware._micro_compact → engine.compress(level=STANDARD)
  - ContextWindowMiddleware._headroom_pre_compress → engine.compress(level=STANDARD)
  - skill_compress.post_skill_compact → engine.compress(level=AGGRESSIVE)
  - Tool.call() 超长输出 → engine.compress(level=LIGHT, max_chars=50000)
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════
# 公共类型定义
# ═══════════════════════════════════════════════════════════


class CompressLevel(str, Enum):
    """压缩力度级别

    LIGHT: 仅做内容类型感知的智能压缩（Headroom ContentRouter），保留最多信息。
           用于当前轮次的工具输出（LLM 仍需完整理解）。
    STANDARD: 标准压缩 + 超长截断。用于历史轮次的 ToolMessage。
    AGGRESSIVE: 激进压缩（低 bias）。用于 Skill 内部中间步骤。
    SUMMARY_ONLY: 极致压缩 → 一行摘要。用于 Headroom 不可用时的最终降级。
    """
    LIGHT = "light"
    STANDARD = "standard"
    AGGRESSIVE = "aggressive"
    SUMMARY_ONLY = "summary"


@dataclass
class CompressedResult:
    """统一的压缩结果"""
    content: str                    # 压缩后内容
    original_chars: int = 0         # 原始字符数
    compressed_chars: int = 0       # 压缩后字符数
    strategy: str = "passthrough"   # 使用的策略名
    ratio: float = 1.0             # 压缩率 (compressed/original, <1 表示有压缩)
    level: CompressLevel = CompressLevel.STANDARD
    duration_ms: float = 0.0       # 压缩耗时

    @property
    def savings_pct(self) -> float:
        """节省百分比"""
        return round((1 - self.ratio) * 100, 1) if self.ratio < 1.0 else 0.0

    @property
    def is_compressed(self) -> bool:
        """是否实际发生了压缩"""
        return self.ratio < 0.95 and self.compressed_chars < self.original_chars


# ═══════════════════════════════════════════════════════════
# 工具级配置
# ═══════════════════════════════════════════════════════════

# 每个工具的压缩 bias（>1 保守, <1 激进, =1 标准）
TOOL_BIAS: dict[str, float] = {
    "query_data": 1.0,
    "query_schema": 0.8,
    "web_search": 0.7,
    "knowledge_search": 1.2,
    "knowledge_doc_detail": 1.2,
    "terminal": 0.6,
    "execute_code": 0.8,
    "read_file": 1.0,
    "write_file": 1.0,
    "search_files": 0.8,
    "analyze_data": 1.2,
    "modify_data": 1.0,
    "browse_metamodel": 0.8,
    "query_metadata": 0.8,
}

# 不应被压缩的工具（输出必须完整保留）
SKIP_TOOLS: frozenset[str] = frozenset({
    "skills_tool",
    "agent_tool",
    "ask_user",
    "ask_clarification",
    "read_skill_resource",
    "manage_memory",
    "memory_read",
})

# 各级别对应的最大输出字符数（超出时做截断兜底）
LEVEL_MAX_CHARS: dict[CompressLevel, int] = {
    CompressLevel.LIGHT: 20_000,       # 当前轮次：宽松
    CompressLevel.STANDARD: 5_000,     # 历史轮次：适中
    CompressLevel.AGGRESSIVE: 2_000,   # Skill 内部：紧凑
    CompressLevel.SUMMARY_ONLY: 500,   # 一行摘要：极短
}

# 各级别对应的 bias 乘数（叠加在工具 bias 之上）
LEVEL_BIAS_MULTIPLIER: dict[CompressLevel, float] = {
    CompressLevel.LIGHT: 1.2,          # 保守：保留更多
    CompressLevel.STANDARD: 1.0,       # 标准
    CompressLevel.AGGRESSIVE: 0.7,     # 激进：压缩更多
    CompressLevel.SUMMARY_ONLY: 0.4,   # 极致
}


# ═══════════════════════════════════════════════════════════
# LLMLingua-2 配置
# ═══════════════════════════════════════════════════════════

# 密度检测模式 — 匹配高信息密度 token（数值+单位、时间、IP、kv 赋值）
# 密度超过阈值的文本不适合语义压缩
LLMLINGUA_DENSITY_PATTERNS: list[str] = [
    r'\d[\d,.]*\s*(?:ms|s|GB|MB|Mi|Gi|%|req/s)',   # 带单位数值
    r'\d{1,2}:\d{2}',                               # 时间 HH:MM
    r'\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}',         # IP 地址
    r'[a-z_][\w.]*=[^\s,;]+',                       # key=value 赋值
]

# 密度 → rate 映射阈值
LLMLINGUA_DENSITY_THRESHOLDS: dict[str, float] = {
    "skip": 4.0,       # 超过此值 → 跳过压缩
    "high": 2.5,       # 超过此值 → rate=0.75（保守）
    "medium": 1.5,     # 超过此值 → rate=0.65（中等）
    # 低于 medium → rate=0.5（标准）
}

LLMLINGUA_DENSITY_RATES: dict[str, float] = {
    "high": 0.75,
    "medium": 0.65,
    "low": 0.5,
}

# 兜底回补模式 — 压缩后若丢失这些模式匹配的数据，则在末尾回补
LLMLINGUA_RECOVER_PATTERNS: list[str] = [
    r'[\$¥￥]\s*\d[\d,.]*',                          # 金额
    r'\d+\.?\d*\s*%',                                 # 百分比
    r'\d{1,2}:\d{2}(?::\d{2})?',                     # 时间
    r'\d{4}-\d{2}-\d{2}',                            # 日期
    r'\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}',          # IP
    r'\d[\d,.]*\s*(?:ms|s|GB|MB|Gi|Mi)',             # 带单位数值
]

# 最多回补项数
LLMLINGUA_RECOVER_MAX: int = 5

# force_tokens — 压缩时强制保留的 token
LLMLINGUA_FORCE_TOKENS: list[str] = [
    '。', '？', '！', '；', '，', '：', '\n',  # 中文标点（语义边界）
    '=', '_', '-',                              # 技术符号
]

# chunk 分割标记
LLMLINGUA_CHUNK_END_TOKENS: list[str] = ['。', '？', '！', '；', '\n']


# ═══════════════════════════════════════════════════════════
# 统一压缩引擎
# ═══════════════════════════════════════════════════════════


class CompressionEngine:
    """统一压缩引擎 — 进程单例

    所有内容块压缩的唯一入口。内部封装：
    1. Headroom ContentRouter（主路径：6 种算法自动路由）
    2. CRM 规则摘要（降级路径：Headroom 不可用时）
    3. 硬截断（最终兜底）

    使用方式：
        engine = CompressionEngine.get_instance()
        result = engine.compress(content, tool_name="query_data", level=CompressLevel.STANDARD)
    """

    _instance: "CompressionEngine | None" = None
    _lock = threading.Lock()

    def __init__(self):
        self._headroom_router = None
        self._headroom_available: bool | None = None
        self._init_lock = threading.Lock()
        # LLMLingua-2 语义压缩器
        self._llmlingua_compressor = None
        self._llmlingua_available: bool | None = None
        self._llmlingua_lock = threading.Lock()
        # 统计
        self._total_calls = 0
        self._total_compressed = 0
        self._total_original_chars = 0
        self._total_compressed_chars = 0
        self._by_strategy: dict[str, int] = {}
        self._by_level: dict[str, int] = {}

    @classmethod
    def get_instance(cls) -> "CompressionEngine":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        """重置单例（测试用）"""
        with cls._lock:
            cls._instance = None

    # ─── 核心压缩方法 ─────────────────────────────────────────

    def compress(
        self,
        content: str,
        tool_name: str = "",
        context: str = "",
        level: CompressLevel = CompressLevel.STANDARD,
        max_chars: int | None = None,
    ) -> CompressedResult:
        """统一压缩入口

        Args:
            content: 要压缩的内容
            tool_name: 工具名称（影响 bias 选择 + 跳过判断）
            context: 用户当前问题（用于 Headroom 相关性评分）
            level: 压缩力度级别
            max_chars: 覆盖默认的最大字符数（None=使用级别默认值）

        Returns:
            CompressedResult
        """
        self._total_calls += 1
        self._by_level[level.value] = self._by_level.get(level.value, 0) + 1
        original_chars = len(content) if content else 0

        # ── 前置检查 ──
        if not content or not content.strip():
            return CompressedResult(content=content or "", strategy="empty")

        if tool_name in SKIP_TOOLS:
            return CompressedResult(
                content=content, original_chars=original_chars,
                compressed_chars=original_chars, strategy="skip_tool",
                ratio=1.0, level=level,
            )

        # 最小压缩阈值：太短的内容不值得压缩
        min_chars = 300 if level == CompressLevel.LIGHT else 150
        if original_chars < min_chars:
            return CompressedResult(
                content=content, original_chars=original_chars,
                compressed_chars=original_chars, strategy="too_short",
                ratio=1.0, level=level,
            )

        # 错误输出保护
        if self._is_error_output(content):
            effective_max = max_chars or LEVEL_MAX_CHARS[level]
            if original_chars <= effective_max:
                return CompressedResult(
                    content=content, original_chars=original_chars,
                    compressed_chars=original_chars, strategy="error_protected",
                    ratio=1.0, level=level,
                )

        t0 = time.perf_counter()

        # ── 主压缩路径 ──
        result = self._do_compress(content, tool_name, context, level, max_chars)

        result.duration_ms = (time.perf_counter() - t0) * 1000
        result.level = level

        # 统计
        if result.is_compressed:
            self._total_compressed += 1
            self._total_original_chars += result.original_chars
            self._total_compressed_chars += result.compressed_chars
        self._by_strategy[result.strategy] = self._by_strategy.get(result.strategy, 0) + 1

        return result

    def _do_compress(
        self,
        content: str,
        tool_name: str,
        context: str,
        level: CompressLevel,
        max_chars: int | None,
    ) -> CompressedResult:
        """内部压缩执行（三级降级链）

        降级链路：
          1. Headroom ContentRouter（零 LLM，6 种算法自动路由）
          2. CRM 规则摘要（零 LLM，手写规则按工具类型分发）
          3. 硬截断兜底（保留前 N 字符）
        """
        original_chars = len(content)
        effective_max = max_chars or LEVEL_MAX_CHARS[level]

        # 计算最终 bias
        tool_bias = TOOL_BIAS.get(tool_name, 1.0)
        level_multiplier = LEVEL_BIAS_MULTIPLIER[level]
        final_bias = tool_bias * level_multiplier

        # ── 路径 1: Headroom（主路径）──
        headroom_result = self._try_headroom(content, context, final_bias)
        if headroom_result is not None:
            compressed, ratio, strategy = headroom_result
            # Headroom 压缩有效
            if ratio < 0.95 and compressed and compressed.strip():
                # 如果压缩后仍超 max_chars，做二次截断
                if len(compressed) > effective_max:
                    compressed = self._truncate_smart(compressed, effective_max, tool_name)
                    strategy = f"headroom:{strategy}+truncate"
                return CompressedResult(
                    content=compressed,
                    original_chars=original_chars,
                    compressed_chars=len(compressed),
                    strategy=f"headroom:{strategy}",
                    ratio=len(compressed) / original_chars,
                )

        # ── 路径 1.5: LLMLingua-2 语义压缩（Headroom 失败时的替代路径）──
        # 仅对 STANDARD/AGGRESSIVE 级别启用（延迟 ~140ms，不适合 LIGHT 实时路径）
        if (
            level in (CompressLevel.STANDARD, CompressLevel.AGGRESSIVE)
            and os.environ.get("LLMLINGUA_ENABLED", "0") == "1"
            and original_chars >= 200
        ):
            llmlingua_result = self._try_llmlingua(content, context, final_bias)
            if llmlingua_result is not None:
                compressed, ratio, strategy = llmlingua_result
                if ratio < 0.95 and compressed and compressed.strip():
                    if len(compressed) > effective_max:
                        compressed = self._truncate_smart(compressed, effective_max, tool_name)
                        strategy = "llmlingua2+truncate"
                    return CompressedResult(
                        content=compressed,
                        original_chars=original_chars,
                        compressed_chars=len(compressed),
                        strategy=strategy,
                        ratio=len(compressed) / original_chars,
                    )

        # ── 路径 2: CRM 规则摘要（降级）──
        if level in (CompressLevel.AGGRESSIVE, CompressLevel.SUMMARY_ONLY):
            summary = self._crm_one_liner(content, tool_name)
            if summary and len(summary) < original_chars * 0.8:
                return CompressedResult(
                    content=summary,
                    original_chars=original_chars,
                    compressed_chars=len(summary),
                    strategy="crm_one_liner",
                    ratio=len(summary) / original_chars,
                )

        # STANDARD/LIGHT 级别如果 Headroom 失败，尝试 CRM 规则但要求保留更多
        if level == CompressLevel.STANDARD and original_chars > effective_max:
            summary = self._crm_one_liner(content, tool_name)
            if summary and len(summary) < original_chars * 0.9:
                return CompressedResult(
                    content=summary,
                    original_chars=original_chars,
                    compressed_chars=len(summary),
                    strategy="crm_one_liner",
                    ratio=len(summary) / original_chars,
                )

        # ── 路径 3: 硬截断兜底 ──
        if original_chars > effective_max:
            truncated = self._truncate_smart(content, effective_max, tool_name)
            return CompressedResult(
                content=truncated,
                original_chars=original_chars,
                compressed_chars=len(truncated),
                strategy="truncate",
                ratio=len(truncated) / original_chars,
            )

        # 不需要压缩
        return CompressedResult(
            content=content,
            original_chars=original_chars,
            compressed_chars=original_chars,
            strategy="passthrough",
            ratio=1.0,
        )

    # ─── Headroom 路径 ────────────────────────────────────────

    def _try_headroom(
        self, content: str, context: str, bias: float
    ) -> tuple[str, float, str] | None:
        """尝试 Headroom 压缩，返回 (compressed, ratio, strategy_name) 或 None"""
        router = self._ensure_headroom()
        if router is None:
            return None

        try:
            result = router.compress(content, context=context, bias=bias)

            if not result.compressed or not result.compressed.strip():
                return None

            ratio = result.compression_ratio
            strategy = (
                result.strategy_used.value
                if hasattr(result.strategy_used, "value")
                else str(result.strategy_used)
            )

            # passthrough 不算压缩成功
            if strategy == "passthrough" or ratio >= 0.95:
                return None

            return result.compressed, ratio, strategy

        except Exception as e:
            logger.debug("[CompressionEngine] Headroom 压缩异常: %s", e)
            return None

    def _ensure_headroom(self):
        """延迟初始化 Headroom ContentRouter"""
        if self._headroom_router is not None:
            return self._headroom_router
        if self._headroom_available is False:
            return None

        with self._init_lock:
            if self._headroom_router is not None:
                return self._headroom_router
            if self._headroom_available is False:
                return None

            try:
                from headroom.transforms import ContentRouter, ContentRouterConfig

                config = ContentRouterConfig(
                    enable_smart_crusher=True,
                    enable_code_aware=True,
                    enable_kompress=False,  # 禁用：Kompress 依赖 ModernBERT，项目不引入该模型
                    enable_search_compressor=True,
                    enable_log_compressor=True,
                    enable_html_extractor=True,
                    ccr_enabled=False,
                    ccr_inject_marker=False,
                    protect_error_outputs=True,
                    skip_user_messages=False,
                    min_chars_for_block_compression=200,
                )
                self._headroom_router = ContentRouter(config=config)
                self._headroom_available = True
                logger.info("[CompressionEngine] Headroom 初始化成功")
                return self._headroom_router

            except ImportError:
                self._headroom_available = False
                logger.info("[CompressionEngine] headroom-ai 未安装，使用 CRM 规则降级")
                return None
            except Exception as e:
                self._headroom_available = False
                logger.warning("[CompressionEngine] Headroom 初始化失败: %s", e)
                return None

    # ─── LLMLingua-2 语义压缩路径 ──────────────────────────────

    def _try_llmlingua(
        self, content: str, context: str, bias: float
    ) -> tuple[str, float, str] | None:
        """LLMLingua-2 语义压缩 (XLM-RoBERTa-large)

        设计原则：
          1. 密度检测 → 高密度文本跳过或保守压缩
          2. force_tokens 中文标点保持语义边界
          3. 兜底回补丢失的关键数值

        配置项（模块级常量，可按需调整）：
          - LLMLINGUA_DENSITY_PATTERNS: 密度检测正则
          - LLMLINGUA_DENSITY_THRESHOLDS: 密度阈值
          - LLMLINGUA_DENSITY_RATES: 各密度档位对应 rate
          - LLMLINGUA_FORCE_TOKENS: 强制保留 token
          - LLMLINGUA_RECOVER_PATTERNS: 兜底回补正则
          - LLMLINGUA_RECOVER_MAX: 最大回补项数
        """
        compressor = self._ensure_llmlingua()
        if compressor is None:
            return None

        try:
            # ── 步骤 1: 内容密度检测 → 动态 rate ──
            compiled_density = [re.compile(p) for p in LLMLINGUA_DENSITY_PATTERNS]
            entity_count = sum(len(p.findall(content)) for p in compiled_density)
            density = entity_count / max(1, len(content) / 100)

            if density > LLMLINGUA_DENSITY_THRESHOLDS["skip"]:
                return None
            elif density > LLMLINGUA_DENSITY_THRESHOLDS["high"]:
                base_rate = LLMLINGUA_DENSITY_RATES["high"]
            elif density > LLMLINGUA_DENSITY_THRESHOLDS["medium"]:
                base_rate = LLMLINGUA_DENSITY_RATES["medium"]
            else:
                base_rate = LLMLINGUA_DENSITY_RATES["low"]

            rate = min(0.85, max(0.35, base_rate * bias))

            # ── 步骤 2: 调用 LLMLingua-2 ──
            result = compressor.compress_prompt(
                content,
                rate=rate,
                force_tokens=LLMLINGUA_FORCE_TOKENS,
                chunk_end_tokens=LLMLINGUA_CHUNK_END_TOKENS,
                drop_consecutive=True,
            )

            compressed = result.get("compressed_prompt", "")
            if not compressed or not compressed.strip():
                return None

            # ── 步骤 3: 轻量后处理 ──
            compressed = re.sub(r'(?<=[。！？；])\s+(?=[\u4e00-\u9fff])', '', compressed)

            # ── 步骤 4: 兜底回补 ──
            compressed = self._recover_missing_numbers(content, compressed)

            ratio = len(compressed) / len(content) if len(content) > 0 else 1.0

            if ratio >= 0.95:
                return None

            return compressed, ratio, "llmlingua2"

        except Exception as e:
            logger.debug("[CompressionEngine] LLMLingua-2 压缩异常: %s", e)
            return None

    @staticmethod
    def _recover_missing_numbers(original: str, compressed: str) -> str:
        """兜底回补：检测压缩后丢失的关键数值并追加到末尾

        使用 LLMLINGUA_RECOVER_PATTERNS 配置回补模式，
        LLMLINGUA_RECOVER_MAX 控制最大回补项数。
        """
        compiled_recover = [re.compile(p) for p in LLMLINGUA_RECOVER_PATTERNS]

        missing: list[str] = []
        normalized_compressed = re.sub(r'\s+', '', compressed)

        for pattern in compiled_recover:
            for match in pattern.finditer(original):
                value = match.group(0).strip()
                if len(value) < 2:
                    continue
                if re.sub(r'\s+', '', value) not in normalized_compressed:
                    missing.append(value)

        # 去重
        seen: set[str] = set()
        unique_missing = []
        for item in missing:
            if item not in seen:
                seen.add(item)
                unique_missing.append(item)

        if unique_missing:
            to_recover = unique_missing[:LLMLINGUA_RECOVER_MAX]
            compressed += " [回补: " + ", ".join(to_recover) + "]"
            if len(unique_missing) > LLMLINGUA_RECOVER_MAX:
                logger.warning(
                    "[CompressionEngine] LLMLingua-2 缺失 %d 项（>%d），"
                    "该文本数据密度可能过高",
                    len(unique_missing),
                    LLMLINGUA_RECOVER_MAX,
                )

        return compressed

    def _ensure_llmlingua(self):
        """延迟初始化 LLMLingua-2 PromptCompressor (XLM-RoBERTa-large)

        支持三种推理模式（通过环境变量切换）：
          1. PyTorch FP32:  默认模式
          2. PyTorch FP16:  LLMLINGUA_FP16=1 (仅 cuda)
          3. ONNX+TRT FP16: LLMLINGUA_ONNX_PATH=path/to/model.onnx

        环境变量：
          LLMLINGUA_ENABLED=1         — 启用 LLMLingua-2（默认关闭）
          LLMLINGUA_MODEL_PATH=...    — 模型路径（默认 ./models/llmlingua-2-xlm-roberta-large-meetingbank）
          LLMLINGUA_DEVICE=cpu|mps|cuda — 推理设备（默认 cpu）
          LLMLINGUA_FP16=1            — 启用 PyTorch FP16（仅 cuda）
          LLMLINGUA_ONNX_PATH=...     — ONNX 模型路径（设置后启用 ONNX/TRT 模式，优先级高于 FP16）
          LLMLINGUA_TRT_CACHE=...     — TensorRT engine 缓存目录（默认 ./models/trt_cache/）
        """
        if self._llmlingua_compressor is not None:
            return self._llmlingua_compressor
        if self._llmlingua_available is False:
            return None

        with self._llmlingua_lock:
            if self._llmlingua_compressor is not None:
                return self._llmlingua_compressor
            if self._llmlingua_available is False:
                return None

            try:
                from llmlingua import PromptCompressor

                model_path = os.environ.get(
                    "LLMLINGUA_MODEL_PATH",
                    "./models/llmlingua-2-xlm-roberta-large-meetingbank",
                )
                device = os.environ.get("LLMLINGUA_DEVICE", "cpu")
                use_fp16 = os.environ.get("LLMLINGUA_FP16", "0") == "1"
                onnx_path = os.environ.get("LLMLINGUA_ONNX_PATH", "")

                self._llmlingua_compressor = PromptCompressor(
                    model_name=model_path,
                    use_llmlingua2=True,
                    device_map=device,
                )

                # 模式选择（优先级: ONNX > FP16 > FP32）
                if onnx_path:
                    # ONNX/TRT 模式：monkey-patch 替换内部模型
                    self._llmlingua_compressor.model = self._create_onnx_model(
                        onnx_path, device
                    )
                    logger.info(
                        "[CompressionEngine] LLMLingua-2 ONNX 模式 (provider=%s)",
                        self._llmlingua_compressor.model.provider_name,
                    )
                elif use_fp16 and device == "cuda":
                    # PyTorch FP16 模式
                    self._llmlingua_compressor.model.half()
                    logger.info("[CompressionEngine] LLMLingua-2 PyTorch FP16 模式")

                self._llmlingua_available = True
                logger.info(
                    "[CompressionEngine] LLMLingua-2 初始化成功 (model=%s, device=%s)",
                    model_path, device,
                )
                return self._llmlingua_compressor

            except ImportError:
                self._llmlingua_available = False
                logger.info(
                    "[CompressionEngine] llmlingua 未安装，LLMLingua-2 路径不可用"
                )
                return None
            except Exception as e:
                self._llmlingua_available = False
                logger.warning("[CompressionEngine] LLMLingua-2 初始化失败: %s", e)
                return None

    @staticmethod
    def _create_onnx_model(onnx_path: str, device: str):
        """创建 ONNX/TRT 推理引擎（兼容 HuggingFace model 接口）

        CUDA 设备: TensorrtExecutionProvider (FP16) > CUDAExecutionProvider > CPU
        CPU 设备: CPUExecutionProvider

        首次推理 TensorRT 会 JIT 编译 engine (~30-60s)，后续从缓存加载 (<1s)。
        """
        import numpy as np
        import onnxruntime as ort
        from dataclasses import dataclass

        trt_cache = os.environ.get("LLMLINGUA_TRT_CACHE", "./models/trt_cache/")

        # 根据设备选择 provider
        if device == "cuda":
            os.makedirs(trt_cache, exist_ok=True)
            providers = [
                ("TensorrtExecutionProvider", {
                    "trt_max_workspace_size": 2 << 30,
                    "trt_fp16_enable": True,
                    "trt_engine_cache_enable": True,
                    "trt_engine_cache_path": trt_cache,
                    "trt_builder_optimization_level": 3,
                }),
                "CUDAExecutionProvider",
                "CPUExecutionProvider",
            ]
        else:
            providers = ["CPUExecutionProvider"]

        sess_options = ort.SessionOptions()
        sess_options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL

        session = ort.InferenceSession(
            onnx_path, sess_options=sess_options, providers=providers
        )
        active_provider = session.get_providers()[0]

        @dataclass
        class _FakeOutput:
            logits: "torch.Tensor"
            loss: None = None

        class _ONNXModel:
            """ONNX 推理引擎 — 兼容 HuggingFace model(input_ids, attention_mask) 接口"""

            def __init__(self):
                self._session = session
                self.provider_name = active_provider

            def __call__(self, input_ids, attention_mask, **kwargs):
                import torch
                ids_np = input_ids.cpu().numpy().astype(np.int64)
                mask_np = attention_mask.cpu().numpy().astype(np.int64)
                logits_np = self._session.run(
                    ["logits"],
                    {"input_ids": ids_np, "attention_mask": mask_np},
                )[0]
                return _FakeOutput(
                    logits=torch.from_numpy(logits_np).to(input_ids.device)
                )

            def half(self):
                return self

            def to(self, *args, **kwargs):
                return self

            def eval(self):
                return self

            def parameters(self):
                return iter([])

            @property
            def training(self):
                return False

        return _ONNXModel()

    # ─── CRM 规则摘要（降级路径）────────────────────────────────

    def _crm_one_liner(self, content: str, tool_name: str) -> str | None:
        """CRM 工具规则摘要 — 按工具类型分发

        此逻辑整合自原 context_window._crm_tool_summary 和
        skill_compress._skill_internal_one_liner，统一到一处维护。
        """
        # 尝试 JSON 解析
        data = None
        stripped = content.strip()
        if stripped.startswith(("{", "[")):
            try:
                data = json.loads(stripped)
            except json.JSONDecodeError:
                pass

        # JSON 数组/对象 → 结构化提取
        if data is not None:
            extracted = self._extract_from_json(tool_name, data)
            if extracted:
                return extracted

        # 非 JSON → 按工具类型提取
        summarizer = _TOOL_ONE_LINERS.get(tool_name)
        if summarizer:
            result = summarizer(content, tool_name)
            if result:
                return result

        # 通用兜底：关键数字 + 前缀预览
        return self._generic_one_liner(content, tool_name)

    @staticmethod
    def _extract_from_json(tool_name: str, data: Any) -> str | None:
        """从 JSON 数据提取结构化摘要"""
        if isinstance(data, dict) and "records" in data:
            records = data["records"]
            if isinstance(records, list):
                count = len(records)
                names = [str(r.get("name", r.get("subject", r.get("id", ""))))
                         for r in records[:5]]
                names_str = ", ".join(n for n in names if n)
                extra = f"...等{count}条" if count > 5 else ""
                amounts = [r.get("amount", 0) for r in records if r.get("amount")]
                amount_str = (f", 总金额{sum(float(a) for a in amounts):,.0f}"
                              if amounts else "")
                return f"[{tool_name}] 返回{count}条: {names_str}{extra}{amount_str}"

        if isinstance(data, dict) and "fields" in data:
            fields = data["fields"]
            if isinstance(fields, list):
                entity = data.get("entity", data.get("name", ""))
                count = len(fields)
                field_names = [f.get("name", f.get("api_key", ""))
                               for f in fields[:6] if isinstance(f, dict)]
                return f"[{tool_name}] {entity} 字段({count}个): {', '.join(n for n in field_names if n)}"

        if isinstance(data, list):
            count = len(data)
            if count > 0 and isinstance(data[0], dict):
                names = [str(r.get("name", r.get("title", ""))) for r in data[:5]]
                return f"[{tool_name}] 返回{count}条: {', '.join(n for n in names if n)}"
            return f"[{tool_name}] 返回{count}项数据"

        if isinstance(data, dict):
            key_fields = ["name", "id", "amount", "stage", "status", "title", "type"]
            parts = [f"{k}={data[k]}" for k in key_fields if k in data and data[k]]
            if parts:
                return f"[{tool_name}] {', '.join(parts[:8])}"

        return None

    @staticmethod
    def _generic_one_liner(content: str, tool_name: str) -> str:
        """通用一行摘要：关键数字 + 前 80 字符预览"""
        key_parts = []
        amounts = re.findall(
            r'[\$¥￥]\s*[\d,.]+[KMB万亿]?|\d[\d,.]*\s*(?:万|亿|USD|CNY|元)',
            content[:2000],
        )
        if amounts:
            key_parts.append(f"金额:{','.join(list(dict.fromkeys(amounts[:3])))}") 
        pcts = re.findall(r'\d+\.?\d*\s*%', content[:2000])
        if pcts:
            key_parts.append(f"比例:{','.join(list(dict.fromkeys(pcts[:3])))}")

        preview = content[:80].replace("\n", " ").strip()
        key_str = f" [{'; '.join(key_parts)}]" if key_parts else ""
        return f"[{tool_name or 'tool'}] {preview}...{key_str} ({len(content)}字符)"

    # ─── 智能截断 ─────────────────────────────────────────────

    @staticmethod
    def _truncate_smart(content: str, max_chars: int, tool_name: str) -> str:
        """智能截断：保留 head + tail（对齐 sandbox ssh_backend 的策略）

        策略：前 60% + 后 40%，中间加截断标记。
        比纯前截断好：终端输出的错误通常在末尾。
        """
        if len(content) <= max_chars:
            return content

        head_ratio = 0.6
        head_chars = int(max_chars * head_ratio)
        tail_chars = max_chars - head_chars - 50  # 50 chars for marker

        head = content[:head_chars]
        tail = content[-tail_chars:] if tail_chars > 0 else ""
        omitted = len(content) - head_chars - tail_chars

        marker = f"\n\n[...已省略 {omitted} 字符...]\n\n"
        return f"{head}{marker}{tail}"

    # ─── 辅助方法 ─────────────────────────────────────────────

    @staticmethod
    def _is_error_output(content: str) -> bool:
        """检测内容是否是错误/异常输出（不应被压缩）"""
        if len(content) > 8000:
            return False  # 超大错误输出仍然需要压缩
        error_indicators = (
            "Traceback (most recent call last)",
            "Error:", "Exception:", "FATAL",
            "panic:", "FAILED", "error[E",
            "SyntaxError", "TypeError", "ValueError",
            "ConnectionError", "TimeoutError",
        )
        head = content[:500]
        return any(indicator in head for indicator in error_indicators)

    # ─── 统计 ─────────────────────────────────────────────────

    def get_stats(self) -> dict[str, Any]:
        """获取压缩统计"""
        total_saved = self._total_original_chars - self._total_compressed_chars
        avg_ratio = (
            self._total_compressed_chars / self._total_original_chars
            if self._total_original_chars > 0 else 1.0
        )
        return {
            "headroom_available": bool(self._headroom_available),
            "llmlingua_available": bool(self._llmlingua_available),
            "total_calls": self._total_calls,
            "total_compressed": self._total_compressed,
            "total_chars_saved": total_saved,
            "avg_ratio": round(avg_ratio, 3),
            "by_strategy": dict(self._by_strategy),
            "by_level": dict(self._by_level),
        }


# ═══════════════════════════════════════════════════════════
# 工具级一行摘要器（CRM 降级路径）
# ═══════════════════════════════════════════════════════════

def _summarize_web_search(content: str, tool_name: str) -> str | None:
    """web_search 摘要"""
    lines = content.split("\n")
    meaningful = [l.strip() for l in lines if l.strip() and 15 < len(l.strip()) <= 200][:3]
    if meaningful:
        return f"[web_search] ({len(content)}字符) " + " | ".join(meaningful)
    return f"[web_search] {content[:150].replace(chr(10), ' ')}..."


def _summarize_terminal(content: str, tool_name: str) -> str | None:
    """terminal/execute_code 日志摘要：保留错误行 + 统计"""
    lines = content.split("\n")
    error_lines = [l for l in lines if any(
        kw in l.lower() for kw in ("error", "fail", "fatal", "exception", "panic")
    )][:5]
    total = len(lines)
    if error_lines:
        errors_str = "\n".join(error_lines)
        return f"[{tool_name}] {total}行输出, {len(error_lines)}个错误:\n{errors_str}"
    # 无错误：取最后 3 行（通常是结果摘要）
    tail = "\n".join(lines[-3:]) if total > 3 else content[:200]
    return f"[{tool_name}] {total}行输出 (无错误):\n{tail}"


def _summarize_analyze(content: str, tool_name: str) -> str | None:
    """analyze_data 摘要：第一行结论 + 关键数字"""
    first_line = content.split("\n")[0][:150] if "\n" in content else content[:150]
    amounts = re.findall(r'[\$¥￥]\s*[\d,.]+[KMB万亿]?', content[:1000])
    pcts = re.findall(r'\d+\.?\d*\s*%', content[:1000])
    key_parts = []
    if amounts:
        key_parts.append(f"金额:{','.join(amounts[:3])}")
    if pcts:
        key_parts.append(f"比例:{','.join(pcts[:3])}")
    key_str = f" [{'; '.join(key_parts)}]" if key_parts else ""
    return f"[analyze_data] {first_line}{key_str}"


# 工具名 → 摘要器映射
_TOOL_ONE_LINERS: dict[str, Any] = {
    "web_search": _summarize_web_search,
    "terminal": _summarize_terminal,
    "execute_code": _summarize_terminal,
    "analyze_data": _summarize_analyze,
}


# ═══════════════════════════════════════════════════════════
# 便捷函数（供各模块直接调用，不需要拿 instance）
# ═══════════════════════════════════════════════════════════


def compress(
    content: str,
    tool_name: str = "",
    context: str = "",
    level: CompressLevel = CompressLevel.STANDARD,
    max_chars: int | None = None,
) -> CompressedResult:
    """模块级便捷压缩函数

    用法：
        from src.middleware.compression_engine import compress, CompressLevel
        result = compress(content, tool_name="query_data", level=CompressLevel.LIGHT)
    """
    return CompressionEngine.get_instance().compress(
        content, tool_name=tool_name, context=context,
        level=level, max_chars=max_chars,
    )


def compress_tool_output(
    content: str,
    tool_name: str = "",
    context: str = "",
) -> tuple[str, float]:
    """兼容旧 HeadroomCompressAdapter 接口（返回 (content, ratio)）

    用于已有的 context_window.py 调用点，无需改动调用方式。
    """
    result = compress(content, tool_name=tool_name, context=context,
                      level=CompressLevel.STANDARD)
    return result.content, result.ratio
