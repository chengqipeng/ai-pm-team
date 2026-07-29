import asyncio, os, sys, time, json, types

sys.path.insert(0, '.')

fake_ctx_mod = types.ModuleType('src.core.context')
fake_core = types.ModuleType('src.core')
class FakeCtx:
    thread_id = 'e2e-' + str(int(time.time()))
    tenant_id = 't100'
    user_id = 'u200'
def get_context():
    return FakeCtx()
fake_ctx_mod.get_context = get_context
sys.modules['src.core'] = fake_core
sys.modules['src.core.context'] = fake_ctx_mod

from src.tools.sandbox.aws_agentcore_backend import AWSAgentCoreSandboxBackend, AWSAgentCoreConfig

REGION = 'ap-southeast-1'
BUCKET = 'agentcore-sandbox-p10'
TID = FakeCtx.thread_id
results = []

def rpt(name, ok, detail=''):
    results.append((name, ok))
    mark = 'PASS' if ok else 'FAIL'
    print('  [' + mark + '] ' + name + (' -- ' + detail if detail else ''))

async def main():
    import boto3
    s3 = boto3.client('s3', region_name=REGION)
    config = AWSAgentCoreConfig(region=REGION, session_timeout=300, working_dir='/tmp/sandbox',
                                sync_bucket=BUCKET, sync_prefix='sandbox', sync_interval=3)
    def make_backend():
        b = AWSAgentCoreSandboxBackend(config)
        b._get_session_id = lambda: TID
        b._get_tenant_id = lambda: 't100'
        b._get_user_id = lambda: 'u200'
        b._save_session_id_to_db = lambda x: None
        b._retry_save_session_id = lambda: None
        return b

    backend = make_backend()
    print('Session: ' + TID)
    print('=' * 50)

    print('\n[1] connect + dirs')
    await backend.connect()
    rpt('connect', backend.is_connected, 'sid=' + str(backend.session_id))
    r = await backend.execute('ls /tmp/sandbox/')
    rpt('dirs', 'workspace' in r.stdout and 'uploads' in r.stdout and 'outputs' in r.stdout)

    print('\n[2] write_file + S3 dual-write')
    data = json.dumps({'ts': int(time.time()), 'msg': 'hello'})
    r = await backend.write_file('/tmp/sandbox/outputs/rpt.json', data)
    rpt('write_file', r.exit_code == 0)
    await asyncio.sleep(2)
    key = 'sandbox/t100/u200/' + TID + '/outputs/rpt.json'
    try:
        obj = s3.get_object(Bucket=BUCKET, Key=key)
        rpt('S3_dual_write', True, 'size=' + str(obj['ContentLength']))
    except Exception as e:
        rpt('S3_dual_write', False, str(e))

    print('\n[3] outside workdir no sync')
    await backend.write_file('/tmp/outside.txt', 'no')
    await asyncio.sleep(1)
    try:
        s3.get_object(Bucket=BUCKET, Key='sandbox/t100/u200/' + TID + '/outside.txt')
        rpt('no_sync_outside', False)
    except:
        rpt('no_sync_outside', True)

    print('\n[4] redirect triggers sync')
    await backend.execute('echo redir_ok > /tmp/sandbox/workspace/rd.txt')
    await asyncio.sleep(2)
    key = 'sandbox/t100/u200/' + TID + '/workspace/rd.txt'
    try:
        obj = s3.get_object(Bucket=BUCKET, Key=key)
        c = obj['Body'].read().decode()
        rpt('redirect_sync', 'redir_ok' in c, c.strip())
    except Exception as e:
        rpt('redirect_sync', False, str(e))

    print('\n[5] counter sync')
    await backend.execute('echo cnt_data > /tmp/sandbox/workspace/cnt.txt')
    await backend.execute('date')
    await backend.execute('whoami')
    await asyncio.sleep(2)
    key = 'sandbox/t100/u200/' + TID + '/workspace/cnt.txt'
    try:
        s3.get_object(Bucket=BUCKET, Key=key)
        rpt('counter_sync', True)
    except Exception as e:
        rpt('counter_sync', False, str(e))

    print('\n[6] read_file')
    r = await backend.read_file('/tmp/sandbox/outputs/rpt.json')
    rpt('read_ok', r.exit_code == 0 and 'ts' in r.stdout)
    r = await backend.read_file('/tmp/sandbox/no_such.xyz')
    rpt('read_404', r.exit_code != 0)

    print('\n[7] file_exists')
    ex = await backend.file_exists('/tmp/sandbox/outputs/rpt.json')
    nex = await backend.file_exists('/tmp/sandbox/nope.xyz')
    rpt('file_exists', ex and not nex, 'ex=' + str(ex) + ' nex=' + str(nex))

    print('\n[8] disconnect full sync')
    await backend.execute('echo final_ok > /tmp/sandbox/uploads/fin.txt')
    await backend.disconnect(force_kill=False)
    rpt('disconnect', not backend.is_connected)
    key = 'sandbox/t100/u200/' + TID + '/uploads/fin.txt'
    try:
        obj = s3.get_object(Bucket=BUCKET, Key=key)
        c = obj['Body'].read().decode()
        rpt('full_sync', 'final_ok' in c)
    except Exception as e:
        rpt('full_sync', False, str(e))

    print('\n[9] new connect restores S3')
    b2 = make_backend()
    await b2.connect()
    rpt('reconnect', b2.is_connected)
    r = await b2.read_file('/tmp/sandbox/outputs/rpt.json')
    rpt('restore_outputs', r.exit_code == 0 and 'ts' in r.stdout, 'len=' + str(len(r.stdout)))
    r = await b2.read_file('/tmp/sandbox/uploads/fin.txt')
    rpt('restore_uploads', r.exit_code == 0 and 'final_ok' in r.stdout)

    print('\n[10] force_kill skips sync')
    await b2.execute('echo lost > /tmp/sandbox/workspace/lost.txt')
    await b2.disconnect(force_kill=True)
    rpt('force_kill_dc', not b2.is_connected)
    key = 'sandbox/t100/u200/' + TID + '/workspace/lost.txt'
    try:
        s3.get_object(Bucket=BUCKET, Key=key)
        rpt('force_kill_no_sync', False, 'should not exist')
    except:
        rpt('force_kill_no_sync', True)

    # cleanup
    print('\nCleanup...')
    prefix = 'sandbox/t100/u200/' + TID + '/'
    pg = s3.get_paginator('list_objects_v2')
    for page in pg.paginate(Bucket=BUCKET, Prefix=prefix):
        for obj in page.get('Contents', []):
            s3.delete_object(Bucket=BUCKET, Key=obj['Key'])

    print('\n' + '=' * 50)
    p = sum(1 for _, ok in results if ok)
    for name, ok in results:
        mark = 'PASS' if ok else 'FAIL'
        print('  [' + mark + '] ' + name)
    print('\n  Result: ' + str(p) + '/' + str(len(results)) + ' passed')
    print('=' * 50)
    return all(ok for _, ok in results)

ok = asyncio.run(main())
sys.exit(0 if ok else 1)
