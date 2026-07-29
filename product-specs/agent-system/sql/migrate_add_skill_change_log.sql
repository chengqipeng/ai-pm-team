-- ═══════════════════════════════════════════════════════════
-- Skill 变更日志表 — 记录技能定义的每次修改操作
-- 用途：审计追溯、回滚参考、变更历史查看
-- ═══════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS ai_skill_change_log (
    id                BIGINT        PRIMARY KEY,
    tenant_id         BIGINT        NOT NULL DEFAULT 0,
    skill_api_key     VARCHAR(100)  NOT NULL,

    -- 变更操作信息
    action            VARCHAR(30)   NOT NULL,          -- create_version / switch_version / delete_version / create / delete
    from_version      VARCHAR(30)   DEFAULT '',        -- 变更前版本号（create 时为空）
    to_version        VARCHAR(30)   DEFAULT '',        -- 变更后版本号（delete 时为空）
    changelog         TEXT          DEFAULT '',        -- 变更说明（用户可读）

    -- 变更内容摘要
    change_summary    TEXT          DEFAULT '',        -- 变更摘要（如"修改提示词、新增 web_search 工具"）
    change_detail     TEXT          DEFAULT '{}',     -- 变更详情 JSON（字段级 diff）
    analysis_report   TEXT          DEFAULT '',        -- 深度分析报告摘要（update_skill 生成的对比分析）

    -- 操作上下文
    trigger_source    VARCHAR(30)   DEFAULT 'chat',   -- 触发来源：chat（对话）/ api（REST API）/ auto（自动优化）
    thread_id         VARCHAR(64)   DEFAULT '',        -- 对话线程 ID（可追溯到哪次对话触发的修改）
    operator_id       BIGINT        NOT NULL DEFAULT 0, -- 操作人 ID

    -- 回滚支持
    rollback_flg      SMALLINT      NOT NULL DEFAULT 0, -- 1=此记录是回滚操作
    rollback_from_log BIGINT        DEFAULT NULL,       -- 回滚时指向被回滚的 change_log ID

    -- BaseEntity
    delete_flg        SMALLINT      NOT NULL DEFAULT 0,
    created_at        BIGINT        NOT NULL,
    created_by        BIGINT        NOT NULL DEFAULT 0,
    updated_at        BIGINT        NOT NULL,
    updated_by        BIGINT        NOT NULL DEFAULT 0
);

-- 按技能查询变更历史（最常用）
CREATE INDEX IF NOT EXISTS idx_skill_change_log_skill
    ON ai_skill_change_log(tenant_id, skill_api_key, created_at DESC)
    WHERE delete_flg = 0;

-- 按操作人查询
CREATE INDEX IF NOT EXISTS idx_skill_change_log_operator
    ON ai_skill_change_log(tenant_id, operator_id, created_at DESC)
    WHERE delete_flg = 0;

-- 按对话线程查询
CREATE INDEX IF NOT EXISTS idx_skill_change_log_thread
    ON ai_skill_change_log(thread_id)
    WHERE thread_id != '' AND delete_flg = 0;
