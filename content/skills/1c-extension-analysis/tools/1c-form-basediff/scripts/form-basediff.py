#!/usr/bin/env python3
# form-basediff v1.0 — what the developer changed in a form of an adopted object:
# the live form against the <BaseForm> snapshot stored in the same Form.xml.
#
# Both sides are compared as trees, not as text, item by item and property by
# property: layout elements (by name, at any depth), form attributes, commands
# and parameters (by name) and the form's own properties. Element `id` values,
# whitespace, indentation and namespace declarations are ignored; nothing else
# is filtered. A text diff of the two sides needed six hand-written rules (indent
# normalisation, wrapper lines, a "noise" class, reading order ...) and every
# run implemented them differently; a tree comparison needs none of them.
#
# Event bindings (`Events`) and command actions (`Action`) are reported apart as
# handler bindings: they wire module code to the form and do not change its
# markup, so a form whose module alone changed stays `markup-unchanged`.
#
# A property lost on one element is checked against a control element: another
# element of the same file that keeps the same property and value on both sides.
# If one exists, the loss is deliberate rather than a serialisation quirk.
#
# No -ConfigPath: the base configuration's form is a third point, and comparing
# the snapshot with it answers mostly serialisation — the snapshot omits form
# attributes, titles and data paths and names sub-elements differently (measured
# on the reference extension: 59 "differences" on a form whose snapshot matches
# the extension's version). See docs/form-basediff.md -> Not offered.
#
# Never use this tool's silence on an own form: it has no snapshot (no-snapshot),
# and "what differs from stock" does not apply to it.

import argparse
import os
import re
import sys
import xml.etree.ElementTree as ET

FORM_NS = "http://v8.1c.ru/8.3/xcf/logform"
MD_NS = "http://v8.1c.ru/8.3/MDClasses"
HANDLER_PROPS = {"Events", "Action"}
SECTIONS = {"ChildItems", "Attributes", "Commands", "Parameters", "BaseForm"}

# Folder -> type for the owners that can hold forms (same names as cfe-diff).
DIR_TYPES = {
    "Catalogs": "Catalog", "Documents": "Document", "DocumentJournals": "DocumentJournal",
    "Enums": "Enum", "Reports": "Report", "DataProcessors": "DataProcessor",
    "InformationRegisters": "InformationRegister",
    "AccumulationRegisters": "AccumulationRegister",
    "AccountingRegisters": "AccountingRegister", "CalculationRegisters": "CalculationRegister",
    "ChartsOfCharacteristicTypes": "ChartOfCharacteristicTypes",
    "ChartsOfAccounts": "ChartOfAccounts", "ChartsOfCalculationTypes": "ChartOfCalculationTypes",
    "BusinessProcesses": "BusinessProcess", "Tasks": "Task", "ExchangePlans": "ExchangePlan",
    "FilterCriteria": "FilterCriterion", "SettingsStorages": "SettingsStorage",
    "CommonForms": "CommonForm",
}


def local(tag):
    return tag.split("}", 1)[-1]


def normalized(el):
    """Nested ChildItems are left out at any depth: the named elements in them are
    compared on their own, so a button added to a command bar is reported once,
    as an own element, and not again as a change of the bar."""
    attrs = tuple(sorted((local(k), v) for k, v in el.attrib.items() if local(k) != "id"))
    return (local(el.tag), attrs, (el.text or "").strip(),
            tuple(normalized(c) for c in el if local(c.tag) != "ChildItems"))


def render(el, limit=160):
    """A compact, readable value: the text of a leaf, else a shortened XML."""
    kids = list(el)
    attrs = {local(k): v for k, v in el.attrib.items() if local(k) != "id"}
    if not kids and not attrs:
        return (el.text or "").strip() or "(empty)"
    text = ET.tostring(el, encoding="unicode")
    text = re.sub(r'\s+xmlns(:\w+)?="[^"]*"', "", text)
    text = re.sub(r"(</?)\w+:", r"\1", text)
    text = re.sub(r'\s+id="\d+"', "", text)
    text = " ".join(text.split())
    return text if len(text) <= limit else text[:limit] + " …"


def properties(el, skip=("ChildItems",)):
    """{key: element} of an item's own properties. A repeated tag gets an index."""
    out, seen = {}, {}
    for c in el:
        name = local(c.tag)
        if name in skip:
            continue
        seen[name] = seen.get(name, 0) + 1
        out[name if seen[name] == 1 else f"{name}[{seen[name]}]"] = c
    return out


def layout_items(form_el):
    """{name: (element, parent_name, index_among_named_siblings)} for every named
    element under ChildItems, at any depth."""
    out = {}

    def walk(container, parent_name):
        idx = 0
        for c in container:
            name = c.get("name")
            if not name:
                continue
            out[name] = (c, parent_name, idx)
            idx += 1
            for sub in c:
                if local(sub.tag) == "ChildItems":
                    walk(sub, name)
            # ContextMenu / AutoCommandBar / ExtendedTooltip are named children
            # with their own ChildItems; walk them too.
            for sub in c:
                if sub.get("name") and local(sub.tag) != "ChildItems":
                    for subsub in sub:
                        if local(subsub.tag) == "ChildItems":
                            walk(subsub, sub.get("name"))

    for c in form_el:
        if local(c.tag) == "ChildItems":
            walk(c, "(form)")
    return out


def named(form_el, section):
    node = next((c for c in form_el if local(c.tag) == section), None)
    if node is None:
        return {}
    return {c.get("name"): c for c in node if c.get("name")}


def diff_props(snap_el, live_el, skip=("ChildItems",)):
    """(removed, added, changed) property lists of one item:
    removed/added: [(key, element)], changed: [(key, snap_el, live_el)]."""
    sp, lp = properties(snap_el, skip), properties(live_el, skip)
    removed = [(k, sp[k]) for k in sp if k not in lp]
    added = [(k, lp[k]) for k in lp if k not in sp]
    changed = [(k, sp[k], lp[k]) for k in sp if k in lp and normalized(sp[k]) != normalized(lp[k])]
    return removed, added, changed


def control_element(prop, value_el, owner, snap_items, live_items):
    """Another element that keeps prop with the same value on both sides."""
    want = normalized(value_el)
    keepers = []
    for name, (live_el, _p, _i) in live_items.items():
        if name == owner or name not in snap_items:
            continue
        s_props = properties(snap_items[name][0])
        l_props = properties(live_el)
        if prop in s_props and prop in l_props and normalized(s_props[prop]) == want \
                and normalized(l_props[prop]) == want:
            keepers.append(name)
    return keepers


def report_props(prefix, s_el, l_el, r, owner, s_items, l_items):
    """Property differences of one item into r; descends into a named
    sub-element (context menu, command bar, extended tooltip) instead of
    printing it whole."""
    removed, added, changed = diff_props(s_el, l_el)
    for key, val in removed:
        if key in HANDLER_PROPS:
            r["handlers"].append(f"{prefix}: {key} removed: {render(val)}")
            continue
        keepers = control_element(key, val, owner, s_items, l_items)
        check = (f"control: kept by {keepers[0]}"
                 + (f" and {len(keepers) - 1} more" if len(keepers) > 1 else "")
                 + " -> deliberate edit") if keepers else \
            "control: no other element keeps it -> a serialisation quirk is not ruled out"
        r["lost"].append(f"{prefix} ({local(l_el.tag)}): -{key} = {render(val)}  [{check}]")
    for key, val in added:
        (r["handlers"] if key in HANDLER_PROPS else r["added_prop"]).append(
            f"{prefix}: +{key} = {render(val)}")
    for key, s_val, l_val in changed:
        if key in HANDLER_PROPS:
            r["handlers"].append(f"{prefix}: {key}: {render(s_val)} -> {render(l_val)}")
        elif s_val.get("name") and l_val.get("name"):
            report_props(f"{prefix}.{key}", s_val, l_val, r, owner, s_items, l_items)
        else:
            r["changed"].append(f"{prefix}: {key}: {render(s_val)} -> {render(l_val)}")


def compare(snap, live):
    """All differences between two form roots, as a dict of lists."""
    r = {"lost": [], "added_el": [], "missing_el": [], "added_prop": [], "changed": [],
         "moved": [], "reordered": [], "sections": [], "form_props": [], "handlers": []}
    s_items, l_items = layout_items(snap), layout_items(live)

    for name, (l_el, l_parent, _i) in l_items.items():
        if name not in s_items:
            r["added_el"].append(f"{name} ({local(l_el.tag)}) under {l_parent}")
            continue
        s_el, s_parent, _si = s_items[name]
        if s_parent != l_parent:
            r["moved"].append(f"{name}: {s_parent} -> {l_parent}")
        report_props(name, s_el, l_el, r, name, s_items, l_items)
    for name, (s_el, _p, _i) in s_items.items():
        if name not in l_items:
            r["missing_el"].append(f"{name} ({local(s_el.tag)})")

    # Order of the elements both sides share, per parent.
    parents = {}
    for name, (_e, parent, idx) in s_items.items():
        if name in l_items and l_items[name][1] == parent:
            parents.setdefault(parent, []).append(name)
    for parent, names in parents.items():
        snap_order = sorted(names, key=lambda n: s_items[n][2])
        live_order = sorted(names, key=lambda n: l_items[n][2])
        if snap_order != live_order:
            r["reordered"].append(f"children of {parent}: {', '.join(live_order)}")

    for section in ("Attributes", "Commands", "Parameters"):
        s_named, l_named = named(snap, section), named(live, section)
        label = section[:-1].lower()
        for n, el in l_named.items():
            if n not in s_named:
                r["sections"].append(f"own {label}: {n}")
                continue
            removed, added, changed = diff_props(s_named[n], el, skip=())
            for key, val in removed:
                (r["handlers"] if key in HANDLER_PROPS else r["sections"]).append(
                    f"{label} {n}: -{key} = {render(val)}")
            for key, val in added:
                (r["handlers"] if key in HANDLER_PROPS else r["sections"]).append(
                    f"{label} {n}: +{key} = {render(val)}")
            for key, s_val, l_val in changed:
                (r["handlers"] if key in HANDLER_PROPS else r["sections"]).append(
                    f"{label} {n}: {key}: {render(s_val)} -> {render(l_val)}")
        for n in s_named:
            if n not in l_named:
                r["sections"].append(f"{label} {n}: missing from the live form")

    removed, added, changed = diff_props(snap, live, skip=tuple(SECTIONS))
    for key, val in removed:
        (r["handlers"] if key in HANDLER_PROPS else r["form_props"]).append(
            f"form: -{key} = {render(val)}")
    for key, val in added:
        (r["handlers"] if key in HANDLER_PROPS else r["form_props"]).append(
            f"form: +{key} = {render(val)}")
    for key, s_val, l_val in changed:
        (r["handlers"] if key in HANDLER_PROPS else r["form_props"]).append(
            f"form: {key}: {render(s_val)} -> {render(l_val)}")
    return r


MARKUP_KEYS = ("lost", "missing_el", "added_el", "added_prop", "changed", "moved",
               "reordered", "sections", "form_props")


def touched(r):
    names = []
    for key in MARKUP_KEYS:
        for line in r[key]:
            if key == "sections" and line.startswith("own "):
                kind, _, name = line[4:].partition(": ")
                name = f"{name} (own {kind})"
            elif key == "sections":
                name = " ".join(line.split(":")[0].split(" ")[1:2]) or line
            else:
                name = line.split(" (")[0].split(":")[0].split(".")[0].strip()
            if name not in names:
                names.append(name)
    return names


def owner_of(ext_path, form_xml):
    """(label, belonging) of a Form.xml: 'Document.X.ФормаДокумента' / 'CommonForm.X'."""
    parts = os.path.relpath(form_xml, ext_path).split(os.sep)
    if parts[0] == "CommonForms":
        label = f"CommonForm.{parts[1]}"
        descriptor = os.path.join(ext_path, "CommonForms", f"{parts[1]}.xml")
    else:
        label = f"{DIR_TYPES.get(parts[0], parts[0])}.{parts[1]}.{parts[3]}"
        descriptor = os.path.join(ext_path, parts[0], parts[1], "Forms", f"{parts[3]}.xml")
    belonging = "?"
    try:
        root = ET.parse(descriptor).getroot()
        ob = root.find(f".//{{{MD_NS}}}Properties/{{{MD_NS}}}ObjectBelonging")
        belonging = "BORROWED" if ob is not None and ob.text == "Adopted" else "OWN"
    except (OSError, ET.ParseError):
        pass
    return label, belonging


def form_files(ext_path, obj):
    out = []
    for dirpath, dirnames, filenames in os.walk(ext_path):
        dirnames.sort()
        if "Form.xml" in filenames and os.path.basename(dirpath) == "Ext":
            out.append(os.path.join(dirpath, "Form.xml"))
    if obj:
        out = [f for f in out
               if owner_of(ext_path, f)[0] == obj or owner_of(ext_path, f)[0].startswith(obj + ".")]
    return out


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(
        description="Diff each form of an adopted object against the <BaseForm> snapshot "
                    "in its own Form.xml, as trees, property by property.",
        allow_abbrev=False,
    )
    parser.add_argument("-ExtensionPath", required=True, help="Path to extension source dump")
    parser.add_argument("-Object", default=None,
                        help='Scope: "Document.<Имя>", "Document.<Имя>.<Форма>" or '
                             '"CommonForm.<Имя>"')
    parser.add_argument("-Summary", action="store_true", help="One line per form")
    args = parser.parse_args()

    ext_path = os.path.abspath(args.ExtensionPath)
    if not os.path.isdir(ext_path):
        print(f"Extension path not found: {ext_path}", file=sys.stderr)
        sys.exit(1)

    files = form_files(ext_path, args.Object)
    if args.Object and not files:
        print(f"No Form.xml found for {args.Object}", file=sys.stderr)
        sys.exit(1)

    n_changed = n_unchanged = n_nosnap = 0
    for path in files:
        rel = os.path.relpath(path, ext_path)
        label, belonging = owner_of(ext_path, path)
        try:
            live = ET.parse(path).getroot()
        except ET.ParseError as exc:
            print(f"[PARSE ERROR] {rel}: {exc}")
            continue
        snap = next((c for c in live if local(c.tag) == "BaseForm"), None)
        if snap is None:
            n_nosnap += 1
            print(f"no-snapshot       {label} [{belonging}] — {rel}")
            continue
        r = compare(snap, live)
        markup = sum(len(r[k]) for k in MARKUP_KEYS)
        verdict = "markup-changed" if markup else "markup-unchanged"
        if markup:
            n_changed += 1
        else:
            n_unchanged += 1
        if args.Summary:
            names = touched(r)
            shown = ", ".join(names[:6]) + (f" and {len(names) - 6} more" if len(names) > 6 else "")
            print(f"{verdict:<17} {label} [{belonging}] — {markup} change(s)"
                  + (f": {shown}" if shown else "")
                  + (f"; handler bindings: {len(r['handlers'])}" if r["handlers"] else ""))
            continue

        print(f"=== {verdict}  {label} [{belonging}] — {rel} ===")
        blocks = (
            ("Lost on the live side (property in the snapshot, gone from the form) — read first",
             "lost"),
            ("Elements of the snapshot missing from the form", "missing_el"),
            ("Own elements", "added_el"),
            ("Properties added to existing elements", "added_prop"),
            ("Property values changed", "changed"),
            ("Elements moved to another parent", "moved"),
            ("Shared elements in a different order", "reordered"),
            ("Form attributes, commands, parameters", "sections"),
            ("Form properties", "form_props"),
            ("Handler bindings (module wiring, not markup)", "handlers"),
        )
        for title, key in blocks:
            if r[key]:
                print(f"  {title} ({len(r[key])}):")
                for line in r[key]:
                    print(f"    {line}")
        print()

    scope = "live form vs its own <BaseForm> snapshot"
    print(f"=== {n_changed + n_unchanged} form(s): {n_changed} markup-changed, {n_unchanged} "
          f"markup-unchanged; {n_nosnap} without a snapshot, not counted [scope: {scope}] ===")


if __name__ == "__main__":
    main()
