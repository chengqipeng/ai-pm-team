-- ═══════════════════════════════════════════════════════════
-- 迁移：DROP ai_knowledge_segment 表
-- 日期：2026-05-09
-- 原因：全 VDB 架构迁移后，segment 表不再使用。
--       切片 section_path 信息已冗余到 ai_knowledge_chunk，
--       段落结构在入库时作为内存 dataclass 传递，不再持久化。
-- ═══════════════════════════════════════════════════════════

SET search_path TO paas_ai;

DROP TABLE IF EXISTS ai_knowledge_segment;
