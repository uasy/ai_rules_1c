#!/usr/bin/env python3
# db-check v1.0 — Designer batch check ladder: CheckModules, CheckCanApplyConfigurationExtensions, CheckConfig
# 1c-rules: local tool, not vendored; canon — content/rules/designer-batch-checks.md.
# The .ps1 peer mirrors it (NOTICE.md).

import argparse
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "..", "_common"))
import dev_env  # noqa: E402
import platform_args  # noqa: E402


def _find_project_v8path():
    """Walk up from CWD to find .v8-project.json and read its v8path."""
    d = os.getcwd()
    while True:
        pf = os.path.join(d, ".v8-project.json")
        if os.path.isfile(pf):
            try:
                with open(pf, encoding="utf-8-sig") as f:
                    data = json.load(f)
                v = data.get("v8path")
                if v:
                    return v
            except Exception:
                pass
            return None
        parent = os.path.dirname(d)
        if parent == d:
            return None
        d = parent


def _version_dir(p):
    """Version dir for both Windows (.../1cv8/<ver>/bin/1cv8.exe) and *nix (.../1cv8/<ver>/1cv8)."""
    parent = os.path.dirname(p)
    if os.path.basename(parent).lower() == "bin":
        parent = os.path.dirname(parent)
    return os.path.basename(parent)


def _version_key(p):
    """Numeric sort key from version dir name."""
    return [int(x) for x in re.findall(r"\d+", _version_dir(p))]


def resolve_v8path(v8path):
    """Resolve path to 1cv8 (.dev.env PLATFORM_PATH → .v8-project.json → newest installed)."""
    if not v8path:
        v8path = dev_env.get_value('PLATFORM_PATH') or _find_project_v8path()
    if not v8path:
        if os.name == "nt":
            candidates = (
                glob.glob(r"C:\Program Files\1cv8\*\bin\1cv8.exe")
                + glob.glob(r"C:\Program Files (x86)\1cv8\*\bin\1cv8.exe")
            )
        else:
            candidates = glob.glob("/opt/1cv8/*/*/1cv8") + glob.glob("/opt/1cv8/*/1cv8")
        if candidates:
            v8path = max(candidates, key=_version_key)
            print(f"Auto-selected platform {_version_dir(v8path)}: {v8path}")
        else:
            print("Error: 1C executable not found. Specify -V8Path", file=sys.stderr)
            sys.exit(1)
    if os.path.isdir(v8path):
        exe = "1cv8.exe" if os.name == "nt" else "1cv8"
        candidate = os.path.join(v8path, exe)
        if not os.path.isfile(candidate):
            candidate = os.path.join(v8path, "bin", exe)
        v8path = candidate
    if not os.path.isfile(v8path):
        print(f"Error: 1C executable not found at {v8path}", file=sys.stderr)
        sys.exit(1)
    return v8path


# --- Checks of the ladder, cheapest first (designer-batch-checks.md → The check ladder) ---
CHECKS = {
    "Modules": "/CheckModules",
    "Apply": "/CheckCanApplyConfigurationExtensions",
    "Config": "/CheckConfig",
}
DEFAULT_MODULE_MODES = "ThinClient,Server,ExternalConnection"
DEFAULT_CONFIG_MODES = ("ConfigLogIntegrity,IncorrectReferences,ThinClient,Server,"
                        "ExternalConnection,HandlersExistence,ExtendedModulesCheck")
CHECK_KEYS = ["/CheckModules", "/CheckCanApplyConfigurationExtensions", "/CheckConfig",
              "/DumpResult"]

# designer-batch-checks.md → The success-phrase trap: neutralize exact success fragments
# first, then any remaining diagnostic stem fails the line.
SUCCESS_FRAGMENTS = re.compile(
    r"(ошибок|предупреждений)\s+не\s+обнаружено|(ошибок|предупреждений)\s*:\s*0(?!\d)"
    r"|errors\s+were\s+not\s+found|(?<!\d)0\s+errors?\b",
    re.IGNORECASE)
DIAGNOSTIC_STEMS = re.compile(
    r"ошибк|ошибок|ошибочн|предупрежден|не найден метод|не может быть применен|невозможно|"
    r"отсутствует обработчик|не совпадает"
    r"|\berror|\bfatal|\bfailed|\bfailure|\bexception",
    re.IGNORECASE)


def diagnostic_lines(text):
    """Log lines that still carry a diagnostic after success fragments are removed."""
    found = []
    for line in text.splitlines():
        rest = SUCCESS_FRAGMENTS.sub(" ", line)
        if DIAGNOSTIC_STEMS.search(rest):
            found.append(line)
    return found


def modes(value, param_name):
    keys = [m.strip().lstrip("-") for m in value.split(",") if m.strip()]
    if not keys:
        print(f"Error: {param_name} is empty", file=sys.stderr)
        sys.exit(1)
    return ["-" + k for k in keys]


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(
        description="Designer batch check ladder on the LOADED configuration / extension: "
                    "CheckModules, CheckCanApplyConfigurationExtensions, CheckConfig. "
                    "Read-only; stops at the first failing check.",
        allow_abbrev=False,
    )
    parser.add_argument("-V8Path", default="")
    parser.add_argument("-InfoBasePath", default="")
    parser.add_argument("-InfoBaseServer", default="")
    parser.add_argument("-InfoBaseRef", default="")
    parser.add_argument("-UserName", default="")
    parser.add_argument("-Password", default="")
    parser.add_argument("-Extension", default="",
                        help="Check this extension instead of the main configuration")
    parser.add_argument("-Checks", default="",
                        help="Comma-separated subset in ladder order: Modules, Apply, Config. "
                             "Default: Modules,Apply,Config with -Extension, Modules,Config without")
    parser.add_argument("-ModuleModes", default=DEFAULT_MODULE_MODES,
                        help=f"/CheckModules mode keys (default {DEFAULT_MODULE_MODES})")
    parser.add_argument("-ConfigModes", default=DEFAULT_CONFIG_MODES,
                        help=f"/CheckConfig mode keys (default {DEFAULT_CONFIG_MODES})")
    parser.add_argument("-ContinueOnFailure", action="store_true",
                        help="Run the remaining checks after a failure (default: stop at the first)")
    parser.add_argument("-TimeoutSeconds", type=int, default=3600,
                        help="Per-check timeout; a Designer waiting on a modal dialog never exits")
    parser.add_argument("-AdditionalV8Arguments", action="append", default=[],
                        help="Extra 1cv8 arguments (comma-separated or repeated). "
                             "A value starting with '-' needs the -Flag=value form.")
    args = parser.parse_args()

    v8path = resolve_v8path(args.V8Path)
    if os.path.basename(v8path).lower().startswith("ibcmd"):
        print("Error: db-check needs 1cv8 (Designer). ibcmd has no /CheckModules or applicability "
              "check — `ibcmd config check` validates metadata only and passes an extension that "
              "/CheckCanApplyConfigurationExtensions rejects", file=sys.stderr)
        sys.exit(1)
    extra_args = platform_args.resolve_extra_args("1cv8", args.AdditionalV8Arguments, None)
    for tok in extra_args:
        for k in CHECK_KEYS:
            if platform_args.key_matches(tok, k):
                print(f"Error: {k} is controlled by db-check and cannot be passed via "
                      "-AdditionalV8Arguments", file=sys.stderr)
                sys.exit(1)

    if not args.InfoBasePath and (not args.InfoBaseServer or not args.InfoBaseRef):
        print("Error: specify -InfoBasePath or -InfoBaseServer + -InfoBaseRef", file=sys.stderr)
        sys.exit(1)

    if args.Checks:
        wanted = [c.strip() for c in args.Checks.split(",") if c.strip()]
        unknown = [c for c in wanted if c not in CHECKS]
        if unknown:
            print(f"Error: unknown check(s) {', '.join(unknown)}; use Modules, Apply, Config",
                  file=sys.stderr)
            sys.exit(1)
        checks = [c for c in CHECKS if c in wanted]  # ladder order, whatever the input order
    else:
        checks = ["Modules", "Apply", "Config"] if args.Extension else ["Modules", "Config"]
    if "Apply" in checks and not args.Extension:
        print("Error: the Apply check (/CheckCanApplyConfigurationExtensions) needs -Extension",
              file=sys.stderr)
        sys.exit(1)

    base = ["DESIGNER"]
    if args.InfoBaseServer and args.InfoBaseRef:
        base += ["/S", f"{args.InfoBaseServer}/{args.InfoBaseRef}"]
    else:
        base += ["/F", args.InfoBasePath]
    if args.UserName:
        base.append(f"/N{args.UserName}")
    if args.Password:
        base.append(f"/P{args.Password}")
    base += ["/DisableStartupDialogs", "/DisableStartupMessages"]

    target = f"extension {args.Extension}" if args.Extension else "main configuration"
    temp_dir = tempfile.mkdtemp(prefix="db_check_")
    failed_code = 0
    try:
        for check in checks:
            op = [CHECKS[check]]
            if check == "Modules":
                op += modes(args.ModuleModes, "-ModuleModes")
            elif check == "Config":
                op += modes(args.ConfigModes, "-ConfigModes")
            if args.Extension:
                op += ["-Extension", args.Extension]
            out_file = os.path.join(temp_dir, f"{check}.log")
            result_file = os.path.join(temp_dir, f"{check}.result")
            arguments = base + op + ["/Out", out_file, "/DumpResult", result_file] + extra_args
            print(f"--- {check}: {target} ---")
            print("Running: 1cv8 " + platform_args.protect_secrets(
                ' '.join(platform_args.format_args_for_display(arguments, "1cv8")),
                [args.Password, args.UserName]))
            try:
                exit_code = subprocess.run([v8path] + arguments, capture_output=True,
                                           timeout=args.TimeoutSeconds).returncode
            except subprocess.TimeoutExpired:
                exit_code = None

            dump = ""
            if os.path.isfile(result_file):
                with open(result_file, encoding="utf-8-sig", errors="replace") as f:
                    dump = re.sub(r"[^\d\-]", "", f.read())
            log = ""
            if os.path.isfile(out_file):
                with open(out_file, encoding="utf-8-sig", errors="replace") as f:
                    log = f.read().strip()
            diagnostics = diagnostic_lines(log)

            # Three signals: exit code, /DumpResult, diagnostic text (designer-batch-checks.md).
            reasons = []
            if exit_code is None:
                reasons.append(f"timed out after {args.TimeoutSeconds} s (base busy or a modal dialog)")
            elif exit_code != 0:
                reasons.append(f"exit code {exit_code}")
            if dump != "0":
                reasons.append(f"/DumpResult {dump}" if dump else "/DumpResult not written")
            if diagnostics:
                reasons.append(f"{len(diagnostics)} diagnostic line(s)")

            if reasons:
                print(f"[{check}] FAILED: {'; '.join(reasons)}")
                if not failed_code:
                    failed_code = int(dump) if dump.lstrip("-").isdigit() and dump != "0" else 1
            else:
                print(f"[{check}] passed")
            if log:
                print("--- Log ---")
                print(log)
                print("--- End ---")
            if reasons and not args.ContinueOnFailure:
                rest = checks[checks.index(check) + 1:]
                if rest:
                    print(f"Stopped at the first failure; not run: {', '.join(rest)}")
                break
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)

    sys.exit(failed_code)


if __name__ == "__main__":
    main()
