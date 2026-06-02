# Tool 评测用例管理与执行设计

> 目标：为 eval/tools 下每个分类建立结构化用例集，支持按分类/方法/参数组合粒度执行，覆盖正向与逆向场景。

---

## 一、用例层级模型

```
eval/tools/
├── query_schema/              ← 工具分类（Tool Category）
│   ├── list_entities          ← 方法（Method）
│   │   ├── case_001: 无参数查询全部实体
│   │   ├── case_002: 指定 entity_api_key 过滤
│   │   ├── case_003: 指定 include_fields=true
│   │   ├── case_004: 不存在的 entity_api_key（逆向）
│   │   └── case_005: 参数类型错误（逆向）
│   ├── get_entity_detail
│   │   ├── case_001: 正常获取单个实体详情
│   │   ├── case_002: 包含关联字段
│   │   └── case_003: entity 不存在（逆向）
│   └── list_fields
│       └── ...
├── query_data/
│   ├── simple_query
│   ├── filter_query
│   ├── pagination_query
│   └── ...
├── modify_data/
│   ├── create_record
│   ├── update_record
│   └── delete_record
├── analyze_data/
│   └── ...
└── manage_memory/
    └── ...
```

---

## 二、数据库表设计

### 2.1 表关系总览

```
ai_eval_tool_category          ← 工具分类（query_schema, query_data, ...）
       │ 1:N
       ▼
ai_eval_tool_method            ← 方法（list_entities, get_entity_detail, ...）
       │ 1:N
       ▼
ai_eval_tool_case              ← 用例（含参数组合 + 期望结果 + 正向/逆向标记）
       │ 1:N
       ▼
ai_eval_tool_case_run          ← 执行记录（每次跑用例的结果快照）
```

### 2.2 表结构定义

```sql
-- ═══════════════════════════════════════════════════════════════
-- 工具分类表
-- ═══════════════════════════════════════════════════════════════
CREATE TABLE ai_eval_tool_category (
    id              BIGINT PRIMARY KEY AUTO_INCREMENT,
    tenant_id       BIGINT NOT NULL DEFAULT 0,          -- 0=平台级, >0=租户级
    category_key    VARCHAR(100) NOT NULL,               -- "query_schema", "query_data"
    display_name    VARCHAR(200) NOT NULL,               -- "Schema 查询工具"
    description     TEXT,
    tool_name       VARCHAR(200) NOT NULL,               -- 对应的 Tool.name（可能多个方法共用同一 tool）
    sort_order      INT DEFAULT 0,
    is_active       TINYINT DEFAULT 1,
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at      DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uk_tenant_category (tenant_id, category_key)
);

-- ═══════════════════════════════════════════════════════════════
-- 工具方法表
-- ═══════════════════════════════════════════════════════════════
CREATE TABLE ai_eval_tool_method (
    id              BIGINT PRIMARY KEY AUTO_INCREMENT,
    category_id     BIGINT NOT NULL,                     -- FK → ai_eval_tool_category
    tenant_id       BIGINT NOT NULL DEFAULT 0,
    method_key      VARCHAR(100) NOT NULL,               -- "list_entities", "get_entity_detail"
    display_name    VARCHAR(200) NOT NULL,               -- "列出所有实体"
    description     TEXT,
    -- 方法签名元数据（用于自动生成参数组合）
    input_schema    JSON,                                -- 该方法的入参 JSON Schema
    output_schema   JSON,                                -- 期望返回的 JSON Schema
    -- 参数组合策略
    param_strategy  VARCHAR(50) DEFAULT 'manual',        -- manual / pairwise / exhaustive / boundary
    sort_order      INT DEFAULT 0,
    is_active       TINYINT DEFAULT 1,
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at      DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uk_category_method (category_id, method_key),
    KEY idx_tenant (tenant_id)
);

-- ═══════════════════════════════════════════════════════════════
-- 用例表（核心）
-- ═══════════════════════════════════════════════════════════════
CREATE TABLE ai_eval_tool_case (
    id              BIGINT PRIMARY KEY AUTO_INCREMENT,
    method_id       BIGINT NOT NULL,                     -- FK → ai_eval_tool_method
    tenant_id       BIGINT NOT NULL DEFAULT 0,
    case_key        VARCHAR(100) NOT NULL,               -- "list_entities_no_params"
    display_name    VARCHAR(300) NOT NULL,               -- "无参数查询全部实体"
    description     TEXT,

    -- 场景分类
    scenario_type   VARCHAR(20) NOT NULL DEFAULT 'positive',
                    -- positive: 正向（正常入参，期望正确结果）
                    -- negative: 逆向（异常入参，期望错误处理）
                    -- boundary: 边界（极端值、空值、超大值）
                    -- permission: 权限（无权限/部分权限）

    -- 输入参数（JSON）
    input_params    JSON NOT NULL,                       -- 工具调用的完整参数
    -- 示例: {"entity_api_key": "order", "include_fields": true}

    -- 前置条件（可选）
    preconditions   JSON,                                -- 执行前需要的环境状态
    -- 示例: {"requires_data": ["order entity exists"], "depends_on": ["case_001"]}

    -- 期望结果
    expected_output JSON,                                -- 精确期望输出（可选）
    assertions      JSON NOT NULL,                       -- 断言规则列表
    -- 示例断言:
    -- [
    --   {"type": "json_schema", "config": {"schema": {...}}},
    --   {"type": "contains_all", "config": {"expected": ["order", "customer"]}},
    --   {"type": "not_error", "config": {}},
    --   {"type": "response_time", "config": {"max_ms": 3000}}
    -- ]

    -- 参数组合标记
    param_combination_id  VARCHAR(100),                  -- 参数组合标识（同方法下区分不同组合）
    param_tags            JSON,                          -- 参数标签 ["required_only", "all_optional", "invalid_type"]

    -- 优先级与分组
    priority        INT DEFAULT 5,                       -- 1-10, 数字越小优先级越高
    tags            JSON,                                -- 自定义标签 ["smoke", "regression", "p0"]
    is_active       TINYINT DEFAULT 1,

    -- 版本控制
    version         INT DEFAULT 1,
    created_by      VARCHAR(100),
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at      DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    UNIQUE KEY uk_method_case (method_id, case_key),
    KEY idx_tenant (tenant_id),
    KEY idx_scenario (scenario_type),
    KEY idx_priority (priority)
);

-- ═══════════════════════════════════════════════════════════════
-- 执行记录表
-- ═══════════════════════════════════════════════════════════════
CREATE TABLE ai_eval_tool_case_run (
    id              BIGINT PRIMARY KEY AUTO_INCREMENT,
    -- 执行范围（支持按分类/方法/用例三种粒度触发）
    run_scope       VARCHAR(20) NOT NULL,                -- category / method / case
    run_scope_id    BIGINT NOT NULL,                     -- 对应 category_id / method_id / case_id
    batch_id        VARCHAR(64) NOT NULL,                -- 同一批次执行的唯一标识

    case_id         BIGINT NOT NULL,                     -- FK → ai_eval_tool_case
    tenant_id       BIGINT NOT NULL DEFAULT 0,

    -- 执行结果
    status          VARCHAR(20) NOT NULL,                -- passed / failed / error / skipped / timeout
    actual_output   JSON,                                -- 工具实际返回
    assertion_results JSON,                              -- 每条断言的通过/失败详情
    error_message   TEXT,

    -- 性能指标
    latency_ms      INT,
    started_at      DATETIME,
    finished_at     DATETIME,

    -- 触发信息
    triggered_by    VARCHAR(100),                        -- user_id 或 "ci_pipeline"
    trigger_type    VARCHAR(20) DEFAULT 'manual',        -- manual / scheduled / ci

    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,

    KEY idx_batch (batch_id),
    KEY idx_case (case_id),
    KEY idx_scope (run_scope, run_scope_id),
    KEY idx_status (status)
);
```

---

## 三、参数组合覆盖策略

### 3.1 参数维度分析（以 list_entities 为例）

```yaml
method: list_entities
tool: query_schema
input_schema:
  type: object
  properties:
    entity_api_key:
      type: string
      description: "实体 API Key，不传则返回全部"
      required: false
    include_fields:
      type: boolean
      description: "是否包含字段定义"
      default: false
    include_relations:
      type: boolean
      description: "是否包含关联关系"
      default: false
    page:
      type: integer
      minimum: 1
    page_size:
      type: integer
      minimum: 1
      maximum: 200
      default: 50
```

### 3.2 参数组合生成规则

```
┌─────────────────────────────────────────────────────────────────────────┐
│  参数组合策略                                                            │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  策略 A: 正交覆盖（Pairwise / 两两组合）                                │
│  ──────────────────────────────────────                                 │
│  目标: 用最少用例覆盖所有参数对之间的组合                                │
│  适用: 参数多（>3个）且相互独立的方法                                    │
│                                                                         │
│  策略 B: 等价类 + 边界值                                                │
│  ──────────────────────────────────────                                 │
│  目标: 每个参数取等价类代表值 + 边界值                                   │
│  适用: 参数有明确取值范围的方法                                          │
│                                                                         │
│  策略 C: 场景驱动                                                       │
│  ──────────────────────────────────────                                 │
│  目标: 按业务场景枚举典型用法                                            │
│  适用: 参数间有业务语义耦合的方法                                        │
│                                                                         │
│  策略 D: 全组合（Exhaustive）                                           │
│  ──────────────────────────────────────                                 │
│  目标: 穷举所有组合（仅用于参数少、取值少的方法）                         │
│  适用: bool 参数 ≤ 3 个的方法                                           │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

### 3.3 list_entities 完整用例矩阵

| 用例 ID | 场景类型 | entity_api_key | include_fields | include_relations | page | page_size | 期望 |
|---------|---------|---------------|:-:|:-:|:-:|:-:|------|
| LE-P001 | positive | (不传) | false | false | 1 | 50 | 返回所有实体列表 |
| LE-P002 | positive | "order" | false | false | - | - | 返回 order 实体 |
| LE-P003 | positive | "order" | true | false | - | - | 返回 order + 字段定义 |
| LE-P004 | positive | "order" | true | true | - | - | 返回 order + 字段 + 关联 |
| LE-P005 | positive | "order" | false | true | - | - | 返回 order + 关联 |
| LE-P006 | positive | (不传) | true | true | 1 | 10 | 分页返回全部(带字段和关联) |
| LE-P007 | positive | (不传) | false | false | 2 | 10 | 返回第二页 |
| LE-N001 | negative | "nonexistent_xyz" | false | false | - | - | 返回空或错误提示 |
| LE-N002 | negative | "" (空字符串) | false | false | - | - | 参数校验失败 |
| LE-N003 | negative | 123 (类型错误) | false | false | - | - | 类型校验失败 |
| LE-N004 | negative | (不传) | false | false | -1 | 50 | page 校验失败 |
| LE-N005 | negative | (不传) | false | false | 1 | 999 | page_size 超限 |
| LE-N006 | negative | (不传) | false | false | 0 | 0 | 边界值校验 |
| LE-B001 | boundary | (不传) | false | false | 1 | 1 | 最小 page_size |
| LE-B002 | boundary | (不传) | false | false | 1 | 200 | 最大 page_size |
| LE-B003 | boundary | "a"*200 (超长) | false | false | - | - | 超长参数处理 |

### 3.4 参数组合自动生成器

```python
# src/eval/tools/param_generator.py

class ParamCombinationGenerator:
    """根据方法的 input_schema 自动生成参数组合用例"""

    def generate(
        self,
        method_schema: dict,
        strategy: str = "pairwise",
    ) -> list[GeneratedCase]:
        """
        生成参数组合用例

        Args:
            method_schema: 方法的 JSON Schema
            strategy: 生成策略 (pairwise / exhaustive / boundary / scenario)

        Returns:
            生成的用例草稿列表（需人工确认后入库）
        """
        params = self._parse_params(method_schema)
        cases = []

        # ═══ 正向用例 ═══
        # 1. 最小必填参数
        cases.append(self._minimal_required_case(params))

        # 2. 全部参数（默认值）
        cases.append(self._all_params_default_case(params))

        # 3. 按策略生成组合
        if strategy == "pairwise":
            cases.extend(self._pairwise_combinations(params))
        elif strategy == "exhaustive":
            cases.extend(self._exhaustive_combinations(params))

        # ═══ 逆向用例 ═══
        # 4. 每个 required 参数缺失
        cases.extend(self._missing_required_cases(params))

        # 5. 每个参数的类型错误
        cases.extend(self._wrong_type_cases(params))

        # 6. 每个参数的边界值（null, 空字符串, 超长, 0, 负数, 超大数）
        cases.extend(self._boundary_cases(params))

        # ═══ 边界用例 ═══
        # 7. 数值型参数的 min/max 边界
        cases.extend(self._numeric_boundary_cases(params))

        # 8. 枚举型参数的非法值
        cases.extend(self._invalid_enum_cases(params))

        return cases

    def _pairwise_combinations(self, params: list[ParamInfo]) -> list[GeneratedCase]:
        """两两组合覆盖（使用 AllPairs 算法）"""
        # 对每个参数取其等价类代表值
        param_values = {}
        for p in params:
            param_values[p.name] = self._get_equivalence_values(p)

        # 使用 pairwise 算法生成最少覆盖组合
        combinations = allpairs(param_values)
        return [
            GeneratedCase(
                scenario_type="positive",
                input_params=combo,
                display_name=f"pairwise-{i}",
            )
            for i, combo in enumerate(combinations)
        ]

    def _get_equivalence_values(self, param: ParamInfo) -> list:
        """获取参数的等价类代表值"""
        values = []
        if param.type == "string":
            values = [param.default or "test_value", "", None]
            if param.enum:
                values = list(param.enum) + [None]
        elif param.type == "integer":
            values = [
                param.minimum or 1,
                param.maximum or 100,
                (param.minimum or 0 + param.maximum or 100) // 2,
            ]
        elif param.type == "boolean":
            values = [True, False]
        elif param.type == "array":
            values = [[], ["item1"], ["item1", "item2"]]
        return values
```

---

## 四、执行粒度与前端交互

### 4.1 三级执行粒度

```
┌─────────────────────────────────────────────────────────────────────────┐
│  执行粒度                                                                │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  Level 1: 按分类执行（Category）                                        │
│  ─────────────────────────────                                          │
│  触发: "执行 query_schema 下所有用例"                                    │
│  范围: ai_eval_tool_case WHERE method_id IN                             │
│        (SELECT id FROM ai_eval_tool_method WHERE category_id = ?)       │
│  场景: 回归测试、CI 触发、工具代码变更后全量验证                          │
│                                                                         │
│  Level 2: 按方法执行（Method）                                          │
│  ─────────────────────────────                                          │
│  触发: "执行 query_schema → list_entities 下所有用例"                    │
│  范围: ai_eval_tool_case WHERE method_id = ?                            │
│  场景: 单个方法实现变更后验证、开发调试                                   │
│                                                                         │
│  Level 3: 按用例执行（Case）                                            │
│  ─────────────────────────────                                          │
│  触发: "执行 list_entities 的 LE-N001 用例"                              │
│  范围: 单条 ai_eval_tool_case                                           │
│  场景: 定位问题、调试单个失败用例                                        │
│                                                                         │
│  Level 1+: 按标签执行（Tag）                                            │
│  ─────────────────────────────                                          │
│  触发: "执行所有 tags 包含 'smoke' 的用例"                               │
│  范围: 跨分类、跨方法，按标签过滤                                        │
│  场景: 冒烟测试、P0 用例快速验证                                         │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

### 4.2 前端页面结构

```
┌─────────────────────────────────────────────────────────────────────────┐
│  Tool 评测用例管理                                        [+ 新建分类]    │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  ┌─ 左侧导航树 ─────────────────┐  ┌─ 右侧内容区 ────────────────────┐ │
│  │                               │  │                                  │ │
│  │  📂 query_schema          [▶] │  │  query_schema > list_entities    │ │
│  │    ├── list_entities    (15) │  │                                  │ │
│  │    ├── get_entity_detail (8) │  │  [▶ 执行全部] [+ 新建用例]       │ │
│  │    └── list_fields       (6) │  │  [🔄 自动生成参数组合]            │ │
│  │                               │  │                                  │ │
│  │  📂 query_data            [▶] │  │  ┌─ 筛选 ──────────────────────┐│ │
│  │    ├── simple_query     (12) │  │  │ 场景: [全部▾] 状态: [全部▾] ││ │
│  │    ├── filter_query     (20) │  │  │ 标签: [smoke] [regression]   ││ │
│  │    └── pagination        (8) │  │  └────────────────────────────────┘│ │
│  │                               │  │                                  │ │
│  │  📂 modify_data          [▶] │  │  ┌─────────────────────────────┐ │ │
│  │    ├── create_record    (10) │  │  │ ✅ LE-P001 无参数查询全部    │ │ │
│  │    ├── update_record    (12) │  │  │    positive | smoke | 2ms    │ │ │
│  │    └── delete_record     (8) │  │  ├─────────────────────────────┤ │ │
│  │                               │  │  │ ✅ LE-P002 指定entity过滤   │ │ │
│  │  📂 analyze_data         [▶] │  │  │    positive | regression    │ │ │
│  │  📂 manage_memory        [▶] │  │  ├─────────────────────────────┤ │ │
│  │  📂 browse_metamodel     [▶] │  │  │ ❌ LE-N001 不存在的entity    │ │ │
│  │                               │  │  │    negative | FAILED | 5ms  │ │ │
│  │  ─────────────────────────── │  │  ├─────────────────────────────┤ │ │
│  │  📊 整体通过率: 92.3%        │  │  │ ⏸ LE-N003 类型错误          │ │ │
│  │  📊 上次运行: 2024-03-15     │  │  │    negative | skipped       │ │ │
│  │                               │  │  └─────────────────────────────┘ │ │
│  └───────────────────────────────┘  └──────────────────────────────────┘ │
│                                                                         │
│  ── 底部执行状态栏 ─────────────────────────────────────────────────── │
│  │ 🔵 正在执行: query_schema > list_entities (7/15)  [取消]             │
│  │    ✅ 5 passed  ❌ 1 failed  ⏳ 9 pending                           │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

### 4.3 用例编辑页面

```
┌─────────────────────────────────────────────────────────────────────────┐
│  编辑用例: LE-P003                                                       │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  用例名称: [指定 entity + include_fields=true              ]             │
│  场景类型: (●) 正向  ( ) 逆向  ( ) 边界  ( ) 权限                       │
│  优先级:   [5 ▾]                                                        │
│  标签:     [regression] [x]  [p1] [x]  [+ 添加]                        │
│                                                                         │
│  ── 输入参数 ──────────────────────────────────────────────────────── │
│  │ 📋 从 Schema 生成表单                [切换 JSON 编辑]                │
│  │                                                                     │
│  │  entity_api_key: [order           ] (string, optional)              │
│  │  include_fields: [✓] true           (boolean, default: false)       │
│  │  include_relations: [ ] false       (boolean, default: false)       │
│  │  page:           [               ]  (integer, optional)             │
│  │  page_size:      [               ]  (integer, optional)             │
│  │                                                                     │
│  │  等效 JSON:                                                         │
│  │  {"entity_api_key": "order", "include_fields": true}                │
│                                                                         │
│  ── 期望断言 ──────────────────────────────────────────────────────── │
│  │                                                                     │
│  │  断言 1: [json_schema ▾]                                            │
│  │    输出必须包含 "fields" 数组字段                                    │
│  │    Schema: {"properties": {"fields": {"type": "array"}}}            │
│  │                                                                     │
│  │  断言 2: [not_error ▾]                                              │
│  │    返回结果不能是错误                                                │
│  │                                                                     │
│  │  断言 3: [response_time ▾]                                          │
│  │    响应时间 ≤ 3000ms                                                │
│  │                                                                     │
│  │  [+ 添加断言]                                                       │
│                                                                         │
│  [保存]  [保存并执行]  [取消]                                           │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## 五、执行引擎设计

### 5.1 Tool 用例执行器

```python
# src/eval/tools/tool_case_runner.py

class ToolCaseRunner:
    """
    Tool 评测用例执行器
    直接调用工具函数（不经过 Agent 推理），验证工具自身的功能正确性
    """

    def __init__(self, tool_registry: ToolRegistry, tenant_id: int):
        self._registry = tool_registry
        self._tenant_id = tenant_id

    async def run_by_category(self, category_id: int, **filters) -> BatchRunResult:
        """按分类执行所有用例"""
        methods = await self._get_methods(category_id)
        all_cases = []
        for method in methods:
            cases = await self._get_cases(method.id, **filters)
            all_cases.extend(cases)
        return await self._run_batch(all_cases, scope="category", scope_id=category_id)

    async def run_by_method(self, method_id: int, **filters) -> BatchRunResult:
        """按方法执行所有用例"""
        cases = await self._get_cases(method_id, **filters)
        return await self._run_batch(cases, scope="method", scope_id=method_id)

    async def run_single_case(self, case_id: int) -> CaseRunResult:
        """执行单条用例"""
        case = await self._load_case(case_id)
        return await self._execute_case(case)

    async def run_by_tags(self, tags: list[str], **filters) -> BatchRunResult:
        """按标签执行用例（跨分类）"""
        cases = await self._get_cases_by_tags(tags, **filters)
        return await self._run_batch(cases, scope="tags", scope_id=0)

    async def _run_batch(
        self,
        cases: list[ToolCase],
        scope: str,
        scope_id: int,
    ) -> BatchRunResult:
        """批量执行用例"""
        batch_id = f"batch_{uuid.uuid4().hex[:12]}"
        results = []

        for case in cases:
            # 检查前置条件
            if case.preconditions and not await self._check_preconditions(case):
                results.append(CaseRunResult(
                    case_id=case.id,
                    status="skipped",
                    reason="precondition not met",
                ))
                continue

            result = await self._execute_case(case)
            results.append(result)

            # 持久化执行记录
            await self._save_run_record(batch_id, scope, scope_id, case, result)

        return BatchRunResult(
            batch_id=batch_id,
            total=len(cases),
            passed=sum(1 for r in results if r.status == "passed"),
            failed=sum(1 for r in results if r.status == "failed"),
            error=sum(1 for r in results if r.status == "error"),
            skipped=sum(1 for r in results if r.status == "skipped"),
            results=results,
        )

    async def _execute_case(self, case: ToolCase) -> CaseRunResult:
        """执行单条用例 — 直接调用 Tool.call()"""
        tool = self._registry.find_by_name(case.tool_name)
        if not tool:
            return CaseRunResult(case_id=case.id, status="error", error="Tool not found")

        context = self._build_plugin_context()
        start_time = time.monotonic()

        try:
            # 直接调用工具（绕过 Agent 推理层）
            result = await asyncio.wait_for(
                tool.call(input_data=case.input_params, context=context),
                timeout=case.timeout_ms / 1000 if case.timeout_ms else 30,
            )
            latency_ms = (time.monotonic() - start_time) * 1000

            # 执行断言验证
            assertion_results = await self._run_assertions(
                case.assertions, result, latency_ms
            )

            all_passed = all(a.passed for a in assertion_results)
            return CaseRunResult(
                case_id=case.id,
                status="passed" if all_passed else "failed",
                actual_output=result.content,
                assertion_results=assertion_results,
                latency_ms=latency_ms,
            )

        except asyncio.TimeoutError:
            return CaseRunResult(case_id=case.id, status="timeout")
        except Exception as e:
            latency_ms = (time.monotonic() - start_time) * 1000
            # 逆向用例期望异常的情况
            if case.scenario_type == "negative":
                assertion_results = await self._run_assertions(
                    case.assertions, ToolResult(content=str(e), is_error=True), latency_ms
                )
                all_passed = all(a.passed for a in assertion_results)
                return CaseRunResult(
                    case_id=case.id,
                    status="passed" if all_passed else "failed",
                    actual_output=str(e),
                    assertion_results=assertion_results,
                    latency_ms=latency_ms,
                )
            return CaseRunResult(case_id=case.id, status="error", error=str(e))
```

### 5.2 API 设计

```python
# src/eval/tools/router.py

@router.post("/eval/tools/run/category/{category_id}")
async def run_category(
    category_id: int,
    filters: RunFilters = Body(default=None),
    # filters: scenario_type, tags, priority_max, is_active
):
    """执行某个工具分类下的所有用例"""
    runner = ToolCaseRunner(tool_registry, tenant_id)
    result = await runner.run_by_category(category_id, **(filters.dict() if filters else {}))
    return result


@router.post("/eval/tools/run/method/{method_id}")
async def run_method(
    method_id: int,
    filters: RunFilters = Body(default=None),
):
    """执行某个方法下的所有用例"""
    runner = ToolCaseRunner(tool_registry, tenant_id)
    result = await runner.run_by_method(method_id, **(filters.dict() if filters else {}))
    return result


@router.post("/eval/tools/run/case/{case_id}")
async def run_single(case_id: int):
    """执行单条用例"""
    runner = ToolCaseRunner(tool_registry, tenant_id)
    result = await runner.run_single_case(case_id)
    return result


@router.post("/eval/tools/run/tags")
async def run_by_tags(tags: list[str] = Body(...)):
    """按标签执行用例"""
    runner = ToolCaseRunner(tool_registry, tenant_id)
    result = await runner.run_by_tags(tags)
    return result


@router.post("/eval/tools/generate-cases/{method_id}")
async def generate_cases(
    method_id: int,
    strategy: str = Query(default="pairwise"),
):
    """根据方法 schema 自动生成参数组合用例（草稿）"""
    generator = ParamCombinationGenerator()
    method = await get_method(method_id)
    cases = generator.generate(method.input_schema, strategy=strategy)
    return {"generated_cases": cases, "count": len(cases), "status": "draft"}
```

---

## 六、与现有评测体系的集成

### 6.1 定位关系

```
┌─────────────────────────────────────────────────────────────────────────┐
│                        评测体系全景                                       │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  ┌──────────────────────────────────────────────────────────────────┐  │
│  │  Tool 评测（本文档）                                              │  │
│  │  定位: 单元测试级别                                               │  │
│  │  被测对象: 单个 Tool 的单个方法                                    │  │
│  │  不经过 Agent: 直接调用 tool.call()                               │  │
│  │  验证目标: 参数校验、返回格式、业务逻辑、异常处理、性能            │  │
│  └──────────────────────────────────────────────────────────────────┘  │
│                              ▼ 通过后                                   │
│  ┌──────────────────────────────────────────────────────────────────┐  │
│  │  Agent 评测（eval-promptfoo-scheme.md）                           │  │
│  │  定位: 集成测试级别                                               │  │
│  │  被测对象: Agent 推理引擎的工具选择与编排能力                      │  │
│  │  Tool 被 Mock: 验证 Agent 决策，不关心 Tool 实现                  │  │
│  └──────────────────────────────────────────────────────────────────┘  │
│                              ▼ 通过后                                   │
│  ┌──────────────────────────────────────────────────────────────────┐  │
│  │  Skill 评测（端到端）                                             │  │
│  │  定位: E2E 测试级别                                               │  │
│  │  被测对象: 完整业务场景                                           │  │
│  │  真实调用或半 Mock: 验证用户可感知的最终效果                       │  │
│  └──────────────────────────────────────────────────────────────────┘  │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

### 6.2 数据复用

Tool 评测用例的输入参数和期望输出可被 Agent 评测的 MockDataset 引用：

```
Tool 评测用例 LE-P003:
  input_params: {"entity_api_key": "order", "include_fields": true}
  expected_output: {"entities": [...], "fields": [...]}
        │
        ▼ 被引用为
Agent 评测 MockDataset:
  tool: query_schema
  rules:
    - when: {entity_api_key: "order", include_fields: true}
      then: {data: <来自 Tool 用例 LE-P003 的 expected_output>}
```

---

## 七、CI/CD 集成

```yaml
# .github/workflows/eval-tools.yml（示例）
eval-tools:
  triggers:
    - on_push:
        paths: ["src/tools/**"]
    - scheduled:
        cron: "0 2 * * *"  # 每天凌晨 2 点

  steps:
    - name: "P0 冒烟测试"
      run: |
        curl -X POST /eval/tools/run/tags -d '["smoke"]'
      timeout: 60s
      fail_on: any_failure

    - name: "变更工具回归"
      run: |
        # 根据 git diff 识别变更的工具，只跑对应分类
        CHANGED_TOOLS=$(detect_changed_tools)
        for tool in $CHANGED_TOOLS; do
          curl -X POST /eval/tools/run/category/$tool
        done
      timeout: 300s

    - name: "全量回归（定时）"
      run: |
        curl -X POST /eval/tools/run/tags -d '["regression"]'
      timeout: 600s
      only_on: scheduled
```

---

## 八、用例数据示例（query_schema 完整）

```yaml
# eval/tools/query_schema/seed_data.yaml

category:
  category_key: "query_schema"
  display_name: "Schema 查询工具"
  tool_name: "query_schema"

methods:
  - method_key: "list_entities"
    display_name: "列出实体列表"
    input_schema:
      type: object
      properties:
        entity_api_key: { type: string }
        include_fields: { type: boolean, default: false }
        include_relations: { type: boolean, default: false }
        page: { type: integer, minimum: 1 }
        page_size: { type: integer, minimum: 1, maximum: 200, default: 50 }
    cases:
      # ═══ 正向用例 ═══
      - case_key: "list_all_default"
        display_name: "无参数查询全部实体"
        scenario_type: positive
        input_params: {}
        assertions:
          - type: not_error
          - type: json_schema
            config:
              schema:
                type: object
                required: [entities]
                properties:
                  entities: { type: array, minItems: 1 }
          - type: response_time
            config: { max_ms: 3000 }
        tags: ["smoke", "p0"]
        priority: 1

      - case_key: "list_by_entity_key"
        display_name: "指定 entity_api_key 过滤"
        scenario_type: positive
        input_params: { "entity_api_key": "order" }
        assertions:
          - type: not_error
          - type: json_path_check
            config:
              path: "$.entities[0].api_key"
              expected: "order"
        tags: ["regression"]
        priority: 3

      - case_key: "with_fields"
        display_name: "include_fields=true 返回字段定义"
        scenario_type: positive
        input_params: { "entity_api_key": "order", "include_fields": true }
        assertions:
          - type: not_error
          - type: json_path_exists
            config: { path: "$.entities[0].fields" }
          - type: json_schema
            config:
              schema:
                type: object
                properties:
                  entities:
                    type: array
                    items:
                      required: [fields]
                      properties:
                        fields: { type: array }
        tags: ["regression"]
        priority: 3

      - case_key: "with_fields_and_relations"
        display_name: "同时包含字段和关联"
        scenario_type: positive
        input_params: { "entity_api_key": "order", "include_fields": true, "include_relations": true }
        assertions:
          - type: not_error
          - type: json_path_exists
            config: { path: "$.entities[0].fields" }
          - type: json_path_exists
            config: { path: "$.entities[0].relations" }
        tags: ["regression"]

      - case_key: "pagination_first_page"
        display_name: "分页查询第一页"
        scenario_type: positive
        input_params: { "page": 1, "page_size": 10 }
        assertions:
          - type: not_error
          - type: json_schema
            config:
              schema:
                type: object
                required: [entities, total, page, page_size]
          - type: json_path_check
            config:
              path: "$.page"
              expected: 1
        tags: ["regression"]

      # ═══ 逆向用例 ═══
      - case_key: "nonexistent_entity"
        display_name: "查询不存在的实体"
        scenario_type: negative
        input_params: { "entity_api_key": "totally_nonexistent_xyz_123" }
        assertions:
          - type: any_of
            config:
              assertions:
                - type: json_path_check
                  config: { path: "$.entities", expected: [] }
                - type: is_error
                  config: { error_contains: "not found" }
        tags: ["regression"]
        priority: 5

      - case_key: "empty_string_entity_key"
        display_name: "空字符串 entity_api_key"
        scenario_type: negative
        input_params: { "entity_api_key": "" }
        assertions:
          - type: is_error
            config: { error_contains: "invalid" }
        tags: ["boundary"]

      - case_key: "wrong_type_entity_key"
        display_name: "entity_api_key 类型错误(传入数字)"
        scenario_type: negative
        input_params: { "entity_api_key": 12345 }
        assertions:
          - type: is_error
        tags: ["boundary"]

      - case_key: "negative_page"
        display_name: "page 为负数"
        scenario_type: boundary
        input_params: { "page": -1, "page_size": 10 }
        assertions:
          - type: is_error
            config: { error_contains: "page" }
        tags: ["boundary"]

      - case_key: "zero_page_size"
        display_name: "page_size 为 0"
        scenario_type: boundary
        input_params: { "page": 1, "page_size": 0 }
        assertions:
          - type: is_error
        tags: ["boundary"]

      - case_key: "exceed_max_page_size"
        display_name: "page_size 超过最大值"
        scenario_type: boundary
        input_params: { "page": 1, "page_size": 999 }
        assertions:
          - type: any_of
            config:
              assertions:
                - type: is_error
                  config: { error_contains: "page_size" }
                - type: json_path_check
                  config: { path: "$.page_size", expected: 200 }  # 可能被截断为 max
        tags: ["boundary"]

      - case_key: "extremely_long_entity_key"
        display_name: "超长 entity_api_key (200字符)"
        scenario_type: boundary
        input_params: { "entity_api_key": "a]repeated_200_times" }
        assertions:
          - type: is_error
        tags: ["boundary"]

  - method_key: "get_entity_detail"
    display_name: "获取单个实体详情"
    input_schema:
      type: object
      required: [entity_api_key]
      properties:
        entity_api_key: { type: string }
        include_fields: { type: boolean, default: true }
        include_layouts: { type: boolean, default: false }
    cases:
      - case_key: "normal_get"
        display_name: "正常获取实体详情"
        scenario_type: positive
        input_params: { "entity_api_key": "order" }
        assertions:
          - type: not_error
          - type: json_schema
            config:
              schema:
                type: object
                required: [api_key, display_name, fields]
        tags: ["smoke", "p0"]
        priority: 1

      - case_key: "not_found"
        display_name: "实体不存在"
        scenario_type: negative
        input_params: { "entity_api_key": "nonexistent_entity" }
        assertions:
          - type: is_error
            config: { error_contains: "not found" }
        tags: ["regression"]

      - case_key: "missing_required"
        display_name: "缺少必填参数 entity_api_key"
        scenario_type: negative
        input_params: {}
        assertions:
          - type: is_error
            config: { error_contains: "required" }
        tags: ["boundary"]

  - method_key: "list_fields"
    display_name: "列出实体字段"
    input_schema:
      type: object
      required: [entity_api_key]
      properties:
        entity_api_key: { type: string }
        field_type: { type: string, enum: ["all", "custom", "system"] }
        include_options: { type: boolean, default: false }
    cases:
      - case_key: "all_fields"
        display_name: "查询全部字段"
        scenario_type: positive
        input_params: { "entity_api_key": "order" }
        assertions:
          - type: not_error
          - type: json_path_exists
            config: { path: "$.fields" }
        tags: ["smoke"]

      - case_key: "custom_fields_only"
        display_name: "仅查询自定义字段"
        scenario_type: positive
        input_params: { "entity_api_key": "order", "field_type": "custom" }
        assertions:
          - type: not_error
          - type: json_path_all_match
            config: { path: "$.fields[*].is_system", expected: false }
        tags: ["regression"]

      - case_key: "with_options"
        display_name: "包含选项值"
        scenario_type: positive
        input_params: { "entity_api_key": "order", "include_options": true }
        assertions:
          - type: not_error
        tags: ["regression"]

      - case_key: "invalid_field_type"
        display_name: "无效的 field_type 枚举值"
        scenario_type: negative
        input_params: { "entity_api_key": "order", "field_type": "invalid_type" }
        assertions:
          - type: is_error
            config: { error_contains: "field_type" }
        tags: ["boundary"]
```

---

## 九、执行结果展示

### Console 输出

```
$ POST /eval/tools/run/category/query_schema

═══════════════════════════════════════════════════════
  Tool 评测 — query_schema 分类执行报告
═══════════════════════════════════════════════════════
  Batch: batch_a3f2c9e1b8d4
  执行时间: 2024-03-15 14:23:05

── list_entities (15 cases) ──────────────────────────
  ✅ list_all_default               2ms
  ✅ list_by_entity_key             3ms
  ✅ with_fields                    5ms
  ✅ with_fields_and_relations      6ms
  ✅ pagination_first_page          4ms
  ✅ nonexistent_entity             2ms
  ✅ empty_string_entity_key        1ms
  ❌ wrong_type_entity_key          1ms
     期望: is_error=true
     实际: 未报错，返回空结果（工具做了类型强转）
  ✅ negative_page                  1ms
  ✅ zero_page_size                 1ms
  ✅ exceed_max_page_size           2ms
  ✅ extremely_long_entity_key      1ms
  ...
  Pass Rate: 14/15 (93.3%)

── get_entity_detail (8 cases) ───────────────────────
  ✅ normal_get                     4ms
  ✅ not_found                      2ms
  ✅ missing_required               1ms
  ...
  Pass Rate: 8/8 (100%)

── list_fields (6 cases) ─────────────────────────────
  ✅ all_fields                     3ms
  ✅ custom_fields_only             4ms
  ✅ with_options                   5ms
  ✅ invalid_field_type             1ms
  ...
  Pass Rate: 6/6 (100%)

── 汇总 ──────────────────────────────────────────────
┌──────────────────────┬───────────┬────────┬────────┐
│ 方法                  │ Pass Rate │ 用例数 │ 耗时    │
├──────────────────────┼───────────┼────────┼────────┤
│ list_entities        │ 93.3%     │ 15     │ 0.04s  │
│ get_entity_detail    │ 100%      │ 8      │ 0.02s  │
│ list_fields          │ 100%      │ 6      │ 0.02s  │
├──────────────────────┼───────────┼────────┼────────┤
│ query_schema 整体     │ 96.6%     │ 29     │ 0.08s  │
└──────────────────────┴───────────┴────────┴────────┘

  失败用例:
    ❌ list_entities > wrong_type_entity_key
       根因: query_schema 工具对 entity_api_key 做了隐式类型转换(int→str)
       建议: 补充显式类型校验，或修改用例期望为"非错误"
```

---

## 十、总结

| 维度 | 设计决策 |
|------|----------|
| 存储 | 数据库四表结构（分类 → 方法 → 用例 → 执行记录） |
| 执行粒度 | 分类级 / 方法级 / 用例级 / 标签级 四种粒度 |
| 参数覆盖 | 正向 + 逆向 + 边界 + 权限 四类场景，支持 pairwise 自动生成 |
| 前端交互 | 树形导航 + 表格列表 + 表单编辑 + 实时执行状态 |
| CI 集成 | 按变更工具自动回归 + 定时全量 + 冒烟快速验证 |
| 与现有体系关系 | 作为 Tool 单元测试层，位于 Agent 评测和 Skill E2E 之下 |
