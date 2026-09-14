#!/usr/bin/env python3
# xdto-compile v1.1 — Build a 1C XDTO package from an XML Schema (XSD)
# Licence and attribution: NOTICE.md of the 1c-metadata-manage skill.
#
# Python port of xdto-compile.ps1 v1.1. Deviations from the .ps1:
#   * the support guard lives centrally in tools/_shared/support_guard.py
#     (the .ps1 inlines the same logic per script);
#   * -Synonym accepts either a plain string ("ru" is assumed) or a JSON object
#     {"ru": "...", "en": "..."} — the .ps1 takes a PowerShell hashtable there;
#   * when the metadata object file already exists (a -Force rebuild, i.e. the
#     path xdto-edit takes), its uuid and its MetaDataObject/@version are kept.
#     The .ps1 mints a fresh uuid and hardcodes version="2.17" on every run, which
#     changes the object's identity and downgrades the format on a mere edit —
#     see metadata-xml-workarounds.md §4 (UUID stability) and subagent-pipeline.md
#     stage 4a ("UUIDs preserved on edits, not regenerated").
# Everything else — attribute order, the dNpN prefix scheme, particle
# flattening, warnings, Configuration.xml registration — is byte-faithful.

import argparse
import json
import os
import re
import sys
import uuid as uuid_mod

from lxml import etree

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "..", "_shared"))
import support_guard  # noqa: E402

XDTO_NS = "http://v8.1c.ru/8.1/xdto"
XS_NS = "http://www.w3.org/2001/XMLSchema"
XSI_NS = "http://www.w3.org/2001/XMLSchema-instance"
MD_NS = "http://v8.1c.ru/8.3/MDClasses"
V8_NS = "http://v8.1c.ru/8.1/data/core"

# Эти пространства имён предоставляет сама платформа — пакетов в конфигурации
# для них нет и быть не должно (выведено по корпусу: импортируются, но
# targetNamespace с таким значением ни у одного пакета нет)
PLATFORM_NS = (
    "http://v8.1c.ru/8.1/data/core",
    "http://v8.1c.ru/8.1/data/enterprise",
    "http://v8.1c.ru/8.1/data/enterprise/current-config",
    "http://v8.1c.ru/8.1/data-composition-system/settings",
    "http://v8.1c.ru/8.3/data/ext",
    "http://www.w3.org/2001/XMLSchema",
)

FACETS = ("length", "minLength", "maxLength", "totalDigits", "fractionDigits",
          "minInclusive", "maxInclusive", "minExclusive", "maxExclusive", "whiteSpace")

# Предупреждения о том, что XSD выражает, а модель XDTO — нет. Молча ронять
# такие конструкции нельзя: пакет соберётся, а половина свойств исчезнет.
WARNINGS = []


def warn(msg):
    if msg not in WARNINGS:
        WARNINGS.append(msg)


def local_name(node):
    return etree.QName(node.tag).localname


def elements(parent):
    return [c for c in parent if isinstance(c.tag, str)]


def XA(el, name):
    """Plain attribute value, or None when absent."""
    return el.get(name)


def MA(el, name):
    """xdto: mirror attribute — the literal value to write into Package.bin.
    Префикс не фиксируем: ищем по namespace, а не по строке "xdto:"."""
    return el.get("{%s}%s" % (XDTO_NS, name))


def XChildren(el, local):
    return [c for c in el if isinstance(c.tag, str)
            and c.tag.startswith("{%s}" % XS_NS) and local_name(c) == local]


def XFirst(el, local):
    r = XChildren(el, local)
    return r[0] if r else None


class QName:
    __slots__ = ("Ns", "Local")

    def __init__(self, ns, local):
        self.Ns = ns
        self.Local = local


def split_qname(el, qname, target_ns):
    """Split a QName from the XSD into (ns, local) using that element's prefix scope."""
    if qname is None or qname == "":
        return None
    parts = qname.split(":")
    if len(parts) == 2:
        ns = el.nsmap.get(parts[0])
        loc = parts[1]
    else:
        # Прощающий ввод: голое имя типа трактуем как тип целевого пространства
        ns = el.nsmap.get(None)
        if not ns:
            ns = target_ns
        loc = parts[0]
    return QName(ns, loc)


def split_qname_list(el, lst, target_ns):
    if not lst:
        return []
    res = []
    for q in re.split(r"\s+", lst):
        if q:
            res.append(split_qname(el, q, target_ns))
    return res


# --- Emit-tree primitives -----------------------------------------------------
# A node carries attributes in canonical order; QName values keep their namespace
# so prefixes can be assigned per depth at serialization time (the dNpN scheme).

class Attr:
    __slots__ = ("Name", "Value", "Ns", "Local", "List", "Clark")

    def __init__(self, name, value=None, ns=None, local=None, lst=None, clark=False):
        self.Name = name
        self.Value = value
        self.Ns = ns
        self.Local = local
        self.List = lst
        self.Clark = clark


class Node:
    __slots__ = ("Tag", "Attrs", "Children", "Text", "Prefix", "DeclareNs")

    def __init__(self, tag):
        self.Tag = tag
        self.Attrs = []
        self.Children = []
        self.Text = None
        self.Prefix = None
        self.DeclareNs = None


def add_attr(node, name, value):
    # None означает «атрибута нет»; пустая строка — валидное значение
    if value is None:
        return
    node.Attrs.append(Attr(name, str(value)))


def add_qattr(node, name, ns, local):
    if local is None:
        return
    node.Attrs.append(Attr(name, None, "" if ns is None else str(ns), str(local)))


def add_qlist_attr(node, name, pairs, clark):
    if not pairs:
        return
    node.Attrs.append(Attr(name, None, None, None, lst=pairs, clark=clark))


def add_child(node, child):
    if child is not None:
        node.Children.append(child)


def set_attr_value(node, name, value):
    for a in node.Attrs:
        if a.Name == name:
            a.Value = value
            return
    add_attr(node, name, value)


# Canonical attribute order per element — derived by topological sort over the
# whole 8.3.24 corpus (acc + erp, 760 packages), see docs/1c-xdto-spec.md.
ATTR_ORDER = {
    "package": ["targetNamespace", "elementFormQualified", "attributeFormQualified"],
    "import": ["namespace"],
    "objectType": ["name", "base", "open", "abstract", "mixed", "ordered", "sequenced"],
    "property": ["name", "ref", "type", "lowerBound", "upperBound", "nillable",
                 "fixed", "default", "form", "localName", "qualified"],
    "valueType": ["name", "base", "variety", "itemType", "length", "memberTypes",
                  "minExclusive", "maxExclusive", "minInclusive", "maxInclusive",
                  "minLength", "maxLength", "totalDigits", "fractionDigits", "whiteSpace"],
    "typeDef": ["xsi:type", "base", "mixed", "open", "ordered", "sequenced", "variety",
                "itemType", "length", "memberTypes", "minExclusive", "maxExclusive",
                "minInclusive", "maxInclusive", "minLength", "maxLength", "totalDigits",
                "fractionDigits", "whiteSpace"],
    "enumeration": ["xsi:type"],
}


def sort_attrs(node):
    order = ATTR_ORDER.get(node.Tag)
    if not order:
        return node.Attrs
    sorted_attrs = []
    for n in order:
        for a in node.Attrs:
            if a.Name == n:
                sorted_attrs.append(a)
    for a in node.Attrs:
        if a.Name not in order:
            sorted_attrs.append(a)
    return sorted_attrs


def esc(s):
    if s is None:
        return ""
    return (str(s).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def esc_text(s):
    if s is None:
        return ""
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


# --- Serializer with the dNpN prefix scheme ---

OUT = []


def serialize_node(node, depth, inherited):
    indent = "\t" * (depth - 1)
    attrs = sort_attrs(node)

    # Namespaces needing a NEW declaration here: те, что ещё не в области видимости.
    # Сериализатор платформы объявляет префикс на первом узле, где он нужен, а
    # потомки его переиспользуют — отсюда d2p1 у property внутри objectType.
    local_ns = []

    def need_prefix(ns):
        if not ns or ns == XS_NS or ns == XSI_NS:
            return
        if ns in inherited:
            return
        if ns not in local_ns:
            local_ns.append(ns)

    for a in attrs:
        if a.List:
            # Нотация Кларка несёт ns в значении и префикса не требует; редкие
            # случаи, где платформа его всё же объявила, приходят зеркалом declareNs
            if not a.Clark:
                for p in a.List:
                    need_prefix(p.Ns)
        elif a.Ns:
            need_prefix(a.Ns)

    # Свойство с qualified платформа сериализует с явным префиксом пространства
    # имён XDTO — и в имени тега, и в имени самого атрибута
    has_qualified = any(a.Name == "qualified" for a in attrs)
    if has_qualified:
        need_prefix(XDTO_NS)
    if node.DeclareNs:
        need_prefix(node.DeclareNs)

    prefix_of = dict(inherited)
    ns_decls = ""
    for i, ns in enumerate(local_ns):
        # Осмысленный префикс из исходника (зеркало xdto:prefix) имеет приоритет
        px = node.Prefix if (i == 0 and node.Prefix) else "d%dp%d" % (depth, i + 1)
        prefix_of[ns] = px
        ns_decls += ' xmlns:%s="%s"' % (px, esc(ns))

    def qval(ns, loc):
        if not ns:
            return loc
        if ns == XS_NS:
            return "xs:" + loc
        if ns == XSI_NS:
            return "xsi:" + loc
        return "%s:%s" % (prefix_of[ns], loc)

    attr_text = ""
    for a in attrs:
        if a.List:
            vals = []
            for p in a.List:
                if a.Clark:
                    vals.append(("{%s}%s" % (p.Ns, p.Local)) if p.Ns else p.Local)
                else:
                    vals.append(qval(p.Ns, p.Local))
            attr_text += ' %s="%s"' % (a.Name, esc(" ".join(vals)))
        elif a.Ns or a.Local:
            attr_text += ' %s="%s"' % (a.Name, esc(qval(a.Ns, a.Local)))
        elif a.Name == "qualified":
            attr_text += ' %s:qualified="%s"' % (prefix_of[XDTO_NS], esc(a.Value))
        else:
            attr_text += ' %s="%s"' % (a.Name, esc(a.Value))

    tag_name = node.Tag
    if has_qualified:
        tag_name = "%s:%s" % (prefix_of[XDTO_NS], node.Tag)

    has_children = len(node.Children) > 0
    # Пустое значение пишется самозакрывающимся тегом: <enumeration/>
    has_text = node.Text is not None and node.Text != ""

    if not has_children and not has_text:
        OUT.append("%s<%s%s%s/>\r\n" % (indent, tag_name, ns_decls, attr_text))
        return
    if has_text and not has_children:
        OUT.append("%s<%s%s%s>%s</%s>\r\n"
                   % (indent, tag_name, ns_decls, attr_text, esc_text(node.Text), tag_name))
        return
    OUT.append("%s<%s%s%s>\r\n" % (indent, tag_name, ns_decls, attr_text))
    for c in node.Children:
        serialize_node(c, depth + 1, prefix_of)
    OUT.append("%s</%s>\r\n" % (indent, tag_name))


# --- simpleType -> valueType / typeDef(ValueType) ---

def fill_simple_type(node, st, target_ns):
    restriction = XFirst(st, "restriction")
    lst = XFirst(st, "list")
    union = XFirst(st, "union")

    if lst is not None:
        it = split_qname(lst, XA(lst, "itemType"), target_ns)
        mv = MA(lst, "variety")
        add_attr(node, "variety", mv if mv is not None else "List")
        if it:
            add_qattr(node, "itemType", it.Ns, it.Local)
        return
    if union is not None:
        mv = MA(union, "variety")
        set_attr_value(node, "variety", mv if mv is not None else "Union")
        members = split_qname_list(union, XA(union, "memberTypes"), target_ns)
        # По умолчанию нотация Кларка — так записано 125 из 135 memberTypes корпуса
        use_clark = MA(union, "memberTypesForm") != "prefixed"
        if members:
            add_qlist_attr(node, "memberTypes", members, use_clark)
        node.DeclareNs = MA(union, "declareNs")
        for anon in XChildren(union, "simpleType"):
            # typeDef в контексте простого типа xsi:type не несёт (40 узлов корпуса)
            td = Node("typeDef")
            fill_simple_type(td, anon, target_ns)
            add_child(node, td)
        return
    if restriction is not None:
        b = split_qname(restriction, XA(restriction, "base"), target_ns)
        if b:
            add_qattr(node, "base", b.Ns, b.Local)
        mv = MA(restriction, "variety")
        if mv is not None:
            add_attr(node, "variety", mv)
        # Анонимный базовый тип внутри xs:restriction — typeDef без xsi:type
        anon_base = XFirst(restriction, "simpleType")
        if anon_base is not None:
            td = Node("typeDef")
            fill_simple_type(td, anon_base, target_ns)
            add_child(node, td)
        for f in FACETS:
            for fe in XChildren(restriction, f):
                add_attr(node, f, XA(fe, "value"))
        for pe in XChildren(restriction, "pattern"):
            pn = Node("pattern")
            pn.Text = XA(pe, "value")
            add_child(node, pn)
        for en in XChildren(restriction, "enumeration"):
            enode = Node("enumeration")
            mt = MA(en, "type")
            if mt is not None:
                q = split_qname(en, mt, target_ns)
                add_qattr(enode, "xsi:type", q.Ns, q.Local)
            enode.Text = XA(en, "value")
            add_child(node, enode)


def get_prop_key(p):
    for a in p.Attrs:
        if a.Name == "name":
            return a.Value
    for a in p.Attrs:
        if a.Name == "ref":
            return "@" + a.Local
    return None


def reorder_properties(node, names):
    """Восстановить исходный порядок свойств по зеркалу xdto:order."""
    props = [c for c in node.Children if c.Tag == "property"]
    if len(props) < 2:
        return
    by_key = {}
    for p in props:
        k = get_prop_key(p)
        if k is not None and k not in by_key:
            by_key[k] = p
    ordered = []
    for n in names:
        if n in by_key:
            ordered.append(by_key.pop(n))
    seen = {id(p) for p in ordered}
    for p in props:
        if id(p) not in seen:
            ordered.append(p)
            seen.add(id(p))
    others = [c for c in node.Children if c.Tag != "property"]
    node.Children = ordered + others


# --- element / attribute -> property ---

def build_property(el, is_attribute, target_ns):
    p = Node("property")

    xsd_name = XA(el, "name")
    mirror_name = MA(el, "name")
    if mirror_name is not None:
        add_attr(p, "name", mirror_name)
        local_nm = xsd_name
    else:
        add_attr(p, "name", xsd_name)
        local_nm = None

    ref_q = split_qname(el, XA(el, "ref"), target_ns)
    if ref_q:
        add_qattr(p, "ref", ref_q.Ns, ref_q.Local)

    type_q = split_qname(el, XA(el, "type"), target_ns)
    if type_q:
        add_qattr(p, "type", type_q.Ns, type_q.Local)

    if is_attribute:
        add_attr(p, "lowerBound", MA(el, "lowerBound"))
        add_attr(p, "upperBound", MA(el, "upperBound"))
        add_attr(p, "nillable", MA(el, "nillable"))
    else:
        add_attr(p, "lowerBound", XA(el, "minOccurs"))
        max_occ = XA(el, "maxOccurs")
        if max_occ is not None:
            add_attr(p, "upperBound", "-1" if max_occ == "unbounded" else max_occ)
        add_attr(p, "nillable", XA(el, "nillable"))

    # XSD-шный fixed="V" несёт значение, в модели это fixed="true" + default="V".
    # Прощающий ввод: модельная форма через зеркало xdto:fixed тоже принимается.
    m_fixed = MA(el, "fixed")
    if m_fixed is not None:
        add_attr(p, "fixed", m_fixed)
        add_attr(p, "default", XA(el, "default"))
        if m_fixed == "true" and XA(el, "default") is None:
            warn('Свойство "%s": xdto:fixed="true" без default — платформа отвергнет пакет '
                 '(«Отсутствует фиксированное значение»). Значение задаётся атрибутом default, '
                 'либо пишите XSD-форму fixed="значение"' % XA(el, "name"))
    elif XA(el, "fixed") is not None:
        add_attr(p, "fixed", "true")
        add_attr(p, "default", XA(el, "fixed"))
    else:
        add_attr(p, "default", XA(el, "default"))

    if is_attribute:
        add_attr(p, "form", "Attribute")
    else:
        mf = MA(el, "form")
        if mf is not None:
            add_attr(p, "form", mf)
    add_attr(p, "localName", local_nm)
    add_attr(p, "qualified", MA(el, "qualified"))
    p.Prefix = MA(el, "prefix")

    # Anonymous inline type
    anon_simple = XFirst(el, "simpleType")
    anon_complex = XFirst(el, "complexType")
    if anon_simple is not None:
        td = Node("typeDef")
        add_attr(td, "xsi:type", "ValueType")
        fill_simple_type(td, anon_simple, target_ns)
        add_child(p, td)
    elif anon_complex is not None:
        td = Node("typeDef")
        add_attr(td, "xsi:type", "ObjectType")
        fill_complex_type(td, anon_complex, target_ns)
        add_child(p, td)
    return p


# --- complexType -> objectType / typeDef(ObjectType) ---

# Разрешение xs:group / xs:attributeGroup по ссылке
GROUPS = {}
ATTR_GROUPS = {}


def resolve_group(el, kind, target_ns):
    ref = XA(el, "ref")
    if not ref:
        return None
    q = split_qname(el, ref, target_ns)
    if not q:
        return None
    src = GROUPS if kind == "group" else ATTR_GROUPS
    return src.get(q.Local)


def collect_particle(particle, elem_list, is_open, type_name, depth, target_ns,
                     optionalize=False):
    """Модель XDTO знает только плоский список свойств: вложенные частицы уплощаются.
    Каждое уплощение — предупреждение, потому что меняется смысл схемы."""
    if depth > 20:
        return
    for c in particle:
        if not isinstance(c.tag, str) or not c.tag.startswith("{%s}" % XS_NS):
            continue
        ln = local_name(c)
        if ln == "element":
            prop = build_property(c, False, target_ns)
            # Ветка уплощённого xs:choice обязана стать необязательной: иначе
            # «одно из двух» превращается в «оба сразу», и тип нельзя заполнить
            if optionalize:
                set_attr_value(prop, "lowerBound", "0")
            elem_list.append(prop)
        elif ln == "any":
            is_open[0] = True
        elif ln == "sequence":
            warn("%s : вложенная xs:sequence уплощена — модель XDTO хранит плоский "
                 "список свойств" % type_name)
            collect_particle(c, elem_list, is_open, type_name, depth + 1, target_ns, optionalize)
        elif ln == "choice":
            branches = [b.get("name") for b in c
                        if isinstance(b.tag, str) and b.tag.startswith("{%s}" % XS_NS)
                        and b.get("name") is not None]
            lst = (" (" + ", ".join(branches) + ")") if branches else ""
            warn("%s : вложенная xs:choice уплощена — ветки%s сделаны необязательными. "
                 "Выбор одного из вариантов не сохранён: модель не запретит заполнить "
                 "сразу несколько или ни одного" % (type_name, lst))
            collect_particle(c, elem_list, is_open, type_name, depth + 1, target_ns, True)
        elif ln == "all":
            warn("%s : xs:all трактуется как последовательность" % type_name)
            collect_particle(c, elem_list, is_open, type_name, depth + 1, target_ns, optionalize)
        elif ln == "group":
            g = resolve_group(c, "group", target_ns)
            if g is not None:
                for gc in g:
                    if (isinstance(gc.tag, str) and gc.tag.startswith("{%s}" % XS_NS)
                            and local_name(gc) in ("sequence", "choice", "all")):
                        collect_particle(gc, elem_list, is_open, type_name, depth + 1,
                                         target_ns, optionalize)
            else:
                warn("%s : не найдена группа %s — её свойства в пакет не попали"
                     % (type_name, XA(c, "ref")))
        # Кратность на самой частице модель выразить не может
        if ln in ("sequence", "choice", "all", "group"):
            if XA(c, "maxOccurs") or XA(c, "minOccurs"):
                warn("%s : кратность на вложенной частице (<xs:%s minOccurs/maxOccurs>) "
                     "не выражается в модели XDTO" % (type_name, ln))


def set_type_flags(node, ct, is_open, choice):
    """open / ordered / sequenced / abstract / mixed: выводим где выводимо,
    остальное приходит зеркалом xdto:"""
    m_open = MA(ct, "open")
    if m_open is not None:
        add_attr(node, "open", m_open)
    elif is_open:
        add_attr(node, "open", "true")

    m_ordered = MA(ct, "ordered")
    if m_ordered is not None:
        add_attr(node, "ordered", m_ordered)
    elif choice is not None:
        add_attr(node, "ordered", "false")

    m_seq = MA(ct, "sequenced")
    if m_seq is not None:
        add_attr(node, "sequenced", m_seq)

    m_abstract = MA(ct, "abstract")
    if m_abstract is not None:
        add_attr(node, "abstract", m_abstract)
    elif XA(ct, "abstract") == "true":
        add_attr(node, "abstract", "true")

    m_mixed = MA(ct, "mixed")
    if m_mixed is not None:
        add_attr(node, "mixed", m_mixed)
    elif XA(ct, "mixed") == "true":
        add_attr(node, "mixed", "true")


def fill_complex_type(node, ct, target_ns):
    # xs:complexContent/xs:extension carries the base type
    content = XFirst(ct, "complexContent")
    body = ct
    if content is not None:
        ext = XFirst(content, "extension")
        if ext is not None:
            b = split_qname(ext, XA(ext, "base"), target_ns)
            if b:
                add_qattr(node, "base", b.Ns, b.Local)
            body = ext

    # xs:simpleContent -> a "Text" property holding the element's own value
    simple = XFirst(ct, "simpleContent")
    if simple is not None:
        ext = XFirst(simple, "extension")
        if ext is not None:
            for a in XChildren(ext, "attribute"):
                add_child(node, build_property(a, True, target_ns))
            tp = Node("property")
            t_name = MA(ext, "textName")
            add_attr(tp, "name", t_name if t_name is not None else "__content")
            b = split_qname(ext, XA(ext, "base"), target_ns)
            if b:
                add_qattr(tp, "type", b.Ns, b.Local)
            add_attr(tp, "lowerBound", MA(ext, "textlowerBound"))
            add_attr(tp, "upperBound", MA(ext, "textupperBound"))
            add_attr(tp, "nillable", MA(ext, "textnillable"))
            add_attr(tp, "form", "Text")
            add_child(node, tp)
            # xs:simpleContent не отменяет флаги самого xs:complexType
            set_type_flags(node, ct, False, None)
            return

    # Particle: xs:sequence (ordered) or xs:choice (ordered="false")
    seq = XFirst(body, "sequence")
    cho = XFirst(body, "choice")
    all_ = XFirst(body, "all")
    grp = XFirst(body, "group")
    particle = seq if seq is not None else (cho if cho is not None
                                            else (all_ if all_ is not None else grp))
    is_open = [False]

    # Порядок в XDTO: сначала form="Attribute", потом остальные (верно для 96.5%
    # типов корпуса). Отклонения приходят зеркалом xdto:order.
    elem_props = []
    type_name = ct.get("name") if ct.get("name") is not None else "(анонимный тип)"
    if particle is not None:
        if all_ is not None:
            warn("%s : xs:all трактуется как последовательность" % type_name)
        if grp is not None and seq is None and cho is None and all_ is None:
            # Корневая частица задана ссылкой на группу — раскрываем её содержимое
            g = resolve_group(grp, "group", target_ns)
            if g is not None:
                for gc in g:
                    if (isinstance(gc.tag, str) and gc.tag.startswith("{%s}" % XS_NS)
                            and local_name(gc) in ("sequence", "choice", "all")):
                        collect_particle(gc, elem_props, is_open, type_name, 1, target_ns)
            else:
                warn("%s : не найдена группа %s — её свойства в пакет не попали"
                     % (type_name, XA(grp, "ref")))
        else:
            collect_particle(particle, elem_props, is_open, type_name, 0, target_ns)

    for a in XChildren(body, "attribute"):
        add_child(node, build_property(a, True, target_ns))
    # xs:attributeGroup раскрываем по ссылке
    for ag in XChildren(body, "attributeGroup"):
        g = resolve_group(ag, "attributeGroup", target_ns)
        if g is not None:
            for a in XChildren(g, "attribute"):
                add_child(node, build_property(a, True, target_ns))
        else:
            warn("Не найдена группа атрибутов %s — её атрибуты в пакет не попали"
                 % XA(ag, "ref"))
    for e in elem_props:
        add_child(node, e)
    if XChildren(body, "anyAttribute"):
        is_open[0] = True

    m_order = MA(ct, "order")
    if m_order is not None:
        reorder_properties(node, m_order.split("|"))

    set_type_flags(node, ct, is_open[0], cho)


# --- Configuration.xml registration ---

def register_in_configuration(config_xml_path, name):
    if not os.path.isfile(config_xml_path):
        return "no-config"
    parser = etree.XMLParser(remove_blank_text=False)
    tree = etree.parse(config_xml_path, parser)
    root = tree.getroot()
    ns = {"md": MD_NS}
    found = root.xpath("//md:Configuration/md:ChildObjects", namespaces=ns)
    if not found:
        return "no-childobj"
    child_objects = found[0]

    existing = child_objects.xpath("md:XDTOPackage", namespaces=ns)
    for e in existing:
        if (e.text or "") == name:
            return "already"

    new_elem = etree.SubElement(child_objects, "{%s}XDTOPackage" % MD_NS)
    new_elem.text = name
    child_objects.remove(new_elem)

    if existing:
        last_elem = existing[-1]
        new_elem.tail = last_elem.tail
        last_elem.tail = "\n\t\t\t"
        last_elem.addnext(new_elem)
    elif len(child_objects):
        last_child = child_objects[-1]
        new_elem.tail = last_child.tail
        last_child.tail = "\n\t\t\t"
        last_child.addnext(new_elem)
    else:
        child_objects.text = "\n\t\t\t"
        new_elem.tail = "\n\t\t"
        child_objects.append(new_elem)

    # Пролог и эпилог берём из исходного файла байт в байт: XmlWriter в .ps1
    # работает с PreserveWhitespace, lxml же теряет пробелы вне корня
    with open(config_xml_path, "rb") as f:
        raw = f.read()
    bom = b"\xef\xbb\xbf" if raw.startswith(b"\xef\xbb\xbf") else b""
    body = raw[len(bom):]
    m = re.match(rb"(<\?xml[^>]*\?>)(\s*)", body)
    prologue = (m.group(1) + m.group(2)) if m else b'<?xml version="1.0" encoding="UTF-8"?>\n'
    epilogue = re.search(rb"(\s*)\Z", body).group(1)

    data = etree.tostring(root, encoding="unicode").encode("utf-8")
    # lxml нормализует переводы строк в LF; исходный стиль файла сохраняем
    if b"\r\n" in body:
        data = data.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
    with open(config_xml_path, "wb") as f:
        f.write(bom + prologue + data + epilogue)
    return "added"


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(
        description="Build a 1C XDTO package from an XML Schema (XSD)",
        allow_abbrev=False)
    parser.add_argument("-XsdPath", "-Path", dest="XsdPath", default=None)
    parser.add_argument("-Xsd", dest="Xsd", default=None)
    parser.add_argument("-OutputDir", dest="OutputDir", required=True)
    parser.add_argument("-Name", dest="Name", default=None)
    # Строка ("Синоним") либо JSON-объект ('{"ru":"...","en":"..."}')
    parser.add_argument("-Synonym", dest="Synonym", default=None)
    parser.add_argument("-Comment", dest="Comment", default=None)
    parser.add_argument("-Force", dest="Force", action="store_true")
    args = parser.parse_args()

    if bool(args.XsdPath) == bool(args.Xsd):
        print("Укажите ровно один источник схемы: -XsdPath <файл> или -Xsd <текст>",
              file=sys.stderr)
        sys.exit(1)

    # --- Load the schema ---
    if args.Xsd:
        xsd_text = args.Xsd
        default_name = "Package"
    else:
        if not os.path.isfile(args.XsdPath):
            print("Файл XSD не найден: %s" % args.XsdPath, file=sys.stderr)
            sys.exit(1)
        with open(args.XsdPath, "r", encoding="utf-8-sig") as f:
            xsd_text = f.read()
        default_name = os.path.splitext(os.path.basename(args.XsdPath))[0]

    try:
        schema = etree.fromstring(xsd_text.encode("utf-8"))
    except Exception as ex:
        print("Не удалось разобрать XSD: %s" % ex, file=sys.stderr)
        sys.exit(1)

    if local_name(schema) != "schema" or not schema.tag.startswith("{%s}" % XS_NS):
        print("Ожидался корневой <xs:schema> в пространстве имён %s" % XS_NS, file=sys.stderr)
        sys.exit(1)

    target_ns = schema.get("targetNamespace")

    # --- Build the package tree ---
    pkg_node = Node("package")
    add_attr(pkg_node, "targetNamespace", target_ns)

    efq_mirror = MA(schema, "elementFormQualified")
    afq_mirror = MA(schema, "attributeFormQualified")
    efd = XA(schema, "elementFormDefault")
    afd = XA(schema, "attributeFormDefault")
    if efq_mirror is not None:
        add_attr(pkg_node, "elementFormQualified", efq_mirror)
    elif efd is not None:
        add_attr(pkg_node, "elementFormQualified", "true" if efd == "qualified" else "false")
    if afq_mirror is not None:
        add_attr(pkg_node, "attributeFormQualified", afq_mirror)
    elif afd is not None:
        add_attr(pkg_node, "attributeFormQualified", "true" if afd == "qualified" else "false")

    # Metadata properties from xs:annotation/xs:appinfo
    meta_name = None
    meta_comment = None
    meta_synonym = []
    ann = XFirst(schema, "annotation")
    if ann is not None:
        appinfo = XFirst(ann, "appinfo")
        if appinfo is not None:
            for pk in appinfo:
                if not isinstance(pk.tag, str) or not pk.tag.startswith("{%s}" % XDTO_NS):
                    continue
                for f in pk:
                    if not isinstance(f.tag, str):
                        continue
                    ln = local_name(f)
                    if ln == "name":
                        meta_name = "".join(f.itertext())
                    elif ln == "comment":
                        meta_comment = "".join(f.itertext())
                    elif ln == "synonym":
                        meta_synonym.append({"Lang": f.get("lang") or "",
                                             "Content": "".join(f.itertext())})

    # Реестр глобальных групп — нужен до обхода, чтобы раскрывать ссылки
    for node in elements(schema):
        if not node.tag.startswith("{%s}" % XS_NS):
            continue
        nm = XA(node, "name")
        ln = local_name(node)
        if ln == "group" and nm:
            GROUPS[nm] = node
        if ln == "attributeGroup" and nm:
            ATTR_GROUPS[nm] = node

    # Конструкции XSD, которым в модели XDTO нет соответствия
    for sg in schema.xpath("//*[local-name()='element'][@substitutionGroup]"):
        warn("Подстановочные группы (substitutionGroup) не поддерживаются моделью XDTO — "
             "объявление %s сохранено как обычное" % sg.get("name"))
    for idc in ("key", "keyref", "unique"):
        if schema.xpath("//*[local-name()='%s']" % idc):
            warn("Ограничения целостности (xs:%s) в модели XDTO не хранятся — отброшены" % idc)
    if schema.xpath("//*[local-name()='redefine']"):
        warn("xs:redefine не поддерживается — переопределения проигнорированы")
    if schema.xpath("//*[local-name()='include']"):
        warn("xs:include проигнорирован: модель XDTO разрешает зависимости только по "
             "namespace. Соберите включаемую схему отдельным пакетом и добавьте <xs:import>")

    for node in elements(schema):
        if not node.tag.startswith("{%s}" % XS_NS):
            continue
        ln = local_name(node)
        if ln in ("annotation", "group", "attributeGroup", "notation", "include"):
            continue
        if ln == "import":
            n = Node("import")
            add_attr(n, "namespace", XA(node, "namespace"))
            add_child(pkg_node, n)
        elif ln == "element":
            add_child(pkg_node, build_property(node, False, target_ns))
        elif ln == "attribute":
            add_child(pkg_node, build_property(node, True, target_ns))
        elif ln == "simpleType":
            n = Node("valueType")
            add_attr(n, "name", XA(node, "name"))
            fill_simple_type(n, node, target_ns)
            add_child(pkg_node, n)
        elif ln == "complexType":
            n = Node("objectType")
            add_attr(n, "name", XA(node, "name"))
            fill_complex_type(n, node, target_ns)
            add_child(pkg_node, n)

    # --- Serialize Package.bin ---
    # Модель XDTO требует строгой последовательности элементов верхнего уровня:
    # import → property → valueType → objectType. Порядок объявлений в XSD произвольный,
    # поэтому пересортировываем — иначе платформа отвергает пакет с «Ошибка преобразования
    # данных XDTO». Все 760 пакетов корпуса этому порядку удовлетворяют, так что
    # round-trip не затрагивается.
    top_order = ("import", "property", "valueType", "objectType")
    sorted_children = []
    for t in top_order:
        sorted_children += [c for c in pkg_node.Children if c.Tag == t]
    sorted_children += [c for c in pkg_node.Children if c.Tag not in top_order]
    pkg_node.Children = sorted_children

    root_attr_text = ""
    for a in sort_attrs(pkg_node):
        root_attr_text += ' %s="%s"' % (a.Name, esc(a.Value))
    OUT.append('<package xmlns="%s" xmlns:xs="%s" xmlns:xsi="%s"%s>\r\n'
               % (XDTO_NS, XS_NS, XSI_NS, root_attr_text))
    for c in pkg_node.Children:
        serialize_node(c, 2, {})
    OUT.append("</package>")

    bin_text = "".join(OUT)

    # --- Resolve the package name ---
    name = args.Name
    if not name:
        name = meta_name if meta_name else default_name
    # Санация под идентификатор 1С
    name = re.sub(r"[^\wЀ-ӿ]", "_", name)
    if re.match(r"^\d", name):
        name = "_" + name

    output_dir = args.OutputDir
    support_guard.assert_edit_allowed(output_dir, "editable")

    pkg_root = os.path.join(output_dir, "XDTOPackages")
    pkg_dir = os.path.join(pkg_root, name)
    ext_dir = os.path.join(pkg_dir, "Ext")
    md_file = os.path.join(pkg_root, name + ".xml")
    bin_file = os.path.join(ext_dir, "Package.bin")

    if os.path.exists(bin_file) and not args.Force:
        print("Пакет уже существует: %s. Используйте -Force для перезаписи." % bin_file,
              file=sys.stderr)
        sys.exit(1)
    os.makedirs(ext_dir, exist_ok=True)

    with open(bin_file, "w", encoding="utf-8-sig", newline="") as f:
        f.write(bin_text)

    # --- Metadata object file ---
    synonym_arg = args.Synonym
    if not synonym_arg and meta_synonym:
        syn_items = meta_synonym
    elif synonym_arg:
        syn_items = None
        s = synonym_arg.strip()
        if s.startswith("{"):
            try:
                d = json.loads(s)
                syn_items = [{"Lang": str(k), "Content": str(v)} for k, v in d.items()]
            except ValueError:
                syn_items = None
        if syn_items is None:
            syn_items = [{"Lang": "ru", "Content": synonym_arg}]
    else:
        syn_items = [{"Lang": "ru", "Content": name}]
    comment = args.Comment
    if not comment and meta_comment:
        comment = meta_comment

    # Пересборка существующего пакета: идентичность объекта и версия формата
    # принадлежат конфигурации, а не сборщику — забираем их из текущего файла
    pkg_uuid = None
    md_version = "2.17"
    if os.path.isfile(md_file):
        try:
            existing_root = etree.parse(md_file).getroot()
            v = existing_root.get("version")
            if v:
                md_version = v
            for child in existing_root:
                if isinstance(child.tag, str) and child.get("uuid"):
                    pkg_uuid = child.get("uuid")
                    break
        except Exception:
            pass
    if not pkg_uuid:
        pkg_uuid = str(uuid_mod.uuid4())

    md_lines = []

    def M(s):
        md_lines.append(s + "\r\n")

    M('<?xml version="1.0" encoding="UTF-8"?>')
    M('<MetaDataObject xmlns="http://v8.1c.ru/8.3/MDClasses" '
      'xmlns:app="http://v8.1c.ru/8.2/managed-application/core" '
      'xmlns:cfg="http://v8.1c.ru/8.1/data/enterprise/current-config" '
      'xmlns:cmi="http://v8.1c.ru/8.2/managed-application/cmi" '
      'xmlns:ent="http://v8.1c.ru/8.1/data/enterprise" '
      'xmlns:lf="http://v8.1c.ru/8.2/managed-application/logform" '
      'xmlns:style="http://v8.1c.ru/8.1/data/ui/style" '
      'xmlns:sys="http://v8.1c.ru/8.1/data/ui/fonts/system" '
      'xmlns:v8="http://v8.1c.ru/8.1/data/core" '
      'xmlns:v8ui="http://v8.1c.ru/8.1/data/ui" '
      'xmlns:web="http://v8.1c.ru/8.1/data/ui/colors/web" '
      'xmlns:win="http://v8.1c.ru/8.1/data/ui/colors/windows" '
      'xmlns:xen="http://v8.1c.ru/8.3/xcf/enums" '
      'xmlns:xpr="http://v8.1c.ru/8.3/xcf/predef" '
      'xmlns:xr="http://v8.1c.ru/8.3/xcf/readable" '
      'xmlns:xs="http://www.w3.org/2001/XMLSchema" '
      'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" version="%s">' % md_version)
    M('\t<XDTOPackage uuid="%s">' % pkg_uuid)
    M("\t\t<Properties>")
    M("\t\t\t<Name>%s</Name>" % esc_text(name))
    M("\t\t\t<Synonym>")
    for s in syn_items:
        M("\t\t\t\t<v8:item>")
        M("\t\t\t\t\t<v8:lang>%s</v8:lang>" % esc_text(s["Lang"]))
        M("\t\t\t\t\t<v8:content>%s</v8:content>" % esc_text(s["Content"]))
        M("\t\t\t\t</v8:item>")
    M("\t\t\t</Synonym>")
    if comment:
        M("\t\t\t<Comment>%s</Comment>" % esc_text(comment))
    else:
        M("\t\t\t<Comment/>")
    M("\t\t\t<Namespace>%s</Namespace>" % esc_text(target_ns))
    M("\t\t</Properties>")
    M("\t</XDTOPackage>")
    md_lines.append("</MetaDataObject>")

    with open(md_file, "w", encoding="utf-8-sig", newline="") as f:
        f.write("".join(md_lines))

    # --- Register in Configuration.xml ---
    # Ранняя диагностика: отказ платформы при db-update дешевле поймать на сборке
    declared_imports = []
    for c in pkg_node.Children:
        if c.Tag == "import":
            for a in c.Attrs:
                if a.Name == "namespace":
                    declared_imports.append(a.Value)
    if declared_imports and os.path.isdir(pkg_root):
        known_ns = set()
        for entry in os.listdir(pkg_root):
            ob = os.path.join(pkg_root, entry, "Ext", "Package.bin")
            if not os.path.isfile(ob):
                continue
            try:
                known_ns.add(etree.parse(ob).getroot().get("targetNamespace"))
            except Exception:
                pass
        for imp in declared_imports:
            if imp not in known_ns and imp not in PLATFORM_NS:
                warn('Импорт "%s" не разрешается: пакета с таким namespace в конфигурации '
                     "нет. Платформа отвергнет пакет при обновлении — соберите зависимость "
                     "первой" % imp)

    reg_result = register_in_configuration(os.path.join(output_dir, "Configuration.xml"), name)

    # --- Report ---
    type_count = sum(1 for c in pkg_node.Children if c.Tag in ("objectType", "valueType"))

    print("✓ Пакет XDTO собран: %s" % name)
    print("  Namespace: %s" % target_ns)
    print("  Типов: %d" % type_count)
    print("  Файлы: XDTOPackages/%s.xml, XDTOPackages/%s/Ext/Package.bin" % (name, name))
    if WARNINGS:
        print("")
        print("Предупреждения (%d) — конструкции XSD без точного соответствия в модели XDTO:"
              % len(WARNINGS))
        for w in WARNINGS:
            print("  ! %s" % w)
        print("")
    if reg_result == "added":
        print("  Configuration.xml: <XDTOPackage>%s</XDTOPackage> добавлен в ChildObjects" % name)
    elif reg_result == "already":
        print("  Configuration.xml: <XDTOPackage>%s</XDTOPackage> уже зарегистрирован" % name)
    elif reg_result == "no-config":
        print("  Configuration.xml не найден — регистрация пропущена")


if __name__ == "__main__":
    main()
