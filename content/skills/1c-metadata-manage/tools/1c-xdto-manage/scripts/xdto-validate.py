#!/usr/bin/env python3
# xdto-validate v1.1 — Validate a 1C XDTO package
# Source: https://github.com/Nikolay-Shirokov/cc-1c-skills

import argparse
import os
import sys

from lxml import etree

# Namespaces the platform provides itself — no package in the configuration
# declares them, and none should (derived from the corpus: they are imported,
# but no package carries such a targetNamespace).
PLATFORM_NS = (
    "http://v8.1c.ru/8.1/data/core",
    "http://v8.1c.ru/8.1/data/enterprise",
    "http://v8.1c.ru/8.1/data/enterprise/current-config",
    "http://v8.1c.ru/8.1/data-composition-system/settings",
    "http://v8.1c.ru/8.3/data/ext",
    "http://www.w3.org/2001/XMLSchema",
)

XS_NS = "http://www.w3.org/2001/XMLSchema"
XSI_NS = "http://www.w3.org/2001/XMLSchema-instance"
MD_NS = "http://v8.1c.ru/8.3/MDClasses"

# The model requires import -> property -> valueType -> objectType. The platform
# does not forgive a violation: db-update fails with "Ошибка преобразования
# данных XDTO".
TOP_ORDER = ("import", "property", "valueType", "objectType")


class R:
    errors = 0
    warnings = 0
    ok_count = 0
    stopped = False
    lines = []
    detailed = False
    max_errors = 20


def out_line(s=""):
    R.lines.append(s)


def report_ok(msg):
    R.ok_count += 1
    if R.detailed:
        out_line(f"[OK]    {msg}")


def report_error(msg):
    R.errors += 1
    out_line(f"[ERROR] {msg}")
    if R.errors >= R.max_errors:
        R.stopped = True


def report_warn(msg):
    R.warnings += 1
    out_line(f"[WARN]  {msg}")


def local_name(node):
    return etree.QName(node.tag).localname


def inner_text(node):
    return "".join(node.itertext())


def elements(parent):
    return [c for c in parent if isinstance(c.tag, str)]


def iter_local(root, *names):
    return [e for e in root.iter() if isinstance(e.tag, str) and local_name(e) in names]


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Validate a 1C XDTO package",
                                     allow_abbrev=False)
    parser.add_argument("-PackagePath", "-Path", dest="PackagePath", required=True)
    parser.add_argument("-ConfigDir", default="")
    parser.add_argument("-Detailed", action="store_true")
    parser.add_argument("-MaxErrors", type=int, default=20)
    parser.add_argument("-OutFile", default="")
    args = parser.parse_args()
    R.detailed, R.max_errors = args.Detailed, args.MaxErrors

    package_path = args.PackagePath
    if not os.path.isabs(package_path):
        package_path = os.path.join(os.getcwd(), package_path)

    bin_path = md_path = None
    if os.path.isfile(package_path):
        if os.path.basename(package_path) == "Package.bin":
            bin_path = package_path
            pkg_dir = os.path.dirname(os.path.dirname(package_path))
            if os.path.isfile(pkg_dir + ".xml"):
                md_path = pkg_dir + ".xml"
        elif package_path.endswith(".xml"):
            md_path = package_path
            stem = os.path.join(os.path.dirname(package_path),
                                os.path.splitext(os.path.basename(package_path))[0])
            c = os.path.join(stem, "Ext", "Package.bin")
            if os.path.isfile(c):
                bin_path = c
    elif os.path.isdir(package_path):
        c = os.path.join(package_path, "Ext", "Package.bin")
        if os.path.isfile(c):
            bin_path = c
            m = package_path.rstrip("\\/") + ".xml"
            if os.path.isfile(m):
                md_path = m

    if not bin_path:
        print(f"[ERROR] Не найден Ext/Package.bin для пути: {package_path}")
        sys.exit(1)

    file_name = os.path.basename(os.path.dirname(os.path.dirname(bin_path)))

    # Configuration directory — for the registration and dependency checks
    config_dir = args.ConfigDir
    if not config_dir:
        # .../XDTOPackages/<Имя>/Ext/Package.bin -> .../XDTOPackages -> root
        d = os.path.dirname(os.path.dirname(os.path.dirname(bin_path)))
        config_dir = os.path.dirname(d)

    def finalize():
        checks = R.ok_count + R.errors + R.warnings
        if R.errors == 0 and R.warnings == 0 and not R.detailed:
            result = f"=== Validation OK: {file_name} ({checks} checks) ==="
        else:
            out_line("")
            out_line(f"=== Result: {R.errors} errors, {R.warnings} warnings ({checks} checks) ===")
            result = "\r\n".join(R.lines)
        print(result)
        if args.OutFile:
            with open(args.OutFile, "w", encoding="utf-8-sig", newline="") as f:
                f.write("\r\n".join(R.lines) + "\r\n")

    # --- 1. Well-formedness ---
    try:
        pkg = etree.parse(bin_path).getroot()
    except Exception as e:
        report_error(f"Package.bin не является корректным XML: {e}")
        finalize()
        sys.exit(1)
    if local_name(pkg) != "package":
        report_error(f"Ожидался корневой <package>, найден <{local_name(pkg)}>")
        finalize()
        sys.exit(1)
    report_ok("Package.bin: корректный XML, корень <package>")

    target_ns = pkg.get("targetNamespace")
    if not target_ns:
        report_error("У <package> не задан targetNamespace")
    else:
        report_ok(f"targetNamespace: {target_ns}")

    # --- 2. Encoding / EOL ---
    with open(bin_path, "rb") as f:
        head = f.read(3)
    if head != b"\xef\xbb\xbf":
        report_warn("Package.bin без BOM UTF-8 — платформа пишет файл с BOM")
    else:
        report_ok("Кодировка: UTF-8 с BOM")

    # --- 3. Collect declarations ---
    imports, local_types = [], set()
    object_type_names, value_type_names, global_props = set(), set(), set()
    top_sequence = []
    for n in elements(pkg):
        ln = local_name(n)
        top_sequence.append(ln)
        if ln == "import":
            imports.append(n.get("namespace"))
        elif ln == "objectType":
            local_types.add(n.get("name"))
            object_type_names.add(n.get("name"))
        elif ln == "valueType":
            local_types.add(n.get("name"))
            value_type_names.add(n.get("name"))
        elif ln == "property" and n.get("name") is not None:
            global_props.add(n.get("name"))

    prev_rank, order_ok = -1, True
    for t in top_sequence:
        if t not in TOP_ORDER:
            continue
        rank = TOP_ORDER.index(t)
        if rank < prev_rank:
            report_error(f"Нарушен порядок элементов верхнего уровня: <{t}> после "
                         f"<{TOP_ORDER[prev_rank]}>. Модель требует import -> property -> "
                         f"valueType -> objectType; платформа отвергнет пакет при обновлении "
                         f"конфигурации")
            order_ok = False
            break
        prev_rank = rank
    if order_ok:
        report_ok("Порядок элементов верхнего уровня корректен")

    # --- 4. Duplicate type names ---
    seen = set()
    for n in elements(pkg):
        if local_name(n) not in ("objectType", "valueType"):
            continue
        nm = n.get("name")
        if not nm:
            report_error(f"<{local_name(n)}> без атрибута name")
            continue
        if nm in seen:
            report_error(f"Дублирующееся имя типа: {nm}")
        else:
            seen.add(nm)
    if local_types:
        report_ok(f"{len(local_types)} тип(ов), имена уникальны")

    # --- 5. Type references resolve ---
    used_namespaces, any_type_props = set(), []
    ref_attrs = ("type", "base", "ref", "itemType")

    def resolve_ref(el, attr, raw):
        if not raw:
            return
        if raw.startswith("{"):   # Clark notation {ns}local
            close = raw.find("}")
            if close < 0:
                report_error(f'Некорректная нотация Кларка в {attr}="{raw}"')
                return
            ns, local = raw[1:close], raw[close + 1:]
        else:
            parts = raw.split(":")
            if len(parts) == 2:
                ns, local = el.nsmap.get(parts[0]), parts[1]
                if not ns:
                    report_error(f'Префикс "{parts[0]}" не объявлен: {attr}="{raw}" '
                                 f'(тип {local_name(el)})')
                    return
            else:
                ns, local = None, parts[0]

        if ns in (XS_NS, XSI_NS):
            if local == "anyType":
                any_type_props.append(el)
            return
        if ns == target_ns:
            if attr == "ref":
                if local not in global_props:
                    report_error(f'ref="{raw}" не разрешается: в пакете нет глобального '
                                 f'свойства "{local}"')
            elif local not in local_types:
                report_error(f'{attr}="{raw}" не разрешается: в пакете нет типа "{local}"')
            return
        if ns:
            used_namespaces.add(ns)
            if ns not in imports:
                report_error(f'{attr}="{raw}" ссылается на "{ns}", но '
                             f'<import namespace="{ns}"/> не объявлен')

    node_count = 0
    for el in pkg.iter():
        if not isinstance(el.tag, str):
            continue
        node_count += 1
        for a in ref_attrs:
            if el.get(a) is not None:
                resolve_ref(el, a, el.get(a))
        if el.get("memberTypes") is not None:
            for m in el.get("memberTypes").split():
                resolve_ref(el, "memberTypes", m)
        if R.stopped:
            break
    if not R.stopped:
        report_ok(f"{node_count} узлов: ссылки на типы разрешаются")
    if R.stopped:
        finalize()
        sys.exit(1)

    # --- 6. Silent degradation to xs:anyType ---
    # On XML-schema import the platform silently swaps an unresolved foreign type
    # for anyType.
    if any_type_props and imports:
        names = [p.get("name") for p in any_type_props if p.get("name")]
        shown = ", ".join(names[:5])
        report_warn(f'Свойств с type="xs:anyType": {len(any_type_props)} при объявленных '
                    f'импортах ({shown}). Тип не разрешён — заполнить структурно такое '
                    f'свойство нельзя. Обычно это след импорта XML-схемы: платформа заменяет '
                    f'неразрешённый чужой тип на anyType без ошибки')

    # --- 7. Unused imports ---
    # An unused import on its own is harmless and occurs in a quarter of the
    # packages of the standard configurations. It becomes a signal only together
    # with anyType — then it is almost certainly an unresolved dependency.
    unused = [i for i in imports if i not in used_namespaces]
    if unused and any_type_props:
        report_warn(f"Импорт(ы) без единого использованного типа: {', '.join(unused)} — "
                    f"вместе с anyType это признак неразрешённой зависимости")
    if imports and not unused:
        report_ok(f"{len(imports)} импорт(ов) — все используются")

    # --- 8. nillable on attribute-form properties ---
    nill_attrs = [p.get("name") for p in iter_local(pkg, "property")
                  if p.get("form") == "Attribute" and p.get("nillable") == "true"]
    if nill_attrs:
        report_warn(f'Свойств с nillable="true" и form="Attribute": {len(nill_attrs)} '
                    f'({", ".join(str(n) for n in nill_attrs[:5])}). Спецификация XSD не '
                    f'допускает nillable у атрибутов — экспорт XML-схемы в Конфигураторе '
                    f'их потеряет')

    # --- 9. Facet consistency ---
    facet_checked = 0
    for t in iter_local(pkg, "valueType", "typeDef"):
        if local_name(t) == "typeDef" and t.get(f"{{{XSI_NS}}}type") == "ObjectType":
            continue
        facet_checked += 1
        nm = t.get("name") or "(анонимный тип)"
        if t.get("length") and (t.get("minLength") is not None or t.get("maxLength") is not None):
            # XSD forbids this, but the platform stores such types — warn, not error
            report_warn(f"{nm} : length задан вместе с minLength/maxLength — спецификация "
                        f"XSD считает их взаимоисключающими")
        min_l, max_l = t.get("minLength"), t.get("maxLength")
        if min_l and max_l and int(min_l) > int(max_l):
            report_error(f"{nm} : minLength ({min_l}) больше maxLength ({max_l})")
        td, fd = t.get("totalDigits"), t.get("fractionDigits")
        if td and fd and int(fd) > int(td):
            report_error(f"{nm} : fractionDigits ({fd}) больше totalDigits ({td})")
        ws = t.get("whiteSpace")
        if ws and ws not in ("preserve", "replace", "collapse"):
            report_error(f'{nm} : недопустимое whiteSpace="{ws}"')
        var = t.get("variety")
        if var and var not in ("Atomic", "List", "Union"):
            report_error(f'{nm} : недопустимое variety="{var}"')
        if var == "List" and t.get("itemType") is None:
            report_warn(f'{nm} : variety="List" без itemType')
        if R.stopped:
            break
    if facet_checked and not R.stopped:
        report_ok(f"{facet_checked} простых тип(ов): фасеты согласованы")
    if R.stopped:
        finalize()
        sys.exit(1)

    # --- 10. property form / bounds ---
    for p in iter_local(pkg, "property"):
        form = p.get("form")
        if form and form not in ("Element", "Attribute", "Text"):
            report_error(f'Свойство "{p.get("name")}": недопустимое form="{form}"')
        ub = p.get("upperBound")
        if ub and ub != "-1" and int(ub) < 1:
            report_error(f'Свойство "{p.get("name")}": upperBound="{ub}" '
                         f'(допустимы -1 или число ≥ 1)')
        lb = p.get("lowerBound")
        if lb and ub and ub != "-1" and int(lb) > int(ub):
            report_error(f'Свойство "{p.get("name")}": lowerBound ({lb}) больше upperBound ({ub})')
        if p.get("name") is None and p.get("ref") is None:
            report_error("Свойство без name и без ref")
        # In the XDTO model `fixed` is a boolean flag and the value lives in
        # `default`. In an XML schema it is the other way round: fixed="V"
        # carries both the flag and the value.
        if p.get("fixed") is not None:
            fx = p.get("fixed")
            p_name = p.get("name") if p.get("name") is not None else p.get("ref")
            if fx not in ("true", "false"):
                report_error(f'Свойство "{p_name}": fixed="{fx}" — в модели это булев признак, '
                             f'значение задаётся в default (в XML-схеме признак и значение '
                             f'совмещены в fixed)')
            elif fx == "true" and p.get("default") is None:
                report_error(f"Отсутствует фиксированное значение свойства '{p_name}': "
                             f'есть fixed="true", нет default')
        if R.stopped:
            break
    if not R.stopped:
        report_ok("Свойства: form, кратности и фиксированные значения корректны")

    # --- 10b. Structural consistency ---
    struct_ok = True
    for t in iter_local(pkg, "objectType", "typeDef"):
        if local_name(t) == "typeDef" and t.get(f"{{{XSI_NS}}}type") != "ObjectType":
            continue
        tn = t.get("name") or "(анонимный тип)"
        prop_names = set()
        for c in elements(t):
            if local_name(c) != "property":
                continue
            pn = c.get("name")
            if pn:
                if pn in prop_names:
                    report_error(f'{tn} : дублирующееся имя свойства "{pn}"')
                    struct_ok = False
                prop_names.add(pn)
        if R.stopped:
            break

    for p in iter_local(pkg, "property"):
        pn = p.get("name") if p.get("name") is not None else p.get("ref")
        if p.get("name") is not None and p.get("ref") is not None:
            report_error(f'Свойство "{pn}": заданы одновременно name и ref — '
                         f'допустимо только одно')
            struct_ok = False
        inline_type_def = next((c for c in elements(p) if local_name(c) == "typeDef"), None)
        if inline_type_def is not None and p.get("type") is not None:
            report_error(f'Свойство "{pn}": заданы одновременно type и вложенный <typeDef> — '
                         f'допустимо только одно')
            struct_ok = False
        if inline_type_def is not None and inline_type_def.get(f"{{{XSI_NS}}}type") is None:
            report_error(f'Свойство "{pn}": у вложенного <typeDef> не задан xsi:type '
                         f'(ValueType или ObjectType)')
            struct_ok = False
        if R.stopped:
            break

    # An anonymous type inside a valueType defines the base type and carries no xsi:type
    for vt in iter_local(pkg, "valueType"):
        for c in elements(vt):
            if local_name(c) != "typeDef":
                continue
            if c.get(f"{{{XSI_NS}}}type") is not None:
                report_warn(f'{vt.get("name")} : у <typeDef> внутри <valueType> задан '
                            f'xsi:type — платформа его здесь не пишет')

    # The kind of the base type must match
    for t in iter_local(pkg, "objectType"):
        b = t.get("base")
        if not b:
            continue
        parts = b.split(":")
        if len(parts) != 2 or t.nsmap.get(parts[0]) != target_ns:
            continue
        if parts[1] in value_type_names:
            report_error(f'{t.get("name")} : base="{b}" ссылается на valueType, а objectType '
                         f'может наследоваться только от objectType')
            struct_ok = False
    for t in iter_local(pkg, "valueType"):
        b = t.get("base")
        if not b:
            continue
        parts = b.split(":")
        if len(parts) != 2 or t.nsmap.get(parts[0]) != target_ns:
            continue
        if parts[1] in object_type_names:
            report_error(f'{t.get("name")} : base="{b}" ссылается на objectType, а valueType '
                         f'может строиться только на простом типе')
            struct_ok = False

    # A Union with no members
    for t in iter_local(pkg, "valueType", "typeDef"):
        if t.get("variety") != "Union" or t.get("memberTypes") is not None:
            continue
        if not any(local_name(c) == "typeDef" for c in elements(t)):
            tn = t.get("name") or "(анонимный тип)"
            report_warn(f'{tn} : variety="Union" без memberTypes и без вложенных типов — '
                        f'состав объединения пуст')

    if struct_ok and not R.stopped:
        report_ok("Структура типов и свойств согласована")
    if R.stopped:
        finalize()
        sys.exit(1)

    # --- 11. Metadata object ---
    ns_md = {"md": MD_NS}
    if md_path:
        md_root = etree.parse(md_path).getroot()
        md_name = md_root.xpath("//md:XDTOPackage/md:Properties/md:Name", namespaces=ns_md)
        md_ns = md_root.xpath("//md:XDTOPackage/md:Properties/md:Namespace", namespaces=ns_md)
        if not md_name:
            report_error("В объекте метаданных не задано <Name>")
        elif inner_text(md_name[0]) != file_name:
            report_error(f"<Name>{inner_text(md_name[0])}</Name> не совпадает с именем "
                         f'каталога "{file_name}"')
        else:
            report_ok(f"Объект метаданных: Name = {inner_text(md_name[0])}")
        if md_ns and inner_text(md_ns[0]) != target_ns:
            report_error(f"<Namespace>{inner_text(md_ns[0])}</Namespace> не совпадает с "
                         f"targetNamespace пакета ({target_ns})")
        elif md_ns:
            report_ok("Namespace объекта метаданных совпадает с targetNamespace")
    else:
        report_warn("Файл объекта метаданных <Имя>.xml не найден рядом с каталогом пакета")

    # --- 12. Registration in Configuration.xml + namespace uniqueness ---
    config_xml = os.path.join(config_dir, "Configuration.xml")
    if os.path.isfile(config_xml):
        cfg_root = etree.parse(config_xml).getroot()
        registered = any(
            inner_text(e) == file_name for e in
            cfg_root.xpath("//md:Configuration/md:ChildObjects/md:XDTOPackage", namespaces=ns_md))
        if registered:
            report_ok("Зарегистрирован в Configuration.xml")
        else:
            report_error(f"<XDTOPackage>{file_name}</XDTOPackage> отсутствует в ChildObjects "
                         f"файла Configuration.xml — платформа пакет не увидит")

        pkg_root = os.path.join(config_dir, "XDTOPackages")
        if os.path.isdir(pkg_root):
            clash, known_ns = [], {}
            for name in sorted(os.listdir(pkg_root)):
                other = os.path.join(pkg_root, name)
                ob = os.path.join(other, "Ext", "Package.bin")
                if not os.path.isfile(ob):
                    continue
                try:
                    ons = etree.parse(ob).getroot().get("targetNamespace")
                except Exception:
                    continue
                known_ns[ons] = name
                if name != file_name and ons == target_ns:
                    clash.append(name)
            # The platform rejects a package when an imported namespace is absent
            # from the configuration: «Ошибка проверки модели XDTO: xdto-package-3.3
            # … не определен»
            missing = [i for i in imports if i not in known_ns and i not in PLATFORM_NS]
            if missing:
                report_error("Импортируемые пакеты не определены в конфигурации: "
                             + ", ".join(missing)
                             + ". Платформа отвергнет пакет при обновлении конфигурации — "
                               "соберите зависимости первыми")
            elif imports:
                report_ok("Все импорты разрешаются в пакеты конфигурации")

            if clash:
                report_warn(f'targetNamespace "{target_ns}" объявлен также в пакет(ах): '
                            f'{", ".join(clash)}. Платформа это допускает, но <import> на это '
                            f'пространство имён становится неоднозначным')
            else:
                report_ok("targetNamespace уникален в конфигурации")
    else:
        report_warn(f"Configuration.xml не найден ({config_dir}) — проверки регистрации и "
                    f"уникальности namespace пропущены")

    finalize()
    sys.exit(1 if R.errors > 0 else 0)


if __name__ == "__main__":
    main()
