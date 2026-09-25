# One test extension on a file manager infobase

A run has two sessions, and they are deliberately different:

| Session | Infobase | Client | Why exactly this |
|---|---|---|---|
| test manager | its own **file** infobase | **thick** (`1cv8 ENTERPRISE /F`) | the test is invoked through `Обработки`, which exists only on a thick client |
| test client | the tested infobase on a standalone server | **thin** (`1cv8c /S`) | a thick client cannot connect to `ibsrv` at all |

Both halves of that table are measured, not assumed:

- on a thin client `Обработки.<Тест>.ВыполнитьСценарий` does not compile — «Переменная не определена (Обработки)»;
- a thick client against `ibsrv` answers «Адрес 'tcp://…:1541' не является адресом кластера
  серверов 1С:Предприятия» over `/S`, and «Неопределена информационная база» over `/WS`.

Hence the manager base is a plain file infobase: nothing publishes it, nothing connects to it over
HTTP, it has no server, no ports and no sessions of its own to clean up.

## A test is a data processor without a form

```
Обработки.Т_<Возможность>_<Тип>_<Тест>.ВыполнитьСценарий(Контекст)  // модуль менеджера, &НаКлиенте
Обработки.Т_<Возможность>_<Тип>_<Тест>.ПолучитьМакет("<Шаг>")       // текстовый макет, серверный код
```

**The object name is composed by the builder, not by the author.** One extension holds every test
of the project in a single flat namespace, so uniqueness has to come from somewhere; taking it
from the path (`asset-model/ui/НаименованиеПоШаблону` → `Т_AssetModel_UI_НаименованиеПоШаблону`)
keeps the source name free to say only what the test checks. Nothing forces a test to be renamed
because a different capability took the name first, and a type prefix in the file name is
redundant with the directory it sits in.

The build refuses when two tests would produce the same object name, naming both source paths —
a manifest keyed by name would otherwise swallow one of them without a word.

The scenario's client code is the processor's **manager module**; every piece of code that has to
run in the *tested* base is a **text template** of the same processor. The scenario does not need a
form: the extension's managed application module reads the launch parameter and dispatches by test
name.

## Sources: BSL only

```
openspec/tests/<capability>/
├── unit/<Check>.bsl                 # проверка целиком; становится макетом «Проверка»
├── ui/<Scenario>/<Scenario>.bsl     # модуль менеджера обработки теста
├── ui/<Scenario>/server/<Step>.bsl  # его серверные шаги; имя файла = имя макета
└── e2e/<Scenario>/…                 # то же, тип e2e
```

The directory of a scenario **is** its processor: `<Scenario>.bsl` becomes the manager module and
every file of `server/` becomes a template named after it. Steps of different tests never mix, and
the mapping needs no rules — a step belongs to the folder it lies in. Two scenarios that need the
same step keep two copies; that is the price of the isolation, paid on purpose.

**The isolation covers the client code too**, and this is the part that surprises: a scenario's
manager module sees itself and the exported methods of `Т_Прогон`, nothing else. A helper defined
in a neighbouring scenario is not in scope, and the failure comes late — the build's `/CheckModules`
says «Процедура или функция с указанным именем не определена», naming the caller's line rather than
the missing author. Two scenarios that need the same helper keep two copies of it, exactly as they
do with a step; `ТекстыСообщений` lives in three of them at once in this project. A helper worth
sharing belongs in `Т_Прогон` — that is the skill's module, not the project's, so promoting one is
a change to the skill.

The scenario calls a step by its file name:

```bsl
Данные = Т_Прогон.ВыполнитьШаг(Контекст, "СоздатьДанные");
Т_Прогон.ВыполнитьШаг(Контекст, "УдалитьДанные", Новый Структура("ИдентификаторАктива", …));
```

## Two traps that cost a run each

- **The extension is created in safe mode**, and safe mode forbids `Новый ЗаписьТекста` — the
  protocol file is never written and the run looks hung. The builder clears it with
  `ibcmd … infobase config extension update --name=… --safe-mode=no`.
- **`add-template.py` registers the template only when `-ObjectName` is a bare object name**
  (`-ObjectName Т_УИТест -SrcDir <build>/DataProcessors`). Given a path to the object's `.xml` it
  creates the files but leaves `ChildObjects` empty, and `ПолучитьМакет` then fails with
  «Недопустимое значение параметра (параметр номер '1')».

## What the manager base cannot do

It holds no configuration, so the scenario may not use anything of the tested one:

| Not available | What to do instead |
|---|---|
| `&НаСервере` against the tested configuration | a server step in `server/<Step>.bsl`, sent with `Т_Прогон.ВыполнитьШаг` |
| common modules of the configuration (`ОбщегоНазначения`, project modules) | the same: the step runs in the tested base |
| references (`СправочникСсылка` …) in a step's result | strings of `УникальныйИдентификатор`; the step resolves them with `ПолучитьСсылку` |

`ПрочитатьJSON` returns **`Структура`** for objects by default, so a step's result comes back as
structures, not maps — `.Получить("ключ")` fails with «Метод объекта не обнаружен». The credentials
of the tested base are still read from `.dev.env` by the scenario.

## Build and freshness

```bash
python3 <skills>/1c-ui-testing/scripts/build-test-extension.py [--force]
```

The builder writes the source fingerprint into `<base>/tests.manifest.json` and skips the build
while it matches, so an ordinary run does not pay for it; the runner calls the builder before every
run, which is what keeps the extension and the sources from drifting apart. A file infobase cannot
be rebuilt while a session holds it — the builder refuses with the process ids instead of failing
half-way.

**The module check is not optional.** After the apply the builder runs Designer `/CheckModules
-ThickClientManagedApplication -Extension`, because a compile error in an extension module is
invisible until the run: the manager shows a dialog, the protocol stays empty, and the event log of
the tested base is clean. The check names the module and the line instead (it needs an X server;
without `DISPLAY` the builder says it was skipped).

## Run

```bash
<skills>/1c-ui-testing/scripts/run-ui-test.sh [<port>] --test <test name> [--via-manager]
```

`--test` takes the short name while it names exactly one test, and `<capability>/<kind>/<name>`
when it does not; an ambiguous short name is refused with both candidates printed rather than
resolved by guesswork. Logs and the protocol are named after the short name either way.

A `ui`/`e2e` test gets a test client in the tested base and the manager in the file base; a `unit`
test needs no client at all — the same file is sent straight to `Dbg_Executor` with `ib-http.py
--exec` of the `1c-test-debug` skill, which is seconds instead of a client session. `--via-manager`
forces a unit check through the manager, the way the extension provides it.

Sessions of killed runs hold licenses, and the third one makes the next client exit with «Файл
программной лицензии не найден». The runner terminates exactly the sessions that appeared in the
**tested** base during its own run; other sessions there belong to the operator and are left alone.
The file manager base has no sessions to clean.
