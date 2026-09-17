#!/usr/bin/env python3
"""Designer /CheckModules for thin client, web client and server on the LOADED configuration.

Usage: python3 check-modules.py [<filter>]

Prints the result code and the log lines; with a filter only the lines containing it — the log of
a real configuration usually holds old lines about other objects. Load the configuration first:
the check reads the infobase, not the sources. The linter does not report calls to undefined
methods or methods unavailable in a client; this check does.
"""
import os
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _ib  # noqa: E402

env = _ib.dev_env()
platform = env.get('PLATFORM_PATH', '')
binary = os.path.join(platform, '1cv8.exe' if os.name == 'nt' else '1cv8')
if not os.path.isfile(binary):
    binary = os.path.join(platform, 'bin', '1cv8.exe' if os.name == 'nt' else '1cv8')
if not os.path.isfile(binary):
    print(f'Не найден 1cv8 в PLATFORM_PATH ({platform})', file=sys.stderr)
    sys.exit(2)

infobase = ['/S', env['INFOBASE_PATH']] if env.get('INFOBASE_KIND') == 'server' else ['/F', env['INFOBASE_PATH']]
work = tempfile.mkdtemp(prefix='checkmodules_')
out, result = os.path.join(work, 'out.txt'), os.path.join(work, 'result.txt')
command = [binary, 'DESIGNER', *infobase, '/DisableStartupDialogs', '/DisableStartupMessages',
           '/CheckModules', '-ThinClient', '-WebClient', '-Server', '/Out', out, '/DumpResult', result]
if env.get('IB_USER'):
    command.insert(4, '/N' + env['IB_USER'])
    if env.get('IB_PASSWORD'):
        command.insert(5, '/P' + env['IB_PASSWORD'])

code = subprocess.run(command, timeout=1800).returncode
verdict = open(result, encoding='utf-8-sig').read().strip() if os.path.exists(result) else 'нет файла результата'
text_filter = sys.argv[1] if len(sys.argv) > 1 else None
lines = open(out, encoding='utf-8-sig', errors='replace').read().splitlines() if os.path.exists(out) else []
print(f'exit={code} result={verdict} lines={len(lines)}')
for line in lines:
    if text_filter is None or text_filter in line:
        print(line)
