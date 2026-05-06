/**
 * 字段类型常量
 *
 * 对齐老项目 neo-ui-component-web 中 NeoGrid/interface.tsx 的 itemType
 * 以及 apps-ingage-web 中各页面的字段类型判断
 */

export const ITEM_TYPE = {
  TEXT: 1,
  SINGLE_SELECT: 2,
  MULTI_SELECT: 3,
  INTEGER: 5,
  DECIMAL: 6,
  DATE: 7,
  LOOKUP: 10,
  PHONE: 22,
  EMAIL: 23,
  URL: 24,
  BOOLEAN: 31,
  PERCENT: 33,
  DATETIME: 38,
  CURRENCY: 40,
  TEXTAREA: 41,
} as const

export const ITEM_TYPE_LABEL: Record<number, string> = {
  [ITEM_TYPE.TEXT]: '文本',
  [ITEM_TYPE.SINGLE_SELECT]: '单选',
  [ITEM_TYPE.MULTI_SELECT]: '多选',
  [ITEM_TYPE.INTEGER]: '整数',
  [ITEM_TYPE.DECIMAL]: '实数',
  [ITEM_TYPE.DATE]: '日期',
  [ITEM_TYPE.LOOKUP]: '关联',
  [ITEM_TYPE.PHONE]: '电话',
  [ITEM_TYPE.EMAIL]: '邮箱',
  [ITEM_TYPE.URL]: '网址',
  [ITEM_TYPE.BOOLEAN]: '布尔',
  [ITEM_TYPE.PERCENT]: '百分比',
  [ITEM_TYPE.DATETIME]: '日期时间',
  [ITEM_TYPE.CURRENCY]: '货币',
  [ITEM_TYPE.TEXTAREA]: '多行文本',
}
