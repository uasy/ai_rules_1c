#!/usr/bin/env python3
# cfe-diff v1.0 — Analyze and compare 1C configuration extension (CFE)
# Licence and attribution: NOTICE.md of the 1c-metadata-manage skill.
#
# Local: Mode A reports everything an adopted object carries, not only its own
# attributes / tabular sections / forms; cfe-diff.ps1 is unchanged upstream code.
#   - every ChildObjects kind is counted (templates, commands, enum values,
#     dimensions, resources, operations, channels ...); a child serialized as a
#     bare name (Form, Template, Subsystem) takes its ownership from its own file;
#   - properties the platform marks as extended (<xr:PropertyState>) are listed,
#     with detail for Type (added types), Content (added items), Rights (objects
#     granted), Predefined (own items) and CommandInterface;
#   - object types missing from CHILD_TYPE_DIR_MAP are resolved by scanning the
#     top-level folders instead of being dropped; Language is not skipped;
#   - modules are found under Ext/ recursively (a common form keeps its module at
#     Ext/Form/Module.bsl), under Commands/, and in the root Ext/ of the extension;
#     a common form's own Ext/Form.xml is read for callType handlers;
#   - a final section lists every file of the extension that no row above
#     interpreted, so an unsupported construct is reported instead of silent.

import argparse
import os
import re
import sys
from lxml import etree

# --- Namespace maps ---

MD_NSMAP = {
    "md": "http://v8.1c.ru/8.3/MDClasses",
    "xr": "http://v8.1c.ru/8.3/xcf/readable",
}

FORM_NSMAP = {
    "f": "http://v8.1c.ru/8.3/xcf/logform",
}

# Local: TypeDescription namespace, for the types a defined type gains.
V8_NS = "http://v8.1c.ru/8.1/data/core"

# --- Type -> directory mapping ---

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
    # Local: types the upstream map lacks; anything still missing is resolved by
    # resolve_type_dir() rather than reported as an unknown type.
    "WebService": "WebServices",
    "HTTPService": "HTTPServices",
    "XDTOPackage": "XDTOPackages",
    "WSReference": "WSReferences",
    "Language": "Languages",
}

# Local: ChildObjects entries serialized as a bare name — their Properties (and
# ObjectBelonging) live in <object dir>/<folder>/<name>.xml.
BARE_CHILD_DIRS = {
    "Form": "Forms",
    "Template": "Templates",
    "Subsystem": "Subsystems",
}

# Local: plural labels for the ChildObjects summary line; other kinds print as-is.
CHILD_KIND_LABELS = {
    "Attribute": "attrs",
    "TabularSection": "TS",
    "Form": "forms",
    "Template": "templates",
    "Command": "commands",
    "EnumValue": "enum values",
    "Dimension": "dimensions",
    "Resource": "resources",
    "Operation": "operations",
    "IntegrationServiceChannel": "channels",
    "Column": "columns",
    "Subsystem": "subsystems",
}


def resolve_type_dir(obj_type, obj_name, extension_path):
    """Local: folder of a top-level object. The map first; otherwise the first
    top-level folder holding <name>.xml whose root element is <obj_type>."""
    if obj_type in CHILD_TYPE_DIR_MAP:
        return CHILD_TYPE_DIR_MAP[obj_type]
    for entry in sorted(os.listdir(extension_path)):
        candidate = os.path.join(extension_path, entry, f"{obj_name}.xml")
        if not os.path.isfile(candidate):
            continue
        try:
            root = etree.parse(candidate).getroot()
        except Exception:
            continue
        first = next((c for c in root if isinstance(c.tag, str)), None)
        if first is not None and etree.QName(first.tag).localname == obj_type:
            CHILD_TYPE_DIR_MAP[obj_type] = entry
            return entry
    return None


# --- Helper: check if object is borrowed ---

def get_object_info(obj_type, obj_name, extension_path):
    dir_name = resolve_type_dir(obj_type, obj_name, extension_path)
    if dir_name is None:
        return None
    obj_file = os.path.join(extension_path, dir_name, f"{obj_name}.xml")

    if not os.path.isfile(obj_file):
        return {"Borrowed": False, "File": obj_file, "Exists": False}

    parser_xml = etree.XMLParser(remove_blank_text=False)
    doc = etree.parse(obj_file, parser_xml)
    doc_root = doc.getroot()

    # Find first element child
    obj_el = None
    for c in doc_root:
        if isinstance(c.tag, str):
            obj_el = c
            break

    if obj_el is None:
        return {"Borrowed": False, "File": obj_file, "Exists": True}

    props_el = obj_el.find("md:Properties", MD_NSMAP)
    ob_node = None
    if props_el is not None:
        ob_node = props_el.find("md:ObjectBelonging", MD_NSMAP)

    borrowed = ob_node is not None and ob_node.text == "Adopted"

    return {
        "Borrowed": borrowed,
        "File": obj_file,
        "Exists": True,
        "Type": obj_type,
        "Name": obj_name,
        "DirName": dir_name,
        "ObjElement": obj_el,
    }


# --- Helper: find .bsl files for object ---

def get_bsl_files(obj_type, obj_name, extension_path):
    dir_name = resolve_type_dir(obj_type, obj_name, extension_path)
    if dir_name is None:
        return []
    obj_dir = os.path.join(extension_path, dir_name, obj_name)

    if not os.path.isdir(obj_dir):
        return []

    # Local: Ext/ is walked recursively (a common form's module is
    # Ext/Form/Module.bsl) and Commands/<Name>/Ext/CommandModule.bsl is included.
    bsl_files = []
    for sub, only_module in (("Ext", False), ("Forms", True), ("Commands", False)):
        root = os.path.join(obj_dir, sub)
        if not os.path.isdir(root):
            continue
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames.sort()
            for fn in sorted(filenames):
                if (fn == "Module.bsl") if only_module else fn.lower().endswith(".bsl"):
                    bsl_files.append(os.path.join(dirpath, fn))

    return bsl_files


# --- Local: helpers for everything an object carries besides attrs/TS/forms ---

def first_element(root):
    return next((c for c in root if isinstance(c.tag, str)), None)


def parse_object_element(xml_path):
    """Root metadata element (<Catalog>, <Template>, <Form> ...) of a descriptor."""
    if not os.path.isfile(xml_path):
        return None
    try:
        return first_element(etree.parse(xml_path).getroot())
    except Exception:
        return None


def is_adopted(obj_el):
    if obj_el is None:
        return False
    ob = obj_el.find("md:Properties/md:ObjectBelonging", MD_NSMAP)
    return ob is not None and ob.text == "Adopted"


def get_child_objects(obj_el, obj_dir):
    """Every ChildObjects entry as {Kind, Name, Own, File}. Own is None when a
    bare-name child has no descriptor file to read ownership from."""
    result = []
    child_obj = obj_el.find("md:ChildObjects", MD_NSMAP)
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
            result.append({
                "Kind": kind,
                "Name": name_el.text if name_el is not None else "?",
                "Own": not (ob is not None and ob.text == "Adopted"),
                "File": None,
            })
            continue
        name = (c.text or "").strip()
        child_file = None
        own = None
        if kind in BARE_CHILD_DIRS:
            child_file = os.path.join(obj_dir, BARE_CHILD_DIRS[kind], f"{name}.xml")
            child_el = parse_object_element(child_file)
            if child_el is not None:
                own = not is_adopted(child_el)
        result.append({"Kind": kind, "Name": name, "Own": own, "File": child_file})
    return result


def get_extended_properties(obj_el):
    """Properties the platform marks in <xr:PropertyState> on an adopted object:
    each is a property whose value the extension changes or adds to."""
    names = []
    info = obj_el.find("md:InternalInfo", MD_NSMAP)
    if info is None:
        return names
    for ps in info.findall("xr:PropertyState", MD_NSMAP):
        prop = ps.find("xr:Property", MD_NSMAP)
        state = ps.find("xr:State", MD_NSMAP)
        if prop is not None and prop.text:
            names.append((prop.text, state.text if state is not None else ""))
    return names


def describe_extensions(obj_el, obj_dir):
    """Human-readable lines for what an adopted object adds outside ChildObjects,
    plus the Ext/ files those lines account for."""
    lines = []
    accounted = set()
    ext_dir = os.path.join(obj_dir, "Ext")
    props = obj_el.find("md:Properties", MD_NSMAP)
    ext_props = get_extended_properties(obj_el)

    for prop, state in ext_props:
        detail = ""
        stem = os.path.join(ext_dir, prop)
        for path in (stem + ".xml", stem + ".bin", stem + ".bsl"):
            if os.path.isfile(path):
                accounted.add(os.path.normpath(path))
        if os.path.isdir(stem):
            for dirpath, _d, filenames in os.walk(stem):
                for fn in filenames:
                    accounted.add(os.path.normpath(os.path.join(dirpath, fn)))

        if prop == "Type" and props is not None:
            types = [t.text for t in props.findall(
                "md:Type/xr:ExtendValue/v8:Type", {**MD_NSMAP, "v8": V8_NS}) if t.text]
            if types:
                detail = f" +{len(types)} type(s): {', '.join(types)}"
        elif prop == "Rights":
            names = rights_objects(os.path.join(ext_dir, "Rights.xml"))
            detail = f" {len(names)} object(s) granted"
        elif prop == "Predefined":
            own = own_predefined_items(os.path.join(ext_dir, "Predefined.xml"))
            if own:
                detail = f" own item(s): {', '.join(own)}"
            else:
                detail = " no own items (adopted items only)"
        elif prop == "CommandInterface":
            n = count_command_interface(os.path.join(ext_dir, "CommandInterface.xml"))
            if n:
                detail = f" {n} command setting(s)"
        elif prop == "Content":
            detail = " see 1c-exchangeplan-content" if os.path.isfile(
                os.path.join(ext_dir, "Content.xml")) else ""
        elif prop.endswith("Module"):
            continue  # its interceptors are already listed per file
        lines.append(f"Extended: {prop} [{state}]{detail}")

    # Content of an adopted subsystem lists only what the extension adds, and the
    # platform does not mark it in PropertyState.
    if props is not None and etree.QName(obj_el.tag).localname == "Subsystem":
        items = [i.text for i in props.findall("md:Content/xr:Item", MD_NSMAP) if i.text]
        if items:
            lines.append(f"Content: +{len(items)} item(s): {', '.join(items)}")

    return lines, accounted



def rights_objects(rights_path):
    if not os.path.isfile(rights_path):
        return []
    try:
        root = etree.parse(rights_path).getroot()
    except Exception:
        return []
    ns = {"r": "http://v8.1c.ru/8.2/roles"}
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


def count_command_interface(ci_path):
    if not os.path.isfile(ci_path):
        return 0
    try:
        root = etree.parse(ci_path).getroot()
    except Exception:
        return 0
    return sum(1 for el in root.iter()
               if isinstance(el.tag, str) and etree.QName(el.tag).localname == "Command")


def files_under(path):
    out = set()
    if os.path.isfile(path):
        out.add(os.path.normpath(path))
    elif os.path.isdir(path):
        for dirpath, _d, filenames in os.walk(path):
            for fn in filenames:
                out.add(os.path.normpath(os.path.join(dirpath, fn)))
    return out


# --- Helper: parse interceptors from .bsl ---

def get_interceptors(bsl_path):
    if not os.path.isfile(bsl_path):
        return []

    with open(bsl_path, "r", encoding="utf-8-sig") as fh:
        lines = fh.readlines()

    interceptors = []
    pattern = re.compile(r'^&(\u041f\u0435\u0440\u0435\u0434|\u041f\u043e\u0441\u043b\u0435|\u0418\u0437\u043c\u0435\u043d\u0435\u043d\u0438\u0435\u0418\u041a\u043e\u043d\u0442\u0440\u043e\u043b\u044c|\u0412\u043c\u0435\u0441\u0442\u043e)\("([^"]+)"\)')
    # The above is: ^&(Перед|После|ИзменениеИКонтроль|Вместо)\("([^"]+)"\)

    for i, line in enumerate(lines):
        stripped = line.strip()
        m = pattern.match(stripped)
        if m:
            interceptors.append({
                "Type": m.group(1),
                "Method": m.group(2),
                "Line": i + 1,
                "File": bsl_path,
            })

    return interceptors


# --- Helper: extract #Вставка blocks from .bsl ---

def get_insertion_blocks(bsl_path):
    if not os.path.isfile(bsl_path):
        return []

    with open(bsl_path, "r", encoding="utf-8-sig") as fh:
        lines = fh.readlines()

    blocks = []
    in_block = False
    block_lines = []
    start_line = 0

    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped == "\u0023\u0412\u0441\u0442\u0430\u0432\u043a\u0430":
            # #Вставка
            in_block = True
            block_lines = []
            start_line = i + 1
        elif stripped == "\u0023\u041a\u043e\u043d\u0435\u0446\u0412\u0441\u0442\u0430\u0432\u043a\u0438" and in_block:
            # #КонецВставки
            in_block = False
            blocks.append({
                "StartLine": start_line,
                "EndLine": i + 1,
                "Code": "\n".join(block_lines).strip(),
                "File": bsl_path,
            })
        elif in_block:
            block_lines.append(line.rstrip("\n").rstrip("\r"))

    return blocks


# --- Helper: analyze form for callType events and commands ---

def get_form_interceptors(form_xml_path):
    if not os.path.isfile(form_xml_path):
        return None

    parser_xml = etree.XMLParser(remove_blank_text=False)
    try:
        doc = etree.parse(form_xml_path, parser_xml)
    except Exception:
        return None

    f_root = doc.getroot()
    base_form = f_root.find("f:BaseForm", FORM_NSMAP)
    is_borrowed = base_form is not None

    interceptors = []

    # Form-level events with callType
    events_node = f_root.find("f:Events", FORM_NSMAP)
    if events_node is not None:
        for evt in events_node.findall("f:Event", FORM_NSMAP):
            ct = evt.get("callType", "")
            if ct:
                evt_name = evt.get("name", "")
                evt_text = evt.text or ""
                interceptors.append(f"Event:{evt_name} [{ct}] -> {evt_text}")

    # Element-level events with callType (scan all elements recursively)
    child_items = f_root.find("f:ChildItems", FORM_NSMAP)
    if child_items is not None:
        # Walk all descendant elements looking for Events/Event[@callType]
        f_ns = FORM_NSMAP["f"]
        for el in child_items.iter():
            if not isinstance(el.tag, str):
                continue
            el_name = el.get("name", "")
            if not el_name:
                continue
            events_sub = el.find(f"{{{f_ns}}}Events")
            if events_sub is None:
                continue
            for evt in events_sub.findall(f"{{{f_ns}}}Event"):
                ct = evt.get("callType", "")
                if ct:
                    evt_name = evt.get("name", "")
                    evt_text = evt.text or ""
                    interceptors.append(f"Element:{el_name}.{evt_name} [{ct}] -> {evt_text}")

    # Commands with callType on Action
    f_ns = FORM_NSMAP["f"]
    cmds_node = f_root.find(f"{{{f_ns}}}Commands")
    if cmds_node is not None:
        for cmd in cmds_node.findall(f"{{{f_ns}}}Command"):
            cmd_name = cmd.get("name", "")
            for action in cmd.findall(f"{{{f_ns}}}Action"):
                ct = action.get("callType", "")
                if ct:
                    action_text = action.text or ""
                    interceptors.append(f"Command:{cmd_name} [{ct}] -> {action_text}")

    # Local: what the extension did to a borrowed form's layout — the difference
    # between the form and the <BaseForm> snapshot stored beside it. Own
    # attributes / commands / elements by name; for an element present in both,
    # a change of its own properties (a removed or edited property is invisible
    # to a name comparison).
    if base_form is not None:
        for section, label in (("Attributes", "Attribute"), ("Commands", "Command")):
            base_names = set(child_names(base_form, section))
            for n in child_names(f_root, section):
                if n not in base_names:
                    interceptors.append(f"Own {label}: {n}")
        cur_items = form_items(f_root)
        base_items = form_items(base_form)
        for n, el in cur_items.items():
            if n not in base_items:
                interceptors.append(f"Own element: {n} ({etree.QName(el.tag).localname})")
            elif item_properties(el) != item_properties(base_items[n]):
                interceptors.append(f"Changed element: {n}")

    return {
        "IsBorrowed": is_borrowed,
        "Interceptors": interceptors,
    }


def child_names(form_el, section):
    node = form_el.find(f"f:{section}", FORM_NSMAP)
    if node is None:
        return []
    return [c.get("name") for c in node if isinstance(c.tag, str) and c.get("name")]


def form_items(form_el):
    """Named layout elements under ChildItems (any depth), by name."""
    out = {}
    child_items = form_el.find("f:ChildItems", FORM_NSMAP)
    if child_items is None:
        return out
    for el in child_items.iter():
        if isinstance(el.tag, str) and el.get("name") and \
                etree.QName(el.getparent().tag).localname == "ChildItems":
            out[el.get("name")] = el
    return out


def item_properties(el):
    """An element's own properties, without nested elements, as a normalized tree:
    indentation and namespace declarations differ between the form and its deeper
    <BaseForm> copy, so serialized text would flag every element as changed."""
    return [normalized(c) for c in el
            if isinstance(c.tag, str) and etree.QName(c.tag).localname != "ChildItems"]


def normalized(el):
    """Nested ChildItems are left out at any depth (a command bar inside an
    element holds named elements that are compared on their own)."""
    attrs = tuple(sorted((k, v) for k, v in el.attrib.items() if k != "id"))
    return (el.tag, attrs, (el.text or "").strip(),
            tuple(normalized(c) for c in el
                  if isinstance(c.tag, str) and etree.QName(c.tag).localname != "ChildItems"))


# --- Mode A: Extension overview ---

def mode_a(objects, extension_path):
    borrowed_list = []
    own_list = []
    # Local: every file some row below interprets; the rest is listed at the end.
    accounted = {os.path.normpath(os.path.join(extension_path, "Configuration.xml"))}

    # Local: interceptors of the configuration's own modules (Ext/*.bsl at the root).
    root_ext = os.path.join(extension_path, "Ext")
    if os.path.isdir(root_ext):
        root_bsl = []
        for dirpath, dirnames, filenames in os.walk(root_ext):
            dirnames.sort()
            root_bsl.extend(os.path.join(dirpath, fn) for fn in sorted(filenames)
                            if fn.lower().endswith(".bsl"))
        if root_bsl:
            print("  [CONFIGURATION] root modules")
            for bsl in root_bsl:
                accounted.add(os.path.normpath(bsl))
                print_interceptors(bsl, extension_path)

    for obj in objects:
        info = get_object_info(obj["Type"], obj["Name"], extension_path)
        if info is None:
            print(f"  [?] {obj['Type']}.{obj['Name']} \u2014 unknown type")
            continue
        if not info["Exists"]:
            print(f"  [?] {obj['Type']}.{obj['Name']} \u2014 file not found")
            continue

        obj_dir = os.path.join(extension_path, info["DirName"], info["Name"])
        accounted.add(os.path.normpath(info["File"]))

        if info["Borrowed"]:
            borrowed_list.append(obj)

            print(f"  [BORROWED] {obj['Type']}.{obj['Name']}")

            # Find .bsl files and interceptors
            bsl_files = get_bsl_files(obj["Type"], obj["Name"], extension_path)
            for bsl in bsl_files:
                accounted.add(os.path.normpath(bsl))
                print_interceptors(bsl, extension_path)

            obj_el = info.get("ObjElement")
            if obj_el is None:
                continue

            # Local: a common form is itself the form; read its own Form.xml.
            if obj["Type"] == "CommonForm":
                form_xml_path = os.path.join(obj_dir, "Ext", "Form.xml")
                accounted.add(os.path.normpath(form_xml_path))
                print_form(obj["Name"], form_xml_path)

            # Local: every ChildObjects kind, ownership per child.
            children = get_child_objects(obj_el, obj_dir)
            own_by_kind = {}
            borrowed_items = 0
            unknown = []
            for ch in children:
                if ch["Own"] is None:
                    unknown.append(f"{ch['Kind']}.{ch['Name']}")
                elif ch["Own"]:
                    own_by_kind.setdefault(ch["Kind"], []).append(ch["Name"])
                else:
                    borrowed_items += 1
            parts = [f"{len(v)} own {CHILD_KIND_LABELS.get(k, k)}" for k, v in own_by_kind.items()]
            if borrowed_items > 0:
                parts.append(f"{borrowed_items} borrowed items")
            if len(parts) > 0:
                print(f"             ChildObjects: {', '.join(parts)}")
            for kind, names in own_by_kind.items():
                if kind not in ("Attribute", "TabularSection", "Form"):
                    print(f"             Own {kind}: {', '.join(names)}")
            for u in unknown:
                print(f"             [?] {u} \u2014 ownership unknown (no descriptor file)")

            for ch in children:
                if ch["Kind"] == "Form":
                    accounted |= files_under(ch["File"]) | files_under(ch["File"][:-4])
                    form_xml_path = os.path.join(obj_dir, "Forms", ch["Name"], "Ext", "Form.xml")
                    print_form(ch["Name"], form_xml_path, parse_object_element(ch["File"]))
                elif ch["Kind"] == "Template":
                    accounted.add(os.path.normpath(ch["File"]))
                    tpl_el = parse_object_element(ch["File"])
                    if ch["Own"]:
                        accounted |= files_under(ch["File"][:-4])
                    elif any(p == "Template" for p, _s in get_extended_properties(tpl_el)):
                        accounted |= files_under(ch["File"][:-4])
                        print(f"             Template.{ch['Name']} (borrowed, content replaced)")
                elif ch["Kind"] == "Subsystem" and ch["File"]:
                    accounted |= describe_nested_subsystem(ch, extension_path)
                elif ch["Kind"] == "Command":
                    accounted |= files_under(os.path.join(obj_dir, "Commands", ch["Name"]))

            # Local: extended properties (Type, Content, Rights, Predefined ...).
            ext_lines, ext_files = describe_extensions(obj_el, obj_dir)
            accounted |= ext_files
            for line in ext_lines:
                print(f"             {line}")
        else:
            own_list.append(obj)
            print(f"  [OWN]      {obj['Type']}.{obj['Name']}")
            # Local: a wholly-own object accounts for everything under its folder.
            accounted |= files_under(obj_dir)

            # Brief info for own objects
            obj_el = info.get("ObjElement")
            if obj_el is not None:
                child_obj = obj_el.find("md:ChildObjects", MD_NSMAP)
                if child_obj is not None:
                    counts = {}
                    for c in child_obj:
                        if not isinstance(c.tag, str):
                            continue
                        ln = etree.QName(c.tag).localname
                        counts[ln] = counts.get(ln, 0) + 1
                    parts = [f"{v} {CHILD_KIND_LABELS.get(k, k)}" for k, v in counts.items()]
                    if len(parts) > 0:
                        print(f"             {', '.join(parts)}")

    print("")
    print(f"=== Summary: {len(borrowed_list)} borrowed, {len(own_list)} own objects ===")

    # Local: completeness check — files no row above interpreted.
    unclassified = sorted(p for p in files_under(extension_path) if p not in accounted)
    print(f"=== Unclassified files: {len(unclassified)} ===")
    for p in unclassified:
        print(f"  [UNCLASSIFIED] {os.path.relpath(p, extension_path)}")


def print_interceptors(bsl, extension_path):
    rel_path = os.path.relpath(bsl, extension_path)
    interceptor_list = get_interceptors(bsl)
    if len(interceptor_list) > 0:
        for ic in interceptor_list:
            print(f'             &{ic["Type"]}("{ic["Method"]}") \u2014 line {ic["Line"]} in {rel_path}')
    else:
        print(f"             {rel_path} (no interceptors)")


def print_form(name, form_xml_path, descriptor_el=None):
    """Form line with its callType handlers. For a form of an adopted object the
    descriptor tells own vs. borrowed and whether the platform marks it Extended."""
    fi = get_form_interceptors(form_xml_path)
    if fi is None:
        print(f"             Form.{name} (?)")
        return
    form_tag = "borrowed" if fi["IsBorrowed"] else "own"
    if descriptor_el is not None and fi["IsBorrowed"]:
        if any(p == "Form" for p, _s in get_extended_properties(descriptor_el)):
            form_tag = "borrowed, modified"
    if len(fi["Interceptors"]) > 0:
        print(f"             Form.{name} ({form_tag}):")
        for ic in fi["Interceptors"]:
            print(f"               {ic}")
    else:
        print(f"             Form.{name} ({form_tag})")


def describe_nested_subsystem(ch, extension_path):
    """A nested subsystem is its own descriptor under <parent>/Subsystems/."""
    accounted = {os.path.normpath(ch["File"])}
    el = parse_object_element(ch["File"])
    tag = "?" if el is None else ("borrowed" if is_adopted(el) else "own")
    print(f"             Subsystem.{ch['Name']} ({tag})")
    if el is None:
        return accounted
    sub_dir = ch["File"][:-4]
    if not is_adopted(el):
        return accounted | files_under(sub_dir)
    lines, files = describe_extensions(el, sub_dir)
    for line in lines:
        print(f"               {line}")
    accounted |= files
    for grand in get_child_objects(el, sub_dir):
        if grand["Kind"] == "Subsystem" and grand["File"]:
            accounted |= describe_nested_subsystem(grand, extension_path)
    return accounted


# --- Mode B: Transfer check ---

def mode_b(objects, extension_path, config_path):
    transferred = 0
    not_transferred = 0
    needs_review = 0

    for obj in objects:
        info = get_object_info(obj["Type"], obj["Name"], extension_path)
        if info is None or not info["Exists"] or not info["Borrowed"]:
            continue

        # Find .bsl files with &ИзменениеИКонтроль
        bsl_files = get_bsl_files(obj["Type"], obj["Name"], extension_path)
        for bsl in bsl_files:
            interceptor_list = get_interceptors(bsl)
            mac_interceptors = [ic for ic in interceptor_list if ic["Type"] == "\u0418\u0437\u043c\u0435\u043d\u0435\u043d\u0438\u0435\u0418\u041a\u043e\u043d\u0442\u0440\u043e\u043b\u044c"]

            if len(mac_interceptors) == 0:
                continue

            for ic in mac_interceptors:
                method_name = ic["Method"]
                rel_bsl = bsl.replace(extension_path, "").lstrip("\\/")

                # Find #Вставка blocks in this file
                insert_blocks = get_insertion_blocks(bsl)

                if len(insert_blocks) == 0:
                    print(f'  [NEEDS_REVIEW] {obj["Type"]}.{obj["Name"]} \u2014 &\u0418\u0437\u043c\u0435\u043d\u0435\u043d\u0438\u0435\u0418\u041a\u043e\u043d\u0442\u0440\u043e\u043b\u044c("{method_name}") \u2014 no #\u0412\u0441\u0442\u0430\u0432\u043a\u0430 blocks')
                    needs_review += 1
                    continue

                # Find corresponding module in config
                if obj["Type"] not in CHILD_TYPE_DIR_MAP:
                    continue
                config_bsl = bsl.replace(extension_path, config_path)

                if not os.path.isfile(config_bsl):
                    print(f'  [NEEDS_REVIEW] {obj["Type"]}.{obj["Name"]} \u2014 &\u0418\u0437\u043c\u0435\u043d\u0435\u043d\u0438\u0435\u0418\u041a\u043e\u043d\u0442\u0440\u043e\u043b\u044c("{method_name}") \u2014 config module not found')
                    needs_review += 1
                    continue

                with open(config_bsl, "r", encoding="utf-8-sig") as fh:
                    config_content = fh.read()

                all_transferred = True
                for block in insert_blocks:
                    code = block["Code"]
                    if not code:
                        continue

                    # Normalize whitespace for comparison
                    code_norm = re.sub(r'\s+', ' ', code)
                    config_norm = re.sub(r'\s+', ' ', config_content)

                    if code_norm not in config_norm:
                        all_transferred = False

                if all_transferred:
                    print(f'  [TRANSFERRED]     {obj["Type"]}.{obj["Name"]} \u2014 &\u0418\u0437\u043c\u0435\u043d\u0435\u043d\u0438\u0435\u0418\u041a\u043e\u043d\u0442\u0440\u043e\u043b\u044c("{method_name}") \u2014 {len(insert_blocks)} block(s)')
                    transferred += 1
                else:
                    print(f'  [NOT_TRANSFERRED] {obj["Type"]}.{obj["Name"]} \u2014 &\u0418\u0437\u043c\u0435\u043d\u0435\u043d\u0438\u0435\u0418\u041a\u043e\u043d\u0442\u0440\u043e\u043b\u044c("{method_name}") \u2014 some blocks not found in config')
                    not_transferred += 1

    print("")
    print(f"=== Transfer check: {transferred} transferred, {not_transferred} not transferred, {needs_review} needs review ===")


# --- Main ---

def main():
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Analyze and compare 1C configuration extension (CFE)", allow_abbrev=False)
    parser.add_argument("-ExtensionPath", required=True, help="Path to extension dump root")
    parser.add_argument("-ConfigPath", required=True, help="Path to base config dump root")
    parser.add_argument("-Mode", choices=["A", "B"], default="A", help="A=overview, B=transfer check")
    args = parser.parse_args()

    extension_path = args.ExtensionPath
    config_path = args.ConfigPath
    mode = args.Mode

    # --- Resolve paths ---
    if not os.path.isabs(extension_path):
        extension_path = os.path.join(os.getcwd(), extension_path)
    if not os.path.isabs(config_path):
        config_path = os.path.join(os.getcwd(), config_path)
    if os.path.isfile(extension_path):
        extension_path = os.path.dirname(extension_path)
    if os.path.isfile(config_path):
        config_path = os.path.dirname(config_path)

    ext_cfg = os.path.join(extension_path, "Configuration.xml")
    src_cfg = os.path.join(config_path, "Configuration.xml")
    if not os.path.isfile(ext_cfg):
        print(f"Extension Configuration.xml not found: {ext_cfg}", file=sys.stderr)
        sys.exit(1)
    if not os.path.isfile(src_cfg):
        print(f"Config Configuration.xml not found: {src_cfg}", file=sys.stderr)
        sys.exit(1)

    # --- Parse extension Configuration.xml ---
    parser_xml = etree.XMLParser(remove_blank_text=False)
    ext_doc = etree.parse(ext_cfg, parser_xml)
    ext_root = ext_doc.getroot()

    ext_props = ext_root.find(".//md:Configuration/md:Properties", MD_NSMAP)
    ext_name_node = ext_props.find("md:Name", MD_NSMAP) if ext_props is not None else None
    ext_name = ext_name_node.text if ext_name_node is not None and ext_name_node.text else "?"
    prefix_node = ext_props.find("md:NamePrefix", MD_NSMAP) if ext_props is not None else None
    name_prefix = prefix_node.text if prefix_node is not None and prefix_node.text else ""
    purpose_node = ext_props.find("md:ConfigurationExtensionPurpose", MD_NSMAP) if ext_props is not None else None
    purpose = purpose_node.text if purpose_node is not None and purpose_node.text else "?"

    print(f"=== cfe-diff Mode {mode}: {ext_name} ({purpose}) ===")
    print(f"    NamePrefix: {name_prefix}")
    print("")

    # --- Collect ChildObjects ---
    child_obj_node = ext_root.find(".//md:Configuration/md:ChildObjects", MD_NSMAP)
    if child_obj_node is None:
        print("[WARN] No ChildObjects in extension")
        sys.exit(0)

    objects = []
    for child in child_obj_node:
        if not isinstance(child.tag, str):
            continue
        ln = etree.QName(child.tag).localname
        # Local: Language is listed too (it is an adopted object with a file).
        objects.append({"Type": ln, "Name": child.text or ""})

    if all(o["Type"] == "Language" for o in objects):
        print("No objects (besides Language) in extension.")
        sys.exit(0)

    # --- Run selected mode ---
    if mode == "A":
        mode_a(objects, extension_path)
    elif mode == "B":
        mode_b(objects, extension_path, config_path)


if __name__ == "__main__":
    main()
