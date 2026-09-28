#!/usr/bin/env python3
# install-files-update — Install a Linux systemd user timer that refreshes a dedicated MCP Designer XML dump.
# Python peer of install-files-update.ps1: the same plan checks, ownership marker, task identity,
# messages and exit codes. Differences are only where Linux has no Windows counterpart:
#   - a systemd user timer and service replace the interactive current-user Task Scheduler task;
#     like that task, the timer runs only while the user is logged in (no linger);
#   - the stage is mirrored into the destination in Python instead of robocopy /MIR, and a file
#     whose content did not change is not rewritten;
#   - symbolic links are refused where the PowerShell script refuses reparse points / junctions;
#   - Designer is PLATFORM_PATH/bin/1cv8 or PLATFORM_PATH/1cv8 (the Linux package layout).
"""Connection settings are read from ProjectRoot/.dev.env on every run.
IndexPath must be the verified host path used by MCP PATH_CODE.
Install creates a launcher and a systemd user timer for the current user.
Run stages a full export through db-dump-xml.py before mirroring the files.
Existing non-empty directories require explicit -AdoptExisting on Install.
-CheckOnly validates without writing, connecting to 1C or registering a timer.
"""
import argparse
import datetime
import fcntl
import hashlib
import json
import os
import re
import shlex
import shutil
import stat
import subprocess
import sys
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', '_common'))
import dev_env  # noqa: E402

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))


class UpdateError(Exception):
    pass


def resolve_update_path(value, base):
    if not os.path.isabs(value):
        value = os.path.join(base, value)
    return os.path.normpath(os.path.abspath(value)).rstrip('/') or '/'


def within_path(path, parent):
    return path == parent or path.startswith(parent.rstrip('/') + '/')


def assert_no_symlink(path, recurse=False):
    cursor = path
    while cursor:
        if os.path.islink(cursor):
            raise UpdateError(f'Каталог содержит ссылку или junction: {cursor}')
        parent = os.path.dirname(cursor)
        if parent == cursor:
            break
        cursor = parent
    if recurse and os.path.isdir(path):
        for dirpath, dirnames, filenames in os.walk(path):
            for name in dirnames + filenames:
                full = os.path.join(dirpath, name)
                if os.path.islink(full):
                    raise UpdateError(f'Каталог содержит ссылку или junction: {full}')


def test_export_log(text):
    # Read only the platform log, not command lines containing arbitrary names.
    match = re.search(r'--- Log ---\s*(.*?)\s*--- End ---', text, re.S)
    if not match or not match.group(1).strip():
        return False
    remaining = re.sub(r'(?i)\b(ошибок|предупреждений)\s+не обнаружено\b|\b(ошибок|предупреждений)\s*:\s*0\b'
                       r'|\berrors were not found\b|\b0 errors\b', '', match.group(1))
    return not re.search(r'(?i)ошиб[ко]|предупреждени|не найден метод|не может быть применен|невозможно'
                         r'|\b(error|fatal|failed|failure|exception)\b', remaining)


def find_designer(platform_path):
    for candidate in (os.path.join(platform_path, 'bin', '1cv8'), os.path.join(platform_path, '1cv8')):
        if os.path.isfile(candidate):
            return candidate
    raise UpdateError('Не найден 1cv8 в PLATFORM_PATH (bin/1cv8 или 1cv8).')


def read_marker(path):
    with open(path, encoding='utf-8-sig') as handle:
        return json.load(handle)


def get_update_plan(args):
    if not sys.platform.startswith('linux'):
        raise UpdateError('Python-версия работает в Linux; в Windows используйте install-files-update.ps1.')
    root = resolve_update_path(args.ProjectRoot, os.getcwd())
    dest = resolve_update_path(args.IndexPath, root)
    if not os.path.isfile(os.path.join(root, '.dev.env')):
        raise UpdateError('В корне проекта отсутствует .dev.env. Создайте его через установщик правил.')
    if dest == '/' or within_path(root, dest):
        raise UpdateError('Каталог индексации не может быть корнем диска, проекта или его родителем.')
    assert_no_symlink(dest, recurse=True)
    values = {}
    for key in ('PLATFORM_PATH', 'INFOBASE_KIND', 'INFOBASE_PATH', 'IB_USER', 'IB_PASSWORD', 'EXTENSION_NAME',
                'EXPORT_PATH', 'EXTENSIONS_PATH'):
        values[key] = dev_env.get_value(key, root)
        if re.search(r'["\r\n]', values[key]):
            raise UpdateError(f'Недопустимая кавычка или перевод строки в {key}.')
    if not values['PLATFORM_PATH'] or not values['INFOBASE_PATH']:
        raise UpdateError('Заполните PLATFORM_PATH и INFOBASE_PATH в .dev.env.')
    kind = (values['INFOBASE_KIND'] or 'file').lower()
    if kind not in ('file', 'server'):
        raise UpdateError('INFOBASE_KIND должен быть file или server.')
    dump = {'V8Path': find_designer(resolve_update_path(values['PLATFORM_PATH'], root)),
            'Mode': 'Full', 'Format': 'Hierarchical'}
    if kind == 'file':
        dump['InfoBasePath'] = resolve_update_path(values['INFOBASE_PATH'], root)
        if not os.path.isfile(os.path.join(dump['InfoBasePath'], '1Cv8.1CD')):
            raise UpdateError('В INFOBASE_PATH не найден файл 1Cv8.1CD.')
        if within_path(dest, dump['InfoBasePath']) or within_path(dump['InfoBasePath'], dest):
            raise UpdateError('Каталог индексации пересекается с файловой базой.')
    else:
        connection = re.split(r'[/\\]', values['INFOBASE_PATH'], maxsplit=1)
        if len(connection) != 2 or not connection[0] or not connection[1]:
            raise UpdateError('Для серверной базы INFOBASE_PATH должен иметь вид сервер/имяБазы.')
        dump['InfoBaseServer'], dump['InfoBaseRef'] = connection
    for source_key, parameter in (('IB_USER', 'UserName'), ('IB_PASSWORD', 'Password'), ('EXTENSION_NAME', 'Extension')):
        if values[source_key]:
            dump[parameter] = values[source_key]
    for key in ('EXPORT_PATH', 'EXTENSIONS_PATH'):
        if values[key]:
            source = resolve_update_path(values[key], root)
        else:
            source = os.path.join(root, 'cfe') if key == 'EXTENSIONS_PATH' else root
        # A dedicated child of the project is allowed when EXPORT_PATH is the project root.
        if source != root and (within_path(dest, source) or within_path(source, dest)):
            raise UpdateError(f'Каталог индексации пересекается с {key}. Выберите отдельный каталог.')
    if os.path.exists(dest):
        for dirpath, dirnames, filenames in os.walk(dest):
            for name in dirnames + filenames:
                if name.lower() in ('.git', '.dev.env', 'agents.md') or name.lower().endswith('.mdo'):
                    raise UpdateError('Каталог содержит рабочий проект или исходники EDT. Нужен отдельный Designer XML dump.')
    task_id = hashlib.sha256((root + '|' + dest).lower().encode('utf-8')).hexdigest().upper()[:16]
    state = os.path.join(root, '.1c-files-update', task_id)
    if within_path(dest, os.path.join(root, '.1c-files-update')) or within_path(state, dest):
        raise UpdateError('Каталог индексации пересекается с каталогом скрипта и журналов.')
    assert_no_symlink(state, recurse=True)
    owner = os.path.join(dest, '.1c-files-update.json')
    if os.path.exists(owner):
        ownership = read_marker(owner)
        if ownership.get('ProjectRoot') != root or ownership.get('IndexPath') != dest:
            raise UpdateError('Каталог индексации принадлежит другому заданию.')
    elif args.Action == 'Run':
        raise UpdateError('Нет маркера установленного задания. Повторите /installfilesupdatescript.')
    elif os.path.isdir(dest) and os.listdir(dest) and not args.AdoptExisting:
        raise UpdateError('Каталог уже содержит файлы. Для передачи отдельного dump-каталога заданию требуется -AdoptExisting.')
    return {'Root': root, 'Destination': dest, 'State': state, 'Owner': owner, 'Dump': dump,
            'TaskName': '1C-MCP-Files-' + task_id}


def systemctl(*arguments, check=True):
    result = subprocess.run(['systemctl', '--user'] + list(arguments), capture_output=True, text=True)
    if check and result.returncode != 0:
        raise UpdateError(f'systemctl --user {" ".join(arguments)}: {(result.stderr or result.stdout).strip()}')
    return result


def unit_quote(value):
    # A double-quoted systemd argument: C escapes, and % starts a specifier.
    return '"' + value.replace('\\', '\\\\').replace('"', '\\"').replace('%', '%%') + '"'


def write_text(path, text, bom=False, mode=None):
    with open(path, 'w', encoding='utf-8-sig' if bom else 'utf-8', newline='\n') as handle:
        handle.write(text)
    if mode is not None:
        os.chmod(path, mode)


def install_files_update(plan, interval):
    if not shutil.which('systemctl') or systemctl('is-system-running', check=False).returncode not in (0, 1):
        raise UpdateError('Нет пользовательского менеджера systemd (systemctl --user).')
    unit_dir = os.path.join(os.environ.get('XDG_CONFIG_HOME') or os.path.expanduser('~/.config'), 'systemd', 'user')
    service_path = os.path.join(unit_dir, plan['TaskName'] + '.service')
    timer_path = os.path.join(unit_dir, plan['TaskName'] + '.timer')
    launcher = os.path.join(plan['State'], 'update-files.sh')
    description = '1c-rules MCP files: ' + plan['State']
    if os.path.isfile(service_path):
        with open(service_path, encoding='utf-8') as handle:
            existing = re.search(r'(?m)^Description=(.*)$', handle.read())
        if not existing or existing.group(1) != description.replace('%', '%%'):
            raise UpdateError('Имя задания занято чужим заданием.')
        if systemctl('is-active', plan['TaskName'] + '.service', check=False).stdout.strip() in ('active', 'activating'):
            raise UpdateError('Задание выполняется. Дождитесь завершения перед переустановкой.')
    os.makedirs(plan['State'], exist_ok=True)
    os.makedirs(plan['Destination'], exist_ok=True)
    write_text(plan['Owner'], json.dumps({'ProjectRoot': plan['Root'], 'IndexPath': plan['Destination']},
                                         ensure_ascii=False, indent=4), bom=True)
    # Only paths are persisted. Quote as shell literals, never interpolate env values as code.
    command = ' '.join(shlex.quote(part) for part in (
        sys.executable, os.path.abspath(__file__), '-Action', 'Run',
        '-ProjectRoot', plan['Root'], '-IndexPath', plan['Destination']))
    write_text(launcher, '#!/bin/sh\n# Generated by /installfilesupdatescript. Connection settings stay in .dev.env.\n'
               f'exec {command}\n', mode=stat.S_IRWXU)
    os.makedirs(unit_dir, exist_ok=True)
    write_text(service_path, '[Unit]\n'
               f'Description={description.replace("%", "%%")}\n\n'
               '[Service]\nType=oneshot\n'
               f'WorkingDirectory={plan["Root"].replace("%", "%%")}\n'
               f'ExecStart=/bin/sh {unit_quote(launcher)}\n'
               # No time limit on a long Designer export.
               'TimeoutStartSec=infinity\n')
    write_text(timer_path, '[Unit]\n'
               f'Description={description.replace("%", "%%")}\n\n'
               # First run in one minute, then every interval; a running export is not started twice.
               f'[Timer]\nOnActiveSec=1min\nOnUnitActiveSec={interval}min\nUnit={plan["TaskName"]}.service\n\n'
               '[Install]\nWantedBy=timers.target\n')
    systemctl('daemon-reload')
    systemctl('enable', plan['TaskName'] + '.timer')
    systemctl('restart', plan['TaskName'] + '.timer')
    exec_start = systemctl('show', plan['TaskName'] + '.service', '-p', 'ExecStart').stdout
    if launcher not in exec_start:
        raise UpdateError('Не удалось подтвердить действие установленного задания.')
    print(f'Задание: {plan["TaskName"]}; интервал: {interval} мин.; пользователь должен быть в системе.')
    print(f'Скрипт: {launcher}')
    print(f'Каталог MCP: {plan["Destination"]}; журнал: {os.path.join(plan["State"], "last-run.log")}')
    environment = systemctl('show-environment', check=False).stdout
    if not re.search(r'(?m)^(DISPLAY|WAYLAND_DISPLAY)=', environment):
        print('Внимание: в окружении пользовательского systemd нет DISPLAY — конфигуратору 1С нужен дисплей. '
              'Выполните в графическом сеансе: systemctl --user import-environment DISPLAY XAUTHORITY', file=sys.stderr)


def files_equal(left, right):
    try:
        if os.path.getsize(left) != os.path.getsize(right):
            return False
        with open(left, 'rb') as a, open(right, 'rb') as b:
            while True:
                chunk_a, chunk_b = a.read(1 << 20), b.read(1 << 20)
                if chunk_a != chunk_b:
                    return False
                if not chunk_a:
                    return True
    except OSError:
        return False


def remove_entry(path):
    if os.path.isdir(path) and not os.path.islink(path):
        shutil.rmtree(path)
    else:
        os.remove(path)


def mirror(stage, dest):
    """robocopy /MIR: dest ends up with exactly the stage's files; dest itself is kept."""
    for dirpath, dirnames, filenames in os.walk(stage):
        relative = os.path.relpath(dirpath, stage)
        target_dir = dest if relative == '.' else os.path.join(dest, relative)
        wanted = set(dirnames) | set(filenames)
        for name in sorted(os.listdir(target_dir)):
            if name not in wanted:
                remove_entry(os.path.join(target_dir, name))
        for name in dirnames:
            target = os.path.join(target_dir, name)
            if os.path.exists(target) and not os.path.isdir(target):
                os.remove(target)
            os.makedirs(target, exist_ok=True)
        for name in filenames:
            source, target = os.path.join(dirpath, name), os.path.join(target_dir, name)
            if os.path.isdir(target):
                shutil.rmtree(target)
            if not files_equal(source, target):
                temporary = target + '.1c-files-update.tmp'
                shutil.copy2(source, temporary)
                os.replace(temporary, target)


def append_log(log, text):
    with open(log, 'a', encoding='utf-8', newline='\n') as handle:
        handle.write(text if text.endswith('\n') else text + '\n')


def invoke_files_update(plan):
    os.makedirs(plan['State'], exist_ok=True)
    lock = open(os.path.join(plan['State'], 'run.lock'), 'a+')
    log = os.path.join(plan['State'], 'last-run.log')
    stage = os.path.normpath(os.path.join(plan['State'], 'staging'))
    try:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise UpdateError('Задание уже выполняется.') from None
        write_text(log, datetime.datetime.now().astimezone().isoformat() + ' START\n', bom=True)
        try:
            # Check the resolved deletion boundary before every recursive cleanup.
            if not within_path(stage, plan['State']) or stage == plan['State']:
                raise UpdateError('Некорректный временный каталог.')
            assert_no_symlink(stage, recurse=True)
            if os.path.exists(stage):
                shutil.rmtree(stage)
            os.makedirs(stage)
            params = dict(plan['Dump'], ConfigDir=stage)
            command = [sys.executable, os.path.join(SCRIPT_DIR, 'db-dump-xml.py')]
            for key, value in params.items():
                command += ['-' + key, value]
            result = subprocess.run(command, cwd=plan['Root'], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                    text=True, errors='replace')
            output = result.stdout or ''
            if params.get('Password'):
                output = output.replace(params['Password'], '***')
            append_log(log, output)
            if result.returncode != 0 or not test_export_log(output):
                raise UpdateError('Выгрузка 1С завершилась ошибкой или не подтверждена журналом.')
            for name in ('Configuration.xml', 'ConfigDumpInfo.xml'):
                file = os.path.join(stage, name)
                if not os.path.isfile(file):
                    raise UpdateError(f'В выгрузке отсутствует {name}.')
                try:
                    if ET.parse(file).getroot() is None:
                        raise UpdateError(f'Пустой XML: {name}.')
                except ET.ParseError as exc:
                    raise UpdateError(f'{name}: {exc}') from None
            # Preserve the directory itself (Docker mounts may refer to it). Mirroring is not atomic.
            assert_no_symlink(plan['Destination'], recurse=True)
            shutil.copyfile(plan['Owner'], os.path.join(stage, '.1c-files-update.json'))
            try:
                mirror(stage, plan['Destination'])
            except OSError as exc:
                append_log(log, str(exc))
                raise UpdateError('Ошибка копирования файлов MCP. Каталог может быть обновлён частично; см. журнал.') from None
            append_log(log, datetime.datetime.now().astimezone().isoformat() + ' SUCCESS')
        except Exception as exc:
            append_log(log, 'FAILED: ' + str(exc))
            raise
    finally:
        lock.close()


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description='Install a systemd user timer that refreshes a dedicated MCP Designer XML dump',
                                     allow_abbrev=False)
    parser.add_argument('-Action', default='Install', type=lambda v: v.capitalize(), choices=['Install', 'Run'])
    parser.add_argument('-ProjectRoot', required=True)
    parser.add_argument('-IndexPath', required=True)
    parser.add_argument('-IntervalMinutes', type=int, default=30)
    parser.add_argument('-AdoptExisting', action='store_true')
    parser.add_argument('-CheckOnly', action='store_true')
    parser.add_argument('-WhatIf', action='store_true')
    args = parser.parse_args()
    try:
        if not 1 <= args.IntervalMinutes <= 44640:
            raise UpdateError('IntervalMinutes должен быть от 1 до 44640.')
        plan = get_update_plan(args)
        if args.CheckOnly:
            # Do not print Dump: it contains the credentials.
            for key in ('Root', 'Destination', 'State', 'TaskName'):
                print(f'{key:<11} : {plan[key]}')
        elif args.WhatIf:
            print(f'What if: Performing the operation "{args.Action}" on target "{plan["Destination"]}".')
        elif args.Action == 'Install':
            install_files_update(plan, args.IntervalMinutes)
        else:
            invoke_files_update(plan)
        sys.exit(0)
    except Exception as exc:  # noqa: BLE001 - every failure is reported and exits 1
        print(str(exc), file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
