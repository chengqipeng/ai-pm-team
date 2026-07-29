# AWS AgentCore 沙箱数据同步机制设计

> 目标：基于 neo-apps-ai-agent-service 现有腾讯云沙箱逻辑，设计 AWS AgentCore 等价的数据同步层，上层使用方（Tools/Middleware）零感知切换

---

## 1. 现有腾讯版功能清单（neo-apps-ai-agent-service 分析）

### 1.1 沙箱生命周期

| 功能 | 实现位置 | 说明 |
|------|---------|------|
| 幂等启用（ensure） | `sandbox/provider.py` | state 有 sandbox_id→复用/resume；无→加锁 create |
| 状态检查 | `sandbox_api_client.py::status` | CREATING/RUNNING/PAUSED/DESTROYED/EXPIRED/UNKNOWN |
| 暂停/恢复 | `sandbox_api_client.py::pause/resume` | pause 保留状态停计费；resume 过期则重建返回新 id |
| 过期透明重建 | `sandbox/base.py::_absorb_rebuild` | 每次 execute/write/read 后检查响应中的 new_sandbox_id |
| 会话结束销毁 | `sandbox_mw.py::aafter_agent` | 本轮请求结束时 destroy（当前实现不做 pause） |
| sandbox_id 状态传播 | `sandbox_mw.py::awrap_tool_call` | 通过 LangGraph Command(update={"sandbox":...}) 写入图 state |

### 1.2 目录布局与隔离

| 功能 | 实现位置 | 说明 |
|------|---------|------|
| 固定根路径 `/sandbox/` | `sandbox/paths.py` | 远端 cd /sandbox/ |
| 预建目录 workspace/uploads/outputs | `paths.py::INIT_DIRS` | create 时自动建 |
| Skills 只读挂载 | `paths.py::MountSpec` | COS 目录挂载到 skills/personal 和 skills/tenant |
| COS subPath 会话隔离 | 远端平台 | `user/{user_id}/conversation/{conversation_id}` |
| 路径安全校验 | `paths.py::validate` | 拒绝 `..` 穿越、禁写 skills/ 区 |

### 1.3 文件入站（外部 → 沙箱）

| 功能 | 实现位置 | 说明 |
|------|---------|------|
| 自动预处理 | `middlewares/file_process.py` | abefore_agent 自动触发 |
| 预签名 URL 获取 | `file_url_utils.py` | fileMeta + generatePresignedUrl |
| 沙箱内 wget 下载 | `file_process.py::_download_file_to_sandbox` | bash -c 'wget -O "$1" "$2"' |
| 文档转 Markdown | `file_process.py::_convert_with_markitdown` | markitdown src -o dst.md |
| 音频 ASR 落盘 | `file_process.py::_write_audio_transcript` | files.write 写 .md |
| 幂等快速路径 | `file_process.py::_handle_one_file` | 一次 find 快照 + test -f 判断 |
| 跨轮历史文件复用 | `file_process.py` | 沙箱 uploads/ 跨轮持久（COS 挂载） |

### 1.4 文件出站（沙箱 → 用户）

| 功能 | 实现位置 | 说明 |
|------|---------|------|
| 只允许 outputs/ | `present_files_tool.py` | normalize_output_path 校验 |
| 混合读取策略 | `present_files_tool.py::_read_bytes` | 快路径 base64 stdout / 慢路径分页 |
| 上传租户私有桶 | `file_upload_client.py` | agentFileUpload + publicAcl=false |
| AGUI 事件呈现 | `present_files_tool.py::_emit` | data_key=artifact_output |
| 部分成功 | `present_files_tool.py` | gather 并发，单文件失败不影响 |

### 1.5 Skill 导入沙箱

| 功能 | 实现位置 | 说明 |
|------|---------|------|
| 按需导入 | `sandbox/skill_importer.py` | 仅含 scripts/ 的 Skill 触发 |
| 请求级临时目录 | `/sandbox/workspace/runtime-skills/<name>/` | 沙箱销毁即消失 |
| 幂等标记 | `.imported` 文件 | 同轮重复调用复用 |
| 资源大小限制 | `resource_limits.py` | 单文件/总包上限 |

### 1.6 安全策略

| 功能 | 实现位置 | 说明 |
|------|---------|------|
| 命令分级审计 | `sandbox/command_policy.py` | block/warn/pass + 审计日志 |
| 高危命令绝对拒绝 | `command_policy.py::_BLOCK_PATTERNS` | rm -rf /, fork bomb, dd 等 |
| 路径穿越拦截 | `command_policy.py::_ESCAPE_PATTERNS` | .. 段、/etc /root 等 |
| 中危命令警告放行 | `command_policy.py::_WARN_PATTERNS` | pip install, sudo 等 |

---

## 2. AWS 等价实现需要解决的差异

| 腾讯能力 | AWS AgentCore CI 现状 | 差距 |
|---------|---------------------|------|
| COS 实时挂载（写入即落） | 无（microVM 文件系统临时） | **需要 sync 层** |
| pause/resume（保留状态） | 不支持（stop 即销毁） | **需要 S3 sync 模拟** |
| subPath 会话隔离 | microVM 天然隔离（更强） | 无差距 |
| extra_mounts（只读 Skill 目录） | 不支持 S3 挂载到单 session | **需要 connect 时拉取** |
| 沙箱跨轮持久（uploads/ 活着） | 不支持（会话销毁即没） | **需要 S3 持久化** |
| 远端过期重建透明返回新 id | 需要自行检测+重建 | 已实现 |

---

## 3. AWS 数据同步层设计（SandboxSyncManager）

### 3.1 核心思路

在 Backend 抽象层之上增加一个 `SandboxSyncManager`，对上层 Tool/Middleware 透明：

```
┌──────────────────────────────────────────────────────────────────┐
│  Tools / Middleware（上层使用方，零改动）                           │
│  terminal / write_file / read_file / present_files / file_process │
└────────────────────────┬─────────────────────────────────────────┘
                         │ 调用 Backend 接口
                         ▼
┌──────────────────────────────────────────────────────────────────┐
│  AWSAgentCoreSandboxBackend（含内嵌 SyncManager）                 │
│                                                                  │
│  connect():                                                      │
│    1. ci.start() 创建 microVM                                    │
│    2. mkdir 标准目录 workspace/uploads/outputs                    │
│    3. SyncManager.restore() — S3 → 沙箱（skills + uploads）      │
│                                                                  │
│  write_file(path, content):                                      │
│    1. 写入沙箱                                                   │
│    2. SyncManager.on_write(path, content) — 异步写 S3            │
│                                                                  │
│  execute(command):                                                │
│    1. 沙箱执行                                                   │
│    2. SyncManager.on_execute() — 计数，触发条件 sync             │
│                                                                  │
│  disconnect():                                                   │
│    1. SyncManager.final_sync() — 全量 sync 兜底                 │
│    2. ci.stop()                                                  │
└──────────────────────────────────────────────────────────────────┘
                         │
                         ▼
┌──────────────────────────────────────────────────────────────────┐
│  S3 存储层                                                       │
│  s3://{bucket}/sandbox/{tenant_id}/{user_id}/{conversation_id}/  │
│    ├── uploads/       ← 用户文件（跨轮持久）                     │
│    ├── outputs/       ← Agent 产出                               │
│    ├── workspace/     ← 工作区文件                               │
│    └── skills/        ← Skill 脚本（从 Skill 源拉取，可选缓存）   │
└──────────────────────────────────────────────────────────────────┘
```

### 3.2 S3 路径约定

对齐腾讯 COS 的 `user/{user_id}/conversation/{conversation_id}` 结构：

```
s3://{bucket}/sandbox/{tenant_id}/{user_id}/{conversation_id}/uploads/123_report.pdf
s3://{bucket}/sandbox/{tenant_id}/{user_id}/{conversation_id}/uploads/123_report.md
s3://{bucket}/sandbox/{tenant_id}/{user_id}/{conversation_id}/outputs/analysis.xlsx
s3://{bucket}/sandbox/{tenant_id}/{user_id}/{conversation_id}/workspace/script.py
```

### 3.3 同步时机（三级策略）

| 时机 | 触发条件 | 同步范围 | 目的 |
|------|---------|---------|------|
| **write_file 即时** | 每次 write_file 调用 | 单文件异步 PUT | 关键产出实时落地 |
| **execute 后检测** | 每 N 次 execute（默认 5）或执行含重定向 `>` 的命令 | 增量 diff（find -newer） | 命令产出文件持久化 |
| **disconnect 兜底** | 会话结束/TTL 前主动断开 | 全量 sync（uploads/ + outputs/ + workspace/） | 确保无遗漏 |

### 3.4 恢复时机

| 时机 | 触发条件 | 恢复范围 |
|------|---------|---------|
| **connect 启动时** | 新 microVM 创建后 | S3 → 沙箱全量（uploads/ + outputs/ + workspace/） |
| **Skill 按需** | skills_tool 命中含 scripts 的 Skill | 从 Skill 资源 API 拉取（同现有逻辑，不走 S3） |

### 3.5 对齐现有功能矩阵

| neo-agent-v2 功能 | AWS 等价实现 |
|-------------------|------------|
| COS 挂载写入即落 | write_file 异步双写 + execute 后增量 sync |
| 跨轮 uploads/ 持久 | S3 uploads/ 前缀持久 + connect 时 restore |
| pause/resume | disconnect 全量 sync + connect 全量 restore |
| extra_mounts (skills) | connect 时从 Skill 资源 API 拉取（按现有 skill_importer 逻辑） |
| 过期透明重建 | _is_session_expired 检测 + _reconnect 重建 + S3 restore |
| present_files 出站 | 无变化（从沙箱读字节 → 上传业务桶，不依赖 COS 挂载） |
| file_process 入站 | 无变化（预签名 URL + wget，落到 /sandbox/uploads/） |

### 3.6 上层使用方零改动的保证

| 使用方 | 为什么不需要改 |
|--------|--------------|
| TerminalTool / bash | 调用 backend.execute()，sync 在内部透明发生 |
| WriteFileTool | 调用 backend.write_file()，S3 双写在内部异步完成 |
| ReadFileTool | 调用 backend.read_file()，文件已在 connect 时 restore |
| PresentFilesTool | 从沙箱读字节上传业务桶，不直接操作 COS/S3 |
| FileProcessMiddleware | wget 到沙箱 uploads/，sync 层自动持久化 |
| SkillImporter | 直接写沙箱临时目录，请求结束即丢，不需要 S3 持久化 |
| SandboxMiddleware | 管理 sandbox_id 传播和 destroy，内部 disconnect 自动 sync |

---

## 4. SyncManager 接口设计

```python
class SandboxSyncManager:
    """沙箱 ↔ S3 双向同步管理器，嵌入 AWSAgentCoreSandboxBackend 内部"""

    def __init__(self, bucket: str, prefix: str, region: str):
        """
        Args:
            bucket: S3 桶名
            prefix: S3 路径前缀（如 sandbox/{tenant_id}/{user_id}/{conversation_id}）
            region: AWS 区域
        """

    async def restore(self, invoke_command, invoke_code) -> int:
        """connect 后调用：从 S3 恢复全部文件到沙箱
        
        Returns: 恢复的文件数量
        """

    async def on_write(self, path: str, content: str) -> None:
        """write_file 后调用：异步上传单文件到 S3（fire-and-forget）"""

    async def on_execute(self, command: str) -> None:
        """execute 后调用：
          - 计数器 +1
          - 如果命令含重定向（>）或计数器 % N == 0，触发增量 sync
        """

    async def incremental_sync(self, invoke_command) -> int:
        """增量同步：find -newer marker → 逐个 cat + S3 PUT
        
        Returns: 同步的文件数量
        """

    async def final_sync(self, invoke_command) -> int:
        """disconnect 前调用：全量 sync（uploads/ + outputs/ + workspace/）
        
        Returns: 同步的文件数量
        """
```

---

## 5. 配置项

```bash
# .env 配置
SANDBOX_BACKEND=aws

# AWS 凭证（标准环境变量）
AWS_ACCESS_KEY_ID=xxx
AWS_SECRET_ACCESS_KEY=xxx

# 沙箱配置
AWS_SANDBOX_REGION=ap-southeast-1
AWS_SANDBOX_TIMEOUT=3600
AWS_SANDBOX_SYNC_BUCKET=your-production-bucket    # 必填，否则不 sync
AWS_SANDBOX_SYNC_PREFIX=sandbox                   # S3 前缀
AWS_SANDBOX_SYNC_INTERVAL=5                       # 每 N 次 execute 触发增量 sync
SANDBOX_WORKING_DIR=/tmp/sandbox                  # microVM 工作根（非 root 可写）
```

---

## 6. 与现有 aws_agentcore_backend.py 的改造点

当前已有文件只实现了收尾 sync（策略 A），需要增加：

1. **write_file 异步双写** — 在 write_file 返回 OK 后，fire-and-forget 方式上传到 S3
2. **execute 后增量 sync** — 带计数器 + 重定向检测，触发 `find -newer` 增量
3. **restore 增强** — 按 uploads/outputs/workspace 三个子目录分别恢复（而非只恢复 working_dir）
4. **SyncManager 抽取** — 把 sync/restore 逻辑从 backend 主体中抽出为独立类

不需要改动的：
- connect / disconnect 主流程不变
- 过期重建 / DB 持久化不变  
- 上层 Tool / Middleware 接口不变

---

## 7. 实现优先级

| 阶段 | 内容 | 价值 |
|------|------|------|
| P0 | write_file 异步双写 + disconnect 全量 sync + connect 全量 restore | 覆盖 80% 场景 |
| P1 | execute 后增量 sync（重定向检测 + 计数器） | 覆盖命令产出文件 |
| P2 | 二进制文件支持（base64 编码 sync） | 覆盖图片/Excel 等 |
| P3 | Skill 只读目录缓存到 S3（减少资源 API 调用） | 性能优化 |
