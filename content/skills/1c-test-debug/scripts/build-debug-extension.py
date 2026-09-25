#!/usr/bin/env python3
"""Builds the debug extension from the template of this skill and, on request, loads it.

The extension is not kept in the project: it is generated for the target configuration, because
its adopted language and compatibility modes belong to that configuration. The build goes to a
directory outside git (default `tmp/АгентОтладкаHTTP`) and can be repeated at any time.

Steps: scaffold without a role (`cfe-init -ConfigPath`), two HTTP services from `extension/*.json`
(`meta-compile`), their modules from `extension/*.bsl`, a check that every `<Handler>` names a
function of its module, `cfe-validate`.

`--load` puts it into the test infobase of `.dev.env` through the standalone server
(`1c-ibsrv-ops`, `IBSRV_DIR`): import, safe mode off (`Dbg_Executor` runs arbitrary code, which a
safe-mode extension refuses), apply. `Dbg_Executor` executes whatever it receives: load it only
into a test infobase and only when the user has agreed to it.

Usage:
  build-debug-extension.py [--out tmp/АгентОтладкаHTTP] [--config <main configuration sources>]
      [--load]

`--config` defaults to EXPORT_PATH of .dev.env, then `src`.
"""
import argparse
import os
import re
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _ib  # noqa: E402

NAME, SYNONYM, PREFIX = 'АгентОтладкаHTTP', 'Агент отладки HTTP', 'Dbg_'
SERVICES = ('Dbg_Executor', 'Dbg_LogReader')

SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKILLS_DIR = os.path.dirname(SKILL_DIR)
TEMPLATE = os.path.join(SKILL_DIR, 'extension')
TOOLS = os.path.join(SKILLS_DIR, '1c-metadata-manage', 'tools')
IBCMD_RUN = os.path.join(SKILLS_DIR, '1c-ibsrv-ops', 'scripts', 'ibcmd-run.py')


def run(title, command, timeout=300):
    """Runs a step; stops the build with the tail of its output when it fails."""
    done = subprocess.run(command, capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=timeout)
    output = (done.stdout + done.stderr).strip()
    if done.returncode:
        sys.exit(f'{title}: exit {done.returncode}\n{output[-1500:]}')
    return output


def absolute(root, path):
    return path if os.path.isabs(path) else os.path.join(root, path)


def check_handlers(out):
    """Every <Handler> of a service names a function of its module.

    meta-compile names a handler «template name + method name»; a module whose functions are
    named otherwise loads without complaint and answers every request with an error.
    """
    for service in SERVICES:
        description = open(os.path.join(out, 'HTTPServices', service + '.xml'), encoding='utf-8-sig').read()
        module = open(os.path.join(out, 'HTTPServices', service, 'Ext', 'Module.bsl'), encoding='utf-8-sig').read()
        handlers = re.findall(r'<Handler>([^<]+)</Handler>', description)
        if not handlers:
            sys.exit(f'{service}: the description has no <Handler>')
        for handler in handlers:
            if not re.search(rf'^\s*Функция\s+{re.escape(handler)}\s*\(', module, re.MULTILINE | re.IGNORECASE):
                sys.exit(f'{service}: handler {handler} is not a function of the module')


def build(out, config):
    if not os.path.isfile(os.path.join(config, 'Configuration.xml')):
        sys.exit(f'No Configuration.xml in {config}: pass --config with the main configuration sources')
    if os.path.exists(out):
        # The directory is regenerated whole; refuse anything that does not look like an earlier build.
        existing = os.path.join(out, 'Configuration.xml')
        if not os.path.isfile(existing) or f'<Name>{NAME}</Name>' not in open(existing, encoding='utf-8-sig').read():
            sys.exit(f'{out} exists and is not a build of {NAME}: choose another --out')
        shutil.rmtree(out)

    print(f'1. Scaffold bound to {config}', flush=True)
    run('cfe-init', ['python3', os.path.join(TOOLS, '1c-cfe-manage', 'scripts', 'cfe-init.py'),
                     '-Name', NAME, '-Synonym', SYNONYM, '-NamePrefix', PREFIX, '-Purpose', 'AddOn',
                     '-ConfigPath', config, '-NoRole', '-OutputDir', out])

    print('2. HTTP services from the template', flush=True)
    for service in SERVICES:
        run(f'meta-compile {service}', ['python3', os.path.join(TOOLS, '1c-meta-compile', 'scripts', 'meta-compile.py'),
                                        '-JsonPath', os.path.join(TEMPLATE, service + '.json'), '-OutputDir', out])
        module = os.path.join(out, 'HTTPServices', service, 'Ext', 'Module.bsl')
        os.makedirs(os.path.dirname(module), exist_ok=True)
        shutil.copy(os.path.join(TEMPLATE, service + '.bsl'), module)
    check_handlers(out)

    print('3. Validation', flush=True)
    print('   ' + run('cfe-validate', ['python3', os.path.join(TOOLS, '1c-cfe-manage', 'scripts', 'cfe-validate.py'),
                                        '-ExtensionPath', out]).splitlines()[-1])


def ibcmd(title, *arguments):
    """ibcmd through the wrapper of 1c-ibsrv-ops; its output is printed, the verdict is the exit code."""
    print('   ' + run(title, ['python3', IBCMD_RUN, *arguments], timeout=1900).replace('\n', '\n   '))


def load(env, out):
    if not env.get('IBSRV_DIR'):
        sys.exit('--load works through the standalone server (IBSRV_DIR is empty in .dev.env). Load the '
                 f'extension {NAME} from {out} with db-load-xml of 1c-metadata-manage, then turn its safe '
                 'mode off — docs/debug-extension.md')
    print('4. Loading into the test infobase', flush=True)
    ibcmd('import', 'infobase', 'config', 'import', f'--extension={NAME}', out)
    ibcmd('safe mode', 'infobase', 'config', 'extension', 'update', f'--name={NAME}', '--safe-mode=no')
    ibcmd('apply', 'infobase', 'config', 'apply', f'--extension={NAME}', '--force', '--dynamic=disable',
          '--session-terminate=force', '--session-terminate-message=обновление тестовой базы')


parser = argparse.ArgumentParser()
parser.add_argument('--out', default=os.path.join('tmp', NAME))
parser.add_argument('--config')
parser.add_argument('--load', action='store_true')
args = parser.parse_args()

root = _ib.project_root()
env = _ib.dev_env(root)
out = absolute(root, args.out)
build(out, absolute(root, args.config or env.get('EXPORT_PATH') or 'src'))
if args.load:
    load(env, out)
    print(f'\nLoaded {NAME}. Check it: check-services.py; a 404 means the publication does not name the '
          'services, or web sessions still hold the old metadata (ibsrv.py restart).')
else:
    print(f'\nBuilt {NAME} in {out}. Not loaded: repeat with --load once the user agrees.')
