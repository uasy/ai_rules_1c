#!/usr/bin/env python3
# uuid-check v1.0 — Detect (and optionally repair) duplicate UUIDs in a 1C XML configuration dump
# Ported from check_uuid_duplicates.py of https://github.com/Desko77/claude-code-skills-1c (MIT)
# and adapted to the Configurator XML format: `uuid="..."` attributes plus
# <xr:TypeId> / <xr:ValueId> elements inside <InternalInfo>.

import argparse
import bisect
import os
import re
import sys
import uuid as uuid_mod

# Two carriers in the Configurator XML dump:
#   attribute  uuid="xxxxxxxx-...."         — object / attribute / tabular-section identity
#   elements   <xr:TypeId>, <xr:ValueId>    — generated types inside <InternalInfo>
GUID = r'[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}'
UUID_RE = re.compile(
    r'(?:\b(?P<attr>uuid)\s*=\s*"(?P<gattr>' + GUID + r')")'
    r'|(?:<(?:\w+:)?(?P<el>TypeId|ValueId)>\s*(?P<gel>' + GUID + r')\s*<)')


def read_file_text(full_name):
    """Decoded text plus the BOM flag needed to write it back byte-identically."""
    with open(full_name, "rb") as f:
        data = f.read()
    has_bom = data[:3] == b"\xef\xbb\xbf"
    text = data[3:].decode("utf-8", errors="replace") if has_bom \
        else data.decode("utf-8", errors="replace")
    return text, has_bom


def write_file_text(full_name, text, has_bom):
    with open(full_name, "wb") as f:
        if has_bom:
            f.write(b"\xef\xbb\xbf")
        f.write(text.encode("utf-8"))


def line_starts(text):
    """Offsets of every line start — a match index maps to a line by bisect.
    (Rescanning the text per match is O(text x matches) and stalls on a
    multi-megabyte Configuration.xml with thousands of generated types.)"""
    starts = [0]
    idx = text.find("\n")
    while idx >= 0:
        starts.append(idx + 1)
        idx = text.find("\n", idx + 1)
    return starts


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(
        description="Detect (and optionally repair) duplicate UUIDs in a 1C XML dump",
        allow_abbrev=False)
    parser.add_argument("-ConfigPath", "-Path", dest="ConfigPath", required=True)
    parser.add_argument("-IncludeIntra", action="store_true",
                        help="also report / repair duplicates inside a single file")
    parser.add_argument("-Fix", action="store_true",
                        help="regenerate every duplicate occurrence except the first")
    parser.add_argument("-Filter", default="*.xml",
                        help="file mask to scan (the Configurator dump is XML; EDT *.mdo "
                             "is not supported by this ruleset)")
    parser.add_argument("-MaxReported", type=int, default=50)
    parser.add_argument("-OutFile", default="")
    args = parser.parse_args()

    config_path = args.ConfigPath
    if not os.path.isabs(config_path):
        config_path = os.path.join(os.getcwd(), config_path)
    if not os.path.exists(config_path):
        print(f"[ERROR] Path not found: {config_path}")
        sys.exit(1)
    resolved_path = os.path.abspath(config_path)

    import fnmatch
    if os.path.isdir(resolved_path):
        base_dir = resolved_path
        files = []
        for dirpath, _dirnames, filenames in os.walk(resolved_path):
            for fn in sorted(filenames):
                if fnmatch.fnmatch(fn, args.Filter):
                    files.append(os.path.join(dirpath, fn))
        files.sort()
    else:
        base_dir = os.path.dirname(resolved_path)
        files = [resolved_path]

    if not files:
        print(f"[ERROR] No files matching '{args.Filter}' under: {resolved_path}")
        sys.exit(1)

    out_lines = []

    def out(msg=""):
        out_lines.append(msg)

    def rel(full_name):
        if full_name.lower().startswith(base_dir.lower()):
            return full_name[len(base_dir):].lstrip("\\/")
        return full_name

    registry = {}   # uuid (lower) -> list of occurrences
    scanned = 0

    for path in files:
        try:
            text, _has_bom = read_file_text(path)
        except OSError as e:
            out(f"[WARN]  Cannot read {rel(path)}: {e}")
            continue
        scanned += 1
        starts = line_starts(text)
        for m in UUID_RE.finditer(text):
            if m.group("gattr") is not None:
                idx, val, carrier = m.start("gattr"), m.group("gattr"), "uuid"
            else:
                idx, val, carrier = m.start("gel"), m.group("gel"), m.group("el")
            key = val.lower()
            registry.setdefault(key, []).append({
                "File": path, "Index": idx, "Length": len(val), "Carrier": carrier,
                "Line": bisect.bisect_right(starts, idx),
            })

    # --- Classify duplicates ---
    cross_file, intra_file = [], []
    for key in sorted(registry):
        occ = registry[key]
        if len(occ) < 2:
            continue
        entry = {"Uuid": key, "Occurrences": occ}
        if len({o["File"] for o in occ}) > 1:
            cross_file.append(entry)
        else:
            intra_file.append(entry)

    targets = list(cross_file)
    if args.IncludeIntra:
        targets += intra_file

    # --- Report ---
    def write_group(title, entries):
        if not entries:
            return
        out()
        out(f"--- {title} ---")
        shown = 0
        for entry in entries:
            if shown >= args.MaxReported:
                out(f"    ... {len(entries) - shown} more (raise -MaxReported to see them)")
                break
            out()
            out(f"  UUID: {entry['Uuid']}")
            for o in entry["Occurrences"]:
                out(f"    {rel(o['File'])}:{o['Line']}  [{o['Carrier']}]")
            shown += 1

    out(f"Scanned files: {scanned}  (mask '{args.Filter}', root {resolved_path})")

    if not targets:
        out("[OK]    No duplicate UUIDs found.")
        if not args.IncludeIntra and intra_file:
            out(f"[WARN]  {len(intra_file)} intra-file duplicate(s) suppressed. In the "
                f"Configurator XML dump these are")
            out("        usually genuine collisions - re-run with -IncludeIntra to inspect them.")
    else:
        intra_shown = len(intra_file) if args.IncludeIntra else 0
        out(f"[ERROR] Duplicate UUIDs: {len(targets)} "
            f"(cross-file: {len(cross_file)}, intra-file: {intra_shown})")
        write_group("CROSS-FILE DUPLICATES (two objects claim the same identity)", cross_file)
        if args.IncludeIntra:
            write_group("INTRA-FILE DUPLICATES", intra_file)
        elif intra_file:
            out()
            out(f"[WARN]  {len(intra_file)} intra-file duplicate(s) suppressed - re-run with "
                f"-IncludeIntra to inspect them.")

    # --- Fix ---
    fixed_count = 0
    if args.Fix and targets:
        out()
        out("--- REPAIR (first occurrence of each UUID is kept) ---")
        out("[WARN]  A UUID is an object's identity. Regenerating one on sources that were already")
        out("        loaded into an infobase makes the platform treat the object as a NEW object "
            "on the")
        out("        next load (the old data is orphaned). 'Keep the first occurrence' is "
            "positional,")
        out("        not semantic - verify which object is meant to keep the identity.")
        out()

        # Group replacements per file and apply them from the end, so earlier
        # indices stay valid.
        by_file = {}
        for entry in targets:
            for o in entry["Occurrences"][1:]:
                by_file.setdefault(o["File"], []).append({
                    "Index": o["Index"], "Length": o["Length"], "Line": o["Line"],
                    "Carrier": o["Carrier"], "Old": entry["Uuid"],
                })

        for file_path in sorted(by_file):
            text, has_bom = read_file_text(file_path)
            for r in sorted(by_file[file_path], key=lambda x: x["Index"], reverse=True):
                new = str(uuid_mod.uuid4())
                text = text[:r["Index"]] + new + text[r["Index"] + r["Length"]:]
                fixed_count += 1
                out(f"  {rel(file_path)}:{r['Line']}  [{r['Carrier']}]  {r['Old']} -> {new}")
            write_file_text(file_path, text, has_bom)

        out()
        out(f"Regenerated UUIDs: {fixed_count}")
        out("[NOTE]  Re-run without -Fix to confirm the dump is clean, then validate the")
        out("        affected objects (meta-validate / cf-validate) before loading.")

    # --- Final output ---
    text = "\r\n".join(out_lines) + "\r\n"
    if args.OutFile:
        d = os.path.dirname(args.OutFile)
        if d:
            os.makedirs(d, exist_ok=True)
        with open(args.OutFile, "w", encoding="utf-8", newline="") as f:
            f.write(text)
        print(f"Report written to: {args.OutFile}")
    else:
        print(text)

    if targets and not args.Fix:
        sys.exit(1)
    if args.Fix and fixed_count > 0:
        sys.exit(0)
    if targets:
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
