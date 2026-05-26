# 腾讯云 Agent Runtime 沙箱环境 API 分析

> 来源: [腾讯云 Agent Runtime SDK 使用指南](https://cloud.tencent.com/document/product/1814/130978)

## 一、产品概述

腾讯云 Agent Runtime（Agent 沙箱服务）提供基于 E2B 协议兼容的沙箱环境，支持代码执行、浏览器操作、终端命令等能力。核心特点：

- **兼容 E2B SDK**（需 2.0+ 版本），可复用 E2B 工作流
- 服务域名: `ap-guangzhou.tencentags.com`
- 通过 API Key 认证

## 二、环境配置

### 必需环境变量

```bash
E2B_DOMAIN=ap-guangzhou.tencentags.com
E2B_API_KEY=ark_dGTlMcosC-n-ZNhfKyW8aBJm3c0KNLXzjSkT7t_3WWc
```

### 配置方式（三选一）

**方式1: .env 文件（推荐）**
```
E2B_DOMAIN=ap-guangzhou.tencentags.com
E2B_API_KEY=ark_dGTlMcosC-n-ZNhfKyW8aBJm3c0KNLXzjSkT7t_3WWc
```

```python
from dotenv import load_dotenv
load_dotenv()
```

**方式2: 终端环境变量**
```bash
export E2B_DOMAIN=ap-guangzhou.tencentags.com
export E2B_API_KEY=ark_dGTlMcosC-n-ZNhfKyW8aBJm3c0KNLXzjSkT7t_3WWc
```

**方式3: 代码内嵌**
```python
import os
os.environ["E2B_DOMAIN"] = "ap-guangzhou.tencentags.com"
os.environ["E2B_API_KEY"] = "ark_dGTlMcosC-n-ZNhfKyW8aBJm3c0KNLXzjSkT7t_3WWc"
```

## 三、沙箱类型

| 沙箱类型 | template 名称 | 主要能力 |
|---------|-------------|---------|
| 代码解释器 | `code-interpreter-v1` | Python/JS 代码执行 |
| 浏览器沙箱 | `browser-v1` | Chromium 浏览器操作 |
| All-In-One | `all-in-one-v1`（自定义） | 代码+浏览器+终端+VSCode 全合一 |

### All-In-One 沙箱端口/服务

| 能力 | 端口/路径 | 说明 |
|-----|----------|------|
| 代码执行 | 49999 | 兼容 E2B 协议，支持 Python/JS 等 |
| 远程浏览器 | 9000/novnc/ | VNC 可视化界面 |
| VSCode 编辑器 | 9000/vscode/ | code-server Web IDE |
| WebShell 终端 | 9000/ttyd/ | 网页终端 |
| 终端 & 文件系统 | 49983 | 文件系统与命令执行接口 |

## 四、核心 API 操作

### 4.1 创建沙箱实例

```python
from e2b import Sandbox

# 基础创建
sandbox = Sandbox.create(template="all-in-one-v1", timeout=3600)

# 代码解释器沙箱
from e2b_code_interpreter import Sandbox as CodeSandbox
sandbox = CodeSandbox.create()  # 默认 template="code-interpreter-v1"

# 指定超时（秒），超时后自动销毁
sandbox = Sandbox.create(template="code-interpreter-v1", timeout=300)
```

### 4.2 获取沙箱信息

```python
# 获取实例信息
info = sandbox.get_info()
# 返回: sandbox_id, template_id, name, state, started_at, end_at 等

# 获取 access token（用于拼接 URL）
token = sandbox._envd_access_token

# 获取服务 host
host = sandbox.get_host(9000)
```

### 4.3 获取各服务访问地址（All-In-One）

```python
token = sandbox._envd_access_token
host = sandbox.get_host(9000)

# 服务导航首页
index_url = f"https://{host}/?access_token={token}"

# NoVNC 远程桌面
novnc_url = f"https://{host}/novnc/vnc_lite.html?access_token={token}&path=websockify%3Faccess_token%3D{token}"

# VSCode Web IDE
vscode_url = f"https://{host}/vscode-sw-boot.html?access_token={token}"

# WebShell 终端
ttyd_url = f"https://{host}/ttyd/?access_token={token}"
```

### 4.4 执行终端命令

```python
# 基础命令执行
response = sandbox.commands.run("ls")

# 指定用户身份
response = sandbox.commands.run("ls", user="root")

# 流式返回
sandbox.commands.run(
    "echo hello && sleep 1 && echo world",
    on_stdout=lambda data: print(data),
    on_stderr=lambda data: print(data)
)

# 后台执行
handler = sandbox.commands.run("long_running_script.sh", background=True)
response = handler.wait(on_stdout=lambda data: print(data))

# 发送 stdin
handler = sandbox.commands.run("read input && echo $input", background=True)
sandbox.commands.send_stdin(handler.pid, "hello\n")

# 列出/终止后台命令
command_list = sandbox.commands.list()
sandbox.commands.kill(command.pid)
```

### 4.5 代码执行（Jupyter）

```python
from e2b_code_interpreter import Sandbox

sandbox = Sandbox.create()

# 执行 Python（默认）
response = sandbox.run_code("print('hello')")

# 执行其他语言: javascript, typescript, java, r, bash
response = sandbox.run_code("console.log('hello')", "javascript")

# 创建独立上下文（共享变量）
ctx = sandbox.create_code_context(language="python")
response = sandbox.run_code("x = 1", context=ctx)
response = sandbox.run_code("print(x)", context=ctx)  # 输出 1

# 流式返回
sandbox.run_code(
    code,
    on_stdout=lambda data: print(data),
    on_stderr=lambda data: print(data),
    on_result=lambda data: print(data),
    on_error=lambda data: print(data)
)

# 指定环境变量和超时
response = sandbox.run_code("print('hello')", envs={"foo": "bar"}, timeout=60)
```

### 4.6 浏览器操作（Playwright）

```python
from e2b import Sandbox
from playwright.sync_api import sync_playwright

# 创建浏览器沙箱（或 All-In-One）
sandbox = Sandbox.create(template="browser-v1")

# 拼接 live url（可视化查看）
live_url = f"https://{sandbox.get_host(9000)}/novnc/vnc_lite.html?access_token={sandbox._envd_access_token}&path=websockify%3Faccess_token%3D{sandbox._envd_access_token}"

# 拼接 CDP url（程序化操控）
cdp_url = f"https://{sandbox.get_host(9000)}/cdp?access_token={sandbox._envd_access_token}"

# 使用 Playwright 操控浏览器
with sync_playwright() as playwright:
    browser = playwright.chromium.connect_over_cdp(
        cdp_url,
        headers={"X-Access-Token": str(sandbox._envd_access_token)}
    )
    context = browser.contexts[0]
    page = context.pages[0]
    page.goto("http://www.tencent.com")
    print(page.title())
```

### 4.7 沙箱实例管理

```python
# 列出所有沙箱实例（分页）
paginator = Sandbox.list()
while paginator.has_next:
    page = paginator.next_items()
    for sandbox_info in page:
        print(sandbox_info)

# 指定分页大小
paginator = Sandbox.list(limit=5)

# 删除沙箱实例
sandbox.kill()
```

## 五、All-In-One 沙箱预装内容

### Python 包
| 包 | 用途 |
|---|------|
| playwright | 浏览器自动化 |
| selenium | WebDriver 浏览器自动化 |
| pyautogui | GUI 自动化（鼠标/键盘） |
| pillow | 图像处理与截图 |
| anthropic | Claude SDK |
| openai | OpenAI SDK |
| langchain | LLM 应用框架 |

### Node.js 包
| 包 | 用途 |
|---|------|
| playwright | 浏览器自动化 |
| puppeteer | 浏览器自动化（系统 Chromium） |
| @anthropic-ai/sdk | Claude SDK |
| openai | OpenAI SDK |
| @anthropic-ai/claude-code | Claude Code CLI |
| @openai/codex | OpenAI Codex CLI |
| @google/gemini-cli | Gemini CLI |

## 六、快速开始示例

### 完整创建 All-In-One 沙箱并使用

```python
import os
from e2b import Sandbox

# 配置环境
os.environ["E2B_DOMAIN"] = "ap-guangzhou.tencentags.com"
os.environ["E2B_API_KEY"] = "ark_dGTlMcosC-n-ZNhfKyW8aBJm3c0KNLXzjSkT7t_3WWc"

# 创建 All-In-One 沙箱（需先在控制台创建对应沙箱工具）
sandbox = Sandbox.create(template="all-in-one-v1", timeout=3600)

# 获取访问地址
token = sandbox._envd_access_token
host = sandbox.get_host(9000)
print(f"首页: https://{host}/?access_token={token}")
print(f"VSCode: https://{host}/vscode-sw-boot.html?access_token={token}")
print(f"终端: https://{host}/ttyd/?access_token={token}")

# 执行命令
result = sandbox.commands.run("python --version")
print(result)

# 执行代码
from e2b_code_interpreter import Sandbox as CodeSandbox
code_sandbox = CodeSandbox.create()
response = code_sandbox.run_code("import sys; print(sys.version)")
print(response)

# 清理
sandbox.kill()
```

## 七、注意事项

1. **前置条件**: 使用 All-In-One 沙箱前，需在 [Agent 沙箱服务控制台](https://console.cloud.tencent.com/ags/sandbox?rid=1) 创建对应名称的沙箱工具（自定义镜像）
2. **SDK 版本**: 需使用 E2B SDK 2.0 及以上版本
3. **参数限制**: `create` 的 `metadata`, `envs`, `secure`, `allow_internet_access` 参数暂不可用
4. **超时机制**: 沙箱运行时间超过 timeout 后自动销毁
5. **依赖安装**: `pip install e2b e2b-code-interpreter python-dotenv playwright`

## 八、API Key 信息

- **API Key**: `ark_dGTlMcosC-n-ZNhfKyW8aBJm3c0KNLXzjSkT7t_3WWc`
- **域名**: `ap-guangzhou.tencentags.com`
- **认证方式**: 通过 `E2B_API_KEY` 环境变量传递
