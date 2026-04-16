---
inclusion: auto
description: aPaaS元数据驱动平台产品定位、三层架构、微服务矩阵、数据模型与全局基线约束
---

# aPaaS 元数据驱动平台 产品上下文

## 产品定位
aPaaS 元数据驱动平台，以元模型为核心，构建"元模型定义→元数据实例→业务数据"三层架构，实现业务对象的声明式配置与动态扩展。
核心价值：从"硬编码建表"到"配置即生效"，新增业务对象从 2-4 周缩短至 10 分钟，支撑 SaaS 多租户规模化。

## 三大核心优势
1. 元模型驱动的 Schema-on-Read：通过 p_meta_model + p_meta_item 声明式定义元模型，大宽表 dbc_xxxN 扩展列存储元数据实例，新增元模型零 DDL
2. Common/Tenant 双层隔离与合并：出厂元数据（system/product）独立升级，租户自定义元数据互不影响，合并读取透明覆盖
3. api_key 全链路关联：禁止 ID 关联，跨环境迁移一致性，人类可读，支持 Module 打包分发

## 三层架构

```
第一层：元模型注册（p_meta_model）
  定义"有哪些类型的元数据"，当前 30+ 种元模型（含 entity 相关 + role/department/operateLog 等独立元模型）
  db_table 指向各元模型的 Tenant 级存储表
第二层：元模型字段定义（p_meta_item）
  定义每种元模型有哪些属性字段，当前 500+ 个字段定义
  db_column 映射到大宽表的 dbc_xxxN 列
第三层：元数据实例
  Common 级：统一存储在 p_common_metadata 大宽表
  Tenant 级：高数据量→独立快捷表，低数据量→共享 p_tenant_metadata
```

## 代码仓库说明

| 仓库 | 路径 | 定位 | 技术栈 |
|:---|:---|:---|:---|
| 新项目（apass_new_projects） | repos/apass_new_projects/ | **所有产品修改必须在此仓库** | Spring Boot + Spring Cloud + MyBatis-Plus |
| 老项目（apass_old_projects） | repos/apass_old_projects/ | **仅作为参考，不做修改** | Spring Boot + Dubbo + Zookeeper + RESTEasy |

> ⚠️ 硬约束：所有新功能开发、Bug 修复、架构重构均在 apass_new_projects 中进行。apass_old_projects 仅用于理解老系统逻辑、数据迁移对照、历史行为参考。

### 新项目（apass_new_projects）— 微服务矩阵
| 服务 | 职责 | 代码路径 |
|:---|:---|:---|
| paas-metarepo-service | 元数据仓库核心：元模型管理 + 元数据 CRUD + Common/Tenant 合并读取 | repos/apass_new_projects/paas-metarepo-service/ |
| paas-front-platform | 新一代前端框架（React 19 + Antd 6 + Vite 8），含元数据管理后台（front-admin） | repos/apass_new_projects/paas-front-platform/ |
| paas-metadata-service | 元数据对外服务层，适配新元数据读取接口 | repos/apass_new_projects/paas-metadata-service/ |
| paas-entity-service | 实体数据 CRUD，基于元数据驱动 | repos/apass_new_projects/paas-entity-service/ |
| paas-layout-service | 布局渲染，依赖元数据字段定义 | repos/apass_new_projects/paas-layout-service/ |
| paas-rule-service | 规则执行，依赖 checkRule 元数据 | repos/apass_new_projects/paas-rule-service/ |
| paas-privilege-service | 权限服务 | repos/apass_new_projects/paas-privilege-service/ |
| paas-gateway | API 网关 | repos/apass_new_projects/paas-gateway/ |
| framework-basic | 基础框架（核心 + Spring Boot 自动配置） | repos/apass_new_projects/framework-basic/ |
| framework-common | 公共工具库 | repos/apass_new_projects/framework-common/ |

### 老项目（apass_old_projects）— 仅供参考
| 服务 | 职责 | 参考价值 |
|:---|:---|:---|
| paas-metarepo-service | 老版元数据仓库 | 老编码体系、老数据结构对照 |
| paas-metadata-service | 老版元数据服务 | 老接口契约参考 |
| paas-customize-service | 自定义数据 CRUD + 字段映射 + 审批流 | 老业务逻辑、数据权限、实体映射参考 |
| neo-apaas-layout-service | 布局服务（JAX-RS + Dubbo） | 老布局 API Schema、聚合层逻辑参考 |
| paas-privilege-service | 老版权限服务 | 权限模型参考 |
| apps-ingage-admin | 管理后台 | 老管理界面参考 |
| platform-sns-dal | 数据访问层 | 老 DAO 层、SQL 参考 |

## 数据架构
| 数据库（schema） | 用途 | 表前缀/关键表 |
|:---|:---|:---|
| paas_metarepo_common | 元模型定义（p_meta_*）+ Common 级元数据（p_common_metadata） | p_meta_*、p_common_* |
| paas_metarepo | Tenant 级元数据（p_tenant_*）+ 运行时数据 | p_tenant_*、p_meta_log |
| paas_auth | 用户认证（p_user、p_passport）+ 用户角色关联（p_user_role） | p_user、p_passport、p_user_role |
| paas_entity_data | 业务数据分片表（p_tenant_data_0~1999）+ 权限 share 表（p_data_share_0~999） | p_tenant_data_*、p_data_share_* |

## 核心数据模型
| 实体 | 说明 | 主键/唯一标识 |
|:---|:---|:---|
| MetaModel（元模型） | 元模型注册，定义元数据类型 | api_key 全局唯一 |
| MetaItem（元模型字段） | 元模型属性字段定义，db_column 映射 | (metamodel_api_key, api_key) |
| MetaLink（元模型关联） | 元模型间父子/引用关系 | api_key 全局唯一 |
| MetaOption（元模型选项） | 枚举字段合法取值 | (metamodel_api_key, item_api_key, option_code) |
| CommonMetadata（Common 元数据） | 大宽表，固定列 + 130 个 dbc_xxxN 扩展列 | (metamodel_api_key, api_key) |
| TenantMetadata（Tenant 元数据） | 与 Common 结构一致 + tenant_id | (tenant_id, metamodel_api_key, api_key) |
| Entity（业务对象） | 业务视图，CommonMetadataConverter 转换 | api_key |
| EntityItem（字段） | 业务视图 | (entity_api_key, api_key) |
| EntityLink（关联关系） | 业务视图 | api_key |
| CheckRule（校验规则） | 业务视图 | (entity_api_key, api_key) |
| BusiType（业务类型） | 业务视图 | (entity_api_key, api_key) |
| DuplicateRule（查重规则） | 业务视图 | (entity_api_key, api_key) |
| DuplicateRuleCriteria（查重条件） | 业务视图 | (entity_api_key, rule_api_key, api_key) |
| DuplicateMatchingRule（查重匹配） | 业务视图 | (entity_api_key, rule_api_key, api_key) |
| FormulaCompute（计算公式） | 业务视图 | (entity_api_key, item_api_key, api_key) |
| FormulaComputeItem（公式引用字段） | 业务视图 | (entity_api_key, compute_api_key, api_key) |
| AggregationCompute（汇总累计） | 业务视图 | (entity_api_key, item_api_key, api_key) |
| AggregationComputeDetail（汇总条件） | 业务视图 | (entity_api_key, aggregate_api_key, api_key) |
| ComputeFactor（计算因子） | 业务视图 | (entity_api_key, compute_api_key, api_key) |
| PickOption（选项值） | 业务视图 | (entity_api_key, item_api_key, api_key) |
| Role（角色） | 独立元模型，存储在 p_tenant_role | api_key |
| Department（部门） | 独立元模型，存储在 p_tenant_department | api_key |
| SharingRule（共享规则） | 独立元模型，存储在 p_tenant_sharing_rule | (entity_api_key, api_key) |
| SharingRuleCondition（共享规则条件） | 独立元模型 | (entity_api_key, rule_api_key, api_key) |
| DataPermission（数据权限配置） | 独立元模型，存储在 p_tenant_data_permission | (entity_api_key, api_key) |

## 技术栈
| 层级 | 技术 | 版本 |
|:---|:---|:---|
| 后端框架 | Spring Boot + Spring Cloud | — |
| ORM | MyBatis-Plus | — |
| 数据库 | MySQL + PostgreSQL（双兼容） | — |
| 主键策略 | 雪花算法 BIGINT | — |
| 前端框架 | React | 19.2 |
| UI 组件库 | Ant Design | 6.3 |
| 构建工具 | Vite | 8.0 |
| 类型系统 | TypeScript | 5.9 |

## 全局基线约束
1. 元数据表禁止使用自增 ID 作为主键，统一使用 api_key 或联合主键
2. 元数据之间的关联禁止使用 ID（entity_id、item_id），统一使用 api_key 关联
3. 字段 apiName 统一 camelCase 英文，展示名用简短中文，尽量给出 helpText
3a. p_meta_item.api_key 统一 camelCase，与 Java Entity 字段名一致，禁止 snake_case
3b. 布尔字段统一 `xxxFlg` 后缀 + Integer(0/1) + SMALLINT，禁止 `enable*`/`is*` 前缀，禁止 Java Boolean 类型
3c. 布尔判断统一使用 `MetaBooleanUtils.isTrue()/isFalse()/TRUE/FALSE`，禁止直接 `== 1` 比较
3d. customFlg 由基类 BaseMetaCommonEntity 统一提供，各元模型实体类不再单独声明
4. 所有文本字段必须有对应 xxxKey 国际化字段（label→labelKey, description→descriptionKey）
5. 数据库表名统一 snake_case，元模型定义表前缀 p_meta_，Common 表前缀 p_common_，Tenant 表前缀 p_tenant_
6. 大宽表列名格式统一 dbc_xxxN（无下划线分隔数字），如 dbc_varchar8、dbc_int1
7. 所有 DDL 必须同时兼容 MySQL 和 PostgreSQL，禁止 AUTO_INCREMENT、ENGINE、COMMENT、BOOLEAN、ENUM
8. namespace 三分类：system（系统出厂）、product（业务产品，受 license 控制）、custom（租户自定义）
9. Common 级数据由平台初始化或 Module 安装写入，业务层不直接写入 Common 表
10. 接口响应时间：元数据列表查询 P95 < 200ms，合并读取 P95 < 500ms，写入 P95 < 1s
11. 前端请求体 camelCase → snake_case 转换，响应体 snake_case → camelCase 转换
12. 敏感数据需脱敏处理，严格遵循 RBAC 权限体系
13. **BaseEntity 基础字段规范**：所有业务表（尤其 paas_auth schema 下的表）必须包含框架 BaseEntity 定义的 6 个基础字段：`id`(BIGINT 主键)、`delete_flg`(SMALLINT 软删除)、`created_at`(BIGINT 创建时间戳)、`created_by`(BIGINT 创建人)、`updated_at`(BIGINT 更新时间戳)、`updated_by`(BIGINT 更新人)。新建表时必须包含全部 6 列，缺少任何一列会导致 MyBatis-Plus 查询报错。
14. **BFF 层禁止直连数据库**：所有数据读写操作必须通过 Java 后端服务接口完成。BFF（Node.js）层仅负责接口代理、请求聚合、前置参数校验等业务编排，严禁直接连接 PostgreSQL/MySQL 执行 SQL。数据校验（必填、格式、唯一性）和业务规则必须在 Java 服务层实现，BFF 层的校验仅作为前置快速拦截，不可替代后端校验。
15. **前端/BFF 禁止存储数据和业务计算**：所有数据存储、业务逻辑计算、规则判断必须在 Java 后端完成并返回结果。前端仅负责页面展示和用户交互，BFF 仅负责接口代理和组合以支撑前端页面展示。禁止在前端或 BFF 层使用本地文件、localStorage、内存缓存等方式存储业务数据，禁止在前端或 BFF 层实现业务规则计算。
16. **线程池必须使用 TTL 包装**：所有 Java 线程池（`ThreadPoolTaskExecutor`、`ExecutorService` 等）必须使用 `com.alibaba.ttl.threadpool.TtlExecutors` 包装，确保 `TransmittableThreadLocal`（租户上下文、权限条件、分表路由等）在异步任务中正确传递。禁止使用 Java 内置的 `Executors.newFixedThreadPool()` 等未包装的线程池。Spring `@Async` 方法对应的 Executor Bean 必须返回 TTL 包装后的实例。

## 进行中 & 规划中
| 方向 | 状态 | 说明 |
|:---|:---:|:---|
| 数据迁移（item_type + db_column） | 🔄进行中 | 剩余 3,333 条 item_type 编码转换 + db_column 重分配 |
| 元模型字段命名规范统一 | 🔄进行中 | p_meta_item api_key + Java 字段名统一 camelCase，消除缩写/前缀不一致 |
| 元数据管理前端 | 🔄进行中 | paas-front-platform（front-admin）：元模型浏览、元数据列表、字段映射可视化 |
| role/department 元模型迁移 | ✅已完成 | 从 entity 注册改为独立元模型，数据迁移到 p_tenant_role/p_tenant_department |
| BFF 直连数据库清理 | ✅已完成 | 删除 server/ 目录（permission-routes.cjs、entity-routes.cjs、index.cjs），移除 mysql2/express/cors 依赖 |
| 计算字段子元模型恢复 | 📋规划中 | formulaCompute/aggregationCompute 等 5 个子元模型 |
| Delta 增量覆盖 | 📋规划中 | enable_delta + delta_scope + delta_mode |
| Module 打包分发 | 📋规划中 | enable_package 元数据模块化 |
| 元数据变更日志完善 | 📋规划中 | p_tenant_meta_log 全量写操作日志 |
| 元数据写入 Schema 校验 | 📋规划中 | p_meta_option 取值范围 + p_meta_item 必填/唯一约束 |

## 设计参考
| 文档 | 路径 | 内容 |
|:---|:---|:---|
| 元数据设计规范 | product-specs/metadata-system/元数据设计规范.md | 存储、命名、关联、唯一性规范 |
| 元模型设计体系 | product-specs/metadata-system/元模型设计体系.md | 三层架构、四表体系、完整字段定义 |
| 元数据实例设计 | product-specs/metadata-system/元数据实例设计.md | 大宽表、合并机制、写入流程、Java 类体系 |
| 数据迁移方案 | product-specs/metadata-system/数据迁移方案.md | 老→新编码转换、db_column 重分配 |

## 功能现状文档索引
> 优化已有功能时，请参考 context/features/ 下的详细文档
> 每个功能一个中文子目录，包含 `功能现状.md`（产品设计视角）和 `代码分析.md`（代码实现视角，如有）

| 功能 | 产品设计文档 | 代码分析文档 | 最后更新 |
|:---|:---|:---|:---:|
| （使用 `#pm-context-harvest` 采集功能文档后，此表自动更新） | | | |
