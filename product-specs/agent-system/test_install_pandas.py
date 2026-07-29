"""验证远程沙箱安装 pandas/numpy 的脚本"""
import asyncio
import os

os.environ.setdefault('SANDBOX_SSH_HOST', '172.17.2.118')
os.environ.setdefault('SANDBOX_SSH_USER', 'hermes')
os.environ.setdefault('SANDBOX_SSH_PORT', '22')

from src.tools.sandbox.ssh_backend import create_ssh_backend_from_env


async def install():
    backend = create_ssh_backend_from_env()
    await backend.connect()

    # 先升级 pip
    print('Upgrading pip...')
    r = await backend.execute(
        '/usr/local/bin/python3 -m pip3 install --upgrade pip3 2>&1 | tail -3',
        timeout=60
    )
    print(r.stdout.strip())

    # 用 pip3.11 安装
    print('Installing with pip3.11...')
    r = await backend.execute(
        '/usr/local/bin/pip3.11 install pandas numpy python-dateutil 2>&1 | tail -10',
        timeout=300
    )
    print(r.stdout[-500:] if r.stdout else '(none)')
    print('exit_code:', r.exit_code)

    # verify
    r = await backend.execute(
        '/usr/local/bin/python3 -c "import pandas,numpy; print(pandas.__version__, numpy.__version__)"'
    )
    print('verify:', r.stdout.strip() if not r.is_error else r.stdout)


asyncio.run(install())
