# 操作日志下沉 framework-dao 详细设计（元数据模式）

## 一、背景

两套操作日志（元数据 + 业务数据）用 `JdbcTemplate` 硬编码 SQL。目标：纳入元数据体系，走 `DataBaseServiceImpl` 标准链路，但保持两张表在各自的 schema 中。

## 二、架构

```
framework-dao（基础设施层，只提供框架能力）
├── annotation/
│   └── IgnoreTenantLine.java            # Entity 级注解，标记跳过租户拦截
├── service/
│   └── DataBaseServiceImpl.java         # 框架基类（自动识别 @IgnoreTenantLine）

paas-platform-service（业务层）
├── entity/
│   ├── operatelog/
│   │   ├── OperateLog.java              # 操作日志 Entity 基类（@IgnoreTenantLine，业务决策）
│   │   ├── BatchSaveContext.java         # 批量操作 ThreadLocal 上下文
│   │   └── OperateLogRollbackHandler.java # 回滚回调接口
│   ├── metadata/
│   │   └── MetaOperateLog.java          # @TableName("p_meta_operate_log")，继承 OperateLog
│   └── entitydata/
│       └── EntityOperateLog.java        # @TableName("p_entity_operate_log")，继承 OperateLog
├── service/
│   ├── MetaOperateLogDao.java           # extends DataBaseServiceImpl<MetaOperateLog>，含业务方法
│   ├── EntityOperateLogDao.java         # extends DataBaseServiceImpl<EntityOperateLog>，含业务方法
│   ├── MetaLogServiceImpl.java          # 瘦身：委托 MetaOperateLogDao
│   └── EntityOperateLogServiceImpl.java # 瘦身：委托 EntityOperateLogDao
```

## 三、存储位置（不变）

| 表 | Schema | 元模型 api_key | 用途 |
|:---|:---|:---|:---|
| `p_meta_operate_log` | paas_metarepo_common | metaOperateLog | 元数据批量操作回滚日志 |
| `p_entity_operate_log` | paas_entity_data | entityOperateLog | 业务数据批量操作回滚日志 |

两张表结构统一，但物理隔离在各自的 schema 中。

## 四、统一表结构

两张表 ALTER 为相同的列结构（在各自 schema 中）：

```sql
-- 统一列结构（两张表共用）
-- p_meta_operate_log 在 paas_metarepo_common
-- p_entity_operate_log 在 paas_entity_data

id                  BIGINT       NOT NULL,    -- 雪花 ID
tenant_id           BIGINT,                   -- 租户 ID
process_id          BIGINT       NOT NULL,    -- 批量操作事务 ID
target_type         VARCHAR(255) NOT NULL,    -- 元数据: metamodelApiKey, 业务数据: entityApiKey
target_key          VARCHAR(255),             -- 元数据: metadataApiKey, 业务数据: null
target_id           BIGINT,                   -- 元数据: null, 业务数据: dataId
dml_type            SMALLINT     NOT NULL,    -- 1=create, 2=update, 3=delete
before_value        TEXT,                     -- 操作前快照（JSON）
rollback_status     SMALLINT     NOT NULL DEFAULT 0,  -- 0=pending, 1=done
delete_flg          SMALLINT     NOT NULL DEFAULT 0,
created_at          BIGINT,
created_by          BIGINT,
updated_at          BIGINT,
updated_by          BIGINT,
PRIMARY KEY (id)
```

### 列名迁移映射

| 老列名（p_meta_operate_log） | 老列名（p_entity_operate_log） | 新统一列名 |
|:---|:---|:---|
| metamodel_api_key | entity_api_key | `target_type` |
| metadata_api_key | — | `target_key` |
| — | data_id | `target_id` |

## 五、元模型注册

```sql
-- 元数据操作日志
INSERT INTO paas_metarepo_common.p_meta_model (
    id, api_key, label, namespace, metamodel_type,
    enable_common, enable_tenant, enable_tenant_intercept,
    db_table, entity_dependency, visible,
    delete_flg, created_by, created_at, updated_by, updated_at
) VALUES (
    1900000000000000011, 'metaOperateLog', '元数据操作日志', 'system', 1,
    0, 1, 0,
    'p_meta_operate_log', 0, 0,
    0, 1, {now}, 1, {now}
);

-- 业务数据操作日志
INSERT INTO paas_metarepo_common.p_meta_model (
    id, api_key, label, namespace, metamodel_type,
    enable_common, enable_tenant, enable_tenant_intercept,
    db_table, entity_dependency, visible,
    delete_flg, created_by, created_at, updated_by, updated_at
) VALUES (
    1900000000000000012, 'entityOperateLog', '业务数据操作日志', 'system', 1,
    0, 1, 0,
    'p_entity_operate_log', 0, 0,
    0, 1, {now}, 1, {now}
);
```

## 六、framework-dao 新增

### 6.1 OperateLog.java（通用 Entity 基类）

```java
package com.hongyang.framework.dao.operatelog;

import com.hongyang.framework.dao.entity.BaseEntity;
import lombok.Data;
import lombok.EqualsAndHashCode;

/**
 * 操作日志通用基类。
 * 不加 @TableName（由子类指定具体表名）。
 * 不加 @DaoCacheConfig（操作日志不走缓存）。
 * 加 @IgnoreTenantLine（操作日志不走租户拦截，由业务代码自行控制 tenant_id）。
 */
@Data
@EqualsAndHashCode(callSuper = true)
@IgnoreTenantLine
public abstract class OperateLog extends BaseEntity {

    private Long tenantId;
    private Long processId;

    /** 业务类型（元数据: metamodelApiKey, 业务数据: entityApiKey） */
    private String targetType;

    /** 业务标识（元数据: metadataApiKey, 业务数据: null） */
    private String targetKey;

    /** 数据 ID（业务数据: dataId, 元数据: null） */
    private Long targetId;

    /** 1=create, 2=update, 3=delete */
    private Integer dmlType;

    /** 操作前数据快照（JSON） */
    private String beforeValue;

    /** 0=pending, 1=done */
    private Integer rollbackStatus;

    public static final int DML_CREATE = 1;
    public static final int DML_UPDATE = 2;
    public static final int DML_DELETE = 3;
    public static final int ROLLBACK_PENDING = 0;
    public static final int ROLLBACK_DONE    = 1;
}
```

### 6.2 OperateLogRollbackHandler.java

```java
package com.hongyang.framework.dao.operatelog;

@FunctionalInterface
public interface OperateLogRollbackHandler {
    void doRollback(OperateLog log);
}
```

### 6.3 BatchSaveContext.java

```java
package com.hongyang.framework.dao.operatelog;

public final class BatchSaveContext {
    private BatchSaveContext() {}
    private static final ThreadLocal<Long> PROCESS_ID = new ThreadLocal<>();

    public static void setProcessId(Long processId) { PROCESS_ID.set(processId); }
    public static Long getProcessId()               { return PROCESS_ID.get(); }
    public static boolean isInBatchSave()           { return PROCESS_ID.get() != null; }
    public static void clear()                      { PROCESS_ID.remove(); }
}
```

## 七、业务层改造

### 7.1 Entity 子类（指定各自的表名）

```java
// paas-platform-service
@TableName("p_meta_operate_log")
public class MetaOperateLog extends OperateLog {}

@TableName("p_entity_operate_log")
public class EntityOperateLog extends OperateLog {}
```

### 7.2 DAO 子类（直接继承 DataBaseServiceImpl，含业务方法）

```java
@Slf4j
@Service
public class MetaOperateLogDao extends DataBaseServiceImpl<MetaOperateLog> {

    /** 提交：删除该 processId 的所有记录 */
    public void commitByProcessId(Long processId) {
        try {
            remove(new QueryWrapper<MetaOperateLog>()
                    .eq("process_id", processId));
            log.info("[OperateLog] commit processId={}", processId);
        } catch (Exception e) {
            log.error("[OperateLog] commit 失败: processId={}", processId, e);
        }
    }

    /** 查询指定 processId 的待回滚记录（倒序） */
    public List<MetaOperateLog> listPendingByProcessId(Long processId) {
        return list(new QueryWrapper<MetaOperateLog>()
                .eq("process_id", processId)
                .eq("rollback_status", OperateLog.ROLLBACK_PENDING)
                .orderByDesc("created_at"));
    }

    /** 标记单条已回滚 */
    public void markRolledBack(Long logId) {
        update(new UpdateWrapper<MetaOperateLog>()
                .eq("id", logId)
                .set("rollback_status", OperateLog.ROLLBACK_DONE));
    }

    /** 查询超时未完成的 processId */
    public List<Long> findPendingProcessIds(long beforeTime) {
        List<MetaOperateLog> logs = list(new QueryWrapper<MetaOperateLog>()
                .le("created_at", beforeTime)
                .eq("rollback_status", OperateLog.ROLLBACK_PENDING));
        if (logs.isEmpty()) return Collections.emptyList();
        return logs.stream()
                .map(OperateLog::getProcessId)
                .distinct()
                .collect(Collectors.toList());
    }

    /** 执行回滚 */
    public void rollbackByProcessId(Long processId,
                                     OperateLogRollbackHandler handler) {
        log.warn("[OperateLog] 开始回滚 processId={}", processId);
        List<MetaOperateLog> logs = listPendingByProcessId(processId);
        BatchSaveContext.clear();
        for (MetaOperateLog opLog : logs) {
            try {
                handler.doRollback(opLog);
                markRolledBack(opLog.getId());
            } catch (Exception e) {
                log.error("[OperateLog] 回滚单条失败: logId={}, targetType={}",
                        opLog.getId(), opLog.getTargetType(), e);
            }
        }
        log.warn("[OperateLog] 回滚完成 processId={}, 共 {} 条",
                processId, logs.size());
    }
}

@Slf4j
@Service
public class EntityOperateLogDao extends DataBaseServiceImpl<EntityOperateLog> {
    // 方法实现与 MetaOperateLogDao 完全相同，泛型参数换为 EntityOperateLog
    // 省略重复代码
}
```

> 两个 DAO 的业务方法完全相同（只是泛型不同）。如需消除重复，可在 paas-platform-service 内部提取抽象基类，但该基类属于业务层，不属于 framework-dao。
> 所有 CRUD 方法（save/list/remove/update）由 DataBaseServiceImpl 提供，
> 租户拦截由框架通过 @IgnoreTenantLine 注解自动跳过，DAO 代码无需任何拦截器相关处理。

### 7.3 Schema 路由

| Entity | @TableName | MetaRepoDataConfig 路由规则 | 实际 schema |
|:---|:---|:---|:---|
| MetaOperateLog | p_meta_operate_log | 规则 2：`p_meta_*` → `paas_metarepo_common` | paas_metarepo_common |
| EntityOperateLog | p_entity_operate_log | 规则 3：`ENTITY_INFRA_TABLES` 已包含 | paas_entity_data |

不需要改路由配置，现有规则已覆盖。

### 7.4 EntityOperateLogServiceImpl（瘦身）

```java
@Service
@RequiredArgsConstructor
public class EntityOperateLogServiceImpl implements IEntityOperateLogService {

    private final EntityOperateLogDao logDao;
    private final IdGenerator idGenerator;
    private final TableRouteService routeService;
    private final TenantDataServiceImpl dataDao;

    @Override
    public Long newProcessId() {
        Long pid = (Long) idGenerator.nextId();
        BatchSaveContext.setProcessId(pid);
        return pid;
    }

    @Override
    public void logOperate(Long processId, long tenantId, String entityApiKey,
                           long dataId, int dmlType, Map<String, Object> beforeValue) {
        if (!BatchSaveContext.isInBatchSave()) return;
        EntityOperateLog log = new EntityOperateLog();
        log.setTenantId(tenantId);
        log.setProcessId(processId);
        log.setTargetType(entityApiKey);
        log.setTargetId(dataId);
        log.setDmlType(dmlType);
        log.setBeforeValue(beforeValue != null ? JSON.toJSONString(beforeValue) : null);
        log.setRollbackStatus(OperateLog.ROLLBACK_PENDING);
        log.setCreatedAt(System.currentTimeMillis());
        logDao.save(log);
    }

    @Override public void commitByProcessId(Long pid) { logDao.commitByProcessId(pid); }
    @Override public List<Long> findPendingProcessIds(long t) { return logDao.findPendingProcessIds(t); }

    @Override
    public void rollbackByProcessId(Long processId) {
        logDao.rollbackByProcessId(processId, log -> doRollback(log));
    }

    /** 回滚逻辑不变 */
    private void doRollback(OperateLog log) {
        long tenantId = log.getTenantId();
        String entityKey = log.getTargetType();
        long dataId = log.getTargetId();
        int dmlType = log.getDmlType();
        String beforeJson = log.getBeforeValue();
        // ... 现有 switch(dmlType) 逻辑不变
    }
}
```

### 7.5 MetaLogServiceImpl（瘦身）

```java
@Service
public class MetaLogServiceImpl extends DataBaseServiceImpl<MetaLog> implements IMetaLogService {

    @Autowired private MetaOperateLogDao operateLogDao;
    @Autowired private IdGenerator idGenerator;
    @Lazy @Autowired private IMetadataMergeWriteService writeService;

    // 审计日志方法保持不变

    @Override
    public Long newProcessId() {
        Long pid = (Long) idGenerator.nextId();
        BatchSaveContext.setProcessId(pid);
        return pid;
    }

    @Override
    public void logOperate(Long processId, Long tenantId, String metamodelApiKey,
                           String metadataApiKey, int dmlType, BaseMetaTenantEntity beforeValue) {
        MetaOperateLog log = new MetaOperateLog();
        log.setTenantId(tenantId);
        log.setProcessId(processId);
        log.setTargetType(metamodelApiKey);
        log.setTargetKey(metadataApiKey);
        log.setDmlType(dmlType);
        log.setBeforeValue(beforeValue != null ? JSON.toJSONString(beforeValue) : null);
        log.setRollbackStatus(OperateLog.ROLLBACK_PENDING);
        log.setCreatedAt(System.currentTimeMillis());
        operateLogDao.save(log);
    }

    @Override public void commitByProcessId(Long pid) { operateLogDao.commitByProcessId(pid); }
    @Override public List<Long> findPendingProcessIds(long t) { return operateLogDao.findPendingProcessIds(t); }

    @Override
    public void rollbackByProcessId(Long processId) {
        operateLogDao.rollbackByProcessId(processId, log -> doRollback(log));
    }

    /** 回滚逻辑不变 */
    private void doRollback(OperateLog log) { /* 现有逻辑 */ }
}
```

## 八、DDL 变更

两张表需要 ALTER 统一列名（在各自 schema 中执行）：

```sql
-- paas_metarepo_common.p_meta_operate_log
ALTER TABLE paas_metarepo_common.p_meta_operate_log
    RENAME COLUMN metamodel_api_key TO target_type;
ALTER TABLE paas_metarepo_common.p_meta_operate_log
    RENAME COLUMN metadata_api_key TO target_key;
ALTER TABLE paas_metarepo_common.p_meta_operate_log
    ADD COLUMN IF NOT EXISTS target_id BIGINT;

-- paas_entity_data.p_entity_operate_log
ALTER TABLE paas_entity_data.p_entity_operate_log
    RENAME COLUMN entity_api_key TO target_type;
ALTER TABLE paas_entity_data.p_entity_operate_log
    ADD COLUMN IF NOT EXISTS target_key VARCHAR(255);
ALTER TABLE paas_entity_data.p_entity_operate_log
    RENAME COLUMN data_id TO target_id;
```

## 九、文件变更清单

### framework-dao 新增（1 个文件）

| 文件 | 说明 |
|:---|:---|
| `annotation/IgnoreTenantLine.java` | Entity 级注解，标记跳过租户拦截 |

### framework-dao 改动（1 个文件）

| 文件 | 说明 |
|:---|:---|
| `service/DataBaseServiceImpl.java` | 新增 `@IgnoreTenantLine` 识别 + `executeWithTenantControl()` 框架级支持 |

### paas-platform-service 新增（5 个文件）

| 文件 | 说明 |
|:---|:---|
| `entity/operatelog/OperateLog.java` | 操作日志 Entity 基类（从 framework-dao 移入，标注 `@IgnoreTenantLine`） |
| `entity/operatelog/BatchSaveContext.java` | 批量操作 ThreadLocal 上下文（从 framework-dao 移入） |
| `entity/operatelog/OperateLogRollbackHandler.java` | 回滚回调接口（从 framework-dao 移入） |
| `entity/metadata/MetaOperateLog.java` | 继承 OperateLog + @TableName("p_meta_operate_log") |
| `entity/entitydata/EntityOperateLog.java` | 继承 OperateLog + @TableName("p_entity_operate_log") |

### paas-platform-service 新增 DAO（2 个文件）

| 文件 | 说明 |
|:---|:---|
| `service/metadata/impl/MetaOperateLogDao.java` | extends DataBaseServiceImpl&lt;MetaOperateLog&gt;，含操作日志业务方法 |
| `service/entitydata/batch/EntityOperateLogDao.java` | extends DataBaseServiceImpl&lt;EntityOperateLog&gt;，含操作日志业务方法 |

### paas-platform-service 修改（2 个文件）

| 文件 | 改动 |
|:---|:---|
| `MetaLogServiceImpl.java` | JdbcTemplate → MetaOperateLogDao |
| `EntityOperateLogServiceImpl.java` | JdbcTemplate → EntityOperateLogDao |

### paas-platform-service 删除（2 个文件）

| 文件 | 原因 |
|:---|:---|
| `MetaBatchSaveContext.java` | 被 framework-dao 的 BatchSaveContext 替代 |
| `EntityBatchSaveContext.java` | 同上 |

## 十、不变的部分

- `IMetaLogService` 接口签名不变
- `IEntityOperateLogService` 接口签名不变
- `PendingTransactionRecovery` / `EntityPendingTransactionRecovery` 不变
- `MetadataBatchSaveApiService` / `EntityDataBatchService` 调用方式不变
- 两张表的物理位置不变（各自 schema）
- 回滚逻辑不变（业务层实现 `OperateLogRollbackHandler`）
