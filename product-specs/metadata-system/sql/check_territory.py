import psycopg2, psycopg2.extras
conn = psycopg2.connect(host='127.0.0.1', port=5432, dbname='paas_db', user='postgres', password='123456')
cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

cur.execute("""
    SELECT api_key, label, dbc_int1 as item_type, dbc_varchar3 as db_column
    FROM paas_metarepo_common.p_common_metadata
    WHERE metamodel_api_key = 'item' AND entity_api_key = 'territory' AND delete_flg = 0
    ORDER BY api_key
""")
print("=== territory fields ===")
for r in cur.fetchall():
    print(f"  {r['api_key']:30s} type={r['item_type']} col={r['db_column']}")

cur.execute("SELECT table_index FROM paas_entity_data.p_tenant_data_route WHERE tenant_id=292193 AND entity_api_key='territory'")
route = cur.fetchone()
if route:
    ti = route['table_index']
    cur.execute(f"SELECT COUNT(*) as cnt FROM paas_entity_data.p_tenant_data_{ti} WHERE entity_api_key='territory' AND delete_flg=0")
    print(f"\nterritory data: {cur.fetchone()['cnt']} rows (shard {ti})")

cur.execute("""
    SELECT api_key, dbc_int1 as item_type, dbc_varchar3 as db_column, dbc_varchar1 as refer_entity
    FROM paas_metarepo_common.p_common_metadata
    WHERE metamodel_api_key = 'item' AND entity_api_key = 'account'
      AND api_key = 'territoryHighSeaId' AND delete_flg = 0
""")
print(f"\naccount.territoryHighSeaId: {cur.fetchone()}")

cur.execute("""
    SELECT api_key, dbc_int1, dbc_varchar3, dbc_varchar1
    FROM paas_metarepo_common.p_common_metadata
    WHERE metamodel_api_key = 'item' AND entity_api_key = 'lead'
      AND api_key LIKE '%territory%' AND delete_flg = 0
""")
print(f"lead territory fields: {cur.fetchall()}")

conn.close()
