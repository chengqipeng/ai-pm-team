# menu — 菜单元模型

> 元模型 api_key：`menu`
> p_meta_model 注册：enable_common=1, enable_tenant=1, db_table=`p_tenant_menu`
> 父元模型：无（独立元模型）
> 子元模型：无
> Java Entity：`Menu.java`（待创建）

## 概述

菜单元模型定义系统导航菜单树。Common 级存储系统出厂菜单（管理后台标准菜单），Tenant 级存储租户自定义菜单（新增/隐藏/重排）。

当前前端菜单硬编码在 `navigation.ts` 中，本元模型将其数据化，实现：
- 菜单结构可配置（无需改前端代码）
- 租户可自定义菜单（隐藏不需要的、新增自定义的）
- 菜单与权限联动（通过 permissionApiKey 控制可见性）

## 存储路由

| 层级 | 表名 | 说明 |
|:---|:---|:---|
| Common | `p_common_metadata` | 系统出厂菜单（WHERE metamodel_api_key='menu'） |
| Tenant | `p_tenant_menu` | 租户自定义菜单，结构与 p_common_metadata 一致 + tenant_id |

读取：Common + Tenant 合并，Tenant 可覆盖（同 apiKey 覆盖）或遮蔽（delete_flg=1 隐藏）。

## 字段定义（p_meta_item，14 个）

### 基础信息（固定列映射）

| api_key | db_column | label | 类型 | 说明 |
|:---|:---|:---|:---|:---|
| namespace | namespace | 命名空间 | String | system/product/custom |
| apiKey | api_key | 菜单标识 | String | 全局唯一 |
| label | label | 菜单名称 | String | 显示文本 |
| labelKey | label_key | 多语言Key | String | 国际化 |
| description | description | 描述 | String | — |
| customFlg | custom_flg | 是否定制 | Integer(0/1) | — |

### 扩展属性（dbc 列映射）

| api_key | db_column | label | 类型 | 说明 |
|:---|:---|:---|:---|:---|
| menuIcon | dbc_varchar1 | 图标 | String | lucide-react 图标名，如 `Users`、`Globe` |
| menuGroup | dbc_varchar2 | 分组标题 | String | 如"组织与权限"、"系统设置" |
| menuGroupKey | dbc_varchar3 | 分组多语言Key | String | 国际化 |
| pageApiKey | dbc_varchar4 | 关联页面 | String | 点击菜单打开的 page.apiKey |
| parentMenuApiKey | dbc_varchar5 | 上级菜单 | String | 支持多级菜单，根菜单为空 |
| permissionApiKey | dbc_varchar6 | 权限标识 | String | 关联权限，控制菜单可见性 |
| menuOrder | dbc_int1 | 菜单排序 | Integer | 同组内排序（升序） |
| groupOrder | dbc_int2 | 分组排序 | Integer | 分组间排序（升序） |
| menuType | dbc_smallint1 | 菜单类型 | Integer | 1=菜单项 2=分组标题 3=分隔线 |
| visibleFlg | dbc_smallint2 | 是否可见 | Integer(0/1) | 0=隐藏 1=显示 |
| enableFlg | dbc_smallint3 | 是否启用 | Integer(0/1) | 0=禁用 1=启用 |

### 审计字段（固定列映射）

| api_key | db_column | 类型 |
|:---|:---|:---|
| createdBy | created_by | Long |
| createdAt | created_at | Long(毫秒) |
| updatedBy | updated_by | Long |
| updatedAt | updated_at | Long(毫秒) |

## menuType 枚举

| code | 名称 | 说明 |
|:---|:---|:---|
| 1 | ITEM | 可点击的菜单项，必须有 pageApiKey |
| 2 | GROUP | 分组标题（不可点击），用于视觉分组 |
| 3 | DIVIDER | 分隔线 |

## 菜单树结构

```
menu 元数据通过 menuGroup + groupOrder 实现分组，通过 menuOrder 实现组内排序。
不使用 parentMenuApiKey 做树形（当前管理后台只有一级菜单），
parentMenuApiKey 预留给未来多级菜单场景。

渲染逻辑：
1. 查询所有 menu（Common + Tenant 合并）
2. 按 groupOrder 排序分组
3. 同组内按 menuOrder 排序
4. 过滤 visibleFlg=0 和 enableFlg=0 的菜单
5. 按权限过滤（permissionApiKey 匹配当前用户权限）
```

## Common 级种子数据（11 个菜单项）

### 组织与权限（groupOrder=1）

| apiKey | label | menuIcon | menuOrder | pageApiKey | 说明 |
|:---|:---|:---|:---|:---|:---|
| menuUsers | 用户管理 | Users | 1 | pageUserList | 用户 CRUD |
| menuDepartments | 部门树管理 | Network | 2 | pageDeptTree | 部门树 |
| menuRoles | 角色与授权 | ShieldCheck | 3 | pageRoleList | 角色管理 |
| menuRoleAuth | 角色权限配置 | Lock | 4 | pageRoleAuth | 权限矩阵 |

### 数据安全（groupOrder=2）

| apiKey | label | menuIcon | menuOrder | pageApiKey | 说明 |
|:---|:---|:---|:---|:---|:---|
| menuSharing | 共享规则 | Share2 | 1 | pageSharingRules | 共享规则配置 |
| menuPublicGroups | 共享组管理 | UsersRound | 2 | pagePublicGroups | 公共组 |
| menuTerritory | 区域数据权限 | Map | 3 | pageTerritory | 销售区域 |

### 业务实体（groupOrder=3）

| apiKey | label | menuIcon | menuOrder | pageApiKey | 说明 |
|:---|:---|:---|:---|:---|:---|
| menuEntities | 实体管理 | Database | 1 | pageEntityList | 实体 CRUD |

### 元模型管理（groupOrder=4）

| apiKey | label | menuIcon | menuOrder | pageApiKey | 说明 |
|:---|:---|:---|:---|:---|:---|
| menuMetamodel | 元模型定义 | Boxes | 1 | pageMetamodel | 元模型浏览 |

### 系统设置（groupOrder=5）

| apiKey | label | menuIcon | menuOrder | pageApiKey | 说明 |
|:---|:---|:---|:---|:---|:---|
| menuSettingsLang | 语言管理 | Globe | 1 | pageSettingsLanguage | 语言选项集 |
| menuSettingsTz | 时区管理 | Clock | 2 | pageSettingsTimezone | 时区选项集 |

## 租户自定义示例

### 隐藏菜单

租户不需要"区域数据权限"，在 Tenant 级写入：
```
apiKey = 'menuTerritory', visibleFlg = 0
```
合并读取时 Tenant 覆盖 Common，该菜单不显示。

### 新增菜单

租户新增"审批管理"菜单：
```
apiKey = 'menuApproval', label = '审批管理', menuIcon = 'CheckSquare',
menuGroup = '业务流程', groupOrder = 6, menuOrder = 1,
pageApiKey = 'pageApprovalList', namespace = 'custom', customFlg = 1
```

### 调整排序

租户想把"实体管理"排到第一组：
```
apiKey = 'menuEntities', menuGroup = '组织与权限', groupOrder = 1, menuOrder = 0
```

## 前端消费方式

```typescript
// hooks/useMenuMeta.ts
function useMenuMeta() {
  const [menus, setMenus] = useState<MenuMeta[]>([])

  useEffect(() => {
    // 通过标准合并读取接口加载菜单
    listMergedMetadata('menu').then(data => {
      const visible = data
        .filter(m => m.visibleFlg !== 0 && m.enableFlg !== 0 && m.menuType === 1)
        .sort((a, b) => (a.groupOrder ?? 0) - (b.groupOrder ?? 0) || (a.menuOrder ?? 0) - (b.menuOrder ?? 0))
      setMenus(visible)
    })
  }, [])

  // 按 menuGroup 分组
  const groups = useMemo(() => {
    const map = new Map<string, { title: string; order: number; items: MenuMeta[] }>()
    for (const m of menus) {
      const key = m.menuGroup ?? '其他'
      if (!map.has(key)) map.set(key, { title: key, order: m.groupOrder ?? 99, items: [] })
      map.get(key)!.items.push(m)
    }
    return [...map.values()].sort((a, b) => a.order - b.order)
  }, [menus])

  return { menus, groups }
}
```

## 与老系统对照

| 老系统 | 新系统 | 说明 |
|:---|:---|:---|
| `navigation.ts` 硬编码数组 | `p_common_metadata` (metamodel='menu') | 数据化 |
| `AdminConsolePage.tsx` switch-case | `PageRuntime` 根据 menu.pageApiKey 动态加载 | 零硬编码 |
| 新增菜单改 3 个文件 | 在 p_common_metadata 插入一条记录 | 零代码 |
| 租户无法自定义菜单 | Tenant 级覆盖/新增/隐藏 | 多租户 |
