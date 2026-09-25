#!/usr/bin/env python3
"""Lifecycle of the standalone server of IBSRV_DIR: status, start, restart, stop.

The server is the publication of the test infobase (docs/setup.md). It holds its database
exclusively, keeps a stale lock.pid after every stop and can take minutes to disappear — this
script is what makes those three facts harmless.

Usage: ibsrv.py status | start | restart | stop

Sessions are a separate matter: ib-sessions.py (leftovers of killed clients hold licenses).
"""
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _srv  # noqa: E402

env = _srv.dev_env()
DIR = _srv.server_dir(env)
if not DIR:
    sys.exit('IBSRV_DIR is not set in .dev.env: nothing to start (file infobase or external cluster)')
CONFIG, DATA = f'{DIR}/server.yml', f'{DIR}/data'
IBSRV = env['PLATFORM_PATH'].rstrip('/') + '/ibsrv'
LOG = f'{DIR}/ibsrv.log'
command = sys.argv[1] if len(sys.argv) > 1 else 'status'


def pid():
    return _srv.server_pid(env)


def stop():
    running = pid()
    if not running:
        print('The server is not running')
    else:
        subprocess.run(['kill', running])
        for _ in range(60):
            if not pid():
                break
            time.sleep(2)
        if pid():
            print(f'Process {running} did not exit within 2 minutes, killing it')
            subprocess.run(['kill', '-9', pid()])
            time.sleep(4)
        print(f'The server is stopped (was pid {running})')
    # The lock file survives any stop and blocks the next start.
    if os.path.exists(f'{DATA}/lock.pid'):
        os.remove(f'{DATA}/lock.pid')
        print('Removed the data directory lock file')


def start():
    if pid():
        sys.exit(f'The server is already running, pid {pid()}')
    if not os.path.exists(CONFIG):
        sys.exit(f'No server configuration {CONFIG} — create it as docs/setup.md describes')
    if os.path.exists(f'{DATA}/lock.pid'):
        os.remove(f'{DATA}/lock.pid')
    subprocess.Popen(['setsid', IBSRV, f'--config={CONFIG}', f'--data={DATA}'],
                     stdout=open(LOG, 'w'), stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL)
    for _ in range(40):
        time.sleep(2)
        text = open(LOG, errors='replace').read()
        if 'ready' in text:
            print(f'The server is running, pid {pid()}; start log {LOG}')
            return
        if 'FATAL' in text:
            break
    sys.exit('The server did not come up:\n' + open(LOG, errors='replace').read()[-400:])


def status():
    running = pid()
    print(f'Infobase directory: {DIR}')
    print(f'Publication:        {env.get("INFOBASE_PUBLISH_URL") or "not set"}')
    print(f'Connection:         {env.get("INFOBASE_KIND") or "file"}, {env.get("INFOBASE_PATH") or "not set"}')
    if not running:
        print('Server:             NOT RUNNING')
        return
    print(f'Server:             running, pid {running}')

    sessions = [line for line in _srv.ibcmd_pty([f'--pid={running}', 'session', 'list'], env).splitlines()
                if line.startswith('app-id')]
    applications = {}
    for line in sessions:
        name = line.split(':', 1)[1].strip()
        applications[name] = applications.get(name, 0) + 1
    print('Sessions:           ' + (', '.join(f'{name} × {count}' for name, count in applications.items())
                                  if applications else 'none'))

    locks = [line for line in _srv.ibcmd_pty([f'--pid={running}', 'lock', 'list'], env).splitlines()
             if line.startswith('descr')]
    print('Locks:              ' + (', '.join(line.split(':', 1)[1].strip() for line in locks) if locks else 'none'))


if command == 'status':
    status()
elif command == 'start':
    start()
elif command == 'stop':
    stop()
elif command == 'restart':
    stop()
    start()
else:
    sys.exit('Commands: status | start | restart | stop')
