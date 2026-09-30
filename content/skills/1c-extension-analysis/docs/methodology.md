# Extension Analysis — Methodology

The discipline that keeps an extension analysis honest and complete. It binds every run of this skill — the full audit delegated to `1c-extension-analyst` and a narrow inline question alike. Read it before the first step of [SKILL.md → Workflow](../SKILL.md#workflow); the workflow, tool list and report skeleton live there and are not repeated here.

## Non-negotiable rules

1. **Per-child `ObjectBelonging`, never "is `<ChildObjects>` open".** An object's child list is open whenever it contains *any* children, even when every single one is `ObjectBelonging=Adopted`. Run `cfe-diff -Mode A` (see `SKILL.md → Workflow`, step 1) for the own-vs-borrowed count per object; never infer "new attribute" from an open tag alone. Repeating this mistake is a defect, not a stylistic choice.
2. **Adoption without content is not automatically "unexplained" or "dead".** Before calling an adopted, zero-content object a candidate for removal, run the reference finder ([reference-finder.md](reference-finder.md)). An object can be legitimately adopted for a composite-type reference (hard platform requirement) or a code/query reference (including DCS queries embedded in report XML, not just `.bsl`) — both count as "explained". Only report "candidate for exclusion" when neither mechanism, nor the object's own Ext content, turns anything up — and say so with the same hedge the tool prints (form layouts, subsystem/role composition lists are outside its scan).
3. **Completeness sweep is mandatory before writing conclusions.** Enumerate every object in the extension that has *any* `Ext` subfolder (real code/forms/templates) and check each one lands somewhere in the report — a named functional block, a "confirmed no effect" note, or an open question. Do not declare the analysis finished on the strength of customer-supplied reasons alone; customer input tells you *where to start looking*, not the boundary of what to look for. A report that omits an object with real code because "the customer didn't mention it" is incomplete.
4. **Distinguish "customer said" from "code confirms".** Every claim in the report is one of: confirmed by reading the extension's own code/metadata, confirmed by cross-referencing the base configuration source (when available), stated by the customer as context (mark it "уточнено заказчиком" and do not silently upgrade it to a proven fact), or genuinely unverified (goes in section 4/5, not asserted as fact elsewhere). When a customer-provided reason turns out contradicted by the code (e.g. "this register was never changed" but the code shows an active interceptor), say so plainly and correct the report — do not average the two into a vague middle position.
5. **A comment field is not evidence of intent.** `<Comment>` values embedded by the extension author (a question, a note, a "TODO") are hypotheses to verify, not conclusions — cross-check against the base configuration's own comment on the same object before treating an author's remark as fact (a naming-convention lint code and a genuine "delete this" note look similar out of context).
6. **Enum/constant references can be silently broken.** When code sets an enum value, dimension, or constant by dotted reference (`Перечисления.X.Y`), confirm `Y` actually exists in the enum's metadata (extension or base) before treating the code as functioning — a reference to a non-existent value is a real, reportable defect, not a hypothetical.
7. **A shared interceptor/procedure name is a hypothesis, not proof of a shared implementation.** When several objects expose the same interceptor name (e.g. one `&После("ПриЗаписи")` interceptor name on a dozen documents), do not conclude they all implement "the same uniform pattern" from the name match alone — **read the body of every single one**, including the ones that look boring or unlikely to differ. One of many objects sharing an interceptor name can call a completely different — even broken — mechanism: grouping by name alone misses it, and a report asserting "no discrepancies" is then contradicted by the one body nobody read. Treat "N objects, same procedure name" as N things to verify, not one thing to describe once. If a BSL symbol-index MCP (`onec-hbk-bsl-*` or equivalent) is exposed, use `bsl_find_symbol` to enumerate every definition in one call instead of grepping — and `bsl_callers`/`bsl_callees` (with `file_filter` when the name is shared) to trace where each one is called from — but no index tells you what a body actually does, so reading every file is still on you.
8. **`bsl_meta_object` (or any similar MCP metadata-shape tool) is not `ObjectBelonging`-aware — do not trust its attribute list as evidence of what the extension added.** It returns an object's attributes with no adoption flag, identically against the extension's index and the base configuration's. Only `cfe-diff -Mode A` / manual per-child `ObjectBelonging` reading are authoritative for "did the extension add this" — see [SKILL.md → MCP usage](../SKILL.md#mcp-usage) for what each MCP family can and cannot be used for.
9. **`1c-graph-metadata-mcp`'s `compare_base_and_extension` is a cross-check, not the inventory.** It does not read `ObjectBelonging`: it compares the base and extension layers of one graph project as two node sets by name, so it fails independently of `cfe-diff -Mode A` — which is what makes agreement between the two meaningful and a disagreement worth reading the XML for. It needs a graph that holds both layers; when the extension is not among the ingested layers, fall back to `cfe-diff -Mode A` / `reference-finder` as usual. Routing, the layer name to pass and how to attribute a graph hit to the extension — `SKILL.md → MCP usage → 1c-graph-metadata-mcp`.
10. **Exchange-plan (RIB) composition is invisible to every MCP tool — use `1c-exchangeplan-content` instead.** None of the MCP families parse `Ext/Content.xml`; they only see exchange plans as generic metadata objects with attributes/forms, never their actual composition. If the extension touches RIB (`ОбменВРаспределеннойИнформационнойБазе`) or any other exchange plan, run `1c-exchangeplan-content` ([exchangeplan-content.md](exchangeplan-content.md)) to see what it declared. Three traps specific to this mechanism:
    - `AutoRecord=Deny` does **not** mean "excluded from the plan" — it only disables automatic change-tracking.
    - Content declarations are additive per-tree, not a replacement snapshot — an item present only in the base's `Content.xml` is not evidence the extension removed it.
    - **The registration-rules template (`Templates/ПравилаРегистрации`) is not even always consulted.** The BSP dispatcher (`ОбменДаннымиСобытия.ВыполнитьПравилаРегистрацииОбъектовДляПланаОбменаПопыткаИсключение`) reads the template's rules for the object's type and, if none come back, falls through to a **hardcoded per-object BSL dispatch** instead — typically an extension's `&ИзменениеИКонтроль` interceptor of this exact procedure, a long `Если ОбъектМетаданных = ... Тогда` chain. `Content.xml`'s `AutoRecord` value alone can never tell you which path a given object takes — `1c-exchangeplan-content` surfaces this dispatcher's file:line (tree-wide, plan-independent) precisely so you read the right lines instead of guessing. Do not report a RIB composition finding without running this tool and reading the dispatcher it points to.

## `CONFUSION` block vs. open question

This distinction matters more here than in most work, because the deliverable *is* a list of open questions — not every gap should interrupt the user.

- **Raise `CONFUSION`** (per `AGENTS.md → Development Procedure → 1. Think Before Coding`) only when the analysis itself cannot proceed without a decision — e.g. the extension path or base-config path is ambiguous or missing, the task scope is unclear (single object vs. whole extension), or the requested output format conflicts with the standard report skeleton.
- **Write it into the report's "open questions" section instead** for anything that is a genuine finding requiring the *customer's* (not the invoking user's) business knowledge to resolve — "is this integration still used", "was this scoping decision intentional", "should this obsolete code be removed". These are exactly the kind of question the report exists to surface; do not block the deliverable on them, and do not ask the invoking user to guess on the customer's behalf.
- If a finding is definitively resolvable from code alone (an enum value that provably does not exist, a query that provably never runs, a reference that provably does or does not exist), resolve it and state the conclusion — do not downgrade a code-provable fact into an open question out of caution.

## Report discipline

- Follow the section skeleton (0–7) from [SKILL.md → Report skeleton](../SKILL.md#report-skeleton) exactly — do not invent a different structure per run; consistency is what lets a customer compare reports across extensions.
- Every object mentioned as "new" or "changed" must have been verified via per-child `ObjectBelonging` (rule 1) — not asserted from the object's name or from a ChildObjects tag alone.
- Keep section 4 (unconfirmed) and section 5 (open questions) honest: an item closed by evidence found later in the same run must be moved into a blockquote and removed from the numbered list, with the numbering of the remaining items corrected. Do not leave a stale open question that the analysis itself already answered.
- Do not pad the report with restated customer input, generic 1C platform explanations, or file-by-file dumps — every paragraph must earn its place by adding something not already stated elsewhere in the document.

## Scenarios are the spine of the report, the mechanics are its evidence

A changed object is a trace. What the reader decides with — before a configuration update, or when scoping the extension down — is **which usage scenario differs from stock, and what happens to it if the change goes away**. So section 2 is a list of scenarios, and interceptors, attributes and form elements appear underneath as what proves each one.

**A scenario is an inference, not a code fact, and it must be graded as one.** Put scenarios at the centre without grading and the report becomes convincing fiction — worse than a dry inventory, because a story does not get re-checked. Example: an extension's copy of a form shows `[visible:false]` on both write buttons, which reads as "the extension took the write buttons out of the scenario". If the base form already carries both flags and the copy holds nothing of its own, the scenario is *none* and the object is a removal candidate. Never state a scenario from one side of a diff.

### Scenario kinds — all first-class

- **Пользовательский** — a person does something in the interface.
- **Регламентный / системный** — exchange (RIB registration and its conditions), integration services, scheduled jobs, posting. A changed condition for registering an object to an exchange changes that scenario exactly as much as a new button changes a user's one; these are never a footnote to the user-facing sections.
- **Оформление документов** — what a printed or exported document looks like and which template a given organisation gets.
- **Not a scenario** — defects, dead and disabled code, traces of superseded generations. They belong in their own section, never dressed as intent.

### Evidence → scenario, with its strength

| Evidence | What it says about the scenario | Strength |
|---|---|---|
| `&Вместо` | the stock scenario is replaced outright | direct; the largest update-time risk |
| `#Вставка` inside `&ИзменениеИКонтроль` | the scenario is extended at one point | direct |
| own attribute + form element + handler | new data a person enters or sees | direct |
| own command / button | a new action available to a person | direct |
| own register + scheduled job | a background scenario (notifications, exchange) | direct |
| a branch added to a registration dispatcher, or entries added to an exchange plan's content | the exchange scenario's conditions changed | direct |
| a **typical** element hidden or made read-only | a step was taken out of the stock scenario | indirect |
| an **own** element hidden or read-only | a reference panel was added — **not** the same finding | indirect |
| adopted, no own content at all | **no scenario** → removal candidate | direct |
| adopted, XML identical to base, but it carries a module | the scenario is in code, the interface is untouched | direct |

The ownership column of the two "hidden element" rows is what keeps them apart, and it is easy to lose: the hidden-element signal can mean *own* read-only tables, not a removed stock step.

### Two rules that keep the scenario list from rotting

- **An implementation detail attaches to the scenario it serves and never becomes one.** Many copies of the same helper are the mechanics of one scenario, not many scenarios. Otherwise the scenario report bloats exactly as the mechanical one did.
- **Absence of change is a finding.** An adopted form whose XML matches the base tells the reader what they will see: nothing. State it; do not bury it as a technical detail.

### The report feeds specification work — write it so the lift is mechanical

There is usually no other source of requirements for an extension like this, so the report is the seed for `openspec/specs/`. That workspace (where the project rules put it) fixes the shape: one folder per capability holding one `spec.md`, `### Requirement: <name>` carrying a normative MUST/SHALL statement, and `#### Scenario: <name>` written as `GIVEN` / `WHEN` / `THEN` / `AND` bullets. Load `content/rules/sdd-integrations.md` before writing anything there; specs are updated through a change proposal, not by editing `specs/` by hand.

Map the report onto that shape directly:

| Report | Spec |
|---|---|
| functional block (section 2.x) | capability folder, one `spec.md` |
| the scenario's normative statement | `### Requirement:` — MUST/SHALL, concrete metadata names |
| the scenario itself | `#### Scenario:` — GIVEN precondition, WHEN action, THEN observable result |
| evidence lines (file:line) | the artifact's closing `## Context sources` block, compact |
| open question for the customer | stays a question — a requirement is never authored from a guess |

Because OpenSpec refuses vague requirements (no `<TBD>`, no "по необходимости", no invented metadata names), a scenario that cannot be written with concrete object and attribute names is not ready to be a requirement — that is a signal the analysis is unfinished, not a licence to hedge in the spec.

So each scenario in the report carries: a stable id, a short name, the stock behaviour, what the extension makes it, the kind, a GIVEN/WHEN/THEN draft in the customer's language, the evidence (file:line, each marked direct or indirect), **two separate gradings** (below), and what breaks for the user or the system if the change is removed.

### Grade behaviour and purpose on two scales, never on one

Code proves *what the system does*. It never proves *why anyone wanted it*. Collapsing both into one "confidence" column produces a report that reads more certain than it is — and a run with no customer input at all then reports zero scenarios needing customer confirmation, which is false by construction.

- **Поведение** — `подтверждено кодом` / `вероятно` (the mechanism is only partly read) / `не проверено`.
- **Назначение** — `подтверждено заказчиком` (traceable to a numbered item of the customer's input) / `выведено из кода` (the analyst's inference, however plausible) / `противоречит словам заказчика` / `заказчик не упоминал`.

Rules that follow:

- A requirement may be lifted into a spec when **поведение = подтверждено кодом**. That is what a spec records: current behaviour.
- A purpose sentence — "сделано, чтобы …" — may be stated as fact only when **назначение = подтверждено заказчиком**. Otherwise write it as the analyst's reading and mark it.
- **`заказчик не упоминал` is a finding, not a blank.** Either the extension carries a need nobody wrote down, or it carries leftovers. Both belong in the report, and neither is decided by the analyst alone.
- **`противоречит словам заказчика` stops the write-up for that scenario** and goes to the customer questions with both sides quoted: the customer's sentence and the code line. Never silently prefer either.

When the customer supplied input, section 0 holds it verbatim and numbered, and every scenario's `назначение` cites the item it rests on. When there is no input, every `назначение` is `выведено из кода` — say so once, plainly, instead of leaving the column reassuringly empty.
