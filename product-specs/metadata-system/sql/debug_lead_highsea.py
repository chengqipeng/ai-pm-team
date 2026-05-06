#!/usr/bin/env python3
"""Debug: trace the full query chain for leadHighSea"""
import psycopg2, psycopg2.extras

conn = psycopg2.connect(host='127.0.0.1', port=5432, dbname='paas_db',
    user='postgres', password='123456')
cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

print("=" * 60)
print("Step 1: TableRouteService.resolveTableIndex")
cur.execute("""
    SELECT table_index FROM paas_entity_data.p_tenant_data_route
    WHERE tenant_id = 292193 AND entity_api_key = 'leadHighSea' AND delete_flg = 0
""")
route = cur.fetchone()
print(f"  route = {route}")
if not route:
    print("  FAIL: no route!")
    conn.close()
    exit()
ti = route['table_index']
tbl = f"paas_entity_data.p_tenant_data_{ti}"

print(f"\nStep 2: EntityColumnResolver - item metadata")
cur.execute("""
    SELECT api_key, dbc_varchar3 as db_column
    FROM paas_metarepo_common.p_common_metadata
    WHERE metamodel_api_key = 'item' AND entity_api_key = 'leadHighSea' AND delete_flg = 0
""")
items = cur.fetchall()
print(f"  items = {len(items)}")
for i in items:
    print(f"    {i['api_key']:20s} -> {i['db_column']}")

print(f"\nStep 3: COUNT query on {tbl}")
cur.execute(f"""
    SELECT COUNT(*) as cnt FROM {tbl}
    WHERE entity_api_key = 'leadHighSea' AND tenant_id = 292193 AND delete_flg = 0
""")
cnt = cur.fetchone()['cnt']
print(f"  count = {cnt}")

print(f"\nStep 4: SELECT data from {tbl}")
fixed = ["id","entity_api_key","name","owner_id","depart_api_key",
         "busitype_api_key","tenant_id","delete_flg","updated_at"]
dbc = [i['db_column'] for i in items if i['db_column'] and i['db_column'].startswith('dbc_')]
cols = fixed + dbc
cur.execute(f"SELECT {', '.join(cols)} FROM {tbl} WHERE entity_api_key = 'leadHighSea' AND tenant_id = 292193 AND delete_flg = 0 ORDER BY updated_at DESC LIMIT 5")
rows = cur.fetchall()
print(f"  rows = {len(rows)}")
for r in rows:
    print(f"    name={r['name']!r}, depart={r['depart_api_key']}")

print(f"\nStep 5: Compare with highSea (which works)")
cur.execute("SELECT table_index FROM paas_entity_data.p_tenant_data_route WHERE tenant_id = 292193 AND entity_api_key = 'highSea' AND delete_flg = 0")
hs = cur.fetchone()
if hs:
    cur.execute(f"SELECT COUNT(*) as cnt FROM paas_entity_data.p_tenant_data_{hs['table_index']} WHERE entity_api_key = 'highSea' AND tenant_id = 292193 AND delete_flg = 0")
    print(f"  highSea: route={hs['table_index']}, count={cur.fetchone()['cnt']}")

print(f"\nStep 6: Check if p_tenant_data_route has delete_flg column issue")
cur.execute("SELECT column_name FROM information_schema.columns WHERE table_schema='paas_entity_data' AND table_name='p_tenant_data_route' ORDER BY ordinal_position")
route_cols = [r['column_name'] for r in cur.fetchall()]
print(f"  route table columns: {route_cols}")

print(f"\nStep 7: Check route with different delete_flg conditions")
cur.execute("SELECT entity_api_key, table_index, delete_flg FROM paas_entity_data.p_tenant_data_route WHERE entity_api_key = 'leadHighSea'")
for r in cur.fetchall():
    print(f"  {r}")

conn.close()
print("\nDone.")
