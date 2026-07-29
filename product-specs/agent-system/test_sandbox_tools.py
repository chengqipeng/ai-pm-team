"""
沙盒工具测试用例 — 10 个用户问题场景验证 5 个新增 Tools

验证工具:
  1. terminal — Shell 命令执行
  2. execute_code — 代码片段执行
  3. read_file — 远程文件读取
  4. write_file — 远程文件写入
  5. search_files — 文件内容搜索

使用方法:
    python test_sandbox_tools.py

无需远程连接，使用 Mock Backend 验证工具逻辑。
"""
import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

from src.tools.sandbox.backend_base import Backend, BackendConfig, ExecutionResult
from src.tools.sandbox.terminal_tool import TerminalTool
from src.tools.sandbox.code_execution_tool import CodeExecutionTool
from src.tools.sandbox.file_tools import ReadFileTool, WriteFileTool, SearchFilesTool


# ─── Mock Backend ───

class MockBackend(Backend):
    """模拟后端 — 不需要真实 SSH 连接，验证工具逻辑"""

    def __init__(self):
        config = BackendConfig(backend_type="mock")
        super().__init__(config)
        self._connected = False
        self._filesystem = {}  # 模拟文件系统
        self._env = {}  # 模拟环境变量

    @property
    def is_connected(self) -> bool:
        return self._connected

    async def connect(self) -> None:
        self._connected = True

    async def disconnect(self) -> None:
        self._connected = False

    async def execute(self, command: str, timeout: int | None = None) -> ExecutionResult:
        """模拟命令执行"""
        # 模拟超时
        if timeout and timeout <= 0:
            return ExecutionResult(stdout="", stderr="超时", exit_code=-1, timed_out=True)

        # 模拟各种命令
        if "echo $HOSTNAME" in command:
            return ExecutionResult(stdout="sandbox-a1-abc123", exit_code=0)
        elif command.startswith("cat ") and ">" not in command:
            path = command.split()[-1].strip("'\"")
            if path in self._filesystem:
                return ExecutionResult(stdout=self._filesystem[path], exit_code=0)
            return ExecutionResult(stderr=f"cat: {path}: No such file or directory", exit_code=1)
        elif "cat >" in command or "cat >>" in command:
            # heredoc 写入
            parts = command.split(">")
            if len(parts) >= 2:
                path = parts[1].split("<<")[0].strip().strip("'\"")
                # 提取 heredoc 内容
                lines = command.split("\n")
                content = "\n".join(lines[1:-1]) if len(lines) > 2 else ""
                self._filesystem[path] = content
            return ExecutionResult(stdout="", exit_code=0)
        elif command.startswith("test -e"):
            path = command.split("'")[1] if "'" in command else command.split()[-4]
            if path in self._filesystem:
                return ExecutionResult(stdout="yes", exit_code=0)
            return ExecutionResult(stdout="no", exit_code=0)
        elif command.startswith("mkdir -p"):
            return ExecutionResult(stdout="", exit_code=0)
        elif command.startswith("rm -f"):
            path = command.replace("rm -f ", "").strip()
            self._filesystem.pop(path, None)
            return ExecutionResult(stdout="", exit_code=0)
        elif command.startswith("grep"):
            # 模拟搜索 — 解析 grep -rn --color=never [--include '*.py'] PATTERN PATH
            # shlex.split 正确处理引号
            import shlex as _shlex
            try:
                parts = _shlex.split(command)
            except ValueError:
                parts = command.split()
            # 过滤掉 grep 本身、选项和选项值
            args = []
            skip_next = False
            for p in parts[1:]:  # 跳过 'grep'
                if skip_next:
                    skip_next = False
                    continue
                if p.startswith("-"):
                    # --include 等带值选项
                    if p in ("--include", "--exclude"):
                        skip_next = True
                    continue
                args.append(p)
            # args 应该是 [pattern, path]
            pattern = args[0] if args else None
            results = []
            for fpath, content in self._filesystem.items():
                for i, line in enumerate(content.split("\n"), 1):
                    if pattern and pattern in line:
                        results.append(f"{fpath}:{i}:{line}")
            if results:
                return ExecutionResult(stdout="\n".join(results), exit_code=0)
            return ExecutionResult(stdout="", exit_code=1)
        elif "python3" in command:
            # 模拟 Python 执行
            script_path = command.split()[-1]
            code = self._filesystem.get(script_path, "")
            if "print" in code:
                # 简单模拟 print 输出
                return ExecutionResult(stdout="Hello, World!\n42\n", exit_code=0)
            elif "raise" in code or "1/0" in code:
                return ExecutionResult(
                    stderr="Traceback (most recent call last):\n  ZeroDivisionError: division by zero",
                    exit_code=1,
                )
            return ExecutionResult(stdout="", exit_code=0)
        elif "node" in command:
            script_path = command.split()[-1]
            return ExecutionResult(stdout="[1, 2, 3, 4, 5]\n", exit_code=0)
        elif command.startswith("sed -n"):
            # 模拟行范围读取
            return ExecutionResult(stdout="line 10\nline 11\nline 12\n", exit_code=0)
        elif "df -h" in command:
            return ExecutionResult(
                stdout="Filesystem      Size  Used Avail Use% Mounted on\n/dev/sda1       50G   12G   38G  24% /\n",
                exit_code=0,
            )
        elif "pip install" in command:
            pkg = command.split("install")[-1].strip()
            return ExecutionResult(stdout=f"Successfully installed {pkg}\n", exit_code=0)
        elif ":(){ :|:& };:" in command:
            return ExecutionResult(stderr="bash: fork: retry: Resource temporarily unavailable", exit_code=1)
        elif "mount" in command:
            return ExecutionResult(stderr="mount: permission denied", exit_code=1)

        return ExecutionResult(stdout=f"[mock] executed: {command[:50]}", exit_code=0)

    async def write_file(self, path: str, content: str) -> ExecutionResult:
        self._filesystem[path] = content
        return ExecutionResult(stdout="", exit_code=0)

    async def read_file(self, path: str) -> ExecutionResult:
        if path in self._filesystem:
            return ExecutionResult(stdout=self._filesystem[path], exit_code=0)
        return ExecutionResult(stderr=f"No such file: {path}", exit_code=1)

    async def file_exists(self, path: str) -> bool:
        return path in self._filesystem


# ─── 10 个用户问题测试用例 ───

TEST_CASES = [
    # ── 用例 1: terminal — 基础系统命令 ──
    {
        "id": 1,
        "user_question": "帮我看看服务器的磁盘使用情况",
        "tool": "terminal",
        "input": {"command": "df -h"},
        "expect_error": False,
        "expect_contains": "Filesystem",
        "description": "用户查看磁盘 → terminal 执行 df -h",
    },
    # ── 用例 2: terminal — 空命令校验 ──
    {
        "id": 2,
        "user_question": "执行一下命令",
        "tool": "terminal",
        "input": {"command": ""},
        "expect_error": True,
        "expect_contains": "命令不能为空",
        "description": "用户未给出具体命令 → 返回错误提示",
    },
    # ── 用例 3: terminal — 危险命令检测 ──
    {
        "id": 3,
        "user_question": "清理一下根目录",
        "tool": "terminal",
        "input": {"command": "rm -rf /"},
        "expect_destructive": True,
        "expect_error": False,
        "description": "用户请求危险操作 → is_destructive 返回 True",
    },
    # ── 用例 4: execute_code — Python 代码执行 ──
    {
        "id": 4,
        "user_question": "帮我写个 Python 脚本计算 1+1 并打印结果",
        "tool": "execute_code",
        "input": {"language": "python", "code": "print('Hello, World!')\nprint(42)"},
        "expect_error": False,
        "expect_contains": "Hello, World!",
        "description": "用户要求执行 Python → execute_code 写入临时文件并运行",
    },
    # ── 用例 5: execute_code — 不支持的语言 ──
    {
        "id": 5,
        "user_question": "帮我跑一段 Rust 代码",
        "tool": "execute_code",
        "input": {"language": "rust", "code": "fn main() { println!(\"hi\"); }"},
        "expect_error": True,
        "expect_contains": "不支持的语言",
        "description": "用户请求不支持的语言 → 返回错误和支持列表",
    },
    # ── 用例 6: write_file — 创建新文件 ──
    {
        "id": 6,
        "user_question": "帮我创建一个 main.py，内容是 hello world",
        "tool": "write_file",
        "input": {"path": "/sandbox/app/main.py", "content": "print('hello world')\n"},
        "expect_error": False,
        "expect_contains": "已写入",
        "description": "用户要求创建文件 → write_file 写入并确认",
    },
    # ── 用例 7: read_file — 读取已存在的文件 ──
    {
        "id": 7,
        "user_question": "帮我看看 main.py 的内容",
        "tool": "read_file",
        "input": {"path": "/sandbox/app/main.py"},
        "expect_error": False,
        "expect_contains": "hello world",
        "description": "用户读取文件 → read_file 返回内容",
        "setup_files": {"/sandbox/app/main.py": "print('hello world')\n"},
    },
    # ── 用例 8: read_file — 文件不存在 ──
    {
        "id": 8,
        "user_question": "帮我看看 config.yaml 的内容",
        "tool": "read_file",
        "input": {"path": "/sandbox/app/config.yaml"},
        "expect_error": True,
        "expect_contains": "文件不存在",
        "description": "用户读取不存在的文件 → 返回文件不存在错误",
    },
    # ── 用例 9: search_files — 搜索代码中的 TODO ──
    {
        "id": 9,
        "user_question": "帮我找一下代码里所有的 TODO 注释",
        "tool": "search_files",
        "input": {"pattern": "TODO", "path": ".", "include": "*.py"},
        "expect_error": False,
        "expect_contains": "TODO",
        "description": "用户搜索 TODO → search_files 用 grep 递归搜索",
        "setup_files": {
            "/sandbox/app/main.py": "# TODO: add error handling\nprint('hello')\n",
            "/sandbox/app/utils.py": "# TODO: refactor this\ndef helper(): pass\n",
        },
    },
    # ── 用例 10: search_files — 搜索无结果 ──
    {
        "id": 10,
        "user_question": "帮我找一下代码里有没有 FIXME",
        "tool": "search_files",
        "input": {"pattern": "FIXME", "path": "."},
        "expect_error": False,
        "expect_contains": "未找到匹配内容",
        "description": "用户搜索不存在的模式 → 返回未找到",
    },
]


async def run_single_test(case: dict) -> dict:
    """执行单个测试用例"""
    backend = MockBackend()
    await backend.connect()

    # 预置文件（如果有）
    if "setup_files" in case:
        for path, content in case["setup_files"].items():
            backend._filesystem[path] = content

    # 创建对应工具
    tool_map = {
        "terminal": TerminalTool(backend),
        "execute_code": CodeExecutionTool(backend),
        "read_file": ReadFileTool(backend),
        "write_file": WriteFileTool(backend),
        "search_files": SearchFilesTool(backend),
    }

    tool = tool_map[case["tool"]]
    input_data = case["input"]

    # 检查 is_destructive（用例 3 特殊验证）
    if "expect_destructive" in case:
        is_destructive = tool.is_destructive(input_data)
        return {
            "pass": is_destructive == case["expect_destructive"],
            "detail": f"is_destructive={is_destructive}, expected={case['expect_destructive']}",
        }

    # 执行工具
    result = await tool.call(input_data)

    # 验证
    error_match = result.is_error == case["expect_error"]
    content_match = case["expect_contains"] in result.content

    passed = error_match and content_match
    detail = f"is_error={result.is_error}(expect={case['expect_error']}), content_match={content_match}"
    if not passed:
        detail += f"\n     实际输出: {result.content[:200]}"

    return {"pass": passed, "detail": detail}


async def main():
    print("=" * 70)
    print("  沙盒工具测试 — 10 个用户问题场景验证新增 Tools")
    print("  工具: terminal / execute_code / read_file / write_file / search_files")
    print("=" * 70)

    total = len(TEST_CASES)
    passed = 0
    failures = []

    for case in TEST_CASES:
        result = await run_single_test(case)

        status = "✅" if result["pass"] else "❌"
        if result["pass"]:
            passed += 1
        else:
            failures.append(case["id"])

        print(f"\n  {status} 用例 {case['id']:2d} [{case['tool']:12s}] {case['description']}")
        print(f"     用户问题: \"{case['user_question']}\"")
        print(f"     工具输入: {case['input']}")
        print(f"     验证结果: {result['detail']}")

    # 汇总
    print(f"\n{'=' * 70}")
    print(f"  结果: {passed}/{total} 通过 ({passed/total*100:.0f}%)")
    if failures:
        print(f"  失败用例: {failures}")
    else:
        print("  🎉 全部通过！")
    print("=" * 70)

    return passed == total


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
