#!/usr/bin/env python3
"""
数据权限端到端测试 — 模拟不同用户、不同权限配置下的查询行为。

测试策略：
  1. 在本地 PG 中构造测试数据（业务数据 + share 记录 + 权限配置）
  2. 通过 HTTP 请求调用 API，验证返回结果是否符合权限规则
  3. 测试完成后清理测试数据

前置条件：
  - 本地 PG 运行在 127.0.0.1:5432/paas_db
  - 服务运行在 127.0.0.1:18010
  - application-dev.yml 中 data-permission.skip-all=false（测试权限过滤）

测试场景矩阵：
  ┌──────────────────────┬──────────────────────────────────────────────────┐
  │ 场景                  │ 预期行为                                         │
  ├──────────────────────┼──────────────────────────────────────────────────┤
  │ 1. 无 userId          │ 跳过过滤，返回全部数据                            │
  │ 2. 负责人查自己的数据   │ owner_id 匹配，返回自己负责的数据                  │
  │ 3. 非负责人无 share    │ 无权限，返回空                                    │
  │ 4. 通过 share 表授权   │ share 表中有记录，返回被共享的数据                  │
  │ 5. defaultAccess=2    │ 全员可见，跳过过滤，返回全部                        │
  │ 6. 无 dataPermission  │ 无权限配置，跳过过滤，返回全部                      │
  │ 7. hasFullDataAccess  │ 全量访问权限用户，跳过过滤（当前未实现，跳过）        │
  │ 8. 部门匹配           │ depart_id 匹配用户部门，返回部门内数据（需 TODO 完成）│
  └──────────────────────┴──────────────────────────────────────────────────┘

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

DB = dict(
    host='127.0.0.1', port=5432, dbname='paas_db',
    user='postgres', password='123456',
    options='-c search_path=public'
)
API_BASE = 'http://127.0.0.1:18010'

# 测试用租户和用户（避免与真实数据冲突）
TEST_TENANT = 999999
TEST_ENTITY = 'testPermEntity'
# 测试用户
USER_OWNER_A = 80001    # 负责人 A，拥有 5 条数据
USER_OWNER_B = 80002    # 负责人 B，拥有 3 条数据
USER_VIEWER  = 80003    # 普通查看者，无数据，但通过 share 可看到部分数据
USER_NOBODY  = 80004    # 无任何权限的用户
# 测试部门
DEPT_SALES   = 90001
DEPT_SUPPORT = 90002


# ═══════════════════════════════════════════════════════════
# 数据库操作
# ═══════════════════════════════════════════════════════════

def get_conn():
    conn = psycopg2.connect(**DB)
    conn.autocommit = True
    return conn

def setup_test_data():
    """构造测试数据"""
    conn = get_conn()
    cur = conn.cursor()

    print("\n📦 构造测试数据...")

    # ── 1. 确保路由表中有测试 entity 的路由 ──
    # 业务数据路由到 p_tenant_data_0（复用已有的分片表）
    cur.execute("""
        DELETE FROM paas_entity_data.p_tenant_data_route
        WHERE tenant_id = %s AND entity_api_key = %s
    """, (TEST_TENANT, TEST_ENTITY))
    cur.execute("""
        INSERT INTO paas_entity_data.p_tenant_data_route
            (id, tenant_id, entity_api_key, table_index, delete_flg, created_at, updated_at)
        VALUES (900000001, %s, %s, 0, 0, %s, %s)
    """, (TEST_TENANT, TEST_ENTITY, int(time.time()*1000), int(time.time()*1000)))

    # share 路由到 p_data_share_0
    cur.execute("""
        DELETE FROM p_data_share_route
        WHERE tenant_id = %s AND entity_api_key = %s
    """, (TEST_TENANT, TEST_ENTITY))
    cur.execute("""
        INSERT INTO p_data_share_route
            (id, tenant_id, entity_api_key, table_index, delete_flg, created_at, updated_at)
        VALUES (900000002, %s, %s, 0, 0, %s, %s)
    """, (TEST_TENANT, TEST_ENTITY, int(time.time()*1000), int(time.time()*1000)))

    # ── 2. 插入业务数据 ──
    # 先清理
    cur.execute("DELETE FROM paas_entity_data.p_tenant_data_0 WHERE tenant_id = %s AND entity_api_key = %s",
                (TEST_TENANT, TEST_ENTITY))
    # USER_OWNER_A 的 5 条数据（部门 DEPT_SALES）
    for i in range(5):
        cur.execute("""
            INSERT INTO paas_entity_data.p_tenant_data_0
                (id, tenant_id, entity_api_key, name, owner_id, depart_id, delete_flg, lock_status, approval_status, created_at, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, 0, 1, 0, %s, %s)
        """, (800000 + i, TEST_TENANT, TEST_ENTITY, f'TestData_A_{i}',
              USER_OWNER_A, DEPT_SALES, int(time.time()*1000), int(time.time()*1000)))

    # USER_OWNER_B 的 3 条数据（部门 DEPT_SUPPORT）
    for i in range(3):
        cur.execute("""
            INSERT INTO paas_entity_data.p_tenant_data_0
                (id, tenant_id, entity_api_key, name, owner_id, depart_id, delete_flg, lock_status, approval_status, created_at, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, 0, 1, 0, %s, %s)
        """, (800010 + i, TEST_TENANT, TEST_ENTITY, f'TestData_B_{i}',
              USER_OWNER_B, DEPT_SUPPORT, int(time.time()*1000), int(time.time()*1000)))

    print(f"  ✅ 业务数据: A={USER_OWNER_A}(5条), B={USER_OWNER_B}(3条), 共 8 条")

    # ── 3. 插入 share 记录 ──
    cur.execute("DELETE FROM p_data_share_0 WHERE tenant_id = %s AND entity_api_key = %s",
                (TEST_TENANT, TEST_ENTITY))
    # USER_VIEWER 可以看到 USER_OWNER_A 的前 2 条数据（手动共享，只读）
    for i in range(2):
        cur.execute("""
            INSERT INTO p_data_share_0
                (id, tenant_id, entity_api_key, data_id, subject_api_key, subject_type, access_level, share_cause, delete_flg, created_at, updated_at)
            VALUES (%s, %s, %s, %s, %s, 0, 1, 6, 0, %s, %s)
        """, (900010 + i, TEST_TENANT, TEST_ENTITY, 800000 + i,
              str(USER_VIEWER), int(time.time()*1000), int(time.time()*1000)))

    print(f"  ✅ share 记录: VIEWER={USER_VIEWER} 可看 A 的 2 条数据")

    # ── 4. 插入 dataPermission 配置（defaultAccess=0 私有模式）──
    cur.execute("DELETE FROM p_common_metadata WHERE id = 900000010")
    cur.execute("""
        INSERT INTO p_common_metadata
            (id, metamodel_api_key, entity_api_key, api_key, label, namespace,
             dbc_smallint1, dbc_smallint2, dbc_smallint3, dbc_smallint4,
             delete_flg, created_at, updated_at)
        VALUES (%s, 'dataPermission', %s, %s, '测试权限配置', 'system',
                0, 0, 2, 0,
                0, %s, %s)
    """, (900000010, TEST_ENTITY, f'{TEST_ENTITY}_data_permission',
          int(time.time()*1000), int(time.time()*1000)))

    print(f"  ✅ dataPermission: defaultAccess=0(私有), ownerAccess=2(读写)")

    # ── 5. 清除 Redis 缓存（避免旧缓存干扰）──
    # 通过 API 无法直接清缓存，依赖 TTL 过期或重启服务

    cur.close()
    conn.close()
    print("  ✅ 测试数据构造完成")


def cleanup_test_data():
    """清理测试数据"""
    conn = get_conn()
    cur = conn.cursor()

    print("\n🧹 清理测试数据...")

    cur.execute("DELETE FROM paas_entity_data.p_tenant_data_0 WHERE tenant_id = %s AND entity_api_key = %s",
                (TEST_TENANT, TEST_ENTITY))
    cur.execute("DELETE FROM p_data_share_0 WHERE tenant_id = %s AND entity_api_key = %s",
                (TEST_TENANT, TEST_ENTITY))
    cur.execute("DELETE FROM p_common_metadata WHERE id = 900000010")
    cur.execute("DELETE FROM p_tenant_data_permission WHERE tenant_id = %s AND entity_api_key = %s",
                (TEST_TENANT, TEST_ENTITY))
    cur.execute("DELETE FROM paas_entity_data.p_tenant_data_route WHERE tenant_id = %s AND entity_api_key = %s",
                (TEST_TENANT, TEST_ENTITY))
    cur.execute("DELETE FROM p_data_share_route WHERE tenant_id = %s AND entity_api_key = %s",
                (TEST_TENANT, TEST_ENTITY))

    cur.close()
    conn.close()
    print("  ✅ 清理完成")


def flush_redis_cache():
    """
    清除 Redis 中的权限相关缓存。
    注意：服务连的是远程 Redis 集群，本地可能无法直接清除。
    如果清除失败，测试通过使用不同的 entity_api_key 来避免缓存命中。
    """
    try:
        import redis
        r = redis.Redis(host='127.0.0.1', port=6379, db=0)
        r.ping()
        keys = r.keys(f'data_perm:{TEST_TENANT}:*')
        if keys:
            r.delete(*keys)
        keys = r.keys(f'ds_route:{TEST_TENANT}:*')
        if keys:
            r.delete(*keys)
        keys = r.keys(f'td_route:{TEST_TENANT}:*')
        if keys:
            r.delete(*keys)
        keys = r.keys(f'user_subjects:{TEST_TENANT}:*')
        if keys:
            r.delete(*keys)
        print("  ✅ Redis 缓存已清除")
    except Exception:
        pass  # 静默失败，测试通过不同 entity 避免缓存


def update_data_permission(default_access):
    """修改 dataPermission 的 defaultAccess"""
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("UPDATE p_common_metadata SET dbc_smallint1 = %s WHERE id = 900000010",
                (default_access,))
    cur.close()
    conn.close()


def remove_data_permission():
    """删除 dataPermission 配置"""
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("UPDATE p_common_metadata SET delete_flg = 1 WHERE id = 900000010")
    cur.close()
    conn.close()


def restore_data_permission():
    """恢复 dataPermission 配置"""
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("UPDATE p_common_metadata SET delete_flg = 0, dbc_smallint1 = 0 WHERE id = 900000010")
    cur.close()
    conn.close()


# ═══════════════════════════════════════════════════════════
# API 调用
# ═══════════════════════════════════════════════════════════

def api_list(entity_api_key, tenant_id=TEST_TENANT, user_id=None, page=1, size=20):
    """调用列表查询 API"""
    headers = {'X-Tenant-Id': str(tenant_id)}
    if user_id is not None:
        headers['X-User-Id'] = str(user_id)
    url = f'{API_BASE}/entity/data/{entity_api_key}?page={page}&size={size}'
    try:
        resp = requests.get(url, headers=headers, timeout=10)
        return resp.json()
    except Exception as e:
        return {'error': str(e)}


def api_get(entity_api_key, data_id, tenant_id=TEST_TENANT, user_id=None):
    """调用单条查询 API"""
    headers = {'X-Tenant-Id': str(tenant_id)}
    if user_id is not None:
        headers['X-User-Id'] = str(user_id)
    url = f'{API_BASE}/entity/data/{entity_api_key}/{data_id}'
    try:
        resp = requests.get(url, headers=headers, timeout=10)
        return resp.json()
    except Exception as e:
        return {'error': str(e)}


# ═══════════════════════════════════════════════════════════
# 测试用例
# ═══════════════════════════════════════════════════════════

passed = 0
failed = 0
errors = []

def test(name, fn):
    global passed, failed
    try:
        fn()
        passed += 1
        print(f"  ✅ {name}")
    except Exception as e:
        failed += 1
        errors.append(f"{name}: {e}")
        print(f"  ❌ {name}: {e}")


def assert_eq(actual, expected, msg=""):
    if actual != expected:
        raise AssertionError(f"{msg} 期望={expected}, 实际={actual}")


def assert_total(result, expected_total, msg=""):
    """断言返回的 total 数量"""
    if 'data' not in result:
        raise AssertionError(f"{msg} 响应无 data 字段: {json.dumps(result, ensure_ascii=False)[:200]}")
    total = result['data'].get('total')
    # total 可能是字符串或数字
    actual = int(total) if total is not None else 0
    if actual != expected_total:
        raise AssertionError(f"{msg} 期望 total={expected_total}, 实际={actual}")


def assert_records_contain_ids(result, expected_ids, msg=""):
    """断言返回的 records 包含指定的 id 集合"""
    records = result.get('data', {}).get('records', [])
    actual_ids = {int(r['id']) for r in records}
    expected_set = set(expected_ids)
    if not expected_set.issubset(actual_ids):
        missing = expected_set - actual_ids
        raise AssertionError(f"{msg} 缺少 id: {missing}, 实际返回: {actual_ids}")


def assert_records_not_contain_ids(result, excluded_ids, msg=""):
    """断言返回的 records 不包含指定的 id"""
    records = result.get('data', {}).get('records', [])
    actual_ids = {int(r['id']) for r in records}
    excluded_set = set(excluded_ids)
    overlap = excluded_set & actual_ids
    if overlap:
        raise AssertionError(f"{msg} 不应包含 id: {overlap}, 实际返回: {actual_ids}")


def run_tests():
    """运行所有测试"""

    print("\n══════════════════════════════════════════════════")
    print("  数据权限端到端测试")
    print("══════════════════════════════════════════════════")

    # ── 场景 1：无 userId（内部调用）→ 跳过过滤，返回全部 ──
    print("\n📦 场景 1：无 userId（内部调用）")

    def test_no_user_id():
        result = api_list(TEST_ENTITY, user_id=None)
        assert_total(result, 8, "无 userId 应返回全部 8 条")

    test("无 userId → 返回全部 8 条数据", test_no_user_id)

    # ── 场景 2：负责人查自己的数据 ──
    print("\n📦 场景 2：负责人查自己的数据")

    def test_owner_a_sees_own():
        result = api_list(TEST_ENTITY, user_id=USER_OWNER_A)
        assert_total(result, 5, "负责人 A 应看到自己的 5 条")
        assert_records_contain_ids(result, [800000, 800001, 800002, 800003, 800004])

    test(f"负责人 A(userId={USER_OWNER_A}) → 看到自己的 5 条", test_owner_a_sees_own)

    def test_owner_b_sees_own():
        result = api_list(TEST_ENTITY, user_id=USER_OWNER_B)
        assert_total(result, 3, "负责人 B 应看到自己的 3 条")
        assert_records_contain_ids(result, [800010, 800011, 800012])

    test(f"负责人 B(userId={USER_OWNER_B}) → 看到自己的 3 条", test_owner_b_sees_own)

    def test_owner_a_not_see_b():
        result = api_list(TEST_ENTITY, user_id=USER_OWNER_A)
        assert_records_not_contain_ids(result, [800010, 800011, 800012], "A 不应看到 B 的数据")

    test("负责人 A 不能看到 B 的数据", test_owner_a_not_see_b)

    # ── 场景 3：无权限用户 ──
    print("\n📦 场景 3：无权限用户")

    def test_nobody_sees_nothing():
        result = api_list(TEST_ENTITY, user_id=USER_NOBODY)
        assert_total(result, 0, "无权限用户应看到 0 条")

    test(f"无权限用户(userId={USER_NOBODY}) → 返回 0 条", test_nobody_sees_nothing)

    # ── 场景 4：通过 share 表授权 ──
    print("\n📦 场景 4：通过 share 表授权")

    def test_viewer_sees_shared():
        result = api_list(TEST_ENTITY, user_id=USER_VIEWER)
        # VIEWER 通过 share 可看到 A 的前 2 条（800000, 800001）
        assert_total(result, 2, "VIEWER 应看到 share 授权的 2 条")
        assert_records_contain_ids(result, [800000, 800001])

    test(f"VIEWER(userId={USER_VIEWER}) → 通过 share 看到 2 条", test_viewer_sees_shared)

    def test_viewer_not_see_unshared():
        result = api_list(TEST_ENTITY, user_id=USER_VIEWER)
        # VIEWER 不应看到 A 的第 3-5 条和 B 的数据
        assert_records_not_contain_ids(result, [800002, 800003, 800004, 800010, 800011, 800012])

    test("VIEWER 不能看到未共享的数据", test_viewer_not_see_unshared)

    # ── 场景 5：defaultAccess=2（全员读写）──
    print("\n📦 场景 5：defaultAccess=2（全员读写）")

    def test_public_access():
        # 用独立的 entity 避免缓存干扰
        ent = 'testPermPublic'
        conn = get_conn()
        cur = conn.cursor()
        # 路由
        cur.execute("DELETE FROM paas_entity_data.p_tenant_data_route WHERE tenant_id=%s AND entity_api_key=%s", (TEST_TENANT, ent))
        cur.execute("""INSERT INTO paas_entity_data.p_tenant_data_route (id,tenant_id,entity_api_key,table_index,delete_flg,created_at,updated_at)
                       VALUES (900000101,%s,%s,0,0,%s,%s)""", (TEST_TENANT, ent, int(time.time()*1000), int(time.time()*1000)))
        cur.execute("DELETE FROM p_data_share_route WHERE tenant_id=%s AND entity_api_key=%s", (TEST_TENANT, ent))
        cur.execute("""INSERT INTO p_data_share_route (id,tenant_id,entity_api_key,table_index,delete_flg,created_at,updated_at)
                       VALUES (900000102,%s,%s,0,0,%s,%s)""", (TEST_TENANT, ent, int(time.time()*1000), int(time.time()*1000)))
        # 数据
        for i in range(3):
            cur.execute("""INSERT INTO paas_entity_data.p_tenant_data_0
                (id,tenant_id,entity_api_key,name,owner_id,depart_id,delete_flg,lock_status,approval_status,created_at,updated_at)
                VALUES (%s,%s,%s,%s,%s,%s,0,1,0,%s,%s)""",
                (810000+i, TEST_TENANT, ent, f'Public_{i}', USER_OWNER_A, DEPT_SALES, int(time.time()*1000), int(time.time()*1000)))
        # dataPermission: defaultAccess=2
        cur.execute("""INSERT INTO p_common_metadata
            (id,metamodel_api_key,entity_api_key,api_key,label,namespace,dbc_smallint1,dbc_smallint2,dbc_smallint3,delete_flg,created_at,updated_at)
            VALUES (900000110,'dataPermission',%s,%s,'公开权限','system',2,0,2,0,%s,%s)""",
            (ent, f'{ent}_dp', int(time.time()*1000), int(time.time()*1000)))
        cur.close()
        conn.close()

        result = api_list(ent, user_id=USER_NOBODY)
        assert_total(result, 3, "全员读写模式下任何用户应看到全部 3 条")

        # 清理
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("DELETE FROM paas_entity_data.p_tenant_data_0 WHERE tenant_id=%s AND entity_api_key=%s", (TEST_TENANT, ent))
        cur.execute("DELETE FROM p_common_metadata WHERE id=900000110")
        cur.execute("DELETE FROM paas_entity_data.p_tenant_data_route WHERE tenant_id=%s AND entity_api_key=%s", (TEST_TENANT, ent))
        cur.execute("DELETE FROM p_data_share_route WHERE tenant_id=%s AND entity_api_key=%s", (TEST_TENANT, ent))
        cur.close()
        conn.close()

    test("defaultAccess=2 → 任何用户看到全部数据", test_public_access)

    # ── 场景 6：无 dataPermission 配置 ──
    print("\n📦 场景 6：无 dataPermission 配置")

    def test_no_config():
        # 用独立的 entity，不插入 dataPermission
        ent = 'testPermNoConfig'
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("DELETE FROM paas_entity_data.p_tenant_data_route WHERE tenant_id=%s AND entity_api_key=%s", (TEST_TENANT, ent))
        cur.execute("""INSERT INTO paas_entity_data.p_tenant_data_route (id,tenant_id,entity_api_key,table_index,delete_flg,created_at,updated_at)
                       VALUES (900000201,%s,%s,0,0,%s,%s)""", (TEST_TENANT, ent, int(time.time()*1000), int(time.time()*1000)))
        cur.execute("DELETE FROM p_data_share_route WHERE tenant_id=%s AND entity_api_key=%s", (TEST_TENANT, ent))
        cur.execute("""INSERT INTO p_data_share_route (id,tenant_id,entity_api_key,table_index,delete_flg,created_at,updated_at)
                       VALUES (900000202,%s,%s,0,0,%s,%s)""", (TEST_TENANT, ent, int(time.time()*1000), int(time.time()*1000)))
        for i in range(4):
            cur.execute("""INSERT INTO paas_entity_data.p_tenant_data_0
                (id,tenant_id,entity_api_key,name,owner_id,depart_id,delete_flg,lock_status,approval_status,created_at,updated_at)
                VALUES (%s,%s,%s,%s,%s,%s,0,1,0,%s,%s)""",
                (820000+i, TEST_TENANT, ent, f'NoConfig_{i}', USER_OWNER_A, DEPT_SALES, int(time.time()*1000), int(time.time()*1000)))
        # 不插入 dataPermission！
        cur.close()
        conn.close()

        result = api_list(ent, user_id=USER_NOBODY)
        assert_total(result, 4, "无权限配置时应跳过过滤，返回全部 4 条")

        # 清理
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("DELETE FROM paas_entity_data.p_tenant_data_0 WHERE tenant_id=%s AND entity_api_key=%s", (TEST_TENANT, ent))
        cur.execute("DELETE FROM paas_entity_data.p_tenant_data_route WHERE tenant_id=%s AND entity_api_key=%s", (TEST_TENANT, ent))
        cur.execute("DELETE FROM p_data_share_route WHERE tenant_id=%s AND entity_api_key=%s", (TEST_TENANT, ent))
        cur.close()
        conn.close()

    test("无 dataPermission 配置 → 跳过过滤，返回全部", test_no_config)

    # ── 场景 7：单条查询权限校验 ──
    print("\n📦 场景 7：单条查询权限校验")

    def test_get_own_data():
        result = api_get(TEST_ENTITY, 800000, user_id=USER_OWNER_A)
        assert_eq(result.get('code'), 200, "负责人查自己的数据应返回 200")
        assert result.get('data') is not None, "应返回数据"

    test(f"负责人 A 查自己的数据(id=800000) → 返回数据", test_get_own_data)

    def test_get_others_data_denied():
        result = api_get(TEST_ENTITY, 800010, user_id=USER_OWNER_A)
        # A 查 B 的数据，应返回 null（无权限）
        assert_eq(result.get('code'), 200, "应返回 200")
        assert result.get('data') is None or result['data'] == {}, "A 不应看到 B 的数据"

    test("负责人 A 查 B 的数据(id=800010) → 返回 null", test_get_others_data_denied)

    def test_get_shared_data():
        result = api_get(TEST_ENTITY, 800000, user_id=USER_VIEWER)
        # VIEWER 通过 share 可看到 800000
        assert_eq(result.get('code'), 200)
        assert result.get('data') is not None, "VIEWER 应能看到 share 授权的数据"

    test(f"VIEWER 查 share 授权的数据(id=800000) → 返回数据", test_get_shared_data)

    # ── 场景 8：负责人 + share 混合 ──
    print("\n📦 场景 8：混合权限场景")

    def test_owner_plus_share():
        """OWNER_A 自己的数据 + share 的 B 的数据，用独立 entity 避免缓存"""
        ent = 'testPermMix'
        conn = get_conn()
        cur = conn.cursor()
        # 路由
        cur.execute("DELETE FROM paas_entity_data.p_tenant_data_route WHERE tenant_id=%s AND entity_api_key=%s", (TEST_TENANT, ent))
        cur.execute("""INSERT INTO paas_entity_data.p_tenant_data_route (id,tenant_id,entity_api_key,table_index,delete_flg,created_at,updated_at)
                       VALUES (900000301,%s,%s,0,0,%s,%s)""", (TEST_TENANT, ent, int(time.time()*1000), int(time.time()*1000)))
        cur.execute("DELETE FROM p_data_share_route WHERE tenant_id=%s AND entity_api_key=%s", (TEST_TENANT, ent))
        cur.execute("""INSERT INTO p_data_share_route (id,tenant_id,entity_api_key,table_index,delete_flg,created_at,updated_at)
                       VALUES (900000302,%s,%s,0,0,%s,%s)""", (TEST_TENANT, ent, int(time.time()*1000), int(time.time()*1000)))
        # A 的 2 条数据
        for i in range(2):
            cur.execute("""INSERT INTO paas_entity_data.p_tenant_data_0
                (id,tenant_id,entity_api_key,name,owner_id,depart_id,delete_flg,lock_status,approval_status,created_at,updated_at)
                VALUES (%s,%s,%s,%s,%s,%s,0,1,0,%s,%s)""",
                (830000+i, TEST_TENANT, ent, f'Mix_A_{i}', USER_OWNER_A, DEPT_SALES, int(time.time()*1000), int(time.time()*1000)))
        # B 的 3 条数据
        for i in range(3):
            cur.execute("""INSERT INTO paas_entity_data.p_tenant_data_0
                (id,tenant_id,entity_api_key,name,owner_id,depart_id,delete_flg,lock_status,approval_status,created_at,updated_at)
                VALUES (%s,%s,%s,%s,%s,%s,0,1,0,%s,%s)""",
                (830010+i, TEST_TENANT, ent, f'Mix_B_{i}', USER_OWNER_B, DEPT_SUPPORT, int(time.time()*1000), int(time.time()*1000)))
        # share: A 可看 B 的第 1 条
        cur.execute("""INSERT INTO p_data_share_0
            (id,tenant_id,entity_api_key,data_id,subject_api_key,subject_type,access_level,share_cause,delete_flg,created_at,updated_at)
            VALUES (900030,%s,%s,%s,%s,0,1,6,0,%s,%s)""",
            (TEST_TENANT, ent, 830010, str(USER_OWNER_A), int(time.time()*1000), int(time.time()*1000)))
        # dataPermission: defaultAccess=0
        cur.execute("""INSERT INTO p_common_metadata
            (id,metamodel_api_key,entity_api_key,api_key,label,namespace,dbc_smallint1,dbc_smallint2,dbc_smallint3,delete_flg,created_at,updated_at)
            VALUES (900000310,'dataPermission',%s,%s,'混合权限','system',0,0,2,0,%s,%s)""",
            (ent, f'{ent}_dp', int(time.time()*1000), int(time.time()*1000)))
        cur.close()
        conn.close()

        result = api_list(ent, user_id=USER_OWNER_A)
        # A 应看到自己的 2 条 + share 的 1 条 = 3 条
        assert_total(result, 3, "A 应看到自己的 2 条 + share 的 1 条 = 3 条")
        assert_records_contain_ids(result, [830000, 830001, 830010])

        # 清理
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("DELETE FROM paas_entity_data.p_tenant_data_0 WHERE tenant_id=%s AND entity_api_key=%s", (TEST_TENANT, ent))
        cur.execute("DELETE FROM p_data_share_0 WHERE tenant_id=%s AND entity_api_key=%s", (TEST_TENANT, ent))
        cur.execute("DELETE FROM p_common_metadata WHERE id=900000310")
        cur.execute("DELETE FROM paas_entity_data.p_tenant_data_route WHERE tenant_id=%s AND entity_api_key=%s", (TEST_TENANT, ent))
        cur.execute("DELETE FROM p_data_share_route WHERE tenant_id=%s AND entity_api_key=%s", (TEST_TENANT, ent))
        cur.close()
        conn.close()

    test("负责人 A(2条) + share B 的 1 条 → 看到 3 条", test_owner_plus_share)


# ═══════════════════════════════════════════════════════════
# 主入口
# ═══════════════════════════════════════════════════════════

def main():
    # 检查服务是否运行
    try:
        resp = requests.get(f'{API_BASE}/actuator/health', timeout=3)
        print(f"✅ 服务运行中: {API_BASE}")
    except Exception:
        print(f"❌ 服务未运行: {API_BASE}")
        print("   请先启动服务: mvn spring-boot:run -pl paas-platform-service-server -Dspring-boot.run.profiles=dev")
        sys.exit(1)

    try:
        cleanup_test_data()  # 先清理可能残留的测试数据
        setup_test_data()
        run_tests()
    finally:
        cleanup_test_data()

    # 结果汇总
    print("\n══════════════════════════════════════════════════")
    print(f"  结果: {passed} passed, {failed} failed")
    print("══════════════════════════════════════════════════")

    if errors:
        print("\n❌ 失败详情:")
        for err in errors:
            print(f"  - {err}")

    sys.exit(1 if failed else 0)


if __name__ == '__main__':
    main()
