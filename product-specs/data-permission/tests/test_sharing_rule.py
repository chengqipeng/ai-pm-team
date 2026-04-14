#!/usr/bin/env python3
"""
共享规则引擎端到端测试。
验证：数据创建后，共享规则自动匹配并写入 share 记录，查询时权限过滤生效。

测试场景：
  1. 基于负责人的规则：owner 属于公共组 → 数据共享给目标公共组
  2. 基于条件的规则：字段值匹配 → 数据共享给目标用户
  3. 规则未激活时不执行
  4. 多条规则同时匹配
"""
import psycopg2, requests, json, sys, time

DB = dict(host='127.0.0.1', port=5432, dbname='paas_db', user='postgres', password='123456', options='-c search_path=public')
API = 'http://127.0.0.1:18010'
T = 999777  # 独立测试租户
ts = lambda: int(time.time() * 1000)

OWNER_1 = 70001   # 负责人 1（属于公共组 pg_east）
OWNER_2 = 70002   # 负责人 2（不属于公共组）
VIEWER  = 70003   # 目标公共组成员
VIEWER2 = 70004   # 条件规则的目标用户
NOBODY  = 70005   # 无权限用户

passed = failed = 0
errors = []

def db():
    c = psycopg2.connect(**DB); c.autocommit = True; return c

def api_list(ent, uid=None):
    h = {'X-Tenant-Id': str(T)}
    if uid: h['X-User-Id'] = str(uid)
    return requests.get(f'{API}/entity/data/{ent}?page=1&size=50', headers=h, timeout=10).json()

def api_create(ent, body, uid=None):
    h = {'X-Tenant-Id': str(T), 'Content-Type': 'application/json'}
    if uid: h['X-User-Id'] = str(uid)
    return requests.post(f'{API}/entity/data/{ent}', headers=h, json=body, timeout=10).json()

def test(name, fn):
    global passed, failed
    try: fn(); passed += 1; print(f"  ✅ {name}")
    except Exception as e: failed += 1; errors.append(f"{name}: {e}"); print(f"  ❌ {name}: {e}")

def _a(cond, msg=""):
    if not cond: raise AssertionError(msg)

def total_of(r):
    if 'data' not in r: raise AssertionError(f"无 data: {json.dumps(r, ensure_ascii=False)[:200]}")
    return int(r['data'].get('total', 0))


def setup():
    """构造测试环境：路由 + 公共组成员 + 共享规则 + dataPermission + meta_item 种子"""
    conn = db(); cur = conn.cursor()
    ent = 'tsrTest'

    # 补充 sharingRule 和 sharingRuleCondition 的 p_meta_item 种子数据（如果不存在）
    cur.execute("SELECT COUNT(*) FROM p_meta_item WHERE metamodel_api_key='sharingRule' AND delete_flg=0")
    if cur.fetchone()[0] == 0:
        sr_items = [
            (1869200001, 'sharingRule', 'shareType', 'dbc_smallint1', 31, 6, 1),
            (1869200002, 'sharingRule', 'fromSubjectType', 'dbc_smallint2', 31, 6, 2),
            (1869200003, 'sharingRule', 'toSubjectType', 'dbc_smallint3', 31, 6, 3),
            (1869200004, 'sharingRule', 'accessLevel', 'dbc_smallint4', 31, 6, 4),
            (1869200005, 'sharingRule', 'scopeType', 'dbc_smallint5', 31, 6, 5),
            (1869200006, 'sharingRule', 'activeFlg', 'dbc_smallint6', 31, 6, 6),
            (1869200007, 'sharingRule', 'enableFlg', 'dbc_smallint7', 31, 6, 7),
            (1869200008, 'sharingRule', 'fromSubjectApiKey', 'dbc_varchar1', 1, 1, 8),
            (1869200009, 'sharingRule', 'toSubjectApiKey', 'dbc_varchar2', 1, 1, 9),
            (1869200010, 'sharingRule', 'criteriaLogic', 'dbc_varchar3', 1, 1, 10),
            (1869200014, 'sharingRule', 'ruleOrder', 'dbc_int1', 2, 4, 14),
        ]
        for item_id, mm, ak, dc, it, dt, order in sr_items:
            cur.execute("""INSERT INTO p_meta_item
                (id,metamodel_api_key,api_key,db_column,item_type,data_type,item_order,
                 label,label_key,namespace,require_flg,custom_flg,delete_flg,created_at,updated_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,'system',0,0,0,%s,%s)""",
                (item_id, mm, ak, dc, it, dt, order, ak, f'meta.{mm}.{ak}', ts(), ts()))
        print(f"  ✅ 补充 sharingRule p_meta_item: {len(sr_items)} 个")

    cur.execute("SELECT COUNT(*) FROM p_meta_item WHERE metamodel_api_key='sharingRuleCondition' AND delete_flg=0")
    if cur.fetchone()[0] == 0:
        src_items = [
            (1869300001, 'sharingRuleCondition', 'ruleApiKey', 'dbc_varchar1', 1, 1, 1),
            (1869300002, 'sharingRuleCondition', 'itemApiKey', 'dbc_varchar2', 1, 1, 2),
            (1869300003, 'sharingRuleCondition', 'operatorCode', 'dbc_varchar3', 1, 1, 3),
            (1869300004, 'sharingRuleCondition', 'conditionValue', 'dbc_varchar4', 1, 1, 4),
            (1869300005, 'sharingRuleCondition', 'conditionValueLabel', 'dbc_varchar5', 1, 1, 5),
            (1869300006, 'sharingRuleCondition', 'rowNo', 'dbc_int1', 2, 4, 6),
            (1869300007, 'sharingRuleCondition', 'conditionType', 'dbc_int2', 2, 4, 7),
        ]
        for item_id, mm, ak, dc, it, dt, order in src_items:
            cur.execute("""INSERT INTO p_meta_item
                (id,metamodel_api_key,api_key,db_column,item_type,data_type,item_order,
                 label,label_key,namespace,require_flg,custom_flg,delete_flg,created_at,updated_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,'system',0,0,0,%s,%s)""",
                (item_id, mm, ak, dc, it, dt, order, ak, f'meta.{mm}.{ak}', ts(), ts()))
        print(f"  ✅ 补充 sharingRuleCondition p_meta_item: {len(src_items)} 个")

    # 清理
    for tbl in ['paas_entity_data.p_tenant_data_0', 'p_data_share_0',
                'p_public_group_member', 'p_common_metadata',
                'paas_entity_data.p_tenant_data_route', 'p_data_share_route']:
        try:
            if 'p_common_metadata' in tbl:
                cur.execute(f"DELETE FROM {tbl} WHERE entity_api_key=%s AND metamodel_api_key IN ('dataPermission','sharingRule','sharingRuleCondition')", (ent,))
            elif 'p_public_group_member' in tbl:
                cur.execute(f"DELETE FROM {tbl} WHERE tenant_id=%s", (T,))
            else:
                cur.execute(f"DELETE FROM {tbl} WHERE tenant_id=%s AND entity_api_key=%s", (T, ent))
        except: pass

    # 路由
    cur.execute("""INSERT INTO paas_entity_data.p_tenant_data_route
        (id,tenant_id,entity_api_key,table_index,delete_flg,created_at,updated_at)
        VALUES (%s,%s,%s,0,0,%s,%s)""", (hash(ent+'r1') % 2**62, T, ent, ts(), ts()))
    cur.execute("""INSERT INTO p_data_share_route
        (id,tenant_id,entity_api_key,table_index,delete_flg,created_at,updated_at)
        VALUES (%s,%s,%s,0,0,%s,%s)""", (hash(ent+'r2') % 2**62, T, ent, ts(), ts()))

    # 公共组成员：OWNER_1 属于 pg_east，VIEWER 也属于 pg_east
    for uid, gak, sid in [(OWNER_1, 'pg_east', 770001), (VIEWER, 'pg_east', 770002)]:
        cur.execute("""INSERT INTO p_public_group_member
            (id,tenant_id,group_api_key,user_id,user_api_key,role_type,delete_flg,created_at,updated_at)
            VALUES (%s,%s,%s,%s,%s,0,0,%s,%s)""",
            (sid, T, gak, uid, str(uid), ts(), ts()))

    # dataPermission：defaultAccess=0（私有）
    cur.execute("""INSERT INTO p_common_metadata
        (id,metamodel_api_key,entity_api_key,api_key,label,namespace,
         dbc_smallint1,dbc_smallint2,dbc_smallint3,delete_flg,created_at,updated_at)
        VALUES (%s,'dataPermission',%s,%s,'SR测试权限','system',0,0,2,0,%s,%s)""",
        (hash(ent+'dp') % 2**62, ent, f'{ent}_dp', ts(), ts()))

    # 共享规则 1：基于负责人 — pg_east 的成员创建的数据共享给 pg_east（公共组）
    cur.execute("""INSERT INTO p_common_metadata
        (id,metamodel_api_key,entity_api_key,api_key,label,namespace,
         dbc_smallint1,dbc_smallint2,dbc_smallint3,dbc_smallint4,dbc_smallint5,dbc_smallint6,dbc_smallint7,
         dbc_varchar1,dbc_varchar2,
         delete_flg,created_at,updated_at)
        VALUES (%s,'sharingRule',%s,'sr_owner_to_pg','负责人共享给公共组','system',
                0,1,1,1,0,1,1,
                'pg_east','pg_east',
                0,%s,%s)""",
        (hash(ent+'sr1') % 2**62, ent, ts(), ts()))
    # shareType=0(基于负责人), fromSubjectType=1(公共组), toSubjectType=1(公共组)
    # accessLevel=1(只读), scopeType=0(全部), activeFlg=1, enableFlg=1
    # fromSubjectApiKey='pg_east', toSubjectApiKey='pg_east'

    # 共享规则 2：基于条件 — name 包含 'VIP' 的数据共享给 VIEWER2（用户）
    cur.execute("""INSERT INTO p_common_metadata
        (id,metamodel_api_key,entity_api_key,api_key,label,namespace,
         dbc_smallint1,dbc_smallint2,dbc_smallint3,dbc_smallint4,dbc_smallint5,dbc_smallint6,dbc_smallint7,
         dbc_varchar1,dbc_varchar2,dbc_varchar3,
         delete_flg,created_at,updated_at)
        VALUES (%s,'sharingRule',%s,'sr_vip_to_user','VIP数据共享给用户','system',
                1,0,0,1,0,1,1,
                '',%s,'',
                0,%s,%s)""",
        (hash(ent+'sr2') % 2**62, ent, str(VIEWER2), ts(), ts()))
    # shareType=1(基于条件), toSubjectType=0(用户), toSubjectApiKey=VIEWER2

    # 共享规则条件：name contain 'VIP'
    cur.execute("""INSERT INTO p_common_metadata
        (id,metamodel_api_key,entity_api_key,api_key,label,namespace,
         dbc_varchar1,dbc_varchar2,dbc_varchar3,dbc_varchar4,dbc_int1,
         delete_flg,created_at,updated_at)
        VALUES (%s,'sharingRuleCondition',%s,'src_vip_name','VIP名称条件','system',
                'sr_vip_to_user','name','contain','VIP',1,
                0,%s,%s)""",
        (hash(ent+'src1') % 2**62, ent, ts(), ts()))
    # ruleApiKey='sr_vip_to_user', itemApiKey='name', operatorCode='contain', conditionValue='VIP', rowNo=1

    # 共享规则 3：未激活的规则（不应执行）
    cur.execute("""INSERT INTO p_common_metadata
        (id,metamodel_api_key,entity_api_key,api_key,label,namespace,
         dbc_smallint1,dbc_smallint2,dbc_smallint3,dbc_smallint4,dbc_smallint5,dbc_smallint6,dbc_smallint7,
         dbc_varchar1,dbc_varchar2,
         delete_flg,created_at,updated_at)
        VALUES (%s,'sharingRule',%s,'sr_inactive','未激活规则','system',
                0,0,0,2,0,0,1,
                '',%s,
                0,%s,%s)""",
        (hash(ent+'sr3') % 2**62, ent, str(NOBODY), ts(), ts()))
    # activeFlg=0 → 不执行

    cur.close(); conn.close()
    print("  ✅ 测试环境构造完成")


def cleanup():
    conn = db(); cur = conn.cursor()
    ent = 'tsrTest'
    for tbl in ['paas_entity_data.p_tenant_data_0', 'p_data_share_0',
                'p_public_group_member',
                'paas_entity_data.p_tenant_data_route', 'p_data_share_route']:
        try:
            if 'p_public_group_member' in tbl:
                cur.execute(f"DELETE FROM {tbl} WHERE tenant_id=%s", (T,))
            else:
                cur.execute(f"DELETE FROM {tbl} WHERE tenant_id=%s AND entity_api_key=%s", (T, ent))
        except: pass
    cur.execute("DELETE FROM p_common_metadata WHERE entity_api_key=%s AND metamodel_api_key IN ('dataPermission','sharingRule','sharingRuleCondition')", (ent,))
    cur.close(); conn.close()
    print("  ✅ 清理完成")


def count_shares(ent, data_id=None, subject_api_key=None):
    """直接查 share 表验证 share 记录"""
    conn = db(); cur = conn.cursor()
    sql = "SELECT COUNT(*) FROM p_data_share_0 WHERE tenant_id=%s AND entity_api_key=%s AND delete_flg=0"
    params = [T, ent]
    if data_id:
        sql += " AND data_id=%s"; params.append(data_id)
    if subject_api_key:
        sql += " AND subject_api_key=%s"; params.append(subject_api_key)
    cur.execute(sql, params)
    cnt = cur.fetchone()[0]
    cur.close(); conn.close()
    return cnt


def run_tests():
    ent = 'tsrTest'

    print("\n══════════════════════════════════════════════════")
    print("  共享规则引擎端到端测试")
    print("══════════════════════════════════════════════════")

    # ── 场景 1：通过 API 创建数据，触发基于负责人的共享规则 ──
    print("\n📦 1. 基于负责人的共享规则")

    # 预生成 ID 通过 API
    next_ids_resp = requests.get(f'{API}/entity/data/next-ids?count=3',
                                  headers={'X-Tenant-Id': str(T)}, timeout=10).json()
    ids = next_ids_resp.get('data', {}).get('ids', [])
    print(f"  预生成 ID: {ids}")

    if len(ids) >= 3:
        # 创建数据 1：OWNER_1 的数据（应触发规则 1 → 共享给 pg_east）
        r1 = api_create(ent, {'id': ids[0], 'name': '客户Alpha', 'ownerId': OWNER_1, 'departId': 90001}, uid=OWNER_1)

        test("API 创建数据(OWNER_1) → 触发基于负责人规则", lambda: (
            _a(r1.get('code') == 200, f"创建应成功: {r1}"),
            # 验证 share 表中有 pg_east 的记录
            _a(count_shares(ent, data_id=ids[0], subject_api_key='pg_east') > 0,
               f"应有 pg_east 的 share 记录，实际: {count_shares(ent, data_id=ids[0], subject_api_key='pg_east')}")
        )[-1])

        test("VIEWER(pg_east 成员) → 能看到共享的数据", lambda: (
            _r := api_list(ent, uid=VIEWER),
            _a(total_of(_r) >= 1, f"VIEWER 应至少看到 1 条，实际: {total_of(_r)}")
        )[-1])

        # 创建数据 2：OWNER_2 的数据（不属于 pg_east，不应触发规则 1）
        r2 = api_create(ent, {'id': ids[1], 'name': '客户Beta', 'ownerId': OWNER_2, 'departId': 90002}, uid=OWNER_2)

        test("OWNER_2 创建数据 → 不触发基于负责人规则", lambda: (
            _a(r2.get('code') == 200, f"创建应成功: {r2}"),
            _a(count_shares(ent, data_id=ids[1], subject_api_key='pg_east') == 0,
               "OWNER_2 的数据不应有 pg_east 的 share")
        )[-1])

        # ── 场景 2：基于条件的共享规则 ──
        print("\n📦 2. 基于条件的共享规则")

        r3 = api_create(ent, {'id': ids[2], 'name': 'VIP大客户', 'ownerId': OWNER_2, 'departId': 90002}, uid=OWNER_2)

        test("创建 name 含 'VIP' 的数据 → 触发条件规则", lambda: (
            _a(r3.get('code') == 200, f"创建应成功: {r3}"),
            _a(count_shares(ent, data_id=ids[2], subject_api_key=str(VIEWER2)) > 0,
               f"应有 VIEWER2 的 share 记录，实际: {count_shares(ent, data_id=ids[2], subject_api_key=str(VIEWER2))}")
        )[-1])

        test("VIEWER2 → 能看到 VIP 数据", lambda: (
            _r := api_list(ent, uid=VIEWER2),
            _a(total_of(_r) >= 1, f"VIEWER2 应至少看到 1 条，实际: {total_of(_r)}")
        )[-1])

        # ── 场景 3：未激活规则不执行 ──
        print("\n📦 3. 未激活规则")

        test("NOBODY 不应看到任何数据（未激活规则不执行）", lambda: (
            _r := api_list(ent, uid=NOBODY),
            _a(total_of(_r) == 0, f"NOBODY 应看到 0 条，实际: {total_of(_r)}")
        )[-1])

        # ── 场景 4：负责人仍能看到自己的数据 ──
        print("\n📦 4. 负责人权限不受影响")

        test("OWNER_1 看到自己的数据", lambda: (
            _r := api_list(ent, uid=OWNER_1),
            _a(total_of(_r) >= 1, f"OWNER_1 应至少看到 1 条")
        )[-1])

        test("OWNER_2 看到自己的数据", lambda: (
            _r := api_list(ent, uid=OWNER_2),
            _a(total_of(_r) >= 1, f"OWNER_2 应至少看到 1 条")
        )[-1])

    else:
        print("  ⚠️ 无法获取 next-ids，跳过 API 创建测试")


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
