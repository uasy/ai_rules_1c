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
  - an Ext/ file nothing interprets, which must come out as [UNCLASSIFIED].

Usage:  python3 -B extension-tools-regression.py [--keep-work-dir]
Nothing here needs a 1C platform or the network.
"""

import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SKILLS = os.path.dirname(os.path.dirname(HERE))
CFE_DIFF = os.path.join(SKILLS, "1c-metadata-manage", "tools", "1c-cfe-manage", "scripts", "cfe-diff.py")
REGISTRY = os.path.join(SKILLS, "1c-extension-analysis", "tools", "1c-change-registry-builder",
                        "scripts", "registry-builder.py")
REFERENCE = os.path.join(SKILLS, "1c-extension-analysis", "tools", "1c-reference-finder",
                         "scripts", "reference-finder.py")

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
		</ChildItems>
		<Attributes>
			<Attribute name="Объект" id="1"><MainAttribute>true</MainAttribute></Attribute>
		</Attributes>
	</BaseForm>
</Form>
"""

COMMON_FORM = f"""<?xml version="1.0" encoding="UTF-8"?>
<Form {FORM_NS} version="2.20">
	<ChildItems>
		<Button name="Кнопка" id="1"><CommandName>Form.Command.Печать</CommandName></Button>
	</ChildItems>
	<Commands>
		<Command name="Печать" id="1"><Action>Печать</Action></Command>
		<Command name="Т_ВРеестр" id="2"><Action callType="After">Т_ВРеестрПосле</Action></Command>
	</Commands>
	<BaseForm version="2.20">
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


def run(*args):
    proc = subprocess.run([sys.executable, "-B", *args], capture_output=True,
                          text=True, encoding="utf-8")
    if proc.returncode != 0:
        raise AssertionError(f"{os.path.basename(args[0])} exited {proc.returncode}:\n{proc.stderr}")
    return proc.stdout


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
            "=== Summary: 7 borrowed, 2 own objects ===",
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

        out = run(REGISTRY, "-ExtensionPath", ext)
        expect("registry-builder", out, present=[
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
