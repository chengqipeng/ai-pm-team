"""把 skills/definitions/*/SKILL.md 导入到 ai_skill_definition 表

设计原则：
- 运行时单一数据源是 DB（见 server.py 中 skill_reg.load_from_db）
- 本地 SKILL.md 仅作"可导入的素材"，通过本脚本一次性 UPSERT 到 ai_skill_definition
- 运行完本脚本后重启 server，LLM 的 <skills> 段就能看到新导入的技能

用法：
    # 全量导入 skills/definitions 下全部有效的 SKILL.md（缺 description 的会被 SkillLoader 拒收）
    python scripts/import_skills_from_definitions.py

    # 导入指定目录
    python scripts/import_skills_from_definitions.py --dir skills/definitions/account-insight

    # 指定租户（默认 0 = 平台级，全部租户可见）
    python scripts/import_skills_from_definitions.py --tenant-id 1

    # 预览（只解析不落库）
    python scripts/import_skills_from_definitions.py --dry-run
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

# 确保项目根目录在 sys.path 中
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def _iter_skill_md_dirs(root: Path):
    """yield 每一个包含 SKILL.md 的子目录"""
    for skill_md in sorted(root.rglob("SKILL.md")):
        yield skill_md.parent


def main() -> int:
    parser = argparse.ArgumentParser(description="Import SKILL.md files into ai_skill_definition")
    parser.add_argument("--dir", default="skills/definitions",
                        help="扫描的根目录或单个 skill 目录（默认 skills/definitions）")
    parser.add_argument("--tenant-id", type=int, default=0,
                        help="目标租户 ID（默认 0 = 平台级）")
    parser.add_argument("--dry-run", action="store_true",
                        help="只解析校验，不写入 DB")
    args = parser.parse_args()

    target = (ROOT / args.dir).resolve() if not os.path.isabs(args.dir) else Path(args.dir)
    if not target.exists():
        logger.error("路径不存在: %s", target)
        return 1

    # 如果传入的是单个 skill 目录（直接含 SKILL.md），只处理它；否则递归找
    if (target / "SKILL.md").exists():
        skill_dirs = [target]
    else:
        skill_dirs = list(_iter_skill_md_dirs(target))

    if not skill_dirs:
        logger.warning("未找到任何 SKILL.md: %s", target)
        return 0

    logger.info("发现 %d 个 skill 目录", len(skill_dirs))

    if args.dry_run:
        from src.skills.base import SkillLoader, SkillValidationError
        ok, skipped = 0, 0
        for d in skill_dirs:
            try:
                skill = SkillLoader.load(str(d / "SKILL.md"))
                logger.info("[dry-run] ✓ %-30s  context=%-6s  desc=%s",
                            skill.name, skill.context, skill.description[:50])
                ok += 1
            except SkillValidationError as e:
                logger.warning("[dry-run] ✗ %-30s  已禁用/非法: %s", d.name, e)
                skipped += 1
            except Exception as e:
                logger.error("[dry-run] ✗ %-30s  解析失败: %s", d.name, e)
                skipped += 1
        logger.info("[dry-run] 可导入 %d 条，跳过 %d 条", ok, skipped)
        return 0

    # 走 SkillInstaller 把 SKILL.md 写进 DB
    from src.skills.installer import SkillInstaller
    installer = SkillInstaller(default_tenant_id=args.tenant_id)

    imported, skipped = 0, 0
    for d in skill_dirs:
        try:
            api_key = installer.install_from_path(str(d), tenant_id=args.tenant_id)
            logger.info("✓ 已导入: %s (tenant=%d)", api_key, args.tenant_id)
            imported += 1
        except Exception as e:
            logger.warning("✗ 跳过 %s: %s", d.name, e)
            skipped += 1

    logger.info("完成：导入 %d 条，跳过 %d 条。请重启 server 使 load_from_db 生效。",
                imported, skipped)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
