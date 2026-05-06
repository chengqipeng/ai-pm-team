"""输入转换中间件 — 可插拔的消息预处理管道

## 定位

InputTransformMiddleware 是一个通用的消息预处理框架，通过注册多个 InputTransformer
实现可插拔的输入转换管道。它在 before_agent 阶段（Agent 开始处理前）对消息列表做
一次性的预处理转换。

## 在中间件管道中的位置

```
before_agent 执行顺序：
  TracingMiddleware          → 记录链路
  AgentLoggingMiddleware     → 打印日志
  DanglingToolCallMiddleware → 修复悬空 tool_call
  FileProcessMiddleware      → 解析上传文件 → 写入 thread_data["parsed_files"]
  InputTransformMiddleware   → ★ 对消息列表做预处理转换（本中间件）
  MemoryMiddleware           → 记忆检索注入
```

## 当前已注册的 Transformer

### 1. PIIRedactTransformer（PII 脱敏转换器）
对齐 agent-platform 的 DataFogAnalyzer + SensitiveDataReplacer。
在消息送入 LLM 前，对用户输入中的敏感信息做脱敏处理：
- 身份证号（18/15 位，含格式校验）→ <PII:CN_ID_CARD_N>
- 银行卡号（16-19 位，Luhn 校验）→ <PII:CN_BANK_CARD_N>
- 手机号（1[3-9] 开头 11 位）→ <PII:CN_PHONE_N>
- 邮箱地址 → <PII:CN_EMAIL_N>

脱敏映射表保存在 metadata["pii_placeholders"] 中，供后续还原使用。
还原时兼容 LLM 幻觉导致的占位符变形（去掉 <>、加空格、改大小写）。
可通过 metadata["redact_pii"] = False 关闭脱敏。

### 2. MultimodalTransformer（多模态输入转换器）
在 before_agent 阶段对上传文件做一次性预处理：
- 图片文件：将 base64 data URL 或普通 URL 转换为 OpenAI 兼容的多模态 content 格式
- 文档文件：将已提取的文本内容注入到最后一条 HumanMessage 中
- 跳过已经是多模态格式的消息（避免重复处理）

注意：MultimodalInjectMiddleware（before_model 阶段）负责每轮迭代的动态注入，
本 Transformer 负责首次进入时的一次性格式转换。两者互补。

## metadata 参数

transform() 的第二个参数 metadata 来自 configurable["input_metadata"]，
调用方可以通过它传递额外的转换控制信息：
- {"redact_pii": False} — 关闭 PII 脱敏（默认开启）
- {"pii_placeholders": {}} — PII 脱敏映射表（由 PIIRedactTransformer 写入，格式 {"<PII:CN_PHONE_1>": "13800138000"}）
"""

import logging
import re
from abc import ABC, abstractmethod
from typing import Any

from langchain_core.messages import HumanMessage
from langchain.agents.middleware.types import AgentMiddleware, AgentState
from langgraph.config import get_config
from langgraph.runtime import Runtime

logger = logging.getLogger(__name__)


class InputTransformer(ABC):
    """输入转换器抽象基类

    每个转换器接收消息列表和元数据，返回转换后的消息列表。
    转换器按注册顺序链式执行，前一个的输出是后一个的输入。
    """

    @abstractmethod
    def transform(self, messages: list, metadata: dict[str, Any]) -> list:
        """转换消息列表

        Args:
            messages: LangChain 消息列表（HumanMessage, AIMessage, ToolMessage 等）
            metadata: 来自 configurable["input_metadata"] 的额外控制信息

        Returns:
            转换后的消息列表（可以原地修改也可以返回新列表）
        """
        ...


# ═══════════════════════════════════════════════════════════
# 输入内容审查转换器
# ═══════════════════════════════════════════════════════════

class ContentReviewTransformer(InputTransformer):
    """输入内容审查转换器 — 在消息送入 Agent 前拦截敏感词

    排在 PIIRedactTransformer 之前：先拦截违规内容，再对合规内容做 PII 脱敏。

    拦截方式：替换最后一条 HumanMessage.content 为拦截提示。
    Agent 看到的是 "[系统提示] 您的输入包含不当内容"，会自然回复拒绝。

    可通过 metadata["content_review"] = False 关闭。
    """

    def __init__(self, review_service: Any = None) -> None:
        self._service = review_service

    def transform(self, messages: list, metadata: dict[str, Any]) -> list:
        if self._service is None or not self._service.enabled:
            return messages
        if metadata.get("content_review") is False:
            return messages

        for i in range(len(messages) - 1, -1, -1):
            if isinstance(messages[i], HumanMessage) and isinstance(messages[i].content, str):
                result = self._service.review_input(messages[i].content)
                if not result.passed:
                    messages[i].content = f"[系统提示] {result.blocked_reason}"
                    logger.warning("输入审查拦截: keywords=%s", result.blocked_keywords)
                break

        return messages


# ═══════════════════════════════════════════════════════════
# PII 脱敏转换器
# 对齐 neo-ai-agent-platform-service 的 DataFogAnalyzer + SensitiveDataReplacer
# ═══════════════════════════════════════════════════════════


class PIIRedactTransformer(InputTransformer):
    """PII 脱敏转换器 — 对齐 agent-platform 的 PII 处理链路

    对齐来源：
    - service/pii/datafog_analyzer.py — 正则分析器（单例，4 种 PII 类型）
    - service/pii/sensitive_data_replacer.py — 占位符替换/还原

    支持的 PII 类型（按匹配优先级排列）：
    1. CN_ID_CARD:   身份证号（18/15 位，含格式校验）→ <PII:CN_ID_CARD_N>
    2. CN_BANK_CARD: 银行卡号（16-19 位，Luhn 校验）→ <PII:CN_BANK_CARD_N>
    3. CN_PHONE:     手机号（1[3-9] 开头 11 位）→ <PII:CN_PHONE_N>
    4. CN_EMAIL:     邮箱地址 → <PII:CN_EMAIL_N>

    占位符格式：<PII:CN_PHONE_1>（对齐老项目，避免 [[...]] 被 LLM 误解为 JSON）

    脱敏策略：
    - 只处理 HumanMessage（用户输入），不处理 AIMessage/ToolMessage
    - 只处理字符串类型的 content（跳过已转为多模态 list 格式的消息）
    - matched_positions 防止同一文本位置被多个模式重复匹配
    - 身份证额外校验：18 位格式（省份+年月日+顺序码+校验位）
    - 银行卡额外校验：Luhn 算法
    - 脱敏映射表写入 metadata["pii_placeholders"]
    - 可通过 metadata["redact_pii"] = False 关闭

    还原策略（restore_pii 静态方法）：
    - 兼容 LLM 幻觉导致的占位符变形（去掉 <>、加空格、改大小写）
    - 按 key 长度降序匹配，避免短 key 前缀匹配长 key
    - 正则：<?(?:PII:)?(KEY1|KEY2)\\s*>?（大小写不敏感）

    示例：
        输入: "客户手机 13800138000，身份证 110101199003071234，邮箱 test@crm.com"
        输出: "客户手机 <PII:CN_PHONE_1>，身份证 <PII:CN_ID_CARD_1>，邮箱 <PII:CN_EMAIL_1>"
        placeholders: {
            "<PII:CN_PHONE_1>": "13800138000",
            "<PII:CN_ID_CARD_1>": "110101199003071234",
            "<PII:CN_EMAIL_1>": "test@crm.com",
        }

    还原示例（兼容 LLM 幻觉）：
        LLM 输出: "该客户手机为 PII:CN_PHONE_1，请确认"
        还原后:   "该客户手机为 13800138000，请确认"
    """

    PLACEHOLDER_PREFIX = "<PII:"
    PLACEHOLDER_SUFFIX = ">"

    # PII 正则模式 — 按优先级排列（对齐 DataFogAnalyzer）
    # 顺序重要：CN_ID_CARD 必须在 CN_BANK_CARD 之前（18 位身份证会被 16-19 位银行卡误匹配）
    _PATTERNS: list[tuple[str, re.Pattern]] = [
        ("CN_ID_CARD", re.compile(r'(?<!\d)[1-9][\d\s-]{16,20}[0-9Xx](?!\d)')),
        ("CN_BANK_CARD", re.compile(r'(?<!\d)[1-9]\d{15,18}(?!\d)')),
        ("CN_PHONE", re.compile(r'(?<!\d)1[3-9]\d{9}(?!\d)')),
        ("CN_EMAIL", re.compile(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}')),
    ]

    # ── 校验方法（对齐 DataFogAnalyzer） ──

    @staticmethod
    def _validate_id_card(text: str) -> bool:
        """验证身份证号是否合法 — 对齐 DataFogAnalyzer._validate_id_card"""
        digits = re.sub(r'[\s-]', '', text)
        if len(digits) not in (15, 18):
            return False
        if not re.match(r'^[1-9]\d+[0-9Xx]?$', digits):
            return False
        if len(digits) == 18:
            return bool(re.match(
                r'[1-9]\d{5}(?:18|19|20)\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])\d{3}[0-9Xx]$',
                digits,
            ))
        return bool(re.match(
            r'[1-9]\d{5}\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])\d{3}$',
            digits,
        ))

    @staticmethod
    def _validate_bank_card(number: str) -> bool:
        """Luhn 算法校验银行卡号 — 对齐 DataFogAnalyzer._validate_bank_card"""
        try:
            digits = [int(d) for d in number]
        except ValueError:
            return False
        checksum = 0
        for i, d in enumerate(reversed(digits)):
            if i % 2 == 1:
                d *= 2
                if d > 9:
                    d -= 9
            checksum += d
        return checksum % 10 == 0

    # ── 核心转换逻辑 ──

    def transform(self, messages: list, metadata: dict[str, Any]) -> list:
        if metadata.get("redact_pii") is False:
            return messages

        placeholders: dict[str, str] = metadata.get("pii_placeholders", {})
        counters: dict[str, int] = {}
        changed = False

        for msg in messages:
            if not isinstance(msg, HumanMessage):
                continue
            if not isinstance(msg.content, str):
                continue

            new_content, msg_changed = self._redact_text(msg.content, placeholders, counters)
            if msg_changed:
                msg.content = new_content
                changed = True

        if changed:
            metadata["pii_placeholders"] = placeholders
            logger.info("PII 脱敏完成: %s, 共 %d 处",
                        list(counters.keys()), sum(counters.values()))

        return messages

    def _redact_text(
        self, text: str,
        placeholders: dict[str, str],
        counters: dict[str, int],
    ) -> tuple[str, bool]:
        """对单段文本做 PII 脱敏 — 对齐 DataFogAnalyzer.analyze + SensitiveDataReplacer"""
        # 第一步：分析（对齐 DataFogAnalyzer.analyze）
        matched_positions: set[int] = set()
        findings: list[tuple[str, str, int, int]] = []  # (type, value, start, end)

        for pii_type, pattern in self._PATTERNS:
            for match in pattern.finditer(text):
                # 位置去重：同一位置不被多个模式重复匹配
                if any(pos in matched_positions for pos in range(match.start(), match.end())):
                    continue

                value = match.group()

                # 身份证额外校验
                if pii_type == "CN_ID_CARD":
                    if not self._validate_id_card(value):
                        continue
                    value = re.sub(r'[\s-]', '', value)

                # 银行卡额外校验
                if pii_type == "CN_BANK_CARD":
                    if not self._validate_bank_card(value):
                        continue

                findings.append((pii_type, value, match.start(), match.end()))
                matched_positions.update(range(match.start(), match.end()))

        if not findings:
            return text, False

        # 第二步：替换（对齐 SensitiveDataReplacer.replace_sensitive_data）
        # 从后往前替换，避免位置偏移
        findings.sort(key=lambda x: x[2], reverse=True)
        result = text
        for pii_type, value, start, end in findings:
            # 检查是否已有相同值的占位符（避免重复）
            existing = None
            for ph, val in placeholders.items():
                if val == value:
                    existing = ph
                    break

            if existing:
                placeholder = existing
            else:
                counters[pii_type] = counters.get(pii_type, 0) + 1
                placeholder = f"{self.PLACEHOLDER_PREFIX}{pii_type}_{counters[pii_type]}{self.PLACEHOLDER_SUFFIX}"
                placeholders[placeholder] = value

            result = result[:start] + placeholder + result[end:]

        return result, True

    # ── 还原方法（对齐 SensitiveDataReplacer.restore_sensitive_data） ──

    @staticmethod
    def restore_pii(text: str, placeholders: dict[str, str]) -> str:
        """将占位符还原为原始值 — 兼容 LLM 幻觉导致的格式变形

        对齐 SensitiveDataReplacer.restore_sensitive_data：
        - 兼容变体：<PII:CN_PHONE_1>、PII:CN_PHONE_1、CN_PHONE_1、cn_phone_1
        - 按 key 长度降序匹配，避免短 key 前缀匹配长 key
        - 大小写不敏感

        Args:
            text: 含占位符的文本（LLM 输出）
            placeholders: {占位符: 原始值} 映射

        Returns:
            还原后的文本
        """
        if not placeholders or not text:
            return text

        # 提取核心 key（去掉 <PII: 和 >）
        key_map: dict[str, str] = {}
        for placeholder, original in placeholders.items():
            core = placeholder.replace("<PII:", "").replace(">", "")
            key_map[core.upper()] = original

        # 按 key 长度降序排列，避免 CN_BANK_CARD_1 被 CN_BANK_CARD_15 的前缀匹配
        sorted_keys = sorted(key_map.keys(), key=len, reverse=True)
        keys_pattern = '|'.join(re.escape(k) for k in sorted_keys)

        # 前缀 < 和 PII: 分别可选，兼容各种变体
        pattern = re.compile(
            r'<?(?:PII:)?(' + keys_pattern + r')\s*>?',
            re.IGNORECASE,
        )

        return pattern.sub(
            lambda m: key_map.get(m.group(1).upper(), m.group(0)),
            text,
        )


# ═══════════════════════════════════════════════════════════
# 多模态输入转换器
# ═══════════════════════════════════════════════════════════

class MultimodalTransformer(InputTransformer):
    """多模态输入转换器 — 在 before_agent 阶段对上传文件做一次性预处理

    处理逻辑：
    1. 从 metadata["parsed_files"] 或 state thread_data 中读取已解析的文件列表
    2. 图片文件：将 URL/base64 转为 OpenAI 兼容的多模态 content 格式
    3. 文档文件：将已提取的文本内容作为上下文注入到 HumanMessage
    4. 跳过已经是多模态格式的消息（content 为 list 类型）

    与 MultimodalInjectMiddleware 的分工：
    - 本 Transformer（before_agent）：首次进入时的一次性格式转换
    - MultimodalInjectMiddleware（before_model）：每轮 LLM 调用前的动态注入

    示例 — 图片上传：
        parsed_files: [{"fileType": "image", "url": "data:image/png;base64,...", "fileName": "screenshot.png"}]

        转换前 HumanMessage.content:
            "这张图片里的客户信息帮我录入系统"

        转换后 HumanMessage.content:
            [
                {"type": "text", "text": "这张图片里的客户信息帮我录入系统"},
                {"type": "image_url", "image_url": {"url": "data:image/png;base64,..."}},
            ]

    示例 — 文档上传：
        parsed_files: [{"fileType": "document", "fileName": "客户清单.csv", "content": "公司名,联系人\\n华为,张三"}]

        转换前 HumanMessage.content:
            "帮我导入这个客户清单"

        转换后 HumanMessage.content:
            "帮我导入这个客户清单\\n\\n---\\n📎 附件 [客户清单.csv]:\\n公司名,联系人\\n华为,张三\\n---"
    """

    # 文档内容注入的最大字符数（避免超长文档撑爆上下文）
    MAX_DOC_CHARS: int = 5000

    def transform(self, messages: list, metadata: dict[str, Any]) -> list:
        parsed_files: list[dict] = metadata.get("parsed_files", [])
        if not parsed_files:
            return messages

        # 找最后一条 HumanMessage
        last_human_idx: int | None = None
        for i in range(len(messages) - 1, -1, -1):
            if isinstance(messages[i], HumanMessage):
                last_human_idx = i
                break

        if last_human_idx is None:
            return messages

        last_human = messages[last_human_idx]

        # 已经是多模态格式 → 跳过（避免重复处理）
        if isinstance(last_human.content, list):
            return messages

        original_text = last_human.content if isinstance(last_human.content, str) else str(last_human.content)

        # 分类文件
        images: list[dict] = []
        documents: list[dict] = []
        for f in parsed_files:
            ft = f.get("fileType", "")
            if ft == "image" and f.get("url"):
                images.append(f)
            elif ft == "document":
                documents.append(f)

        # 无可处理的文件 → 跳过
        if not images and not documents:
            return messages

        # 有图片 → 转为多模态 content 格式（OpenAI 兼容）
        if images:
            multimodal_content: list[dict[str, Any]] = []

            # 文档内容先拼接到文本中
            text_with_docs = original_text
            if documents:
                text_with_docs = self._inject_documents(original_text, documents)

            multimodal_content.append({"type": "text", "text": text_with_docs})

            for img in images:
                multimodal_content.append({
                    "type": "image_url",
                    "image_url": {"url": img["url"]},
                })

            new_messages = list(messages)
            new_messages[last_human_idx] = HumanMessage(
                content=multimodal_content,
                id=last_human.id,
            )
            logger.info("多模态转换: %d 张图片, %d 个文档", len(images), len(documents))
            return new_messages

        # 只有文档（无图片）→ 文本注入
        new_content = self._inject_documents(original_text, documents)
        if new_content != original_text:
            new_messages = list(messages)
            new_messages[last_human_idx] = HumanMessage(
                content=new_content,
                id=last_human.id,
            )
            logger.info("文档注入: %d 个文档", len(documents))
            return new_messages

        return messages

    def _inject_documents(self, text: str, documents: list[dict]) -> str:
        """将文档内容以附件格式注入到文本末尾"""
        parts = [text]
        for doc in documents:
            name = doc.get("fileName", "document")
            content = doc.get("content", "")
            if not content:
                parts.append(f"\n\n---\n📎 附件 [{name}]（内容未提取）\n---")
                continue
            # 截断超长文档
            if len(content) > self.MAX_DOC_CHARS:
                content = content[:self.MAX_DOC_CHARS] + f"\n... (截断，原文共 {len(doc.get('content', ''))} 字符)"
            parts.append(f"\n\n---\n📎 附件 [{name}]:\n{content}\n---")
        return "".join(parts)


# ═══════════════════════════════════════════════════════════
# 中间件主体
# ═══════════════════════════════════════════════════════════

class InputTransformMiddleware(AgentMiddleware):
    """输入转换中间件 — 可插拔的消息预处理管道

    在 before_agent 阶段按注册顺序依次执行所有 InputTransformer，
    对消息列表做一次性的预处理转换。任何单个 Transformer 失败不会
    阻断整个管道，会跳过并记录错误日志。

    默认执行顺序（由 build_middleware 注册）：
    1. PIIRedactTransformer  — 先脱敏，确保后续 Transformer 处理的是脱敏后的文本
    2. MultimodalTransformer — 再做多模态格式转换
    """

    def __init__(self, transformers: list[InputTransformer] | None = None):
        super().__init__()
        self._transformers: list[InputTransformer] = transformers or []

    def register(self, transformer: InputTransformer) -> None:
        """注册一个输入转换器，追加到管道末尾"""
        self._transformers.append(transformer)

    def before_agent(self, state: AgentState, runtime: Runtime) -> dict[str, Any] | None:
        if not self._transformers:
            return None

        messages = state.get("messages", [])
        configurable = get_config().get("configurable", {})
        metadata = configurable.get("input_metadata", {})

        # 将 thread_data 中的 parsed_files 也放入 metadata，供 MultimodalTransformer 消费
        thread_data = state.get("thread_data", {}) or {}
        if "parsed_files" not in metadata and thread_data.get("parsed_files"):
            metadata["parsed_files"] = thread_data["parsed_files"]

        transformed = messages
        for t in self._transformers:
            try:
                transformed = t.transform(transformed, metadata)
            except Exception as e:
                logger.error("InputTransformer %s failed: %s", type(t).__name__, e)

        # 只有消息列表确实被修改时才返回 patch
        return {"messages": transformed} if transformed is not messages else None
