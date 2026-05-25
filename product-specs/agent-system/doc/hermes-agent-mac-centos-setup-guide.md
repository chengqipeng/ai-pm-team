# Hermes Agent 安装配置指南：Mac + CentOS 虚拟机

## 部署拓扑

```
┌─────────────────────┐              SSH              ┌─────────────────────┐
│  Mac (大脑)          │  ─────────────────────────▶  │  CentOS 虚拟机 (手脚) │
│                     │                              │                     │
│  • Hermes Agent     │                              │  • 执行所有命令      │
│  • LLM API 调用     │                              │  • 文件操作          │
│  • Gateway 收消息   │                              │  • 代码运行          │
│  • 会话/记忆存储    │                              │  • 随便折腾不怕搞坏  │
└─────────────────────┘                              └─────────────────────┘

虚拟机 IP: 192.168.56.101
```

---

## 第一步：CentOS 虚拟机准备

### 1.1 安装并启动 SSH 服务

```bash
# CentOS 通常已预装 openssh-server，确认一下
sudo yum install -y openssh-server

# 启动并设置开机自启
sudo systemctl start sshd
sudo systemctl enable sshd

# 确认运行状态
sudo systemctl status sshd
```

### 1.2 创建专用用户

```bash
# 创建 hermes 用户
sudo useradd -m -s /bin/bash hermes

# 设置密码
echo "a12345678" | sudo passwd --stdin hermes
```

### 1.3 开放防火墙

```bash
# 检查防火墙状态
sudo firewall-cmd --state

# 如果是 running，放行 SSH
sudo firewall-cmd --permanent --add-service=ssh
sudo firewall-cmd --reload
```

如果用的是 iptables：

```bash
sudo iptables -I INPUT -p tcp --dport 22 -j ACCEPT
sudo service iptables save
```

### 1.4 检查 SELinux（CentOS 特有）

```bash
# 查看状态
getenforce

# 如果是 Enforcing 且 SSH 连不上，临时关闭排查
sudo setenforce 0

# 永久关闭（可选，生产环境不建议）
sudo sed -i 's/SELINUX=enforcing/SELINUX=permissive/' /etc/selinux/config
```

### 1.5 确认虚拟机 IP

```bash
ip addr show | grep inet
# 或
hostname -I
# 本例中为 192.168.56.101
```

---

## 第二步：Mac 上安装 Hermes Agent

### 2.1 安装 Hermes

```bash
curl -fsSL https://raw.githubusercontent.com/NousResearch/hermes-agent/main/scripts/install.sh | bash
source ~/.zshrc
hermes setup  # 完成初始配置（选 LLM provider 等）
```

### 2.2 安装 Node.js（Dashboard 需要）

```bash
brew install node
```

---

## 第三步：Mac 上配置 SSH 免密登录

### 3.1 生成密钥

```bash
ssh-keygen -t ed25519 -f ~/.ssh/hermes_vm_key -C "hermes-agent"
```

### 3.2 传公钥到虚拟机

```bash
ssh-copy-id -i ~/.ssh/hermes_vm_key.pub hermes@192.168.56.101
```

输入密码 `a12345678` 完成传输。

### 3.3 验证免密登录

```bash
ssh -i ~/.ssh/hermes_vm_key hermes@192.168.56.101 "echo 连接成功"
```

---

## 第四步：配置 Hermes 使用 SSH 后端

### 4.1 修改 config.yaml

```bash
nano ~/.hermes/config.yaml
```

找到 `terminal:` 部分，修改为：

```yaml
terminal:
  backend: ssh
```

保存：`Ctrl+O` → 回车 → `Ctrl+X` 退出。

### 4.2 配置 SSH 连接信息

```bash
echo 'TERMINAL_SSH_HOST=192.168.56.101' >> ~/.hermes/.env
echo 'TERMINAL_SSH_USER=hermes' >> ~/.hermes/.env
echo 'TERMINAL_SSH_KEY=~/.ssh/hermes_vm_key' >> ~/.hermes/.env
```

---

## 第五步：验证

```bash
hermes
```

进入对话后输入：

```
运行 whoami && hostname && cat /etc/centos-release
```

预期返回：
- `hermes`（虚拟机上的用户名）
- 虚拟机的主机名
- CentOS 版本信息

---

## 第六步（可选）：启动 Web Dashboard

### 6.1 构建 Web UI

```bash
cd ~/.hermes/hermes-agent/web && npm install && npm run build
```

> ⚠️ 注意：不要用 `sudo` 执行 npm 命令。如果遇到权限问题，先清理缓存：
> ```bash
> sudo rm -rf ~/.npm/_cacache
> ```
> 然后重新执行上面的命令。

### 6.2 启动 Dashboard

```bash
hermes dashboard
```

浏览器打开 `http://localhost:9119`。

---

## 常见问题

| 问题 | 解决方案 |
|------|----------|
| SSH 连接超时 | 检查虚拟机防火墙 `sudo firewall-cmd --list-all` |
| Permission denied (SSH) | 检查 `/home/hermes/.ssh/authorized_keys` 权限为 600 |
| SELinux 阻止 SSH | `sudo restorecon -Rv /home/hermes/.ssh` |
| 命令仍在 Mac 本地执行 | 确认 `config.yaml` 中 `backend: ssh`，不是 `local` |
| npm install 权限错误 | `sudo rm -rf ~/.npm/_cacache` 后不带 sudo 重新执行 |
| passwd 拒绝简单密码 | 用 `echo "密码" \| sudo passwd --stdin hermes` |

---

## 界面选项

| 方式 | 命令 | 说明 |
|------|------|------|
| 终端对话 | `hermes` | 默认交互模式 |
| TUI 界面 | `hermes --tui` | 带多行编辑、语法高亮 |
| Web Dashboard | `hermes dashboard` | 浏览器可视化界面 |
| 消息平台 | `hermes gateway start` | Telegram/Discord/微信等 |
