# CRM SaaS 通用 Tool/Skill 体系设计

> 基于 Claude Code / Hermes Agent / neo-apps 三系统精华，面向 toB CRM SaaS 场景设计。
> 每个设计点标注参考来源：**[CC]** = Claude Code, **[HA]** = Hermes Agent, **[NA]** = neo-apps, **[NEW]** = 本方案新增。
> 与 `CRM-Agent上下文压缩详细设计方案.md` 中的四层压缩机制完全配合。

---

## 一、设计目标与约束

### 1.1 三框架必须吸收的精华

| 来源 | 精华 | 本方案对应章节 |
|------|------|--------------|
| **[CC] Claude Code** | 动态描述 `description(input)` | §二 Tool 统一接口 |
| [CC] | 延迟加载 `should_defer` + `search_hint` | §三 工具发现与延迟加载 |
| [CC] | 搜索/读取折叠 | §三 工具折叠策略 |
| [CC] | 中断行为 `cancel` / `block` | §六 三种中断类型 |
| [CC] | 每工具独立结果预算 `max_result_size_chars` | §二 输出控制 |
| [CC] | 输入回填 `backfillObservableInput` | §二 输入回填 |
| **[HA] Hermes** | 引擎暴露工具 `get_tool_schemas` | §三 ToolRegistry.get_tool_schemas |
| [HA] | 按工具类型信息摘要 `_summarize_tool_result` | §四 与上下文压缩配合 |
| [HA] | 辅助 LLM 路由（按 task 选 model） | §七 辅助 LLM 路由 |
| [HA] | 独立 Skill 概念（可复用工作流） | §五 Skill 体系 |
| **[NA] neo-apps** | 前端组件分流 | §四 Layer 1 配合 |
| [NA] | Action 元数据驱动（数据库配置） | §八 Action 元数据驱动 |
| [NA] | 三种中断类型（澄清/确认/执行中断） | §六 中断体系 |
| [NA] | 虚拟文件 FileInfo | §四 虚拟文件引用 |

### 1.2 与上下文压缩的配合约束

本方案中的每个 Tool 设计决策都必须与上下文压缩方案的四层机制配合：

```
Tool 输出 → Layer 1（源头隔离）→ Layer 2（轮次裁剪）→ Layer 3（回复摘要）→ Layer 4（历史构建）
              ↑                    ↑                    ↑
              Tool 的               Tool 的               Skill 的
              max_result_size_chars  摘要模板              执行结果
              + 前端组件分流         _summarize_crm_tool   answerSummary
```

### 1.3 设计原则

```
1. Tool 是 LLM 的手 — 一次调用，一次返回，无状态
2. Skill 是 Agent 的 SOP — 多步编排，有策略，有判断
3. Plugin 是系统的器官 — 可插拔基础设施，有生命周期
4. 三者单向依赖: Skill 编排 Tool → Tool 调用 Plugin → Plugin 不知道 Tool 的存在
5. ToolRegistry 是工具的唯一真相源 — Plugin 不直接注册 Tool
6. 每个 Tool 自带压缩元数据 — 与 Layer 1/Layer 2 无缝衔接
```


---

## 二、Tool 统一接口

### 2.1 完整接口定义 [CC+HA+NA+NEW]

四组字段，每组标注来源：

```python
class Tool(ABC):
    """
    工具基类。四组字段:
    - 核心（必须实现）: name, input_schema, call, description
    - 注册与发现（可选覆盖）: aliases, search_hint, is_enabled, should_defer, tags
    - 安全与权限（可选覆盖）: validate_input, check_permissions, is_read_only, is_destructive
    - 输出控制（可选覆盖）: max_result_size_chars, prompt, backfill_observable_input
    - 压缩协作（可选覆盖）: summary_threshold, summary_max_words, render_type, code_extractable
    """

    # ═══════ 核心（必须实现） ═══════

    @property
    @abstractmethod
    def name(self) -> str:
        """工具唯一名称，如 "query_schema"、"web_search"。"""
        ...

    @abstractmethod
    def input_schema(self) -> dict:
        """
        JSON Schema 格式的输入定义。[CC+HA]
        LLM 通过此 schema 生成工具调用参数。
        必须包含 type, properties, required 三个字段。
        """
        ...

    @abstractmethod
    async def call(
        self,
        input_data: dict,
        context: PluginContext,
        on_progress: Callable[[str], None] | None = None,
    ) -> ToolResult:
        """
        执行工具。[CC+HA+NA]
        
        参数:
            input_data: 符合 input_schema 的参数字典
            context: Plugin 上下文（可访问 llm/memory/tenant_id/user_id 等）
            on_progress: 进度回调（长时间执行时报告中间状态）
        返回:
            ToolResult（content + is_error + metadata + render_hint）
        异常:
            不应抛出异常，所有错误通过 ToolResult.is_error=True 返回
        """
        ...

    async def description(self, input_data: dict) -> str:
        """
        动态描述 [CC] — 根据实际参数生成人类可读的操作描述。
        
        Claude Code 精华: description 不是静态字符串，而是 description(input) 函数。
        用于审计日志和前端展示（如"查询华为的工商信息"而非"调用 company_info"）。
        
        场景举例:
          company_info(keyword="华为") → "查询华为的基本工商信息"
          query_data(action="delete", entity="lead") → "删除 lead 记录"
          web_search(query="Odoo pricing") → "搜索 'Odoo pricing'"
        """
        return self.name

    # ═══════ 注册与发现 [CC] ═══════

    @property
    def aliases(self) -> list[str]:
        """别名列表。LLM 可能用不同名称调用同一工具（向后兼容）。"""
        return []

    @property
    def search_hint(self) -> str | None:
        """
        搜索提示关键词 [CC]。当工具数量多时，帮助 LLM 找到正确工具。
        如 company_info 的 search_hint = "企业 公司 工商 注册资本 法人 股东"
        
        与 should_defer 配合: 延迟加载的工具只有通过 search_hint 匹配才会出现。
        """
        return None

    def is_enabled(self, context: PluginContext) -> bool:
        """
        运行时开关 [CC+NEW]。返回 False 时工具不出现在 LLM 的工具列表中。
        
        与 Plugin 的关系: 依赖 Plugin 的工具通过此方法检查 Plugin 是否可用。
        如 web_search.is_enabled() = context.search is not None
        """
        return True

    @property
    def should_defer(self) -> bool:
        """
        延迟加载 [CC]。True 时工具不在初始 schema 列表中，
        只有 LLM 通过 search_hint 搜索到时才加载。
        
        适用于不常用的工具，减少初始 token 消耗。
        CRM 场景: financial_report、company_info 等低频工具设为 defer。
        """
        return False

    @property
    def tags(self) -> list[str]:
        """
        工具标签 [NEW]。用于分类、过滤、权限控制。
        如 ["read", "crm", "data"] 或 ["write", "external", "destructive"]
        
        与 Hook 的 toolTypes 配合: preToolUse hook 可按 tag 过滤。
        """
        return []

    # ═══════ 安全与权限 [CC+NA] ═══════

    def validate_input(self, input_data: dict) -> ValidationResult:
        """
        输入校验 [CC] — 在 call() 之前执行。
        校验失败时错误信息作为 tool_result 返回给 LLM，让 LLM 自行修正参数。
        """
        return ValidationResult(valid=True)

    async def check_permissions(
        self, input_data: dict, context: PluginContext
    ) -> PermissionDecision:
        """
        工具级权限检查 [CC+NA] — 比 Middleware 更细粒度。
        返回 ALLOW / DENY / ASK。
        """
        return PermissionDecision(behavior="allow")

    def is_read_only(self, input_data: dict) -> bool:
        """
        是否只读操作 [CC]（根据实际参数判断）。
        只读工具可并行执行，写操作串行。
        """
        return False

    def is_destructive(self, input_data: dict) -> bool:
        """
        是否破坏性操作 [CC+NA]（根据实际参数判断）。
        破坏性操作触发 HITLMiddleware 审批（§六 中断体系）。
        """
        return False

    # ═══════ 输出控制 [CC] ═══════

    @property
    def max_result_size_chars(self) -> int:
        """
        每工具独立结果预算 [CC]。超出时自动截断。
        
        不同工具有不同预算:
        - query_data: 50,000（查询结果可能很大）
        - web_search: 30,000
        - query_schema: 100,000（元数据定义需要完整）
        - ask_user: 无限制
        
        与 Layer 1 的关系: 截断在 Layer 1 摘要之前执行，
        确保进入摘要流程的文本不会过大。
        """
        return 50_000

    def prompt(self) -> str:
        """
        工具使用说明 [CC+HA]，注入到 system prompt 中。
        LLM 通过此说明理解何时、如何使用此工具。
        """
        return ""

    def backfill_observable_input(self, input_data: dict) -> dict | None:
        """
        输入回填 [CC] — 将 LLM 不可见的自动注入参数暴露给用户。
        
        场景: TenantMiddleware 自动注入 _tenant_id，但 LLM 生成的参数中没有。
        回填后前端可以展示完整的工具调用参数（含 tenant_id）。
        
        返回 None 表示不回填（使用原始 input_data）。
        返回 dict 表示回填后的完整参数。
        """
        return None

    # ═══════ 压缩协作 [NEW — 与上下文压缩方案配合] ═══════

    @property
    def summary_threshold(self) -> int:
        """
        摘要触发阈值 [NEW]。工具结果超过此字符数时触发 Layer 1 摘要。
        
        与上下文压缩方案的 SUMMARY_THRESHOLDS 对应:
        - 查询类: 300（信息密度低，摘要即可）
        - 分析类: 800（需要保留推理依据）
        - 报价类: 1500（含精确数字，摘要必须保留金额/折扣/日期）
        """
        return 500  # 默认值

    @property
    def summary_max_words(self) -> int:
        """摘要字数上限 [NEW]。与 summary_threshold 配合。"""
        return 150  # 默认值

    @property
    def render_type(self) -> str | None:
        """
        前端渲染类型 [NA]。非 None 时工具结果通过前端组件渲染，不进入 LLM 上下文。
        
        与 Layer 1 前端组件分流配合:
        - "pipeline_dashboard" → Pipeline 仪表盘
        - "bant_analysis" → BANT 四象限卡片
        - "customer_profile" → 客户画像卡片
        - None → 纯文本，走 LLM 上下文
        """
        return None

    @property
    def code_extractable(self) -> bool:
        """
        是否支持代码格式化提取 [HA+NEW]。
        True 时 Layer 1 优先用零 LLM 成本的代码规则提取摘要。
        
        适用于返回结构化数据的工具（JSON 列表、组件数据）。
        """
        return False
```

### 2.2 ToolResult 扩展 [CC+NA+NEW]

```python
@dataclass
class ToolResult:
    """工具执行结果"""
    content: str                          # 结果文本（返回给 LLM）
    is_error: bool = False                # 是否失败
    metadata: dict = field(default_factory=dict)  # 附加元数据（不返回给 LLM）
    
    # [NA] 前端渲染提示
    render_hint: RenderHint | None = None
    
    # [NEW] 压缩提示 — 告诉 Layer 1 如何处理此结果
    virtual_file: FileInfo | None = None  # 原文保存为虚拟文件


@dataclass
class RenderHint:
    """前端渲染提示 [NA] — 告诉前端如何展示工具结果"""
    render_type: str                      # 组件类型（pipeline_dashboard, bant_analysis 等）
    schema: dict | None = None            # 组件 schema
    props_data: dict | None = None        # 组件数据
    template: str | None = None           # 文本化模板（Layer 1 CustomContent 文本化用）


@dataclass
class FileInfo:
    """虚拟文件 [NA] — 保留工具结果原文，供后续引用"""
    file_path: str                        # 虚拟路径（如 /action_result/query_001）
    content: str                          # 完整原文
    summary: str                          # 摘要（Layer 1 生成）
    extend: dict = field(default_factory=dict)  # 扩展信息
```


---

## 三、工具注册、发现与延迟加载

### 3.1 ToolRegistry [CC+HA]

```python
class ToolRegistry:
    """
    工具注册表 — 工具的唯一真相源。
    
    融合:
    - [CC] assembleToolPool + findToolByName + aliases
    - [HA] get_tool_schemas（引擎暴露工具定义给 LLM）
    - [NEW] 延迟加载池 + 搜索匹配
    """

    def __init__(self):
        self._tools: dict[str, Tool] = {}           # 已激活工具
        self._deferred: dict[str, Tool] = {}         # 延迟加载池
        self._alias_map: dict[str, str] = {}         # 别名 → 规范名
        self._search_index: dict[str, list[str]] = {}  # 关键词 → 工具名列表

    def register(self, tool: Tool) -> None:
        """注册工具。should_defer=True 的工具进入延迟池。"""
        if tool.should_defer:
            self._deferred[tool.name] = tool
        else:
            self._tools[tool.name] = tool
        # 注册别名
        for alias in tool.aliases:
            self._alias_map[alias] = tool.name
        # 建立搜索索引
        if tool.search_hint:
            for keyword in tool.search_hint.split():
                self._search_index.setdefault(keyword, []).append(tool.name)

    def unregister(self, name: str) -> None:
        self._tools.pop(name, None)
        self._deferred.pop(name, None)

    def find_by_name(self, name: str) -> Tool | None:
        """
        按名称查找工具 [CC]。支持别名。
        如果在延迟池中找到，自动激活（移入已激活池）。
        """
        # 先查已激活
        if name in self._tools:
            return self._tools[name]
        # 查别名
        canonical = self._alias_map.get(name)
        if canonical and canonical in self._tools:
            return self._tools[canonical]
        # 查延迟池（找到则激活）
        if name in self._deferred:
            tool = self._deferred.pop(name)
            self._tools[name] = tool
            return tool
        if canonical and canonical in self._deferred:
            tool = self._deferred.pop(canonical)
            self._tools[canonical] = tool
            return tool
        return None

    def search_tools(self, query: str) -> list[Tool]:
        """
        搜索工具 [CC search_hint]。
        在延迟池和已激活池中搜索匹配 search_hint 的工具。
        匹配到的延迟工具自动激活。
        """
        keywords = query.lower().split()
        matched_names: set[str] = set()
        for kw in keywords:
            for index_kw, tool_names in self._search_index.items():
                if kw in index_kw.lower():
                    matched_names.update(tool_names)
        
        results = []
        for name in matched_names:
            tool = self.find_by_name(name)  # 自动激活延迟工具
            if tool:
                results.append(tool)
        return results

    def get_tool_schemas(self, context: PluginContext) -> list[dict]:
        """
        返回所有已激活且已启用工具的 LLM function calling 格式定义 [HA]。
        
        Hermes 精华: 引擎暴露 get_tool_schemas 给 LLM，
        LLM 可以在 reasoning 中查看可用工具列表。
        
        与延迟加载的关系: 延迟工具不在此列表中，
        直到 LLM 通过 search_tools 搜索到并激活。
        """
        schemas = []
        for tool in self._tools.values():
            if tool.is_enabled(context):
                schemas.append({
                    "name": tool.name,
                    "description": tool.prompt() or f"Tool: {tool.name}",
                    "input_schema": tool.input_schema(),
                    "tags": tool.tags,
                })
        return schemas

    def get_deferred_hints(self) -> list[dict]:
        """
        返回延迟工具的搜索提示 [CC+NEW]。
        注入到 system prompt 中，让 LLM 知道还有哪些工具可以搜索激活。
        
        格式: [{"name": "financial_report", "hint": "上市公司 财报 利润表 资产负债表"}]
        """
        return [
            {"name": t.name, "hint": t.search_hint or t.name}
            for t in self._deferred.values()
        ]

    @property
    def all_tools(self) -> list[Tool]:
        return list(self._tools.values())

    @property
    def all_deferred(self) -> list[Tool]:
        return list(self._deferred.values())
```

### 3.2 延迟加载策略 [CC]

```
初始化时:
  ToolRegistry 注册 15 个工具
  ├── 9 个常用工具 → 直接激活（should_defer=False）
  │   query_schema, query_data, analyze_data, query_permission,
  │   ask_user, delegate_task, start_async_task,
  │   search_memories, save_memory
  │
  └── 6 个低频工具 → 延迟池（should_defer=True）
      web_search, company_info, financial_report,
      api_call, mcp_tool, send_notification

System Prompt 注入:
  "以下工具可通过搜索激活（当前未加载）:
   - financial_report: 上市公司 财报 利润表 资产负债表 现金流
   - company_info: 企业 公司 工商 注册资本 法人 股东
   - web_search: 搜索 网络 查询 最新信息
   - api_call: 外部API 接口调用 第三方
   - mcp_tool: MCP 扩展工具
   - send_notification: 通知 消息 推送 提醒
   如需使用，请先描述你的需求，系统会自动匹配并加载对应工具。"

LLM 请求使用延迟工具时:
  LLM: tool_use(name="company_info", input={keyword:"华为"})
  → registry.find_by_name("company_info")
  → 在延迟池中找到 → 自动激活 → 执行
  → 后续 reasoning 中 company_info 出现在 get_tool_schemas() 中
```

**CRM 场景中的收益**:

```
初始 schema token 消耗:
  9 个常用工具 × ~200 tokens/工具 = ~1,800 tokens
  vs 全部 15 个: ~3,000 tokens
  节省: 40% 初始 schema token

大部分 CRM 对话（查客户→查商机→回复）只用 3-4 个工具，
延迟的 6 个工具从未被加载 → 每轮对话节省 ~1,200 tokens
```

### 3.3 工具折叠策略 [CC]

Claude Code 的搜索/读取折叠思路：连续多次调用同类工具时，在上下文中折叠为摘要。

```python
class ToolFoldingStrategy:
    """
    工具折叠策略 [CC] — 连续同类工具调用折叠为摘要。
    
    与 Layer 2 Pass 1（MD5 去重）互补:
    - MD5 去重: 完全相同的结果去重
    - 折叠: 不同参数但同类工具的结果合并展示
    """

    # 可折叠的工具组
    FOLDABLE_GROUPS = {
        "search": ["web_search", "search_memories"],
        "query": ["query_data", "query_schema", "query_permission"],
        "external": ["company_info", "financial_report"],
    }

    @staticmethod
    def should_fold(tool_calls: list[ToolCallRecord]) -> bool:
        """连续 3+ 次调用同组工具时触发折叠"""
        if len(tool_calls) < 3:
            return False
        group = ToolFoldingStrategy._get_group(tool_calls[-1].tool_name)
        if not group:
            return False
        consecutive = 0
        for tc in reversed(tool_calls):
            if ToolFoldingStrategy._get_group(tc.tool_name) == group:
                consecutive += 1
            else:
                break
        return consecutive >= 3

    @staticmethod
    def fold(tool_calls: list[ToolCallRecord]) -> str:
        """
        将连续同组工具调用折叠为一行摘要。
        
        场景举例:
          连续 5 次 query_data 查询不同实体 →
          "[折叠] 查询了 account/opportunity/lead/contact/activity 共 5 个实体"
        """
        group = ToolFoldingStrategy._get_group(tool_calls[-1].tool_name)
        names = [tc.tool_name for tc in tool_calls if ToolFoldingStrategy._get_group(tc.tool_name) == group]
        args_summary = [_extract_key_arg(tc) for tc in tool_calls[-len(names):]]
        return f"[折叠] 执行了 {len(names)} 次 {group} 类操作: {', '.join(args_summary)}"
```


---

## 四、与上下文压缩机制的配合

### 4.1 Tool 输出 → Layer 1 源头隔离

每个 Tool 通过三个压缩协作字段告诉 Layer 1 如何处理其输出：

```python
# 工具压缩元数据配置（从 Tool 接口字段自动提取）
def get_tool_compression_config(tool: Tool) -> dict:
    """从 Tool 实例提取压缩配置，供 Layer 1 使用"""
    return {
        "threshold": tool.summary_threshold,
        "max_words": tool.summary_max_words,
        "render_type": tool.render_type,
        "code_extractable": tool.code_extractable,
    }
```

**各工具的压缩配置一览 [NEW]**:

| 工具 | summary_threshold | summary_max_words | render_type | code_extractable | 说明 |
|------|:-:|:-:|:-:|:-:|------|
| query_data | 300 | 100 | 按实体动态 | True | 列表数据，信息密度低 |
| query_schema | 500 | 150 | None | True | 元数据定义，JSON 结构化 |
| analyze_data | 800 | 200 | 按分析类型动态 | True | 聚合结果，需保留推理依据 |
| query_permission | 500 | 150 | None | True | 权限配置，结构化 |
| web_search | 500 | 150 | None | False | 非结构化文本，需 LLM 摘要 |
| company_info | 800 | 200 | customer_profile | True | 工商数据，结构化 JSON |
| financial_report | 1500 | 300 | financial_table | True | 含精确数字，必须保留金额 |
| api_call | 500 | 150 | None | False | 返回格式不确定 |
| ask_user | ∞ | - | None | False | 用户输入不摘要 |
| search_memories | 300 | 100 | None | True | 记忆条目，结构化 |
| save_memory | ∞ | - | None | False | 写入确认，通常很短 |
| delegate_task | 500 | 200 | None | False | 子 Agent 结果，已经是摘要 |
| send_notification | ∞ | - | None | False | 发送确认，通常很短 |

### 4.2 Layer 1 处理流程（与 Tool 接口的衔接）

```python
async def process_tool_result(tool: Tool, result: ToolResult, state) -> tuple[str, str]:
    """
    Layer 1 源头隔离 — 处理单个工具的执行结果。
    
    输入: Tool 实例 + ToolResult
    输出: (original_text, context_text)
      - original_text: 完整原文（存入虚拟文件）
      - context_text: 进入 LLM 上下文的文本（可能是摘要）
    """
    original_text = result.content
    
    # Step 1: 前端组件分流 [NA]
    if result.render_hint and result.render_hint.render_type:
        # 推送给前端渲染，不进入 LLM 上下文
        await neo_ai_emit_custom(
            config=state.config,
            data=result.render_hint.props_data,
            render_type=result.render_hint.render_type,
            schema=result.render_hint.schema,
        )
        # 但仍然需要生成摘要给 LLM（LLM 需要知道发生了什么）
    
    # Step 2: 检查是否需要摘要（使用 Tool 自带的阈值）
    threshold = tool.summary_threshold
    if len(original_text) <= threshold:
        return original_text, original_text  # 不摘要
    
    # Step 3: 两层摘要策略 [HA+NA+NEW]
    # 第一层: 代码格式化提取（零 LLM 成本）
    if tool.code_extractable:
        code_summary = try_code_extract(tool.name, result)
        if code_summary:
            # 保存虚拟文件 [NA]
            virtual_file = FileInfo(
                file_path=f"/action_result/{tool.name}_{state.step_count}",
                content=original_text,
                summary=code_summary,
            )
            state.file_list.append(virtual_file)
            return original_text, code_summary
    
    # 第二层: LLM 摘要（代码提取失败时降级）
    max_words = tool.summary_max_words
    model = agent_summary_model()  # [HA] 辅助 LLM 路由
    summary = await model.ainvoke([
        HumanMessage(content=SUMMARY_PROMPT.format(
            text=original_text,
            max_words=max_words,
            language_name=state.language_name,
        ))
    ])
    
    # 保存虚拟文件 [NA]
    virtual_file = FileInfo(
        file_path=f"/action_result/{tool.name}_{state.step_count}",
        content=original_text,
        summary=summary.content,
    )
    state.file_list.append(virtual_file)
    
    return original_text, summary.content
```

### 4.3 Layer 2 摘要模板（与 Tool 的 tags 配合）[HA+NEW]

```python
def _summarize_crm_tool_result(tool: Tool, tool_args: dict, tool_content: str) -> str:
    """
    CRM 工具专用信息摘要 [HA _summarize_tool_result 模式 + NEW CRM 内容]。
    零 LLM 成本，用于 Layer 2 Pass 2 保护区外的旧 ToolMessage 替换。
    
    与 Tool 接口的关系: 使用 tool.name 和 tool.tags 选择摘要模板。
    """
    name = tool.name
    
    if name == "query_data":
        entity = tool_args.get("entity_api_key", "?")
        action = tool_args.get("action", "query")
        count = _extract_record_count(tool_content)
        amount = _extract_total_amount(tool_content)
        amount_str = f", 总金额{amount}" if amount else ""
        return f"[{name}] {action} {entity}，{count} 条记录{amount_str}"
    
    if name == "query_schema":
        entity = tool_args.get("entity_api_key", "?")
        query_type = tool_args.get("query_type", "entity")
        return f"[{name}] {query_type} {entity}"
    
    if name == "analyze_data":
        entity = tool_args.get("entity_api_key", "?")
        metrics = tool_args.get("metrics", [])
        funcs = [m.get("function", "?") for m in metrics[:3]]
        return f"[{name}] {entity} {'/'.join(funcs)} ({len(tool_content):,} chars)"
    
    if name == "web_search":
        query = tool_args.get("query", "?")[:40]
        return f"[{name}] '{query}' ({len(tool_content):,} chars)"
    
    if name == "company_info":
        keyword = tool_args.get("keyword", "?")
        query_type = tool_args.get("query_type", "basic")
        return f"[{name}] {keyword} {query_type} ({len(tool_content):,} chars)"
    
    if name == "financial_report":
        stock = tool_args.get("stock_code", "?")
        report_type = tool_args.get("report_type", "income_statement")
        return f"[{name}] {stock} {report_type} ({len(tool_content):,} chars)"
    
    if name == "modify_data":
        entity = tool_args.get("entity_api_key", "?")
        action = tool_args.get("action", "update")
        record_name = _extract_record_name(tool_content)
        return f"[{name}] {action} {entity}({record_name})"
    
    if name == "delegate_task":
        task = tool_args.get("task", "?")[:50]
        return f"[{name}] '{task}' ({len(tool_content):,} chars)"
    
    # 通用 fallback — 使用 tags 提供额外信息
    tag_str = ",".join(tool.tags[:2]) if tool.tags else ""
    first_arg = str(next(iter(tool_args.values()), ""))[:40]
    return f"[{name}] {first_arg} ({len(tool_content):,} chars) [{tag_str}]"
```

### 4.4 虚拟文件引用 [NA]

```
工具执行完毕后，Layer 1 生成虚拟文件:

  FileInfo(
    file_path="/action_result/query_data_1",
    content="[100条商机的完整JSON]",           ← 完整原文（35K chars）
    summary="100条商机, 总金额$3.6M, ...",     ← 摘要（80 chars）
    extend={"entity": "opportunity", "total": 100}
  )

LLM 上下文中只有摘要（80 chars）。
如果 LLM 后续需要某条商机的具体字段值:
  → LLM 可以引用虚拟文件路径
  → 引擎从 state.file_list 中查找并返回原文片段
  → 不需要重新调用 query_data

与 Layer 4 的关系:
  虚拟文件也作为 file_list 传给意图识别节点，
  意图识别可以从 summary 快速判断上下文中有哪些数据。
```


---

## 五、Skill 体系

### 5.1 Skill 定义 [HA+CC+NA]

```python
@dataclass
class SkillDefinition:
    """
    技能定义 — 一段业务知识 + 执行策略的 prompt 模板。
    
    融合:
    - [HA] 独立 Skill 概念: .md 文件定义，可复用工作流
    - [CC] bundledSkills: 内置技能 + 文件加载 + 动态创建
    - [NA] 子 Agent 预定义类型: verifier/analyzer/researcher
    - [NEW] CRM 业务技能: 配置向导/数据分析/权限审计
    """
    name: str                                    # 技能名称
    description: str                             # 一行描述
    
    # 发现与匹配
    aliases: list[str] = field(default_factory=list)
    when_to_use: str | None = None               # 何时使用（LLM 判断依据）
    argument_hint: str | None = None             # 参数提示
    
    # 执行配置
    context: str = "fork"                        # "inline" | "fork"
    allowed_tools: list[str] | None = None       # 限制可用工具（None=继承主Agent）
    model: str | None = None                     # 指定模型（None=使用主模型）
    max_llm_calls: int = 20                      # 最大 LLM 调用次数
    
    # 内容
    get_prompt: Callable[..., Awaitable[str]] | None = None  # 动态 prompt 生成
    files: dict[str, str] = field(default_factory=dict)      # 附带文件
    
    # 来源
    source: str = "bundled"                      # bundled / project / user / plugin / db
    
    # [NEW] CRM 扩展
    entity_scope: list[str] | None = None        # 适用的业务对象（如 ["opportunity", "account"]）
    requires_plugins: list[str] | None = None    # 依赖的 Plugin（如 ["memory-plugin"]）
```

### 5.2 Skill 与 Tool 的本质区别

```
判断标准:
  Q1: LLM 能一次调用完成吗？ → 是 → Tool
  Q2: 需要多步推理、多次 Tool 调用？ → 是 → Skill
  Q3: 是引擎内部机制（用户不感知）？ → 是 → 引擎内置逻辑（不是 Skill）

示例:
  query_data(entity="account", filters={...})
    → 一次调用，一次返回 → Tool ✅

  "诊断为什么客户看不到某条商机"
    → 需要: 查权限配置 → 查角色 → 查共享规则 → 查数据权限 → 分析原因
    → 多步推理 → Skill ✅

  "Agent 卡住了，需要自救"
    → 引擎内部机制（ReflectionNode 的一部分）
    → 不是 Skill ❌ → 引擎内置逻辑
```

### 5.3 CRM 内置 Skill 清单 [HA+CC+NA+NEW]

| Skill | 功能 | 执行方式 | 允许的工具 | 来源 |
|-------|------|---------|-----------|------|
| verify_config | 元数据配置校验 | inline | query_schema | [CC] verify 思路 + [NEW] CRM 适配 |
| diagnose | 业务问题诊断 | fork | query_schema, query_data, query_permission, search_memories | [CC] debug 思路 + [NEW] CRM 适配 |
| config_entity | 业务对象配置向导 | fork | query_schema, query_data, ask_user | [NA] 子 Agent 类型 + [NEW] |
| batch_data | 批量数据操作 | fork | query_data, ask_user | [CC] batch 思路 + [NEW] CRM 适配 |
| data_analysis | 业务数据分析 | fork | query_schema, query_data, analyze_data | [HA] Skill 概念 + [NEW] CRM 适配 |
| migration | 数据迁移 | fork | query_schema, query_data, ask_user | [NEW] CRM 业务需求 |
| permission_audit | 权限审计 | fork | query_permission, query_data, query_schema | [NEW] CRM 业务需求 |
| skillify | 操作转技能 | fork | 全部 | [CC] skillify 原版 |
| competitive_analysis | 竞品分析 | fork | web_search, company_info, financial_report, query_data | [NEW] CRM 销售场景 |
| customer_onboarding | 客户入职引导 | fork | query_data, query_schema, ask_user, send_notification | [NEW] CRM 业务需求 |
| deal_coaching | 商机辅导 | fork | query_data, analyze_data, search_memories | [NEW] CRM 销售场景 |
| report_generation | 报告生成 | fork | query_data, analyze_data, web_search | [NEW] CRM 管理场景 |

**去掉的（不应该是 Skill 的）**:
- ~~stuck~~ → 移入 ReflectionNode 内置逻辑
- ~~remember~~ → LLM 直接调用 save_memory 工具
- ~~reflect~~ → 移入 ReflectionNode 内置逻辑
- ~~iterate~~ → 移入 PlanningNode 的规划策略
- ~~loop~~ → 移入 ExecutionNode 的重试策略

### 5.4 Skill 执行模式 [CC+HA+NA]

```python
class SkillExecutor:
    """
    技能执行器 — 根据 context 字段选择执行模式。
    
    两种模式:
    - inline: 将 Skill prompt 注入当前对话上下文，不启动子 Agent
    - fork: 启动子 Agent 执行，结果通过 delegate_task 返回
    """

    async def execute(
        self,
        skill: SkillDefinition,
        args: str,
        state: GraphState,
        context: PluginContext,
    ) -> SkillResult:
        prompt = await skill.get_prompt(args=args)
        
        if skill.context == "inline":
            return await self._execute_inline(skill, prompt, state)
        else:
            return await self._execute_fork(skill, prompt, args, state, context)

    async def _execute_inline(self, skill, prompt, state) -> SkillResult:
        """
        Inline 模式 [CC]: 将 prompt 注入当前对话。
        适用于轻量级技能（verify_config 等）。
        不启动子 Agent，不消耗额外 session。
        """
        # 将 Skill prompt 作为 SystemMessage 追加到当前消息列表
        state.messages.append(Message(
            role=MessageRole.SYSTEM,
            content=f"[SKILL: {skill.name}]\n{prompt}",
        ))
        return SkillResult(mode="inline", injected=True)

    async def _execute_fork(self, skill, prompt, args, state, context) -> SkillResult:
        """
        Fork 模式 [NA+HA]: 启动子 Agent 执行。
        适用于复杂技能（diagnose, data_analysis 等）。
        
        子 Agent 工具集 = 主 Agent 工具集 ∩ skill.allowed_tools
        """
        # 构建子 Agent 配置
        sub_config = AgentConfig(
            tenant_id=state.tenant_id,
            user_id=state.user_id,
            llm_plugin_config=context.llm.config,
            enabled_tools=skill.allowed_tools,
            max_total_llm_calls=skill.max_llm_calls,
            system_prompt_append=prompt,
        )
        
        # 使用辅助 LLM 路由 [HA]
        if skill.model:
            sub_config.llm_plugin_config.model = skill.model
        
        sub_engine = await AgentFactory.create(sub_config)
        sub_state = GraphState(
            session_id=f"{state.session_id}__skill_{skill.name}",
            tenant_id=state.tenant_id,
            user_id=state.user_id,
            messages=[Message(role=MessageRole.USER, content=args or skill.description)],
        )
        
        final_state = await sub_engine.run_to_completion(sub_state)
        return SkillResult(
            mode="fork",
            content=final_state.final_answer,
            tool_calls_count=final_state.total_tool_calls,
        )
```

### 5.5 Skill 注册表 [HA+CC]

```python
class SkillRegistry:
    """
    技能注册表 — 多源加载 + 动态发现。
    
    加载顺序（后加载的覆盖先加载的）:
    1. 内置技能（bundled）
    2. 项目技能（.kiro/skills/*.md）
    3. 用户技能（~/.kiro/skills/*.md）
    4. Plugin 提供的技能
    5. 数据库配置的技能（Action 元数据驱动，§八）
    """

    def __init__(self):
        self._skills: dict[str, SkillDefinition] = {}
        self._alias_map: dict[str, str] = {}

    def register(self, skill: SkillDefinition) -> None:
        self._skills[skill.name] = skill
        for alias in skill.aliases:
            self._alias_map[alias] = skill.name

    def find(self, name: str) -> SkillDefinition | None:
        if name in self._skills:
            return self._skills[name]
        canonical = self._alias_map.get(name)
        return self._skills.get(canonical) if canonical else None

    def match_by_intent(self, intent: str, entity: str | None = None) -> SkillDefinition | None:
        """
        根据意图和实体匹配最佳技能 [NEW]。
        PlanningNode 在规划阶段调用此方法。
        """
        for skill in self._skills.values():
            if skill.when_to_use and intent.lower() in skill.when_to_use.lower():
                if entity and skill.entity_scope and entity not in skill.entity_scope:
                    continue
                return skill
        return None

    def load_from_directory(self, directory: str, source: str = "project") -> int:
        """从 .md 文件加载技能 [CC+HA]"""
        loaded = 0
        skills_dir = Path(directory)
        if not skills_dir.is_dir():
            return 0
        for md_file in skills_dir.rglob("*.md"):
            skill = self._parse_skill_file(md_file, source)
            if skill:
                self.register(skill)
                loaded += 1
        return loaded

    def load_from_db(self, tenant_id: str, db_skills: list[dict]) -> int:
        """
        从数据库加载技能 [NA Action 元数据驱动]。
        租户可以在管理后台配置自定义技能。
        """
        loaded = 0
        for skill_data in db_skills:
            skill = self._parse_db_skill(skill_data, tenant_id)
            if skill:
                self.register(skill)
                loaded += 1
        return loaded

    @property
    def all_skills(self) -> list[SkillDefinition]:
        return list(self._skills.values())
```


---

## 六、中断体系

### 6.1 三种中断类型 [CC+NA]

融合 Claude Code 的 `cancel`/`block` 和 neo-apps 的三种中断类型：

```python
class InterruptType(str, Enum):
    """
    中断类型 — 融合 [CC] cancel/block + [NA] 澄清/确认/执行中断
    """
    # ─── 来自 [NA] neo-apps ───
    CLARIFY = "clarify"          # 澄清中断: Agent 需要用户补充信息才能继续
    CONFIRM = "confirm"          # 确认中断: Agent 即将执行危险操作，需要用户确认
    EXECUTION = "execution"      # 执行中断: 长时间执行中，用户可以取消
    
    # ─── 来自 [CC] Claude Code ───
    CANCEL = "cancel"            # 取消中断: 用户主动取消当前操作
    BLOCK = "block"              # 阻塞中断: 权限/配额/系统限制导致无法继续


@dataclass
class InterruptRequest:
    """中断请求"""
    type: InterruptType
    reason: str                           # 中断原因（展示给用户）
    tool_name: str | None = None          # 触发中断的工具
    tool_input: dict | None = None        # 工具参数（confirm 时展示）
    options: list[str] | None = None      # 用户可选项（clarify 时提供）
    timeout_seconds: int = 300            # 超时时间（超时自动取消）
    
    # [CC] 中断行为配置
    on_timeout: str = "cancel"            # 超时行为: cancel / block / retry
    resumable: bool = True                # 是否可恢复


@dataclass
class InterruptResponse:
    """中断响应"""
    action: str                           # "approve" / "reject" / "cancel" / "clarify_answer"
    data: dict | None = None              # 用户提供的额外数据
```

### 6.2 中断触发点

```
工具执行链路中的中断触发点:

  LLM 返回 tool_use
    │
    ├── [1] validate_input → 校验失败
    │   → 不中断，错误返回给 LLM 自行修正
    │
    ├── [2] check_permissions → DENY
    │   → BLOCK 中断: "权限不足: {reason}"
    │   → 用户无法恢复（需要管理员授权）
    │
    ├── [3] check_permissions → ASK
    │   → CONFIRM 中断: "操作需要确认: {description}"
    │   → 用户可以 approve / reject
    │
    ├── [4] HITLMiddleware → is_destructive
    │   → CONFIRM 中断: "即将删除 {N} 条记录，是否确认？"
    │   → 用户可以 approve / reject
    │
    ├── [5] tool.call() 执行中
    │   → EXECUTION 中断: 用户可以随时取消
    │   → 取消后 → CANCEL 中断 → 清理资源
    │
    └── [6] Skill 执行中需要用户输入
        → CLARIFY 中断: "请提供以下信息: {options}"
        → 用户回答后恢复执行
```

### 6.3 中断与上下文压缩的关系

```
CONFIRM 中断时:
  state.status = PAUSED
  state.pause_reason = InterruptRequest(...)
  
  Layer 3 sessionSummary 更新:
    ## 待处理
    等待用户确认: 删除 lead 实体的 1247 条过期记录
  
  用户恢复后:
    Layer 4 从 Redis 加载 sessionSummary → LLM 知道之前在等什么
    → 继续执行被中断的操作

CLARIFY 中断时:
  ask_user 工具返回 → 用户回答作为 ToolResult 进入上下文
  → Layer 1 不摘要（ask_user 的 summary_threshold = ∞）
  → 用户的回答完整保留在上下文中
```


---

## 七、辅助 LLM 路由 [HA]

### 7.1 按任务类型选模型

Hermes 精华：不同任务使用不同模型，摘要/意图识别用便宜模型，推理用强模型。

```python
class LLMRouter:
    """
    辅助 LLM 路由 [HA] — 按任务类型选择最优模型。
    
    与 Tool/Skill 的关系:
    - Tool 执行本身不调用 LLM（Tool 是确定性操作）
    - Tool 结果的摘要（Layer 1）使用辅助模型
    - Skill 可以指定 model 字段覆盖默认模型
    """

    def __init__(self, config: LLMRouterConfig):
        self._config = config

    def get_model(self, task_type: str) -> LLMPluginInterface:
        """
        根据任务类型返回对应的 LLM 实例。
        
        任务类型:
        - "reasoning": 主推理（强模型）
        - "compression": 摘要/压缩（便宜模型）
        - "intent": 意图识别（便宜模型）
        - "safety": 安全检查（便宜模型）
        - "skill:{name}": 技能指定模型
        """
        model_config = self._config.task_models.get(
            task_type,
            self._config.task_models.get("default")
        )
        return self._create_llm(model_config)


@dataclass
class LLMRouterConfig:
    """LLM 路由配置"""
    task_models: dict[str, ModelConfig] = field(default_factory=lambda: {
        "default":      ModelConfig(provider="deepseek", model="deepseek-chat"),
        "reasoning":    ModelConfig(provider="deepseek", model="deepseek-chat"),
        "compression":  ModelConfig(provider="google", model="gemini-flash"),
        "intent":       ModelConfig(provider="google", model="gemini-flash"),
        "safety":       ModelConfig(provider="google", model="gemini-flash"),
    })
```

### 7.2 与 Tool/Skill 的配合

```
Tool 执行完毕 → Layer 1 摘要:
  model = llm_router.get_model("compression")  # gemini-flash
  summary = await model.ainvoke(SUMMARY_PROMPT)
  成本: ~$0.01/M tokens

Skill 执行（fork 模式）:
  if skill.model:
      # Skill 指定了模型 → 使用指定模型
      model = llm_router.get_model(f"skill:{skill.name}")
  else:
      # 使用默认推理模型
      model = llm_router.get_model("reasoning")

sessionSummary 更新:
  model = llm_router.get_model("compression")  # gemini-flash
  成本: ~$0.01/M tokens

成本对比（每次完整对话）:
  全部用强模型: ~$0.00124
  分离后: ~$0.001034
  规模化（100 租户 × 50 次/天）月节省: ~$31
```

---

## 八、Action 元数据驱动 [NA+NEW]

### 8.1 数据库配置的工具与技能

neo-apps 精华：Action 通过数据库配置驱动，租户可以在管理后台自定义 Agent 的能力。

```python
@dataclass
class ActionMetadata:
    """
    Action 元数据 [NA] — 数据库中的工具/技能配置。
    
    租户管理员可以在管理后台:
    1. 启用/禁用内置工具
    2. 配置自定义 API 连接（api_call 工具的数据源）
    3. 创建自定义技能（prompt 模板 + 工具组合）
    4. 配置审批规则（哪些操作需要确认）
    """
    id: str
    tenant_id: str
    action_type: str                      # "tool" | "skill" | "hitl_rule"
    name: str
    config: dict                          # 具体配置（JSON）
    enabled: bool = True
    created_by: str = ""
    updated_at: str = ""


class ActionMetadataLoader:
    """从数据库加载 Action 元数据，注入到 ToolRegistry / SkillRegistry"""

    async def load_tenant_actions(
        self,
        tenant_id: str,
        tool_registry: ToolRegistry,
        skill_registry: SkillRegistry,
    ) -> None:
        """
        AgentFactory Phase 3/5 中调用。
        从数据库加载租户配置的自定义 Action。
        """
        actions = await self._db.query(
            "SELECT * FROM ai_action_metadata WHERE tenant_id = ? AND enabled = 1",
            [tenant_id]
        )
        
        for action in actions:
            if action.action_type == "tool":
                # 自定义 API 连接 → 注册为 api_call 的子工具
                tool = self._build_custom_api_tool(action)
                tool_registry.register(tool)
            
            elif action.action_type == "skill":
                # 自定义技能 → 注册到 SkillRegistry
                skill = self._build_custom_skill(action)
                skill_registry.register(skill)
            
            elif action.action_type == "hitl_rule":
                # 自定义审批规则 → 注入到 HITLMiddleware
                pass  # 由 Middleware 层处理

    def _build_custom_api_tool(self, action: ActionMetadata) -> Tool:
        """
        将数据库中的 API 连接配置转为 Tool 实例。
        
        数据库配置示例:
        {
          "connection_name": "erp_system",
          "base_url": "https://erp.customer.com/api",
          "auth_type": "bearer",
          "endpoints": [
            {"path": "/orders", "method": "GET", "description": "查询订单"},
            {"path": "/orders", "method": "POST", "description": "创建订单"}
          ]
        }
        """
        config = action.config
        return CustomApiTool(
            tool_name=f"api_{config['connection_name']}",
            base_url=config["base_url"],
            auth_type=config.get("auth_type", "bearer"),
            endpoints=config.get("endpoints", []),
            # 压缩协作字段
            _summary_threshold=config.get("summary_threshold", 500),
            _code_extractable=config.get("code_extractable", False),
        )

    def _build_custom_skill(self, action: ActionMetadata) -> SkillDefinition:
        """
        将数据库中的技能配置转为 SkillDefinition。
        
        数据库配置示例:
        {
          "name": "weekly_pipeline_review",
          "description": "每周 Pipeline 审查流程",
          "prompt": "执行以下步骤进行 Pipeline 审查:\n1. 查询本周新增商机...",
          "allowed_tools": ["query_data", "analyze_data"],
          "context": "fork"
        }
        """
        config = action.config
        prompt_text = config.get("prompt", "")
        
        async def get_prompt(args: str = "", **kw) -> str:
            return prompt_text.replace("${1}", args)
        
        return SkillDefinition(
            name=config["name"],
            description=config.get("description", ""),
            allowed_tools=config.get("allowed_tools"),
            context=config.get("context", "fork"),
            source="db",
            get_prompt=get_prompt,
        )
```

### 8.2 元数据驱动的优势

```
传统方式（代码驱动）:
  新增一个工具 → 写代码 → 发版 → 重启 → 生效
  周期: 1-2 天

元数据驱动 [NA]:
  新增一个 API 连接 → 管理后台配置 → 立即生效
  新增一个自定义技能 → 管理后台配置 → 立即生效
  周期: 5 分钟

CRM SaaS 场景的价值:
  - 不同租户有不同的 ERP/OA/财务系统 → 各自配置 API 连接
  - 不同行业有不同的销售流程 → 各自配置业务技能
  - 不需要为每个租户定制代码
```


---

## 九、完整工具调用链路（14 步）

融合三框架的工具执行链路：

```
LLM 返回 tool_use block
  │
  ├── [1]  registry.find_by_name(name)  [CC+HA]
  │        → 查找工具（支持 aliases + 延迟池自动激活）
  │        → 找不到? → ToolResult(is_error=True, content="未知工具: {name}")
  │
  ├── [2]  tool.is_enabled(context)  [CC]
  │        → 运行时开关检查（Plugin 是否可用）
  │        → False? → ToolResult(is_error=True, content="工具已禁用: {name}")
  │
  ├── [3]  Middleware.before_tool_call()  [NA]
  │        ├── TenantMiddleware: 注入 tenant_id
  │        ├── AuditMiddleware: 记录调用开始
  │        └── HITLMiddleware: 检查是否需要审批
  │            → 需要审批? → CONFIRM 中断 → state.status=PAUSED
  │
  ├── [4]  tool.validate_input(input_data)  [CC]
  │        → valid=False? → ToolResult(is_error=True, content=message)
  │        → LLM 收到错误后自行修正参数重试
  │
  ├── [5]  tool.check_permissions(input_data, context)  [CC+NA]
  │        → DENY? → BLOCK 中断
  │        → ASK? → CONFIRM 中断
  │
  ├── [6]  tool.description(input_data)  [CC]
  │        → 生成动态描述（审计日志 + 前端展示）
  │
  ├── [7]  tool.backfill_observable_input(input_data)  [CC]
  │        → 回填自动注入的参数（前端展示完整参数）
  │
  ├── [8]  callbacks.on_tool_start(name, input_data)
  │        → 通知前端工具开始执行
  │
  ├── [9]  tool.call(input_data, context, on_progress)  [CC+HA+NA]
  │        → 执行（带超时 + 进度回调）
  │        → 超时? → ToolResult(is_error=True, content="工具执行超时")
  │        → 用户取消? → CANCEL 中断
  │
  ├── [10] 结果预算控制  [CC max_result_size_chars]
  │        → len(result.content) > tool.max_result_size_chars?
  │        → 超出? → 截断 + 持久化到虚拟文件
  │
  ├── [11] Layer 1 源头隔离  [NA+HA+NEW]
  │        → process_tool_result(tool, result, state)
  │        → 前端组件分流 + 两层摘要 + 虚拟文件
  │
  ├── [12] callbacks.on_tool_end(name, result)
  │        → 通知前端工具执行完毕
  │
  ├── [13] Middleware.after_tool_call()  [NA]
  │        ├── AuditMiddleware: 记录结果和耗时
  │        └── MemoryMiddleware: 记忆提取
  │
  └── [14] 更新执行追踪 + 构建 ToolResultBlock → 追加到 state.messages
```

---

## 十、完整工具清单

### 10.1 内置工具（15 个）

| # | 工具名 | 功能 | 依赖 Plugin | should_defer | tags |
|---|--------|------|------------|:---:|------|
| 1 | query_schema | 查询元数据定义 | — | ✗ | read, crm, metadata |
| 2 | query_data | 业务数据 CRUD | — | ✗ | read/write, crm, data |
| 3 | analyze_data | 数据聚合统计 | — | ✗ | read, crm, analytics |
| 4 | query_permission | 权限配置查询 | — | ✗ | read, crm, permission |
| 5 | web_search | 网络搜索 | search-plugin | ✓ | read, external, search |
| 6 | company_info | 企业工商查询 | company-data-plugin | ✓ | read, external, company |
| 7 | financial_report | 上市公司财报 | financial-data-plugin | ✓ | read, external, financial |
| 8 | api_call | 外部 API 调用 | — | ✓ | read/write, external, api |
| 9 | mcp_tool | MCP 协议扩展 | — | ✓ | dynamic |
| 10 | ask_user | 向用户提问 | — | ✗ | interaction |
| 11 | search_memories | 搜索长期记忆 | memory-plugin | ✗ | read, memory |
| 12 | save_memory | 写入长期记忆 | memory-plugin | ✗ | write, memory |
| 13 | delegate_task | 派生同步子 Agent | — | ✗ | orchestration |
| 14 | start_async_task | 派生异步子 Agent | — | ✗ | orchestration |
| 15 | send_notification | 推送通知 | notification-plugin | ✓ | write, external, notification |

### 10.2 工具与 Plugin 的关系

```
Tool（稳定接口，LLM 调用）          Plugin（可替换适配层，运维配置）
─────────────────────              ─────────────────────────────
web_search Tool                    search-plugin
  → call() 内部调用                  ├── TavilyAdapter（当前）
    context.search.query()           ├── BingAdapter（备选）
                                     └── GoogleAdapter（备选）

company_info Tool                  company-data-plugin
  → call() 内部调用                  ├── TianyanchaAdapter（当前）
    context.company.query()          ├── QichachaAdapter（备选）
                                     └── QixinbaoAdapter（备选）

financial_report Tool              financial-data-plugin
  → call() 内部调用                  ├── CninfoAdapter（当前）
    context.financial.query()        ├── WindAdapter（备选）
                                     └── EastmoneyAdapter（备选）

search_memories / save_memory      memory-plugin
  → call() 内部调用                  ├── FilesystemAdapter
    context.memory.recall()          ├── PgVectorAdapter
    context.memory.commit()          └── ElasticsearchAdapter

send_notification Tool             notification-plugin
  → call() 内部调用                  ├── 站内信Adapter
    context.notification.send()      ├── 钉钉Adapter
                                     ├── 飞书Adapter
                                     └── 邮件Adapter

关键原则:
  Plugin 不直接注册 Tool → Tool 始终由 ToolRegistry 管理
  Plugin 只提供接口 → Tool 通过 PluginContext 调用 Plugin 的能力
  换供应商时只改 Plugin 配置 → Tool 接口不变 → LLM 完全无感知
```


---

## 十一、端到端场景演示

### 11.1 场景：销售经理进行竞品分析（Tool + Skill + 压缩 全链路）

```
用户: "帮我分析一下华为的竞争态势，我们下周要跟 PT Sentosa Jaya 谈判"

═══ PlanningNode ═══
  意图识别 → "competitive_analysis"
  SkillRegistry.match_by_intent("competitive_analysis") → competitive_analysis Skill
  规划:
    Step 1: 查询客户信息（了解背景）
    Step 2: 执行 competitive_analysis Skill（fork 模式）
    Step 3: 生成谈判建议

═══ ExecutionNode Step 1 ═══
  LLM → tool_use: query_data(action="get", entity="account", record_id="acc_xxx")
  
  工具调用链路:
    [1] registry.find_by_name("query_data") → BusinessDataTool ✅
    [2] is_enabled() → True（核心工具，始终启用）
    [3] TenantMiddleware: 注入 _tenant_id
    [4] validate_input → valid
    [5] check_permissions → ALLOW
    [6] description(input) → "获取 account 记录 acc_xxx"
    [7] backfill_observable_input → {_tenant_id: "tenant_001", ...}
    [8] on_tool_start("query_data", input)
    [9] call() → ToolResult(content="PT Sentosa Jaya, 制造业, 200人...", 800 chars)
    [10] max_result_size_chars=50,000 → 800 < 50,000 → 不截断
    [11] Layer 1 源头隔离:
         summary_threshold=300, 800 > 300 → 触发摘要
         code_extractable=True → try_code_extract()
         → extract_from_json() → "PT Sentosa Jaya, 制造业, 200人, 评分87"
         → 成功！零 LLM 成本
         虚拟文件: FileInfo(content=800chars原文, summary=50chars摘要)
    [12] on_tool_end
    [13] AuditMiddleware: 记录
    [14] ToolResultBlock → state.messages

═══ ExecutionNode Step 2 ═══
  LLM → tool_use: delegate_task(task="竞品分析", agent_type="researcher")
  
  → 启动 competitive_analysis Skill（fork 模式）
  → 子 Agent 工具集: web_search, company_info, financial_report, query_data
  
  子 Agent 内部执行:
    Sub-Step 1: company_info(keyword="华为技术有限公司")
      → 延迟池中找到 company_info → 自动激活
      → call() → 返回工商信息 1,800 chars
      → Layer 1: summary_threshold=800, 1800 > 800
        code_extractable=True → extract_from_component("customer_profile", data)
        → "华为技术有限公司, 通信设备, 207,000人, 注册资本4104113万"
        → 零 LLM 成本
    
    Sub-Step 2: financial_report(stock_code="002502")
      → 延迟池中找到 financial_report → 自动激活
      → call() → 返回财报数据 3,500 chars
      → Layer 1: summary_threshold=1500, 3500 > 1500
        code_extractable=True → extract_from_json() 提取关键财务指标
        → "华为2025年营收8809亿/净利680亿/研发占比21.8%"
        → 零 LLM 成本
    
    Sub-Step 3: web_search(query="华为 vs 竞品 CRM 市场份额 2025")
      → 延迟池中找到 web_search → 自动激活
      → call() → 返回搜索结果 2,100 chars
      → Layer 1: summary_threshold=500, 2100 > 500
        code_extractable=False → try_code_extract() 失败
        → 降级到 LLM 摘要（gemini-flash，$0.01/M tokens）
        → "华为企业业务2025年增长15%，CRM市场份额约8%..."
    
    Sub-Step 4: 生成竞品分析报告
  
  子 Agent 返回 → delegate_task 的 ToolResult
  → Layer 1: summary_threshold=500
  → 子 Agent 结果已经是摘要 → 可能不触发二次摘要

═══ Layer 2 检查 ═══
  当前轮次 ToolMessage 数量 = 2（query_data + delegate_task）
  2 < 5 → 不触发 Layer 2 裁剪

═══ ExecutionNode Step 3 ═══
  LLM 基于摘要生成谈判建议

═══ Layer 3 回复摘要 ═══
  最终回复 2,500 chars > 500 → 触发 answerSummary（异步，gemini-flash）
  sessionSummary 迭代更新:
    ## Active Task: 华为竞品分析 + PT Sentosa Jaya 谈判准备
    ## 已完成操作:
    1. 查询 PT Sentosa Jaya 客户信息 — 制造业/200人/评分87
    2. 竞品分析(华为) — 营收8809亿/净利680亿/CRM市场份额8%
    ## 关键数据:
    华为: 营收8809亿, 净利680亿, 研发占比21.8%, CRM市场份额8%
    PT Sentosa Jaya: 制造业, 200人, 评分87

上下文占用统计:
  System Prompt: ~2,000 tokens
  sessionSummary: ~200 tokens
  conversation_history: ~0 tokens（首轮）
  当前 messages: ~400 tokens（2个摘要后的 ToolMessage + 最终回复）
  总计: ~2,600 tokens

对比无压缩（完整原文）: ~15,000 tokens
节省: 83%
```

### 11.2 场景：HITL 中断 + Skill 协作

```
用户: "帮我把所有超过 60 天未跟进的线索标记为过期并删除"

═══ PlanningNode ═══
  意图识别 → "batch_data"（批量操作）
  SkillRegistry.match_by_intent("batch_data") → batch_data Skill
  
═══ Skill 执行（fork 模式）═══
  
  Sub-Step 1: query_data(action="count", entity="lead", filters={last_activity: "<60d_ago"})
    → ToolResult: "lead 符合条件的记录数: 1,247"
    → Layer 1: 短文本，不摘要
  
  Sub-Step 2: LLM 判断 1,247 条 → 需要用户确认
    → ask_user(question="将标记并删除 1,247 条超过60天未跟进的线索，是否确认？")
    → CLARIFY 中断 → 等待用户回答
    → 用户: "确认，但先导出一份备份"
  
  Sub-Step 3: query_data(action="query", entity="lead", filters={...}, page_size=100)
    → 分页查询，导出为虚拟文件
    → Layer 1: 大结果 → 前端组件渲染（表格）+ 摘要进入上下文
  
  Sub-Step 4: query_data(action="update", entity="lead", data={status:"expired"}, filters={...})
    → HITLMiddleware 检查: 批量更新 1,247 条
    → CONFIRM 中断: "即将更新 1,247 条 lead 记录的状态为 expired"
    → 用户确认 → 执行
  
  Sub-Step 5: query_data(action="delete", entity="lead", filters={status:"expired"})
    → is_destructive(action="delete") → True
    → CONFIRM 中断: "即将删除 1,247 条 expired 状态的 lead 记录"
    → 用户确认 → 执行
  
  Sub-Step 6: 生成操作报告

═══ Layer 3 ═══
  sessionSummary:
    ## 已完成操作:
    1. 统计超60天未跟进线索 — 1,247条
    2. 导出备份 — 虚拟文件 /action_result/lead_backup
    3. 批量标记为 expired — 1,247条
    4. 批量删除 — 1,247条
    ## 关键数据:
    删除线索数: 1,247, 备份文件: /action_result/lead_backup
```

---

## 十二、设计点来源汇总

| 设计点 | [CC] | [HA] | [NA] | [NEW] | 所在章节 |
|--------|:----:|:----:|:----:|:-----:|---------|
| Tool 统一接口（四组字段） | ✅ | ✅ | ✅ | | §二 |
| 动态描述 description(input) | ✅ | | | | §二 |
| 延迟加载 should_defer + search_hint | ✅ | | | | §三 |
| 搜索/读取折叠 | ✅ | | | | §三 |
| 每工具独立结果预算 max_result_size_chars | ✅ | | | | §二 |
| 输入回填 backfillObservableInput | ✅ | | | | §二 |
| 中断行为 cancel/block | ✅ | | | | §六 |
| 引擎暴露工具 get_tool_schemas | | ✅ | | | §三 |
| 按工具类型信息摘要 _summarize_tool_result | | ✅ | | ✅ | §四 |
| 辅助 LLM 路由（按 task 选 model） | | ✅ | | | §七 |
| 独立 Skill 概念（可复用工作流） | | ✅ | | | §五 |
| Skill 多源加载（文件 + 内置 + DB） | ✅ | ✅ | | ✅ | §五 |
| 前端组件分流 | | | ✅ | | §四 |
| Action 元数据驱动（数据库配置） | | | ✅ | | §八 |
| 三种中断类型（澄清/确认/执行中断） | | | ✅ | | §六 |
| 虚拟文件 FileInfo | | | ✅ | | §四 |
| 工具标签 tags | | | | ✅ | §二 |
| 压缩协作字段（summary_threshold 等） | | | | ✅ | §二 |
| 工具折叠策略 | ✅ | | | ✅ | §三 |
| CRM 内置 Skill 清单（12 个） | ✅ | ✅ | ✅ | ✅ | §五 |
| Skill 意图匹配 match_by_intent | | | | ✅ | §五 |
| 数据库加载技能 load_from_db | | | ✅ | ✅ | §八 |
| 完整工具调用链路（14 步） | ✅ | ✅ | ✅ | ✅ | §九 |

**来源统计**:
- **[CC] 吸收 8 项**: 动态描述、延迟加载、折叠、中断行为、结果预算、输入回填、Skill 文件加载、工具调用链路
- **[HA] 吸收 5 项**: get_tool_schemas、信息摘要、LLM 路由、Skill 概念、Skill 多源加载
- **[NA] 保留 5 项**: 前端组件分流、Action 元数据驱动、三种中断、虚拟文件、数据库技能
- **[NEW] 新增 6 项**: 工具标签、压缩协作字段、折叠策略 CRM 适配、CRM Skill 清单、意图匹配、DB 技能加载

---

## 十三、与现有代码的对应关系

| 本方案 | 现有代码文件 | 变更说明 |
|--------|------------|---------|
| Tool 统一接口 | `src/tools.py` Tool 类 | 新增压缩协作字段（summary_threshold 等） |
| ToolRegistry | `src/tools.py` ToolRegistry 类 | 新增延迟池 + search_tools + get_deferred_hints |
| ToolResult | `src/types.py` ToolResult | 新增 render_hint + virtual_file |
| Skill 体系 | `src/skills.py` | 新增 CRM 内置技能 + match_by_intent + load_from_db |
| Plugin 体系 | `src/plugins.py` | 不变（Plugin 不再直接注册 Tool） |
| 中断体系 | `src/types.py` | 新增 InterruptType + InterruptRequest |
| LLM 路由 | 新文件 `src/llm_router.py` | 新增 |
| Action 元数据 | 新文件 `src/action_metadata.py` | 新增 |
| 工具调用链路 | `src/tools.py` execute_tool_use | 在 Step 11 插入 Layer 1 处理 |
