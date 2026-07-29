"""
服务器 CPU 压力监控采集模块

通过方舟 DevOps 平台认证，获取 Prometheus 实例列表，查询各环境服务器 CPU 使用率。

链路：
  1. 方舟登录 → JWT Token
  2. 通过方舟 API 获取 Prometheus 实例列表（/monitor_api/prom/{id}）
  3. 直接查询 Prometheus API 获取 CPU 数据

配置读取：
  从 config/server_monitor.yaml 加载方舟账号、Prometheus 实例等配置
  支持环境变量覆盖: ARCA_USERNAME, ARCA_PASSWORD
"""
from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import httpx
import yaml

logger = logging.getLogger(__name__)

# 配置文件默认路径
_CONFIG_DIR = Path(__file__).resolve().parent.parent.parent / "config"
_DEFAULT_CONFIG_PATH = _CONFIG_DIR / "server_monitor.yaml"


# ═══════════════════════════════════════════════════════════
# 配置模型
# ═══════════════════════════════════════════════════════════


@dataclass
class ArcaConfig:
    """方舟 DevOps 平台配置"""
    base_url: str = "http://arca-devops.ingageapp.com"
    login_api: str = "/ac_api/user/login/"
    username: str = ""
    password: str = ""


@dataclass
class PrometheusInstance:
    """单个 Prometheus 实例"""
    id: int = 0
    name: str = ""
    url: str = ""
    remark: str = ""


@dataclass
class MonitorConfig:
    """监控采集配置"""
    arca: ArcaConfig = field(default_factory=ArcaConfig)
    prometheus_instances: list[PrometheusInstance] = field(default_factory=list)
    # 查询参数
    cpu_query: str = '100 - (avg by(instance) (rate(node_cpu_seconds_total{mode="idle"}[5m])) * 100)'
    query_timeout: float = 10.0
    # 自动发现实例（通过方舟 API）
    auto_discover: bool = True
    discover_id_range: tuple[int, int] = (1, 20)


def load_monitor_config(config_path: Optional[str] = None) -> MonitorConfig:
    """从 YAML 配置文件加载监控配置，支持环境变量覆盖"""
    path = Path(config_path) if config_path else _DEFAULT_CONFIG_PATH
    config = MonitorConfig()

    if path.exists():
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        logger.info("加载监控配置: %s", path)

        # 解析 arca 配置
        arca_raw = raw.get("arca", {})
        config.arca = ArcaConfig(
            base_url=arca_raw.get("base_url", config.arca.base_url),
            login_api=arca_raw.get("login_api", config.arca.login_api),
            username=arca_raw.get("username", ""),
            password=arca_raw.get("password", ""),
        )

        # 解析 prometheus 实例
        for inst in raw.get("prometheus_instances", []):
            config.prometheus_instances.append(PrometheusInstance(
                id=inst.get("id", 0),
                name=inst.get("name", ""),
                url=inst.get("url", ""),
                remark=inst.get("remark", ""),
            ))

        # 查询参数
        config.cpu_query = raw.get("cpu_query", config.cpu_query)
        config.query_timeout = raw.get("query_timeout", config.query_timeout)
        config.auto_discover = raw.get("auto_discover", config.auto_discover)

        id_range = raw.get("discover_id_range", [1, 20])
        if isinstance(id_range, list) and len(id_range) == 2:
            config.discover_id_range = (id_range[0], id_range[1])
    else:
        logger.warning("监控配置文件不存在: %s，使用默认配置", path)

    # 环境变量覆盖（优先级最高）
    config.arca.username = os.getenv("ARCA_USERNAME", config.arca.username)
    config.arca.password = os.getenv("ARCA_PASSWORD", config.arca.password)
    config.arca.base_url = os.getenv("ARCA_BASE_URL", config.arca.base_url)

    return config


# ═══════════════════════════════════════════════════════════
# 方舟认证客户端
# ═══════════════════════════════════════════════════════════


class ArcaAuthClient:
    """方舟 DevOps 登录 + Token 管理"""

    def __init__(self, config: ArcaConfig):
        self._config = config
        self._token: str = ""
        self._token_expire: float = 0
        self._user_info: dict[str, Any] = {}

    @property
    def token(self) -> str:
        return self._token

    @property
    def is_authenticated(self) -> bool:
        return bool(self._token) and time.time() < self._token_expire

    def login(self) -> bool:
        """同步登录方舟平台，获取 JWT Token"""
        url = f"{self._config.base_url}{self._config.login_api}"
        payload = {
            "username": self._config.username,
            "password": self._config.password,
        }

        try:
            with httpx.Client(verify=False, timeout=10.0) as client:
                resp = client.post(url, json=payload,
                                   headers={"Content-Type": "application/json"})
                data = resp.json()
        except Exception as e:
            logger.error("方舟登录请求失败: %s", e)
            return False

        if data.get("code") != 2000:
            logger.error("方舟登录失败: %s", data.get("errmsg", "未知错误"))
            return False

        result = data["data"]
        self._token = result["token"]
        self._user_info = {
            "username": result.get("username", ""),
            "cn_name": result.get("cn_name", ""),
        }

        # 解析过期时间
        expire_str = result.get("expire", "")
        if expire_str:
            try:
                from datetime import datetime
                expire_dt = datetime.strptime(expire_str, "%Y-%m-%d %H:%M:%S")
                self._token_expire = expire_dt.timestamp()
            except ValueError:
                # 默认 24 小时后过期
                self._token_expire = time.time() + 86400
        else:
            self._token_expire = time.time() + 86400

        logger.info("方舟登录成功: %s (%s)", self._user_info["cn_name"], self._user_info["username"])
        return True

    def ensure_token(self) -> str:
        """确保 token 有效，过期则重新登录"""
        if not self.is_authenticated:
            if not self.login():
                raise RuntimeError("方舟平台登录失败，请检查账号配置")
        return self._token

    def get_headers(self) -> dict[str, str]:
        """获取带认证的请求头"""
        return {"Authorization": f"JWT {self.ensure_token()}"}


# ═══════════════════════════════════════════════════════════
# Prometheus 实例发现
# ═══════════════════════════════════════════════════════════


def discover_prometheus_instances(
    auth_client: ArcaAuthClient,
    config: MonitorConfig,
) -> list[PrometheusInstance]:
    """通过方舟 API 自动发现 Prometheus 实例"""
    instances: list[PrometheusInstance] = []
    base_url = config.arca.base_url
    headers = auth_client.get_headers()
    start_id, end_id = config.discover_id_range

    with httpx.Client(verify=False, timeout=config.query_timeout) as client:
        for prom_id in range(start_id, end_id + 1):
            try:
                resp = client.get(
                    f"{base_url}/monitor_api/prom/{prom_id}",
                    headers=headers,
                )
                data = resp.json()
                if data.get("code") == 2000 and isinstance(data.get("data"), dict):
                    info = data["data"]
                    instances.append(PrometheusInstance(
                        id=info["id"],
                        name=info.get("name", ""),
                        url=info.get("url", ""),
                        remark=info.get("remark", ""),
                    ))
            except Exception as e:
                logger.debug("探测 prom_id=%d 失败: %s", prom_id, e)

    logger.info("发现 %d 个 Prometheus 实例: %s",
                len(instances), [i.name for i in instances])
    return instances


# ═══════════════════════════════════════════════════════════
# CPU 数据采集
# ═══════════════════════════════════════════════════════════


@dataclass
class CpuMetric:
    """单节点 CPU 指标"""
    instance: str
    cpu_percent: float
    env: str = ""
    labels: dict[str, str] = field(default_factory=dict)


@dataclass
class EnvCpuReport:
    """单环境 CPU 报告"""
    env_name: str
    prom_url: str
    timestamp: float
    metrics: list[CpuMetric] = field(default_factory=list)
    error: str = ""

    @property
    def avg_cpu(self) -> float:
        if not self.metrics:
            return 0.0
        return sum(m.cpu_percent for m in self.metrics) / len(self.metrics)

    @property
    def max_cpu(self) -> float:
        if not self.metrics:
            return 0.0
        return max(m.cpu_percent for m in self.metrics)

    @property
    def node_count(self) -> int:
        return len(self.metrics)


class ServerMonitorCollector:
    """服务器 CPU 监控采集器

    Usage:
        collector = ServerMonitorCollector()
        collector.initialize()
        reports = collector.collect_all_cpu()
    """

    def __init__(self, config_path: Optional[str] = None):
        self._config = load_monitor_config(config_path)
        self._auth_client = ArcaAuthClient(self._config.arca)
        self._instances: list[PrometheusInstance] = []
        self._initialized = False

    @property
    def config(self) -> MonitorConfig:
        return self._config

    @property
    def instances(self) -> list[PrometheusInstance]:
        return self._instances

    def initialize(self) -> None:
        """初始化：登录 + 发现实例"""
        # 登录方舟
        self._auth_client.ensure_token()

        # 加载实例列表
        if self._config.prometheus_instances:
            self._instances = list(self._config.prometheus_instances)
            logger.info("使用配置文件中的 %d 个 Prometheus 实例", len(self._instances))
        elif self._config.auto_discover:
            self._instances = discover_prometheus_instances(
                self._auth_client, self._config)
        else:
            raise RuntimeError("未配置 Prometheus 实例且未开启自动发现")

        self._initialized = True

    def collect_cpu(self, instance: PrometheusInstance) -> EnvCpuReport:
        """采集单个环境的 CPU 数据"""
        report = EnvCpuReport(
            env_name=instance.name,
            prom_url=instance.url,
            timestamp=time.time(),
        )

        try:
            with httpx.Client(verify=False, timeout=self._config.query_timeout) as client:
                resp = client.get(
                    f"{instance.url}/api/v1/query",
                    params={"query": self._config.cpu_query},
                )
                data = resp.json()

            if data.get("status") != "success":
                report.error = f"Prometheus 查询失败: {data.get('error', 'unknown')}"
                return report

            for result in data["data"]["result"]:
                metric_labels = result.get("metric", {})
                value = float(result["value"][1])
                report.metrics.append(CpuMetric(
                    instance=metric_labels.get("instance", "unknown"),
                    cpu_percent=round(value, 2),
                    env=instance.name,
                    labels=metric_labels,
                ))

            # 按 CPU 使用率降序排列
            report.metrics.sort(key=lambda m: m.cpu_percent, reverse=True)

        except Exception as e:
            report.error = str(e)
            logger.error("采集 %s CPU 数据失败: %s", instance.name, e)

        return report

    def collect_all_cpu(self) -> list[EnvCpuReport]:
        """采集所有环境的 CPU 数据"""
        if not self._initialized:
            self.initialize()

        reports: list[EnvCpuReport] = []
        for instance in self._instances:
            report = self.collect_cpu(instance)
            reports.append(report)
            logger.info(
                "[%s] 节点数=%d, 平均CPU=%.1f%%, 最高CPU=%.1f%%",
                instance.name, report.node_count, report.avg_cpu, report.max_cpu,
            )

        return reports

    def collect_cpu_by_env(self, env_name: str) -> Optional[EnvCpuReport]:
        """按环境名称采集 CPU 数据"""
        if not self._initialized:
            self.initialize()

        for instance in self._instances:
            if instance.name == env_name:
                return self.collect_cpu(instance)

        logger.warning("未找到环境: %s", env_name)
        return None

    def get_summary(self) -> dict[str, Any]:
        """获取所有环境的 CPU 概要"""
        reports = self.collect_all_cpu()
        summary = {
            "timestamp": time.time(),
            "environments": [],
        }
        for r in reports:
            env_info = {
                "name": r.env_name,
                "node_count": r.node_count,
                "avg_cpu_percent": round(r.avg_cpu, 2),
                "max_cpu_percent": round(r.max_cpu, 2),
                "error": r.error,
            }
            if r.metrics:
                env_info["top_5_nodes"] = [
                    {"instance": m.instance, "cpu_percent": m.cpu_percent}
                    for m in r.metrics[:5]
                ]
            summary["environments"].append(env_info)

        return summary


# ═══════════════════════════════════════════════════════════
# 便捷函数
# ═══════════════════════════════════════════════════════════


def get_cpu_pressure(env_name: Optional[str] = None, config_path: Optional[str] = None) -> dict[str, Any]:
    """快速获取 CPU 压力数据（适合 Agent 工具调用）

    Args:
        env_name: 环境名称（stress/test/sandbox 等），不传则查询全部
        config_path: 配置文件路径，不传则使用默认路径

    Returns:
        CPU 压力报告字典
    """
    collector = ServerMonitorCollector(config_path)
    collector.initialize()

    if env_name:
        report = collector.collect_cpu_by_env(env_name)
        if not report:
            return {"error": f"未找到环境: {env_name}", "available_envs": [i.name for i in collector.instances]}
        return {
            "env": report.env_name,
            "node_count": report.node_count,
            "avg_cpu_percent": round(report.avg_cpu, 2),
            "max_cpu_percent": round(report.max_cpu, 2),
            "timestamp": report.timestamp,
            "error": report.error,
            "nodes": [
                {"instance": m.instance, "cpu_percent": m.cpu_percent}
                for m in report.metrics
            ],
        }
    else:
        return collector.get_summary()
