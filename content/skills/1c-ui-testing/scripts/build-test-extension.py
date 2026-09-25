#!/usr/bin/env python3
"""Builds one test extension holding every test of the project, in the manager's file infobase.

The test manager runs as a **thick client against a file infobase**: the `Обработки` collection a
test is invoked through exists only there, and a thick client cannot reach a standalone server at
all (`/S` answers «не является адресом кластера», `/WS` — «Неопределена информационная база»). The
test client stays thin and works in the tested infobase on the standalone server.

A test is a data processor without a form:

    Обработки.<Object>.ВыполнитьСценарий(Контекст)   - manager module, &НаКлиенте
    Обработки.<Object>.ПолучитьМакет("<Step>")       - text template holding the server-side code

Only BSL is kept in the repository:

    openspec/tests/<capability>/ui/<Scenario>/<Scenario>.bsl        - the scenario
    openspec/tests/<capability>/ui/<Scenario>/server/<Step>.bsl     - its server-side steps
    openspec/tests/<capability>/e2e/<Scenario>/…                    - the same, kind e2e
    openspec/tests/<capability>/unit/<Check>.bsl                    - a server check, whole

The object name is composed here, not by the author: `<prefix><Capability>_<Kind>_<Name>`.

The build is skipped while the source fingerprint matches the loaded one (--force overrides).

Usage:
  build-test-extension.py [--tests openspec/tests] [--data-dir base-tests]
      [--extension Т_Тесты] [--prefix Т_] [--force]
"""
import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
EXTENSION_SOURCES = os.path.join(os.path.dirname(SCRIPT_DIR), 'extension')


def project_root():
    """The nearest ancestor of the working directory holding .dev.env."""
    directory = os.getcwd()
    while True:
        if os.path.isfile(os.path.join(directory, '.dev.env')):
            return directory
        parent = os.path.dirname(directory)
        if parent == directory:
            sys.exit('No .dev.env found: run from the project directory')
        directory = parent


def dev_env(root):
    """Keys of .dev.env; a value in matching quotes is unquoted."""
    values = {}
    with open(os.path.join(root, '.dev.env'), encoding='utf-8-sig') as handle:
        for line in handle:
            if '=' in line and not line.lstrip().startswith('#'):
                key, value = line.rstrip('\r\n').split('=', 1)
                value = value.strip()
                if len(value) >= 2 and value[0] == value[-1] and value[0] in '"\'':
                    value = value[1:-1].strip()
                values[key.strip()] = value
    return values


KIND_TAG = {'unit': 'Unit', 'ui': 'UI', 'e2e': 'E2E'}


def camel(text):
    """`catalog-items` -> `CatalogItems`: a metadata name tolerates no hyphens."""
    return ''.join(part[:1].upper() + part[1:] for part in re.split(r'[^0-9A-Za-zА-Яа-яЁё]+', text) if part)


def collect_tests(tests_dir):
    """Tests of the project: one dict per test, sorted by name.

    Fields: kind (ui/e2e/unit), capability, name, id, object, module (path to the BSL),
    text (manager module for ui/e2e), steps (step name -> text). A scenario's server steps live in
    its own `server` directory: they belong to it alone and never reach another processor's
    templates.

    A name in the sources carries the meaning of the check and nothing else. Uniqueness is the
    build's job — the object is `<prefix><Capability>_<Kind>_<Name>` — and a test is still found by
    its short name while that name is unambiguous. So the directory is not repeated in the file
    name, and a neighbour in another capability never forces a rename.
    """
    found = []
    for capability in sorted(os.listdir(tests_dir)):
        capability_dir = os.path.join(tests_dir, capability)
        if not os.path.isdir(capability_dir):
            continue

        for kind in ('ui', 'e2e'):
            kind_dir = os.path.join(capability_dir, kind)
            for name in sorted(os.listdir(kind_dir)) if os.path.isdir(kind_dir) else []:
                scenario_dir = os.path.join(kind_dir, name)
                module = os.path.join(scenario_dir, name + '.bsl')
                if not os.path.isfile(module):
                    continue
                steps_dir = os.path.join(scenario_dir, 'server')
                steps = {}
                for file_name in sorted(os.listdir(steps_dir)) if os.path.isdir(steps_dir) else []:
                    if file_name.endswith('.bsl'):
                        steps[os.path.splitext(file_name)[0]] = \
                            open(os.path.join(steps_dir, file_name), encoding='utf-8-sig').read()
                found.append({'kind': kind, 'capability': capability, 'name': name,
                              'module': module,
                              'text': open(module, encoding='utf-8-sig').read(), 'steps': steps})

        unit_dir = os.path.join(capability_dir, 'unit')
        for file_name in sorted(os.listdir(unit_dir)) if os.path.isdir(unit_dir) else []:
            if file_name.endswith('.bsl'):
                name = os.path.splitext(file_name)[0]
                path = os.path.join(unit_dir, file_name)
                found.append({'kind': 'unit', 'capability': capability, 'name': name,
                              'module': path, 'text': None,
                              'steps': {'Проверка': open(path, encoding='utf-8-sig').read()}})
    return found


def qualify(tests, prefix):
    """Gives every test its `id` (for lookup) and `object` (the extension object name).

    Two capabilities can in principle camel-case to one token (`yaml-library` and `yaml_library`
    would), and the collision would silently eat one of the tests, the manifest being a dict. The
    build stops on it instead, naming both source paths.
    """
    by_object = {}
    for test in tests:
        test['id'] = f'{test["capability"]}/{test["kind"]}/{test["name"]}'
        test['object'] = f'{prefix}{camel(test["capability"])}_{KIND_TAG[test["kind"]]}_{test["name"]}'
        by_object.setdefault(test['object'], []).append(test)

    collisions = {name: group for name, group in by_object.items() if len(group) > 1}
    if collisions:
        lines = ['Extension objects with the same name — build stopped:']
        for name, group in sorted(collisions.items()):
            lines.append(f'  {name}')
            lines += [f'    {test["module"]}' for test in group]
        raise SystemExit('\n'.join(lines))
    return tests


def fingerprint(tests_dir):
    """Fingerprint of every test source: any edit of them makes the build stale."""
    digest = hashlib.sha256()
    for directory, _, files in sorted(os.walk(tests_dir)):
        for file_name in sorted(files):
            if file_name.endswith('.bsl'):
                path = os.path.join(directory, file_name)
                digest.update(path.encode())
                digest.update(open(path, 'rb').read())
    return digest.hexdigest()


def dispatcher(tests, prefix):
    """Test dispatcher for the managed application module: one branch per test.

    It branches on the qualified `id` (`<capability>/<kind>/<name>`), which the runner supplies
    after resolving a short name against the manifest. Short names never reach the dispatcher, so
    same-named tests of different capabilities do not collide here.
    """
    body = ['Процедура Т_ВыполнитьТестПоИмени(Контекст)', '']
    condition = 'Если'
    for test in tests:
        body.append(f'\t{condition} Контекст.Тест = "{test["id"]}" Тогда')
        condition = 'ИначеЕсли'
        body.append(f'\t\tКонтекст.Обработка = "{test["object"]}";')
        if test['kind'] == 'unit':
            body.append(f'\t\t{prefix}Unit.ВыполнитьПроверку(Контекст);')
        else:
            body.append(f'\t\tОбработки.{test["object"]}.ВыполнитьСценарий(Контекст);')
    if condition == 'Если':
        body.append('\tВызватьИсключение "Тестовое расширение собрано без тестов";')
    else:
        body.append('\tИначе')
        body.append('\t\tВызватьИсключение "Тест не найден в расширении: " + Контекст.Тест;')
        body.append('\tКонецЕсли;')
    body += ['', 'КонецПроцедуры']
    return '\n'.join(body)


parser = argparse.ArgumentParser()
parser.add_argument('--tests', default='openspec/tests')
parser.add_argument('--data-dir', default='base-tests')
parser.add_argument('--extension', default='Т_Тесты')
parser.add_argument('--prefix', default='Т_')
parser.add_argument('--force', action='store_true')
args = parser.parse_args()

ROOT = project_root()
env = dev_env(ROOT)
PLATFORM = env['PLATFORM_PATH'].rstrip('/')
IBCMD, V8 = f'{PLATFORM}/ibcmd', f'{PLATFORM}/1cv8'
BASE = args.data_dir if os.path.isabs(args.data_dir) else os.path.join(ROOT, args.data_dir)
BUILD, MANIFEST = f'{BASE}-build', f'{BASE}/tests.manifest.json'
TESTS_DIR = args.tests if os.path.isabs(args.tests) else os.path.join(ROOT, args.tests)
# 1c-metadata-manage is a sibling skill wherever the skills are installed.
TOOLS = os.path.join(os.path.dirname(os.path.dirname(SCRIPT_DIR)), '1c-metadata-manage', 'tools')


def ibcmd(*command):
    """ibcmd against the manager file infobase (--db-path)."""
    split = 3 if command[:2] == ('infobase', 'config') else 2
    run = subprocess.run([IBCMD] + list(command[:split]) + [f'--db-path={BASE}'] + list(command[split:]),
                         capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=900)
    if run.returncode:
        sys.exit(f'{" ".join(command[:split + 1])}: exit {run.returncode}\n' + (run.stdout + run.stderr)[-800:])
    return run.stdout + run.stderr


def designer(*arguments, name='operation'):
    """Designer in batch mode over the file infobase; the verdict is read from the result file."""
    log, result = f'{BUILD}/{name}.log', f'{BUILD}/{name}.result'
    for path in (log, result):
        if os.path.exists(path):
            os.remove(path)
    subprocess.run([V8, 'DESIGNER', '/F', BASE, '/DisableStartupMessages', *arguments,
                    '/Out', log, '/DumpResult', result],
                   capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=900)
    verdict = open(result, encoding='utf-8-sig').read().strip() if os.path.exists(result) else ''
    output = open(log, encoding='utf-8-sig', errors='replace').read().strip() if os.path.exists(log) else ''
    return verdict, output


def create_base():
    """The manager file infobase: no server, no publication — only a thick client opens it."""
    os.makedirs(BASE, exist_ok=True)
    run = subprocess.run([V8, 'CREATEINFOBASE', f'File={BASE};Locale=ru_RU;', '/DisableStartupMessages'],
                         capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=900)
    if run.returncode or not os.path.exists(f'{BASE}/1Cv8.1CD'):
        sys.exit('The manager infobase was not created: ' + (run.stdout + run.stderr)[-400:])


def check_modules():
    """Designer /CheckModules over the extension.

    A compile error in an extension module gives no sign of itself until the run: the manager
    session shows a dialog, the protocol stays empty and the tested base's event log is clean.
    This check is the only place that names such an error.
    """
    if not os.environ.get('DISPLAY'):
        print('  skipped: no DISPLAY (Designer needs an X server)')
        return
    verdict, output = designer('/CheckModules', '-ThickClientManagedApplication',
                               '-Extension', args.extension, name='checkmodules')
    if verdict != '0':
        sys.exit(f'Extension modules fail the check (verdict {verdict or "no result file"}):\n'
                 + output[-1500:])
    print('  ' + (output.splitlines() or ['check performed'])[0])


def refuse_if_busy():
    """A file infobase cannot be rebuilt while a session holds it: the build says so outright."""
    busy = subprocess.run(['pgrep', '-x', '1cv8'], capture_output=True, text=True).stdout.split()
    holding = []
    for pid in busy:
        try:
            if BASE in open(f'/proc/{pid}/cmdline', 'rb').read().decode():
                holding.append(pid)
        except OSError:
            continue
    if holding:
        sys.exit(f'The manager infobase is held by {", ".join(holding)}: close them and repeat')


tests = collect_tests(TESTS_DIR)
if not tests:
    sys.exit(f'No test found in {TESTS_DIR}')
tests = qualify(tests, args.prefix)
current = fingerprint(TESTS_DIR)

loaded = json.load(open(MANIFEST, encoding='utf-8'))['fingerprint'] if os.path.isfile(MANIFEST) else None
if loaded == current and not args.force:
    print(f'No build needed: the source fingerprint matches ({len(tests)} tests)')
    print('Tests in the extension: ' + ', '.join(test['name'] for test in tests))
    sys.exit(0)

print(f'Tests to build: {len(tests)}'
      f" (ui/e2e: {sum(1 for t in tests if t['kind'] != 'unit')}, "
      f"unit: {sum(1 for t in tests if t['kind'] == 'unit')})", flush=True)
refuse_if_busy()

if not os.path.exists(f'{BASE}/1Cv8.1CD'):
    print('1. Manager file infobase', flush=True)
    create_base()

print('2. Extension and its scaffold', flush=True)
shutil.rmtree(BUILD, ignore_errors=True)
os.makedirs(BUILD, exist_ok=True)
# The extension is recreated whole: otherwise the exported scaffold carries objects of the
# previous build, and a renamed or deleted test stays in the infobase forever.
if f'"{args.extension}"' in ibcmd('infobase', 'config', 'extension', 'list'):
    ibcmd('infobase', 'config', 'extension', 'delete', f'--name={args.extension}')
ibcmd('infobase', 'config', 'extension', 'create', f'--name={args.extension}',
      f'--name-prefix={args.prefix}', '--purpose=add-on')
# Safe mode of an extension forbids writing the protocol file («Установлен безопасный режим»).
ibcmd('infobase', 'config', 'extension', 'update', f'--name={args.extension}', '--safe-mode=no')
ibcmd('infobase', 'config', 'export', f'--extension={args.extension}', BUILD)

print('3. Test data processors, their modules and templates', flush=True)
definition = f'{BUILD}/object.json'
for name, context, source in (('Прогон', 'client', 'Т_Прогон.bsl'), ('Unit', 'client', 'Т_Unit.bsl')):
    with open(definition, 'w', encoding='utf-8') as handle:
        json.dump({'type': 'CommonModule', 'name': args.prefix + name, 'context': context},
                  handle, ensure_ascii=False)
    made = subprocess.run(['python3', f'{TOOLS}/1c-meta-compile/scripts/meta-compile.py',
                           '-JsonPath', definition, '-OutputDir', BUILD],
                          capture_output=True, text=True, timeout=300)
    if made.returncode:
        sys.exit(f'Common module {name} was not created: ' + (made.stdout + made.stderr)[-400:])
    module = f'{BUILD}/CommonModules/{args.prefix}{name}/Ext/Module.bsl'
    os.makedirs(os.path.dirname(module), exist_ok=True)
    shutil.copy(f'{EXTENSION_SOURCES}/{source}', module)

for test in tests:
    processor = test['object']
    with open(definition, 'w', encoding='utf-8') as handle:
        json.dump({'type': 'DataProcessor', 'name': processor, 'synonym': test['id']},
                  handle, ensure_ascii=False)
    made = subprocess.run(['python3', f'{TOOLS}/1c-meta-compile/scripts/meta-compile.py',
                           '-JsonPath', definition, '-OutputDir', BUILD],
                          capture_output=True, text=True, timeout=300)
    if made.returncode:
        sys.exit(f'Data processor {processor} was not created: ' + (made.stdout + made.stderr)[-400:])

    if test['text'] is not None:
        manager = f'{BUILD}/DataProcessors/{processor}/Ext/ManagerModule.bsl'
        os.makedirs(os.path.dirname(manager), exist_ok=True)
        with open(manager, 'w', encoding='utf-8-sig') as handle:
            handle.write(test['text'])

    for step, text in sorted(test['steps'].items()):
        added = subprocess.run(['python3', f'{TOOLS}/1c-template-manage/scripts/add-template.py',
                                '-ObjectName', processor, '-TemplateName', step,
                                '-TemplateType', 'Text', '-SrcDir', f'{BUILD}/DataProcessors'],
                               capture_output=True, text=True, timeout=300)
        if added.returncode:
            sys.exit(f'Template {processor}.{step} was not created: ' + (added.stdout + added.stderr)[-400:])
        content = f'{BUILD}/DataProcessors/{processor}/Templates/{step}/Ext/Template.txt'
        os.makedirs(os.path.dirname(content), exist_ok=True)
        with open(content, 'w', encoding='utf-8') as handle:
            handle.write(text)
os.remove(definition)

application = open(f'{EXTENSION_SOURCES}/ManagedApplicationModule.bsl', encoding='utf-8').read()
head, _, tail = application.partition('Процедура Т_ВыполнитьТестПоИмени(Контекст)')
os.makedirs(f'{BUILD}/Ext', exist_ok=True)
with open(f'{BUILD}/Ext/ManagedApplicationModule.bsl', 'w', encoding='utf-8-sig') as handle:
    handle.write(head + dispatcher(tests, args.prefix) + tail.partition('// КОНЕЦ ДИСПЕТЧЕРА')[1] + '\n')

print('4. Loading the extension', flush=True)
ibcmd('infobase', 'config', 'import', f'--extension={args.extension}', BUILD)
ibcmd('infobase', 'config', 'apply', f'--extension={args.extension}', '--force')

print('5. Checking the extension modules', flush=True)
check_modules()

with open(MANIFEST, 'w', encoding='utf-8') as handle:
    json.dump({'fingerprint': current,
               'tests': {test['id']: {'kind': test['kind'],
                                      'capability': test['capability'],
                                      'name': test['name'],
                                      'object': test['object'],
                                      'module': os.path.relpath(test['module'], ROOT)}
                         for test in tests}},
              handle, ensure_ascii=False, indent=1)

print(f'\nManager infobase: file, {BASE}')
print('Tests in the extension: ' + ', '.join(test['name'] for test in tests))
