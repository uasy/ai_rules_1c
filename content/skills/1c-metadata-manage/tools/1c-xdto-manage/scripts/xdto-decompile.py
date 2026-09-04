#!/usr/bin/env python3
# xdto-decompile v1.0 — Convert 1C XDTO package to XML Schema (XSD)
# Source: https://github.com/Nikolay-Shirokov/cc-1c-skills

import argparse
import os
import re
import sys

from lxml import etree

XDTO_NS = "http://v8.1c.ru/8.1/xdto"
XS_NS = "http://www.w3.org/2001/XMLSchema"
XSI_NS = "http://www.w3.org/2001/XMLSchema-instance"
MD_NS = "http://v8.1c.ru/8.3/MDClasses"
V8_NS = "http://v8.1c.ru/8.1/data/core"

FACET_ATTRS = ("length", "minLength", "maxLength", "totalDigits", "fractionDigits",
               "minInclusive", "maxInclusive", "minExclusive", "maxExclusive", "whiteSpace")

DNPM_RE = re.compile(r'^d\d+p\d+$')


def local_name(node):
    return etree.QName(node.tag).localname


def inner_text(node):
    return "".join(node.itertext())


def elements(parent):
    return [c for c in parent if isinstance(c.tag, str)]


def A(el, name):
    """Attribute value, or None when absent (mirrors PowerShell's HasAttribute check)."""
    return el.get(name)


def own_nsmap(el):
    """Prefixes declared ON this element (lxml exposes only the inherited map)."""
    parent = el.getparent()
    parent_map = parent.nsmap if parent is not None else {}
    return {k: v for k, v in el.nsmap.items() if parent_map.get(k) != v}


class S:
    """Emitter state."""
    ns_prefix = {}
    uses_xdto_ns = False
    lines = []
    target_ns = None


def X(line):
    S.lines.append(line)


def esc(s):
    if s is None:
        return ""
    return (str(s).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def esc_text(s):
    if s is None:
        return ""
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def register_ns(ns):
    """A foreign namespace that is referenced but not imported still needs a prefix."""
    if not ns:
        return
    if ns not in S.ns_prefix:
        S.ns_prefix[ns] = "ns" + str(len(S.ns_prefix))


def convert_qname(el, qname):
    """bin prefix -> schema prefix."""
    if not qname:
        return None
    if qname.startswith("{"):   # Clark notation {ns}local — almost all memberTypes
        close = qname.find("}")
        if close > 0:
            ns, local = qname[1:close], qname[close + 1:]
            if not ns:
                return local
            register_ns(ns)
            return f"{S.ns_prefix[ns]}:{local}"
    parts = qname.split(":")
    if len(parts) == 2:
        ns, local = el.nsmap.get(parts[0]), parts[1]
    else:
        ns, local = el.nsmap.get(None), parts[0]
    if not ns:
        return qname
    register_ns(ns)
    return f"{S.ns_prefix[ns]}:{local}"


def convert_qname_list(el, lst):
    if not lst:
        return None
    return " ".join(convert_qname(el, q) for q in lst.split() if q)


def attrs(pairs):
    """`key="value"` pairs, skipping Nones."""
    out = ""
    for i in range(0, len(pairs), 2):
        v = pairs[i + 1]
        if v is not None:
            out += f' {pairs[i]}="{esc(v)}"'
    return out


# --- xdto: mirror attributes ---
# Everything XSD cannot express literally rides as xdto:<same name as in
# Package.bin>. Mirrors are emitted only when the literal bin form is not
# recoverable from the XSD.

def mirror(name, value):
    if value is None:
        return ""
    S.uses_xdto_ns = True
    return f' xdto:{name}="{esc(value)}"'


def mirror_prefix(el):
    """Prefixes are normally generated as dNpM, but a node occasionally carries a
    meaningful one (dcsset, say) — keep it, or the round-trip will not match."""
    for k in own_nsmap(el):
        if k is None or DNPM_RE.match(k):
            continue
        return mirror("prefix", k)
    return ""


def emit_facets(el, indent):
    for f in FACET_ATTRS:
        v = A(el, f)
        if v is not None:
            X(f'{indent}<xs:{f} value="{esc(v)}"/>')
    for child in elements(el):
        ln = local_name(child)
        if ln == "pattern":
            X(f'{indent}<xs:pattern value="{esc(inner_text(child))}"/>')
        elif ln == "enumeration":
            # xsi:type on enumeration has no XSD counterpart — mirror it
            xsi_type = child.get(f"{{{XSI_NS}}}type")
            m = mirror("type", convert_qname(child, xsi_type)) if xsi_type else ""
            X(f'{indent}<xs:enumeration value="{esc(inner_text(child))}"{m}/>')


def has_simple_content(el):
    for c in elements(el):
        if local_name(c) in ("pattern", "enumeration"):
            return True
    return any(A(el, f) is not None for f in FACET_ATTRS)


def emit_simple_type_body(el, indent):
    variety = A(el, "variety")
    base = convert_qname(el, A(el, "base"))
    item_type = convert_qname(el, A(el, "itemType"))
    member_types = convert_qname_list(el, A(el, "memberTypes"))

    # variety is mirrored: "Atomic" is written explicitly for only part of the corpus
    mv = mirror("variety", variety)

    # memberTypes are almost always in Clark notation; the rare prefixed form is mirrored
    raw_members = A(el, "memberTypes")
    if raw_members is not None and not raw_members.startswith("{"):
        mv += mirror("memberTypesForm", "prefixed")
    # With Clark notation the xmlns:dNpM declaration is sometimes present and
    # sometimes not — that cannot be derived from the value (it depends on the
    # serializer's state), so mirror the fact.
    if raw_members is not None and raw_members.startswith("{"):
        for k, v in own_nsmap(el).items():
            if k and DNPM_RE.match(k):
                mv += mirror("declareNs", v)
                break

    if variety == "List" or item_type:
        X(f'{indent}<xs:list{attrs(["itemType", item_type])}{mv}/>')
        return
    if variety == "Union" or member_types:
        anon = [c for c in elements(el) if local_name(c) == "typeDef"]
        if not anon:
            X(f'{indent}<xs:union{attrs(["memberTypes", member_types])}{mv}/>')
        else:
            X(f'{indent}<xs:union{attrs(["memberTypes", member_types])}{mv}>')
            for c in anon:
                X(f"{indent}\t<xs:simpleType>")
                emit_simple_type_body(c, indent + "\t\t")
                X(f"{indent}\t</xs:simpleType>")
            X(f"{indent}</xs:union>")
        return

    # The base type may come from a nested anonymous typeDef instead of `base`
    anon_base = next((c for c in elements(el) if local_name(c) == "typeDef"), None)

    if has_simple_content(el) or anon_base is not None:
        X(f'{indent}<xs:restriction{attrs(["base", base])}{mv}>')
        if anon_base is not None:
            X(f"{indent}\t<xs:simpleType>")
            emit_simple_type_body(anon_base, indent + "\t\t")
            X(f"{indent}\t</xs:simpleType>")
        emit_facets(el, indent + "\t")
        X(f"{indent}</xs:restriction>")
    else:
        X(f'{indent}<xs:restriction{attrs(["base", base])}{mv}/>')


def get_prop_form(p):
    f = A(p, "form")
    return "Element" if f is None else f


def get_anon_type_def(p):
    return next((c for c in elements(p) if local_name(c) == "typeDef"), None)


def emit_property(p, indent, is_global):
    form = get_prop_form(p)
    name = A(p, "name")
    type_ = convert_qname(p, A(p, "type"))
    ref = convert_qname(p, A(p, "ref"))
    local = A(p, "localName")
    lower = A(p, "lowerBound")
    upper = A(p, "upperBound")
    nill = A(p, "nillable")
    default = A(p, "default")
    fix = A(p, "fixed")
    # In the model `fixed` is a boolean flag and the value lives in `default`;
    # in XSD it is the other way round: fixed="V" carries the value itself.
    # Translate rather than copy.
    def_out, fix_out, fix_mirror = default, None, ""
    if fix == "true" and default is not None:
        fix_out, def_out = default, None
    elif fix is not None:
        fix_mirror = mirror("fixed", fix)
    anon = get_anon_type_def(p)
    # `qualified` is written as an attribute in the XDTO namespace
    qual = p.get(f"{{{XDTO_NS}}}qualified") or None

    # lowerBound/upperBound map 1:1 onto minOccurs/maxOccurs, "written explicitly" included
    min_occurs = lower
    max_occurs = None
    if upper is not None:
        max_occurs = "unbounded" if upper == "-1" else upper

    # localName carries the original XML name when it is not a valid 1C identifier
    xml_name = local if local is not None else name
    mirror_name = mirror("name", name) if local is not None else ""

    m = ""
    if form == "Attribute":
        # XSD forbids nillable on attributes, and has no minOccurs/maxOccurs
        if qual is not None:
            m += mirror("qualified", qual)
        if nill is not None:
            m += mirror("nillable", nill)
        if lower is not None:
            m += mirror("lowerBound", lower)
        if upper is not None:
            m += mirror("upperBound", upper)
        m += mirror_name
        m += fix_mirror
        body = attrs(["name", xml_name, "ref", ref, "type", type_,
                      "default", def_out, "fixed", fix_out])
        if anon is not None:
            X(f"{indent}<xs:attribute{body}{m}>")
            X(f"{indent}\t<xs:simpleType>")
            emit_simple_type_body(anon, indent + "\t\t")
            X(f"{indent}\t</xs:simpleType>")
            X(f"{indent}</xs:attribute>")
        else:
            X(f"{indent}<xs:attribute{body}{m}/>")
        return

    if form == "Text":
        # handled by the owning complexType (xs:simpleContent)
        return

    # form="Element" written explicitly is indistinguishable in XSD from the default
    if A(p, "form") is not None:
        m += mirror("form", form)
    if qual is not None:
        m += mirror("qualified", qual)
    m += mirror_name
    m += mirror_prefix(p)
    m += fix_mirror

    body = attrs(["name", xml_name, "ref", ref, "type", type_,
                  "minOccurs", min_occurs, "maxOccurs", max_occurs,
                  "nillable", nill, "default", def_out, "fixed", fix_out])

    if anon is not None:
        X(f"{indent}<xs:element{body}{m}>")
        if anon.get(f"{{{XSI_NS}}}type") == "ObjectType":
            anon_base = convert_qname(anon, A(anon, "base"))
            if anon_base:
                X(f"{indent}\t<xs:complexType{complex_type_attrs(anon)}>")
                X(f"{indent}\t\t<xs:complexContent>")
                X(f'{indent}\t\t\t<xs:extension{attrs(["base", anon_base])}>')
                emit_complex_type_body(anon, indent + "\t\t\t\t")
                X(f"{indent}\t\t\t</xs:extension>")
                X(f"{indent}\t\t</xs:complexContent>")
                X(f"{indent}\t</xs:complexType>")
            else:
                X(f"{indent}\t<xs:complexType{complex_type_attrs(anon)}>")
                emit_complex_type_body(anon, indent + "\t\t")
                X(f"{indent}\t</xs:complexType>")
        else:
            X(f"{indent}\t<xs:simpleType>")
            emit_simple_type_body(anon, indent + "\t\t")
            X(f"{indent}\t</xs:simpleType>")
        X(f"{indent}</xs:element>")
    else:
        X(f"{indent}<xs:element{body}{m}/>")


def emit_complex_type_body(el, indent):
    open_ = A(el, "open")
    ordered = A(el, "ordered")

    props = [c for c in elements(el) if local_name(c) == "property"]
    elems, attrs_list, text = [], [], None
    for p in props:
        f = get_prop_form(p)
        if f == "Attribute":
            attrs_list.append(p)
        elif f == "Text":
            text = p
        else:
            elems.append(p)

    # simpleContent: a "Text" property holds the element's own value
    if text is not None:
        t_type = convert_qname(text, A(text, "type"))
        tm = ""
        t_name = A(text, "name")
        if t_name != "__content":
            tm += mirror("textName", t_name)
        for extra in ("lowerBound", "upperBound", "nillable"):
            v = A(text, extra)
            if v is not None:
                tm += mirror("text" + extra, v)
        X(f"{indent}<xs:simpleContent>")
        X(f'{indent}\t<xs:extension{attrs(["base", t_type])}{tm}>')
        for a in attrs_list:
            emit_property(a, indent + "\t\t", False)
        X(f"{indent}\t</xs:extension>")
        X(f"{indent}</xs:simpleContent>")
        return

    particle_tag = "xs:choice" if ordered == "false" else "xs:sequence"
    if elems or open_ == "true":
        X(f"{indent}<{particle_tag}>")
        for e in elems:
            emit_property(e, indent + "\t", False)
        if open_ == "true":
            X(f'{indent}\t<xs:any namespace="##any" processContents="lax" '
              f'minOccurs="0" maxOccurs="unbounded"/>')
        X(f"{indent}</{particle_tag}>")

    for a in attrs_list:
        emit_property(a, indent, False)
    if open_ == "true":
        X(f'{indent}<xs:anyAttribute namespace="##any" processContents="lax"/>')


def complex_type_attrs(el):
    """Attributes of a complexType tag itself (mirrors + XSD-native abstract/mixed)."""
    open_ = A(el, "open")
    ordered = A(el, "ordered")
    sequenced = A(el, "sequenced")
    abstract = A(el, "abstract")
    mixed = A(el, "mixed")

    out = ""
    if abstract == "true":
        out += ' abstract="true"'
    elif abstract is not None:
        out += mirror("abstract", abstract)
    if mixed == "true":
        out += ' mixed="true"'
    elif mixed is not None:
        out += mirror("mixed", mixed)

    # XSD requires attributes after the particle, so the original property order
    # is restored as "form=Attribute first, then the rest" — true for 96.5% of the
    # corpus. Divergences (768 types) are mirrored as a name list.
    order, kinds = [], []
    for c in elements(el):
        if local_name(c) != "property":
            continue
        nm = A(c, "name")
        if nm is None:
            nm = "@" + (A(c, "ref") or "").split(":")[-1]
        order.append(nm)
        kinds.append(0 if get_prop_form(c) == "Attribute" else 1)
    if len(order) > 1:
        natural = all(kinds[i] >= kinds[i - 1] for i in range(1, len(kinds)))
        if not natural:
            out += mirror("order", "|".join(order))

    # open="true" is rendered as xs:any + xs:anyAttribute; anything else is mirrored
    if open_ is not None and open_ != "true":
        out += mirror("open", open_)
    # ordered="false" is rendered as xs:choice; "true" written explicitly is mirrored
    if ordered is not None and ordered != "false":
        out += mirror("ordered", ordered)
    # sequenced has no XSD counterpart at all
    if sequenced is not None:
        out += mirror("sequenced", sequenced)
    return out


def resolve_package_paths(p):
    """Accept a package dir, Package.bin, or the metadata .xml."""
    bin_path = md_path = None
    if os.path.isfile(p):
        if os.path.basename(p) == "Package.bin":
            bin_path = p
            # <Name>/Ext/Package.bin -> <Name>.xml
            pkg_dir = os.path.dirname(os.path.dirname(p))
            if os.path.isfile(pkg_dir + ".xml"):
                md_path = pkg_dir + ".xml"
        elif p.endswith(".xml"):
            md_path = p
            pkg_dir = os.path.join(os.path.dirname(p), os.path.splitext(os.path.basename(p))[0])
            cand = os.path.join(pkg_dir, "Ext", "Package.bin")
            if os.path.isfile(cand):
                bin_path = cand
    elif os.path.isdir(p):
        cand = os.path.join(p, "Ext", "Package.bin")
        if os.path.isfile(cand):
            bin_path = cand
            md_cand = p.rstrip("\\/") + ".xml"
            if os.path.isfile(md_cand):
                md_path = md_cand
    if not bin_path:
        print(f"Не найден Ext/Package.bin для пути: {p}", file=sys.stderr)
        sys.exit(1)
    return bin_path, md_path


def get_metadata_block(md_path):
    """Name / Synonym / Comment from the object's .xml."""
    if not md_path or not os.path.isfile(md_path):
        return None
    ns = {"md": MD_NS, "v8": V8_NS}
    root = etree.parse(md_path).getroot()
    found = root.xpath("//md:XDTOPackage/md:Properties", namespaces=ns)
    if not found:
        return None
    props = found[0]
    res = {"Name": None, "Comment": None, "Synonym": []}
    n = props.xpath("md:Name", namespaces=ns)
    if n:
        res["Name"] = inner_text(n[0])
    c = props.xpath("md:Comment", namespaces=ns)
    if c:
        res["Comment"] = inner_text(c[0])
    for item in props.xpath("md:Synonym/v8:item", namespaces=ns):
        lang = item.xpath("v8:lang", namespaces=ns)
        cont = item.xpath("v8:content", namespaces=ns)
        res["Synonym"].append({"Lang": inner_text(lang[0]) if lang else "",
                               "Content": inner_text(cont[0]) if cont else ""})
    return res


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Convert 1C XDTO package to XML Schema (XSD)",
                                     allow_abbrev=False)
    parser.add_argument("-PackagePath", "-Path", dest="PackagePath", required=True)
    parser.add_argument("-OutFile", default="")
    args = parser.parse_args()

    package_path = args.PackagePath
    if not os.path.isabs(package_path):
        package_path = os.path.join(os.getcwd(), package_path)
    bin_path, md_path = resolve_package_paths(package_path)

    pkg = etree.parse(bin_path).getroot()
    if local_name(pkg) != "package":
        print(f"Ожидался корневой <package>, получен <{local_name(pkg)}>", file=sys.stderr)
        sys.exit(1)

    S.target_ns = pkg.get("targetNamespace")
    S.ns_prefix = {XS_NS: "xs"}
    if S.target_ns:
        S.ns_prefix[S.target_ns] = "tns"
    for imp in elements(pkg):
        if local_name(imp) != "import":
            continue
        ns = imp.get("namespace")
        if ns not in S.ns_prefix:
            S.ns_prefix[ns] = "ns" + str(len(S.ns_prefix))

    meta = get_metadata_block(md_path)

    # Body first: emitting it registers every namespace actually referenced, so
    # the schema element can declare a complete prefix map.
    S.lines = []
    for node in elements(pkg):
        ln = local_name(node)
        if ln == "import":
            X(f'\t<xs:import namespace="{esc(node.get("namespace"))}"/>')
        elif ln == "property":
            emit_property(node, "\t", True)
        elif ln == "valueType":
            X(f'\t<xs:simpleType{attrs(["name", A(node, "name")])}>')
            emit_simple_type_body(node, "\t\t")
            X("\t</xs:simpleType>")
        elif ln == "objectType":
            name = A(node, "name")
            base = convert_qname(node, A(node, "base"))
            cta = complex_type_attrs(node)
            if base:
                X(f'\t<xs:complexType{attrs(["name", name])}{cta}>')
                X("\t\t<xs:complexContent>")
                X(f'\t\t\t<xs:extension{attrs(["base", base])}>')
                emit_complex_type_body(node, "\t\t\t\t")
                X("\t\t\t</xs:extension>")
                X("\t\t</xs:complexContent>")
                X("\t</xs:complexType>")
            else:
                has_body = bool(elements(node))
                if not has_body and A(node, "open") != "true":
                    X(f'\t<xs:complexType{attrs(["name", name])}{cta}/>')
                else:
                    X(f'\t<xs:complexType{attrs(["name", name])}{cta}>')
                    emit_complex_type_body(node, "\t\t")
                    X("\t</xs:complexType>")
    body = S.lines

    # --- Schema element ---
    S.lines = []
    ns_decls = ""
    for ns, prefix in sorted(S.ns_prefix.items(), key=lambda kv: kv[1]):
        ns_decls += f' xmlns:{prefix}="{esc(ns)}"'
    if S.uses_xdto_ns:
        ns_decls += f' xmlns:xdto="{XDTO_NS}"'

    schema_attrs = ""
    efq = A(pkg, "elementFormQualified")
    afq = A(pkg, "attributeFormQualified")
    if efq is not None:
        schema_attrs += f' elementFormDefault="{"qualified" if efq == "true" else "unqualified"}"'
    if afq is not None:
        schema_attrs += f' attributeFormDefault="{"qualified" if afq == "true" else "unqualified"}"'

    X(f'<xs:schema{ns_decls}{attrs(["targetNamespace", S.target_ns])}{schema_attrs}>')

    if meta:
        X("\t<xs:annotation>")
        X("\t\t<xs:appinfo>")
        X(f'\t\t\t<xdto:package xmlns:xdto="{XDTO_NS}">')
        if meta["Name"] is not None:
            X(f'\t\t\t\t<xdto:name>{esc_text(meta["Name"])}</xdto:name>')
        if meta["Comment"]:
            X(f'\t\t\t\t<xdto:comment>{esc_text(meta["Comment"])}</xdto:comment>')
        for s in meta["Synonym"]:
            X(f'\t\t\t\t<xdto:synonym lang="{esc(s["Lang"])}">'
              f'{esc_text(s["Content"])}</xdto:synonym>')
        X("\t\t\t</xdto:package>")
        X("\t\t</xs:appinfo>")
        X("\t</xs:annotation>")

    S.lines += body
    X("</xs:schema>")

    # --- Output (UTF-8 with BOM, CRLF — matches the Designer's own XSD export) ---
    text = "".join(line + "\r\n" for line in S.lines)
    if args.OutFile:
        d = os.path.dirname(args.OutFile)
        if d:
            os.makedirs(d, exist_ok=True)
        with open(args.OutFile, "w", encoding="utf-8-sig", newline="") as f:
            f.write(text)
        print(f"✓ XSD записана: {args.OutFile}")
        print(f"  targetNamespace: {S.target_ns}")
    else:
        sys.stdout.write(text)


if __name__ == "__main__":
    main()
