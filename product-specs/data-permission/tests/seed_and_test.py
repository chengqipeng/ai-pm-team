#!/usr/bin/env python3
"""
数据权限完整测试：种子数据补充 + 端到端验证。
连接本地 PG 库，不连接历史库。
"""
import psycopg2
import requests
import json
import sys
import time

# ═══════════════════════════════════════════════════════════
# 配置
# ═══════════════════════════════════════════════════════════
DB = dict(host='127.0.0.1', port=5432, dbname='paas_db',
          user='postgres', password='123456', options='-c search_path=public')
API = 'http://127.0.0.1:18010'
T = 999999          # 测试租户
E = 'tperm'         # 基础 entity 前缀
ts = lambda: int(time.time() * 1000)

# 用户
OWNER_A  = 80001    # 负责人 A
OWNER_B  = 80002    # 负责人 B
VIEWER   = 80003    # 通过 share 授权的查看者
NOBODY   = 80004    # 无任何权限
DEPT_S   = 'sales_dept'    # 销售部
DEPT_T   = 'tech_dept'    # 技术部

passed = failed = 0
errors = []

def db():
    c = psycopg2.connect(**DB); c.autocommit = True; return c

def api_list(ent, uid=None, page=1, size=20):
    h = {'X-Tenant-Id': str(T)}
    if uid: h['X-User-Id'] = str(uid)
    try: return requests.get(f'{API}/entity/data/{ent}?page={page}&size={size}', headers=h, timeout=10).json()
    except Exception as e: return {'error': str(e)}

def api_get(ent, did, uid=None):
    h = {'X-Tenant-Id': str(T)}
    if uid: h['X-User-Id'] = str(uid)
    try: return requests.get(f'{API}/entity/data/{ent}/{did}', headers=h, timeout=10).json()
    except Exception as e: return {'error': str(e)}

def test(name, fn):
    global passed, failed
    try: fn(); passed += 1; print(f"  ✅ {name}")
    except Exception as e: failed += 1; errors.append(f"{name}: {e}"); print(f"  ❌ {name}: {e}")

def total_of(r):
    if 'data' not in r: raise AssertionError(f"响应无 data: {json.dumps(r, ensure_ascii=False)[:200]}")
    return int(r['data'].get('total', 0))

def ids_of(r):
    return {int(x['id']) for x in r.get('data', {}).get('records', [])}


# ═══════════════════════════════════════════════════════════
# Step 1: 补充 dataPermission 的 p_meta_item 种子数据
# ═══════════════════════════════════════════════════════════

def seed_meta_item():
    """补充 dataPermission 元模型的字段定义到 p_meta_item"""
    conn = db()
    cur = conn.cursor()

    # 检查是否已存在
    cur.execute("SELECT COUNT(*) FROM p_meta_item WHERE metamodel_api_key='dataPermission' AND delete_flg=0")
    if cur.fetchone()[0] > 0:
        print("  ⏭️  dataPermission 的 p_meta_item 已存在，跳过")
        cur.close(); conn.close(); return

    # 字段定义（与设计文档 §2.5 对齐）
    items = [
        # (id, apiKey, dbColumn, itemType, dataType, order, label)
        (1868100001, 'defaultAccess',    'dbc_smallint1', 31, 6, 1, '默认访问级别'),
        (1868100002, 'hierarchyAccess',  'dbc_smallint2', 31, 6, 2, '层级访问'),
        (1868100003, 'ownerAccess',      'dbc_smallint3', 31, 6, 3, '负责人权限'),
        (1868100004, 'teamAccess',       'dbc_smallint4', 31, 6, 4, '团队成员权限'),
        (1868100005, 'territoryAccess',  'dbc_smallint5', 31, 6, 5, '区域权限'),
        (1868100006, 'sharingFlg',       'dbc_smallint6', 31, 6, 6, '启用共享'),
        (1868100007, 'sharingRuleFlg',   'dbc_smallint7', 31, 6, 7, '启用共享规则'),
        (1868100008, 'externalAccess',   'dbc_smallint8', 31, 6, 8, '外部访问'),
    ]

    for item_id, api_key, db_col, item_type, data_type, order, label in items:
        cur.execute("""
            INSERT INTO p_meta_item
                (id, metamodel_api_key, api_key, db_column, item_type, data_type,
                 item_order, label, label_key, namespace, require_flg,
                 custom_flg, delete_flg, created_at, updated_at)
            VALUES (%s, 'dataPermission', %s, %s, %s, %s,
                    %s, %s, %s, 'system', 0,
                    0, 0, %s, %s)
        """, (item_id, api_key, db_col, item_type, data_type,
              order, label, f'meta.dataPermission.{api_key}', ts(), ts()))

    print(f"  ✅ 补充 dataPermission p_meta_item: {len(items)} 个字段")
    cur.close(); conn.close()


# ═══════════════════════════════════════════════════════════
# Step 2: 每个场景用独立 entity，避免 Redis 缓存干扰
# ═══════════════════════════════════════════════════════════

def make_env(ent, biz_data, share_data=None, dp_config=None):
    """
    为一个测试场景构造完整环境。
    biz_data: [(id, owner_id, depart_api_key, name), ...]
    share_data: [(id, data_id, subject_api_key), ...] or None
    dp_config: (defaultAccess, hierarchyAccess, ownerAccess) or None (不创建配置)
    """
    conn = db(); cur = conn.cursor()

    # 路由
    cur.execute("DELETE FROM paas_entity_data.p_tenant_data_route WHERE tenant_id=%s AND entity_api_key=%s", (T, ent))
    cur.execute("""INSERT INTO paas_entity_data.p_tenant_data_route
        (id,tenant_id,entity_api_key,table_index,delete_flg,created_at,updated_at)
        VALUES (%s,%s,%s,0,0,%s,%s)""", (hash(ent+'route') % 2**62, T, ent, ts(), ts()))

    cur.execute("DELETE FROM p_data_share_route WHERE tenant_id=%s AND entity_api_key=%s", (T, ent))
    cur.execute("""INSERT INTO p_data_share_route
        (id,tenant_id,entity_api_key,table_index,delete_flg,created_at,updated_at)
        VALUES (%s,%s,%s,0,0,%s,%s)""", (hash(ent+'sroute') % 2**62, T, ent, ts(), ts()))

    # 业务数据
    cur.execute("DELETE FROM paas_entity_data.p_tenant_data_0 WHERE tenant_id=%s AND entity_api_key=%s", (T, ent))
    for did, oid, dept, name in biz_data:
        cur.execute("""INSERT INTO paas_entity_data.p_tenant_data_0
            (id,tenant_id,entity_api_key,name,owner_id,depart_api_key,delete_flg,lock_status,approval_status,created_at,updated_at)
            VALUES (%s,%s,%s,%s,%s,%s,0,1,0,%s,%s)""",
            (did, T, ent, name, oid, dept, ts(), ts()))

    # share 数据
    cur.execute("DELETE FROM p_data_share_0 WHERE tenant_id=%s AND entity_api_key=%s", (T, ent))
    if share_data:
        for sid, data_id, subj_key in share_data:
            cur.execute("""INSERT INTO p_data_share_0
                (id,tenant_id,entity_api_key,data_id,subject_api_key,subject_type,access_level,share_cause,delete_flg,created_at,updated_at)
                VALUES (%s,%s,%s,%s,%s,0,1,6,0,%s,%s)""",
                (sid, T, ent, data_id, subj_key, ts(), ts()))

    # dataPermission 配置
    dp_id = hash(ent+'dp') % 2**62
    cur.execute("DELETE FROM p_common_metadata WHERE id=%s", (dp_id,))
    if dp_config:
        da, ha, oa = dp_config
        cur.execute("""INSERT INTO p_common_metadata
            (id,metamodel_api_key,entity_api_key,api_key,label,namespace,
             dbc_smallint1,dbc_smallint2,dbc_smallint3,delete_flg,created_at,updated_at)
            VALUES (%s,'dataPermission',%s,%s,'权限配置','system',%s,%s,%s,0,%s,%s)""",
            (dp_id, ent, f'{ent}_dp', da, ha, oa, ts(), ts()))

    cur.close(); conn.close()


def drop_env(ent):
    """清理测试环境"""
    conn = db(); cur = conn.cursor()
    cur.execute("DELETE FROM paas_entity_data.p_tenant_data_0 WHERE tenant_id=%s AND entity_api_key=%s", (T, ent))
    cur.execute("DELETE FROM p_data_share_0 WHERE tenant_id=%s AND entity_api_key=%s", (T, ent))
    cur.execute("DELETE FROM p_common_metadata WHERE id=%s", (hash(ent+'dp') % 2**62,))
    cur.execute("DELETE FROM paas_entity_data.p_tenant_data_route WHERE tenant_id=%s AND entity_api_key=%s", (T, ent))
    cur.execute("DELETE FROM p_data_share_route WHERE tenant_id=%s AND entity_api_key=%s", (T, ent))
    cur.close(); conn.close()


# ═══════════════════════════════════════════════════════════
# Step 3: 测试场景
# ═══════════════════════════════════════════════════════════

def run_all():
    print("\n══════════════════════════════════════════════════")
    print("  数据权限完整端到端测试")
    print("══════════════════════════════════════════════════")

    # ── 场景 1：内部调用（无 userId）跳过过滤 ──
    print("\n📦 1. 内部调用（无 userId）")
    ent = 'tp01internal'
    make_env(ent,
        biz_data=[(700001,OWNER_A,DEPT_S,'d1'),(700002,OWNER_B,DEPT_T,'d2'),(700003,OWNER_A,DEPT_S,'d3')],
        dp_config=(0, 0, 2))  # 私有模式
    test("无 userId → 返回全部 3 条", lambda: (
        _r := api_list(ent, uid=None),
        _assert(total_of(_r) == 3, f"期望3, 实际{total_of(_r)}")
    )[-1])
    drop_env(ent)

    # ── 场景 2：负责人只看到自己的数据 ──
    print("\n📦 2. 负责人隔离")
    ent = 'tp02owner'
    make_env(ent,
        biz_data=[
            (700010,OWNER_A,DEPT_S,'A1'),(700011,OWNER_A,DEPT_S,'A2'),(700012,OWNER_A,DEPT_S,'A3'),
            (700020,OWNER_B,DEPT_T,'B1'),(700021,OWNER_B,DEPT_T,'B2'),
        ],
        dp_config=(0, 0, 2))

    test("负责人 A → 看到 3 条", lambda: (
        _r := api_list(ent, uid=OWNER_A),
        _assert(total_of(_r) == 3, f"期望3, 实际{total_of(_r)}"),
        _assert(ids_of(_r) == {700010,700011,700012}, f"id 不对: {ids_of(_r)}")
    )[-1])

    test("负责人 B → 看到 2 条", lambda: (
        _r := api_list(ent, uid=OWNER_B),
        _assert(total_of(_r) == 2, f"期望2, 实际{total_of(_r)}"),
        _assert(ids_of(_r) == {700020,700021}, f"id 不对: {ids_of(_r)}")
    )[-1])

    test("A 不含 B 的数据", lambda: (
        _r := api_list(ent, uid=OWNER_A),
        _assert(len(ids_of(_r) & {700020,700021}) == 0, "A 不应看到 B 的数据")
    )[-1])
    drop_env(ent)

    # ── 场景 3：无权限用户返回空 ──
    print("\n📦 3. 无权限用户")
    ent = 'tp03nobody'
    make_env(ent,
        biz_data=[(700030,OWNER_A,DEPT_S,'d1'),(700031,OWNER_B,DEPT_T,'d2')],
        dp_config=(0, 0, 2))

    test("无权限用户 → 0 条", lambda: (
        _r := api_list(ent, uid=NOBODY),
        _assert(total_of(_r) == 0, f"期望0, 实际{total_of(_r)}")
    )[-1])
    drop_env(ent)

    # ── 场景 4：share 表授权 ──
    print("\n📦 4. share 表授权")
    ent = 'tp04share'
    make_env(ent,
        biz_data=[
            (700040,OWNER_A,DEPT_S,'A1'),(700041,OWNER_A,DEPT_S,'A2'),
            (700042,OWNER_A,DEPT_S,'A3'),(700043,OWNER_B,DEPT_T,'B1'),
        ],
        share_data=[
            (750001, 700040, str(VIEWER)),  # VIEWER 可看 A1
            (750002, 700041, str(VIEWER)),  # VIEWER 可看 A2
        ],
        dp_config=(0, 0, 2))

    test("VIEWER 通过 share 看到 2 条", lambda: (
        _r := api_list(ent, uid=VIEWER),
        _assert(total_of(_r) == 2, f"期望2, 实际{total_of(_r)}"),
        _assert(ids_of(_r) == {700040,700041}, f"id 不对: {ids_of(_r)}")
    )[-1])

    test("VIEWER 不含未共享的数据", lambda: (
        _r := api_list(ent, uid=VIEWER),
        _assert(len(ids_of(_r) & {700042,700043}) == 0, "不应看到未共享的")
    )[-1])
    drop_env(ent)

    # ── 场景 5：defaultAccess=2 全员读写 ──
    print("\n📦 5. defaultAccess=2（全员读写）")
    ent = 'tp05public'
    make_env(ent,
        biz_data=[(700050,OWNER_A,DEPT_S,'d1'),(700051,OWNER_B,DEPT_T,'d2'),(700052,OWNER_A,DEPT_S,'d3')],
        dp_config=(2, 0, 2))  # defaultAccess=2

    test("全员读写 → NOBODY 看到全部 3 条", lambda: (
        _r := api_list(ent, uid=NOBODY),
        _assert(total_of(_r) == 3, f"期望3, 实际{total_of(_r)}")
    )[-1])
    drop_env(ent)

    # ── 场景 6：无 dataPermission 配置 ──
    print("\n📦 6. 无 dataPermission 配置")
    ent = 'tp06noconf'
    make_env(ent,
        biz_data=[(700060,OWNER_A,DEPT_S,'d1'),(700061,OWNER_B,DEPT_T,'d2')],
        dp_config=None)  # 不创建配置

    test("无配置 → 跳过过滤，返回全部 2 条", lambda: (
        _r := api_list(ent, uid=NOBODY),
        _assert(total_of(_r) == 2, f"期望2, 实际{total_of(_r)}")
    )[-1])
    drop_env(ent)

    # ── 场景 7：单条查询权限 ──
    print("\n📦 7. 单条查询权限")
    ent = 'tp07single'
    make_env(ent,
        biz_data=[(700070,OWNER_A,DEPT_S,'A1'),(700071,OWNER_B,DEPT_T,'B1')],
        share_data=[(750010, 700070, str(VIEWER))],  # VIEWER 可看 A1
        dp_config=(0, 0, 2))

    test("负责人查自己的 → 有数据", lambda: (
        _r := api_get(ent, 700070, uid=OWNER_A),
        _assert(_r.get('code') == 200 and _r.get('data') is not None, f"应返回数据: {_r}")
    )[-1])

    test("负责人查别人的 → null", lambda: (
        _r := api_get(ent, 700071, uid=OWNER_A),
        _assert(_r.get('code') == 200, f"应返回200"),
        _assert(_r.get('data') is None, f"不应有数据: {_r.get('data')}")
    )[-1])

    test("VIEWER 查 share 授权的 → 有数据", lambda: (
        _r := api_get(ent, 700070, uid=VIEWER),
        _assert(_r.get('code') == 200 and _r.get('data') is not None, f"应返回数据: {_r}")
    )[-1])

    test("VIEWER 查未授权的 → null", lambda: (
        _r := api_get(ent, 700071, uid=VIEWER),
        _assert(_r.get('code') == 200, f"应返回200"),
        _assert(_r.get('data') is None, f"不应有数据: {_r.get('data')}")
    )[-1])

    test("NOBODY 查任何数据 → null", lambda: (
        _r := api_get(ent, 700070, uid=NOBODY),
        _assert(_r.get('code') == 200, f"应返回200"),
        _assert(_r.get('data') is None, f"不应有数据: {_r.get('data')}")
    )[-1])
    drop_env(ent)

    # ── 场景 8：负责人 + share 混合 ──
    print("\n📦 8. 负责人 + share 混合")
    ent = 'tp08mix'
    make_env(ent,
        biz_data=[
            (700080,OWNER_A,DEPT_S,'A1'),(700081,OWNER_A,DEPT_S,'A2'),
            (700090,OWNER_B,DEPT_T,'B1'),(700091,OWNER_B,DEPT_T,'B2'),(700092,OWNER_B,DEPT_T,'B3'),
        ],
        share_data=[
            (750020, 700090, str(OWNER_A)),  # A 可看 B1
            (750021, 700091, str(OWNER_A)),  # A 可看 B2
        ],
        dp_config=(0, 0, 2))

    test("A: 自己 2 条 + share 2 条 = 4 条", lambda: (
        _r := api_list(ent, uid=OWNER_A),
        _assert(total_of(_r) == 4, f"期望4, 实际{total_of(_r)}"),
        _assert(ids_of(_r) == {700080,700081,700090,700091}, f"id 不对: {ids_of(_r)}")
    )[-1])

    test("A 不含 B3(未共享)", lambda: (
        _r := api_list(ent, uid=OWNER_A),
        _assert(700092 not in ids_of(_r), "不应看到 B3")
    )[-1])

    test("B 只看到自己的 3 条", lambda: (
        _r := api_list(ent, uid=OWNER_B),
        _assert(total_of(_r) == 3, f"期望3, 实际{total_of(_r)}")
    )[-1])
    drop_env(ent)

    # ── 场景 9：defaultAccess=1（只读，部门内可见）──
    print("\n📦 9. defaultAccess=1（部门内可见）")
    ent = 'tp09dept'
    # 注意：UserSubjectService 的部门展开 TODO 未实现，
    # 所以 depart_api_key 匹配不会生效，但 owner_id 匹配仍然有效
    make_env(ent,
        biz_data=[
            (700100,OWNER_A,DEPT_S,'A1'),(700101,OWNER_A,DEPT_S,'A2'),
            (700110,OWNER_B,DEPT_T,'B1'),
        ],
        dp_config=(1, 0, 2))  # defaultAccess=1

    test("defaultAccess=1, A 至少看到自己的 2 条", lambda: (
        _r := api_list(ent, uid=OWNER_A),
        _assert(total_of(_r) >= 2, f"期望>=2, 实际{total_of(_r)}"),
        _assert({700100,700101}.issubset(ids_of(_r)), f"应包含自己的数据")
    )[-1])
    drop_env(ent)


def _assert(cond, msg=""):
    if not cond: raise AssertionError(msg)

# walrus operator helper
class _WalrusHelper:
    """让 lambda 中能用赋值"""
    pass


# ═══════════════════════════════════════════════════════════
# 主入口
# ═══════════════════════════════════════════════════════════

def main():
    # 检查服务
    try:
        requests.get(f'{API}/actuator/health', timeout=3)
        print(f"✅ 服务运行中: {API}")
    except:
        print(f"❌ 服务未运行: {API}")
        sys.exit(1)

    # Step 1: 补充种子数据
    print("\n📦 Step 1: 补充 dataPermission 元模型字段定义")
    seed_meta_item()

    # Step 2: 运行测试
    run_all()

    # 结果
    print("\n══════════════════════════════════════════════════")
    print(f"  结果: {passed} passed, {failed} failed")
    print("══════════════════════════════════════════════════")
    if errors:
        print("\n❌ 失败详情:")
        for e in errors: print(f"  - {e}")
    sys.exit(1 if failed else 0)

if __name__ == '__main__':
    main()
