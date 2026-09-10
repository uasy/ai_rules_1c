# Reference Finder — Why Was This Object Adopted?

Use after `1c-cfe-manage` `cfe-diff -Mode A` (see `content/skills/1c-metadata-manage/docs/cfe-manage.md`) has produced the `[BORROWED]`/`[OWN]` overview of an extension. For every `[BORROWED]` object that shows **zero** own attrs/TS/forms and no interceptors — a candidate for the "adopted without changes" bucket — run this tool to find (or rule out) the technical reason it needed to be adopted at all.

## Why this exists

The single most error-prone step in analyzing "why does this extension modify the base configuration" is distinguishing:

- an object whose `<ChildObjects>` is merely **open** because it contains adopted (unchanged) children, from
- an object that genuinely has new/changed children.

`cfe-diff -Mode A` already gets this right (it counts own vs. borrowed children). What it does **not** answer is the next question this skill's workflow always needs: for an object that is adopted with **zero** real content, *why is it in the extension at all* — is there a load-bearing reason, or is it dead weight that can be excluded?

There are exactly two mechanisms that justify adoption of an otherwise-untouched object, plus a third case that makes the question moot:

1. **Composite-type reference (hard platform requirement).** Some *other* object in the extension has an attribute/dimension/resource/tabular-section column whose type includes this object's Ref type (`CatalogRef.X`, `DocumentRef.X`, `EnumRef.X`, …). Without adopting `X`, the extension would not compile. Not applicable to registers (no Ref type exists for them).
2. **Code/query reference (soft, author's choice).** The object's manager-style name (`Справочники.X`), query table name (`Справочник.X`), or metadata lookup (`Метаданные.Справочники.X`) appears inside a `.bsl` module or a report's embedded DCS query (`Reports/*/Templates/*/Ext/Template.xml`) somewhere in the extension. The platform does not strictly require this — the author (or the metadata-management tooling) chose to bring the object along for consistency.
3. **The object has its own Ext content.** If the object has its own module/form/template, its adoption is self-explanatory — this question does not apply to it. Run `cfe-diff -Mode A` for the exact own-attrs/own-TS/own-forms breakdown.

If none of the three holds, the object has **no discoverable justification** for adoption in this extension: flag it as a candidate for exclusion — *"if no reference to a typical object remains, it can also be excluded from the extension"*.

## Usage

```bash
python3 skills/1c-extension-analysis/tools/1c-reference-finder/scripts/reference-finder.py \
    -ExtensionPath <path-to-extension-source-dump> \
    -Object "Catalog.ИмяСправочника;;AccumulationRegister.ИмяРегистра"
```

| Parameter | Description | Default |
|---|---|---|
| `ExtensionPath` | Path to the extension source dump (directory containing `Configuration.xml`) | — (required) |
| `Object` | One or more `Type.Name` entries, `;;`-separated (same convention as `cfe-borrow -Object`) | — (required) |

**Supported types:** `Catalog`, `Document`, `Enum`, `ChartOfCharacteristicTypes`, `ChartOfAccounts`, `ChartOfCalculationTypes`, `BusinessProcess`, `Task`, `ExchangePlan`, `InformationRegister`, `AccumulationRegister`, `AccountingRegister`, `CalculationRegister`, `Report`, `DataProcessor`.

## Output

For each object: `[OWN CONTENT]` (if applicable), `[TYPE REFERENCE]` hits with file:line, `[CODE REFERENCE]` hits with file:line and the matching line text, then a `VERDICT` line — one of:

- `explained — composite-type reference (adoption is structurally required)`
- `explained — code/query reference only (...)`
- `explained — own Ext content (...)`
- `NO REFERENCE FOUND and no own Ext content — candidate for exclusion (...)`

## Known gaps (check manually before excluding an object)

- **Fixed (previously a known gap):** earlier versions missed `Метаданные.Справочники.X` / `Метаданные.Документы.X`-style metadata lookups because the word-boundary regex rejected a match preceded by a dot (the dot in `Метаданные.`). The tool now searches for `Метаданные.<manager>.<name>` as its own literal token — see Provenance for the real-world case that surfaced this.
- Does **not** scan compiled form layouts (`Forms/*/Ext/Form.xml`) for data-path bindings, or `Subsystems`/`Roles` composition lists (`<Item xsi:type="xr:MDObjectRef">Type.Name</Item>`) — an object referenced only from a subsystem's command-interface grouping or a role's rights list would show as "NO REFERENCE FOUND" here even though removing the adoption would break that composition. Cross-check with a plain `grep -r "<Object.Name>"` across `Subsystems/` and `Roles/` before deleting an adoption based solely on this tool's verdict.
- Only searches inside the **extension's own** source tree — a reference living in the base configuration is irrelevant to *why the extension* had to adopt the object, so this is intentional, not a bug.
- Word-bounded literal search, not a BSL parser — a match inside a comment or a string literal that happens to look like `Справочник.X` will still be reported (rare in practice, but read the printed line before concluding).

## Provenance

Built from the methodology developed while auditing a real-world 1C configuration extension, and validated against it — including the `Метаданные.<manager>.<name>` regex fix described in "Known gaps" above. No specifics about that extension are reproduced here, to avoid disclosing details of a third party's codebase; the tool and its checks are fully general regardless.
