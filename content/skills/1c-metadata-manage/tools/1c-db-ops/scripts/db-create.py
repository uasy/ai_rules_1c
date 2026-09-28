#!/usr/bin/env python3
# db-create v1.10 — Create 1C information base
# Licence and attribution: NOTICE.md of the 1c-metadata-manage skill.
# Local: -Locale (1cv8 and ibcmd) and -PageSize (1cv8, file infobase); the ibcmd branch also
#        creates a DBMS infobase without a 1C cluster (-Dbms / -DbServer / -DbName / -DbUser /
#        -DbPassword) and takes -IbcmdDataPath / -IbcmdTempPath. db-create.ps1 has none of this.

import argparse
import atexit
import glob
import json
import os
import random
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
    """Resolve path to a 1C executable (1cv8; ibcmd only when given explicitly)."""
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
        exe = "1cv8.exe" if os.name == "nt" else "1cv8"
        v8path = os.path.join(v8path, exe)
    if not os.path.isfile(v8path):
        print(f"Error: 1C executable not found at {v8path}", file=sys.stderr)
        sys.exit(1)
    return v8path


IBCMD_NOUSER_HINT = (
    "[ibcmd] No -UserName/-Password given; the infobase may require authentication. "
    "On Windows ibcmd reads credentials from the console (stdin is ignored), so this "
    "call may block instead of failing. If it does not return promptly, abort and "
    "re-run with -UserName and -Password.\n"
)


def run_ibcmd(cmd, has_username=False, warn_no_user=True):
    """Run an ibcmd command non-interactively.

    input="" closes stdin (EOF) so ibcmd's auth prompt fast-fails instead of hanging.
    On Windows without -UserName ibcmd reads the console directly and may still block —
    that residual case is flagged via IBCMD_NOUSER_HINT (model-facing).
    """
    if warn_no_user and os.name == "nt" and not has_username:
        sys.stderr.write(IBCMD_NOUSER_HINT)
        sys.stderr.flush()
    return subprocess.run(cmd, input="", capture_output=True, encoding="utf-8", errors="replace")


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(
        description="Create 1C information base",
        allow_abbrev=False,
    )
    parser.add_argument("-V8Path", default="")
    parser.add_argument("-InfoBasePath", default="")
    parser.add_argument("-InfoBaseServer", default="")
    parser.add_argument("-InfoBaseRef", default="")
    parser.add_argument("-UseTemplate", default="")
    parser.add_argument("-AddToList", action="store_true")
    parser.add_argument("-ListName", default="")
    parser.add_argument("-AdditionalV8Arguments", action="append", default=[],
                        help="Extra 1cv8 arguments (comma-separated or repeated). "
                             "A value starting with '-' needs the -Flag=value form.")
    parser.add_argument("-AdditionalIbcmdArguments", action="append", default=[],
                        help="Extra ibcmd arguments, --key=value form "
                             "(comma-separated or repeated). Use -Flag=value to pass them.")
    parser.add_argument("-PageSize", default="", choices=["", "4k", "8k", "16k", "32k", "64k"],
                        help="1cv8 file infobase only: page size (DBPageSize, format 8.3.8). "
                             "A larger page raises the size limit of an internal file of 1Cv8.1CD")
    platform_args.add_ibcmd_connection_arguments(parser)
    args = parser.parse_args()

    v8path = resolve_v8path(args.V8Path)
    engine = "ibcmd" if os.path.basename(v8path).lower().startswith("ibcmd") else "1cv8"
    extra_args = platform_args.resolve_extra_args(
        engine, args.AdditionalV8Arguments, args.AdditionalIbcmdArguments)

    # --- Validate connection ---
    ib_conn, is_dbms, db_secrets = platform_args.ibcmd_connection(
        args, engine, extra_args, locale_for_1cv8=True)
    if args.PageSize and (engine == "ibcmd" or not args.InfoBasePath):
        print("Error: -PageSize applies to a 1cv8 file infobase only (ibcmd infobase create has no page size)",
              file=sys.stderr)
        sys.exit(1)
    if engine != "ibcmd" and not args.InfoBasePath and (not args.InfoBaseServer or not args.InfoBaseRef):
        print("Error: specify -InfoBasePath or -InfoBaseServer + -InfoBaseRef", file=sys.stderr)
        sys.exit(1)

    # --- Validate template ---
    if args.UseTemplate and not os.path.exists(args.UseTemplate):
        print(f"Error: template file not found: {args.UseTemplate}", file=sys.stderr)
        sys.exit(1)

    # --- ibcmd branch (file or DBMS infobase, no 1C cluster) ---
    if engine == "ibcmd":
        arguments = ["infobase", "create"] + ib_conn + ["--create-database"]
        if args.Locale:
            arguments.append(f"--locale={args.Locale}")
        if args.UseTemplate:
            if os.path.splitext(args.UseTemplate)[1].lower() == ".dt":
                arguments.append(f"--restore={args.UseTemplate}")
            else:
                arguments.extend([f"--load={args.UseTemplate}", "--apply"])
        def make_data_dir():
            d = tempfile.mkdtemp(prefix="ibcmd_data_")
            atexit.register(shutil.rmtree, d, ignore_errors=True)
            return d
        arguments = arguments + platform_args.ibcmd_work_dirs(args, make_data_dir) + extra_args
        print("Running: ibcmd " + platform_args.protect_secrets(
            ' '.join(platform_args.format_args_for_display(arguments, engine)), db_secrets))
        result = run_ibcmd([v8path] + arguments, warn_no_user=False)
        if result.returncode == 0:
            target = f"{args.Dbms} {args.DbServer} / {args.DbName}" if is_dbms else args.InfoBasePath
            print(f"Information base created successfully: {target}")
        else:
            print(f"Error creating information base (code: {result.returncode})", file=sys.stderr)
        if result.stdout:
            print(result.stdout)
        if result.stderr:
            print(result.stderr, file=sys.stderr)
        sys.exit(result.returncode)

    # --- Temp dir ---
    temp_dir = os.path.join(tempfile.gettempdir(), f"db_create_{random.randint(0, 999999)}")
    os.makedirs(temp_dir, exist_ok=True)

    try:
        # --- Build arguments ---
        arguments = ["CREATEINFOBASE"]

        if args.InfoBaseServer and args.InfoBaseRef:
            # No embedded quotes: subprocess quotes the whole token; 1C's argv parser
            # strips outer quotes. Inner quotes get escaped by list2cmdline and break parsing.
            conn = f'Srvr={args.InfoBaseServer};Ref={args.InfoBaseRef}'
        else:
            conn = f'File={args.InfoBasePath}'
            if args.PageSize:
                # DBPageSize needs the 8.3.8 file format.
                conn += f';DBFormat=8.3.8;DBPageSize={args.PageSize}'
        if args.Locale:
            conn += f';Locale={args.Locale}'
        arguments.append(conn)

        # --- Template ---
        if args.UseTemplate:
            arguments.extend(["/UseTemplate", args.UseTemplate])

        # --- Add to list ---
        if args.AddToList:
            if args.ListName:
                arguments.extend(["/AddToList", args.ListName])
            else:
                arguments.append("/AddToList")

        # --- Output ---
        out_file = os.path.join(temp_dir, "create_log.txt")
        arguments.extend(["/Out", out_file])
        arguments.append("/DisableStartupDialogs")

        # --- Execute ---
        arguments = arguments + extra_args
        print("Running: 1cv8.exe " + ' '.join(platform_args.format_args_for_display(arguments, engine)))
        result = subprocess.run(
            [v8path] + arguments,
            capture_output=True,
            text=True,
        )
        exit_code = result.returncode

        # --- Result ---
        if exit_code == 0:
            if args.InfoBaseServer and args.InfoBaseRef:
                print(f"Information base created successfully: {args.InfoBaseServer}/{args.InfoBaseRef}")
            else:
                print(f"Information base created successfully: {args.InfoBasePath}")
        else:
            print(f"Error creating information base (code: {exit_code})", file=sys.stderr)

        if os.path.isfile(out_file):
            try:
                with open(out_file, "r", encoding="utf-8-sig") as f:
                    log_content = f.read()
                if log_content:
                    print("--- Log ---")
                    print(log_content)
                    print("--- End ---")
            except Exception:
                pass

        sys.exit(exit_code)

    finally:
        if os.path.isdir(temp_dir):
            shutil.rmtree(temp_dir, ignore_errors=True)


if __name__ == "__main__":
    main()
