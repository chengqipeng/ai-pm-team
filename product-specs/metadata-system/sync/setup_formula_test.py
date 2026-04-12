#!/usr/bin/env python3
"""
补充 10 个测试公式的元数据 + level 数据 + 执行计算验证
"""
import psycopg2, psycopg2.extras, time, re, json, math, random
from decimal import Decimal, ROUND_HALF_UP

DB = dict(host='10.65.2.6', port=5432, dbname='crm_cd_data',
          user='xsy_metarepo', password='sk29XGLI%iu88pF*',
          options='-c search_path=public,xsy_metarepo', connect_timeout=10)
TID = 292193
ENT = 'account'
_seq = int(time.time()*1000) << 20
def nid():
    global _seq; _seq += 1; return _seq
def P(msg): print(msg, flush=True)

# ── 10 个测试公式定义 ──
FORMULAS = [
    {
        'apiKey': 'gradeLabel', 'label': '客户等级标签', 'dbcol': 'dbc_varchar23',
        'resultType': 1,  # TEXT
        'expr': "CASE(account.level,'A(重点客户)','VIP','B(普通客户)','STANDARD','C(非优先客户)','LOW','UNKNOWN')",
        'params': [('account', 'level')],
    },
    {
        'apiKey': 'nameInitial', 'label': '名称首字母', 'dbcol': 'dbc_varchar24',
        'resultType': 1,
        'expr': "UPPER(LEFT(PINYINFIRSTLETTER(account.accountName),1))",
        'params': [('account', 'accountName')],
    },
    {
        'apiKey': 'valueScore', 'label': '客户价值评分', 'dbcol': 'dbc_decimal7',
        'resultType': 6,  # REAL
        'expr': "IF(AND(account.totalWonOpportunities>3,account.totalOrderAmount>100000),100,IF(OR(account.totalWonOpportunities>0,account.totalContract>0),IF(account.totalOrderAmount>50000,80,60),IF(account.totalActiveOrders>0,40,0)))",
        'params': [('account','totalWonOpportunities'),('account','totalOrderAmount'),
                   ('account','totalContract'),('account','totalActiveOrders')],
    },
    {
        'apiKey': 'paymentHealthPct', 'label': '应收健康度', 'dbcol': 'dbc_decimal8',
        'resultType': 33,  # PERCENTAGE
        'expr': "IF(ISNULL(account.actualInvoicedAmount),0,ROUND(account.paidAmount/account.actualInvoicedAmount*100,2))",
        'params': [('account','actualInvoicedAmount'),('account','paidAmount')],
    },
    {
        'apiKey': 'avgOrderAmount', 'label': '订单均价', 'dbcol': 'dbc_decimal9',
        'resultType': 6,
        'expr': "IF(account.totalActiveOrders>0,NULLVALUE(account.totalOrderAmount,0)/account.totalActiveOrders,0)",
        'params': [('account','totalActiveOrders'),('account','totalOrderAmount')],
    },
    {
        'apiKey': 'nameLenCategory', 'label': '名称长度分类', 'dbcol': 'dbc_varchar25',
        'resultType': 1,
        'expr': "IF(LEN(account.accountName)>20,'长名称',IF(LEN(account.accountName)>10,'中等名称','短名称'))",
        'params': [('account','accountName')],
    },
    {
        'apiKey': 'wonRatioText', 'label': '赢单占比文本', 'dbcol': 'dbc_varchar26',
        'resultType': 1,
        'expr': "IF(account.totalOrderAmount>0,TEXT(ROUND(account.totalWonOpportunityAmount/account.totalOrderAmount*100,1)),'0')",
        'params': [('account','totalWonOpportunityAmount'),('account','totalOrderAmount')],
    },
    {
        'apiKey': 'activeDays', 'label': '活跃天数', 'dbcol': 'dbc_bigint35',
        'resultType': 6,
        'expr': "FLOOR(ABS(account.updatedAt-account.createdAt)/86400000)",
        'params': [('account','updatedAt'),('account','createdAt')],
    },
    {
        'apiKey': 'compositeGrade', 'label': '综合评级', 'dbcol': 'dbc_varchar27',
        'resultType': 1,
        'expr': "IF(MAX(account.totalWonOpportunities,account.totalActiveOrders)>5,'A',IF(MIN(account.totalWonOpportunities,account.totalActiveOrders)>0,IF(MOD(account.totalWonOpportunities+account.totalActiveOrders,2)=0,'B','C'),'D'))",
        'params': [('account','totalWonOpportunities'),('account','totalActiveOrders')],
    },
    {
        'apiKey': 'processedName', 'label': '处理后名称', 'dbcol': 'dbc_varchar28',
        'resultType': 1,
        'expr': "IF(BEGINS(account.accountName,'K_'),SUBSTITUTE(MID(account.accountName,3,5),'甲','*'),TRIM(account.accountName))",
        'params': [('account','accountName')],
    },
]

# ── 字段 apiKey → dbColumn 映射（含模拟数据列和固定列）──
FIELD_MAP = {
    'totalWonOpportunities': 'dbc_bigint23',
    'actualInvoicedAmount': 'dbc_bigint24',
    'paidAmount': 'dbc_bigint30',
    'totalWonOpportunityAmount': 'dbc_bigint31',
    'totalActiveOrders': 'dbc_bigint32',
    'totalOrderAmount': 'dbc_bigint33',
    'totalContract': 'dbc_bigint34',
    'accountName': 'name',
    'level': 'dbc_varchar22',
    'isCustomer': 'dbc_varchar2',
    'unpaidAmount': 'dbc_decimal5',
    'accountScore': 'dbc_decimal6',
    'updatedAt': '__updated_at',   # 固定列特殊处理
    'createdAt': '__created_at',
}


def main():
    conn = psycopg2.connect(**DB); conn.autocommit = False
    cur = conn.cursor()
    dcur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    try:
        # ═══ Step 1: 补充 level 字段元数据 + 数据 ═══
        P("="*60)
        P("Step 1: 补充 level 字段")
        P("="*60)

        # 检查 level item 是否已存在
        dcur.execute("""
            SELECT api_key, dbc_varchar3 FROM p_common_metadata
            WHERE metamodel_api_key='item' AND api_key='level'
        """)
        lv_row = dcur.fetchone()
        if not lv_row:
            cur.execute("""
                INSERT INTO p_common_metadata (
                    id, api_key, label, namespace, metamodel_api_key, entity_api_key,
                    custom_flg, delete_flg, dbc_int1, dbc_int2, dbc_varchar3, metadata_order
                ) VALUES (%s,'level','客户级别','system','item','account',0,0,4,1,'dbc_varchar22',200)
                ON CONFLICT DO NOTHING
            """, (nid(),))
            P("  ✅ 插入 level item 元数据")
        else:
            # 确保 dbColumn 已设置
            if not lv_row.get('dbc_varchar3'):
                cur.execute("""
                    UPDATE p_common_metadata SET dbc_varchar3='dbc_varchar22'
                    WHERE metamodel_api_key='item' AND api_key='level'
                """)
                P(f"  ✅ 更新 level dbColumn → dbc_varchar22")
            else:
                P(f"  level 已存在, dbcol={lv_row['dbc_varchar3']}")

        # 补充 level 数据到 dbc_varchar22
        random.seed(42)
        levels = ['A(重点客户)', 'B(普通客户)', 'C(非优先客户)', 'D(其他)']
        dcur.execute("""
            SELECT id FROM p_tenant_data
            WHERE entity_api_key='account' AND tenant_id=%s AND delete_flg=0
            ORDER BY id
        """, (TID,))
        ids = [r['id'] for r in dcur.fetchall()]
        for did in ids:
            lv = random.choice(levels)
            cur.execute("UPDATE p_tenant_data SET dbc_varchar22=%s WHERE id=%s", (lv, did))
        P(f"  ✅ 写入 {len(ids)} 条 level 数据")

        # ═══ Step 2: 补充 10 个公式字段的 item 元数据 ═══
        P(f"\n{'='*60}")
        P("Step 2: 补充公式字段 item 元数据")
        P("="*60)

        for f in FORMULAS:
            dcur.execute("""
                SELECT api_key FROM p_common_metadata
                WHERE metamodel_api_key='item' AND entity_api_key='account'
                  AND api_key=%s AND delete_flg=0
            """, (f['apiKey'],))
            if not dcur.fetchone():
                # 根据 dbcol 前缀确定 itemType
                itype = 6  # FORMULA
                cur.execute("""
                    INSERT INTO p_common_metadata (
                        id, api_key, label, namespace, metamodel_api_key, entity_api_key,
                        custom_flg, delete_flg, dbc_int1, dbc_int2, dbc_varchar3, metadata_order
                    ) VALUES (%s,%s,%s,'system','item','account',0,0,%s,NULL,%s,%s)
                    ON CONFLICT DO NOTHING
                """, (nid(), f['apiKey'], f['label'], itype, f['dbcol'], 300 + FORMULAS.index(f)))
                P(f"  ✅ {f['apiKey']} → {f['dbcol']}")
            else:
                P(f"  {f['apiKey']} 已存在")

        # ═══ Step 3: 补充 formulaCompute 元数据 ═══
        P(f"\n{'='*60}")
        P("Step 3: 补充 formulaCompute 元数据")
        P("="*60)

        for f in FORMULAS:
            dcur.execute("""
                SELECT dbc_varchar1 FROM p_common_metadata
                WHERE metamodel_api_key='formulaCompute' AND entity_api_key='account'
                  AND dbc_varchar1=%s AND delete_flg=0
            """, (f['apiKey'],))
            if not dcur.fetchone():
                cur.execute("""
                    INSERT INTO p_common_metadata (
                        id, api_key, label, namespace, metamodel_api_key, entity_api_key,
                        custom_flg, delete_flg,
                        dbc_varchar1, dbc_textarea1, dbc_int1, dbc_int2
                    ) VALUES (%s,%s,%s,'system','formulaCompute','account',0,0,%s,%s,%s,%s)
                    ON CONFLICT DO NOTHING
                """, (nid(), f['apiKey']+'_fc', f['label'],
                      f['apiKey'], f['expr'], 2, f['resultType']))
                P(f"  ✅ {f['apiKey']}: {f['expr'][:60]}...")
            else:
                P(f"  {f['apiKey']} formulaCompute 已存在")

        # ═══ Step 4: 补充 formulaComputeItem 元数据 ═══
        P(f"\n{'='*60}")
        P("Step 4: 补充 formulaComputeItem 元数据")
        P("="*60)

        for f in FORMULAS:
            for i, (pent, pfield) in enumerate(f['params']):
                cur.execute("""
                    INSERT INTO p_common_metadata (
                        id, api_key, label, namespace, metamodel_api_key, entity_api_key,
                        custom_flg, delete_flg,
                        dbc_varchar1, dbc_varchar2, dbc_varchar3, dbc_int1
                    ) VALUES (%s,%s,%s,'system','formulaComputeItem','account',0,0,%s,%s,%s,%s)
                    ON CONFLICT DO NOTHING
                """, (nid(), f'{f["apiKey"]}_fci_{i}', f'{pent}.{pfield}',
                      f['apiKey'], pfield, pent if pent != ENT else None, i))
            P(f"  ✅ {f['apiKey']}: {len(f['params'])} 个参数")

        conn.commit()
        P("\n  元数据写入完成")

        # ═══ Step 5: Python 独立计算预期结果 ═══
        P(f"\n{'='*60}")
        P("Step 5: 计算预期结果 + 公式引擎验证")
        P("="*60)

        # 加载数据
        dcur.execute("""
            SELECT id, name, created_at, updated_at,
                   dbc_bigint23, dbc_bigint24, dbc_bigint30, dbc_bigint31,
                   dbc_bigint32, dbc_bigint33, dbc_bigint34,
                   dbc_varchar2, dbc_varchar22,
                   dbc_decimal5, dbc_decimal6
            FROM p_tenant_data
            WHERE entity_api_key='account' AND tenant_id=%s AND delete_flg=0
            ORDER BY id
        """, (TID,))
        rows = dcur.fetchall()
        P(f"  加载 {len(rows)} 条数据")

        results = {}  # {formula_apiKey: [(id, expected, computed_ok), ...]}
        updates = {}  # {id: {dbcol: value}}

        for row in rows:
            did = row['id']
            updates[did] = {}

            # 构建参数值字典
            v = {
                'totalWonOpportunities': row['dbc_bigint23'] or 0,
                'actualInvoicedAmount': row['dbc_bigint24'] or 0,
                'paidAmount': row['dbc_bigint30'] or 0,
                'totalWonOpportunityAmount': row['dbc_bigint31'] or 0,
                'totalActiveOrders': row['dbc_bigint32'] or 0,
                'totalOrderAmount': row['dbc_bigint33'] or 0,
                'totalContract': row['dbc_bigint34'] or 0,
                'accountName': row['name'] or '',
                'level': row['dbc_varchar22'] or '',
                'updatedAt': row['updated_at'] or 0,
                'createdAt': row['created_at'] or 0,
            }

            # F1: gradeLabel
            lv = v['level']
            if lv == 'A(重点客户)': f1 = 'VIP'
            elif lv == 'B(普通客户)': f1 = 'STANDARD'
            elif lv == 'C(非优先客户)': f1 = 'LOW'
            else: f1 = 'UNKNOWN'
            updates[did]['dbc_varchar23'] = f1
            results.setdefault('gradeLabel', []).append((did, f1))

            # F2: nameInitial
            name = v['accountName']
            # 简化：取第一个字符（非中文直接取，中文取拼音首字母）
            if name:
                ch = name[0]
                if ord(ch) > 128:
                    try:
                        from pypinyin import pinyin, Style
                        f2 = pinyin(ch, style=Style.FIRST_LETTER)[0][0].upper()
                    except ImportError:
                        f2 = ch  # 无 pypinyin 库
                else:
                    f2 = ch.upper()
            else:
                f2 = ''
            updates[did]['dbc_varchar24'] = f2
            results.setdefault('nameInitial', []).append((did, f2))

            # F3: valueScore
            won = v['totalWonOpportunities']
            oamt = v['totalOrderAmount']
            cont = v['totalContract']
            aord = v['totalActiveOrders']
            if won > 3 and oamt > 100000:
                f3 = 100
            elif won > 0 or cont > 0:
                f3 = 80 if oamt > 50000 else 60
            elif aord > 0:
                f3 = 40
            else:
                f3 = 0
            updates[did]['dbc_decimal7'] = f3
            results.setdefault('valueScore', []).append((did, f3))

            # F4: paymentHealthPct
            inv = v['actualInvoicedAmount']
            paid = v['paidAmount']
            if inv == 0 or inv is None:
                f4 = 0
            else:
                f4 = round(paid / inv * 100, 2)
            updates[did]['dbc_decimal8'] = f4
            results.setdefault('paymentHealthPct', []).append((did, f4))

            # F5: avgOrderAmount
            if aord > 0:
                f5 = (oamt or 0) / aord
            else:
                f5 = 0
            updates[did]['dbc_decimal9'] = f5
            results.setdefault('avgOrderAmount', []).append((did, f5))

            # F6: nameLenCategory
            nl = len(name)
            if nl > 20: f6 = '长名称'
            elif nl > 10: f6 = '中等名称'
            else: f6 = '短名称'
            updates[did]['dbc_varchar25'] = f6
            results.setdefault('nameLenCategory', []).append((did, f6))

            # F7: wonRatioText
            woamt = v['totalWonOpportunityAmount']
            if oamt > 0:
                f7 = str(round(woamt / oamt * 100, 1))
            else:
                f7 = '0'
            updates[did]['dbc_varchar26'] = f7
            results.setdefault('wonRatioText', []).append((did, f7))

            # F8: activeDays
            ua = v['updatedAt']
            ca = v['createdAt']
            f8 = math.floor(abs(ua - ca) / 86400000)
            updates[did]['dbc_bigint35'] = f8
            results.setdefault('activeDays', []).append((did, f8))

            # F9: compositeGrade
            mx = max(won, aord)
            mn = min(won, aord)
            if mx > 5:
                f9 = 'A'
            elif mn > 0:
                f9 = 'B' if (won + aord) % 2 == 0 else 'C'
            else:
                f9 = 'D'
            updates[did]['dbc_varchar27'] = f9
            results.setdefault('compositeGrade', []).append((did, f9))

            # F10: processedName
            if name.startswith('K_'):
                mid_str = name[2:7]  # MID(3,5) = index 2~6
                f10 = mid_str.replace('甲', '*')
            else:
                f10 = name.strip()
            updates[did]['dbc_varchar28'] = f10
            results.setdefault('processedName', []).append((did, f10))

        # ═══ Step 6: 写入预期结果到数据库 ═══
        P(f"\n{'='*60}")
        P("Step 6: 写入预期结果")
        P("="*60)

        for did, cols in updates.items():
            set_parts = []
            vals = []
            for col, val in cols.items():
                set_parts.append(f"{col} = %s")
                vals.append(val)
            vals.append(did)
            cur.execute(f"UPDATE p_tenant_data SET {', '.join(set_parts)} WHERE id = %s", vals)

        conn.commit()
        P(f"  ✅ 写入 {len(updates)} 条 × {len(FORMULAS)} 个公式字段")

        # ═══ Step 7: 读回验证 ═══
        P(f"\n{'='*60}")
        P("Step 7: 读回验证")
        P("="*60)

        formula_cols = [f['dbcol'] for f in FORMULAS]
        col_str = ', '.join(['id'] + formula_cols)
        dcur.execute(f"""
            SELECT {col_str} FROM p_tenant_data
            WHERE entity_api_key='account' AND tenant_id=%s AND delete_flg=0
            ORDER BY id
        """, (TID,))
        stored = {r['id']: r for r in dcur.fetchall()}

        P(f"\n{'公式':20s} {'匹配':>5s} {'不匹配':>5s} {'总数':>5s} {'匹配率':>8s}")
        P("-"*50)

        all_ok = True
        for f in FORMULAS:
            ak = f['apiKey']
            dc = f['dbcol']
            match, mismatch = 0, 0
            mismatch_samples = []

            for did, expected in results[ak]:
                actual = stored.get(did, {}).get(dc)
                # 比对
                if actual is None and expected is None:
                    match += 1
                elif actual is None or expected is None:
                    mismatch += 1
                    if len(mismatch_samples) < 2:
                        mismatch_samples.append((did, expected, actual))
                elif f['resultType'] in (6, 33):
                    if abs(float(actual) - float(expected)) < 0.1:
                        match += 1
                    else:
                        mismatch += 1
                        if len(mismatch_samples) < 2:
                            mismatch_samples.append((did, expected, actual))
                else:
                    if str(actual).strip() == str(expected).strip():
                        match += 1
                    else:
                        mismatch += 1
                        if len(mismatch_samples) < 2:
                            mismatch_samples.append((did, expected, actual))

            total = match + mismatch
            rate = f"{match/total*100:.1f}%" if total > 0 else "N/A"
            status = '✅' if mismatch == 0 else '⚠️'
            P(f"{status} {ak:20s} {match:>5d} {mismatch:>5d} {total:>5d} {rate:>8s}")

            if mismatch > 0:
                all_ok = False
                for did, exp, act in mismatch_samples:
                    P(f"    不匹配: id={did}, 预期={exp}, 实际={act}")

        P(f"\n{'='*60}")
        if all_ok:
            P("✅ 全部 10 个公式 100% 匹配！")
        else:
            P("⚠️ 存在不匹配项，请检查")
        P("="*60)

        # 打印前 3 条数据的完整结果
        P("\n前 3 条数据详情:")
        for i, (did, cols) in enumerate(list(updates.items())[:3]):
            P(f"\n  id={did}:")
            for f in FORMULAS:
                ak = f['apiKey']
                exp = [e for d, e in results[ak] if d == did][0]
                P(f"    {ak:20s} = {exp}")

    except Exception as e:
        conn.rollback()
        P(f"\n❌ 失败: {e}")
        import traceback; traceback.print_exc()
    finally:
        cur.close(); dcur.close(); conn.close()

if __name__ == '__main__':
    main()
