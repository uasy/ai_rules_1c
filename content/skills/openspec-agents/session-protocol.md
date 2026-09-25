# Session protocol (mandatory)

You run non-interactively: nobody answers questions or approves commands, and nobody watches the
screen. These steps come before the task itself and are not optional.

0. **Treat the task as non-trivial.** It runs against a real infobase through project tools you have
   not seen in this session. Before planning, read the project tools section named in your agent
   definition and check that the MCP servers you will rely on answer (one cheap call each, for
   example `bsl_status` of `onec-hbk-bsl`, a `docsearch` of `1C-docs-mcp`). An unavailable server
   is stated in `PREFLIGHT`, not discovered halfway through the task.
1. **Load before you act.** Before the first `Write`, `Edit` or `Bash` call, invoke through the
   `Skill` tool every skill your agent definition names under «Knowledge to load» that applies to the
   task, and `Read` every document named there. Knowing that a skill exists is not loading it.
2. **Show what you loaded.** Then write one message that starts with the line `PREFLIGHT` and lists:
   - the skills invoked and the documents read;
   - the rules and traps from them that apply to what this task will write and run — concrete
     items, not section titles;
   - which MCP servers answered and which did not;
   - how you will diagnose a run or a command that produces no result, before repeating it.
3. **Wait in the foreground.** A command whose result you need runs in the foreground with an
   explicit time limit that fits one tool call (at most 10 minutes). Never end a turn while a
   background task you depend on is still running and never schedule a wake-up: the session may end
   and the task is killed with it.
4. **Credentials stay out of the log.** Do not read or print `.dev.env`, and do not pass `-Password`
   or a password-bearing URL to a command: the scripts of the skills read the connection settings
   themselves, and everything you read or run is written to the session log. The environment you
   need for `PREFLIGHT` — publication URL, infobase kind and path, platform, user — is printed by
   `check-services.py` of `1c-test-debug`.
5. **The machine is the operator's.** Do not change the state of the session or the machine: no
   unlocking or locking the screen, no starting or stopping services, no killing processes. When a
   tool reports an environment problem (a locked screen, an infobase server that does not answer, an
   infobase locked by another session), do what does not depend on it, then stop and name the
   problem in the final report. Repeating a run the environment refused changes nothing.
6. **A denied command stays denied.** Do not reach the same effect with another command (`pkill`
   after a denied `kill`, a script after a denied call): name it in the final report and continue
   with what does not need it.
7. **Only then start the task.** When a later step would break a rule you listed, stop that step and
   say so in the final report instead of working around it.
