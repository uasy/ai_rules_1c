#!/usr/bin/env python3
# exchangeplan-content v1.0 — inspect and/or diff the composition (Ext/Content.xml) of a
# 1C exchange plan (ПланОбмена), including RIB (Обмен в распределенной информационной базе).
#
# General-purpose: works on any single source tree (Inspect mode) or two trees at once
# (Diff mode — typically base config vs extension, but any two trees work). Not tied to
# any specific extension or configuration.
#
# Platform grounding (verified via 1c_help_mcp / 1c-ssl-mcp before writing this tool):
#   - Ext/Content.xml is the authoritative source for "СоставПланаОбмена" (ExchangePlanContent)
#     — each <Item> pairs a <Metadata>Type.Name</Metadata> ref with an <AutoRecord> value
#     of Allow/Deny (platform type АвтоРегистрацияИзменений — only two values exist).
#   - AutoRecord=Deny does NOT mean "excluded from the exchange plan" — it means automatic
#     change-tracking is off for that object *in this plan*; the object is still nominally
#     part of the plan's content. Explicit registration typically happens via BSP's generic
#     dispatcher (ОбменДаннымиСобытия.МеханизмРегистрацииОбъектовПередЗаписьюРегистра /
#     ...ПередЗаписьюДокумента), wired through EventSubscriptions, which reads a separate
#     "registration rules" template (Templates/ПравилаРегистрации) owned by the plan itself
#     and calls ОбменДаннымиСобытия.ВыполнитьПравилаРегистрацииДляОбъекта(...).
#   - That registration-rules template mixes data (the rules) with code (the BSP dispatcher
#     + whatever extension/common-module code the rules invoke) — this tool does NOT parse
#     or diff its content. It only detects the template's presence and flags candidate BSL
#     locations (literal plan-name mentions) for manual reading. Treating "no template" or
#     "no code mention found" as proof of "no registration mechanism" would be exactly the
#     kind of unverified claim this project's tooling is built to avoid — don't do that.
#
# Companion to 1c-reference-finder (composite-type / code-query adoption reasons) and
# cfe-diff -Mode A (per-child ObjectBelonging). Neither of those tools reads exchange-plan
# content — this one is the gap-filler for that specific question.

import argparse
import os
import re
import sys
import xml.etree.ElementTree as ET


def _localname(tag):
    return tag.split("}", 1)[-1] if "}" in tag else tag


def content_xml_path(root, plan_name):
    return os.path.join(root, "ExchangePlans", plan_name, "Ext", "Content.xml")


def registration_rules_paths(root, plan_name):
    plan_dir = os.path.join(root, "ExchangePlans", plan_name)
    return (
        os.path.join(plan_dir, "Templates", "ПравилаРегистрации.xml"),
        os.path.join(plan_dir, "Templates", "ПравилаРегистрации"),
    )


def parse_content_xml(path):
    """Parse an Ext/Content.xml file into {metadata_ref: autorecord}. Returns None if the
    file does not exist (plan not present / not adopted in this tree, or genuinely has an
    empty declared content — both are legitimate, the caller decides how to report it)."""
    if not os.path.isfile(path):
        return None
    try:
        tree = ET.parse(path)
    except ET.ParseError as e:
        print(f"[!] Failed to parse {path}: {e}", file=sys.stderr)
        return None
    result = {}
    for item in tree.getroot():
        if _localname(item.tag) != "Item":
            continue
        metadata, autorecord = None, None
        for child in item:
            name = _localname(child.tag)
            if name == "Metadata":
                metadata = (child.text or "").strip()
            elif name == "AutoRecord":
                autorecord = (child.text or "").strip()
        if metadata:
            result[metadata] = autorecord
    return result


# Project-independent platform/BSP identifiers (not specific to any one plan or
# extension) — CommonModules/ОбменДаннымиСобытия is the standard БСП "Обмен данными"
# subsystem module, procedure ВыполнитьПравилаРегистрацииОбъектовДляПланаОбменаПопыткаИсключение.
# A substring match (not word-bounded) is used deliberately so it also catches an
# extension's own interceptor sharing the tail of the name (e.g. a prefixed
# <Префикс>ВыполнитьПравилаРегистрацииОбъектовДляПланаОбменаПопыткаИсключение via
# &ИзменениеИКонтроль).
BSP_REGISTRATION_DISPATCH_MARKERS = (
    "ВыполнитьПравилаРегистрацииОбъектовДляПланаОбмена",
    "МеханизмРегистрацииОбъектовПередЗаписью",
)

_bsp_dispatch_cache = {}


def find_bsp_dispatch_hits(root):
    """Tree-wide search (independent of any specific plan name) for the standard BSP
    'Обмен данными' subsystem registration-dispatch procedures. Confirmed structural
    fact: when a plan's own registration-rules template (Templates/ПравилаРегистрации)
    has zero rules for a given metadata object
    (`ПравилаРегистрацииОбъекта.Количество() = 0`), this dispatcher falls through to a
    hardcoded per-object BSL dispatch instead of reading the template. This means
    Content.xml's AutoRecord value alone can NEVER tell you which path (template rules
    vs. hardcoded BSL) an object actually takes for a given plan — only reading this
    dispatcher's body (and any extension interceptor on it) can. Cached per root since
    multiple -Plan values reuse the same tree-wide scan."""
    if root in _bsp_dispatch_cache:
        return _bsp_dispatch_cache[root]
    hits = []
    for dirpath, _dirnames, filenames in os.walk(root):
        for fn in filenames:
            if not fn.lower().endswith(".bsl"):
                continue
            path = os.path.join(dirpath, fn)
            try:
                with open(path, "r", encoding="utf-8-sig", errors="replace") as fh:
                    for i, line in enumerate(fh, start=1):
                        if any(marker in line for marker in BSP_REGISTRATION_DISPATCH_MARKERS):
                            hits.append((os.path.relpath(path, root), i, line.strip()))
            except OSError:
                continue
    _bsp_dispatch_cache[root] = hits
    return hits


def find_registration_code_hits(root, plan_name):
    """Best-effort, NOT exhaustive: word-bounded search for the plan name across .bsl
    files, as a starting point for manually locating where registration for this plan is
    wired (BSP dispatcher call, custom event-subscription handler, etc.). A hit is a
    candidate to read, not confirmed registration logic; an empty result does not prove
    the plan has no registration mechanism (it may be wired without a literal plan-name
    string, e.g. via a parameter passed down from elsewhere)."""
    pattern = re.compile(r"(?<![\w.])" + re.escape(plan_name) + r"(?![\w])", re.UNICODE)
    hits = []
    for dirpath, _dirnames, filenames in os.walk(root):
        for fn in filenames:
            if not fn.lower().endswith(".bsl"):
                continue
            path = os.path.join(dirpath, fn)
            try:
                with open(path, "r", encoding="utf-8-sig", errors="replace") as fh:
                    for i, line in enumerate(fh, start=1):
                        if pattern.search(line):
                            hits.append((os.path.relpath(path, root), i, line.strip()))
            except OSError:
                continue
    return hits


def inspect_tree(root, plan_name, label):
    print(f"--- {label}: {plan_name} ---")
    path = content_xml_path(root, plan_name)
    content = parse_content_xml(path)

    if content is None:
        print(f"  Content.xml not found at {os.path.relpath(path, root)} "
              f"(plan not present / not adopted in this tree, or exported without content)")
    else:
        print(f"  {len(content)} item(s) in Ext/Content.xml:")
        for metadata, autorecord in sorted(content.items()):
            print(f"    {metadata} — AutoRecord={autorecord}")

    rules_xml, rules_dir = registration_rules_paths(root, plan_name)
    rules_present = os.path.isfile(rules_xml) or os.path.isdir(rules_dir)
    print(f"  Registration-rules template (Templates/ПравилаРегистрации): "
          f"{'present' if rules_present else 'not found'} — "
          f"NOT parsed by this tool, read it directly if AutoRecord=Deny items need verification")

    dispatch_hits = find_bsp_dispatch_hits(root)
    if dispatch_hits:
        print(f"  BSP registration-dispatch code found in this tree ({len(dispatch_hits)} "
              f"location(s), plan-independent — read for ANY AutoRecord=Deny object above, "
              f"since an empty template rule set for that object falls through to hardcoded "
              f"BSL here rather than the template):")
        for rel, line_no, text in dispatch_hits:
            print(f"      {rel}:{line_no}: {text}")
    else:
        print("  No standard BSP registration-dispatch procedure found in this tree "
              "(this project may use a different/custom exchange mechanism, or this tree "
              "genuinely has none — the base tree normally has it if the 'Обмен данными' "
              "BSP subsystem is in use)")

    code_hits = find_registration_code_hits(root, plan_name)
    if code_hits:
        print(f"  Candidate registration code — {len(code_hits)} literal mention(s) of "
              f"'{plan_name}' in .bsl (read each before concluding anything):")
        for rel, line_no, text in code_hits:
            print(f"      {rel}:{line_no}: {text}")
    else:
        print(f"  No literal '{plan_name}' mentions found in .bsl — does not prove no "
              f"registration mechanism exists (it may be parameterized rather than literal)")
    print()
    return content


def diff_trees(base_content, ext_content, plan_name, new_objects):
    print(f"--- Diff: {plan_name} ---")
    if base_content is None and ext_content is None:
        print("  Plan absent from both trees — nothing to compare.\n")
        return
    base_content = base_content or {}
    ext_content = ext_content or {}

    base_keys = set(base_content)
    ext_keys = set(ext_content)

    added_by_ext = sorted(ext_keys - base_keys)
    only_in_base = sorted(base_keys - ext_keys)
    changed = sorted(k for k in (base_keys & ext_keys) if base_content[k] != ext_content[k])

    print("  NOTE: Ext/Content.xml declarations appear to be per-tree and additive, not a "
          "full replacement snapshot (verified empirically — every item found in a real "
          "extension's own Content.xml was itself an object added by that extension, not "
          "an overlap with the base list). Do NOT read 'only_in_base' below as 'removed by "
          "the extension' — it most likely just means the extension did not need to "
          "re-declare it. Only 'changed' entries are a genuine, unambiguous override.")

    if added_by_ext:
        print(f"\n  Declared only in the extension's own Content.xml ({len(added_by_ext)}):")
        for k in added_by_ext:
            print(f"    {k} — AutoRecord={ext_content[k]}")

    if only_in_base:
        print(f"\n  Declared only in the base's Content.xml ({len(only_in_base)}) — "
              f"see NOTE above, not evidence of removal:")
        for k in only_in_base[:20]:
            print(f"    {k} — AutoRecord={base_content[k]}")
        if len(only_in_base) > 20:
            print(f"    ... and {len(only_in_base) - 20} more")

    if changed:
        print(f"\n  AutoRecord changed for the same Metadata ref in both trees ({len(changed)}) "
              f"— genuine override, worth a closer look:")
        for k in changed:
            print(f"    {k}: base={base_content[k]} -> ext={ext_content[k]}")
    else:
        print("\n  No Metadata ref appears in both trees with a different AutoRecord value.")

    if new_objects:
        combined = base_keys | ext_keys
        missing = sorted(obj for obj in new_objects if obj not in combined)
        print(f"\n  Cross-check against {len(new_objects)} supplied new-object ref(s):")
        if missing:
            print(f"    NOT found in either Content.xml ({len(missing)}) — verify whether "
                  f"these should participate in this exchange plan:")
            for obj in missing:
                print(f"      {obj}")
        else:
            print("    All supplied new objects are present in at least one tree's content.")
    print()


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(
        description="Inspect and/or diff the composition (Ext/Content.xml) of a 1C exchange "
                    "plan across one or two source trees.",
        allow_abbrev=False,
    )
    parser.add_argument(
        "-Plan", required=True,
        help='One or more exchange plan names, ";;"-separated, '
             'e.g. "ОбменВРаспределеннойИнформационнойБазе;;ОбменСообщениями"',
    )
    parser.add_argument("-BasePath", help="Path to a base configuration source dump")
    parser.add_argument("-ExtPath", help="Path to an extension source dump")
    parser.add_argument(
        "-NewObjects",
        help='Optional cross-check list, ";;"-separated "Type.Name" entries '
             '(same format as Content.xml\'s <Metadata>), '
             'e.g. "Document.НовыйДокумент;;InformationRegister.НовыйРегистр"',
    )
    args = parser.parse_args()

    if not args.BasePath and not args.ExtPath:
        print("At least one of -BasePath / -ExtPath is required.", file=sys.stderr)
        sys.exit(1)

    def resolve(path):
        if not path:
            return None
        if not os.path.isabs(path):
            path = os.path.join(os.getcwd(), path)
        if not os.path.isdir(path):
            print(f"Path not found: {path}", file=sys.stderr)
            sys.exit(1)
        return path

    base_path = resolve(args.BasePath)
    ext_path = resolve(args.ExtPath)

    new_objects = []
    if args.NewObjects:
        new_objects = [e.strip() for e in args.NewObjects.split(";;") if e.strip()]

    plans = [p.strip() for p in args.Plan.split(";;") if p.strip()]
    for plan_name in plans:
        print(f"=== {plan_name} ===")
        base_content = inspect_tree(base_path, plan_name, "Base") if base_path else None
        ext_content = inspect_tree(ext_path, plan_name, "Extension") if ext_path else None
        if base_path and ext_path:
            diff_trees(base_content, ext_content, plan_name, new_objects)


if __name__ == "__main__":
    main()
