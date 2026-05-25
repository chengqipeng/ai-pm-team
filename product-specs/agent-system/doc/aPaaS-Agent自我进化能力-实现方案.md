# aPaaS Agent 自我进化能力 — 实现方案

> 基于 Hermes Agent 的设计范式，结合 aPaaS 平台技术栈（Spring Boot + React + PostgreSQL），给出可落地的 Memory + Skills 自我进化实现方案。

---

## 一、整体技术架构

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         前端（React 19 + Antd 6）                        │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────────────┐  │
│  │ Agent 对话面板 │  │ Skills 管理  │  │ Memory 可视化                 │  │
│  └──────┬───────┘  └──────┬───────┘  └──────────────┬───────────────┘  │
└─────────┼──────────────────┼─────────────────────────┼──────────────────┘
          │                  │                         │
          ▼                  ▼                         ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                    BFF 层（接口代理 + 会话管理）                           │
└─────────────────────────────────────────────────────────────────────────┘
          │
          ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                    paas-agent-service（新微服务）                          │
│                                                                          │
│  ┌──────────────────────────────────────────────────────────────────┐   │
│  │                    Agent 核心循环                                  │   │
│  │  ┌────────────┐  ┌────────────┐  ┌────────────┐  ┌───────────┐  │   │
│  │  │ Prompt     │  │ LLM        │  │ Tool       │  │ Memory    │  │   │
│  │  │ Builder    │  │ Provider   │  │ Executor   │  │ Manager   │  │   │
│  │  └────────────┘  └────────────┘  └────────────┘  └───────────┘  │   │
│  └──────────────────────────────────────────────────────────────────┘   │
│                                                                          │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────────────┐   │
│  │ Memory Store │  │ Skill Store  │  │ Session Store                 │   │
│  └──────────────┘  └──────────────┘  └──────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────┘
          │
          ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                    PostgreSQL（paas_agent schema）                        │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌───────────┐  │
│  │ p_agent_     │  │ p_agent_     │  │ p_agent_     │  │ p_agent_  │  │
│  │ memory       │  │ skill        │  │ session      │  │ skill_    │  │
│  │              │  │              │  │              │  │ usage     │  │
│  └──────────────┘  └──────────────┘  └──────────────┘  └───────────┘  │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## 二、数据库设计

### 2.1 Memory 表

```sql
-- Agent 记忆存储（有界策展式）
CREATE TABLE p_agent_memory (
    id              BIGINT PRIMARY KEY,
    tenant_id       BIGINT NOT NULL,
    user_id         BIGINT NOT NULL,
    target          VARCHAR(20) NOT NULL,       -- 'memory' | 'user_profile'
    entries         TEXT NOT NULL DEFAULT '',    -- §分隔的条目文本
    char_limit      INT NOT NULL DEFAULT 2200,
    snapshot_hash   VARCHAR(64),                -- 快照哈希，用于检测变更
    delete_flg      SMALLINT NOT NULL DEFAULT 0,
    created_at      BIGINT NOT NULL,
    created_by      BIGINT NOT NULL,
    updated_at      BIGINT NOT NULL,
    updated_by      BIGINT NOT NULL
);

-- 唯一约束：每个用户每个 target 只有一条记录
CREATE UNIQUE INDEX uk_agent_memory_user_target
    ON p_agent_memory(tenant_id, user_id, target)
    WHERE delete_flg = 0;
```


### 2.2 Skill 表

```sql
-- Agent 技能存储（程序性记忆）
CREATE TABLE p_agent_skill (
    id              BIGINT PRIMARY KEY,
    tenant_id       BIGINT NOT NULL,
    name            VARCHAR(64) NOT NULL,       -- 技能名称（小写+连字符）
    category        VARCHAR(64),                -- 分类
    description     VARCHAR(1024) NOT NULL,     -- 简短描述
    content         TEXT NOT NULL,              -- 完整 SKILL.md 内容
    version         VARCHAR(20) DEFAULT '1.0.0',
    scope           VARCHAR(20) NOT NULL DEFAULT 'tenant',  -- 'global'|'tenant'|'user'
    created_by_agent SMALLINT NOT NULL DEFAULT 0,  -- 1=Agent创建, 0=人工创建
    pinned_flg      SMALLINT NOT NULL DEFAULT 0,
    state           VARCHAR(20) NOT NULL DEFAULT 'active',  -- active|stale|archived
    tags            VARCHAR(512),               -- JSON array of tags
    platforms       VARCHAR(256),               -- JSON array of platforms
    delete_flg      SMALLINT NOT NULL DEFAULT 0,
    created_at      BIGINT NOT NULL,
    created_by      BIGINT NOT NULL,
    updated_at      BIGINT NOT NULL,
    updated_by      BIGINT NOT NULL
);

CREATE UNIQUE INDEX uk_agent_skill_name
    ON p_agent_skill(tenant_id, name)
    WHERE delete_flg = 0;

CREATE INDEX idx_agent_skill_category
    ON p_agent_skill(tenant_id, category, state);
```

### 2.3 Skill 支撑文件表

```sql
-- Skill 的参考文件/模板/脚本
CREATE TABLE p_agent_skill_file (
    id              BIGINT PRIMARY KEY,
    skill_id        BIGINT NOT NULL,
    file_path       VARCHAR(256) NOT NULL,      -- 'references/api.md'
    file_content    TEXT NOT NULL,
    file_type       VARCHAR(20),                -- 'reference'|'template'|'script'
    delete_flg      SMALLINT NOT NULL DEFAULT 0,
    created_at      BIGINT NOT NULL,
    created_by      BIGINT NOT NULL,
    updated_at      BIGINT NOT NULL,
    updated_by      BIGINT NOT NULL
);

CREATE UNIQUE INDEX uk_skill_file_path
    ON p_agent_skill_file(skill_id, file_path)
    WHERE delete_flg = 0;
```

### 2.4 Skill 使用遥测表

```sql
-- Skill 使用追踪（Curator 决策依据）
CREATE TABLE p_agent_skill_usage (
    id              BIGINT PRIMARY KEY,
    skill_id        BIGINT NOT NULL,
    tenant_id       BIGINT NOT NULL,
    use_count       INT NOT NULL DEFAULT 0,
    view_count      INT NOT NULL DEFAULT 0,
    patch_count     INT NOT NULL DEFAULT 0,
    last_used_at    BIGINT,
    last_viewed_at  BIGINT,
    last_patched_at BIGINT,
    created_at      BIGINT NOT NULL,
    created_by      BIGINT NOT NULL,
    updated_at      BIGINT NOT NULL,
    updated_by      BIGINT NOT NULL
);

CREATE UNIQUE INDEX uk_skill_usage
    ON p_agent_skill_usage(skill_id, tenant_id);
```

### 2.5 会话存储表

```sql
-- Agent 对话会话
CREATE TABLE p_agent_session (
    id              BIGINT PRIMARY KEY,
    tenant_id       BIGINT NOT NULL,
    user_id         BIGINT NOT NULL,
    session_key     VARCHAR(64) NOT NULL,       -- UUID
    title           VARCHAR(256),
    messages        TEXT,                       -- JSON array of messages
    tool_call_count INT NOT NULL DEFAULT 0,
    state           VARCHAR(20) DEFAULT 'active',
    parent_session_id BIGINT,                  -- 压缩后的父会话
    delete_flg      SMALLINT NOT NULL DEFAULT 0,
    created_at      BIGINT NOT NULL,
    created_by      BIGINT NOT NULL,
    updated_at      BIGINT NOT NULL,
    updated_by      BIGINT NOT NULL
);

CREATE INDEX idx_agent_session_user
    ON p_agent_session(tenant_id, user_id, state);
```

---

## 三、Java 核心类设计

### 3.1 Memory 模块

```java
/**
 * Agent 记忆存储引擎 — 有界策展式
 * 
 * 设计要点：
 * 1. 有界：硬性字符限制，强制信息密度
 * 2. 策展式：Agent 自主决定 add/replace/remove
 * 3. 冻结快照：会话开始时捕获，中途不变
 * 4. 安全扫描：写入前检测注入模式
 */
@Service
public class AgentMemoryService {

    private static final String ENTRY_DELIMITER = "\n§\n";
    private static final int DEFAULT_MEMORY_LIMIT = 2200;
    private static final int DEFAULT_USER_PROFILE_LIMIT = 1375;

    @Autowired
    private AgentMemoryMapper memoryMapper;

    /**
     * 加载冻结快照 — 会话开始时调用一次
     */
    public MemorySnapshot loadSnapshot(Long tenantId, Long userId) {
        AgentMemory memory = memoryMapper.selectByUserAndTarget(
            tenantId, userId, "memory");
        AgentMemory userProfile = memoryMapper.selectByUserAndTarget(
            tenantId, userId, "user_profile");

        return MemorySnapshot.builder()
            .memoryBlock(renderBlock("memory", memory))
            .userProfileBlock(renderBlock("user_profile", userProfile))
            .build();
    }

    /**
     * 新增条目
     */
    public MemoryResult add(Long tenantId, Long userId, 
                            String target, String content) {
        // 1. 内容校验
        content = content.strip();
        if (content.isEmpty()) {
            return MemoryResult.error("内容不能为空");
        }

        // 2. 安全扫描
        String scanError = scanContent(content);
        if (scanError != null) {
            return MemoryResult.error(scanError);
        }

        // 3. 加载当前条目
        AgentMemory record = getOrCreate(tenantId, userId, target);
        List<String> entries = parseEntries(record.getEntries());
        int limit = getCharLimit(target);

        // 4. 去重检查
        if (entries.contains(content)) {
            return MemoryResult.success(entries, limit, "条目已存在，未重复添加");
        }

        // 5. 容量检查
        List<String> newEntries = new ArrayList<>(entries);
        newEntries.add(content);
        int newTotal = String.join(ENTRY_DELIMITER, newEntries).length();

        if (newTotal > limit) {
            int current = String.join(ENTRY_DELIMITER, entries).length();
            return MemoryResult.builder()
                .success(false)
                .error(String.format(
                    "记忆已使用 %d/%d 字符。新增条目（%d 字符）将超出限制。" +
                    "请先替换或删除现有条目。", current, limit, content.length()))
                .entries(entries)
                .usage(current + "/" + limit)
                .build();
        }

        // 6. 写入
        record.setEntries(String.join(ENTRY_DELIMITER, newEntries));
        memoryMapper.updateById(record);

        return MemoryResult.success(newEntries, limit, "条目已添加");
    }

    /**
     * 子串匹配替换
     */
    public MemoryResult replace(Long tenantId, Long userId,
                                String target, String oldText, String newContent) {
        // 1. 参数校验
        oldText = oldText.strip();
        newContent = newContent.strip();
        if (oldText.isEmpty() || newContent.isEmpty()) {
            return MemoryResult.error("old_text 和 content 不能为空");
        }

        // 2. 安全扫描新内容
        String scanError = scanContent(newContent);
        if (scanError != null) {
            return MemoryResult.error(scanError);
        }

        // 3. 子串匹配
        AgentMemory record = getOrCreate(tenantId, userId, target);
        List<String> entries = parseEntries(record.getEntries());

        List<Integer> matchIndices = new ArrayList<>();
        for (int i = 0; i < entries.size(); i++) {
            if (entries.get(i).contains(oldText)) {
                matchIndices.add(i);
            }
        }

        if (matchIndices.isEmpty()) {
            return MemoryResult.error("未找到匹配 '" + oldText + "' 的条目");
        }
        if (matchIndices.size() > 1) {
            // 检查是否全部相同（重复条目）
            Set<String> unique = matchIndices.stream()
                .map(entries::get).collect(Collectors.toSet());
            if (unique.size() > 1) {
                return MemoryResult.error(
                    "多个条目匹配 '" + oldText + "'，请提供更精确的子串");
            }
        }

        // 4. 容量检查
        int idx = matchIndices.get(0);
        List<String> testEntries = new ArrayList<>(entries);
        testEntries.set(idx, newContent);
        int newTotal = String.join(ENTRY_DELIMITER, testEntries).length();
        int limit = getCharLimit(target);

        if (newTotal > limit) {
            return MemoryResult.error(String.format(
                "替换后将达到 %d/%d 字符，请缩短新内容或先删除其他条目", 
                newTotal, limit));
        }

        // 5. 执行替换
        entries.set(idx, newContent);
        record.setEntries(String.join(ENTRY_DELIMITER, entries));
        memoryMapper.updateById(record);

        return MemoryResult.success(entries, limit, "条目已替换");
    }

    /**
     * 子串匹配删除
     */
    public MemoryResult remove(Long tenantId, Long userId,
                               String target, String oldText) {
        // 逻辑同 replace，但执行 entries.remove(idx)
        // ...
    }

    /**
     * 安全扫描 — 检测注入/泄露模式
     */
    private String scanContent(String content) {
        // 注入检测
        String lower = content.toLowerCase();
        if (lower.contains("ignore previous instructions") ||
            lower.contains("you are now") ||
            lower.contains("system prompt override") ||
            lower.contains("disregard your")) {
            return "内容包含疑似 prompt 注入模式，已拒绝写入";
        }

        // 敏感数据检测（aPaaS 特化）
        if (content.matches(".*tenant_id\\s*[=:]\\s*\\d+.*")) {
            return "内容包含跨租户标识，已拒绝写入";
        }
        if (content.matches(".*(?i)(password|secret|token)\\s*[=:]\\s*\\S+.*")) {
            return "内容包含敏感凭证，请勿存储密码/密钥到记忆中";
        }

        return null; // 通过
    }

    /**
     * 渲染 system prompt 注入块
     */
    private String renderBlock(String target, AgentMemory record) {
        if (record == null || record.getEntries().isEmpty()) {
            return "";
        }
        List<String> entries = parseEntries(record.getEntries());
        int limit = getCharLimit(target);
        int current = record.getEntries().length();
        int pct = Math.min(100, (current * 100) / limit);

        String header = target.equals("user_profile")
            ? String.format("用户画像 [%d%% — %d/%d 字符]", pct, current, limit)
            : String.format("Agent 记忆 [%d%% — %d/%d 字符]", pct, current, limit);

        String separator = "═".repeat(40);
        return separator + "\n" + header + "\n" + separator + "\n" 
               + String.join(ENTRY_DELIMITER, entries);
    }

    private List<String> parseEntries(String raw) {
        if (raw == null || raw.isBlank()) return new ArrayList<>();
        return Arrays.stream(raw.split(Pattern.quote(ENTRY_DELIMITER)))
            .map(String::strip)
            .filter(s -> !s.isEmpty())
            .collect(Collectors.toCollection(ArrayList::new));
    }

    private int getCharLimit(String target) {
        return "user_profile".equals(target) 
            ? DEFAULT_USER_PROFILE_LIMIT 
            : DEFAULT_MEMORY_LIMIT;
    }
}
```


### 3.2 Skills 模块

```java
/**
 * Agent 技能管理服务 — 程序性记忆的自动固化与持续改进
 */
@Service
public class AgentSkillService {

    private static final int MAX_CONTENT_CHARS = 100_000;
    private static final int MAX_NAME_LENGTH = 64;
    private static final int MAX_DESCRIPTION_LENGTH = 1024;
    private static final Pattern VALID_NAME = 
        Pattern.compile("^[a-z0-9][a-z0-9._-]*$");

    @Autowired
    private AgentSkillMapper skillMapper;
    @Autowired
    private AgentSkillFileMapper skillFileMapper;
    @Autowired
    private AgentSkillUsageMapper usageMapper;

    // ═══════════════════════════════════════════════════════════════
    // 创建 Skill
    // ═══════════════════════════════════════════════════════════════

    public SkillResult create(Long tenantId, SkillCreateRequest req) {
        // 1. 名称校验
        String nameError = validateName(req.getName());
        if (nameError != null) return SkillResult.error(nameError);

        // 2. 内容校验
        String contentError = validateContent(req.getContent());
        if (contentError != null) return SkillResult.error(contentError);

        // 3. 冲突检查
        AgentSkill existing = skillMapper.selectByName(tenantId, req.getName());
        if (existing != null) {
            return SkillResult.error("同名技能已存在: " + req.getName());
        }

        // 4. 解析 frontmatter
        SkillFrontmatter fm = parseFrontmatter(req.getContent());

        // 5. 写入数据库
        AgentSkill skill = new AgentSkill();
        skill.setTenantId(tenantId);
        skill.setName(req.getName());
        skill.setCategory(req.getCategory());
        skill.setDescription(fm.getDescription());
        skill.setContent(req.getContent());
        skill.setVersion(fm.getVersion());
        skill.setCreatedByAgent(req.isAgentCreated() ? 1 : 0);
        skill.setState("active");
        skill.setTags(JSON.toJSONString(fm.getTags()));
        skillMapper.insert(skill);

        // 6. 初始化使用记录
        initUsageRecord(skill.getId(), tenantId);

        return SkillResult.success("技能 '" + req.getName() + "' 已创建", skill);
    }

    // ═══════════════════════════════════════════════════════════════
    // Patch — 定向修改（首选改进方式）
    // ═══════════════════════════════════════════════════════════════

    public SkillResult patch(Long tenantId, String name, 
                             String oldString, String newString) {
        // 1. 查找 Skill
        AgentSkill skill = skillMapper.selectByName(tenantId, name);
        if (skill == null) {
            return SkillResult.error("技能 '" + name + "' 不存在");
        }

        // 2. 匹配检查
        String content = skill.getContent();
        int matchCount = countOccurrences(content, oldString);

        if (matchCount == 0) {
            // 尝试模糊匹配（忽略空白差异）
            String fuzzyResult = fuzzyReplace(content, oldString, newString);
            if (fuzzyResult == null) {
                return SkillResult.error(
                    "未找到匹配文本。请确认 old_string 在 SKILL 内容中存在。");
            }
            content = fuzzyResult;
            matchCount = 1;
        } else if (matchCount > 1) {
            return SkillResult.error(
                "找到 " + matchCount + " 处匹配，请提供更精确的上下文以唯一定位");
        } else {
            content = content.replace(oldString, newString);
        }

        // 3. 校验修改后的内容
        String error = validateContent(content);
        if (error != null) {
            return SkillResult.error("修改后内容校验失败: " + error);
        }

        // 4. 更新
        skill.setContent(content);
        // 重新解析 description（可能被修改了）
        SkillFrontmatter fm = parseFrontmatter(content);
        skill.setDescription(fm.getDescription());
        skillMapper.updateById(skill);

        // 5. 更新遥测
        bumpPatch(skill.getId(), tenantId);

        return SkillResult.success(
            "技能 '" + name + "' 已更新（" + matchCount + " 处替换）", skill);
    }

    // ═══════════════════════════════════════════════════════════════
    // Edit — 完全重写（大规模重构时使用）
    // ═══════════════════════════════════════════════════════════════

    public SkillResult edit(Long tenantId, String name, String newContent) {
        AgentSkill skill = skillMapper.selectByName(tenantId, name);
        if (skill == null) {
            return SkillResult.error("技能 '" + name + "' 不存在");
        }

        String error = validateContent(newContent);
        if (error != null) return SkillResult.error(error);

        SkillFrontmatter fm = parseFrontmatter(newContent);
        skill.setContent(newContent);
        skill.setDescription(fm.getDescription());
        skill.setVersion(fm.getVersion());
        skillMapper.updateById(skill);

        bumpPatch(skill.getId(), tenantId);
        return SkillResult.success("技能 '" + name + "' 已完全更新", skill);
    }

    // ═══════════════════════════════════════════════════════════════
    // Delete — 删除（支持声明合并意图）
    // ═══════════════════════════════════════════════════════════════

    public SkillResult delete(Long tenantId, String name, String absorbedInto) {
        AgentSkill skill = skillMapper.selectByName(tenantId, name);
        if (skill == null) {
            return SkillResult.error("技能 '" + name + "' 不存在");
        }

        // Pin 保护
        if (skill.getPinnedFlg() == 1) {
            return SkillResult.error(
                "技能 '" + name + "' 已被钉住，无法删除。" +
                "如需删除请先取消钉住。修改（patch/edit）仍然允许。");
        }

        // 验证 absorbedInto 目标
        if (absorbedInto != null && !absorbedInto.isBlank()) {
            AgentSkill target = skillMapper.selectByName(tenantId, absorbedInto.trim());
            if (target == null) {
                return SkillResult.error(
                    "absorbed_into 目标 '" + absorbedInto + "' 不存在，" +
                    "请先创建/修改目标技能再删除");
            }
        }

        // 软删除
        skill.setDeleteFlg(1);
        skill.setState("archived");
        skillMapper.updateById(skill);

        String msg = "技能 '" + name + "' 已删除";
        if (absorbedInto != null && !absorbedInto.isBlank()) {
            msg += "，内容已合并到 '" + absorbedInto.trim() + "'";
        }
        return SkillResult.success(msg, null);
    }

    // ═══════════════════════════════════════════════════════════════
    // 渐进式加载
    // ═══════════════════════════════════════════════════════════════

    /**
     * Level 0: 列表（注入 system prompt 的 skills index）
     */
    public List<SkillIndexItem> listForPrompt(Long tenantId) {
        return skillMapper.selectActiveIndex(tenantId);
        // 只返回 name + description + category，~3k tokens
    }

    /**
     * Level 1: 完整内容（Agent 决定使用时加载）
     */
    public SkillDetail view(Long tenantId, String name) {
        AgentSkill skill = skillMapper.selectByName(tenantId, name);
        if (skill == null) return null;

        // 更新使用遥测
        bumpUse(skill.getId(), tenantId);

        // 获取支撑文件列表
        List<AgentSkillFile> files = skillFileMapper.selectBySkillId(skill.getId());

        return SkillDetail.builder()
            .name(skill.getName())
            .description(skill.getDescription())
            .content(skill.getContent())
            .linkedFiles(files.stream()
                .collect(Collectors.groupingBy(AgentSkillFile::getFileType)))
            .build();
    }

    /**
     * Level 2: 特定支撑文件
     */
    public String viewFile(Long tenantId, String name, String filePath) {
        AgentSkill skill = skillMapper.selectByName(tenantId, name);
        if (skill == null) return null;

        AgentSkillFile file = skillFileMapper.selectByPath(skill.getId(), filePath);
        return file != null ? file.getFileContent() : null;
    }

    // ═══════════════════════════════════════════════════════════════
    // Curator — 生命周期自动管理
    // ═══════════════════════════════════════════════════════════════

    /**
     * 定时任务：检查过时 Skill 并自动归档
     * 建议每天执行一次
     */
    @Scheduled(cron = "0 0 3 * * ?")  // 每天凌晨3点
    public void curatorCheck() {
        int staleDays = 30;    // 30天未使用标记 stale
        int archiveDays = 60;  // 60天未使用自动归档

        long now = System.currentTimeMillis();
        long staleThreshold = now - staleDays * 86400_000L;
        long archiveThreshold = now - archiveDays * 86400_000L;

        // 只处理 Agent 创建的 Skill
        List<AgentSkillUsage> usages = usageMapper.selectAgentCreated();

        for (AgentSkillUsage usage : usages) {
            AgentSkill skill = skillMapper.selectById(usage.getSkillId());
            if (skill == null || skill.getPinnedFlg() == 1) continue;

            long lastActivity = Math.max(
                usage.getLastUsedAt() != null ? usage.getLastUsedAt() : 0,
                Math.max(
                    usage.getLastViewedAt() != null ? usage.getLastViewedAt() : 0,
                    usage.getLastPatchedAt() != null ? usage.getLastPatchedAt() : 0
                )
            );

            if (lastActivity < archiveThreshold && "stale".equals(skill.getState())) {
                skill.setState("archived");
                skill.setDeleteFlg(1);
                skillMapper.updateById(skill);
                log.info("Curator: archived skill '{}' (inactive {} days)",
                    skill.getName(), (now - lastActivity) / 86400_000L);
            } else if (lastActivity < staleThreshold && "active".equals(skill.getState())) {
                skill.setState("stale");
                skillMapper.updateById(skill);
                log.info("Curator: marked skill '{}' as stale", skill.getName());
            }
        }
    }

    // ═══════════════════════════════════════════════════════════════
    // 内部方法
    // ═══════════════════════════════════════════════════════════════

    private String validateName(String name) {
        if (name == null || name.isEmpty()) return "技能名称不能为空";
        if (name.length() > MAX_NAME_LENGTH) return "技能名称超过64字符";
        if (!VALID_NAME.matcher(name).matches()) 
            return "技能名称只能包含小写字母、数字、连字符和下划线";
        return null;
    }

    private String validateContent(String content) {
        if (content == null || content.isBlank()) return "内容不能为空";
        if (content.length() > MAX_CONTENT_CHARS) 
            return "内容超过 " + MAX_CONTENT_CHARS + " 字符限制";
        if (!content.startsWith("---")) 
            return "内容必须以 YAML frontmatter 开头（---）";
        // 校验 frontmatter 结构
        SkillFrontmatter fm = parseFrontmatter(content);
        if (fm == null) return "YAML frontmatter 解析失败";
        if (fm.getName() == null) return "frontmatter 缺少 name 字段";
        if (fm.getDescription() == null) return "frontmatter 缺少 description 字段";
        return null;
    }

    private void bumpUse(Long skillId, Long tenantId) {
        usageMapper.incrementUse(skillId, tenantId, System.currentTimeMillis());
    }

    private void bumpPatch(Long skillId, Long tenantId) {
        usageMapper.incrementPatch(skillId, tenantId, System.currentTimeMillis());
    }
}
```
