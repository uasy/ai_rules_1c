# Broken Metadata-Path Checker — Does This Hardcoded Path Actually Exist?

Use to sweep an extension's `.bsl` files for hardcoded metadata-path string literals (`ОткрытьФорму("Документ.X.ФормаСписка", ...)` and similar) that reference an object that does not exist — a class of defect that parses fine as BSL and is invisible to `syntaxcheck`, but fails at runtime with "object not found".

## Why this exists

A navigation command, a print handler, or any code that opens a form by a hardcoded metadata-path string literal is only correct as long as that literal keeps matching a real object name. A rename that touches most call sites but misses one command — or a copy-pasted command whose target string was never updated — leaves a literal that still parses as valid BSL but points at nothing. Running that specific command guarantees a runtime "object not found" error for the user, and nothing short of actually exercising that code path (or reading every literal against the object list by hand) surfaces it beforehand.

## What it checks

Scans every `.bsl` file in the extension for double-quoted string literals matching `"<Type>.<Name>.<Anything>"` — three dot-separated segments, where `<Type>` is one of the query-style Cyrillic metadata keywords (`Справочник`, `Документ`, `Отчет`, `Обработка`, `ПланВидовХарактеристик`, `ПланСчетов`, `ПланВидовРасчета`, `БизнесПроцесс`, `Задача`, `ПланОбмена`, `РегистрСведений`, `РегистрНакопления`, `РегистрБухгалтерии`, `РегистрРасчета`, `Перечисление`, `ЖурналДокументов`, `ОбщаяФорма`). For each hit, checks whether `<Type>.<Name>` resolves to a real object (`<Dir>/<Name>.xml`) in the extension and/or the base configuration.

The third segment (form/list/whatever name) is required syntactically (to specifically target navigation/form-path literals rather than bare two-segment metadata full-name strings used for other purposes) but is **not itself verified** — only `<Type>.<Name>` existence is checked. The bug class this targets is a wrong *object* name, not a wrong form name within a correct object.

## Usage

```bash
python3 skills/1c-extension-analysis/tools/1c-broken-metadata-path-checker/scripts/broken-metadata-path-checker.py \
    -ExtensionPath <path-to-extension-source-dump> \
    -ConfigPath <path-to-base-config-source-dump>
```

| Parameter | Description | Default |
|---|---|---|
| `ExtensionPath` | Path to the extension source dump | — (required) |
| `ConfigPath` | Path to the base configuration source dump | none — without it, any literal not found in the extension is reported `[UNKNOWN]` rather than confirmed `[BROKEN]`, since it might legitimately be a base-config object |

## Output

One line per literal found: `[OK]` (resolved in extension or base config), `[BROKEN]` (not found in either, with `-ConfigPath` given), or `[UNKNOWN]` (not found in the extension, and no `-ConfigPath` was given to check further) — each with `file:line`, the resolved `Тип.Имя`, and the source line. A closing summary line gives total literals checked and the broken/unknown counts.

## Known limitations

- **Line-based, skips fully commented-out lines** (`stripped.startswith("//")`) but does not strip trailing same-line comments the way `enum-value-checker.py` does — a literal appearing only after a trailing `//` on an otherwise-code line would still be reported. Read the printed line before concluding, same accepted trade-off as `reference-finder.py`.
- **Only checks `<Type>.<Name>` existence, not the third segment.** A literal like `"Документ.X.НесуществующаяФорма"` (correct object, wrong form name) is reported `[OK]` — this tool does not open the object's form list. Combine with `inspect_form_layout` / `search_forms` (per `content/rules/tooling-playbooks.md → Form Analysis and Generation`) when the object resolves but the specific form is in doubt.
- **Does not scan `Form.xml`** — a broken path embedded in a form's XML (e.g. a command's navigation target set visually rather than in code) is out of scope; this tool only reads `.bsl`.
- **`ОбщаяФорма` (`CommonForms`) is included** in the recognized keyword list, but common forms are addressed slightly differently in some contexts (`ОбщаяФорма.X` without a third segment, e.g. as a report's form) — such two-segment usages are not matched by this tool's three-segment pattern by design (see "What it checks" above).

## Relationship to BSL-LS / MCP diagnostics

**Verified no overlap.** A full run of `onec-hbk-bsl-*`'s `bsl_diagnostics(include_unused=true)` against the real file carrying this tool's confirmed bug fired only an unrelated `UnusedParameters` and a `BSL-DEAD` "unused function" hit — neither addresses a broken hardcoded metadata path. This tool is additive, not a duplicate of any existing MCP check.

## Provenance

Built and validated while auditing a real-world 1C configuration extension — the motivating bug: a navigation command, visible to the user in a document's navigation panel, opened a form path naming an object that did not exist anywhere in either the extension or the base configuration. A sibling command on the same object correctly referenced the real object name — this looked like an incomplete rename that missed one command. Running the broken command guaranteed a runtime error for the user; a human found it only by reading every command module and mentally checking each hardcoded path against the object list. The BSL-LS cross-check on the command's module returned only unrelated diagnostics, none flagging the broken reference. No specifics identifying the extension are reproduced here, to avoid disclosing details of a third party's codebase.
