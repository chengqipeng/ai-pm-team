# XOQL 新系统设计方案

## 1. 概述

XOQL（XSY Object Query Language）是平台的对象查询语言，允许用户通过类 SQL 语法查询业务数据。新系统 XOQL 模块完全对标老系统 `xsy-xoql-service`，实现一致的查询语义，同时适配新系统的元数据驱动架构。

### 核心差异

| 维度 | 老系统 (xsy-xoql-service) | 新系统 (paas-platform-service) |
|:---|:---|:---|
| 部署方式 | 独立微服务 (RESTEasy + Dubbo) | 集成在 paas-platform-service 中 |
| 元数据来源 | Dubbo RPC 调用 + 本地缓存 | IMetadataMergeReadService (Common/Tenant 合并) |
| 数据表 | 固定表名 (p_custom_data_N) | 分表路由 (p_tenant_data_N via TableRouteService) |
| 数据权限 | 自定义 SQL 拼接 | DataPermissionFilter + PermissionCondition |
| 租户隔离 | MyCat 中间件 | 手动追加 tenant_id + entity_api_key 条件 |
| SQL 解析 | JSqlParser 1.4 | JSqlParser 4.6 |
| 框架 | Spring Boot + RESTEasy | Spring Boot + Spring MVC |

## 2. 模块结构

```
service/xoql/
├── XoqlConstants.java          # 常量定义（对标 XoqlConstants）
├── XoqlException.java          # 异常类（对标 XoqlException）
├── XoqlService.java            # 🔑 服务门面（对标 XoqlControllerImpl 核心逻辑）
├── check/                      # 校验器（对标 check 包）
│   ├── XoqlChecker.java
│   ├── XoqlLengthChecker.java
│   ├── XoqlSelectAllChecker.java
│   └── SqlWhereProtectionChecker.java
├── metadata/                   # 元数据服务（对标 XObjectAndXItemService）
│   └── XoqlMetadataService.java
├── model/                      # 数据模型（对标 entity 包）
│   ├── EntityMetaCache.java    # 对标 XObjectCacheData
│   ├── ItemMetaCache.java      # 对标 XoqlItemCacheData
│   ├── JoinEntity.java
│   ├── RelationEntity.java
│   ├── SubSelectEntity.java
│   ├── XoqlColumn.java
│   ├── XoqlParseEntity.java
│   ├── XoqlQueryParam.java
│   └── XoqlQueryResult.java
├── parser/                     # 🔑 解析器（对标 parser 包）
│   ├── SqlParseService.java    # SQL 解析工具
│   ├── XoqlParser.java         # 解析器接口
│   ├── XoqlParserImpl.java     # 解析器实现
│   └── dispatcher/             # SQL 转换调度器链（对标 dispatchers 包）
│       ├── SqlDispatcher.java
│       ├── UpRelationDispatcher.java
│       ├── ApiKeyReplaceDispatcher.java
│       ├── DeleteFlagDispatcher.java
│       ├── TenantIdDispatcher.java
│       ├── EntityApiKeyDispatcher.java
│       ├── DataPermissionDispatcher.java
│       └── PagingDispatcher.java
└── query/                      # 查询执行（对标 query 包）
    └── XoqlDataQueryService.java

api/xoql/
└── XoqlController.java         # REST 控制器（对标 XoqlController）
```

## 3. 核心流程

```
XOQL 输入
  │
  ▼
XoqlParserImpl.parse()
  │
  ├─ 1. prepare: 解析 XOQL → JSqlParser Select, 提取 FROM 实体, 加载元数据
  ├─ 2. extractColumns: 提取 SELECT 字段列表
  ├─ 3. check: 校验合法性（长度、SELECT *、SQL 注入）
  ├─ 4. checkAndAppendIdColumn: 确保 id 列存在
  └─ 5. dispatcher chain:
       ├─ UpRelationDispatcher     → 向上关联查询 → LEFT JOIN
       ├─ ApiKeyReplaceDispatcher  → apiKey → 物理列名/表名
       ├─ DeleteFlagDispatcher     → 追加 delete_flg = 0
       ├─ TenantIdDispatcher       → 追加 tenant_id = ?
       ├─ EntityApiKeyDispatcher   → 追加 entity_api_key = ?
       ├─ DataPermissionDispatcher → 追加数据权限条件
       └─ PagingDispatcher         → 处理 LIMIT/OFFSET
  │
  ▼
最终 SQL
  │
  ▼
XoqlDataQueryService.query()
  │
  ├─ 执行主查询 (JdbcTemplate)
  ├─ 处理子查询（向下关联、特殊字段）
  ├─ 合并结果（物理列名 → apiKey 映射）
  └─ 查询 count（可选）
  │
  ▼
XoqlQueryResult
```

## 4. API 接口

| 接口 | 方法 | 路径 | 说明 |
|:---|:---|:---|:---|
| OpenAPI 查询 | POST | /data/v2.0/query/xoql | 外部开发者调用，完整权限校验 |
| 内部查询 | POST | /data/v2.0/query/xoql-inner | 内部服务调用，可跳过权限 |
| 内部 JSON 查询 | POST | /data/v2.0/query/xoql-inner-json | JSON 参数版本 |
| 内部 View 查询 | POST | /data/v2.0/query/xoql-inner-json/for-view | 列表视图查询 |

## 5. 老系统对照表

| 老系统类 | 新系统类 | 说明 |
|:---|:---|:---|
| XoqlConstants | XoqlConstants | 常量定义，语义一致 |
| XoqlException | XoqlException | 异常类 |
| XoqlQueryParam | XoqlQueryParam | 查询参数 |
| XoqlParseEntity | XoqlParseEntity | 解析结果 |
| XObjectCacheData | EntityMetaCache | 实体元数据缓存 |
| XoqlItemCacheData | ItemMetaCache | 字段元数据缓存 |
| XoqlColumn | XoqlColumn | 查询字段 |
| XoqlQueryResult + RestResult | XoqlQueryResult | 查询结果 |
| AbstractXoqlParser | XoqlParserImpl | 解析器（合并了抽象类和实现类） |
| AbstractSqlDispatcher | SqlDispatcher | 调度器接口 |
| ReplaceApiKeySqlDispatcherImpl | ApiKeyReplaceDispatcher | apiKey 替换 |
| DataDeleteFlagSqlDispatcherImpl | DeleteFlagDispatcher | 删除标识 |
| DataPermissionSqlDispatcherImpl | DataPermissionDispatcher | 数据权限 |
| PagingSyntaxSqlDispatcherImpl | PagingDispatcher | 分页 |
| UpRelationSqlDispatcherImpl | UpRelationDispatcher | 向上关联 |
| XObjectAndXItemService | XoqlMetadataService | 元数据加载 |
| XoqlQueryService | XoqlDataQueryService | 查询执行 |
| XoqlControllerImpl | XoqlService + XoqlController | 服务门面 + REST |
| SqlParseService | SqlParseService | SQL 解析工具 |
