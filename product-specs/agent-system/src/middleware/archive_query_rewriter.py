"""存档检索 Query Rewriter — 将用户追问改写为适合 VDB 混合检索的关键词查询

与入口层 QueryRewriter 的区别:
  - 入口层: 面向主 Agent 推理，输出是自然语言句子
  - 本模块: 面向 VDB 检索，输出是关键词序列（实体+属性+数值）

核心能力:
  1. 代词消解 — "他们的报价" → "PT Sentosa 报价"（利用活跃实体上下文）
  2. 意图转关键词 — "怎么定下来的" → "变更 确认 更新"
  3. 实体补全 — 从当前摘要中提取活跃实体注入 query
  4. 数值关键词提取 — "$45K" "¥480万" "15%" 直接作为检索词
  5. 工具名推断 — "搜了什么" → "web_search"

设计原则:
  - 零 LLM 成本（纯规则 + 正则）
  - 毫秒级延迟（不阻塞主流程）
  - 不过拟合（规则基于通用语言模式，非特定数据）
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass
class RewriteResult:
    """改写结果"""
    original_query: str               # 原始查询
    rewritten_query: str              # 改写后的查询（用于 VDB 检索）
    extracted_entities: list[str]     # 提取的实体
    extracted_keywords: list[str]     # 提取的关键词
    intent_type: str = ""             # 识别的意图类型
    was_rewritten: bool = False       # 是否发生了改写


class ArchiveQueryRewriter:
    """存档检索专用 Query Rewriter

    使用:
        rewriter = ArchiveQueryRewriter(active_entities=["PT Sentosa", "华为科技"])
        result = rewriter.rewrite("他们的报价怎么变的")
        # result.rewritten_query = "PT Sentosa 报价 变更 金额"
    """

    def __init__(
        self,
        active_entities: list[str] | None = None,
        current_summary: str = "",
    ):
        """
        Args:
            active_entities: 当前会话的活跃实体（从迭代摘要中提取）
            current_summary: 当前迭代摘要文本（用于代词消解上下文）
        """
        self._active_entities = active_entities or []
        self._current_summary = current_summary

    def rewrite(self, query: str) -> RewriteResult:
        """改写查询

        流程:
          1. 提取原始 query 中的实体和关键词
          2. 代词消解（替换为活跃实体）
          3. 意图识别 + 关键词扩展
          4. 数值关键词提取
          5. 工具名推断
          6. 组合为最终检索 query（已有实体时不重复追加）
        """
        if not query or not query.strip():
            return RewriteResult(query, query, [], [], was_rewritten=False)

        original = query.strip()

        # Step 1: 提取原始实体和关键词
        entities = self._extract_entities(original)
        keywords = self._extract_base_keywords(original)

        # Step 2: 代词消解
        resolved_query, pronoun_resolved = self._resolve_pronouns(original)

        # Step 3: 意图识别 + 关键词扩展
        intent_type, intent_keywords = self._identify_intent(original)
        keywords.extend(intent_keywords)

        # Step 4: 数值关键词
        numeric_keywords = self._extract_numeric_keywords(original)
        keywords.extend(numeric_keywords)

        # Step 5: 工具名推断
        tool_keywords = self._infer_tool_names(original)
        keywords.extend(tool_keywords)

        # Step 6: 实体补全 — 仅在 query 无任何实体且代词被消解时补充
        if not entities and self._active_entities and pronoun_resolved:
            entities = self._active_entities[:2]
        elif not entities and not pronoun_resolved and self._active_entities:
            # query 既无实体也无代词（如 "报价多少钱"）→ 从上下文补充
            # 但如果 query 已有足够信息则不补:
            #   - 数值关键词（自带检索线索）
            #   - 工具名推断（足够明确）
            #   - 较长文本（>=8字，有独立语义）
            #   - 包含英文词 >=4 字符（可能是专有名词如 Amazon/Kubernetes）
            import re as _re
            has_english_noun = bool(_re.search(r'[A-Z][a-z]{3,}', original))
            has_sufficient_info = (
                len(numeric_keywords) > 0
                or len(tool_keywords) > 0
                or len(original) > 8
                or has_english_noun
            )
            if not has_sufficient_info:
                entities = self._active_entities[:1]

        # Step 7: 组合最终 query
        # 如果原始 query 已包含实体，不重复追加
        query_already_has_entity = bool(self._extract_entities(original))

        if query_already_has_entity:
            # 已自包含 → 不追加实体，只补意图关键词（且不加太多）
            rewritten = resolved_query
            was_rewritten = resolved_query != original
        else:
            # 无实体 → 追加实体前缀
            parts = []
            if entities:
                parts.extend(entities)
            parts.append(resolved_query)
            rewritten = " ".join(parts)
            was_rewritten = True

        return RewriteResult(
            original_query=original,
            rewritten_query=rewritten,
            extracted_entities=entities,
            extracted_keywords=list(dict.fromkeys(keywords))[:20],
            intent_type=intent_type,
            was_rewritten=was_rewritten,
        )

    # ═══════════════════════════════════════════════════════════
    # 代词消解
    # ═══════════════════════════════════════════════════════════

    def _resolve_pronouns(self, query: str) -> tuple[str, bool]:
        """将代词替换为活跃实体

        支持: 他们/他/她/它/那个/这个/那家/这家/该客户/对方
        """
        if not self._active_entities:
            return query, False

        pronouns = {
            r'他们的?': self._active_entities[0],
            r'她们的?': self._active_entities[0],
            r'它的?': self._active_entities[0],
            r'那个客户': self._active_entities[0],
            r'这个客户': self._active_entities[0],
            r'那家公司': self._active_entities[0],
            r'这家公司': self._active_entities[0],
            r'该客户': self._active_entities[0],
            r'对方': self._active_entities[0],
            r'那边': self._active_entities[0],
        }

        resolved = query
        was_resolved = False
        for pattern, replacement in pronouns.items():
            new_text = re.sub(pattern, replacement, resolved)
            if new_text != resolved:
                resolved = new_text
                was_resolved = True

        return resolved, was_resolved

    # ═══════════════════════════════════════════════════════════
    # 意图识别
    # ═══════════════════════════════════════════════════════════

    def _identify_intent(self, query: str) -> tuple[str, list[str]]:
        """识别查询意图并生成扩展关键词

        Returns:
            (intent_type, keywords) — 意图类型 + 应追加的检索关键词

        注意: 模式按优先级排列，先匹配的先生效。
        "为什么" 优先匹配 decision_reason（而非 change_tracking）。
        """
        # 决策原因意图（优先级最高 — "为什么" 类问题）
        reason_patterns = [
            r'为什么|原因|理由|依据|怎么定的|怎么决定',
            r'怎么定.*的',  # "怎么定下来的" 匹配
            r'谁决定|谁同意|谁确认|谁批准',
            r'谁赢了|谁输了',
        ]
        for p in reason_patterns:
            if re.search(p, query):
                return "decision_reason", ["决策", "确认", "同意", "原因"]

        # 否定回忆意图（"之前否了什么""被砍了的"）
        negation_patterns = [
            r'否了|拒绝了|不要了|砍了什么|砍了哪',
            r'被砍|被否|被拒|没通过',
            r'取消了什么|去掉了什么',
        ]
        for p in negation_patterns:
            if re.search(p, query):
                return "change_tracking", ["砍掉", "取消", "去掉", "不要", "变更"]

        # 时间线意图（优先于变更 — "全过程"不是"变更"）
        timeline_patterns = [
            r'全过程|全部历[程史]|从头|时间线|历程',
            r'从.*开始|从.*到现在',
            r'第一次|最早|一开始|后来|最后怎',
            r'总共.*几次|一共.*几次|跟进了几次',
            r'前后.*什么|前后.*发生',
            r'总共.*几轮|一共.*几轮|互动了几轮|用了几轮',
            r'持续了多[久长]|谈了多[久长]',
            r'从.*到.*用了',
        ]
        for p in timeline_patterns:
            if re.search(p, query):
                return "timeline", ["时间线", "过程"]

        # 变更追踪意图
        change_patterns = [
            r'怎么变的|怎么改的|变化|变更|调整了|改了|改到|降到|升到',
            r'缩短|缩减|延长|增加了|减少了|砍了|加了',
            r'之前是多少|原来是|最初是|一开始是',
            r'历史.*变|演变',
            r'调整历史',  # "报价调整历史" 匹配
            r'从[\$¥￥\d].*(?:改|调|降|变)',
        ]
        for p in change_patterns:
            if re.search(p, query):
                return "change_tracking", ["变更", "调整", "更新", "确认"]

        # 最新状态意图
        latest_patterns = [
            r'最新|当前|现在|目前|最终|最后',
            r'最近一次|上次|上一次|刚才',
            r'定了没|确认了吗|签了吗|成了吗',
        ]
        for p in latest_patterns:
            if re.search(p, query):
                return "latest_state", ["最终", "确认", "当前"]

        # 对比意图
        compare_patterns = [
            r'对比|比较|vs|和.*比|跟.*比|差多少',
            r'哪个.*贵|哪个.*便宜|哪个.*好',
            r'哪个先|哪个后|先后顺序',
        ]
        for p in compare_patterns:
            if re.search(p, query):
                return "comparison", ["对比", "竞品"]

        # 具体数据意图
        data_patterns = [
            r'多少钱|金额|价格|费用|报价|成本',
            r'什么时候|日期|到期|截止|deadline',
            r'百分之|折扣|比例|占比',
            r'怎么分|怎么算|如何分配|怎么付|付款.*条件',
            r'一共.*多少|总共.*多少|花了多少',
        ]
        for p in data_patterns:
            if re.search(p, query):
                return "specific_data", []

        return "general", []

    # ═══════════════════════════════════════════════════════════
    # 关键词提取
    # ═══════════════════════════════════════════════════════════

    def _extract_base_keywords(self, text: str) -> list[str]:
        """提取基础关键词"""
        keywords = []
        # 中文 2-4 字词
        cn = re.findall(r'[\u4e00-\u9fa5]{2,4}', text)
        # 过滤停用词
        cn_stop = {"什么", "怎么", "为什么", "是不是", "有没有", "多少",
                   "可以", "能不能", "帮我", "给我", "看看", "一下",
                   "他们", "她们", "那个", "这个", "哪个", "还有",
                   "的", "了", "吗", "呢", "吧", "啊", "嘛"}
        keywords.extend(w for w in cn if w not in cn_stop)
        # 英文 3+ 字符
        en = [w.lower() for w in re.findall(r'[a-zA-Z][a-zA-Z0-9_\-]{2,}', text)]
        en_stop = {"the", "and", "for", "that", "this", "with", "from",
                   "are", "was", "were", "how", "what", "why", "when"}
        keywords.extend(w for w in en if w not in en_stop)
        return keywords

    def _extract_numeric_keywords(self, text: str) -> list[str]:
        """提取数值关键词（金额/日期/百分比）"""
        keywords = []
        # 金额
        keywords += re.findall(r'[\$¥￥]\s*[\d,.]+[KMB万亿]?', text)
        keywords += re.findall(r'\d[\d,.]*\s*(?:万|亿|USD|CNY|元)', text)
        # 百分比
        keywords += re.findall(r'\d+\.?\d*\s*%', text)
        # 日期
        keywords += re.findall(r'\d{4}[-/]\d{1,2}[-/]\d{1,2}', text)
        return keywords

    def _extract_entities(self, text: str) -> list[str]:
        """提取实体"""
        entities = []
        entities += re.findall(r'(?:PT|CV|Ltd|Inc)\s+[\w\s]{2,20}', text)
        entities += re.findall(r'[\u4e00-\u9fa5]{2,10}(?:科技|集团|公司|有限|技术|云)', text)
        entities += re.findall(r'(?:opp|acc|con|case|quote|act|Q|CON|POC)[-_][\w\-]+', text)
        entities += re.findall(r'(?:Pak|Ibu|Mr|Ms|Dr|Prof)\s+\w+', text)
        # CRM 业务实体名
        entities += re.findall(r'(?:Odoo|SAP|Salesforce|Oracle|Microsoft)', text, re.IGNORECASE)
        return list(dict.fromkeys(e.strip() for e in entities if len(e.strip()) > 1))

    # ═══════════════════════════════════════════════════════════
    # 工具名推断
    # ═══════════════════════════════════════════════════════════

    # 工具名 → 中文描述映射（用于检索时扩展 + 写入时索引增强）
    TOOL_DESCRIPTIONS = {
        "web_search": "网络搜索 搜索 网上查 竞品调研 定价查询",
        "query_data": "数据查询 查询 查了 查到 获取数据 读取",
        "analyze_data": "数据分析 分析 统计 汇总 生成报告 BANT pipeline",
        "execute_task": "执行操作 更新 修改 创建 删除 签约 成交 确认",
    }

    def _infer_tool_names(self, query: str) -> list[str]:
        """从查询意图推断可能涉及的工具名 + 中文描述

        支持区分同工具多次调用:
          - "第一次查的" / "最近查的" → 附加时序关键词
          - "搜Odoo那次" → 附加实体上下文帮助精确命中
        """
        tool_map = {
            r'搜索|搜了|网上|竞品.*价|定价|调研': ["web_search"],
            r'查询|查了|查过|数据|查到|获取': ["query_data"],
            r'分析|统计|汇总|pipeline|BANT|报告': ["analyze_data"],
            r'更新|修改|创建|执行|签约|成交|确认': ["execute_task"],
        }
        tools = []
        for pattern, names in tool_map.items():
            if re.search(pattern, query):
                tools.extend(names)
                # 同时追加中文描述关键词（提升 BM25 命中率）
                for name in names:
                    desc = self.TOOL_DESCRIPTIONS.get(name, "")
                    if desc:
                        # 取描述中的前 2 个关键词
                        desc_words = desc.split()[:2]
                        tools.extend(desc_words)

        # 时序修饰词检测（帮助区分同工具多次调用）
        if tools:
            if re.search(r'第一次|最早|最初', query):
                tools.append("__time_first__")
            elif re.search(r'最近|最后|上次|刚才', query):
                tools.append("__time_latest__")
            elif re.search(r'几次|多少次|所有', query):
                tools.append("__time_all__")

        return list(dict.fromkeys(tools))  # 去重
