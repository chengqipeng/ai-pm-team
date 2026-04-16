# 元数据驱动平台 - 项目上下文

> 创建日期：2026-03-31 | 状态：进行中

## 项目信息
- 项目名称：metadata-system
- 需求来源：战略规划 / 技术驱动
- 期望上线：分阶段交付（MVP 6周 + V1 4周 + V2 6周）
- 优先级：P0

## 需求背景

aPaaS 平台当前的业务对象管理采用"硬编码建表"模式——每新增一种业务对象（如 Entity、Item、CheckRule），都需要开发人员手动建表、写 DAO、写 Service，周期 2-4 周。随着 SaaS 多租户规模化，业务对象种类持续增长，这种模式已成为平台扩展的核心瓶颈。

老系统存在多项技术债：字段类型编码（item_type）新老混用导致前端渲染异常（月均 5-8 次）；元数据间通过 ID 关联导致跨环境迁移失败率高达 15%；字段命名不统一（snake_case/camelCase 混用、enable*/is* 前缀不一致）增加了维护成本。

本项目的核心目标是构建以元模型为核心的三层架构（元模型定义→元数据实例→业务数据），通过声明式配置替代硬编码，实现"配置即生效"。

## 价值主张

### 业务价值
- 新增业务对象从 2-4 周缩短至 10 分钟，极大提升业务响应速度
- 支撑 SaaS 多租户规模化，Common/Tenant 双层隔离确保租户间数据安全
- 通过 Module 打包分发（规划中），实现业务能力的模块化交付

### 用户价值
- 平台管理员可通过管理前端（paas-front-platform / front-admin）可视化浏览和管理元模型与元数据，无需依赖开发
- 租户管理员可自定义业务对象和字段，满足个性化需求
- 业务开发者通过统一 API 读写元数据，无需关心底层存储细节

### 技术价值
- Schema-on-Read 架构：大宽表 + dbc_xxxN 扩展列，新增元模型零 DDL
- api_key 全链路关联替代 ID 关联，跨环境迁移一致性从 85% 提升至 99%+
- 统一 ItemTypeEnum 编码体系，消除新老编码混用导致的前端渲染异常
- DynamicTableNameHolder 路由机制，Tenant 级独立快捷表与 Common 大宽表结构一致，Java 层统一操作

### 战略价值
- 元数据驱动是 aPaaS 平台的核心基础设施，所有上层业务（实体数据 CRUD、布局渲染、规则执行、权限控制）均依赖元数据
- 为后续 Delta 增量覆盖、Module 打包分发、计算字段子元模型恢复等高级能力奠定架构基础
- 从"代码驱动"到"配置驱动"的范式转变，是平台长期竞争力的关键

## 目标用户
| 角色 | 核心诉求 | 使用频率 |
|:---|:---|:---|
| 平台管理员 | 管理元模型定义、初始化 Common 元数据、监控元数据健康状态 | 日常 |
| 租户管理员 | 自定义业务对象和字段、管理选项值和校验规则 | 高频 |
| 业务开发者 | 通过 API 读写元数据、基于元数据驱动业务逻辑 | 高频 |

## 成功指标
| 指标 | 当前值 | 目标值 | 衡量方式 |
|:---|:---:|:---:|:---|
| 新增业务对象耗时 | 2-4 周 | 10 分钟 | 配置到可用的端到端时间 |
| 字段类型映射异常 | 月均 5-8 次 | 0 | 前端渲染异常工单数 |
| 跨环境迁移失败率 | 15% | <1% | api_key 关联后迁移成功率 |
| 元数据列表查询 | 未统计 | P95 < 200ms | APM 监控 |
| 元数据合并读取 | 未统计 | P95 < 500ms | APM 监控 |

## 范围边界

**做什么：**
- 元模型四表体系（p_meta_model / p_meta_item / p_meta_link / p_meta_option）
- 大宽表存储机制（p_common_metadata + p_tenant_* 独立快捷表）
- Common/Tenant 合并读取引擎（CommonMetadataConverter + MergeReadService）
- 元数据 CRUD API（6 读 + 6 写 + 内部浏览接口）
- 数据迁移（item_type 编码转换 + db_column 重分配 + api_key 命名统一 + ID→apiKey 关联改造）
- Schema 校验（p_meta_option 取值范围 + p_meta_item 必填/唯一约束）
- 管理前端 paas-front-platform / front-admin（元模型浏览、元数据浏览）
- 元数据变更日志（P1）
- 管理前端编辑 + 字段映射可视化（P1）

**不做什么：**
- 计算字段子元模型恢复（formulaCompute 等 5 个子元模型）— P2 规划
- Delta 增量覆盖机制 — P2 规划
- Module 打包分发 — P2 规划
- 业务数据层（paas-entity-service）的改造 — 独立项目
- 布局渲染层（paas-layout-service）的适配 — 独立项目

## 风险与约束
| 风险/约束 | 影响 | 应对策略 |
|:---|:---|:---|
| 数据迁移量大（item 23,819 条） | 迁移耗时长，需停机窗口 | 分批迁移 + 灰度验证，按元模型并行执行 |
| 老系统 entityLink 的 db_column 带下划线格式 | 新老格式不一致 | 新增字段统一无下划线格式，老数据标注为历史遗留 |
| DDL 需同时兼容 MySQL 和 PostgreSQL | 限制可用的数据类型和语法 | 禁止 AUTO_INCREMENT/ENGINE/COMMENT/BOOLEAN/ENUM |
| Common 库跨库查询性能 | 合并读取延迟 | P95 < 500ms 目标，超时降级为仅返回单层数据 |
| 前端 ItemTypeEnum 映射 API 加载失败 | 字段类型展示异常 | 前端回退硬编码 ITEM_TYPE_MAP |

## 关联文档
- 产品设计：`product-specs/metadata-system/`
  - [产品方案设计](../../product-specs/metadata-system/产品-方案设计.md)
  - [元模型设计体系](../../product-specs/metadata-system/元模型设计体系.md)
  - [元数据实例设计](../../product-specs/metadata-system/元数据实例设计.md)
  - [元数据设计规范](../../product-specs/metadata-system/元数据设计规范.md)
  - [数据迁移方案](../../product-specs/metadata-system/数据迁移方案.md)
  - 元模型详细设计：`product-specs/metadata-system/models/`
  - 迁移详细方案：`product-specs/metadata-system/migration/`

## 关键决策记录
| 日期 | 决策 | 原因 | 决策人 |
|:---|:---|:---|:---|
| — | Common 级元数据统一存储在 p_common_metadata 大宽表，不使用独立表 | 减少表数量，通过 metamodel_api_key 区分类型，新增元模型零 DDL | 架构组 |
| — | Tenant 级使用独立快捷表（p_tenant_entity 等）而非共享 p_tenant_metadata | 高数据量元模型（item 23,819 条）需要独立索引和查询优化 | 架构组 |
| — | 禁止 ID 关联，统一使用 api_key | 跨环境迁移一致性，人类可读，支持 Module 打包分发 | 架构组 |
| — | 布尔字段统一 xxxFlg 后缀，禁止 enable*/is* 前缀 | 消除命名不一致，Java Integer 三值语义（null/0/1）优于 Boolean | 架构组 |
| — | DDL 同时兼容 MySQL 和 PostgreSQL | 多云部署需求，避免数据库锁定 | 架构组 |
| 2026-04-16 | role/department 注册为独立元模型，数据存在 p_tenant_role/p_tenant_department | 角色和部门是元数据（定义），不是业务数据，应与 checkRule/busiType 同级 | 架构组 |
| 2026-04-16 | user 保持 p_user 独立表（paas_auth），不迁移到 p_tenant_data | 认证安全列（phone/passport_id/密码相关）需要物理隔离和独立索引 | 架构组 |
| 2026-04-16 | 禁止使用 public schema，默认 schema 改为 paas_metarepo | 所有表必须在明确的 schema 中，public 保持为空 | 架构组 |
| 2026-04-16 | BFF 层禁止直连数据库，删除 server/ 目录 | 所有数据操作通过 Java 后端 REST 接口，前端通过 Vite 代理 | 架构组 |
