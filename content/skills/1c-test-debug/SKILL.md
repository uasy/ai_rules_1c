---
name: 1c-test-debug
description: "Debugging and verifying behaviour on a 1C test infobase: run BSL and read the event log through a debug extension over HTTP, call HTTP services with credentials from .dev.env, check module compilation with Designer, publish the infobase on Linux. Use when a task needs facts from a running infobase — server-side checks, runtime errors, HTTP service tests, why a UI scenario produced no protocol."
---

# 1C test and debug tools

Facts about a running test infobase, obtained without a person at the screen: execute code in it,
read its event log, call its HTTP services, check that its modules compile. UI scenarios themselves
are the `1c-ui-testing` skill; this skill is what they, and every other verification, lean on.

**This is not a trivial task.** The tools act on a real infobase through a web publication and
Designer. Before relying on them: read this file to the end, check that `.dev.env` has the keys
below, and run `scripts/check-services.py` once — an unpublished service is found in a second, not
halfway through a task.

## What is needed

| Need | Where it comes from |
|---|---|
| `PLATFORM_PATH`, `INFOBASE_PATH`, `INFOBASE_KIND`, `IB_USER`, `IB_PASSWORD` | `.dev.env` of the project |
| `INFOBASE_PUBLISH_URL` — `http://localhost:<port>/<publication>` | `.dev.env`; the publication itself — [docs/deploy-linux.md](docs/deploy-linux.md), `1c-web-ops` on Windows |
| the debug extension (`Dbg_Executor`, `Dbg_LogReader`) loaded into the infobase | [docs/debug-extension.md](docs/debug-extension.md) — template in `extension/` |
| a user with full rights in `IB_USER` | the extension has no role of its own |

The scripts find the project root as the nearest directory above the working directory that holds
`.dev.env`: run them from inside the project.

## Tools

| Script | What it does |
|---|---|
| `scripts/ib-http.py <METHOD> <path> [--data <json> \| --data-file <file>] [--no-auth]` | any HTTP call to the publication with credentials from `.dev.env`; `--no-auth` checks a refusal |
| `scripts/ib-http.py --exec <file.bsl>` | runs BSL through `Dbg_Executor`, prints `Результат` |
| `scripts/ib-errors.py [<since>] [<count>] [--all]` | error events of the event log: runtime errors (`_$PerformError$_`) first, background job noise hidden |
| `scripts/check-modules.py [<filter>]` | Designer `/CheckModules` for thin client, web client and server on the **loaded** configuration |
| `scripts/check-services.py` | both debug services published and answering; names the reason when not |

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

An environment the tools cannot fix — web server down, screen locked, infobase locked by a foreign
process — is reported to the operator, not worked around.

## Related

- `1c-ui-testing` — UI scenarios; its runner uses `ib-errors.py` of this skill for diagnostics.
- `1c-metadata-manage` — loading configuration and extensions (`db-ops`), publishing on Windows
  (`web-ops`), creating the debug extension (`cfe-manage`, `meta-compile`).
