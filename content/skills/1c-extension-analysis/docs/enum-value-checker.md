# Enum Value Checker — Do Referenced Enum Values Actually Exist?

Use as a companion pass alongside (not instead of) full code reading — it closes a specific, narrow gap that a `grep`-scale reading pass over a large extension tends to miss: an enum-value literal that parses as valid BSL but names a value the enum does not actually have.

## Why this exists

An interceptor or object module can write a literal `Перечисления.<Enum>.<Value>` (or the string-literal form `ПредопределенноеЗначение("Перечисление.<Enum>.<Value>")`) whose `<Value>` does not actually exist in that enum's declared value list. This parses as perfectly valid BSL and is invisible to `syntaxcheck` — the failure only surfaces at runtime, as a metadata-level error when the code executes. It is easy to miss in a large extension: cross-checking every enum-value literal against the enum's real declared values, object by object, does not scale past a `grep`-speed reading pass, and the literal itself gives no visual hint that anything is wrong.

## What it checks

Two BSL forms that reference an enum value by name:

1. **Manager-style access** — `Перечисления.<Enum>.<Value>` (assignment/comparison, e.g. `Объект.Статус = Перечисления.X.Y`).
2. **String-literal form** — `ПредопределенноеЗначение("Перечисление.<Enum>.<Value>")`.

For every distinct `<Enum>` referenced this way anywhere in the extension's `.bsl` files, the tool resolves the enum's actual declared value list and flags any `<Value>` that is not in it.

## Usage

```bash
python3 skills/1c-extension-analysis/tools/1c-enum-value-checker/scripts/enum-value-checker.py \
    -ExtensionPath <path-to-extension-source-dump> \
    -ConfigPath <path-to-base-config-source-dump>
```

| Parameter | Description | Default |
|---|---|---|
| `ExtensionPath` | Path to the extension source dump (directory containing `Configuration.xml`) | — (required) |
| `ConfigPath` | Path to the base configuration source dump | none — enums that are `Adopted` (typical) cannot be reliably verified without it, see "Adopted enum resolution" below |

## Output

Grouped by `Enum.<Name>`, one line per hit: `[OK]` or `[BROKEN — value does not exist]`, with `file:line`, the access form (`manager`/`predefined`), and the matched source line. A closing summary line gives the total broken-reference count across the whole extension.

## Adopted enum resolution — read before trusting a `[BROKEN]` verdict on a typical enum

**Confirmed pitfall, found while validating this tool against a real extension.** An extension's own copy of an `Adopted` (typical) enum can be a **stale snapshot** — its `<ChildObjects>` may list far fewer values than the base configuration currently declares, even though the enum object itself is marked `Adopted`. Treating the extension's own snapshot as authoritative for such an enum produces false `[BROKEN]` verdicts on code that is actually correct against the live base configuration — the values genuinely exist there, just not in the extension's outdated local copy. This is exactly the class of drift a customer typically worries about across a base-configuration update: an extension's local copy of a typical object silently falling behind the base it was adopted from. See Provenance below for the case that surfaced this.

**Resolution the tool applies:**

- Enum is **own** to the extension (no `ObjectBelonging=Adopted` on the `<Enum>` itself) → the extension's own file is authoritative; there is nothing else to compare against.
- Enum is **Adopted** and `-ConfigPath` is given and has the file → the **base config's copy is used**, not the extension's own snapshot, since the snapshot may be stale. The declared-values line states explicitly that the extension's Adopted snapshot was not used and how many values it had, for transparency.
- Enum is **Adopted** but no usable `-ConfigPath` was given → falls back to the extension's own (possibly stale) snapshot, with an explicit `UNVERIFIED against base config` note in the output. **Do not treat a `[BROKEN]` verdict under this note as conclusive** — re-run with `-ConfigPath` before reporting it as a real defect.

**Always pass `-ConfigPath` when it is available.** Running without it is a degraded mode, not the normal path.

## Known false-positive class already filtered

`Перечисления.<Enum>.<MethodName>(args)` — enums can have their own manager-module export functions (`Enums/<Enum>/Ext/ManagerModule.bsl`), and this syntax calls one of those, not a value literal. Confirmed real example while validating this tool: an enum's manager module exported two functions called exactly this way — excluded via a lookahead that checks the value token is not immediately followed by `(`.

## Known limitations

- **Comment stripping is line-based, not string-literal-aware.** A line is cut at its first `//`; a `//` occurring inside a quoted string literal would truncate the line early. Same accepted trade-off as `reference-finder.py`'s word-bounded search (see its own "Known gaps") — rare in practice, but read the printed source line before concluding.
- **Word-bounded literal search, not a BSL parser.** A match inside a string that merely looks like the pattern would still be reported.
- Only scans `.bsl` files — does not look inside DCS report queries embedded as XML (`Reports/*/Templates/*/Ext/Template.xml`), where an enum-value literal could also appear inside a query's `ГДЕ`/`ВЫБРАТЬ` clause. Cross-check DCS-heavy reports manually, or with `dcs-query-fields-extractor` (see [docs/dcs-query-fields-extractor.md](dcs-query-fields-extractor.md)) as a starting point for reading the query text.

## Relationship to BSL-LS / MCP diagnostics

**Verified no overlap.** A full run of `onec-hbk-bsl-*`'s `bsl_diagnostics(include_unused=true)` against the real file carrying this tool's confirmed bug fired only unrelated diagnostics — none of the BSL Language Server's ~180 public rules address enum-value existence. `1c-syntax-checker-mcp`'s `syntaxcheck` cannot cover this either — it takes a bare code string with no metadata context, so it has no enum declarations to check against. This tool is additive, not a duplicate of any existing MCP check.

## Provenance

Built and validated while auditing a real-world 1C configuration extension. Three distinct real findings from that session shaped this tool, described generically (no specifics identifying the extension are reproduced here, to avoid disclosing details of a third party's codebase):

- **The motivating bug:** an interceptor wrote an enum-value literal into a document field on every write — a value absent from the enum's actual (short) declared value list.
- **The Adopted-snapshot staleness pitfall:** one enum's extension-side copy listed only a fraction of the base configuration's real values; another enum's extension-side copy listed none of the base's much larger real value list.
- **The method-call false positive:** one enum's manager module exported its own functions, called via the same `Перечисления.X.Y(...)` syntax as a value access.
- **The BSL-LS cross-check:** run against the file carrying the motivating bug, `bsl_diagnostics(include_unused=true)` returned only unrelated diagnostics, none addressing the enum-value bug.
