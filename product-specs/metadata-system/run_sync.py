#!/usr/bin/env python3
"""
数据同步统一入口
==================

用法:
  python3 run_sync.py <command> [options]

命令:
  verify-meta          Phase 0: 元数据验证（9 项检查）
  build-mappings       Phase 1: 构建映射表（列/SELECT/busiType）
  sync-tenant-meta     同步 Tenant 级元数据（b_item → p_tenant_item 等）
  sync-biz-data        Phase 2: 同步业务数据（a_account → p_tenant_data）
  verify-biz-data      Phase 3: 业务数据验证（行数+值+公式）
  verify-formulas      验证计算公式（引擎求值 vs baseline）
  setup-formula-test   补充 10 个测试公式的元数据和数据
  all                  执行全流程（verify-meta → build-mappings → sync-tenant-meta → verify-formulas）
  all --verify-only    仅验证，不同步

示例:
  python3 run_sync.py verify-meta
  python3 run_sync.py verify-meta account lead
  python3 run_sync.py sync-tenant-meta
  python3 run_sync.py verify-formulas
  python3 run_sync.py all
"""
import sys
import os
import importlib
import importlib.util
import types
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
log = logging.getLogger(__name__)


def setup_sync_package():
    """手动设置 sync 包，解决相对导入"""
    sync_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'sync')
    sync_pkg = types.ModuleType('sync')
    sync_pkg.__path__ = [sync_dir]
    sync_pkg.__file__ = os.path.join(sync_dir, '__init__.py')
    sys.modules['sync'] = sync_pkg

    # 按依赖顺序加载
    for mod_name in ['config', 'db', 'transform', 'build_mappings', 'verify_metadata',
                     'verify_formulas', 'sync_biz_data', 'verify_biz_data']:
        fpath = os.path.join(sync_dir, f'{mod_name}.py')
        if not os.path.exists(fpath):
            continue
        spec = importlib.util.spec_from_file_location(f'sync.{mod_name}', fpath)
        mod = importlib.util.module_from_spec(spec)
        sys.modules[f'sync.{mod_name}'] = mod
        spec.loader.exec_module(mod)
        setattr(sync_pkg, mod_name, mod)


def run_standalone(script_name):
    """运行 sync/ 目录下的独立脚本"""
    script_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'sync', script_name)
    if not os.path.exists(script_path):
        log.error(f"脚本不存在: {script_path}")
        sys.exit(1)
    log.info(f"执行: {script_name}")
    exec(open(script_path).read(), {'__name__': '__main__', '__file__': script_path})


def main():
    if len(sys.argv) < 2 or sys.argv[1] in ('-h', '--help', 'help'):
        print(__doc__)
        sys.exit(0)

    cmd = sys.argv[1]
    extra_args = sys.argv[2:]

    # 解析 entity 参数
    entities = [a for a in extra_args if not a.startswith('-')] or None
    verify_only = '--verify-only' in extra_args

    setup_sync_package()
    from sync.config import TEST_TENANT_ID

    tenant_id = TEST_TENANT_ID
    for a in extra_args:
        if a.isdigit():
            tenant_id = int(a)

    if cmd == 'verify-meta':
        from sync.verify_metadata import MetadataVerifier
        v = MetadataVerifier(entities)
        v.run()

    elif cmd == 'build-mappings':
        from sync.build_mappings import MappingBuilder
        mb = MappingBuilder(entities)
        mb.build_all()

    elif cmd == 'sync-tenant-meta':
        run_standalone('sync_tenant_meta.py')

    elif cmd == 'sync-biz-data':
        from sync.sync_biz_data import BizDataSyncer
        syncer = BizDataSyncer(tenant_id, entities)
        syncer.run()

    elif cmd == 'verify-biz-data':
        from sync.verify_biz_data import BizDataVerifier
        verifier = BizDataVerifier(tenant_id, entities)
        verifier.run()

    elif cmd == 'verify-formulas':
        run_standalone('verify_formula_engine.py')

    elif cmd == 'setup-formula-test':
        run_standalone('setup_formula_test.py')

    elif cmd == 'all':
        log.info("█" * 60)
        log.info("█  全流程执行")
        log.info("█" * 60)

        # Phase 0
        log.info("\n── Phase 0: 元数据验证 ──")
        from sync.verify_metadata import MetadataVerifier
        MetadataVerifier(entities).run()

        # Phase 1
        log.info("\n── Phase 1: 映射表构建 ──")
        from sync.build_mappings import MappingBuilder
        MappingBuilder(entities).build_all()

        if not verify_only:
            # Tenant 元数据同步
            log.info("\n── Tenant 元数据同步 ──")
            run_standalone('sync_tenant_meta.py')

        # Phase 3: 公式验证
        log.info("\n── Phase 3: 公式验证 ──")
        run_standalone('verify_formula_engine.py')

        log.info("\n" + "=" * 60)
        log.info("全流程完成")

    else:
        print(f"未知命令: {cmd}")
        print(__doc__)
        sys.exit(1)


if __name__ == '__main__':
    main()
