# AWS 沙箱 S3 同步策略验证方案

> 目标：确定 AWS AgentCore 沙箱的文件持久化策略，在数据安全性、性能、成本之间找到平衡

## 1. 问题陈述

AWS AgentCore CI 与腾讯 AGS 的核心差异：
- 腾讯：COS virtiofs 挂载，**写入即落盘**，沙箱 TTL 超时后数据仍在 COS
- AWS：microVM 文件系统临时，**会话销毁即丢**，需要主动 sync 到 S3

当前实现：仅在 `disconnect()` 时做收尾 sync。风险场景：

| 场景 | 数据丢失？ | 发生概率 |
|------|-----------|---------|
| Agent 正常结束 → 调用 disconnect | ❌ 不丢 | 高（正常路径） |
| 会话 TTL 自然超时（用户开着不操作） | ✅ 丢失 | 中 |
| 服务进程崩溃/OOM/重启 | ✅ 丢失 | 低 |
| 用户主动关闭浏览器（SSE 断开） | 取决于是否触发 disconnect | 中 |

## 2. 三种候选策略

### 策略 A：仅收尾 sync（当前实现）

```
disconnect(force_kill=False) 时一次性 sync 全量文件到 S3
```

优点：
- 实现最简单，S3 调用最少，成本最低
- 无运行时性能损耗

缺点：
- TTL 超时、进程崩溃时丢数据
- 依赖上层一定会调 disconnect

适用条件：
- 业务可接受"极端场景丢失未保存数据"
- Agent 任务执行时间远短于 TTL（比如 TTL=1h，任务平均 5min 完成）

### 策略 B：write_file 时同步双写

```
write_file() → 写沙箱 + 异步上传 S3（仅 write_file 触发，execute 不触发）
disconnect() → 全量 sync（兜底）
```

优点：
- 通过 Tool 写入的文件实时持久化（覆盖 Agent 80%+ 的文件产出场景）
- 不影响 execute 性能（命令执行不触发 sync）

缺点：
- execute 中 `echo > file` 或 `python script.py > output.txt` 产生的文件不会被实时 sync
- 每次 write_file 多一次 S3 PUT（延迟 ~50-100ms，异步不阻塞）

适用条件：
- 业务产出文件主要通过 write_file Tool 写入
- 可接受 execute 命令产出的中间文件不实时持久化

### 策略 C：定时增量 sync（心跳模式）

```
每 N 次 Tool 调用 或 每 M 秒，后台 diff+sync 工作目录到 S3
disconnect() → 最终全量 sync
```

优点：
- 最接近腾讯"写入即落"的语义（延迟 = 心跳间隔）
- 不区分文件来源（write_file / execute 产出的都能覆盖）
- TTL 超时时最多丢 1 个心跳间隔的数据

缺点：
- 实现复杂（需后台定时器 + 文件变更检测 + 增量上传）
- S3 调用量大（每次心跳 find + diff + 上传变更文件）
- 大量小文件场景可能产生显著 S3 费用

适用条件：
- 业务对数据持久性要求高（不容忍任何丢失）
- 沙箱内文件频繁变化且产出方式多样

## 3. 验证实验设计

### 实验环境
- 区域：ap-southeast-1（p10）
- 桶：SANDBOX_SYNC_BUCKET（测试专用桶）
- 凭证：标准 AKSK

### 实验 1：收尾 sync 的可靠性（策略 A 基线）

目的：验证正常路径下收尾 sync 是否丢数据

```python
# 1. 创建会话，执行多种写入操作
ci.start(session_timeout_seconds=900)
ci.invoke("executeCommand", {"command": "echo hello > /tmp/sandbox/.skills/a.txt"})
ci.invoke("executeCode", {"language": "python", "code": "open('/tmp/sandbox/.skills/b.json','w').write('{}')"})
# 通过 write_file Tool 路径
backend.write_file("/tmp/sandbox/.skills/c.md", "# Report")

# 2. 调用 disconnect（触发 sync）
backend.disconnect(force_kill=False)

# 3. 验证 S3 上是否有 a.txt, b.json, c.md
s3.head_object(Bucket=bucket, Key="sessions/{sid}/a.txt")  # 应存在
s3.head_object(Bucket=bucket, Key="sessions/{sid}/b.json") # 应存在
s3.head_object(Bucket=bucket, Key="sessions/{sid}/c.md")   # 应存在
```

预期：全部存在。

### 实验 2：TTL 超时场景的数据丢失验证

目的：确认 TTL 超时时数据确实丢失（量化风险）

```python
# 1. 创建短 TTL 会话
ci.start(session_timeout_seconds=300)  # 5 分钟
ci.invoke("executeCommand", {"command": "echo important > /tmp/sandbox/.skills/data.txt"})

# 2. 不调用 disconnect/stop，等待 TTL 超时
time.sleep(360)

# 3. 验证 S3 无数据
try:
    s3.head_object(Bucket=bucket, Key="sessions/{sid}/data.txt")
    print("❌ 数据不应存在（sync 从未触发）")
except s3.exceptions.ClientError:
    print("✅ 确认：TTL 超时导致数据丢失")

# 4. 尝试再次连接该会话
try:
    ci.invoke("executeCommand", {"command": "echo test"})
    print("❌ 会话不应存活")
except Exception as e:
    print(f"✅ 确认：会话已销毁 ({e})")
```

### 实验 3：write_file 双写的延迟开销（策略 B）

目的：测量异步 S3 PUT 对 write_file 响应时间的影响

```python
import time

# 对照组：纯沙箱写入（不触发 S3）
times_no_s3 = []
for i in range(20):
    t0 = time.time()
    await backend.write_file(f"/tmp/sandbox/.skills/file_{i}.txt", "x" * 1024)
    times_no_s3.append(time.time() - t0)

# 实验组：沙箱写入 + 异步 S3 PUT
times_with_s3 = []
for i in range(20):
    t0 = time.time()
    await backend.write_file(f"/tmp/sandbox/.skills/file_{i}.txt", "x" * 1024)
    # 模拟异步 S3 PUT（asyncio.create_task）
    asyncio.create_task(upload_to_s3(f"file_{i}.txt", "x" * 1024))
    times_with_s3.append(time.time() - t0)

# 比较 P50/P95
```

预期：异步双写不影响 write_file 返回时间（<5ms 差异）。

### 实验 4：定时增量 sync 的 S3 开销（策略 C）

目的：测量实际场景的 sync 频率和 S3 调用量

```python
# 模拟典型 Agent 任务：10 次 execute + 3 次 write_file
# 心跳间隔 = 30 秒
# 测量：
# - 每次心跳的 find 命令耗时
# - 变更文件数量（增量）
# - S3 PUT 调用次数
# - 总 sync 耗时
```

### 实验 5：恢复完整性验证（connect 时 restore）

目的：验证从 S3 恢复后文件完整性

```python
# 1. 写入多种文件（文本、JSON、二进制模拟、大文件）
files = {
    "/tmp/sandbox/.skills/report.json": json.dumps({"key": "value", "中文": "测试"}),
    "/tmp/sandbox/.skills/code.py": "# -*- coding: utf-8 -*-\nprint('hello')\n",
    "/tmp/sandbox/.skills/data.csv": "a,b,c\n" * 1000,  # ~6KB
    "/tmp/sandbox/.skills/nested/deep/file.txt": "nested content",
}
for path, content in files.items():
    await backend.write_file(path, content)

# 2. disconnect（sync）
await backend.disconnect()

# 3. 重新 connect（restore from S3）
await backend.connect()

# 4. 逐个读取并校验
for path, expected in files.items():
    result = await backend.read_file(path)
    assert result.stdout == expected, f"MISMATCH: {path}"
    print(f"✅ {path} 恢复正确")
```

## 4. 决策矩阵

验证完成后，按以下维度打分（1-5）：

| 维度 | 策略 A (收尾) | 策略 B (双写) | 策略 C (心跳) |
|------|:---:|:---:|:---:|
| 数据安全性（TTL/崩溃时不丢） | | | |
| 实现复杂度（越低越好） | | | |
| 运行时性能影响 | | | |
| S3 成本 | | | |
| 与腾讯行为一致性 | | | |

## 5. 建议的验证顺序

1. 先跑实验 1 + 2：确认基线行为和风险大小
2. 看实验 2 的结果判断：如果业务 TTL 远大于任务时长（如 TTL=8h，任务 5min），策略 A 可能已经够用
3. 如果需要更强保障，跑实验 3：确认双写不影响性能后，选策略 B
4. 只有当业务要求"任何时刻崩溃都不丢"时，才考虑策略 C（跑实验 4 评估成本）

## 6. 我的初步判断

基于当前架构（sandbox backend 是全局单例，Agent 任务结束后由上层触发 disconnect）：

**推荐策略 B（write_file 双写）+ 兜底收尾 sync**，理由：

1. Agent 产出给用户的最终文件（报告、代码、数据）几乎都通过 `write_file` Tool 写入
2. `execute` 中间过程产出的临时文件（compile output、log）通常不需要持久化
3. 异步 S3 PUT 不阻塞主流程，性能影响可忽略
4. 比策略 C 简单得多，比策略 A 安全得多
5. TTL 超时的边角场景：即使 sync 心跳没来得及，write_file 产出的文件已经在 S3 了

如果验证实验 3 确认异步双写性能无影响，可直接采用。
