# 新老系统实体配置 CRUD 对比分析

> 日期：2026-04-24
> 老系统源码：`apps-ingage-admin/XObjectAction.java`、`XItemAction.java`、`XCheckRuleAction.java`、`XDuplicateRuleAction.java`、`FieldSetAction.java`

---

## 一、实体管理（entity）

### 老系统逻辑（XObjectAction.java）

| 操作 | URL | 核心逻辑 | 新系统是否覆盖 |
|:-----|:----|:---------|:-------------|
| 列表 | `/custom/entity-list` | License 检查（CRM-CM）→ 加载自定义实体 → SVG 图标映射 → Delta 权限 | ⚠️ 缺 License 检查 |
| 新建弹框 | `/custom/popup-entity-add` | 生成默认 apiKey（`getDefaultObjectApiKey`） | ⚠️ 缺默认 apiKey 生成 |
| 保存（新建） | `/custom/save-entity` | apiKey 追加 `__c` → 设置启用开关 → `saveObject(entity, item)` 创建实体+主属性 → 国际化同步 → 多态字段关联 → 保存 APP/Web 菜单 | ⚠️ 缺多态字段、国际化、菜单同步 |
| 保存（编辑） | `/custom/save-entity` | 加载 DB 实体 → 更新 label/description/iconId/开关 → `updateObject` → 多态字段增减处理 → 更新菜单 | ⚠️ 缺多态字段增减 |
| 删除 | `/custom/delete-entity` | 审批单引用检查 → 字段关联引用检查（`checkEntityFieldRelation`）→ `deleteObject` 级联删除 → 删除 APP/Canvas 菜单 | ⚠️ 缺引用检查 |
| 启用/禁用 | `/custom/set-entity-use-flg` | 审批单 Limit 检查 → 自定义按钮引用检查 → 字段关联引用检查（禁用时）→ `enableObject` | ⚠️ 缺引用检查 |
| 编辑标准实体 | `/custom/update-standard-entity` | 仅更新有限字段（标准实体不可删除/改 apiKey） | ❌ 未设计 |

### 差异清单

| # | 差异 | 老系统 | 新系统 | 优先级 | 说明 |
|:--|:-----|:-------|:-------|:-------|:-----|
| E1 | License 检查 | 检查 CRM-CM 模块 License | 未实现 | P2 | 依赖 License 服务 |
| E2 | 默认 apiKey 生成 | `getDefaultObjectApiKey()` 自动生成 `customEntity1` | 用户手动输入 | P1 | 可在前端自动生成 |
| E3 | apiKey `__c` 后缀 | 自动追加 | ✅ 已设计 | — | 一致 |
| E4 | 主属性字段创建 | `saveObject(entity, item)` 同时创建 | ✅ 已设计 | — | 一致 |
| E5 | 多态字段关联 | 新建/编辑时处理多态字段支持列表 | 未实现 | P2 | 复杂度高 |
| E6 | 国际化同步 | `customEntityMultiLangSyncAggService.syncResource` | 未实现 | P2 | 依赖 i18n 基础设施 |
| E7 | 菜单同步 | `saveAppMenu` + `saveWebMenu` | ✅ 已设计（menu 元数据） | — | 新系统走 menu 元数据 |
| E8 | 删除引用检查 | `checkEntityFieldRelation` + 审批单引用 + 自定义按钮引用 | 未实现 | **P0** | 必须有，防止误删 |
| E9 | 禁用引用检查 | 同上 | 未实现 | **P0** | 必须有 |
| E10 | 标准实体编辑 | `update-standard-entity` 限制可编辑字段 | 未区分标准/自定义的编辑权限 | P1 | 标准实体应限制编辑范围 |
| E11 | 启用开关确认 | 前端 JS confirm 弹框 | ✅ 已设计 | — | 一致 |
| E12 | 团队成员不可逆 | 前端 + 后端双重校验 | ✅ 前端已设计，后端未校验 | P1 | 需后端校验 |

---

## 二、字段管理（item）

### 老系统逻辑（XItemAction.java）

| 操作 | URL | 核心逻辑 | 新系统是否覆盖 |
|:-----|:----|:---------|:-------------|
| 列表 | `/custom/item-list` | 按 entity 加载字段 → 按 itemOrder 排序 → 区分系统/自定义 | ✅ 已覆盖 |
| 新建 | `/custom/save-item` | 处理 itemTypeProperty → 动态默认值 → Markdown 标记 → 关联筛选 → `createXItemNew` | ⚠️ 缺 itemTypeProperty 处理 |
| 编辑 | `/custom/update-item` | 更新 label/description/requireFlg 等 → 关联筛选更新 | ✅ 基本覆盖 |
| 删除 | `/custom/delete-item` | **级联引用检查**（6 种）→ `deleteXItemNew` | ⚠️ 缺引用检查 |
| 启用/禁用 | `/custom/set-item-use-flg` | 引用检查 → `enableItem` | ⚠️ 缺引用检查 |

### 字段删除的引用检查（老系统 6 种）

| 检查项 | 错误码 | 说明 |
|:-------|:-------|:-----|
| 被查重规则引用 | `ERROR_ITEM_USED_BY_DUPLICATERULE` (110004) | 字段被查重规则的条件引用 |
| 被计算公式引用 | `ERROR_ITEM_USED_BY_COMPUTEFORMULA` | 字段被公式计算引用 |
| 被汇总聚合引用 | `ERROR_ITEM_USED_BY_COMPUTEAGGREGATE` | 字段被汇总计算引用 |
| 被 JOIN 引用 | `ERROR_ITEM_USED_BY_JOIN` (310002) | 字段被关联字段引用 |
| 被关联筛选引用 | `ERROR_ITEM_USED_BY_REFERFILTER` | 字段被关联过滤引用 |
| 通用引用检查 | `ERROR_ITEM_IS_USED` | 其他引用 |

### 差异清单

| # | 差异 | 老系统 | 新系统 | 优先级 |
|:--|:-----|:-------|:-------|:-------|
| I1 | itemTypeProperty 处理 | 解析 JSON 属性（format/startNumber 等） | **新系统已拆为独立字段，不需要 JSON 解析** | ✅ 已解决 |
| I2 | 动态默认值 | `initDynamicDefaultValue()` | 未实现 | P2 |
| I3 | Markdown 标记 | `initMarkdownValue()` | 未实现 | P2 |
| I4 | 关联筛选（referFilter） | 新建/编辑时处理 | 未实现 | P1 |
| I5 | 删除引用检查（6 种） | 完整检查 | **未实现** | **P0** |
| I6 | apiKey `__c` 后缀 | 自定义字段追加 | 未实现 | P1 |
| I7 | 字段类型限制 | 编辑时 itemType 不可改 | ✅ 已设计 | — |
| I8 | 字段数量限制 | `tenantLimitValueService` 检查 | 未实现 | P1 |
| I9 | 选项值管理 | SELECT/MULTI_SELECT 类型的 pickOption CRUD | 未实现 | **P0** |

---

## 三、校验规则（checkRule）

### 老系统逻辑（XCheckRuleAction.java）

| 操作 | URL | 核心逻辑 | 新系统是否覆盖 |
|:-----|:----|:---------|:-------------|
| 列表 | `/paas/checkRule/list` | 按 entity 加载 → 数量限制检查 → Delta 权限 | ✅ 基本覆盖 |
| 新建 | `/paas/checkRule/save-rule` | **表达式编译校验** → apiKey 重复检查 → apiKey 追加 `__c` → `createCheckRule` | ⚠️ 缺表达式校验 |
| 编辑 | `/paas/checkRule/edit` | 更新公式/激活状态/错误提示 → **表达式编译校验** → `updateCheckRule` | ⚠️ 缺表达式校验 |
| 删除 | `/paas/checkRule/delete` | `deleteCheckRule` | ✅ 已覆盖 |

### 差异清单

| # | 差异 | 老系统 | 新系统 | 优先级 |
|:--|:-----|:-------|:-------|:-------|
| C1 | 表达式编译校验 | `commonCheckExpression` → `xComputeService.compileCheckRule` | **未实现** | **P0** |
| C2 | apiKey `__c` 后缀 | 自动追加 | 未实现 | P1 |
| C3 | apiKey 重复检查 | `getByApiKey` 查重 | 未实现（依赖后端 batchSave 校验） | P1 |
| C4 | 规则数量限制 | `tenantLimitValueService`（默认 20 条） | 未实现 | P1 |
| C5 | $USER 变量替换 | 表达式中 `$USER` 替换为实际字段 | 未实现 | P2 |
| C6 | 错误位置配置 | `checkErrorLocation`（页面顶部/字段旁） | ✅ 已设计 | — |
| C7 | 弱校验类型 | `checkErrorWay`（阻止/警告） | 未在弹框中暴露 | P2 |

---

## 四、查重规则（duplicateRule）

### 老系统逻辑（XDuplicateRuleAction.java）

| 操作 | URL | 核心逻辑 | 新系统是否覆盖 |
|:-----|:----|:---------|:-------------|
| 列表 | `/paas/duplicateRule/list` | 按 entity 加载 → 疑似查重规则（Lead/Contact/Opportunity/Account 特殊处理）→ AI 智能查重配置 → 数量限制（默认 5 条） | ⚠️ 缺疑似查重、AI 查重 |
| 新建页面 | `/paas/duplicateRule/to-add-rule-page` | 生成默认 apiKey → 加载可选字段（过滤不支持的类型） | ⚠️ 缺字段类型过滤 |
| 保存 | `/paas/duplicateRule/save-rule` | 保存规则 + 条件 + 匹配规则 | ✅ 基本覆盖 |
| 删除 | `/paas/duplicateRule/delete` | 级联删除条件和匹配规则 | ✅ 已覆盖（后端级联） |

### 查重条件的字段类型过滤（老系统）

老系统在选择查重字段时，过滤掉以下类型：
- 不支持的 itemType（非 TEXT/SELECT/NUMBER/DATE/PHONE/EMAIL/URL 等）
- 日期时间模式的日期字段
- 复合子字段（compoundSub）
- 扩展长文本/扩展 URL
- 自动编号（非主属性时）
- 工作流阶段字段
- 锁定状态/审批状态字段

### 差异清单

| # | 差异 | 老系统 | 新系统 | 优先级 |
|:--|:-----|:-------|:-------|:-------|
| D1 | 疑似查重规则 | Lead/Contact/Opportunity/Account 各有独立的疑似查重 | 未实现 | P2 |
| D2 | AI 智能查重 | Opportunity 支持 AI Prompt 配置 | 未实现 | P3 |
| D3 | 字段类型过滤 | 过滤不支持查重的字段类型 | **未实现** | **P0** |
| D4 | 规则数量限制 | 默认 5 条（`tenantLimitValueService`） | 未实现 | P1 |
| D5 | apiKey `__c` 后缀 | 自动追加 | 未实现 | P1 |
| D6 | 条件子表管理 | 弹框内嵌条件编辑 | ✅ 已设计 | — |
| D7 | 匹配规则子表 | 模糊匹配时的匹配规则配置 | 未在弹框中暴露 | P1 |

---

## 五、字段组（fieldSet）

### 老系统逻辑（FieldSetAction.java）

| 操作 | URL | 核心逻辑 | 新系统是否覆盖 |
|:-----|:----|:---------|:-------------|
| 列表 | `/fieldset/list` | 按 entity 加载字段组 | ✅ 已覆盖 |
| 新建 | `/fieldset/save-fieldset` | apiKey 追加 `__c` → apiKey 重复检查 → 特殊场景校验（复制场景字段限制）→ 创建字段组 + 成员 | ⚠️ 缺特殊场景校验 |
| 编辑 | `/fieldset/update-fieldset` | 更新字段组 + 成员 → 产品 picker 字段集数量限制（≤10） | ⚠️ 缺数量限制 |
| 删除 | `/fieldset/delete` | 直接删除（级联删除 fieldSetItem） | ✅ 已覆盖 |

### 差异清单

| # | 差异 | 老系统 | 新系统 | 优先级 |
|:--|:-----|:-------|:-------|:-------|
| F1 | apiKey `__c` 后缀 | 自动追加（特殊租户除外） | 未实现 | P1 |
| F2 | apiKey 重复检查 | `isApiKeyExistFlg` | 未实现（依赖后端 batchSave） | P1 |
| F3 | 复制场景字段限制 | `FIELDS_NOT_COPY` apiKey 不能包含标准字段 | 未实现 | P2 |
| F4 | 产品 picker 数量限制 | 最多 10 个字段 | 未实现 | P2 |
| F5 | 字段组成员管理 | 勾选字段 + 排序 | ✅ 已设计 | — |
| F6 | 特殊租户处理 | Lenovo 租户不追加 `__c` | 未实现 | P3 |

---

## 六、P0 差异汇总（必须补充）

| # | 模块 | 差异 | 影响 | 修复方案 |
|:--|:-----|:-----|:-----|:---------|
| **E8** | 实体 | 删除引用检查 | 误删实体导致关联数据断裂 | 后端 `batchSaveMetadata` 的 deleteMap 增加引用检查 |
| **E9** | 实体 | 禁用引用检查 | 禁用后关联功能异常 | 同上 |
| **I5** | 字段 | 删除引用检查（6 种） | 误删字段导致公式/查重/汇总失效 | 后端 `batchSaveMetadata` 的 deleteMap 增加引用检查 |
| **I9** | 字段 | 选项值管理 | SELECT/MULTI_SELECT 字段无法配置选项 | 前端 ItemFormDialog 增加选项值编辑区域 |
| **C1** | 校验规则 | 表达式编译校验 | 无效公式保存后运行时报错 | 后端新增 `/metadata/check-formula/validate` 接口 |
| **D3** | 查重规则 | 字段类型过滤 | 选择不支持查重的字段类型 | 前端弹框中过滤字段下拉列表 |

---

## 七、P1 差异汇总（建议补充）

| # | 模块 | 差异 | 修复方案 |
|:--|:-----|:-----|:---------|
| E2 | 实体 | 默认 apiKey 生成 | 前端自动生成 `customEntity{N}` |
| E10 | 实体 | 标准实体编辑限制 | 前端根据 namespace 限制可编辑字段 |
| E12 | 实体 | 团队成员后端校验 | 后端 batchSave 校验 groupMemberFlg 不可从 1→0 |
| I1 | 字段 | itemTypeProperty → 独立字段 | **新系统已拆分，无需处理**（format/startNumber/dateMode 等已是独立 dbc 列） |
| I4 | 字段 | 关联筛选 | 前端弹框增加关联筛选配置区域 |
| I6 | 字段 | apiKey `__c` 后缀 | 前端自动追加 |
| I8 | 字段 | 字段数量限制 | 后端 batchSave 校验 |
| C2 | 校验规则 | apiKey `__c` 后缀 | 前端自动追加 |
| C3 | 校验规则 | apiKey 重复检查 | 后端 batchSave 校验 |
| C4 | 校验规则 | 规则数量限制 | 后端 batchSave 校验（默认 20 条） |
| D4 | 查重规则 | 规则数量限制 | 后端 batchSave 校验（默认 5 条） |
| D5 | 查重规则 | apiKey `__c` 后缀 | 前端自动追加 |
| D7 | 查重规则 | 匹配规则子表 | 前端弹框增加匹配规则配置 |
| F1 | 字段组 | apiKey `__c` 后缀 | 前端自动追加 |
| F2 | 字段组 | apiKey 重复检查 | 后端 batchSave 校验 |
