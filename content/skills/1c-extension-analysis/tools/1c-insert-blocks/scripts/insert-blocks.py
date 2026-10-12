#!/usr/bin/env python3
# insert-blocks v1.0 — dump every #Вставка/#КонецВставки (and #Удаление/
# #КонецУдаления) block of an extension, with the &ИзменениеИКонтроль routine
# that holds it. For &ИзменениеИКонтроль the routine body is a verbatim copy of
# the typical one; only these blocks are the extension's own change, so the
# "what it writes / what it reads" column of the change registry is filled from
# them (../../SKILL.md step 1).
#
# Why a tool: the markers are bare lines (`#Вставка`, not `// #Вставка`); a scan
# written for the commented spelling returns zero blocks, which reads as "the
# extension inserts nothing". And reading the blocks on demand, per object
# already classified, misses the comment that sits in another object's block:
# dump them all before grouping (docs/insert-blocks.md -> Provenance).
#
# The block and interceptor parsing is registry-builder's, loaded from this
# skill's own tools, so the two tools cannot disagree on what a block is.

import argparse
import importlib.util
import os
import sys

# Loading registry-builder must not leave a __pycache__ in its folder.
sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
RB_PATH = os.path.join(HERE, "..", "..", "1c-change-registry-builder", "scripts",
                       "registry-builder.py")
_spec = importlib.util.spec_from_file_location("registry_builder", RB_PATH)
rb = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rb)

OPEN_DELETE, CLOSE_DELETE = "#Удаление", "#КонецУдаления"


def delete_ranges(lines):
    """#Удаление ... #КонецУдаления ranges, same rules as rb.find_insertion_ranges."""
    ranges, start = [], None
    for k, line in enumerate(lines):
        stripped = line.strip()
        if stripped == OPEN_DELETE:
            start = k
        elif stripped == CLOSE_DELETE and start is not None:
            ranges.append((start, k))
            start = None
    if start is not None:
        ranges.append((start, len(lines) - 1))
    return ranges


def interceptor_routines(path, lines):
    """[{Type, Method, Name, Line, Start, End}] for every annotated interceptor
    routine (0-based Start/End of the routine body)."""
    out = []
    for ic in rb.scan_bsl_for_interceptors(path):
        start = ic["RoutineLine"] - 1
        m = rb.RE_ROUTINE_START.match(rb.strip_comment(lines[start]).strip()) \
            if start < len(lines) else None
        end = len(lines) - 1
        for k in range(start, len(lines)):
            if rb.RE_ROUTINE_END.match(rb.strip_comment(lines[k]).strip()):
                end = k
                break
        out.append({"Type": ic["Type"], "Method": ic["Method"], "Name": m.group(2) if m else "?",
                    "Line": ic["Line"], "Start": start, "End": end})
    return out


def has_executable_line(lines, start, end):
    for k in range(start + 1, end):
        code = lines[k].strip()
        if code and not code.startswith("//"):
            return True
    return False


def base_note(config_path, rel, method):
    if not config_path:
        return "base module not checked (no -ConfigPath)"
    base = os.path.join(config_path, rel)
    if not os.path.isfile(base):
        return ("base module absent — the typical object has no such module, so there is "
                "nothing to change and no own change is hidden here")
    for r in rb.scan_bsl_routines_with_lines(base):
        if r["Name"] == method:
            return (f"base declares {method} at {rel}:{r['Line']} — compare the bodies: "
                    f"an untouched copy is an interceptor with no own change")
    return f"base module exists but declares no {method} — read both modules"


def object_dir(ext_path, obj):
    kind, _, name = obj.partition(".")
    folder = rb.CHILD_TYPE_DIR_MAP.get(kind)
    if folder is None or not name:
        return None
    return os.path.join(ext_path, folder, name)


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(
        description="Dump every #Вставка/#Удаление block of an extension with the "
                    "&ИзменениеИКонтроль routine that holds it.",
        allow_abbrev=False,
    )
    parser.add_argument("-ExtensionPath", required=True, help="Path to extension source dump")
    parser.add_argument("-ConfigPath", default=None,
                        help="Path to the base configuration dump: checks the base module "
                             "behind each &ИзменениеИКонтроль that has no block")
    parser.add_argument("-Object", default=None, help='Scope to one object, e.g. "Document.<Имя>"')
    parser.add_argument("-Summary", action="store_true",
                        help="Counters and flagged items only, no block bodies")
    args = parser.parse_args()

    ext_path = os.path.abspath(args.ExtensionPath)
    if not os.path.isdir(ext_path):
        print(f"Extension path not found: {ext_path}", file=sys.stderr)
        sys.exit(1)
    config_path = os.path.abspath(args.ConfigPath) if args.ConfigPath else None
    if config_path and not os.path.isdir(config_path):
        print(f"Config path not found: {config_path}", file=sys.stderr)
        sys.exit(1)
    root = ext_path
    if args.Object:
        root = object_dir(ext_path, args.Object)
        if root is None or not os.path.isdir(root):
            print(f"Object not found in the extension: {args.Object}", file=sys.stderr)
            sys.exit(1)

    bsl_files = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames.sort()
        bsl_files += [os.path.join(dirpath, f) for f in sorted(filenames)
                      if f.lower().endswith(".bsl")]

    n_insert = n_delete = n_empty = n_outside = n_iik = 0
    files_with_blocks = 0
    no_block, flagged = [], []
    for path in bsl_files:
        rel = os.path.relpath(path, ext_path)
        lines = rb.read_lines(path)
        annotated = interceptor_routines(path, lines)
        routines = [r for r in annotated if r["Type"] == "ИзменениеИКонтроль"]
        n_iik += len(routines)
        blocks = ([("INSERT", s, e) for s, e in rb.find_insertion_ranges(lines, 0, len(lines) - 1)]
                  if lines else [])
        blocks += [("DELETE", s, e) for s, e in delete_ranges(lines)]
        blocks.sort(key=lambda b: b[1])
        if blocks:
            files_with_blocks += 1
            if not args.Summary:
                print(f"=== {rel} ===")
        for kind, s, e in blocks:
            holder = next((r for r in annotated if r["Start"] <= s <= r["End"]), None)
            if holder is None:
                where = "OUTSIDE any interceptor routine"
            else:
                where = f'&{holder["Type"]}("{holder["Method"]}") {holder["Name"]}'
            if holder is not None and holder["Type"] != "ИзменениеИКонтроль":
                # Markers only mean something under &ИзменениеИКонтроль; elsewhere
                # the whole body is the extension's own and the markers are inert
                # — usually a trace of copying the body from a typical routine.
                holder_note = f'inside &{holder["Type"]}: the whole body is own, markers inert'
            elif holder is None:
                holder_note = "outside any interceptor: markers inert"
            else:
                holder_note = None
            marks = []
            if kind == "INSERT":
                n_insert += 1
                if not has_executable_line(lines, s, e):
                    n_empty += 1
                    marks.append("no executable lines")
            else:
                n_delete += 1
            if holder_note:
                n_outside += 1
                marks.append(holder_note)
            tag = f" [{'; '.join(marks)}]" if marks else ""
            if marks:
                flagged.append(f"  [{kind}] {rel}:{s + 1}-{e + 1} {where}{tag}")
            if not args.Summary:
                print(f"  [{kind}] {rel}:{s + 1}-{e + 1} {where}{tag}")
                for k in range(s + 1, e):
                    print(f"    {k + 1:>5}: {lines[k].rstrip()}")
        for r in routines:
            if not any(r["Start"] <= s <= r["End"] for _k, s, _e in blocks):
                no_block.append(f'  {rel}:{r["Line"]} &ИзменениеИКонтроль("{r["Method"]}") '
                                f'{r["Name"]} — {base_note(config_path, rel, r["Method"])}')

    if not args.Summary:
        print()
    print(f"=== flagged blocks — no executable lines (comments only) or outside "
          f"&ИзменениеИКонтроль ({len(flagged)}) ===")
    for f in flagged:
        print(f)
    print(f"=== &ИзменениеИКонтроль routines with no block ({len(no_block)}) ===")
    for f in no_block:
        print(f)

    scope = "extension + base config" if config_path else "extension only, no -ConfigPath"
    if args.Object:
        scope += f", object {args.Object}"
    print(f"=== {n_insert} insert block(s), {n_delete} delete block(s) in {files_with_blocks} "
          f"file(s): {n_empty} without executable lines, {n_outside} outside "
          f"&ИзменениеИКонтроль; {n_iik} &ИзменениеИКонтроль, {len(no_block)} without a "
          f"block [scope: {scope}] ===")

    # Zero is an answer only when nothing could hold a block.
    if n_insert + n_delete == 0:
        if n_iik:
            print(f"PARSE FAILURE: {n_iik} &ИзменениеИКонтроль routine(s) and no block found — "
                  f"the markers are spelled differently here; do not read this as "
                  f"'the extension inserts nothing'", file=sys.stderr)
            sys.exit(2)
        print("No &ИзменениеИКонтроль and no block: an extension built from &Перед / &После / "
              "&Вместо and its own modules — zero is the right answer here.")


if __name__ == "__main__":
    main()
