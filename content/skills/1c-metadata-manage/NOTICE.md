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

**Hardened Python entry points — six, all vendored from the pinned commit above.**
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
  (upstream spells the key `OnEndEdit`, so the auto-name fell through).
- `tools/1c-form-scaffold/scripts/form-add.py` — Python runtime of `form-add`,
  the managed-form scaffolder. Downstream deltas: `.dev.env` support guard via
  `tools/_common/dev_env.py`, and XML escaping of the user-supplied `-FormName` /
  `-Synonym` in the generated descriptor (upstream interpolates them verbatim, so
  an ordinary `A & B` produced a descriptor no parser accepts).
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
  name it declares must be the name that was registered (6d).
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

This notice also covers `scripts/overlay-grid.py` of the `img-grid-analysis`
skill, which is derived from the same project.

All of them are pinned by `tools/tests/python-ports-regression.py` (an LF and a
CRLF run per tool). The pin above is not to be advanced without re-running
`tools/tests/python-ports-regression.py` and re-recording the deltas here.

- the PowerShell tool scripts under `tools/` synced from the same upstream
  (per-tool versions and local changes: `docs/*.md`, section "Upstream sync").

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
