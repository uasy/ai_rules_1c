#!/usr/bin/env python3
# dump-validate — Read-only integrity check of a complete hierarchical Designer XML dump (CF or CFE)
# Python peer of dump-validate.ps1, same findings, output and exit codes.
"""Checks declared objects against disk, nested subsystems, metadata versions,
configuration/subsystem references and an optional ConfigDumpInfo.xml.
Does not replace cf-validate/cfe-validate, object validators or platform checks.
Local implementation; no md-sparrow source code or runtime dependency.
"""
import argparse
import json
import os
import sys
import unicodedata
from lxml import etree

METADATA_NAMESPACE = 'http://v8.1c.ru/8.3/MDClasses'
DUMPINFO_NAMESPACE = 'http://v8.1c.ru/8.3/xcf/dumpinfo'

# Same directory vocabulary as cf-validate; only immediate descriptor files are scanned.
# Ext, modules, forms, templates and supplier dumps are not mistaken for root objects.
TYPE_DIRECTORIES = {
    'Language': 'Languages', 'Subsystem': 'Subsystems', 'StyleItem': 'StyleItems', 'Style': 'Styles',
    'CommonPicture': 'CommonPictures', 'SessionParameter': 'SessionParameters', 'Role': 'Roles',
    'CommonTemplate': 'CommonTemplates', 'FilterCriterion': 'FilterCriteria', 'CommonModule': 'CommonModules',
    'Bot': 'Bots', 'CommonAttribute': 'CommonAttributes', 'ExchangePlan': 'ExchangePlans',
    'XDTOPackage': 'XDTOPackages', 'WebService': 'WebServices', 'HTTPService': 'HTTPServices', 'WSReference': 'WSReferences',
    'EventSubscription': 'EventSubscriptions', 'ScheduledJob': 'ScheduledJobs', 'SettingsStorage': 'SettingsStorages',
    'FunctionalOption': 'FunctionalOptions', 'FunctionalOptionsParameter': 'FunctionalOptionsParameters',
    'DefinedType': 'DefinedTypes', 'CommonCommand': 'CommonCommands', 'CommandGroup': 'CommandGroups',
    'Constant': 'Constants', 'CommonForm': 'CommonForms', 'Catalog': 'Catalogs', 'Document': 'Documents',
    'DocumentNumerator': 'DocumentNumerators', 'Sequence': 'Sequences', 'DocumentJournal': 'DocumentJournals',
    'Enum': 'Enums', 'Report': 'Reports', 'DataProcessor': 'DataProcessors', 'InformationRegister': 'InformationRegisters',
    'AccumulationRegister': 'AccumulationRegisters', 'ChartOfCharacteristicTypes': 'ChartsOfCharacteristicTypes',
    'ChartOfAccounts': 'ChartsOfAccounts', 'AccountingRegister': 'AccountingRegisters',
    'ChartOfCalculationTypes': 'ChartsOfCalculationTypes', 'CalculationRegister': 'CalculationRegisters',
    'BusinessProcess': 'BusinessProcesses', 'Task': 'Tasks', 'IntegrationService': 'IntegrationServices',
    'WebSocketClient': 'WebSocketClients',
}
# PowerShell hashtables and -eq / -contains compare keys case-insensitively.
TYPE_BY_LOWER = {t.lower(): t for t in TYPE_DIRECTORIES}


class KeySet:
    """Case-insensitive key -> value map (a PowerShell @{} hashtable)."""

    def __init__(self):
        self._items = {}

    def __contains__(self, key):
        return key.lower() in self._items

    def __setitem__(self, key, value):
        self._items[key.lower()] = value

    def __len__(self):
        return len(self._items)


def is_identifier(value):
    # ^[\p{L}_][\p{L}\p{Nd}_]*$
    if not value:
        return False
    for index, ch in enumerate(value):
        category = unicodedata.category(ch)
        if ch == '_' or category.startswith('L'):
            continue
        if index > 0 and category == 'Nd':
            continue
        return False
    return True


def local(node):
    return etree.QName(node).localname


def element_children(node):
    return [c for c in node if isinstance(c.tag, str)]


def inner_text(node):
    return ''.join(node.itertext())


class DumpValidator:
    def __init__(self, root_path):
        self.root_path = root_path
        self.findings = []
        self.objects = KeySet()
        self.reference_sources = []
        self.dump_version = ''

    def add_finding(self, kind, file, obj, message):
        relative = file
        prefix = self.root_path.rstrip('\\/') + os.sep
        if file.lower().startswith(prefix.lower()):
            relative = file[len(prefix):]
        self.findings.append({'kind': kind, 'severity': 'error', 'path': relative.replace('\\', '/'),
                              'object': obj, 'message': message})

    def read_xml(self, file, obj):
        try:
            parser = etree.XMLParser(resolve_entities=False, no_network=True, load_dtd=False)
            tree = etree.parse(file, parser)
            if tree.docinfo.doctype:
                raise ValueError('DTD is prohibited in this XML document.')
            return tree.getroot()
        except Exception as exc:  # noqa: BLE001 - every unreadable file is a finding
            self.add_finding('xml-unreadable', file, obj, f'Не удалось прочитать XML: {exc}')
            return None

    def metadata_node(self, root, type_name, file, obj):
        qname = etree.QName(root)
        if qname.localname.lower() != 'metadataobject' or (qname.namespace or '').lower() != METADATA_NAMESPACE.lower():
            self.add_finding('metadata-root-invalid', file, obj, 'Ожидается MetaDataObject в пространстве имён MDClasses.')
            return None
        node = next((c for c in element_children(root)
                     if local(c) == type_name and etree.QName(c).namespace == METADATA_NAMESPACE), None)
        if node is None:
            self.add_finding('metadata-root-invalid', file, obj, f'Не найден объект {type_name}.')
        return node

    @staticmethod
    def child(node, name):
        return next((c for c in element_children(node) if local(c) == name), None)

    def test_object_file(self, file, type_name, name, key):
        # Keep existing but unreadable objects in the inventory: do not cascade into false missing-reference reports.
        if key in self.objects:
            return
        self.objects[key] = file
        document = self.read_xml(file, key)
        if document is None:
            return
        node = self.metadata_node(document, type_name, file, key)
        if node is None:
            return
        object_version = document.get('version', '')
        if not object_version:
            self.add_finding('version-unreadable', file, key, 'Не указана версия формата объекта.')
        elif object_version.lower() != self.dump_version.lower():
            self.add_finding('version-mismatch', file, key,
                             f'Версия объекта {object_version} отличается от версии конфигурации {self.dump_version}.')
        properties = self.child(node, 'Properties')
        name_node = self.child(properties, 'Name') if properties is not None else None
        if name_node is None or inner_text(name_node) != name:
            self.add_finding('name-mismatch', file, key, f'Имя внутри XML не совпадает с именем файла {name}.xml.')
        if type_name == 'Subsystem':
            self.reference_sources.append((file, key, node))
            self.test_composition(node, os.path.splitext(file)[0], key, file)

    def test_composition(self, node, directory, parent_key, owner_file):
        composition = self.child(node, 'ChildObjects')
        declared = KeySet()
        allowed = ['Subsystem'] if parent_key else list(TYPE_DIRECTORIES)
        allowed_lower = {t.lower() for t in allowed}
        if composition is None and not parent_key:
            self.add_finding('composition-missing', owner_file, '', 'Не найден состав конфигурации ChildObjects.')
        if composition is not None:
            for entry in element_children(composition):
                type_name = local(entry)
                name = inner_text(entry).strip()
                key = f'{parent_key}.{type_name}.{name}' if parent_key else f'{type_name}.{name}'
                if type_name.lower() not in allowed_lower:
                    self.add_finding('unknown-type', owner_file, key, f'Неизвестный для этого состава тип {type_name}.')
                    continue
                if not is_identifier(name):
                    self.add_finding('invalid-name', owner_file, key, 'Некорректное имя объекта в составе.')
                    continue
                if key in declared:
                    self.add_finding('duplicate-entry', owner_file, key, 'Объект объявлен в составе несколько раз.')
                    continue
                declared[key] = True
                file = os.path.join(directory, TYPE_DIRECTORIES[TYPE_BY_LOWER[type_name.lower()]], f'{name}.xml')
                if not os.path.isfile(file):
                    self.add_finding('missing-file', file, key, 'Объект объявлен в составе, но файл отсутствует.')
                else:
                    self.test_object_file(file, type_name, name, key)
        for type_name in allowed:
            folder = os.path.join(directory, TYPE_DIRECTORIES[type_name])
            if not os.path.isdir(folder):
                continue
            names = [n for n in os.listdir(folder)
                     if n.lower().endswith('.xml') and os.path.isfile(os.path.join(folder, n))]
            for file_name in sorted(names, key=lambda n: (n.lower(), n)):
                base_name = os.path.splitext(file_name)[0]
                key = f'{parent_key}.{type_name}.{base_name}' if parent_key else f'{type_name}.{base_name}'
                if key not in declared:
                    full = os.path.join(folder, file_name)
                    self.add_finding('orphan-file', full, key, 'Файл объекта отсутствует в объявленном составе.')
                    self.test_object_file(full, type_name, base_name, key)

    @staticmethod
    def object_key(reference):
        # Resolve the owning metadata object, not embedded attributes or module names.
        parts = reference.split('.')
        if len(parts) < 2 or (parts[0].lower() != 'configuration' and parts[0].lower() not in TYPE_BY_LOWER):
            return None
        if not is_identifier(parts[1]):
            return None
        key = f'{parts[0]}.{parts[1]}'
        if parts[0].lower() == 'subsystem':
            i = 2
            while i + 1 < len(parts) and parts[i].lower() == 'subsystem':
                if not is_identifier(parts[i + 1]):
                    return None
                key += f'.Subsystem.{parts[i + 1]}'
                i += 2
        return key

    @staticmethod
    def leaves(node):
        return [d for d in node.iter() if isinstance(d.tag, str) and not element_children(d)]

    def check_references(self):
        for file, key, node in self.reference_sources:
            # Only reference-bearing properties. A comment containing Catalog.X is ordinary text.
            properties = self.child(node, 'Properties')
            if properties is None:
                continue
            references = []
            if key:
                for content in (c for c in element_children(properties) if local(c) == 'Content'):
                    references += [d for d in self.leaves(content) if d is not content]
            else:
                for prop in (c for c in element_children(properties) if local(c).startswith('Default')):
                    references += self.leaves(prop)
            seen = KeySet()
            for reference in references:
                ref_key = self.object_key(inner_text(reference).strip())
                if ref_key and ref_key not in seen and ref_key not in self.objects:
                    self.add_finding('dangling-reference', file, ref_key, 'Ссылка ведёт на отсутствующий объект выгрузки.')
                    seen[ref_key] = True

    def check_dump_info(self):
        info_file = os.path.join(self.root_path, 'ConfigDumpInfo.xml')
        if not os.path.isfile(info_file):
            return
        info = self.read_xml(info_file, '')
        if info is None:
            return
        qname = etree.QName(info)
        if qname.localname.lower() != 'configdumpinfo' or (qname.namespace or '').lower() != DUMPINFO_NAMESPACE:
            self.add_finding('dump-info-invalid', info_file, '', 'Ожидается корневой элемент ConfigDumpInfo в пространстве имён dumpinfo.')
            return
        info_format = info.get('format', '')
        if info_format and info_format.lower() != 'hierarchical':
            self.add_finding('dump-format-unsupported', info_file, '',
                             f'Поддерживается только иерархическая выгрузка; получен формат {info_format}.')
        if info.get('version', '').lower() != self.dump_version.lower():
            self.add_finding('dump-info-version', info_file, '', 'Версия ConfigDumpInfo.xml отличается от версии конфигурации.')
        seen = KeySet()
        for entry in info.iter():
            if not isinstance(entry.tag, str) or local(entry) != 'Metadata' or entry.get('name') is None:
                continue
            key = self.object_key(entry.get('name'))
            if key and key not in seen and key not in self.objects:
                self.add_finding('dump-info-extra', info_file, key, 'ConfigDumpInfo.xml содержит отсутствующий объект выгрузки.')
                seen[key] = True

    def run(self, configuration_file):
        if not os.path.isfile(configuration_file):
            self.add_finding('configuration-missing', configuration_file, '', 'Не найден Configuration.xml полной выгрузки.')
            return
        configuration = self.read_xml(configuration_file, '')
        if configuration is None:
            return
        node = self.metadata_node(configuration, 'Configuration', configuration_file, '')
        self.dump_version = configuration.get('version', '')
        if not self.dump_version:
            self.add_finding('version-unreadable', configuration_file, '', 'Не указана версия формата конфигурации.')
        if node is None or not self.dump_version:
            return
        properties = self.child(node, 'Properties')
        name_node = self.child(properties, 'Name') if properties is not None else None
        if name_node is not None and inner_text(name_node):
            self.objects[f'Configuration.{inner_text(name_node)}'] = configuration_file
        self.reference_sources.append((configuration_file, '', node))
        self.test_composition(node, self.root_path, '', configuration_file)
        self.check_references()
        self.check_dump_info()


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description='Integrity check of a complete hierarchical Designer XML dump',
                                     allow_abbrev=False)
    parser.add_argument('-ConfigPath', '-Path', required=True)
    parser.add_argument('-Format', default='Text', type=lambda v: v.capitalize(), choices=['Text', 'Json'])
    parser.add_argument('-OutFile', default='')
    args = parser.parse_args()

    input_path = args.ConfigPath if os.path.isabs(args.ConfigPath) else os.path.join(os.getcwd(), args.ConfigPath)
    root_path = os.path.normpath(os.path.abspath(input_path))
    validator = DumpValidator(root_path)
    output_path = None
    scan_failed = False
    try:
        if os.path.isfile(root_path):
            configuration_file = root_path
            validator.root_path = root_path = os.path.dirname(configuration_file)
        else:
            configuration_file = os.path.join(root_path, 'Configuration.xml')
        if args.OutFile:
            candidate = args.OutFile if os.path.isabs(args.OutFile) else os.path.join(os.getcwd(), args.OutFile)
            candidate = os.path.normpath(os.path.abspath(candidate))
            root_prefix = root_path.rstrip('\\/') + os.sep
            if candidate == root_path or candidate.lower().startswith(root_prefix.lower()):
                raise ValueError('OutFile должен находиться вне проверяемой выгрузки: исходные файлы не изменяются.')
            output_path = candidate
        validator.run(configuration_file)
    except Exception as exc:  # noqa: BLE001 - the scan reports its own failure
        scan_failed = True
        validator.add_finding('scan-error', validator.root_path, '', f'Обход выгрузки не завершён: {exc}')

    status = 'error' if scan_failed else ('invalid' if validator.findings else 'valid')
    result = {'schema_version': 1, 'status': status, 'root': validator.root_path,
              'objects_checked': len(validator.objects), 'findings': validator.findings}
    if args.Format == 'Json':
        text = json.dumps(result, ensure_ascii=False, indent=2)
    else:
        lines = [f'Проверка полной выгрузки: {status}; объектов: {result["objects_checked"]}; ошибок: {len(validator.findings)}']
        lines += [f'[{f["kind"]}] {f["path"]}: {f["message"]} {f["object"]}' for f in validator.findings]
        text = os.linesep.join(lines)
    if output_path:
        with open(output_path, 'w', encoding='utf-8-sig', newline='') as handle:
            handle.write(text)
    print(text)
    sys.exit(0 if status == 'valid' else 1)


if __name__ == '__main__':
    main()
