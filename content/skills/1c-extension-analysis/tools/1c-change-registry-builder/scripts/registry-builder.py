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
# (e.g. an already-known interceptor name) across the tree instead of enumerating everything a
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
# Coverage: every ChildObjects kind of an adopted object (templates, commands,
# enum values, dimensions, nested subsystems ...), the properties the platform
# marks as extended (<xr:PropertyState>: Type, Rights, Predefined, Content,
# Template, Form, CommandInterface) and a subsystem's added content each get rows;
# a wholly-own object always gets one row naming it; folders missing from
# CHILD_TYPE_DIR_MAP are typed by their descriptors; the configuration's own root
# Ext/ modules are scanned. A whole-extension run ends with the files no row
# interprets ([UNCLASSIFIED]), so an unsupported construct is reported, not lost.
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
    "xr": "http://v8.1c.ru/8.3/xcf/readable",
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
    "WebService": "WebServices",
    "HTTPService": "HTTPServices",
    "XDTOPackage": "XDTOPackages",
    "WSReference": "WSReferences",
    "Language": "Languages",
}

# ChildObjects entries serialized as a bare name: their Properties (and
# ObjectBelonging) live in <object dir>/<folder>/<name>.xml.
BARE_CHILD_DIRS = {
    "Form": "Forms",
    "Template": "Templates",
    "Subsystem": "Subsystems",
}

ROLES_NS = "http://v8.1c.ru/8.2/roles"
V8_NS = "http://v8.1c.ru/8.1/data/core"

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


def parse_object_element(xml_path):
    """Root metadata element (<Catalog>, <Template>, <Form> ...) of a descriptor."""
    if not os.path.isfile(xml_path):
        return None
    try:
        root = etree.parse(xml_path, etree.XMLParser(remove_blank_text=False)).getroot()
    except Exception:
        return None
    return next((c for c in root if isinstance(c.tag, str)), None)


def element_is_adopted(obj_el):
    if obj_el is None:
        return False
    ob = obj_el.find("md:Properties/md:ObjectBelonging", MD_NSMAP)
    return ob is not None and ob.text == "Adopted"


def get_child_objects(obj_el, obj_dir):
    """Every ChildObjects entry as {Kind, Name, Own, File}. A bare-name child
    (Form, Template, Subsystem) takes its ownership from its own descriptor; Own
    is None when that descriptor is missing."""
    result = []
    child_obj = obj_el.find("md:ChildObjects", MD_NSMAP) if obj_el is not None else None
    if child_obj is None:
        return result
    for c in child_obj:
        if not isinstance(c.tag, str):
            continue
        kind = etree.QName(c.tag).localname
        props = c.find("md:Properties", MD_NSMAP)
        if props is not None:
            name_el = props.find("md:Name", MD_NSMAP)
            ob = props.find("md:ObjectBelonging", MD_NSMAP)
            result.append({"Kind": kind, "Name": name_el.text if name_el is not None else "?",
                           "Own": not (ob is not None and ob.text == "Adopted"), "File": None})
            continue
        name = (c.text or "").strip()
        child_file, own = None, None
        if kind in BARE_CHILD_DIRS:
            child_file = os.path.join(obj_dir, BARE_CHILD_DIRS[kind], f"{name}.xml")
            child_el = parse_object_element(child_file)
            if child_el is not None:
                own = not element_is_adopted(child_el)
        result.append({"Kind": kind, "Name": name, "Own": own, "File": child_file})
    return result


def get_extended_properties(obj_el):
    """Properties the platform marks in <xr:PropertyState> on an adopted object —
    each one is a property whose value the extension changes or adds to."""
    out = []
    info = obj_el.find("md:InternalInfo", MD_NSMAP) if obj_el is not None else None
    if info is None:
        return out
    for ps in info.findall("xr:PropertyState", MD_NSMAP):
        prop = ps.find("xr:Property", MD_NSMAP)
        if prop is not None and prop.text:
            out.append(prop.text)
    return out


def rights_objects(rights_path):
    if not os.path.isfile(rights_path):
        return []
    try:
        root = etree.parse(rights_path).getroot()
    except Exception:
        return []
    ns = {"r": ROLES_NS}
    return [n.text for n in root.findall("r:object/r:name", ns) if n.text]


def own_predefined_items(predefined_path):
    """Predefined items without <ExtensionState> — the adopted ones carry it."""
    if not os.path.isfile(predefined_path):
        return []
    try:
        root = etree.parse(predefined_path).getroot()
    except Exception:
        return []
    own = []
    for item in root.iter():
        if not isinstance(item.tag, str) or etree.QName(item.tag).localname != "Item":
            continue
        tags = {etree.QName(c.tag).localname: c for c in item if isinstance(c.tag, str)}
        if "ExtensionState" not in tags:
            own.append(tags["Name"].text if "Name" in tags else "?")
    return own


def files_under(path):
    out = set()
    if path and os.path.isfile(path):
        out.add(os.path.normpath(path))
    elif path and os.path.isdir(path):
        for dirpath, _d, filenames in os.walk(path):
            for fn in filenames:
                out.add(os.path.normpath(os.path.join(dirpath, fn)))
    return out


def extension_rows(obj_label, obj_el, obj_dir):
    """Rows for what an adopted object (or nested subsystem) adds outside its
    modules and ChildObjects attrs/TS, and the files those rows account for."""
    rows, accounted = [], set()
    ext_dir = os.path.join(obj_dir, "Ext")
    props = obj_el.find("md:Properties", MD_NSMAP)
    for prop in get_extended_properties(obj_el):
        stem = os.path.join(ext_dir, prop)
        for suffix in (".xml", ".bin", ".bsl"):
            accounted |= files_under(stem + suffix)
        accounted |= files_under(stem)
        if prop.endswith("Module"):
            continue  # interceptors and added routines already have their rows
        if prop == "Type" and props is not None:
            types = [t.text for t in props.findall(
                "md:Type/xr:ExtendValue/v8:Type", {**MD_NSMAP, "v8": V8_NS}) if t.text]
            mech = f"extended Type: +{len(types)} type(s): {', '.join(types)}"
        elif prop == "Rights":
            names = rights_objects(os.path.join(ext_dir, "Rights.xml"))
            mech = (f"extended Rights: {len(names)} object(s) granted in Ext/Rights.xml: "
                    + ", ".join(names))
        elif prop == "Predefined":
            own = own_predefined_items(os.path.join(ext_dir, "Predefined.xml"))
            if not own:
                continue  # only adopted items: nothing of the extension's own
            mech = f"own predefined item(s): {', '.join(own)}"
        elif prop == "Content":
            mech = ("extended Content (exchange plan composition in Ext/Content.xml) — "
                    "run 1c-exchangeplan-content")
        elif prop == "CommandInterface":
            ci = os.path.join(ext_dir, "CommandInterface.xml")
            mech = ("extended CommandInterface" + (
                " — visibility / placement / order settings in Ext/CommandInterface.xml"
                if os.path.isfile(ci) else ""))
        elif prop == "Template":
            mech = "template content replaced (Ext/Template.xml differs from the base)"
        elif prop == "Form":
            mech = ("form marked extended (its module, its layout or both) — own and "
                    "changed layout elements: cfe-diff -Mode A, which diffs Ext/Form.xml "
                    "against its <BaseForm>")
        else:
            mech = f"extended property: {prop}"
        rows.append({"Object": obj_label, "Mechanism": mech, "Block": ""})
    if props is not None and etree.QName(obj_el.tag).localname == "Subsystem":
        items = [i.text for i in props.findall("md:Content/xr:Item", MD_NSMAP) if i.text]
        if items:
            rows.append({"Object": obj_label,
                         "Mechanism": f"subsystem content: +{len(items)} item(s): {', '.join(items)}",
                         "Block": ""})
    return rows, accounted


def child_rows(obj_label, obj_el, obj_dir):
    """Rows for ChildObjects kinds other than attributes / tabular sections (those
    keep their own rows from get_own_children), and the files they account for."""
    rows, accounted = [], set()
    for ch in get_child_objects(obj_el, obj_dir):
        kind, name = ch["Kind"], ch["Name"]
        if kind in ("Attribute", "TabularSection"):
            continue
        if ch["Own"] is None:
            rows.append({"Object": obj_label,
                         "Mechanism": f"{kind} {name}: ownership unknown (no descriptor file)",
                         "Block": ""})
            continue
        if kind == "Subsystem":
            sub_el = parse_object_element(ch["File"])
            sub_dir = ch["File"][:-4]
            label = f"{obj_label}.Subsystem.{name}"
            accounted.add(os.path.normpath(ch["File"]))
            if ch["Own"]:
                rows.append({"Object": label, "Mechanism": "own nested subsystem", "Block": ""})
                accounted |= files_under(sub_dir)
            else:
                r, a = extension_rows(label, sub_el, sub_dir)
                rows += r
                accounted |= a
                r, a = child_rows(label, sub_el, sub_dir)
                rows += r
                accounted |= a
            continue
        if kind == "Form":
            accounted |= files_under(ch["File"])
            form_xml = os.path.join(obj_dir, "Forms", name, "Ext", "Form.xml")
            accounted.add(os.path.normpath(form_xml))
            if ch["Own"]:
                rows.append({"Object": obj_label, "Mechanism": f"own form: {name}", "Block": ""})
                accounted |= files_under(os.path.join(obj_dir, "Forms", name))
            elif "Form" in get_extended_properties(parse_object_element(ch["File"])):
                rows.append({"Object": obj_label, "Mechanism": (
                    f"borrowed form {name} marked extended (its module, its layout or both) — "
                    f"own and changed layout elements: cfe-diff -Mode A, which diffs its "
                    f"Form.xml against <BaseForm>"), "Block": ""})
            continue
        if not ch["Own"]:
            if kind == "Template":
                accounted |= files_under(ch["File"])
                if "Template" in get_extended_properties(parse_object_element(ch["File"])):
                    accounted |= files_under(ch["File"][:-4])
                    rows.append({"Object": obj_label, "Mechanism": (
                        f"borrowed template {name}: content replaced "
                        f"(Templates/{name}/Ext/Template.xml differs from the base)"), "Block": ""})
            continue
        if kind == "Template":
            accounted |= files_under(ch["File"]) | files_under(ch["File"][:-4])
        elif kind == "Command":
            accounted |= files_under(os.path.join(obj_dir, "Commands", name))
        rows.append({"Object": obj_label, "Mechanism": f"own {kind}: {name}", "Block": ""})
    return rows, accounted


def find_own_bsl_files(ext_path, type_dir, name):
    """ObjectModule/ManagerModule/RecordSetModule/ValueManagerModule/CommandModule
    plus every Form's Module.bsl, relative to the object's own directory.

    The object's own `Ext/` is walked recursively, not listed: a common form keeps
    its module at `Ext/Form/Module.bsl`, one level deeper than an object module,
    and a flat listing missed that file — and with it every interceptor the
    extension put on a typical common form (2 of the 101 annotations on a real
    extension were invisible for exactly this reason)."""
    obj_dir = os.path.join(ext_path, type_dir, name)
    if not os.path.isdir(obj_dir):
        return []
    files = []
    ext_dir = os.path.join(obj_dir, "Ext")
    if os.path.isdir(ext_dir):
        for dirpath, _dirnames, filenames in os.walk(ext_dir):
            for fn in filenames:
                if fn.lower().endswith(".bsl"):
                    files.append(os.path.join(dirpath, fn))
    forms_dir = os.path.join(obj_dir, "Forms")
    if os.path.isdir(forms_dir):
        for dirpath, _dirnames, filenames in os.walk(forms_dir):
            for fn in filenames:
                if fn == "Module.bsl":
                    files.append(os.path.join(dirpath, fn))
    # An object's own commands keep their modules at
    # `<Object>/Commands/<Name>/Ext/CommandModule.bsl` — outside both `Ext/` and
    # `Forms/`, so neither walk above reaches them and the whole command module
    # was invisible (3 such files on a real extension, one of them holding a
    # command that opens a form of an object that does not exist).
    commands_dir = os.path.join(obj_dir, "Commands")
    if os.path.isdir(commands_dir):
        for dirpath, _dirnames, filenames in os.walk(commands_dir):
            for fn in filenames:
                if fn.lower().endswith(".bsl"):
                    files.append(os.path.join(dirpath, fn))
    return files


def find_insertion_ranges(lines, start, end):
    """Returns [(ins_start, ins_end), ...] inclusive 0-based line-index ranges for
    every #Вставка...#КонецВставки block within [start, end]. Unclosed blocks run
    to `end`."""
    ranges = []
    in_block = False
    block_start = None
    for k in range(start, end + 1):
        stripped = lines[k].strip()
        if stripped == "#Вставка":
            in_block = True
            block_start = k
        elif stripped == "#КонецВставки" and in_block:
            ranges.append((block_start, k))
            in_block = False
    if in_block:
        ranges.append((block_start, end))
    return ranges


def scan_bsl_for_interceptors(bsl_path):
    """Returns a list of dicts: {Type, Method, Line, DispatchBranches, Scoped}.
    DispatchBranches > 1 means the routine's own body should be decomposed by
    branch instead of emitted as one registry row (SKILL.md step 1 rule).

    For `&ИзменениеИКонтроль` specifically, the routine body is a verbatim copy of
    the current typical implementation with only the `#Вставка`/`#КонецВставки`
    portions being the extension's own — comparisons living in the untouched
    copied text are not the extension's own dispatch logic and must not inflate
    the branch count (confirmed gap: a real `&ИзменениеИКонтроль` dispatcher had
    ~85 total `ОбъектМетаданных = Метаданные.X` comparisons in its full copied
    body, but only a handful were inside its own `#Вставка` blocks — the rest was
    typical code copied in whole by the annotation's own mechanics, not new
    dispatch branches added by the extension). For every other annotation type
    the whole body is the extension's own by construction, so the full-body count
    from earlier versions of this tool remains correct there."""
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

        scoped = itype == "ИзменениеИКонтроль"
        if scoped:
            ranges = find_insertion_ranges(lines, body_start, body_end)
            branch_count = 0
            for (ins_start, ins_end) in ranges:
                for k in range(ins_start, ins_end + 1):
                    branch_count += len(RE_DISPATCH_BRANCH.findall(lines[k]))
        else:
            branch_count = 0
            for k in range(body_start, body_end + 1):
                branch_count += len(RE_DISPATCH_BRANCH.findall(lines[k]))

        results.append({
            "Type": itype,
            "Method": method,
            "Line": i + 1,
            "RoutineLine": body_start + 1,
            "DispatchBranches": branch_count,
            "Scoped": scoped,
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


def scan_bsl_routines_with_lines(bsl_path):
    """Every Процедура/Функция with its 1-based line and whether it is Экспорт.
    Used to find the routines an extension ADDED to a module: in a CFE the
    extension's copy of an adopted object's module holds only what the extension
    declares — the annotated interceptor routines (whose bodies are verbatim
    copies of the typical implementation) plus its own new routines. So an
    unannotated routine in such a module is an addition by construction, and no
    base-configuration copy is needed to tell.

    Verified against `1c-graph-metadata-mcp`'s independent layer diff on a real
    extension: for `Документ.Отпуск`'s manager module this rule yields exactly the
    five routines the graph reports as "Добавлены", and the annotated ones exactly
    match its "Переопределены"."""
    lines = read_lines(bsl_path)
    out = []
    for idx, line in enumerate(lines):
        m = RE_ROUTINE_START.match(strip_comment(line).strip())
        if m:
            tail = strip_comment(line)
            out.append({
                "Name": m.group(2),
                "Line": idx + 1,
                "Export": bool(re.search(r"\bЭкспорт\b", tail, re.IGNORECASE)),
            })
    return out


def iter_objects(ext_path):
    """Every top-level object descriptor. Folders missing from CHILD_TYPE_DIR_MAP
    are not skipped: the type is read from the descriptor's root element, so a
    new or rare metadata type still produces rows instead of vanishing."""
    known_dirs = set(CHILD_TYPE_DIR_MAP.values())
    for type_name, dir_name in CHILD_TYPE_DIR_MAP.items():
        type_dir = os.path.join(ext_path, dir_name)
        if not os.path.isdir(type_dir):
            continue
        for fn in sorted(os.listdir(type_dir)):
            if fn.lower().endswith(".xml"):
                yield type_name, dir_name, fn[:-4]
    for dir_name in sorted(os.listdir(ext_path)):
        type_dir = os.path.join(ext_path, dir_name)
        if dir_name in known_dirs or dir_name == "Ext" or not os.path.isdir(type_dir):
            continue
        for fn in sorted(os.listdir(type_dir)):
            if not fn.lower().endswith(".xml"):
                continue
            el = parse_object_element(os.path.join(type_dir, fn))
            if el is not None:
                yield etree.QName(el.tag).localname, dir_name, fn[:-4]


def module_rows(ext_path, bsl, obj_label, borrowed):
    """Rows for one module: its interceptors and the routines the extension added."""
    rows = []
    is_form_module = (os.sep + "Forms" + os.sep in bsl
                      or bsl.endswith(os.sep + "Ext" + os.sep + "Form" + os.sep + "Module.bsl"))
    interceptors = scan_bsl_for_interceptors(bsl)
    rel = os.path.relpath(bsl, ext_path)

    # Routines the extension added to this module — everything that is not
    # an annotated interceptor. Emitted regardless of whether the module
    # also carries interceptors: a module with an interceptor used to
    # suppress these rows entirely, which silently dropped whole layers of
    # own code (39 own routines on one real extension, among them 17
    # copies of the same registry-id helper; and, in a form module, a
    # 420-line own procedure sitting beside one annotated interceptor).
    annotated_lines = {ic["RoutineLine"] for ic in interceptors}
    added = [r for r in scan_bsl_routines_with_lines(bsl)
             if r["Line"] not in annotated_lines]
    if is_form_module:
        # A form module stays one row: its routines are mostly event
        # handlers, and the element they are bound to is read from the
        # matching Form.xml (SKILL.md → «Forms»), not from this list.
        if added:
            rows.append({
                "Object": obj_label,
                "Mechanism": (
                    f"form module {rel} — {len(added)} own routine(s) "
                    f'{"beside " + str(len(interceptors)) + " interceptor(s) in the same file" if interceptors else "and no interceptor annotation"}'
                    f" (read the element bindings in the matching Form.xml "
                    f"with 1c-form-info): "
                    + ", ".join(r["Name"] for r in added)
                ),
                "Block": "",
            })
    else:
        if added and borrowed:
            # One row per routine: each is a separate addition to a typical
            # module, and the analyst assigns each its own Блок.
            for r in added:
                rows.append({
                    "Object": obj_label,
                    "Mechanism": (
                        f'own routine added to a typical module: '
                        f'{r["Name"]}{" Экспорт" if r["Export"] else ""} '
                        f'at {rel}:{r["Line"]}'
                    ),
                    "Block": "",
                })
        elif added:
            # Wholly-own object: the object itself is the change, so its
            # routines are listed once per module instead of one row each.
            rows.append({
                "Object": obj_label,
                "Mechanism": (
                    f"own module {rel} of a wholly-own object — "
                    f'{len(added)} routine(s): '
                    + ", ".join(r["Name"] for r in added)
                ),
                "Block": "",
            })

    if interceptors:
        for ic in interceptors:
            if ic["DispatchBranches"] > 1:
                scope_note = (
                    " (counted inside #Вставка/#КонецВставки only — the "
                    "surrounding copied-typical body is excluded)"
                    if ic["Scoped"] else ""
                )
                rows.append({
                    "Object": obj_label,
                    "Mechanism": (
                        f'DISPATCHER &{ic["Type"]}("{ic["Method"]}") at {rel}:{ic["Line"]} — '
                        f'{ic["DispatchBranches"]} metadata-comparison branches{scope_note}, '
                        f'decompose by unique shape before assigning Блок'
                    ),
                    "Block": "",
                })
            else:
                rows.append({
                    "Object": obj_label,
                    "Mechanism": f'&{ic["Type"]}("{ic["Method"]}") at {rel}:{ic["Line"]}',
                    "Block": "",
                })
    return rows


def build_registry(ext_path, only_object=None, accounted=None):
    """Rows for every own change. When `accounted` is a set, every file some row
    interprets is added to it, so the caller can list what nothing covered."""
    rows = []
    if accounted is None:
        accounted = set()
    accounted.add(os.path.normpath(os.path.join(ext_path, "Configuration.xml")))

    # The configuration's own modules (session, application ...) at the root Ext/.
    root_ext = os.path.join(ext_path, "Ext")
    if os.path.isdir(root_ext) and not only_object:
        for dirpath, dirnames, filenames in os.walk(root_ext):
            dirnames.sort()
            for fn in sorted(filenames):
                if fn.lower().endswith(".bsl"):
                    bsl = os.path.join(dirpath, fn)
                    accounted.add(os.path.normpath(bsl))
                    rows += module_rows(ext_path, bsl, "Configuration", True)

    for type_name, type_dir, name in iter_objects(ext_path):
        if only_object and f"{type_name}.{name}" != only_object:
            continue
        obj_xml = find_object_xml(ext_path, type_dir, name)
        borrowed = is_borrowed(obj_xml)
        if borrowed is None:
            continue
        obj_label = f"{type_name}.{name}"
        obj_dir = os.path.join(ext_path, type_dir, name)
        obj_el = parse_object_element(obj_xml)
        accounted.add(os.path.normpath(obj_xml))

        if not borrowed:
            # A wholly-own object is itself the change: one row names it, so an
            # object with no attributes and no module (an event subscription, a
            # scheduled job, an enum) still reaches the registry.
            counts = {}
            for ch in get_child_objects(obj_el, obj_dir):
                counts[ch["Kind"]] = counts.get(ch["Kind"], 0) + 1
            summary = ", ".join(f"{v} {k}" for k, v in counts.items())
            rows.append({"Object": obj_label,
                         "Mechanism": "own object" + (f" — {summary}" if summary else ""),
                         "Block": ""})
            accounted |= files_under(obj_dir)

        own_attrs, own_ts = get_own_children(obj_xml)
        for a in own_attrs:
            rows.append({"Object": obj_label, "Mechanism": f"own attribute: {a}", "Block": ""})
        for t in own_ts:
            rows.append({"Object": obj_label, "Mechanism": f"own tabular section: {t}", "Block": ""})

        if borrowed:
            r, acc = extension_rows(obj_label, obj_el, obj_dir)
            rows += r
            accounted |= acc
            r, acc = child_rows(obj_label, obj_el, obj_dir)
            rows += r
            accounted |= acc
            if type_name == "CommonForm":
                accounted.add(os.path.normpath(os.path.join(obj_dir, "Ext", "Form.xml")))

        for bsl in find_own_bsl_files(ext_path, type_dir, name):
            accounted.add(os.path.normpath(bsl))
            rows += module_rows(ext_path, bsl, obj_label, borrowed)
    return rows


def unclassified_files(ext_path, accounted):
    """Files of the extension that no row interprets."""
    return sorted(p for p in files_under(ext_path) if p not in accounted)


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(
        description="Build the change registry required by SKILL.md step 1 directly "
                    "from the extension source (own attrs/TS/interceptors/forms), "
                    "instead of from a search for an already-known pattern name.",
        allow_abbrev=False,
    )
    parser.add_argument("-ExtensionPath", required=True, help="Path to extension source dump")
    parser.add_argument("-Object", default=None, help='Scope to one object, e.g. "Document.<Имя>"')
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

    accounted = set()
    rows = build_registry(ext_path, only_object=args.Object, accounted=accounted)

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

    # Completeness check (whole-extension runs only): a file no row interprets is
    # either an unsupported construct or a gap in this tool — never silent.
    if not args.Object:
        unclassified = unclassified_files(ext_path, accounted)
        print(f"=== {len(unclassified)} unclassified file(s) — interpreted by no row above ===")
        for path in unclassified:
            print(f"  [UNCLASSIFIED] {os.path.relpath(path, ext_path)}")


if __name__ == "__main__":
    main()
