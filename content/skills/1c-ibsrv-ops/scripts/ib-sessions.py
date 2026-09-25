#!/usr/bin/env python3
"""Sessions of a standalone server (ibsrv) through ibcmd: list and terminate.

Sessions of killed clients stay in the infobase, survive a restart of the server and hold their
licenses until they are terminated — see docs/troubleshooting.md.

ibcmd asks for the infobase credentials on a terminal, so it is driven through a pty; the
credentials come from .dev.env and never appear on a command line.

Usage: ib-sessions.py <server pid|auto> list
       ib-sessions.py <server pid|auto> ids
       ib-sessions.py <server pid|auto> terminate <session-id>...
       ib-sessions.py <server pid|auto> terminate-all [<app-id>]

  <server pid>   the process of the standalone server: pgrep -x ibsrv
  auto           the server of IBSRV_DIR (.dev.env)
  <app-id>       terminate only sessions of that application (1CV8C, WebClient, …)
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _srv  # noqa: E402

env = _srv.dev_env()
IBCMD = env['PLATFORM_PATH'].rstrip('/') + '/ibcmd'


def run(args, timeout=120):
    """ibcmd on a pty — the credential prompts are answered from .dev.env."""
    return _srv.ibcmd_pty(args, env, timeout)


def sessions(server_pid):
    """Sessions as list of dicts with the fields ibcmd prints."""
    found, current = [], {}
    for line in run([f'--pid={server_pid}', 'session', 'list']).splitlines():
        if ':' not in line:
            continue
        key, _, value = line.partition(':')
        key, value = key.strip(), value.strip()
        if key == 'session':
            current = {}
            found.append(current)
        if current is not None:
            current[key] = value
    return [item for item in found if item.get('session')]


server = sys.argv[1]
if server == 'auto':
    server = _srv.server_pid(env)
    if not server:
        sys.exit('No standalone server found: check IBSRV_DIR in .dev.env and whether ibsrv runs')
command = sys.argv[2]
items = sessions(server)
if command == 'list':
    for item in items:
        print(f"{item.get('session-id'):>4} {item.get('app-id', ''):22} {item.get('user-name', '')} "
              f"{item.get('started-at', '')}")
    print(f'sessions in total: {len(items)}')
elif command == 'ids':
    print(' '.join(str(item.get('session-id')) for item in items))
elif command == 'terminate':
    wanted = set(sys.argv[3:])
    killed = 0
    for item in items:
        if str(item.get('session-id')) not in wanted:
            continue
        run([f'--pid={server}', 'session', 'terminate', f"--session={item['session']}",
             '--error-message=сеанс прогона снят его раннером'])
        killed += 1
    print(f'снято сеансов: {killed}, осталось: {len(sessions(server))}')
else:
    app_filter = sys.argv[3] if len(sys.argv) > 3 else None
    killed = 0
    for item in items:
        if app_filter and item.get('app-id') != app_filter:
            continue
        out = run([f'--pid={server}', 'session', 'terminate', f"--session={item['session']}",
                   '--error-message=сеанс снят перед прогоном тестов'])
        killed += 1
        if 'шибка' in out:
            print(f"сеанс {item.get('session-id')}: {out.strip().splitlines()[-1][:120]}")
    print(f'снято сеансов: {killed}, осталось: {len(sessions(server))}')
