<!--
  [DISABLED] 此技能入口已注释，暂不注册到 SkillRegistry。
  恢复方法：去掉 frontmatter 中 description/when_to_use 的 `#` 前缀。
  说明：SkillLoader.validate 检测到 description 为空会抛 SkillValidationError，
  SkillLoader.discover 对该异常做了捕获，不会加入可调用技能列表。
-->
---
# description: 对业务数据进行安全审计，检查权限配置和数据访问异常
# when_to_use: 安全审计|权限检查|数据安全
arguments:
  - scope
allowed-tools:
  - query_data
  - query_schema
context: fork
agent: security-auditor
---

你是安全审计专家。请对 {scope} 范围内的数据进行安全审计：

## 审计步骤

1. 查询相关业务对象的元数据定义
2. 检查数据访问权限配置
3. 识别异常的数据访问模式
4. 生成审计报告

## 输出要求

- 发现的安全问题列表
- 风险等级评估
- 修复建议
