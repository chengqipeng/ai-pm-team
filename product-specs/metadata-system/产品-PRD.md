# aPaaS 元数据驱动平台体系建设 — PRD

> 版本：v2.0 | 日期：2026-03-31
> 前置文档：[需求澄清](产品-需求澄清.md) | [方案设计](产品-方案设计.md)
> 需求类型：`架构重构` | 特征标签：`数据模型变更`、`跨租户/权限`

---

## 一、业务全景

### 价值描述
平台从硬编码建表模式升级为元模型驱动架构后，产品配置师和租户管理员可以通过可视化界面配置业务对象、字段、校验规则，无需开发介入即可完成业务扩展。出厂元数据与租户自定义元数据独立存储、独立升级，彻底消除升级时的全量回归问题。

### 量化目标
| 指标 | 当前值 | 目标值 | 衡量方式 |
|:---|:---:|:---:|:---|
| 新增业务对象耗时 | 2-4 周 | 10 分钟 | 配置到可用的端到端时间 |
| 字段类型映射异常 | 月均 5-8 次 | 0 | 前端渲染异常工单数 |
| 跨环境迁移失败率 | 15% | <1% | api_key 关联后迁移成功率 |
| 元数据列表查询 | 未统计 | P95 < 200ms | APM 监控 |
| 元数据合并读取 | 未统计 | P95 < 500ms | APM 监控 |
| 元数据写入 | 未统计 | P95 < 1s | APM 监控 |

### 范围（按优先级）
| 优先级 | 功能点 |
|:---|:---|
| P0（MVP） | 元模型四表体系、大宽表存储、合并读取引擎、CRUD API、数据迁移、Schema 校验、管理前端浏览 |
| P1（V1） | 元数据变更日志、管理前端编辑、字段映射可视化、ItemTypeEnum 映射展示 |
| P2（V2） | 计算字段子元模型恢复、Delta 增量覆盖、Module 打包分发 |

### 角色与权限
| 角色 | 核心操作 | License/权限 |
|:---|:---|:---|
| 平台管理员 | 元模型注册、Common 元数据初始化、全部管理功能 | 平台级权限 |
| 租户管理员 | Tenant 级元数据 CRUD、自定义对象/字段/选项值 | 租户管理员权限 |
| 业务开发者 | 通过 API 读取元数据驱动业务逻辑 | API 调用权限 |
| 产品配置师 | 可视化配置业务对象、字段、校验规则 | 配置管理权限 |

---

## 二、信息架构

```
aPaaS 元数据驱动平台
├── 元模型定义层（Schema）【核心新建】
│   ├── p_meta_model（元模型注册）
│   ├── p_meta_item（字段定义 + db_column 映射）
│   ├── p_meta_link（元模型间关联）
│   └── p_meta_option（字段取值约束）
├── 元数据实例层（Data）【核心新建】
│   ├── Common 级（p_common_metadata 大宽表）
│   └── Tenant 级（p_tenant_* 独立快捷表 / p_tenant_metadata 共享表）
├── 合并引擎【核心新建】
│   ├── CommonMetadataConverter（大宽表行 ↔ 业务 Entity 转换）
│   ├── MergeReadService（Common + Tenant 合并）
│   └── DynamicTableNameHolder（写入路由）
├── API 层【核心新建】
│   ├── MetaRepoReadApi（6 个读接口）
│   ├── MetaRepoWriteApi（6 个写接口）
│   └── MetamodelBrowseApiService（内部浏览接口）
└── 管理前端 metarepo-web【新建】
    ├── 元模型列表/详情
    ├── 元数据浏览（按 entity 分组）
    ├── 元数据编辑（Tenant 级）【P1】
    └── 字段映射可视化【P1】
```

---

## 三、详细功能设计

### 3.1 元模型管理

**业务规则：**
- BR-01：api_key 全局唯一，camelCase 格式
- BR-02：必须指定 enable_common 和 enable_tenant（至少一个为 1）
- BR-03：db_table 指向 Tenant 级存储表，格式 p_tenant_{name}
- BR-04：新表结构必须与 p_common_metadata 一致（+ tenant_id）
- BR-05：元模型注册后，可通过 p_meta_item 定义字段，无需建新表即可存储元数据

**元模型字段定义规则：**
- BR-06：db_column 三种映射方式——固定列名 / dbc_xxxN 扩展列 / 特殊映射
- BR-07：固定列优先（api_key、label、namespace 等直接映射）
- BR-08：dbc 列按 Java 字段数据类型选择前缀（varchar/textarea/int/smallint/bigint/decimal）
- BR-09：同一元模型内同前缀按 item_order 递增分配序号
- BR-10：不同元模型的 dbc 列序号独立分配，互不冲突
- BR-11：列名格式统一 dbc_xxxN（无下划线分隔数字）

### 3.2 元数据 CRUD

**业务规则：**
- BR-12：读取时 enable_common=1 且 enable_tenant=1 → 先查 Common 再查 Tenant，合并返回
- BR-13：合并规则——Common 有 Tenant 无→用 Common，同 apiKey→Tenant 覆盖，Tenant delete_flg=1→隐藏
- BR-14：namespace=product 需检查 license，无权限则隐藏
- BR-15：所有写操作仅写入 Tenant 级表，Common 级由平台初始化写入
- BR-16：写入前校验 p_meta_option 定义的取值范围
- BR-17：写入前校验 p_meta_item 定义的必填/唯一约束
- BR-18：删除 Common 数据 → 插入 delete_flg=1 的 Tenant 记录（遮蔽删除）
- BR-19：级联删除遵循 p_meta_link.cascade_delete 配置

**读接口（MetaRepoReadApi）：**
| 方法 | 路径 | 参数 | 返回 |
|:---|:---|:---|:---|
| listEntities | GET /metarepo/read/entities | tenantId(header) | List\<XEntity\> |
| getEntity | GET /metarepo/read/entity | apiKey | XEntity |
| listItems | GET /metarepo/read/items | entityApiKey | List\<XEntityItem\> |
| listPickOptions | GET /metarepo/read/pick-options | entityApiKey, itemApiKey | List\<XPickOption\> |
| listCheckRules | GET /metarepo/read/check-rules | entityApiKey | List\<XCheckRule\> |
| listEntityLinks | GET /metarepo/read/entity-links | entityApiKey | List\<XLink\> |

**写接口（MetaRepoWriteApi）：**
| 方法 | 路径 | 参数 | 说明 |
|:---|:---|:---|:---|
| createEntity | POST /metarepo/write/entity | XEntity body | 创建 Tenant 级对象 |
| updateEntity | PUT /metarepo/write/entity | XEntity body | Tenant 覆盖 Common |
| deleteEntity | DELETE /metarepo/write/entity | apiKey | 遮蔽删除 + 级联 |
| createItem | POST /metarepo/write/item | XEntityItem body | 创建字段 |
| updateItem | PUT /metarepo/write/item | XEntityItem body | 更新字段 |
| deleteItem | DELETE /metarepo/write/item | apiKey, entityApiKey | 级联删除 pickOption/referenceFilter |
