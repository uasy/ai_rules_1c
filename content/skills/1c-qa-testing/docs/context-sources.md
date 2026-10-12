# Other MCP servers in a check

QA MCP sees only what the test client shows. Use the other 1C servers wherever they answer a question of the check faster or more reliably, under the same `TOOL_*` policy and `content/rules/mcp-policy.md` (read before the first 1C MCP call):

- **What to open and what it is called** — `content/skills/1c-meta-info/SKILL.md` (graph / code metadata): the object's exact metadata name for `ui_open(kind=, metadata_name=)`, its synonym (the title the client shows), attributes, tabular parts, commands, subsystems.
- **Which form and which elements** — `content/skills/1c-form-inspect/SKILL.md`: the forms of the object, the default form, element names and groups before the first `ui_window_tree`. Form code that substitutes another form (`ОбработкаПолученияФормы`) or changes elements on open is found through `content/skills/1c-code-search/SKILL.md`.
- **Where the effect lands** — `content/skills/1c-impact/SKILL.md`: registers a document writes, subscriptions and handlers a command runs; this tells which data to confirm afterwards.
- **Code behind an error** — after `ui_errors` names a module and line, read that code through `1c-code-search`.
- **Data** — `1c-data-mcp` (`content/skills/1c-live-ib/SKILL.md`), read-only: existing test data to use (an employee, a document number, a catalog item), and the data effect of a step (`qa-testclient.md → Confirming data through 1c-data-mcp`).

Metadata indexes describe the project sources; use them only when they cover the configuration loaded into the tested infobase (the same project, fresh after the change). The live window wins: names from an index are candidates until `ui_window_tree` / `ui_find` shows them.
