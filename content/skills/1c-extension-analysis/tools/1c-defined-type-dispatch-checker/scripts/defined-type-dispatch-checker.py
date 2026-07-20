#!/usr/bin/env python3
# defined-type-dispatch-checker v1.0 — find a BSL dispatch chain (Если ТипЗнч(Х) =
# Тип("...") ИначеЕсли ... Иначе ВызватьИсключение) that does not handle every type
# actually listed in a DefinedType's composition.
#
# Companion to 1c-reference-finder / 1c-enum-value-checker (same skill:
# 1c-extension-analysis). Born from a concrete bug found while auditing a real 1C
# extension: a dispatch function branched on ТипЗнч(Параметр) against every member of
# a DefinedType, with a hand-maintained comment listing every member with +/- markers
# ("handled" / "consciously not handled") — but one member was not mentioned in the
# comment at all and was not handled by any Если/ИначеЕсли branch, while the
# function's Иначе branch unconditionally ВызватьИсключение's on any unrecognized
# type. If that type is ever passed in (directly, or via RIB registration), the
# function raises. This was found only by a human diffing the hand-written comment
# against the DefinedType's real XML composition, line by line — exactly the kind of
# manual cross-check this tool automates. See docs/defined-type-dispatch-checker.md
# -> Provenance for the exact case.
#
# IMPORTANT — read before trusting a "missing" verdict on an Adopted DefinedType:
# an extension's own copy of a typical (Adopted) DefinedType can be a stale
# snapshot with FEWER <v8:Type> entries than the base configuration currently
# declares (confirmed in practice — see docs/defined-type-dispatch-checker.md ->
# Provenance for the case that surfaced this). This tool resolves composition the
# same way enum-value-checker.py resolves enum values: base config wins for
# Adopted objects whenever -ConfigPath is available. See
# docs/defined-type-dispatch-checker.md.

import argparse
import os
import re
import sys
from lxml import etree

MD_NSMAP = {
    "md": "http://v8.1c.ru/8.3/MDClasses",
    "v8": "http://v8.1c.ru/8.1/data/core",
}

# Ref-type prefix (as it appears inside <v8:Type>cfg:XRef.Name</v8:Type>) -> the
# Cyrillic "<Kind>Ссылка" token used inside a BSL Тип("...") string literal.
REF_TO_QUERY = {
    "CatalogRef": "СправочникСсылка",
    "DocumentRef": "ДокументСсылка",
    "EnumRef": "ПеречислениеСсылка",
    "ChartOfCharacteristicTypesRef": "ПланВидовХарактеристикСсылка",
    "ChartOfAccountsRef": "ПланСчетовСсылка",
    "ChartOfCalculationTypesRef": "ПланВидовРасчетаСсылка",
    "BusinessProcessRef": "БизнесПроцессСсылка",
    "TaskRef": "ЗадачаСсылка",
    "ExchangePlanRef": "ПланОбменаСсылка",
}

RE_TYPE_ENTRY = re.compile(r"^(?:cfg:)?(\w+Ref)\.(.+)$")


def parse_defined_type_file(xml_path):
    """Parses one DefinedTypes/<Name>.xml. Returns (is_adopted, raw_type_strings) or
    (None, None) if unparseable. raw_type_strings are the literal <v8:Type> texts,
    e.g. "cfg:CatalogRef.ФизическиеЛица"."""
    try:
        parser_xml = etree.XMLParser(remove_blank_text=False)
        doc = etree.parse(xml_path, parser_xml)
    except Exception:
        return None, None
    root_el = doc.getroot()
    dt_el = None
    for c in root_el:
        if isinstance(c.tag, str):
            dt_el = c
            break
    if dt_el is None:
        return False, []

    props = dt_el.find("md:Properties", MD_NSMAP)
    ob_node = props.find("md:ObjectBelonging", MD_NSMAP) if props is not None else None
    is_adopted = ob_node is not None and ob_node.text == "Adopted"

    type_el = props.find("md:Type", MD_NSMAP) if props is not None else None
    raw_types = []
    if type_el is not None:
        for t in type_el.findall("v8:Type", MD_NSMAP):
            if t.text:
                raw_types.append(t.text.strip())
    return is_adopted, raw_types


def load_composition(extension_path, config_path, defined_type_name):
    """Same Adopted-vs-Own resolution priority as enum-value-checker.py's
    load_enum_values — see the module docstring above for why this matters.
    Returns (raw_type_strings_or_None, note)."""
    ext_xml = os.path.join(extension_path, "DefinedTypes", f"{defined_type_name}.xml") if extension_path else None
    ext_adopted, ext_types = (None, None)
    if ext_xml and os.path.isfile(ext_xml):
        ext_adopted, ext_types = parse_defined_type_file(ext_xml)

    base_xml = os.path.join(config_path, "DefinedTypes", f"{defined_type_name}.xml") if config_path else None
    base_types = None
    if base_xml and os.path.isfile(base_xml):
        _base_adopted, base_types = parse_defined_type_file(base_xml)

    if ext_xml and os.path.isfile(ext_xml) and ext_adopted is False:
        return ext_types, f"own to extension ({len(ext_types)} type(s), {ext_xml})"

    if ext_adopted and base_types is not None:
        return base_types, (
            f"base config, authoritative — extension's own Adopted snapshot has "
            f"{len(ext_types)} type(s) and was NOT used (may be stale), base has "
            f"{len(base_types)} ({base_xml})"
        )

    if ext_adopted and ext_types is not None:
        return ext_types, (
            f"extension's Adopted snapshot ({len(ext_types)} type(s), {ext_xml}) "
            f"— UNVERIFIED against base config (no -ConfigPath given or file "
            f"missing there); this snapshot can be stale, see tool docs"
        )

    if base_types is not None:
        return base_types, f"base config ({len(base_types)} type(s), {base_xml})"

    return None, "not found in extension" + (" or base config" if config_path else " (no -ConfigPath given)")


def to_dispatch_token(raw_type):
    """Converts "cfg:CatalogRef.ИмяСправочника" -> ("СправочникСсылка.ИмяСправочника",
    None), or (None, raw_type) when the type is not a recognized reference type
    (primitive types like xs:string, or an unrecognized/new Ref prefix) — such
    entries are reported separately, not counted as missing dispatch coverage."""
    m = RE_TYPE_ENTRY.match(raw_type)
    if not m:
        return None, raw_type
    ref_prefix, name = m.group(1), m.group(2)
    query = REF_TO_QUERY.get(ref_prefix)
    if query is None:
        return None, raw_type
    return f"{query}.{name}", None


def extract_routine_body(bsl_path, function_name):
    """Extracts the line range of one Функция/Процедура <function_name> ... КонецФункции
    /КонецПроцедуры from a .bsl file. Returns (start_line, end_line, text) or None if
    not found. Simple line-based state machine — 1C does not nest routine
    declarations, so this is unambiguous."""
    with open(bsl_path, "r", encoding="utf-8-sig", errors="replace") as fh:
        lines = fh.readlines()

    start_pattern = re.compile(
        r"^\s*(Функция|Процедура)\s+" + re.escape(function_name) + r"\s*\(",
        re.IGNORECASE,
    )
    start_idx = None
    for i, line in enumerate(lines):
        if start_pattern.match(line):
            start_idx = i
            break
    if start_idx is None:
        return None

    for j in range(start_idx, len(lines)):
        stripped = lines[j].strip().rstrip(";").strip()
        if stripped in ("КонецФункции", "КонецПроцедуры"):
            return start_idx + 1, j + 1, "".join(lines[start_idx:j + 1])
    return start_idx + 1, len(lines), "".join(lines[start_idx:])


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(
        description="Find DefinedType members not handled by a BSL Если ТипЗнч(...) "
                    "= Тип(...) dispatch chain.",
        allow_abbrev=False,
    )
    parser.add_argument("-ExtensionPath", required=True, help="Path to extension source dump")
    parser.add_argument(
        "-ConfigPath", default=None,
        help="Path to base configuration source dump (strongly recommended — see "
             "docs/defined-type-dispatch-checker.md, Adopted DefinedTypes can be "
             "stale in the extension's own copy)",
    )
    parser.add_argument("-DefinedType", required=True, help="DefinedType name, e.g. ИмяОпределяемогоТипа")
    parser.add_argument("-BslFile", required=True, help="Path to the .bsl module containing the dispatch function")
    parser.add_argument(
        "-Function", default=None,
        help="Name of the Функция/Процедура to scope the search to (recommended); "
             "if omitted, the whole file is scanned",
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

    bsl_path = args.BslFile
    if not os.path.isabs(bsl_path):
        bsl_path = os.path.join(os.getcwd(), bsl_path)
    if not os.path.isfile(bsl_path):
        print(f"BSL file not found: {bsl_path}", file=sys.stderr)
        sys.exit(1)

    raw_types, note = load_composition(extension_path, config_path, args.DefinedType)
    print(f"=== DefinedType.{args.DefinedType} ===")
    if raw_types is None:
        print(f"  [?] {note}")
        sys.exit(1)
    print(f"  Composition ({note}):")

    if args.Function:
        extracted = extract_routine_body(bsl_path, args.Function)
        if extracted is None:
            print(f"  [?] Функция/Процедура '{args.Function}' not found in {bsl_path}", file=sys.stderr)
            sys.exit(1)
        start_line, end_line, body = extracted
        print(f"  Scanning {args.Function} ({bsl_path}:{start_line}-{end_line})")
    else:
        with open(bsl_path, "r", encoding="utf-8-sig", errors="replace") as fh:
            body = fh.read()
        print(f"  Scanning whole file ({bsl_path})")

    # Bounded window (not full-body DOTALL) so an unrelated "Иначе" far earlier in a
    # large routine can't pair with an unrelated "ВызватьИсключение" far later.
    # 200 chars comfortably spans a couple of comment/blank lines between the two
    # (e.g. "Иначе \n\t// Защита\n\tВызватьИсключение ...", the real pattern found in
    # the dispatcher this tool was validated against) without scanning across
    # unrelated code.
    has_defensive_raise = bool(
        re.search(r"Иначе\b[\s\S]{0,200}?ВызватьИсключение", body, re.IGNORECASE)
    )

    handled, missing, skipped = [], [], []
    for raw_type in raw_types:
        token, unrecognized = to_dispatch_token(raw_type)
        if unrecognized:
            skipped.append(unrecognized)
            continue
        pattern = re.compile(r'Тип\(\s*"' + re.escape(token) + r'"\s*\)')
        if pattern.search(body):
            handled.append(token)
        else:
            missing.append(token)

    print(f"  {len(handled)} handled, {len(missing)} NOT handled, {len(skipped)} skipped (non-reference / unrecognized type)")
    if skipped:
        print(f"  Skipped (not a recognized Ref type — verify manually if relevant): {', '.join(skipped)}")
    if missing:
        print("  [MISSING] not referenced anywhere as Тип(\"...\") in the scanned scope:")
        for token in missing:
            print(f"      {token}")
        if has_defensive_raise:
            print("  RISK: the scanned scope contains an Иначе ... ВызватьИсключение branch — "
                  "any of the missing types above will raise an exception at runtime if it is "
                  "ever passed in (e.g. via RIB registration of an object of that type).")
        else:
            print("  No unconditional Иначе ВызватьИсключение detected in the scanned scope — "
                  "missing types likely fall through silently instead of raising; verify the "
                  "actual Иначе branch (or absence of one) manually.")
    else:
        print("  All composition members are handled in the scanned scope.")


if __name__ == "__main__":
    main()
