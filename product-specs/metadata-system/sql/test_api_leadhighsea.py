#!/usr/bin/env python3
"""直接调 API 测试 leadHighSea，并对比 highSea"""
import subprocess, json

def gen_token():
    return subprocess.check_output(['python3', 'product-specs/metadata-system/sql/gen_token.py']).decode().strip()

def api_get(path, token):
    result = subprocess.run(
        ['curl', '-s', f'http://127.0.0.1:18010{path}', '-H', f'Authorization: Bearer {token}'],
        capture_output=True, text=True, timeout=10
    )
    return json.loads(result.stdout) if result.stdout else None

token = gen_token()

print("=== 1. 对比 highSea 和 leadHighSea ===")
for entity in ['highSea', 'leadHighSea', 'account', 'lead']:
    resp = api_get(f'/entity/data/{entity}?page=1&size=5', token)
    total = resp.get('data', {}).get('total', '?') if resp else 'ERROR'
    recs = len(resp.get('data', {}).get('records', [])) if resp else 0
    print(f"  {entity:20s} total={total}, records={recs}")

print("\n=== 2. 检查 entity 列表 API ===")
resp = api_get('/metadata/entities', token)
if resp:
    entities = resp.get('data', resp) if isinstance(resp.get('data'), list) else resp.get('data', {}).get('data', [])
    if isinstance(entities, list):
        for e in entities:
            ak = e.get('apiKey', e.get('api_key', ''))
            if 'lead' in ak.lower() or 'high' in ak.lower():
                print(f"  {ak}: label={e.get('label', '')}, enableFlg={e.get('enableFlg', e.get('enable_flg', ''))}")
    else:
        print(f"  响应格式: {type(entities)}, keys={list(resp.keys()) if isinstance(resp, dict) else '?'}")
else:
    print("  ERROR: 无响应")

print("\n=== 3. 直接查 leadHighSea 详情 ===")
# 用已知的 ID
resp = api_get('/entity/data/leadHighSea/3006781577359471', token)
if resp:
    data = resp.get('data')
    if data:
        print(f"  name={data.get('name')}, depart={data.get('depart_api_key')}")
    else:
        print(f"  data=null, resp={json.dumps(resp, ensure_ascii=False)[:200]}")
else:
    print("  ERROR: 无响应")
