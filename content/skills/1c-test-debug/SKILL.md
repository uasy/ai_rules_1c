---
name: 1c-test-debug
description: "Debugging and verifying behaviour on a 1C test infobase: run BSL and read the event log through a debug extension over HTTP, call HTTP services with credentials from .dev.env, check module compilation with Designer. Use when a task needs facts from a running infobase — server-side checks, runtime errors, HTTP service tests, why a UI scenario produced no protocol."
---

# 1C test and debug tools

Facts about a running test infobase, obtained without a person at the screen: execute code in it,
read its event log, call its HTTP services, check that its modules compile. UI scenarios themselves
are the `1c-ui-testing` skill; this skill is what they, and every other verification, lean on.

**This is not a trivial task.** The tools act on a real infobase through its publication and
Designer. Before relying on them: read this file to the end, check that `.dev.env` has the keys
below, and run `scripts/check-services.py` once — an unpublished service is found in a second, not
halfway through a task.

## What is needed

| Need | Where it comes from |
|---|---|
| `PLATFORM_PATH`, `INFOBASE_KIND`, `IB_USER`, `IB_PASSWORD` | `.dev.env` of the project |
| `INFOBASE_PATH` — the **client's** target: a directory for a file base, a connection string (`localhost:1541\<name>`) for a served one | `.dev.env`; the two layers — skill `1c-ibsrv-ops` |
| `INFOBASE_PUBLISH_URL` — `http://localhost:<port>/<base>` | `.dev.env`; the publication itself and its lifecycle — skill `1c-ibsrv-ops` |
| the debug extension (`Dbg_Executor`, `Dbg_LogReader`) loaded into the infobase | built from the template in `extension/` by `scripts/build-debug-extension.py`, never kept in the project — [docs/debug-extension.md](docs/debug-extension.md) |
| a user with full rights in `IB_USER` | the extension has no role of its own |

The scripts find the project root as the nearest directory above the working directory that holds
`.dev.env`: run them from inside the project.

**No debug extension in the infobase** — both services 404 while the publication names them — is
offered, not fixed: tell the user, and run `build-debug-extension.py --load` only after they agree
and only against a test infobase. `Dbg_Executor` runs any code it receives
([docs/debug-extension.md](docs/debug-extension.md), «Installing into a target infobase»).

## Tools

| Script | What it does |
|---|---|
| `scripts/ib-http.py <METHOD> <path> [--data <json> \| --data-file <file>] [--no-auth] [--user <name> --password-file <file>] [--include]` | any HTTP call to the publication with credentials from `.dev.env`; `--no-auth` checks a refusal; `--user` calls as another infobase user, the password taken from the first line of the file (checks the rights of a role — in a БСП configuration the user must be an element of `Справочник.Пользователи`, otherwise the session start refuses it whatever its roles); `--include` prints the response headers |
| `scripts/ib-http.py --exec <file.bsl>`, `--code "<BSL>"` | runs BSL through `Dbg_Executor`, prints `Результат`; exit 3 — the server closed the connection without an answer (its module crashed on the code: read the infobase event log and the server's own output, do not resend the same code blindly) |
| `scripts/ib-errors.py [<since>] [<count>] [--all]` | error events of the event log: runtime errors (`_$PerformError$_`) first, background job noise hidden |
| `scripts/check-modules.py [<filter>]` | Designer `/CheckModules` for thin client, web client and server on the **loaded** configuration |
| `scripts/check-services.py` | the environment without secrets (publication, infobase kind and path, platform, user), then both debug services published and answering; names the reason when not |
| `scripts/build-debug-extension.py [--load]` | builds the debug extension for this configuration into `tmp/АгентОтладкаHTTP`; `--load` puts it into the test infobase through the standalone server |

**Use `ib-http.py`, not `curl`.** With `curl -u user:password` the password lands on the command
line and in every log of the session; the script takes it from `.dev.env`.

## Server-side checks

A rule whose outcome depends on data or schema state the infobase does not have is checked inside
a transaction that is always rolled back:

```bsl
НачатьТранзакцию();
Попытка
	// create the state: schema rows, duplicates, special value types
	Результат = <проверяемая функция>(...);  // reads the state in the same transaction
Исключение
	Результат = ОписаниеОшибки();
КонецПопытки;
Если ТранзакцияАктивна() Тогда
	ОтменитьТранзакцию();
КонецЕсли;
```

Never "set it and put it back": a failure in the middle leaves the infobase changed. Fingerprints
before and after (`ВерсияДанных` of the touched objects, record counts) prove nothing was left.

Pitfalls of code sent to `Dbg_Executor`:

- Global-context manager names (`Отчеты`, `Справочники`, …) cannot be assigned; `Новый` is a keyword.
- Query aliases cannot be reserved words (`В`, `По`, `Неопределено`).
- A `Соответствие` whose keys are not identifiers breaks the JSON answer — return arrays of
  structures.
- A characteristic type created in a check must have a value type that is a subset of the chart's
  type **with its qualifiers**: `Новый ОписаниеТипов("Число", Метаданные.ПланыВидовХарактеристик.<Имя>.Тип.КвалификаторыЧисла)`;
  a bare `Новый ОписаниеТипов("Число")` fails with «Тип не является подмножеством типа значений
  плана видов характеристик».
- A session from `ПолучитьСеансыИнформационнойБазы()` has `НачалоСеанса`, `ИмяПриложения`,
  `НомерСеанса`, `Пользователь`, `ИмяКомпьютера` — not `ДатаНачала`.
- Reading an attribute through a reference is served from the session cache; after writes made by
  another session read by query.
- A configuration may contain БСП only partially: confirm a library function exists in the sources
  before calling it — neither the linter nor `Выполнить()` checks that in advance.

## Diagnosing a run that produced nothing

In this order, and before repeating anything:

1. **The runner's own output** — `1c-ui-testing` runners stop a hung run and name why.
2. **`ib-errors.py <minutes>`** — a module that does not compile, an unhandled error before a
   scenario started, a failed server call: all are `_$PerformError$_` with text and line.
3. **Sessions** — `ib-http.py --exec` with `ПолучитьСеансыИнформационнойБазы()`: a leftover web
   client or test client session blocks a file infobase.
4. **`check-modules.py <object>`** after loading changed modules — undefined methods and methods
   unavailable in a client, which neither the linter nor the load reports.
5. **[docs/troubleshooting.md](docs/troubleshooting.md)** — an extension that loads and does
   nothing, a security prompt nobody can answer, a request that dies without an answer. Symptoms of
   the server that publishes the base — `1c-ibsrv-ops/docs/troubleshooting.md`.

An environment the tools cannot fix — the server not running, the screen locked, the infobase held
by a foreign process — is reported to the operator, not worked around.

## Related

- `1c-ui-testing` — UI scenarios; its runner uses `ib-errors.py` of this skill for diagnostics.
- `1c-ibsrv-ops` — the standalone server that publishes this infobase: setup, lifecycle, sessions.
- `1c-metadata-manage` — loading configuration and extensions (`db-ops`), creating the debug
  extension (`cfe-manage`, `meta-compile`).
