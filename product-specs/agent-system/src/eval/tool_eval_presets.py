"""Tool 评测预置用例

为每个内置工具提供标准的评测用例集，覆盖正常/异常/边界/副作用四类场景。
基于 CrmSimulatedBackend 的 seed data 设计。
"""
from __future__ import annotations

from src.eval.tool_eval_runner import (
    ToolEvalSuite, ToolEvalCase, Assertion, AssertionType,
)


def build_query_schema_cases() -> list[ToolEvalCase]:
    """query_schema 工具评测用例"""
    return [
        ToolEvalCase(
            id="qs_01",
            tool_name="query_schema",
            description="list_entities - 列出所有业务对象",
            category="normal",
            input_data={"query_type": "list_entities"},
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="不应报错"),
                Assertion(type=AssertionType.CONTAINS, expected="account", description="包含 account"),
                Assertion(type=AssertionType.CONTAINS, expected="opportunity", description="包含 opportunity"),
                Assertion(type=AssertionType.CONTAINS, expected="contact", description="包含 contact"),
            ],
        ),
        ToolEvalCase(
            id="qs_02",
            tool_name="query_schema",
            description="entity - 查看 opportunity 定义",
            category="normal",
            input_data={"query_type": "entity", "entity_api_key": "opportunity"},
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="不应报错"),
                Assertion(type=AssertionType.CONTAINS, expected="amount", description="包含 amount 字段"),
                Assertion(type=AssertionType.CONTAINS, expected="stage", description="包含 stage 字段"),
            ],
        ),
        ToolEvalCase(
            id="qs_03",
            tool_name="query_schema",
            description="entity_items - 查看字段列表",
            category="normal",
            input_data={"query_type": "entity_items", "entity_api_key": "account"},
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="不应报错"),
                Assertion(type=AssertionType.CONTAINS, expected="name", description="包含 name 字段"),
            ],
        ),
        ToolEvalCase(
            id="qs_04",
            tool_name="query_schema",
            description="不存在的 entity - 应返回错误",
            category="error",
            input_data={"query_type": "entity", "entity_api_key": "nonexistent_xyz"},
            assertions=[
                Assertion(type=AssertionType.IS_ERROR, description="应返回错误"),
            ],
        ),
        ToolEvalCase(
            id="qs_05",
            tool_name="query_schema",
            description="entity_pick_options - 查询选项值",
            category="normal",
            input_data={"query_type": "entity_pick_options", "entity_api_key": "opportunity", "item_api_key": "stage"},
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="不应报错"),
            ],
        ),
    ]


def build_query_data_cases() -> list[ToolEvalCase]:
    """query_data 工具评测用例"""
    return [
        ToolEvalCase(
            id="qd_01",
            tool_name="query_data",
            description="query - 查询所有客户",
            category="normal",
            input_data={"action": "query", "entity_api_key": "account"},
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="不应报错"),
                Assertion(type=AssertionType.CONTAINS, expected="records", description="返回 records 字段"),
            ],
        ),
        ToolEvalCase(
            id="qd_02",
            tool_name="query_data",
            description="query - 按 owner_name 过滤",
            category="normal",
            input_data={"action": "query", "entity_api_key": "opportunity", "filters": {"owner_name": "张三"}},
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="不应报错"),
                Assertion(type=AssertionType.CONTAINS, expected="张三", description="结果包含张三"),
            ],
        ),
        ToolEvalCase(
            id="qd_03",
            tool_name="query_data",
            description="get - 按 ID 查单条记录",
            category="normal",
            input_data={"action": "get", "entity_api_key": "account", "record_id": "acc_001"},
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="不应报错"),
                Assertion(type=AssertionType.CONTAINS, expected="acc_001", description="返回对应记录"),
            ],
        ),
        ToolEvalCase(
            id="qd_04",
            tool_name="query_data",
            description="get - 不存在的 ID",
            category="error",
            input_data={"action": "get", "entity_api_key": "account", "record_id": "acc_999999"},
            assertions=[
                Assertion(type=AssertionType.IS_ERROR, description="应返回错误"),
                Assertion(type=AssertionType.CONTAINS, expected="不存在", description="提示不存在"),
            ],
        ),
        ToolEvalCase(
            id="qd_05",
            tool_name="query_data",
            description="count - 统计记录数",
            category="normal",
            input_data={"action": "count", "entity_api_key": "account"},
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="不应报错"),
                Assertion(type=AssertionType.CONTAINS, expected="记录数", description="返回统计结果"),
            ],
        ),
        ToolEvalCase(
            id="qd_06",
            tool_name="query_data",
            description="query - 分页参数",
            category="boundary",
            input_data={"action": "query", "entity_api_key": "opportunity", "page": 1, "page_size": 2},
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="不应报错"),
            ],
        ),
        ToolEvalCase(
            id="qd_07",
            tool_name="query_data",
            description="query - 不存在的 entity",
            category="error",
            input_data={"action": "query", "entity_api_key": "nonexistent_entity"},
            assertions=[
                Assertion(type=AssertionType.IS_ERROR, description="应返回错误"),
            ],
        ),
    ]


def build_modify_data_cases() -> list[ToolEvalCase]:
    """modify_data 工具评测用例"""
    return [
        ToolEvalCase(
            id="md_01",
            tool_name="modify_data",
            description="create - 创建新客户",
            category="normal",
            input_data={
                "action": "create",
                "entity_api_key": "account",
                "data": {"name": "评测新客户", "industry": "科技", "owner_name": "评测员"},
            },
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="不应报错"),
                Assertion(type=AssertionType.CONTAINS, expected="评测新客户", description="返回创建的数据"),
            ],
        ),
        ToolEvalCase(
            id="md_02",
            tool_name="modify_data",
            description="update - 更新客户名称",
            category="normal",
            input_data={
                "action": "update",
                "entity_api_key": "account",
                "record_id": "acc_001",
                "data": {"name": "更新后的名称"},
            },
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="不应报错"),
                Assertion(type=AssertionType.CONTAINS, expected="更新后的名称", description="返回更新后的数据"),
            ],
        ),
        ToolEvalCase(
            id="md_03",
            tool_name="modify_data",
            description="update - 不存在的记录",
            category="error",
            input_data={
                "action": "update",
                "entity_api_key": "account",
                "record_id": "acc_not_exist",
                "data": {"name": "xxx"},
            },
            assertions=[
                Assertion(type=AssertionType.IS_ERROR, description="应返回错误"),
            ],
        ),
        ToolEvalCase(
            id="md_04",
            tool_name="modify_data",
            description="delete - 删除记录",
            category="normal",
            input_data={
                "action": "delete",
                "entity_api_key": "account",
                "record_id": "acc_001",
            },
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="不应报错"),
            ],
        ),
        ToolEvalCase(
            id="md_05",
            tool_name="modify_data",
            description="create 副作用验证 - 创建后可查到",
            category="side_effect",
            input_data={
                "action": "create",
                "entity_api_key": "account",
                "data": {"name": "副作用测试客户", "industry": "金融"},
            },
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="创建不应报错"),
                Assertion(
                    type=AssertionType.SIDE_EFFECT,
                    description="创建后通过 query 能查到",
                    expected={
                        "verify_tool": "query_data",
                        "verify_input": {"action": "query", "entity_api_key": "account", "filters": {"name": "副作用测试客户"}},
                        "verify_path": "records.0.name",
                        "verify_value": "副作用测试客户",
                    },
                ),
            ],
        ),
    ]


def build_analyze_data_cases() -> list[ToolEvalCase]:
    """analyze_data 工具评测用例"""
    return [
        ToolEvalCase(
            id="ad_01",
            tool_name="analyze_data",
            description="sum - 商机金额汇总",
            category="normal",
            input_data={
                "entity_api_key": "opportunity",
                "metrics": [{"field": "amount", "function": "sum"}],
            },
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="不应报错"),
            ],
        ),
        ToolEvalCase(
            id="ad_02",
            tool_name="analyze_data",
            description="count + group_by - 按阶段统计商机数",
            category="normal",
            input_data={
                "entity_api_key": "opportunity",
                "metrics": [{"field": "id", "function": "count"}],
                "group_by": "stage",
            },
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="不应报错"),
            ],
        ),
        ToolEvalCase(
            id="ad_03",
            tool_name="analyze_data",
            description="不存在的 entity",
            category="error",
            input_data={
                "entity_api_key": "nonexistent",
                "metrics": [{"field": "id", "function": "count"}],
            },
            assertions=[
                Assertion(type=AssertionType.IS_ERROR, description="应返回错误"),
            ],
        ),
    ]


def build_metarepo_cases() -> list[ToolEvalCase]:
    """browse_metamodel / query_metadata 工具评测用例"""
    return [
        ToolEvalCase(
            id="mr_01",
            tool_name="browse_metamodel",
            description="列出所有元模型",
            category="normal",
            input_data={"action": "list"},
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="不应报错"),
            ],
        ),
        ToolEvalCase(
            id="mr_02",
            tool_name="query_metadata",
            description="查询元数据实例",
            category="normal",
            input_data={"metamodel_api_key": "entity", "action": "list"},
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="不应报错"),
            ],
        ),
    ]


def build_terminal_cases() -> list[ToolEvalCase]:
    """terminal 工具评测用例"""
    return [
        # ── 正常场景 ──
        ToolEvalCase(
            id="term_01",
            tool_name="terminal",
            description="执行简单命令 - echo",
            category="normal",
            input_data={"command": "echo hello"},
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="不应报错"),
                Assertion(type=AssertionType.CONTAINS, expected="hello", description="输出包含 hello"),
            ],
        ),
        ToolEvalCase(
            id="term_02",
            tool_name="terminal",
            description="执行系统信息命令 - uname",
            category="normal",
            input_data={"command": "uname -s"},
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="不应报错"),
            ],
        ),
        ToolEvalCase(
            id="term_03",
            tool_name="terminal",
            description="执行多命令组合 - pwd && whoami",
            category="normal",
            input_data={"command": "pwd && whoami"},
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="不应报错"),
            ],
        ),
        ToolEvalCase(
            id="term_04",
            tool_name="terminal",
            description="执行带超时参数的命令",
            category="normal",
            input_data={"command": "sleep 1 && echo done", "timeout": 10},
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="不应报错"),
                Assertion(type=AssertionType.CONTAINS, expected="done", description="输出包含 done"),
            ],
        ),
        ToolEvalCase(
            id="term_05",
            tool_name="terminal",
            description="执行 ls 列出目录",
            category="normal",
            input_data={"command": "ls /tmp"},
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="不应报错"),
            ],
        ),
        # ── 异常场景 ──
        ToolEvalCase(
            id="term_06",
            tool_name="terminal",
            description="空命令 - 应返回错误",
            category="error",
            input_data={"command": ""},
            assertions=[
                Assertion(type=AssertionType.IS_ERROR, description="空命令应报错"),
            ],
        ),
        ToolEvalCase(
            id="term_07",
            tool_name="terminal",
            description="不存在的命令",
            category="error",
            input_data={"command": "nonexistent_command_xyz_123"},
            assertions=[
                Assertion(type=AssertionType.IS_ERROR, description="不存在的命令应报错"),
            ],
        ),
        ToolEvalCase(
            id="term_08",
            tool_name="terminal",
            description="命令执行失败 - exit 1",
            category="error",
            input_data={"command": "exit 1"},
            assertions=[
                Assertion(type=AssertionType.IS_ERROR, description="非零退出码应报错"),
            ],
        ),
        # ── 边界场景 ──
        ToolEvalCase(
            id="term_09",
            tool_name="terminal",
            description="超短超时 - 可能超时",
            category="boundary",
            input_data={"command": "sleep 5", "timeout": 1},
            assertions=[
                Assertion(type=AssertionType.IS_ERROR, description="应超时报错"),
            ],
        ),
        ToolEvalCase(
            id="term_10",
            tool_name="terminal",
            description="输出为空的命令",
            category="boundary",
            input_data={"command": "true"},
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="不应报错"),
            ],
        ),
    ]


def build_execute_code_cases() -> list[ToolEvalCase]:
    """execute_code 工具评测用例"""
    return [
        # ── 正常场景: Python ──
        ToolEvalCase(
            id="ec_01",
            tool_name="execute_code",
            description="Python - 简单 print",
            category="normal",
            input_data={"language": "python", "code": "print('hello world')"},
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="不应报错"),
                Assertion(type=AssertionType.CONTAINS, expected="hello world", description="输出 hello world"),
            ],
        ),
        ToolEvalCase(
            id="ec_02",
            tool_name="execute_code",
            description="Python - 数学计算",
            category="normal",
            input_data={"language": "python", "code": "import math\nprint(math.pi)"},
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="不应报错"),
                Assertion(type=AssertionType.CONTAINS, expected="3.14", description="输出包含 pi"),
            ],
        ),
        ToolEvalCase(
            id="ec_03",
            tool_name="execute_code",
            description="Python - 列表处理",
            category="normal",
            input_data={"language": "python", "code": "data = [1,2,3,4,5]\nprint(sum(data))"},
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="不应报错"),
                Assertion(type=AssertionType.CONTAINS, expected="15", description="输出包含 15"),
            ],
        ),
        ToolEvalCase(
            id="ec_04",
            tool_name="execute_code",
            description="Python - JSON 处理",
            category="normal",
            input_data={"language": "python", "code": "import json\ndata = {'name': 'test', 'value': 42}\nprint(json.dumps(data))"},
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="不应报错"),
                Assertion(type=AssertionType.CONTAINS, expected="test", description="输出包含 test"),
            ],
        ),
        # ── 正常场景: JavaScript ──
        ToolEvalCase(
            id="ec_05",
            tool_name="execute_code",
            description="JavaScript - console.log",
            category="normal",
            input_data={"language": "javascript", "code": "console.log('js works')"},
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="不应报错"),
                Assertion(type=AssertionType.CONTAINS, expected="js works", description="输出 js works"),
            ],
        ),
        ToolEvalCase(
            id="ec_06",
            tool_name="execute_code",
            description="JavaScript - 数组操作",
            category="normal",
            input_data={"language": "javascript", "code": "const arr = [1,2,3];\nconsole.log(arr.reduce((a,b)=>a+b, 0));"},
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="不应报错"),
                Assertion(type=AssertionType.CONTAINS, expected="6", description="输出包含 6"),
            ],
        ),
        # ── 正常场景: Shell ──
        ToolEvalCase(
            id="ec_07",
            tool_name="execute_code",
            description="Shell - 脚本执行",
            category="normal",
            input_data={"language": "sh", "code": "echo 'shell script'\ndate +%Y"},
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="不应报错"),
                Assertion(type=AssertionType.CONTAINS, expected="shell script", description="输出包含 shell script"),
            ],
        ),
        # ── 异常场景 ──
        ToolEvalCase(
            id="ec_08",
            tool_name="execute_code",
            description="空代码 - 应返回错误",
            category="error",
            input_data={"language": "python", "code": ""},
            assertions=[
                Assertion(type=AssertionType.IS_ERROR, description="空代码应报错"),
            ],
        ),
        ToolEvalCase(
            id="ec_09",
            tool_name="execute_code",
            description="不支持的语言",
            category="error",
            input_data={"language": "rust", "code": "fn main() {}"},
            assertions=[
                Assertion(type=AssertionType.IS_ERROR, description="不支持的语言应报错"),
            ],
        ),
        ToolEvalCase(
            id="ec_10",
            tool_name="execute_code",
            description="Python 语法错误",
            category="error",
            input_data={"language": "python", "code": "def foo(\n  print('broken'"},
            assertions=[
                Assertion(type=AssertionType.IS_ERROR, description="语法错误应报错"),
            ],
        ),
        ToolEvalCase(
            id="ec_11",
            tool_name="execute_code",
            description="Python 运行时异常",
            category="error",
            input_data={"language": "python", "code": "raise ValueError('test error')"},
            assertions=[
                Assertion(type=AssertionType.IS_ERROR, description="运行时异常应报错"),
            ],
        ),
        # ── 边界场景 ──
        ToolEvalCase(
            id="ec_12",
            tool_name="execute_code",
            description="超时代码",
            category="boundary",
            input_data={"language": "python", "code": "import time\ntime.sleep(10)", "timeout": 2},
            assertions=[
                Assertion(type=AssertionType.IS_ERROR, description="应超时报错"),
            ],
        ),
    ]


def build_file_tools_cases() -> list[ToolEvalCase]:
    """read_file / write_file / search_files 工具评测用例"""
    return [
        # ══ read_file ══
        ToolEvalCase(
            id="rf_01",
            tool_name="read_file",
            description="读取存在的文件",
            category="normal",
            input_data={"path": "/etc/hostname"},
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="不应报错"),
            ],
        ),
        ToolEvalCase(
            id="rf_02",
            tool_name="read_file",
            description="读取不存在的文件",
            category="error",
            input_data={"path": "/nonexistent/path/file.txt"},
            assertions=[
                Assertion(type=AssertionType.IS_ERROR, description="不存在的文件应报错"),
            ],
        ),
        ToolEvalCase(
            id="rf_03",
            tool_name="read_file",
            description="空路径 - 应返回错误",
            category="error",
            input_data={"path": ""},
            assertions=[
                Assertion(type=AssertionType.IS_ERROR, description="空路径应报错"),
            ],
        ),
        ToolEvalCase(
            id="rf_04",
            tool_name="read_file",
            description="按行范围读取 - offset + limit",
            category="normal",
            input_data={"path": "/etc/passwd", "offset": 0, "limit": 3},
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="不应报错"),
            ],
        ),
        ToolEvalCase(
            id="rf_05",
            tool_name="read_file",
            description="offset 超出文件行数",
            category="boundary",
            input_data={"path": "/etc/hostname", "offset": 99999, "limit": 10},
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="不应崩溃"),
            ],
        ),

        # ══ write_file ══
        ToolEvalCase(
            id="wf_01",
            tool_name="write_file",
            description="写入新文件",
            category="normal",
            input_data={"path": "/tmp/eval_test_write.txt", "content": "hello eval"},
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="写入不应报错"),
                Assertion(type=AssertionType.CONTAINS, expected="已写入", description="提示已写入"),
            ],
        ),
        ToolEvalCase(
            id="wf_02",
            tool_name="write_file",
            description="写入多行内容",
            category="normal",
            input_data={"path": "/tmp/eval_multiline.txt", "content": "line1\nline2\nline3"},
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="不应报错"),
                Assertion(type=AssertionType.CONTAINS, expected="3 行", description="提示 3 行"),
            ],
        ),
        ToolEvalCase(
            id="wf_03",
            tool_name="write_file",
            description="写入到不存在的深层目录（自动创建）",
            category="normal",
            input_data={"path": "/tmp/eval_deep/sub/dir/file.txt", "content": "deep"},
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="自动创建目录不应报错"),
            ],
        ),
        ToolEvalCase(
            id="wf_04",
            tool_name="write_file",
            description="空路径 - 应返回错误",
            category="error",
            input_data={"path": "", "content": "test"},
            assertions=[
                Assertion(type=AssertionType.IS_ERROR, description="空路径应报错"),
            ],
        ),
        ToolEvalCase(
            id="wf_05",
            tool_name="write_file",
            description="写入空内容",
            category="boundary",
            input_data={"path": "/tmp/eval_empty.txt", "content": ""},
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="空内容应允许写入"),
            ],
        ),
        ToolEvalCase(
            id="wf_06",
            tool_name="write_file",
            description="副作用验证 - 写入后可读取",
            category="side_effect",
            input_data={"path": "/tmp/eval_side_effect.txt", "content": "side_effect_value"},
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="写入不应报错"),
                Assertion(
                    type=AssertionType.SIDE_EFFECT,
                    description="写入后通过 read_file 能读到",
                    expected={
                        "verify_tool": "read_file",
                        "verify_input": {"path": "/tmp/eval_side_effect.txt"},
                        "verify_path": "",
                        "verify_value": "side_effect_value",
                    },
                ),
            ],
        ),

        # ══ search_files ══
        ToolEvalCase(
            id="sf_01",
            tool_name="search_files",
            description="搜索存在的内容",
            category="normal",
            input_data={"pattern": "root", "path": "/etc", "include": "passwd"},
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="不应报错"),
                Assertion(type=AssertionType.CONTAINS, expected="root", description="结果包含 root"),
            ],
        ),
        ToolEvalCase(
            id="sf_02",
            tool_name="search_files",
            description="搜索不存在的内容",
            category="normal",
            input_data={"pattern": "zzz_nonexistent_xyz_999", "path": "/etc"},
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="未找到不应报错"),
                Assertion(type=AssertionType.CONTAINS, expected="未找到", description="提示未找到"),
            ],
        ),
        ToolEvalCase(
            id="sf_03",
            tool_name="search_files",
            description="空模式 - 应返回错误",
            category="error",
            input_data={"pattern": ""},
            assertions=[
                Assertion(type=AssertionType.IS_ERROR, description="空模式应报错"),
            ],
        ),
        ToolEvalCase(
            id="sf_04",
            tool_name="search_files",
            description="使用 include 过滤文件类型",
            category="normal",
            input_data={"pattern": "import", "path": ".", "include": "*.py"},
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="不应报错"),
            ],
        ),
    ]


def build_manage_memory_cases() -> list[ToolEvalCase]:
    """manage_memory 工具评测用例"""
    return [
        # ── 正常场景 ──
        ToolEvalCase(
            id="mm_01",
            tool_name="manage_memory",
            description="list - 列出所有记忆",
            category="normal",
            input_data={"action": "list"},
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="不应报错"),
            ],
        ),
        ToolEvalCase(
            id="mm_02",
            tool_name="manage_memory",
            description="list - 按关键词搜索",
            category="normal",
            input_data={"action": "list", "keyword": "客户"},
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="不应报错"),
            ],
        ),
        ToolEvalCase(
            id="mm_03",
            tool_name="manage_memory",
            description="list - 按维度筛选",
            category="normal",
            input_data={"action": "list", "dimension": "customer_context"},
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="不应报错"),
            ],
        ),
        ToolEvalCase(
            id="mm_04",
            tool_name="manage_memory",
            description="list - 同时按关键词和维度筛选",
            category="normal",
            input_data={"action": "list", "keyword": "张三", "dimension": "user_profile"},
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="不应报错"),
            ],
        ),
        ToolEvalCase(
            id="mm_05",
            tool_name="manage_memory",
            description="delete - 按关键词删除",
            category="normal",
            input_data={"action": "delete", "keyword": "测试记忆"},
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="不应报错"),
                Assertion(type=AssertionType.CONTAINS, expected="已删除", description="提示已删除"),
            ],
        ),
        ToolEvalCase(
            id="mm_06",
            tool_name="manage_memory",
            description="delete_by_ids - 按 ID 删除",
            category="normal",
            input_data={"action": "delete_by_ids", "ids": [1, 2, 3]},
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="不应报错"),
                Assertion(type=AssertionType.CONTAINS, expected="已删除", description="提示已删除"),
            ],
        ),
        ToolEvalCase(
            id="mm_07",
            tool_name="manage_memory",
            description="clear - 清空所有记忆",
            category="normal",
            input_data={"action": "clear"},
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="不应报错"),
                Assertion(type=AssertionType.CONTAINS, expected="已清空", description="提示已清空"),
            ],
        ),
        # ── 异常场景 ──
        ToolEvalCase(
            id="mm_08",
            tool_name="manage_memory",
            description="delete - 缺少 keyword 参数",
            category="error",
            input_data={"action": "delete"},
            assertions=[
                Assertion(type=AssertionType.IS_ERROR, description="缺少 keyword 应报错"),
            ],
        ),
        ToolEvalCase(
            id="mm_09",
            tool_name="manage_memory",
            description="delete_by_ids - 缺少 ids 参数",
            category="error",
            input_data={"action": "delete_by_ids"},
            assertions=[
                Assertion(type=AssertionType.IS_ERROR, description="缺少 ids 应报错"),
            ],
        ),
        ToolEvalCase(
            id="mm_10",
            tool_name="manage_memory",
            description="未知 action",
            category="error",
            input_data={"action": "unknown_action"},
            assertions=[
                Assertion(type=AssertionType.IS_ERROR, description="未知 action 应报错"),
            ],
        ),
        # ── 边界场景 ──
        ToolEvalCase(
            id="mm_11",
            tool_name="manage_memory",
            description="delete_by_ids - 空 ids 列表",
            category="error",
            input_data={"action": "delete_by_ids", "ids": []},
            assertions=[
                Assertion(type=AssertionType.IS_ERROR, description="空 ids 应报错"),
            ],
        ),
        ToolEvalCase(
            id="mm_12",
            tool_name="manage_memory",
            description="list - 超长关键词",
            category="boundary",
            input_data={"action": "list", "keyword": "x" * 500},
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="不应崩溃"),
            ],
        ),
    ]


def build_memory_read_cases() -> list[ToolEvalCase]:
    """memory_read 工具评测用例"""
    return [
        # ── 正常场景 ──
        ToolEvalCase(
            id="mrd_01",
            tool_name="memory_read",
            description="L2 - 读取叶子记忆详情",
            category="normal",
            input_data={"memory_id": "mem_001", "level": "L2"},
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="不应报错"),
            ],
        ),
        ToolEvalCase(
            id="mrd_02",
            tool_name="memory_read",
            description="L1 - 读取目录结构化概览",
            category="normal",
            input_data={"memory_id": "dir_001", "level": "L1"},
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="不应报错"),
            ],
        ),
        ToolEvalCase(
            id="mrd_03",
            tool_name="memory_read",
            description="默认 level（应为 L2）",
            category="normal",
            input_data={"memory_id": "mem_002"},
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="不应报错"),
            ],
        ),
        # ── 异常场景 ──
        ToolEvalCase(
            id="mrd_04",
            tool_name="memory_read",
            description="空 memory_id",
            category="error",
            input_data={"memory_id": ""},
            assertions=[
                Assertion(type=AssertionType.IS_ERROR, description="空 ID 应报错"),
            ],
        ),
        ToolEvalCase(
            id="mrd_05",
            tool_name="memory_read",
            description="不存在的 memory_id",
            category="error",
            input_data={"memory_id": "nonexistent_memory_xyz"},
            assertions=[
                Assertion(type=AssertionType.IS_ERROR, description="不存在的记忆应报错"),
            ],
        ),
        # ── 边界场景 ──
        ToolEvalCase(
            id="mrd_06",
            tool_name="memory_read",
            description="超长 memory_id",
            category="boundary",
            input_data={"memory_id": "x" * 200, "level": "L2"},
            assertions=[
                Assertion(type=AssertionType.IS_ERROR, description="超长 ID 应报错或返回未找到"),
            ],
        ),
    ]


def build_default_suite() -> ToolEvalSuite:
    """构建默认的完整评测集"""
    all_cases = (
        build_query_schema_cases()
        + build_query_data_cases()
        + build_modify_data_cases()
        + build_analyze_data_cases()
        + build_metarepo_cases()
        + build_terminal_cases()
        + build_execute_code_cases()
        + build_file_tools_cases()
        + build_manage_memory_cases()
        + build_memory_read_cases()
    )

    return ToolEvalSuite(
        id="suite_default",
        name="Tool 评测 — 默认全量",
        description="覆盖所有内置工具的正常/异常/边界/副作用场景",
        cases=all_cases,
    )
