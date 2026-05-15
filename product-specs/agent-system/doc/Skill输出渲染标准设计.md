# Skill 输出渲染标准设计方案

> 统一所有 Skill 的输出渲染判定标准，让业务开发者在定义 Skill 时就能明确预期输出形式。
> 与 `AGUI-A2UI-协议层设计.md` §2.3 ModelName 分流机制对齐。

---

## 一、问题分析

### 1.1 当前链路

```
Skill 执行完成
    │
    ├─ context=inline → SkillExecutor 返回 prompt 文本
    │   → LLM 继续推理 → 产出 on_chat_model_stream
    │   → AGUIConverter → TEXT_MESSAGE_* 三段式
    │   → 前端渲染为 Markdown 文本气泡 ✅
    │
    └─ context=fork → SkillExecutor 返回子 Agent 输出
        → LangGraph on_chain_end(name="skill_xxx")
        → AGUIConverter._handle_skill_end()
        → 产出 CUSTOM("skill_output", {skill_apikey, data})
        → ProgressiveRenderer 拦截
        → ComponentMatcher.resolve(skill_apikey)
            ├─ 匹配到组件 → CUSTOM("component_complete") + STATE_DELTA
            │   → 前端渲染为 A2UI 组件 ✅
            └─ 未匹配 → STATE_DELTA({/panels/<skill>/data: 长文本})
                → 前端降级渲染为文档卡片 ❌（非预期）
```

### 1.2 问题根因

| 问题 | 根因 |
|------|------|
| fork 模式的知识检索输出变成卡片 | ComponentMatcher 未注册 knowledge_doc_search 的组件映射，前端对无组件的 STATE_DELTA 长文本降级为卡片 |
| 无法预期输出形式 | Skill 定义中没有声明"我期望的输出形式"，渲染方式由下游链路隐式推断 |
| inline 模式重复输出 | Agent Loop 终止条件不明确，LLM 在同一上下文中可能多次生成回答 |
| 各 Skill 输出风格不统一 | 没有统一的输出类型定义，每个 Skill 各自为政 |

### 1.3 现有机制的能力

AG-UI 协议已经定义了完整的事件分流机制（§2.3 ModelName）：

| ModelName | 事件通道 | 前端渲染 |
|-----------|----------|----------|
| `textResult` / `explanation` / `longText` | TEXT_MESSAGE_* | Markdown 文本气泡 |
| `component` | CUSTOM("component_complete") | 指定的 A2UI 组件 |
| `relevantData` / `searchResults` / `link` | CUSTOM("component_data") | Renderer 匹配组件 |
| 未声明 | CUSTOM("skill_output") → Renderer | 降级（当前问题所在） |

**问题不是缺少机制，而是 Skill 定义层没有声明 ModelName，导致所有 fork 输出都走了"未声明"分支。**

---

## 二、设计方案：output_mode 声明式控制

### 2.1 核心思路

在 Skill 定义中新增 `output_mode` 字段，**显式声明输出的渲染方式**。该字段在 AGUIConverter 层被翻译为对应的 ModelName，从而走正确的事件通道。

```
Skill 定义 (output_mode)
    ↓ 翻译
AGUIConverter (ModelName 分流)
    ↓ 事件
前端 (按事件类型渲染)
```

### 2.2 output_mode 枚举定义

```python
class OutputMode(str, Enum):
    """Skill 输出渲染模式 — 决定前端如何展示 Skill 的执行结果"""

    TEXT = "text"
    # 渲染为 Markdown 文本气泡，直接嵌入对话流
    # AG-UI 通道：TEXT_MESSAGE_START → TEXT_MESSAGE_CONTENT → TEXT_MESSAGE_END
    # ModelName 映射：textResult
    # 适用：知识检索回答、诊断结论、校验报告、步骤指引

    CARD = "card"
    # 渲染为可展开的文档卡片（标题 + 摘要 + "点击查看全文"）
    # AG-UI 通道：CUSTOM("component_complete", {apikey: "doc_card", data: {title, summary, content}})
    # 适用：长篇分析报告（>3000字）、完整文档输出、导出型内容

    COMPONENT = "component"
    # 渲染为指定的 A2UI 组件（需配合 component_apikey 字段）
    # AG-UI 通道：CUSTOM("component_complete") + STATE_DELTA
    # 适用：CRM 客户画像卡、Pipeline 看板、BANT 矩阵

    TABLE = "table"
    # 渲染为结构化数据表格
    # AG-UI 通道：CUSTOM("component_data", {model_name: "searchResults", data: [...]})
    # 适用：数据分析结果、多产品参数对比、列表型数据

    STREAMING = "streaming"
    # 流式输出（逐字渲染），适用于需要实时反馈的长回答
    # AG-UI 通道：TEXT_MESSAGE_CONTENT 逐 chunk 推送
    # 适用：实时生成的长文本、逐步推理过程展示

    AUTO = "auto"
    # 由系统根据内容特征自动判断（默认值）
    # 判定规则见 §2.4
```

### 2.3 output_mode 与现有字段的关系

```
┌─────────────────────────────────────────────────────────────────┐
│ ai_skill_definition 表                                           │
│                                                                  │
│  context (执行方式)          output_mode (展示方式)                │
│  ├─ inline: 注入当前对话     ├─ text: 文本气泡                    │
│  └─ fork: 独立子 Agent       ├─ card: 文档卡片                    │
│                              ├─ component: A2UI 组件              │
│  两者正交，互不干扰          ├─ table: 数据表格                    │
│                              ├─ streaming: 流式文本               │
│                              └─ auto: 自动判断                    │
│                                                                  │
│  component_apikey (可选)                                          │
│  └─ 当 output_mode=component 时，指定渲染的 A2UI 组件 apikey      │
└─────────────────────────────────────────────────────────────────┘
```

**关键约束**：
- `context` 决定 Skill 在哪里执行（主 Agent 上下文 vs 独立子 Agent）
- `output_mode` 决定执行结果如何展示给用户
- 两者组合自由，但有推荐搭配（见 §2.6）

### 2.4 auto 模式的判定规则

```python
def resolve_output_mode(content: str, skill_def: SkillDefinition) -> str:
    """auto 模式下的输出类型自动判定"""

    # 规则 1：如果 Skill 注册了组件映射 → component
    if ComponentMatcher.resolve(skill_def.name):
        return "component"

    # 规则 2：如果内容包含结构化数据标记（JSON Array / Markdown Table）→ table
    if _contains_structured_data(content):
        return "table"

    # 规则 3：按内容长度判定
    char_count = len(content)
    if char_count <= 2000:
        return "text"           # 短文本 → 直接展示
    elif char_count <= 5000:
        return "streaming"      # 中等长度 → 流式展示（用户能看到逐步生成）
    else:
        return "card"           # 超长文本 → 卡片折叠

def _contains_structured_data(content: str) -> bool:
    """检测内容是否包含结构化数据"""
    # Markdown 表格：至少 3 行 | 分隔
    table_lines = [l for l in content.split('\n') if '|' in l and l.strip().startswith('|')]
    if len(table_lines) >= 3:
        return True
    # JSON Array
    if content.strip().startswith('[') and content.strip().endswith(']'):
        return True
    return False
```

### 2.5 各 Skill 的 output_mode 配置

| Skill | context | output_mode | 理由 |
|-------|---------|-------------|------|
| **knowledge_doc_search** | fork | **text** | 用户期望直接看到检索结果和回答，不需要点击展开 |
| accountInsight | fork | component | 客户画像有专属 CRM 卡片组件 |
| customer_360 | inline | component | 360 全景有专属组件 |
| pipeline_analysis | fork | table | Pipeline 数据适合表格展示 |
| data_analysis | fork | table | 分析结果适合表格 |
| verify_config | inline | text | 校验报告直接文本展示 |
| diagnose | inline | text | 诊断结论直接文本展示 |
| inspect_metamodel | inline | text | 元模型档案直接文本展示 |
| trace_db_column | inline | text | 反查结果直接文本展示 |
| batch_cleanup | fork | text | 操作结果直接文本展示 |

### 2.6 context × output_mode 推荐搭配

| 组合 | 推荐度 | 说明 |
|------|--------|------|
| fork + text | ⭐⭐⭐ | 子 Agent 独立执行，结果直接展示为文本。避免重复问题 |
| fork + component | ⭐⭐⭐ | 子 Agent 产出结构化数据，渲染为组件。最佳实践 |
| fork + card | ⭐⭐ | 子 Agent 产出长文档，折叠为卡片。适合报告类 |
| fork + table | ⭐⭐⭐ | 子 Agent 产出数据，渲染为表格 |
| inline + text | ⭐⭐ | 主 Agent 继续推理后输出文本。有重复风险，需 prompt 约束 |
| inline + component | ⭐ | 不推荐。inline 模式下 LLM 难以产出精确的组件数据结构 |
| inline + card | ⭐ | 不推荐。inline 模式的输出通常不会太长 |

---

## 三、AGUIConverter 改造

### 3.1 _handle_skill_end 改造

```python
async def _handle_skill_end(self, name: str, data: dict) -> AsyncGenerator[m.AGUIEvent, None]:
    """Skill 执行完成 — 根据 output_mode 决定事件通道"""
    skill_apikey = name[len(SKILL_CHAIN_PREFIX):]
    step_name = skill_apikey
    output = data.get("output", {})
    status = "failed" if isinstance(output, dict) and output.get("error") else "completed"

    # 获取 Skill 的 output_mode
    output_mode = self._resolve_output_mode(skill_apikey)

    if status == "completed" and output:
        output_text = self._extract_text(output)

        if output_mode == "text" or output_mode == "streaming":
            # 走 TEXT_MESSAGE 通道 → 前端渲染为 Markdown 文本气泡
            async for e in self._emit_text(output_text):
                yield e

        elif output_mode == "card":
            # 走 CUSTOM("component_complete") + 内置 doc_card 组件
            yield m.custom_event("component_complete", {
                "apikey": "doc_card",
                "state": "complete",
                "data": {
                    "title": self._extract_title(output_text),
                    "content": output_text,
                    "skill_apikey": skill_apikey,
                },
            })

        elif output_mode == "component":
            # 走 CUSTOM("component_complete") + 指定组件
            comp_apikey = self._resolve_component_apikey(skill_apikey)
            yield m.custom_event("component_complete", {
                "apikey": comp_apikey or skill_apikey,
                "state": "complete",
                "data": output if isinstance(output, dict) else {"value": output},
            })
            yield m.state_delta([
                {"op": "replace", "path": f"/panels/{comp_apikey or skill_apikey}/state", "value": "complete"},
                {"op": "replace", "path": f"/panels/{comp_apikey or skill_apikey}/data", "value": output},
            ])

        elif output_mode == "table":
            # 走 CUSTOM("component_data") + searchResults 类型
            yield m.custom_event("component_data", {
                "model_name": "searchResults",
                "skill_apikey": skill_apikey,
                "data": output if isinstance(output, (dict, list)) else {"value": output},
            })

        elif output_mode == "auto":
            # 自动判定
            resolved = self._auto_resolve(output_text, skill_apikey)
            # 递归调用对应分支（简化：直接内联）
            if resolved == "text":
                async for e in self._emit_text(output_text):
                    yield e
            elif resolved == "card":
                yield m.custom_event("skill_output",
                                     {"skill_apikey": skill_apikey, "data": output})
            else:
                yield m.custom_event("skill_output",
                                     {"skill_apikey": skill_apikey, "data": output})

        else:
            # 兜底：走原有 skill_output 路径
            yield m.custom_event("skill_output",
                                 {"skill_apikey": skill_apikey, "data": output})

    # step 元数据和结束事件（不变）
    skill_context = self._resolve_skill_context(skill_apikey)
    yield m.step_metadata(step_name, skill_apikey=skill_apikey,
                          step_index=self._step_index, status=status,
                          phase="finished", skill_context=skill_context)
    yield m.step_finished(step_name)
    self._step_index += 1
    yield m.messages_snapshot(list(self._messages))
```

### 3.2 _resolve_output_mode 方法

```python
def _resolve_output_mode(self, skill_apikey: str) -> str:
    """从 SkillRegistry 获取 Skill 的 output_mode"""
    if self._skill_registry is None:
        return "auto"
    try:
        skill = self._skill_registry.get(skill_apikey)
        if skill:
            return getattr(skill, 'output_mode', 'auto') or 'auto'
    except Exception:
        pass
    return "auto"
```

### 3.3 ProgressiveRenderer 的变化

当 `output_mode` 为 `text` 时，`_handle_skill_end` 直接走 TEXT_MESSAGE 通道，**不再产出 CUSTOM("skill_output") 内部事件**。因此 ProgressiveRenderer 不会拦截到该事件，也不会触发 ComponentMatcher → 不会产出 component_complete → 前端不会渲染为卡片。

```
output_mode=text 的事件流：
  STEP_STARTED → step_metadata → TEXT_MESSAGE_START → TEXT_MESSAGE_CONTENT×N → TEXT_MESSAGE_END → step_metadata → STEP_FINISHED

output_mode=component 的事件流：
  STEP_STARTED → step_metadata → component_loading → skill_output(内部) → component_complete + STATE_DELTA → step_metadata → STEP_FINISHED

output_mode=card 的事件流：
  STEP_STARTED → step_metadata → component_complete(doc_card) → step_metadata → STEP_FINISHED
```

---

## 四、数据库层改动

### 4.1 DDL

```sql
-- 新增 output_mode 字段
ALTER TABLE ai_skill_definition
ADD COLUMN IF NOT EXISTS output_mode VARCHAR(20) NOT NULL DEFAULT 'auto';

-- 新增 component_apikey 字段（output_mode=component 时使用）
ALTER TABLE ai_skill_definition
ADD COLUMN IF NOT EXISTS component_apikey VARCHAR(100) NOT NULL DEFAULT '';

COMMENT ON COLUMN ai_skill_definition.output_mode IS
  '输出渲染模式: text | card | component | table | streaming | auto';
COMMENT ON COLUMN ai_skill_definition.component_apikey IS
  '当 output_mode=component 时，指定渲染的 A2UI 组件 apikey';
```

### 4.2 现有 Skill 数据迁移

```sql
-- 知识检索：直接文本展示
UPDATE ai_skill_definition SET output_mode = 'text'
WHERE api_key = 'knowledge_doc_search' AND delete_flg = 0;

-- 客户洞察：组件展示
UPDATE ai_skill_definition SET output_mode = 'component', component_apikey = 'crm_record_card'
WHERE api_key = 'accountInsight' AND delete_flg = 0;

-- 数据分析：表格展示
UPDATE ai_skill_definition SET output_mode = 'table'
WHERE api_key IN ('data_analysis', 'pipeline_analysis') AND delete_flg = 0;

-- 其他：文本展示
UPDATE ai_skill_definition SET output_mode = 'text'
WHERE api_key IN ('verify_config', 'diagnose', 'customer_360', 'inspect_metamodel',
                  'trace_db_column', 'inspect_entity_metadata', 'batch_cleanup')
  AND delete_flg = 0;
```

### 4.3 SkillDefinitionRow 新增字段

```python
@dataclass
class SkillDefinitionRow:
    ...
    output_mode: str = "auto"           # text | card | component | table | streaming | auto
    component_apikey: str = ""          # output_mode=component 时的目标组件
```

### 4.4 SkillDefinition 运行时对象

```python
@dataclass
class SkillDefinition:
    ...
    output_mode: str = "auto"
    component_apikey: str = ""
```

---

## 五、前端适配

### 5.1 渲染规则（前端不再自行判断）

| 收到的事件 | 渲染方式 | 说明 |
|-----------|----------|------|
| TEXT_MESSAGE_* | Markdown 文本气泡 | 支持表格、代码块、列表等 Markdown 语法 |
| CUSTOM("component_complete") + 有组件注册 | A2UI 组件 | 按 catalog 中的组件定义渲染 |
| CUSTOM("component_complete") + apikey="doc_card" | 文档卡片 | 内置的文档预览卡片组件 |
| CUSTOM("component_data") | 数据表格/列表 | 按 model_name 选择表格/列表/链接卡片 |
| STATE_DELTA 无伴随 component_complete | 静默更新状态 | 不触发新的 UI 渲染 |

### 5.2 移除前端降级逻辑

当前前端对"无匹配组件的 STATE_DELTA 长文本"降级为卡片的逻辑应该移除。改为：
- 有 `component_complete` 事件 → 按事件中的 apikey 渲染
- 只有 `STATE_DELTA` 无 `component_complete` → 静默更新，不渲染新 UI

---

## 六、API 层变化

### 6.1 Skill 创建/编辑 API

`CreateSkillBody` 和 `UpdateSkillBody` 新增字段：

```python
class CreateSkillBody(BaseModel):
    ...
    output_mode: str = Field(default="auto", pattern="^(text|card|component|table|streaming|auto)$")
    component_apikey: str = Field(default="", max_length=100)
```

### 6.2 Skill 详情 API 响应

```json
{
  "api_key": "knowledge_doc_search",
  "output_mode": "text",
  "component_apikey": "",
  ...
}
```

### 6.3 前端编辑页面

在 Skill 编辑表单中新增「输出模式」下拉选择：

```
输出模式：[自动判断 ▾]
  - 自动判断（根据内容长度和类型）
  - 文本气泡（直接展示 Markdown）
  - 文档卡片（折叠长文本，点击展开）
  - A2UI 组件（需指定组件）
  - 数据表格（结构化数据）
  - 流式文本（逐字渲染）

[当选择"A2UI 组件"时显示]
目标组件：[crm_record_card ▾]  ← 从 CatalogRegistry 加载选项
```

---

## 七、实施计划

### Phase 1：数据库 + 模型层（立即，0.5 天）

1. ALTER TABLE 新增 `output_mode` + `component_apikey`
2. `SkillDefinitionRow` / `SkillDefinition` 新增字段
3. `from_db_row` 读取新字段
4. 为现有 Skill 执行数据迁移 SQL
5. `knowledge_doc_search` 设为 `output_mode=text`

### Phase 2：AGUIConverter 改造（1 天）

1. `_handle_skill_end` 按 output_mode 分流
2. 新增 `_resolve_output_mode` 方法
3. `auto` 模式的判定逻辑
4. 单元测试：验证各 output_mode 产出正确的事件类型

### Phase 3：ProgressiveRenderer 适配（0.5 天）

1. 当 output_mode=text 时，不再拦截 skill_output（因为不会产出）
2. 当 output_mode=component 时，保持现有 ComponentMatcher 逻辑
3. 当 output_mode=card 时，使用内置 doc_card 组件

### Phase 4：API + 前端（1 天）

1. Skill API 新增 output_mode / component_apikey 字段
2. 前端编辑页面新增「输出模式」选择器
3. 前端移除"无组件长文本降级为卡片"的逻辑

### Phase 5：验证 + 文档（0.5 天）

1. 端到端验证：knowledge_doc_search → text 气泡
2. 端到端验证：accountInsight → component 组件
3. 端到端验证：data_analysis → table 表格
4. 更新 Skill 管理体系设计方案文档

---

## 八、向后兼容

| 场景 | 处理 |
|------|------|
| 已有 Skill 未设置 output_mode | 默认 `auto`，行为与当前一致（Renderer 降级） |
| 前端未升级 | 后端 output_mode=text 走 TEXT_MESSAGE 通道，前端天然支持 |
| 新建 Skill 未指定 output_mode | 默认 `auto`，系统自动判断 |
| ComponentMatcher 已注册的 Skill | output_mode=auto 时优先走 component 分支 |

---

## 九、总结

**一句话**：Skill 定义时声明 `output_mode`，AGUIConverter 按声明走对应事件通道，前端按事件类型渲染。不再依赖下游链路的隐式推断。

**核心公式**：
```
output_mode → ModelName → AG-UI 事件类型 → 前端渲染方式
```

| output_mode | ModelName | AG-UI 事件 | 前端渲染 |
|-------------|-----------|-----------|----------|
| text | textResult | TEXT_MESSAGE_* | Markdown 气泡 |
| card | — | CUSTOM(component_complete, doc_card) | 文档卡片 |
| component | component | CUSTOM(component_complete) + STATE_DELTA | A2UI 组件 |
| table | searchResults | CUSTOM(component_data) | 数据表格 |
| streaming | textResult | TEXT_MESSAGE_CONTENT (逐 chunk) | 流式文本 |
| auto | 动态 | 动态 | 动态 |
