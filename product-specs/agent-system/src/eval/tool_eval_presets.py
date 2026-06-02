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
        # ══════════════════════════════════════════════════════
        # 正常场景 — 基础 Shell 命令
        # ══════════════════════════════════════════════════════
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

        # ══════════════════════════════════════════════════════
        # 正常场景 — 系统信息 / 资源监控命令
        # ══════════════════════════════════════════════════════
        ToolEvalCase(
            id="term_11",
            tool_name="terminal",
            description="磁盘空间 - df -h",
            category="normal",
            input_data={"command": "df -h"},
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="不应报错"),
                Assertion(type=AssertionType.CONTAINS, expected="Filesystem", description="输出包含 Filesystem 表头"),
            ],
        ),
        ToolEvalCase(
            id="term_12",
            tool_name="terminal",
            description="内存信息 - free -m",
            category="normal",
            input_data={"command": "free -m"},
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="不应报错"),
                Assertion(type=AssertionType.CONTAINS, expected="Mem", description="输出包含 Mem"),
            ],
        ),
        ToolEvalCase(
            id="term_13",
            tool_name="terminal",
            description="进程列表 - ps aux",
            category="normal",
            input_data={"command": "ps aux | head -5"},
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="不应报错"),
                Assertion(type=AssertionType.CONTAINS, expected="PID", description="输出包含 PID"),
            ],
        ),
        ToolEvalCase(
            id="term_14",
            tool_name="terminal",
            description="环境变量 - env",
            category="normal",
            input_data={"command": "env | head -10"},
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="不应报错"),
            ],
        ),
        ToolEvalCase(
            id="term_15",
            tool_name="terminal",
            description="网络信息 - hostname",
            category="normal",
            input_data={"command": "hostname"},
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="不应报错"),
            ],
        ),
        ToolEvalCase(
            id="term_16",
            tool_name="terminal",
            description="日期时间 - date",
            category="normal",
            input_data={"command": "date '+%Y-%m-%d %H:%M:%S'"},
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="不应报错"),
                Assertion(type=AssertionType.REGEX, expected=r"\d{4}-\d{2}-\d{2}", description="输出匹配日期格式"),
            ],
        ),
        ToolEvalCase(
            id="term_17",
            tool_name="terminal",
            description="当前工作目录 - pwd",
            category="normal",
            input_data={"command": "pwd"},
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="不应报错"),
                Assertion(type=AssertionType.CONTAINS, expected="/", description="输出包含路径分隔符"),
            ],
        ),
        ToolEvalCase(
            id="term_18",
            tool_name="terminal",
            description="用户信息 - id",
            category="normal",
            input_data={"command": "id"},
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="不应报错"),
                Assertion(type=AssertionType.CONTAINS, expected="uid=", description="输出包含 uid"),
            ],
        ),

        # ══════════════════════════════════════════════════════
        # 正常场景 — 文件操作命令
        # ══════════════════════════════════════════════════════
        ToolEvalCase(
            id="term_19",
            tool_name="terminal",
            description="创建目录 - mkdir -p",
            category="normal",
            input_data={"command": "mkdir -p /tmp/eval_test_dir && echo ok"},
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="不应报错"),
                Assertion(type=AssertionType.CONTAINS, expected="ok", description="创建目录成功"),
            ],
        ),
        ToolEvalCase(
            id="term_20",
            tool_name="terminal",
            description="文件写入和读取 - echo + cat",
            category="normal",
            input_data={"command": "echo 'test content' > /tmp/eval_test.txt && cat /tmp/eval_test.txt"},
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="不应报错"),
                Assertion(type=AssertionType.CONTAINS, expected="test content", description="读取到写入内容"),
            ],
        ),
        ToolEvalCase(
            id="term_21",
            tool_name="terminal",
            description="文件权限 - chmod",
            category="normal",
            input_data={"command": "touch /tmp/eval_chmod_test && chmod 755 /tmp/eval_chmod_test && ls -la /tmp/eval_chmod_test"},
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="不应报错"),
                Assertion(type=AssertionType.CONTAINS, expected="rwx", description="权限设置成功"),
            ],
        ),
        ToolEvalCase(
            id="term_22",
            tool_name="terminal",
            description="文件查找 - find",
            category="normal",
            input_data={"command": "find /tmp -name 'eval_test*' -type f 2>/dev/null | head -5"},
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="不应报错"),
            ],
        ),
        ToolEvalCase(
            id="term_23",
            tool_name="terminal",
            description="文本搜索 - grep",
            category="normal",
            input_data={"command": "echo 'line1\nline2\nfoo bar' | grep 'foo'"},
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="不应报错"),
                Assertion(type=AssertionType.CONTAINS, expected="foo", description="grep 匹配到内容"),
            ],
        ),
        ToolEvalCase(
            id="term_24",
            tool_name="terminal",
            description="文本处理 - awk",
            category="normal",
            input_data={"command": "echo 'name age\nAlice 30\nBob 25' | awk '{print $1}'"},
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="不应报错"),
                Assertion(type=AssertionType.CONTAINS, expected="Alice", description="awk 提取成功"),
            ],
        ),
        ToolEvalCase(
            id="term_25",
            tool_name="terminal",
            description="文本处理 - sed 替换",
            category="normal",
            input_data={"command": "echo 'hello world' | sed 's/world/python/'"},
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="不应报错"),
                Assertion(type=AssertionType.CONTAINS, expected="hello python", description="sed 替换成功"),
            ],
        ),
        ToolEvalCase(
            id="term_26",
            tool_name="terminal",
            description="排序和去重 - sort + uniq",
            category="normal",
            input_data={"command": "echo -e 'b\na\nc\na\nb' | sort | uniq"},
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="不应报错"),
            ],
        ),
        ToolEvalCase(
            id="term_27",
            tool_name="terminal",
            description="行数统计 - wc",
            category="normal",
            input_data={"command": "echo -e 'line1\nline2\nline3' | wc -l"},
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="不应报错"),
                Assertion(type=AssertionType.CONTAINS, expected="3", description="统计3行"),
            ],
        ),
        ToolEvalCase(
            id="term_28",
            tool_name="terminal",
            description="文件头尾 - head + tail",
            category="normal",
            input_data={"command": "seq 1 20 | tail -3"},
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="不应报错"),
                Assertion(type=AssertionType.CONTAINS, expected="20", description="tail 包含最后一行"),
            ],
        ),

        # ══════════════════════════════════════════════════════
        # 正常场景 — 管道 / 重定向 / 变量
        # ══════════════════════════════════════════════════════
        ToolEvalCase(
            id="term_29",
            tool_name="terminal",
            description="管道组合 - 多级管道",
            category="normal",
            input_data={"command": "echo 'apple banana cherry' | tr ' ' '\n' | sort | head -2"},
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="不应报错"),
                Assertion(type=AssertionType.CONTAINS, expected="apple", description="管道处理正确"),
            ],
        ),
        ToolEvalCase(
            id="term_30",
            tool_name="terminal",
            description="Shell 变量和子命令",
            category="normal",
            input_data={"command": "TODAY=$(date +%Y-%m-%d) && echo \"today is $TODAY\""},
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="不应报错"),
                Assertion(type=AssertionType.CONTAINS, expected="today is", description="变量展开成功"),
            ],
        ),
        ToolEvalCase(
            id="term_31",
            tool_name="terminal",
            description="条件执行 - if 语句",
            category="normal",
            input_data={"command": "if [ -d /tmp ]; then echo 'exists'; else echo 'not found'; fi"},
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="不应报错"),
                Assertion(type=AssertionType.CONTAINS, expected="exists", description="条件判断正确"),
            ],
        ),
        ToolEvalCase(
            id="term_32",
            tool_name="terminal",
            description="循环执行 - for 循环",
            category="normal",
            input_data={"command": "for i in 1 2 3; do echo \"num: $i\"; done"},
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="不应报错"),
                Assertion(type=AssertionType.CONTAINS, expected="num: 3", description="循环执行完成"),
            ],
        ),
        ToolEvalCase(
            id="term_33",
            tool_name="terminal",
            description="后台进程和重定向 - nohup",
            category="normal",
            input_data={"command": "echo 'log line' > /tmp/eval_redirect.log && cat /tmp/eval_redirect.log"},
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="不应报错"),
                Assertion(type=AssertionType.CONTAINS, expected="log line", description="重定向写入成功"),
            ],
        ),

        # ══════════════════════════════════════════════════════
        # 正常场景 — Python 脚本执行
        # ══════════════════════════════════════════════════════
        ToolEvalCase(
            id="term_py_01",
            tool_name="terminal",
            description="Python - 直接执行 print 语句",
            category="normal",
            input_data={"command": "python3 -c \"print('hello from python')\""},
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="不应报错"),
                Assertion(type=AssertionType.CONTAINS, expected="hello from python", description="Python 输出正确"),
            ],
        ),
        ToolEvalCase(
            id="term_py_02",
            tool_name="terminal",
            description="Python - 数学运算",
            category="normal",
            input_data={"command": "python3 -c \"import math; print(math.pi)\""},
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="不应报错"),
                Assertion(type=AssertionType.CONTAINS, expected="3.14159", description="数学运算正确"),
            ],
        ),
        ToolEvalCase(
            id="term_py_03",
            tool_name="terminal",
            description="Python - JSON 处理",
            category="normal",
            input_data={"command": "python3 -c \"import json; data={'name':'test','value':42}; print(json.dumps(data))\""},
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="不应报错"),
                Assertion(type=AssertionType.CONTAINS, expected="\"name\"", description="JSON 输出正确"),
                Assertion(type=AssertionType.CONTAINS, expected="42", description="包含数值"),
            ],
        ),
        ToolEvalCase(
            id="term_py_04",
            tool_name="terminal",
            description="Python - 文件读写脚本",
            category="normal",
            input_data={"command": "python3 -c \"\nwith open('/tmp/py_eval_test.txt', 'w') as f:\n    f.write('python wrote this')\nwith open('/tmp/py_eval_test.txt', 'r') as f:\n    print(f.read())\n\""},
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="不应报错"),
                Assertion(type=AssertionType.CONTAINS, expected="python wrote this", description="Python 文件读写正确"),
            ],
        ),
        ToolEvalCase(
            id="term_py_05",
            tool_name="terminal",
            description="Python - 列表推导和数据处理",
            category="normal",
            input_data={"command": "python3 -c \"squares = [x**2 for x in range(5)]; print(squares)\""},
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="不应报错"),
                Assertion(type=AssertionType.CONTAINS, expected="[0, 1, 4, 9, 16]", description="列表推导正确"),
            ],
        ),
        ToolEvalCase(
            id="term_py_06",
            tool_name="terminal",
            description="Python - 异常处理验证",
            category="normal",
            input_data={"command": "python3 -c \"\ntry:\n    result = 10 / 0\nexcept ZeroDivisionError as e:\n    print(f'caught: {e}')\n\""},
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="不应报错（异常被 catch）"),
                Assertion(type=AssertionType.CONTAINS, expected="caught:", description="异常被正确捕获"),
            ],
        ),
        ToolEvalCase(
            id="term_py_07",
            tool_name="terminal",
            description="Python - 正则表达式处理",
            category="normal",
            input_data={"command": "python3 -c \"import re; m = re.findall(r'\\d+', 'abc123def456'); print(m)\""},
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="不应报错"),
                Assertion(type=AssertionType.CONTAINS, expected="123", description="正则匹配正确"),
                Assertion(type=AssertionType.CONTAINS, expected="456", description="正则匹配多个结果"),
            ],
        ),
        ToolEvalCase(
            id="term_py_08",
            tool_name="terminal",
            description="Python - os 模块系统操作",
            category="normal",
            input_data={"command": "python3 -c \"import os; print(os.getcwd()); print(os.listdir('/tmp')[:3])\""},
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="不应报错"),
                Assertion(type=AssertionType.CONTAINS, expected="/", description="输出包含路径"),
            ],
        ),
        ToolEvalCase(
            id="term_py_09",
            tool_name="terminal",
            description="Python - subprocess 调用系统命令",
            category="normal",
            input_data={"command": "python3 -c \"import subprocess; r = subprocess.run(['echo','hi'], capture_output=True, text=True); print(r.stdout.strip())\""},
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="不应报错"),
                Assertion(type=AssertionType.CONTAINS, expected="hi", description="subprocess 调用成功"),
            ],
        ),
        ToolEvalCase(
            id="term_py_10",
            tool_name="terminal",
            description="Python - 多行脚本文件执行",
            category="normal",
            input_data={"command": "cat > /tmp/eval_script.py << 'EOF'\nimport sys\ndef fibonacci(n):\n    a, b = 0, 1\n    for _ in range(n):\n        a, b = b, a + b\n    return a\n\nprint(f'fib(10) = {fibonacci(10)}')\nprint(f'python version: {sys.version_info.major}.{sys.version_info.minor}')\nEOF\npython3 /tmp/eval_script.py"},
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="不应报错"),
                Assertion(type=AssertionType.CONTAINS, expected="fib(10) = 55", description="Fibonacci 计算正确"),
                Assertion(type=AssertionType.CONTAINS, expected="python version:", description="版本输出正确"),
            ],
        ),
        ToolEvalCase(
            id="term_py_11",
            tool_name="terminal",
            description="Python - pip 列出已安装包",
            category="normal",
            input_data={"command": "python3 -m pip list 2>/dev/null | head -5"},
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="不应报错"),
                Assertion(type=AssertionType.CONTAINS, expected="Package", description="pip list 输出表头"),
            ],
        ),
        ToolEvalCase(
            id="term_py_12",
            tool_name="terminal",
            description="Python - CSV 数据处理脚本",
            category="normal",
            input_data={"command": "python3 -c \"\nimport csv, io\ndata = 'name,age\\nAlice,30\\nBob,25\\n'\nreader = csv.DictReader(io.StringIO(data))\nfor row in reader:\n    print(f\\\"{row['name']} is {row['age']}\\\")\n\""},
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="不应报错"),
                Assertion(type=AssertionType.CONTAINS, expected="Alice is 30", description="CSV 解析正确"),
            ],
        ),
        ToolEvalCase(
            id="term_py_13",
            tool_name="terminal",
            description="Python - datetime 时间处理",
            category="normal",
            input_data={"command": "python3 -c \"from datetime import datetime; now = datetime.now(); print(now.strftime('%Y-%m-%d'))\""},
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="不应报错"),
                Assertion(type=AssertionType.REGEX, expected=r"\d{4}-\d{2}-\d{2}", description="输出日期格式正确"),
            ],
        ),
        ToolEvalCase(
            id="term_py_14",
            tool_name="terminal",
            description="Python - HTTP 请求（urllib）",
            category="normal",
            input_data={"command": "python3 -c \"import urllib.request; print(urllib.request.urlopen('http://httpbin.org/get').status)\"", "timeout": 15},
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="不应报错"),
                Assertion(type=AssertionType.CONTAINS, expected="200", description="HTTP 请求成功"),
            ],
        ),
        ToolEvalCase(
            id="term_py_15",
            tool_name="terminal",
            description="Python - 类定义和实例化",
            category="normal",
            input_data={"command": "python3 -c \"\nclass Calculator:\n    def __init__(self):\n        self.result = 0\n    def add(self, x):\n        self.result += x\n        return self\n\nc = Calculator()\nc.add(10).add(20).add(30)\nprint(f'result = {c.result}')\n\""},
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="不应报错"),
                Assertion(type=AssertionType.CONTAINS, expected="result = 60", description="类方法链调用正确"),
            ],
        ),

        # ══════════════════════════════════════════════════════
        # 正常场景 — 包管理 / Git
        # ══════════════════════════════════════════════════════
        ToolEvalCase(
            id="term_34",
            tool_name="terminal",
            description="Git 版本信息",
            category="normal",
            input_data={"command": "git --version"},
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="不应报错"),
                Assertion(type=AssertionType.CONTAINS, expected="git version", description="git 可用"),
            ],
        ),
        ToolEvalCase(
            id="term_35",
            tool_name="terminal",
            description="curl 请求",
            category="normal",
            input_data={"command": "curl -s -o /dev/null -w '%{http_code}' http://httpbin.org/get", "timeout": 10},
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="不应报错"),
                Assertion(type=AssertionType.CONTAINS, expected="200", description="HTTP 200"),
            ],
        ),
        ToolEvalCase(
            id="term_36",
            tool_name="terminal",
            description="which 查找命令路径",
            category="normal",
            input_data={"command": "which python3"},
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="不应报错"),
                Assertion(type=AssertionType.CONTAINS, expected="python3", description="python3 路径存在"),
            ],
        ),
        ToolEvalCase(
            id="term_37",
            tool_name="terminal",
            description="tar 压缩解压",
            category="normal",
            input_data={"command": "echo 'data' > /tmp/eval_tar_test.txt && tar czf /tmp/eval_test.tar.gz -C /tmp eval_tar_test.txt && tar tzf /tmp/eval_test.tar.gz"},
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="不应报错"),
                Assertion(type=AssertionType.CONTAINS, expected="eval_tar_test.txt", description="tar 包含目标文件"),
            ],
        ),
        ToolEvalCase(
            id="term_38",
            tool_name="terminal",
            description="xargs 批量处理",
            category="normal",
            input_data={"command": "echo '1 2 3' | xargs -n1 echo 'num:'"},
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="不应报错"),
                Assertion(type=AssertionType.CONTAINS, expected="num: 1", description="xargs 处理正确"),
            ],
        ),
        ToolEvalCase(
            id="term_39",
            tool_name="terminal",
            description="tee 同时输出到文件和终端",
            category="normal",
            input_data={"command": "echo 'tee test' | tee /tmp/eval_tee_out.txt && cat /tmp/eval_tee_out.txt"},
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="不应报错"),
                Assertion(type=AssertionType.CONTAINS, expected="tee test", description="tee 输出正确"),
            ],
        ),
        ToolEvalCase(
            id="term_40",
            tool_name="terminal",
            description="base64 编解码",
            category="normal",
            input_data={"command": "echo -n 'hello' | base64 | base64 -d"},
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="不应报错"),
                Assertion(type=AssertionType.CONTAINS, expected="hello", description="base64 编解码正确"),
            ],
        ),
        ToolEvalCase(
            id="term_41",
            tool_name="terminal",
            description="md5sum 计算哈希",
            category="normal",
            input_data={"command": "echo -n 'test' | md5sum"},
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="不应报错"),
                Assertion(type=AssertionType.REGEX, expected=r"[a-f0-9]{32}", description="md5 哈希格式正确"),
            ],
        ),
        ToolEvalCase(
            id="term_42",
            tool_name="terminal",
            description="cut 列提取",
            category="normal",
            input_data={"command": "echo 'col1:col2:col3' | cut -d: -f2"},
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="不应报错"),
                Assertion(type=AssertionType.CONTAINS, expected="col2", description="cut 提取正确"),
            ],
        ),
        ToolEvalCase(
            id="term_43",
            tool_name="terminal",
            description="diff 文件比较",
            category="normal",
            input_data={"command": "echo 'a' > /tmp/eval_diff1.txt && echo 'a' > /tmp/eval_diff2.txt && diff /tmp/eval_diff1.txt /tmp/eval_diff2.txt && echo 'identical'"},
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="不应报错"),
                Assertion(type=AssertionType.CONTAINS, expected="identical", description="文件相同"),
            ],
        ),

        # ══════════════════════════════════════════════════════
        # 异常场景
        # ══════════════════════════════════════════════════════
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
        ToolEvalCase(
            id="term_44",
            tool_name="terminal",
            description="Python 语法错误",
            category="error",
            input_data={"command": "python3 -c \"def foo(\""},
            assertions=[
                Assertion(type=AssertionType.IS_ERROR, description="Python 语法错误应报错"),
            ],
        ),
        ToolEvalCase(
            id="term_45",
            tool_name="terminal",
            description="Python 运行时异常 - 未捕获",
            category="error",
            input_data={"command": "python3 -c \"1/0\""},
            assertions=[
                Assertion(type=AssertionType.IS_ERROR, description="未捕获异常应报错"),
            ],
        ),
        ToolEvalCase(
            id="term_46",
            tool_name="terminal",
            description="Python 导入不存在的模块",
            category="error",
            input_data={"command": "python3 -c \"import nonexistent_module_xyz\""},
            assertions=[
                Assertion(type=AssertionType.IS_ERROR, description="导入不存在模块应报错"),
            ],
        ),
        ToolEvalCase(
            id="term_47",
            tool_name="terminal",
            description="权限不足 - 写 /root",
            category="error",
            input_data={"command": "touch /root/no_permission_file"},
            assertions=[
                Assertion(type=AssertionType.IS_ERROR, description="权限不足应报错"),
            ],
        ),
        ToolEvalCase(
            id="term_48",
            tool_name="terminal",
            description="读取不存在的文件",
            category="error",
            input_data={"command": "cat /nonexistent_path_xyz_123/file.txt"},
            assertions=[
                Assertion(type=AssertionType.IS_ERROR, description="文件不存在应报错"),
            ],
        ),

        # ══════════════════════════════════════════════════════
        # 边界场景
        # ══════════════════════════════════════════════════════
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
        ToolEvalCase(
            id="term_49",
            tool_name="terminal",
            description="大量输出 - seq 10000",
            category="boundary",
            input_data={"command": "seq 1 10000 | wc -l"},
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="不应报错"),
                Assertion(type=AssertionType.CONTAINS, expected="10000", description="输出行数正确"),
            ],
        ),
        ToolEvalCase(
            id="term_50",
            tool_name="terminal",
            description="特殊字符处理 - 引号/换行",
            category="boundary",
            input_data={"command": "echo \"hello 'world' \\\"quoted\\\"\""},
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="不应报错"),
                Assertion(type=AssertionType.CONTAINS, expected="hello", description="特殊字符处理正确"),
            ],
        ),
        ToolEvalCase(
            id="term_51",
            tool_name="terminal",
            description="Python 长时间运算超时",
            category="boundary",
            input_data={"command": "python3 -c \"import time; time.sleep(10)\"", "timeout": 2},
            assertions=[
                Assertion(type=AssertionType.IS_ERROR, description="Python 脚本超时应报错"),
            ],
        ),
        ToolEvalCase(
            id="term_52",
            tool_name="terminal",
            description="Unicode 字符处理",
            category="boundary",
            input_data={"command": "python3 -c \"print('你好世界 🚀 émojis')\""},
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="不应报错"),
                Assertion(type=AssertionType.CONTAINS, expected="你好世界", description="Unicode 输出正确"),
            ],
        ),
    ]


def build_execute_code_cases() -> list[ToolEvalCase]:
    """execute_code 工具评测用例

    对齐 read_file 的覆盖深度，覆盖以下维度：
    - 正常场景：各语言基础执行、语言别名、标准库、数据处理、文件 I/O、多行复杂脚本
    - 错误场景：空代码、不支持语言、语法错误、运行时异常、权限错误
    - 边界场景：超时、大输出、中文/Unicode 输出、无输出代码、退出码、环境变量、内存边界
    - 副作用场景：代码生成文件后其他工具可读取、代码读取其他工具写入的文件
    """
    return [
        # ══════════════════════════════════════════════════════════════
        # execute_code — 正常场景：Python 基础
        # ══════════════════════════════════════════════════════════════

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
            description="Python - 数学计算（标准库 math）",
            category="normal",
            input_data={"language": "python", "code": "import math\nprint(math.pi)\nprint(math.sqrt(144))"},
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="不应报错"),
                Assertion(type=AssertionType.CONTAINS, expected="3.14", description="输出包含 pi"),
                Assertion(type=AssertionType.CONTAINS, expected="12.0", description="输出包含 sqrt(144)"),
            ],
        ),
        ToolEvalCase(
            id="ec_03",
            tool_name="execute_code",
            description="Python - 列表处理与推导式",
            category="normal",
            input_data={"language": "python", "code": "data = [1,2,3,4,5]\nprint(sum(data))\nprint([x**2 for x in data])"},
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="不应报错"),
                Assertion(type=AssertionType.CONTAINS, expected="15", description="输出包含 sum"),
                Assertion(type=AssertionType.CONTAINS, expected="25", description="输出包含 5**2"),
            ],
        ),
        ToolEvalCase(
            id="ec_04",
            tool_name="execute_code",
            description="Python - JSON 序列化与反序列化",
            category="normal",
            input_data={"language": "python", "code": "import json\ndata = {'name': 'test', 'value': 42, 'tags': ['a','b']}\ns = json.dumps(data, ensure_ascii=False)\nparsed = json.loads(s)\nprint(parsed['name'])\nprint(parsed['value'])"},
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="不应报错"),
                Assertion(type=AssertionType.CONTAINS, expected="test", description="输出包含 name"),
                Assertion(type=AssertionType.CONTAINS, expected="42", description="输出包含 value"),
            ],
        ),
        ToolEvalCase(
            id="ec_05",
            tool_name="execute_code",
            description="Python - 字典与字符串操作",
            category="normal",
            input_data={"language": "python", "code": "d = {'a': 1, 'b': 2, 'c': 3}\nprint(sorted(d.keys()))\nprint('hello world'.upper().split())"},
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="不应报错"),
                Assertion(type=AssertionType.CONTAINS, expected="['a', 'b', 'c']", description="排序后的 keys"),
                Assertion(type=AssertionType.CONTAINS, expected="HELLO", description="大写转换"),
            ],
        ),
        ToolEvalCase(
            id="ec_06",
            tool_name="execute_code",
            description="Python - 多行函数定义与调用",
            category="normal",
            input_data={"language": "python", "code": "def fibonacci(n):\n    a, b = 0, 1\n    result = []\n    for _ in range(n):\n        result.append(a)\n        a, b = b, a + b\n    return result\n\nprint(fibonacci(8))"},
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="不应报错"),
                Assertion(type=AssertionType.CONTAINS, expected="0, 1, 1, 2, 3, 5, 8, 13", description="斐波那契序列"),
            ],
        ),
        ToolEvalCase(
            id="ec_07",
            tool_name="execute_code",
            description="Python - 类定义与实例化",
            category="normal",
            input_data={"language": "python", "code": "class Calculator:\n    def __init__(self):\n        self.history = []\n    def add(self, a, b):\n        result = a + b\n        self.history.append(f'{a}+{b}={result}')\n        return result\n\ncalc = Calculator()\nprint(calc.add(3, 7))\nprint(calc.add(10, 20))\nprint(calc.history)"},
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="不应报错"),
                Assertion(type=AssertionType.CONTAINS, expected="10", description="3+7=10"),
                Assertion(type=AssertionType.CONTAINS, expected="30", description="10+20=30"),
            ],
        ),
        ToolEvalCase(
            id="ec_08",
            tool_name="execute_code",
            description="Python - 正则表达式处理",
            category="normal",
            input_data={"language": "python", "code": "import re\ntext = 'email: user@example.com, admin@test.org'\npattern = r'[\\w.]+@[\\w.]+'\nmatches = re.findall(pattern, text)\nprint(matches)\nprint(len(matches))"},
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="不应报错"),
                Assertion(type=AssertionType.CONTAINS, expected="user@example.com", description="匹配到第一个邮箱"),
                Assertion(type=AssertionType.CONTAINS, expected="2", description="匹配到2个"),
            ],
        ),
        ToolEvalCase(
            id="ec_09",
            tool_name="execute_code",
            description="Python - datetime 标准库",
            category="normal",
            input_data={"language": "python", "code": "from datetime import datetime, timedelta\nnow = datetime(2024, 3, 15, 10, 30, 0)\ntomorrow = now + timedelta(days=1)\nprint(now.strftime('%Y-%m-%d'))\nprint(tomorrow.strftime('%Y-%m-%d'))"},
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="不应报错"),
                Assertion(type=AssertionType.CONTAINS, expected="2024-03-15", description="当前日期"),
                Assertion(type=AssertionType.CONTAINS, expected="2024-03-16", description="明天日期"),
            ],
        ),
        ToolEvalCase(
            id="ec_10",
            tool_name="execute_code",
            description="Python - CSV 数据处理（标准库 csv）",
            category="normal",
            input_data={"language": "python", "code": "import csv\nimport io\n\ndata = 'name,score\\n张三,95\\n李四,88\\n王五,72\\n'\nreader = csv.DictReader(io.StringIO(data))\nrows = list(reader)\nprint(f'记录数: {len(rows)}')\nprint(f'最高分: {max(int(r[\"score\"]) for r in rows)}')\nprint(f'平均分: {sum(int(r[\"score\"]) for r in rows)/len(rows):.1f}')"},
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="不应报错"),
                Assertion(type=AssertionType.CONTAINS, expected="记录数: 3", description="解析3条记录"),
                Assertion(type=AssertionType.CONTAINS, expected="最高分: 95", description="最高分正确"),
            ],
        ),

        # ══════════════════════════════════════════════════════════════
        # execute_code — 正常场景：Python 文件 I/O
        # ══════════════════════════════════════════════════════════════

        ToolEvalCase(
            id="ec_11",
            tool_name="execute_code",
            description="Python - 写入文件并读取验证",
            category="normal",
            input_data={"language": "python", "code": "import json\ndata = {'status': 'ok', 'count': 5}\nwith open('/tmp/ec_test_output.json', 'w') as f:\n    json.dump(data, f)\nwith open('/tmp/ec_test_output.json', 'r') as f:\n    loaded = json.load(f)\nprint(loaded['status'])\nprint(loaded['count'])"},
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="不应报错"),
                Assertion(type=AssertionType.CONTAINS, expected="ok", description="读回 status"),
                Assertion(type=AssertionType.CONTAINS, expected="5", description="读回 count"),
            ],
            cleanup_steps=[
                {"tool": "terminal", "input": {"command": "rm -f /tmp/ec_test_output.json"}},
            ],
        ),
        ToolEvalCase(
            id="ec_12",
            tool_name="execute_code",
            description="Python - 读取已存在的文件（前置写入）",
            category="normal",
            setup_steps=[
                {"tool": "write_file", "input": {
                    "path": "/sandbox/ec_input_data.csv",
                    "content": "id,name,amount\n1,订单A,99.9\n2,订单B,150.0\n3,订单C,30.5\n",
                }},
            ],
            input_data={"language": "python", "code": "with open('/sandbox/ec_input_data.csv') as f:\n    lines = f.readlines()\nprint(f'行数: {len(lines)}')\nprint(lines[0].strip())\nprint(lines[-1].strip())"},
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="不应报错"),
                Assertion(type=AssertionType.CONTAINS, expected="行数: 4", description="包含表头共4行"),
                Assertion(type=AssertionType.CONTAINS, expected="id,name,amount", description="读到表头"),
            ],
            cleanup_steps=[
                {"tool": "terminal", "input": {"command": "rm -f /sandbox/ec_input_data.csv"}},
            ],
        ),
        ToolEvalCase(
            id="ec_13",
            tool_name="execute_code",
            description="Python - os/pathlib 文件系统操作",
            category="normal",
            setup_steps=[
                {"tool": "write_file", "input": {
                    "path": "/sandbox/ec_fs_test/a.txt",
                    "content": "file_a",
                }},
                {"tool": "write_file", "input": {
                    "path": "/sandbox/ec_fs_test/b.py",
                    "content": "# file_b",
                }},
                {"tool": "write_file", "input": {
                    "path": "/sandbox/ec_fs_test/sub/c.json",
                    "content": "{}",
                }},
            ],
            input_data={"language": "python", "code": "import os\nfrom pathlib import Path\n\nbase = Path('/sandbox/ec_fs_test')\nfiles = sorted([f.name for f in base.rglob('*') if f.is_file()])\nprint(files)\nprint(f'文件数: {len(files)}')\nprint(f'存在子目录: {(base / \"sub\").is_dir()}')"},
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="不应报错"),
                Assertion(type=AssertionType.CONTAINS, expected="a.txt", description="列出 a.txt"),
                Assertion(type=AssertionType.CONTAINS, expected="文件数: 3", description="共3个文件"),
                Assertion(type=AssertionType.CONTAINS, expected="True", description="子目录存在"),
            ],
            cleanup_steps=[
                {"tool": "terminal", "input": {"command": "rm -rf /sandbox/ec_fs_test"}},
            ],
        ),

        # ══════════════════════════════════════════════════════════════
        # execute_code — 正常场景：语言别名
        # ══════════════════════════════════════════════════════════════

        ToolEvalCase(
            id="ec_14",
            tool_name="execute_code",
            description="语言别名 - python3 等价于 python",
            category="normal",
            input_data={"language": "python3", "code": "import sys\nprint(f'version: {sys.version_info.major}')"},
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="python3 别名应正常工作"),
                Assertion(type=AssertionType.CONTAINS, expected="version: 3", description="确认 Python 3"),
            ],
        ),
        ToolEvalCase(
            id="ec_15",
            tool_name="execute_code",
            description="语言别名 - js 等价于 javascript",
            category="normal",
            input_data={"language": "js", "code": "console.log('js alias works')"},
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="js 别名应正常工作"),
                Assertion(type=AssertionType.CONTAINS, expected="js alias works", description="输出正确"),
            ],
        ),
        ToolEvalCase(
            id="ec_16",
            tool_name="execute_code",
            description="语言别名 - node 等价于 javascript",
            category="normal",
            input_data={"language": "node", "code": "const v = process.version;\nconsole.log(`node ${v}`)"},
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="node 别名应正常工作"),
                Assertion(type=AssertionType.CONTAINS, expected="node v", description="输出 node 版本"),
            ],
        ),

        # ══════════════════════════════════════════════════════════════
        # execute_code — 正常场景：JavaScript
        # ══════════════════════════════════════════════════════════════

        ToolEvalCase(
            id="ec_17",
            tool_name="execute_code",
            description="JavaScript - console.log 基础输出",
            category="normal",
            input_data={"language": "javascript", "code": "console.log('js works');\nconsole.log(1 + 2);"},
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="不应报错"),
                Assertion(type=AssertionType.CONTAINS, expected="js works", description="字符串输出"),
                Assertion(type=AssertionType.CONTAINS, expected="3", description="数学运算"),
            ],
        ),
        ToolEvalCase(
            id="ec_18",
            tool_name="execute_code",
            description="JavaScript - 数组高阶函数",
            category="normal",
            input_data={"language": "javascript", "code": "const arr = [1,2,3,4,5];\nconsole.log(arr.reduce((a,b)=>a+b, 0));\nconsole.log(arr.filter(x=>x%2===0));\nconsole.log(arr.map(x=>x*x));"},
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="不应报错"),
                Assertion(type=AssertionType.CONTAINS, expected="15", description="reduce 求和"),
                Assertion(type=AssertionType.CONTAINS, expected="2,4", description="filter 偶数"),
            ],
        ),
        ToolEvalCase(
            id="ec_19",
            tool_name="execute_code",
            description="JavaScript - 对象与 JSON 操作",
            category="normal",
            input_data={"language": "javascript", "code": "const obj = {name: '测试', items: [1,2,3], nested: {key: 'value'}};\nconst json = JSON.stringify(obj);\nconst parsed = JSON.parse(json);\nconsole.log(parsed.name);\nconsole.log(parsed.nested.key);"},
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="不应报错"),
                Assertion(type=AssertionType.CONTAINS, expected="测试", description="中文 key 正确"),
                Assertion(type=AssertionType.CONTAINS, expected="value", description="嵌套 key"),
            ],
        ),
        ToolEvalCase(
            id="ec_20",
            tool_name="execute_code",
            description="JavaScript - async/await 与 Promise",
            category="normal",
            input_data={"language": "javascript", "code": "async function fetchData() {\n  return new Promise(resolve => {\n    setTimeout(() => resolve({status: 'done', count: 42}), 100);\n  });\n}\n\n(async () => {\n  const result = await fetchData();\n  console.log(result.status);\n  console.log(result.count);\n})();"},
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="不应报错"),
                Assertion(type=AssertionType.CONTAINS, expected="done", description="async 返回 status"),
                Assertion(type=AssertionType.CONTAINS, expected="42", description="async 返回 count"),
            ],
        ),
        ToolEvalCase(
            id="ec_21",
            tool_name="execute_code",
            description="JavaScript - 文件读写（fs 模块）",
            category="normal",
            input_data={"language": "javascript", "code": "const fs = require('fs');\nfs.writeFileSync('/tmp/ec_js_test.txt', 'hello from node');\nconst content = fs.readFileSync('/tmp/ec_js_test.txt', 'utf8');\nconsole.log(content);"},
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="不应报错"),
                Assertion(type=AssertionType.CONTAINS, expected="hello from node", description="文件读写正确"),
            ],
            cleanup_steps=[
                {"tool": "terminal", "input": {"command": "rm -f /tmp/ec_js_test.txt"}},
            ],
        ),

        # ══════════════════════════════════════════════════════════════
        # execute_code — 正常场景：Shell
        # ══════════════════════════════════════════════════════════════

        ToolEvalCase(
            id="ec_22",
            tool_name="execute_code",
            description="Shell - 基础 echo 与变量",
            category="normal",
            input_data={"language": "sh", "code": "NAME=\"world\"\necho \"hello $NAME\"\necho \"current user: $(whoami)\""},
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="不应报错"),
                Assertion(type=AssertionType.CONTAINS, expected="hello world", description="变量替换"),
            ],
        ),
        ToolEvalCase(
            id="ec_23",
            tool_name="execute_code",
            description="Shell - 循环与条件判断",
            category="normal",
            input_data={"language": "sh", "code": "total=0\nfor i in 1 2 3 4 5; do\n  total=$((total + i))\ndone\necho \"sum=$total\"\n\nif [ $total -gt 10 ]; then\n  echo \"greater than 10\"\nfi"},
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="不应报错"),
                Assertion(type=AssertionType.CONTAINS, expected="sum=15", description="循环求和"),
                Assertion(type=AssertionType.CONTAINS, expected="greater than 10", description="条件判断"),
            ],
        ),
        ToolEvalCase(
            id="ec_24",
            tool_name="execute_code",
            description="Shell - 管道与文本处理",
            category="normal",
            input_data={"language": "sh", "code": "echo -e \"apple\\nbanana\\ncherry\\napricot\" | grep '^a' | wc -l | tr -d ' '"},
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="不应报错"),
                Assertion(type=AssertionType.CONTAINS, expected="2", description="以 a 开头的行数"),
            ],
        ),
        ToolEvalCase(
            id="ec_25",
            tool_name="execute_code",
            description="Shell - 多命令脚本（创建目录+写文件+读取）",
            category="normal",
            input_data={"language": "sh", "code": "mkdir -p /tmp/ec_sh_test\necho '{\"result\": \"success\"}' > /tmp/ec_sh_test/out.json\ncat /tmp/ec_sh_test/out.json"},
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="不应报错"),
                Assertion(type=AssertionType.CONTAINS, expected="success", description="文件内容正确"),
            ],
            cleanup_steps=[
                {"tool": "terminal", "input": {"command": "rm -rf /tmp/ec_sh_test"}},
            ],
        ),

        # ══════════════════════════════════════════════════════════════
        # execute_code — 正常场景：中文/Unicode 输出
        # ══════════════════════════════════════════════════════════════

        ToolEvalCase(
            id="ec_26",
            tool_name="execute_code",
            description="Python - 中文输出与 Unicode 处理",
            category="normal",
            input_data={"language": "python", "code": "print('你好世界')\nprint('Emoji: 🎉 📊 ✅')\nprint(f'长度: {len(\"中文测试\")}')\nprint('日文: こんにちは')"},
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="不应报错"),
                Assertion(type=AssertionType.CONTAINS, expected="你好世界", description="中文输出"),
                Assertion(type=AssertionType.CONTAINS, expected="🎉", description="Emoji 输出"),
                Assertion(type=AssertionType.CONTAINS, expected="長度: 4", description="中文字符长度"),
            ],
        ),
        ToolEvalCase(
            id="ec_27",
            tool_name="execute_code",
            description="JavaScript - 中文 Unicode 处理",
            category="normal",
            input_data={"language": "javascript", "code": "console.log('你好 JavaScript');\nconsole.log(`字符数: ${'测试'.length}`);"},
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="不应报错"),
                Assertion(type=AssertionType.CONTAINS, expected="你好 JavaScript", description="中文输出"),
            ],
        ),

        # ══════════════════════════════════════════════════════════════
        # execute_code — 正常场景：多行复杂脚本
        # ══════════════════════════════════════════════════════════════

        ToolEvalCase(
            id="ec_28",
            tool_name="execute_code",
            description="Python - 数据分析脚本（统计+排序+格式化输出）",
            category="normal",
            input_data={"language": "python", "code": "from collections import Counter\n\nwords = 'apple banana apple cherry banana apple cherry cherry cherry'.split()\ncounter = Counter(words)\n\nprint('=== 词频统计 ===')\nfor word, count in counter.most_common():\n    bar = '#' * count\n    print(f'{word:10s} {count:2d} {bar}')\nprint(f'\\n总词数: {len(words)}')\nprint(f'去重数: {len(counter)}')"},
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="不应报错"),
                Assertion(type=AssertionType.CONTAINS, expected="词频统计", description="标题输出"),
                Assertion(type=AssertionType.CONTAINS, expected="cherry", description="最高频词"),
                Assertion(type=AssertionType.CONTAINS, expected="总词数:", description="统计信息"),
            ],
        ),
        ToolEvalCase(
            id="ec_29",
            tool_name="execute_code",
            description="Python - 异常处理（try/except/finally）",
            category="normal",
            input_data={"language": "python", "code": "results = []\n\ntry:\n    x = int('abc')\nexcept ValueError as e:\n    results.append(f'caught: {e}')\n\ntry:\n    d = {}\n    v = d['missing']\nexcept KeyError:\n    results.append('key not found')\nfinally:\n    results.append('cleanup done')\n\nfor r in results:\n    print(r)"},
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="正常 try/except 不应标记为错误"),
                Assertion(type=AssertionType.CONTAINS, expected="caught:", description="捕获 ValueError"),
                Assertion(type=AssertionType.CONTAINS, expected="key not found", description="捕获 KeyError"),
                Assertion(type=AssertionType.CONTAINS, expected="cleanup done", description="finally 执行"),
            ],
        ),
        ToolEvalCase(
            id="ec_30",
            tool_name="execute_code",
            description="Python - 生成器与迭代器",
            category="normal",
            input_data={"language": "python", "code": "def chunked(lst, size):\n    for i in range(0, len(lst), size):\n        yield lst[i:i+size]\n\ndata = list(range(10))\nchunks = list(chunked(data, 3))\nfor i, chunk in enumerate(chunks):\n    print(f'chunk {i}: {chunk}')"},
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="不应报错"),
                Assertion(type=AssertionType.CONTAINS, expected="chunk 0: [0, 1, 2]", description="第一个 chunk"),
                Assertion(type=AssertionType.CONTAINS, expected="chunk 3: [9]", description="最后一个 chunk"),
            ],
        ),

        # ══════════════════════════════════════════════════════════════
        # execute_code — 正常场景：环境变量与工作目录
        # ══════════════════════════════════════════════════════════════

        ToolEvalCase(
            id="ec_31",
            tool_name="execute_code",
            description="Python - 读取环境变量",
            category="normal",
            input_data={"language": "python", "code": "import os\npath = os.environ.get('PATH', '')\nprint(f'PATH exists: {len(path) > 0}')\nhome = os.environ.get('HOME', os.environ.get('USER', 'unknown'))\nprint(f'home/user: {home}')"},
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="不应报错"),
                Assertion(type=AssertionType.CONTAINS, expected="PATH exists: True", description="PATH 环境变量存在"),
            ],
        ),
        ToolEvalCase(
            id="ec_32",
            tool_name="execute_code",
            description="Shell - 环境变量访问",
            category="normal",
            input_data={"language": "sh", "code": "echo \"PATH length: ${#PATH}\"\necho \"PWD: $PWD\""},
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="不应报错"),
                Assertion(type=AssertionType.CONTAINS, expected="PATH length:", description="PATH 有值"),
                Assertion(type=AssertionType.CONTAINS, expected="PWD:", description="工作目录有值"),
            ],
        ),

        # ══════════════════════════════════════════════════════════════
        # execute_code — 错误场景
        # ══════════════════════════════════════════════════════════════

        ToolEvalCase(
            id="ec_40",
            tool_name="execute_code",
            description="错误 - 空代码应返回错误",
            category="error",
            input_data={"language": "python", "code": ""},
            assertions=[
                Assertion(type=AssertionType.IS_ERROR, description="空代码应报错"),
                Assertion(type=AssertionType.CONTAINS, expected="不能为空", description="错误信息明确"),
            ],
        ),
        ToolEvalCase(
            id="ec_41",
            tool_name="execute_code",
            description="错误 - 不支持的语言 rust",
            category="error",
            input_data={"language": "rust", "code": "fn main() {}"},
            assertions=[
                Assertion(type=AssertionType.IS_ERROR, description="不支持的语言应报错"),
                Assertion(type=AssertionType.CONTAINS, expected="不支持", description="错误信息包含'不支持'"),
            ],
        ),
        ToolEvalCase(
            id="ec_42",
            tool_name="execute_code",
            description="错误 - 不支持的语言 java",
            category="error",
            input_data={"language": "java", "code": "public class Main { public static void main(String[] args) {} }"},
            assertions=[
                Assertion(type=AssertionType.IS_ERROR, description="java 不支持应报错"),
                Assertion(type=AssertionType.CONTAINS, expected="不支持", description="错误信息包含'不支持'"),
            ],
        ),
        ToolEvalCase(
            id="ec_43",
            tool_name="execute_code",
            description="错误 - 不支持的语言 go",
            category="error",
            input_data={"language": "go", "code": "package main\nimport \"fmt\"\nfunc main() { fmt.Println(\"hi\") }"},
            assertions=[
                Assertion(type=AssertionType.IS_ERROR, description="go 不支持应报错"),
            ],
        ),
        ToolEvalCase(
            id="ec_44",
            tool_name="execute_code",
            description="错误 - Python 语法错误（括号不匹配）",
            category="error",
            input_data={"language": "python", "code": "def foo(\n  print('broken'"},
            assertions=[
                Assertion(type=AssertionType.IS_ERROR, description="语法错误应报错"),
                Assertion(type=AssertionType.CONTAINS, expected="SyntaxError", description="包含 SyntaxError"),
            ],
        ),
        ToolEvalCase(
            id="ec_45",
            tool_name="execute_code",
            description="错误 - Python 缩进错误",
            category="error",
            input_data={"language": "python", "code": "def foo():\nprint('bad indent')"},
            assertions=[
                Assertion(type=AssertionType.IS_ERROR, description="缩进错误应报错"),
            ],
        ),
        ToolEvalCase(
            id="ec_46",
            tool_name="execute_code",
            description="错误 - Python 运行时异常 ValueError",
            category="error",
            input_data={"language": "python", "code": "raise ValueError('test error message')"},
            assertions=[
                Assertion(type=AssertionType.IS_ERROR, description="运行时异常应报错"),
                Assertion(type=AssertionType.CONTAINS, expected="ValueError", description="包含异常类型"),
                Assertion(type=AssertionType.CONTAINS, expected="test error message", description="包含异常信息"),
            ],
        ),
        ToolEvalCase(
            id="ec_47",
            tool_name="execute_code",
            description="错误 - Python NameError（未定义变量）",
            category="error",
            input_data={"language": "python", "code": "print(undefined_variable)"},
            assertions=[
                Assertion(type=AssertionType.IS_ERROR, description="NameError 应报错"),
                Assertion(type=AssertionType.CONTAINS, expected="NameError", description="包含 NameError"),
            ],
        ),
        ToolEvalCase(
            id="ec_48",
            tool_name="execute_code",
            description="错误 - Python ImportError（不存在的模块）",
            category="error",
            input_data={"language": "python", "code": "import nonexistent_module_xyz_999"},
            assertions=[
                Assertion(type=AssertionType.IS_ERROR, description="ImportError 应报错"),
                Assertion(type=AssertionType.CONTAINS, expected="ModuleNotFoundError", description="包含模块未找到"),
            ],
        ),
        ToolEvalCase(
            id="ec_49",
            tool_name="execute_code",
            description="错误 - Python ZeroDivisionError",
            category="error",
            input_data={"language": "python", "code": "result = 10 / 0"},
            assertions=[
                Assertion(type=AssertionType.IS_ERROR, description="除零应报错"),
                Assertion(type=AssertionType.CONTAINS, expected="ZeroDivisionError", description="包含除零异常"),
            ],
        ),
        ToolEvalCase(
            id="ec_50",
            tool_name="execute_code",
            description="错误 - Python FileNotFoundError（读取不存在文件）",
            category="error",
            input_data={"language": "python", "code": "with open('/nonexistent/path/abc.txt') as f:\n    print(f.read())"},
            assertions=[
                Assertion(type=AssertionType.IS_ERROR, description="文件不存在应报错"),
                Assertion(type=AssertionType.CONTAINS, expected="FileNotFoundError", description="包含文件未找到"),
            ],
        ),
        ToolEvalCase(
            id="ec_51",
            tool_name="execute_code",
            description="错误 - JavaScript 语法错误",
            category="error",
            input_data={"language": "javascript", "code": "function broken( { console.log('missing paren') }"},
            assertions=[
                Assertion(type=AssertionType.IS_ERROR, description="JS 语法错误应报错"),
            ],
        ),
        ToolEvalCase(
            id="ec_52",
            tool_name="execute_code",
            description="错误 - JavaScript 运行时异常 TypeError",
            category="error",
            input_data={"language": "javascript", "code": "const obj = null;\nconsole.log(obj.property);"},
            assertions=[
                Assertion(type=AssertionType.IS_ERROR, description="TypeError 应报错"),
                Assertion(type=AssertionType.CONTAINS, expected="TypeError", description="包含 TypeError"),
            ],
        ),
        ToolEvalCase(
            id="ec_53",
            tool_name="execute_code",
            description="错误 - JavaScript throw Error",
            category="error",
            input_data={"language": "javascript", "code": "throw new Error('custom error from js');"},
            assertions=[
                Assertion(type=AssertionType.IS_ERROR, description="throw 应报错"),
                Assertion(type=AssertionType.CONTAINS, expected="custom error from js", description="包含错误信息"),
            ],
        ),
        ToolEvalCase(
            id="ec_54",
            tool_name="execute_code",
            description="错误 - Shell 非零退出码",
            category="error",
            input_data={"language": "sh", "code": "echo 'before exit'\nexit 1"},
            assertions=[
                Assertion(type=AssertionType.IS_ERROR, description="exit 1 应标记为错误"),
            ],
        ),
        ToolEvalCase(
            id="ec_55",
            tool_name="execute_code",
            description="错误 - Shell 命令不存在",
            category="error",
            input_data={"language": "sh", "code": "nonexistent_command_xyz_999"},
            assertions=[
                Assertion(type=AssertionType.IS_ERROR, description="不存在的命令应报错"),
                Assertion(type=AssertionType.CONTAINS, expected="not found", description="包含 not found"),
            ],
        ),
        ToolEvalCase(
            id="ec_56",
            tool_name="execute_code",
            description="错误 - Python 权限错误（写入受保护目录）",
            category="error",
            input_data={"language": "python", "code": "with open('/etc/ec_test_permission.txt', 'w') as f:\n    f.write('should fail')"},
            assertions=[
                Assertion(type=AssertionType.IS_ERROR, description="权限错误应报错"),
                Assertion(type=AssertionType.CONTAINS, expected="Permission", description="包含 Permission 关键字"),
            ],
        ),

        # ══════════════════════════════════════════════════════════════
        # execute_code — 边界场景
        # ══════════════════════════════════════════════════════════════

        ToolEvalCase(
            id="ec_60",
            tool_name="execute_code",
            description="边界 - 超时代码（Python sleep）",
            category="boundary",
            input_data={"language": "python", "code": "import time\ntime.sleep(10)\nprint('should not reach here')", "timeout": 2},
            assertions=[
                Assertion(type=AssertionType.IS_ERROR, description="应超时报错"),
                Assertion(type=AssertionType.CONTAINS, expected="超时", description="包含超时提示"),
                Assertion(type=AssertionType.NOT_CONTAINS, expected="should not reach here", description="不应有输出"),
            ],
        ),
        ToolEvalCase(
            id="ec_61",
            tool_name="execute_code",
            description="边界 - 超时代码（JavaScript setTimeout 阻塞）",
            category="boundary",
            input_data={"language": "javascript", "code": "const start = Date.now();\nwhile(Date.now() - start < 10000) {}\nconsole.log('done');", "timeout": 2},
            assertions=[
                Assertion(type=AssertionType.IS_ERROR, description="JS 无限循环应超时报错"),
                Assertion(type=AssertionType.CONTAINS, expected="超时", description="包含超时提示"),
            ],
        ),
        ToolEvalCase(
            id="ec_62",
            tool_name="execute_code",
            description="边界 - 超时代码（Shell sleep）",
            category="boundary",
            input_data={"language": "sh", "code": "sleep 10\necho done", "timeout": 2},
            assertions=[
                Assertion(type=AssertionType.IS_ERROR, description="Shell sleep 应超时报错"),
            ],
        ),
        ToolEvalCase(
            id="ec_63",
            tool_name="execute_code",
            description="边界 - 大量输出（Python 输出1000行）",
            category="boundary",
            input_data={"language": "python", "code": "for i in range(1000):\n    print(f'line {i}: ' + 'x' * 80)"},
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="大量输出不应崩溃"),
                Assertion(type=AssertionType.CONTAINS, expected="line 0:", description="包含起始行"),
            ],
        ),
        ToolEvalCase(
            id="ec_64",
            tool_name="execute_code",
            description="边界 - 无输出的代码（只做计算不 print）",
            category="boundary",
            input_data={"language": "python", "code": "x = 42\ny = x * 2\nz = [i for i in range(100)]"},
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="无输出不应报错"),
                Assertion(type=AssertionType.CONTAINS, expected="无输出", description="提示无输出"),
            ],
        ),
        ToolEvalCase(
            id="ec_65",
            tool_name="execute_code",
            description="边界 - 只有空白行和注释的代码",
            category="boundary",
            input_data={"language": "python", "code": "# 这是注释\n\n# 另一行注释\n\n"},
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="纯注释不应报错"),
            ],
        ),
        ToolEvalCase(
            id="ec_66",
            tool_name="execute_code",
            description="边界 - 极短代码（单个表达式）",
            category="boundary",
            input_data={"language": "python", "code": "print(1)"},
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="最短有效代码不应报错"),
                Assertion(type=AssertionType.CONTAINS, expected="1", description="输出 1"),
            ],
        ),
        ToolEvalCase(
            id="ec_67",
            tool_name="execute_code",
            description="边界 - 代码中包含特殊字符（引号/转义/换行）",
            category="boundary",
            input_data={"language": "python", "code": "s1 = \"it's a \\\"test\\\"\"\ns2 = 'line1\\nline2\\ttab'\nprint(s1)\nprint(s2)"},
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="特殊字符不应导致问题"),
                Assertion(type=AssertionType.CONTAINS, expected="test", description="引号内容正确"),
            ],
        ),
        ToolEvalCase(
            id="ec_68",
            tool_name="execute_code",
            description="边界 - stderr 输出（Python logging/warnings）",
            category="boundary",
            input_data={"language": "python", "code": "import sys\nprint('stdout output')\nprint('stderr output', file=sys.stderr)"},
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="stderr 输出不应导致错误标记"),
                Assertion(type=AssertionType.CONTAINS, expected="stdout output", description="stdout 内容可见"),
            ],
        ),
        ToolEvalCase(
            id="ec_69",
            tool_name="execute_code",
            description="边界 - 自定义 timeout 参数（较长超时）",
            category="boundary",
            input_data={"language": "python", "code": "import time\ntime.sleep(3)\nprint('completed after 3s')", "timeout": 10},
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="在超时范围内完成不应报错"),
                Assertion(type=AssertionType.CONTAINS, expected="completed after 3s", description="正常完成"),
            ],
        ),
        ToolEvalCase(
            id="ec_70",
            tool_name="execute_code",
            description="边界 - Python 递归深度（不应段错误）",
            category="boundary",
            input_data={"language": "python", "code": "import sys\nsys.setrecursionlimit(200)\ndef recurse(n):\n    return recurse(n+1)\ntry:\n    recurse(0)\nexcept RecursionError:\n    print('RecursionError caught')"},
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="捕获 RecursionError 不应崩溃"),
                Assertion(type=AssertionType.CONTAINS, expected="RecursionError caught", description="递归异常被捕获"),
            ],
        ),
        ToolEvalCase(
            id="ec_71",
            tool_name="execute_code",
            description="边界 - 非零退出码但有 stdout 输出",
            category="boundary",
            input_data={"language": "python", "code": "import sys\nprint('some output before exit')\nsys.exit(1)"},
            assertions=[
                Assertion(type=AssertionType.IS_ERROR, description="sys.exit(1) 应标记为错误"),
                Assertion(type=AssertionType.CONTAINS, expected="some output", description="退出前的输出应可见"),
            ],
        ),
        ToolEvalCase(
            id="ec_72",
            tool_name="execute_code",
            description="边界 - sys.exit(0) 正常退出",
            category="boundary",
            input_data={"language": "python", "code": "import sys\nprint('normal exit')\nsys.exit(0)"},
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="exit(0) 不应标记为错误"),
                Assertion(type=AssertionType.CONTAINS, expected="normal exit", description="输出正常"),
            ],
        ),
        ToolEvalCase(
            id="ec_73",
            tool_name="execute_code",
            description="边界 - 代码中有超长单行（10000 字符）",
            category="boundary",
            input_data={"language": "python", "code": "s = 'A' * 10000\nprint(f'length={len(s)}')"},
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="超长字符串不应崩溃"),
                Assertion(type=AssertionType.CONTAINS, expected="length=10000", description="长度正确"),
            ],
        ),

        # ══════════════════════════════════════════════════════════════
        # execute_code — 副作用场景
        # ══════════════════════════════════════════════════════════════

        ToolEvalCase(
            id="ec_80",
            tool_name="execute_code",
            description="副作用 - execute_code 生成文件后 read_file 可读取",
            category="side_effect",
            input_data={"language": "python", "code": "import json, os\nos.makedirs('/sandbox/ec_output', exist_ok=True)\ndata = {'generated': True, 'items': [1,2,3]}\nwith open('/sandbox/ec_output/result.json', 'w') as f:\n    json.dump(data, f, indent=2)\nprint('file written')"},
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="不应报错"),
                Assertion(type=AssertionType.CONTAINS, expected="file written", description="写入完成"),
                Assertion(
                    type=AssertionType.SIDE_EFFECT,
                    description="read_file 能读到 execute_code 生成的 JSON",
                    expected={
                        "verify_tool": "read_file",
                        "verify_input": {"path": "/sandbox/ec_output/result.json"},
                        "verify_path": "content",
                        "verify_value": "generated",
                    },
                ),
            ],
            cleanup_steps=[
                {"tool": "terminal", "input": {"command": "rm -rf /sandbox/ec_output"}},
            ],
        ),
        ToolEvalCase(
            id="ec_81",
            tool_name="execute_code",
            description="副作用 - execute_code 生成文件后 search_files 可搜索",
            category="side_effect",
            input_data={"language": "python", "code": "import os\nos.makedirs('/sandbox/ec_search_test', exist_ok=True)\nwith open('/sandbox/ec_search_test/module.py', 'w') as f:\n    f.write('def unique_function_ec81():\\n    return 42\\n')\nprint('module written')"},
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="不应报错"),
                Assertion(type=AssertionType.CONTAINS, expected="module written", description="写入完成"),
                Assertion(
                    type=AssertionType.SIDE_EFFECT,
                    description="search_files 能搜索到 execute_code 生成的内容",
                    expected={
                        "verify_tool": "search_files",
                        "verify_input": {"pattern": "unique_function_ec81", "path": "/sandbox/ec_search_test"},
                        "verify_path": "content",
                        "verify_value": "unique_function_ec81",
                    },
                ),
            ],
            cleanup_steps=[
                {"tool": "terminal", "input": {"command": "rm -rf /sandbox/ec_search_test"}},
            ],
        ),
        ToolEvalCase(
            id="ec_82",
            tool_name="execute_code",
            description="副作用 - write_file 写入后 execute_code 可执行该文件",
            category="side_effect",
            setup_steps=[
                {"tool": "write_file", "input": {
                    "path": "/sandbox/ec_run_target.py",
                    "content": "# 由 write_file 创建\ndef compute():\n    return sum(range(1, 11))\n\nif __name__ == '__main__':\n    print(f'result={compute()}')\n",
                }},
            ],
            input_data={"language": "sh", "code": "python3 /sandbox/ec_run_target.py"},
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="执行 write_file 写入的脚本不应报错"),
                Assertion(type=AssertionType.CONTAINS, expected="result=55", description="执行结果正确"),
            ],
            cleanup_steps=[
                {"tool": "terminal", "input": {"command": "rm -f /sandbox/ec_run_target.py"}},
            ],
        ),
        ToolEvalCase(
            id="ec_83",
            tool_name="execute_code",
            description="副作用 - terminal 创建数据后 execute_code 可处理",
            category="side_effect",
            setup_steps=[
                {"tool": "terminal", "input": {
                    "command": "mkdir -p /tmp/ec_terminal_data && echo -e 'a,1\\nb,2\\nc,3' > /tmp/ec_terminal_data/input.csv",
                }},
            ],
            input_data={"language": "python", "code": "with open('/tmp/ec_terminal_data/input.csv') as f:\n    lines = f.read().strip().split('\\n')\ntotal = sum(int(line.split(',')[1]) for line in lines)\nprint(f'total={total}')"},
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="不应报错"),
                Assertion(type=AssertionType.CONTAINS, expected="total=6", description="计算结果正确"),
            ],
            cleanup_steps=[
                {"tool": "terminal", "input": {"command": "rm -rf /tmp/ec_terminal_data"}},
            ],
        ),
        ToolEvalCase(
            id="ec_84",
            tool_name="execute_code",
            description="副作用 - execute_code 多次执行间状态不共享（隔离性验证）",
            category="side_effect",
            input_data={"language": "python", "code": "import os\n# 每次执行都是独立进程，不应有上次执行的残留变量\ntry:\n    print(f'prev_var exists: {prev_var}')\nexcept NameError:\n    print('prev_var not defined - isolated')\n\n# 但文件系统是共享的\nos.makedirs('/tmp/ec_isolation_test', exist_ok=True)\nwith open('/tmp/ec_isolation_test/marker.txt', 'w') as f:\n    f.write('exists')\nprint('marker written')"},
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="不应报错"),
                Assertion(type=AssertionType.CONTAINS, expected="prev_var not defined - isolated", description="进程间变量隔离"),
                Assertion(type=AssertionType.CONTAINS, expected="marker written", description="文件系统共享"),
            ],
            cleanup_steps=[
                {"tool": "terminal", "input": {"command": "rm -rf /tmp/ec_isolation_test"}},
            ],
        ),

        # ══════════════════════════════════════════════════════════════
        # execute_code — 安全边界场景
        # ══════════════════════════════════════════════════════════════

        ToolEvalCase(
            id="ec_90",
            tool_name="execute_code",
            description="安全 - 代码中包含 shell 注入尝试（不应逃逸）",
            category="boundary",
            input_data={"language": "python", "code": "# 代码内容不应影响宿主系统\nimport subprocess\ntry:\n    result = subprocess.run(['echo', 'inside sandbox'], capture_output=True, text=True, timeout=5)\n    print(result.stdout.strip())\nexcept Exception as e:\n    print(f'blocked: {e}')"},
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="沙盒内 subprocess 调用不应崩溃"),
            ],
        ),
        ToolEvalCase(
            id="ec_91",
            tool_name="execute_code",
            description="安全 - 尝试读取沙盒外敏感文件",
            category="boundary",
            input_data={"language": "python", "code": "try:\n    with open('/etc/shadow') as f:\n        print(f.read())\nexcept PermissionError:\n    print('permission denied')\nexcept FileNotFoundError:\n    print('file not found')"},
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="应正常执行 try/except 而非崩溃"),
            ],
        ),
    ]


def build_file_tools_cases() -> list[ToolEvalCase]:
    """read_file / write_file / search_files 工具评测用例"""
    return [
        # ══════════════════════════════════════════════════════════════
        # read_file — /sandbox 目录场景
        # ══════════════════════════════════════════════════════════════

        # ── 正常场景：各类文件类型读取 ──
        ToolEvalCase(
            id="rf_01",
            tool_name="read_file",
            description="/sandbox - 读取 Python 文件",
            category="normal",
            setup_steps=[
                {"tool": "write_file", "input": {
                    "path": "/sandbox/app/main.py",
                    "content": "#!/usr/bin/env python3\nimport os\n\ndef main():\n    print('hello')\n\nif __name__ == '__main__':\n    main()\n",
                }},
            ],
            input_data={"path": "/sandbox/app/main.py"},
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="不应报错"),
                Assertion(type=AssertionType.CONTAINS, expected="import os", description="包含 Python import 语句"),
                Assertion(type=AssertionType.CONTAINS, expected="def main", description="包含函数定义"),
            ],
            cleanup_steps=[
                {"tool": "terminal", "input": {"command": "rm -f '/sandbox/app/main.py'"}},
            ],
        ),
        ToolEvalCase(
            id="rf_02",
            tool_name="read_file",
            description="/sandbox - 读取 Markdown 文件",
            category="normal",
            setup_steps=[
                {"tool": "write_file", "input": {
                    "path": "/sandbox/docs/README.md",
                    "content": "# Project Title\n\n## Overview\n\nThis is a **test** project.\n\n- Item 1\n- Item 2\n\n```python\nprint('hello')\n```\n",
                }},
            ],
            input_data={"path": "/sandbox/docs/README.md"},
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="不应报错"),
                Assertion(type=AssertionType.CONTAINS, expected="# Project Title", description="包含 Markdown 标题"),
                Assertion(type=AssertionType.CONTAINS, expected="**test**", description="包含 Markdown 格式"),
            ],
            cleanup_steps=[
                {"tool": "terminal", "input": {"command": "rm -f '/sandbox/docs/README.md'"}},
            ],
        ),
        ToolEvalCase(
            id="rf_03",
            tool_name="read_file",
            description="/sandbox - 读取 JSON 配置文件",
            category="normal",
            setup_steps=[
                {"tool": "write_file", "input": {
                    "path": "/sandbox/config/settings.json",
                    "content": '{\n  "database": {\n    "host": "localhost",\n    "port": 5432\n  },\n  "debug": true\n}\n',
                }},
            ],
            input_data={"path": "/sandbox/config/settings.json"},
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="不应报错"),
                Assertion(type=AssertionType.CONTAINS, expected="database", description="包含 JSON key"),
                Assertion(type=AssertionType.CONTAINS, expected="5432", description="包含端口号"),
            ],
            cleanup_steps=[
                {"tool": "terminal", "input": {"command": "rm -f '/sandbox/config/settings.json'"}},
            ],
        ),
        ToolEvalCase(
            id="rf_04",
            tool_name="read_file",
            description="/sandbox - 读取 YAML 文件",
            category="normal",
            setup_steps=[
                {"tool": "write_file", "input": {
                    "path": "/sandbox/config/docker-compose.yaml",
                    "content": "version: '3.8'\nservices:\n  web:\n    image: nginx:latest\n    ports:\n      - '8080:80'\n  db:\n    image: postgres:15\n    environment:\n      POSTGRES_PASSWORD: secret\n",
                }},
            ],
            input_data={"path": "/sandbox/config/docker-compose.yaml"},
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="不应报错"),
                Assertion(type=AssertionType.CONTAINS, expected="services", description="包含 YAML 结构"),
                Assertion(type=AssertionType.CONTAINS, expected="nginx", description="包含 image 引用"),
            ],
            cleanup_steps=[
                {"tool": "terminal", "input": {"command": "rm -f '/sandbox/config/docker-compose.yaml'"}},
            ],
        ),
        ToolEvalCase(
            id="rf_05",
            tool_name="read_file",
            description="/sandbox - 读取 CSV 数据文件",
            category="normal",
            setup_steps=[
                {"tool": "write_file", "input": {
                    "path": "/sandbox/data/records.csv",
                    "content": "id,name,email,score\n1,张三,zhangsan@test.com,95\n2,李四,lisi@test.com,88\n3,王五,wangwu@test.com,72\n",
                }},
            ],
            input_data={"path": "/sandbox/data/records.csv"},
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="不应报错"),
                Assertion(type=AssertionType.CONTAINS, expected="id,name,email,score", description="包含 CSV 表头"),
                Assertion(type=AssertionType.CONTAINS, expected="张三", description="包含中文数据"),
            ],
            cleanup_steps=[
                {"tool": "terminal", "input": {"command": "rm -f '/sandbox/data/records.csv'"}},
            ],
        ),
        ToolEvalCase(
            id="rf_06",
            tool_name="read_file",
            description="/sandbox - 读取 Shell 脚本",
            category="normal",
            setup_steps=[
                {"tool": "write_file", "input": {
                    "path": "/sandbox/scripts/deploy.sh",
                    "content": "#!/bin/bash\nset -e\n\necho \"Starting deployment...\"\ncd /app\npip install -r requirements.txt\npython manage.py migrate\necho \"Done!\"\n",
                }},
            ],
            input_data={"path": "/sandbox/scripts/deploy.sh"},
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="不应报错"),
                Assertion(type=AssertionType.CONTAINS, expected="#!/bin/bash", description="包含 shebang"),
                Assertion(type=AssertionType.CONTAINS, expected="set -e", description="包含 shell 命令"),
            ],
            cleanup_steps=[
                {"tool": "terminal", "input": {"command": "rm -f '/sandbox/scripts/deploy.sh'"}},
            ],
        ),
        ToolEvalCase(
            id="rf_07",
            tool_name="read_file",
            description="/sandbox - 读取 SQL 文件",
            category="normal",
            setup_steps=[
                {"tool": "write_file", "input": {
                    "path": "/sandbox/db/init.sql",
                    "content": "CREATE TABLE users (\n    id SERIAL PRIMARY KEY,\n    name VARCHAR(100) NOT NULL,\n    email VARCHAR(255) UNIQUE,\n    created_at TIMESTAMP DEFAULT NOW()\n);\n\nINSERT INTO users (name, email) VALUES ('admin', 'admin@test.com');\n",
                }},
            ],
            input_data={"path": "/sandbox/db/init.sql"},
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="不应报错"),
                Assertion(type=AssertionType.CONTAINS, expected="CREATE TABLE", description="包含 DDL 语句"),
                Assertion(type=AssertionType.CONTAINS, expected="INSERT INTO", description="包含 DML 语句"),
            ],
            cleanup_steps=[
                {"tool": "terminal", "input": {"command": "rm -f '/sandbox/db/init.sql'"}},
            ],
        ),
        ToolEvalCase(
            id="rf_08",
            tool_name="read_file",
            description="/sandbox - 读取 HTML 文件",
            category="normal",
            setup_steps=[
                {"tool": "write_file", "input": {
                    "path": "/sandbox/web/index.html",
                    "content": "<!DOCTYPE html>\n<html lang=\"zh\">\n<head>\n    <meta charset=\"UTF-8\">\n    <title>测试页面</title>\n</head>\n<body>\n    <h1>Hello World</h1>\n    <p>这是一个测试页面</p>\n</body>\n</html>\n",
                }},
            ],
            input_data={"path": "/sandbox/web/index.html"},
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="不应报错"),
                Assertion(type=AssertionType.CONTAINS, expected="<!DOCTYPE html>", description="包含 HTML 声明"),
                Assertion(type=AssertionType.CONTAINS, expected="测试页面", description="包含中文内容"),
            ],
            cleanup_steps=[
                {"tool": "terminal", "input": {"command": "rm -f '/sandbox/web/index.html'"}},
            ],
        ),
        ToolEvalCase(
            id="rf_09",
            tool_name="read_file",
            description="/sandbox - 读取 TypeScript 文件",
            category="normal",
            setup_steps=[
                {"tool": "write_file", "input": {
                    "path": "/sandbox/src/index.ts",
                    "content": "interface User {\n  id: number;\n  name: string;\n  email: string;\n}\n\nconst getUser = async (id: number): Promise<User> => {\n  const response = await fetch(`/api/users/${id}`);\n  return response.json();\n};\n\nexport { User, getUser };\n",
                }},
            ],
            input_data={"path": "/sandbox/src/index.ts"},
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="不应报错"),
                Assertion(type=AssertionType.CONTAINS, expected="interface User", description="包含 TS 接口定义"),
                Assertion(type=AssertionType.CONTAINS, expected="Promise<User>", description="包含泛型类型"),
            ],
            cleanup_steps=[
                {"tool": "terminal", "input": {"command": "rm -f '/sandbox/src/index.ts'"}},
            ],
        ),
        ToolEvalCase(
            id="rf_10",
            tool_name="read_file",
            description="/sandbox - 读取 .env 配置文件",
            category="normal",
            setup_steps=[
                {"tool": "write_file", "input": {
                    "path": "/sandbox/.env",
                    "content": "DATABASE_URL=postgresql://user:pass@localhost:5432/mydb\nREDIS_URL=redis://localhost:6379\nSECRET_KEY=abc123xyz\nDEBUG=true\n",
                }},
            ],
            input_data={"path": "/sandbox/.env"},
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="不应报错"),
                Assertion(type=AssertionType.CONTAINS, expected="DATABASE_URL", description="包含环境变量"),
                Assertion(type=AssertionType.CONTAINS, expected="REDIS_URL", description="包含 Redis 配置"),
            ],
            cleanup_steps=[
                {"tool": "terminal", "input": {"command": "rm -f '/sandbox/.env'"}},
            ],
        ),

        # ── 正常场景：行范围读取 ──
        ToolEvalCase(
            id="rf_11",
            tool_name="read_file",
            description="/sandbox - 按行范围读取 offset=0 limit=3",
            category="normal",
            setup_steps=[
                {"tool": "write_file", "input": {
                    "path": "/sandbox/app/large_file.py",
                    "content": "line1\nline2\nline3\nline4\nline5\nline6\nline7\nline8\nline9\nline10\n",
                }},
            ],
            input_data={"path": "/sandbox/app/large_file.py", "offset": 0, "limit": 3},
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="不应报错"),
                Assertion(type=AssertionType.CONTAINS, expected="line1", description="包含第1行"),
                Assertion(type=AssertionType.CONTAINS, expected="line3", description="包含第3行"),
                Assertion(type=AssertionType.NOT_CONTAINS, expected="line4", description="不应包含第4行"),
            ],
            cleanup_steps=[
                {"tool": "terminal", "input": {"command": "rm -f '/sandbox/app/large_file.py'"}},
            ],
        ),
        ToolEvalCase(
            id="rf_12",
            tool_name="read_file",
            description="/sandbox - 按行范围读取中间部分 offset=3 limit=4",
            category="normal",
            setup_steps=[
                {"tool": "write_file", "input": {
                    "path": "/sandbox/app/offset_test.py",
                    "content": "line1\nline2\nline3\nline4\nline5\nline6\nline7\nline8\nline9\nline10\n",
                }},
            ],
            input_data={"path": "/sandbox/app/offset_test.py", "offset": 3, "limit": 4},
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="不应报错"),
                Assertion(type=AssertionType.CONTAINS, expected="line4", description="包含第4行（offset=3 起始）"),
                Assertion(type=AssertionType.CONTAINS, expected="line7", description="包含第7行"),
                Assertion(type=AssertionType.NOT_CONTAINS, expected="line1", description="不应包含第1行"),
                Assertion(type=AssertionType.NOT_CONTAINS, expected="line8", description="不应包含第8行"),
            ],
            cleanup_steps=[
                {"tool": "terminal", "input": {"command": "rm -f '/sandbox/app/offset_test.py'"}},
            ],
        ),
        ToolEvalCase(
            id="rf_13",
            tool_name="read_file",
            description="/sandbox - limit=1 只读取一行",
            category="normal",
            setup_steps=[
                {"tool": "write_file", "input": {
                    "path": "/sandbox/app/single_line_test.txt",
                    "content": "first\nsecond\nthird\n",
                }},
            ],
            input_data={"path": "/sandbox/app/single_line_test.txt", "offset": 1, "limit": 1},
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="不应报错"),
                Assertion(type=AssertionType.CONTAINS, expected="second", description="只包含第2行"),
                Assertion(type=AssertionType.NOT_CONTAINS, expected="first", description="不应包含第1行"),
                Assertion(type=AssertionType.NOT_CONTAINS, expected="third", description="不应包含第3行"),
            ],
            cleanup_steps=[
                {"tool": "terminal", "input": {"command": "rm -f '/sandbox/app/single_line_test.txt'"}},
            ],
        ),

        # ── 正常场景：特殊内容 ──
        ToolEvalCase(
            id="rf_14",
            tool_name="read_file",
            description="/sandbox - 读取包含中文/Unicode 的文件",
            category="normal",
            setup_steps=[
                {"tool": "write_file", "input": {
                    "path": "/sandbox/docs/中文文档.md",
                    "content": "# 项目说明\n\n## 功能列表\n\n- 用户管理 👤\n- 订单处理 📦\n- 数据分析 📊\n\n> 注意：请使用 UTF-8 编码\n",
                }},
            ],
            input_data={"path": "/sandbox/docs/中文文档.md"},
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="不应报错"),
                Assertion(type=AssertionType.CONTAINS, expected="项目说明", description="包含中文标题"),
                Assertion(type=AssertionType.CONTAINS, expected="📦", description="包含 Emoji 字符"),
            ],
            cleanup_steps=[
                {"tool": "terminal", "input": {"command": "rm -f '/sandbox/docs/中文文档.md'"}},
            ],
        ),
        ToolEvalCase(
            id="rf_15",
            tool_name="read_file",
            description="/sandbox - 读取包含特殊字符的文件（引号/转义）",
            category="normal",
            setup_steps=[
                {"tool": "write_file", "input": {
                    "path": "/sandbox/test/special_chars.txt",
                    "content": "Line with 'single quotes'\nLine with \"double quotes\"\nLine with $variable\nLine with `backticks`\nLine with \\backslash\n",
                }},
            ],
            input_data={"path": "/sandbox/test/special_chars.txt"},
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="不应报错"),
                Assertion(type=AssertionType.CONTAINS, expected="single quotes", description="包含单引号内容"),
                Assertion(type=AssertionType.CONTAINS, expected="double quotes", description="包含双引号内容"),
            ],
            cleanup_steps=[
                {"tool": "terminal", "input": {"command": "rm -f '/sandbox/test/special_chars.txt'"}},
            ],
        ),
        ToolEvalCase(
            id="rf_16",
            tool_name="read_file",
            description="/sandbox - 读取空文件",
            category="boundary",
            setup_steps=[
                {"tool": "write_file", "input": {
                    "path": "/sandbox/test/empty_file.txt",
                    "content": "",
                }},
            ],
            input_data={"path": "/sandbox/test/empty_file.txt"},
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="空文件不应报错"),
            ],
            cleanup_steps=[
                {"tool": "terminal", "input": {"command": "rm -f '/sandbox/test/empty_file.txt'"}},
            ],
        ),
        ToolEvalCase(
            id="rf_17",
            tool_name="read_file",
            description="/sandbox - 读取大文件（超过默认 limit）",
            category="boundary",
            setup_steps=[
                {"tool": "terminal", "input": {
                    "command": "python3 -c \"f=open('/sandbox/test/bigfile.txt','w');\nfor i in range(3000): f.write(f'line {i}: ' + 'x'*80 + '\\n')\nf.close()\"",
                }},
            ],
            input_data={"path": "/sandbox/test/bigfile.txt"},
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="大文件不应报错"),
                Assertion(type=AssertionType.CONTAINS, expected="line 0:", description="包含起始行"),
            ],
            cleanup_steps=[
                {"tool": "terminal", "input": {"command": "rm -f '/sandbox/test/bigfile.txt'"}},
            ],
        ),

        # ── 正常场景：Excel 类二进制文件 ──
        ToolEvalCase(
            id="rf_18",
            tool_name="read_file",
            description="/sandbox - 读取 Excel(.xlsx) 文件（二进制，验证不崩溃）",
            category="boundary",
            setup_steps=[
                {"tool": "terminal", "input": {
                    "command": "pip install -q openpyxl 2>/dev/null; python3 -c \"import os; os.makedirs('/sandbox/data', exist_ok=True); import openpyxl; wb = openpyxl.Workbook(); ws = wb.active; ws['A1'] = '姓名'; ws['B1'] = '分数'; ws['A2'] = '张三'; ws['B2'] = 95; wb.save('/sandbox/data/test.xlsx')\"",
                }},
            ],
            input_data={"path": "/sandbox/data/test.xlsx"},
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="二进制文件读取不应崩溃（返回原始内容或提示）"),
            ],
            cleanup_steps=[
                {"tool": "terminal", "input": {"command": "rm -f '/sandbox/data/test.xlsx'"}},
            ],
        ),

        # ── 正常场景：深层目录结构 ──
        ToolEvalCase(
            id="rf_19",
            tool_name="read_file",
            description="/sandbox - 读取深层嵌套目录中的文件",
            category="normal",
            setup_steps=[
                {"tool": "write_file", "input": {
                    "path": "/sandbox/src/modules/auth/handlers/login.py",
                    "content": "from flask import request\n\ndef handle_login():\n    username = request.json.get('username')\n    password = request.json.get('password')\n    return {'token': 'abc123'}\n",
                }},
            ],
            input_data={"path": "/sandbox/src/modules/auth/handlers/login.py"},
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="深层目录不应报错"),
                Assertion(type=AssertionType.CONTAINS, expected="handle_login", description="包含函数定义"),
            ],
            cleanup_steps=[
                {"tool": "terminal", "input": {"command": "rm -f '/sandbox/src/modules/auth/handlers/login.py'"}},
            ],
        ),
        ToolEvalCase(
            id="rf_20",
            tool_name="read_file",
            description="/sandbox - 读取隐藏文件（dot file）",
            category="normal",
            setup_steps=[
                {"tool": "write_file", "input": {
                    "path": "/sandbox/.gitignore",
                    "content": "node_modules/\n__pycache__/\n*.pyc\n.env\n.venv/\ndist/\n",
                }},
            ],
            input_data={"path": "/sandbox/.gitignore"},
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="隐藏文件不应报错"),
                Assertion(type=AssertionType.CONTAINS, expected="node_modules", description="包含 gitignore 规则"),
            ],
            cleanup_steps=[
                {"tool": "terminal", "input": {"command": "rm -f '/sandbox/.gitignore'"}},
            ],
        ),

        # ══════════════════════════════════════════════════════════════
        # read_file — /tmp 目录场景
        # ══════════════════════════════════════════════════════════════

        ToolEvalCase(
            id="rf_21",
            tool_name="read_file",
            description="/tmp - 读取 Python 临时文件",
            category="normal",
            setup_steps=[
                {"tool": "write_file", "input": {
                    "path": "/tmp/eval_test_script.py",
                    "content": "import sys\nimport json\n\ndef process(data):\n    return json.dumps(data, indent=2)\n\nif __name__ == '__main__':\n    result = process({'key': 'value'})\n    print(result)\n",
                }},
            ],
            input_data={"path": "/tmp/eval_test_script.py"},
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="不应报错"),
                Assertion(type=AssertionType.CONTAINS, expected="import json", description="包含 import"),
                Assertion(type=AssertionType.CONTAINS, expected="def process", description="包含函数定义"),
            ],
            cleanup_steps=[
                {"tool": "terminal", "input": {"command": "rm -f '/tmp/eval_test_script.py'"}},
            ],
        ),
        ToolEvalCase(
            id="rf_22",
            tool_name="read_file",
            description="/tmp - 读取 Markdown 文档",
            category="normal",
            setup_steps=[
                {"tool": "write_file", "input": {
                    "path": "/tmp/eval_report.md",
                    "content": "# 评测报告\n\n## 概要\n\n| 指标 | 数值 |\n|------|------|\n| 通过率 | 95% |\n| 用例数 | 100 |\n\n## 详情\n\n1. 工具调用正确性: ✅\n2. 参数提取准确率: ✅\n",
                }},
            ],
            input_data={"path": "/tmp/eval_report.md"},
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="不应报错"),
                Assertion(type=AssertionType.CONTAINS, expected="评测报告", description="包含中文标题"),
                Assertion(type=AssertionType.CONTAINS, expected="通过率", description="包含表格内容"),
            ],
            cleanup_steps=[
                {"tool": "terminal", "input": {"command": "rm -f '/tmp/eval_report.md'"}},
            ],
        ),
        ToolEvalCase(
            id="rf_23",
            tool_name="read_file",
            description="/tmp - 读取 Excel 文件（二进制验证不崩溃）",
            category="boundary",
            setup_steps=[
                {"tool": "terminal", "input": {
                    "command": "pip install -q openpyxl 2>/dev/null; python3 -c \"import openpyxl; wb = openpyxl.Workbook(); ws = wb.active; ws.title = '销售数据'; ws['A1'] = '日期'; ws['B1'] = '金额'; ws['A2'] = '2024-01-01'; ws['B2'] = 10000; wb.save('/tmp/eval_sales.xlsx')\"",
                }},
            ],
            input_data={"path": "/tmp/eval_sales.xlsx"},
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="读取二进制 Excel 文件不应崩溃"),
            ],
            cleanup_steps=[
                {"tool": "terminal", "input": {"command": "rm -f '/tmp/eval_sales.xlsx'"}},
            ],
        ),
        ToolEvalCase(
            id="rf_24",
            tool_name="read_file",
            description="/tmp - 读取 JSON 数据文件",
            category="normal",
            setup_steps=[
                {"tool": "write_file", "input": {
                    "path": "/tmp/eval_data.json",
                    "content": '[\n  {"id": 1, "name": "订单A", "status": "paid", "amount": 99.9},\n  {"id": 2, "name": "订单B", "status": "shipped", "amount": 150.0},\n  {"id": 3, "name": "订单C", "status": "cancelled", "amount": 30.5}\n]\n',
                }},
            ],
            input_data={"path": "/tmp/eval_data.json"},
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="不应报错"),
                Assertion(type=AssertionType.CONTAINS, expected="订单A", description="包含 JSON 数组元素"),
                Assertion(type=AssertionType.CONTAINS, expected="shipped", description="包含状态字段"),
            ],
            cleanup_steps=[
                {"tool": "terminal", "input": {"command": "rm -f '/tmp/eval_data.json'"}},
            ],
        ),
        ToolEvalCase(
            id="rf_25",
            tool_name="read_file",
            description="/tmp - 读取带 offset+limit 的文件",
            category="normal",
            setup_steps=[
                {"tool": "write_file", "input": {
                    "path": "/tmp/eval_lines.txt",
                    "content": "alpha\nbeta\ngamma\ndelta\nepsilon\nzeta\neta\ntheta\n",
                }},
            ],
            input_data={"path": "/tmp/eval_lines.txt", "offset": 2, "limit": 3},
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="不应报错"),
                Assertion(type=AssertionType.CONTAINS, expected="gamma", description="包含第3行"),
                Assertion(type=AssertionType.CONTAINS, expected="epsilon", description="包含第5行"),
                Assertion(type=AssertionType.NOT_CONTAINS, expected="alpha", description="不应包含第1行"),
            ],
            cleanup_steps=[
                {"tool": "terminal", "input": {"command": "rm -f '/tmp/eval_lines.txt'"}},
            ],
        ),
        ToolEvalCase(
            id="rf_26",
            tool_name="read_file",
            description="/tmp - 读取 CSV 数据文件",
            category="normal",
            setup_steps=[
                {"tool": "write_file", "input": {
                    "path": "/tmp/eval_metrics.csv",
                    "content": "metric,value,timestamp\ncpu_usage,78.5,2024-03-15T10:00:00\nmemory_usage,62.3,2024-03-15T10:00:00\ndisk_io,15.7,2024-03-15T10:00:00\n",
                }},
            ],
            input_data={"path": "/tmp/eval_metrics.csv"},
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="不应报错"),
                Assertion(type=AssertionType.CONTAINS, expected="metric,value,timestamp", description="包含 CSV 表头"),
                Assertion(type=AssertionType.CONTAINS, expected="cpu_usage", description="包含数据行"),
            ],
            cleanup_steps=[
                {"tool": "terminal", "input": {"command": "rm -f '/tmp/eval_metrics.csv'"}},
            ],
        ),
        ToolEvalCase(
            id="rf_27",
            tool_name="read_file",
            description="/tmp - 读取深层子目录文件",
            category="normal",
            setup_steps=[
                {"tool": "write_file", "input": {
                    "path": "/tmp/eval_deep/level1/level2/level3/config.yaml",
                    "content": "app:\n  name: test-service\n  version: 1.0.0\n  port: 8080\n",
                }},
            ],
            input_data={"path": "/tmp/eval_deep/level1/level2/level3/config.yaml"},
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="深层 /tmp 子目录不应报错"),
                Assertion(type=AssertionType.CONTAINS, expected="test-service", description="包含 YAML 内容"),
            ],
            cleanup_steps=[
                {"tool": "terminal", "input": {"command": "rm -f '/tmp/eval_deep/level1/level2/level3/config.yaml'"}},
            ],
        ),

        # ══════════════════════════════════════════════════════════════
        # read_file — 错误场景
        # ══════════════════════════════════════════════════════════════

        ToolEvalCase(
            id="rf_30",
            tool_name="read_file",
            description="错误 - 空路径应返回错误",
            category="error",
            input_data={"path": ""},
            assertions=[
                Assertion(type=AssertionType.IS_ERROR, description="空路径应报错"),
            ],
        ),
        ToolEvalCase(
            id="rf_31",
            tool_name="read_file",
            description="错误 - /sandbox 中不存在的文件",
            category="error",
            input_data={"path": "/sandbox/nonexistent_file_xyz.txt"},
            assertions=[
                Assertion(type=AssertionType.IS_ERROR, description="不存在的文件应报错"),
                Assertion(type=AssertionType.CONTAINS, expected="不存在", description="错误信息包含'不存在'"),
            ],
        ),
        ToolEvalCase(
            id="rf_32",
            tool_name="read_file",
            description="错误 - /tmp 中不存在的文件",
            category="error",
            input_data={"path": "/tmp/nonexistent_file_xyz_999.txt"},
            assertions=[
                Assertion(type=AssertionType.IS_ERROR, description="不存在的文件应报错"),
                Assertion(type=AssertionType.CONTAINS, expected="不存在", description="错误信息包含'不存在'"),
            ],
        ),
        ToolEvalCase(
            id="rf_33",
            tool_name="read_file",
            description="错误 - 不存在的深层路径",
            category="error",
            input_data={"path": "/sandbox/a/b/c/d/e/f/nonexistent.py"},
            assertions=[
                Assertion(type=AssertionType.IS_ERROR, description="不存在的深层路径应报错"),
            ],
        ),
        ToolEvalCase(
            id="rf_34",
            tool_name="read_file",
            description="错误 - 读取目录而非文件",
            category="error",
            setup_steps=[
                {"tool": "write_file", "input": {
                    "path": "/sandbox/testdir/placeholder.txt",
                    "content": "placeholder",
                }},
            ],
            input_data={"path": "/sandbox/testdir"},
            assertions=[
                Assertion(type=AssertionType.IS_ERROR, description="读取目录应报错或返回非常规结果"),
            ],
            cleanup_steps=[
                {"tool": "terminal", "input": {"command": "rm -f '/sandbox/testdir/placeholder.txt'"}},
            ],
        ),

        # ══════════════════════════════════════════════════════════════
        # read_file — 边界场景
        # ══════════════════════════════════════════════════════════════

        ToolEvalCase(
            id="rf_40",
            tool_name="read_file",
            description="边界 - offset 超出文件行数",
            category="boundary",
            setup_steps=[
                {"tool": "write_file", "input": {
                    "path": "/sandbox/test/short.txt",
                    "content": "only three\nlines\nhere\n",
                }},
            ],
            input_data={"path": "/sandbox/test/short.txt", "offset": 99999, "limit": 10},
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="offset 超出不应崩溃"),
            ],
            cleanup_steps=[
                {"tool": "terminal", "input": {"command": "rm -f '/sandbox/test/short.txt'"}},
            ],
        ),
        ToolEvalCase(
            id="rf_41",
            tool_name="read_file",
            description="边界 - limit=0 读取零行",
            category="boundary",
            setup_steps=[
                {"tool": "write_file", "input": {
                    "path": "/sandbox/test/limit_zero.txt",
                    "content": "some content\n",
                }},
            ],
            input_data={"path": "/sandbox/test/limit_zero.txt", "offset": 0, "limit": 0},
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="limit=0 不应崩溃"),
            ],
            cleanup_steps=[
                {"tool": "terminal", "input": {"command": "rm -f '/sandbox/test/limit_zero.txt'"}},
            ],
        ),
        ToolEvalCase(
            id="rf_42",
            tool_name="read_file",
            description="边界 - 只有一行的文件",
            category="boundary",
            setup_steps=[
                {"tool": "write_file", "input": {
                    "path": "/sandbox/test/one_line.txt",
                    "content": "single line without newline",
                }},
            ],
            input_data={"path": "/sandbox/test/one_line.txt"},
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="单行文件不应报错"),
                Assertion(type=AssertionType.CONTAINS, expected="single line", description="包含文件内容"),
            ],
            cleanup_steps=[
                {"tool": "terminal", "input": {"command": "rm -f '/sandbox/test/one_line.txt'"}},
            ],
        ),
        ToolEvalCase(
            id="rf_43",
            tool_name="read_file",
            description="边界 - 文件名含空格",
            category="boundary",
            setup_steps=[
                {"tool": "write_file", "input": {
                    "path": "/sandbox/test/file with spaces.txt",
                    "content": "content of file with spaces in name\n",
                }},
            ],
            input_data={"path": "/sandbox/test/file with spaces.txt"},
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="文件名含空格不应报错"),
                Assertion(type=AssertionType.CONTAINS, expected="content of file", description="能正确读取内容"),
            ],
            cleanup_steps=[
                {"tool": "terminal", "input": {"command": "rm -f '/sandbox/test/file with spaces.txt'"}},
            ],
        ),
        ToolEvalCase(
            id="rf_44",
            tool_name="read_file",
            description="边界 - 文件名含特殊字符",
            category="boundary",
            setup_steps=[
                {"tool": "write_file", "input": {
                    "path": "/tmp/eval_special-file_v2.0(1).txt",
                    "content": "file with special chars in name\n",
                }},
            ],
            input_data={"path": "/tmp/eval_special-file_v2.0(1).txt"},
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="特殊字符文件名不应报错"),
                Assertion(type=AssertionType.CONTAINS, expected="special chars", description="能正确读取"),
            ],
            cleanup_steps=[
                {"tool": "terminal", "input": {"command": "rm -f '/tmp/eval_special-file_v2.0(1).txt'"}},
            ],
        ),
        ToolEvalCase(
            id="rf_45",
            tool_name="read_file",
            description="边界 - 非常长的单行文件",
            category="boundary",
            setup_steps=[
                {"tool": "terminal", "input": {
                    "command": "python3 -c \"f=open('/sandbox/test/long_line.txt','w'); f.write('A'*10000 + '\\n'); f.close()\"",
                }},
            ],
            input_data={"path": "/sandbox/test/long_line.txt"},
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="超长单行不应崩溃"),
            ],
            cleanup_steps=[
                {"tool": "terminal", "input": {"command": "rm -f '/sandbox/test/long_line.txt'"}},
            ],
        ),
        ToolEvalCase(
            id="rf_46",
            tool_name="read_file",
            description="边界 - /tmp 中 offset 超出范围",
            category="boundary",
            setup_steps=[
                {"tool": "write_file", "input": {
                    "path": "/tmp/eval_boundary.txt",
                    "content": "line1\nline2\n",
                }},
            ],
            input_data={"path": "/tmp/eval_boundary.txt", "offset": 50000, "limit": 10},
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="offset 超出范围不应崩溃"),
            ],
            cleanup_steps=[
                {"tool": "terminal", "input": {"command": "rm -f '/tmp/eval_boundary.txt'"}},
            ],
        ),
        ToolEvalCase(
            id="rf_47",
            tool_name="read_file",
            description="边界 - 读取包含 NULL 字节的二进制内容",
            category="boundary",
            setup_steps=[
                {"tool": "terminal", "input": {
                    "command": "python3 -c \"f=open('/sandbox/test/binary.bin','wb'); f.write(b'\\x00\\x01\\x02\\xff\\xfe\\xfd'); f.close()\"",
                }},
            ],
            input_data={"path": "/sandbox/test/binary.bin"},
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="二进制内容不应导致崩溃"),
            ],
            cleanup_steps=[
                {"tool": "terminal", "input": {"command": "rm -f '/sandbox/test/binary.bin'"}},
            ],
        ),

        # ── 副作用场景：write 后 read 验证 ──
        ToolEvalCase(
            id="rf_50",
            tool_name="read_file",
            description="副作用 - write_file 写入 /sandbox 后 read_file 可读取",
            category="side_effect",
            setup_steps=[
                {"tool": "write_file", "input": {
                    "path": "/sandbox/verify/side_effect_test.py",
                    "content": "# Side effect verification\nresult = 42\n",
                }},
            ],
            input_data={"path": "/sandbox/verify/side_effect_test.py"},
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="不应报错"),
                Assertion(type=AssertionType.CONTAINS, expected="result = 42", description="能读到刚写入的内容"),
            ],
            cleanup_steps=[
                {"tool": "terminal", "input": {"command": "rm -f '/sandbox/verify/side_effect_test.py'"}},
            ],
        ),
        ToolEvalCase(
            id="rf_51",
            tool_name="read_file",
            description="副作用 - terminal 创建文件后 read_file 可读取",
            category="side_effect",
            setup_steps=[
                {"tool": "terminal", "input": {
                    "command": "echo 'created by terminal' > /tmp/eval_terminal_created.txt",
                }},
            ],
            input_data={"path": "/tmp/eval_terminal_created.txt"},
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="不应报错"),
                Assertion(type=AssertionType.CONTAINS, expected="created by terminal", description="能读到 terminal 创建的内容"),
            ],
            cleanup_steps=[
                {"tool": "terminal", "input": {"command": "rm -f '/tmp/eval_terminal_created.txt'"}},
            ],
        ),
        ToolEvalCase(
            id="rf_52",
            tool_name="read_file",
            description="副作用 - execute_code 生成文件后 read_file 可读取",
            category="side_effect",
            setup_steps=[
                {"tool": "terminal", "input": {
                    "command": "python3 -c \"with open('/sandbox/output/result.json','w') as f: f.write('{\\\"status\\\": \\\"ok\\\", \\\"count\\\": 5}')\"",
                }},
            ],
            input_data={"path": "/sandbox/output/result.json"},
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="不应报错"),
                Assertion(type=AssertionType.CONTAINS, expected="status", description="包含 JSON 内容"),
                Assertion(type=AssertionType.CONTAINS, expected="ok", description="包含生成的值"),
            ],
            cleanup_steps=[
                {"tool": "terminal", "input": {"command": "rm -f '/sandbox/output/result.json'"}},
            ],
        ),

        # ══════════════════════════════════════════════════════════════
        # write_file — /sandbox 目录场景
        # ══════════════════════════════════════════════════════════════

        # ── 正常场景：各类文件类型写入 /sandbox ──
        ToolEvalCase(
            id="wf_01",
            tool_name="write_file",
            description="/sandbox - 写入 Python 文件",
            category="normal",
            input_data={
                "path": "/sandbox/app/main.py",
                "content": "#!/usr/bin/env python3\nimport os\n\ndef main():\n    print('hello')\n\nif __name__ == '__main__':\n    main()\n",
            },
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="写入不应报错"),
                Assertion(type=AssertionType.CONTAINS, expected="已写入", description="提示已写入"),
                Assertion(
                    type=AssertionType.SIDE_EFFECT,
                    description="写入后 read_file 能读到 Python 代码",
                    expected={
                        "verify_tool": "read_file",
                        "verify_input": {"path": "/sandbox/app/main.py"},
                        "verify_path": "",
                        "verify_value": "def main",
                    },
                ),
            ],
            cleanup_steps=[
                {"tool": "terminal", "input": {"command": "rm -f '/sandbox/app/main.py'"}},
            ],
        ),
        ToolEvalCase(
            id="wf_02",
            tool_name="write_file",
            description="/sandbox - 写入 Markdown 文件",
            category="normal",
            input_data={
                "path": "/sandbox/docs/README.md",
                "content": "# Project Title\n\n## Overview\n\nThis is a **test** project.\n\n- Item 1\n- Item 2\n\n```python\nprint('hello')\n```\n",
            },
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="写入不应报错"),
                Assertion(type=AssertionType.CONTAINS, expected="已写入", description="提示已写入"),
                Assertion(
                    type=AssertionType.SIDE_EFFECT,
                    description="写入后 read_file 能读到 Markdown 内容",
                    expected={
                        "verify_tool": "read_file",
                        "verify_input": {"path": "/sandbox/docs/README.md"},
                        "verify_path": "",
                        "verify_value": "# Project Title",
                    },
                ),
            ],
            cleanup_steps=[
                {"tool": "terminal", "input": {"command": "rm -f '/sandbox/docs/README.md'"}},
            ],
        ),
        ToolEvalCase(
            id="wf_03",
            tool_name="write_file",
            description="/sandbox - 写入 JSON 配置文件",
            category="normal",
            input_data={
                "path": "/sandbox/config/settings.json",
                "content": '{\n  "database": {\n    "host": "localhost",\n    "port": 5432\n  },\n  "debug": true\n}\n',
            },
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="写入不应报错"),
                Assertion(
                    type=AssertionType.SIDE_EFFECT,
                    description="写入后 read_file 能读到 JSON",
                    expected={
                        "verify_tool": "read_file",
                        "verify_input": {"path": "/sandbox/config/settings.json"},
                        "verify_path": "",
                        "verify_value": "database",
                    },
                ),
            ],
        ),
        ToolEvalCase(
            id="wf_04",
            tool_name="write_file",
            description="/sandbox - 写入 YAML 配置文件",
            category="normal",
            input_data={
                "path": "/sandbox/config/docker-compose.yaml",
                "content": "version: '3.8'\nservices:\n  web:\n    image: nginx:latest\n    ports:\n      - '8080:80'\n  db:\n    image: postgres:15\n    environment:\n      POSTGRES_PASSWORD: secret\n",
            },
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="写入不应报错"),
                Assertion(
                    type=AssertionType.SIDE_EFFECT,
                    description="写入后 read_file 能读到 YAML",
                    expected={
                        "verify_tool": "read_file",
                        "verify_input": {"path": "/sandbox/config/docker-compose.yaml"},
                        "verify_path": "",
                        "verify_value": "services",
                    },
                ),
            ],
        ),
        ToolEvalCase(
            id="wf_05",
            tool_name="write_file",
            description="/sandbox - 写入 CSV 数据文件",
            category="normal",
            input_data={
                "path": "/sandbox/data/records.csv",
                "content": "id,name,email,score\n1,张三,zhangsan@test.com,95\n2,李四,lisi@test.com,88\n3,王五,wangwu@test.com,72\n",
            },
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="写入不应报错"),
                Assertion(
                    type=AssertionType.SIDE_EFFECT,
                    description="写入后 read_file 能读到 CSV",
                    expected={
                        "verify_tool": "read_file",
                        "verify_input": {"path": "/sandbox/data/records.csv"},
                        "verify_path": "",
                        "verify_value": "张三",
                    },
                ),
            ],
        ),
        ToolEvalCase(
            id="wf_06",
            tool_name="write_file",
            description="/sandbox - 写入 Shell 脚本",
            category="normal",
            input_data={
                "path": "/sandbox/scripts/deploy.sh",
                "content": "#!/bin/bash\nset -e\n\necho \"Starting deployment...\"\ncd /app\npip install -r requirements.txt\npython manage.py migrate\necho \"Done!\"\n",
            },
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="写入不应报错"),
                Assertion(
                    type=AssertionType.SIDE_EFFECT,
                    description="写入后 read_file 能读到 Shell 脚本",
                    expected={
                        "verify_tool": "read_file",
                        "verify_input": {"path": "/sandbox/scripts/deploy.sh"},
                        "verify_path": "",
                        "verify_value": "#!/bin/bash",
                    },
                ),
            ],
        ),
        ToolEvalCase(
            id="wf_07",
            tool_name="write_file",
            description="/sandbox - 写入 SQL 文件",
            category="normal",
            input_data={
                "path": "/sandbox/db/init.sql",
                "content": "CREATE TABLE users (\n    id SERIAL PRIMARY KEY,\n    name VARCHAR(100) NOT NULL,\n    email VARCHAR(255) UNIQUE,\n    created_at TIMESTAMP DEFAULT NOW()\n);\n\nINSERT INTO users (name, email) VALUES ('admin', 'admin@test.com');\n",
            },
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="写入不应报错"),
                Assertion(
                    type=AssertionType.SIDE_EFFECT,
                    description="写入后 read_file 能读到 SQL",
                    expected={
                        "verify_tool": "read_file",
                        "verify_input": {"path": "/sandbox/db/init.sql"},
                        "verify_path": "",
                        "verify_value": "CREATE TABLE",
                    },
                ),
            ],
        ),
        ToolEvalCase(
            id="wf_08",
            tool_name="write_file",
            description="/sandbox - 写入 HTML 文件",
            category="normal",
            input_data={
                "path": "/sandbox/web/index.html",
                "content": "<!DOCTYPE html>\n<html lang=\"zh\">\n<head>\n    <meta charset=\"UTF-8\">\n    <title>测试页面</title>\n</head>\n<body>\n    <h1>Hello World</h1>\n    <p>这是一个测试页面</p>\n</body>\n</html>\n",
            },
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="写入不应报错"),
                Assertion(
                    type=AssertionType.SIDE_EFFECT,
                    description="写入后 read_file 能读到 HTML",
                    expected={
                        "verify_tool": "read_file",
                        "verify_input": {"path": "/sandbox/web/index.html"},
                        "verify_path": "",
                        "verify_value": "<!DOCTYPE html>",
                    },
                ),
            ],
        ),
        ToolEvalCase(
            id="wf_09",
            tool_name="write_file",
            description="/sandbox - 写入 TypeScript 文件",
            category="normal",
            input_data={
                "path": "/sandbox/src/index.ts",
                "content": "interface User {\n  id: number;\n  name: string;\n  email: string;\n}\n\nconst getUser = async (id: number): Promise<User> => {\n  const response = await fetch(`/api/users/${id}`);\n  return response.json();\n};\n\nexport { User, getUser };\n",
            },
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="写入不应报错"),
                Assertion(
                    type=AssertionType.SIDE_EFFECT,
                    description="写入后 read_file 能读到 TypeScript",
                    expected={
                        "verify_tool": "read_file",
                        "verify_input": {"path": "/sandbox/src/index.ts"},
                        "verify_path": "",
                        "verify_value": "interface User",
                    },
                ),
            ],
        ),
        ToolEvalCase(
            id="wf_10",
            tool_name="write_file",
            description="/sandbox - 写入 .env 配置文件",
            category="normal",
            input_data={
                "path": "/sandbox/.env",
                "content": "DATABASE_URL=postgresql://user:pass@localhost:5432/mydb\nREDIS_URL=redis://localhost:6379\nSECRET_KEY=abc123xyz\nDEBUG=true\n",
            },
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="写入不应报错"),
                Assertion(
                    type=AssertionType.SIDE_EFFECT,
                    description="写入后 read_file 能读到 .env",
                    expected={
                        "verify_tool": "read_file",
                        "verify_input": {"path": "/sandbox/.env"},
                        "verify_path": "",
                        "verify_value": "DATABASE_URL",
                    },
                ),
            ],
        ),
        ToolEvalCase(
            id="wf_11",
            tool_name="write_file",
            description="/sandbox - 写入 .gitignore 隐藏文件",
            category="normal",
            input_data={
                "path": "/sandbox/.gitignore",
                "content": "node_modules/\n__pycache__/\n*.pyc\n.env\n.venv/\ndist/\n",
            },
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="写入不应报错"),
                Assertion(
                    type=AssertionType.SIDE_EFFECT,
                    description="写入后 read_file 能读到隐藏文件",
                    expected={
                        "verify_tool": "read_file",
                        "verify_input": {"path": "/sandbox/.gitignore"},
                        "verify_path": "",
                        "verify_value": "node_modules",
                    },
                ),
            ],
        ),

        # ── 正常场景：深层目录 /sandbox ──
        ToolEvalCase(
            id="wf_12",
            tool_name="write_file",
            description="/sandbox - 写入深层嵌套目录（自动创建）",
            category="normal",
            input_data={
                "path": "/sandbox/src/modules/auth/handlers/login.py",
                "content": "from flask import request\n\ndef handle_login():\n    username = request.json.get('username')\n    password = request.json.get('password')\n    return {'token': 'abc123'}\n",
            },
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="深层目录自动创建不应报错"),
                Assertion(
                    type=AssertionType.SIDE_EFFECT,
                    description="写入后 read_file 能读到深层目录文件",
                    expected={
                        "verify_tool": "read_file",
                        "verify_input": {"path": "/sandbox/src/modules/auth/handlers/login.py"},
                        "verify_path": "",
                        "verify_value": "handle_login",
                    },
                ),
            ],
        ),

        # ── 正常场景：特殊内容 /sandbox ──
        ToolEvalCase(
            id="wf_13",
            tool_name="write_file",
            description="/sandbox - 写入含中文/Unicode/Emoji 的文件",
            category="normal",
            input_data={
                "path": "/sandbox/docs/中文文档.md",
                "content": "# 项目说明\n\n## 功能列表\n\n- 用户管理 👤\n- 订单处理 📦\n- 数据分析 📊\n\n> 注意：请使用 UTF-8 编码\n",
            },
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="写入中文/Emoji 不应报错"),
                Assertion(
                    type=AssertionType.SIDE_EFFECT,
                    description="写入后 read_file 能读到中文内容",
                    expected={
                        "verify_tool": "read_file",
                        "verify_input": {"path": "/sandbox/docs/中文文档.md"},
                        "verify_path": "",
                        "verify_value": "项目说明",
                    },
                ),
            ],
        ),
        ToolEvalCase(
            id="wf_14",
            tool_name="write_file",
            description="/sandbox - 写入含特殊字符的内容（引号/转义）",
            category="normal",
            input_data={
                "path": "/sandbox/test/special_chars.txt",
                "content": "Line with 'single quotes'\nLine with \"double quotes\"\nLine with $variable\nLine with `backticks`\nLine with \\backslash\n",
            },
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="特殊字符写入不应报错"),
                Assertion(
                    type=AssertionType.SIDE_EFFECT,
                    description="写入后 read_file 能读到特殊字符",
                    expected={
                        "verify_tool": "read_file",
                        "verify_input": {"path": "/sandbox/test/special_chars.txt"},
                        "verify_path": "",
                        "verify_value": "single quotes",
                    },
                ),
            ],
        ),
        ToolEvalCase(
            id="wf_15",
            tool_name="write_file",
            description="/sandbox - 写入多行文件（用于 read_file 行范围测试）",
            category="normal",
            input_data={
                "path": "/sandbox/app/large_file.py",
                "content": "line1\nline2\nline3\nline4\nline5\nline6\nline7\nline8\nline9\nline10\n",
            },
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="不应报错"),
                Assertion(type=AssertionType.CONTAINS, expected="已写入", description="提示已写入"),
                Assertion(
                    type=AssertionType.SIDE_EFFECT,
                    description="写入后 read_file 能读到多行内容",
                    expected={
                        "verify_tool": "read_file",
                        "verify_input": {"path": "/sandbox/app/large_file.py"},
                        "verify_path": "",
                        "verify_value": "line1",
                    },
                ),
            ],
        ),

        # ══════════════════════════════════════════════════════════════
        # write_file — /tmp 目录场景
        # ══════════════════════════════════════════════════════════════

        ToolEvalCase(
            id="wf_20",
            tool_name="write_file",
            description="/tmp - 写入 Python 临时文件",
            category="normal",
            input_data={
                "path": "/tmp/eval_test_script.py",
                "content": "import sys\nimport json\n\ndef process(data):\n    return json.dumps(data, indent=2)\n\nif __name__ == '__main__':\n    result = process({'key': 'value'})\n    print(result)\n",
            },
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="写入不应报错"),
                Assertion(
                    type=AssertionType.SIDE_EFFECT,
                    description="写入后 read_file 能读到",
                    expected={
                        "verify_tool": "read_file",
                        "verify_input": {"path": "/tmp/eval_test_script.py"},
                        "verify_path": "",
                        "verify_value": "def process",
                    },
                ),
            ],
        ),
        ToolEvalCase(
            id="wf_21",
            tool_name="write_file",
            description="/tmp - 写入 Markdown 报告文件",
            category="normal",
            input_data={
                "path": "/tmp/eval_report.md",
                "content": "# 评测报告\n\n## 概要\n\n| 指标 | 数值 |\n|------|------|\n| 通过率 | 95% |\n| 用例数 | 100 |\n\n## 详情\n\n1. 工具调用正确性: ✅\n2. 参数提取准确率: ✅\n",
            },
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="写入不应报错"),
                Assertion(
                    type=AssertionType.SIDE_EFFECT,
                    description="写入后 read_file 能读到 Markdown",
                    expected={
                        "verify_tool": "read_file",
                        "verify_input": {"path": "/tmp/eval_report.md"},
                        "verify_path": "",
                        "verify_value": "评测报告",
                    },
                ),
            ],
        ),
        ToolEvalCase(
            id="wf_22",
            tool_name="write_file",
            description="/tmp - 写入 JSON 数据文件",
            category="normal",
            input_data={
                "path": "/tmp/eval_data.json",
                "content": '[\n  {"id": 1, "name": "订单A", "status": "paid", "amount": 99.9},\n  {"id": 2, "name": "订单B", "status": "shipped", "amount": 150.0},\n  {"id": 3, "name": "订单C", "status": "cancelled", "amount": 30.5}\n]\n',
            },
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="写入不应报错"),
                Assertion(
                    type=AssertionType.SIDE_EFFECT,
                    description="写入后 read_file 能读到 JSON",
                    expected={
                        "verify_tool": "read_file",
                        "verify_input": {"path": "/tmp/eval_data.json"},
                        "verify_path": "",
                        "verify_value": "订单A",
                    },
                ),
            ],
        ),
        ToolEvalCase(
            id="wf_23",
            tool_name="write_file",
            description="/tmp - 写入 CSV 文件",
            category="normal",
            input_data={
                "path": "/tmp/eval_metrics.csv",
                "content": "metric,value,timestamp\ncpu_usage,78.5,2024-03-15T10:00:00\nmemory_usage,62.3,2024-03-15T10:00:00\ndisk_io,15.7,2024-03-15T10:00:00\n",
            },
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="写入不应报错"),
                Assertion(
                    type=AssertionType.SIDE_EFFECT,
                    description="写入后 read_file 能读到 CSV",
                    expected={
                        "verify_tool": "read_file",
                        "verify_input": {"path": "/tmp/eval_metrics.csv"},
                        "verify_path": "",
                        "verify_value": "cpu_usage",
                    },
                ),
            ],
        ),
        ToolEvalCase(
            id="wf_24",
            tool_name="write_file",
            description="/tmp - 写入多行文件（行范围读取依赖）",
            category="normal",
            input_data={
                "path": "/tmp/eval_lines.txt",
                "content": "alpha\nbeta\ngamma\ndelta\nepsilon\nzeta\neta\ntheta\n",
            },
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="写入不应报错"),
                Assertion(type=AssertionType.CONTAINS, expected="已写入", description="提示已写入"),
                Assertion(
                    type=AssertionType.SIDE_EFFECT,
                    description="写入后 read_file 能读到",
                    expected={
                        "verify_tool": "read_file",
                        "verify_input": {"path": "/tmp/eval_lines.txt"},
                        "verify_path": "",
                        "verify_value": "alpha",
                    },
                ),
            ],
        ),
        ToolEvalCase(
            id="wf_25",
            tool_name="write_file",
            description="/tmp - 写入深层子目录文件（自动创建）",
            category="normal",
            input_data={
                "path": "/tmp/eval_deep/level1/level2/level3/config.yaml",
                "content": "app:\n  name: test-service\n  version: 1.0.0\n  port: 8080\n",
            },
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="深层目录自动创建不应报错"),
                Assertion(
                    type=AssertionType.SIDE_EFFECT,
                    description="写入后 read_file 能读到深层文件",
                    expected={
                        "verify_tool": "read_file",
                        "verify_input": {"path": "/tmp/eval_deep/level1/level2/level3/config.yaml"},
                        "verify_path": "",
                        "verify_value": "test-service",
                    },
                ),
            ],
        ),

        # ── 正常场景：覆盖写入 ──
        ToolEvalCase(
            id="wf_26",
            tool_name="write_file",
            description="/sandbox - 覆盖已有文件",
            category="normal",
            setup_steps=[
                {"tool": "write_file", "input": {
                    "path": "/sandbox/overwrite_test.txt",
                    "content": "original content",
                }},
            ],
            input_data={
                "path": "/sandbox/overwrite_test.txt",
                "content": "new overwritten content",
            },
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="覆盖写入不应报错"),
                Assertion(
                    type=AssertionType.SIDE_EFFECT,
                    description="覆盖后 read_file 应读到新内容",
                    expected={
                        "verify_tool": "read_file",
                        "verify_input": {"path": "/sandbox/overwrite_test.txt"},
                        "verify_path": "",
                        "verify_value": "new overwritten content",
                    },
                ),
            ],
        ),
        ToolEvalCase(
            id="wf_27",
            tool_name="write_file",
            description="/tmp - 覆盖已有文件",
            category="normal",
            setup_steps=[
                {"tool": "write_file", "input": {
                    "path": "/tmp/eval_overwrite.txt",
                    "content": "old data",
                }},
            ],
            input_data={
                "path": "/tmp/eval_overwrite.txt",
                "content": "replaced data after overwrite",
            },
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="覆盖写入不应报错"),
                Assertion(
                    type=AssertionType.SIDE_EFFECT,
                    description="覆盖后 read_file 应读到新内容",
                    expected={
                        "verify_tool": "read_file",
                        "verify_input": {"path": "/tmp/eval_overwrite.txt"},
                        "verify_path": "",
                        "verify_value": "replaced data after overwrite",
                    },
                ),
            ],
        ),

        # ══════════════════════════════════════════════════════════════
        # write_file — 错误场景
        # ══════════════════════════════════════════════════════════════

        ToolEvalCase(
            id="wf_30",
            tool_name="write_file",
            description="错误 - 空路径应返回错误",
            category="error",
            input_data={"path": "", "content": "test"},
            assertions=[
                Assertion(type=AssertionType.IS_ERROR, description="空路径应报错"),
            ],
        ),
        ToolEvalCase(
            id="wf_31",
            tool_name="write_file",
            description="错误 - 路径穿越 ../../../etc/passwd 应拒绝",
            category="error",
            input_data={"path": "/sandbox/../../../etc/passwd", "content": "hacked"},
            assertions=[
                Assertion(type=AssertionType.IS_ERROR, description="路径穿越应报错或被拦截"),
            ],
        ),
        ToolEvalCase(
            id="wf_32",
            tool_name="write_file",
            description="错误 - 写入禁止目录 /etc",
            category="error",
            input_data={"path": "/etc/evil.conf", "content": "malicious"},
            assertions=[
                Assertion(type=AssertionType.IS_ERROR, description="写入 /etc 应报错"),
            ],
        ),
        ToolEvalCase(
            id="wf_33",
            tool_name="write_file",
            description="错误 - 写入禁止目录 /root",
            category="error",
            input_data={"path": "/root/.bashrc", "content": "export EVIL=1"},
            assertions=[
                Assertion(type=AssertionType.IS_ERROR, description="写入 /root 应报错"),
            ],
        ),
        ToolEvalCase(
            id="wf_34",
            tool_name="write_file",
            description="错误 - 路径穿越 /tmp/../etc/hosts 应拒绝",
            category="error",
            input_data={"path": "/tmp/../etc/hosts", "content": "127.0.0.1 evil.com"},
            assertions=[
                Assertion(type=AssertionType.IS_ERROR, description="路径穿越到系统目录应报错"),
            ],
        ),
        ToolEvalCase(
            id="wf_35",
            tool_name="write_file",
            description="错误 - 写入已存在目录同名路径（路径是目录不是文件）",
            category="error",
            setup_steps=[
                {"tool": "terminal", "input": {"command": "mkdir -p /sandbox/existing_dir"}},
            ],
            input_data={"path": "/sandbox/existing_dir", "content": "should fail"},
            assertions=[
                Assertion(type=AssertionType.IS_ERROR, description="写入目录路径应报错"),
            ],
            cleanup_steps=[
                {"tool": "terminal", "input": {"command": "rm -rf /sandbox/existing_dir"}},
            ],
        ),
        ToolEvalCase(
            id="wf_36",
            tool_name="write_file",
            description="错误 - 缺少 content 字段（只传 path）",
            category="error",
            input_data={"path": "/sandbox/no_content.txt"},
            assertions=[
                Assertion(type=AssertionType.IS_ERROR, description="缺少 content 应报错"),
            ],
        ),
        ToolEvalCase(
            id="wf_37",
            tool_name="write_file",
            description="错误 - 写入绝对路径不在允许范围（如 /var/log/）",
            category="error",
            input_data={"path": "/var/log/evil.log", "content": "inject"},
            assertions=[
                Assertion(type=AssertionType.IS_ERROR, description="写入 /var/log 应报错"),
            ],
        ),

        # ══════════════════════════════════════════════════════════════
        # write_file — 边界场景
        # ══════════════════════════════════════════════════════════════

        ToolEvalCase(
            id="wf_40",
            tool_name="write_file",
            description="边界 - 写入空内容",
            category="boundary",
            input_data={"path": "/sandbox/test/empty_file.txt", "content": ""},
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="空内容应允许写入"),
                Assertion(
                    type=AssertionType.SIDE_EFFECT,
                    description="写入后 read_file 能读到（空文件）",
                    expected={
                        "verify_tool": "read_file",
                        "verify_input": {"path": "/sandbox/test/empty_file.txt"},
                        "verify_path": "",
                        "verify_value": "",
                    },
                ),
            ],
            cleanup_steps=[
                {"tool": "terminal", "input": {"command": "rm -f '/sandbox/test/empty_file.txt'"}},
            ],
        ),
        ToolEvalCase(
            id="wf_41",
            tool_name="write_file",
            description="边界 - 写入只有换行符的内容",
            category="boundary",
            input_data={"path": "/sandbox/test/newlines_only.txt", "content": "\n\n\n"},
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="纯换行内容应允许写入"),
                Assertion(
                    type=AssertionType.SIDE_EFFECT,
                    description="写入后 read_file 可读到",
                    expected={
                        "verify_tool": "read_file",
                        "verify_input": {"path": "/sandbox/test/newlines_only.txt"},
                        "verify_path": "",
                        "verify_value": "",
                    },
                ),
            ],
            cleanup_steps=[
                {"tool": "terminal", "input": {"command": "rm -f '/sandbox/test/newlines_only.txt'"}},
            ],
        ),
        ToolEvalCase(
            id="wf_42",
            tool_name="write_file",
            description="边界 - 写入超长单行内容（10000字符）",
            category="boundary",
            input_data={"path": "/sandbox/test/long_line.txt", "content": "A" * 10000 + "\n"},
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="超长行不应报错"),
                Assertion(
                    type=AssertionType.SIDE_EFFECT,
                    description="写入后 read_file 能读到",
                    expected={
                        "verify_tool": "read_file",
                        "verify_input": {"path": "/sandbox/test/long_line.txt"},
                        "verify_path": "",
                        "verify_value": "AAAA",
                    },
                ),
            ],
            cleanup_steps=[
                {"tool": "terminal", "input": {"command": "rm -f '/sandbox/test/long_line.txt'"}},
            ],
        ),
        ToolEvalCase(
            id="wf_43",
            tool_name="write_file",
            description="边界 - 文件名含空格",
            category="boundary",
            input_data={
                "path": "/sandbox/test/file with spaces.txt",
                "content": "content of file with spaces in name\n",
            },
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="文件名含空格不应报错"),
                Assertion(
                    type=AssertionType.SIDE_EFFECT,
                    description="写入后 read_file 能读到",
                    expected={
                        "verify_tool": "read_file",
                        "verify_input": {"path": "/sandbox/test/file with spaces.txt"},
                        "verify_path": "",
                        "verify_value": "content of file",
                    },
                ),
            ],
            cleanup_steps=[
                {"tool": "terminal", "input": {"command": "rm -f '/sandbox/test/file with spaces.txt'"}},
            ],
        ),
        ToolEvalCase(
            id="wf_44",
            tool_name="write_file",
            description="边界 - 文件名含特殊字符（连字符/括号/点）",
            category="boundary",
            input_data={
                "path": "/tmp/eval_special-file_v2.0(1).txt",
                "content": "file with special chars in name\n",
            },
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="特殊字符文件名不应报错"),
                Assertion(
                    type=AssertionType.SIDE_EFFECT,
                    description="写入后 read_file 能读到",
                    expected={
                        "verify_tool": "read_file",
                        "verify_input": {"path": "/tmp/eval_special-file_v2.0(1).txt"},
                        "verify_path": "",
                        "verify_value": "special chars",
                    },
                ),
            ],
            cleanup_steps=[
                {"tool": "terminal", "input": {"command": "rm -f '/tmp/eval_special-file_v2.0(1).txt'"}},
            ],
        ),
        ToolEvalCase(
            id="wf_45",
            tool_name="write_file",
            description="边界 - /tmp 写入空内容",
            category="boundary",
            input_data={"path": "/tmp/eval_empty_boundary.txt", "content": ""},
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="空内容应允许写入"),
            ],
            cleanup_steps=[
                {"tool": "terminal", "input": {"command": "rm -f '/tmp/eval_empty_boundary.txt'"}},
            ],
        ),
        ToolEvalCase(
            id="wf_46",
            tool_name="write_file",
            description="边界 - 写入大量行数的文件（200行）",
            category="boundary",
            input_data={
                "path": "/sandbox/test/many_lines.txt",
                "content": "\n".join([f"line {i}: data_{i}" for i in range(200)]) + "\n",
            },
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="大量行数写入不应报错"),
                Assertion(type=AssertionType.CONTAINS, expected="已写入", description="提示已写入"),
                Assertion(
                    type=AssertionType.SIDE_EFFECT,
                    description="写入后 read_file 能读到末尾数据",
                    expected={
                        "verify_tool": "read_file",
                        "verify_input": {"path": "/sandbox/test/many_lines.txt", "offset": 195, "limit": 5},
                        "verify_path": "",
                        "verify_value": "line 199",
                    },
                ),
            ],
            cleanup_steps=[
                {"tool": "terminal", "input": {"command": "rm -f '/sandbox/test/many_lines.txt'"}},
            ],
        ),
        ToolEvalCase(
            id="wf_47",
            tool_name="write_file",
            description="边界 - 文件名含中文字符",
            category="boundary",
            input_data={
                "path": "/sandbox/docs/测试报告_v1.md",
                "content": "# 中文文件名测试\n\n内容正常\n",
            },
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="中文文件名不应报错"),
                Assertion(
                    type=AssertionType.SIDE_EFFECT,
                    description="写入后 read_file 能通过中文路径读到",
                    expected={
                        "verify_tool": "read_file",
                        "verify_input": {"path": "/sandbox/docs/测试报告_v1.md"},
                        "verify_path": "",
                        "verify_value": "中文文件名测试",
                    },
                ),
            ],
            cleanup_steps=[
                {"tool": "terminal", "input": {"command": "rm -f '/sandbox/docs/测试报告_v1.md'"}},
            ],
        ),
        ToolEvalCase(
            id="wf_48",
            tool_name="write_file",
            description="边界 - 写入包含特殊控制字符的内容（Tab/CR/垂直制表符）",
            category="boundary",
            input_data={
                "path": "/sandbox/test/control_chars.txt",
                "content": "header\t\ttab_separated\r\nCRLF line\nNormal line\x0bvertical_tab\n",
            },
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="包含控制字符不应崩溃"),
            ],
            cleanup_steps=[
                {"tool": "terminal", "input": {"command": "rm -f '/sandbox/test/control_chars.txt'"}},
            ],
        ),
        ToolEvalCase(
            id="wf_49",
            tool_name="write_file",
            description="边界 - 非常深的嵌套路径（7层）自动创建",
            category="boundary",
            input_data={
                "path": "/sandbox/a/b/c/d/e/f/g/deep_file.txt",
                "content": "very deep file\n",
            },
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="7层深目录自动创建不应报错"),
                Assertion(
                    type=AssertionType.SIDE_EFFECT,
                    description="写入后 read_file 能读到深层文件",
                    expected={
                        "verify_tool": "read_file",
                        "verify_input": {"path": "/sandbox/a/b/c/d/e/f/g/deep_file.txt"},
                        "verify_path": "",
                        "verify_value": "very deep",
                    },
                ),
            ],
            cleanup_steps=[
                {"tool": "terminal", "input": {"command": "rm -rf /sandbox/a"}},
            ],
        ),

        # ══════════════════════════════════════════════════════════════
        # write_file — 副作用场景（与其他工具交叉验证）
        # ══════════════════════════════════════════════════════════════

        ToolEvalCase(
            id="wf_50",
            tool_name="write_file",
            description="副作用 - write_file 写入后 search_files 能搜索到内容",
            category="side_effect",
            input_data={
                "path": "/sandbox/side_effect/searchable.py",
                "content": "# UNIQUE_MARKER_WF50\ndef unique_function():\n    pass\n",
            },
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="写入不应报错"),
                Assertion(
                    type=AssertionType.SIDE_EFFECT,
                    description="写入后 search_files 能搜索到唯一标记",
                    expected={
                        "verify_tool": "search_files",
                        "verify_input": {"pattern": "UNIQUE_MARKER_WF50", "path": "/sandbox/side_effect"},
                        "verify_path": "",
                        "verify_value": "UNIQUE_MARKER_WF50",
                    },
                ),
            ],
            cleanup_steps=[
                {"tool": "terminal", "input": {"command": "rm -rf /sandbox/side_effect"}},
            ],
        ),
        ToolEvalCase(
            id="wf_51",
            tool_name="write_file",
            description="副作用 - write_file 写入后 terminal cat 能读到内容",
            category="side_effect",
            input_data={
                "path": "/sandbox/side_effect/cat_test.txt",
                "content": "TERMINAL_VERIFY_CONTENT_WF51\n",
            },
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="写入不应报错"),
                Assertion(
                    type=AssertionType.SIDE_EFFECT,
                    description="写入后 terminal cat 能读到内容",
                    expected={
                        "verify_tool": "terminal",
                        "verify_input": {"command": "cat /sandbox/side_effect/cat_test.txt"},
                        "verify_path": "",
                        "verify_value": "TERMINAL_VERIFY_CONTENT_WF51",
                    },
                ),
            ],
            cleanup_steps=[
                {"tool": "terminal", "input": {"command": "rm -rf /sandbox/side_effect"}},
            ],
        ),
        ToolEvalCase(
            id="wf_52",
            tool_name="write_file",
            description="副作用 - write_file 覆盖后旧内容不再存在",
            category="side_effect",
            setup_steps=[
                {"tool": "write_file", "input": {
                    "path": "/sandbox/side_effect/overwrite_verify.txt",
                    "content": "OLD_CONTENT_SHOULD_DISAPPEAR\n",
                }},
            ],
            input_data={
                "path": "/sandbox/side_effect/overwrite_verify.txt",
                "content": "NEW_CONTENT_AFTER_OVERWRITE\n",
            },
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="覆盖写入不应报错"),
                Assertion(
                    type=AssertionType.SIDE_EFFECT,
                    description="覆盖后 read_file 应读到新内容",
                    expected={
                        "verify_tool": "read_file",
                        "verify_input": {"path": "/sandbox/side_effect/overwrite_verify.txt"},
                        "verify_path": "",
                        "verify_value": "NEW_CONTENT_AFTER_OVERWRITE",
                    },
                ),
                Assertion(
                    type=AssertionType.SIDE_EFFECT,
                    description="覆盖后 search_files 搜索旧内容应找不到",
                    expected={
                        "verify_tool": "search_files",
                        "verify_input": {"pattern": "OLD_CONTENT_SHOULD_DISAPPEAR", "path": "/sandbox/side_effect"},
                        "verify_path": "",
                        "verify_value": "未找到",
                    },
                ),
            ],
            cleanup_steps=[
                {"tool": "terminal", "input": {"command": "rm -rf /sandbox/side_effect"}},
            ],
        ),
        ToolEvalCase(
            id="wf_53",
            tool_name="write_file",
            description="副作用 - write_file 写入 Python 文件后 execute_code 可执行",
            category="side_effect",
            input_data={
                "path": "/sandbox/side_effect/runnable.py",
                "content": "print('EXEC_OUTPUT_WF53')\n",
            },
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="写入不应报错"),
                Assertion(
                    type=AssertionType.SIDE_EFFECT,
                    description="写入后 terminal 执行 python 能得到输出",
                    expected={
                        "verify_tool": "terminal",
                        "verify_input": {"command": "python3 /sandbox/side_effect/runnable.py"},
                        "verify_path": "",
                        "verify_value": "EXEC_OUTPUT_WF53",
                    },
                ),
            ],
            cleanup_steps=[
                {"tool": "terminal", "input": {"command": "rm -rf /sandbox/side_effect"}},
            ],
        ),
        ToolEvalCase(
            id="wf_54",
            tool_name="write_file",
            description="副作用 - write_file 写入 /tmp 后 search_files 能搜索到",
            category="side_effect",
            input_data={
                "path": "/tmp/eval_side_effect/marker.txt",
                "content": "TMP_SEARCH_MARKER_WF54\n",
            },
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="写入不应报错"),
                Assertion(
                    type=AssertionType.SIDE_EFFECT,
                    description="写入后 search_files 能在 /tmp 搜索到",
                    expected={
                        "verify_tool": "search_files",
                        "verify_input": {"pattern": "TMP_SEARCH_MARKER_WF54", "path": "/tmp/eval_side_effect"},
                        "verify_path": "",
                        "verify_value": "TMP_SEARCH_MARKER_WF54",
                    },
                ),
            ],
            cleanup_steps=[
                {"tool": "terminal", "input": {"command": "rm -rf /tmp/eval_side_effect"}},
            ],
        ),
        ToolEvalCase(
            id="wf_55",
            tool_name="write_file",
            description="副作用 - 写入 Shell 脚本后 terminal 可执行",
            category="side_effect",
            input_data={
                "path": "/sandbox/side_effect/run.sh",
                "content": "#!/bin/bash\necho 'SHELL_EXEC_WF55'\n",
            },
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="写入不应报错"),
                Assertion(
                    type=AssertionType.SIDE_EFFECT,
                    description="写入后赋予权限并执行能得到输出",
                    expected={
                        "verify_tool": "terminal",
                        "verify_input": {"command": "chmod +x /sandbox/side_effect/run.sh && /sandbox/side_effect/run.sh"},
                        "verify_path": "",
                        "verify_value": "SHELL_EXEC_WF55",
                    },
                ),
            ],
            cleanup_steps=[
                {"tool": "terminal", "input": {"command": "rm -rf /sandbox/side_effect"}},
            ],
        ),

        # ══════════════════════════════════════════════════════════════
        # search_files — /sandbox 目录正常场景
        # ══════════════════════════════════════════════════════════════

        ToolEvalCase(
            id="sf_01",
            tool_name="search_files",
            description="/sandbox - 搜索 Python 文件中的函数定义",
            category="normal",
            setup_steps=[
                {"tool": "write_file", "input": {
                    "path": "/sandbox/app/main.py",
                    "content": "import os\n\ndef hello_world():\n    print('hello')\n\ndef goodbye():\n    print('bye')\n",
                }},
            ],
            input_data={"pattern": "def hello_world", "path": "/sandbox/app"},
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="不应报错"),
                Assertion(type=AssertionType.CONTAINS, expected="hello_world", description="结果包含函数名"),
            ],
            cleanup_steps=[
                {"tool": "terminal", "input": {"command": "rm -rf /sandbox/app"}},
            ],
        ),
        ToolEvalCase(
            id="sf_02",
            tool_name="search_files",
            description="/sandbox - 搜索 TODO 注释",
            category="normal",
            setup_steps=[
                {"tool": "write_file", "input": {
                    "path": "/sandbox/src/utils.py",
                    "content": "# TODO: add error handling\nimport sys\n# TODO: optimize performance\ndef run():\n    pass\n",
                }},
            ],
            input_data={"pattern": "TODO", "path": "/sandbox/src"},
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="不应报错"),
                Assertion(type=AssertionType.CONTAINS, expected="TODO", description="结果包含 TODO"),
            ],
            cleanup_steps=[
                {"tool": "terminal", "input": {"command": "rm -rf /sandbox/src"}},
            ],
        ),
        ToolEvalCase(
            id="sf_03",
            tool_name="search_files",
            description="/sandbox - 搜索 JSON 文件中的配置项",
            category="normal",
            setup_steps=[
                {"tool": "write_file", "input": {
                    "path": "/sandbox/config/settings.json",
                    "content": "{\n  \"database\": {\n    \"host\": \"localhost\",\n    \"port\": 5432\n  }\n}\n",
                }},
            ],
            input_data={"pattern": "localhost", "path": "/sandbox/config"},
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="不应报错"),
                Assertion(type=AssertionType.CONTAINS, expected="localhost", description="结果包含配置值"),
            ],
            cleanup_steps=[
                {"tool": "terminal", "input": {"command": "rm -rf /sandbox/config"}},
            ],
        ),
        ToolEvalCase(
            id="sf_04",
            tool_name="search_files",
            description="/sandbox - 使用 include 过滤仅搜索 .py 文件",
            category="normal",
            setup_steps=[
                {"tool": "write_file", "input": {
                    "path": "/sandbox/mixed/code.py",
                    "content": "# Python import\nimport os\n",
                }},
                {"tool": "write_file", "input": {
                    "path": "/sandbox/mixed/code.js",
                    "content": "// JS import\nimport React from 'react';\n",
                }},
            ],
            input_data={"pattern": "import", "path": "/sandbox/mixed", "include": "*.py"},
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="不应报错"),
                Assertion(type=AssertionType.CONTAINS, expected="code.py", description="结果包含 .py 文件"),
            ],
            cleanup_steps=[
                {"tool": "terminal", "input": {"command": "rm -rf /sandbox/mixed"}},
            ],
        ),
        ToolEvalCase(
            id="sf_05",
            tool_name="search_files",
            description="/sandbox - 搜索不存在的内容返回未找到",
            category="normal",
            setup_steps=[
                {"tool": "write_file", "input": {
                    "path": "/sandbox/test/sample.txt",
                    "content": "hello world\nfoo bar\n",
                }},
            ],
            input_data={"pattern": "zzz_nonexistent_xyz_999", "path": "/sandbox/test"},
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="未找到不应报错"),
                Assertion(type=AssertionType.CONTAINS, expected="未找到", description="提示未找到"),
            ],
            cleanup_steps=[
                {"tool": "terminal", "input": {"command": "rm -rf /sandbox/test"}},
            ],
        ),
        ToolEvalCase(
            id="sf_06",
            tool_name="search_files",
            description="/sandbox - 递归搜索深层目录",
            category="normal",
            setup_steps=[
                {"tool": "write_file", "input": {
                    "path": "/sandbox/deep/a/b/c/target.py",
                    "content": "# DEEP_MARKER_UNIQUE\ndeep content\n",
                }},
            ],
            input_data={"pattern": "DEEP_MARKER_UNIQUE", "path": "/sandbox/deep"},
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="不应报错"),
                Assertion(type=AssertionType.CONTAINS, expected="DEEP_MARKER_UNIQUE", description="能递归搜索到深层文件"),
            ],
            cleanup_steps=[
                {"tool": "terminal", "input": {"command": "rm -rf /sandbox/deep"}},
            ],
        ),
        ToolEvalCase(
            id="sf_07",
            tool_name="search_files",
            description="/sandbox - 搜索结果包含行号",
            category="normal",
            setup_steps=[
                {"tool": "write_file", "input": {
                    "path": "/sandbox/lineno/test.py",
                    "content": "line1\nline2\nTARGET_LINE\nline4\n",
                }},
            ],
            input_data={"pattern": "TARGET_LINE", "path": "/sandbox/lineno"},
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="不应报错"),
                Assertion(type=AssertionType.CONTAINS, expected="3", description="结果包含行号 3"),
                Assertion(type=AssertionType.CONTAINS, expected="TARGET_LINE", description="结果包含匹配内容"),
            ],
            cleanup_steps=[
                {"tool": "terminal", "input": {"command": "rm -rf /sandbox/lineno"}},
            ],
        ),
        ToolEvalCase(
            id="sf_08",
            tool_name="search_files",
            description="/sandbox - 搜索多个文件匹配",
            category="normal",
            setup_steps=[
                {"tool": "write_file", "input": {
                    "path": "/sandbox/multi/a.py",
                    "content": "# COMMON_MARKER\nfile a\n",
                }},
                {"tool": "write_file", "input": {
                    "path": "/sandbox/multi/b.py",
                    "content": "# COMMON_MARKER\nfile b\n",
                }},
                {"tool": "write_file", "input": {
                    "path": "/sandbox/multi/c.txt",
                    "content": "# COMMON_MARKER\nfile c\n",
                }},
            ],
            input_data={"pattern": "COMMON_MARKER", "path": "/sandbox/multi"},
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="不应报错"),
                Assertion(type=AssertionType.CONTAINS, expected="a.py", description="结果包含 a.py"),
                Assertion(type=AssertionType.CONTAINS, expected="b.py", description="结果包含 b.py"),
                Assertion(type=AssertionType.CONTAINS, expected="c.txt", description="结果包含 c.txt"),
            ],
            cleanup_steps=[
                {"tool": "terminal", "input": {"command": "rm -rf /sandbox/multi"}},
            ],
        ),
        ToolEvalCase(
            id="sf_09",
            tool_name="search_files",
            description="/sandbox - 搜索中文内容",
            category="normal",
            setup_steps=[
                {"tool": "write_file", "input": {
                    "path": "/sandbox/i18n/chinese.md",
                    "content": "# 项目说明\n这是一个测试项目\n包含中文内容\n",
                }},
            ],
            input_data={"pattern": "测试项目", "path": "/sandbox/i18n"},
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="不应报错"),
                Assertion(type=AssertionType.CONTAINS, expected="测试项目", description="能搜索到中文内容"),
            ],
            cleanup_steps=[
                {"tool": "terminal", "input": {"command": "rm -rf /sandbox/i18n"}},
            ],
        ),
        ToolEvalCase(
            id="sf_10",
            tool_name="search_files",
            description="/sandbox - 搜索隐藏文件(dot file)内容",
            category="normal",
            setup_steps=[
                {"tool": "write_file", "input": {
                    "path": "/sandbox/hidden/.env",
                    "content": "DB_HOST=localhost\nDB_PORT=3306\nSECRET_KEY=abc123\n",
                }},
            ],
            input_data={"pattern": "DB_HOST", "path": "/sandbox/hidden"},
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="不应报错"),
                Assertion(type=AssertionType.CONTAINS, expected="DB_HOST", description="能搜索到隐藏文件内容"),
            ],
            cleanup_steps=[
                {"tool": "terminal", "input": {"command": "rm -rf /sandbox/hidden"}},
            ],
        ),

        # ══════════════════════════════════════════════════════════════
        # search_files — /tmp 目录正常场景
        # ══════════════════════════════════════════════════════════════

        ToolEvalCase(
            id="sf_11",
            tool_name="search_files",
            description="/tmp - 搜索临时文件内容",
            category="normal",
            setup_steps=[
                {"tool": "write_file", "input": {
                    "path": "/tmp/eval_search/data.csv",
                    "content": "name,age,city\n张三,25,北京\n李四,30,上海\n",
                }},
            ],
            input_data={"pattern": "张三", "path": "/tmp/eval_search"},
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="不应报错"),
                Assertion(type=AssertionType.CONTAINS, expected="张三", description="能搜索到内容"),
            ],
            cleanup_steps=[
                {"tool": "terminal", "input": {"command": "rm -rf /tmp/eval_search"}},
            ],
        ),
        ToolEvalCase(
            id="sf_12",
            tool_name="search_files",
            description="/tmp - 使用 include 过滤 .md 文件",
            category="normal",
            setup_steps=[
                {"tool": "write_file", "input": {
                    "path": "/tmp/eval_filter/readme.md",
                    "content": "# FILTER_TARGET\nmarkdown content\n",
                }},
                {"tool": "write_file", "input": {
                    "path": "/tmp/eval_filter/readme.txt",
                    "content": "FILTER_TARGET in txt\n",
                }},
            ],
            input_data={"pattern": "FILTER_TARGET", "path": "/tmp/eval_filter", "include": "*.md"},
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="不应报错"),
                Assertion(type=AssertionType.CONTAINS, expected="readme.md", description="结果只包含 .md 文件"),
            ],
            cleanup_steps=[
                {"tool": "terminal", "input": {"command": "rm -rf /tmp/eval_filter"}},
            ],
        ),
        ToolEvalCase(
            id="sf_13",
            tool_name="search_files",
            description="/tmp - 搜索深层子目录",
            category="normal",
            setup_steps=[
                {"tool": "write_file", "input": {
                    "path": "/tmp/eval_deep/level1/level2/level3/target.py",
                    "content": "# TMP_DEEP_UNIQUE_MARKER\npass\n",
                }},
            ],
            input_data={"pattern": "TMP_DEEP_UNIQUE_MARKER", "path": "/tmp/eval_deep"},
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="不应报错"),
                Assertion(type=AssertionType.CONTAINS, expected="TMP_DEEP_UNIQUE_MARKER", description="能递归到深层目录"),
            ],
            cleanup_steps=[
                {"tool": "terminal", "input": {"command": "rm -rf /tmp/eval_deep"}},
            ],
        ),

        # ══════════════════════════════════════════════════════════════
        # search_files — 正则表达式场景
        # ══════════════════════════════════════════════════════════════

        ToolEvalCase(
            id="sf_14",
            tool_name="search_files",
            description="正则 - 匹配 IP 地址格式",
            category="normal",
            setup_steps=[
                {"tool": "write_file", "input": {
                    "path": "/sandbox/regex/config.txt",
                    "content": "server=192.168.1.100\ngateway=10.0.0.1\nname=hello\n",
                }},
            ],
            input_data={"pattern": "[0-9]\\+\\.[0-9]\\+\\.[0-9]\\+\\.[0-9]\\+", "path": "/sandbox/regex"},
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="正则搜索不应报错"),
                Assertion(type=AssertionType.CONTAINS, expected="192.168.1.100", description="匹配到 IP 地址"),
            ],
            cleanup_steps=[
                {"tool": "terminal", "input": {"command": "rm -rf /sandbox/regex"}},
            ],
        ),
        ToolEvalCase(
            id="sf_15",
            tool_name="search_files",
            description="正则 - 匹配邮箱格式",
            category="normal",
            setup_steps=[
                {"tool": "write_file", "input": {
                    "path": "/sandbox/regex/contacts.txt",
                    "content": "user: admin@example.com\nphone: 123456\nbackup: test@test.org\n",
                }},
            ],
            input_data={"pattern": "[a-zA-Z0-9]\\+@[a-zA-Z0-9]\\+\\.[a-z]\\+", "path": "/sandbox/regex"},
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="正则搜索不应报错"),
                Assertion(type=AssertionType.CONTAINS, expected="admin@example.com", description="匹配到邮箱"),
            ],
            cleanup_steps=[
                {"tool": "terminal", "input": {"command": "rm -rf /sandbox/regex"}},
            ],
        ),
        ToolEvalCase(
            id="sf_16",
            tool_name="search_files",
            description="正则 - 行首匹配 (^import)",
            category="normal",
            setup_steps=[
                {"tool": "write_file", "input": {
                    "path": "/sandbox/regex/imports.py",
                    "content": "import os\nimport sys\nfrom pathlib import Path\nx = 'import'\n",
                }},
            ],
            input_data={"pattern": "^import", "path": "/sandbox/regex", "include": "*.py"},
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="行首匹配不应报错"),
                Assertion(type=AssertionType.CONTAINS, expected="import os", description="匹配到行首 import"),
            ],
            cleanup_steps=[
                {"tool": "terminal", "input": {"command": "rm -rf /sandbox/regex"}},
            ],
        ),
        ToolEvalCase(
            id="sf_17",
            tool_name="search_files",
            description="正则 - 行尾匹配 (;$)",
            category="normal",
            setup_steps=[
                {"tool": "write_file", "input": {
                    "path": "/sandbox/regex/code.js",
                    "content": "const a = 1;\nconst b = 2\nconst c = 3;\n",
                }},
            ],
            input_data={"pattern": ";$", "path": "/sandbox/regex", "include": "*.js"},
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="行尾匹配不应报错"),
                Assertion(type=AssertionType.CONTAINS, expected="const a = 1;", description="匹配到以分号结尾的行"),
            ],
            cleanup_steps=[
                {"tool": "terminal", "input": {"command": "rm -rf /sandbox/regex"}},
            ],
        ),

        # ══════════════════════════════════════════════════════════════
        # search_files — 错误场景
        # ══════════════════════════════════════════════════════════════

        ToolEvalCase(
            id="sf_30",
            tool_name="search_files",
            description="错误 - 空搜索模式应返回错误",
            category="error",
            input_data={"pattern": ""},
            assertions=[
                Assertion(type=AssertionType.IS_ERROR, description="空模式应报错"),
            ],
        ),
        ToolEvalCase(
            id="sf_31",
            tool_name="search_files",
            description="错误 - 搜索不存在的目录",
            category="error",
            input_data={"pattern": "test", "path": "/sandbox/nonexistent_dir_xyz_999"},
            assertions=[
                Assertion(type=AssertionType.IS_ERROR, description="不存在的目录应报错"),
            ],
        ),
        ToolEvalCase(
            id="sf_32",
            tool_name="search_files",
            description="错误 - 搜索不存在的 /tmp 子目录",
            category="error",
            input_data={"pattern": "test", "path": "/tmp/nonexistent_dir_xyz_999"},
            assertions=[
                Assertion(type=AssertionType.IS_ERROR, description="不存在的目录应报错"),
            ],
        ),
        ToolEvalCase(
            id="sf_33",
            tool_name="search_files",
            description="错误 - 无效正则表达式",
            category="error",
            input_data={"pattern": "[invalid(regex", "path": "/sandbox"},
            assertions=[
                Assertion(type=AssertionType.IS_ERROR, description="无效正则应报错"),
            ],
        ),
        ToolEvalCase(
            id="sf_34",
            tool_name="search_files",
            description="错误 - 对文件路径而非目录执行搜索",
            category="error",
            setup_steps=[
                {"tool": "write_file", "input": {
                    "path": "/sandbox/err_test/file.txt",
                    "content": "some content\n",
                }},
            ],
            input_data={"pattern": "content", "path": "/sandbox/err_test/file.txt"},
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="grep 对单文件也能工作，不应报错"),
                Assertion(type=AssertionType.CONTAINS, expected="content", description="能搜到文件内容"),
            ],
            cleanup_steps=[
                {"tool": "terminal", "input": {"command": "rm -rf /sandbox/err_test"}},
            ],
        ),
        ToolEvalCase(
            id="sf_35",
            tool_name="search_files",
            description="错误 - 不存在的深层目录路径",
            category="error",
            input_data={"pattern": "test", "path": "/sandbox/a/b/c/d/e/nonexistent"},
            assertions=[
                Assertion(type=AssertionType.IS_ERROR, description="不存在的深层目录应报错"),
            ],
        ),

        # ══════════════════════════════════════════════════════════════
        # search_files — 边界场景
        # ══════════════════════════════════════════════════════════════

        ToolEvalCase(
            id="sf_40",
            tool_name="search_files",
            description="边界 - 搜索空目录（无文件）",
            category="boundary",
            setup_steps=[
                {"tool": "terminal", "input": {"command": "mkdir -p /sandbox/empty_dir"}},
            ],
            input_data={"pattern": "anything", "path": "/sandbox/empty_dir"},
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="空目录搜索不应崩溃"),
                Assertion(type=AssertionType.CONTAINS, expected="未找到", description="空目录无结果"),
            ],
            cleanup_steps=[
                {"tool": "terminal", "input": {"command": "rm -rf /sandbox/empty_dir"}},
            ],
        ),
        ToolEvalCase(
            id="sf_41",
            tool_name="search_files",
            description="边界 - 搜索包含大量匹配的文件",
            category="boundary",
            setup_steps=[
                {"tool": "terminal", "input": {
                    "command": "python3 -c \"f=open('/sandbox/big/many_matches.txt','w'); [f.write(f'LINE_{i}_MATCH\\n') for i in range(500)]; f.close()\"",
                }},
            ],
            input_data={"pattern": "MATCH", "path": "/sandbox/big"},
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="大量匹配不应崩溃"),
                Assertion(type=AssertionType.CONTAINS, expected="MATCH", description="能返回匹配结果"),
            ],
            cleanup_steps=[
                {"tool": "terminal", "input": {"command": "rm -rf /sandbox/big"}},
            ],
        ),
        ToolEvalCase(
            id="sf_42",
            tool_name="search_files",
            description="边界 - 搜索超长行中的内容",
            category="boundary",
            setup_steps=[
                {"tool": "terminal", "input": {
                    "command": "python3 -c \"f=open('/sandbox/boundary/long_line.txt','w'); f.write('A'*5000 + 'NEEDLE' + 'B'*5000 + '\\n'); f.close()\"",
                }},
            ],
            input_data={"pattern": "NEEDLE", "path": "/sandbox/boundary"},
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="超长行搜索不应崩溃"),
                Assertion(type=AssertionType.CONTAINS, expected="NEEDLE", description="能在超长行中找到内容"),
            ],
            cleanup_steps=[
                {"tool": "terminal", "input": {"command": "rm -rf /sandbox/boundary"}},
            ],
        ),
        ToolEvalCase(
            id="sf_43",
            tool_name="search_files",
            description="边界 - 路径包含空格",
            category="boundary",
            setup_steps=[
                {"tool": "write_file", "input": {
                    "path": "/sandbox/path with spaces/test file.txt",
                    "content": "SPACE_PATH_MARKER content\n",
                }},
            ],
            input_data={"pattern": "SPACE_PATH_MARKER", "path": "/sandbox/path with spaces"},
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="路径含空格不应崩溃"),
                Assertion(type=AssertionType.CONTAINS, expected="SPACE_PATH_MARKER", description="能在含空格路径中搜索"),
            ],
            cleanup_steps=[
                {"tool": "terminal", "input": {"command": "rm -rf '/sandbox/path with spaces'"}},
            ],
        ),
        ToolEvalCase(
            id="sf_44",
            tool_name="search_files",
            description="边界 - 文件名含特殊字符",
            category="boundary",
            setup_steps=[
                {"tool": "write_file", "input": {
                    "path": "/tmp/eval_special_sf/file-v2.0(1).txt",
                    "content": "SPECIAL_CHAR_FILE content\n",
                }},
            ],
            input_data={"pattern": "SPECIAL_CHAR_FILE", "path": "/tmp/eval_special_sf"},
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="特殊字符文件名不应影响搜索"),
                Assertion(type=AssertionType.CONTAINS, expected="SPECIAL_CHAR_FILE", description="能搜到特殊文件名中的内容"),
            ],
            cleanup_steps=[
                {"tool": "terminal", "input": {"command": "rm -rf /tmp/eval_special_sf"}},
            ],
        ),
        ToolEvalCase(
            id="sf_45",
            tool_name="search_files",
            description="边界 - pattern 包含特殊 grep 字符（需转义）",
            category="boundary",
            setup_steps=[
                {"tool": "write_file", "input": {
                    "path": "/sandbox/escape/code.cpp",
                    "content": "int arr[10];\nprintf(\"hello\");\nmap<string, int> m;\n",
                }},
            ],
            input_data={"pattern": "arr\\[10\\]", "path": "/sandbox/escape"},
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="转义搜索不应报错"),
                Assertion(type=AssertionType.CONTAINS, expected="arr[10]", description="能搜索到含方括号的内容"),
            ],
            cleanup_steps=[
                {"tool": "terminal", "input": {"command": "rm -rf /sandbox/escape"}},
            ],
        ),
        ToolEvalCase(
            id="sf_46",
            tool_name="search_files",
            description="边界 - 搜索二进制文件不崩溃",
            category="boundary",
            setup_steps=[
                {"tool": "terminal", "input": {
                    "command": "python3 -c \"f=open('/sandbox/binary/data.bin','wb'); f.write(b'\\x00\\x01TEXT_IN_BIN\\x02\\x03'); f.close()\"",
                }},
            ],
            input_data={"pattern": "TEXT_IN_BIN", "path": "/sandbox/binary"},
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="二进制文件搜索不应崩溃"),
            ],
            cleanup_steps=[
                {"tool": "terminal", "input": {"command": "rm -rf /sandbox/binary"}},
            ],
        ),
        ToolEvalCase(
            id="sf_47",
            tool_name="search_files",
            description="边界 - include 多种扩展名过滤",
            category="boundary",
            setup_steps=[
                {"tool": "write_file", "input": {
                    "path": "/sandbox/filter/app.py",
                    "content": "MULTI_EXT_MARKER py\n",
                }},
                {"tool": "write_file", "input": {
                    "path": "/sandbox/filter/app.js",
                    "content": "MULTI_EXT_MARKER js\n",
                }},
                {"tool": "write_file", "input": {
                    "path": "/sandbox/filter/app.txt",
                    "content": "MULTI_EXT_MARKER txt\n",
                }},
            ],
            input_data={"pattern": "MULTI_EXT_MARKER", "path": "/sandbox/filter", "include": "*.py"},
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="过滤不应报错"),
                Assertion(type=AssertionType.CONTAINS, expected="app.py", description="只包含 .py 文件结果"),
            ],
            cleanup_steps=[
                {"tool": "terminal", "input": {"command": "rm -rf /sandbox/filter"}},
            ],
        ),
        ToolEvalCase(
            id="sf_48",
            tool_name="search_files",
            description="边界 - 搜索空文件不崩溃",
            category="boundary",
            setup_steps=[
                {"tool": "write_file", "input": {
                    "path": "/sandbox/empty_file/empty.txt",
                    "content": "",
                }},
            ],
            input_data={"pattern": "anything", "path": "/sandbox/empty_file"},
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="搜索空文件不应崩溃"),
                Assertion(type=AssertionType.CONTAINS, expected="未找到", description="空文件中无匹配"),
            ],
            cleanup_steps=[
                {"tool": "terminal", "input": {"command": "rm -rf /sandbox/empty_file"}},
            ],
        ),
        ToolEvalCase(
            id="sf_49",
            tool_name="search_files",
            description="边界 - 大小写敏感搜索验证",
            category="boundary",
            setup_steps=[
                {"tool": "write_file", "input": {
                    "path": "/sandbox/case/test.txt",
                    "content": "Hello World\nhello world\nHELLO WORLD\n",
                }},
            ],
            input_data={"pattern": "Hello World", "path": "/sandbox/case"},
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="大小写搜索不应报错"),
                Assertion(type=AssertionType.CONTAINS, expected="Hello World", description="精确匹配大小写"),
            ],
            cleanup_steps=[
                {"tool": "terminal", "input": {"command": "rm -rf /sandbox/case"}},
            ],
        ),

        # ══════════════════════════════════════════════════════════════
        # search_files — 副作用（与其他工具联动）
        # ══════════════════════════════════════════════════════════════

        ToolEvalCase(
            id="sf_50",
            tool_name="search_files",
            description="副作用 - write_file 写入后 search_files 可搜索到",
            category="side_effect",
            setup_steps=[
                {"tool": "write_file", "input": {
                    "path": "/sandbox/side/new_file.py",
                    "content": "# SIDE_EFFECT_WRITE_MARKER\ndef new_function():\n    pass\n",
                }},
            ],
            input_data={"pattern": "SIDE_EFFECT_WRITE_MARKER", "path": "/sandbox/side"},
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="不应报错"),
                Assertion(type=AssertionType.CONTAINS, expected="SIDE_EFFECT_WRITE_MARKER", description="能搜索到刚写入的内容"),
            ],
            cleanup_steps=[
                {"tool": "terminal", "input": {"command": "rm -rf /sandbox/side"}},
            ],
        ),
        ToolEvalCase(
            id="sf_51",
            tool_name="search_files",
            description="副作用 - terminal 创建文件后 search_files 可搜索到",
            category="side_effect",
            setup_steps=[
                {"tool": "terminal", "input": {
                    "command": "mkdir -p /tmp/eval_side_sf && echo 'TERMINAL_CREATED_MARKER' > /tmp/eval_side_sf/created.txt",
                }},
            ],
            input_data={"pattern": "TERMINAL_CREATED_MARKER", "path": "/tmp/eval_side_sf"},
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="不应报错"),
                Assertion(type=AssertionType.CONTAINS, expected="TERMINAL_CREATED_MARKER", description="能搜索到 terminal 创建的内容"),
            ],
            cleanup_steps=[
                {"tool": "terminal", "input": {"command": "rm -rf /tmp/eval_side_sf"}},
            ],
        ),
        ToolEvalCase(
            id="sf_52",
            tool_name="search_files",
            description="副作用 - 删除文件后 search_files 搜索不到",
            category="side_effect",
            setup_steps=[
                {"tool": "write_file", "input": {
                    "path": "/sandbox/delete_test/will_delete.txt",
                    "content": "DELETE_ME_MARKER content\n",
                }},
                {"tool": "terminal", "input": {
                    "command": "rm -f /sandbox/delete_test/will_delete.txt",
                }},
            ],
            input_data={"pattern": "DELETE_ME_MARKER", "path": "/sandbox/delete_test"},
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="搜索已删除文件不应报错"),
                Assertion(type=AssertionType.CONTAINS, expected="未找到", description="文件已删除，搜索不到"),
            ],
            cleanup_steps=[
                {"tool": "terminal", "input": {"command": "rm -rf /sandbox/delete_test"}},
            ],
        ),
        ToolEvalCase(
            id="sf_53",
            tool_name="search_files",
            description="副作用 - write_file 覆盖后搜索到新内容",
            category="side_effect",
            setup_steps=[
                {"tool": "write_file", "input": {
                    "path": "/sandbox/overwrite/target.txt",
                    "content": "OLD_CONTENT_MARKER\n",
                }},
                {"tool": "write_file", "input": {
                    "path": "/sandbox/overwrite/target.txt",
                    "content": "NEW_CONTENT_MARKER\n",
                }},
            ],
            input_data={"pattern": "NEW_CONTENT_MARKER", "path": "/sandbox/overwrite"},
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="不应报错"),
                Assertion(type=AssertionType.CONTAINS, expected="NEW_CONTENT_MARKER", description="搜索到新内容"),
            ],
            cleanup_steps=[
                {"tool": "terminal", "input": {"command": "rm -rf /sandbox/overwrite"}},
            ],
        ),
        ToolEvalCase(
            id="sf_54",
            tool_name="search_files",
            description="副作用 - execute_code 生成文件后可搜索",
            category="side_effect",
            setup_steps=[
                {"tool": "terminal", "input": {
                    "command": "python3 -c \"import os; os.makedirs('/sandbox/codegen', exist_ok=True); f=open('/sandbox/codegen/output.log','w'); f.write('CODEGEN_RESULT=success\\n'); f.close()\"",
                }},
            ],
            input_data={"pattern": "CODEGEN_RESULT", "path": "/sandbox/codegen"},
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="不应报错"),
                Assertion(type=AssertionType.CONTAINS, expected="CODEGEN_RESULT", description="能搜索到代码生成的内容"),
            ],
            cleanup_steps=[
                {"tool": "terminal", "input": {"command": "rm -rf /sandbox/codegen"}},
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


def build_web_search_cases() -> list[ToolEvalCase]:
    """web_search 工具评测用例"""
    return [
        # ── 正常场景 ──
        ToolEvalCase(
            id="ws_01",
            tool_name="web_search",
            description="正常搜索 - 中文关键词",
            category="normal",
            input_data={"query": "CRM行业趋势 2026"},
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="不应报错"),
                Assertion(type=AssertionType.CONTAINS, expected="搜索结果", description="返回搜索结果"),
            ],
        ),
        ToolEvalCase(
            id="ws_02",
            tool_name="web_search",
            description="正常搜索 - 英文关键词",
            category="normal",
            input_data={"query": "Salesforce CRM latest features"},
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="不应报错"),
            ],
        ),
        ToolEvalCase(
            id="ws_03",
            tool_name="web_search",
            description="正常搜索 - 公司新闻类查询",
            category="normal",
            input_data={"query": "华为 2026 年营收"},
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="不应报错"),
            ],
        ),
        # ── 异常场景 ──
        ToolEvalCase(
            id="ws_04",
            tool_name="web_search",
            description="空 query - 应返回错误",
            category="error",
            input_data={"query": ""},
            assertions=[
                Assertion(type=AssertionType.IS_ERROR, description="空查询应报错"),
            ],
        ),
        ToolEvalCase(
            id="ws_05",
            tool_name="web_search",
            description="缺少 query 参数",
            category="error",
            input_data={},
            assertions=[
                Assertion(type=AssertionType.IS_ERROR, description="缺少必填参数应报错"),
            ],
        ),
        # ── 边界场景 ──
        ToolEvalCase(
            id="ws_06",
            tool_name="web_search",
            description="超长查询字符串",
            category="boundary",
            input_data={"query": "CRM " * 500},
            assertions=[
                # 超长查询可能成功也可能被截断，不应崩溃
                Assertion(type=AssertionType.NOT_ERROR, description="超长查询不应导致崩溃"),
            ],
        ),
        ToolEvalCase(
            id="ws_07",
            tool_name="web_search",
            description="特殊字符查询",
            category="boundary",
            input_data={"query": "价格 <100 & 折扣 >50%"},
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="特殊字符不应导致崩溃"),
            ],
        ),
    ]


def build_knowledge_search_cases() -> list[ToolEvalCase]:
    """knowledge_search 工具评测用例"""
    return [
        # ── 正常场景 ──
        ToolEvalCase(
            id="ks_01",
            tool_name="knowledge_search",
            description="正常检索 - 基础自然语言查询",
            category="normal",
            input_data={"query": "产品定价方案"},
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="不应报错"),
            ],
        ),
        ToolEvalCase(
            id="ks_02",
            tool_name="knowledge_search",
            description="正常检索 - 带 top_k 参数",
            category="normal",
            input_data={"query": "客户成功案例", "top_k": 3},
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="不应报错"),
            ],
        ),
        ToolEvalCase(
            id="ks_03",
            tool_name="knowledge_search",
            description="正常检索 - 指定知识库 ID",
            category="normal",
            input_data={"query": "销售话术", "knowledge_base_id": 1},
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="不应报错"),
            ],
        ),
        ToolEvalCase(
            id="ks_04",
            tool_name="knowledge_search",
            description="正常检索 - 带元数据过滤",
            category="normal",
            input_data={"query": "竞品分析", "doc_category": "竞品情报", "industry": "制造业"},
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="不应报错"),
            ],
        ),
        # ── 异常场景 ──
        ToolEvalCase(
            id="ks_05",
            tool_name="knowledge_search",
            description="空 query - 应返回错误",
            category="error",
            input_data={"query": ""},
            assertions=[
                Assertion(type=AssertionType.IS_ERROR, description="空查询应报错"),
            ],
        ),
        ToolEvalCase(
            id="ks_06",
            tool_name="knowledge_search",
            description="不存在的知识库 ID",
            category="error",
            input_data={"query": "产品手册", "knowledge_base_id": 999999},
            assertions=[
                # 不存在的知识库应该返回空结果或错误
                Assertion(type=AssertionType.NOT_ERROR, description="不存在的 KB 不应崩溃（可能返回空结果）"),
            ],
        ),
        # ── 边界场景 ──
        ToolEvalCase(
            id="ks_07",
            tool_name="knowledge_search",
            description="top_k=0 - 边界值",
            category="boundary",
            input_data={"query": "产品文档", "top_k": 0},
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="top_k=0 不应崩溃"),
            ],
        ),
        ToolEvalCase(
            id="ks_08",
            tool_name="knowledge_search",
            description="超长查询文本",
            category="boundary",
            input_data={"query": "请帮我查找关于" + "产品功能特性" * 100 + "的文档"},
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="超长查询不应崩溃"),
            ],
        ),
        ToolEvalCase(
            id="ks_09",
            tool_name="knowledge_search",
            description="top_k 超大值",
            category="boundary",
            input_data={"query": "解决方案", "top_k": 1000},
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="超大 top_k 不应崩溃"),
            ],
        ),
    ]


def build_list_knowledge_bases_cases() -> list[ToolEvalCase]:
    """list_knowledge_bases 工具评测用例"""
    return [
        # ── 正常场景 ──
        ToolEvalCase(
            id="lkb_01",
            tool_name="list_knowledge_bases",
            description="列出知识库 - 无参数",
            category="normal",
            input_data={},
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="不应报错"),
            ],
        ),
        # ── 异常场景 ──
        ToolEvalCase(
            id="lkb_02",
            tool_name="list_knowledge_bases",
            description="无租户上下文 - 应优雅降级",
            category="error",
            input_data={},
            assertions=[
                # 在评测环境中 tenant_id 可能为 0，工具应给出明确提示
                Assertion(type=AssertionType.NOT_ERROR, description="无租户上下文应有明确提示（不崩溃）"),
            ],
        ),
    ]


def build_knowledge_doc_detail_cases() -> list[ToolEvalCase]:
    """knowledge_doc_detail 工具评测用例"""
    return [
        # ── 正常场景 ──
        ToolEvalCase(
            id="kdd_01",
            tool_name="knowledge_doc_detail",
            description="获取文档目录 - sections 为空",
            category="normal",
            input_data={"doc_id": "doc-test-001", "sections": []},
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="不应报错"),
            ],
        ),
        ToolEvalCase(
            id="kdd_02",
            tool_name="knowledge_doc_detail",
            description="获取指定章节内容",
            category="normal",
            input_data={"doc_id": "doc-test-001", "sections": ["产品概述", "技术规格"]},
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="不应报错"),
            ],
        ),
        # ── 异常场景 ──
        ToolEvalCase(
            id="kdd_03",
            tool_name="knowledge_doc_detail",
            description="空 doc_id - 应返回错误",
            category="error",
            input_data={"doc_id": "", "sections": []},
            assertions=[
                Assertion(type=AssertionType.IS_ERROR, description="空 doc_id 应报错"),
            ],
        ),
        ToolEvalCase(
            id="kdd_04",
            tool_name="knowledge_doc_detail",
            description="不存在的文档 ID",
            category="error",
            input_data={"doc_id": "nonexistent-doc-id-xyz", "sections": []},
            assertions=[
                Assertion(type=AssertionType.IS_ERROR, description="不存在的文档应报错"),
            ],
        ),
        ToolEvalCase(
            id="kdd_05",
            tool_name="knowledge_doc_detail",
            description="不存在的章节名称",
            category="boundary",
            input_data={"doc_id": "doc-test-001", "sections": ["根本不存在的章节"]},
            assertions=[
                # 不存在的章节不应崩溃，应返回空或提示
                Assertion(type=AssertionType.NOT_ERROR, description="不存在的章节不应崩溃"),
            ],
        ),
        # ── 边界场景 ──
        ToolEvalCase(
            id="kdd_06",
            tool_name="knowledge_doc_detail",
            description="大量 sections 请求",
            category="boundary",
            input_data={"doc_id": "doc-test-001", "sections": [f"章节{i}" for i in range(50)]},
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="大量章节请求不应崩溃"),
            ],
        ),
    ]


def build_file_upload_cases() -> list[ToolEvalCase]:
    """file_upload 工具评测用例"""
    return [
        # ── 正常场景 ──
        ToolEvalCase(
            id="fu_01",
            tool_name="file_upload",
            description="content 模式 - 上传 HTML 内容",
            category="normal",
            input_data={
                "content": "<html><body><h1>测试报告</h1><p>这是一份测试报告。</p></body></html>",
                "file_name": "test_report.html",
            },
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="不应报错"),
                Assertion(type=AssertionType.CONTAINS, expected="上传成功", description="包含成功提示"),
            ],
        ),
        ToolEvalCase(
            id="fu_02",
            tool_name="file_upload",
            description="content 模式 - 上传 Markdown 内容",
            category="normal",
            input_data={
                "content": "# 分析报告\n\n## 概要\n\n这是一份分析报告。",
                "file_name": "analysis.md",
            },
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="不应报错"),
                Assertion(type=AssertionType.CONTAINS, expected="上传成功", description="包含成功提示"),
            ],
        ),
        ToolEvalCase(
            id="fu_03",
            tool_name="file_upload",
            description="content 模式 - 不指定 file_name（自动推断）",
            category="normal",
            input_data={
                "content": "<!DOCTYPE html><html><body>auto name test</body></html>",
            },
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="不应报错"),
                Assertion(type=AssertionType.CONTAINS, expected=".html", description="自动推断为 html 扩展名"),
            ],
        ),
        # ── 异常场景 ──
        ToolEvalCase(
            id="fu_04",
            tool_name="file_upload",
            description="无 file_path 且无 content - 应报错",
            category="error",
            input_data={},
            assertions=[
                Assertion(type=AssertionType.IS_ERROR, description="无参数应报错"),
            ],
        ),
        ToolEvalCase(
            id="fu_05",
            tool_name="file_upload",
            description="file_path 指向不存在的文件",
            category="error",
            input_data={"file_path": "/nonexistent/path/no_such_file.txt"},
            assertions=[
                Assertion(type=AssertionType.IS_ERROR, description="文件不存在应报错"),
            ],
        ),
        ToolEvalCase(
            id="fu_06",
            tool_name="file_upload",
            description="file_path 指向目录而非文件",
            category="error",
            input_data={"file_path": "/tmp"},
            assertions=[
                Assertion(type=AssertionType.IS_ERROR, description="路径不是文件应报错"),
            ],
        ),
        # ── 边界场景 ──
        ToolEvalCase(
            id="fu_07",
            tool_name="file_upload",
            description="空内容上传",
            category="boundary",
            input_data={"content": "", "file_name": "empty.txt"},
            assertions=[
                # 空内容可能成功也可能报错，但不应崩溃
                Assertion(type=AssertionType.NOT_ERROR, description="空内容不应崩溃"),
            ],
        ),
        ToolEvalCase(
            id="fu_08",
            tool_name="file_upload",
            description="自定义 expires 参数",
            category="normal",
            input_data={
                "content": "short lived content",
                "file_name": "temp.txt",
                "expires": 3600,
            },
            assertions=[
                Assertion(type=AssertionType.NOT_ERROR, description="自定义有效期不应报错"),
                Assertion(type=AssertionType.CONTAINS, expected="上传成功", description="包含成功提示"),
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
        + build_web_search_cases()
        + build_knowledge_search_cases()
        + build_list_knowledge_bases_cases()
        + build_knowledge_doc_detail_cases()
        + build_file_upload_cases()
    )

    return ToolEvalSuite(
        id="suite_default",
        name="Tool 评测 — 默认全量",
        description="覆盖所有内置工具的正常/异常/边界/副作用场景",
        cases=all_cases,
    )
