#!/usr/bin/env python3
# cfe-build v1.1 — Build a compiled extension (.cfe) from XML sources via a throwaway infobase
#
# Unlike a deploy against a shared/persistent infobase, this always (re)creates a fresh
# local infobase, optionally loads a compiled base configuration (-BaseCfFile) into it,
# loads the extension XML source as an extension, dumps the compiled .cfe, and leaves the
# throwaway infobase behind for inspection (rerun to get a clean one).
#
# -BaseCfFile is required whenever the extension borrows objects from the base
# configuration (ObjectBelonging=Adopted) — verified empirically: loading such an
# extension into a truly empty infobase (no base config at all) fails at the platform
# level with dozens/hundreds of "Не найден объект ..." errors and a non-zero exit code,
# because the extension's adopted-object references cannot resolve. A standalone
# extension with no adopted objects can omit -BaseCfFile.

import argparse
import glob
import os
import re
import shutil
import subprocess
import sys
from xml.etree import ElementTree as ET

NS = {"md": "http://v8.1c.ru/8.3/MDClasses"}


def _version_dir(p):
    """Version dir for both Windows (.../1cv8/<ver>/bin/1cv8.exe) and *nix (.../1cv8/<ver>/1cv8)."""
    parent = os.path.dirname(p)
    if os.path.basename(parent).lower() == "bin":
        parent = os.path.dirname(parent)
    return os.path.basename(parent)


def _version_key(p):
    return [int(x) for x in re.findall(r"\d+", _version_dir(p))]


def resolve_v8path(v8path):
    """Resolve path to a 1C executable (1cv8 only — ibcmd cannot run DESIGNER-mode extension loads)."""
    if not v8path:
        if os.name == "nt":
            candidates = (
                glob.glob(r"C:\Program Files\1cv8\*\bin\1cv8.exe")
                + glob.glob(r"C:\Program Files (x86)\1cv8\*\bin\1cv8.exe")
            )
        else:
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
        exe = "1cv8.exe" if os.name == "nt" else "1cv8"
        v8path = os.path.join(v8path, exe)
    if not os.path.isfile(v8path):
        print(f"Error: 1C executable not found at {v8path}", file=sys.stderr)
        sys.exit(1)
    return v8path


def detect_extension_name(extension_path):
    """Read <Configuration/Properties/Name> from the extension's Configuration.xml.

    This is the value the platform expects for -Extension — it commonly differs from
    the source directory name (e.g. directory base_МоеРасширение, extension
    name МоеРасширение).
    """
    cfg_file = os.path.join(extension_path, "Configuration.xml")
    if not os.path.isfile(cfg_file):
        print(f"Error: Configuration.xml not found in extension path: {cfg_file}", file=sys.stderr)
        sys.exit(1)
    tree = ET.parse(cfg_file)
    name_node = tree.find(".//md:Configuration/md:Properties/md:Name", NS)
    if name_node is None or not name_node.text:
        print(f"Error: <Name> not found in {cfg_file}", file=sys.stderr)
        sys.exit(1)
    return name_node.text.strip()


def run_step(cmd, description):
    print(f"\n--- {description} ---")
    print(f"Running: {' '.join(cmd)}")
    result = subprocess.run(cmd)
    if result.returncode != 0:
        print(f"Error: {description} failed (code: {result.returncode})", file=sys.stderr)
        sys.exit(result.returncode)


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(
        description="Build a compiled extension (.cfe) from XML sources via a throwaway local infobase",
        allow_abbrev=False,
    )
    parser.add_argument("-ExtensionPath", "-Path", required=True,
                         help="Path to extension XML source directory (contains Configuration.xml)")
    parser.add_argument("-V8Path", default="", help="Path to 1cv8(.exe) or its bin directory")
    parser.add_argument("-BasePath", default=os.path.join("base", "empty"),
                         help="Throwaway infobase directory, recreated on every run (default: base/empty)")
    parser.add_argument("-BaseCfFile", default="",
                         help="Compiled base configuration (.cf) to load before the extension — "
                              "required when the extension has adopted (borrowed) objects")
    parser.add_argument("-OutputFile", default="", help="Output .cfe path (default: build/<ExtensionName>.cfe)")
    parser.add_argument("-ExtensionName", default="",
                         help="Extension name for -Extension (default: read from Configuration.xml <Name>)")
    parser.add_argument("-UserName", default="", help="1C user name for the throwaway infobase")
    parser.add_argument("-Password", default="", help="1C user password for the throwaway infobase")
    args = parser.parse_args()

    if not os.path.isdir(args.ExtensionPath):
        print(f"Error: extension path not found: {args.ExtensionPath}", file=sys.stderr)
        sys.exit(1)

    if args.BaseCfFile and not os.path.isfile(args.BaseCfFile):
        print(f"Error: base .cf file not found: {args.BaseCfFile}", file=sys.stderr)
        sys.exit(1)

    v8path = resolve_v8path(args.V8Path)
    ext_name = args.ExtensionName or detect_extension_name(args.ExtensionPath)
    print(f"Extension name: {ext_name}")

    output_file = args.OutputFile or os.path.join("build", f"{ext_name}.cfe")
    out_dir = os.path.dirname(output_file)
    if out_dir and not os.path.exists(out_dir):
        os.makedirs(out_dir, exist_ok=True)

    scripts_dir = os.path.dirname(os.path.abspath(__file__))
    db_ops_dir = os.path.join(scripts_dir, "..", "..", "1c-db-ops", "scripts")
    db_create = os.path.join(db_ops_dir, "db-create.py")
    db_load_cf = os.path.join(db_ops_dir, "db-load-cf.py")
    db_load_xml = os.path.join(db_ops_dir, "db-load-xml.py")
    db_update = os.path.join(db_ops_dir, "db-update.py")
    db_dump_cf = os.path.join(db_ops_dir, "db-dump-cf.py")

    total_steps = 5 if args.BaseCfFile else 3
    step_n = 1

    # --- Step: recreate the throwaway empty infobase ---
    base_path = os.path.abspath(args.BasePath)
    if os.path.exists(base_path):
        shutil.rmtree(base_path)
    os.makedirs(base_path, exist_ok=True)

    run_step(
        [sys.executable, db_create, "-V8Path", v8path, "-InfoBasePath", base_path],
        f"Step {step_n}/{total_steps}: create empty infobase",
    )
    step_n += 1

    # --- Step (optional): load the base configuration the extension borrows objects from ---
    if args.BaseCfFile:
        load_cf_cmd = [
            sys.executable, db_load_cf,
            "-V8Path", v8path,
            "-InfoBasePath", base_path,
            "-InputFile", os.path.abspath(args.BaseCfFile),
        ]
        if args.UserName:
            load_cf_cmd += ["-UserName", args.UserName]
        if args.Password:
            load_cf_cmd += ["-Password", args.Password]
        run_step(load_cf_cmd, f"Step {step_n}/{total_steps}: load base configuration ({args.BaseCfFile})")
        step_n += 1

        update_cmd = [sys.executable, db_update, "-V8Path", v8path, "-InfoBasePath", base_path]
        if args.UserName:
            update_cmd += ["-UserName", args.UserName]
        if args.Password:
            update_cmd += ["-Password", args.Password]
        run_step(update_cmd, f"Step {step_n}/{total_steps}: apply base configuration to database")
        step_n += 1

    # --- Step: load the extension XML source as an extension ---
    load_cmd = [
        sys.executable, db_load_xml,
        "-V8Path", v8path,
        "-InfoBasePath", base_path,
        "-ConfigDir", args.ExtensionPath,
        "-Mode", "Full",
        "-Extension", ext_name,
        "-UpdateDB",
    ]
    if args.UserName:
        load_cmd += ["-UserName", args.UserName]
    if args.Password:
        load_cmd += ["-Password", args.Password]
    run_step(load_cmd, f"Step {step_n}/{total_steps}: load extension configuration")
    step_n += 1

    # --- Step: dump the compiled extension to .cfe ---
    dump_cmd = [
        sys.executable, db_dump_cf,
        "-V8Path", v8path,
        "-InfoBasePath", base_path,
        "-Extension", ext_name,
        "-OutputFile", output_file,
    ]
    if args.UserName:
        dump_cmd += ["-UserName", args.UserName]
    if args.Password:
        dump_cmd += ["-Password", args.Password]
    run_step(dump_cmd, f"Step {step_n}/{total_steps}: dump compiled extension")

    print(f"\nBuild completed successfully: {output_file}")


if __name__ == "__main__":
    main()
