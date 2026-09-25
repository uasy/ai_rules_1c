#!/usr/bin/env python3
"""HTTP call to the published test infobase with credentials from .dev.env.

Replaces curl for agents: the password appears neither on the command line nor in a session log.

Usage:
  python3 ib-http.py <METHOD> <path> [--data <JSON> | --data-file <file>] [--no-auth]
      [--user <name> --password-file <file>] [--include]
      [--header "<Name>: <value>"]... [--timeout <s>]
  python3 ib-http.py --exec <file.bsl> [--timeout <s>]
  python3 ib-http.py --code "<BSL statements>" [--timeout <s>]

  <path>       relative to INFOBASE_PUBLISH_URL (/hs/<root>/...) or a full URL.
  --no-auth    no Basic authentication (checks access refusal).
  --user       authenticates as this infobase user instead of IB_USER (checks the rights of
               a role); the password is the first line of --password-file, so it appears
               neither on the command line nor in the output. An empty file - empty password.
  --include    prints the response headers after the status line, one «Name: value» per line.
  --exec       runs BSL from the file through Dbg_Executor and prints its «Результат».
  --code       the same for BSL given on the command line (short checks; no shell heredoc needed).

Prints «HTTP <code>», the headers with --include, an empty line after them, and the body (JSON indented). Exit code 0 for any server answer,
2 when the server does not answer, 3 when it closed the connection without an answer
(the server module crashed on the request — see the infobase event log and the server's output).
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _ib  # noqa: E402

parser = argparse.ArgumentParser()
parser.add_argument('method', nargs='?')
parser.add_argument('path', nargs='?')
parser.add_argument('--data')
parser.add_argument('--data-file')
parser.add_argument('--no-auth', action='store_true')
parser.add_argument('--user')
parser.add_argument('--password-file')
parser.add_argument('--include', action='store_true')
parser.add_argument('--header', action='append', default=[])
parser.add_argument('--timeout', type=int, default=120)
parser.add_argument('--exec', dest='exec_file')
parser.add_argument('--code')
args = parser.parse_args()

env = _ib.dev_env()
executes = bool(args.exec_file or args.code)
if executes:
    if args.exec_file:
        with open(args.exec_file, encoding='utf-8-sig') as handle:
            code = handle.read()
    else:
        code = args.code
    body = json.dumps({'Код': code}, ensure_ascii=False).encode('utf-8')
    method, path = 'POST', '/hs/dbg_executor/exec/x'
else:
    if not args.method or not args.path:
        parser.error('needs <METHOD> and <path>, --exec <file.bsl> or --code "<BSL>"')
    method, path = args.method.upper(), args.path
    if args.data_file:
        with open(args.data_file, 'rb') as handle:
            body = handle.read()
    elif args.data is not None:
        body = args.data.encode('utf-8')
    else:
        body = None

credentials = None
if args.user is not None or args.password_file is not None:
    if args.user is None or args.password_file is None or args.no_auth:
        parser.error('--user and --password-file go together and exclude --no-auth')
    with open(args.password_file, encoding='utf-8-sig') as handle:
        lines = handle.read().splitlines()
    credentials = (args.user, lines[0] if lines else '')

headers = []
for header in args.header:
    name, _, value = header.partition(':')
    headers.append((name.strip(), value.strip()))

status, text, answer_headers = _ib.request(env, method, path, body, auth=not args.no_auth,
                                           headers=headers, timeout=args.timeout,
                                           credentials=credentials, with_headers=True)
print(f'HTTP {status}')
if args.include:
    for name, value in answer_headers:
        print(f'{name}: {value}')
    print()
try:
    parsed = json.loads(text)
    if executes and status == 200 and isinstance(parsed, dict) and 'Результат' in parsed:
        parsed = parsed['Результат']
    print(json.dumps(parsed, ensure_ascii=False, indent=2))
except ValueError:
    print(text)
