#!/usr/bin/env python3
"""
p_user → paas_entity_data (p_tenant_data) 迁移脚本

迁移路径:
  1. 通过 Java API /auth/login 获取 token
  2. 通过 Java API /auth/users 读取 p_user 数据
  3. 通过 Java API /metadata/items?entityApiKey=user 读取字段映射
  4. 转换数据格式: p_user 列 → p_tenant_data dbc_xxx 列
  5. 通过 Java API /entity/data/user (POST) 写入 p_tenant_data

用法:
  python3 -m sync.migrate_user [--dry-run] [--tenant-id 292193]
"""
import json
import logging
import sys
import urllib.request
import urllib.error

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
log = logging.getLogger(__name__)

BASE_URL = 'http://localhost:18010'
DEFAULT_TENANT = '292193'
LOGIN_PHONE = '13800000001'
LOGIN_PASSWORD = '123456'

# p_user 列 → user entity item apiKey 的映射
# 左边是 /auth/users 返回的 camelCase 字段名
# 右边是 user entity 的 item apiKey
#
# 重要同步规则：
#   name ↔ realName：name 是固定列（列表展示用），realName 是元数据字段（编辑弹框用）。
#                    两者表达同一含义（用户姓名），迁移时 name → realName，
#                    前端编辑保存时 realName → name 自动同步。
#   phone ↔ userName：phone 是 p_user 登录凭证，userName 是元数据字段（编辑弹框用）。
#                     迁移时 phone → userName，前端编辑回显时 userName ← phone。
USER_FIELD_MAP = {
    'name':           'realName',       # 姓名 → realName (元数据字段，与固定列 name 双向同步)
    'phone':          'userName',       # 手机号 → userName (元数据字段，与 p_user.phone 双向同步)
    'email':          'email',          # 邮箱
    'status':         'status',         # 状态 1=启用 2=停用
    'userType':       'userType',       # 用户类型 0=普通 1=管理员
    'departId':       'departId',       # 所属部门
    'managerId':      'managerId',      # 上级主管
    'lockAuthStatus': 'lockAuthStatus', # 锁定状态
}


class UserMigrator:
    def __init__(self, tenant_id=DEFAULT_TENANT, dry_run=False):
        self.tenant_id = tenant_id
        self.dry_run = dry_run
        self.token = None
        self.item_map = {}  # apiKey → {label, dbColumn, itemType}
        self.stats = {'read': 0, 'written': 0, 'skipped': 0, 'errors': 0}

    def run(self):
        log.info('=' * 60)
        log.info('p_user → p_tenant_data 迁移')
        log.info(f'租户: {self.tenant_id}, dry_run: {self.dry_run}')
        log.info('=' * 60)

        # Step 1: Login
        self._login()

        # Step 2: Load user entity item definitions
        self._load_item_map()

        # Step 3: Read all users from p_user
        users = self._read_users()

        # Step 4: Transform and write
        self._migrate_users(users)

        # Step 5: Report
        self._report()

    def _login(self):
        log.info('\n[1/5] 登录获取 token...')
        body = json.dumps({
            'phone': LOGIN_PHONE,
            'password': LOGIN_PASSWORD,
            'tenant_id': int(self.tenant_id),
        }).encode()
        resp = self._http('POST', '/auth/login', body)
        self.token = resp.get('accessToken')
        if not self.token:
            log.error(f'登录失败: {resp}')
            sys.exit(1)
        log.info(f'  token: {self.token[:20]}...')

    def _load_item_map(self):
        log.info('\n[2/5] 加载 user 实体字段定义...')
        items = self._http('GET', '/metadata/items?entityApiKey=user')
        if not isinstance(items, list):
            log.error(f'加载字段失败: {items}')
            sys.exit(1)
        for item in items:
            ak = item.get('api_key') or item.get('apiKey')
            if not ak:
                continue
            self.item_map[ak] = {
                'label': item.get('label', ak),
                'dbColumn': item.get('db_column') or item.get('dbColumn'),
                'itemType': item.get('item_type') or item.get('itemType'),
                'customFlg': item.get('custom_flg') or item.get('customFlg') or 0,
            }
        log.info(f'  {len(self.item_map)} 个字段定义')
        sys_count = sum(1 for v in self.item_map.values() if v['customFlg'] != 1)
        cust_count = sum(1 for v in self.item_map.values() if v['customFlg'] == 1)
        log.info(f'  系统: {sys_count}, 自定义: {cust_count}')

    def _read_users(self):
        log.info('\n[3/5] 读取 p_user 数据...')
        resp = self._http('GET', '/auth/users')
        if isinstance(resp, dict) and 'data' in resp:
            users = resp['data']
        elif isinstance(resp, list):
            users = resp
        else:
            log.error(f'读取用户失败: {str(resp)[:200]}')
            return []
        self.stats['read'] = len(users)
        log.info(f'  读取 {len(users)} 条用户记录')
        if users:
            log.info(f'  示例字段: {list(users[0].keys())}')
        return users

    def _migrate_users(self, users):
        log.info(f'\n[4/5] 转换并写入 p_tenant_data... {"(DRY RUN)" if self.dry_run else ""}')
        for i, user in enumerate(users):
            try:
                new_row = self._transform_user(user)
                if self.dry_run:
                    if i < 3:  # 只打印前 3 条
                        log.info(f'  [DRY] {json.dumps(new_row, ensure_ascii=False)[:200]}')
                    self.stats['written'] += 1
                else:
                    self._write_user(new_row)
                    self.stats['written'] += 1
            except Exception as e:
                log.error(f'  转换失败 id={user.get("id")}: {e}')
                self.stats['errors'] += 1

            if (i + 1) % 100 == 0:
                log.info(f'  进度: {i + 1}/{len(users)}')

    def _transform_user(self, user):
        """
        将 p_user 行转换为 p_tenant_data 格式。

        关键同步逻辑：
          - p_user.name → p_tenant_data.name（固定列，直接写入）
          - p_user.name → realName（元数据字段 dbc_varchar2，通过 USER_FIELD_MAP 映射）
          - p_user.phone → userName（元数据字段 dbc_varchar1，通过 USER_FIELD_MAP 映射）
        这样前端列表读 name 固定列，编辑弹框读 realName/userName 元数据字段，两边数据一致。
        """
        # 读取 camelCase 或 snake_case 字段
        def g(key):
            return user.get(key) or user.get(self._to_snake(key))

        new_row = {
            'entityApiKey': 'user',
            'name': g('name') or g('realName') or '',
        }

        # 映射业务字段
        for old_field, new_api_key in USER_FIELD_MAP.items():
            val = g(old_field)
            if val is not None and val != '':
                new_row[new_api_key] = val

        # 保留原始 ID（如果写入支持）
        old_id = g('id')
        if old_id:
            new_row['_sourceId'] = str(old_id)

        return new_row

    def _write_user(self, row):
        """通过 batch-save 写入一条用户数据"""
        # 使用 batch-save 的 createMap
        resp = self._http('POST', '/metadata/batch-save', json.dumps({
            'create_map': {
                'user': [row]
            }
        }).encode())
        if isinstance(resp, dict) and resp.get('code') == 200:
            return
        # 如果 batch-save 不支持业务数据写入，尝试 entity data API
        resp2 = self._http('POST', '/entity/data/user', json.dumps(row).encode())
        if isinstance(resp2, dict) and resp2.get('code') == 200:
            return
        log.warning(f'  写入响应: {str(resp)[:100]}, {str(resp2)[:100]}')

    def _report(self):
        log.info(f'\n[5/5] 迁移报告')
        log.info('=' * 60)
        log.info(f'  读取: {self.stats["read"]}')
        log.info(f'  写入: {self.stats["written"]}')
        log.info(f'  跳过: {self.stats["skipped"]}')
        log.info(f'  错误: {self.stats["errors"]}')
        if self.dry_run:
            log.info('  模式: DRY RUN（未实际写入）')
        log.info('=' * 60)

    def _http(self, method, path, body=None):
        url = BASE_URL + path
        headers = {
            'x-tenant-id': self.tenant_id,
            'x-user-id': '1',
            'x-device-type': 'web',
            'x-language-code': 'zh',
            'x-root-service': 'metarepo-web',
        }
        if self.token:
            headers['Authorization'] = f'Bearer {self.token}'
        if body:
            headers['Content-Type'] = 'application/json'

        req = urllib.request.Request(url, data=body, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as e:
            try:
                return json.loads(e.read())
            except Exception:
                return {'error': str(e)}
        except Exception as e:
            return {'error': str(e)}

    @staticmethod
    def _to_snake(s):
        import re
        return re.sub(r'([A-Z])', lambda m: '_' + m.group(1).lower(), s)


def main():
    dry_run = '--dry-run' in sys.argv
    tenant_id = DEFAULT_TENANT
    for i, arg in enumerate(sys.argv):
        if arg == '--tenant-id' and i + 1 < len(sys.argv):
            tenant_id = sys.argv[i + 1]

    migrator = UserMigrator(tenant_id=tenant_id, dry_run=dry_run)
    migrator.run()


if __name__ == '__main__':
    main()
