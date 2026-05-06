#!/usr/bin/env python3
"""
Phase 3 核心: 计算公式验证
修复版：正确处理 null 参数、改进错误日志
"""
import re
import sys
import logging
from decimal import Decimal
from .config import CORE_ENTITIES, TEST_TENANT_ID
from .db import get_pg_dict

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
log = logging.getLogger(__name__)


def load_field_map(cur, entity_api_key):
    """apiKey → (dbColumn, itemType)"""
    cur.execute("""
        SELECT api_key, dbc_varchar3, dbc_int1
        FROM p_common_metadata
        WHERE metamodel_api_key='item' AND entity_api_key=%s
          AND delete_flg=0 AND api_key IS NOT NULL
    """, (entity_api_key,))
    return {r['api_key']: (r['dbc_varchar3'], r['dbc_int1']) for r in cur.fetchall()}


def load_formulas(cur, entity_api_key):
    cur.execute("""
        SELECT dbc_varchar1 AS item_api_key,
               dbc_textarea1 AS expression,
               dbc_int1 AS null_treatment,
               dbc_int2 AS result_type
        FROM p_common_metadata
        WHERE metamodel_api_key='formulaCompute' AND entity_api_key=%s
          AND delete_flg=0 AND dbc_varchar1 IS NOT NULL
    """, (entity_api_key,))
    return cur.fetchall()


def load_aggregations(cur, entity_api_key):
    cur.execute("""
        SELECT dbc_varchar1 AS child_entity,
               dbc_varchar2 AS rollup_item,
               dbc_varchar3 AS link_item,
               dbc_varchar4 AS agg_target_item,
               dbc_int1 AS agg_type
        FROM p_common_metadata
        WHERE metamodel_api_key='aggregationCompute' AND entity_api_key=%s
          AND delete_flg=0
    """, (entity_api_key,))
    return cur.fetchall()


def extract_params(expression, entity_api_key):
    pattern = rf'{re.escape(entity_api_key)}\.(\w+)'
    return list(set(re.findall(pattern, expression)))


def evaluate_formula(expression, param_values, null_treatment=2):
    """
    公式求值 — 改进版
    null_treatment: 0或2=null视为0参与计算, 1=null导致结果null
    """
    expr = expression

    # 单等号→双等号（字符串比较）
    expr = re.sub(r"(?<![><!= ])='([^']*)'", r'=="\1"', expr)
    expr = re.sub(r'(?<![><!= ])="([^"]*)"', r'=="\1"', expr)

    # 参数替换
    var_dict = {}
    has_null = False
    for i, (param, value) in enumerate(param_values.items()):
        var_name = f'_p{i}'
        if value is None:
            has_null = True
            if null_treatment == 1:
                # null 导致结果 null
                return None
            else:
                # null 视为 0（数值）或空字符串
                value = 0
        if isinstance(value, Decimal):
            value = float(value)
        var_dict[var_name] = value
        expr = expr.replace(param, var_name)

    # 函数映射
    expr = expr.replace('IF(', '_IF(')
    expr = expr.replace('OR(', '_OR(')
    expr = expr.replace('AND(', '_AND(')
    expr = expr.replace('NOT(', '_NOT(')
    expr = expr.replace('ISNULL(', '_ISNULL(')
    expr = expr.replace('OPTIONAPINAME(', '_OPTAPI(')
    expr = expr.replace('NUMBERSTRING(', '_NUMSTR(')

    def _IF(cond, t, f):
        return t if cond else f
    def _OR(*a):
        return any(bool(x) for x in a)
    def _AND(*a):
        return all(bool(x) for x in a)
    def _NOT(x):
        return not x
    def _ISNULL(x):
        return x is None or x == 0
    def _OPTAPI(x):
        return str(x) if x else ''
    def _NUMSTR(x):
        return str(x) if x is not None else ''

    ctx = {
        '__builtins__': {}, 'None': None, 'True': True, 'False': False,
        '_IF': _IF, '_OR': _OR, '_AND': _AND, '_NOT': _NOT,
        '_ISNULL': _ISNULL, '_OPTAPI': _OPTAPI, '_NUMSTR': _NUMSTR,
    }
    ctx.update(var_dict)

    try:
        return eval(expr, ctx)
    except Exception as e:
        return f"EVAL_ERROR: {e} | expr={expr[:80]}"


def compare_values(old_val, new_val, result_type):
    if old_val is None and new_val is None:
        return 'EXACT'
    if old_val is None or new_val is None:
        return 'NULL_DIFF'

    if result_type in (1, 3):
        return 'EXACT' if str(old_val).strip() == str(new_val).strip() else 'MISMATCH'

    if result_type == 31:
        ob = 1 if old_val in (1, True, '1', 'true') else 0
        nb = 1 if new_val in (1, True, '1', 'true') else 0
        return 'EXACT' if ob == nb else 'MISMATCH'

    if result_type in (6, 33):
        try:
            diff = abs(float(old_val) - float(new_val))
            return 'EXACT' if diff == 0 else ('PRECISION' if diff < 0.01 else 'MISMATCH')
        except (ValueError, TypeError):
            return 'TYPE_ERR'

    if result_type == 21:
        try:
            return 'EXACT' if int(old_val) == int(new_val) else 'MISMATCH'
        except (ValueError, TypeError):
            return 'TYPE_ERR'

    return 'EXACT' if str(old_val) == str(new_val) else 'MISMATCH'


class FormulaVerifier:
    def __init__(self, tenant_id, entity_api_key, sample_size=500):
        self.tenant_id = tenant_id
        self.entity = entity_api_key
        self.sample_size = sample_size

    def run(self):
        log.info(f"\n{'='*60}")
        log.info(f"公式验证: {self.entity} (tenant={self.tenant_id})")
        log.info('='*60)

        conn, cur = get_pg_dict()
        try:
            field_map = load_field_map(cur, self.entity)
            formulas = load_formulas(cur, self.entity)
            aggregations = load_aggregations(cur, self.entity)

            log.info(f"字段: {len(field_map)}, 公式: {len(formulas)}, 汇总: {len(aggregations)}")

            if not formulas and not aggregations:
                log.info("无公式/汇总定义，跳过")
                return {'status': 'SKIP'}

            # 构建 SELECT 列
            all_dbcols = set()
            for ak, (dc, it) in field_map.items():
                if dc:
                    all_dbcols.add(dc)
            col_list = ', '.join(['id', 'name'] + sorted(all_dbcols))

            cur.execute(f"""
                SELECT {col_list} FROM p_tenant_data
                WHERE entity_api_key = %s AND tenant_id = %s AND delete_flg = 0
                ORDER BY random() LIMIT %s
            """, (self.entity, self.tenant_id, self.sample_size))
            records = cur.fetchall()  # RealDictCursor 直接返回 dict
            log.info(f"抽样 {len(records)} 条业务数据")

            if not records:
                log.warning("无业务数据，跳过")
                return {'status': 'SKIP', 'reason': 'no data'}

            # 逐公式验证
            results = {}
            for formula in formulas:
                item_ak = formula['item_api_key']
                expression = formula['expression']
                result_type = formula['result_type'] or 6
                null_treat = formula['null_treatment']
                # nullTreatment=2 按 0 处理（null 视为 0）
                if null_treat is None or null_treat == 2:
                    null_treat = 0

                r = self._verify_formula(
                    records, field_map, item_ak, expression, result_type, null_treat)
                results[item_ak] = r
                self._log_formula_result(item_ak, expression, r)

            # 汇总验证
            agg_results = {}
            for agg in aggregations:
                r = self._verify_aggregation(cur, field_map, agg)
                key = agg['rollup_item'] or 'unknown'
                agg_results[key] = r

            self._print_report(results, agg_results)
            return {'formulas': results, 'aggregations': agg_results}
        finally:
            cur.close()
            conn.close()

    def _verify_formula(self, records, field_map, item_ak, expression, result_type, null_treat):
        baseline_col = field_map.get(item_ak, (None, None))[0]
        param_fields = extract_params(expression, self.entity)

        # 检查缺失的参数字段
        missing_params = [pf for pf in param_fields if pf not in field_map]
        if missing_params:
            log.warning(f"    公式 {item_ak} 依赖的字段缺少元数据: {missing_params}")

        exact, precision, null_ok, mismatch, error = 0, 0, 0, 0, 0
        mismatch_samples = []

        for record in records:
            baseline = record.get(baseline_col) if baseline_col else None

            # 构建参数值
            param_values = {}
            for pf in param_fields:
                pf_col = field_map.get(pf, (None, None))[0]
                val = record.get(pf_col) if pf_col else None
                if isinstance(val, Decimal):
                    val = float(val)
                param_values[f'{self.entity}.{pf}'] = val

            # 求值
            computed = evaluate_formula(expression, param_values, null_treat)
            if isinstance(computed, str) and computed.startswith('EVAL_ERROR'):
                error += 1
                if error <= 3:
                    log.warning(f"    求值错误 id={record.get('id')}: {computed[:150]}")
                continue

            # 比对
            cmp = compare_values(baseline, computed, result_type)
            if cmp == 'EXACT':
                exact += 1
            elif cmp == 'PRECISION':
                precision += 1
            elif cmp == 'NULL_DIFF':
                if baseline is None and computed is None:
                    null_ok += 1
                else:
                    mismatch += 1
                    if len(mismatch_samples) < 3:
                        mismatch_samples.append({
                            'id': record.get('id'), 'baseline': baseline,
                            'computed': computed, 'cmp': cmp
                        })
            else:
                mismatch += 1
                if len(mismatch_samples) < 3:
                    mismatch_samples.append({
                        'id': record.get('id'), 'baseline': baseline,
                        'computed': computed, 'cmp': cmp,
                        'params': {k: v for k, v in param_values.items() if v is not None}
                    })

        total = exact + precision + null_ok + mismatch + error
        return {
            'total': total, 'exact': exact, 'precision': precision,
            'null_ok': null_ok, 'mismatch': mismatch, 'error': error,
            'match_rate': f"{(exact+precision+null_ok)/max(total,1)*100:.1f}%",
            'samples': mismatch_samples
        }

    def _verify_aggregation(self, cur, field_map, agg):
        child_entity = agg['child_entity']
        rollup_item = agg['rollup_item']
        link_item = agg['link_item']
        agg_type = agg['agg_type'] or 0

        rollup_col = field_map.get(rollup_item, (None, None))[0]
        if not rollup_col:
            return {'status': 'SKIP', 'reason': f'rollup field {rollup_item} has no dbColumn'}

        # 加载子实体字段映射
        conn2, cur2 = get_pg_dict()
        child_field_map = load_field_map(cur2, child_entity)
        cur2.close()
        conn2.close()

        link_col = child_field_map.get(link_item, (None, None))[0]
        if not link_col:
            return {'status': 'SKIP', 'reason': f'link field {link_item} has no dbColumn in {child_entity}'}

        cur.execute(f"""
            SELECT id, {rollup_col} AS baseline FROM p_tenant_data
            WHERE entity_api_key = %s AND tenant_id = %s AND delete_flg = 0
            ORDER BY random() LIMIT 100
        """, (self.entity, self.tenant_id))
        parents = cur.fetchall()
        if not parents:
            return {'status': 'SKIP', 'reason': 'no parent records'}

        parent_ids = [p['id'] for p in parents]
        baseline_map = {p['id']: p['baseline'] for p in parents}

        agg_func = 'COUNT(*)' if agg_type == 0 else f'SUM(COALESCE({link_col},0))'
        try:
            cur.execute(f"""
                SELECT {link_col} AS parent_id, {agg_func} AS agg_val
                FROM p_tenant_data
                WHERE entity_api_key = %s AND tenant_id = %s
                  AND {link_col} = ANY(%s) AND delete_flg = 0
                GROUP BY {link_col}
            """, (child_entity, self.tenant_id, parent_ids))
            agg_map = {r['parent_id']: r['agg_val'] for r in cur.fetchall()}
        except Exception as e:
            return {'status': 'ERROR', 'reason': str(e)}

        match, mismatch = 0, 0
        for pid in parent_ids:
            baseline = baseline_map.get(pid)
            computed = agg_map.get(pid, 0)
            cmp = compare_values(baseline, computed, 6)
            if cmp in ('EXACT', 'PRECISION'):
                match += 1
            else:
                mismatch += 1

        return {
            'total': len(parent_ids), 'match': match, 'mismatch': mismatch,
            'match_rate': f"{match/max(len(parent_ids),1)*100:.1f}%"
        }

    def _log_formula_result(self, item_ak, expression, r):
        status = '✅' if r['mismatch'] == 0 and r['error'] == 0 else '⚠️'
        log.info(f"  {status} {item_ak}: {r['match_rate']} "
                 f"(exact={r['exact']}, prec={r['precision']}, "
                 f"null={r['null_ok']}, mis={r['mismatch']}, err={r['error']})")
        for s in r['samples'][:2]:
            log.info(f"    不匹配: id={s['id']}, baseline={s['baseline']}, "
                     f"computed={s['computed']}")

    def _print_report(self, formula_results, agg_results):
        log.info(f"\n{'─'*40}")
        log.info(f"验证报告: {self.entity}")
        log.info('─'*40)
        if formula_results:
            log.info("FORMULA:")
            for ak, r in formula_results.items():
                log.info(f"  {ak:30s}: {r['match_rate']:>6s} "
                         f"({r['exact']}+{r['precision']}+{r['null_ok']}"
                         f"/{r['total']}, err={r['error']})")
        if agg_results:
            log.info("ROLLUP:")
            for ak, r in agg_results.items():
                if 'match_rate' in r:
                    log.info(f"  {ak:30s}: {r['match_rate']:>6s} ({r['match']}/{r['total']})")
                else:
                    log.info(f"  {ak:30s}: {r.get('status')} - {r.get('reason','')}")
