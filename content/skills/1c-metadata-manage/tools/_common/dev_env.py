"""dev_env — read project settings from `.dev.env` (Python twin of DevEnv.ps1).

In the 1c-rules toolkit `.dev.env` at the project root is the single source of
truth for project parameters. The vendored cc-1c-skills scripts natively read
`.v8-project.json`; the twins consult this helper first, so a project only ever
maintains `.dev.env`.

Never raises: a malformed `.dev.env` must not break a metadata operation — every
lookup degrades to "" / [] and the caller falls through to its own next source.
"""

import os
import re

_ASSIGN = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$")


def find_dev_env_file(start_dir=None):
    """Nearest `.dev.env` walking up from `start_dir` (default: CWD).

    Mirrors the `.v8-project.json` lookup it complements, including its 20-level
    walk limit. Returns None when absent.
    """
    d = start_dir or os.getcwd()
    for _ in range(20):
        if not d:
            break
        candidate = os.path.join(d, ".dev.env")
        if os.path.isfile(candidate):
            return candidate
        parent = os.path.dirname(d)
        if not parent or parent == d:
            break
        d = parent
    return None


def get_value(name, start_dir=None):
    """Single KEY value from `.dev.env`; "" when file, key or value is missing."""
    try:
        path = find_dev_env_file(start_dir)
        if not path:
            return ""
        with open(path, encoding="utf-8-sig", errors="replace") as f:
            for line in f:
                trimmed = line.strip()
                if not trimmed or trimmed.startswith("#"):
                    continue
                m = _ASSIGN.match(trimmed)
                if not m or m.group(1) != name:
                    continue
                val = m.group(2).strip()
                # Quoted paths must still resolve: PLATFORM_PATH="/opt/1cv8".
                if len(val) >= 2 and val[0] == val[-1] and val[0] in ('"', "'"):
                    val = val[1:-1].strip()
                return val
    except Exception:
        pass
    return ""


def get_args(name, start_dir=None):
    """Comma-separated argument list (PLATFORM_ARGS / IBCMD_ARGS) as a list.

    Empty list when unset — same contract as the `.v8-project.json`
    v8args / ibcmdargs lookup this shadows.
    """
    raw = get_value(name, start_dir)
    if not raw:
        return []
    return [tok.strip() for tok in raw.split(",") if tok.strip()]
