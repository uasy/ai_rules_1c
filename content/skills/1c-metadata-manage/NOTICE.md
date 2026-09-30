# Third-party notices — `1c-metadata-manage`

This skill vendors tool scripts from a third-party project. The notice below is
reproduced as the licence requires; it applies to the vendored files listed here
and travels with every copy of this skill, including installed ones
(`<tool>/skills/1c-metadata-manage/NOTICE.md`).

## Nikolay-Shirokov/cc-1c-skills

- Upstream: <https://github.com/Nikolay-Shirokov/cc-1c-skills>
- Pinned commit: `ecd289fe11733028d87b55284ea9fb5feff8f513`
- Licence: MIT

Vendored under `tools/`, with local modifications documented in each file's
header and in `docs/`:

**Six hardened metadata Python entry points, all vendored from the pinned commit above.**
Each was taken from that immutable commit, not from a moving `HEAD`, and each
carries its downstream deltas in its own file header:

- `tools/1c-form-scaffold/scripts/remove-form.py` — Python runtime of
  `form-remove`. Downstream deltas: input validation (1C identifiers, no
  traversal / separators / UNC / symlinked targets), the `-DryRun` / `-Force`
  safety gate, path containment anchored at `-SrcDir` (a symlink or junction on
  any component of the chain is refused before the first mutation), a
  transactional mutation path whose quarantine is discarded only after every
  payload is verifiably back or the transaction has committed, and
  byte-preserving `ChildObjects` editing. Upstream base: v1.4.
- `tools/1c-template-manage/scripts/remove-template.py` — Python runtime of
  `template-remove`. Downstream deltas: the same local hardening
  `remove-template.ps1` carries on top of upstream v1.3 — preflight parse (the
  root XML is parsed, planned and rendered before anything is deleted), a
  refusal when the template is not registered in `ChildObjects`, an atomic
  root-XML write through a temporary file, and the `-DryRun` / `-Force` safety
  gate (upstream deletes unconditionally and accepts neither flag). Pinned by
  `tools/tests/python-ports-regression.py`. Upstream base: v1.3.
- `tools/1c-form-compile/scripts/form-compile.py` — Python runtime of
  `form-compile`. Downstream deltas: one event normalizer for all three DSL
  spellings (`events`, `on` + `handlers`, standalone `handlers`), an explicit
  non-zero refusal when two spellings are given at once or an event name is
  unknown, and the corrected `OnEditEnd` → `ПриОкончанииРедактирования` suffix
  (upstream spells the key `OnEndEdit`, so the auto-name fell through);
  from-object document choice forms get `ChoiceMode`, the document item preset
  writes `AutoTime` / `UsePostingMode` / `RepostOnWrite`, `Description` is bound
  only when `DescriptionLength > 0`, form-property enum values are a closed set,
  and a missing `Configuration.xml` is reported instead of assuming 2.17.
- `tools/1c-form-scaffold/scripts/form-add.py` — Python runtime of `form-add`,
  the managed-form scaffolder. Downstream deltas: `.dev.env` support guard via
  `tools/_common/dev_env.py`, and XML escaping of the user-supplied `-FormName` /
  `-Synonym` in the generated descriptor (upstream interpolates them verbatim, so
  an ordinary `A & B` produced a descriptor no parser accepts); `-FormName` must be
  a 1C identifier, and an information register's object form names its
  `RecordManager` main attribute `Запись`.
- `tools/1c-meta-edit/scripts/meta-edit.py` — Python runtime of `meta-edit`.
  Downstream deltas: `add-form` is refused before any mutation and redirected to
  `form-add`, in every key spelling the dispatcher itself accepts and across the
  whole definition; the auto-validator is resolved under the downstream directory name
  (`1c-meta-validate`), its absence is a refusal raised *before* the edit is
  written, `-NoValidate` is the single explicit opt-out, and the validator's
  exit code propagates instead of being discarded.
- `tools/1c-meta-validate/scripts/meta-validate.py` — Python runtime of
  `meta-validate`. Downstream deltas: checks 6a–6d — a `ChildObjects/Form`
  registration must be a scalar reference (6a), it must resolve to
  `Forms/<Name>.xml` on disk (6b), that descriptor must parse as XML (6c), and the
  name it declares must be the name that was registered (6d); versions equal to
  `Configuration.xml` (1e, 6e), required and exactly named GeneratedTypes (2),
  default-form references and roles (6f), `Description` / `Code` bindings (6g, 6h),
  case-insensitive cross-kind name uniqueness (8), information-register forbidden
  properties (12) and export-folder type names (16a).
- `tools/_common/dev_env.py` — not upstream code: the Python peer of the local
  `DevEnv.ps1`, so both runtimes read project parameters from `.dev.env`.
- `tools/_common/MetadataAddress.py` and `tools/_common/Invoke-1CEdit.py` —
  not upstream code: Python peers of the local `MetadataAddress.ps1` /
  `Invoke-1CEdit.ps1`, so logical addressing and the preview wrapper work on a
  Linux / macOS install for every tool that ships a `.py` runtime.

The other `.py` files under `tools/` are maintained in this repository at the
versions of their `.ps1` peers; twenty of them go through the local support guard
(`tools/_shared/support_guard.py`). These also carry the XML-layout fix the
PowerShell writers have:

- `cf-edit.py`, `cfe-borrow.py`, `subsystem-compile.py`, `subsystem-edit.py`,
  `interface-edit.py`, `form-edit.py`, `add-help.py`, `add-template.py` — keep the
  target file's CRLF / LF style when rewriting an existing XML file, and never
  write the indentation they insert as a literal `&#13;` (lxml normalises CRLF
  to LF on parsing and serialises an inserted CR as `&#13;`). Shared helper: `tools/_shared/xml_eol.py`, not upstream code.
  `add-template.py` also accepts the object's XML path in `-ObjectName`, as the
  downstream `add-template.ps1` does.
- `form-compile.py` (above) — registering a compiled form in its object keeps the
  object file's line endings.
- `cf-edit.py`, `interface-edit.py`, `subsystem-compile.py`, `subsystem-edit.py` —
  auto-validation calls the sibling validator. The PowerShell peers look for
  `../../<validator>/scripts/<validator>.ps1`, which does not exist in this layout,
  so their auto-validation is skipped.

This notice also covers `scripts/overlay-grid.py` of the `img-grid-analysis`
skill, which is derived from the same project.

All of them are pinned by `tools/tests/python-ports-regression.py` (an LF and a
CRLF run per tool).

**Four local web ports**, derived from the existing vendored PowerShell
publication layout rather than copied from upstream Python:

- `tools/1c-web-ops/scripts/web-publish.py` — publication creation/update.
- `tools/1c-web-ops/scripts/web-info.py` — publication and process status.
- `tools/1c-web-ops/scripts/web-stop.py` — scoped managed-process shutdown.
- `tools/1c-web-ops/scripts/web-unpublish.py` — preview and guarded removal.
- `tools/1c-web-ops/scripts/web_common.py` — shared local implementation:
  standalone Apache, loopback binding, no downloads, path/ownership checks and
  rollback on failed publication updates. Runtime differences are documented
  in `docs/web-manage.md`; offline checks are in
  `tools/tests/web-python-regression.py` in the ruleset source.
  Local delta, marked `# Local:` in `vrd_content()`: `default.vrd` also sets
  `publishExtensionsByDefault="true"` on `<httpServices>`, so the HTTP services
  of the infobase's extensions are published too; without it they answer 404.
  `web-publish.ps1` has the same gap. Pinned by `tools/tests/web-python-regression.py`.

The pin above is not to be advanced without re-running
`tools/tests/python-ports-regression.py` and re-recording the deltas here.

- the PowerShell tool scripts under `tools/` synced from the same upstream
  (per-tool versions and local changes: `docs/*.md`, section "Upstream sync").

`tools/1c-db-ops/scripts/db-create.py` (upstream v1.10), `db-load-dt.py` (upstream v1.12),
`db-load-xml.py` (upstream v1.19) and `db-update.py` (upstream v1.13) carry a local delta,
listed under `# Local:` in each header; their `.ps1` peers are unchanged. The `ibcmd` branch
also reaches a DBMS infobase without a 1C cluster (`-Dbms` / `-DbServer` / `-DbName` /
`-DbUser` / `-DbPassword`) and takes `-IbcmdDataPath` / `-IbcmdTempPath`; `db-create` adds
`-Locale` (both engines) and `-PageSize` (`1cv8` file infobase); `db-update` adds
`-SessionTerminate` (both engines); `db-load-xml` adds `-SessionTerminate` for its `ibcmd`
`-UpdateDB` step and applies the loaded extension there (`--extension`), not the main
configuration. The shared part is `ibcmd_connection()` in `tools/_common/platform_args.py`.
`db-check.py` is not upstream code and has no `.ps1` peer: the Designer check ladder of
`content/rules/designer-batch-checks.md`.

`tools/1c-cfe-manage/scripts/cfe-diff.py` (upstream v1.0) carries a local delta in Mode A, listed
under `# Local:` in its header; `cfe-diff.ps1` is unchanged. Mode A counts own children of every kind
(a bare-name form / template / subsystem takes its ownership from its own descriptor), prints the
properties marked in `<xr:PropertyState>` with their detail and an adopted subsystem's added
`Content`, diffs each borrowed form against its `<BaseForm>`, resolves types missing from the
type map by scanning the top-level folders, lists `Language`, finds modules under `Ext/`
recursively, under `Commands/` and in the root `Ext/`, and ends with the files no line
interpreted (`[UNCLASSIFIED]`). Mode B is unchanged apart from the module search. Pinned by
`skills/1c-extension-analysis/tests/extension-tools-regression.py`.

`tools/1c-db-ops/scripts/db-run.py` (upstream v1.7) adds three flags its `.ps1` peer does not have,
listed under `Deviation` in its header: `-Out` (startup errors of a batch run are written only there),
`-Wait` (wait for the client and return its exit code) and `-ClientKind thin` (the thin client —
the thick one cannot connect to a standalone server).

### MIT licence text

```
MIT License

Copyright (c) 2025-2026 Nick Shirokov

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

### `1c-uuid-check`

`tools/1c-uuid-check/scripts/uuid-check.ps1` is a port of
`check_uuid_duplicates.py` from <https://github.com/Desko77/claude-code-skills-1c>
(MIT), adapted to the Configurator XML format. The MIT terms above apply to it
under that project's own copyright.
