#!/usr/bin/env python3
"""
省市区全局选项集迁移到 Common 级（p_common_metadata）

从老库 PostgreSQL 读取 globalPickItem + pickOption 数据，
按新命名规则（拼音 api_key）写入新库 MySQL p_common_metadata。

用法：
  python -m sync.sync_global_pick_option          # 全量迁移
  python -m sync.sync_global_pick_option --dry-run # 仅打印不写入
"""
import sys
import time
import re
import pymysql
import psycopg2
import psycopg2.extras

from .config import OLD_DB, NEW_META_DB

# ── 雪花 ID 生成 ──
_seq = int(time.time() * 1000) << 20

def nid():
    global _seq
    _seq += 1
    return _seq

def P(msg):
    print(msg, flush=True)

# ============================================================================
# 拼音映射表
# ============================================================================

# 省份：api_key = 国际惯例拼音
PROVINCE_PINYIN = {
    '北京': 'beijing', '天津': 'tianjin', '河北': 'hebei', '山西': 'shanxi',
    '内蒙古': 'neimenggu', '辽宁': 'liaoning', '吉林': 'jilin', '黑龙江': 'heilongjiang',
    '上海': 'shanghai', '江苏': 'jiangsu', '浙江': 'zhejiang', '安徽': 'anhui',
    '福建': 'fujian', '江西': 'jiangxi', '山东': 'shandong', '河南': 'henan',
    '湖北': 'hubei', '湖南': 'hunan', '广东': 'guangdong', '广西': 'guangxi',
    '海南': 'hainan', '重庆': 'chongqing', '四川': 'sichuan', '贵州': 'guizhou',
    '云南': 'yunnan', '西藏': 'xizang', '陕西': 'shaanxi', '甘肃': 'gansu',
    '青海': 'qinghai', '宁夏': 'ningxia', '新疆': 'xinjiang',
    '香港': 'xianggang', '澳门': 'aomen', '台湾': 'taiwan',
}

# 城市缩写表（用于区县 api_key 前缀）
# 规则：双音节取两个首字母，三音节取三个首字母
# 冲突时手动调整（如 承德=cd → 成都=chd）
CITY_ABBR = {}  # 运行时从城市拼音自动生成，冲突手动覆盖

CITY_ABBR_OVERRIDE = {
    # 已知冲突的手动覆盖
    '成都': 'chd',    # cd 被承德占用
    '苏州': 'su',     # sz 被深圳占用
    '长沙': 'cs',
    '长春': 'cc',
}


def to_pinyin(chinese_name):
    """
    中文转拼音（需要 pypinyin 库）。
    pip install pypinyin
    """
    try:
        from pypinyin import pinyin, Style
        result = pinyin(chinese_name, style=Style.NORMAL)
        return ''.join([item[0] for item in result])
    except ImportError:
        P("⚠️  需要安装 pypinyin: pip install pypinyin")
        sys.exit(1)


def make_city_abbr(city_label):
    """生成城市缩写：双音节取首字母，三音节取三个首字母"""
    if city_label in CITY_ABBR_OVERRIDE:
        return CITY_ABBR_OVERRIDE[city_label]
    # 去掉"市"后缀
    name = city_label.rstrip('市')
    py = to_pinyin(name)
    # 按音节数决定缩写长度
    from pypinyin import pinyin, Style
    syllables = pinyin(name, style=Style.NORMAL)
    if len(syllables) <= 2:
        return ''.join(s[0][0] for s in syllables)
    else:
        return ''.join(s[0][0] for s in syllables[:3])


def make_district_apikey(city_label, district_label):
    """生成区县 api_key：城市缩写 + 区县拼音（camelCase）"""
    abbr = CITY_ABBR.get(city_label)
    if not abbr:
        abbr = make_city_abbr(city_label)
        CITY_ABBR[city_label] = abbr
    # 去掉"区/县/市"后缀
    name = district_label
    for suffix in ['区', '县', '市', '旗', '盟']:
        if name.endswith(suffix) and len(name) > 1:
            name = name[:-1]
            break
    py = to_pinyin(name)
    # camelCase: 缩写小写 + 拼音首字母大写
    return abbr + py[0].upper() + py[1:]


# ============================================================================
# 数据库连接
# ============================================================================

def get_old_pg():
    conn = psycopg2.connect(**OLD_DB)
    conn.autocommit = False
    return conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)


def get_new_mysql():
    conn = pymysql.connect(**NEW_META_DB)
    conn.autocommit = False
    return conn, conn.cursor()


# ============================================================================
# 老库常量
# ============================================================================

# 老库 globalPickItem IDs（tenant_id=-101 的系统级数据）
GLOBAL_PICK_ITEM_METAMODEL_ID = -10000
GLOBAL_PICK_OPTION_METAMODEL_ID = -10010
SYSTEM_TENANT_ID = -101

# 已知的省市区 globalPickItem IDs
PROVINCE_ITEM_ID = 153305
CITY_ITEM_ID = 153306
DISTRICT_ITEM_ID = 153307


# ============================================================================
# 主流程
# ============================================================================

def main():
    dry_run = '--dry-run' in sys.argv
    if dry_run:
        P("🔍 DRY RUN 模式：仅打印不写入")

    P("=" * 60)
    P("省市区全局选项集迁移到 Common 级")
    P("=" * 60)

    pg_conn, pg_cur = get_old_pg()
    my_conn, my_cur = get_new_mysql() if not dry_run else (None, None)
    now = int(time.time() * 1000)

    try:
        # ── Step 0: 先更新 p_meta_model enable_common ──
        P("\n── Step 0: 更新 p_meta_model ──")
        if not dry_run:
            my_cur.execute(
                "UPDATE p_meta_model SET enable_common = 1 WHERE api_key = 'globalPickOption'"
            )
            P(f"  globalPickOption enable_common → 1 (affected={my_cur.rowcount})")

        # ── Step 1: 注册 p_meta_item 字段定义 ──
        P("\n── Step 1: 注册 p_meta_item 字段定义 ──")
        meta_items = [
            ('optionOrder', 'globalPickOption', '排序序号', 'dbc_int1', 2),
            ('defaultFlg',  'globalPickOption', '是否默认', 'dbc_smallint1', 9),
            ('enableFlg',   'globalPickOption', '是否启用', 'dbc_smallint2', 9),
        ]
        for api_key, mm, label, db_col, itype in meta_items:
            if not dry_run:
                my_cur.execute("""
                    INSERT INTO p_meta_item
                        (id, api_key, metamodel_api_key, label, db_column, item_type,
                         namespace, custom_flg, delete_flg, created_at, created_by, updated_at, updated_by)
                    VALUES (%s, %s, %s, %s, %s, %s, 'system', 0, 0, %s, 0, %s, 0)
                    ON DUPLICATE KEY UPDATE db_column = VALUES(db_column)
                """, (nid(), api_key, mm, label, db_col, itype, now, now))
            P(f"  {api_key} → {db_col}")

        # ── Step 2: 插入选项集定义 ──
        P("\n── Step 2: 选项集定义 ──")
        for label, api_key in [('省份', 'province'), ('城市', 'city'), ('区县', 'district')]:
            insert_common(my_cur, dry_run, now,
                          api_key=api_key, entity_api_key=None,
                          label=label, label_key=f'globalPick.{api_key}.label',
                          namespace='system')
            P(f"  {api_key} ({label})")

        # ── Step 3: 从老库读取省份选项值 ──
        P("\n── Step 3: 省份选项值 ──")
        pg_cur.execute("""
            SELECT option_code, api_key, option_label, option_label_key, option_order,
                   default_flg, enable_flg, created_at, created_by, updated_at, updated_by
            FROM p_custom_pickoption
            WHERE item_id = %s AND tenant_id = %s AND delete_flg = 0
            ORDER BY option_order
        """, (PROVINCE_ITEM_ID, SYSTEM_TENANT_ID))
        provinces = pg_cur.fetchall()
        P(f"  老库读取 {len(provinces)} 条省份")

        # 构建 optionCode → 新 api_key 映射
        province_code_map = {}  # old_option_code → new_api_key
        province_label_map = {}  # label → new_api_key
        for row in provinces:
            label = row['option_label'].strip()
            # 去掉"省/市/自治区"等后缀匹配拼音表
            match_label = label
            for suffix in ['省', '市', '自治区', '壮族自治区', '回族自治区', '维吾尔自治区', '特别行政区']:
                if match_label.endswith(suffix):
                    match_label = match_label[:-len(suffix)]
                    break
            new_ak = PROVINCE_PINYIN.get(match_label)
            if not new_ak:
                new_ak = to_pinyin(match_label)
                P(f"  ⚠️  省份 '{label}' 未在拼音表中，自动生成: {new_ak}")
            province_code_map[row['option_code']] = new_ak
            province_label_map[label] = new_ak

            insert_common(my_cur, dry_run, now,
                          api_key=new_ak, entity_api_key='province',
                          label=label, label_key=row.get('option_label_key'),
                          namespace='system',
                          dbc_int1=row.get('option_order'),
                          dbc_smallint1=row.get('default_flg', 0),
                          dbc_smallint2=row.get('enable_flg', 1))
        P(f"  写入 {len(provinces)} 条省份")

        # ── Step 4: 从老库读取城市选项值 ──
        P("\n── Step 4: 城市选项值 ──")
        pg_cur.execute("""
            SELECT option_code, api_key, option_label, option_label_key, option_order,
                   default_flg, enable_flg
            FROM p_custom_pickoption
            WHERE item_id = %s AND tenant_id = %s AND delete_flg = 0
            ORDER BY option_order
        """, (CITY_ITEM_ID, SYSTEM_TENANT_ID))
        cities = pg_cur.fetchall()
        P(f"  老库读取 {len(cities)} 条城市")

        city_code_map = {}  # old_option_code → new_api_key
        city_label_map = {}  # label → new_api_key
        used_city_keys = set()
        for row in cities:
            label = row['option_label'].strip()
            name = label.rstrip('市')
            new_ak = to_pinyin(name)
            # 去重（理论上地级市不重名，但防御性处理）
            if new_ak in used_city_keys:
                new_ak = new_ak + str(row['option_code'])
                P(f"  ⚠️  城市拼音冲突: {label} → {new_ak}")
            used_city_keys.add(new_ak)
            city_code_map[row['option_code']] = new_ak
            city_label_map[label] = new_ak

            insert_common(my_cur, dry_run, now,
                          api_key=new_ak, entity_api_key='city',
                          label=label, label_key=row.get('option_label_key'),
                          namespace='system',
                          dbc_int1=row.get('option_order'),
                          dbc_smallint1=row.get('default_flg', 0),
                          dbc_smallint2=row.get('enable_flg', 1))
        P(f"  写入 {len(cities)} 条城市")

        # ── Step 5: 从老库读取区县选项值 ──
        P("\n── Step 5: 区县选项值 ──")
        pg_cur.execute("""
            SELECT option_code, api_key, option_label, option_label_key, option_order,
                   default_flg, enable_flg
            FROM p_custom_pickoption
            WHERE item_id = %s AND tenant_id = %s AND delete_flg = 0
            ORDER BY option_order
        """, (DISTRICT_ITEM_ID, SYSTEM_TENANT_ID))
        districts = pg_cur.fetchall()
        P(f"  老库读取 {len(districts)} 条区县")

        # 需要省→市→区的映射来确定每个区县属于哪个城市
        # 从依赖明细中获取
        pg_cur.execute("""
            SELECT d.control_option_code, d.dependent_option_codes
            FROM p_custom_item_dependency_detail d
            JOIN p_custom_item_dependency dep ON d.item_dependency_id = dep.id
            WHERE dep.entity_id = %s AND dep.control_item_id = %s
              AND dep.tenant_id = %s AND d.tenant_id = %s
        """, (SYSTEM_TENANT_ID, CITY_ITEM_ID, SYSTEM_TENANT_ID, SYSTEM_TENANT_ID))
        city_to_district_deps = pg_cur.fetchall()

        # 构建 district_code → city_code 反向映射
        district_to_city = {}
        for dep in city_to_district_deps:
            city_code = dep['control_option_code']
            codes_str = dep.get('dependent_option_codes') or ''
            for dc in codes_str.split(','):
                dc = dc.strip()
                if dc:
                    try:
                        district_to_city[int(dc)] = city_code
                    except ValueError:
                        pass

        # 还需要 city_code → city_label 映射
        city_code_to_label = {}
        for row in cities:
            city_code_to_label[row['option_code']] = row['option_label'].strip()

        district_code_map = {}
        used_district_keys = set()
        no_city_count = 0
        for row in districts:
            label = row['option_label'].strip()
            d_code = row['option_code']
            city_code = district_to_city.get(d_code)
            city_label = city_code_to_label.get(city_code, '未知') if city_code else '未知'

            if city_label == '未知':
                no_city_count += 1
                # fallback: 用 option_code 做后缀
                new_ak = to_pinyin(label.rstrip('区县市旗')) + str(d_code)
            else:
                new_ak = make_district_apikey(city_label, label)

            # 去重
            if new_ak in used_district_keys:
                new_ak = new_ak + str(d_code)
            used_district_keys.add(new_ak)
            district_code_map[d_code] = new_ak

            insert_common(my_cur, dry_run, now,
                          api_key=new_ak, entity_api_key='district',
                          label=label, label_key=row.get('option_label_key'),
                          namespace='system',
                          dbc_int1=row.get('option_order'),
                          dbc_smallint1=row.get('default_flg', 0),
                          dbc_smallint2=row.get('enable_flg', 1))
        P(f"  写入 {len(districts)} 条区县 (无城市归属: {no_city_count})")

        # ── Step 6: 省→市 依赖 ──
        P("\n── Step 6: 级联依赖定义 ──")
        insert_common(my_cur, dry_run, now,
                      api_key='provinceToCity', entity_api_key='province',
                      label='省份→城市', label_key='globalPick.dep.provinceToCity',
                      namespace='system', metamodel='globalPickDependency',
                      dbc_varchar1='province', dbc_varchar2='city')
        insert_common(my_cur, dry_run, now,
                      api_key='cityToDistrict', entity_api_key='province',
                      label='城市→区县', label_key='globalPick.dep.cityToDistrict',
                      namespace='system', metamodel='globalPickDependency',
                      dbc_varchar1='city', dbc_varchar2='district')
        P("  provinceToCity, cityToDistrict")

        # ── Step 7: 省→市 依赖明细 ──
        P("\n── Step 7: 省→市 依赖明细 ──")
        pg_cur.execute("""
            SELECT d.control_option_code, d.dependent_option_codes
            FROM p_custom_item_dependency_detail d
            JOIN p_custom_item_dependency dep ON d.item_dependency_id = dep.id
            WHERE dep.entity_id = %s AND dep.control_item_id = %s
              AND dep.tenant_id = %s AND d.tenant_id = %s
        """, (SYSTEM_TENANT_ID, PROVINCE_ITEM_ID, SYSTEM_TENANT_ID, SYSTEM_TENANT_ID))
        prov_city_deps = pg_cur.fetchall()
        P(f"  老库读取 {len(prov_city_deps)} 条省→市映射")

        for dep in prov_city_deps:
            prov_code = dep['control_option_code']
            prov_ak = province_code_map.get(prov_code)
            if not prov_ak:
                continue
            codes_str = dep.get('dependent_option_codes') or ''
            new_codes = []
            for c in codes_str.split(','):
                c = c.strip()
                if c:
                    try:
                        new_codes.append(city_code_map.get(int(c), c))
                    except ValueError:
                        new_codes.append(c)
            insert_common(my_cur, dry_run, now,
                          api_key=f'dep{prov_ak[0].upper()}{prov_ak[1:]}City',
                          entity_api_key='province',
                          label=f'{prov_ak}→城市', label_key=None,
                          namespace='system', metamodel='globalPickDependencyDetail',
                          dbc_varchar1='provinceToCity',
                          dbc_int1=prov_code,
                          dbc_varchar2=','.join(new_codes))
        P(f"  写入 {len(prov_city_deps)} 条")

        # ── Step 8: 市→区 依赖明细 ──
        P("\n── Step 8: 市→区 依赖明细 ──")
        P(f"  老库读取 {len(city_to_district_deps)} 条市→区映射")

        for dep in city_to_district_deps:
            city_code = dep['control_option_code']
            city_ak = city_code_map.get(city_code)
            if not city_ak:
                continue
            codes_str = dep.get('dependent_option_codes') or ''
            new_codes = []
            for c in codes_str.split(','):
                c = c.strip()
                if c:
                    try:
                        new_codes.append(district_code_map.get(int(c), c))
                    except ValueError:
                        new_codes.append(c)
            insert_common(my_cur, dry_run, now,
                          api_key=f'dep{city_ak[0].upper()}{city_ak[1:]}District',
                          entity_api_key='province',
                          label=f'{city_ak}→区县', label_key=None,
                          namespace='system', metamodel='globalPickDependencyDetail',
                          dbc_varchar1='cityToDistrict',
                          dbc_int1=city_code,
                          dbc_varchar2=','.join(new_codes))
        P(f"  写入 {len(city_to_district_deps)} 条")

        # ── 提交 ──
        if not dry_run:
            my_conn.commit()

        P(f"\n{'=' * 60}")
        P(f"✅ 迁移完成:")
        P(f"   省份: {len(provinces)} 条")
        P(f"   城市: {len(cities)} 条")
        P(f"   区县: {len(districts)} 条")
        P(f"   省→市依赖: {len(prov_city_deps)} 条")
        P(f"   市→区依赖: {len(city_to_district_deps)} 条")
        P(f"   城市缩写表: {len(CITY_ABBR)} 个")
        P("=" * 60)

        # 打印城市缩写表供检查
        if CITY_ABBR:
            P("\n── 城市缩写对照表 ──")
            for city, abbr in sorted(CITY_ABBR.items()):
                P(f"  {city:10s} → {abbr}")

    except Exception as e:
        if my_conn:
            my_conn.rollback()
        P(f"\n❌ 失败: {e}")
        import traceback
        traceback.print_exc()
    finally:
        pg_cur.close()
        pg_conn.close()
        if my_cur:
            my_cur.close()
        if my_conn:
            my_conn.close()


def insert_common(cur, dry_run, now, *,
                  api_key, entity_api_key, label, label_key,
                  namespace='system', metamodel='globalPickOption',
                  dbc_int1=None, dbc_smallint1=None, dbc_smallint2=None,
                  dbc_varchar1=None, dbc_varchar2=None):
    """插入一条 p_common_metadata 记录"""
    if dry_run:
        return
    cur.execute("""
        INSERT INTO p_common_metadata
            (id, metamodel_api_key, api_key, entity_api_key, label, label_key,
             namespace, custom_flg, delete_flg,
             dbc_int1, dbc_smallint1, dbc_smallint2,
             dbc_varchar1, dbc_varchar2,
             created_at, created_by, updated_at, updated_by)
        VALUES (%s, %s, %s, %s, %s, %s, %s, 0, 0, %s, %s, %s, %s, %s, %s, 0, %s, 0)
        ON DUPLICATE KEY UPDATE label = VALUES(label)
    """, (nid(), metamodel, api_key, entity_api_key, label, label_key,
          namespace, dbc_int1, dbc_smallint1, dbc_smallint2,
          dbc_varchar1, dbc_varchar2, now, now))


if __name__ == '__main__':
    main()
