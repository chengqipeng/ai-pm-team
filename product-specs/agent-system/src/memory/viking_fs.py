"""VikingFS — 虚拟文件系统范式的记忆路径管理

参考 OpenViking 的文件系统范式，用 PG 表模拟目录树结构。
不是真正的文件系统，而是基于 URI 路径的记忆组织层。

核心概念:
  - 每条记忆有一个 URI 路径（如 viking://user/memories/entities/华为科技/ERP升级项目）
  - 每个目录有聚合的 L0 摘要（如 viking://user/memories/entities/华为科技/ 的摘要是"华为科技: 3商机780万"）
  - 支持 ls / tree / read / find / mkdir / rm 操作
  - 目录的 L0 摘要在子条目变更时自动更新

URI 格式:
  viking://{space}/memories/{category}/{parent}/{name}

  space:    "user" 或 "agent"
  category: 8 类之一
  parent:   父实体（可选，如 "华为科技"）
  name:     记忆名（可选，如 "ERP升级项目"）

目录结构示例:
  viking://user/memories/
  ├── profile                              → 单条记忆
  ├── preferences/
  │   ├── .abstract.md                     → 目录 L0: "用户偏好: 表格展示、简洁风格、中文"
  │   ├── 数据展示偏好                      → L2: "用户偏好表格展示..."
  │   └── 回复风格偏好                      → L2: "用户偏好简洁风格..."
  ├── entities/
  │   ├── .abstract.md                     → 目录 L0: "3个客户: 华为(780万)、腾讯(2000万)、小米(2450万)"
  │   ├── 华为科技/
  │   │   ├── .abstract.md                 → 目录 L0: "华为科技: 3商机780万，2联系人"
  │   │   ├── ERP升级项目                   → L2: "金额500万，谈判阶段..."
  │   │   ├── 云迁移项目                    → L2: "金额200万，方案阶段..."
  │   │   └── 张总                          → L2: "CTO，139-xxxx..."
  │   └── 腾讯/
  │       └── ...
  └── events/
      ├── 2026-04-28_华为ERP评审通过         → L2: "丁总同意报价方案..."
      └── 2026-04-25_腾讯项目启动            → L2: "确定技术方案..."

  viking://agent/memories/
  ├── cases/
  │   └── 查询报错_字段名拼写                → L2: "stage写成status..."
  ├── patterns/
  │   └── 客户360分析流程                    → L2: "基本信息→商机→联系人→活动→汇总"
  ├── tools/
  │   └── query_data                        → L2: "调用42次，成功率95%..."
  └── skills/
      └── Pipeline报告                      → L2: "阶段统计→负责人统计→环比→建议"
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════
# URI 解析与构建
# ═══════════════════════════════════════════════════════════

# 类别 → space 映射
_CATEGORY_SPACE = {
    "profile": "user", "preferences": "user",
    "entities": "user", "events": "user",
    "cases": "agent", "patterns": "agent",
    "tools": "agent", "skills": "agent",
    "agent_rules": "user",
}


@dataclass
class VikingURI:
    """解析后的 viking:// URI"""
    raw: str = ""
    space: str = ""          # "user" / "agent"
    category: str = ""       # 8 类之一
    parent: str = ""         # 父实体（如 "华为科技"）
    name: str = ""           # 记忆名（如 "ERP升级项目"）
    is_directory: bool = False

    @property
    def path(self) -> str:
        """不含 viking:// 前缀的路径"""
        parts = [self.space, "memories", self.category]
        if self.parent:
            parts.append(self.parent)
        if self.name:
            parts.append(self.name)
        p = "/".join(p for p in parts if p)
        return p + ("/" if self.is_directory else "")

    @property
    def full(self) -> str:
        return f"viking://{self.path}"

    @property
    def parent_uri(self) -> str:
        """父目录 URI"""
        parts = [self.space, "memories", self.category]
        if self.parent:
            parts.append(self.parent)
        return "viking://" + "/".join(p for p in parts if p) + "/"

    @property
    def depth(self) -> int:
        """路径深度（用于 tree 展示缩进）"""
        d = 0
        if self.category:
            d += 1
        if self.parent:
            d += 1
        if self.name:
            d += 1
        return d


def parse_uri(uri: str) -> VikingURI:
    """解析 viking:// URI"""
    if not uri.startswith("viking://"):
        return VikingURI(raw=uri)

    path = uri[len("viking://"):]
    is_dir = path.endswith("/")
    parts = [p for p in path.strip("/").split("/") if p]

    r = VikingURI(raw=uri, is_directory=is_dir)
    if len(parts) >= 1:
        r.space = parts[0]
    # parts[1] 是 "memories"，跳过
    if len(parts) >= 3:
        r.category = parts[2]
    if len(parts) >= 4:
        r.parent = parts[3]
    if len(parts) >= 5:
        r.name = parts[4]
    return r


def build_uri(category: str, merge_key: str = "", parent_entity: str = "") -> str:
    """从记忆字段构建 viking:// URI"""
    space = _CATEGORY_SPACE.get(category, "user")
    parts = [space, "memories", category]

    if parent_entity:
        parts.append(parent_entity)
        if merge_key and merge_key != parent_entity:
            # merge_key = "华为科技/ERP升级" → name = "ERP升级"
            name = merge_key.split("/")[-1] if "/" in merge_key else merge_key
            if name != parent_entity:
                parts.append(name)
    elif merge_key:
        parts.append(merge_key)

    return "viking://" + "/".join(p for p in parts if p)


def build_parent_uri(category: str, parent_entity: str = "") -> str:
    """构建父目录 URI"""
    space = _CATEGORY_SPACE.get(category, "user")
    parts = [space, "memories", category]
    if parent_entity:
        parts.append(parent_entity)
    return "viking://" + "/".join(parts) + "/"


# ═══════════════════════════════════════════════════════════
# VikingFS — 虚拟文件系统操作
# ═══════════════════════════════════════════════════════════

@dataclass
class FSNode:
    """文件系统节点（文件或目录）"""
    uri: str = ""
    name: str = ""
    is_directory: bool = False
    abstract: str = ""       # L0 摘要
    overview: str = ""       # L1 概览
    content: str = ""        # L2 完整内容
    category: str = ""
    children_count: int = 0  # 子条目数（目录时有效）
    updated_at: str = ""


class VikingFS:
    """虚拟文件系统 — 基于 PG(ai_agent_memory) + 向量库的路径索引层

    PG 存储（ai_agent_memory 表）: 全部类别的权威数据源
      - 精确查询类: profile / agent_rules
      - 语义检索类: entities / events / cases / patterns / preferences
    向量库: 语义检索索引（从库，只存 embedding + 元数据）

    VikingFS 在两者之上提供统一的 URI 路径视图。

    Args:
        pg_dao: MemoryDAO 实例（读写 ai_agent_memory 表）
        vdb: VectorStore 实例（向量库检索）
        user_id: 当前用户 ID
    """

    # PG 类别
    _PG_CATS = {"profile", "agent_rules"}
    # 向量库类别
    _VDB_CATS = {"entities", "events", "cases", "patterns", "preferences"}

    def __init__(self, pg_dao: Any = None, vdb: Any = None, user_id: str = ""):
        self._pg = pg_dao
        self._vdb = vdb
        self._uid = user_id

    # ── ls: 列出目录下的直接子条目 ──

    def ls(self, uri: str = "viking://user/memories/") -> list[FSNode]:
        """列出目录下的直接子条目

        示例:
          ls("viking://user/memories/")
            → [profile, preferences/, entities/, events/]
          ls("viking://user/memories/entities/")
            → [华为科技/, 腾讯/, 小米集团/]
          ls("viking://user/memories/entities/华为科技/")
            → [ERP升级项目, 云迁移项目, 张总, 李经理]
        """
        parsed = parse_uri(uri)
        nodes: list[FSNode] = []

        # 根目录: 列出所有类别
        if not parsed.category:
            for cat in sorted(set(list(self._PG_CATS) + list(self._VDB_CATS))):
                space = _CATEGORY_SPACE.get(cat, "user")
                if space != parsed.space:
                    continue
                is_dir = cat not in ("profile", "agent_rules")  # profile 和 agent_rules 是单文件
                count = self._count_in_category(cat)
                nodes.append(FSNode(
                    uri=f"viking://{space}/memories/{cat}" + ("/" if is_dir else ""),
                    name=cat, is_directory=is_dir, category=cat,
                    children_count=count,
                    abstract=f"{cat}: {count} 条记忆",
                ))
            return nodes

        # 类别目录: 列出该类别下的条目
        if parsed.category and not parsed.parent:
            return self._ls_category(parsed.category)

        # 实体目录: 列出该实体下的子条目
        if parsed.category and parsed.parent and not parsed.name:
            return self._ls_entity(parsed.category, parsed.parent)

        return nodes

    def _ls_category(self, category: str) -> list[FSNode]:
        """列出类别下的条目（按 parent_entity 分组）"""
        nodes = []

        if category in self._PG_CATS and self._pg:
            rows = self._pg.get_by_user_category(self._uid, category)
            # 按 merge_key 的第一段分组（如 "华为科技/ERP" → "华为科技"）
            groups: dict[str, list] = {}
            for r in rows:
                key = r.merge_key.split("/")[0] if "/" in r.merge_key else r.merge_key
                groups.setdefault(key, []).append(r)

            for key, items in sorted(groups.items()):
                if len(items) == 1 and "/" not in items[0].merge_key:
                    # 单条记忆（如 preferences 的单个 aspect）
                    nodes.append(FSNode(
                        uri=build_uri(category, items[0].merge_key),
                        name=key, is_directory=False, category=category,
                        abstract=items[0].abstract,
                    ))
                else:
                    # 多条记忆 → 目录
                    nodes.append(FSNode(
                        uri=build_parent_uri(category, key),
                        name=key, is_directory=True, category=category,
                        children_count=len(items),
                        abstract=f"{key}: {len(items)} 条",
                    ))

        elif category in self._VDB_CATS and self._vdb:
            try:
                # 从向量库查询该类别下所有 parent_entity 为空的顶层条目
                results = self._vdb.query_by_filter(
                    f'user_id = "{self._uid}" and category = "{category}" and parent_entity = ""',
                    limit=50,
                )
                for r in results:
                    mk = r.get("merge_key", "")
                    # preferences 的每个 aspect 是叶子节点（无层级结构）
                    if category == "preferences":
                        nodes.append(FSNode(
                            uri=build_uri(category, mk),
                            name=mk or r.get("abstract", "")[:30],
                            is_directory=False, category=category,
                            abstract=r.get("abstract", ""),
                            content=r.get("content", ""),
                        ))
                    else:
                        nodes.append(FSNode(
                            uri=build_parent_uri(category, mk) if mk else build_uri(category, mk),
                            name=mk or r.get("abstract", "")[:30],
                            is_directory=True, category=category,
                            abstract=r.get("abstract", ""),
                        ))
                # 也查有 parent_entity 但 parent_entity 不在顶层的
                results2 = self._vdb.query_by_filter(
                    f'user_id = "{self._uid}" and category = "{category}" and parent_entity != ""',
                    limit=100,
                )
                # 收集所有 parent_entity
                parents = set()
                for r in results2:
                    pe = r.get("parent_entity", "")
                    if pe:
                        parents.add(pe)
                # 已有顶层条目的 parent 不重复添加
                existing = {n.name for n in nodes}
                for pe in sorted(parents):
                    if pe not in existing:
                        children = [r for r in results2 if r.get("parent_entity") == pe]
                        nodes.append(FSNode(
                            uri=build_parent_uri(category, pe),
                            name=pe, is_directory=True, category=category,
                            children_count=len(children),
                            abstract=f"{pe}: {len(children)} 条子记忆",
                        ))
            except Exception as e:
                logger.warning("VDB ls failed: %s", e)

        return nodes

    def _ls_entity(self, category: str, parent: str) -> list[FSNode]:
        """列出实体下的子条目"""
        nodes = []

        if category in self._PG_CATS and self._pg:
            rows = self._pg.get_by_user_category(self._uid, category)
            for r in rows:
                if r.merge_key.startswith(parent + "/") or r.merge_key == parent:
                    name = r.merge_key.split("/")[-1] if "/" in r.merge_key else r.merge_key
                    nodes.append(FSNode(
                        uri=build_uri(category, r.merge_key, parent),
                        name=name, is_directory=False, category=category,
                        abstract=r.abstract, content=r.content,
                    ))

        elif category in self._VDB_CATS and self._vdb:
            try:
                results = self._vdb.query_by_filter(
                    f'user_id = "{self._uid}" and category = "{category}" and parent_entity = "{parent}"',
                    limit=50,
                )
                for r in results:
                    mk = r.get("merge_key", "")
                    name = mk.split("/")[-1] if "/" in mk else mk
                    nodes.append(FSNode(
                        uri=build_uri(category, mk, parent),
                        name=name or r.get("abstract", "")[:30],
                        is_directory=False, category=category,
                        abstract=r.get("abstract", ""),
                        content=r.get("content", ""),
                    ))
            except Exception as e:
                logger.warning("VDB ls entity failed: %s", e)

        return nodes

    # ── tree: 递归展示目录树 ──

    def tree(self, uri: str = "viking://user/memories/", max_depth: int = 3) -> str:
        """递归展示目录树（文本格式）

        示例输出:
          viking://user/memories/
          ├── profile: 华东区销售总监，管理15人团队
          ├── preferences/
          │   ├── 数据展示偏好: 表格格式
          │   └── 回复风格偏好: 简洁，给结论
          ├── entities/
          │   ├── 华为科技/ (5 条)
          │   │   ├── ERP升级项目: 金额500万，谈判阶段
          │   │   ├── 云迁移项目: 金额200万，方案阶段
          │   │   └── 张总: CTO，139-xxxx
          │   └── 腾讯/ (3 条)
          └── events/
              └── 2026-04-28_华为ERP评审通过
        """
        lines = [uri]
        self._tree_recursive(uri, lines, prefix="", depth=0, max_depth=max_depth)
        return "\n".join(lines)

    def _tree_recursive(self, uri: str, lines: list[str], prefix: str,
                        depth: int, max_depth: int) -> None:
        if depth >= max_depth:
            return
        children = self.ls(uri)
        for i, child in enumerate(children):
            is_last = (i == len(children) - 1)
            connector = "└── " if is_last else "├── "
            label = child.name
            if child.is_directory:
                label += "/"
                if child.children_count > 0:
                    label += f" ({child.children_count} 条)"
            elif child.abstract:
                label += f": {child.abstract[:50]}"

            lines.append(f"{prefix}{connector}{label}")

            if child.is_directory:
                next_prefix = prefix + ("    " if is_last else "│   ")
                self._tree_recursive(child.uri, lines, next_prefix, depth + 1, max_depth)

    # ── read: 读取指定路径的记忆 ──

    def read(self, uri: str, level: str = "L2") -> FSNode | None:
        """读取指定 URI 的记忆内容

        Args:
            uri: viking:// URI
            level: "L0"(abstract) / "L1"(overview) / "L2"(content)
        """
        parsed = parse_uri(uri)
        if not parsed.category:
            return None

        if parsed.category in self._PG_CATS and self._pg:
            rows = self._pg.get_by_user_category(self._uid, parsed.category)
            for r in rows:
                if self._match_uri(r, parsed):
                    return FSNode(
                        uri=uri, name=parsed.name or parsed.parent or parsed.category,
                        category=parsed.category,
                        abstract=r.abstract, overview=r.overview, content=r.content,
                    )

        elif parsed.category in self._VDB_CATS and self._vdb:
            try:
                mk = f"{parsed.parent}/{parsed.name}" if parsed.parent and parsed.name else (parsed.parent or parsed.name or "")
                filter_parts = [f'user_id = "{self._uid}"', f'category = "{parsed.category}"']
                if mk:
                    filter_parts.append(f'merge_key = "{mk}"')
                results = self._vdb.query_by_filter(" and ".join(filter_parts), limit=1)
                if results:
                    r = results[0]
                    return FSNode(
                        uri=uri, name=parsed.name or parsed.parent,
                        category=parsed.category,
                        abstract=r.get("abstract", ""),
                        overview=r.get("overview", ""),
                        content=r.get("content", ""),
                    )
            except Exception as e:
                logger.warning("VDB read failed: %s", e)

        return None

    # ── find: 路径前缀搜索 ──

    def find(self, pattern: str) -> list[FSNode]:
        """按路径前缀或关键词搜索

        示例:
          find("华为")     → 所有包含"华为"的记忆
          find("entities/华为") → entities 类别下华为相关的记忆
        """
        nodes = []

        # PG 搜索
        if self._pg:
            for cat in self._PG_CATS:
                rows = self._pg.get_by_user_category(self._uid, cat)
                for r in rows:
                    if pattern in r.merge_key or pattern in r.abstract or pattern in r.content:
                        nodes.append(FSNode(
                            uri=build_uri(cat, r.merge_key),
                            name=r.merge_key, category=cat,
                            abstract=r.abstract,
                        ))

        # 向量库搜索
        if self._vdb:
            for cat in self._VDB_CATS:
                try:
                    results = self._vdb.query_by_filter(
                        f'user_id = "{self._uid}" and category = "{cat}"', limit=50,
                    )
                    for r in results:
                        mk = r.get("merge_key", "")
                        abstract = r.get("abstract", "")
                        if pattern in mk or pattern in abstract:
                            nodes.append(FSNode(
                                uri=build_uri(cat, mk, r.get("parent_entity", "")),
                                name=mk, category=cat,
                                abstract=abstract,
                            ))
                except Exception:
                    pass

        return nodes

    # ── rm: 删除 ──

    def rm(self, uri: str) -> bool:
        """删除指定 URI 的记忆"""
        parsed = parse_uri(uri)
        if not parsed.category:
            return False

        if parsed.category in self._PG_CATS and self._pg:
            rows = self._pg.get_by_user_category(self._uid, parsed.category)
            for r in rows:
                if self._match_uri(r, parsed):
                    return self._pg.delete_by_id(r.id)

        elif parsed.category in self._VDB_CATS and self._vdb:
            try:
                mk = f"{parsed.parent}/{parsed.name}" if parsed.parent and parsed.name else ""
                if mk:
                    results = self._vdb.query_by_filter(
                        f'user_id = "{self._uid}" and category = "{parsed.category}" and merge_key = "{mk}"',
                        limit=1,
                    )
                    if results:
                        self._vdb.delete([results[0].get("id", "")])
                        return True
            except Exception as e:
                logger.warning("VDB rm failed: %s", e)

        return False

    # ── 辅助 ──

    def _count_in_category(self, category: str) -> int:
        if category in self._PG_CATS and self._pg:
            rows = self._pg.get_by_user_category(self._uid, category)
            return len(rows)
        elif category in self._VDB_CATS and self._vdb:
            try:
                results = self._vdb.query_by_filter(
                    f'user_id = "{self._uid}" and category = "{category}"', limit=200,
                )
                return len(results)
            except Exception:
                return 0
        return 0

    @staticmethod
    def _match_uri(row, parsed: VikingURI) -> bool:
        """检查 PG 行是否匹配 URI"""
        mk = row.merge_key
        if parsed.name:
            return mk == f"{parsed.parent}/{parsed.name}" or mk == parsed.name
        if parsed.parent:
            return mk == parsed.parent or mk.startswith(parsed.parent + "/")
        return mk == parsed.category or mk == ""
