# A2UI 组件元数据目录

本目录定义 **Viking CRM A2UI Catalog（`https://viking.tencent.com/a2ui/crm-v1.json`）** 的组件清单。

每个 JSON 文件描述一个业务组件，启动时由 `CatalogRegistry.load_from_dir()` 加载，并注入
`ComponentMatcherV2` 用于 5 层匹配（bind / prefer / ModelName / schema / LLM fallback）。

## JSON 字段

| 字段 | 必填 | 说明 |
|:---|:---:|:---|
| `type` | ✅ | 组件标识。前端 ComponentRegistry 通过此名查找 React 组件实现。 |
| `description` | ✅ | 组件用途。供 LLM 生成时的上下文，也用于 Debug 面板展示。 |
| `input_schema` | ✅ | 组件 props 的 JSON Schema。用于 Schema 匹配（Layer 4），并可被前端 PropsValidator 消费防御 LLM 幻觉。 |
| `skill_bindings` | - | `{bind: [...], prefer: [...]}`。静态声明组件 ↔ Skill 的绑定关系。 |
| `supported_model_names` | - | 该组件能消费的 ModelName 类型（`component` / `relevantData` / `searchResults` / `link`）。 |

## 匹配优先级（由 `ComponentMatcherV2` 实现）

```
Layer 1  bind     —— 静态一对一：skill_bindings.bind 里命中 skill_apikey
Layer 2  prefer   —— 静态首选：skill_bindings.prefer 里命中 skill_apikey 的第一个组件
Layer 3  model    —— ModelName 唯一候选 / LLM 选一：按 supported_model_names 匹配
Layer 4  schema   —— 字段重叠 ≥ 0.6：skill.output_schema.properties vs input_schema.properties
Layer 5  fallback —— 多候选时 LLM 选择（可关闭），或直接返回首选
```

## 新增组件步骤

1. 在本目录新建 `<type>.json`
2. 确保 `type` 在整个 catalog 内唯一
3. 前端 `ComponentRegistry` 里用同名注册 React 实现
4. 重启服务触发 `rewarmup`（或调用 `ComponentMatcherV2.rewarmup()`）

## 参考

- 设计文档：`doc/AGUI-A2UI-协议层设计.md` §3.3 / §4.5 / §8.4
- 对齐实现：`apps-agent` 的 `resources/agui/components/*.json`（见 `神经网络对比` §13.2）
