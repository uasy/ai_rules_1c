# Troubleshooting the standalone server

Symptoms that cost hours because the tool that fails is never the tool that is wrong. Each entry is
a measured case, not a guess: the check comes first, the fix second.

**Where the truth is.** The server's own stdout says why it refused to start (busy ports, a held
data directory). The infobase event log — `<IBSRV_DIR>/data/log-data/*.lgp` — says what happened
inside it, and it is plain text: `grep` finds the message when no session can be opened at all.
Problems of the infobase itself rather than of the server (an extension that does not apply, a
service that crashes on the code it runs) are in `1c-test-debug/docs/troubleshooting.md`.

## The client connects to the wrong infobase

**Symptom.** `1cv8c /S localhost/<name>` opens a base whose configuration belongs to another
instance; a session appears on the other server, not on the one that owns `<name>`.

**Cause.** TCP connections go to the direct gate, port 1541 by default. Two standalone servers on
one machine cannot both hold it: the second one either fails to start (`Ошибка открытия порта
'1541' шлюза прямого подключения`, `Address already in use`) or runs with the gate disabled — and
every `/S` connection then lands on whichever server holds 1541, regardless of the infobase name.

**Fix.** Give each instance its own gate: `--direct-regport=<port> --direct-range=<lower:upper>`,
and name that port in the connection string — `/S localhost:<port>\<name>`. Over HTTP the address
is unambiguous (`/WS http://localhost:<http port>/<name>`), which is the reason to prefer it. Verify by
sessions, not by the window: `ib-sessions.py <pid> list` on each server.

## The server refuses to start after a stop

**Symptom.** `[FATAL] Ошибка блокировки каталога данных сервера. Рабочий каталог заблокирован
процессом: 0`.

**Cause.** `ibsrv` does not remove `<data>/lock.pid` — not on `kill`, not on `kill -9`. The number
inside belongs to a process that no longer exists, hence `процессом: 0`.

**Fix.** With no `ibsrv` running (`pgrep -x ibsrv`), delete `<data>/lock.pid` and start again.
A stop can also be slow: the process keeps running for minutes after `kill` while the port is
already free, and a start in that window fails with `Ошибка доступа к реестру сервера` — wait for
the process to disappear instead of starting a second one.

## «Лицензия не обнаружена» on a client that worked a minute ago

**Symptom.** A client — plain, test client or test manager alike — opens the licensing wizard
(«Не обнаружена лицензия на запуск сервера»), while the same command line worked before.

**Cause.** Sessions of killed clients stay in the infobase, survive a restart of the standalone
server (they live in `<data>/session-data`) and hold their licenses. After a handful of killed runs
there is nothing left to hand out. A client that exits normally releases its session.

**Fix.** List and terminate the leftovers before a run — `scripts/ib-sessions.py <server pid> list`
and `… terminate-all`. Deleting `<data>/session-data` with the server stopped does the same, less
selectively. Test modes have no special licensing requirement; if a bare client also fails, the
sessions are the cause.

## HTTP service of an extension answers 503 `sessionId != kUUIDNull`

**Cause.** The service is found but its session cannot be created: the standalone server publishes
extension services only when the publication section names them.

**Fix.** In the server's `config.yml`, `http` is a **list** of publications, each with its own
services:

```yaml
http:
  - base: /it-mgmt
    http-services:
      publish-by-default: true
      publish-extensions-by-default: true
      service:
        - name: Dbg_Executor
          root: dbg_executor
          publish: true
```

Without the `service` list the request reaches the service and fails with 503; with a list whose
names match nothing the answer is 404. An unknown key in the file is accepted silently, so a typo
shows up only as one of those two codes.

## «Вход в приложение невозможен» right after the base was created

**Symptom.** Every client — thin or web — is refused before the login form, and the detail line
says «Национальные настройки информационной базы не соответствуют настройкам базы данных».

**Cause.** `ibcmd infobase create` takes the locale of the shell that runs it. A shell under
`LANG=en_US.UTF-8` creates an `en_US` infobase, and a Russian dump restored into it does not match.

**Fix.** Create the base with an explicit locale: `ibcmd infobase create --locale=ru_RU …`.
An existing base is repaired by opening it once in Designer.

## Commands that mislead

- **`ibcmd --pid` comes before the mode:** `ibcmd --pid=<pid> session list`, not
  `ibcmd session --pid=<pid> list` — the wrong order hangs without a message.
- **`session` mode has no `--user` / `--password`:** it asks on a terminal, so a script needs a pty
  (`scripts/ib-sessions.py` does this).
- **`--safe-mode` / `--unsafe-action-protection` are rejected offline** (`--config`/`--data`) and
  accepted against a running server (`--pid`).
- **`ibcmd server config init --id=auto` is rejected** (`value != kUUIDNull`) — pass a real UUID.
- **`pgrep -f` matches the shell that runs it.** A `kill -9 $(pgrep -f …)` whose pattern appears in
  its own command line kills the shell (exit 144). Match the process name (`pgrep -x ibsrv`) and
  select by `/proc/<pid>/cmdline`.
