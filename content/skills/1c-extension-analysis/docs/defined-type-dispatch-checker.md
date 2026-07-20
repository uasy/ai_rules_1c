# Defined-Type Dispatch Checker — Does the Dispatcher Handle Every Member?

Use when an extension has a BSL function that dispatches on `ТипЗнч(Параметр)` against every member of a `ОпределяемыйТип` (a common pattern for RIB registration filters, generic document/catalog handlers, cross-cutting integration code). This tool answers one narrow question: does the dispatch chain actually cover every type currently in the `DefinedType`'s composition?

## Why this exists

A dispatch chain that branches on `ТипЗнч(Параметр) = Тип("...")` for every member of a `DefinedType` is only as complete as the day it was written — if the `DefinedType`'s composition grows later (the base configuration adds a member, or the extension itself adds one), nothing forces the dispatcher to grow with it. A hand-maintained tracking comment listing "handled" vs. "not handled" members is a common mitigation, but it is just as easy to let drift out of sync as the dispatcher itself. If the dispatcher's `Иначе` branch unconditionally raises an exception for anything unrecognized, a member added after the dispatcher was last updated causes a guaranteed runtime crash the moment an object of that type is ever passed through it (e.g. via RIB registration). This is invisible to `syntaxcheck` and to ordinary code reading, since confirming it requires diffing the dispatcher's handled-types list against the `DefinedType`'s actual XML composition, member by member — exactly the kind of cross-check a reading pass at scale tends to skip.

## What it checks

Given a `DefinedType` name and the `.bsl` file (and, ideally, the specific routine) implementing the dispatch:

1. Resolves the DefinedType's actual composition (`<v8:Type>` entries) — see "Adopted DefinedType resolution" below, this is the part that needs care.
2. Converts each composite Ref-type entry (`cfg:CatalogRef.X`, `cfg:DocumentRef.X`, …) into the Cyrillic dispatch-style token BSL code actually compares against (`СправочникСсылка.X`, `ДокументСсылка.X`, …).
3. Searches the scanned scope for `Тип("<token>")` for each — anywhere, not just inside `Если ТипЗнч(...) = Тип(...)`, since the same literal can appear in an `ИЛИ` chain or a lookup table.
4. Reports handled / missing / skipped (non-reference types in the composition, if any), and — if the scope contains an `Иначе ... ВызватьИсключение` pattern — flags missing types as a runtime risk, not just an incompleteness note.

## Usage

```bash
python3 skills/1c-extension-analysis/tools/1c-defined-type-dispatch-checker/scripts/defined-type-dispatch-checker.py \
    -ExtensionPath <path-to-extension-source-dump> \
    -ConfigPath <path-to-base-config-source-dump> \
    -DefinedType <ИмяОпределяемогоТипа> \
    -BslFile <path-to-Ext/Module.bsl> \
    -Function <ИмяФункцииДиспетчера>
```

| Parameter | Description | Default |
|---|---|---|
| `ExtensionPath` | Path to the extension source dump | — (required) |
| `ConfigPath` | Path to the base configuration source dump | none — **strongly recommended**, see below |
| `DefinedType` | Name of the `ОпределяемыйТип` to check composition against | — (required) |
| `BslFile` | Path to the `.bsl` module containing the dispatch code | — (required) |
| `Function` | Name of the specific `Функция`/`Процедура` to scope the search to | none — whole file scanned if omitted (noisier, may pick up unrelated `Тип("...")` calls elsewhere in the module) |

Always pass `-Function` when the dispatcher is one routine among several in the same module — scoping avoids false "handled" matches from an unrelated routine that happens to reference the same type elsewhere in the file.

## Adopted DefinedType resolution — read before trusting a `[MISSING]` verdict

**Same pitfall as `enum-value-checker.py`, confirmed on a real extension.** An extension's own copy of an `Adopted` (typical) `DefinedType` can be a stale snapshot with far fewer `<v8:Type>` entries than the base configuration currently declares. Resolving composition from the extension's own snapshot alone in that case would make this tool useless (it could report "N members, nothing missing" when the true composition is much larger). See Provenance below for the case that surfaced this.

**Resolution the tool applies**, identical in spirit to the enum checker:

- DefinedType is **own** to the extension → the extension's own file is authoritative.
- DefinedType is **Adopted** and `-ConfigPath` has the file → the **base config's copy is used**, ignoring the extension's own (possibly stale) snapshot. The composition line states this explicitly, including how many entries the ignored snapshot had, for transparency.
- DefinedType is **Adopted** with no usable `-ConfigPath` → falls back to the extension's snapshot with an explicit `UNVERIFIED against base config` note — treat any `[MISSING]` result under this note as unverified, not conclusive.

**Always pass `-ConfigPath`.** For an `Adopted` DefinedType, running without it can silently produce a report with zero findings that means nothing at all, rather than "everything is handled".

## Known limitations

- **Line-based routine extraction, not a BSL parser.** `-Function` extraction looks for `^\s*(Функция|Процедура)\s+<name>\s*\(` and the next bare `КонецФункции`/`КонецПроцедуры` line. 1C does not nest routine declarations, so this is unambiguous in practice, but a routine name that is a substring/prefix of another (unlikely given 1C naming conventions) is not specially guarded against beyond the regex's own word-ish anchoring.
- **`Тип("...")` presence is treated as "handled" regardless of surrounding logic.** If the literal appears in a comment, or in code that is itself unreachable (see `dead-code-after-insert-checker`), this tool still counts it as handled. Cross-check with that tool when both are relevant.
- **The `Иначе ... ВызватьИсключение` detector is a bounded-window heuristic** (`Иначе` followed within ~200 characters by `ВызватьИсключение`, allowing intervening comments/blank lines) — not a scope-aware parser. It can occasionally pair an unrelated `Иначе`/`ВызватьИсключение` if they happen to sit within that window in a very dense routine; read the routine before treating the `RISK` line as certain, same spirit as `reference-finder.py`'s own accepted trade-offs.
- **Composite types that are not recognized `*Ref` entries (e.g. primitive types like `xs:string`) are skipped**, not flagged missing — verify those manually if the DefinedType genuinely mixes primitive and reference types.

## Relationship to BSL-LS / MCP diagnostics

**Verified no overlap.** A full run of `onec-hbk-bsl-*`'s `bsl_diagnostics(include_unused=true)` against the real file carrying this tool's confirmed bug produced a number of diagnostics — complexity, duplicated branches, a typo, an unrelated genuine `MissingCommonModuleMethod` — none addressing `DefinedType` composition completeness. This tool is additive, not a duplicate of any existing MCP check.

## Provenance

Built and validated while auditing a real-world 1C configuration extension. No specifics identifying that extension are reproduced here, to avoid disclosing details of a third party's codebase — the findings that shaped this tool, described generically:

- **The motivating bug:** a dispatch function carried a hand-written comment enumerating every member of a large `DefinedType` with `+`/`-` markers ("handled" / "consciously not handled"), but one member was not mentioned in the comment at all and was not handled by any branch. The function's `Иначе` branch unconditionally raised an exception on any unrecognized type, so an object of that type would crash the function the first time it was ever passed in (e.g. via RIB registration).
- **The Adopted-snapshot staleness pitfall:** the extension's own copy of that same `DefinedType` had zero entries in its `Adopted` snapshot, while the base configuration's copy had the real, much larger composition — resolving from the extension's own file alone would have made this tool report "nothing missing" trivially.
- **The BSL-LS cross-check:** run against the file carrying the dispatcher, `bsl_diagnostics(include_unused=true)` returned diagnostics for cognitive/cyclomatic complexity, duplicated `Если`/`ИначеЕсли` blocks, a typo, and one genuine (unrelated) `MissingCommonModuleMethod` error — none flagged the missing-member gap.
