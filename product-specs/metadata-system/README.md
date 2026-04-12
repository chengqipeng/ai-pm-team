# 元数据系统 — 文档与脚本索引

## 一、设计文档（7 个）

按阅读顺序：

| # | 文档 | 内容 | 行数 |
|:---:|:---|:---|:---:|
| 1 | [产品-方案设计](产品-方案设计.md) | 产品定位、量化目标、信息架构 | 218 |
| 2 | [元模型设计体系](元模型设计体系.md) | **核心**：三层架构、4 张核心表（p_meta_model/item/link/option）、字段映射规则、Common/Tenant 合并、读写路由、字段类型体系 | 942 |
| 3 | [元数据实例详细设计](元数据实例详细设计.md) | 27 个元模型的业务实例设计、数据规模、层级关系 | 685 |
| 4 | [元数据设计规范](元数据设计规范.md) | 命名规范、编码规范、关联规范 | 324 |
| 5 | [业务数据大宽表设计](业务数据大宽表设计.md) | p_tenant_data 表结构、分表策略（2000 张）、CRUD 流程、索引、API | 1348 |
| 6 | [数据迁移方案](数据迁移方案.md) | Common 级元数据迁移（已完成 99%）、脚本清单、数据质量清理规则 | 202 |
| 7 | [业务数据同步完整方案](业务数据同步完整方案.md) | **主方案**：Phase 0~3 全流程、逐类型转换逻辑、公式验证、Tenant 元数据同步 | 2256 |

## 二、元模型定义（models/ — 16 个）

每个元模型一个文件，定义字段映射、存储路由、层级关系、业务规则。

核心元模型：`entity.md` → `item.md` → `pick-option.md` / `entity-link.md` / `check-rule.md` / `compute-formula.md`

## 三、迁移细则（migration/ — 7 个）

每个元模型的具体迁移 SQL：api_key 命名统一、itemType 编码转换、ID→apiKey 转换。

## 四、计算公式文档（compute-formula/ — 8 个）

| 文档 | 内容 |
|:---|:---|
| [03-详细计算逻辑](../compute-formula/03-详细计算逻辑.md) | 新建/更新/批量/实时计算的完整流程 |
| [04-接口设计与实现要点](../compute-formula/04-接口设计与实现要点.md) | ComputePipeline 接口定义 |
| [05-异常处理设计](../compute-formula/05-异常处理设计.md) | 异常体系、错误码 |
| [07-数据迁移与计算验证报告](../compute-formula/07-数据迁移与计算验证报告.md) | account 公式验证结果 |
| [08-详细设计与新老对比](../compute-formula/08-详细设计与新老对比.md) | **核心**：新老系统架构对比、6 个核心类设计 |
| [09-业务数据批量操作详细设计](../compute-formula/09-业务数据批量操作详细设计.md) | 批量操作设计 |
| [公式函数新老对比分析](../compute-formula/公式函数新老对比分析.md) | 70 个函数逐个对比，100% 覆盖 |
| [公式函数验证测试设计](../compute-formula/公式函数验证测试设计.md) | 10 个测试公式（覆盖 21 种函数） |

## 五、同步脚本（sync/ — 统一入口 `run_sync.py`）

```bash
python3 run_sync.py <command>
```

| 命令 | 功能 |
|:---|:---|
| `verify-meta` | 元数据 9 项验证 |
| `build-mappings` | 构建映射表 |
| `sync-tenant-meta` | Tenant 级元数据同步 |
| `sync-biz-data` | 业务数据同步 |
| `verify-biz-data` | 业务数据验证 |
| `verify-formulas` | 公式引擎验证（13 公式 × 100 条） |
| `setup-formula-test` | 补充测试公式元数据 |
| `all` | 全流程 |

## 六、Java 测试

```bash
cd repos/apass_new_projects/paas-platform-service
mvn test -pl paas-platform-service-server -Dtest="AllFunctionsTest*,ComplexMixedFormulaTest,MixedFormulaValidationTest"
```

146 用例全部通过（88 函数类 + 33 复杂公式 + 25 语法验证）。

## 七、当前状态

| 项目 | 状态 |
|:---|:---|
| Common 级元数据迁移 | ✅ 99%（46,814 条） |
| Tenant 级元数据同步 | ✅ 548 条（5 实体） |
| 公式函数覆盖 | ✅ 70/70 |
| Python 公式验证 | ✅ 1300 次 100% |
| Java 测试 | ✅ 146 用例通过 |
| 业务数据同步 | ⏳ 待执行 |
