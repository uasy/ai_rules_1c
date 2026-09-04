"""meta_dsl — forgiving-input helpers shared by the 1c-metadata-manage twins.

Ported from the PowerShell tools, where the same helpers are duplicated in each
script. The Python twins keep one implementation here so an upstream change has
a single place to land.

The host script wires its own primitives and the current object context in
before calling anything:

    import meta_dsl
    meta_dsl.ctx.esc_xml = esc_xml
    meta_dsl.ctx.resolve_type_str = resolve_type_str
    meta_dsl.ctx.obj_type = obj_type
    meta_dsl.ctx.obj_name = obj_name

`esc_xml` and `resolve_type_str` differ slightly between the twins (the compiler
resolves type synonyms against its own table), so they are injected rather than
imported.
"""

import re


class _Ctx:
    """Host-provided primitives and the object currently being processed."""
    esc_xml = staticmethod(lambda s: str(s))
    resolve_type_str = staticmethod(lambda s: s)
    obj_type = ""
    obj_name = ""


ctx = _Ctx()


# English -> Russian standard attribute names, and the standard attributes each
# object kind actually has. Used by resolve_std_attr_en / expand_data_path.
RESERVED_ATTR_EN_RU = {
    'Ref': 'Ссылка', 'DeletionMark': 'ПометкаУдаления', 'Code': 'Код',
    'Description': 'Наименование', 'Date': 'Дата', 'Number': 'Номер', 'Posted': 'Проведен',
    'Parent': 'Родитель', 'Owner': 'Владелец', 'IsFolder': 'ЭтоГруппа',
    'Predefined': 'Предопределенный', 'PredefinedDataName': 'ИмяПредопределенныхДанных',
    'Recorder': 'Регистратор', 'Period': 'Период', 'LineNumber': 'НомерСтроки',
    'Active': 'Активность', 'Order': 'Порядок', 'Type': 'Тип', 'OffBalance': 'Забалансовый',
    'Started': 'Стартован', 'Completed': 'Завершен', 'HeadTask': 'ВедущаяЗадача',
    'Executed': 'Выполнена', 'RoutePoint': 'ТочкаМаршрута', 'BusinessProcess': 'БизнесПроцесс',
    'ThisNode': 'ЭтотУзел', 'SentNo': 'НомерОтправленного', 'ReceivedNo': 'НомерПринятого',
    'CalculationType': 'ВидРасчета', 'RegistrationPeriod': 'ПериодРегистрации',
    'ReversingEntry': 'СторноЗапись', 'Account': 'Счет', 'ValueType': 'ТипЗначения',
    'ActionPeriodIsBasic': 'ПериодДействияБазовый',
}

RESERVED_BY_CONTEXT = {
    'catalog': ['Ref', 'DeletionMark', 'Predefined', 'PredefinedDataName', 'Code',
                'Description', 'Owner', 'Parent', 'IsFolder'],
    'document': ['Ref', 'DeletionMark', 'Date', 'Number', 'Posted'],
}


MD_REF_ROOTS = {
    'справочник': 'Catalog', 'документ': 'Document', 'перечисление': 'Enum', 'константа': 'Constant',
    'регистрсведений': 'InformationRegister', 'регистрнакопления': 'AccumulationRegister',
    'регистрбухгалтерии': 'AccountingRegister', 'регистррасчета': 'CalculationRegister',
    'регистррасчёта': 'CalculationRegister',
    'плансчетов': 'ChartOfAccounts', 'планвидовхарактеристик': 'ChartOfCharacteristicTypes',
    'планвидоврасчета': 'ChartOfCalculationTypes', 'планвидоврасчёта': 'ChartOfCalculationTypes',
    'планобмена': 'ExchangePlan', 'бизнеспроцесс': 'BusinessProcess', 'задача': 'Task',
    'журналдокументов': 'DocumentJournal', 'отчет': 'Report', 'отчёт': 'Report',
    'обработка': 'DataProcessor',
    'табличнаячасть': 'TabularSection', 'реквизит': 'Attribute', 'измерение': 'Dimension',
    'ресурс': 'Resource', 'стандартныйреквизит': 'StandardAttribute',
    'значениеперечисления': 'EnumValue', 'команда': 'Command',
    'признакучета': 'AccountingFlag', 'признакучёта': 'AccountingFlag',
    'catalogref': 'Catalog', 'documentref': 'Document', 'enumref': 'Enum',
    'chartofaccountsref': 'ChartOfAccounts', 'chartofcharacteristictypesref': 'ChartOfCharacteristicTypes',
    'chartofcalculationtypesref': 'ChartOfCalculationTypes', 'exchangeplanref': 'ExchangePlan',
    'businessprocessref': 'BusinessProcess', 'taskref': 'Task',
    'справочникссылка': 'Catalog', 'документссылка': 'Document', 'перечислениессылка': 'Enum',
    'плансчетовссылка': 'ChartOfAccounts', 'планвидовхарактеристикссылка': 'ChartOfCharacteristicTypes',
    'планвидоврасчетассылка': 'ChartOfCalculationTypes', 'планвидоврасчётассылка': 'ChartOfCalculationTypes',
    'планобменассылка': 'ExchangePlan', 'бизнеспроцессссылка': 'BusinessProcess',
    'задачассылка': 'Task',
}


def normalize_md_object_ref(ref, default_root=None):
    """default_root is the kind for a BARE name with no dot (owners: "Валюты" -> "Catalog.Валюты")."""
    if not ref:
        return ref
    if "." not in ref:
        return f"{default_root}.{ref}" if default_root else ref
    parts = ref.split(".")
    for k in range(0, len(parts), 2):
        t = MD_REF_ROOTS.get(parts[k].lower())
        if t:
            parts[k] = t
    return ".".join(parts)


# Known object properties (union over the acc+erp 8.3.24 corpus) — the allowlist
# for modify-property. A known but missing property is created; an unknown one
# (a typo) is an error.
def build_min_max_value_xml(tag, val):
    """MinValue / MaxValue — a typed value: nil / xs:string / xs:decimal."""
    if val is None or str(val) == "":
        return f'<{tag} xsi:nil="true"/>'
    t = "xs:string" if isinstance(val, str) else "xs:decimal"
    return f'<{tag} xsi:type="{t}">{ctx.esc_xml(str(val))}</{tag}>'


def get_ch_el_prop(obj, names):
    """First present key from `names` in a dict-like definition, else None."""
    if obj is None:
        return None
    if isinstance(obj, dict):
        for n in names:
            if n in obj:
                return obj[n]
    return None


def resolve_std_attr_en(name):
    """Standard attribute ru/en -> English (Catalog / Document only)."""
    kind = {'Catalog': 'catalog', 'Document': 'document'}.get(ctx.obj_type)
    if not kind:
        return None
    for en in RESERVED_BY_CONTEXT[kind]:
        ru = RESERVED_ATTR_EN_RU.get(en)
        if name.lower() == en.lower() or (ru and name.lower() == ru.lower()):
            return en
    return None


def expand_data_path(dp):
    """Forgiving data-path input: a short attribute name becomes the full object path."""
    if not dp:
        return dp
    s = str(dp)
    if re.search(r"[:/]", s):
        return s
    if re.match(r"^-?\d+$", s):
        return s
    if re.match(r"^(StandardAttribute|Attribute)\.", s):
        return f"{ctx.obj_type}.{ctx.obj_name}.{s}"
    if "." not in s:
        en = resolve_std_attr_en(s)
        if en:
            return f"{ctx.obj_type}.{ctx.obj_name}.StandardAttribute.{en}"
        return f"{ctx.obj_type}.{ctx.obj_name}.Attribute.{s}"
    return s


def parse_ch_link_shorthand(s):
    """"name=path" | "name=path:Clear|DontChange" -> {name, dataPath, valueChange?}."""
    eq = s.find("=")
    if eq < 0:
        return {"name": s.strip()}
    out = {"name": s[:eq].strip()}
    rest = s[eq + 1:].strip()
    m = re.match(r"^(.*):(Clear|DontChange|очистить|неизменять)$", rest, re.I)
    if m:
        out["dataPath"] = m.group(1).strip()
        out["valueChange"] = m.group(2)
    else:
        out["dataPath"] = rest
    return out


def build_link_by_type_xml(indent, spec):
    """LinkByType — {dataPath, linkItem?}. A plain string is the dataPath, linkItem = 0."""
    if not spec:
        return f"{indent}<LinkByType/>"
    if isinstance(spec, str):
        dp, li = spec, 0
    else:
        dp = str(get_ch_el_prop(spec, ['dataPath', 'path', 'путь']) or "")
        li_raw = get_ch_el_prop(spec, ['linkItem', 'элементСвязи'])
        li = li_raw if li_raw is not None else 0
    if not dp:
        return f"{indent}<LinkByType/>"
    dp = expand_data_path(dp)
    return "\r\n".join([
        f"{indent}<LinkByType>",
        f"{indent}\t<xr:DataPath>{ctx.esc_xml(str(dp))}</xr:DataPath>",
        f"{indent}\t<xr:LinkItem>{li}</xr:LinkItem>",
        f"{indent}</LinkByType>",
    ])


def build_choice_parameter_links_xml(indent, cpl):
    """ChoiceParameterLinks — [{name, dataPath, valueChange?}]; valueChange defaults to Clear."""
    items = cpl if isinstance(cpl, list) else ([cpl] if cpl else [])
    if not items:
        return f"{indent}<ChoiceParameterLinks/>"
    out = [f"{indent}<ChoiceParameterLinks>"]
    for lk in items:
        if isinstance(lk, str):
            lk = parse_ch_link_shorthand(lk)
        name = get_ch_el_prop(lk, ['name', 'имя']) or ""
        dp = expand_data_path(get_ch_el_prop(lk, ['dataPath', 'path', 'путь']) or "")
        vc_raw = get_ch_el_prop(lk, ['valueChange', 'режимИзменения'])
        vc = 'Clear'
        if vc_raw:
            low = str(vc_raw).lower()
            if re.match(r"^(clear|очистить|очистка)$", low):
                vc = 'Clear'
            elif re.match(r"^(dontchange|неизменять|неменять|нет)$", low):
                vc = 'DontChange'
            else:
                vc = str(vc_raw)
        out.append(f"{indent}\t<xr:Link>")
        out.append(f"{indent}\t\t<xr:Name>{ctx.esc_xml(str(name))}</xr:Name>")
        out.append(f'{indent}\t\t<xr:DataPath xsi:type="xs:string">{ctx.esc_xml(str(dp))}</xr:DataPath>')
        out.append(f"{indent}\t\t<xr:ValueChange>{vc}</xr:ValueChange>")
        out.append(f"{indent}\t</xr:Link>")
    out.append(f"{indent}</ChoiceParameterLinks>")
    return "\r\n".join(out)


# --- Choice parameter values (ChoiceParameters) ---

FILL_REF_ROOTS = {
    'перечисление': 'Enum', 'справочник': 'Catalog', 'документ': 'Document',
    'плансчетов': 'ChartOfAccounts', 'планвидовхарактеристик': 'ChartOfCharacteristicTypes',
    'планвидоврасчета': 'ChartOfCalculationTypes', 'планвидоврасчёта': 'ChartOfCalculationTypes',
    'планобмена': 'ExchangePlan', 'бизнеспроцесс': 'BusinessProcess', 'задача': 'Task',
    'enum': 'Enum', 'catalog': 'Catalog', 'document': 'Document', 'chartofaccounts': 'ChartOfAccounts',
    'chartofcharacteristictypes': 'ChartOfCharacteristicTypes',
    'chartofcalculationtypes': 'ChartOfCalculationTypes', 'exchangeplan': 'ExchangePlan',
    'businessprocess': 'BusinessProcess', 'task': 'Task',
}
FILL_EMPTY_REF_WORDS = ('emptyref', 'пустаяссылка')
FILL_ENUM_VAL_WORDS = ('enumvalue', 'значениеперечисления')
ACCOUNT_TYPE_VALUES = ('Active', 'Passive', 'ActivePassive')
FILL_REF_KIND_ROOT = {
    'catalogref': 'Catalog', 'documentref': 'Document', 'enumref': 'Enum',
    'chartofaccountsref': 'ChartOfAccounts', 'chartofcharacteristictypesref': 'ChartOfCharacteristicTypes',
    'chartofcalculationtypesref': 'ChartOfCalculationTypes', 'exchangeplanref': 'ExchangePlan',
    'businessprocessref': 'BusinessProcess', 'taskref': 'Task',
}


def to_ch_scalar(s):
    t = str(s).strip()
    if re.match(r"^(true|истина)$", t, re.I):
        return True
    if re.match(r"^(false|ложь)$", t, re.I):
        return False
    if re.match(r"^-?\d+$", t):
        return int(t)
    if re.match(r"^-?\d+\.\d+$", t):
        return float(t)
    return t


def format_fill_num(n):
    if isinstance(n, float):
        return repr(n) if n != int(n) else f"{n:g}"
    return str(n)


def normalize_fill_ref(s):
    if not s:
        return None
    if re.match(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
                r"[0-9a-fA-F]{12}\.[0-9a-fA-F-]+$", s):
        return s
    parts = s.split(".")
    if len(parts) < 2:
        return None
    root = FILL_REF_ROOTS.get(parts[0].lower())
    if not root:
        return None
    type_name = parts[1]
    if root == 'Enum':
        if len(parts) == 2:
            return None
        if len(parts) == 3:
            if parts[2].lower() in FILL_EMPTY_REF_WORDS:
                return f"Enum.{type_name}.EmptyRef"
            return f"Enum.{type_name}.EnumValue.{parts[2]}"
        member = parts[2]
        if member.lower() in FILL_ENUM_VAL_WORDS:
            rest = ".".join(parts[3:])
        else:
            rest = ".".join(parts[2:])
        return f"Enum.{type_name}.EnumValue.{rest}"
    tail = list(parts[1:])
    for i, t in enumerate(tail):
        if t.lower() in FILL_EMPTY_REF_WORDS:
            tail[i] = 'EmptyRef'
    return root + "." + ".".join(tail)


def expand_choice_ref_value(value, type_str):
    if not type_str:
        return None
    t = ctx.resolve_type_str(type_str)
    root = tn = None
    m = re.match(r"^(\w+Ref)\.(.+)$", t)
    if m:
        root = FILL_REF_KIND_ROOT.get(m.group(1).lower())
        tn = m.group(2)
    else:
        m = re.match(r"^([^.]+)\.(.+)$", t)
        if m:
            root = FILL_REF_ROOTS.get(m.group(1).lower())
            tn = m.group(2)
    if not root:
        return None
    if str(value).lower() in FILL_EMPTY_REF_WORDS:
        return f"{root}.{tn}.EmptyRef"
    if root == 'Enum':
        return f"Enum.{tn}.EnumValue.{value}"
    return f"{root}.{tn}.{value}"


def normalize_choice_value(value):
    if isinstance(value, bool):
        return {"XsiType": "xs:boolean", "Text": "true" if value else "false"}
    if isinstance(value, (int, float)):
        return {"XsiType": "xs:decimal", "Text": format_fill_num(value)}
    s = str(value)
    if s == "":
        return {"XsiType": "xs:string", "Text": ""}
    if re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}$", s):
        return {"XsiType": "xs:dateTime", "Text": s}
    ref = normalize_fill_ref(s)
    if ref:
        return {"XsiType": "xr:DesignTimeRef", "Text": ref}
    if s in ACCOUNT_TYPE_VALUES:
        return {"XsiType": "ent:AccountType", "Text": s}
    return {"XsiType": "xs:string", "Text": s}


def normalize_choice_value_t(value, type_str):
    if type_str and isinstance(value, str) and "." not in str(value):
        ex = expand_choice_ref_value(str(value), type_str)
        if ex:
            return {"XsiType": "xr:DesignTimeRef", "Text": ex}
    return normalize_choice_value(value)


def parse_ch_param_shorthand(s):
    eq = s.find("=")
    if eq < 0:
        return {"name": s.strip()}
    name = s[:eq].strip()
    rest = s[eq + 1:]
    if "," in rest:
        return {"name": name, "value": [to_ch_scalar(p) for p in rest.split(",")]}
    return {"name": name, "value": to_ch_scalar(rest)}


def build_choice_parameters_xml(indent, cp):
    """ChoiceParameters — [{name, type?, value?}]. The value goes on app:value
    (xsi:type = its type); a list becomes v8:FixedArray with v8:Value children;
    no value at all -> nil. Requires xmlns:app in import_fragment."""
    items = cp if isinstance(cp, list) else ([cp] if cp else [])
    if not items:
        return f"{indent}<ChoiceParameters/>"
    out = [f"{indent}<ChoiceParameters>"]
    for item in items:
        if isinstance(item, str):
            item = parse_ch_param_shorthand(item)
        name = get_ch_el_prop(item, ['name', 'имя']) or ""
        ptype = get_ch_el_prop(item, ['type', 'тип'])
        has_val = isinstance(item, dict) and ('value' in item or 'значение' in item)
        val = item.get('value', item.get('значение')) if has_val else None
        val_is_array = isinstance(val, (list, tuple))
        out.append(f'{indent}\t<app:item name="{ctx.esc_xml(str(name))}">')
        if not has_val:
            out.append(f'{indent}\t\t<app:value xsi:nil="true"/>')
        elif val_is_array:
            out.append(f'{indent}\t\t<app:value xsi:type="v8:FixedArray">')
            for v in val:
                norm = normalize_choice_value_t(v, ptype)
                if norm["Text"] == "":
                    out.append(f'{indent}\t\t\t<v8:Value xsi:type="{norm["XsiType"]}"/>')
                else:
                    out.append(f'{indent}\t\t\t<v8:Value xsi:type="{norm["XsiType"]}">'
                               f'{ctx.esc_xml(norm["Text"])}</v8:Value>')
            out.append(f"{indent}\t\t</app:value>")
        else:
            norm = normalize_choice_value_t(val, ptype)
            if norm["Text"] == "":
                out.append(f'{indent}\t\t<app:value xsi:type="{norm["XsiType"]}"/>')
            else:
                out.append(f'{indent}\t\t<app:value xsi:type="{norm["XsiType"]}">'
                           f'{ctx.esc_xml(norm["Text"])}</app:value>')
        out.append(f"{indent}\t</app:item>")
    out.append(f"{indent}</ChoiceParameters>")
    return "\r\n".join(out)


# --- Explicit fill value (FillValue) ---

FILL_BOOL_TRUE = ('true', 'истина', 'да')
FILL_BOOL_FALSE = ('false', 'ложь', 'нет')


def esc_xml_text(s):
    """Text-node escaping — unlike esc_xml it leaves quotes alone."""
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def get_fill_type_category(type_str):
    if not type_str:
        return 'String'
    if "+" in type_str:
        return 'Other'
    t = ctx.resolve_type_str(type_str)
    if re.match(r"^Boolean$", t):
        return 'Boolean'
    if re.match(r"^String(\(|$)", t):
        return 'String'
    if re.match(r"^Number(\(|$)", t):
        return 'Number'
    if re.match(r"^(Date|DateTime)$", t):
        return 'Date'
    return 'Other'


def expand_fill_short_ref(s, type_str):
    if not type_str or "+" in type_str:
        return None
    t = ctx.resolve_type_str(type_str)
    m = re.match(r"^(\w+Ref)\.(.+)$", t)
    if not m:
        return None
    root = FILL_REF_KIND_ROOT.get(m.group(1).lower())
    if not root:
        return None
    type_name = m.group(2)
    if s.lower() in FILL_EMPTY_REF_WORDS:
        return f"{root}.{type_name}.EmptyRef"
    if root == 'Enum':
        return f"Enum.{type_name}.EnumValue.{s}"
    return f"{root}.{type_name}.{s}"


def resolve_fill_value_spec(s, type_str):
    cat = get_fill_type_category(type_str)
    if s == "":
        return {"XsiType": "xs:string", "Text": ""}
    if cat == 'String':
        return {"XsiType": "xs:string", "Text": s}
    if cat == 'Boolean' or s.lower() in FILL_BOOL_TRUE or s.lower() in FILL_BOOL_FALSE:
        if s.lower() in FILL_BOOL_TRUE:
            return {"XsiType": "xs:boolean", "Text": "true"}
        if s.lower() in FILL_BOOL_FALSE:
            return {"XsiType": "xs:boolean", "Text": "false"}
    if cat == 'Number':
        return {"XsiType": "xs:decimal", "Text": s}
    if cat == 'Date' or re.match(r"^\d{4}-\d{2}-\d{2}(T\d{2}:\d{2}:\d{2})?$", s):
        if re.match(r"^\d{4}-\d{2}-\d{2}$", s):
            s = f"{s}T00:00:00"
        return {"XsiType": "xs:dateTime", "Text": s}
    ref = normalize_fill_ref(s)
    if ref:
        return {"XsiType": "xr:DesignTimeRef", "Text": ref}
    short = expand_fill_short_ref(s, type_str)
    if short:
        return {"XsiType": "xr:DesignTimeRef", "Text": short}
    return {"XsiType": "xs:string", "Text": s}


def build_fill_value_explicit_xml(type_str, spec):
    """FillValue — an explicit value. Markers {nil} / {emptyRef}; otherwise by type."""
    if spec is None:
        return '<FillValue xsi:nil="true"/>'
    if isinstance(spec, bool):
        return f'<FillValue xsi:type="xs:boolean">{"true" if spec else "false"}</FillValue>'
    if isinstance(spec, (int, float)):
        return f'<FillValue xsi:type="xs:decimal">{format_fill_num(spec)}</FillValue>'
    if get_ch_el_prop(spec, ['nil']) is True:
        return '<FillValue xsi:nil="true"/>'
    if get_ch_el_prop(spec, ['emptyRef', 'пустаяссылка']) is True:
        return '<FillValue xsi:type="xr:DesignTimeRef"/>'
    r = resolve_fill_value_spec(str(spec), type_str)
    if r["Text"] == "" and r["XsiType"] == "xs:string":
        return '<FillValue xsi:type="xs:string"/>'
    return f'<FillValue xsi:type="{r["XsiType"]}">{esc_xml_text(r["Text"])}</FillValue>'


