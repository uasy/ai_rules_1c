#!/usr/bin/env python3
# reference-finder v1.0 — find why a 1C extension adopted (borrowed) a base-config
# object with no real changes of its own: composite-type reference vs code/query reference.
#
# Companion to 1c-metadata-manage/tools/1c-cfe-manage/scripts/cfe-diff.py (-Mode A).
# Run cfe-diff first to get the [BORROWED] object list; for every borrowed object
# that shows zero own attrs/TS/forms, run this tool to find (or rule out) the reason
# it needed to be adopted at all.
#
# Two independent mechanisms are checked, and reported separately because they carry
# different weight:
#   1. Composite-type reference (hard platform requirement) — the object's Ref type
#      (e.g. CatalogRef.X) appears in the <Type>/<v8:Type> of an attribute, dimension,
#      resource or tabular-section column belonging to ANOTHER object in the extension.
#      Without this, the extension would not compile.
#   2. Code/query reference (soft, not a compiler requirement) — the object's manager
#      collection name (Справочники.X), query table name (Справочник.X), or metadata
#      lookup (Метаданные.Справочники.X) appears in some .bsl module of the extension.
#      The extension author chose to bring the object along for IDE/consistency
#      reasons, not because the platform forced it.
#
# If neither is found, the object has no discoverable justification for adoption in
# this extension and is a candidate for exclusion (removal of the borrow), per the
# project rule: "usynovlenie bez ssylki = kandidat na isklyuchenie".

import argparse
import os
import re
import sys

# --- Object type -> (directory, Ref-type prefix or None, query singular, manager plural) ---
# Ref-type prefix is the literal token used inside <v8:Type>...Ref.Name</v8:Type> in
# metadata XML (language-neutral). Query singular / manager plural are the Cyrillic
# BSL tokens used in query text ("ИЗ Справочник.X") and manager-style code
# ("Справочники.X.СоздатьЭлемент()") respectively. Registers have no Ref type — a
# composite-type reference is structurally impossible for them, so RefPrefix is None.
OBJECT_TYPES = {
    "Catalog": {
        "dir": "Catalogs", "ref": "CatalogRef",
        "query": "Справочник",
        "manager": "Справочники",
    },
    "Document": {
        "dir": "Documents", "ref": "DocumentRef",
        "query": "Документ",
        "manager": "Документы",
    },
    "Enum": {
        "dir": "Enums", "ref": "EnumRef",
        "query": "Перечисление",
        "manager": "Перечисления",
    },
    "ChartOfCharacteristicTypes": {
        "dir": "ChartsOfCharacteristicTypes", "ref": "ChartOfCharacteristicTypesRef",
        "query": "ПланВидовХарактеристик",
        "manager": "ПланыВидовХарактеристик",
    },
    "ChartOfAccounts": {
        "dir": "ChartsOfAccounts", "ref": "ChartOfAccountsRef",
        "query": "ПланСчетов",
        "manager": "ПланыСчетов",
    },
    "ChartOfCalculationTypes": {
        "dir": "ChartsOfCalculationTypes", "ref": "ChartOfCalculationTypesRef",
        "query": "ПланВидовРасчета",
        "manager": "ПланыВидовРасчета",
    },
    "BusinessProcess": {
        "dir": "BusinessProcesses", "ref": "BusinessProcessRef",
        "query": "БизнесПроцесс",
        "manager": "БизнесПроцессы",
    },
    "Task": {
        "dir": "Tasks", "ref": "TaskRef",
        "query": "Задача",
        "manager": "Задачи",
    },
    "ExchangePlan": {
        "dir": "ExchangePlans", "ref": "ExchangePlanRef",
        "query": "ПланОбмена",
        "manager": "ПланыОбмена",
    },
    "InformationRegister": {
        "dir": "InformationRegisters", "ref": None,
        "query": "РегистрСведений",
        "manager": "РегистрыСведений",
    },
    "AccumulationRegister": {
        "dir": "AccumulationRegisters", "ref": None,
        "query": "РегистрНакопления",
        "manager": "РегистрыНакопления",
    },
    "AccountingRegister": {
        "dir": "AccountingRegisters", "ref": None,
        "query": "РегистрБухгалтерии",
        "manager": "РегистрыБухгалтерии",
    },
    "CalculationRegister": {
        "dir": "CalculationRegisters", "ref": None,
        "query": "РегистрРасчета",
        "manager": "РегистрыРасчета",
    },
    "Report": {
        "dir": "Reports", "ref": None,
        "query": "Отчет",
        "manager": "Отчеты",
    },
    "DataProcessor": {
        "dir": "DataProcessors", "ref": None,
        "query": "Обработка",
        "manager": "Обработки",
    },
}


def find_files(root, extensions):
    for dirpath, _dirnames, filenames in os.walk(root):
        for fn in filenames:
            if fn.lower().endswith(extensions):
                yield os.path.join(dirpath, fn)


def own_files_of(extension_path, type_dir, name):
    """Paths that belong to the object itself — matches here are self-references, not
    evidence of adoption by something else, so they are excluded from the search."""
    owned = set()
    obj_xml = os.path.join(extension_path, type_dir, f"{name}.xml")
    owned.add(os.path.normpath(obj_xml))
    obj_dir = os.path.join(extension_path, type_dir, name)
    if os.path.isdir(obj_dir):
        for dirpath, _dirnames, filenames in os.walk(obj_dir):
            for fn in filenames:
                owned.add(os.path.normpath(os.path.join(dirpath, fn)))
    return owned


def has_own_ext_content(extension_path, type_dir, name):
    """True if the object's own directory contains an Ext/ subfolder anywhere (own
    module file, own form, own template) — even an empty stub module counts, since it
    means the extension deliberately created a hook there. This is a separate, prior
    question to "why was this object adopted at all": an object with its own Ext
    content is self-explanatory and does not need an external reference to justify
    adoption. Run cfe-diff -Mode A for the exact own-attrs/own-TS/own-forms counts."""
    obj_dir = os.path.join(extension_path, type_dir, name)
    if not os.path.isdir(obj_dir):
        return False
    for dirpath, dirnames, _filenames in os.walk(obj_dir):
        if os.path.basename(dirpath) == "Ext":
            return True
    return False


def search_token(root, extensions, token, exclude_files):
    """Word-bounded literal search for `token` across every file with one of
    `extensions` under `root`, skipping files in `exclude_files`. Returns a list of
    (relative_path, line_number, line_text) hits."""
    pattern = re.compile(r"(?<![\w.])" + re.escape(token) + r"(?![\w])", re.UNICODE)
    hits = []
    for path in find_files(root, extensions):
        if os.path.normpath(path) in exclude_files:
            continue
        try:
            with open(path, "r", encoding="utf-8-sig", errors="replace") as fh:
                for i, line in enumerate(fh, start=1):
                    if pattern.search(line):
                        rel = os.path.relpath(path, root)
                        hits.append((rel, i, line.strip()))
        except OSError:
            continue
    return hits


def analyze_object(extension_path, obj_type, name):
    spec = OBJECT_TYPES.get(obj_type)
    if spec is None:
        print(f"[?] Unknown or unsupported object type: {obj_type}")
        print(f"    Supported types: {', '.join(sorted(OBJECT_TYPES))}")
        return

    exclude = own_files_of(extension_path, spec["dir"], name)
    own_content = has_own_ext_content(extension_path, spec["dir"], name)

    print(f"=== {obj_type}.{name} ===")
    if own_content:
        print("  [OWN CONTENT] object has its own Ext/ presence (module/form/template) — "
              "adoption is self-explanatory regardless of external references; "
              "see cfe-diff -Mode A for exact own-attrs/own-TS/own-forms counts.")

    type_hits = []
    if spec["ref"]:
        ref_token = f"{spec['ref']}.{name}"
        type_hits = search_token(extension_path, (".xml",), ref_token, exclude)
        if type_hits:
            print(f"  [TYPE REFERENCE] {ref_token} used as a composite/simple type"
                  f" in {len(type_hits)} place(s) (hard platform requirement):")
            for rel, line_no, text in type_hits:
                print(f"      {rel}:{line_no}")
        else:
            print(f"  [TYPE REFERENCE] none found for {ref_token}")
    else:
        print("  [TYPE REFERENCE] not applicable (registers have no Ref type)")

    # Manager-style code ("Справочники.X.СоздатьЭлемент()") only ever appears in .bsl
    # modules. Query-style table names ("ИЗ Справочник.X") appear both in .bsl query
    # text AND inside DCS report schemas embedded as XML (Reports/*/Templates/*/Ext/
    # Template.xml) — a report's query is not a .bsl file, but it is exactly the kind
    # of "code reference" this tool is meant to catch.
    #
    # A third, separate form — metadata lookup by reference ("Метаданные.Справочники.X",
    # "Метаданные.Документы.X") — needs its own search_plan entry rather than being
    # caught by the manager-style search above: search_token's word-boundary regex
    # uses `(?<![\w.])` before the token, which deliberately rejects a match preceded
    # by a bare word character but, as a side effect, also rejects one preceded by a
    # dot. "Метаданные." is exactly such a preceding dot, so "Справочники.X" alone
    # never matches inside "Метаданные.Справочники.X" — the fix is to search for the
    # full "Метаданные.<manager>.<name>" string as its own literal token (its own
    # start, "М" of "Метаданные", is not preceded by a dot). Found and fixed while
    # auditing a real 1C extension: a RIB registration dispatcher enumerated dozens
    # of objects exactly this way, and the pre-fix tool reported all of them as
    # "NO REFERENCE FOUND". See docs/reference-finder.md -> Provenance.
    code_hits = []
    search_plan = (
        (spec["manager"], "manager", (".bsl",)),
        (spec["query"], "query", (".bsl", ".xml")),
        (f"Метаданные.{spec['manager']}", "metadata", (".bsl",)),
    )
    for form, label, extensions in search_plan:
        token = f"{form}.{name}"
        hits = search_token(extension_path, extensions, token, exclude)
        code_hits.extend(hits)
        if hits:
            print(f"  [CODE REFERENCE] {token} used in {len(hits)} place(s) ({label}-style):")
            for rel, line_no, text in hits:
                print(f"      {rel}:{line_no}: {text}")

    if not code_hits:
        print(f"  [CODE REFERENCE] none found for {spec['manager']}.{name} / {spec['query']}.{name}")

    if type_hits:
        print("  VERDICT: explained — composite-type reference (adoption is structurally required).")
    elif code_hits:
        print("  VERDICT: explained — code/query reference only (adoption reflects the author's "
              "choice, not a hard platform requirement; safe to reconsider if the referencing "
              "code is itself removed).")
    elif own_content:
        print("  VERDICT: explained — own Ext content (see [OWN CONTENT] above); no external "
              "reference needed or found.")
    else:
        print("  VERDICT: NO REFERENCE FOUND and no own Ext content — candidate for exclusion "
              "from the extension (unless a reference lives in a source this tool does not scan, "
              "e.g. a compiled form layout or a role/subsystem composition list — verify before removing).")
    print()


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(
        description="Find why a 1C extension adopted a base-config object with no own changes "
                    "(composite-type reference vs code/query reference).",
        allow_abbrev=False,
    )
    parser.add_argument("-ExtensionPath", required=True, help="Path to extension dump root")
    parser.add_argument(
        "-Object", required=True,
        help='One or more "Type.Name" entries, ";;"-separated, '
             'e.g. "Catalog.ИмяСправочника;;AccumulationRegister.ИмяРегистра"',
    )
    args = parser.parse_args()

    extension_path = args.ExtensionPath
    if not os.path.isabs(extension_path):
        extension_path = os.path.join(os.getcwd(), extension_path)
    if not os.path.isdir(extension_path):
        print(f"Extension path not found: {extension_path}", file=sys.stderr)
        sys.exit(1)

    for entry in args.Object.split(";;"):
        entry = entry.strip()
        if not entry:
            continue
        if "." not in entry:
            print(f"[?] Malformed -Object entry (expected Type.Name): {entry}", file=sys.stderr)
            continue
        obj_type, name = entry.split(".", 1)
        analyze_object(extension_path, obj_type, name)


if __name__ == "__main__":
    main()
