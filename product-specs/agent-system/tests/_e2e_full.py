import sys, types, time, asyncio, json, base64
sys.path.insert(0, '.')
import src.core
src.core.context = types.ModuleType('src.core.context')
class FC:
    thread_id = 'full-' + str(int(time.time()))
    tenant_id = 't100'
    user_id = 'u200'
src.core.context.get_context = lambda: FC()
sys.modules['src.core.context'] = src.core.context
from src.tools.sandbox.aws_agentcore_backend import AWSAgentCoreSandboxBackend, AWSAgentCoreConfig
R='ap-southeast-1'; B='agentcore-sandbox-p10'; TID=FC.thread_id
results=[]
def rpt(n,ok,d=''):
    results.append((n,ok))
    print('  ['+('PASS' if ok else 'FAIL')+'] '+n+(' -- '+d if d else ''))
async def main():
    import boto3
    s3=boto3.client('s3',region_name=R)
    cfg=AWSAgentCoreConfig(region=R,session_timeout=300,working_dir='/tmp/sandbox',sync_bucket=B,sync_prefix='sandbox',sync_interval=3)
    def mk():
        b=AWSAgentCoreSandboxBackend(cfg)
        b._get_session_id=lambda:TID
        b._get_tenant_id=lambda:'t100'
        b._get_user_id=lambda:'u200'
        b._save_session_id_to_db=lambda x:None
        b._retry_save_session_id=lambda:None
        return b
    be=mk()
    print('TID='+TID)
    print('='*60)
    # A connect
    print('\n[A1] connect')
    await be.connect()
    rpt('A1_connect',be.is_connected)
    r=await be.execute('ls /tmp/sandbox/')
    rpt('A2_dirs','workspace' in r.stdout and 'uploads' in r.stdout and 'outputs' in r.stdout)
    old_sid=be.session_id
    await be.connect()
    rpt('A3_idempotent',be.session_id==old_sid)
    # B write_file
    print('\n[B] write_file')
    r=await be.write_file('/tmp/sandbox/workspace/hello.txt','Hello World!')
    rpt('B1_text',r.exit_code==0)
    jdata=json.dumps({'name':'test','items':[1,2,3],'zh':'中文'},ensure_ascii=False)
    r=await be.write_file('/tmp/sandbox/outputs/data.json',jdata)
    rpt('B2_json',r.exit_code==0)
    special='line1\nline2\n\ttab\n"quotes"\nend'
    r=await be.write_file('/tmp/sandbox/workspace/special.txt',special)
    rpt('B3_special',r.exit_code==0)
    big='x'*10240
    r=await be.write_file('/tmp/sandbox/outputs/big.bin',big)
    rpt('B4_big',r.exit_code==0)
    r=await be.write_file('/tmp/sandbox/workspace/a/b/c/deep.txt','deep')
    rpt('B5_nested',r.exit_code==0)
    await be.write_file('/tmp/sandbox/workspace/hello.txt','v1')
    r=await be.write_file('/tmp/sandbox/workspace/hello.txt','v2')
    r2=await be.read_file('/tmp/sandbox/workspace/hello.txt')
    rpt('B6_overwrite',r.exit_code==0 and 'v2' in r2.stdout)
    await asyncio.sleep(2)
    k='sandbox/t100/u200/'+TID+'/outputs/data.json'
    try:
        s3.get_object(Bucket=B,Key=k);rpt('B7_s3_dual',True)
    except Exception as e:
        rpt('B7_s3_dual',False,str(e))
    await be.write_file('/tmp/nosync.txt','x')
    await asyncio.sleep(1)
    try:
        s3.get_object(Bucket=B,Key='sandbox/t100/u200/'+TID+'/nosync.txt');rpt('B8_no_outside',False)
    except:
        rpt('B8_no_outside',True)
    # C read_file
    print('\n[C] read_file')
    r=await be.read_file('/tmp/sandbox/workspace/hello.txt')
    rpt('C1_read',r.exit_code==0 and 'v2' in r.stdout)
    r=await be.read_file('/tmp/sandbox/outputs/data.json')
    rpt('C2_json','中文' in r.stdout)
    r=await be.read_file('/tmp/sandbox/workspace/special.txt')
    rpt('C3_special',r.exit_code==0 and 'quotes' in r.stdout)
    r=await be.read_file('/tmp/sandbox/outputs/big.bin')
    rpt('C4_big',r.exit_code==0 and len(r.stdout)>=10000)
    r=await be.read_file('/tmp/sandbox/workspace/a/b/c/deep.txt')
    rpt('C5_nested',r.exit_code==0 and 'deep' in r.stdout)
    r=await be.read_file('/tmp/sandbox/no_exist.xyz')
    rpt('C6_404',r.exit_code!=0)
    # D execute
    print('\n[D] execute')
    r=await be.execute('echo hello && pwd')
    rpt('D1_basic',r.exit_code==0 and 'hello' in r.stdout)
    await be.write_file('/tmp/sandbox/workspace/calc.py','import math\nprint(math.pi)\n')
    r=await be.execute('python3 /tmp/sandbox/workspace/calc.py')
    rpt('D2_python','3.14' in r.stdout)
    r=await be.execute('echo -e "b\\na\\nc" | sort')
    rpt('D3_pipe',r.exit_code==0)
    r=await be.execute('export FOO=bar && echo $FOO')
    rpt('D4_env','bar' in r.stdout)
    r=await be.execute('seq 1 5 | while read i; do echo "line $i"; done')
    rpt('D5_loop','line 5' in r.stdout)
    await be.execute('echo sync_d6 > /tmp/sandbox/workspace/d6.txt')
    k='sandbox/t100/u200/'+TID+'/workspace/d6.txt'
    try:
        o=s3.get_object(Bucket=B,Key=k);c=o['Body'].read().decode();rpt('D6_redir_sync','sync_d6' in c)
    except Exception as e:
        rpt('D6_redir_sync',False,str(e))
    await be.execute('echo tee_test | tee /tmp/sandbox/workspace/d7.txt')
    k='sandbox/t100/u200/'+TID+'/workspace/d7.txt'
    try:
        o=s3.get_object(Bucket=B,Key=k);c=o['Body'].read().decode();rpt('D7_tee','tee_test' in c)
    except Exception as e:
        rpt('D7_tee',False,str(e))
    r=await be.execute('ls /nonexist_xyz 2>&1; echo DONE')
    rpt('D8_err_cmd','DONE' in r.stdout)
    r=await be.execute('python3 -c "print(\'A\'*60000)"')
    rpt('D9_truncate',r.exit_code==0 and len(r.stdout)<=51000)
    # E file_exists
    print('\n[E] file_exists')
    rpt('E1_exists',await be.file_exists('/tmp/sandbox/outputs/data.json'))
    rpt('E2_not',not await be.file_exists('/tmp/sandbox/ghost.xyz'))
    rpt('E3_dir',await be.file_exists('/tmp/sandbox/workspace'))
    # F disconnect + restore
    print('\n[F] disconnect + restore')
    await be.disconnect(force_kill=False)
    rpt('F1_dc',not be.is_connected)
    prefix='sandbox/t100/u200/'+TID+'/'
    checks=['outputs/data.json','outputs/big.bin','workspace/hello.txt','workspace/a/b/c/deep.txt']
    found=sum(1 for rel in checks if s3_exists(s3,B,prefix+rel))
    rpt('F2_s3_all',found==len(checks),'found='+str(found)+'/'+str(len(checks)))
    b2=mk()
    await b2.connect()
    rpt('F3_reconnect',b2.is_connected)
    r=await b2.read_file('/tmp/sandbox/outputs/data.json')
    rpt('F4_restore_json','中文' in r.stdout)
    r=await b2.read_file('/tmp/sandbox/workspace/a/b/c/deep.txt')
    rpt('F4_restore_nested','deep' in r.stdout)
    r=await b2.read_file('/tmp/sandbox/outputs/big.bin')
    rpt('F4_restore_big',len(r.stdout)>=10000)
    r=await b2.write_file('/tmp/sandbox/workspace/post_restore.txt','ok')
    rpt('F5_write_after',r.exit_code==0)
    r=await b2.execute('wc -c /tmp/sandbox/outputs/big.bin')
    rpt('F6_exec_after','10240' in r.stdout)
    # G 边界
    print('\n[G] edge cases')
    r=await b2.write_file('/tmp/sandbox/workspace/empty.txt','')
    r2=await b2.read_file('/tmp/sandbox/workspace/empty.txt')
    rpt('G1_empty',r.exit_code==0)
    r=await b2.write_file('/tmp/sandbox/workspace/cn_name.md','# 报告')
    r2=await b2.read_file('/tmp/sandbox/workspace/cn_name.md')
    rpt('G2_chinese','报告' in r2.stdout)
    enc=base64.b64encode(b'\x00\x01\x02PNG').decode()
    r=await b2.write_file('/tmp/sandbox/workspace/enc.b64',enc)
    r2=await b2.read_file('/tmp/sandbox/workspace/enc.b64')
    rpt('G3_b64',enc in r2.stdout)
    tasks=[b2.write_file('/tmp/sandbox/workspace/p'+str(i)+'.txt','val'+str(i)) for i in range(5)]
    rets=await asyncio.gather(*tasks)
    rpt('G4_parallel',all(r.exit_code==0 for r in rets))
    all_read=True
    for i in range(5):
        r=await b2.read_file('/tmp/sandbox/workspace/p'+str(i)+'.txt')
        if 'val'+str(i) not in r.stdout: all_read=False
    rpt('G4_parallel_read',all_read)
    # H force_kill
    print('\n[H] force_kill')
    await b2.execute('echo ephemeral > /tmp/sandbox/workspace/eph.txt')
    await b2.disconnect(force_kill=True)
    rpt('H1_fk_dc',not b2.is_connected)
    # summary
    print('\n'+'='*60)
    ps=sum(1 for _,ok in results if ok)
    fl=len(results)-ps
    for n,ok in results:
        print('  ['+('PASS' if ok else 'FAIL')+'] '+n)
    print('\n  Result: '+str(ps)+'/'+str(len(results))+' passed, '+str(fl)+' failed')
    print('='*60)

def s3_exists(s3,bucket,key):
    try:
        s3.head_object(Bucket=bucket,Key=key)
        return True
    except:
        return False

asyncio.run(main())
