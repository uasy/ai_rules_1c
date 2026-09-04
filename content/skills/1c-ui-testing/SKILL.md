---
name: 1c-ui-testing
description: "Automated UI testing of a 1C thick/thin client through the platform's own mechanism — test client (/TestClient) driven by a test manager (/TestManager) running a scenario data processor. Use when a task needs interactive UI verification of forms, commands and controls, or when a manual test plan has to be turned into a repeatable run."
---

# 1C UI testing — test manager and test client

The platform ships a full UI-automation mechanism (ITS 31.7, local copy of the article:
kept locally, outside the repository). Two 1C sessions take part:

- **test client** — the application under test, started with `/TestClient`; executes what the
  manager tells it;
- **test manager** — a session started with `/TestManager` that runs the scenario written in BSL
  and drives the client over TCP.

The scenario sees the *logical* interface model of the client (windows, forms, fields, buttons,
tables), not pixels. No change to the tested configuration is required.

An acceptance scenario written this way replaces a manual test plan and carries the acceptance
conditions itself: it drives the forms and verifies each outcome against the underlying API from
`&НаСервере` methods of the same manager module. That module is also where a precondition the UI
cannot produce is created — call the integration or object module directly to set the state up,
then drive the UI against it.

Runner — `skills/1c-ui-testing/scripts/run-ui-test.sh` (see *Runner* below).

## Preconditions

- **An X server is mandatory.** Both sessions are ordinary 1C windows; there is no headless mode
  batch startup mode does not make the 1C client headless. `DISPLAY` must be set.
- Platform path and infobase come from `.dev.env` (`PLATFORM_PATH`, `INFOBASE_PATH`, `IB_USER`,
  `IB_PASSWORD`).
- Automated testing works **only for the managed application** (ITS 31.7.1).
- Session startup on a large infobase is slow — count on ~50 s per session, ~2 min per run.
  Poll for readiness, never assume a fixed short sleep is enough.

## Step 1 — start the test client

Start it **empty**: the scenario opens whatever it needs itself (see step 3). Launch through the
`1c-metadata-manage` skill's `db-ops` tool — `docs/db-manage.md → 2. Run 1C Enterprise` — never an
ad-hoc `1cv8` command line:

```bash
python3 skills/1c-metadata-manage/tools/1c-db-ops/scripts/db-run.py \
  -V8Path "$PLATFORM_PATH" -InfoBasePath "$INFOBASE_PATH" \
  -UserName "$IB_USER" -Password "$IB_PASSWORD" \
  -AdditionalV8Arguments "/TestClient,-Tport,1538" \
  -Out tmp/ui-test.client.log &
```

- `-AdditionalV8Arguments` takes a comma-separated list; each comma-separated item becomes one
  argv entry, so `/TestClient -Tport 1538` is written `"/TestClient,-Tport,1538"`.
- The port defaults to 1538. Give an explicit one whenever several clients run on the machine.
- A client started this way shows **"Клиент тестирования"** in its main window title; in BSL the
  session can check itself with `ТекущийСеансТестируется()`.
- **Wait for the port, not for a timer** — the manager wastes its retry budget against a closed
  port:

```bash
for _ in $(seq 1 120); do ss -ltn | grep -q ":1538\b" && break; sleep 1; done
```

## Step 2 — start the test manager

Same tool, `/TestManager` plus the scenario data processor:

```bash
python3 skills/1c-metadata-manage/tools/1c-db-ops/scripts/db-run.py \
  -V8Path "$PLATFORM_PATH" -InfoBasePath "$INFOBASE_PATH" \
  -UserName "$IB_USER" -Password "$IB_PASSWORD" \
  -Execute /abs/path/УИТест.epf \
  -CParam "УИМенеджер|1538|localhost|/abs/path/tmp/ui-test.result.txt" \
  -AdditionalV8Arguments "/TestManager" \
  -Out tmp/ui-test.manager.log -Wait
```

- `-Execute` opens the scenario data processor after startup; `-CParam` becomes `ПараметрЗапуска`
  inside it. Pass absolute paths — the session's working directory is not guaranteed.
- `-Wait` blocks until the session exits. Wrap it in `timeout`: a scenario that hangs leaves the
  session alive forever.
- The manager's window title shows **"Менеджер тестирования"**. Seeing it is the cheapest proof
  that the mode was accepted.
- **Cleanup:** `db-run` runs `1cv8` as a child process, so killing the wrapper leaves the client
  alive holding the port. Kill by pattern: `pkill -f "1cv8 ENTERPRISE.*-Tport <port>"`.

## Step 3 — the scenario data processor

An EPF with one managed form; the scenario lives in the form module and is launched from
`ПриОткрытии`. Build it with the `1c-metadata-manage` skill (`1c-epf-scaffold` → `1c-form-scaffold`
→ `1c-form-compile` → `1c-epf-validate` → `1c-epf-build`).

### Two traps that cost hours if missed

1. **Declare the form event handlers in `Form.xml`.** A handler procedure in the form module is
   never called unless the event is declared:

   ```xml
   <Events>
     <Event name="OnOpen">ПриОткрытии</Event>
   </Events>
   ```

   `1c-form-scaffold` generates the form **without** this block, and the platform reports nothing —
   no error, no event-log record, the module simply never runs. Declare it through the `events`
   key of the `1c-form-compile` JSON DSL, never by hand-editing `Form.xml`.

2. **`Новый ТестируемоеПриложение` is resolved at compile time.** In a session started *without*
   `/TestManager` the whole form module fails to compile, and the event log shows
   `{ВнешняяОбработка.<Имя>.Форма.Форма.Форма(<строка>)}: Тип не определен (ТестируемоеПриложение)`.
   Consequence: such a data processor cannot be opened by hand in a normal session — that is
   expected, not a defect.

### Skeleton

```bsl
&НаКлиенте
Процедура ПриОткрытии(Отказ)

	// Роль задаётся параметром запуска /C; при открытии вручную он пуст и сценарий не стартует.
	// ЗавершитьРаботуСистемы в ПриОткрытии платформа не выполняет - откладываем на обработчик.
	Если СтрНачинаетсяС(ПараметрЗапуска, "УИМенеджер") Тогда
		ПодключитьОбработчикОжидания("ВыполнитьСценарийПакетно", 0.1, Истина);
	КонецЕсли;

КонецПроцедуры

&НаКлиенте
Процедура ВыполнитьСценарийПакетно()

	Попытка
		Приложение = Новый ТестируемоеПриложение("localhost", 1538);
		Приложение.УстановитьСоединение();   // повторять в цикле до таймаута
		ВыполнитьСценарий(Приложение);
		Приложение.РазорватьСоединение();
	Исключение
		ЗаписатьШаг(Ложь, "Сценарий прерван: " + ОписаниеОшибки());
	КонецПопытки;

	ЗавершитьРаботуСистемы(Ложь);

КонецПроцедуры
```

Rules that make a run diagnosable:

- **Wrap the whole scenario body in `Попытка/Исключение`, and make the exception branch write the
  error and reach `ЗавершитьРаботуСистемы`.** This is the single rule that decides whether a failed
  run costs a minute or an hour. Without it an unhandled exception leaves the manager session
  sitting on screen with no output: the runner hits its `timeout`, the client is still holding the
  port, and the only way left to find out what happened is taking screenshots of the X display.
  With it, every failure comes back as a `[FAIL]` line with `ОписаниеОшибки()` and both sessions
  close by themselves. Every step that can throw (connect, `НайтиОбъект` on a missing element,
  `ВыполнитьКоманду` on a wrong URL) is inside that block.
- Never let a helper swallow an exception silently — an empty `Исключение` branch reproduces the
  same hang one level down.
- Rewrite the protocol file **on every step**, not once at the end: when the session is killed by a
  timeout, the already-written steps show exactly where it stopped.
- Duplicate every step into the event log (`ЗаписьЖурналаРегистрации`, own event name such as
  `УИТест.Шаг`) — see step 4 for how to read it back.
- End with `ЗавершитьРаботуСистемы(Ложь)`, otherwise the manager session never exits.

### Driving the client

Open forms by command URL rather than by clicking through the interface (ITS 31.7.4):

```bsl
ГлавноеОкно = Приложение.НайтиОбъект(Тип("ТестируемоеОкноКлиентскогоПриложения"));
ГлавноеОкно.Активизировать();
ГлавноеОкно.ВыполнитьКоманду("e1cib/command/Справочник.Контрагенты.Создать");
Приложение.ОжидатьОтображениеОбъекта(Тип("ТестируемаяФорма"), "Контрагент*", , 60);
Форма = Приложение.НайтиОбъект(Тип("ТестируемаяФорма"), "Контрагент*");
Поле = Форма.НайтиОбъект(Тип("ТестируемоеПолеФормы"), "Наименование");
Поле.Активизировать();
Поле.ВвестиТекст("Новый контрагент");
Кнопка = Форма.НайтиОбъект(Тип("ТестируемаяКнопкаФормы"), "Записать и закрыть");
Кнопка.Нажать();
```

### Traps in the tested-object API

Each of these costs a run to find.

- **Always pass a timeout to `НайтиОбъект` / `НайтиОбъекты`.** The default search time is
  *unbounded* — a missing object hangs the scenario until the runner's `timeout` kills it.
- **Open a data processor form by the link the platform builds itself.**
  `ПолучитьНавигационнуюСсылку(Обработки.<Имя>.Создать())` returns `e1cib/app/Обработка.<Имя>`;
  hand-written spellings such as `e1cib/app/Обработка.<Имя>.Форма` open an error window instead.
- **Column addressing differs by method.** `ПерейтиКСтроке` matches by column *title*
  (`Соответствие("Наименование", …)`); `ПолучитьТекстЯчейки` takes the column *element name*
  (`РазделыНаименование`). Mixing them up gives "В элементе управления отсутствует указанное
  значение".
- **`Развернуть()` on an already expanded node throws** "Неподходящее состояние элемента
  управления" — wrap it, an already expanded node is the state you wanted anyway.
- **Standard dialogs are ordinary tested objects.** `ПоказатьВводСтроки` is a `ТестируемаяФорма`
  whose title is the `Подсказка` argument; a question / warning is found by its button
  (`"Да"`, `"ОК"`), and the dialog form is reached with `ПолучитьРодителя()` from that button.
  The message text lives in the form's decorations — and a decoration with no title returns its
  own *element name* (`Icon`, `Title`, `Hyperlink`) from `ТекстЗаголовка`, so filter out
  `ТекстЗаголовка = Декорация.Имя`. Reading and closing these dialogs is how a scenario asserts
  that a server refusal is actually shown to the user, instead of stalling on it.
- **Close every form you open and re-activate the main one.** A leftover window covers the form
  under test and its elements start failing with "Недоступный пользователю элемент управления не
  может выполнять интерактивные действия".
- **`Окно` is a managed-form property** — a local variable of that name assigns into the form
  instead ("Поле объекта недоступно для записи"). Same class of trap as the `url` form attribute.
- **`ПерейтиКСтроке` on an empty table throws** "Структура описания строки не совпадает со
  структурой данных в элементе управления" instead of reporting "row not found" — there is no
  row structure to compare against. Assertions of the form "the item is gone from this list"
  land exactly on that case, so treat the exception as "not found".
- **A run killed by a timeout leaves the 1C sessions alive.** The test client keeps holding its
  port, and the next run's manager silently attaches to *that* client while the runner's startup
  `rm -f` wipes the protocol — the failure looks like an unexplained hang with no result lines at
  all. The runner shipped with this skill refuses to start on an occupied port; keep that check
  in any runner you write.
- **There is no sleep primitive in BSL.** When the system under test needs a moment to make a
  change readable (an external system often does, on deletes), separate re-reads with an active
  wait on
  `ТекущаяУниверсальнаяДатаВМиллисекундах` — never with a tight loop of API calls.

Object model (all available from 8.3.1, thin and thick client):

| Type | What it is | Key members |
|---|---|---|
| `ТестируемоеПриложение` | the connection | `УстановитьСоединение`, `РазорватьСоединение`, `НайтиОбъект`, `НайтиОбъекты`, `ОжидатьОтображениеОбъекта`, `ОжидатьСостояния`, `ПолучитьАктивноеОкно`, `УстановитьРезультатДиалогаВыбораФайла`, `УстановитьМаксимальноеВремяВыполненияДействия` |
| `ТестируемоеОкноКлиентскогоПриложения` | application window | `Активизировать`, `ВыполнитьКоманду`, `Закрыть`, `ПолучитьКомандныйИнтерфейс`, `ПолучитьТекстыСообщенийПользователю`, `Заголовок` |
| `ТестируемаяФорма` | managed or ordinary form | `Активизировать`, `НайтиОбъект`, `ВыполнитьВыборИзМеню`, `ВыполнитьВыборИзСписка`, `ОжидатьЗакрытие`, `ПолучитьТекущийЭлемент`, `ТекущаяМодифицированность` |
| `ТестируемоеПолеФормы` | input field | `Активизировать`, `ПолучитьПредставлениеДанных`, `ТекущаяВидимость`, `ТекущаяДоступность`, `ТекущееТолькоПросмотр`, `ПолучитьКонтекстноеМеню`; typing methods live on the per-kind extension (`ВвестиТекст`, …) |
| `ТестируемаяКнопкаФормы` | button | `Нажать`, `Активизировать`, `ТекущаяДоступность`, `ТекущаяВидимость`, `ТекущееПометка` |
| `ТестируемаяТаблицаФормы` | table | `ДобавитьСтроку`, `ИзменитьСтроку`, `УдалитьСтроку`, `ЗакончитьРедактированиеСтроки`, `ПерейтиКСтроке`, `ПолучитьТекстЯчейки`, `ПолучитьВыделенныеСтроки`, `Развернуть` / `Свернуть`, `Выбрать`, `УстановитьПорядок` |
| `ТестируемаяДекорацияФормы` | decoration | hyperlink / picture click |

`НайтиОбъект(<Тип>, <ТекстЗаголовка>, <Имя>, <Таймаут>)` — title and name accept `*` and `?`
wildcards; without a timeout the search is unbounded. `ОжидатьОтображениеОбъекта` has the same
signature, returns `Булево` and defaults to a 60 s timeout — prefer it over a bare `НайтиОбъект`
right after an action that opens a window.

Verify any method against `1C-docs-mcp` (`docinfo "ТестируемаяФорма"` etc.) before using it — the
set differs between platform versions.

## Step 4 — reading the results

Two channels, both usable from outside the session:

1. **Protocol file** written by the scenario (`tmp/<scenario>.result.txt`). Lines `[OK] …` /
   `[FAIL] …`; the runner greps for `^\[FAIL\]` to decide the exit code.
2. **Event log** — the only channel that shows platform-side failures the session never reported
   (a module that failed to compile, an unhandled error before the scenario started). Duplicate
   every scenario step into it (`ЗаписьЖурналаРегистрации` with an own event name such as
   `УИТест.Шаг`), then read it back after the run:

   - **`1c-data-mcp`**, when the server is exposed — `vcloggetlasterror` for the last error, or a
     `ВыгрузитьЖурналРегистрации` call wrapped in `vcexecutecode` for a filtered read
     (`skills/mcp-1c-tools/docs/1c-data-mcp.md`). This is the portable route; prefer it.
   - Otherwise `ВыгрузитьЖурналРегистрации` into an XML file from a batch session, or whatever
     debug HTTP service the project itself publishes.

   Platform failures surface as `_$PerformError$_` — that is how the "Тип не определен
   (ТестируемоеПриложение)" trap above is found.

Preparing test data and checking post-conditions the UI does not show is the same story: run the
BSL through `1c-data-mcp`'s `vcexecutecode` when available, or through a batch session, rather than
bending the scenario around a state the UI cannot reach.

Screenshots (`import -window root`) are the last resort, and needing them is a signal that step 3's
`Попытка/Исключение` rule was not followed: a scenario that reports its own failures never leaves
you guessing whether the session is still on the splash screen. Keep them for the one case the
scenario cannot report on — the client or manager failing before the scenario starts.

## Runner

`scripts/run-ui-test.sh` does all of the above: reads `.dev.env`, clears a leftover client off the
port, starts the client, waits for the port, runs the manager under `timeout`, prints the protocol,
kills leftover sessions, and exits non-zero on any `[FAIL]` or a missing protocol.

```bash
skills/1c-ui-testing/scripts/run-ui-test.sh [<port>] [<scenario epf>]
```

The scenario is the second argument, or `UI_TEST_SCENARIO` in `.dev.env` when it is omitted; the
runner refuses to start without one. Protocol and log file names are derived from the EPF base name
(`tmp/<name>.result.txt`, `tmp/<name>.client.log`, `tmp/<name>.manager.log`), so runs of different
scenarios do not overwrite each other. It locates `db-run.py` in the sibling `1c-metadata-manage`
skill; override with the `DB_RUN` environment variable if the skill lives elsewhere.

Rebuild the EPF after every scenario edit (`1c-epf-build`) — the runner uses the built file, not
the sources.

## Checklist for a new scenario

1. `recall` for project specifics, then write the scenario steps as verifiable
   assertions (`ЗаписатьШаг(<условие>, <что проверено>)`), not as a click list.
2. Scaffold or extend the EPF through `1c-metadata-manage`; **declare every form event in
   `Form.xml`**.
3. Check the scenario body is inside `Попытка/Исключение` with `ЗавершитьРаботуСистемы` after it —
   before running anything. Lint the module (`syntaxcheck` / `bsl_check_file`), then
   `1c-epf-validate` and `1c-epf-build`.
4. Run `scripts/run-ui-test.sh`; on a hang read the event log (step 4) before changing anything.
5. Record the outcome where the task expects it (manual test plan, `tasks.md`, report in `tmp/`).
