#!/usr/bin/env python3
# dcs-query-fields-extractor v1.0 — pull the query text and referenced
# tables/registers out of a Report's (or DataProcessor's) embedded Data
# Composition Schema, without requiring a human to open and read the whole
# Template.xml by hand.
#
# Companion to the rest of 1c-extension-analysis's tools. Born from a concrete
# classification mistake found comparing two independent analyses of the same real
# extension: a wholly new report was grouped by one analysis into the same
# functional block as unrelated subdivision-tracking objects purely because of a
# shared name suffix. Reading the report's actual DCS query showed it aggregates
# turnovers from three unrelated payroll/bookkeeping accumulation registers and
# does not reference those subdivision-tracking objects at all. The other analysis,
# which did read the query, correctly identified this report as the answer to a
# separately-described "bookkeeping adaptation" requirement, unrelated to the
# subdivision-tracking objects. Grouping a wholly-new Report by name similarity
# instead of by what its query actually reads is exactly the mistake this tool is
# meant to make cheap to avoid — SKILL.md step 3 now requires running it (or
# reading the query by hand) before assigning such an object to a functional
# block. See docs/dcs-query-fields-extractor.md -> Provenance for the exact case.

import argparse
import os
import re
import sys
from lxml import etree

DCS_NS = "http://v8.1c.ru/8.1/data-composition-system/schema"
XSI_NS = "http://www.w3.org/2001/XMLSchema-instance"
DCS_NSMAP = {"dcs": DCS_NS, "xsi": XSI_NS}

TYPE_DIR_MAP = {
    "Report": "Reports",
    "DataProcessor": "DataProcessors",
}

# Metadata-table references inside a query's text, including virtual-table calls
# (Остатки/Обороты/ОстаткиИОбороты for accumulation & accounting registers,
# СрезПервых/СрезПоследних for information registers).
RE_TABLE_REF = re.compile(
    r"(РегистрНакопления|РегистрСведений|РегистрБухгалтерии|РегистрРасчета|"
    r"Справочник|Документ|Перечисление|ПланВидовХарактеристик|ПланСчетов|"
    r"ПланВидовРасчета|БизнесПроцесс|Задача|ЖурналДокументов)"
    r"\.([A-Za-zА-Яа-яЁё0-9_]+)"
    r"(\.(Остатки|Обороты|ОстаткиИОбороты|СрезПервых|СрезПоследних)\(\))?"
)


def find_template_files(extension_path, type_dir, object_name, template_filter):
    obj_dir = os.path.join(extension_path, type_dir, object_name, "Templates")
    if not os.path.isdir(obj_dir):
        return []
    found = []
    for entry in sorted(os.listdir(obj_dir)):
        if template_filter and entry != template_filter:
            continue
        candidate = os.path.join(obj_dir, entry, "Ext", "Template.xml")
        if os.path.isfile(candidate):
            found.append((entry, candidate))
    return found


def qname(tag, ns):
    return f"{{{ns}}}{tag}"


def extract_data_sets(template_path):
    """Returns a list of dicts describing every <dataSet> in the schema, or None
    if the file's root is not a DataCompositionSchema (e.g. a plain MXL template
    sharing the Templates/ directory)."""
    try:
        parser_xml = etree.XMLParser(remove_blank_text=False)
        doc = etree.parse(template_path, parser_xml)
    except Exception as exc:
        return None, str(exc)

    root = doc.getroot()
    if etree.QName(root.tag).localname != "DataCompositionSchema":
        return None, f"root element is <{etree.QName(root.tag).localname}>, not a DCS schema"

    data_sets = []
    for ds in root.iter(qname("dataSet", DCS_NS)):
        ds_type = ds.get(qname("type", XSI_NS), "?")
        name_el = ds.find("dcs:name", DCS_NSMAP)
        name = name_el.text if name_el is not None and name_el.text else "?"

        entry = {"name": name, "type": ds_type}

        if ds_type == "DataSetQuery":
            query_el = ds.find("dcs:query", DCS_NSMAP)
            query_text = query_el.text if query_el is not None and query_el.text else ""
            entry["query"] = query_text
            refs = set()
            for m in RE_TABLE_REF.finditer(query_text):
                table = f"{m.group(1)}.{m.group(2)}"
                if m.group(3):
                    table += m.group(3)
                refs.add(table)
            entry["tables"] = sorted(refs)
        elif ds_type == "DataSetUnion":
            items = [it.text for it in ds.findall("dcs:item", DCS_NSMAP) if it.text]
            entry["items"] = items
        else:
            entry["raw_children"] = [etree.QName(c.tag).localname for c in ds if isinstance(c.tag, str)]

        data_sets.append(entry)

    return data_sets, None


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(
        description="Extract the query text and referenced tables from a Report's "
                    "(or DataProcessor's) embedded Data Composition Schema.",
        allow_abbrev=False,
    )
    parser.add_argument("-ExtensionPath", required=True, help="Path to extension (or base config) source dump")
    parser.add_argument(
        "-Object", required=True,
        help='"Report.Name" or "DataProcessor.Name", e.g. "Report.ИмяОтчета"',
    )
    parser.add_argument(
        "-Template", default=None,
        help="Restrict to one template directory name (default: all templates with a DCS schema)",
    )
    parser.add_argument(
        "-ShowQueryText", action="store_true",
        help="Also print the full query text of each DataSetQuery, not just the referenced-tables summary",
    )
    args = parser.parse_args()

    extension_path = args.ExtensionPath
    if not os.path.isabs(extension_path):
        extension_path = os.path.join(os.getcwd(), extension_path)
    if not os.path.isdir(extension_path):
        print(f"Path not found: {extension_path}", file=sys.stderr)
        sys.exit(1)

    if "." not in args.Object:
        print(f"[?] Malformed -Object (expected Type.Name): {args.Object}", file=sys.stderr)
        sys.exit(1)
    obj_type, obj_name = args.Object.split(".", 1)
    type_dir = TYPE_DIR_MAP.get(obj_type)
    if type_dir is None:
        print(f"[?] Unsupported object type: {obj_type} (supported: {', '.join(TYPE_DIR_MAP)})", file=sys.stderr)
        sys.exit(1)

    templates = find_template_files(extension_path, type_dir, obj_name, args.Template)
    if not templates:
        print(f"No Ext/Template.xml found under {type_dir}/{obj_name}/Templates/"
              + (f" (filtered to '{args.Template}')" if args.Template else ""))
        return

    for template_name, template_path in templates:
        print(f"=== {obj_type}.{obj_name} / Templates/{template_name} ===")
        data_sets, err = extract_data_sets(template_path)
        if data_sets is None:
            print(f"  [skip] {err}")
            print()
            continue

        for ds in data_sets:
            print(f"  dataSet \"{ds['name']}\" ({ds['type']})")
            if ds["type"] == "DataSetQuery":
                if ds["tables"]:
                    print(f"    Referenced tables: {', '.join(ds['tables'])}")
                else:
                    print("    Referenced tables: (none matched — query may use only temporary tables/joins on prior datasets)")
                if args.ShowQueryText:
                    print("    --- query text ---")
                    for line in ds["query"].splitlines():
                        print(f"    {line}")
                    print("    --- end query text ---")
            elif ds["type"] == "DataSetUnion":
                print(f"    Union of: {', '.join(ds['items']) if ds['items'] else '(no items found)'}")
            else:
                print(f"    (unrecognized dataSet type — children: {', '.join(ds['raw_children'])})")
        print()


if __name__ == "__main__":
    main()
