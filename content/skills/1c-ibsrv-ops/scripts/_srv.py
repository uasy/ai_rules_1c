"""Shared helpers of the 1c-ibsrv-ops scripts: project settings, the server process, ibcmd on a pty.

The reading of `.dev.env` is repeated here on purpose: a skill has to work when it is installed
alone, and the parser is ten lines of `key=value`.
"""
import os
import subprocess
import sys
import time


def project_root():
    """Nearest ancestor of the working directory that holds .dev.env."""
    directory = os.getcwd()
    while True:
        if os.path.isfile(os.path.join(directory, '.dev.env')):
            return directory
        parent = os.path.dirname(directory)
        if parent == directory:
            print('No .dev.env found: run from the project directory', file=sys.stderr)
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


def server_dir(env, root=None):
    """IBSRV_DIR — the infobase directory a standalone server is raised over.

    The server keeps its own `server.yml` and `data` there, next to the database. An empty value
    means there is nothing to start: a file infobase worked with directly, or an external cluster.
    """
    value = env.get('IBSRV_DIR', '').strip()
    if not value:
        return ''
    return value if os.path.isabs(value) else os.path.join(root or project_root(), value)


def server_pid(env, root=None):
    """PID of the standalone server of IBSRV_DIR, empty string when it is not running.

    The process is matched by its name and its data directory — a `pgrep -f` over a path also
    matches the shell that runs it.
    """
    directory = server_dir(env, root)
    if not directory:
        return ''
    # Matched against the whole argument: one infobase directory can be a prefix of another
    # (`…/base` and `…/base-tests`), and a substring search then returns the wrong server.
    wanted = {f'--data={directory}/data', f'--data={directory}/data/', f'--data={directory}'}
    for pid in subprocess.run(['pgrep', '-x', 'ibsrv'], capture_output=True, text=True).stdout.split():
        try:
            arguments = open(f'/proc/{pid}/cmdline', 'rb').read().decode().split('\0')
        except OSError:
            continue
        if wanted & set(arguments):
            return pid
    return ''


class Output(str):
    """Output of ibcmd; `code` is its exit status, -1 when the run was cut short."""

    code = 0


def ibcmd_pty(arguments, env, timeout=120):
    """Runs ibcmd on a pty, answering its credential prompts from .dev.env.

    Modes that act on the server as a whole (`session`, `lock`) have no --user / --password of
    their own and read the console directly, so a plain pipe fails with «Invalid seek». The rest
    would take credentials on the command line, where they do not belong.

    Reading goes on until ibcmd exits or the timeout runs out: a silence is not the end of the
    work — an import writes nothing while it loads. A run that outlives its timeout is killed
    rather than left behind holding the infobase.
    """
    import pty
    import select
    import signal

    executable = env['PLATFORM_PATH'].rstrip('/') + '/ibcmd'
    pid, handle = pty.fork()
    if pid == 0:
        os.execv(executable, [executable] + list(arguments))
    buffer, answered, note = b'', 0, ''
    deadline = time.time() + timeout
    while time.time() < deadline:
        ready, _, _ = select.select([handle], [], [], 2)
        if not ready:
            continue
        try:
            chunk = os.read(handle, 4096)
        except OSError:
            break
        if not chunk:
            break
        buffer += chunk
        text = buffer.decode('utf-8', 'replace')
        if answered == 0 and 'Имя пользователя' in text:
            os.write(handle, (env.get('IB_USER', '') + '\n').encode())
            answered = 1
        elif answered == 1 and 'ароль' in text.split('Имя пользователя')[-1]:
            os.write(handle, (env.get('IB_PASSWORD', '') + '\n').encode())
            answered = 2
        elif answered == 2 and text.count('Имя пользователя') > 1:
            note = '\n[ERROR] ibcmd asks for the user name again — IB_USER / IB_PASSWORD were not accepted'
            break
    else:
        note = f'\n[ERROR] ibcmd did not finish within {timeout}s and was killed'
    if note:
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    os.close(handle)
    status = os.waitpid(pid, 0)[1]
    text = buffer.decode('utf-8', 'replace') + note
    # The pty echoes what is typed into it, so some modes print the password back.
    password = env.get('IB_PASSWORD', '')
    result = Output(text.replace(password, '***') if password else text)
    result.code = -1 if note else os.waitstatus_to_exitcode(status)
    return result
