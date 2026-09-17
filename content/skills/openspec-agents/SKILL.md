---
name: openspec-agents
description: "Delegating an OpenSpec change to agents: openspec-tester writes tests from the spec and verifies, openspec-implementer implements tasks.md; review.md / test-plan.md / verify.md artifacts; running an agent non-interactively with claude -p (permissions, session protocol, log, resume). Use when a change is to be implemented or verified by agents rather than in the main session."
---

# OpenSpec agents

Two agents take the hands-on part of a change; the main session stays the orchestrator — it writes
the tasks, watches, checks the results and brings decisions to the user.

| Agent | Writes | Never touches |
|---|---|---|
| `openspec-tester` | tests in `openspec/tests/<capability>/`, `test-plan.md`, `verify.md` | product sources, specs, design, git |
| `openspec-implementer` | product sources, `[x]` in `tasks.md` | tests, `test-plan.md`, design, specs, git |

The order of work and the artifacts — [docs/lifecycle.md](docs/lifecycle.md). The agents rely on
the `1c-ui-testing` and `1c-test-debug` skills for anything that runs against the infobase.

## Running an agent

```bash
<skills>/openspec-agents/scripts/run-agent.sh <agent> <task file> [<session id>]
```

The runner drives the Claude Code CLI (`claude -p`) and needs `bash`, GNU coreutils and `python3`.
Other AI clients get the agent definitions and this workflow, but not the runner: there the
orchestrator delegates through its own subagent mechanism.

Run it in the background from the main session and watch the log; resume the same session with a
new task file to deliver defects — the agent keeps its context.

- **Model** — `RUN_AGENT_MODEL`, otherwise `SUBAGENT_MODEL_CODING` of `.dev.env`. A cheaper model than
  the orchestrator's is the point of delegating.
- **Permissions** — non-interactive: whatever the role list does not allow is denied without a
  question and recorded in `permission_denials`. `git` writes, process killing, `curl`/`wget`,
  subagents, wake-ups and monitors are denied for every role; the MCP servers of `.mcp.json` are
  allowed. The lists are a guard rail, not a sandbox: `python3` is allowed, so the boundaries in the
  agent definitions and the session protocol still carry the weight.
- **Session protocol** — [session-protocol.md](session-protocol.md) is appended to the system prompt:
  check tools and MCP, load the skills, write `PREFLIGHT`, wait in the foreground, a denied command
  stays denied. The protocol goes into the system prompt because a skill that is only named in the
  agent definition is not loaded reliably.
- **Log** — `tmp/agents/<agent>-<time>.jsonl`. A `result` event closes every turn; the work is over
  when the process exits.

## Writing the task

- Name the change or the requirements, the task numbers and what is already done.
- State what is **not** the agent's: other tasks, acceptance, commits.
- Put the one or two rules this particular task is most likely to break into the task itself — the
  agent follows concrete task text more reliably than general instructions.
- Say what the environment is: configuration loaded or not, whether the agent loads it.

## Watching and accepting

- Watch for: `PREFLIGHT` before the first edit, runs in the foreground with a time limit, denials,
  repeated runs without a change in between.
- An agent's report is a claim. Re-run the decisive check yourself: build and run the test, load and
  `/CheckModules`, look for leftovers of test data.
- Environment problems the agent cannot fix — a locked screen, a web server down, a stale session —
  are the orchestrator's: fix them and resume the session, stating that the aborted runs do not count.

## Known behaviour of `claude -p`

- There is nobody to answer a permission prompt; a compound shell command is checked part by part
  (`…; echo $?` is denied when `echo` is not allowed).
- The end of a turn while a background task is running may end the process and kill the task — hence
  foreground runs and the denied wake-up and monitor tools.
- Without `--mcp-config` the project MCP servers are not approved in a non-interactive session.
- `--agent` ignores the `skills:` field of the definition; knowledge that must be in context goes
  through the system prompt or the task.
