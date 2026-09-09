---
name: 1c-metadata-manage
description: "1C metadata management — create, edit, validate, and remove configuration objects (catalogs, documents, registers, enums), managed forms, data composition schemas (SKD), spreadsheet layouts (MXL), roles, external processors (EPF/ERF), extensions (CFE), configurations (CF), databases, subsystems, command interfaces, templates. Use when working with 1C metadata structure."
---

# 1C Metadata Manage — Skill Dispatch

Use this skill when the task involves **1C metadata structure** (creating, editing, validating, or removing configuration objects, forms, reports, layouts, roles, extensions, or databases).

## Hard rule

The gate itself — every metadata-XML mutation and every infobase operation goes through this skill (dispatch below → domain doc → PowerShell tools) or the `1c-metadata-manager` subagent, hand-editing is a defect, repository-bound projects add the `1c-repository-manage` lock / commit discipline, EDT-format trees (`.mdo` / `.form`, never fed to these tools) route per `content/rules/edt-workflow.md` — is owned by `AGENTS.md → Skills and Subagents`; this skill's own canon is only the exceptions:

- **Unambiguous one-line fix** of an existing value that cannot break structure — a synonym / comment typo, a boolean flag flip on an existing element. Anything that adds / removes / reorders elements, touches UUIDs, or spans more than one line of XML is not "one-line".
- **Skill not available in the session** (files not installed / not exposed) — state it once in one line, then hand-edit with `metadata-xml-workarounds.md` loaded and validate per `verification-gates.md → Gate 5`.
- **Read-only analysis** of metadata XML is not a mutation — reading files directly is fine (subject to `mcp-first-search.md` for locating them).

## Vendor support gate

Every mutating tool refuses to edit a locked ("на замке") object of a typical configuration on vendor support and refuses to delete one still on support — the run exits `1`, the refusal is the correct outcome (extension first, `support-edit` only as a stated decision): [support-manage.md](docs/support-manage.md).

## Path conventions

PowerShell examples in this skill (`SKILL.md` and every `docs/*.md`) use the prefix `skills/1c-metadata-manage/tools/...`. That prefix is **relative to the active tool's skills directory**, not to the repository root:

- After installation: the script lives under `<tool>/skills/1c-metadata-manage/tools/...` (e.g. `.cursor/skills/1c-metadata-manage/tools/...`, `.claude/skills/1c-metadata-manage/tools/...`, `.kilo/skills/1c-metadata-manage/tools/...`, `.ai-agent/skills/1c-metadata-manage/tools/...`). Active tools that load this skill resolve the prefix automatically.
- In the `1c-rules` source repository (when editing the skill itself): the same script lives under `content/skills/1c-metadata-manage/tools/...`. Prepend `content/` when running the example outside of an installed project.

The same convention applies to `docs/*.md` references like `skills/1c-metadata-manage/tools/1c-skd-info/modes-reference.md`.

## Runtime selection — Windows / Linux / macOS

Each tool of this skill ships as a PowerShell script (`*.ps1`). Nearly all of them also ship a **Python entry point** (`*.py`) next to it — same directory, same file name, same PowerShell-style `-Param` spelling (`-ObjectPath`, `-OutputDir`, `-Force`, `-NoValidate`), so a documented command line ports by swapping `powershell.exe -File …ps1` for `python3 …py`. One shell caveat: a value that itself starts with `-` must be passed as `-Flag=value`.

The `.py` files do **not** all carry the same guarantees, and the difference matters when a run misbehaves:

| Tier | Files | What it means |
|---|---|---|
| **Parity-tested** | `1c-form-scaffold/scripts/form-add.py`, `remove-form.py`, `1c-form-compile/scripts/form-compile.py`, `1c-meta-edit/scripts/meta-edit.py`, `1c-meta-validate/scripts/meta-validate.py` (plus the shared helper `tools/_common/dev_env.py`) | Locally hardened ports. `tools/tests/python-ports-regression.py` runs both runtimes and compares results; CI runs the Python suite on Linux without a PowerShell host. Identical output, exit codes and support-guard semantics (`SUPPORT_GUARD` in `.dev.env`). |
| **Vendored** | every other `*.py` under `tools/` (`cf-*`, `cfe-*`, `db-*`, `skd-*`, `mxl-*`, `xdto-*`, …) | Taken from `Nikolay-Shirokov/cc-1c-skills` (attribution and local deltas: [`NOTICE.md`](NOTICE.md)). Usable, but **not covered by the parity tests and not locally hardened** — treat a divergence from the `.ps1` as a bug in the port, and verify the result before loading it into a base. |
| **Not ported** | `1c-web-ops/scripts/*.ps1` (IIS / Apache publication — Windows-only by nature), the `_common` / `_shared` PowerShell helpers, and the `-Check` / `-Actualize` resync modes of `1c-cfe-manage/scripts/cfe-patch-method.py` (generation is ported; the resync path exits with a notice) | No `.py` peer to call. Use the `.ps1` on Windows. |

Rules:

- **Windows** — run the `.ps1` (`powershell -NoProfile -File <script> …`). This is the reference runtime; the PowerShell scripts are the complete toolchain.
- **Linux / macOS** — run the `.py` with `python3`. Requirements: Python 3.8+ and `lxml` (`python3 -m pip install lxml`); no other third-party package is used. Installing `pwsh` makes the `.ps1` files launchable there, but the availability of a PowerShell host does not guarantee that a Windows-specific tool works on Linux or macOS: anything that relies on COM, platform binaries, or Windows paths and encodings can still fail under `pwsh`. Respect the platform requirements of the individual tool instead of assuming a blanket cross-platform guarantee.
- **Prefer the runtime that matches the host, and do not mix runners inside one multi-step operation.**
- **Do not overwrite the parity-tested five from upstream.** Upstream `cc-1c-skills` ships its own `.py` for those commands; the copies here carry local fixes and would be silently overwritten. Where a port knowingly diverges from its `.ps1`, the deviation is listed in that file's header.

**A missing runtime does not unlock hand-editing.** When a task needs a tool that has no Python entry point and no PowerShell host is available, that is a blocked task, not an exception to the Hard rule above — say so in one line and stop, or install `pwsh`. Silently hand-writing metadata XML because "the script would not run here" is the same defect as hand-editing with the tool available.

## Preview before apply, and logical addressing

`tools/_common/Invoke-1CEdit.ps1` wraps any tool of this skill and adds three things the vendored scripts do not have: a **logical address** instead of a physical path, a **unified diff** of what the run changed, and a **preview** that runs the real tool and then puts the tree back. Full reference: [edit-preview.md](docs/edit-preview.md).

```powershell
# what would change, shown as a diff, nothing written
powershell -NoProfile -File skills/1c-metadata-manage/tools/_common/Invoke-1CEdit.ps1 `
    -Tool meta-edit -Object Справочник.Контрагенты -Preview `
    -Operation add-attribute -Value '{"name":"ИНН","type":"String","length":12}'

# same call without -Preview applies it
```

- **`-Object <Kind>.<Name>[.Форма|Макет|Права|МодульОбъекта.<Member>]`** resolves to the path the tool expects and is passed as `-Path`. Russian and English kind names both work. This is the same address the MCP servers use for `object_name`, so one task no longer carries two addressing schemes. Unknown kind = a refusal listing the accepted ones, never a path that points at nothing.
- **`-Preview`** (alias `-DryRun`) shows the diff and restores the tree. When the tool has its own `-DryRun` — `meta-remove`, `remove-form`, `remove-template`, `web-unpublish`, `db-load-git` — that native plan is used instead, because nothing gets written that would need undoing.
- **Rollback backends.** A dump under git is watched whole, so a write outside the edited object is still caught and undone; the run **refuses to start** when the watched path already has uncommitted changes, because a rollback would take that work with it. Without git, the object folder, its parent and the root `Configuration.xml` are copied first, and the watched scope is printed — a write outside it is reported as unwatched rather than silently missed.
- Applying without the wrapper stays valid; the wrapper is how a change is **shown** before it lands, which the delivery report can then cite.

## Dispatch Strategy

Determine task complexity, then choose the execution mode:

### Direct execution — simple / read-only tasks

Use when the task is a **single lightweight query**: checking metadata info, a quick lookup, one validation call. In this case identify the task domain from the table below, read the corresponding file, and follow its instructions directly.

### Subagent delegation — complex / mutation tasks

Delegate to the **`1c-metadata-manager`** subagent (defined in `content/agents/metadata-manager.md`, or in the installed agents directory for the active tool) when **any** of the following is true:

- The task **creates, scaffolds, or compiles** metadata (objects, forms, SKD, MXL, roles, EPF, CF, CFE, databases)
- The task **edits multiple files** or **spans multiple domains**
- The task involves a **multi-step workflow** (create → edit → validate → fix → re-validate)
- The task requires **reading large domain docs** (forms, meta-manage, SKD, MXL, roles, EPF, DB — each 200–800 lines)

The subagent already knows how to read the skill docs, execute PowerShell scripts, and validate results. Provide it with the full task description including object names, attributes, types, and any business context from the conversation.

## Task Domain Table

| Task Domain | Keywords | File |
|---|---|---|
| Metadata objects — create, edit, analyze, remove, validate | catalog, document, register, enum, constant, module, attribute, tabular section | [meta-manage.md](docs/meta-manage.md) |
| UUID integrity — duplicate identities in an XML dump | UUID, duplicate uuid, TypeId, ValueId, identity collision, load failure after generation | [uuid-check.md](docs/uuid-check.md) |
| Managed forms — design, create, edit, analyze, validate | form, Form.xml, UI, elements, commands, events | [form-manage.md](docs/form-manage.md) |
| Managed-form layout patterns — archetypes, naming conventions, advanced patterns | form patterns, archetype, layout, naming, ERP form, list form, document form, wizard | fetch `standards(name="form-patterns")` on `1C-docs-mcp` (server not exposed → `content/rules/help-corpus-retrieval.md`) |
| Form-compile DSL reference — full JSON DSL spec for `1c-form-compile`, `--from-object` mode, presets | form DSL, form-compile, autoCmdBar, columnGroup, RadioButtonField, --from-object, form preset | [form-compile-dsl.md](docs/form-compile-dsl.md) |
| Data Composition Schema (DCS/SKD) — create, edit, analyze, decompile, validate | report, DCS, SKD, data composition, data set, query, decompile | [skd-manage.md](docs/skd-manage.md) |
| Spreadsheet documents (MXL) — create, decompile, analyze, validate | MXL, spreadsheet, template, print form, layout | [mxl-manage.md](docs/mxl-manage.md) |
| Roles and access rights — create, analyze, validate | role, rights, RLS, access, permissions | [role-manage.md](docs/role-manage.md) |
| External processors/reports (EPF/ERF) — scaffold, build, dump, validate | EPF, ERF, data processor, external report, build, dump | [epf-manage.md](docs/epf-manage.md) |
| BSP/SSL registration and commands | BSP, SSL, ExternalDataProcessorInfo, registration, command | [bsp-manage.md](docs/bsp-manage.md) |
| Configuration (CF) — create, edit, analyze, validate | configuration, Configuration.xml, CF | [cf-manage.md](docs/cf-manage.md) |
| Extensions (CFE) — create, borrow, diff, patch, validate | extension, CFE, borrow, interceptor, patch | [cfe-manage.md](docs/cfe-manage.md) |
| Vendor support state — "на замке", editability, off-support | support, поддержка, на замке, замок, vendor updates, support-guard, SUPPORT_GUARD | [support-manage.md](docs/support-manage.md) |
| XDTO packages — analyze, create from XSD, export, edit, validate | XDTO, package, XSD, XML schema, ФабрикаXDTO, namespace, exchange format, EnterpriseData | [xdto-manage.md](docs/xdto-manage.md) |
| Databases — create, run, load, dump, DT backup | database, infobase, create DB, run 1C, dt, backup, .v8-project.json | [db-manage.md](docs/db-manage.md) |
| Subsystems — create, edit, analyze, validate | subsystem, command interface, ChildObjects | [subsystem-manage.md](docs/subsystem-manage.md) |
| Command interface — edit, validate | CommandInterface.xml, commands visibility, groups | [interface-manage.md](docs/interface-manage.md) |
| Templates/layouts management — add, remove | template, layout, SpreadsheetDocument, HTML template | [template-manage.md](docs/template-manage.md) |
| Help pages — add, manage | help, built-in help, documentation | [help-manage.md](docs/help-manage.md) |
| SSL/BSP subsystems patterns | SSL patterns, standard subsystems, BSP events | `standards(name="dev-standards-architecture") §4` + `content/skills/mcp-1c-tools/docs/1c-ssl-mcp.md` |
| Query writing — compose new queries from scratch | write query, build query, query template, ВЫБРАТЬ, ИЗ, СОЕДИНЕНИЕ, virtual tables, batch queries | [query-writing.md](docs/query-writing.md) |
| Query optimization | query, temporary table, join, DCS optimization | [query-optimization.md](docs/query-optimization.md) |
| Web publishing — publish, unpublish, status, smoke test | web, publish, Apache, IIS, web client, webdav, default.vrd | [web-manage.md](docs/web-manage.md) |
| Unpack / rebuild CF, CFE, EPF binaries without 1C platform | v8unpack, binary unpack, headless extract, no platform | [v8unpack-cf.md](docs/v8unpack-cf.md) → standalone skill `v8unpack-cf` |

**If the task spans multiple domains**, the subagent will read all relevant docs automatically (or read each one directly for simple tasks).
