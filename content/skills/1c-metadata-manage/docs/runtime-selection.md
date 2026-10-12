# Runtime selection — Windows / Linux / macOS

## In this package

This package ships more Python entry points than the upstream text below assumes: its tiers below replace the "Nine commands" table and the "every other tool … none" row. The rules after the table still apply.

Each tool of this skill ships as a PowerShell script (`*.ps1`) and a **Python entry point** (`*.py`) next to it (one exception: `1c-db-ops/scripts/db-check.py` is Python only) — same directory, same file name, same PowerShell-style `-Param` spelling (`-ObjectPath`, `-OutputDir`, `-Force`, `-NoValidate`), so a documented command line ports by swapping `powershell.exe -File …ps1` for `python3 …py`. One shell caveat: a value that itself starts with `-` must be passed as `-Flag=value`.

The `.py` files do **not** all carry the same guarantees, and the difference matters when a run misbehaves:

| Tier | Files | What it means |
|---|---|---|
| **Parity-tested** | `1c-form-scaffold/scripts/form-add.py`, `remove-form.py`, `1c-form-compile/scripts/form-compile.py`, `1c-meta-edit/scripts/meta-edit.py`, `1c-meta-validate/scripts/meta-validate.py` (plus the shared helper `tools/_common/dev_env.py`) | Locally hardened ports. `tools/tests/python-ports-regression.py` runs both runtimes and compares results; CI runs the Python suite on Linux without a PowerShell host. Identical output, exit codes and support-guard semantics (`SUPPORT_GUARD` in `.dev.env`). |
| **Vendored** | every other `*.py` under `tools/` outside `1c-web-ops` (`cf-*`, `cfe-*`, `db-*`, `skd-*`, `mxl-*`, `xdto-*`, …) — except `1c-template-manage/scripts/remove-template.py`, which carries the local `-DryRun` / `-Force` gate and is pinned by the Python suite ([NOTICE.md](../NOTICE.md)); the XML writers named above also carry the local line-ending fix, and `1c-template-manage/scripts/add-template.py` accepts an object XML path in `-ObjectName` | Maintained in this repository alongside their `.ps1` peers (attribution and local deltas: [`NOTICE.md`](../NOTICE.md)). Usable, but **not covered by the parity tests** — treat a divergence from the `.ps1` as a bug in the port, and verify the result before loading it into a base. |
| **Web, own implementation** | `1c-web-ops/scripts/web-publish.py`, `web-info.py`, `web-stop.py`, `web-unpublish.py` (shared `web_common.py`) | Not ports of the `.ps1`: a preinstalled standalone Apache (no download; a distribution config that uses `Include` is refused), loopback-only listener, only the Apache process these scripts started is stopped. Differences from the `.ps1` and prerequisites — [web-manage.md](web-manage.md). `tools/tests/web-python-regression.py` checks them with isolated fixtures and mocked processes, not against a live Apache / 1C. |
| **Not ported** | The `-Check` / `-Actualize` resync modes of `1c-cfe-manage/scripts/cfe-patch-method.py` (generation is ported; the resync path exits with a notice) | No `.py` peer to call. Use the `.ps1` on Windows. The `_common` / `_shared` helpers carry Python peers where a peer makes sense (`dev_env.py`, `meta_dsl.py`, `platform_args.py`, `support_guard.py`, `MetadataAddress.py`, `Invoke-1CEdit.py`; `xml_eol.py` is Python-only and has no PowerShell counterpart). |

Rules:

- **Windows** — run the `.ps1` (`powershell -NoProfile -File <script> …`). This is the reference runtime; the PowerShell scripts are the complete toolchain.
- **Linux / macOS** — run the `.py` with `python3`. Requirements: Python 3.8+ and `lxml` (`python3 -m pip install lxml`); no other third-party package is used. The web scripts need only the standard library, but a compatible Apache and the 1C web extension must already be installed. Installing `pwsh` makes the `.ps1` files launchable there, but the availability of a PowerShell host does not guarantee that a Windows-specific tool works on Linux or macOS: anything that relies on COM, platform binaries, or Windows paths and encodings can still fail under `pwsh`. Respect the platform requirements of the individual tool instead of assuming a blanket cross-platform guarantee.
- **Prefer the runtime that matches the host, and do not mix runners inside one multi-step operation.**
- **Do not replace a port with an outside copy.** The parity-tested five, `1c-template-manage/scripts/remove-template.py` and the XML writers carry local fixes (safety gates, line endings) that a wholesale copy would silently drop. Where a port knowingly diverges from its `.ps1`, the deviation is listed in that file's header.

## Upstream baseline

Each tool of this skill ships as a PowerShell script (`*.ps1`). Some tools additionally ship a **Python entry point** (`*.py`) next to it, with the same parameter names and the same contract:

**Nine commands have a Python entry point today.** These are the only shipped Python commands; `tools/_common/dev_env.py` and `tools/1c-web-ops/scripts/web_common.py` are shared helpers. No tool outside this table may be assumed to work on Linux.

| Tool directory | PowerShell | Python | Notes |
|---|---|---|---|
| `1c-form-scaffold/scripts/` | `form-add.ps1` | `form-add.py` | creates a managed form (scalar registration + descriptor + `Ext/Form.xml` + module) |
| `1c-form-scaffold/scripts/` | `remove-form.ps1` | `remove-form.py` | `-DryRun` first, a real deletion needs `-Force` |
| `1c-form-compile/scripts/` | `form-compile.ps1` | `form-compile.py` | form DSL → `Form.xml` |
| `1c-meta-edit/scripts/` | `meta-edit.ps1` | `meta-edit.py` | `add-form` is refused in both runtimes — use `form-add` |
| `1c-meta-validate/scripts/` | `meta-validate.ps1` | `meta-validate.py` | also the mandatory post-edit check `meta-edit` runs |
| `1c-web-ops/scripts/` | `web-publish.ps1` | `web-publish.py` | local Apache publication; Python requires a preinstalled compatible Apache and 1C web extension |
| `1c-web-ops/scripts/` | `web-info.ps1` | `web-info.py` | publication and managed-process status |
| `1c-web-ops/scripts/` | `web-stop.ps1` | `web-stop.py` | stops only a verified Python-managed Apache process |
| `1c-web-ops/scripts/` | `web-unpublish.ps1` | `web-unpublish.py` | `-DryRun` first, `-Force` for removal; scoped publications only |
| **every other tool under `tools/`** | `*.ps1` | **none** | **not ported** — needs Windows or `pwsh`; there is no `.py` peer to call |

Rules:

- **Windows** — run the `.ps1` (`powershell -NoProfile -File <script> …`). This is the reference runtime; the PowerShell scripts are the complete toolchain.
- **Linux / macOS** — run the available `.py` with `python3`, using the documented switches. The five metadata ports need `lxml`; the four web ports use the standard library but require compatible external Apache/1C binaries. Their operational differences and prerequisites are in [web-manage.md](web-manage.md). A Python entry point is not a claim that the platform web extension works on every OS. Installing `pwsh` likewise does not make Windows-specific PowerShell code portable.
- `tools/tests/python-ports-regression.py` checks the metadata ports' parity, command inventory and installer packaging. `tools/tests/web-python-regression.py` checks web operations with isolated fixtures and mocked process calls; it does not certify a live Apache/1C deployment. CI runs both Python suites on Windows and Linux.

**Upstream ships Python variants of commands that this package does not.** They live in `Nikolay-Shirokov/cc-1c-skills` at the pinned commit `ecd289fe11733028d87b55284ea9fb5feff8f513` — immutable tree: <https://github.com/Nikolay-Shirokov/cc-1c-skills/tree/ecd289fe11733028d87b55284ea9fb5feff8f513/.claude/skills> (for example the `cf-*`, `cfe-*` and `db-*` skills); attribution and local deltas: [`NOTICE.md`](../NOTICE.md). Those files are **not installed and not managed by this package's manifest**, and **not covered by our parity tests or by the local hardening** the shipped entry points above went through. They are therefore not a claim of full Linux / macOS support: do not install them automatically, and do not copy them over the patched `.py` scripts here, which carry local fixes and would be silently overwritten. If you use one, take it from upstream deliberately, keep it outside the installed skill tree, and follow the platform instructions upstream gives for that specific tool. Their existence never makes hand-editing metadata XML acceptable.

**A missing runtime does not unlock hand-editing.** When a task needs a tool that has no Python entry point yet and no PowerShell host is available, that is a blocked task, not an exception to the Hard rule above — say so in one line and stop, or install `pwsh`. Silently hand-writing metadata XML because "the script would not run here" is the same defect as hand-editing with the tool available.
