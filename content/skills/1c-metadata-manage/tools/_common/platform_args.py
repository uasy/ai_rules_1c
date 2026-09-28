"""platform_args — extra 1cv8 / ibcmd arguments (Python twin of the
"Additional platform arguments" block shared by the db-ops / epf scripts).

Sources, in precedence order:
  1. `.dev.env` PLATFORM_ARGS / IBCMD_ARGS  (1c-rules single source of truth)
  2. `.v8-project.json` v8args / ibcmdargs  (legacy fallback)
  3. the caller's -AdditionalV8Arguments / -AdditionalIbcmdArguments

Keys the skill drives itself are rejected: the platform accepts only one batch
operation, and a duplicate connection or output key fails with an opaque 1C
error that is far harder to diagnose than an explicit refusal here.
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dev_env  # noqa: E402

V8_OWNED_KEYS = [
    "DESIGNER", "ENTERPRISE", "CREATEINFOBASE", "CONFIG",
    "/F", "/S", "/N", "/P", "/Out", "/DisableStartupDialogs",
    "/UseTemplate", "/AddToList", "/Execute", "/C", "/URL", "/UC",
    "/DumpIB", "/RestoreIB", "/DumpCfg", "/LoadCfg",
    "/DumpConfigToFiles", "/LoadConfigFromFiles", "/UpdateDBCfg",
    "/DumpExternalDataProcessorOrReportToFiles",
    "/LoadExternalDataProcessorOrReportFromFiles",
]
IBCMD_OWNED_KEYS = [
    "--db-path", "--data", "--out", "--file", "--load", "--restore",
    "--import", "--export", "--apply", "--force", "--create-database",
    "--user", "--password",
]
V8_SECRET_KEYS = ["/P", "/UC", "/WSP", "/AWSP"]
IBCMD_SECRET_KEYS = ["--password", "--token", "--db-pwd"]


def _fail(message):
    print("Error: " + message, file=sys.stderr)
    sys.exit(1)


def key_matches(token, key):
    """True when `token` is `key`, or starts with it and the next character is
    not a letter — catches glued /N"user" and --password=x, while keeping
    /ClearCache distinct from /C."""
    if len(token) < len(key):
        return False
    if token[:len(key)].lower() != key.lower():
        return False
    if len(token) == len(key):
        return True
    return not token[len(key)].isalpha()


def project_extra_args(name, start_dir=None):
    """v8args / ibcmdargs — `.dev.env` first, then `.v8-project.json` (same
    upward walk as the v8path lookup)."""
    env_key = "IBCMD_ARGS" if name == "ibcmdargs" else "PLATFORM_ARGS"
    from_env = dev_env.get_args(env_key, start_dir)
    if from_env:
        return from_env
    d = start_dir or os.getcwd()
    while True:
        pf = os.path.join(d, ".v8-project.json")
        if os.path.isfile(pf):
            try:
                with open(pf, encoding="utf-8-sig") as f:
                    data = json.load(f)
                vals = data.get(name)
                if vals:
                    return [str(v) for v in vals]
            except Exception:
                pass
            return []
        parent = os.path.dirname(d)
        if not parent or parent == d:
            return []
        d = parent


def assert_extra_args(extra_args, engine, hints=None):
    param_name = ("-AdditionalIbcmdArguments" if engine == "ibcmd"
                  else "-AdditionalV8Arguments")
    owned = IBCMD_OWNED_KEYS if engine == "ibcmd" else V8_OWNED_KEYS
    for tok in extra_args:
        if engine == "ibcmd" and not tok.startswith("-"):
            _fail("'%s' is a positional token - pass values as --key=value "
                  "(%s cannot extend the ibcmd command)" % (tok, param_name))
        for k in owned:
            if key_matches(tok, k):
                hint = ""
                if hints and k in hints:
                    hint = " (use %s)" % hints[k]
                _fail("%s is controlled by the skill and cannot be passed via %s%s"
                      % (k, param_name, hint))


def _split_list(values):
    # Callers may pass the repo's comma-separated convention or repeat the flag.
    # A value containing a comma is not supported (same limitation as the .ps1).
    out = []
    for v in values or []:
        out.extend(tok for tok in str(v).split(",") if tok != "")
    return out


def resolve_extra_args(engine, v8_extra=None, ibcmd_extra=None, hints=None,
                       start_dir=None):
    """Pick and validate the argument list for the selected engine.

    Passing the other engine's parameter explicitly is an error; the same keys
    coming from `.dev.env` / `.v8-project.json` simply do not apply, because a
    project may describe both engines.
    """
    v8_extra = _split_list(v8_extra)
    ibcmd_extra = _split_list(ibcmd_extra)
    if engine == "ibcmd" and v8_extra:
        _fail("-AdditionalV8Arguments applies to 1cv8 only; the selected "
              "engine is ibcmd (use -AdditionalIbcmdArguments)")
    if engine != "ibcmd" and ibcmd_extra:
        _fail("-AdditionalIbcmdArguments applies to ibcmd only; the selected "
              "engine is 1cv8 (use -AdditionalV8Arguments)")
    if engine == "ibcmd":
        extra = project_extra_args("ibcmdargs", start_dir) + ibcmd_extra
    else:
        extra = project_extra_args("v8args", start_dir) + v8_extra
    if extra:
        assert_extra_args(extra, engine, hints)
    return extra


def format_args_for_display(arg_list, engine):
    """Redact values of secret-prone keys in glued, =-joined and separate forms.

    Matching is a plain prefix (no letter rule): over-masking costs nothing,
    a leaked password does.
    """
    keys = IBCMD_SECRET_KEYS if engine == "ibcmd" else V8_SECRET_KEYS
    res = []
    mask_next = False
    for tok in arg_list:
        if mask_next:
            res.append("***")
            mask_next = False
            continue
        hit = None
        for k in keys:
            if len(tok) >= len(k) and tok[:len(k)].lower() == k.lower():
                hit = k
                break
        if not hit:
            res.append(tok)
        elif len(tok) == len(hit):
            res.append(tok)
            mask_next = True
        elif tok[len(hit)] == "=":
            res.append(hit + "=***")
        else:
            res.append(hit + "***")
    return res


def clean_path(value, param_name):
    """Forgive what is unambiguous in a caller-supplied path: surrounding
    whitespace, surrounding quotes that survived shell parsing, a trailing
    separator. A quote left inside afterwards cannot be part of a real path -
    reject it by name instead of letting 1C answer with its opaque
    "Неверные или отсутствующие параметры соединения"."""
    if not value:
        return value
    v = value.strip()
    if len(v) >= 2 and v[0] == v[-1] and v[0] in ('"', "'"):
        v = v[1:-1].strip()
    if len(v) > 3 and v[-1] in ("\\", "/"):
        v = v[:-1]
    if '"' in v:
        _fail("%s contains a quote character: %s" % (param_name, value))
    return v


def protect_secrets(text, secrets):
    """Redact literal secret values from a display string (plain substring
    replacement, not a regex) — masks a password that reached the command line
    as a bare value rather than as a recognised key."""
    for s in secrets or []:
        if s:
            text = text.replace(s, "***")
    return text


# --- 1cv8 batch verdict and output postconditions ---------------------------
# Python twin of the verdict block of the db-* / epf-* scripts (canon:
# content/rules/designer-batch-checks.md -> The verdict is three signals).

def batch_verdict(exit_code, result_file):
    """Exit code after the platform's own verdict: /DumpResult writes 0 on success,
    and a batch command can fail while 1cv8 exits 0. Read it before trusting the
    exit code."""
    if exit_code != 0:
        return exit_code
    dump_code = ""
    try:
        with open(result_file, "r", encoding="utf-8-sig", errors="replace") as handle:
            dump_code = "".join(ch for ch in handle.read() if ch.isdigit() or ch == "-")
    except OSError:
        pass
    if dump_code == "0":
        return 0
    if dump_code:
        print(f"[error] batch result {dump_code} reported by /DumpResult (0 = success)", file=sys.stderr)
    else:
        print("[error] /DumpResult wrote no result - the batch command did not complete", file=sys.stderr)
    return 1


def output_file_non_empty(path):
    """Postcondition: the platform must have produced a non-empty output file.
    Exit code 0 without it (broken/headless env) is a false success."""
    try:
        return os.path.isfile(path) and os.path.getsize(path) > 0
    except OSError:
        return False


def output_dir_non_empty(path):
    """Postcondition: the platform must have written files into the output directory.
    Exit code 0 with an empty dir (broken/headless env) is a false success."""
    try:
        return os.path.isdir(path) and any(True for _ in os.scandir(path))
    except OSError:
        return False


# --- ibcmd: DBMS infobase and working directories ---------------------------
# ibcmd reaches a file infobase (--db-path) or a DBMS infobase directly, without
# a 1C cluster. The keys below are driven by -Dbms / -DbServer / -DbName /
# -DbUser / -DbPassword / -Locale / -IbcmdDataPath / -IbcmdTempPath, so they are
# refused in the extra arguments of the scripts that take those parameters.

IBCMD_DBMS_KINDS = ["PostgreSQL", "MSSQLServer", "IBMDB2", "OracleDatabase"]
IBCMD_CONNECTION_KEYS = [
    "--dbms", "--database-server", "--db-server", "--database-name", "--db-name",
    "--database-user", "--db-user", "--database-password", "--db-pwd",
    "--locale", "--temp",
]


def add_ibcmd_connection_arguments(parser, with_locale=True):
    """Register the ibcmd DBMS / working-directory parameters on an argparse parser.
    with_locale=False leaves -Locale out (a tool that never creates an infobase)."""
    parser.add_argument("-Dbms", default="", choices=[""] + IBCMD_DBMS_KINDS,
                        help="ibcmd only: DBMS of the infobase (omit for a file infobase)")
    parser.add_argument("-DbServer", default="",
                        help="ibcmd only: DBMS server; a non-default PostgreSQL port "
                             "goes as 'host port=5433'")
    parser.add_argument("-DbName", default="", help="ibcmd only: database name")
    parser.add_argument("-DbUser", default="", help="ibcmd only: DBMS user")
    parser.add_argument("-DbPassword", default="", help="ibcmd only: DBMS user password")
    if with_locale:
        parser.add_argument("-Locale", default="",
                            help="locale of the new infobase, e.g. ru_RU (default: the locale "
                                 "of the process environment, which a DBMS may reject)")
    parser.add_argument("-IbcmdDataPath", default="",
                        help="ibcmd only: server data directory (--data); default is a "
                             "fresh temporary directory. Must support file renames — "
                             "not a VirtualBox shared folder")
    parser.add_argument("-IbcmdTempPath", default="",
                        help="ibcmd only: temporary files directory (--temp); large DT "
                             "loads write multi-GB files here")


def ibcmd_connection(args, engine, extra_args, locale_for_1cv8=False):
    """Validate the ibcmd connection parameters and return
    (connection_keys, is_dbms, secrets).

    connection_keys is either [--db-path=...] or the --dbms/--db-* set; the
    caller adds --data / --temp through ibcmd_work_dirs(). locale_for_1cv8 lets
    a caller that also passes -Locale to 1cv8 (db-create) accept it there.
    """
    dbms_given = any([args.Dbms, args.DbServer, args.DbName, args.DbUser,
                      args.DbPassword])
    locale = getattr(args, "Locale", "")
    ibcmd_only = dbms_given or any([args.IbcmdDataPath, args.IbcmdTempPath]) or (
        bool(locale) and not locale_for_1cv8)
    if engine != "ibcmd":
        if ibcmd_only:
            _fail("-Dbms / -DbServer / -DbName / -DbUser / -DbPassword / -IbcmdDataPath / "
                  "-IbcmdTempPath%s apply to ibcmd only; point -V8Path at ibcmd (a DBMS "
                  "infobase under 1cv8 goes through -InfoBaseServer + -InfoBaseRef)"
                  % ("" if locale_for_1cv8 or not hasattr(args, "Locale") else " / -Locale"))
        return [], False, []
    for tok in extra_args:
        for k in IBCMD_CONNECTION_KEYS:
            if key_matches(tok, k):
                _fail("%s is controlled by the skill and cannot be passed via "
                      "-AdditionalIbcmdArguments (use the matching -Db* / -Locale / "
                      "-Ibcmd*Path parameter)" % k)
    if dbms_given:
        if args.InfoBasePath:
            _fail("specify either -InfoBasePath (file infobase) or -Dbms + -DbServer + "
                  "-DbName (DBMS infobase), not both")
        if not (args.Dbms and args.DbServer and args.DbName):
            _fail("a DBMS infobase needs -Dbms, -DbServer and -DbName")
        keys = ["--dbms=%s" % args.Dbms, "--db-server=%s" % args.DbServer,
                "--db-name=%s" % args.DbName]
        if args.DbUser:
            keys.append("--db-user=%s" % args.DbUser)
        if args.DbPassword:
            keys.append("--db-pwd=%s" % args.DbPassword)
        return keys, True, [args.DbPassword]
    if not args.InfoBasePath:
        _fail("ibcmd needs -InfoBasePath (file infobase) or -Dbms + -DbServer + "
              "-DbName (DBMS infobase)")
    return ["--db-path=%s" % args.InfoBasePath], False, []


def ibcmd_work_dirs(args, make_temp_dir):
    """--data (caller-given or a fresh temporary directory from make_temp_dir())
    and, when given, --temp."""
    data = args.IbcmdDataPath or make_temp_dir()
    keys = ["--data=%s" % data]
    if args.IbcmdTempPath:
        keys.append("--temp=%s" % args.IbcmdTempPath)
    return keys
