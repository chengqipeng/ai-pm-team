#!/usr/bin/env python3
"""
公共组权限端到端测试。
验证：公共组成员通过 share 表授权能看到被共享的数据。
"""
import psycopg2, requests, json, sys, time

DB = dict(host='127.0.0.1', port=5432, dbname='paas_db', user='postgres', password='123456', options='-c search_path=public')
API = 'http://127.0.0.1:18010'
T = 999888  # 独立测试租户
ts = lambda: int(time.time() * 1000)

USER_A = 60001   # 负责人 A
USER_B = 60002   # 负责人 B
USER_C = 60003   # 公共组成员（非负责人）
USER_D = 60004   # 不在公共组的用户
PG_VIP = 'pg_vip_service'  # 公共组 apiKey

passed = failed = 0
errors = []

def db():
    c = psycopg2.connect(**DB); c.autocommit = True; return c

def api_list(ent, uid=None):
    h = {'X-Tenant-Id': str(T)}
    if uid: h['X-User-Id'] = str(uid)
    return requests.get(f'{API}/entity/data/{ent}?page=1&size=50', headers=h, timeout=10).json()

def api_get(ent, did, uid=None):
    h = {'X-Tenant-Id': str(T)}
    if uid: h['X-User-Id'] = str(uid)
    return requests.get(f'{API}/entity/data/{ent}/{did}', headers=h, timeout=10).json()

def test(name, fn):
    global passed, failed
    try: fn(); passed += 1; print(f"  ✅ {name}")
    except Exception as e: failed += 1; errors.append(f"{name}: {e}"); print(f"  ❌ {name}: {e}")

def _a(cond, msg=""): 
    if not cond: raise AssertionError(msg)

def total_of(r):
    if 'data' not in r: raise AssertionError(f"无 data: {json.dumps(r, ensure_ascii=False)[:200]}")
    return int(r['data'].get('total', 0))

def ids_of(r):
    return {int(x['id']) for x in r.get('data', {}).get('records', [])}


def setup():
    conn = db(); cur = conn.cursor()
    ent = 'tpgTest'

    # 清理
    cur.execute("DELETE FROM paas_entity_data.p_tenant_data_route WHERE tenant_id=%s AND entity_api_key=%s", (T, ent))
    cur.execute("DELETE FROM p_data_share_route WHERE tenant_id=%s AND entity_api_key=%s", (T, ent))
    cur.execute("DELETE FROM paas_entity_data.p_tenant_data_0 WHERE tenant_id=%s AND entity_api_key=%s", (T, ent))
    cur.execute("DELETE FROM p_data_share_0 WHERE tenant_id=%s AND entity_api_key=%s", (T, ent))
    cur.execute("DELETE FROM p_public_group_member WHERE tenant_id=%s", (T,))
    cur.execute("DELETE FROM p_common_metadata WHERE entity_api_key=%s AND metamodel_api_key='dataPermission'", (ent,))

    # 路由
    cur.execute("""INSERT INTO paas_entity_data.p_tenant_data_route
        (id,tenant_id,entity_api_key,table_index,delete_flg,created_at,updated_at)
        VALUES (%s,%s,%s,0,0,%s,%s)""", (hash(ent+'r1') % 2**62, T, ent, ts(), ts()))
    cur.execute("""INSERT INTO p_data_share_route
        (id,tenant_id,entity_api_key,table_index,delete_flg,created_at,updated_at)
        VALUES (%s,%s,%s,0,0,%s,%s)""", (hash(ent+'r2') % 2**62, T, ent, ts(), ts()))

    # 业务数据：A 有 3 条，B 有 2 条
    for i in range(3):
        cur.execute("""INSERT INTO paas_entity_data.p_tenant_data_0
            (id,tenant_id,entity_api_key,name,owner_id,depart_id,delete_flg,lock_status,approval_status,created_at,updated_at)
            VALUES (%s,%s,%s,%s,%s,90001,0,1,0,%s,%s)""",
            (600000+i, T, ent, f'PG_A_{i}', USER_A, ts(), ts()))
    for i in range(2):
        cur.execute("""INSERT INTO paas_entity_data.p_tenant_data_0
            (id,tenant_id,entity_api_key,name,owner_id,depart_id,delete_flg,lock_status,approval_status,created_at,updated_at)
            VALUES (%s,%s,%s,%s,%s,90002,0,1,0,%s,%s)""",
            (600010+i, T, ent, f'PG_B_{i}', USER_B, ts(), ts()))

    # share：将 A 的前 2 条共享给公共组 pg_vip_service（cause=5 共享规则）
    for i in range(2):
        cur.execute("""INSERT INTO p_data_share_0
            (id,tenant_id,entity_api_key,data_id,subject_api_key,subject_type,access_level,share_cause,delete_flg,created_at,updated_at)
            VALUES (%s,%s,%s,%s,%s,2,1,5,0,%s,%s)""",
            (650000+i, T, ent, 600000+i, PG_VIP, ts(), ts()))

    # 公共组成员：USER_C 是 pg_vip_service 的成员
    cur.execute("""INSERT INTO p_public_group_member
        (id,tenant_id,group_api_key,user_id,user_api_key,role_type,delete_flg,created_at,updated_at)
        VALUES (%s,%s,%s,%s,%s,0,0,%s,%s)""",
        (660001, T, PG_VIP, USER_C, str(USER_C), ts(), ts()))

    # dataPermission：defaultAccess=0（私有）
    cur.execute("""INSERT INTO p_common_metadata
        (id,metamodel_api_key,entity_api_key,api_key,label,namespace,
         dbc_smallint1,dbc_smallint2,dbc_smallint3,delete_flg,created_at,updated_at)
        VALUES (%s,'dataPermission',%s,%s,'PG测试权限','system',0,0,2,0,%s,%s)""",
        (hash(ent+'dp') % 2**62, ent, f'{ent}_dp', ts(), ts()))

    cur.close(); conn.close()
    print("  ✅ 测试数据构造完成")


def cleanup():
    conn = db(); cur = conn.cursor()
    ent = 'tpgTest'
    cur.execute("DELETE FROM paas_entity_data.p_tenant_data_0 WHERE tenant_id=%s AND entity_api_key=%s", (T, ent))
    cur.execute("DELETE FROM p_data_share_0 WHERE tenant_id=%s AND entity_api_key=%s", (T, ent))
    cur.execute("DELETE FROM p_public_group_member WHERE tenant_id=%s", (T,))
    cur.execute("DELETE FROM p_common_metadata WHERE id=%s", (hash(ent+'dp') % 2**62,))
    cur.execute("DELETE FROM paas_entity_data.p_tenant_data_route WHERE tenant_id=%s AND entity_api_key=%s", (T, ent))
    cur.execute("DELETE FROM p_data_share_route WHERE tenant_id=%s AND entity_api_key=%s", (T, ent))
    cur.close(); conn.close()
    print("  ✅ 清理完成")


def run_tests():
    ent = 'tpgTest'

    print("\n══════════════════════════════════════════════════")
    print("  公共组权限端到端测试")
    print("══════════════════════════════════════════════════")

    # 场景 1：公共组成员通过 share 看到被共享的数据
    print("\n📦 1. 公共组成员查询")

    test("USER_C(公共组成员) → 看到 share 授权的 2 条", lambda: (
        _r := api_list(ent, uid=USER_C),
        _a(total_of(_r) == 2, f"期望2, 实际{total_of(_r)}"),
        _a(ids_of(_r) == {600000, 600001}, f"id 不对: {ids_of(_r)}")
    )[-1])

    test("USER_C 不能看到未共享的数据", lambda: (
        _r := api_list(ent, uid=USER_C),
        _a(600002 not in ids_of(_r), "不应看到 A 的第 3 条"),
        _a(len(ids_of(_r) & {600010, 600011}) == 0, "不应看到 B 的数据")
    )[-1])

    # 场景 2：不在公共组的用户看不到
    print("\n📦 2. 非公共组成员")

    test("USER_D(非公共组成员) → 0 条", lambda: (
        _r := api_list(ent, uid=USER_D),
        _a(total_of(_r) == 0, f"期望0, 实际{total_of(_r)}")
    )[-1])

    # 场景 3：负责人仍然能看到自己的数据
    print("\n📦 3. 负责人 + 公共组混合")

    test("USER_A(负责人) → 看到自己的 3 条", lambda: (
        _r := api_list(ent, uid=USER_A),
        _a(total_of(_r) == 3, f"期望3, 实际{total_of(_r)}")
    )[-1])

    test("USER_B(负责人) → 看到自己的 2 条", lambda: (
        _r := api_list(ent, uid=USER_B),
        _a(total_of(_r) == 2, f"期望2, 实际{total_of(_r)}")
    )[-1])

    # 场景 4：单条查询
    print("\n📦 4. 单条查询权限")

    test("USER_C 查 share 授权的数据 → 有数据", lambda: (
        _r := api_get(ent, 600000, uid=USER_C),
        _a(_r.get('code') == 200 and _r.get('data') is not None, f"应返回数据: {_r}")
    )[-1])

    test("USER_C 查未授权的数据 → null", lambda: (
        _r := api_get(ent, 600002, uid=USER_C),
        _a(_r.get('code') == 200, "应返回200"),
        _a(_r.get('data') is None, f"不应有数据: {_r.get('data')}")
    )[-1])

    test("USER_D 查任何数据 → null", lambda: (
        _r := api_get(ent, 600000, uid=USER_D),
        _a(_r.get('code') == 200, "应返回200"),
        _a(_r.get('data') is None, f"不应有数据")
    )[-1])

    # 场景 5：无 userId 跳过过滤
    print("\n📦 5. 内部调用")

    test("无 userId → 全部 5 条", lambda: (
        _r := api_list(ent, uid=None),
        _a(total_of(_r) == 5, f"期望5, 实际{total_of(_r)}")
    )[-1])


def main():
    try:
        requests.get(f'{API}/actuator/health', timeout=3)
        print(f"✅ 服务运行中: {API}")
    except:
        print(f"❌ 服务未运行"); sys.exit(1)

    try:
        cleanup()
        setup()
        run_tests()
    finally:
        cleanup()

    print(f"\n══════════════════════════════════════════════════")
    print(f"  结果: {passed} passed, {failed} failed")
    print(f"══════════════════════════════════════════════════")
    if errors:
        print("\n❌ 失败详情:")
        for e in errors: print(f"  - {e}")
    sys.exit(1 if failed else 0)

if __name__ == '__main__':
    main()
