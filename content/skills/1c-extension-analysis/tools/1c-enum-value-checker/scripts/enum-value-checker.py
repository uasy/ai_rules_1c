#!/usr/bin/env python3
# enum-value-checker v1.0 — find BSL references to enum values that do not exist in
# the enum's actual declared value list.
#
# Companion to 1c-reference-finder (same skill: 1c-extension-analysis). Born from a
# concrete bug found while auditing a real 1C extension: an interceptor wrote a
# hardcoded enum-value literal that did not actually exist in the enum's declared
# value list. That reference was found only by a human reading both the code and the
# enum's XML side by side; grep-based passes over a large extension (hundreds of
# objects) do not surface this on their own, because the literal parses fine as valid
# BSL syntax and only fails at the metadata level. This tool automates exactly that
# side-by-side comparison. See docs/enum-value-checker.md -> Provenance for the exact
# case that motivated it.
#
# Two BSL forms are checked:
#   1. Manager-style access:  Перечисления.<Enum>.<Value>
#   2. String-literal form:   ПредопределенноеЗначение("Перечисление.<Enum>.<Value>")
#
# For every distinct <Enum> encountered, the tool resolves the enum's declared values
# from Enums/<Enum>.xml — checked in the extension tree first, then (if -ConfigPath is
# given) the base configuration tree — and flags any <Value> not present there.

import argparse
import os
import re
import sys
from lxml import etree

MD_NSMAP = {
    "md": "http://v8.1c.ru/8.3/MDClasses",
}

# Matches "Перечисления.<Enum>.<Value>" — manager-collection style, the form used when
# assigning/comparing an enum value directly (e.g. "Объект.Статус = Перечисления.X.Y").
# Two trailing lookaheads on the value group, in this order:
#   (?![A-Za-z...]) — forbids the greedy `+` from backtracking one character short
#   just to satisfy the next assertion (without this, a value immediately followed by
#   "(" gets matched one character shorter than the real identifier, still "passing"
#   the "not followed by (" check on the truncated tail — confirmed to happen in
#   practice against a real manager-module method call).
#   (?!\s*\() — excludes "Перечисления.X.Y(args)": enums can have their own
#   manager-module export functions (Enums/<Enum>/Ext/ManagerModule.bsl), and
#   "Перечисления.X.МетодМенеджера(...)" calls one of those, not a value literal.
#   Confirmed false-positive class while validating this tool: a real enum's manager
#   module exported its own functions, called via this exact syntax.
RE_MANAGER = re.compile(
    r"(?<!\w)Перечисления\.([A-Za-zА-Яа-яЁё0-9_]+)\."
    r"([A-Za-zА-Яа-яЁё0-9_]+)(?![A-Za-zА-Яа-яЁё0-9_])(?!\s*\()"
)

# Matches the string-literal form passed to ПредопределенноеЗначение(...).
RE_PREDEFINED = re.compile(
    r'"Перечисление\.([A-Za-zА-Яа-яЁё0-9_]+)\.([A-Za-zА-Яа-яЁё0-9_]+)"'
)


def strip_comment(line):
    """Cut a line at the first '//'. Does not track string-literal context (a '//'
    inside a quoted string would be mis-cut) — same accepted trade-off as
    reference-finder.py's word-bounded search; read the printed line before
    concluding, per that tool's own documented limitation."""
    idx = line.find("//")
    return line if idx == -1 else line[:idx]


def find_bsl_files(root):
    for dirpath, _dirnames, filenames in os.walk(root):
        for fn in filenames:
            if fn.lower().endswith(".bsl"):
                yield os.path.join(dirpath, fn)


def scan_hits(root):
    """Word-bounded scan for both enum-value literal forms across every .bsl file
    under root. Returns a list of dicts: enum, value, file (relative to root), line,
    matched text, form ('manager'|'predefined')."""
    hits = []
    for path in find_bsl_files(root):
        try:
            with open(path, "r", encoding="utf-8-sig", errors="replace") as fh:
                for i, raw_line in enumerate(fh, start=1):
                    line = strip_comment(raw_line)
                    for m in RE_MANAGER.finditer(line):
                        hits.append({
                            "enum": m.group(1),
                            "value": m.group(2),
                            "file": os.path.relpath(path, root),
                            "line": i,
                            "text": raw_line.strip(),
                            "form": "manager",
                        })
                    for m in RE_PREDEFINED.finditer(line):
                        hits.append({
                            "enum": m.group(1),
                            "value": m.group(2),
                            "file": os.path.relpath(path, root),
                            "line": i,
                            "text": raw_line.strip(),
                            "form": "predefined",
                        })
        except OSError:
            continue
    return hits


def parse_enum_file(xml_path):
    """Parses one Enums/<Name>.xml. Returns (is_adopted, values_set) or (None, None)
    if the file cannot be parsed. is_adopted reflects the <Enum>'s own
    <Properties><ObjectBelonging> — True only when explicitly "Adopted"."""
    try:
        parser_xml = etree.XMLParser(remove_blank_text=False)
        doc = etree.parse(xml_path, parser_xml)
    except Exception:
        return None, None
    root_el = doc.getroot()
    enum_el = None
    for c in root_el:
        if isinstance(c.tag, str):
            enum_el = c
            break
    if enum_el is None:
        return False, set()

    props = enum_el.find("md:Properties", MD_NSMAP)
    ob_node = props.find("md:ObjectBelonging", MD_NSMAP) if props is not None else None
    is_adopted = ob_node is not None and ob_node.text == "Adopted"

    child_obj = enum_el.find("md:ChildObjects", MD_NSMAP)
    values = set()
    if child_obj is not None:
        for c in child_obj:
            if not isinstance(c.tag, str):
                continue
            if etree.QName(c.tag).localname != "EnumValue":
                continue
            v_props = c.find("md:Properties", MD_NSMAP)
            name_el = v_props.find("md:Name", MD_NSMAP) if v_props is not None else None
            if name_el is not None and name_el.text:
                values.add(name_el.text)
    return is_adopted, values


def load_enum_values(extension_path, config_path, enum_name):
    """Resolves the authoritative declared value list for <enum_name>.

    Confirmed pitfall (found while validating this tool against a real extension,
    details intentionally not reproduced here to avoid disclosing a third party's
    codebase — see docs/enum-value-checker.md -> Provenance): an extension's own
    copy of an ADOPTED enum can be a stale snapshot — missing values the base
    configuration has genuinely declared since the extension last adopted the
    object. In the confirmed case, values referenced by BSL code that looked
    "missing" against the extension's own snapshot turned out to genuinely exist in
    the base config, so treating the extension's own snapshot as authoritative for
    an Adopted enum produces false "BROKEN" verdicts. This is exactly the kind of
    drift a customer typically worries about across a base-config update.

    Resolution order:
      - Enum is OWN in the extension (no ObjectBelonging=Adopted on the <Enum>
        itself) → the extension's own file is authoritative; it is the only
        declaration that exists.
      - Enum is ADOPTED in the extension and -ConfigPath was given and has the
        file → the base config's copy is authoritative (freshest declaration);
        the extension's own snapshot is not used at all, since it may be stale.
      - Enum is ADOPTED but no usable -ConfigPath is available → fall back to the
        extension's own (possibly stale) snapshot, with an explicit caveat in the
        returned note.

    Returns (values_set_or_None, note) where note describes the resolution and
    any caveat; values_set is None only when the enum could not be resolved from
    any available source.
    """
    ext_xml = os.path.join(extension_path, "Enums", f"{enum_name}.xml") if extension_path else None
    ext_adopted, ext_values = (None, None)
    if ext_xml and os.path.isfile(ext_xml):
        ext_adopted, ext_values = parse_enum_file(ext_xml)

    base_xml = os.path.join(config_path, "Enums", f"{enum_name}.xml") if config_path else None
    base_values = None
    if base_xml and os.path.isfile(base_xml):
        _base_adopted, base_values = parse_enum_file(base_xml)

    if ext_xml and os.path.isfile(ext_xml) and ext_adopted is False:
        return ext_values, f"own to extension ({len(ext_values)} value(s), {ext_xml})"

    if ext_adopted and base_values is not None:
        return base_values, (
            f"base config, authoritative — extension's own Adopted snapshot "
            f"has {len(ext_values)} value(s) and was NOT used (may be stale), "
            f"base has {len(base_values)} ({base_xml})"
        )

    if ext_adopted and ext_values is not None:
        return ext_values, (
            f"extension's Adopted snapshot ({len(ext_values)} value(s), {ext_xml}) "
            f"— UNVERIFIED against base config (no -ConfigPath given or file "
            f"missing there); this snapshot can be stale, see tool docs"
        )

    if base_values is not None:
        return base_values, f"base config ({len(base_values)} value(s), {base_xml})"

    return None, "not found in extension" + (" or base config" if config_path else " (no -ConfigPath given)")


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(
        description="Find BSL references to enum values that do not exist in the "
                    "enum's declared value list (Перечисления.X.Y / "
                    'ПредопределенноеЗначение("Перечисление.X.Y")).',
        allow_abbrev=False,
    )
    parser.add_argument("-ExtensionPath", required=True, help="Path to extension source dump")
    parser.add_argument(
        "-ConfigPath", default=None,
        help="Path to base configuration source dump (optional — needed to resolve "
             "enums that are typical/adopted rather than owned by the extension)",
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

    hits = scan_hits(extension_path)
    if not hits:
        print("No enum-value literals found (Перечисления.X.Y / "
              'ПредопределенноеЗначение("Перечисление.X.Y")) in this extension tree.')
        return

    by_enum = {}
    for hit in hits:
        by_enum.setdefault(hit["enum"], []).append(hit)

    total_broken = 0
    for enum_name in sorted(by_enum):
        enum_hits = by_enum[enum_name]
        values, note = load_enum_values(extension_path, config_path, enum_name)

        print(f"=== Enum.{enum_name} ===")
        if values is None:
            print(f"  [?] {note} — cannot verify, listing raw hits:")
            for h in enum_hits:
                print(f"      {h['file']}:{h['line']} ({h['form']}): {h['text']}")
            print()
            continue

        print(f"  Declared values ({note}):")
        print(f"    {', '.join(sorted(values)) or '(none)'}")

        for h in enum_hits:
            if h["value"] in values:
                status = "OK"
            else:
                status = "BROKEN — value does not exist"
                total_broken += 1
            print(f"  [{status}] {h['file']}:{h['line']} ({h['form']}): {h['text']}")
        print()

    if total_broken:
        print(f"=== {total_broken} broken enum-value reference(s) found ===")
    else:
        print("=== No broken enum-value references found ===")


if __name__ == "__main__":
    main()
