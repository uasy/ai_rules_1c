#!/usr/bin/env python3
# broken-metadata-path-checker v1.0 — find hardcoded metadata-path string literals
# (e.g. passed to ОткрытьФорму / ПолучитьФорму) that reference an object that does
# not actually exist, in either the extension or the base configuration.
#
# Companion to 1c-reference-finder / 1c-enum-value-checker / 1c-defined-type-
# dispatch-checker (same skill: 1c-extension-analysis). Born from a concrete bug
# found while auditing a real 1C extension: a navigation command opened a hardcoded
# metadata-path string naming an object that did not exist anywhere, neither in the
# extension nor in the base configuration — a sibling command on the same object
# correctly referenced the real object name, so this looked like an incomplete
# rename that missed one command. Running the broken command guarantees a runtime
# "object not found" error. This tool automates the existence check a human did by
# hand for every hardcoded metadata path literal found while reading the
# extension's command modules. See docs/broken-metadata-path-checker.md ->
# Provenance for the exact case.

import argparse
import os
import re
import sys

# Query-style (singular, Cyrillic) metadata keyword -> source-dump directory name.
QUERY_TO_DIR = {
    "Справочник": "Catalogs",
    "Документ": "Documents",
    "Отчет": "Reports",
    "Обработка": "DataProcessors",
    "ПланВидовХарактеристик": "ChartsOfCharacteristicTypes",
    "ПланСчетов": "ChartsOfAccounts",
    "ПланВидовРасчета": "ChartsOfCalculationTypes",
    "БизнесПроцесс": "BusinessProcesses",
    "Задача": "Tasks",
    "ПланОбмена": "ExchangePlans",
    "РегистрСведений": "InformationRegisters",
    "РегистрНакопления": "AccumulationRegisters",
    "РегистрБухгалтерии": "AccountingRegisters",
    "РегистрРасчета": "CalculationRegisters",
    "Перечисление": "Enums",
    "ЖурналДокументов": "DocumentJournals",
    "ОбщаяФорма": "CommonForms",
}

# "Тип.Имя.ЧтоУгодно" inside a double-quoted string literal — requires at least
# three dot-separated segments (Type.Name.FormOrWhatever) to specifically target
# navigation/form-path literals (ОткрытьФорму("Документ.X.ФормаСписка", ...) and
# similar), deliberately excluding bare two-segment "Тип.Имя" metadata full-name
# strings (a different, unrelated usage this tool does not check).
RE_PATH_LITERAL = re.compile(
    r'"(' + "|".join(re.escape(k) for k in QUERY_TO_DIR) + r')'
    r'\.([A-Za-zА-Яа-яЁё0-9_]+)\.[A-Za-zА-Яа-яЁё0-9_]+'
)


def find_bsl_files(root):
    for dirpath, _dirnames, filenames in os.walk(root):
        for fn in filenames:
            if fn.lower().endswith(".bsl"):
                yield os.path.join(dirpath, fn)


def object_exists(root, keyword, name):
    if not root:
        return False
    dir_name = QUERY_TO_DIR[keyword]
    return os.path.isfile(os.path.join(root, dir_name, f"{name}.xml"))


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(
        description="Find hardcoded metadata-path string literals "
                    '("Тип.Имя.Что-то", e.g. an ОткрытьФорму target) referencing '
                    "an object that does not exist in the extension or base config.",
        allow_abbrev=False,
    )
    parser.add_argument("-ExtensionPath", required=True, help="Path to extension source dump")
    parser.add_argument(
        "-ConfigPath", default=None,
        help="Path to base configuration source dump (optional but recommended — "
             "without it, an object that exists only in the base config is "
             "reported as UNKNOWN rather than confirmed OK)",
    )
    args = parser.parse_args()

    extension_path = args.ExtensionPath
    if not os.path.isabs(extension_path):
        extension_path = os.path.join(os.getcwd(), extension_path)
    if not os.path.isdir(extension_path):
        print(f"Extension path not found: {extension_path}", file=sys.stderr)
        sys.exit(1)

    config_path = args.ConfigPath
    if config_path and not os.path.isabs(config_path):
        config_path = os.path.join(os.getcwd(), config_path)

    total_broken = 0
    total_unknown = 0
    total_hits = 0

    for path in find_bsl_files(extension_path):
        try:
            with open(path, "r", encoding="utf-8-sig", errors="replace") as fh:
                lines = fh.readlines()
        except OSError:
            continue

        for i, raw_line in enumerate(lines, start=1):
            # Skip fully commented-out lines — same accepted line-based trade-off as
            # the other tools in this skill (reference-finder.py, enum-value-checker.py).
            stripped = raw_line.strip()
            if stripped.startswith("//"):
                continue

            for m in RE_PATH_LITERAL.finditer(raw_line):
                keyword, name = m.group(1), m.group(2)
                total_hits += 1
                rel_path = os.path.relpath(path, extension_path)

                in_ext = object_exists(extension_path, keyword, name)
                in_base = object_exists(config_path, keyword, name)

                if in_ext or in_base:
                    origin = "extension" if in_ext else "base config"
                    print(f"[OK] {rel_path}:{i} ({origin}): {keyword}.{name} — {stripped}")
                elif config_path:
                    total_broken += 1
                    print(f"[BROKEN] {rel_path}:{i}: {keyword}.{name} not found in "
                          f"extension or base config — {stripped}")
                else:
                    total_unknown += 1
                    print(f"[UNKNOWN] {rel_path}:{i}: {keyword}.{name} not found in "
                          f"extension; no -ConfigPath given to check base config — {stripped}")

    print()
    print(f"=== {total_hits} metadata-path literal(s) checked: "
          f"{total_broken} broken, {total_unknown} unknown (no -ConfigPath) ===")


if __name__ == "__main__":
    main()
