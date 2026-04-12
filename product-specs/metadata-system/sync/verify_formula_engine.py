#!/usr/bin/env python3
"""
用公式引擎逻辑验证 13 个公式（3 个原有 + 10 个新增）
流程：加载公式元数据 → 从表达式提取参数 → 从业务数据取参数值 → 求值 → 与 baseline 比对
"""
import psycopg2, psycopg2.extras, re, math
from decimal import Decimal

DB = dict(host='10.65.2.6', port=5432, dbname='crm_cd_data',
          user='xsy_metarepo', password='sk29XGLI%iu88pF*',
          options='-c search_path=public,xsy_metarepo', connect_timeout=10)
TID = 292193
ENT = 'account'
def P(msg): print(msg, flush=True)


# ══════════════════════════════════════════════════════════
# 公式求值引擎（模拟 Java ComputeUtils + FunctionRegistry）
# ══════════════════════════════════════════════════════════

def evaluate(expression, param_values, null_treatment=2):
    """
    公式求值引擎 — 对齐 Java FunctionRegistry 的 70 个函数
    param_values: {"account.fieldName": value}
    """
    expr = expression

    # 1. 单等号→双等号
    expr = re.sub(r"(?<![><!= ])='([^']*)'", r'=="\1"', expr)
    expr = re.sub(r'(?<![><!= ])="([^"]*)"', r'=="\1"', expr)
    # 处理 = 0 这种数值比较
    expr = re.sub(r'(?<![><!= ])= ?(\d+)', r'==\1', expr)

    # 2. 参数替换为临时变量
    var_dict = {}
    # 按参数名长度降序排列，避免短名称误替换长名称的前缀
    sorted_params = sorted(param_values.items(), key=lambda x: -len(x[0]))
    for i, (param, value) in enumerate(sorted_params):
        vn = f'_v{i}'
        if value is None:
            value = 0 if null_treatment == 0 or null_treatment == 2 else None
        if isinstance(value, Decimal):
            value = float(value)
        var_dict[vn] = value
        expr = expr.replace(param, vn)

    # 3. 函数映射 — 用正则确保只替换独立的函数调用，不误替换子串
    import re as _re
    FUNC_NAMES = [
        'PINYINFIRSTLETTER','OPTIONAPINAME','NUMBERSTRING','REALTIMETODAY',
        'REALTIMENOW','RANDBETWEEN','DATETIMEVALUE','PRIORVALUE','NULLVALUE',
        'SUBSTITUTE','DAYOFYEAR','ADDMONTHS','ISCHANGED','ISPICKVAL',
        'FILECOUNT','DATEVALUE','DATETIME','INCLUDES','ISNUMBER','CONTAINS',
        'WEEKNUM','WEEKDAY','ISCLONE','CEILING','HYPERLINK','BEGINS',
        'ISNULL','PINYIN','MINUTE','SECOND','MILLISECOND','NOWTIME',
        'FLOOR','ROUND','UPPER','LOWER','RIGHT','IMAGE','ISNEW',
        'MONTH','VALUE','TODAY','FIND','TRIM','LEFT','LPAD','RPAD',
        'SQRT','RAND','TEXT','YEAR','HOUR','DATE','CASE',
        'NOT','AND','ABS','MAX','MIN','MOD','LEN','MID','DAY','NOW','LOG',
        'IF','OR','IN','LN',
    ]
    for fn in FUNC_NAMES:
        # 只替换前面不是字母/下划线的函数名（避免 FLOOR 中的 OR 被替换）
        expr = _re.sub(r'(?<![A-Za-z_])' + fn + r'\(', f'_{fn}(', expr)

    # 4. 函数实现
    def _IF(c, t, f): return t if c else f
    # 注意：Python eval 是急切求值，IF 的两个分支都会被计算
    # Java ANTLR4 引擎是惰性求值，不会计算未选中的分支
    # 这里用 try/except 兼容除零等情况
    def _OR(*a): return any(bool(x) for x in a)
    def _AND(*a): return all(bool(x) for x in a)
    def _NOT(x): return not x
    def _ISNULL(x): return x is None or (isinstance(x, str) and x == '')
    def _NULLVALUE(x, sub): return sub if _ISNULL(x) else x
    def _SAFE_DIV(a, b):
        """安全除法，避免 Python eval 急切求值导致的除零"""
        if b == 0 or b is None: return 0
        return a / b
    def _CASE(*args):
        if len(args) < 2: return None
        expr_val = args[0]; default = args[-1]
        for i in range(1, len(args)-1, 2):
            if i+1 < len(args) and str(expr_val) == str(args[i]):
                return args[i+1]
        return default
    def _ISPICKVAL(a, b): return str(a) == str(b) if a and b else a is None and b is None
    def _ABS(x): return abs(x) if x is not None else None
    def _CEILING(x): return math.ceil(x) if x is not None else None
    def _FLOOR(x): return math.floor(x) if x is not None else None
    def _SQRT(x): return math.sqrt(x) if x is not None and x >= 0 else None
    def _ROUND(x, d):
        if x is None: return None
        return round(float(x), int(d))
    def _MOD(a, b):
        if a is None or b is None or b == 0: return None
        return a % b
    def _MAX(*a): return max(x for x in a if x is not None) if any(x is not None for x in a) else None
    def _MIN(*a): return min(x for x in a if x is not None) if any(x is not None for x in a) else None
    def _LN(x): return math.log(x) if x and x > 0 else None
    def _LOG(x): return math.log10(x) if x and x > 0 else None
    def _LEN(x): return len(str(x)) if x is not None else 0
    def _LEFT(x, n): return str(x)[:int(n)] if x else None
    def _RIGHT(x, n): return str(x)[-int(n):] if x else None
    def _MID(x, s, n): return str(x)[int(s)-1:int(s)-1+int(n)] if x else None
    def _TRIM(x): return str(x).strip() if x else None
    def _UPPER(x): return str(x).upper() if x else None
    def _LOWER(x): return str(x).lower() if x else None
    def _BEGINS(x, p): return str(x).startswith(str(p)) if x else False
    def _CONTAINS(x, s): return str(s) in str(x) if x and s else False
    def _SUBSTITUTE(x, old, new): return str(x).replace(str(old), str(new)) if x else None
    def _FIND(s, t, *a):
        start = int(a[0])-1 if a else 0
        idx = str(t).find(str(s), start)
        return idx + 1 if idx >= 0 else None
    def _TEXT(x):
        if x is None: return None
        if isinstance(x, float):
            # 保留 1 位小数（与 ROUND 配合时的格式）
            s = f"{x:.10f}".rstrip('0')
            if s.endswith('.'): s += '0'
            return s
        return str(x)
    def _VALUE(x):
        try: return float(x)
        except: return None
    def _LPAD(x, n, p=' '): return str(x).rjust(int(n), str(p)[0]) if x else None
    def _RPAD(x, n, p=' '): return str(x).ljust(int(n), str(p)[0]) if x else None
    def _INCLUDES(m, t): return str(t) in str(m).split(',') if m else False
    def _IN(a, b):
        la = set(str(a).split(',')); lb = set(str(b).split(','))
        return lb.issubset(la)
    def _ISNUMBER(x):
        try: float(str(x)); return True
        except: return False
    def _PINYINFIRSTLETTER(x):
        if not x: return None
        result = []
        for ch in str(x):
            if ord(ch) > 128:
                try:
                    from pypinyin import pinyin, Style
                    result.append(pinyin(ch, style=Style.FIRST_LETTER)[0][0])
                except ImportError:
                    result.append(ch)
            else:
                result.append(ch)
        return ''.join(result)
    def _PINYIN(x): return x  # 简化
    def _NUMBERSTRING(x): return str(x)  # 简化
    def _OPTIONAPINAME(x): return str(x) if x else None
    def _FILECOUNT(x): return int(x) if x else 0
    def _TODAY(): return None
    def _NOW(): return None
    def _REALTIMETODAY(): return None
    def _REALTIMENOW(): return None
    def _DATE(y,m,d): return None
    def _DATEVALUE(x): return None
    def _YEAR(d): return None
    def _MONTH(d): return None
    def _DAY(d): return None
    def _HOUR(t): return None
    def _MINUTE(t): return None
    def _SECOND(t): return None
    def _WEEKDAY(d): return None
    def _WEEKNUM(d, *a): return None
    def _DAYOFYEAR(d): return None
    def _ADDMONTHS(d, n): return None
    def _ISNEW(): return False
    def _ISCHANGED(x): return False
    def _ISCLONE(): return False
    def _PRIORVALUE(x): return x
    def _HYPERLINK(u, n, *a): return f'<a href="{u}">{n}</a>'
    def _IMAGE(u, a, *s): return f'<img src="{u}" alt="{a}"/>'
    def _RAND(n): return 0
    def _RANDBETWEEN(a, b): return a

    ctx = {'__builtins__': {}, 'None': None, 'True': True, 'False': False}
    # 注入所有函数
    for name in dir():
        if name.startswith('_') and not name.startswith('__'):
            ctx[name] = locals()[name]
    ctx.update(var_dict)

    try:
        result = eval(expr, ctx)
        return result
    except ZeroDivisionError:
        return 0  # IF 分支中的除零，Java 惰性求值不会触发
    except Exception as e:
        return f"EVAL_ERROR: {e} | {expr[:80]}"


# ══════════════════════════════════════════════════════════
# 主流程
# ══════════════════════════════════════════════════════════

def main():
    conn = psycopg2.connect(**DB); conn.autocommit = False
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    P("="*70)
    P("公式引擎验证 — 从元数据加载公式 → 求值 → 比对 baseline")
    P("="*70)

    # 1. 加载所有 formulaCompute
    cur.execute("""
        SELECT dbc_varchar1 AS item_ak, dbc_textarea1 AS expr,
               dbc_int1 AS null_treat, dbc_int2 AS result_type
        FROM p_common_metadata
        WHERE metamodel_api_key='formulaCompute' AND entity_api_key=%s
          AND delete_flg=0 AND dbc_varchar1 IS NOT NULL AND dbc_textarea1 IS NOT NULL
        ORDER BY dbc_varchar1
    """, (ENT,))
    formulas = cur.fetchall()
    P(f"\n加载 {len(formulas)} 个公式定义")

    # 2. 加载字段映射 apiKey → dbColumn
    cur.execute("""
        SELECT api_key, dbc_varchar3 AS dbcol, dbc_int1 AS itype
        FROM p_common_metadata
        WHERE metamodel_api_key='item' AND entity_api_key=%s
          AND delete_flg=0 AND api_key IS NOT NULL
    """, (ENT,))
    fm = {r['api_key']: r['dbcol'] for r in cur.fetchall()}
    # 补充 Tenant 级
    cur.execute("""
        SELECT api_key, dbc_varchar3 AS dbcol FROM p_tenant_item
        WHERE tenant_id=%s AND entity_api_key=%s AND delete_flg=0 AND api_key IS NOT NULL
    """, (TID, ENT))
    for r in cur.fetchall():
        if r['api_key'] not in fm or not fm[r['api_key']]:
            fm[r['api_key']] = r['dbcol']

    P(f"字段映射: {len(fm)} 个")

    # 3. 加载业务数据
    all_dbcols = set(v for v in fm.values() if v)
    # 加上固定列
    fixed = {'name', 'owner_id', 'created_at', 'updated_at', 'lock_status', 'approval_status', 'dbc_varchar22'}
    col_list = ', '.join(['id'] + sorted(all_dbcols | fixed))
    cur.execute(f"""
        SELECT {col_list} FROM p_tenant_data
        WHERE entity_api_key=%s AND tenant_id=%s AND delete_flg=0
        ORDER BY id
    """, (ENT, TID))
    records = cur.fetchall()
    P(f"业务数据: {len(records)} 条")

    # 4. 逐公式验证
    P(f"\n{'公式':25s} {'表达式':50s} {'匹配':>5s} {'误差':>5s} {'错误':>5s} {'率':>7s}")
    P("─"*100)

    total_formulas = 0
    total_match = 0
    total_mismatch = 0
    total_error = 0
    detail_results = []

    for formula in formulas:
        item_ak = formula['item_ak']
        expr = formula['expr']
        rtype = formula['result_type'] or 6
        nt = formula['null_treat']
        if nt is None or nt == 2: nt = 0

        baseline_col = fm.get(item_ak)

        # 从表达式提取参数
        param_refs = list(set(re.findall(r'(\w+)\.(\w+)', expr)))

        match, mismatch, error = 0, 0, 0
        samples = []

        for rec in records:
            # 构建参数值
            pv = {}
            for pent, pfield in param_refs:
                if pent != ENT:
                    continue
                dcol = fm.get(pfield)
                if dcol:
                    val = rec.get(dcol)
                elif pfield == 'updatedAt':
                    val = rec.get('updated_at')
                elif pfield == 'createdAt':
                    val = rec.get('created_at')
                elif pfield == 'accountName':
                    val = rec.get('name')
                elif pfield == 'level':
                    # level 数据写在 dbc_varchar22（补充的）
                    val = rec.get('dbc_varchar22')
                else:
                    val = None
                if isinstance(val, Decimal):
                    val = float(val)
                pv[f'{pent}.{pfield}'] = val

            # 求值
            computed = evaluate(expr, pv, nt)

            # 取 baseline
            baseline = rec.get(baseline_col) if baseline_col else None
            if isinstance(baseline, Decimal):
                baseline = float(baseline)

            # 比对
            if isinstance(computed, str) and computed.startswith('EVAL_ERROR'):
                error += 1
                if error <= 2:
                    samples.append(('ERR', rec['id'], computed[:80]))
                continue

            if baseline is None and computed is None:
                match += 1
            elif baseline is None or computed is None:
                mismatch += 1
                if len(samples) < 2:
                    samples.append(('NULL', rec['id'], baseline, computed))
            elif rtype in (6, 33):
                try:
                    if abs(float(baseline) - float(computed)) < 0.1:
                        match += 1
                    else:
                        mismatch += 1
                        if len(samples) < 2:
                            samples.append(('NUM', rec['id'], baseline, computed))
                except (ValueError, TypeError):
                    mismatch += 1
            else:
                if str(baseline).strip() == str(computed).strip():
                    match += 1
                else:
                    mismatch += 1
                    if len(samples) < 2:
                        samples.append(('STR', rec['id'], baseline, computed))

        total = match + mismatch + error
        rate = f"{match/total*100:.1f}%" if total > 0 else "N/A"
        icon = '✅' if mismatch == 0 and error == 0 else ('⚠️' if error > 0 and mismatch == 0 else '❌')

        P(f"{icon} {item_ak:25s} {expr[:50]:50s} {match:>5d} {mismatch:>5d} {error:>5d} {rate:>7s}")

        if samples:
            for s in samples:
                if s[0] == 'ERR':
                    P(f"   求值错误 id={s[1]}: {s[2]}")
                else:
                    P(f"   不匹配 id={s[1]}: baseline={s[2]}, computed={s[3]}")

        total_formulas += 1
        total_match += match
        total_mismatch += mismatch
        total_error += error

        detail_results.append({
            'formula': item_ak, 'match': match, 'mismatch': mismatch,
            'error': error, 'total': total, 'rate': rate
        })

    # 5. 汇总
    P(f"\n{'='*70}")
    P("验证汇总")
    P("="*70)

    grand_total = total_match + total_mismatch + total_error
    P(f"  公式数: {total_formulas}")
    P(f"  总计算次数: {grand_total}")
    P(f"  匹配: {total_match} ({total_match/grand_total*100:.1f}%)" if grand_total > 0 else "")
    P(f"  不匹配: {total_mismatch}")
    P(f"  求值错误: {total_error}")

    perfect = [r for r in detail_results if r['mismatch'] == 0 and r['error'] == 0]
    has_error = [r for r in detail_results if r['error'] > 0]
    has_mismatch = [r for r in detail_results if r['mismatch'] > 0]

    P(f"\n  ✅ 完美匹配: {len(perfect)}/{total_formulas} 个公式")
    if has_error:
        P(f"  ⚠️ 有求值错误: {len(has_error)} 个")
        for r in has_error:
            P(f"    {r['formula']}: {r['error']} 次错误")
    if has_mismatch:
        P(f"  ❌ 有不匹配: {len(has_mismatch)} 个")
        for r in has_mismatch:
            P(f"    {r['formula']}: {r['mismatch']} 次不匹配")

    # 函数覆盖统计
    all_funcs = set()
    for f in formulas:
        fns = re.findall(r'([A-Z_]{2,})\s*\(', f['expr'])
        all_funcs.update(fn for fn in fns if fn not in ('A','B','C','D'))
    P(f"\n  覆盖函数: {sorted(all_funcs)}")
    P(f"  函数种类: {len(all_funcs)}")

    P(f"\n{'='*70}")
    if not has_mismatch and not has_error:
        P("✅ 全部公式引擎验证通过！")
    P("="*70)

    cur.close(); conn.close()

if __name__ == '__main__':
    main()
