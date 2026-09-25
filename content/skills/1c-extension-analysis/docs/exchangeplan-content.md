# Exchange Plan Content — Composition Inspector / Differ

Inspects and/or diffs the composition (`Ext/Content.xml`) of a 1C exchange plan (ПланОбмена) — including RIB (Обмен в распределенной информационной базе). General-purpose: works on any single source tree, or two trees at once (typically base config vs extension, but any two trees work — the tool has no notion of "which side is the extension").

## Why this exists

Neither `cfe-diff -Mode A` nor `reference-finder.py` reads exchange-plan content. `cfe-diff` classifies `ObjectBelonging` for attributes/tabular sections/forms — the exchange plan's `Content.xml` is a separate XML file (`Ext/Content.xml`) outside that model entirely. None of the project's MCP tools read it either (verified: no mention of `ExchangePlan`/`ПланОбмена` in any module of `1c-graph-metadata-mcp`, text or binary — it only sees exchange plans as generic `MetadataObject` nodes with no composition data). For any extension that touches RIB or another exchange plan, "which objects participate, and did the extension change that" was previously answerable only by opening the XML by hand.

## Platform grounding (verified before writing this tool)

- `Ext/Content.xml` is the source-dump form of `СоставПланаОбмена` (`ExchangePlanContent`) — confirmed via `1c_help_mcp docsearch`. Each `<Item>` pairs a `<Metadata>Type.Name</Metadata>` ref with `<AutoRecord>Allow|Deny</AutoRecord>` (platform type `АвтоРегистрацияИзменений` has exactly these two values).
- **`AutoRecord=Deny` does not mean "excluded from the plan"** — it means automatic change-tracking is off for that object *in this plan*. The object is still nominally part of the plan's content. Confirmed via `1c-ssl-mcp ssl_search`: standard БСП (SSL) dispatchers (`ОбменДаннымиСобытия.МеханизмРегистрацииОбъектовПередЗаписьюРегистра` / `...ПередЗаписьюДокумента`), wired through `EventSubscriptions`, call `ОбменДаннымиСобытия.ВыполнитьПравилаРегистрацииДляОбъекта(...)`, which reads a separate **registration-rules template** owned by the plan itself (`Templates/ПравилаРегистрации`) to decide which nodes get the change. `ОбменВРаспределеннойИнформационнойБазе` specifically is a БСП-provided RIB plan (its `ПриНастройкеПодчиненногоУзлаРИБ` override point is a documented БСП extension hook, not a customer invention).
- **The registration-rules template mixes data (the rules) with code** (the BSP dispatcher plus whatever module code the rules invoke) — this tool does **not** parse or diff that template's content. It only detects the template's presence and flags candidate `.bsl` locations (literal plan-name mentions) for manual reading. Treating "no template" or "no code mention found" as proof of "no registration mechanism" is exactly the kind of unverified claim this skill's tooling exists to avoid — don't make it.
- **Confirmed by reading the actual code (not a hypothesis): the template is not even always consulted.** The BSP dispatcher (`ОбменДаннымиСобытия.ВыполнитьПравилаРегистрацииОбъектовДляПланаОбменаПопыткаИсключение`) reads the template's rules for the object's metadata type, and **if zero rules come back** (`ПравилаРегистрацииОбъекта.Количество() = 0`), it falls through to a **hardcoded per-object BSL dispatch** (`Если ОбъектМетаданных = Метаданные.X.Y Тогда ...`) instead of the template — confirmed by reading a real extension's own interceptor of this exact procedure, a long `Если/ИначеЕсли` chain covering dozens of specific objects. This means **`Content.xml`'s `AutoRecord` value alone can never tell you which path (template rules vs. hardcoded BSL) a given object actually takes** — for any object you need a real answer on, you must read both the template *and* this dispatcher's body (including any extension interceptor on it via `&ИзменениеИКонтроль`). The tool surfaces this dispatcher's location (see `find_bsp_dispatch_hits` output below) precisely so you don't have to discover it by reading a long stretch of unrelated code first.
- **Content declarations appear to be per-tree and additive, not a full replacement snapshot.** Verified empirically on a real extension: every single item in the extension's own `Content.xml` was itself an object added by that extension, with no overlap against the base's (much larger) own list. This means an item present only in the base's `Content.xml` is *not* evidence the extension removed it — it most likely just means the extension didn't need to re-declare it. Only an item present in **both** trees with a **different** `AutoRecord` value is an unambiguous override.

## Usage

```bash
# Inspect one tree only
python3 content/skills/1c-extension-analysis/tools/1c-exchangeplan-content/scripts/exchangeplan-content.py \
    -Plan "ОбменВРаспределеннойИнформационнойБазе" \
    -BasePath <path-to-base-config-source-dump>

# Diff base vs extension
python3 content/skills/1c-extension-analysis/tools/1c-exchangeplan-content/scripts/exchangeplan-content.py \
    -Plan "ОбменВРаспределеннойИнформационнойБазе;;ОбменСообщениями" \
    -BasePath <path-to-base-config-source-dump> \
    -ExtPath <path-to-extension-source-dump> \
    -NewObjects "InformationRegister.НовыйРегистр;;Document.НовыйДокумент"
```

| Parameter | Description | Default |
|---|---|---|
| `Plan` | One or more exchange plan names, `;;`-separated | — (required) |
| `BasePath` | Path to a source tree (base config, or any tree) | at least one of `BasePath`/`ExtPath` required |
| `ExtPath` | Path to a second source tree (extension, or any tree) | at least one of `BasePath`/`ExtPath` required |
| `NewObjects` | Optional cross-check list, `;;`-separated `Type.Name` entries (same format as `Content.xml`'s `<Metadata>` and as `reference-finder.py -Object`) — flags any entry absent from both trees' content | none |

Supplying only one of `BasePath`/`ExtPath` runs Inspect-only for that tree. Supplying both also runs the Diff section.

## Output

**Per tree (Inspect):**
- Item count and full list (`Metadata — AutoRecord=...`), or "Content.xml not found" if the plan isn't present/adopted in that tree.
- Whether `Templates/ПравилаРегистрации` exists — presence/absence only, content is never parsed.
- **Tree-wide (plan-independent) locations of the standard BSP registration-dispatch procedures** (`ВыполнитьПравилаРегистрацииОбъектовДляПланаОбмена*`, `МеханизмРегистрацииОбъектовПередЗаписью*`) with `file:line:text` — read these for **any** `AutoRecord=Deny` item above, since an empty rule set for that object's type falls through to hardcoded BSL here instead of the template (confirmed by reading code — see the platform-grounding note above). Computed once per tree and cached, even when `-Plan` lists several plans.
- Literal `.bsl` mentions of the plan name (candidate registration/query code) with `file:line:text` — a starting point for manual reading, not a verified finding.

**Diff (only when both paths given):**
- Items declared only in the extension's own `Content.xml` (its own additions).
- Items declared only in the base's `Content.xml`, capped at 20 with a count of the rest — explicitly labeled as *not* evidence of removal (see the additive-declaration note above).
- Items whose `AutoRecord` differs between the two trees — the only genuine, unambiguous override signal this tool produces.
- If `-NewObjects` was supplied: which of those refs are missing from both trees' combined content.

## Known gaps

- Does not parse `Templates/ПравилаРегистрации` at all — presence-only detection. For any `AutoRecord=Deny` item where you need to know *which nodes* actually receive it, read the template and the BSL it invokes directly.
- The `.bsl` code-hit search is a literal, word-bounded string match on the plan name — it will miss registration wiring that references the plan through a variable or a parameter rather than a literal name, and it does not distinguish "this is the BSP dispatcher call" from "this is an unrelated query mentioning the plan".
- Only reads `Ext/Content.xml` under `ExchangePlans/<Name>/` — does not read the plan's own attributes, tabular sections, or forms (use `cfe-diff -Mode A` / `get_object_dossier` for those).

## Provenance

Built after confirming — via direct XML inspection plus `1c_help_mcp`/`1c-ssl-mcp` cross-checks — that none of the MCP servers this skill's "MCP usage" section covers (`onec-hbk-bsl-*`, `1c-code-metadata-mcp`, `1c-graph-metadata-mcp`) parses exchange-plan content at all. Validated against a real-world extension that genuinely modified RIB participation for its own new objects. No specifics about that extension are reproduced here, to avoid disclosing details of a third party's codebase.
