# DCS Query Fields Extractor — What Does This Report Actually Read?

Use for step 3 ("group into functional blocks") whenever a wholly-new `Report` or `DataProcessor` has only a Data Composition Schema and no `ObjectModule`/`ManagerModule` code — pulls the query text and the tables/registers it references out of the embedded schema, without requiring a human to open and read the whole `Template.xml` by hand.

## Why this exists

Grouping a wholly-new report into a functional block by **name similarity** with other objects in the extension, without reading what its query actually aggregates, is a real classification mistake — a report can be named after one subsystem while its query reads data belonging to an entirely different one. Since such reports usually carry no BSL at all (SKD-only), the only way to know what they actually do is to read the query text; this tool makes that a one-call, mechanical step instead of requiring the query to be opened and read by hand every time.

## What it checks

Given a `Report`/`DataProcessor` name, finds every `Templates/*/Ext/Template.xml` under it whose root is a `DataCompositionSchema`, and for each `dataSet` inside:

- **`DataSetQuery`** — extracts the query text and scans it for metadata-table references (`Справочник.X`, `Документ.X`, `РегистрНакопления.X`, including virtual-table calls like `.Обороты(...)`/`.Остатки(...)`/`.СрезПоследних(...)`, and the other query-table keywords `reference-finder.py` recognizes).
- **`DataSetUnion`** — lists the names of the sub-`dataSet`s it combines.

## Usage

```bash
python3 skills/1c-extension-analysis/tools/1c-dcs-query-fields-extractor/scripts/dcs-query-fields-extractor.py \
    -ExtensionPath <path-to-extension-source-dump> \
    -Object "Report.ИмяОтчета"
```

| Parameter | Description | Default |
|---|---|---|
| `ExtensionPath` | Path to the extension (or base config) source dump | — (required) |
| `Object` | `"Report.Name"` or `"DataProcessor.Name"` | — (required) |
| `Template` | Restrict to one template directory name | none — all templates with a DCS schema are read |
| `ShowQueryText` | Also print the full query text of each `DataSetQuery`, not just the referenced-tables summary | off |

## Output

Per template, per `dataSet`: its name and type, the deduplicated list of referenced tables/registers for a `DataSetQuery` (or the list of combined dataset names for a `DataSetUnion`), and — with `-ShowQueryText` — the full query text.

## Known limitations

- **Regex-based table extraction, not a query parser.** A query that builds table references dynamically, or names them only through an alias with no literal `Тип.Имя` in sight, will not be picked up. In practice DCS-embedded queries almost always spell out the literal table name, so this is a rare gap.
- **Does not inspect `DataSetObject` or `DataSetUnion` member queries recursively beyond listing their names** — for a union, read each named member dataset's own query separately if a full picture is needed.
- **Existence of the referenced tables is not verified** — this tool answers "what does the query read", not "does that object exist". Combine with `reference-finder.py` / structural checks when an existence question also needs answering.

## Provenance

Built and validated while auditing a real-world 1C configuration extension — a concrete misclassification motivated this tool: a wholly-new report was grouped by one analysis into the same functional block as unrelated subdivision-tracking objects purely because of a shared name suffix. Running this tool against the report showed its query actually aggregates data from unrelated payroll/bookkeeping accumulation registers and does not reference the subdivision-tracking objects at all — confirmed by the customer, in a separate round of the same audit, as the actual answer to an unrelated open question about a bookkeeping adaptation. No specifics identifying the extension are reproduced here, to avoid disclosing details of a third party's codebase.
