-- ═══════════════════════════════════════════════════════════
-- 修复 ai_skill_resource 中 parent_id 为 NULL 的错误数据
--
-- 问题原因：_copy_resources 在复制版本时使用 path.rsplit 查找父目录，
--           但目录 path 带尾部斜杠（如 knowledge/），导致映射失败，
--           所有复制出的节点 parent_id 都变成了 NULL。
--
-- 修复策略：根据 path 字段重建 parent_id 关系
--   - 目录节点：从 path 推导父目录 path，查找同版本同 skill 的父目录 ID
--   - 文件节点：从 path 推导所在目录 path，查找同版本同 skill 的目录 ID
-- ═══════════════════════════════════════════════════════════

SET search_path TO paas_ai;

-- 1. 修复子目录的 parent_id（depth > 0 的目录）
-- 例如 knowledge/industries/ 的父目录是 knowledge/
UPDATE ai_skill_resource AS child
SET parent_id = parent.id
FROM ai_skill_resource AS parent
WHERE child.node_type = 'dir'
  AND child.depth > 0
  AND child.parent_id IS NULL
  AND child.delete_flg = 0
  AND parent.node_type = 'dir'
  AND parent.delete_flg = 0
  AND parent.skill_api_key = child.skill_api_key
  AND parent.tenant_id = child.tenant_id
  AND parent.version = child.version
  -- 父目录 path = 子目录 path 去掉最后一段
  -- 例如 child.path = 'knowledge/industries/' → parent.path = 'knowledge/'
  AND parent.path = regexp_replace(child.path, '[^/]+/$', '');

-- 2. 修复文件的 parent_id
-- 例如 knowledge/industries/_index.md 的父目录是 knowledge/industries/
UPDATE ai_skill_resource AS child
SET parent_id = parent.id
FROM ai_skill_resource AS parent
WHERE child.node_type = 'file'
  AND child.parent_id IS NULL
  AND child.delete_flg = 0
  AND child.path LIKE '%/%'  -- 排除根级文件
  AND parent.node_type = 'dir'
  AND parent.delete_flg = 0
  AND parent.skill_api_key = child.skill_api_key
  AND parent.tenant_id = child.tenant_id
  AND parent.version = child.version
  -- 父目录 path = 文件 path 去掉文件名部分
  -- 例如 child.path = 'knowledge/industries/_index.md' → parent.path = 'knowledge/industries/'
  AND parent.path = regexp_replace(child.path, '[^/]+$', '');

-- 3. 验证修复结果
SELECT version, 
       COUNT(*) AS total,
       COUNT(*) FILTER (WHERE parent_id IS NULL AND depth > 0) AS orphan_dirs,
       COUNT(*) FILTER (WHERE parent_id IS NULL AND node_type = 'file' AND path LIKE '%/%') AS orphan_files
FROM ai_skill_resource
WHERE delete_flg = 0
GROUP BY version
ORDER BY version;
