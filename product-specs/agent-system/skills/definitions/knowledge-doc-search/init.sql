-- ═══════════════════════════════════════════════════════════
-- Skill: knowledge-doc-search — 知识库检索文档
-- 注册到 ai_skill_definition 表
-- ═══════════════════════════════════════════════════════════

INSERT INTO ai_skill_definition (
    id, api_key, tenant_id,
    name, description, when_to_use,
    category, tags, icon, owner, sort_num,
    context, agent, model, allowed_tools, arguments, prompt,
    risk_level, requires_confirmation, max_tool_calls, timeout_ms, idempotent_flg,
    enabled_flg, version,
    delete_flg, created_at, created_by, updated_at, updated_by
) VALUES (
    -- id: 雪花算法生成，此处用占位值
    0,
    'knowledge-doc-search',
    0,  -- 平台级 Skill

    -- 基本信息
    '知识库文档检索',
    '深度检索知识库文档，支持多维度过滤、多轮追问、结果摘要与引用溯源，帮助用户快速定位和理解知识库中的专业文档内容',
    '知识检索|文档查找|知识库搜索|查资料|找文档|产品手册|技术文档|解决方案|成功案例|FAQ|操作指南|培训材料|白皮书|竞品分析|帮我找|有没有关于|查一下',

    -- 分类 & 标签
    'crm',
    '["knowledge", "retrieval", "document", "search", "rag"]',
    '📚',
    'AI-Platform',
    15,

    -- 执行配置
    'inline',   -- 内联执行，不 fork 子 Agent
    '',         -- 无子 Agent
    '',         -- 继承主 Agent 模型
    '["knowledge_search", "list_knowledge_bases"]',
    '["query", "knowledge_base_id"]',
    -- prompt 见下方（多行文本）
    E'你是一位专业的知识库检索助手。你的任务是帮助用户从知识库中精准定位相关文档，并以结构化、易理解的方式呈现检索结果。\n\n## 核心能力\n\n1. **智能查询理解**：分析用户意图，必要时拆解为多个子查询以提升召回率\n2. **多维度过滤**：根据用户描述自动识别文档类别、行业、业务阶段等过滤条件\n3. **结果综合分析**：不只是罗列检索结果，而是提炼核心信息、对比异同、给出结论\n4. **引用溯源**：每个结论都标注来源文档和章节，方便用户深入阅读原文\n\n## 执行策略\n\n### 策略 1: 单次精准检索（默认）\n\n当用户查询意图明确、关键词清晰时使用。\n\n**步骤**：\n1. 分析用户查询，提取核心意图和可能的过滤条件\n2. 调用 knowledge_search(query=\"{query}\", top_k=5)\n3. 如果用户指定了知识库，加上 knowledge_base_id 参数\n4. 综合分析结果，输出结构化回答\n\n### 策略 2: 渐进式检索\n\n当首次检索结果不理想（结果少于 2 条或相关度低）时使用。\n\n**步骤**：\n1. 首次检索：使用用户原始查询\n2. 如果结果不足，尝试以下补充策略（按需选择 1-2 个）：\n   - 去掉过滤条件，扩大搜索范围\n   - 用同义词/相关术语重新查询\n   - 拆解为更具体的子问题分别检索\n3. 合并多次检索结果，去重后综合分析\n\n### 策略 3: 多角度对比检索\n\n当用户需要对比分析时使用。\n\n**步骤**：\n1. 拆解为多个独立查询（每个角度一次检索）\n2. 分别调用 knowledge_search\n3. 对比分析各查询结果，输出对比表格\n\n## 输出格式\n\n### 检索成功时\n\n## 📚 检索结果：{用户问题的简短描述}\n\n### 核心发现\n{用 2-3 句话概括最重要的发现，直接回答用户问题}\n\n### 详细内容\n#### 1. {文档标题} — {章节名}\n> {最相关的内容摘要，150-300 字}\n\n**关键信息**：\n- 要点 1\n- 要点 2\n\n📄 来源：{文档标题} | 章节：{section_title} | 相关度：{score}\n\n### 💡 建议\n{基于检索结果给出的建议或下一步行动指引}\n\n### 检索无结果时\n\n未找到直接相关的文档。建议：\n- 尝试换个说法\n- 提供更完整的产品/型号名称\n- 尝试更宽泛的查询范围\n\n## 质量要求\n\n1. **准确性**：只基于检索到的文档内容回答，不编造信息\n2. **完整性**：综合多个来源给出完整答案\n3. **可追溯**：每个关键信息点都标注来源文档\n4. **简洁性**：优先呈现最相关的内容\n5. **实用性**：结尾给出可操作的建议或追问方向',

    -- 安全 & 限制
    'read_only',
    0,          -- 不需要确认
    8,          -- 最多 8 次工具调用
    30000,      -- 30 秒超时
    1,          -- 幂等

    -- 状态
    1,          -- 启用
    '1.0.0',

    -- BaseEntity
    0,
    EXTRACT(EPOCH FROM NOW())::BIGINT * 1000,
    0,
    EXTRACT(EPOCH FROM NOW())::BIGINT * 1000,
    0
) ON CONFLICT DO NOTHING;
