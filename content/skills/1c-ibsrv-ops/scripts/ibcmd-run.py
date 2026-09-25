"""Any ibcmd command against the standalone server of this project.

`ibcmd --pid=$(pgrep -x ibsrv) …` breaks on a real project twice over: an infobase with users
asks for credentials on the terminal and waits there forever, and a second server (a base of a
test manager, for instance) makes `pgrep` return two pids. This wrapper takes the pid from the
data directory of IBSRV_DIR and answers the prompts from .dev.env, so only the mode is typed.

Usage: ibcmd-run.py [--timeout <seconds>] [--offline] <ibcmd arguments...>

  --timeout   default 1800; ibcmd is killed when it expires
  --offline   for a stopped server: --config / --data of IBSRV_DIR instead of --pid

Examples:
  ibcmd-run.py infobase config import src
  ibcmd-run.py infobase config apply --force --dynamic=disable --session-terminate=force
  ibcmd-run.py --offline infobase config repair --rollback
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _srv  # noqa: E402


def parse(argv):
    """Own options before the ibcmd arguments; the first unknown word starts the ibcmd command."""
    timeout, offline = 1800, False
    while argv and argv[0].startswith('--') and argv[0] in ('--timeout', '--offline'):
        option = argv.pop(0)
        if option == '--offline':
            offline = True
        else:
            if not argv:
                sys.exit('--timeout without a value')
            timeout = int(argv.pop(0))
    if not argv:
        sys.exit(__doc__)
    return timeout, offline, argv


def address(arguments, env, offline):
    """The arguments with the addressing of this project's server put in front of the options."""
    directory = _srv.server_dir(env)
    if not directory:
        sys.exit('IBSRV_DIR is not set in .dev.env: the project has no standalone server')
    running = _srv.server_pid(env)
    if offline:
        if running:
            sys.exit(f'The server is running (pid {running}): stop it — ibsrv.py stop')
        placed = [f'--config={directory}/server.yml', f'--data={directory}/data']
    else:
        if not running:
            sys.exit('The server is not running: start it (ibsrv.py start) or pass --offline')
        return [f'--pid={running}'] + arguments
    position = next((i for i, word in enumerate(arguments) if word.startswith('-')), len(arguments))
    return arguments[:position] + placed + arguments[position:]


def main():
    timeout, offline, arguments = parse(sys.argv[1:])
    env = _srv.dev_env()
    output = _srv.ibcmd_pty(address(arguments, env, offline), env, timeout)
    print(output.strip())
    return output.code


if __name__ == '__main__':
    sys.exit(main())
