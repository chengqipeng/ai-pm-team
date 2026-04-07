"""
插件系统 — 借鉴 plugins/builtinPlugins.ts / utils/plugins/
插件可提供: Skills + Hooks + MCP Servers

借鉴源码:
  - src/plugins/builtinPlugins.ts: registerBuiltinPlugin, getBuiltinPlugins
  - src/types/plugin.ts: BuiltinPluginDefinition, LoadedPlugin
  - src/utils/plugins/pluginLoader.ts: loadAllPluginsCacheOnly
  - src/utils/plugins/loadPluginAgents.ts: loadPluginAgents
  - src/utils/plugins/loadPluginCommands.ts: loadPluginCommands
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from dataclasses import dataclass, field
from typing import Any

from .skills import SkillDefinition, SkillRegistry
from .hooks import HookDefinition, HookRegistry

logger = logging.getLogger(__name__)


# ─── Plugin Manifest (借鉴 types/plugin.ts) ───

@dataclass
class PluginManifest:
    """插件清单"""
    name: str
    version: str
    description: str = ""
    author: str = ""
    # 插件提供的组件
    skills: list[dict] = field(default_factory=list)
    hooks: list[dict] = field(default_factory=list)
    agents: list[dict] = field(default_factory=list)
    mcp_servers: list[dict] = field(default_factory=list)


@dataclass
class LoadedPlugin:
    """已加载的插件 (借鉴 types/plugin.ts:LoadedPlugin)"""
    name: str
    manifest: PluginManifest
    enabled: bool = True
    source: str = "user"  # builtin / user / marketplace / managed
    plugin_id: str = ""   # {name}@{source}

    def __post_init__(self):
        if not self.plugin_id:
            self.plugin_id = f"{self.name}@{self.source}"


# ─── Plugin Registry (借鉴 plugins/builtinPlugins.ts) ───

class PluginRegistry:
    """
    插件注册表 (借鉴 builtinPlugins.ts)
    管理插件的注册、启用/禁用、组件加载
    """

    def __init__(self):
        self._plugins: dict[str, LoadedPlugin] = {}
        self._disabled_plugins: set[str] = set()

    def register(self, plugin: LoadedPlugin) -> None:
        """注册插件"""
        self._plugins[plugin.plugin_id] = plugin
        logger.info(f"Plugin registered: {plugin.plugin_id}")

    def unregister(self, plugin_id: str) -> bool:
        """注销插件"""
        if plugin_id in self._plugins:
            del self._plugins[plugin_id]
            return True
        return False

    def enable(self, plugin_id: str) -> bool:
        """启用插件"""
        if plugin_id in self._plugins:
            self._plugins[plugin_id].enabled = True
            self._disabled_plugins.discard(plugin_id)
            return True
        return False

    def disable(self, plugin_id: str) -> bool:
        """禁用插件"""
        if plugin_id in self._plugins:
            self._plugins[plugin_id].enabled = False
            self._disabled_plugins.add(plugin_id)
            return True
        return False

    def get_enabled_plugins(self) -> list[LoadedPlugin]:
        """获取所有已启用插件"""
        return [p for p in self._plugins.values() if p.enabled]

    def get_all_plugins(self) -> list[LoadedPlugin]:
        """获取所有插件"""
        return list(self._plugins.values())

    def get_plugin(self, plugin_id: str) -> LoadedPlugin | None:
        return self._plugins.get(plugin_id)

    # ─── 组件加载 ───

    def load_skills_into(self, skill_registry: SkillRegistry) -> int:
        """
        将所有已启用插件的 skills 加载到 SkillRegistry
        (借鉴 utils/plugins/loadPluginCommands.ts)
        """
        count = 0
        for plugin in self.get_enabled_plugins():
            for skill_def in plugin.manifest.skills:
                try:
                    skill = self._parse_plugin_skill(skill_def, plugin)
                    skill_registry.register(skill)
                    count += 1
                except Exception as e:
                    logger.error(f"Failed to load skill from plugin {plugin.name}: {e}")
        return count

    def load_hooks_into(self, hook_registry: HookRegistry) -> int:
        """将所有已启用插件的 hooks 加载到 HookRegistry"""
        count = 0
        for plugin in self.get_enabled_plugins():
            for hook_def in plugin.manifest.hooks:
                try:
                    hook = self._parse_plugin_hook(hook_def, plugin)
                    hook_registry.register(hook)
                    count += 1
                except Exception as e:
                    logger.error(f"Failed to load hook from plugin {plugin.name}: {e}")
        return count

    def _parse_plugin_skill(self, skill_def: dict, plugin: LoadedPlugin) -> SkillDefinition:
        """解析插件中的 skill 定义"""
        async def get_prompt(args: str = "", **kw) -> str:
            return skill_def.get("prompt", "").replace("${1}", args)

        return SkillDefinition(
            name=skill_def["name"],
            description=skill_def.get("description", ""),
            aliases=skill_def.get("aliases", []),
            when_to_use=skill_def.get("when_to_use"),
            allowed_tools=skill_def.get("allowed_tools"),
            model=skill_def.get("model"),
            context=skill_def.get("context", "fork"),
            source="plugin",
            get_prompt=get_prompt,
        )

    def _parse_plugin_hook(self, hook_def: dict, plugin: LoadedPlugin) -> HookDefinition:
        """解析插件中的 hook 定义"""
        from .hooks import HookEvent, HookMatcher, HookAction, HookActionType

        return HookDefinition(
            name=f"{plugin.name}:{hook_def.get('name', 'unnamed')}",
            event=HookEvent(hook_def.get("event", "post_tool_use")),
            matcher=HookMatcher(
                tool_name=hook_def.get("tool_name"),
                tool_pattern=hook_def.get("tool_pattern"),
                tool_category=hook_def.get("tool_category"),
            ),
            action=HookAction(
                type=HookActionType(hook_def.get("action_type", "ask_agent")),
                prompt=hook_def.get("prompt"),
                command=hook_def.get("command"),
            ),
            source="plugin",
        )

    # ─── 从目录加载插件 ───

    @classmethod
    def load_from_directory(cls, directory: str) -> list[LoadedPlugin]:
        """
        从目录加载插件 (借鉴 utils/plugins/pluginLoader.ts)
        每个子目录是一个插件，包含 manifest.json
        """
        plugins = []
        plugins_dir = Path(directory)
        if not plugins_dir.is_dir():
            return plugins

        for plugin_dir in plugins_dir.iterdir():
            if not plugin_dir.is_dir():
                continue
            manifest_path = plugin_dir / "manifest.json"
            if not manifest_path.exists():
                continue
            try:
                manifest_data = json.loads(manifest_path.read_text(encoding="utf-8"))
                manifest = PluginManifest(
                    name=manifest_data.get("name", plugin_dir.name),
                    version=manifest_data.get("version", "0.0.0"),
                    description=manifest_data.get("description", ""),
                    author=manifest_data.get("author", ""),
                    skills=manifest_data.get("skills", []),
                    hooks=manifest_data.get("hooks", []),
                    agents=manifest_data.get("agents", []),
                    mcp_servers=manifest_data.get("mcp_servers", []),
                )
                plugins.append(LoadedPlugin(
                    name=manifest.name,
                    manifest=manifest,
                    source="user",
                ))
            except Exception as e:
                logger.error(f"Failed to load plugin from {plugin_dir}: {e}")

        return plugins
