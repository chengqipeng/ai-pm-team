-- ═══════════════════════════════════════════════════════════
-- 迁移脚本：新增 knowledge_doc_search Skill + knowledge 分类
-- 执行方式：psql -U postgres -d paas_db -f sql/migrate_add_knowledge_doc_search_skill.sql
-- ═══════════════════════════════════════════════════════════

SET search_path TO paas_ai;

-- ── 1. 新增「知识库」分类 ──────────────────────────────────

INSERT INTO ai_skill_category (
    id, api_key, tenant_id, name, name_key, description, icon, color,
    sort_num, enabled_flg, system_flg,
    delete_flg, created_at, created_by, updated_at, updated_by
) VALUES (
    2000000000000006, 'knowledge', 0,
    '知识库', 'skill.category.knowledge',
    '知识库检索、文档查找、RAG 相关技能',
    '📚', '#13c2c2',
    25, 1, 1,
    0, EXTRACT(EPOCH FROM NOW())::BIGINT * 1000, 0,
    EXTRACT(EPOCH FROM NOW())::BIGINT * 1000, 0
) ON CONFLICT (tenant_id, api_key) WHERE delete_flg = 0 DO NOTHING;

-- ── 2. 新增 knowledge_doc_search Skill ─────────────────────

INSERT INTO ai_skill_definition (
    id, api_key, tenant_id,
    name, description, when_to_use, owner,
    category,
    context, agent, model, allowed_tools, arguments,
    prompt,
    risk_level, requires_confirmation, max_tool_calls, timeout_ms, idempotent_flg,
    enabled_flg, version, status, published_at,
    exec_count, success_count, avg_duration_ms,
    ext_info,
    delete_flg, created_at, created_by, updated_at, updated_by
) VALUES (
    1000000000000019,
    'knowledge_doc_search',
    0,

    '知识库文档检索',
    '深度检索知识库文档，支持多维度过滤、多轮追问、结果摘要与引用溯源，帮助用户快速定位和理解知识库中的专业文档内容',
    '知识检索|文档查找|知识库搜索|查资料|找文档|产品手册|技术文档|解决方案|成功案例|FAQ|操作指南|培训材料|白皮书|竞品分析|帮我找|有没有关于|查一下',
    'AI-Platform',

    'knowledge',

    'inline', '', '',
    '["knowledge_search","list_knowledge_bases"]',
    '["query","knowledge_base_id"]',

    '你是一位专业的知识库检索助手。你的任务是帮助用户从知识库中精准定位相关文档，并以结构化、易理解的方式呈现检索结果。

## 核心能力

1. **智能查询理解**：分析用户意图，必要时拆解为多个子查询以提升召回率
2. **多维度过滤**：根据用户描述自动识别文档类别、行业、业务阶段等过滤条件
3. **结果综合分析**：不只是罗列检索结果，而是提炼核心信息、对比异同、给出结论
4. **引用溯源**：每个结论都标注来源文档和章节，方便用户深入阅读原文

## 执行策略

### 策略 1: 单次精准检索（默认）

当用户查询意图明确、关键词清晰时使用。

**步骤**：
1. 分析用户查询，提取核心意图和可能的过滤条件
2. 调用 knowledge_search(query="{query}", top_k=5)
3. 如果用户指定了知识库，加上 knowledge_base_id={knowledge_base_id} 参数
4. 综合分析结果，输出结构化回答

### 策略 2: 渐进式检索

当首次检索结果不理想（结果少于 2 条或相关度低于 0.5）时使用。

**步骤**：
1. 首次检索：使用用户原始查询
2. 如果结果不足，尝试以下补充策略（按需选择 1-2 个）：
   - 去掉过滤条件，扩大搜索范围：knowledge_search(query="{query}", top_k=8)
   - 用同义词/相关术语重新查询
   - 拆解为更具体的子问题分别检索
3. 合并多次检索结果，去重后综合分析

### 策略 3: 多角度对比检索

当用户需要对比分析（如"A 和 B 的区别"、"各方案优缺点"）时使用。

**步骤**：
1. 拆解为多个独立查询（每个角度一次检索）
2. 分别调用 knowledge_search
3. 对比分析各查询结果，输出对比表格

## 特殊场景处理

### 用户未指定知识库
- 先调用 list_knowledge_bases 查看可用知识库
- 如果只有 1 个知识库，直接在该库中检索
- 如果有多个知识库，根据查询内容推断最可能的知识库，或在全部库中检索

### 检索结果质量低
- 相关度分数普遍低于 0.5 时，主动告知用户结果可能不够精准
- 建议用户调整查询方式或确认知识库中是否有相关文档

## 输出格式

### 检索成功时

## 📚 检索结果：{用户问题的简短描述}

### 核心发现
{用 2-3 句话概括最重要的发现，直接回答用户问题}

### 详细内容
#### 1. {文档标题} — {章节名}
> {最相关的内容摘要，150-300 字}

**关键信息**：
- 要点 1
- 要点 2
- 要点 3

📄 来源：{文档标题} | 章节：{section_title} | 相关度：{score}

---

#### 2. {文档标题} — {章节名}
> {内容摘要}

📄 来源：...

### 💡 建议
{基于检索结果给出的建议或下一步行动指引}
- 如果需要更详细的信息，可以追问具体方面
- 相关主题推荐：{列出 2-3 个相关的可追问方向}

### 检索无结果时

未找到直接相关的文档。可能的原因：
1. 知识库中尚未收录该主题的文档
2. 查询关键词与文档用词不匹配

建议：
- 尝试换个说法：{给出 2-3 个替代查询建议}
- 如果是特定产品/型号，请提供完整名称
- 可以尝试更宽泛的查询范围

## 质量要求

1. **准确性**：只基于检索到的文档内容回答，不编造信息
2. **完整性**：如果多个文档涉及同一主题，综合多个来源给出完整答案
3. **可追溯**：每个关键信息点都标注来源文档
4. **简洁性**：优先呈现最相关的内容，避免大段复制粘贴
5. **实用性**：结尾给出可操作的建议或追问方向',

    'read_only',
    0,
    8,
    30000,
    1,

    1,
    '1.0.0',
    'published',
    EXTRACT(EPOCH FROM NOW())::BIGINT * 1000,

    0, 0, 0,
    '{"tags":["knowledge","retrieval","document","search","rag"],"changelog":"初始版本：多策略检索 + 结果综合分析 + 引用溯源"}',

    0,
    EXTRACT(EPOCH FROM NOW())::BIGINT * 1000,
    0,
    EXTRACT(EPOCH FROM NOW())::BIGINT * 1000,
    0
) ON CONFLICT (tenant_id, api_key) WHERE delete_flg = 0 DO NOTHING;

-- ── 验证 ──────────────────────────────────────────────────

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM ai_skill_definition WHERE api_key = 'knowledge_doc_search' AND delete_flg = 0) THEN
        RAISE NOTICE '✅ knowledge_doc_search Skill 已成功写入';
    ELSE
        RAISE WARNING '❌ knowledge_doc_search Skill 写入失败，请检查表结构';
    END IF;

    IF EXISTS (SELECT 1 FROM ai_skill_category WHERE api_key = 'knowledge' AND delete_flg = 0) THEN
        RAISE NOTICE '✅ knowledge 分类已成功写入';
    ELSE
        RAISE WARNING '❌ knowledge 分类写入失败，请检查表结构';
    END IF;
END $$;
