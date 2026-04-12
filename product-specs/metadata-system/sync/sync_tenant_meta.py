#!/usr/bin/env python3
"""Tenant 级元数据同步：5 个标准实体"""
import psycopg2, psycopg2.extras, time, re, sys

DB = dict(host='10.65.2.6', port=5432, dbname='crm_cd_data',
          user='xsy_metarepo', password='sk29XGLI%iu88pF*',
          options='-c search_path=public,xsy_metarepo', connect_timeout=10)
TID = 292193
ENT_MAP = {1:'account', 2:'contact', 3:'opportunity', 4:'lead', 5:'product'}

ITYPE = {1:1,2:8,3:4,4:16,5:2,6:10,7:3,8:8,10:5,21:15,22:13,23:12,24:14,
         26:21,27:6,29:19,31:9,32:18,33:11,34:17,38:20,39:22,40:27,41:7,99:99}
DTYPE = {1:1,2:3,3:3,4:1,5:3,6:None,7:None,8:5,9:6,10:4,11:4,12:1,13:1,
         14:1,15:3,16:1,17:3,18:1,19:1,20:1,21:None,22:1,27:None,99:None}
VIRTUAL = {6,7,21,27}
_seq = int(time.time()*1000) << 20

def nid():
    global _seq; _seq += 1; return _seq

def P(msg):
    print(msg, flush=True)

def cvt_dbc(old):
    m = re.match(r'(dbc_)(\w+?)_(\d+)', old)
    if not m: return old
    pm = {'varchar':'varchar','svarchar':'varchar','select':'varchar',
          'integer':'bigint','date':'bigint','relation':'bigint',
          'real':'decimal','tinyint':'smallint','textarea':'textarea'}
    return f"dbc_{pm.get(m.group(2), m.group(2))}{m.group(3)}"

def main():
    P("="*60)
    P(f"Tenant 级元数据同步 (tid={TID})")
    P("="*60)
    conn = psycopg2.connect(**DB); conn.autocommit = False
    cur = conn.cursor()
    cur.execute("SET statement_timeout = '30s'")

    try:
        # Step 0: ID 映射
        P("\n── Step 0: ID 映射 ──")
        cur.execute("SELECT id, api_key FROM p_common_metadata WHERE metamodel_api_key='entity' AND delete_flg=0 AND api_key IS NOT NULL")
        eid_map = {r[0]:r[1] for r in cur.fetchall()}
        for k,v in ENT_MAP.items(): eid_map[k] = v
        P(f"  entity: {len(eid_map)}")

        iid_map = {}
        for bid in ENT_MAP:
            cur.execute("SELECT id, api_key FROM xsy_metarepo.b_item WHERE tenant_id=%s AND belong_id=%s AND delete_flg=0 AND api_key IS NOT NULL", (TID, bid))
            for r in cur.fetchall(): iid_map[r[0]] = r[1]
        P(f"  item: {len(iid_map)}")

        cur.execute("SELECT id, api_key FROM xsy_metarepo.p_custom_entity_link WHERE tenant_id=%s AND delete_flg=0 AND api_key IS NOT NULL", (TID,))
        lid_map = {r[0]:r[1] for r in cur.fetchall()}
        P(f"  link: {len(lid_map)}")

        cfm = {}
        for ent in ENT_MAP.values():
            cur.execute("SELECT api_key, dbc_varchar3 FROM p_common_metadata WHERE metamodel_api_key='item' AND entity_api_key=%s AND delete_flg=0 AND api_key IS NOT NULL", (ent,))
            for r in cur.fetchall(): cfm[(ent, r[0])] = r[1]
        P(f"  common fields: {len(cfm)}")

        # Step 1: busiType
        P("\n── Step 1: busiType ──")
        cur.execute("SELECT * FROM xsy_metarepo.b_entity_belong_type WHERE tenant_id=%s AND belong_id IN (1,2,3,4,5) AND del_flg=0", (TID,))
        cols = [d[0] for d in cur.description]
        bt = 0
        for row in cur.fetchall():
            r = dict(zip(cols, row))
            ent = ENT_MAP.get(r['belong_id'])
            if not ent: continue
            cur.execute("""INSERT INTO p_tenant_busi_type
                (tenant_id,id,api_key,label,label_key,namespace,metamodel_api_key,entity_api_key,
                 custom_flg,delete_flg,metadata_order,created_at,created_by,updated_at,updated_by,
                 dbc_smallint1,dbc_smallint2,dbc_int1)
                VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING""",
                (TID, nid(), r.get('api_key') or str(r['id']),
                 r.get('type_name') or r.get('name'), r.get('label_key'),
                 'tenant','busiType',ent,0,0,r.get('type_order'),
                 r.get('created_at'),r.get('created_by'),r.get('updated_at'),r.get('updated_by'),
                 1 if r.get('status',1)==1 else 0, r.get('default_flg',0), r.get('special_flg',0)))
            bt += 1
        P(f"  写入 {bt} 条")

        # Step 2: item（逐 entity 查询避免超时）
        P("\n── Step 2: item ──")
        it = 0
        for bid, ent in ENT_MAP.items():
            cur.execute("SELECT * FROM xsy_metarepo.b_item WHERE tenant_id=%s AND belong_id=%s AND delete_flg=0", (TID, bid))
            cols = [d[0] for d in cur.description]
            ec = 0
            for row in cur.fetchall():
                r = dict(zip(cols, row))
                ak = r.get('api_key')
                if not ak: continue
                ot = r.get('item_type_entry') or 1
                nt = ITYPE.get(ot, ot); dt = DTYPE.get(nt)
                # dbColumn
                odc = r.get('db_column') or ''
                ndc = None
                if nt not in VIRTUAL:
                    ndc = cfm.get((ent, ak))
                    if not ndc and odc.startswith('dbc_'):
                        ndc = cvt_dbc(odc)
                # refs
                re_ent = eid_map.get(r.get('relation_belong_id')) if r.get('relation_belong_id') else None
                re_lnk = lid_map.get(r.get('refer_link_id')) if r.get('refer_link_id') else None
                sf = r.get('system_item_flg', 0)
                ns = 'system' if sf == 1 else 'tenant'
                cf = 0 if sf == 1 else 1
                cur.execute("""INSERT INTO p_tenant_item
                    (tenant_id,id,api_key,label,label_key,namespace,metamodel_api_key,entity_api_key,
                     custom_flg,delete_flg,metadata_order,description,created_at,created_by,updated_at,updated_by,
                     dbc_int1,dbc_int2,dbc_int3,dbc_int4,dbc_int5,dbc_int6,
                     dbc_varchar1,dbc_varchar2,dbc_varchar3,dbc_varchar4,dbc_varchar5,
                     dbc_textarea1,dbc_textarea2,
                     dbc_smallint1,dbc_smallint2,dbc_smallint3,dbc_smallint4,
                     dbc_smallint5,dbc_smallint6,dbc_smallint7,dbc_smallint8)
                    VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                           %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT DO NOTHING""",
                    (TID,nid(),ak,r.get('item_name'),r.get('label_key'),ns,'item',ent,cf,0,
                     r.get('item_order'),r.get('description'),r.get('created_at'),r.get('created_by'),
                     r.get('updated_at'),r.get('updated_by'),
                     nt,dt,r.get('item_order'),r.get('readonly_status'),r.get('visible_status'),r.get('sort_flg'),
                     re_ent,re_lnk,ndc,
                     r.get('input_caution') or r.get('help_text_key'), r.get('help_text_key'),
                     r.get('type_property'),r.get('default_value'),
                     r.get('must_enter_flg',0),r.get('use_flg',1),r.get('hidden_flg',0),r.get('unique_key_flg',0),
                     r.get('creatable',1),r.get('updatable',1),r.get('enable_history_log',0),r.get('enable_deactive',0)))
                ec += 1
            P(f"  {ent}: {ec} 条")
            it += ec
        P(f"  合计 {it} 条 item")

        # Step 3: pickOption
        P("\n── Step 3: pickOption ──")
        po = 0
        for bid, ent in ENT_MAP.items():
            cur.execute("SELECT * FROM xsy_metarepo.b_select_item WHERE tenant_id=%s AND belong_id=%s", (TID, bid))
            cols = [d[0] for d in cur.description]
            for row in cur.fetchall():
                r = dict(zip(cols, row))
                iak = iid_map.get(r.get('item_id'))
                oak = r.get('api_key') or str(r.get('option_code', r.get('id')))
                cur.execute("""INSERT INTO p_tenant_pick_option
                    (tenant_id,id,api_key,label,label_key,namespace,metamodel_api_key,
                     entity_api_key,parent_metadata_api_key,custom_flg,delete_flg,metadata_order,
                     dbc_int1,dbc_smallint1,dbc_smallint2)
                    VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING""",
                    (TID,nid(),oak,r.get('option_label') or r.get('item_name'),
                     r.get('option_label_key') or r.get('label_key'),
                     'tenant','pickOption',ent,iak,0,0,r.get('option_order',0),
                     r.get('option_code'),r.get('default_flg',0),1))
                po += 1
        # b_check_item
        try:
            for bid, ent in ENT_MAP.items():
                cur.execute("SELECT * FROM xsy_metarepo.b_check_item WHERE tenant_id=%s AND belong_id=%s", (TID, bid))
                cols = [d[0] for d in cur.description]
                for row in cur.fetchall():
                    r = dict(zip(cols, row))
                    iak = iid_map.get(r.get('item_id'))
                    oak = r.get('api_key') or str(r.get('option_code', r.get('id')))
                    cur.execute("""INSERT INTO p_tenant_pick_option
                        (tenant_id,id,api_key,label,label_key,namespace,metamodel_api_key,
                         entity_api_key,parent_metadata_api_key,custom_flg,delete_flg,metadata_order,
                         dbc_int1,dbc_smallint1,dbc_smallint2)
                        VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING""",
                        (TID,nid(),oak,r.get('option_label') or r.get('item_name'),
                         r.get('option_label_key'),
                         'tenant','pickOption',ent,iak,0,0,r.get('option_order',0),
                         r.get('option_code'),r.get('default_flg',0),1))
                    po += 1
        except Exception as e:
            P(f"  b_check_item: {e}")
            conn.rollback()
            cur.execute("SET statement_timeout = '30s'")
        P(f"  写入 {po} 条 pickOption")

        # Step 4: entityLink
        P("\n── Step 4: entityLink ──")
        el = 0
        for bid, ent in ENT_MAP.items():
            cur.execute("""SELECT * FROM xsy_metarepo.p_custom_entity_link
                WHERE tenant_id=%s AND (parent_entity_id=%s OR child_entity_id=%s) AND delete_flg=0""",
                (TID, bid, bid))
            cols = [d[0] for d in cur.description]
            for row in cur.fetchall():
                r = dict(zip(cols, row))
                pe = eid_map.get(r.get('parent_entity_id'))
                ce = eid_map.get(r.get('child_entity_id'))
                ri = iid_map.get(r.get('refer_item_id'))
                ea = pe or ce or 'unknown'
                cur.execute("""INSERT INTO p_tenant_entity_link
                    (tenant_id,id,api_key,label,label_key,namespace,metamodel_api_key,entity_api_key,
                     custom_flg,delete_flg,created_at,created_by,updated_at,updated_by,
                     dbc_varchar1,dbc_varchar2,dbc_varchar3,dbc_int1,
                     dbc_smallint1,dbc_smallint2,dbc_smallint3,dbc_smallint4)
                    VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT DO NOTHING""",
                    (TID,nid(),r.get('api_key') or str(r['id']),
                     r.get('label') or r.get('name'),r.get('label_key'),
                     'tenant','entityLink',ea,0,0,
                     r.get('created_at'),r.get('created_by'),r.get('updated_at'),r.get('updated_by'),
                     pe,ce,ri,r.get('link_type'),
                     r.get('cascade_delete',0),r.get('access_control',0),
                     r.get('detail_link',0),r.get('enable_flg',1)))
                el += 1
        P(f"  写入 {el} 条 entityLink")

        conn.commit()
        P(f"\n{'='*60}")
        P(f"✅ 同步完成: busiType={bt}, item={it}, pickOption={po}, entityLink={el}, 总计={bt+it+po+el}")
        P("="*60)

        # 验证
        P("\n── 验证 ──")
        for tbl in ['p_tenant_busi_type','p_tenant_item','p_tenant_pick_option','p_tenant_entity_link']:
            cur.execute(f"SELECT entity_api_key, namespace, custom_flg, COUNT(*) FROM {tbl} WHERE tenant_id=%s GROUP BY 1,2,3 ORDER BY 1,2", (TID,))
            P(f"\n  {tbl}:")
            for r in cur.fetchall():
                P(f"    {r[0]:15s} ns={r[1]:8s} custom={r[2]} cnt={r[3]}")

    except Exception as e:
        conn.rollback()
        P(f"\n❌ 失败: {e}")
        import traceback; traceback.print_exc()
    finally:
        cur.close(); conn.close()

if __name__ == '__main__':
    main()
