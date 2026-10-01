#!/usr/bin/env python3
# form-validate v1.10 — Validate 1C managed form
# Licence and attribution: NOTICE.md of the 1c-metadata-manage skill.
# DynamicList attributes without MainTable and QueryText are an error —
# the form loads but fails to open.
# v1.10: the root version must equal Configuration.xml (1); a type spelled
# with an export folder name (cfg:Catalogs.X) is an error (12); the main attribute
# of a default object / record form belongs to the owner and a zero-length
# Description / Code is not bound (12b); Module.bsl is checked against the
# handlers Form.xml references (13) and for form-data conversion outside
# &НаСервере (14); a button or command Representation outside its own
# enumeration is an error (15).

import argparse
import os
import re
import sys
from lxml import etree

F_NS = "http://v8.1c.ru/8.3/xcf/logform"
V8_NS = "http://v8.1c.ru/8.1/data/core"

NSMAP = {"f": F_NS, "v8": V8_NS}

KNOWN_INVALID_TYPES = {
    'FormDataStructure', 'FormDataCollection', 'FormDataTree',
    'FormDataTreeItem', 'FormDataCollectionItem',
    'FormGroup', 'FormField', 'FormButton', 'FormDecoration', 'FormTable',
}

VALID_CLOSED_TYPES = {
    'xs:boolean', 'xs:string', 'xs:decimal', 'xs:dateTime', 'xs:binary',
    'v8:FillChecking', 'v8:Null', 'v8:StandardPeriod', 'v8:StandardBeginningDate', 'v8:Type',
    'v8:TypeDescription', 'v8:UUID', 'v8:ValueListType', 'v8:ValueTable', 'v8:ValueTree',
    'v8:Universal', 'v8:FixedArray', 'v8:FixedStructure',
    'v8ui:Color', 'v8ui:Font', 'v8ui:FormattedString', 'v8ui:HorizontalAlign',
    'v8ui:Picture', 'v8ui:SizeChangeMode', 'v8ui:VerticalAlign',
    'dcsset:DataCompositionComparisonType', 'dcsset:DataCompositionFieldPlacement',
    'dcsset:Filter', 'dcsset:SettingsComposer', 'dcsset:DataCompositionSettings',
    'dcssch:DataCompositionSchema',
    'dcscor:DataCompositionComparisonType', 'dcscor:DataCompositionGroupType',
    'dcscor:DataCompositionPeriodAdditionType', 'dcscor:DataCompositionSortDirection', 'dcscor:Field',
    'ent:AccountType', 'ent:AccumulationRecordType', 'ent:AccountingRecordType',
}

VALID_CFG_PREFIXES = {
    'AccountingRegisterRecordSet', 'AccumulationRegisterRecordSet',
    'BusinessProcessObject', 'BusinessProcessRef',
    'CatalogObject', 'CatalogRef',
    'ChartOfAccountsObject', 'ChartOfAccountsRef',
    'ChartOfCalculationTypesObject', 'ChartOfCalculationTypesRef',
    'ChartOfCharacteristicTypesObject', 'ChartOfCharacteristicTypesRef',
    'ConstantsSet', 'DataProcessorObject', 'DocumentObject', 'DocumentRef',
    'DynamicList', 'EnumRef', 'ExchangePlanObject', 'ExchangePlanRef',
    'ExternalDataProcessorObject', 'ExternalReportObject',
    'InformationRegisterRecordManager', 'InformationRegisterRecordSet',
    'ReportObject', 'TaskObject', 'TaskRef',
}

# Export folder names that are sometimes written where a type belongs -> the
# reference type, if the kind has one.
EXPORT_FOLDER_TYPES = {
    'Catalogs': 'CatalogRef', 'Documents': 'DocumentRef', 'Enums': 'EnumRef',
    'ChartsOfAccounts': 'ChartOfAccountsRef', 'ChartsOfCharacteristicTypes': 'ChartOfCharacteristicTypesRef',
    'ChartsOfCalculationTypes': 'ChartOfCalculationTypesRef', 'BusinessProcesses': 'BusinessProcessRef',
    'ExchangePlans': 'ExchangePlanRef', 'Tasks': 'TaskRef', 'DefinedTypes': 'DefinedType',
    'InformationRegisters': '', 'AccumulationRegisters': '', 'AccountingRegisters': '',
    'CalculationRegisters': '', 'Constants': '', 'DataProcessors': '', 'Reports': '', 'DocumentJournals': '',
}

MD_NS = "http://v8.1c.ru/8.3/MDClasses"

OWNER_KINDS = ('Catalog', 'Document', 'ChartOfAccounts', 'ChartOfCharacteristicTypes', 'ChartOfCalculationTypes',
               'ExchangePlan', 'BusinessProcess', 'Task', 'InformationRegister')

DIRECTIVE_MAP = {
    "наклиенте": "client", "atclient": "client",
    "насервере": "server", "atserver": "server",
    "насерверебезконтекста": "servernc", "atservernocontext": "servernc",
    "наклиентенасерверебезконтекста": "clientservernc", "atclientatservernocontext": "clientservernc",
    "наклиентенасервере": "clientserver", "atclientatserver": "clientserver",
}

# Largest number of parameters the platform passes to a handler, per element tag and
# event (a handler may declare fewer). Unlisted events are not arity-checked.
# Keys are lower case: the PowerShell hashtable matches them case-insensitively.
EVENT_ARITY = {k.lower(): v for k, v in {
    "Form|OnCreateAtServer": 2, "Form|OnOpen": 1, "Form|NotificationProcessing": 3, "Form|ExternalEvent": 3,
    "Form|FillCheckProcessingAtServer": 2, "Form|BeforeClose": 4, "Form|OnClose": 1, "Form|ChoiceProcessing": 2,
    "Form|OnReadAtServer": 1, "Form|BeforeWrite": 2, "Form|BeforeWriteAtServer": 3, "Form|OnWriteAtServer": 3,
    "Form|AfterWriteAtServer": 2, "Form|AfterWrite": 1,
    "InputField|OnChange": 1, "InputField|StartChoice": 4, "InputField|Clearing": 2, "InputField|ChoiceProcessing": 5,
    "InputField|AutoComplete": 6, "InputField|TextEditEnd": 5, "InputField|Opening": 2,
    "CheckBoxField|OnChange": 1, "LabelDecoration|Click": 2, "LabelDecoration|URLProcessing": 3,
    "LabelField|OnChange": 1, "LabelField|Click": 2, "LabelField|URLProcessing": 3, "RadioButtonField|OnChange": 1,
    "Pages|OnCurrentPageChange": 2,
    "Table|Selection": 4, "Table|OnActivateRow": 1, "Table|ChoiceProcessing": 3, "Table|OnStartEdit": 3,
    "Table|BeforeAddRow": 6, "Table|BeforeRowChange": 2, "Table|BeforeDeleteRow": 2, "Table|AfterDeleteRow": 1,
    "Table|OnChange": 1, "Table|OnEditEnd": 3,
    "Command|Action": 1,
}.items()}

DECL_RE = re.compile(r'^\s*(?:(?:Асинх|Async)\s+)?(?:Процедура|Функция|Procedure|Function)\s+([\w]+)\s*\(', re.I)
END_RE = re.compile(r'^\s*(?:КонецПроцедуры|КонецФункции|EndProcedure|EndFunction)\b', re.I)
CALL_RE = re.compile(r'(?<![\w.])(РеквизитФормыВЗначение|ЗначениеВРеквизитФормы|FormAttributeToValue|ValueToFormAttribute)\s*\(', re.I)
DIRECTIVE_RE = re.compile(r'^&\s*(\w+)')


def localname(el):
    return etree.QName(el.tag).localname


def read_lines(path):
    # File.ReadAllLines: CR, LF and CRLF end a line; no empty line after the last break.
    with open(path, encoding="utf-8-sig", errors="replace", newline="") as handle:
        text = handle.read()
    lines = re.split(r'\r\n|\r|\n', text)
    if lines and lines[-1] == "":
        lines.pop()
    return lines


def directive_of(text):
    dm = DIRECTIVE_RE.match(text)
    if dm and dm.group(1).lower() in DIRECTIVE_MAP:
        return DIRECTIVE_MAP[dm.group(1).lower()]
    return None


def bsl_procedures(lines):
    # name (lower case) -> list of {Name, Line, Directive, Params, Required}
    result = {}
    for i, line in enumerate(lines):
        m = DECL_RE.match(line)
        if not m:
            continue
        name = m.group(1)
        # Directive: walk back over blank lines, comments and annotations.
        directive = None
        for j in range(i - 1, -1, -1):
            s = lines[j].strip()
            if not s or s.startswith("//"):
                continue
            if s.startswith("&"):
                found = directive_of(s)
                if found:
                    directive = found
                continue
            break
        # Parameters: the text between the declaration's parentheses (strings and
        # comments skipped, may span lines).
        buf = []
        depth = 0
        in_str = False
        closed = False
        j = i
        while j < min(i + 40, len(lines)) and not closed:
            s = lines[j]
            k = m.end() - 1 if j == i else 0
            while k < len(s):
                ch = s[k]
                if in_str:
                    buf.append(ch)
                    if ch == '"':
                        in_str = False
                    k += 1
                    continue
                if ch == '"':
                    in_str = True
                    buf.append(ch)
                elif ch == '/' and k + 1 < len(s) and s[k + 1] == '/':
                    break
                elif ch == '(':
                    depth += 1
                    if depth > 1:
                        buf.append(ch)
                elif ch == ')':
                    depth -= 1
                    if depth == 0:
                        closed = True
                        break
                    buf.append(ch)
                elif depth >= 1:
                    buf.append(ch)
                k += 1
            buf.append(' ')
            j += 1
        params = required = None
        if closed:
            parts = []
            cur = []
            p_in_str = False
            p_depth = 0
            for ch in "".join(buf):
                if p_in_str:
                    cur.append(ch)
                    if ch == '"':
                        p_in_str = False
                    continue
                if ch == '"':
                    p_in_str = True
                if ch == '(':
                    p_depth += 1
                if ch == ')':
                    p_depth -= 1
                if ch == ',' and p_depth == 0:
                    parts.append("".join(cur))
                    cur = []
                    continue
                cur.append(ch)
            parts.append("".join(cur))
            parts = [part for part in parts if part.strip()]
            params = len(parts)
            required = sum(1 for part in parts if "=" not in part)
        result.setdefault(name.lower(), []).append(
            {"Name": name, "Line": i + 1, "Directive": directive, "Params": params, "Required": required})
    return result


def form_data_conversions(lines):
    # {Line, Procedure, Directive, Call} for every unqualified conversion call
    found = []
    cur = cur_directive = pending = None
    in_str = False
    for i, line in enumerate(lines):
        # Strip string literals (a multi-line literal continues on lines starting with |) and comments.
        if in_str and not line.lstrip().startswith("|"):
            in_str = False
        code = []
        k = 0
        while k < len(line):
            ch = line[k]
            if in_str:
                if ch == '"':
                    if k + 1 < len(line) and line[k + 1] == '"':
                        k += 2
                        continue
                    in_str = False
                k += 1
                continue
            if ch == '"':
                in_str = True
                k += 1
                continue
            if ch == '/' and k + 1 < len(line) and line[k + 1] == '/':
                break
            code.append(ch)
            k += 1
        c = "".join(code)
        s = c.strip()
        if s.startswith("&"):
            found_directive = directive_of(s)
            if found_directive:
                pending = found_directive
            continue
        dmatch = DECL_RE.match(c)
        if dmatch:
            cur = dmatch.group(1)
            cur_directive = pending
            pending = None
        if END_RE.match(c):
            cur = cur_directive = None
            continue
        for cm in CALL_RE.finditer(c):
            found.append({"Line": i + 1, "Procedure": cur, "Directive": cur_directive, "Call": cm.group(1)})
    return found


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Validate 1C managed form", allow_abbrev=False)
    parser.add_argument("-FormPath", "-Path", required=True)
    parser.add_argument("-Detailed", action="store_true")
    parser.add_argument("-MaxErrors", type=int, default=30)
    args = parser.parse_args()

    form_path = args.FormPath
    detailed = args.Detailed
    max_errors = args.MaxErrors

    if not os.path.isabs(form_path):
        form_path = os.path.join(os.getcwd(), form_path)

    # A: Directory → Ext/Form.xml
    if os.path.isdir(form_path):
        form_path = os.path.join(form_path, 'Ext', 'Form.xml')
    # B1: Missing Ext/ (e.g. Forms/Форма/Form.xml → Forms/Форма/Ext/Form.xml)
    if not os.path.exists(form_path):
        fn = os.path.basename(form_path)
        if fn == 'Form.xml':
            c = os.path.join(os.path.dirname(form_path), 'Ext', fn)
            if os.path.exists(c):
                form_path = c
    # B2: Descriptor (Forms/Форма.xml → Forms/Форма/Ext/Form.xml)
    if not os.path.exists(form_path) and form_path.endswith('.xml'):
        stem = os.path.splitext(os.path.basename(form_path))[0]
        parent = os.path.dirname(form_path)
        c = os.path.join(parent, stem, 'Ext', 'Form.xml')
        if os.path.exists(c):
            form_path = c

    if not os.path.isfile(form_path):
        print(f"File not found: {form_path}", file=sys.stderr)
        sys.exit(1)

    # --- Load XML ---
    try:
        xml_parser = etree.XMLParser(remove_blank_text=True)
        tree = etree.parse(form_path, xml_parser)
    except Exception as e:
        print(f"[ERROR] XML parse error: {e}")
        print()
        print("---")
        print("Errors: 1, Warnings: 0")
        sys.exit(1)

    root = tree.getroot()

    # Detect context: config vs EPF/ERF
    is_config_context = False
    config_version = ""
    walk_dir = os.path.dirname(os.path.abspath(form_path))
    for _ in range(15):
        parent = os.path.dirname(walk_dir)
        if parent == walk_dir:
            break
        if os.path.isfile(os.path.join(walk_dir, 'Configuration.xml')):
            is_config_context = True
            # The format version of the configuration (Check 1).
            try:
                with open(os.path.join(walk_dir, 'Configuration.xml'), encoding="utf-8-sig", errors="replace") as handle:
                    cfg_head = handle.read(2000)
                vm = re.search(r'<MetaDataObject[^>]+version="(\d+\.\d+)"', cfg_head, re.I)
                if vm:
                    config_version = vm.group(1)
            except OSError:
                pass
            break
        walk_dir = parent

    errors = 0
    warnings = 0
    ok_count = 0
    stopped = False
    output_lines = []

    def report_ok(msg):
        nonlocal ok_count
        ok_count += 1
        if detailed:
            output_lines.append(f"[OK]    {msg}")

    def report_error(msg):
        nonlocal errors, stopped
        errors += 1
        output_lines.append(f"[ERROR] {msg}")
        if errors >= max_errors:
            stopped = True

    def report_warn(msg):
        nonlocal warnings
        warnings += 1
        output_lines.append(f"[WARN]  {msg}")

    # --- Form name from path ---
    form_name = os.path.splitext(os.path.basename(form_path))[0]
    parent_dir = os.path.dirname(form_path)
    if parent_dir:
        ext_dir = os.path.basename(parent_dir)
        if ext_dir == "Ext":
            form_dir = os.path.dirname(parent_dir)
            if form_dir:
                form_name = os.path.basename(form_dir)

    output_lines.append(f"=== Validation: Form.{form_name} ===")
    output_lines.append("")

    # Early BaseForm detection
    has_base_form = root.find(f"{{{F_NS}}}BaseForm") is not None

    # --- Check 1: Root element and version ---
    if localname(root) != "Form":
        report_error(f"Root element is '{localname(root)}', expected 'Form'")
    else:
        version = root.get("version", "")
        if version and config_version and version != config_version:
            report_error(f"Form version='{version}' differs from Configuration.xml ({config_version}) \u2014 the Configurator refuses to load a dump with mixed format versions")
        elif version in ("2.17", "2.20"):
            report_ok(f"Root element: Form version={version}")
        elif version:
            report_warn(f"Form version='{version}' (expected 2.17 or 2.20)")
        else:
            report_warn("Form version attribute missing")

    # --- Check 2: AutoCommandBar ---
    if not stopped:
        acb = root.find(f"{{{F_NS}}}AutoCommandBar")
        if acb is not None:
            acb_name = acb.get("name", "")
            acb_id = acb.get("id", "")
            if acb_id == "-1":
                report_ok(f"AutoCommandBar: name='{acb_name}', id={acb_id}")
            else:
                report_error(f"AutoCommandBar id='{acb_id}', expected '-1'")
        else:
            report_error("AutoCommandBar element missing")

    # --- Collect all elements with IDs ---
    element_ids = {}    # id -> name
    element_names = {}  # name -> id (имена элементов уникальны в пределах формы)
    all_elements = []  # list of dicts {Name, Tag, Id, ParentName, Node}

    def collect_elements(node, parent_name):
        nonlocal stopped
        for child in node:
            if not isinstance(child.tag, str):
                continue

            name = child.get("name", "")
            eid = child.get("id", "")

            if name and eid:
                tag = localname(child)

                all_elements.append({
                    "Name": name,
                    "Tag": tag,
                    "Id": eid,
                    "ParentName": parent_name,
                    "Node": child,
                })

                if eid != "-1":
                    if eid in element_ids:
                        report_error(f"Duplicate element id={eid}: '{name}' and '{element_ids[eid]}'")
                    else:
                        element_ids[eid] = name

                    # Имена элементов уникальны (требование 1С)
                    if name in element_names:
                        report_error(f"Duplicate element name '{name}': id={eid} and id={element_names[name]}")
                    else:
                        element_names[name] = eid

                child_items = child.find(f"{{{F_NS}}}ChildItems")
                if child_items is not None:
                    collect_elements(child_items, name)

    child_items_root = root.find(f"{{{F_NS}}}ChildItems")
    if child_items_root is not None:
        collect_elements(child_items_root, "(root)")

    acb = root.find(f"{{{F_NS}}}AutoCommandBar")
    if acb is not None:
        acb_children = acb.find(f"{{{F_NS}}}ChildItems")
        if acb_children is not None:
            collect_elements(acb_children, "\u0424\u043e\u0440\u043c\u0430\u041a\u043e\u043c\u0430\u043d\u0434\u043d\u0430\u044f\u041f\u0430\u043d\u0435\u043b\u044c")

    # --- Check 3: Unique element IDs ---
    if not stopped:
        # Duplicates already reported during collection
        dup_count = 0
        id_counts = {}
        for el in all_elements:
            eid = el["Id"]
            if eid == "-1":
                continue
            id_counts[eid] = id_counts.get(eid, 0) + 1
        dup_count = sum(1 for v in id_counts.values() if v > 1)
        if dup_count == 0:
            report_ok(f"Unique element IDs: {len(element_ids)} elements")

    # --- Collect attributes (separate ID pool) ---
    attr_map = {}   # name -> node
    attr_ids = {}   # id -> name

    attr_nodes_parent = root.find(f"{{{F_NS}}}Attributes")
    attr_nodes = []
    if attr_nodes_parent is not None:
        attr_nodes = attr_nodes_parent.findall(f"{{{F_NS}}}Attribute")

    for attr in attr_nodes:
        attr_name = attr.get("name", "")
        attr_id = attr.get("id", "")
        if attr_name:
            # Имена реквизитов уникальны среди реквизитов (отдельный неймспейс от элементов)
            if attr_name in attr_map:
                report_error(f"Duplicate attribute name '{attr_name}': id={attr_id} and id={attr_map[attr_name].get('id', '')}")
            attr_map[attr_name] = attr
        if attr_id:
            if attr_id in attr_ids:
                report_error(f"Duplicate attribute id={attr_id}: '{attr_name}' and '{attr_ids[attr_id]}'")
            else:
                attr_ids[attr_id] = attr_name

        # Column IDs uniqueness within parent
        col_ids = {}
        col_names = {}  # имена колонок уникальны в пределах своего реквизита
        columns = attr.find(f"{{{F_NS}}}Columns")
        if columns is not None:
            for col in columns.findall(f"{{{F_NS}}}Column"):
                col_id = col.get("id", "")
                col_name = col.get("name", "")
                if col_id:
                    if col_id in col_ids:
                        report_error(f"Duplicate column id={col_id} in '{attr_name}': '{col_name}' and '{col_ids[col_id]}'")
                    else:
                        col_ids[col_id] = col_name
                if col_name:
                    if col_name in col_names:
                        report_error(f"Duplicate column name '{col_name}' in '{attr_name}': id={col_id} and id={col_names[col_name]}")
                    else:
                        col_names[col_name] = col_id

        type_val = ""
        for tn in attr.findall(f"{{{F_NS}}}Type/{{{V8_NS}}}Type"):
            text = "".join(tn.itertext())
            if text:
                type_val = text
                break
        if type_val == "cfg:DynamicList":
            main_table = attr.find(f"{{{F_NS}}}Settings/{{{F_NS}}}MainTable")
            query_text = attr.find(f"{{{F_NS}}}Settings/{{{F_NS}}}QueryText")
            has_main = main_table is not None and "".join(main_table.itertext()).strip()
            has_query = query_text is not None and "".join(query_text.itertext()).strip()
            if not has_main and not has_query:
                report_error(f"Attribute '{attr_name}': DynamicList has neither MainTable nor QueryText — the form will fail to open")

    if not stopped:
        if attr_ids:
            report_ok(f"Unique attribute IDs: {len(attr_ids)} entries")

    # --- Collect commands (separate ID pool) ---
    cmd_map = {}   # name -> node
    cmd_ids = {}   # id -> name

    cmd_nodes_parent = root.find(f"{{{F_NS}}}Commands")
    cmd_nodes = []
    if cmd_nodes_parent is not None:
        cmd_nodes = cmd_nodes_parent.findall(f"{{{F_NS}}}Command")

    for cmd in cmd_nodes:
        cmd_name = cmd.get("name", "")
        cmd_id = cmd.get("id", "")
        if cmd_name:
            # Имена команд уникальны среди команд (отдельный неймспейс)
            if cmd_name in cmd_map:
                report_error(f"Duplicate command name '{cmd_name}': id={cmd_id} and id={cmd_map[cmd_name].get('id', '')}")
            cmd_map[cmd_name] = cmd
        if cmd_id:
            if cmd_id in cmd_ids:
                report_error(f"Duplicate command id={cmd_id}: '{cmd_name}' and '{cmd_ids[cmd_id]}'")
            else:
                cmd_ids[cmd_id] = cmd_name

    if not stopped:
        if cmd_ids:
            report_ok(f"Unique command IDs: {len(cmd_ids)} entries")

    # --- Collect parameters (separate name pool, без id) ---
    param_names = {}  # name -> True (имена параметров уникальны среди параметров)
    params_parent = root.find(f"{{{F_NS}}}Parameters")
    if params_parent is not None:
        for param in params_parent.findall(f"{{{F_NS}}}Parameter"):
            param_name = param.get("name", "")
            if param_name:
                if param_name in param_names:
                    report_error(f"Duplicate parameter name '{param_name}'")
                else:
                    param_names[param_name] = True

    # --- Check 4: Companion elements ---
    companion_rules = {
        "InputField": ["ContextMenu", "ExtendedTooltip"],
        "CheckBoxField": ["ContextMenu", "ExtendedTooltip"],
        "LabelDecoration": ["ContextMenu", "ExtendedTooltip"],
        "LabelField": ["ContextMenu", "ExtendedTooltip"],
        "PictureDecoration": ["ContextMenu", "ExtendedTooltip"],
        "PictureField": ["ContextMenu", "ExtendedTooltip"],
        "CalendarField": ["ContextMenu", "ExtendedTooltip"],
        "UsualGroup": ["ExtendedTooltip"],
        "Pages": ["ExtendedTooltip"],
        "Page": ["ExtendedTooltip"],
        "Button": ["ExtendedTooltip"],
        "Table": ["ContextMenu", "AutoCommandBar", "SearchStringAddition", "ViewStatusAddition", "SearchControlAddition"],
    }

    if not stopped:
        companion_errors = 0
        companion_checked = 0

        for el in all_elements:
            if stopped:
                break
            tag = el["Tag"]
            el_name = el["Name"]
            node = el["Node"]

            if tag not in companion_rules:
                continue

            required = companion_rules[tag]
            companion_checked += 1

            for comp_tag in required:
                comp_node = node.find(f"{{{F_NS}}}{comp_tag}")
                if comp_node is None:
                    report_error(f"[{tag}] '{el_name}': missing companion <{comp_tag}>")
                    companion_errors += 1

        if companion_errors == 0 and companion_checked > 0:
            report_ok(f"Companion elements: {companion_checked} elements checked")

    # --- Check 5: DataPath -> Attribute references ---
    if not stopped:
        path_errors = 0
        path_checked = 0
        path_base_skipped = 0

        # All data-binding tags whose value is an attribute path (root must exist in <Attributes>).
        binding_tags = ["DataPath", "TitleDataPath", "FooterDataPath", "HeaderDataPath",
                        "MultipleValueDataPath", "MultipleValuePresentDataPath", "RowPictureDataPath", "MultipleValuePictureDataPath"]

        skip_tags = {"ContextMenu", "ExtendedTooltip", "AutoCommandBar", "SearchStringAddition", "ViewStatusAddition", "SearchControlAddition"}

        for el in all_elements:
            if stopped:
                break
            tag = el["Tag"]
            el_name = el["Name"]
            node = el["Node"]

            if tag in skip_tags:
                continue

            if has_base_form and el["Id"]:
                try:
                    if int(el["Id"]) < 1000000:
                        path_base_skipped += 1
                        continue
                except (ValueError, TypeError):
                    pass

            for b_tag in binding_tags:
                if stopped:
                    break
                dp_node = node.find(f"{{{F_NS}}}{b_tag}")
                if dp_node is None:
                    continue

                data_path = (dp_node.text or "").strip()
                if not data_path:
                    continue

                # Opaque platform-internal shapes — not validatable from Form.xml alone:
                #   - bare numeric (e.g. "10", "1000003") — internal index
                #   - "N/M:<uuid>" — metadata reference by UUID
                if re.match(r'^\d+$', data_path) or re.match(r'^\d+/\d+:[0-9a-fA-F-]+$', data_path):
                    continue

                path_checked += 1

                clean_path = re.sub(r'\[\d+\]', '', data_path)
                # Strip leading '~' (current row of DynamicList: ~Список.Поле)
                if clean_path.startswith('~'):
                    clean_path = clean_path[1:]
                segments = clean_path.split(".")
                root_attr = segments[0]

                # Resolve Items.<TableName>.CurrentData.<Field>... — table element, not attribute
                if root_attr == 'Items':
                    if len(segments) < 3 or segments[2] != 'CurrentData':
                        report_warn(f"[{tag}] '{el_name}': {b_tag}='{data_path}' — unknown Items.* shape, expected Items.<Table>.CurrentData.*")
                        continue
                    table_name = segments[1]
                    table_el = None
                    for candidate in all_elements:
                        if candidate["Tag"] == 'Table' and candidate["Name"] == table_name:
                            table_el = candidate
                            break
                    if table_el is None:
                        report_error(f"[{tag}] '{el_name}': {b_tag}='{data_path}' — table element '{table_name}' not found")
                        path_errors += 1
                        continue
                    table_dp_node = table_el["Node"].find(f"{{{F_NS}}}DataPath")
                    if table_dp_node is None or not (table_dp_node.text or "").strip():
                        continue
                    table_dp = re.sub(r'\[\d+\]', '', (table_dp_node.text or "").strip())
                    if table_dp.startswith('~'):
                        table_dp = table_dp[1:]
                    root_attr = table_dp.split(".")[0]

                if root_attr not in attr_map:
                    report_error(f"[{tag}] '{el_name}': {b_tag}='{data_path}' — attribute '{root_attr}' not found")
                    path_errors += 1

        path_msg = ""
        if path_checked > 0:
            path_msg = f"{path_checked} paths checked"
        if path_base_skipped > 0:
            skip_note = f"{path_base_skipped} base skipped"
            path_msg = f"{path_msg}, {skip_note}" if path_msg else skip_note
        if path_errors == 0 and path_msg:
            report_ok(f"Data bindings: {path_msg}")

    # --- Check 6: Button command references ---
    if not stopped:
        cmd_errors = 0
        cmd_checked = 0

        for el in all_elements:
            if stopped:
                break
            tag = el["Tag"]
            el_name = el["Name"]
            node = el["Node"]

            if tag != "Button":
                continue

            cmd_node = node.find(f"{{{F_NS}}}CommandName")
            if cmd_node is None:
                continue

            cmd_ref = (cmd_node.text or "").strip()
            if not cmd_ref:
                continue

            m = re.match(r'^Form\.Command\.(.+)$', cmd_ref)
            if m:
                cmd_name_ref = m.group(1)
                cmd_checked += 1
                if cmd_name_ref not in cmd_map:
                    report_error(f"[Button] '{el_name}': CommandName='{cmd_ref}' \u2014 command '{cmd_name_ref}' not found in Commands")
                    cmd_errors += 1

        if cmd_errors == 0 and cmd_checked > 0:
            report_ok(f"Command references: {cmd_checked} buttons checked")

    # --- Check 7: Events have handler names ---
    if not stopped:
        event_errors = 0
        event_checked = 0

        # Form-level events
        form_events = root.find(f"{{{F_NS}}}Events")
        if form_events is not None:
            for evt in form_events.findall(f"{{{F_NS}}}Event"):
                evt_name = evt.get("name", "")
                handler = (evt.text or "").strip()
                event_checked += 1
                if not handler:
                    report_error(f"Form event '{evt_name}': empty handler name")
                    event_errors += 1

        # Element-level events
        for el in all_elements:
            if stopped:
                break
            tag = el["Tag"]
            el_name = el["Name"]
            node = el["Node"]

            events_node = node.find(f"{{{F_NS}}}Events")
            if events_node is None:
                continue

            for evt in events_node.findall(f"{{{F_NS}}}Event"):
                evt_name = evt.get("name", "")
                handler = (evt.text or "").strip()
                event_checked += 1
                if not handler:
                    report_error(f"[{tag}] '{el_name}' event '{evt_name}': empty handler name")
                    event_errors += 1

        if event_errors == 0 and event_checked > 0:
            report_ok(f"Event handlers: {event_checked} events checked")

    # --- Check 8: Command actions ---
    if not stopped:
        action_errors = 0
        action_checked = 0

        for cmd in cmd_nodes:
            if stopped:
                break
            cmd_name = cmd.get("name", "")
            action_node = cmd.find(f"{{{F_NS}}}Action")
            action_checked += 1
            if action_node is None or not (action_node.text or "").strip():
                report_error(f"Command '{cmd_name}': missing or empty Action")
                action_errors += 1

        if action_errors == 0 and action_checked > 0:
            report_ok(f"Command actions: {action_checked} commands checked")

    # --- Check 9: MainAttribute count ---
    if not stopped:
        main_count = 0
        for attr in attr_nodes:
            main_node = attr.find(f"{{{F_NS}}}MainAttribute")
            if main_node is not None and (main_node.text or "") == "true":
                main_count += 1

        if main_count <= 1:
            main_info = "1 main attribute" if main_count == 1 else "no main attribute"
            report_ok(f"MainAttribute: {main_info}")
        else:
            report_error(f"Multiple MainAttribute=true ({main_count} found, expected 0 or 1)")

    # --- Check 10: Title must be multilingual XML ---
    if not stopped:
        title_node = root.find(f"{{{F_NS}}}Title")
        if title_node is not None:
            v8_items = title_node.findall(f"{{{V8_NS}}}item")
            if len(v8_items) == 0 and (title_node.text or "").strip():
                report_error(f"Form Title is plain text ('{(title_node.text or '').strip()}') \u2014 must be multilingual XML (<v8:item>). Use top-level 'title' key in form-compile DSL.")
            else:
                report_ok("Title: multilingual XML")

    # --- Check 11: Extension-specific validations ---
    base_form_node = root.find(f"{{{F_NS}}}BaseForm")
    is_extension = base_form_node is not None

    if not stopped and is_extension:
        # 11a. BaseForm version
        bf_version = base_form_node.get("version", "")
        if bf_version:
            report_ok(f"BaseForm: version={bf_version}")
        else:
            report_warn("BaseForm: version attribute missing")

        # 11b. callType values validation
        valid_call_types = {"Before", "After", "Override"}
        ct_errors = 0
        ct_checked = 0

        form_events_node = root.find(f"{{{F_NS}}}Events")
        if form_events_node is not None:
            for evt in form_events_node.findall(f"{{{F_NS}}}Event"):
                ct = evt.get("callType", "")
                if ct:
                    ct_checked += 1
                    if ct not in valid_call_types:
                        report_error(f"Form event '{evt.get('name', '')}': invalid callType='{ct}' (expected: Before, After, Override)")
                        ct_errors += 1

        for el in all_elements:
            if stopped:
                break
            events_node = el["Node"].find(f"{{{F_NS}}}Events")
            if events_node is None:
                continue
            for evt in events_node.findall(f"{{{F_NS}}}Event"):
                ct = evt.get("callType", "")
                if ct:
                    ct_checked += 1
                    if ct not in valid_call_types:
                        report_error(f"[{el['Tag']}] '{el['Name']}' event '{evt.get('name', '')}': invalid callType='{ct}'")
                        ct_errors += 1

        for cmd in cmd_nodes:
            if stopped:
                break
            cmd_name = cmd.get("name", "")
            for action in cmd.findall(f"{{{F_NS}}}Action"):
                ct = action.get("callType", "")
                if ct:
                    ct_checked += 1
                    if ct not in valid_call_types:
                        report_error(f"Command '{cmd_name}' Action: invalid callType='{ct}'")
                        ct_errors += 1

        if not stopped and ct_errors == 0 and ct_checked > 0:
            report_ok(f"callType values: {ct_checked} checked")

        # 11c. Extension ID ranges
        base_attr_names = set()
        base_cmd_names = set()

        bf_attrs = base_form_node.find(f"{{{F_NS}}}Attributes")
        if bf_attrs is not None:
            for b_attr in bf_attrs.findall(f"{{{F_NS}}}Attribute"):
                ba_name = b_attr.get("name", "")
                if ba_name:
                    base_attr_names.add(ba_name)

        bf_cmds = base_form_node.find(f"{{{F_NS}}}Commands")
        if bf_cmds is not None:
            for b_cmd in bf_cmds.findall(f"{{{F_NS}}}Command"):
                bc_name = b_cmd.get("name", "")
                if bc_name:
                    base_cmd_names.add(bc_name)

        id_warn_count = 0
        for attr in attr_nodes:
            a_name = attr.get("name", "")
            a_id = attr.get("id", "")
            if a_name and a_name not in base_attr_names and a_id:
                try:
                    int_id = int(a_id)
                    if int_id < 1000000:
                        report_warn(f"Attribute '{a_name}' (id={a_id}): extension-added attribute has id < 1000000")
                        id_warn_count += 1
                except (ValueError, TypeError):
                    pass

        for cmd in cmd_nodes:
            c_name = cmd.get("name", "")
            c_id = cmd.get("id", "")
            if c_name and c_name not in base_cmd_names and c_id:
                try:
                    int_id = int(c_id)
                    if int_id < 1000000:
                        report_warn(f"Command '{c_name}' (id={c_id}): extension-added command has id < 1000000")
                        id_warn_count += 1
                except (ValueError, TypeError):
                    pass

        if not stopped and id_warn_count == 0:
            ext_attr_count = sum(1 for a in attr_nodes if a.get("name", "") not in base_attr_names)
            ext_cmd_count = sum(1 for c in cmd_nodes if c.get("name", "") not in base_cmd_names)
            if (ext_attr_count + ext_cmd_count) > 0:
                report_ok(f"Extension ID ranges: {ext_attr_count} attr(s), {ext_cmd_count} cmd(s) \u2014 all >= 1000000")

    # Check callType without BaseForm
    if not stopped and not is_extension:
        call_type_without_base = False
        fe_node = root.find(f"{{{F_NS}}}Events")
        if fe_node is not None:
            for evt in fe_node.findall(f"{{{F_NS}}}Event"):
                if evt.get("callType"):
                    call_type_without_base = True
                    break
        if not call_type_without_base:
            for cmd in cmd_nodes:
                for action in cmd.findall(f"{{{F_NS}}}Action"):
                    if action.get("callType"):
                        call_type_without_base = True
                        break
                if call_type_without_base:
                    break
        if call_type_without_base:
            report_warn("callType attributes found but no BaseForm \u2014 possible incorrect structure")

    # --- Check 12: Type validation ---
    if not stopped:
        type_nodes = root.xpath('//v8:Type', namespaces={'v8': V8_NS})
        type_error_count = 0
        type_warn_count = 0
        type_count = len(type_nodes)

        for tn in type_nodes:
            if stopped:
                break
            tv = (tn.text or "").strip()
            if not tv:
                continue

            if tv in KNOWN_INVALID_TYPES:
                report_error(f'12. Type "{tv}": invalid runtime/UI type (not valid in XDTO schema)')
                type_error_count += 1
            elif tv in VALID_CLOSED_TYPES:
                pass  # OK
            elif tv.startswith("cfg:"):
                suffix = tv[4:]  # after "cfg:"
                prefix = suffix.split(".")[0]
                # cfg:Catalogs.X is the export folder name, not a type — the platform refuses it.
                if "." in suffix and prefix and prefix in EXPORT_FOLDER_TYPES:
                    folder_hint = f" \u2014 a reference type is 'cfg:{EXPORT_FOLDER_TYPES[prefix]}.<Name>'" if EXPORT_FOLDER_TYPES[prefix] else ""
                    report_error(f"12. Type '{tv}': export folder name '{prefix}' instead of a type{folder_hint}")
                    type_error_count += 1
                elif prefix in VALID_CFG_PREFIXES or suffix == "DynamicList":
                    # ExternalDataProcessorObject/ExternalReportObject valid only in EPF/ERF context
                    if is_config_context and prefix in ('ExternalDataProcessorObject', 'ExternalReportObject'):
                        report_error(f'12. Type "{tv}": External* type in configuration context (use DataProcessorObject/ReportObject instead)')
                        type_error_count += 1
                else:
                    report_warn(f'12. Type "{tv}": unrecognized cfg prefix')
                    type_warn_count += 1
            elif ":" in tv:
                pass  # unknown namespace, pass through
            else:
                report_warn(f'12. Type "{tv}": bare type without namespace prefix')
                type_warn_count += 1

        if type_error_count == 0 and type_warn_count == 0:
            if type_count > 0:
                report_ok(f'12. Types: {type_count} values, all valid')
            else:
                report_ok('12. Types: no type values to check')

    # --- Check 12b: the owner of a default object / record form ---
    # A form reached through DefaultObjectForm / DefaultFolderForm / DefaultRecordForm
    # (or the Auxiliary* twin) of a catalog, document, chart, exchange plan, business
    # process, task or information register receives an object of that owner: its main
    # attribute must be <Kind>Object.<Owner> (InformationRegisterRecordManager for a
    # register). A form copied from another object keeps the other owner's type and
    # loads, but fails when it is opened. Data processors and reports are not checked:
    # vendor configurations share one processor's object between several of them.
    # The same main attribute must not bind Description / Code when the owner's
    # DescriptionLength / CodeLength is 0 — the standard attribute does not exist.
    owner_descriptor = None
    if not stopped and form_name:
        form_dir_path = os.path.dirname(os.path.dirname(os.path.abspath(form_path)))
        forms_dir_path = os.path.dirname(form_dir_path)
        if os.path.basename(forms_dir_path) == "Forms":
            owner_xml_path = os.path.dirname(forms_dir_path) + ".xml"
            if os.path.isfile(owner_xml_path):
                try:
                    owner_descriptor = etree.parse(owner_xml_path).getroot()
                except Exception:
                    owner_descriptor = None
    if owner_descriptor is not None:
        md = {"md": MD_NS}
        owner_node = next((c for c in owner_descriptor if isinstance(c.tag, str)), None)
        owner_props = owner_node.find("md:Properties", md) if owner_node is not None else None
        owner_kind = localname(owner_node) if owner_node is not None else ""
        owner_name_node = owner_props.find("md:Name", md) if owner_props is not None else None
        owner_name = "".join(owner_name_node.itertext()).strip() if owner_name_node is not None else ""
        main_attr = None
        for attr in attr_nodes:
            main_node = attr.find(f"{{{F_NS}}}MainAttribute")
            if main_node is not None and "".join(main_node.itertext()).lower() == "true":
                main_attr = attr
                break
        main_types = []
        if main_attr is not None:
            for tn in main_attr.findall(f"{{{F_NS}}}Type/{{{V8_NS}}}Type"):
                text = "".join(tn.itertext()).strip()
                if text:
                    main_types.append(text)
        if owner_props is not None and owner_name and owner_kind in OWNER_KINDS:
            own_form_ref = f"{owner_kind}.{owner_name}.Form.{form_name}"
            slots = []
            for slot in ("DefaultObjectForm", "DefaultFolderForm", "DefaultRecordForm",
                         "AuxiliaryObjectForm", "AuxiliaryFolderForm", "AuxiliaryRecordForm"):
                slot_node = owner_props.find(f"md:{slot}", md)
                if slot_node is not None and "".join(slot_node.itertext()).strip() == own_form_ref:
                    slots.append(slot)
            if slots and main_attr is not None:
                if owner_kind == "InformationRegister":
                    expected_type = f"cfg:InformationRegisterRecordManager.{owner_name}"
                else:
                    expected_type = f"cfg:{owner_kind}Object.{owner_name}"
                if len(main_types) != 1 or main_types[0] != expected_type:
                    report_error(f"12b. Main attribute '{main_attr.get('name', '')}' has type '{', '.join(main_types)}', "
                                 f"but the form is {' / '.join(slots)} of {owner_kind}.{owner_name} \u2014 expected "
                                 f"'{expected_type}' (form copied from another object?)")
                else:
                    report_ok(f"12b. Owner: main attribute '{main_attr.get('name', '')}' is {expected_type}")
            if main_attr is not None and len(main_types) == 1 and main_types[0] == f"cfg:{owner_kind}Object.{owner_name}":
                main_name = main_attr.get("name", "")
                bound_paths = {"".join(dp.itertext()).strip() for dp in root.iter(f"{{{F_NS}}}DataPath")}
                for length_prop, standard in (("DescriptionLength", "Description"), ("CodeLength", "Code")):
                    length_node = owner_props.find(f"md:{length_prop}", md)
                    if (length_node is not None and "".join(length_node.itertext()).strip() == "0"
                            and f"{main_name}.{standard}" in bound_paths):
                        report_error(f"12b. '{main_name}.{standard}' is bound, but {owner_kind}.{owner_name} has "
                                     f"{length_prop}=0 \u2014 the object has no {standard}")

    # --- Check 13: Form.xml handlers against Module.bsl ---
    # Every event handler and command Action named in Form.xml must be a procedure of
    # the form module, declared once (a duplicate does not compile — error). The rest
    # are warnings, because vendor configurations ship all of them: a handler that is
    # missing, has no compilation directive, runs in the wrong context (client event
    # on a server procedure, *AtServer event or command on a client one), or has more
    # mandatory parameters than the platform passes for that event.
    # Check 14: РеквизитФормыВЗначение / ЗначениеВРеквизитФормы need the form
    # context on the server — a call in a procedure explicitly compiled &НаКлиенте,
    # &НаСервереБезКонтекста or &НаКлиентеНаСервереБезКонтекста is an error. A procedure
    # without a directive is server-side in a form module and is accepted.
    module_path = os.path.join(os.path.dirname(os.path.abspath(form_path)), "Form", "Module.bsl")
    if not stopped and os.path.isfile(module_path):
        module_lines = read_lines(module_path)
        procedures = bsl_procedures(module_lines)

        # References: form events, element events, command actions. In a borrowed form
        # (BaseForm) only the extension's own references are checked: an event with a
        # callType, an element with id >= 1000000, a command absent from the base form.
        refs = []
        base_cmds = set()
        if has_base_form:
            for b_cmd in root.findall(f"{{{F_NS}}}BaseForm/{{{F_NS}}}Commands/{{{F_NS}}}Command"):
                base_cmds.add(b_cmd.get("name", "").lower())
        form_events_node = root.find(f"{{{F_NS}}}Events")
        if form_events_node is not None:
            for evt in form_events_node.findall(f"{{{F_NS}}}Event"):
                if has_base_form and not evt.get("callType"):
                    continue
                refs.append({"Owner": "Form", "Event": evt.get("name", ""), "Handler": "".join(evt.itertext()).strip(),
                             "Where": f"Form event '{evt.get('name', '')}'"})
        for el in all_elements:
            events_node = el["Node"].find(f"{{{F_NS}}}Events")
            if events_node is None:
                continue
            is_base_element = False
            if has_base_form:
                try:
                    is_base_element = int(el["Id"]) < 1000000
                except ValueError:
                    pass
            for evt in events_node.findall(f"{{{F_NS}}}Event"):
                if is_base_element and not evt.get("callType"):
                    continue
                refs.append({"Owner": el["Tag"], "Event": evt.get("name", ""), "Handler": "".join(evt.itertext()).strip(),
                             "Where": f"[{el['Tag']}] '{el['Name']}' event '{evt.get('name', '')}'"})
        for cmd in cmd_nodes:
            c_name = cmd.get("name", "")
            for action in cmd.findall(f"{{{F_NS}}}Action"):
                if has_base_form and c_name.lower() in base_cmds and not action.get("callType"):
                    continue
                refs.append({"Owner": "Command", "Event": "Action", "Handler": "".join(action.itertext()).strip(),
                             "Where": f"Command '{c_name}'"})

        handler_errors = 0
        handler_warnings = 0
        handlers_checked = 0
        seen_duplicates = set()
        for ref in refs:
            if stopped:
                break
            if not ref["Handler"]:
                continue
            handlers_checked += 1
            decls = procedures.get(ref["Handler"].lower())
            if not decls:
                report_warn(f"13. {ref['Where']}: handler '{ref['Handler']}' not found in Module.bsl")
                handler_warnings += 1
                continue
            if len(decls) > 1:
                if ref["Handler"].lower() not in seen_duplicates:
                    seen_duplicates.add(ref["Handler"].lower())
                    report_error(f"13. Handler '{ref['Handler']}' is declared {len(decls)} times in Module.bsl "
                                 f"(lines {', '.join(str(d['Line']) for d in decls)}) \u2014 the module does not compile")
                    handler_errors += 1
                continue
            decl = decls[0]
            # Events are named by an identifier; a UUID-named event carries no contract here.
            if not re.match(r'^[A-Za-z]\w*$', ref["Event"]):
                continue
            if not decl["Directive"]:
                report_warn(f"13. {ref['Where']}: handler '{decl['Name']}' (line {decl['Line']}) has no compilation "
                            f"directive \u2014 it compiles &НаСервере")
                handler_warnings += 1
            else:
                server_event = ref["Event"].endswith("AtServer")
                if server_event and decl["Directive"] not in ("server", "servernc"):
                    report_warn(f"13. {ref['Where']}: handler '{decl['Name']}' (line {decl['Line']}) is not a server "
                                f"procedure \u2014 a *AtServer event needs &НаСервере")
                    handler_warnings += 1
                elif not server_event and decl["Directive"] != "client":
                    report_warn(f"13. {ref['Where']}: handler '{decl['Name']}' (line {decl['Line']}) is not &НаКлиенте "
                                f"\u2014 client events and commands run on the client")
                    handler_warnings += 1
            arity_key = f"{ref['Owner']}|{ref['Event']}".lower()
            if arity_key in EVENT_ARITY and decl["Required"] is not None and decl["Required"] > EVENT_ARITY[arity_key]:
                report_warn(f"13. {ref['Where']}: handler '{decl['Name']}' (line {decl['Line']}) requires "
                            f"{decl['Required']} parameters, the platform passes at most {EVENT_ARITY[arity_key]}")
                handler_warnings += 1
        if handler_errors == 0 and handler_warnings == 0:
            if handlers_checked > 0:
                report_ok(f"13. Handlers: {handlers_checked} references match Module.bsl")
            else:
                report_ok("13. Handlers: none referenced")

        conversion_errors = 0
        directive_names = {"client": "&НаКлиенте", "servernc": "&НаСервереБезКонтекста",
                           "clientservernc": "&НаКлиентеНаСервереБезКонтекста"}
        for conv in form_data_conversions(module_lines):
            if stopped:
                break
            if conv["Directive"] and conv["Directive"] != "server":
                dir_name = directive_names.get(conv["Directive"], "&НаКлиентеНаСервере")
                report_error(f"14. Module.bsl line {conv['Line']}: {conv['Call']} in '{conv['Procedure']}' compiled "
                             f"{dir_name} \u2014 it needs the form context on the server (&НаСервере)")
                conversion_errors += 1
        if conversion_errors == 0:
            report_ok("14. Form data conversion: server context only")

    # --- Check 15: Representation of buttons and commands ---
    # The two properties have different enumerations: a button shows picture and
    # text as PictureAndText, a command as TextPicture. The other spelling is not a
    # value of the property, and the platform refuses the file with an XDTO
    # exception on load.
    if not stopped:
        repr_errors = 0
        repr_allowed = {"Button": ["Auto", "Text", "Picture", "PictureAndText"],
                        "Command": ["Auto", "Text", "Picture", "TextPicture"]}
        repr_nodes = [("Button", el["Name"], el["Node"]) for el in all_elements if el["Tag"] == "Button"]
        repr_nodes += [("Command", cmd.get("name", ""), cmd) for cmd in cmd_nodes]
        for kind, rname, node in repr_nodes:
            repr_node = node.find(f"{{{F_NS}}}Representation")
            if repr_node is None:
                continue
            value = "".join(repr_node.itertext()).strip()
            if value.lower() not in [v.lower() for v in repr_allowed[kind]]:
                report_error(f"15. [{kind}] '{rname}': Representation='{value}' is not a value of this property "
                             f"(expected: {', '.join(repr_allowed[kind])})")
                repr_errors += 1
        if repr_errors == 0:
            report_ok("15. Button/command Representation values")

    # --- Finalize ---
    checks = ok_count + errors + warnings
    if errors == 0 and warnings == 0 and not detailed:
        result = f"=== Validation OK: Form.{form_name} ({checks} checks) ==="
    else:
        output_lines.append("")
        output_lines.append(f"=== Result: {errors} errors, {warnings} warnings ({checks} checks) ===")
        result = "\n".join(output_lines)

    print(result)

    if errors > 0:
        sys.exit(1)
    else:
        sys.exit(0)


if __name__ == "__main__":
    main()
