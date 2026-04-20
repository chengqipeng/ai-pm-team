# 元数据字段类型与 UI 组件映射规范

> 本文档定义了元模型字段类型（ItemTypeEnum）到前端 UI 组件的完整映射关系。
> 所有业务数据的表单页面、列表页面、详情页面必须按照本规范渲染字段。

## 1. 三层类型模型

```
itemType (UI 交互类型)
  └── itemSubType (真实数据类型，非计算型 = itemType)
        └── dataType (数据库存储类型)
              └── dbcPrefix (大宽表列前缀)
```

## 2. ItemTypeEnum 完整定义

| code | 枚举名 | 中文名 | dataType | dbc 列前缀 | 是否虚拟 |
|------|--------|--------|----------|-----------|---------|
| 1 | TEXT | 文本 | VARCHAR(1) | dbc_varchar | 否 |
| 2 | SELECT | 单选 | VARCHAR(1) | dbc_varchar | 否 |
| 3 | MULTI_SELECT | 多选 | VARCHAR(1) | dbc_varchar | 否 |
| 4 | TEXTAREA | 文本域 | TEXT(5) | dbc_textarea | 否 |
| 5 | NUMBER | 整数 | BIGINT(3) | dbc_bigint | 否 |
| 6 | CURRENCY | 实数/货币 | DECIMAL(4) | dbc_decimal | 否 |
| 7 | DATE | 日期 | BIGINT(3) | dbc_bigint | 否 |
| 8 | LAYOUT_LINE | 布局行 | — | — | 是 |
| 9 | AUTONUMBER | 自动编号 | VARCHAR(1) | dbc_varchar | 否 |
| 10 | RELATION_SHIP | 关联(Lookup) | BIGINT(3) | dbc_bigint | 否 |
| 11 | NUMBER_OLD | 整数(旧) | BIGINT(3) | dbc_bigint | 否 |
| 13 | PHONE_OLD | 电话(旧) | VARCHAR(1) | dbc_varchar | 否 |
| 15 | DATETIME_OLD | 日期时间(旧) | BIGINT(3) | dbc_bigint | 否 |
| 16 | MULTI_TAG | 多选标签 | VARCHAR(1) | dbc_varchar | 否 |
| 22 | PHONE | 电话 | VARCHAR(1) | dbc_varchar | 否 |
| 23 | EMAIL | 邮箱 | VARCHAR(1) | dbc_varchar | 否 |
| 24 | URL | 网址 | VARCHAR(1) | dbc_varchar | 否 |
| 26 | JOIN | 引用类型 | — | — | 是 |
| 27 | FORMULA | 计算类型 | — | — | 是 |
| 29 | IMAGE | 图片 | VARCHAR(1) | dbc_varchar | 否 |
| 31 | BOOLEAN | 布尔型 | SMALLINT(6) | dbc_smallint | 否 |
| 32 | GEO | 地理定位 | VARCHAR(1) | dbc_varchar | 否 |
| 33 | PERCENT | 百分比 | DECIMAL(4) | dbc_decimal | 否 |
| 34 | MULTI_RELATION | 多态关联 | BIGINT(3) | dbc_bigint | 否 |
| 38 | DATETIME | 时间 | BIGINT(3) | dbc_bigint | 否 |
| 39 | FILE | 文件 | VARCHAR(1) | dbc_varchar | 否 |
| 40 | RICHTEXT | 富文本 | TEXT(5) | dbc_textarea | 否 |
| 41 | MASTER_DETAIL | 多值关联 | BIGINT(3) | dbc_bigint | 否 |
| 99 | DIMENSION | 维度 | — | — | 是 |

## 3. DataType 存储类型

| code | 枚举名 | SQL 类型 | dbc 列前缀 | Java 类型 |
|------|--------|---------|-----------|----------|
| 1 | VARCHAR | VARCHAR(300) | dbc_varchar | String |
| 2 | INT | INTEGER | dbc_int | Integer |
| 3 | BIGINT | BIGINT | dbc_bigint | Long |
| 4 | DECIMAL | DECIMAL(20,4) | dbc_decimal | BigDecimal |
| 5 | TEXT | TEXT | dbc_textarea | String |
| 6 | SMALLINT | SMALLINT | dbc_smallint | Integer |

## 4. UI 组件映射规范

### 4.1 表单组件（编辑/新建）

| itemType | 组件类型 | HTML 元素 | 输入约束 | 说明 |
|----------|---------|----------|---------|------|
| 1 (TEXT) | 单行文本框 | `<input type="text">` | maxLength=300 | 默认文本输入 |
| 2 (SELECT) | 下拉单选 | `<select>` | 选项来自 pickOption | 选项值从元数据加载 |
| 3 (MULTI_SELECT) | 多选复选框组 | `<checkbox-group>` | 选项来自 pickOption | 多选，值以逗号分隔存储 |
| 4 (TEXTAREA) | 多行文本域 | `<textarea rows="3">` | 无长度限制 | 长文本 |
| 5 (NUMBER) | 数字输入框 | `<input type="number">` | step=1, 整数 | 不允许小数 |
| 6 (CURRENCY) | 数字输入框 | `<input type="number">` | step=0.01, 小数位由 decimal 字段控制 | 显示千分位 |
| 7 (DATE) | 日期选择器 | `<input type="date">` | 存储为毫秒时间戳 | 仅日期，无时间 |
| 8 (LAYOUT_LINE) | 分隔线 | `<hr>` + 标题 | — | 不渲染输入框，仅作为表单分组标题 |
| 9 (AUTONUMBER) | 只读文本 | `<input readonly>` | 系统自动生成 | 不可编辑 |
| 10 (RELATION_SHIP) | 关联选择器 | 弹窗选择 / 搜索下拉 | referEntityApiKey 指定目标实体 | 存储关联记录 ID |
| 11 (NUMBER_OLD) | 数字输入框 | `<input type="number">` | 同 NUMBER(5) | 旧编码兼容 |
| 13 (PHONE_OLD) | 电话输入框 | `<input type="tel">` | 同 PHONE(22) | 旧编码兼容 |
| 15 (DATETIME_OLD) | 日期时间选择器 | `<input type="datetime-local">` | 同 DATETIME(38) | 旧编码兼容 |
| 16 (MULTI_TAG) | 标签输入 | 标签组件 | 多值，逗号分隔 | 自由输入标签 |
| 22 (PHONE) | 电话输入框 | `<input type="tel">` | pattern 校验手机号 | 显示拨号图标 |
| 23 (EMAIL) | 邮箱输入框 | `<input type="email">` | 浏览器内置邮箱校验 | 显示邮件图标 |
| 24 (URL) | 网址输入框 | `<input type="url">` | 浏览器内置 URL 校验 | 可点击跳转 |
| 26 (JOIN) | 只读引用 | 只读文本 | — | 虚拟字段，不可编辑 |
| 27 (FORMULA) | 只读计算 | 只读文本 | — | 虚拟字段，不可编辑 |
| 29 (IMAGE) | 图片上传 | 文件上传组件 | accept="image/*" | 预览缩略图 |
| 31 (BOOLEAN) | 是/否单选 | 单选按钮组 | 值为 "0"(否) / "1"(是) | 不用文本框 |
| 32 (GEO) | 地理定位 | 地图选点组件 | — | 存储经纬度 JSON |
| 33 (PERCENT) | 百分比输入 | `<input type="number">` | step=0.01, suffix="%" | 显示百分号 |
| 34 (MULTI_RELATION) | 多态关联选择器 | 弹窗选择 | referEntityApiKeys 指定候选实体 | 多态 |
| 38 (DATETIME) | 日期时间选择器 | `<input type="datetime-local">` | 存储为毫秒时间戳 | 日期 + 时间 |
| 39 (FILE) | 文件上传 | 文件上传组件 | — | 显示文件名和大小 |
| 40 (RICHTEXT) | 富文本编辑器 | 富文本组件 | — | Markdown 或 HTML |
| 41 (MASTER_DETAIL) | 子表格 | 内嵌表格组件 | — | 主从关系 |
| 99 (DIMENSION) | 不渲染 | — | — | 虚拟字段 |

### 4.2 列表组件（只读展示）

| itemType | 展示方式 | 格式化规则 |
|----------|---------|-----------|
| 1 (TEXT) | 纯文本 | 超长截断 + tooltip |
| 2 (SELECT) | 选项标签 | 显示 label，不显示 code |
| 3 (MULTI_SELECT) | 标签组 | 多个标签并排 |
| 4 (TEXTAREA) | 截断文本 | 最多显示 2 行 |
| 5 (NUMBER) | 数字 | 千分位格式化 |
| 6 (CURRENCY) | 金额 | 千分位 + 小数位 + 币种符号 |
| 7 (DATE) | 日期 | yyyy-MM-dd |
| 9 (AUTONUMBER) | 纯文本 | 等宽字体 |
| 10 (RELATION_SHIP) | 链接 | 显示关联记录 name，可点击跳转 |
| 22 (PHONE) | 电话 | 等宽字体，可点击拨号 |
| 23 (EMAIL) | 邮箱 | 可点击发邮件 |
| 24 (URL) | 链接 | 可点击跳转 |
| 29 (IMAGE) | 缩略图 | 32×32 圆角 |
| 31 (BOOLEAN) | 状态标签 | 是=绿色标签，否=灰色标签 |
| 33 (PERCENT) | 百分比 | 数字 + % |
| 38 (DATETIME) | 日期时间 | yyyy-MM-dd HH:mm |
| 39 (FILE) | 文件图标 | 图标 + 文件名 |

### 4.3 详情组件（只读展示，比列表更完整）

与列表组件一致，但不截断文本，完整展示所有内容。

## 5. 字段属性对 UI 的影响

| 元数据属性 | 类型 | 对 UI 的影响 |
|-----------|------|-------------|
| requireFlg | 0/1 | 1=必填，label 后显示红色 `*`，提交时校验非空 |
| enableFlg | 0/1 | 0=禁用，表单和列表中不显示 |
| hiddenFlg | 0/1 | 1=隐藏，表单和列表中不显示 |
| deleteFlg | 0/1 | 1=已删除，任何地方不显示 |
| creatable | 0/1 | 0=新建时不可赋值，新建表单中该字段只读 |
| updatable | 0/1 | 0=不可更新，编辑表单中该字段只读 |
| readonlyStatus | 0-3 | 0=始终可编辑, 1=管理员可编辑, 2=系统只读, 3=完全只读 |
| visibleStatus | 0-3 | 0=不可见, 1=管理员可见, 2=系统可见, 3=所有人可见 |
| maxLength | int | 文本类输入框的 maxLength 属性 |
| minLength | int | 文本类输入框的 minLength 属性（提交时校验） |
| defaultValue | string | 新建时的默认值 |
| itemOrder | int | 字段在表单/列表中的排序顺序（升序） |
| customFlg | 0/1 | 1=租户自定义字段，表单中显示"自定义"标签 |
| description | string | 输入框的 placeholder 或 tooltip |
| helpText | string | 字段下方的帮助说明文字 |

## 6. 前端 TypeScript 映射函数

```typescript
/**
 * 根据元数据 itemType 返回表单组件类型。
 * 所有业务数据表单页面必须使用此函数确定组件类型。
 */
function resolveFormComponent(itemType: number): string {
  switch (itemType) {
    case 1:  return 'text';           // 单行文本
    case 2:  return 'select';         // 下拉单选
    case 3:  return 'multi-select';   // 多选
    case 4:  return 'textarea';       // 文本域
    case 5:  return 'number';         // 整数
    case 6:  return 'currency';       // 实数/货币
    case 7:  return 'date';           // 日期
    case 8:  return 'layout-line';    // 分隔线（不渲染输入框）
    case 9:  return 'readonly';       // 自动编号（只读）
    case 10: return 'relation';       // 关联选择器
    case 11: return 'number';         // 整数（旧编码）
    case 13: return 'phone';          // 电话（旧编码）
    case 15: return 'datetime';       // 日期时间（旧编码）
    case 16: return 'multi-tag';      // 多选标签
    case 22: return 'phone';          // 电话
    case 23: return 'email';          // 邮箱
    case 24: return 'url';            // 网址
    case 26: return 'readonly';       // 引用（只读）
    case 27: return 'readonly';       // 计算（只读）
    case 29: return 'image';          // 图片上传
    case 31: return 'boolean';        // 是/否单选
    case 32: return 'geo';            // 地理定位
    case 33: return 'percent';        // 百分比
    case 34: return 'multi-relation'; // 多态关联
    case 38: return 'datetime';       // 日期时间
    case 39: return 'file';           // 文件上传
    case 40: return 'richtext';       // 富文本
    case 41: return 'sub-table';      // 子表格
    case 99: return 'hidden';         // 维度（不渲染）
    default: return 'text';           // 未知类型降级为文本
  }
}

/**
 * 判断字段是否应在表单中显示。
 */
function isFieldVisible(item: XEntityItem): boolean {
  if (item.enableFlg === 0) return false;
  if (item.hiddenFlg === 1) return false;
  if (item.deleteFlg === 1) return false;
  // 虚拟字段不渲染
  const virtualTypes = new Set([8, 26, 27, 99]);
  if (virtualTypes.has(item.itemType ?? 0)) return false;
  return true;
}

/**
 * 判断字段在当前场景下是否只读。
 * @param mode 'create' | 'edit' | 'detail'
 */
function isFieldReadonly(item: XEntityItem, mode: string): boolean {
  if (mode === 'detail') return true;
  if (mode === 'create' && item.creatable === 0) return true;
  if (mode === 'edit' && item.updatable === 0) return true;
  if (item.readonlyStatus === 3) return true;  // 完全只读
  if (item.readonlyStatus === 2) return true;  // 系统只读
  // readonlyStatus=1 需要判断当前用户是否管理员（由业务层处理）
  return false;
}
```

## 7. 值的存储与转换

| itemType | 存储格式 | 前端显示转换 | 前端提交转换 |
|----------|---------|-------------|-------------|
| 7 (DATE) | BIGINT 毫秒时间戳 | `new Date(val).toLocaleDateString()` | `new Date(input).getTime()` |
| 38 (DATETIME) | BIGINT 毫秒时间戳 | `new Date(val).toLocaleString()` | `new Date(input).getTime()` |
| 15 (DATETIME_OLD) | 同 DATETIME | 同上 | 同上 |
| 31 (BOOLEAN) | SMALLINT 0/1 | 0→"否", 1→"是" | "否"→0, "是"→1 |
| 6 (CURRENCY) | DECIMAL(20,4) | 千分位格式化 | 去除千分位符号 |
| 33 (PERCENT) | DECIMAL(20,4) | 值×100 + "%" | 输入值÷100 |
| 2 (SELECT) | VARCHAR option_code | 显示 option.label | 提交 option_code |
| 3 (MULTI_SELECT) | VARCHAR 逗号分隔 | 拆分为标签数组 | 合并为逗号分隔字符串 |
| 10 (RELATION_SHIP) | BIGINT 关联 ID | 显示关联记录 name | 提交关联记录 ID |

## 8. 预定义选项集字段

部分 `itemType=1 (TEXT)` 的字段虽然底层存储为 VARCHAR，但其取值范围是有限的标准集合，必须渲染为下拉选择器而非文本输入框。通过字段的 `apiKey` 识别。

### 8.1 需要下拉选择的字段清单

| apiKey | 字段名 | 选项来源 | 说明 |
|--------|--------|---------|------|
| timezone | 时区 | 前端内置 IANA 时区列表 | 值为 IANA 标准时区名，如 `Asia/Shanghai` |
| languageCode | 语言编码 | 前端内置 locale 列表 | 值为标准 locale 编码，如 `zh_CN` |
| busitypeApiKey | 业务类型 | 后端 API 动态加载 | 值为业务类型 apiKey |
| departApiKey | 所属部门 | 后端 API 动态加载 | 值为部门 apiKey |
| status | 状态 | 前端内置 | 1=启用, 2=停用 |
| userType | 用户类型 | 前端内置 | 0=普通用户, 1=管理员 |

### 8.2 时区选项（TIMEZONE_OPTIONS）

值使用 IANA 标准时区名，按 UTC 偏移从西到东排序。

| 值 (IANA) | 显示标签 |
|-----------|---------|
| Pacific/Midway | (UTC-11:00) 中途岛 |
| Pacific/Honolulu | (UTC-10:00) 夏威夷 |
| America/Anchorage | (UTC-09:00) 阿拉斯加 |
| America/Los_Angeles | (UTC-08:00) 太平洋时间（美西） |
| America/Denver | (UTC-07:00) 山地时间（美国） |
| America/Chicago | (UTC-06:00) 中部时间（美国） |
| America/New_York | (UTC-05:00) 东部时间（美东） |
| America/Sao_Paulo | (UTC-03:00) 巴西利亚 |
| Atlantic/Reykjavik | (UTC+00:00) 冰岛 |
| Europe/London | (UTC+00:00) 伦敦 |
| Europe/Paris | (UTC+01:00) 巴黎/柏林 |
| Europe/Helsinki | (UTC+02:00) 赫尔辛基 |
| Europe/Moscow | (UTC+03:00) 莫斯科 |
| Asia/Dubai | (UTC+04:00) 迪拜 |
| Asia/Karachi | (UTC+05:00) 卡拉奇 |
| Asia/Kolkata | (UTC+05:30) 孟买/新德里 |
| Asia/Dhaka | (UTC+06:00) 达卡 |
| Asia/Bangkok | (UTC+07:00) 曼谷/雅加达 |
| Asia/Singapore | (UTC+08:00) 新加坡/吉隆坡 |
| Asia/Shanghai | (UTC+08:00) 北京/上海 |
| Asia/Taipei | (UTC+08:00) 台北 |
| Asia/Hong_Kong | (UTC+08:00) 香港 |
| Asia/Tokyo | (UTC+09:00) 东京 |
| Asia/Seoul | (UTC+09:00) 首尔 |
| Australia/Sydney | (UTC+10:00) 悉尼 |
| Pacific/Auckland | (UTC+12:00) 奥克兰 |

### 8.3 语言选项（LANGUAGE_OPTIONS）

值使用标准 locale 编码（语言_地区），覆盖东南亚 CRM 目标市场。

| 值 (locale) | 显示标签 |
|------------|---------|
| zh_CN | 简体中文 |
| zh_TW | 繁體中文 |
| en_US | English (US) |
| en_GB | English (UK) |
| ja_JP | 日本語 |
| ko_KR | 한국어 |
| th_TH | ภาษาไทย |
| vi_VN | Tiếng Việt |
| id_ID | Bahasa Indonesia |
| ms_MY | Bahasa Melayu |

### 8.4 前端识别规则

```typescript
/**
 * 判断字段是否应渲染为预定义下拉选择器。
 * 优先级高于 itemType 的通用映射。
 * 在 renderField 中，先检查 apiKey 是否命中预定义选项集，
 * 命中则渲染 <select>，否则按 itemType 通用规则渲染。
 */
const PREDEFINED_SELECT_FIELDS = new Set([
  'timezone',        // → TIMEZONE_OPTIONS
  'languageCode',    // → LANGUAGE_OPTIONS
  'departApiKey',    // → 后端 API 加载
  'busitypeApiKey',  // → 后端 API 加载
]);
```

### 8.5 扩展规则

当新增字段的取值范围是有限标准集合时（如币种、国家代码等），应：
1. 在本节新增选项表
2. 在前端代码中新增对应的 `XXX_OPTIONS` 常量数组
3. 在 `renderField` 中按 `apiKey` 匹配渲染为 `<select>`
4. 禁止让用户手动输入这类字段
