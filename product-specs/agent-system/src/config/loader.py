"""配置加载器 — YAML/JSON + 环境变量覆盖

环境变量使用 DEEPAGENT_ 前缀，双下划线分隔嵌套层级。
例如: DEEPAGENT_MODEL__DEFAULT_MODEL=gpt-4o → config["model"]["default_model"] = "gpt-4o"
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from .models import AppConfig

logger = logging.getLogger(__name__)

_ENV_PREFIX = "DEEPAGENT_"
_ENV_SEP = "__"


class ConfigLoader:
    """统一配置加载器"""

    def load(self, config_path: str) -> AppConfig:
        """从文件加载配置"""
        path = Path(config_path)
        if not path.exists():
            logger.warning("配置文件不存在: %s，使用默认配置", config_path)
            return AppConfig()

        raw = self._read_file(path)
        raw = self._apply_env_overrides(raw)
        return self._parse_config(raw)

    def load_from_dict(self, data: dict[str, Any]) -> AppConfig:
        """从字典加载配置"""
        data = self._apply_env_overrides(data)
        return self._parse_config(data)

    def _read_file(self, path: Path) -> dict[str, Any]:
        suffix = path.suffix.lower()
        content = path.read_text(encoding="utf-8")
        if suffix in (".yaml", ".yml"):
            data = yaml.safe_load(content)
        elif suffix == ".json":
            data = json.loads(content)
        else:
            raise ValueError(f"不支持的配置文件格式: {suffix}")
        if not isinstance(data, dict):
            raise ValueError("配置文件内容必须是字典格式")
        return data

    def _apply_env_overrides(self, config: dict[str, Any]) -> dict[str, Any]:
        """用 DEEPAGENT_ 前缀的环境变量覆盖配置项"""
        config = dict(config)
        for key, value in os.environ.items():
            if not key.startswith(_ENV_PREFIX):
                continue
            parts = key[len(_ENV_PREFIX):].lower().split(_ENV_SEP)
            if not parts or not parts[0]:
                continue
            self._set_nested(config, parts, value)
        return config

    @staticmethod
    def _set_nested(data: dict[str, Any], keys: list[str], value: str) -> None:
        current = data
        for k in keys[:-1]:
            if k not in current or not isinstance(current[k], dict):
                current[k] = {}
            current = current[k]
        current[keys[-1]] = value

    def _parse_config(self, raw: dict[str, Any]) -> AppConfig:
        known_fields = set(AppConfig.model_fields.keys())
        unknown = set(raw.keys()) - known_fields
        for uk in unknown:
            logger.warning("忽略未知配置项: %s", uk)
        filtered = {k: v for k, v in raw.items() if k in known_fields}
        try:
            return AppConfig.model_validate(filtered)
        except ValidationError as exc:
            logger.error("配置验证失败: %s", exc)
            raise
