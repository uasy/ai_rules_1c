#!/usr/bin/env python3
# remove-template v1.3 — Remove template from 1C object
# Licence and attribution: NOTICE.md of the 1c-metadata-manage skill.
# Local: the same hardening remove-template.ps1 carries on top of the
#        original v1.3 — preflight parse (the root XML is parsed, planned and rendered
#        before anything is deleted, so a parse failure cannot leave a
#        half-removed tree), a refusal when the template is not registered in
#        ChildObjects, an atomic root-XML write through a temporary file, and
#        the -DryRun / -Force safety gate. The original deleted unconditionally
#        and accepted neither flag.

import argparse
import os
import re
import shutil
import sys

from lxml import etree

NSMAP = {"md": "http://v8.1c.ru/8.3/MDClasses"}


def render_xml_with_bom(tree):
    """Serialize the tree the way the platform writes its dumps: UTF-8 BOM,
    double-quoted lowercase declaration, final newline."""
    xml_bytes = etree.tostring(tree, xml_declaration=True, encoding="UTF-8")
    xml_bytes = xml_bytes.replace(b"<?xml version='1.0' encoding='UTF-8'?>", b'<?xml version="1.0" encoding="utf-8"?>')
    if not xml_bytes.endswith(b"\n"):
        xml_bytes += b"\n"
    return b"\xef\xbb\xbf" + xml_bytes


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Remove template from 1C object", allow_abbrev=False)
    parser.add_argument("-ObjectName", "-ProcessorName", required=True)
    parser.add_argument("-TemplateName", required=True)
    parser.add_argument("-SrcDir", default="src")
    parser.add_argument("-DryRun", action="store_true",
                        help="print the plan and change nothing")
    parser.add_argument("-Force", action="store_true",
                        help="confirm the reviewed plan and perform the removal")
    args = parser.parse_args()

    object_name = args.ObjectName
    template_name = args.TemplateName
    src_dir = args.SrcDir

    # --- Checks ---

    root_xml_path = os.path.join(src_dir, f"{object_name}.xml")
    if not os.path.exists(root_xml_path):
        print(f"Корневой файл обработки не найден: {root_xml_path}", file=sys.stderr)
        sys.exit(1)

    processor_dir = os.path.join(src_dir, object_name)
    templates_dir = os.path.join(processor_dir, "Templates")
    template_meta_path = os.path.join(templates_dir, f"{template_name}.xml")
    template_dir = os.path.join(templates_dir, template_name)

    if not os.path.exists(template_meta_path):
        print(f"Метаданные макета не найдены: {template_meta_path}", file=sys.stderr)
        sys.exit(1)

    # --- Preflight: parse and modify the XML in memory before deleting anything ---

    root_xml_full = os.path.abspath(root_xml_path)
    parser_xml = etree.XMLParser(remove_blank_text=False)
    tree = etree.parse(root_xml_full, parser_xml)
    root = tree.getroot()

    # Remove <Template>TemplateName</Template> from ChildObjects
    template_node_found = False
    for node in root.findall(".//md:ChildObjects/md:Template", NSMAP):
        if node.text and node.text.strip() == template_name:
            template_node_found = True
            parent = node.getparent()
            prev = node.getprevious()
            # Exactly one whitespace separator must go with the entry, the way
            # remove-template.ps1 drops the single preceding whitespace node.
            # In lxml the separator *before* the node lives in prev.tail (or in
            # parent.text for the first child) and the one *after* it lives in
            # node.tail, which `remove` takes along. Clearing prev.tail as well
            # would drop both, so the neighbours close up: the entry that
            # followed joins the previous line, and a removed last entry pulls
            # </ChildObjects> onto the line of the entry before it. Hand
            # node.tail over instead — one separator leaves, one stays.
            if prev is not None:
                if prev.tail and prev.tail.strip() == "":
                    prev.tail = node.tail
            else:
                # First child — the separator before it is parent.text.
                if parent.text and parent.text.strip() == "":
                    parent.text = node.tail
            parent.remove(node)
            break

    if not template_node_found:
        print(f"Template is not registered in ChildObjects: {template_name}", file=sys.stderr)
        sys.exit(1)

    # Clear MainDataCompositionSchema if it pointed to this template
    main_dcs = root.find(".//md:MainDataCompositionSchema", NSMAP)
    if main_dcs is not None and main_dcs.text:
        if re.search(rf"Template\.{re.escape(template_name)}$", main_dcs.text):
            main_dcs.text = ""
            print("[PLAN] Clear MainDataCompositionSchema")

    # Render now: a serialization failure must surface before anything is deleted.
    payload = render_xml_with_bom(tree)

    # --- Safety gate ---

    print("Planned changes:")
    print(f"  modify: {root_xml_path} (remove ChildObjects/Template '{template_name}')")
    print(f"  delete: {template_meta_path}")
    if os.path.isdir(template_dir):
        print(f"  delete: {template_dir} (recursive)")

    if args.DryRun:
        print("[DRY-RUN] No files changed.")
        sys.exit(0)
    if not args.Force:
        print("Removal requires explicit -Force. Run with -DryRun first to review the plan.",
              file=sys.stderr)
        sys.exit(2)

    # --- Mutation: commit the root registration change before deleting files ---

    # Serialize to a temporary file first. If writing fails, the source tree
    # remains untouched.
    temp_root_xml = root_xml_full + ".remove-template.tmp"
    try:
        with open(temp_root_xml, "wb") as handle:
            handle.write(payload)
        os.replace(temp_root_xml, root_xml_full)
    except BaseException:
        if os.path.exists(temp_root_xml):
            os.remove(temp_root_xml)
        raise

    if os.path.isdir(template_dir):
        shutil.rmtree(template_dir)
        print(f"[OK] Removed directory: {template_dir}")

    os.remove(template_meta_path)
    print(f"[OK] Removed file: {template_meta_path}")
    print(f"[OK] Template {template_name} removed from {root_xml_path}")


if __name__ == "__main__":
    main()
