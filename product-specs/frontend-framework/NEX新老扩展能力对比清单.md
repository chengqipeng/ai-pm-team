# NEX 扩展系统 — 新老能力对比清单

> 日期：2026-04-15
> 老系统：xsy-neo-ui-component / neo-ui-common 中的 NEX V2（React 16 + MobX/MST + ComTree）
> 新系统：paas-front-platform / front-core 中的 NEX V3（React 19 + ESM + Sandbox）

---

## 一、架构层面对比

| 维度 | 老系统 NEX V2 | 新系统 NEX V3 | 差异说明 |
|------|-------------|-------------|---------|
| 代码格式 | JSON 配置 + 内联 JS 字符串 | ESM 模块（TypeScript 编译后） | 老系统用 JSON 描述扩展，逻辑写在字符串里；新系统是标准 TS/ESM 模块 |
| 渲染引擎 | ComTree + XNode 树 + Amis 低代码引擎 | SchemaRenderer（自研轻量渲染器） | 老系统依赖 ComTree/Amis 两套渲染体系；新系统统一为 SchemaRenderer |
| 运行时注入 | NexRuntimeManager 动态注入（AOP 切面、事件、属性覆盖） | NexEngine 加载 ESM 模块，按生命周期钩子执行 | 老系统是运行时 monkey-patch；新系统是声明式钩子 |
| 配置合并 | NexMergeFactory 多源合并（设计器 + 运行时 + 默认，~1041 行） | 单一模块，无需合并 | 老系统有复杂的多源配置冲突解决；新系统一个实体+场景=一个模块 |
| 结构转换 | NexStructConverter（JSON → XNode 树，~2515 行） | 无需转换，ESM 模块直接导出标准接口 | 老系统需要 JSON→组件树的桥接层；新系统消除了这层 |
| 代码量 | extension/ 目录 ~10,000+ 行（合并引擎+结构转换+运行时+上下文+缓存+聚合+模板+常量+存储） | NexEngine ~100 行 + NexSandbox ~70 行 + 类型定义 ~90 行 | 新系统代码量减少 97% |

---

## 二、安全与隔离

| 维度 | 老系统 NEX V2 | 新系统 NEX V3 | 差异说明 |
|------|-------------|-------------|---------|
| 沙箱隔离 | ❌ 无隔离，扩展代码与主应用同一上下文执行 | ✅ 生产环境 iframe sandbox 隔离，开发环境 Blob URL | 老系统扩展代码可直接访问全局变量、DOM、window；新系统生产环境完全隔离 |
| 执行超时 | ❌ 无超时保护 | ✅ 10 秒超时自动终止 | 老系统扩展死循环会卡死页面；新系统有超时兜底 |
| 错误隔离 | ❌ 扩展错误可能阻断主流程 | ✅ try-catch 包裹，扩展错误不阻断主流程 | 新系统每个钩子执行都有错误捕获 |
| HTTP 访问 | ❌ 扩展可直接调用任意 API | ✅ 受限 HTTP 代理（仅 get/post，走主应用拦截器） | 新系统扩展的网络请求受控 |
| DOM 访问 | ❌ 可直接操作 DOM | ✅ 生产环境无法访问主应用 DOM | iframe sandbox 隔离了 DOM 访问 |

---

## 三、开发体验

| 维度 | 老系统 NEX V2 | 新系统 NEX V3 | 差异说明 |
|------|-------------|-------------|---------|
| 开发语言 | JSON 配置 + 内联 JavaScript 字符串 | TypeScript（设计器中编写，编译为 ESM） | 老系统在 JSON 里写 JS 字符串，无语法高亮、无自动补全；新系统是标准 TS |
| 类型安全 | ❌ 无类型检查 | ✅ `@front-platform/nex-types` 提供完整 API 类型 | 新系统编译期即可发现类型错误 |
| 调试能力 | ❌ 内联字符串无法断点调试 | ✅ Source Map 支持，DevTools 面板可断点 | 新系统开发环境用 Blob URL import，支持标准调试 |
| 代码编辑 | Admin 后台的 NEX 扩展管理页面（~2104 行，24 个文件） | 在线设计器（规划中），支持 TS 编辑 + 实时预览 | 老系统编辑器功能有限；新系统规划完整 IDE 体验 |
| 版本管理 | ❌ 无版本概念，覆盖式更新 | ✅ 服务端版本号 + 增量更新 | 新系统每个扩展有 version 字段，支持回滚 |
| 热更新 | 需要刷新页面 | 运行时动态加载/卸载（loadExtension/unloadExtension） | 新系统可不刷新页面更新扩展 |

---

## 四、扩展能力对比

### 4.1 生命周期钩子

| 钩子 | 老系统 NEX V2 | 新系统 NEX V3 | 说明 |
|------|-------------|-------------|------|
| 页面加载前 | ❌ 无 | ✅ `onBeforeMount` | 新增：可在页面渲染前执行初始化逻辑 |
| 页面加载后 | 通过 AOP 切面注入 `componentDidMount` | ✅ `onMounted` | 老系统通过 AOP hack；新系统是声明式钩子 |
| 页面卸载前 | 通过 AOP 切面注入 `componentWillUnmount` | ✅ `onBeforeUnmount` | 同上 |
| 数据加载后 | 通过事件监听 `dataLoaded` | ✅ `onDataLoaded(ctx, data)` | 老系统需手动监听事件；新系统直接声明 |
| 表单提交前 | 通过 AOP 切面拦截 `onSubmit` | ✅ `onBeforeSubmit(ctx, data)` → 返回 false 可阻断 | 新系统更直观，返回 false 即阻断 |
| 表单提交后 | 通过事件监听 `afterSubmit` | ✅ `onAfterSubmit(ctx, result)` | 同上 |

### 4.2 字段级扩展

| 能力 | 老系统 NEX V2 | 新系统 NEX V3 | 说明 |
|------|-------------|-------------|------|
| 字段可见性 | ✅ 通过属性覆盖 `visible` | ✅ `fields[apiKey].visible` (布尔值或函数) | 新系统支持动态函数 |
| 字段禁用 | ✅ 通过属性覆盖 `disabled` | ✅ `fields[apiKey].disabled` (布尔值或函数) | 同上 |
| 字段必填 | ❌ 需通过 AOP 修改校验逻辑 | ✅ `fields[apiKey].required` (布尔值或函数) | 新增：声明式必填控制 |
| 字段帮助文本 | ❌ 无 | ✅ `fields[apiKey].helpText` | 新增 |
| 字段值变更监听 | 通过事件监听 `fieldChange` | ✅ `fields[apiKey].onChange(ctx, value, oldValue)` | 新系统直接声明，自动绑定 |
| 自定义字段渲染 | 通过 ComTree 组件替换 | ✅ `fields[apiKey].render(ctx, props)` → ReactNode | 新系统更简洁，直接返回 JSX |

### 4.3 Schema / 布局扩展

| 能力 | 老系统 NEX V2 | 新系统 NEX V3 | 说明 |
|------|-------------|-------------|------|
| 布局修改 | NexStructConverter 转换 JSON → XNode 树，支持增删改节点 | ✅ `schemaPatch(schema, ctx)` → 返回修改后的 Schema | 老系统通过结构转换器；新系统通过纯函数补丁 |
| 多源配置合并 | ✅ NexMergeFactory 三源合并 + 冲突解决 | ✅ NexMerger 多模块按优先级合并 | 新系统支持同一 key 注册多模块，自动合并 |
| 配置模板 | ✅ NEX 模板系统（预定义配置模板） | ✅ NexTemplateRegistry | 新系统支持注册/查询/基于模板创建模块 |

### 4.4 操作按钮扩展

| 能力 | 老系统 NEX V2 | 新系统 NEX V3 | 说明 |
|------|-------------|-------------|------|
| 自定义按钮 | 通过 JSON 配置 actions 数组 | ✅ `actions[]` 数组，支持 key/label/icon/position/visible/onClick | 能力等价，新系统类型更安全 |
| 按钮位置 | toolbar / more | ✅ toolbar / more / inline | 新增 inline 位置（行内操作） |
| 按钮可见性 | 静态配置 | ✅ `visible(ctx)` 动态函数 | 新系统支持根据数据动态控制 |
| 异步操作 | ❌ 需手动处理 Promise | ✅ `onClick` 支持 async/await | 新系统原生支持异步 |

### 4.5 上下文 API

| API 域 | 老系统 NEX V2 | 新系统 NEX V3 | 说明 |
|--------|-------------|-------------|------|
| 实体信息 | 通过 NexContext 获取，结构不固定 | ✅ `ctx.entity` (apiKey, name, items) | 新系统结构固定、类型安全 |
| 表单操作 | 通过 ComTree XNode API 间接操作 | ✅ `ctx.form` (getValue/setValue/validate/submit/reset) | 新系统 API 更直观 |
| 列表操作 | 通过 EntityGrid store 间接操作 | ✅ `ctx.grid` (refresh/getSelectedRows/setFilter) | 同上 |
| 导航 | 通过 Navigator 全局单例 | ✅ `ctx.navigator` (openForm/openDetail/openDialog/openDrawer/goBack) | 新系统收敛到上下文内 |
| HTTP 请求 | 直接使用全局 axios 实例 | ✅ `ctx.http` (get/post，受限代理) | 新系统受控，走主应用拦截器 |
| 消息提示 | 通过全局 message 组件 | ✅ `ctx.util.message` (success/error/warning) | 新系统收敛到上下文内 |
| 确认弹窗 | 通过全局 Modal.confirm | ✅ `ctx.util.confirm(content)` → Promise | 同上 |
| 国际化 | 通过全局 i18n 函数 | ✅ `ctx.util.i18n(key, defaultValue)` | 同上 |
| 事件系统 | 通过 ComEventApi 全局事件 | ✅ `ctx.on(event, handler)` / `ctx.emit(event, payload)` | 新系统作用域隔离 |

---

## 五、作用域与粒度

| 维度 | 老系统 NEX V2 | 新系统 NEX V3 | 差异说明 |
|------|-------------|-------------|---------|
| 扩展粒度 | 组件级（任意 ComTree 节点可被扩展） | 实体+场景级 + 组件级（componentExtensions 按 schemaType/Key 扩展任意节点） | 新系统同时支持粗粒度和细粒度 |
| 场景类型 | 无明确场景概念，按组件类型区分 | ✅ 5 种场景：form / grid / detail / home / custom | 新系统场景明确 |
| 布局级扩展 | ❌ 无布局维度 | ✅ 支持 layoutApiKey，同一实体不同布局可有不同扩展 | 新增能力 |
| 多扩展叠加 | ✅ 多个 NEX 配置可叠加合并 | ✅ 同一 key 支持多模块注册，NexMerger 自动合并 | 能力对齐 |

---

## 六、老系统独有能力（已在 NEX V3 补齐）

| 能力 | 老系统实现 | 新系统实现 | 说明 |
|------|----------|----------|------|
| AOP 切面注入 | Aop.addComFx() 拦截任意组件方法 | ✅ `NexAopInterceptor` — before/after/around 三种 advice，`executeWithAop()` 执行拦截链 | before 返回 false 可阻断，around 手动调用 proceed() |
| 多扩展叠加 | NexMergeFactory 三源合并 + 冲突解决 | ✅ `NexMerger` — 同一 key 注册多模块，按 priority 排序后合并 hooks/fields/actions/schemaPatch/aop/componentExtensions | 低优先级先执行，高优先级后执行可覆盖 |
| 配置模板 | NEX 模板系统（预定义配置模板） | ✅ `NexTemplateRegistry` — register/listByScene/createFromTemplate | 深拷贝模板模块，ISV 基于模板快速创建扩展 |
| 配置缓存 | NexCache 本地缓存 + 版本缓存 | ✅ `NexCache` — TTL 过期 + 版本比对（isUpToDate），按 entity/scene/layout 三维缓存 | loadExtension 自动跳过已缓存的同版本 |
| 配置聚合 | NexAgg 多配置聚合 | ✅ 由 `NexMerger` 统一处理，hooks 链式执行、fields 深度合并、actions 按 key 去重、schemaPatch 链式调用 | 合并结果缓存在 mergedCache 中 |
| 组件级细粒度扩展 | 任意 ComTree XNode 可被扩展 | ✅ `NexComponentExtension` — 按 schemaType + schemaKey 匹配任意 Schema 节点，支持 props 覆盖、visible 控制、wrapper 包裹渲染 | `getComponentExtensions()` 返回匹配的扩展列表 |

---

## 七、新系统独有能力（老系统不具备）

| 能力 | 新系统实现 | 价值 |
|------|----------|------|
| iframe 沙箱隔离 | NexSandbox 生产环境 iframe sandbox | 扩展代码无法污染主应用，安全性质的飞跃 |
| TypeScript 类型安全 | 完整类型定义 + 编译期检查 | 开发期发现错误，减少运行时 bug |
| Source Map 调试 | 开发环境 Blob URL + Source Map | 扩展代码可断点调试 |
| 执行超时保护 | 10 秒超时自动终止 | 防止扩展死循环卡死页面 |
| 声明式字段必填控制 | `fields[apiKey].required` | 无需 AOP hack |
| 自定义字段渲染器 | `fields[apiKey].render()` → ReactNode | 直接返回 JSX，无需 ComTree 组件注册 |
| 布局级扩展隔离 | layoutApiKey 维度 | 同一实体不同布局可有不同扩展逻辑 |
| 版本管理 + 增量更新 | version 字段 + 后端版本存储 | 支持回滚、灰度发布 |
| 运行时热加载/卸载 | loadExtension / unloadExtension | 不刷新页面即可更新扩展 |
| 行内操作按钮 | `actions[].position: 'inline'` | 列表行内操作扩展 |

---

## 八、迁移风险评估

| 风险项 | 影响 | 缓解措施 |
|--------|------|---------|
| AOP 语义差异 | 老系统 AOP 可拦截任意 class 方法，新系统按 target 字符串匹配 | 梳理现有 AOP 用例，映射到 before/after/around target |
| ISV 扩展代码迁移 | 现有 JSON 配置格式与新 ESM 模块不兼容 | 提供迁移工具，将 JSON 配置转换为 TS 模块 |
| 老系统 NexContext API 差异 | 老系统通过 ComTree API 操作，新系统通过 ctx 对象 | 提供 API 映射文档 |
