# macOS 服务远程访问配置指南

让远程电脑（包括虚拟机）能够访问 Mac 上运行的 HTTP 服务（如 `http://172.16.8.66:9119/sessions`）。

---

## 0. Hermes Agent 启动命令

### 基础对话模式

```bash
hermes              # 交互式终端对话
hermes --tui        # TUI 富界面模式
```

### Gateway + Dashboard（Web 界面）

```bash
# 启动 Gateway（后台服务，接收消息平台 + API 请求）
hermes gateway start

# 启动 Dashboard（Web 对话界面，默认端口 9119）
hermes dashboard
```

启动后浏览器打开 `http://localhost:9119` 即可使用 Web 对话界面。

### 让远程电脑访问 Dashboard

Dashboard 默认监听 `127.0.0.1`，需要改为 `0.0.0.0` 才能远程访问：

```bash
# 方式 1：环境变量
HERMES_DASHBOARD_HOST=0.0.0.0 hermes dashboard

# 方式 2：在 ~/.hermes/.env 中添加
HERMES_DASHBOARD_HOST=0.0.0.0
HERMES_DASHBOARD_PORT=9119
```

### API Server（供第三方 UI 接入）

在 `~/.hermes/.env` 中添加：

```bash
API_SERVER_ENABLED=true
API_SERVER_HOST=0.0.0.0
API_SERVER_KEY=你的密钥至少8位
```

然后启动 Gateway，API 端口为 `8642`：

```bash
hermes gateway start
```

远程电脑可通过 `http://172.16.8.66:8642/v1` 以 OpenAI 兼容格式调用。

### 常用命令速查

| 命令 | 用途 |
|------|------|
| `hermes` | 终端交互对话 |
| `hermes --tui` | TUI 富界面 |
| `hermes dashboard` | 启动 Web Dashboard (端口 9119) |
| `hermes gateway start` | 启动 Gateway 后台服务 (端口 8642) |
| `hermes gateway stop` | 停止 Gateway |
| `hermes model` | 切换 LLM 模型 |
| `hermes tools` | 管理工具集 |
| `hermes skills list` | 查看已安装 Skills |
| `hermes doctor` | 诊断问题 |
| `hermes update` | 更新到最新版本 |

### Skills 管理

#### 查看已安装的 Skills

```bash
# 列出所有 skill
hermes skills list

# 或在对话中
/skills
```

#### 查看 Skill 存储位置

```bash
ls ~/.hermes/skills/
```

#### 查看某个 Skill 详情

```
# 在对话中
/skills list
```

或直接用 slash 命令加载某个 skill：

```
/plan
/github-pr-workflow
```

#### 验证 Skill 命令确实在虚拟机执行

进入 hermes 对话，试试：

```
/plan 写一个 Python hello world 脚本并运行它
```

Agent 会根据 Skill 指令生成 terminal 命令，通过 SSH 在虚拟机上执行。可以验证：

```
运行 whoami && hostname
```

返回的应该是虚拟机的用户名和主机名，而不是 Mac 的。

---

## 1. 确认服务监听地址

服务必须监听 `0.0.0.0`（所有网卡），而不是 `127.0.0.1`（仅本机）。

### 检查当前监听状态

```bash
lsof -i :9119
```

如果输出中显示 `127.0.0.1:9119` 或 `localhost:9119`，说明服务只接受本机连接，需要修改。

### 修改监听地址

**uvicorn（FastAPI / Starlette）：**

```bash
uvicorn server:app --host 0.0.0.0 --port 9119
```

**Python http.server：**

```bash
python -m http.server 9119 --bind 0.0.0.0
```

**Flask：**

```python
app.run(host="0.0.0.0", port=9119)
```

**Node.js / Express：**

```javascript
app.listen(9119, '0.0.0.0')
```

---

## 2. macOS 防火墙配置

### 检查防火墙状态

```bash
sudo /usr/libexec/ApplicationFirewall/socketfilterfw --getglobalstate
```

### 方案 A：临时关闭防火墙（快速验证）

```bash
sudo /usr/libexec/ApplicationFirewall/socketfilterfw --setglobalstate off
```

验证完成后记得重新开启：

```bash
sudo /usr/libexec/ApplicationFirewall/socketfilterfw --setglobalstate on
```

### 方案 B：添加应用例外（推荐）

通过 GUI：系统设置 → 网络 → 防火墙 → 选项 → 添加应用程序例外

通过命令行：

```bash
# 添加 Python 为允许的应用
sudo /usr/libexec/ApplicationFirewall/socketfilterfw --add /usr/local/bin/python3
sudo /usr/libexec/ApplicationFirewall/socketfilterfw --unblockapp /usr/local/bin/python3
```

---

## 3. 验证网络连通性

从远程电脑执行以下命令：

### 测试网络可达

```bash
ping 172.16.8.66
```

### 测试端口连通

```bash
# 方式 1: telnet
telnet 172.16.8.66 9119

# 方式 2: nc
nc -zv 172.16.8.66 9119

# 方式 3: curl（直接测试 HTTP）
curl http://172.16.8.66:9119/sessions
```

### 结果判断

| 现象 | 原因 | 解决方案 |
|:---|:---|:---|
| ping 不通 | 不在同一子网 / VLAN 隔离 | 检查网络拓扑，联系网管 |
| ping 通，端口不通 | 防火墙拦截 | 参考第 2 步 |
| 端口通，HTTP 无响应 | 服务绑定了 127.0.0.1 | 参考第 1 步 |
| 连接被拒绝 (Connection refused) | 服务未启动或端口错误 | 检查服务进程 |

---

## 4. 跨子网 / VPN 场景

如果远程电脑和 Mac 不在同一局域网，可以使用以下方案：

### 方案 A：ngrok 内网穿透（最快验证）

```bash
# 安装
brew install ngrok

# 暴露本地端口
ngrok http 9119
```

ngrok 会生成一个公网 URL（如 `https://xxxx.ngrok.io`），远程电脑直接访问该 URL。

### 方案 B：SSH 反向隧道

前提：远程电脑能 SSH 到 Mac，或 Mac 能 SSH 到远程电脑。

```bash
# 在 Mac 上执行（将本地 9119 映射到远程机器的 9119）
ssh -R 9119:localhost:9119 user@remote-machine
```

远程机器上访问 `http://localhost:9119/sessions` 即可。

### 方案 C：frp 内网穿透（长期使用）

适合没有公网 IP 但需要稳定暴露服务的场景，需要一台有公网 IP 的服务器作为中转。

---

## 5. 快速排查清单

```bash
# 1. 确认服务在运行
lsof -i :9119

# 2. 确认监听 0.0.0.0
netstat -an | grep 9119

# 3. 本机测试
curl http://localhost:9119/sessions

# 4. 确认 Mac IP
ifconfig | grep "inet " | grep -v 127.0.0.1

# 5. 检查防火墙
sudo /usr/libexec/ApplicationFirewall/socketfilterfw --getglobalstate
```

---

## 6. 新电脑远程访问虚拟机 SSH 配置

场景：新电脑 (172.17.2.93) 需要通过 SSH 访问虚拟机 (172.17.2.118)。

### 在新电脑上执行

#### 6.1 生成 SSH 密钥

```bash
ssh-keygen -t ed25519 -f ~/.ssh/hermes_vm_key -C "hermes-agent"
```

#### 6.2 传公钥到虚拟机

```bash
ssh-copy-id -i ~/.ssh/hermes_vm_key.pub hermes@172.17.2.118
```

输入密码 `a12345678`。

#### 6.3 验证免密登录

```bash
ssh -i ~/.ssh/hermes_vm_key hermes@172.17.2.118 "echo 连接成功"
```

#### 6.4 配置 Hermes（如果新电脑也装了 Hermes）

```yaml
# ~/.hermes/config.yaml
terminal:
  backend: ssh
```

```bash
# ~/.hermes/.env
TERMINAL_SSH_HOST=172.17.2.118
TERMINAL_SSH_USER=hermes
TERMINAL_SSH_KEY=~/.ssh/hermes_vm_key
```

> 虚拟机的 SSH 服务支持多个公钥同时授权，Mac 和新电脑的公钥分别存在虚拟机的 `/sandbox/.ssh/authorized_keys` 文件中，互不影响。

---

## 常见问题

**Q: 改了 0.0.0.0 还是访问不了？**

A: 检查是否有多层代理。如果用了 Docker，需要 `-p 9119:9119` 映射端口。

**Q: 重启后配置丢失？**

A: 将启动命令写入启动脚本或 systemd/launchd 配置，确保 `--host 0.0.0.0` 参数持久化。

**Q: 只想让特定 IP 访问？**

A: 在应用层或 nginx 反向代理中配置 IP 白名单，而不是依赖防火墙。
