#!/usr/bin/env python3
# dead-code-after-insert-checker v1.0 — find a top-level (unconditional, not nested
# inside Если/Пока/Для/Попытка) Возврат statement that is followed by more code
# before the end of its routine — meaning that trailing code is unreachable.
#
# Companion to 1c-reference-finder / 1c-enum-value-checker / 1c-defined-type-
# dispatch-checker / 1c-broken-metadata-path-checker (same skill:
# 1c-extension-analysis). Born from concrete bugs found while auditing a real 1C
# extension (see docs/dead-code-after-insert-checker.md -> Provenance for the exact
# cases):
#
#   1. A wholly new (own) &После interceptor whose very first statements are a
#      debug comment then a bare "Возврат;", making the logging code that follows
#      completely unreachable. No #Вставка markers involved at all — the dead code
#      is the extension's own.
#   2. An &ИзменениеИКонтроль interceptor whose inserted block
#      (#Вставка ... #КонецВставки) is a bare "Возврат Истина;" — an unconditional
#      return — immediately followed (after #КонецВставки) by the original typical
#      line it was supposed to extend, which can now never execute. The typical
#      feature-option check is silently overridden for every caller, regardless of
#      the actual constant/option value.
#
# Neither #Вставка/#КонецВставки nor &-directives affect control flow at runtime —
# they are markers for the extension-diff tooling only. A top-level unconditional
# Возврат with more code after it in the same routine is unreachable regardless of
# whether that code is "typical" (case 2) or the extension's own (case 1), so this
# tool does not special-case #Вставка blocks — a single reachability check over
# every routine's raw statement sequence catches both bug classes uniformly.

import argparse
import os
import re
import sys

# Pragma-only lines: markers for extension-diff tooling, not executable BSL. Treated
# as inert — they neither open/close a block nor count as "code" for reachability.
PRAGMA_LINES = {"#Вставка", "#КонецВставки", "#Удаление", "#КонецУдаления"}

RE_ROUTINE_START = re.compile(r"^\s*(Функция|Процедура)\s+(\S+?)\s*\(", re.IGNORECASE)
RE_OPENER = re.compile(r"^(Если|Пока|Для(\s+Каждого)?|Попытка)\b", re.IGNORECASE)
RE_CLOSER = re.compile(r"^(КонецЕсли|КонецЦикла|КонецПопытки);?$", re.IGNORECASE)
RE_ROUTINE_END = re.compile(r"^(КонецФункции|КонецПроцедуры);?$", re.IGNORECASE)
# Trailing ";" is mandatory here (unlike a looser "optional ;" pattern) specifically
# to reject the first line of a multi-line call used as the return expression, e.g.
#   Возврат СтрШаблон("%1;%2;%3;%4",
#       ВидДокумента.Код, ...);
# — "Возврат СтрШаблон(...)," does not terminate the statement (unbalanced open
# paren, no trailing ";"), so it must NOT be treated as a complete, reachable-once
# top-level Возврат. Confirmed false-positive class found while validating this
# tool: dozens of string-building helper functions in a real extension use exactly this
# multi-line-call return shape.
RE_RETURN = re.compile(r"^Возврат(\s+.+)?;\s*$", re.IGNORECASE)


def strip_comment(line):
    idx = line.find("//")
    return line if idx == -1 else line[:idx]


def find_bsl_files(root):
    for dirpath, _dirnames, filenames in os.walk(root):
        for fn in filenames:
            if fn.lower().endswith(".bsl"):
                yield os.path.join(dirpath, fn)


def find_routines(lines):
    """Yields (name, start_idx, end_idx) 0-based line-index ranges (inclusive) for
    every Функция/Процедура ... КонецФункции/КонецПроцедуры in the file. 1C does not
    nest routine declarations, so this is unambiguous."""
    i = 0
    n = len(lines)
    while i < n:
        m = RE_ROUTINE_START.match(lines[i])
        if not m:
            i += 1
            continue
        name = m.group(2)
        start = i
        end = None
        for j in range(i, n):
            stripped = strip_comment(lines[j]).strip().rstrip(";").strip()
            if stripped in ("КонецФункции", "КонецПроцедуры"):
                end = j
                break
        if end is None:
            end = n - 1
        yield name, start, end
        i = end + 1


def check_routine(lines, start, end):
    """Returns (return_line_idx, next_code_line_idx, trailing_line_count) for the
    first top-level unconditional Возврат in [start, end] that has real code after
    it before end (inclusive), or None if the routine is clean. Line indices are
    0-based into the full file's `lines` list."""
    depth = 0
    return_idx = None
    for i in range(start, end + 1):
        raw = lines[i]
        stripped = strip_comment(raw).strip()
        if not stripped:
            continue
        if stripped in PRAGMA_LINES:
            continue

        if return_idx is None:
            if depth == 0 and RE_RETURN.match(stripped):
                return_idx = i
                continue
            if RE_OPENER.match(stripped):
                depth += 1
            elif RE_CLOSER.match(stripped):
                depth = max(0, depth - 1)
            continue

        # We already found a candidate top-level Возврат. The routine's own closing
        # "КонецФункции"/"КонецПроцедуры" is not trailing code — a Возврат as the
        # routine's genuinely last statement is completely normal and must not be
        # flagged (this was the dominant false-positive class before this check was
        # added: every function whose last statement happens to be its Возврат
        # matched, because the closer line itself was counted as "code after it").
        if RE_ROUTINE_END.match(stripped):
            return None

        # First non-blank, non-pragma, non-closer line after the candidate — real
        # trailing code.
        trailing = i - return_idx
        return return_idx, i, trailing

    return None


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(
        description="Find a top-level unconditional Возврат followed by more code "
                    "in the same routine (that code is unreachable).",
        allow_abbrev=False,
    )
    parser.add_argument("-ExtensionPath", required=True, help="Path to extension source dump")
    parser.add_argument(
        "-BslFile", default=None,
        help="Scope the scan to one .bsl file instead of the whole extension tree",
    )
    args = parser.parse_args()

    extension_path = args.ExtensionPath
    if not os.path.isabs(extension_path):
        extension_path = os.path.join(os.getcwd(), extension_path)
    if not os.path.isdir(extension_path):
        print(f"Extension path not found: {extension_path}", file=sys.stderr)
        sys.exit(1)

    if args.BslFile:
        target = args.BslFile
        if not os.path.isabs(target):
            target = os.path.join(os.getcwd(), target)
        if not os.path.isfile(target):
            print(f"BSL file not found: {target}", file=sys.stderr)
            sys.exit(1)
        files = [target]
    else:
        files = list(find_bsl_files(extension_path))

    total_findings = 0
    for path in files:
        try:
            with open(path, "r", encoding="utf-8-sig", errors="replace") as fh:
                lines = fh.readlines()
        except OSError:
            continue

        rel_path = os.path.relpath(path, extension_path) if os.path.isdir(extension_path) else path
        file_reported = False

        for name, start, end in find_routines(lines):
            result = check_routine(lines, start, end)
            if result is None:
                continue
            return_idx, next_code_idx, trailing = result
            if not file_reported:
                print(f"=== {rel_path} ===")
                file_reported = True
            total_findings += 1
            print(f"  [DEAD CODE] {name}() — unconditional Возврат at line {return_idx + 1} "
                  f"makes the rest of the routine ({trailing} line(s), starting at "
                  f"line {next_code_idx + 1}) unreachable")
            print(f"      {return_idx + 1}: {lines[return_idx].strip()}")
            print(f"      {next_code_idx + 1}: {lines[next_code_idx].strip()}  <-- unreachable")

        if file_reported:
            print()

    print(f"=== {total_findings} routine(s) with unreachable code after an unconditional Возврат ===")


if __name__ == "__main__":
    main()
