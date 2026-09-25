---
name: 1c-ui-testing
description: "Automated UI testing of a 1C thick/thin client through the platform's own mechanism — test client (/TestClient) driven by a test manager (/TestManager) that runs the scenario from a test extension of its own infobase. Use when a task needs interactive UI verification of forms, commands and controls, or when a manual test plan has to be turned into a repeatable run."
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
conditions itself: it drives the forms and verifies each outcome against the underlying API. The
manager works in an infobase of its own, so that API is reached over HTTP — a server step sent to
`Dbg_Executor` of the tested base (`1c-test-debug`). A precondition the UI cannot produce is
created the same way: the step writes the state, the scenario drives the UI against it.
Layout, build and constraints — [docs/test-extension.md](docs/test-extension.md).

Runner — `skills/1c-ui-testing/scripts/run-ui-test.sh` (see *Runner* below).

**This is not a trivial task.** A scenario runs two 1C sessions against a real infobase, and most of
the time lost on it goes to the environment, not to the scenario. Before writing anything: read
this skill to the end, read the project's own test tooling section (a project may override the
runner and add diagnostics), and check that the MCP servers you will use for platform methods and
code navigation actually answer.

## Preconditions

- **An X server is mandatory.** Both sessions are ordinary 1C windows; there is no headless mode
  batch startup mode does not make the 1C client headless. `DISPLAY` must be set.
- Platform path and infobase come from `.dev.env` (`PLATFORM_PATH`, `INFOBASE_PATH`, `IB_USER`,
  `IB_PASSWORD`).
- **`INFOBASE_PUBLISH_URL` is the tested infobase** — the one the *test client* works in and the one
  the scenario reaches over HTTP for its server steps. It is never the manager's own base: that one
  is built by `scripts/build-test-extension.py` and has an address of its own
  ([docs/test-extension.md](docs/test-extension.md)).
- Automated testing works **only for the managed application** (ITS 31.7.1).
- Session startup on a large infobase is slow — count on ~50 s per session, ~2 min per run.
  Poll for readiness, never assume a fixed short sleep is enough.
- **The screen must not be locked.** Under the lock screen the test client still connects and
  runs server calls, but its forms do not open: the scenario fails on waits ("форма не открылась")
  and everything on the machine slows down. Check `loginctl show-session <id> -p LockedHint` and
  disable automatic screen locking on a machine that runs UI tests unattended. The shipped runner
  refuses to start on a locked screen (exit code 3).
- **Server-side checks run before or after a scenario, not during it.** A request through the
  publication that writes data while the run is in progress has been seen to kill the worker that
  serves it — `1c-test-debug/docs/troubleshooting.md`; the server itself is `1c-ibsrv-ops`. Data a scenario needs is prepared from the
  manager's own `&НаСервере` code, or through the debug services before the run.
- **Leftover sessions block a run.** A client that was killed leaves its session alive: it holds a
  license, and with a file infobase it holds the base itself — the test client then never connects,
  1C processes live with no window and no protocol. List and terminate them before blaming the
  scenario (`1c-ibsrv-ops/scripts/ib-sessions.py auto list | terminate-all`).

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

Same tool, `/TestManager`, and the infobase the manager works in — **not** the tested one:

```bash
python3 skills/1c-metadata-manage/tools/1c-db-ops/scripts/db-run.py \
  -V8Path "$PLATFORM_PATH" -ClientKind thick -InfoBasePath "$PROJECT_ROOT/base-tests" \
  -CParam "УИМенеджер|1538|localhost|/abs/path/tmp/<test>.result.txt|$PROJECT_ROOT|$INFOBASE_PUBLISH_URL|<test>" \
  -AdditionalV8Arguments "/TestManager" \
  -Out tmp/<test>.manager.log -Wait
```

- The manager base is a **file** infobase built by `scripts/build-test-extension.py`, and the
  manager is a **thick** client: the test is invoked through `Обработки`, which a thin client does
  not have, and a thick client cannot reach a standalone server at all
  ([docs/test-extension.md](docs/test-extension.md)). It has no users, so no credentials are passed.
- `-CParam` becomes `ПараметрЗапуска` inside the session; its last element is the test name, which
  the extension's dispatcher resolves. Pass absolute paths — the session's working directory is not
  guaranteed.
- `-Wait` blocks until the session exits. Wrap it in `timeout`: a scenario that hangs leaves the
  session alive forever.
- The manager's window title shows **"Менеджер тестирования"**. Seeing it is the cheapest proof
  that the mode was accepted.
- **Cleanup:** `db-run` runs `1cv8` as a child process, so killing the wrapper leaves the client
  alive holding the port. Kill by pattern: `pkill -f "1cv8c.*-Tport <port>"` for the client and
  `pkill -f "1cv8 ENTERPRIS[E].*base-tests"` for the manager.

## Step 3 — the scenario

One BSL file with one entry point:

```bsl
// openspec/tests/<capability>/ui/<Scenario>/<Scenario>.bsl
&НаКлиенте
Процедура ВыполнитьСценарий(Контекст) Экспорт
	Приложение = Т_Прогон.ПодключитьсяККлиентуТестирования(Контекст);
	Данные = Т_Прогон.ВыполнитьШаг(Контекст, "СоздатьДанные");   // сервер проверяемой базы
	…
	Т_Прогон.ЗаписатьШаг(Контекст, Условие, "что именно проверено");
КонецПроцедуры
```

The build makes it the manager module of a data processor of the test extension and dispatches to
it by the test name — [docs/test-extension.md](docs/test-extension.md). There is no form, no
external data processor and no security prompt for the unattended session to answer.

### Two traps that cost hours if missed

1. **`Новый ТестируемоеПриложение` is resolved at compile time.** In a session started *without*
   `/TestManager` the module does not compile at all — which is why the scenario lives in the test
   extension of the manager infobase and is never opened by hand in a normal session.

2. **A module that does not compile hangs the run without a trace in the protocol.** A call to a
   procedure the module does not define, a misspelt platform method, a name of the tested
   configuration that the manager base does not have — each is a compile error: the manager session
   shows a modal window, no protocol line is written, and the event log of the tested base stays
   clean. The BSL linter does **not** report calls to undefined procedures. The builder's
   `/CheckModules` pass is what names the module and the line
   ([docs/test-extension.md](docs/test-extension.md)); never run with that check skipped.

### Skeleton

```bsl
// openspec/tests/<capability>/ui/<Сценарий>/<Сценарий>.bsl
&НаКлиенте
Процедура ВыполнитьСценарий(Контекст) Экспорт

	Приложение = Неопределено;
	Попытка
		Приложение = Т_Прогон.ПодключитьсяККлиентуТестирования(Контекст);
		Данные = Т_Прогон.ВыполнитьШаг(Контекст, "СоздатьДанные");
		ПроверитьФорму(Контекст, Приложение, Данные);
	Исключение
		Т_Прогон.ЗаписатьШаг(Контекст, Ложь, "Сценарий прерван: " + ОписаниеОшибки());
	КонецПопытки;

	Если Приложение <> Неопределено Тогда
		Попытка
			Приложение.РазорватьСоединение();
		Исключение
			Т_Прогон.ЗаписатьШаг(Контекст, Истина, "Соединение уже разорвано клиентом");
		КонецПопытки;
	КонецЕсли;

	Т_Прогон.ВыполнитьШаг(Контекст, "УдалитьДанные", Объявления);

КонецПроцедуры
```

Rules that make a run diagnosable:

- **Wrap the whole scenario body in `Попытка/Исключение` and write the error into the protocol.**
  This is the single rule that decides whether a failed run costs a minute or an hour. Without it
  an unhandled exception leaves the manager session sitting on screen with no output: the runner
  hits its `timeout`, the client is still holding the port, and the only way left to find out what
  happened is taking screenshots of the X display. Every step that can throw (connect, `НайтиОбъект`
  on a missing element, `ВыполнитьКоманду` on a wrong URL) is inside that block.
- Never let a helper swallow an exception silently — an empty `Исключение` branch reproduces the
  same hang one level down.
- The protocol file is rewritten on every step by `Т_Прогон.ЗаписатьШаг`, so a session killed by a
  timeout still shows where it stopped. The final line and the session shutdown belong to the
  dispatcher, not to the scenario: do not call `ЗавершитьРаботуСистемы` yourself.
- **Remove leftovers of earlier runs at the start, not only your own data at the end.** A run
  stopped by a timeout, a lost session or a locked screen never reaches its cleanup. Give the test
  data an unmistakable invented marker (a name prefix) and delete everything carrying it before
  creating fresh data.

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
  instead ("Поле объекта недоступно для записи"). Same class of trap as `url`, `Заголовок`,
  `Параметры`, `ТекущийЭлемент` (the last one fails as "Несоответствие типов"). Prefix them:
  `ОкноФормы`.
- **Typed text reaches the form data only when focus leaves the field by traversal.**
  `ВвестиТекст` fills the field, but the value is committed only after
  `Форма.ПерейтиКСледующемуЭлементу()`; activating another field does not commit it. Compare
  `ПолучитьТекстРедактирования` (what was typed) with `ПолучитьПредставлениеДанных` (form data)
  when unsure.
- **A field with «Предупреждение при редактировании»** opens a `MessageBox` («Продолжить
  редактирование?», buttons «Да» / «Нет») on the first input; until it is answered the form is
  "недоступна пользователю". Find the `ТестируемаяФорма` named `MessageBox` and press «Да».
- **Input does not set `ТекущаяМодифицированность`?** Check `<SavedData>true</SavedData>` on the
  main attribute in `Form.xml` first: without it the platform does not consider the form modified
  for a user either — no asterisk in the title, no save question.
- **Infobase checks from the manager session go through a query or a transaction.** Reading an
  attribute through a reference (`Ссылка.Реквизит`), and even `ПолучитьОбъект()` outside a
  transaction, is served from the session cache and returns the value from before the client
  session wrote it — restoring data then passes falsely and auto-save checks fail falsely.
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
   - **`1c-test-debug`** — `scripts/ib-errors.py` through the debug extension, when the project
     has it installed; the runner calls it by itself after a hang.
   - Otherwise `ВыгрузитьЖурналРегистрации` into an XML file from a batch session.

   Platform failures surface as `_$PerformError$_` — that is how the "Тип не определен
   (ТестируемоеПриложение)" trap and a scenario module that does not compile are found.

   **A run that produced no protocol line at all is never re-run unchanged.** Read the event log
   first: a compile error of the scenario, a leftover session holding the port or the infobase are
   all visible there or in the session list, and a blind re-run costs a full `timeout` again.

Preparing test data and checking post-conditions the UI does not show is the same story: run the
BSL through `1c-data-mcp`'s `vcexecutecode` when available, or through a batch session, rather than
bending the scenario around a state the UI cannot reach.

**Guard against a false green.** A step that checks "the value changed" must fail when nothing
changed: match the exact key being edited rather than the first occurrence of a value (the same
value may sit in a comment line), and require the effect itself (a non-empty change plan, a new
value read back by query), not just the absence of an error. Run every new scenario once against
a deliberately wrong expectation and make sure exactly the affected steps turn `[FAIL]`.

Screenshots (`import -window root`) are the last resort, and needing them is a signal that step 3's
`Попытка/Исключение` rule was not followed: a scenario that reports its own failures never leaves
you guessing whether the session is still on the splash screen. Keep them for the one case the
scenario cannot report on — the client or manager failing before the scenario starts. The root
window shows only what is on top: a 1C window covered by another application is not in the picture.

## The manager in a separate infobase

The manager and the client do not share an infobase: the manager is a **thick** client in a
**file** base whose extension holds every test of the project, and drives a **thin** test client in
the tested one — the two client kinds are forced by the platform, see the doc below. The
scenario therefore touches no metadata of the tested configuration — data preparation, cleanup and
verification go through `Dbg_Executor` of `1c-test-debug`. Build, constraints and the traps —
[docs/test-extension.md](docs/test-extension.md), script `scripts/build-test-extension.py`.

Useful when the tested base is a restored dump under a standalone server, when a run must not add
sessions to the tested base, or when the tested configuration is reloaded under a running scenario.

## Runner

`scripts/run-ui-test.sh` does all of the above: reads `.dev.env`, refuses to start on a locked screen,
clears a leftover client off the port, starts the client, waits for the port, starts the manager,
**fails fast** — no manager connection within `UI_TEST_CONNECT_TIMEOUT` (240 s), no protocol line
within `UI_TEST_FIRST_STEP_TIMEOUT` (360 s), or a protocol that has not grown for
`UI_TEST_STALL_TIMEOUT` (300 s) stops the run — prints the protocol, kills leftover
sessions of both roles, and exits non-zero on any `[FAIL]` or a missing protocol. After a stop or a
missing protocol it prints the event-log errors — through `scripts/ib-errors.py` of the
`1c-test-debug` skill when it is installed, or through `UI_TEST_DIAG_CMD` when set — so a scenario that
does not compile is named in the runner's own output. The scenario receives
`УИМенеджер|<port>|<client address>|<protocol file>|<project root>|<publication of the tested
base>` — the last element is what a scenario in a manager base of its own uses to reach
`Dbg_Executor` of the tested base.

**What the runner does is not repeated by hand.** Checking `DISPLAY` or the lock screen, looking
for leftover 1C processes, killing them, waiting for the port and reading the event log after a
hang are the runner's job. Call the runner, read its output; act on the environment only when the
runner reports a problem it cannot solve.

**A project may ship its own runner** (for example with project-specific diagnostics built in).
When the project rules name one, use that runner, not this copy.

```bash
skills/1c-ui-testing/scripts/run-ui-test.sh [<port>] --test <test name> [--via-manager]
```

The runner rebuilds the test extension when the sources changed, finds the test by name and runs it
([docs/test-extension.md](docs/test-extension.md)). A `unit` test goes straight to `Dbg_Executor`
without any 1C session; `--via-manager` forces it through the manager instead.

The name is the short one (`НаименованиеПоШаблону`) while it belongs to a single test, or
`<capability>/<kind>/<name>` when two capabilities share it — the runner prints both candidates
instead of picking one.

**A test name says what the test checks, and nothing else.** A kind prefix (`Юнит`, `УИ`, `E2E`),
the capability, or the technology the capability is already named after all repeat something the
path has said. Worse, a name loaded that way is a name someone else can take first, and the second
test then gets named after whatever word was still free rather than after what it checks.
Uniqueness is not the author's problem: the build names the object `Т_<Capability>_<Kind>_<Name>`,
so the same short name in two capabilities is legal.

Put such a word in only when it carries meaning the path does not. `АдресСервераPasswork` in the
`predefined-reference-data` capability is one: the subject really is the Passwork server, and the
capability name does not say so. Where a unit check and a UI scenario of one capability cover the
same requirement, they still get different names, because they check different things — the
function and the form — and two tests named alike are ambiguous to the runner for no gain.

Protocol and log file names are derived from the test name (`tmp/<name>.result.txt`,
`tmp/<name>.client.log`, `tmp/<name>.manager.log`), so runs of different tests do not overwrite
each other. A `unit` check answers with JSON rather than a protocol: the runner saves it whole to
`tmp/<name>.result.json` and prints a summary — every failed step in full, then
`Steps: <total>, failed: <failed>`. It summarises rather than truncates on purpose: a check has
as many steps as it needs, and the one that failed is as likely to be the twenty-third as the
first. It locates `db-run.py` in the sibling `1c-metadata-manage`
skill; override with the `DB_RUN` environment variable if the skill lives elsewhere.

Nothing has to be rebuilt by hand: the runner calls the builder, which rebuilds the extension only
when the sources changed.

## Running from an autonomous agent

An agent started non-interactively (`claude -p`, CI) has no one to look at the screen and no
turn after it stops:

- **Run in the foreground, never in the background.** In a non-interactive session a turn that
  ends while a background task is running may end the process, and the task is killed with it — the
  run is lost without a protocol. Run the runner in the foreground under `timeout` that fits one
  tool call (for example `timeout 570` with a 600000 ms call timeout), allowing a minute or more for
  manager startup. Never schedule a wake-up instead of waiting.
- **One run at a time** — the port and the infobase are shared.
- **After a run without protocol lines, diagnose before re-running** (step 4): event log, then the
  session list. Two identical failures in a row end the attempt with a report, not a third run.
- **Restarting the infobase server or killing sessions other than through the runner** is left to
  the operator; report what was seen instead.

## Checklist for a new scenario

1. `recall` for project specifics, then write the scenario steps as verifiable
   assertions (`ЗаписатьШаг(<условие>, <что проверено>)`), not as a click list.
2. Write it as `openspec/tests/<capability>/ui/<Scenario>/<Scenario>.bsl` — the entry point
   `&НаКлиенте Процедура ВыполнитьСценарий(Контекст) Экспорт` — and put each server step into
   `server/<Step>.bsl` of the same directory ([docs/test-extension.md](docs/test-extension.md)).
3. Check the scenario body is inside `Попытка/Исключение` — before running anything. Check that
   every procedure the module calls is defined in it or is a platform method confirmed through
   `1C-docs-mcp` (the linter does not report undefined calls). Lint the module (`syntaxcheck` /
   `bsl_check_file`); the compile check against the platform is the builder's `/CheckModules` pass.
4. Run `scripts/run-ui-test.sh`; on a hang or an empty protocol read the event log (step 4) before
   changing anything.
5. Prove the scenario can fail: one run against a deliberately wrong expectation, `[FAIL]` exactly
   on the affected steps, then revert.
6. Record the outcome where the task expects it (manual test plan, `tasks.md`, report in `tmp/`).
