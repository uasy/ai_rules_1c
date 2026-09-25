---
name: 1c-ibsrv-ops
description: "The 1C standalone server (ibsrv) as the publication of a test infobase: create the base and the server configuration, publish HTTP services of the configuration and of extensions, start / restart / stop it, see its sessions and locks, terminate leftovers. Use when a task needs a published infobase without an external web server, or when a client cannot reach one."
---

# 1C standalone server operations

`ibsrv` is the platform's own server application: one infobase, its own HTTP endpoint, no external
web server, no root, no site files. It serves everything a publication serves — web client, thin
client over HTTP, OData, HTTP services of the configuration and of its extensions — and it is what
the debugging tools (`1c-test-debug`) and UI runs (`1c-ui-testing`) talk to.

**This is not a trivial task.** A running server holds its database exclusively, keeps a stale lock
file after every stop and can take minutes to disappear. Drive it through the scripts below, not by
hand, and read [docs/troubleshooting.md](docs/troubleshooting.md) when a client does not arrive
where it should.

## Two decisions, and which setting carries each

| Decision | Options | Where it is recorded |
|---|---|---|
| how the infobase is **worked with** | file (`/F`) or server (`/S`, `/WS`) | `INFOBASE_KIND` |
| if server — **who serves it** | this standalone server (has to be started) or a 1C cluster (already running, nothing to start) | `IBSRV_DIR`: the infobase directory a server is raised over; empty = nothing to start |

The addresses and the storage are separate again:

| What | File infobase | Standalone server | Cluster |
|---|---|---|---|
| where a client connects | `/F <INFOBASE_PATH>` | `/S <host>:<gate port>\<name>` or `/WS <INFOBASE_PUBLISH_URL>` | `/S <host>\<ref>` or `/WS …` |
| what `INFOBASE_PATH` holds | the directory of the base | the connection string (`localhost:1541\<name>`) | the connection string |
| where the data lies | that directory | `IBSRV_DIR` — the database, with the server's `server.yml` and `data` next to it | the DBMS |

A settings set that contradicts itself is the most common cause of a lost hour: `INFOBASE_KIND=file`
with a server running over the same directory means every `/F` fails, and a publication URL of a
server nobody started means every check reports «сервер не отвечает».

## Tools

| Script | What it does |
|---|---|
| `scripts/ibsrv.py status` | the state: publication, connection, pid, sessions by application, locks |
| `scripts/ibsrv.py start \| restart \| stop` | lifecycle: waits out a slow stop, falls back to `kill -9`, removes the stale `lock.pid` |
| `scripts/ib-sessions.py <pid \| auto> list \| terminate-all [<app-id>]` | sessions of the server: leftovers of killed clients hold licenses until terminated |
| `scripts/ibcmd-run.py [--timeout <s>] [--offline] <ibcmd arguments>` | any `ibcmd` command against this project's server: finds its pid, answers the credential prompts, kills a run that hangs |

Creating the base and the server configuration, the publication block for extension services and
several instances on one machine — [docs/setup.md](docs/setup.md).

## Order of work

1. **Before anything that uses the infobase** — `ibsrv.py status`. A server that is not running is
   reported to the operator, not started behind their back on a machine that is not yours.
2. **Before a run with clients** — `ib-sessions.py auto list`, and `terminate-all` when leftovers
   are there: their licenses are what the next client is refused.
3. **After loading a configuration or an extension** — `ibsrv.py restart`: sessions cache metadata,
   and then the data update, which `config apply` does not do ([docs/setup.md](docs/setup.md)).
4. **Before Designer, `ibcmd` offline or a `/F` client** — `ibsrv.py stop`: the server holds the
   database exclusively.

Loading a configuration or an extension into a running server goes **through** it:
`ibcmd-run.py infobase config import|apply …` — with `--dynamic=disable
--session-terminate=force`, so the update takes the exclusive lock instead of degrading to a
dynamic one. The same wrapper works offline (`--offline`), with the server stopped. An update that hangs
or breaks off has its own order of recovery — [docs/setup.md](docs/setup.md).

## Related

- `1c-test-debug` — executing BSL and reading the event log through the debug extension published
  by this server; diagnosing a run that produced nothing.
- `1c-ui-testing` — the test client runs in the infobase this server publishes; the test manager
  works in a file base of its own and needs no server at all.
- `1c-metadata-manage` — creating infobases and loading configurations with Designer / `ibcmd`
  (`db-ops`), for everything that is not about the running server.
