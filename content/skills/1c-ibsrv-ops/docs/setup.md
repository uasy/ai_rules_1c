# Creating the infobase and the server configuration

The layers and the day-to-day order are in the skill file; this document is what you do once per
environment.

Requirements: the platform installed (`ibsrv` and `ibcmd` next to `1cv8`), a directory for the
infobase, and a free TCP port.

## Create

```bash
D=$IBSRV_DIR                           # the infobase directory; the server keeps its files there
ibcmd server config init --out=$D/server.yml --db-path=$D --name=<base> \
  --http-address=localhost --http-port=8314 --http-base=/<base> \
  --schedule-jobs=deny --id=$(python3 -c 'import uuid;print(uuid.uuid4())')

ibcmd infobase create --config=$D/server.yml --data=$D/data --create-database --locale=ru_RU \
  [--restore=<dump>.dt]               # or --load=<config>.cf
```

- **`--locale` is not optional** for a Russian configuration. Without it the base takes the locale
  of the shell, and every login is refused with «Национальные настройки информационной базы не
  соответствуют настройкам базы данных».
- `--id=auto` is rejected (`value != kUUIDNull`) — pass a generated UUID.
- `--schedule-jobs=deny` keeps scheduled jobs out of a test environment.

## Publish the services of the debug extension

Services of a **configuration extension** are published only when the publication block names
them. `http` in `server.yml` is a list of publications:

```yaml
http:
  - base: /<base>
    http-services:
      publish-by-default: true
      publish-extensions-by-default: true
      service:
        - name: Dbg_Executor
          root: dbg_executor
          publish: true
        - name: Dbg_LogReader
          root: dbg_logreader
          publish: true
```

Without the `service` list such a request fails with 503; with names that match nothing it is 404
(`docs/troubleshooting.md`). An unknown key in the file is accepted silently.

## `INFOBASE_PUBLISH_URL` for this server

The setting is shared: browser UI tests read it, the `1c-data-mcp` server is configured from it by
the installer, and the scripts of `1c-test-debug` append `/hs/<service>` to it. Its shape here is
not the one an IIS or Apache publication has:

| | Web server (IIS / Apache) | Standalone server |
|---|---|---|
| what forms the address | the site's port and the alias of the publication directory | `http-port` and `http-base` of `server.yml` |
| locale segment (`/ru`, `/en`) | often present in the published address | never — there is no such segment to publish under |
| where anonymous access is configured | `<usr name="…" pwd=""/>` of `default.vrd` | the publication block of `server.yml`; not verified by this skill |
| after changing the publication | restart the web server | `ibsrv.py restart` |

Consequences worth knowing:

- Write the value without a trailing `/` and without a locale segment —
  `http://localhost:8314/<base>`. The scripts strip a trailing slash, nothing more.
- `1c-data-mcp` sends no `Authorization` header: it needs the service reachable anonymously. A
  standalone server with users answers 401, so that server's tools stay unavailable until anonymous
  access is arranged. The `default.vrd` recipe from the `.dev.env` comment does not apply here —
  there is no `default.vrd`.
- Changing the value changes what the installer writes into the MCP config on its next run
  (`<value>/hs/mcp`).

## Load configuration and extensions

A running server holds the data directory exclusively, so loading goes **through** it:

```bash
python3 <skills>/1c-ibsrv-ops/scripts/ibcmd-run.py infobase config import --extension=<Name> <dir>
python3 <skills>/1c-ibsrv-ops/scripts/ibcmd-run.py infobase config apply --extension=<Name> --force \
        --dynamic=disable --session-terminate=force \
        --session-terminate-message="обновление тестовой базы"
```

Web sessions cache metadata: restart the server after loading (`ibsrv.py restart`).

**Why the wrapper and not `ibcmd` itself.** Written by hand, that command fails in two ways that
look like nothing at all. An infobase **with users** answers «Для выполнения операции требуется
аутентификация» and then waits on the terminal for a name nobody types: an `import` stays silent
until it is killed, an `apply` fills its log with repeated prompts. And
`--pid=$(pgrep -x ibsrv)` substitutes two pids as soon as a second server runs, a manager base
for instance. `ibcmd-run.py` takes the pid from the data directory of `IBSRV_DIR`, answers the
prompts from `.dev.env` (never on a command line), kills a run that outlives its `--timeout`
(default 1800 s) and returns the exit code of the utility. With the server stopped the same
wrapper works offline: `ibcmd-run.py --offline …` puts `--config`/`--data` in place of `--pid`.

**Why those two flags.** `--dynamic=disable` forbids a dynamic update, so the new metadata takes
effect for everyone instead of only for sessions started later; `--session-terminate=force` then
takes the exclusive lock the update needs by closing the sessions that stand in its way — which is
also what clears the leftovers that hold licenses. Defaults are the opposite (`auto` and
`disable`), and with them an update over a base with live sessions silently degrades to a dynamic
one or refuses the lock.

**Read the output, not only the code.** An update that has to restructure data takes minutes; an
update waiting for a lock waits until the wrapper's timeout kills it. Both end in a printed
diagnostic — a `[INFO ] … успешно завершено` line is what confirms the work, an exit code of 0
alone does not.

## Update the data after the configuration

`config apply` updates the **database structure**; the configuration's own data update — БСП
handlers, filling new attributes, deferred processing — is a separate step that only happens
inside a session. With `schedule-jobs: deny` the background job БСП would normally use never
starts, so nothing runs until it is asked for explicitly.

Ask for it once, after the restart, through the debug extension (`1c-test-debug`):

```bash
python3 <skills>/1c-test-debug/scripts/ib-http.py --timeout 1800 \
  --code 'Результат = ОбновлениеИнформационнойБазы.ВыполнитьОбновлениеИнформационнойБазы(Истина);'
```

`Истина` is «выполнить отложенные обработчики»: they run inside the same call instead of waiting
for a job that will not start, so no second call is needed for the deferred ones.

**Matching versions are not proof that the update is done.** The data version is written before the
deferred handlers run, so read the register:

```bsl
ВЫБРАТЬ ИмяОбработчика, Статус ИЗ РегистрСведений.ОбработчикиОбновления
```

Everything «Выполнен» is the end of the update. Anything else — «Не выполнялся», «Ошибка» — means
the base is mid-update, and **no test run may start**: the first session to arrive will try to
finish the update and collide with whatever else is running («Ошибка разделенного доступа»).

**A base without the debug extension** cannot be asked this way. Load the extension first
(`config import --extension` + `apply`, above), or, when that is not wanted, let a client do it:
`1cv8c … /CЗапуститьОбновлениеИнформационнойБазы` runs the same update in a started session.

## When the update hangs or fails

The order below is the same one the ruleset's `/update1cbase` prescribes for Designer, adapted to
a running standalone server. The budget is the same too: **three full attempts**, then stop and
report.

1. **Read the output, not the exit code.** `ibcmd` prints its diagnostics to stdout; a line about
   metadata or the database structure means a failed attempt even when the process exits 0.
2. **Find what holds the lock** — `ibsrv.py status` lists sessions by application and the locks.
   A client on a modal dialog is the usual answer: `--session-terminate=force` closes ordinary
   sessions, but a Designer session is not one of them.
3. **Kill the utility, not the server.** A stuck `ibcmd` is a separate process (`pgrep -x ibcmd`);
   killing it leaves the server alive. Never kill the server to end an `apply` — an interrupted
   update is what the next step is about. The killed utility leaves its own session behind, listed
   as `Designer` and holding «Конфигуратор(<база>)»: the next `import` fails on that lock until
   `ib-sessions.py auto terminate-all` clears it.
4. **Recover an interrupted update.** With the server stopped (`ibsrv.py stop`, the command is not
   available through `--pid`):

   ```bash
   python3 <skills>/1c-ibsrv-ops/scripts/ibcmd-run.py --offline infobase config repair --rollback
   python3 <skills>/1c-ibsrv-ops/scripts/ibcmd-run.py --offline infobase config repair --fix-metadata
   ```

   `--rollback` discards the unfinished operation, `--commit` finishes it, `--fix-metadata`
   repairs the metadata structure. Start with `--rollback` unless the log says the change was
   already applied to the database.
5. **Fix the cause before retrying.** Re-running the same command against unchanged sources is
   forbidden: an error in the XML is fixed in the sources, a lock error is fixed by closing the
   session, a parameter error in the command line.
6. **The last resort is the dump.** A base that does not repair is recreated from its `.dt`
   (`infobase create --restore=…`) — for a test environment that is a routine step, not a defect.

## Several instances on one machine

Each instance needs its own data directory, its own HTTP port **and its own direct-gate port**:

```bash
ibsrv --config=... --data=... --direct-regport=1641 --direct-range=1660:1691
```

Without a separate gate port the second instance either fails to start (`Address already in use`)
or every `/S localhost/<name>` connection lands on the instance that holds port 1541 — regardless
of the infobase name in the connection string. Over HTTP (`/WS http://localhost:<port>/<base>`) the
address is unambiguous.

## Check

`python3 <skills>/1c-test-debug/scripts/check-services.py` — the environment and both debug services at 200.
Typical answers:

| Answer | Meaning |
|---|---|
| server does not answer | `ibsrv` not running, wrong port in `INFOBASE_PUBLISH_URL` |
| 404 with authentication | the service is not in the publication block, or the extension is not applied (event log) |
| 503 | the service is found but its session cannot be created — publication block without the `service` list |
| 403 | the user of `.dev.env` lacks rights to the service |
| 200 | ready |

The server's own stdout says why it did not start; the infobase event log
(`<data>/log-data/*.lgp`, readable as plain text) says why an extension was not applied.
