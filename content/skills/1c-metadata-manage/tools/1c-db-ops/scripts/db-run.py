#!/usr/bin/env python3
# db-run v1.7 — Launch 1C:Enterprise
# Licence and attribution: NOTICE.md of the 1c-metadata-manage skill.
#
# Deviation from db-run.ps1 (py twin only): three opt-in flags the PowerShell twin does not have.
#   -Out <file>  passes /Out. In batch startup mode (/DisableStartupDialogs, always
#                added below) the platform writes startup errors ONLY to this file —
#                without it a failed /Execute run is completely silent.
#   -Wait        waits for the client to exit and propagates its exit code, instead
#                of the default fire-and-forget Popen. The default (no -Wait) is
#                unchanged: launch and return 0 immediately.
#   -ClientKind thick|thin  chooses the executable: thick (1cv8, the default and the upstream
#                behaviour) or thin (1cv8c). A thick client cannot connect to a standalone server
#                (ibsrv) at all — it looks for a cluster at the address and reports «не является
#                адресом кластера» — so without this flag a served test infobase is unreachable
#                through this tool.
# None of the flags changes behaviour unless passed, so existing callers are unaffected.

import argparse
import glob
import json
import os
import re
import subprocess
import sys

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


def resolve_v8path(v8path, client_kind="thick"):
    """Resolve path to a 1C executable (1cv8; ibcmd only when given explicitly).

    1c-rules extension over the upstream algorithm: `client_kind="thin"` resolves the thin client
    (`1cv8c`) instead of the thick one. A thick client cannot connect to a standalone server at
    all, so without this the tool has no way to reach one.
    """
    if not v8path:
        # 1c-rules: .dev.env is the single source of truth and wins over
        # .v8-project.json, which stays supported as the legacy fallback.
        v8path = dev_env.get_value('PLATFORM_PATH') or _find_project_v8path()
    if not v8path:
        if os.name == "nt":
            candidates = (
                glob.glob(r"C:\Program Files\1cv8\*\bin\1cv8.exe")
                + glob.glob(r"C:\Program Files (x86)\1cv8\*\bin\1cv8.exe")
            )
        else:
            # PY-only: PS-порт на *nix не исполняется, поэтому *nix-раскладки нет в .ps1.
            candidates = glob.glob("/opt/1cv8/*/*/1cv8") + glob.glob("/opt/1cv8/*/1cv8")
            # Real Linux packages install to /opt/1cv8/<arch>/<ver>/1cv8 (two levels,
            # e.g. /opt/1cv8/x86_64/8.3.27.2074/1cv8) — the single-level glob below is
            # kept only as a fallback for a non-standard flat layout.
        if candidates:
            v8path = max(candidates, key=_version_key)
            print(f"Auto-selected platform {_version_dir(v8path)}: {v8path}")
        else:
            print("Error: 1C executable not found. Specify -V8Path", file=sys.stderr)
            sys.exit(1)
    if os.path.isdir(v8path):
        # PY-only: на *nix исполняемый называется "1cv8" (без .exe); ibcmd — только явным путём.
        # 1c-rules extension: тонкий клиент — "1cv8c" рядом с "1cv8".
        base = "1cv8c" if client_kind == "thin" else "1cv8"
        exe = f"{base}.exe" if os.name == "nt" else base
        v8path = os.path.join(v8path, exe)
    if not os.path.isfile(v8path):
        print(f"Error: 1C executable not found at {v8path}", file=sys.stderr)
        sys.exit(1)
    return v8path


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(
        description="Launch 1C:Enterprise",
        allow_abbrev=False,
    )
    parser.add_argument("-V8Path", default="")
    # 1c-rules extension over the upstream algorithm: which client to launch. A standalone server
    # (ibsrv) accepts the thin client only — the thick one reports «не является адресом кластера».
    parser.add_argument("-ClientKind", default="thick", choices=["thick", "thin"],
                        help="Client to launch: thick (1cv8, default) or thin (1cv8c).")
    parser.add_argument("-InfoBasePath", default="")
    parser.add_argument("-InfoBaseServer", default="")
    parser.add_argument("-InfoBaseRef", default="")
    parser.add_argument("-UserName", default="")
    parser.add_argument("-Password", default="")
    parser.add_argument("-Execute", default="")
    parser.add_argument("-CParam", default="")
    parser.add_argument("-URL", default="")
    parser.add_argument("-Out", dest="Out", default="",
                        help="Service message output file (/Out). In batch startup mode "
                             "this is the only place startup errors are reported.")
    parser.add_argument("-Wait", dest="Wait", action="store_true",
                        help="Wait for the client to exit and return its exit code.")
    parser.add_argument("-AdditionalV8Arguments", action="append", default=[],
                        help="Extra 1cv8 arguments (comma-separated or repeated). "
                             "A value starting with '-' needs the -Flag=value form.")
    parser.add_argument("-AdditionalIbcmdArguments", action="append", default=[],
                        help="Extra ibcmd arguments, --key=value form "
                             "(comma-separated or repeated). Use -Flag=value to pass them.")
    args = parser.parse_args()
    engine = "1cv8"  # this tool never dispatches to ibcmd
    extra_args = platform_args.resolve_extra_args(
        engine, args.AdditionalV8Arguments, args.AdditionalIbcmdArguments)

    v8path = resolve_v8path(args.V8Path, args.ClientKind)

    # --- Validate connection ---
    if not args.InfoBasePath and (not args.InfoBaseServer or not args.InfoBaseRef):
        print("Error: specify -InfoBasePath or -InfoBaseServer + -InfoBaseRef", file=sys.stderr)
        sys.exit(1)

    # --- Build arguments ---
    arguments = ["ENTERPRISE"]

    if args.InfoBaseServer and args.InfoBaseRef:
        arguments.extend(["/S", f"{args.InfoBaseServer}/{args.InfoBaseRef}"])
    else:
        arguments.extend(["/F", args.InfoBasePath])

    if args.UserName:
        arguments.append(f"/N{args.UserName}")
    if args.Password:
        arguments.append(f"/P{args.Password}")

    # --- Optional params ---
    execute = args.Execute
    if execute:
        ext = os.path.splitext(execute)[1].lower()
        if ext == ".erf":
            print("[WARN] /Execute does not support ERF files (external reports).")
            print(f"       Open the report via File -> Open: {execute}")
            print("       Launching database without /Execute.")
            execute = ""

    if execute:
        arguments.extend(["/Execute", execute])
    if args.CParam:
        arguments.extend(["/C", args.CParam])
    if args.URL:
        arguments.extend(["/URL", args.URL])

    if args.Out:
        arguments.extend(["/Out", args.Out])

    arguments.append("/DisableStartupDialogs")

    # --- Execute ---
    arguments = arguments + extra_args
    print(f"Running: {os.path.basename(v8path)} " + platform_args.protect_secrets(
        ' '.join(platform_args.format_args_for_display(arguments, engine)),
        [args.Password, args.UserName]))

    if not args.Wait:
        subprocess.Popen([v8path] + arguments)
        print("1C:Enterprise launched")
        return

    result = subprocess.run([v8path] + arguments)
    if result.returncode == 0:
        print("1C:Enterprise finished successfully")
    else:
        print(f"1C:Enterprise finished with code {result.returncode}", file=sys.stderr)

    # Пакетный режим пишет ошибки запуска только в /Out — показываем их сразу,
    # иначе неуспешный прогон выглядит как молчание.
    if args.Out and os.path.isfile(args.Out):
        try:
            with open(args.Out, "r", encoding="utf-8-sig") as f:
                log = f.read().strip()
        except Exception:
            log = ""
        if log:
            print("--- Out ---")
            print(log)
            print("--- End ---")
    sys.exit(result.returncode)


if __name__ == "__main__":
    main()
