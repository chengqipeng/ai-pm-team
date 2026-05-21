"""Skill 版本管理服务

三表结构：
  ai_skill            → 主记录（current_version 标识当前生效版本）
  ai_skill_definition → 版本内容（每个版本一行）
  ai_skill_resource   → 资源文件（每个版本独立一套）

操作：
  创建新版本 = 复制当前版本的 definition + resource
  删除版本   = 软删除 definition + resource（不能删除当前版本）
  切换版本   = 更新 ai_skill.current_version
  版本对比   = diff 两个 definition + resource
"""
from __future__ import annotations

import difflib
import json
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any

from src.store.skill_dao import SkillDAO, SkillDefinitionDAO
from src.store.skill_models import SkillRow, SkillDefinitionRow
from src.store.snowflake import next_id

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════
# 请求/响应模型
# ═══════════════════════════════════════════════════════════

@dataclass
class CreateVersionRequest:
    version: str
    changelog: str = ""


@dataclass
class FieldDiff:
    field: str
    field_label: str
    old_value: Any
    new_value: Any
    diff_type: str  # added | removed | modified


@dataclass
class VersionDiffResult:
    skill_api_key: str
    base_version: str
    target_version: str
    has_changes: bool
    summary: str
    field_diffs: list[FieldDiff]
    prompt_diff: list[str] | None
    resource_diffs: list[dict] = field(default_factory=list)
    prompt_old: str = ""
    prompt_new: str = ""


class SkillVersionError(Exception):
    def __init__(self, message: str, code: str = "VERSION_ERROR"):
        super().__init__(message)
        self.code = code


_FIELD_LABELS = {
    "when_to_use": "使用场景", "context": "执行模式", "agent": "子Agent",
    "model": "模型", "allowed_tools": "允许工具", "arguments": "参数列表",
    "prompt": "提示词", "risk_level": "风险等级", "requires_confirmation": "需要确认",
    "max_tool_calls": "最大工具调用数", "timeout_ms": "超时时间(ms)",
    "output_mode": "输出模式", "post_output_behavior": "输出后行为",
}
_DIFF_FIELDS = list(_FIELD_LABELS.keys())


class SkillVersionService:

    def __init__(self, skill_registry=None):
        """
        Args:
            skill_registry: SkillRegistry 实例（可选），用于版本切换后热加载
        """
        self._skill_registry = skill_registry

    # ── 版本列表 ──

    def list_versions(self, api_key: str, tenant_id: int = 0) -> list[dict]:
        skill = SkillDAO.get_by_api_key(tenant_id, api_key)
        if skill is None:
            raise SkillVersionError(f"Skill '{api_key}' 不存在", code="NOT_FOUND")
        versions = SkillDefinitionDAO.list_versions(tenant_id, api_key)
        return [{
            "version": v.version,
            "changelog": v.changelog,
            "context": v.context,
            "risk_level": v.risk_level,
            "published_by": v.published_by,
            "created_at": v.created_at,
            "is_current": v.version == skill.current_version,
        } for v in versions]

    # ── 版本详情 ──

    def get_version_detail(self, api_key: str, version: str, tenant_id: int = 0) -> dict:
        row = SkillDefinitionDAO.get_by_version(tenant_id, api_key, version)
        if row is None:
            raise SkillVersionError(f"版本 '{version}' 不存在", code="VERSION_NOT_FOUND")
        return self._def_to_detail(row)

    # ── 创建新版本 ──

    def create_version(self, api_key: str, req: CreateVersionRequest,
                       tenant_id: int = 0, user_id: int = 0) -> dict:
        self._validate_version(req.version)
        skill = SkillDAO.get_by_api_key(tenant_id, api_key)
        if skill is None:
            raise SkillVersionError(f"Skill '{api_key}' 不存在", code="NOT_FOUND")
        if SkillDefinitionDAO.get_by_version(tenant_id, api_key, req.version):
            raise SkillVersionError(f"版本 '{req.version}' 已存在", code="DUPLICATE_VERSION")

        current_version = skill.current_version
        now = int(time.time() * 1000)

        # 复制 definition
        source_def = SkillDefinitionDAO.get_by_version(tenant_id, api_key, current_version)
        if source_def is None:
            raise SkillVersionError(f"当前版本 '{current_version}' 数据缺失", code="SOURCE_MISSING")

        new_def = SkillDefinitionRow(
            id=next_id(), skill_api_key=api_key, tenant_id=tenant_id,
            version=req.version, name=skill.name, description=skill.description,
            changelog=req.changelog,
            when_to_use=source_def.when_to_use, category=source_def.category,
            context=source_def.context,
            agent=source_def.agent, model=source_def.model,
            allowed_tools=source_def.allowed_tools, arguments=source_def.arguments,
            prompt=source_def.prompt, risk_level=source_def.risk_level,
            requires_confirmation=source_def.requires_confirmation,
            max_tool_calls=source_def.max_tool_calls, timeout_ms=source_def.timeout_ms,
            output_mode=source_def.output_mode, component_apikey=source_def.component_apikey,
            post_output_behavior=source_def.post_output_behavior,
            published_by=user_id, created_at=now, created_by=user_id, updated_at=now, updated_by=user_id,
        )
        SkillDefinitionDAO.insert(new_def)

        # 复制 resource
        self._copy_resources(tenant_id, api_key, current_version, req.version, user_id)

        # 更新主记录 current_version
        SkillDAO.update_fields(tenant_id, api_key, {
            "current_version": req.version, "updated_at": now, "updated_by": user_id,
        })

        logger.info("新版本创建: %s v%s (from v%s)", api_key, req.version, current_version)
        # 热加载 registry，确保运行时使用新版本
        self._reload_registry(tenant_id)
        return {"skill_api_key": api_key, "version": req.version, "created_at": now}

    # ── 删除版本 ──

    def delete_version(self, api_key: str, version: str,
                       tenant_id: int = 0, user_id: int = 0) -> dict:
        """删除版本：软删除 definition + resource（不能删除当前版本）"""
        skill = SkillDAO.get_by_api_key(tenant_id, api_key)
        if skill is None:
            raise SkillVersionError(f"Skill '{api_key}' 不存在", code="NOT_FOUND")
        if skill.current_version == version:
            raise SkillVersionError("不能删除当前生效版本", code="CANNOT_DELETE_CURRENT")
        if not SkillDefinitionDAO.get_by_version(tenant_id, api_key, version):
            raise SkillVersionError(f"版本 '{version}' 不存在", code="VERSION_NOT_FOUND")

        SkillDefinitionDAO.soft_delete(tenant_id, api_key, version, updated_by=user_id)
        self._delete_version_resources(tenant_id, api_key, version, user_id)

        logger.info("版本删除: %s v%s", api_key, version)
        return {"skill_api_key": api_key, "deleted_version": version}

    # ── 切换版本 ──

    def switch_version(self, api_key: str, target_version: str,
                       tenant_id: int = 0, user_id: int = 0) -> dict:
        """切换当前生效版本，同步 name/description 到主表"""
        skill = SkillDAO.get_by_api_key(tenant_id, api_key)
        if skill is None:
            raise SkillVersionError(f"Skill '{api_key}' 不存在", code="NOT_FOUND")
        target = SkillDefinitionDAO.get_by_version(tenant_id, api_key, target_version)
        if not target:
            raise SkillVersionError(f"版本 '{target_version}' 不存在", code="VERSION_NOT_FOUND")

        now = int(time.time() * 1000)
        # 更新主表：current_version + name/description/category 同步
        SkillDAO.update_fields(tenant_id, api_key, {
            "current_version": target_version,
            "name": target.name,
            "description": target.description,
            "category": target.category,
            "updated_at": now,
            "updated_by": user_id,
        })
        logger.info("版本切换: %s → v%s", api_key, target_version)
        # 热加载 registry，确保运行时使用新版本
        self._reload_registry(tenant_id)
        return {"skill_api_key": api_key, "current_version": target_version}

    # ── 版本对比 ──

    def diff_versions(self, api_key: str, base_version: str, target_version: str,
                      tenant_id: int = 0) -> VersionDiffResult:
        base = SkillDefinitionDAO.get_by_version(tenant_id, api_key, base_version)
        if not base:
            raise SkillVersionError(f"版本 '{base_version}' 不存在", code="VERSION_NOT_FOUND")
        target = SkillDefinitionDAO.get_by_version(tenant_id, api_key, target_version)
        if not target:
            raise SkillVersionError(f"版本 '{target_version}' 不存在", code="VERSION_NOT_FOUND")

        field_diffs = self._compute_field_diffs(base, target)
        prompt_diff = self._compute_prompt_diff(base.prompt or "", target.prompt or "")
        resource_diffs = self._compute_resource_diffs(tenant_id, api_key, base_version, target_version)
        has_changes = len(field_diffs) > 0 or prompt_diff is not None or any(r["diff_type"] != "unchanged" for r in resource_diffs)

        return VersionDiffResult(
            skill_api_key=api_key, base_version=base_version, target_version=target_version,
            has_changes=has_changes, summary=self._summary(field_diffs, resource_diffs),
            field_diffs=field_diffs, prompt_diff=prompt_diff, resource_diffs=resource_diffs,
            prompt_old=base.prompt or "", prompt_new=target.prompt or "",
        )

    # ── 资源读取 ──

    def get_version_resources(self, api_key: str, version: str, tenant_id: int = 0) -> list[dict]:
        from src.store.pg_pool import get_conn
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT path, name, content_type, content_size, description
                FROM ai_skill_resource WHERE skill_api_key=%s AND tenant_id=%s AND version=%s
                AND node_type='file' AND delete_flg=0 AND enabled_flg=1 ORDER BY path
            """, (api_key, tenant_id, version))
            return [{"path": r[0], "name": r[1], "content_type": r[2], "content_size": r[3], "description": r[4]}
                    for r in cur.fetchall()]

    def get_version_resource_content(self, api_key: str, version: str, path: str, tenant_id: int = 0) -> dict | None:
        from src.store.pg_pool import get_conn
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT content, content_type, content_size, description
                FROM ai_skill_resource WHERE skill_api_key=%s AND version=%s AND path=%s
                AND tenant_id=%s AND node_type='file' AND delete_flg=0
            """, (api_key, version, path, tenant_id))
            row = cur.fetchone()
        if not row:
            return None
        return {"content": row[0], "content_type": row[1], "content_size": row[2], "description": row[3]}

    # ═══════════════════════════════════════════════════════════
    # 内部方法
    # ═══════════════════════════════════════════════════════════

    @staticmethod
    def _copy_resources(tenant_id: int, api_key: str, from_ver: str, to_ver: str, user_id: int = 0) -> int:
        from src.store.pg_pool import get_conn
        now = int(time.time() * 1000)
        count = 0
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT id, parent_id, node_type, name, path, depth,
                       content, content_type, content_size, description, icon, sort_num
                FROM ai_skill_resource
                WHERE skill_api_key=%s AND tenant_id=%s AND version=%s AND delete_flg=0
                ORDER BY depth, path
            """, (api_key, tenant_id, from_ver))
            rows = cur.fetchall()
            # 建立旧 ID → 新 ID 的映射（用于 parent_id 重映射）
            old_id_to_new_id: dict[int, int] = {}
            for (old_id, parent_id, node_type, name, path, depth, content, ctype, csize, desc, icon, sort_num) in rows:
                new_id = next_id()
                # 通过旧 parent_id 查找对应的新 parent_id
                new_parent = None
                if parent_id:
                    new_parent = old_id_to_new_id.get(parent_id)
                cur.execute("""
                    INSERT INTO ai_skill_resource
                    (id, tenant_id, skill_api_key, version, parent_id, node_type, name, path, depth,
                     content, content_type, content_size, description, icon, sort_num,
                     enabled_flg, delete_flg, created_at, created_by, updated_at, updated_by)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,1,0,%s,%s,%s,%s)
                """, (new_id, tenant_id, api_key, to_ver, new_parent, node_type, name, path, depth,
                      content, ctype, csize, desc, icon, sort_num, now, user_id, now, user_id))
                old_id_to_new_id[old_id] = new_id
                count += 1
        return count

    @staticmethod
    def _delete_version_resources(tenant_id: int, api_key: str, version: str, user_id: int = 0) -> None:
        from src.store.pg_pool import get_conn
        now = int(time.time() * 1000)
        with get_conn() as conn:
            conn.cursor().execute(
                "UPDATE ai_skill_resource SET delete_flg=1, updated_at=%s, updated_by=%s "
                "WHERE skill_api_key=%s AND tenant_id=%s AND version=%s AND delete_flg=0",
                (now, user_id, api_key, tenant_id, version))

    def _compute_field_diffs(self, base: SkillDefinitionRow, target: SkillDefinitionRow) -> list[FieldDiff]:
        diffs = []
        for f in _DIFF_FIELDS:
            ov = getattr(base, f, None)
            nv = getattr(target, f, None)
            if f in ("allowed_tools", "arguments"):
                ov = self._json(ov); nv = self._json(nv)
            ov = "" if ov is None else ov
            nv = "" if nv is None else nv
            if ov != nv:
                dt = "added" if ov in ("", [], "[]") else ("removed" if nv in ("", [], "[]") else "modified")
                diffs.append(FieldDiff(field=f, field_label=_FIELD_LABELS.get(f, f), old_value=ov, new_value=nv, diff_type=dt))
        return diffs

    def _compute_prompt_diff(self, old: str, new: str) -> list[str] | None:
        if old == new: return None
        d = list(difflib.unified_diff(old.splitlines(keepends=True), new.splitlines(keepends=True),
                                      fromfile="base", tofile="target", lineterm=""))
        return d or None

    def _compute_resource_diffs(self, tenant_id: int, api_key: str, bv: str, tv: str) -> list[dict]:
        from src.store.pg_pool import get_conn
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute("SELECT path, name, content FROM ai_skill_resource WHERE skill_api_key=%s AND tenant_id=%s AND version=%s AND node_type='file' AND delete_flg=0", (api_key, tenant_id, bv))
            bf = {r[0]: {"name": r[1], "content": r[2] or ""} for r in cur.fetchall()}
            cur.execute("SELECT path, name, content FROM ai_skill_resource WHERE skill_api_key=%s AND tenant_id=%s AND version=%s AND node_type='file' AND delete_flg=0", (api_key, tenant_id, tv))
            tf = {r[0]: {"name": r[1], "content": r[2] or ""} for r in cur.fetchall()}
        diffs = []
        for p in sorted(set(list(bf) + list(tf))):
            if p in bf and p not in tf:
                diffs.append({"path": p, "name": bf[p]["name"], "diff_type": "removed", "content_diff": None,
                              "old_content": bf[p]["content"], "new_content": None})
            elif p not in bf and p in tf:
                diffs.append({"path": p, "name": tf[p]["name"], "diff_type": "added", "content_diff": None,
                              "old_content": None, "new_content": tf[p]["content"]})
            elif bf[p]["content"] != tf[p]["content"]:
                cd = list(difflib.unified_diff(bf[p]["content"].splitlines(keepends=True), tf[p]["content"].splitlines(keepends=True), fromfile=p, tofile=p, lineterm=""))
                diffs.append({"path": p, "name": tf[p]["name"], "diff_type": "modified", "content_diff": cd or None,
                              "old_content": bf[p]["content"], "new_content": tf[p]["content"]})
            else:
                # 内容相同的文件也包含在列表中，标记为 unchanged
                diffs.append({"path": p, "name": tf[p]["name"], "diff_type": "unchanged", "content_diff": None,
                              "old_content": bf[p]["content"], "new_content": tf[p]["content"]})
        return diffs

    def _summary(self, diffs: list[FieldDiff], rd: list[dict] | None = None) -> str:
        changed_resources = [r for r in (rd or []) if r["diff_type"] != "unchanged"]
        if not diffs and not changed_resources: return "无变更"
        parts = [f"{'新增' if d.diff_type=='added' else '移除' if d.diff_type=='removed' else '修改'} {d.field_label}" for d in diffs]
        if changed_resources:
            a=sum(1 for r in changed_resources if r["diff_type"]=="added"); rm=sum(1 for r in changed_resources if r["diff_type"]=="removed"); m=sum(1 for r in changed_resources if r["diff_type"]=="modified")
            rp=[]
            if a: rp.append(f"新增{a}个文件")
            if rm: rp.append(f"删除{rm}个文件")
            if m: rp.append(f"修改{m}个文件")
            if rp: parts.append(f"资源: {'、'.join(rp)}")
        return "、".join(parts) if parts else "无变更"

    @staticmethod
    def _json(val):
        if isinstance(val, str):
            try: return json.loads(val)
            except: return val
        return val

    def _reload_registry(self, tenant_id: int) -> None:
        """版本变更后热加载 SkillRegistry"""
        if self._skill_registry is None:
            return
        try:
            self._skill_registry.load_from_db(tenant_id=tenant_id)
        except Exception as e:
            logger.warning("版本变更后 SkillRegistry 热加载失败: %s", e)

    @staticmethod
    def _validate_version(v: str):
        if not re.match(r'^\d+\.\d+\.\d+(-[a-zA-Z0-9._-]+)?$', v):
            raise SkillVersionError(f"版本号格式无效: '{v}'", code="INVALID_VERSION")

    @staticmethod
    def _def_to_detail(row: SkillDefinitionRow) -> dict:
        def _j(s, d=None):
            try: return json.loads(s) if s else d
            except: return d
        return {
            "skill_api_key": row.skill_api_key, "version": row.version,
            "name": row.name, "description": row.description,
            "changelog": row.changelog, "when_to_use": row.when_to_use,
            "category": row.category, "context": row.context,
            "agent": row.agent, "model": row.model,
            "allowed_tools": _j(row.allowed_tools, []), "arguments": _j(row.arguments, []),
            "prompt": row.prompt, "risk_level": row.risk_level,
            "requires_confirmation": bool(row.requires_confirmation),
            "max_tool_calls": row.max_tool_calls, "timeout_ms": row.timeout_ms,
            "output_mode": row.output_mode, "component_apikey": row.component_apikey,
            "post_output_behavior": row.post_output_behavior,
            "published_by": row.published_by, "created_at": row.created_at,
        }
