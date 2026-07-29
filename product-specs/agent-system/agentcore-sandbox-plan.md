# AgentCore 沙箱方案（对标腾讯云 Agent Runtime/AGS）

> 2026-07-02/03 在 AWS p10（ap-southeast-1）真机验证；配套验证脚本 `test_agentcore_sandbox.py`

## 1. 背景与目标

现状：沙箱能力跑在腾讯云 Agent Runtime（AGS）上——自定义镜像 code-sandbox 工具，E2B SDK 按需拉沙箱执行代码，COS 挂载 `/sandbox/.skills`，创建时传 `subPath=session_id` 实现会话级目录隔离。

目标：评估 AWS Bedrock AgentCore 能否承接同样的能力。三个硬需求：

1. 按需拉起沙箱执行任意代码，用完销毁
2. 不同沙箱（session）的工作目录互相隔离
3. 工作目录文件落到自己的对象存储（S3），外部程序/用户可直接访问

## 2. 结论

**可承接。** 推荐形态：**AgentCore Code Interpreter（内置沙箱）+ 显式 sync 落 S3**。

- 用法模型与现在 E2B 一致：`start() → invoke(executeCommand/executeCode) → stop()`
- 隔离由平台自带（每会话独立 microVM），无需 subPath 之类参数，隔离强度高于挂载方案
- 文件落 S3 由"挂载自动落"改为"收尾 sync 一步"（工作目录整体上传 `s3://桶/sessions/{session_id}/`），S3 侧目录结构与现在 COS 的 `asg/{session_id}/` 同构，外部访问方式不变（S3 API / 预签名 URL）

形态差异及适配结论：
- **S3 里是同步副本，不是实时挂载**（收尾 sync 时落桶）。适用于"任务完成后取结果"的消费模式；若业务要求"文件写下即出现在对象存储"，此点为腾讯方案优势项（AgentCore 的 S3 挂载方案因无会话隔离被否，见 §5）
- 外部向沙箱**反向投递文件**：在 sync 旁增加对称的下载步骤即可（同前缀约定，S3 → 工作目录），实现方式与 sync 相同
- 内置沙箱为 **Node 24**；依赖 Node 20 精确版本的负载需改用 Runtime Container 构建（自定义镜像，用法模型变为部署制），其余场景内置版本直接可用

## 3. 方案要点

### 3.1 沙箱：内置 Code Interpreter（`aws.codeinterpreter.v1`）

- 免部署、免镜像维护：出厂自带 Python 3.12 / Node 24 / npm（现在自建镜像装 Python+Node 的动机消失）
- TTL：`session_timeout_seconds`，默认 900s，最大 28800s（8h），与 AGS timeout 语义一致
- 网络模式：PUBLIC / SANDBOX（全断网，跑不可信代码更安全）/ VPC
- 运行用户为非 root（uid 991），根目录不可写；工作目录用 `/tmp/` 下路径（如 `/tmp/sandbox/.skills`）
- 环境不可定制（无自定义镜像、无资源规格选项）。若必须锁定工具链版本（如 Node 20）或预建系统级内容，改用 Runtime Container 构建（自己的 Dockerfile，ARM64），用法模型随之变为"部署 agent 服务"

### 3.2 隔离

每个会话独立 microVM，文件系统天然隔离，任意代码无法访问其他会话数据。实测：A 会话建 `a/` 目录、B 会话建 `b/` 目录，互相 `ls` 不可见、`cat` 报 No such file。

### 3.3 文件落 S3（sync 模式）

调用方在收尾时把工作目录文件拉出并按会话前缀上传：

```
find <工作目录> -type f  →  逐个上传  s3://<桶>/sessions/{session_id}/<相对路径>
```

前缀由代码根据 session_id 生成（不经过任何模型/用户输入），不存在写错目录的口子。外部消费：S3 API 直读或预签名 URL。

### 3.4 与腾讯 AGS 差异对照

| 项 | 腾讯 AGS 现状 | AgentCore CI 方案 |
|---|---|---|
| 拉起/执行/销毁 | E2B SDK | AgentCore SDK，模型一致 |
| TTL | timeout，最大 8h | 相同语义，相同上限 |
| 会话隔离 | COS subPath 挂载隔离 | microVM 自带，更强 |
| 对象存储落地 | COS 挂载，写下自动落 | **sync 一步，异步副本** |
| 自定义镜像 | 支持（v4 自装工具链） | 不支持（Python/Node 已内置；硬需求走 Container Runtime） |
| root | 镜像内可控 | 无（安全设计，不可改） |
| 空前缀坑 | 有（需占位文件） | 无 |

## 4. 验证脚本

`test_agentcore_sandbox.py`（与腾讯版 `test_sandbox.py` 同风格），依赖 `bedrock-agentcore` + `boto3`（Python ≥3.10）：

```bash
# 一键全验证：场景测试（拉沙箱→执行分析脚本→产报告→状态保持→sync 落 S3）+ 隔离验证
python3 test_agentcore_sandbox.py

# 交互进沙箱查看（敲什么执行什么；`py <代码>` 跑 python；exit 退出销毁）
python3 test_agentcore_sandbox.py shell [存活秒数]
```

凭证：使用各自的 AKSK，标准环境变量注入（脚本不含任何凭证）：

```bash
export AWS_ACCESS_KEY_ID=xxx
export AWS_SECRET_ACCESS_KEY=xxx
```

需要的权限：bedrock-agentcore 会话操作；若要验证 sync 步，另需对测试桶的 s3:PutObject。

桶：`SANDBOX_SYNC_BUCKET` 环境变量指定，默认 `agentcore-sandbox-p10` ——**本次评估创建的测试专用桶**（空桶、带 1 天自动清理策略，非任何线上业务桶）；桶不可达时 sync 步自动跳过，不影响其余验证。

已验证输出：场景 7 步全过、报告出现在 `s3://agentcore-sandbox-p10/sessions/{会话ID}/report.json` 且预签名 URL 可读、隔离双向不可见。

## 5. 已验证的备选与否决记录

- **S3 Files 挂载**（真挂载语义）：功能通（双向同步、外部可见），但挂载对所有会话全共享、无 subPath 等价物，隔离不满足 → 否。且强制 VPC 模式，附带 agentic_ai ENI 滞留问题（删 runtime 后 ENI 最长 8h 才释放，期间 SG/子网清不掉，客户无任何手段干预；官方文档明确此行为，社区有 Terraform destroy 被卡死的 issue）
- **Runtime + Session Storage + sync 工具**（部署形态）：三需求全满足且已真机验证（含空闲回收后数据自动恢复）。适用于"沙箱行为内嵌在常驻 agent 服务里"的场景；按需拉沙箱的场景用 CI 更轻
- Session Storage 当前为 Preview 状态，生产化前需复核 GA 时间表

