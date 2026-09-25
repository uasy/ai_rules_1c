# Debug extension — `Dbg_Executor` and `Dbg_LogReader`

A configuration extension with two HTTP services that let an agent run BSL in a test infobase and
read its event log. **A debug tool for a trusted caller on a test infobase only** — `Dbg_Executor`
runs any code it receives. Never install it into a production infobase and never publish it beyond
the local machine.

The extension ships as a template in `extension/`: HTTP service descriptions for the
`1c-metadata-manage` DSL (`*.json`) and their modules (`*.bsl`). The extension itself is created
for each target configuration: its adopted configuration object, language and compatibility mode
belong to that configuration and cannot be copied from another project.

The template is the only source. A project does not keep the extension in its repository: the
build goes to `tmp/АгентОтладкаHTTP`, outside git, and is repeated whenever it is needed. Nor does
the extension belong in `EXTENSION_NAMES` — that list feeds `/build-release` and
`/restore-testbase`, and a debug tool must reach neither a release nor a restored snapshot.

## Contract

### `Dbg_Executor` — run BSL, get the result back

`POST <publication>/hs/dbg_executor/exec/<anything>`, body `{"Код": "<BSL statements>"}`.

- The code runs through `Выполнить()` in the scope of the handler; assign to `Результат` to return
  a value.
- Answer `{"Результат": <JSON value>}`: `ТаблицаЗначений` → array of row objects; `Структура`,
  `Соответствие` → object; references, objects and metadata → their `Строка(...)`; nothing assigned →
  `null`.
- 200 — executed (also when nothing is assigned); 400 — body is not JSON or has no `Код`;
  500 — compile or runtime error in the code, with its text.

From a project: `python3 <skill>/scripts/ib-http.py --exec <file.bsl>` prints `Результат`.

### `Dbg_LogReader` — the event log as JSON

`POST <publication>/hs/dbg_logreader/read/<anything>`, body — a filter, all fields optional:
`ДатаНачала` / `ДатаОкончания` (XML date-time), `Уровень` (`"Информация"`, `"Ошибка"`,
`"Предупреждение"`, `"Примечание"`; string or array), `Событие`, `Пользователь`, `Метаданные`
(string or array), `КоличествоСобытий` (default 100, at most 5000). `{}` returns the last 100 events.

- Answer `{"Количество": N, "События": [...]}`; an event carries `Дата, Уровень, Пользователь,
  Компьютер, ИмяПриложения, Событие, Комментарий, Метаданные, Данные, Транзакция,
  СтатусТранзакции, Сеанс, Соединение`.
- 400 — bad filter (invalid date, `ДатаНачала` later than `ДатаОкончания`, unknown `Уровень`);
  500 — platform error.

From a project: `python3 <skill>/scripts/ib-errors.py` reads the errors.

### Rights

The extension has **no role**. Both services require a user with full rights of the main
configuration (`ПолныеПрава` or equivalent): through them the platform grants the HTTP services of
the extension and the event-log right.

An extension role does not replace them. A user who has only an extension role granting
`EventLog` on the adopted configuration gets **403** «Недостаточно прав для использования ресурса с
данным HTTP методом» on both services, and `ПравоДоступа("ЖурналРегистрации", Метаданные, <роль>)`
returns `Ложь` for that role. Such a role only ties the extension to the name of the configuration,
so the extension is created without one.

## Installing into a target infobase

**Offer, do not install.** When `check-services.py` answers 404 on both services and the
publication does name them, the extension is missing. Say so, name what it gives and what it
costs — arbitrary code execution in that infobase — and install only after the user agrees, and
only into a test infobase. Build without loading needs no consent: it touches nothing but `tmp/`.

```bash
python3 <skill>/scripts/build-debug-extension.py            # build into tmp/АгентОтладкаHTTP
python3 <skill>/scripts/build-debug-extension.py --load     # build and load, after consent
python3 <skill>/scripts/check-services.py                   # both services 200
```

Run from the project root; `<skill>` is this skill's directory. `--config` points at the main
configuration sources when they are neither `EXPORT_PATH` of `.dev.env` nor `src`; `--out` changes
the build directory. The build directory is regenerated whole on every run; the script refuses a
directory that holds anything but an earlier build.

What the build does, in case a step fails:

1. **Scaffold without a role** — `cfe-init` of `1c-metadata-manage` with `-ConfigPath`. From the
   main configuration it takes the identifier of the adopted language, `CompatibilityMode` and
   `InterfaceCompatibilityMode`. Without them the platform refuses the load: «Значение
   контролируемого свойства РежимСовместимостиИнтерфейса … не совпадает» and
   «… ОбъектРасширяемойКонфигурации у объекта Язык.Русский не совпадает».
2. **HTTP services** — `meta-compile` from `extension/*.json`, modules copied from
   `extension/*.bsl`. `meta-compile` names a handler «template name + method name»
   (`ВыполнениеВызов`, `ЧтениеВызов`); the script checks that every `<Handler>` is a function of
   its module, because a mismatch loads silently and fails every request.
3. **Validate** — `cfe-validate`.

`--load` works through the standalone server of `1c-ibsrv-ops` (`IBSRV_DIR`): `config import`,
safe mode off, `config apply --dynamic=disable --session-terminate=force`. Safe mode is turned off
because code of a safe-mode extension is denied privileged operations — files, external components
and the like — and `Dbg_Executor` must run what a check needs. The apply closes live sessions of
the test infobase; the services answer right after it, without a server restart.

**Without a standalone server** the script builds and stops. Load the build yourself:
`db-load-xml.py … -ConfigDir tmp/АгентОтладкаHTTP -Extension АгентОтладкаHTTP -Mode Full -UpdateDB`
of `1c-metadata-manage` (read the whole log), then turn safe mode off —
`ibcmd infobase config extension update --name=АгентОтладкаHTTP --safe-mode=no` with the infobase
addressing of that tool. This path is not covered by the script and has not been run.

**Publication.** The services answer only when the publication names them —
`1c-ibsrv-ops/docs/setup.md`, section «Publish the services of the debug extension». A 404 after a
successful load points there.

**Removal** — `ibcmd-run.py infobase config extension delete --name=АгентОтладкаHTTP` of
`1c-ibsrv-ops`. Nothing in the project depends on the extension, so removing it leaves no trace.
