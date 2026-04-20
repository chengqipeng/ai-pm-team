---
inclusion: fileMatch
fileMatchPattern: "**/*.tsx,**/*.ts"
---

# 元数据字段类型与 UI 组件映射规范（自动注入）

当编写或修改前端表单、列表、详情页面组件时，必须遵循以下规范：

## 硬约束

1. **字段组件类型必须由 itemType 决定**，禁止硬编码组件类型，必须通过 `resolveFormComponent(itemType)` 函数映射
2. **布尔型字段（itemType=31）必须渲染为是/否单选按钮**，禁止渲染为文本输入框
3. **日期字段（itemType=7/15/38）存储为毫秒时间戳**，显示时转换为日期格式，提交时转换回时间戳
4. **虚拟字段（itemType=8/26/27/99）不渲染输入框**，布局行(8)仅作为分组标题
5. **只读字段（itemType=9/26/27 或 readonlyStatus≥2）禁止编辑**
6. **字段可见性必须检查 enableFlg、hiddenFlg、deleteFlg**，任一为禁用/隐藏/删除状态则不显示
7. **必填字段（requireFlg=1）必须在 label 后显示红色 `*`**，提交时校验非空
8. **新建表单中 creatable=0 的字段必须只读**，编辑表单中 updatable=0 的字段必须只读
9. **单选字段（itemType=2）和多选字段（itemType=3）的选项必须从元数据 pickOption 加载**，禁止硬编码选项
10. **文本字段的 maxLength 必须从元数据 maxLength 属性获取**，默认 300（VARCHAR 列长度）
11. **预定义选项集字段（timezone、languageCode 等）必须渲染为下拉选择器**，禁止渲染为文本输入框，通过 apiKey 识别
12. **时区字段值必须使用 IANA 标准时区名**（如 `Asia/Shanghai`），语言字段值必须使用标准 locale 编码（如 `zh_CN`）

## 完整映射规范

完整规范文档：#[[file:product-specs/metadata-system/models/item-type-ui-mapping.md]]
