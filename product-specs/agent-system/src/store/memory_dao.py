"""记忆 PG 存储 — 统一使用 ai_agent_memory 表

所有类别（profile / agent_rules / entities / events / cases / patterns / preferences）
统一存储在 ai_agent_memory 表中。PG 为权威数据源，向量库为检索索引。

迁移说明：
  - 原 agent_memory 表已废弃，所有读写迁移到 ai_agent_memory
  - 接口保持不变（MemoryDAO / MemoryRow），调用方无需修改
  - ai_agent_memory 表结构见 doc/长期记忆数据库表设计.md
"""
from __future__ import annotations

import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from .pg_pool import get_conn

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════
# 数据模型
# ═══════════════════════════════════════════════════════════

@dataclass
class MemoryRow:
    """PG 记忆行 — 对齐 ai_agent_memory 表结构"""
    id: int = 0
    memory_id: str = ""
    tenant_id: int = 0
    user_id: str = ""
    category: str = ""          # profile / agent_rules / entities / events / ...
    source_type: str = "insight"
    merge_key: str = ""         # 合并键
    parent_entity: str = ""     # 父实体
    abstract: str = ""          # L0 摘要
    overview: str = ""          # L1 概览
    content: str = ""           # L2 完整内容
    biz_id: str = ""            # CRM record_id
    biz_parent_id: str = ""     # 父实体 record_id
    biz_type: str = ""          # 业务实体类型
    thread_id: str = ""         # 来源会话
    message_id: int = 0         # 来源消息
    status: str = "active"      # active / archived / expired
    active_count: int = 0       # 检索命中次数
    confidence: float = 1.0     # 置信度
    vector_synced: int = 0      # 向量库同步状态
    vector_id: str = ""         # 向量库文档 ID
    metadata_json: str = "{}"   # 兼容旧接口的扩展元数据
    created_at: int = 0         # 毫秒时间戳
    updated_at: int = 0


# ═══════════════════════════════════════════════════════════
# 建表 SQL（ai_agent_memory，幂等）
# ═══════════════════════════════════════════════════════════

ENSURE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS ai_agent_memory (
    id              BIGSERIAL    PRIMARY KEY,
    memory_id       VARCHAR(64)  NOT NULL,
    tenant_id       BIGINT       NOT NULL DEFAULT 0,
    user_id         VARCHAR(64)  NOT NULL,
    category        VARCHAR(32)  NOT NULL,
    source_type     VARCHAR(32)  NOT NULL DEFAULT 'insight',
    abstract        TEXT         NOT NULL DEFAULT '',
    overview        TEXT         NOT NULL DEFAULT '',
    content         TEXT         NOT NULL DEFAULT '',
    merge_key       VARCHAR(512) NOT NULL DEFAULT '',
    parent_entity   VARCHAR(256) NOT NULL DEFAULT '',
    biz_id          VARCHAR(128) NOT NULL DEFAULT '',
    biz_parent_id   VARCHAR(128) NOT NULL DEFAULT '',
    biz_type        VARCHAR(64)  NOT NULL DEFAULT '',
    thread_id       VARCHAR(64)  NOT NULL DEFAULT '',
    message_id      BIGINT       NOT NULL DEFAULT 0,
    status          VARCHAR(20)  NOT NULL DEFAULT 'active',
    active_count    INT          NOT NULL DEFAULT 0,
    confidence      DECIMAL(5,4) NOT NULL DEFAULT 1.0,
    vector_synced   SMALLINT     NOT NULL DEFAULT 0,
    vector_id       VARCHAR(64)  NOT NULL DEFAULT '',
    delete_flg      SMALLINT     NOT NULL DEFAULT 0,
    created_at      BIGINT       NOT NULL DEFAULT 0,
    created_by      BIGINT       NOT NULL DEFAULT 0,
    updated_at      BIGINT       NOT NULL DEFAULT 0,
    updated_by      BIGINT       NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_memory_user_cat
    ON ai_agent_memory (tenant_id, user_id, category, delete_flg);

CREATE UNIQUE INDEX IF NOT EXISTS uk_memory_merge
    ON ai_agent_memory (tenant_id, user_id, category, merge_key)
    WHERE merge_key != '' AND delete_flg = 0;

CREATE INDEX IF NOT EXISTS idx_memory_parent
    ON ai_agent_memory (tenant_id, user_id, parent_entity)
    WHERE parent_entity != '' AND delete_flg = 0;

CREATE INDEX IF NOT EXISTS idx_memory_biz_id
    ON ai_agent_memory (biz_id)
    WHERE biz_id != '';

CREATE INDEX IF NOT EXISTS idx_memory_biz_parent
    ON ai_agent_memory (biz_parent_id)
    WHERE biz_parent_id != '';

CREATE INDEX IF NOT EXISTS idx_memory_status_time
    ON ai_agent_memory (tenant_id, category, status, updated_at)
    WHERE delete_flg = 0;

CREATE INDEX IF NOT EXISTS idx_memory_vector_sync
    ON ai_agent_memory (vector_synced, updated_at)
    WHERE vector_synced = 0 AND delete_flg = 0;

CREATE INDEX IF NOT EXISTS idx_memory_thread
    ON ai_agent_memory (tenant_id, thread_id)
    WHERE thread_id != '';
"""


# ═══════════════════════════════════════════════════════════
# DAO
# ═══════════════════════════════════════════════════════════

class MemoryDAO:
    """记忆 CRUD — 统一使用 ai_agent_memory 表

    接口保持与旧版兼容，调用方（VikingMemoryEngine / VikingFS）无需修改。
    """

    @staticmethod
    def ensure_table() -> None:
        """建表（幂等）"""
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(ENSURE_TABLE_SQL)
        logger.info("ai_agent_memory table ensured")

    # ── 写入 / 更新 ──

    @staticmethod
    def upsert(user_id: str, category: str, merge_key: str,
               abstract: str, overview: str = "", content: str = "",
               metadata: dict | None = None, now: int = 0,
               tenant_id: int = 0, parent_entity: str = "",
               thread_id: str = "", source_type: str = "insight") -> int:
        """写入或更新记忆（按 tenant_id + user_id + category + merge_key 唯一约束）

        - profile: merge_key="profile"，content 追加合并
        - tools/skills: merge_key=工具名/技能名，新值替换旧值
        - agent_rules: merge_key="agent_rules"，新值替换旧值
        """
        now = now or int(time.time() * 1000)
        memory_id = uuid.uuid4().hex[:16]

        with get_conn() as conn:
            with conn.cursor() as cur:
                if category == "profile" and merge_key == "profile":
                    # profile 特殊处理：追加合并 content
                    cur.execute("""
                        SELECT id, content FROM ai_agent_memory
                        WHERE tenant_id = %s AND user_id = %s
                          AND category = 'profile' AND merge_key = 'profile'
                          AND delete_flg = 0
                    """, (tenant_id, user_id))
                    row = cur.fetchone()
                    if row:
                        old_content = row[1] or ""
                        merged = old_content + "\n" + content if old_content else content
                        cur.execute("""
                            UPDATE ai_agent_memory
                            SET abstract = %s, overview = %s, content = %s,
                                updated_at = %s
                            WHERE id = %s
                        """, (abstract, overview, merged, now, row[0]))
                        return row[0]

                # 其他类别：upsert（有 merge_key 时按唯一约束更新，无则插入）
                if merge_key:
                    cur.execute("""
                        INSERT INTO ai_agent_memory
                            (memory_id, tenant_id, user_id, category, source_type,
                             abstract, overview, content, merge_key, parent_entity,
                             thread_id, status, created_at, updated_at)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'active', %s, %s)
                        ON CONFLICT (tenant_id, user_id, category, merge_key)
                            WHERE merge_key != '' AND delete_flg = 0
                        DO UPDATE SET
                            abstract = EXCLUDED.abstract,
                            overview = EXCLUDED.overview,
                            content = EXCLUDED.content,
                            parent_entity = EXCLUDED.parent_entity,
                            thread_id = EXCLUDED.thread_id,
                            updated_at = EXCLUDED.updated_at
                        RETURNING id
                    """, (memory_id, tenant_id, user_id, category, source_type,
                          abstract, overview, content, merge_key, parent_entity,
                          thread_id, now, now))
                else:
                    cur.execute("""
                        INSERT INTO ai_agent_memory
                            (memory_id, tenant_id, user_id, category, source_type,
                             abstract, overview, content, merge_key, parent_entity,
                             thread_id, status, created_at, updated_at)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'active', %s, %s)
                        RETURNING id
                    """, (memory_id, tenant_id, user_id, category, source_type,
                          abstract, overview, content, merge_key, parent_entity,
                          thread_id, now, now))

                result = cur.fetchone()
                return result[0] if result else 0

    # ── 查询 ──

    @staticmethod
    def get_by_user_category(user_id: str, category: str,
                             tenant_id: int = 0) -> list[MemoryRow]:
        """按用户+类别查询所有记忆"""
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT id, memory_id, tenant_id, user_id, category, source_type,
                           merge_key, parent_entity, abstract, overview, content,
                           biz_id, biz_parent_id, biz_type, thread_id, message_id,
                           status, active_count, confidence, vector_synced, vector_id,
                           created_at, updated_at
                    FROM ai_agent_memory
                    WHERE tenant_id = %s AND user_id = %s AND category = %s
                      AND delete_flg = 0 AND status = 'active'
                    ORDER BY updated_at DESC
                """, (tenant_id, user_id, category))
                return [_row_to_memory(row) for row in cur.fetchall()]

    @staticmethod
    def get_profile(user_id: str, tenant_id: int = 0) -> MemoryRow | None:
        """获取用户 profile（唯一一条）"""
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT id, memory_id, tenant_id, user_id, category, source_type,
                           merge_key, parent_entity, abstract, overview, content,
                           biz_id, biz_parent_id, biz_type, thread_id, message_id,
                           status, active_count, confidence, vector_synced, vector_id,
                           created_at, updated_at
                    FROM ai_agent_memory
                    WHERE tenant_id = %s AND user_id = %s
                      AND category = 'profile' AND merge_key = 'profile'
                      AND delete_flg = 0
                """, (tenant_id, user_id))
                row = cur.fetchone()
                return _row_to_memory(row) if row else None

    @staticmethod
    def get_agent_rules(user_id: str, tenant_id: int = 0) -> MemoryRow | None:
        """获取用户 Agent 行为准则（唯一一条）"""
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT id, memory_id, tenant_id, user_id, category, source_type,
                           merge_key, parent_entity, abstract, overview, content,
                           biz_id, biz_parent_id, biz_type, thread_id, message_id,
                           status, active_count, confidence, vector_synced, vector_id,
                           created_at, updated_at
                    FROM ai_agent_memory
                    WHERE tenant_id = %s AND user_id = %s
                      AND category = 'agent_rules' AND merge_key = 'agent_rules'
                      AND delete_flg = 0
                """, (tenant_id, user_id))
                row = cur.fetchone()
                return _row_to_memory(row) if row else None

    @staticmethod
    def get_all_for_reflection(user_id: str, tenant_id: int = 0) -> list[MemoryRow]:
        """获取用户所有记忆（用于反思，排除 agent_rules 本身）"""
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT id, memory_id, tenant_id, user_id, category, source_type,
                           merge_key, parent_entity, abstract, overview, content,
                           biz_id, biz_parent_id, biz_type, thread_id, message_id,
                           status, active_count, confidence, vector_synced, vector_id,
                           created_at, updated_at
                    FROM ai_agent_memory
                    WHERE tenant_id = %s AND user_id = %s AND category != 'agent_rules'
                      AND delete_flg = 0 AND status = 'active'
                    ORDER BY category, updated_at DESC
                """, (tenant_id, user_id))
                return [_row_to_memory(row) for row in cur.fetchall()]

    # ── 删除 ──

    @staticmethod
    def delete_by_id(memory_id: int) -> bool:
        """软删除（标记 delete_flg=1）"""
        now = int(time.time() * 1000)
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    UPDATE ai_agent_memory SET delete_flg = 1, updated_at = %s
                    WHERE id = %s AND delete_flg = 0
                """, (now, memory_id))
                return cur.rowcount > 0

    @staticmethod
    def delete_by_user_category(user_id: str, category: str,
                                tenant_id: int = 0) -> int:
        """按用户+类别软删除"""
        now = int(time.time() * 1000)
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    UPDATE ai_agent_memory SET delete_flg = 1, updated_at = %s
                    WHERE tenant_id = %s AND user_id = %s AND category = %s
                      AND delete_flg = 0
                """, (now, tenant_id, user_id, category))
                return cur.rowcount

    @staticmethod
    def delete_all(user_id: str, tenant_id: int = 0) -> int:
        """按用户软删除全部记忆"""
        now = int(time.time() * 1000)
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    UPDATE ai_agent_memory SET delete_flg = 1, updated_at = %s
                    WHERE tenant_id = %s AND user_id = %s AND delete_flg = 0
                """, (now, tenant_id, user_id))
                return cur.rowcount

    # ── 统计 ──

    @staticmethod
    def count_by_user(user_id: str, tenant_id: int = 0) -> dict[str, int]:
        """按类别统计记忆数量"""
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT category, COUNT(*) FROM ai_agent_memory
                    WHERE tenant_id = %s AND user_id = %s
                      AND delete_flg = 0 AND status = 'active'
                    GROUP BY category
                """, (tenant_id, user_id))
                return {row[0]: row[1] for row in cur.fetchall()}

    # ── 统计衰减 ──

    @staticmethod
    def decay_tool_stats(decay_factor: float = 0.7, tenant_id: int = 0) -> int:
        """工具/技能统计按月衰减

        对 tools 和 skills 类别的 active_count 乘以衰减系数。
        衰减后 active_count = 0 的标记为 stale（通过 status 字段）。
        建议每月执行一次。
        """
        now_ms = int(time.time() * 1000)
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    UPDATE ai_agent_memory
                    SET active_count = GREATEST(0, FLOOR(active_count * %s)),
                        updated_at = %s
                    WHERE category IN ('tools', 'skills')
                      AND active_count > 0 AND delete_flg = 0
                """, (decay_factor, now_ms))
                decayed = cur.rowcount

                cur.execute("""
                    UPDATE ai_agent_memory
                    SET status = 'archived', updated_at = %s
                    WHERE category IN ('tools', 'skills')
                      AND active_count = 0 AND status = 'active'
                      AND delete_flg = 0
                """, (now_ms,))
        return decayed


# ═══════════════════════════════════════════════════════════
# 内部工具函数
# ═══════════════════════════════════════════════════════════

def _row_to_memory(row) -> MemoryRow:
    """将查询结果行转为 MemoryRow"""
    if not row:
        return MemoryRow()
    return MemoryRow(
        id=row[0],
        memory_id=row[1],
        tenant_id=row[2],
        user_id=row[3],
        category=row[4],
        source_type=row[5],
        merge_key=row[6],
        parent_entity=row[7],
        abstract=row[8],
        overview=row[9],
        content=row[10],
        biz_id=row[11],
        biz_parent_id=row[12],
        biz_type=row[13],
        thread_id=row[14],
        message_id=row[15],
        status=row[16],
        active_count=row[17],
        confidence=float(row[18]) if row[18] else 1.0,
        vector_synced=row[19],
        vector_id=row[20],
        created_at=row[21],
        updated_at=row[22],
    )
