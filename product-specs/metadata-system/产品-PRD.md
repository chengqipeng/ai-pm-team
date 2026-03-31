# aPaaS 元数据体系 — PRD

## 1. 产品概述

| 维度 | 内容 |
|:---|:---|
| 产品名称 | aPaaS 元数据驱动平台 |
| 版本 | V1.0 |
| 目标 | 构建元模型驱动的三层元数据架构，实现业务对象声明式配置与动态扩展 |
| 核心交付 | 元模型四表体系 + 大宽表存储 + Common/Tenant 合并 + 元数据管理 API + 可视化管理前端 |

## 2. 功能清单

### 2.1 元模型管理

| 功能 | 优先级 | 说明 |
|:---|:---:|:---|
| 元模型注册 | P0 | 通过 p_meta_model 注册新元模型类型 |
| 元模型字段定义 | P0 | 通过 p_meta_item 定义元模型属性字段及 db_column 映射 |
| 元模型关联定义 | P0 | 通过 p_meta_link 定义元模型间父子/引用关系 |
| 元模型取值约束 | P0 | 通过 p_meta_option 定义枚举字段合法取值 |
| 元模型浏览 API | P0 | listMetaModels / listMetaItems / getColumnMapping |

### 2.2 元数据 CRUD

| 功能 | 优先级 | 说明 |
|:---|:---:|:---|
| 元数据读取（合并） | P0 | Common + Tenant 合并读取，namespace 过滤，license 控制 |
| 元数据创建 | P0 | Tenant 级创建，Schema 校验，DynamicTableNameHolder 路由 |
| 元数据更新 | P0 | Tenant 覆盖 Common（同 apiKey 覆盖） |
| 元数据删除 | P0 | 软删除 + 遮蔽删除（Common 数据插入 delete_flg=1 的 Tenant 记录） |
| 级联操作 | P0 | 删除 entity 级联删除 item/entityLink/checkRule，删除 item 级联删除 pickOption/referenceFilter |

### 2.3 元数据管理前端（metarepo-web）

| 功能 | 优先级 | 说明 |
|:---|:---:|:---|
| 元模型列表页 | P0 | 展示所有元模型，字段数、关联关系、存储配置 |
| 元模型详情页 | P0 | 字段定义列表，db_column 映射，取值约束展示 |
| 元数据浏览页 | P0 | 按 entity 分组浏览，Common/Tenant 来源标识 |
| 元数据编辑 | P1 | Tenant 级元数据的创建/更新/删除表单 |
| 字段映射可视化 | P1 | db_column → 大宽表物理列映射关系图 |
| ItemTypeEnum 映射 | P1 | 字段类型编码 → 名称 → dbColumnPrefix 对照表 |

### 2.4 数据迁移

| 功能 | 优先级 | 说明 |
|:---|:---:|:---|
| item_type 编码转换 | P0 | 老编码→新 ItemTypeEnum 编码（剩余 3,333 条） |
| db_column 重分配 | P0 | 按 entity 分组 + itemType 前缀递增分配 |
| 关联字段标准化 | P0 | ID 关联→api_key 关联 |
| globalPickItem 迁移 | P1 | ID→apiKey 引用转换 |

### 2.5 待恢复能力

| 功能 | 优先级 | 说明 |
|:---|:---:|:---|
| formulaCompute 子元模型 | P1 | 计算公式定义：公式表达式、空值处理、结果类型 |
| formulaComputeItem 子元模型 | P1 | 公式明细：引用的字段列表 |
| aggregationCompute 子元模型 | P1 | 汇总累计定义：汇总对象、汇总字段、汇总方式 |
| aggregationComputeDetail 子元模型 | P1 | 汇总条件明细：过滤条件 |
| computeFactor 子元模型 | P1 | 计算因子：公式/汇总共享变量定义 |
| Delta 增量覆盖 | P2 | enable_delta + delta_scope + delta_mode |
| Module 打包分发 | P2 | enable_package 元数据模块化 |

## 3. 业务规则

### 3.1 元模型注册规则
- api_key 全局唯一，camelCase 格式
- 必须指定 enable_common 和 enable_tenant（至少一个为 1）
- db_table 指向 Tenant 级存储表，格式 p_tenant_{name}
- 新表结构必须与 p_common_metadata 一致（CREATE TABLE ... LIKE + ALTER ADD tenant_id）

### 3.2 元模型字段定义规则
- db_column 三种映射：固定列名 / dbc_xxxN 扩展列 / 特殊映射
- 固定列优先：api_key、label、namespace 等直接映射
- dbc 列按 Java 字段数据类型选择前缀（varchar/textarea/int/smallint/bigint/decimal）
- 同一元模型内同前缀按 item_order 递增分配序号
- 不同元模型的 dbc 列序号独立分配
- 列名格式统一 dbc_xxxN（无下划线分隔数字）

### 3.3 元数据读取规则
- enable_common=1 且 enable_tenant=1：先查 Common，再查 Tenant，合并返回
- enable_common=1 且 enable_tenant=0：仅查 Common
- enable_common=0 且 enable_tenant=1：仅查 Tenant
- 合并规则：Common 有 Tenant 无→用 Common，同 apiKey→Tenant 覆盖，Tenant delete_flg=1→隐藏
- namespace=product 需检查 license

### 3.4 元数据写入规则
- 所有写操作仅写入 Tenant 级表
- Common 级数据由平台初始化或 Module 安装写入
- 写入前校验 p_meta_option 定义的取值范围
- 写入前校验 p_meta_item 定义的必填/唯一约束
- 删除 Common 数据：插入 delete_flg=1 的 Tenant 记录（遮蔽删除）
- 级联删除遵循 p_meta_link.cascade_delete 配置

### 3.5 namespace 规则
| namespace | 存储位置 | 写入方 | 可见性 |
|:---|:---|:---|:---|
| system | p_common_metadata | 平台初始化 | 所有租户 |
| product | p_common_metadata | Module 安装 | 受 license 控制 |
| custom | p_tenant_* | 租户管理员 | 仅该租户 |

### 3.6 国际化规则
- 所有文本字段必须有对应 xxxKey 国际化字段
- Key 格式：XdMDObj.{entityApiKey}、XdMDItem.{itemApiKey} 等
- 运行时通过 p_meta_i18n_resource 查找翻译

## 4. 字段类型体系（ItemTypeEnum）

| 编码 | 名称 | dbColumnPrefix | 说明 |
|:---:|:---|:---|:---|
| 1 | TEXT | dbc_varchar | 文本 |
| 2 | NUMBER | dbc_bigint | 数字 |
| 3 | DATE | dbc_bigint | 日期 |
| 4 | PICKLIST | dbc_int | 单选 |
| 5 | LOOKUP | dbc_bigint | 查找关联 |
| 6 | FORMULA | null | 公式（不占物理列） |
| 7 | ROLLUP | null | 汇总（不占物理列） |
| 8 | TEXTAREA | dbc_textarea | 长文本 |
| 9 | BOOLEAN | dbc_smallint | 布尔 |
| 10 | CURRENCY | dbc_decimal | 货币 |
| 11 | PERCENT | dbc_decimal | 百分比 |
| 12 | EMAIL | dbc_varchar | 邮箱 |
| 13 | PHONE | dbc_varchar | 电话 |
| 14 | URL | dbc_varchar | URL |
| 15 | DATETIME | dbc_bigint | 日期时间 |
| 16 | MULTIPICKLIST | dbc_varchar | 多选 |
| 17 | MASTER_DETAIL | dbc_bigint | 主从关联 |
| 18 | GEOLOCATION | dbc_varchar | 地理位置 |
| 19 | IMAGE | dbc_varchar | 图片 |
| 20 | AUTONUMBER | dbc_varchar | 自动编号 |
| 21 | JOIN | null | 引用（不占物理列） |
| 22 | AUDIO | dbc_varchar | 语音 |
| 27 | COMPUTED | null | 计算字段（不占物理列） |

## 5. 验收标准

### 5.1 元模型管理
- [ ] 可通过 p_meta_model 注册新元模型，无需建表即可存储元数据
- [ ] p_meta_item 字段定义完整覆盖 6 种元模型共 176 个字段
- [ ] p_meta_link 正确定义 5 条层级关系
- [ ] p_meta_option 正确约束 17 个枚举字段的 62 个选项值

### 5.2 元数据 CRUD
- [ ] 读取接口正确合并 Common + Tenant 数据
- [ ] 写入接口正确路由到 Tenant 级独立表
- [ ] 删除操作正确执行遮蔽删除和级联删除
- [ ] Schema 校验拦截非法取值

### 5.3 数据迁移
- [ ] 所有 item_type 编码转换为新 ItemTypeEnum
- [ ] 所有 db_column 格式统一为 dbc_xxxN
- [ ] 所有关联字段从 ID 转换为 api_key
- [ ] 迁移后业务功能回归通过

### 5.4 性能
- [ ] 元数据列表查询 P95 < 200ms
- [ ] 元数据合并读取 P95 < 500ms
- [ ] 元数据写入 P95 < 1s

### 5.5 前端
- [ ] 元模型列表正确展示所有已注册元模型
- [ ] 元数据浏览正确区分 Common/Tenant 来源
- [ ] ItemTypeEnum 映射从 API 加载，失败回退前端硬编码

## 6. 审核清单

| 检查项 | 状态 |
|:---|:---:|
| 业务规则完整且无歧义 | ⬜ |
| 接口规格可直接用于技术设计 | ⬜ |
| 字段类型体系覆盖所有业务场景 | ⬜ |
| 数据迁移方案可执行 | ⬜ |
| 验收标准可测试 | ⬜ |
| 性能指标明确 | ⬜ |
| 兼容性（MySQL + PostgreSQL）已考虑 | ⬜ |
