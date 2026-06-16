"""上下文存档检索服务 — 纯 VDB 架构，检索语义独立于记忆系统

核心差异（vs 记忆系统 MemoryMiddleware）:
  - 记忆系统: 按相关性排序，返回"提炼后的认知"，回答"是什么"
  - 存档检索: 按时间线排序，返回"原始对话过程"，回答"怎么变成这样的"

设计要点:
  1. 时间线排序 — 同一关键词命中多条，按 timestamp 升序排列
  2. 变更检测  — 同实体/属性在多轮次间的值变化自动标注
  3. 分级返回  — Level 1 时间线摘要 → Level 2 展开某轮原文
  4. 倾向链构建 — 追踪用户对同一事项的态度/决策演变
  5. 数据时效性 — 标注数据采集时间，提示可能过时的信息

架构:
  - 存储: 纯 VDB（原文 + 语义索引一体化，无 PG 依赖）
  - 检索: VDB hybrid_search (dense 0.3 + BM25 0.7)
  - VDB 不可用时不降级，直接返回空

与 ContextArchive 的分工:
  - ContextArchive: 负责写入 + 底层 VDB 检索
  - ContextArchiveService: 负责高层读取（时间线 + 变更检测 + 分级返回）
"""
from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════
# 数据模型
# ═══════════════════════════════════════════════════════════

@dataclass
class ChangePoint:
    """变更点 — 同实体/属性在不同轮次间的值变化"""
    turn_id: int
    timestamp: float
    field: str                    # 变更的字段/属性名
    old_value: str                # 变更前的值
    new_value: str                # 变更后的值
    reason: str = ""              # 变更原因（从对话中提取）
    actor: str = ""               # 谁触发的变更（user/agent/tool）


@dataclass
class TimelineEntry:
    """时间线条目 — 单轮对话的摘要视图"""
    turn_id: int
    timestamp: float
    data_timestamp: float         # 数据采集时间
    user_query: str               # 用户问题
    answer_preview: str           # Agent 回复预览
    tools_used: list[str]         # 使用的工具
    entities: list[str]           # 涉及的实体
    has_change: bool = False      # 是否有变更
    change_summary: str = ""      # 变更摘要（如 "报价: $45K → $40K"）
    data_age_label: str = ""      # 数据时效性标注


@dataclass
class EvolutionChain:
    """倾向/决策演变链"""
    subject: str                  # 演变主体（如 "PT Sentosa 报价"）
    chain: list[ChangePoint]      # 变更链（按时间升序）
    current_state: str = ""       # 当前有效值
    decision_rationale: str = ""  # 最终决策的依据


@dataclass
class ArchiveRecallResult:
    """recall_context 的结构化返回"""
    # Level 1: 时间线视图
    timeline: list[TimelineEntry] = field(default_factory=list)
    # 变更检测结果
    changes: list[ChangePoint] = field(default_factory=list)
    # 倾向链
    evolution: EvolutionChain | None = None
    # 当前有效状态摘要
    current_state_summary: str = ""
    # 格式化输出（供 LLM 消费）
    formatted_output: str = ""
    # Level 2: 某轮的完整原文（仅在 mode="full" 时填充）
    full_content: list[dict] = field(default_factory=list)

    def to_llm_context(self) -> str:
        """生成供 LLM 上下文注入的格式化文本"""
        if self.formatted_output:
            return self.formatted_output
        return self._build_formatted_output()

    def _build_formatted_output(self) -> str:
        parts = []

        # 演变链（如果有）
        if self.evolution and self.evolution.chain:
            parts.append(f"## 决策演变: {self.evolution.subject}")
            for cp in self.evolution.chain:
                parts.append(
                    f"  - [轮次{cp.turn_id}] {cp.field}: {cp.old_value} → {cp.new_value}"
                    + (f"（原因: {cp.reason}）" if cp.reason else "")
                )
            if self.evolution.current_state:
                parts.append(f"  **当前有效**: {self.evolution.current_state}")
            parts.append("")

        # 时间线
        if self.timeline:
            parts.append("## 相关历史轮次")
            for entry in self.timeline:
                prefix = "⚡" if entry.has_change else "•"
                line = f"  {prefix} [轮次{entry.turn_id}] {entry.user_query[:80]}"
                if entry.change_summary:
                    line += f" → {entry.change_summary}"
                if entry.data_age_label:
                    line += f" [{entry.data_age_label}]"
                parts.append(line)
            parts.append("")

        # 当前状态
        if self.current_state_summary:
            parts.append(f"## 当前有效状态\n  {self.current_state_summary}")

        return "\n".join(parts) if parts else "历史存档中未找到相关内容。"


# ═══════════════════════════════════════════════════════════
# 核心服务
# ═══════════════════════════════════════════════════════════

class ContextArchiveService:
    """对话存档检索服务 — 与记忆系统共享 VDB 存储，但检索逻辑完全独立

    使用方式:
      service = ContextArchiveService(archive)
      result = await service.recall("PT Sentosa 报价怎么变的", mode="timeline")
      context_text = result.to_llm_context()
    """

    def __init__(self, archive):
        """
        Args:
            archive: ContextArchive 实例（提供底层 search/get_by_turn_id 能力）
        """
        self._archive = archive

    async def recall(
        self,
        query: str,
        mode: str = "timeline",
        top_k: int = 8,
        target_turn_id: int | None = None,
    ) -> ArchiveRecallResult:
        """主检索入口

        Args:
            query: 用户问题或搜索关键词
            mode:
              "timeline" — 返回按时间排序的变更链（默认）
              "latest"   — 只返回与查询最相关的最新状态
              "full"     — 返回某轮的完整原文（需指定 target_turn_id）
            top_k: 检索条数上限
            target_turn_id: 指定展开某轮原文（仅 mode="full" 时使用）

        Returns:
            ArchiveRecallResult — 结构化检索结果
        """
        if mode == "full" and target_turn_id is not None:
            return await self._recall_full(target_turn_id)

        # Step 1: 从 VDB + PG 检索候选轮次
        entries = await self._search_entries(query, top_k)
        if not entries:
            return ArchiveRecallResult(
                formatted_output="历史存档中未找到相关内容。建议使用业务工具重新查询最新数据。"
            )

        # Step 2: 按时间线排序
        entries.sort(key=lambda e: e.timestamp)

        # Step 3: 变更检测
        changes = self._detect_changes(entries, query)

        # Step 4: 构建倾向链
        evolution = self._build_evolution_chain(entries, changes, query)

        # Step 5: 构建时间线条目
        timeline = self._build_timeline(entries, changes)

        # Step 6: 提取当前有效状态
        current_state = self._extract_current_state(entries, changes)

        if mode == "latest":
            # 只返回最新相关条目
            latest_entries = entries[-3:] if len(entries) > 3 else entries
            timeline = self._build_timeline(latest_entries, changes)

        result = ArchiveRecallResult(
            timeline=timeline,
            changes=changes,
            evolution=evolution,
            current_state_summary=current_state,
        )
        result.formatted_output = result._build_formatted_output()
        return result

    async def recall_by_entity(
        self,
        entity_name: str,
        attribute: str | None = None,
        top_k: int = 10,
    ) -> ArchiveRecallResult:
        """按实体名检索其历史变更

        Args:
            entity_name: 实体名称（如 "PT Sentosa"）
            attribute: 可选的属性名（如 "报价"、"联系人"），缩小检索范围
        """
        query = entity_name
        if attribute:
            query = f"{entity_name} {attribute}"
        return await self.recall(query, mode="timeline", top_k=top_k)

    # ═══════════════════════════════════════════════════════════
    # Level 2: 展开某轮完整原文
    # ═══════════════════════════════════════════════════════════

    async def _recall_full(self, turn_id: int) -> ArchiveRecallResult:
        """获取某轮次的完整原始消息"""
        entry = self._archive.get_by_turn_id(turn_id)
        if not entry:
            return ArchiveRecallResult(
                formatted_output=f"轮次 {turn_id} 的存档记录未找到。"
            )

        # 反序列化原始消息
        try:
            messages = json.loads(entry.original_messages_json) if entry.original_messages_json else []
        except (json.JSONDecodeError, TypeError):
            messages = []

        # 数据时效性标注
        age_label = self._archive.get_data_age_description(entry)
        is_stale = self._archive.is_data_likely_stale(entry)

        # 格式化完整内容
        parts = [f"## 轮次 {turn_id} 完整内容 [{age_label}]"]
        if is_stale:
            parts.append("⚠️ 注意: 该数据可能已过时，建议使用业务工具重新查询确认。\n")

        parts.append(f"**用户问题**: {entry.user_query}")
        parts.append(f"**使用工具**: {', '.join(entry.tool_names) if entry.tool_names else '无'}")
        parts.append(f"**涉及实体**: {', '.join(entry.entities) if entry.entities else '无'}")
        parts.append("")

        # 展开原始消息
        if messages:
            parts.append("### 对话过程")
            for msg in messages:
                role = msg.get("role", "unknown")
                content = msg.get("content", "")
                if role == "human":
                    parts.append(f"  👤 用户: {content[:500]}")
                elif role == "ai":
                    tool_calls = msg.get("tool_calls", [])
                    if tool_calls:
                        for tc in tool_calls:
                            args_str = json.dumps(tc.get("args", {}), ensure_ascii=False)[:200]
                            parts.append(f"  🤖 调用工具: {tc.get('name', '')}({args_str})")
                    if content:
                        parts.append(f"  🤖 Agent: {content[:500]}")
                elif role == "tool":
                    name = msg.get("name", "tool")
                    if len(content) > 300:
                        parts.append(f"  🔧 [{name}]: {content[:300]}...")
                    else:
                        parts.append(f"  🔧 [{name}]: {content}")
        else:
            parts.append(f"**Agent 回复**: {entry.answer_preview}")

        return ArchiveRecallResult(
            full_content=messages,
            formatted_output="\n".join(parts),
        )

    # ═══════════════════════════════════════════════════════════
    # 检索层
    # ═══════════════════════════════════════════════════════════

    async def _search_entries(self, query: str, top_k: int):
        """检索候选轮次（VDB 混合检索）

        流程: query rewrite → VDB hybrid_search → 邻轮扩展
        """
        # Step 0: Query Rewrite（零 LLM，纯规则）
        from src.middleware.archive_query_rewriter import ArchiveQueryRewriter
        rewriter = ArchiveQueryRewriter(
            active_entities=self._get_active_entities(),
            current_summary="",
        )
        rewrite_result = rewriter.rewrite(query)
        search_query = rewrite_result.rewritten_query

        # 检索
        entries = self._archive.search(search_query, top_k=top_k)

        # 连续轮次扩展: 对话是连续的，命中某轮时其相邻轮次大概率也相关
        if entries:
            entries = self._expand_neighbors(entries, top_k)

        return entries

    def _get_active_entities(self) -> list[str]:
        """从最近的检索结果中提取活跃实体（简单缓存）"""
        # 尝试从 archive 获取最近存档的实体
        try:
            recent = self._archive.search("", top_k=3)
            entities = []
            for entry in recent:
                entities.extend(entry.entities)
            return list(dict.fromkeys(entities))[:5]
        except Exception:
            return []

    def _expand_neighbors(self, entries: list, top_k: int) -> list:
        """扩展相邻轮次 — 对话连续性先验

        原理: 如果 turn 6 被命中，turn 5（前因）和 turn 7（后果）
        与 turn 6 有共享实体时，大概率属于同一段对话上下文。

        限制: 最多扩展 top_k * 1.5 条，避免无限膨胀。
        """
        if not entries:
            return entries

        max_total = int(top_k * 1.5)
        hit_ids = {e.turn_id for e in entries}
        expanded = list(entries)

        for entry in entries:
            if len(expanded) >= max_total:
                break
            entry_entities = set(entry.entities)
            if not entry_entities:
                continue

            # 检查前一轮和后一轮
            for neighbor_id in [entry.turn_id - 1, entry.turn_id + 1]:
                if neighbor_id in hit_ids or neighbor_id < 1:
                    continue
                if len(expanded) >= max_total:
                    break

                neighbor = self._archive.get_by_turn_id(neighbor_id)
                if neighbor is None:
                    continue

                # 共享实体检查: 必须有交集才扩展
                neighbor_entities = set(neighbor.entities)
                if entry_entities & neighbor_entities:
                    expanded.append(neighbor)
                    hit_ids.add(neighbor_id)

        return expanded

    # ═══════════════════════════════════════════════════════════
    # 变更检测
    # ═══════════════════════════════════════════════════════════

    def _detect_changes(self, entries: list, query: str) -> list[ChangePoint]:
        """检测同一实体/属性在多个轮次间的变更

        策略:
          1. 从每轮的 key_data 中提取与 query 相关的数值型字段
          2. 按时间顺序对比相邻轮次，值不同则标记为变更
          3. 从对话内容中提取变更原因
        """
        if len(entries) < 2:
            return []

        changes: list[ChangePoint] = []
        prev_values: dict[str, str] = {}

        for entry in entries:
            current_values = self._extract_trackable_values(entry, query)

            for field_name, value in current_values.items():
                if field_name in prev_values and prev_values[field_name] != value:
                    reason = self._extract_change_reason(entry, field_name, prev_values[field_name], value)
                    actor = self._infer_change_actor(entry)

                    changes.append(ChangePoint(
                        turn_id=entry.turn_id,
                        timestamp=entry.timestamp,
                        field=field_name,
                        old_value=prev_values[field_name],
                        new_value=value,
                        reason=reason,
                        actor=actor,
                    ))
                prev_values[field_name] = value

        return changes

    def _extract_trackable_values(self, entry, query: str) -> dict[str, str]:
        """从存档条目中提取可追踪的值

        提取策略:
          - key_data 中的金额/日期/百分比
          - answer_preview 中与 query 实体相关的数值
          - tool_summaries 中的关键数据
        """
        values: dict[str, str] = {}
        query_lower = query.lower()

        # 从 key_data 提取
        key_data = entry.key_data if isinstance(entry.key_data, dict) else {}
        for category, items in key_data.items():
            if isinstance(items, list):
                for i, item in enumerate(items):
                    values[f"{category}_{i}"] = str(item)

        # 从 answer_preview 提取报价/金额模式
        preview = entry.answer_preview or ""
        # 报价模式: "$45K" / "¥30万" / "45,000 USD"
        amounts_in_preview = re.findall(
            r'[\$¥￥]\s*[\d,.]+[KMB万亿]?|\d[\d,.]*\s*(?:万|亿|USD|CNY|元)', preview
        )
        for amt in amounts_in_preview:
            # 关联到查询中的实体
            entities_in_query = _extract_entity_names(query)
            for entity in (entities_in_query or ["主体"]):
                if entity.lower() in preview.lower() or entity.lower() in query_lower:
                    values[f"{entity}_金额"] = amt
                    break
            else:
                values[f"金额"] = amt

        # 从 answer_preview 提取百分比
        pcts_in_preview = re.findall(r'\d+\.?\d*\s*%', preview)
        for pct in pcts_in_preview:
            values["比例"] = pct

        # 从 answer_preview 提取日期
        dates_in_preview = re.findall(r'\d{4}[-/]\d{1,2}[-/]\d{1,2}', preview)
        for date in dates_in_preview:
            values["日期"] = date

        return values

    def _extract_change_reason(
        self, entry, field_name: str, old_value: str, new_value: str
    ) -> str:
        """从对话内容中提取变更原因

        策略:
          - 检查 user_query 中是否有"因为"、"改为"、"调整"等关键词
          - 检查 answer_preview 中的原因说明
        """
        reason_patterns = [
            # 中文原因模式
            r'(?:因为|由于|原因是|考虑到|基于)(.{5,50})',
            r'(?:客户|用户)(?:反馈|要求|提出|建议|觉得|认为)(.{5,50})',
            r'(?:调整|修改|变更)(?:为|到|成).*?(?:因为|由于|原因)(.{5,50})',
            # 英文原因模式
            r'(?:because|due to|since|as)\s+(.{5,50})',
            r'(?:client|customer)\s+(?:requested|asked|suggested)\s+(.{5,50})',
        ]

        # 在 user_query 和 answer_preview 中搜索
        search_text = f"{entry.user_query} {entry.answer_preview}"
        for pattern in reason_patterns:
            match = re.search(pattern, search_text, re.IGNORECASE)
            if match:
                return match.group(1).strip()[:100]

        # 兜底: 如果 user_query 本身就是变更指令
        change_indicators = ["改", "调", "降", "升", "加", "减", "换", "取消"]
        if any(ind in (entry.user_query or "") for ind in change_indicators):
            return entry.user_query[:60]

        return ""

    def _infer_change_actor(self, entry) -> str:
        """推断变更发起者"""
        query = entry.user_query or ""
        # 用户主动发起变更的信号
        user_indicators = ["帮我", "请", "改", "调", "我要", "我想", "换成", "降到"]
        if any(ind in query for ind in user_indicators):
            return "user"
        # 工具返回引起的变更
        if entry.tool_names:
            return "tool"
        return "agent"

    # ═══════════════════════════════════════════════════════════
    # 倾向链构建
    # ═══════════════════════════════════════════════════════════

    def _build_evolution_chain(
        self, entries: list, changes: list[ChangePoint], query: str
    ) -> EvolutionChain | None:
        """构建倾向/决策演变链

        只有在检测到 ≥1 个变更时才生成演变链。
        """
        if not changes:
            return None

        # 确定演变主体（从 query 中提取实体 + 属性）
        entities = _extract_entity_names(query)
        subject = entities[0] if entities else query[:30]

        # 按字段分组，取变更最多的字段作为主线
        field_changes: dict[str, list[ChangePoint]] = {}
        for cp in changes:
            field_changes.setdefault(cp.field, []).append(cp)

        # 选择变更次数最多的字段作为主演变链
        main_field = max(field_changes, key=lambda f: len(field_changes[f]))
        main_chain = field_changes[main_field]

        # 确定当前有效值
        current_state = main_chain[-1].new_value if main_chain else ""

        # 构建决策依据
        reasons = [cp.reason for cp in main_chain if cp.reason]
        rationale = " → ".join(reasons) if reasons else ""

        return EvolutionChain(
            subject=f"{subject} {main_field}" if main_field != subject else subject,
            chain=main_chain,
            current_state=current_state,
            decision_rationale=rationale,
        )

    # ═══════════════════════════════════════════════════════════
    # 时间线构建
    # ═══════════════════════════════════════════════════════════

    def _build_timeline(self, entries: list, changes: list[ChangePoint]) -> list[TimelineEntry]:
        """构建时间线条目列表"""
        # 将变更按 turn_id 索引
        changes_by_turn: dict[int, list[ChangePoint]] = {}
        for cp in changes:
            changes_by_turn.setdefault(cp.turn_id, []).append(cp)

        timeline = []
        for entry in entries:
            turn_changes = changes_by_turn.get(entry.turn_id, [])
            has_change = len(turn_changes) > 0

            # 构建变更摘要
            change_summary = ""
            if turn_changes:
                summaries = []
                for cp in turn_changes:
                    summaries.append(f"{cp.field}: {cp.old_value} → {cp.new_value}")
                change_summary = "; ".join(summaries)

            # 数据时效性
            age_label = self._get_age_label(entry.data_timestamp)

            timeline.append(TimelineEntry(
                turn_id=entry.turn_id,
                timestamp=entry.timestamp,
                data_timestamp=entry.data_timestamp,
                user_query=entry.user_query,
                answer_preview=entry.answer_preview[:150],
                tools_used=entry.tool_names,
                entities=entry.entities,
                has_change=has_change,
                change_summary=change_summary,
                data_age_label=age_label,
            ))

        return timeline

    # ═══════════════════════════════════════════════════════════
    # 当前状态提取
    # ═══════════════════════════════════════════════════════════

    def _extract_current_state(self, entries: list, changes: list[ChangePoint]) -> str:
        """从最新轮次和变更链中提取当前有效状态"""
        if not entries:
            return ""

        parts = []

        # 从变更链取最新值
        if changes:
            # 按字段取最新变更
            latest_by_field: dict[str, ChangePoint] = {}
            for cp in changes:
                latest_by_field[cp.field] = cp  # 后面的覆盖前面的（时间升序）

            for field_name, cp in latest_by_field.items():
                parts.append(f"{field_name}: {cp.new_value}")

        # 如果没有变更，从最新轮次的 key_data 取
        if not parts and entries:
            latest = entries[-1]
            key_data = latest.key_data if isinstance(latest.key_data, dict) else {}
            for category, items in key_data.items():
                if isinstance(items, list) and items:
                    parts.append(f"{category}: {', '.join(str(i) for i in items[:3])}")

        return "; ".join(parts) if parts else ""

    # ═══════════════════════════════════════════════════════════
    # 辅助方法
    # ═══════════════════════════════════════════════════════════

    @staticmethod
    def _get_age_label(data_timestamp: float) -> str:
        """获取数据时效性标签"""
        if not data_timestamp:
            return ""
        age_seconds = time.time() - data_timestamp
        age_minutes = age_seconds / 60
        age_hours = age_seconds / 3600
        age_days = age_seconds / 86400

        if age_minutes < 5:
            return "实时"
        elif age_minutes < 60:
            return f"{int(age_minutes)}分钟前"
        elif age_hours < 4:
            return f"{age_hours:.0f}小时前"
        elif age_hours < 24:
            return f"{age_hours:.0f}小时前⚠️"
        else:
            return f"{age_days:.0f}天前⚠️过时"


# ═══════════════════════════════════════════════════════════
# 辅助函数
# ═══════════════════════════════════════════════════════════

def _extract_entity_names(text: str) -> list[str]:
    """从文本中提取实体名称"""
    if not text:
        return []
    entities: list[str] = []
    # 公司名
    entities += re.findall(r'(?:PT|CV|Ltd|Inc)\s+[\w\s]{2,20}', text)
    entities += re.findall(r'[\u4e00-\u9fa5]{2,10}(?:科技|集团|公司|有限|技术)', text)
    # 人名
    entities += re.findall(r'(?:Pak|Ibu|Mr|Ms|Dr|Prof)\s+\w+', text)
    # 中文人名（2-3字）
    entities += re.findall(r'(?:张|李|王|刘|陈|杨|赵|黄|周|吴|徐|孙|胡|朱|高|林|何|郭|马|罗)[\u4e00-\u9fa5]{1,2}', text)
    return list(dict.fromkeys(e.strip() for e in entities if len(e.strip()) > 1))[:10]
