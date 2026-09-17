#!/usr/bin/env python3
"""Error events of the test infobase event log, read through Dbg_LogReader.

Usage: python3 ib-errors.py [<since>] [<count>] [--all]
  <since>  XML date-time (2026-09-16T17:31:00) or minutes ago; default 15.
  <count>  limit per part; default 20.
  --all    also show errors of background and scheduled jobs.

Prints two parts: runtime errors `_$PerformError$_` first — a module that does not compile,
including a UI scenario data processor, shows up here with its text and line — then other
events of level «Ошибка». Background job errors are hidden by default: a test infobase often
has many of them, and they crowd out the ones that matter.
"""
import datetime
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _ib  # noqa: E402

arguments = [a for a in sys.argv[1:] if a != '--all']
show_jobs = '--all' in sys.argv[1:]
since = arguments[0] if arguments else '15'
if since.isdigit():
    since = (datetime.datetime.now() - datetime.timedelta(minutes=int(since))).strftime('%Y-%m-%dT%H:%M:%S')
limit = int(arguments[1]) if len(arguments) > 1 else 20

env = _ib.dev_env()


def show(title, events):
    print(f'{title}: {len(events)}')
    for event in events:
        print(f"--- {event['Дата']} сеанс {event['Сеанс']} {event['ИмяПриложения']} {event['Событие']}")
        print((event['Комментарий'] or '').strip())


show(f'Ошибки выполнения с {since}',
     _ib.read_event_log(env, {'ДатаНачала': since, 'Событие': ['_$PerformError$_'], 'КоличествоСобытий': limit}))
# The limit applies before background jobs are filtered out here, so the request asks for more.
other = _ib.read_event_log(env, {'ДатаНачала': since, 'Уровень': ['Ошибка'],
                                 'КоличествоСобытий': min(limit * 20, 5000)})
other = [e for e in other if e['Событие'] != '_$PerformError$_'
         and (show_jobs or e['ИмяПриложения'] != 'BackgroundJob')][-limit:]
show('Прочие ошибки' + ('' if show_jobs else ' (без фоновых заданий)'), other)
