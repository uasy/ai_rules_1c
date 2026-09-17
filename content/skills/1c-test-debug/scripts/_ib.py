"""Shared helpers of the 1c-test-debug scripts: project root, .dev.env, HTTP calls to the
published infobase with the credentials from .dev.env (they never appear on a command line).
"""
import base64
import json
import os
import sys
import urllib.error
import urllib.request


def project_root():
    """Nearest ancestor of the working directory that holds .dev.env.

    The skill may be installed under any tool directory, so the root is never derived from
    the location of the script itself.
    """
    directory = os.getcwd()
    while True:
        if os.path.isfile(os.path.join(directory, '.dev.env')):
            return directory
        parent = os.path.dirname(directory)
        if parent == directory:
            print('Не найден .dev.env: запускайте из каталога проекта', file=sys.stderr)
            sys.exit(2)
        directory = parent


def dev_env(root=None):
    """Keys of .dev.env; a value in matching single or double quotes is unquoted."""
    values = {}
    with open(os.path.join(root or project_root(), '.dev.env'), encoding='utf-8-sig') as handle:
        for line in handle:
            if '=' in line and not line.lstrip().startswith('#'):
                key, value = line.rstrip('\r\n').split('=', 1)
                value = value.strip()
                if len(value) >= 2 and value[0] == value[-1] and value[0] in '"\'':
                    value = value[1:-1].strip()
                values[key.strip()] = value
    return values


def publish_url(env):
    url = env.get('INFOBASE_PUBLISH_URL', '').rstrip('/')
    if not url:
        print('В .dev.env не задан INFOBASE_PUBLISH_URL', file=sys.stderr)
        sys.exit(2)
    return url


def request(env, method, path, body=None, auth=True, headers=(), timeout=120):
    """Returns (status, text). Exits with code 2 when the server does not answer."""
    url = path if path.startswith(('http://', 'https://')) else publish_url(env) + '/' + path.lstrip('/')
    call = urllib.request.Request(url, data=body, method=method)
    if body is not None:
        call.add_header('Content-Type', 'application/json; charset=utf-8')
    for name, value in headers:
        call.add_header(name, value)
    if auth:
        credentials = f"{env.get('IB_USER', '')}:{env.get('IB_PASSWORD', '')}"
        call.add_header('Authorization', 'Basic ' + base64.b64encode(credentials.encode('utf-8')).decode())
    try:
        response = urllib.request.urlopen(call, timeout=timeout)
        status, raw = response.status, response.read()
    except urllib.error.HTTPError as error:
        status, raw = error.code, error.read()
    except (urllib.error.URLError, TimeoutError) as error:
        print(f'Сервер не отвечает ({url}): {error}. Опубликована ли база, запущен ли веб-сервер?',
              file=sys.stderr)
        sys.exit(2)
    return status, raw.decode('utf-8', 'replace').lstrip('﻿')


def read_event_log(env, event_filter, timeout=60):
    """Events of the event log through the Dbg_LogReader service of the debug extension."""
    status, text = request(env, 'POST', '/hs/dbg_logreader/read/x',
                           json.dumps(event_filter, ensure_ascii=False).encode('utf-8'), timeout=timeout)
    if status != 200:
        print(f'Журнал не прочитан: HTTP {status} {text[:300]}', file=sys.stderr)
        sys.exit(2)
    return json.loads(text)['События']
