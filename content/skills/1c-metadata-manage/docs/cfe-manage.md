# 1C Extension Manage — Init, Borrow, Diff, Patch, Validate, Build

Comprehensive extension (CFE) management: create scaffold, borrow objects from configuration, analyze changes, generate method interceptors, validate correctness, compile XML sources to a deliverable `.cfe`.

---

## 1. Init — Create Extension Scaffold

```powershell
powershell.exe -NoProfile -File skills/1c-metadata-manage/tools/1c-cfe-manage/scripts/cfe-init.ps1 -Name "МоёРасширение"
```

| Parameter | Description | Default |
|-----------|-------------|---------|
| `Name` | Extension name (required) | — |
| `Synonym` | Synonym | = Name |
| `NamePrefix` | Prefix for own objects | = Name + "_" |
| `OutputDir` | Output directory | `src` |
| `Purpose` | `Patch` / `Customization` / `AddOn` | `Customization` |
| `Version` | Extension version | — |
| `Vendor` | Vendor | — |
| `CompatibilityMode` | Compatibility mode | `Version8_3_24` |
| `NoRole` | Without main role | false |

### What Gets Created

```
<OutputDir>/
├── Configuration.xml         # Extension properties
├── Languages/
│   └── Русский.xml           # Language (borrowed)
└── Roles/                    # If not -NoRole
    └── <Prefix>ОсновнаяРоль.xml
```

**Preparation**: Before creating, get the base configuration version: `1c-cf-manage info <ConfigPath>`.

---

## 2. Borrow — Borrow Objects from Configuration

```powershell
powershell.exe -NoProfile -File skills/1c-metadata-manage/tools/1c-cfe-manage/scripts/cfe-borrow.ps1 -ExtensionPath src -ConfigPath <config> -Object "Catalog.Контрагенты"
```

| Parameter | Description |
|-----------|-------------|
| `ExtensionPath` | Path to extension directory (required) |
| `ConfigPath` | Path to source configuration (required) |
| `Object` | What to borrow (required), batch via `;;` |

Format: `Catalog.X`, `CommonModule.Y`, `Document.Z`. All 44 object types supported. Batch: `"Catalog.X ;; CommonModule.Y ;; Enum.Z"`.

Creates XML files with `ObjectBelonging=Adopted` and `ExtendedConfigurationObject`, adds to ChildObjects.

---

## 3. Diff — Analyze Extension Changes

```powershell
powershell.exe -NoProfile -File skills/1c-metadata-manage/tools/1c-cfe-manage/scripts/cfe-diff.ps1 -ExtensionPath src -ConfigPath <config> -Mode A
```

| Parameter | Description | Default |
|-----------|-------------|---------|
| `ExtensionPath` | Path to extension (required) | — |
| `ConfigPath` | Path to configuration (required) | — |
| `Mode` | `A` (overview) / `B` (transfer check) | `A` |

**Mode A** — overview: For each object shows `[BORROWED]` (interceptors, own attributes/TS/forms) or `[OWN]` (counts).

**Mode B** — transfer check: For each `&ИзменениеИКонтроль`, extracts `#Вставка`/`#КонецВставки` blocks and searches for them in the configuration module. Statuses: `[TRANSFERRED]`, `[NOT_TRANSFERRED]`, `[NEEDS_REVIEW]`.

---

## 4. Patch — Generate Method Interceptor

```powershell
powershell.exe -NoProfile -File skills/1c-metadata-manage/tools/1c-cfe-manage/scripts/cfe-patch-method.ps1 -ExtensionPath src -ModulePath "Catalog.Контрагенты.ObjectModule" -MethodName "ПриЗаписи" -InterceptorType Before
```

| Parameter | Description | Default |
|-----------|-------------|---------|
| `ExtensionPath` | Path to extension (required) | — |
| `ModulePath` | Module path (required) | — |
| `MethodName` | Method to intercept (required) | — |
| `InterceptorType` | `Before` / `After` / `ModificationAndControl` (required) | — |
| `Context` | Context directive | `НаСервере` |
| `IsFunction` | Method is a function (adds `Return`) | false |

### ModulePath Format

| ModulePath | File |
|------------|------|
| `Catalog.X.ObjectModule` | `Catalogs/X/Ext/ObjectModule.bsl` |
| `Catalog.X.ManagerModule` | `Catalogs/X/Ext/ManagerModule.bsl` |
| `Catalog.X.Form.Y` | `Catalogs/X/Forms/Y/Ext/Form/Module.bsl` |
| `CommonModule.X` | `CommonModules/X/Ext/Module.bsl` |

### Interceptor Types

| Type | Decorator | Purpose |
|------|-----------|---------|
| `Before` | `&Перед` | Code before the original method call |
| `After` | `&После` | Code after the original method call |
| `ModificationAndControl` | `&ИзменениеИКонтроль` | Copy of method body with `#Вставка`/`#Удаление` markers |

**Prerequisite**: Object must be borrowed first (`cfe-borrow`).

---

## 5. Validate — Check Extension Correctness

```powershell
powershell.exe -NoProfile -File skills/1c-metadata-manage/tools/1c-cfe-manage/scripts/cfe-validate.ps1 -ExtensionPath src
```

### Checks (9 steps)

| # | Check | Severity |
|---|-------|----------|
| 1 | XML well-formedness, MetaDataObject/Configuration, version | ERROR |
| 2 | InternalInfo: 7 ContainedObject, valid ClassId | ERROR |
| 3 | Extension properties: ObjectBelonging=Adopted, Name, Purpose, NamePrefix, KeepMapping | ERROR |
| 4 | Enum values: CompatibilityMode, DefaultRunMode, ScriptVariant, InterfaceCompatibilityMode | ERROR |
| 5 | ChildObjects: valid types (44), no duplicates, canonical order | ERROR/WARN |
| 6 | DefaultLanguage references Language in ChildObjects | ERROR |
| 7 | Language files exist | WARN |
| 8 | Object directories exist | WARN |
| 9 | Borrowed objects: ObjectBelonging=Adopted, ExtendedConfigurationObject UUID | ERROR/WARN |

Exit code: 0 = OK, 1 = errors.

---

## 6. Build — Compile Extension XML Sources to `.cfe`

```powershell
powershell.exe -NoProfile -File skills/1c-metadata-manage/tools/1c-cfe-manage/scripts/cfe-build.ps1 -ExtensionPath src -BaseCfFile base/actual.cf -OutputFile build/МоеРасширение.cfe
```

Builds a compiled `.cfe` file from extension XML sources via a **throwaway local infobase** — no persistent/shared infobase is touched. Unlike `1c-epf-build` (which compiles EPF/ERF through a single Designer command, `/LoadExternalDataProcessorOrReportFromFiles`), extensions have no such shortcut: the platform must actually load the extension into a real infobase to compile it, then dump the result.

| Parameter | Required | Description |
|-----------|:--------:|-------------|
| `-ExtensionPath` (alias `-Path`) | yes | Path to the extension XML source directory (contains `Configuration.xml`) |
| `-BaseCfFile` | conditional | Compiled base configuration (`.cf`) to load into the throwaway infobase before the extension. **Required whenever the extension has borrowed (`ObjectBelonging=Adopted`) objects** — see below. |
| `-V8Path` | no | Platform `bin/` directory or path to `1cv8`/`1cv8.exe` (auto-detected if omitted) |
| `-BasePath` | no | Throwaway infobase directory, **recreated on every run** (default: `base/empty`) |
| `-OutputFile` | no | Output `.cfe` path (default: `build/<ExtensionName>.cfe`) |
| `-ExtensionName` | no | Value passed to `-Extension` (default: read from `Configuration.xml`'s `<Name>` — usually differs from the source directory name, e.g. dir `zup30_ИсправлениеКонфигурации`, name `ИсправлениеКонфигурации`) |
| `-UserName` / `-Password` | no | Credentials for the throwaway infobase |

### Why `-BaseCfFile` is (usually) required

Verified empirically: loading an extension with adopted objects into a **truly empty** infobase (no base configuration at all) fails at the platform level with dozens-to-hundreds of `Не найден объект <Тип>.<Имя>` errors and a non-zero exit code — every reference to a base-configuration object (subsystems, style elements, common pictures, catalogs, documents, registers, …) is unresolved. A standalone extension with zero adopted objects can omit `-BaseCfFile` and build against a genuinely empty base.

**Keep the `.cf` fresh.** `-BaseCfFile` must match the configuration version the extension was borrowed from — a stale `.cf` (wrong `NamePrefix`/UUID generation for objects added or removed since) will produce the same "object not found" failures or, worse, a `.cfe` that silently drops references. Rebuild it from the current XML source when in doubt:

```powershell
powershell.exe -NoProfile -File skills/1c-metadata-manage/tools/1c-db-ops/scripts/db-create.ps1 -InfoBasePath base/empty
powershell.exe -NoProfile -File skills/1c-metadata-manage/tools/1c-db-ops/scripts/db-load-xml.ps1 -InfoBasePath base/empty -ConfigDir <path-to-main-config-src> -Mode Full -UpdateDB
powershell.exe -NoProfile -File skills/1c-metadata-manage/tools/1c-db-ops/scripts/db-dump-cf.ps1 -InfoBasePath base/empty -OutputFile base/actual.cf
```

### What it does internally

1. Recreates the infobase at `-BasePath` (`db-create`).
2. *(if `-BaseCfFile` given)* Loads the base configuration (`db-load-cf`) and applies it to the database (`db-update`).
3. Loads the extension XML source as an extension (`db-load-xml -Mode Full -Extension <name> -UpdateDB`).
4. Dumps the compiled extension (`db-dump-cf -Extension <name> -OutputFile <path>`).

Each step reuses the corresponding `1c-db-ops` script — `cfe-build` is a thin orchestrator, not a reimplementation. The throwaway infobase is **not** deleted after a successful build (left behind for inspection); the next run wipes and recreates it.

---

## Typical Extension Workflow

```
1c-cf-manage info <config>          — get base config version/compatibility
1c-cfe-manage init                  — create extension scaffold
1c-cfe-manage borrow               — borrow objects to modify
1c-cfe-manage patch                 — generate interceptors
1c-cfe-manage validate              — check correctness
1c-cfe-manage diff -Mode A          — review changes overview
1c-cfe-manage diff -Mode B          — check transfer status
1c-cfe-manage build                 — compile to a deliverable .cfe
```

## Recent Additions (upstream `w-2026-05-17`)

The PowerShell scripts under `tools/1c-cfe-manage/scripts/` were refreshed from [Nikolay-Shirokov/cc-1c-skills](https://github.com/Nikolay-Shirokov/cc-1c-skills). Highlights:

### `cfe-borrow` — borrowing forms now matches Configurator output

- The borrowed form gets the **complete `ChildItems` tree** (not the previously empty skeleton). Loadable into the target base without manual XML fixes for complex ERP forms.
- **Dependencies are auto-borrowed**: shared pictures, style elements, enums, and enum values used by the borrowed form. No more cascade of "object not found" errors after the first load.
- `DataPath`, `Events`, `TitleDataPath`, `TypeLink`, `CommandName` are stripped from the borrowed form (these caused "invalid data path" / "event not loaded" errors on real ERP forms, also for command-bar buttons).
- Form-level properties (`AutoTitle`, `WindowOpeningMode`, …) are preserved both in the main section and in `BaseForm`.
- **`-BorrowMainAttribute`** (`Form` or `All`) — borrows the form's main attribute (`Object`) and transitively all its attributes, tabular sections, and dependent types. Closes the manual-collection workflow when adding an attribute to a borrowed form.

### `cfe-validate`

- New checks for borrowed-form structure, their dependencies (shared pictures, style elements, enums), and the extension's own subobjects (attributes, tabular sections, enum values, forms).
- False positives removed: `DataPath` / `TitleDataPath` inside `BaseForm` are correct (Configurator emits them); the extension's own subobjects (own attributes, own enum values) are no longer validated as borrowed.

### `cfe-init`

- Interface mode and compatibility mode are inherited from the base configuration (resolved via `-ConfigPath`). The extension matches the base's behaviour by default.

### `cfe-patch-method`

- Accepts plural type names (`Catalogs` → `Catalog`).
- Python port: no extra blank lines in generated modules.

## MCP Integration

- **get_object_dossier** — Comprehensive structural passport of the base object before borrowing (structure, forms, dependencies, code modules, roles).
- **metadatasearch** — Find objects to borrow and verify module paths.
- **get_metadata_details** — Get full object structure for objects being borrowed.
- **search_code** — Find methods to intercept (prefer over `codesearch`; supports semantic/fulltext/hybrid search with detail levels L0–L3).
- **codesearch** — Find methods in raw BSL files (fallback when `search_code` is not available).
- **metadatasearch** (`names_only=true`) — Find similar metadata objects for extension XML reference.
- **compare_base_and_extension** — Structural diff between base and extension after borrowing: attributes, forms, and routines added/overridden/unchanged.
- **trace_impact** — Recursive impact analysis of extension changes on the base configuration (preferred over `graph_dependencies` for deep dependency chains).
- **graph_dependencies** — Flat dependency overview before borrowing.
- **syntaxcheck** — Verify generated BSL code.

## SDD Integration

When creating extensions as part of a feature, update SDD artifacts if present (see `content/rules/sdd-integrations.md` for detection):

- **OpenSpec**: Document borrowed objects, interceptors, and extension scope in spec deltas under `openspec/changes/`.
