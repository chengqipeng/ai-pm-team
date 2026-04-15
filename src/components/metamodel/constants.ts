/** 对象类型映射 */
export const OBJECT_TYPE_MAP: Record<number, string> = {
  0: '标准对象',
  1: '自定义对象',
  2: '系统对象',
  3: '虚拟对象',
};

/**
 * 字段类型映射（新老编码一致）
 */
export const ITEM_TYPE_MAP: Record<number, string> = {
  1: '文本',
  2: '单选',
  3: '多选',
  4: '文本域',
  5: '整数',
  6: '实数',
  7: '日期',
  8: '布局行',
  9: '自动编号',
  10: '关联',
  11: '整数',
  13: '电话',
  15: '日期时间',
  16: '多选标签',
  22: '电话',
  23: '邮箱',
  24: '网址',
  26: '引用',
  27: '计算',
  29: '图片',
  31: '布尔',
  32: '地理定位',
  33: '百分比',
  34: '多态关联',
  38: '时间',
  39: '文件',
  40: '富文本',
  41: '多值关联',
  99: '维度',
};

/** 数据类型映射（底层存储类型） */
export const DATA_TYPE_MAP: Record<number, string> = {
  1: 'VARCHAR',
  2: 'INT',
  3: 'BIGINT',
  4: 'DECIMAL',
  5: 'TEXT',
  6: 'SMALLINT',
};

/**
 * 字段子类型映射（真实数据类型）
 * 非计算型字段 itemSubType = itemType；计算型字段为计算结果类型
 */
export const ITEM_SUB_TYPE_MAP: Record<number, string> = {
  1: '文本',
  2: '单选',
  3: '多选',
  4: '文本域',
  5: '整数',
  6: '实数',
  7: '日期',
  9: '自动编号',
  10: '关联',
  11: '整数',
  13: '电话',
  15: '日期时间',
  16: '多选',
  31: '布尔',
  33: '百分比',
  38: '时间',
};

/** 计算型字段类型集合 */
export const COMPUTE_ITEM_TYPES = new Set([27]);

/** 获取字段的完整类型描述 */
export function getItemTypeLabel(itemType?: number, itemSubType?: number): string {
  if (!itemType) return '未知';
  const typeName = ITEM_TYPE_MAP[itemType] ?? `未知(${itemType})`;
  if (COMPUTE_ITEM_TYPES.has(itemType) && itemSubType) {
    const subName = ITEM_SUB_TYPE_MAP[itemSubType] ?? ITEM_TYPE_MAP[itemSubType] ?? `未知(${itemSubType})`;
    return `${typeName}(${subName})`;
  }
  return typeName;
}

/** 关联类型映射 */
export const LINK_TYPE_MAP: Record<number, string> = {
  0: 'LOOKUP',
  1: '主从',
  2: '多对多',
};
