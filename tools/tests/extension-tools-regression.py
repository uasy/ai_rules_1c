#!/usr/bin/env python3
"""Regressions for the extension inventory tools: cfe-diff -Mode A
(1c-metadata-manage), registry-builder and reference-finder (1c-extension-analysis).

A synthetic extension is materialized into a temp directory. It holds one
instance of every construct these tools used to miss silently:

  - an own template and an own command on an adopted document (bare-name
    ChildObjects entries whose ownership lives in their own descriptor), and a
    borrowed template whose content the extension replaces;
  - a borrowed form whose layout gains an attribute and a button and loses a
    property of an existing element (diff against <BaseForm>);
  - an adopted subsystem that adds content, with a nested adopted subsystem;
  - an adopted role that grants rights (Ext/Rights.xml);
  - an adopted defined type that gains a type (xr:ExtendValue);
  - an adopted common form with a module at Ext/Form/Module.bsl;
  - an adopted catalog that adds a predefined item;
  - a web service and a Language object (absent from the old type map);
  - a top-level folder of a type no map lists (Bots/);
  - an Ext/ file nothing interprets, which must come out as [UNCLASSIFIED];
  - a manager module with #Вставка blocks (code, comments only, a #Удаление,
    an &ИзменениеИКонтроль with no block, inert markers under &После) and a
    dispatcher; an adopted common module whose module is empty; a catalog whose
    only change is an extended Predefined list with adopted items only.

Separate small trees check insert-blocks' zero handling, exchangeplan-content's
section headers and typical/own split, and the dispatch checker's relative
-BslFile resolution.

Usage:  python3 -B extension-tools-regression.py [--keep-work-dir]
Nothing here needs a 1C platform or the network.
"""

import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SKILLS = os.path.join(os.path.dirname(os.path.dirname(HERE)), "content", "skills")
CFE_DIFF = os.path.join(SKILLS, "1c-metadata-manage", "tools", "1c-cfe-manage", "scripts", "cfe-diff.py")
REGISTRY = os.path.join(SKILLS, "1c-extension-analysis", "tools", "1c-change-registry-builder",
                        "scripts", "registry-builder.py")
REFERENCE = os.path.join(SKILLS, "1c-extension-analysis", "tools", "1c-reference-finder",
                         "scripts", "reference-finder.py")
TOOLS = os.path.join(SKILLS, "1c-extension-analysis", "tools")
FORM_BASEDIFF = os.path.join(TOOLS, "1c-form-basediff", "scripts", "form-basediff.py")
INSERT_BLOCKS = os.path.join(TOOLS, "1c-insert-blocks", "scripts", "insert-blocks.py")
EXCHANGE = os.path.join(TOOLS, "1c-exchangeplan-content", "scripts", "exchangeplan-content.py")
DISPATCH = os.path.join(TOOLS, "1c-defined-type-dispatch-checker", "scripts",
                        "defined-type-dispatch-checker.py")

HEAD = ('<?xml version="1.0" encoding="UTF-8"?>\n'
        '<MetaDataObject xmlns="http://v8.1c.ru/8.3/MDClasses" '
        'xmlns:xr="http://v8.1c.ru/8.3/xcf/readable" '
        'xmlns:v8="http://v8.1c.ru/8.1/data/core" '
        'xmlns:cfg="http://v8.1c.ru/8.1/data/enterprise/current-config" '
        'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" version="2.20">\n')
TAIL = "</MetaDataObject>\n"
ADOPTED = "<ObjectBelonging>Adopted</ObjectBelonging>"


def state(*props):
    body = "".join(f"<xr:PropertyState><xr:Property>{p}</xr:Property>"
                   f"<xr:State>{s}</xr:State></xr:PropertyState>" for p, s in props)
    return f"<InternalInfo>{body}</InternalInfo>" if body else ""


def md(kind, name, adopted=True, internal="", props="", children=None):
    ob = ADOPTED if adopted else ""
    ch = "" if children is None else f"<ChildObjects>{children}</ChildObjects>"
    return (HEAD + f"<{kind}>{internal}<Properties>{ob}<Name>{name}</Name>{props}</Properties>"
            f"{ch}</{kind}>\n" + TAIL)


def attr(name, adopted):
    return f"<Attribute><Properties>{ADOPTED if adopted else ''}<Name>{name}</Name></Properties></Attribute>"


FORM_NS = ('xmlns="http://v8.1c.ru/8.3/xcf/logform" xmlns:v8="http://v8.1c.ru/8.1/data/core" '
           'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"')

DOC_FORM = f"""<?xml version="1.0" encoding="UTF-8"?>
<Form {FORM_NS} version="2.20">
	<ChildItems>
		<InputField name="Поле" id="1">
			<DataPath>Объект.Номер</DataPath>
		</InputField>
		<InputField name="Поле2" id="2">
			<DataPath>Объект.Дата</DataPath>
			<ReadOnly>true</ReadOnly>
		</InputField>
		<Button name="Т_Кнопка" id="5">
			<CommandName>Form.Command.Т_Команда</CommandName>
		</Button>
	</ChildItems>
	<Attributes>
		<Attribute name="Объект" id="1"><MainAttribute>true</MainAttribute></Attribute>
		<Attribute name="Т_Список" id="2"><Type><v8:Type>v8:ValueTable</v8:Type></Type></Attribute>
	</Attributes>
	<Commands>
		<Command name="Т_Команда" id="1"><Action callType="After">Т_КомандаПосле</Action></Command>
	</Commands>
	<BaseForm version="2.20">
		<ChildItems>
			<InputField name="Поле" id="1">
				<DataPath>Объект.Номер</DataPath>
				<ReadOnly>true</ReadOnly>
			</InputField>
			<InputField name="Поле2" id="2">
				<DataPath>Объект.Дата</DataPath>
				<ReadOnly>true</ReadOnly>
			</InputField>
		</ChildItems>
		<Attributes>
			<Attribute name="Объект" id="1"><MainAttribute>true</MainAttribute></Attribute>
		</Attributes>
	</BaseForm>
</Form>
"""

COMMON_FORM = f"""<?xml version="1.0" encoding="UTF-8"?>
<Form {FORM_NS} version="2.20">
	<Events>
		<Event name="OnCreateAtServer">ПриСозданииНаСервере</Event>
		<Event name="OnCreateAtServer" callType="After">Т_ПриСозданииНаСервереПосле</Event>
	</Events>
	<ChildItems>
		<Button name="Кнопка" id="1"><CommandName>Form.Command.Печать</CommandName></Button>
	</ChildItems>
	<Commands>
		<Command name="Печать" id="1"><Action>Печать</Action></Command>
		<Command name="Т_ВРеестр" id="2"><Action callType="After">Т_ВРеестрПосле</Action></Command>
	</Commands>
	<BaseForm version="2.20">
		<Events>
			<Event name="OnCreateAtServer">ПриСозданииНаСервере</Event>
		</Events>
		<ChildItems>
			<Button name="Кнопка" id="1"><CommandName>Form.Command.Печать</CommandName></Button>
		</ChildItems>
		<Commands>
			<Command name="Печать" id="1"><Action>Печать</Action></Command>
		</Commands>
	</BaseForm>
</Form>
"""

RIGHTS = """<?xml version="1.0" encoding="UTF-8"?>
<Rights xmlns="http://v8.1c.ru/8.2/roles" version="2.20">
	<object><name>Document.Т_Реестр</name><right><name>Read</name><value>true</value></right></object>
	<object><name>WebService.Сервис.Operation.Получить</name><right><name>Use</name><value>true</value></right></object>
</Rights>
"""

MANAGER_MODULE = """&ИзменениеИКонтроль("ДобавитьКоманды")
Процедура Т_ДобавитьКоманды(Команды)
	Команда = Команды.Добавить();
#Вставка
	Команда.Т_Реестр = Истина;
#КонецВставки
#Вставка
	// только комментарий
#КонецВставки
#Удаление
	Команда.Порядок = 10;
#КонецУдаления
КонецПроцедуры

&ИзменениеИКонтроль("Печать")
Процедура Т_Печать(Массив)
	Возврат;
КонецПроцедуры

&После("ПриПолученииДанных")
Процедура Т_ПриПолученииДанныхПосле(Данные)
#Вставка
	Данные.Т_Флаг = Истина;
#КонецВставки
	Если ОбъектМетаданных = Метаданные.Документы.Приказ Тогда
	ИначеЕсли ОбъектМетаданных = Метаданные.Документы.Т_Реестр Тогда
	КонецЕсли;
КонецПроцедуры
"""

PREDEFINED_ADOPTED_ONLY = """<?xml version="1.0" encoding="UTF-8"?>
<PredefinedData xmlns="http://v8.1c.ru/8.3/xcf/predef" version="2.20">
	<Item id="1"><Name>Прочие</Name><ExtensionState>AdoptedCheck</ExtensionState></Item>
</PredefinedData>
"""

PREDEFINED = """<?xml version="1.0" encoding="UTF-8"?>
<PredefinedData xmlns="http://v8.1c.ru/8.3/xcf/predef" version="2.20">
	<Item id="1"><Name>Прочие</Name><ExtensionState>AdoptedCheck</ExtensionState></Item>
	<Item id="2"><Name>Т_Свой</Name></Item>
</PredefinedData>
"""

FILES = {
    "Configuration.xml": HEAD + (
        "<Configuration><Properties><Name>ТестРасширение</Name><NamePrefix>Т_</NamePrefix>"
        "<ConfigurationExtensionPurpose>Patch</ConfigurationExtensionPurpose></Properties>"
        "<ChildObjects><Language>Русский</Language><Document>Приказ</Document>"
        "<Subsystem>Кадры</Subsystem><Role>ПолныеПрава</Role><DefinedType>Владелец</DefinedType>"
        "<CommonForm>Печать</CommonForm><WebService>Сервис</WebService><Catalog>Виды</Catalog>"
        "<Catalog>Типы</Catalog><CommonModule>Пустой</CommonModule>"
        "<Bot>Бот</Bot></ChildObjects></Configuration>\n") + TAIL,
    "Languages/Русский.xml": md("Language", "Русский"),
    "Documents/Приказ.xml": md(
        "Document", "Приказ", internal=state(("ObjectModule", "Extended")),
        children=attr("Сотрудник", True) + attr("Т_Флаг", False)
        + "<Template>ПФ_Свой</Template><Template>ПФ_Чужой</Template>"
        + "<Template>ПФ_Замена</Template>"
        + "<Command><Properties><Name>Т_Отправить</Name></Properties></Command>"
        + "<Form>ФормаДокумента</Form>"),
    "Documents/Приказ/Ext/ObjectModule.bsl":
        '&После("ПриЗаписи")\nПроцедура Т_ПриЗаписиПосле(Отказ)\nКонецПроцедуры\n\n'
        'Процедура Т_Своя()\nКонецПроцедуры\n',
    "Documents/Приказ/Ext/Help.xml": "<Help/>\n",
    "Documents/Приказ/Ext/ManagerModule.bsl": MANAGER_MODULE,
    "Catalogs/Типы.xml": md("Catalog", "Типы", internal=state(("Predefined", "Extended"))),
    "Catalogs/Типы/Ext/Predefined.xml": PREDEFINED_ADOPTED_ONLY,
    "CommonModules/Пустой.xml": md("CommonModule", "Пустой", internal=state(("Module", "Extended"))),
    "CommonModules/Пустой/Ext/Module.bsl": "\ufeff",
    "Documents/Приказ/Templates/ПФ_Свой.xml": md("Template", "ПФ_Свой", adopted=False),
    "Documents/Приказ/Templates/ПФ_Свой/Ext/Template.xml": "<document/>\n",
    "Documents/Приказ/Templates/ПФ_Чужой.xml": md("Template", "ПФ_Чужой"),
    "Documents/Приказ/Templates/ПФ_Замена.xml": md(
        "Template", "ПФ_Замена", internal=state(("Template", "Extended"))),
    "Documents/Приказ/Templates/ПФ_Замена/Ext/Template.xml": "<document/>\n",
    "Documents/Приказ/Commands/Т_Отправить/Ext/CommandModule.bsl":
        "&НаКлиенте\nПроцедура ОбработкаКоманды(Параметр, Параметры)\nКонецПроцедуры\n",
    "Documents/Приказ/Forms/ФормаДокумента.xml": md(
        "Form", "ФормаДокумента", internal=state(("Form", "Extended"))),
    "Documents/Приказ/Forms/ФормаДокумента/Ext/Form.xml": DOC_FORM,
    "Subsystems/Кадры.xml": md(
        "Subsystem", "Кадры", props='<Content><xr:Item xsi:type="xr:MDObjectRef">'
        "Document.Т_Реестр</xr:Item></Content>", children="<Subsystem>Вложенная</Subsystem>"),
    "Subsystems/Кадры/Subsystems/Вложенная.xml": md(
        "Subsystem", "Вложенная", internal=state(("CommandInterface", "Extended")),
        props='<Content><xr:Item xsi:type="xr:MDObjectRef">Catalog.Виды</xr:Item></Content>'),
    "Roles/ПолныеПрава.xml": md("Role", "ПолныеПрава", internal=state(("Rights", "Extended"))),
    "Roles/ПолныеПрава/Ext/Rights.xml": RIGHTS,
    "DefinedTypes/Владелец.xml": md(
        "DefinedType", "Владелец", internal=state(("Type", "MultiState")),
        props='<Type xsi:type="xr:ExtendedProperty"><xr:ExtendValue xsi:type="v8:TypeDescription">'
              "<v8:Type>cfg:DocumentRef.Т_Реестр</v8:Type></xr:ExtendValue></Type>"),
    "CommonForms/Печать.xml": md("CommonForm", "Печать", internal=state(("Form", "Extended"))),
    "CommonForms/Печать/Ext/Form.xml": COMMON_FORM,
    "CommonForms/Печать/Ext/Form/Module.bsl":
        '&НаСервере\n&После("ПриСозданииНаСервере")\n'
        "Процедура Т_ПриСозданииНаСервереПосле(Отказ, СтандартнаяОбработка)\nКонецПроцедуры\n",
    "WebServices/Сервис.xml": md("WebService", "Сервис", adopted=False,
                                 children="<Operation><Properties><Name>Получить</Name>"
                                          "</Properties></Operation>"),
    "WebServices/Сервис/Ext/Module.bsl":
        'Функция Получить()\n\tЕсли РолиДоступны("Администратор, ПолныеПрава") Тогда\n'
        '\tКонецЕсли;\n\tЕсли РолиДоступны("ПолныеПраваДоп") Тогда\n\tКонецЕсли;\n'
        "\tВозврат Неопределено;\nКонецФункции\n",
    "Catalogs/Виды.xml": md("Catalog", "Виды", internal=state(("Predefined", "Extended"))),
    "Catalogs/Виды/Ext/Predefined.xml": PREDEFINED,
    "Bots/Бот.xml": md("Bot", "Бот", adopted=False),
}


def materialize(root):
    for rel, text in FILES.items():
        path = os.path.join(root, *rel.split("/"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)


def run_rc(*args, cwd=None):
    proc = subprocess.run([sys.executable, "-B", *args], capture_output=True,
                          text=True, encoding="utf-8", cwd=cwd)
    return proc.returncode, proc.stdout, proc.stderr


def run(*args, cwd=None):
    rc, out, err = run_rc(*args, cwd=cwd)
    if rc != 0:
        raise AssertionError(f"{os.path.basename(args[0])} exited {rc}:\n{err}")
    return out


def write(root, rel, text):
    path = os.path.join(root, *rel.split("/"))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


FAILURES = []


def expect(label, output, present=(), absent=()):
    for s in present:
        if s not in output:
            FAILURES.append(f"{label}: missing {s!r}")
    for s in absent:
        if s in output:
            FAILURES.append(f"{label}: unexpected {s!r}")


def main():
    keep = "--keep-work-dir" in sys.argv
    work = tempfile.mkdtemp(prefix="ext-tools-")
    ext = os.path.join(work, "ext")
    cfg = os.path.join(work, "cfg")
    try:
        materialize(ext)
        os.makedirs(cfg)
        with open(os.path.join(cfg, "Configuration.xml"), "w", encoding="utf-8") as fh:
            fh.write(FILES["Configuration.xml"])

        out = run(CFE_DIFF, "-ExtensionPath", ext, "-ConfigPath", cfg, "-Mode", "A")
        expect("cfe-diff", out, present=[
            "=== Summary: 9 borrowed, 2 own objects ===",
            "[BORROWED] Language.Русский",
            "[OWN]      WebService.Сервис",
            "[OWN]      Bot.Бот",
            "ChildObjects: 1 own attrs, 1 own templates, 1 own commands, 4 borrowed items",
            "Own Template: ПФ_Свой",
            "Own Command: Т_Отправить",
            "Template.ПФ_Замена (borrowed, content replaced)",
            '&После("ПриЗаписи")',
            "Documents/Приказ/Commands/Т_Отправить/Ext/CommandModule.bsl (no interceptors)",
            "Form.ФормаДокумента (borrowed, modified):",
            "Command:Т_Команда [After] -> Т_КомандаПосле",
            "Own Attribute: Т_Список",
            "Own element: Т_Кнопка (Button)",
            "Changed element: Поле",
            "Content: +1 item(s): Document.Т_Реестр",
            "Subsystem.Вложенная (borrowed)",
            "Content: +1 item(s): Catalog.Виды",
            "Extended: Rights [Extended] 2 object(s) granted",
            "Extended: Type [MultiState] +1 type(s): cfg:DocumentRef.Т_Реестр",
            '&После("ПриСозданииНаСервере") — line 2 in CommonForms/Печать/Ext/Form/Module.bsl',
            "Own Command: Т_ВРеестр",
            "Extended: Predefined [Extended] own item(s): Т_Свой",
            "=== Unclassified files: 1 ===",
            "[UNCLASSIFIED] Documents/Приказ/Ext/Help.xml",
        ], absent=["unknown type", "Own Template: ПФ_Чужой", "Extended: ObjectModule",
                   "Changed element: Кнопка"])

        cfe_file = os.path.join(work, "cfe-diff-A.txt")
        with open(cfe_file, "w", encoding="utf-8") as fh:
            fh.write(out)

        out = run(REGISTRY, "-ExtensionPath", ext)
        expect("registry-builder", out, present=[
            'DISPATCHER &После("ПриПолученииДанных")',
            "| Форм: ? | Блок: (fill in)",
            "each of the 1 DISPATCHER row(s) a number in Форм",
            "own attribute: Т_Флаг",
            "own Template: ПФ_Свой",
            "own Command: Т_Отправить",
            "borrowed template ПФ_Замена: content replaced",
            "borrowed form ФормаДокумента marked extended",
            '&После("ПриЗаписи") at Documents/Приказ/Ext/ObjectModule.bsl:1',
            "own routine added to a typical module: Т_Своя",
            "subsystem content: +1 item(s): Document.Т_Реестр",
            "=== Subsystem.Кадры.Subsystem.Вложенная ===",
            "extended Rights: 2 object(s) granted",
            "extended Type: +1 type(s): cfg:DocumentRef.Т_Реестр",
            '&После("ПриСозданииНаСервере") at CommonForms/Печать/Ext/Form/Module.bsl:2',
            "own predefined item(s): Т_Свой",
            "=== WebService.Сервис ===",
            "own module WebServices/Сервис/Ext/Module.bsl",
            "=== Bot.Бот ===",
            "=== 1 unclassified file(s)",
            "[UNCLASSIFIED] Documents/Приказ/Ext/Help.xml",
        ], absent=["own Template: ПФ_Чужой", "own attribute: Сотрудник"])

        out = run(REGISTRY, "-ExtensionPath", ext, "-GroupByModule")
        expect("registry-builder -GroupByModule", out, present=[
            "=== Document.Приказ ===",
            'Documents/Приказ/Ext/ManagerModule.bsl: 3 — &ИзменениеИКонтроль("ДобавитьКоманды")',
            'Documents/Приказ/Ext/ObjectModule.bsl: 1 — &После("ПриЗаписи")',
            "=== group-by-module: 1 object(s) with interceptors in 2+ modules ===",
        ])

        out = run(REGISTRY, "-ExtensionPath", ext, "-CloseAgainst", cfe_file)
        expect("registry-builder -CloseAgainst", out, present=[
            "[UNACCOUNTED] CommonModule.Пустой — module is empty (3 bytes): "
            "CommonModules/Пустой/Ext/Module.bsl",
            "[NESTED] Subsystem.Кадры.Subsystem.Вложенная",
            "absent from the registry by design (1) ===\n  Catalog.Типы",
            "Language.Русский;;",
            "1 unaccounted ===",
        ], absent=["[CHECK]", "[UNACCOUNTED] Catalog.Типы"])
        truncated = os.path.join(work, "cfe-diff-cut.txt")
        with open(truncated, "w", encoding="utf-8") as fh:
            fh.write(open(cfe_file, encoding="utf-8").read().split("=== Summary")[0])
        rc, _out, err = run_rc(REGISTRY, "-ExtensionPath", ext, "-CloseAgainst", truncated)
        if rc != 2 or "truncated" not in err:
            FAILURES.append(f"registry-builder -CloseAgainst on a truncated file: rc={rc} {err!r}")

        out = run(FORM_BASEDIFF, "-ExtensionPath", ext)
        expect("form-basediff", out, present=[
            "=== markup-changed  Document.Приказ.ФормаДокумента [BORROWED]",
            "Поле (InputField): -ReadOnly = true  [control: kept by Поле2 -> deliberate edit]",
            "Т_Кнопка (Button) under (form)",
            "own attribute: Т_Список",
            "=== markup-changed  CommonForm.Печать [BORROWED]",
            "own command: Т_ВРеестр",
            "Handler bindings (module wiring, not markup) (1):",
            "=== 2 form(s): 2 markup-changed, 0 markup-unchanged; 0 without a snapshot",
        ], absent=["Поле2 (InputField): -ReadOnly", "Кнопка: "])

        out = run(INSERT_BLOCKS, "-ExtensionPath", ext, "-Summary")
        expect("insert-blocks", out, present=[
            "[INSERT] Documents/Приказ/Ext/ManagerModule.bsl:7-9 "
            '&ИзменениеИКонтроль("ДобавитьКоманды") Т_ДобавитьКоманды [no executable lines]',
            "[INSERT] Documents/Приказ/Ext/ManagerModule.bsl:22-24 "
            '&После("ПриПолученииДанных") Т_ПриПолученииДанныхПосле [inside &После',
            'ManagerModule.bsl:15 &ИзменениеИКонтроль("Печать") Т_Печать — base module not checked',
            "=== 3 insert block(s), 1 delete block(s) in 1 file(s): 1 without executable lines, "
            "1 outside &ИзменениеИКонтроль; 2 &ИзменениеИКонтроль, 1 without a block",
        ])

        # insert-blocks: zero is an answer only when nothing could hold a block.
        plain = os.path.join(work, "plain")
        write(plain, "CommonModules/М/Ext/Module.bsl",
              '&После("Х")\nПроцедура Т_Х()\nКонецПроцедуры\n')
        rc, out, _err = run_rc(INSERT_BLOCKS, "-ExtensionPath", plain)
        if rc != 0 or "zero is the right answer here" not in out:
            FAILURES.append(f"insert-blocks on an extension without &ИзменениеИКонтроль: rc={rc}")
        commented = os.path.join(work, "commented")
        write(commented, "CommonModules/М/Ext/Module.bsl",
              '&ИзменениеИКонтроль("Х")\nПроцедура Т_Х()\n// #Вставка\n\tА = 1;\n'
              "// #КонецВставки\nКонецПроцедуры\n")
        rc, _out, err = run_rc(INSERT_BLOCKS, "-ExtensionPath", commented)
        if rc != 2 or "PARSE FAILURE" not in err:
            FAILURES.append(f"insert-blocks with &ИзменениеИКонтроль and no block: rc={rc}")

        # exchangeplan-content: one header format, typical vs own split.
        ep_base, ep_ext = os.path.join(work, "ep-base"), os.path.join(work, "ep-ext")
        content = ('<?xml version="1.0" encoding="UTF-8"?>\n<ExchangePlanContent '
                   'xmlns="http://v8.1c.ru/8.3/xcf/extrnprops">{}</ExchangePlanContent>\n')
        item = "<Item><Metadata>{}</Metadata><AutoRecord>Allow</AutoRecord></Item>"
        write(ep_base, "ExchangePlans/П/Ext/Content.xml", content.format(item.format("Catalog.Базовый")))
        write(ep_base, "Catalogs/Типовой.xml", md("Catalog", "Типовой", adopted=False))
        write(ep_ext, "ExchangePlans/П/Ext/Content.xml", content.format(
            item.format("Catalog.Типовой") + item.format("Document.Т_Свой")))
        out = run(EXCHANGE, "-Plan", "П", "-BasePath", ep_base, "-ExtPath", ep_ext)
        expect("exchangeplan-content", out, present=[
            "typical objects (present in the base tree) the extension pulls into this exchange "
            "(1):\n    Catalog.Типовой",
            "absent from the base tree — the extension's own (1):\n    Document.Т_Свой",
            "not evidence of removal (1):",
        ], absent=["was itself an object added by that extension"])
        headers = [l for l in out.splitlines() if l.rstrip().endswith(":") and not l.startswith("    ")]
        bad = [h for h in headers if not h.rstrip().endswith("):")]
        if bad:
            FAILURES.append(f"exchangeplan-content: headers not ending in '(N):': {bad}")

        # dispatch checker: a -BslFile relative to the extension tree resolves.
        rc, _out, err = run_rc(DISPATCH, "-ExtensionPath", ext, "-DefinedType", "Владелец",
                               "-BslFile", "Documents/Приказ/Ext/ObjectModule.bsl", cwd=work)
        if "BSL file not found" in err:
            FAILURES.append(f"dispatch-checker: relative -BslFile not resolved: {err.strip()}")

        out = run(REFERENCE, "-ExtensionPath", ext,
                  "-Object", "DefinedType.Владелец;;Role.ПолныеПрава;;CommonForm.Печать;;Catalog.Виды")
        expect("reference-finder", out, present=[
            "=== DefinedType.Владелец ===",
            "[OWN CONTENT] the extension adds to this object itself (Type)",
            "role check naming ПолныеПрава in 1 place(s)",
            "[OWN CONTENT] the extension adds to this object itself (Form)",
            "[METADATA REFERENCE] Catalog.Виды in 1 place(s):",
            "Subsystems/Кадры/Subsystems/Вложенная.xml:",
            "VERDICT: explained — own content",
        ], absent=["Unknown or unsupported object type"])
    finally:
        if keep:
            print(f"work dir kept: {work}")
        else:
            shutil.rmtree(work, ignore_errors=True)

    if FAILURES:
        for f in FAILURES:
            print(f"FAIL {f}")
        print(f"=== {len(FAILURES)} failure(s) ===")
        return 1
    print("=== extension tools regression: all checks passed ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
