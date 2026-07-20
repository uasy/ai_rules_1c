#!/usr/bin/env python3
# registry-builder v1.0 — build the "change registry" required by
# ../../SKILL.md workflow step 1: one row per atomic own change (own attribute /
# own tabular section / own interceptor), generated directly from the extension
# source tree, not from a search for an already-known pattern name.
#
# Companion to 1c-reference-finder / 1c-enum-value-checker / 1c-defined-type-
# dispatch-checker / 1c-broken-metadata-path-checker / 1c-dead-code-after-insert-
# checker (same skill: 1c-extension-analysis). Born from a concrete methodology
# gap found while auditing a real 1C extension (see docs/registry-builder.md ->
# Provenance for the exact case): a document's second, differently-named own
# interceptor (registering data into an unrelated typical register) was missed
# by every pass that searched for a single already-known interceptor name
# (e.g. "ИК_ПриЗаписи") across the tree instead of enumerating everything a
# given object actually owns. A name-search can only ever find what you already
# think to look for; this tool enumerates what is actually there.
#
# Two modes:
#   1. Generate (default) — walk the extension, print one row per own change,
#      leaving the "Блок" column for the analyst to fill in during step 3.
#   2. Compare (-CompareAgainst <file>) — additionally check whether each
#      generated object name still appears somewhere in an already-written
#      report/registry file, and flag the ones that do not (the same output,
#      minus the ones already accounted for). This is a coverage check, not a
#      strict per-row structural diff — it only proves an object was not even
#      mentioned, not that its every mechanism was individually addressed
#      inside the mentioning text (see docs/registry-builder.md -> Known gaps).
#
# Dispatcher detection: an interceptor whose own body contains more than one
# comparison against metadata identity/type (`ОбъектМетаданных = Метаданные.X`,
# `ТипЗнч(...) = Тип(...)`) is flagged instead of emitted as a single row —
# SKILL.md step 1 requires decomposing such a procedure by unique branch shape,
# which needs a human to read the branches and group them; the tool only says
# where to look and how many branches there are.

import argparse
import os
import re
import sys
from lxml import etree

MD_NSMAP = {
    "md": "http://v8.1c.ru/8.3/MDClasses",
}
FORM_NSMAP = {
    "f": "http://v8.1c.ru/8.3/xcf/logform",
}

# Same type -> directory mapping as 1c-metadata-manage's cfe-diff.py, kept as an
# independent copy on purpose — this skill's tools are self-contained and do not
# import across skill boundaries (see AGENTS.md -> Surgical Changes).
CHILD_TYPE_DIR_MAP = {
    "Catalog": "Catalogs",
    "Document": "Documents",
    "Enum": "Enums",
    "CommonModule": "CommonModules",
    "CommonPicture": "CommonPictures",
    "CommonCommand": "CommonCommands",
    "CommonTemplate": "CommonTemplates",
    "ExchangePlan": "ExchangePlans",
    "Report": "Reports",
    "DataProcessor": "DataProcessors",
    "InformationRegister": "InformationRegisters",
    "AccumulationRegister": "AccumulationRegisters",
    "ChartOfCharacteristicTypes": "ChartsOfCharacteristicTypes",
    "ChartOfAccounts": "ChartsOfAccounts",
    "AccountingRegister": "AccountingRegisters",
    "ChartOfCalculationTypes": "ChartsOfCalculationTypes",
    "CalculationRegister": "CalculationRegisters",
    "BusinessProcess": "BusinessProcesses",
    "Task": "Tasks",
    "Subsystem": "Subsystems",
    "Role": "Roles",
    "Constant": "Constants",
    "FunctionalOption": "FunctionalOptions",
    "DefinedType": "DefinedTypes",
    "FunctionalOptionsParameter": "FunctionalOptionsParameters",
    "CommonForm": "CommonForms",
    "DocumentJournal": "DocumentJournals",
    "SessionParameter": "SessionParameters",
    "StyleItem": "StyleItems",
    "EventSubscription": "EventSubscriptions",
    "ScheduledJob": "ScheduledJobs",
    "SettingsStorage": "SettingsStorages",
    "FilterCriterion": "FilterCriteria",
    "CommandGroup": "CommandGroups",
    "DocumentNumerator": "DocumentNumerators",
    "Sequence": "Sequences",
    "IntegrationService": "IntegrationServices",
    "CommonAttribute": "CommonAttributes",
}

RE_INTERCEPTOR = re.compile(
    r'^&(Перед|После|ИзменениеИКонтроль|Вместо)\("([^"]+)"\)'
)
RE_ROUTINE_START = re.compile(r"^\s*(Функция|Процедура)\s+(\S+?)\s*\(", re.IGNORECASE)
RE_ROUTINE_END = re.compile(r"^(КонецФункции|КонецПроцедуры);?$", re.IGNORECASE)
RE_DISPATCH_BRANCH = re.compile(
    r"ОбъектМетаданных\s*=\s*Метаданные\.|ТипЗнч\([^)]*\)\s*=\s*Тип\("
)


def strip_comment(line):
    idx = line.find("//")
    return line if idx == -1 else line[:idx]


def read_lines(path):
    try:
        with open(path, "r", encoding="utf-8-sig", errors="replace") as fh:
            return fh.readlines()
    except OSError:
        return []


def find_object_xml(ext_path, type_dir, name):
    return os.path.join(ext_path, type_dir, f"{name}.xml")


def get_own_children(obj_xml_path):
    """Returns (own_attr_names, own_ts_names) from top-level ChildObjects,
    skipping anything with ObjectBelonging=Adopted. Absence of the tag entirely
    (own object, not a borrowed one) is treated as "everything is own" — the
    caller is expected to already know whether the object itself is borrowed."""
    if not os.path.isfile(obj_xml_path):
        return [], []
    try:
        doc = etree.parse(obj_xml_path, etree.XMLParser(remove_blank_text=False))
    except Exception:
        return [], []
    root = doc.getroot()
    obj_el = next((c for c in root if isinstance(c.tag, str)), None)
    if obj_el is None:
        return [], []
    child_obj = obj_el.find("md:ChildObjects", MD_NSMAP)
    if child_obj is None:
        return [], []

    own_attrs, own_ts = [], []
    for c in child_obj:
        if not isinstance(c.tag, str):
            continue
        local = etree.QName(c.tag).localname
        if local not in ("Attribute", "TabularSection"):
            continue
        props = c.find("md:Properties", MD_NSMAP)
        belonging = None
        name_el = None
        if props is not None:
            ob = props.find("md:ObjectBelonging", MD_NSMAP)
            belonging = ob.text if ob is not None else None
            name_el = props.find("md:Name", MD_NSMAP)
        if belonging == "Adopted":
            continue
        cname = name_el.text if name_el is not None else "?"
        (own_ts if local == "TabularSection" else own_attrs).append(cname)
    return own_attrs, own_ts


def is_borrowed(obj_xml_path):
    if not os.path.isfile(obj_xml_path):
        return None
    try:
        doc = etree.parse(obj_xml_path, etree.XMLParser(remove_blank_text=False))
    except Exception:
        return None
    root = doc.getroot()
    obj_el = next((c for c in root if isinstance(c.tag, str)), None)
    if obj_el is None:
        return None
    props = obj_el.find("md:Properties", MD_NSMAP)
    if props is None:
        return False
    ob = props.find("md:ObjectBelonging", MD_NSMAP)
    return ob is not None and ob.text == "Adopted"


def find_own_bsl_files(ext_path, type_dir, name):
    """ObjectModule/ManagerModule/RecordSetModule/ValueManagerModule/CommandModule
    plus every Form's Module.bsl, relative to the object's own directory."""
    obj_dir = os.path.join(ext_path, type_dir, name)
    if not os.path.isdir(obj_dir):
        return []
    files = []
    ext_dir = os.path.join(obj_dir, "Ext")
    if os.path.isdir(ext_dir):
        for fn in os.listdir(ext_dir):
            if fn.lower().endswith(".bsl"):
                files.append(os.path.join(ext_dir, fn))
    forms_dir = os.path.join(obj_dir, "Forms")
    if os.path.isdir(forms_dir):
        for dirpath, _dirnames, filenames in os.walk(forms_dir):
            for fn in filenames:
                if fn == "Module.bsl":
                    files.append(os.path.join(dirpath, fn))
    return files


def scan_bsl_for_interceptors(bsl_path):
    """Returns a list of dicts: {Type, Method, Line, DispatchBranches}.
    DispatchBranches > 1 means the routine's own body should be decomposed by
    branch instead of emitted as one registry row (SKILL.md step 1 rule)."""
    lines = read_lines(bsl_path)
    results = []
    i = 0
    n = len(lines)
    while i < n:
        stripped = strip_comment(lines[i]).strip()
        m = RE_INTERCEPTOR.match(stripped)
        if not m:
            i += 1
            continue
        itype, method = m.group(1), m.group(2)
        # Find the routine body that follows (may be a couple of lines below the
        # annotation if compilation directives sit in between).
        j = i + 1
        while j < n and not RE_ROUTINE_START.match(strip_comment(lines[j]).strip()):
            j += 1
        body_start = j
        body_end = n - 1
        for k in range(body_start, n):
            if RE_ROUTINE_END.match(strip_comment(lines[k]).strip()):
                body_end = k
                break
        branch_count = 0
        for k in range(body_start, body_end + 1):
            branch_count += len(RE_DISPATCH_BRANCH.findall(lines[k]))
        results.append({
            "Type": itype,
            "Method": method,
            "Line": i + 1,
            "DispatchBranches": branch_count,
        })
        i = body_end + 1
    return results


def scan_bsl_for_all_routines(bsl_path):
    """Plain enumeration of every Процедура/Функция name — used for own form
    modules, where own logic is frequently a plain event-bound procedure, not an
    extension interceptor annotation at all (the form itself is new, so there is
    nothing typical to intercept)."""
    lines = read_lines(bsl_path)
    names = []
    for line in lines:
        m = RE_ROUTINE_START.match(strip_comment(line).strip())
        if m:
            names.append(m.group(2))
    return names


def iter_objects(ext_path):
    for type_name, dir_name in CHILD_TYPE_DIR_MAP.items():
        type_dir = os.path.join(ext_path, dir_name)
        if not os.path.isdir(type_dir):
            continue
        for fn in os.listdir(type_dir):
            if fn.lower().endswith(".xml"):
                yield type_name, dir_name, fn[:-4]


def build_registry(ext_path, only_object=None):
    rows = []
    for type_name, type_dir, name in iter_objects(ext_path):
        if only_object and f"{type_name}.{name}" != only_object:
            continue
        obj_xml = find_object_xml(ext_path, type_dir, name)
        borrowed = is_borrowed(obj_xml)
        if borrowed is None:
            continue

        own_attrs, own_ts = get_own_children(obj_xml)
        for a in own_attrs:
            rows.append({"Object": f"{type_name}.{name}", "Mechanism": f"own attribute: {a}", "Block": ""})
        for t in own_ts:
            rows.append({"Object": f"{type_name}.{name}", "Mechanism": f"own tabular section: {t}", "Block": ""})

        for bsl in find_own_bsl_files(ext_path, type_dir, name):
            is_form_module = os.sep + "Forms" + os.sep in bsl
            interceptors = scan_bsl_for_interceptors(bsl)
            rel = os.path.relpath(bsl, ext_path)
            if interceptors:
                for ic in interceptors:
                    if ic["DispatchBranches"] > 1:
                        rows.append({
                            "Object": f"{type_name}.{name}",
                            "Mechanism": (
                                f'DISPATCHER &{ic["Type"]}("{ic["Method"]}") at {rel}:{ic["Line"]} — '
                                f'{ic["DispatchBranches"]} metadata-comparison branches, '
                                f'decompose by unique shape before assigning Блок'
                            ),
                            "Block": "",
                        })
                    else:
                        rows.append({
                            "Object": f"{type_name}.{name}",
                            "Mechanism": f'&{ic["Type"]}("{ic["Method"]}") at {rel}:{ic["Line"]}',
                            "Block": "",
                        })
            elif is_form_module:
                own_routines = scan_bsl_for_all_routines(bsl)
                if own_routines:
                    rows.append({
                        "Object": f"{type_name}.{name}",
                        "Mechanism": (
                            f"own form module {rel} — {len(own_routines)} routine(s), "
                            f"no interceptor annotations (likely a wholly-own form; "
                            f"read event bindings in the matching Form.xml manually): "
                            + ", ".join(own_routines[:12])
                            + (", ..." if len(own_routines) > 12 else "")
                        ),
                        "Block": "",
                    })
    return rows


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(
        description="Build the change registry required by SKILL.md step 1 directly "
                    "from the extension source (own attrs/TS/interceptors/forms), "
                    "instead of from a search for an already-known pattern name.",
        allow_abbrev=False,
    )
    parser.add_argument("-ExtensionPath", required=True, help="Path to extension source dump")
    parser.add_argument("-Object", default=None, help='Scope to one object, e.g. "Document.ПереносОтпуска"')
    parser.add_argument(
        "-CompareAgainst", default=None,
        help="Path to an already-written report/registry Markdown file; flags objects "
             "generated here that are not even mentioned anywhere in that file",
    )
    args = parser.parse_args()

    ext_path = args.ExtensionPath
    if not os.path.isabs(ext_path):
        ext_path = os.path.join(os.getcwd(), ext_path)
    if not os.path.isdir(ext_path):
        print(f"Extension path not found: {ext_path}", file=sys.stderr)
        sys.exit(1)

    rows = build_registry(ext_path, only_object=args.Object)

    report_text = None
    if args.CompareAgainst:
        cmp_path = args.CompareAgainst
        if not os.path.isabs(cmp_path):
            cmp_path = os.path.join(os.getcwd(), cmp_path)
        if not os.path.isfile(cmp_path):
            print(f"-CompareAgainst file not found: {cmp_path}", file=sys.stderr)
            sys.exit(1)
        with open(cmp_path, "r", encoding="utf-8", errors="replace") as fh:
            report_text = fh.read()

    if report_text is not None:
        missing = [r for r in rows if r["Object"] not in report_text]
        print(f"=== {len(missing)} object(s) generated from source but NOT mentioned anywhere in "
              f"{os.path.basename(args.CompareAgainst)} ===")
        print("(Coverage check only — an object's name appearing in the file does not by itself\n"
              " prove every one of its own mechanisms was individually addressed there.)\n")
        for r in missing:
            print(f"  [NOT IN REPORT] {r['Object']} — {r['Mechanism']}")
        print()
        print(f"=== {len(rows)} row(s) generated in total, {len(rows) - len(missing)} object(s) at "
              f"least mentioned in the report ===")
        return

    current_object = None
    for r in rows:
        if r["Object"] != current_object:
            if current_object is not None:
                print()
            print(f"=== {r['Object']} ===")
            current_object = r["Object"]
        print(f"  | {r['Mechanism']} | Блок: {r['Block'] or '(fill in)'}")

    print()
    print(f"=== {len(rows)} row(s) generated — every row needs a non-empty Блок before the "
          f"analysis counts as complete (SKILL.md step 5) ===")


if __name__ == "__main__":
    main()
