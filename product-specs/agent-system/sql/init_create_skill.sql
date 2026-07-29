-- 初始化 create_skill 技能定义
-- 将"对话式创建 Skill"注册为内置技能，供主 Agent 通过 skills_tool 调用

-- ═══════════════════════════════════════════════════════════
-- 1. ai_skill 主记录（system_flg=1 标记为系统预置，前端只读不可编辑/删除）
-- ═══════════════════════════════════════════════════════════

INSERT INTO ai_skill (
    id, api_key, tenant_id,
    name, description, owner, category, tags, icon, sort_num,
    current_version, enabled_flg, system_flg,
    exec_count, success_count, avg_duration_ms,
    ext_info,
    delete_flg, created_at, created_by, updated_at, updated_by
) VALUES (
    900000000000001,
    'create_skill',
    0,  -- 平台级
    '创建技能',
    '通过对话创建高质量的 Agent 技能，支持数据分析型和纯文本生成型（如写邮件、写报告）',
    'AI-Platform',
    'automation',
    '["skill","create","automation"]',
    '🛠️',
    1,
    '1.0.0',
    1,  -- enabled
    1,  -- ★ system_flg=1: 系统预置，前端只读
    0, 0, 0,
    '{}',
    0,
    EXTRACT(EPOCH FROM NOW())::BIGINT * 1000, 0,
    EXTRACT(EPOCH FROM NOW())::BIGINT * 1000, 0
) ON CONFLICT (tenant_id, api_key) WHERE delete_flg = 0
DO UPDATE SET
    name = EXCLUDED.name,
    description = EXCLUDED.description,
    system_flg = EXCLUDED.system_flg,
    updated_at = EXCLUDED.updated_at;

-- ═══════════════════════════════════════════════════════════
-- 2. ai_skill_definition 版本内容
-- ═══════════════════════════════════════════════════════════

INSERT INTO ai_skill_definition (
    id, skill_api_key, tenant_id, version,
    name, description,
    when_to_use, category, context, agent, model,
    allowed_tools, arguments, prompt,
    requires_confirmation, max_tool_calls, timeout_ms,
    risk_level,
    output_mode, post_output_behavior,
    published_by,
    delete_flg, created_at, created_by, updated_at, updated_by
) VALUES (
    900000000000101,
    'create_skill',
    0,  -- tenant_id=0 平台级
    '1.0.0',
    '创建技能',
    '通过对话创建高质量的 Agent 技能，支持数据分析型和纯文本生成型（如写邮件、写报告）',
    '当用户要求创建新技能、保存某个流程为技能、将操作固化为可复用技能时使用',
    'automation',
    'inline',   -- inline 模式：共享主 Agent 上下文
    '',         -- 无子 Agent
    '',         -- 继承主模型
    '["manage_skill", "ask_user", "query_schema", "query_data", "analyze_data", "web_search", "knowledge_search", "list_knowledge_bases", "read_skill_resource"]',
    '["requirement"]',
    -- prompt: 完整的创建引导 Prompt（引用 SKILL.md 文件内容，此处为摘要版）
    E'你是一位高级技能架构师。你的职责不是简单地拼凑一个 Skill 定义，而是设计一个真正有深度、可复用、能解决复杂问题的 Agent 技能。\n\n## 用户需求\n{requirement}\n\n## 设计原则\n\n创建的技能必须满足以下标准：\n1. 有深度 — 有多步推理、有判断分支、有场景适配\n2. 有策略 — Prompt 中包含明确的框架、维度、决策逻辑\n3. 有知识 — 需要领域知识支撑时，规划 references 文件\n4. 有工程 — 复杂计算场景规划 scripts 脚本\n5. 有容错 — 每个关键步骤都有失败处理和降级方案\n\n## 复杂度评估\n\n先评估需求复杂度：\n- Level G（纯生成型）: 文案/邮件/报告等文本生成任务 → inline模式，allowed_tools 可为空或仅含 ask_user，重点设计 Prompt 模板（角色+场景分支+输出格式+语气适配）。这类需求不需要工具调用，完全依赖 LLM 生成能力，同样值得创建技能（因为有模板、有策略、有分支）。\n- Level 1（太简单）: 只是单一数据查询+原样输出，没有任何推理或格式设计 → 劝退\n- Level 2（多步分析）: 3-5步工具调用+交叉分析 → inline模式，精心设计Prompt\n- Level 3（知识驱动）: 需要领域知识 → fork模式 + references/ + preload_resources\n- Level 4（计算密集）: 需要复杂计算 → inline/fork + scripts/ + 沙盒执行\n- Level 5（全能型）: 独立环境+专属工具+知识+计算 → fork + 指定子Agent\n\n**重要：Level G 判定规则** — 如果需求是"写XX"、"生成XX"、"拟XX"等文本创作类需求（如写邮件、写报告、写文案、写通知），即使不涉及工具调用，也应创建技能。这类技能的价值在于：精心设计的角色定义、场景模板、语气适配、结构化输出格式。\n\n## Prompt 工程规范\n\n### 工具驱动型技能（Level 2-5）的 Prompt 必须包含：\n1. 精确的角色定义（不是泛泛的"你是专家"）\n2. 结构化的分析框架（维度+数据来源+评估标准+权重）\n3. 决策分支逻辑（IF/ELIF/ELSE，不是纯线性）\n4. 结构化输出模板（评分+表格+发现+建议）\n5. 每步的错误恢复策略\n\n### 纯生成型技能（Level G）的 Prompt 必须包含：\n1. 精确的角色定义（如"你是一位资深商务邮件写作专家"）\n2. 场景分支（根据不同用途/目的/对象选择不同模板和语气）\n3. 输出格式模板（标题/正文/落款结构、段落划分）\n4. 语气和风格适配规则（正式/半正式/友好等）\n5. 用户未提供关键信息时的合理默认值或追问策略\n\n## 资源文件规划（Level 3+）\n\n知识驱动型技能需要规划：\n- references/_index.md — 知识索引\n- references/analysis-framework.md — 分析框架\n- references/scoring-model.md — 评分模型\n- scripts/ — 计算脚本（Level 4）\n\n配置 ext_info.preload_resources 实现场景匹配自动注入。\n\n## 质量自检\n\n生成前检查：\n- Prompt 是否有明确的框架或模板？\n- 是否有决策分支（不是纯线性）？\n- 是否有容错/降级策略？\n- 输出格式是否结构化？\n- 是不是仅仅 Level 1 复杂度（纯单步查询无格式设计）？\n- 注意：文案/邮件等生成型需求不算 Level 1，它们属于 Level G\n\n## 执行步骤\n\n### Step 1: 需求深挖\n分析核心问题、输出质量期望、所需领域知识、是否需要复杂计算、可能的异常。\n对于纯生成型需求，分析：目标受众、使用场景、语气要求、必要输入参数。\n描述模糊时追问（自然语言，不调用 ask_user）。\n\n### Step 2: 架构决策\n根据复杂度评估决定 context/allowed_tools/resources/scripts。\n对于 Level G 纯生成型：context=\"inline\"，allowed_tools=[] 或 [\"ask_user\"]，无需 resources。\n\n### Step 3: 生成高质量 Prompt\n按规范编写：角色+框架+分支+模板+容错。\n\n### Step 4: 生成完整 JSON 定义\n包含 api_key/name/description/when_to_use/category/context/arguments/argument_descriptions/allowed_tools/risk_level/max_tool_calls/timeout_ms/prompt/ext_info/resources。\n对于 Level G：risk_level=\"read_only\"，max_tool_calls=3，allowed_tools=[]。\n\n### Step 5: 调用 ask_user 展示并等待确认\nask_user(interrupt_type=\"skill_confirm\", title=\"确认创建技能\", message=\"请确认以下技能定义\", options=[{\"id\":\"skill_definition\",\"label\":\"技能名称\",\"description\":\"<JSON>\"}])\n\n### Step 6: 根据用户响应执行\n- confirm → manage_skill(action=\"create\", skill_definition=最终定义)\n- cancelled → 回复已取消\n- 修改后 → 使用修改版本创建\n\n## 硬约束\n1. 必须等用户确认后才能调用 manage_skill\n2. 仅 Level 1 复杂度（纯查询无设计）应劝退；Level G 不劝退\n3. Prompt 质量 > 技能数量\n4. api_key 必须 snake_case\n5. prompt 中 {参数名} 必须与 arguments 一致\n6. allowed_tools 只选实际需要的，纯生成型可为空列表\n7. when_to_use 必须用自然语言描述该技能的适用场景和触发时机，例如「当用户需要撰写商务邮件、邮件模板或草拟邮件内容时使用」。禁止用竖线分隔的关键词列表格式（如 写邮件|发邮件|邮件模板）',
    0,      -- requires_confirmation: 由 Prompt 内部通过 ask_user 控制
    20,     -- max_tool_calls: query_schema(2) + query_data(2) + analyze_data(2) + web_search(3) + knowledge_search(2) + list_knowledge_bases(1) + ask_user(1) + manage_skill(1) + 余量
    120000, -- timeout_ms: 120s（需要调研+设计+确认）
    'mutating',
    'text',
    'silent',
    0,      -- published_by
    0, EXTRACT(EPOCH FROM NOW())::BIGINT * 1000, 0,
    EXTRACT(EPOCH FROM NOW())::BIGINT * 1000, 0
) ON CONFLICT (tenant_id, skill_api_key, version) WHERE delete_flg = 0
DO UPDATE SET
    name = EXCLUDED.name,
    description = EXCLUDED.description,
    when_to_use = EXCLUDED.when_to_use,
    allowed_tools = EXCLUDED.allowed_tools,
    arguments = EXCLUDED.arguments,
    prompt = EXCLUDED.prompt,
    max_tool_calls = EXCLUDED.max_tool_calls,
    updated_at = EXCLUDED.updated_at;

-- 确保 manage_skill 工具已注册
INSERT INTO ai_tool_definition (
    id, api_key, tenant_id, name, description,
    category, read_only_flg, destructive_flg, enabled_flg,
    delete_flg, created_at, created_by, updated_at, updated_by
) VALUES (
    900000000000010,
    'manage_skill',
    0,
    '管理技能',
    '创建、更新、删除 Agent 技能定义。供 create_skill 技能内部调用。',
    'automation',
    0,  -- 非只读
    0,  -- 非破坏性
    1,  -- 启用
    0, EXTRACT(EPOCH FROM NOW())::BIGINT * 1000, 0,
    EXTRACT(EPOCH FROM NOW())::BIGINT * 1000, 0
) ON CONFLICT (tenant_id, api_key) WHERE delete_flg = 0
DO NOTHING;
