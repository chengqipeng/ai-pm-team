-- ═══════════════════════════════════════════════════════════
-- 为 accountInsight Skill 配置资源预加载规则
-- 
-- 解决问题：fork 模式子 Agent 需要多轮推理才能逐个加载知识文件，
-- 通过预加载机制在子 Agent 启动前批量注入基础知识，减少 1-2 轮推理循环。
-- ═══════════════════════════════════════════════════════════

SET search_path TO paas_ai;

-- 更新 accountInsight 的 ext_info，添加 preload_resources 配置
UPDATE ai_skill_definition
SET ext_info = jsonb_set(
    COALESCE(ext_info::jsonb, '{}'::jsonb),
    '{preload_resources}',
    '{
      "always": ["knowledge/industries/_index.md"],
      "scene_map": {
        "新客开拓|新客|开拓|了解客户|客户背景": [
          "knowledge/analysis-strategies/business-model-patterns.md",
          "knowledge/analysis-strategies/signal-patterns.md"
        ],
        "续约|续费|流失|健康度|续约评审|续约风险": [
          "knowledge/analysis-strategies/risk-scoring-models.md",
          "knowledge/analysis-strategies/signal-patterns.md"
        ],
        "商机|推进|赢单|竞争|商机推进": [
          "knowledge/analysis-strategies/value-proposition-frameworks.md",
          "knowledge/competitor-playbooks/incumbent-replacement.md"
        ],
        "巡检|定时|变更|客户动态": [
          "knowledge/analysis-strategies/signal-patterns.md"
        ]
      },
      "max_preload": 4
    }'::jsonb
)::text,
    updated_at = EXTRACT(EPOCH FROM NOW()) * 1000
WHERE api_key = 'accountInsight'
  AND tenant_id = 0
  AND delete_flg = 0;

-- 验证更新结果
SELECT api_key, 
       (ext_info::jsonb -> 'preload_resources' -> 'always') AS preload_always,
       jsonb_object_keys(ext_info::jsonb -> 'preload_resources' -> 'scene_map') AS scene_keys
FROM ai_skill_definition
WHERE api_key = 'accountInsight' AND tenant_id = 0 AND delete_flg = 0;
