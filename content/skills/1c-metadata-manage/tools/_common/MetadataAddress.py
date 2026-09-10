#!/usr/bin/env python3
# MetadataAddress.py — logical 1C metadata addresses to physical dump paths.
#
# Python peer of MetadataAddress.ps1 (which the PowerShell tools dot-source),
# contract-identical so the two runtimes cannot drift.
#
# The vendored tools address a Designer XML dump by file path: the caller has to
# know that `Справочник.Контрагенты` lives in `Catalogs/Контрагенты.xml` and that
# its form is `Catalogs/Контрагенты/Forms/ФормаЭлемента/Ext/Form.xml`. The MCP
# servers of this toolkit already speak the logical name (`object_name`), so the
# two halves of one task used two addressing schemes. This file is the bridge:
# one logical address, resolved the same way everywhere.
#
# Address grammar:
#   <Kind>.<Name>                      -> the object's own XML
#   <Kind>.<Name>.Форма.<FormName>     -> Forms/<FormName>/Ext/Form.xml
#   <Kind>.<Name>.Макет.<TemplateName> -> Templates/<TemplateName>/Ext/Template.xml
#   <Kind>.<Name>.Права                -> Ext/Rights.xml (roles)
#   <Kind>.<Name>.МодульОбъекта        -> Ext/ObjectModule.bsl
#   <Kind>.<Name>.МодульМенеджера      -> Ext/ManagerModule.bsl
#   Kind, and every segment keyword, may be written in Russian or English.

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dev_env  # noqa: E402

KIND_FOLDERS = {
    'Справочник': 'Catalogs',
    'Catalog': 'Catalogs',
    'Документ': 'Documents',
    'Document': 'Documents',
    'ЖурналДокументов': 'DocumentJournals',
    'DocumentJournal': 'DocumentJournals',
    'Перечисление': 'Enums',
    'Enum': 'Enums',
    'Отчет': 'Reports',
    'Отчёт': 'Reports',
    'Report': 'Reports',
    'Обработка': 'DataProcessors',
    'DataProcessor': 'DataProcessors',
    'ПланВидовХарактеристик': 'ChartsOfCharacteristicTypes',
    'ChartOfCharacteristicTypes': 'ChartsOfCharacteristicTypes',
    'ПланСчетов': 'ChartsOfAccounts',
    'ChartOfAccounts': 'ChartsOfAccounts',
    'ПланВидовРасчета': 'ChartsOfCalculationTypes',
    'ПланВидовРасчёта': 'ChartsOfCalculationTypes',
    'ChartOfCalculationTypes': 'ChartsOfCalculationTypes',
    'РегистрСведений': 'InformationRegisters',
    'InformationRegister': 'InformationRegisters',
    'РегистрНакопления': 'AccumulationRegisters',
    'AccumulationRegister': 'AccumulationRegisters',
    'РегистрБухгалтерии': 'AccountingRegisters',
    'AccountingRegister': 'AccountingRegisters',
    'РегистрРасчета': 'CalculationRegisters',
    'РегистрРасчёта': 'CalculationRegisters',
    'CalculationRegister': 'CalculationRegisters',
    'БизнесПроцесс': 'BusinessProcesses',
    'BusinessProcess': 'BusinessProcesses',
    'Задача': 'Tasks',
    'Task': 'Tasks',
    'Константа': 'Constants',
    'Constant': 'Constants',
    'ОбщийМодуль': 'CommonModules',
    'CommonModule': 'CommonModules',
    'Подсистема': 'Subsystems',
    'Subsystem': 'Subsystems',
    'Роль': 'Roles',
    'Role': 'Roles',
    'ОбщаяФорма': 'CommonForms',
    'CommonForm': 'CommonForms',
    'ОбщийМакет': 'CommonTemplates',
    'CommonTemplate': 'CommonTemplates',
    'ОбщаяКоманда': 'CommonCommands',
    'CommonCommand': 'CommonCommands',
    'ГруппаКоманд': 'CommandGroups',
    'CommandGroup': 'CommandGroups',
    'ОбщийРеквизит': 'CommonAttributes',
    'CommonAttribute': 'CommonAttributes',
    'ОбщаяКартинка': 'CommonPictures',
    'CommonPicture': 'CommonPictures',
    'ПланОбмена': 'ExchangePlans',
    'ExchangePlan': 'ExchangePlans',
    'КритерийОтбора': 'FilterCriteria',
    'FilterCriterion': 'FilterCriteria',
    'ПодпискаНаСобытие': 'EventSubscriptions',
    'EventSubscription': 'EventSubscriptions',
    'РегламентноеЗадание': 'ScheduledJobs',
    'ScheduledJob': 'ScheduledJobs',
    'ФункциональнаяОпция': 'FunctionalOptions',
    'FunctionalOption': 'FunctionalOptions',
    'ПараметрФункциональныхОпций': 'FunctionalOptionsParameters',
    'FunctionalOptionsParameter': 'FunctionalOptionsParameters',
    'ОпределяемыйТип': 'DefinedTypes',
    'DefinedType': 'DefinedTypes',
    'ПараметрСеанса': 'SessionParameters',
    'SessionParameter': 'SessionParameters',
    'HTTPСервис': 'HTTPServices',
    'HTTPService': 'HTTPServices',
    'WebСервис': 'WebServices',
    'WebService': 'WebServices',
    'XDTOПакет': 'XDTOPackages',
    'XDTOPackage': 'XDTOPackages',
    'ХранилищеНастроек': 'SettingsStorages',
    'SettingsStorage': 'SettingsStorages',
    'Последовательность': 'Sequences',
    'Sequence': 'Sequences',
    'ВнешнийИсточникДанных': 'ExternalDataSources',
    'ExternalDataSource': 'ExternalDataSources',
    'Стиль': 'Styles',
    'Style': 'Styles',
    'ЭлементСтиля': 'StyleItems',
    'StyleItem': 'StyleItems',
    'Язык': 'Languages',
    'Language': 'Languages',
}

MEMBER_KEYWORDS = {
    'Форма': 'form',
    'Form': 'form',
    'Макет': 'template',
    'Template': 'template',
    'Права': 'rights',
    'Rights': 'rights',
    'МодульОбъекта': 'objectmodule',
    'ObjectModule': 'objectmodule',
    'МодульМенеджера': 'managermodule',
    'ManagerModule': 'managermodule',
    'МодульНабораЗаписей': 'recordsetmodule',
    'RecordSetModule': 'recordsetmodule',
}


class AddressError(ValueError):
    """A logical address that cannot be resolved. Raised with the list of
    accepted kinds or members: a wrong path silently pointing at nothing is
    the failure mode this module exists to remove."""


def resolve_dump_root(root=None, start_dir=None):
    """Configuration dump root: explicit root, then EXPORT_PATH from .dev.env,
    then the nearest ancestor holding a Configuration.xml. Returns None when
    none of the three answers - the caller reports that, never guesses."""
    if root:
        full = os.path.abspath(root)
        if os.path.isfile(os.path.join(full, 'Configuration.xml')):
            return full
        if os.path.isdir(full):
            return full
        return None

    from_env = dev_env.get_value('EXPORT_PATH', start_dir)
    if from_env:
        candidate = from_env if os.path.isabs(from_env) else os.path.join(os.getcwd(), from_env)
        if os.path.isdir(candidate):
            return os.path.abspath(candidate)

    directory = start_dir or os.getcwd()
    for _ in range(20):
        if not directory:
            break
        if os.path.isfile(os.path.join(directory, 'Configuration.xml')):
            return directory
        parent = os.path.dirname(directory)
        if not parent or parent == directory:
            break
        directory = parent
    return None


def resolve_object_path(address, root):
    """Logical address -> physical path inside the dump. Raises AddressError
    with the list of accepted kinds when the kind is unknown."""
    parts = [p for p in address.split('.') if p]
    if len(parts) < 2:
        raise AddressError(f"Address '{address}' is not <Kind>.<Name>, e.g. Справочник.Контрагенты.")

    kind = parts[0]
    if kind not in KIND_FOLDERS:
        known = ', '.join(sorted(KIND_FOLDERS))
        raise AddressError(f"Unknown metadata kind '{kind}'. Accepted: {known}")
    folder = KIND_FOLDERS[kind]
    name = parts[1]
    object_dir = os.path.join(root, folder, name)
    object_xml = os.path.join(root, folder, name + '.xml')

    if len(parts) == 2:
        return object_xml

    member = parts[2]
    if member not in MEMBER_KEYWORDS:
        known = ', '.join(sorted(MEMBER_KEYWORDS))
        raise AddressError(f"Unknown member '{member}' in '{address}'. Accepted: {known}")
    member_kind = MEMBER_KEYWORDS[member]
    member_name = parts[3] if len(parts) >= 4 else None

    if member_kind == 'form':
        if not member_name:
            raise AddressError(f"'{address}' needs a form name: <Kind>.<Name>.Форма.<FormName>.")
        return os.path.join(object_dir, 'Forms', member_name, 'Ext', 'Form.xml')
    if member_kind == 'template':
        if not member_name:
            raise AddressError(f"'{address}' needs a template name: <Kind>.<Name>.Макет.<TemplateName>.")
        return os.path.join(object_dir, 'Templates', member_name, 'Ext', 'Template.xml')
    if member_kind == 'rights':
        return os.path.join(object_dir, 'Ext', 'Rights.xml')
    if member_kind == 'objectmodule':
        return os.path.join(object_dir, 'Ext', 'ObjectModule.bsl')
    if member_kind == 'managermodule':
        return os.path.join(object_dir, 'Ext', 'ManagerModule.bsl')
    if member_kind == 'recordsetmodule':
        return os.path.join(object_dir, 'Ext', 'RecordSetModule.bsl')
    raise AddressError(f"Cannot resolve '{address}'.")


def get_watch_paths(target_path):
    """What a run against this target may touch: the file itself, the object's
    own folder (forms, templates, modules live there) and the root
    Configuration.xml, which every registering tool rewrites."""
    paths = [target_path]

    directory = os.path.dirname(target_path)
    leaf = os.path.splitext(os.path.basename(target_path))[0]
    sibling = os.path.join(directory, leaf)
    if os.path.isdir(sibling):
        paths.append(sibling)

    probe = directory
    for _ in range(12):
        if not probe:
            break
        cfg = os.path.join(probe, 'Configuration.xml')
        if os.path.isfile(cfg):
            paths.append(cfg)
            object_root = os.path.join(os.path.dirname(target_path), leaf)
            if os.path.isdir(object_root):
                paths.append(object_root)
            break
        parent = os.path.dirname(probe)
        if not parent or parent == probe:
            break
        probe = parent

    return sorted({p for p in paths if p})
