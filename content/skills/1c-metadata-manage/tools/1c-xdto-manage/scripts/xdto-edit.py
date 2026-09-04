#!/usr/bin/env python3
# xdto-edit v1.0 — Point edits of a 1C XDTO package
# Source: https://github.com/Nikolay-Shirokov/cc-1c-skills
#
# Python port of xdto-edit.ps1 v1.0. Deviations from the .ps1:
#   * the support guard lives centrally in tools/_shared/support_guard.py;
#   * sibling scripts are looked up in this directory first (the 1c-rules bundle
#     merges xdto-decompile / xdto-compile / xdto-validate into one skill), with
#     the upstream ../../<skill>/scripts/ layout kept as a fallback;
#   * XML rewrites preserve the prologue / epilogue / newline style of the
#     original file byte for byte (lxml, unlike .NET XmlWriter, drops them).
# Model operations still go through the decompile → edit XSD → compile
# round-trip — the same deliberate exception to skill autonomy as upstream:
# a second emitter would drift from the first and break byte fidelity.

import argparse
import copy
import os
import re
import subprocess
import sys
import uuid as uuid_mod

from lxml import etree

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "..", "_shared"))
import support_guard  # noqa: E402

XDTO_NS = "http://v8.1c.ru/8.1/xdto"
XS_NS = "http://www.w3.org/2001/XMLSchema"
MD_NS = "http://v8.1c.ru/8.3/MDClasses"
V8_NS = "http://v8.1c.ru/8.1/data/core"

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

OPERATIONS = ("add-property", "replace-property", "remove-property",
              "add-type", "remove-type", "add-enum", "add-import",
              "rename", "set-synonym", "set-comment", "set-namespace")

META_OPS = ("rename", "set-synonym", "set-comment")


def die(msg):
    print(msg, file=sys.stderr)
    sys.exit(1)


def local_name(node):
    return etree.QName(node.tag).localname


def is_xs(node, local=None):
    return (isinstance(node.tag, str) and node.tag.startswith("{%s}" % XS_NS)
            and (local is None or local_name(node) == local))


def sibling_script(name):
    """Same directory first (1c-rules bundle), upstream per-skill layout second."""
    here = os.path.join(SCRIPT_DIR, name + ".py")
    if os.path.isfile(here):
        return here
    return os.path.join(SCRIPT_DIR, "..", "..", name, "scripts", name + ".py")


DECOMPILE_SCRIPT = sibling_script("xdto-decompile")
COMPILE_SCRIPT = sibling_script("xdto-compile")
VALIDATE_SCRIPT = sibling_script("xdto-validate")


def assert_siblings_present(operation):
    """Проверяем комплектность заранее, чтобы не падать на середине правки."""
    needed = {}
    if operation not in META_OPS:
        needed["xdto-decompile"] = DECOMPILE_SCRIPT
        needed["xdto-compile"] = COMPILE_SCRIPT
    missing = [k for k, v in needed.items() if not os.path.isfile(v)]
    if missing:
        die("Навык неработоспособен: рядом нет %s.\n"
            'Операция "%s" выполняется через %s.\n'
            "Ожидаются в каталоге навыка: %s"
            % (", ".join(missing), operation,
               "них" if len(missing) > 1 else "него", SCRIPT_DIR))


def invoke_sibling(script, arg_list, what):
    if not os.path.isfile(script):
        die("Не найден навык %s по пути: %s" % (what, script))
    proc = subprocess.run([sys.executable, script] + arg_list,
                          capture_output=True, text=True, encoding="utf-8")
    if proc.returncode != 0:
        die("%s завершился с ошибкой:\n%s%s" % (what, proc.stdout or "", proc.stderr or ""))
    return proc.stdout


# --- XML writing that preserves everything outside the root -------------------

def write_xml_like_original(path, root):
    """Пролог и эпилог берём из исходного файла байт в байт: XmlWriter в .ps1
    работает с PreserveWhitespace, lxml же теряет пробелы вне корня."""
    with open(path, "rb") as f:
        raw = f.read()
    bom = b"\xef\xbb\xbf" if raw.startswith(b"\xef\xbb\xbf") else b""
    body = raw[len(bom):]
    m = re.match(rb"(<\?xml[^>]*\?>)(\s*)", body)
    prologue = (m.group(1) + m.group(2)) if m else b'<?xml version="1.0" encoding="UTF-8"?>\n'
    epilogue = re.search(rb"(\s*)\Z", body).group(1)

    data = etree.tostring(root, encoding="unicode").encode("utf-8")
    if b"\r\n" in body:
        data = data.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
    with open(path, "wb") as f:
        f.write(bom + prologue + data + epilogue)


def set_inner_text(el, text):
    for c in list(el):
        el.remove(c)
    el.text = text


# --- Metadata object edits ------------------------------------------------------

class Pkg:
    """Resolved package paths — filled in main()."""
    name = None
    dir = None
    xdto_root = None
    config_root = None
    bin_file = None
    md_file = None
    config_xml = None


def edit_metadata(field, new_value):
    tree = etree.parse(Pkg.md_file)
    root = tree.getroot()
    ns = {"md": MD_NS, "v8": V8_NS}
    found = root.xpath("//md:XDTOPackage/md:Properties", namespaces=ns)
    if not found:
        die("В объекте метаданных не найден блок <Properties>")
    props = found[0]

    if field == "Name":
        n = props.xpath("md:Name", namespaces=ns)
        if not n:
            die("В объекте метаданных нет <Name>")
        set_inner_text(n[0], new_value)
    elif field == "Comment":
        c = props.xpath("md:Comment", namespaces=ns)
        if c:
            c = c[0]
        else:
            c = etree.SubElement(props, "{%s}Comment" % MD_NS)
        set_inner_text(c, new_value)
    elif field == "Namespace":
        n = props.xpath("md:Namespace", namespaces=ns)
        if not n:
            die("В объекте метаданных нет <Namespace>")
        set_inner_text(n[0], new_value)
    elif field == "Synonym":
        syn = props.xpath("md:Synonym", namespaces=ns)
        if syn:
            syn = syn[0]
        else:
            syn = etree.SubElement(props, "{%s}Synonym" % MD_NS)
        item = syn.xpath("v8:item[v8:lang='ru']", namespaces=ns)
        if item:
            item = item[0]
        else:
            item = etree.SubElement(syn, "{%s}item" % V8_NS)
            lang = etree.SubElement(item, "{%s}lang" % V8_NS)
            lang.text = "ru"
            etree.SubElement(item, "{%s}content" % V8_NS)
        set_inner_text(item.xpath("v8:content", namespaces=ns)[0], new_value)

    write_xml_like_original(Pkg.md_file, root)


def rename_package(new_name):
    if not re.match(r"^[\wЀ-ӿ]+$", new_name) or re.match(r"^\d", new_name):
        die('"%s" не является допустимым идентификатором 1С' % new_name)
    new_md = os.path.join(Pkg.xdto_root, new_name + ".xml")
    new_dir = os.path.join(Pkg.xdto_root, new_name)
    if os.path.exists(new_md) or os.path.exists(new_dir):
        die('Имя "%s" уже занято другим пакетом' % new_name)

    edit_metadata("Name", new_name)
    os.rename(Pkg.md_file, new_md)
    os.rename(Pkg.dir, new_dir)

    if os.path.isfile(Pkg.config_xml):
        tree = etree.parse(Pkg.config_xml)
        root = tree.getroot()
        ns = {"md": MD_NS}
        found = False
        for e in root.xpath("//md:Configuration/md:ChildObjects/md:XDTOPackage", namespaces=ns):
            if (e.text or "") == Pkg.name:
                e.text = new_name
                found = True
                break
        if found:
            write_xml_like_original(Pkg.config_xml, root)
            print("  Configuration.xml: <XDTOPackage> переименован в %s" % new_name)
        else:
            print("WARNING: В Configuration.xml не найдена запись <XDTOPackage>%s</XDTOPackage> — "
                  "зарегистрируйте пакет вручную" % Pkg.name, file=sys.stderr)
    print("✓ Пакет переименован: %s → %s" % (Pkg.name, new_name))
    print("  Перемещены: %s.xml, %s/" % (new_name, new_name))


# --- Model edits through the XSD round-trip -------------------------------------

def schema_children(el, local):
    return [c for c in el if is_xs(c, local)]


def schema_first(el, local):
    r = schema_children(el, local)
    return r[0] if r else None


def find_type_element(schema, type_name):
    for kind in ("complexType", "simpleType"):
        for t in schema_children(schema, kind):
            if t.get("name") == type_name:
                return t
    die('В пакете нет типа "%s"' % type_name)


def get_type_body(ct):
    """Тело типа: внутрь xs:complexContent/xs:extension, если тип наследуется."""
    content = schema_first(ct, "complexContent")
    if content is not None:
        ext = schema_first(content, "extension")
        if ext is not None:
            return ext
    return ct


def find_declaration(body, prop_name):
    for node in body.iterdescendants():
        if not isinstance(node.tag, str) or not node.tag.startswith("{%s}" % XS_NS):
            continue
        if local_name(node) not in ("element", "attribute"):
            continue
        if node.get("name") == prop_name:
            return node
    return None


def resolve_path(schema, path):
    """Путь Тип.Свойство[.Вложенное...] — точка безопасна: имена в модели XDTO
    являются идентификаторами 1С и точку содержать не могут."""
    segments = path.split(".")
    type_el = find_type_element(schema, segments[0])
    if len(segments) == 1:
        return type_el, None

    body = get_type_body(type_el)
    decl = None
    for i in range(1, len(segments)):
        decl = find_declaration(body, segments[i])
        if decl is None:
            die('По пути "%s" не найдено свойство "%s"' % (path, segments[i]))
        if i < len(segments) - 1:
            inner = schema_first(decl, "complexType")
            if inner is None:
                die('Свойство "%s" не содержит вложенного типа — путь дальше не идёт'
                    % segments[i])
            body = get_type_body(inner)
    return type_el, decl


def import_fragment(schema, xml):
    ns_attrs = ' xmlns:xs="%s" xmlns:xdto="%s"' % (XS_NS, XDTO_NS)
    tns = schema.get("targetNamespace")
    if tns:
        ns_attrs += ' xmlns:tns="%s"' % tns
    for prefix, uri in schema.nsmap.items():
        if prefix and prefix not in ("xs", "xdto", "tns"):
            ns_attrs += ' xmlns:%s="%s"' % (prefix, uri)
    try:
        tmp = etree.fromstring(("<wrap%s>%s</wrap>" % (ns_attrs, xml)).encode("utf-8"))
    except Exception as ex:
        die("Не удалось разобрать -Value как фрагмент XML-схемы: %s\n"
            "Получено: %s\n"
            "Если фрагмент передан инлайном, кавычки могли схлопнуться на границе "
            'процессов — положите его в файл и укажите -Value "@путь".' % (ex, xml))
    res = [copy.deepcopy(c) for c in tmp if isinstance(c.tag, str)]
    if not res:
        die("Во фрагменте нет ни одного элемента: %s" % xml)
    return res


def replace_target_namespace(schema, old, new):
    """lxml не позволяет менять nsmap существующего элемента — пересобираем корень.
    Префиксы в значениях атрибутов (tns:Тип) при этом остаются валидными: тот же
    префикс просто начинает указывать на новый URI."""
    nsmap = {k: (new if v == old else v) for k, v in schema.nsmap.items()}
    new_root = etree.Element(schema.tag, nsmap=nsmap)
    for k, v in schema.attrib.items():
        new_root.set(k, v)
    new_root.set("targetNamespace", new)
    new_root.text = schema.text
    for c in list(schema):
        new_root.append(c)
    return new_root


def apply_model_operation(schema, operation, target, value):
    """Returns the schema root to save (set-namespace rebuilds it)."""
    if operation == "add-property":
        if not target:
            die("add-property требует -Target <Тип>")
        type_el, decl = resolve_path(schema, target)
        host = schema_first(decl, "complexType") if decl is not None else type_el
        body = get_type_body(host)
        for frag in import_fragment(schema, value):
            kind = local_name(frag)
            if kind == "attribute":
                body.append(frag)
            elif kind == "element":
                particle = schema_first(body, "sequence")
                if particle is None:
                    particle = schema_first(body, "choice")
                if particle is None:
                    particle = schema_first(body, "all")
                if particle is None:
                    particle = etree.Element("{%s}sequence" % XS_NS)
                    first_attr = schema_first(body, "attribute")
                    if first_attr is not None:
                        first_attr.addprevious(particle)
                    else:
                        body.append(particle)
                particle.append(frag)
            else:
                die("add-property ожидает <xs:element> или <xs:attribute>, получен <xs:%s>"
                    % kind)
            print("  + %s  в тип %s" % (frag.get("name"), target))

    elif operation == "replace-property":
        if not target:
            die('replace-property требует -Target "Тип.Свойство"')
        _, decl = resolve_path(schema, target)
        if decl is None:
            die('replace-property требует путь вида "Тип.Свойство"')
        frags = import_fragment(schema, value)
        if len(frags) != 1:
            die("replace-property ожидает ровно одно объявление")
        decl.getparent().replace(decl, frags[0])
        print("  ~ %s заменено" % target)

    elif operation == "remove-property":
        if not target:
            die('remove-property требует путь "Тип.Свойство"')
        for one in re.split(r"\s*;;\s*", target):
            if not one:
                continue
            _, decl = resolve_path(schema, one)
            if decl is None:
                die('remove-property требует путь вида "Тип.Свойство", получено "%s"' % one)
            decl.getparent().remove(decl)
            print("  − %s удалено" % one)

    elif operation == "add-type":
        for frag in import_fragment(schema, value):
            if local_name(frag) not in ("complexType", "simpleType"):
                die("add-type ожидает <xs:complexType> или <xs:simpleType>, получен <xs:%s>"
                    % local_name(frag))
            schema.append(frag)
            print("  + тип %s" % frag.get("name"))

    elif operation == "remove-type":
        if not target:
            die("remove-type требует -Target <Тип>")
        for one in re.split(r"\s*;;\s*", target):
            if not one:
                continue
            t = find_type_element(schema, one)
            t.getparent().remove(t)
            print("  − тип %s удалён" % one)

    elif operation == "add-enum":
        if not target:
            die("add-enum требует -Target <ТипЗначения>")
        t = find_type_element(schema, target)
        restriction = schema_first(t, "restriction")
        if restriction is None:
            die('Тип "%s" не является ограничением простого типа' % target)
        for lit in re.split(r"\s*;;\s*", value or ""):
            if not lit:
                continue
            e = etree.SubElement(restriction, "{%s}enumeration" % XS_NS)
            e.set("value", lit)
            print('  + значение "%s" в тип %s' % (lit, target))

    elif operation == "add-import":
        for uri in re.split(r"\s*;;\s*", value or ""):
            if not uri:
                continue
            if any(i.get("namespace") == uri for i in schema_children(schema, "import")):
                print("  = импорт %s уже объявлен" % uri)
                continue
            imp = etree.Element("{%s}import" % XS_NS)
            imp.set("namespace", uri)
            first_other = None
            for c in schema:
                if isinstance(c.tag, str) and local_name(c) not in ("annotation", "import"):
                    first_other = c
                    break
            if first_other is not None:
                first_other.addprevious(imp)
            else:
                schema.append(imp)
            print("  + импорт %s" % uri)

    elif operation == "set-namespace":
        if not value:
            die("set-namespace требует -Value <URI>")
        old = schema.get("targetNamespace")
        # Установка того же значения не отбрасывается: пакет пересобирается вхолостую,
        # и это заодно проба точности пути «выгрузить → собрать» на любом пакете
        if old == value:
            print("  = namespace уже %s, пакет пересобран без изменений" % value)
        # Меняем и targetNamespace, и объявление префикса, который на него указывал:
        # иначе ссылки на собственные типы станут ссылками в чужое пространство имён
        schema = replace_target_namespace(schema, old, value)
        print("  ~ namespace: %s → %s" % (old, value))

    return schema


# --- Dispatch -------------------------------------------------------------------

def resolve_package(package_path):
    if not os.path.isabs(package_path):
        package_path = os.path.join(os.getcwd(), package_path)

    pkg_dir = None
    if os.path.isdir(package_path):
        if os.path.isfile(os.path.join(package_path, "Ext", "Package.bin")):
            pkg_dir = package_path
    elif os.path.isfile(package_path) and os.path.basename(package_path) == "Package.bin":
        pkg_dir = os.path.dirname(os.path.dirname(package_path))
    elif package_path.endswith(".xml"):
        stem = os.path.join(os.path.dirname(package_path),
                            os.path.splitext(os.path.basename(package_path))[0])
        if os.path.isfile(os.path.join(stem, "Ext", "Package.bin")):
            pkg_dir = stem
    if not pkg_dir:
        die("Не найден пакет XDTO по пути: %s" % package_path)

    pkg_dir = os.path.normpath(pkg_dir)
    Pkg.dir = pkg_dir
    Pkg.name = os.path.basename(pkg_dir)
    Pkg.xdto_root = os.path.dirname(pkg_dir)
    Pkg.config_root = os.path.dirname(Pkg.xdto_root)
    Pkg.bin_file = os.path.join(pkg_dir, "Ext", "Package.bin")
    Pkg.md_file = os.path.join(Pkg.xdto_root, Pkg.name + ".xml")
    Pkg.config_xml = os.path.join(Pkg.config_root, "Configuration.xml")


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Point edits of a 1C XDTO package",
                                     allow_abbrev=False)
    parser.add_argument("-PackagePath", "-Path", dest="PackagePath", required=True)
    parser.add_argument("-Operation", dest="Operation", required=True, choices=OPERATIONS)
    parser.add_argument("-Target", dest="Target", default="")
    parser.add_argument("-Value", dest="Value", default="")
    parser.add_argument("-NoValidate", dest="NoValidate", action="store_true")
    args = parser.parse_args()

    resolve_package(args.PackagePath)

    # -Value "@путь" — содержимое берётся из файла. Передавать XSD-фрагмент инлайном
    # через оболочку ненадёжно: вложенные кавычки схлопываются на границе процессов,
    # и вместо понятной ошибки получается сырой сбой разбора XML.
    value = args.Value
    if value and value.startswith("@"):
        value_file = value[1:]
        if not os.path.isabs(value_file):
            value_file = os.path.join(os.getcwd(), value_file)
        if not os.path.isfile(value_file):
            die("Файл значения не найден: %s" % value_file)
        with open(value_file, "r", encoding="utf-8-sig") as f:
            value = f.read().strip()

    support_guard.assert_edit_allowed(Pkg.dir, "editable")

    operation = args.Operation
    assert_siblings_present(operation)

    print("Пакет: %s" % Pkg.name)

    if operation == "rename":
        if not value:
            die("rename требует -Value <НовоеИмя>")
        rename_package(value)
        Pkg.name = value
        Pkg.dir = os.path.join(Pkg.xdto_root, value)
    elif operation == "set-synonym":
        if not value:
            die("set-synonym требует -Value <текст>")
        edit_metadata("Synonym", value)
        print("✓ Синоним: %s" % value)
    elif operation == "set-comment":
        edit_metadata("Comment", value)
        print("✓ Комментарий обновлён")
    else:
        tmp_dir = os.path.join(os.environ.get("TMPDIR", "/tmp"),
                               "xdto-edit_" + uuid_mod.uuid4().hex[:8])
        os.makedirs(tmp_dir, exist_ok=True)
        try:
            xsd_path = os.path.join(tmp_dir, "schema.xsd")
            invoke_sibling(DECOMPILE_SCRIPT,
                           ["-PackagePath", Pkg.bin_file, "-OutFile", xsd_path],
                           "xdto-decompile")

            schema = etree.parse(xsd_path).getroot()
            old_namespace = schema.get("targetNamespace")
            schema = apply_model_operation(schema, operation, args.Target, value)

            with open(xsd_path, "wb") as f:
                f.write(etree.tostring(schema, encoding="UTF-8", xml_declaration=True))
            invoke_sibling(COMPILE_SCRIPT,
                           ["-XsdPath", xsd_path, "-OutputDir", Pkg.config_root,
                            "-Name", Pkg.name, "-Force"],
                           "xdto-compile")

            if operation == "set-namespace":
                edit_metadata("Namespace", value)
                # Зависящие пакеты не трогаем: при версионировании они обязаны
                # продолжать смотреть на прежний namespace. Но молчать о них нельзя.
                dependents = []
                for entry in sorted(os.listdir(Pkg.xdto_root)):
                    if entry == Pkg.name:
                        continue
                    ob = os.path.join(Pkg.xdto_root, entry, "Ext", "Package.bin")
                    if not os.path.isfile(ob):
                        continue
                    try:
                        od = etree.parse(ob).getroot()
                        for imp in od:
                            if (isinstance(imp.tag, str) and local_name(imp) == "import"
                                    and imp.get("namespace") == old_namespace):
                                dependents.append(entry)
                                break
                    except Exception:
                        pass
                if dependents:
                    print("")
                    print("WARNING: Старый namespace импортируют пакеты (%d): %s. "
                          "Они не изменены — при версионировании это верно; если нет, "
                          "поправьте их импорты." % (len(dependents), ", ".join(dependents)),
                          file=sys.stderr)
            print("✓ Пакет пересобран: XDTOPackages/%s/Ext/Package.bin" % Pkg.name)
        finally:
            for r, dirs, files in os.walk(tmp_dir, topdown=False):
                for fn in files:
                    try:
                        os.remove(os.path.join(r, fn))
                    except OSError:
                        pass
                for dn in dirs:
                    try:
                        os.rmdir(os.path.join(r, dn))
                    except OSError:
                        pass
            try:
                os.rmdir(tmp_dir)
            except OSError:
                pass

    # --- Validate ---
    if not args.NoValidate:
        if os.path.isfile(VALIDATE_SCRIPT):
            print("")
            print("--- xdto-validate ---")
            sys.stdout.flush()
            subprocess.run([sys.executable, VALIDATE_SCRIPT,
                            "-PackagePath", os.path.join(Pkg.xdto_root, Pkg.name)])
        else:
            print("[SKIP] xdto-validate не найден: %s" % VALIDATE_SCRIPT)
    sys.exit(0)


if __name__ == "__main__":
    main()
