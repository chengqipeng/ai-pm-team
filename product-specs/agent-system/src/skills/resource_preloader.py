"""Skill 资源预加载器 — fork 模式子 Agent 启动前自动注入基础知识文件

解决问题：
  fork 模式的子 Agent 需要多轮 LLM 推理才能逐个加载知识文件（read_skill_resource），
  导致不必要的延迟和 token 消耗。

方案：
  在子 Agent 启动前，根据 Skill 配置的 preload_resources 规则，
  从 ai_skill_resource 表批量加载基础知识文件，注入到 task_instruction 中。
  子 Agent 启动时已经拥有基础上下文，减少 1-2 轮推理循环。

配置方式（ext_info JSON）：
  {
    "preload_resources": {
      "always": ["knowledge/industries/_index.md"],
      "scene_map": {
        "新客开拓|新客|开拓": ["knowledge/analysis-strategies/business-model-patterns.md", "knowledge/analysis-strategies/signal-patterns.md"],
        "续约|续费|流失|健康度": ["knowledge/analysis-strategies/risk-scoring-models.md", "knowledge/analysis-strategies/signal-patterns.md"],
        "商机|推进|赢单|竞争": ["knowledge/analysis-strategies/value-proposition-frameworks.md", "knowledge/competitor-playbooks/incumbent-replacement.md"],
        "巡检|定时|变更": ["knowledge/analysis-strategies/signal-patterns.md"]
      },
      "max_preload": 4
    }
  }
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class PreloadConfig:
    """预加载配置"""
    always: list[str] = field(default_factory=list)       # 始终加载的文件
    scene_map: dict[str, list[str]] = field(default_factory=dict)  # 场景关键词 → 文件列表
    max_preload: int = 4                                  # 最大预加载文件数


@dataclass
class PreloadResult:
    """预加载结果"""
    files: list[dict[str, str]]  # [{path, content, description}]
    duration_ms: float = 0.0
    matched_scene: str = ""


class ResourcePreloader:
    """Skill 资源预加载器

    在 fork 模式子 Agent 启动前，批量加载基础知识文件。
    """

    def __init__(self, tenant_id: int = 0):
        self._tenant_id = tenant_id

    def parse_config(self, ext_info: str | dict) -> PreloadConfig | None:
        """从 ext_info 解析预加载配置

        Args:
            ext_info: SkillDefinition 的 ext_info 字段（JSON 字符串或 dict）

        Returns:
            PreloadConfig 或 None（无配置时）
        """
        if not ext_info:
            return None

        if isinstance(ext_info, str):
            try:
                ext_info = json.loads(ext_info)
            except (json.JSONDecodeError, TypeError):
                return None

        preload_cfg = ext_info.get("preload_resources")
        if not preload_cfg or not isinstance(preload_cfg, dict):
            return None

        return PreloadConfig(
            always=preload_cfg.get("always", []),
            scene_map=preload_cfg.get("scene_map", {}),
            max_preload=preload_cfg.get("max_preload", 4),
        )

    def match_scene(self, config: PreloadConfig, arguments: dict[str, str]) -> list[str]:
        """根据用户意图匹配场景，返回需要加载的文件路径列表

        匹配逻辑：
        1. always 列表中的文件始终加载
        2. 遍历 scene_map，用 arguments 中的文本匹配关键词
        3. 去重，限制总数不超过 max_preload
        """
        paths: list[str] = list(config.always)

        # 拼接所有 arguments 的值作为匹配文本
        match_text = " ".join(str(v) for v in arguments.values()).lower()

        matched_scene = ""
        for keywords_str, file_paths in config.scene_map.items():
            keywords = [kw.strip().lower() for kw in keywords_str.split("|")]
            if any(kw in match_text for kw in keywords):
                matched_scene = keywords_str
                for p in file_paths:
                    if p not in paths:
                        paths.append(p)
                break  # 只匹配第一个命中的场景

        # 限制总数
        if len(paths) > config.max_preload:
            paths = paths[:config.max_preload]

        logger.info("[preloader] 场景匹配: text=%s, scene=%s, files=%d",
                    match_text[:50], matched_scene or "(none)", len(paths))
        return paths

    async def preload(
        self,
        skill_name: str,
        resource_paths: list[str],
    ) -> PreloadResult:
        """批量加载知识文件

        Args:
            skill_name: 技能标识（api_key）
            resource_paths: 要加载的文件路径列表

        Returns:
            PreloadResult 包含加载的文件内容
        """
        if not resource_paths:
            return PreloadResult(files=[])

        start = time.monotonic()
        files: list[dict[str, str]] = []

        try:
            from src.store.pg_pool import get_conn
            import re

            # 构建 skill_name 的多种格式（兼容 camelCase/kebab-case/snake_case）
            names = self._build_name_variants(skill_name)

            with get_conn() as conn:
                cur = conn.cursor()

                # 批量查询：一次 SQL 获取所有文件
                name_placeholders = ",".join(["%s"] * len(names))
                path_placeholders = ",".join(["%s"] * len(resource_paths))

                cur.execute(f"""
                    SELECT path, content, description
                    FROM ai_skill_resource
                    WHERE skill_api_key IN ({name_placeholders})
                      AND path IN ({path_placeholders})
                      AND node_type = 'file'
                      AND tenant_id = %s
                      AND delete_flg = 0
                      AND enabled_flg = 1
                    ORDER BY sort_num, path
                """, (*names, *resource_paths, self._tenant_id))

                rows = cur.fetchall()

            for path, content, description in rows:
                if content:
                    files.append({
                        "path": path,
                        "content": content,
                        "description": description or "",
                    })

            duration_ms = (time.monotonic() - start) * 1000
            logger.info("[preloader] 批量加载完成: skill=%s, requested=%d, loaded=%d, %.0fms",
                        skill_name, len(resource_paths), len(files), duration_ms)

            return PreloadResult(files=files, duration_ms=duration_ms)

        except Exception as e:
            duration_ms = (time.monotonic() - start) * 1000
            logger.warning("[preloader] 批量加载失败: skill=%s, err=%s, %.0fms",
                           skill_name, e, duration_ms)
            return PreloadResult(files=[], duration_ms=duration_ms)

    @staticmethod
    def _build_name_variants(skill_name: str) -> list[str]:
        """构建 skill_name 的多种格式变体"""
        import re

        names = [skill_name]

        # 连字符/下划线互换
        if "-" in skill_name:
            alt = skill_name.replace("-", "_")
        else:
            alt = skill_name.replace("_", "-")
        if alt != skill_name:
            names.append(alt)

        # camelCase → kebab-case
        if any(c.isupper() for c in skill_name):
            kebab = re.sub(r'([a-z])([A-Z])', r'\1-\2', skill_name).lower()
            if kebab not in names:
                names.append(kebab)

        # kebab-case → camelCase
        if "-" in skill_name:
            parts = skill_name.split("-")
            camel = parts[0] + "".join(p.capitalize() for p in parts[1:])
            if camel not in names:
                names.append(camel)

        return names

    @staticmethod
    def format_preloaded_context(result: PreloadResult) -> str:
        """将预加载结果格式化为注入 task_instruction 的文本块

        格式设计原则：
        - 明确标注这是预加载的知识（让 LLM 知道不需要再次加载）
        - 保留文件路径（LLM 可以引用）
        - 提示 LLM 仍可按需加载其他文件
        """
        if not result.files:
            return ""

        lines = [
            "\n---\n",
            "## 📚 预加载知识文件（已自动加载，无需再次调用 read_skill_resource）\n",
        ]

        for f in result.files:
            lines.append(f"### 📄 {f['path']}")
            if f["description"]:
                lines.append(f"> {f['description']}\n")
            lines.append(f["content"])
            lines.append("")  # 空行分隔

        lines.append("---")
        lines.append(
            "> 💡 以上知识文件已预加载。如需加载其他文件（如特定行业包或竞争剧本），"
            "仍可调用 `read_skill_resource`。"
        )

        return "\n".join(lines)
