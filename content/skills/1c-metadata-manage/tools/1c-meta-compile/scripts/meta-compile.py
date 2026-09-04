#!/usr/bin/env python3
# meta-compile v1.68 — Compile 1C metadata object from JSON
# Source: https://github.com/Nikolay-Shirokov/cc-1c-skills

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import uuid
import xml.etree.ElementTree as ET
from lxml import etree

sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")

# ============================================================
# Support guard (Ext/ParentConfigurations.bin) — see docs/support-manage.md
# Shared implementation: tools/_shared/support_guard.py (Python port of
# tools/_shared/support-guard.ps1 — same .dev.env SUPPORT_EDIT_POLICY source,
# .v8-project.json is documentation-only for this guard, see docs/db-manage.md).
# ============================================================
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "_shared"))
import support_guard  # noqa: E402

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "_common"))
import meta_dsl  # noqa: E402

# ---------------------------------------------------------------------------
# Inline utilities
# ---------------------------------------------------------------------------

def esc_xml(s):
    return s.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').replace('"', '&quot;')

def new_uuid():
    return str(uuid.uuid4())

def write_utf8_bom(path, content):
    with open(path, 'w', encoding='utf-8-sig', newline='') as f:
        f.write(content)

# ---------------------------------------------------------------------------
# XML builder (lines list)
# ---------------------------------------------------------------------------

lines = []

def X(text):
    lines.append(text)

def emit_mltext(indent, tag, text):
    # None / empty string -> self-closing tag; a dict -> one item per language.
    if text is None or (isinstance(text, str) and text == '') or not text:
        X(f'{indent}<{tag}/>')
        return
    X(f'{indent}<{tag}>')
    emit_ml_items(f'{indent}\t', text)
    X(f'{indent}</{tag}>')

# ---------------------------------------------------------------------------
# CamelCase splitter
# ---------------------------------------------------------------------------

def split_camel_case(name):
    if not name:
        return name
    result = re.sub(r'([а-яё])([А-ЯЁ])', r'\1 \2', name)
    result = re.sub(r'([a-z])([A-Z])', r'\1 \2', result)
    if len(result) > 1:
        result = result[0] + result[1:].lower()
    return result

# ---------------------------------------------------------------------------
# 1. Load and validate JSON
# ---------------------------------------------------------------------------

parser = argparse.ArgumentParser(allow_abbrev=False)
parser.add_argument('-JsonPath', required=True)
parser.add_argument('-OutputDir', required=True)
args = parser.parse_args()

json_path = args.JsonPath
output_dir = args.OutputDir

if not os.path.isfile(json_path):
    print(f'File not found: {json_path}', file=sys.stderr)
    sys.exit(1)

with open(json_path, 'r', encoding='utf-8-sig') as f:
    json_text = f.read()

defn = json.loads(json_text)

support_guard.assert_edit_allowed(output_dir, "editable")

# --- Batch mode: JSON array of objects ---
if isinstance(defn, list):
    batch_ok = 0
    batch_fail = 0
    for idx, item in enumerate(defn, 1):
        tmp_fd, tmp_path = tempfile.mkstemp(suffix='.json', prefix=f'meta-compile-batch-{idx}-')
        try:
            with os.fdopen(tmp_fd, 'w', encoding='utf-8') as f:
                json.dump(item, f, ensure_ascii=False, indent=2)
            rc = subprocess.call([sys.executable, __file__, '-JsonPath', tmp_path, '-OutputDir', output_dir])
            if rc == 0:
                batch_ok += 1
            else:
                batch_fail += 1
        finally:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)
    print()
    print(f"=== Batch: {len(defn)} objects, {batch_ok} compiled, {batch_fail} failed ===")
    sys.exit(1 if batch_fail > 0 else 0)

# Normalize field synonyms: accept "objectType" as alias for "type"
if not defn.get('type') and defn.get('objectType'):
    defn['type'] = defn['objectType']

# Object type synonyms (Russian -> English)
object_type_synonyms = {
    'Справочник': 'Catalog',
    'Каталог': 'Catalog',
    'Документ': 'Document',
    'Перечисление': 'Enum',
    'Константа': 'Constant',
    'РегистрСведений': 'InformationRegister',
    'РегистрНакопления': 'AccumulationRegister',
    'РегистрБухгалтерии': 'AccountingRegister',
    'РегистрРасчёта': 'CalculationRegister',
    'РегистрРасчета': 'CalculationRegister',
    'ПланСчетов': 'ChartOfAccounts',
    'ПланВидовХарактеристик': 'ChartOfCharacteristicTypes',
    'ПланВидовРасчёта': 'ChartOfCalculationTypes',
    'ПланВидовРасчета': 'ChartOfCalculationTypes',
    'БизнесПроцесс': 'BusinessProcess',
    'Задача': 'Task',
    'ПланОбмена': 'ExchangePlan',
    'ЖурналДокументов': 'DocumentJournal',
    'Отчёт': 'Report',
    'Отчет': 'Report',
    'Обработка': 'DataProcessor',
    'ОбщийМодуль': 'CommonModule',
    'РегламентноеЗадание': 'ScheduledJob',
    'ПодпискаНаСобытие': 'EventSubscription',
    'HTTPСервис': 'HTTPService',
    'ВебСервис': 'WebService',
    'ОпределяемыйТип': 'DefinedType',
    'ФункциональнаяОпция': 'FunctionalOption',
    'ОбщийРеквизит': 'CommonAttribute',
    'ОбщаяКоманда': 'CommonCommand',
    'ОбщаяФорма': 'CommonForm',
    'ОбщаяКартинка': 'CommonPicture',
    'ОбщийМакет': 'CommonTemplate',
    'ГруппаКоманд': 'CommandGroup',
    'Нумератор': 'DocumentNumerator',
    'КритерийОтбора': 'FilterCriterion',
    'ПараметрФункциональныхОпций': 'FunctionalOptionsParameter',
    'Последовательность': 'Sequence',
    'ПараметрСеанса': 'SessionParameter',
    'ХранилищеНастроек': 'SettingsStorage',
    'WSСсылка': 'WSReference',
}

# Enum property value synonyms — model often gets these slightly wrong
enum_value_aliases = {
    # RegisterType (AccumulationRegister)
    'Balances': 'Balance', 'Остатки': 'Balance', 'Обороты': 'Turnovers',
    # WriteMode (InformationRegister)
    'RecordSubordinate': 'RecorderSubordinate', 'Subordinate': 'RecorderSubordinate',
    'ПодчинениеРегистратору': 'RecorderSubordinate', 'Независимый': 'Independent',
    # DependenceOnCalculationTypes (ChartOfCalculationTypes)
    'NotDependOnCalculationTypes': 'DontUse', 'NoDependence': 'DontUse', 'NotUsed': 'DontUse',
    'Depend': 'OnActionPeriod', 'ПоПериодуДействия': 'OnActionPeriod',
    # InformationRegisterPeriodicity
    'None': 'Nonperiodical', 'Daily': 'Day', 'Monthly': 'Month',
    'Quarterly': 'Quarter', 'Yearly': 'Year',
    'Непериодический': 'Nonperiodical', 'Секунда': 'Second', 'День': 'Day',
    'Месяц': 'Month', 'Квартал': 'Quarter', 'Год': 'Year',
    'ПозицияРегистратора': 'RecorderPosition',
    # DataLockControlMode
    'Автоматический': 'Automatic', 'Управляемый': 'Managed',
    # FullTextSearch
    'Использовать': 'Use', 'НеИспользовать': 'DontUse',
    # Posting
    'Разрешить': 'Allow', 'Запретить': 'Deny',
    # EditType
    'ВДиалоге': 'InDialog', 'ВСписке': 'InList', 'ОбаСпособа': 'BothWays',
    # DefaultPresentation
    'ВВидеНаименования': 'AsDescription', 'ВВидеКода': 'AsCode',
    # FillChecking
    'НеПроверять': 'DontCheck', 'Ошибка': 'ShowError', 'Предупреждение': 'ShowWarning',
    # Indexing
    'НеИндексировать': 'DontIndex', 'Индексировать': 'Index',
    'ИндексироватьСДопУпорядочиванием': 'IndexWithAdditionalOrder',
}

# Valid enum values per property (from meta-validate)
valid_enum_values = {
    'RegisterType': ['Balance', 'Turnovers'],
    'WriteMode': ['Independent', 'RecorderSubordinate'],
    'InformationRegisterPeriodicity': ['Nonperiodical', 'Second', 'Day', 'Month', 'Quarter', 'Year', 'RecorderPosition'],
    'DependenceOnCalculationTypes': ['DontUse', 'OnActionPeriod'],
    'DataLockControlMode': ['Automatic', 'Managed'],
    'FullTextSearch': ['Use', 'DontUse'],
    'DataHistory': ['Use', 'DontUse'],
    'DefaultPresentation': ['AsDescription', 'AsCode'],
    'Posting': ['Allow', 'Deny'],
    'RealTimePosting': ['Allow', 'Deny'],
    'EditType': ['InDialog', 'InList', 'BothWays'],
    'HierarchyType': ['HierarchyFoldersAndItems', 'HierarchyOfItems'],
    'CodeType': ['String', 'Number'],
    'CodeAllowedLength': ['Variable', 'Fixed'],
    'NumberType': ['String', 'Number'],
    'NumberAllowedLength': ['Variable', 'Fixed'],
    'RegisterRecordsDeletion': ['AutoDelete', 'AutoDeleteOnUnpost', 'AutoDeleteOff'],
    'RegisterRecordsWritingOnPost': ['WriteModified', 'WriteSelected', 'WriteAll'],
    'ReturnValuesReuse': ['DontUse', 'DuringRequest', 'DuringSession'],
    'ReuseSessions': ['DontUse', 'AutoUse'],
    'FillChecking': ['DontCheck', 'ShowError', 'ShowWarning'],
    'Indexing': ['DontIndex', 'Index', 'IndexWithAdditionalOrder'],
    'SubordinationUse': ['ToItems', 'ToFolders', 'ToFoldersAndItems'],
    'CodeSeries': ['WholeCatalog', 'WithinSubordination', 'WithinOwnerSubordination',
                   'WholeCharacteristicKind', 'WholeChartOfAccounts'],
    'ChoiceMode': ['BothWays', 'QuickChoice', 'FromForm'],
    'CreateOnInput': ['Auto', 'Use', 'DontUse'],
    'ChoiceHistoryOnInput': ['Auto', 'DontUse'],
    'PredefinedDataUpdate': ['Auto', 'DontAutoUpdate', 'AutoUpdate'],
    'SearchStringModeOnInputByString': ['Begin', 'AnyPart'],
    'FullTextSearchOnInputByString': ['Use', 'DontUse'],
    'Category': ['NavigationPanel', 'ActionsPanel', 'FormCommandBar', 'FormNavigationPanel'],
}

def normalize_enum_value(prop_name, value):
    # 1. Check alias dictionary — silent auto-correct
    if value in enum_value_aliases:
        return enum_value_aliases[value]
    # 2. Case-insensitive match against valid values — silent
    valid = valid_enum_values.get(prop_name)
    if valid:
        for v in valid:
            if v.lower() == value.lower():
                return v
        # 3. Known property, unknown value — error with hint
        print(f"Invalid value '{value}' for property '{prop_name}'. Valid values: {', '.join(valid)}", file=sys.stderr)
        sys.exit(1)
    # 4. Unknown property — pass-through (no validation data)
    return value

def get_enum_prop(prop_name, field_name, default):
    val = defn.get(field_name)
    raw = str(val) if val else default
    return normalize_enum_value(prop_name, raw)

# ---------------------------------------------------------------------------
# Generic property emitters (ported from meta-compile.ps1 v1.68).
# The forgiving-input helpers they build on live in _common/meta_dsl.py.
# ---------------------------------------------------------------------------

def test_def_key(name):
    """True when the JSON definition mentions the key at all — distinguishes
    "not specified" (use the default) from "explicitly empty"."""
    return isinstance(defn, dict) and name in defn


def get_bool_prop(field_name, default):
    val = defn.get(field_name)
    if val is None:
        return default
    if isinstance(val, bool):
        return val
    return bool(re.match(r'^(true|1|да|истина)$', str(val), re.I))


def emit_ml_items(indent, val):
    """Multi-language items. A dict is {lang: text}; anything else is ru text."""
    if isinstance(val, dict):
        for k, v in val.items():
            X(f'{indent}<v8:item>')
            X(f'{indent}\t<v8:lang>{k}</v8:lang>')
            X(f'{indent}\t<v8:content>{meta_dsl.esc_xml_text(v)}</v8:content>')
            X(f'{indent}</v8:item>')
    else:
        X(f'{indent}<v8:item>')
        X(f'{indent}\t<v8:lang>ru</v8:lang>')
        X(f'{indent}\t<v8:content>{meta_dsl.esc_xml_text(val)}</v8:content>')
        X(f'{indent}</v8:item>')


def emit_dsl(fragment):
    """Emit a multi-line fragment produced by meta_dsl (which joins with CRLF)
    through X(), one line at a time, so the writer keeps a single line list."""
    for line in fragment.replace('\r\n', '\n').split('\n'):
        X(line)


def emit_min_max_value(indent, tag, val):
    X(f'{indent}{meta_dsl.build_min_max_value_xml(tag, val)}')


def emit_choice_parameter_links(indent, cpl):
    emit_dsl(meta_dsl.build_choice_parameter_links_xml(indent, cpl))


def emit_choice_parameters(indent, cp):
    emit_dsl(meta_dsl.build_choice_parameters_xml(indent, cp))


def emit_link_by_type(indent, spec):
    emit_dsl(meta_dsl.build_link_by_type_xml(indent, spec))


def emit_verbatim_ref(indent, tag, val):
    """A reference emitted exactly as given (no normalisation)."""
    if val:
        X(f'{indent}<{tag}>{esc_xml(str(val))}</{tag}>')
    else:
        X(f'{indent}<{tag}/>')


def normalize_form_ref(s):
    """Forgiving form reference: Russian metadata root -> English, "Форма" ->
    "Form", and a bare 3-part path gets the missing "Form" segment
    ("Справочник.Валюты.ФормаЭлемента" -> "Catalog.Валюты.Form.ФормаЭлемента")."""
    if not s:
        return s
    parts = str(s).split('.')
    if len(parts) < 3:
        return s
    root = meta_dsl.FILL_REF_ROOTS.get(parts[0].lower())
    if root:
        parts[0] = root
    for k in range(1, len(parts)):
        if parts[k].lower() == 'форма':
            parts[k] = 'Form'
    if 'Form' not in parts and len(parts) == 3:
        parts = [parts[0], parts[1], 'Form', parts[2]]
    return '.'.join(parts)


def emit_form_ref(indent, tag, val):
    if val:
        X(f'{indent}<{tag}>{esc_xml(normalize_form_ref(str(val)))}</{tag}>')
    else:
        X(f'{indent}<{tag}/>')


def emit_field_block(indent, tag, fields):
    """<Tag> holding a list of <xr:Field> (InputByString / DataLockFields).
    `fields` are already-expanded full paths; empty -> self-closing tag."""
    arr = [f for f in (fields or []) if str(f) != '']
    if not arr:
        X(f'{indent}<{tag}/>')
        return
    X(f'{indent}<{tag}>')
    for f in arr:
        X(f'{indent}\t<xr:Field>{esc_xml(str(f))}</xr:Field>')
    X(f'{indent}</{tag}>')


def emit_md_ref_list(indent, tag, items):
    arr = list(items) if items else []
    if not arr:
        X(f'{indent}<{tag}/>')
        return
    X(f'{indent}<{tag}>')
    for it in arr:
        X(f'{indent}\t<xr:Item xsi:type="xr:MDObjectRef">'
          f'{esc_xml(meta_dsl.normalize_md_object_ref(str(it)))}</xr:Item>')
    X(f'{indent}</{tag}>')


def emit_based_on(indent, items):
    emit_md_ref_list(indent, 'BasedOn', [i for i in (items or []) if i])


# --- Characteristics ---

def resolve_char_std_en(name):
    n = str(name).lower()
    if n in ('ref', 'ссылка'):
        return 'Ref'
    if n in ('parent', 'родитель'):
        return 'Parent'
    if n in ('owner', 'владелец'):
        return 'Owner'
    return None


CHAR_FROM_TABULAR_ROOTS = ('Catalog', 'Document', 'ChartOfCharacteristicTypes',
                           'ChartOfCalculationTypes', 'ChartOfAccounts', 'ExchangePlan',
                           'BusinessProcess', 'Task')
CHAR_PART_SYNONYMS = {'ТабличнаяЧасть': 'TabularSection', 'Измерение': 'Dimension',
                      'Ресурс': 'Resource', 'Реквизит': 'Attribute'}


def normalize_char_from(frm):
    """Forgiving `from` path of a characteristic source."""
    if not frm:
        return frm
    parts = str(frm).split('.')
    if parts[0] in object_type_synonyms:
        parts[0] = object_type_synonyms[parts[0]]
    for i in range(1, len(parts)):
        parts[i] = CHAR_PART_SYNONYMS.get(parts[i], parts[i])
    if len(parts) == 3 and parts[0] in CHAR_FROM_TABULAR_ROOTS:
        parts = [parts[0], parts[1], 'TabularSection', parts[2]]
    return '.'.join(parts)


def expand_char_field(field, frm):
    s = str(field) if field is not None else ''
    if not s:
        return s
    if s == '-1':      # field not set (an "empty" characteristic) — keep as is
        return '-1'
    if re.match(r'^(StandardAttribute|Attribute|Dimension|Resource)\.', s):
        return f'{frm}.{s}'
    if '.' not in s:
        en = resolve_char_std_en(s)
        if en:
            return f'{frm}.StandardAttribute.{en}'
        return f'{frm}.Attribute.{s}'
    return s


def get_char_int_field(obj, names):
    v = meta_dsl.get_ch_el_prop(obj, names)
    if v is None or str(v) == '':
        return -1
    return int(v)


def emit_characteristics(indent, chars):
    items = chars if isinstance(chars, list) else ([chars] if chars else [])
    if not items:
        X(f'{indent}<Characteristics/>')
        return
    g = meta_dsl.get_ch_el_prop
    X(f'{indent}<Characteristics>')
    for ch in items:
        types = g(ch, ['types', 'characteristicTypes', 'типы'])
        values = g(ch, ['values', 'characteristicValues', 'значения'])
        t_from = normalize_char_from(str(g(types, ['from', 'source', 'источник']) or ''))
        v_from = normalize_char_from(str(g(values, ['from', 'source', 'источник']) or ''))
        key = expand_char_field(g(types, ['key', 'keyField']), t_from)
        tff = expand_char_field(g(types, ['filterField', 'typesFilterField']), t_from)
        obj_f = expand_char_field(g(values, ['object', 'objectField']), v_from)
        typ_f = expand_char_field(g(values, ['type', 'typeField']), v_from)
        val_f = expand_char_field(g(values, ['value', 'valueField']), v_from)
        # numeric flag fields (usually -1, occasionally 0)
        dpf = get_char_int_field(types, ['dataPathField'])
        mvu = get_char_int_field(types, ['multipleValuesUseField'])
        mvk = get_char_int_field(values, ['multipleValuesKeyField'])
        mvo = get_char_int_field(values, ['multipleValuesOrderField'])

        X(f'{indent}\t<xr:Characteristic>')
        X(f'{indent}\t\t<xr:CharacteristicTypes from="{esc_xml(t_from)}">')
        X(f'{indent}\t\t\t<xr:KeyField>{esc_xml(key)}</xr:KeyField>')
        X(f'{indent}\t\t\t<xr:TypesFilterField>{esc_xml(tff)}</xr:TypesFilterField>')
        # filterValue: None -> nil; bare -> xs:string; full path -> DesignTimeRef; bool -> xs:boolean
        tfv_raw = g(types, ['filterValue', 'typesFilterValue'])
        if tfv_raw is None:
            X(f'{indent}\t\t\t<xr:TypesFilterValue xsi:nil="true"/>')
        else:
            n = meta_dsl.normalize_choice_value(tfv_raw)
            if n['Text'] == '':
                X(f'{indent}\t\t\t<xr:TypesFilterValue xsi:type="{n["XsiType"]}"/>')
            else:
                X(f'{indent}\t\t\t<xr:TypesFilterValue xsi:type="{n["XsiType"]}">'
                  f'{esc_xml(n["Text"])}</xr:TypesFilterValue>')
        X(f'{indent}\t\t\t<xr:DataPathField>{dpf}</xr:DataPathField>')
        X(f'{indent}\t\t\t<xr:MultipleValuesUseField>{mvu}</xr:MultipleValuesUseField>')
        X(f'{indent}\t\t</xr:CharacteristicTypes>')
        X(f'{indent}\t\t<xr:CharacteristicValues from="{esc_xml(v_from)}">')
        X(f'{indent}\t\t\t<xr:ObjectField>{esc_xml(obj_f)}</xr:ObjectField>')
        X(f'{indent}\t\t\t<xr:TypeField>{esc_xml(typ_f)}</xr:TypeField>')
        X(f'{indent}\t\t\t<xr:ValueField>{esc_xml(val_f)}</xr:ValueField>')
        X(f'{indent}\t\t\t<xr:MultipleValuesKeyField>{mvk}</xr:MultipleValuesKeyField>')
        X(f'{indent}\t\t\t<xr:MultipleValuesOrderField>{mvo}</xr:MultipleValuesOrderField>')
        X(f'{indent}\t\t</xr:CharacteristicValues>')
        X(f'{indent}\t</xr:Characteristic>')
    X(f'{indent}</Characteristics>')



if not defn.get('type'):
    print("JSON must have 'type' field", file=sys.stderr)
    sys.exit(1)

obj_type = str(defn['type'])
if obj_type in object_type_synonyms:
    obj_type = object_type_synonyms[obj_type]

valid_types = [
    'Catalog', 'Document', 'Enum', 'Constant', 'InformationRegister',
    'AccumulationRegister', 'AccountingRegister', 'CalculationRegister',
    'ChartOfAccounts', 'ChartOfCharacteristicTypes', 'ChartOfCalculationTypes',
    'BusinessProcess', 'Task', 'ExchangePlan', 'DocumentJournal',
    'Report', 'DataProcessor', 'CommonModule', 'ScheduledJob',
    'EventSubscription', 'HTTPService', 'WebService', 'DefinedType',
    'CommonAttribute', 'CommonCommand', 'CommonForm', 'CommonPicture', 'CommonTemplate',
    'CommandGroup', 'DocumentNumerator', 'FilterCriterion', 'FunctionalOption',
    'FunctionalOptionsParameter', 'Sequence', 'SessionParameter', 'SettingsStorage',
    'WSReference',
]
if obj_type not in valid_types:
    print(f"Unsupported type: {obj_type}. Valid: {', '.join(valid_types)}", file=sys.stderr)
    sys.exit(1)

if not defn.get('name'):
    print("JSON must have 'name' field", file=sys.stderr)
    sys.exit(1)

obj_name = str(defn['name'])

# Hand the shared DSL helpers this script's primitives and the object context.
# resolve_type_str is assigned after the type tables are built, below.
meta_dsl.ctx.esc_xml = esc_xml
meta_dsl.ctx.obj_type = obj_type
meta_dsl.ctx.obj_name = obj_name

# Auto-synonym
synonym = str(defn['synonym']) if defn.get('synonym') else split_camel_case(obj_name)
comment = str(defn['comment']) if defn.get('comment') else ''

# ---------------------------------------------------------------------------
# 4. Type system
# ---------------------------------------------------------------------------

type_synonyms = {
    'число': 'Number',
    'строка': 'String',
    'булево': 'Boolean',
    'дата': 'Date',
    'датавремя': 'DateTime',
    'время': 'Time',
    'time': 'Time',
    # ValueStorage / UUID — forgiving input (base64Binary or the Russian form)
    'valuestorage': 'ValueStorage',
    'base64binary': 'ValueStorage',
    'хранилищезначений': 'ValueStorage',
    'хранилищезначения': 'ValueStorage',
    'uuid': 'UUID',
    'уникальныйидентификатор': 'UUID',
    'таблицазначений': 'ValueTable',
    'деревозначений': 'ValueTree',
    'списокзначений': 'ValueListType',
    'стандартныйпериод': 'StandardPeriod',
    'number': 'Number',
    'string': 'String',
    'boolean': 'Boolean',
    'date': 'Date',
    'datetime': 'DateTime',
    'bool': 'Boolean',
    # Reference synonyms (Russian, lowercase)
    'справочникссылка': 'CatalogRef',
    'документссылка': 'DocumentRef',
    'перечислениессылка': 'EnumRef',
    'плансчетовссылка': 'ChartOfAccountsRef',
    'планвидовхарактеристикссылка': 'ChartOfCharacteristicTypesRef',
    'планвидоврасчётассылка': 'ChartOfCalculationTypesRef',
    'планвидоврасчетассылка': 'ChartOfCalculationTypesRef',
    'планобменассылка': 'ExchangePlanRef',
    'бизнеспроцессссылка': 'BusinessProcessRef',
    'задачассылка': 'TaskRef',
    'определяемыйтип': 'DefinedType',
    'definedtype': 'DefinedType',
    # English lowercase ref synonyms
    'catalogref': 'CatalogRef',
    'documentref': 'DocumentRef',
    'enumref': 'EnumRef',
}

def resolve_type_str(type_str):
    if not type_str:
        return type_str
    # Parameterized types: Number(15,2), Строка(100), etc.
    m = re.match(r'^([^(]+)\((.+)\)$', type_str)
    if m:
        base_name = m.group(1).strip()
        params = m.group(2)
        resolved = type_synonyms.get(base_name.lower())
        if resolved:
            return f'{resolved}({params})'
        return type_str
    # Reference types: СправочникСсылка.Организации -> CatalogRef.Организации
    if '.' in type_str:
        dot_idx = type_str.index('.')
        prefix = type_str[:dot_idx]
        suffix = type_str[dot_idx:]  # includes the dot
        resolved = type_synonyms.get(prefix.lower())
        if resolved:
            return f'{resolved}{suffix}'
        return type_str
    # Simple name lookup
    resolved = type_synonyms.get(type_str.lower())
    if resolved:
        return resolved
    return type_str


meta_dsl.ctx.resolve_type_str = resolve_type_str

# Platform types that need the v8: prefix (collections / periods, common on
# data-processor and report attributes).
V8_PLATFORM_TYPES = ('ValueTable', 'ValueTree', 'ValueList', 'ValueListType', 'StandardPeriod',
                     'StandardBeginningDate', 'PointInTime', 'TypeDescription',
                     'FixedArray', 'FixedMap', 'FixedStructure')
# Types living in their own namespace (declared locally on <v8:Type>).
TYPE_NAMESPACE_MAP = {
    'Chart': ('http://v8.1c.ru/8.2/data/chart', 'd5p1'),
    'SettingsComposer': ('http://v8.1c.ru/8.1/data-composition-system/settings', 'dcsset'),
    'SpreadsheetDocument': ('http://v8.1c.ru/8.2/data/spreadsheet', 'mxl'),
}
# current-config (cfg:, declared at the root): bare types and object types.
# Reference types (*Ref.X / DefinedType.X) go through a local d5p1 instead.
CFG_BARE_TYPES = ('ConstantsSet', 'ReportBuilder', 'FilterCriterion')
CFG_OBJECT_KINDS = ('Catalog', 'Document', 'Enum', 'ChartOfAccounts', 'ChartOfCharacteristicTypes',
                    'ChartOfCalculationTypes', 'ExchangePlan', 'BusinessProcess', 'Task',
                    'InformationRegister', 'AccumulationRegister', 'AccountingRegister',
                    'CalculationRegister', 'DataProcessor', 'Report', 'DocumentJournal',
                    'Constant', 'ConstantValue', 'Sequence', 'Recalculation')
REF_KIND_RE = (r'^(CatalogRef|DocumentRef|EnumRef|ChartOfAccountsRef|ChartOfCharacteristicTypesRef|'
               r'ChartOfCalculationTypesRef|ExchangePlanRef|BusinessProcessRef|'
               r'BusinessProcessRoutePointRef|TaskRef)')


def emit_type_content(indent, type_str):
    if not type_str:
        return
    # Composite type: "Type1 + Type2 + Type3"
    if ' + ' in type_str:
        for part in [p.strip() for p in type_str.split('+')]:
            emit_type_content(indent, part)
        return
    type_str = resolve_type_str(type_str)

    if type_str == 'Boolean':
        X(f'{indent}<v8:Type>xs:boolean</v8:Type>')
        return

    # String / String(N) / String(N,fixed|variable)
    m = re.match(r'^String(\((\d+)(\s*,\s*(fixed|variable))?\))?$', type_str)
    if m:
        length = m.group(2) if m.group(2) else '10'
        allowed = 'Fixed' if (m.group(4) and m.group(4).lower() == 'fixed') else 'Variable'
        X(f'{indent}<v8:Type>xs:string</v8:Type>')
        X(f'{indent}<v8:StringQualifiers>')
        X(f'{indent}\t<v8:Length>{length}</v8:Length>')
        X(f'{indent}\t<v8:AllowedLength>{allowed}</v8:AllowedLength>')
        X(f'{indent}</v8:StringQualifiers>')
        return

    if type_str == 'Number':
        X(f'{indent}<v8:Type>xs:decimal</v8:Type>')
        X(f'{indent}<v8:NumberQualifiers>')
        X(f'{indent}\t<v8:Digits>10</v8:Digits>')
        X(f'{indent}\t<v8:FractionDigits>0</v8:FractionDigits>')
        X(f'{indent}\t<v8:AllowedSign>Any</v8:AllowedSign>')
        X(f'{indent}</v8:NumberQualifiers>')
        return

    m = re.match(r'^Number\((\d+),(\d+)(,nonneg)?\)$', type_str)
    if m:
        sign = 'Nonnegative' if m.group(3) else 'Any'
        X(f'{indent}<v8:Type>xs:decimal</v8:Type>')
        X(f'{indent}<v8:NumberQualifiers>')
        X(f'{indent}\t<v8:Digits>{m.group(1)}</v8:Digits>')
        X(f'{indent}\t<v8:FractionDigits>{m.group(2)}</v8:FractionDigits>')
        X(f'{indent}\t<v8:AllowedSign>{sign}</v8:AllowedSign>')
        X(f'{indent}</v8:NumberQualifiers>')
        return

    # Date / DateTime / Time share one shape and differ only in DateFractions
    if re.match(r'^(Date|DateTime|Time)$', type_str):
        X(f'{indent}<v8:Type>xs:dateTime</v8:Type>')
        X(f'{indent}<v8:DateQualifiers>')
        X(f'{indent}\t<v8:DateFractions>{type_str}</v8:DateFractions>')
        X(f'{indent}</v8:DateQualifiers>')
        return

    # TypeSet: a defined type, or a characteristic of a ChartOfCharacteristicTypes
    if re.match(r'^(DefinedType|Characteristic)\.(.+)$', type_str):
        X(f'{indent}<v8:TypeSet>cfg:{type_str}</v8:TypeSet>')
        return
    # A bare metatype category (CatalogRef / ... / AnyRef with no object name) is
    # the set "any object of this category" -> TypeSet, not a named Type.
    if re.match(REF_KIND_RE + r'$', type_str) or type_str in ('AnyRef', 'AnyIBRef'):
        X(f'{indent}<v8:TypeSet>cfg:{type_str}</v8:TypeSet>')
        return

    # ValueStorage is canonically v8:ValueStorage (1C also accepts xs:base64Binary)
    if type_str == 'ValueStorage':
        X(f'{indent}<v8:Type>v8:ValueStorage</v8:Type>')
        return
    if type_str == 'UUID':
        X(f'{indent}<v8:Type>v8:UUID</v8:Type>')
        return
    if type_str in V8_PLATFORM_TYPES:
        X(f'{indent}<v8:Type>v8:{type_str}</v8:Type>')
        return
    if type_str in TYPE_NAMESPACE_MAP:
        ns, prefix = TYPE_NAMESPACE_MAP[type_str]
        X(f'{indent}<v8:Type xmlns:{prefix}="{ns}">{prefix}:{type_str}</v8:Type>')
        return

    if type_str in CFG_BARE_TYPES:
        X(f'{indent}<v8:Type>cfg:{type_str}</v8:Type>')
        return
    m = re.match(r'^(\w+?)(Object|List|Manager|Selection|RecordSet|RecordKey|RecordManager)\.(.+)$', type_str)
    if m and m.group(1) in CFG_OBJECT_KINDS:
        X(f'{indent}<v8:Type>cfg:{type_str}</v8:Type>')
        return
    # A bare object metatype (no name) — e.g. in an event subscription's Source:
    #   Object / RecordSet -> "any object of the category" = TypeSet
    #   Manager / List / Selection / RecordKey / RecordManager -> the manager or
    #   list type itself = a single Type.
    # ConstantValueManager is the exception: a set of constant value managers.
    m = re.match(r'^(\w+?)(Object|RecordSet)$', type_str)
    if (m and m.group(1) in CFG_OBJECT_KINDS) or type_str == 'ConstantValueManager':
        X(f'{indent}<v8:TypeSet>cfg:{type_str}</v8:TypeSet>')
        return
    m = re.match(r'^(\w+?)(Manager|List|Selection|RecordKey|RecordManager)$', type_str)
    if m and m.group(1) in CFG_OBJECT_KINDS:
        X(f'{indent}<v8:Type>cfg:{type_str}</v8:Type>')
        return

    # Reference types — a local xmlns declaration, for 1C compatibility
    if re.match(REF_KIND_RE + r'\.(.+)$', type_str):
        X(f'{indent}<v8:Type xmlns:d5p1="http://v8.1c.ru/8.1/data/enterprise/current-config">'
          f'd5p1:{type_str}</v8:Type>')
        return

    X(f'{indent}<v8:Type>{type_str}</v8:Type>')


def emit_value_type(indent, type_str):
    X(f'{indent}<Type>')
    emit_type_content(f'{indent}\t', type_str)
    X(f'{indent}</Type>')

def emit_fill_value(indent, type_str):
    if not type_str:
        X(f'{indent}<FillValue xsi:nil="true"/>')
        return
    type_str = resolve_type_str(type_str)
    if type_str == 'Boolean':
        X(f'{indent}<FillValue xsi:type="xs:boolean">false</FillValue>')
        return
    if re.match(r'^String', type_str):
        X(f'{indent}<FillValue xsi:type="xs:string"/>')
        return
    if re.match(r'^Number', type_str):
        X(f'{indent}<FillValue xsi:type="xs:decimal">0</FillValue>')
        return
    if re.match(r'^(Date|DateTime)$', type_str):
        X(f'{indent}<FillValue xsi:nil="true"/>')
        return
    X(f'{indent}<FillValue xsi:nil="true"/>')

# ---------------------------------------------------------------------------
# 5. Attribute shorthand parser
# ---------------------------------------------------------------------------

def build_type_str(obj):
    t = str(obj.get('valueType') or obj.get('type') or '')
    if t and '(' not in t:
        if t == 'String' and obj.get('length'):
            t = f"String({obj['length']})"
        elif t == 'Number' and obj.get('length'):
            prec = obj.get('precision', 0)
            nn = ',nonneg' if obj.get('nonneg') or obj.get('nonnegative') else ''
            t = f"Number({obj['length']},{prec}{nn})"
    return t

def parse_attribute_shorthand(val):
    if isinstance(val, str):
        parsed = {
            'name': '',
            'type': '',
            'synonym': '',
            'comment': '',
            'flags': [],
            'fillChecking': '',
            'indexing': '',
        }
        parts = val.split('|', 1)
        main_part = parts[0].strip()
        if len(parts) > 1:
            flag_str = parts[1].strip()
            parsed['flags'] = [f.strip().lower() for f in flag_str.split(',') if f.strip()]
        colon_parts = main_part.split(':', 1)
        parsed['name'] = colon_parts[0].strip()
        if len(colon_parts) > 1:
            parsed['type'] = colon_parts[1].strip()
        parsed['synonym'] = split_camel_case(parsed['name'])
        return parsed
    # Object form
    name = str(val.get('name', ''))
    return {
        'name': name,
        'type': build_type_str(val),
        'synonym': str(val['synonym']) if val.get('synonym') else split_camel_case(name),
        'comment': str(val['comment']) if val.get('comment') else '',
        'flags': list(val.get('flags', [])),
        'fillChecking': str(val['fillChecking']) if val.get('fillChecking') else '',
        'indexing': str(val['indexing']) if val.get('indexing') else '',
        'multiLine': True if val.get('multiLine') is True else False,
        'choiceHistoryOnInput': str(val['choiceHistoryOnInput']) if val.get('choiceHistoryOnInput') else '',
    }

def parse_enum_value_shorthand(val):
    if isinstance(val, str):
        return {
            'name': val,
            'synonym': split_camel_case(val),
            'comment': '',
        }
    name = str(val.get('name', ''))
    return {
        'name': name,
        'synonym': str(val['synonym']) if val.get('synonym') else split_camel_case(name),
        'comment': str(val['comment']) if val.get('comment') else '',
    }

# ---------------------------------------------------------------------------
# 6. GeneratedType categories
# ---------------------------------------------------------------------------

generated_types = {
    'Sequence': [
        {'prefix': 'SequenceRecord', 'category': 'Record'},
        {'prefix': 'SequenceManager', 'category': 'Manager'},
        {'prefix': 'SequenceRecordSet', 'category': 'RecordSet'},
    ],
    'FilterCriterion': [
        {'prefix': 'FilterCriterionManager', 'category': 'Manager'},
        {'prefix': 'FilterCriterionList', 'category': 'List'},
    ],
    'SettingsStorage': [
        {'prefix': 'SettingsStorageManager', 'category': 'Manager'},
    ],
    'WSReference': [
        {'prefix': 'WSReferenceManager', 'category': 'Manager'},
    ],
    'Catalog': [
        {'prefix': 'CatalogObject', 'category': 'Object'},
        {'prefix': 'CatalogRef', 'category': 'Ref'},
        {'prefix': 'CatalogSelection', 'category': 'Selection'},
        {'prefix': 'CatalogList', 'category': 'List'},
        {'prefix': 'CatalogManager', 'category': 'Manager'},
    ],
    'Document': [
        {'prefix': 'DocumentObject', 'category': 'Object'},
        {'prefix': 'DocumentRef', 'category': 'Ref'},
        {'prefix': 'DocumentSelection', 'category': 'Selection'},
        {'prefix': 'DocumentList', 'category': 'List'},
        {'prefix': 'DocumentManager', 'category': 'Manager'},
    ],
    'Enum': [
        {'prefix': 'EnumRef', 'category': 'Ref'},
        {'prefix': 'EnumManager', 'category': 'Manager'},
        {'prefix': 'EnumList', 'category': 'List'},
    ],
    'Constant': [
        {'prefix': 'ConstantManager', 'category': 'Manager'},
        {'prefix': 'ConstantValueManager', 'category': 'ValueManager'},
        {'prefix': 'ConstantValueKey', 'category': 'ValueKey'},
    ],
    'InformationRegister': [
        {'prefix': 'InformationRegisterRecord', 'category': 'Record'},
        {'prefix': 'InformationRegisterManager', 'category': 'Manager'},
        {'prefix': 'InformationRegisterSelection', 'category': 'Selection'},
        {'prefix': 'InformationRegisterList', 'category': 'List'},
        {'prefix': 'InformationRegisterRecordSet', 'category': 'RecordSet'},
        {'prefix': 'InformationRegisterRecordKey', 'category': 'RecordKey'},
        {'prefix': 'InformationRegisterRecordManager', 'category': 'RecordManager'},
    ],
    'AccumulationRegister': [
        {'prefix': 'AccumulationRegisterRecord', 'category': 'Record'},
        {'prefix': 'AccumulationRegisterManager', 'category': 'Manager'},
        {'prefix': 'AccumulationRegisterSelection', 'category': 'Selection'},
        {'prefix': 'AccumulationRegisterList', 'category': 'List'},
        {'prefix': 'AccumulationRegisterRecordSet', 'category': 'RecordSet'},
        {'prefix': 'AccumulationRegisterRecordKey', 'category': 'RecordKey'},
    ],
    'AccountingRegister': [
        {'prefix': 'AccountingRegisterRecord', 'category': 'Record'},
        {'prefix': 'AccountingRegisterExtDimensions', 'category': 'ExtDimensions'},
        {'prefix': 'AccountingRegisterRecordSet', 'category': 'RecordSet'},
        {'prefix': 'AccountingRegisterRecordKey', 'category': 'RecordKey'},
        {'prefix': 'AccountingRegisterSelection', 'category': 'Selection'},
        {'prefix': 'AccountingRegisterList', 'category': 'List'},
        {'prefix': 'AccountingRegisterManager', 'category': 'Manager'},
    ],
    'CalculationRegister': [
        {'prefix': 'CalculationRegisterRecord', 'category': 'Record'},
        {'prefix': 'CalculationRegisterManager', 'category': 'Manager'},
        {'prefix': 'CalculationRegisterSelection', 'category': 'Selection'},
        {'prefix': 'CalculationRegisterList', 'category': 'List'},
        {'prefix': 'CalculationRegisterRecordSet', 'category': 'RecordSet'},
        {'prefix': 'CalculationRegisterRecordKey', 'category': 'RecordKey'},
        {'prefix': 'RecalculationsManager', 'category': 'Recalcs'},
    ],
    'ChartOfAccounts': [
        {'prefix': 'ChartOfAccountsObject', 'category': 'Object'},
        {'prefix': 'ChartOfAccountsRef', 'category': 'Ref'},
        {'prefix': 'ChartOfAccountsSelection', 'category': 'Selection'},
        {'prefix': 'ChartOfAccountsList', 'category': 'List'},
        {'prefix': 'ChartOfAccountsManager', 'category': 'Manager'},
        {'prefix': 'ChartOfAccountsExtDimensionTypes', 'category': 'ExtDimensionTypes'},
        {'prefix': 'ChartOfAccountsExtDimensionTypesRow', 'category': 'ExtDimensionTypesRow'},
    ],
    'ChartOfCharacteristicTypes': [
        {'prefix': 'ChartOfCharacteristicTypesObject', 'category': 'Object'},
        {'prefix': 'ChartOfCharacteristicTypesRef', 'category': 'Ref'},
        {'prefix': 'ChartOfCharacteristicTypesSelection', 'category': 'Selection'},
        {'prefix': 'ChartOfCharacteristicTypesList', 'category': 'List'},
        {'prefix': 'ChartOfCharacteristicTypesCharacteristic', 'category': 'Characteristic'},
        {'prefix': 'ChartOfCharacteristicTypesManager', 'category': 'Manager'},
    ],
    'ChartOfCalculationTypes': [
        {'prefix': 'ChartOfCalculationTypesObject', 'category': 'Object'},
        {'prefix': 'ChartOfCalculationTypesRef', 'category': 'Ref'},
        {'prefix': 'ChartOfCalculationTypesSelection', 'category': 'Selection'},
        {'prefix': 'ChartOfCalculationTypesList', 'category': 'List'},
        {'prefix': 'ChartOfCalculationTypesManager', 'category': 'Manager'},
        {'prefix': 'DisplacingCalculationTypes', 'category': 'DisplacingCalculationTypes'},
        {'prefix': 'DisplacingCalculationTypesRow', 'category': 'DisplacingCalculationTypesRow'},
        {'prefix': 'BaseCalculationTypes', 'category': 'BaseCalculationTypes'},
        {'prefix': 'BaseCalculationTypesRow', 'category': 'BaseCalculationTypesRow'},
        {'prefix': 'LeadingCalculationTypes', 'category': 'LeadingCalculationTypes'},
        {'prefix': 'LeadingCalculationTypesRow', 'category': 'LeadingCalculationTypesRow'},
    ],
    'BusinessProcess': [
        {'prefix': 'BusinessProcessObject', 'category': 'Object'},
        {'prefix': 'BusinessProcessRef', 'category': 'Ref'},
        {'prefix': 'BusinessProcessSelection', 'category': 'Selection'},
        {'prefix': 'BusinessProcessList', 'category': 'List'},
        {'prefix': 'BusinessProcessManager', 'category': 'Manager'},
        {'prefix': 'BusinessProcessRoutePointRef', 'category': 'RoutePointRef'},
    ],
    'Task': [
        {'prefix': 'TaskObject', 'category': 'Object'},
        {'prefix': 'TaskRef', 'category': 'Ref'},
        {'prefix': 'TaskSelection', 'category': 'Selection'},
        {'prefix': 'TaskList', 'category': 'List'},
        {'prefix': 'TaskManager', 'category': 'Manager'},
    ],
    'ExchangePlan': [
        {'prefix': 'ExchangePlanObject', 'category': 'Object'},
        {'prefix': 'ExchangePlanRef', 'category': 'Ref'},
        {'prefix': 'ExchangePlanSelection', 'category': 'Selection'},
        {'prefix': 'ExchangePlanList', 'category': 'List'},
        {'prefix': 'ExchangePlanManager', 'category': 'Manager'},
    ],
    'DefinedType': [
        {'prefix': 'DefinedType', 'category': 'DefinedType'},
    ],
    'DocumentJournal': [
        {'prefix': 'DocumentJournalSelection', 'category': 'Selection'},
        {'prefix': 'DocumentJournalList', 'category': 'List'},
        {'prefix': 'DocumentJournalManager', 'category': 'Manager'},
    ],
    'Report': [
        {'prefix': 'ReportObject', 'category': 'Object'},
        {'prefix': 'ReportManager', 'category': 'Manager'},
    ],
    'DataProcessor': [
        {'prefix': 'DataProcessorObject', 'category': 'Object'},
        {'prefix': 'DataProcessorManager', 'category': 'Manager'},
    ],
}

def emit_internal_info(indent, object_type, object_name):
    types = generated_types.get(object_type)
    if not types:
        return
    X(f'{indent}<InternalInfo>')
    if object_type == 'ExchangePlan':
        X(f'{indent}\t<xr:ThisNode>{new_uuid()}</xr:ThisNode>')
    for gt in types:
        full_name = f"{gt['prefix']}.{object_name}"
        X(f'{indent}\t<xr:GeneratedType name="{full_name}" category="{gt["category"]}">')
        X(f'{indent}\t\t<xr:TypeId>{new_uuid()}</xr:TypeId>')
        X(f'{indent}\t\t<xr:ValueId>{new_uuid()}</xr:ValueId>')
        X(f'{indent}\t</xr:GeneratedType>')
    X(f'{indent}</InternalInfo>')

# ---------------------------------------------------------------------------
# 7. StandardAttributes
# ---------------------------------------------------------------------------

standard_attributes_by_type = {
    'Catalog': ['PredefinedDataName', 'Predefined', 'Ref', 'DeletionMark', 'IsFolder', 'Owner', 'Parent', 'Description', 'Code'],
    'Document': ['Posted', 'Ref', 'DeletionMark', 'Date', 'Number'],
    'Enum': ['Order', 'Ref'],
    'InformationRegister': ['Active', 'LineNumber', 'Recorder', 'Period'],
    'AccumulationRegister': ['Active', 'LineNumber', 'Recorder', 'Period'],
    'AccountingRegister': ['Active', 'Period', 'Recorder', 'LineNumber', 'Account'],
    'CalculationRegister': ['Active', 'Recorder', 'LineNumber', 'RegistrationPeriod', 'CalculationType', 'ReversingEntry'],
    'ChartOfAccounts': ['PredefinedDataName', 'Predefined', 'Ref', 'DeletionMark', 'Description', 'Code', 'Parent', 'Order', 'Type', 'OffBalance'],
    'ChartOfCharacteristicTypes': ['PredefinedDataName', 'Predefined', 'Ref', 'DeletionMark', 'Description', 'Code', 'Parent', 'ValueType'],
    'ChartOfCalculationTypes': ['PredefinedDataName', 'Predefined', 'Ref', 'DeletionMark', 'Description', 'Code', 'ActionPeriodIsBasic'],
    'BusinessProcess': ['Ref', 'DeletionMark', 'Date', 'Number', 'Started', 'Completed', 'HeadTask'],
    'Task': ['Ref', 'DeletionMark', 'Date', 'Number', 'Executed', 'Description', 'RoutePoint', 'BusinessProcess'],
    'ExchangePlan': ['Ref', 'DeletionMark', 'Code', 'Description', 'ThisNode', 'SentNo', 'ReceivedNo'],
    'DocumentJournal': ['Type', 'Ref', 'Date', 'Posted', 'DeletionMark', 'Number'],
}

def emit_standard_attribute(indent, attr_name, ov=None):
    """A standard attribute. `ov` overrides individual properties — used e.g.
    for ExtDimensionType (FillChecking=ShowError) and for the ExtDimensionN ->
    Account link on an accounting register."""
    def ov_or(key, default):
        if ov and key in ov:
            return ov[key]
        return default

    fc = ov_or('FillChecking', 'DontCheck')
    ffv = ov_or('FillFromFillingValue', 'false')
    dh = ov_or('DataHistory', 'Use')
    fts = ov_or('FullTextSearch', 'Use')
    syn = ov_or('Synonym', '')
    tt = ov_or('ToolTip', '')
    cf = ov_or('ChoiceForm', '')
    cmt = ov_or('Comment', '')
    msk = ov_or('Mask', '')
    fmt = ov_or('Format', None)
    efmt = ov_or('EditFormat', None)
    chi = ov_or('ChoiceHistoryOnInput', 'Auto')

    X(f'{indent}<xr:StandardAttribute name="{attr_name}">')
    # LinkByType of a standard attribute (e.g. ExtDimensionN -> Account on an
    # accounting register). DataPath is emitted verbatim (already a full path).
    lbt = ov_or('LinkByType', None)
    if lbt:
        lbt_dp = str(lbt.get('dataPath')) if isinstance(lbt, dict) and lbt.get('dataPath') else str(lbt)
        lbt_li = lbt.get('linkItem', 0) if isinstance(lbt, dict) else 0
        X(f'{indent}\t<xr:LinkByType>')
        X(f'{indent}\t\t<xr:DataPath>{esc_xml(lbt_dp)}</xr:DataPath>')
        X(f'{indent}\t\t<xr:LinkItem>{lbt_li}</xr:LinkItem>')
        X(f'{indent}\t</xr:LinkByType>')
    else:
        X(f'{indent}\t<xr:LinkByType/>')
    X(f'{indent}\t<xr:FillChecking>{fc}</xr:FillChecking>')
    X(f'{indent}\t<xr:MultiLine>false</xr:MultiLine>')
    X(f'{indent}\t<xr:FillFromFillingValue>{ffv}</xr:FillFromFillingValue>')
    X(f'{indent}\t<xr:CreateOnInput>Auto</xr:CreateOnInput>')
    # Format 2.20 (8.3.27): the platform writes a type-reduction mode on EVERY
    # standard attribute; always TransformValues except Owner, which is Deny.
    if is_format_220:
        trm = ov_or('TypeReductionMode', 'Deny' if attr_name == 'Owner' else 'TransformValues')
        X(f'{indent}\t<xr:TypeReductionMode>{trm}</xr:TypeReductionMode>')
    X(f'{indent}\t<xr:MaxValue xsi:nil="true"/>')
    if tt:
        emit_mltext(f'{indent}\t', 'xr:ToolTip', tt)
    else:
        X(f'{indent}\t<xr:ToolTip/>')
    X(f'{indent}\t<xr:ExtendedEdit>false</xr:ExtendedEdit>')
    if fmt:
        emit_mltext(f'{indent}\t', 'xr:Format', fmt)
    else:
        X(f'{indent}\t<xr:Format/>')
    if cf:
        X(f'{indent}\t<xr:ChoiceForm>{esc_xml(str(cf))}</xr:ChoiceForm>')
    else:
        X(f'{indent}\t<xr:ChoiceForm/>')
    X(f'{indent}\t<xr:QuickChoice>Auto</xr:QuickChoice>')
    X(f'{indent}\t<xr:ChoiceHistoryOnInput>{chi}</xr:ChoiceHistoryOnInput>')
    if efmt:
        emit_mltext(f'{indent}\t', 'xr:EditFormat', efmt)
    else:
        X(f'{indent}\t<xr:EditFormat/>')
    X(f'{indent}\t<xr:PasswordMode>false</xr:PasswordMode>')
    X(f'{indent}\t<xr:DataHistory>{dh}</xr:DataHistory>')
    X(f'{indent}\t<xr:MarkNegatives>false</xr:MarkNegatives>')
    X(f'{indent}\t<xr:MinValue xsi:nil="true"/>')
    if syn:
        emit_mltext(f'{indent}\t', 'xr:Synonym', syn)
    else:
        X(f'{indent}\t<xr:Synonym/>')
    if cmt:
        X(f'{indent}\t<xr:Comment>{meta_dsl.esc_xml_text(cmt)}</xr:Comment>')
    else:
        X(f'{indent}\t<xr:Comment/>')
    X(f'{indent}\t<xr:FullTextSearch>{fts}</xr:FullTextSearch>')
    X(f'{indent}\t<xr:ChoiceParameterLinks/>')
    X(f'{indent}\t<xr:FillValue xsi:nil="true"/>')
    if msk:
        X(f'{indent}\t<xr:Mask>{meta_dsl.esc_xml_text(msk)}</xr:Mask>')
    else:
        X(f'{indent}\t<xr:Mask/>')
    X(f'{indent}\t<xr:ChoiceParameters/>')
    X(f'{indent}</xr:StandardAttribute>')


def resolve_type_prefix_syn(ref):
    """Forgiving metadata-object reference: resolve only the type prefix
    (ПланВидовХарактеристик.X -> ChartOfCharacteristicTypes.X)."""
    if ref and '.' in ref:
        d = ref.index('.')
        prefix, suffix = ref[:d], ref[d + 1:]
        prefix = object_type_synonyms.get(prefix, prefix)
        return f'{prefix}.{suffix}'
    return ref


def emit_standard_attributes(indent, object_type):
    attrs = standard_attributes_by_type.get(object_type)
    if not attrs:
        return
    X(f'{indent}<StandardAttributes>')
    for a in attrs:
        emit_standard_attribute(f'{indent}\t', a)
    X(f'{indent}</StandardAttributes>')

def emit_tabular_standard_attributes(indent):
    X(f'{indent}<StandardAttributes>')
    emit_standard_attribute(f'{indent}\t', 'LineNumber')
    X(f'{indent}</StandardAttributes>')

# ---------------------------------------------------------------------------
# 8. Attribute emitter
# ---------------------------------------------------------------------------

RESERVED_ATTR_NAMES = {
    'Ref', 'DeletionMark', 'Code', 'Description', 'Date', 'Number', 'Posted',
    'Parent', 'Owner', 'IsFolder', 'Predefined', 'PredefinedDataName',
    'Recorder', 'Period', 'LineNumber', 'Active', 'Order', 'Type', 'OffBalance',
    'Started', 'Completed', 'HeadTask', 'Executed', 'RoutePoint', 'BusinessProcess',
    'ThisNode', 'SentNo', 'ReceivedNo', 'CalculationType', 'RegistrationPeriod',
    'ReversingEntry', 'Account', 'ValueType', 'ActionPeriodIsBasic',
}
RESERVED_ATTR_NAMES_RU = {
    '\u0421\u0441\u044b\u043b\u043a\u0430', '\u041f\u043e\u043c\u0435\u0442\u043a\u0430\u0423\u0434\u0430\u043b\u0435\u043d\u0438\u044f',
    '\u041a\u043e\u0434', '\u041d\u0430\u0438\u043c\u0435\u043d\u043e\u0432\u0430\u043d\u0438\u0435',
    '\u0414\u0430\u0442\u0430', '\u041d\u043e\u043c\u0435\u0440', '\u041f\u0440\u043e\u0432\u0435\u0434\u0435\u043d',
    '\u0420\u043e\u0434\u0438\u0442\u0435\u043b\u044c', '\u0412\u043b\u0430\u0434\u0435\u043b\u0435\u0446',
    '\u042d\u0442\u043e\u0413\u0440\u0443\u043f\u043f\u0430', '\u041f\u0440\u0435\u0434\u043e\u043f\u0440\u0435\u0434\u0435\u043b\u0435\u043d\u043d\u044b\u0439',
    '\u0418\u043c\u044f\u041f\u0440\u0435\u0434\u043e\u043f\u0440\u0435\u0434\u0435\u043b\u0435\u043d\u043d\u044b\u0445\u0414\u0430\u043d\u043d\u044b\u0445',
    '\u0420\u0435\u0433\u0438\u0441\u0442\u0440\u0430\u0442\u043e\u0440', '\u041f\u0435\u0440\u0438\u043e\u0434',
    '\u041d\u043e\u043c\u0435\u0440\u0421\u0442\u0440\u043e\u043a\u0438', '\u0410\u043a\u0442\u0438\u0432\u043d\u043e\u0441\u0442\u044c',
    '\u041f\u043e\u0440\u044f\u0434\u043e\u043a', '\u0422\u0438\u043f', '\u0417\u0430\u0431\u0430\u043b\u0430\u043d\u0441\u043e\u0432\u044b\u0439',
    '\u0421\u0442\u0430\u0440\u0442\u043e\u0432\u0430\u043d', '\u0417\u0430\u0432\u0435\u0440\u0448\u0435\u043d',
    '\u0412\u0435\u0434\u0443\u0449\u0430\u044f\u0417\u0430\u0434\u0430\u0447\u0430',
    '\u0412\u044b\u043f\u043e\u043b\u043d\u0435\u043d\u0430', '\u0422\u043e\u0447\u043a\u0430\u041c\u0430\u0440\u0448\u0440\u0443\u0442\u0430',
    '\u0411\u0438\u0437\u043d\u0435\u0441\u041f\u0440\u043e\u0446\u0435\u0441\u0441',
    '\u042d\u0442\u043e\u0442\u0423\u0437\u0435\u043b', '\u041d\u043e\u043c\u0435\u0440\u041e\u0442\u043f\u0440\u0430\u0432\u043b\u0435\u043d\u043d\u043e\u0433\u043e',
    '\u041d\u043e\u043c\u0435\u0440\u041f\u0440\u0438\u043d\u044f\u0442\u043e\u0433\u043e',
    '\u0412\u0438\u0434\u0420\u0430\u0441\u0447\u0435\u0442\u0430', '\u041f\u0435\u0440\u0438\u043e\u0434\u0420\u0435\u0433\u0438\u0441\u0442\u0440\u0430\u0446\u0438\u0438',
    '\u0421\u0442\u043e\u0440\u043d\u043e\u0417\u0430\u043f\u0438\u0441\u044c',
    '\u0421\u0447\u0435\u0442', '\u0422\u0438\u043f\u0417\u043d\u0430\u0447\u0435\u043d\u0438\u044f',
    '\u041f\u0435\u0440\u0438\u043e\u0434\u0414\u0435\u0439\u0441\u0442\u0432\u0438\u044f\u0411\u0430\u0437\u043e\u0432\u044b\u0439',
}

def emit_attribute(indent, parsed, context):
    attr_name = parsed['name']
    if context not in ('tabular', 'processor-tabular') and (attr_name in RESERVED_ATTR_NAMES or attr_name in RESERVED_ATTR_NAMES_RU):
        print(f"WARNING: Attribute '{attr_name}' conflicts with a standard attribute name. This may cause errors when loading into 1C.", file=sys.stderr)
    uid = new_uuid()
    X(f'{indent}<Attribute uuid="{uid}">')
    X(f'{indent}\t<Properties>')
    X(f'{indent}\t\t<Name>{esc_xml(parsed["name"])}</Name>')
    emit_mltext(f'{indent}\t\t', 'Synonym', parsed['synonym'])
    X(f'{indent}\t\t<Comment/>')
    type_str = parsed['type']
    if type_str:
        emit_value_type(f'{indent}\t\t', type_str)
    else:
        X(f'{indent}\t\t<Type>')
        X(f'{indent}\t\t\t<v8:Type>xs:string</v8:Type>')
        X(f'{indent}\t\t</Type>')
    X(f'{indent}\t\t<PasswordMode>false</PasswordMode>')
    X(f'{indent}\t\t<Format/>')
    X(f'{indent}\t\t<EditFormat/>')
    X(f'{indent}\t\t<ToolTip/>')
    X(f'{indent}\t\t<MarkNegatives>false</MarkNegatives>')
    X(f'{indent}\t\t<Mask/>')
    multi_line = 'true' if (parsed.get('multiLine') is True or 'multiline' in parsed.get('flags', [])) else 'false'
    X(f'{indent}\t\t<MultiLine>{multi_line}</MultiLine>')
    X(f'{indent}\t\t<ExtendedEdit>false</ExtendedEdit>')
    X(f'{indent}\t\t<MinValue xsi:nil="true"/>')
    X(f'{indent}\t\t<MaxValue xsi:nil="true"/>')
    # FillFromFillingValue / FillValue — not for tabular/processor/chart/register-other
    # (Chart*, AccumulationRegister/AccountingRegister/CalculationRegister don't support these)
    if context not in ('tabular', 'processor', 'chart', 'register-other'):
        X(f'{indent}\t\t<FillFromFillingValue>false</FillFromFillingValue>')
    if context not in ('tabular', 'processor', 'chart', 'register-other'):
        emit_fill_value(f'{indent}\t\t', type_str)
    fill_checking = 'DontCheck'
    if 'req' in parsed.get('flags', []):
        fill_checking = 'ShowError'
    if parsed.get('fillChecking'):
        fill_checking = parsed['fillChecking']
    X(f'{indent}\t\t<FillChecking>{fill_checking}</FillChecking>')
    X(f'{indent}\t\t<ChoiceFoldersAndItems>Items</ChoiceFoldersAndItems>')
    X(f'{indent}\t\t<ChoiceParameterLinks/>')
    X(f'{indent}\t\t<ChoiceParameters/>')
    X(f'{indent}\t\t<QuickChoice>Auto</QuickChoice>')
    X(f'{indent}\t\t<CreateOnInput>Auto</CreateOnInput>')
    X(f'{indent}\t\t<ChoiceForm/>')
    X(f'{indent}\t\t<LinkByType/>')
    chi = parsed.get('choiceHistoryOnInput') or 'Auto'
    X(f'{indent}\t\t<ChoiceHistoryOnInput>{chi}</ChoiceHistoryOnInput>')
    if context == 'catalog':
        X(f'{indent}\t\t<Use>ForItem</Use>')
    if context not in ('processor', 'processor-tabular'):
        indexing = 'DontIndex'
        if 'index' in parsed.get('flags', []):
            indexing = 'Index'
        if 'indexadditional' in parsed.get('flags', []):
            indexing = 'IndexWithAdditionalOrder'
        if parsed.get('indexing'):
            indexing = parsed['indexing']
        X(f'{indent}\t\t<Indexing>{indexing}</Indexing>')
        X(f'{indent}\t\t<FullTextSearch>Use</FullTextSearch>')
        # DataHistory — not for Chart* types and non-InformationRegister register family
        if context not in ('chart', 'register-other'):
            X(f'{indent}\t\t<DataHistory>Use</DataHistory>')
    X(f'{indent}\t</Properties>')
    X(f'{indent}</Attribute>')

# ---------------------------------------------------------------------------
# 9. TabularSection emitter
# ---------------------------------------------------------------------------

def emit_tabular_section(indent, ts_name, columns, object_type, object_name):
    uid = new_uuid()
    X(f'{indent}<TabularSection uuid="{uid}">')
    type_prefix = f'{object_type}TabularSection'
    row_prefix = f'{object_type}TabularSectionRow'
    X(f'{indent}\t<InternalInfo>')
    X(f'{indent}\t\t<xr:GeneratedType name="{type_prefix}.{object_name}.{ts_name}" category="TabularSection">')
    X(f'{indent}\t\t\t<xr:TypeId>{new_uuid()}</xr:TypeId>')
    X(f'{indent}\t\t\t<xr:ValueId>{new_uuid()}</xr:ValueId>')
    X(f'{indent}\t\t</xr:GeneratedType>')
    X(f'{indent}\t\t<xr:GeneratedType name="{row_prefix}.{object_name}.{ts_name}" category="TabularSectionRow">')
    X(f'{indent}\t\t\t<xr:TypeId>{new_uuid()}</xr:TypeId>')
    X(f'{indent}\t\t\t<xr:ValueId>{new_uuid()}</xr:ValueId>')
    X(f'{indent}\t\t</xr:GeneratedType>')
    X(f'{indent}\t</InternalInfo>')
    ts_synonym = split_camel_case(ts_name)
    X(f'{indent}\t<Properties>')
    X(f'{indent}\t\t<Name>{esc_xml(ts_name)}</Name>')
    emit_mltext(f'{indent}\t\t', 'Synonym', ts_synonym)
    X(f'{indent}\t\t<Comment/>')
    X(f'{indent}\t\t<ToolTip/>')
    X(f'{indent}\t\t<FillChecking>DontCheck</FillChecking>')
    emit_tabular_standard_attributes(f'{indent}\t\t')
    if object_type == 'Catalog':
        X(f'{indent}\t\t<Use>ForItem</Use>')
    # Format 2.20 (8.3.27): row-number length (5..9 -> up to 999 999 999 rows
    # instead of 99 999). Last in Properties; the default follows the
    # compatibility mode in force when the tabular section was created.
    if is_format_220:
        X(f'{indent}\t\t<LineNumberLength>{line_number_length_default}</LineNumberLength>')
    X(f'{indent}\t</Properties>')
    ts_context = 'processor-tabular' if object_type in ('DataProcessor', 'Report') else 'tabular'
    X(f'{indent}\t<ChildObjects>')
    for col in columns:
        parsed = parse_attribute_shorthand(col)
        emit_attribute(f'{indent}\t\t', parsed, ts_context)
    X(f'{indent}\t</ChildObjects>')
    X(f'{indent}</TabularSection>')

# ---------------------------------------------------------------------------
# 10. EnumValue emitter
# ---------------------------------------------------------------------------

def emit_enum_value(indent, parsed):
    uid = new_uuid()
    X(f'{indent}<EnumValue uuid="{uid}">')
    X(f'{indent}\t<Properties>')
    X(f'{indent}\t\t<Name>{esc_xml(parsed["name"])}</Name>')
    emit_mltext(f'{indent}\t\t', 'Synonym', parsed['synonym'])
    X(f'{indent}\t\t<Comment/>')
    X(f'{indent}\t</Properties>')
    X(f'{indent}</EnumValue>')

# ---------------------------------------------------------------------------
# 11. Dimension emitter
# ---------------------------------------------------------------------------

def emit_dimension(indent, parsed, register_type):
    uid = new_uuid()
    X(f'{indent}<Dimension uuid="{uid}">')
    X(f'{indent}\t<Properties>')
    X(f'{indent}\t\t<Name>{esc_xml(parsed["name"])}</Name>')
    emit_mltext(f'{indent}\t\t', 'Synonym', parsed['synonym'])
    X(f'{indent}\t\t<Comment/>')
    type_str = parsed['type']
    if type_str:
        emit_value_type(f'{indent}\t\t', type_str)
    else:
        X(f'{indent}\t\t<Type>')
        X(f'{indent}\t\t\t<v8:Type>xs:string</v8:Type>')
        X(f'{indent}\t\t</Type>')
    X(f'{indent}\t\t<PasswordMode>false</PasswordMode>')
    X(f'{indent}\t\t<Format/>')
    X(f'{indent}\t\t<EditFormat/>')
    X(f'{indent}\t\t<ToolTip/>')
    X(f'{indent}\t\t<MarkNegatives>false</MarkNegatives>')
    X(f'{indent}\t\t<Mask/>')
    multi_line = 'true' if (parsed.get('multiLine') is True or 'multiline' in parsed.get('flags', [])) else 'false'
    X(f'{indent}\t\t<MultiLine>{multi_line}</MultiLine>')
    X(f'{indent}\t\t<ExtendedEdit>false</ExtendedEdit>')
    X(f'{indent}\t\t<MinValue xsi:nil="true"/>')
    X(f'{indent}\t\t<MaxValue xsi:nil="true"/>')
    flags = parsed.get('flags', [])
    if register_type == 'InformationRegister':
        fill_from = 'true' if 'master' in flags else 'false'
        X(f'{indent}\t\t<FillFromFillingValue>{fill_from}</FillFromFillingValue>')
        X(f'{indent}\t\t<FillValue xsi:nil="true"/>')
    fill_checking = 'DontCheck'
    if 'req' in flags:
        fill_checking = 'ShowError'
    X(f'{indent}\t\t<FillChecking>{fill_checking}</FillChecking>')
    X(f'{indent}\t\t<ChoiceFoldersAndItems>Items</ChoiceFoldersAndItems>')
    X(f'{indent}\t\t<ChoiceParameterLinks/>')
    X(f'{indent}\t\t<ChoiceParameters/>')
    X(f'{indent}\t\t<QuickChoice>Auto</QuickChoice>')
    X(f'{indent}\t\t<CreateOnInput>Auto</CreateOnInput>')
    X(f'{indent}\t\t<ChoiceForm/>')
    X(f'{indent}\t\t<LinkByType/>')
    X(f'{indent}\t\t<ChoiceHistoryOnInput>Auto</ChoiceHistoryOnInput>')
    if register_type == 'InformationRegister':
        master = 'true' if 'master' in flags else 'false'
        main_filter = 'true' if 'mainfilter' in flags else 'false'
        deny_incomplete = 'true' if 'denyincomplete' in flags else 'false'
        X(f'{indent}\t\t<Master>{master}</Master>')
        X(f'{indent}\t\t<MainFilter>{main_filter}</MainFilter>')
        X(f'{indent}\t\t<DenyIncompleteValues>{deny_incomplete}</DenyIncompleteValues>')
    if register_type == 'AccumulationRegister':
        deny_incomplete = 'true' if 'denyincomplete' in flags else 'false'
        X(f'{indent}\t\t<DenyIncompleteValues>{deny_incomplete}</DenyIncompleteValues>')
    indexing = 'DontIndex'
    if 'index' in flags:
        indexing = 'Index'
    X(f'{indent}\t\t<Indexing>{indexing}</Indexing>')
    X(f'{indent}\t\t<FullTextSearch>Use</FullTextSearch>')
    if register_type == 'AccumulationRegister':
        use_in_totals = 'false' if 'nouseintotals' in flags else 'true'
        X(f'{indent}\t\t<UseInTotals>{use_in_totals}</UseInTotals>')
    if register_type == 'InformationRegister':
        X(f'{indent}\t\t<DataHistory>Use</DataHistory>')
    # Format 2.20 (8.3.27): type-reduction mode goes last in Properties and only
    # on information-register dimensions — the platform writes it nowhere else.
    if is_format_220 and register_type == 'InformationRegister':
        trm = parsed.get('typeReductionMode') or 'TransformValues'
        X(f'{indent}\t\t<TypeReductionMode>{trm}</TypeReductionMode>')
    X(f'{indent}\t</Properties>')
    X(f'{indent}</Dimension>')

# ---------------------------------------------------------------------------
# 12. Resource emitter
# ---------------------------------------------------------------------------

def emit_resource(indent, parsed, register_type):
    uid = new_uuid()
    X(f'{indent}<Resource uuid="{uid}">')
    X(f'{indent}\t<Properties>')
    X(f'{indent}\t\t<Name>{esc_xml(parsed["name"])}</Name>')
    emit_mltext(f'{indent}\t\t', 'Synonym', parsed['synonym'])
    X(f'{indent}\t\t<Comment/>')
    type_str = parsed['type']
    if type_str:
        emit_value_type(f'{indent}\t\t', type_str)
    else:
        X(f'{indent}\t\t<Type>')
        X(f'{indent}\t\t\t<v8:Type>xs:decimal</v8:Type>')
        X(f'{indent}\t\t\t<v8:NumberQualifiers>')
        X(f'{indent}\t\t\t\t<v8:Digits>15</v8:Digits>')
        X(f'{indent}\t\t\t\t<v8:FractionDigits>2</v8:FractionDigits>')
        X(f'{indent}\t\t\t\t<v8:AllowedSign>Any</v8:AllowedSign>')
        X(f'{indent}\t\t\t</v8:NumberQualifiers>')
        X(f'{indent}\t\t</Type>')
    X(f'{indent}\t\t<PasswordMode>false</PasswordMode>')
    X(f'{indent}\t\t<Format/>')
    X(f'{indent}\t\t<EditFormat/>')
    X(f'{indent}\t\t<ToolTip/>')
    X(f'{indent}\t\t<MarkNegatives>false</MarkNegatives>')
    X(f'{indent}\t\t<Mask/>')
    multi_line = 'true' if (parsed.get('multiLine') is True or 'multiline' in parsed.get('flags', [])) else 'false'
    X(f'{indent}\t\t<MultiLine>{multi_line}</MultiLine>')
    X(f'{indent}\t\t<ExtendedEdit>false</ExtendedEdit>')
    X(f'{indent}\t\t<MinValue xsi:nil="true"/>')
    X(f'{indent}\t\t<MaxValue xsi:nil="true"/>')
    if register_type == 'InformationRegister':
        X(f'{indent}\t\t<FillFromFillingValue>false</FillFromFillingValue>')
        X(f'{indent}\t\t<FillValue xsi:nil="true"/>')
    flags = parsed.get('flags', [])
    fill_checking = 'DontCheck'
    if 'req' in flags:
        fill_checking = 'ShowError'
    X(f'{indent}\t\t<FillChecking>{fill_checking}</FillChecking>')
    X(f'{indent}\t\t<ChoiceFoldersAndItems>Items</ChoiceFoldersAndItems>')
    X(f'{indent}\t\t<ChoiceParameterLinks/>')
    X(f'{indent}\t\t<ChoiceParameters/>')
    X(f'{indent}\t\t<QuickChoice>Auto</QuickChoice>')
    X(f'{indent}\t\t<CreateOnInput>Auto</CreateOnInput>')
    X(f'{indent}\t\t<ChoiceForm/>')
    X(f'{indent}\t\t<LinkByType/>')
    X(f'{indent}\t\t<ChoiceHistoryOnInput>Auto</ChoiceHistoryOnInput>')
    if register_type == 'InformationRegister':
        X(f'{indent}\t\t<Indexing>DontIndex</Indexing>')
        X(f'{indent}\t\t<FullTextSearch>Use</FullTextSearch>')
        X(f'{indent}\t\t<DataHistory>Use</DataHistory>')
    if register_type == 'AccumulationRegister':
        X(f'{indent}\t\t<FullTextSearch>Use</FullTextSearch>')
    X(f'{indent}\t</Properties>')
    X(f'{indent}</Resource>')

# ---------------------------------------------------------------------------
# 13. Property emitters per type
# ---------------------------------------------------------------------------

def emit_catalog_properties(indent):
    i = indent
    X(f'{i}<Name>{esc_xml(obj_name)}</Name>')
    emit_mltext(i, 'Synonym', synonym)
    if defn.get('comment'):
        X(f'{i}<Comment>{meta_dsl.esc_xml_text(defn["comment"])}</Comment>')
    else:
        X(f'{i}<Comment/>')
    hierarchical = 'true' if defn.get('hierarchical') is True else 'false'
    hierarchy_type = get_enum_prop('HierarchyType', 'hierarchyType', 'HierarchyFoldersAndItems')
    X(f'{i}<Hierarchical>{hierarchical}</Hierarchical>')
    X(f'{i}<HierarchyType>{hierarchy_type}</HierarchyType>')
    limit_level_count = 'true' if defn.get('limitLevelCount') is True else 'false'
    level_count = str(defn['levelCount']) if defn.get('levelCount') is not None else '2'
    folders_on_top = 'false' if defn.get('foldersOnTop') is False else 'true'
    X(f'{i}<LimitLevelCount>{limit_level_count}</LimitLevelCount>')
    X(f'{i}<LevelCount>{level_count}</LevelCount>')
    X(f'{i}<FoldersOnTop>{folders_on_top}</FoldersOnTop>')
    use_std_cmds = 'true' if get_bool_prop('useStandardCommands', True) else 'false'
    X(f'{i}<UseStandardCommands>{use_std_cmds}</UseStandardCommands>')
    owners = defn.get('owners', [])
    if owners:
        X(f'{i}<Owners>')
        for owner_ref in owners:
            full_ref = meta_dsl.normalize_md_object_ref(str(owner_ref), 'Catalog')
            X(f'{i}\t<xr:Item xsi:type="xr:MDObjectRef">{esc_xml(full_ref)}</xr:Item>')
        X(f'{i}</Owners>')
    else:
        X(f'{i}<Owners/>')
    subordination_use = get_enum_prop('SubordinationUse', 'subordinationUse', 'ToItems')
    X(f'{i}<SubordinationUse>{subordination_use}</SubordinationUse>')
    code_length = str(defn['codeLength']) if defn.get('codeLength') is not None else '9'
    description_length = str(defn['descriptionLength']) if defn.get('descriptionLength') is not None else '25'
    code_type = get_enum_prop('CodeType', 'codeType', 'String')
    code_allowed_length = get_enum_prop('CodeAllowedLength', 'codeAllowedLength', 'Variable')
    autonumbering = 'false' if defn.get('autonumbering') is False else 'true'
    check_unique = 'true' if defn.get('checkUnique') is True else 'false'
    X(f'{i}<CodeLength>{code_length}</CodeLength>')
    X(f'{i}<DescriptionLength>{description_length}</DescriptionLength>')
    X(f'{i}<CodeType>{code_type}</CodeType>')
    X(f'{i}<CodeAllowedLength>{code_allowed_length}</CodeAllowedLength>')
    code_series = get_enum_prop('CodeSeries', 'codeSeries', 'WholeCatalog')
    X(f'{i}<CodeSeries>{code_series}</CodeSeries>')
    X(f'{i}<CheckUnique>{check_unique}</CheckUnique>')
    X(f'{i}<Autonumbering>{autonumbering}</Autonumbering>')
    default_presentation = get_enum_prop('DefaultPresentation', 'defaultPresentation', 'AsDescription')
    X(f'{i}<DefaultPresentation>{default_presentation}</DefaultPresentation>')
    emit_standard_attributes(i, 'Catalog')
    emit_characteristics(i, defn.get('characteristics'))
    X(f'{i}<PredefinedDataUpdate>'
      f'{get_enum_prop("PredefinedDataUpdate", "predefinedDataUpdate", "Auto")}'
      f'</PredefinedDataUpdate>')
    X(f'{i}<EditType>{get_enum_prop("EditType", "editType", "InDialog")}</EditType>')
    quick_choice = 'true' if defn.get('quickChoice') is True else 'false'
    choice_mode = get_enum_prop('ChoiceMode', 'choiceMode', 'BothWays')
    X(f'{i}<QuickChoice>{quick_choice}</QuickChoice>')
    X(f'{i}<ChoiceMode>{choice_mode}</ChoiceMode>')
    # InputByString: an explicit `inputByString` override (names are auto-resolved,
    # [] means empty), otherwise [Description if D>0] + [Code if C>0].
    if test_def_key('inputByString'):
        ib_fields = [meta_dsl.expand_data_path(str(f)) for f in (defn.get('inputByString') or [])]
    else:
        ib_fields = []
        if int(description_length) > 0:
            ib_fields.append(f'Catalog.{obj_name}.StandardAttribute.Description')
        if int(code_length) > 0:
            ib_fields.append(f'Catalog.{obj_name}.StandardAttribute.Code')
    emit_field_block(i, 'InputByString', ib_fields)
    X(f'{i}<SearchStringModeOnInputByString>'
      f'{get_enum_prop("SearchStringModeOnInputByString", "searchStringModeOnInputByString", "Begin")}'
      f'</SearchStringModeOnInputByString>')
    X(f'{i}<FullTextSearchOnInputByString>'
      f'{get_enum_prop("FullTextSearchOnInputByString", "fullTextSearchOnInputByString", "DontUse")}'
      f'</FullTextSearchOnInputByString>')
    X(f'{i}<ChoiceDataGetModeOnInputByString>Directly</ChoiceDataGetModeOnInputByString>')
    for tag, key in (('DefaultObjectForm', 'defaultObjectForm'),
                     ('DefaultFolderForm', 'defaultFolderForm'),
                     ('DefaultListForm', 'defaultListForm'),
                     ('DefaultChoiceForm', 'defaultChoiceForm'),
                     ('DefaultFolderChoiceForm', 'defaultFolderChoiceForm'),
                     ('AuxiliaryObjectForm', 'auxiliaryObjectForm'),
                     ('AuxiliaryFolderForm', 'auxiliaryFolderForm'),
                     ('AuxiliaryListForm', 'auxiliaryListForm'),
                     ('AuxiliaryChoiceForm', 'auxiliaryChoiceForm'),
                     ('AuxiliaryFolderChoiceForm', 'auxiliaryFolderChoiceForm')):
        emit_form_ref(i, tag, defn.get(key))
    incl_help = 'true' if get_bool_prop('includeHelpInContents', False) else 'false'
    X(f'{i}<IncludeHelpInContents>{incl_help}</IncludeHelpInContents>')
    emit_based_on(i, defn.get('basedOn'))
    dl_fields = ([meta_dsl.expand_data_path(str(f)) for f in (defn.get('dataLockFields') or [])]
                 if test_def_key('dataLockFields') else [])
    emit_field_block(i, 'DataLockFields', dl_fields)
    data_lock_control_mode = get_enum_prop('DataLockControlMode', 'dataLockControlMode', 'Managed')
    X(f'{i}<DataLockControlMode>{data_lock_control_mode}</DataLockControlMode>')
    full_text_search = get_enum_prop('FullTextSearch', 'fullTextSearch', 'Use')
    X(f'{i}<FullTextSearch>{full_text_search}</FullTextSearch>')
    for tag, key in (('ObjectPresentation', 'objectPresentation'),
                     ('ExtendedObjectPresentation', 'extendedObjectPresentation'),
                     ('ListPresentation', 'listPresentation'),
                     ('ExtendedListPresentation', 'extendedListPresentation'),
                     ('Explanation', 'explanation')):
        emit_mltext(i, tag, defn.get(key))
    X(f'{i}<CreateOnInput>{get_enum_prop("CreateOnInput", "createOnInput", "Use")}</CreateOnInput>')
    X(f'{i}<ChoiceHistoryOnInput>'
      f'{get_enum_prop("ChoiceHistoryOnInput", "choiceHistoryOnInput", "Auto")}'
      f'</ChoiceHistoryOnInput>')
    X(f'{i}<DataHistory>DontUse</DataHistory>')
    X(f'{i}<UpdateDataHistoryImmediatelyAfterWrite>false</UpdateDataHistoryImmediatelyAfterWrite>')
    X(f'{i}<ExecuteAfterWriteDataHistoryVersionProcessing>false</ExecuteAfterWriteDataHistoryVersionProcessing>')

def emit_document_properties(indent):
    i = indent
    X(f'{i}<Name>{esc_xml(obj_name)}</Name>')
    emit_mltext(i, 'Synonym', synonym)
    if defn.get('comment'):
        X(f'{i}<Comment>{meta_dsl.esc_xml_text(defn["comment"])}</Comment>')
    else:
        X(f'{i}<Comment/>')
    use_std_cmd = 'true' if get_bool_prop('useStandardCommands', True) else 'false'
    X(f'{i}<UseStandardCommands>{use_std_cmd}</UseStandardCommands>')
    emit_verbatim_ref(i, 'Numerator', defn.get('numerator'))

    number_type = get_enum_prop('NumberType', 'numberType', 'String')
    number_length = str(defn['numberLength']) if defn.get('numberLength') is not None else '11'
    number_allowed_length = get_enum_prop('NumberAllowedLength', 'numberAllowedLength', 'Variable')
    number_periodicity = get_enum_prop('NumberPeriodicity', 'numberPeriodicity', 'Year')
    check_unique = 'false' if defn.get('checkUnique') is False else 'true'
    autonumbering = 'false' if defn.get('autonumbering') is False else 'true'
    X(f'{i}<NumberType>{number_type}</NumberType>')
    X(f'{i}<NumberLength>{number_length}</NumberLength>')
    X(f'{i}<NumberAllowedLength>{number_allowed_length}</NumberAllowedLength>')
    X(f'{i}<NumberPeriodicity>{number_periodicity}</NumberPeriodicity>')
    X(f'{i}<CheckUnique>{check_unique}</CheckUnique>')
    X(f'{i}<Autonumbering>{autonumbering}</Autonumbering>')

    emit_standard_attributes(i, 'Document')
    emit_characteristics(i, defn.get('characteristics'))
    emit_based_on(i, defn.get('basedOn'))

    # InputByString: an explicit `inputByString` override, otherwise [Number].
    if test_def_key('inputByString'):
        ib_fields = [meta_dsl.expand_data_path(str(f)) for f in (defn.get('inputByString') or [])]
    else:
        ib_fields = [f'Document.{obj_name}.StandardAttribute.Number']
    emit_field_block(i, 'InputByString', ib_fields)
    X(f'{i}<CreateOnInput>{get_enum_prop("CreateOnInput", "createOnInput", "Use")}</CreateOnInput>')
    X(f'{i}<SearchStringModeOnInputByString>'
      f'{get_enum_prop("SearchStringModeOnInputByString", "searchStringModeOnInputByString", "Begin")}'
      f'</SearchStringModeOnInputByString>')
    X(f'{i}<FullTextSearchOnInputByString>'
      f'{get_enum_prop("FullTextSearchOnInputByString", "fullTextSearchOnInputByString", "DontUse")}'
      f'</FullTextSearchOnInputByString>')
    X(f'{i}<ChoiceDataGetModeOnInputByString>Directly</ChoiceDataGetModeOnInputByString>')
    for tag, key in (('DefaultObjectForm', 'defaultObjectForm'),
                     ('DefaultListForm', 'defaultListForm'),
                     ('DefaultChoiceForm', 'defaultChoiceForm'),
                     ('AuxiliaryObjectForm', 'auxiliaryObjectForm'),
                     ('AuxiliaryListForm', 'auxiliaryListForm'),
                     ('AuxiliaryChoiceForm', 'auxiliaryChoiceForm')):
        emit_form_ref(i, tag, defn.get(key))

    X(f'{i}<Posting>{get_enum_prop("Posting", "posting", "Allow")}</Posting>')
    X(f'{i}<RealTimePosting>{get_enum_prop("RealTimePosting", "realTimePosting", "Deny")}</RealTimePosting>')
    X(f'{i}<RegisterRecordsDeletion>'
      f'{get_enum_prop("RegisterRecordsDeletion", "registerRecordsDeletion", "AutoDelete")}'
      f'</RegisterRecordsDeletion>')
    X(f'{i}<RegisterRecordsWritingOnPost>'
      f'{get_enum_prop("RegisterRecordsWritingOnPost", "registerRecordsWritingOnPost", "WriteSelected")}'
      f'</RegisterRecordsWritingOnPost>')
    X(f'{i}<SequenceFilling>{get_enum_prop("SequenceFilling", "sequenceFilling", "AutoFill")}</SequenceFilling>')

    # RegisterRecords — the document's movements (MDObjectRef list; type synonyms resolved)
    reg_records = []
    for rr in (defn.get('registerRecords') or []):
        rr_str = str(rr)
        if '.' in rr_str:
            dot_idx = rr_str.index('.')
            rr_prefix = rr_str[:dot_idx]
            rr_suffix = rr_str[dot_idx + 1:]
            rr_prefix = object_type_synonyms.get(rr_prefix, rr_prefix)
            reg_records.append(f'{rr_prefix}.{rr_suffix}')
        else:
            reg_records.append(rr_str)
    emit_md_ref_list(i, 'RegisterRecords', reg_records)

    post_in_priv = 'false' if defn.get('postInPrivilegedMode') is False else 'true'
    unpost_in_priv = 'false' if defn.get('unpostInPrivilegedMode') is False else 'true'
    X(f'{i}<PostInPrivilegedMode>{post_in_priv}</PostInPrivilegedMode>')
    X(f'{i}<UnpostInPrivilegedMode>{unpost_in_priv}</UnpostInPrivilegedMode>')
    incl_help = 'true' if get_bool_prop('includeHelpInContents', False) else 'false'
    X(f'{i}<IncludeHelpInContents>{incl_help}</IncludeHelpInContents>')
    dl_fields = ([meta_dsl.expand_data_path(str(f)) for f in (defn.get('dataLockFields') or [])]
                 if test_def_key('dataLockFields') else [])
    emit_field_block(i, 'DataLockFields', dl_fields)
    X(f'{i}<DataLockControlMode>'
      f'{get_enum_prop("DataLockControlMode", "dataLockControlMode", "Managed")}'
      f'</DataLockControlMode>')
    X(f'{i}<FullTextSearch>{get_enum_prop("FullTextSearch", "fullTextSearch", "Use")}</FullTextSearch>')

    for tag, key in (('ObjectPresentation', 'objectPresentation'),
                     ('ExtendedObjectPresentation', 'extendedObjectPresentation'),
                     ('ListPresentation', 'listPresentation'),
                     ('ExtendedListPresentation', 'extendedListPresentation'),
                     ('Explanation', 'explanation')):
        emit_mltext(i, tag, defn.get(key))
    X(f'{i}<ChoiceHistoryOnInput>'
      f'{get_enum_prop("ChoiceHistoryOnInput", "choiceHistoryOnInput", "Auto")}'
      f'</ChoiceHistoryOnInput>')
    X(f'{i}<DataHistory>{get_enum_prop("DataHistory", "dataHistory", "DontUse")}</DataHistory>')
    upd_dh = 'true' if get_bool_prop('updateDataHistoryImmediatelyAfterWrite', False) else 'false'
    X(f'{i}<UpdateDataHistoryImmediatelyAfterWrite>{upd_dh}</UpdateDataHistoryImmediatelyAfterWrite>')
    exec_dh = 'true' if get_bool_prop('executeAfterWriteDataHistoryVersionProcessing', False) else 'false'
    X(f'{i}<ExecuteAfterWriteDataHistoryVersionProcessing>{exec_dh}'
      f'</ExecuteAfterWriteDataHistoryVersionProcessing>')


def emit_enum_properties(indent):
    i = indent
    X(f'{i}<Name>{esc_xml(obj_name)}</Name>')
    emit_mltext(i, 'Synonym', synonym)
    if defn.get('comment'):
        X(f'{i}<Comment>{meta_dsl.esc_xml_text(defn["comment"])}</Comment>')
    else:
        X(f'{i}<Comment/>')
    use_std_cmds = 'true' if get_bool_prop('useStandardCommands', False) else 'false'
    X(f'{i}<UseStandardCommands>{use_std_cmds}</UseStandardCommands>')

    emit_standard_attributes(i, 'Enum')
    emit_characteristics(i, defn.get('characteristics'))

    quick_choice = 'false' if defn.get('quickChoice') is False else 'true'
    X(f'{i}<QuickChoice>{quick_choice}</QuickChoice>')
    X(f'{i}<ChoiceMode>{get_enum_prop("ChoiceMode", "choiceMode", "BothWays")}</ChoiceMode>')
    for tag, key in (('DefaultListForm', 'defaultListForm'),
                     ('DefaultChoiceForm', 'defaultChoiceForm'),
                     ('AuxiliaryListForm', 'auxiliaryListForm'),
                     ('AuxiliaryChoiceForm', 'auxiliaryChoiceForm')):
        emit_form_ref(i, tag, defn.get(key))
    for tag, key in (('ListPresentation', 'listPresentation'),
                     ('ExtendedListPresentation', 'extendedListPresentation'),
                     ('Explanation', 'explanation')):
        emit_mltext(i, tag, defn.get(key))
    X(f'{i}<ChoiceHistoryOnInput>'
      f'{get_enum_prop("ChoiceHistoryOnInput", "choiceHistoryOnInput", "Auto")}'
      f'</ChoiceHistoryOnInput>')


def emit_constant_properties(indent):
    i = indent
    X(f'{i}<Name>{esc_xml(obj_name)}</Name>')
    emit_mltext(i, 'Synonym', synonym)
    if defn.get('comment'):
        X(f'{i}<Comment>{meta_dsl.esc_xml_text(defn["comment"])}</Comment>')
    else:
        X(f'{i}<Comment/>')

    # Type from valueType. An explicitly empty '' means <Type/> (an untyped
    # constant); a missing key falls back to String.
    value_type = build_type_str(defn)
    type_empty = ((defn.get('valueType') is not None and str(defn['valueType']).strip() == '')
                  or (defn.get('type') is not None and str(defn['type']).strip() == ''))
    if type_empty:
        X(f'{i}<Type/>')
    else:
        emit_value_type(i, value_type or 'String')

    use_std_cmds = 'true' if get_bool_prop('useStandardCommands', True) else 'false'
    X(f'{i}<UseStandardCommands>{use_std_cmds}</UseStandardCommands>')
    emit_verbatim_ref(i, 'DefaultForm', defn.get('defaultForm'))
    emit_mltext(i, 'ExtendedPresentation', defn.get('extendedPresentation'))
    emit_mltext(i, 'Explanation', defn.get('explanation'))
    X(f'{i}<PasswordMode>{"true" if get_bool_prop("passwordMode", False) else "false"}</PasswordMode>')
    emit_mltext(i, 'Format', defn.get('format'))
    emit_mltext(i, 'EditFormat', defn.get('editFormat'))
    emit_mltext(i, 'ToolTip', defn.get('tooltip'))
    X(f'{i}<MarkNegatives>{"true" if get_bool_prop("markNegatives", False) else "false"}</MarkNegatives>')
    if defn.get('mask'):
        X(f'{i}<Mask>{meta_dsl.esc_xml_text(defn["mask"])}</Mask>')
    else:
        X(f'{i}<Mask/>')
    X(f'{i}<MultiLine>{"true" if get_bool_prop("multiLine", False) else "false"}</MultiLine>')
    X(f'{i}<ExtendedEdit>{"true" if get_bool_prop("extendedEdit", False) else "false"}</ExtendedEdit>')
    emit_min_max_value(i, 'MinValue', defn.get('minValue'))
    emit_min_max_value(i, 'MaxValue', defn.get('maxValue'))
    X(f'{i}<FillChecking>{get_enum_prop("FillChecking", "fillChecking", "DontCheck")}</FillChecking>')
    X(f'{i}<ChoiceFoldersAndItems>'
      f'{get_enum_prop("ChoiceFoldersAndItems", "choiceFoldersAndItems", "Items")}'
      f'</ChoiceFoldersAndItems>')
    emit_choice_parameter_links(i, defn.get('choiceParameterLinks'))
    emit_choice_parameters(i, defn.get('choiceParameters'))
    X(f'{i}<QuickChoice>{get_enum_prop("QuickChoice", "quickChoice", "Auto")}</QuickChoice>')
    if defn.get('choiceForm'):
        X(f'{i}<ChoiceForm>{esc_xml(str(defn["choiceForm"]))}</ChoiceForm>')
    else:
        X(f'{i}<ChoiceForm/>')
    emit_link_by_type(i, defn.get('linkByType'))
    X(f'{i}<ChoiceHistoryOnInput>'
      f'{get_enum_prop("ChoiceHistoryOnInput", "choiceHistoryOnInput", "Auto")}'
      f'</ChoiceHistoryOnInput>')

    X(f'{i}<DataLockControlMode>'
      f'{get_enum_prop("DataLockControlMode", "dataLockControlMode", "Managed")}'
      f'</DataLockControlMode>')
    X(f'{i}<DataHistory>{get_enum_prop("DataHistory", "dataHistory", "DontUse")}</DataHistory>')
    upd_dh = 'true' if get_bool_prop('updateDataHistoryImmediatelyAfterWrite', False) else 'false'
    X(f'{i}<UpdateDataHistoryImmediatelyAfterWrite>{upd_dh}</UpdateDataHistoryImmediatelyAfterWrite>')
    exec_dh = 'true' if get_bool_prop('executeAfterWriteDataHistoryVersionProcessing', False) else 'false'
    X(f'{i}<ExecuteAfterWriteDataHistoryVersionProcessing>{exec_dh}'
      f'</ExecuteAfterWriteDataHistoryVersionProcessing>')


def emit_information_register_properties(indent):
    i = indent
    X(f'{i}<Name>{esc_xml(obj_name)}</Name>')
    emit_mltext(i, 'Synonym', synonym)
    if defn.get('comment'):
        X(f'{i}<Comment>{meta_dsl.esc_xml_text(defn["comment"])}</Comment>')
    else:
        X(f'{i}<Comment/>')
    use_std_cmd = 'true' if get_bool_prop('useStandardCommands', True) else 'false'
    X(f'{i}<UseStandardCommands>{use_std_cmd}</UseStandardCommands>')
    X(f'{i}<EditType>{get_enum_prop("EditType", "editType", "InDialog")}</EditType>')
    for tag, key in (('DefaultRecordForm', 'defaultRecordForm'),
                     ('DefaultListForm', 'defaultListForm'),
                     ('AuxiliaryRecordForm', 'auxiliaryRecordForm'),
                     ('AuxiliaryListForm', 'auxiliaryListForm')):
        emit_form_ref(i, tag, defn.get(key))

    emit_standard_attributes(i, 'InformationRegister')

    periodicity = get_enum_prop('InformationRegisterPeriodicity', 'periodicity', 'Nonperiodical')
    write_mode = get_enum_prop('WriteMode', 'writeMode', 'Independent')
    # MainFilterOnPeriod is taken independently — deriving it from periodicity is
    # wrong against the reference corpus.
    main_filter_on_period = 'true' if get_bool_prop('mainFilterOnPeriod', False) else 'false'
    X(f'{i}<InformationRegisterPeriodicity>{periodicity}</InformationRegisterPeriodicity>')
    X(f'{i}<WriteMode>{write_mode}</WriteMode>')
    X(f'{i}<MainFilterOnPeriod>{main_filter_on_period}</MainFilterOnPeriod>')
    incl_help = 'true' if get_bool_prop('includeHelpInContents', False) else 'false'
    X(f'{i}<IncludeHelpInContents>{incl_help}</IncludeHelpInContents>')

    X(f'{i}<DataLockControlMode>'
      f'{get_enum_prop("DataLockControlMode", "dataLockControlMode", "Managed")}'
      f'</DataLockControlMode>')
    X(f'{i}<FullTextSearch>{get_enum_prop("FullTextSearch", "fullTextSearch", "Use")}</FullTextSearch>')

    en_tot_first = 'true' if get_bool_prop('enableTotalsSliceFirst', False) else 'false'
    en_tot_last = 'true' if get_bool_prop('enableTotalsSliceLast', False) else 'false'
    X(f'{i}<EnableTotalsSliceFirst>{en_tot_first}</EnableTotalsSliceFirst>')
    X(f'{i}<EnableTotalsSliceLast>{en_tot_last}</EnableTotalsSliceLast>')
    for tag, key in (('RecordPresentation', 'recordPresentation'),
                     ('ExtendedRecordPresentation', 'extendedRecordPresentation'),
                     ('ListPresentation', 'listPresentation'),
                     ('ExtendedListPresentation', 'extendedListPresentation'),
                     ('Explanation', 'explanation')):
        emit_mltext(i, tag, defn.get(key))
    X(f'{i}<DataHistory>{get_enum_prop("DataHistory", "dataHistory", "DontUse")}</DataHistory>')
    upd_dh = 'true' if get_bool_prop('updateDataHistoryImmediatelyAfterWrite', False) else 'false'
    X(f'{i}<UpdateDataHistoryImmediatelyAfterWrite>{upd_dh}</UpdateDataHistoryImmediatelyAfterWrite>')
    exec_dh = 'true' if get_bool_prop('executeAfterWriteDataHistoryVersionProcessing', False) else 'false'
    X(f'{i}<ExecuteAfterWriteDataHistoryVersionProcessing>{exec_dh}'
      f'</ExecuteAfterWriteDataHistoryVersionProcessing>')


def emit_accumulation_register_properties(indent):
    i = indent
    X(f'{i}<Name>{esc_xml(obj_name)}</Name>')
    emit_mltext(i, 'Synonym', synonym)
    if defn.get('comment'):
        X(f'{i}<Comment>{meta_dsl.esc_xml_text(defn["comment"])}</Comment>')
    else:
        X(f'{i}<Comment/>')
    use_std_cmd = 'true' if get_bool_prop('useStandardCommands', True) else 'false'
    X(f'{i}<UseStandardCommands>{use_std_cmd}</UseStandardCommands>')
    emit_form_ref(i, 'DefaultListForm', defn.get('defaultListForm'))
    emit_form_ref(i, 'AuxiliaryListForm', defn.get('auxiliaryListForm'))

    X(f'{i}<RegisterType>{get_enum_prop("RegisterType", "registerType", "Balance")}</RegisterType>')
    incl_help = 'true' if get_bool_prop('includeHelpInContents', False) else 'false'
    X(f'{i}<IncludeHelpInContents>{incl_help}</IncludeHelpInContents>')

    emit_standard_attributes(i, 'AccumulationRegister')

    X(f'{i}<DataLockControlMode>'
      f'{get_enum_prop("DataLockControlMode", "dataLockControlMode", "Managed")}'
      f'</DataLockControlMode>')
    X(f'{i}<FullTextSearch>{get_enum_prop("FullTextSearch", "fullTextSearch", "Use")}</FullTextSearch>')

    enable_totals_splitting = 'false' if defn.get('enableTotalsSplitting') is False else 'true'
    X(f'{i}<EnableTotalsSplitting>{enable_totals_splitting}</EnableTotalsSplitting>')

    for tag, key in (('ListPresentation', 'listPresentation'),
                     ('ExtendedListPresentation', 'extendedListPresentation'),
                     ('Explanation', 'explanation')):
        emit_mltext(i, tag, defn.get(key))


def emit_defined_type_properties(indent):
    i = indent
    X(f'{i}<Name>{esc_xml(obj_name)}</Name>')
    emit_mltext(i, 'Synonym', synonym)
    if defn.get('comment'):
        X(f'{i}<Comment>{meta_dsl.esc_xml_text(defn["comment"])}</Comment>')
    else:
        X(f'{i}<Comment/>')

    # Composite value type joined with ' + '. Accepts valueType (string) or
    # valueTypes (array); emission goes through the shared emit_value_type, which
    # handles d5p1 refs, cfg: refs, platform types and qualifiers.
    if defn.get('valueType'):
        vt_raw = defn['valueType']
        vt = ' + '.join(str(v) for v in vt_raw) if isinstance(vt_raw, list) else str(vt_raw)
    elif defn.get('valueTypes'):
        vt = ' + '.join(str(v) for v in defn['valueTypes'])
    else:
        vt = ''
    if vt:
        emit_value_type(i, vt)
    else:
        X(f'{i}<Type/>')


def emit_common_module_properties(indent):
    i = indent
    X(f'{i}<Name>{esc_xml(obj_name)}</Name>')
    emit_mltext(i, 'Synonym', synonym)
    if defn.get('comment'):
        X(f'{i}<Comment>{meta_dsl.esc_xml_text(defn["comment"])}</Comment>')
    else:
        X(f'{i}<Comment/>')
    context = str(defn['context']) if defn.get('context') else ''
    global_val = 'true' if defn.get('global') is True else 'false'
    server = 'false'
    server_call = 'false'
    client_managed = 'false'
    client_ordinary = 'false'
    external_connection = 'false'
    privileged = 'false'
    if context == 'server' or context == 'serverCall':
        server = 'true'
        server_call = 'true'
    elif context == 'client':
        client_managed = 'true'
    elif context == 'serverClient':
        server = 'true'
        client_managed = 'true'
    else:
        if defn.get('server') is True:
            server = 'true'
        if defn.get('serverCall') is True:
            server_call = 'true'
        if defn.get('clientManagedApplication') is True:
            client_managed = 'true'
        if defn.get('clientOrdinaryApplication') is True:
            client_ordinary = 'true'
        if defn.get('externalConnection') is True:
            external_connection = 'true'
        if defn.get('privileged') is True:
            privileged = 'true'
    X(f'{i}<Global>{global_val}</Global>')
    X(f'{i}<ClientManagedApplication>{client_managed}</ClientManagedApplication>')
    X(f'{i}<Server>{server}</Server>')
    X(f'{i}<ExternalConnection>{external_connection}</ExternalConnection>')
    X(f'{i}<ClientOrdinaryApplication>{client_ordinary}</ClientOrdinaryApplication>')
    X(f'{i}<ServerCall>{server_call}</ServerCall>')
    X(f'{i}<Privileged>{privileged}</Privileged>')
    return_values_reuse = get_enum_prop('ReturnValuesReuse', 'returnValuesReuse', 'DontUse')
    X(f'{i}<ReturnValuesReuse>{return_values_reuse}</ReturnValuesReuse>')

def emit_scheduled_job_properties(indent):
    i = indent
    X(f'{i}<Name>{esc_xml(obj_name)}</Name>')
    emit_mltext(i, 'Synonym', synonym)
    if defn.get('comment'):
        X(f'{i}<Comment>{meta_dsl.esc_xml_text(defn["comment"])}</Comment>')
    else:
        X(f'{i}<Comment/>')
    method_name = str(defn['methodName']) if defn.get('methodName') else ''
    if method_name and not method_name.startswith('CommonModule.'):
        method_name = f'CommonModule.{method_name}'
    X(f'{i}<MethodName>{esc_xml(method_name)}</MethodName>')
    # Description is a flat string and defaults to EMPTY — substituting the
    # synonym here breaks the decompile/compile round-trip.
    description = str(defn['description']) if defn.get('description') else ''
    if description:
        X(f'{i}<Description>{meta_dsl.esc_xml_text(description)}</Description>')
    else:
        X(f'{i}<Description/>')
    key = str(defn['key']) if defn.get('key') else ''
    X(f'{i}<Key>{esc_xml(key)}</Key>')
    use = 'true' if defn.get('use') is True else 'false'
    X(f'{i}<Use>{use}</Use>')
    predefined = 'true' if defn.get('predefined') is True else 'false'
    X(f'{i}<Predefined>{predefined}</Predefined>')
    restart_count = str(defn['restartCountOnFailure']) if defn.get('restartCountOnFailure') is not None else '3'
    restart_interval = str(defn['restartIntervalOnFailure']) if defn.get('restartIntervalOnFailure') is not None else '10'
    X(f'{i}<RestartCountOnFailure>{restart_count}</RestartCountOnFailure>')
    X(f'{i}<RestartIntervalOnFailure>{restart_interval}</RestartIntervalOnFailure>')


def emit_event_subscription_properties(indent):
    i = indent
    X(f'{i}<Name>{esc_xml(obj_name)}</Name>')
    emit_mltext(i, 'Synonym', synonym)
    if defn.get('comment'):
        X(f'{i}<Comment>{meta_dsl.esc_xml_text(defn["comment"])}</Comment>')
    else:
        X(f'{i}<Comment/>')
    # Source is a set of source types. Object types (CatalogObject.X /
    # DocumentObject.X / ...RecordSet / ...Manager) go out as cfg:, reference
    # types as d5p1 — emit_type_content owns that split, so Russian roots are
    # accepted here too.
    sources = list(defn.get('source', []))
    if sources:
        X(f'{i}<Source>')
        for src in sources:
            emit_type_content(f'{i}\t', resolve_type_str(str(src)))
        X(f'{i}</Source>')
    else:
        X(f'{i}<Source/>')
    event = str(defn['event']) if defn.get('event') else 'BeforeWrite'
    X(f'{i}<Event>{event}</Event>')
    handler = str(defn['handler']) if defn.get('handler') else ''
    if handler and not handler.startswith('CommonModule.'):
        handler = f'CommonModule.{handler}'
    X(f'{i}<Handler>{esc_xml(handler)}</Handler>')


# --- 13b. Report, DataProcessor ---

def emit_report_properties(indent):
    i = indent
    X(f'{i}<Name>{esc_xml(obj_name)}</Name>')
    emit_mltext(i, 'Synonym', synonym)
    if defn.get('comment'):
        X(f'{i}<Comment>{meta_dsl.esc_xml_text(defn["comment"])}</Comment>')
    else:
        X(f'{i}<Comment/>')
    # UseStandardCommands defaults to true: with false and no explicit command
    # placement the object is reachable only through a navigation link.
    use_std_cmds = 'true' if get_bool_prop('useStandardCommands', True) else 'false'
    X(f'{i}<UseStandardCommands>{use_std_cmds}</UseStandardCommands>')

    for tag, key in (('DefaultForm', 'defaultForm'),
                     ('AuxiliaryForm', 'auxiliaryForm'),
                     ('MainDataCompositionSchema', 'mainDataCompositionSchema'),
                     ('DefaultSettingsForm', 'defaultSettingsForm'),
                     ('AuxiliarySettingsForm', 'auxiliarySettingsForm'),
                     ('DefaultVariantForm', 'defaultVariantForm'),
                     ('VariantsStorage', 'variantsStorage'),
                     ('SettingsStorage', 'settingsStorage')):
        emit_verbatim_ref(i, tag, defn.get(key))
    incl_help = 'true' if get_bool_prop('includeHelpInContents', False) else 'false'
    X(f'{i}<IncludeHelpInContents>{incl_help}</IncludeHelpInContents>')
    emit_mltext(i, 'ExtendedPresentation', defn.get('extendedPresentation'))
    emit_mltext(i, 'Explanation', defn.get('explanation'))


def emit_data_processor_properties(indent):
    i = indent
    X(f'{i}<Name>{esc_xml(obj_name)}</Name>')
    emit_mltext(i, 'Synonym', synonym)
    if defn.get('comment'):
        X(f'{i}<Comment>{meta_dsl.esc_xml_text(defn["comment"])}</Comment>')
    else:
        X(f'{i}<Comment/>')
    use_std_cmds = 'true' if get_bool_prop('useStandardCommands', True) else 'false'
    X(f'{i}<UseStandardCommands>{use_std_cmds}</UseStandardCommands>')

    emit_verbatim_ref(i, 'DefaultForm', defn.get('defaultForm'))
    emit_verbatim_ref(i, 'AuxiliaryForm', defn.get('auxiliaryForm'))
    incl_help = 'true' if get_bool_prop('includeHelpInContents', False) else 'false'
    X(f'{i}<IncludeHelpInContents>{incl_help}</IncludeHelpInContents>')
    emit_mltext(i, 'ExtendedPresentation', defn.get('extendedPresentation'))
    emit_mltext(i, 'Explanation', defn.get('explanation'))


# --- 13c. ExchangePlan, ChartOfCharacteristicTypes, DocumentJournal ---

def emit_exchange_plan_properties(indent):
    i = indent
    X(f'{i}<Name>{esc_xml(obj_name)}</Name>')
    emit_mltext(i, 'Synonym', synonym)
    if defn.get('comment'):
        X(f'{i}<Comment>{meta_dsl.esc_xml_text(defn["comment"])}</Comment>')
    else:
        X(f'{i}<Comment/>')
    use_std_cmd = 'true' if get_bool_prop('useStandardCommands', True) else 'false'
    X(f'{i}<UseStandardCommands>{use_std_cmd}</UseStandardCommands>')

    code_length = str(defn['codeLength']) if defn.get('codeLength') is not None else '9'
    description_length = str(defn['descriptionLength']) if defn.get('descriptionLength') is not None else '150'
    code_allowed_length = get_enum_prop('CodeAllowedLength', 'codeAllowedLength', 'Variable')
    X(f'{i}<CodeLength>{code_length}</CodeLength>')
    X(f'{i}<CodeAllowedLength>{code_allowed_length}</CodeAllowedLength>')
    X(f'{i}<DescriptionLength>{description_length}</DescriptionLength>')
    X(f'{i}<DefaultPresentation>'
      f'{get_enum_prop("DefaultPresentation", "defaultPresentation", "AsDescription")}'
      f'</DefaultPresentation>')
    X(f'{i}<EditType>{get_enum_prop("EditType", "editType", "InDialog")}</EditType>')
    quick_choice = 'true' if defn.get('quickChoice') is True else 'false'
    X(f'{i}<QuickChoice>{quick_choice}</QuickChoice>')
    X(f'{i}<ChoiceMode>{get_enum_prop("ChoiceMode", "choiceMode", "BothWays")}</ChoiceMode>')

    if test_def_key('inputByString'):
        ib_fields = [meta_dsl.expand_data_path(str(f)) for f in (defn.get('inputByString') or [])]
    else:
        ib_fields = []
        if int(description_length) > 0:
            ib_fields.append(f'ExchangePlan.{obj_name}.StandardAttribute.Description')
        if int(code_length) > 0:
            ib_fields.append(f'ExchangePlan.{obj_name}.StandardAttribute.Code')
    emit_field_block(i, 'InputByString', ib_fields)
    X(f'{i}<SearchStringModeOnInputByString>'
      f'{get_enum_prop("SearchStringModeOnInputByString", "searchStringModeOnInputByString", "Begin")}'
      f'</SearchStringModeOnInputByString>')
    X(f'{i}<FullTextSearchOnInputByString>'
      f'{get_enum_prop("FullTextSearchOnInputByString", "fullTextSearchOnInputByString", "DontUse")}'
      f'</FullTextSearchOnInputByString>')
    X(f'{i}<ChoiceDataGetModeOnInputByString>Directly</ChoiceDataGetModeOnInputByString>')
    for tag, key in (('DefaultObjectForm', 'defaultObjectForm'),
                     ('DefaultListForm', 'defaultListForm'),
                     ('DefaultChoiceForm', 'defaultChoiceForm'),
                     ('AuxiliaryObjectForm', 'auxiliaryObjectForm'),
                     ('AuxiliaryListForm', 'auxiliaryListForm'),
                     ('AuxiliaryChoiceForm', 'auxiliaryChoiceForm')):
        emit_form_ref(i, tag, defn.get(key))

    emit_standard_attributes(i, 'ExchangePlan')
    emit_characteristics(i, defn.get('characteristics'))
    emit_based_on(i, defn.get('basedOn'))

    distributed = 'true' if defn.get('distributedInfoBase') is True else 'false'
    include_ext = 'true' if defn.get('includeConfigurationExtensions') is True else 'false'
    X(f'{i}<DistributedInfoBase>{distributed}</DistributedInfoBase>')
    X(f'{i}<IncludeConfigurationExtensions>{include_ext}</IncludeConfigurationExtensions>')

    X(f'{i}<CreateOnInput>{get_enum_prop("CreateOnInput", "createOnInput", "DontUse")}</CreateOnInput>')
    X(f'{i}<ChoiceHistoryOnInput>'
      f'{get_enum_prop("ChoiceHistoryOnInput", "choiceHistoryOnInput", "Auto")}'
      f'</ChoiceHistoryOnInput>')
    incl_help = 'true' if get_bool_prop('includeHelpInContents', False) else 'false'
    X(f'{i}<IncludeHelpInContents>{incl_help}</IncludeHelpInContents>')
    dl_fields = ([meta_dsl.expand_data_path(str(f)) for f in (defn.get('dataLockFields') or [])]
                 if test_def_key('dataLockFields') else [])
    emit_field_block(i, 'DataLockFields', dl_fields)
    X(f'{i}<DataLockControlMode>'
      f'{get_enum_prop("DataLockControlMode", "dataLockControlMode", "Managed")}'
      f'</DataLockControlMode>')
    X(f'{i}<FullTextSearch>{get_enum_prop("FullTextSearch", "fullTextSearch", "Use")}</FullTextSearch>')

    for tag, key in (('ObjectPresentation', 'objectPresentation'),
                     ('ExtendedObjectPresentation', 'extendedObjectPresentation'),
                     ('ListPresentation', 'listPresentation'),
                     ('ExtendedListPresentation', 'extendedListPresentation'),
                     ('Explanation', 'explanation')):
        emit_mltext(i, tag, defn.get(key))
    X(f'{i}<DataHistory>{get_enum_prop("DataHistory", "dataHistory", "DontUse")}</DataHistory>')
    upd_dh = 'true' if get_bool_prop('updateDataHistoryImmediatelyAfterWrite', False) else 'false'
    X(f'{i}<UpdateDataHistoryImmediatelyAfterWrite>{upd_dh}</UpdateDataHistoryImmediatelyAfterWrite>')
    exec_dh = 'true' if get_bool_prop('executeAfterWriteDataHistoryVersionProcessing', False) else 'false'
    X(f'{i}<ExecuteAfterWriteDataHistoryVersionProcessing>{exec_dh}'
      f'</ExecuteAfterWriteDataHistoryVersionProcessing>')


def emit_chart_of_characteristic_types_properties(indent):
    i = indent
    X(f'{i}<Name>{esc_xml(obj_name)}</Name>')
    emit_mltext(i, 'Synonym', synonym)
    if defn.get('comment'):
        X(f'{i}<Comment>{meta_dsl.esc_xml_text(defn["comment"])}</Comment>')
    else:
        X(f'{i}<Comment/>')
    use_std_cmd = 'true' if get_bool_prop('useStandardCommands', True) else 'false'
    X(f'{i}<UseStandardCommands>{use_std_cmd}</UseStandardCommands>')
    incl_help = 'true' if get_bool_prop('includeHelpInContents', False) else 'false'
    X(f'{i}<IncludeHelpInContents>{incl_help}</IncludeHelpInContents>')

    # CharacteristicExtValues — the catalog of additional characteristic values
    emit_verbatim_ref(i, 'CharacteristicExtValues', defn.get('characteristicExtValues'))

    # Type — the characteristic's value type (composite). valueType may be a
    # "A + B + C" string or an array; with no key at all we emit the platform default.
    vt = defn.get('valueType')
    if not vt and defn.get('valueTypes'):
        vt = ' + '.join(str(v) for v in defn['valueTypes'])
    elif isinstance(vt, list):
        vt = ' + '.join(str(v) for v in vt)
    if vt:
        X(f'{i}<Type>')
        emit_type_content(f'{i}\t', str(vt))
        X(f'{i}</Type>')
    else:
        X(f'{i}<Type>')
        X(f'{i}\t<v8:Type>xs:boolean</v8:Type>')
        X(f'{i}\t<v8:Type>xs:string</v8:Type>')
        X(f'{i}\t<v8:StringQualifiers>')
        X(f'{i}\t\t<v8:Length>100</v8:Length>')
        X(f'{i}\t\t<v8:AllowedLength>Variable</v8:AllowedLength>')
        X(f'{i}\t</v8:StringQualifiers>')
        X(f'{i}\t<v8:Type>xs:decimal</v8:Type>')
        X(f'{i}\t<v8:NumberQualifiers>')
        X(f'{i}\t\t<v8:Digits>15</v8:Digits>')
        X(f'{i}\t\t<v8:FractionDigits>2</v8:FractionDigits>')
        X(f'{i}\t\t<v8:AllowedSign>Any</v8:AllowedSign>')
        X(f'{i}\t</v8:NumberQualifiers>')
        X(f'{i}\t<v8:Type>xs:dateTime</v8:Type>')
        X(f'{i}\t<v8:DateQualifiers>')
        X(f'{i}\t\t<v8:DateFractions>DateTime</v8:DateFractions>')
        X(f'{i}\t</v8:DateQualifiers>')
        X(f'{i}</Type>')

    hierarchical = 'true' if defn.get('hierarchical') is True else 'false'
    X(f'{i}<Hierarchical>{hierarchical}</Hierarchical>')
    folders_on_top = 'false' if defn.get('foldersOnTop') is False else 'true'
    X(f'{i}<FoldersOnTop>{folders_on_top}</FoldersOnTop>')

    code_length = str(defn['codeLength']) if defn.get('codeLength') is not None else '9'
    description_length = str(defn['descriptionLength']) if defn.get('descriptionLength') is not None else '100'
    X(f'{i}<CodeLength>{code_length}</CodeLength>')
    X(f'{i}<CodeAllowedLength>'
      f'{get_enum_prop("CodeAllowedLength", "codeAllowedLength", "Variable")}</CodeAllowedLength>')
    X(f'{i}<DescriptionLength>{description_length}</DescriptionLength>')
    X(f'{i}<CodeSeries>{get_enum_prop("CodeSeries", "codeSeries", "WholeCharacteristicKind")}</CodeSeries>')
    check_unique = 'false' if defn.get('checkUnique') is False else 'true'
    X(f'{i}<CheckUnique>{check_unique}</CheckUnique>')
    autonumbering = 'false' if defn.get('autonumbering') is False else 'true'
    X(f'{i}<Autonumbering>{autonumbering}</Autonumbering>')
    X(f'{i}<DefaultPresentation>'
      f'{get_enum_prop("DefaultPresentation", "defaultPresentation", "AsDescription")}'
      f'</DefaultPresentation>')

    emit_standard_attributes(i, 'ChartOfCharacteristicTypes')
    emit_characteristics(i, defn.get('characteristics'))
    X(f'{i}<PredefinedDataUpdate>'
      f'{get_enum_prop("PredefinedDataUpdate", "predefinedDataUpdate", "Auto")}</PredefinedDataUpdate>')
    X(f'{i}<EditType>{get_enum_prop("EditType", "editType", "InDialog")}</EditType>')
    quick_choice = 'true' if defn.get('quickChoice') is True else 'false'
    X(f'{i}<QuickChoice>{quick_choice}</QuickChoice>')
    X(f'{i}<ChoiceMode>{get_enum_prop("ChoiceMode", "choiceMode", "BothWays")}</ChoiceMode>')

    if test_def_key('inputByString'):
        ib_fields = [meta_dsl.expand_data_path(str(f)) for f in (defn.get('inputByString') or [])]
    else:
        ib_fields = []
        if int(description_length) > 0:
            ib_fields.append(f'ChartOfCharacteristicTypes.{obj_name}.StandardAttribute.Description')
        if int(code_length) > 0:
            ib_fields.append(f'ChartOfCharacteristicTypes.{obj_name}.StandardAttribute.Code')
    emit_field_block(i, 'InputByString', ib_fields)
    X(f'{i}<CreateOnInput>{get_enum_prop("CreateOnInput", "createOnInput", "DontUse")}</CreateOnInput>')
    X(f'{i}<SearchStringModeOnInputByString>'
      f'{get_enum_prop("SearchStringModeOnInputByString", "searchStringModeOnInputByString", "Begin")}'
      f'</SearchStringModeOnInputByString>')
    X(f'{i}<ChoiceDataGetModeOnInputByString>Directly</ChoiceDataGetModeOnInputByString>')
    X(f'{i}<FullTextSearchOnInputByString>'
      f'{get_enum_prop("FullTextSearchOnInputByString", "fullTextSearchOnInputByString", "DontUse")}'
      f'</FullTextSearchOnInputByString>')
    X(f'{i}<ChoiceHistoryOnInput>'
      f'{get_enum_prop("ChoiceHistoryOnInput", "choiceHistoryOnInput", "Auto")}</ChoiceHistoryOnInput>')
    for tag, key in (('DefaultObjectForm', 'defaultObjectForm'),
                     ('DefaultFolderForm', 'defaultFolderForm'),
                     ('DefaultListForm', 'defaultListForm'),
                     ('DefaultChoiceForm', 'defaultChoiceForm'),
                     ('DefaultFolderChoiceForm', 'defaultFolderChoiceForm'),
                     ('AuxiliaryObjectForm', 'auxiliaryObjectForm'),
                     ('AuxiliaryFolderForm', 'auxiliaryFolderForm'),
                     ('AuxiliaryListForm', 'auxiliaryListForm'),
                     ('AuxiliaryChoiceForm', 'auxiliaryChoiceForm'),
                     ('AuxiliaryFolderChoiceForm', 'auxiliaryFolderChoiceForm')):
        emit_form_ref(i, tag, defn.get(key))
    emit_based_on(i, defn.get('basedOn'))
    dl_fields = ([meta_dsl.expand_data_path(str(f)) for f in (defn.get('dataLockFields') or [])]
                 if test_def_key('dataLockFields') else [])
    emit_field_block(i, 'DataLockFields', dl_fields)
    X(f'{i}<DataLockControlMode>'
      f'{get_enum_prop("DataLockControlMode", "dataLockControlMode", "Managed")}</DataLockControlMode>')
    X(f'{i}<FullTextSearch>{get_enum_prop("FullTextSearch", "fullTextSearch", "Use")}</FullTextSearch>')
    for tag, key in (('ObjectPresentation', 'objectPresentation'),
                     ('ExtendedObjectPresentation', 'extendedObjectPresentation'),
                     ('ListPresentation', 'listPresentation'),
                     ('ExtendedListPresentation', 'extendedListPresentation'),
                     ('Explanation', 'explanation')):
        emit_mltext(i, tag, defn.get(key))
    X(f'{i}<DataHistory>{get_enum_prop("DataHistory", "dataHistory", "DontUse")}</DataHistory>')
    upd_dh = 'true' if get_bool_prop('updateDataHistoryImmediatelyAfterWrite', False) else 'false'
    X(f'{i}<UpdateDataHistoryImmediatelyAfterWrite>{upd_dh}</UpdateDataHistoryImmediatelyAfterWrite>')
    exec_dh = 'true' if get_bool_prop('executeAfterWriteDataHistoryVersionProcessing', False) else 'false'
    X(f'{i}<ExecuteAfterWriteDataHistoryVersionProcessing>{exec_dh}'
      f'</ExecuteAfterWriteDataHistoryVersionProcessing>')


def emit_document_journal_properties(indent):
    i = indent
    X(f'{i}<Name>{esc_xml(obj_name)}</Name>')
    emit_mltext(i, 'Synonym', synonym)
    if defn.get('comment'):
        X(f'{i}<Comment>{meta_dsl.esc_xml_text(defn["comment"])}</Comment>')
    else:
        X(f'{i}<Comment/>')

    emit_verbatim_ref(i, 'DefaultForm', defn.get('defaultForm'))
    emit_verbatim_ref(i, 'AuxiliaryForm', defn.get('auxiliaryForm'))
    use_std_cmds = 'true' if get_bool_prop('useStandardCommands', True) else 'false'
    X(f'{i}<UseStandardCommands>{use_std_cmds}</UseStandardCommands>')

    # RegisteredDocuments — the documents this journal registers
    emit_md_ref_list(i, 'RegisteredDocuments', defn.get('registeredDocuments'))

    incl_help = 'true' if get_bool_prop('includeHelpInContents', False) else 'false'
    X(f'{i}<IncludeHelpInContents>{incl_help}</IncludeHelpInContents>')

    emit_standard_attributes(i, 'DocumentJournal')

    for tag, key in (('ListPresentation', 'listPresentation'),
                     ('ExtendedListPresentation', 'extendedListPresentation'),
                     ('Explanation', 'explanation')):
        emit_mltext(i, tag, defn.get(key))


def emit_chart_of_accounts_properties(indent):
    i = indent
    X(f'{i}<Name>{esc_xml(obj_name)}</Name>')
    emit_mltext(i, 'Synonym', synonym)
    if defn.get('comment'):
        X(f'{i}<Comment>{meta_dsl.esc_xml_text(defn["comment"])}</Comment>')
    else:
        X(f'{i}<Comment/>')
    use_std_cmd = 'true' if get_bool_prop('useStandardCommands', True) else 'false'
    X(f'{i}<UseStandardCommands>{use_std_cmd}</UseStandardCommands>')
    incl_help = 'true' if get_bool_prop('includeHelpInContents', False) else 'false'
    X(f'{i}<IncludeHelpInContents>{incl_help}</IncludeHelpInContents>')
    emit_based_on(i, defn.get('basedOn'))

    # ExtDimensionTypes — the chart of characteristic types holding the extra
    # dimension kinds (ПланВидовХарактеристик.X is accepted).
    ext_dim_types = resolve_type_prefix_syn(str(defn['extDimensionTypes'])) if defn.get('extDimensionTypes') else ''
    if ext_dim_types:
        X(f'{i}<ExtDimensionTypes>{esc_xml(ext_dim_types)}</ExtDimensionTypes>')
    else:
        X(f'{i}<ExtDimensionTypes/>')

    # Without a characteristics chart the platform refuses a count > 0, so the
    # default is 0 without one and 3 with one.
    if defn.get('maxExtDimensionCount') is not None:
        max_ext_dim = str(defn['maxExtDimensionCount'])
    else:
        max_ext_dim = '3' if ext_dim_types else '0'
    X(f'{i}<MaxExtDimensionCount>{max_ext_dim}</MaxExtDimensionCount>')

    if defn.get('codeMask'):
        X(f'{i}<CodeMask>{meta_dsl.esc_xml_text(defn["codeMask"])}</CodeMask>')
    else:
        X(f'{i}<CodeMask/>')

    code_length = str(defn['codeLength']) if defn.get('codeLength') is not None else '9'
    description_length = str(defn['descriptionLength']) if defn.get('descriptionLength') is not None else '25'
    X(f'{i}<CodeLength>{code_length}</CodeLength>')
    X(f'{i}<DescriptionLength>{description_length}</DescriptionLength>')
    X(f'{i}<CodeSeries>{get_enum_prop("CodeSeries", "codeSeries", "WholeChartOfAccounts")}</CodeSeries>')
    check_unique = 'false' if defn.get('checkUnique') is False else 'true'
    X(f'{i}<CheckUnique>{check_unique}</CheckUnique>')
    X(f'{i}<DefaultPresentation>'
      f'{get_enum_prop("DefaultPresentation", "defaultPresentation", "AsCode")}</DefaultPresentation>')

    emit_standard_attributes(i, 'ChartOfAccounts')
    emit_characteristics(i, defn.get('characteristics'))

    # StandardTabularSections — ExtDimensionTypes. The wrapper is fixed by the
    # platform (Synonym with an empty lang, Comment/ToolTip/FillChecking) and
    # nests four standard attributes.
    X(f'{i}<StandardTabularSections>')
    X(f'{i}\t<xr:StandardTabularSection name="ExtDimensionTypes">')
    X(f'{i}\t\t<xr:Synonym>')
    X(f'{i}\t\t\t<v8:item>')
    X(f'{i}\t\t\t\t<v8:lang/>')
    X(f'{i}\t\t\t\t<v8:content>Виды субконто</v8:content>')
    X(f'{i}\t\t\t</v8:item>')
    X(f'{i}\t\t</xr:Synonym>')
    X(f'{i}\t\t<xr:Comment/>')
    X(f'{i}\t\t<xr:ToolTip/>')
    X(f'{i}\t\t<xr:FillChecking>DontCheck</xr:FillChecking>')
    X(f'{i}\t\t<xr:StandardAttributes>')
    for st_attr in ('TurnoversOnly', 'Predefined', 'ExtDimensionType', 'LineNumber'):
        st_ov = {'FillChecking': 'ShowError'} if st_attr == 'ExtDimensionType' else None
        emit_standard_attribute(f'{i}\t\t\t', st_attr, st_ov)
    X(f'{i}\t\t</xr:StandardAttributes>')
    X(f'{i}\t</xr:StandardTabularSection>')
    X(f'{i}</StandardTabularSections>')

    X(f'{i}<PredefinedDataUpdate>'
      f'{get_enum_prop("PredefinedDataUpdate", "predefinedDataUpdate", "Auto")}</PredefinedDataUpdate>')
    X(f'{i}<EditType>{get_enum_prop("EditType", "editType", "InDialog")}</EditType>')
    quick_choice = 'true' if defn.get('quickChoice') is True else 'false'
    X(f'{i}<QuickChoice>{quick_choice}</QuickChoice>')
    X(f'{i}<ChoiceMode>{get_enum_prop("ChoiceMode", "choiceMode", "BothWays")}</ChoiceMode>')

    if test_def_key('inputByString'):
        ib_fields = [meta_dsl.expand_data_path(str(f)) for f in (defn.get('inputByString') or [])]
    else:
        ib_fields = []
        if int(description_length) > 0:
            ib_fields.append(f'ChartOfAccounts.{obj_name}.StandardAttribute.Description')
        if int(code_length) > 0:
            ib_fields.append(f'ChartOfAccounts.{obj_name}.StandardAttribute.Code')
    emit_field_block(i, 'InputByString', ib_fields)
    X(f'{i}<SearchStringModeOnInputByString>'
      f'{get_enum_prop("SearchStringModeOnInputByString", "searchStringModeOnInputByString", "Begin")}'
      f'</SearchStringModeOnInputByString>')
    X(f'{i}<FullTextSearchOnInputByString>'
      f'{get_enum_prop("FullTextSearchOnInputByString", "fullTextSearchOnInputByString", "DontUse")}'
      f'</FullTextSearchOnInputByString>')
    X(f'{i}<ChoiceDataGetModeOnInputByString>Directly</ChoiceDataGetModeOnInputByString>')
    X(f'{i}<CreateOnInput>{get_enum_prop("CreateOnInput", "createOnInput", "DontUse")}</CreateOnInput>')
    X(f'{i}<ChoiceHistoryOnInput>'
      f'{get_enum_prop("ChoiceHistoryOnInput", "choiceHistoryOnInput", "Auto")}</ChoiceHistoryOnInput>')
    for tag, key in (('DefaultObjectForm', 'defaultObjectForm'),
                     ('DefaultListForm', 'defaultListForm'),
                     ('DefaultChoiceForm', 'defaultChoiceForm'),
                     ('AuxiliaryObjectForm', 'auxiliaryObjectForm'),
                     ('AuxiliaryListForm', 'auxiliaryListForm'),
                     ('AuxiliaryChoiceForm', 'auxiliaryChoiceForm')):
        emit_form_ref(i, tag, defn.get(key))

    auto_order = 'false' if defn.get('autoOrderByCode') is False else 'true'
    X(f'{i}<AutoOrderByCode>{auto_order}</AutoOrderByCode>')
    order_length = str(defn['orderLength']) if defn.get('orderLength') is not None else '9'
    X(f'{i}<OrderLength>{order_length}</OrderLength>')

    dl_fields = ([meta_dsl.expand_data_path(str(f)) for f in (defn.get('dataLockFields') or [])]
                 if test_def_key('dataLockFields') else [])
    emit_field_block(i, 'DataLockFields', dl_fields)
    X(f'{i}<DataLockControlMode>'
      f'{get_enum_prop("DataLockControlMode", "dataLockControlMode", "Managed")}</DataLockControlMode>')
    X(f'{i}<FullTextSearch>{get_enum_prop("FullTextSearch", "fullTextSearch", "Use")}</FullTextSearch>')
    X(f'{i}<DataHistory>{get_enum_prop("DataHistory", "dataHistory", "DontUse")}</DataHistory>')
    upd_dh = 'true' if get_bool_prop('updateDataHistoryImmediatelyAfterWrite', False) else 'false'
    X(f'{i}<UpdateDataHistoryImmediatelyAfterWrite>{upd_dh}</UpdateDataHistoryImmediatelyAfterWrite>')
    exec_dh = 'true' if get_bool_prop('executeAfterWriteDataHistoryVersionProcessing', False) else 'false'
    X(f'{i}<ExecuteAfterWriteDataHistoryVersionProcessing>{exec_dh}'
      f'</ExecuteAfterWriteDataHistoryVersionProcessing>')

    for tag, key in (('ObjectPresentation', 'objectPresentation'),
                     ('ExtendedObjectPresentation', 'extendedObjectPresentation'),
                     ('ListPresentation', 'listPresentation'),
                     ('ExtendedListPresentation', 'extendedListPresentation'),
                     ('Explanation', 'explanation')):
        emit_mltext(i, tag, defn.get(key))


def emit_accounting_register_properties(indent):
    i = indent
    X(f'{i}<Name>{esc_xml(obj_name)}</Name>')
    emit_mltext(i, 'Synonym', synonym)
    if defn.get('comment'):
        X(f'{i}<Comment>{meta_dsl.esc_xml_text(defn["comment"])}</Comment>')
    else:
        X(f'{i}<Comment/>')
    use_std_cmd = 'true' if get_bool_prop('useStandardCommands', True) else 'false'
    X(f'{i}<UseStandardCommands>{use_std_cmd}</UseStandardCommands>')
    incl_help = 'true' if get_bool_prop('includeHelpInContents', False) else 'false'
    X(f'{i}<IncludeHelpInContents>{incl_help}</IncludeHelpInContents>')

    emit_verbatim_ref(i, 'ChartOfAccounts', defn.get('chartOfAccounts'))

    correspondence = 'true' if defn.get('correspondence') is True else 'false'
    X(f'{i}<Correspondence>{correspondence}</Correspondence>')
    period_adj_len = str(defn['periodAdjustmentLength']) if defn.get('periodAdjustmentLength') is not None else '0'
    X(f'{i}<PeriodAdjustmentLength>{period_adj_len}</PeriodAdjustmentLength>')

    emit_form_ref(i, 'DefaultListForm', defn.get('defaultListForm'))
    emit_form_ref(i, 'AuxiliaryListForm', defn.get('auxiliaryListForm'))

    emit_standard_attributes(i, 'AccountingRegister')

    X(f'{i}<DataLockControlMode>'
      f'{get_enum_prop("DataLockControlMode", "dataLockControlMode", "Managed")}</DataLockControlMode>')
    enable_totals_splitting = 'false' if defn.get('enableTotalsSplitting') is False else 'true'
    X(f'{i}<EnableTotalsSplitting>{enable_totals_splitting}</EnableTotalsSplitting>')
    X(f'{i}<FullTextSearch>{get_enum_prop("FullTextSearch", "fullTextSearch", "Use")}</FullTextSearch>')

    for tag, key in (('ListPresentation', 'listPresentation'),
                     ('ExtendedListPresentation', 'extendedListPresentation'),
                     ('Explanation', 'explanation')):
        emit_mltext(i, tag, defn.get(key))


# Standard tabular sections of a chart of calculation types — the wrapper shape
# is fixed by the platform; only the section name and synonym differ.
CALC_TYPES_STD_TABULAR = (
    ('LeadingCalculationTypes', 'Ведущие виды расчета'),
    ('DisplacingCalculationTypes', 'Вытесняющие виды расчета'),
    ('BaseCalculationTypes', 'Базовые виды расчета'),
)


def emit_calc_types_std_tabular(i):
    X(f'{i}<StandardTabularSections>')
    for name, syn in CALC_TYPES_STD_TABULAR:
        X(f'{i}\t<xr:StandardTabularSection name="{name}">')
        X(f'{i}\t\t<xr:Synonym>')
        X(f'{i}\t\t\t<v8:item>')
        X(f'{i}\t\t\t\t<v8:lang/>')
        X(f'{i}\t\t\t\t<v8:content>{meta_dsl.esc_xml_text(syn)}</v8:content>')
        X(f'{i}\t\t\t</v8:item>')
        X(f'{i}\t\t</xr:Synonym>')
        X(f'{i}\t\t<xr:Comment/>')
        X(f'{i}\t\t<xr:ToolTip/>')
        X(f'{i}\t\t<xr:FillChecking>DontCheck</xr:FillChecking>')
        X(f'{i}\t\t<xr:StandardAttributes>')
        for st_attr in ('Predefined', 'CalculationType', 'LineNumber'):
            st_ov = {'FillChecking': 'ShowError'} if st_attr == 'CalculationType' else None
            emit_standard_attribute(f'{i}\t\t\t', st_attr, st_ov)
        X(f'{i}\t\t</xr:StandardAttributes>')
        X(f'{i}\t</xr:StandardTabularSection>')
    X(f'{i}</StandardTabularSections>')


def emit_chart_of_calculation_types_properties(indent):
    i = indent
    X(f'{i}<Name>{esc_xml(obj_name)}</Name>')
    emit_mltext(i, 'Synonym', synonym)
    if defn.get('comment'):
        X(f'{i}<Comment>{meta_dsl.esc_xml_text(defn["comment"])}</Comment>')
    else:
        X(f'{i}<Comment/>')
    use_std_cmd = 'true' if get_bool_prop('useStandardCommands', True) else 'false'
    X(f'{i}<UseStandardCommands>{use_std_cmd}</UseStandardCommands>')

    code_length = str(defn['codeLength']) if defn.get('codeLength') is not None else '5'
    description_length = str(defn['descriptionLength']) if defn.get('descriptionLength') is not None else '100'
    X(f'{i}<CodeLength>{code_length}</CodeLength>')
    X(f'{i}<DescriptionLength>{description_length}</DescriptionLength>')
    X(f'{i}<CodeType>{get_enum_prop("CodeType", "codeType", "String")}</CodeType>')
    X(f'{i}<CodeAllowedLength>'
      f'{get_enum_prop("CodeAllowedLength", "codeAllowedLength", "Variable")}</CodeAllowedLength>')
    X(f'{i}<DefaultPresentation>'
      f'{get_enum_prop("DefaultPresentation", "defaultPresentation", "AsDescription")}</DefaultPresentation>')
    X(f'{i}<EditType>{get_enum_prop("EditType", "editType", "InDialog")}</EditType>')
    quick_choice = 'true' if defn.get('quickChoice') is True else 'false'
    X(f'{i}<QuickChoice>{quick_choice}</QuickChoice>')
    X(f'{i}<ChoiceMode>{get_enum_prop("ChoiceMode", "choiceMode", "BothWays")}</ChoiceMode>')

    if test_def_key('inputByString'):
        ib_fields = [meta_dsl.expand_data_path(str(f)) for f in (defn.get('inputByString') or [])]
    else:
        ib_fields = []
        if int(description_length) > 0:
            ib_fields.append(f'ChartOfCalculationTypes.{obj_name}.StandardAttribute.Description')
        if int(code_length) > 0:
            ib_fields.append(f'ChartOfCalculationTypes.{obj_name}.StandardAttribute.Code')
    emit_field_block(i, 'InputByString', ib_fields)
    X(f'{i}<SearchStringModeOnInputByString>'
      f'{get_enum_prop("SearchStringModeOnInputByString", "searchStringModeOnInputByString", "Begin")}'
      f'</SearchStringModeOnInputByString>')
    X(f'{i}<FullTextSearchOnInputByString>'
      f'{get_enum_prop("FullTextSearchOnInputByString", "fullTextSearchOnInputByString", "DontUse")}'
      f'</FullTextSearchOnInputByString>')
    X(f'{i}<ChoiceDataGetModeOnInputByString>Directly</ChoiceDataGetModeOnInputByString>')
    X(f'{i}<CreateOnInput>{get_enum_prop("CreateOnInput", "createOnInput", "DontUse")}</CreateOnInput>')
    X(f'{i}<ChoiceHistoryOnInput>'
      f'{get_enum_prop("ChoiceHistoryOnInput", "choiceHistoryOnInput", "Auto")}</ChoiceHistoryOnInput>')
    for tag, key in (('DefaultObjectForm', 'defaultObjectForm'),
                     ('DefaultListForm', 'defaultListForm'),
                     ('DefaultChoiceForm', 'defaultChoiceForm'),
                     ('AuxiliaryObjectForm', 'auxiliaryObjectForm'),
                     ('AuxiliaryListForm', 'auxiliaryListForm'),
                     ('AuxiliaryChoiceForm', 'auxiliaryChoiceForm')):
        emit_form_ref(i, tag, defn.get(key))
    emit_based_on(i, defn.get('basedOn'))

    X(f'{i}<DependenceOnCalculationTypes>'
      f'{get_enum_prop("DependenceOnCalculationTypes", "dependenceOnCalculationTypes", "DontUse")}'
      f'</DependenceOnCalculationTypes>')
    # BaseCalculationTypes — references to charts of calculation types
    # (ПланВидовРасчета.X is accepted).
    base_types = [resolve_type_prefix_syn(str(b)) for b in (defn.get('baseCalculationTypes') or [])]
    emit_md_ref_list(i, 'BaseCalculationTypes', base_types)
    action_period_use = 'true' if defn.get('actionPeriodUse') is True else 'false'
    X(f'{i}<ActionPeriodUse>{action_period_use}</ActionPeriodUse>')

    emit_standard_attributes(i, 'ChartOfCalculationTypes')
    emit_characteristics(i, defn.get('characteristics'))
    emit_calc_types_std_tabular(i)

    X(f'{i}<PredefinedDataUpdate>'
      f'{get_enum_prop("PredefinedDataUpdate", "predefinedDataUpdate", "Auto")}</PredefinedDataUpdate>')
    incl_help = 'true' if get_bool_prop('includeHelpInContents', False) else 'false'
    X(f'{i}<IncludeHelpInContents>{incl_help}</IncludeHelpInContents>')
    dl_fields = ([meta_dsl.expand_data_path(str(f)) for f in (defn.get('dataLockFields') or [])]
                 if test_def_key('dataLockFields') else [])
    emit_field_block(i, 'DataLockFields', dl_fields)
    X(f'{i}<DataLockControlMode>'
      f'{get_enum_prop("DataLockControlMode", "dataLockControlMode", "Managed")}</DataLockControlMode>')
    X(f'{i}<FullTextSearch>{get_enum_prop("FullTextSearch", "fullTextSearch", "Use")}</FullTextSearch>')

    for tag, key in (('ObjectPresentation', 'objectPresentation'),
                     ('ExtendedObjectPresentation', 'extendedObjectPresentation'),
                     ('ListPresentation', 'listPresentation'),
                     ('ExtendedListPresentation', 'extendedListPresentation'),
                     ('Explanation', 'explanation')):
        emit_mltext(i, tag, defn.get(key))
    X(f'{i}<DataHistory>{get_enum_prop("DataHistory", "dataHistory", "DontUse")}</DataHistory>')
    upd_dh = 'true' if get_bool_prop('updateDataHistoryImmediatelyAfterWrite', False) else 'false'
    X(f'{i}<UpdateDataHistoryImmediatelyAfterWrite>{upd_dh}</UpdateDataHistoryImmediatelyAfterWrite>')
    exec_dh = 'true' if get_bool_prop('executeAfterWriteDataHistoryVersionProcessing', False) else 'false'
    X(f'{i}<ExecuteAfterWriteDataHistoryVersionProcessing>{exec_dh}'
      f'</ExecuteAfterWriteDataHistoryVersionProcessing>')


def emit_calculation_register_properties(indent):
    i = indent
    X(f'{i}<Name>{esc_xml(obj_name)}</Name>')
    emit_mltext(i, 'Synonym', synonym)
    if defn.get('comment'):
        X(f'{i}<Comment>{meta_dsl.esc_xml_text(defn["comment"])}</Comment>')
    else:
        X(f'{i}<Comment/>')
    use_std_cmd = 'true' if get_bool_prop('useStandardCommands', True) else 'false'
    X(f'{i}<UseStandardCommands>{use_std_cmd}</UseStandardCommands>')
    emit_form_ref(i, 'DefaultListForm', defn.get('defaultListForm'))
    emit_form_ref(i, 'AuxiliaryListForm', defn.get('auxiliaryListForm'))

    X(f'{i}<Periodicity>'
      f'{get_enum_prop("InformationRegisterPeriodicity", "periodicity", "Month")}</Periodicity>')
    action_period = 'true' if defn.get('actionPeriod') is True else 'false'
    X(f'{i}<ActionPeriod>{action_period}</ActionPeriod>')
    base_period = 'true' if defn.get('basePeriod') is True else 'false'
    X(f'{i}<BasePeriod>{base_period}</BasePeriod>')

    emit_verbatim_ref(i, 'Schedule', defn.get('schedule'))
    emit_verbatim_ref(i, 'ScheduleValue', defn.get('scheduleValue'))
    emit_verbatim_ref(i, 'ScheduleDate', defn.get('scheduleDate'))
    emit_verbatim_ref(i, 'ChartOfCalculationTypes', defn.get('chartOfCalculationTypes'))

    incl_help = 'true' if get_bool_prop('includeHelpInContents', False) else 'false'
    X(f'{i}<IncludeHelpInContents>{incl_help}</IncludeHelpInContents>')

    emit_standard_attributes(i, 'CalculationRegister')

    X(f'{i}<DataLockControlMode>'
      f'{get_enum_prop("DataLockControlMode", "dataLockControlMode", "Managed")}</DataLockControlMode>')
    X(f'{i}<FullTextSearch>{get_enum_prop("FullTextSearch", "fullTextSearch", "Use")}</FullTextSearch>')

    for tag, key in (('ListPresentation', 'listPresentation'),
                     ('ExtendedListPresentation', 'extendedListPresentation'),
                     ('Explanation', 'explanation')):
        emit_mltext(i, tag, defn.get(key))


def emit_business_process_properties(indent):
    i = indent
    X(f'{i}<Name>{esc_xml(obj_name)}</Name>')
    emit_mltext(i, 'Synonym', synonym)
    if defn.get('comment'):
        X(f'{i}<Comment>{meta_dsl.esc_xml_text(defn["comment"])}</Comment>')
    else:
        X(f'{i}<Comment/>')
    use_std_cmd = 'true' if get_bool_prop('useStandardCommands', True) else 'false'
    X(f'{i}<UseStandardCommands>{use_std_cmd}</UseStandardCommands>')
    X(f'{i}<EditType>{get_enum_prop("EditType", "editType", "InDialog")}</EditType>')

    if test_def_key('inputByString'):
        ib_fields = [meta_dsl.expand_data_path(str(f)) for f in (defn.get('inputByString') or [])]
    else:
        ib_fields = [f'BusinessProcess.{obj_name}.StandardAttribute.Number']
    emit_field_block(i, 'InputByString', ib_fields)
    X(f'{i}<CreateOnInput>{get_enum_prop("CreateOnInput", "createOnInput", "DontUse")}</CreateOnInput>')
    X(f'{i}<SearchStringModeOnInputByString>'
      f'{get_enum_prop("SearchStringModeOnInputByString", "searchStringModeOnInputByString", "Begin")}'
      f'</SearchStringModeOnInputByString>')
    X(f'{i}<ChoiceDataGetModeOnInputByString>Directly</ChoiceDataGetModeOnInputByString>')
    X(f'{i}<FullTextSearchOnInputByString>'
      f'{get_enum_prop("FullTextSearchOnInputByString", "fullTextSearchOnInputByString", "DontUse")}'
      f'</FullTextSearchOnInputByString>')
    for tag, key in (('DefaultObjectForm', 'defaultObjectForm'),
                     ('DefaultListForm', 'defaultListForm'),
                     ('DefaultChoiceForm', 'defaultChoiceForm'),
                     ('AuxiliaryObjectForm', 'auxiliaryObjectForm'),
                     ('AuxiliaryListForm', 'auxiliaryListForm'),
                     ('AuxiliaryChoiceForm', 'auxiliaryChoiceForm')):
        emit_form_ref(i, tag, defn.get(key))
    X(f'{i}<ChoiceHistoryOnInput>'
      f'{get_enum_prop("ChoiceHistoryOnInput", "choiceHistoryOnInput", "Auto")}</ChoiceHistoryOnInput>')

    number_length = str(defn['numberLength']) if defn.get('numberLength') is not None else '11'
    check_unique = 'false' if defn.get('checkUnique') is False else 'true'
    X(f'{i}<NumberType>{get_enum_prop("NumberType", "numberType", "String")}</NumberType>')
    X(f'{i}<NumberLength>{number_length}</NumberLength>')
    X(f'{i}<NumberAllowedLength>'
      f'{get_enum_prop("NumberAllowedLength", "numberAllowedLength", "Variable")}</NumberAllowedLength>')
    X(f'{i}<CheckUnique>{check_unique}</CheckUnique>')

    emit_standard_attributes(i, 'BusinessProcess')
    emit_characteristics(i, defn.get('characteristics'))

    autonumbering = 'false' if defn.get('autonumbering') is False else 'true'
    X(f'{i}<Autonumbering>{autonumbering}</Autonumbering>')
    emit_based_on(i, defn.get('basedOn'))
    X(f'{i}<NumberPeriodicity>'
      f'{get_enum_prop("NumberPeriodicity", "numberPeriodicity", "Nonperiodical")}</NumberPeriodicity>')

    emit_verbatim_ref(i, 'Task', defn.get('task'))
    create_task_priv = 'true' if get_bool_prop('createTaskInPrivilegedMode', True) else 'false'
    X(f'{i}<CreateTaskInPrivilegedMode>{create_task_priv}</CreateTaskInPrivilegedMode>')

    dl_fields = ([meta_dsl.expand_data_path(str(f)) for f in (defn.get('dataLockFields') or [])]
                 if test_def_key('dataLockFields') else [])
    emit_field_block(i, 'DataLockFields', dl_fields)
    X(f'{i}<DataLockControlMode>'
      f'{get_enum_prop("DataLockControlMode", "dataLockControlMode", "Managed")}</DataLockControlMode>')
    incl_help = 'true' if get_bool_prop('includeHelpInContents', False) else 'false'
    X(f'{i}<IncludeHelpInContents>{incl_help}</IncludeHelpInContents>')
    X(f'{i}<FullTextSearch>{get_enum_prop("FullTextSearch", "fullTextSearch", "Use")}</FullTextSearch>')

    for tag, key in (('ObjectPresentation', 'objectPresentation'),
                     ('ExtendedObjectPresentation', 'extendedObjectPresentation'),
                     ('ListPresentation', 'listPresentation'),
                     ('ExtendedListPresentation', 'extendedListPresentation'),
                     ('Explanation', 'explanation')):
        emit_mltext(i, tag, defn.get(key))
    X(f'{i}<DataHistory>{get_enum_prop("DataHistory", "dataHistory", "DontUse")}</DataHistory>')
    upd_dh = 'true' if get_bool_prop('updateDataHistoryImmediatelyAfterWrite', False) else 'false'
    X(f'{i}<UpdateDataHistoryImmediatelyAfterWrite>{upd_dh}</UpdateDataHistoryImmediatelyAfterWrite>')
    exec_dh = 'true' if get_bool_prop('executeAfterWriteDataHistoryVersionProcessing', False) else 'false'
    X(f'{i}<ExecuteAfterWriteDataHistoryVersionProcessing>{exec_dh}'
      f'</ExecuteAfterWriteDataHistoryVersionProcessing>')


def emit_task_properties(indent):
    i = indent
    X(f'{i}<Name>{esc_xml(obj_name)}</Name>')
    emit_mltext(i, 'Synonym', synonym)
    if defn.get('comment'):
        X(f'{i}<Comment>{meta_dsl.esc_xml_text(defn["comment"])}</Comment>')
    else:
        X(f'{i}<Comment/>')
    use_std_cmd = 'true' if get_bool_prop('useStandardCommands', True) else 'false'
    X(f'{i}<UseStandardCommands>{use_std_cmd}</UseStandardCommands>')

    number_length = str(defn['numberLength']) if defn.get('numberLength') is not None else '14'
    check_unique = 'false' if defn.get('checkUnique') is False else 'true'
    autonumbering = 'false' if defn.get('autonumbering') is False else 'true'
    task_number_auto_prefix = str(defn['taskNumberAutoPrefix']) if defn.get('taskNumberAutoPrefix') else 'BusinessProcessNumber'
    description_length = str(defn['descriptionLength']) if defn.get('descriptionLength') is not None else '150'
    X(f'{i}<NumberType>{get_enum_prop("NumberType", "numberType", "String")}</NumberType>')
    X(f'{i}<NumberLength>{number_length}</NumberLength>')
    X(f'{i}<NumberAllowedLength>'
      f'{get_enum_prop("NumberAllowedLength", "numberAllowedLength", "Variable")}</NumberAllowedLength>')
    X(f'{i}<CheckUnique>{check_unique}</CheckUnique>')
    X(f'{i}<Autonumbering>{autonumbering}</Autonumbering>')
    X(f'{i}<TaskNumberAutoPrefix>{task_number_auto_prefix}</TaskNumberAutoPrefix>')
    X(f'{i}<DescriptionLength>{description_length}</DescriptionLength>')
    emit_verbatim_ref(i, 'Addressing', defn.get('addressing'))
    emit_verbatim_ref(i, 'MainAddressingAttribute', defn.get('mainAddressingAttribute'))
    emit_verbatim_ref(i, 'CurrentPerformer', defn.get('currentPerformer'))
    emit_based_on(i, defn.get('basedOn'))
    emit_standard_attributes(i, 'Task')
    emit_characteristics(i, defn.get('characteristics'))
    X(f'{i}<DefaultPresentation>'
      f'{get_enum_prop("DefaultPresentation", "defaultPresentation", "AsDescription")}</DefaultPresentation>')
    X(f'{i}<EditType>{get_enum_prop("EditType", "editType", "InDialog")}</EditType>')

    if test_def_key('inputByString'):
        ib_fields = [meta_dsl.expand_data_path(str(f)) for f in (defn.get('inputByString') or [])]
    else:
        ib_fields = [f'Task.{obj_name}.StandardAttribute.Number']
    emit_field_block(i, 'InputByString', ib_fields)
    X(f'{i}<SearchStringModeOnInputByString>'
      f'{get_enum_prop("SearchStringModeOnInputByString", "searchStringModeOnInputByString", "Begin")}'
      f'</SearchStringModeOnInputByString>')
    X(f'{i}<FullTextSearchOnInputByString>'
      f'{get_enum_prop("FullTextSearchOnInputByString", "fullTextSearchOnInputByString", "DontUse")}'
      f'</FullTextSearchOnInputByString>')
    X(f'{i}<ChoiceDataGetModeOnInputByString>Directly</ChoiceDataGetModeOnInputByString>')
    X(f'{i}<CreateOnInput>{get_enum_prop("CreateOnInput", "createOnInput", "DontUse")}</CreateOnInput>')
    for tag, key in (('DefaultObjectForm', 'defaultObjectForm'),
                     ('DefaultListForm', 'defaultListForm'),
                     ('DefaultChoiceForm', 'defaultChoiceForm'),
                     ('AuxiliaryObjectForm', 'auxiliaryObjectForm'),
                     ('AuxiliaryListForm', 'auxiliaryListForm'),
                     ('AuxiliaryChoiceForm', 'auxiliaryChoiceForm')):
        emit_form_ref(i, tag, defn.get(key))
    X(f'{i}<ChoiceHistoryOnInput>'
      f'{get_enum_prop("ChoiceHistoryOnInput", "choiceHistoryOnInput", "Auto")}</ChoiceHistoryOnInput>')
    incl_help = 'true' if get_bool_prop('includeHelpInContents', False) else 'false'
    X(f'{i}<IncludeHelpInContents>{incl_help}</IncludeHelpInContents>')
    dl_fields = ([meta_dsl.expand_data_path(str(f)) for f in (defn.get('dataLockFields') or [])]
                 if test_def_key('dataLockFields') else [])
    emit_field_block(i, 'DataLockFields', dl_fields)
    X(f'{i}<DataLockControlMode>'
      f'{get_enum_prop("DataLockControlMode", "dataLockControlMode", "Managed")}</DataLockControlMode>')
    X(f'{i}<FullTextSearch>{get_enum_prop("FullTextSearch", "fullTextSearch", "Use")}</FullTextSearch>')
    for tag, key in (('ObjectPresentation', 'objectPresentation'),
                     ('ExtendedObjectPresentation', 'extendedObjectPresentation'),
                     ('ListPresentation', 'listPresentation'),
                     ('ExtendedListPresentation', 'extendedListPresentation'),
                     ('Explanation', 'explanation')):
        emit_mltext(i, tag, defn.get(key))
    X(f'{i}<DataHistory>{get_enum_prop("DataHistory", "dataHistory", "DontUse")}</DataHistory>')
    upd_dh = 'true' if get_bool_prop('updateDataHistoryImmediatelyAfterWrite', False) else 'false'
    X(f'{i}<UpdateDataHistoryImmediatelyAfterWrite>{upd_dh}</UpdateDataHistoryImmediatelyAfterWrite>')
    exec_dh = 'true' if get_bool_prop('executeAfterWriteDataHistoryVersionProcessing', False) else 'false'
    X(f'{i}<ExecuteAfterWriteDataHistoryVersionProcessing>{exec_dh}'
      f'</ExecuteAfterWriteDataHistoryVersionProcessing>')


def emit_http_service_properties(indent):
    i = indent
    X(f'{i}<Name>{esc_xml(obj_name)}</Name>')
    emit_mltext(i, 'Synonym', synonym)
    X(f'{i}<Comment/>')
    root_url = str(defn['rootURL']) if defn.get('rootURL') else obj_name.lower()
    X(f'{i}<RootURL>{esc_xml(root_url)}</RootURL>')
    reuse_sessions = get_enum_prop('ReuseSessions', 'reuseSessions', 'DontUse')
    X(f'{i}<ReuseSessions>{reuse_sessions}</ReuseSessions>')
    session_max_age = str(defn['sessionMaxAge']) if defn.get('sessionMaxAge') is not None else '20'
    X(f'{i}<SessionMaxAge>{session_max_age}</SessionMaxAge>')

def emit_web_service_properties(indent):
    i = indent
    X(f'{i}<Name>{esc_xml(obj_name)}</Name>')
    emit_mltext(i, 'Synonym', synonym)
    X(f'{i}<Comment/>')
    namespace = str(defn['namespace']) if defn.get('namespace') else ''
    X(f'{i}<Namespace>{esc_xml(namespace)}</Namespace>')
    xdto_packages = str(defn['xdtoPackages']) if defn.get('xdtoPackages') else ''
    if xdto_packages:
        X(f'{i}<XDTOPackages>{xdto_packages}</XDTOPackages>')
    else:
        X(f'{i}<XDTOPackages/>')
    reuse_sessions = get_enum_prop('ReuseSessions', 'reuseSessions', 'DontUse')
    X(f'{i}<ReuseSessions>{reuse_sessions}</ReuseSessions>')
    session_max_age = str(defn['sessionMaxAge']) if defn.get('sessionMaxAge') is not None else '20'
    X(f'{i}<SessionMaxAge>{session_max_age}</SessionMaxAge>')


# --- 13g. ChildObjects emitters for new types ---

def emit_column(indent, col_def):
    uid = new_uuid()
    name = ''
    col_synonym = ''
    indexing = 'DontIndex'
    references = []
    if isinstance(col_def, str):
        name = col_def
        col_synonym = split_camel_case(name)
    else:
        name = str(col_def.get('name', ''))
        col_synonym = str(col_def['synonym']) if col_def.get('synonym') else split_camel_case(name)
        if col_def.get('indexing'):
            indexing = str(col_def['indexing'])
        if col_def.get('references'):
            references = list(col_def['references'])
    X(f'{indent}<Column uuid="{uid}">')
    X(f'{indent}\t<Properties>')
    X(f'{indent}\t\t<Name>{esc_xml(name)}</Name>')
    emit_mltext(f'{indent}\t\t', 'Synonym', col_synonym)
    X(f'{indent}\t\t<Comment/>')
    X(f'{indent}\t\t<Indexing>{indexing}</Indexing>')
    if references:
        X(f'{indent}\t\t<References>')
        for ref in references:
            X(f'{indent}\t\t\t<xr:Item xsi:type="xr:MDObjectRef">{ref}</xr:Item>')
        X(f'{indent}\t\t</References>')
    else:
        X(f'{indent}\t\t<References/>')
    X(f'{indent}\t</Properties>')
    X(f'{indent}</Column>')

def emit_accounting_flag(indent, flag_name):
    uid = new_uuid()
    flag_synonym = split_camel_case(flag_name)
    X(f'{indent}<AccountingFlag uuid="{uid}">')
    X(f'{indent}\t<Properties>')
    X(f'{indent}\t\t<Name>{esc_xml(flag_name)}</Name>')
    emit_mltext(f'{indent}\t\t', 'Synonym', flag_synonym)
    X(f'{indent}\t\t<Comment/>')
    X(f'{indent}\t\t<Type>')
    X(f'{indent}\t\t\t<v8:Type>xs:boolean</v8:Type>')
    X(f'{indent}\t\t</Type>')
    X(f'{indent}\t\t<PasswordMode>false</PasswordMode>')
    X(f'{indent}\t\t<Format/>')
    X(f'{indent}\t\t<EditFormat/>')
    X(f'{indent}\t\t<ToolTip/>')
    X(f'{indent}\t\t<MarkNegatives>false</MarkNegatives>')
    X(f'{indent}\t\t<Mask/>')
    X(f'{indent}\t\t<MultiLine>false</MultiLine>')
    X(f'{indent}\t\t<ExtendedEdit>false</ExtendedEdit>')
    X(f'{indent}\t\t<MinValue xsi:nil="true"/>')
    X(f'{indent}\t\t<MaxValue xsi:nil="true"/>')
    X(f'{indent}\t\t<FillChecking>DontCheck</FillChecking>')
    X(f'{indent}\t\t<ChoiceParameterLinks/>')
    X(f'{indent}\t\t<ChoiceParameters/>')
    X(f'{indent}\t\t<QuickChoice>Auto</QuickChoice>')
    X(f'{indent}\t\t<ChoiceForm/>')
    X(f'{indent}\t\t<LinkByType/>')
    X(f'{indent}\t\t<ChoiceHistoryOnInput>Auto</ChoiceHistoryOnInput>')
    X(f'{indent}\t</Properties>')
    X(f'{indent}</AccountingFlag>')

def emit_ext_dimension_accounting_flag(indent, flag_name):
    uid = new_uuid()
    flag_synonym = split_camel_case(flag_name)
    X(f'{indent}<ExtDimensionAccountingFlag uuid="{uid}">')
    X(f'{indent}\t<Properties>')
    X(f'{indent}\t\t<Name>{esc_xml(flag_name)}</Name>')
    emit_mltext(f'{indent}\t\t', 'Synonym', flag_synonym)
    X(f'{indent}\t\t<Comment/>')
    X(f'{indent}\t\t<Type>')
    X(f'{indent}\t\t\t<v8:Type>xs:boolean</v8:Type>')
    X(f'{indent}\t\t</Type>')
    X(f'{indent}\t\t<PasswordMode>false</PasswordMode>')
    X(f'{indent}\t\t<Format/>')
    X(f'{indent}\t\t<EditFormat/>')
    X(f'{indent}\t\t<ToolTip/>')
    X(f'{indent}\t\t<MarkNegatives>false</MarkNegatives>')
    X(f'{indent}\t\t<Mask/>')
    X(f'{indent}\t\t<MultiLine>false</MultiLine>')
    X(f'{indent}\t\t<ExtendedEdit>false</ExtendedEdit>')
    X(f'{indent}\t\t<MinValue xsi:nil="true"/>')
    X(f'{indent}\t\t<MaxValue xsi:nil="true"/>')
    X(f'{indent}\t\t<FillChecking>DontCheck</FillChecking>')
    X(f'{indent}\t\t<ChoiceParameterLinks/>')
    X(f'{indent}\t\t<ChoiceParameters/>')
    X(f'{indent}\t\t<QuickChoice>Auto</QuickChoice>')
    X(f'{indent}\t\t<ChoiceForm/>')
    X(f'{indent}\t\t<LinkByType/>')
    X(f'{indent}\t\t<ChoiceHistoryOnInput>Auto</ChoiceHistoryOnInput>')
    X(f'{indent}\t</Properties>')
    X(f'{indent}</ExtDimensionAccountingFlag>')

def emit_url_template(indent, tmpl_name, tmpl_def):
    uid = new_uuid()
    tmpl_synonym = split_camel_case(tmpl_name)
    template = ''
    methods = {}
    if isinstance(tmpl_def, str):
        template = tmpl_def
    else:
        template = str(tmpl_def['template']) if tmpl_def.get('template') else f'/{tmpl_name.lower()}'
        if tmpl_def.get('methods'):
            for k, v in tmpl_def['methods'].items():
                methods[k] = str(v)
    X(f'{indent}<URLTemplate uuid="{uid}">')
    X(f'{indent}\t<Properties>')
    X(f'{indent}\t\t<Name>{esc_xml(tmpl_name)}</Name>')
    emit_mltext(f'{indent}\t\t', 'Synonym', tmpl_synonym)
    X(f'{indent}\t\t<Template>{esc_xml(template)}</Template>')
    X(f'{indent}\t</Properties>')
    if methods:
        X(f'{indent}\t<ChildObjects>')
        for method_name, http_method in sorted(methods.items()):
            method_uuid = new_uuid()
            method_synonym = split_camel_case(method_name)
            handler = f'{tmpl_name}{method_name}'
            X(f'{indent}\t\t<Method uuid="{method_uuid}">')
            X(f'{indent}\t\t\t<Properties>')
            X(f'{indent}\t\t\t\t<Name>{esc_xml(method_name)}</Name>')
            emit_mltext(f'{indent}\t\t\t\t', 'Synonym', method_synonym)
            X(f'{indent}\t\t\t\t<HTTPMethod>{http_method}</HTTPMethod>')
            X(f'{indent}\t\t\t\t<Handler>{esc_xml(handler)}</Handler>')
            X(f'{indent}\t\t\t</Properties>')
            X(f'{indent}\t\t</Method>')
        X(f'{indent}\t</ChildObjects>')
    else:
        X(f'{indent}\t<ChildObjects/>')
    X(f'{indent}</URLTemplate>')

def emit_operation(indent, op_name, op_def):
    uid = new_uuid()
    op_synonym = split_camel_case(op_name)
    return_type = 'xs:string'
    nillable = 'false'
    transactioned = 'false'
    handler = op_name
    params = {}
    if isinstance(op_def, str):
        return_type = op_def
    else:
        if op_def.get('returnType'):
            return_type = str(op_def['returnType'])
        if op_def.get('nillable') is True:
            nillable = 'true'
        if op_def.get('transactioned') is True:
            transactioned = 'true'
        if op_def.get('handler'):
            handler = str(op_def['handler'])
        if op_def.get('parameters'):
            for k, v in op_def['parameters'].items():
                params[k] = v
    X(f'{indent}<Operation uuid="{uid}">')
    X(f'{indent}\t<Properties>')
    X(f'{indent}\t\t<Name>{esc_xml(op_name)}</Name>')
    emit_mltext(f'{indent}\t\t', 'Synonym', op_synonym)
    X(f'{indent}\t\t<Comment/>')
    X(f'{indent}\t\t<XDTOReturningValueType>{return_type}</XDTOReturningValueType>')
    X(f'{indent}\t\t<Nillable>{nillable}</Nillable>')
    X(f'{indent}\t\t<Transactioned>{transactioned}</Transactioned>')
    X(f'{indent}\t\t<ProcedureName>{esc_xml(handler)}</ProcedureName>')
    X(f'{indent}\t</Properties>')
    if params:
        X(f'{indent}\t<ChildObjects>')
        for param_name, param_def in sorted(params.items()):
            param_uuid = new_uuid()
            param_synonym = split_camel_case(param_name)
            param_type = 'xs:string'
            param_nillable = 'true'
            param_dir = 'In'
            if isinstance(param_def, str):
                param_type = param_def
            else:
                if param_def.get('type'):
                    param_type = str(param_def['type'])
                if param_def.get('nillable') is False:
                    param_nillable = 'false'
                if param_def.get('direction'):
                    param_dir = str(param_def['direction'])
            X(f'{indent}\t\t<Parameter uuid="{param_uuid}">')
            X(f'{indent}\t\t\t<Properties>')
            X(f'{indent}\t\t\t\t<Name>{esc_xml(param_name)}</Name>')
            emit_mltext(f'{indent}\t\t\t\t', 'Synonym', param_synonym)
            X(f'{indent}\t\t\t\t<XDTOValueType>{param_type}</XDTOValueType>')
            X(f'{indent}\t\t\t\t<Nillable>{param_nillable}</Nillable>')
            X(f'{indent}\t\t\t\t<TransferDirection>{param_dir}</TransferDirection>')
            X(f'{indent}\t\t\t</Properties>')
            X(f'{indent}\t\t</Parameter>')
        X(f'{indent}\t</ChildObjects>')
    else:
        X(f'{indent}\t<ChildObjects/>')
    X(f'{indent}</Operation>')

def emit_addressing_attribute(indent, addr_def):
    uid = new_uuid()
    name = ''
    attr_synonym = ''
    type_str = ''
    addressing_dimension = ''
    indexing = 'Index'
    parsed = parse_attribute_shorthand(addr_def)
    name = parsed['name']
    attr_synonym = parsed['synonym']
    type_str = parsed['type']
    if not isinstance(addr_def, str):
        if addr_def.get('addressingDimension'):
            addressing_dimension = str(addr_def['addressingDimension'])
        if addr_def.get('indexing'):
            indexing = str(addr_def['indexing'])
    X(f'{indent}<AddressingAttribute uuid="{uid}">')
    X(f'{indent}\t<Properties>')
    X(f'{indent}\t\t<Name>{esc_xml(name)}</Name>')
    emit_mltext(f'{indent}\t\t', 'Synonym', attr_synonym)
    X(f'{indent}\t\t<Comment/>')
    if type_str:
        emit_value_type(f'{indent}\t\t', type_str)
    else:
        X(f'{indent}\t\t<Type>')
        X(f'{indent}\t\t\t<v8:Type>xs:string</v8:Type>')
        X(f'{indent}\t\t</Type>')
    if addressing_dimension:
        X(f'{indent}\t\t<AddressingDimension>{addressing_dimension}</AddressingDimension>')
    else:
        X(f'{indent}\t\t<AddressingDimension/>')
    X(f'{indent}\t\t<Indexing>{indexing}</Indexing>')
    X(f'{indent}\t\t<FullTextSearch>Use</FullTextSearch>')
    X(f'{indent}\t\t<DataHistory>Use</DataHistory>')
    X(f'{indent}\t</Properties>')
    X(f'{indent}</AddressingAttribute>')

# ---------------------------------------------------------------------------
# 14. Namespaces
# ---------------------------------------------------------------------------

xmlns_decl = 'xmlns="http://v8.1c.ru/8.3/MDClasses" xmlns:app="http://v8.1c.ru/8.2/managed-application/core" xmlns:cfg="http://v8.1c.ru/8.1/data/enterprise/current-config" xmlns:cmi="http://v8.1c.ru/8.2/managed-application/cmi" xmlns:ent="http://v8.1c.ru/8.1/data/enterprise" xmlns:lf="http://v8.1c.ru/8.2/managed-application/logform" xmlns:style="http://v8.1c.ru/8.1/data/ui/style" xmlns:sys="http://v8.1c.ru/8.1/data/ui/fonts/system" xmlns:v8="http://v8.1c.ru/8.1/data/core" xmlns:v8ui="http://v8.1c.ru/8.1/data/ui" xmlns:web="http://v8.1c.ru/8.1/data/ui/colors/web" xmlns:win="http://v8.1c.ru/8.1/data/ui/colors/windows" xmlns:xen="http://v8.1c.ru/8.3/xcf/enums" xmlns:xpr="http://v8.1c.ru/8.3/xcf/predef" xmlns:xr="http://v8.1c.ru/8.3/xcf/readable" xmlns:xs="http://www.w3.org/2001/XMLSchema" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"'

# ---------------------------------------------------------------------------
# 14a. Detect format version from existing Configuration.xml
# ---------------------------------------------------------------------------

def detect_format_version(d):
    while d:
        cfg_path = os.path.join(d, "Configuration.xml")
        if os.path.isfile(cfg_path):
            with open(cfg_path, "r", encoding="utf-8-sig") as f:
                head = f.read(2000)
            m = re.search(r'<MetaDataObject[^>]+version="(\d+\.\d+)"', head)
            if m:
                return m.group(1)
        parent = os.path.dirname(d)
        if parent == d:
            break
        d = parent
    return "2.17"

def detect_compatibility_mode(d):
    """<CompatibilityMode> from the nearest Configuration.xml up the tree."""
    while d:
        cfg_path = os.path.join(d, "Configuration.xml")
        if os.path.isfile(cfg_path):
            try:
                with open(cfg_path, "r", encoding="utf-8-sig") as f:
                    head = f.read(65536)
                m = re.search(r'<CompatibilityMode>([^<]+)</CompatibilityMode>', head)
                if m:
                    return m.group(1).strip()
            except Exception:
                pass
        parent = os.path.dirname(d)
        if parent == d:
            break
        d = parent
    return "Version8_3_24"


def compat_mode_rank(mode):
    m = re.match(r'^Version(\d+)_(\d+)_(\d+)$', mode or '')
    if m:
        return int(m.group(1)) * 10000 + int(m.group(2)) * 100 + int(m.group(3))
    return 0


def format_rank(ver):
    m = re.match(r'^(\d+)\.(\d+)$', ver or '')
    if m:
        return int(m.group(1)) * 100 + int(m.group(2))
    return 0


format_version = detect_format_version(output_dir)
compat_mode = detect_compatibility_mode(output_dir)
# Format 2.20 (platform 8.3.27) added TypeReductionMode and LineNumberLength.
is_format_220 = format_rank(format_version) >= 220
# Default row-number length of a tabular section: 9 from 8.3.27, 5 before.
line_number_length_default = 9 if compat_mode_rank(compat_mode) >= 80327 else 5

# ---------------------------------------------------------------------------
# 15. Main assembler
# ---------------------------------------------------------------------------

obj_uuid = new_uuid()

# ---------------------------------------------------------------------------
# Object types without child objects (common attributes / commands / forms /
# pictures / templates, session parameters, storages, references, numerators,
# filter criteria, functional options, sequences, command groups).
# ---------------------------------------------------------------------------

def _comment(i):
    if defn.get('comment'):
        X(f'{i}<Comment>{meta_dsl.esc_xml_text(defn["comment"])}</Comment>')
    else:
        X(f'{i}<Comment/>')


def _head(i):
    X(f'{i}<Name>{esc_xml(obj_name)}</Name>')
    emit_mltext(i, 'Synonym', synonym)
    _comment(i)


def _value_type_or_empty(i):
    """Composite value type from valueType / valueTypes; <Type/> when absent."""
    if defn.get('valueType'):
        vt_raw = defn['valueType']
        vt = ' + '.join(str(v) for v in vt_raw) if isinstance(vt_raw, list) else str(vt_raw)
    elif defn.get('valueTypes'):
        vt = ' + '.join(str(v) for v in defn['valueTypes'])
    else:
        vt = ''
    if vt:
        emit_value_type(i, vt)
    else:
        X(f'{i}<Type/>')


def emit_command_picture(indent, cmd):
    pic = cmd.get('picture')
    if not pic:
        X(f'{indent}<Picture/>')
        return
    lt = True
    tpx = None
    if isinstance(pic, str):
        src = pic
        if cmd.get('loadTransparent') is False:
            lt = False
    else:
        src = str(pic.get('src') or pic.get('ref') or '')
        if pic.get('loadTransparent') is False:
            lt = False
        tpx = pic.get('transparentPixel')
    if not src:
        X(f'{indent}<Picture/>')
        return
    X(f'{indent}<Picture>')
    m = re.match(r'^abs:(.*)$', src)
    if m:
        X(f'{indent}\t<xr:Abs>{esc_xml(m.group(1))}</xr:Abs>')
    else:
        X(f'{indent}\t<xr:Ref>{esc_xml(src)}</xr:Ref>')
    X(f'{indent}\t<xr:LoadTransparent>{"true" if lt else "false"}</xr:LoadTransparent>')
    if tpx:
        X(f'{indent}\t<xr:TransparentPixel x="{tpx.get("x")}" y="{tpx.get("y")}"/>')
    X(f'{indent}</Picture>')


# ---------------------------------------------------------------------------
# Object command interface: command groups and the <Command> emitter.
# ---------------------------------------------------------------------------

# Groups of a SECTION's command interface (navigation / actions panel): such a
# command takes NO parameter. Form groups do allow one.
SECTION_COMMAND_GROUPS = (
    'NavigationPanelImportant', 'NavigationPanelOrdinary', 'NavigationPanelSeeAlso',
    'ActionsPanelCreate', 'ActionsPanelReports', 'ActionsPanelTools',
)
FORM_COMMAND_GROUPS = (
    'FormCommandBarImportant', 'FormCommandBarCreateBasedOn',
    'FormNavigationPanelImportant', 'FormNavigationPanelGoTo', 'FormNavigationPanelSeeAlso',
)
VALID_COMMAND_GROUPS = SECTION_COMMAND_GROUPS + FORM_COMMAND_GROUPS
# Forgiving input: the Russian captions of the groups map to the canonical names.
COMMAND_GROUP_ALIASES = {
    'Панель навигации.Важное': 'NavigationPanelImportant',
    'Панель навигации.Обычное': 'NavigationPanelOrdinary',
    'Панель навигации.См. также': 'NavigationPanelSeeAlso',
    'Панель действий.Создать': 'ActionsPanelCreate',
    'Панель действий.Отчеты': 'ActionsPanelReports',
    'Панель действий.Отчёты': 'ActionsPanelReports',
    'Панель действий.Сервис': 'ActionsPanelTools',
    'Командная панель формы.Важное': 'FormCommandBarImportant',
    'Командная панель формы.Создать на основании': 'FormCommandBarCreateBasedOn',
    'Панель навигации формы.Важное': 'FormNavigationPanelImportant',
    'Панель навигации формы.Перейти': 'FormNavigationPanelGoTo',
    'Панель навигации формы.См. также': 'FormNavigationPanelSeeAlso',
}


def resolve_command_group(raw, cmd_name):
    """Russian synonym -> canonical; ГруппаКоманд.X -> CommandGroup.X.
    1C requires a group, so an empty value is an error with a hint."""
    g = str(raw or '').strip()
    if not g:
        print(f"Команде '{cmd_name}' не задана группа (group). 1С требует группу. "
              f"Валидные: {', '.join(VALID_COMMAND_GROUPS)}; либо CommandGroup.<Имя> - "
              f"кастомная группа.", file=sys.stderr)
        sys.exit(1)
    if g in COMMAND_GROUP_ALIASES:
        return COMMAND_GROUP_ALIASES[g]
    m = re.match(r'^(?:CommandGroup|ГруппаКоманд)\.(.+)$', g)
    if m:
        return f'CommandGroup.{m.group(1)}'
    return g


def emit_command(indent, cmd_name, cmd):
    X(f'{indent}<Command uuid="{new_uuid()}">')
    X(f'{indent}\t<Properties>')
    X(f'{indent}\t\t<Name>{esc_xml(cmd_name)}</Name>')
    syn = cmd.get('synonym') if cmd.get('synonym') is not None else split_camel_case(cmd_name)
    emit_mltext(f'{indent}\t\t', 'Synonym', syn)
    if cmd.get('comment'):
        X(f'{indent}\t\t<Comment>{meta_dsl.esc_xml_text(cmd["comment"])}</Comment>')
    else:
        X(f'{indent}\t\t<Comment/>')
    group = resolve_command_group(cmd.get('group'), cmd_name)
    if cmd.get('commandParameterType') and group in SECTION_COMMAND_GROUPS:
        print(f"Команда '{cmd_name}': тип параметра (commandParameterType) недоступен для команд "
              f"командного интерфейса раздела ('{group}'). Тип параметра - только для групп формы "
              f"(FormCommandBar*/FormNavigationPanel*) или CommandGroup.<Имя>.", file=sys.stderr)
        sys.exit(1)
    X(f'{indent}\t\t<Group>{esc_xml(group)}</Group>')
    if cmd.get('commandParameterType'):
        X(f'{indent}\t\t<CommandParameterType>')
        emit_type_content(f'{indent}\t\t\t', str(cmd['commandParameterType']))
        X(f'{indent}\t\t</CommandParameterType>')
    else:
        X(f'{indent}\t\t<CommandParameterType/>')
    pum = str(cmd['parameterUseMode']) if cmd.get('parameterUseMode') else 'Single'
    X(f'{indent}\t\t<ParameterUseMode>{pum}</ParameterUseMode>')
    md = 'true' if cmd.get('modifiesData') is True else 'false'
    X(f'{indent}\t\t<ModifiesData>{md}</ModifiesData>')
    rep_ = str(cmd['representation']) if cmd.get('representation') else 'Auto'
    X(f'{indent}\t\t<Representation>{rep_}</Representation>')
    emit_mltext(f'{indent}\t\t', 'ToolTip', cmd.get('tooltip'))
    emit_command_picture(f'{indent}\t\t', cmd)
    if cmd.get('shortcut'):
        X(f'{indent}\t\t<Shortcut>{esc_xml(str(cmd["shortcut"]))}</Shortcut>')
    else:
        X(f'{indent}\t\t<Shortcut/>')
    osu = str(cmd['onMainServerUnavalableBehavior']) if cmd.get('onMainServerUnavalableBehavior') else 'Auto'
    X(f'{indent}\t\t<OnMainServerUnavalableBehavior>{osu}</OnMainServerUnavalableBehavior>')
    X(f'{indent}\t</Properties>')
    X(f'{indent}</Command>')


def collect_commands(raw):
    """`commands` accepts a list of {name, ...} or a {name: {...}} mapping."""
    if not raw:
        return []
    if isinstance(raw, dict):
        return [(k, v) for k, v in raw.items()]
    return [(str(c.get('name')), c) for c in raw]


def emit_common_attribute_properties(indent):
    i = indent
    _head(i)
    # The type defaults to String(0) — NOT defn['type'], which is the metadata
    # object kind ("CommonAttribute").
    vt = str(defn['valueType']) if defn.get('valueType') else 'String(0)'
    emit_value_type(i, vt)
    X(f'{i}<PasswordMode>{"true" if get_bool_prop("passwordMode", False) else "false"}</PasswordMode>')
    emit_mltext(i, 'Format', defn.get('format'))
    emit_mltext(i, 'EditFormat', defn.get('editFormat'))
    emit_mltext(i, 'ToolTip', defn.get('tooltip'))
    X(f'{i}<MarkNegatives>{"true" if get_bool_prop("markNegatives", False) else "false"}</MarkNegatives>')
    if defn.get('mask'):
        X(f'{i}<Mask>{meta_dsl.esc_xml_text(defn["mask"])}</Mask>')
    else:
        X(f'{i}<Mask/>')
    X(f'{i}<MultiLine>{"true" if get_bool_prop("multiLine", False) else "false"}</MultiLine>')
    X(f'{i}<ExtendedEdit>{"true" if get_bool_prop("extendedEdit", False) else "false"}</ExtendedEdit>')
    emit_min_max_value(i, 'MinValue', defn.get('minValue'))
    emit_min_max_value(i, 'MaxValue', defn.get('maxValue'))
    ffv = 'true' if get_bool_prop('fillFromFillingValue', False) else 'false'
    X(f'{i}<FillFromFillingValue>{ffv}</FillFromFillingValue>')
    if defn.get('fillValue') is not None:
        X(f'{i}{meta_dsl.build_fill_value_explicit_xml(vt, defn["fillValue"])}')
    else:
        emit_fill_value(i, vt)
    X(f'{i}<FillChecking>{get_enum_prop("FillChecking", "fillChecking", "DontCheck")}</FillChecking>')
    X(f'{i}<ChoiceFoldersAndItems>'
      f'{get_enum_prop("ChoiceFoldersAndItems", "choiceFoldersAndItems", "Items")}</ChoiceFoldersAndItems>')
    emit_choice_parameter_links(i, defn.get('choiceParameterLinks'))
    emit_choice_parameters(i, defn.get('choiceParameters'))
    X(f'{i}<QuickChoice>{get_enum_prop("QuickChoice", "quickChoice", "Auto")}</QuickChoice>')
    X(f'{i}<CreateOnInput>{get_enum_prop("CreateOnInput", "createOnInput", "Auto")}</CreateOnInput>')
    if defn.get('choiceForm'):
        X(f'{i}<ChoiceForm>{esc_xml(str(defn["choiceForm"]))}</ChoiceForm>')
    else:
        X(f'{i}<ChoiceForm/>')
    emit_link_by_type(i, defn.get('linkByType'))
    X(f'{i}<ChoiceHistoryOnInput>'
      f'{get_enum_prop("ChoiceHistoryOnInput", "choiceHistoryOnInput", "Auto")}</ChoiceHistoryOnInput>')

    # Content — the objects the common attribute was added to
    content = defn.get('content') or []
    if content:
        X(f'{i}<Content>')
        for c in content:
            md = c if isinstance(c, str) else str(c.get('metadata', ''))
            use = 'Use' if isinstance(c, str) else str(c.get('use') or 'Use')
            cs = '' if isinstance(c, str) else str(c.get('conditionalSeparation') or '')
            X(f'{i}\t<xr:Item>')
            X(f'{i}\t\t<xr:Metadata>{esc_xml(meta_dsl.normalize_md_object_ref(md))}</xr:Metadata>')
            X(f'{i}\t\t<xr:Use>{use}</xr:Use>')
            if cs:
                X(f'{i}\t\t<xr:ConditionalSeparation>{esc_xml(cs)}</xr:ConditionalSeparation>')
            else:
                X(f'{i}\t\t<xr:ConditionalSeparation/>')
            X(f'{i}\t</xr:Item>')
        X(f'{i}</Content>')
    else:
        X(f'{i}<Content/>')

    X(f'{i}<AutoUse>{get_enum_prop("AutoUse", "autoUse", "DontUse")}</AutoUse>')
    X(f'{i}<DataSeparation>{get_enum_prop("DataSeparation", "dataSeparation", "DontUse")}</DataSeparation>')
    X(f'{i}<SeparatedDataUse>'
      f'{get_enum_prop("SeparatedDataUse", "separatedDataUse", "Independently")}</SeparatedDataUse>')
    emit_verbatim_ref(i, 'DataSeparationValue', defn.get('dataSeparationValue'))
    emit_verbatim_ref(i, 'DataSeparationUse', defn.get('dataSeparationUse'))
    emit_verbatim_ref(i, 'ConditionalSeparation', defn.get('conditionalSeparation'))
    X(f'{i}<UsersSeparation>{get_enum_prop("UsersSeparation", "usersSeparation", "DontUse")}</UsersSeparation>')
    X(f'{i}<AuthenticationSeparation>'
      f'{get_enum_prop("AuthenticationSeparation", "authenticationSeparation", "DontUse")}'
      f'</AuthenticationSeparation>')
    X(f'{i}<ConfigurationExtensionsSeparation>'
      f'{get_enum_prop("ConfigurationExtensionsSeparation", "configurationExtensionsSeparation", "DontUse")}'
      f'</ConfigurationExtensionsSeparation>')
    X(f'{i}<Indexing>{get_enum_prop("Indexing", "indexing", "DontIndex")}</Indexing>')
    X(f'{i}<FullTextSearch>{get_enum_prop("FullTextSearch", "fullTextSearch", "Use")}</FullTextSearch>')
    X(f'{i}<DataHistory>{get_enum_prop("DataHistory", "dataHistory", "Use")}</DataHistory>')


def emit_common_command_properties(indent):
    i = indent
    _head(i)
    emit_verbatim_ref(i, 'Group', defn.get('group'))
    X(f'{i}<Representation>{get_enum_prop("Representation", "representation", "Auto")}</Representation>')
    emit_mltext(i, 'ToolTip', defn.get('tooltip'))
    emit_command_picture(i, defn)
    emit_verbatim_ref(i, 'Shortcut', defn.get('shortcut'))
    incl_help = 'true' if get_bool_prop('includeHelpInContents', False) else 'false'
    X(f'{i}<IncludeHelpInContents>{incl_help}</IncludeHelpInContents>')
    if defn.get('commandParameterType'):
        X(f'{i}<CommandParameterType>')
        emit_type_content(f'{i}\t', str(defn['commandParameterType']))
        X(f'{i}</CommandParameterType>')
    else:
        X(f'{i}<CommandParameterType/>')
    X(f'{i}<ParameterUseMode>{get_enum_prop("ParameterUseMode", "parameterUseMode", "Single")}</ParameterUseMode>')
    X(f'{i}<ModifiesData>{"true" if get_bool_prop("modifiesData", False) else "false"}</ModifiesData>')
    X(f'{i}<OnMainServerUnavalableBehavior>'
      f'{get_enum_prop("OnMainServerUnavalableBehavior", "onMainServerUnavalableBehavior", "Auto")}'
      f'</OnMainServerUnavalableBehavior>')


def emit_common_form_properties(indent):
    i = indent
    _head(i)
    X(f'{i}<FormType>{get_enum_prop("FormType", "formType", "Managed")}</FormType>')
    incl_help = 'true' if get_bool_prop('includeHelpInContents', False) else 'false'
    X(f'{i}<IncludeHelpInContents>{incl_help}</IncludeHelpInContents>')
    # UsePurposes — which applications the form is used in
    purposes = list(defn['usePurposes']) if defn.get('usePurposes') else \
        ['PlatformApplication', 'MobilePlatformApplication']
    if purposes:
        X(f'{i}<UsePurposes>')
        for p in purposes:
            X(f'{i}\t<v8:Value xsi:type="app:ApplicationUsePurpose">{p}</v8:Value>')
        X(f'{i}</UsePurposes>')
    else:
        X(f'{i}<UsePurposes/>')
    use_std_cmds = 'true' if get_bool_prop('useStandardCommands', False) else 'false'
    X(f'{i}<UseStandardCommands>{use_std_cmds}</UseStandardCommands>')
    emit_mltext(i, 'ExtendedPresentation', defn.get('extendedPresentation'))
    emit_mltext(i, 'Explanation', defn.get('explanation'))


def emit_common_picture_properties(indent):
    i = indent
    _head(i)
    afc = 'true' if get_bool_prop('availabilityForChoice', False) else 'false'
    afa = 'true' if get_bool_prop('availabilityForAppearance', False) else 'false'
    X(f'{i}<AvailabilityForChoice>{afc}</AvailabilityForChoice>')
    X(f'{i}<AvailabilityForAppearance>{afa}</AvailabilityForAppearance>')


def emit_common_template_properties(indent):
    i = indent
    _head(i)
    X(f'{i}<TemplateType>'
      f'{get_enum_prop("TemplateType", "templateType", "SpreadsheetDocument")}</TemplateType>')


def emit_session_parameter_properties(indent):
    _head(indent)
    _value_type_or_empty(indent)


def emit_settings_storage_properties(indent):
    i = indent
    _head(i)
    for tag, key in (('DefaultSaveForm', 'defaultSaveForm'),
                     ('DefaultLoadForm', 'defaultLoadForm'),
                     ('AuxiliarySaveForm', 'auxiliarySaveForm'),
                     ('AuxiliaryLoadForm', 'auxiliaryLoadForm')):
        emit_verbatim_ref(i, tag, defn.get(key))


def emit_ws_reference_properties(indent):
    i = indent
    _head(i)
    url = defn.get('locationURL') or defn.get('locationUrl') or ''
    if url:
        X(f'{i}<LocationURL>{meta_dsl.esc_xml_text(url)}</LocationURL>')
    else:
        X(f'{i}<LocationURL/>')


def emit_document_numerator_properties(indent):
    i = indent
    _head(i)
    number_length = str(defn['numberLength']) if defn.get('numberLength') is not None else '11'
    X(f'{i}<NumberType>{get_enum_prop("NumberType", "numberType", "String")}</NumberType>')
    X(f'{i}<NumberLength>{number_length}</NumberLength>')
    X(f'{i}<NumberAllowedLength>'
      f'{get_enum_prop("NumberAllowedLength", "numberAllowedLength", "Variable")}</NumberAllowedLength>')
    X(f'{i}<NumberPeriodicity>'
      f'{get_enum_prop("NumberPeriodicity", "numberPeriodicity", "Year")}</NumberPeriodicity>')
    X(f'{i}<CheckUnique>{"true" if get_bool_prop("checkUnique", True) else "false"}</CheckUnique>')


def emit_filter_criterion_properties(indent):
    i = indent
    _head(i)
    _value_type_or_empty(i)
    use_std_cmds = 'true' if get_bool_prop('useStandardCommands', True) else 'false'
    X(f'{i}<UseStandardCommands>{use_std_cmds}</UseStandardCommands>')
    # Content — the attributes the criterion filters on
    emit_md_ref_list(i, 'Content', defn.get('content'))
    emit_verbatim_ref(i, 'DefaultForm', defn.get('defaultForm'))
    emit_verbatim_ref(i, 'AuxiliaryForm', defn.get('auxiliaryForm'))
    for tag, key in (('ListPresentation', 'listPresentation'),
                     ('ExtendedListPresentation', 'extendedListPresentation'),
                     ('Explanation', 'explanation')):
        emit_mltext(i, tag, defn.get(key))


def emit_functional_option_properties(indent):
    i = indent
    _head(i)
    # Location — where the option's value is stored (Constant.X /
    # InformationRegister.X.Resource.Y / <Kind>.X.Attribute.Y). Accepts
    # `location` or `value`.
    loc = defn.get('location') or defn.get('value') or ''
    if loc:
        X(f'{i}<Location>{esc_xml(meta_dsl.normalize_md_object_ref(str(loc)))}</Location>')
    else:
        X(f'{i}<Location/>')
    # PrivilegedGetMode defaults to true (the whole reference corpus has it set).
    pgm = 'true' if get_bool_prop('privilegedGetMode', True) else 'false'
    X(f'{i}<PrivilegedGetMode>{pgm}</PrivilegedGetMode>')
    # Content — the objects that depend on the option
    content = defn.get('content') or []
    if content:
        X(f'{i}<Content>')
        for obj in content:
            X(f'{i}\t<xr:Object>{esc_xml(meta_dsl.normalize_md_object_ref(str(obj)))}</xr:Object>')
        X(f'{i}</Content>')
    else:
        X(f'{i}<Content/>')


def emit_functional_options_parameter_properties(indent):
    i = indent
    _head(i)
    # Use — the register dimensions / attributes the parameter is bound to
    emit_md_ref_list(i, 'Use', defn.get('use'))


def emit_sequence_properties(indent):
    i = indent
    _head(i)
    X(f'{i}<MoveBoundaryOnPosting>'
      f'{get_enum_prop("MoveBoundaryOnPosting", "moveBoundaryOnPosting", "DontMove")}'
      f'</MoveBoundaryOnPosting>')
    emit_md_ref_list(i, 'Documents', defn.get('documents'))
    emit_md_ref_list(i, 'RegisterRecords', defn.get('registerRecords'))
    X(f'{i}<DataLockControlMode>'
      f'{get_enum_prop("DataLockControlMode", "dataLockControlMode", "Managed")}</DataLockControlMode>')


def emit_command_group_properties(indent):
    i = indent
    _head(i)
    X(f'{i}<Representation>{get_enum_prop("Representation", "representation", "Auto")}</Representation>')
    emit_mltext(i, 'ToolTip', defn.get('tooltip'))
    emit_command_picture(i, defn)
    X(f'{i}<Category>{get_enum_prop("Category", "category", "NavigationPanel")}</Category>')


def emit_sequence_dimension(indent, dim_def):
    """A dimension of a Sequence — like a register dimension, plus the
    DocumentMap / RegisterRecordsMap reference lists."""
    parsed = parse_attribute_shorthand(dim_def)
    X(f'{indent}<Dimension uuid="{new_uuid()}">')
    X(f'{indent}\t<Properties>')
    X(f'{indent}\t\t<Name>{esc_xml(parsed["name"])}</Name>')
    emit_mltext(f'{indent}\t\t', 'Synonym', parsed.get('synonym'))
    if parsed.get('comment'):
        X(f'{indent}\t\t<Comment>{meta_dsl.esc_xml_text(parsed["comment"])}</Comment>')
    else:
        X(f'{indent}\t\t<Comment/>')
    if parsed.get('typeEmpty') or not parsed.get('type'):
        X(f'{indent}\t\t<Type/>')
    else:
        emit_value_type(f'{indent}\t\t', parsed['type'])
    dm = None if isinstance(dim_def, str) else dim_def.get('documentMap')
    rrm = None if isinstance(dim_def, str) else dim_def.get('registerRecordsMap')
    emit_md_ref_list(f'{indent}\t\t', 'DocumentMap', dm)
    emit_md_ref_list(f'{indent}\t\t', 'RegisterRecordsMap', rrm)
    X(f'{indent}\t</Properties>')
    X(f'{indent}</Dimension>')



X('<?xml version="1.0" encoding="UTF-8"?>')
X(f'<MetaDataObject {xmlns_decl} version="{format_version}">')
X(f'\t<{obj_type} uuid="{obj_uuid}">')

# InternalInfo
emit_internal_info('\t\t', obj_type, obj_name)

# Properties
X('\t\t<Properties>')

property_emitters = {
    'Catalog': emit_catalog_properties,
    'Document': emit_document_properties,
    'Enum': emit_enum_properties,
    'Constant': emit_constant_properties,
    'InformationRegister': emit_information_register_properties,
    'AccumulationRegister': emit_accumulation_register_properties,
    'DefinedType': emit_defined_type_properties,
    'CommonModule': emit_common_module_properties,
    'ScheduledJob': emit_scheduled_job_properties,
    'EventSubscription': emit_event_subscription_properties,
    'Report': emit_report_properties,
    'DataProcessor': emit_data_processor_properties,
    'ExchangePlan': emit_exchange_plan_properties,
    'ChartOfCharacteristicTypes': emit_chart_of_characteristic_types_properties,
    'DocumentJournal': emit_document_journal_properties,
    'ChartOfAccounts': emit_chart_of_accounts_properties,
    'AccountingRegister': emit_accounting_register_properties,
    'ChartOfCalculationTypes': emit_chart_of_calculation_types_properties,
    'CalculationRegister': emit_calculation_register_properties,
    'BusinessProcess': emit_business_process_properties,
    'Task': emit_task_properties,
    'HTTPService': emit_http_service_properties,
    'WebService': emit_web_service_properties,
    'CommonAttribute': emit_common_attribute_properties,
    'CommonCommand': emit_common_command_properties,
    'CommonForm': emit_common_form_properties,
    'CommonPicture': emit_common_picture_properties,
    'CommonTemplate': emit_common_template_properties,
    'CommandGroup': emit_command_group_properties,
    'DocumentNumerator': emit_document_numerator_properties,
    'FilterCriterion': emit_filter_criterion_properties,
    'FunctionalOption': emit_functional_option_properties,
    'FunctionalOptionsParameter': emit_functional_options_parameter_properties,
    'Sequence': emit_sequence_properties,
    'SessionParameter': emit_session_parameter_properties,
    'SettingsStorage': emit_settings_storage_properties,
    'WSReference': emit_ws_reference_properties,
}

property_emitters[obj_type]('\t\t\t')

X('\t\t</Properties>')

# ChildObjects
has_children = False

# --- Types with Attributes + TabularSections ---
types_with_attr_ts = [
    'Catalog', 'Document', 'Report', 'DataProcessor', 'ExchangePlan',
    'ChartOfCharacteristicTypes', 'ChartOfAccounts', 'ChartOfCalculationTypes',
    'BusinessProcess', 'Task',
]

if obj_type in types_with_attr_ts:
    def _as_list(val):
        """Normalize attributes: dict {"K":"V"} → ["K:V"], list/other → list."""
        if val is None:
            return []
        if isinstance(val, dict):
            return [f"{k}:{v}" for k, v in val.items()]
        return list(val)

    attrs = []
    if defn.get('attributes'):
        for a in _as_list(defn['attributes']):
            attrs.append(parse_attribute_shorthand(a))
    ts_sections = {}
    ts_order = []
    if defn.get('tabularSections'):
        ts_data = defn['tabularSections']
        if isinstance(ts_data, list):
            for ts in ts_data:
                ts_name = ts['name']
                ts_cols = _as_list(ts.get('attributes', []))
                ts_sections[ts_name] = ts_cols
                ts_order.append(ts_name)
        else:
            for k, v in ts_data.items():
                ts_sections[k] = _as_list(v)
                ts_order.append(k)
    # ChartOfAccounts: AccountingFlags + ExtDimensionAccountingFlags
    acct_flags = []
    ext_dim_flags = []
    if obj_type == 'ChartOfAccounts':
        if defn.get('accountingFlags'):
            acct_flags = _as_list(defn['accountingFlags'])
        if defn.get('extDimensionAccountingFlags'):
            ext_dim_flags = _as_list(defn['extDimensionAccountingFlags'])
    # Task: AddressingAttributes
    addr_attrs = []
    if obj_type == 'Task' and defn.get('addressingAttributes'):
        addr_attrs = _as_list(defn['addressingAttributes'])
    obj_commands = collect_commands(defn.get('commands'))
    child_count = (len(attrs) + len(ts_sections) + len(acct_flags) + len(ext_dim_flags)
                   + len(addr_attrs) + len(obj_commands))
    if child_count > 0:
        has_children = True
        X('\t\t<ChildObjects>')
        if obj_type == 'Catalog':
            context = 'catalog'
        elif obj_type == 'Document':
            context = 'document'
        elif obj_type in ('DataProcessor', 'Report'):
            context = 'processor'
        elif obj_type in ('ChartOfAccounts', 'ChartOfCharacteristicTypes', 'ChartOfCalculationTypes'):
            context = 'chart'
        else:
            context = 'object'
        for a in attrs:
            emit_attribute('\t\t\t', a, context)
        for ts_name in ts_order:
            columns = ts_sections[ts_name]
            emit_tabular_section('\t\t\t', ts_name, columns, obj_type, obj_name)
        for af in acct_flags:
            af_name = af['name'] if isinstance(af, dict) else str(af)
            emit_accounting_flag('\t\t\t', af_name)
        for edf in ext_dim_flags:
            edf_name = edf['name'] if isinstance(edf, dict) else str(edf)
            emit_ext_dimension_accounting_flag('\t\t\t', edf_name)
        for aa in addr_attrs:
            emit_addressing_attribute('\t\t\t', aa)
        for cmd_name, cmd in obj_commands:
            emit_command('\t\t\t', cmd_name, cmd)
        X('\t\t</ChildObjects>')
    else:
        X('\t\t<ChildObjects/>')

# --- Enum: enum values ---
if obj_type == 'Enum':
    values = []
    if defn.get('values'):
        for v in defn['values']:
            values.append(parse_enum_value_shorthand(v))
    if values:
        has_children = True
        X('\t\t<ChildObjects>')
        for v in values:
            emit_enum_value('\t\t\t', v)
        X('\t\t</ChildObjects>')
    else:
        X('\t\t<ChildObjects/>')

# --- Constant, DefinedType, ScheduledJob, EventSubscription: no ChildObjects ---

# --- Registers: dimensions + resources + attributes ---
if obj_type in ('InformationRegister', 'AccumulationRegister', 'AccountingRegister', 'CalculationRegister'):
    dims = []
    resources = []
    reg_attrs = []
    if defn.get('dimensions'):
        for d in defn['dimensions']:
            dims.append(parse_attribute_shorthand(d))
    if defn.get('resources'):
        for r in defn['resources']:
            resources.append(parse_attribute_shorthand(r))
    if defn.get('attributes'):
        for a in defn['attributes']:
            reg_attrs.append(parse_attribute_shorthand(a))
    reg_commands = collect_commands(defn.get('commands'))
    if dims or resources or reg_attrs or reg_commands:
        has_children = True
        X('\t\t<ChildObjects>')
        for r in resources:
            emit_resource('\t\t\t', r, obj_type)
        for d in dims:
            emit_dimension('\t\t\t', d, obj_type)
        # InformationRegister.Attribute supports FillFromFillingValue/FillValue/DataHistory;
        # AccumulationRegister/AccountingRegister/CalculationRegister.Attribute do NOT.
        reg_ctx = 'register-info' if obj_type == 'InformationRegister' else 'register-other'
        for a in reg_attrs:
            emit_attribute('\t\t\t', a, reg_ctx)
        for cmd_name, cmd in reg_commands:
            emit_command('\t\t\t', cmd_name, cmd)
        X('\t\t</ChildObjects>')
    else:
        X('\t\t<ChildObjects/>')

# --- DocumentJournal: columns ---
if obj_type == 'DocumentJournal':
    columns = list(defn.get('columns', []))
    dj_commands = collect_commands(defn.get('commands'))
    if columns or dj_commands:
        has_children = True
        X('\t\t<ChildObjects>')
        for col in columns:
            emit_column('\t\t\t', col)
        for cmd_name, cmd in dj_commands:
            emit_command('\t\t\t', cmd_name, cmd)
        X('\t\t</ChildObjects>')
    else:
        X('\t\t<ChildObjects/>')

# --- HTTPService: URLTemplates ---
if obj_type == 'HTTPService':
    url_templates = {}
    url_tmpl_order = []
    if defn.get('urlTemplates'):
        for k, v in defn['urlTemplates'].items():
            url_templates[k] = v
            url_tmpl_order.append(k)
    if url_templates:
        has_children = True
        X('\t\t<ChildObjects>')
        for tmpl_name in sorted(url_tmpl_order):
            emit_url_template('\t\t\t', tmpl_name, url_templates[tmpl_name])
        X('\t\t</ChildObjects>')
    else:
        X('\t\t<ChildObjects/>')

# --- WebService: Operations ---
if obj_type == 'WebService':
    operations = {}
    op_order = []
    if defn.get('operations'):
        for k, v in defn['operations'].items():
            operations[k] = v
            op_order.append(k)
    if operations:
        has_children = True
        X('\t\t<ChildObjects>')
        for op_name in sorted(op_order):
            emit_operation('\t\t\t', op_name, operations[op_name])
        X('\t\t</ChildObjects>')
    else:
        X('\t\t<ChildObjects/>')

# --- Sequence: dimensions ---
if obj_type == 'Sequence':
    seq_dims = list(defn.get('dimensions') or [])
    if seq_dims:
        has_children = True
        X('\t\t<ChildObjects>')
        for d in seq_dims:
            emit_sequence_dimension('\t\t\t', d)
        X('\t\t</ChildObjects>')
    else:
        X('\t\t<ChildObjects/>')

# --- Types carrying no child objects at all: emit the empty element so the
# --- file still matches the schema.
if obj_type in ('FilterCriterion', 'SettingsStorage'):
    fc_commands = collect_commands(defn.get('commands'))
    if fc_commands:
        has_children = True
        X('\t\t<ChildObjects>')
        for cmd_name, cmd in fc_commands:
            emit_command('\t\t\t', cmd_name, cmd)
        X('\t\t</ChildObjects>')
    else:
        X('\t\t<ChildObjects/>')

if obj_type in ('CommonAttribute', 'CommonCommand', 'CommonForm', 'CommonPicture',
                'CommonTemplate', 'CommandGroup', 'DocumentNumerator', 'FunctionalOption',
                'FunctionalOptionsParameter', 'SessionParameter', 'WSReference'):
    X('\t\t<ChildObjects/>')

# --- CommonModule: no ChildObjects ---

X(f'\t</{obj_type}>')
X('</MetaDataObject>')

metadata_xml = '\n'.join(lines) + '\n'

# ---------------------------------------------------------------------------
# 16. Write files
# ---------------------------------------------------------------------------

type_plural_map = {
    'Catalog': 'Catalogs',
    'Document': 'Documents',
    'Enum': 'Enums',
    'Constant': 'Constants',
    'InformationRegister': 'InformationRegisters',
    'AccumulationRegister': 'AccumulationRegisters',
    'AccountingRegister': 'AccountingRegisters',
    'CalculationRegister': 'CalculationRegisters',
    'ChartOfAccounts': 'ChartsOfAccounts',
    'ChartOfCharacteristicTypes': 'ChartsOfCharacteristicTypes',
    'ChartOfCalculationTypes': 'ChartsOfCalculationTypes',
    'BusinessProcess': 'BusinessProcesses',
    'Task': 'Tasks',
    'ExchangePlan': 'ExchangePlans',
    'DocumentJournal': 'DocumentJournals',
    'Report': 'Reports',
    'DataProcessor': 'DataProcessors',
    'CommonModule': 'CommonModules',
    'ScheduledJob': 'ScheduledJobs',
    'EventSubscription': 'EventSubscriptions',
    'HTTPService': 'HTTPServices',
    'WebService': 'WebServices',
    'DefinedType': 'DefinedTypes',
    'FunctionalOption': 'FunctionalOptions',
    'Sequence': 'Sequences',
    'FilterCriterion': 'FilterCriteria',
    'DocumentNumerator': 'DocumentNumerators',
    'SettingsStorage': 'SettingsStorages',
    'CommonForm': 'CommonForms',
    'SessionParameter': 'SessionParameters',
    'CommonCommand': 'CommonCommands',
    'CommandGroup': 'CommandGroups',
    'CommonAttribute': 'CommonAttributes',
    'FunctionalOptionsParameter': 'FunctionalOptionsParameters',
    'WSReference': 'WSReferences',
    'CommonPicture': 'CommonPictures',
    'CommonTemplate': 'CommonTemplates',
}

type_plural = type_plural_map[obj_type]
type_dir = os.path.join(output_dir, type_plural)

# Main XML file
main_xml_path = os.path.join(type_dir, f'{obj_name}.xml')

# Types that don't have subdirectory structure
types_no_sub_dir = ['DefinedType', 'ScheduledJob', 'EventSubscription']

obj_sub_dir = os.path.join(type_dir, obj_name)
ext_dir = os.path.join(obj_sub_dir, 'Ext')

os.makedirs(type_dir, exist_ok=True)
if obj_type not in types_no_sub_dir:
    os.makedirs(obj_sub_dir, exist_ok=True)

write_utf8_bom(main_xml_path, metadata_xml)

# Module files
modules_created = []

types_with_object_module = [
    'Catalog', 'Document', 'Report', 'DataProcessor', 'ExchangePlan',
    'ChartOfAccounts', 'ChartOfCharacteristicTypes', 'ChartOfCalculationTypes',
    'BusinessProcess', 'Task',
]
types_with_record_set_module = [
    'InformationRegister', 'AccumulationRegister', 'AccountingRegister', 'CalculationRegister',
]
types_with_manager_module = ['Report', 'DataProcessor', 'Constant', 'Enum']
types_with_value_manager_module = ['Constant']
types_with_module = ['CommonModule', 'HTTPService', 'WebService']

# ---------------------------------------------------------------------------
# Predefined data (Ext/Predefined.xml): catalogs / characteristic kinds,
# accounts, calculation types.
# ---------------------------------------------------------------------------

PREDEF_ROOT_BY_TYPE = {
    'Catalog': 'CatalogPredefinedItems',
    'ChartOfCharacteristicTypes': 'PlanOfCharacteristicKindPredefinedItems',
}
SUBCONTO_TURNOVER_TOKENS = ('turnover', 'толькообороты', 'только обороты', 'оборотный')
PREDEF_HEADER = (
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    '<PredefinedData xmlns="http://v8.1c.ru/8.3/xcf/predef" '
    'xmlns:v8="http://v8.1c.ru/8.1/data/core" '
    'xmlns:xr="http://v8.1c.ru/8.3/xcf/readable" '
    'xmlns:xs="http://www.w3.org/2001/XMLSchema" '
    'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
    'xsi:type="{xsi_type}" version="{version}">\n'
)


def predef_get(o, keys):
    if isinstance(o, dict):
        for k in keys:
            if k in o:
                return o[k]
    return None


def resolve_predef_item(val):
    """Grammar "(Code) Name [Description]: Type", or the object form with
    Russian key synonyms. `type` is the value type of a predefined
    characteristic: None -> no block, '' -> empty <Type/>, 'A + B' -> filled."""
    if isinstance(val, str):
        s = val
        type_ = None
        desc_raw = None
        has_desc = False
        m = re.search(r'\[(.*)\]', s)
        if m:
            desc_raw = m.group(1)
            has_desc = True
            s = re.sub(r'\s*\[.*\]', '', s)
        if ':' in s:
            s, type_ = s.split(':', 1)
            type_ = type_.strip()
        m = re.match(r'^\s*(?:\(([^)]*)\)\s*)?(\S+)\s*$', s.strip())
        name = m.group(2) if m else s.strip()
        code = m.group(1) if (m and m.group(1) is not None) else ''
        desc = desc_raw if has_desc else split_camel_case(name)
        return {'name': name, 'code': code, 'desc': desc, 'isFolder': False,
                'children': [], 'type': type_}

    name = str(predef_get(val, ['name', 'имя']) or '')
    code_v = predef_get(val, ['code', 'код'])
    code = str(code_v) if code_v is not None else ''
    has_desc = isinstance(val, dict) and ('description' in val or 'наименование' in val)
    desc_v = predef_get(val, ['description', 'наименование'])
    desc = str(desc_v) if has_desc else split_camel_case(name)
    is_folder = predef_get(val, ['isFolder', 'группа']) is True
    subs = predef_get(val, ['childItems', 'подчиненные'])
    type_v = predef_get(val, ['type', 'тип'])
    if isinstance(type_v, list):
        type_v = ' + '.join(str(t) for t in type_v)
    return {'name': name, 'code': code, 'desc': desc, 'isFolder': is_folder,
            'children': list(subs) if subs else [], 'type': type_v}


def _capture_type_content(indent, type_str):
    """emit_type_content writes through X(); capture it into a string instead."""
    global lines
    saved = lines
    lines = []
    try:
        emit_type_content(indent, type_str)
        return ''.join(ln + '\n' for ln in lines)
    finally:
        lines = saved


def emit_predef_item(out, val, indent, code_type):
    r = resolve_predef_item(val)
    out.append(f'{indent}<Item id="{new_uuid()}">\n')
    out.append(f'{indent}\t<Name>{meta_dsl.esc_xml_text(r["name"])}</Name>\n')
    if not r['code']:
        out.append(f'{indent}\t<Code/>\n')
    elif code_type == 'Number':
        out.append(f'{indent}\t<Code xsi:type="xs:decimal">{meta_dsl.esc_xml_text(r["code"])}</Code>\n')
    else:
        out.append(f'{indent}\t<Code>{meta_dsl.esc_xml_text(r["code"])}</Code>\n')
    if r['desc'] == '':
        out.append(f'{indent}\t<Description/>\n')
    else:
        out.append(f'{indent}\t<Description>{meta_dsl.esc_xml_text(r["desc"])}</Description>\n')
    # Type sits between Description and IsFolder (characteristic kinds only).
    if r['type'] is not None and str(r['type']) == '':
        out.append(f'{indent}\t<Type/>\n')
    elif r['type']:
        out.append(f'{indent}\t<Type>\n')
        out.append(_capture_type_content(f'{indent}\t\t', str(r['type'])))
        out.append(f'{indent}\t</Type>\n')
    out.append(f'{indent}\t<IsFolder>{"true" if r["isFolder"] else "false"}</IsFolder>\n')
    if r['children']:
        out.append(f'{indent}\t<ChildItems>\n')
        for c in r['children']:
            emit_predef_item(out, c, f'{indent}\t\t', code_type)
        out.append(f'{indent}\t</ChildItems>\n')
    out.append(f'{indent}</Item>\n')


def build_predefined_xml(items, xsi_type, code_type):
    out = [PREDEF_HEADER.format(xsi_type=xsi_type, version=format_version)]
    for it in items:
        emit_predef_item(out, it, '\t', code_type)
    out.append('</PredefinedData>\n')
    return ''.join(out)


def emit_predef_account_flags(out, indent, tag, ref_kind, object_name, flag_names, true_set):
    if not flag_names:
        out.append(f'{indent}<{tag}/>\n')
        return
    true_names = {str(t) for t in (true_set or [])}
    out.append(f'{indent}<{tag}>\n')
    for fn in flag_names:
        v = 'true' if fn in true_names else 'false'
        out.append(f'{indent}\t<Flag ref="ChartOfAccounts.{object_name}.{ref_kind}.{fn}">{v}</Flag>\n')
    out.append(f'{indent}</{tag}>\n')


def emit_predef_account(out, val, indent, object_name, acct_flag_names,
                        ext_dim_flag_names, ext_dim_types_ref=''):
    g = predef_get
    name = str(g(val, ['name', 'имя']) or '')
    code_v = g(val, ['code', 'код'])
    code = str(code_v) if code_v is not None else ''
    has_desc = isinstance(val, dict) and ('description' in val or 'наименование' in val)
    desc_v = g(val, ['description', 'наименование'])
    desc = str(desc_v) if has_desc else split_camel_case(name)
    acct_type = str(g(val, ['accountType', 'видСчета', 'вид']) or '') or 'ActivePassive'
    off = 'true' if g(val, ['offBalance', 'забалансовый']) is True else 'false'
    order = str(g(val, ['order', 'порядок']) or '')
    flags = g(val, ['flags', 'признаки'])
    subconto = g(val, ['subconto', 'extDimensionTypes', 'видыСубконто'])
    children = g(val, ['childItems', 'подчиненные'])

    out.append(f'{indent}<Item id="{new_uuid()}">\n')
    out.append(f'{indent}\t<Name>{meta_dsl.esc_xml_text(name)}</Name>\n')
    out.append(f'{indent}\t<Code/>\n' if not code
               else f'{indent}\t<Code>{meta_dsl.esc_xml_text(code)}</Code>\n')
    out.append(f'{indent}\t<Description/>\n' if desc == ''
               else f'{indent}\t<Description>{meta_dsl.esc_xml_text(desc)}</Description>\n')
    out.append(f'{indent}\t<AccountType>{acct_type}</AccountType>\n')
    out.append(f'{indent}\t<OffBalance>{off}</OffBalance>\n')
    out.append(f'{indent}\t<Order>{meta_dsl.esc_xml_text(order)}</Order>\n')
    emit_predef_account_flags(out, f'{indent}\t', 'AccountingFlags', 'AccountingFlag',
                              object_name, acct_flag_names, flags)

    sub_arr = list(subconto) if subconto else []
    if not sub_arr:
        out.append(f'{indent}\t<ExtDimensionTypes/>\n')
    else:
        out.append(f'{indent}\t<ExtDimensionTypes>\n')
        for sc in sub_arr:
            # String form "Kind | Flag1, Flag2" (flags after |, turnover=false);
            # object form {type, turnover?, flags?}.
            sc_turn_v = None
            sc_flags = None
            if isinstance(sc, str):
                if '|' in sc:
                    head, tail = sc.split('|', 1)
                    sc_type = head.strip()
                    sc_flags = [f.strip() for f in tail.split(',') if f.strip()]
                else:
                    sc_type = sc.strip()
            else:
                sc_type = str(g(sc, ['type', 'тип']) or '')
                sc_turn_v = g(sc, ['turnover', 'толькоОбороты', 'оборотный'])
                sc_flags = g(sc, ['flags', 'признаки'])
            # A bare value name is prefixed with the chart's characteristic-kind
            # reference; a dotted one only gets its type prefix resolved.
            if '.' not in sc_type:
                if ext_dim_types_ref:
                    sc_type = f'{ext_dim_types_ref}.{sc_type}'
            else:
                sc_type = resolve_type_prefix_syn(sc_type)
            # "turnover only" may arrive as a token inside flags — pull it out.
            sc_turn = 'true' if sc_turn_v is True else 'false'
            sc_flags_real = []
            for f in (sc_flags or []):
                if str(f).strip().lower() in SUBCONTO_TURNOVER_TOKENS:
                    sc_turn = 'true'
                else:
                    sc_flags_real.append(f)
            out.append(f'{indent}\t\t<ExtDimensionType name="{esc_xml(sc_type)}">\n')
            out.append(f'{indent}\t\t\t<Turnover>{sc_turn}</Turnover>\n')
            emit_predef_account_flags(out, f'{indent}\t\t\t', 'AccountingFlags',
                                      'ExtDimensionAccountingFlag', object_name,
                                      ext_dim_flag_names, sc_flags_real)
            out.append(f'{indent}\t\t</ExtDimensionType>\n')
        out.append(f'{indent}\t</ExtDimensionTypes>\n')

    child_arr = list(children) if children else []
    if child_arr:
        out.append(f'{indent}\t<ChildItems>\n')
        for c in child_arr:
            emit_predef_account(out, c, f'{indent}\t\t', object_name, acct_flag_names,
                                ext_dim_flag_names, ext_dim_types_ref)
        out.append(f'{indent}\t</ChildItems>\n')
    out.append(f'{indent}</Item>\n')


def build_predefined_account_xml(items, object_name, acct_flag_names,
                                 ext_dim_flag_names, ext_dim_types_ref=''):
    out = [PREDEF_HEADER.format(xsi_type='ChartOfAccountsPredefinedItems', version=format_version)]
    for it in items:
        emit_predef_account(out, it, '\t', object_name, acct_flag_names,
                            ext_dim_flag_names, ext_dim_types_ref)
    out.append('</PredefinedData>\n')
    return ''.join(out)


def emit_predef_calc_type(out, val, indent):
    r = resolve_predef_item(val)
    apib = 'false'
    if not isinstance(val, str):
        if predef_get(val, ['actionPeriodIsBase', 'периодДействияБазовый']) is True:
            apib = 'true'
    out.append(f'{indent}<Item id="{new_uuid()}">\n')
    out.append(f'{indent}\t<Name>{meta_dsl.esc_xml_text(r["name"])}</Name>\n')
    out.append(f'{indent}\t<Code/>\n' if not r['code']
               else f'{indent}\t<Code>{meta_dsl.esc_xml_text(r["code"])}</Code>\n')
    out.append(f'{indent}\t<Description/>\n' if r['desc'] == ''
               else f'{indent}\t<Description>{meta_dsl.esc_xml_text(r["desc"])}</Description>\n')
    out.append(f'{indent}\t<ActionPeriodIsBase>{apib}</ActionPeriodIsBase>\n')
    out.append(f'{indent}</Item>\n')


def build_predefined_calc_type_xml(items):
    out = [PREDEF_HEADER.format(xsi_type='CalculationTypePredefinedItems', version=format_version)]
    for it in items:
        emit_predef_calc_type(out, it, '\t')
    out.append('</PredefinedData>\n')
    return ''.join(out)


def ensure_ext_dir():
    os.makedirs(ext_dir, exist_ok=True)

if obj_type in types_with_object_module:
    module_path = os.path.join(ext_dir, 'ObjectModule.bsl')
    if not os.path.isfile(module_path):
        ensure_ext_dir()
        write_utf8_bom(module_path, '')
        modules_created.append(module_path)

if obj_type in types_with_manager_module:
    module_path = os.path.join(ext_dir, 'ManagerModule.bsl')
    if not os.path.isfile(module_path):
        ensure_ext_dir()
        write_utf8_bom(module_path, '')
        modules_created.append(module_path)

if obj_type in types_with_value_manager_module:
    module_path = os.path.join(ext_dir, 'ValueManagerModule.bsl')
    if not os.path.isfile(module_path):
        ensure_ext_dir()
        write_utf8_bom(module_path, '')
        modules_created.append(module_path)

if obj_type in types_with_record_set_module:
    module_path = os.path.join(ext_dir, 'RecordSetModule.bsl')
    if not os.path.isfile(module_path):
        ensure_ext_dir()
        write_utf8_bom(module_path, '')
        modules_created.append(module_path)

if obj_type in types_with_module:
    module_path = os.path.join(ext_dir, 'Module.bsl')
    if not os.path.isfile(module_path):
        ensure_ext_dir()
        write_utf8_bom(module_path, '')
        modules_created.append(module_path)

# Special files
if obj_type == 'ExchangePlan':
    content_path = os.path.join(ext_dir, 'Content.xml')
    if not os.path.isfile(content_path):
        ensure_ext_dir()
        content_xml = f'<?xml version="1.0" encoding="UTF-8"?>\r\n<ExchangePlanContent xmlns="http://v8.1c.ru/8.3/xcf/extrnprops" xmlns:xr="http://v8.1c.ru/8.3/xcf/readable" version="{format_version}"/>\r\n'
        write_utf8_bom(content_path, content_xml)
        modules_created.append(content_path)

if obj_type == 'BusinessProcess':
    flowchart_path = os.path.join(ext_dir, 'Flowchart.xml')
    if not os.path.isfile(flowchart_path):
        ensure_ext_dir()
        flowchart_xml = f'<?xml version="1.0" encoding="UTF-8"?>\r\n<Flowchart xmlns="http://v8.1c.ru/8.3/MDClasses" version="{format_version}"/>\r\n'
        write_utf8_bom(flowchart_path, flowchart_xml)
        modules_created.append(flowchart_path)

# --- Predefined data (Ext/Predefined.xml). The root element depends on the
# --- object kind; an absent or empty `predefined` key writes no file at all.
predefined_items = list(defn.get('predefined') or [])
if predefined_items:
    predef_xml = None
    if obj_type == 'ChartOfAccounts':
        # Predefined ACCOUNTS have their own grammar: flags are expanded in the
        # order the chart declares them.
        af_names = [parse_attribute_shorthand(af)['name']
                    for af in (defn.get('accountingFlags') or [])]
        edf_names = [parse_attribute_shorthand(edf)['name']
                     for edf in (defn.get('extDimensionAccountingFlags') or [])]
        edt_ref = resolve_type_prefix_syn(str(defn['extDimensionTypes'])) \
            if defn.get('extDimensionTypes') else ''
        predef_xml = build_predefined_account_xml(predefined_items, obj_name,
                                                  af_names, edf_names, edt_ref)
    elif obj_type == 'ChartOfCalculationTypes':
        predef_xml = build_predefined_calc_type_xml(predefined_items)
    elif obj_type in PREDEF_ROOT_BY_TYPE:
        cat_code_type = str(defn['codeType']) if defn.get('codeType') else 'String'
        predef_xml = build_predefined_xml(predefined_items, PREDEF_ROOT_BY_TYPE[obj_type],
                                          cat_code_type)
    if predef_xml is not None:
        ensure_ext_dir()
        predef_path = os.path.join(ext_dir, 'Predefined.xml')
        write_utf8_bom(predef_path, predef_xml)
        modules_created.append(predef_path)

# ---------------------------------------------------------------------------
# 17. Register in Configuration.xml
# ---------------------------------------------------------------------------

config_xml_path = os.path.join(output_dir, 'Configuration.xml')
reg_result = None

child_tag = obj_type

if os.path.isfile(config_xml_path):
    # Parse preserving whitespace via raw string manipulation
    with open(config_xml_path, 'r', encoding='utf-8-sig') as f:
        config_content = f.read()

    ns = 'http://v8.1c.ru/8.3/MDClasses'
    ET.register_namespace('', ns)
    # Parse all namespaces used in the file
    # Use iterparse to collect namespace prefixes
    namespaces_in_file = {}
    for evt, elem in ET.iterparse(config_xml_path, events=['start-ns']):
        prefix, uri = elem
        if prefix:
            namespaces_in_file[prefix] = uri
            ET.register_namespace(prefix, uri)

    tree = ET.parse(config_xml_path)
    root = tree.getroot()

    child_objects = root.find(f'{{{ns}}}Configuration/{{{ns}}}ChildObjects')
    if child_objects is None:
        # Try direct path
        config_elem = root.find(f'{{{ns}}}Configuration')
        if config_elem is not None:
            child_objects = config_elem.find(f'{{{ns}}}ChildObjects')

    if child_objects is not None:
        existing = child_objects.findall(f'{{{ns}}}{child_tag}')
        already_exists = False
        for e in existing:
            if (e.text or '').strip() == obj_name:
                already_exists = True
                break

        if already_exists:
            reg_result = 'already'
        else:
            new_elem = ET.SubElement(child_objects, f'{{{ns}}}{child_tag}')
            new_elem.text = obj_name

            if existing:
                # Insert after last existing element of same type
                last_elem = existing[-1]
                all_children = list(child_objects)
                idx = all_children.index(last_elem)
                child_objects.remove(new_elem)
                child_objects.insert(idx + 1, new_elem)

            # Write back preserving BOM
            tree.write(config_xml_path, encoding='utf-8', xml_declaration=True)
            # Re-read to add BOM, fix declaration quotes, ensure trailing newline
            with open(config_xml_path, 'r', encoding='utf-8') as f:
                raw = f.read()
            if raw.startswith("<?xml version='1.0' encoding='utf-8'?>"):
                raw = raw.replace("<?xml version='1.0' encoding='utf-8'?>", '<?xml version="1.0" encoding="UTF-8"?>', 1)
            if not raw.endswith('\n'):
                raw += '\n'
            write_utf8_bom(config_xml_path, raw)
            reg_result = 'added'
    else:
        reg_result = 'no-childobj'
else:
    reg_result = 'no-config'

# ---------------------------------------------------------------------------
# 18. Summary
# ---------------------------------------------------------------------------

attr_count = len(defn.get('attributes', []))
ts_count = 0
if defn.get('tabularSections'):
    ts_data = defn['tabularSections']
    if isinstance(ts_data, list):
        ts_count = len(ts_data)
    else:
        ts_count = len(ts_data)
dim_count = len(defn.get('dimensions', []))
res_count = len(defn.get('resources', []))
val_count = len(defn.get('values', []))
col_count = len(defn.get('columns', []))

print(f"[OK] {obj_type} '{obj_name}' compiled")
print(f'     UUID: {obj_uuid}')
print(f'     File: {main_xml_path}')

details = []
if attr_count > 0:
    details.append(f'Attributes: {attr_count}')
if ts_count > 0:
    details.append(f'TabularSections: {ts_count}')
if dim_count > 0:
    details.append(f'Dimensions: {dim_count}')
if res_count > 0:
    details.append(f'Resources: {res_count}')
if val_count > 0:
    details.append(f'Values: {val_count}')
if col_count > 0:
    details.append(f'Columns: {col_count}')

if details:
    print(f"     {', '.join(details)}")

for mc in modules_created:
    print(f'     Module: {mc}')

if reg_result == 'added':
    print(f'     Configuration.xml: <{child_tag}>{obj_name}</{child_tag}> added to ChildObjects')
elif reg_result == 'already':
    print(f'     Configuration.xml: <{child_tag}>{obj_name}</{child_tag}> already registered')
elif reg_result == 'no-childobj':
    print('WARNING: Configuration.xml found but <ChildObjects> not found', file=sys.stderr)
elif reg_result == 'no-config':
    print(f'     Configuration.xml: not found at {config_xml_path} (register manually)')

# Cross-reference hints
if obj_type == 'AccountingRegister' and not defn.get('chartOfAccounts'):
    print('[HINT] AccountingRegister requires ChartOfAccounts reference:')
    print('       /meta-edit -Operation modify-property -Value "ChartOfAccounts=ChartOfAccounts.XXX"')
if obj_type == 'CalculationRegister' and not defn.get('chartOfCalculationTypes'):
    print('[HINT] CalculationRegister requires ChartOfCalculationTypes reference:')
    print('       /meta-edit -Operation modify-property -Value "ChartOfCalculationTypes=ChartOfCalculationTypes.XXX"')
if obj_type == 'BusinessProcess' and not defn.get('task'):
    print('[HINT] BusinessProcess requires Task reference:')
    print('       /meta-edit -Operation modify-property -Value "Task=Task.XXX"')
if obj_type == 'ChartOfAccounts':
    max_ext_dim = int(defn['maxExtDimensionCount']) if defn.get('maxExtDimensionCount') is not None else 0
    if max_ext_dim > 0 and not defn.get('extDimensionTypes'):
        print('[HINT] ChartOfAccounts with MaxExtDimensionCount>0 requires ExtDimensionTypes:')
        print('       /meta-edit -Operation modify-property -Value "ExtDimensionTypes=ChartOfCharacteristicTypes.XXX"')
