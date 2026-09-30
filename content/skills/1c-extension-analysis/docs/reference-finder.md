# Reference Finder — Why Was This Object Adopted?

Use after `1c-cfe-manage` `cfe-diff -Mode A` (see `content/skills/1c-metadata-manage/docs/cfe-manage.md`) has produced the `[BORROWED]`/`[OWN]` overview of an extension. For every `[BORROWED]` object that shows **zero** own attrs/TS/forms and no interceptors — a candidate for the "adopted without changes" bucket — run this tool to find (or rule out) the technical reason it needed to be adopted at all.

## Why this exists

The single most error-prone step in analyzing "why does this extension modify the base configuration" is distinguishing:

- an object whose `<ChildObjects>` is merely **open** because it contains adopted (unchanged) children, from
- an object that genuinely has new/changed children.

`cfe-diff -Mode A` already gets this right (it counts own vs. borrowed children). What it does **not** answer is the next question this skill's workflow always needs: for an object that is adopted with **zero** real content, *why is it in the extension at all* — is there a load-bearing reason, or is it dead weight that can be excluded?

Three mechanisms justify adoption of an otherwise-untouched object, plus a fourth case that makes the question moot:

1. **Composite-type reference (hard platform requirement).** Some *other* object in the extension has an attribute/dimension/resource/tabular-section column whose type includes this object's Ref type (`CatalogRef.X`, `DocumentRef.X`, `EnumRef.X`, …). Without adopting `X`, the extension would not compile. Not applicable to registers (no Ref type exists for them).
2. **Code/query reference (soft, author's choice).** The object's manager-style name (`Справочники.X`), query table name (`Справочник.X`), or metadata lookup (`Метаданные.Справочники.X`) appears inside a `.bsl` module or a report's embedded DCS query (`Reports/*/Templates/*/Ext/Template.xml`) somewhere in the extension. The platform does not strictly require this — the author (or the metadata-management tooling) chose to bring the object along for consistency.
3. **Metadata reference (the extension's own composition).** The object's Latin type name (`Catalog.X`, `Document.X.Command.Y`) appears in another object's metadata XML — a subsystem's content, a role's `Rights.xml`, a command interface. Removing the adoption would break that composition.
4. **The object has its own content.** If the object has its own module/form/template, or its descriptor carries a property the platform marks in `<xr:PropertyState>` (the types a defined type gains, a role's rights, a subsystem's command interface) or an adopted subsystem adds `Content`, its adoption is self-explanatory — this question does not apply to it. Run `cfe-diff -Mode A` for the exact breakdown.

If none of the four holds, the object has **no discoverable justification** for adoption in this extension: flag it as a candidate for exclusion — *"if no reference to a typical object remains, it can also be excluded from the extension"*.

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

**Types with a syntax of their own** — no Ref type and no manager collection, so each has its own search tokens: `CommonForm` (`CommonForm.X`; `"ОбщаяФорма.X`, `Метаданные.ОбщиеФормы.X`), `CommonTemplate` (`CommonTemplate.X`; `ПолучитьОбщийМакет("X")`, `"ОбщийМакет.X`, `Метаданные.ОбщиеМакеты.X`), `CommonPicture` (`CommonPicture.X`; `БиблиотекаКартинок.X`, `Метаданные.ОбщиеКартинки.X`), `StyleItem` (`style:X`, `StyleItem.X`; `ЦветаСтиля.X`, `ШрифтыСтиля.X`, `Метаданные.ЭлементыСтиля.X`), `DefinedType` (`cfg:DefinedType.X`; `"ОпределяемыйТип.X`, `Метаданные.ОпределяемыеТипы.X`), `Subsystem` (`Subsystem.X`; `Метаданные.Подсистемы.X`), `Role` (`Role.X`; `Метаданные.Роли.X`, and the role named anywhere inside `РольДоступна("…")` / `РолиДоступны("А, Б")`), `WebService` (`WebService.X`; `Метаданные.WebСервисы.X`), `IntegrationService` (`IntegrationService.X`; `СервисыИнтеграции.X`, `Метаданные.СервисыИнтеграции.X`). The first group is searched in `.xml`, the second in `.bsl`.

## Output

For each object: `[OWN CONTENT]` (if applicable), `[TYPE REFERENCE]` hits with file:line, `[METADATA REFERENCE]` hits with file:line, `[CODE REFERENCE]` hits with file:line and the matching line text, then a `VERDICT` line — one of:

- `explained — composite-type reference (adoption is structurally required)`
- `explained — referenced from the extension's metadata (...)`
- `explained — code/query reference only (...)`
- `explained — own Ext content (...)` (standard types) / `explained — own content (...)` (types with a syntax of their own, where the content can also be a marked property or added subsystem content)
- `NO REFERENCE FOUND and no own Ext content — candidate for exclusion (...)`

## Known gaps (check manually before excluding an object)

- Does **not** resolve data paths in compiled form layouts (`<DataPath>Объект.Реквизит</DataPath>` names an attribute, not an object's type), so an object reached only that way shows as "NO REFERENCE FOUND". Read the forms of the objects that could hold it before deleting an adoption based solely on this tool's verdict.
- Only searches inside the **extension's own** source tree — a reference living in the base configuration is irrelevant to *why the extension* had to adopt the object, so this is intentional, not a bug.
- Word-bounded literal search, not a BSL parser — a match inside a comment or a string literal that happens to look like `Справочник.X` will still be reported (rare in practice, but read the printed line before concluding).

## Provenance

Built from the methodology developed while auditing a real-world 1C configuration extension, and validated against it. No specifics about that extension are reproduced here, to avoid disclosing details of a third party's codebase; the tool and its checks are fully general regardless.
