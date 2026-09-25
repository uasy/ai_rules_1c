#!/usr/bin/env python3
"""Prints the test environment and checks that the debug extension services are published and answer.

Usage: python3 check-services.py

The environment summary is the non-secret part of .dev.env (publication, infobase, platform, user;
the password only as set / not set), so that nobody needs to open .dev.env itself.

For each service: a request without authentication (expected 401 — the server and publication
are alive) and an authenticated request (expected 200). An authenticated 404 means the service is
not published: the extension is not applied, or the publication block of the server configuration
does not name the service (`1c-ibsrv-ops/docs/setup.md`). 503 means the service was found but its session
could not be created — same publication block. 403 means the user has no rights to the service.
Exit code 0 when both services answer 200.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _ib  # noqa: E402

env = _ib.dev_env()
print(f'Публикация: {_ib.publish_url(env)}')
print(f"База: {env.get('INFOBASE_KIND') or 'тип не задан'}, {env.get('INFOBASE_PATH') or 'путь не задан'}")
print(f"Платформа: {env.get('PLATFORM_PATH') or 'не задана'}")
print(f"Пользователь: {env.get('IB_USER') or 'не задан'}; пароль {'задан' if env.get('IB_PASSWORD') else 'не задан'}")
print(f"Автономный сервер: {env.get('IBSRV_DIR') or 'не используется (IBSRV_DIR пуст)'}"
      f"{' — состояние: ibsrv.py status навыка 1c-ibsrv-ops' if env.get('IBSRV_DIR') else ''}")

checks = (
    ('Dbg_Executor', '/hs/dbg_executor/exec/x', {'Код': 'Результат = 1;'}),
    ('Dbg_LogReader', '/hs/dbg_logreader/read/x', {'КоличествоСобытий': 1}),
)
hints = {
    200: 'работает',
    401: 'нет доступа с учётными данными .dev.env',
    403: 'у пользователя нет прав на сервис (нужны полные права)',
    404: 'не опубликован: расширение не применено или сервис не указан в публикации сервера',
    503: 'сервис найден, но сеанс не создан: в публикации сервера нет списка service',
}
healthy = True
for name, path, body in checks:
    anonymous, _ = _ib.request(env, 'POST', path, b'{}', auth=False, timeout=30)
    status, text = _ib.request(env, 'POST', path, json.dumps(body, ensure_ascii=False).encode('utf-8'), timeout=60)
    print(f'{name:14} без аутентификации HTTP {anonymous}; с аутентификацией HTTP {status} — '
          f'{hints.get(status, text[:200])}')
    healthy = healthy and status == 200
sys.exit(0 if healthy else 1)
