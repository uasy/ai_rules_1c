#!/usr/bin/env python3
# xdto-info v1.0 — Analyze 1C XDTO package structure
# Licence and attribution: NOTICE.md of the 1c-metadata-manage skill.

import argparse
import os
import sys

from lxml import etree

XS_NS = "http://www.w3.org/2001/XMLSchema"
XSI_NS = "http://www.w3.org/2001/XMLSchema-instance"

out_lines = []


def O(line=""):
    out_lines.append(line)


def fail(msg):
    # A negative search result is not an exception: print the message and exit 1,
    # without a stack trace.
    print(msg)
    sys.exit(1)


def local_name(node):
    return etree.QName(node.tag).localname


def inner_text(node):
    return "".join(node.itertext())


def sort_ordinal(items):
    """PowerShell's Sort-Object sorts by culture, Python's sorted() by code point.
    Both ports sort ordinally so their output matches."""
    return sorted(items)


# --- Type notation: XSD -> 1С ---
XS_TO_1C = {
    "string": "Строка", "normalizedString": "Строка", "token": "Строка", "NCName": "Строка",
    "Name": "Строка", "QName": "Строка", "anyURI": "Строка", "language": "Строка",
    "ID": "Строка", "IDREF": "Строка", "NMTOKEN": "Строка",
    "decimal": "Число", "integer": "Число", "int": "Число", "long": "Число", "short": "Число",
    "byte": "Число", "float": "Число", "double": "Число",
    "nonNegativeInteger": "Число", "positiveInteger": "Число", "nonPositiveInteger": "Число",
    "negativeInteger": "Число", "unsignedInt": "Число", "unsignedLong": "Число",
    "unsignedShort": "Число", "unsignedByte": "Число",
    "date": "Дата", "dateTime": "Дата", "time": "Дата",
    "boolean": "Булево",
    "base64Binary": "ДвоичныеДанные", "hexBinary": "ДвоичныеДанные",
    "anyType": "произвольный", "anySimpleType": "произвольный",
}

FACET_NAMES = ("length", "minLength", "maxLength", "totalDigits", "fractionDigits",
               "minInclusive", "maxInclusive", "minExclusive", "maxExclusive")


def split_ref(el, raw):
    """{ns}Local, prefix:Local or a bare local name -> (ns, local)."""
    if not raw:
        return None
    if raw.startswith("{"):
        close = raw.find("}")
        if close < 0:
            return None
        return {"Ns": raw[1:close], "Local": raw[close + 1:]}
    parts = raw.split(":")
    if len(parts) == 2:
        return {"Ns": el.nsmap.get(parts[0]), "Local": parts[1]}
    return {"Ns": None, "Local": parts[0]}


def get_facets(t):
    res = {}
    for f in FACET_NAMES:
        v = t.get(f)
        if v:
            res[f] = v
    for c in t:
        if isinstance(c.tag, str) and local_name(c) == "pattern":
            res["pattern"] = inner_text(c)
            break
    return res


def get_enumerations(t):
    return [inner_text(c) for c in t
            if isinstance(c.tag, str) and local_name(c) == "enumeration"]


class Index:
    """Package index shared by the resolvers."""
    by_namespace = {}
    packages = []


def find_type(q, pkg):
    if not q:
        return None
    target = None
    if not q["Ns"] or (pkg and q["Ns"] == pkg["Namespace"]):
        target = pkg
    elif q["Ns"] in Index.by_namespace:
        target = Index.by_namespace[q["Ns"]]
    if not target or q["Local"] not in target["Types"]:
        return None
    return {"Element": target["Types"][q["Local"]], "Package": target}


def format_ref_name(q, pkg):
    if not q:
        return ""
    if q["Ns"] == XS_NS:
        return XS_TO_1C.get(q["Local"], f'xs:{q["Local"]}')
    return q["Local"]


def resolve_scalar(t, pkg, guard=0):
    """Unwind an alias chain down to a primitive, collecting facets on the way."""
    acc = {"Base1C": None, "Facets": {}, "Alias": None, "Enum": [], "Kind": "scalar"}
    if guard > 10 or t is None:
        return acc

    variety = t.get("variety")
    if variety == "List":
        it = split_ref(t, t.get("itemType"))
        acc["Kind"] = "list"
        acc["Base1C"] = "список " + (format_ref_name(it, pkg) if it else "значений")
        return acc
    if variety == "Union" or t.get("memberTypes"):
        members = []
        for m in (t.get("memberTypes") or "").split():
            q = split_ref(t, m)
            if q:
                members.append(format_ref_name(q, pkg))
        for c in t:
            if isinstance(c.tag, str) and local_name(c) == "typeDef":
                members.append(resolve_scalar(c, pkg, guard + 1)["Base1C"])
        acc["Kind"] = "union"
        acc["Base1C"] = "одно из (" + " | ".join(m for m in members if m) + ")"
        return acc

    acc["Facets"] = get_facets(t)
    acc["Enum"] = get_enumerations(t)

    # base type: the `base` attribute or a nested anonymous typeDef
    base_q = split_ref(t, t.get("base"))
    anon_base = None
    for c in t:
        if isinstance(c.tag, str) and local_name(c) == "typeDef":
            anon_base = c
            break
    if not base_q and anon_base is not None:
        inner = resolve_scalar(anon_base, pkg, guard + 1)
        acc["Base1C"] = inner["Base1C"]
        for k, v in inner["Facets"].items():
            acc["Facets"].setdefault(k, v)
        if inner["Enum"] and not acc["Enum"]:
            acc["Enum"] = inner["Enum"]
        return acc
    if not base_q:
        acc["Base1C"] = "произвольный"
        return acc

    if base_q["Ns"] == XS_NS:
        acc["Base1C"] = XS_TO_1C.get(base_q["Local"], f'xs:{base_q["Local"]}')
        return acc

    # the base is a named value type — keep unwinding
    target = find_type(base_q, pkg)
    if target and local_name(target["Element"]) == "valueType":
        inner = resolve_scalar(target["Element"], target["Package"], guard + 1)
        acc["Base1C"] = inner["Base1C"]
        for k, v in inner["Facets"].items():
            acc["Facets"].setdefault(k, v)
        if inner["Enum"] and not acc["Enum"]:
            acc["Enum"] = inner["Enum"]
        if not acc["Alias"]:
            acc["Alias"] = base_q["Local"]
        return acc
    acc["Base1C"] = base_q["Local"]
    return acc


def format_scalar(res):
    t = res["Base1C"]
    f = res["Facets"]
    if t == "Строка":
        if "length" in f:
            t = f'Строка({f["length"]})'
        elif "maxLength" in f:
            t = f'Строка({f["maxLength"]})'
    elif t == "Число":
        if "totalDigits" in f:
            frac = f.get("fractionDigits", "0")
            t = f'Число({f["totalDigits"]},{frac})'
    return t or ""


def format_notes(res):
    notes = []
    if res["Alias"]:
        notes.append(f'← {res["Alias"]}')
    if "pattern" in res["Facets"]:
        p = res["Facets"]["pattern"]
        if len(p) > 40:
            p = p[:40] + "…"
        notes.append(f"шаблон {p}")
    for k in ("minInclusive", "maxInclusive", "minExclusive", "maxExclusive"):
        if k in res["Facets"]:
            notes.append(f'{k} {res["Facets"][k]}')
    return notes


# --- Property rendering ---

def get_prop_rows(type_el, pkg, depth, indent, seen):
    rows = []
    for p in type_el:
        if not isinstance(p.tag, str) or local_name(p) != "property":
            continue

        pname = p.get("name")
        if not pname:
            ref_q = split_ref(p, p.get("ref"))
            pname = ref_q["Local"] if ref_q else "(без имени)"
        lower = p.get("lowerBound")
        upper = p.get("upperBound")
        flags = []
        # the model defaults lowerBound to 1; mark the required ones, like meta-info
        if lower != "0":
            flags.append("обязательный")
        if upper == "-1":
            flags.append("список")
        elif upper and upper != "1":
            flags.append(f"до {upper}")
        if p.get("form") == "Text":
            flags.append("значение элемента")

        notes = []
        type_text = ""
        children = None
        child_pkg = pkg
        # A named nested type is fetched like a root one; the detour through the
        # owner property is only needed for an anonymous one — it has no name.
        obj_name = None
        obj_ns = None

        anon = None
        for c in p:
            if isinstance(c.tag, str) and local_name(c) == "typeDef":
                anon = c
                break

        if anon is not None:
            if anon.get(f"{{{XSI_NS}}}type") == "ObjectType":
                type_text = "объект (анонимный)"
                obj_name = "(анонимный)"
                children = anon   # always expanded: there is nowhere else to look
            else:
                res = resolve_scalar(anon, pkg)
                type_text = format_scalar(res)
                notes += format_notes(res)
                if res["Enum"]:
                    notes.append("значения: " + ", ".join(res["Enum"][:8]))
        else:
            q = split_ref(p, p.get("type"))
            if not q:
                type_text = "произвольный"
            elif q["Ns"] == XS_NS:
                type_text = XS_TO_1C.get(q["Local"], f'xs:{q["Local"]}')
            else:
                target = find_type(q, pkg)
                if not target:
                    type_text = f'объект {q["Local"]}'
                    notes.append(f'(пакет не найден: {q["Ns"]})')
                elif local_name(target["Element"]) == "objectType":
                    type_text = f'объект {q["Local"]}'
                    if target["Package"]["Namespace"] != pkg["Namespace"]:
                        type_text += f' · {target["Package"]["Name"]}'
                    obj_name = q["Local"]
                    obj_ns = target["Package"]["Namespace"]
                    children = target["Element"]
                    child_pkg = target["Package"]
                else:
                    res = resolve_scalar(target["Element"], target["Package"])
                    type_text = format_scalar(res)
                    notes.append(f'← {q["Local"]}')
                    notes += [n for n in format_notes(res) if not n.startswith("←")]
                    if res["Enum"]:
                        notes.append("значения: " + ", ".join(res["Enum"][:8]))

        rows.append({"Indent": indent, "Name": pname, "Type": type_text,
                     "Flags": flags, "Notes": [n for n in notes if n],
                     "ObjName": obj_name, "ObjNs": obj_ns})

        if children is not None:
            key = f'{child_pkg["Namespace"]}#{children.get("name")}'
            is_anon = not children.get("name")
            if not is_anon and key in seen:
                rows.append({"Indent": indent + 1, "Name": "(раскрыт выше)", "Type": "",
                             "Flags": [], "Notes": [], "ObjName": None, "ObjNs": None})
            elif is_anon or depth > 1:
                next_seen = set(seen)
                if not is_anon:
                    next_seen.add(key)
                next_depth = depth if is_anon else depth - 1
                rows += get_prop_rows(children, child_pkg, next_depth, indent + 1, next_seen)
    return rows


def select_required(rows):
    """Keep only required properties. A child of an optional object goes too: it
    hangs off an optional branch, so filling it is not required either."""
    res = []
    cut_from = -1
    for r in rows:
        if cut_from >= 0 and r["Indent"] > cut_from:
            continue
        cut_from = -1
        if "обязательный" not in r["Flags"]:
            cut_from = r["Indent"]
            continue
        res.append(r)
    return res


def write_rows(rows, offset, limit):
    if not rows:
        O("  (нет свойств)")
        return
    shown = rows
    if offset > 0 or len(rows) > limit:
        shown = rows[offset:offset + limit]
    w_name = w_type = 0
    for r in shown:
        n = "  " * r["Indent"] + r["Name"]
        w_name = max(w_name, len(n))
        w_type = max(w_type, len(r["Type"]))
    for r in shown:
        n = "  " * r["Indent"] + r["Name"]
        line = "  " + n.ljust(w_name + 2) + r["Type"].ljust(w_type + 2)
        if r["Flags"]:
            line += "[" + ", ".join(r["Flags"]) + "]  "
        if r["Notes"]:
            line += ", ".join(r["Notes"])
        O(line.rstrip())
    if len(rows) > len(shown):
        O(f"  … показано {len(shown)} из {len(rows)}; листать через -Offset/-Limit")


# --- Modes ---

def show_package_list(packages, offset, limit):
    O(f"=== Пакеты XDTO: {len(packages)} ===")
    O("")
    shown = packages
    if offset > 0 or len(packages) > limit:
        shown = packages[offset:offset + limit]
    wn = max((len(p["Name"]) for p in shown), default=0)
    for p in shown:
        O("  " + p["Name"].ljust(wn + 2) + str(len(p["Types"])).rjust(4) + "  " + p["Namespace"])
    if len(packages) > len(shown):
        O("")
        O(f"  … показано {len(shown)} из {len(packages)}; листать через -Offset/-Limit")
    O("")
    O("Колонки: имя пакета, число типов, namespace.")
    O("Следующий шаг: -Package <имя> или -Namespace <URI> — состав пакета; "
      "-Name <Тип> — поиск типа по всем пакетам")


def show_package_overview(pkg):
    O(f'=== Пакет XDTO: {pkg["Name"]} ===')
    O(f'Namespace: {pkg["Namespace"]}')
    if pkg["Imports"]:
        O("")
        O(f'Импорты ({len(pkg["Imports"])}):')
        for i in pkg["Imports"]:
            dep = Index.by_namespace[i]["Name"] if i in Index.by_namespace else "(пакет не найден)"
            O(f"  {i}  →  {dep}")
    if not pkg["GlobalProps"]:
        O("")
        O("Точки входа: нет — пакет не объявляет корневых элементов документа")
    else:
        O("")
        O(f'Точки входа ({len(pkg["GlobalProps"])}) — корневые элементы документа:')
        for gp in pkg["GlobalProps"]:
            q = split_ref(gp, gp.get("type"))
            tn = format_ref_name(q, pkg) if q else "произвольный"
            form = "  (атрибут)" if gp.get("form") == "Attribute" else ""
            O(f'  <{gp.get("name")}>  →  {tn}{form}')

    objs, vals = [], []
    for k in sort_ordinal(pkg["Types"].keys()):
        (objs if local_name(pkg["Types"][k]) == "objectType" else vals).append(k)
    if objs:
        O("")
        O(f"Объектные типы ({len(objs)}):")
        for n in objs:
            cnt = sum(1 for c in pkg["Types"][n]
                      if isinstance(c.tag, str) and local_name(c) == "property")
            base = split_ref(pkg["Types"][n], pkg["Types"][n].get("base"))
            suffix = f'  ← {base["Local"]}' if base else ""
            O("  " + n.ljust(40) + f"свойств: {cnt}" + suffix)
    if vals:
        O("")
        O(f"Типы значений ({len(vals)}):")
        for n in vals:
            res = resolve_scalar(pkg["Types"][n], pkg)
            line = "  " + n.ljust(40) + format_scalar(res)
            if res["Enum"]:
                line += "  значения: " + ", ".join(res["Enum"][:6])
            O(line)
    O("")
    O("Следующий шаг: -Name <Тип> — структура типа для заполнения")


def write_legend(rows):
    """The legend travels with the output instead of living in the docs: only the
    notations that actually occurred are shown, else it becomes noise itself."""
    text = " ".join(r["Type"] + " " + ",".join(r["Flags"]) + " " + ",".join(r["Notes"])
                    for r in rows)
    items = []
    if "объект " in text:
        items.append("объект X — присвоить вложенный объект XDTO, состав раскрывает -Depth")
    if "←" in text:
        items.append("← Имя — исходный тип из схемы, слева от стрелки развёрнутое значение")
    if "список" in text:
        items.append("список — коллекция, заполняется через .Добавить()")
    import re as _re
    if _re.search(r"до \d", text):
        items.append("до N — коллекция с ограничением сверху")
    if "значение элемента" in text:
        items.append("значение элемента — собственное значение узла XML")
    if "·" in text:
        items.append("· Пакет — тип объявлен в другом пакете")
    if not items:
        return
    O("")
    O("Обозначения:")
    for i in items:
        O(f"  {i}")


def show_type(pkg, type_name, depth, required_only, offset, limit):
    el = pkg["Types"][type_name]
    if local_name(el) == "valueType":
        res = resolve_scalar(el, pkg)
        O(f"=== Тип значения XDTO: {type_name} ===")
        O(f'Пакет: {pkg["Name"]} · {pkg["Namespace"]}')
        O("")
        O(f"Значение: {format_scalar(res)}")
        for n in format_notes(res):
            O(f"  {n}")
        if res["Enum"]:
            O("")
            O(f'Допустимые значения ({len(res["Enum"])}):')
            for v in res["Enum"]:
                O(f"  {v}")
        O("")
        O("Создание:")
        # Создать(<Тип>, <Значение>) takes a ТипЗначенияXDTO — this form does not
        # apply to an object type
        O(f'  Значение = ФабрикаXDTO.Создать(ФабрикаXDTO.Тип("{pkg["Namespace"]}", '
          f'"{type_name}"), Значение);')
        return

    hdr = f"=== Тип XDTO: {type_name} ==="
    if depth > 1:
        hdr += f"  (глубина {depth})"
    O(hdr)
    O(f'Пакет: {pkg["Name"]} · {pkg["Namespace"]}')
    base = split_ref(el, el.get("base"))
    if base:
        O(f'Наследует: {base["Local"]}')
    if el.get("abstract") == "true":
        O("Абстрактный — создаётся только тип-наследник")
    if el.get("open") == "true":
        O("Открытый — допускает произвольные элементы и атрибуты")
    O("")

    seen = {f'{pkg["Namespace"]}#{type_name}'}
    rows = get_prop_rows(el, pkg, depth, 0, seen)
    own = [r for r in rows if r["Indent"] == 0]
    if required_only:
        total = len(rows)
        rows = select_required(rows)
        own_req = [r for r in rows if r["Indent"] == 0]
        # The filter must announce itself, else the list reads as complete
        O(f"Свойства: обязательных {len(own_req)} из {len(own)} "
          f"(-RequiredOnly; скрыто строк: {total - len(rows)})")
    else:
        O(f"Свойства ({len(own)}):")
    write_rows(rows, offset, limit)
    write_legend(rows)
    O("")
    O("Создание:")
    O(f'  Тип = ФабрикаXDTO.Тип("{pkg["Namespace"]}", "{type_name}");')
    O("  Объект = ФабрикаXDTO.Создать(Тип);")
    # Recipes for nested and anonymous types: an anonymous type has no name, so
    # ФабрикаXDTO.Тип(ns, имя) cannot reach it — only the owner property can.
    named = next((r for r in rows if r["ObjName"] and r["ObjName"] != "(анонимный)"), None)
    if named:
        O("  // вложенный именованный тип — так же, как корневой:")
        O(f'  {named["Name"]} = ФабрикаXDTO.Создать(ФабрикаXDTO.Тип("{named["ObjNs"]}", '
          f'"{named["ObjName"]}"));')
    anon_row = next((r for r in rows if r["ObjName"] == "(анонимный)"), None)
    if anon_row:
        O("  // у анонимного типа нет имени — только через свойство владельца:")
        O(f'  {anon_row["Name"]} = ФабрикаXDTO.Создать('
          f'Тип.Свойства.Получить("{anon_row["Name"]}").Тип);')
    text_row = next((r for r in rows if "значение элемента" in r["Flags"]), None)
    if text_row:
        O(f'  // собственное значение узла лежит в свойстве {text_row["Name"]}')


def show_used_by(type_name, owner_pkg):
    O(f"=== Ссылки на тип: {type_name} ===")
    if owner_pkg:
        O(f'Объявлен в: {owner_pkg["Name"]} · {owner_pkg["Namespace"]}')
    O("")
    hits = []
    for p in Index.packages:
        for node in p["Root"].iter():
            if not isinstance(node.tag, str):
                continue
            for a in ("type", "base", "itemType", "memberTypes"):
                raw = node.get(a)
                if not raw:
                    continue
                for one in raw.split():
                    q = split_ref(node, one)
                    if not q or q["Local"] != type_name:
                        continue
                    if owner_pkg and q["Ns"] and q["Ns"] != owner_pkg["Namespace"]:
                        continue
                    owner = node
                    while owner is not None and local_name(owner) not in ("objectType", "valueType"):
                        owner = owner.getparent()
                    where = owner.get("name") if (owner is not None and owner.get("name")) \
                        else "(верхний уровень)"
                    what = node.get("name") or local_name(node)
                    hits.append(f'  {p["Name"]}.{where}.{what}  ({a})')
    if not hits:
        O("  Ссылок не найдено")
        return
    O(f"Найдено ({len(hits)}):")
    for h in sort_ordinal(set(hits)):
        O(h)


# --- Package index ---

def read_package(pkg_dir):
    bin_path = os.path.join(pkg_dir, "Ext", "Package.bin")
    if not os.path.isfile(bin_path):
        return None
    try:
        root = etree.parse(bin_path).getroot()
    except Exception:
        return None
    if local_name(root) != "package":
        return None
    info = {
        "Name": os.path.basename(pkg_dir), "Dir": pkg_dir,
        "Namespace": root.get("targetNamespace"), "Root": root,
        "Imports": [], "Types": {}, "GlobalProps": [],
    }
    for n in root:
        if not isinstance(n.tag, str):
            continue
        ln = local_name(n)
        if ln == "import":
            info["Imports"].append(n.get("namespace"))
        elif ln in ("objectType", "valueType"):
            info["Types"][n.get("name")] = n
        elif ln == "property":
            info["GlobalProps"].append(n)
    return info


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Analyze 1C XDTO package structure",
                                     allow_abbrev=False)
    parser.add_argument("-PackagePath", "-Path", dest="PackagePath", required=True)
    parser.add_argument("-Package", default="")
    parser.add_argument("-Namespace", default="")
    parser.add_argument("-Name", default="")
    parser.add_argument("-Mode", default="auto", choices=["auto", "used-by"])
    parser.add_argument("-Depth", type=int, default=1)
    parser.add_argument("-RequiredOnly", action="store_true")
    parser.add_argument("-Limit", type=int, default=150)
    parser.add_argument("-Offset", type=int, default=0)
    parser.add_argument("-OutFile", default="")
    args = parser.parse_args()

    package_path = args.PackagePath
    if not os.path.isabs(package_path):
        package_path = os.path.join(os.getcwd(), package_path)
    if not os.path.exists(package_path):
        fail(f"Путь не найден: {package_path}")

    # The path may point at the configuration root (then all packages are in
    # scope) or at one package.
    config_root = None
    direct_pkg_dir = None
    if os.path.isfile(os.path.join(package_path, "Configuration.xml")):
        config_root = package_path
    elif os.path.basename(package_path.rstrip("/\\")) == "XDTOPackages":
        config_root = os.path.dirname(package_path.rstrip("/\\"))
    elif os.path.isfile(os.path.join(package_path, "Ext", "Package.bin")):
        direct_pkg_dir = package_path
        config_root = os.path.dirname(os.path.dirname(package_path.rstrip("/\\")))
    elif os.path.isfile(package_path) and os.path.basename(package_path) == "Package.bin":
        direct_pkg_dir = os.path.dirname(os.path.dirname(package_path))
        config_root = os.path.dirname(os.path.dirname(direct_pkg_dir))
    elif package_path.endswith(".xml"):
        stem = os.path.join(os.path.dirname(package_path),
                            os.path.splitext(os.path.basename(package_path))[0])
        if os.path.isfile(os.path.join(stem, "Ext", "Package.bin")):
            direct_pkg_dir = stem
            config_root = os.path.dirname(os.path.dirname(stem))
    if not config_root and not direct_pkg_dir:
        fail(f"Не удалось определить пакет или конфигурацию по пути: {package_path}")

    packages = []
    by_namespace = {}
    xdto_dir = os.path.join(config_root, "XDTOPackages") if config_root else None
    if xdto_dir and os.path.isdir(xdto_dir):
        for dn in sort_ordinal(os.listdir(xdto_dir)):
            full = os.path.join(xdto_dir, dn)
            if not os.path.isdir(full):
                continue
            p = read_package(full)
            if p:
                packages.append(p)
                by_namespace.setdefault(p["Namespace"], p)
    if direct_pkg_dir and not packages:
        p = read_package(direct_pkg_dir)
        if p:
            packages.append(p)
            by_namespace[p["Namespace"]] = p
    if not packages:
        fail(f"Пакеты XDTO не найдены: {package_path}")
    Index.packages, Index.by_namespace = packages, by_namespace

    # --- Dispatch: explicit path, then -Namespace / -Package, then a type search ---
    selected = None
    if direct_pkg_dir:
        leaf = os.path.basename(direct_pkg_dir.rstrip("/\\"))
        selected = next((p for p in packages if p["Name"] == leaf), None)
    if not selected and args.Namespace:
        selected = next((p for p in packages if p["Namespace"] == args.Namespace), None)
        if not selected:
            fail(f'Пакет с namespace "{args.Namespace}" не найден. '
                 f"Список: -PackagePath <корень> без параметров")
    if not selected and args.Package:
        selected = next((p for p in packages if p["Name"] == args.Package), None)
        if not selected:
            fail(f'Пакет "{args.Package}" не найден. Список: -PackagePath <корень> без параметров')

    if args.Mode == "used-by":
        if not args.Name:
            fail("Режим used-by требует -Name <Тип>")
        owner_pkg = selected or next((p for p in packages if args.Name in p["Types"]), None)
        show_used_by(args.Name, owner_pkg)
    elif args.Name:
        if not selected:
            found = [p for p in packages if args.Name in p["Types"]]
            if not found:
                fail(f'Тип "{args.Name}" не найден ни в одном пакете конфигурации')
            if len(found) > 1:
                O(f'=== Тип "{args.Name}" найден в нескольких пакетах ({len(found)}) ===')
                O("Уточните через -Namespace или -Package:")
                O("")
                for f in found:
                    O(f'  {f["Name"]}  ·  {f["Namespace"]}')
                flush_output(args.OutFile)
                sys.exit(0)
            selected = found[0]
        if args.Name not in selected["Types"]:
            fail(f'В пакете {selected["Name"]} нет типа "{args.Name}". '
                 f"Список типов: тот же вызов без -Name")
        show_type(selected, args.Name, args.Depth, args.RequiredOnly, args.Offset, args.Limit)
    elif selected:
        show_package_overview(selected)
    else:
        show_package_list(packages, args.Offset, args.Limit)

    flush_output(args.OutFile)
    sys.exit(0)


def flush_output(out_file):
    text = "\n".join(out_lines).rstrip()
    if out_file:
        d = os.path.dirname(out_file)
        if d:
            os.makedirs(d, exist_ok=True)
        with open(out_file, "w", encoding="utf-8-sig", newline="") as f:
            f.write(text + "\r\n")
        print(f"✓ Записано: {out_file}")
    else:
        print(text)


if __name__ == "__main__":
    main()
