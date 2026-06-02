# Eval 测试数据初始化机制深度分析

> 核心问题：read_file / search_files 等工具评测需要**文件先存在于沙箱中**，但当前 setup_steps 机制存在多个脆弱点，导致测试数据初始化频繁失败。

---

## 一、当前初始化链路全景

```
┌─────────────────────────────────────────────────────────────────────┐
│  测试数据初始化链路                                                   │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  ToolEvalCase 定义                                                   │
│  ┌───────────────────┐                                              │
│  │ setup_steps: [    │                                              │
│  │   {tool, input}   │ ← 用例声明前置操作                           │
│  │ ]                 │                                              │
│  └────────┬──────────┘                                              │
│           │                                                         │
│           ▼                                                         │
│  ToolEvalRunner.run_case()                                          │
│  ┌───────────────────────────────────────────────────────┐          │
│  │ 1. _reset_backend()    ← 仅重置 CRM，不重置沙箱       │          │
│  │ 2. for step in setup_steps:                            │          │
│  │      tool = reg.find_by_name(step["tool"])             │          │
│  │      await tool.call(step["input"], context)           │          │
│  │ 3. await target_tool.call(input_data, context)         │          │
│  │ 4. assertion_engine.check(result)                      │          │
│  └───────────────────────────────────────────────────────┘          │
│           │                                                         │
│           ▼                                                         │
│  实际工具执行（WriteFileTool / TerminalTool）                        │
│  ┌───────────────────────────────────────────────────────┐          │
│  │ WriteFileTool.call():                                  │          │
│  │   1. mkdir -p <parent_dir>    ← 确保目录存在           │          │
│  │   2. sandbox.files.write(path, content)                │          │
│  │                                                        │          │
│  │ TerminalTool.call():                                   │          │
│  │   1. sandbox.commands.run(command)                      │          │
│  │   ← 不保证目录存在、不保证依赖库已安装                  │          │
│  └───────────────────────────────────────────────────────┘          │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 二、已发现的故障点分析

### 故障点 1：setup_steps 字段名不匹配（已修复）

| 位置 | 用例定义 | Runner 解析 |
|------|----------|-------------|
| 工具名 | `"tool": "write_file"` | `step.get("tool_name", case.tool_name)` |
| 输入 | `"input": {...}` | `step.get("input_data", {})` |

**影响**：所有依赖 setup_steps 的用例（rf_11~rf_20, rf_25, rf_40~rf_47, rf_50~rf_52）全部失败。

**修复**：Runner 已兼容两种 key（`"tool"/"tool_name"`, `"input"/"input_data"`）。

---

### 故障点 2：terminal 命令依赖未安装的 Python 库

```python
# rf_18: 依赖 openpyxl
{"tool": "terminal", "input": {
    "command": "python3 -c \"import openpyxl; ...\""
}}
```

**问题**：沙箱环境中 `openpyxl` 可能未预装，导致 `ModuleNotFoundError`。

**受影响用例**：rf_18（xlsx）、rf_23（/tmp xlsx）

**根因**：setup_step 假设沙箱环境有特定依赖，但沙箱模板（`code-sandbox`）的预装包不确定。

---

### 故障点 3：terminal 命令无静默失败处理

当前 runner 中 setup_step 失败的行为：
```python
try:
    await setup_tool.call(setup_input, context)
except Exception as e:
    result.error = f"setup_step 执行失败: {e}"
    result.passed = False
    return result
```

但 `TerminalTool.call()` 不会抛异常——它返回 `ToolResult(is_error=True)`：
```python
# TerminalTool 内部
result = await self._backend.execute(command)
if result.exit_code != 0:
    return ToolResult(content=f"退出码: {result.exit_code}\n{result.stderr}", is_error=True)
```

**关键问题**：Runner 没有检查 setup_step 的返回值 `is_error`！即使 terminal 命令失败（openpyxl 未安装、目录不存在等），runner 仍认为 setup 成功，继续执行后续测试。

---

### 故障点 4：沙箱状态跨用例泄漏

```python
def _reset_backend(self):
    """重置 CRM Backend 数据为初始 seed data"""
    if self._backend is not None:
        self._backend._data = build_seed_data()
        self._backend._audit_log = []
```

**只重置 CRM，不重置沙箱文件系统**。意味着：
- 前一个用例 write_file 创建的文件会残留
- 如果用例执行顺序变化，测试可能偶发通过/失败
- 副作用用例（rf_50~rf_52）如果排在其他用例后面，可能读到脏数据

---

### 故障点 5：setup_tool 找不到时静默跳过

```python
setup_tool = reg.find_by_name(setup_tool_name)
if setup_tool:  # ← 如果找不到，静默跳过！
    ...
```

如果沙箱工具注册失败（`try/except` 包裹的注册逻辑），`write_file`/`terminal` 工具不存在，setup_step 被完全跳过，没有任何报错。

---

## 三、各用例类别的初始化需求矩阵

| 用例类别 | 初始化需求 | 当前方式 | 可靠性 |
|----------|-----------|---------|--------|
| rf_01~rf_10（基础读取） | 特定格式文件存在于 /sandbox | `write_file` setup_step | ⚠️ 依赖 key 修复 |
| rf_11~rf_13（offset/limit） | 多行文本文件 | `write_file` setup_step | ⚠️ 依赖 key 修复 |
| rf_14~rf_15（特殊字符） | 含 unicode/转义的文件 | `write_file` setup_step | ⚠️ 依赖 key 修复 |
| rf_16（空文件） | 空文件存在 | `write_file` + `content=""` | ✅ 简单 |
| rf_17（大文件） | 3000 行文件 | `terminal` + python 生成 | ⚠️ terminal 无报错检测 |
| rf_18（xlsx 二进制） | 有效 xlsx 文件 | `terminal` + openpyxl | ❌ 依赖未安装 |
| rf_19~rf_20（深层目录/隐藏文件） | 多层目录结构 | `write_file` setup_step | ✅ WriteFileTool 自动 mkdir |
| rf_21~rf_27（/tmp 场景） | /tmp 下各格式文件 | `write_file` setup_step | ⚠️ 依赖 key 修复 |
| rf_40~rf_47（边界） | 各种边界数据 | `write_file`/`terminal` | ⚠️ 混合风险 |
| rf_50~rf_52（副作用） | 先写后读/先执行后读 | 多步 setup_step | ⚠️ 最复杂，链式依赖 |

---

## 四、根本问题总结

### 核心矛盾

**eval 测试框架同时承担两个角色**：
1. 评测工具本身的功能（read_file 能否正确读取）
2. 通过工具来准备测试前置数据（write_file 来创建测试文件）

当**用于准备数据的工具本身可能不可用**时，被测工具的测试就会失败——但失败原因不是被测工具有问题，而是"准备环境"失败了。

### 设计缺陷

| 缺陷 | 描述 | 影响 |
|------|------|------|
| 无独立初始化通道 | setup_steps 复用运行时工具链，与被测工具共享相同的故障域 | 准备失败 ≠ 测试失败，但无法区分 |
| 无 setup 结果校验 | Runner 不检查 setup_step 返回的 is_error | 数据未就绪就执行测试 |
| 无环境先决条件声明 | 用例不声明依赖（如 openpyxl），系统无法提前检查 | 运行时才发现环境缺失 |
| 无沙箱状态隔离 | 用例间共享沙箱文件系统 | 执行顺序敏感，偶发失败 |
| 无初始化失败重试 | 网络抖动导致沙箱 API 一次失败即放弃 | 瞬时故障放大 |

---

## 五、推荐改进方案

### 方案 A：增强现有 setup_steps 机制（短期）

```python
# 1. setup_step 结果校验
for step in case.setup_steps:
    setup_tool_name = step.get("tool_name") or step.get("tool") or case.tool_name
    setup_tool = reg.find_by_name(setup_tool_name)
    
    if setup_tool is None:
        result.error = f"setup_step 工具未注册: {setup_tool_name}"
        result.passed = False
        return result
    
    setup_input = step.get("input_data") or step.get("input") or {}
    setup_result = await setup_tool.call(setup_input, context)
    
    # ✅ 新增：检查返回值
    if setup_result.is_error:
        result.error = f"setup_step 执行返回错误: {setup_tool_name} → {setup_result.content}"
        result.passed = False
        return result

# 2. 重试机制
MAX_SETUP_RETRIES = 2
for attempt in range(MAX_SETUP_RETRIES + 1):
    setup_result = await setup_tool.call(setup_input, context)
    if not setup_result.is_error:
        break
    if attempt == MAX_SETUP_RETRIES:
        result.error = f"setup_step 重试{MAX_SETUP_RETRIES}次仍失败"
        ...
```

### 方案 B：引入独立的 TestFixture 层（中期）

```python
@dataclass
class TestFixture:
    """测试数据固件 — 独立于工具链的数据准备机制"""
    
    # 声明式文件列表（直接通过 sandbox API 写入，不经过 Tool 层）
    files: dict[str, str | bytes] = field(default_factory=dict)
    
    # 需要执行的 shell 命令（安装依赖等）
    shell_commands: list[str] = field(default_factory=list)
    
    # 环境先决条件
    prerequisites: list[str] = field(default_factory=list)  # e.g. ["openpyxl", "pandas"]


@dataclass
class ToolEvalCase:
    ...
    # 新增：声明式数据固件（替代 setup_steps 中的 write_file 场景）
    fixture: TestFixture | None = None
    # 保留 setup_steps 用于真正需要"通过工具操作"的副作用场景
    setup_steps: list[dict] = field(default_factory=list)
```

**执行流程**：
```
1. 检查 prerequisites → 不满足则 skip（不标记为 FAIL）
2. 通过 sandbox API 直接写入 fixture.files（绕过 Tool 层）
3. 执行 fixture.shell_commands
4. 执行 setup_steps（仅副作用场景使用）
5. 执行被测工具
6. 断言校验
```

### 方案 C：沙箱快照 + 预热机制（长期）

```
┌─────────────────────────────────────────────────────────────────────┐
│  测试沙箱生命周期                                                    │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  Phase 1: 沙箱预热（Suite 级别，执行一次）                           │
│  ─────────────────────────────────                                  │
│  • 安装所需依赖: pip install openpyxl pandas ...                    │
│  • 创建公共目录结构: /sandbox/app, /sandbox/data, /sandbox/test     │
│  • 写入"共享固件"文件（不会被用例修改的只读数据）                    │
│                                                                     │
│  Phase 2: 用例级初始化（每个 Case 执行前）                           │
│  ─────────────────────────────────                                  │
│  • 清理上一用例的写入（rm -rf /sandbox/tmp_case/）                  │
│  • 写入本用例独有的文件（通过 fixture.files）                        │
│  • 执行 setup_steps（仅副作用场景）                                  │
│                                                                     │
│  Phase 3: 执行 + 断言                                               │
│  ─────────────────────────────────                                  │
│  • 调用被测工具                                                     │
│  • 验证结果                                                         │
│                                                                     │
│  Phase 4: 清理（Suite 结束时）                                       │
│  ─────────────────────────────────                                  │
│  • 销毁/暂停沙箱                                                    │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 六、立即可执行的修复清单

| # | 修复项 | 文件 | 优先级 |
|---|--------|------|--------|
| 1 | ✅ setup_steps key 兼容 | tool_eval_runner.py | P0 已完成 |
| 2 | setup_step 返回值检查 | tool_eval_runner.py | P0 |
| 3 | setup_tool 为 None 时报错而非跳过 | tool_eval_runner.py | P0 |
| 4 | rf_18/rf_23 改用 write_file 写入预生成的 xlsx bytes | tool_eval_presets.py | P1 |
| 5 | rf_17 大文件改用 write_file（生成 content 在 Python 内完成） | tool_eval_presets.py | P1 |
| 6 | 增加 Suite 级别的沙箱预热步骤 | tool_eval_runner.py | P2 |
| 7 | 用例间文件系统隔离（每用例独立目录或清理） | tool_eval_runner.py | P2 |

---

## 七、rf_18 xlsx 用例的推荐修复

用 `write_file` + base64 解码替代 `terminal` + openpyxl：

```python
ToolEvalCase(
    id="rf_18",
    tool_name="read_file",
    description="/sandbox - 读取 Excel(.xlsx) 文件（二进制，验证不崩溃）",
    category="boundary",
    setup_steps=[
        # 方案 1：用 terminal 内联生成（确保依赖存在）
        {"tool": "terminal", "input": {
            "command": (
                "pip install -q openpyxl 2>/dev/null; "
                "python3 -c \""
                "import openpyxl; "
                "wb = openpyxl.Workbook(); ws = wb.active; "
                "ws['A1'] = '姓名'; ws['B1'] = '分数'; "
                "ws['A2'] = '张三'; ws['B2'] = 95; "
                "wb.save('/sandbox/data/test.xlsx')"
                "\""
            ),
        }},
        # 方案 2（更可靠）：用 terminal 写入预编码的最小 xlsx
        # {"tool": "terminal", "input": {
        #     "command": "echo 'UEsDBBQ...' | base64 -d > /sandbox/data/test.xlsx"
        # }},
    ],
    ...
)
```

**推荐方案 2**：预先生成一个最小 xlsx 文件的 base64 编码，通过 `echo | base64 -d` 写入。完全不依赖 openpyxl，100% 可靠。
