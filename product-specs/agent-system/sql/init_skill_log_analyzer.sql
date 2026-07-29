-- ═══════════════════════════════════════════════════════════
-- Skill: log-analyzer — 智能日志分析工具
--
-- 功能：
--   多格式日志解析、错误聚类、性能瓶颈检测、异常模式识别、
--   日志统计报表生成，支持 Nginx/Java/Python/JSON 等常见日志格式
--
-- Python 脚本（10+ 文件）：
--   scripts/
--     ├── main.py              主入口
--     ├── config.py            配置管理
--     ├── parser.py            日志解析器（多格式）
--     ├── analyzer.py          核心分析引擎
--     ├── error_cluster.py     错误聚类
--     ├── performance.py       性能分析
--     ├── anomaly.py           异常检测
--     ├── reporter.py          报告生成
--     ├── filters.py           日志过滤器
--     ├── utils.py             工具函数
--     ├── models.py            数据模型
--     └── requirements.txt     依赖声明
--   references/
--     └── usage-guide.md       使用说明
--
-- 依赖表：ai_skill + ai_skill_definition + ai_skill_resource
-- ═══════════════════════════════════════════════════════════

SET search_path TO paas_ai;

-- ═══════════════════════════════════════════════════════════
-- 1. ai_skill — 主记录
-- ═══════════════════════════════════════════════════════════

INSERT INTO ai_skill (
    id, api_key, tenant_id,
    name, description, owner, category, tags, icon, sort_num,
    current_version, enabled_flg, system_flg,
    exec_count, success_count, avg_duration_ms,
    ext_info,
    delete_flg, created_at, created_by, updated_at, updated_by
) VALUES (
    4000000000000001,
    'log-analyzer',
    0,
    '智能日志分析',
    '多格式日志解析与智能分析，支持错误聚类、性能瓶颈检测、异常模式识别，生成结构化分析报告',
    'AI-Platform',
    'devops',
    '["log","analysis","devops","python","error","performance","anomaly"]',
    '🔍',
    60,
    '1.0.0',
    1,
    0,
    0, 0, 0,
    '{"script_execution":{"entry":"scripts/main.py","language":"python","required_packages":["pandas>=2.0","numpy>=1.24","scikit-learn>=1.3","python-dateutil>=2.8"],"auto_install":true,"timeout":180},"preload_resources":{"always":["references/usage-guide.md"],"max_preload":2}}',
    0,
    1748275200000,
    0,
    1748275200000,
    0
) ON CONFLICT (tenant_id, api_key) WHERE delete_flg = 0 DO NOTHING;

-- ═══════════════════════════════════════════════════════════
-- 2. ai_skill_definition — 版本内容
-- ═══════════════════════════════════════════════════════════

INSERT INTO ai_skill_definition (
    id, skill_api_key, tenant_id, version,
    changelog,
    when_to_use, context, agent, model,
    allowed_tools, arguments, prompt,
    risk_level, requires_confirmation, max_tool_calls, timeout_ms,
    output_mode, component_apikey, post_output_behavior,
    published_by,
    delete_flg, created_at, created_by, updated_at, updated_by
) VALUES (
    4000000000000101,
    'log-analyzer',
    0,
    '1.0.0',
    '初始版本：支持多格式日志解析、错误聚类、性能分析、异常检测',
    '日志分析|log分析|错误排查|性能瓶颈|异常检测|日志统计|error分析|慢请求',
    'inline',
    '',
    '',
    '["terminal","execute_code","read_file","write_file"]',
    '["log_file","analysis_mode"]',
    '# 智能日志分析

你是一位资深 SRE 工程师。请使用预装的 Python 日志分析工具集，对用户指定的日志文件进行深度分析。

## 前置条件
- 分析脚本已自动同步到沙盒: `${SKILL_DIR}/scripts/`
- 如首次执行，需先安装依赖

## 执行步骤

### 步骤 1: 安装依赖（仅首次需要）
```bash
pip install -r ${SKILL_DIR}/scripts/requirements.txt
```

### 步骤 2: 确认日志文件存在
```bash
ls -la {log_file}
head -20 {log_file}
```

### 步骤 3: 运行分析
```bash
python3 ${SKILL_DIR}/scripts/main.py --input {log_file} --mode {analysis_mode} --output /tmp/log_analysis_result.json
```

分析模式：
- `full` — 完整分析（错误聚类 + 性能 + 异常，默认）
- `errors` — 仅错误聚类分析
- `performance` — 仅性能瓶颈分析
- `anomaly` — 仅异常模式检测
- `stats` — 仅统计概览

### 步骤 4: 读取分析结果
使用 read_file 读取 `/tmp/log_analysis_result.json`

### 步骤 5: 生成报告
根据 JSON 结果，生成结构化的分析报告：
- 📊 日志概览（总行数、时间范围、日志级别分布）
- 🔴 错误聚类（Top N 错误模式、影响范围、首次/末次出现）
- ⚡ 性能瓶颈（慢请求 Top N、P50/P95/P99 延迟）
- ⚠️ 异常模式（突增/突降、周期异常、罕见事件）
- 💡 建议（基于分析给出的排查建议）

## 错误处理
- ModuleNotFoundError → 重新执行步骤 1
- FileNotFoundError → 检查文件路径
- UnicodeDecodeError → 尝试指定编码: --encoding gbk

## 注意事项
- 支持的日志格式：Nginx access/error、Java Log4j/Logback、Python logging、JSON Lines
- 大文件（>100MB）会自动采样分析，结果中标注采样率
- 可通过 --filter 参数过滤特定时间段或关键词',
    'read_only',
    0,
    15,
    180000,
    'text',
    '',
    'silent',
    0,
    0, 1748275200000, 0, 1748275200000, 0
) ON CONFLICT (tenant_id, skill_api_key, version) WHERE delete_flg = 0 DO NOTHING;

-- ═══════════════════════════════════════════════════════════
-- 3. ai_skill_resource — 资源文件树
-- ═══════════════════════════════════════════════════════════

-- ── 3.1 目录节点 ──

INSERT INTO ai_skill_resource (
    id, tenant_id, skill_api_key, version,
    parent_id, node_type, name, path, depth,
    content, content_type, content_size,
    description, icon, sort_num,
    enabled_flg, delete_flg, created_at, created_by, updated_at, updated_by
) VALUES (
    4000000000001001, 0, 'log-analyzer', '1.0.0',
    NULL, 'dir', 'scripts', 'scripts', 0,
    NULL, 'dir', 0,
    'Python 日志分析脚本目录', '📂', 10,
    1, 0, 1748275200000, 0, 1748275200000, 0
) ON CONFLICT (tenant_id, skill_api_key, version, path) WHERE delete_flg = 0 DO NOTHING;

INSERT INTO ai_skill_resource (
    id, tenant_id, skill_api_key, version,
    parent_id, node_type, name, path, depth,
    content, content_type, content_size,
    description, icon, sort_num,
    enabled_flg, delete_flg, created_at, created_by, updated_at, updated_by
) VALUES (
    4000000000001002, 0, 'log-analyzer', '1.0.0',
    NULL, 'dir', 'references', 'references', 0,
    NULL, 'dir', 0,
    '参考文档目录', '📁', 20,
    1, 0, 1748275200000, 0, 1748275200000, 0
) ON CONFLICT (tenant_id, skill_api_key, version, path) WHERE delete_flg = 0 DO NOTHING;


-- ── 3.2 scripts/main.py — 主入口 ──

INSERT INTO ai_skill_resource (
    id, tenant_id, skill_api_key, version,
    parent_id, node_type, name, path, depth,
    content, content_type, content_size,
    description, icon, sort_num,
    enabled_flg, delete_flg, created_at, created_by, updated_at, updated_by
) VALUES (
    4000000000001011, 0, 'log-analyzer', '1.0.0',
    4000000000001001, 'file', 'main.py', 'scripts/main.py', 1,
    '#!/usr/bin/env python3
"""智能日志分析工具 — 主入口

用法:
    python3 main.py --input access.log --mode full --output result.json
    python3 main.py --input app.log --mode errors --filter "2024-01-15"
    python3 main.py --input service.log --mode performance --top 20

分析模式:
    full        — 完整分析（默认）
    errors      — 错误聚类
    performance — 性能瓶颈
    anomaly     — 异常检测
    stats       — 统计概览
"""
import argparse
import json
import sys
import time
from pathlib import Path

from config import AnalysisConfig
from parser import LogParser
from analyzer import LogAnalyzer
from error_cluster import ErrorClusterer
from performance import PerformanceAnalyzer
from anomaly import AnomalyDetector
from reporter import ReportGenerator
from filters import LogFilter
from utils import setup_logging, format_duration


def main():
    parser = argparse.ArgumentParser(description="智能日志分析工具")
    parser.add_argument("--input", required=True, help="日志文件路径")
    parser.add_argument("--mode", default="full",
                        choices=["full", "errors", "performance", "anomaly", "stats"],
                        help="分析模式（默认: full）")
    parser.add_argument("--output", default="/tmp/log_analysis_result.json",
                        help="输出 JSON 路径")
    parser.add_argument("--encoding", default="utf-8", help="文件编码")
    parser.add_argument("--filter", default="", help="过滤条件（时间或关键词）")
    parser.add_argument("--top", type=int, default=10, help="Top N 结果数量")
    parser.add_argument("--sample-rate", type=float, default=1.0,
                        help="采样率（0.0-1.0），大文件自动降低")
    args = parser.parse_args()

    logger = setup_logging("log-analyzer")
    start_time = time.time()

    # 验证输入文件
    input_path = Path(args.input)
    if not input_path.exists():
        print(f"错误: 文件不存在 — {args.input}", file=sys.stderr)
        sys.exit(1)

    # 大文件自动采样
    file_size_mb = input_path.stat().st_size / (1024 * 1024)
    sample_rate = args.sample_rate
    if file_size_mb > 100 and sample_rate == 1.0:
        sample_rate = min(0.1, 100 / file_size_mb)
        logger.warning(f"大文件({file_size_mb:.0f}MB)，自动采样率: {sample_rate:.2%}")

    # 初始化配置
    config = AnalysisConfig(
        encoding=args.encoding,
        top_n=args.top,
        sample_rate=sample_rate,
        filter_expr=args.filter,
    )

    # 解析日志
    logger.info(f"开始解析: {args.input} ({file_size_mb:.1f}MB)")
    log_parser = LogParser(config)
    entries = log_parser.parse_file(args.input)

    if not entries:
        print("错误: 未能解析出有效日志条目", file=sys.stderr)
        sys.exit(1)

    # 应用过滤器
    if args.filter:
        log_filter = LogFilter(config)
        entries = log_filter.apply(entries, args.filter)
        logger.info(f"过滤后: {len(entries)} 条")

    # 执行分析
    logger.info(f"分析模式: {args.mode}, 条目数: {len(entries)}")
    analyzer = LogAnalyzer(config)
    result = analyzer.analyze(entries, mode=args.mode)

    # 添加元信息
    elapsed = time.time() - start_time
    result["meta"] = {
        "input_file": args.input,
        "file_size_mb": round(file_size_mb, 2),
        "total_entries": len(entries),
        "analysis_mode": args.mode,
        "sample_rate": sample_rate,
        "elapsed_seconds": round(elapsed, 2),
        "elapsed_human": format_duration(elapsed),
    }

    # 输出结果
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2))

    print(f"✅ 分析完成 [{args.mode}]")
    print(f"   条目数: {len(entries)}")
    print(f"   耗时: {format_duration(elapsed)}")
    print(f"   结果: {args.output}")


if __name__ == "__main__":
    main()
',
    'python', 3200,
    '主入口脚本 — 参数解析、流程编排', '🐍', 10,
    1, 0, 1748275200000, 0, 1748275200000, 0
) ON CONFLICT (tenant_id, skill_api_key, version, path) WHERE delete_flg = 0 DO NOTHING;

-- ── 3.3 scripts/config.py — 配置管理 ──

INSERT INTO ai_skill_resource (
    id, tenant_id, skill_api_key, version,
    parent_id, node_type, name, path, depth,
    content, content_type, content_size,
    description, icon, sort_num,
    enabled_flg, delete_flg, created_at, created_by, updated_at, updated_by
) VALUES (
    4000000000001012, 0, 'log-analyzer', '1.0.0',
    4000000000001001, 'file', 'config.py', 'scripts/config.py', 1,
    '"""分析配置管理

集中管理所有分析参数，支持从环境变量和命令行覆盖。
"""
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class AnalysisConfig:
    """分析配置"""
    # 文件读取
    encoding: str = "utf-8"
    max_line_length: int = 10000
    sample_rate: float = 1.0

    # 分析参数
    top_n: int = 10
    filter_expr: str = ""
    time_bucket_minutes: int = 5

    # 错误聚类
    cluster_similarity_threshold: float = 0.75
    min_cluster_size: int = 2
    max_clusters: int = 50

    # 性能分析
    slow_threshold_ms: float = 1000.0
    percentiles: list = field(default_factory=lambda: [50, 75, 90, 95, 99])

    # 异常检测
    anomaly_zscore_threshold: float = 3.0
    anomaly_min_data_points: int = 10
    anomaly_window_size: int = 12

    # 输出
    max_sample_lines: int = 5
    truncate_message_length: int = 200


# 日志格式正则模式
LOG_PATTERNS = {
    "nginx_access": (
        r'''^(?P<ip>[\d.]+)\s+-\s+(?P<user>\S+)\s+'''
        r'''\[(?P<time>[^\]]+)\]\s+'''
        r'''"(?P<method>\w+)\s+(?P<path>\S+)\s+\S+"\s+'''
        r'''(?P<status>\d+)\s+(?P<size>\d+)\s+'''
        r'''"(?P<referer>[^"]*)"\s+"(?P<ua>[^"]*)"'''
        r'''(?:\s+(?P<duration>[\d.]+))?'''
    ),
    "nginx_error": (
        r'''^(?P<time>\d{4}/\d{2}/\d{2}\s+\d{2}:\d{2}:\d{2})\s+'''
        r'''\[(?P<level>\w+)\]\s+'''
        r'''(?P<pid>\d+)#(?P<tid>\d+):\s+'''
        r'''(?:\*\d+\s+)?(?P<message>.+)'''
    ),
    "java_logback": (
        r'''^(?P<time>\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}[.,]\d{3})\s+'''
        r'''(?P<level>\w+)\s+'''
        r'''\[(?P<thread>[^\]]+)\]\s+'''
        r'''(?P<logger>\S+)\s+-\s+'''
        r'''(?P<message>.+)'''
    ),
    "python_logging": (
        r'''^(?P<time>\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2},\d{3})\s+'''
        r'''(?P<level>\w+)\s+'''
        r'''(?P<logger>\S+)\s+'''
        r'''(?P<message>.+)'''
    ),
    "json_lines": None,  # JSON 格式特殊处理
}

# 日志级别权重（用于严重度排序）
LEVEL_WEIGHTS = {
    "TRACE": 0,
    "DEBUG": 1,
    "INFO": 2,
    "WARN": 3,
    "WARNING": 3,
    "ERROR": 4,
    "FATAL": 5,
    "CRITICAL": 5,
}
',
    'python', 2400,
    '配置管理 — 分析参数、日志格式正则、级别权重', '🐍', 20,
    1, 0, 1748275200000, 0, 1748275200000, 0
) ON CONFLICT (tenant_id, skill_api_key, version, path) WHERE delete_flg = 0 DO NOTHING;


-- ── 3.4 scripts/parser.py — 日志解析器 ──

INSERT INTO ai_skill_resource (
    id, tenant_id, skill_api_key, version,
    parent_id, node_type, name, path, depth,
    content, content_type, content_size,
    description, icon, sort_num,
    enabled_flg, delete_flg, created_at, created_by, updated_at, updated_by
) VALUES (
    4000000000001013, 0, 'log-analyzer', '1.0.0',
    4000000000001001, 'file', 'parser.py', 'scripts/parser.py', 1,
    '"""多格式日志解析器

支持自动检测日志格式，解析为统一的 LogEntry 结构。
支持格式：Nginx access/error、Java Logback、Python logging、JSON Lines
"""
import json
import re
import random
from datetime import datetime
from typing import Optional

from config import AnalysisConfig, LOG_PATTERNS
from models import LogEntry


class LogParser:
    """日志解析器 — 自动检测格式并解析"""

    def __init__(self, config: AnalysisConfig):
        self.config = config
        self._compiled_patterns = {}
        self._detected_format: Optional[str] = None

        # 预编译正则
        for name, pattern in LOG_PATTERNS.items():
            if pattern is not None:
                self._compiled_patterns[name] = re.compile(pattern)

    def parse_file(self, filepath: str) -> list[LogEntry]:
        """解析日志文件，返回 LogEntry 列表"""
        entries = []
        multiline_buffer = []
        current_entry = None

        try:
            with open(filepath, "r", encoding=self.config.encoding) as f:
                for line_num, line in enumerate(f, 1):
                    # 采样控制
                    if self.config.sample_rate < 1.0:
                        if random.random() > self.config.sample_rate:
                            continue

                    # 跳过过长行
                    if len(line) > self.config.max_line_length:
                        continue

                    line = line.rstrip("\n")
                    if not line.strip():
                        continue

                    # 自动检测格式（前 10 行）
                    if self._detected_format is None and line_num <= 10:
                        self._detected_format = self._detect_format(line)

                    # 解析
                    entry = self._parse_line(line, line_num)
                    if entry:
                        # 保存之前的多行条目
                        if current_entry and multiline_buffer:
                            current_entry.message += "\n" + "\n".join(multiline_buffer)
                            multiline_buffer = []
                        if current_entry:
                            entries.append(current_entry)
                        current_entry = entry
                    else:
                        # 多行日志（如 Java 堆栈）
                        if current_entry:
                            multiline_buffer.append(line)

            # 最后一条
            if current_entry:
                if multiline_buffer:
                    current_entry.message += "\n" + "\n".join(multiline_buffer)
                entries.append(current_entry)

        except UnicodeDecodeError:
            # 尝试 GBK fallback
            return self._parse_with_encoding(filepath, "gbk")

        return entries

    def _detect_format(self, line: str) -> str:
        """自动检测日志格式"""
        # JSON Lines
        if line.strip().startswith("{"):
            try:
                json.loads(line)
                return "json_lines"
            except json.JSONDecodeError:
                pass

        # 尝试各种正则
        for name, pattern in self._compiled_patterns.items():
            if pattern.match(line):
                return name

        return "unknown"

    def _parse_line(self, line: str, line_num: int) -> Optional[LogEntry]:
        """解析单行日志"""
        if self._detected_format == "json_lines":
            return self._parse_json_line(line, line_num)

        if self._detected_format and self._detected_format in self._compiled_patterns:
            pattern = self._compiled_patterns[self._detected_format]
            match = pattern.match(line)
            if match:
                return self._match_to_entry(match, line_num)

        # 未知格式：尝试所有模式
        for name, pattern in self._compiled_patterns.items():
            match = pattern.match(line)
            if match:
                self._detected_format = name
                return self._match_to_entry(match, line_num)

        return None

    def _parse_json_line(self, line: str, line_num: int) -> Optional[LogEntry]:
        """解析 JSON Lines 格式"""
        try:
            data = json.loads(line)
            return LogEntry(
                line_num=line_num,
                timestamp=self._parse_timestamp(
                    data.get("timestamp") or data.get("time") or data.get("@timestamp", "")
                ),
                level=(data.get("level") or data.get("severity") or "INFO").upper(),
                message=data.get("message") or data.get("msg") or str(data),
                logger=data.get("logger") or data.get("name") or "",
                thread=data.get("thread") or "",
                extra=data,
            )
        except (json.JSONDecodeError, KeyError):
            return None

    def _match_to_entry(self, match: re.Match, line_num: int) -> LogEntry:
        """正则匹配结果转 LogEntry"""
        groups = match.groupdict()
        return LogEntry(
            line_num=line_num,
            timestamp=self._parse_timestamp(groups.get("time", "")),
            level=(groups.get("level") or "INFO").upper(),
            message=groups.get("message") or "",
            logger=groups.get("logger") or "",
            thread=groups.get("thread") or "",
            extra={k: v for k, v in groups.items()
                   if k not in ("time", "level", "message", "logger", "thread") and v},
        )

    def _parse_timestamp(self, time_str: str) -> Optional[datetime]:
        """解析时间戳（支持多种格式）"""
        if not time_str:
            return None

        formats = [
            "%Y-%m-%d %H:%M:%S,%f",      # Python logging
            "%Y-%m-%d %H:%M:%S.%f",      # Java Logback
            "%Y-%m-%dT%H:%M:%S.%fZ",     # ISO 8601
            "%Y-%m-%dT%H:%M:%S%z",       # ISO with timezone
            "%d/%b/%Y:%H:%M:%S %z",      # Nginx access
            "%Y/%m/%d %H:%M:%S",         # Nginx error
        ]

        for fmt in formats:
            try:
                return datetime.strptime(time_str.strip(), fmt)
            except ValueError:
                continue

        return None

    def _parse_with_encoding(self, filepath: str, encoding: str) -> list[LogEntry]:
        """使用指定编码重新解析"""
        old_encoding = self.config.encoding
        self.config.encoding = encoding
        self._detected_format = None
        try:
            return self.parse_file(filepath)
        finally:
            self.config.encoding = old_encoding
',
    'python', 5100,
    '多格式日志解析器 — 自动检测 Nginx/Java/Python/JSON 格式', '🐍', 30,
    1, 0, 1748275200000, 0, 1748275200000, 0
) ON CONFLICT (tenant_id, skill_api_key, version, path) WHERE delete_flg = 0 DO NOTHING;

-- ── 3.5 scripts/models.py — 数据模型 ──

INSERT INTO ai_skill_resource (
    id, tenant_id, skill_api_key, version,
    parent_id, node_type, name, path, depth,
    content, content_type, content_size,
    description, icon, sort_num,
    enabled_flg, delete_flg, created_at, created_by, updated_at, updated_by
) VALUES (
    4000000000001014, 0, 'log-analyzer', '1.0.0',
    4000000000001001, 'file', 'models.py', 'scripts/models.py', 1,
    '"""数据模型定义

所有分析模块共享的数据结构。
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional


@dataclass
class LogEntry:
    """单条日志条目"""
    line_num: int = 0
    timestamp: Optional[datetime] = None
    level: str = "INFO"
    message: str = ""
    logger: str = ""
    thread: str = ""
    extra: dict = field(default_factory=dict)

    @property
    def is_error(self) -> bool:
        return self.level in ("ERROR", "FATAL", "CRITICAL")

    @property
    def is_warning(self) -> bool:
        return self.level in ("WARN", "WARNING")

    @property
    def duration_ms(self) -> Optional[float]:
        """从 extra 中提取请求耗时"""
        dur = self.extra.get("duration") or self.extra.get("elapsed")
        if dur is not None:
            try:
                return float(dur)
            except (ValueError, TypeError):
                pass
        return None

    @property
    def status_code(self) -> Optional[int]:
        """从 extra 中提取 HTTP 状态码"""
        status = self.extra.get("status")
        if status is not None:
            try:
                return int(status)
            except (ValueError, TypeError):
                pass
        return None


@dataclass
class ErrorCluster:
    """错误聚类结果"""
    cluster_id: int = 0
    pattern: str = ""
    count: int = 0
    first_seen: Optional[datetime] = None
    last_seen: Optional[datetime] = None
    sample_messages: list = field(default_factory=list)
    affected_loggers: list = field(default_factory=list)
    severity: str = "ERROR"

    def to_dict(self) -> dict:
        return {
            "cluster_id": self.cluster_id,
            "pattern": self.pattern,
            "count": self.count,
            "first_seen": self.first_seen.isoformat() if self.first_seen else None,
            "last_seen": self.last_seen.isoformat() if self.last_seen else None,
            "sample_messages": self.sample_messages[:3],
            "affected_loggers": self.affected_loggers[:5],
            "severity": self.severity,
        }


@dataclass
class PerformanceMetrics:
    """性能指标"""
    endpoint: str = ""
    count: int = 0
    p50_ms: float = 0.0
    p75_ms: float = 0.0
    p90_ms: float = 0.0
    p95_ms: float = 0.0
    p99_ms: float = 0.0
    max_ms: float = 0.0
    error_rate: float = 0.0
    slow_count: int = 0

    def to_dict(self) -> dict:
        return {
            "endpoint": self.endpoint,
            "count": self.count,
            "p50_ms": round(self.p50_ms, 2),
            "p75_ms": round(self.p75_ms, 2),
            "p90_ms": round(self.p90_ms, 2),
            "p95_ms": round(self.p95_ms, 2),
            "p99_ms": round(self.p99_ms, 2),
            "max_ms": round(self.max_ms, 2),
            "error_rate": round(self.error_rate, 4),
            "slow_count": self.slow_count,
        }


@dataclass
class AnomalyEvent:
    """异常事件"""
    timestamp: Optional[datetime] = None
    metric: str = ""
    expected_value: float = 0.0
    actual_value: float = 0.0
    zscore: float = 0.0
    anomaly_type: str = ""  # spike, drop, pattern_break
    description: str = ""

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
            "metric": self.metric,
            "expected_value": round(self.expected_value, 2),
            "actual_value": round(self.actual_value, 2),
            "zscore": round(self.zscore, 2),
            "anomaly_type": self.anomaly_type,
            "description": self.description,
        }
',
    'python', 3500,
    '数据模型 — LogEntry/ErrorCluster/PerformanceMetrics/AnomalyEvent', '🐍', 25,
    1, 0, 1748275200000, 0, 1748275200000, 0
) ON CONFLICT (tenant_id, skill_api_key, version, path) WHERE delete_flg = 0 DO NOTHING;


-- ── 3.6 scripts/analyzer.py — 核心分析引擎 ──

INSERT INTO ai_skill_resource (
    id, tenant_id, skill_api_key, version,
    parent_id, node_type, name, path, depth,
    content, content_type, content_size,
    description, icon, sort_num,
    enabled_flg, delete_flg, created_at, created_by, updated_at, updated_by
) VALUES (
    4000000000001015, 0, 'log-analyzer', '1.0.0',
    4000000000001001, 'file', 'analyzer.py', 'scripts/analyzer.py', 1,
    '"""核心分析引擎

编排各分析模块，汇总结果。
"""
from collections import Counter
from datetime import datetime
from typing import Optional

from config import AnalysisConfig, LEVEL_WEIGHTS
from models import LogEntry
from error_cluster import ErrorClusterer
from performance import PerformanceAnalyzer
from anomaly import AnomalyDetector


class LogAnalyzer:
    """日志分析引擎 — 编排各子分析器"""

    def __init__(self, config: AnalysisConfig):
        self.config = config
        self.error_clusterer = ErrorClusterer(config)
        self.perf_analyzer = PerformanceAnalyzer(config)
        self.anomaly_detector = AnomalyDetector(config)

    def analyze(self, entries: list[LogEntry], mode: str = "full") -> dict:
        """执行分析，返回结构化结果"""
        result = {}

        # 基础统计（所有模式都包含）
        result["stats"] = self._compute_stats(entries)

        if mode == "stats":
            return result

        if mode in ("full", "errors"):
            error_entries = [e for e in entries if e.is_error]
            result["error_clusters"] = self.error_clusterer.cluster(error_entries)

        if mode in ("full", "performance"):
            result["performance"] = self.perf_analyzer.analyze(entries)

        if mode in ("full", "anomaly"):
            result["anomalies"] = self.anomaly_detector.detect(entries)

        return result

    def _compute_stats(self, entries: list[LogEntry]) -> dict:
        """计算基础统计信息"""
        if not entries:
            return {"total": 0}

        # 时间范围
        timestamps = [e.timestamp for e in entries if e.timestamp]
        time_range = {}
        if timestamps:
            time_range = {
                "start": min(timestamps).isoformat(),
                "end": max(timestamps).isoformat(),
                "duration_seconds": (max(timestamps) - min(timestamps)).total_seconds(),
            }

        # 级别分布
        level_dist = Counter(e.level for e in entries)
        level_sorted = sorted(level_dist.items(),
                              key=lambda x: LEVEL_WEIGHTS.get(x[0], 0), reverse=True)

        # Logger 分布（Top 10）
        logger_dist = Counter(e.logger for e in entries if e.logger)
        top_loggers = logger_dist.most_common(self.config.top_n)

        # 每分钟请求量（QPS 趋势）
        qps_timeline = self._compute_qps_timeline(entries)

        return {
            "total": len(entries),
            "time_range": time_range,
            "level_distribution": dict(level_sorted),
            "error_count": sum(1 for e in entries if e.is_error),
            "warning_count": sum(1 for e in entries if e.is_warning),
            "error_rate": round(sum(1 for e in entries if e.is_error) / len(entries), 4),
            "top_loggers": [{"logger": l, "count": c} for l, c in top_loggers],
            "qps_timeline": qps_timeline,
        }

    def _compute_qps_timeline(self, entries: list[LogEntry]) -> list[dict]:
        """计算每时间桶的请求量"""
        timestamps = [e.timestamp for e in entries if e.timestamp]
        if len(timestamps) < 2:
            return []

        bucket_seconds = self.config.time_bucket_minutes * 60
        min_ts = min(timestamps)
        buckets = Counter()

        for ts in timestamps:
            bucket_idx = int((ts - min_ts).total_seconds() / bucket_seconds)
            buckets[bucket_idx] = buckets.get(bucket_idx, 0) + 1

        if not buckets:
            return []

        max_bucket = max(buckets.keys())
        timeline = []
        for i in range(min(max_bucket + 1, 288)):  # 最多 24 小时
            from datetime import timedelta
            bucket_time = min_ts + timedelta(seconds=i * bucket_seconds)
            timeline.append({
                "time": bucket_time.strftime("%H:%M"),
                "count": buckets.get(i, 0),
            })

        return timeline
',
    'python', 3400,
    '核心分析引擎 — 编排错误聚类/性能/异常子分析器', '🐍', 35,
    1, 0, 1748275200000, 0, 1748275200000, 0
) ON CONFLICT (tenant_id, skill_api_key, version, path) WHERE delete_flg = 0 DO NOTHING;

-- ── 3.7 scripts/error_cluster.py — 错误聚类 ──

INSERT INTO ai_skill_resource (
    id, tenant_id, skill_api_key, version,
    parent_id, node_type, name, path, depth,
    content, content_type, content_size,
    description, icon, sort_num,
    enabled_flg, delete_flg, created_at, created_by, updated_at, updated_by
) VALUES (
    4000000000001016, 0, 'log-analyzer', '1.0.0',
    4000000000001001, 'file', 'error_cluster.py', 'scripts/error_cluster.py', 1,
    '"""错误日志聚类分析

将相似的错误消息聚合为模式，识别 Top N 错误类型。
使用文本相似度（TF-IDF + 余弦相似度）进行聚类。
"""
import re
from collections import defaultdict
from typing import Optional

import numpy as np

from config import AnalysisConfig
from models import LogEntry, ErrorCluster


class ErrorClusterer:
    """错误聚类器 — 基于文本相似度"""

    def __init__(self, config: AnalysisConfig):
        self.config = config
        self._pattern_cache: dict[str, str] = {}

    def cluster(self, error_entries: list[LogEntry]) -> dict:
        """对错误日志进行聚类"""
        if not error_entries:
            return {"total_errors": 0, "clusters": []}

        # 提取错误模式
        patterns = defaultdict(list)
        for entry in error_entries:
            pattern = self._extract_pattern(entry.message)
            patterns[pattern].append(entry)

        # 构建聚类结果
        clusters = []
        for idx, (pattern, entries) in enumerate(
            sorted(patterns.items(), key=lambda x: len(x[1]), reverse=True)
        ):
            if idx >= self.config.max_clusters:
                break
            if len(entries) < self.config.min_cluster_size:
                continue

            timestamps = [e.timestamp for e in entries if e.timestamp]
            loggers = list(set(e.logger for e in entries if e.logger))

            cluster = ErrorCluster(
                cluster_id=idx + 1,
                pattern=pattern,
                count=len(entries),
                first_seen=min(timestamps) if timestamps else None,
                last_seen=max(timestamps) if timestamps else None,
                sample_messages=[e.message[:self.config.truncate_message_length]
                                 for e in entries[:self.config.max_sample_lines]],
                affected_loggers=loggers,
                severity=self._assess_severity(entries),
            )
            clusters.append(cluster)

        return {
            "total_errors": len(error_entries),
            "unique_patterns": len(patterns),
            "clusters": [c.to_dict() for c in clusters[:self.config.top_n]],
        }

    def _extract_pattern(self, message: str) -> str:
        """提取错误消息的模式（去除变量部分）"""
        if message in self._pattern_cache:
            return self._pattern_cache[message]

        pattern = message
        # 替换数字为占位符
        pattern = re.sub(r''\b\d+\b'', ''<NUM>'', pattern)
        # 替换 UUID
        pattern = re.sub(
            r''[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}'',
            ''<UUID>'', pattern, flags=re.IGNORECASE
        )
        # 替换 IP 地址
        pattern = re.sub(r''\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}'', ''<IP>'', pattern)
        # 替换文件路径
        pattern = re.sub(r''/[\w./\-]+'', ''<PATH>'', pattern)
        # 替换引号内的变量内容
        pattern = re.sub(r''\"[^\"]{20,}\"'', ''\"<VAR>\"'', pattern)
        # 截断
        if len(pattern) > self.config.truncate_message_length:
            pattern = pattern[:self.config.truncate_message_length] + "..."

        self._pattern_cache[message] = pattern
        return pattern

    def _assess_severity(self, entries: list[LogEntry]) -> str:
        """评估错误严重度"""
        levels = [e.level for e in entries]
        if "FATAL" in levels or "CRITICAL" in levels:
            return "CRITICAL"
        if len(entries) > 100:
            return "HIGH"
        if len(entries) > 10:
            return "MEDIUM"
        return "LOW"
',
    'python', 3200,
    '错误聚类 — 基于文本模式提取和相似度聚合', '🐍', 40,
    1, 0, 1748275200000, 0, 1748275200000, 0
) ON CONFLICT (tenant_id, skill_api_key, version, path) WHERE delete_flg = 0 DO NOTHING;


-- ── 3.8 scripts/performance.py — 性能分析 ──

INSERT INTO ai_skill_resource (
    id, tenant_id, skill_api_key, version,
    parent_id, node_type, name, path, depth,
    content, content_type, content_size,
    description, icon, sort_num,
    enabled_flg, delete_flg, created_at, created_by, updated_at, updated_by
) VALUES (
    4000000000001017, 0, 'log-analyzer', '1.0.0',
    4000000000001001, 'file', 'performance.py', 'scripts/performance.py', 1,
    '"""性能瓶颈分析

分析请求延迟分布，识别慢请求和性能瓶颈。
"""
from collections import defaultdict

import numpy as np

from config import AnalysisConfig
from models import LogEntry, PerformanceMetrics


class PerformanceAnalyzer:
    """性能分析器 — 延迟分布与慢请求识别"""

    def __init__(self, config: AnalysisConfig):
        self.config = config

    def analyze(self, entries: list[LogEntry]) -> dict:
        """分析性能指标"""
        # 按 endpoint 分组
        endpoint_durations = defaultdict(list)
        endpoint_errors = defaultdict(int)

        for entry in entries:
            duration = entry.duration_ms
            if duration is None:
                continue

            # 提取 endpoint（从 extra 中获取 path 或 method+path）
            endpoint = self._extract_endpoint(entry)
            endpoint_durations[endpoint].append(duration)

            if entry.status_code and entry.status_code >= 400:
                endpoint_errors[endpoint] += 1

        if not endpoint_durations:
            return {"message": "未找到包含耗时信息的日志条目", "endpoints": []}

        # 计算各 endpoint 的性能指标
        metrics_list = []
        for endpoint, durations in endpoint_durations.items():
            arr = np.array(durations)
            count = len(arr)

            metrics = PerformanceMetrics(
                endpoint=endpoint,
                count=count,
                p50_ms=float(np.percentile(arr, 50)),
                p75_ms=float(np.percentile(arr, 75)),
                p90_ms=float(np.percentile(arr, 90)),
                p95_ms=float(np.percentile(arr, 95)),
                p99_ms=float(np.percentile(arr, 99)),
                max_ms=float(arr.max()),
                error_rate=endpoint_errors.get(endpoint, 0) / count,
                slow_count=int(np.sum(arr > self.config.slow_threshold_ms)),
            )
            metrics_list.append(metrics)

        # 按 P95 排序
        metrics_list.sort(key=lambda m: m.p95_ms, reverse=True)

        # 全局统计
        all_durations = np.concatenate(
            [np.array(d) for d in endpoint_durations.values()]
        )

        return {
            "total_requests": len(all_durations),
            "global_p50_ms": round(float(np.percentile(all_durations, 50)), 2),
            "global_p95_ms": round(float(np.percentile(all_durations, 95)), 2),
            "global_p99_ms": round(float(np.percentile(all_durations, 99)), 2),
            "slow_requests": int(np.sum(all_durations > self.config.slow_threshold_ms)),
            "slow_rate": round(
                float(np.sum(all_durations > self.config.slow_threshold_ms)) / len(all_durations), 4
            ),
            "endpoints": [m.to_dict() for m in metrics_list[:self.config.top_n]],
        }

    def _extract_endpoint(self, entry: LogEntry) -> str:
        """从日志条目提取 endpoint"""
        path = entry.extra.get("path") or entry.extra.get("url") or ""
        method = entry.extra.get("method") or ""

        if not path:
            # 尝试从 message 中提取
            return entry.logger or "unknown"

        # 归一化路径（去除查询参数和路径变量）
        path = self._normalize_path(path)

        if method:
            return f"{method} {path}"
        return path

    @staticmethod
    def _normalize_path(path: str) -> str:
        """归一化 URL 路径（替换数字 ID 为占位符）"""
        import re
        # 去除查询参数
        path = path.split("?")[0]
        # 替换纯数字路径段
        path = re.sub(r''/\d+'', ''/:id'', path)
        # 替换 UUID 路径段
        path = re.sub(
            r''/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}'',
            ''/:uuid'', path, flags=re.IGNORECASE
        )
        return path
',
    'python', 3300,
    '性能分析 — 延迟百分位、慢请求识别、endpoint 归一化', '🐍', 45,
    1, 0, 1748275200000, 0, 1748275200000, 0
) ON CONFLICT (tenant_id, skill_api_key, version, path) WHERE delete_flg = 0 DO NOTHING;

-- ── 3.9 scripts/anomaly.py — 异常检测 ──

INSERT INTO ai_skill_resource (
    id, tenant_id, skill_api_key, version,
    parent_id, node_type, name, path, depth,
    content, content_type, content_size,
    description, icon, sort_num,
    enabled_flg, delete_flg, created_at, created_by, updated_at, updated_by
) VALUES (
    4000000000001018, 0, 'log-analyzer', '1.0.0',
    4000000000001001, 'file', 'anomaly.py', 'scripts/anomaly.py', 1,
    '"""异常模式检测

基于统计方法检测日志中的异常模式：
- 流量突增/突降（Z-Score）
- 错误率突变
- 周期性异常
"""
from collections import Counter, defaultdict
from datetime import datetime, timedelta

import numpy as np

from config import AnalysisConfig
from models import LogEntry, AnomalyEvent


class AnomalyDetector:
    """异常检测器 — 基于统计方法"""

    def __init__(self, config: AnalysisConfig):
        self.config = config

    def detect(self, entries: list[LogEntry]) -> dict:
        """检测异常模式"""
        anomalies = []

        # 1. 流量异常（每分钟请求量的 Z-Score）
        volume_anomalies = self._detect_volume_anomalies(entries)
        anomalies.extend(volume_anomalies)

        # 2. 错误率异常
        error_anomalies = self._detect_error_rate_anomalies(entries)
        anomalies.extend(error_anomalies)

        # 3. 延迟异常
        latency_anomalies = self._detect_latency_anomalies(entries)
        anomalies.extend(latency_anomalies)

        # 按 Z-Score 绝对值排序
        anomalies.sort(key=lambda a: abs(a.zscore), reverse=True)

        return {
            "total_anomalies": len(anomalies),
            "by_type": self._group_by_type(anomalies),
            "events": [a.to_dict() for a in anomalies[:self.config.top_n * 2]],
        }

    def _detect_volume_anomalies(self, entries: list[LogEntry]) -> list[AnomalyEvent]:
        """检测流量突增/突降"""
        time_series = self._build_time_series(entries, "volume")
        if len(time_series) < self.config.anomaly_min_data_points:
            return []

        values = np.array([v for _, v in time_series])
        mean = values.mean()
        std = values.std()

        if std == 0:
            return []

        anomalies = []
        for timestamp, value in time_series:
            zscore = (value - mean) / std
            if abs(zscore) > self.config.anomaly_zscore_threshold:
                anomaly_type = "spike" if zscore > 0 else "drop"
                anomalies.append(AnomalyEvent(
                    timestamp=timestamp,
                    metric="request_volume",
                    expected_value=mean,
                    actual_value=value,
                    zscore=zscore,
                    anomaly_type=anomaly_type,
                    description=f"流量{'突增' if anomaly_type == 'spike' else '突降'}: "
                                f"期望 {mean:.0f}/min, 实际 {value:.0f}/min",
                ))

        return anomalies

    def _detect_error_rate_anomalies(self, entries: list[LogEntry]) -> list[AnomalyEvent]:
        """检测错误率突变"""
        time_series = self._build_time_series(entries, "error_rate")
        if len(time_series) < self.config.anomaly_min_data_points:
            return []

        values = np.array([v for _, v in time_series])
        mean = values.mean()
        std = values.std()

        if std == 0:
            return []

        anomalies = []
        for timestamp, value in time_series:
            zscore = (value - mean) / std
            if zscore > self.config.anomaly_zscore_threshold:  # 只关注错误率上升
                anomalies.append(AnomalyEvent(
                    timestamp=timestamp,
                    metric="error_rate",
                    expected_value=mean,
                    actual_value=value,
                    zscore=zscore,
                    anomaly_type="spike",
                    description=f"错误率突增: 期望 {mean:.2%}, 实际 {value:.2%}",
                ))

        return anomalies

    def _detect_latency_anomalies(self, entries: list[LogEntry]) -> list[AnomalyEvent]:
        """检测延迟异常"""
        time_series = self._build_time_series(entries, "latency_p95")
        if len(time_series) < self.config.anomaly_min_data_points:
            return []

        values = np.array([v for _, v in time_series])
        mean = values.mean()
        std = values.std()

        if std == 0:
            return []

        anomalies = []
        for timestamp, value in time_series:
            zscore = (value - mean) / std
            if zscore > self.config.anomaly_zscore_threshold:
                anomalies.append(AnomalyEvent(
                    timestamp=timestamp,
                    metric="latency_p95",
                    expected_value=mean,
                    actual_value=value,
                    zscore=zscore,
                    anomaly_type="spike",
                    description=f"P95 延迟突增: 期望 {mean:.0f}ms, 实际 {value:.0f}ms",
                ))

        return anomalies

    def _build_time_series(
        self, entries: list[LogEntry], metric: str
    ) -> list[tuple[datetime, float]]:
        """构建时间序列"""
        bucket_seconds = self.config.time_bucket_minutes * 60
        timestamps = [e.timestamp for e in entries if e.timestamp]
        if not timestamps:
            return []

        min_ts = min(timestamps)
        buckets = defaultdict(list)

        for entry in entries:
            if not entry.timestamp:
                continue
            bucket_idx = int((entry.timestamp - min_ts).total_seconds() / bucket_seconds)
            buckets[bucket_idx].append(entry)

        series = []
        for idx in sorted(buckets.keys()):
            bucket_entries = buckets[idx]
            bucket_time = min_ts + timedelta(seconds=idx * bucket_seconds)

            if metric == "volume":
                series.append((bucket_time, float(len(bucket_entries))))
            elif metric == "error_rate":
                errors = sum(1 for e in bucket_entries if e.is_error)
                rate = errors / len(bucket_entries) if bucket_entries else 0
                series.append((bucket_time, rate))
            elif metric == "latency_p95":
                durations = [e.duration_ms for e in bucket_entries if e.duration_ms is not None]
                if durations:
                    p95 = float(np.percentile(durations, 95))
                    series.append((bucket_time, p95))

        return series

    @staticmethod
    def _group_by_type(anomalies: list[AnomalyEvent]) -> dict:
        """按类型分组统计"""
        groups = Counter(a.anomaly_type for a in anomalies)
        return dict(groups)
',
    'python', 4800,
    '异常检测 — 流量突变/错误率突增/延迟异常（Z-Score）', '🐍', 50,
    1, 0, 1748275200000, 0, 1748275200000, 0
) ON CONFLICT (tenant_id, skill_api_key, version, path) WHERE delete_flg = 0 DO NOTHING;


-- ── 3.10 scripts/reporter.py — 报告生成 ──

INSERT INTO ai_skill_resource (
    id, tenant_id, skill_api_key, version,
    parent_id, node_type, name, path, depth,
    content, content_type, content_size,
    description, icon, sort_num,
    enabled_flg, delete_flg, created_at, created_by, updated_at, updated_by
) VALUES (
    4000000000001019, 0, 'log-analyzer', '1.0.0',
    4000000000001001, 'file', 'reporter.py', 'scripts/reporter.py', 1,
    '"""分析报告生成器

将分析结果格式化为 Markdown 或 JSON 报告。
"""
from datetime import datetime
from typing import Any


class ReportGenerator:
    """报告生成器"""

    def __init__(self, format: str = "markdown"):
        self.format = format

    def generate(self, result: dict) -> str:
        """生成分析报告"""
        if self.format == "markdown":
            return self._generate_markdown(result)
        return self._generate_text(result)

    def _generate_markdown(self, result: dict) -> str:
        """生成 Markdown 格式报告"""
        lines = []
        lines.append("# 📋 日志分析报告")
        lines.append(f"\n> 生成时间: {datetime.now().strftime(''%Y-%m-%d %H:%M:%S'')}")
        lines.append("")

        # 基础统计
        stats = result.get("stats", {})
        if stats:
            lines.append("## 📊 概览")
            lines.append("")
            lines.append(f"| 指标 | 值 |")
            lines.append(f"|------|-----|")
            lines.append(f"| 总条目数 | {stats.get(''total'', 0):,} |")
            lines.append(f"| 错误数 | {stats.get(''error_count'', 0):,} |")
            lines.append(f"| 告警数 | {stats.get(''warning_count'', 0):,} |")
            lines.append(f"| 错误率 | {stats.get(''error_rate'', 0):.2%} |")

            time_range = stats.get("time_range", {})
            if time_range:
                lines.append(f"| 时间范围 | {time_range.get(''start'', ''N/A'')} ~ {time_range.get(''end'', ''N/A'')} |")
            lines.append("")

            # 级别分布
            level_dist = stats.get("level_distribution", {})
            if level_dist:
                lines.append("### 日志级别分布")
                lines.append("")
                for level, count in level_dist.items():
                    pct = count / stats["total"] * 100 if stats["total"] else 0
                    bar = "█" * int(pct / 2)
                    lines.append(f"- **{level}**: {count:,} ({pct:.1f}%) {bar}")
                lines.append("")

        # 错误聚类
        errors = result.get("error_clusters", {})
        if errors and errors.get("clusters"):
            lines.append("## 🔴 错误聚类")
            lines.append("")
            lines.append(f"共 {errors[''total_errors'']} 个错误，归为 {errors[''unique_patterns'']} 种模式")
            lines.append("")
            for cluster in errors["clusters"]:
                lines.append(f"### #{cluster[''cluster_id'']} [{cluster[''severity'']}] (×{cluster[''count'']})")
                lines.append(f"**模式**: `{cluster[''pattern'']}`")
                if cluster.get("first_seen"):
                    lines.append(f"**时间**: {cluster[''first_seen'']} ~ {cluster[''last_seen'']}")
                if cluster.get("sample_messages"):
                    lines.append("**示例**:")
                    for msg in cluster["sample_messages"][:2]:
                        lines.append(f"  - `{msg}`")
                lines.append("")

        # 性能分析
        perf = result.get("performance", {})
        if perf and perf.get("endpoints"):
            lines.append("## ⚡ 性能分析")
            lines.append("")
            lines.append(f"| 指标 | 值 |")
            lines.append(f"|------|-----|")
            lines.append(f"| 总请求数 | {perf.get(''total_requests'', 0):,} |")
            lines.append(f"| 全局 P50 | {perf.get(''global_p50_ms'', 0):.0f}ms |")
            lines.append(f"| 全局 P95 | {perf.get(''global_p95_ms'', 0):.0f}ms |")
            lines.append(f"| 全局 P99 | {perf.get(''global_p99_ms'', 0):.0f}ms |")
            lines.append(f"| 慢请求数 | {perf.get(''slow_requests'', 0):,} ({perf.get(''slow_rate'', 0):.2%}) |")
            lines.append("")
            lines.append("### Top 慢 Endpoint")
            lines.append("")
            lines.append("| Endpoint | 请求数 | P95 | P99 | 慢请求 |")
            lines.append("|----------|--------|-----|-----|--------|")
            for ep in perf["endpoints"][:10]:
                lines.append(
                    f"| {ep[''endpoint'']} | {ep[''count'']} | "
                    f"{ep[''p95_ms'']:.0f}ms | {ep[''p99_ms'']:.0f}ms | {ep[''slow_count'']} |"
                )
            lines.append("")

        # 异常事件
        anomalies = result.get("anomalies", {})
        if anomalies and anomalies.get("events"):
            lines.append("## ⚠️ 异常事件")
            lines.append("")
            lines.append(f"共检测到 {anomalies[''total_anomalies'']} 个异常")
            by_type = anomalies.get("by_type", {})
            if by_type:
                lines.append(f"- 突增: {by_type.get(''spike'', 0)} 次")
                lines.append(f"- 突降: {by_type.get(''drop'', 0)} 次")
            lines.append("")
            for event in anomalies["events"][:5]:
                lines.append(f"- **[{event[''anomaly_type'']}]** {event[''description'']}")
                if event.get("timestamp"):
                    lines.append(f"  时间: {event[''timestamp'']}, Z-Score: {event[''zscore'']:.1f}")
            lines.append("")

        return "\n".join(lines)

    def _generate_text(self, result: dict) -> str:
        """生成纯文本格式报告"""
        lines = []
        stats = result.get("stats", {})
        lines.append(f"=== 日志分析报告 ===")
        lines.append(f"总条目: {stats.get(''total'', 0)}")
        lines.append(f"错误数: {stats.get(''error_count'', 0)}")
        lines.append(f"错误率: {stats.get(''error_rate'', 0):.2%}")
        return "\n".join(lines)
',
    'python', 4600,
    '报告生成器 — Markdown/Text 格式化输出', '🐍', 55,
    1, 0, 1748275200000, 0, 1748275200000, 0
) ON CONFLICT (tenant_id, skill_api_key, version, path) WHERE delete_flg = 0 DO NOTHING;

-- ── 3.11 scripts/filters.py — 日志过滤器 ──

INSERT INTO ai_skill_resource (
    id, tenant_id, skill_api_key, version,
    parent_id, node_type, name, path, depth,
    content, content_type, content_size,
    description, icon, sort_num,
    enabled_flg, delete_flg, created_at, created_by, updated_at, updated_by
) VALUES (
    4000000000001020, 0, 'log-analyzer', '1.0.0',
    4000000000001001, 'file', 'filters.py', 'scripts/filters.py', 1,
    '"""日志过滤器

支持按时间范围、日志级别、关键词、正则表达式过滤日志条目。
"""
import re
from datetime import datetime, timedelta
from typing import Optional

from dateutil import parser as date_parser

from config import AnalysisConfig
from models import LogEntry


class LogFilter:
    """日志过滤器"""

    def __init__(self, config: AnalysisConfig):
        self.config = config

    def apply(self, entries: list[LogEntry], filter_expr: str) -> list[LogEntry]:
        """应用过滤表达式

        支持的过滤语法：
        - 日期: "2024-01-15" 或 "2024-01-15 10:00~12:00"
        - 级别: "level:ERROR" 或 "level:ERROR,WARN"
        - 关键词: "keyword:timeout"
        - 正则: "regex:Connection.*refused"
        - 组合: "2024-01-15 level:ERROR keyword:timeout"
        """
        if not filter_expr.strip():
            return entries

        filters = self._parse_filter_expr(filter_expr)
        result = entries

        for filter_type, filter_value in filters:
            if filter_type == "time_range":
                result = self._filter_by_time(result, filter_value)
            elif filter_type == "level":
                result = self._filter_by_level(result, filter_value)
            elif filter_type == "keyword":
                result = self._filter_by_keyword(result, filter_value)
            elif filter_type == "regex":
                result = self._filter_by_regex(result, filter_value)

        return result

    def _parse_filter_expr(self, expr: str) -> list[tuple[str, str]]:
        """解析过滤表达式"""
        filters = []
        parts = expr.split()
        i = 0

        while i < len(parts):
            part = parts[i]

            if part.startswith("level:"):
                filters.append(("level", part[6:]))
            elif part.startswith("keyword:"):
                filters.append(("keyword", part[8:]))
            elif part.startswith("regex:"):
                # 正则可能包含空格，取到末尾
                regex_parts = [part[6:]]
                while i + 1 < len(parts) and not parts[i + 1].startswith(("level:", "keyword:", "regex:")):
                    i += 1
                    regex_parts.append(parts[i])
                filters.append(("regex", " ".join(regex_parts)))
            else:
                # 尝试解析为日期/时间
                time_str = part
                # 检查下一个 part 是否是时间部分
                if i + 1 < len(parts) and re.match(r''^\d{2}:\d{2}'', parts[i + 1]):
                    i += 1
                    time_str += " " + parts[i]
                filters.append(("time_range", time_str))

            i += 1

        return filters

    def _filter_by_time(self, entries: list[LogEntry], time_str: str) -> list[LogEntry]:
        """按时间范围过滤"""
        start_time, end_time = self._parse_time_range(time_str)
        if start_time is None:
            return entries

        return [
            e for e in entries
            if e.timestamp and start_time <= e.timestamp <= (end_time or datetime.max)
        ]

    def _filter_by_level(self, entries: list[LogEntry], levels_str: str) -> list[LogEntry]:
        """按日志级别过滤"""
        levels = set(l.strip().upper() for l in levels_str.split(","))
        return [e for e in entries if e.level in levels]

    def _filter_by_keyword(self, entries: list[LogEntry], keyword: str) -> list[LogEntry]:
        """按关键词过滤（不区分大小写）"""
        keyword_lower = keyword.lower()
        return [e for e in entries if keyword_lower in e.message.lower()]

    def _filter_by_regex(self, entries: list[LogEntry], pattern: str) -> list[LogEntry]:
        """按正则表达式过滤"""
        try:
            compiled = re.compile(pattern, re.IGNORECASE)
            return [e for e in entries if compiled.search(e.message)]
        except re.error:
            return entries  # 正则无效时不过滤

    def _parse_time_range(self, time_str: str) -> tuple[Optional[datetime], Optional[datetime]]:
        """解析时间范围字符串"""
        # 处理范围格式: "10:00~12:00" 或 "2024-01-15~2024-01-16"
        if "~" in time_str:
            parts = time_str.split("~")
            try:
                start = date_parser.parse(parts[0].strip())
                end = date_parser.parse(parts[1].strip())
                return start, end
            except (ValueError, IndexError):
                return None, None

        # 单个日期/时间
        try:
            dt = date_parser.parse(time_str)
            # 如果只有日期，范围为整天
            if dt.hour == 0 and dt.minute == 0 and dt.second == 0:
                return dt, dt + timedelta(days=1)
            # 如果有时间，范围为 ±30 分钟
            return dt - timedelta(minutes=30), dt + timedelta(minutes=30)
        except ValueError:
            return None, None
',
    'python', 4100,
    '日志过滤器 — 时间/级别/关键词/正则组合过滤', '🐍', 60,
    1, 0, 1748275200000, 0, 1748275200000, 0
) ON CONFLICT (tenant_id, skill_api_key, version, path) WHERE delete_flg = 0 DO NOTHING;


-- ── 3.12 scripts/utils.py — 工具函数 ──

INSERT INTO ai_skill_resource (
    id, tenant_id, skill_api_key, version,
    parent_id, node_type, name, path, depth,
    content, content_type, content_size,
    description, icon, sort_num,
    enabled_flg, delete_flg, created_at, created_by, updated_at, updated_by
) VALUES (
    4000000000001021, 0, 'log-analyzer', '1.0.0',
    4000000000001001, 'file', 'utils.py', 'scripts/utils.py', 1,
    '"""通用工具函数"""
import hashlib
import logging
import sys
from pathlib import Path
from typing import Optional


def setup_logging(name: str, level: str = "INFO") -> logging.Logger:
    """配置日志"""
    logger = logging.getLogger(name)
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))

    if not logger.handlers:
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%H:%M:%S"
        ))
        logger.addHandler(handler)

    return logger


def format_duration(seconds: float) -> str:
    """格式化时长为人类可读格式"""
    if seconds < 1:
        return f"{seconds * 1000:.0f}ms"
    if seconds < 60:
        return f"{seconds:.1f}s"
    minutes = int(seconds // 60)
    secs = seconds % 60
    return f"{minutes}m {secs:.0f}s"


def format_bytes(size: int) -> str:
    """格式化字节数"""
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024:
            return f"{size:.1f}{unit}"
        size /= 1024
    return f"{size:.1f}TB"


def file_hash(filepath: str) -> str:
    """计算文件 MD5 哈希"""
    h = hashlib.md5()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def truncate_text(text: str, max_length: int = 200) -> str:
    """截断文本"""
    if len(text) <= max_length:
        return text
    return text[:max_length - 3] + "..."


def safe_divide(numerator: float, denominator: float, default: float = 0.0) -> float:
    """安全除法"""
    if denominator == 0:
        return default
    return numerator / denominator


def count_lines(filepath: str) -> int:
    """快速统计文件行数"""
    count = 0
    with open(filepath, "rb") as f:
        for _ in f:
            count += 1
    return count


def detect_encoding(filepath: str) -> str:
    """检测文件编码（简单启发式）"""
    try:
        with open(filepath, "rb") as f:
            raw = f.read(4096)

        # BOM 检测
        if raw.startswith(b"\\xef\\xbb\\xbf"):
            return "utf-8-sig"
        if raw.startswith(b"\\xff\\xfe"):
            return "utf-16-le"

        # 尝试 UTF-8 解码
        try:
            raw.decode("utf-8")
            return "utf-8"
        except UnicodeDecodeError:
            pass

        # 尝试 GBK
        try:
            raw.decode("gbk")
            return "gbk"
        except UnicodeDecodeError:
            pass

        return "utf-8"  # 默认
    except IOError:
        return "utf-8"
',
    'python', 2200,
    '通用工具函数 — 日志配置、格式化、编码检测', '🐍', 65,
    1, 0, 1748275200000, 0, 1748275200000, 0
) ON CONFLICT (tenant_id, skill_api_key, version, path) WHERE delete_flg = 0 DO NOTHING;

-- ── 3.13 scripts/requirements.txt — 依赖声明 ──

INSERT INTO ai_skill_resource (
    id, tenant_id, skill_api_key, version,
    parent_id, node_type, name, path, depth,
    content, content_type, content_size,
    description, icon, sort_num,
    enabled_flg, delete_flg, created_at, created_by, updated_at, updated_by
) VALUES (
    4000000000001022, 0, 'log-analyzer', '1.0.0',
    4000000000001001, 'file', 'requirements.txt', 'scripts/requirements.txt', 1,
    'pandas>=2.0
numpy>=1.24
scikit-learn>=1.3
python-dateutil>=2.8
',
    'text', 68,
    'Python 依赖声明', '📋', 99,
    1, 0, 1748275200000, 0, 1748275200000, 0
) ON CONFLICT (tenant_id, skill_api_key, version, path) WHERE delete_flg = 0 DO NOTHING;

-- ── 3.14 references/usage-guide.md — 使用说明 ──

INSERT INTO ai_skill_resource (
    id, tenant_id, skill_api_key, version,
    parent_id, node_type, name, path, depth,
    content, content_type, content_size,
    description, icon, sort_num,
    enabled_flg, delete_flg, created_at, created_by, updated_at, updated_by
) VALUES (
    4000000000001031, 0, 'log-analyzer', '1.0.0',
    4000000000001002, 'file', 'usage-guide.md', 'references/usage-guide.md', 1,
    '# 智能日志分析 — 使用指南

## 支持的日志格式

| 格式 | 自动检测 | 示例 |
|------|---------|------|
| Nginx Access | ✅ | `192.168.1.1 - - [25/May/2025:10:00:00 +0800] "GET /api/users HTTP/1.1" 200 1234` |
| Nginx Error | ✅ | `2025/05/25 10:00:00 [error] 1234#0: *5678 connect() failed` |
| Java Logback | ✅ | `2025-05-25 10:00:00.123 ERROR [main] c.e.Service - NullPointerException` |
| Python logging | ✅ | `2025-05-25 10:00:00,123 ERROR myapp Connection refused` |
| JSON Lines | ✅ | `{"timestamp":"2025-05-25T10:00:00Z","level":"ERROR","message":"..."}` |

## 分析模式

### full（完整分析）
包含所有子分析：统计概览 + 错误聚类 + 性能分析 + 异常检测

### errors（错误聚类）
- 提取错误消息模式（去除变量部分）
- 按相似度聚合为错误类型
- 输出 Top N 错误模式、影响范围、时间线

### performance（性能分析）
- 按 endpoint 分组计算延迟百分位
- 识别慢请求（默认阈值 1000ms）
- 输出 P50/P75/P90/P95/P99 和错误率

### anomaly（异常检测）
- 流量突增/突降检测（Z-Score > 3）
- 错误率突变检测
- 延迟异常检测

### stats（统计概览）
- 日志级别分布
- 时间范围
- QPS 时间线
- Top Logger

## 过滤语法

```
# 按日期
python3 main.py --input app.log --filter "2024-01-15"

# 按时间范围
python3 main.py --input app.log --filter "10:00~12:00"

# 按级别
python3 main.py --input app.log --filter "level:ERROR,WARN"

# 按关键词
python3 main.py --input app.log --filter "keyword:timeout"

# 按正则
python3 main.py --input app.log --filter "regex:Connection.*refused"

# 组合过滤
python3 main.py --input app.log --filter "2024-01-15 level:ERROR keyword:database"
```

## 大文件处理

- 文件 > 100MB 时自动启用采样（采样率 = 100MB / 文件大小）
- 可通过 `--sample-rate 0.5` 手动指定采样率
- 采样结果中会标注采样率，统计值按比例还原

## 输出字段说明

### stats
- `total`: 总条目数
- `error_rate`: 错误率
- `level_distribution`: 各级别数量
- `qps_timeline`: 每 5 分钟请求量

### error_clusters
- `pattern`: 错误模式（变量已替换为占位符）
- `count`: 出现次数
- `severity`: 严重度（CRITICAL/HIGH/MEDIUM/LOW）
- `first_seen` / `last_seen`: 首次/末次出现时间

### performance
- `global_p95_ms`: 全局 P95 延迟
- `slow_rate`: 慢请求占比
- `endpoints[].p95_ms`: 各 endpoint 的 P95

### anomalies
- `anomaly_type`: spike（突增）/ drop（突降）
- `zscore`: 偏离程度（越大越异常）
- `expected_value` / `actual_value`: 期望值 vs 实际值
',
    'md', 2800,
    '使用指南 — 格式说明、分析模式、过滤语法、输出字段', '📖', 10,
    1, 0, 1748275200000, 0, 1748275200000, 0
) ON CONFLICT (tenant_id, skill_api_key, version, path) WHERE delete_flg = 0 DO NOTHING;

-- ═══════════════════════════════════════════════════════════
-- 4. 验证查询
-- ═══════════════════════════════════════════════════════════

-- 验证 1: 主记录
-- SELECT api_key, name, current_version, category
-- FROM ai_skill WHERE api_key = 'log-analyzer' AND delete_flg = 0;

-- 验证 2: 版本内容
-- SELECT skill_api_key, version, context, allowed_tools
-- FROM ai_skill_definition
-- WHERE skill_api_key = 'log-analyzer' AND delete_flg = 0;

-- 验证 3: 资源文件树（应有 12 个 Python 文件 + 1 个 txt + 1 个 md = 14 文件）
-- SELECT node_type, path, name, content_type, content_size
-- FROM ai_skill_resource
-- WHERE skill_api_key = 'log-analyzer' AND version = '1.0.0' AND delete_flg = 0
-- ORDER BY node_type DESC, depth, sort_num;

-- 预期输出:
-- node_type | path                      | name              | content_type
-- dir       | scripts                   | scripts           | dir
-- dir       | references                | references        | dir
-- file      | scripts/main.py           | main.py           | python
-- file      | scripts/config.py         | config.py         | python
-- file      | scripts/parser.py         | parser.py         | python
-- file      | scripts/models.py         | models.py         | python
-- file      | scripts/analyzer.py       | analyzer.py       | python
-- file      | scripts/error_cluster.py  | error_cluster.py  | python
-- file      | scripts/performance.py    | performance.py    | python
-- file      | scripts/anomaly.py        | anomaly.py        | python
-- file      | scripts/reporter.py       | reporter.py       | python
-- file      | scripts/filters.py        | filters.py        | python
-- file      | scripts/utils.py          | utils.py          | python
-- file      | scripts/requirements.txt  | requirements.txt  | text
-- file      | references/usage-guide.md | usage-guide.md    | md

