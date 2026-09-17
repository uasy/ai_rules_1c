#!/usr/bin/env python3
"""Checks that the debug extension services are published and answer.

Usage: python3 check-services.py

For each service: a request without authentication (expected 401 — the server and publication
are alive) and an authenticated request (expected 200). An authenticated 404 means the service
is not published: the extension is not loaded, or default.vrd lacks
publishExtensionsByDefault="true". 403 means the user has no rights to the service. Exit code 0
when both services answer 200.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _ib  # noqa: E402

env = _ib.dev_env()
print(f'Публикация: {_ib.publish_url(env)}')

checks = (
    ('Dbg_Executor', '/hs/dbg_executor/exec/x', {'Код': 'Результат = 1;'}),
    ('Dbg_LogReader', '/hs/dbg_logreader/read/x', {'КоличествоСобытий': 1}),
)
hints = {
    200: 'работает',
    401: 'нет доступа с учётными данными .dev.env',
    403: 'у пользователя нет прав на сервис (нужны полные права)',
    404: 'не опубликован: расширение не загружено или в default.vrd нет publishExtensionsByDefault="true"',
}
healthy = True
for name, path, body in checks:
    anonymous, _ = _ib.request(env, 'POST', path, b'{}', auth=False, timeout=30)
    status, text = _ib.request(env, 'POST', path, json.dumps(body, ensure_ascii=False).encode('utf-8'), timeout=60)
    print(f'{name:14} без аутентификации HTTP {anonymous}; с аутентификацией HTTP {status} — '
          f'{hints.get(status, text[:200])}')
    healthy = healthy and status == 200
sys.exit(0 if healthy else 1)
